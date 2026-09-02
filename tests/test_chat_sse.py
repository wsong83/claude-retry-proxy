"""Chat-mode SSE streaming tests: frame assembly, reasoning deltas,
tool-call delta conversion, degradation paths, and streamed e2e.

Part of the claude-retry-proxy suite; runnable standalone.
"""

import json

from _harness import (
    _assert_degradation_metadata_only,
    _cc,
    _chat_sse_fetch_frames,
    _degraded_trace_events,
    _mode_tiers,
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
    errors,
    fail,
    find_free_port,
    info,
    pass_,
    run_cli,
)




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
    """Terminal events are synthesized when the stream ends without finish_reason."""
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
        missing = [t for t in ("content_block_stop", "message_delta", "message_stop") if t not in types]
        if missing:
            fail("EOF without finish_reason should synthesize terminal events; missing {}".format(missing))
        else:
            pass_("terminal events synthesized on EOF")
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
    """A length/stop finish while tool blocks are open closes them and maps normally."""
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
        if _sse_stop_reason(frames2) != "end_turn":
            fail("stop finish should map to end_turn (never tool_use), got {!r}".format(_sse_stop_reason(frames2)))
            return
    finally:
        cleanup2()
    pass_("non-tool_calls finish with open tool blocks: close blocks, map finish normally, log event")




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
    """Valid metadata + tool_calls finish but unparseable args degrade the stop reason."""
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
        if _sse_stop_reason(frames) is not None:
            fail("unparseable accumulated arguments must degrade stop_reason to null, got {!r}".format(_sse_stop_reason(frames)))
            return
        events = _degraded_trace_events(trace_file)
        if len(events) != 1 or events[0].get("unparseable_arg_count") != 1:
            fail("expected one event with unparseable_arg_count 1, got {!r}".format(events))
            return
        pass_("unparseable accumulated arguments degrade stop_reason to null")
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
    """Non-empty fragments without an index are dropped, counted, and block tool_use."""
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
        if _sse_stop_reason(frames) is not None:
            fail("dropped fragments must prevent tool_use claim, got {!r}".format(_sse_stop_reason(frames)))
            return
        events = _degraded_trace_events(trace_file)
        if len(events) != 1 or events[0].get("dropped_fragment_count") != 1:
            fail("expected one event with dropped_fragment_count 1, got {!r}".format(events))
            return
        pass_("index-less fragments dropped, counted, and tool_use not claimed")
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
    """More than 32 tracked tool indexes overflow into the coalesced diagnostic."""
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
        if _sse_stop_reason(frames) is not None:
            fail("tool-index overflow must degrade stop_reason to null, got {!r}".format(_sse_stop_reason(frames)))
            return
        events = _degraded_trace_events(trace_file)
        if len(events) != 1 or events[0].get("overflow_tool_count") != 1:
            fail("expected overflow_tool_count 1 in one event, got {!r}".format(events))
            return
        pass_("33 parallel tool indexes: 32 started contiguously, overflow diagnosed, stop null")
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
    """One unparseable parallel tool degrades the whole stream to a null stop reason.

    R2 review remediation: the finish claim condition includes
    unparseable_arg_count == 0, so a stream with a valid tool and a second tool
    whose accumulated arguments fail json.loads never claims tool_use, even
    though both blocks start and close.
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
        if _sse_stop_reason(frames) is not None:
            fail("mixed parseable+unparseable finish must degrade to null, got {!r}".format(_sse_stop_reason(frames)))
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
        pass_("mixed parseable+unparseable parallel finish -> null, unparseable_arg_count 1, metadata-only event")
    finally:
        cleanup()




def test_chat_sse_non_dict_arguments_at_close():
    """Arguments that parse but not as a dict (e.g. \"123\") are counted unparseable.

    R3 review remediation: close-time json.loads must produce a dict to count a
    tool as valid; a number/string/bool/null parse result increments
    unparseable_arg_count, so this stream degrades to a null stop reason.
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
        if _sse_stop_reason(frames) is not None:
            fail("non-dict arguments at close must not claim tool_use, got {!r}".format(_sse_stop_reason(frames)))
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
        pass_("non-dict arguments at close -> null stop_reason, unparseable_arg_count 1, metadata-only event")
    finally:
        cleanup()




def test_chat_sse_frame_dropped_guard():
    """A mid-stream oversized no-delimiter frame blocks the tool_use claim.

    R5 review remediation: when an oversized (>64 KB) no-delimiter frame is
    dropped after a tool block was emitted, frame_dropped blocks the finish
    claim via `not (frame_dropped and emitted_tool_use)`, so the stream
    degrades to null and the trace event reports frame_dropped: 1.
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
        if _sse_stop_reason(frames) is not None:
            fail("frame drop with emitted tool use must degrade to null, got {!r}".format(_sse_stop_reason(frames)))
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
        pass_("oversized no-delimiter frame mid-tool-stream -> null stop_reason, frame_dropped 1")
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
]


if __name__ == "__main__":
    run_cli(ALL_TESTS, "claude-retry-proxy tests: test_chat_sse")
