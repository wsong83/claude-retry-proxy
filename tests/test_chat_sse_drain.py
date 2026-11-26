"""Chat-mode stream termination, drain semantics and frame-cap disposition tests.

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
    fail,
    find_free_port,
    pass_,
    run_cli,
)


# A post-finish drain that has not terminated by this point is a failure: the
# drain is bounded by MAX_DRAIN_SECONDS (5s) and must leave ample headroom
# under its own socket pin, which is the mode's drain bound rather than any
# config-swap timeout (the swap drain waits for live work and has no
# wall-clock cap).
DRAIN_BOUND_TEST_SECONDS = 20


def _start_hanging_chat_proxy(pre_body, hold_s, post_body=None, gap_s=0.0,
                              extra_env=None):
    """Chat-mode proxy whose mock upstream streams `pre_body` over an unterminated
    response (HTTP/1.0, no Content-Length) and then holds the socket open.

    The harness responder always sets Content-Length and closes, so the proxy's
    read loop sees EOF immediately and the stall path is never exercised. This
    mirror of _start_chat_sse_proxy exists solely to reach it.

    With `post_body` and `gap_s` the upstream writes `post_body` after a delay,
    which lands it in a later read chunk than `pre_body` — the shape that makes
    a post-finish frame count as *late* (the per-chunk offset is taken at chunk
    receipt, before the frames are parsed).

    `extra_env` passes additional env vars to the proxy subprocess — the drain
    tests pin PROXY_READ_TIMEOUT here (its validation floor is 10; smaller
    values are refused by design and fall back to 120).

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
        passphrase=None, trace_file=trace_file, extra_env=extra_env)

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


# ===========================================================================
# Frame-cap disposition (plan 2026-11-15-httpx2-transport-sse, Step 5a)
# ===========================================================================

# The cap is chat_sse.py's MAX_EVENT_BUFFER local constant (2 MB), defined
# inside _stream_chat_sse_to_anthropic. The fixtures overshoot it by a margin
# far larger than any read-chunk boundary, so the trip is reached on
# accumulated bytes rather than on a lucky split.
_FRAME_CAP_BYTES = 2 * 1024 * 1024


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


def test_chat_sse_drain_time_deadline():
    """A provider that sends finish_reason and then goes silent must not hold the
    request open past the drain bound.

    The bound is now the request read timeout (PROXY_READ_TIMEOUT, pinned to its
    10 s floor here) — the old point-of-blocking socket arming died with the
    stdlib transport. The per-chunk MAX_DRAIN_SECONDS check still governs a
    CHATTY drain (a provider that keeps sending frames); it cannot fire for a
    silent one, so `drain_exit` must read "read_timeout", which is what
    distinguishes the read boundary from the time budget.
    """
    print("\n--- Test: Chat SSE Drain Time Deadline ---")
    read_timeout = 10
    pre = _sse_stream_chunks([_cc({"role": "assistant", "content": "hi"}),
                              _cc({}, finish="stop")])
    proxy_port, trace_file, cleanup = _start_hanging_chat_proxy(
        pre, DRAIN_BOUND_TEST_SECONDS * 3,
        extra_env={"PROXY_READ_TIMEOUT": str(read_timeout)})
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
        # The fixture goes silent after finish_reason, so the drain exits on the
        # read timeout. If that clause were dead code — e.g. a silent drain
        # mislabelled "read_error" by the generic exception arm — this reports
        # the wrong enum.
        # Poll: _read_sse_until_stop returns at message_stop, which the proxy
        # writes before it logs the drain event, so an immediate read races
        # the sink write.
        drain_events = _wait_for_trace_events(trace_file, "chat_sse_drain")
        if len(drain_events) != 1:
            fail("expected exactly one chat_sse_drain event, got {}".format(len(drain_events)))
            return
        if drain_events[0].get("drain_exit") != "read_timeout":
            fail("silent provider must exit the drain on the read boundary "
                 "(read_timeout), got {!r}".format(drain_events[0].get("drain_exit")))
            return
        pass_("silent provider: drain bounded by the {}s read timeout, terminal "
              "emitted in {:.1f}s".format(read_timeout, elapsed))
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


