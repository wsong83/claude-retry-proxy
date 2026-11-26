"""Chat-mode SSE core-stream conversion tests: frame assembly, reasoning deltas and degradation paths.

Part of the claude-retry-proxy suite; runnable standalone.
"""

import io
import json
import os
import shutil
import tempfile
import time
from _harness import (
    _cc,
    _chat_sse_fetch_frames,
    _message_delta_usage,
    _mode_tiers,
    _parse_sse_frames,
    _send_proxy_request_stream,
    _sse_frame_type,
    _sse_frames_with_type,
    _sse_stop_reason,
    _sse_stream_chunks,
    _sse_types,
    _start_chat_sse_proxy,
    _start_mode_proxy,
    _trace_events_named,
    _wait_for_trace_events,
    fail,
    find_free_port,
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
            # Self-classifying failure (deferred issue
            # flaky-chat-sse-transition-empty-stream): the frame types and
            # raw head distinguish an SSE error frame (proxy cut the
            # stream) from raw chat-completion chunks (Content-Type
            # misdetected, untransformed passthrough) without a rerun —
            # and with Step 8's preservation the trace and stderr survive
            # for the same triage.
            fail("expected 2 starts and 2 stops, got starts={!r} stops={!r}; "
                 "frame types={!r}; raw head={!r}".format(
                     starts, stops,
                     [t for t, _ in frames[:8]], raw[:200]))
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


def test_chat_sse_inband_usage_terminal():
    """A non-int upstream usage value still yields a full terminal sequence.

    Pins terminal()'s int-only usage copy: usage is stored unvalidated from
    the upstream frame, so a non-int value used to be copied verbatim into
    the message_delta payload — the re-encode raised RecursionError and
    escaped as a SILENT clean EOF: no message_delta, no message_stop, no
    error event, bypassing the cut-stream machinery. Post-fix only ints
    (bools excluded) enter the payload: the non-int prompt_tokens falls back
    to 0 while the int completion_tokens passes through, and the stream
    completes. Re-fixtured shallow (plan 2026-10-25-json-nesting-limit): the
    subject was never the interpreter's recursion profile.
    """
    print("\n--- Test: Chat SSE In-Band Usage Terminal ---")

    usage_frame = _inband_usage_frame_bytes()
    sse_body = (_sse_stream_chunks([_cc({"role": "assistant"})])
                + b"data: " + usage_frame + b"\n\n"
                + b"data: [DONE]\n\n")

    upstream_port = find_free_port()
    tiers = _mode_tiers()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port),
                     "key": "K", "mode": "chat"}}
    responders = {"p": lambda info: (200, "text/event-stream", sse_body)}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(
        tiers, vendors, responders=responders)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        frames = _chat_sse_fetch_frames(proxy_port)
        if frames is None:
            fail("the non-int usage frame dropped the connection — "
                 "the terminal()/_sse_event guards regressed")
            return
        types = _sse_types(frames)
        if "message_delta" not in types:
            fail("no message_delta after a non-int usage value (silent-EOF "
                 "class): {}".format(types))
            return
        if "message_stop" not in types:
            fail("no message_stop after a non-int usage value: {}".format(types))
            return
        if "error" in types:
            fail("unexpected error frame: the copy-site type check should keep "
                 "the payload serializable, got {}".format(types))
            return
        usage = _message_delta_usage(frames)
        if not usage:
            fail("no usage on message_delta")
            return
        if usage.get("input_tokens") != 0:
            fail("non-int prompt_tokens must fall back to input_tokens 0, "
                 "got {!r}".format(usage))
            return
        if usage.get("output_tokens") != 7:
            fail("the int completion_tokens must pass the type check, "
                 "got {!r}".format(usage))
            return
        if _sse_stop_reason(frames) != "end_turn":
            fail("expected end_turn, got {!r}".format(_sse_stop_reason(frames)))
            return
        pass_("non-int usage: message_delta(input 0, output 7) + "
              "message_stop, no error frame")
    finally:
        cleanup()


