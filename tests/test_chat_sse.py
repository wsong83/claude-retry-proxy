"""Chat-mode SSE streaming tests: frame assembly, reasoning deltas,
tool-call delta conversion, degradation paths, and streamed e2e.

Part of the claude-retry-proxy suite; runnable standalone.
"""

import http.client
import http.server
import json
import os
import shutil
import socket
import subprocess
import tempfile
import threading
import time

from _harness import (
    _assert_degradation_metadata_only,
    _cc,
    _chat_sse_fetch_frames,
    _create_test_config,
    _create_test_keys_plain,
    _degraded_trace_events,
    _mode_tiers,
    _models_for_vendors,
    _parse_sse_frames,
    _send_proxy_request_stream,
    _sse_content_block_starts,
    _sse_frame_type,
    _sse_frames_with_type,
    _sse_stop_reason,
    _sse_stream_chunks,
    _sse_tool_use_blocks,
    _sse_types,
    _start_chat_sse_proxy,
    _start_mode_proxy,
    _start_proxy_server_directly,
    errors,
    fail,
    find_free_port,
    info,
    pass_,
    run_cli,
)

# A post-finish drain that has not terminated by this point is a failure: the
# drain is bounded by MAX_DRAIN_SECONDS (5s) and must leave ample headroom under
# the 30s drain-and-swap timeout a config switch waits on.
DRAIN_BOUND_TEST_SECONDS = 20



def _start_hanging_chat_proxy(pre_body, hold_s, post_body=None, gap_s=0.0):
    """Chat-mode proxy whose mock upstream streams `pre_body` over an unterminated
    response (HTTP/1.0, no Content-Length) and then holds the socket open.

    The harness responder always sets Content-Length and closes, so the proxy's
    read loop sees EOF immediately and the stall path is never exercised. This
    mirror of _start_chat_sse_proxy exists solely to reach it.

    With `post_body` and `gap_s` the upstream writes `post_body` after a delay,
    which lands it in a later read chunk than `pre_body` — the shape that makes
    a post-finish frame count as *late* (the per-chunk offset is taken at chunk
    receipt, before the frames are parsed).

    Returns (proxy_port, trace_file, cleanup), or (None, None, None) on failure.
    """
    upstream_port = find_free_port()
    tiers = _mode_tiers()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port),
                     "key": "K", "mode": "chat"}}

    class HangHandler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"

        def do_POST(self):
            content_len = int(self.headers.get("Content-Length", 0))
            if content_len > 0:
                self.rfile.read(content_len)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.wfile.write(pre_body)
            self.wfile.flush()
            if post_body is not None:
                time.sleep(gap_s)
                self.wfile.write(post_body)
                self.wfile.flush()
            time.sleep(hold_s)

        def log_message(self, format, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", upstream_port), HangHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    time.sleep(0.1)

    temp_dir = tempfile.mkdtemp(prefix="proxy_drain_")
    proxy_port = find_free_port()
    config_path = _create_test_config(
        temp_dir, tiers, models=_models_for_vendors(tiers, vendors))
    keys_path = _create_test_keys_plain(temp_dir, vendors)
    trace_fd, trace_file = tempfile.mkstemp(suffix=".jsonl", dir=temp_dir)
    os.close(trace_fd)
    proc, probe_ok = _start_proxy_server_directly(
        proxy_port, config_path=config_path, keys_path=keys_path,
        passphrase=None, trace_file=trace_file)

    if not probe_ok:
        server.shutdown()
        shutil.rmtree(temp_dir, ignore_errors=True)
        return None, None, None

    def cleanup():
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        server.shutdown()
        shutil.rmtree(temp_dir, ignore_errors=True)

    return proxy_port, trace_file, cleanup



def _read_sse_until_stop(port, deadline_s, body=None):
    """POST a streaming chat request, reading until message_stop or `deadline_s`.

    Returns (raw_bytes, saw_message_stop, elapsed_seconds). Returns early on
    message_stop so a promptly-terminating drain is not charged the full budget.
    """
    if body is None:
        body = {"model": "sonnet", "messages": [{"role": "user", "content": "hi"}],
                "stream": True}
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=deadline_s + 5)
    start = time.time()
    conn.request("POST", "/v1/messages", body=json.dumps(body),
                 headers={"Content-Type": "application/json"})
    resp = conn.getresponse()
    chunks = []
    saw_stop = False
    try:
        while True:
            # read1 (not read): read(n) blocks until exactly n bytes or EOF, so a
            # streaming response that emits 501 bytes and then stalls would read
            # as zero bytes and hide the terminal event this helper looks for.
            # read1 returns whatever has actually arrived.
            chunk = resp.read1(4096) if hasattr(resp, "read1") else resp.read(4096)
            if not chunk:
                break
            chunks.append(chunk)
            if b"message_stop" in b"".join(chunks):
                saw_stop = True
                break
            if time.time() - start > deadline_s:
                break
    except (socket.timeout, OSError):
        pass
    finally:
        elapsed = time.time() - start
        conn.close()
    return b"".join(chunks), saw_stop, elapsed



def _trace_events_named(trace_file, event_name):
    """Return every trace event in `trace_file` whose "event" is `event_name`."""
    out = []
    if not trace_file or not os.path.exists(trace_file):
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
            if ev.get("event") == event_name:
                out.append(ev)
    return out



def _wait_for_trace_events(trace_file, event_name, timeout_s=3.0):
    """Poll trace_file until at least one `event_name` event appears.

    A client that returns at message_stop can outrun the proxy's trace write:
    the terminal frames are flushed to the wire before chat_sse_drain (or the
    detector events) reach the sink, so a single immediate read races the
    proxy process. Returns the events found, or [] if none landed within
    `timeout_s` seconds.
    """
    deadline = time.time() + timeout_s
    while True:
        out = _trace_events_named(trace_file, event_name)
        if out or time.time() >= deadline:
            return out
        time.sleep(0.05)



def _message_delta_usage(frames):
    """Return the usage dict on the first message_delta frame, or None."""
    deltas = _sse_frames_with_type(frames, "message_delta")
    if not deltas:
        return None
    return deltas[0].get("usage")




def test_chat_sse_basic_streaming():
    """Simulated OpenAI SSE chunks produce valid Anthropic SSE events."""
    print("\n--- Test: Chat SSE Basic Streaming ---")
    upstream_port = find_free_port()
    tiers = _mode_tiers()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port), "key": "K", "mode": "chat"}}
    chunks = [
        {"id": "chatcmpl-1", "object": "chat.completion.chunk", "created": 1, "model": "gpt-4o",
         "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]},
        {"id": "chatcmpl-1", "object": "chat.completion.chunk", "created": 1, "model": "gpt-4o",
         "choices": [{"index": 0, "delta": {"content": "Hel"}, "finish_reason": None}]},
        {"id": "chatcmpl-1", "object": "chat.completion.chunk", "created": 1, "model": "gpt-4o",
         "choices": [{"index": 0, "delta": {"content": "lo"}, "finish_reason": None}]},
        {"id": "chatcmpl-1", "object": "chat.completion.chunk", "created": 1, "model": "gpt-4o",
         "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
    ]
    sse_body = _sse_stream_chunks(chunks) + b"data: [DONE]\n\n"
    responders = {"p": lambda info: (200, "text/event-stream", sse_body)}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(tiers, vendors, responders=responders)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        status, content_type, raw = _send_proxy_request_stream(
            proxy_port, body={"model": "sonnet", "messages": [{"role": "user", "content": "hi"}], "stream": True})
        if status != 200:
            fail("expected 200, got {}".format(status))
            return
        frames = _parse_sse_frames(raw)
        types = _sse_types(frames)
        required = ("message_start", "content_block_start", "content_block_delta",
                    "content_block_stop", "message_delta", "message_stop")
        missing = [t for t in required if t not in types]
        if missing:
            fail("missing SSE events {}; got {}".format(missing, types))
            return
        order_idx = {t: types.index(t) for t in required}
        if [order_idx[t] for t in required] != sorted(order_idx.values()):
            fail("SSE event ordering wrong: {}".format(types))
        if types.count("message_delta") != 1 or types.count("message_stop") != 1:
            fail("expected exactly one message_delta/message_stop, got {}".format(types))
        start = _sse_frames_with_type(frames, "message_start")
        if start:
            msg = start[0].get("message", {})
            if not (msg.get("id", "").startswith("msg_") and msg.get("model") == "sonnet"):
                fail("synthetic message_start wrong: {!r}".format(start[0]))
        if b"[DONE]" in raw:
            fail("[DONE] sentinel leaked into client stream")
        if not missing and [order_idx[t] for t in required] == sorted(order_idx.values()):
            pass_("chat SSE produces valid Anthropic event sequence")
    finally:
        cleanup()




def test_chat_sse_finish_reason_mapping():
    """finish_reason maps to stop_reason in the terminal message_delta."""
    print("\n--- Test: Chat SSE Finish Reason Mapping ---")
    upstream_port = find_free_port()
    tiers = _mode_tiers()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port), "key": "K", "mode": "chat"}}
    chunks = [
        {"id": "c1", "object": "chat.completion.chunk", "created": 1, "model": "gpt-4o",
         "choices": [{"index": 0, "delta": {"role": "assistant", "content": "hi"}, "finish_reason": None}]},
        {"id": "c1", "object": "chat.completion.chunk", "created": 1, "model": "gpt-4o",
         "choices": [{"index": 0, "delta": {}, "finish_reason": "length"}]},
    ]
    sse_body = _sse_stream_chunks(chunks) + b"data: [DONE]\n\n"
    responders = {"p": lambda info: (200, "text/event-stream", sse_body)}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(tiers, vendors, responders=responders)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        status, content_type, raw = _send_proxy_request_stream(
            proxy_port, body={"model": "sonnet", "messages": [{"role": "user", "content": "hi"}]})
        if status != 200:
            fail("expected 200, got {}".format(status))
            return
        frames = _parse_sse_frames(raw)
        deltas = _sse_frames_with_type(frames, "message_delta")
        if not deltas:
            fail("no message_delta event in stream")
            return
        delta_obj = deltas[0].get("delta", {})
        stop_reason = delta_obj.get("stop_reason")
        if stop_reason != "max_tokens":
            fail("finish_reason length should map to stop_reason max_tokens, got {!r}".format(stop_reason))
        else:
            pass_("SSE finish_reason length -> stop_reason max_tokens")
    finally:
        cleanup()




def test_chat_sse_no_content_delta():
    """Chunks without content delta produce no content_block_delta events."""
    print("\n--- Test: Chat SSE No Content Delta ---")
    upstream_port = find_free_port()
    tiers = _mode_tiers()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port), "key": "K", "mode": "chat"}}
    chunks = [
        {"id": "c1", "object": "chat.completion.chunk", "created": 1, "model": "gpt-4o",
         "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]},
        {"id": "c1", "object": "chat.completion.chunk", "created": 1, "model": "gpt-4o",
         "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
    ]
    sse_body = _sse_stream_chunks(chunks) + b"data: [DONE]\n\n"
    responders = {"p": lambda info: (200, "text/event-stream", sse_body)}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(tiers, vendors, responders=responders)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        status, content_type, raw = _send_proxy_request_stream(
            proxy_port, body={"model": "sonnet", "messages": [{"role": "user", "content": "hi"}]})
        if status != 200:
            fail("expected 200, got {}".format(status))
            return
        frames = _parse_sse_frames(raw)
        types = _sse_types(frames)
        if "content_block_delta" in types:
            fail("chunks without content produced content_block_delta: {}".format(types))
        else:
            pass_("no content_block_delta when chunks carry no content")
    finally:
        cleanup()




def test_chat_sse_empty_choices_usage_chunk():
    """An empty-choices usage chunk does not crash and its usage is accumulated."""
    print("\n--- Test: Chat SSE Empty Choices Usage Chunk ---")
    upstream_port = find_free_port()
    tiers = _mode_tiers()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port), "key": "K", "mode": "chat"}}
    chunks = [
        {"id": "c1", "object": "chat.completion.chunk", "created": 1, "model": "gpt-4o",
         "choices": [{"index": 0, "delta": {"role": "assistant", "content": "hi"}, "finish_reason": None}]},
        {"id": "c1", "object": "chat.completion.chunk", "created": 1, "model": "gpt-4o",
         "choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}},
        {"id": "c1", "object": "chat.completion.chunk", "created": 1, "model": "gpt-4o",
         "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
    ]
    sse_body = _sse_stream_chunks(chunks) + b"data: [DONE]\n\n"
    responders = {"p": lambda info: (200, "text/event-stream", sse_body)}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(tiers, vendors, responders=responders)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        status, content_type, raw = _send_proxy_request_stream(
            proxy_port, body={"model": "sonnet", "messages": [{"role": "user", "content": "hi"}]})
        if status != 200:
            fail("expected 200, got {}".format(status))
            return
        frames = _parse_sse_frames(raw)
        deltas = _sse_frames_with_type(frames, "message_delta")
        if not deltas:
            fail("no message_delta in stream")
            return
        usage = deltas[0].get("usage", {})
        if usage.get("input_tokens") != 10 or usage.get("output_tokens") != 5:
            fail("expected usage input_tokens=10 output_tokens=5 in message_delta, got {!r}".format(usage))
        else:
            pass_("empty-choices usage chunk accumulated into message_delta")
    finally:
        cleanup()




def test_chat_sse_eof_without_finish_reason():
    """A cut stream (no finish_reason, no [DONE]) closes with a retryable SSE
    error event instead of a synthesized terminal, and chat_sse_truncated
    records saw_done: 0.

    The synthesized end_turn was indistinguishable on the wire from a turn the
    model actually finished, so the client recorded a completed message and
    never retried. Open blocks are still closed first so the partial turn is a
    well-formed stream up to the error; no message_delta/message_stop follows.
    """
    print("\n--- Test: Chat SSE EOF Without Finish Reason ---")
    upstream_port = find_free_port()
    tiers = _mode_tiers()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port), "key": "K", "mode": "chat"}}
    chunks = [
        {"id": "c1", "object": "chat.completion.chunk", "created": 1, "model": "gpt-4o",
         "choices": [{"index": 0, "delta": {"role": "assistant", "content": "hello"}, "finish_reason": None}]},
    ]
    sse_body = _sse_stream_chunks(chunks)
    responders = {"p": lambda info: (200, "text/event-stream", sse_body)}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(tiers, vendors, responders=responders)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        status, content_type, raw = _send_proxy_request_stream(
            proxy_port, body={"model": "sonnet", "messages": [{"role": "user", "content": "hi"}]})
        if status != 200:
            fail("expected 200, got {}".format(status))
            return
        frames = _parse_sse_frames(raw)
        types = _sse_types(frames)
        if "content_block_stop" not in types:
            fail("cut stream must close its open content blocks before the error; got {}".format(types))
            return
        present = [t for t in ("message_delta", "message_stop") if t in types]
        if present:
            fail("cut stream must not synthesize {}; got {}".format(present, types))
            return
        errs = _sse_frames_with_type(frames, "error")
        if len(errs) != 1:
            fail("cut stream must close with exactly one error frame, got {} ({})".format(len(errs), types))
            return
        if (errs[0].get("error") or {}).get("type") != "api_error":
            fail("cut-stream error must be api_error (retryable), got {!r}".format(errs[0].get("error")))
            return
        if types.index("content_block_stop") > types.index("error"):
            fail("content_block_stop must precede the error frame; got {}".format(types))
            return
        events = _trace_events_named(trace_file, "chat_sse_truncated")
        if len(events) != 1:
            fail("expected exactly one chat_sse_truncated event, got {}".format(len(events)))
            return
        if events[0].get("saw_done") != 0:
            fail("chat_sse_truncated must record saw_done: 0 on a cut stream, got {!r}".format(events[0].get("saw_done")))
            return
        if _trace_events_named(trace_file, "chat_sse_drain"):
            fail("a stream that never reached finish_reason must not log chat_sse_drain")
            return
        pass_("cut stream: blocks closed, api_error closes, saw_done 0, no synthesized terminal")
    finally:
        cleanup()