def test_chat_sse_done_without_trailing_blank_line():
    """A [DONE] sentinel stranded at EOF (no trailing blank line) is honoured.

    A provider may write `data: [DONE]\\n` and close without the blank line
    that delimits a frame, stranding the sentinel in the buffer. At EOF the
    sentinel is unambiguous, so the stream is protocol-complete: it closes
    with the synthesized terminal sequence — never a retryable error — and
    chat_sse_truncated records saw_done: 1. Without the EOF flush the client
    would re-issue a request that already succeeded.

    No finish frame is declared: the flush under test lives on the pre-finish
    EOF disposition, where a stranded [DONE] is the only completion signal.
    """
    print("\n--- Test: Chat SSE DONE Without Trailing Blank Line ---")
    upstream_port = find_free_port()
    tiers = _mode_tiers()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port), "key": "K", "mode": "chat"}}
    chunks = [_cc({"role": "assistant", "content": "hello"})]
    sse_body = _sse_stream_chunks(chunks) + b"data: [DONE]\n"
    responders = {"p": lambda info: (200, "text/event-stream", sse_body)}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(
        tiers, vendors, responders=responders)
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
        missing = [t for t in ("message_delta", "message_stop") if t not in types]
        if missing:
            fail("stranded-[DONE] stream must close with the terminal sequence; "
                 "missing {} ({})".format(missing, types))
            return
        errs = _sse_frames_with_type(frames, "error")
        if errs:
            fail("stranded-[DONE] stream must not emit an error frame, got {!r}".format(errs))
            return
        if _sse_stop_reason(frames) != "end_turn":
            fail("stranded [DONE] should synthesize end_turn, got {!r}".format(
                _sse_stop_reason(frames)))
            return
        events = _trace_events_named(trace_file, "chat_sse_truncated")
        if len(events) != 1:
            fail("expected exactly one chat_sse_truncated event, got {}".format(len(events)))
            return
        if events[0].get("saw_done") != 1:
            fail("chat_sse_truncated must record saw_done: 1 for a stranded [DONE], "
                 "got {!r}".format(events[0].get("saw_done")))
            return
        pass_("[DONE] without trailing blank line: terminal sequence, no error frame, saw_done 1")
    finally:
        cleanup()


def test_chat_sse_partial_frame_at_eof_is_not_flushed():
    """A partial data payload stranded at EOF is discarded, not flushed.

    The stranded-sentinel flush at EOF honours only an exact [DONE]. A
    truncated payload (`data: {"cho`) is ambiguous, so the stream keeps the
    cut-stream disposition: chat_sse_truncated records saw_done: 0 and a
    retryable api_error closes it — the negative control proving the flush
    does not over-reach into partial payloads.
    """
    print("\n--- Test: Chat SSE Partial Frame At EOF Is Not Flushed ---")
    upstream_port = find_free_port()
    tiers = _mode_tiers()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port), "key": "K", "mode": "chat"}}
    chunks = [_cc({"role": "assistant", "content": "hello"})]
    sse_body = _sse_stream_chunks(chunks) + b'data: {"cho'
    responders = {"p": lambda info: (200, "text/event-stream", sse_body)}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(
        tiers, vendors, responders=responders)
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
        present = [t for t in ("message_delta", "message_stop") if t in types]
        if present:
            fail("partial-payload stream must not synthesize {}; got {}".format(present, types))
            return
        errs = _sse_frames_with_type(frames, "error")
        if len(errs) != 1:
            fail("partial-payload stream must close with exactly one error frame, "
                 "got {} ({})".format(len(errs), types))
            return
        if (errs[0].get("error") or {}).get("type") != "api_error":
            fail("partial-payload error must be api_error (retryable), got {!r}".format(
                errs[0].get("error")))
            return
        events = _trace_events_named(trace_file, "chat_sse_truncated")
        if len(events) != 1:
            fail("expected exactly one chat_sse_truncated event, got {}".format(len(events)))
            return
        if events[0].get("saw_done") != 0:
            fail("chat_sse_truncated must record saw_done: 0 for a partial payload, "
                 "got {!r}".format(events[0].get("saw_done")))
            return
        pass_("partial payload at EOF: api_error closes, saw_done 0, no flushed terminal")
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
        # Late-frame offsets are null on a stream that ended at the finish
        # frame: the content, finish and [DONE] frames all arrive in a single
        # read chunk. The late-frame trio IS stamped when the finish is
        # discovered and the post-loop accounting DOES run — but the [DONE]
        # sentinel is excluded from frames_seen, so no frame follows the
        # finish signal and the offsets stay null. A stream that ended at the
        # finish signal must not claim something arrived after it.
        if ev.get("first_late_ms") is not None or ev.get("last_late_ms") is not None:
            fail("first_late_ms/last_late_ms must both be null when no frame "
                 "followed the finish signal, got {!r}/{!r}".format(
                     ev.get("first_late_ms"), ev.get("last_late_ms")))
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


