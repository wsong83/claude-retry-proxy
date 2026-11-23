#!/usr/bin/env python3
"""Multi-provider HTTP retry gateway for Claude API. Listens on localhost, routes
requests by model tier (haiku/sonnet/opus) to different upstream providers, retries
429/503/connection errors with jittered exponential backoff, and logs every request
to a JSONL trace file. Tier routing configured via ~/.claude/proxy/config.json;
provider credentials stored encrypted in ~/.claude/keys-index.json (vim blowfish2)
and decrypted at startup via passphrase prompt. Supports concurrent requests via
ThreadingHTTPServer.

Dependencies: cryptography (for vim blowfish2 decryption) and httpx2 (upstream
transport), plus Python stdlib (http.server, json, threading, uuid, signal,
socket, os, sys, time, argparse).
"""

import argparse
import http.server
import httpx2
import json
import os
import signal
import socket
import sys
import threading
import time
import uuid

from . import sinks
from . import admin_api
from . import runtime_state
from .admin_api import AdminHandlerMixin
from .chat_sse import ChatSSEHandlerMixin
from .config import load_config, validate_config
from .keys import load_keys_file, read_passphrase_from_stdin, vendor_key_names
from .nesting import (MAX_JSON_NESTING_DEPTH, _nesting_limit_message,
                      check_payload_nesting, nesting_event)
from .sanitize import sanitize_error
from .compat import (_compat_normalize_threshold, _compat_retry_lock,
                     _compat_state_lock, _compat_validate_constants,
                     _load_compat_state, _persist_compat_state_locked)
from .sinks import (log_trace, write_state, increment_total,
                    write_start_marker, write_stop_marker)
from .transforms_chat import (_anthropic_to_chat, _chat_to_anthropic,
                              _transform_anthropic_messages_to_chat,
                              _transform_anthropic_tool_choice_to_chat,
                              _transform_anthropic_tools_to_chat)
from .transforms_response import (_anthropic_to_response, _response_to_anthropic)
from .safety import _ADMIN_NAME_RE
from .settings import SETTINGS, resolve_trace_file
from . import forwarder
from .forwarder import (_DISCONNECT_ERRORS, _client_user_agent,
                        _error_body, _forward_request_impl, _note_swap_eviction,
                        _resolve_extra_request_headers, _retry_nudge_arm,
                        _retry_nudge_check, _retry_nudge_messages_bytes,
                        _retry_nudge_remember, _rewrite_json_response,
                        _rewrite_sse_event, _rng, _swap_epoch_changed,
                        _touch_upstream_activity, _trace_model,
                        CLIENT_USER_AGENT_MAX_CHARS,
                        CLIENT_USER_AGENT_TRUNCATION_MARKER,
                        RETRY_NUDGE_TTL_SECONDS, compute_delay,
                        compute_jittered_delay, extract_model, resolve_api_key)


# Bind the process-wide sinks to the resolved paths, exactly as the module-level
# path constants did before the extraction.
sinks.configure(trace_path=SETTINGS.trace_file, state_path=SETTINGS.state_file)


class _BestEffortStderr:
    """Wraps a stderr stream so diagnostic prints cannot raise into callers.

    Runtime stderr prints — server.py's own and, on the forward path,
    forwarder.py's — include several inside the retry loop's try block. A
    stderr write failure there (full disk — proxy-stderr.log sits on the same
    volume as the sinks) would be read by the loop's
    `except (httpx2.RequestError, httpx2.StreamError, OSError)` clause as a
    connection error, re-issuing the upstream POST or dropping an
    already-answered response. Guarding the stream covers every present and
    future print site.
    """

    def __init__(self, stream):
        self._stream = stream

    def write(self, data):
        try:
            return self._stream.write(data)
        except Exception:
            # Generic form: a payload with no __len__ must not turn the
            # swallowed write failure into a TypeError out of this wrapper.
            return len(data) if hasattr(data, "__len__") else 0

    def flush(self):
        try:
            self._stream.flush()
        except Exception:
            pass

    def __getattr__(self, name):
        return getattr(self._stream, name)


# ---------------------------------------------------------------------------
# HTTP request forwarding
# ---------------------------------------------------------------------------