def test_sse_event_unserializable_payload_degrades():
    """A payload _sse_event cannot serialize degrades to an SSE error frame.

    Pins the _sse_event encode fence: its json.dumps was the only
    request/response-path encode with no enclosing try, so an upstream-typed
    value that survived every copy-site check raised out of the write path
    and the client saw a silent clean EOF. Post-fix the encode degrades to a
    standard SSE error event carrying error.code ==
    "response_frame_encode_failure" with request_id threaded — preserving the
    close-with-an-error property — instead of raising.

    Re-fixtured shallow (plan 2026-10-25-json-nesting-limit): a set is
    unserializable by json.dumps at any depth, so the coverage no longer
    depends on locating an interpreter-specific encode band.
    """
    print("\n--- Test: SSE Event Unserializable Payload Degrades ---")
    import claude_retry_proxy.server as srv

    payload = {"type": "message_delta",
               "usage": {"input_tokens": {1, 2}, "output_tokens": 7}}

    handler = object.__new__(srv.ProxyHandler)
    try:
        out = handler._sse_event(payload, request_id="req-unserializable-test")
    except Exception as e:
        fail("_sse_event raised {!r} on an unserializable payload — the encode "
             "fence regressed".format(e))
        return
    if not isinstance(out, bytes):
        fail("_sse_event returned {!r}, expected bytes".format(type(out)))
        return
    text = out.decode("utf-8")
    lines = text.splitlines()
    if not lines or lines[0] != "event: error":
        fail("expected 'event: error' as the first line, got {!r}".format(lines[:2]))
        return
    data_lines = [ln[len("data: "):] for ln in lines if ln.startswith("data: ")]
    if not data_lines:
        fail("no data line in the degraded frame: {!r}".format(text[:200]))
        return
    try:
        env = json.loads(data_lines[0])
    except Exception as e:
        fail("degraded frame data is not JSON: {} ({!r})".format(e, data_lines[0][:200]))
        return
    err = env.get("error") if isinstance(env, dict) else None
    if not isinstance(err, dict):
        fail("degraded frame has no error object: {!r}".format(env))
        return
    if err.get("code") != "response_frame_encode_failure":
        fail("expected error.code response_frame_encode_failure, got {!r}".format(err))
        return
    if err.get("type") != "api_error":
        fail("expected error.type api_error, got {!r}".format(err))
        return
    if env.get("request_id") != "req-unserializable-test":
        fail("request_id not threaded into the degraded frame, got {!r}".format(
            env.get("request_id")))
        return
    pass_("unserializable payload -> event: error with "
          "response_frame_encode_failure")


def test_choices_non_list_degrades_frame():
    """A frame whose `choices` is a dict (not a list) is skipped without
    raising; the stream continues and closes normally (Step 1 shape guard).

    Before the guard, `choices = chunk.get("choices")` returning a dict made
    `choices[0]` raise KeyError mid-stream, past except _DISCONNECT_ERRORS,
    into do_POST's total guard after response headers were committed.
    """
    print("\n--- Test: Chat SSE Choices Non-List Degrades Frame ---")
    bad = {"id": "c1", "object": "chat.completion.chunk", "created": 1,
           "model": "gpt-4o", "choices": {"delta": {}}}
    chunks = [_cc({"role": "assistant", "content": "hi"}),
              bad,
              _cc({}, finish="stop")]
    proxy_port, trace_file, cleanup = _start_chat_sse_proxy(chunks)
    if proxy_port is None:
        return
    try:
        frames = _chat_sse_fetch_frames(proxy_port)
        if frames is None:
            return
        if "error" in _sse_types(frames):
            fail("a malformed choices frame must be skipped, not surfaced as an error")
            return
        if _sse_stop_reason(frames) != "end_turn":
            fail("the stream must close normally past a malformed choices frame, "
                 "got stop_reason {!r}".format(_sse_stop_reason(frames)))
            return
        deltas = _sse_frames_with_type(frames, "content_block_delta")
        text_bits = [d.get("delta", {}).get("text") for d in deltas
                     if isinstance(d.get("delta", {}).get("text"), str)]
        if text_bits != ["hi"]:
            fail("the content before the degraded frame must still stream, got {!r}".format(text_bits))
            return
        pass_("non-list choices frame skipped; the stream continues and closes normally")
    finally:
        cleanup()


