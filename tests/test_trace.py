"""Trace-log tests: markers, oversized-body 413, relative log path,
trace pruning, retry-event enrichment.

Part of the claude-retry-proxy suite; runnable standalone.
"""

import contextlib
import http
import io
import json
import os
import re
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
    _mode_tiers,
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


def test_trace_includes_key_name_not_payload():
    """Request trace events carry the resolved key *name* for a multi-key tier
    (never the payload); the unknown-model 400 path still delivers the 400
    response with a trace entry that omits the key field; and an EXTRA
    (non-standard) tier routed via reverse model lookup also carries its key
    in the trace (generic re-resolution, no tier whitelist)."""
    print("\n--- Test: Trace Includes Key Name Not Payload ---")
    upstream = find_free_port()
    tiers = {
        "haiku": {"provider": "p", "model": "claude-haiku-4-5", "key": "CZ"},
        "sonnet": {"provider": "p", "model": "claude-sonnet-5", "key": "SW"},
        "opus": {"provider": "p", "model": "claude-opus-5"},
        "extra": {"provider": "p", "model": "extra-model", "key": "CZ"},
    }
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream),
                     "keys": {"SW": "p1", "CZ": "p2"}}}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(tiers, vendors)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        # (1) multi-key tier request carries the resolved key name; no payload
        status, _ = _send_proxy_request(proxy_port)
        if status != 200:
            fail("ruled request expected 200, got {}".format(status))
            return
        events = _read_request_events(trace_file)
        ev = [e for e in events if e.get("provider") == "p" and e.get("http_status") == 200][-1]
        if ev.get("key") == "SW":
            pass_("request trace carries resolved key name SW")
        else:
            fail("expected trace key 'SW', got {!r}".format(ev.get("key")))
        with open(trace_file) as f:
            raw = f.read()
        if "p1" not in raw and "p2" not in raw:
            pass_("trace JSONL contains no key payload strings")
        else:
            fail("trace JSONL leaked a key payload (p1/p2 present)")

        # (2) unknown-model 400: response delivered AND trace entry without key
        status, _ = _send_proxy_request(proxy_port, body=json.dumps({
            "model": "zz-not-a-model", "messages": [{"role": "user", "content": "hi"}]}))
        if status != 400:
            fail("unknown model expected 400, got {}".format(status))
            return
        pass_("unknown-model request still delivered a 400 response")
        events = _read_request_events(trace_file)
        ev = [e for e in events if e.get("http_status") == 400][-1]
        if "key" not in ev and ev.get("provider") is None:
            pass_("400 trace entry omits the key field (provider None, no crash)")
        else:
            fail("expected 400 event without key, got provider={!r} keys={!r}".format(
                ev.get("provider"), sorted(ev.keys())))

        # (3) extra (non-standard) tier routed via reverse model lookup carries
        #     its key in the trace too (generic re-resolution, no whitelist)
        status, _ = _send_proxy_request(proxy_port, body=json.dumps({
            "model": "extra-model", "messages": [{"role": "user", "content": "hi"}]}))
        if status != 200:
            fail("extra-tier request expected 200, got {}".format(status))
            return
        events = _read_request_events(trace_file)
        ev = [e for e in events
              if e.get("tier") == "extra" and e.get("http_status") == 200][-1]
        if ev.get("key") == "CZ":
            pass_("extra-tier request trace carries key CZ (generic resolution)")
        else:
            fail("expected extra-tier trace key 'CZ', got tier={!r} key={!r}".format(
                ev.get("tier"), ev.get("key")))
    finally:
        cleanup()


# --- Sink I/O failure guards (plan 2026-09-10-guard-trace-state-sinks) ---
#
# The trace and state sinks must never raise into their callers: a trace-write
# OSError inside the retry loop's `except (socket.error, ConnectionError,
# OSError)` clause would be misread as a connection error and re-issue the
# upstream POST.

def _reset_sink_warn_state(sink):
    """Drop any in-flight failure episode for `sink` (module state is shared
    across the in-process tests below)."""
    import claude_retry_proxy.server as srv
    with srv._sink_warn_lock:
        srv._sink_warn_state.pop(sink, None)


def _parse_suppressed(line):
    """Exact integer from '(N further failures suppressed)', or None."""
    m = re.search(r"\((\d+) further failures? suppressed\)", line)
    return int(m.group(1)) if m else None


