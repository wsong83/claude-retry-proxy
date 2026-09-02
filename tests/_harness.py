"""Shared test infrastructure for the claude-retry-proxy suite.

Module-scope environment isolation (trace file, state file, and the
compatibility state file) is applied here before any server module
import, so tests never touch the user's live ~/.claude files. Also
hosts the shared runner (run_cli) used by the aggregator and by each
standalone cluster module.
"""


import argparse
import http.server
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid




# Tests must never write into the user's live proxy trace. server.py binds
# PROXY_TRACE_FILE at import time (in-process transforms log via log_trace),
# and subprocess spawn helpers inherit the test runner's env via
# os.environ.copy(). Force it to a session temp file before any server module
# is imported, so both routes stay isolated from ~/.claude/logs.
os.environ["PROXY_TRACE_FILE"] = os.path.join(
    tempfile.gettempdir(), "claude-retry-proxy-test-trace.jsonl")



# Same isolation for the CLI/state file. cli.py and server.py read
# PROXY_STATE_FILE from the env (added 2026-08-28 to fix the
# test-suite-kills-live-proxy hazard). Force it to a session temp path before
# any CLI subprocess or server module is spawned, so the dummy proxies the
# tests launch read/write an isolated state file and can never stop or touch
# the live proxy's ~/.claude/proxy/proxy-state.json.
os.environ["PROXY_STATE_FILE"] = os.path.join(
    tempfile.gettempdir(), "claude-retry-proxy-test-state.json")




# ---------------------------------------------------------------------------
# Test infrastructure
# ---------------------------------------------------------------------------

CLAUDE_PROXY = [sys.executable, "-m", "claude_retry_proxy.cli"]


PROXY_SERVER = [sys.executable, "-m", "claude_retry_proxy.server"]



SETTINGS_FILE = os.path.join(os.path.expanduser("~"), ".claude", "settings.json")


PROXY_DIR = os.path.join(os.path.expanduser("~"), ".claude", "proxy")


# Isolated test state path (set above); must match what cli.py/server.py read
# from PROXY_STATE_FILE so CLI subprocesses and the tests' own checks agree.
PROXY_STATE_FILE = os.environ["PROXY_STATE_FILE"]


URL_LOCK_FILE = os.path.join(PROXY_DIR, "base-url.lock")


URL_SWAP_LOCK_FILE = os.path.join(PROXY_DIR, "url-swap.lock")



errors = []


warnings_list = []




def fail(msg):
    errors.append(msg)
    print(f"  FAIL: {msg}")




def warn(msg):
    warnings_list.append(msg)
    print(f"  WARN: {msg}")




def info(msg):
    print(f"  INFO: {msg}")




def pass_(msg):
    print(f"  PASS: {msg}")




def cleanup_lock_files():
    """Remove proxy lock files left from previous test runs."""
    for f in [URL_LOCK_FILE, URL_SWAP_LOCK_FILE]:
        try:
            os.remove(f)
        except OSError:
            pass




def _backup_proxy_state():
    """Back up proxy-state.json, return backup content or None."""
    if os.path.exists(PROXY_STATE_FILE):
        with open(PROXY_STATE_FILE) as f:
            return f.read()
    return None




def _restore_proxy_state(backup):
    """Restore proxy-state.json from backup, or delete if None."""
    if backup is not None:
        os.makedirs(PROXY_DIR, exist_ok=True)
        with open(PROXY_STATE_FILE, "w") as f:
            f.write(backup)
    else:
        try:
            os.remove(PROXY_STATE_FILE)
        except OSError:
            pass




def _cli_start_with_plain_keys(port, config_path, keys_path, trace_file):
    """Start proxy via CLI with plain keys. Returns (proc, stdout, stderr, returncode)."""
    cmd = CLAUDE_PROXY + [
        "start", "--port", str(port),
        "--config-path", config_path,
        "--keys-path", keys_path,
        "--log", trace_file
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            stdin=subprocess.PIPE, text=True)
    # Close stdin — plain keys, no passphrase needed
    try:
        proc.stdin.close()
    except OSError:
        pass
    try:
        stdout, stderr = proc.communicate(timeout=30)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        return proc, "", "", "timeout"
    return proc, stdout, stderr, proc.returncode




