"""Chat-mode transform tests: Anthropic-to-Chat request conversion and
Chat-to-Anthropic response conversion.

Part of the claude-retry-proxy suite; runnable standalone.
"""

import json
import os
import uuid

from _harness import (
    _require_server_func,
    _trace_events_for_request,
    fail,
    pass_,
    run_cli,
)




def test_anthropic_to_chat_messages_transform():
    """Full message array (thinking/text/tool_use/tool_result) -> valid OpenAI Chat messages."""
    print("\n--- Test: Anthropic To Chat Messages Transform ---")
    fn = _require_server_func("_transform_anthropic_messages_to_chat")
    if fn is None:
        return
    messages = [
        {"role": "assistant", "content": [
            {"type": "thinking", "thinking": "hidden", "signature": "sig1"},
            {"type": "text", "text": "Let me check."},
            {"type": "tool_use", "id": "toolu_1", "name": "get_weather", "input": {"city": "SF"}},
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "toolu_1", "content": "60F"},
            {"type": "text", "text": "thanks"},
        ]},
    ]
    out = fn(messages, request_id="T-" + uuid.uuid4().hex[:8], mode="chat", provider="p", tier="sonnet")
    expected = [
        {"role": "assistant", "content": "Let me check.",
         "reasoning_content": "hidden", "reasoning": "hidden"},
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "toolu_1", "type": "function",
             "function": {"name": "get_weather", "arguments": '{"city": "SF"}'}}]},
        {"role": "tool", "tool_call_id": "toolu_1", "content": "60F"},
        {"role": "user", "content": "thanks"},
    ]
    if out != expected:
        fail("full transform mismatch, got {!r}".format(out))
    else:
        pass_("full message array transformed correctly")




def test_anthropic_to_chat_messages_thinking_stripped():
    """thinking is converted to reasoning_content; redacted_thinking non-empty data -> placeholder."""
    print("\n--- Test: Anthropic To Chat Messages Thinking Stripped ---")
    fn = _require_server_func("_transform_anthropic_messages_to_chat")
    if fn is None:
        return
    messages = [
        {"role": "assistant", "content": [
            {"type": "thinking", "thinking": "hidden", "signature": "s"},
            {"type": "redacted_thinking", "data": "enc", "signature": "s2"},
            {"type": "text", "text": "visible"},
        ]},
    ]
    out = fn(messages, request_id="T-" + uuid.uuid4().hex[:8], mode="chat", provider="p", tier="sonnet")
    expected = [{"role": "assistant", "content": "visible",
                 "reasoning_content": "hidden", "reasoning": "hidden"}]
    if out != expected:
        fail("thinking should convert to reasoning_content (real thinking wins over redacted placeholder), got {!r}".format(out))
    else:
        pass_("thinking converted to reasoning_content; redacted_thinking placeholder suppressed by real thinking")




def test_anthropic_to_chat_messages_redacted_thinking_trace():
    """redacted_thinking with non-empty data -> placeholder reasoning_content + passthrough trace event.

    Real thinking text wins over the placeholder. Empty data is stripped and
    counted in dropped.redacted_thinking, not passed through.
    """
    print("\n--- Test: Anthropic To Chat Messages Redacted Thinking Trace ---")
    fn = _require_server_func("_transform_anthropic_messages_to_chat")
    if fn is None:
        return
    rid = "T-" + uuid.uuid4().hex[:8]
    messages = [
        {"role": "assistant", "content": [
            {"type": "redacted_thinking", "data": "enc", "signature": "s2"},
            {"type": "text", "text": "visible"},
        ]},
    ]
    out = fn(messages, request_id=rid, mode="chat", provider="p", tier="sonnet")
    expected = [{"role": "assistant", "content": "visible",
                 "reasoning_content": "[redacted_thinking: data not available]",
                 "reasoning": "[redacted_thinking: data not available]"}]
    if out != expected:
        fail("redacted_thinking non-empty data should set placeholder reasoning_content, got {!r}".format(out))
        return
    evs = [e for e in _trace_events_for_request(rid) if e.get("event") == "redacted_thinking_passthrough"]
    if len(evs) != 1:
        fail("expected exactly ONE redacted_thinking_passthrough event, got {}: {!r}".format(len(evs), evs))
        return
    ev = evs[0]
    if not (ev.get("mode") == "chat" and ev.get("provider") == "p"
            and ev.get("tier") == "sonnet" and ev.get("request_id") == rid):
        fail("redacted_thinking_passthrough missing correlation fields, got {!r}".format(ev))
        return
    if ev.get("data_length") != 3:
        fail("redacted_thinking_passthrough data_length should be len('enc')=3, got {!r}".format(ev.get("data_length")))
        return
    # Real thinking text wins over the redacted placeholder.
    rid2 = "T-" + uuid.uuid4().hex[:8]
    messages2 = [
        {"role": "assistant", "content": [
            {"type": "thinking", "thinking": "real", "signature": "s"},
            {"type": "redacted_thinking", "data": "enc", "signature": "s2"},
        ]},
    ]
    out2 = fn(messages2, request_id=rid2, mode="chat", provider="p", tier="sonnet")
    if out2 != [{"role": "assistant", "content": "",
                 "reasoning_content": "real", "reasoning": "real"}]:
        fail("real thinking should win over redacted placeholder, got {!r}".format(out2))
        return
    evs2 = [e for e in _trace_events_for_request(rid2) if e.get("event") == "redacted_thinking_passthrough"]
    if evs2:
        fail("real thinking present should suppress redacted_thinking_passthrough event, got {!r}".format(evs2))
        return
    # Empty/missing data is stripped and counted in dropped, not passed through.
    rid3 = "T-" + uuid.uuid4().hex[:8]
    messages3 = [
        {"role": "assistant", "content": [
            {"type": "redacted_thinking", "data": "", "signature": "s2"},
            {"type": "redacted_thinking", "signature": "s3"},
            {"type": "text", "text": "x"},
        ]},
    ]
    out3 = fn(messages3, request_id=rid3, mode="chat", provider="p", tier="sonnet")
    if out3 != [{"role": "assistant", "content": "x"}]:
        fail("empty-data redacted_thinking should be stripped, got {!r}".format(out3))
        return
    evs3 = [e for e in _trace_events_for_request(rid3) if e.get("event") == "redacted_thinking_passthrough"]
    if evs3:
        fail("empty-data redacted_thinking must not log passthrough event, got {!r}".format(evs3))
        return
    dropped3 = [e for e in _trace_events_for_request(rid3) if e.get("event") == "content_block_dropped"]
    counts3 = (dropped3[0].get("dropped_counts") or {}) if dropped3 else {}
    if counts3.get("redacted_thinking") != 2:
        fail("empty-data redacted_thinking should count in dropped.redacted_thinking, got {!r}".format(counts3))
        return
    pass_("redacted_thinking non-empty -> placeholder + passthrough trace; empty -> stripped")




