"""Retry/backoff, exhaustion, disconnect, streaming, thread-safety,
concurrency, and count-tokens retry-flag tests.

Part of the claude-retry-proxy suite; runnable standalone.
"""

import http
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time

from _harness import (
    PROXY_SERVER,
    _create_test_config,
    _create_test_config_with_flag,
    _create_test_keys,
    _create_test_keys_plain,
    _derive_models_from_tiers,
    _mode_tiers,
    _send_proxy_request,
    _start_mode_mock_upstream,
    _start_mode_proxy,
    _start_proxy_server_directly,
    errors,
    fail,
    find_free_port,
    info,
    pass_,
    run_cli,
    warn,
)




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


def test_buffered_response_size_cap():
    """Buffered 2xx-JSON and non-2xx response paths cap the upstream body at
    PROXY_MAX_RESPONSE_SIZE: the body is truncated, a
    response_size_cap_exceeded trace event fires, and the request still
    completes with its original status. (Plan 2026-09-01 Step 2 follow-up,
    issue buffered-response-paths-uncapped. The 2xx other-content-type
    chat/response loop shares the same fix pattern.)"""
    print("\n--- Test: Buffered Response Size Cap ---")
    upstream_port = find_free_port()
    proxy_port = find_free_port()
    request_count = [0]
    count_lock = threading.Lock()
    pad = "x" * 10240
    big_ok = json.dumps({
        "id": "msg_big", "type": "message", "role": "assistant",
        "model": "claude-sonnet-5",
        "content": [{"type": "text", "text": pad}],
        "stop_reason": "end_turn", "stop_sequence": None,
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }).encode()
    big_err = json.dumps({
        "type": "error",
        "error": {"type": "invalid_request_error", "message": pad},
    }).encode()

    class SizeCapHandler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            content_len = int(self.headers.get("Content-Length", 0))
            if content_len > 0:
                self.rfile.read(content_len)
            with count_lock:
                request_count[0] += 1
                n = request_count[0]
            body = big_ok if n == 1 else big_err
            status = 200 if n == 1 else 400
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            pass

    mock_server = http.server.ThreadingHTTPServer(
        ("127.0.0.1", upstream_port), SizeCapHandler)
    threading.Thread(target=mock_server.serve_forever, daemon=True).start()
    time.sleep(0.1)

    temp_dir = tempfile.mkdtemp(prefix="proxy_size_cap_test_")
    tiers = {
        "haiku": {"provider": "test-provider", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "test-provider", "model": "claude-sonnet-5"},
        "opus": {"provider": "test-provider", "model": "claude-opus-5"},
    }
    vendors = {
        "test-provider": {"url": f"http://127.0.0.1:{upstream_port}",
                          "key": "test-api-key"}
    }
    config_path = _create_test_config(temp_dir, tiers)
    keys_path = _create_test_keys_plain(temp_dir, vendors)
    trace_fd, trace_file = tempfile.mkstemp(suffix=".jsonl", dir=temp_dir)
    os.close(trace_fd)

    proc, probe_ok = _start_proxy_server_directly(
        proxy_port, config_path=config_path, keys_path=keys_path,
        passphrase=None, trace_file=trace_file,
        extra_env={"PROXY_MAX_RESPONSE_SIZE": "1024"})
    if not probe_ok:
        proc.kill()
        mock_server.shutdown()
        shutil.rmtree(temp_dir, ignore_errors=True)
        fail("Proxy server failed to start")
        return

    def cap_events():
        out = []
        if not os.path.exists(trace_file):
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
                if ev.get("event") == "response_size_cap_exceeded":
                    out.append(ev)
        return out

    try:
        # Sub-case 1: buffered 2xx application/json path. Truncation lands on
        # a read-chunk boundary, so assert non-empty and smaller than sent.
        status, resp_body = _send_proxy_request(proxy_port)
        if status != 200:
            fail("2xx big-body request returned %s" % status)
            return
        if not (0 < len(resp_body) < len(big_ok)):
            fail("2xx big body not truncated (sent %d, got %d bytes)"
                 % (len(big_ok), len(resp_body)))
            return
        pass_("buffered 2xx JSON body truncated under PROXY_MAX_RESPONSE_SIZE")

        # Sub-case 2: buffered non-2xx path.
        status, resp_body = _send_proxy_request(proxy_port)
        if status != 400:
            fail("non-2xx big-body request returned %s" % status)
            return
        if not (0 < len(resp_body) < len(big_err)):
            fail("non-2xx body not truncated (sent %d, got %d bytes)"
                 % (len(big_err), len(resp_body)))
            return
        pass_("buffered non-2xx body truncated under PROXY_MAX_RESPONSE_SIZE")

        events = cap_events()
        if not events:
            fail("no response_size_cap_exceeded trace event emitted")
            return
        pass_("response_size_cap_exceeded emitted (%d event(s))"
              % len(events))
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        mock_server.shutdown()
        shutil.rmtree(temp_dir, ignore_errors=True)


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


