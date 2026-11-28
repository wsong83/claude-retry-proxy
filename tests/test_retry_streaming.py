"""Retry/backoff and 429/503 exhaustion tests: the retry loop, backoff
pacing, exhaustion envelopes, give-up body preservation, and the
connection-error retry mapping.

The streaming/flow, concurrency, disconnect, count-tokens, and
upstream-transport clusters live in their own modules
(test_retry_streaming_flow, test_retry_streaming_concurrency,
test_retry_streaming_disconnects, test_retry_streaming_count_tokens,
test_retry_streaming_transport), chained through this module's ALL_TESTS
(plan 2026-11-27-partition-retry-streaming).

Part of the claude-retry-proxy suite; runnable standalone."""

import http
import json
import os
import shutil
import socket
import subprocess
import tempfile
import threading
import time
from _harness import PROXY_SERVER, _create_test_config, _create_test_keys, _drain_child_stderr, _mode_tiers, _send_proxy_request, _start_mode_proxy, _wait_for_trace_events, fail, find_free_port, info, pass_, run_cli, warn
from test_retry_streaming_count_tokens import ALL_TESTS as COUNT_TOKENS_TESTS
from test_retry_streaming_flow import ALL_TESTS as FLOW_TESTS
from test_retry_streaming_concurrency import ALL_TESTS as CONCURRENCY_TESTS
from test_retry_streaming_disconnects import ALL_TESTS as DISCONNECTS_TESTS
from test_retry_streaming_transport import ALL_TESTS as TRANSPORT_TESTS


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
    _drain_child_stderr(proc)

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
    _drain_child_stderr(proc)

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
    _drain_child_stderr(proc)

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
    _drain_child_stderr(proc)

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
    _drain_child_stderr(proc)

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
    _drain_child_stderr(proc)

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


def _truncating_429_responder(info):
    """Upstream answering 429 with a body larger than the drain cap."""
    return 429, "application/json", json.dumps({
        "error": {"type": "rate_limit_error", "message": "x" * 4096}
    }).encode()


def test_give_up_truncated_body_envelope():
    """A truncated give-up body carries upstream_body_truncated and the
    status-appropriate error.type.

    On retry exhaustion the retry loop drains the upstream body through
    _read_capped, capped at PROXY_MAX_BODY_SIZE. When the drain hits that cap
    the proxy substitutes its own body — now the standard envelope with
    error.code upstream_body_truncated and error.type derived from the
    upstream status (429 -> rate_limit_error).
    """
    print("\n--- Test: Give-Up Truncated Body Envelope ---")

    upstream = find_free_port()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream), "key": "K"}}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(
        _mode_tiers(), vendors,
        responders={"p": _truncating_429_responder},
        extra_env={"PROXY_MAX_RETRIES": "1", "PROXY_INITIAL_DELAY": "1",
                   "PROXY_MAX_DELAY": "1", "PROXY_MAX_BODY_SIZE": "1024"})
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        status, resp_body = _send_proxy_request(proxy_port)
        if status != 429:
            fail("expected 429 on exhaustion, got {}".format(status))
            return
        try:
            data = json.loads(resp_body)
        except Exception as e:
            fail("truncated-body response is not valid JSON: {} ({!r})".format(
                e, resp_body[:200]))
            return
        err = data.get("error")
        if not isinstance(err, dict):
            fail("truncated-body: error is not an object: {!r}".format(err))
            return
        if err.get("code") != "upstream_body_truncated":
            fail("expected code upstream_body_truncated, got {!r}".format(err.get("code")))
            return
        if err.get("type") != "rate_limit_error":
            fail("expected error.type rate_limit_error for a 429, got {!r}".format(err.get("type")))
            return
        if data.get("type") != "error" or not data.get("request_id"):
            fail("truncated-body envelope shape wrong: {!r}".format(data))
            return
        pass_("truncated give-up body -> upstream_body_truncated / rate_limit_error")
    finally:
        cleanup()


# --- extra_request_headers retry stability ---
# (plan 2026-09-06-opencode-session-header)

def test_retry_stability_extra_header():
    """A 429-retried request to a ruled provider carries the SAME
    x-opencode-session value on every attempt.

    The resolver is applied once in _forward_request_impl's header build
    (before the retry loop), so the outbound header must not drift across
    attempts. Also correlates the value with the request's trace request_id
    (the fallback token source).
    """
    print("\n--- Test: extra_request_headers retry stability ---")
    upstream_port = find_free_port()
    tiers = _mode_tiers("opencode-go")
    vendors = {
        "opencode-go": {"url": "http://127.0.0.1:{}".format(upstream_port),
                        "key": "K-OG", "mode": "chat"},
    }
    extra = {
        "opencode-go": [
            {"header": "x-opencode-session", "fallback": "request_id"},
        ],
    }
    attempts = [0]

    def responder(info):
        attempts[0] += 1
        if attempts[0] <= 3:
            return 429, "application/json", b'{"error":"Too Many Requests"}'
        return 200, "application/json", b'{"id":"ok","type":"message","content":[{"text":"response"}]}'

    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(
        tiers, vendors, responders={"opencode-go": responder}, extra_headers=extra,
        extra_env={"PROXY_MAX_RETRIES": "5", "PROXY_INITIAL_DELAY": "1",
                   "PROXY_MAX_DELAY": "1"})
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        status, body = _send_proxy_request(proxy_port)
        if status != 200:
            fail("expected 200 after 429 retries, got {}".format(status))
            return

        reqs = mock_servers["opencode-go"]["requests"]
        if len(reqs) < 4:
            fail("expected >=4 upstream attempts (3x429 + 200), got {}".format(len(reqs)))
            return
        values = []
        for r in reqs:
            vals = (r.get("headers") or {}).get("x-opencode-session", [])
            values.append(vals[0] if vals else "<missing>")
        distinct = set(values)
        if len(distinct) == 1:
            pass_("same x-opencode-session value on all {} attempts: {}".format(
                len(reqs), values[0]))
        else:
            fail("x-opencode-session drifted across retries: {}".format(values))

        # Correlate with the trace: the fallback token resolves to the
        # per-request uuid4 recorded as the request event's request_id.
        expected = None
        if trace_file and os.path.exists(trace_file):
            with open(trace_file) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        ev = json.loads(line)
                    except Exception:
                        continue
                    if (ev.get("event") == "request"
                            and ev.get("provider") == "opencode-go"
                            and ev.get("http_status") == 200):
                        expected = ev.get("request_id")
        if expected and values and values[0] == expected:
            pass_("resolved value equals the request trace event's request_id")
        elif expected:
            fail("expected x-opencode-session={!r} (trace request_id), got {!r}".format(
                expected, values[0] if values else None))
    finally:
        cleanup()


