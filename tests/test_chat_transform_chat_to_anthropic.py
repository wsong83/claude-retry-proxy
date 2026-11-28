"""Chat-to-Anthropic response-conversion tests: content/usage/stop_reason
mapping, reasoning_content recognition, tool-call degradation to the
visible placeholder, and the nesting-limit guards."""

import json
import os
import unittest.mock
import uuid
from _harness import _require_server_func, fail, pass_, run_cli
from claude_retry_proxy.nesting import MAX_JSON_NESTING_DEPTH


# --- Step 5: _chat_to_anthropic ---

def test_chat_to_anthropic_basic():
    """content, model, stop_reason, usage mapped correctly."""
    print("\n--- Test: Chat To Anthropic Basic ---")
    fn = _require_server_func("_chat_to_anthropic")
    if fn is None:
        return
    chat = {"id": "chatcmpl-123", "object": "chat.completion", "model": "gpt-4o",
            "choices": [{"index": 0,
                         "message": {"role": "assistant", "content": "Hello"},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8}}
    out = fn(chat, "sonnet")
    if not isinstance(out, dict):
        fail("_chat_to_anthropic must return a dict")
        return
    checks = [
        (out.get("id") == "msg_chatcmpl-123", "id prefixed with msg_"),
        (out.get("model") == "sonnet", "model rewritten to tier"),
        (out.get("type") == "message", "type hardcoded to message"),
        (out.get("role") == "assistant", "role hardcoded to assistant"),
        (out.get("content") == [{"type": "text", "text": "Hello"}], "content string wrapped"),
        (out.get("stop_reason") == "end_turn", "stop->end_turn"),
        (out.get("stop_sequence") is None, "stop_sequence null"),
        (out.get("usage") == {"input_tokens": 5, "output_tokens": 3}, "usage mapped"),
    ]
    for ok, label in checks:
        if not ok:
            fail("basic mapping failed: {} (out={!r})".format(label, out))
    if all(ok for ok, _ in checks):
        pass_("chat->anthropic basic mapping correct")


def test_chat_to_anthropic_reasoning_content_to_thinking():
    """reasoning_content in the chat message becomes a thinking block first in content."""
    print("\n--- Test: Chat To Anthropic Reasoning Content To Thinking ---")
    fn = _require_server_func("_chat_to_anthropic")
    if fn is None:
        return
    chat = {"id": "c1", "model": "gpt-4o",
            "choices": [{"index": 0,
                         "message": {"role": "assistant", "content": "Answer",
                                     "reasoning_content": "Let me think"},
                         "finish_reason": "stop"}]}
    out = fn(chat, "sonnet")
    content = out.get("content") if isinstance(out, dict) else None
    expected = [
        {"type": "thinking", "thinking": "Let me think", "signature": ""},
        {"type": "text", "text": "Answer"},
    ]
    if content != expected:
        fail("reasoning_content should become a thinking block first, got content={!r}".format(content))
        return
    if not isinstance(content, list) or content[0].get("type") != "thinking" \
            or content[0].get("signature") != "":
        fail("thinking block must carry signature:'', got {!r}".format(content))
        return
    pass_("reasoning_content -> thinking block first with signature:''")


def test_chat_to_anthropic_reasoning_field_compat():
    """vLLM 'reasoning' field is also recognized; reasoning_content wins when both present."""
    print("\n--- Test: Chat To Anthropic Reasoning Field Compat ---")
    fn = _require_server_func("_chat_to_anthropic")
    if fn is None:
        return
    # 'reasoning' alone (vLLM compat)
    chat = {"id": "c1", "model": "gpt-4o",
            "choices": [{"index": 0,
                         "message": {"role": "assistant", "content": "A",
                                     "reasoning": "vllm-reason"},
                         "finish_reason": "stop"}]}
    out = fn(chat, "sonnet")
    content = out.get("content") if isinstance(out, dict) else None
    if content != [{"type": "thinking", "thinking": "vllm-reason", "signature": ""},
                   {"type": "text", "text": "A"}]:
        fail("reasoning field (vLLM) should map to thinking block, got {!r}".format(content))
        return
    # Both present: reasoning_content wins
    chat2 = {"id": "c2", "model": "gpt-4o",
             "choices": [{"index": 0,
                          "message": {"role": "assistant", "content": "A",
                                      "reasoning_content": "rc", "reasoning": "r"},
                          "finish_reason": "stop"}]}
    out2 = fn(chat2, "sonnet")
    content2 = out2.get("content") if isinstance(out2, dict) else None
    if content2 != [{"type": "thinking", "thinking": "rc", "signature": ""},
                    {"type": "text", "text": "A"}]:
        fail("reasoning_content must take precedence over reasoning, got {!r}".format(content2))
        return
    pass_("reasoning field recognized; reasoning_content wins precedence")


def test_chat_to_anthropic_reasoning_content_empty():
    """Empty reasoning_content produces no thinking block."""
    print("\n--- Test: Chat To Anthropic Reasoning Content Empty ---")
    fn = _require_server_func("_chat_to_anthropic")
    if fn is None:
        return
    chat = {"id": "c1", "model": "gpt-4o",
            "choices": [{"index": 0,
                         "message": {"role": "assistant", "content": "A",
                                     "reasoning_content": ""},
                         "finish_reason": "stop"}]}
    out = fn(chat, "sonnet")
    content = out.get("content") if isinstance(out, dict) else None
    if content != [{"type": "text", "text": "A"}]:
        fail("empty reasoning_content should emit no thinking block, got {!r}".format(content))
        return
    # Non-string reasoning_content is also skipped
    chat2 = {"id": "c2", "model": "gpt-4o",
             "choices": [{"index": 0,
                          "message": {"role": "assistant", "content": "A",
                                      "reasoning_content": None},
                          "finish_reason": "stop"}]}
    out2 = fn(chat2, "sonnet")
    content2 = out2.get("content") if isinstance(out2, dict) else None
    if content2 != [{"type": "text", "text": "A"}]:
        fail("non-string reasoning_content should be skipped, got {!r}".format(content2))
        return
    pass_("empty/non-string reasoning_content emits no thinking block")


def test_chat_to_anthropic_reasoning_content_with_tool_calls():
    """reasoning_content + tool_calls -> thinking block first, then tool_use blocks."""
    print("\n--- Test: Chat To Anthropic Reasoning Content With Tool Calls ---")
    fn = _require_server_func("_chat_to_anthropic")
    if fn is None:
        return
    chat = {"id": "c1", "model": "gpt-4o",
            "choices": [{"index": 0,
                         "message": {"role": "assistant", "content": None,
                                     "reasoning_content": "thinking",
                                     "tool_calls": [
                                         {"id": "call_1", "type": "function",
                                          "function": {"name": "get_weather",
                                                       "arguments": '{"city": "SF"}'}}]},
                         "finish_reason": "tool_calls"}]}
    out = fn(chat, "sonnet")
    content = out.get("content") if isinstance(out, dict) else None
    expected = [
        {"type": "thinking", "thinking": "thinking", "signature": ""},
        {"type": "tool_use", "id": "call_1", "name": "get_weather", "input": {"city": "SF"}},
    ]
    if content != expected:
        fail("reasoning_content + tool_calls should be thinking first then tool_use, got {!r}".format(content))
        return
    if out.get("stop_reason") != "tool_use":
        fail("tool_calls finish_reason should map to stop_reason tool_use, got {!r}".format(out.get("stop_reason")))
        return
    pass_("reasoning_content + tool_calls -> thinking block then tool_use blocks")


def test_chat_to_anthropic_empty_choices():
    """Empty choices returns a minimal valid Anthropic message."""
    print("\n--- Test: Chat To Anthropic Empty Choices ---")
    fn = _require_server_func("_chat_to_anthropic")
    if fn is None:
        return
    chat = {"id": "chatcmpl-1", "choices": [], "model": "gpt-4o"}
    out = fn(chat, "sonnet")
    if not isinstance(out, dict):
        fail("empty choices must still return a dict")
        return
    if out.get("type") != "message":
        fail("minimal response missing type=message")
    if out.get("role") != "assistant":
        fail("minimal response missing role=assistant")
    if out.get("model") != "sonnet":
        fail("minimal response missing model=tier")
    if out.get("content") != []:
        fail("minimal response expected content=[], got {!r}".format(out.get("content")))
    if out.get("type") == "message" and out.get("role") == "assistant" and out.get("content") == []:
        pass_("empty choices returns minimal valid message")


def test_chat_to_anthropic_tool_calls():
    """tool_calls map to tool_use content blocks."""
    print("\n--- Test: Chat To Anthropic Tool Calls ---")
    fn = _require_server_func("_chat_to_anthropic")
    if fn is None:
        return
    chat = {"id": "chatcmpl-1",
            "choices": [{"index": 0,
                         "message": {"role": "assistant", "content": "",
                                     "tool_calls": [
                                         {"id": "call_1", "type": "function",
                                          "function": {"name": "get_weather",
                                                       "arguments": '{"city": "SF"}'}}]},
                         "finish_reason": "tool_calls"}]}
    out = fn(chat, "sonnet")
    content = out.get("content") if isinstance(out.get("content"), list) else []
    tools = [b for b in content if b.get("type") == "tool_use"]
    if not tools:
        fail("expected a tool_use content block, content={!r}".format(out.get("content")))
        return
    t = tools[0]
    if t.get("name") != "get_weather":
        fail("tool_use name mismatch: {!r}".format(t.get("name")))
    if t.get("input") != {"city": "SF"}:
        fail("tool_use input mismatch: {!r}".format(t.get("input")))
    if t.get("id") != "call_1":
        fail("tool_use id mismatch: {!r}".format(t.get("id")))
    if out.get("stop_reason") != "tool_use":
        fail("finish_reason tool_calls should map to stop_reason tool_use, got {!r}".format(out.get("stop_reason")))
    if tools and t.get("name") == "get_weather" and t.get("input") == {"city": "SF"}:
        pass_("tool_calls mapped to tool_use blocks")


def test_chat_to_anthropic_finish_reason_mapping():
    """All finish_reason values map to the correct stop_reason."""
    print("\n--- Test: Chat To Anthropic Finish Reason Mapping ---")
    fn = _require_server_func("_chat_to_anthropic")
    if fn is None:
        return
    cases = [("stop", "end_turn"), ("length", "max_tokens"),
             ("content_filter", None), ("weird_thing", None)]
    ok = True
    for fr, expected in cases:
        chat = {"id": "x", "choices": [{"index": 0,
                                        "message": {"role": "assistant", "content": "hi"},
                                        "finish_reason": fr}]}
        out = fn(chat, "sonnet")
        actual = out.get("stop_reason")
        if actual != expected:
            fail("finish_reason {!r} -> stop_reason {!r}, expected {!r}".format(fr, actual, expected))
            ok = False
    # finish_reason 'tool_calls' only maps to 'tool_use' when a tool_use block
    # is actually emitted (Step 6a: null/absent tool_calls must not claim
    # tool_use, or the client hangs waiting for tool_use blocks).
    chat_tool = {"id": "x", "choices": [{"index": 0,
                                         "message": {"role": "assistant", "content": "hi",
                                                     "tool_calls": [
                                                         {"id": "call_1", "type": "function",
                                                          "function": {"name": "f", "arguments": '{"city": "SF"}'}}]},
                                         "finish_reason": "tool_calls"}]}
    out = fn(chat_tool, "sonnet")
    if out.get("stop_reason") != "tool_use":
        fail("finish_reason 'tool_calls' with emitted tool_use -> stop_reason {!r}, expected 'tool_use'".format(out.get("stop_reason")))
        ok = False
    chat_null_tc = {"id": "x", "choices": [{"index": 0,
                                            "message": {"role": "assistant", "content": "hi",
                                                        "tool_calls": None},
                                            "finish_reason": "tool_calls"}]}
    out = fn(chat_null_tc, "sonnet")
    if out.get("stop_reason") is not None:
        fail("null tool_calls + finish_reason 'tool_calls' -> stop_reason {!r}, expected None".format(out.get("stop_reason")))
        ok = False
    chat_missing = {"id": "x", "choices": [{"index": 0, "message": {"role": "assistant", "content": "hi"}}]}
    out = fn(chat_missing, "sonnet")
    if out.get("stop_reason") is not None:
        fail("missing finish_reason should map to null, got {!r}".format(out.get("stop_reason")))
        ok = False
    if ok:
        pass_("finish_reason->stop_reason mapping correct")


def test_chat_to_anthropic_usage_absent():
    """Missing usage maps to zero input/output tokens."""
    print("\n--- Test: Chat To Anthropic Usage Absent ---")
    fn = _require_server_func("_chat_to_anthropic")
    if fn is None:
        return
    chat = {"id": "x", "choices": [{"index": 0,
                                    "message": {"role": "assistant", "content": "hi"},
                                    "finish_reason": "stop"}]}
    out = fn(chat, "sonnet")
    if out.get("usage") != {"input_tokens": 0, "output_tokens": 0}:
        fail("expected usage {input_tokens:0, output_tokens:0}, got {!r}".format(out.get("usage")))
    else:
        pass_("missing usage handled with zero defaults")


def test_chat_to_anthropic_content_array():
    """Array content blocks map individually."""
    print("\n--- Test: Chat To Anthropic Content Array ---")
    fn = _require_server_func("_chat_to_anthropic")
    if fn is None:
        return
    chat = {"id": "x", "choices": [{"index": 0,
                                    "message": {"role": "assistant", "content": [
                                        {"type": "text", "text": "part1"},
                                        {"type": "text", "text": "part2"}]},
                                    "finish_reason": "stop"}]}
    out = fn(chat, "sonnet")
    expected = [{"type": "text", "text": "part1"}, {"type": "text", "text": "part2"}]
    if out.get("content") != expected:
        fail("array content not preserved: {!r}".format(out.get("content")))
    else:
        pass_("array content mapped block by block")


def test_chat_to_anthropic_malformed_tool_args_text_block():
    """Malformed tool args degrade to a text block, not a tool_use with input {}.

    Option C (plan 2026-08-28-thread-request-id-to-transform-functions):
    when tool arguments cannot produce a valid dict, emit a text block
    "[Tool call failed: arguments for '<name>' (call <id>) could not be
    parsed as JSON]" instead of a tool_use block with input {}. stop_reason
    is forced to None when no tool_use block is emitted. The transform also
    accepts request_id, mode, provider kwargs.
    """
    print("\n--- Test: Chat To Anthropic Malformed Tool Args Text Block ---")
    fn = _require_server_func("_chat_to_anthropic")
    if fn is None:
        return
    cases = [
        # (label, arguments value)
        ("string-fails-json", "{not json"),
        ("string-parses-to-non-dict-int", "42"),
        ("string-parses-to-non-dict-array", "[1,2]"),
        ("non-string-null", None),
    ]
    for label, args_val in cases:
        chat = {"id": "x",
                "choices": [{"index": 0,
                             "message": {"role": "assistant", "content": "",
                                         "tool_calls": [
                                             {"id": "call_1", "type": "function",
                                              "function": {"name": "f", "arguments": args_val}}]},
                             "finish_reason": "tool_calls"}]}
        out = fn(chat, "sonnet", request_id="R1", mode="chat", provider="p")
        content = out.get("content") if isinstance(out.get("content"), list) else []
        tools = [b for b in content if b.get("type") == "tool_use"]
        if tools:
            fail("[{}] malformed args should NOT emit a tool_use block, content={!r}".format(label, content))
            continue
        text_blocks = [b for b in content if b.get("type") == "text"]
        if not any("f" in (b.get("text") or "") and "call_1" in (b.get("text") or "")
                   for b in text_blocks):
            fail("[{}] expected a text block naming tool 'f' and call 'call_1', content={!r}".format(label, content))
            continue
        if out.get("stop_reason") is not None:
            fail("[{}] all-malformed tool calls should force stop_reason None, got {!r}".format(label, out.get("stop_reason")))
            continue
    # Non-dict parses to a valid dict (no dict -> dict is fine) is NOT a failure.
    chat_ok = {"id": "x",
               "choices": [{"index": 0,
                            "message": {"role": "assistant", "content": "",
                                        "tool_calls": [
                                            {"id": "call_1", "type": "function",
                                             "function": {"name": "f", "arguments": '{"city": "SF"}'}}]},
                            "finish_reason": "tool_calls"}]}
    out_ok = fn(chat_ok, "sonnet", request_id="R2", mode="chat", provider="p")
    tools_ok = [b for b in (out_ok.get("content") or []) if b.get("type") == "tool_use"]
    if not tools_ok or tools_ok[0].get("input") != {"city": "SF"} or out_ok.get("stop_reason") != "tool_use":
        fail("valid tool args should still emit a tool_use block with parsed input, content={!r}".format(out_ok.get("content")))
        return
    # Step 6c: verify a tool_args_parse_failure trace event from THIS test
    # (request_id R1, from the malformed cases) carries the threaded
    # request_id/mode/provider/tier fields — the unit-level proof that
    # _transform_and_guard threads the correlation context through. The trace
    # file is session-shared and appended, so assert on the matching event
    # (request_id R1) rather than a count.
    trace_file = os.environ.get("PROXY_TRACE_FILE")
    if not trace_file or not os.path.exists(trace_file):
        fail("expected PROXY_TRACE_FILE to be set to an existing temp path, got {!r}".format(trace_file))
        return
    matched = None
    with open(trace_file) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except Exception:
                continue
            if ev.get("event") == "tool_args_parse_failure" and ev.get("request_id") == "R1":
                matched = ev
                break
    if matched is None:
        fail("expected a tool_args_parse_failure trace event with request_id R1, none found")
        return
    if (matched.get("mode") != "chat" or matched.get("provider") != "p"
            or matched.get("tier") != "sonnet"):
        fail("tool_args_parse_failure event missing mode/provider/tier, got {!r}".format(matched))
        return
    pass_("malformed tool args produce a text block, no input {}, stop_reason None")


def test_chat_to_anthropic_nesting_limit_tool_args():
    """A tool-args JSON string past the nesting limit degrades like malformed args.

    The arguments ride inside a JSON *string*, so no outer body scan can see
    their depth — _chat_to_anthropic checks the string itself before parsing
    it. The degrade is the existing visible placeholder (never a tool_use with
    input {}), stop_reason is forced to None, and the trace carries both the
    pre-existing tool_args_parse_failure event and the new
    nesting_limit_exceeded event at site "tool_args". Both firing is intended:
    the first is the user-facing degrade, the second names its cause.
    """
    print("\n--- Test: Chat To Anthropic Nesting-Limit Tool Args ---")
    fn = _require_server_func("_chat_to_anthropic")
    if fn is None:
        return
    limit = MAX_JSON_NESTING_DEPTH
    deep_args = "[" * (limit + 1) + "]" * (limit + 1)
    chat = {"id": "x",
            "choices": [{"index": 0,
                         "message": {"role": "assistant", "content": "",
                                     "tool_calls": [
                                         {"id": "call_1", "type": "function",
                                          "function": {"name": "f",
                                                       "arguments": deep_args}}]},
                         "finish_reason": "tool_calls"}]}
    rid = "R-nesting-chat-" + uuid.uuid4().hex[:8]
    out = fn(chat, "sonnet", request_id=rid, mode="chat", provider="p")
    content = out.get("content") if isinstance(out.get("content"), list) else []
    if [b for b in content if b.get("type") == "tool_use"]:
        fail(">limit arguments must not emit a tool_use block, content={!r}".format(content))
        return
    texts = [b.get("text") or "" for b in content if b.get("type") == "text"]
    if not any("f" in t and "call_1" in t for t in texts):
        fail("expected the visible placeholder naming 'f' and 'call_1', "
             "content={!r}".format(content))
        return
    if out.get("stop_reason") is not None:
        fail("a degraded call must force stop_reason None, got {!r}".format(
            out.get("stop_reason")))
        return

    trace_file = os.environ.get("PROXY_TRACE_FILE")
    if not trace_file or not os.path.exists(trace_file):
        fail("expected PROXY_TRACE_FILE to be set to an existing temp path, got {!r}".format(
            trace_file))
        return
    events = []
    with open(trace_file) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except Exception:
                continue
            if ev.get("request_id") == rid:
                events.append(ev)
    nesting = [e for e in events if e.get("event") == "nesting_limit_exceeded"]
    if len(nesting) != 1:
        fail("expected exactly one nesting_limit_exceeded event for {!r}, got "
             "{!r}".format(rid, [e.get("event") for e in events]))
        return
    ev = nesting[0]
    if ev.get("site") != "tool_args":
        fail("expected site tool_args, got {!r}".format(ev.get("site")))
        return
    if ev.get("depth", 0) < limit + 1:
        fail("event depth {} is not past the limit {}".format(ev.get("depth"), limit))
        return
    if (ev.get("mode"), ev.get("provider"), ev.get("tier")) != ("chat", "p", "sonnet"):
        fail("nesting event missing mode/provider/tier: {!r}".format(ev))
        return
    if not [e for e in events if e.get("event") == "tool_args_parse_failure"]:
        fail("the user-facing degrade must still fire tool_args_parse_failure")
        return
    pass_(">limit args -> placeholder block, null stop_reason, tool_args nesting "
          "event alongside tool_args_parse_failure")


def test_chat_to_anthropic_nesting_guard_total():
    """A RecursionError from the tool-args parse degrades identically.

    Pins the widened catch in _chat_to_anthropic: under the pre-plan narrow
    ``except json.JSONDecodeError`` a RecursionError (not a ValueError)
    escaped the function. The total idiom converts it to the same placeholder
    degrade. Proven with a patched json.loads, so it holds on any interpreter.
    """
    print("\n--- Test: Chat To Anthropic Nesting Guard Total ---")
    fn = _require_server_func("_chat_to_anthropic")
    if fn is None:
        return
    chat = {"id": "x",
            "choices": [{"index": 0,
                         "message": {"role": "assistant", "content": "",
                                     "tool_calls": [
                                         {"id": "call_1", "type": "function",
                                          "function": {"name": "f",
                                                       "arguments": '{"city": "SF"}'}}]},
                         "finish_reason": "tool_calls"}]}
    try:
        with unittest.mock.patch("json.loads", side_effect=RecursionError):
            out = fn(chat, "sonnet", request_id="R-nesting-total-" + uuid.uuid4().hex[:8],
                     mode="chat", provider="p")
    except Exception as e:
        fail("a RecursionError escaped _chat_to_anthropic: {!r}".format(e))
        return
    content = out.get("content") if isinstance(out.get("content"), list) else []
    if [b for b in content if b.get("type") == "tool_use"]:
        fail("a parse fault must not emit a tool_use block, content={!r}".format(content))
        return
    texts = [b.get("text") or "" for b in content if b.get("type") == "text"]
    if not any("f" in t and "call_1" in t for t in texts):
        fail("expected the placeholder degrade, content={!r}".format(content))
        return
    if out.get("stop_reason") is not None:
        fail("a degraded call must force stop_reason None, got {!r}".format(
            out.get("stop_reason")))
        return
    pass_("patched json.loads RecursionError -> same placeholder degrade, no raise")


def test_chat_to_anthropic_malformed_tool_args_mixed():
    """Mixed valid + malformed tool calls: valid tool_use kept, malformed degrades.

    Guards the emitted_tool_use flag introduced by Option C: when at least one
    tool_use block is emitted, stop_reason still maps from finish_reason.
    """
    print("\n--- Test: Chat To Anthropic Malformed Tool Args Mixed ---")
    fn = _require_server_func("_chat_to_anthropic")
    if fn is None:
        return
    chat = {"id": "x",
            "choices": [{"index": 0,
                         "message": {"role": "assistant", "content": "",
                                     "tool_calls": [
                                         {"id": "call_1", "type": "function",
                                          "function": {"name": "good", "arguments": '{"city": "SF"}'}},
                                         {"id": "call_2", "type": "function",
                                          "function": {"name": "bad", "arguments": "{not json"}}]},
                         "finish_reason": "tool_calls"}]}
    out = fn(chat, "sonnet", request_id="R3", mode="chat", provider="p")
    content = out.get("content") if isinstance(out.get("content"), list) else []
    tools = [b for b in content if b.get("type") == "tool_use"]
    if len(tools) != 1:
        fail("expected exactly one tool_use block, got {!r}".format(content))
        return
    if tools[0].get("name") != "good" or tools[0].get("input") != {"city": "SF"}:
        fail("valid tool call should be preserved, got {!r}".format(tools[0]))
        return
    text_blocks = [b for b in content if b.get("type") == "text"]
    if not any("bad" in (b.get("text") or "") and "call_2" in (b.get("text") or "") for b in text_blocks):
        fail("malformed tool call should produce a text block naming 'bad' and 'call_2', content={!r}".format(content))
        return
    if out.get("stop_reason") != "tool_use":
        fail("with a valid tool_use emitted, stop_reason should map to tool_use, got {!r}".format(out.get("stop_reason")))
        return
    pass_("mixed valid + malformed tool calls: valid tool_use kept, malformed degrades")


ALL_TESTS = [
    ("chat-to-anthropic-basic", test_chat_to_anthropic_basic),
    ("chat-to-anthropic-reasoning-content-to-thinking", test_chat_to_anthropic_reasoning_content_to_thinking),
    ("chat-to-anthropic-reasoning-field-compat", test_chat_to_anthropic_reasoning_field_compat),
    ("chat-to-anthropic-reasoning-content-empty", test_chat_to_anthropic_reasoning_content_empty),
    ("chat-to-anthropic-reasoning-content-with-tool-calls", test_chat_to_anthropic_reasoning_content_with_tool_calls),
    ("chat-to-anthropic-empty-choices", test_chat_to_anthropic_empty_choices),
    ("chat-to-anthropic-tool-calls", test_chat_to_anthropic_tool_calls),
    ("chat-to-anthropic-finish-reason-mapping", test_chat_to_anthropic_finish_reason_mapping),
    ("chat-to-anthropic-usage-absent", test_chat_to_anthropic_usage_absent),
    ("chat-to-anthropic-content-array", test_chat_to_anthropic_content_array),
    ("chat-to-anthropic-malformed-tool-args-text-block", test_chat_to_anthropic_malformed_tool_args_text_block),
    ("chat-to-anthropic-nesting-limit-tool-args", test_chat_to_anthropic_nesting_limit_tool_args),
    ("chat-to-anthropic-nesting-guard-total", test_chat_to_anthropic_nesting_guard_total),
    ("chat-to-anthropic-malformed-tool-args-mixed", test_chat_to_anthropic_malformed_tool_args_mixed),
]


if __name__ == "__main__":
    run_cli(ALL_TESTS, "claude-retry-proxy tests: test_chat_transform_chat_to_anthropic")