def test_anthropic_to_chat_messages_tool_use_to_tool_calls():
    """tool_use block converts to tool_calls with JSON-stringified arguments."""
    print("\n--- Test: Anthropic To Chat Messages Tool Use To Tool Calls ---")
    fn = _require_server_func("_transform_anthropic_messages_to_chat")
    if fn is None:
        return
    messages = [
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "toolu_x", "name": "lookup", "input": {"key": "a", "n": 1}},
        ]},
    ]
    out = fn(messages, request_id="T-" + uuid.uuid4().hex[:8], mode="chat", provider="p", tier="sonnet")
    expected = [
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "toolu_x", "type": "function",
             "function": {"name": "lookup", "arguments": '{"key": "a", "n": 1}'}}]},
    ]
    if out != expected:
        fail("tool_use -> tool_calls mismatch, got {!r}".format(out))
    else:
        pass_("tool_use converted to tool_calls with JSON arguments")




def test_anthropic_to_chat_messages_tool_result_to_role_tool():
    """tool_result block in a user message becomes a separate role:tool message."""
    print("\n--- Test: Anthropic To Chat Messages Tool Result To Role Tool ---")
    fn = _require_server_func("_transform_anthropic_messages_to_chat")
    if fn is None:
        return
    messages = [
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "toolu_1", "name": "f", "input": {}},
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "toolu_1", "content": "the answer"},
        ]},
    ]
    out = fn(messages, request_id="T-" + uuid.uuid4().hex[:8], mode="chat", provider="p", tier="sonnet")
    expected = [
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "toolu_1", "type": "function", "function": {"name": "f", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "toolu_1", "content": "the answer"},
    ]
    if out != expected:
        fail("tool_result -> role:tool mismatch, got {!r}".format(out))
    else:
        pass_("tool_result emitted as role:tool message")




def test_anthropic_to_chat_messages_mixed_text_and_tool_use():
    """Assistant with both text and tool_use -> text message first, then content:null + tool_calls."""
    print("\n--- Test: Anthropic To Chat Messages Mixed Text And Tool Use ---")
    fn = _require_server_func("_transform_anthropic_messages_to_chat")
    if fn is None:
        return
    messages = [
        {"role": "assistant", "content": [
            {"type": "text", "text": "I'll look that up."},
            {"type": "tool_use", "id": "toolu_2", "name": "f", "input": {}},
        ]},
    ]
    out = fn(messages, request_id="T-" + uuid.uuid4().hex[:8], mode="chat", provider="p", tier="sonnet")
    expected = [
        {"role": "assistant", "content": "I'll look that up."},
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "toolu_2", "type": "function", "function": {"name": "f", "arguments": "{}"}}]},
    ]
    if out != expected:
        fail("text must be preserved as a separate message before tool_calls, got {!r}".format(out))
    else:
        pass_("text preserved + content:null tool_calls message when both present")