def forward_request(method, path, headers, body, handler=None, request_id=None):
    """Forward a request to the upstream API with tier-based routing.

    Args:
        method, path, headers, body: request components
        handler: ProxyHandler instance for streaming responses
        request_id: unique request identifier for tracing

    Returns (status, response_headers, body_bytes, first_byte_ms, total_sec, retries, tier, provider, actual_model).
    total_sec covers the entire request including all retry waits.
    On 429 and 503, retries with jittered exponential backoff. 429 uses the
    maximal delay (SETTINGS.max_delay); 503 uses the exponential.
    When handler is provided and the upstream responds 2xx, the body is
    streamed to the client in real time via the handler (body_bytes is then
    b""); otherwise the body is buffered and returned.
    """
    # Drain-and-swap: snapshot config state at request start
    # If a config swap is in progress, wait for it to complete before proceeding
    # Snapshot config and vendors together under the same lock
    # to prevent race where config is read before lock but vendors is
    # snapshotted inside lock (reviewer-drain-swap-race fix).
    while True:
        with forwarder._config_lock:
            if not forwarder._config_swapping:
                # No swap in progress - increment counter and snapshot all state together
                forwarder._inflight_count += 1
                config_snapshot = runtime_state._current_config
                vendors_snapshot = runtime_state._vendors
                epoch_snapshot = forwarder._config_epoch
                break
        # Swap in progress - wait for it to complete
        forwarder._swap_done.wait()

    try:
        return _forward_request_impl(method, path, headers, body, handler, request_id,
                                     config_snapshot, vendors_snapshot, epoch_snapshot)
    finally:
        # Decrement counter when request completes (success or failure)
        with forwarder._config_lock:
            forwarder._inflight_count -= 1


# ---------------------------------------------------------------------------
# HTTP request handler
# ---------------------------------------------------------------------------

def _crlf_safe(headers):
    """Drop headers whose name or value contains CR/LF (response-splitting guard).

    A header name or value carrying a raw newline would let an upstream-injected
    value reach the client's parser as a different header set than the proxy
    parsed (parser-differential attack; cf. CVE-2019-9740/CVE-2019-9947). Omit
    such entries rather than forwarding them.
    """
    if not headers:
        return {}
    return {k: v for k, v in headers.items()
            if "\r" not in k and "\n" not in k
            and "\r" not in str(v) and "\n" not in str(v)}


