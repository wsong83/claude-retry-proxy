"""Response-header contracts plus the trace model cap and the analyzer's
terminal-escape treatment (plan 2026-11-13-operator-output-hygiene).

Contracts pinned here:
  - exactly one Date on every response (the proxy's own);
  - no proxy Server header ever (no BaseHTTP/Python disclosure);
  - the upstream Server forwarded verbatim on forwarded responses;
  - the trace entry's client-derived model string capped at 512 chars,
    head kept, with the visible truncation marker;
  - the analyzer escapes terminal-hostile characters in the model label;
  - the response Content-Type *dispatch* is case-insensitive per RFC 9110
    field-name rules (plan 2026-11-20-fix-response-content-type-casing): a
    lowercased `content-type` name — every HTTP/2 connection, some HTTP/1.1
    gateways — still takes the anthropic JSON rewrite, the anthropic SSE
    message_start rewrite, the chat-mode SSE conversion, and the non-2xx
    anthropic JSON rewrite, while forwarded header casing is unchanged.
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
    _parse_sse_frames,
    _spawn_proxy_with_bind_retry,
    _sse_frames_with_type,
    _sse_types,
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
# The upstream's own view of the model name, and the tier alias the proxy
# must rewrite it to. Distinct strings so a passthrough is visible.
_UPSTREAM_MODEL = "claude-sonnet-5"
_TIER_ALIAS = "sonnet"

# The anthropic-mode SSE event sequence shared by the canonical-casing and
# lowercased-name stubs; only the header casing differs between them.
_ANTHROPIC_SSE_EVENTS = (
    b'event: message_start\ndata: {"type": "message_start", "message": {"model": "m"}}\n\n',
    b'event: content_block_start\ndata: {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}\n\n',
    b'event: content_block_stop\ndata: {"type": "content_block_stop", "index": 0}\n\n',
    b'event: message_delta\ndata: {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 1}}\n\n',
    b'event: message_stop\ndata: {"type": "message_stop"}\n\n',
)

# Chat-completions SSE frames (data-only, as OpenAI-compatible providers
# emit them) ending with the [DONE] sentinel.
_CHAT_SSE_EVENTS = (
    b'data: {"id": "c1", "object": "chat.completion.chunk", "created": 1, '
    b'"model": "gpt-4o", "choices": [{"index": 0, '
    b'"delta": {"role": "assistant", "content": "hi"}, "finish_reason": null}]}\n\n',
    b'data: {"id": "c1", "object": "chat.completion.chunk", "created": 1, '
    b'"model": "gpt-4o", "choices": [{"index": 0, '
    b'"delta": {}, "finish_reason": "stop"}]}\n\n',
    b'data: [DONE]\n\n',
)


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
        self.send_response_only(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Server", _UPSTREAM_SERVER)
        self.send_header("Date", _UPSTREAM_DATE)
        self.end_headers()
        for ev in _ANTHROPIC_SSE_EVENTS:
            self.wfile.write(ev)
        self.wfile.flush()


# --- Lowercased response-header-name stubs ---------------------------------
#
# BaseHTTPRequestHandler.send_header writes the header name verbatim to the
# wire, so each stub below emits exactly the lowercased `content-type` an
# HTTP/2 connection (and some HTTP/1.1 gateways) produces. The dispatch must
# still be identical to the canonical-casing path (RFC 9110 field names are
# case-insensitive); forwarding must keep the received casing.

class _LowercaseJSONUpstream(http.server.BaseHTTPRequestHandler):
    """200 JSON under a lowercased `content-type` name; model is the upstream's."""
    def do_POST(self):
        content_len = int(self.headers.get("Content-Length", 0))
        if content_len:
            self.rfile.read(content_len)
        body = json.dumps({
            "id": "ok", "type": "message", "role": "assistant",
            "model": _UPSTREAM_MODEL,
            "content": [{"type": "text", "text": "x"}],
            "stop_reason": "end_turn", "stop_sequence": None,
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }).encode()
        self.send_response_only(200)
        self.send_header("content-type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass


class _LowercaseSSEUpstream(http.server.BaseHTTPRequestHandler):
    """200 anthropic SSE under a lowercased `content-type` name."""
    def do_POST(self):
        content_len = int(self.headers.get("Content-Length", 0))
        if content_len:
            self.rfile.read(content_len)
        self.send_response_only(200)
        self.send_header("content-type", "text/event-stream")
        self.end_headers()
        for ev in _ANTHROPIC_SSE_EVENTS:
            self.wfile.write(ev)
        self.wfile.flush()

    def log_message(self, fmt, *args):
        pass


class _LowercaseChatSSEUpstream(http.server.BaseHTTPRequestHandler):
    """200 chat-completions SSE under a lowercased `content-type` name."""
    def do_POST(self):
        content_len = int(self.headers.get("Content-Length", 0))
        if content_len:
            self.rfile.read(content_len)
        self.send_response_only(200)
        self.send_header("content-type", "text/event-stream")
        self.end_headers()
        for ev in _CHAT_SSE_EVENTS:
            self.wfile.write(ev)
        self.wfile.flush()

    def log_message(self, fmt, *args):
        pass


class _LowercaseErrorUpstream(http.server.BaseHTTPRequestHandler):
    """400 JSON under a lowercased `content-type` name, with a top-level model."""
    def do_POST(self):
        content_len = int(self.headers.get("Content-Length", 0))
        if content_len:
            self.rfile.read(content_len)
        body = json.dumps({
            "type": "error",
            "error": {"type": "invalid_request_error", "message": "bad request"},
            "model": _UPSTREAM_MODEL,
        }).encode()
        self.send_response_only(400)
        self.send_header("content-type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass


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


def _start_env(temp_dir, upstream_port, trace_file=None, mode=None):
    """Start a proxy against an upstream port.

    mode: optional provider mode written into the keys file ("chat" /
    "response"); None leaves the vendor anthropic (no mode field).
    """
    config = _create_test_config(temp_dir, _TIERS)
    vendor = {"url": "http://127.0.0.1:{}".format(upstream_port), "key": "k"}
    if mode is not None:
        vendor["mode"] = mode
    keys = _create_test_keys_plain(temp_dir, {"p": vendor})
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


def test_lowercase_resp_content_type_anthropic_json_rewrites_model():
    """A lowercased response `content-type: application/json` still dispatches
    the anthropic 2xx JSON branch, so the body's model is rewritten to the
    tier alias.

    Pre-fix the canonical-spelling lookup on the received-casing header dict
    returned "" and the body was streamed through untouched — the client saw
    the upstream's own model name.
    """
    print("\n--- Test: Lowercase Response Content-Type — Anthropic JSON Rewrite ---")
    temp_dir = tempfile.mkdtemp(prefix="hdr_lc_json_")
    upstream = _start_upstream(_LowercaseJSONUpstream)
    try:
        port, proc, probe_ok, _trace = _start_env(
            temp_dir, upstream.server_address[1])
        if not probe_ok:
            fail("lowercase-json: proxy failed to start")
            return
        try:
            status, _headers, body = _get_headers_body(
                port, "POST", "/v1/messages",
                json.dumps({"model": "sonnet",
                            "messages": [{"role": "user", "content": "hi"}]}))
            if status != 200:
                fail("lowercase-json: expected 200, got {}".format(status))
                return
            try:
                data = json.loads(body)
            except Exception:
                fail("lowercase-json: response is not valid JSON: {!r}"
                     .format(body[:200]))
                return
            model = data.get("model") if isinstance(data, dict) else None
            if model != _TIER_ALIAS:
                fail("lowercase-json: expected model rewritten to the tier "
                     "alias {!r}, got {!r} (pre-fix the upstream name "
                     "'{}' passes through raw)".format(
                         _TIER_ALIAS, model, _UPSTREAM_MODEL))
                return
            pass_("lowercase-json: lowercased content-type dispatches the "
                  "anthropic JSON model rewrite")
        finally:
            _stop(proc)
    finally:
        _stop_upstream(upstream)
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_lowercase_resp_content_type_anthropic_sse_rewrites_message_start():
    """A lowercased response `content-type: text/event-stream` still takes the
    anthropic SSE branch: the first event's message_start.message.model is
    rewritten to the tier alias (the raw passthrough would not rewrite).

    Also pins that forwarding keeps the RECEIVED header casing — the
    lowercased `content-type` name reaches the client unchanged.
    """
    print("\n--- Test: Lowercase Response Content-Type — Anthropic SSE Rewrite ---")
    temp_dir = tempfile.mkdtemp(prefix="hdr_lc_sse_")
    upstream = _start_upstream(_LowercaseSSEUpstream)
    try:
        port, proc, probe_ok, _trace = _start_env(
            temp_dir, upstream.server_address[1])
        if not probe_ok:
            fail("lowercase-sse: proxy failed to start")
            return
        try:
            status, headers, body = _get_headers_body(
                port, "POST", "/v1/messages",
                json.dumps({"model": "sonnet", "stream": True,
                            "messages": [{"role": "user", "content": "hi"}]}))
            if status != 200:
                fail("lowercase-sse: expected 200, got {}".format(status))
                return
            if b"message_stop" not in body:
                fail("lowercase-sse: SSE body was not relayed (got {!r})"
                     .format(body[:200]))
                return
            forwarded = [k for k, _v in headers if k.lower() == "content-type"]
            if forwarded != ["content-type"]:
                fail("lowercase-sse: expected the received header casing "
                     "'content-type' forwarded verbatim, got {!r}"
                     .format(forwarded))
                return
            frames = _parse_sse_frames(body)
            starts = _sse_frames_with_type(frames, "message_start")
            if not starts:
                fail("lowercase-sse: no message_start frame in {!r}"
                     .format(_sse_types(frames)))
                return
            msg = starts[0].get("message") or {}
            model = msg.get("model")
            if model != _TIER_ALIAS:
                fail("lowercase-sse: expected message_start.message.model "
                     "{!r}, got {!r} (pre-fix the SSE branch is skipped and "
                     "the upstream model passes through raw)".format(
                         _TIER_ALIAS, model))
                return
            pass_("lowercase-sse: lowercased content-type dispatches the SSE "
                  "message_start rewrite; received header casing forwarded")
        finally:
            _stop(proc)
    finally:
        _stop_upstream(upstream)
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_lowercase_resp_content_type_chat_sse_streamed_as_anthropic():
    """A lowercased response `content-type: text/event-stream` from a chat-mode
    provider still takes the SSE branch: the client receives Anthropic-shaped
    events and the trace records no transform_failure.

    Pre-fix the header is missed, the chat stream is buffered whole, the
    chat→anthropic transform fails on SSE text (transform_failure), and the
    raw chat body passes through.
    """
    print("\n--- Test: Lowercase Response Content-Type — Chat SSE To Anthropic ---")
    temp_dir = tempfile.mkdtemp(prefix="hdr_lc_chat_sse_")
    upstream = _start_upstream(_LowercaseChatSSEUpstream)
    try:
        port, proc, probe_ok, trace_file = _start_env(
            temp_dir, upstream.server_address[1], mode="chat")
        if not probe_ok:
            fail("lowercase-chat-sse: proxy failed to start")
            return
        try:
            status, _headers, body = _get_headers_body(
                port, "POST", "/v1/messages",
                json.dumps({"model": "sonnet", "stream": True,
                            "messages": [{"role": "user", "content": "hi"}]}))
            if status != 200:
                fail("lowercase-chat-sse: expected 200, got {}".format(status))
                return
            frames = _parse_sse_frames(body)
            types = _sse_types(frames)
            required = ("message_start", "content_block_start",
                        "content_block_delta", "content_block_stop",
                        "message_delta", "message_stop")
            missing = [t for t in required if t not in types]
            if missing:
                fail("lowercase-chat-sse: not converted to Anthropic events "
                     "(missing {}; got {}; raw begins {!r})".format(
                         missing, types, body[:120]))
                return
            if b'"object": "chat.completion.chunk"' in body:
                fail("lowercase-chat-sse: raw chat frames leaked to the client")
                return
            if b"[DONE]" in body:
                fail("lowercase-chat-sse: [DONE] sentinel leaked into the "
                     "client stream")
                return
            failures = _trace_events_named(trace_file, "transform_failure")
            if failures:
                fail("lowercase-chat-sse: expected no transform_failure, got "
                     "{} event(s): {!r}".format(len(failures), failures[:1]))
                return
            pass_("lowercase-chat-sse: lowercased content-type dispatches the "
                  "chat SSE conversion, no transform_failure")
        finally:
            _stop(proc)
    finally:
        _stop_upstream(upstream)
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_lowercase_resp_content_type_non2xx_anthropic_json_rewrite():
    """A lowercased response `content-type: application/json` on a non-2xx
    anthropic response still rewrites the error body's top-level model to the
    tier alias (pre-fix the body passes through with the upstream name)."""
    print("\n--- Test: Lowercase Response Content-Type — Non-2xx JSON Rewrite ---")
    temp_dir = tempfile.mkdtemp(prefix="hdr_lc_non2xx_")
    upstream = _start_upstream(_LowercaseErrorUpstream)
    try:
        port, proc, probe_ok, _trace = _start_env(
            temp_dir, upstream.server_address[1])
        if not probe_ok:
            fail("lowercase-non2xx: proxy failed to start")
            return
        try:
            status, _headers, body = _get_headers_body(
                port, "POST", "/v1/messages",
                json.dumps({"model": "sonnet",
                            "messages": [{"role": "user", "content": "hi"}]}))
            if status != 400:
                fail("lowercase-non2xx: expected 400, got {}".format(status))
                return
            try:
                data = json.loads(body)
            except Exception:
                fail("lowercase-non2xx: response is not valid JSON: {!r}"
                     .format(body[:200]))
                return
            model = data.get("model") if isinstance(data, dict) else None
            if model != _TIER_ALIAS:
                fail("lowercase-non2xx: expected top-level model rewritten to "
                     "{!r}, got {!r} (pre-fix the upstream name '{}' passes "
                     "through raw)".format(_TIER_ALIAS, model, _UPSTREAM_MODEL))
                return
            err = data.get("error") if isinstance(data, dict) else None
            if not isinstance(err, dict) or err.get("type") != "invalid_request_error":
                fail("lowercase-non2xx: upstream error body not preserved: {!r}"
                     .format(data))
                return
            pass_("lowercase-non2xx: lowercased content-type dispatches the "
                  "non-2xx anthropic JSON rewrite")
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
    ("lowercase-resp-content-type-anthropic-json-rewrite",
     test_lowercase_resp_content_type_anthropic_json_rewrites_model),
    ("lowercase-resp-content-type-anthropic-sse-rewrite",
     test_lowercase_resp_content_type_anthropic_sse_rewrites_message_start),
    ("lowercase-resp-content-type-chat-sse-to-anthropic",
     test_lowercase_resp_content_type_chat_sse_streamed_as_anthropic),
    ("lowercase-resp-content-type-non2xx-json-rewrite",
     test_lowercase_resp_content_type_non2xx_anthropic_json_rewrite),
    ("trace-model-field-capped", test_trace_model_field_capped),
    ("analyzer-model-escape", test_analyzer_model_escape),
]


if __name__ == "__main__":
    run_cli(ALL_TESTS, "response-header contracts / trace model cap / analyzer escape")