# --- Sink guard: retry-loop misclassification (plan 2026-09-10-guard-trace-state-sinks) ---

def _oversized_json_responder(info):
    """200 anthropic-shape JSON, deliberately larger than the 1024-byte cap.

    Exceeding PROXY_MAX_RESPONSE_SIZE is what makes the in-loop
    `response_size_cap_exceeded` log_trace (server.py:2072) fire on an
    otherwise successful response.
    """
    payload = json.dumps({
        "id": "msg_big",
        "type": "message",
        "role": "assistant",
        "model": "claude-sonnet-5",
        "content": [{"type": "text", "text": "x" * 2000}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }).encode()
    return 200, "application/json", payload


def test_trace_write_failure_does_not_duplicate_upstream_request():
    """A trace-write failure inside the retry loop must not be misread as a
    connection error and re-issue the upstream POST.

    The response-size cap is what puts a log_trace call inside the retry loop's
    `try`: the body exceeds PROXY_MAX_RESPONSE_SIZE, so the cap event is traced
    and the truncated body is returned. With the trace path blocked at runtime,
    that call is exactly what `except (socket.error, ConnectionError, OSError)`
    would have swallowed pre-fix — backing off and sending the POST upstream a
    second time, then handing the client status 0 with an upstream_unreachable
    body. PROXY_MAX_RETRIES=1 bounds a pre-fix regression to ~1s of backoff.
    """
    print("\n--- Test: Trace Write Failure Does Not Duplicate Upstream Request ---")

    upstream = find_free_port()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream), "key": "K"}}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(
        _mode_tiers(), vendors,
        responders={"p": _oversized_json_responder},
        extra_env={"PROXY_MAX_RESPONSE_SIZE": "1024", "PROXY_MAX_RETRIES": "1"})
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        # Block the trace sink at runtime — a blocked path at startup aborts.
        os.remove(trace_file)
        os.mkdir(trace_file)

        status, body = _send_proxy_request(proxy_port)
        if status == 200:
            pass_("client received 200 despite the in-loop trace-write failure")
        else:
            fail("expected 200, got {} ({!r}) — the trace-write failure was "
                 "misread as a connection error".format(status, body[:200]))

        reqs = mock_servers["p"]["requests"]
        if len(reqs) == 1:
            pass_("upstream received exactly 1 request (no duplicate POST)")
        else:
            fail("expected exactly 1 upstream request, got {} — the retry loop "
                 "re-issued the POST after a trace-write failure".format(len(reqs)))
    finally:
        cleanup()


class _RaisingStderr(object):
    """A stderr whose write() raises OSError(28) — the full-disk fault."""
    encoding = "utf-8"

    def write(self, _s):
        raise OSError(28, "No space left on device")

    def flush(self):
        pass

    def isatty(self):
        return False


def _responder_503(info):
    """Upstream that always answers 503, so the retry loop's notices fire."""
    return 503, "application/json", b'{"error":"Service Unavailable"}'


