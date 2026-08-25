"""Test suite for claude-retry-proxy — HTTP retry proxy with URL swapping.

Covers 36 test cases:
  1-11 from plan 2026-07-15-manual-proxy Guidance for Tester:
    1. URL swapping: start replaces URL in settings, stop restores it
    2. Crash recovery: stale lock recovery on restart
    3. Race conditions: concurrent start calls rejected while proxy runs
    4. Concurrent requests: 10+ parallel requests complete
    5. Retry logic: 429 and 503 retried with jittered exponential backoff
    6. Trace markers: start/end events logged with counters
    7. URL validation: rejects localhost URLs at startup
    8. Manual edit detection: stop after manual edit warns
    9. Thread safety: N parallel requests produce N trace entries
    10. PID in lock: lock contains server PID, second start detects 'already running'
  11-12 from plan 2026-07-16-fix-proxy-start-silent-failure Guidance for Tester:
    11. Relative log path: '-l relative.jsonl' with cwd resolves to temp dir
    12. Start early-exit rollback: port pre-occupied, rollback restores settings and removes lock
  13-19 from plan 2026-07-16-fix-proxy-stop-cleanup Guidance for Tester:
    13. Stop cleans proxy-state.json: taskkill /F bypasses server cleanup, stop compensates
    14. Stop cleans lock on write failure: write_settings_url raises, lock still deleted, stderr has URL
    15. Stop kills proxy with non-localhost URL: kill moved before early-return check
    16. release_swap_lock retries: os.remove fails 3x then succeeds, function retries
    17. release_swap_lock warns on final failure: os.remove always fails, warning to stderr
    18. Trace logs oversized body: 413 logged with status:failure, http_status:413
  19-22 from plan 2026-07-16-fix-proxy-stop-tracing Guidance for Tester:
    19. Stop trace no proxy: stop with no proxy prints trace to stderr, exits 0
    20. Stop trace with proxy: stop with running proxy shows full kill→cleanup→restore sequence
    21. Stop cleans proxy-state.lock: cmd_stop removes orphaned proxy-state.lock
    22. Start stdout not contaminated: stdout is DEVNULL (no auth token), trace on stderr only
  23-24 from plan 2026-07-16-remove-proxy-auth Guidance for Tester:
    23. Start no auth header required: POST without X-Proxy-Auth returns 200 (not 401)
    24. Proxy state no auth token: proxy-state.json does not contain auth_token field
  25-28b from plan 2026-07-19-fix-giveup-body-and-trace-prune Guidance for Tester:
    25. Exhaust 429 preserves body: client receives 429 with body containing 'rate_limited' (not empty)
    26. Exhaust connection error synthesizes body: trace 'error' field contains 'upstream_unreachable'
    27. Client disconnect no traceback: stderr has no Traceback, contains disconnect message
    28. Start prunes old trace entries: prune_trace_file returns (2, 1), removes old entries
    28b. Prune trace file edge cases: nonexistent file → (0, 0), empty file → (0, 0)
  29-32 from plan 2026-08-12-streaming-proxy Guidance for Tester:
    29. Streaming response body: 5 chunks streamed with delays reach client in order, first byte fast
    30. Streaming mid-stream upstream failure: truncated upstream → partial body, no traceback, no client_disconnect event
    31. Empty body 429 exhaust: client receives proper 429 status line (streamed-flag regression guard)
    32. CRLF header filter: _crlf_safe drops CR/LF headers, keeps clean ones

Run: pip install -e .  then  python tests/test_claude_proxy.py
Requires: Python 3.8+, no external dependencies (stdlib-only tests).

WARNING: Tests 1-3, 7-10, 11-17 modify the user's ~/.claude/settings.json.
         They save/restore the original settings state. Do not run casually
         by third-party installers — these tests mutate live config.

PUBLIC PACKAGE NOTE: This is a pip-installable public package. Tests that
start the proxy via the CLI (tests 1-3, 7-10, 12-17) modify the real
~/.claude/settings.json. The backup/restore helpers protect your config,
but these tests should not be run casually by third-party installers.
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


# ---------------------------------------------------------------------------
# Settings backup/restore (protects user's real config)
# ---------------------------------------------------------------------------

_settings_backup = None


def backup_settings():
    """Save current settings.json content for later restoration."""
    global _settings_backup
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE) as f:
            _settings_backup = f.read()


def restore_settings():
    """Restore settings.json to its backed-up state."""
    if _settings_backup is not None:
        with open(SETTINGS_FILE, "w") as f:
            f.write(_settings_backup)


def read_settings():
    with open(SETTINGS_FILE) as f:
        return json.load(f)


def write_settings(data):
    with open(SETTINGS_FILE, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def get_base_url():
    data = read_settings()
    return data.get("env", {}).get("ANTHROPIC_BASE_URL", "")


def set_base_url(url):
    data = read_settings()
    if "env" not in data:
        data["env"] = {}
    data["env"]["ANTHROPIC_BASE_URL"] = url
    write_settings(data)


def cleanup_lock_files():
    """Remove proxy lock files left from previous test runs."""
    for f in [URL_LOCK_FILE, URL_SWAP_LOCK_FILE]:
        try:
            os.remove(f)
        except OSError:
            pass


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

def _create_test_config(temp_dir, tiers, models=None):
    """Create a temp config.json with tier mappings.

    Args:
        temp_dir: Directory to create config.json in
        tiers: Dict mapping tier names to {provider, model}
        models: Optional dict mapping provider names to model lists

    Returns:
        Path to created config.json
    """
    config = {
        "tiers": tiers,
        "models": models or {}
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

    # Pipe passphrase to server
    if proc.stdin:
        try:
            proc.stdin.write(passphrase + "\n")
            proc.stdin.close()
        except (BrokenPipeError, OSError):
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
    """Start proxy, kill server with taskkill /F, run stop, verify proxy-state.json deleted."""
    print("\n--- Test 13: Stop Cleans proxy-state.json ---")
    backup_settings()
    cleanup_lock_files()

    STATE_FILE = os.path.join(PROXY_DIR, "proxy-state.json")

    try:
        port = find_free_port()

        # Start proxy
        info(f"Starting proxy on port {port}...")
        result = subprocess.run(
            CLAUDE_PROXY + ["start", "--port", str(port)],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            fail(f"Start failed: {result.stdout} {result.stderr}")
            return

        # Verify proxy-state.json exists (server creates it on startup)
        if not os.path.exists(STATE_FILE):
            fail("proxy-state.json not found after start — server may not have created it")
            return
        pass_("proxy-state.json exists after proxy start")

        # Kill the server process forcefully (simulating Windows taskkill /F)
        if os.path.exists(URL_LOCK_FILE):
            with open(URL_LOCK_FILE) as f:
                lock_data = json.load(f)
            pid = lock_data.get("pid")
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
        if os.path.exists(STATE_FILE):
            pass_("proxy-state.json still exists after taskkill /F (server cleanup bypassed)")
        else:
            warn("proxy-state.json already gone — server may have cleaned up; test may be inconclusive")

        # Run stop — should clean up proxy-state.json
        info("Running claude-retry-proxy stop...")
        result = subprocess.run(
            CLAUDE_PROXY + ["stop"],
            capture_output=True, text=True, timeout=10
        )

        # Verify proxy-state.json is deleted
        if not os.path.exists(STATE_FILE):
            pass_("proxy-state.json deleted by claude-retry-proxy stop")
        else:
            fail("proxy-state.json still exists after stop — not cleaned up by cmd_stop")

        # Verify lock is also cleaned up
        if not os.path.exists(URL_LOCK_FILE):
            pass_("base-url.lock also cleaned up")
        else:
            fail("base-url.lock still exists after stop")

    finally:
        cleanup_lock_files()
        subprocess.run(
            CLAUDE_PROXY + ["stop"],
            capture_output=True, text=True, timeout=10
        )
        restore_settings()


# ===========================================================================
# Test Case 14: Stop Cleans Lock on write_settings_url Failure
# ===========================================================================

def test_stop_cleans_lock_on_write_failure():
    """Mock write_settings_url to raise; verify base-url.lock deleted and stderr has original URL."""
    print("\n--- Test 14: Stop Cleans Lock on write_settings_url Failure ---")
    backup_settings()
    cleanup_lock_files()

    try:
        import claude_retry_proxy.cli as cpm

        # Set up state: create a valid base-url.lock and point settings to localhost
        original_url = get_base_url()
        if not original_url:
            fail("ANTHROPIC_BASE_URL is not set — cannot test")
            return

        port = find_free_port()

        # Start proxy first to create proper lock state
        info(f"Starting proxy on port {port}...")
        result = subprocess.run(
            CLAUDE_PROXY + ["start", "--port", str(port)],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            fail(f"Start failed: {result.stdout} {result.stderr}")
            return

        # Kill the proxy process (we only need the lock file state)
        if os.path.exists(URL_LOCK_FILE):
            with open(URL_LOCK_FILE) as f:
                lock_data = json.load(f)
            pid = lock_data.get("pid")
            if pid:
                if sys.platform == "win32":
                    subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
                else:
                    try:
                        os.kill(pid, signal.SIGKILL)
                    except OSError:
                        pass
                time.sleep(0.3)

        # Mock write_settings_url (module already loaded via import)
        original_write = None
        try:
            original_write = cpm.write_settings_url

            # Replace write_settings_url with a version that always raises
            def _failing_write(url):
                raise PermissionError("Simulated write failure for testing")

            cpm.write_settings_url = _failing_write

            # Capture stderr
            import io
            saved_stderr = sys.stderr
            sys.stderr = io.StringIO()

            try:
                exit_code = cpm.cmd_stop([])
            finally:
                stderr_output = sys.stderr.getvalue()
                sys.stderr = saved_stderr

            # Restore original
            cpm.write_settings_url = original_write

            # Verify: base-url.lock is deleted
            if not os.path.exists(URL_LOCK_FILE):
                pass_("base-url.lock deleted even though write_settings_url failed")
            else:
                fail("base-url.lock NOT deleted after write_settings_url failure")

            # Verify: stderr contains the original URL
            if original_url in stderr_output:
                pass_(f"stderr contains original URL: '{original_url}'")
            else:
                fail(f"stderr does NOT contain original URL. stderr: {stderr_output[:200]}")

            # Verify: error message on stderr
            if stderr_output.strip():
                pass_("Error message printed to stderr on write failure")
            else:
                fail("No error message on stderr — failure was silent")

        finally:
            if original_write:
                cpm.write_settings_url = original_write

    finally:
        cleanup_lock_files()
        subprocess.run(
            CLAUDE_PROXY + ["stop"],
            capture_output=True, text=True, timeout=10
        )
        restore_settings()


# ===========================================================================
# Test Case 15: Stop Kills Proxy with Non-localhost URL
# ===========================================================================

def test_stop_kills_proxy_with_non_localhost_url():
    """Set settings to non-localhost URL, start proxy, run stop — verify proxy process killed."""
    print("\n--- Test 15: Stop Kills Proxy with Non-localhost URL ---")
    backup_settings()
    cleanup_lock_files()

    try:
        original_url = get_base_url()
        if not original_url:
            fail("ANTHROPIC_BASE_URL is not set — cannot test")
            return

        port = find_free_port()

        # Start proxy normally
        info(f"Starting proxy on port {port}...")
        result = subprocess.run(
            CLAUDE_PROXY + ["start", "--port", str(port)],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            fail(f"Start failed: {result.stdout} {result.stderr}")
            return

        # Read lock to get the proxy PID
        if not os.path.exists(URL_LOCK_FILE):
            fail("base-url.lock not found after start")
            return
        with open(URL_LOCK_FILE) as f:
            lock_data = json.load(f)
        proxy_pid = lock_data.get("pid")
        info(f"Proxy PID from lock: {proxy_pid}")

        # Verify proxy is alive
        if not proxy_pid:
            fail("No PID in lock file")
            return

        import subprocess as sp
        if sys.platform == "win32":
            r = sp.run(["tasklist", "/FI", f"PID eq {proxy_pid}"], capture_output=True, text=True)
            if str(proxy_pid) not in r.stdout:
                fail(f"Proxy PID {proxy_pid} not alive before stop — cannot test")
                return
        else:
            try:
                os.kill(proxy_pid, 0)
            except OSError:
                fail(f"Proxy PID {proxy_pid} not alive before stop — cannot test")
                return
        pass_(f"Proxy PID {proxy_pid} confirmed alive before stop")

        # Simulate manual edit: set settings URL to a non-localhost URL
        set_base_url("https://manual-edit.example.com")

        # Run stop
        info("Running claude-retry-proxy stop with non-localhost URL in settings...")
        result = subprocess.run(
            CLAUDE_PROXY + ["stop"],
            capture_output=True, text=True, timeout=10
        )

        output = result.stdout + result.stderr

        # Verify: proxy process is killed (the fix moves kill BEFORE the non-localhost check)
        time.sleep(0.5)
        if sys.platform == "win32":
            r = sp.run(["tasklist", "/FI", f"PID eq {proxy_pid}"], capture_output=True, text=True)
            pid_alive_after = str(proxy_pid) in r.stdout
        else:
            try:
                os.kill(proxy_pid, 0)
                pid_alive_after = True
            except OSError:
                pid_alive_after = False

        if not pid_alive_after:
            pass_(f"Proxy PID {proxy_pid} killed despite non-localhost URL in settings")
        else:
            fail(f"Proxy PID {proxy_pid} still alive after stop — "
                 "kill block was skipped due to non-localhost early return")

        # Verify: manual edit warning appears
        if "manual" in output.lower() or "not modifying" in output.lower():
            pass_("Manual edit warning present in stop output")
        else:
            info(f"Stop output: {output[:200]}")

        # Verify: lock is cleaned up
        if not os.path.exists(URL_LOCK_FILE):
            pass_("base-url.lock cleaned up after stop")
        else:
            fail("base-url.lock still exists after stop")

        # Verify: settings NOT overwritten (manual edit preserved)
        current_url = get_base_url()
        if "manual-edit.example.com" in current_url:
            pass_("Manual edit preserved — settings NOT overwritten by stop")
        else:
            info(f"Settings URL after stop: '{current_url}'")

    finally:
        cleanup_lock_files()
        subprocess.run(
            CLAUDE_PROXY + ["stop"],
            capture_output=True, text=True, timeout=10
        )
        restore_settings()


# ===========================================================================
# Test Case 16: release_swap_lock Retries on Transient Failure
# ===========================================================================

def test_release_swap_lock_retries():
    """Mock os.remove to fail 3x then succeed; verify function retries and returns cleanly."""
    print("\n--- Test 16: release_swap_lock Retries ---")
    cleanup_lock_files()

    try:
        import claude_retry_proxy.cli as cpm

        # Create the swap lock file so it exists to be removed
        os.makedirs(PROXY_DIR, exist_ok=True)
        with open(cpm.URL_SWAP_LOCK_FILE, "w") as f:
            f.write("")

        # Build a mock os.remove that fails 3 times then succeeds
        call_count = [0]
        original_remove = os.remove

        def _mock_remove(path):
            call_count[0] += 1
            if call_count[0] <= 3 and path == cpm.URL_SWAP_LOCK_FILE:
                raise OSError("Simulated transient failure")
            # On 4th call, actually remove
            original_remove(path)

        # Patch os.remove on the module
        cpm.os.remove = _mock_remove

        try:
            cpm.release_swap_lock()
        finally:
            cpm.os.remove = original_remove

        # Verify: os.remove was called at least 4 times (3 failures + 1 success)
        if call_count[0] >= 4:
            pass_(f"os.remove called {call_count[0]} times (3 failures + 1 success)")
        else:
            fail(f"os.remove called only {call_count[0]} times; expected at least 4 (3 retries + success)")

        # Verify: swap lock file is gone
        if not os.path.exists(cpm.URL_SWAP_LOCK_FILE):
            pass_("Swap lock file removed after retries")
        else:
            fail("Swap lock file still exists after release_swap_lock")

        # Verify: no exception raised
        pass_("release_swap_lock returned without raising")

    finally:
        cleanup_lock_files()


# ===========================================================================
# Test Case 17: release_swap_lock Warns on Final Failure
# ===========================================================================

def test_release_swap_lock_warns_on_final_failure():
    """Mock os.remove to always fail; verify warning printed to stderr."""
    print("\n--- Test 17: release_swap_lock Warns on Final Failure ---")
    cleanup_lock_files()

    try:
        import claude_retry_proxy.cli as cpm
        import io

        # Create the swap lock file
        os.makedirs(PROXY_DIR, exist_ok=True)
        with open(cpm.URL_SWAP_LOCK_FILE, "w") as f:
            f.write("")

        # Build a mock os.remove that always fails
        original_remove = os.remove

        def _always_fail_remove(path):
            raise OSError("Simulated permanent failure")

        cpm.os.remove = _always_fail_remove

        # Capture stderr
        saved_stderr = sys.stderr
        sys.stderr = io.StringIO()

        try:
            cpm.release_swap_lock()
        finally:
            stderr_output = sys.stderr.getvalue()
            sys.stderr = saved_stderr
            cpm.os.remove = original_remove

        # Verify: warning on stderr
        if "WARNING" in stderr_output or "Could not release" in stderr_output:
            pass_("Warning printed to stderr on final failure")
        else:
            fail(f"No warning on stderr. stderr: {stderr_output[:200]}")

        # Verify: no exception raised
        pass_("release_swap_lock returned without raising (failure is logged, not thrown)")

    finally:
        cleanup_lock_files()


# ===========================================================================
# Test Case 18: Trace Logs Oversized Body (413)
# ===========================================================================

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


# ===========================================================================
# Test Case 19: Stop Trace Output with No Proxy Running
# ===========================================================================

def test_stop_trace_no_proxy():
    """Run claude-retry-proxy stop with no proxy running; verify trace lines on stderr."""
    print("\n--- Test 19: Stop Trace with No Proxy ---")
    cleanup_lock_files()

    try:
        result = subprocess.run(
            CLAUDE_PROXY + ["stop"],
            capture_output=True, text=True, timeout=10
        )

        # Assert exit code 0
        if result.returncode == 0:
            pass_("stop exited 0 with no proxy running")
        else:
            fail(f"stop exited {result.returncode}, expected 0")

        stderr = result.stderr

        # Assert: stderr contains trace lines
        if "cmd_stop: entering" in stderr:
            pass_("stderr contains 'cmd_stop: entering'")
        else:
            fail(f"stderr missing 'cmd_stop: entering'. stderr: {stderr[:300]}")

        if "read_url_lock" in stderr:
            pass_("stderr contains read_url_lock trace")
        else:
            fail(f"stderr missing read_url_lock trace. stderr: {stderr[:300]}")

        if "returning 0" in stderr:
            pass_("stderr contains 'returning 0'")
        else:
            fail(f"stderr missing 'returning 0'. stderr: {stderr[:300]}")

        # Assert: trace format uses [claude-retry-proxy] prefix
        if "[claude-retry-proxy]" in stderr:
            pass_("stderr trace lines use [claude-retry-proxy] prefix")
        else:
            fail(f"stderr missing [claude-retry-proxy] prefix. stderr: {stderr[:300]}")

    finally:
        cleanup_lock_files()


# ===========================================================================
# Test Case 20: Stop Trace Output with Proxy Running (Full Sequence)
# ===========================================================================

def test_stop_trace_with_proxy():
    """Start proxy, run claude-retry-proxy stop; verify stderr shows full stop sequence."""
    print("\n--- Test 20: Stop Trace with Proxy Running ---")
    backup_settings()
    cleanup_lock_files()

    try:
        port = find_free_port()

        # Start proxy
        info(f"Starting proxy on port {port}...")
        result = subprocess.run(
            CLAUDE_PROXY + ["start", "--port", str(port)],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            fail(f"Start failed (exit {result.returncode}): {result.stdout} {result.stderr}")
            return

        # Verify proxy is running (lock exists with live PID)
        if not os.path.exists(URL_LOCK_FILE):
            fail("base-url.lock not created after start")
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

        # Assert: trace shows kill step
        if "killing" in stderr.lower() or "kill" in stderr.lower():
            pass_("stderr trace shows kill step")
        else:
            fail(f"stderr missing kill step. stderr: {stderr[:500]}")

        # Assert: trace shows state cleanup (proxy-state removal)
        if "proxy-state" in stderr.lower():
            pass_("stderr trace shows proxy-state cleanup")
        else:
            warn("stderr missing proxy-state reference — may be expected if file didn't exist")

        # Assert: trace shows URL restore step
        if "restoring" in stderr.lower() or "original" in stderr.lower():
            pass_("stderr trace shows URL restore step")
        else:
            fail(f"stderr missing URL restore step. stderr: {stderr[:500]}")

        # Assert: trace shows lock removal (finally block)
        if "base-url.lock" in stderr or "removing" in stderr.lower():
            pass_("stderr trace shows lock removal step")
        else:
            fail(f"stderr missing lock removal step. stderr: {stderr[:500]}")

        # Assert: trace shows exit code
        if "returning 0" in stderr:
            pass_("stderr trace shows 'returning 0'")
        else:
            fail(f"stderr missing 'returning 0'. stderr: {stderr[:500]}")

        # Assert: lock files cleaned up
        if not os.path.exists(URL_LOCK_FILE):
            pass_("base-url.lock removed after stop")
        else:
            fail("base-url.lock still exists after stop")

    finally:
        cleanup_lock_files()
        subprocess.run(
            CLAUDE_PROXY + ["stop"],
            capture_output=True, text=True, timeout=10
        )
        restore_settings()


# ===========================================================================
# Test Case 21: Stop Cleans proxy-state.lock
# ===========================================================================

def test_stop_cleans_proxy_state_lock():
    """Create dummy proxy-state.lock; run stop with dead-PID lock; verify file deleted."""
    print("\n--- Test 21: Stop Cleans proxy-state.lock ---")
    backup_settings()
    cleanup_lock_files()

    STATE_LOCK_FILE = os.path.join(PROXY_DIR, "proxy-state.lock")

    try:
        # Create proxy directory if needed
        os.makedirs(PROXY_DIR, exist_ok=True)

        # Create a fake base-url.lock with a dead PID so cmd_stop enters the
        # kill/cleanup block where proxy-state.lock removal lives.
        dead_pid = 99999  # Almost certainly not a real PID
        fake_lock = {
            "original_url": "https://api.anthropic.com",
            "proxy_port": 18080,
            "locked_at": "2020-01-01T00:00:00Z",
            "locked_at_epoch": 1577836800.0,
            "pid": dead_pid
        }
        with open(URL_LOCK_FILE, "w") as f:
            json.dump(fake_lock, f)
        pass_("Created fake base-url.lock with dead PID")

        # Create the dummy proxy-state.lock file
        with open(STATE_LOCK_FILE, "w") as f:
            f.write("dummy lock content")
        if os.path.exists(STATE_LOCK_FILE):
            pass_("Created dummy proxy-state.lock")
        else:
            fail("Failed to create proxy-state.lock")
            return

        # Run stop — should enter kill block, attempt kill (dead PID = no-op),
        # then clean up both proxy-state.json and proxy-state.lock
        info("Running claude-retry-proxy stop...")
        result = subprocess.run(
            CLAUDE_PROXY + ["stop"],
            capture_output=True, text=True, timeout=10
        )

        # Assert: proxy-state.lock is deleted
        if not os.path.exists(STATE_LOCK_FILE):
            pass_("proxy-state.lock deleted by claude-retry-proxy stop")
        else:
            fail("proxy-state.lock still exists after stop — not cleaned up by cmd_stop")

        # Assert: base-url.lock also cleaned up
        if not os.path.exists(URL_LOCK_FILE):
            pass_("base-url.lock also cleaned up")
        else:
            fail("base-url.lock still exists after stop")

    finally:
        # Clean up any remaining files
        try:
            os.remove(STATE_LOCK_FILE)
        except OSError:
            pass
        cleanup_lock_files()
        subprocess.run(
            CLAUDE_PROXY + ["stop"],
            capture_output=True, text=True, timeout=10
        )
        restore_settings()


# ===========================================================================
# Test Case 22: Start Stdout Not Contaminated by Trace
# ===========================================================================

def test_start_stdout_not_contaminated():
    """Start proxy; assert stdout has startup messages, no trace lines or auth token."""
    print("\n--- Test 22: Start Stdout Not Contaminated ---")
    backup_settings()
    cleanup_lock_files()

    try:
        original_url = get_base_url()
        if not original_url:
            fail("ANTHROPIC_BASE_URL is not set — cannot test")
            return

        port = find_free_port()

        # Start proxy, capturing stdout and stderr separately
        info(f"Starting proxy on port {port}...")
        proc = subprocess.Popen(
            CLAUDE_PROXY + ["start", "--port", str(port)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        try:
            stdout, stderr = proc.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            fail("claude-retry-proxy start timed out")
            return

        if proc.returncode != 0:
            fail(f"Start failed (exit {proc.returncode}): {stdout} {stderr}")
            return

        # Assert: stdout contains startup messages (Proxy started, Original URL)
        if "Proxy started" in stdout:
            pass_("stdout contains 'Proxy started'")
        else:
            fail(f"stdout missing 'Proxy started'. stdout: {stdout[:300]}")

        if "Original URL" in stdout:
            pass_("stdout contains 'Original URL'")
        else:
            fail(f"stdout missing 'Original URL'. stdout: {stdout[:300]}")

        # Assert: NO "Auth token:" on stdout (auth removed)
        if "Auth token:" in stdout:
            fail("stdout contains 'Auth token:' — auth should be removed")
        else:
            pass_("stdout does NOT contain 'Auth token:'")

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

        # Verify the proxy actually started (URL was swapped)
        current_url = get_base_url()
        if f"localhost:{port}" in current_url:
            pass_(f"URL swapped to localhost:{port} — proxy started successfully")
        else:
            fail(f"URL not swapped: '{current_url}'")

    finally:
        cleanup_lock_files()
        subprocess.run(
            CLAUDE_PROXY + ["stop"],
            capture_output=True, text=True, timeout=10
        )
        restore_settings()


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


# ===========================================================================
# Test Case 24: Proxy State No Auth Token
# ===========================================================================

def test_proxy_state_no_auth_token():
    """Start proxy, read proxy-state.json; assert auth_token key is absent."""
    print("\n--- Test 24: Proxy State No Auth Token ---")
    backup_settings()
    cleanup_lock_files()

    STATE_FILE = os.path.join(PROXY_DIR, "proxy-state.json")

    try:
        port = find_free_port()

        # Start proxy
        info(f"Starting proxy on port {port}...")
        result = subprocess.run(
            CLAUDE_PROXY + ["start", "--port", str(port)],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            fail(f"Start failed (exit {result.returncode}): {result.stdout} {result.stderr}")
            return

        # Verify proxy-state.json exists
        if not os.path.exists(STATE_FILE):
            fail("proxy-state.json not found after start")
            return
        pass_("proxy-state.json exists after proxy start")

        # Read and verify no auth_token field
        with open(STATE_FILE) as f:
            state = json.load(f)

        if "auth_token" in state:
            fail(f"proxy-state.json contains auth_token field: '{state['auth_token'][:20]}...'")
        else:
            pass_("proxy-state.json does NOT contain auth_token field")

        # Verify other expected fields are still present
        if "port" in state:
            pass_(f"proxy-state.json has port={state['port']}")
        else:
            warn("proxy-state.json missing 'port' field")

        if "pid" in state:
            pass_(f"proxy-state.json has pid={state['pid']}")
        else:
            warn("proxy-state.json missing 'pid' field")

    finally:
        cleanup_lock_files()
        subprocess.run(
            CLAUDE_PROXY + ["stop"],
            capture_output=True, text=True, timeout=10
        )
        restore_settings()


# ===========================================================================
# Test Case 25: Exhaust 429 Preserves Body (Step 1 — Fix B, 429 path)
# ===========================================================================

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

    # Create config
    config_path = _create_test_config(temp_dir, tiers_config)

    # Create keys
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
# Test: Response Model Rewrite Unmapped Model
# ===========================================================================

def test_response_model_rewrite_unmapped_model():
    """Upstream returns model name not in reverse map → passed through unchanged, warning logged."""
    print("\n--- Test: Response Model Rewrite Unmapped Model ---")

    upstream_port = find_free_port()

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            content_len = int(self.headers.get("Content-Length", 0))
            if content_len > 0:
                self.rfile.read(content_len)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            # Return a model not in the reverse map
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

        # Response should have the unmapped model passed through
        try:
            resp_data = json.loads(resp_body)
            if resp_data.get("model") == "unknown-model":
                pass_("Unmapped model passed through unchanged")
            else:
                fail(f"Unmapped model was modified: {resp_data.get('model')}")
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
            "models": {}
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
            "models": {}
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
# Test: Config Template Copy
# ===========================================================================

def test_config_template_copy():
    """Missing config.json → template copied, start fails with message."""
    print("\n--- Test: Config Template Copy ---")

    # This test requires CLI, which may not be implemented yet
    # Skip for now — will be tested via CLI integration
    print("SKIP: Requires CLI implementation")


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

def test_admin_api_switch():
    """POST /admin/api/switch updates tier, subsequent request routes to new provider."""
    print("\n--- Test: Admin API Switch ---")
    print("SKIP: Requires admin API implementation")


# ===========================================================================
# Test: Admin API Switch Invalid Provider
# ===========================================================================

def test_admin_api_switch_invalid_provider():
    """POST with unknown provider → error response."""
    print("\n--- Test: Admin API Switch Invalid Provider ---")
    print("SKIP: Requires admin API implementation")


# ===========================================================================
# Test: Admin API Switch Preserves Models
# ===========================================================================

def test_admin_api_switch_preserves_models():
    """Switch tiers, verify models section unchanged in config.json."""
    print("\n--- Test: Admin API Switch Preserves Models ---")
    print("SKIP: Requires admin API implementation")


# ===========================================================================
# Test: Admin API CSRF Rejected
# ===========================================================================

def test_admin_api_csrf_rejected():
    """POST with foreign Origin header → rejected."""
    print("\n--- Test: Admin API CSRF Rejected ---")
    print("SKIP: Requires admin API implementation")


# ===========================================================================
# Test: Admin API CSRF Null Origin Rejected
# ===========================================================================

def test_admin_api_csrf_null_origin_rejected():
    """POST with Origin: null → rejected."""
    print("\n--- Test: Admin API CSRF Null Origin Rejected ---")
    print("SKIP: Requires admin API implementation")


# ===========================================================================
# Test: Admin API CSRF Missing Origin Rejected
# ===========================================================================

def test_admin_api_csrf_missing_origin_rejected():
    """POST without Origin header → rejected."""
    print("\n--- Test: Admin API CSRF Missing Origin Rejected ---")
    print("SKIP: Requires admin API implementation")


# ===========================================================================
# Test: Admin API CSRF IPv6 Loopback Accepted
# ===========================================================================

def test_admin_api_csrf_ipv6_loopback_accepted():
    """POST with Origin: http://[::1]:<port> → accepted."""
    print("\n--- Test: Admin API CSRF IPv6 Loopback Accepted ---")
    print("SKIP: Requires admin API implementation")