def start_proxy(port=19876, extra_args=None, timeout=30):
    """Start proxy via claude-retry-proxy start. Returns (proc, stdout, stderr, returncode)."""
    cmd = CLAUDE_PROXY + ["start", "--port", str(port)]
    if extra_args:
        cmd.extend(extra_args)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        return None, None, None, "timeout"
    return proc, stdout.strip(), stderr.strip(), proc.returncode




def stop_proxy(timeout=30):
    """Stop proxy via claude-retry-proxy stop."""
    proc = subprocess.run(
        CLAUDE_PROXY + ["stop"],
        capture_output=True, text=True, timeout=timeout
    )
    return proc.stdout.strip(), proc.stderr.strip(), proc.returncode




def proxy_status():
    """Get proxy status via claude-retry-proxy status."""
    proc = subprocess.run(
        CLAUDE_PROXY + ["status"],
        capture_output=True, text=True, timeout=10
    )
    return proc.stdout.strip(), proc.stderr.strip(), proc.returncode




# ---------------------------------------------------------------------------
# Utility: find free port
# ---------------------------------------------------------------------------

def find_free_port():
    """Find a free TCP port."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port




# ===========================================================================
# Test Case 4: Concurrent Requests
# ===========================================================================

def _derive_models_from_tiers(tiers):
    """Derive a provider-keyed models catalog from tier mappings.

    Each tier's configured model is listed under its provider. Used so that
    generated configs satisfy the models-per-provider startup validation
    (every provider in keys-index.json needs >=1 model in config.models).
    """
    models = {}
    for tier in tiers.values():
        if isinstance(tier, dict) and tier.get("provider") and tier.get("model"):
            models.setdefault(tier["provider"], []).append(tier["model"])
    return {provider: sorted(set(names)) for provider, names in models.items()}




def _models_for_vendors(tiers, vendors):
    """Provider-keyed models catalog covering every vendor in keys-index.json.

    The proxy's startup validation requires each provider in keys to have at
    least one model in config.models. Models from the tiers cover the providers
    those tiers reference; vendors referenced by no tier get the union of all
    configured model names (the catalog content only drives the admin page's
    suggestion list, not routing).
    """
    derived = _derive_models_from_tiers(tiers)
    known = sorted({name for names in derived.values() for name in names})
    for vendor in vendors:
        if vendor not in derived:
            derived[vendor] = list(known)
    return derived




def _create_test_config(temp_dir, tiers, models=None):
    """Create a temp config.json with tier mappings.

    Args:
        temp_dir: Directory to create config.json in
        tiers: Dict mapping tier names to {provider, model}
        models: Optional dict mapping provider names to model lists. When None,
            a provider-keyed catalog is derived from the tier mappings so the
            config passes models-per-provider startup validation.

    Returns:
        Path to created config.json
    """
    if models is None:
        models = _derive_models_from_tiers(tiers)
    config = {
        "tiers": tiers,
        "models": models
    }
    path = os.path.join(temp_dir, "config.json")
    with open(path, "w") as f:
        json.dump(config, f)
    return path




def _create_test_keys(temp_dir, vendors, passphrase="test-passphrase"):
    """Create an encrypted keys-index.json for testing.

    Encrypts using vim blowfish2 format (VimCrypt~03!) compatible with vimcrypt.decrypt.

    Args:
        temp_dir: Directory to create keys-index.json in
        vendors: Dict mapping vendor names to {url, key}
        passphrase: Passphrase to encrypt with

    Returns:
        Path to created keys-index.json
    """
    import hashlib
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    # Prepare plaintext
    keys_data = json.dumps({"vendors": vendors}).encode()
    plaintext = keys_data

    # Generate random salt and seed
    salt = os.urandom(8)
    seed = os.urandom(8)

    # Derive key (same as vimcrypt._derive_key)
    digest = hashlib.sha256(passphrase.encode("utf-8") + salt).hexdigest()
    for _ in range(1000):
        digest = hashlib.sha256(digest.encode("ascii") + salt).hexdigest()
    key = bytes.fromhex(digest)

    # Encrypt using CFB-64 mode (same as vimcrypt but in reverse)
    def swap_words(block8):
        return block8[0:4][::-1] + block8[4:8][::-1]

    encryptor = Cipher(algorithms.Blowfish(key), modes.ECB()).encryptor()

    def bf_ecb(block8):
        return swap_words(encryptor.update(swap_words(block8)))

    # CFB-64 encrypt
    register = seed
    ciphertext = bytearray()
    for i in range(0, len(plaintext), 8):
        block = plaintext[i : i + 8]
        keystream = bf_ecb(register)
        encrypted_block = bytearray()
        for j, byte in enumerate(block):
            encrypted_block.append(byte ^ keystream[j])
        ciphertext.extend(encrypted_block)
        register = bytes(encrypted_block)

    # Write vim blowfish2 format
    path = os.path.join(temp_dir, "keys-index.json")
    with open(path, "wb") as f:
        f.write(b"VimCrypt~03!")  # magic
        f.write(salt)
        f.write(seed)
        f.write(bytes(ciphertext))

    return path




def _create_test_keys_plain(temp_dir, vendors):
    """Create a plain (unencrypted) keys-index.json for testing."""
    path = os.path.join(temp_dir, "keys-index.json")
    with open(path, "w") as f:
        json.dump({"vendors": vendors}, f)
    return path




def _start_proxy_server_directly(port, config_path=None, keys_path=None,
                                  passphrase="test-passphrase", trace_file=None, cwd=None,
                                  extra_env=None):
    """Start proxy server directly (not via claude-retry-proxy CLI) for testing.

    New flow: uses config.json + keys-index.json + passphrase instead of settings.json.

    Args:
        port: Port to listen on
        config_path: Path to config.json (required for new flow)
        keys_path: Path to keys-index.json (required for new flow)
        passphrase: Passphrase to decrypt keys (default: "test-passphrase")
        trace_file: Optional path for trace log
        cwd: Optional working directory

    Returns:
        (proc, probe_ok) tuple
    """
    env = os.environ.copy()
    env["PROXY_PORT"] = str(port)
    if trace_file:
        env["PROXY_TRACE_FILE"] = trace_file
    if extra_env:
        env.update(extra_env)

    extra_args = []
    if config_path:
        extra_args.extend(["--config-path", config_path])
    if keys_path:
        extra_args.extend(["--keys-path", keys_path])
    if trace_file:
        extra_args.extend(["-l", trace_file])

    proc = subprocess.Popen(
        PROXY_SERVER + ["--port", str(port)] + extra_args,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
        text=True, cwd=cwd
    )

    # Pipe passphrase to server (or close stdin for plain keys)
    if passphrase is not None:
        if proc.stdin:
            try:
                proc.stdin.write(passphrase + "\n")
                proc.stdin.close()
            except (BrokenPipeError, OSError):
                pass
    else:
        # Plain keys: close stdin so server doesn't block on read
        if proc.stdin:
            try:
                proc.stdin.close()
            except OSError:
                pass

    # Wait for server to be ready
    deadline = time.time() + 10
    probe_ok = False
    while time.time() < deadline:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            sock.connect(("127.0.0.1", port))
            sock.close()
            probe_ok = True
            break
        except (socket.error, ConnectionRefusedError):
            time.sleep(0.1)
    return proc, probe_ok




def _send_proxy_request(port, path="/v1/messages", body=None):
    """Send an HTTP request to the proxy and return (status, response_body)."""
    import http.client as _hc
    if body is None:
        body = json.dumps({"model": "sonnet", "messages": [{"role": "user", "content": "hi"}]})
    conn = _hc.HTTPConnection("127.0.0.1", port, timeout=10)
    headers = {
        "Content-Type": "application/json",
    }
    try:
        conn.request("POST", path, body=body, headers=headers)
        resp = conn.getresponse()
        status = resp.status
        resp_body = resp.read()
        conn.close()
        return status, resp_body
    except Exception as e:
        conn.close()
        return 0, str(e).encode()




def _admin_post(proxy_port, path, body, origin=None):
    """POST to admin API with CSRF Origin header. Returns (status, data)."""
    import http.client as _hc
    conn = _hc.HTTPConnection("127.0.0.1", proxy_port, timeout=10)
    headers = {"Content-Type": "application/json"}
    if origin is not None:
        headers["Origin"] = origin
    else:
        headers["Origin"] = "http://127.0.0.1:{}".format(proxy_port)
    conn.request("POST", path, body=json.dumps(body), headers=headers)
    resp = conn.getresponse()
    data = resp.read().decode()
    conn.close()
    return resp.status, data




# ===========================================================================
# New tests for plan 2026-08-23-cc-switch-mode (Multi-Provider Tier Routing)
# ===========================================================================

# ---------------------------------------------------------------------------
# Helper: standard test setup with mock upstreams and config
# ---------------------------------------------------------------------------

def _setup_tier_routing_test(tiers_config, vendors, default_passphrase="test-passphrase"):
    """Set up a standard tier routing test environment.

    Creates temp directory with config.json and keys-index.json, starts mock
    upstream servers for each vendor, and starts the proxy server.

    Args:
        tiers_config: Dict mapping tier -> {provider, model}
        vendors: Dict mapping vendor -> {url, key}
        default_passphrase: Passphrase for keys decryption

    Returns:
        (temp_dir, proxy_port, proxy_proc, mock_servers, cleanup_fn)
    """
    temp_dir = tempfile.mkdtemp(prefix="proxy_tier_test_")
    proxy_port = find_free_port()

    # Create config — every vendor in keys needs >=1 model for startup validation
    config_path = _create_test_config(
        temp_dir, tiers_config, models=_models_for_vendors(tiers_config, vendors)
    )

    # Create keys (plain or encrypted depending on passphrase)
    if default_passphrase is None:
        keys_path = _create_test_keys_plain(temp_dir, vendors)
    else:
        keys_path = _create_test_keys(temp_dir, vendors, default_passphrase)

    # Start mock upstreams
    mock_servers = {}
    for vendor_name, vendor_info in vendors.items():
        # Parse port from URL
        from urllib.parse import urlparse
        parsed = urlparse(vendor_info["url"])
        port = parsed.port

        # Create mock handler that records requests
        # Use a factory function to properly capture requests_received per iteration
        requests_received = []

        def make_handler(req_list):
            class MockHandler(http.server.BaseHTTPRequestHandler):
                def do_POST(self):
                    content_len = int(self.headers.get("Content-Length", 0))
                    body = self.rfile.read(content_len) if content_len > 0 else b"{}"
                    api_key = self.headers.get("x-api-key", "")
                    req_list.append({"body": body, "api_key": api_key})
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    # Return the model name from the request
                    try:
                        req_data = json.loads(body)
                        model = req_data.get("model", "unknown")
                    except:
                        model = "unknown"
                    self.wfile.write(json.dumps({
                        "id": "ok",
                        "type": "message",
                        "model": model,
                        "content": [{"text": "response"}]
                    }).encode())

                def log_message(self, format, *args):
                    pass
            return MockHandler

        MockHandler = make_handler(requests_received)
        server = http.server.ThreadingHTTPServer(("127.0.0.1", port), MockHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        time.sleep(0.1)
        mock_servers[vendor_name] = {"server": server, "requests": requests_received}

    # Start proxy
    trace_fd, trace_file = tempfile.mkstemp(suffix=".jsonl", dir=temp_dir)
    os.close(trace_fd)

    proc, probe_ok = _start_proxy_server_directly(
        proxy_port, config_path=config_path, keys_path=keys_path,
        passphrase=default_passphrase, trace_file=trace_file
    )

    if not probe_ok:
        for ms in mock_servers.values():
            ms["server"].shutdown()
        proc.kill()
        shutil.rmtree(temp_dir, ignore_errors=True)
        return None, None, None, None, None

    def cleanup():
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        for ms in mock_servers.values():
            ms["server"].shutdown()
        shutil.rmtree(temp_dir, ignore_errors=True)

    return temp_dir, proxy_port, proc, mock_servers, cleanup




# ===========================================================================
# Test: Admin API Switch
# ===========================================================================

def _start_mock_upstream(port, req_list):
    """Start a mock upstream server recording requests into req_list."""
    class MockHandler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            content_len = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_len) if content_len > 0 else b"{}"
            api_key = self.headers.get("x-api-key", "")
            req_list.append({"body": body, "api_key": api_key})
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            try:
                req_data = json.loads(body)
                model = req_data.get("model", "unknown")
            except Exception:
                model = "unknown"
            self.wfile.write(json.dumps({
                "id": "ok",
                "type": "message",
                "model": model,
                "content": [{"text": "response"}]
            }).encode())

        def log_message(self, format, *args):
            pass
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), MockHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.1)
    return server




def _start_admin_proxy(tiers, vendors, models=None):
    """Start proxy via _start_proxy_server_directly with plain keys.

    Returns (proxy_port, proc, mock_servers, temp_dir, cleanup).
    """
    temp_dir = tempfile.mkdtemp(prefix="proxy_admin_")
    proxy_port = find_free_port()
    if models is None:
        # Every vendor in keys needs >=1 model for startup validation
        models = _models_for_vendors(tiers, vendors)
    config_path = _create_test_config(temp_dir, tiers, models=models)
    keys_path = _create_test_keys_plain(temp_dir, vendors)

    mock_servers = {}
    for vendor_name, vendor_info in vendors.items():
        from urllib.parse import urlparse
        parsed = urlparse(vendor_info["url"])
        port = parsed.port
        req_list = []
        mock_servers[vendor_name] = {
            "server": _start_mock_upstream(port, req_list),
            "requests": req_list,
        }

    trace_fd, trace_file = tempfile.mkstemp(suffix=".jsonl", dir=temp_dir)
    os.close(trace_fd)

    proc, probe_ok = _start_proxy_server_directly(
        proxy_port, config_path=config_path, keys_path=keys_path,
        passphrase=None, trace_file=trace_file
    )

    if not probe_ok:
        for ms in mock_servers.values():
            ms["server"].shutdown()
        proc.kill()
        shutil.rmtree(temp_dir, ignore_errors=True)
        return None, None, None, None, None

    def cleanup():
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        for ms in mock_servers.values():
            ms["server"].shutdown()
        shutil.rmtree(temp_dir, ignore_errors=True)

    return proxy_port, proc, mock_servers, temp_dir, cleanup




# ===========================================================================
# Part B (Steps 9-15): disable_retry_claude_count_token
# ===========================================================================

def _create_test_config_with_flag(temp_dir, tiers, flag_value=None):
    """Create a config.json with an optional disable_retry_claude_count_token.

    flag_value: True/False to set, or None to omit the key entirely.
    """
    config = {"tiers": tiers, "models": _derive_models_from_tiers(tiers)}
    if flag_value is not None:
        config["disable_retry_claude_count_token"] = flag_value
    path = os.path.join(temp_dir, "config.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f)
    return path




def _start_proxy_with_flag(proxy_port, temp_dir, flag_value, extra_env=None):
    """Start the proxy server with a config carrying the flag.

    Returns (proc, probe_ok). Config/keys written to temp_dir.
    """
    tiers = {
        "haiku": {"provider": "test-provider", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "test-provider", "model": "claude-sonnet-5"},
        "opus": {"provider": "test-provider", "model": "claude-opus-5"},
    }
    vendors = {
        "test-provider": {"url": f"http://127.0.0.1:{find_free_port()}", "key": "test-api-key"}
    }
    config_path = _create_test_config_with_flag(temp_dir, tiers, flag_value)
    keys_path = _create_test_keys(temp_dir, vendors)

    env = os.environ.copy()
    env["PROXY_PORT"] = str(proxy_port)
    env["PROXY_MAX_RETRIES"] = "3"
    env["PROXY_INITIAL_DELAY"] = "1"
    env["PROXY_MAX_DELAY"] = "1"
    if extra_env:
        env.update(extra_env)

    proc = subprocess.Popen(
        PROXY_SERVER + ["--port", str(proxy_port), "--config-path", config_path, "--keys-path", keys_path],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, text=True
    )
    if proc.stdin:
        try:
            proc.stdin.write("test-passphrase\n")
            proc.stdin.close()
        except (BrokenPipeError, OSError):
            pass

    probe_ok = False
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            sock.connect(("127.0.0.1", proxy_port))
            sock.close()
            probe_ok = True
            break
        except (socket.error, ConnectionRefusedError):
            time.sleep(0.1)
    return proc, probe_ok




# ===========================================================================
# Mode dispatch tests (plan 2026-08-27-support-three-endpoint-modes)
# ===========================================================================

def _require_server_func(name):
    """Import claude_retry_proxy.server and return the named function.

    Returns None (with a recorded failure) if the module or function does not
    exist yet so the rest of the suite still runs cleanly.
    """
    try:
        import claude_retry_proxy.server as srv
    except Exception as e:
        fail("cannot import claude_retry_proxy.server: {}".format(e))
        return None
    fn = getattr(srv, name, None)
    if fn is None:
        fail("server.py does not define {} (not implemented yet)".format(name))
        return None
    return fn




def _mode_tiers(provider="p", model="claude-sonnet-5"):
    """Three-tier config mapping for mode-dispatch tests."""
    return {
        "haiku": {"provider": provider, "model": "claude-haiku-4-5"},
        "sonnet": {"provider": provider, "model": model},
        "opus": {"provider": provider, "model": "claude-opus-5"},
    }




def _start_mode_mock_upstream(port, req_list, responder):
    """Start a mock upstream for mode-dispatch tests.

    responder(info) -> (status, content_type, body_bytes). info is a dict with
    keys path, body, api_key, authorization. Every request (all retries
    included) is appended to req_list.
    """
    class MockHandler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            content_len = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_len) if content_len > 0 else b""
            info = {
                "path": self.path,
                "body": body,
                "api_key": self.headers.get("x-api-key", ""),
                "authorization": self.headers.get("authorization", ""),
                "anthropic_beta": self.headers.get("anthropic-beta", ""),
            }
            req_list.append(info)
            status, content_type, resp_body = responder(info)
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(resp_body)))
            self.end_headers()
            self.wfile.write(resp_body)

        def log_message(self, format, *args):
            pass
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), MockHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.1)
    return server




def _mode_default_responder(info):
    """Default responder: 200 JSON echoing the request's model (anthropic shape)."""
    try:
        model = json.loads(info["body"]).get("model", "unknown")
    except Exception:
        model = "unknown"
    body = json.dumps({
        "id": "msg_ok",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": [{"type": "text", "text": "hello"}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }).encode()
    return 200, "application/json", body




def _start_mode_proxy(tiers, vendors, responders=None, extra_env=None):
    """Start proxy + mode-aware mock upstreams (plain keys).

    vendors maps vendor -> {url, key, mode?}. responders maps vendor ->
    responder(info). extra_env passes additional env vars to the proxy
    subprocess (e.g. reduced PROXY_MAX_DELAY for fast retry tests). Returns
    (temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup).
    """
    temp_dir = tempfile.mkdtemp(prefix="proxy_mode_")
    proxy_port = find_free_port()
    config_path = _create_test_config(
        temp_dir, tiers, models=_models_for_vendors(tiers, vendors))
    keys_path = _create_test_keys_plain(temp_dir, vendors)

    responders = responders or {}
    mock_servers = {}
    for vendor_name, vendor_info in vendors.items():
        from urllib.parse import urlparse
        port = urlparse(vendor_info["url"]).port
        req_list = []
        responder = responders.get(vendor_name, _mode_default_responder)
        server = _start_mode_mock_upstream(port, req_list, responder)
        mock_servers[vendor_name] = {"server": server, "requests": req_list}

    trace_fd, trace_file = tempfile.mkstemp(suffix=".jsonl", dir=temp_dir)
    os.close(trace_fd)

    proc, probe_ok = _start_proxy_server_directly(
        proxy_port, config_path=config_path, keys_path=keys_path,
        passphrase=None, trace_file=trace_file, extra_env=extra_env
    )

    if not probe_ok:
        for ms in mock_servers.values():
            ms["server"].shutdown()
        proc.kill()
        shutil.rmtree(temp_dir, ignore_errors=True)
        return None, None, None, None, None, None

    def cleanup():
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        for ms in mock_servers.values():
            ms["server"].shutdown()
        shutil.rmtree(temp_dir, ignore_errors=True)

    return temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup




def _send_proxy_request_stream(port, body, path="/v1/messages"):
    """POST to the proxy and read the full response until close (SSE).

    Returns (status, content_type, raw_body_bytes).
    """
    import http.client as _hc
    conn = _hc.HTTPConnection("127.0.0.1", port, timeout=30)
    conn.request("POST", path, body=json.dumps(body),
                 headers={"Content-Type": "application/json"})
    resp = conn.getresponse()
    status = resp.status
    content_type = resp.getheader("Content-Type", "")
    chunks = []
    while True:
        chunk = resp.read(4096)
        if not chunk:
            break
        chunks.append(chunk)
    conn.close()
    return status, content_type, b"".join(chunks)




def _parse_sse_frames(raw):
    """Split an SSE byte stream into [(event_type_or_None, data_or_raw)] frames."""
    frames = []
    text = raw.decode("utf-8", errors="replace")
    for block in text.split("\n\n"):
        block = block.strip("\n").strip("\r")
        if not block:
            continue
        event_type = None
        data_val = None
        for line in block.split("\n"):
            line = line.strip("\r")
            if line.startswith("event:"):
                event_type = line[6:].strip()
            elif line.startswith("data:"):
                payload = line[5:].strip()
                try:
                    data_val = json.loads(payload)
                except Exception:
                    data_val = payload
        frames.append((event_type, data_val))
    return frames




def _sse_frame_type(frame):
    """Effective SSE frame type: event: line if present, else data JSON type field."""
    name, data = frame
    if name:
        return name
    if isinstance(data, dict):
        return data.get("type")
    return None




def _sse_frames_with_type(frames, wanted):
    """Return data dicts of frames whose effective type equals wanted."""
    out = []
    for name, data in frames:
        if _sse_frame_type((name, data)) == wanted and isinstance(data, dict):
            out.append(data)
    return out




def _sse_types(frames):
    return [_sse_frame_type(f) for f in frames]




def _admin_get(proxy_port, path, source_ip=None):
    """GET an admin endpoint; returns (status, body_bytes, status_text)."""
    import http.client as _hc
    kwargs = {"timeout": 10}
    if source_ip is not None:
        kwargs["source_address"] = (source_ip, 0)
    conn = _hc.HTTPConnection("127.0.0.1", proxy_port, **kwargs)
    try:
        conn.request("GET", path)
        resp = conn.getresponse()
        body = resp.read()
        status = resp.status
        stat = resp.reason
        conn.close()
        return status, body, stat
    except Exception as e:
        conn.close()
        return 0, str(e).encode(), "connect-error"




def _trace_events_for_request(request_id):
    """Read the session trace file, return events matching request_id (or [] if unavailable)."""
    trace_file = os.environ.get("PROXY_TRACE_FILE")
    if not trace_file or not os.path.exists(trace_file):
        return []
    out = []
    with open(trace_file) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except Exception:
                continue
            if ev.get("request_id") == request_id:
                out.append(ev)
    return out




# --- Step 8: chat-mode SSE transformation ---

def _sse_stream_chunks(chunks):
    return "".join("data: {}\n\n".format(json.dumps(c)) for c in chunks).encode()




def _cc(delta, finish=None):
    """One minimal OpenAI chat-completion chunk."""
    return {"id": "c1", "object": "chat.completion.chunk", "created": 1,
            "model": "gpt-4o",
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}




def _sse_stop_reason(frames):
    """Return the stop_reason from the first message_delta frame, or None."""
    deltas = _sse_frames_with_type(frames, "message_delta")
    if not deltas:
        return None
    return (deltas[0].get("delta") or {}).get("stop_reason")




def _sse_content_block_starts(frames):
    """Return [(index, type)] for every content_block_start, in stream order."""
    out = []
    for name, data in frames:
        if _sse_frame_type((name, data)) == "content_block_start" and isinstance(data, dict):
            out.append((data.get("index"), (data.get("content_block") or {}).get("type")))
    return out




def _sse_tool_use_blocks(frames):
    """Reconstruct Anthropic tool_use blocks from parsed SSE frames.

    Joins input_json_delta partial_json fragments per content_block_start
    (tool_use) and JSON-decodes the concatenation. Returns dicts
    {index, id, name, input, closed} in content_block_start order.
    """
    blocks = []
    for name, data in frames:
        ftype = _sse_frame_type((name, data))
        if not isinstance(data, dict):
            continue
        if ftype == "content_block_start":
            cb = data.get("content_block") or {}
            if cb.get("type") == "tool_use":
                blocks.append({"index": data.get("index"), "id": cb.get("id"),
                               "name": cb.get("name"), "fragments": [],
                               "closed": False})
        elif ftype == "content_block_delta":
            dd = data.get("delta") or {}
            if dd.get("type") == "input_json_delta":
                frag = dd.get("partial_json")
                idx = data.get("index")
                for b in blocks:
                    if b["index"] == idx and not b["closed"] and isinstance(frag, str):
                        b["fragments"].append(frag)
        elif ftype == "content_block_stop":
            for b in blocks:
                if b["index"] == data.get("index"):
                    b["closed"] = True
    out = []
    for b in blocks:
        joined = "".join(b["fragments"])
        try:
            parsed = json.loads(joined) if joined else {}
        except Exception:
            parsed = joined
        out.append({"index": b["index"], "id": b["id"], "name": b["name"],
                    "input": parsed, "closed": b["closed"]})
    return out




def _start_chat_sse_proxy(chunks, add_done=True):
    """Start a chat-mode proxy whose mock upstream streams the given OpenAI chunks.

    Returns (proxy_port, trace_file, cleanup) or (None, None, None) on failure.
    """
    upstream_port = find_free_port()
    tiers = _mode_tiers()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port), "key": "K", "mode": "chat"}}
    sse_body = _sse_stream_chunks(chunks)
    if add_done:
        sse_body += b"data: [DONE]\n\n"
    responders = {"p": lambda info: (200, "text/event-stream", sse_body)}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(
        tiers, vendors, responders=responders)
    if proc is None:
        fail("Failed to set up test")
        return None, None, None
    return proxy_port, trace_file, cleanup