def test_chat_sse_drain_late_tool_call_time_budget():
    """A tool call that arrives after finish_reason on a drain that ends at the
    read boundary reports a non-null late_tool_call_ms — the arrival latency
    of a tool call the drain would otherwise have lost, and the number that
    answers whether the 5 s per-chunk budget is generous or binding.

    Uses a two-phase hanging upstream: the finish stream lands first, the tool
    frame 0.3 s later (a distinct read chunk, so it counts as late), then the
    socket goes silent until the REQUEST READ TIMEOUT fires (PROXY_READ_TIMEOUT
    pinned to its 10 s floor) — the same read_timeout exit
    test_chat_sse_drain_time_deadline pins. The name is kept for continuity;
    the exit enum is no longer "time_budget", which now belongs to a chatty
    drain cut by the per-chunk MAX_DRAIN_SECONDS check.
    """
    print("\n--- Test: Chat SSE Drain Late Tool Call Time Budget ---")
    read_timeout = 10
    pre = _sse_stream_chunks([_cc({"role": "assistant", "content": "hi"}),
                              _cc({}, finish="stop")])
    post = _sse_stream_chunks([_cc({"tool_calls": [{"index": 0, "id": "call_really_late",
                                                    "function": {"name": "late_tool",
                                                                 "arguments": "{\"q\":1}"}}]})])
    proxy_port, trace_file, cleanup = _start_hanging_chat_proxy(
        pre, DRAIN_BOUND_TEST_SECONDS * 3, post_body=post, gap_s=0.3,
        extra_env={"PROXY_READ_TIMEOUT": str(read_timeout)})
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
        if ev.get("drain_exit") != "read_timeout":
            fail("a silent drain must end at the read boundary, got {!r}".format(
                ev.get("drain_exit")))
            return
        if ev.get("late_tool_call_ms") is None:
            fail("a tool call arriving after finish_reason must record late_tool_call_ms, "
                 "got {!r}".format(ev.get("late_tool_call_ms")))
            return
        if ev.get("late_tool_call_ms") < 0:
            fail("late_tool_call_ms must be non-negative, got {!r}".format(ev.get("late_tool_call_ms")))
            return
        # The tool call is one of this stream's late frames, so its arrival
        # offset must sit inside the [first, last] late-frame window. Guard
        # all three on non-None first — comparing against None raises on
        # Python 3, and the None cases are pinned by the drain-on-done fixture.
        _first_late = ev.get("first_late_ms")
        _last_late = ev.get("last_late_ms")
        _late_tool = ev.get("late_tool_call_ms")
        if _first_late is None or _last_late is None or _late_tool is None:
            fail("first_late_ms/last_late_ms/late_tool_call_ms must all be set "
                 "when a late tool call arrived, got {!r}/{!r}/{!r}".format(
                     _first_late, _last_late, _late_tool))
            return
        if not (_first_late <= _late_tool <= _last_late):
            fail("late_tool_call_ms must be sandwiched between first_late_ms and "
                 "last_late_ms, got first={} tool={} last={}".format(
                     _first_late, _late_tool, _last_late))
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


