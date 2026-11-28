"""Streaming and response-flow tests: streamed bodies, mid-stream upstream
failure, buffered response-size caps, read-timeout stall bounding, and the
response-mode swap-abort SSE fallback."""

import http
import json
import os
import shutil
import socket
import subprocess
import tempfile
import threading
import time
from _harness import PROXY_SERVER, _admin_post, _create_test_config, _create_test_keys, _create_test_keys_plain, _drain_child_stderr, _mode_tiers, _read_child_stderr, _send_proxy_request, _send_proxy_request_stream, _start_mode_proxy, _start_proxy_server_directly, _trace_events_named, _wait_admin_swapping, _wait_for_trace_events, _wait_upstream_request, fail, find_free_port, pass_, run_cli


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

            # Same as above: the drain reader owns this child's stderr pipe, so
            # a direct proc.stderr.read() would return "" and the no-Traceback
            # assertion would pass vacuously.
            stderr_output = _read_child_stderr(proc, timeout=5)

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


def test_response_mode_swap_aborts_sse_fallback():
    """The response-mode SSE fallback's drain is an upstream read like any
    other: a swap completed mid-drain stops it at the next chunk (the epoch
    check) with a swap_abort event (phase 'stream'), and the client still gets
    the synthesized terminal — never the raw upstream SSE."""
    print("\n--- Test: Response-Mode Swap Aborts the SSE Fallback ---")
    late_frame = threading.Event()

    def streamer(handler, info):
        handler.send_response(200)
        handler.send_header("Content-Type", "text/event-stream")
        handler.end_headers()
        handler.wfile.write(
            b'data: {"type":"response.output_text.delta","delta":"one"}\n\n')
        handler.wfile.flush()
        late_frame.wait(20)
        handler.wfile.write(
            b'data: {"type":"response.output_text.delta","delta":"OLD-ROUTING-MARKER"}\n\n')
        handler.wfile.flush()

    tiers = _mode_tiers()
    vendors = {
        "p": {"url": "http://127.0.0.1:{}".format(find_free_port()),
              "key": "K", "mode": "response"},
        "q": {"url": "http://127.0.0.1:{}".format(find_free_port()),
              "key": "K", "mode": "response"},
    }
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(
        tiers, vendors, streamers={"p": streamer},
        extra_env={"PROXY_SWAP_SILENCE_TIMEOUT": "2"})
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        out = {}

        def worker():
            try:
                out["result"] = _send_proxy_request_stream(
                    proxy_port, {"model": "sonnet",
                                 "messages": [{"role": "user", "content": "hi"}]})
            except Exception as e:
                out["result"] = (0, "", str(e).encode())

        client = threading.Thread(target=worker, daemon=True)
        client.start()
        if not _wait_upstream_request(mock_servers, "p"):
            fail("upstream never received the request")
            return
        switch_body = {"tiers": {
            "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
            "sonnet": {"provider": "q", "model": "claude-sonnet-5"},
            "opus": {"provider": "p", "model": "claude-opus-5"},
        }}
        switch_out = {}
        sw = threading.Thread(
            target=lambda: switch_out.update(zip(
                ("status", "data"),
                _admin_post(proxy_port, "/admin/api/switch", switch_body))),
            daemon=True)
        sw.start()
        if _wait_admin_swapping(proxy_port) is None:
            fail("swap never became visible on /admin/api/swap-status")
            return
        sw.join(20)
        if switch_out.get("status") != 200:
            fail("switch returned {}: {}".format(
                switch_out.get("status"), switch_out.get("data")))
            return
        # The swap is complete; release the late frame so the fallback's drain
        # hits its epoch check.
        late_frame.set()
        client.join(20)
        cstatus, _ctype, raw = out.get("result", (0, "", b""))
        if cstatus != 200:
            fail("client status {}, expected 200".format(cstatus))
            return
        if b"OLD-ROUTING-MARKER" in raw:
            fail("raw upstream SSE leaked to the client")
            return
        if b"message_stop" not in raw:
            fail("the fallback must still synthesize the terminal sequence: {!r}".format(raw[:300]))
            return
        phases = {e.get("phase") for e in _wait_for_trace_events(trace_file, "swap_abort")}
        if "stream" not in phases:
            fail("swap_abort phases {} must include stream".format(phases))
            return
        if not _trace_events_named(trace_file, "response_sse_unexpected"):
            fail("the response-mode SSE fallback path was never entered")
            return
        pass_("response-mode fallback stopped on the epoch change; terminal synthesized; "
              "swap_abort phase 'stream'")
    finally:
        cleanup()