def test_anthropic_to_chat_messages_mixed_text_and_tool_result():
    """User with both text and tool_result -> tool message first, then user text message."""
    print("\n--- Test: Anthropic To Chat Messages Mixed Text And Tool Result ---")
    fn = _require_server_func("_transform_anthropic_messages_to_chat")
    if fn is None:
        return
    messages = [
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "toolu_1", "name": "f", "input": {}},
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "toolu_1", "content": "res"},
            {"type": "text", "text": "Thanks"},
        ]},
    ]
    out = fn(messages, request_id="T-" + uuid.uuid4().hex[:8], mode="chat", provider="p", tier="sonnet")
    expected = [
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "toolu_1", "type": "function", "function": {"name": "f", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "toolu_1", "content": "res"},
        {"role": "user", "content": "Thanks"},
    ]
    if out != expected:
        fail("tool messages must precede user text, got {!r}".format(out))
    else:
        pass_("tool messages first, then user text message")




def test_anthropic_to_chat_messages_interleaved_thinking_tool_use():
    """Real-world interleaved pattern: thinking, text, tool_use, text in one assistant turn."""
    print("\n--- Test: Anthropic To Chat Messages Interleaved Thinking Tool Use ---")
    fn = _require_server_func("_transform_anthropic_messages_to_chat")
    if fn is None:
        return
    messages = [
        {"role": "assistant", "content": [
            {"type": "thinking", "thinking": "reasoning...", "signature": "sig"},
            {"type": "text", "text": "Let me look up the weather for San Francisco."},
            {"type": "tool_use", "id": "toolu_weather", "name": "get_weather", "input": {"city": "San Francisco"}},
            {"type": "text", "text": "I found the forecast."},
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "toolu_weather", "content": "Sunny, 72F"},
        ]},
    ]
    out = fn(messages, request_id="T-" + uuid.uuid4().hex[:8], mode="chat", provider="p", tier="sonnet")
    expected = [
        {"role": "assistant",
         "content": "Let me look up the weather for San Francisco.\nI found the forecast.",
         "reasoning_content": "reasoning...", "reasoning": "reasoning..."},
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "toolu_weather", "type": "function",
             "function": {"name": "get_weather", "arguments": '{"city": "San Francisco"}'}}]},
        {"role": "tool", "tool_call_id": "toolu_weather", "content": "Sunny, 72F"},
    ]
    if out != expected:
        fail("interleaved pattern mismatch, got {!r}".format(out))
    else:
        pass_("interleaved thinking/text/tool_use pattern transformed with reasoning_content on text message")




def test_anthropic_to_chat_messages_string_content_passthrough():
    """String content passes through unchanged in a NEW message dict (input not reused)."""
    print("\n--- Test: Anthropic To Chat Messages String Content Passthrough ---")
    fn = _require_server_func("_transform_anthropic_messages_to_chat")
    if fn is None:
        return
    msg = {"role": "user", "content": "hi there"}
    out = fn([msg], request_id="T-" + uuid.uuid4().hex[:8], mode="chat", provider="p", tier="sonnet")
    if not isinstance(out, list) or len(out) != 1:
        fail("expected one output message, got {!r}".format(out))
        return
    out_msg = out[0]
    if out_msg.get("role") != "user" or out_msg.get("content") != "hi there":
        fail("string content not preserved, got {!r}".format(out_msg))
    elif out_msg is msg:
        fail("input message dict must not be reused")
    else:
        pass_("string content passed through in a new dict")




def test_anthropic_to_chat_messages_cache_control_stripped():
    """Block-level cache_control removed from blocks; cache_control_stripped trace event logged."""
    print("\n--- Test: Anthropic To Chat Messages Cache Control Stripped ---")
    fn = _require_server_func("_anthropic_to_chat")
    if fn is None:
        return
    rid = "T-" + uuid.uuid4().hex[:8]
    body = {
        "messages": [
            {"role": "user", "content": [
                {"type": "text", "text": "a", "cache_control": {"type": "ephemeral"}},
                {"type": "text", "text": "b", "cache_control": {"type": "ephemeral"}},
            ]},
        ],
    }
    out = fn(body, request_id=rid, mode="chat", provider="p", tier="sonnet")
    # Multiple user text blocks with cache_control stripped are joined to a string.
    expected = {"messages": [{"role": "user", "content": "a\nb"}]}
    if out != expected:
        fail("cache_control not stripped from blocks, got {!r}".format(out))
        return
    evs = [e for e in _trace_events_for_request(rid) if e.get("event") == "cache_control_stripped"]
    if not evs:
        fail("expected cache_control_stripped trace event, none found")
    elif evs[0].get("locations") != ["messages"]:
        fail("expected locations ['messages'], got {!r}".format(evs[0].get("locations")))
    else:
        pass_("block-level cache_control stripped and coalesced trace event logged")




def test_anthropic_to_chat_messages_non_list_guarded():
    """Non-list messages input returns []."""
    print("\n--- Test: Anthropic To Chat Messages Non List Guarded ---")
    fn = _require_server_func("_transform_anthropic_messages_to_chat")
    if fn is None:
        return
    for bad in (None, "notalist", {"role": "user", "content": "x"}, 42):
        out = fn(bad, request_id="T-" + uuid.uuid4().hex[:8], mode="chat", provider="p", tier="sonnet")
        if out != []:
            fail("expected [] for {!r}, got {!r}".format(bad, out))
            return
    pass_("non-list messages returns []")




