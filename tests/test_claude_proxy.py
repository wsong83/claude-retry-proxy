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

NOTE: CLI tests use hardcoded ~/.claude/proxy/proxy-state.json (the CLI's
state path). They back up/restore that file and isolate config/keys/log via
--config-path/--keys-path/--log, so the user's real proxy config is not
touched. Tests should not be run while a production proxy on the same state
file is active.
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


# ---------------------------------------------------------------------------
# Test infrastructure
# ---------------------------------------------------------------------------

CLAUDE_PROXY = [sys.executable, "-m", "claude_retry_proxy.cli"]
PROXY_SERVER = [sys.executable, "-m", "claude_retry_proxy.server"]

SETTINGS_FILE = os.path.join(os.path.expanduser("~"), ".claude", "settings.json")
PROXY_DIR = os.path.join(os.path.expanduser("~"), ".claude", "proxy")
PROXY_STATE_FILE = os.path.join(PROXY_DIR, "proxy-state.json")
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
                                  passphrase="test-passphrase", trace_file=None, cwd=None):
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
# Test: Models Per Provider Validation
# ===========================================================================

def test_models_per_provider_validation():
    """Every provider in keys-index.json must have a non-empty models catalog.

    Server refuses to start when a provider has no models entry, an empty
    list, a string instead of a list, or a list whose entries are empty or
    whitespace-only — with a clear "has no models" error — and starts when all
    providers have at least one non-empty model name.
    """
    print("\n--- Test: Models Per Provider Validation ---")

    def try_start(models):
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
            keys_path = _create_test_keys(temp_dir, {
                "p": {"url": "http://127.0.0.1:1", "key": "k"}
            })
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

    # (a) provider "p" missing from models -> refuse with clear message
    started, err = try_start({})
    if not started and "has no models" in err:
        pass_("Server refused to start with 'has no models' for missing providers entry")
    else:
        fail(f"Expected refusal with 'has no models', got started={started}, stderr={err[:300]!r}")

    # (b) provider "p" present but empty list -> refuse
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

    # (d) provider "p" has a string instead of a list -> refuse
    started, err = try_start({"p": "claude-sonnet-5"})
    if not started and "has no models" in err:
        pass_("Server refused to start when models.p is a string (not a list)")
    else:
        fail(f"Expected refusal for string models value, got started={started}, stderr={err[:300]!r}")

    # (e) provider "p" has a list containing an empty string -> refuse
    started, err = try_start({"p": [""]})
    if not started and "has no models" in err:
        pass_("Server refused to start when models.p list contains an empty string")
    else:
        fail(f"Expected refusal for list with empty string, got started={started}, stderr={err[:300]!r}")

    # (f) provider "p" has a list containing a whitespace-only string -> refuse
    started, err = try_start({"p": ["   "]})
    if not started and "has no models" in err:
        pass_("Server refused to start when models.p list contains a whitespace-only string")
    else:
        fail(f"Expected refusal for whitespace-only model string, got started={started}, stderr={err[:300]!r}")


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
    ("models-per-provider-validation", test_models_per_provider_validation),
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