def test_stream_read_timeout_bounds_stall():
    """A silent SSE upstream ends the client-visible stream at the read
    boundary, not at a multi-minute hang.

    PROXY_READ_TIMEOUT is pinned to its validation floor (10 s — smaller
    values are refused by design and fall back to 120). The old transport
    armed a per-read socket timeout; httpx2 has no mid-stream timeout API, so
    the uniform client timeout is the only bound. The lower bound matters as
    much as the upper one: an immediate close would pass an upper-bound-only
    assertion while proving nothing about the read bound.
    """
    print("\n--- Test: Stream Read Timeout Bounds a Silent Stall ---")
    read_timeout = 10
    upstream_port = find_free_port()
    tiers = _mode_tiers()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port), "key": "K"}}
    frame = (b"event: message_start\ndata: " + json.dumps({
        "type": "message_start",
        "message": {"id": "msg_stall", "type": "message", "role": "assistant",
                    "content": [], "model": "claude-sonnet-5",
                    "stop_reason": None, "stop_sequence": None,
                    "usage": {"input_tokens": 1, "output_tokens": 0}},
    }).encode() + b"\n\n")

    def streamer(handler, info):
        handler.send_response(200)
        handler.send_header("Content-Type", "text/event-stream")
        handler.end_headers()
        handler.wfile.write(frame)
        handler.wfile.flush()
        time.sleep(60)  # silent hold: the read bound is the only exit

    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(
        tiers, vendors, streamers={"p": streamer},
        extra_env={"PROXY_READ_TIMEOUT": str(read_timeout)})
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        start = time.time()
        status, _ctype, raw = _send_proxy_request_stream(
            proxy_port, {"model": "sonnet", "stream": True,
                         "messages": [{"role": "user", "content": "hi"}]})
        elapsed = time.time() - start
        if status != 200:
            fail("expected 200, got {}".format(status))
            return
        if b"message_start" not in raw:
            fail("the pre-stall frame never reached the client: {!r}".format(raw[:200]))
            return
        if elapsed < read_timeout - 1.5:
            fail("the stream ended after only {:.1f}s — the stall was not bounded "
                 "by the read timeout, so this passes vacuously".format(elapsed))
            return
        if elapsed > read_timeout + 6:
            fail("silent stream held the client {:.1f}s, beyond the {}s read "
                 "bound".format(elapsed, read_timeout))
            return
        pass_("silent SSE stream ended at the {}s read boundary ({:.1f}s)".format(
            read_timeout, elapsed))
    finally:
        cleanup()


ALL_TESTS = [
    ("streaming-response-body", test_streaming_response_body),
    ("streaming-mid-stream-upstream-failure", test_streaming_mid_stream_upstream_failure),
    ("buffered-response-size-cap", test_buffered_response_size_cap),
    # Config-swap drain (plan 2026-10-12-swap-silence-drain)
    ("response-mode-swap-aborts-sse-fallback", test_response_mode_swap_aborts_sse_fallback),
    ("stream-read-timeout-bounds-stall", test_stream_read_timeout_bounds_stall),
]


if __name__ == "__main__":
    run_cli(ALL_TESTS, "claude-retry-proxy tests: test_retry_streaming_flow")