def _parse_resumed_count(line):
    """Exact integer from 'resumed after N failed write(s)', or None."""
    m = re.search(r"resumed after (\d+) failed write", line)
    return int(m.group(1)) if m else None


class _FastTime(object):
    """Delegates to the real time module, but shortens sleep().

    heartbeat_loop sleeps a hardcoded 30s with no env override; this keeps the
    heartbeat tests from stalling the suite.
    """
    def sleep(self, _seconds):
        time.sleep(0.02)

    def __getattr__(self, name):
        return getattr(time, name)


class _FailingStderr(object):
    """A stderr whose write() raises OSError(28), like a full disk.

    The server's stderr is a file on the same volume as the state file
    (cli.py -> ~/.claude/proxy/proxy-stderr.log), so an ENOSPC condition breaks
    the sink write and the warning print together.
    """
    encoding = "utf-8"

    def write(self, _s):
        raise OSError(28, "No space left on device")

    def flush(self):
        pass

    def close(self):
        pass

    def isatty(self):
        return False


def test_sink_failure_does_not_drop_response():
    """A failing trace sink must not drop an otherwise successful response, nor
    make the retry loop re-issue the upstream POST.

    The sink is blocked *at runtime* — the healthy trace file is replaced by a
    directory after startup — because startup itself fails fast on an
    unwritable trace path, so runtime degradation is only observable on a proxy
    that started cleanly.
    """
    print("\n--- Test: Sink Failure Does Not Drop Response ---")

    upstream = find_free_port()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream), "key": "K"}}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
        _start_mode_proxy(_mode_tiers(), vendors)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        # Block the trace sink: the path must exist and be a directory. On
        # Windows open() raises PermissionError; on POSIX IsADirectoryError —
        # both OSError subclasses.
        os.remove(trace_file)
        os.mkdir(trace_file)

        status, body = _send_proxy_request(proxy_port)
        if status == 200:
            pass_("client received 200 despite the failing trace sink")
        else:
            fail("expected 200 with a failing trace sink, got {} ({!r})".format(
                status, body[:200]))

        reqs = mock_servers["p"]["requests"]
        if len(reqs) == 1:
            pass_("upstream received exactly 1 request (no retry misclassification)")
        else:
            fail("expected exactly 1 upstream request, got {} — a trace-write "
                 "failure was misread as a connection error".format(len(reqs)))
    finally:
        cleanup()


def test_sink_warning_rate_limit():
    """The first failure of an episode warns immediately; further failures
    inside SINK_WARN_INTERVAL are silent; the next failure after the interval
    warns once and reports how many were suppressed."""
    print("\n--- Test: Sink Warning Rate Limit ---")

    import claude_retry_proxy.server as srv

    sink = "trace"
    rapid = 5
    _reset_sink_warn_state(sink)
    try:
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            for _ in range(rapid):
                srv._warn_sink_failure(sink, OSError("boom"))
        first = [l for l in buf.getvalue().splitlines()
                 if "[proxy] WARNING:" in l and sink in l]
        if len(first) == 1:
            pass_("1 warning for {} rapid failures: {!r}".format(rapid, first[0]))
        else:
            fail("expected exactly 1 warning for {} rapid failures, got {}".format(
                rapid, len(first)))

        # Force the interval to lapse, then fail once more. Only the failures
        # that were actually silent (rapid - 1) are reported: the failure
        # triggering the emission is never counted as suppressed.
        with srv._sink_warn_lock:
            srv._sink_warn_state[sink]["last_warn"] = \
                time.time() - (srv.SINK_WARN_INTERVAL + 1)
        later_buf = io.StringIO()
        with contextlib.redirect_stderr(later_buf):
            srv._warn_sink_failure(sink, OSError("boom"))
        later = [l for l in later_buf.getvalue().splitlines()
                 if "[proxy] WARNING:" in l]
        expected = rapid - 1
        got = _parse_suppressed(later[0]) if len(later) == 1 else None
        if got == expected:
            pass_("failure past the interval reports exactly {} suppressed: "
                  "{!r}".format(expected, later[0]))
        else:
            fail("expected exactly 1 warning reporting {} suppressed, parsed "
                 "{!r} from {!r}".format(expected, got, later))
    finally:
        _reset_sink_warn_state(sink)