def test_chat_sse_done_without_finish_reason_is_terminal():
    """[DONE] without ever a finish_reason is protocol-complete: the stream
    closes with the synthesized terminal sequence — never an error frame — and
    chat_sse_truncated records saw_done: 1.

    A provider that always omits finish_reason but terminates properly would
    otherwise be turned into a retry storm against a retryable error, replacing
    a working integration with an outage. This test pins that contract.
    """
    print("\n--- Test: Chat SSE Done Without Finish Reason Is Terminal ---")
    chunks = [_cc({"role": "assistant", "content": "hello"})]
    proxy_port, trace_file, cleanup = _start_chat_sse_proxy(chunks)  # appends [DONE]
    if proxy_port is None:
        return
    try:
        frames = _chat_sse_fetch_frames(proxy_port)
        if frames is None:
            return
        types = _sse_types(frames)
        missing = [t for t in ("content_block_stop", "message_delta", "message_stop") if t not in types]
        if missing:
            fail("[DONE]-terminated stream must close with the terminal sequence; missing {} ({})".format(missing, types))
            return
        errs = _sse_frames_with_type(frames, "error")
        if errs:
            fail("[DONE]-terminated stream must not emit an error frame, got {!r}".format(errs))
            return
        if _sse_stop_reason(frames) != "end_turn":
            fail("protocol-complete finish-less stream should synthesize end_turn, got {!r}".format(_sse_stop_reason(frames)))
            return
        events = _trace_events_named(trace_file, "chat_sse_truncated")
        if len(events) != 1:
            fail("expected exactly one chat_sse_truncated event, got {}".format(len(events)))
            return
        if events[0].get("saw_done") != 1:
            fail("chat_sse_truncated must record saw_done: 1 for a [DONE]-terminated stream, got {!r}".format(events[0].get("saw_done")))
            return
        pass_("[DONE] without finish_reason: terminal sequence, no error frame, saw_done 1")
    finally:
        cleanup()