def test_choices_non_dict_element_degrades_frame():
    """A frame whose `choices[0]` is a non-dict (e.g. a string) is skipped
    without raising (Step 1 shape guard).

    Before the guard, `choice.get("delta")` on a str raised AttributeError
    mid-stream.
    """
    print("\n--- Test: Chat SSE Choices Non-Dict Element Degrades Frame ---")
    bad = {"id": "c1", "object": "chat.completion.chunk", "created": 1,
           "model": "gpt-4o", "choices": ["x"]}
    chunks = [_cc({"role": "assistant", "content": "hi"}),
              bad,
              _cc({}, finish="stop")]
    proxy_port, trace_file, cleanup = _start_chat_sse_proxy(chunks)
    if proxy_port is None:
        return
    try:
        frames = _chat_sse_fetch_frames(proxy_port)
        if frames is None:
            return
        if "error" in _sse_types(frames):
            fail("a non-dict choices element must be skipped, not surfaced as an error")
            return
        if _sse_stop_reason(frames) != "end_turn":
            fail("the stream must close normally past a non-dict choices element, "
                 "got stop_reason {!r}".format(_sse_stop_reason(frames)))
            return
        deltas = _sse_frames_with_type(frames, "content_block_delta")
        text_bits = [d.get("delta", {}).get("text") for d in deltas
                     if isinstance(d.get("delta", {}).get("text"), str)]
        if text_bits != ["hi"]:
            fail("the content before the degraded frame must still stream, got {!r}".format(text_bits))
            return
        pass_("non-dict choices element skipped; the stream continues and closes normally")
    finally:
        cleanup()


def test_choices_none_element_still_degrades_harmlessly():
    """A frame with a `None` choices element still behaves as today: the
    `choices[0] or {}` idiom yields an empty delta and no raise (Step 1).

    Kept as a alongside-the-guard assertion: the new isinstance(choice, dict)
    check must not reject the harmless None element that already degraded.
    """
    print("\n--- Test: Chat SSE Choices None Element Still Degrades Harmlessly ---")
    bad = {"id": "c1", "object": "chat.completion.chunk", "created": 1,
           "model": "gpt-4o", "choices": [None]}
    chunks = [_cc({"role": "assistant", "content": "hi"}),
              bad,
              _cc({}, finish="stop")]
    proxy_port, trace_file, cleanup = _start_chat_sse_proxy(chunks)
    if proxy_port is None:
        return
    try:
        frames = _chat_sse_fetch_frames(proxy_port)
        if frames is None:
            return
        if "error" in _sse_types(frames):
            fail("a None choices element must degrade harmlessly, not surface an error")
            return
        if _sse_stop_reason(frames) != "end_turn":
            fail("the stream must close normally past a None choices element, "
                 "got stop_reason {!r}".format(_sse_stop_reason(frames)))
            return
        deltas = _sse_frames_with_type(frames, "content_block_delta")
        text_bits = [d.get("delta", {}).get("text") for d in deltas
                     if isinstance(d.get("delta", {}).get("text"), str)]
        if text_bits != ["hi"]:
            fail("the content before the degraded frame must still stream, got {!r}".format(text_bits))
            return
        pass_("None choices element degrades harmlessly; the stream closes normally")
    finally:
        cleanup()


