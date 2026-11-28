"""Disconnect and failure-classification tests: client disconnects without
tracebacks, trace-write failure not duplicating the upstream request, and
retry-path stderr writes not misclassified as connection errors."""

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
from _harness import PROXY_SERVER, _create_test_config, _create_test_keys, _drain_child_stderr, _mode_tiers, _read_child_stderr, _send_proxy_request, _start_mode_mock_upstream, _start_mode_proxy, fail, find_free_port, pass_, run_cli


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

        # Collect stderr through the harness accessor: this child's stderr pipe
        # is owned by the drain reader _drain_child_stderr installed at spawn,
        # so a direct proc.stderr.read() here returns "" and the assertion below
        # would fail on an empty diagnostic rather than on a real one.
        stderr_output = _read_child_stderr(proc, timeout=5)

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


# --- Sink guard: retry-loop misclassification (plan 2026-09-10-guard-trace-state-sinks) ---

def _oversized_json_responder(info):
    """200 anthropic-shape JSON, deliberately larger than the 1024-byte cap.

    Exceeding PROXY_MAX_RESPONSE_SIZE is what makes the in-loop
    `response_size_cap_exceeded` log_trace (in `forwarder._forward_core`) fire
    on an otherwise successful response.
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
    import claude_retry_proxy.runtime_state as runtime_state
    from claude_retry_proxy import sinks

    upstream_port = find_free_port()
    reqs = []
    mock_server = _start_mode_mock_upstream(upstream_port, reqs, _responder_503)
    # The mock owns the port it actually bound; the URL below follows it.
    upstream_port = mock_server.server_address[1]
    root = tempfile.mkdtemp(prefix="proxy_retryprint_")
    # The sinks hold their own path, so the redirection goes through
    # configure(); assigning server.PROXY_TRACE_FILE would be inert here.
    prev_trace_path = sinks._trace._path
    prev_state_path = sinks._state._path
    saved = (runtime_state._current_config,
             runtime_state._vendors, srv.SETTINGS.max_retries,
             srv.SETTINGS.initial_delay, srv.SETTINGS.max_delay, sys.stderr)
    try:
        sinks.configure(trace_path=os.path.join(root, "trace.jsonl"),
                        state_path=os.path.join(root, "state.json"))
        # One retry (2 attempts), fast backoff.
        srv.SETTINGS.max_retries = 1
        srv.SETTINGS.initial_delay = 1
        srv.SETTINGS.max_delay = 1
        runtime_state._current_config = {
            "tiers": {
                "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
                "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
                "opus": {"provider": "p", "model": "claude-opus-5"},
            },
            "models": {"p": ["claude-haiku-4-5", "claude-sonnet-5",
                             "claude-opus-5"]},
        }
        runtime_state._vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port),
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
        (runtime_state._current_config,
         runtime_state._vendors, srv.SETTINGS.max_retries,
         srv.SETTINGS.initial_delay, srv.SETTINGS.max_delay, sys.stderr) = saved
        sinks.configure(trace_path=prev_trace_path, state_path=prev_state_path)
        try:
            mock_server.shutdown()
            mock_server.server_close()
        except Exception:
            pass
        shutil.rmtree(root, ignore_errors=True)


ALL_TESTS = [
    ("client-disconnect-no-traceback", test_client_disconnect_no_traceback),
    ("trace-write-failure-does-not-duplicate-upstream-request", test_trace_write_failure_does_not_duplicate_upstream_request),
    ("retry-path-print-failure-does-not-misclassify", test_retry_path_print_failure_does_not_misclassify),
]


if __name__ == "__main__":
    run_cli(ALL_TESTS, "claude-retry-proxy tests: test_retry_streaming_disconnects")