def test_chat_sse_first_event_has_content():
    """A first chunk that carries real content emits a content_block_delta."""
    print("\n--- Test: Chat SSE First Event Has Content ---")
    upstream_port = find_free_port()
    tiers = _mode_tiers()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port), "key": "K", "mode": "chat"}}
    chunks = [
        {"id": "c1", "object": "chat.completion.chunk", "created": 1, "model": "gpt-4o",
         "choices": [{"index": 0, "delta": {"role": "assistant", "content": "Deep"}, "finish_reason": None}]},
        {"id": "c1", "object": "chat.completion.chunk", "created": 1, "model": "gpt-4o",
         "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
    ]
    sse_body = _sse_stream_chunks(chunks) + b"data: [DONE]\n\n"
    responders = {"p": lambda info: (200, "text/event-stream", sse_body)}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(tiers, vendors, responders=responders)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        status, content_type, raw = _send_proxy_request_stream(
            proxy_port, body={"model": "sonnet", "messages": [{"role": "user", "content": "hi"}]})
        if status != 200:
            fail("expected 200, got {}".format(status))
            return
        frames = _parse_sse_frames(raw)
        deltas = _sse_frames_with_type(frames, "content_block_delta")
        texts = []
        for d in deltas:
            dd = d.get("delta", {})
            if isinstance(dd.get("text"), str):
                texts.append(dd.get("text"))
        if not any("Deep" in t for t in texts):
            fail("first-chunk content should appear in a content_block_delta, texts={!r}".format(texts))
        else:
            pass_("first-chunk content emitted as content_block_delta")
    finally:
        cleanup()




def test_chat_sse_injection_prevented():
    """Provider-controlled newline/event/data text cannot inject extra SSE events."""
    print("\n--- Test: Chat SSE Injection Prevented ---")
    upstream_port = find_free_port()
    tiers = _mode_tiers()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port), "key": "K", "mode": "chat"}}
    injected = "line1\nevent: message_stop\ndata: fake\n\nline2"
    chunks = [
        {"id": "c1", "object": "chat.completion.chunk", "created": 1, "model": "gpt-4o",
         "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]},
        {"id": "c1", "object": "chat.completion.chunk", "created": 1, "model": "gpt-4o",
         "choices": [{"index": 0, "delta": {"content": injected}, "finish_reason": None}]},
        {"id": "c1", "object": "chat.completion.chunk", "created": 1, "model": "gpt-4o",
         "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
    ]
    sse_body = _sse_stream_chunks(chunks) + b"data: [DONE]\n\n"
    responders = {"p": lambda info: (200, "text/event-stream", sse_body)}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(tiers, vendors, responders=responders)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        status, content_type, raw = _send_proxy_request_stream(
            proxy_port, body={"model": "sonnet", "messages": [{"role": "user", "content": "hi"}]})
        if status != 200:
            fail("expected 200, got {}".format(status))
            return
        # The injection must be confined inside a single JSON payload: a real
        # \n event: line only ever appears as an SSE frame boundary emitted by
        # the proxy itself. The terminal message_stop legitimately emits one
        # event: line, so assert exact count 1 and no injected line survives.
        n_real_events = raw.count(b"\nevent: message_stop")
        if b"\ndata: fake" in raw:
            fail("raw data: injection leaked into the client stream")
            return
        if n_real_events != 1:
            fail("injected event: line leaked into the client stream (count={})".format(n_real_events))
            return
        frames = _parse_sse_frames(raw)
        if _sse_types(frames).count("message_stop") != 1:
            fail("message_stop should appear exactly once; injected frame leaked: {}".format(_sse_types(frames)))
            return
        deltas = _sse_frames_with_type(frames, "content_block_delta")
        texts = [d.get("delta", {}).get("text") for d in deltas if isinstance(d.get("delta", {}).get("text"), str)]
        if injected not in texts:
            fail("delta content should arrive intact inside one payload, texts={!r}".format(texts))
        elif _sse_types(frames).count("message_stop") == 1:
            pass_("provider-controlled newlines cannot inject SSE events")
    finally:
        cleanup()




def test_chat_sse_event_line_present():
    """Every data-bearing SSE frame has an event: line matching the JSON type field.

    The Anthropic SDKs dispatch streaming events on the SSE `event:` field
    against a hardcoded whitelist; a data-only frame arrives with event=None and
    is silently dropped. This test inspects the raw wire format (not the JSON
    `type` fallback in _sse_frame_type) so a missing event: line fails the test.
    """
    print("\n--- Test: Chat SSE Event Line Present ---")
    upstream_port = find_free_port()
    tiers = _mode_tiers()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port), "key": "K", "mode": "chat"}}
    chunks = [
        {"id": "c1", "object": "chat.completion.chunk", "created": 1, "model": "gpt-4o",
         "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]},
        {"id": "c1", "object": "chat.completion.chunk", "created": 1, "model": "gpt-4o",
         "choices": [{"index": 0, "delta": {"content": "hi"}, "finish_reason": None}]},
        {"id": "c1", "object": "chat.completion.chunk", "created": 1, "model": "gpt-4o",
         "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
    ]
    sse_body = _sse_stream_chunks(chunks) + b"data: [DONE]\n\n"
    responders = {"p": lambda info: (200, "text/event-stream", sse_body)}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(tiers, vendors, responders=responders)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        status, content_type, raw = _send_proxy_request_stream(
            proxy_port, body={"model": "sonnet", "messages": [{"role": "user", "content": "hi"}]})
        if status != 200:
            fail("expected 200, got {}".format(status))
            return
        # Parse the raw wire format: extract event: lines and data: JSON independently.
        text = raw.decode("utf-8", errors="replace")
        wire_frames = []
        for block in text.split("\n\n"):
            block = block.strip("\n").strip("\r")
            if not block:
                continue
            event_line = None
            data_payload = None
            for line in block.split("\n"):
                line = line.strip("\r")
                if line.startswith("event:"):
                    event_line = line[6:].strip()
                elif line.startswith("data:"):
                    data_payload = line[5:].strip()
            if data_payload is not None:
                wire_frames.append((event_line, data_payload))
        if not wire_frames:
            fail("no data-bearing SSE frames found in client stream")
            return
        bad = []
        for event_line, data_payload in wire_frames:
            try:
                parsed = json.loads(data_payload)
            except Exception:
                continue
            if not isinstance(parsed, dict) or "type" not in parsed:
                continue
            json_type = parsed.get("type")
            if not event_line or event_line != json_type:
                bad.append((event_line, json_type))
        if bad:
            fail("SSE frames missing/mismatched event: line: {}".format(bad))
            return
        # A data-only frame (no event: line) must never be emitted — it would be
        # silently dropped by the Anthropic SDK.
        for event_line, data_payload in wire_frames:
            if event_line is None:
                fail("data-only SSE frame emitted (no event: line): {!r}".format(data_payload))
                return
        pass_("every data-bearing SSE frame has an event: line matching JSON type")
    finally:
        cleanup()




def test_chat_sse_single_tool_call_fragmented_arguments():
    """A single tool call split across frames emits one tool_use block with ordered deltas."""
    print("\n--- Test: Chat SSE Single Tool Call Fragmented Arguments ---")
    chunks = [
        _cc({"role": "assistant"}),
        _cc({"tool_calls": [{"index": 0, "id": "call_1", "type": "function",
                             "function": {"name": "get_weather"}}]}),
        _cc({"tool_calls": [{"index": 0, "function": {"arguments": "{\"city\":"}}]}),
        _cc({"tool_calls": [{"index": 0, "function": {"arguments": "\"NYC\"}"}}]}),
        _cc({}, finish="tool_calls"),
    ]
    proxy_port, trace_file, cleanup = _start_chat_sse_proxy(chunks)
    if proxy_port is None:
        return
    try:
        frames = _chat_sse_fetch_frames(proxy_port)
        if frames is None:
            return
        blocks = _sse_tool_use_blocks(frames)
        if len(blocks) != 1:
            fail("expected exactly one tool_use block, got {!r}".format(blocks))
            return
        b = blocks[0]
        if b["index"] != 0 or b["id"] != "call_1" or b["name"] != "get_weather" \
                or b["input"] != {"city": "NYC"} or not b["closed"]:
            fail("tool_use block mismatch: {!r}".format(b))
            return
        if _sse_content_block_starts(frames) != [(0, "tool_use")]:
            fail("expected one tool_use start at index 0, got {!r}".format(_sse_content_block_starts(frames)))
            return
        deltas = _sse_frames_with_type(frames, "content_block_delta")
        frags = [(d.get("index"), d.get("delta", {}).get("type"), d.get("delta", {}).get("partial_json"))
                 for d in deltas]
        if frags != [(0, "input_json_delta", '{"city":'), (0, "input_json_delta", '"NYC"}')]:
            fail("expected ordered input_json_delta fragments at index 0, got {!r}".format(frags))
            return
        if _sse_types(frames) != ["message_start", "content_block_start", "content_block_delta",
                                  "content_block_delta", "content_block_stop",
                                  "message_delta", "message_stop"]:
            fail("unexpected event sequence: {}".format(_sse_types(frames)))
            return
        if _sse_stop_reason(frames) != "tool_use":
            fail("expected stop_reason tool_use, got {!r}".format(_sse_stop_reason(frames)))
            return
        pass_("single fragmented tool call -> one tool_use block, ordered deltas, stop tool_use")
    finally:
        cleanup()




def test_chat_sse_parallel_tool_calls_interleaved():
    """Two interleaved tool indexes keep per-call association and close ascending."""
    print("\n--- Test: Chat SSE Parallel Tool Calls Interleaved ---")
    chunks = [
        _cc({"role": "assistant"}),
        _cc({"tool_calls": [{"index": 0, "id": "call_a", "function": {"name": "tool_a",
                                                                      "arguments": "{\"x\":"}}]}),
        _cc({"tool_calls": [{"index": 1, "id": "call_b", "function": {"name": "tool_b",
                                                                      "arguments": "{\"y\":"}}]}),
        _cc({"tool_calls": [{"index": 0, "function": {"arguments": "1}"}}]}),
        _cc({"tool_calls": [{"index": 1, "function": {"arguments": "2}"}}]}),
        _cc({}, finish="tool_calls"),
    ]
    proxy_port, trace_file, cleanup = _start_chat_sse_proxy(chunks)
    if proxy_port is None:
        return
    try:
        frames = _chat_sse_fetch_frames(proxy_port)
        if frames is None:
            return
        blocks = _sse_tool_use_blocks(frames)
        if len(blocks) != 2:
            fail("expected 2 tool_use blocks, got {!r}".format(blocks))
            return
        by_idx = {b["index"]: b for b in blocks}
        if set(by_idx) != {0, 1}:
            fail("tool block indices should be {{0, 1}}, got {!r}".format(list(by_idx)))
            return
        a, b = by_idx[0], by_idx[1]
        if a["id"] != "call_a" or a["name"] != "tool_a" or a["input"] != {"x": 1} or not a["closed"]:
            fail("index 0 tool block wrong: {!r}".format(a))
            return
        if b["id"] != "call_b" or b["name"] != "tool_b" or b["input"] != {"y": 2} or not b["closed"]:
            fail("index 1 tool block wrong: {!r}".format(b))
            return
        if _sse_content_block_starts(frames) != [(0, "tool_use"), (1, "tool_use")]:
            fail("contiguous tool starts [0, 1] required, got {!r}".format(_sse_content_block_starts(frames)))
            return
        stop_idx = [data.get("index") for name, data in frames
                    if _sse_frame_type((name, data)) == "content_block_stop" and isinstance(data, dict)]
        if stop_idx != [0, 1]:
            fail("content_block_stop must close ascending [0, 1], got {!r}".format(stop_idx))
            return
        if _sse_types(frames).count("content_block_start") != 2 or _sse_types(frames).count("content_block_stop") != 2:
            fail("expected exactly 2 starts and 2 stops, got {}".format(_sse_types(frames)))
            return
        deltas = _sse_frames_with_type(frames, "content_block_delta")
        frag_seq = [(d.get("index"), d.get("delta", {}).get("partial_json")) for d in deltas]
        if frag_seq != [(0, '{"x":'), (1, '{"y":'), (0, "1}"), (1, "2}")]:
            fail("interleaved fragments mis-associated: {!r}".format(frag_seq))
            return
        if _sse_stop_reason(frames) != "tool_use":
            fail("expected stop_reason tool_use, got {!r}".format(_sse_stop_reason(frames)))
            return
        pass_("interleaved parallel tool calls keep association, contiguous indices, ascending close")
    finally:
        cleanup()




def test_chat_sse_reasoning_text_then_tool_call():
    """Scalar blocks close before a tool block starts; indices stay contiguous."""
    print("\n--- Test: Chat SSE Reasoning Text Then Tool Call ---")
    chunks = [
        _cc({"role": "assistant", "reasoning_content": "Let me think"}),
        _cc({"content": "text answer"}),
        _cc({"tool_calls": [{"index": 0, "id": "call_1",
                             "function": {"name": "Bash", "arguments": "{\"command\":\"ls\"}"}}]}),
        _cc({}, finish="tool_calls"),
    ]
    proxy_port, trace_file, cleanup = _start_chat_sse_proxy(chunks)
    if proxy_port is None:
        return
    try:
        frames = _chat_sse_fetch_frames(proxy_port)
        if frames is None:
            return
        starts = _sse_content_block_starts(frames)
        if starts != [(0, "thinking"), (1, "text"), (2, "tool_use")]:
            fail("scalar-then-tool indices/types wrong: {!r}".format(starts))
            return
        seq = []
        for name, data in frames:
            t = _sse_frame_type((name, data))
            if t in ("content_block_start", "content_block_stop") and isinstance(data, dict):
                seq.append((t, data.get("index")))
        expected_seq = [("content_block_start", 0), ("content_block_stop", 0),
                        ("content_block_start", 1), ("content_block_stop", 1),
                        ("content_block_start", 2), ("content_block_stop", 2)]
        if seq != expected_seq:
            fail("block lifecycle order wrong: {!r}".format(seq))
            return
        blocks = _sse_tool_use_blocks(frames)
        if len(blocks) != 1 or blocks[0]["id"] != "call_1" or blocks[0]["name"] != "Bash" \
                or blocks[0]["input"] != {"command": "ls"} or not blocks[0]["closed"]:
            fail("tool block mismatch: {!r}".format(blocks))
            return
        if _sse_stop_reason(frames) != "tool_use":
            fail("expected stop_reason tool_use, got {!r}".format(_sse_stop_reason(frames)))
            return
        pass_("reasoning/text blocks close before tool start; indices unique and contiguous")
    finally:
        cleanup()




def test_chat_sse_tool_call_metadata_buffering():
    """Arguments arriving before id/name are buffered and emitted in order after the start."""
    print("\n--- Test: Chat SSE Tool Call Metadata Buffering ---")
    chunks = [
        _cc({"role": "assistant"}),
        _cc({"tool_calls": [{"index": 0, "function": {"arguments": "{\"city\":"}}]}),
        _cc({"tool_calls": [{"index": 0, "function": {"arguments": "\"NYC\"}"}}]}),
        _cc({"tool_calls": [{"index": 0, "id": "call_1", "function": {"name": "get_weather"}}]}),
        _cc({}, finish="tool_calls"),
    ]
    proxy_port, trace_file, cleanup = _start_chat_sse_proxy(chunks)
    if proxy_port is None:
        return
    try:
        frames = _chat_sse_fetch_frames(proxy_port)
        if frames is None:
            return
        blocks = _sse_tool_use_blocks(frames)
        if len(blocks) != 1 or blocks[0]["id"] != "call_1" or blocks[0]["name"] != "get_weather" \
                or blocks[0]["input"] != {"city": "NYC"} or not blocks[0]["closed"]:
            fail("buffered tool block mismatch: {!r}".format(blocks))
            return
        types = _sse_types(frames)
        start_pos = types.index("content_block_start")
        delta_positions = [i for i, t in enumerate(types) if t == "content_block_delta"]
        if not delta_positions or any(p < start_pos for p in delta_positions):
            fail("buffered fragments must emit after content_block_start: {}".format(types))
            return
        deltas = _sse_frames_with_type(frames, "content_block_delta")
        frags = [d.get("delta", {}).get("partial_json") for d in deltas]
        if frags != ['{"city":', '"NYC"}']:
            fail("fragments must be emitted in original order, got {!r}".format(frags))
            return
        if _sse_stop_reason(frames) != "tool_use":
            fail("expected stop_reason tool_use, got {!r}".format(_sse_stop_reason(frames)))
            return
        pass_("arguments before metadata buffered and emitted in order after the start")
    finally:
        cleanup()




def test_chat_sse_malformed_tool_call_degrades():
    """Malformed tool-call deltas never emit a tool_use block; one metadata-only trace event.

    Covers missing/non-string index, non-string id, and null function object.
    The coalesced event must carry request_id and integer counts only — no tool
    id/name/fragment text/request body.
    """
    print("\n--- Test: Chat SSE Malformed Tool Call Degrades ---")

    def run_case(chunks, markers):
        proxy_port, trace_file, cleanup = _start_chat_sse_proxy(chunks)
        if proxy_port is None:
            return False
        try:
            frames = _chat_sse_fetch_frames(proxy_port)
            if frames is None:
                return False
            if _sse_content_block_starts(frames):
                fail("malformed tool deltas must not emit a content_block_start: {!r}".format(
                    _sse_content_block_starts(frames)))
                return False
            if "message_stop" not in _sse_types(frames):
                fail("malformed stream must still terminate cleanly with message_stop")
                return False
            if _sse_stop_reason(frames) is not None:
                fail("no-valid-tool stream must degrade to null stop_reason, got {!r}".format(
                    _sse_stop_reason(frames)))
                return False
            events = _degraded_trace_events(trace_file)
            if len(events) != 1:
                fail("expected exactly one chat_sse_tool_degradation trace event, got {}".format(len(events)))
                return False
            ev = events[0]
            if not ev.get("request_id"):
                fail("degradation event missing request_id: {!r}".format(ev))
                return False
            blob = json.dumps(ev)
            for marker in markers:
                if marker in blob:
                    fail("degradation event leaked tool content marker {!r}: {}".format(marker, blob))
                    return False
            return True
        finally:
            cleanup()

    ok = True
    if not run_case([
        _cc({"role": "assistant"}),
        _cc({"tool_calls": [{"index": "x", "id": "call_mal_a", "function": {"name": "fx", "arguments": "{frag"}}]}),
        _cc({}, finish="tool_calls"),
    ], ["call_mal_a", "fx", "{frag"]):
        ok = False
    if not run_case([
        _cc({"role": "assistant"}),
        _cc({"tool_calls": [{"index": 0, "id": 123, "function": {"name": "nb", "arguments": "{}"}}]}),
        _cc({}, finish="tool_calls"),
    ], ["nb"]):
        ok = False
    if not run_case([
        _cc({"role": "assistant"}),
        _cc({"tool_calls": [{"index": 0, "id": "call_nullfn", "function": None}]}),
        _cc({}, finish="tool_calls"),
    ], ["call_nullfn"]):
        ok = False
    if ok:
        pass_("malformed tool deltas degrade to null stop_reason with one metadata-only trace event")




def test_chat_sse_mixed_valid_and_malformed_tool_calls():
    """A valid parallel call survives alongside a malformed entry without contamination."""
    print("\n--- Test: Chat SSE Mixed Valid And Malformed Tool Calls ---")
    chunks = [
        _cc({"role": "assistant"}),
        _cc({"tool_calls": [{"index": 0, "id": "call_ok", "function": {"name": "ok", "arguments": "{\"a\":1}"}}]}),
        _cc({"tool_calls": [{"index": 1, "function": None}]}),
        _cc({}, finish="tool_calls"),
    ]
    proxy_port, trace_file, cleanup = _start_chat_sse_proxy(chunks)
    if proxy_port is None:
        return
    try:
        frames = _chat_sse_fetch_frames(proxy_port)
        if frames is None:
            return
        blocks = _sse_tool_use_blocks(frames)
        if len(blocks) != 1:
            fail("valid call should survive alongside malformed, got {!r}".format(blocks))
            return
        b = blocks[0]
        if b["index"] != 0 or b["id"] != "call_ok" or b["name"] != "ok" or b["input"] != {"a": 1} or not b["closed"]:
            fail("valid block mismatch: {!r}".format(b))
            return
        if _sse_stop_reason(frames) != "tool_use":
            fail("surviving valid block should map finish tool_calls to tool_use, got {!r}".format(_sse_stop_reason(frames)))
            return
        events = _degraded_trace_events(trace_file)
        if len(events) != 1:
            fail("malformed entry must be diagnosed once, got {}".format(len(events)))
            return
        pass_("valid parallel call survives; malformed entry diagnosed without contamination")
    finally:
        cleanup()




def test_chat_sse_tool_call_eof_without_finish():
    """EOF without finish_reason: valid blocks close and get null; no deltas get end_turn."""
    print("\n--- Test: Chat SSE Tool Call EOF Without Finish ---")
    chunks_a = [
        _cc({"role": "assistant"}),
        _cc({"tool_calls": [{"index": 0, "id": "call_eof", "function": {"name": "eof_tool", "arguments": "{\"z\":9}"}}]}),
    ]
    proxy_port, trace_file, cleanup = _start_chat_sse_proxy(chunks_a)
    if proxy_port is None:
        return
    try:
        frames = _chat_sse_fetch_frames(proxy_port)
        if frames is None:
            return
        blocks = _sse_tool_use_blocks(frames)
        if len(blocks) != 1 or not blocks[0]["closed"]:
            fail("EOF after valid tool deltas must close the emitted block, got {!r}".format(blocks))
            return
        if blocks[0]["input"] != {"z": 9}:
            fail("EOF tool block input wrong: {!r}".format(blocks[0]))
            return
        if _sse_stop_reason(frames) is not None:
            fail("EOF with emitted tool block must degrade to null stop_reason, got {!r}".format(_sse_stop_reason(frames)))
            return
        if "message_stop" not in _sse_types(frames):
            fail("EOF must synthesize message_stop")
            return
    finally:
        cleanup()
    chunks_b = [
        _cc({"role": "assistant", "content": "hi"}),
    ]
    proxy_port2, trace_file2, cleanup2 = _start_chat_sse_proxy(chunks_b)
    if proxy_port2 is None:
        return
    try:
        frames2 = _chat_sse_fetch_frames(proxy_port2)
        if frames2 is None:
            return
        if _sse_stop_reason(frames2) != "end_turn":
            fail("EOF with no tool deltas should map to end_turn, got {!r}".format(_sse_stop_reason(frames2)))
            return
        if "message_stop" not in _sse_types(frames2):
            fail("EOF must synthesize message_stop (no-tools case)")
            return
    finally:
        cleanup2()
    chunks_c = [
        _cc({"role": "assistant"}),
        _cc({"tool_calls": [{"index": 0, "id": "call_incomplete"}]}),
    ]
    proxy_port3, trace_file3, cleanup3 = _start_chat_sse_proxy(chunks_c)
    if proxy_port3 is None:
        return
    try:
        frames3 = _chat_sse_fetch_frames(proxy_port3)
        if frames3 is None:
            return
        if _sse_content_block_starts(frames3):
            fail("incomplete metadata must not emit a tool_use at EOF, got {!r}".format(_sse_content_block_starts(frames3)))
            return
        if _sse_stop_reason(frames3) is not None:
            fail("incomplete tool metadata at EOF must degrade to null, got {!r}".format(_sse_stop_reason(frames3)))
            return
        events = _degraded_trace_events(trace_file3)
        if len(events) != 1:
            fail("incomplete metadata at EOF must fire the coalesced trace event, got {}".format(len(events)))
            return
    finally:
        cleanup3()
    pass_("EOF: emitted tool block -> null; no tool deltas -> end_turn; incomplete metadata -> null + trace")




def test_chat_sse_non_tool_calls_finish_with_tool_blocks():
    """A length/stop finish while tool blocks are open closes them and maps.

    A non-"stop" reason still maps verbatim (length -> max_tokens). "stop"
    alongside emitted tool calls is upgraded to tool_use: the client must wait
    for tool results rather than stopping for user input. That is the same
    upgrade the post-finish drain applies, reached here with no drain at all.
    """
    print("\n--- Test: Chat SSE Non Tool Calls Finish With Tool Blocks ---")
    base = [
        _cc({"role": "assistant"}),
        _cc({"tool_calls": [{"index": 0, "id": "call_1", "function": {"name": "len_tool", "arguments": "{\"a\":1}"}}]}),
    ]
    proxy_port, trace_file, cleanup = _start_chat_sse_proxy(base + [_cc({}, finish="length")])
    if proxy_port is None:
        return
    try:
        frames = _chat_sse_fetch_frames(proxy_port)
        if frames is None:
            return
        blocks = _sse_tool_use_blocks(frames)
        if len(blocks) != 1 or not blocks[0]["closed"]:
            fail("length finish with open tool blocks must close them, got {!r}".format(blocks))
            return
        if _sse_stop_reason(frames) != "max_tokens":
            fail("length finish should map to max_tokens (never tool_use), got {!r}".format(_sse_stop_reason(frames)))
            return
        events = _degraded_trace_events(trace_file)
        if len(events) != 1:
            fail("non-tool_calls finish with open tool blocks must log the coalesced event, got {}".format(len(events)))
            return
    finally:
        cleanup()
    proxy_port2, trace_file2, cleanup2 = _start_chat_sse_proxy(base + [_cc({}, finish="stop")])
    if proxy_port2 is None:
        return
    try:
        frames2 = _chat_sse_fetch_frames(proxy_port2)
        if frames2 is None:
            return
        blocks2 = _sse_tool_use_blocks(frames2)
        if len(blocks2) != 1 or not blocks2[0]["closed"]:
            fail("stop finish with open tool blocks must close them, got {!r}".format(blocks2))
            return
        if _sse_stop_reason(frames2) != "tool_use":
            fail("stop finish with emitted tool blocks must upgrade to tool_use, got {!r}".format(_sse_stop_reason(frames2)))
            return
    finally:
        cleanup2()
    pass_("non-tool_calls finish with open tool blocks: close blocks, map/upgrade finish, log event")




def test_chat_sse_scalar_delta_after_tool_blocks():
    """Scalar deltas after the first tool block are dropped with a counted diagnostic."""
    print("\n--- Test: Chat SSE Scalar Delta After Tool Blocks ---")
    chunks = [
        _cc({"role": "assistant"}),
        _cc({"tool_calls": [{"index": 0, "id": "call_1", "function": {"name": "t", "arguments": "{\"a\":1}"}}]}),
        _cc({"content": "late text"}),
        _cc({"reasoning_content": "late think"}),
        _cc({}, finish="tool_calls"),
    ]
    proxy_port, trace_file, cleanup = _start_chat_sse_proxy(chunks)
    if proxy_port is None:
        return
    try:
        frames = _chat_sse_fetch_frames(proxy_port)
        if frames is None:
            return
        if _sse_content_block_starts(frames) != [(0, "tool_use")]:
            fail("no scalar content_block_start may follow a tool block, got {!r}".format(_sse_content_block_starts(frames)))
            return
        deltas = _sse_frames_with_type(frames, "content_block_delta")
        text_bits = [d.get("delta", {}).get("text") for d in deltas if isinstance(d.get("delta", {}).get("text"), str)]
        think_bits = [d.get("delta", {}).get("thinking") for d in deltas if isinstance(d.get("delta", {}).get("thinking"), str)]
        if text_bits or think_bits:
            fail("scalar deltas after tool blocks must be dropped, text={!r} thinking={!r}".format(text_bits, think_bits))
            return
        blocks = _sse_tool_use_blocks(frames)
        if len(blocks) != 1 or blocks[0]["input"] != {"a": 1}:
            fail("tool block contaminated by late scalar deltas: {!r}".format(blocks))
            return
        if _sse_stop_reason(frames) != "tool_use":
            fail("valid tool block should still yield tool_use, got {!r}".format(_sse_stop_reason(frames)))
            return
        events = _degraded_trace_events(trace_file)
        if len(events) != 1 or events[0].get("scalar_after_tools_dropped") != 2:
            fail("dropped scalar deltas must be counted (2) once, got {!r}".format(events))
            return
        pass_("scalar deltas after tool blocks dropped with counted diagnostic; tool block intact")
    finally:
        cleanup()




def test_chat_sse_final_fragment_in_finish_frame():
    """The last argument fragment sharing the finish frame is emitted before close."""
    print("\n--- Test: Chat SSE Final Fragment In Finish Frame ---")
    chunks = [
        _cc({"role": "assistant"}),
        _cc({"tool_calls": [{"index": 0, "id": "call_1", "function": {"name": "t", "arguments": "{\"a\":"}}]}),
        {"id": "c1", "object": "chat.completion.chunk", "created": 1, "model": "gpt-4o",
         "choices": [{"index": 0,
                      "delta": {"tool_calls": [{"index": 0, "function": {"arguments": "1}"}}]},
                      "finish_reason": "tool_calls"}]},
    ]
    proxy_port, trace_file, cleanup = _start_chat_sse_proxy(chunks)
    if proxy_port is None:
        return
    try:
        frames = _chat_sse_fetch_frames(proxy_port)
        if frames is None:
            return
        blocks = _sse_tool_use_blocks(frames)
        if len(blocks) != 1 or blocks[0]["input"] != {"a": 1}:
            fail("final fragment in the finish frame must be included, got {!r}".format(blocks))
            return
        types = _sse_types(frames)
        delta_pos = types.index("content_block_delta")
        stop_pos = types.index("content_block_stop")
        if not (delta_pos < stop_pos):
            fail("final fragment delta must be emitted before tool close: {}".format(types))
            return
        if _sse_stop_reason(frames) != "tool_use":
            fail("expected stop_reason tool_use, got {!r}".format(_sse_stop_reason(frames)))
            return
        pass_("final fragment in finish frame emitted before close and claimed tool_use")
    finally:
        cleanup()




def test_chat_sse_no_deltas_tool_calls_finish():
    """finish_reason tool_calls with zero tool-call deltas degrades to null (never tool_use)."""
    print("\n--- Test: Chat SSE No Deltas Tool Calls Finish ---")
    chunks = [
        _cc({"role": "assistant", "content": "ok"}),
        _cc({}, finish="tool_calls"),
    ]
    proxy_port, trace_file, cleanup = _start_chat_sse_proxy(chunks)
    if proxy_port is None:
        return
    try:
        frames = _chat_sse_fetch_frames(proxy_port)
        if frames is None:
            return
        if _sse_stop_reason(frames) is not None:
            fail("tool_calls finish with zero tool deltas must degrade to null stop_reason, got {!r}".format(_sse_stop_reason(frames)))
            return
        if _sse_content_block_starts(frames) != [(0, "text")]:
            fail("expected only the text block, got {!r}".format(_sse_content_block_starts(frames)))
            return
        if "message_stop" not in _sse_types(frames):
            fail("message_stop must be emitted")
            return
        pass_("tool_calls finish with zero deltas -> null stop_reason")
    finally:
        cleanup()




def test_chat_sse_unparseable_arguments_at_close():
    """Valid metadata + tool_calls finish: the emitted block claims tool_use.

    D4-revised (2026-10-03): the stop reason follows block emission, not argument
    parseability. A tool_use block reached the client, so the finish reason is
    tool_use; unparseable_arg_count stays a diagnostic only.
    """
    print("\n--- Test: Chat SSE Unparseable Arguments At Close ---")
    chunks = [
        _cc({"role": "assistant"}),
        _cc({"tool_calls": [{"index": 0, "id": "call_1", "function": {"name": "bad", "arguments": "{oops"}}]}),
        _cc({}, finish="tool_calls"),
    ]
    proxy_port, trace_file, cleanup = _start_chat_sse_proxy(chunks)
    if proxy_port is None:
        return
    try:
        frames = _chat_sse_fetch_frames(proxy_port)
        if frames is None:
            return
        blocks = _sse_tool_use_blocks(frames)
        if len(blocks) != 1 or not blocks[0]["closed"]:
            fail("unparseable-args tool block should still be emitted and closed, got {!r}".format(blocks))
            return
        if _sse_stop_reason(frames) != "tool_use":
            fail("emitted tool block must claim tool_use even with unparseable args, got {!r}".format(_sse_stop_reason(frames)))
            return
        events = _degraded_trace_events(trace_file)
        if len(events) != 1 or events[0].get("unparseable_arg_count") != 1:
            fail("expected one event with unparseable_arg_count 1, got {!r}".format(events))
            return
        pass_("unparseable accumulated arguments: block emitted, stop_reason tool_use, count diagnostic")
    finally:
        cleanup()




def test_chat_sse_conflicting_metadata():
    """A later valid-but-different id/name on an existing index is treated as malformed."""
    print("\n--- Test: Chat SSE Conflicting Metadata ---")
    chunks_a = [
        _cc({"role": "assistant"}),
        _cc({"tool_calls": [{"index": 0, "id": "call_orig"}]}),
        _cc({"tool_calls": [{"index": 0, "id": "call_other", "function": {"name": "n1", "arguments": "{}"}}]}),
        _cc({}, finish="tool_calls"),
    ]
    proxy_port, trace_file, cleanup = _start_chat_sse_proxy(chunks_a)
    if proxy_port is None:
        return
    try:
        frames = _chat_sse_fetch_frames(proxy_port)
        if frames is None:
            return
        if _sse_content_block_starts(frames):
            fail("conflicting id must prevent tool_use emission, got {!r}".format(_sse_content_block_starts(frames)))
            return
        if _sse_stop_reason(frames) is not None:
            fail("conflicting id must degrade stop_reason to null, got {!r}".format(_sse_stop_reason(frames)))
            return
        if len(_degraded_trace_events(trace_file)) != 1:
            fail("conflicting id must log one degradation event")
            return
    finally:
        cleanup()
    chunks_b = [
        _cc({"role": "assistant"}),
        _cc({"tool_calls": [{"index": 0, "function": {"name": "n1"}}]}),
        _cc({"tool_calls": [{"index": 0, "function": {"name": "n2"}}]}),
        _cc({"tool_calls": [{"index": 0, "id": "call_c"}]}),
        _cc({}, finish="tool_calls"),
    ]
    proxy_port2, trace_file2, cleanup2 = _start_chat_sse_proxy(chunks_b)
    if proxy_port2 is None:
        return
    try:
        frames2 = _chat_sse_fetch_frames(proxy_port2)
        if frames2 is None:
            return
        if _sse_content_block_starts(frames2):
            fail("conflicting name must prevent tool_use emission, got {!r}".format(_sse_content_block_starts(frames2)))
            return
        if _sse_stop_reason(frames2) is not None:
            fail("conflicting name must degrade stop_reason to null, got {!r}".format(_sse_stop_reason(frames2)))
            return
        if len(_degraded_trace_events(trace_file2)) != 1:
            fail("conflicting name must log one degradation event")
            return
    finally:
        cleanup2()
    pass_("conflicting id/name on an existing index degrades the entry (coalesced trace, no tool_use)")




def test_chat_sse_fragments_missing_index():
    """Non-empty fragments without an index are dropped and counted; the block still claims tool_use.

    D4-revised (2026-10-03): a dropped fragment no longer forces the stop reason
    to null — the started block was emitted, so tool_use is claimed. The drop is
    still diagnosed via dropped_fragment_count.
    """
    print("\n--- Test: Chat SSE Fragments Missing Index ---")
    chunks = [
        _cc({"role": "assistant"}),
        _cc({"tool_calls": [{"index": 0, "id": "call_1", "function": {"name": "frag_tool", "arguments": "{\"a\":1}"}}]}),
        _cc({"tool_calls": [{"function": {"arguments": "{\"b\":2}"}}]}),
        _cc({}, finish="tool_calls"),
    ]
    proxy_port, trace_file, cleanup = _start_chat_sse_proxy(chunks)
    if proxy_port is None:
        return
    try:
        frames = _chat_sse_fetch_frames(proxy_port)
        if frames is None:
            return
        blocks = _sse_tool_use_blocks(frames)
        if len(blocks) != 1 or blocks[0]["input"] != {"a": 1}:
            fail("index-less fragment must not contaminate the started block, got {!r}".format(blocks))
            return
        if _sse_stop_reason(frames) != "tool_use":
            fail("emitted block must claim tool_use despite the dropped fragment, got {!r}".format(_sse_stop_reason(frames)))
            return
        events = _degraded_trace_events(trace_file)
        if len(events) != 1 or events[0].get("dropped_fragment_count") != 1:
            fail("expected one event with dropped_fragment_count 1, got {!r}".format(events))
            return
        pass_("index-less fragments dropped and counted; emitted block still claims tool_use")
    finally:
        cleanup()




def test_chat_sse_malformed_delta_shapes():
    """Malformed delta shapes are skipped without crashing; the stream still terminates."""
    print("\n--- Test: Chat SSE Malformed Delta Shapes ---")
    chunks = [
        _cc({"role": "assistant"}),
        _cc({"tool_calls": [123]}),
        _cc({"tool_calls": "abc"}),
        _cc({"tool_calls": [None]}),
        _cc("oops"),
        _cc({}, finish="stop"),
    ]
    proxy_port, trace_file, cleanup = _start_chat_sse_proxy(chunks)
    if proxy_port is None:
        return
    try:
        frames = _chat_sse_fetch_frames(proxy_port)
        if frames is None:
            return
        if _sse_content_block_starts(frames):
            fail("malformed delta shapes must not emit content blocks, got {!r}".format(_sse_content_block_starts(frames)))
            return
        if "message_stop" not in _sse_types(frames):
            fail("malformed delta frames must not crash mid-stream; message_stop required")
            return
        if _sse_stop_reason(frames) != "end_turn":
            fail("stop finish maps to end_turn, got {!r}".format(_sse_stop_reason(frames)))
            return
        events = _degraded_trace_events(trace_file)
        if len(events) != 1:
            fail("expected exactly one coalesced degradation event, got {}".format(len(events)))
            return
        if events[0].get("malformed_tool_count", 0) < 3:
            fail("malformed_tool_count should count the bad shapes, got {!r}".format(events[0]))
            return
        pass_("malformed delta shapes skipped; stream terminates cleanly with one trace event")
    finally:
        cleanup()




def test_chat_sse_pending_buffer_cap_exceeded():
    """Pending argument fragments exceeding the per-tool cap never emit a tool_use."""
    print("\n--- Test: Chat SSE Pending Buffer Cap Exceeded ---")
    frag = 'x' * 8000
    chunks = [_cc({"role": "assistant"})]
    for _ in range(12):
        chunks.append(_cc({"tool_calls": [{"index": 0, "function": {"arguments": frag}}]}))
    proxy_port, trace_file, cleanup = _start_chat_sse_proxy(chunks)
    if proxy_port is None:
        return
    try:
        frames = _chat_sse_fetch_frames(proxy_port)
        if frames is None:
            return
        if _sse_content_block_starts(frames):
            fail("pending buffer over the per-tool cap must never emit a tool_use, got {!r}".format(_sse_content_block_starts(frames)))
            return
        if _sse_stop_reason(frames) is not None:
            fail("overflowed pending buffer must not claim tool_use, got {!r}".format(_sse_stop_reason(frames)))
            return
        events = _degraded_trace_events(trace_file)
        if len(events) != 1:
            fail("expected exactly one coalesced degradation event on EOF, got {}".format(len(events)))
            return
        if events[0].get("malformed_tool_count", 0) < 1:
            fail("overflowed pending buffer should be counted, got {!r}".format(events[0]))
            return
        pass_("per-tool pending buffer cap bounds memory and degrades without claiming tool_use")
    finally:
        cleanup()




def test_chat_sse_too_many_parallel_tools():
    """More than 32 tracked tool indexes overflow into the coalesced diagnostic.

    D4-revised (2026-10-03): the 32 blocks emitted before the 33rd overflowed
    claim tool_use; overflow_tool_count remains a diagnostic only.
    """
    print("\n--- Test: Chat SSE Too Many Parallel Tools ---")
    chunks = [_cc({"role": "assistant"})]
    for i in range(33):
        chunks.append(_cc({"tool_calls": [{"index": i, "id": "call_{}".format(i),
                                           "function": {"name": "t{}".format(i),
                                                        "arguments": "{}"}}]}))
    chunks.append(_cc({}, finish="tool_calls"))
    proxy_port, trace_file, cleanup = _start_chat_sse_proxy(chunks)
    if proxy_port is None:
        return
    try:
        frames = _chat_sse_fetch_frames(proxy_port)
        if frames is None:
            return
        starts = _sse_content_block_starts(frames)
        if len(starts) != 32:
            fail("expected 32 tracked tool starts (33rd overflows), got {}".format(len(starts)))
            return
        if [s[0] for s in starts] != list(range(32)):
            fail("tool starts must use contiguous indices 0..31, got {!r}".format([s[0] for s in starts]))
            return
        if _sse_stop_reason(frames) != "tool_use":
            fail("emitted parallel blocks must claim tool_use despite the overflow, got {!r}".format(_sse_stop_reason(frames)))
            return
        events = _degraded_trace_events(trace_file)
        if len(events) != 1 or events[0].get("overflow_tool_count") != 1:
            fail("expected overflow_tool_count 1 in one event, got {!r}".format(events))
            return
        pass_("33 parallel tool indexes: 32 started contiguously, overflow diagnosed, stop tool_use")
    finally:
        cleanup()




def test_chat_sse_eof_empty_tool_calls_sentinel():
    """An empty tool_calls: [] sentinel frame must not mark tool deltas seen at EOF.

    R1 review remediation: tool_calls_seen is set only when delta.tool_calls is
    truthy — an empty list is falsy — so a stream that ends after only this
    sentinel terminates with stop_reason "end_turn" (never null), emits no
    tool_use block, and fires no degradation event.
    """
    print("\n--- Test: Chat SSE EOF Empty Tool Calls Sentinel ---")
    chunks = [
        _cc({"role": "assistant", "tool_calls": []}),
    ]
    proxy_port, trace_file, cleanup = _start_chat_sse_proxy(chunks)
    if proxy_port is None:
        return
    try:
        frames = _chat_sse_fetch_frames(proxy_port)
        if frames is None:
            return
        if _sse_content_block_starts(frames):
            fail("empty tool_calls sentinel must not emit a tool block, got {!r}".format(_sse_content_block_starts(frames)))
            return
        if _sse_stop_reason(frames) != "end_turn":
            fail("EOF after empty tool_calls sentinel must stop with end_turn, got {!r}".format(_sse_stop_reason(frames)))
            return
        if "message_stop" not in _sse_types(frames):
            fail("EOF must synthesize message_stop")
            return
        if _degraded_trace_events(trace_file):
            fail("empty tool_calls sentinel at EOF must not fire a degradation event, got {!r}".format(_degraded_trace_events(trace_file)))
            return
        pass_("EOF + empty tool_calls sentinel -> end_turn, no tool_use, no degradation event")
    finally:
        cleanup()




def test_chat_sse_mixed_parseable_unparseable_finish():
    """One unparseable parallel tool no longer degrades the stream to a null stop reason.

    D4-revised (2026-10-03): both parallel blocks are emitted, so the finish
    claims tool_use; unparseable_arg_count (== 1) stays a diagnostic. The
    earlier rule gated the stop reason on unparseable_arg_count == 0.
    """
    print("\n--- Test: Chat SSE Mixed Parseable Unparseable Finish ---")
    chunks = [
        _cc({"role": "assistant"}),
        _cc({"tool_calls": [{"index": 0, "id": "call_good", "function": {"name": "good_tool", "arguments": "{\"a\":1}"}}]}),
        _cc({"tool_calls": [{"index": 1, "id": "call_bad", "function": {"name": "bad_tool", "arguments": "{\"b\":"}}]}),
        _cc({}, finish="tool_calls"),
    ]
    proxy_port, trace_file, cleanup = _start_chat_sse_proxy(chunks)
    if proxy_port is None:
        return
    try:
        frames = _chat_sse_fetch_frames(proxy_port)
        if frames is None:
            return
        blocks = _sse_tool_use_blocks(frames)
        if len(blocks) != 2:
            fail("both parallel tools should emit blocks, got {!r}".format(blocks))
            return
        if [b["index"] for b in blocks] != [0, 1] or not all(b["closed"] for b in blocks):
            fail("parallel tools must close ascending 0..1, got {!r}".format(blocks))
            return
        if _sse_types(frames).count("content_block_start") != 2 or _sse_types(frames).count("content_block_stop") != 2:
            fail("expected exactly 2 starts and 2 stops, got {}".format(_sse_types(frames)))
            return
        if _sse_stop_reason(frames) != "tool_use":
            fail("emitted parallel blocks must claim tool_use (one unparseable), got {!r}".format(_sse_stop_reason(frames)))
            return
        events = _degraded_trace_events(trace_file)
        if len(events) != 1:
            fail("expected exactly one degradation event, got {}".format(len(events)))
            return
        if events[0].get("unparseable_arg_count") != 1:
            fail("expected unparseable_arg_count 1, got {!r}".format(events[0]))
            return
        if not _assert_degradation_metadata_only(events[0]):
            return
        blob = json.dumps(events[0])
        for marker in ["call_good", "call_bad", "good_tool", "bad_tool"]:
            if marker in blob:
                fail("degradation event leaked tool marker {!r}: {}".format(marker, blob))
                return
        pass_("mixed parseable+unparseable parallel finish -> tool_use, unparseable_arg_count 1, metadata-only event")
    finally:
        cleanup()




def test_chat_sse_non_dict_arguments_at_close():
    """Arguments that parse but not as a dict (e.g. \"123\") still claim tool_use.

    The block is still emitted (input reconstructed as the non-dict parse), so
    D4-revised (2026-10-03) claims tool_use; unparseable_arg_count stays a
    diagnostic. The earlier rule required a dict parse to claim tool_use.
    """
    print("\n--- Test: Chat SSE Non Dict Arguments At Close ---")
    chunks = [
        _cc({"role": "assistant"}),
        _cc({"tool_calls": [{"index": 0, "id": "call_nd", "function": {"name": "nd_tool", "arguments": "123"}}]}),
        _cc({}, finish="tool_calls"),
    ]
    proxy_port, trace_file, cleanup = _start_chat_sse_proxy(chunks)
    if proxy_port is None:
        return
    try:
        frames = _chat_sse_fetch_frames(proxy_port)
        if frames is None:
            return
        blocks = _sse_tool_use_blocks(frames)
        if len(blocks) != 1 or not blocks[0]["closed"]:
            fail("non-dict args tool should still emit a closed block, got {!r}".format(blocks))
            return
        if blocks[0]["input"] != 123:
            fail("block input should reconstruct the non-dict parse 123, got {!r}".format(blocks[0]["input"]))
            return
        if _sse_stop_reason(frames) != "tool_use":
            fail("emitted block must claim tool_use despite non-dict args, got {!r}".format(_sse_stop_reason(frames)))
            return
        events = _degraded_trace_events(trace_file)
        if len(events) != 1 or events[0].get("unparseable_arg_count") != 1:
            fail("expected unparseable_arg_count 1 in one event, got {!r}".format(events))
            return
        if not _assert_degradation_metadata_only(events[0]):
            return
        blob = json.dumps(events[0])
        for marker in ["call_nd", "nd_tool", "partial_json"]:
            if marker in blob:
                fail("degradation event leaked tool marker {!r}: {}".format(marker, blob))
                return
        pass_("non-dict arguments at close -> tool_use, unparseable_arg_count 1, metadata-only event")
    finally:
        cleanup()




def test_chat_sse_frame_dropped_guard():
    """A mid-stream oversized no-delimiter frame is counted; the emitted block still claims tool_use.

    D4-revised (2026-10-03): frame_dropped no longer blocks the finish claim —
    the tool block was emitted before the drop, so tool_use is claimed. The
    drop is still diagnosed via frame_dropped: 1.
    """
    print("\n--- Test: Chat SSE Frame Dropped Guard ---")
    upstream_port = find_free_port()
    tiers = _mode_tiers()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port), "key": "K", "mode": "chat"}}
    chunks = [
        _cc({"role": "assistant"}),
        _cc({"tool_calls": [{"index": 0, "id": "call_fd", "function": {"name": "fd_tool", "arguments": "{\"a\":1}"}}]}),
    ]
    finish = _cc({}, finish="tool_calls")
    sse_body = (_sse_stream_chunks(chunks) + b"z" * 90000 + b"\n\n"
                + _sse_stream_chunks([finish]) + b"data: [DONE]\n\n")
    responders = {"p": lambda info: (200, "text/event-stream", sse_body)}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(
        tiers, vendors, responders=responders)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        frames = _chat_sse_fetch_frames(proxy_port)
        if frames is None:
            return
        blocks = _sse_tool_use_blocks(frames)
        if len(blocks) != 1 or not blocks[0]["closed"]:
            fail("tool block emitted before the drop should close, got {!r}".format(blocks))
            return
        if blocks[0]["input"] != {"a": 1}:
            fail("tool input wrong after frame drop: {!r}".format(blocks[0]))
            return
        if _sse_stop_reason(frames) != "tool_use":
            fail("emitted block must claim tool_use despite the dropped frame, got {!r}".format(_sse_stop_reason(frames)))
            return
        events = _degraded_trace_events(trace_file)
        if len(events) != 1:
            fail("expected exactly one degradation event, got {}".format(len(events)))
            return
        if events[0].get("frame_dropped") != 1:
            fail("expected frame_dropped 1 in the trace event, got {!r}".format(events[0]))
            return
        if not _assert_degradation_metadata_only(events[0]):
            return
        blob = json.dumps(events[0])
        for marker in ["call_fd", "fd_tool"]:
            if marker in blob:
                fail("degradation event leaked tool marker {!r}: {}".format(marker, blob))
                return
        pass_("oversized no-delimiter frame mid-tool-stream: emitted block claims tool_use, frame_dropped 1")
    finally:
        cleanup()