def test_anthropic_to_chat_messages_non_dict_entries_skipped():
    """Non-dict message entries are skipped."""
    print("\n--- Test: Anthropic To Chat Messages Non Dict Entries Skipped ---")
    fn = _require_server_func("_transform_anthropic_messages_to_chat")
    if fn is None:
        return
    messages = [{"role": "user", "content": "ok"}, "garbage", 42, None, ["nested"]]
    out = fn(messages, request_id="T-" + uuid.uuid4().hex[:8], mode="chat", provider="p", tier="sonnet")
    if out != [{"role": "user", "content": "ok"}]:
        fail("non-dict entries not skipped, got {!r}".format(out))
    else:
        pass_("non-dict message entries skipped")




def test_anthropic_to_chat_messages_null_user_content():
    """Null user content becomes '' (OpenAI requires non-null user content)."""
    print("\n--- Test: Anthropic To Chat Messages Null User Content ---")
    fn = _require_server_func("_transform_anthropic_messages_to_chat")
    if fn is None:
        return
    messages = [{"role": "user", "content": None}]
    out = fn(messages, request_id="T-" + uuid.uuid4().hex[:8], mode="chat", provider="p", tier="sonnet")
    if out != [{"role": "user", "content": ""}]:
        fail("null user content not replaced with '', got {!r}".format(out))
    else:
        pass_("null user content -> ''")




def test_anthropic_to_chat_tools_transform():
    """Anthropic tools -> OpenAI tools (input_schema -> parameters)."""
    print("\n--- Test: Anthropic To Chat Tools Transform ---")
    fn = _require_server_func("_transform_anthropic_tools_to_chat")
    if fn is None:
        return
    tools = [
        {"name": "get_weather", "description": "Get weather",
         "input_schema": {"type": "object", "properties": {}}},
        {"name": "get_time", "input_schema": {}},
    ]
    out = fn(tools, request_id="T-" + uuid.uuid4().hex[:8], mode="chat", provider="p", tier="sonnet")
    expected = [
        {"type": "function", "function": {
            "name": "get_weather", "description": "Get weather",
            "parameters": {"type": "object", "properties": {}}}},
        {"type": "function", "function": {"name": "get_time", "parameters": {}}},
    ]
    if out != expected:
        fail("tools transform mismatch, got {!r}".format(out))
    else:
        pass_("tools transformed (input_schema -> parameters)")




def test_anthropic_to_chat_tools_cache_control_stripped():
    """cache_control on tool definitions is stripped; cache_control_stripped trace event logged."""
    print("\n--- Test: Anthropic To Chat Tools Cache Control Stripped ---")
    fn = _require_server_func("_anthropic_to_chat")
    if fn is None:
        return
    rid = "T-" + uuid.uuid4().hex[:8]
    body = {
        "messages": [{"role": "user", "content": "hi"}],
        "tools": [{"name": "t", "input_schema": {}, "cache_control": {"type": "ephemeral"}}],
    }
    out = fn(body, request_id=rid, mode="chat", provider="p", tier="sonnet")
    expected_tools = [{"type": "function", "function": {"name": "t", "parameters": {}}}]
    if out.get("tools") != expected_tools:
        fail("cache_control not stripped from tool, got {!r}".format(out.get("tools")))
        return
    evs = [e for e in _trace_events_for_request(rid) if e.get("event") == "cache_control_stripped"]
    if not evs:
        fail("expected cache_control_stripped trace event for tool, none found")
    elif evs[0].get("locations") != ["tools"]:
        fail("expected locations ['tools'], got {!r}".format(evs[0].get("locations")))
    else:
        pass_("tool cache_control stripped and coalesced trace event logged")




def test_anthropic_to_chat_tools_non_list_guarded():
    """Non-list tools returns [] (tools: null treated as absent)."""
    print("\n--- Test: Anthropic To Chat Tools Non List Guarded ---")
    fn = _require_server_func("_transform_anthropic_tools_to_chat")
    if fn is None:
        return
    for bad in (None, "tools", {"name": "x"}, 42):
        out = fn(bad, request_id="T-" + uuid.uuid4().hex[:8], mode="chat", provider="p", tier="sonnet")
        if out != []:
            fail("expected [] for {!r}, got {!r}".format(bad, out))
            return
    pass_("non-list tools returns []")




def test_anthropic_to_chat_tools_malformed_entries_skipped():
    """Entries missing name or input_schema are skipped with a content_block_dropped trace event."""
    print("\n--- Test: Anthropic To Chat Tools Malformed Entries Skipped ---")
    fn = _require_server_func("_transform_anthropic_tools_to_chat")
    if fn is None:
        return
    rid = "T-" + uuid.uuid4().hex[:8]
    tools = [
        {"name": "good", "input_schema": {}},
        {"name": "no-schema"},
        {"input_schema": {}},
        "garbage",
        42,
        None,
    ]
    out = fn(tools, request_id=rid, mode="chat", provider="p", tier="sonnet")
    expected = [{"type": "function", "function": {"name": "good", "parameters": {}}}]
    if out != expected:
        fail("malformed tool entries not skipped, got {!r}".format(out))
        return
    evs = [e for e in _trace_events_for_request(rid) if e.get("event") == "content_block_dropped"]
    if not evs:
        fail("expected content_block_dropped trace event for malformed tools, none found")
    else:
        pass_("malformed tool entries skipped with trace event")




