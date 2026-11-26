"""Chat-mode tool-call synthesis, degradation and nesting-limit tests.

Part of the claude-retry-proxy suite; runnable standalone.
"""

import json
from _harness import (
    _assert_degradation_metadata_only,
    _cc,
    _chat_sse_fetch_frames,
    _degraded_trace_events,
    _mode_tiers,
    _sse_content_block_starts,
    _sse_frame_type,
    _sse_frames_with_type,
    _sse_stop_reason,
    _sse_stream_chunks,
    _sse_tool_use_blocks,
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
from claude_retry_proxy.nesting import MAX_JSON_NESTING_DEPTH


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
        # Valid arguments must never count as unparseable (no false positives)
        # at the length (non-finish-disposition-independent) close site.
        if events[0].get("unparseable_arg_count") != 0:
            fail("valid arguments must count unparseable_arg_count 0 at the "
                 "length disposition, got {!r}".format(events[0].get("unparseable_arg_count")))
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
        events2 = _degraded_trace_events(trace_file2)
        if len(events2) != 1:
            fail("stop finish with open tool blocks must log the coalesced event, got {}".format(len(events2)))
            return
        if events2[0].get("unparseable_arg_count") != 0:
            fail("valid arguments must count unparseable_arg_count 0 at the "
                 "stop disposition, got {!r}".format(events2[0].get("unparseable_arg_count")))
            return
    finally:
        cleanup2()
    # Invalid-arguments variant: the emitted-tool_use disposition must validate
    # too, so the degradation counter is finish-disposition-independent. Before
    # the Step 2 fix (validate=False here) this path structurally reported 0.
    invalid = [
        _cc({"role": "assistant"}),
        _cc({"tool_calls": [{"index": 0, "id": "call_bad", "function": {"name": "bad_tool", "arguments": "{oops"}}]}),
    ]
    proxy_port3, trace_file3, cleanup3 = _start_chat_sse_proxy(invalid + [_cc({}, finish="stop")])
    if proxy_port3 is None:
        return
    try:
        frames3 = _chat_sse_fetch_frames(proxy_port3)
        if frames3 is None:
            return
        blocks3 = _sse_tool_use_blocks(frames3)
        if len(blocks3) != 1 or not blocks3[0]["closed"]:
            fail("stop finish with an unparseable-args tool block must still close it, got {!r}".format(blocks3))
            return
        if _sse_stop_reason(frames3) != "tool_use":
            fail("stop finish with emitted tool blocks must upgrade to tool_use "
                 "even with unparseable args, got {!r}".format(_sse_stop_reason(frames3)))
            return
        events3 = _degraded_trace_events(trace_file3)
        if len(events3) != 1:
            fail("unparseable-args stop finish must log the coalesced event, got {}".format(len(events3)))
            return
        if events3[0].get("unparseable_arg_count", 0) < 1:
            fail("the degradation counter must be finish-disposition-independent: "
                 "unparseable args at the stop disposition must count at least 1, "
                 "got {!r}".format(events3[0].get("unparseable_arg_count")))
            return
    finally:
        cleanup3()
    pass_("non-tool_calls finish with open tool blocks: close blocks, map/upgrade "
          "finish, log event; degradation counter validates at both dispositions")


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


def test_chat_sse_nesting_limit_frame_skipped():
    """A chat frame past the nesting limit is skipped, and the stream completes.

    The boundary check runs before handle_frame's json.loads: a frame nested
    past MAX_JSON_NESTING_DEPTH is refused unparsed (site "chat_frame") rather
    than raising out of the request path, and the rest of the stream flows
    normally. It deliberately does NOT emit chat_sse_malformed_json — the
    frame is well formed, just too deep — so this test also carries a shallow
    UNPARSEABLE frame and pins that the pre-existing malformed-JSON skip still
    fires for it. That event's only remaining coverage is here; a rewrite that
    asserted the nesting case only through chat_sse_malformed_json would leave
    the distinction unpinned.
    """
    print("\n--- Test: Chat SSE Nesting-Limit Frame Skipped ---")

    limit = MAX_JSON_NESTING_DEPTH
    deep_frame = b"data: " + b"[" * (limit + 1) + b"]" * (limit + 1) + b"\n\n"
    malformed_frame = b"data: {not json\n\n"
    sse_body = (deep_frame + malformed_frame
                + _sse_stream_chunks([
                    _cc({"role": "assistant"}),
                    _cc({"content": "ok"}),
                    _cc({}, finish="stop"),
                ]) + b"data: [DONE]\n\n")

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
            fail("the >limit frame dropped the connection or returned non-200")
            return
        types = _sse_types(frames)
        if "message_stop" not in types:
            fail("stream did not complete after a skipped >limit frame: {}".format(types))
            return
        if _sse_stop_reason(frames) != "end_turn":
            fail("expected end_turn after recovery, got {!r}".format(
                _sse_stop_reason(frames)))
            return
        events = _wait_for_trace_events(trace_file, "nesting_limit_exceeded")
        frame_events = [e for e in events if e.get("site") == "chat_frame"]
        if len(frame_events) != 1:
            fail("expected one nesting event with site chat_frame, got {!r}".format(events))
            return
        if frame_events[0].get("depth", 0) < limit + 1:
            fail("chat_frame event depth {} is not past the limit {}".format(
                frame_events[0].get("depth"), limit))
            return
        if frame_events[0].get("tier") != "sonnet":
            fail("the chat_frame event must carry the tier, got {!r}".format(
                frame_events[0].get("tier")))
            return
        malformed = _wait_for_trace_events(trace_file, "chat_sse_malformed_json")
        if len(malformed) != 1:
            fail("expected exactly one chat_sse_malformed_json event for the "
                 "shallow unparseable frame, got {!r}".format(malformed))
            return
        pass_(">limit frame skipped (site chat_frame); the shallow malformed frame "
              "still logs chat_sse_malformed_json; stream completed")
    finally:
        cleanup()


def test_chat_sse_nesting_limit_tool_args_at_close():
    """Tool arguments nested past the limit degrade at close, not fatal.

    The deep content rides inside a JSON *string*, so the frame itself is
    shallow and no outer body scan can see it: the check lives at the
    accumulated-arguments parse in close_open_tool_blocks. Post-fix the call
    counts as unparseable (the existing placeholder/stop-reason path) and the
    stream completes with the emitted tool block, plus the nesting event at
    site "tool_args".
    """
    print("\n--- Test: Chat SSE Nesting-Limit Tool Args At Close ---")

    limit = MAX_JSON_NESTING_DEPTH
    deep_args = "[" * (limit + 1) + "]" * (limit + 1)

    chunks = [
        _cc({"role": "assistant"}),
        _cc({"tool_calls": [{"index": 0, "id": "call_deep",
                             "function": {"name": "deep_tool", "arguments": deep_args}}]}),
        _cc({}, finish="tool_calls"),
    ]
    proxy_port, trace_file, cleanup = _start_chat_sse_proxy(chunks)
    if proxy_port is None:
        return
    try:
        frames = _chat_sse_fetch_frames(proxy_port)
        if frames is None:
            fail(">limit tool arguments dropped the connection")
            return
        blocks = _sse_tool_use_blocks(frames)
        if len(blocks) != 1 or not blocks[0]["closed"]:
            fail("a >limit-args tool block should still be emitted and closed, "
                 "got {!r}".format(blocks))
            return
        if _sse_stop_reason(frames) != "tool_use":
            fail("expected tool_use, got {!r}".format(_sse_stop_reason(frames)))
            return
        events = _wait_for_trace_events(trace_file, "chat_sse_tool_degradation")
        if len(events) != 1 or events[0].get("unparseable_arg_count") != 1:
            fail("expected one degradation event with unparseable_arg_count 1, "
                 "got {!r}".format(events))
            return
        nesting = [e for e in _wait_for_trace_events(trace_file, "nesting_limit_exceeded")
                   if e.get("site") == "tool_args"]
        if len(nesting) != 1:
            fail("expected one nesting event with site tool_args, got {!r}".format(
                _wait_for_trace_events(trace_file, "nesting_limit_exceeded")))
            return
        if nesting[0].get("depth", 0) < limit + 1:
            fail("tool_args event depth {} is not past the limit {}".format(
                nesting[0].get("depth"), limit))
            return
        if nesting[0].get("tier") != "sonnet":
            fail("the tool_args event must carry the tier, got {!r}".format(
                nesting[0].get("tier")))
            return
        pass_(">limit args unparseable at close; block emitted, tool_use, "
              "degradation + tool_args nesting event")
    finally:
        cleanup()


ALL_TESTS = [
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
    ("chat-mode-streamed-tool-command-e2e", test_chat_mode_streamed_tool_command_e2e),
    ("chat-sse-tool-degradation-on-cut-stream", test_chat_sse_tool_degradation_on_cut_stream),
    ("chat-sse-nesting-limit-frame-skipped", test_chat_sse_nesting_limit_frame_skipped),
    ("chat-sse-nesting-limit-tool-args-at-close", test_chat_sse_nesting_limit_tool_args_at_close),
]


if __name__ == "__main__":
    run_cli(ALL_TESTS, "claude-retry-proxy tests: test_chat_sse_tools")
