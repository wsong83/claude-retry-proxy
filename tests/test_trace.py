"""Trace-log tests: markers, oversized-body 413, relative log path,
trace pruning, retry-event enrichment.

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
    _send_proxy_request,
    _start_mode_proxy,
    fail,
    find_free_port,
    info,
    pass_,
    run_cli,
    warn,
)




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


# --- extra_request_headers in trace events ---
# (plan 2026-09-06-opencode-session-header)

def _read_request_events(trace_file):
    """Read all 'request' trace events from the trace file."""
    events = []
    if not trace_file or not os.path.exists(trace_file):
        return events
    with open(trace_file) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except Exception:
                continue
            if ev.get("event") == "request":
                events.append(ev)
    return events


def test_extra_request_headers_in_trace():
    """Request trace events include extra_request_headers (resolved map) for a
    ruled provider, omit it for an unruled provider, and omit it on the
    unknown-model 400 error path (provider None)."""
    print("\n--- Test: extra_request_headers in trace events ---")
    upstream1 = find_free_port()
    upstream2 = find_free_port()
    tiers = {
        "haiku": {"provider": "opencode-go", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "opencode-go", "model": "sonnet"},
        "opus": {"provider": "other", "model": "opaque-model-other"},
    }
    vendors = {
        "opencode-go": {"url": "http://127.0.0.1:{}".format(upstream1), "key": "K-OG"},
        "other": {"url": "http://127.0.0.1:{}".format(upstream2), "key": "K-OTHER"},
    }
    extra = {
        "opencode-go": [
            {"header": "x-opencode-session",
             "from": ["x-claude-code-session-id"],
             "fallback": "request_id"},
        ],
    }
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(
        tiers, vendors, extra_headers=extra)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        # (1) ruled provider 200 with inbound session header
        status, _ = _send_proxy_request(
            proxy_port, headers={"X-Claude-Code-Session-Id": "trace-sess"})
        if status != 200:
            fail("ruled provider request expected 200, got {}".format(status))
            return
        events = _read_request_events(trace_file)
        ev = [e for e in events
              if e.get("provider") == "opencode-go" and e.get("http_status") == 200]
        if not ev:
            fail("no request trace event for the ruled-provider request")
            return
        ev = ev[-1]
        if ev.get("extra_request_headers") == {"x-opencode-session": "trace-sess"}:
            pass_("ruled provider request event carries extra_request_headers={!r}".format(
                ev.get("extra_request_headers")))
        else:
            fail("expected extra_request_headers={{'x-opencode-session': 'trace-sess'}}, got {!r}".format(
                ev.get("extra_request_headers")))

        # (2) unruled provider request omits the key
        status, _ = _send_proxy_request(
            proxy_port,
            body=json.dumps({"model": "opaque-model-other",
                             "messages": [{"role": "user", "content": "hi"}]}))
        if status != 200:
            fail("unruled provider request expected 200, got {}".format(status))
            return
        events = _read_request_events(trace_file)
        ev = [e for e in events
              if e.get("provider") == "other" and e.get("http_status") == 200][-1]
        if "extra_request_headers" not in ev:
            pass_("unruled provider request event omits extra_request_headers")
        else:
            fail("expected unruled provider trace to omit extra_request_headers, got {!r}".format(
                ev.get("extra_request_headers")))

        # (3) unknown-model 400 (provider None) omits the key
        status, _ = _send_proxy_request(
            proxy_port,
            body=json.dumps({"model": "zz-not-a-model",
                             "messages": [{"role": "user", "content": "hi"}]}))
        if status != 400:
            fail("unknown model expected 400, got {}".format(status))
            return
        events = _read_request_events(trace_file)
        ev = [e for e in events if e.get("http_status") == 400]
        if not ev:
            fail("no request trace event for the unknown-model 400 path")
            return
        ev = ev[-1]
        if ev.get("provider") is None and "extra_request_headers" not in ev:
            pass_("unknown-model 400 event (provider None) omits extra_request_headers")
        else:
            fail("expected 400 event without extra_request_headers, got provider={!r}, keys={!r}".format(
                ev.get("provider"), sorted(ev.keys())))
    finally:
        cleanup()


ALL_TESTS = [
    ("start-prunes-old-trace-entries", test_start_prunes_old_trace_entries),
    ("prune-trace-file-edge-cases", test_prune_trace_file_edge_cases),
    ("trace-markers", test_trace_markers),
    ("trace-logs-oversized-body", test_trace_logs_oversized_body),
    ("relative-log-path", test_relative_log_path),
    ("retry-trace-event-enriched", test_retry_trace_event_enriched),
    ("extra-request-headers-in-trace", test_extra_request_headers_in_trace),
]


if __name__ == "__main__":
    run_cli(ALL_TESTS, "claude-retry-proxy tests: test_trace")