def test_chat_mode_streamed_tool_command_e2e():
    """State-wide: a streamed Bash tool call becomes a runnable Anthropic tool_use turn."""
    print("\n--- Test: Chat Mode Streamed Tool Command E2E ---")
    chunks = [
        _cc({"role": "assistant"}),
        _cc({"tool_calls": [{"index": 0, "id": "call_123", "function": {"name": "Bash",
                                                                        "arguments": "{\"command\":\"ls -la\"}"}}]}),
        _cc({}, finish="tool_calls"),
    ]
    proxy_port, trace_file, cleanup = _start_chat_sse_proxy(chunks)
    if proxy_port is None:
        return
    try:
        body = {
            "model": "sonnet",
            "messages": [{"role": "user", "content": "list files"}],
            "tools": [{"name": "Bash", "description": "Run a bash command",
                       "input_schema": {"type": "object",
                                        "properties": {"command": {"type": "string"}}}}],
            "stream": True,
        }
        frames = _chat_sse_fetch_frames(proxy_port, body=body)
        if frames is None:
            return
        blocks = _sse_tool_use_blocks(frames)
        if len(blocks) != 1:
            fail("e2e streamed tool call should yield one tool_use block, got {!r}".format(blocks))
            return
        b = blocks[0]
        if b["id"] != "call_123" or b["name"] != "Bash" or b["input"] != {"command": "ls -la"} \
                or b["index"] != 0 or not b["closed"]:
            fail("e2e tool_use block mismatch: {!r}".format(b))
            return
        if _sse_stop_reason(frames) != "tool_use":
            fail("e2e stream should terminate with stop_reason tool_use, got {!r}".format(_sse_stop_reason(frames)))
            return
        if "message_stop" not in _sse_types(frames):
            fail("e2e stream missing message_stop")
            return
        pass_("streamed tool command e2e: runnable tool_use block + stop_reason tool_use")
    finally:
        cleanup()