def test_sink_recovery_notice():
    """The first successful write after a failure episode emits one line
    carrying the episode's dropped-write count; later successes are silent."""
    print("\n--- Test: Sink Recovery Notice ---")

    import claude_retry_proxy.server as srv

    sink = "state"
    _reset_sink_warn_state(sink)
    try:
        quiet = io.StringIO()
        with contextlib.redirect_stderr(quiet):
            srv._note_sink_recovery(sink)
        if "resumed" not in quiet.getvalue():
            pass_("recovery with no open episode emits nothing")
        else:
            fail("recovery notice without a failure episode: {!r}".format(
                quiet.getvalue()))

        failures = 3
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            for _ in range(failures):
                srv._warn_sink_failure(sink, OSError("nope"))
            srv._note_sink_recovery(sink)
        lines = [l for l in buf.getvalue().splitlines() if "resumed" in l]
        got = _parse_resumed_count(lines[0]) if len(lines) == 1 else None
        if got == failures and sink in lines[0]:
            pass_("recovery line reports exactly {} failed write(s): {!r}".format(
                failures, lines[0]))
        else:
            fail("expected 1 recovery line reporting exactly {} failed writes, "
                 "parsed {!r} from {!r}".format(failures, got, lines))

        second = io.StringIO()
        with contextlib.redirect_stderr(second):
            srv._note_sink_recovery(sink)
        if "resumed" not in second.getvalue():
            pass_("episode closed — a second recovery emits nothing")
        else:
            fail("second recovery notice emitted: {!r}".format(second.getvalue()))
    finally:
        _reset_sink_warn_state(sink)


def test_trace_sink_creates_missing_directories():
    """log_trace still creates missing parent directories and writes the entry.

    Guards the makedirs self-heal against regression by the sink guard: a
    deleted trace directory must recover on the next call with no intervention.
    """
    print("\n--- Test: Trace Sink Creates Missing Directories ---")

    import claude_retry_proxy.server as srv

    root = tempfile.mkdtemp(prefix="proxy_trace_mkdir_")
    target = os.path.join(root, "missing", "nested", "trace.jsonl")
    saved = srv.PROXY_TRACE_FILE
    srv.PROXY_TRACE_FILE = target
    try:
        ok = srv.log_trace({"event": "sink_mkdir_probe", "value": 1})
        if ok is True:
            pass_("log_trace returned True")
        else:
            fail("log_trace returned {!r}, expected True".format(ok))
            return
        if not os.path.exists(target):
            fail("trace file not created at {!r}".format(target))
            return
        pass_("missing parent directories were created and the entry written")

        with open(target) as f:
            lines = [l for l in f if l.strip()]
        if len(lines) == 1 and json.loads(lines[0])["event"] == "sink_mkdir_probe":
            pass_("entry round-trips through the newly created directory")
        else:
            fail("unexpected trace contents: {!r}".format(lines))
    finally:
        srv.PROXY_TRACE_FILE = saved
        shutil.rmtree(root, ignore_errors=True)


def test_heartbeat_survives_failed_state_write():
    """The heartbeat thread survives a failing state write.

    Before the guard, an OSError escaping write_state propagated out of
    heartbeat_loop and killed the thread permanently — proxy-state.json then
    stopped updating for the rest of the process's life. This runs the real
    heartbeat_loop with its 30s sleep shortened, blocks the state path at
    runtime, and asserts the thread is still alive and that the obstruction
    clears on the next cycle.

    Scope is survival and recovery only. The state file's field *values* are
    asserted by test_heartbeat_preserves_state (tests/test_config_keys.py); a
    presence-only re-check here would be a strictly weaker copy of it.
    """
    print("\n--- Test: Heartbeat Survives Failed State Write ---")

    import claude_retry_proxy.server as srv

    root = tempfile.mkdtemp(prefix="proxy_hb_blocked_")
    blocked = os.path.join(root, "state.json")
    os.mkdir(blocked)

    _reset_sink_warn_state("state")
    saved = (srv.STATE_FILE, srv._startup_state, srv._shutting_down, srv.time)
    srv.STATE_FILE = blocked
    srv._startup_state = {
        "pid": 12345,
        "port": 8080,
        "started_at": "2026-09-10T00:00:00Z",
        "owner_pid": 54321,
        "last_heartbeat": "2026-09-10T00:00:00Z",
        "last_request_at": "2026-09-10T00:00:00Z",
    }
    srv._shutting_down = False
    srv.time = _FastTime()

    thread = None
    buf = io.StringIO()
    try:
        with contextlib.redirect_stderr(buf):
            thread = threading.Thread(target=srv.heartbeat_loop, daemon=True)
            thread.start()

            deadline = time.time() + 5
            while (time.time() < deadline
                   and "state sink write failed" not in buf.getvalue()):
                time.sleep(0.02)
            if thread.is_alive():
                pass_("heartbeat thread alive after a failing state write")
            else:
                fail("heartbeat thread died on a failing state write")

            # Clear the obstruction; the next cycle should succeed.
            for _ in range(50):
                try:
                    os.rmdir(blocked)
                    break
                except OSError:
                    time.sleep(0.05)
            deadline = time.time() + 5
            while time.time() < deadline and not os.path.exists(blocked):
                time.sleep(0.02)

            srv._shutting_down = True
            thread.join(timeout=5)

        if os.path.exists(blocked):
            pass_("state file rewritten after the obstruction was cleared")
        else:
            fail("state file was not rewritten after the obstruction was cleared")

        if "resumed" in buf.getvalue():
            pass_("recovery notice emitted for the state sink")
        else:
            fail("no recovery notice after the state sink recovered")
    finally:
        srv._shutting_down = True
        if thread is not None:
            thread.join(timeout=5)
        srv.STATE_FILE, srv._startup_state, srv._shutting_down, srv.time = saved
        _reset_sink_warn_state("state")
        shutil.rmtree(root, ignore_errors=True)