def test_anthropic_to_chat_tool_choice_mapping():
    """All 4 tool_choice variants map correctly."""
    print("\n--- Test: Anthropic To Chat Tool Choice Mapping ---")
    fn = _require_server_func("_transform_anthropic_tool_choice_to_chat")
    if fn is None:
        return
    cases = [
        ({"type": "none"}, "none"),
        ({"type": "auto"}, "auto"),
        ({"type": "any"}, "required"),
        ({"type": "tool", "name": "x"}, {"type": "function", "function": {"name": "x"}}),
    ]
    for tc, expected in cases:
        out = fn(tc)
        if out != expected:
            fail("tool_choice {!r} -> {!r}, expected {!r}".format(tc, out, expected))
            return
    pass_("all tool_choice variants mapped")




def test_anthropic_to_chat_tool_choice_none_omitted():
    """None/absent tool_choice is omitted from output."""
    print("\n--- Test: Anthropic To Chat Tool Choice None Omitted ---")
    fn_choice = _require_server_func("_transform_anthropic_tool_choice_to_chat")
    if fn_choice is not None and fn_choice(None) is not None:
        fail("None tool_choice should map to None")
        return
    fn = _require_server_func("_anthropic_to_chat")
    if fn is None:
        return
    inp = {"model": "sonnet",
           "messages": [{"role": "user", "content": "hi"}],
           "tools": [{"name": "t", "input_schema": {}}]}
    out = fn(dict(inp))
    if "tool_choice" in out:
        fail("tool_choice should be absent when not provided, keys={!r}".format(sorted(out.keys())))
    else:
        pass_("absent tool_choice omitted")




def test_anthropic_to_chat_tool_choice_malformed_omitted():
    """Malformed/unknown tool_choice maps to None (omitted, defensive)."""
    print("\n--- Test: Anthropic To Chat Tool Choice Malformed Omitted ---")
    fn = _require_server_func("_transform_anthropic_tool_choice_to_chat")
    if fn is None:
        return
    for bad in ("auto", {"type": "weird"}, {}, {"type": "tool"}, {"type": "tool", "name": None}, 42, []):
        out = fn(bad)
        if out is not None:
            fail("malformed tool_choice {!r} should map to None, got {!r}".format(bad, out))
            return
    pass_("malformed tool_choice omitted")




def test_anthropic_to_chat_tool_choice_only_with_tools():
    """tool_choice is omitted when the tools array is empty or absent."""
    print("\n--- Test: Anthropic To Chat Tool Choice Only With Tools ---")
    fn = _require_server_func("_anthropic_to_chat")
    if fn is None:
        return
    inp_empty = {"model": "sonnet",
                 "messages": [{"role": "user", "content": "hi"}],
                 "tools": [],
                 "tool_choice": {"type": "auto"}}
    out_empty = fn(dict(inp_empty))
    if "tool_choice" in out_empty:
        fail("tool_choice should be omitted when tools array is empty, got {!r}".format(out_empty.get("tool_choice")))
        return
    inp_no_tools = {"model": "sonnet",
                    "messages": [{"role": "user", "content": "hi"}],
                    "tool_choice": {"type": "auto"}}
    out_no_tools = fn(dict(inp_no_tools))
    if "tool_choice" in out_no_tools:
        fail("tool_choice should be omitted when tools absent, got {!r}".format(out_no_tools.get("tool_choice")))
        return
    pass_("tool_choice omitted when tools empty/absent")




def test_anthropic_to_chat_integration():
    """Full Anthropic request (system, tools, tool_choice, multi-turn) -> valid OpenAI Chat request."""
    print("\n--- Test: Anthropic To Chat Integration ---")
    fn = _require_server_func("_anthropic_to_chat")
    if fn is None:
        return
    inp = {
        "model": "sonnet",
        "system": "You are a helpful assistant.",
        "max_tokens": 256,
        "temperature": 0.2,
        "stream": False,
        "tools": [
            {"name": "get_weather", "description": "Weather lookup",
             "input_schema": {"type": "object", "properties": {"city": {"type": "string"}}}},
        ],
        "tool_choice": {"type": "auto"},
        "messages": [
            {"role": "user", "content": "What's the weather in SF?"},
            {"role": "assistant", "content": [
                {"type": "thinking", "thinking": "hidden", "signature": "s"},
                {"type": "text", "text": "Let me look it up."},
                {"type": "tool_use", "id": "toolu_1", "name": "get_weather", "input": {"city": "SF"}},
            ]},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "toolu_1", "content": "Sunny, 72F"},
                {"type": "text", "text": "Great, thanks!"},
            ]},
        ],
    }
    out = fn(dict(inp))
    expected_messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "What's the weather in SF?"},
        {"role": "assistant", "content": "Let me look it up.",
         "reasoning_content": "hidden", "reasoning": "hidden"},
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "toolu_1", "type": "function",
             "function": {"name": "get_weather", "arguments": '{"city": "SF"}'}}]},
        {"role": "tool", "tool_call_id": "toolu_1", "content": "Sunny, 72F"},
        {"role": "user", "content": "Great, thanks!"},
    ]
    expected_tools = [{"type": "function", "function": {
        "name": "get_weather", "description": "Weather lookup",
        "parameters": {"type": "object", "properties": {"city": {"type": "string"}}}}}]
    checks = [
        (out.get("model") == "sonnet", "model passthrough"),
        (out.get("max_tokens") == 256, "max_tokens passthrough"),
        (out.get("temperature") == 0.2, "temperature passthrough"),
        (out.get("stream") is False, "stream passthrough"),
        (out.get("messages") == expected_messages, "messages transformed"),
        (out.get("tools") == expected_tools, "tools transformed"),
        (out.get("tool_choice") == "auto", "tool_choice mapped"),
    ]
    for ok, label in checks:
        if not ok:
            fail("integration failed: {} (out={!r})".format(label, out))
            return
    pass_("full chat-mode request transformed correctly")