def test_chat_sse_reasoning_delta_to_thinking_delta():
    """reasoning_content delta -> thinking block at index 0, then text block at index 1.

    The Anthropic client expects unique, increasing block indices across
    content_block_start / content_block_delta / content_block_stop events.
    """
    print("\n--- Test: Chat SSE Reasoning Delta To Thinking Delta ---")
    upstream_port = find_free_port()
    tiers = _mode_tiers()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port), "key": "K", "mode": "chat"}}
    chunks = [
        {"id": "c1", "object": "chat.completion.chunk", "created": 1, "model": "gpt-4o",
         "choices": [{"index": 0, "delta": {"role": "assistant", "reasoning_content": "Let me"},
                      "finish_reason": None}]},
        {"id": "c1", "object": "chat.completion.chunk", "created": 1, "model": "gpt-4o",
         "choices": [{"index": 0, "delta": {"reasoning_content": " think"}, "finish_reason": None}]},
        {"id": "c1", "object": "chat.completion.chunk", "created": 1, "model": "gpt-4o",
         "choices": [{"index": 0, "delta": {"content": "Hi"}, "finish_reason": None}]},
        {"id": "c1", "object": "chat.completion.chunk", "created": 1, "model": "gpt-4o",
         "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
    ]
    sse_body = _sse_stream_chunks(chunks) + b"data: [DONE]\n\n"
    responders = {"p": lambda info: (200, "text/event-stream", sse_body)}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(tiers, vendors, responders=responders)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        status, content_type, raw = _send_proxy_request_stream(
            proxy_port, body={"model": "sonnet", "messages": [{"role": "user", "content": "hi"}]})
        if status != 200:
            fail("expected 200, got {}".format(status))
            return
        frames = _parse_sse_frames(raw)
        starts = _sse_frames_with_type(frames, "content_block_start")
        deltas = _sse_frames_with_type(frames, "content_block_delta")
        stops = _sse_frames_with_type(frames, "content_block_stop")
        if len(starts) != 2:
            fail("expected 2 content_block_start events (thinking + text), got {}: {!r}".format(len(starts), starts))
            return
        if starts[0].get("index") != 0 or starts[0].get("content_block", {}).get("type") != "thinking":
            fail("first content_block_start should be thinking at index 0, got {!r}".format(starts[0]))
            return
        if starts[1].get("index") != 1 or starts[1].get("content_block", {}).get("type") != "text":
            fail("second content_block_start should be text at index 1, got {!r}".format(starts[1]))
            return
        thinking_deltas = [d for d in deltas if d.get("delta", {}).get("type") == "thinking_delta"]
        text_deltas = [d for d in deltas if d.get("delta", {}).get("type") == "text_delta"]
        if not thinking_deltas:
            fail("expected thinking_delta events, got {!r}".format(deltas))
            return
        for d in thinking_deltas:
            if d.get("index") != 0:
                fail("thinking_delta must use index 0, got {!r}".format(d))
                return
        if not text_deltas or text_deltas[0].get("index") != 1:
            fail("text_delta should use index 1, got {!r}".format(text_deltas))
            return
        joined_reasoning = "".join(d.get("delta", {}).get("thinking", "") for d in thinking_deltas)
        if "Let me think" != joined_reasoning:
            fail("reasoning text mismatch, joined={!r}".format(joined_reasoning))
            return
        if len(stops) != 2:
            fail("expected 2 content_block_stop events, got {}: {!r}".format(len(stops), stops))
            return
        indices = [s.get("index") for s in starts] + [d.get("index") for d in deltas] + [s.get("index") for s in stops]
        if len(set(indices)) != 2 or set(indices) != {0, 1}:
            fail("block indices should be exactly {{0, 1}}, got {!r}".format(indices))
            return
        pass_("reasoning delta -> thinking block index 0, text index 1, unique indices")
    finally:
        cleanup()




def test_chat_sse_reasoning_delta_no_content():
    """A stream with only reasoning deltas still emits valid thinking blocks and terminal events.

    One content_block_stop for the thinking block; the client never hangs.
    """
    print("\n--- Test: Chat SSE Reasoning Delta No Content ---")
    upstream_port = find_free_port()
    tiers = _mode_tiers()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port), "key": "K", "mode": "chat"}}
    chunks = [
        {"id": "c1", "object": "chat.completion.chunk", "created": 1, "model": "gpt-4o",
         "choices": [{"index": 0, "delta": {"role": "assistant", "reasoning_content": "r1"},
                      "finish_reason": None}]},
        {"id": "c1", "object": "chat.completion.chunk", "created": 1, "model": "gpt-4o",
         "choices": [{"index": 0, "delta": {"reasoning_content": "r2"}, "finish_reason": None}]},
        {"id": "c1", "object": "chat.completion.chunk", "created": 1, "model": "gpt-4o",
         "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
    ]
    sse_body = _sse_stream_chunks(chunks) + b"data: [DONE]\n\n"
    responders = {"p": lambda info: (200, "text/event-stream", sse_body)}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(tiers, vendors, responders=responders)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        status, content_type, raw = _send_proxy_request_stream(
            proxy_port, body={"model": "sonnet", "messages": [{"role": "user", "content": "hi"}]})
        if status != 200:
            fail("expected 200, got {}".format(status))
            return
        frames = _parse_sse_frames(raw)
        types = _sse_types(frames)
        starts = _sse_frames_with_type(frames, "content_block_start")
        stops = _sse_frames_with_type(frames, "content_block_stop")
        if len(starts) != 1 or starts[0].get("content_block", {}).get("type") != "thinking":
            fail("expected exactly one thinking content_block_start, got {!r}".format(starts))
            return
        if starts[0].get("index") != 0:
            fail("thinking block should be at index 0, got {!r}".format(starts[0]))
            return
        if len(stops) != 1 or stops[0].get("index") != 0:
            fail("expected one content_block_stop at index 0, got {!r}".format(stops))
            return
        missing = [t for t in ("content_block_start", "content_block_delta",
                               "content_block_stop", "message_delta", "message_stop") if t not in types]
        if missing:
            fail("missing terminal SSE events {}; got {}".format(missing, types))
            return
        deltas = _sse_frames_with_type(frames, "content_block_delta")
        if not all(d.get("delta", {}).get("type") == "thinking_delta" for d in deltas):
            fail("all deltas should be thinking_delta, got {!r}".format(deltas))
            return
        pass_("reasoning-only stream -> valid thinking block + terminal events")
    finally:
        cleanup()




def test_chat_sse_reasoning_then_text_transition():
    """thinking content_block_stop(index 0) precedes text content_block_start(index 1)."""
    print("\n--- Test: Chat SSE Reasoning Then Text Transition ---")
    upstream_port = find_free_port()
    tiers = _mode_tiers()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port), "key": "K", "mode": "chat"}}
    chunks = [
        {"id": "c1", "object": "chat.completion.chunk", "created": 1, "model": "gpt-4o",
         "choices": [{"index": 0, "delta": {"role": "assistant", "reasoning_content": "r"},
                      "finish_reason": None}]},
        {"id": "c1", "object": "chat.completion.chunk", "created": 1, "model": "gpt-4o",
         "choices": [{"index": 0, "delta": {"content": "text"}, "finish_reason": None}]},
        {"id": "c1", "object": "chat.completion.chunk", "created": 1, "model": "gpt-4o",
         "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
    ]
    sse_body = _sse_stream_chunks(chunks) + b"data: [DONE]\n\n"
    responders = {"p": lambda info: (200, "text/event-stream", sse_body)}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(tiers, vendors, responders=responders)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        status, content_type, raw = _send_proxy_request_stream(
            proxy_port, body={"model": "sonnet", "messages": [{"role": "user", "content": "hi"}]})
        if status != 200:
            fail("expected 200, got {}".format(status))
            return
        frames = _parse_sse_frames(raw)
        starts = _sse_frames_with_type(frames, "content_block_start")
        stops = _sse_frames_with_type(frames, "content_block_stop")
        if len(starts) != 2 or len(stops) != 2:
            fail("expected 2 starts and 2 stops, got starts={!r} stops={!r}".format(starts, stops))
            return
        thinking_stop = stops[0]
        text_start = starts[1]
        if thinking_stop.get("index") != 0:
            fail("thinking stop should be at index 0, got {!r}".format(thinking_stop))
            return
        if text_start.get("index") != 1 or text_start.get("content_block", {}).get("type") != "text":
            fail("text start should be at index 1, got {!r}".format(text_start))
            return
        stop_pos = next(i for i, f in enumerate(frames) if _sse_frame_type(f) == "content_block_stop" and isinstance(f[1], dict) and f[1].get("index") == 0)
        start_pos = next(i for i, f in enumerate(frames) if _sse_frame_type(f) == "content_block_start" and isinstance(f[1], dict) and f[1].get("index") == 1)
        if not (stop_pos < start_pos):
            fail("thinking stop (pos {}) must precede text start (pos {})".format(stop_pos, start_pos))
            return
        pass_("thinking stop(index 0) precedes text start(index 1)")
    finally:
        cleanup()


def test_chat_sse_usage_after_finish_reason():
    """The usage chunk that follows finish_reason is read during the drain and
    reported on message_delta, instead of being dropped for a zero-filled one."""
    print("\n--- Test: Chat SSE Usage After Finish Reason ---")
    chunks = [
        _cc({"role": "assistant", "content": "hi"}),
        _cc({}, finish="stop"),
        # OpenAI's documented ordering: include_usage puts this AFTER finish.
        {"id": "c1", "object": "chat.completion.chunk", "created": 1,
         "model": "gpt-4o", "choices": [],
         "usage": {"prompt_tokens": 111, "completion_tokens": 222}},
    ]
    proxy_port, trace_file, cleanup = _start_chat_sse_proxy(chunks)
    if proxy_port is None:
        return
    try:
        frames = _chat_sse_fetch_frames(proxy_port)
        if frames is None:
            return
        if _sse_stop_reason(frames) != "end_turn":
            fail("stop finish should still map to end_turn, got {!r}".format(_sse_stop_reason(frames)))
            return
        usage = _message_delta_usage(frames)
        if not usage:
            fail("no usage on message_delta")
            return
        if usage.get("input_tokens") != 111 or usage.get("output_tokens") != 222:
            fail("trailing usage not reported on message_delta; got {!r} "
                 "(expected input_tokens=111, output_tokens=222)".format(usage))
            return
        pass_("trailing usage chunk read during drain -> message_delta usage")
    finally:
        cleanup()




def test_chat_sse_tool_calls_after_finish_reason():
    """A provider that sends finish_reason before its tool_call frames: the drain
    captures them and the stream ends tool_use, not end_turn."""
    print("\n--- Test: Chat SSE Tool Calls After Finish Reason ---")
    chunks = [
        _cc({"role": "assistant"}),
        _cc({}, finish="stop"),
        _cc({"tool_calls": [{"index": 0, "id": "call_1",
                             "function": {"name": "get_weather",
                                          "arguments": "{\"city\":\"NY\"}"}}]}),
    ]
    proxy_port, trace_file, cleanup = _start_chat_sse_proxy(chunks)
    if proxy_port is None:
        return
    try:
        frames = _chat_sse_fetch_frames(proxy_port)
        if frames is None:
            return
        blocks = _sse_tool_use_blocks(frames)
        if len(blocks) != 1:
            fail("tool_call arriving after finish_reason must be captured, got {!r}".format(blocks))
            return
        if blocks[0]["name"] != "get_weather" or blocks[0]["input"] != {"city": "NY"}:
            fail("drained tool block wrong: {!r}".format(blocks[0]))
            return
        if not blocks[0]["closed"]:
            fail("drained tool block must be closed by the terminal sequence, got {!r}".format(blocks[0]))
            return
        if _sse_stop_reason(frames) != "tool_use":
            fail("drained tool call must upgrade stop to tool_use, got {!r}".format(_sse_stop_reason(frames)))
            return
        types = _sse_types(frames)
        if types.count("message_delta") != 1 or types.count("message_stop") != 1:
            fail("expected exactly one terminal sequence, got {}".format(types))
            return
        pass_("tool_calls after finish_reason captured; stop_reason tool_use")
    finally:
        cleanup()




def test_chat_sse_usage_and_tool_calls_after_finish_reason():
    """Both trailing frame classes are captured in one drain: the tool call
    drives stop_reason, the usage chunk drives message_delta usage."""
    print("\n--- Test: Chat SSE Usage And Tool Calls After Finish Reason ---")
    chunks = [
        _cc({"role": "assistant"}),
        _cc({}, finish="stop"),
        _cc({"tool_calls": [{"index": 0, "id": "call_9",
                             "function": {"name": "ls", "arguments": "{\"p\":\"/tmp\"}"}}]}),
        {"id": "c1", "object": "chat.completion.chunk", "created": 1,
         "model": "gpt-4o", "choices": [],
         "usage": {"prompt_tokens": 7, "completion_tokens": 9}},
    ]
    proxy_port, trace_file, cleanup = _start_chat_sse_proxy(chunks)
    if proxy_port is None:
        return
    try:
        frames = _chat_sse_fetch_frames(proxy_port)
        if frames is None:
            return
        blocks = _sse_tool_use_blocks(frames)
        if len(blocks) != 1 or blocks[0]["input"] != {"p": "/tmp"}:
            fail("tool call after finish must survive alongside usage, got {!r}".format(blocks))
            return
        if _sse_stop_reason(frames) != "tool_use":
            fail("stop_reason should be tool_use, got {!r}".format(_sse_stop_reason(frames)))
            return
        usage = _message_delta_usage(frames)
        if not usage or usage.get("input_tokens") != 7 or usage.get("output_tokens") != 9:
            fail("trailing usage not reported when tool calls are also drained; got {!r}".format(usage))
            return
        pass_("drain captures both trailing tool_calls and usage")
    finally:
        cleanup()




def test_chat_sse_finish_reason_last_chunk_no_drain():
    """A stream whose finish_reason is genuinely last is unchanged: one terminal
    sequence with the mapped stop reason and no extra frames."""
    print("\n--- Test: Chat SSE Finish Reason Last Chunk No Drain ---")
    chunks = [
        _cc({"role": "assistant", "content": "Hel"}),
        _cc({"content": "lo"}),
        _cc({}, finish="stop"),
    ]
    proxy_port, trace_file, cleanup = _start_chat_sse_proxy(chunks)
    if proxy_port is None:
        return
    try:
        frames = _chat_sse_fetch_frames(proxy_port)
        if frames is None:
            return
        types = _sse_types(frames)
        required = ("message_start", "content_block_start", "content_block_delta",
                    "content_block_stop", "message_delta", "message_stop")
        missing = [t for t in required if t not in types]
        if missing:
            fail("missing SSE events {}; got {}".format(missing, types))
            return
        if _sse_stop_reason(frames) != "end_turn":
            fail("final stop chunk should still map to end_turn, got {!r}".format(_sse_stop_reason(frames)))
            return
        starts = _sse_content_block_starts(frames)
        if len(starts) != 1:
            fail("no-drain stream must emit exactly one content block, got {!r}".format(starts))
            return
        if types.count("message_delta") != 1 or types.count("message_stop") != 1:
            fail("expected exactly one terminal sequence, got {}".format(types))
            return
        deltas = _sse_frames_with_type(frames, "content_block_delta")
        texts = [d["delta"].get("text") for d in deltas if isinstance(d.get("delta"), dict)]
        if texts != ["Hel", "lo"]:
            fail("text deltas should be unchanged, got {!r}".format(texts))
            return
        pass_("finish_reason as last chunk: behavior unchanged")
    finally:
        cleanup()




def test_chat_sse_truncation_still_works():
    """EOF with no finish_reason still takes the truncation path — but its
    disposition changed (2026-10-04): chat_sse_truncated fires with
    saw_done: 0 and the stream closes with a retryable SSE error event, not a
    synthesized terminal. No chat_sse_drain event accompanies it: the drain
    only runs for streams that reached a finish_reason.
    """
    print("\n--- Test: Chat SSE Truncation Still Works ---")
    chunks = [_cc({"role": "assistant", "content": "half a th"})]
    upstream_port = find_free_port()
    tiers = _mode_tiers()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port), "key": "K", "mode": "chat"}}
    sse_body = _sse_stream_chunks(chunks)  # no finish_reason, no [DONE]
    responders = {"p": lambda info: (200, "text/event-stream", sse_body)}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(tiers, vendors, responders=responders)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        frames = _chat_sse_fetch_frames(proxy_port)
        if frames is None:
            return
        types = _sse_types(frames)
        if "content_block_stop" not in types:
            fail("truncation must still close open blocks; missing content_block_stop in {}".format(types))
            return
        present = [t for t in ("message_delta", "message_stop") if t in types]
        if present:
            fail("truncation must not synthesize {}; got {}".format(present, types))
            return
        errs = _sse_frames_with_type(frames, "error")
        if len(errs) != 1:
            fail("truncation must close with exactly one error frame, got {} ({})".format(len(errs), types))
            return
        if (errs[0].get("error") or {}).get("type") != "api_error":
            fail("truncation error must be api_error (retryable), got {!r}".format(errs[0].get("error")))
            return
        events = _trace_events_named(trace_file, "chat_sse_truncated")
        if len(events) != 1:
            fail("expected exactly one chat_sse_truncated event, got {}".format(len(events)))
            return
        if events[0].get("saw_done") != 0:
            fail("chat_sse_truncated must record saw_done: 0 on a cut stream, got {!r}".format(events[0].get("saw_done")))
            return
        if _trace_events_named(trace_file, "chat_sse_drain"):
            fail("a cut stream never reaches the drain; no chat_sse_drain expected")
            return
        suppressed = _trace_events_named(trace_file, "chat_sse_post_finish_suppressed")
        if suppressed:
            fail("a never-finished stream must not report post-finish suppression")
            return
        pass_("truncation path: chat_sse_truncated (saw_done 0) + api_error close, no chat_sse_drain")
    finally:
        cleanup()