def test_sink_emission_survives_failing_stderr():
    """The guard's own warning/recovery emission must not raise.

    The motivating fault: the server's stderr is a file on the same volume as
    the state file, so a full disk breaks the sink write and the warning print
    together. Before Step 4 the emission escaped the guard — log_trace and
    write_state raised anyway, and a real heartbeat_loop thread died, which is
    the original harm returning through the reporting path.
    """
    print("\n--- Test: Sink Emission Survives Failing stderr ---")

    import claude_retry_proxy.server as srv

    root = tempfile.mkdtemp(prefix="proxy_stderr_fail_")
    good_state = os.path.join(root, "state.json")
    blocked_state = os.path.join(root, "state-is-a-directory")
    blocked_trace = os.path.join(root, "trace-is-a-directory")
    os.mkdir(blocked_state)
    os.mkdir(blocked_trace)

    _reset_sink_warn_state("trace")
    _reset_sink_warn_state("state")
    saved = (srv.PROXY_TRACE_FILE, srv.STATE_FILE, srv._startup_state,
             srv._shutting_down, srv.time, sys.stderr)
    thread = None
    try:
        sys.stderr = _FailingStderr()

        # (1) Blocked trace path — the sink fails AND the warning print fails.
        srv.PROXY_TRACE_FILE = blocked_trace
        try:
            result = srv.log_trace({"event": "stderr_fail_probe"})
            if result is False:
                pass_("log_trace returned False without raising")
            else:
                fail("log_trace returned {!r}, expected False".format(result))
        except Exception as e:
            fail("log_trace raised with a failing stderr: {!r}".format(e))

        # (2) Success path — the recovery emission cannot raise either.
        srv.STATE_FILE = good_state
        try:
            result = srv.write_state({"pid": 1})
            if result is True:
                pass_("write_state returned True without raising (good path)")
            else:
                fail("write_state returned {!r}, expected True".format(result))
        except Exception as e:
            fail("write_state raised with a failing stderr: {!r}".format(e))

        # (3) Blocked state path — fails and opens a reportable episode.
        srv.STATE_FILE = blocked_state
        try:
            result = srv.write_state({"pid": 1})
            if result is False:
                pass_("write_state returned False without raising (blocked path)")
            else:
                fail("write_state returned {!r}, expected False".format(result))
        except Exception as e:
            fail("write_state raised with a failing stderr: {!r}".format(e))

        # (4) Closing the open episode must not raise.
        try:
            srv._note_sink_recovery("state")
            pass_("_note_sink_recovery did not raise")
        except Exception as e:
            fail("_note_sink_recovery raised with a failing stderr: {!r}".format(e))

        # (5) A real heartbeat thread survives the whole condition.
        srv._startup_state = {
            "pid": 12345,
            "port": 8080,
            "started_at": "2026-09-10T00:00:00Z",
            "owner_pid": 54321,
            "last_heartbeat": "2026-09-10T00:00:00Z",
            "last_request_at": "2026-09-10T00:00:00Z",
        }
        srv._shutting_down = False
        srv.time = _FastTime()
        thread = threading.Thread(target=srv.heartbeat_loop, daemon=True)
        thread.start()
        time.sleep(1.0)
        alive = thread.is_alive()
        srv._shutting_down = True
        thread.join(timeout=5)
        if alive:
            pass_("heartbeat thread survived failing writes with a failing stderr")
        else:
            fail("heartbeat thread died — the guard's own emission raised")
    finally:
        srv._shutting_down = True
        if thread is not None:
            thread.join(timeout=5)
        srv.PROXY_TRACE_FILE, srv.STATE_FILE, srv._startup_state, \
            srv._shutting_down, srv.time, sys.stderr = saved
        _reset_sink_warn_state("trace")
        _reset_sink_warn_state("state")
        shutil.rmtree(root, ignore_errors=True)


