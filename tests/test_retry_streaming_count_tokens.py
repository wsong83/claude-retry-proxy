"""count_tokens retry-flag tests: disable_retry_claude_count_tokens across
503 and connection-error failures, path anchoring, type validation, the
retry-on-false default, and the unaffected normal path."""

import http
import json
import os
import shutil
import socket
import subprocess
import tempfile
import threading
import time
from _harness import PROXY_SERVER, _create_test_config_with_flag, _create_test_keys, _derive_models_from_tiers, _drain_child_stderr, _send_proxy_request, fail, find_free_port, pass_, run_cli


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
    _drain_child_stderr(proc)
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
    _drain_child_stderr(proc)
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

        if status == 502:
            try:
                data = json.loads(resp_body)
            except Exception as e:
                fail("conn-error response is not valid JSON: {} ({!r})".format(
                    e, resp_body[:200]))
                data = None
            if data is not None:
                code = (data.get("error") or {}).get("code")
                if code == "upstream_unreachable":
                    pass_("Client received parseable 502 upstream_unreachable")
                else:
                    fail("expected error.code upstream_unreachable, got {!r}".format(code))
        elif status == 0:
            fail("Client received status 0 — the response is unparseable")
        else:
            fail(f"Client received {status}, expected 502 (upstream unreachable)")

        # The trace 'error' field carries the same envelope body.
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
    _drain_child_stderr(proc)
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
    _drain_child_stderr(proc)
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
    _drain_child_stderr(proc)
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
    """validate_config rejects the two models.json riders' invalid shapes:
    a non-boolean disable_retry_claude_count_token, and an invalid
    reasoning_field_switch policy — non-int/bool field values, values below
    1, unknown inner keys, a non-object value, and the effective-pair
    ordering rule (defaults applied first, so {"saturation_max": 2} against
    the defaulted saturation_on_switch 3 is rejected, not silently clamped)."""
    print("\n--- Test: Config Riders (invalid types rejected) ---")

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

    # --- reasoning_field_switch: the second rider's rejection surface ------
    def switch_errors(switch):
        cfg = {"tiers": valid_tiers,
               "models": _derive_models_from_tiers(valid_tiers),
               "reasoning_field_switch": switch}
        return validate_config(cfg, set(vendors.keys()))

    # Effective-pair rejection: the defaulted saturation_on_switch (3) exceeds
    # the explicit saturation_max 2 — rejected, not silently clamped to 2/2.
    errors = switch_errors({"saturation_max": 2})
    if any("saturation_on_switch" in e for e in errors):
        pass_("validate_config rejected the effective pair "
              "{'saturation_max': 2} against the defaulted 3")
    else:
        fail("validate_config accepted saturation_max 2 against the "
             f"defaulted saturation_on_switch 3: {errors}")

    for bad, label in ((True, "a non-object policy"),
                       ({"saturation_max": True}, "boolean saturation_max"),
                       ({"saturation_on_switch": False},
                        "boolean saturation_on_switch"),
                       ({"saturation_max": "4"}, "string saturation_max"),
                       ({"saturation_max": 0}, "zero saturation_max"),
                       ({"saturation_on_switch": -1},
                        "negative saturation_on_switch"),
                       ({"saturation_max": 4, "saturation_on_switch": 5},
                        "saturation_on_switch above saturation_max"),
                       ({"saturation_maxx": 4}, "unknown inner key")):
        errors = switch_errors(bad)
        if any("reasoning_field_switch" in e for e in errors):
            pass_(f"validate_config rejected {label}")
        else:
            fail(f"validate_config accepted {label} ({bad!r}): {errors}")

    # A valid non-default pair is accepted.
    errors = switch_errors({"saturation_max": 4, "saturation_on_switch": 2})
    if errors:
        fail(f"validate_config rejected a valid reasoning_field_switch pair: "
             f"{errors}")
    else:
        pass_("validate_config accepted a valid reasoning_field_switch pair (4/2)")


ALL_TESTS = [
    ("disable-retry-count-tokens-503", test_disable_retry_count_tokens_503),
    ("disable-retry-count-tokens-conn-error", test_disable_retry_count_tokens_conn_error),
    ("disable-retry-count-tokens-normal-path-unaffected", test_disable_retry_count_tokens_normal_path_unaffected),
    ("disable-retry-count-tokens-false-retries", test_disable_retry_count_tokens_false_retries),
    ("disable-retry-count-tokens-path-anchoring", test_disable_retry_count_tokens_path_anchoring),
    ("disable-retry-count-tokens-invalid-type", test_disable_retry_count_tokens_invalid_type),
]


if __name__ == "__main__":
    run_cli(ALL_TESTS, "claude-retry-proxy tests: test_retry_streaming_count_tokens")