def test_chat_sse_truncation_with_tool_block_emits_error_event():
    """A cut stream (no finish_reason, no [DONE]) that had opened a tool block
    closes the block first, then terminates with a retryable api_error — and
    never a message_delta/message_stop.

    Not a duplicate of test_chat_sse_tool_call_eof_without_finish case (a):
    that fixture carries [DONE] and takes the protocol-complete branch, so the
    cut-with-tool-block shape is otherwise uncovered.
    """
    print("\n--- Test: Chat SSE Truncation With Tool Block Emits Error Event ---")
    chunks = [
        _cc({"role": "assistant"}),
        _cc({"tool_calls": [{"index": 0, "id": "call_cut",
                             "function": {"name": "cut_tool", "arguments": "{\"a\":1}"}}]}),
    ]
    proxy_port, trace_file, cleanup = _start_chat_sse_proxy(chunks, add_done=False)
    if proxy_port is None:
        return
    try:
        frames = _chat_sse_fetch_frames(proxy_port)
        if frames is None:
            return
        blocks = _sse_tool_use_blocks(frames)
        if len(blocks) != 1 or not blocks[0]["closed"]:
            fail("the emitted tool block must be closed before the error frame, got {!r}".format(blocks))
            return
        if blocks[0]["input"] != {"a": 1}:
            fail("tool block input wrong: {!r}".format(blocks[0]))
            return
        types = _sse_types(frames)
        present = [t for t in ("message_delta", "message_stop") if t in types]
        if present:
            fail("cut stream with a tool block must not synthesize {}; got {}".format(present, types))
            return
        errs = _sse_frames_with_type(frames, "error")
        if len(errs) != 1:
            fail("cut stream with a tool block must close with exactly one error frame, got {} ({})".format(len(errs), types))
            return
        if (errs[0].get("error") or {}).get("type") != "api_error":
            fail("error frame must be api_error (retryable), got {!r}".format(errs[0].get("error")))
            return
        if types.index("content_block_stop") > types.index("error"):
            fail("content_block_stop must precede the error frame; got {}".format(types))
            return
        events = _trace_events_named(trace_file, "chat_sse_truncated")
        if len(events) != 1 or events[0].get("saw_done") != 0:
            fail("expected one chat_sse_truncated with saw_done 0, got {!r}".format(events))
            return
        pass_("cut stream with tool block: block closed, api_error closes, no terminal")
    finally:
        cleanup()




def test_chat_sse_tool_degradation_on_cut_stream():
    """A cut stream whose only defect is a tracked-but-unstarted tool call
    still fires the coalesced degradation event.

    The unstarted-tool counting loop lives in log_degradation_if_needed() rather
    than terminal(), precisely so that the cut path — which no longer calls
    terminal() — finalizes identically. Every [DONE]-bearing fixture reaches
    that loop through terminal() and would stay green if the loop were moved
    back; only a cut fixture pins the refactor.

    No polling here, unlike the _wait_for_trace_events tests: both trace writes
    precede the client-visible error frame (log_degradation_if_needed runs
    before chat_sse_truncated's block and before the error write on the cut
    path), so reading the client stream to EOF via _chat_sse_fetch_frames
    cannot outrun them. Do not "fix" this into a poll.
    """
    print("\n--- Test: Chat SSE Tool Degradation On Cut Stream ---")
    chunks = [
        _cc({"role": "assistant"}),
        _cc({"tool_calls": [{"index": 0, "id": "call_incomplete"}]}),
    ]
    proxy_port, trace_file, cleanup = _start_chat_sse_proxy(chunks, add_done=False)
    if proxy_port is None:
        return
    try:
        frames = _chat_sse_fetch_frames(proxy_port)
        if frames is None:
            return
        events = _degraded_trace_events(trace_file)
        if len(events) != 1:
            fail("cut stream with an unstarted tool must fire exactly one degradation "
                 "event (the counting loop now lives in log_degradation_if_needed), "
                 "got {}".format(len(events)))
            return
        if _sse_content_block_starts(frames):
            fail("an id with no function.name must never open a tool block on the "
                 "cut path, got {!r}".format(_sse_content_block_starts(frames)))
            return
        types = _sse_types(frames)
        present = [t for t in ("message_delta", "message_stop") if t in types]
        if present:
            fail("cut stream must not synthesize {}; got {}".format(present, types))
            return
        errs = _sse_frames_with_type(frames, "error")
        if len(errs) != 1:
            fail("cut stream must close with exactly one error frame, got {} ({})".format(
                len(errs), types))
            return
        if (errs[0].get("error") or {}).get("type") != "api_error":
            fail("error frame must be api_error (retryable), got {!r}".format(errs[0].get("error")))
            return
        trunc = _trace_events_named(trace_file, "chat_sse_truncated")
        if len(trunc) != 1 or trunc[0].get("saw_done") != 0:
            fail("expected one chat_sse_truncated with saw_done 0, got {!r}".format(trunc))
            return
        pass_("cut stream with unstarted tool: degradation event fires, no tool_use, "
              "api_error closes, saw_done 0")
    finally:
        cleanup()




def test_chat_sse_drain_time_deadline():
    """A provider that sends finish_reason and then goes silent must not hold the
    request open past the drain bound."""
    print("\n--- Test: Chat SSE Drain Time Deadline ---")
    pre = _sse_stream_chunks([_cc({"role": "assistant", "content": "hi"}),
                              _cc({}, finish="stop")])
    proxy_port, trace_file, cleanup = _start_hanging_chat_proxy(
        pre, DRAIN_BOUND_TEST_SECONDS * 3)
    if proxy_port is None:
        return
    try:
        raw, saw_stop, elapsed = _read_sse_until_stop(proxy_port, DRAIN_BOUND_TEST_SECONDS)
        if not saw_stop:
            fail("silent provider after finish_reason: no message_stop within {}s "
                 "(got {} bytes)".format(DRAIN_BOUND_TEST_SECONDS, len(raw)))
            return
        if elapsed > DRAIN_BOUND_TEST_SECONDS:
            fail("drain took {:.1f}s, exceeding the {}s bound".format(elapsed, DRAIN_BOUND_TEST_SECONDS))
            return
        frames = _parse_sse_frames(raw)
        if _sse_stop_reason(frames) != "end_turn":
            fail("drain must still emit the mapped stop reason, got {!r}".format(_sse_stop_reason(frames)))
            return
        # The fixture goes silent after finish_reason, so the drain exits on
        # the socket timeout (the except socket.timeout clause). If that clause
        # were dead code — e.g. ordered after the OSError tuple, which
        # socket.timeout subclasses — this would report "read_error".
        # Poll: _read_sse_until_stop returns at message_stop, which the proxy
        # writes before it logs the drain event, so an immediate read races
        # the sink write.
        drain_events = _wait_for_trace_events(trace_file, "chat_sse_drain")
        if len(drain_events) != 1:
            fail("expected exactly one chat_sse_drain event, got {}".format(len(drain_events)))
            return
        if drain_events[0].get("drain_exit") != "time_budget":
            fail("silent provider must exit the drain on its own deadline "
                 "(socket.timeout -> time_budget), got {!r}".format(drain_events[0].get("drain_exit")))
            return
        pass_("silent provider: drain bounded, terminal emitted in {:.1f}s".format(elapsed))
    finally:
        cleanup()




def test_chat_sse_done_terminates_drain():
    """[DONE] ends the drain promptly even when the provider keeps the socket open,
    so the client is not made to wait out the full bound."""
    print("\n--- Test: Chat SSE Done Terminates Drain ---")
    pre = _sse_stream_chunks([_cc({"role": "assistant", "content": "hi"}),
                              _cc({}, finish="stop"),
                              {"id": "c1", "object": "chat.completion.chunk",
                               "created": 1, "model": "gpt-4o", "choices": [],
                               "usage": {"prompt_tokens": 3, "completion_tokens": 4}}])
    pre += b"data: [DONE]\n\n"
    proxy_port, trace_file, cleanup = _start_hanging_chat_proxy(
        pre, DRAIN_BOUND_TEST_SECONDS * 3)
    if proxy_port is None:
        return
    try:
        raw, saw_stop, elapsed = _read_sse_until_stop(proxy_port, DRAIN_BOUND_TEST_SECONDS)
        if not saw_stop:
            fail("no message_stop within {}s after [DONE]".format(DRAIN_BOUND_TEST_SECONDS))
            return
        frames = _parse_sse_frames(raw)
        usage = _message_delta_usage(frames)
        if not usage or usage.get("output_tokens") != 4:
            fail("usage frame before [DONE] must be captured, got {!r}".format(usage))
            return
        if b"[DONE]" in raw:
            fail("[DONE] sentinel leaked into client stream")
            return
        if elapsed > DRAIN_BOUND_TEST_SECONDS:
            fail("[DONE] should end the drain promptly, took {:.1f}s".format(elapsed))
            return
        pass_("[DONE] terminates drain in {:.1f}s with usage captured".format(elapsed))
    finally:
        cleanup()