def test_chat_sse_first_frame_oversize_errors_loud():
    """A pre-finish frame that never terminates errors out loud instead of
    being silently dropped.

    A >2 MB no-delimiter frame before finish_reason means the turn has not been
    terminal-signaled: the client gets `message_start` then `event: error` with
    error.code "upstream_frame_oversize" and NO message_delta/message_stop, so
    the turn is retryable rather than silently degraded. The trace carries both
    chat_sse_frame_oversize (with the frame size) and the invariant
    chat_sse_truncated event — every 200 chat stream ends with exactly one of
    chat_sse_drain / chat_sse_truncated.
    """
    print("\n--- Test: Chat SSE Pre-Finish Oversize Frame Errors Loud ---")
    upstream_port = find_free_port()
    tiers = _mode_tiers()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port),
                     "key": "K", "mode": "chat"}}
    # One frame head, no delimiter anywhere after it: the buffer can only grow.
    sse_body = b"data: " + b"z" * (_FRAME_CAP_BYTES + 65536)
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
        types = _sse_types(frames)
        if not types or types[0] != "message_start":
            fail("the stream must open with message_start, got {}".format(types[:3]))
            return
        if "message_delta" in types or "message_stop" in types:
            fail("an oversize pre-finish frame must not synthesize a terminal: "
                 "{}".format(types))
            return
        errors = [d for t, d in frames if _sse_frame_type((t, d)) == "error"]
        if len(errors) != 1:
            fail("expected exactly one SSE error frame, got {} ({})".format(
                len(errors), types))
            return
        code = ((errors[0] or {}).get("error") or {}).get("code")
        if code != "upstream_frame_oversize":
            fail("expected error.code 'upstream_frame_oversize', got {!r}".format(code))
            return
        oversized = _wait_for_trace_events(trace_file, "chat_sse_frame_oversize")
        if len(oversized) != 1:
            fail("expected exactly one chat_sse_frame_oversize event, got {}".format(
                len(oversized)))
            return
        size = oversized[0].get("bytes")
        if not isinstance(size, int) or size <= _FRAME_CAP_BYTES:
            fail("chat_sse_frame_oversize must record the frame size above the "
                 "cap, got {!r}".format(size))
            return
        truncated = _wait_for_trace_events(trace_file, "chat_sse_truncated")
        if len(truncated) != 1:
            fail("the loud error must also emit the invariant chat_sse_truncated "
                 "event, got {}".format(len(truncated)))
            return
        if _trace_events_named(trace_file, "chat_sse_drain"):
            fail("a pre-finish close must not emit chat_sse_drain")
            return
        pass_("pre-finish oversize frame: message_start + upstream_frame_oversize "
              "error, no terminal, frame_oversize {} bytes + chat_sse_truncated".format(
                  size))
    finally:
        cleanup()