class ProxyHandler(AdminHandlerMixin, ChatSSEHandlerMixin, http.server.BaseHTTPRequestHandler):

    def send_response(self, code, message=None):
        """send_response minus BaseHTTPRequestHandler's auto-emitted pair.

        The stock method emits "Server: BaseHTTP/0.6 Python/<version>" --
        an implementation disclosure -- and its own "Date" before the
        handler's headers, which the upstream-forwarding loops then
        duplicate. This override emits no Server ever (the upstream's is
        forwarded verbatim by the loops) and exactly one Date (the
        proxy's own; the loops skip the upstream's). log_request is
        preserved: the stderr access-log behavior is unchanged.
        """
        self.log_request(code)
        self.send_response_only(code, message)
        self.send_header("Date", self.date_time_string())

    def _send_response(self, status, body_bytes, headers=None):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        if headers:
            for k, v in _crlf_safe(headers).items():
                if k.lower() not in {"content-type", "transfer-encoding",
                                     "content-length", "connection", "date"}:
                    self.send_header(k, v)
        self.send_header("Content-Length", str(len(body_bytes)))
        self.end_headers()
        self.wfile.write(body_bytes)

    def _stream_upstream_response(self, resp, status, resp_headers, request_id, retries,
                                   epoch, tier=None, mode=None, tools_declared=False,
                                   provider=None, key=None, retry_original_id=None, *,
                                   content_type):
        """Stream an upstream 2xx response body to the client as it arrives.

        For SSE (text/event-stream):
          - anthropic mode: scans the stream's leading events under a 64 KB
            total budget and rewrites model in the first message_start event
            to the tier name (vendors may open with keep-alive frames, e.g.
            event:ping). Events before and after it forward unchanged; past
            the budget the stream forwards unscanned (the degrade).
          - chat mode: transforms the OpenAI chat-completions SSE stream into
            synthetic Anthropic Messages SSE events.
          - response mode: upstream SSE is unexpected (the request transform
            forces stream:false); handled by a defensive terminal-only fallback.

        For other content types: streams unchanged.

        The upstream read bound is the client's `PROXY_READ_TIMEOUT` (uniform
        connect/read/write/pool timeout), replacing the old hardcoded 300 s
        socket timeout. There is no mid-stream timeout API in httpx2, so a
        stream silent at a swap press wakes at its NEXT READ BOUNDARY — within
        the read timeout, no longer the old 30 s armed wake — and is then
        evicted retryably. That residual is accepted by design: reaching into
        httpcore2 internals to interrupt a blocked read is deliberately not
        done.

        A stream admitted before a completed swap is a straggler: the epoch
        check after each read closes it with the retryable config_swap_restart
        error instead of delivering old-routing bytes. The residual window
        (bytes already read under the old routing when the epoch bumps) is the
        accepted chunk-granularity bound.

        Returns the first-byte latency in ms, or None if aborted.
        """
        first_byte_start = time.time()
        first_byte_ms = None
        first_chunk = True
        bytes_streamed = 0

        def evict_stream():
            """Close a straggler stream with the retryable swap error.

            The in-stream `event: error` mirrors the existing emission
            precedent (response_frame_encode_failure). When nothing has been
            written to the client yet, a minimal message_start opens the
            stream first — an error frame with no preceding message_start is
            a shape clients may not surface correctly.
            """
            _note_swap_eviction("stream", request_id, tier=tier, provider=provider)
            if first_byte_ms is None:
                self.wfile.write(self._sse_event({
                    "type": "message_start",
                    "message": {"id": "msg_" + str(uuid.uuid4()),
                                "type": "message", "role": "assistant",
                                "content": [], "model": tier,
                                "stop_reason": None, "stop_sequence": None,
                                "usage": {"input_tokens": 0, "output_tokens": 0}}},
                    request_id))
            self.wfile.write(b"event: error\ndata: " + _error_body(
                "api_error", "config_swap_restart",
                "config swap in progress: this request was restarted; "
                "the client should retry",
                request_id) + b"\n\n")
            self.wfile.flush()

        # content_type is resolved once by the forwarder's case-insensitive
        # dispatch and threaded here: this method must agree with that
        # dispatch, and re-deriving from the received-casing resp_headers
        # dict would repeat the canonical-spelling lookup defect.
        is_sse = "text/event-stream" in content_type

        try:
            self.send_response(status)
            # Forward all other headers verbatim, including content-type
            # (required for text/event-stream SSE responses). Drop hop-by-hop
            # headers — transfer framing is handled by the library, and the
            # response is close-delimited via HTTP/1.0.
            for k, v in _crlf_safe(resp_headers).items():
                if k.lower() not in {"transfer-encoding", "content-length",
                                     "connection", "date"}:
                    self.send_header(k, v)
            self.end_headers()

            if is_sse and tier:
                if mode == "chat":
                    return self._stream_chat_sse_to_anthropic(
                        resp, request_id, tier, first_byte_start, epoch,
                        tools_declared=tools_declared, provider=provider, key=key,
                        retry_original_id=retry_original_id)
                if mode == "response":
                    return self._stream_response_sse_fallback(
                        resp, request_id, tier, first_byte_start, epoch)
                # SSE path (anthropic mode): scan the stream's leading events
                # for the message_start rewrite. Vendors may open with
                # keep-alive frames (qwen sends event:ping before
                # message_start), so the rewrite targets the first
                # message_start event at any position, under a total byte
                # budget — past it the scan gives up and the stream forwards
                # unscanned (the documented degrade).
                scanned = bytearray()   # events processed by the rewrite scan
                pending = bytearray()   # unprocessed tail: complete-but-unscanned events + partial event
                MAX_SCAN_BUDGET = 64 * 1024  # total scanned bytes before the rewrite gives up
                scan_capped = False

                # ONE raw iterator serves the scan and the remainder loop: an
                # httpx2 response stream is single-consumption (a second
                # iter_raw raises StreamConsumed), so both phases consume
                # this same object.
                chunks = resp.iter_raw()
                try:
                    for chunk in chunks:
                        _touch_upstream_activity()
                        if _swap_epoch_changed(epoch):
                            # A completed swap: never forward old-routing bytes.
                            evict_stream()
                            return first_byte_ms
                        pending.extend(chunk)

                        # Split complete events (\n\n-delimited) off the front
                        # and run each through the rewrite until message_start
                        # or the budget ends the scan. The budget check runs
                        # before each split, so scan work stays bounded by the
                        # budget regardless of chunk size or event count.
                        scan_over = False
                        while True:
                            if len(scanned) + len(pending) > MAX_SCAN_BUDGET:
                                scan_capped = True
                                scan_over = True
                                break
                            idx = pending.find(b"\n\n")
                            if idx < 0:
                                break  # no complete event yet; keep reading
                            event_bytes = bytes(pending[:idx + 2])
                            del pending[:idx + 2]
                            rewritten, is_message_start = _rewrite_sse_event(
                                event_bytes, tier, request_id)
                            scanned.extend(rewritten)
                            if is_message_start:
                                scan_over = True
                                break
                        if scan_over:
                            break
                except httpx2.ReadTimeout:
                    # The read bound is the client timeout. A swap in progress
                    # owns this wake (evict retryably); otherwise the stall is
                    # what ends the stream.
                    if forwarder._config_swapping or _swap_epoch_changed(epoch):
                        evict_stream()
                        return first_byte_ms
                except (httpx2.RequestError, httpx2.StreamError, OSError):
                    pass

                if scan_capped:
                    log_trace({
                        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        "event": "sse_buffer_cap_exceeded",
                        "request_id": request_id,
                        "bytes": len(scanned) + len(pending),
                    })

                if scanned or pending:
                    # Flush the scan window: the rewritten message_start (if
                    # found) or the verbatim degrade, plus whatever trailed it
                    # in the final chunk. A partial trailing event is never
                    # parsed — it forwards as received and is completed by the
                    # remainder loop below.
                    head = bytes(scanned) + bytes(pending)
                    self.wfile.write(head)
                    self.wfile.flush()
                    bytes_streamed += len(head)
                    first_byte_ms = (time.time() - first_byte_start) * 1000
                    first_chunk = False

                # Stream remaining events unchanged. Same iterator: the
                # stream stays single-consumption.
                try:
                    for chunk in chunks:
                        _touch_upstream_activity()
                        if _swap_epoch_changed(epoch):
                            evict_stream()
                            return first_byte_ms
                        bytes_streamed += len(chunk)
                        if bytes_streamed > SETTINGS.max_response_size:
                            log_trace({
                                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                "event": "response_size_cap_exceeded",
                                "request_id": request_id,
                                "bytes_streamed": bytes_streamed,
                                "limit": SETTINGS.max_response_size,
                            })
                            print("[proxy] Response size limit exceeded ({} bytes)".format(
                                bytes_streamed), file=sys.stderr)
                            break
                        self.wfile.write(chunk)
                        self.wfile.flush()
                except httpx2.ReadTimeout:
                    if forwarder._config_swapping or _swap_epoch_changed(epoch):
                        evict_stream()
                        return first_byte_ms
                except (httpx2.RequestError, httpx2.StreamError, OSError):
                    pass
            else:
                # Non-SSE path: stream unchanged. This branch is the sole
                # consumer of the response, so it owns the iterator.
                try:
                    for chunk in resp.iter_raw():
                        _touch_upstream_activity()
                        if _swap_epoch_changed(epoch):
                            evict_stream()
                            return first_byte_ms
                        bytes_streamed += len(chunk)
                        if bytes_streamed > SETTINGS.max_response_size:
                            log_trace({
                                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                "event": "response_size_cap_exceeded",
                                "request_id": request_id,
                                "bytes_streamed": bytes_streamed,
                                "limit": SETTINGS.max_response_size,
                            })
                            print("[proxy] Response size limit exceeded ({} bytes)".format(
                                bytes_streamed), file=sys.stderr)
                            break
                        self.wfile.write(chunk)
                        self.wfile.flush()
                        if first_chunk:
                            first_byte_ms = (time.time() - first_byte_start) * 1000
                            first_chunk = False
                except httpx2.ReadTimeout:
                    if forwarder._config_swapping or _swap_epoch_changed(epoch):
                        evict_stream()
                        return first_byte_ms
                except (httpx2.RequestError, httpx2.StreamError, OSError):
                    pass

        except _DISCONNECT_ERRORS:
            self._log_client_disconnect(request_id, status, retries)
            return None
        return first_byte_ms

    def _sse_event(self, payload, request_id=None):
        """Serialize one SSE frame — `event: <type>` + `data: <json>` lines.

        The Anthropic SDKs dispatch streaming events on the SSE `event:` field
        against a hardcoded whitelist; a data-only frame arrives with
        event=None and is silently dropped. The type is taken from
        payload["type"], and provider-controlled bytes only ever flow through
        json.dumps (SSE injection guard).

        The encode is fenced: a payload json.dumps cannot serialize (an
        in-band upstream-typed value that survived every copy-site check)
        degrades to a standard SSE error event rather than raising — an
        uncaught raise here surfaced to the client as a silent clean EOF
        with no terminal events, bypassing the cut-stream error machinery.
        """
        etype = payload.get("type")
        if not isinstance(etype, str) or not etype:
            etype = "message"
        try:
            body = json.dumps(payload)
        except Exception:  # total per compat._compat_guarded_parse (RecursionError is not a ValueError)
            etype = "error"
            body = _error_body("api_error", "response_frame_encode_failure",
                               "response frame could not be serialized",
                               request_id).decode("utf-8")
        return ("event: " + etype + "\n"
                "data: " + body + "\n\n").encode("utf-8")

    def _stream_response_sse_fallback(self, resp, request_id, tier, first_byte_start,
                                      epoch):
        """Handle unexpected Responses-mode upstream SSE defensively.

        The request transform forces stream:false, so SSE here means a provider
        ignored the flag. Drain the unexpected stream and synthesize a clean,
        empty Anthropic terminal sequence instead of leaking raw OpenAI SSE.

        The drain is an upstream read like any other: it touches the shared
        activity clock, and an epoch change stops it — the synthesized
        terminal is then the close (no error event is needed; this is the
        defensive terminal-only path).
        """
        first_byte_ms = None
        try:
            log_trace({
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "event": "response_sse_unexpected",
                "request_id": request_id,
            })
            try:
                for chunk in resp.iter_raw():
                    _touch_upstream_activity()
                    if _swap_epoch_changed(epoch):
                        _note_swap_eviction("stream", request_id, tier=tier)
                        break
            except (httpx2.RequestError, httpx2.StreamError, OSError):
                pass
            mid = "msg_" + str(uuid.uuid4())
            events = [
                {"type": "message_start",
                 "message": {"id": mid, "type": "message", "role": "assistant",
                             "content": [], "model": tier, "stop_reason": None,
                             "stop_sequence": None,
                             "usage": {"input_tokens": 0, "output_tokens": 0}}},
                {"type": "content_block_start", "index": 0,
                 "content_block": {"type": "text", "text": ""}},
                {"type": "content_block_stop", "index": 0},
                {"type": "message_delta",
                 "delta": {"stop_reason": None, "stop_sequence": None},
                 "usage": {"input_tokens": 0, "output_tokens": 0}},
                {"type": "message_stop"},
            ]
            for ev in events:
                self.wfile.write(self._sse_event(ev, request_id))
            self.wfile.flush()
            first_byte_ms = (time.time() - first_byte_start) * 1000
        except _DISCONNECT_ERRORS:
            return None
        return first_byte_ms

    def _log_client_disconnect(self, request_id, status, retries):
        """Record a client_disconnect event; suppress the traceback.

        Must never raise: it runs from an except handler, so a secondary
        failure here would re-raise and defeat the fix. stderr print is
        primary; trace event is best-effort.
        """
        try:
            print("[proxy] client disconnected mid-response "
                  "(request_id={}, status={}, retries={})".format(
                      request_id, status, retries), file=sys.stderr)
        except Exception:
            pass
        try:
            log_trace({
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "event": "client_disconnect",
                "request_id": request_id,
                "http_status": status,
                "retries": retries,
            })
        except Exception:
            pass

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Allow", "POST, OPTIONS")
        self.end_headers()

    def do_GET(self):
        # Admin page
        if self.path == "/admin/" or self.path == "/admin":
            return self._admin_handle_page()

        # Admin API: get config
        if self.path == "/admin/api/config":
            return self._admin_handle_config()

        # Admin API: live config-swap status. Exactly five scalars, nothing
        # provider-, config- or request-derived, and no CORS headers — the
        # endpoint widens an existing (explicitly out-of-scope) local
        # disclosure surface and must not widen it further.
        if self.path == "/admin/api/swap-status":
            return self._admin_handle_swap_status()

        # Admin API: get providers list
        if self.path == "/admin/api/providers":
            return self._admin_handle_providers()

        # Admin API: get per-provider mode detail (mode only — never url/key)
        if self.path == "/admin/api/providers-detail":
            return self._admin_handle_providers_detail()

        # Default: 404 — answers any non-admin GET, including GET /v1/models,
        # so it is an Anthropic-surface response and carries the envelope.
        self._send_response(404, _error_body(
            "not_found_error", "not_found", "not found", str(uuid.uuid4())))

    def do_POST(self):
        # Admin shutdown — localhost-only, graceful shutdown via server.shutdown()
        if self.path == "/admin/shutdown":
            return self._admin_handle_shutdown()

        # Admin API: switch tiers
        if self.path == "/admin/api/switch":
            return self._admin_handle_switch()

        # Admin API: reload config from disk
        if self.path == "/admin/api/reload":
            return self._admin_handle_reload()

        request_id = str(uuid.uuid4())

        # Read request body
        try:
            content_length = int(self.headers.get("Content-Length", 0))
        except (ValueError, TypeError):
            self._send_response(400, _error_body(
                "invalid_request_error", "invalid_content_length",
                "invalid Content-Length", request_id))
            return
        if content_length > SETTINGS.max_body_size:
            try:
                self._send_response(413, _error_body(
                    "request_too_large", "payload_too_large",
                    "Payload too large", request_id))
            except _DISCONNECT_ERRORS:
                self._log_client_disconnect(request_id, 413, 0)
            log_trace({
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "event": "request",
                "request_id": request_id,
                "method": self.command,
                "path": self.path,
                "model": "unknown",
                "status": "failure",
                "http_status": 413,
                "retries": 0,
                "total_latency_sec": 0,
                "first_byte_latency_ms": None,
                "error": "Payload too large"
            })
            return
        body = self.rfile.read(content_length) if content_length > 0 else b""

        # Ownership check before the body is parsed anywhere (extract_model,
        # the forward path, and the --all capture all read these same bytes).
        _nesting = check_payload_nesting(body)
        if _nesting is not None:
            message = _nesting_limit_message(_nesting)
            log_trace(nesting_event("request_body", _nesting,
                                    request_id=request_id))
            # The fields mirror the pre-routing 413 entry above (no tier, no
            # provider); the ordering follows the main request path — both
            # entries are on disk before the client is answered.
            log_trace({
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "event": "request",
                "request_id": request_id,
                "method": self.command,
                "path": self.path,
                "model": "unknown",
                "status": "failure",
                "http_status": 400,
                "retries": 0,
                "total_latency_sec": 0,
                "first_byte_latency_ms": None,
                "error": message
            })
            try:
                self._send_response(400, _error_body(
                    "invalid_request_error", "nesting_limit_exceeded",
                    message, request_id))
            except _DISCONNECT_ERRORS:
                self._log_client_disconnect(request_id, 400, 0)
            return

        # request_id already generated above
        model, _body_error = extract_model(body)

        increment_total()

        try:
            status, resp_headers, resp_body, first_byte_ms, total_sec, retries, tier, provider, actual_model = \
                forward_request(self.command, self.path,
                                {k: v for k, v in self.headers.items()},
                                body, handler=self, request_id=request_id)
        except Exception as e:  # total: no request may end with a closed
                                # connection and no record (do_POST has no
                                # outer try; anything outside the retry loop's
                                # (httpx2.RequestError, httpx2.StreamError,
                                # OSError) tuple -- e.g. httpx2.InvalidURL,
                                # a bare Exception -- would reach
                                # handle_error and drop the connection).
            print("[proxy] forward failed, rid={}: {}".format(
                request_id, sanitize_error(str(e))), file=sys.stderr)
            log_trace({
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "event": "forward_failed",
                "request_id": request_id,
                "method": self.command,
                "path": self.path,
                "error": sanitize_error(str(e)),
            })
            status, resp_headers, resp_body, first_byte_ms = 502, {}, _error_body(
                "api_error", "upstream_unreachable",
                "upstream: internal forwarding failure", request_id), None
            # The trace entry below reads the remaining tuple members; no
            # tier/provider was resolved on this path.
            total_sec, retries, tier, provider, actual_model = 0, 0, None, None, None

        # Mirrors forward_request's streaming branch: streaming paths return
        # resp_body=b"" (already sent to client), buffering paths return the
        # actual body (needs _send_response). Check both status and body.
        streamed = (200 <= status < 300) and (resp_body == b"")

        # Build trace entry
        success = 200 <= status < 300
        trace_entry = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "event": "request",
            "request_id": request_id,
            "method": self.command,
            "path": self.path,
            "model": _trace_model(actual_model, model),
            "tier": tier,
            "provider": provider,
            "key": None,  # resolved below; omitted when resolution fails
            "status": "success" if success else "failure",
            "http_status": status,
            "retries": retries,
            "total_latency_sec": round(total_sec, 3) if total_sec else 0,
            "first_byte_latency_ms": int(first_byte_ms) if first_byte_ms else None,
            "error": None if success else sanitize_error(
                resp_body.decode("utf-8", errors="replace") if resp_body else
                "HTTP {}".format(status))
        }

        # Re-resolve extra request headers for the trace (never threaded
        # through forward_request's return tuple — signature discipline).
        # This uses _current_config at event time, so a mid-request admin
        # swap could log the post-swap mapping; the wire header used the
        # entry snapshot. Trace-only cosmetic divergence, accepted.
        resolved_extra = _resolve_extra_request_headers(
            {k: v for k, v in self.headers.items()},
            provider, runtime_state._current_config, request_id)
        if resolved_extra:
            trace_entry["extra_request_headers"] = resolved_extra

        # The client's User-Agent as received. Recorded on every request, not
        # only under --all -- like extra_request_headers above, and unlike the
        # bodies. It is the input a UA-based edge refusal keys on, and the one
        # thing the entry otherwise omits when a 403 comes back carrying
        # nothing but `error code: 1010`.
        _client_ua = _client_user_agent(self.headers)
        if _client_ua is not None:
            trace_entry["client_user_agent"] = _client_ua

        # Re-resolve the provider key name for the trace (never threaded
        # through forward_request's return tuple — signature discipline; the
        # wire auth used the entry snapshot). Resolution is generic over ANY
        # tier present in config, so an extra tier reached via reverse model
        # lookup gets its key traced too. Unlike _resolve_extra_request_headers
        # above (total on its inputs), this dereferences _current_config["tiers"]
        # and _vendors, which can KeyError on the unknown-tier / None-provider
        # early-return paths (method/path/model 400s and the 413) and after a
        # mid-request admin swap; the guard keeps do_POST from crashing before
        # the error response and the trace entry are written, and the key field
        # is omitted when resolution is impossible. The provider-ownership
        # check (entry-snapshot provider still owns the tier) prevents a
        # post-swap tier from mixing the old provider's vendor with the new
        # tier's key selector; an unowned tier simply omits the field.
        try:
            if provider:
                _tier_cfg = (runtime_state._current_config.get("tiers") or {}).get(tier)
                if (isinstance(_tier_cfg, dict)
                        and _tier_cfg.get("provider") == provider
                        and isinstance(runtime_state._vendors.get(provider), dict)):
                    trace_entry["key"] = resolve_api_key(
                        runtime_state._vendors[provider], _tier_cfg)[1]
        except Exception:
            pass
        if trace_entry.get("key") is None:
            trace_entry.pop("key", None)

        if SETTINGS.log_all:
            # Include full request/response bodies
            try:
                trace_entry["request_body"] = json.loads(body.decode("utf-8"))
            except Exception:
                trace_entry["request_body"] = body.decode("utf-8", errors="replace") if body else None
            if not streamed:
                # Streamed 2xx bodies were consumed by the client in real time
                # and are not captured — a deliberate reduction in data-at-rest
                # exposure under --all.
                _resp_nesting = check_payload_nesting(resp_body)
                if _resp_nesting is not None:
                    # A distinct payload from the request body: bound it here
                    # too, and fall back to the non-JSON capture form.
                    log_trace(nesting_event("response_body_capture",
                                            _resp_nesting,
                                            request_id=request_id, tier=tier))
                    trace_entry["response_body"] = resp_body.decode("utf-8", errors="replace") if resp_body else None
                else:
                    try:
                        trace_entry["response_body"] = json.loads(resp_body.decode("utf-8"))
                    except Exception:
                        trace_entry["response_body"] = resp_body.decode("utf-8", errors="replace") if resp_body else None

        log_trace(trace_entry)

        if not streamed:
            try:
                self._send_response(status, resp_body, resp_headers)
            except _DISCONNECT_ERRORS:
                # Client disconnected mid-response (timed out, cancelled, etc.).
                # The request already completed upstream and is traced above;
                # record a delivery-failure event and avoid a traceback.
                self._log_client_disconnect(request_id, status, retries)

    def log_message(self, format, *args):
        # Suppress default http.server logging (we use our own trace log)
        pass


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