def test_anthropic_to_chat_content_block_dropped_trace():
    """Coalesced content_block_dropped trace event with dropped_counts (not per-block)."""
    print("\n--- Test: Anthropic To Chat Content Block Dropped Trace ---")
    fn = _require_server_func("_transform_anthropic_messages_to_chat")
    if fn is None:
        return
    rid = "T-" + uuid.uuid4().hex[:8]
    messages = [
        {"role": "assistant", "content": [
            {"type": "thinking", "thinking": "a", "signature": "s"},
            {"type": "thinking", "thinking": "b", "signature": "s"},
        ]},
        {"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "data": "x"}},
            {"type": "text", "text": "hi"},
        ]},
    ]
    fn(messages, request_id=rid, mode="chat", provider="p", tier="sonnet")
    evs = [e for e in _trace_events_for_request(rid) if e.get("event") == "content_block_dropped"]
    if len(evs) != 1:
        fail("expected exactly ONE coalesced content_block_dropped event, got {}: {!r}".format(len(evs), evs))
        return
    ev = evs[0]
    counts = ev.get("dropped_counts") or {}
    checks = [
        (ev.get("mode") == "chat", "mode field"),
        (ev.get("provider") == "p", "provider field"),
        (ev.get("tier") == "sonnet", "tier field"),
        (ev.get("request_id") == rid, "request_id field"),
        (counts.get("thinking") == 0, "thinking no longer counted as dropped"),
        (counts.get("image") == 1, "image count 1"),
    ]
    for ok, label in checks:
        if not ok:
            fail("content_block_dropped event wrong: {} (ev={!r})".format(label, ev))
            return
    pass_("coalesced content_block_dropped event with dropped_counts")




def test_anthropic_to_chat_cache_control_stripped_trace():
    """cache_control_stripped logged once per request (coalesced), not per block."""
    print("\n--- Test: Anthropic To Chat Cache Control Stripped Trace ---")
    fn = _require_server_func("_anthropic_to_chat")
    if fn is None:
        return
    rid = "T-" + uuid.uuid4().hex[:8]
    body = {
        "messages": [
            {"role": "user", "content": [
                {"type": "text", "text": "a", "cache_control": {"type": "ephemeral"}},
                {"type": "text", "text": "b", "cache_control": {"type": "ephemeral"}},
            ]},
        ],
        "tools": [{"name": "t", "input_schema": {}, "cache_control": {"type": "ephemeral"}}],
    }
    fn(body, request_id=rid, mode="chat", provider="p", tier="sonnet")
    evs = [e for e in _trace_events_for_request(rid) if e.get("event") == "cache_control_stripped"]
    if len(evs) != 1:
        fail("expected exactly ONE cache_control_stripped event, got {}: {!r}".format(len(evs), evs))
        return
    ev = evs[0]
    if ev.get("locations") not in (["messages", "tools"], ["tools", "messages"]):
        fail("cache_control_stripped missing valid locations, got {!r}".format(ev))
        return
    if (ev.get("mode") != "chat" or ev.get("provider") != "p"
            or ev.get("tier") != "sonnet" or ev.get("request_id") != rid):
        fail("cache_control_stripped missing correlation fields, got {!r}".format(ev))
        return
    pass_("cache_control_stripped logged once per request with coalesced locations")