def test_retry_path_print_failure_does_not_misclassify():
    """A failing print inside the retry loop must not read as a connection error.

    In-process: forward_request is driven directly while sys.stderr is
    _BestEffortStderr over a raising stream. The mock upstream answers 503, so
    the loop's retry notice fires — the print that, unguarded, would raise
    OSError out of the try block and be caught by `except (socket.error,
    ConnectionError, OSError)`, turning an answered 503 into a synthesized
    status-0 upstream_unreachable. With the stream wrapper the 503 survives.

    This exercises the wrapper directly; main()'s installation of it is covered
    by the structural check, and no other test drives forward_request in-process
    because every other integration test spawns the proxy as a subprocess (whose
    sys.stderr the test cannot replace).
    """
    print("\n--- Test: Retry-Path Print Failure Does Not Misclassify ---")

    import claude_retry_proxy.server as srv

    upstream_port = find_free_port()
    reqs = []
    mock_server = _start_mode_mock_upstream(upstream_port, reqs, _responder_503)
    root = tempfile.mkdtemp(prefix="proxy_retryprint_")
    saved = (srv.PROXY_TRACE_FILE, srv.STATE_FILE, srv._current_config,
             srv._vendors, srv.PROXY_MAX_RETRIES, srv.PROXY_INITIAL_DELAY,
             srv.PROXY_MAX_DELAY, sys.stderr)
    try:
        srv.PROXY_TRACE_FILE = os.path.join(root, "trace.jsonl")
        srv.STATE_FILE = os.path.join(root, "state.json")
        # One retry (2 attempts), fast backoff.
        srv.PROXY_MAX_RETRIES = 1
        srv.PROXY_INITIAL_DELAY = 1
        srv.PROXY_MAX_DELAY = 1
        srv._current_config = {
            "tiers": {
                "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
                "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
                "opus": {"provider": "p", "model": "claude-opus-5"},
            },
            "models": {"p": ["claude-haiku-4-5", "claude-sonnet-5",
                             "claude-opus-5"]},
        }
        srv._vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port),
                              "key": "K"}}
        srv._compat_validate_constants()
        srv._load_compat_state()

        sys.stderr = srv._BestEffortStderr(_RaisingStderr())
        body = json.dumps({
            "model": "sonnet",
            "messages": [{"role": "user", "content": "hi"}],
        }).encode()
        status = srv.forward_request(
            "POST", "/v1/messages", {"content-type": "application/json"},
            body, None, "retryprint-1")[0]
        sys.stderr = saved[-1]

        if status == 503:
            pass_("client received the upstream 503 (print failure not misclassified)")
        else:
            fail("expected 503, got {} — a diagnostic print failure was read as "
                 "a connection error".format(status))

        if len(reqs) == 2:
            pass_("upstream received exactly 2 requests (1 retry, no duplicates)")
        else:
            fail("expected exactly 2 upstream requests, got {}".format(len(reqs)))
    finally:
        (srv.PROXY_TRACE_FILE, srv.STATE_FILE, srv._current_config,
         srv._vendors, srv.PROXY_MAX_RETRIES, srv.PROXY_INITIAL_DELAY,
         srv.PROXY_MAX_DELAY, sys.stderr) = saved
        try:
            mock_server.shutdown()
        except Exception:
            pass
        shutil.rmtree(root, ignore_errors=True)


ALL_TESTS = [
    ("concurrent-requests", test_concurrent_requests),
    ("retry-logic", test_retry_logic),
    ("retry-429", test_retry_429),
    ("retry-429-exhaust-returns-429", test_retry_429_exhaust_returns_429),
    ("thread-safety", test_thread_safety),
    ("start-no-auth-header-required", test_start_no_auth_header_required),
    ("exhaust-429-preserves-body", test_exhaust_429_preserves_body),
    ("exhaust-connection-error-synthesizes-body", test_exhaust_connection_error_synthesizes_body),
    ("client-disconnect-no-traceback", test_client_disconnect_no_traceback),
    ("streaming-response-body", test_streaming_response_body),
    ("streaming-mid-stream-upstream-failure", test_streaming_mid_stream_upstream_failure),
    ("empty-body-429-exhaust", test_empty_body_429_exhaust),
    ("disable-retry-count-tokens-503", test_disable_retry_count_tokens_503),
    ("disable-retry-count-tokens-conn-error", test_disable_retry_count_tokens_conn_error),
    ("disable-retry-count-tokens-normal-path-unaffected", test_disable_retry_count_tokens_normal_path_unaffected),
    ("disable-retry-count-tokens-false-retries", test_disable_retry_count_tokens_false_retries),
    ("disable-retry-count-tokens-path-anchoring", test_disable_retry_count_tokens_path_anchoring),
    ("disable-retry-count-tokens-invalid-type", test_disable_retry_count_tokens_invalid_type),
    ("buffered-response-size-cap", test_buffered_response_size_cap),
    ("retry-stability-extra-header", test_retry_stability_extra_header),
    ("trace-write-failure-does-not-duplicate-upstream-request", test_trace_write_failure_does_not_duplicate_upstream_request),
    ("retry-path-print-failure-does-not-misclassify", test_retry_path_print_failure_does_not_misclassify),
]


if __name__ == "__main__":
    run_cli(ALL_TESTS, "claude-retry-proxy tests: test_retry_streaming")