def _chat_sse_fetch_frames(proxy_port, body=None):
    """POST a chat-mode streaming request and return parsed frames (None on non-200)."""
    if body is None:
        body = {"model": "sonnet", "messages": [{"role": "user", "content": "hi"}], "stream": True}
    status, content_type, raw = _send_proxy_request_stream(proxy_port, body=body)
    if status != 200:
        fail("expected 200, got {}".format(status))
        return None
    return _parse_sse_frames(raw)




def _degraded_trace_events(trace_file):
    """Return every chat_sse_tool_degradation trace event in the trace file."""
    out = []
    if not trace_file or not os.path.exists(trace_file):
        return out
    with open(trace_file) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except Exception:
                continue
            if ev.get("event") == "chat_sse_tool_degradation":
                out.append(ev)
    return out




def _assert_degradation_metadata_only(ev):
    """Assert a chat_sse_tool_degradation event carries only fixed metadata fields."""
    fixed = {"timestamp", "event", "request_id", "malformed_tool_count",
             "overflow_tool_count", "dropped_fragment_count",
             "unparseable_arg_count", "scalar_after_tools_dropped",
             "frame_dropped"}
    keys = set(ev)
    if keys != fixed:
        fail("degradation event key set must be the fixed metadata fields, got {!r}".format(keys))
        return False
    return True