def test_chat_sse_drain_window_frame_oversize_drops_and_completes():
    """An oversize frame arriving AFTER finish_reason is dropped, and the turn
    still completes.

    The turn is already terminal-signaled in the drain window, so failing it
    would force a full client re-run for data the client never needed. The drop
    is trace-visible (chat_sse_frame_oversize with the size) and counted in
    chat_sse_tool_degradation's frame_dropped — the field's narrowed,
    drain-window-only meaning.

    The oversize bytes must arrive without a delimiter in the same buffer (a
    coalesced chunk containing the junk AND its terminator would be parsed as
    one frame and charged to the byte budget instead), so the fixture flushes
    the junk first and the terminator after a pause.
    """
    print("\n--- Test: Chat SSE Drain-Window Oversize Frame Drops and Completes ---")
    upstream_port = find_free_port()
    tiers = _mode_tiers()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port),
                     "key": "K", "mode": "chat"}}
    pre = _sse_stream_chunks([_cc({"role": "assistant", "content": "hi"}),
                              _cc({}, finish="stop")])
    junk = b"z" * (_FRAME_CAP_BYTES + 65536)

    def streamer(handler, info):
        handler.send_response(200)
        handler.send_header("Content-Type", "text/event-stream")
        handler.end_headers()
        handler.wfile.write(pre)
        handler.wfile.flush()
        handler.wfile.write(junk)
        handler.wfile.flush()
        time.sleep(0.3)
        # Terminator + sentinel: the junk has no delimiter of its own, so it is
        # dropped by the frame cap before these bytes are ever scanned.
        handler.wfile.write(b"\ndata: [DONE]\n\n")
        handler.wfile.flush()

    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(
        tiers, vendors, streamers={"p": streamer})
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        frames = _chat_sse_fetch_frames(proxy_port)
        if frames is None:
            return
        types = _sse_types(frames)
        missing = [t for t in ("message_delta", "message_stop") if t not in types]
        if missing:
            fail("the turn must still terminate normally, missing {}".format(missing))
            return
        if _sse_stop_reason(frames) != "end_turn":
            fail("stop reason must still be end_turn, got {!r}".format(
                _sse_stop_reason(frames)))
            return
        oversized = _wait_for_trace_events(trace_file, "chat_sse_frame_oversize")
        if len(oversized) != 1:
            fail("expected exactly one chat_sse_frame_oversize event, got {}".format(
                len(oversized)))
            return
        size = oversized[0].get("bytes")
        if not isinstance(size, int) or size <= _FRAME_CAP_BYTES:
            fail("chat_sse_frame_oversize must record the frame size above the "
                 "cap, got {!r}".format(size))
            return
        events = _degraded_trace_events(trace_file)
        if len(events) != 1:
            fail("expected exactly one chat_sse_tool_degradation event, got {}".format(
                len(events)))
            return
        if events[0].get("frame_dropped") != 1:
            fail("the drain-window drop must count frame_dropped 1, got {!r}".format(
                events[0].get("frame_dropped")))
            return
        if not _assert_degradation_metadata_only(events[0]):
            return
        pass_("drain-window oversize frame dropped ({} bytes, frame_dropped 1) and "
              "the turn completed with its normal terminal".format(size))
    finally:
        cleanup()


def test_chat_sse_drain_read_timeout_completes_turn():
    """A silent post-finish drain completes the turn at the read boundary and
    records which bound ended it.

    PROXY_READ_TIMEOUT is pinned to its 10 s floor. The per-chunk
    MAX_DRAIN_SECONDS budget cannot fire when no chunk arrives, so the exit is
    the read timeout — the new drain_exit value that makes this residual
    measurable — and the post-loop terminal synthesis still runs, so the client
    sees message_delta + message_stop rather than a truncated stream.
    """
    print("\n--- Test: Chat SSE Drain Read Timeout Completes the Turn ---")
    read_timeout = 10
    pre = _sse_stream_chunks([_cc({"role": "assistant", "content": "hi"}),
                              _cc({}, finish="stop")])
    proxy_port, trace_file, cleanup = _start_hanging_chat_proxy(
        pre, DRAIN_BOUND_TEST_SECONDS * 3,
        extra_env={"PROXY_READ_TIMEOUT": str(read_timeout)})
    if proxy_port is None:
        return
    try:
        raw, saw_stop, elapsed = _read_sse_until_stop(proxy_port, DRAIN_BOUND_TEST_SECONDS)
        if not saw_stop:
            fail("a silent drain must still complete the turn, no message_stop "
                 "within {}s (got {} bytes)".format(DRAIN_BOUND_TEST_SECONDS, len(raw)))
            return
        if elapsed > read_timeout + 8:
            fail("the drain ran {:.1f}s — the {}s read timeout did not bound "
                 "it".format(elapsed, read_timeout))
            return
        types = _sse_types(_parse_sse_frames(raw))
        missing = [t for t in ("message_delta", "message_stop") if t not in types]
        if missing:
            fail("the read-timeout exit must synthesize the normal terminal, "
                 "missing {}".format(missing))
            return
        events = _wait_for_trace_events(trace_file, "chat_sse_drain")
        if len(events) != 1:
            fail("expected exactly one chat_sse_drain event, got {}".format(len(events)))
            return
        if events[0].get("drain_exit") != "read_timeout":
            fail("drain_exit must be 'read_timeout', got {!r}".format(
                events[0].get("drain_exit")))
            return
        if _trace_events_named(trace_file, "chat_sse_truncated"):
            fail("a completed drain must not emit chat_sse_truncated")
            return
        pass_("silent drain ended at the {}s read boundary ({:.1f}s) with the "
              "normal terminal and drain_exit 'read_timeout'".format(
                  read_timeout, elapsed))
    finally:
        cleanup()