def test_coalesced_finish_tail_counted_as_late_frames():
    """A finish frame and a trailing usage frame sharing one coalesced read
    chunk count as late frames with a ~0 offset (Step 3a discovery capture).

    The chunk is injected structurally — one pre-built iter_raw chunk carrying
    content + finish + usage + [DONE] — never inferred from TCP flush
    coalescing. Because every frame shares the read, the chunk-top capture ran
    before the finish was discovered; before Step 3a the post-loop accounting
    never saw the tail and reported late_frames 0 with null offsets. The
    [DONE] sentinel is excluded (Step 3b), so only the usage frame counts. The
    assertions mirror test_chat_sse_drain_late_tool_call_time_budget's window
    checks so the two late-frame branches stay consistent.
    """
    print("\n--- Test: Chat SSE Coalesced Finish Tail Counted As Late Frames ---")
    usage_tail = {"id": "c1", "object": "chat.completion.chunk", "created": 1,
                  "model": "gpt-4o", "choices": [],
                  "usage": {"prompt_tokens": 3, "completion_tokens": 2,
                            "total_tokens": 5}}
    sse_body = _sse_stream_chunks([_cc({"role": "assistant", "content": "hi"}),
                                   _cc({}, finish="stop"),
                                   usage_tail]) + b"data: [DONE]\n\n"
    root = tempfile.mkdtemp(prefix="proxy_chatsse_coalesced_")
    trace_file = os.path.join(root, "trace.jsonl")
    try:
        raw = _stream_chat_sse_in_one_read(sse_body, trace_file)
        frames = _parse_sse_frames(raw)
        if _sse_stop_reason(frames) != "end_turn":
            fail("the coalesced-tail stream must map stop to end_turn, got {!r}".format(
                _sse_stop_reason(frames)))
            return
        events = _trace_events_named(trace_file, "chat_sse_drain")
        if len(events) != 1:
            fail("expected exactly one chat_sse_drain event, got {}".format(len(events)))
            return
        ev = events[0]
        if not ev.get("late_frames") or ev.get("late_frames") < 1:
            fail("a coalesced finish+tail chunk must count late_frames >= 1 "
                 "(pre-fix reported 0), got {!r}".format(ev.get("late_frames")))
            return
        _first_late = ev.get("first_late_ms")
        _last_late = ev.get("last_late_ms")
        if _first_late != 0:
            fail("same-chunk late frames must report first_late_ms 0 (finish_seen_at "
                 "set one line earlier), got {!r}".format(_first_late))
            return
        if _last_late is None:
            fail("last_late_ms must be populated for a coalesced tail, got None")
            return
        pass_("coalesced finish+usage tail: late_frames {} first_late_ms {} "
              "last_late_ms {}".format(ev.get("late_frames"), _first_late, _last_late))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_true_no_tail_still_reports_null():
    """Control: the coalesced content+finish+[DONE]-only shape (no usage/tool
    tail) still reports late_frames 0 and null offsets (Step 3b).

    The [DONE] sentinel is not a frame that followed the finish signal, so a
    stream that ended at the finish frame attributes no late frame — the
    documented null-case semantics hold after both Step 3 edits.
    """
    print("\n--- Test: Chat SSE True No-Tail Still Reports Null ---")
    chunks = [_cc({"role": "assistant", "content": "hi"}),
              _cc({}, finish="stop")]
    proxy_port, trace_file, cleanup = _start_chat_sse_proxy(chunks)  # + [DONE], single write
    if proxy_port is None:
        return
    try:
        frames = _chat_sse_fetch_frames(proxy_port)
        if frames is None:
            return
        if _sse_stop_reason(frames) != "end_turn":
            fail("the no-tail stream must map stop to end_turn, got {!r}".format(
                _sse_stop_reason(frames)))
            return
        events = _wait_for_trace_events(trace_file, "chat_sse_drain")
        if len(events) != 1:
            fail("expected exactly one chat_sse_drain event, got {}".format(len(events)))
            return
        ev = events[0]
        if ev.get("late_frames"):
            fail("a finish+[DONE]-only chunk must not count a late frame, "
                 "got {!r}".format(ev.get("late_frames")))
            return
        if ev.get("first_late_ms") is not None or ev.get("last_late_ms") is not None:
            fail("no frame followed the finish signal: first_late_ms/last_late_ms "
                 "must both be null, got {!r}/{!r}".format(
                     ev.get("first_late_ms"), ev.get("last_late_ms")))
            return
        pass_("coalesced finish+[DONE]-only stream: late_frames 0, null offsets")
    finally:
        cleanup()


