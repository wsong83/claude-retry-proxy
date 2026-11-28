"""Chat-mode request-transform tool tests: the tools-array conversion,
tool_choice mapping, end-to-end request traces, tool-argument edge cases
(NaN/Infinity, non-dict input, list content, zero-arg calls), and input
non-mutation."""

import uuid
from _harness import _require_server_func, _trace_events_for_request, fail, pass_, run_cli


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
        {"role": "assistant", "content": "Let me look it up.", "tool_calls": [
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
    """NaN tool_use + valid tool_use coexist -> ONE assistant message carrying
    the placeholder text and the surviving tool_calls.

    The placeholder path collapses like the normal path. A turn whose tool
    calls were ALL degraded keeps the placeholder as plain text with no
    ``tool_calls`` key at all — the collapse must not imply one survives.
    """
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
                     "could not be serialized as JSON]"),
         "tool_calls": [
             {"id": "toolu_ok", "type": "function",
              "function": {"name": "g", "arguments": '{"a": 1}'}}]},
    ]
    if out != expected:
        fail("NaN placeholder must share one message with the surviving "
             "tool_calls, got {!r}".format(out))
        return
    evs = [e for e in _trace_events_for_request(rid) if e.get("event") == "tool_args_parse_failure"]
    if not evs:
        fail("expected tool_args_parse_failure trace event, none found")
        return
    if evs[0].get("tool_name") != "f" or evs[0].get("tool_id") != "toolu_nan":
        fail("tool_args_parse_failure missing tool_name/tool_id, got {!r}".format(evs[0]))
        return
    # Every tool call in the turn degraded -> the placeholder stays plain text
    # with no tool_calls key.
    rid2 = "T-" + uuid.uuid4().hex[:8]
    all_bad = fn([
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "toolu_nan2", "name": "f", "input": {"value": float("nan")}},
        ]},
    ], request_id=rid2, mode="chat", provider="p", tier="sonnet")
    if (len(all_bad) != 1 or "tool_calls" in all_bad[0]
            or not isinstance(all_bad[0].get("content"), str)
            or not all_bad[0].get("content")):
        fail("a fully degraded turn must stay placeholder text with no "
             "tool_calls key, got {!r}".format(all_bad))
        return
    pass_("NaN placeholder shares one message with the surviving tool_calls; "
          "an all-degraded turn keeps no tool_calls key")


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


def test_chat_anthropic_to_chat_zero_arg_tool():
    """A zero-argument tool call (arguments "{}") emits a real tool_use block with input {}.

    Step 11 (plan 2026-10-02-drain-after-finish-reason): the buffered chat
    transform's `or parsed_args == {}` over-check previously replaced a
    legitimate zero-argument call with the "[Tool call failed: ...]" text
    placeholder. Dropping it emits `input: {}` and fires no
    tool_args_parse_failure event. Response mode already accepted {}; this
    aligns chat mode with it. Genuinely unparseable arguments still degrade to
    the placeholder (companion assertion below).
    """
    print("\n--- Test: Chat To Anthropic Zero Arg Tool ---")
    fn = _require_server_func("_chat_to_anthropic")
    if fn is None:
        return
    # Zero-argument call: arguments "{}" is valid JSON and a valid tool_use input.
    chat = {"id": "x",
            "choices": [{"index": 0,
                         "message": {"role": "assistant", "content": "",
                                     "tool_calls": [
                                         {"id": "call_zero", "type": "function",
                                          "function": {"name": "zero_arg", "arguments": "{}"}}]},
                         "finish_reason": "tool_calls"}]}
    out = fn(chat, "sonnet", request_id="R0z", mode="chat", provider="p")
    content = out.get("content") if isinstance(out.get("content"), list) else []
    tools = [b for b in content if b.get("type") == "tool_use"]
    if len(tools) != 1:
        fail("zero-arg tool call must emit exactly one tool_use block, got {!r}".format(content))
        return
    if tools[0].get("name") != "zero_arg" or tools[0].get("input") != {}:
        fail("zero-arg tool block must carry input {{}}, got {!r}".format(tools[0]))
        return
    text_blocks = [b for b in content if b.get("type") == "text"]
    if text_blocks:
        fail("zero-arg tool call must not emit a placeholder text block, got {!r}".format(text_blocks))
        return
    if out.get("stop_reason") != "tool_use":
        fail("zero-arg tool call should claim tool_use, got {!r}".format(out.get("stop_reason")))
        return
    if any(ev.get("event") == "tool_args_parse_failure" for ev in _trace_events_for_request("R0z")):
        fail("zero-arg tool call must not fire tool_args_parse_failure")
        return
    # Companion: a genuinely unparseable arguments string still degrades.
    chat_bad = {"id": "x",
                "choices": [{"index": 0,
                             "message": {"role": "assistant", "content": "",
                                         "tool_calls": [
                                             {"id": "call_bad", "type": "function",
                                              "function": {"name": "bad_arg", "arguments": "{not json"}}]},
                             "finish_reason": "tool_calls"}]}
    out_bad = fn(chat_bad, "sonnet", request_id="R0b", mode="chat", provider="p")
    content_bad = out_bad.get("content") if isinstance(out_bad.get("content"), list) else []
    if any(b.get("type") == "tool_use" for b in content_bad):
        fail("unparseable arguments must NOT emit a tool_use block, got {!r}".format(content_bad))
        return
    if not any(b.get("type") == "text" and "bad_arg" in (b.get("text") or "") for b in content_bad):
        fail("unparseable arguments must emit the placeholder text block, got {!r}".format(content_bad))
        return
    if out_bad.get("stop_reason") is not None:
        fail("all-malformed tool calls should force stop_reason None, got {!r}".format(out_bad.get("stop_reason")))
        return
    if not any(ev.get("event") == "tool_args_parse_failure" for ev in _trace_events_for_request("R0b")):
        fail("unparseable arguments must fire tool_args_parse_failure")
        return
    pass_("zero-arg tool call emits input {} with no failure event; unparseable still placeholders")


ALL_TESTS = [
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
    ("chat-zero-arg-tool", test_chat_anthropic_to_chat_zero_arg_tool),
]


if __name__ == "__main__":
    run_cli(ALL_TESTS, "claude-retry-proxy tests: test_chat_transform_tools")