# Same isolation for the compatibility learned-state file (plan
# 2026-09-01-learn-context-management-compatibility). server.py reads
# PROXY_FEATURE_COMPAT_FILE, so spawned proxies and in-process imports use an
# isolated state path and can never touch the live user file
# ~/.claude/proxy/feature-compatibility.json.
os.environ["PROXY_FEATURE_COMPAT_FILE"] = os.path.join(
    tempfile.gettempdir(), "claude-retry-proxy-test-compat-state.json")


def run_cli(all_tests, description):
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--test", "-t", type=str, nargs="*",
                        choices=[t[0] for t in all_tests],
                        help="Specific tests to run (default: all)")
    parser.add_argument("--list", action="store_true",
                        help="List available tests")
    args = parser.parse_args()

    if args.list:
        for name, func in all_tests:
            print(f"  {name}")
        return

    selected = args.test if args.test else [t[0] for t in all_tests]
    test_map = dict(all_tests)

    # Verify prerequisites
    import importlib.util
    if importlib.util.find_spec("claude_retry_proxy") is None:
        print("ERROR: claude-retry-proxy not installed; run: pip install -e .")
        sys.exit(2)
    if not os.path.exists(SETTINGS_FILE):
        print(f"ERROR: settings.json not found at {SETTINGS_FILE}")
        sys.exit(2)

    print(f"Running {len(selected)} of {len(all_tests)} tests...")
    print(f"Settings: {SETTINGS_FILE}")

    passed = 0
    failed = 0

    for name in selected:
        func = test_map[name]
        # Clear per-test errors
        global errors
        errors = []
        try:
            func()
        except Exception as e:
            fail(f"Test crashed: {e}")
            import traceback
            traceback.print_exc()

        if errors:
            failed += 1
            print(f"  >> {name}: FAILED ({len(errors)} error(s))")
        else:
            passed += 1
            print(f"  >> {name}: PASSED")

    print(f"\n{'=' * 60}")
    print(f"Results: {passed} passed, {failed} failed, {len(selected)} total")
    if warnings_list:
        print(f"Warnings: {len(warnings_list)}")
        for w in warnings_list:
            print(f"  - {w}")

    # Write test output to a temp file for the session report
    test_output = []
    test_output.append(f"Tests run: {len(selected)}")
    test_output.append(f"Passed: {passed}")
    test_output.append(f"Failed: {failed}")
    if warnings_list:
        test_output.append(f"Warnings: {len(warnings_list)}")

    global TEST_OUTPUT_TEXT
    TEST_OUTPUT_TEXT = "\n".join(test_output)

    sys.exit(0 if failed == 0 else 1)


TEST_OUTPUT_TEXT = ""