class _ProxyHTTPServer(http.server.ThreadingHTTPServer):
    """The proxy's listening server.

    allow_reuse_address is platform-dependent because SO_REUSEADDR does not
    mean the same thing on Windows. On POSIX it tolerates binding a port left
    in TIME_WAIT while still refusing a second LISTEN. On Windows it permits
    binding a port that already has a live listener, so the sole-owner
    guarantee needs a plain bind there; a plain bind still tolerates
    TIME_WAIT on Windows. On POSIX a plain bind would refuse the TIME_WAIT
    residue a just-stopped proxy leaves behind, so that branch keeps the
    reuse flag.
    """
    allow_reuse_address = sys.platform != "win32"
    # socketserver's default accept backlog is 5; a burst of
    # simultaneous connections (parallel tool fan-outs, test
    # concurrency) overflows it and the kernel drops SYNs — measured
    # 2026-11-19 via TcpExtListenDrops/ListenOverflows deltas (+71)
    # during six 20-request bursts (evidence: plan
    # 2026-11-19-drop-redacted-thinking-chat-placeholder, issue
    # ingress-listen-backlog). A dropped connection never reaches the
    # handler: the client sees a ~1 s SYN-retransmit stall or a
    # ConnectionResetError, and leaves no trace entry. 128 gives
    # realistic fan-outs 25x headroom; somaxconn clamps beyond that.
    request_queue_size = 128