def test_chat_sse_text_after_finish_suppressed():
    """Text and reasoning deltas arriving after finish_reason are dropped by
    policy — terminal() runs after the drain, so nothing is closed while it
    runs — and counted in the trace."""
    print("\n--- Test: Chat SSE Text After Finish Suppressed ---")
    chunks = [
        _cc({"role": "assistant", "content": "keep"}),
        _cc({}, finish="stop"),
        _cc({"content": "trailing text that must not reach the client"}),
        _cc({"reasoning_content": "late thought"}),
    ]
    proxy_port, trace_file, cleanup = _start_chat_sse_proxy(chunks)
    if proxy_port is None:
        return
    try:
        frames = _chat_sse_fetch_frames(proxy_port)
        if frames is None:
            return
        deltas = _sse_frames_with_type(frames, "content_block_delta")
        texts = [d["delta"].get("text") for d in deltas
                 if isinstance(d.get("delta"), dict) and d["delta"].get("type") == "text_delta"]
        thinking = [d["delta"].get("thinking") for d in deltas
                    if isinstance(d.get("delta"), dict) and d["delta"].get("type") == "thinking_delta"]
        if texts != ["keep"]:
            fail("only pre-finish text may be emitted, got {!r}".format(texts))
            return
        if thinking:
            fail("late reasoning must be suppressed, got {!r}".format(thinking))
            return
        if len(_sse_content_block_starts(frames)) != 1:
            fail("suppressed deltas must not open new blocks, got {!r}".format(_sse_content_block_starts(frames)))
            return
        # Order guard: every content_block_delta must precede its block's stop.
        types = _sse_types(frames)
        if types.index("content_block_delta") > types.index("content_block_stop"):
            fail("no delta may follow content_block_stop; got {}".format(types))
            return
        events = _trace_events_named(trace_file, "chat_sse_post_finish_suppressed")
        if len(events) != 1:
            fail("expected exactly one chat_sse_post_finish_suppressed event, got {}".format(len(events)))
            return
        if events[0].get("count") != 2:
            fail("both suppressed deltas should be counted, got {!r}".format(events[0].get("count")))
            return
        pass_("post-finish text/reasoning suppressed and counted")
    finally:
        cleanup()




def test_chat_sse_stream_options_include_usage():
    """A streaming chat-mode request asks the provider for the trailing usage
    frame; a non-streaming request must not carry stream_options at all."""
    print("\n--- Test: Chat SSE Stream Options Include Usage ---")
    upstream_port = find_free_port()
    tiers = _mode_tiers()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port), "key": "K", "mode": "chat"}}
    sse_body = _sse_stream_chunks([_cc({"role": "assistant", "content": "hi"}),
                                   _cc({}, finish="stop")]) + b"data: [DONE]\n\n"
    responders = {"p": lambda info: (200, "text/event-stream", sse_body)}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(tiers, vendors, responders=responders)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        status, content_type, raw = _send_proxy_request_stream(
            proxy_port, body={"model": "sonnet", "messages": [{"role": "user", "content": "hi"}],
                              "stream": True})
        if status != 200:
            fail("expected 200, got {}".format(status))
            return
        reqs = mock_servers["p"]["requests"]
        if not reqs:
            fail("upstream received no request")
            return
        try:
            sent = json.loads(reqs[0]["body"])
        except Exception as e:
            fail("upstream body not JSON: {}".format(e))
            return
        so = sent.get("stream_options")
        if so != {"include_usage": True}:
            fail("streaming chat request must send stream_options include_usage, got {!r}".format(so))
            return

        # Non-streaming: OpenAI rejects stream_options on a buffered request.
        status2, content_type2, raw2 = _send_proxy_request_stream(
            proxy_port, body={"model": "sonnet", "messages": [{"role": "user", "content": "hi"}]})
        if status2 != 200:
            fail("non-streaming request expected 200, got {}".format(status2))
            return
        reqs2 = mock_servers["p"]["requests"]
        if len(reqs2) < 2:
            fail("expected a second upstream request, got {}".format(len(reqs2)))
            return
        try:
            sent2 = json.loads(reqs2[1]["body"])
        except Exception as e:
            fail("non-streaming upstream body not JSON: {}".format(e))
            return
        if sent2.get("stream") is True:
            fail("second request should not be streaming: {!r}".format(sent2.get("stream")))
            return
        if "stream_options" in sent2:
            fail("non-streaming chat request must omit stream_options, got {!r}".format(sent2["stream_options"]))
            return
        pass_("streaming request sends include_usage; non-streaming omits stream_options")
    finally:
        cleanup()




def test_chat_sse_drain_byte_budget():
    """A drain cut by MAX_DRAIN_BYTES mid-tool-call still claims tool_use.

    The provider sends finish_reason, then a tool frame that opens the block,
    then argument fragments that push the drain past the 64 KB budget with no
    [DONE]. The budget is checked per chunk, so the crossing chunk is discarded
    unparsed and the argument stream ends mid-fragment. Resolved Decision D4:
    the partially filled block still closes and the stop reason is tool_use (the
    client can surface the parse failure), never null.
    """
    print("\n--- Test: Chat SSE Drain Byte Budget ---")
    tail = [_cc({"tool_calls": [{"index": 0, "id": "call_big",
                                 "function": {"name": "big_tool", "arguments": ""}}]})]
    # ~24 frames x 4000 argument bytes = ~96 KB, comfortably past MAX_DRAIN_BYTES.
    for _ in range(24):
        tail.append(_cc({"tool_calls": [{"index": 0, "function": {"arguments": "x" * 4000}}]}))
    chunks = [_cc({"role": "assistant", "content": "hi"}),
              _cc({}, finish="stop")] + tail
    proxy_port, trace_file, cleanup = _start_chat_sse_proxy(chunks, add_done=False)
    if proxy_port is None:
        return
    try:
        frames = _chat_sse_fetch_frames(proxy_port)
        if frames is None:
            return
        types = _sse_types(frames)
        if types.count("message_delta") != 1 or types.count("message_stop") != 1:
            fail("expected exactly one terminal sequence, got {}".format(types))
            return
        blocks = _sse_tool_use_blocks(frames)
        if len(blocks) != 1 or not blocks[0]["closed"]:
            fail("the opened tool block must survive the budget cut and close, got {!r}".format(blocks))
            return
        if blocks[0]["name"] != "big_tool":
            fail("drained tool block wrong: {!r}".format(blocks[0]))
            return
        if not isinstance(blocks[0]["input"], str):
            fail("the budget is checked per chunk, so the argument stream must be "
                 "cut mid-fragment and stay unparseable; got {!r}".format(blocks[0]["input"]))
            return
        if _sse_stop_reason(frames) != "tool_use":
            fail("byte-budget cut mid-tool-call must still claim tool_use (D4), "
                 "got {!r}".format(_sse_stop_reason(frames)))
            return
        drain_events = _trace_events_named(trace_file, "chat_sse_drain")
        if len(drain_events) != 1:
            fail("expected exactly one chat_sse_drain event, got {}".format(len(drain_events)))
            return
        if drain_events[0].get("drain_exit") != "byte_budget":
            fail("a drain cut by MAX_DRAIN_BYTES must report drain_exit "
                 "\"byte_budget\", got {!r}".format(drain_events[0].get("drain_exit")))
            return
        pass_("drain cut at MAX_DRAIN_BYTES: partial tool block closes, stop_reason tool_use")
    finally:
        cleanup()




def test_chat_sse_drain_event_on_done():
    """A normal stream (finish_reason then [DONE]) logs exactly one
    chat_sse_drain event describing the drain: the finish_reason, why it ended
    (drain_exit "done"), byte/time counters, tool flags, and tools_declared 0
    for a request that declared no tools."""
    print("\n--- Test: Chat SSE Drain Event On Done ---")
    chunks = [_cc({"role": "assistant", "content": "hi"}),
              _cc({}, finish="stop")]
    proxy_port, trace_file, cleanup = _start_chat_sse_proxy(chunks)  # appends [DONE]
    if proxy_port is None:
        return
    try:
        frames = _chat_sse_fetch_frames(proxy_port)
        if frames is None:
            return
        if _sse_stop_reason(frames) != "end_turn":
            fail("normal stop stream must map to end_turn, got {!r}".format(_sse_stop_reason(frames)))
            return
        events = _trace_events_named(trace_file, "chat_sse_drain")
        if len(events) != 1:
            fail("expected exactly one chat_sse_drain event, got {}".format(len(events)))
            return
        ev = events[0]
        if ev.get("finish_reason") != "stop":
            fail("chat_sse_drain.finish_reason must be the upstream value, got {!r}".format(ev.get("finish_reason")))
            return
        if ev.get("drain_exit") != "done":
            fail("drain ended by [DONE] must report drain_exit \"done\", got {!r}".format(ev.get("drain_exit")))
            return
        for field in ("drain_bytes", "drain_ms"):
            v = ev.get(field)
            if not isinstance(v, int) or v < 0:
                fail("chat_sse_drain.{} must be a non-negative int, got {!r}".format(field, v))
                return
        if ev.get("tool_calls_seen") != 0 or ev.get("emitted_tool_use") != 0:
            fail("tool flags must be 0 on a text-only stream, got {!r}/{!r}".format(
                ev.get("tool_calls_seen"), ev.get("emitted_tool_use")))
            return
        if ev.get("tools_declared") != 0:
            fail("a request with no tools must log tools_declared 0, got {!r}".format(ev.get("tools_declared")))
            return
        pass_("chat_sse_drain on [DONE]: finish_reason stop, drain_exit done, tools_declared 0")
    finally:
        cleanup()




def test_chat_sse_drain_event_trailing_tool_calls():
    """A stream whose finish_reason precedes its tool_call frames reports
    tool_calls_seen 1 and emitted_tool_use 1 on chat_sse_drain — the evidence
    channel that turns a missing trailing tool call from an inference into a
    readable field."""
    print("\n--- Test: Chat SSE Drain Event Trailing Tool Calls ---")
    chunks = [
        _cc({"role": "assistant"}),
        _cc({}, finish="stop"),
        _cc({"tool_calls": [{"index": 0, "id": "call_late",
                             "function": {"name": "late_tool", "arguments": "{\"k\":1}"}}]}),
    ]
    proxy_port, trace_file, cleanup = _start_chat_sse_proxy(chunks)  # appends [DONE]
    if proxy_port is None:
        return
    try:
        frames = _chat_sse_fetch_frames(proxy_port)
        if frames is None:
            return
        if _sse_stop_reason(frames) != "tool_use":
            fail("trailing tool call must upgrade the stop to tool_use, got {!r}".format(_sse_stop_reason(frames)))
            return
        events = _trace_events_named(trace_file, "chat_sse_drain")
        if len(events) != 1:
            fail("expected exactly one chat_sse_drain event, got {}".format(len(events)))
            return
        ev = events[0]
        if ev.get("tool_calls_seen") != 1:
            fail("chat_sse_drain.tool_calls_seen must be 1, got {!r}".format(ev.get("tool_calls_seen")))
            return
        if ev.get("emitted_tool_use") != 1:
            fail("chat_sse_drain.emitted_tool_use must be 1, got {!r}".format(ev.get("emitted_tool_use")))
            return
        pass_("chat_sse_drain: tool_calls_seen 1, emitted_tool_use 1 on trailing tool frames")
    finally:
        cleanup()




def test_chat_sse_drain_event_eof_exit():
    """A drain that runs to upstream EOF (finish_reason arrived, connection
    closed, no [DONE]) reports drain_exit "eof" on chat_sse_drain.

    The guidance for this plan asked for this assertion inside the migrated
    truncation test, but a cut stream never reaches the drain and logs no
    chat_sse_drain at all — the field is only observable on a finish-bearing
    stream, which is this fixture."""
    print("\n--- Test: Chat SSE Drain Event EOF Exit ---")
    chunks = [_cc({"role": "assistant", "content": "hi"}),
              _cc({}, finish="stop")]
    proxy_port, trace_file, cleanup = _start_chat_sse_proxy(chunks, add_done=False)
    if proxy_port is None:
        return
    try:
        frames = _chat_sse_fetch_frames(proxy_port)
        if frames is None:
            return
        if _sse_stop_reason(frames) != "end_turn":
            fail("eof-drained stop stream must map to end_turn, got {!r}".format(_sse_stop_reason(frames)))
            return
        events = _trace_events_named(trace_file, "chat_sse_drain")
        if len(events) != 1:
            fail("expected exactly one chat_sse_drain event, got {}".format(len(events)))
            return
        if events[0].get("drain_exit") != "eof":
            fail("a drain that ends at upstream EOF must report drain_exit \"eof\", "
                 "got {!r}".format(events[0].get("drain_exit")))
            return
        pass_("chat_sse_drain: drain_exit eof on a finish stream without [DONE]")
    finally:
        cleanup()




def test_chat_sse_unfinished_turn_shadow_logged():
    """The unfinished-turn detector fires in shadow mode: a tools-declaring
    request whose prose ends in ':' after finish_reason "stop", with no tool
    block, logs exactly one chat_sse_unfinished_turn — and changes nothing
    about the response. The same stream without tools logs none (tools_declared
    gate), and the chat_sse_drain event carries tools_declared 1/0 to match."""
    print("\n--- Test: Chat SSE Unfinished Turn Shadow Logged ---")
    chunks = [_cc({"role": "assistant", "content": "Running the check: "}),
              _cc({}, finish="stop")]
    proxy_port, trace_file, cleanup = _start_chat_sse_proxy(chunks)  # appends [DONE]
    if proxy_port is None:
        return
    try:
        tool = {"name": "lookup", "description": "look things up",
                "input_schema": {"type": "object", "properties": {}}}
        body_with_tools = {"model": "sonnet",
                           "messages": [{"role": "user", "content": "go"}],
                           "stream": True, "tools": [tool]}
        frames = _chat_sse_fetch_frames(proxy_port, body=body_with_tools)
        if frames is None:
            return
        # Shadow mode must be structurally incapable of acting: the terminal
        # sequence is exactly what the detector-less path emits.
        types = _sse_types(frames)
        missing = [t for t in ("message_delta", "message_stop") if t not in types]
        if missing:
            fail("the detector must not alter the response; missing {} ({})".format(missing, types))
            return
        if _sse_frames_with_type(frames, "error"):
            fail("the detector must not emit an error frame, got {!r}".format(_sse_frames_with_type(frames, "error")))
            return
        if _sse_stop_reason(frames) != "end_turn":
            fail("detector stream must still stop with end_turn, got {!r}".format(_sse_stop_reason(frames)))
            return
        events = _trace_events_named(trace_file, "chat_sse_unfinished_turn")
        if len(events) != 1:
            fail("expected exactly one chat_sse_unfinished_turn event, got {}".format(len(events)))
            return
        ev = events[0]
        if ev.get("rule") != "colon_after_prose":
            fail("unfinished-turn rule must be colon_after_prose, got {!r}".format(ev.get("rule")))
            return
        if ev.get("finish_reason") != "stop":
            fail("unfinished-turn finish_reason must be stop, got {!r}".format(ev.get("finish_reason")))
            return
        if ev.get("tools_declared") != 1:
            fail("tools-declaring request must log tools_declared 1, got {!r}".format(ev.get("tools_declared")))
            return
        if ev.get("tool_calls_seen") != 0 or ev.get("emitted_tool_use") != 0:
            fail("detector predicates on no tool frames: got tool_calls_seen {!r}, "
                 "emitted_tool_use {!r}".format(ev.get("tool_calls_seen"), ev.get("emitted_tool_use")))
            return
        if not isinstance(ev.get("text_tail_len"), int) or ev.get("text_tail_len") <= 0:
            fail("text_tail_len must be a positive int (the tail itself is never logged), "
                 "got {!r}".format(ev.get("text_tail_len")))
            return
        if "provider" not in ev or "key" not in ev:
            fail("unfinished-turn event must carry provider and key, got keys {}".format(sorted(ev)))
            return
        drain_events = _trace_events_named(trace_file, "chat_sse_drain")
        if len(drain_events) != 1 or drain_events[0].get("tools_declared") != 1:
            fail("chat_sse_drain must carry tools_declared 1 for this request, got {!r}".format(drain_events))
            return
        # Negative: the same upstream stream on a request with no tools must
        # not fire the detector (tools_declared gate), and logs tools_declared 0.
        body_no_tools = {"model": "sonnet",
                         "messages": [{"role": "user", "content": "go"}],
                         "stream": True}
        frames2 = _chat_sse_fetch_frames(proxy_port, body=body_no_tools)
        if frames2 is None:
            return
        events2 = _trace_events_named(trace_file, "chat_sse_unfinished_turn")
        if len(events2) != 1:
            fail("a request without tools must not fire the detector; got {} events".format(len(events2)))
            return
        drain_events2 = _trace_events_named(trace_file, "chat_sse_drain")
        if len(drain_events2) != 2 or drain_events2[1].get("tools_declared") != 0:
            fail("chat_sse_drain must carry tools_declared 0 on the no-tools request, "
                 "got {!r}".format(drain_events2))
            return
        pass_("shadow detector: fires once with tools (response unchanged), silent without")
    finally:
        cleanup()