def test_anthropic_to_chat_nan_infinity_arguments_rejected():
    """NaN/Infinity tool_use.input degrades to a text placeholder, not silently dropped."""
    print("\n--- Test: Anthropic To Chat NaN Infinity Arguments Rejected ---")
    fn = _require_server_func("_transform_anthropic_messages_to_chat")
    if fn is None:
        return
    rid = "T-" + uuid.uuid4().hex[:8]
    messages = [
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "toolu_nan", "name": "f", "input": {"value": float("nan")}},
        ]},
    ]
    out = fn(messages, request_id=rid, mode="chat", provider="p", tier="sonnet")
    msg = out[0] if out else {}
    tool_calls = msg.get("tool_calls") if isinstance(msg, dict) else None
    if tool_calls:
        fail("NaN tool_use must not produce a tool_calls entry, got {!r}".format(out))
        return
    content = msg.get("content") if isinstance(msg, dict) else None
    expected_placeholder = ("[Tool call failed: arguments for 'f' (call toolu_nan) "
                            "could not be serialized as JSON]")
    if content != expected_placeholder:
        fail("NaN tool_use should degrade to a text placeholder, got content={!r}".format(content))
        return
    evs = [e for e in _trace_events_for_request(rid) if e.get("event") == "tool_args_parse_failure"]
    if not evs:
        fail("expected tool_args_parse_failure trace event, none found")
        return
    ev = evs[0]
    if ev.get("tool_name") != "f" or ev.get("tool_id") != "toolu_nan":
        fail("tool_args_parse_failure missing tool_name/tool_id, got {!r}".format(ev))
        return
    pass_("NaN tool_use degraded to placeholder with tool_args_parse_failure event")




def test_anthropic_to_chat_tool_use_non_dict_input():
    """tool_use.input with non-dict value (string/None/number) degrades to placeholder, no non-object arguments."""
    print("\n--- Test: Anthropic To Chat Tool Use Non Dict Input ---")
    fn = _require_server_func("_transform_anthropic_messages_to_chat")
    if fn is None:
        return
    rid = "T-" + uuid.uuid4().hex[:8]
    for bad in ("hello", None, 42, [1, 2]):
        messages = [
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "toolu_bad", "name": "f", "input": bad},
            ]},
        ]
        out = fn(messages, request_id=rid, mode="chat", provider="p", tier="sonnet")
        expected = [{"role": "assistant",
                     "content": ("[Tool call failed: arguments for 'f' (call toolu_bad) "
                                 "could not be serialized as JSON]")}]
        if out != expected:
            fail("non-dict input {!r} should degrade to placeholder, got {!r}".format(bad, out))
            return
        if any(isinstance(m, dict) and m.get("tool_calls") for m in out):
            fail("non-dict input {!r} must not produce a tool_calls entry, got {!r}".format(bad, out))
            return
    evs = [e for e in _trace_events_for_request(rid) if e.get("event") == "tool_args_parse_failure"]
    if len(evs) < 4:
        fail("expected tool_args_parse_failure events for each non-dict input, got {}: {!r}".format(len(evs), evs))
        return
    for ev in evs:
        if ev.get("tool_name") != "f" or ev.get("tool_id") != "toolu_bad" or not isinstance(ev.get("error"), str):
            fail("tool_args_parse_failure missing tool_name/tool_id/error, got {!r}".format(ev))
            return
    pass_("non-dict tool_use input degraded to placeholder with tool_args_parse_failure")




def test_anthropic_to_chat_nan_placeholder_with_valid_tool_use():
    """NaN tool_use + valid tool_use coexist -> placeholder as separate assistant message before tool_calls."""
    print("\n--- Test: Anthropic To Chat Nan Placeholder With Valid Tool Use ---")
    fn = _require_server_func("_transform_anthropic_messages_to_chat")
    if fn is None:
        return
    rid = "T-" + uuid.uuid4().hex[:8]
    messages = [
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "toolu_nan", "name": "f", "input": {"value": float("nan")}},
            {"type": "tool_use", "id": "toolu_ok", "name": "g", "input": {"a": 1}},
        ]},
    ]
    out = fn(messages, request_id=rid, mode="chat", provider="p", tier="sonnet")
    expected = [
        {"role": "assistant",
         "content": ("[Tool call failed: arguments for 'f' (call toolu_nan) "
                     "could not be serialized as JSON]")},
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "toolu_ok", "type": "function",
             "function": {"name": "g", "arguments": '{"a": 1}'}}]},
    ]
    if out != expected:
        fail("NaN placeholder must be preserved before tool_calls, got {!r}".format(out))
        return
    evs = [e for e in _trace_events_for_request(rid) if e.get("event") == "tool_args_parse_failure"]
    if not evs:
        fail("expected tool_args_parse_failure trace event, none found")
        return
    if evs[0].get("tool_name") != "f" or evs[0].get("tool_id") != "toolu_nan":
        fail("tool_args_parse_failure missing tool_name/tool_id, got {!r}".format(evs[0]))
        return
    pass_("NaN placeholder preserved as separate message before tool_calls")




def test_anthropic_to_chat_tool_result_list_content():
    """tool_result.content as a list of text blocks is joined with newlines."""
    print("\n--- Test: Anthropic To Chat Tool Result List Content ---")
    fn = _require_server_func("_transform_anthropic_messages_to_chat")
    if fn is None:
        return
    messages = [
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "toolu_1", "name": "f", "input": {}},
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "toolu_1", "content": [
                {"type": "text", "text": "line1"},
                {"type": "text", "text": "line2"},
            ]},
        ]},
    ]
    out = fn(messages, request_id="T-" + uuid.uuid4().hex[:8], mode="chat", provider="p", tier="sonnet")
    expected = [
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "toolu_1", "type": "function", "function": {"name": "f", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "toolu_1", "content": "line1\nline2"},
    ]
    if out != expected:
        fail("tool_result list content not joined, got {!r}".format(out))
    else:
        pass_("tool_result list content joined with newlines")