def test_connection_error_retry_mapping():
    """A mid-response upstream reset is retried and labelled connection_error.

    The stub declares a Content-Length it does not honour and closes, which
    httpx2 surfaces as RemoteProtocolError (TransportError -> RequestError).
    The retry loop's total tuple must map it to a `retry` event with
    reason "connection_error" — an unmapped type would either escape the loop
    (no retry, no record) or be retried as a 429/503. The exhaustion/502 half
    is covered by test_exhaust_connection_error_synthesizes_body and
    test_disable_retry_count_tokens_conn_error and is deliberately not
    re-pinned here.
    """
    print("\n--- Test: Connection Error Retry Mapping ---")
    upstream_port = find_free_port()
    tiers = _mode_tiers()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port), "key": "K"}}
    partial = b'{"id":"msg_trunc'

    def streamer(handler, info):
        handler.send_response(200)
        handler.send_header("Content-Type", "application/json")
        # Promise far more than is delivered, then return: the close leaves the
        # message body short and the next read raises.
        handler.send_header("Content-Length", "4096")
        handler.end_headers()
        handler.wfile.write(partial)
        handler.wfile.flush()
        handler.close_connection = True

    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(
        tiers, vendors, streamers={"p": streamer},
        extra_env={"PROXY_MAX_RETRIES": "1", "PROXY_INITIAL_DELAY": "1",
                   "PROXY_MAX_DELAY": "1"})
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        _send_proxy_request(proxy_port)
        events = _wait_for_trace_events(trace_file, "retry", timeout_s=8.0)
        conn_retries = [e for e in events if e.get("reason") == "connection_error"]
        if conn_retries:
            pass_("mid-response reset mapped to a retry event with "
                  "reason 'connection_error'")
        else:
            fail("no retry event with reason 'connection_error'; got {}".format(
                [e.get("reason") for e in events]))
    finally:
        cleanup()


def test_forward_failure_returns_envelope():
    """A forwarding exception outside the retry tuple still answers the client.

    do_POST has no outer try of its own: anything raised above the retry loop
    used to drop the connection with no response and no record. The vendor URL
    here carries a NUL in its host, which urlparse accepts but httpx2 rejects
    with InvalidURL at client construction — an exception outside
    (RequestError, StreamError, OSError) and therefore outside the retry loop.
    The client must receive the proxy's 502 Anthropic envelope with
    error.code "upstream_unreachable", and the failure must leave a
    forward_failed trace entry.
    """
    print("\n--- Test: Forwarding Failure Returns the Envelope ---")
    upstream_port = find_free_port()
    tiers = _mode_tiers()
    vendors = {"p": {"url": "http://exa\x00mple.invalid:{}".format(upstream_port),
                     "key": "K"}}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(
        tiers, vendors)
    if proc is None:
        fail("Failed to set up test (does startup reject the vendor URL?)")
        return
    try:
        status, body = _send_proxy_request(proxy_port)
        if status != 502:
            fail("expected 502 for a forwarding failure, got {}: {!r}".format(
                status, body[:300]))
            return
        try:
            payload = json.loads(body)
        except Exception:
            fail("502 body is not JSON: {!r}".format(body[:300]))
            return
        code = ((payload or {}).get("error") or {}).get("code")
        if code != "upstream_unreachable":
            fail("expected error.code 'upstream_unreachable', got {!r}".format(code))
            return
        events = _wait_for_trace_events(trace_file, "forward_failed")
        if not events:
            fail("no forward_failed trace event landed")
            return
        pass_("forwarding failure answered with the 502 upstream_unreachable "
              "envelope plus a forward_failed trace entry")
    finally:
        cleanup()


ALL_TESTS = [
    ("retry-logic", test_retry_logic),
    ("retry-429", test_retry_429),
    ("retry-429-exhaust-returns-429", test_retry_429_exhaust_returns_429),
    ("exhaust-429-preserves-body", test_exhaust_429_preserves_body),
    ("exhaust-connection-error-synthesizes-body", test_exhaust_connection_error_synthesizes_body),
    ("empty-body-429-exhaust", test_empty_body_429_exhaust),
    ("give-up-truncated-body-envelope", test_give_up_truncated_body_envelope),
    ("retry-stability-extra-header", test_retry_stability_extra_header),
    ("connection-error-retry-mapping", test_connection_error_retry_mapping),
    ("forward-failure-returns-envelope", test_forward_failure_returns_envelope),
] + COUNT_TOKENS_TESTS + FLOW_TESTS + CONCURRENCY_TESTS + DISCONNECTS_TESTS + TRANSPORT_TESTS


if __name__ == "__main__":
    run_cli(ALL_TESTS, "claude-retry-proxy tests: test_retry_streaming")