def _inband_usage_frame_bytes():
    """Finish-frame JSON built as BYTES with a non-int usage value.

    A dict at usage.prompt_tokens is the shape that used to be copied
    verbatim into the message_delta payload; it is shallow, so the fixture
    keeps the coverage independent of any interpreter recursion profile.
    """
    return (
        b'{"id": "c1", "object": "chat.completion.chunk", "created": 1, '
        b'"model": "gpt-4o", '
        b'"choices": [{"index": 0, "delta": {"content": "hi"}, '
        b'"finish_reason": "stop"}], '
        b'"usage": {"prompt_tokens": {"nested": 1}, "completion_tokens": 7}}')


def _stream_chat_sse_in_one_read(sse_body, trace_file):
    """Drive the chat SSE transform in-process with ONE injected iter_raw chunk.

    A real socket's read boundaries are transport accidents, so the
    spawned-proxy fixtures cannot request a coalesced finish+tail read — they
    can only hope the kernel delivers one. Injecting one pre-built chunk makes
    the coalesced shapes structural, so timestamp assertions never ride on TCP
    flush coalescing (the plan's fixture discipline).

    The handler double is a real ProxyHandler created without
    BaseHTTPRequestHandler.__init__ — the transform touches only `_sse_event`
    and `wfile`. The trace sink is rebound to `trace_file` for the synchronous
    call and the previous sink object restored afterwards (the sinks hold
    their own path, so assigning a module-level path would be inert).
    """
    from claude_retry_proxy import sinks
    from claude_retry_proxy.server import ProxyHandler

    class _OneChunkResponse:
        def iter_raw(self):
            yield sse_body

    handler = object.__new__(ProxyHandler)
    handler.wfile = io.BytesIO()
    prev_trace_sink = sinks._trace
    try:
        sinks.configure(trace_path=trace_file)
        handler._stream_chat_sse_to_anthropic(
            _OneChunkResponse(), "coalesced-fixture", "sonnet",
            time.time(), None)
    finally:
        sinks._trace = prev_trace_sink
    return handler.wfile.getvalue()


ALL_TESTS = [
    ("chat-sse-basic-streaming", test_chat_sse_basic_streaming),
    ("chat-sse-finish-reason-mapping", test_chat_sse_finish_reason_mapping),
    ("chat-sse-no-content-delta", test_chat_sse_no_content_delta),
    ("chat-sse-empty-choices-usage-chunk", test_chat_sse_empty_choices_usage_chunk),
    ("chat-sse-first-event-has-content", test_chat_sse_first_event_has_content),
    ("chat-sse-injection-prevented", test_chat_sse_injection_prevented),
    ("chat-sse-event-line-present", test_chat_sse_event_line_present),
    ("chat-sse-reasoning-delta-to-thinking-delta", test_chat_sse_reasoning_delta_to_thinking_delta),
    ("chat-sse-reasoning-delta-no-content", test_chat_sse_reasoning_delta_no_content),
    ("chat-sse-reasoning-then-text-transition", test_chat_sse_reasoning_then_text_transition),
    ("chat-sse-usage-after-finish-reason", test_chat_sse_usage_after_finish_reason),
    ("chat-sse-stream-options-include-usage", test_chat_sse_stream_options_include_usage),
    ("chat-sse-inband-usage-terminal", test_chat_sse_inband_usage_terminal),
    ("sse-event-unserializable-payload-degrades", test_sse_event_unserializable_payload_degrades),
    # Deferred chat_sse defects (plan 2026-11-20-chat-sse-deferred-fixes, Step 4)
    ("chat-sse-choices-non-list-degrades-frame", test_choices_non_list_degrades_frame),
    ("chat-sse-choices-non-dict-element-degrades-frame", test_choices_non_dict_element_degrades_frame),
    ("chat-sse-choices-none-element-still-degrades-harmlessly", test_choices_none_element_still_degrades_harmlessly),
    ("chat-sse-coalesced-finish-tail-counted-as-late-frames", test_coalesced_finish_tail_counted_as_late_frames),
    ("chat-sse-true-no-tail-still-reports-null", test_true_no_tail_still_reports_null),
]


if __name__ == "__main__":
    run_cli(ALL_TESTS, "claude-retry-proxy tests: test_chat_sse")