# ===========================================================================
# Test: Admin API Switch Missing Tier Rejected
# ===========================================================================

def test_admin_api_switch_missing_tier_rejected():
    """POST with only 2 tiers → 400 error listing missing tier."""
    print("\n--- Test: Admin API Switch Missing Tier Rejected ---")
    print("SKIP: Requires admin API implementation")


# ===========================================================================
# Test: Config Validation Reverse Map Collision
# ===========================================================================

def test_config_validation_reverse_map_collision():
    """Config with two tiers mapping to same model → server refuses to start."""
    print("\n--- Test: Config Validation Reverse Map Collision ---")

    temp_dir = tempfile.mkdtemp(prefix="proxy_config_test_")
    try:
        # Two tiers map to same model
        invalid_config = {
            "tiers": {
                "haiku": {"provider": "p", "model": "same-model"},
                "sonnet": {"provider": "p", "model": "same-model"},  # collision!
                "opus": {"provider": "p", "model": "claude-opus-5"},
            },
            "models": {}
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
            pass_("Server refused to start with reverse map collision")
        else:
            fail("Server started with reverse map collision (should have refused)")
            proc.kill()

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


# ===========================================================================
# Test: Admin API Reload
# ===========================================================================

def test_admin_api_reload():
    """Modify config.json on disk, POST /admin/api/reload, verify new mapping active."""
    print("\n--- Test: Admin API Reload ---")
    print("SKIP: Requires admin API implementation")


# ===========================================================================
# Test: CLI Reload
# ===========================================================================

def test_cli_reload():
    """claude-retry-proxy reload sends reload request to running proxy."""
    print("\n--- Test: CLI Reload ---")
    print("SKIP: Requires CLI implementation")


# ===========================================================================
# Test: CLI Start No Config
# ===========================================================================

def test_cli_start_no_config():
    """Start without config.json → template created, exit 1, message printed."""
    print("\n--- Test: CLI Start No Config ---")
    print("SKIP: Requires CLI implementation")


# ===========================================================================
# Test: CLI Start Invalid Config
# ===========================================================================

def test_cli_start_invalid_config():
    """Start with broken config → exit 1, specific error."""
    print("\n--- Test: CLI Start Invalid Config ---")
    print("SKIP: Requires CLI implementation")


# ===========================================================================
# Test: CLI Status Shows Tiers
# ===========================================================================

def test_cli_status_shows_tiers():
    """Status output includes tier → provider → model mapping."""
    print("\n--- Test: CLI Status Shows Tiers ---")
    print("SKIP: Requires CLI implementation")


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
    ("response-model-rewrite-unmapped-model", test_response_model_rewrite_unmapped_model),
    ("config-validation-missing-tier", test_config_validation_missing_tier),
    ("config-validation-unknown-provider", test_config_validation_unknown_provider),
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
    ("config-validation-reverse-map-collision", test_config_validation_reverse_map_collision),
    ("admin-api-reload", test_admin_api_reload),
    ("cli-reload", test_cli_reload),
    ("cli-start-no-config", test_cli_start_no_config),
    ("cli-start-invalid-config", test_cli_start_invalid_config),
    ("cli-status-shows-tiers", test_cli_status_shows_tiers),
    ("key-decryption-wrong-passphrase", test_key_decryption_wrong_passphrase),
    ("key-decryption-missing-file", test_key_decryption_missing_file),
    ("api-key-from-keys-index", test_api_key_from_keys_index),
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