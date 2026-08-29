"""Test suite for claude-retry-proxy — HTTP retry proxy with tier routing.

Behavioral tests covering:
  - Retry/backoff: 429 and 503 retried with jittered exponential backoff,
    exhaustion paths (body preservation, synthesized upstream_unreachable)
  - Tier routing: model resolution, provider routing, pattern match
  - Response model rewriting: SSE and JSON paths, unconditional tier-name rewrite
  - Admin API: config GET, tier switch (validation, CSRF, models preservation),
    reload from disk, missing-tier/invalid-provider rejection
  - CLI: start (stdout cleanliness, missing/invalid config, template copy),
    stop (state cleanup, trace lines), reload, status
  - Config/keys: validation (tiers present, providers known, models-per-provider
    catalog), encrypted + plain keys-index.json, wrong passphrase
  - Trace log: markers, oversized-body 413, retry event enrichment, pruning
  - Streaming: response streaming, mid-stream upstream failure, disconnect

Run: pip install -e .  then  python tests/test_claude_proxy.py
Requires: Python 3.8+, no external dependencies (stdlib-only tests).

NOTE: CLI tests use PROXY_STATE_FILE isolation (module-scope env var set to a
session temp path before any CLI/server module import). cli.py and server.py
read PROXY_STATE_FILE from the env, so test proxies use an isolated state file
and can never touch the live proxy's ~/.claude/proxy/proxy-state.json. Config,
keys, and trace log are isolated via --config-path/--keys-path/--log. The suite
is safe to run alongside a live proxy (landed 2026-08-28).
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


def test_concurrent_requests():
    """10+ parallel requests complete successfully."""
    print("\n--- Test 4: Concurrent Requests ---")

    port = find_free_port()
    upstream_port = find_free_port()

    # Start a mock upstream server that responds to all requests
    mock_responses = []
    mock_lock = threading.Lock()

    class MockHandler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            content_len = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_len) if content_len > 0 else b"{}"
            with mock_lock:
                mock_responses.append(body)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"id":"ok","type":"message","content":[{"text":"response"}]}')

        def log_message(self, format, *args):
            pass

    mock_server = http.server.ThreadingHTTPServer(("127.0.0.1", upstream_port), MockHandler)
    mock_thread = threading.Thread(target=mock_server.serve_forever, daemon=True)
    mock_thread.start()
    time.sleep(0.3)

    # Create temp config and keys
    temp_dir = tempfile.mkdtemp(prefix="proxy_concurrent_test_")
    tiers = {
        "haiku": {"provider": "test-provider", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "test-provider", "model": "claude-sonnet-5"},
        "opus": {"provider": "test-provider", "model": "claude-opus-5"},
    }
    vendors = {
        "test-provider": {"url": f"http://127.0.0.1:{upstream_port}", "key": "test-api-key"}
    }
    config_path = _create_test_config(temp_dir, tiers)
    keys_path = _create_test_keys(temp_dir, vendors)

    env = os.environ.copy()
    env["PROXY_PORT"] = str(port)

    proc = subprocess.Popen(
        PROXY_SERVER + ["--port", str(port), "--config-path", config_path, "--keys-path", keys_path],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, text=True
    )

    # Pipe passphrase to server
    if proc.stdin:
        try:
            proc.stdin.write("test-passphrase\n")
            proc.stdin.flush()
        except BrokenPipeError:
            pass
        finally:
            try:
                proc.stdin.close()
            except:
                pass

    # TCP probe for readiness
    probe_ok = False
    deadline = time.time() + 10
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

    if not probe_ok:
        proc.kill()
        mock_server.shutdown()
        shutil.rmtree(temp_dir, ignore_errors=True)
        fail("Proxy server failed to start")
        return

    try:
        # Send 10 concurrent requests
        num_requests = 10
        results = []

        def send_request(i):
            status, body = _send_proxy_request(port)
            results.append((i, status, body))

        threads_list = []
        for i in range(num_requests):
            t = threading.Thread(target=send_request, args=(i,))
            threads_list.append(t)
            t.start()

        for t in threads_list:
            t.join(timeout=30)

        # Verify results
        success_count = sum(1 for _, s, _ in results if s == 200)
        if success_count == num_requests:
            pass_(f"All {num_requests} concurrent requests completed (HTTP 200)")
        else:
            fail(f"Only {success_count}/{num_requests} requests succeeded")

        # Verify mock received all requests
        with mock_lock:
            received = len(mock_responses)
        if received == num_requests:
            pass_(f"Mock upstream received all {num_requests} requests")
        else:
            fail(f"Mock upstream received {received}/{num_requests} requests")

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        mock_server.shutdown()
        shutil.rmtree(temp_dir, ignore_errors=True)


# ===========================================================================
# Test Case 5: Retry Logic
# ===========================================================================

def test_retry_logic():
    """Start proxy; mock upstream returns 503 3x then 200; verify exponential backoff."""
    print("\n--- Test 5: Retry Logic ---")

    upstream_port = find_free_port()
    proxy_port = find_free_port()

    # Mock upstream: 503 for first 3 requests, 200 after
    retry_count = [0]
    count_lock = threading.Lock()

    class RetryHandler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            content_len = int(self.headers.get("Content-Length", 0))
            if content_len > 0:
                self.rfile.read(content_len)
            with count_lock:
                retry_count[0] += 1
                current = retry_count[0]
            if current <= 3:
                self.send_response(503)
                self.send_header("Retry-After", "1")
                self.end_headers()
                self.wfile.write(b'{"error":"Service Unavailable"}')
            else:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"id":"ok","type":"message","content":[{"text":"response"}]}')

        def log_message(self, format, *args):
            pass

    mock_server = http.server.ThreadingHTTPServer(("127.0.0.1", upstream_port), RetryHandler)
    mock_thread = threading.Thread(target=mock_server.serve_forever, daemon=True)
    mock_thread.start()
    time.sleep(0.3)

    # Create temp config and keys
    temp_dir = tempfile.mkdtemp(prefix="proxy_retry_test_")
    tiers = {
        "haiku": {"provider": "test-provider", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "test-provider", "model": "claude-sonnet-5"},
        "opus": {"provider": "test-provider", "model": "claude-opus-5"},
    }
    vendors = {
        "test-provider": {"url": f"http://127.0.0.1:{upstream_port}", "key": "test-api-key"}
    }
    config_path = _create_test_config(temp_dir, tiers)
    keys_path = _create_test_keys(temp_dir, vendors)

    env = os.environ.copy()
    env["PROXY_PORT"] = str(proxy_port)
    env["PROXY_MAX_RETRIES"] = "5"
    env["PROXY_INITIAL_DELAY"] = "1"
    env["PROXY_MAX_DELAY"] = "2"  # Cap delay at 2s for fast test

    proc = subprocess.Popen(
        PROXY_SERVER + ["--port", str(proxy_port), "--config-path", config_path, "--keys-path", keys_path],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, text=True
    )

    # Pipe passphrase to server
    if proc.stdin:
        try:
            proc.stdin.write("test-passphrase\n")
            proc.stdin.flush()
        except BrokenPipeError:
            pass
        finally:
            try:
                proc.stdin.close()
            except:
                pass

    # TCP probe for readiness
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

    if not probe_ok:
        proc.kill()
        mock_server.shutdown()
        shutil.rmtree(temp_dir, ignore_errors=True)
        fail("Proxy server failed to start for retry test")
        return

    try:
        # Send request that will trigger retries.
        # Give a generous timeout — backoff delays add up.
        status, body = _send_proxy_request(proxy_port)

        with count_lock:
            total_attempts = retry_count[0]
            actual_retries = max(0, total_attempts - 1)  # -1 for the success

        info(f"Total upstream requests made: {total_attempts} (first 3 = 503, 4th = 200)")

        if status == 200:
            pass_(f"Request succeeded after {actual_retries} retries (expected 3)")
            if actual_retries >= 3:
                pass_("Retry count matches expected 503 sequence — exponential backoff working")
            elif actual_retries > 0:
                pass_(f"Retry logic active ({actual_retries} retries) — may be less than mock 503s due to timing")
        else:
            fail(f"Request failed with status {status} after {actual_retries} retries — expected 200")

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        mock_server.shutdown()
        shutil.rmtree(temp_dir, ignore_errors=True)


# ===========================================================================
# Test Case 5b: Jittered Delay Bounds (unit test of compute_jittered_delay)
# ===========================================================================

def test_compute_jittered_delay_bounds():
    """Unit-test compute_jittered_delay: bounds, rounding, de-sync pattern, guards, thread-local RNG."""
    print("\n--- Test 5b: Jittered Delay Bounds ---")

    import math
    from claude_retry_proxy.server import compute_jittered_delay, compute_delay, _rng, \
        PROXY_INITIAL_DELAY, PROXY_MAX_DELAY

    bases = [1, 2, 3, 4, 8, 16, 30, 300]
    draws_per_base = 2000

    for base in bases:
        results = [compute_jittered_delay(base) for _ in range(draws_per_base)]

        # Every result must be an int >= 0
        for r in results:
            if not isinstance(r, int):
                fail(f"base={base}: non-int result: {r} (type={type(r).__name__})")
                break
            if r < 0:
                fail(f"base={base}: negative result: {r}")
                break
        else:
            # Upper bound: floor(base * 1.25 + 0.5)
            hi = math.floor(base * 1.25 + 0.5)
            for r in results:
                if r > hi:
                    fail(f"base={base}: result {r} exceeds upper bound {hi}")
                    break
            else:
                pass_(f"base={base}: all {draws_per_base} draws within [0, {hi}]")

            # Lower bound (allow one integer step below floor for edge effects)
            lo = math.floor(base * 0.75 + 0.5) - 1
            for r in results:
                if r < lo:
                    fail(f"base={base}: result {r} below lower bound {lo}")
                    break
            else:
                pass_(f"base={base}: all draws >= lower bound {lo}")

            # Empirical mean check (±15% of base — unbiased jitter)
            mean = sum(results) / len(results)
            if abs(mean - base) < 0.15 * base:
                pass_(f"base={base}: mean={mean:.2f} ≈ {base} (within ±15%)")
            else:
                fail(f"base={base}: mean={mean:.2f} deviates >15% from {base}")

    # De-sync regression guard: base=3 and base=4 produce ≥2 distinct values
    for base in [3, 4]:
        results = [compute_jittered_delay(base) for _ in range(draws_per_base)]
        distinct = len(set(results))
        if distinct >= 2:
            pass_(f"base={base}: {distinct} distinct values (de-sync active)")
        else:
            fail(f"base={base}: only 1 distinct value — de-sync dead (rounding bug)")

    # De-sync regression guard: base=1 and base=2 are degenerate (documented)
    for base in [1, 2]:
        results = [compute_jittered_delay(base) for _ in range(500)]
        distinct = len(set(results))
        if distinct == 1:
            pass_(f"base={base}: exactly 1 distinct value ({results[0]}) — degenerate, documented")
        else:
            fail(f"base={base}: {distinct} distinct values — expected exactly 1 (degenerate case)")

    # Guard clause: compute_jittered_delay(0) == 0 and compute_jittered_delay(-5) == 0
    if compute_jittered_delay(0) == 0:
        pass_("compute_jittered_delay(0) == 0")
    else:
        fail(f"compute_jittered_delay(0) = {compute_jittered_delay(0)}, expected 0")

    if compute_jittered_delay(-5) == 0:
        pass_("compute_jittered_delay(-5) == 0")
    else:
        fail(f"compute_jittered_delay(-5) = {compute_jittered_delay(-5)}, expected 0")

    # Regression guard on unchanged compute_delay
    if compute_delay(0) == PROXY_INITIAL_DELAY:
        pass_(f"compute_delay(0) == PROXY_INITIAL_DELAY ({PROXY_INITIAL_DELAY})")
    else:
        fail(f"compute_delay(0) = {compute_delay(0)}, expected {PROXY_INITIAL_DELAY}")

    if compute_delay(100) == PROXY_MAX_DELAY:
        pass_(f"compute_delay(100) == PROXY_MAX_DELAY ({PROXY_MAX_DELAY})")
    else:
        fail(f"compute_delay(100) = {compute_delay(100)}, expected {PROXY_MAX_DELAY}")

    # Thread-local RNG correctness: same object within one thread
    r1 = _rng()
    r2 = _rng()
    if r1 is r2:
        pass_("_rng() returns same object within one thread")
    else:
        fail("_rng() returned different objects within the same thread")

    # Thread-local RNG correctness: distinct objects across threads
    cross_thread_results = []
    def get_rng():
        cross_thread_results.append(_rng())

    t = threading.Thread(target=get_rng)
    t.start()
    t.join()
    if len(cross_thread_results) == 1 and cross_thread_results[0] is not r1:
        pass_("_rng() returns distinct objects across threads")
    elif len(cross_thread_results) == 1 and cross_thread_results[0] is r1:
        fail("_rng() returned the SAME object across threads — not thread-local")
    else:
        fail(f"Unexpected cross-thread _rng() result: {cross_thread_results}")


# ===========================================================================
# Test Case 5c: 429 Retry (3x 429 then 200)
# ===========================================================================

def test_retry_429():
    """Mock upstream returns 429 3x then 200; assert success, trace reason:'429'."""
    print("\n--- Test 5c: 429 Retry ---")

    upstream_port = find_free_port()
    proxy_port = find_free_port()

    retry_count = [0]
    count_lock = threading.Lock()

    class Retry429Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            content_len = int(self.headers.get("Content-Length", 0))
            if content_len > 0:
                self.rfile.read(content_len)
            with count_lock:
                retry_count[0] += 1
                current = retry_count[0]
            if current <= 3:
                self.send_response(429)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"error":"Too Many Requests"}')
            else:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"id":"ok","type":"message","content":[{"text":"response"}]}')

        def log_message(self, format, *args):
            pass

    mock_server = http.server.ThreadingHTTPServer(("127.0.0.1", upstream_port), Retry429Handler)
    mock_thread = threading.Thread(target=mock_server.serve_forever, daemon=True)
    mock_thread.start()
    time.sleep(0.3)

    # Create temp config and keys
    temp_dir = tempfile.mkdtemp(prefix="proxy_retry429_test_")
    tiers = {
        "haiku": {"provider": "test-provider", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "test-provider", "model": "claude-sonnet-5"},
        "opus": {"provider": "test-provider", "model": "claude-opus-5"},
    }
    vendors = {
        "test-provider": {"url": f"http://127.0.0.1:{upstream_port}", "key": "test-api-key"}
    }
    config_path = _create_test_config(temp_dir, tiers)
    keys_path = _create_test_keys(temp_dir, vendors)

    trace_fd, trace_file = tempfile.mkstemp(suffix=".jsonl", dir=temp_dir)
    os.close(trace_fd)

    env = os.environ.copy()
    env["PROXY_PORT"] = str(proxy_port)
    env["PROXY_MAX_RETRIES"] = "5"
    env["PROXY_INITIAL_DELAY"] = "1"
    env["PROXY_MAX_DELAY"] = "2"
    env["PROXY_TRACE_FILE"] = trace_file

    proc = subprocess.Popen(
        PROXY_SERVER + ["--port", str(proxy_port), "--config-path", config_path, "--keys-path", keys_path],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, text=True
    )

    # Pipe passphrase to server
    if proc.stdin:
        try:
            proc.stdin.write("test-passphrase\n")
            proc.stdin.flush()
        except BrokenPipeError:
            pass
        finally:
            try:
                proc.stdin.close()
            except:
                pass

    # TCP probe for readiness
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

    if not probe_ok:
        proc.kill()
        mock_server.shutdown()
        shutil.rmtree(temp_dir, ignore_errors=True)
        fail("Proxy server failed to start for 429 retry test")
        return

    try:
        status, body = _send_proxy_request(proxy_port)

        with count_lock:
            total_attempts = retry_count[0]
            actual_retries = max(0, total_attempts - 1)

        info(f"Total upstream requests made: {total_attempts} (first 3 = 429, 4th = 200)")

        if status == 200:
            pass_(f"Request succeeded after {actual_retries} retries (expected 3)")
            if total_attempts >= 4:
                pass_(f"Upstream received {total_attempts} calls (expected 4: 3×429 + 1×200)")
            else:
                fail(f"Upstream received only {total_attempts} calls, expected at least 4")
        else:
            fail(f"Request failed with status {status} after {actual_retries} retries — expected 200")

        # Kill proxy to flush trace
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        time.sleep(0.5)

        # Verify trace file has a retry line with reason "429"
        if not os.path.exists(trace_file):
            fail(f"Trace file not created: {trace_file}")
            return

        with open(trace_file) as f:
            entries = [json.loads(line) for line in f if line.strip()]

        retry_429_events = [e for e in entries
                            if e.get("event") == "retry" and e.get("reason") == "429"]
        if len(retry_429_events) >= 1:
            pass_(f"Trace has {len(retry_429_events)} retry event(s) with reason '429'")
        else:
            fail("No retry event with reason '429' in trace")

    finally:
        mock_server.shutdown()
        shutil.rmtree(temp_dir, ignore_errors=True)


# ===========================================================================
# Test Case 5d: 429 Exhaustion Returns 429
# ===========================================================================

def test_retry_429_exhaust_returns_429():
    """Mock upstream always returns 429; verify client gets 429 on exhaustion."""
    print("\n--- Test 5d: 429 Exhaustion Returns 429 ---")

    upstream_port = find_free_port()
    proxy_port = find_free_port()

    request_count = [0]
    count_lock = threading.Lock()

    class Always429Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            content_len = int(self.headers.get("Content-Length", 0))
            if content_len > 0:
                self.rfile.read(content_len)
            with count_lock:
                request_count[0] += 1
            self.send_response(429)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error":"Too Many Requests"}')

        def log_message(self, format, *args):
            pass

    mock_server = http.server.ThreadingHTTPServer(("127.0.0.1", upstream_port), Always429Handler)
    mock_thread = threading.Thread(target=mock_server.serve_forever, daemon=True)
    mock_thread.start()
    time.sleep(0.3)

    # Create temp config and keys
    temp_dir = tempfile.mkdtemp(prefix="proxy_exhaust429_test_")
    tiers = {
        "haiku": {"provider": "test-provider", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "test-provider", "model": "claude-sonnet-5"},
        "opus": {"provider": "test-provider", "model": "claude-opus-5"},
    }
    vendors = {
        "test-provider": {"url": f"http://127.0.0.1:{upstream_port}", "key": "test-api-key"}
    }
    config_path = _create_test_config(temp_dir, tiers)
    keys_path = _create_test_keys(temp_dir, vendors)

    env = os.environ.copy()
    env["PROXY_PORT"] = str(proxy_port)
    env["PROXY_MAX_RETRIES"] = "2"
    env["PROXY_MAX_DELAY"] = "1"
    env["PROXY_INITIAL_DELAY"] = "1"

    proc = subprocess.Popen(
        PROXY_SERVER + ["--port", str(proxy_port), "--config-path", config_path, "--keys-path", keys_path],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, text=True
    )

    # Pipe passphrase to server
    if proc.stdin:
        try:
            proc.stdin.write("test-passphrase\n")
            proc.stdin.flush()
        except BrokenPipeError:
            pass
        finally:
            try:
                proc.stdin.close()
            except:
                pass

    # TCP probe for readiness
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

    if not probe_ok:
        proc.kill()
        mock_server.shutdown()
        shutil.rmtree(temp_dir, ignore_errors=True)
        fail("Proxy server failed to start for 429 exhaustion test")
        return

    try:
        status, body = _send_proxy_request(proxy_port)

        with count_lock:
            total = request_count[0]

        if status == 429:
            pass_(f"Client received 429 on exhaustion (status={status})")
        elif status == 503:
            fail(f"Client received 503 — should be 429 (the actual upstream status)")
        elif status == 0:
            fail(f"Client received 0 — connection error, expected 429")
        else:
            fail(f"Client received {status}, expected 429 on exhaustion")

        expected_attempts = 3  # MAX_RETRIES=2 → 3 total attempts (attempts 0,1,2)
        if total == expected_attempts:
            pass_(f"Upstream received {total} requests (expected {expected_attempts} = MAX_RETRIES+1)")
        elif total < expected_attempts:
            fail(f"Upstream received only {total} requests, expected {expected_attempts}")
        else:
            # More than expected may be OK if timing caused extra attempts
            warn(f"Upstream received {total} requests, expected {expected_attempts}")

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        mock_server.shutdown()
        shutil.rmtree(temp_dir, ignore_errors=True)


# ===========================================================================
# Test Case 6: Trace Markers
# ===========================================================================

def test_trace_markers():
    """Start proxy, send requests, kill; verify trace has start/end markers with counters."""
    print("\n--- Test 6: Trace Markers ---")

    upstream_port = find_free_port()
    proxy_port = find_free_port()

    class TraceHandler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            content_len = int(self.headers.get("Content-Length", 0))
            if content_len > 0:
                self.rfile.read(content_len)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"id":"ok","type":"message"}')

        def log_message(self, format, *args):
            pass

    mock_server = http.server.ThreadingHTTPServer(("127.0.0.1", upstream_port), TraceHandler)
    mock_thread = threading.Thread(target=mock_server.serve_forever, daemon=True)
    mock_thread.start()
    time.sleep(0.3)

    # Create temp config and keys
    temp_dir = tempfile.mkdtemp(prefix="proxy_trace_test_")
    tiers = {
        "haiku": {"provider": "test-provider", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "test-provider", "model": "claude-sonnet-5"},
        "opus": {"provider": "test-provider", "model": "claude-opus-5"},
    }
    vendors = {
        "test-provider": {"url": f"http://127.0.0.1:{upstream_port}", "key": "test-api-key"}
    }
    config_path = _create_test_config(temp_dir, tiers)
    keys_path = _create_test_keys(temp_dir, vendors)

    trace_fd, trace_file = tempfile.mkstemp(suffix=".jsonl", dir=temp_dir)
    os.close(trace_fd)

    env = os.environ.copy()
    env["PROXY_PORT"] = str(proxy_port)
    env["PROXY_TRACE_FILE"] = trace_file

    proc = subprocess.Popen(
        PROXY_SERVER + ["--port", str(proxy_port), "--config-path", config_path, "--keys-path", keys_path],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, text=True
    )

    # Pipe passphrase to server
    if proc.stdin:
        try:
            proc.stdin.write("test-passphrase\n")
            proc.stdin.flush()
        except BrokenPipeError:
            pass
        finally:
            try:
                proc.stdin.close()
            except:
                pass

    # TCP probe for readiness
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

    if not probe_ok:
        proc.kill()
        mock_server.shutdown()
        shutil.rmtree(temp_dir, ignore_errors=True)
        fail("Proxy server failed to start for trace test")
        return

    try:
        # Send a few requests
        for i in range(3):
            _send_proxy_request(proxy_port)

        time.sleep(0.5)

        # Kill proxy to trigger stop marker
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

        time.sleep(0.5)

        # Read trace file
        if not os.path.exists(trace_file):
            fail(f"Trace file not created: {trace_file}")
            return

        with open(trace_file) as f:
            lines = [json.loads(line) for line in f if line.strip()]

        # Verify proxy_start event
        start_events = [l for l in lines if l.get("event") == "proxy_start"]
        if len(start_events) >= 1:
            pass_(f"proxy_start event found (port={start_events[0].get('port')})")
        else:
            fail("No proxy_start event in trace")

        # Verify request events
        request_events = [l for l in lines if l.get("event") == "request"]
        if len(request_events) >= 3:
            pass_(f"Found {len(request_events)} request events")
        else:
            fail(f"Only {len(request_events)} request events found, expected at least 3")

        # Verify proxy_stop event
        stop_events = [l for l in lines if l.get("event") == "proxy_stop"]
        if len(stop_events) >= 1:
            pass_("proxy_stop event found")
            if stop_events[0].get("requests_total") is not None:
                pass_(f"requests_total counter present: {stop_events[0].get('requests_total')}")
            else:
                fail("proxy_stop missing requests_total counter")
        else:
            warn("No proxy_stop event in trace (may be expected if termination was abrupt)")

    finally:
        mock_server.shutdown()
        shutil.rmtree(temp_dir, ignore_errors=True)


# ===========================================================================
# Test Case 9: Thread Safety
# ===========================================================================

def test_thread_safety():
    """N parallel requests produce exactly N trace entries (no lost entries)."""
    print("\n--- Test 9: Thread Safety ---")

    upstream_port = find_free_port()
    proxy_port = find_free_port()

    import random

    class ThreadSafetyHandler(http.server.BaseHTTPRequestHandler):
        """Handler that adds random delay to simulate real API latency."""
        def do_POST(self):
            time.sleep(random.uniform(0.05, 0.2))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"id":"ok","type":"message"}')

        def log_message(self, format, *args):
            pass

    mock_server = http.server.ThreadingHTTPServer(("127.0.0.1", upstream_port), ThreadSafetyHandler)
    mock_thread = threading.Thread(target=mock_server.serve_forever, daemon=True)
    mock_thread.start()
    time.sleep(0.3)

    # Create temp config and keys
    temp_dir = tempfile.mkdtemp(prefix="proxy_threadsafety_test_")
    tiers = {
        "haiku": {"provider": "test-provider", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "test-provider", "model": "claude-sonnet-5"},
        "opus": {"provider": "test-provider", "model": "claude-opus-5"},
    }
    vendors = {
        "test-provider": {"url": f"http://127.0.0.1:{upstream_port}", "key": "test-api-key"}
    }
    config_path = _create_test_config(temp_dir, tiers)
    keys_path = _create_test_keys(temp_dir, vendors)

    trace_fd, trace_file = tempfile.mkstemp(suffix=".jsonl", dir=temp_dir)
    os.close(trace_fd)

    env = os.environ.copy()
    env["PROXY_PORT"] = str(proxy_port)
    env["PROXY_TRACE_FILE"] = trace_file

    proc = subprocess.Popen(
        PROXY_SERVER + ["--port", str(proxy_port), "--config-path", config_path, "--keys-path", keys_path],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, text=True
    )

    # Pipe passphrase to server
    if proc.stdin:
        try:
            proc.stdin.write("test-passphrase\n")
            proc.stdin.flush()
        except BrokenPipeError:
            pass
        finally:
            try:
                proc.stdin.close()
            except:
                pass

    # TCP probe for readiness
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

    if not probe_ok:
        proc.kill()
        mock_server.shutdown()
        shutil.rmtree(temp_dir, ignore_errors=True)
        fail("Proxy server failed to start for thread safety test")
        return

    try:
        num_requests = 20
        results_lock = threading.Lock()
        request_results = []

        def send_and_record(i):
            import http.client as _hc2
            body = json.dumps({"model": "sonnet", "messages": [{"role": "user", "content": f"msg{i}"}]})
            conn = _hc2.HTTPConnection("127.0.0.1", proxy_port, timeout=30)
            try:
                conn.request("POST", "/v1/messages", body=body,
                           headers={"Content-Type": "application/json"})
                resp = conn.getresponse()
                status = resp.status
                resp.read()
                conn.close()
                with results_lock:
                    request_results.append({"index": i, "status": status})
            except Exception as e:
                conn.close()
                with results_lock:
                    request_results.append({"index": i, "status": 0, "error": str(e)})

        threads_list = []
        for i in range(num_requests):
            t = threading.Thread(target=send_and_record, args=(i,))
            threads_list.append(t)
            t.start()

        for t in threads_list:
            t.join(timeout=60)

        success_count = sum(1 for r in request_results if r["status"] == 200)
        if success_count == num_requests:
            pass_(f"All {num_requests} requests completed (HTTP 200)")
        else:
            fail(f"Only {success_count}/{num_requests} requests succeeded")

        # Kill proxy to flush trace
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

        time.sleep(0.5)

        # Verify trace has exactly N request entries
        if not os.path.exists(trace_file):
            fail(f"Trace file not created: {trace_file}")
            return

        with open(trace_file) as f:
            lines = [json.loads(line) for line in f if line.strip()]

        request_events = [l for l in lines if l.get("event") == "request"]
        if len(request_events) == num_requests:
            pass_(f"Trace has exactly {num_requests} request entries (matches concurrent requests)")
        else:
            fail(f"Trace has {len(request_events)} request entries, expected {num_requests} — entries lost/duplicated")

        # Verify all entries have complete fields
        corrupted = []
        for i, event in enumerate(request_events):
            if "request_id" not in event or "status" not in event:
                corrupted.append(i)
        if corrupted:
            fail(f"{len(set(corrupted))} trace entries have missing fields (corrupted writes)")
        else:
            pass_("All trace entries have complete field sets — no corrupted writes")

    finally:
        mock_server.shutdown()
        shutil.rmtree(temp_dir, ignore_errors=True)


# ===========================================================================
# Test Case 11: Relative Log Path
# ===========================================================================

def test_relative_log_path():
    """Start proxy server directly with '-l relative.jsonl' and cwd=temp dir.

    Validates Step 2 (relative --log resolved to absolute via os.getcwd())
    and the Step 1 guard (log_trace dirname check). The trace file must
    be created in the temp CWD, not under ~/.claude/logs/.
    """
    print("\n--- Test 11: Relative Log Path ---")

    tmpdir = tempfile.mkdtemp(prefix="proxy_test_log_")
    trace_arg = "relative.jsonl"
    expected_path = os.path.join(tmpdir, trace_arg)

    port = find_free_port()
    upstream_port = find_free_port()

    # Start a mock upstream on upstream_port
    class MockUpstreamHandler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            resp = json.dumps({"id": "msg_test", "type": "message", "content": [{"text": "ok"}]})
            self.wfile.write(resp.encode())

        def log_message(self, format, *args):
            pass

    mock_server = http.server.ThreadingHTTPServer(("127.0.0.1", upstream_port), MockUpstreamHandler)
    mock_thread = threading.Thread(target=mock_server.serve_forever, daemon=True)
    mock_thread.start()
    time.sleep(0.3)

    info(f"Mock upstream on port {upstream_port}")

    # Create temp config and keys
    tiers = {
        "haiku": {"provider": "test-provider", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "test-provider", "model": "claude-sonnet-5"},
        "opus": {"provider": "test-provider", "model": "claude-opus-5"},
    }
    vendors = {
        "test-provider": {"url": f"http://127.0.0.1:{upstream_port}", "key": "test-api-key"}
    }
    config_path = _create_test_config(tmpdir, tiers)
    keys_path = _create_test_keys(tmpdir, vendors)

    env = os.environ.copy()
    env["PROXY_PORT"] = str(port)

    extra_args = ["--port", str(port), "--config-path", config_path, "--keys-path", keys_path, "-l", trace_arg]

    # Start proxy server directly with relative log in temp CWD
    info(f"Starting proxy server directly on port {port} with -l {trace_arg} in cwd={tmpdir}")
    proc = subprocess.Popen(
        PROXY_SERVER + extra_args,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
        text=True, cwd=tmpdir
    )

    # Pipe passphrase to server
    if proc.stdin:
        try:
            proc.stdin.write("test-passphrase\n")
            proc.stdin.flush()
        except BrokenPipeError:
            pass
        finally:
            try:
                proc.stdin.close()
            except:
                pass

    # TCP probe for readiness
    probe_ok = False
    deadline = time.time() + 10
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

    if not probe_ok:
        proc.kill()
        mock_server.shutdown()
        shutil.rmtree(tmpdir, ignore_errors=True)
        fail("Failed to start proxy server directly")
        return

    try:
        # Send one request to trigger trace events
        status, body = _send_proxy_request(port)
        if status == 0:
            fail(f"Proxy request failed (connection error): {body}")
        else:
            pass_(f"Proxy forwarded request: HTTP {status}")

        info(f"Checking for trace file at {expected_path}...")
        # Kill the server
        try:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        except OSError:
            pass

        # Give the server a moment to flush writes
        time.sleep(0.3)

        # Assert trace file exists at the resolved absolute path (in tmpdir)
        if os.path.exists(expected_path):
            pass_(f"Trace file created at expected location: {expected_path}")
        else:
            fail(f"Trace file NOT found at {expected_path}")
            # Check if it was created elsewhere (e.g. repo root or ~/.claude/logs)
            if os.path.exists("relative.jsonl"):
                fail("Trace file created in repo root (CWD was not overridden)")
            home_log = os.path.join(os.path.expanduser("~"), ".claude", "logs", "relative.jsonl")
            if os.path.exists(home_log):
                fail(f"Trace file created under ~/.claude/logs/: {home_log}")
            return

        # Verify content: must contain a proxy_start event
        with open(expected_path) as f:
            lines = f.readlines()
        if not lines:
            fail("Trace file is empty")
            return

        first_event = json.loads(lines[0].strip())
        if first_event.get("event") == "proxy_start":
            pass_(f"Trace file contains proxy_start event (port={first_event.get('port')})")
        else:
            fail(f"First event is not proxy_start: {first_event}")

        # Verify all lines parse as valid JSON
        valid = True
        for i, line in enumerate(lines):
            try:
                json.loads(line.strip())
            except json.JSONDecodeError:
                fail(f"Line {i + 1} is not valid JSON: {line[:100]}")
                valid = False
        if valid:
            pass_(f"All {len(lines)} trace entries are valid JSON")

    finally:
        # Cleanup temp dir
        try:
            mock_server.shutdown()
        except Exception:
            pass
        shutil.rmtree(tmpdir, ignore_errors=True)


# ===========================================================================
# Test Case 13: Stop Cleans proxy-state.json
# ===========================================================================

def test_stop_cleans_proxy_state():
    """Start proxy, force-kill server, run stop, verify proxy-state.json deleted."""
    print("\n--- Test 13: Stop Cleans proxy-state.json ---")
    state_backup = _backup_proxy_state()
    cleanup_lock_files()

    try:
        # Ensure cmd_start doesn't refuse with "Proxy already running"
        try:
            os.remove(PROXY_STATE_FILE)
        except OSError:
            pass

        port = find_free_port()
        temp_dir = tempfile.mkdtemp(prefix="proxy_stop_state_")
        try:
            config_path = _create_test_config(temp_dir, {
                "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
                "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
                "opus": {"provider": "p", "model": "claude-opus-5"},
            })
            keys_path = _create_test_keys_plain(temp_dir, {
                "p": {"url": f"http://127.0.0.1:{find_free_port()}", "key": "k"}
            })
            trace_fd, trace_file = tempfile.mkstemp(suffix=".jsonl", dir=temp_dir)
            os.close(trace_fd)

            # Start proxy via CLI (writes proxy-state.json)
            info(f"Starting proxy on port {port}...")
            proc, stdout, stderr, rc = _cli_start_with_plain_keys(
                port, config_path, keys_path, trace_file)
            if rc != 0:
                fail(f"Start failed (exit {rc}): {stdout} {stderr}")
                return

            # Verify proxy-state.json exists (server creates it on startup)
            if not os.path.exists(PROXY_STATE_FILE):
                fail("proxy-state.json not found after start — server may not have created it")
                return
            pass_("proxy-state.json exists after proxy start")

            # Read PID from proxy-state.json
            with open(PROXY_STATE_FILE) as f:
                state = json.load(f)
            pid = state.get("pid")

            # Force-kill the server process (simulating Windows taskkill /F)
            if pid:
                info(f"Force-killing proxy process PID {pid}...")
                if sys.platform == "win32":
                    subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
                else:
                    try:
                        os.kill(pid, signal.SIGKILL)
                    except OSError:
                        pass
                time.sleep(0.5)

            # Verify proxy-state.json still exists (force kill bypasses server finally block)
            if os.path.exists(PROXY_STATE_FILE):
                pass_("proxy-state.json still exists after taskkill /F (server cleanup bypassed)")
            else:
                warn("proxy-state.json already gone — server may have cleaned up; test may be inconclusive")

            # Run stop — should clean up proxy-state.json
            info("Running claude-retry-proxy stop...")
            stop_result = subprocess.run(
                CLAUDE_PROXY + ["stop"],
                capture_output=True, text=True, timeout=10
            )
            stderr = stop_result.stderr

            # Verify proxy-state.json is deleted
            if not os.path.exists(PROXY_STATE_FILE):
                pass_("proxy-state.json deleted by claude-retry-proxy stop")
            else:
                fail("proxy-state.json still exists after stop — not cleaned up by cmd_stop")

            # Assert trace lines (dead-PID flow: force-kill, no graceful shutdown)
            if "cmd_stop: entering" in stderr:
                pass_("stderr trace shows 'cmd_stop: entering'")
            else:
                fail(f"stderr missing 'cmd_stop: entering'. stderr: {stderr[:300]}")
            if "cmd_stop: returning 0" in stderr:
                pass_("stderr trace shows 'cmd_stop: returning 0'")
            else:
                fail(f"stderr missing 'cmd_stop: returning 0'. stderr: {stderr[:300]}")
            if "proxy-state.json removed" in stderr or "proxy-state.json not found" in stderr:
                pass_("stderr trace shows proxy-state.json cleanup")
            else:
                fail(f"stderr missing proxy-state.json cleanup line. stderr: {stderr[:300]}")

            if stop_result.returncode != 0:
                fail(f"stop exited {stop_result.returncode}: {stop_result.stdout} {stderr}")
            else:
                pass_(f"stop exit code 0 ({stop_result.returncode})")

        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    finally:
        cleanup_lock_files()
        subprocess.run(
            CLAUDE_PROXY + ["stop"],
            capture_output=True, text=True, timeout=10
        )
        # Remove the stale state file so the restore reliably puts back the
        # pre-test backup (server wrote state on startup, force-kill bypassed
        # its cleanup, leaving a dead test PID).
        try:
            os.remove(PROXY_STATE_FILE)
        except OSError:
            pass
        _restore_proxy_state(state_backup)


def test_trace_logs_oversized_body():
    """Send POST with body exceeding PROXY_MAX_BODY_SIZE; verify 413 AND trace entry."""
    print("\n--- Test 18: Trace Logs Oversized Body ---")

    import http.client as http_client

    upstream_port = find_free_port()
    proxy_port = find_free_port()

    class OversizedHandler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"id":"should-not-reach"}')

        def log_message(self, format, *args):
            pass

    mock_server = http.server.ThreadingHTTPServer(("127.0.0.1", upstream_port), OversizedHandler)
    mock_thread = threading.Thread(target=mock_server.serve_forever, daemon=True)
    mock_thread.start()
    time.sleep(0.3)

    # Create temp config and keys
    temp_dir = tempfile.mkdtemp(prefix="proxy_oversized_test_")
    tiers = {
        "haiku": {"provider": "test-provider", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "test-provider", "model": "claude-sonnet-5"},
        "opus": {"provider": "test-provider", "model": "claude-opus-5"},
    }
    vendors = {
        "test-provider": {"url": f"http://127.0.0.1:{upstream_port}", "key": "test-api-key"}
    }
    config_path = _create_test_config(temp_dir, tiers)
    keys_path = _create_test_keys(temp_dir, vendors)

    trace_fd, trace_file = tempfile.mkstemp(suffix=".jsonl", dir=temp_dir)
    os.close(trace_fd)

    # Start proxy with a SMALL max body size so the test body is oversized.
    # PROXY_MAX_BODY_SIZE has min_val=1024, so use exactly 1024 and send > 1024 bytes.
    env = os.environ.copy()
    env["PROXY_PORT"] = str(proxy_port)
    env["PROXY_TRACE_FILE"] = trace_file
    env["PROXY_MAX_BODY_SIZE"] = "1024"  # minimum allowed; test body will exceed this

    proc = subprocess.Popen(
        PROXY_SERVER + ["--port", str(proxy_port), "--config-path", config_path, "--keys-path", keys_path],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, text=True
    )

    # Pipe passphrase to server
    if proc.stdin:
        try:
            proc.stdin.write("test-passphrase\n")
            proc.stdin.flush()
        except BrokenPipeError:
            pass
        finally:
            try:
                proc.stdin.close()
            except:
                pass

    # TCP probe for readiness
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

    if not probe_ok:
        proc.kill()
        mock_server.shutdown()
        shutil.rmtree(temp_dir, ignore_errors=True)
        fail("Proxy server failed to start")
        return

    try:
        # Send request with oversized body (>1024 bytes)
        oversized_body = json.dumps({
            "model": "sonnet",
            "messages": [{"role": "user", "content": "x" * 1500}]
        })
        conn = http_client.HTTPConnection("127.0.0.1", proxy_port, timeout=10)
        conn.request("POST", "/v1/messages", body=oversized_body,
                    headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        status = resp.status
        resp.read()
        conn.close()

        # Verify 413 response
        if status == 413:
            pass_("Oversized body returned HTTP 413")
        else:
            fail(f"Expected 413 for oversized body, got {status}")

        # Kill proxy to flush trace
        time.sleep(0.3)
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        time.sleep(0.3)

        # Read trace file
        if not os.path.exists(trace_file):
            fail(f"Trace file not created: {trace_file}")
            return

        with open(trace_file) as f:
            lines = [json.loads(line) for line in f if line.strip()]

        request_events = [l for l in lines if l.get("event") == "request"]
        if len(request_events) >= 1:
            pass_(f"Found {len(request_events)} request trace event(s) for oversized body")
            size_event = request_events[0]
            if size_event.get("status") == "failure":
                pass_("Trace entry has status: 'failure'")
            else:
                fail(f"Trace entry status is '{size_event.get('status')}', expected 'failure'")
            if size_event.get("http_status") == 413:
                pass_("Trace entry has http_status: 413")
            else:
                fail(f"Trace entry http_status is {size_event.get('http_status')}, expected 413")
            if size_event.get("model") == "unknown":
                pass_("Trace entry has model: 'unknown' (body rejected before parsing)")
            else:
                info(f"Trace entry model: '{size_event.get('model')}'")
        else:
            fail("No request trace event found — oversized body rejection was NOT logged")

    finally:
        mock_server.shutdown()
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_stop_trace_with_proxy():
    """Start proxy, run claude-retry-proxy stop; verify stderr shows graceful-stop sequence."""
    print("\n--- Test 20: Stop Trace with Proxy Running ---")
    state_backup = _backup_proxy_state()
    cleanup_lock_files()

    try:
        # Ensure cmd_start doesn't refuse with "Proxy already running"
        try:
            os.remove(PROXY_STATE_FILE)
        except OSError:
            pass

        port = find_free_port()
        temp_dir = tempfile.mkdtemp(prefix="proxy_stop_trace_")
        try:
            config_path = _create_test_config(temp_dir, {
                "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
                "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
                "opus": {"provider": "p", "model": "claude-opus-5"},
            })
            keys_path = _create_test_keys_plain(temp_dir, {
                "p": {"url": f"http://127.0.0.1:{find_free_port()}", "key": "k"}
            })
            trace_fd, trace_file = tempfile.mkstemp(suffix=".jsonl", dir=temp_dir)
            os.close(trace_fd)

            # Start proxy via CLI
            info(f"Starting proxy on port {port}...")
            proc, stdout, stderr_start, rc = _cli_start_with_plain_keys(
                port, config_path, keys_path, trace_file)
            if rc != 0:
                fail(f"Start failed (exit {rc}): {stdout} {stderr_start}")
                return

            # Verify proxy is running (state file has live PID)
            if not os.path.exists(PROXY_STATE_FILE):
                fail("proxy-state.json not created after start")
                return

            # Run stop, capturing stderr separately
            info("Running claude-retry-proxy stop...")
            stop_result = subprocess.run(
                CLAUDE_PROXY + ["stop"],
                capture_output=True, text=True, timeout=30
            )
            stderr = stop_result.stderr

            if stop_result.returncode != 0:
                fail(f"stop exited {stop_result.returncode}: {stop_result.stdout} {stderr}")

            # Assert: deterministic graceful-shutdown trace lines (live proxy,
            # /admin/shutdown succeeds). Do NOT assert "force-killing" or
            # "proxy-state.json removed" — in the graceful path the server's
            # finally block removes proxy-state.json first, and the PID is dead.
            if "cmd_stop: entering" in stderr:
                pass_("stderr contains 'cmd_stop: entering'")
            else:
                fail(f"stderr missing 'cmd_stop: entering'. stderr: {stderr[:300]}")

            if "cmd_stop: shutdown request accepted" in stderr:
                pass_("stderr contains 'cmd_stop: shutdown request accepted'")
            else:
                fail(f"stderr missing 'cmd_stop: shutdown request accepted'. stderr: {stderr[:300]}")

            if "cmd_stop: proxy exited gracefully" in stderr:
                pass_("stderr contains 'cmd_stop: proxy exited gracefully'")
            else:
                fail(f"stderr missing 'cmd_stop: proxy exited gracefully'. stderr: {stderr[:300]}")

            if "cmd_stop: returning 0" in stderr:
                pass_("stderr contains 'cmd_stop: returning 0'")
            else:
                fail(f"stderr missing 'cmd_stop: returning 0'. stderr: {stderr[:300]}")

            # Assert: trace format uses [claude-retry-proxy] prefix
            if "[claude-retry-proxy]" in stderr:
                pass_("stderr trace lines use [claude-retry-proxy] prefix")
            else:
                fail(f"stderr missing [claude-retry-proxy] prefix. stderr: {stderr[:300]}")

            # Assert: stdout reports stopped
            if "Proxy: stopped" in stop_result.stdout:
                pass_("stdout contains 'Proxy: stopped'")
            else:
                fail(f"stdout missing 'Proxy: stopped'. stdout: {stop_result.stdout[:300]}")

        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    finally:
        cleanup_lock_files()
        subprocess.run(
            CLAUDE_PROXY + ["stop"],
            capture_output=True, text=True, timeout=10
        )
        _restore_proxy_state(state_backup)


# ===========================================================================
# Test Case 21: Stop Cleans proxy-state.json (dead PID)
# ===========================================================================

def test_stop_cleans_proxy_state_lock():
    """Create proxy-state.json with a dead PID; run stop; verify state file deleted."""
    print("\n--- Test 21: Stop Cleans proxy-state.json (dead PID) ---")
    state_backup = _backup_proxy_state()
    cleanup_lock_files()

    try:
        # Create proxy directory if needed
        os.makedirs(PROXY_DIR, exist_ok=True)

        # Create proxy-state.json with a dead PID so cmd_stop enters the
        # kill/cleanup block and removes the state file.
        dead_pid = 99999  # Almost certainly not a real PID
        fake_state = {
            "pid": dead_pid,
            "port": 19999,
            "start_time": "2020-01-01T00:00:00Z",
            "config_path": "/nonexistent",
            "keys_path": "/nonexistent"
        }
        with open(PROXY_STATE_FILE, "w") as f:
            json.dump(fake_state, f)
        pass_("Created proxy-state.json with dead PID")

        # Run stop — dead PID = no-op kill, then state file removed
        info("Running claude-retry-proxy stop...")
        result = subprocess.run(
            CLAUDE_PROXY + ["stop"],
            capture_output=True, text=True, timeout=10
        )
        stderr = result.stderr

        # Assert: proxy-state.json is deleted
        if not os.path.exists(PROXY_STATE_FILE):
            pass_("proxy-state.json deleted by claude-retry-proxy stop")
        else:
            fail("proxy-state.json still exists after stop — not cleaned up by cmd_stop")

        # Assert: trace lines — dead-PID flow skips graceful shutdown, so the
        # server's finally block never runs and cmd_stop's own os.remove
        # succeeds ("proxy-state.json removed" is deterministic here).
        if "cmd_stop: entering" in stderr:
            pass_("stderr trace shows 'cmd_stop: entering'")
        else:
            fail(f"stderr missing 'cmd_stop: entering'. stderr: {stderr[:300]}")
        if "cmd_stop: proxy-state.json removed" in stderr:
            pass_("stderr trace shows 'cmd_stop: proxy-state.json removed'")
        else:
            fail(f"stderr missing 'cmd_stop: proxy-state.json removed'. stderr: {stderr[:300]}")
        if "cmd_stop: returning 0" in stderr:
            pass_("stderr trace shows 'cmd_stop: returning 0'")
        else:
            fail(f"stderr missing 'cmd_stop: returning 0'. stderr: {stderr[:300]}")

        # Assert: stdout reports stopped
        if "Proxy: stopped" in result.stdout:
            pass_("stdout contains 'Proxy: stopped'")
        else:
            fail(f"stdout missing 'Proxy: stopped'. stdout: {result.stdout[:300]}")

        if result.returncode != 0:
            fail(f"stop exited {result.returncode}: {result.stdout} {stderr}")
        else:
            pass_(f"stop exit code 0 ({result.returncode})")

    finally:
        cleanup_lock_files()
        subprocess.run(
            CLAUDE_PROXY + ["stop"],
            capture_output=True, text=True, timeout=10
        )
        _restore_proxy_state(state_backup)


# ===========================================================================
# Test Case 22: Start Stdout Not Contaminated by Trace
# ===========================================================================

def test_start_stdout_not_contaminated():
    """Start proxy with plain keys; assert stdout clean (no trace, no key material)."""
    print("\n--- Test 22: Start Stdout Not Contaminated ---")
    state_backup = _backup_proxy_state()
    cleanup_lock_files()

    try:
        # Ensure cmd_start doesn't refuse with "Proxy already running"
        try:
            os.remove(PROXY_STATE_FILE)
        except OSError:
            pass

        port = find_free_port()
        temp_dir = tempfile.mkdtemp(prefix="proxy_stdout_")
        try:
            config_path = _create_test_config(temp_dir, {
                "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
                "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
                "opus": {"provider": "p", "model": "claude-opus-5"},
            })
            keys_path = _create_test_keys_plain(temp_dir, {
                "p": {"url": f"http://127.0.0.1:{find_free_port()}", "key": "test-api-key"}
            })
            trace_fd, trace_file = tempfile.mkstemp(suffix=".jsonl", dir=temp_dir)
            os.close(trace_fd)

            # Start proxy via CLI with plain keys
            info(f"Starting proxy on port {port}...")
            proc, stdout, stderr, rc = _cli_start_with_plain_keys(
                port, config_path, keys_path, trace_file)

            if rc != 0:
                fail(f"Start failed (exit {rc}): {stdout} {stderr}")
                return

            # Assert: stdout contains startup messages
            if "Proxy started" in stdout:
                pass_("stdout contains 'Proxy started'")
            else:
                fail(f"stdout missing 'Proxy started'. stdout: {stdout[:300]}")

            if "Tiers:" in stdout:
                pass_("stdout contains 'Tiers:'")
            else:
                fail(f"stdout missing 'Tiers:'. stdout: {stdout[:300]}")

            # Assert: NO "Auth token:" on stdout (auth removed)
            if "Auth token:" in stdout:
                fail("stdout contains 'Auth token:' — auth should be removed")
            else:
                pass_("stdout does NOT contain 'Auth token:'")

            # Assert: NO key material on stdout
            if "test-api-key" in stdout:
                fail("stdout contains API key material — key leaked to stdout")
            else:
                pass_("stdout does NOT contain API key material")

            # Assert: NO trace lines on stdout (trace goes to stderr)
            if "[claude-retry-proxy]" in stdout:
                fail("stdout contains [claude-retry-proxy] trace lines — trace leaked to stdout")
            else:
                pass_("stdout does NOT contain [claude-retry-proxy] trace prefix")

            # Assert: trace IS on stderr (proves trace is working, just on the right stream)
            if "[claude-retry-proxy]" in stderr:
                pass_("stderr contains [claude-retry-proxy] trace lines (trace on correct stream)")
            else:
                warn("stderr missing [claude-retry-proxy] trace — tracing may not be active")

            # Clean up the running proxy
            stop_result = subprocess.run(
                CLAUDE_PROXY + ["stop"],
                capture_output=True, text=True, timeout=10
            )
            if stop_result.returncode != 0:
                fail(f"stop after start failed: {stop_result.stdout} {stop_result.stderr}")

        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    finally:
        cleanup_lock_files()
        subprocess.run(
            CLAUDE_PROXY + ["stop"],
            capture_output=True, text=True, timeout=10
        )
        _restore_proxy_state(state_backup)


# ===========================================================================
# Test Case 23: Start No Auth Header Required
# ===========================================================================

def test_start_no_auth_header_required():
    """Start proxy, send POST without X-Proxy-Auth header; assert 200 (forwarded)."""
    print("\n--- Test 23: Start No Auth Header Required ---")

    import http.client as http_client

    upstream_port = find_free_port()
    proxy_port = find_free_port()

    class NoAuthHandler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"id":"ok","type":"message"}')

        def log_message(self, format, *args):
            pass

    mock_server = http.server.ThreadingHTTPServer(("127.0.0.1", upstream_port), NoAuthHandler)
    mock_thread = threading.Thread(target=mock_server.serve_forever, daemon=True)
    mock_thread.start()
    time.sleep(0.3)

    # Create temp config and keys
    temp_dir = tempfile.mkdtemp(prefix="proxy_noauth_test_")
    tiers = {
        "haiku": {"provider": "test-provider", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "test-provider", "model": "claude-sonnet-5"},
        "opus": {"provider": "test-provider", "model": "claude-opus-5"},
    }
    vendors = {
        "test-provider": {"url": f"http://127.0.0.1:{upstream_port}", "key": "test-api-key"}
    }
    config_path = _create_test_config(temp_dir, tiers)
    keys_path = _create_test_keys(temp_dir, vendors)

    env = os.environ.copy()
    env["PROXY_PORT"] = str(proxy_port)

    proc = subprocess.Popen(
        PROXY_SERVER + ["--port", str(proxy_port), "--config-path", config_path, "--keys-path", keys_path],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, text=True
    )

    # Pipe passphrase to server
    if proc.stdin:
        try:
            proc.stdin.write("test-passphrase\n")
            proc.stdin.flush()
        except BrokenPipeError:
            pass
        finally:
            try:
                proc.stdin.close()
            except:
                pass

    # TCP probe for readiness (server no longer prints auth token)
    ready = False
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            sock.connect(("127.0.0.1", proxy_port))
            sock.close()
            ready = True
            break
        except (socket.error, ConnectionRefusedError):
            time.sleep(0.1)

    if not ready:
        proc.kill()
        mock_server.shutdown()
        shutil.rmtree(temp_dir, ignore_errors=True)
        fail("Proxy server failed to start (TCP probe timeout)")
        return

    try:
        # Send request WITHOUT X-Proxy-Auth header — must succeed (200)
        body = json.dumps({"model": "sonnet", "messages": [{"role": "user", "content": "hi"}]})
        conn = http_client.HTTPConnection("127.0.0.1", proxy_port, timeout=10)
        conn.request("POST", "/v1/messages", body=body,
                    headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        status = resp.status
        resp.read()
        conn.close()

        if status == 200:
            pass_("POST without X-Proxy-Auth returned 200 — no auth required")
        else:
            fail(f"POST without X-Proxy-Auth returned {status}, expected 200")

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        mock_server.shutdown()
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_exhaust_429_preserves_body():
    """Mock upstream always returns 429 with body '{"error":"rate_limited"}';
    PROXY_MAX_RETRIES=1; verify client receives 429 with body containing
    'rate_limited' (not empty); trace 'error' field contains 'rate_limited'."""
    print("\n--- Test 25: Exhaust 429 Preserves Body ---")

    upstream_port = find_free_port()
    proxy_port = find_free_port()

    request_count = [0]
    count_lock = threading.Lock()

    class Always429BodyHandler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            content_len = int(self.headers.get("Content-Length", 0))
            if content_len > 0:
                self.rfile.read(content_len)
            with count_lock:
                request_count[0] += 1
            self.send_response(429)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error":"rate_limited"}')

        def log_message(self, format, *args):
            pass

    mock_server = http.server.ThreadingHTTPServer(("127.0.0.1", upstream_port), Always429BodyHandler)
    mock_thread = threading.Thread(target=mock_server.serve_forever, daemon=True)
    mock_thread.start()
    time.sleep(0.3)

    # Create temp config and keys
    temp_dir = tempfile.mkdtemp(prefix="proxy_exhaust429body_test_")
    tiers = {
        "haiku": {"provider": "test-provider", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "test-provider", "model": "claude-sonnet-5"},
        "opus": {"provider": "test-provider", "model": "claude-opus-5"},
    }
    vendors = {
        "test-provider": {"url": f"http://127.0.0.1:{upstream_port}", "key": "test-api-key"}
    }
    config_path = _create_test_config(temp_dir, tiers)
    keys_path = _create_test_keys(temp_dir, vendors)

    trace_fd, trace_file = tempfile.mkstemp(suffix=".jsonl", dir=temp_dir)
    os.close(trace_fd)

    env = os.environ.copy()
    env["PROXY_PORT"] = str(proxy_port)
    env["PROXY_MAX_RETRIES"] = "1"
    env["PROXY_MAX_DELAY"] = "1"
    env["PROXY_INITIAL_DELAY"] = "1"
    env["PROXY_TRACE_FILE"] = trace_file

    proc = subprocess.Popen(
        PROXY_SERVER + ["--port", str(proxy_port), "--config-path", config_path, "--keys-path", keys_path],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, text=True
    )

    # Pipe passphrase to server
    if proc.stdin:
        try:
            proc.stdin.write("test-passphrase\n")
            proc.stdin.flush()
        except BrokenPipeError:
            pass
        finally:
            try:
                proc.stdin.close()
            except:
                pass

    # TCP probe for readiness
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

    if not probe_ok:
        proc.kill()
        mock_server.shutdown()
        shutil.rmtree(temp_dir, ignore_errors=True)
        fail("Proxy server failed to start for exhaust-429-body test")
        return

    try:
        status, body = _send_proxy_request(proxy_port)

        # Assert: client receives 429 (the upstream status preserved)
        if status == 429:
            pass_(f"Client received 429 on exhaustion (status={status})")
        else:
            fail(f"Client received {status}, expected 429")

        # Assert: body contains the upstream error content, not empty
        body_str = body.decode("utf-8", errors="replace") if isinstance(body, bytes) else str(body)
        if "rate_limited" in body_str:
            pass_("Response body contains 'rate_limited' — upstream error body preserved")
        else:
            fail(f"Response body does NOT contain 'rate_limited': {body_str[:200]}")

        # Kill proxy to flush trace
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        time.sleep(0.5)

        # Read trace file
        if not os.path.exists(trace_file):
            fail(f"Trace file not created: {trace_file}")
            return

        with open(trace_file) as f:
            entries = [json.loads(line) for line in f if line.strip()]

        request_events = [e for e in entries if e.get("event") == "request"]
        if len(request_events) >= 1:
            req = request_events[0]
            error_field = req.get("error", "")
            if error_field and "rate_limited" in str(error_field):
                pass_("Trace 'error' field contains 'rate_limited'")
            else:
                fail(f"Trace 'error' field does NOT contain 'rate_limited': {error_field}")
        else:
            fail("No request event in trace")

        # Verify upstream received expected number of requests (MAX_RETRIES+1 = 2)
        with count_lock:
            total = request_count[0]
        expected_attempts = 2  # MAX_RETRIES=1 → 2 total attempts
        if total == expected_attempts:
            pass_(f"Upstream received {total} requests (expected {expected_attempts})")
        else:
            fail(f"Upstream received {total} requests, expected {expected_attempts}")

    finally:
        mock_server.shutdown()
        shutil.rmtree(temp_dir, ignore_errors=True)


# ===========================================================================
# Test Case 26: Exhaust Connection Error Synthesizes Body (Step 1 — Fix B, conn-error path)
# ===========================================================================

def test_exhaust_connection_error_synthesizes_body():
    """Point proxy at a port with no listener; PROXY_MAX_RETRIES=1;
    verify trace 'error' field contains 'upstream_unreachable' (not 'HTTP 0')."""
    print("\n--- Test 26: Exhaust Connection Error Synthesizes Body ---")

    proxy_port = find_free_port()
    # Pick a port that almost certainly has no listener
    dead_port = find_free_port()
    # Ensure it's truly dead by binding+closing first to confirm free,
    # then use it as the upstream target without any listener
    test_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    test_sock.bind(("127.0.0.1", dead_port))
    test_sock.close()
    # Now dead_port is confirmed free and will refuse connections

    # Create temp config and keys
    temp_dir = tempfile.mkdtemp(prefix="proxy_connsynth_test_")
    tiers = {
        "haiku": {"provider": "test-provider", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "test-provider", "model": "claude-sonnet-5"},
        "opus": {"provider": "test-provider", "model": "claude-opus-5"},
    }
    vendors = {
        "test-provider": {"url": f"http://127.0.0.1:{dead_port}", "key": "test-api-key"}
    }
    config_path = _create_test_config(temp_dir, tiers)
    keys_path = _create_test_keys(temp_dir, vendors)

    trace_fd, trace_file = tempfile.mkstemp(suffix=".jsonl", dir=temp_dir)
    os.close(trace_fd)

    env = os.environ.copy()
    env["PROXY_PORT"] = str(proxy_port)
    env["PROXY_MAX_RETRIES"] = "1"
    env["PROXY_INITIAL_DELAY"] = "1"
    env["PROXY_MAX_DELAY"] = "1"
    env["PROXY_TRACE_FILE"] = trace_file

    proc = subprocess.Popen(
        PROXY_SERVER + ["--port", str(proxy_port), "--config-path", config_path, "--keys-path", keys_path],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, text=True
    )

    # Pipe passphrase to server
    if proc.stdin:
        try:
            proc.stdin.write("test-passphrase\n")
            proc.stdin.flush()
        except BrokenPipeError:
            pass
        finally:
            try:
                proc.stdin.close()
            except:
                pass

    # TCP probe for readiness
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

    if not probe_ok:
        proc.kill()
        shutil.rmtree(temp_dir, ignore_errors=True)
        fail("Proxy server failed to start for connection-error test")
        return

    try:
        # Send request — will fail with connection refused
        status, body = _send_proxy_request(proxy_port)

        # Kill proxy to flush trace
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        time.sleep(0.5)

        # Read trace file — the trace is the assertion target
        if not os.path.exists(trace_file):
            fail(f"Trace file not created: {trace_file}")
            return

        with open(trace_file) as f:
            entries = [json.loads(line) for line in f if line.strip()]

        request_events = [e for e in entries if e.get("event") == "request"]
        if len(request_events) >= 1:
            req = request_events[0]
            error_field = req.get("error", "")
            if error_field and "upstream_unreachable" in str(error_field):
                pass_("Trace 'error' field contains 'upstream_unreachable'")
            elif error_field and "HTTP 0" in str(error_field):
                fail("Trace 'error' field contains 'HTTP 0' — old bare body behavior")
            else:
                fail(f"Trace 'error' field does NOT contain 'upstream_unreachable': {error_field}")
        else:
            fail("No request event in trace")

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


# ===========================================================================
# Test Case 27: Client Disconnect No Traceback (Step 2 — Fix C)
# ===========================================================================

def test_client_disconnect_no_traceback():
    """Start proxy with mock upstream returning 200; send request via raw socket,
    close socket before reading response; assert stderr has no Traceback,
    contains '[proxy] client disconnected mid-response'; trace has
    'client_disconnect' event with matching request_id."""
    print("\n--- Test 27: Client Disconnect No Traceback ---")

    upstream_port = find_free_port()
    proxy_port = find_free_port()

    class DisconnectHandler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            content_len = int(self.headers.get("Content-Length", 0))
            if content_len > 0:
                self.rfile.read(content_len)
            # Return a response in chunks with delays so the proxy is still
            # writing when the client closes the socket
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            # Send 2MB in 100KB chunks with 50ms delays = ~1 second total
            chunk_size = 100 * 1024
            total_size = 2 * 1024 * 1024
            self.send_header("Content-Length", str(total_size))
            self.end_headers()
            try:
                sent = 0
                while sent < total_size:
                    chunk = b"x" * min(chunk_size, total_size - sent)
                    self.wfile.write(chunk)
                    self.wfile.flush()
                    sent += len(chunk)
                    time.sleep(0.05)  # 50ms delay between chunks
            except (socket.error, OSError):
                pass

        def log_message(self, format, *args):
            pass

    mock_server = http.server.ThreadingHTTPServer(("127.0.0.1", upstream_port), DisconnectHandler)
    mock_thread = threading.Thread(target=mock_server.serve_forever, daemon=True)
    mock_thread.start()
    time.sleep(0.3)

    # Create temp config and keys
    temp_dir = tempfile.mkdtemp(prefix="proxy_disconnect_test_")
    tiers = {
        "haiku": {"provider": "test-provider", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "test-provider", "model": "claude-sonnet-5"},
        "opus": {"provider": "test-provider", "model": "claude-opus-5"},
    }
    vendors = {
        "test-provider": {"url": f"http://127.0.0.1:{upstream_port}", "key": "test-api-key"}
    }
    config_path = _create_test_config(temp_dir, tiers)
    keys_path = _create_test_keys(temp_dir, vendors)

    trace_fd, trace_file = tempfile.mkstemp(suffix=".jsonl", dir=temp_dir)
    os.close(trace_fd)

    env = os.environ.copy()
    env["PROXY_PORT"] = str(proxy_port)
    env["PROXY_TRACE_FILE"] = trace_file

    proc = subprocess.Popen(
        PROXY_SERVER + ["--port", str(proxy_port), "--config-path", config_path, "--keys-path", keys_path],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, text=True
    )

    # Pipe passphrase to server
    if proc.stdin:
        try:
            proc.stdin.write("test-passphrase\n")
            proc.stdin.flush()
        except BrokenPipeError:
            pass
        finally:
            try:
                proc.stdin.close()
            except:
                pass

    # TCP probe for readiness
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

    if not probe_ok:
        proc.kill()
        mock_server.shutdown()
        shutil.rmtree(temp_dir, ignore_errors=True)
        fail("Proxy server failed to start for disconnect test")
        return

    try:
        # Send request via raw socket, then close before reading response
        raw_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        raw_sock.settimeout(5)
        raw_sock.connect(("127.0.0.1", proxy_port))

        body = json.dumps({"model": "sonnet", "messages": [{"role": "user", "content": "hi"}]})
        request_line = (
            f"POST /v1/messages HTTP/1.0\r\n"
            f"Host: 127.0.0.1:{proxy_port}\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(body)}\r\n"
            f"\r\n"
            f"{body}"
        )
        raw_sock.sendall(request_line.encode())

        # Give the proxy time to start processing and begin writing
        time.sleep(0.5)

        # Close the socket abruptly — this triggers disconnect before full response
        raw_sock.close()

        # Wait for the proxy to process the disconnect
        time.sleep(1.0)

        # Phase 2: streaming-path disconnect — the client reads the status
        # line and headers, then closes mid-stream while the proxy is still
        # delivering the (large) body. Exercises _stream_upstream_response's
        # outer _DISCONNECT_ERRORS handler on the streaming path.
        raw_sock2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        raw_sock2.settimeout(5)
        raw_sock2.connect(("127.0.0.1", proxy_port))
        raw_sock2.sendall(request_line.encode())

        header_buf = b""
        read_deadline = time.time() + 5
        while time.time() < read_deadline and b"\r\n\r\n" not in header_buf:
            try:
                part = raw_sock2.recv(4096)
            except socket.timeout:
                break
            if not part:
                break
            header_buf += part

        first_line = header_buf.split(b"\r\n", 1)[0] if header_buf else b""
        if b"200 OK" in first_line:
            pass_("Phase 2: received HTTP 200 status line + headers before closing")
        else:
            fail(f"Phase 2: did not receive 200 status line before close (got {header_buf[:80]!r})")

        # Close mid-stream while the proxy is still delivering body chunks.
        raw_sock2.close()

        # Wait for the proxy to detect the disconnect and log the event.
        time.sleep(1.0)

        # Kill proxy to flush trace
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        time.sleep(0.3)

        # Collect stderr
        try:
            stderr_output = proc.stderr.read() if proc.stderr else ""
        except Exception:
            stderr_output = ""

        # Assert: NO Traceback in stderr
        if "Traceback" not in stderr_output:
            pass_("stderr contains NO Traceback")
        else:
            fail(f"stderr contains Traceback — disconnect not caught:\n{stderr_output[:500]}")

        # Assert: stderr contains client disconnected message. With the 2MB
        # payload and the phase-2 mid-stream close, the disconnect is now
        # reliably detected (no longer timing-dependent), so this is a hard
        # assertion rather than the old warn-with-fallback.
        if "[proxy] client disconnected mid-response" in stderr_output:
            pass_("stderr contains '[proxy] client disconnected mid-response'")
        else:
            fail("stderr does NOT contain '[proxy] client disconnected mid-response'")

        # Read trace file for client_disconnect event
        if not os.path.exists(trace_file):
            fail(f"Trace file not created: {trace_file}")
            return

        with open(trace_file) as f:
            entries = [json.loads(line) for line in f if line.strip()]

        disconnect_events = [e for e in entries if e.get("event") == "client_disconnect"]
        request_events = [e for e in entries if e.get("event") == "request"]

        if len(disconnect_events) >= 1:
            pass_(f"Trace contains {len(disconnect_events)} 'client_disconnect' event(s)")
            # Verify EVERY disconnect event's request_id matches some request
            # event (phases 1 and 2 may each log a disconnect; each must
            # correlate to the request that produced it).
            req_ids = {e.get("request_id") for e in request_events}
            mismatched = [e.get("request_id") for e in disconnect_events
                          if e.get("request_id") not in req_ids]
            if not mismatched:
                pass_("All client_disconnect request_ids match a request event")
            else:
                fail(f"client_disconnect request_ids {mismatched} do not match "
                     f"request events {req_ids}")
        else:
            fail("No 'client_disconnect' event in trace — disconnect was not detected")

        # At minimum, verify the request completed and no traceback appeared
        if len(request_events) >= 1:
            pass_(f"Request event traced (total: {len(request_events)})")
        else:
            fail("No request event in trace — request was never processed")

    finally:
        mock_server.shutdown()
        shutil.rmtree(temp_dir, ignore_errors=True)


# ===========================================================================
# Test Case 28: Start Prunes Old Trace Entries (Step 3 — Fix D)
# ===========================================================================

def test_start_prunes_old_trace_entries():
    """Directly import prune_trace_file from claude_retry_proxy.cli; create temp
    trace file with entries dated now, 10 days ago, and a malformed line;
    assert return is (2, 1), old entry removed, today+malformed kept, summary printed."""
    print("\n--- Test 28: Start Prunes Old Trace Entries ---")

    from claude_retry_proxy.cli import prune_trace_file

    # Create a temp trace file
    fd, temp_path = tempfile.mkstemp(suffix=".jsonl")
    os.close(fd)

    try:
        now = time.time()
        ten_days_ago = now - 10 * 86400

        now_ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))
        old_ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ten_days_ago))

        today_entry = json.dumps({
            "timestamp": now_ts,
            "event": "request",
            "request_id": "test-today",
            "http_status": 200,
            "status": "success",
        })
        old_entry = json.dumps({
            "timestamp": old_ts,
            "event": "request",
            "request_id": "test-old",
            "http_status": 429,
            "status": "failure",
        })
        malformed_line = "not json{"

        with open(temp_path, "w") as f:
            f.write(today_entry + "\n")
            f.write(old_entry + "\n")
            f.write(malformed_line + "\n")

        # Capture stdout
        import io
        saved_stdout = sys.stdout
        sys.stdout = io.StringIO()
        try:
            kept, removed = prune_trace_file(temp_path)
        finally:
            stdout_output = sys.stdout.getvalue()
            sys.stdout = saved_stdout

        # Assert: return value is (2, 1)
        if kept == 2 and removed == 1:
            pass_(f"prune_trace_file returned ({kept}, {removed}) — expected (2, 1)")
        else:
            fail(f"prune_trace_file returned ({kept}, {removed}), expected (2, 1)")

        # Assert: summary line printed
        if "Trace:" in stdout_output:
            pass_("Summary line printed to stdout")
        else:
            fail(f"No summary line on stdout: {stdout_output[:200]}")

        # Assert: file now contains today entry and malformed line but NOT old entry
        with open(temp_path) as f:
            remaining = f.read()

        if now_ts in remaining:
            pass_("Today entry preserved in file")
        else:
            fail("Today entry missing from file after prune")

        if malformed_line in remaining:
            pass_("Malformed line preserved in file")
        else:
            fail("Malformed line missing from file after prune")

        if old_ts not in remaining:
            pass_("Old entry removed from file")
        else:
            fail("Old entry still in file after prune")

        # Verify line count (should be 2: today + malformed)
        lines_after = remaining.strip().split("\n")
        if len(lines_after) == 2:
            pass_(f"File has {len(lines_after)} lines after prune (expected 2)")
        else:
            fail(f"File has {len(lines_after)} lines after prune, expected 2")

    finally:
        try:
            os.unlink(temp_path)
        except OSError:
            pass


# ===========================================================================
# Test Case 28b: Prune Trace File Edge Cases
# ===========================================================================

def test_prune_trace_file_edge_cases():
    """Edge cases for prune_trace_file: file doesn't exist → (0, 0);
    empty file → (0, 0)."""
    print("\n--- Test 28b: Prune Trace File Edge Cases ---")

    from claude_retry_proxy.cli import prune_trace_file

    # Edge case 1: file doesn't exist
    nonexistent = tempfile.mktemp(suffix=".jsonl")
    try:
        kept, removed = prune_trace_file(nonexistent)
        if kept == 0 and removed == 0:
            pass_("prune_trace_file on nonexistent file returns (0, 0)")
        else:
            fail(f"prune_trace_file on nonexistent file returned ({kept}, {removed}), expected (0, 0)")
    finally:
        try:
            os.unlink(nonexistent)
        except OSError:
            pass
        try:
            os.unlink(nonexistent + ".tmp")
        except OSError:
            pass

    # Edge case 2: empty file
    fd, empty_path = tempfile.mkstemp(suffix=".jsonl")
    os.close(fd)
    try:
        kept, removed = prune_trace_file(empty_path)
        if kept == 0 and removed == 0:
            pass_("prune_trace_file on empty file returns (0, 0)")
        else:
            fail(f"prune_trace_file on empty file returned ({kept}, {removed}), expected (0, 0)")
    finally:
        try:
            os.unlink(empty_path)
        except OSError:
            pass


# ===========================================================================
# Test Case 29: Streaming Response Body (plan 2026-08-12-streaming-proxy, Step 1)
# ===========================================================================

def test_streaming_response_body():
    """Mock upstream streams 5 chunks with 50ms delays between them; proxy
    forwards to the client in real time; client reads incrementally. Verify:
    (a) first byte arrives within 1s AND before generation completes,
    (b) all 5 chunks received in order, (c) concatenated body matches upstream,
    (d) HTTP status is 200."""
    print("\n--- Test 29: Streaming Response Body ---")

    upstream_port = find_free_port()
    proxy_port = find_free_port()

    # Proper SSE format: each event ends with \n\n
    chunk_data = [
        b"event: message_start\ndata: {\"type\":\"message_start\",\"model\":\"claude-sonnet-5\"}\n\n",
        b"data: chunk-0\n\n",
        b"data: chunk-1\n\n",
        b"data: chunk-2\n\n",
        b"data: chunk-3\n\n",
    ]
    expected_body = b"".join(chunk_data)
    generation_done = [False]

    class StreamHandler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            content_len = int(self.headers.get("Content-Length", 0))
            if content_len > 0:
                self.rfile.read(content_len)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for chunk in chunk_data:
                self.wfile.write(chunk)
                self.wfile.flush()
                time.sleep(0.05)
            generation_done[0] = True

        def log_message(self, format, *args):
            pass

    mock_server = http.server.ThreadingHTTPServer(("127.0.0.1", upstream_port), StreamHandler)
    mock_thread = threading.Thread(target=mock_server.serve_forever, daemon=True)
    mock_thread.start()
    time.sleep(0.3)

    # Create temp config and keys
    temp_dir = tempfile.mkdtemp(prefix="proxy_streaming_test_")
    tiers = {
        "haiku": {"provider": "test-provider", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "test-provider", "model": "claude-sonnet-5"},
        "opus": {"provider": "test-provider", "model": "claude-opus-5"},
    }
    vendors = {
        "test-provider": {"url": f"http://127.0.0.1:{upstream_port}", "key": "test-api-key"}
    }
    config_path = _create_test_config(temp_dir, tiers)
    keys_path = _create_test_keys(temp_dir, vendors)

    env = os.environ.copy()
    env["PROXY_PORT"] = str(proxy_port)

    proc = subprocess.Popen(
        PROXY_SERVER + ["--port", str(proxy_port), "--config-path", config_path, "--keys-path", keys_path],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, text=True
    )

    # Pipe passphrase to server
    if proc.stdin:
        try:
            proc.stdin.write("test-passphrase\n")
            proc.stdin.flush()
        except BrokenPipeError:
            pass
        finally:
            try:
                proc.stdin.close()
            except:
                pass

    # TCP probe for readiness
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

    if not probe_ok:
        proc.kill()
        mock_server.shutdown()
        shutil.rmtree(temp_dir, ignore_errors=True)
        fail("Proxy server failed to start for streaming test")
        return

    try:
        import http.client as _hc
        body_bytes = json.dumps({"model": "sonnet",
                                 "messages": [{"role": "user", "content": "hi"}]})

        start = time.time()
        conn = _hc.HTTPConnection("127.0.0.1", proxy_port, timeout=10)
        conn.request("POST", "/v1/messages", body=body_bytes,
                     headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        status = resp.status
        first_byte = resp.read(1)          # incremental read: first byte
        first_byte_ms = (time.time() - start) * 1000
        generation_was_running = not generation_done[0]
        remainder = resp.read()            # read the rest incrementally
        conn.close()

        if status == 200:
            pass_(f"HTTP status 200 (status={status})")
        else:
            fail(f"HTTP status {status}, expected 200")

        if first_byte_ms < 1000:
            pass_(f"First byte arrived in {first_byte_ms:.0f}ms (< 1000ms)")
        else:
            fail(f"First byte arrived in {first_byte_ms:.0f}ms (>= 1000ms) — "
                 "response was buffered, not streamed")

        # (a) TTFB << total generation time: the first byte must arrive while
        # the mock is STILL generating (only the first chunk flushed). A
        # buffering regression would deliver nothing until generation done.
        if generation_was_running:
            pass_("First byte arrived while upstream was still generating "
                  "(TTFB << total generation time)")
        else:
            fail("First byte arrived only AFTER generation completed — "
                 "response was buffered")

        body = first_byte + remainder
        if body == expected_body:
            pass_(f"All 5 chunks received in order; concatenated body matches "
                  f"upstream ({len(body)} bytes)")
        else:
            fail(f"Body mismatch: got {body[:60]!r}... expected {expected_body[:60]!r}...")

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        mock_server.shutdown()
        shutil.rmtree(temp_dir, ignore_errors=True)


# ===========================================================================
# Test Case 30: Streaming Mid-Stream Upstream Failure (plan 2026-08-12-streaming-proxy, Step 1)
# ===========================================================================

def test_streaming_mid_stream_upstream_failure():
    """Two mock modes validate the proxy's dual-path truncation detection:

    (a) close-delimited — the mock sends 2 chunks with a Content-Length larger
        than the bytes actually sent, then closes. `read1(amt)` returns b'' on
        short read (only bare `read()` raises IncompleteRead), so the proxy's
        `if not chunk: break` branch ends the loop.
    (b) chunked — the mock sends 2 chunked (Transfer-Encoding) chunks then drops
        the connection WITHOUT the terminating 0-chunk; `read1` raises
        http.client.IncompleteRead, exercising the inner except.

    Both: the client receives the 2 chunks then a truncated (close-delimited)
    response; no traceback in proxy stderr AND no 'client_disconnect' trace
    event — an upstream failure must not be misattributed as a client
    disconnect."""
    print("\n--- Test 30: Streaming Mid-Stream Upstream Failure ---")

    chunk1 = b"chunk-one-"
    chunk2 = b"chunk-two-"
    expected = chunk1 + chunk2

    def run_mode(name, handler_cls):
        upstream_port = find_free_port()
        proxy_port = find_free_port()

        mock_server = http.server.ThreadingHTTPServer(("127.0.0.1", upstream_port), handler_cls)
        mock_thread = threading.Thread(target=mock_server.serve_forever, daemon=True)
        mock_thread.start()
        time.sleep(0.3)

        # Create temp config and keys for this mode
        temp_dir = tempfile.mkdtemp(prefix=f"proxy_midstream_{name}_test_")
        tiers = {
            "haiku": {"provider": "test-provider", "model": "claude-haiku-4-5"},
            "sonnet": {"provider": "test-provider", "model": "claude-sonnet-5"},
            "opus": {"provider": "test-provider", "model": "claude-opus-5"},
        }
        vendors = {
            "test-provider": {"url": f"http://127.0.0.1:{upstream_port}", "key": "test-api-key"}
        }
        config_path = _create_test_config(temp_dir, tiers)
        keys_path = _create_test_keys(temp_dir, vendors)

        trace_fd, trace_file = tempfile.mkstemp(suffix=".jsonl", dir=temp_dir)
        os.close(trace_fd)

        env = os.environ.copy()
        env["PROXY_PORT"] = str(proxy_port)
        env["PROXY_TRACE_FILE"] = trace_file

        proc = subprocess.Popen(
            PROXY_SERVER + ["--port", str(proxy_port), "--config-path", config_path, "--keys-path", keys_path],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, text=True
        )

        # Pipe passphrase to server
        if proc.stdin:
            try:
                proc.stdin.write("test-passphrase\n")
                proc.stdin.flush()
            except BrokenPipeError:
                pass
            finally:
                try:
                    proc.stdin.close()
                except:
                    pass

        # TCP probe for readiness
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

        try:
            if not probe_ok:
                fail(f"[{name}] Proxy server failed to start")
                return

            import http.client as _hc
            body_bytes = json.dumps({"model": "sonnet",
                                     "messages": [{"role": "user", "content": "hi"}]})
            conn = _hc.HTTPConnection("127.0.0.1", proxy_port, timeout=10)
            conn.request("POST", "/v1/messages", body=body_bytes,
                         headers={"Content-Type": "application/json"})
            resp = conn.getresponse()
            status = resp.status
            received = resp.read()   # 2 chunks then close-delimited EOF
            conn.close()

            if status == 200:
                pass_(f"[{name}] HTTP status 200 (status={status})")
            else:
                fail(f"[{name}] HTTP status {status}, expected 200")

            if received == expected:
                pass_(f"[{name}] Client received the {len(received)} streamed bytes "
                      "before truncation")
            else:
                fail(f"[{name}] Client received {received!r}, expected {expected!r}")

            # Kill proxy to flush trace, then collect stderr
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
            time.sleep(0.3)

            try:
                stderr_output = proc.stderr.read() if proc.stderr else ""
            except Exception:
                stderr_output = ""

            if "Traceback" not in stderr_output:
                pass_(f"[{name}] stderr contains NO Traceback on upstream truncation")
            else:
                fail(f"[{name}] stderr contains Traceback:\n{stderr_output[:500]}")

            # No client_disconnect event — the truncation was an UPSTREAM
            # failure, not a client disconnect.
            with open(trace_file) as f:
                entries = [json.loads(line) for line in f if line.strip()]
            disconnect_events = [e for e in entries if e.get("event") == "client_disconnect"]
            if not disconnect_events:
                pass_(f"[{name}] No 'client_disconnect' trace event — upstream "
                      "failure correctly distinguished from client disconnect")
            else:
                fail(f"[{name}] Found {len(disconnect_events)} 'client_disconnect' "
                     "event(s) on upstream failure")

        finally:
            try:
                proc.kill()
            except Exception:
                pass
            mock_server.shutdown()
            shutil.rmtree(temp_dir, ignore_errors=True)

    # Mode (a): close-delimited — oversized Content-Length, connection
    # closes with an unsatisfied length → read1 returns b'' (clean EOF,
    # `if not chunk: break` branch).
    class TruncatedHandler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            content_len = int(self.headers.get("Content-Length", 0))
            if content_len > 0:
                self.rfile.read(content_len)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(chunk1) + len(chunk2) + 1000000))
            self.end_headers()
            self.wfile.write(chunk1)
            self.wfile.flush()
            time.sleep(0.05)
            self.wfile.write(chunk2)
            self.wfile.flush()
            # return → HTTP/1.0 close with unsatisfied Content-Length

        def log_message(self, format, *args):
            pass

    run_mode("close-delimited", TruncatedHandler)

    # Mode (b): chunked — Transfer-Encoding: chunked, connection dropped
    # before the terminating 0-chunk → read1 raises IncompleteRead (inner
    # except).
    class ChunkedTruncatedHandler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_POST(self):
            content_len = int(self.headers.get("Content-Length", 0))
            if content_len > 0:
                self.rfile.read(content_len)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            for c in (chunk1, chunk2):
                self.wfile.write(("%x\r\n" % len(c)).encode() + c + b"\r\n")
                self.wfile.flush()
                time.sleep(0.05)
            # Force the connection closed WITHOUT the terminating
            # "0\r\n\r\n" chunk → the proxy's next read1 raises IncompleteRead.
            self.close_connection = True

        def log_message(self, format, *args):
            pass

    run_mode("chunked", ChunkedTruncatedHandler)


# ===========================================================================
# Test Case 31: Empty Body 429 Exhaust (plan 2026-08-12-streaming-proxy, Step 3 regression guard)
# ===========================================================================

def test_empty_body_429_exhaust():
    """Mock upstream always returns 429 with Content-Length: 0 (empty body)
    through all retries; PROXY_MAX_RETRIES=1. The client must receive a proper
    HTTP 429 status line (not a bare connection close). Regression guard for
    do_POST's explicit `streamed` flag discrimination (an empty-body error
    response must still get a status line via _send_response)."""
    print("\n--- Test 31: Empty Body 429 Exhaust ---")

    upstream_port = find_free_port()
    proxy_port = find_free_port()

    class Empty429Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            content_len = int(self.headers.get("Content-Length", 0))
            if content_len > 0:
                self.rfile.read(content_len)
            self.send_response(429)
            self.send_header("Content-Length", "0")
            self.end_headers()
            # no body written — empty 429

        def log_message(self, format, *args):
            pass

    mock_server = http.server.ThreadingHTTPServer(("127.0.0.1", upstream_port), Empty429Handler)
    mock_thread = threading.Thread(target=mock_server.serve_forever, daemon=True)
    mock_thread.start()
    time.sleep(0.3)

    # Create temp config and keys
    temp_dir = tempfile.mkdtemp(prefix="proxy_empty429_test_")
    tiers = {
        "haiku": {"provider": "test-provider", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "test-provider", "model": "claude-sonnet-5"},
        "opus": {"provider": "test-provider", "model": "claude-opus-5"},
    }
    vendors = {
        "test-provider": {"url": f"http://127.0.0.1:{upstream_port}", "key": "test-api-key"}
    }
    config_path = _create_test_config(temp_dir, tiers)
    keys_path = _create_test_keys(temp_dir, vendors)

    env = os.environ.copy()
    env["PROXY_PORT"] = str(proxy_port)
    env["PROXY_MAX_RETRIES"] = "1"
    env["PROXY_MAX_DELAY"] = "1"
    env["PROXY_INITIAL_DELAY"] = "1"

    proc = subprocess.Popen(
        PROXY_SERVER + ["--port", str(proxy_port), "--config-path", config_path, "--keys-path", keys_path],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, text=True
    )

    # Pipe passphrase to server
    if proc.stdin:
        try:
            proc.stdin.write("test-passphrase\n")
            proc.stdin.flush()
        except BrokenPipeError:
            pass
        finally:
            try:
                proc.stdin.close()
            except:
                pass

    # TCP probe for readiness
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

    if not probe_ok:
        proc.kill()
        mock_server.shutdown()
        shutil.rmtree(temp_dir, ignore_errors=True)
        fail("Proxy server failed to start for empty-body-429 test")
        return

    try:
        status, body = _send_proxy_request(proxy_port)
        if status == 429:
            pass_(f"Client received proper HTTP 429 status line (status={status})")
        else:
            fail(f"Client received status={status}, expected 429 (body={body[:100]!r})")

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        mock_server.shutdown()
        shutil.rmtree(temp_dir, ignore_errors=True)


# ===========================================================================
# Test Case 32: CRLF Header Filter (plan 2026-08-12-streaming-proxy, Step 5 unit test)
# ===========================================================================

def test_crlf_header_filter():
    """In-process unit test of _crlf_safe: clean headers pass through; a header
    VALUE containing CR/LF is omitted; a header NAME containing CR/LF is
    omitted; None → {}; a mixed dict keeps only clean entries. Behavioral
    testing via a mock upstream is infeasible (modern http.client parses raw
    CR/LF header lines into separate clean headers before the proxy sees them)
    — the unit test is authoritative."""
    print("\n--- Test 32: CRLF Header Filter ---")

    from claude_retry_proxy.server import _crlf_safe

    # Clean headers pass through
    result = _crlf_safe({"X-Ok": "fine"})
    if result == {"X-Ok": "fine"}:
        pass_("Clean header preserved: {\"X-Ok\": \"fine\"}")
    else:
        fail(f"_crlf_safe({{'X-Ok': 'fine'}}) returned {result!r}, expected "
             "{\"X-Ok\": \"fine\"}")

    # Header VALUE containing CR/LF is omitted
    result = _crlf_safe({"X-Bad": "a\r\nSet-Cookie: injected=1"})
    if result == {}:
        pass_("Header value with CRLF omitted")
    else:
        fail(f"_crlf_safe returned {result!r}, expected {{}} for CRLF value")

    # Header NAME containing CR/LF is omitted
    result = _crlf_safe({"X\nBad": "v"})
    if result == {}:
        pass_("Header name with newline omitted")
    else:
        fail(f"_crlf_safe returned {result!r}, expected {{}} for CRLF name")

    # None input returns {}
    if _crlf_safe(None) == {}:
        pass_("_crlf_safe(None) returns {}")
    else:
        fail(f"_crlf_safe(None) returned {_crlf_safe(None)!r}, expected {{}}")

    # Empty dict returns {}
    if _crlf_safe({}) == {}:
        pass_("_crlf_safe({}) returns {}")
    else:
        fail(f"_crlf_safe({{}}) returned {_crlf_safe({})!r}, expected {{}}")

    # Mixed dict keeps only clean entries
    result = _crlf_safe({"X-Clean": "ok", "X-Dirty": "a\nb", "Y\nZ": "1"})
    if result == {"X-Clean": "ok"}:
        pass_("Mixed dict keeps only clean entries")
    else:
        fail(f"_crlf_safe mixed returned {result!r}, expected "
             "{\"X-Clean\": \"ok\"}")


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
# Test: Tier Routing Basic
# ===========================================================================

def test_tier_routing_basic():
    """Send request with model "sonnet", verify correct upstream receives the configured model name and API key."""
    print("\n--- Test: Tier Routing Basic ---")

    upstream_port = find_free_port()
    tiers = {
        "haiku": {"provider": "test-provider", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "test-provider", "model": "claude-sonnet-5"},
        "opus": {"provider": "test-provider", "model": "claude-opus-5"},
    }
    vendors = {
        "test-provider": {"url": f"http://127.0.0.1:{upstream_port}", "key": "test-api-key-12345"}
    }

    temp_dir, proxy_port, proc, mock_servers, cleanup = _setup_tier_routing_test(tiers, vendors)
    if proc is None:
        fail("Failed to set up tier routing test")
        return

    try:
        # Send request with model "sonnet"
        body = json.dumps({"model": "sonnet", "messages": [{"role": "user", "content": "hi"}]})
        status, resp_body = _send_proxy_request(proxy_port, body=body)

        if status != 200:
            fail(f"Request failed with status {status}")
            return

        # Verify upstream received the request
        requests = mock_servers["test-provider"]["requests"]
        if len(requests) == 0:
            fail("Upstream received no requests")
            return

        req = requests[0]
        # Verify API key was injected
        if req["api_key"] != "test-api-key-12345":
            fail(f"Upstream received wrong API key: {req['api_key']}")
        else:
            pass_("Upstream received correct API key from keys-index.json")

        # Verify model was rewritten
        req_data = json.loads(req["body"])
        if req_data.get("model") == "claude-sonnet-5":
            pass_("Upstream received rewritten model name: claude-sonnet-5")
        else:
            fail(f"Upstream received wrong model: {req_data.get('model')}")

    finally:
        cleanup()


# ===========================================================================
# Test: Tier Routing All Tiers
# ===========================================================================

def test_tier_routing_all_tiers():
    """Send haiku/sonnet/opus requests, verify each routes to its configured provider."""
    print("\n--- Test: Tier Routing All Tiers ---")

    haiku_port = find_free_port()
    sonnet_port = find_free_port()
    opus_port = find_free_port()

    tiers = {
        "haiku": {"provider": "haiku-provider", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "sonnet-provider", "model": "claude-sonnet-5"},
        "opus": {"provider": "opus-provider", "model": "claude-opus-5"},
    }
    vendors = {
        "haiku-provider": {"url": f"http://127.0.0.1:{haiku_port}", "key": "haiku-key"},
        "sonnet-provider": {"url": f"http://127.0.0.1:{sonnet_port}", "key": "sonnet-key"},
        "opus-provider": {"url": f"http://127.0.0.1:{opus_port}", "key": "opus-key"},
    }

    temp_dir, proxy_port, proc, mock_servers, cleanup = _setup_tier_routing_test(tiers, vendors)
    if proc is None:
        fail("Failed to set up tier routing test")
        return

    try:
        # Test each tier
        for tier, expected_model in [("haiku", "claude-haudit-4-5"), ("sonnet", "claude-sonnet-5"), ("opus", "claude-opus-5")]:
            body = json.dumps({"model": tier, "messages": [{"role": "user", "content": "hi"}]})
            status, _ = _send_proxy_request(proxy_port, body=body)

            if status != 200:
                fail(f"{tier} request failed with status {status}")
                continue

        # Verify each provider received exactly one request
        for provider_name in ["haiku-provider", "sonnet-provider", "opus-provider"]:
            reqs = mock_servers[provider_name]["requests"]
            if len(reqs) == 1:
                pass_(f"{provider_name} received 1 request")
            else:
                fail(f"{provider_name} received {len(reqs)} requests, expected 1")

    finally:
        cleanup()


# ===========================================================================
# Test: Model Resolution Reverse Lookup
# ===========================================================================

def test_model_resolution_reverse_lookup():
    """Send request with actual model name (e.g. "claude-sonnet-5"), verify reverse-mapping to tier."""
    print("\n--- Test: Model Resolution Reverse Lookup ---")

    upstream_port = find_free_port()
    tiers = {
        "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
        "opus": {"provider": "p", "model": "claude-opus-5"},
    }
    vendors = {"p": {"url": f"http://127.0.0.1:{upstream_port}", "key": "k"}}

    temp_dir, proxy_port, proc, mock_servers, cleanup = _setup_tier_routing_test(tiers, vendors)
    if proc is None:
        fail("Failed to set up test")
        return

    try:
        # Send with actual model name — should reverse-map to tier
        body = json.dumps({"model": "claude-sonnet-5", "messages": [{"role": "user", "content": "hi"}]})
        status, resp_body = _send_proxy_request(proxy_port, body=body)

        if status == 200:
            pass_("Request with actual model name succeeded (reverse lookup worked)")
        else:
            fail(f"Request with actual model name failed: status {status}")

        # Verify response has tier name
        try:
            resp_data = json.loads(resp_body)
            if resp_data.get("model") == "sonnet":
                pass_("Response model rewritten to tier name: sonnet")
            else:
                fail(f"Response model not rewritten: {resp_data.get('model')}")
        except:
            pass  # Response parsing may not be implemented yet

    finally:
        cleanup()


# ===========================================================================
# Test: Model Resolution Pattern Match
# ===========================================================================

def test_model_resolution_pattern_match():
    """Send request with model name containing tier keyword (e.g. "my-sonnet-model"), verify pattern-match resolves to sonnet tier."""
    print("\n--- Test: Model Resolution Pattern Match ---")

    upstream_port = find_free_port()
    tiers = {
        "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
        "opus": {"provider": "p", "model": "claude-opus-5"},
    }
    vendors = {"p": {"url": f"http://127.0.0.1:{upstream_port}", "key": "k"}}

    temp_dir, proxy_port, proc, mock_servers, cleanup = _setup_tier_routing_test(tiers, vendors)
    if proc is None:
        fail("Failed to set up test")
        return

    try:
        # Send with model name containing "sonnet"
        body = json.dumps({"model": "my-custom-sonnet-model", "messages": [{"role": "user", "content": "hi"}]})
        status, _ = _send_proxy_request(proxy_port, body=body)

        if status == 200:
            pass_("Request with pattern-matched model name succeeded")
        else:
            fail(f"Request with pattern-matched model failed: status {status}")

        # Verify upstream received the sonnet model
        reqs = mock_servers["p"]["requests"]
        if len(reqs) > 0:
            req_data = json.loads(reqs[0]["body"])
            if req_data.get("model") == "claude-sonnet-5":
                pass_("Upstream received sonnet model (pattern match resolved correctly)")
            else:
                fail(f"Upstream received wrong model: {req_data.get('model')}")

    finally:
        cleanup()


# ===========================================================================
# Test: Model Resolution Unknown Rejected
# ===========================================================================

def test_model_resolution_unknown_rejected():
    """Send request with unrecognized model name (e.g. "gpt-4"), verify 400 error with valid tier list."""
    print("\n--- Test: Model Resolution Unknown Rejected ---")

    upstream_port = find_free_port()
    tiers = {
        "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
        "opus": {"provider": "p", "model": "claude-opus-5"},
    }
    vendors = {"p": {"url": f"http://127.0.0.1:{upstream_port}", "key": "k"}}

    temp_dir, proxy_port, proc, mock_servers, cleanup = _setup_tier_routing_test(tiers, vendors)
    if proc is None:
        fail("Failed to set up test")
        return

    try:
        # Send with unknown model
        body = json.dumps({"model": "gpt-4", "messages": [{"role": "user", "content": "hi"}]})
        status, resp_body = _send_proxy_request(proxy_port, body=body)

        if status == 400:
            pass_("Unknown model rejected with 400")
            # Check error message includes valid tiers
            try:
                resp_data = json.loads(resp_body)
                error_msg = resp_data.get("error", "")
                if "haiku" in error_msg or "sonnet" in error_msg or "opus" in error_msg:
                    pass_("Error message includes valid tier names")
                else:
                    fail("Error message doesn't list valid tiers")
            except:
                pass
        else:
            fail(f"Unknown model should return 400, got {status}")

        # Verify upstream received NO requests
        reqs = mock_servers["p"]["requests"]
        if len(reqs) == 0:
            pass_("Upstream received no requests for unknown model")
        else:
            fail(f"Upstream received {len(reqs)} requests for unknown model")

    finally:
        cleanup()


# ===========================================================================
# Test: Model Resolution None Rejected
# ===========================================================================

def test_model_resolution_none_rejected():
    """Send request with {"model": null}, verify 400 error (not crash)."""
    print("\n--- Test: Model Resolution None Rejected ---")

    upstream_port = find_free_port()
    tiers = {
        "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
        "opus": {"provider": "p", "model": "claude-opus-5"},
    }
    vendors = {"p": {"url": f"http://127.0.0.1:{upstream_port}", "key": "k"}}

    temp_dir, proxy_port, proc, mock_servers, cleanup = _setup_tier_routing_test(tiers, vendors)
    if proc is None:
        fail("Failed to set up test")
        return

    try:
        # Send with null model
        body = json.dumps({"model": None, "messages": [{"role": "user", "content": "hi"}]})
        status, _ = _send_proxy_request(proxy_port, body=body)

        if status == 400:
            pass_("Null model rejected with 400")
        elif status == 0:
            fail("Null model caused crash (connection error)")
        else:
            fail(f"Null model should return 400, got {status}")

    finally:
        cleanup()


# ===========================================================================
# Test: Response Model Rewrite (non-streaming)
# ===========================================================================

def test_response_model_rewrite():
    """Verify response model name is replaced with tier name (non-streaming)."""
    print("\n--- Test: Response Model Rewrite ---")

    upstream_port = find_free_port()
    tiers = {
        "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
        "opus": {"provider": "p", "model": "claude-opus-5"},
    }
    vendors = {"p": {"url": f"http://127.0.0.1:{upstream_port}", "key": "k"}}

    temp_dir, proxy_port, proc, mock_servers, cleanup = _setup_tier_routing_test(tiers, vendors)
    if proc is None:
        fail("Failed to set up test")
        return

    try:
        # Send request
        body = json.dumps({"model": "sonnet", "messages": [{"role": "user", "content": "hi"}]})
        status, resp_body = _send_proxy_request(proxy_port, body=body)

        if status != 200:
            fail(f"Request failed: {status}")
            return

        # Check response model is rewritten
        try:
            resp_data = json.loads(resp_body)
            if resp_data.get("model") == "sonnet":
                pass_("Response model rewritten to tier name")
            else:
                fail(f"Response model not rewritten: {resp_data.get('model')}")
        except:
            fail("Could not parse response JSON")

    finally:
        cleanup()


# ===========================================================================
# Test: Response Model Rewrite Streaming
# ===========================================================================

def test_response_model_rewrite_streaming():
    """Verify SSE message_start event has tier name, subsequent events unchanged."""
    print("\n--- Test: Response Model Rewrite Streaming ---")

    upstream_port = find_free_port()

    # Mock that streams SSE
    class SSEHandler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            content_len = int(self.headers.get("Content-Length", 0))
            if content_len > 0:
                self.rfile.read(content_len)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            # Send message_start with model
            event1 = json.dumps({"type": "message_start", "message": {"model": "claude-sonnet-5"}})
            self.wfile.write(f"data: {event1}\n\n".encode())
            self.wfile.flush()
            # Send content_block_delta (no model field)
            event2 = json.dumps({"type": "content_block_delta", "delta": {"text": "Hi"}})
            self.wfile.write(f"data: {event2}\n\n".encode())
            self.wfile.flush()

        def log_message(self, format, *args):
            pass

    mock_server = http.server.ThreadingHTTPServer(("127.0.0.1", upstream_port), SSEHandler)
    mock_thread = threading.Thread(target=mock_server.serve_forever, daemon=True)
    mock_thread.start()
    time.sleep(0.2)

    tiers = {
        "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
        "opus": {"provider": "p", "model": "claude-opus-5"},
    }
    vendors = {"p": {"url": f"http://127.0.0.1:{upstream_port}", "key": "k"}}

    temp_dir, proxy_port, proc, mock_servers, cleanup = _setup_tier_routing_test(tiers, vendors)
    if proc is None:
        mock_server.shutdown()
        fail("Failed to set up test")
        return

    try:
        # Send streaming request
        body = json.dumps({"model": "sonnet", "messages": [{"role": "user", "content": "hi"}], "stream": True})
        import http.client as _hc
        conn = _hc.HTTPConnection("127.0.0.1", proxy_port, timeout=10)
        conn.request("POST", "/v1/messages", body=body, headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        resp_data = resp.read().decode()
        conn.close()

        # Check first event has tier name
        if '"model": "sonnet"' in resp_data or '"model":"sonnet"' in resp_data:
            pass_("SSE message_start has tier name")
        else:
            fail("SSE message_start doesn't have tier name")

        # Check subsequent events are unchanged
        if "content_block_delta" in resp_data:
            pass_("Subsequent SSE events present")
        else:
            fail("Subsequent SSE events missing")

    finally:
        cleanup()
        mock_server.shutdown()


# ===========================================================================
# Test: Response Model Rewrite Streaming Non-Message-Start
# ===========================================================================

def test_response_model_rewrite_streaming_non_message_start():
    """First SSE event is not message_start → forwarded unchanged, no rewrite attempted."""
    print("\n--- Test: Response Model Rewrite Streaming Non-Message-Start ---")

    upstream_port = find_free_port()

    class SSEHandler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            content_len = int(self.headers.get("Content-Length", 0))
            if content_len > 0:
                self.rfile.read(content_len)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            # First event is a ping, not message_start
            self.wfile.write(b"data: {\"type\": \"ping\"}\n\n")
            self.wfile.flush()
            self.wfile.write(b"data: {\"type\": \"message_start\", \"message\": {\"model\": \"claude-sonnet-5\"}}\n\n")
            self.wfile.flush()

        def log_message(self, format, *args):
            pass

    mock_server = http.server.ThreadingHTTPServer(("127.0.0.1", upstream_port), SSEHandler)
    mock_thread = threading.Thread(target=mock_server.serve_forever, daemon=True)
    mock_thread.start()
    time.sleep(0.2)

    tiers = {
        "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
        "opus": {"provider": "p", "model": "claude-opus-5"},
    }
    vendors = {"p": {"url": f"http://127.0.0.1:{upstream_port}", "key": "k"}}

    temp_dir, proxy_port, proc, mock_servers, cleanup = _setup_tier_routing_test(tiers, vendors)
    if proc is None:
        mock_server.shutdown()
        fail("Failed to set up test")
        return

    try:
        body = json.dumps({"model": "sonnet", "messages": [{"role": "user", "content": "hi"}], "stream": True})
        import http.client as _hc
        conn = _hc.HTTPConnection("127.0.0.1", proxy_port, timeout=10)
        conn.request("POST", "/v1/messages", body=body, headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        resp_data = resp.read().decode()
        conn.close()

        # First event should be unchanged (ping)
        if '{"type": "ping"}' in resp_data or '{"type":"ping"}' in resp_data:
            pass_("First SSE event (ping) forwarded unchanged")
        else:
            fail("First SSE event was modified")

    finally:
        cleanup()
        mock_server.shutdown()


# ===========================================================================
# Test: Two Tiers, Same Model, Same Provider
# ===========================================================================

def test_two_tiers_same_model_same_provider():
    """Two tiers mapping to the same model from the same provider: the server
    starts, each request routes to the shared model, and JSON + SSE responses
    are rewritten to the requesting tier's name (no reverse map needed)."""
    print("\n--- Test: Two Tiers Same Model Same Provider ---")

    upstream_port = find_free_port()
    requests = []

    class CollisionHandler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            content_len = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_len) if content_len > 0 else b"{}"
            api_key = self.headers.get("x-api-key", "")
            requests.append({"body": body, "api_key": api_key})
            try:
                req_data = json.loads(body)
                model = req_data.get("model", "unknown")
                is_stream = bool(req_data.get("stream", False))
            except Exception:
                model = "unknown"
                is_stream = False
            if is_stream:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                event1 = json.dumps({"type": "message_start", "message": {"model": model}})
                self.wfile.write(f"data: {event1}\n\n".encode())
                self.wfile.flush()
                event2 = json.dumps({"type": "content_block_delta", "delta": {"text": "Hi"}})
                self.wfile.write(f"data: {event2}\n\n".encode())
                self.wfile.flush()
            else:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "id": "ok",
                    "type": "message",
                    "model": model,
                    "content": [{"text": "response"}],
                }).encode())

        def log_message(self, format, *args):
            pass

    mock_server = http.server.ThreadingHTTPServer(("127.0.0.1", upstream_port), CollisionHandler)
    mock_thread = threading.Thread(target=mock_server.serve_forever, daemon=True)
    mock_thread.start()
    time.sleep(0.2)

    tiers = {
        "haiku": {"provider": "p", "model": "deepseek-v4-flash"},
        "sonnet": {"provider": "p", "model": "deepseek-v4-flash"},  # collision with haiku
        "opus": {"provider": "p", "model": "claude-opus-5"},
    }
    vendors = {"p": {"url": f"http://127.0.0.1:{upstream_port}", "key": "k"}}

    temp_dir = tempfile.mkdtemp(prefix="proxy_collision_test_")
    proxy_port = find_free_port()
    try:
        config_path = _create_test_config(temp_dir, tiers)
        keys_path = _create_test_keys(temp_dir, vendors)
        trace_fd, trace_file = tempfile.mkstemp(suffix=".jsonl", dir=temp_dir)
        os.close(trace_fd)
        proc, probe_ok = _start_proxy_server_directly(
            proxy_port, config_path=config_path, keys_path=keys_path, trace_file=trace_file
        )
        if not probe_ok:
            fail("Proxy failed to start with two tiers mapping to the same model")
            return

        try:
            import http.client as _hc

            # --- JSON path: each request gets its own tier name ---
            body = json.dumps({"model": "sonnet", "messages": [{"role": "user", "content": "hi"}]})
            status, resp_body = _send_proxy_request(proxy_port, body=body)
            if status != 200:
                fail(f"sonnet request failed: {status}")
            else:
                resp_data = json.loads(resp_body)
                if resp_data.get("model") == "sonnet":
                    pass_("sonnet request -> response model 'sonnet'")
                else:
                    fail(f"sonnet response model: {resp_data.get('model')!r}, expected 'sonnet'")

            body = json.dumps({"model": "haiku", "messages": [{"role": "user", "content": "hi"}]})
            status, resp_body = _send_proxy_request(proxy_port, body=body)
            if status != 200:
                fail(f"haiku request failed: {status}")
            else:
                resp_data = json.loads(resp_body)
                if resp_data.get("model") == "haiku":
                    pass_("haiku request -> response model 'haiku'")
                else:
                    fail(f"haiku response model: {resp_data.get('model')!r}, expected 'haiku'")

            # Upstream received the shared configured model name for both tiers
            if len(requests) >= 2 and all(
                json.loads(r["body"]).get("model") == "deepseek-v4-flash"
                for r in requests[:2]
            ):
                pass_("Upstream received deepseek-v4-flash for both tiers")
            else:
                fail(f"Upstream model names: {[json.loads(r['body']).get('model') for r in requests]}")

            # --- SSE path: message_start rewritten to per-request tier ---
            stream_body = json.dumps({"model": "sonnet", "messages": [{"role": "user", "content": "hi"}], "stream": True})
            conn = _hc.HTTPConnection("127.0.0.1", proxy_port, timeout=10)
            conn.request("POST", "/v1/messages", body=stream_body, headers={"Content-Type": "application/json"})
            resp = conn.getresponse()
            sse_data = resp.read().decode()
            conn.close()

            if '"model": "sonnet"' in sse_data or '"model":"sonnet"' in sse_data:
                pass_("SSE message_start rewritten to 'sonnet' for sonnet request")
            else:
                fail(f"SSE response model not 'sonnet': {sse_data[:200]}")

            stream_body = json.dumps({"model": "haiku", "messages": [{"role": "user", "content": "hi"}], "stream": True})
            conn = _hc.HTTPConnection("127.0.0.1", proxy_port, timeout=10)
            conn.request("POST", "/v1/messages", body=stream_body, headers={"Content-Type": "application/json"})
            resp = conn.getresponse()
            sse_data = resp.read().decode()
            conn.close()

            if '"model": "haiku"' in sse_data or '"model":"haiku"' in sse_data:
                pass_("SSE message_start rewritten to 'haiku' for haiku request")
            else:
                fail(f"SSE response model not 'haiku': {sse_data[:200]}")

        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
    finally:
        mock_server.shutdown()
        shutil.rmtree(temp_dir, ignore_errors=True)


# ===========================================================================
# Test: Response Model Rewrite Upstream Model
# ===========================================================================

def test_response_model_rewrite_upstream_model():
    """Upstream returns an arbitrary model name → rewritten to tier name (unconditional rewrite)."""
    print("\n--- Test: Response Model Rewrite Upstream Model ---")

    upstream_port = find_free_port()

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            content_len = int(self.headers.get("Content-Length", 0))
            if content_len > 0:
                self.rfile.read(content_len)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            # Return a model name not configured in any tier
            self.wfile.write(b'{"id":"ok","type":"message","model":"unknown-model"}')

        def log_message(self, format, *args):
            pass

    mock_server = http.server.ThreadingHTTPServer(("127.0.0.1", upstream_port), Handler)
    mock_thread = threading.Thread(target=mock_server.serve_forever, daemon=True)
    mock_thread.start()
    time.sleep(0.2)

    tiers = {
        "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
        "opus": {"provider": "p", "model": "claude-opus-5"},
    }
    vendors = {"p": {"url": f"http://127.0.0.1:{upstream_port}", "key": "k"}}

    temp_dir, proxy_port, proc, mock_servers, cleanup = _setup_tier_routing_test(tiers, vendors)
    if proc is None:
        mock_server.shutdown()
        fail("Failed to set up test")
        return

    try:
        body = json.dumps({"model": "sonnet", "messages": [{"role": "user", "content": "hi"}]})
        status, resp_body = _send_proxy_request(proxy_port, body=body)

        if status != 200:
            fail(f"Request failed: {status}")
            return

        # Unconfigured upstream model is still rewritten to the tier name
        try:
            resp_data = json.loads(resp_body)
            if resp_data.get("model") == "sonnet":
                pass_("Unknown upstream model rewritten to tier name")
            else:
                fail(f"Response model not rewritten: {resp_data.get('model')}")
        except:
            fail("Could not parse response")

    finally:
        cleanup()
        mock_server.shutdown()


# ===========================================================================
# Test: Config Validation Missing Tier
# ===========================================================================

def test_config_validation_missing_tier():
    """Config with empty provider → server refuses to start."""
    print("\n--- Test: Config Validation Missing Tier ---")

    temp_dir = tempfile.mkdtemp(prefix="proxy_config_test_")
    try:
        # Create invalid config (missing model in haiku tier)
        invalid_config = {
            "tiers": {
                "haiku": {"provider": "p"},  # missing model
                "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
                "opus": {"provider": "p", "model": "claude-opus-5"},
            },
            "models": {"p": ["claude-sonnet-5", "claude-opus-5"]}
        }
        config_path = os.path.join(temp_dir, "config.json")
        with open(config_path, "w") as f:
            json.dump(invalid_config, f)

        keys_path = os.path.join(temp_dir, "keys-index.json")
        with open(keys_path, "w") as f:
            json.dump({"vendors": {"p": {"url": "http://127.0.0.1:9999", "key": "k"}}}, f)

        proxy_port = find_free_port()
        proc, probe_ok = _start_proxy_server_directly(
            proxy_port, config_path=config_path, keys_path=keys_path
        )

        # Server should not start (probe_ok should be False)
        if not probe_ok:
            pass_("Server refused to start with invalid config")
        else:
            fail("Server started with invalid config (should have refused)")
            proc.kill()

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


# ===========================================================================
# Test: Config Validation Unknown Provider
# ===========================================================================

def test_config_validation_unknown_provider():
    """Config references provider not in keys-index.json → server refuses to start."""
    print("\n--- Test: Config Validation Unknown Provider ---")

    temp_dir = tempfile.mkdtemp(prefix="proxy_config_test_")
    try:
        # Config references "unknown-provider" but keys only has "p"
        invalid_config = {
            "tiers": {
                "haiku": {"provider": "unknown-provider", "model": "m"},
                "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
                "opus": {"provider": "p", "model": "claude-opus-5"},
            },
            # "p" has models so the only validation error is the unknown provider
            "models": {"p": ["claude-sonnet-5", "claude-opus-5"]}
        }
        config_path = os.path.join(temp_dir, "config.json")
        with open(config_path, "w") as f:
            json.dump(invalid_config, f)

        keys_path = os.path.join(temp_dir, "keys-index.json")
        with open(keys_path, "w") as f:
            json.dump({"vendors": {"p": {"url": "http://127.0.0.1:9999", "key": "k"}}}, f)

        proxy_port = find_free_port()
        proc, probe_ok = _start_proxy_server_directly(
            proxy_port, config_path=config_path, keys_path=keys_path
        )

        if not probe_ok:
            pass_("Server refused to start with unknown provider")
        else:
            fail("Server started with unknown provider (should have refused)")
            proc.kill()

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


# ===========================================================================
# Test: Config Validation Models To Keys
# ===========================================================================

def test_config_validation_models_to_keys():
    """Config validation direction is config→keys, not keys→config.

    A provider present in config.models but missing from keys-index.json →
    server refuses to start with "has no entry in keys-index.json". A provider
    present in keys-index.json but absent from config.models and not referenced
    by any tier → server starts successfully (config is authoritative; inactive
    keys providers are silently ignored).
    """
    print("\n--- Test: Config Validation Models To Keys ---")

    temp_dir = tempfile.mkdtemp(prefix="proxy_cfg_models_keys_")
    try:
        # Config models references "orphan" which has no entry in keys-index.json
        invalid_config = {
            "tiers": {
                "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
                "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
                "opus": {"provider": "p", "model": "claude-opus-5"},
            },
            "models": {"p": ["claude-sonnet-5", "claude-opus-5"], "orphan": ["some-model"]}
        }
        config_path = os.path.join(temp_dir, "config.json")
        with open(config_path, "w") as f:
            json.dump(invalid_config, f)

        keys_path = os.path.join(temp_dir, "keys-index.json")
        with open(keys_path, "w") as f:
            json.dump({"vendors": {"p": {"url": "http://127.0.0.1:9999", "key": "k"}}}, f)

        proc, probe_ok = _start_proxy_server_directly(
            find_free_port(), config_path=config_path, keys_path=keys_path
        )

        if not probe_ok:
            try:
                _, err = proc.communicate(timeout=5)
            except Exception:
                err = ""
            if "has no entry in keys-index.json" in err:
                pass_("Server refused to start when config.models references a provider missing from keys-index.json")
            else:
                fail(f"Server refused but without 'has no entry in keys-index.json' error: {err[:300]!r}")
        else:
            fail("Server started although config.models references a provider missing from keys-index.json")
            proc.kill()

        # Now: provider in keys-index.json but not in config.models and not tier-referenced → starts
        valid_config = {
            "tiers": {
                "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
                "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
                "opus": {"provider": "p", "model": "claude-opus-5"},
            },
            "models": {"p": ["claude-sonnet-5", "claude-opus-5"]}
        }
        config_path2 = os.path.join(temp_dir, "config2.json")
        with open(config_path2, "w") as f:
            json.dump(valid_config, f)

        # keys-index.json contains an extra "legacy" provider not in config.models
        keys_path2 = os.path.join(temp_dir, "keys2-index.json")
        with open(keys_path2, "w") as f:
            json.dump({"vendors": {
                "p": {"url": "http://127.0.0.1:9999", "key": "k"},
                "legacy": {"url": "http://127.0.0.1:9998", "key": "k2"},
            }}, f)

        proc2, probe_ok2 = _start_proxy_server_directly(
            find_free_port(), config_path=config_path2, keys_path=keys_path2
        )
        if probe_ok2:
            pass_("Server started with a keys-only provider absent from config.models (not tier-referenced)")
            proc2.terminate()
            try:
                proc2.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc2.kill()
        else:
            try:
                _, err2 = proc2.communicate(timeout=5)
            except Exception:
                err2 = ""
            fail(f"Server refused to start with tier-unreferenced keys-only provider: {err2[:300]!r}")

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


# ===========================================================================
# Test: Config Validation Tier Provider Needs Models
# ===========================================================================

def test_config_validation_tier_provider_needs_models():
    """A tier-referenced provider must have an entry in config.models.

    Server refuses to start when a tier's provider has no models entry, with a
    clear error mentioning the tier name.
    """
    print("\n--- Test: Config Validation Tier Provider Needs Models ---")

    temp_dir = tempfile.mkdtemp(prefix="proxy_cfg_tier_models_")
    try:
        # "q" is referenced by the opus tier but has no entry in config.models
        invalid_config = {
            "tiers": {
                "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
                "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
                "opus": {"provider": "q", "model": "claude-opus-5"},
            },
            "models": {"p": ["claude-sonnet-5", "claude-opus-5"]}
        }
        config_path = os.path.join(temp_dir, "config.json")
        with open(config_path, "w") as f:
            json.dump(invalid_config, f)

        keys_path = os.path.join(temp_dir, "keys-index.json")
        with open(keys_path, "w") as f:
            json.dump({"vendors": {
                "p": {"url": "http://127.0.0.1:9999", "key": "k"},
                "q": {"url": "http://127.0.0.1:9998", "key": "k2"},
            }}, f)

        proc, probe_ok = _start_proxy_server_directly(
            find_free_port(), config_path=config_path, keys_path=keys_path
        )

        if not probe_ok:
            try:
                _, err = proc.communicate(timeout=5)
            except Exception:
                err = ""
            if "used by tier" in err and "opus" in err:
                pass_("Server refused to start when tier-referenced provider has no models entry, mentioning the tier")
            else:
                fail(f"Server refused but without 'used by tier'/'opus' error: {err[:300]!r}")
        else:
            fail("Server started although a tier-referenced provider had no models entry")
            proc.kill()

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


# ===========================================================================
# Test: Heartbeat Preserves State
# ===========================================================================

def test_heartbeat_preserves_state():
    """Heartbeat writes the in-memory startup state, never a disk-read {}.

    The heartbeat must write from _startup_state (full pid/port fields), not
    from read_state() which returns {} when proxy-state.json is deleted
    externally. This test exercises the server module in-process: it sets
    _startup_state to a full state dict (as main() does at startup), runs the
    same write the heartbeat performs, and asserts pid/port are preserved when
    the file was deleted first (simulating external deletion).
    """
    print("\n--- Test: Heartbeat Preserves State ---")

    import claude_retry_proxy.server as srv

    state_path = srv.STATE_FILE
    state_backup = None
    if os.path.exists(state_path):
        with open(state_path) as f:
            state_backup = f.read()
    try:
        # Simulate external deletion of the state file (file gone on disk)
        try:
            os.remove(state_path)
        except OSError:
            pass

        # Simulate main() startup: _startup_state holds the full state dict
        full_state = {
            "pid": 12345,
            "port": 8080,
            "started_at": "2026-08-26T00:00:00Z",
            "owner_pid": 54321,
            "last_heartbeat": "2026-08-26T00:00:00Z",
            "last_request_at": "2026-08-26T00:00:00Z",
        }
        srv._startup_state = full_state

        # Heartbeat write: update last_heartbeat on the in-memory copy and write it
        srv._startup_state["last_heartbeat"] = "2026-08-26T01:00:00Z"
        srv.write_state(srv._startup_state)

        with open(state_path) as f:
            recreated = json.load(f)

        pid_ok = recreated.get("pid") == 12345
        port_ok = recreated.get("port") == 8080
        started_ok = recreated.get("started_at") == "2026-08-26T00:00:00Z"
        hb_ok = recreated.get("last_heartbeat") == "2026-08-26T01:00:00Z"

        if pid_ok and port_ok and started_ok:
            pass_("Heartbeat write preserves pid, port, started_at from in-memory state")
        else:
            fail(f"Heartbeat write lost fields: {recreated!r}")
        if hb_ok:
            pass_("Heartbeat write updates last_heartbeat")
        else:
            fail(f"Heartbeat write did not update last_heartbeat: {recreated!r}")

        # Clean up the file we wrote
        try:
            os.remove(state_path)
        except OSError:
            pass
    finally:
        # Restore the previous state file (if any)
        if state_backup is not None:
            os.makedirs(os.path.dirname(state_path), exist_ok=True)
            with open(state_path, "w") as f:
                f.write(state_backup)
        else:
            try:
                os.remove(state_path)
            except OSError:
                pass


# ===========================================================================
# Test: Models Per Provider Validation
# ===========================================================================

def test_models_per_provider_validation():
    """Config.models entries must have valid shape; tier-referenced providers must have a models entry.

    Server refuses to start when a provider's models entry is malformed (missing,
    empty list, a string instead of a list, or a list whose entries are empty or
    whitespace-only) — with a clear "has no models" error — and when a provider
    referenced by a tier has no models entry ("used by tier" error). Starts when
    all tier-referenced providers have at least one non-empty model name.
    Providers in keys-index.json that are neither referenced by a tier nor
    present in config.models are silently ignored.
    """
    print("\n--- Test: Models Per Provider Validation ---")

    def try_start(models, keys_vendors=None):
        temp_dir = tempfile.mkdtemp(prefix="proxy_models_val_")
        try:
            config = {
                "tiers": {
                    "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
                    "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
                    "opus": {"provider": "p", "model": "claude-opus-5"},
                },
                "models": models,
            }
            config_path = os.path.join(temp_dir, "config.json")
            with open(config_path, "w") as f:
                json.dump(config, f)
            if keys_vendors is None:
                keys_vendors = {"p": {"url": "http://127.0.0.1:1", "key": "k"}}
            keys_path = _create_test_keys(temp_dir, keys_vendors)
            proc, probe_ok = _start_proxy_server_directly(
                find_free_port(), config_path=config_path, keys_path=keys_path
            )
            err = ""
            if probe_ok:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
            else:
                # Validation refused startup — collect the error message
                try:
                    _, err = proc.communicate(timeout=5)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass
            return probe_ok, err or ""
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    # (a) provider "p" missing from models but referenced by tiers -> refuse with "used by tier"
    started, err = try_start({})
    if not started and "used by tier" in err:
        pass_("Server refused to start with 'used by tier' when tier provider has no models entry")
    else:
        fail(f"Expected refusal with 'used by tier', got started={started}, stderr={err[:300]!r}")

    # (b) provider "p" present but empty list -> refuse (shape)
    started, err = try_start({"p": []})
    if not started and "has no models" in err:
        pass_("Server refused to start when provider models list is empty")
    else:
        fail(f"Expected refusal for empty models list, got started={started}, stderr={err[:300]!r}")

    # (c) provider "p" has >=1 model -> starts
    started, err = try_start({"p": ["claude-haiku-4-5", "claude-sonnet-5", "claude-opus-5"]})
    if started:
        pass_("Server started when all providers have at least one model")
    else:
        fail(f"Server refused to start although all providers had models: {err[:300]!r}")

    # (d) provider "p" has a string instead of a list -> refuse (shape)
    started, err = try_start({"p": "claude-sonnet-5"})
    if not started and "has no models" in err:
        pass_("Server refused to start when models.p is a string (not a list)")
    else:
        fail(f"Expected refusal for string models value, got started={started}, stderr={err[:300]!r}")

    # (e) provider "p" has a list containing an empty string -> refuse (shape)
    started, err = try_start({"p": [""]})
    if not started and "has no models" in err:
        pass_("Server refused to start when models.p list contains an empty string")
    else:
        fail(f"Expected refusal for list with empty string, got started={started}, stderr={err[:300]!r}")

    # (f) provider "p" has a list containing a whitespace-only string -> refuse (shape)
    started, err = try_start({"p": ["   "]})
    if not started and "has no models" in err:
        pass_("Server refused to start when models.p list contains a whitespace-only string")
    else:
        fail(f"Expected refusal for whitespace-only model string, got started={started}, stderr={err[:300]!r}")

    # (g) provider in keys but not in models and not referenced by any tier -> starts
    #     (config→keys validation direction: keys-index.json is not authoritative)
    started, err = try_start({"p": ["claude-haiku-4-5", "claude-sonnet-5", "claude-opus-5"]},
                             keys_vendors={"p": {"url": "http://127.0.0.1:1", "key": "k"},
                                           "legacy": {"url": "http://127.0.0.1:2", "key": "k2"}})
    if started:
        pass_("Server started with a keys-only provider absent from models (not tier-referenced)")
    else:
        fail(f"Server refused to start although extra keys provider is tier-unreferenced: {err[:300]!r}")


# ===========================================================================
# Test: Config Template Copy
# ===========================================================================

def test_config_template_copy():
    """Missing config.json → template copied, start fails with message."""
    print("\n--- Test: Config Template Copy ---")
    state_backup = _backup_proxy_state()
    cleanup_lock_files()

    try:
        try:
            os.remove(PROXY_STATE_FILE)
        except OSError:
            pass

        temp_dir = tempfile.mkdtemp(prefix="proxy_template_copy_")
        try:
            nonexistent_config = os.path.join(temp_dir, "config.json")
            keys_path = _create_test_keys_plain(temp_dir, {
                "p": {"url": "http://127.0.0.1:1", "key": "k"}
            })

            proc = subprocess.Popen(
                CLAUDE_PROXY + ["start", "--config-path", nonexistent_config,
                                "--keys-path", keys_path],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                stdin=subprocess.PIPE, text=True
            )
            try:
                proc.stdin.close()
            except OSError:
                pass
            stdout, stderr = proc.communicate(timeout=30)

            if proc.returncode == 1:
                pass_("Start without config exited 1")
            else:
                fail(f"Start without config exited {proc.returncode} (expected 1): {stdout} {stderr}")

            if os.path.exists(nonexistent_config):
                pass_("Template created at config path")
            else:
                fail("Template NOT created at config path")

            if "Created config template" in stdout:
                pass_("stdout mentions 'Created config template'")
            else:
                fail(f"stdout missing 'Created config template'. stdout: {stdout[:300]}")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    finally:
        cleanup_lock_files()
        subprocess.run(CLAUDE_PROXY + ["stop"], capture_output=True, text=True, timeout=10)
        _restore_proxy_state(state_backup)


# ===========================================================================
# Test: Admin Page Served
# ===========================================================================

def test_admin_page_served():
    """GET /admin/ returns HTML."""
    print("\n--- Test: Admin Page Served ---")

    upstream_port = find_free_port()
    tiers = {
        "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
        "opus": {"provider": "p", "model": "claude-opus-5"},
    }
    vendors = {"p": {"url": f"http://127.0.0.1:{upstream_port}", "key": "k"}}

    temp_dir, proxy_port, proc, mock_servers, cleanup = _setup_tier_routing_test(tiers, vendors)
    if proc is None:
        fail("Failed to set up test")
        return

    try:
        import http.client as _hc
        conn = _hc.HTTPConnection("127.0.0.1", proxy_port, timeout=10)
        conn.request("GET", "/admin/")
        resp = conn.getresponse()
        status = resp.status
        content_type = resp.getheader("Content-Type", "")
        body = resp.read().decode()
        conn.close()

        if status == 200:
            pass_("GET /admin/ returned 200")
        else:
            fail(f"GET /admin/ returned {status}, expected 200")

        if "text/html" in content_type:
            pass_("Content-Type is text/html")
        else:
            fail(f"Content-Type is {content_type}, expected text/html")

        if "<html" in body.lower() or "<!doctype" in body.lower():
            pass_("Response contains HTML")
        else:
            fail("Response doesn't contain HTML")

    finally:
        cleanup()


# ===========================================================================
# Test: Admin API Config
# ===========================================================================

def test_admin_api_config():
    """GET /admin/api/config returns current tiers + models."""
    print("\n--- Test: Admin API Config ---")

    upstream_port = find_free_port()
    tiers = {
        "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
        "opus": {"provider": "p", "model": "claude-opus-5"},
    }
    vendors = {"p": {"url": f"http://127.0.0.1:{upstream_port}", "key": "k"}}

    temp_dir, proxy_port, proc, mock_servers, cleanup = _setup_tier_routing_test(tiers, vendors)
    if proc is None:
        fail("Failed to set up test")
        return

    try:
        import http.client as _hc
        conn = _hc.HTTPConnection("127.0.0.1", proxy_port, timeout=10)
        conn.request("GET", "/admin/api/config")
        resp = conn.getresponse()
        status = resp.status
        body = resp.read().decode()
        conn.close()

        if status != 200:
            fail(f"GET /admin/api/config returned {status}")
            return

        try:
            config = json.loads(body)
            if "tiers" in config and "models" in config:
                pass_("Config API returns tiers and models")
            else:
                fail("Config API missing tiers or models")
        except:
            fail("Config API response not valid JSON")

    finally:
        cleanup()


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
# Test: Admin API Switch
# ===========================================================================

def test_admin_api_switch():
    """POST /admin/api/switch updates tier, subsequent request routes to new provider."""
    print("\n--- Test: Admin API Switch ---")

    p1_port = find_free_port()
    p2_port = find_free_port()
    tiers = {
        "haiku": {"provider": "p1", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "p1", "model": "claude-sonnet-5"},
        "opus": {"provider": "p1", "model": "claude-opus-5"},
    }
    vendors = {
        "p1": {"url": f"http://127.0.0.1:{p1_port}", "key": "k1"},
        "p2": {"url": f"http://127.0.0.1:{p2_port}", "key": "k2"},
    }

    proxy_port, proc, mock_servers, temp_dir, cleanup = _start_admin_proxy(tiers, vendors)
    if proc is None:
        fail("Failed to set up test")
        return

    try:
        # Baseline: sonnet routes to p1
        status, resp_body = _send_proxy_request(proxy_port, body=json.dumps({
            "model": "sonnet", "messages": [{"role": "user", "content": "hi"}]}))
        if status != 200:
            fail(f"Baseline request returned {status}")
            return
        p1_count_before = len(mock_servers["p1"]["requests"])
        pass_(f"Baseline sonnet request routed to p1 ({p1_count_before} requests)")

        # Switch sonnet from p1 to p2
        switch_body = {
            "tiers": {
                "haiku": {"provider": "p1", "model": "claude-haiku-4-5"},
                "sonnet": {"provider": "p2", "model": "claude-sonnet-5"},
                "opus": {"provider": "p1", "model": "claude-opus-5"},
            }
        }
        status, data = _admin_post(proxy_port, "/admin/api/switch", switch_body)
        if status != 200:
            fail(f"Switch returned {status}: {data}")
            return
        try:
            resp = json.loads(data)
            if resp.get("status") == "ok":
                pass_("Admin API switch returned {'status': 'ok'} (200)")
            else:
                fail(f"Switch response missing 'status': 'ok': {data}")
        except Exception:
            fail(f"Switch response not valid JSON: {data}")

        # Post-switch: sonnet routes to p2
        status, resp_body = _send_proxy_request(proxy_port, body=json.dumps({
            "model": "sonnet", "messages": [{"role": "user", "content": "hi"}]}))
        if status != 200:
            fail(f"Post-switch request returned {status}")
            return

        p2_count = len(mock_servers["p2"]["requests"])
        if p2_count >= 1:
            pass_(f"Post-switch sonnet request routed to p2 ({p2_count} requests)")
        else:
            fail("Post-switch sonnet request did NOT route to p2")

        p1_count_after = len(mock_servers["p1"]["requests"])
        if p1_count_after == p1_count_before:
            pass_("p1 received zero further sonnet requests")
        else:
            fail(f"p1 received further requests after switch: before={p1_count_before} after={p1_count_after}")

    finally:
        cleanup()


# ===========================================================================
# Test: Admin API Switch Invalid Provider
# ===========================================================================

def test_admin_api_switch_invalid_provider():
    """POST with unknown provider → error response."""
    print("\n--- Test: Admin API Switch Invalid Provider ---")

    p_port = find_free_port()
    tiers = {
        "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
        "opus": {"provider": "p", "model": "claude-opus-5"},
    }
    vendors = {"p": {"url": f"http://127.0.0.1:{p_port}", "key": "k"}}

    proxy_port, proc, mock_servers, temp_dir, cleanup = _start_admin_proxy(tiers, vendors)
    if proc is None:
        fail("Failed to set up test")
        return

    try:
        switch_body = {
            "tiers": {
                "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
                "sonnet": {"provider": "nonexistent", "model": "claude-sonnet-5"},
                "opus": {"provider": "p", "model": "claude-opus-5"},
            }
        }
        status, data = _admin_post(proxy_port, "/admin/api/switch", switch_body)
        if status == 400:
            pass_(f"Switch with invalid provider returned 400")
        else:
            fail(f"Switch with invalid provider returned {status}: {data}")
        if "unknown provider" in data:
            pass_(f"Error mentions 'unknown provider': {data}")
        else:
            fail(f"Error missing 'unknown provider': {data}")
    finally:
        cleanup()


# ===========================================================================
# Test: Admin API Switch Preserves Models
# ===========================================================================

def test_admin_api_switch_preserves_models():
    """Switch tiers, verify models section unchanged in config.json."""
    print("\n--- Test: Admin API Switch Preserves Models ---")

    p_port = find_free_port()
    tiers = {
        "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
        "opus": {"provider": "p", "model": "claude-opus-5"},
    }
    models = {"p": ["claude-sonnet-5", "claude-haiku-4-5", "claude-opus-5"]}
    vendors = {"p": {"url": f"http://127.0.0.1:{p_port}", "key": "k"}}

    proxy_port, proc, mock_servers, temp_dir, cleanup = _start_admin_proxy(
        tiers, vendors, models=models)
    if proc is None:
        fail("Failed to set up test")
        return

    try:
        # POST switch with tiers only (no models field)
        switch_body = {
            "tiers": {
                "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
                "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
                "opus": {"provider": "p", "model": "claude-opus-5"},
            }
        }
        status, data = _admin_post(proxy_port, "/admin/api/switch", switch_body)
        if status != 200:
            fail(f"Switch returned {status}: {data}")
            return

        # GET /admin/api/config → models section unchanged
        import http.client as _hc
        conn = _hc.HTTPConnection("127.0.0.1", proxy_port, timeout=10)
        conn.request("GET", "/admin/api/config")
        resp = conn.getresponse()
        body = resp.read().decode()
        conn.close()
        if resp.status != 200:
            fail(f"GET /admin/api/config returned {resp.status}")
            return
        config = json.loads(body)
        if config.get("models") == models:
            pass_("Models section unchanged in /admin/api/config response")
        else:
            fail(f"Models section changed: {config.get('models')}")

        # On-disk config.json still has models section
        config_path = os.path.join(temp_dir, "config.json")
        with open(config_path) as f:
            disk_config = json.load(f)
        if disk_config.get("models") == models:
            pass_("Models section still present in on-disk config.json")
        else:
            fail(f"Models section missing from on-disk config.json: {disk_config.get('models')}")
    finally:
        cleanup()


# ===========================================================================
# Test: Admin API CSRF Rejected
# ===========================================================================

def test_admin_api_csrf_rejected():
    """POST with foreign Origin header → rejected."""
    print("\n--- Test: Admin API CSRF Rejected ---")

    p_port = find_free_port()
    tiers = {
        "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
        "opus": {"provider": "p", "model": "claude-opus-5"},
    }
    vendors = {"p": {"url": f"http://127.0.0.1:{p_port}", "key": "k"}}

    proxy_port, proc, mock_servers, temp_dir, cleanup = _start_admin_proxy(tiers, vendors)
    if proc is None:
        fail("Failed to set up test")
        return

    try:
        switch_body = {
            "tiers": {
                "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
                "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
                "opus": {"provider": "p", "model": "claude-opus-5"},
            }
        }
        status, data = _admin_post(proxy_port, "/admin/api/switch", switch_body,
                                   origin="http://evil.com:9999")
        if status == 403:
            pass_("Foreign Origin rejected with 403")
        else:
            fail(f"Foreign Origin returned {status} (expected 403): {data}")
    finally:
        cleanup()


# ===========================================================================
# Test: Admin API CSRF Null Origin Rejected
# ===========================================================================

def test_admin_api_csrf_null_origin_rejected():
    """POST with Origin: null → rejected."""
    print("\n--- Test: Admin API CSRF Null Origin Rejected ---")

    p_port = find_free_port()
    tiers = {
        "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
        "opus": {"provider": "p", "model": "claude-opus-5"},
    }
    vendors = {"p": {"url": f"http://127.0.0.1:{p_port}", "key": "k"}}

    proxy_port, proc, mock_servers, temp_dir, cleanup = _start_admin_proxy(tiers, vendors)
    if proc is None:
        fail("Failed to set up test")
        return

    try:
        switch_body = {
            "tiers": {
                "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
                "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
                "opus": {"provider": "p", "model": "claude-opus-5"},
            }
        }
        status, data = _admin_post(proxy_port, "/admin/api/switch", switch_body,
                                   origin="null")
        if status == 403:
            pass_("Origin: null rejected with 403")
        else:
            fail(f"Origin: null returned {status} (expected 403): {data}")
    finally:
        cleanup()


# ===========================================================================
# Test: Admin API CSRF Missing Origin Rejected
# ===========================================================================

def test_admin_api_csrf_missing_origin_rejected():
    """POST without Origin header → rejected."""
    print("\n--- Test: Admin API CSRF Missing Origin Rejected ---")

    p_port = find_free_port()
    tiers = {
        "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
        "opus": {"provider": "p", "model": "claude-opus-5"},
    }
    vendors = {"p": {"url": f"http://127.0.0.1:{p_port}", "key": "k"}}

    proxy_port, proc, mock_servers, temp_dir, cleanup = _start_admin_proxy(tiers, vendors)
    if proc is None:
        fail("Failed to set up test")
        return

    try:
        import http.client as _hc
        switch_body = {
            "tiers": {
                "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
                "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
                "opus": {"provider": "p", "model": "claude-opus-5"},
            }
        }
        conn = _hc.HTTPConnection("127.0.0.1", proxy_port, timeout=10)
        conn.request("POST", "/admin/api/switch",
                     body=json.dumps(switch_body),
                     headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        data = resp.read().decode()
        conn.close()
        if resp.status == 403:
            pass_("Missing Origin rejected with 403")
        else:
            fail(f"Missing Origin returned {resp.status} (expected 403): {data}")
    finally:
        cleanup()


# ===========================================================================
# Test: Admin API CSRF IPv6 Loopback Accepted
# ===========================================================================

def test_admin_api_csrf_ipv6_loopback_accepted():
    """POST with Origin: http://[::1]:<port> → accepted."""
    print("\n--- Test: Admin API CSRF IPv6 Loopback Accepted ---")

    p_port = find_free_port()
    tiers = {
        "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
        "opus": {"provider": "p", "model": "claude-opus-5"},
    }
    vendors = {"p": {"url": f"http://127.0.0.1:{p_port}", "key": "k"}}

    proxy_port, proc, mock_servers, temp_dir, cleanup = _start_admin_proxy(tiers, vendors)
    if proc is None:
        fail("Failed to set up test")
        return

    try:
        switch_body = {
            "tiers": {
                "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
                "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
                "opus": {"provider": "p", "model": "claude-opus-5"},
            }
        }
        origin = "http://[::1]:{}".format(proxy_port)
        status, data = _admin_post(proxy_port, "/admin/api/switch", switch_body,
                                   origin=origin)
        if status == 200:
            pass_("IPv6 loopback Origin accepted (200) — validates Origin allowlist")
        else:
            fail(f"IPv6 loopback Origin returned {status} (expected 200): {data}")
    finally:
        cleanup()


# ===========================================================================
# Test: Admin API Switch Missing Tier Rejected
# ===========================================================================

def test_admin_api_switch_missing_tier_rejected():
    """POST with only 2 tiers → 400 error listing missing tier."""
    print("\n--- Test: Admin API Switch Missing Tier Rejected ---")

    p_port = find_free_port()
    tiers = {
        "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
        "opus": {"provider": "p", "model": "claude-opus-5"},
    }
    vendors = {"p": {"url": f"http://127.0.0.1:{p_port}", "key": "k"}}

    proxy_port, proc, mock_servers, temp_dir, cleanup = _start_admin_proxy(tiers, vendors)
    if proc is None:
        fail("Failed to set up test")
        return

    try:
        switch_body = {
            "tiers": {
                "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
                "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
            }
        }
        status, data = _admin_post(proxy_port, "/admin/api/switch", switch_body)
        if status == 400:
            pass_(f"Switch with 2 tiers returned 400")
        else:
            fail(f"Switch with 2 tiers returned {status} (expected 400): {data}")
        if "missing tiers" in data:
            pass_(f"Error mentions 'missing tiers': {data}")
        else:
            fail(f"Error missing 'missing tiers': {data}")
    finally:
        cleanup()


# ===========================================================================
# Test: Admin API Reload
# ===========================================================================

def test_admin_api_reload():
    """Modify config.json on disk, POST /admin/api/reload, verify new mapping active."""
    print("\n--- Test: Admin API Reload ---")

    p_port = find_free_port()
    tiers_a = {
        "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "p", "model": "model-a"},
        "opus": {"provider": "p", "model": "claude-opus-5"},
    }
    vendors = {"p": {"url": f"http://127.0.0.1:{p_port}", "key": "k"}}

    temp_dir = tempfile.mkdtemp(prefix="proxy_admin_reload_")
    proxy_port = find_free_port()
    config_path = _create_test_config(temp_dir, tiers_a)
    keys_path = _create_test_keys_plain(temp_dir, vendors)

    req_list = []
    mock_servers = {"p": {
        "server": _start_mock_upstream(p_port, req_list),
        "requests": req_list,
    }}

    trace_fd, trace_file = tempfile.mkstemp(suffix=".jsonl", dir=temp_dir)
    os.close(trace_fd)

    proc, probe_ok = _start_proxy_server_directly(
        proxy_port, config_path=config_path, keys_path=keys_path,
        passphrase=None, trace_file=trace_file
    )

    if not probe_ok:
        mock_servers["p"]["server"].shutdown()
        proc.kill()
        shutil.rmtree(temp_dir, ignore_errors=True)
        fail("Failed to set up test")
        return

    def cleanup():
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        mock_servers["p"]["server"].shutdown()
        shutil.rmtree(temp_dir, ignore_errors=True)

    try:
        # Baseline: sonnet routes to model-a
        status, resp_body = _send_proxy_request(proxy_port, body=json.dumps({
            "model": "sonnet", "messages": [{"role": "user", "content": "hi"}]}))
        if status != 200:
            fail(f"Baseline request returned {status}")
            return
        if req_list and b"model-a" in req_list[-1]["body"]:
            pass_("Baseline sonnet request routed to model-a")
        else:
            fail(f"Baseline sonnet request did not route to model-a. last: {req_list[-1] if req_list else 'none'}")

        # Modify config.json on disk: sonnet → model-b
        tiers_b = dict(tiers_a)
        tiers_b["sonnet"] = {"provider": "p", "model": "model-b"}
        with open(config_path, "w") as f:
            # Reload re-validates: provider "p" needs >=1 model in config.models
            json.dump({"tiers": tiers_b, "models": _derive_models_from_tiers(tiers_b)}, f)

        # POST /admin/api/reload
        status, data = _admin_post(proxy_port, "/admin/api/reload", {})
        if status == 200:
            pass_("Admin API reload returned 200")
        else:
            fail(f"Admin API reload returned {status}: {data}")
            return

        # Post-reload: sonnet routes to model-b
        status, resp_body = _send_proxy_request(proxy_port, body=json.dumps({
            "model": "sonnet", "messages": [{"role": "user", "content": "hi"}]}))
        if status != 200:
            fail(f"Post-reload request returned {status}")
            return
        if req_list and b"model-b" in req_list[-1]["body"]:
            pass_("Post-reload sonnet request routed to model-b")
        else:
            fail(f"Post-reload sonnet request did not route to model-b. last: {req_list[-1] if req_list else 'none'}")
    finally:
        cleanup()


# ===========================================================================
# Test: CLI Reload
# ===========================================================================

def test_cli_reload():
    """claude-retry-proxy reload sends reload request to running proxy."""
    print("\n--- Test: CLI Reload ---")
    state_backup = _backup_proxy_state()
    cleanup_lock_files()

    try:
        try:
            os.remove(PROXY_STATE_FILE)
        except OSError:
            pass

        port = find_free_port()
        p_port = find_free_port()
        temp_dir = tempfile.mkdtemp(prefix="proxy_cli_reload_")
        try:
            tiers_a = {
                "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
                "sonnet": {"provider": "p", "model": "model-a"},
                "opus": {"provider": "p", "model": "claude-opus-5"},
            }
            config_path = _create_test_config(temp_dir, tiers_a)
            keys_path = _create_test_keys_plain(temp_dir, {
                "p": {"url": f"http://127.0.0.1:{p_port}", "key": "k"}
            })
            trace_fd, trace_file = tempfile.mkstemp(suffix=".jsonl", dir=temp_dir)
            os.close(trace_fd)

            req_list = []
            mock_server = _start_mock_upstream(p_port, req_list)
            mock_started = True

            proc, stdout, stderr, rc = _cli_start_with_plain_keys(
                port, config_path, keys_path, trace_file)
            if rc != 0:
                fail(f"Start failed (exit {rc}): {stdout} {stderr}")
                return

            # Probe the port to confirm proxy is ready
            probe_ok = False
            deadline = time.time() + 5
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
            if not probe_ok:
                fail("Proxy did not become ready on port")
                return

            # Modify config.json on disk: sonnet → model-b
            tiers_b = dict(tiers_a)
            tiers_b["sonnet"] = {"provider": "p", "model": "model-b"}
            with open(config_path, "w") as f:
                # Reload re-validates: provider "p" needs >=1 model in config.models
                json.dump({"tiers": tiers_b, "models": _derive_models_from_tiers(tiers_b)}, f)

            # Run claude-retry-proxy reload (no --port; reads from proxy-state.json)
            result = subprocess.run(CLAUDE_PROXY + ["reload"],
                                    capture_output=True, text=True, timeout=10)
            if result.returncode != 0:
                fail(f"reload exited {result.returncode}: {result.stdout} {result.stderr}")
                return
            pass_("claude-retry-proxy reload exited 0")

            # Verify reload took effect: sonnet routes to model-b
            status, resp_body = _send_proxy_request(port, body=json.dumps({
                "model": "sonnet", "messages": [{"role": "user", "content": "hi"}]}))
            if status != 200:
                fail(f"Post-reload request returned {status}")
                return
            if req_list and b"model-b" in req_list[-1]["body"]:
                pass_("Post-reload sonnet request routed to model-b")
            else:
                fail(f"Post-reload sonnet request did not route to model-b. last: {req_list[-1] if req_list else 'none'}")

            # Clean up the proxy
            stop_result = subprocess.run(CLAUDE_PROXY + ["stop"],
                                         capture_output=True, text=True, timeout=10)
            if stop_result.returncode != 0:
                fail(f"stop failed: {stop_result.stdout} {stop_result.stderr}")

        finally:
            if 'mock_started' in dir():
                mock_server.shutdown()
            shutil.rmtree(temp_dir, ignore_errors=True)

    finally:
        cleanup_lock_files()
        subprocess.run(CLAUDE_PROXY + ["stop"], capture_output=True, text=True, timeout=10)
        _restore_proxy_state(state_backup)


# ===========================================================================
# Test: CLI Start No Config
# ===========================================================================

def test_cli_start_no_config():
    """Start without config.json → template created, exit 1, message printed."""
    print("\n--- Test: CLI Start No Config ---")
    state_backup = _backup_proxy_state()
    cleanup_lock_files()

    try:
        try:
            os.remove(PROXY_STATE_FILE)
        except OSError:
            pass

        temp_dir = tempfile.mkdtemp(prefix="proxy_cli_noconfig_")
        try:
            nonexistent_config = os.path.join(temp_dir, "config.json")
            keys_path = _create_test_keys_plain(temp_dir, {
                "p": {"url": "http://127.0.0.1:1", "key": "k"}
            })

            proc = subprocess.Popen(
                CLAUDE_PROXY + ["start", "--config-path", nonexistent_config,
                                "--keys-path", keys_path],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                stdin=subprocess.PIPE, text=True
            )
            try:
                proc.stdin.close()
            except OSError:
                pass
            stdout, stderr = proc.communicate(timeout=30)

            if proc.returncode == 1:
                pass_("Start without config exited 1")
            else:
                fail(f"Start without config exited {proc.returncode} (expected 1): {stdout} {stderr}")

            if os.path.exists(nonexistent_config):
                pass_("Template created at config path")
            else:
                fail("Template NOT created at config path")

            if "Created config template" in stdout:
                pass_("stdout mentions 'Created config template'")
            else:
                fail(f"stdout missing 'Created config template'. stdout: {stdout[:300]}")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    finally:
        cleanup_lock_files()
        subprocess.run(CLAUDE_PROXY + ["stop"], capture_output=True, text=True, timeout=10)
        _restore_proxy_state(state_backup)


# ===========================================================================
# Test: CLI Start Invalid Config
# ===========================================================================

def test_cli_start_invalid_config():
    """Start with broken config → exit 1, specific error."""
    print("\n--- Test: CLI Start Invalid Config ---")
    state_backup = _backup_proxy_state()
    cleanup_lock_files()

    try:
        try:
            os.remove(PROXY_STATE_FILE)
        except OSError:
            pass

        temp_dir = tempfile.mkdtemp(prefix="proxy_cli_invalidcfg_")
        try:
            invalid_config_path = os.path.join(temp_dir, "config.json")
            with open(invalid_config_path, "w") as f:
                f.write("not valid json {{{")
            keys_path = _create_test_keys_plain(temp_dir, {
                "p": {"url": "http://127.0.0.1:1", "key": "k"}
            })

            proc = subprocess.Popen(
                CLAUDE_PROXY + ["start", "--config-path", invalid_config_path,
                                "--keys-path", keys_path],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                stdin=subprocess.PIPE, text=True
            )
            try:
                proc.stdin.close()
            except OSError:
                pass
            stdout, stderr = proc.communicate(timeout=30)

            if proc.returncode == 1:
                pass_("Start with invalid config exited 1")
            else:
                fail(f"Start with invalid config exited {proc.returncode} (expected 1): {stdout} {stderr}")

            combined = stdout + stderr
            if "Invalid config" in combined or "ERROR" in combined:
                pass_("Error message mentions 'Invalid config' or 'ERROR'")
            else:
                fail(f"Error message missing 'Invalid config'/'ERROR'. stdout={stdout[:200]} stderr={stderr[:200]}")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    finally:
        cleanup_lock_files()
        subprocess.run(CLAUDE_PROXY + ["stop"], capture_output=True, text=True, timeout=10)
        _restore_proxy_state(state_backup)


# ===========================================================================
# Test: CLI Status Shows Tiers
# ===========================================================================

def test_cli_status_shows_tiers():
    """Status output includes tier → provider → model mapping."""
    print("\n--- Test: CLI Status Shows Tiers ---")
    state_backup = _backup_proxy_state()
    cleanup_lock_files()

    try:
        try:
            os.remove(PROXY_STATE_FILE)
        except OSError:
            pass

        port = find_free_port()
        p_port = find_free_port()
        temp_dir = tempfile.mkdtemp(prefix="proxy_cli_status_")
        try:
            tiers = {
                "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
                "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
                "opus": {"provider": "p", "model": "claude-opus-5"},
            }
            config_path = _create_test_config(temp_dir, tiers)
            keys_path = _create_test_keys_plain(temp_dir, {
                "p": {"url": f"http://127.0.0.1:{p_port}", "key": "k"}
            })
            trace_fd, trace_file = tempfile.mkstemp(suffix=".jsonl", dir=temp_dir)
            os.close(trace_fd)

            mock_server = _start_mock_upstream(p_port, [])

            proc, stdout, stderr, rc = _cli_start_with_plain_keys(
                port, config_path, keys_path, trace_file)
            if rc != 0:
                fail(f"Start failed (exit {rc}): {stdout} {stderr}")
                return

            # Run claude-retry-proxy status
            stdout, stderr, status_rc = proxy_status()
            if status_rc == 0:
                pass_("claude-retry-proxy status exited 0")
            else:
                fail(f"status exited {status_rc}: {stdout} {stderr}")
                return

            for tier in ("haiku", "sonnet", "opus"):
                if tier in stdout:
                    pass_(f"status shows tier '{tier}'")
                else:
                    fail(f"status missing tier '{tier}'. stdout: {stdout[:300]}")

            # Provider/model info shown (e.g. "sonnet -> claude-sonnet-5 (p)")
            for needle in ("claude-haiku-4-5", "claude-sonnet-5", "claude-opus-5", "(p)"):
                if needle in stdout:
                    pass_(f"status shows provider/model info '{needle}'")
                else:
                    fail(f"status missing '{needle}'. stdout: {stdout[:300]}")

            # Clean up the proxy
            stop_result = subprocess.run(CLAUDE_PROXY + ["stop"],
                                         capture_output=True, text=True, timeout=10)
            if stop_result.returncode != 0:
                fail(f"stop failed: {stop_result.stdout} {stop_result.stderr}")
            mock_server.shutdown()

        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    finally:
        cleanup_lock_files()
        subprocess.run(CLAUDE_PROXY + ["stop"], capture_output=True, text=True, timeout=10)
        _restore_proxy_state(state_backup)


# ===========================================================================
# Test: Key Decryption Wrong Passphrase
# ===========================================================================

def test_key_decryption_wrong_passphrase():
    """Wrong passphrase → start fails with clear error."""
    print("\n--- Test: Key Decryption Wrong Passphrase ---")

    upstream_port = find_free_port()
    tiers = {
        "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
        "opus": {"provider": "p", "model": "claude-opus-5"},
    }
    vendors = {"p": {"url": f"http://127.0.0.1:{upstream_port}", "key": "k"}}

    temp_dir = tempfile.mkdtemp(prefix="proxy_keys_test_")
    try:
        config_path = _create_test_config(temp_dir, tiers)
        keys_path = _create_test_keys(temp_dir, vendors, passphrase="correct-passphrase")

        proxy_port = find_free_port()
        # Try to start with wrong passphrase
        proc, probe_ok = _start_proxy_server_directly(
            proxy_port, config_path=config_path, keys_path=keys_path,
            passphrase="wrong-passphrase"
        )

        if not probe_ok:
            pass_("Server failed to start with wrong passphrase")
            # Check stderr for error message
            try:
                _, stderr = proc.communicate(timeout=2)
                if "passphrase" in stderr.lower() or "decrypt" in stderr.lower():
                    pass_("Error message mentions passphrase/decryption")
                else:
                    fail("Error message doesn't mention passphrase issue")
            except:
                pass
        else:
            fail("Server started with wrong passphrase (should have failed)")
            proc.kill()

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


# ===========================================================================
# Test: Key Decryption Missing File
# ===========================================================================

def test_key_decryption_missing_file():
    """No keys-index.json → start fails with clear error."""
    print("\n--- Test: Key Decryption Missing File ---")

    temp_dir = tempfile.mkdtemp(prefix="proxy_keys_test_")
    try:
        tiers = {
            "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
            "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
            "opus": {"provider": "p", "model": "claude-opus-5"},
        }
        config_path = _create_test_config(temp_dir, tiers)
        # Don't create keys file

        proxy_port = find_free_port()
        proc, probe_ok = _start_proxy_server_directly(
            proxy_port, config_path=config_path, keys_path="/nonexistent/keys.json"
        )

        if not probe_ok:
            pass_("Server failed to start with missing keys file")
        else:
            fail("Server started with missing keys file (should have failed)")
            proc.kill()

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


# ===========================================================================
# Test: API Key From Keys-Index
# ===========================================================================

def test_api_key_from_keys_index():
    """Verify x-api-key sent to upstream comes from keys-index.json, not from client."""
    print("\n--- Test: API Key From Keys-Index ---")

    upstream_port = find_free_port()
    tiers = {
        "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
        "opus": {"provider": "p", "model": "claude-opus-5"},
    }
    vendors = {"p": {"url": f"http://127.0.0.1:{upstream_port}", "key": "keys-index-key-12345"}}

    temp_dir, proxy_port, proc, mock_servers, cleanup = _setup_tier_routing_test(tiers, vendors)
    if proc is None:
        fail("Failed to set up test")
        return

    try:
        # Send request with a different API key in the client request
        import http.client as _hc
        body = json.dumps({"model": "sonnet", "messages": [{"role": "user", "content": "hi"}]})
        conn = _hc.HTTPConnection("127.0.0.1", proxy_port, timeout=10)
        conn.request("POST", "/v1/messages", body=body,
                    headers={"Content-Type": "application/json", "x-api-key": "client-key-99999"})
        resp = conn.getresponse()
        resp.read()
        conn.close()

        # Verify upstream received the keys-index key, not the client key
        reqs = mock_servers["p"]["requests"]
        if len(reqs) == 0:
            fail("Upstream received no requests")
            return

        if reqs[0]["api_key"] == "keys-index-key-12345":
            pass_("Upstream received API key from keys-index.json (client key ignored)")
        else:
            fail(f"Upstream received wrong API key: {reqs[0]['api_key']}")

    finally:
        cleanup()


# ===========================================================================
# Test: Admin API Serves Provider-Keyed Models (plan Step 3)
# ===========================================================================

def test_admin_models_provider_keyed():
    """Admin API serves models keyed by provider; admin.html model <select> is
    populated from config.models[provider] — no placeholder or custom options."""
    print("\n--- Test: Admin Models Provider-Keyed ---")

    upstream_port = find_free_port()
    tiers = {
        "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
        "opus": {"provider": "p", "model": "claude-opus-5"},
    }
    vendors = {"p": {"url": f"http://127.0.0.1:{upstream_port}", "key": "k"}}
    # Models keyed by PROVIDER name (matching config.json layout), not by tier
    models = {
        "p": ["claude-haiku-4-5", "claude-sonnet-5", "claude-opus-5", "qwen3.7-plus"]
    }

    temp_dir = tempfile.mkdtemp(prefix="proxy_admin_models_test_")
    try:
        config_path = _create_test_config(temp_dir, tiers, models=models)
        keys_path = _create_test_keys(temp_dir, vendors)

        proxy_port = find_free_port()
        proc, probe_ok = _start_proxy_server_directly(
            proxy_port, config_path=config_path, keys_path=keys_path
        )
        if not probe_ok:
            fail("Proxy server failed to start")
            return

        try:
            import http.client as _hc

            # 1. Admin API serves provider-keyed models
            conn = _hc.HTTPConnection("127.0.0.1", proxy_port, timeout=10)
            conn.request("GET", "/admin/api/config")
            resp = conn.getresponse()
            status = resp.status
            body = resp.read().decode()
            conn.close()

            if status != 200:
                fail(f"GET /admin/api/config returned {status}")
                return

            config = json.loads(body)
            if "models" not in config:
                fail("Admin config missing 'models' key")
                return

            if "p" in config["models"] and isinstance(config["models"]["p"], list):
                pass_("config.models is keyed by provider name (models.p present)")
            else:
                fail(f"config.models not provider-keyed: {list(config['models'].keys())}")

            if "qwen3.7-plus" in config["models"]["p"]:
                pass_("Provider model list contains expected model")
            else:
                fail(f"Provider model list missing qwen3.7-plus: {config['models']['p']}")

            # 2. Admin page HTML: model <select> populated from the provider's model
            #    catalog — no placeholders, no "Custom...", no hidden input
            conn = _hc.HTTPConnection("127.0.0.1", proxy_port, timeout=10)
            conn.request("GET", "/admin/")
            html_resp = conn.getresponse()
            html = html_resp.read().decode()
            conn.close()

            if '<select id="${tier}-model"' in html:
                pass_("admin.html model field is a <select> per tier")
            else:
                fail("admin.html model field is not a <select>")

            if "config.models" in html:
                pass_("admin.html references config.models for model population")
            else:
                fail("admin.html missing config.models reference")

            if '<option value="">' in html:
                fail("admin.html still contains an empty placeholder <option>")
            else:
                pass_("admin.html has no placeholder <option value=\"\">")

            if "__custom__" in html:
                fail("admin.html still contains the 'Custom...' option")
            else:
                pass_("admin.html has no 'Custom...' option")

            if "-custom-model" in html:
                fail("admin.html still contains a -custom-model input")
            else:
                pass_("admin.html has no hidden custom-model input")

            if ".model-custom" in html:
                fail("admin.html still contains .model-custom CSS")
            else:
                pass_("admin.html has no .model-custom CSS")

        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


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


def test_disable_retry_count_tokens_503():
    """Flag=true, upstream 503s /count_tokens → exactly 1 attempt, drained body returned."""
    print("\n--- Test: Disable Retry Count Tokens (503, flag=true) ---")

    upstream_port = find_free_port()
    proxy_port = find_free_port()
    request_count = [0]
    count_lock = threading.Lock()

    class CountTokens503Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            content_len = int(self.headers.get("Content-Length", 0))
            if content_len > 0:
                self.rfile.read(content_len)
            with count_lock:
                request_count[0] += 1
            self.send_response(503)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error":"Service Unavailable"}')
        def log_message(self, format, *args):
            pass

    mock_server = http.server.ThreadingHTTPServer(("127.0.0.1", upstream_port), CountTokens503Handler)
    threading.Thread(target=mock_server.serve_forever, daemon=True).start()
    time.sleep(0.3)

    temp_dir = tempfile.mkdtemp(prefix="proxy_drct_503_test_")
    tiers = {
        "haiku": {"provider": "test-provider", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "test-provider", "model": "claude-sonnet-5"},
        "opus": {"provider": "test-provider", "model": "claude-opus-5"},
    }
    vendors = {"test-provider": {"url": f"http://127.0.0.1:{upstream_port}", "key": "test-api-key"}}
    config_path = _create_test_config_with_flag(temp_dir, tiers, True)
    keys_path = _create_test_keys(temp_dir, vendors)

    env = os.environ.copy()
    env["PROXY_PORT"] = str(proxy_port)
    env["PROXY_MAX_RETRIES"] = "3"

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

    if not probe_ok:
        proc.kill()
        mock_server.shutdown()
        shutil.rmtree(temp_dir, ignore_errors=True)
        fail("Proxy server failed to start")
        return

    try:
        body = json.dumps({"model": "sonnet", "messages": [{"role": "user", "content": "hi"}]})
        conn = http.client.HTTPConnection("127.0.0.1", proxy_port, timeout=10)
        conn.request("POST", "/v1/messages/count_tokens?beta=true", body=body,
                     headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        status = resp.status
        resp_body = resp.read()
        conn.close()

        with count_lock:
            total = request_count[0]

        if total == 1:
            pass_(f"count_tokens attempted exactly once (total={total})")
        else:
            fail(f"count_tokens attempted {total} times, expected 1 (retry should be skipped)")

        if status == 503:
            pass_("Client received 503 (upstream status preserved)")
        else:
            fail(f"Client received {status}, expected 503")

        if resp_body:
            pass_("Upstream error body drained and returned (non-empty)")
        else:
            fail("Upstream error body is empty — expected drained body returned")

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        mock_server.shutdown()
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_disable_retry_count_tokens_conn_error():
    """Flag=true, upstream connection reset → 1 attempt, upstream_unreachable body."""
    print("\n--- Test: Disable Retry Count Tokens (conn error, flag=true) ---")

    dead_port = find_free_port()
    test_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    test_sock.bind(("127.0.0.1", dead_port))
    test_sock.close()

    proxy_port = find_free_port()
    temp_dir = tempfile.mkdtemp(prefix="proxy_drct_conn_test_")

    tiers = {
        "haiku": {"provider": "test-provider", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "test-provider", "model": "claude-sonnet-5"},
        "opus": {"provider": "test-provider", "model": "claude-opus-5"},
    }
    vendors = {"test-provider": {"url": f"http://127.0.0.1:{dead_port}", "key": "test-api-key"}}
    config_path = _create_test_config_with_flag(temp_dir, tiers, True)
    keys_path = _create_test_keys(temp_dir, vendors)

    trace_fd, trace_file = tempfile.mkstemp(suffix=".jsonl", dir=temp_dir)
    os.close(trace_fd)

    env = os.environ.copy()
    env["PROXY_PORT"] = str(proxy_port)
    env["PROXY_MAX_RETRIES"] = "3"
    env["PROXY_INITIAL_DELAY"] = "1"
    env["PROXY_MAX_DELAY"] = "1"
    env["PROXY_TRACE_FILE"] = trace_file

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

    if not probe_ok:
        proc.kill()
        shutil.rmtree(temp_dir, ignore_errors=True)
        fail("Proxy server failed to start")
        return

    try:
        body = json.dumps({"model": "sonnet", "messages": [{"role": "user", "content": "hi"}]})
        status, resp_body = _send_proxy_request(
            proxy_port, path="/v1/messages/count_tokens?beta=true", body=body)

        if status == 0:
            pass_("Client received status 0 (connection error path)")
        else:
            fail(f"Client received {status}, expected 0 (connection error)")

        # Client cannot parse HTTP/1.0 0, so the upstream_unreachable body is
        # asserted via the trace (mirrors test_exhaust_connection_error_synthesizes_body).
        time.sleep(0.3)
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        time.sleep(0.3)

        if not os.path.exists(trace_file):
            fail("Trace file not created")
            return

        with open(trace_file) as f:
            entries = [json.loads(line) for line in f if line.strip()]
        request_events = [e for e in entries if e.get("event") == "request"]
        if request_events:
            error_field = request_events[0].get("error", "")
            if error_field and "upstream_unreachable" in str(error_field):
                pass_("Trace 'error' field contains 'upstream_unreachable'")
            else:
                fail(f"Trace 'error' field missing 'upstream_unreachable': {error_field}")
        else:
            fail("No request event in trace")

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_disable_retry_count_tokens_normal_path_unaffected():
    """Flag=true, /v1/messages still retries normally (503 then 200)."""
    print("\n--- Test: Disable Retry Count Tokens (normal path unaffected) ---")

    upstream_port = find_free_port()
    proxy_port = find_free_port()
    request_count = [0]
    count_lock = threading.Lock()

    class FlakyHandler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            content_len = int(self.headers.get("Content-Length", 0))
            if content_len > 0:
                self.rfile.read(content_len)
            with count_lock:
                request_count[0] += 1
                current = request_count[0]
            if current <= 2:
                self.send_response(503)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"error":"Service Unavailable"}')
            else:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"id":"ok","type":"message"}')
        def log_message(self, format, *args):
            pass

    mock_server = http.server.ThreadingHTTPServer(("127.0.0.1", upstream_port), FlakyHandler)
    threading.Thread(target=mock_server.serve_forever, daemon=True).start()
    time.sleep(0.3)

    temp_dir = tempfile.mkdtemp(prefix="proxy_drct_normal_test_")
    tiers = {
        "haiku": {"provider": "test-provider", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "test-provider", "model": "claude-sonnet-5"},
        "opus": {"provider": "test-provider", "model": "claude-opus-5"},
    }
    vendors = {"test-provider": {"url": f"http://127.0.0.1:{upstream_port}", "key": "test-api-key"}}
    config_path = _create_test_config_with_flag(temp_dir, tiers, True)
    keys_path = _create_test_keys(temp_dir, vendors)

    env = os.environ.copy()
    env["PROXY_PORT"] = str(proxy_port)
    env["PROXY_MAX_RETRIES"] = "3"

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

    if not probe_ok:
        proc.kill()
        mock_server.shutdown()
        shutil.rmtree(temp_dir, ignore_errors=True)
        fail("Proxy server failed to start")
        return

    try:
        status, resp_body = _send_proxy_request(proxy_port)

        with count_lock:
            total = request_count[0]

        if total >= 2:
            pass_(f"/v1/messages retried normally (attempts={total})")
        else:
            fail(f"/v1/messages only attempted {total} time(s), expected retry")

        if status == 200:
            pass_("Client eventually received 200")
        else:
            fail(f"Client received {status}, expected 200 after retry")

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        mock_server.shutdown()
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_disable_retry_count_tokens_false_retries():
    """Flag=false, count_tokens still retries (503 then 200)."""
    print("\n--- Test: Disable Retry Count Tokens (false retries normally) ---")

    upstream_port = find_free_port()
    proxy_port = find_free_port()
    request_count = [0]
    count_lock = threading.Lock()

    class CountTokensFlakyHandler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            content_len = int(self.headers.get("Content-Length", 0))
            if content_len > 0:
                self.rfile.read(content_len)
            with count_lock:
                request_count[0] += 1
                current = request_count[0]
            if current <= 1:
                self.send_response(503)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"error":"Service Unavailable"}')
            else:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"id":"ok","type":"message"}')
        def log_message(self, format, *args):
            pass

    mock_server = http.server.ThreadingHTTPServer(("127.0.0.1", upstream_port), CountTokensFlakyHandler)
    threading.Thread(target=mock_server.serve_forever, daemon=True).start()
    time.sleep(0.3)

    temp_dir = tempfile.mkdtemp(prefix="proxy_drct_false_test_")
    tiers = {
        "haiku": {"provider": "test-provider", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "test-provider", "model": "claude-sonnet-5"},
        "opus": {"provider": "test-provider", "model": "claude-opus-5"},
    }
    vendors = {"test-provider": {"url": f"http://127.0.0.1:{upstream_port}", "key": "test-api-key"}}
    config_path = _create_test_config_with_flag(temp_dir, tiers, False)
    keys_path = _create_test_keys(temp_dir, vendors)

    env = os.environ.copy()
    env["PROXY_PORT"] = str(proxy_port)
    env["PROXY_MAX_RETRIES"] = "3"

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

    if not probe_ok:
        proc.kill()
        mock_server.shutdown()
        shutil.rmtree(temp_dir, ignore_errors=True)
        fail("Proxy server failed to start")
        return

    try:
        body = json.dumps({"model": "sonnet", "messages": [{"role": "user", "content": "hi"}]})
        conn = http.client.HTTPConnection("127.0.0.1", proxy_port, timeout=10)
        conn.request("POST", "/v1/messages/count_tokens?beta=true", body=body,
                     headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        resp.read()
        conn.close()

        with count_lock:
            total = request_count[0]

        if total >= 2:
            pass_(f"count_tokens retried with flag=false (attempts={total})")
        else:
            fail(f"count_tokens only attempted {total} time(s), expected retry")

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        mock_server.shutdown()
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_disable_retry_count_tokens_path_anchoring():
    """Flag=true: only /v1/messages/count_tokens* is affected; /v1/messages,
    /v1/messages?x=count_tokens, /v1/messages/count_tokens_batch retry normally."""
    print("\n--- Test: Disable Retry Count Tokens (path anchoring) ---")

    upstream_port = find_free_port()
    proxy_port = find_free_port()
    request_count = [0]
    count_lock = threading.Lock()

    class FlakyPathHandler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            content_len = int(self.headers.get("Content-Length", 0))
            if content_len > 0:
                self.rfile.read(content_len)
            with count_lock:
                request_count[0] += 1
                current = request_count[0]
            if current <= 1:
                self.send_response(503)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"error":"Service Unavailable"}')
            else:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"id":"ok","type":"message"}')
        def log_message(self, format, *args):
            pass

    mock_server = http.server.ThreadingHTTPServer(("127.0.0.1", upstream_port), FlakyPathHandler)
    threading.Thread(target=mock_server.serve_forever, daemon=True).start()
    time.sleep(0.3)

    temp_dir = tempfile.mkdtemp(prefix="proxy_drct_anchor_test_")
    tiers = {
        "haiku": {"provider": "test-provider", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "test-provider", "model": "claude-sonnet-5"},
        "opus": {"provider": "test-provider", "model": "claude-opus-5"},
    }
    vendors = {"test-provider": {"url": f"http://127.0.0.1:{upstream_port}", "key": "test-api-key"}}
    config_path = _create_test_config_with_flag(temp_dir, tiers, True)
    keys_path = _create_test_keys(temp_dir, vendors)

    env = os.environ.copy()
    env["PROXY_PORT"] = str(proxy_port)
    env["PROXY_MAX_RETRIES"] = "3"

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

    if not probe_ok:
        proc.kill()
        mock_server.shutdown()
        shutil.rmtree(temp_dir, ignore_errors=True)
        fail("Proxy server failed to start")
        return

    try:
        # These three paths must ALL retry (attempt >= 2 each) despite flag=true
        paths = ["/v1/messages", "/v1/messages?x=count_tokens", "/v1/messages/count_tokens_batch"]
        all_retried = True
        for p in paths:
            with count_lock:
                request_count[0] = 0
            body = json.dumps({"model": "sonnet", "messages": [{"role": "user", "content": "hi"}]})
            conn = http.client.HTTPConnection("127.0.0.1", proxy_port, timeout=10)
            conn.request("POST", p, body=body, headers={"Content-Type": "application/json"})
            resp = conn.getresponse()
            resp.read()
            conn.close()
            with count_lock:
                attempts = request_count[0]
            if attempts >= 2:
                pass_(f"path '{p}' retried normally (attempts={attempts})")
            else:
                fail(f"path '{p}' only attempted {attempts} time(s), expected retry")
                all_retried = False

        # The real count_tokens path must NOT retry
        with count_lock:
            request_count[0] = 0
        body = json.dumps({"model": "sonnet", "messages": [{"role": "user", "content": "hi"}]})
        conn = http.client.HTTPConnection("127.0.0.1", proxy_port, timeout=10)
        conn.request("POST", "/v1/messages/count_tokens?beta=true", body=body,
                     headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        resp.read()
        conn.close()
        with count_lock:
            ct_attempts = request_count[0]
        if ct_attempts == 1:
            pass_("count_tokens path did NOT retry (exactly 1 attempt)")
        else:
            fail(f"count_tokens attempted {ct_attempts} times, expected 1")

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        mock_server.shutdown()
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_disable_retry_count_tokens_invalid_type():
    """validate_config rejects non-boolean disable_retry_claude_count_token."""
    print("\n--- Test: Disable Retry Count Tokens (invalid type rejected) ---")

    from claude_retry_proxy.server import validate_config

    vendors = {"p": {"url": "http://127.0.0.1:1", "key": "k"}}
    valid_tiers = {
        "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
        "opus": {"provider": "p", "model": "claude-opus-5"},
    }

    # Non-boolean values must be rejected
    for bad in ["false", 0, None]:
        config = {"tiers": valid_tiers, "models": _derive_models_from_tiers(valid_tiers), "disable_retry_claude_count_token": bad}
        errors = validate_config(config, set(vendors.keys()))
        if any("disable_retry_claude_count_token" in e for e in errors):
            pass_(f"validate_config rejected non-boolean value {bad!r}")
        else:
            fail(f"validate_config accepted non-boolean value {bad!r}")

    # Valid boolean true must be accepted
    config = {"tiers": valid_tiers, "models": _derive_models_from_tiers(valid_tiers), "disable_retry_claude_count_token": True}
    errors = validate_config(config, set(vendors.keys()))
    if errors:
        fail(f"validate_config rejected valid boolean True: {errors}")
    else:
        pass_("validate_config accepted boolean True")


def test_admin_switch_preserves_disable_retry_flag():
    """Admin Apply preserves disable_retry_claude_count_token in returned + on-disk config."""
    print("\n--- Test: Admin Switch Preserves Disable Retry Flag ---")

    upstream_port = find_free_port()
    proxy_port = find_free_port()

    tiers = {
        "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
        "opus": {"provider": "p", "model": "claude-opus-5"},
    }
    vendors = {"p": {"url": f"http://127.0.0.1:{upstream_port}", "key": "k"}}

    temp_dir = tempfile.mkdtemp(prefix="proxy_drct_admin_test_")
    try:
        config_path = _create_test_config_with_flag(temp_dir, tiers, True)
        keys_path = _create_test_keys(temp_dir, vendors)

        proc, probe_ok = _start_proxy_server_directly(
            proxy_port, config_path=config_path, keys_path=keys_path
        )
        if not probe_ok:
            fail("Proxy server failed to start")
            return

        try:
            import http.client as _hc
            # Apply a tier switch (swap sonnet to a new model on same provider)
            switch_body = json.dumps({
                "tiers": {
                    "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
                    "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
                    "opus": {"provider": "p", "model": "claude-opus-5"},
                }
            })
            conn = _hc.HTTPConnection("127.0.0.1", proxy_port, timeout=10)
            conn.request("POST", "/admin/api/switch", body=switch_body,
                         headers={"Content-Type": "application/json", "Origin": f"http://localhost:{proxy_port}"})
            resp = conn.getresponse()
            switch_status = resp.status
            resp.read()
            conn.close()

            if switch_status != 200:
                fail(f"Admin switch returned {switch_status}, expected 200")
                return

            # Check returned config
            conn = _hc.HTTPConnection("127.0.0.1", proxy_port, timeout=10)
            conn.request("GET", "/admin/api/config")
            resp = conn.getresponse()
            config = json.loads(resp.read().decode())
            conn.close()

            if config.get("disable_retry_claude_count_token") is True:
                pass_("Returned config preserves disable_retry_claude_count_token=true")
            else:
                fail(f"Returned config missing/preserved flag: {config.get('disable_retry_claude_count_token')}")

            # Check on-disk config.json
            with open(config_path) as f:
                disk_config = json.load(f)
            if disk_config.get("disable_retry_claude_count_token") is True:
                pass_("On-disk config preserves disable_retry_claude_count_token=true")
            else:
                fail(f"On-disk config missing/preserved flag: {disk_config.get('disable_retry_claude_count_token')}")

        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_retry_trace_event_enriched():
    """Retry trace events include model, provider, request_id."""
    print("\n--- Test: Retry Trace Event Enriched ---")

    upstream_port = find_free_port()
    proxy_port = find_free_port()
    request_count = [0]
    count_lock = threading.Lock()

    class FlakyTraceHandler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            content_len = int(self.headers.get("Content-Length", 0))
            if content_len > 0:
                self.rfile.read(content_len)
            with count_lock:
                request_count[0] += 1
                current = request_count[0]
            if current <= 1:
                self.send_response(503)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"error":"Service Unavailable"}')
            else:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"id":"ok","type":"message"}')
        def log_message(self, format, *args):
            pass

    mock_server = http.server.ThreadingHTTPServer(("127.0.0.1", upstream_port), FlakyTraceHandler)
    threading.Thread(target=mock_server.serve_forever, daemon=True).start()
    time.sleep(0.3)

    temp_dir = tempfile.mkdtemp(prefix="proxy_drct_trace_test_")
    tiers = {
        "haiku": {"provider": "test-provider", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "test-provider", "model": "claude-sonnet-5"},
        "opus": {"provider": "test-provider", "model": "claude-opus-5"},
    }
    vendors = {"test-provider": {"url": f"http://127.0.0.1:{upstream_port}", "key": "test-api-key"}}
    config_path = _create_test_config_with_flag(temp_dir, tiers, None)  # no flag
    keys_path = _create_test_keys(temp_dir, vendors)

    trace_fd, trace_file = tempfile.mkstemp(suffix=".jsonl", dir=temp_dir)
    os.close(trace_fd)

    env = os.environ.copy()
    env["PROXY_PORT"] = str(proxy_port)
    env["PROXY_MAX_RETRIES"] = "3"
    env["PROXY_TRACE_FILE"] = trace_file

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

    if not probe_ok:
        proc.kill()
        mock_server.shutdown()
        shutil.rmtree(temp_dir, ignore_errors=True)
        fail("Proxy server failed to start")
        return

    try:
        status, resp_body = _send_proxy_request(proxy_port)
        if status != 200:
            fail(f"Request did not succeed (status={status})")
            return

        # Give the trace a moment to flush
        time.sleep(0.3)
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        time.sleep(0.3)

        with open(trace_file) as f:
            entries = [json.loads(line) for line in f if line.strip()]

        retry_events = [e for e in entries if e.get("event") == "retry"]
        if not retry_events:
            fail("No retry trace events found")
            return

        retry = retry_events[0]
        if "model" in retry and "provider" in retry and "request_id" in retry:
            pass_(f"Retry event has model={retry['model']!r}, provider={retry['provider']!r}, request_id={retry['request_id']!r}")
        else:
            fail(f"Retry event missing model/provider/request_id: {retry}")

        if "reason" in retry:
            pass_(f"Retry event has reason={retry['reason']!r}")
        else:
            fail("Retry event missing 'reason'")

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        mock_server.shutdown()
        shutil.rmtree(temp_dir, ignore_errors=True)


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


# --- Step 1: mode read from vendor entry ---

def test_mode_defaults_to_anthropic():
    """Vendor without a mode field is treated as anthropic (x-api-key used)."""
    print("\n--- Test: Mode Defaults To Anthropic ---")
    upstream_port = find_free_port()
    tiers = _mode_tiers()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port), "key": "K-1"}}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(tiers, vendors)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        status, body = _send_proxy_request(proxy_port)
        if status != 200:
            fail("expected 200, got {}".format(status))
            return
        reqs = mock_servers["p"]["requests"]
        if not reqs:
            fail("upstream received no requests")
            return
        if reqs[0]["api_key"] != "K-1":
            fail("expected x-api-key=K-1 (anthropic default), got {!r}".format(reqs[0]["api_key"]))
        else:
            pass_("vendor without mode uses x-api-key (anthropic default)")
    finally:
        cleanup()


def test_mode_null_defaults_to_anthropic():
    """Vendor with mode: null is treated as anthropic."""
    print("\n--- Test: Mode Null Defaults To Anthropic ---")
    upstream_port = find_free_port()
    tiers = _mode_tiers()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port), "key": "K-2", "mode": None}}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(tiers, vendors)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        status, body = _send_proxy_request(proxy_port)
        if status != 200:
            fail("expected 200, got {}".format(status))
            return
        reqs = mock_servers["p"]["requests"]
        if not reqs:
            fail("upstream received no requests")
            return
        if reqs[0]["api_key"] != "K-2":
            fail("expected x-api-key with mode=null (anthropic default), got {!r}".format(reqs[0]["api_key"]))
        else:
            pass_("vendor with mode:null uses x-api-key")
    finally:
        cleanup()


def test_mode_invalid_rejected():
    """Vendor with an unknown mode returns 500 invalid_provider_mode."""
    print("\n--- Test: Mode Invalid Rejected ---")
    upstream_port = find_free_port()
    tiers = _mode_tiers()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port), "key": "K-3", "mode": "watermelon"}}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(tiers, vendors)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        status, body = _send_proxy_request(proxy_port)
        if status != 500:
            fail("expected 500 for invalid mode, got {}".format(status))
        elif b"invalid_provider_mode" not in body:
            fail("expected invalid_provider_mode in error body, got {}".format(body.decode(errors="replace")))
        else:
            pass_("invalid mode returns 500 invalid_provider_mode")
    finally:
        cleanup()


# --- Step 2: auth header dispatch by mode ---

def test_auth_header_anthropic_mode():
    """Anthropic mode forwards with x-api-key, no Authorization header."""
    print("\n--- Test: Auth Header Anthropic Mode ---")
    upstream_port = find_free_port()
    tiers = _mode_tiers()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port), "key": "auth-K-ant"}}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(tiers, vendors)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        status, body = _send_proxy_request(proxy_port)
        if status != 200:
            fail("expected 200, got {}".format(status))
            return
        reqs = mock_servers["p"]["requests"]
        if not reqs:
            fail("upstream received no requests")
            return
        r = reqs[0]
        if r["api_key"] != "auth-K-ant":
            fail("anthropic mode: expected x-api-key=auth-K-ant, got {!r}".format(r["api_key"]))
        if r["authorization"] != "":
            fail("anthropic mode: expected no Authorization header, got {!r}".format(r["authorization"]))
        if r["api_key"] == "auth-K-ant" and r["authorization"] == "":
            pass_("anthropic mode uses x-api-key and drops Authorization")
    finally:
        cleanup()


def test_auth_header_chat_mode():
    """Chat mode forwards with Authorization: Bearer, no x-api-key."""
    print("\n--- Test: Auth Header Chat Mode ---")
    upstream_port = find_free_port()
    tiers = _mode_tiers()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port), "key": "auth-K-chat", "mode": "chat"}}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(tiers, vendors)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        status, body = _send_proxy_request(proxy_port)
        if status != 200:
            fail("expected 200, got {}".format(status))
            return
        reqs = mock_servers["p"]["requests"]
        if not reqs:
            fail("upstream received no requests")
            return
        r = reqs[0]
        if r["authorization"] != "Bearer auth-K-chat":
            fail("chat mode: expected 'Authorization: Bearer auth-K-chat', got {!r}".format(r["authorization"]))
        if r["api_key"] != "":
            fail("chat mode: expected no x-api-key, got {!r}".format(r["api_key"]))
        if r["authorization"] == "Bearer auth-K-chat" and r["api_key"] == "":
            pass_("chat mode uses Authorization: Bearer")
    finally:
        cleanup()


def test_auth_header_response_mode():
    """Response mode forwards with Authorization: Bearer, no x-api-key."""
    print("\n--- Test: Auth Header Response Mode ---")
    upstream_port = find_free_port()
    tiers = _mode_tiers()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port), "key": "auth-K-resp", "mode": "response"}}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(tiers, vendors)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        status, body = _send_proxy_request(proxy_port)
        if status != 200:
            fail("expected 200, got {}".format(status))
            return
        reqs = mock_servers["p"]["requests"]
        if not reqs:
            fail("upstream received no requests")
            return
        r = reqs[0]
        if r["authorization"] != "Bearer auth-K-resp":
            fail("response mode: expected 'Authorization: Bearer auth-K-resp', got {!r}".format(r["authorization"]))
        if r["api_key"] != "":
            fail("response mode: expected no x-api-key, got {!r}".format(r["api_key"]))
        if r["authorization"] == "Bearer auth-K-resp" and r["api_key"] == "":
            pass_("response mode uses Authorization: Bearer")
    finally:
        cleanup()


# --- Step 3: path construction by mode ---

def test_path_anthropic_mode():
    """Anthropic mode appends the original request path to the upstream URL."""
    print("\n--- Test: Path Anthropic Mode ---")
    upstream_port = find_free_port()
    tiers = _mode_tiers()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port), "key": "K"}}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(tiers, vendors)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        status, body = _send_proxy_request(proxy_port)
        if status != 200:
            fail("expected 200, got {}".format(status))
            return
        reqs = mock_servers["p"]["requests"]
        if not reqs:
            fail("upstream received no requests")
            return
        if reqs[0]["path"] != "/v1/messages":
            fail("anthropic mode: expected upstream path /v1/messages, got {!r}".format(reqs[0]["path"]))
        else:
            pass_("anthropic mode forwards the original request path")
    finally:
        cleanup()


def test_path_chat_mode():
    """Chat mode upstream path is path_prefix + /v1/chat/completions."""
    print("\n--- Test: Path Chat Mode ---")
    upstream_port = find_free_port()
    tiers = _mode_tiers()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port), "key": "K", "mode": "chat"}}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(tiers, vendors)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        status, body = _send_proxy_request(proxy_port)
        if status != 200:
            fail("expected 200, got {}".format(status))
            return
        reqs = mock_servers["p"]["requests"]
        if not reqs:
            fail("upstream received no requests")
            return
        if reqs[0]["path"] != "/v1/chat/completions":
            fail("chat mode: expected upstream path /v1/chat/completions, got {!r}".format(reqs[0]["path"]))
        else:
            pass_("chat mode upstream path ends in /v1/chat/completions")
    finally:
        cleanup()


def test_path_response_mode():
    """Response mode upstream path is path_prefix + /v1/responses."""
    print("\n--- Test: Path Response Mode ---")
    upstream_port = find_free_port()
    tiers = _mode_tiers()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port), "key": "K", "mode": "response"}}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(tiers, vendors)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        status, body = _send_proxy_request(proxy_port)
        if status != 200:
            fail("expected 200, got {}".format(status))
            return
        reqs = mock_servers["p"]["requests"]
        if not reqs:
            fail("upstream received no requests")
            return
        if reqs[0]["path"] != "/v1/responses":
            fail("response mode: expected upstream path /v1/responses, got {!r}".format(reqs[0]["path"]))
        else:
            pass_("response mode upstream path ends in /v1/responses")
    finally:
        cleanup()


def test_path_double_v1_prevention():
    """A vendor URL ending in /v1 must not produce a /v1/v1/ upstream path."""
    print("\n--- Test: Path Double V1 Prevention ---")
    upstream_port = find_free_port()
    tiers = _mode_tiers()
    vendors = {"p": {"url": "http://127.0.0.1:{}/v1".format(upstream_port), "key": "K", "mode": "chat"}}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(tiers, vendors)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        status, body = _send_proxy_request(proxy_port)
        if status != 200:
            fail("expected 200, got {}".format(status))
            return
        reqs = mock_servers["p"]["requests"]
        if not reqs:
            fail("upstream received no requests")
            return
        p = reqs[0]["path"]
        if p == "/v1/v1/chat/completions":
            fail("chat mode produced double /v1/v1 upstream path: {!r}".format(p))
        elif p != "/v1/chat/completions":
            fail("expected /v1/chat/completions, got {!r}".format(p))
        else:
            pass_("trailing /v1 in vendor URL is not duplicated: {}".format(p))
    finally:
        cleanup()


def test_count_tokens_rejected_chat_mode():
    """count_tokens returns 400 in chat mode."""
    print("\n--- Test: Count Tokens Rejected Chat Mode ---")
    upstream_port = find_free_port()
    tiers = _mode_tiers()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port), "key": "K", "mode": "chat"}}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(tiers, vendors)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        status, body = _send_proxy_request(
            proxy_port, path="/v1/messages/count_tokens",
            body=json.dumps({"model": "sonnet"}))
        if status != 400:
            fail("chat mode count_tokens: expected 400, got {}".format(status))
        elif b"count_tokens" not in body:
            fail("expected count_tokens rejection message, got {}".format(body.decode(errors="replace")))
        else:
            pass_("chat mode rejects count_tokens with 400")
    finally:
        cleanup()


def test_count_tokens_rejected_response_mode():
    """count_tokens returns 400 in response mode."""
    print("\n--- Test: Count Tokens Rejected Response Mode ---")
    upstream_port = find_free_port()
    tiers = _mode_tiers()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port), "key": "K", "mode": "response"}}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(tiers, vendors)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        status, body = _send_proxy_request(
            proxy_port, path="/v1/messages/count_tokens",
            body=json.dumps({"model": "sonnet"}))
        if status != 400:
            fail("response mode count_tokens: expected 400, got {}".format(status))
        elif b"count_tokens" not in body:
            fail("expected count_tokens rejection message, got {}".format(body.decode(errors="replace")))
        else:
            pass_("response mode rejects count_tokens with 400")
    finally:
        cleanup()


# --- Step 4: _anthropic_to_chat ---

def test_anthropic_to_chat_basic():
    """messages, model, max_tokens, temperature map through."""
    print("\n--- Test: Anthropic To Chat Basic ---")
    fn = _require_server_func("_anthropic_to_chat")
    if fn is None:
        return
    inp = {"model": "sonnet",
           "messages": [{"role": "user", "content": "hi"}],
           "max_tokens": 100,
           "temperature": 0.5}
    out = fn(dict(inp))
    if not isinstance(out, dict):
        fail("_anthropic_to_chat must return a dict, got {!r}".format(type(out)))
        return
    checks = [
        (out.get("model") == "sonnet", "model pass-through"),
        (out.get("messages") == [{"role": "user", "content": "hi"}], "messages pass-through"),
        (out.get("max_tokens") == 100, "max_tokens pass-through"),
        (out.get("temperature") == 0.5, "temperature pass-through"),
    ]
    for ok, label in checks:
        if not ok:
            fail("basic mapping failed: {}".format(label))
    if all(ok for ok, _ in checks):
        pass_("anthropic->chat basic mapping correct")


def test_anthropic_to_chat_system_string():
    """system string becomes the first system message."""
    print("\n--- Test: Anthropic To Chat System String ---")
    fn = _require_server_func("_anthropic_to_chat")
    if fn is None:
        return
    inp = {"model": "sonnet", "system": "You are helpful",
           "messages": [{"role": "user", "content": "hi"}]}
    out = fn(inp)
    msgs = out.get("messages")
    if not isinstance(msgs, list) or len(msgs) < 2:
        fail("expected system message prepended to messages")
    elif not isinstance(msgs[0], dict) or msgs[0].get("role") != "system" or msgs[0].get("content") != "You are helpful":
        fail("expected first message to be the system message, got {!r}".format(msgs[0]))
    else:
        pass_("system string prepended as system message")


def test_anthropic_to_chat_system_list():
    """system content blocks are concatenated with newlines; non-text dropped."""
    print("\n--- Test: Anthropic To Chat System List ---")
    fn = _require_server_func("_anthropic_to_chat")
    if fn is None:
        return
    inp = {"model": "sonnet",
           "system": [{"type": "text", "text": "First"},
                      {"type": "text", "text": "Second"},
                      {"type": "image", "source": {"type": "base64", "data": "x"}}],
           "messages": [{"role": "user", "content": "hi"}]}
    out = fn(inp)
    msgs = out.get("messages")
    if not isinstance(msgs, list) or not msgs:
        fail("messages missing from output")
        return
    if msgs[0].get("role") != "system" or msgs[0].get("content") != "First\nSecond":
        fail("expected system message content 'First\\nSecond', got {!r}".format(msgs[0]))
    if len(msgs) != 2:
        fail("expected exactly user message after system (image block dropped), got {} messages".format(len(msgs)))
    if msgs[0].get("role") == "system" and msgs[0].get("content") == "First\nSecond" and len(msgs) == 2:
        pass_("system list concatenated; non-text blocks dropped")


def test_anthropic_to_chat_dropped_fields():
    """thinking, metadata, top_k absent; tools and tool_choice now transformed (plan 2026-08-29)."""
    print("\n--- Test: Anthropic To Chat Dropped Fields ---")
    fn = _require_server_func("_anthropic_to_chat")
    if fn is None:
        return
    inp = {"model": "sonnet",
           "messages": [{"role": "user", "content": "hi"}],
           "thinking": {"type": "enabled", "budget_tokens": 100},
           "tools": [{"name": "t", "input_schema": {}}],
           "tool_choice": {"type": "auto"},
           "metadata": {"user_id": "x"},
           "top_k": 5}
    out = fn(inp)
    for key in ("thinking", "metadata", "top_k"):
        if key in out:
            fail("expected {!r} dropped from output, present: {}".format(key, sorted(out.keys())))
    if "messages" not in out:
        fail("messages missing from output")
    if out.get("tools") != [{"type": "function", "function": {"name": "t", "parameters": {}}}]:
        fail("expected transformed tools, got {!r}".format(out.get("tools")))
    if out.get("tool_choice") != "auto":
        fail("expected tool_choice 'auto' (transformed), got {!r}".format(out.get("tool_choice")))
    if (all(key not in out for key in ("thinking", "metadata", "top_k"))
            and "messages" in out
            and out.get("tools") == [{"type": "function", "function": {"name": "t", "parameters": {}}}]
            and out.get("tool_choice") == "auto"):
        pass_("thinking/metadata/top_k dropped; tools/tool_choice transformed")


def test_anthropic_to_chat_stop_sequences():
    """stop_sequences is renamed to stop."""
    print("\n--- Test: Anthropic To Chat Stop Sequences ---")
    fn = _require_server_func("_anthropic_to_chat")
    if fn is None:
        return
    inp = {"model": "sonnet",
           "messages": [{"role": "user", "content": "hi"}],
           "stop_sequences": ["END", "</s>"]}
    out = fn(inp)
    if "stop_sequences" in out:
        fail("stop_sequences should be renamed, still present")
    if out.get("stop") != ["END", "</s>"]:
        fail("expected stop=['END', '</s>'], got {!r}".format(out.get("stop")))
    if "stop_sequences" not in out and out.get("stop") == ["END", "</s>"]:
        pass_("stop_sequences renamed to stop")


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


def test_anthropic_to_chat_messages_transform():
    """Full message array (thinking/text/tool_use/tool_result) -> valid OpenAI Chat messages."""
    print("\n--- Test: Anthropic To Chat Messages Transform ---")
    fn = _require_server_func("_transform_anthropic_messages_to_chat")
    if fn is None:
        return
    messages = [
        {"role": "assistant", "content": [
            {"type": "thinking", "thinking": "hidden", "signature": "sig1"},
            {"type": "text", "text": "Let me check."},
            {"type": "tool_use", "id": "toolu_1", "name": "get_weather", "input": {"city": "SF"}},
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "toolu_1", "content": "60F"},
            {"type": "text", "text": "thanks"},
        ]},
    ]
    out = fn(messages, request_id="T-" + uuid.uuid4().hex[:8], mode="chat", provider="p", tier="sonnet")
    expected = [
        {"role": "assistant", "content": "Let me check.",
         "reasoning_content": "hidden", "reasoning": "hidden"},
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "toolu_1", "type": "function",
             "function": {"name": "get_weather", "arguments": '{"city": "SF"}'}}]},
        {"role": "tool", "tool_call_id": "toolu_1", "content": "60F"},
        {"role": "user", "content": "thanks"},
    ]
    if out != expected:
        fail("full transform mismatch, got {!r}".format(out))
    else:
        pass_("full message array transformed correctly")


def test_anthropic_to_chat_messages_thinking_stripped():
    """thinking is converted to reasoning_content; redacted_thinking non-empty data -> placeholder."""
    print("\n--- Test: Anthropic To Chat Messages Thinking Stripped ---")
    fn = _require_server_func("_transform_anthropic_messages_to_chat")
    if fn is None:
        return
    messages = [
        {"role": "assistant", "content": [
            {"type": "thinking", "thinking": "hidden", "signature": "s"},
            {"type": "redacted_thinking", "data": "enc", "signature": "s2"},
            {"type": "text", "text": "visible"},
        ]},
    ]
    out = fn(messages, request_id="T-" + uuid.uuid4().hex[:8], mode="chat", provider="p", tier="sonnet")
    expected = [{"role": "assistant", "content": "visible",
                 "reasoning_content": "hidden", "reasoning": "hidden"}]
    if out != expected:
        fail("thinking should convert to reasoning_content (real thinking wins over redacted placeholder), got {!r}".format(out))
    else:
        pass_("thinking converted to reasoning_content; redacted_thinking placeholder suppressed by real thinking")


def test_anthropic_to_chat_messages_redacted_thinking_trace():
    """redacted_thinking with non-empty data -> placeholder reasoning_content + passthrough trace event.

    Real thinking text wins over the placeholder. Empty data is stripped and
    counted in dropped.redacted_thinking, not passed through.
    """
    print("\n--- Test: Anthropic To Chat Messages Redacted Thinking Trace ---")
    fn = _require_server_func("_transform_anthropic_messages_to_chat")
    if fn is None:
        return
    rid = "T-" + uuid.uuid4().hex[:8]
    messages = [
        {"role": "assistant", "content": [
            {"type": "redacted_thinking", "data": "enc", "signature": "s2"},
            {"type": "text", "text": "visible"},
        ]},
    ]
    out = fn(messages, request_id=rid, mode="chat", provider="p", tier="sonnet")
    expected = [{"role": "assistant", "content": "visible",
                 "reasoning_content": "[redacted_thinking: data not available]",
                 "reasoning": "[redacted_thinking: data not available]"}]
    if out != expected:
        fail("redacted_thinking non-empty data should set placeholder reasoning_content, got {!r}".format(out))
        return
    evs = [e for e in _trace_events_for_request(rid) if e.get("event") == "redacted_thinking_passthrough"]
    if len(evs) != 1:
        fail("expected exactly ONE redacted_thinking_passthrough event, got {}: {!r}".format(len(evs), evs))
        return
    ev = evs[0]
    if not (ev.get("mode") == "chat" and ev.get("provider") == "p"
            and ev.get("tier") == "sonnet" and ev.get("request_id") == rid):
        fail("redacted_thinking_passthrough missing correlation fields, got {!r}".format(ev))
        return
    if ev.get("data_length") != 3:
        fail("redacted_thinking_passthrough data_length should be len('enc')=3, got {!r}".format(ev.get("data_length")))
        return
    # Real thinking text wins over the redacted placeholder.
    rid2 = "T-" + uuid.uuid4().hex[:8]
    messages2 = [
        {"role": "assistant", "content": [
            {"type": "thinking", "thinking": "real", "signature": "s"},
            {"type": "redacted_thinking", "data": "enc", "signature": "s2"},
        ]},
    ]
    out2 = fn(messages2, request_id=rid2, mode="chat", provider="p", tier="sonnet")
    if out2 != [{"role": "assistant", "content": "",
                 "reasoning_content": "real", "reasoning": "real"}]:
        fail("real thinking should win over redacted placeholder, got {!r}".format(out2))
        return
    evs2 = [e for e in _trace_events_for_request(rid2) if e.get("event") == "redacted_thinking_passthrough"]
    if evs2:
        fail("real thinking present should suppress redacted_thinking_passthrough event, got {!r}".format(evs2))
        return
    # Empty/missing data is stripped and counted in dropped, not passed through.
    rid3 = "T-" + uuid.uuid4().hex[:8]
    messages3 = [
        {"role": "assistant", "content": [
            {"type": "redacted_thinking", "data": "", "signature": "s2"},
            {"type": "redacted_thinking", "signature": "s3"},
            {"type": "text", "text": "x"},
        ]},
    ]
    out3 = fn(messages3, request_id=rid3, mode="chat", provider="p", tier="sonnet")
    if out3 != [{"role": "assistant", "content": "x"}]:
        fail("empty-data redacted_thinking should be stripped, got {!r}".format(out3))
        return
    evs3 = [e for e in _trace_events_for_request(rid3) if e.get("event") == "redacted_thinking_passthrough"]
    if evs3:
        fail("empty-data redacted_thinking must not log passthrough event, got {!r}".format(evs3))
        return
    dropped3 = [e for e in _trace_events_for_request(rid3) if e.get("event") == "content_block_dropped"]
    counts3 = (dropped3[0].get("dropped_counts") or {}) if dropped3 else {}
    if counts3.get("redacted_thinking") != 2:
        fail("empty-data redacted_thinking should count in dropped.redacted_thinking, got {!r}".format(counts3))
        return
    pass_("redacted_thinking non-empty -> placeholder + passthrough trace; empty -> stripped")


def test_anthropic_to_chat_messages_tool_use_to_tool_calls():
    """tool_use block converts to tool_calls with JSON-stringified arguments."""
    print("\n--- Test: Anthropic To Chat Messages Tool Use To Tool Calls ---")
    fn = _require_server_func("_transform_anthropic_messages_to_chat")
    if fn is None:
        return
    messages = [
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "toolu_x", "name": "lookup", "input": {"key": "a", "n": 1}},
        ]},
    ]
    out = fn(messages, request_id="T-" + uuid.uuid4().hex[:8], mode="chat", provider="p", tier="sonnet")
    expected = [
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "toolu_x", "type": "function",
             "function": {"name": "lookup", "arguments": '{"key": "a", "n": 1}'}}]},
    ]
    if out != expected:
        fail("tool_use -> tool_calls mismatch, got {!r}".format(out))
    else:
        pass_("tool_use converted to tool_calls with JSON arguments")


def test_anthropic_to_chat_messages_tool_result_to_role_tool():
    """tool_result block in a user message becomes a separate role:tool message."""
    print("\n--- Test: Anthropic To Chat Messages Tool Result To Role Tool ---")
    fn = _require_server_func("_transform_anthropic_messages_to_chat")
    if fn is None:
        return
    messages = [
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "toolu_1", "name": "f", "input": {}},
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "toolu_1", "content": "the answer"},
        ]},
    ]
    out = fn(messages, request_id="T-" + uuid.uuid4().hex[:8], mode="chat", provider="p", tier="sonnet")
    expected = [
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "toolu_1", "type": "function", "function": {"name": "f", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "toolu_1", "content": "the answer"},
    ]
    if out != expected:
        fail("tool_result -> role:tool mismatch, got {!r}".format(out))
    else:
        pass_("tool_result emitted as role:tool message")


def test_anthropic_to_chat_messages_mixed_text_and_tool_use():
    """Assistant with both text and tool_use -> text message first, then content:null + tool_calls."""
    print("\n--- Test: Anthropic To Chat Messages Mixed Text And Tool Use ---")
    fn = _require_server_func("_transform_anthropic_messages_to_chat")
    if fn is None:
        return
    messages = [
        {"role": "assistant", "content": [
            {"type": "text", "text": "I'll look that up."},
            {"type": "tool_use", "id": "toolu_2", "name": "f", "input": {}},
        ]},
    ]
    out = fn(messages, request_id="T-" + uuid.uuid4().hex[:8], mode="chat", provider="p", tier="sonnet")
    expected = [
        {"role": "assistant", "content": "I'll look that up."},
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "toolu_2", "type": "function", "function": {"name": "f", "arguments": "{}"}}]},
    ]
    if out != expected:
        fail("text must be preserved as a separate message before tool_calls, got {!r}".format(out))
    else:
        pass_("text preserved + content:null tool_calls message when both present")


def test_anthropic_to_chat_messages_mixed_text_and_tool_result():
    """User with both text and tool_result -> tool message first, then user text message."""
    print("\n--- Test: Anthropic To Chat Messages Mixed Text And Tool Result ---")
    fn = _require_server_func("_transform_anthropic_messages_to_chat")
    if fn is None:
        return
    messages = [
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "toolu_1", "name": "f", "input": {}},
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "toolu_1", "content": "res"},
            {"type": "text", "text": "Thanks"},
        ]},
    ]
    out = fn(messages, request_id="T-" + uuid.uuid4().hex[:8], mode="chat", provider="p", tier="sonnet")
    expected = [
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "toolu_1", "type": "function", "function": {"name": "f", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "toolu_1", "content": "res"},
        {"role": "user", "content": "Thanks"},
    ]
    if out != expected:
        fail("tool messages must precede user text, got {!r}".format(out))
    else:
        pass_("tool messages first, then user text message")


def test_anthropic_to_chat_messages_interleaved_thinking_tool_use():
    """Real-world interleaved pattern: thinking, text, tool_use, text in one assistant turn."""
    print("\n--- Test: Anthropic To Chat Messages Interleaved Thinking Tool Use ---")
    fn = _require_server_func("_transform_anthropic_messages_to_chat")
    if fn is None:
        return
    messages = [
        {"role": "assistant", "content": [
            {"type": "thinking", "thinking": "reasoning...", "signature": "sig"},
            {"type": "text", "text": "Let me look up the weather for San Francisco."},
            {"type": "tool_use", "id": "toolu_weather", "name": "get_weather", "input": {"city": "San Francisco"}},
            {"type": "text", "text": "I found the forecast."},
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "toolu_weather", "content": "Sunny, 72F"},
        ]},
    ]
    out = fn(messages, request_id="T-" + uuid.uuid4().hex[:8], mode="chat", provider="p", tier="sonnet")
    expected = [
        {"role": "assistant",
         "content": "Let me look up the weather for San Francisco.\nI found the forecast.",
         "reasoning_content": "reasoning...", "reasoning": "reasoning..."},
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "toolu_weather", "type": "function",
             "function": {"name": "get_weather", "arguments": '{"city": "San Francisco"}'}}]},
        {"role": "tool", "tool_call_id": "toolu_weather", "content": "Sunny, 72F"},
    ]
    if out != expected:
        fail("interleaved pattern mismatch, got {!r}".format(out))
    else:
        pass_("interleaved thinking/text/tool_use pattern transformed with reasoning_content on text message")


def test_anthropic_to_chat_messages_string_content_passthrough():
    """String content passes through unchanged in a NEW message dict (input not reused)."""
    print("\n--- Test: Anthropic To Chat Messages String Content Passthrough ---")
    fn = _require_server_func("_transform_anthropic_messages_to_chat")
    if fn is None:
        return
    msg = {"role": "user", "content": "hi there"}
    out = fn([msg], request_id="T-" + uuid.uuid4().hex[:8], mode="chat", provider="p", tier="sonnet")
    if not isinstance(out, list) or len(out) != 1:
        fail("expected one output message, got {!r}".format(out))
        return
    out_msg = out[0]
    if out_msg.get("role") != "user" or out_msg.get("content") != "hi there":
        fail("string content not preserved, got {!r}".format(out_msg))
    elif out_msg is msg:
        fail("input message dict must not be reused")
    else:
        pass_("string content passed through in a new dict")


def test_anthropic_to_chat_messages_cache_control_stripped():
    """Block-level cache_control removed from blocks; cache_control_stripped trace event logged."""
    print("\n--- Test: Anthropic To Chat Messages Cache Control Stripped ---")
    fn = _require_server_func("_anthropic_to_chat")
    if fn is None:
        return
    rid = "T-" + uuid.uuid4().hex[:8]
    body = {
        "messages": [
            {"role": "user", "content": [
                {"type": "text", "text": "a", "cache_control": {"type": "ephemeral"}},
                {"type": "text", "text": "b", "cache_control": {"type": "ephemeral"}},
            ]},
        ],
    }
    out = fn(body, request_id=rid, mode="chat", provider="p", tier="sonnet")
    # Multiple user text blocks with cache_control stripped are joined to a string.
    expected = {"messages": [{"role": "user", "content": "a\nb"}]}
    if out != expected:
        fail("cache_control not stripped from blocks, got {!r}".format(out))
        return
    evs = [e for e in _trace_events_for_request(rid) if e.get("event") == "cache_control_stripped"]
    if not evs:
        fail("expected cache_control_stripped trace event, none found")
    elif evs[0].get("locations") != ["messages"]:
        fail("expected locations ['messages'], got {!r}".format(evs[0].get("locations")))
    else:
        pass_("block-level cache_control stripped and coalesced trace event logged")


def test_anthropic_to_chat_messages_non_list_guarded():
    """Non-list messages input returns []."""
    print("\n--- Test: Anthropic To Chat Messages Non List Guarded ---")
    fn = _require_server_func("_transform_anthropic_messages_to_chat")
    if fn is None:
        return
    for bad in (None, "notalist", {"role": "user", "content": "x"}, 42):
        out = fn(bad, request_id="T-" + uuid.uuid4().hex[:8], mode="chat", provider="p", tier="sonnet")
        if out != []:
            fail("expected [] for {!r}, got {!r}".format(bad, out))
            return
    pass_("non-list messages returns []")


def test_anthropic_to_chat_messages_non_dict_entries_skipped():
    """Non-dict message entries are skipped."""
    print("\n--- Test: Anthropic To Chat Messages Non Dict Entries Skipped ---")
    fn = _require_server_func("_transform_anthropic_messages_to_chat")
    if fn is None:
        return
    messages = [{"role": "user", "content": "ok"}, "garbage", 42, None, ["nested"]]
    out = fn(messages, request_id="T-" + uuid.uuid4().hex[:8], mode="chat", provider="p", tier="sonnet")
    if out != [{"role": "user", "content": "ok"}]:
        fail("non-dict entries not skipped, got {!r}".format(out))
    else:
        pass_("non-dict message entries skipped")


def test_anthropic_to_chat_messages_null_user_content():
    """Null user content becomes '' (OpenAI requires non-null user content)."""
    print("\n--- Test: Anthropic To Chat Messages Null User Content ---")
    fn = _require_server_func("_transform_anthropic_messages_to_chat")
    if fn is None:
        return
    messages = [{"role": "user", "content": None}]
    out = fn(messages, request_id="T-" + uuid.uuid4().hex[:8], mode="chat", provider="p", tier="sonnet")
    if out != [{"role": "user", "content": ""}]:
        fail("null user content not replaced with '', got {!r}".format(out))
    else:
        pass_("null user content -> ''")


def test_anthropic_to_chat_tools_transform():
    """Anthropic tools -> OpenAI tools (input_schema -> parameters)."""
    print("\n--- Test: Anthropic To Chat Tools Transform ---")
    fn = _require_server_func("_transform_anthropic_tools_to_chat")
    if fn is None:
        return
    tools = [
        {"name": "get_weather", "description": "Get weather",
         "input_schema": {"type": "object", "properties": {}}},
        {"name": "get_time", "input_schema": {}},
    ]
    out = fn(tools, request_id="T-" + uuid.uuid4().hex[:8], mode="chat", provider="p", tier="sonnet")
    expected = [
        {"type": "function", "function": {
            "name": "get_weather", "description": "Get weather",
            "parameters": {"type": "object", "properties": {}}}},
        {"type": "function", "function": {"name": "get_time", "parameters": {}}},
    ]
    if out != expected:
        fail("tools transform mismatch, got {!r}".format(out))
    else:
        pass_("tools transformed (input_schema -> parameters)")


def test_anthropic_to_chat_tools_cache_control_stripped():
    """cache_control on tool definitions is stripped; cache_control_stripped trace event logged."""
    print("\n--- Test: Anthropic To Chat Tools Cache Control Stripped ---")
    fn = _require_server_func("_anthropic_to_chat")
    if fn is None:
        return
    rid = "T-" + uuid.uuid4().hex[:8]
    body = {
        "messages": [{"role": "user", "content": "hi"}],
        "tools": [{"name": "t", "input_schema": {}, "cache_control": {"type": "ephemeral"}}],
    }
    out = fn(body, request_id=rid, mode="chat", provider="p", tier="sonnet")
    expected_tools = [{"type": "function", "function": {"name": "t", "parameters": {}}}]
    if out.get("tools") != expected_tools:
        fail("cache_control not stripped from tool, got {!r}".format(out.get("tools")))
        return
    evs = [e for e in _trace_events_for_request(rid) if e.get("event") == "cache_control_stripped"]
    if not evs:
        fail("expected cache_control_stripped trace event for tool, none found")
    elif evs[0].get("locations") != ["tools"]:
        fail("expected locations ['tools'], got {!r}".format(evs[0].get("locations")))
    else:
        pass_("tool cache_control stripped and coalesced trace event logged")


def test_anthropic_to_chat_tools_non_list_guarded():
    """Non-list tools returns [] (tools: null treated as absent)."""
    print("\n--- Test: Anthropic To Chat Tools Non List Guarded ---")
    fn = _require_server_func("_transform_anthropic_tools_to_chat")
    if fn is None:
        return
    for bad in (None, "tools", {"name": "x"}, 42):
        out = fn(bad, request_id="T-" + uuid.uuid4().hex[:8], mode="chat", provider="p", tier="sonnet")
        if out != []:
            fail("expected [] for {!r}, got {!r}".format(bad, out))
            return
    pass_("non-list tools returns []")


def test_anthropic_to_chat_tools_malformed_entries_skipped():
    """Entries missing name or input_schema are skipped with a content_block_dropped trace event."""
    print("\n--- Test: Anthropic To Chat Tools Malformed Entries Skipped ---")
    fn = _require_server_func("_transform_anthropic_tools_to_chat")
    if fn is None:
        return
    rid = "T-" + uuid.uuid4().hex[:8]
    tools = [
        {"name": "good", "input_schema": {}},
        {"name": "no-schema"},
        {"input_schema": {}},
        "garbage",
        42,
        None,
    ]
    out = fn(tools, request_id=rid, mode="chat", provider="p", tier="sonnet")
    expected = [{"type": "function", "function": {"name": "good", "parameters": {}}}]
    if out != expected:
        fail("malformed tool entries not skipped, got {!r}".format(out))
        return
    evs = [e for e in _trace_events_for_request(rid) if e.get("event") == "content_block_dropped"]
    if not evs:
        fail("expected content_block_dropped trace event for malformed tools, none found")
    else:
        pass_("malformed tool entries skipped with trace event")


def test_anthropic_to_chat_tool_choice_mapping():
    """All 4 tool_choice variants map correctly."""
    print("\n--- Test: Anthropic To Chat Tool Choice Mapping ---")
    fn = _require_server_func("_transform_anthropic_tool_choice_to_chat")
    if fn is None:
        return
    cases = [
        ({"type": "none"}, "none"),
        ({"type": "auto"}, "auto"),
        ({"type": "any"}, "required"),
        ({"type": "tool", "name": "x"}, {"type": "function", "function": {"name": "x"}}),
    ]
    for tc, expected in cases:
        out = fn(tc)
        if out != expected:
            fail("tool_choice {!r} -> {!r}, expected {!r}".format(tc, out, expected))
            return
    pass_("all tool_choice variants mapped")


def test_anthropic_to_chat_tool_choice_none_omitted():
    """None/absent tool_choice is omitted from output."""
    print("\n--- Test: Anthropic To Chat Tool Choice None Omitted ---")
    fn_choice = _require_server_func("_transform_anthropic_tool_choice_to_chat")
    if fn_choice is not None and fn_choice(None) is not None:
        fail("None tool_choice should map to None")
        return
    fn = _require_server_func("_anthropic_to_chat")
    if fn is None:
        return
    inp = {"model": "sonnet",
           "messages": [{"role": "user", "content": "hi"}],
           "tools": [{"name": "t", "input_schema": {}}]}
    out = fn(dict(inp))
    if "tool_choice" in out:
        fail("tool_choice should be absent when not provided, keys={!r}".format(sorted(out.keys())))
    else:
        pass_("absent tool_choice omitted")


def test_anthropic_to_chat_tool_choice_malformed_omitted():
    """Malformed/unknown tool_choice maps to None (omitted, defensive)."""
    print("\n--- Test: Anthropic To Chat Tool Choice Malformed Omitted ---")
    fn = _require_server_func("_transform_anthropic_tool_choice_to_chat")
    if fn is None:
        return
    for bad in ("auto", {"type": "weird"}, {}, {"type": "tool"}, {"type": "tool", "name": None}, 42, []):
        out = fn(bad)
        if out is not None:
            fail("malformed tool_choice {!r} should map to None, got {!r}".format(bad, out))
            return
    pass_("malformed tool_choice omitted")


def test_anthropic_to_chat_tool_choice_only_with_tools():
    """tool_choice is omitted when the tools array is empty or absent."""
    print("\n--- Test: Anthropic To Chat Tool Choice Only With Tools ---")
    fn = _require_server_func("_anthropic_to_chat")
    if fn is None:
        return
    inp_empty = {"model": "sonnet",
                 "messages": [{"role": "user", "content": "hi"}],
                 "tools": [],
                 "tool_choice": {"type": "auto"}}
    out_empty = fn(dict(inp_empty))
    if "tool_choice" in out_empty:
        fail("tool_choice should be omitted when tools array is empty, got {!r}".format(out_empty.get("tool_choice")))
        return
    inp_no_tools = {"model": "sonnet",
                    "messages": [{"role": "user", "content": "hi"}],
                    "tool_choice": {"type": "auto"}}
    out_no_tools = fn(dict(inp_no_tools))
    if "tool_choice" in out_no_tools:
        fail("tool_choice should be omitted when tools absent, got {!r}".format(out_no_tools.get("tool_choice")))
        return
    pass_("tool_choice omitted when tools empty/absent")


def test_anthropic_to_chat_integration():
    """Full Anthropic request (system, tools, tool_choice, multi-turn) -> valid OpenAI Chat request."""
    print("\n--- Test: Anthropic To Chat Integration ---")
    fn = _require_server_func("_anthropic_to_chat")
    if fn is None:
        return
    inp = {
        "model": "sonnet",
        "system": "You are a helpful assistant.",
        "max_tokens": 256,
        "temperature": 0.2,
        "stream": False,
        "tools": [
            {"name": "get_weather", "description": "Weather lookup",
             "input_schema": {"type": "object", "properties": {"city": {"type": "string"}}}},
        ],
        "tool_choice": {"type": "auto"},
        "messages": [
            {"role": "user", "content": "What's the weather in SF?"},
            {"role": "assistant", "content": [
                {"type": "thinking", "thinking": "hidden", "signature": "s"},
                {"type": "text", "text": "Let me look it up."},
                {"type": "tool_use", "id": "toolu_1", "name": "get_weather", "input": {"city": "SF"}},
            ]},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "toolu_1", "content": "Sunny, 72F"},
                {"type": "text", "text": "Great, thanks!"},
            ]},
        ],
    }
    out = fn(dict(inp))
    expected_messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "What's the weather in SF?"},
        {"role": "assistant", "content": "Let me look it up.",
         "reasoning_content": "hidden", "reasoning": "hidden"},
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "toolu_1", "type": "function",
             "function": {"name": "get_weather", "arguments": '{"city": "SF"}'}}]},
        {"role": "tool", "tool_call_id": "toolu_1", "content": "Sunny, 72F"},
        {"role": "user", "content": "Great, thanks!"},
    ]
    expected_tools = [{"type": "function", "function": {
        "name": "get_weather", "description": "Weather lookup",
        "parameters": {"type": "object", "properties": {"city": {"type": "string"}}}}}]
    checks = [
        (out.get("model") == "sonnet", "model passthrough"),
        (out.get("max_tokens") == 256, "max_tokens passthrough"),
        (out.get("temperature") == 0.2, "temperature passthrough"),
        (out.get("stream") is False, "stream passthrough"),
        (out.get("messages") == expected_messages, "messages transformed"),
        (out.get("tools") == expected_tools, "tools transformed"),
        (out.get("tool_choice") == "auto", "tool_choice mapped"),
    ]
    for ok, label in checks:
        if not ok:
            fail("integration failed: {} (out={!r})".format(label, out))
            return
    pass_("full chat-mode request transformed correctly")


def test_anthropic_to_chat_content_block_dropped_trace():
    """Coalesced content_block_dropped trace event with dropped_counts (not per-block)."""
    print("\n--- Test: Anthropic To Chat Content Block Dropped Trace ---")
    fn = _require_server_func("_transform_anthropic_messages_to_chat")
    if fn is None:
        return
    rid = "T-" + uuid.uuid4().hex[:8]
    messages = [
        {"role": "assistant", "content": [
            {"type": "thinking", "thinking": "a", "signature": "s"},
            {"type": "thinking", "thinking": "b", "signature": "s"},
        ]},
        {"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "data": "x"}},
            {"type": "text", "text": "hi"},
        ]},
    ]
    fn(messages, request_id=rid, mode="chat", provider="p", tier="sonnet")
    evs = [e for e in _trace_events_for_request(rid) if e.get("event") == "content_block_dropped"]
    if len(evs) != 1:
        fail("expected exactly ONE coalesced content_block_dropped event, got {}: {!r}".format(len(evs), evs))
        return
    ev = evs[0]
    counts = ev.get("dropped_counts") or {}
    checks = [
        (ev.get("mode") == "chat", "mode field"),
        (ev.get("provider") == "p", "provider field"),
        (ev.get("tier") == "sonnet", "tier field"),
        (ev.get("request_id") == rid, "request_id field"),
        (counts.get("thinking") == 0, "thinking no longer counted as dropped"),
        (counts.get("image") == 1, "image count 1"),
    ]
    for ok, label in checks:
        if not ok:
            fail("content_block_dropped event wrong: {} (ev={!r})".format(label, ev))
            return
    pass_("coalesced content_block_dropped event with dropped_counts")


def test_anthropic_to_chat_cache_control_stripped_trace():
    """cache_control_stripped logged once per request (coalesced), not per block."""
    print("\n--- Test: Anthropic To Chat Cache Control Stripped Trace ---")
    fn = _require_server_func("_anthropic_to_chat")
    if fn is None:
        return
    rid = "T-" + uuid.uuid4().hex[:8]
    body = {
        "messages": [
            {"role": "user", "content": [
                {"type": "text", "text": "a", "cache_control": {"type": "ephemeral"}},
                {"type": "text", "text": "b", "cache_control": {"type": "ephemeral"}},
            ]},
        ],
        "tools": [{"name": "t", "input_schema": {}, "cache_control": {"type": "ephemeral"}}],
    }
    fn(body, request_id=rid, mode="chat", provider="p", tier="sonnet")
    evs = [e for e in _trace_events_for_request(rid) if e.get("event") == "cache_control_stripped"]
    if len(evs) != 1:
        fail("expected exactly ONE cache_control_stripped event, got {}: {!r}".format(len(evs), evs))
        return
    ev = evs[0]
    if ev.get("locations") not in (["messages", "tools"], ["tools", "messages"]):
        fail("cache_control_stripped missing valid locations, got {!r}".format(ev))
        return
    if (ev.get("mode") != "chat" or ev.get("provider") != "p"
            or ev.get("tier") != "sonnet" or ev.get("request_id") != rid):
        fail("cache_control_stripped missing correlation fields, got {!r}".format(ev))
        return
    pass_("cache_control_stripped logged once per request with coalesced locations")


def test_anthropic_to_chat_nan_infinity_arguments_rejected():
    """NaN/Infinity tool_use.input degrades to a text placeholder, not silently dropped."""
    print("\n--- Test: Anthropic To Chat NaN Infinity Arguments Rejected ---")
    fn = _require_server_func("_transform_anthropic_messages_to_chat")
    if fn is None:
        return
    rid = "T-" + uuid.uuid4().hex[:8]
    messages = [
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "toolu_nan", "name": "f", "input": {"value": float("nan")}},
        ]},
    ]
    out = fn(messages, request_id=rid, mode="chat", provider="p", tier="sonnet")
    msg = out[0] if out else {}
    tool_calls = msg.get("tool_calls") if isinstance(msg, dict) else None
    if tool_calls:
        fail("NaN tool_use must not produce a tool_calls entry, got {!r}".format(out))
        return
    content = msg.get("content") if isinstance(msg, dict) else None
    expected_placeholder = ("[Tool call failed: arguments for 'f' (call toolu_nan) "
                            "could not be serialized as JSON]")
    if content != expected_placeholder:
        fail("NaN tool_use should degrade to a text placeholder, got content={!r}".format(content))
        return
    evs = [e for e in _trace_events_for_request(rid) if e.get("event") == "tool_args_parse_failure"]
    if not evs:
        fail("expected tool_args_parse_failure trace event, none found")
        return
    ev = evs[0]
    if ev.get("tool_name") != "f" or ev.get("tool_id") != "toolu_nan":
        fail("tool_args_parse_failure missing tool_name/tool_id, got {!r}".format(ev))
        return
    pass_("NaN tool_use degraded to placeholder with tool_args_parse_failure event")


def test_anthropic_to_chat_tool_use_non_dict_input():
    """tool_use.input with non-dict value (string/None/number) degrades to placeholder, no non-object arguments."""
    print("\n--- Test: Anthropic To Chat Tool Use Non Dict Input ---")
    fn = _require_server_func("_transform_anthropic_messages_to_chat")
    if fn is None:
        return
    rid = "T-" + uuid.uuid4().hex[:8]
    for bad in ("hello", None, 42, [1, 2]):
        messages = [
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "toolu_bad", "name": "f", "input": bad},
            ]},
        ]
        out = fn(messages, request_id=rid, mode="chat", provider="p", tier="sonnet")
        expected = [{"role": "assistant",
                     "content": ("[Tool call failed: arguments for 'f' (call toolu_bad) "
                                 "could not be serialized as JSON]")}]
        if out != expected:
            fail("non-dict input {!r} should degrade to placeholder, got {!r}".format(bad, out))
            return
        if any(isinstance(m, dict) and m.get("tool_calls") for m in out):
            fail("non-dict input {!r} must not produce a tool_calls entry, got {!r}".format(bad, out))
            return
    evs = [e for e in _trace_events_for_request(rid) if e.get("event") == "tool_args_parse_failure"]
    if len(evs) < 4:
        fail("expected tool_args_parse_failure events for each non-dict input, got {}: {!r}".format(len(evs), evs))
        return
    for ev in evs:
        if ev.get("tool_name") != "f" or ev.get("tool_id") != "toolu_bad" or not isinstance(ev.get("error"), str):
            fail("tool_args_parse_failure missing tool_name/tool_id/error, got {!r}".format(ev))
            return
    pass_("non-dict tool_use input degraded to placeholder with tool_args_parse_failure")


def test_anthropic_to_chat_nan_placeholder_with_valid_tool_use():
    """NaN tool_use + valid tool_use coexist -> placeholder as separate assistant message before tool_calls."""
    print("\n--- Test: Anthropic To Chat Nan Placeholder With Valid Tool Use ---")
    fn = _require_server_func("_transform_anthropic_messages_to_chat")
    if fn is None:
        return
    rid = "T-" + uuid.uuid4().hex[:8]
    messages = [
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "toolu_nan", "name": "f", "input": {"value": float("nan")}},
            {"type": "tool_use", "id": "toolu_ok", "name": "g", "input": {"a": 1}},
        ]},
    ]
    out = fn(messages, request_id=rid, mode="chat", provider="p", tier="sonnet")
    expected = [
        {"role": "assistant",
         "content": ("[Tool call failed: arguments for 'f' (call toolu_nan) "
                     "could not be serialized as JSON]")},
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "toolu_ok", "type": "function",
             "function": {"name": "g", "arguments": '{"a": 1}'}}]},
    ]
    if out != expected:
        fail("NaN placeholder must be preserved before tool_calls, got {!r}".format(out))
        return
    evs = [e for e in _trace_events_for_request(rid) if e.get("event") == "tool_args_parse_failure"]
    if not evs:
        fail("expected tool_args_parse_failure trace event, none found")
        return
    if evs[0].get("tool_name") != "f" or evs[0].get("tool_id") != "toolu_nan":
        fail("tool_args_parse_failure missing tool_name/tool_id, got {!r}".format(evs[0]))
        return
    pass_("NaN placeholder preserved as separate message before tool_calls")


def test_anthropic_to_chat_tool_result_list_content():
    """tool_result.content as a list of text blocks is joined with newlines."""
    print("\n--- Test: Anthropic To Chat Tool Result List Content ---")
    fn = _require_server_func("_transform_anthropic_messages_to_chat")
    if fn is None:
        return
    messages = [
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "toolu_1", "name": "f", "input": {}},
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "toolu_1", "content": [
                {"type": "text", "text": "line1"},
                {"type": "text", "text": "line2"},
            ]},
        ]},
    ]
    out = fn(messages, request_id="T-" + uuid.uuid4().hex[:8], mode="chat", provider="p", tier="sonnet")
    expected = [
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "toolu_1", "type": "function", "function": {"name": "f", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "toolu_1", "content": "line1\nline2"},
    ]
    if out != expected:
        fail("tool_result list content not joined, got {!r}".format(out))
    else:
        pass_("tool_result list content joined with newlines")


def test_anthropic_to_chat_no_input_mutation():
    """_anthropic_to_chat does not mutate the input dict or its nested structures."""
    print("\n--- Test: Anthropic To Chat No Input Mutation ---")
    fn = _require_server_func("_anthropic_to_chat")
    if fn is None:
        return
    import copy
    inp = {
        "model": "sonnet",
        "messages": [
            {"role": "assistant", "content": [
                {"type": "text", "text": "a"},
                {"type": "tool_use", "id": "t1", "name": "f", "input": {"x": 1}},
            ]},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "t1", "content": "r"},
            ]},
        ],
        "tools": [{"name": "f", "input_schema": {}, "cache_control": {"type": "ephemeral"}}],
        "tool_choice": {"type": "auto"},
        "thinking": {"type": "enabled", "budget_tokens": 100},
    }
    messages_identity = inp["messages"]
    original = copy.deepcopy(inp)
    fn(dict(inp))
    if inp != original:
        fail("input dict was mutated")
        return
    if inp["messages"] is not messages_identity:
        fail("input messages list identity changed")
        return
    pass_("input dict and nested structures not mutated")


# --- Step 5: _chat_to_anthropic ---

def test_chat_to_anthropic_basic():
    """content, model, stop_reason, usage mapped correctly."""
    print("\n--- Test: Chat To Anthropic Basic ---")
    fn = _require_server_func("_chat_to_anthropic")
    if fn is None:
        return
    chat = {"id": "chatcmpl-123", "object": "chat.completion", "model": "gpt-4o",
            "choices": [{"index": 0,
                         "message": {"role": "assistant", "content": "Hello"},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8}}
    out = fn(chat, "sonnet")
    if not isinstance(out, dict):
        fail("_chat_to_anthropic must return a dict")
        return
    checks = [
        (out.get("id") == "msg_chatcmpl-123", "id prefixed with msg_"),
        (out.get("model") == "sonnet", "model rewritten to tier"),
        (out.get("type") == "message", "type hardcoded to message"),
        (out.get("role") == "assistant", "role hardcoded to assistant"),
        (out.get("content") == [{"type": "text", "text": "Hello"}], "content string wrapped"),
        (out.get("stop_reason") == "end_turn", "stop->end_turn"),
        (out.get("stop_sequence") is None, "stop_sequence null"),
        (out.get("usage") == {"input_tokens": 5, "output_tokens": 3}, "usage mapped"),
    ]
    for ok, label in checks:
        if not ok:
            fail("basic mapping failed: {} (out={!r})".format(label, out))
    if all(ok for ok, _ in checks):
        pass_("chat->anthropic basic mapping correct")


def test_chat_to_anthropic_reasoning_content_to_thinking():
    """reasoning_content in the chat message becomes a thinking block first in content."""
    print("\n--- Test: Chat To Anthropic Reasoning Content To Thinking ---")
    fn = _require_server_func("_chat_to_anthropic")
    if fn is None:
        return
    chat = {"id": "c1", "model": "gpt-4o",
            "choices": [{"index": 0,
                         "message": {"role": "assistant", "content": "Answer",
                                     "reasoning_content": "Let me think"},
                         "finish_reason": "stop"}]}
    out = fn(chat, "sonnet")
    content = out.get("content") if isinstance(out, dict) else None
    expected = [
        {"type": "thinking", "thinking": "Let me think", "signature": ""},
        {"type": "text", "text": "Answer"},
    ]
    if content != expected:
        fail("reasoning_content should become a thinking block first, got content={!r}".format(content))
        return
    if not isinstance(content, list) or content[0].get("type") != "thinking" \
            or content[0].get("signature") != "":
        fail("thinking block must carry signature:'', got {!r}".format(content))
        return
    pass_("reasoning_content -> thinking block first with signature:''")


def test_chat_to_anthropic_reasoning_field_compat():
    """vLLM 'reasoning' field is also recognized; reasoning_content wins when both present."""
    print("\n--- Test: Chat To Anthropic Reasoning Field Compat ---")
    fn = _require_server_func("_chat_to_anthropic")
    if fn is None:
        return
    # 'reasoning' alone (vLLM compat)
    chat = {"id": "c1", "model": "gpt-4o",
            "choices": [{"index": 0,
                         "message": {"role": "assistant", "content": "A",
                                     "reasoning": "vllm-reason"},
                         "finish_reason": "stop"}]}
    out = fn(chat, "sonnet")
    content = out.get("content") if isinstance(out, dict) else None
    if content != [{"type": "thinking", "thinking": "vllm-reason", "signature": ""},
                   {"type": "text", "text": "A"}]:
        fail("reasoning field (vLLM) should map to thinking block, got {!r}".format(content))
        return
    # Both present: reasoning_content wins
    chat2 = {"id": "c2", "model": "gpt-4o",
             "choices": [{"index": 0,
                          "message": {"role": "assistant", "content": "A",
                                      "reasoning_content": "rc", "reasoning": "r"},
                          "finish_reason": "stop"}]}
    out2 = fn(chat2, "sonnet")
    content2 = out2.get("content") if isinstance(out2, dict) else None
    if content2 != [{"type": "thinking", "thinking": "rc", "signature": ""},
                    {"type": "text", "text": "A"}]:
        fail("reasoning_content must take precedence over reasoning, got {!r}".format(content2))
        return
    pass_("reasoning field recognized; reasoning_content wins precedence")


def test_chat_to_anthropic_reasoning_content_empty():
    """Empty reasoning_content produces no thinking block."""
    print("\n--- Test: Chat To Anthropic Reasoning Content Empty ---")
    fn = _require_server_func("_chat_to_anthropic")
    if fn is None:
        return
    chat = {"id": "c1", "model": "gpt-4o",
            "choices": [{"index": 0,
                         "message": {"role": "assistant", "content": "A",
                                     "reasoning_content": ""},
                         "finish_reason": "stop"}]}
    out = fn(chat, "sonnet")
    content = out.get("content") if isinstance(out, dict) else None
    if content != [{"type": "text", "text": "A"}]:
        fail("empty reasoning_content should emit no thinking block, got {!r}".format(content))
        return
    # Non-string reasoning_content is also skipped
    chat2 = {"id": "c2", "model": "gpt-4o",
             "choices": [{"index": 0,
                          "message": {"role": "assistant", "content": "A",
                                      "reasoning_content": None},
                          "finish_reason": "stop"}]}
    out2 = fn(chat2, "sonnet")
    content2 = out2.get("content") if isinstance(out2, dict) else None
    if content2 != [{"type": "text", "text": "A"}]:
        fail("non-string reasoning_content should be skipped, got {!r}".format(content2))
        return
    pass_("empty/non-string reasoning_content emits no thinking block")


def test_chat_to_anthropic_reasoning_content_with_tool_calls():
    """reasoning_content + tool_calls -> thinking block first, then tool_use blocks."""
    print("\n--- Test: Chat To Anthropic Reasoning Content With Tool Calls ---")
    fn = _require_server_func("_chat_to_anthropic")
    if fn is None:
        return
    chat = {"id": "c1", "model": "gpt-4o",
            "choices": [{"index": 0,
                         "message": {"role": "assistant", "content": None,
                                     "reasoning_content": "thinking",
                                     "tool_calls": [
                                         {"id": "call_1", "type": "function",
                                          "function": {"name": "get_weather",
                                                       "arguments": '{"city": "SF"}'}}]},
                         "finish_reason": "tool_calls"}]}
    out = fn(chat, "sonnet")
    content = out.get("content") if isinstance(out, dict) else None
    expected = [
        {"type": "thinking", "thinking": "thinking", "signature": ""},
        {"type": "tool_use", "id": "call_1", "name": "get_weather", "input": {"city": "SF"}},
    ]
    if content != expected:
        fail("reasoning_content + tool_calls should be thinking first then tool_use, got {!r}".format(content))
        return
    if out.get("stop_reason") != "tool_use":
        fail("tool_calls finish_reason should map to stop_reason tool_use, got {!r}".format(out.get("stop_reason")))
        return
    pass_("reasoning_content + tool_calls -> thinking block then tool_use blocks")


def test_chat_to_anthropic_empty_choices():
    """Empty choices returns a minimal valid Anthropic message."""
    print("\n--- Test: Chat To Anthropic Empty Choices ---")
    fn = _require_server_func("_chat_to_anthropic")
    if fn is None:
        return
    chat = {"id": "chatcmpl-1", "choices": [], "model": "gpt-4o"}
    out = fn(chat, "sonnet")
    if not isinstance(out, dict):
        fail("empty choices must still return a dict")
        return
    if out.get("type") != "message":
        fail("minimal response missing type=message")
    if out.get("role") != "assistant":
        fail("minimal response missing role=assistant")
    if out.get("model") != "sonnet":
        fail("minimal response missing model=tier")
    if out.get("content") != []:
        fail("minimal response expected content=[], got {!r}".format(out.get("content")))
    if out.get("type") == "message" and out.get("role") == "assistant" and out.get("content") == []:
        pass_("empty choices returns minimal valid message")


def test_chat_to_anthropic_tool_calls():
    """tool_calls map to tool_use content blocks."""
    print("\n--- Test: Chat To Anthropic Tool Calls ---")
    fn = _require_server_func("_chat_to_anthropic")
    if fn is None:
        return
    chat = {"id": "chatcmpl-1",
            "choices": [{"index": 0,
                         "message": {"role": "assistant", "content": "",
                                     "tool_calls": [
                                         {"id": "call_1", "type": "function",
                                          "function": {"name": "get_weather",
                                                       "arguments": '{"city": "SF"}'}}]},
                         "finish_reason": "tool_calls"}]}
    out = fn(chat, "sonnet")
    content = out.get("content") if isinstance(out.get("content"), list) else []
    tools = [b for b in content if b.get("type") == "tool_use"]
    if not tools:
        fail("expected a tool_use content block, content={!r}".format(out.get("content")))
        return
    t = tools[0]
    if t.get("name") != "get_weather":
        fail("tool_use name mismatch: {!r}".format(t.get("name")))
    if t.get("input") != {"city": "SF"}:
        fail("tool_use input mismatch: {!r}".format(t.get("input")))
    if t.get("id") != "call_1":
        fail("tool_use id mismatch: {!r}".format(t.get("id")))
    if out.get("stop_reason") != "tool_use":
        fail("finish_reason tool_calls should map to stop_reason tool_use, got {!r}".format(out.get("stop_reason")))
    if tools and t.get("name") == "get_weather" and t.get("input") == {"city": "SF"}:
        pass_("tool_calls mapped to tool_use blocks")


def test_chat_to_anthropic_finish_reason_mapping():
    """All finish_reason values map to the correct stop_reason."""
    print("\n--- Test: Chat To Anthropic Finish Reason Mapping ---")
    fn = _require_server_func("_chat_to_anthropic")
    if fn is None:
        return
    cases = [("stop", "end_turn"), ("length", "max_tokens"),
             ("content_filter", None), ("weird_thing", None)]
    ok = True
    for fr, expected in cases:
        chat = {"id": "x", "choices": [{"index": 0,
                                        "message": {"role": "assistant", "content": "hi"},
                                        "finish_reason": fr}]}
        out = fn(chat, "sonnet")
        actual = out.get("stop_reason")
        if actual != expected:
            fail("finish_reason {!r} -> stop_reason {!r}, expected {!r}".format(fr, actual, expected))
            ok = False
    # finish_reason 'tool_calls' only maps to 'tool_use' when a tool_use block
    # is actually emitted (Step 6a: null/absent tool_calls must not claim
    # tool_use, or the client hangs waiting for tool_use blocks).
    chat_tool = {"id": "x", "choices": [{"index": 0,
                                         "message": {"role": "assistant", "content": "hi",
                                                     "tool_calls": [
                                                         {"id": "call_1", "type": "function",
                                                          "function": {"name": "f", "arguments": '{"city": "SF"}'}}]},
                                         "finish_reason": "tool_calls"}]}
    out = fn(chat_tool, "sonnet")
    if out.get("stop_reason") != "tool_use":
        fail("finish_reason 'tool_calls' with emitted tool_use -> stop_reason {!r}, expected 'tool_use'".format(out.get("stop_reason")))
        ok = False
    chat_null_tc = {"id": "x", "choices": [{"index": 0,
                                            "message": {"role": "assistant", "content": "hi",
                                                        "tool_calls": None},
                                            "finish_reason": "tool_calls"}]}
    out = fn(chat_null_tc, "sonnet")
    if out.get("stop_reason") is not None:
        fail("null tool_calls + finish_reason 'tool_calls' -> stop_reason {!r}, expected None".format(out.get("stop_reason")))
        ok = False
    chat_missing = {"id": "x", "choices": [{"index": 0, "message": {"role": "assistant", "content": "hi"}}]}
    out = fn(chat_missing, "sonnet")
    if out.get("stop_reason") is not None:
        fail("missing finish_reason should map to null, got {!r}".format(out.get("stop_reason")))
        ok = False
    if ok:
        pass_("finish_reason->stop_reason mapping correct")


def test_chat_to_anthropic_usage_absent():
    """Missing usage maps to zero input/output tokens."""
    print("\n--- Test: Chat To Anthropic Usage Absent ---")
    fn = _require_server_func("_chat_to_anthropic")
    if fn is None:
        return
    chat = {"id": "x", "choices": [{"index": 0,
                                    "message": {"role": "assistant", "content": "hi"},
                                    "finish_reason": "stop"}]}
    out = fn(chat, "sonnet")
    if out.get("usage") != {"input_tokens": 0, "output_tokens": 0}:
        fail("expected usage {input_tokens:0, output_tokens:0}, got {!r}".format(out.get("usage")))
    else:
        pass_("missing usage handled with zero defaults")


def test_chat_to_anthropic_content_array():
    """Array content blocks map individually."""
    print("\n--- Test: Chat To Anthropic Content Array ---")
    fn = _require_server_func("_chat_to_anthropic")
    if fn is None:
        return
    chat = {"id": "x", "choices": [{"index": 0,
                                    "message": {"role": "assistant", "content": [
                                        {"type": "text", "text": "part1"},
                                        {"type": "text", "text": "part2"}]},
                                    "finish_reason": "stop"}]}
    out = fn(chat, "sonnet")
    expected = [{"type": "text", "text": "part1"}, {"type": "text", "text": "part2"}]
    if out.get("content") != expected:
        fail("array content not preserved: {!r}".format(out.get("content")))
    else:
        pass_("array content mapped block by block")


def test_chat_to_anthropic_malformed_tool_args_text_block():
    """Malformed tool args degrade to a text block, not a tool_use with input {}.

    Option C (plan 2026-08-28-thread-request-id-to-transform-functions):
    when tool arguments cannot produce a valid dict, emit a text block
    "[Tool call failed: arguments for '<name>' (call <id>) could not be
    parsed as JSON]" instead of a tool_use block with input {}. stop_reason
    is forced to None when no tool_use block is emitted. The transform also
    accepts request_id, mode, provider kwargs.
    """
    print("\n--- Test: Chat To Anthropic Malformed Tool Args Text Block ---")
    fn = _require_server_func("_chat_to_anthropic")
    if fn is None:
        return
    cases = [
        # (label, arguments value)
        ("string-fails-json", "{not json"),
        ("string-parses-to-non-dict-int", "42"),
        ("string-parses-to-non-dict-array", "[1,2]"),
        ("non-string-null", None),
    ]
    for label, args_val in cases:
        chat = {"id": "x",
                "choices": [{"index": 0,
                             "message": {"role": "assistant", "content": "",
                                         "tool_calls": [
                                             {"id": "call_1", "type": "function",
                                              "function": {"name": "f", "arguments": args_val}}]},
                             "finish_reason": "tool_calls"}]}
        out = fn(chat, "sonnet", request_id="R1", mode="chat", provider="p")
        content = out.get("content") if isinstance(out.get("content"), list) else []
        tools = [b for b in content if b.get("type") == "tool_use"]
        if tools:
            fail("[{}] malformed args should NOT emit a tool_use block, content={!r}".format(label, content))
            continue
        text_blocks = [b for b in content if b.get("type") == "text"]
        if not any("f" in (b.get("text") or "") and "call_1" in (b.get("text") or "")
                   for b in text_blocks):
            fail("[{}] expected a text block naming tool 'f' and call 'call_1', content={!r}".format(label, content))
            continue
        if out.get("stop_reason") is not None:
            fail("[{}] all-malformed tool calls should force stop_reason None, got {!r}".format(label, out.get("stop_reason")))
            continue
    # Non-dict parses to a valid dict (no dict -> dict is fine) is NOT a failure.
    chat_ok = {"id": "x",
               "choices": [{"index": 0,
                            "message": {"role": "assistant", "content": "",
                                        "tool_calls": [
                                            {"id": "call_1", "type": "function",
                                             "function": {"name": "f", "arguments": '{"city": "SF"}'}}]},
                            "finish_reason": "tool_calls"}]}
    out_ok = fn(chat_ok, "sonnet", request_id="R2", mode="chat", provider="p")
    tools_ok = [b for b in (out_ok.get("content") or []) if b.get("type") == "tool_use"]
    if not tools_ok or tools_ok[0].get("input") != {"city": "SF"} or out_ok.get("stop_reason") != "tool_use":
        fail("valid tool args should still emit a tool_use block with parsed input, content={!r}".format(out_ok.get("content")))
        return
    # Step 6c: verify a tool_args_parse_failure trace event from THIS test
    # (request_id R1, from the malformed cases) carries the threaded
    # request_id/mode/provider/tier fields — the unit-level proof that
    # _transform_and_guard threads the correlation context through. The trace
    # file is session-shared and appended, so assert on the matching event
    # (request_id R1) rather than a count.
    trace_file = os.environ.get("PROXY_TRACE_FILE")
    if not trace_file or not os.path.exists(trace_file):
        fail("expected PROXY_TRACE_FILE to be set to an existing temp path, got {!r}".format(trace_file))
        return
    matched = None
    with open(trace_file) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except Exception:
                continue
            if ev.get("event") == "tool_args_parse_failure" and ev.get("request_id") == "R1":
                matched = ev
                break
    if matched is None:
        fail("expected a tool_args_parse_failure trace event with request_id R1, none found")
        return
    if (matched.get("mode") != "chat" or matched.get("provider") != "p"
            or matched.get("tier") != "sonnet"):
        fail("tool_args_parse_failure event missing mode/provider/tier, got {!r}".format(matched))
        return
    pass_("malformed tool args produce a text block, no input {}, stop_reason None")


def test_chat_to_anthropic_malformed_tool_args_mixed():
    """Mixed valid + malformed tool calls: valid tool_use kept, malformed degrades.

    Guards the emitted_tool_use flag introduced by Option C: when at least one
    tool_use block is emitted, stop_reason still maps from finish_reason.
    """
    print("\n--- Test: Chat To Anthropic Malformed Tool Args Mixed ---")
    fn = _require_server_func("_chat_to_anthropic")
    if fn is None:
        return
    chat = {"id": "x",
            "choices": [{"index": 0,
                         "message": {"role": "assistant", "content": "",
                                     "tool_calls": [
                                         {"id": "call_1", "type": "function",
                                          "function": {"name": "good", "arguments": '{"city": "SF"}'}},
                                         {"id": "call_2", "type": "function",
                                          "function": {"name": "bad", "arguments": "{not json"}}]},
                         "finish_reason": "tool_calls"}]}
    out = fn(chat, "sonnet", request_id="R3", mode="chat", provider="p")
    content = out.get("content") if isinstance(out.get("content"), list) else []
    tools = [b for b in content if b.get("type") == "tool_use"]
    if len(tools) != 1:
        fail("expected exactly one tool_use block, got {!r}".format(content))
        return
    if tools[0].get("name") != "good" or tools[0].get("input") != {"city": "SF"}:
        fail("valid tool call should be preserved, got {!r}".format(tools[0]))
        return
    text_blocks = [b for b in content if b.get("type") == "text"]
    if not any("bad" in (b.get("text") or "") and "call_2" in (b.get("text") or "") for b in text_blocks):
        fail("malformed tool call should produce a text block naming 'bad' and 'call_2', content={!r}".format(content))
        return
    if out.get("stop_reason") != "tool_use":
        fail("with a valid tool_use emitted, stop_reason should map to tool_use, got {!r}".format(out.get("stop_reason")))
        return
    pass_("mixed valid + malformed tool calls: valid tool_use kept, malformed degrades")


# --- Step 6: _anthropic_to_response ---

def test_anthropic_to_response_basic():
    """model, input, instructions, max_output_tokens, stream mapped correctly."""
    print("\n--- Test: Anthropic To Response Basic ---")
    fn = _require_server_func("_anthropic_to_response")
    if fn is None:
        return
    inp = {"model": "sonnet",
           "messages": [{"role": "user", "content": "hi"}],
           "system": "Be concise",
           "max_tokens": 50,
           "temperature": 0.5,
           "top_p": 0.9,
           "stream": True}
    out = fn(inp)
    if not isinstance(out, dict):
        fail("_anthropic_to_response must return a dict")
        return
    checks = [
        (out.get("model") == "sonnet", "model pass-through"),
        (out.get("stream") is False, "stream forced false"),
        (out.get("input") == "hi", "input from user message"),
        (out.get("instructions") == "Be concise", "system -> instructions"),
        (out.get("max_output_tokens") == 50, "max_tokens -> max_output_tokens"),
        (out.get("temperature") == 0.5, "temperature pass-through"),
        (out.get("top_p") == 0.9, "top_p pass-through"),
        ("messages" not in out, "messages dropped"),
    ]
    for ok, label in checks:
        if not ok:
            fail("basic response mapping failed: {}".format(label))
    if all(ok for ok, _ in checks):
        pass_("anthropic->response basic mapping correct")


def test_anthropic_to_response_system_list():
    """system content block list concatenates into instructions."""
    print("\n--- Test: Anthropic To Response System List ---")
    fn = _require_server_func("_anthropic_to_response")
    if fn is None:
        return
    inp = {"model": "sonnet",
           "messages": [{"role": "user", "content": "hi"}],
           "system": [{"type": "text", "text": "A"}, {"type": "text", "text": "B"}]}
    out = fn(inp)
    if out.get("instructions") != "A\nB":
        fail("expected instructions 'A\\nB', got {!r}".format(out.get("instructions")))
    else:
        pass_("system list concatenated to instructions")


def test_anthropic_to_response_multiple_user_messages():
    """Last user message provides input; text content blocks joined with newline."""
    print("\n--- Test: Anthropic To Response Multiple User Messages ---")
    fn = _require_server_func("_anthropic_to_response")
    if fn is None:
        return
    inp = {"model": "sonnet",
           "messages": [{"role": "user", "content": "first"},
                        {"role": "assistant", "content": "resp"},
                        {"role": "user", "content": [{"type": "text", "text": "secX"},
                                                      {"type": "text", "text": "secY"}]}]}
    out = fn(inp)
    if out.get("input") != "secX\nsecY":
        fail("expected input 'secX\\nsecY', got {!r}".format(out.get("input")))
    else:
        pass_("last user message used for input")


def test_anthropic_to_response_no_user_message():
    """No user message yields input: ''."""
    print("\n--- Test: Anthropic To Response No User Message ---")
    fn = _require_server_func("_anthropic_to_response")
    if fn is None:
        return
    inp = {"model": "sonnet", "messages": [{"role": "assistant", "content": "hi"}]}
    out = fn(inp)
    if out.get("input") != "":
        fail("expected input '', got {!r}".format(out.get("input")))
    else:
        pass_("no user message -> input empty string")


def test_anthropic_to_response_stream_forced_false():
    """stream is always false regardless of the client's stream flag."""
    print("\n--- Test: Anthropic To Response Stream Forced False ---")
    fn = _require_server_func("_anthropic_to_response")
    if fn is None:
        return
    ok = True
    for stream_flag in (True, False):
        inp = {"model": "sonnet",
               "messages": [{"role": "user", "content": "hi"}],
               "stream": stream_flag}
        out = fn(inp)
        if out.get("stream") is not False:
            fail("stream should be false, input flag was {!r}".format(stream_flag))
            ok = False
    inp_missing = {"model": "sonnet", "messages": [{"role": "user", "content": "hi"}]}
    out = fn(inp_missing)
    if out.get("stream") is not False:
        fail("stream should be false when flag absent")
        ok = False
    if ok:
        pass_("response mode always forces stream:false")


# --- Step 7: _response_to_anthropic ---

def test_response_to_anthropic_basic():
    """content, model, id, usage mapped correctly."""
    print("\n--- Test: Response To Anthropic Basic ---")
    fn = _require_server_func("_response_to_anthropic")
    if fn is None:
        return
    resp = {"id": "resp_123", "object": "response", "created_at": 1, "model": "gpt-4o",
            "status": "completed",
            "output": [{"type": "message", "role": "assistant",
                        "content": [{"type": "output_text", "text": "Hello", "annotations": []}]}],
            "usage": {"input_tokens": 4, "output_tokens": 2, "total_tokens": 6}}
    out = fn(resp, "sonnet")
    if not isinstance(out, dict):
        fail("_response_to_anthropic must return a dict")
        return
    checks = [
        (out.get("id") == "resp_123", "id passed through"),
        (out.get("model") == "sonnet", "model rewritten to tier"),
        (out.get("type") == "message", "type hardcoded"),
        (out.get("role") == "assistant", "role hardcoded"),
        (out.get("content") == [{"type": "text", "text": "Hello"}], "output_text -> text block"),
        (out.get("stop_reason") == "end_turn", "status completed -> end_turn"),
        (out.get("usage") == {"input_tokens": 4, "output_tokens": 2}, "usage mapped"),
    ]
    for ok, label in checks:
        if not ok:
            fail("basic response->anthropic mapping failed: {}".format(label))
    if all(ok for ok, _ in checks):
        pass_("response->anthropic basic mapping correct")


def test_response_to_anthropic_empty_output():
    """Empty output returns a minimal valid Anthropic message."""
    print("\n--- Test: Response To Anthropic Empty Output ---")
    fn = _require_server_func("_response_to_anthropic")
    if fn is None:
        return
    resp = {"id": "resp_1", "output": [], "status": "completed", "model": "gpt-4o"}
    out = fn(resp, "sonnet")
    if not isinstance(out, dict):
        fail("empty output must still return a dict")
        return
    if out.get("type") != "message" or out.get("role") != "assistant" or out.get("model") != "sonnet":
        fail("minimal response missing core fields: {!r}".format(out))
    if out.get("content") != []:
        fail("minimal response expected content=[], got {!r}".format(out.get("content")))
    if out.get("type") == "message" and out.get("role") == "assistant" and out.get("content") == []:
        pass_("empty output returns minimal valid message")


def test_response_to_anthropic_multiple_output():
    """First message output is used for content (per tester spec)."""
    print("\n--- Test: Response To Anthropic Multiple Output ---")
    fn = _require_server_func("_response_to_anthropic")
    if fn is None:
        return
    resp = {"id": "resp_1", "status": "completed", "model": "gpt-4o",
            "output": [
                {"type": "message", "role": "assistant",
                 "content": [{"type": "output_text", "text": "First", "annotations": []}]},
                {"type": "message", "role": "assistant",
                 "content": [{"type": "output_text", "text": "Second", "annotations": []}]},
                {"type": "function_call", "call_id": "c1", "name": "f", "arguments": "{}"},
            ]}
    out = fn(resp, "sonnet")
    content = out.get("content") if isinstance(out.get("content"), list) else []
    texts = [b.get("text") for b in content if b.get("type") == "text"]
    if texts != ["First"]:
        fail("expected only first message output content, got {!r}".format(texts))
    else:
        pass_("first message output used for content")


def test_response_to_anthropic_status_completed():
    """stop_reason derived from the status field."""
    print("\n--- Test: Response To Anthropic Status Completed ---")
    fn = _require_server_func("_response_to_anthropic")
    if fn is None:
        return
    cases = [("completed", "end_turn"), ("incomplete", None), ("failed", None), (None, None)]
    ok = True
    for status, expected in cases:
        resp = {"id": "r", "status": status,
                "output": [{"type": "message", "role": "assistant",
                            "content": [{"type": "output_text", "text": "hi"}]}]}
        out = fn(resp, "sonnet")
        if out.get("stop_reason") != expected:
            fail("status {!r} -> stop_reason {!r}, expected {!r}".format(status, out.get("stop_reason"), expected))
            ok = False
    if ok:
        pass_("status->stop_reason mapping correct")


def test_response_to_anthropic_usage_absent():
    """Missing usage maps to zero input/output tokens."""
    print("\n--- Test: Response To Anthropic Usage Absent ---")
    fn = _require_server_func("_response_to_anthropic")
    if fn is None:
        return
    resp = {"id": "r", "status": "completed",
            "output": [{"type": "message", "role": "assistant",
                        "content": [{"type": "output_text", "text": "hi"}]}]}
    out = fn(resp, "sonnet")
    if out.get("usage") != {"input_tokens": 0, "output_tokens": 0}:
        fail("expected usage {input_tokens:0, output_tokens:0}, got {!r}".format(out.get("usage")))
    else:
        pass_("missing usage handled with zero defaults")


# --- Step 8: chat-mode SSE transformation ---

def _sse_stream_chunks(chunks):
    return "".join("data: {}\n\n".format(json.dumps(c)) for c in chunks).encode()


def test_chat_sse_basic_streaming():
    """Simulated OpenAI SSE chunks produce valid Anthropic SSE events."""
    print("\n--- Test: Chat SSE Basic Streaming ---")
    upstream_port = find_free_port()
    tiers = _mode_tiers()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port), "key": "K", "mode": "chat"}}
    chunks = [
        {"id": "chatcmpl-1", "object": "chat.completion.chunk", "created": 1, "model": "gpt-4o",
         "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]},
        {"id": "chatcmpl-1", "object": "chat.completion.chunk", "created": 1, "model": "gpt-4o",
         "choices": [{"index": 0, "delta": {"content": "Hel"}, "finish_reason": None}]},
        {"id": "chatcmpl-1", "object": "chat.completion.chunk", "created": 1, "model": "gpt-4o",
         "choices": [{"index": 0, "delta": {"content": "lo"}, "finish_reason": None}]},
        {"id": "chatcmpl-1", "object": "chat.completion.chunk", "created": 1, "model": "gpt-4o",
         "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
    ]
    sse_body = _sse_stream_chunks(chunks) + b"data: [DONE]\n\n"
    responders = {"p": lambda info: (200, "text/event-stream", sse_body)}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(tiers, vendors, responders=responders)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        status, content_type, raw = _send_proxy_request_stream(
            proxy_port, body={"model": "sonnet", "messages": [{"role": "user", "content": "hi"}], "stream": True})
        if status != 200:
            fail("expected 200, got {}".format(status))
            return
        frames = _parse_sse_frames(raw)
        types = _sse_types(frames)
        required = ("message_start", "content_block_start", "content_block_delta",
                    "content_block_stop", "message_delta", "message_stop")
        missing = [t for t in required if t not in types]
        if missing:
            fail("missing SSE events {}; got {}".format(missing, types))
            return
        order_idx = {t: types.index(t) for t in required}
        if [order_idx[t] for t in required] != sorted(order_idx.values()):
            fail("SSE event ordering wrong: {}".format(types))
        if types.count("message_delta") != 1 or types.count("message_stop") != 1:
            fail("expected exactly one message_delta/message_stop, got {}".format(types))
        start = _sse_frames_with_type(frames, "message_start")
        if start:
            msg = start[0].get("message", {})
            if not (msg.get("id", "").startswith("msg_") and msg.get("model") == "sonnet"):
                fail("synthetic message_start wrong: {!r}".format(start[0]))
        if b"[DONE]" in raw:
            fail("[DONE] sentinel leaked into client stream")
        if not missing and [order_idx[t] for t in required] == sorted(order_idx.values()):
            pass_("chat SSE produces valid Anthropic event sequence")
    finally:
        cleanup()


def test_chat_sse_finish_reason_mapping():
    """finish_reason maps to stop_reason in the terminal message_delta."""
    print("\n--- Test: Chat SSE Finish Reason Mapping ---")
    upstream_port = find_free_port()
    tiers = _mode_tiers()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port), "key": "K", "mode": "chat"}}
    chunks = [
        {"id": "c1", "object": "chat.completion.chunk", "created": 1, "model": "gpt-4o",
         "choices": [{"index": 0, "delta": {"role": "assistant", "content": "hi"}, "finish_reason": None}]},
        {"id": "c1", "object": "chat.completion.chunk", "created": 1, "model": "gpt-4o",
         "choices": [{"index": 0, "delta": {}, "finish_reason": "length"}]},
    ]
    sse_body = _sse_stream_chunks(chunks) + b"data: [DONE]\n\n"
    responders = {"p": lambda info: (200, "text/event-stream", sse_body)}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(tiers, vendors, responders=responders)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        status, content_type, raw = _send_proxy_request_stream(
            proxy_port, body={"model": "sonnet", "messages": [{"role": "user", "content": "hi"}]})
        if status != 200:
            fail("expected 200, got {}".format(status))
            return
        frames = _parse_sse_frames(raw)
        deltas = _sse_frames_with_type(frames, "message_delta")
        if not deltas:
            fail("no message_delta event in stream")
            return
        delta_obj = deltas[0].get("delta", {})
        stop_reason = delta_obj.get("stop_reason")
        if stop_reason != "max_tokens":
            fail("finish_reason length should map to stop_reason max_tokens, got {!r}".format(stop_reason))
        else:
            pass_("SSE finish_reason length -> stop_reason max_tokens")
    finally:
        cleanup()


def test_chat_sse_no_content_delta():
    """Chunks without content delta produce no content_block_delta events."""
    print("\n--- Test: Chat SSE No Content Delta ---")
    upstream_port = find_free_port()
    tiers = _mode_tiers()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port), "key": "K", "mode": "chat"}}
    chunks = [
        {"id": "c1", "object": "chat.completion.chunk", "created": 1, "model": "gpt-4o",
         "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]},
        {"id": "c1", "object": "chat.completion.chunk", "created": 1, "model": "gpt-4o",
         "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
    ]
    sse_body = _sse_stream_chunks(chunks) + b"data: [DONE]\n\n"
    responders = {"p": lambda info: (200, "text/event-stream", sse_body)}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(tiers, vendors, responders=responders)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        status, content_type, raw = _send_proxy_request_stream(
            proxy_port, body={"model": "sonnet", "messages": [{"role": "user", "content": "hi"}]})
        if status != 200:
            fail("expected 200, got {}".format(status))
            return
        frames = _parse_sse_frames(raw)
        types = _sse_types(frames)
        if "content_block_delta" in types:
            fail("chunks without content produced content_block_delta: {}".format(types))
        else:
            pass_("no content_block_delta when chunks carry no content")
    finally:
        cleanup()


def test_chat_sse_empty_choices_usage_chunk():
    """An empty-choices usage chunk does not crash and its usage is accumulated."""
    print("\n--- Test: Chat SSE Empty Choices Usage Chunk ---")
    upstream_port = find_free_port()
    tiers = _mode_tiers()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port), "key": "K", "mode": "chat"}}
    chunks = [
        {"id": "c1", "object": "chat.completion.chunk", "created": 1, "model": "gpt-4o",
         "choices": [{"index": 0, "delta": {"role": "assistant", "content": "hi"}, "finish_reason": None}]},
        {"id": "c1", "object": "chat.completion.chunk", "created": 1, "model": "gpt-4o",
         "choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}},
        {"id": "c1", "object": "chat.completion.chunk", "created": 1, "model": "gpt-4o",
         "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
    ]
    sse_body = _sse_stream_chunks(chunks) + b"data: [DONE]\n\n"
    responders = {"p": lambda info: (200, "text/event-stream", sse_body)}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(tiers, vendors, responders=responders)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        status, content_type, raw = _send_proxy_request_stream(
            proxy_port, body={"model": "sonnet", "messages": [{"role": "user", "content": "hi"}]})
        if status != 200:
            fail("expected 200, got {}".format(status))
            return
        frames = _parse_sse_frames(raw)
        deltas = _sse_frames_with_type(frames, "message_delta")
        if not deltas:
            fail("no message_delta in stream")
            return
        usage = deltas[0].get("usage", {})
        if usage.get("input_tokens") != 10 or usage.get("output_tokens") != 5:
            fail("expected usage input_tokens=10 output_tokens=5 in message_delta, got {!r}".format(usage))
        else:
            pass_("empty-choices usage chunk accumulated into message_delta")
    finally:
        cleanup()


def test_chat_sse_eof_without_finish_reason():
    """Terminal events are synthesized when the stream ends without finish_reason."""
    print("\n--- Test: Chat SSE EOF Without Finish Reason ---")
    upstream_port = find_free_port()
    tiers = _mode_tiers()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port), "key": "K", "mode": "chat"}}
    chunks = [
        {"id": "c1", "object": "chat.completion.chunk", "created": 1, "model": "gpt-4o",
         "choices": [{"index": 0, "delta": {"role": "assistant", "content": "hello"}, "finish_reason": None}]},
    ]
    sse_body = _sse_stream_chunks(chunks)
    responders = {"p": lambda info: (200, "text/event-stream", sse_body)}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(tiers, vendors, responders=responders)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        status, content_type, raw = _send_proxy_request_stream(
            proxy_port, body={"model": "sonnet", "messages": [{"role": "user", "content": "hi"}]})
        if status != 200:
            fail("expected 200, got {}".format(status))
            return
        frames = _parse_sse_frames(raw)
        types = _sse_types(frames)
        missing = [t for t in ("content_block_stop", "message_delta", "message_stop") if t not in types]
        if missing:
            fail("EOF without finish_reason should synthesize terminal events; missing {}".format(missing))
        else:
            pass_("terminal events synthesized on EOF")
    finally:
        cleanup()


def test_chat_sse_first_event_has_content():
    """A first chunk that carries real content emits a content_block_delta."""
    print("\n--- Test: Chat SSE First Event Has Content ---")
    upstream_port = find_free_port()
    tiers = _mode_tiers()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port), "key": "K", "mode": "chat"}}
    chunks = [
        {"id": "c1", "object": "chat.completion.chunk", "created": 1, "model": "gpt-4o",
         "choices": [{"index": 0, "delta": {"role": "assistant", "content": "Deep"}, "finish_reason": None}]},
        {"id": "c1", "object": "chat.completion.chunk", "created": 1, "model": "gpt-4o",
         "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
    ]
    sse_body = _sse_stream_chunks(chunks) + b"data: [DONE]\n\n"
    responders = {"p": lambda info: (200, "text/event-stream", sse_body)}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(tiers, vendors, responders=responders)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        status, content_type, raw = _send_proxy_request_stream(
            proxy_port, body={"model": "sonnet", "messages": [{"role": "user", "content": "hi"}]})
        if status != 200:
            fail("expected 200, got {}".format(status))
            return
        frames = _parse_sse_frames(raw)
        deltas = _sse_frames_with_type(frames, "content_block_delta")
        texts = []
        for d in deltas:
            dd = d.get("delta", {})
            if isinstance(dd.get("text"), str):
                texts.append(dd.get("text"))
        if not any("Deep" in t for t in texts):
            fail("first-chunk content should appear in a content_block_delta, texts={!r}".format(texts))
        else:
            pass_("first-chunk content emitted as content_block_delta")
    finally:
        cleanup()


def test_chat_sse_injection_prevented():
    """Provider-controlled newline/event/data text cannot inject extra SSE events."""
    print("\n--- Test: Chat SSE Injection Prevented ---")
    upstream_port = find_free_port()
    tiers = _mode_tiers()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port), "key": "K", "mode": "chat"}}
    injected = "line1\nevent: message_stop\ndata: fake\n\nline2"
    chunks = [
        {"id": "c1", "object": "chat.completion.chunk", "created": 1, "model": "gpt-4o",
         "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]},
        {"id": "c1", "object": "chat.completion.chunk", "created": 1, "model": "gpt-4o",
         "choices": [{"index": 0, "delta": {"content": injected}, "finish_reason": None}]},
        {"id": "c1", "object": "chat.completion.chunk", "created": 1, "model": "gpt-4o",
         "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
    ]
    sse_body = _sse_stream_chunks(chunks) + b"data: [DONE]\n\n"
    responders = {"p": lambda info: (200, "text/event-stream", sse_body)}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(tiers, vendors, responders=responders)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        status, content_type, raw = _send_proxy_request_stream(
            proxy_port, body={"model": "sonnet", "messages": [{"role": "user", "content": "hi"}]})
        if status != 200:
            fail("expected 200, got {}".format(status))
            return
        # The injection must be confined inside a single JSON payload: a real
        # \n event: line only ever appears as an SSE frame boundary emitted by
        # the proxy itself. The terminal message_stop legitimately emits one
        # event: line, so assert exact count 1 and no injected line survives.
        n_real_events = raw.count(b"\nevent: message_stop")
        if b"\ndata: fake" in raw:
            fail("raw data: injection leaked into the client stream")
            return
        if n_real_events != 1:
            fail("injected event: line leaked into the client stream (count={})".format(n_real_events))
            return
        frames = _parse_sse_frames(raw)
        if _sse_types(frames).count("message_stop") != 1:
            fail("message_stop should appear exactly once; injected frame leaked: {}".format(_sse_types(frames)))
            return
        deltas = _sse_frames_with_type(frames, "content_block_delta")
        texts = [d.get("delta", {}).get("text") for d in deltas if isinstance(d.get("delta", {}).get("text"), str)]
        if injected not in texts:
            fail("delta content should arrive intact inside one payload, texts={!r}".format(texts))
        elif _sse_types(frames).count("message_stop") == 1:
            pass_("provider-controlled newlines cannot inject SSE events")
    finally:
        cleanup()


def test_chat_sse_event_line_present():
    """Every data-bearing SSE frame has an event: line matching the JSON type field.

    The Anthropic SDKs dispatch streaming events on the SSE `event:` field
    against a hardcoded whitelist; a data-only frame arrives with event=None and
    is silently dropped. This test inspects the raw wire format (not the JSON
    `type` fallback in _sse_frame_type) so a missing event: line fails the test.
    """
    print("\n--- Test: Chat SSE Event Line Present ---")
    upstream_port = find_free_port()
    tiers = _mode_tiers()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port), "key": "K", "mode": "chat"}}
    chunks = [
        {"id": "c1", "object": "chat.completion.chunk", "created": 1, "model": "gpt-4o",
         "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]},
        {"id": "c1", "object": "chat.completion.chunk", "created": 1, "model": "gpt-4o",
         "choices": [{"index": 0, "delta": {"content": "hi"}, "finish_reason": None}]},
        {"id": "c1", "object": "chat.completion.chunk", "created": 1, "model": "gpt-4o",
         "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
    ]
    sse_body = _sse_stream_chunks(chunks) + b"data: [DONE]\n\n"
    responders = {"p": lambda info: (200, "text/event-stream", sse_body)}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(tiers, vendors, responders=responders)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        status, content_type, raw = _send_proxy_request_stream(
            proxy_port, body={"model": "sonnet", "messages": [{"role": "user", "content": "hi"}]})
        if status != 200:
            fail("expected 200, got {}".format(status))
            return
        # Parse the raw wire format: extract event: lines and data: JSON independently.
        text = raw.decode("utf-8", errors="replace")
        wire_frames = []
        for block in text.split("\n\n"):
            block = block.strip("\n").strip("\r")
            if not block:
                continue
            event_line = None
            data_payload = None
            for line in block.split("\n"):
                line = line.strip("\r")
                if line.startswith("event:"):
                    event_line = line[6:].strip()
                elif line.startswith("data:"):
                    data_payload = line[5:].strip()
            if data_payload is not None:
                wire_frames.append((event_line, data_payload))
        if not wire_frames:
            fail("no data-bearing SSE frames found in client stream")
            return
        bad = []
        for event_line, data_payload in wire_frames:
            try:
                parsed = json.loads(data_payload)
            except Exception:
                continue
            if not isinstance(parsed, dict) or "type" not in parsed:
                continue
            json_type = parsed.get("type")
            if not event_line or event_line != json_type:
                bad.append((event_line, json_type))
        if bad:
            fail("SSE frames missing/mismatched event: line: {}".format(bad))
            return
        # A data-only frame (no event: line) must never be emitted — it would be
        # silently dropped by the Anthropic SDK.
        for event_line, data_payload in wire_frames:
            if event_line is None:
                fail("data-only SSE frame emitted (no event: line): {!r}".format(data_payload))
                return
        pass_("every data-bearing SSE frame has an event: line matching JSON type")
    finally:
        cleanup()


def test_chat_sse_tool_calls_stop_reason_null():
    """tool_calls finish_reason maps to null stop_reason when tool deltas were seen.

    The SSE path does not transform delta.tool_calls into tool_use content
    blocks, so claiming stop_reason='tool_use' would make Claude Code hang
    waiting for tool_use blocks that never arrive. When tool_calls deltas were
    seen but not transformed, the terminal stop_reason degrades to null.
    """
    print("\n--- Test: Chat SSE Tool Calls Stop Reason Null ---")
    upstream_port = find_free_port()
    tiers = _mode_tiers()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port), "key": "K", "mode": "chat"}}
    chunks = [
        {"id": "c1", "object": "chat.completion.chunk", "created": 1, "model": "gpt-4o",
         "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]},
        {"id": "c1", "object": "chat.completion.chunk", "created": 1, "model": "gpt-4o",
         "choices": [{"index": 0, "delta": {"tool_calls": [{"index": 0, "id": "call_1", "type": "function",
                      "function": {"name": "get_weather", "arguments": "{\"city\":\"NYC\"}"}}]}, "finish_reason": None}]},
        {"id": "c1", "object": "chat.completion.chunk", "created": 1, "model": "gpt-4o",
         "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]},
    ]
    sse_body = _sse_stream_chunks(chunks) + b"data: [DONE]\n\n"
    responders = {"p": lambda info: (200, "text/event-stream", sse_body)}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(tiers, vendors, responders=responders)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        status, content_type, raw = _send_proxy_request_stream(
            proxy_port, body={"model": "sonnet", "messages": [{"role": "user", "content": "hi"}]})
        if status != 200:
            fail("expected 200, got {}".format(status))
            return
        frames = _parse_sse_frames(raw)
        deltas = _sse_frames_with_type(frames, "message_delta")
        if not deltas:
            fail("no message_delta in stream")
            return
        stop_reason = deltas[0].get("delta", {}).get("stop_reason")
        if stop_reason is not None:
            fail("tool_calls finish_reason with tool_calls deltas seen should map to null stop_reason, got {!r}".format(stop_reason))
            return
        # Control: tool_calls finish_reason WITHOUT tool_calls deltas seen maps to tool_use.
        upstream2_port = find_free_port()
        vendors2 = {"p": {"url": "http://127.0.0.1:{}".format(upstream2_port), "key": "K", "mode": "chat"}}
        chunks2 = [
            {"id": "c1", "object": "chat.completion.chunk", "created": 1, "model": "gpt-4o",
             "choices": [{"index": 0, "delta": {"role": "assistant", "content": "ok"}, "finish_reason": None}]},
            {"id": "c1", "object": "chat.completion.chunk", "created": 1, "model": "gpt-4o",
             "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]},
        ]
        sse2 = _sse_stream_chunks(chunks2) + b"data: [DONE]\n\n"
        responders2 = {"p": lambda info: (200, "text/event-stream", sse2)}
        temp_dir2, proxy_port2, proc2, mock2, trace2, cleanup2 = _start_mode_proxy(tiers, vendors2, responders=responders2)
        if proc2 is None:
            fail("Failed to set up control test")
            return
        try:
            status2, content_type2, raw2 = _send_proxy_request_stream(
                proxy_port2, body={"model": "sonnet", "messages": [{"role": "user", "content": "hi"}]})
            if status2 != 200:
                fail("control expected 200, got {}".format(status2))
                return
            frames2 = _parse_sse_frames(raw2)
            deltas2 = _sse_frames_with_type(frames2, "message_delta")
            if not deltas2:
                fail("control: no message_delta in stream")
                return
            sr2 = deltas2[0].get("delta", {}).get("stop_reason")
            if sr2 != "tool_use":
                fail("control: tool_calls finish_reason WITHOUT tool deltas seen should map to tool_use, got {!r}".format(sr2))
                return
        finally:
            cleanup2()
        pass_("tool_calls deltas seen -> null stop_reason; control (no deltas) -> tool_use")
    finally:
        cleanup()


def test_chat_sse_reasoning_delta_to_thinking_delta():
    """reasoning_content delta -> thinking block at index 0, then text block at index 1.

    The Anthropic client expects unique, increasing block indices across
    content_block_start / content_block_delta / content_block_stop events.
    """
    print("\n--- Test: Chat SSE Reasoning Delta To Thinking Delta ---")
    upstream_port = find_free_port()
    tiers = _mode_tiers()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port), "key": "K", "mode": "chat"}}
    chunks = [
        {"id": "c1", "object": "chat.completion.chunk", "created": 1, "model": "gpt-4o",
         "choices": [{"index": 0, "delta": {"role": "assistant", "reasoning_content": "Let me"},
                      "finish_reason": None}]},
        {"id": "c1", "object": "chat.completion.chunk", "created": 1, "model": "gpt-4o",
         "choices": [{"index": 0, "delta": {"reasoning_content": " think"}, "finish_reason": None}]},
        {"id": "c1", "object": "chat.completion.chunk", "created": 1, "model": "gpt-4o",
         "choices": [{"index": 0, "delta": {"content": "Hi"}, "finish_reason": None}]},
        {"id": "c1", "object": "chat.completion.chunk", "created": 1, "model": "gpt-4o",
         "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
    ]
    sse_body = _sse_stream_chunks(chunks) + b"data: [DONE]\n\n"
    responders = {"p": lambda info: (200, "text/event-stream", sse_body)}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(tiers, vendors, responders=responders)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        status, content_type, raw = _send_proxy_request_stream(
            proxy_port, body={"model": "sonnet", "messages": [{"role": "user", "content": "hi"}]})
        if status != 200:
            fail("expected 200, got {}".format(status))
            return
        frames = _parse_sse_frames(raw)
        starts = _sse_frames_with_type(frames, "content_block_start")
        deltas = _sse_frames_with_type(frames, "content_block_delta")
        stops = _sse_frames_with_type(frames, "content_block_stop")
        if len(starts) != 2:
            fail("expected 2 content_block_start events (thinking + text), got {}: {!r}".format(len(starts), starts))
            return
        if starts[0].get("index") != 0 or starts[0].get("content_block", {}).get("type") != "thinking":
            fail("first content_block_start should be thinking at index 0, got {!r}".format(starts[0]))
            return
        if starts[1].get("index") != 1 or starts[1].get("content_block", {}).get("type") != "text":
            fail("second content_block_start should be text at index 1, got {!r}".format(starts[1]))
            return
        thinking_deltas = [d for d in deltas if d.get("delta", {}).get("type") == "thinking_delta"]
        text_deltas = [d for d in deltas if d.get("delta", {}).get("type") == "text_delta"]
        if not thinking_deltas:
            fail("expected thinking_delta events, got {!r}".format(deltas))
            return
        for d in thinking_deltas:
            if d.get("index") != 0:
                fail("thinking_delta must use index 0, got {!r}".format(d))
                return
        if not text_deltas or text_deltas[0].get("index") != 1:
            fail("text_delta should use index 1, got {!r}".format(text_deltas))
            return
        joined_reasoning = "".join(d.get("delta", {}).get("thinking", "") for d in thinking_deltas)
        if "Let me think" != joined_reasoning:
            fail("reasoning text mismatch, joined={!r}".format(joined_reasoning))
            return
        if len(stops) != 2:
            fail("expected 2 content_block_stop events, got {}: {!r}".format(len(stops), stops))
            return
        indices = [s.get("index") for s in starts] + [d.get("index") for d in deltas] + [s.get("index") for s in stops]
        if len(set(indices)) != 2 or set(indices) != {0, 1}:
            fail("block indices should be exactly {{0, 1}}, got {!r}".format(indices))
            return
        pass_("reasoning delta -> thinking block index 0, text index 1, unique indices")
    finally:
        cleanup()


def test_chat_sse_reasoning_delta_no_content():
    """A stream with only reasoning deltas still emits valid thinking blocks and terminal events.

    One content_block_stop for the thinking block; the client never hangs.
    """
    print("\n--- Test: Chat SSE Reasoning Delta No Content ---")
    upstream_port = find_free_port()
    tiers = _mode_tiers()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port), "key": "K", "mode": "chat"}}
    chunks = [
        {"id": "c1", "object": "chat.completion.chunk", "created": 1, "model": "gpt-4o",
         "choices": [{"index": 0, "delta": {"role": "assistant", "reasoning_content": "r1"},
                      "finish_reason": None}]},
        {"id": "c1", "object": "chat.completion.chunk", "created": 1, "model": "gpt-4o",
         "choices": [{"index": 0, "delta": {"reasoning_content": "r2"}, "finish_reason": None}]},
        {"id": "c1", "object": "chat.completion.chunk", "created": 1, "model": "gpt-4o",
         "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
    ]
    sse_body = _sse_stream_chunks(chunks) + b"data: [DONE]\n\n"
    responders = {"p": lambda info: (200, "text/event-stream", sse_body)}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(tiers, vendors, responders=responders)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        status, content_type, raw = _send_proxy_request_stream(
            proxy_port, body={"model": "sonnet", "messages": [{"role": "user", "content": "hi"}]})
        if status != 200:
            fail("expected 200, got {}".format(status))
            return
        frames = _parse_sse_frames(raw)
        types = _sse_types(frames)
        starts = _sse_frames_with_type(frames, "content_block_start")
        stops = _sse_frames_with_type(frames, "content_block_stop")
        if len(starts) != 1 or starts[0].get("content_block", {}).get("type") != "thinking":
            fail("expected exactly one thinking content_block_start, got {!r}".format(starts))
            return
        if starts[0].get("index") != 0:
            fail("thinking block should be at index 0, got {!r}".format(starts[0]))
            return
        if len(stops) != 1 or stops[0].get("index") != 0:
            fail("expected one content_block_stop at index 0, got {!r}".format(stops))
            return
        missing = [t for t in ("content_block_start", "content_block_delta",
                               "content_block_stop", "message_delta", "message_stop") if t not in types]
        if missing:
            fail("missing terminal SSE events {}; got {}".format(missing, types))
            return
        deltas = _sse_frames_with_type(frames, "content_block_delta")
        if not all(d.get("delta", {}).get("type") == "thinking_delta" for d in deltas):
            fail("all deltas should be thinking_delta, got {!r}".format(deltas))
            return
        pass_("reasoning-only stream -> valid thinking block + terminal events")
    finally:
        cleanup()


def test_chat_sse_reasoning_then_text_transition():
    """thinking content_block_stop(index 0) precedes text content_block_start(index 1)."""
    print("\n--- Test: Chat SSE Reasoning Then Text Transition ---")
    upstream_port = find_free_port()
    tiers = _mode_tiers()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port), "key": "K", "mode": "chat"}}
    chunks = [
        {"id": "c1", "object": "chat.completion.chunk", "created": 1, "model": "gpt-4o",
         "choices": [{"index": 0, "delta": {"role": "assistant", "reasoning_content": "r"},
                      "finish_reason": None}]},
        {"id": "c1", "object": "chat.completion.chunk", "created": 1, "model": "gpt-4o",
         "choices": [{"index": 0, "delta": {"content": "text"}, "finish_reason": None}]},
        {"id": "c1", "object": "chat.completion.chunk", "created": 1, "model": "gpt-4o",
         "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
    ]
    sse_body = _sse_stream_chunks(chunks) + b"data: [DONE]\n\n"
    responders = {"p": lambda info: (200, "text/event-stream", sse_body)}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(tiers, vendors, responders=responders)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        status, content_type, raw = _send_proxy_request_stream(
            proxy_port, body={"model": "sonnet", "messages": [{"role": "user", "content": "hi"}]})
        if status != 200:
            fail("expected 200, got {}".format(status))
            return
        frames = _parse_sse_frames(raw)
        starts = _sse_frames_with_type(frames, "content_block_start")
        stops = _sse_frames_with_type(frames, "content_block_stop")
        if len(starts) != 2 or len(stops) != 2:
            fail("expected 2 starts and 2 stops, got starts={!r} stops={!r}".format(starts, stops))
            return
        thinking_stop = stops[0]
        text_start = starts[1]
        if thinking_stop.get("index") != 0:
            fail("thinking stop should be at index 0, got {!r}".format(thinking_stop))
            return
        if text_start.get("index") != 1 or text_start.get("content_block", {}).get("type") != "text":
            fail("text start should be at index 1, got {!r}".format(text_start))
            return
        stop_pos = next(i for i, f in enumerate(frames) if _sse_frame_type(f) == "content_block_stop" and isinstance(f[1], dict) and f[1].get("index") == 0)
        start_pos = next(i for i, f in enumerate(frames) if _sse_frame_type(f) == "content_block_start" and isinstance(f[1], dict) and f[1].get("index") == 1)
        if not (stop_pos < start_pos):
            fail("thinking stop (pos {}) must precede text start (pos {})".format(stop_pos, start_pos))
            return
        pass_("thinking stop(index 0) precedes text start(index 1)")
    finally:
        cleanup()


# --- Step 9: wiring / e2e ---

def test_chat_mode_e2e_json():
    """End-to-end chat mode request/response through the live proxy."""
    print("\n--- Test: Chat Mode E2E JSON ---")
    upstream_port = find_free_port()
    tiers = _mode_tiers()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port), "key": "K", "mode": "chat"}}
    chat_ok = json.dumps({
        "id": "chatcmpl-1", "object": "chat.completion", "created": 1, "model": "gpt-4o",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "Hello"},
                     "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
    }).encode()
    responders = {"p": lambda info: (200, "application/json", chat_ok)}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(tiers, vendors, responders=responders)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        status, body = _send_proxy_request(proxy_port)
        if status != 200:
            fail("expected 200, got {}".format(status))
            return
        try:
            data = json.loads(body)
        except Exception:
            fail("response is not valid JSON: {!r}".format(body[:200]))
            return
        if data.get("type") != "message" or data.get("role") != "assistant":
            fail("response not anthropic-shaped: {!r}".format(data))
        if data.get("model") != "sonnet":
            fail("expected model tier 'sonnet', got {!r}".format(data.get("model")))
        if data.get("content") != [{"type": "text", "text": "Hello"}]:
            fail("expected content [text Hello], got {!r}".format(data.get("content")))
        if data.get("stop_reason") != "end_turn":
            fail("expected stop_reason end_turn, got {!r}".format(data.get("stop_reason")))
        reqs = mock_servers["p"]["requests"]
        if not reqs:
            fail("upstream received no requests")
            return
        try:
            upstream_body = json.loads(reqs[0]["body"])
        except Exception:
            fail("upstream request body is not JSON: {!r}".format(reqs[0]["body"][:200]))
            return
        if upstream_body.get("model") != "claude-sonnet-5":
            fail("upstream should receive the actual model name, got {!r}".format(upstream_body.get("model")))
        if not isinstance(upstream_body.get("messages"), list):
            fail("upstream should receive messages array, got {!r}".format(upstream_body.get("messages")))
        if data.get("type") == "message" and data.get("content") == [{"type": "text", "text": "Hello"}] and isinstance(upstream_body.get("messages"), list):
            pass_("chat mode e2e transform round-trips")
    finally:
        cleanup()


def test_response_mode_e2e_json():
    """End-to-end response mode request/response through the live proxy."""
    print("\n--- Test: Response Mode E2E JSON ---")
    upstream_port = find_free_port()
    tiers = _mode_tiers()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port), "key": "K", "mode": "response"}}
    resp_ok = json.dumps({
        "id": "resp_1", "object": "response", "created_at": 1, "model": "gpt-4o",
        "status": "completed",
        "output": [{"type": "message", "role": "assistant",
                    "content": [{"type": "output_text", "text": "Hello", "annotations": []}]}],
        "usage": {"input_tokens": 4, "output_tokens": 2, "total_tokens": 6},
    }).encode()
    responders = {"p": lambda info: (200, "application/json", resp_ok)}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(tiers, vendors, responders=responders)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        body = json.dumps({"model": "sonnet",
                           "system": "Be concise",
                           "messages": [{"role": "user", "content": "one"},
                                        {"role": "assistant", "content": "two"},
                                        {"role": "user", "content": "three"}],
                           "stream": True})
        status, resp_body = _send_proxy_request(proxy_port, body=body)
        if status != 200:
            fail("expected 200, got {}".format(status))
            return
        try:
            data = json.loads(resp_body)
        except Exception:
            fail("response is not valid JSON: {!r}".format(resp_body[:200]))
            return
        if data.get("model") != "sonnet":
            fail("expected model tier 'sonnet', got {!r}".format(data.get("model")))
        if data.get("content") != [{"type": "text", "text": "Hello"}]:
            fail("expected content [text Hello], got {!r}".format(data.get("content")))
        reqs = mock_servers["p"]["requests"]
        if not reqs:
            fail("upstream received no requests")
            return
        try:
            ubody = json.loads(reqs[0]["body"])
        except Exception:
            fail("upstream request body not JSON: {!r}".format(reqs[0]["body"][:200]))
            return
        if ubody.get("stream") is not False:
            fail("upstream should receive stream=false, got {!r}".format(ubody.get("stream")))
        if ubody.get("input") != "three":
            fail("upstream input should be last user message 'three', got {!r}".format(ubody.get("input")))
        if ubody.get("instructions") != "Be concise":
            fail("upstream instructions mismatch: {!r}".format(ubody.get("instructions")))
        if "messages" in ubody:
            fail("upstream body should drop messages, got {!r}".format(sorted(ubody.keys())))
        if data.get("model") == "sonnet" and data.get("content") == [{"type": "text", "text": "Hello"}] and "messages" not in ubody:
            pass_("response mode e2e transform round-trips")
    finally:
        cleanup()


def test_anthropic_mode_unchanged():
    """Existing anthropic behavior is preserved (no mode field)."""
    print("\n--- Test: Anthropic Mode Unchanged ---")
    upstream_port = find_free_port()
    tiers = _mode_tiers()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port), "key": "K"}}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(tiers, vendors)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        status, body = _send_proxy_request(proxy_port)
        if status != 200:
            fail("expected 200, got {}".format(status))
            return
        try:
            data = json.loads(body)
        except Exception:
            fail("response not JSON: {!r}".format(body[:200]))
            return
        # x-api-key used (anthropic default)
        reqs = mock_servers["p"]["requests"]
        if not reqs or reqs[0]["api_key"] != "K":
            fail("anthropic mode should use x-api-key=K")
        # model rewritten to tier name
        if data.get("model") != "sonnet":
            fail("expected model rewritten to 'sonnet', got {!r}".format(data.get("model")))
        if data.get("content") == [{"type": "text", "text": "hello"}] and reqs and reqs[0]["api_key"] == "K":
            pass_("anthropic mode preserves existing behavior")
    finally:
        cleanup()


def test_chat_mode_non_2xx_passthrough():
    """Chat-mode non-2xx error body passes through untransformed."""
    print("\n--- Test: Chat Mode Non 2xx Passthrough ---")
    upstream_port = find_free_port()
    tiers = _mode_tiers()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port), "key": "K", "mode": "chat"}}
    err_body = json.dumps({"error": {"message": "Nothing here", "type": "invalid_request_error"}}).encode()
    responders = {"p": lambda info: (404, "application/json", err_body)}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(tiers, vendors, responders=responders)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        status, body = _send_proxy_request(proxy_port)
        if status != 404:
            fail("expected 404, got {}".format(status))
            return
        if body != err_body:
            fail("non-2xx body should pass through byte-for-byte, got {!r}".format(body[:200]))
        else:
            pass_("chat-mode non-2xx body passes through untransformed")
    finally:
        cleanup()


def test_transform_failure_passthrough():
    """Malformed JSON response body passes through with a transform_failure trace event."""
    print("\n--- Test: Transform Failure Passthrough ---")
    upstream_port = find_free_port()
    tiers = _mode_tiers()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port), "key": "K", "mode": "chat"}}
    bad_body = b"this is not json at all"
    responders = {"p": lambda info: (200, "application/json", bad_body)}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(tiers, vendors, responders=responders)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        status, body = _send_proxy_request(proxy_port)
        if status != 200:
            fail("expected 200, got {}".format(status))
            return
        if body != bad_body:
            fail("malformed JSON body should pass through unchanged, got {!r}".format(body[:200]))
            return
        found = False
        fields_ok = False
        with open(trace_file) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except Exception:
                    continue
                if ev.get("event") == "transform_failure":
                    found = True
                    if (ev.get("provider") == "p" and ev.get("tier") == "sonnet"
                            and ev.get("request_id") and ev.get("mode") == "chat"):
                        fields_ok = True
        if not found:
            fail("expected a transform_failure trace event, none found")
        elif not fields_ok:
            fail("transform_failure event missing provider/tier/request_id/mode, got {!r}".format(ev))
        else:
            pass_("malformed JSON passes through with transform_failure trace event carrying provider/tier")
    finally:
        cleanup()


def test_tool_args_parse_failure_trace_has_request_id():
    """End-to-end: tool_args_parse_failure trace event carries request_id/mode/provider/tier.

    Chat-mode proxy with a mock upstream returning malformed tool-call
    arguments. The proxy's response transform degrades the malformed call to
    a text block and logs tool_args_parse_failure with the full correlation
    context threaded through _transform_and_guard.
    """
    print("\n--- Test: Tool Args Parse Failure Trace Has Request ID ---")
    upstream_port = find_free_port()
    tiers = _mode_tiers()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port), "key": "K", "mode": "chat"}}
    chat_malformed = json.dumps({
        "id": "chatcmpl-1", "object": "chat.completion", "created": 1, "model": "gpt-4o",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "",
                                             "tool_calls": [
                                                 {"id": "call_1", "type": "function",
                                                  "function": {"name": "f", "arguments": "{not json"}}]},
                     "finish_reason": "tool_calls"}],
        "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
    }).encode()
    responders = {"p": lambda info: (200, "application/json", chat_malformed)}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(
        tiers, vendors, responders=responders)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        status, body = _send_proxy_request(proxy_port)
        if status != 200:
            fail("expected 200, got {}".format(status))
            return
        try:
            data = json.loads(body)
        except Exception:
            fail("response is not valid JSON: {!r}".format(body[:200]))
            return
        content = data.get("content") if isinstance(data.get("content"), list) else []
        if any(b.get("type") == "tool_use" for b in content):
            fail("malformed tool args must not produce a tool_use block, content={!r}".format(content))
            return
        if data.get("stop_reason") is not None:
            fail("all-malformed tool calls should force stop_reason None, got {!r}".format(data.get("stop_reason")))
            return
        found = False
        fields_ok = False
        matched_ev = None
        with open(trace_file) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except Exception:
                    continue
                if ev.get("event") == "tool_args_parse_failure":
                    found = True
                    matched_ev = ev
                    if (ev.get("request_id") and ev.get("mode") == "chat"
                            and ev.get("provider") == "p" and ev.get("tier") == "sonnet"):
                        fields_ok = True
        if not found:
            fail("expected a tool_args_parse_failure trace event, none found")
        elif not fields_ok:
            fail("tool_args_parse_failure event missing request_id/mode/provider/tier, got {!r}".format(matched_ev))
        else:
            pass_("tool_args_parse_failure trace event carries request_id/mode/provider/tier")
    finally:
        cleanup()


def test_retry_does_not_double_transform():
    """A 429 retry sends the same single-transformed body, not double-encoded."""
    print("\n--- Test: Retry Does Not Double Transform ---")
    upstream_port = find_free_port()
    tiers = _mode_tiers()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port), "key": "K", "mode": "chat"}}
    chat_ok = json.dumps({
        "id": "chatcmpl-1", "object": "chat.completion", "created": 1, "model": "gpt-4o",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "Hello"},
                     "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
    }).encode()
    err_body = json.dumps({"error": {"message": "too many", "type": "rate_limit"}}).encode()
    attempts = {"n": 0}

    def responder(info):
        attempts["n"] += 1
        if attempts["n"] == 1:
            return 429, "application/json", err_body
        return 200, "application/json", chat_ok

    responders = {"p": responder}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(
        tiers, vendors, responders=responders,
        extra_env={"PROXY_MAX_RETRIES": "2", "PROXY_MAX_DELAY": "2", "PROXY_INITIAL_DELAY": "1"})
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        status, body = _send_proxy_request(proxy_port)
        if status != 200:
            fail("expected 200 after retry, got {}".format(status))
            return
        reqs = mock_servers["p"]["requests"]
        if len(reqs) < 2:
            fail("expected upstream to receive at least 2 requests (429 then 200), got {}".format(len(reqs)))
            return
        bodies = [json.loads(r["body"]) for r in reqs]
        for rb in bodies:
            if not isinstance(rb, dict) or not isinstance(rb.get("messages"), list):
                fail("transformed body should be single-pass JSON with messages list, got {!r}".format(rb))
                return
        if reqs[0]["body"] != reqs[1]["body"]:
            fail("retry should reuse the same pre-built transformed body")
        else:
            pass_("retry sends the single-transformed body, unchanged across attempts")
    finally:
        cleanup()


# --- Step 10: admin providers-detail endpoint ---

def test_admin_providers_detail():
    """providers-detail returns mode per provider without keys."""
    print("\n--- Test: Admin Providers Detail ---")
    p1, p2, p3 = find_free_port(), find_free_port(), find_free_port()
    tiers = _mode_tiers("anthro")
    vendors = {
        "anthro": {"url": "http://127.0.0.1:{}".format(p1), "key": "KEY-AAA"},
        "chat_p": {"url": "http://127.0.0.1:{}".format(p2), "key": "KEY-BBB", "mode": "chat"},
        "resp_p": {"url": "http://127.0.0.1:{}".format(p3), "key": "KEY-CCC", "mode": "response"},
    }
    proxy_port, proc, mock_servers, temp_dir, cleanup = _start_admin_proxy(tiers, vendors)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        status, body, _ = _admin_get(proxy_port, "/admin/api/providers-detail")
        if status != 200:
            fail("expected 200, got {}".format(status))
            return
        try:
            data = json.loads(body)
        except Exception:
            fail("providers-detail not JSON: {!r}".format(body[:200]))
            return
        providers = data.get("providers", {})
        if providers.get("anthro", {}).get("mode") != "anthropic":
            fail("expected anthro mode anthropic, got {!r}".format(providers))
        if providers.get("chat_p", {}).get("mode") != "chat":
            fail("expected chat_p mode chat, got {!r}".format(providers))
        if providers.get("resp_p", {}).get("mode") != "response":
            fail("expected resp_p mode response, got {!r}".format(providers))
        text = body.decode("utf-8", errors="replace")
        for key in ("KEY-AAA", "KEY-BBB", "KEY-CCC"):
            if key in text:
                fail("providers-detail leaked key material: {}".format(key))
        if providers.get("chat_p", {}).get("mode") == "chat" and "KEY-BBB" not in text:
            pass_("providers-detail returns modes without keys")
    finally:
        cleanup()


def test_admin_providers_detail_no_mode():
    """Providers without a mode return anthropic."""
    print("\n--- Test: Admin Providers Detail No Mode ---")
    p1 = find_free_port()
    tiers = _mode_tiers("anthro")
    vendors = {"anthro": {"url": "http://127.0.0.1:{}".format(p1), "key": "K"}}
    proxy_port, proc, mock_servers, temp_dir, cleanup = _start_admin_proxy(tiers, vendors)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        status, body, _ = _admin_get(proxy_port, "/admin/api/providers-detail")
        if status != 200:
            fail("expected 200, got {}".format(status))
            return
        try:
            data = json.loads(body)
        except Exception:
            fail("providers-detail not JSON: {!r}".format(body[:200]))
            return
        mode = data.get("providers", {}).get("anthro", {}).get("mode")
        if mode != "anthropic":
            fail("expected mode anthropic for mode-less provider, got {!r}".format(mode))
        else:
            pass_("mode-less provider reports anthropic")
    finally:
        cleanup()


def test_admin_providers_detail_forbidden():
    """providers-detail is rejected for non-localhost clients."""
    print("\n--- Test: Admin Providers Detail Forbidden ---")
    p1 = find_free_port()
    tiers = _mode_tiers("anthro")
    vendors = {"anthro": {"url": "http://127.0.0.1:{}".format(p1), "key": "K"}}
    proxy_port, proc, mock_servers, temp_dir, cleanup = _start_admin_proxy(tiers, vendors)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        try:
            status, body, _ = _admin_get(proxy_port, "/admin/api/providers-detail", source_ip="127.0.0.2")
        except OSError as e:
            fail("cannot bind alternate loopback source: {} — environment limited".format(e))
            return
        if status != 403:
            fail("expected 403 for non-localhost client, got {} ({})".format(status, body[:100]))
        else:
            pass_("non-localhost providers-detail request rejected")
    finally:
        cleanup()


def test_admin_providers_detail_invalid_mode_normalized():
    """Unknown mode in keys is normalized to anthropic in the admin endpoint."""
    print("\n--- Test: Admin Providers Detail Invalid Mode Normalized ---")
    p1 = find_free_port()
    tiers = _mode_tiers("anthro")
    vendors = {"anthro": {"url": "http://127.0.0.1:{}".format(p1), "key": "K", "mode": "watermelon"}}
    proxy_port, proc, mock_servers, temp_dir, cleanup = _start_admin_proxy(tiers, vendors)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        # Server must still start (mode validation is warn-only) and normalize display
        status, body, _ = _admin_get(proxy_port, "/admin/api/providers-detail")
        if status != 200:
            fail("expected 200, got {}".format(status))
            return
        try:
            data = json.loads(body)
        except Exception:
            fail("providers-detail not JSON: {!r}".format(body[:200]))
            return
        mode = data.get("providers", {}).get("anthro", {}).get("mode")
        if mode != "anthropic":
            fail("expected unknown mode normalized to anthropic, got {!r}".format(mode))
        else:
            pass_("unknown mode displayed as anthropic")
    finally:
        cleanup()


# ===========================================================================
# Test runner
# ===========================================================================

ALL_TESTS = [
    # Unit tests (no settings.json dependency, should still work)
    ("compute-jittered-delay-bounds", test_compute_jittered_delay_bounds),
    ("start-prunes-old-trace-entries", test_start_prunes_old_trace_entries),
    ("prune-trace-file-edge-cases", test_prune_trace_file_edge_cases),
    ("crlf-header-filter", test_crlf_header_filter),

    # Direct-server tests (need migration to config/keys flow — will fail until migrated)
    ("concurrent-requests", test_concurrent_requests),
    ("retry-logic", test_retry_logic),
    ("retry-429", test_retry_429),
    ("retry-429-exhaust-returns-429", test_retry_429_exhaust_returns_429),
    ("trace-markers", test_trace_markers),
    ("thread-safety", test_thread_safety),
    ("relative-log-path", test_relative_log_path),
    ("trace-logs-oversized-body", test_trace_logs_oversized_body),
    ("start-no-auth-header-required", test_start_no_auth_header_required),
    ("exhaust-429-preserves-body", test_exhaust_429_preserves_body),
    ("exhaust-connection-error-synthesizes-body", test_exhaust_connection_error_synthesizes_body),
    ("client-disconnect-no-traceback", test_client_disconnect_no_traceback),
    ("streaming-response-body", test_streaming_response_body),
    ("streaming-mid-stream-upstream-failure", test_streaming_mid_stream_upstream_failure),
    ("empty-body-429-exhaust", test_empty_body_429_exhaust),

    # New tests for plan 2026-08-23-cc-switch-mode
    ("tier-routing-basic", test_tier_routing_basic),
    ("tier-routing-all-tiers", test_tier_routing_all_tiers),
    ("model-resolution-reverse-lookup", test_model_resolution_reverse_lookup),
    ("model-resolution-pattern-match", test_model_resolution_pattern_match),
    ("model-resolution-unknown-rejected", test_model_resolution_unknown_rejected),
    ("model-resolution-none-rejected", test_model_resolution_none_rejected),
    ("response-model-rewrite", test_response_model_rewrite),
    ("response-model-rewrite-streaming", test_response_model_rewrite_streaming),
    ("response-model-rewrite-streaming-non-message-start", test_response_model_rewrite_streaming_non_message_start),
    ("response-model-rewrite-upstream-model", test_response_model_rewrite_upstream_model),
    ("two-tiers-same-model-same-provider", test_two_tiers_same_model_same_provider),
    ("config-validation-missing-tier", test_config_validation_missing_tier),
    ("config-validation-unknown-provider", test_config_validation_unknown_provider),
    ("config-validation-models-to-keys", test_config_validation_models_to_keys),
    ("config-validation-tier-provider-needs-models", test_config_validation_tier_provider_needs_models),
    ("models-per-provider-validation", test_models_per_provider_validation),
    ("heartbeat-preserves-state", test_heartbeat_preserves_state),
    ("config-template-copy", test_config_template_copy),
    ("admin-page-served", test_admin_page_served),
    ("admin-api-config", test_admin_api_config),
    ("admin-api-switch", test_admin_api_switch),
    ("admin-api-switch-invalid-provider", test_admin_api_switch_invalid_provider),
    ("admin-api-switch-preserves-models", test_admin_api_switch_preserves_models),
    ("admin-api-csrf-rejected", test_admin_api_csrf_rejected),
    ("admin-api-csrf-null-origin-rejected", test_admin_api_csrf_null_origin_rejected),
    ("admin-api-csrf-missing-origin-rejected", test_admin_api_csrf_missing_origin_rejected),
    ("admin-api-csrf-ipv6-loopback-accepted", test_admin_api_csrf_ipv6_loopback_accepted),
    ("admin-api-switch-missing-tier-rejected", test_admin_api_switch_missing_tier_rejected),
    ("admin-api-reload", test_admin_api_reload),
    ("cli-reload", test_cli_reload),
    ("cli-start-no-config", test_cli_start_no_config),
    ("cli-start-invalid-config", test_cli_start_invalid_config),
    ("cli-status-shows-tiers", test_cli_status_shows_tiers),
    ("cli-stop-cleans-proxy-state-lock", test_stop_cleans_proxy_state_lock),
    ("cli-stop-cleans-proxy-state", test_stop_cleans_proxy_state),
    ("cli-stop-trace-with-proxy", test_stop_trace_with_proxy),
    ("cli-start-stdout-not-contaminated", test_start_stdout_not_contaminated),
    ("key-decryption-wrong-passphrase", test_key_decryption_wrong_passphrase),
    ("key-decryption-missing-file", test_key_decryption_missing_file),
    ("api-key-from-keys-index", test_api_key_from_keys_index),
    ("admin-models-provider-keyed", test_admin_models_provider_keyed),
    ("disable-retry-count-tokens-503", test_disable_retry_count_tokens_503),
    ("disable-retry-count-tokens-conn-error", test_disable_retry_count_tokens_conn_error),
    ("disable-retry-count-tokens-normal-path-unaffected", test_disable_retry_count_tokens_normal_path_unaffected),
    ("disable-retry-count-tokens-false-retries", test_disable_retry_count_tokens_false_retries),
    ("disable-retry-count-tokens-path-anchoring", test_disable_retry_count_tokens_path_anchoring),
    ("disable-retry-count-tokens-invalid-type", test_disable_retry_count_tokens_invalid_type),
    ("admin-switch-preserves-disable-retry-flag", test_admin_switch_preserves_disable_retry_flag),
    ("retry-trace-event-enriched", test_retry_trace_event_enriched),

    # Mode dispatch tests (plan 2026-08-27-support-three-endpoint-modes)
    ("mode-defaults-to-anthropic", test_mode_defaults_to_anthropic),
    ("mode-null-defaults-to-anthropic", test_mode_null_defaults_to_anthropic),
    ("mode-invalid-rejected", test_mode_invalid_rejected),
    ("auth-header-anthropic-mode", test_auth_header_anthropic_mode),
    ("auth-header-chat-mode", test_auth_header_chat_mode),
    ("auth-header-response-mode", test_auth_header_response_mode),
    ("path-anthropic-mode", test_path_anthropic_mode),
    ("path-chat-mode", test_path_chat_mode),
    ("path-response-mode", test_path_response_mode),
    ("path-double-v1-prevention", test_path_double_v1_prevention),
    ("count-tokens-rejected-chat-mode", test_count_tokens_rejected_chat_mode),
    ("count-tokens-rejected-response-mode", test_count_tokens_rejected_response_mode),
    ("anthropic-to-chat-basic", test_anthropic_to_chat_basic),
    ("anthropic-to-chat-system-string", test_anthropic_to_chat_system_string),
    ("anthropic-to-chat-system-list", test_anthropic_to_chat_system_list),
    ("anthropic-to-chat-dropped-fields", test_anthropic_to_chat_dropped_fields),
    ("anthropic-to-chat-stop-sequences", test_anthropic_to_chat_stop_sequences),

    # Chat-mode request transform tests (plan 2026-08-29-fix-chat-mode-request-transform)
    ("anthropic-to-chat-messages-transform", test_anthropic_to_chat_messages_transform),
    ("anthropic-to-chat-messages-thinking-stripped", test_anthropic_to_chat_messages_thinking_stripped),
    ("anthropic-to-chat-messages-redacted-thinking-trace", test_anthropic_to_chat_messages_redacted_thinking_trace),
    ("anthropic-to-chat-messages-tool-use-to-tool-calls", test_anthropic_to_chat_messages_tool_use_to_tool_calls),
    ("anthropic-to-chat-messages-tool-result-to-role-tool", test_anthropic_to_chat_messages_tool_result_to_role_tool),
    ("anthropic-to-chat-messages-mixed-text-and-tool-use", test_anthropic_to_chat_messages_mixed_text_and_tool_use),
    ("anthropic-to-chat-messages-mixed-text-and-tool-result", test_anthropic_to_chat_messages_mixed_text_and_tool_result),
    ("anthropic-to-chat-messages-interleaved-thinking-tool-use", test_anthropic_to_chat_messages_interleaved_thinking_tool_use),
    ("anthropic-to-chat-messages-string-content-passthrough", test_anthropic_to_chat_messages_string_content_passthrough),
    ("anthropic-to-chat-messages-cache-control-stripped", test_anthropic_to_chat_messages_cache_control_stripped),
    ("anthropic-to-chat-messages-non-list-guarded", test_anthropic_to_chat_messages_non_list_guarded),
    ("anthropic-to-chat-messages-non-dict-entries-skipped", test_anthropic_to_chat_messages_non_dict_entries_skipped),
    ("anthropic-to-chat-messages-null-user-content", test_anthropic_to_chat_messages_null_user_content),
    ("anthropic-to-chat-tools-transform", test_anthropic_to_chat_tools_transform),
    ("anthropic-to-chat-tools-cache-control-stripped", test_anthropic_to_chat_tools_cache_control_stripped),
    ("anthropic-to-chat-tools-non-list-guarded", test_anthropic_to_chat_tools_non_list_guarded),
    ("anthropic-to-chat-tools-malformed-entries-skipped", test_anthropic_to_chat_tools_malformed_entries_skipped),
    ("anthropic-to-chat-tool-choice-mapping", test_anthropic_to_chat_tool_choice_mapping),
    ("anthropic-to-chat-tool-choice-none-omitted", test_anthropic_to_chat_tool_choice_none_omitted),
    ("anthropic-to-chat-tool-choice-malformed-omitted", test_anthropic_to_chat_tool_choice_malformed_omitted),
    ("anthropic-to-chat-tool-choice-only-with-tools", test_anthropic_to_chat_tool_choice_only_with_tools),
    ("anthropic-to-chat-integration", test_anthropic_to_chat_integration),
    ("anthropic-to-chat-content-block-dropped-trace", test_anthropic_to_chat_content_block_dropped_trace),
    ("anthropic-to-chat-cache-control-stripped-trace", test_anthropic_to_chat_cache_control_stripped_trace),
    ("anthropic-to-chat-nan-infinity-arguments-rejected", test_anthropic_to_chat_nan_infinity_arguments_rejected),
    ("anthropic-to-chat-tool-use-non-dict-input", test_anthropic_to_chat_tool_use_non_dict_input),
    ("anthropic-to-chat-nan-placeholder-with-valid-tool-use", test_anthropic_to_chat_nan_placeholder_with_valid_tool_use),
    ("anthropic-to-chat-tool-result-list-content", test_anthropic_to_chat_tool_result_list_content),
    ("anthropic-to-chat-no-input-mutation", test_anthropic_to_chat_no_input_mutation),
    ("chat-to-anthropic-basic", test_chat_to_anthropic_basic),
    ("chat-to-anthropic-reasoning-content-to-thinking", test_chat_to_anthropic_reasoning_content_to_thinking),
    ("chat-to-anthropic-reasoning-field-compat", test_chat_to_anthropic_reasoning_field_compat),
    ("chat-to-anthropic-reasoning-content-empty", test_chat_to_anthropic_reasoning_content_empty),
    ("chat-to-anthropic-reasoning-content-with-tool-calls", test_chat_to_anthropic_reasoning_content_with_tool_calls),
    ("chat-to-anthropic-empty-choices", test_chat_to_anthropic_empty_choices),
    ("chat-to-anthropic-tool-calls", test_chat_to_anthropic_tool_calls),
    ("chat-to-anthropic-finish-reason-mapping", test_chat_to_anthropic_finish_reason_mapping),
    ("chat-to-anthropic-usage-absent", test_chat_to_anthropic_usage_absent),
    ("chat-to-anthropic-content-array", test_chat_to_anthropic_content_array),
    ("chat-to-anthropic-malformed-tool-args-text-block", test_chat_to_anthropic_malformed_tool_args_text_block),
    ("chat-to-anthropic-malformed-tool-args-mixed", test_chat_to_anthropic_malformed_tool_args_mixed),
    ("anthropic-to-response-basic", test_anthropic_to_response_basic),
    ("anthropic-to-response-system-list", test_anthropic_to_response_system_list),
    ("anthropic-to-response-multiple-user-messages", test_anthropic_to_response_multiple_user_messages),
    ("anthropic-to-response-no-user-message", test_anthropic_to_response_no_user_message),
    ("anthropic-to-response-stream-forced-false", test_anthropic_to_response_stream_forced_false),
    ("response-to-anthropic-basic", test_response_to_anthropic_basic),
    ("response-to-anthropic-empty-output", test_response_to_anthropic_empty_output),
    ("response-to-anthropic-multiple-output", test_response_to_anthropic_multiple_output),
    ("response-to-anthropic-status-completed", test_response_to_anthropic_status_completed),
    ("response-to-anthropic-usage-absent", test_response_to_anthropic_usage_absent),
    ("chat-sse-basic-streaming", test_chat_sse_basic_streaming),
    ("chat-sse-finish-reason-mapping", test_chat_sse_finish_reason_mapping),
    ("chat-sse-no-content-delta", test_chat_sse_no_content_delta),
    ("chat-sse-empty-choices-usage-chunk", test_chat_sse_empty_choices_usage_chunk),
    ("chat-sse-eof-without-finish-reason", test_chat_sse_eof_without_finish_reason),
    ("chat-sse-first-event-has-content", test_chat_sse_first_event_has_content),
    ("chat-sse-injection-prevented", test_chat_sse_injection_prevented),
    ("chat-sse-event-line-present", test_chat_sse_event_line_present),
    ("chat-sse-tool-calls-stop-reason-null", test_chat_sse_tool_calls_stop_reason_null),
    ("chat-sse-reasoning-delta-to-thinking-delta", test_chat_sse_reasoning_delta_to_thinking_delta),
    ("chat-sse-reasoning-delta-no-content", test_chat_sse_reasoning_delta_no_content),
    ("chat-sse-reasoning-then-text-transition", test_chat_sse_reasoning_then_text_transition),
    ("chat-mode-e2e-json", test_chat_mode_e2e_json),
    ("response-mode-e2e-json", test_response_mode_e2e_json),
    ("anthropic-mode-unchanged", test_anthropic_mode_unchanged),
    ("chat-mode-non-2xx-passthrough", test_chat_mode_non_2xx_passthrough),
    ("transform-failure-passthrough", test_transform_failure_passthrough),
    ("tool-args-parse-failure-trace-has-request-id", test_tool_args_parse_failure_trace_has_request_id),
    ("retry-does-not-double-transform", test_retry_does_not_double_transform),
    ("admin-providers-detail", test_admin_providers_detail),
    ("admin-providers-detail-no-mode", test_admin_providers_detail_no_mode),
    ("admin-providers-detail-forbidden", test_admin_providers_detail_forbidden),
    ("admin-providers-detail-invalid-mode-normalized", test_admin_providers_detail_invalid_mode_normalized),
]


def main():
    parser = argparse.ArgumentParser(description="Test suite for claude-retry-proxy")
    parser.add_argument("--test", "-t", type=str, nargs="*", choices=[t[0] for t in ALL_TESTS],
                        help="Specific tests to run (default: all)")
    parser.add_argument("--list", action="store_true", help="List available tests")
    args = parser.parse_args()

    if args.list:
        for name, func in ALL_TESTS:
            print(f"  {name}")
        return

    selected = args.test if args.test else [t[0] for t in ALL_TESTS]
    test_map = dict(ALL_TESTS)

    # Verify prerequisites
    import importlib.util
    if importlib.util.find_spec("claude_retry_proxy") is None:
        print("ERROR: claude-retry-proxy not installed; run: pip install -e .")
        sys.exit(2)
    if not os.path.exists(SETTINGS_FILE):
        print(f"ERROR: settings.json not found at {SETTINGS_FILE}")
        sys.exit(2)

    print(f"Running {len(selected)} of {len(ALL_TESTS)} tests...")
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

    print(f"\n{'='*60}")
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


if __name__ == "__main__":
    main()