ALL_TESTS = [
    ("chat-sse-eof-without-finish-reason", test_chat_sse_eof_without_finish_reason),
    ("chat-sse-tool-calls-after-finish-reason", test_chat_sse_tool_calls_after_finish_reason),
    ("chat-sse-usage-and-tool-calls-after-finish", test_chat_sse_usage_and_tool_calls_after_finish_reason),
    ("chat-sse-finish-reason-last-chunk", test_chat_sse_finish_reason_last_chunk_no_drain),
    ("chat-sse-truncation-still-works", test_chat_sse_truncation_still_works),
    ("chat-sse-drain-time-deadline", test_chat_sse_drain_time_deadline),
    ("chat-sse-done-terminates-drain", test_chat_sse_done_terminates_drain),
    ("chat-sse-text-after-finish-suppressed", test_chat_sse_text_after_finish_suppressed),
    ("chat-sse-drain-byte-budget", test_chat_sse_drain_byte_budget),
    ("chat-sse-first-frame-finish", test_chat_sse_first_frame_finish),
    ("chat-sse-empty-finish-reason", test_chat_sse_empty_finish_reason_no_change),
    ("chat-sse-unmapped-finish-with-tools", test_chat_sse_unmapped_finish_with_tools),
    ("chat-sse-empty-revision-no-downgrade", test_chat_sse_empty_revision_does_not_downgrade),
    ("chat-sse-done-without-finish-reason-is-terminal", test_chat_sse_done_without_finish_reason_is_terminal),
    ("chat-sse-done-without-trailing-blank-line", test_chat_sse_done_without_trailing_blank_line),
    ("chat-sse-partial-frame-at-eof-is-not-flushed", test_chat_sse_partial_frame_at_eof_is_not_flushed),
    ("chat-sse-truncation-with-tool-block-emits-error", test_chat_sse_truncation_with_tool_block_emits_error_event),
    ("chat-sse-drain-event-on-done", test_chat_sse_drain_event_on_done),
    ("chat-sse-drain-event-trailing-tool-calls", test_chat_sse_drain_event_trailing_tool_calls),
    ("chat-sse-drain-event-eof-exit", test_chat_sse_drain_event_eof_exit),
    ("chat-sse-drain-late-tool-call-time-budget", test_chat_sse_drain_late_tool_call_time_budget),
    # Frame-cap disposition (plan 2026-11-15-httpx2-transport-sse, Step 5a)
    ("chat-sse-first-frame-oversize-errors-loud", test_chat_sse_first_frame_oversize_errors_loud),
    ("chat-sse-drain-window-frame-oversize-drops-and-completes", test_chat_sse_drain_window_frame_oversize_drops_and_completes),
    ("chat-sse-drain-read-timeout-completes-turn", test_chat_sse_drain_read_timeout_completes_turn),
]


if __name__ == "__main__":
    run_cli(ALL_TESTS, "claude-retry-proxy tests: test_chat_sse_drain")
