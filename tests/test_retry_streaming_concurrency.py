"""Concurrency and listener tests: concurrent request handling, retry-path
thread safety, 429 drain bounding, and the listener accept backlog."""

import http
import json
import os
import shutil
import socket
import subprocess
import tempfile
import threading
import time
from _harness import PROXY_SERVER, _create_test_config, _create_test_keys, _drain_child_stderr, _mode_tiers, _send_proxy_request, _start_mode_proxy, _wait_for_trace_events, fail, find_free_port, pass_, run_cli


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


def test_429_drain_bounded():
    """A 429 body larger than the body cap still retries promptly.

    The pre-retry drain must be raw and bounded: `resp.read()` decodes
    (b"".join(iter_bytes()) — a compressed error body expands into worker
    memory, uncapped, on every retry attempt) and waits for the whole
    declared response, so a slow or withheld error body stalls the retry.
    Here the stub answers 429 with `Content-Encoding: gzip`, a real ~8 KiB
    gzip blob (8 MiB decoded, well past PROXY_MAX_BODY_SIZE=1024) and a
    Content-Length covering a remainder it never sends, then holds. The
    bounded iter_raw discard breaks after the cap and closes, so attempt 2
    lands in seconds; a regression to a full decoding read waits out the
    pinned read timeout (10 s) — which both exceeds this test's client
    deadline and fails the elapsed assertion.
    """
    print("\n--- Test: 429 Drain Is Bounded ---")
    import gzip
    oversize = gzip.compress(b"\x00" * (8 * 1024 * 1024))
    withheld = 4 * 1024 * 1024          # declared, never sent
    attempts = []
    attempt_lock = threading.Lock()
    hold = threading.Event()
    ok_body = json.dumps({
        "id": "msg_ok", "type": "message", "role": "assistant",
        "model": "claude-sonnet-5",
        "content": [{"type": "text", "text": "ok"}],
        "stop_reason": "end_turn", "stop_sequence": None,
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }).encode()

    def streamer(handler, info):
        with attempt_lock:
            attempts.append(info.get("path"))
            n = len(attempts)
        if n == 1:
            handler.send_response(429)
            handler.send_header("Content-Type", "application/json")
            handler.send_header("Content-Encoding", "gzip")
            handler.send_header("Content-Length",
                                str(len(oversize) + withheld))
            handler.end_headers()
            handler.wfile.write(oversize)
            handler.wfile.flush()
            # The remainder never arrives inside the drain's bound. Return
            # without writing: the proxy has already closed the connection,
            # and a post-hoc write would only noise this process's stderr.
            hold.wait(15)
            handler.close_connection = True
            return
        handler.send_response(200)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(ok_body)))
        handler.end_headers()
        handler.wfile.write(ok_body)
        handler.wfile.flush()

    tiers = _mode_tiers()
    upstream_port = find_free_port()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port),
                     "key": "K"}}
    temp_dir, proxy_port, proc, _mock_servers, trace_file, cleanup = \
        _start_mode_proxy(
            tiers, vendors, streamers={"p": streamer},
            extra_env={"PROXY_MAX_BODY_SIZE": "1024",
                       "PROXY_READ_TIMEOUT": "10",
                       "PROXY_MAX_RETRIES": "3",
                       "PROXY_INITIAL_DELAY": "1",
                       "PROXY_MAX_DELAY": "2"})
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        start = time.time()
        status, body = _send_proxy_request(proxy_port)
        elapsed = time.time() - start
        if status != 200:
            fail("expected 200 after the 429 retry, got {} after {:.1f}s: "
                 "{!r}".format(status, elapsed, body[:300]))
            return
        if len(attempts) != 2:
            fail("expected exactly two upstream attempts, got {}".format(
                len(attempts)))
            return
        events = _wait_for_trace_events(trace_file, "retry", timeout_s=5.0)
        retries_429 = [e for e in events if e.get("reason") == "429"]
        if not retries_429:
            fail("no retry trace event with reason '429'; got {}".format(
                [e.get("reason") for e in events]))
            return
        if elapsed >= 9.0:
            fail("the retried exchange took {:.1f}s — the drain waited for the "
                 "withheld remainder instead of stopping at the "
                 "PROXY_MAX_BODY_SIZE bound".format(elapsed))
            return
        pass_("bounded non-decoding 429 drain retried in {:.1f}s "
              "(oversize gzip body, {} bytes withheld)".format(
                  elapsed, withheld))
    finally:
        hold.set()
        cleanup()


def test_proxy_listen_backlog():
    """_ProxyHTTPServer pins the accept backlog at 128 (plan 2026-11-19).

    socketserver's default request_queue_size is 5; a burst of simultaneous
    connections (parallel tool fan-outs, test concurrency) overflows the
    kernel accept queue and the kernel drops SYNs, so a dropped connection
    never reaches the handler — no trace entry, and the client sees a ~1 s
    SYN-retransmit stall or a ConnectionResetError. The issue
    ingress-listen-backlog measured +71 TcpExtListenDrops/ListenOverflows
    across six 20-request bursts on the default. This pin keeps a refactor
    from silently reverting the class attribute; measure drops on demand with
    `nstat -az | grep -E "ListenDrops|ListenOverflows"` deltas around a burst.
    """
    print("\n--- Test: Proxy Listen Backlog ---")
    try:
        from claude_retry_proxy.server import _ProxyHTTPServer
    except Exception as e:
        fail("cannot import _ProxyHTTPServer: {}".format(e))
        return
    got = getattr(_ProxyHTTPServer, "request_queue_size", None)
    if got != 128:
        fail("_ProxyHTTPServer.request_queue_size must be 128 (burst "
             "tolerance; socketserver's default 5 drops SYNs under "
             "simultaneous fan-outs), got {!r}".format(got))
        return
    pass_("_ProxyHTTPServer.request_queue_size is 128")


ALL_TESTS = [
    ("concurrent-requests", test_concurrent_requests),
    ("thread-safety", test_thread_safety),
    ("429-drain-bounded", test_429_drain_bounded),
    # Listener accept backlog (plan 2026-11-19-drop-redacted-thinking-chat-placeholder)
    ("proxy-listen-backlog", test_proxy_listen_backlog),
]


if __name__ == "__main__":
    run_cli(ALL_TESTS, "claude-retry-proxy tests: test_retry_streaming_concurrency")