def main():
    # Parse CLI args
    parser = argparse.ArgumentParser(
        description="HTTP retry proxy for Claude API")
    parser.add_argument("--port", type=int, default=None,
                        help="Port to listen on (default: $PROXY_PORT or 8080)")
    parser.add_argument("--log", "-l", type=str, default=None,
                        help="Trace log file path")
    parser.add_argument("--all", "-a", action="store_true",
                        help="Log full request/response bodies")
    parser.add_argument("--config-path", type=str, default=None,
                        help="Path to config.json (default: ~/.claude/proxy/config.json)")
    parser.add_argument("--keys-path", type=str, default=None,
                        help="Path to encrypted keys-index.json (default: ~/.claude/keys-index.json)")
    parser.add_argument("--passphrase-file", type=str, default=None,
                        help="Read passphrase from file instead of stdin")
    args = parser.parse_args()

    if args.port is not None:
        SETTINGS.port = args.port
    SETTINGS.trace_file = resolve_trace_file(args.log)
    if getattr(args, "all"):
        SETTINGS.log_all = True
    sinks.configure(trace_path=SETTINGS.trace_file, state_path=SETTINGS.state_file)

    # Resolve paths
    config_path = args.config_path or SETTINGS.config_path
    keys_path = args.keys_path or SETTINGS.keys_path

    # Read keys file and detect format
    try:
        with open(keys_path, "rb") as _kf:
            _keys_data = _kf.read()
    except FileNotFoundError:
        print("[proxy] ERROR: Keys file not found: {}".format(keys_path), file=sys.stderr)
        sys.exit(1)

    _needs_passphrase = _keys_data.startswith(b"VimCrypt~03!")

    if _needs_passphrase:
        # Read passphrase (same logic as before)
        if args.passphrase_file:
            try:
                with open(args.passphrase_file, "r", encoding="utf-8") as f:
                    passphrase = f.read().rstrip("\r\n")
            except OSError as e:
                print("[proxy] ERROR: Cannot read passphrase file: {}".format(e), file=sys.stderr)
                sys.exit(1)
            if not passphrase:
                print("[proxy] ERROR: Empty passphrase in file", file=sys.stderr)
                sys.exit(1)
        else:
            passphrase = read_passphrase_from_stdin()
    else:
        passphrase = None
        # Warn about plain keys at-rest exposure (mirrors --all warning)
        print("[proxy] WARNING: keys file is plain JSON — API keys are stored "
              "unencrypted on disk", file=sys.stderr)

    # Load keys (decrypts if encrypted, parses plain JSON otherwise)
    try:
        runtime_state._vendors = load_keys_file(keys_path, passphrase)
    except ValueError as e:
        print("[proxy] ERROR: Key decryption failed: {}".format(e), file=sys.stderr)
        sys.exit(1)

    # Load and validate config
    try:
        runtime_state._current_config = load_config(config_path)
        runtime_state._config_path = config_path
    except FileNotFoundError:
        print("[proxy] ERROR: Config file not found: {}".format(config_path), file=sys.stderr)
        print("[proxy] Run 'claude-retry-proxy start' to create from template", file=sys.stderr)
        sys.exit(1)
    except (json.JSONDecodeError, ValueError) as e:
        print("[proxy] ERROR: Invalid config: {}".format(e), file=sys.stderr)
        sys.exit(1)

    provider_names = set(runtime_state._vendors.keys())
    provider_keys = {name: vendor_key_names(v) for name, v in runtime_state._vendors.items()}
    errors = validate_config(runtime_state._current_config, provider_names, provider_keys)
    if errors:
        print("[proxy] ERROR: Config validation failed:", file=sys.stderr)
        for err in errors:
            print("[proxy]   - {}".format(err), file=sys.stderr)
        sys.exit(1)

    # Compatibility subsystem: validate tuning constants and load learned state
    _compat_validate_constants()
    _load_compat_state()

    # Check if another proxy is already running on this port.
    # The probe mirrors the bind it guards, so it can never be stricter than
    # the real listener. On POSIX SO_REUSEADDR tolerates a port left in
    # TIME_WAIT while still refusing a second LISTEN. On Windows the flag
    # means something different: it permits binding a port that already has
    # a live listener, so the probe — and the listener — must use a plain
    # bind there. A plain bind on Windows still tolerates TIME_WAIT.
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if sys.platform != "win32":
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("127.0.0.1", SETTINGS.port))
    except OSError:
        print("[proxy] Port {} is already in use. Proxy may already be running.".format(
            SETTINGS.port), file=sys.stderr)
        sys.exit(1)
    finally:
        sock.close()

    # Write initial state
    state = {
        "pid": os.getpid(),
        "port": SETTINGS.port,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "owner_pid": os.getppid(),
        "last_heartbeat": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "last_request_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    if not write_state(state):
        try:
            print("[proxy] ERROR: state file {} is not writable — aborting startup".format(
                SETTINGS.state_file), file=sys.stderr)
        except Exception:
            pass
        sys.exit(1)
    runtime_state._startup_state = state

    # Write start marker to trace
    if not write_start_marker(SETTINGS.port):
        try:
            print("[proxy] ERROR: trace file {} is not writable — aborting startup".format(
                SETTINGS.trace_file), file=sys.stderr)
        except Exception:
            pass
        sys.exit(1)

    # Runtime diagnostics become best-effort from here on (see _BestEffortStderr).
    # Installed after both fail-fast checks so their ERROR lines stay loud.
    sys.stderr = _BestEffortStderr(sys.stderr)

    # Start background threads
    threading.Thread(target=runtime_state.heartbeat_loop, daemon=True).start()

    # Start server with ThreadingHTTPServer for concurrent requests
    server = _ProxyHTTPServer(("127.0.0.1", SETTINGS.port), ProxyHandler)
    print("[proxy] Listening on 127.0.0.1:{}".format(SETTINGS.port), file=sys.stderr)
    print("[proxy] Providers: {}".format(", ".join(runtime_state._vendors.keys())), file=sys.stderr)
    # Register graceful shutdown signal handlers so write_stop_marker()
    # runs on normal shutdown (claude-retry-proxy stop sends SIGTERM/taskkill).
    def _shutdown_handler(signum, frame):
        # socketserver.BaseServer.shutdown() blocks until serve_forever()
        # returns, and a Python signal handler runs ON the serve_forever
        # thread — calling it inline is the documented deadlock. Dispatch it,
        # mirroring the admin path's _delayed_shutdown.
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, _shutdown_handler)
    if sys.platform != "win32":
        signal.signal(signal.SIGINT, _shutdown_handler)
    # On Windows, Ctrl+C raises KeyboardInterrupt which the try/except already handles

    # Readiness now post-dates handler registration: READY (stdout marker for
    # the CLI) and the pollable proxy_ready trace event both mean "fully
    # initialised" — a consumer acting on either can safely deliver SIGTERM.
    print("READY", flush=True)
    log_trace({
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
        "event": "proxy_ready",
        "port": SETTINGS.port,
        "pid": os.getpid(),
    })

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        write_stop_marker()
        # Clean up state file
        try:
            os.remove(SETTINGS.state_file)
        except OSError:
            pass


if __name__ == "__main__":
    main()