def test_anthropic_to_chat_no_input_mutation():
    """_anthropic_to_chat does not mutate the input dict or its nested structures."""
    print("\n--- Test: Anthropic To Chat No Input Mutation ---")
    fn = _require_server_func("_anthropic_to_chat")
    if fn is None:
        return
    import copy
    inp = {
        "model": "sonnet",
        "messages": [
            {"role": "assistant", "content": [
                {"type": "text", "text": "a"},
                {"type": "tool_use", "id": "t1", "name": "f", "input": {"x": 1}},
            ]},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "t1", "content": "r"},
            ]},
        ],
        "tools": [{"name": "f", "input_schema": {}, "cache_control": {"type": "ephemeral"}}],
        "tool_choice": {"type": "auto"},
        "thinking": {"type": "enabled", "budget_tokens": 100},
    }
    messages_identity = inp["messages"]
    original = copy.deepcopy(inp)
    fn(dict(inp))
    if inp != original:
        fail("input dict was mutated")
        return
    if inp["messages"] is not messages_identity:
        fail("input messages list identity changed")
        return
    pass_("input dict and nested structures not mutated")




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
    ("anthropic-to-chat-messages-transform", test_anthropic_to_chat_messages_transform),
    ("anthropic-to-chat-messages-thinking-stripped", test_anthropic_to_chat_messages_thinking_stripped),
    ("anthropic-to-chat-messages-redacted-thinking-trace", test_anthropic_to_chat_messages_redacted_thinking_trace),
    ("anthropic-to-chat-messages-tool-use-to-tool-calls", test_anthropic_to_chat_messages_tool_use_to_tool_calls),
    ("anthropic-to-chat-messages-tool-result-to-role-tool", test_anthropic_to_chat_messages_tool_result_to_role_tool),
    ("anthropic-to-chat-messages-mixed-text-and-tool-use", test_anthropic_to_chat_messages_mixed_text_and_tool_use),
    ("anthropic-to-chat-messages-mixed-text-and-tool-result", test_anthropic_to_chat_messages_mixed_text_and_tool_result),
    ("anthropic-to-chat-messages-interleaved-thinking-tool-use", test_anthropic_to_chat_messages_interleaved_thinking_tool_use),
    ("anthropic-to-chat-messages-string-content-passthrough", test_anthropic_to_chat_messages_string_content_passthrough),
    ("anthropic-to-chat-messages-cache-control-stripped", test_anthropic_to_chat_messages_cache_control_stripped),
    ("anthropic-to-chat-messages-non-list-guarded", test_anthropic_to_chat_messages_non_list_guarded),
    ("anthropic-to-chat-messages-non-dict-entries-skipped", test_anthropic_to_chat_messages_non_dict_entries_skipped),
    ("anthropic-to-chat-messages-null-user-content", test_anthropic_to_chat_messages_null_user_content),
    ("anthropic-to-chat-tools-transform", test_anthropic_to_chat_tools_transform),
    ("anthropic-to-chat-tools-cache-control-stripped", test_anthropic_to_chat_tools_cache_control_stripped),
    ("anthropic-to-chat-tools-non-list-guarded", test_anthropic_to_chat_tools_non_list_guarded),
    ("anthropic-to-chat-tools-malformed-entries-skipped", test_anthropic_to_chat_tools_malformed_entries_skipped),
    ("anthropic-to-chat-tool-choice-mapping", test_anthropic_to_chat_tool_choice_mapping),
    ("anthropic-to-chat-tool-choice-none-omitted", test_anthropic_to_chat_tool_choice_none_omitted),
    ("anthropic-to-chat-tool-choice-malformed-omitted", test_anthropic_to_chat_tool_choice_malformed_omitted),
    ("anthropic-to-chat-tool-choice-only-with-tools", test_anthropic_to_chat_tool_choice_only_with_tools),
    ("anthropic-to-chat-integration", test_anthropic_to_chat_integration),
    ("anthropic-to-chat-content-block-dropped-trace", test_anthropic_to_chat_content_block_dropped_trace),
    ("anthropic-to-chat-cache-control-stripped-trace", test_anthropic_to_chat_cache_control_stripped_trace),
    ("anthropic-to-chat-nan-infinity-arguments-rejected", test_anthropic_to_chat_nan_infinity_arguments_rejected),
    ("anthropic-to-chat-tool-use-non-dict-input", test_anthropic_to_chat_tool_use_non_dict_input),
    ("anthropic-to-chat-nan-placeholder-with-valid-tool-use", test_anthropic_to_chat_nan_placeholder_with_valid_tool_use),
    ("anthropic-to-chat-tool-result-list-content", test_anthropic_to_chat_tool_result_list_content),
    ("anthropic-to-chat-no-input-mutation", test_anthropic_to_chat_no_input_mutation),
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
    ("chat-to-anthropic-malformed-tool-args-mixed", test_chat_to_anthropic_malformed_tool_args_mixed),
]


if __name__ == "__main__":
    run_cli(ALL_TESTS, "claude-retry-proxy tests: test_chat_transform")