def test_chat_sse_drain_late_tool_call_time_budget():
    """A tool call that arrives after finish_reason on a drain that ends by
    the time budget reports a non-null late_tool_call_ms — the arrival latency
    of a tool call the drain would otherwise have lost, and the number that
    answers whether the 5 s budget is generous or binding.

    Uses a two-phase hanging upstream: the finish stream lands first, the tool
    frame 0.3 s later (a distinct read chunk, so it counts as late), then the
    socket goes silent until the drain's socket timeout fires — the same
    except-socket.timeout exit test_chat_sse_drain_time_deadline pins."""
    print("\n--- Test: Chat SSE Drain Late Tool Call Time Budget ---")
    pre = _sse_stream_chunks([_cc({"role": "assistant", "content": "hi"}),
                              _cc({}, finish="stop")])
    post = _sse_stream_chunks([_cc({"tool_calls": [{"index": 0, "id": "call_really_late",
                                                    "function": {"name": "late_tool",
                                                                 "arguments": "{\"q\":1}"}}]})])
    proxy_port, trace_file, cleanup = _start_hanging_chat_proxy(
        pre, DRAIN_BOUND_TEST_SECONDS * 3, post_body=post, gap_s=0.3)
    if proxy_port is None:
        return
    try:
        raw, saw_stop, elapsed = _read_sse_until_stop(proxy_port, DRAIN_BOUND_TEST_SECONDS)
        if not saw_stop:
            fail("no message_stop within {}s (got {} bytes)".format(DRAIN_BOUND_TEST_SECONDS, len(raw)))
            return
        frames = _parse_sse_frames(raw)
        if _sse_stop_reason(frames) != "tool_use":
            fail("late tool call must upgrade the stop to tool_use, got {!r}".format(_sse_stop_reason(frames)))
            return
        # Poll: the client returns at message_stop, which the proxy writes
        # before it logs the drain event — an immediate read can outrun the
        # sink write (observed 2-of-3 runs failing without the wait).
        events = _wait_for_trace_events(trace_file, "chat_sse_drain")
        if len(events) != 1:
            fail("expected exactly one chat_sse_drain event, got {}".format(len(events)))
            return
        ev = events[0]
        if ev.get("drain_exit") != "time_budget":
            fail("drain must end on its own deadline, got {!r}".format(ev.get("drain_exit")))
            return
        if ev.get("late_tool_call_ms") is None:
            fail("a tool call arriving after finish_reason must record late_tool_call_ms, "
                 "got {!r}".format(ev.get("late_tool_call_ms")))
            return
        if ev.get("late_tool_call_ms") < 0:
            fail("late_tool_call_ms must be non-negative, got {!r}".format(ev.get("late_tool_call_ms")))
            return
        if not ev.get("late_frames"):
            fail("late_frames must count the post-finish chunk, got {!r}".format(ev.get("late_frames")))
            return
        if ev.get("tool_calls_seen") != 1 or ev.get("emitted_tool_use") != 1:
            fail("tool flags must both be 1, got {!r}/{!r}".format(
                ev.get("tool_calls_seen"), ev.get("emitted_tool_use")))
            return
        pass_("time_budget drain: late_tool_call_ms {} (late_frames {})".format(
            ev.get("late_tool_call_ms"), ev.get("late_frames")))
    finally:
        cleanup()




def test_chat_sse_first_frame_finish():
    """A stream whose first data frame carries finish_reason still produces a
    well-formed message_start -> terminal sequence with no content block.

    The first frame is the only chance to open the message; the post-drain logic
    must guarantee message_start precedes the terminal events so the client
    never sees a delta/stop without an opening message.
    """
    print("\n--- Test: Chat SSE First Frame Finish ---")
    chunks = [_cc({}, finish="stop")]
    proxy_port, trace_file, cleanup = _start_chat_sse_proxy(chunks)
    if proxy_port is None:
        return
    try:
        frames = _chat_sse_fetch_frames(proxy_port)
        if frames is None:
            return
        types = _sse_types(frames)
        if not types or types[0] != "message_start":
            fail("message_start must open the stream, got {}".format(types[:3]))
            return
        missing = [t for t in ("message_start", "message_delta", "message_stop")
                   if t not in types]
        if missing:
            fail("finish-only stream missing terminal events {}".format(missing))
            return
        if _sse_content_block_starts(frames):
            fail("a finish-only stream must open no content block, got {!r}".format(
                _sse_content_block_starts(frames)))
            return
        if _sse_stop_reason(frames) != "end_turn":
            fail("stop finish on the first frame should map to end_turn, got {!r}".format(
                _sse_stop_reason(frames)))
            return
        if types.count("message_delta") != 1 or types.count("message_stop") != 1:
            fail("expected exactly one terminal sequence, got {}".format(types))
            return
        pass_("finish on the first frame: start_message precedes a single terminal sequence")
    finally:
        cleanup()




def test_chat_sse_empty_finish_reason_no_change():
    """An empty finish_reason is a finish, not an absence: the is-not-None
    discipline records it, the stop reason follows the mapping (null), and the
    EOF truncation path — which would synthesize end_turn and log
    chat_sse_truncated — must not run. A truthiness regression on
    finish_reason_seen would flip both signals.
    """
    print("\n--- Test: Chat SSE Empty Finish Reason ---")
    chunks = [_cc({"role": "assistant", "content": "hi"}), _cc({}, finish="")]
    proxy_port, trace_file, cleanup = _start_chat_sse_proxy(chunks)
    if proxy_port is None:
        return
    try:
        frames = _chat_sse_fetch_frames(proxy_port)
        if frames is None:
            return
        types = _sse_types(frames)
        if types.count("message_delta") != 1 or types.count("message_stop") != 1:
            fail("expected exactly one terminal sequence, got {}".format(types))
            return
        if _sse_stop_reason(frames) is not None:
            fail("an empty finish_reason must map to a null stop_reason, got {!r}".format(
                _sse_stop_reason(frames)))
            return
        if _trace_events_named(trace_file, "chat_sse_truncated"):
            fail("a recorded (empty) finish_reason must not take the truncation path")
            return
        pass_("empty finish_reason recorded; stop_reason null; no truncation event")
    finally:
        cleanup()




def test_chat_sse_unmapped_finish_with_tools():
    """An empty (unmapped) finish_reason during drain plus captured tool calls
    reports stop_reason null — the None mapping is NOT upgraded by the presence
    of tool blocks (Resolved Decision D3). The block still closes so the client
    can read the tool call.
    """
    print("\n--- Test: Chat SSE Unmapped Finish With Tools ---")
    chunks = [
        _cc({"role": "assistant"}),
        _cc({}, finish=""),
        _cc({"tool_calls": [{"index": 0, "id": "call_u",
                             "function": {"name": "u_tool", "arguments": "{\"a\":1}"}}]}),
    ]
    proxy_port, trace_file, cleanup = _start_chat_sse_proxy(chunks)
    if proxy_port is None:
        return
    try:
        frames = _chat_sse_fetch_frames(proxy_port)
        if frames is None:
            return
        blocks = _sse_tool_use_blocks(frames)
        if len(blocks) != 1 or not blocks[0]["closed"] or blocks[0]["input"] != {"a": 1}:
            fail("the drained tool call must be captured and closed, got {!r}".format(blocks))
            return
        types = _sse_types(frames)
        if types.count("message_delta") != 1 or types.count("message_stop") != 1:
            fail("expected exactly one terminal sequence, got {}".format(types))
            return
        if _sse_stop_reason(frames) is not None:
            fail("an unmapped finish reason must stay null even with tool blocks "
                 "(D3), got {!r}".format(_sse_stop_reason(frames)))
            return
        pass_("unmapped finish + drained tool blocks: block closed, stop_reason null")
    finally:
        cleanup()




def test_chat_sse_empty_revision_does_not_downgrade():
    """A trailing empty-string finish_reason is the absence of an answer, not a
    correction. The drain's revision path exists to honour a provider correcting
    itself ("stop" -> "tool_calls"), so a falsy revised value is refused: an
    already-resolved "tool_calls" survives it, the emitted block still claims
    tool_use, and no spurious chat_sse_tool_degradation event is logged. A
    truthiness regression on the revision guard would overwrite the resolved
    reason with "" and fall into the emitted_tool_use branch, whose force_log
    reports the downgrade as a degradation.
    """
    print("\n--- Test: Chat SSE Empty Revision Does Not Downgrade ---")
    chunks = [
        _cc({"role": "assistant"}),
        _cc({"tool_calls": [{"index": 0, "id": "call_r",
                             "function": {"name": "r_tool", "arguments": "{\"k\":1}"}}]}),
        _cc({}, finish="tool_calls"),
        # A later frame revises the reason to "" — the falsy revision must be
        # refused, leaving the resolved "tool_calls" in place.
        _cc({}, finish=""),
    ]
    proxy_port, trace_file, cleanup = _start_chat_sse_proxy(chunks)
    if proxy_port is None:
        return
    try:
        frames = _chat_sse_fetch_frames(proxy_port)
        if frames is None:
            return
        blocks = _sse_tool_use_blocks(frames)
        if len(blocks) != 1 or not blocks[0]["closed"] or blocks[0]["input"] != {"k": 1}:
            fail("the emitted tool block must survive the empty revision, got {!r}".format(blocks))
            return
        types = _sse_types(frames)
        if types.count("message_delta") != 1 or types.count("message_stop") != 1:
            fail("expected exactly one terminal sequence, got {}".format(types))
            return
        if _sse_stop_reason(frames) != "tool_use":
            fail("an empty revision must not downgrade tool_use, got {!r}".format(
                _sse_stop_reason(frames)))
            return
        degraded = _degraded_trace_events(trace_file)
        if degraded:
            fail("a resolved tool_calls stream must log no degradation event, got {!r}".format(degraded))
            return
        if _trace_events_named(trace_file, "chat_sse_truncated"):
            fail("a recorded finish_reason must not take the truncation path")
            return
        pass_("empty revision refused; stop_reason tool_use; no degradation event")
    finally:
        cleanup()




ALL_TESTS = [
    ("chat-sse-basic-streaming", test_chat_sse_basic_streaming),
    ("chat-sse-finish-reason-mapping", test_chat_sse_finish_reason_mapping),
    ("chat-sse-no-content-delta", test_chat_sse_no_content_delta),
    ("chat-sse-empty-choices-usage-chunk", test_chat_sse_empty_choices_usage_chunk),
    ("chat-sse-eof-without-finish-reason", test_chat_sse_eof_without_finish_reason),
    ("chat-sse-first-event-has-content", test_chat_sse_first_event_has_content),
    ("chat-sse-injection-prevented", test_chat_sse_injection_prevented),
    ("chat-sse-event-line-present", test_chat_sse_event_line_present),
    ("chat-sse-single-tool-call-fragmented-arguments", test_chat_sse_single_tool_call_fragmented_arguments),
    ("chat-sse-parallel-tool-calls-interleaved", test_chat_sse_parallel_tool_calls_interleaved),
    ("chat-sse-reasoning-text-then-tool-call", test_chat_sse_reasoning_text_then_tool_call),
    ("chat-sse-tool-call-metadata-buffering", test_chat_sse_tool_call_metadata_buffering),
    ("chat-sse-malformed-tool-call-degrades", test_chat_sse_malformed_tool_call_degrades),
    ("chat-sse-mixed-valid-and-malformed-tool-calls", test_chat_sse_mixed_valid_and_malformed_tool_calls),
    ("chat-sse-tool-call-eof-without-finish", test_chat_sse_tool_call_eof_without_finish),
    ("chat-sse-non-tool-calls-finish-with-tool-blocks", test_chat_sse_non_tool_calls_finish_with_tool_blocks),
    ("chat-sse-scalar-delta-after-tool-blocks", test_chat_sse_scalar_delta_after_tool_blocks),
    ("chat-sse-final-fragment-in-finish-frame", test_chat_sse_final_fragment_in_finish_frame),
    ("chat-sse-no-deltas-tool-calls-finish", test_chat_sse_no_deltas_tool_calls_finish),
    ("chat-sse-unparseable-arguments-at-close", test_chat_sse_unparseable_arguments_at_close),
    ("chat-sse-conflicting-metadata", test_chat_sse_conflicting_metadata),
    ("chat-sse-fragments-missing-index", test_chat_sse_fragments_missing_index),
    ("chat-sse-malformed-delta-shapes", test_chat_sse_malformed_delta_shapes),
    ("chat-sse-pending-buffer-cap-exceeded", test_chat_sse_pending_buffer_cap_exceeded),
    ("chat-sse-too-many-parallel-tools", test_chat_sse_too_many_parallel_tools),
    ("chat-sse-eof-empty-tool-calls-sentinel", test_chat_sse_eof_empty_tool_calls_sentinel),
    ("chat-sse-mixed-parseable-unparseable-finish", test_chat_sse_mixed_parseable_unparseable_finish),
    ("chat-sse-non-dict-arguments-at-close", test_chat_sse_non_dict_arguments_at_close),
    ("chat-sse-frame-dropped-guard", test_chat_sse_frame_dropped_guard),
    ("chat-mode-streamed-tool-command-e2e", test_chat_mode_streamed_tool_command_e2e),
    ("chat-sse-reasoning-delta-to-thinking-delta", test_chat_sse_reasoning_delta_to_thinking_delta),
    ("chat-sse-reasoning-delta-no-content", test_chat_sse_reasoning_delta_no_content),
    ("chat-sse-reasoning-then-text-transition", test_chat_sse_reasoning_then_text_transition),
    ("chat-sse-usage-after-finish-reason", test_chat_sse_usage_after_finish_reason),
    ("chat-sse-tool-calls-after-finish-reason", test_chat_sse_tool_calls_after_finish_reason),
    ("chat-sse-usage-and-tool-calls-after-finish", test_chat_sse_usage_and_tool_calls_after_finish_reason),
    ("chat-sse-finish-reason-last-chunk", test_chat_sse_finish_reason_last_chunk_no_drain),
    ("chat-sse-truncation-still-works", test_chat_sse_truncation_still_works),
    ("chat-sse-drain-time-deadline", test_chat_sse_drain_time_deadline),
    ("chat-sse-done-terminates-drain", test_chat_sse_done_terminates_drain),
    ("chat-sse-text-after-finish-suppressed", test_chat_sse_text_after_finish_suppressed),
    ("chat-sse-stream-options-include-usage", test_chat_sse_stream_options_include_usage),
    ("chat-sse-drain-byte-budget", test_chat_sse_drain_byte_budget),
    ("chat-sse-first-frame-finish", test_chat_sse_first_frame_finish),
    ("chat-sse-empty-finish-reason", test_chat_sse_empty_finish_reason_no_change),
    ("chat-sse-unmapped-finish-with-tools", test_chat_sse_unmapped_finish_with_tools),
    ("chat-sse-empty-revision-no-downgrade", test_chat_sse_empty_revision_does_not_downgrade),
    ("chat-sse-done-without-finish-reason-is-terminal", test_chat_sse_done_without_finish_reason_is_terminal),
    ("chat-sse-truncation-with-tool-block-emits-error", test_chat_sse_truncation_with_tool_block_emits_error_event),
    ("chat-sse-drain-event-on-done", test_chat_sse_drain_event_on_done),
    ("chat-sse-drain-event-trailing-tool-calls", test_chat_sse_drain_event_trailing_tool_calls),
    ("chat-sse-drain-event-eof-exit", test_chat_sse_drain_event_eof_exit),
    ("chat-sse-unfinished-turn-shadow-logged", test_chat_sse_unfinished_turn_shadow_logged),
    ("chat-sse-drain-late-tool-call-time-budget", test_chat_sse_drain_late_tool_call_time_budget),
    ("chat-sse-tool-degradation-on-cut-stream", test_chat_sse_tool_degradation_on_cut_stream),
]


if __name__ == "__main__":
    run_cli(ALL_TESTS, "claude-retry-proxy tests: test_chat_sse")
