"""Response-header contracts plus the trace model cap and the analyzer's
terminal-escape treatment (plan 2026-11-13-operator-output-hygiene).

Contracts pinned here:
  - exactly one Date on every response (the proxy's own);
  - no proxy Server header ever (no BaseHTTP/Python disclosure);
  - the upstream Server forwarded verbatim on forwarded responses;
  - the trace entry's client-derived model string capped at 512 chars,
    head kept, with the visible truncation marker;
  - the analyzer escapes terminal-hostile characters in the model label.
"""
import http.client
import http.server
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone

from _harness import (
    _MockHTTPServer,
    _create_test_config,
    _create_test_keys_plain,
    _spawn_proxy_with_bind_retry,
    _trace_events_named,
    fail,
    find_free_port,
    pass_,
    run_cli,
)

_TIERS = {
    "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
    "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
    "opus": {"provider": "p", "model": "claude-opus-5"},
}
_UPSTREAM_SERVER = "cloudflare-test"
_UPSTREAM_DATE = "Mon, 01 Jan 2024 00:00:00 GMT"
_MODEL_MARKER = "[proxy: model truncated]"


def _ok_body():
    return json.dumps({
        "id": "ok", "type": "message", "model": "m",
        "content": [{"type": "text", "text": "x"}],
        "stop_reason": "end_turn", "stop_sequence": None,
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }).encode()