def test_best_effort_stderr_wrapper():
    """_BestEffortStderr makes a failing stderr stream non-raising.

    server.py holds ~40 runtime diagnostics, several inside the retry loop's
    try block. An OSError from one of those prints is read by the loop's
    `except (socket.error, ConnectionError, OSError)` clause as a connection
    error, so guarding the stream covers every present and future print site.
    """
    print("\n--- Test: Best-Effort stderr Wrapper ---")

    import claude_retry_proxy.server as srv

    # (1) A raising stream: write returns a length instead of raising.
    w = srv._BestEffortStderr(_FailingStderr())
    try:
        result = w.write("hello")
        if result == 5:
            pass_("write over a raising stream returned len(data)=5, no raise")
        else:
            fail("write returned {!r}, expected 5".format(result))
    except Exception as e:
        fail("write raised out of the wrapper: {!r}".format(e))

    # (1b) The failure return is total: a payload with no __len__ must not turn
    # the swallowed write failure into a TypeError escaping the wrapper.
    try:
        result = w.write(42)
        if result == 0:
            pass_("write(42) over a raising stream returned 0, no TypeError")
        else:
            fail("write(42) returned {!r}, expected 0".format(result))
    except Exception as e:
        fail("write(42) raised out of the wrapper: {!r}".format(e))

    # (2) flush over the raising stream is swallowed.
    try:
        w.flush()
        pass_("flush over a raising stream is silent")
    except Exception as e:
        fail("flush raised out of the wrapper: {!r}".format(e))

    # (3) Attribute access delegates to the wrapped stream.
    inner = _FailingStderr()
    w2 = srv._BestEffortStderr(inner)
    if w2.encoding == "utf-8":
        pass_("`encoding` delegates to the wrapped stream: {!r}".format(w2.encoding))
    else:
        fail("`encoding` did not delegate, got {!r}".format(getattr(w2, "encoding", None)))
    try:
        if w2.isatty() is False:
            pass_("`isatty()` delegates to the wrapped stream")
        else:
            fail("`isatty()` did not delegate")
    except Exception as e:
        fail("`isatty()` raised instead of delegating: {!r}".format(e))

    # (4) A healthy wrapped stream still receives the text.
    healthy = io.StringIO()
    w3 = srv._BestEffortStderr(healthy)
    w3.write("delegated text")
    if healthy.getvalue() == "delegated text":
        pass_("healthy wrapped stream receives the text")
    else:
        fail("healthy stream got {!r}".format(healthy.getvalue()))


ALL_TESTS = [
    ("start-prunes-old-trace-entries", test_start_prunes_old_trace_entries),
    ("prune-trace-file-edge-cases", test_prune_trace_file_edge_cases),
    ("trace-markers", test_trace_markers),
    ("trace-logs-oversized-body", test_trace_logs_oversized_body),
    ("relative-log-path", test_relative_log_path),
    ("retry-trace-event-enriched", test_retry_trace_event_enriched),
    ("extra-request-headers-in-trace", test_extra_request_headers_in_trace),
    ("trace-includes-key-name-not-payload", test_trace_includes_key_name_not_payload),
    ("sink-failure-does-not-drop-response", test_sink_failure_does_not_drop_response),
    ("sink-warning-rate-limit", test_sink_warning_rate_limit),
    ("sink-recovery-notice", test_sink_recovery_notice),
    ("trace-sink-creates-missing-directories", test_trace_sink_creates_missing_directories),
    ("heartbeat-survives-failed-state-write", test_heartbeat_survives_failed_state_write),
    ("sink-emission-survives-failing-stderr", test_sink_emission_survives_failing_stderr),
    ("best-effort-stderr-wrapper", test_best_effort_stderr_wrapper),
]


if __name__ == "__main__":
    run_cli(ALL_TESTS, "claude-retry-proxy tests: test_trace")