class _HeadersUpstream(http.server.BaseHTTPRequestHandler):
    """Buffered upstream: one distinctive Server, one fixed Date.

    send_response_only (not send_response) so the mock itself emits no
    BaseHTTP Server/Date pair -- the response the proxy sees carries
    exactly the headers below, so "the proxy forwarded the upstream
    Server" cannot pass by accident.
    """
    def do_POST(self):
        content_len = int(self.headers.get("Content-Length", 0))
        if content_len:
            self.rfile.read(content_len)  # drain: undrained HTTP/1.0 close RSTs
        body = _ok_body()
        self.send_response_only(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Server", _UPSTREAM_SERVER)
        self.send_header("Date", _UPSTREAM_DATE)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass


class _HeadersUpstreamNoDate(_HeadersUpstream):
    """Upstream that sends no Date at all (HTTP/1.0-origin shape):
    the proxy must still emit exactly one Date -- its own."""
    def do_POST(self):
        content_len = int(self.headers.get("Content-Length", 0))
        if content_len:
            self.rfile.read(content_len)
        body = _ok_body()
        self.send_response_only(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Server", _UPSTREAM_SERVER)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class _HeadersUpstreamSSE(_HeadersUpstream):
    """Streamed upstream: same distinctive headers, an SSE body.

    The event sequence mirrors the suite's existing SSE mocks (see
    tests/test_retry_streaming.py); only the headers differ.
    """
    def do_POST(self):
        content_len = int(self.headers.get("Content-Length", 0))
        if content_len:
            self.rfile.read(content_len)  # drain: undrained HTTP/1.0 close RSTs
        events = (
            b'event: message_start\ndata: {"type": "message_start", "message": {"model": "m"}}\n\n',
            b'event: content_block_start\ndata: {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}\n\n',
            b'event: content_block_stop\ndata: {"type": "content_block_stop", "index": 0}\n\n',
            b'event: message_delta\ndata: {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 1}}\n\n',
            b'event: message_stop\ndata: {"type": "message_stop"}\n\n',
        )
        self.send_response_only(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Server", _UPSTREAM_SERVER)
        self.send_header("Date", _UPSTREAM_DATE)
        self.end_headers()
        for ev in events:
            self.wfile.write(ev)
        self.wfile.flush()


def _get_headers(port, method, path, body=None, timeout=10):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    conn.request(method, path, body=body,
                 headers={"Content-Type": "application/json"})
    resp = conn.getresponse()
    headers = resp.getheaders()
    resp.read()
    conn.close()
    return resp.status, headers


def _get_headers_body(port, method, path, body=None, timeout=10):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    conn.request(method, path, body=body,
                 headers={"Content-Type": "application/json"})
    resp = conn.getresponse()
    headers = resp.getheaders()
    resp_body = resp.read()
    conn.close()
    return resp.status, headers, resp_body


def _dates(headers):
    return [v for k, v in headers if k.lower() == "date"]


def _servers(headers):
    return [v for k, v in headers if k.lower() == "server"]


def _start_env(temp_dir, upstream_port, trace_file=None):
    config = _create_test_config(temp_dir, _TIERS)
    keys = _create_test_keys_plain(temp_dir, {"p": {
        "url": "http://127.0.0.1:{}".format(upstream_port), "key": "k"}})
    if trace_file is None:
        trace_fd, trace_file = tempfile.mkstemp(suffix=".jsonl", dir=temp_dir)
        os.close(trace_fd)
    port, proc, probe_ok = _spawn_proxy_with_bind_retry(
        find_free_port(), config_path=config, keys_path=keys,
        passphrase=None, trace_file=trace_file)
    return port, proc, probe_ok, trace_file


def _stop(proc):
    if proc is None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def _start_upstream(handler_cls):
    server = _MockHTTPServer(("127.0.0.1", 0), handler_cls)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _stop_upstream(server):
    server.shutdown()
    server.server_close()


def test_response_headers_buffered():
    print("\n--- Test: Response Headers Buffered ---")
    temp_dir = tempfile.mkdtemp(prefix="hdr_buffered_")
    upstream = _start_upstream(_HeadersUpstream)
    try:
        port, proc, probe_ok, _trace = _start_env(
            temp_dir, upstream.server_address[1])
        if not probe_ok:
            fail("buffered: proxy failed to start")
            return
        try:
            status, headers = _get_headers(
                port, "POST", "/v1/messages",
                json.dumps({"model": "sonnet",
                            "messages": [{"role": "user", "content": "hi"}]}))
            if status != 200:
                fail("buffered: expected 200, got {}".format(status))
                return
            if len(_dates(headers)) != 1:
                fail("buffered: expected exactly 1 Date, got {!r}".format(
                    _dates(headers)))
                return
            if _servers(headers) != [_UPSTREAM_SERVER]:
                fail("buffered: expected only the upstream Server {!r}, "
                     "got {!r}".format(_UPSTREAM_SERVER, _servers(headers)))
                return
            pass_("buffered: one Date, upstream Server only, no disclosure")
        finally:
            _stop(proc)
    finally:
        _stop_upstream(upstream)
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_response_headers_streamed():
    print("\n--- Test: Response Headers Streamed ---")
    temp_dir = tempfile.mkdtemp(prefix="hdr_streamed_")
    upstream = _start_upstream(_HeadersUpstreamSSE)
    try:
        port, proc, probe_ok, _trace = _start_env(
            temp_dir, upstream.server_address[1])
        if not probe_ok:
            fail("streamed: proxy failed to start")
            return
        try:
            status, headers, body = _get_headers_body(
                port, "POST", "/v1/messages",
                json.dumps({"model": "sonnet", "stream": True,
                            "messages": [{"role": "user", "content": "hi"}]}))
            if status != 200:
                fail("streamed: expected 200, got {}".format(status))
                return
            if b"message_stop" not in body:
                fail("streamed: SSE body was not relayed (got {!r})"
                     .format(body[:200]))
                return
            if len(_dates(headers)) != 1:
                fail("streamed: expected exactly 1 Date, got {!r}".format(
                    _dates(headers)))
                return
            if _servers(headers) != [_UPSTREAM_SERVER]:
                fail("streamed: expected only the upstream Server {!r}, "
                     "got {!r}".format(_UPSTREAM_SERVER, _servers(headers)))
                return
            pass_("streamed: one Date, upstream Server only, no disclosure")
        finally:
            _stop(proc)
    finally:
        _stop_upstream(upstream)
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_response_headers_proxy_generated():
    print("\n--- Test: Response Headers Proxy-Generated ---")
    temp_dir = tempfile.mkdtemp(prefix="hdr_generated_")
    upstream = _start_upstream(_HeadersUpstream)
    try:
        port, proc, probe_ok, _trace = _start_env(
            temp_dir, upstream.server_address[1])
        if not probe_ok:
            fail("proxy-generated: proxy failed to start")
            return
        try:
            status, headers = _get_headers(
                port, "POST", "/v1/messages",
                json.dumps({"model": "no-such-model",
                            "messages": [{"role": "user", "content": "hi"}]}))
            if status != 400:
                fail("proxy-generated: expected 400, got {}".format(status))
                return
            if len(_dates(headers)) != 1:
                fail("proxy-generated: expected exactly 1 Date, got {!r}"
                     .format(_dates(headers)))
                return
            if _servers(headers) != []:
                fail("proxy-generated: expected no Server, got {!r}"
                     .format(_servers(headers)))
                return
            pass_("proxy-generated 400: one Date, no Server")
        finally:
            _stop(proc)
    finally:
        _stop_upstream(upstream)
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_response_headers_options():
    print("\n--- Test: Response Headers OPTIONS ---")
    temp_dir = tempfile.mkdtemp(prefix="hdr_options_")
    upstream = _start_upstream(_HeadersUpstream)
    try:
        port, proc, probe_ok, _trace = _start_env(
            temp_dir, upstream.server_address[1])
        if not probe_ok:
            fail("OPTIONS: proxy failed to start")
            return
        try:
            status, headers = _get_headers(port, "OPTIONS", "/v1/messages")
            if status != 200:
                fail("OPTIONS: expected 200, got {}".format(status))
                return
            if len(_dates(headers)) != 1:
                fail("OPTIONS: expected exactly 1 Date, got {!r}".format(
                    _dates(headers)))
                return
            if _servers(headers) != []:
                fail("OPTIONS: expected no Server, got {!r}".format(
                    _servers(headers)))
                return
            pass_("OPTIONS preflight: one Date, no Server")
        finally:
            _stop(proc)
    finally:
        _stop_upstream(upstream)
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_response_headers_upstream_no_date():
    print("\n--- Test: Response Headers Upstream Without Date ---")
    temp_dir = tempfile.mkdtemp(prefix="hdr_nodate_")
    upstream = _start_upstream(_HeadersUpstreamNoDate)
    try:
        port, proc, probe_ok, _trace = _start_env(
            temp_dir, upstream.server_address[1])
        if not probe_ok:
            fail("upstream-no-date: proxy failed to start")
            return
        try:
            status, headers = _get_headers(
                port, "POST", "/v1/messages",
                json.dumps({"model": "sonnet",
                            "messages": [{"role": "user", "content": "hi"}]}))
            if status != 200:
                fail("upstream-no-date: expected 200, got {}".format(status))
                return
            if _servers(headers) != [_UPSTREAM_SERVER]:
                fail("upstream-no-date: expected only the upstream Server "
                     "{!r}, got {!r}".format(_UPSTREAM_SERVER,
                                             _servers(headers)))
                return
            dates = _dates(headers)
            if len(dates) != 1:
                fail("upstream-no-date: expected exactly 1 Date (the proxy's "
                     "own), got {!r}".format(dates))
                return
            pass_("upstream sent no Date: proxy emitted exactly one Date")
        finally:
            _stop(proc)
    finally:
        _stop_upstream(upstream)
        shutil.rmtree(temp_dir, ignore_errors=True)


def _wait_request_events(trace_file, count, timeout_s=5.0):
    deadline = time.time() + timeout_s
    while True:
        events = [e for e in _trace_events_named(trace_file, "request")
                  if e.get("http_status") == 400]
        if len(events) >= count or time.time() >= deadline:
            return events
        time.sleep(0.05)


def test_trace_model_field_capped():
    print("\n--- Test: Trace Model Field Capped ---")
    temp_dir = tempfile.mkdtemp(prefix="trace_model_cap_")
    upstream = _start_upstream(_HeadersUpstream)
    try:
        port, proc, probe_ok, trace_file = _start_env(
            temp_dir, upstream.server_address[1])
        if not probe_ok:
            fail("trace-model: proxy failed to start")
            return
        try:
            models = ["A" * 512, "B" * 513, "C" * 600]
            for m in models:
                status, _headers = _get_headers(
                    port, "POST", "/v1/messages",
                    json.dumps({"model": m,
                                "messages": [{"role": "user",
                                              "content": "hi"}]}))
                if status != 400:
                    fail("trace-model: expected 400 for a {}-char unknown "
                         "model, got {}".format(len(m), status))
                    return
            events = _wait_request_events(trace_file, 3)
            if len(events) < 3:
                fail("trace-model: expected 3 request events with http_status "
                     "400, got {}".format(len(events)))
                return
            got = [e.get("model") for e in events[:3]]
            keep = 512 - len(_MODEL_MARKER)
            expected = [
                "A" * 512,
                "B" * keep + _MODEL_MARKER,
                "C" * keep + _MODEL_MARKER,
            ]
            if got != expected:
                fail("trace-model: capped values mismatch: got lengths {!r}, "
                     "expected lengths {!r}".format(
                         [len(g) if isinstance(g, str) else g for g in got],
                         [len(x) for x in expected]))
                return
            if _MODEL_MARKER in got[0]:
                fail("trace-model: the 512-char model gained a marker: {!r}"
                     .format(got[0][-40:]))
                return
            pass_("trace-model: 512 unchanged, 513/600 truncated head-kept "
                  "with the marker")
        finally:
            _stop(proc)
    finally:
        _stop_upstream(upstream)
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_analyzer_model_escape():
    print("\n--- Test: Analyzer Model Escape ---")
    temp_dir = tempfile.mkdtemp(prefix="analyzer_escape_")
    try:
        script = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "scripts", "analyze_proxy_trace.py")
        if not os.path.exists(script):
            fail("analyzer-escape: analyzer script not found at {}".format(script))
            return
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        hostile = "\x1b]0;pwned\x07\ud800sonnet"
        line = json.dumps({
            "timestamp": now,
            "event": "request",
            "request_id": "r1",
            "model": hostile,
            "status": "failure",
            "http_status": 400,
            "retries": 0,
            "total_latency_sec": 0,
        })
        trace_file = os.path.join(temp_dir, "hostile-trace.jsonl")
        with open(trace_file, "w", encoding="utf-8") as f:
            f.write(line + "\n")
        proc = subprocess.run(
            [sys.executable, script, "--trace-file", trace_file, "--days", "1"],
            capture_output=True, text=True, encoding="utf-8",
            errors="backslashreplace", timeout=60)
        out = proc.stdout
        if proc.returncode != 0:
            fail("analyzer-escape: analyzer exited {} (stderr tail: {!r})"
                 .format(proc.returncode, proc.stderr[-400:]))
            return
        if "\x1b" in out or "\x07" in out:
            fail("analyzer-escape: raw control byte reached stdout")
            return
        escaped = "\\x1b]0;pwned\\x07\\ud800sonnet"
        if escaped not in out:
            fail("analyzer-escape: escaped label {!r} not present in stdout"
                 .format(escaped))
            return
        pass_("analyzer-escape: hostile model escaped, exit 0, no raw ESC/BEL")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


ALL_TESTS = [
    ("response-headers-buffered-single-date-no-self-server",
     test_response_headers_buffered),
    ("response-headers-streamed-single-date-no-self-server",
     test_response_headers_streamed),
    ("response-headers-proxy-generated-no-server-one-date",
     test_response_headers_proxy_generated),
    ("response-headers-options-one-date-no-server",
     test_response_headers_options),
    ("response-headers-upstream-no-date",
     test_response_headers_upstream_no_date),
    ("trace-model-field-capped", test_trace_model_field_capped),
    ("analyzer-model-escape", test_analyzer_model_escape),
]


if __name__ == "__main__":
    run_cli(ALL_TESTS, "response-header contracts / trace model cap / analyzer escape")
