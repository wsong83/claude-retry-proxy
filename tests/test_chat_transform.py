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

from claude_retry_proxy.transforms_common import (
    _sanitize_body_tools,
    _sanitize_schema_patterns,
    _strip_regex_identity_escapes,
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
        {"role": "assistant", "content": "Let me check."},
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
    """thinking is dropped by default (no reasoning echo); redacted_thinking non-empty data is folded into the same default."""
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
    expected = [{"role": "assistant", "content": "visible"}]
    if out != expected:
        fail("default selection must emit no reasoning field (real thinking still wins over the redacted placeholder), got {!r}".format(out))
    else:
        pass_("default emits no reasoning field; redacted_thinking placeholder suppressed by real thinking")




def test_anthropic_to_chat_messages_redacted_thinking_trace():
    """redacted_thinking with non-empty data -> placeholder reasoning text + passthrough trace event.

    The placeholder rides the same selection-dependent echo path as real
    thinking, so at the default selection no field is emitted at all. Real
    thinking text wins over the placeholder. Empty data is stripped and counted
    in dropped.redacted_thinking, not passed through.
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
    expected = [{"role": "assistant", "content": "visible"}]
    if out != expected:
        fail("default selection must emit no reasoning field for a redacted placeholder, got {!r}".format(out))
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
    if out2 != [{"role": "assistant", "content": ""}]:
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
         "content": "Let me look up the weather for San Francisco.\nI found the forecast."},
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "toolu_weather", "type": "function",
             "function": {"name": "get_weather", "arguments": '{"city": "San Francisco"}'}}]},
        {"role": "tool", "tool_call_id": "toolu_weather", "content": "Sunny, 72F"},
    ]
    if out != expected:
        fail("interleaved pattern mismatch, got {!r}".format(out))
    else:
        pass_("interleaved thinking/text/tool_use pattern transformed with no reasoning echo at the default")




# Sentinel for "the caller omitted reasoning_selection entirely".
_OMIT = object()


def test_chat_transform_emits_only_selected_field():
    """The request-direction reasoning echo is selection-driven: only the two
    field-name strings emit a field, everything else (including the omitted
    argument, None, and unrecognized values) emits none — and never both."""
    print("\n--- Test: Chat Transform Emits Only Selected Field ---")
    fn = _require_server_func("_transform_anthropic_messages_to_chat")
    if fn is None:
        return
    messages = [
        {"role": "assistant", "content": [
            {"type": "thinking", "thinking": "hmm", "signature": "s"},
            {"type": "text", "text": "visible"},
        ]},
    ]

    def emit(selection):
        kwargs = {}
        if selection is not _OMIT:
            kwargs["reasoning_selection"] = selection
        out = fn(messages, request_id="T-" + uuid.uuid4().hex[:8],
                 mode="chat", provider="p", tier="sonnet", **kwargs)
        return out[0] if out else None

    base = {"role": "assistant", "content": "visible"}
    no_echo = [
        ("omitted-argument", _OMIT),
        ("none-string", "none"),
        ("None-value", None),
        ("unrecognized-value", "both"),
        ("case-variant", "Reasoning_Content"),
        ("empty-string", ""),
    ]
    for label, selection in no_echo:
        got = emit(selection)
        if got != base:
            fail("%s must emit no reasoning field, got {!r}".format(
                label, got))
            return

    for field in ("reasoning_content", "reasoning"):
        got = emit(field)
        expected = dict(base)
        expected[field] = "hmm"
        if got != expected:
            fail("selection {!r} must emit that field only, got {!r}".format(
                field, got))
            return
        other = ("reasoning" if field == "reasoning_content"
                 else "reasoning_content")
        if other in got:
            fail("selection {!r} must never emit the other field, got "
                 "{!r}".format(field, got))
            return

    pass_("selection matrix: only the two field names emit, never both, "
          "everything else (including omission) emits none")


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




def test_strip_regex_identity_escapes_table():
    """_strip_regex_identity_escapes implements the plan's reference table exactly.

    Plan 2026-10-06-re2-portable-tool-schema-patterns, Step 1: the sanitizer
    rewrites one JSON-Schema `pattern` regex by dropping ECMA identity
    escapes (backslash before a non-metacharacter symbol), while preserving
    every meaningful escape (ASCII letter/digit-introduced) and the
    metacharacter escapes. The class tracker keeps `\\-` inside a character
    class and drops it outside. One row per table entry so a regression in
    any single rule fails loudly.
    """
    print("\n--- Test: Strip Regex Identity Escapes Table ---")
    # backslash built at runtime so this file never carries a \ + u escape
    # sequence that a tool layer might mangle on write
    _bs = chr(92)
    unicode_escape = _bs + "u0041"
    # (raw input, expected output, why) -- the plan's reference table.
    table = [
        (r"^agent\_run\_", r"^agent_run_", "the reported bug"),
        (r"foo\-bar", "foo-bar", "- outside class is identity"),
        (r"[a\-z]", r"[a\-z]", "- inside class is a literal-hyphen escape (kept)"),
        (r"[a\-z]\-x", r"[a\-z]-x", "mixed: in-class kept, out-of-class dropped"),
        (r"\d{1,3}\.\d+", r"\d{1,3}\.\d+", "\\d (letter), \\. (metachar) meaningful"),
        (r"\.\^\[\]\{\}\\\*\+\?\$\|", r"\.\^\[\]\{\}\\\*\+\?\$\|",
         "all metacharacter escapes unchanged"),
        (r"\s\w\n\t\x41" + unicode_escape + r"\p{L}\Qx\E\0",
         r"\s\w\n\t\x41" + unicode_escape + r"\p{L}\Qx\E\0",
         "every escape is letter/digit-introduced"),
        (r"a\/b\:c\@d\!\#e", "a/b:c@d!#e", "/ and punctuation are identity"),
        (r"\ ", " ", "whitespace is identity"),
        ("ab\\", "ab\\", "trailing escape copied verbatim"),
        ("", "", "empty passthrough"),
    ]
    for raw, expected, why in table:
        out = _strip_regex_identity_escapes(raw)
        if out != expected:
            fail("row {!r} -> {!r}, expected {!r} ({})".format(raw, out, expected, why))
            return
    pass_("all 11 reference-table rows transformed correctly")




def test_sanitize_schema_patterns_walk():
    """_sanitize_schema_patterns rewrites pattern/patternProperties at every depth.

    Nested schema: `pattern` under properties, items, anyOf[0] and a nested
    $defs entry; a patternProperties object whose string keys carry escapes
    and whose values recurse to their own pattern; totality -- a non-string
    `pattern` value, a non-string patternProperties key, non-dict/list nodes
    (scalars, lists of scalars) all pass through unchanged.
    """
    print("\n--- Test: Sanitize Schema Patterns Walk ---")
    schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "pattern": r"^agent\_run\_"},
            "arr": {"type": "array", "items": {"type": "string", "pattern": r"foo\-bar"}},
        },
        "anyOf": [
            {"type": "string", "pattern": r"a\/b"},
            {"type": "number"},
        ],
        "patternProperties": {
            r"^k\-e\_\d": {"type": "string", "pattern": r"nested\/p"},
            7: {"pattern": r"kept\-p"},
        },
        "not": {"pattern": 42},          # non-string pattern -> untouched
        "$defs": {"sub": {"pattern": r"deep\-x"}},
        "scalar": "plain",               # non-dict node -> untouched
        "list": ["a", 7, None],          # list of scalars -> untouched
    }
    out = _sanitize_schema_patterns(schema)
    checks = [
        (out["properties"]["name"]["pattern"], "^agent_run_", "properties depth"),
        (out["properties"]["arr"]["items"]["pattern"], "foo-bar", "items depth"),
        (out["anyOf"][0]["pattern"], "a/b", "anyOf depth"),
        (out["$defs"]["sub"]["pattern"], "deep-x", "$defs depth"),
        (list(out["patternProperties"].keys())[0], r"^k-e_\d",
         "patternProperties key stripped (identity escapes dropped, \\d kept)"),
        (out["patternProperties"][r"^k-e_\d"]["pattern"], "nested/p",
         "patternProperties value recursed"),
        (out["patternProperties"][7]["pattern"], "kept-p",
         "non-string key preserved, its value still recursed"),
        (out["not"]["pattern"], 42, "non-string pattern passes through"),
        (out["scalar"], "plain", "scalar node passes through"),
        (out["list"], ["a", 7, None], "scalar list passes through"),
    ]
    for got, expected, label in checks:
        if got != expected:
            fail("{}: got {!r}, expected {!r}".format(label, got, expected))
            return
    pass_("walk sanitizes both regex-typed locations at every depth; totality holds")




def test_sanitize_schema_patterns_no_mutation():
    """_sanitize_schema_patterns never mutates its argument; returns a new structure."""
    print("\n--- Test: Sanitize Schema Patterns No Mutation ---")
    import copy
    schema = {
        "type": "object",
        "properties": {"n": {"type": "string", "pattern": r"^agent\_run\_"}},
        "patternProperties": {r"p\-": {"pattern": r"q\/"}},
        "anyOf": [{"pattern": r"a\-b"}],
    }
    snapshot = copy.deepcopy(schema)
    out = _sanitize_schema_patterns(schema)
    if schema != snapshot:
        fail("input schema was mutated: {!r}".format(schema))
        return
    if out is schema:
        fail("returned object is the input itself (must be a copy)")
        return
    if out["properties"] is schema["properties"]:
        fail("nested dict shared with input (shallow copy), not rebuilt")
        return
    if out["properties"]["n"]["pattern"] != "^agent_run_":
        fail("expected sanitized copy, got {!r}".format(out["properties"]["n"]["pattern"]))
        return
    pass_("input unchanged; fresh structure returned with sanitized patterns")




def test_sanitize_schema_patterns_value_positions():
    """Step 4a: value keywords verbatim, name->schema map values sanitized.

    Plan 2026-10-06-re2-portable-tool-schema-patterns, Step 4 (review finding
    2): `const`/`enum`/`default`/`examples` hold asserted DATA, so a
    `pattern`-keyed string inside them must survive byte-for-byte at any
    depth, while a property legitimately *named* `default` (or `const`,
    `enum`) is a name->schema map entry whose subschema IS walked — both
    directions of the position split. `$defs`/`definitions`/`dependentSchemas`
    behave the same way: keys are names, values are schemas.
    """
    print("\n--- Test: Sanitize Schema Patterns Value Positions ---")
    import copy
    schema = {
        # asserted data: byte-for-byte, at any depth
        "const": {"pattern": r"^agent\_run\_",
                  "nested": {"pattern": r"foo\-bar"}},
        "enum": [{"pattern": r"a\/b"}, r"str\-x"],
        "default": {"pattern": r"def\-ault"},
        "examples": [{"pattern": r"exa\-mple"}],
        # name->schema maps: names never rewritten, values are schemas
        "properties": {
            "default": {"type": "string", "pattern": r"^agent\_run\_"},
            "const": {"type": "string", "pattern": r"foo\-bar"},
            "enum": {"type": "string", "pattern": r"keep\-d"},
        },
        "$defs": {"default": {"pattern": r"defs\-p"}},
        "definitions": {"examples": {"pattern": r"defn\-p"}},
        "dependentSchemas": {"const": {"pattern": r"dep\-p"}},
        # a `default` inside an ordinary subschema is still asserted data
        "items": {"type": "string", "default": {"pattern": r"item\-d"}},
    }
    snapshot = copy.deepcopy(schema)
    out = _sanitize_schema_patterns(schema)
    checks = [
        (out["const"]["pattern"], r"^agent\_run\_", "const value verbatim"),
        (out["const"]["nested"]["pattern"], r"foo\-bar",
         "nested-under-const value verbatim"),
        (out["enum"][0]["pattern"], r"a\/b", "dict enum entry verbatim"),
        (out["enum"][1], r"str\-x", "scalar enum entry verbatim"),
        (out["default"]["pattern"], r"def\-ault", "default value verbatim"),
        (out["examples"][0]["pattern"], r"exa\-mple", "examples value verbatim"),
        (out["items"]["default"]["pattern"], r"item\-d",
         "default inside an ordinary subschema verbatim"),
        (out["properties"]["default"]["pattern"], "^agent_run_",
         "property named default sanitized"),
        (out["properties"]["const"]["pattern"], "foo-bar",
         "property named const sanitized"),
        (out["properties"]["enum"]["pattern"], "keep-d",
         "property named enum sanitized"),
        (out["$defs"]["default"]["pattern"], "defs-p",
         "$defs name kept, its value sanitized"),
        (out["definitions"]["examples"]["pattern"], "defn-p",
         "definitions name kept, its value sanitized"),
        (out["dependentSchemas"]["const"]["pattern"], "dep-p",
         "dependentSchemas name kept, its value sanitized"),
    ]
    for got, expected, label in checks:
        if got != expected:
            fail("{}: got {!r}, expected {!r}".format(label, got, expected))
            return
    if set(out["properties"]) != {"default", "const", "enum"}:
        fail("property names rewritten: {!r}".format(list(out["properties"])))
        return
    if out["const"] is schema["const"]:
        fail("value-keyword subtree shared with input (not a fresh copy)")
        return
    if schema != snapshot:
        fail("input schema was mutated: {!r}".format(schema))
        return
    pass_("value keywords verbatim; name-map keys kept, their schemas sanitized")




def test_sanitize_schema_patterns_collision_merge():
    """Step 4b: colliding patternProperties keys merge as allOf; none dropped.

    Plan 2026-10-06-re2-portable-tool-schema-patterns, Step 4 (review finding
    3): source keys differing only by identity escapes strip to the same
    output key. The merge keeps BOTH subschemas under `{"allOf": [...]}`,
    chained for repeated collisions, while a key that does not collide
    survives untouched beside it and a non-string key still passes through
    with its value recursed.
    """
    print("\n--- Test: Sanitize Schema Patterns Collision Merge ---")
    import copy
    schema = {
        "patternProperties": {
            # three distinct sources, one output key: ^a-b-c
            r"^a\-b\-c": {"type": "string", "pattern": r"p\-1"},
            r"^a-b\-c": {"type": "string", "pattern": r"p\-2"},
            r"^a-b-c": {"type": "string", "pattern": r"p\-3"},
            # non-colliding key: must be preserved as-is
            r"^k\-e\_\d": {"type": "string", "pattern": r"keep\-p"},
            # non-string key: left alone, value still recursed
            7: {"pattern": r"non\-string"},
        },
    }
    snapshot = copy.deepcopy(schema)
    out = _sanitize_schema_patterns(schema)
    pp = out["patternProperties"]
    if schema != snapshot:
        fail("input schema was mutated: {!r}".format(schema))
        return
    if len(pp) != 3:
        fail("expected 3 output keys (3 sources collide to one), got {}: "
             "{!r}".format(len(pp), list(pp)))
        return
    if r"^a-b-c" not in pp:
        fail("collided output key missing: {!r}".format(list(pp)))
        return
    expect_merged = {"allOf": [
        {"allOf": [{"type": "string", "pattern": "p-1"},
                   {"type": "string", "pattern": "p-2"}]},
        {"type": "string", "pattern": "p-3"},
    ]}
    if pp[r"^a-b-c"] != expect_merged:
        fail("collision merge wrong: got {!r}, expected {!r}".format(
            pp[r"^a-b-c"], expect_merged))
        return
    if pp[r"^k-e_\d"] != {"type": "string", "pattern": "keep-p"}:
        fail("non-colliding key altered: {!r}".format(pp.get(r"^k-e_\d")))
        return
    if pp.get(7) != {"pattern": "non-string"}:
        fail("non-string key/value handling altered: {!r}".format(pp.get(7)))
        return
    pass_("collisions merge as chained allOf (no entry dropped); "
          "non-colliding and non-string keys preserved")




def test_anthropic_to_chat_tools_pattern_sanitized():
    """Chat mode: input_schema.pattern identity escapes stripped before forwarding.

    Integration for Step 2's chat call site: a tool whose input_schema
    carries Zod's `^agent\\_run\\_` pattern reaches the backend as
    `^agent_run_` in function.parameters, and the input tools list is
    unmutated (the transforms' declared no-mutation contract).
    """
    print("\n--- Test: Anthropic To Chat Tools Pattern Sanitized ---")
    fn = _require_server_func("_transform_anthropic_tools_to_chat")
    if fn is None:
        return
    import copy
    tools = [
        {"name": "mcp__exa__agent_run",
         "input_schema": {"type": "object",
                          "properties": {"query": {"type": "string",
                                                  "pattern": r"^agent\_run\_"}},
                          "patternProperties": {r"^k\-": {"type": "string"}}}},
    ]
    snapshot = copy.deepcopy(tools)
    out = fn(tools, request_id="T-" + uuid.uuid4().hex[:8], mode="chat",
             provider="p", tier="sonnet")
    params = out[0]["function"]["parameters"]
    if params["properties"]["query"]["pattern"] != "^agent_run_":
        fail("parameters.pattern not sanitized, got {!r}".format(
            params["properties"]["query"]["pattern"]))
        return
    if list(params["patternProperties"].keys())[0] != "^k-":
        fail("patternProperties key not sanitized, got {!r}".format(
            list(params["patternProperties"].keys())))
        return
    if tools != snapshot:
        fail("input tools list was mutated: {!r}".format(tools))
        return
    pass_("chat parameters sanitized (pattern + patternProperties key); input unmutated")




def test_sanitize_body_tools_sanitized_copy():
    """_sanitize_body_tools returns a sanitized copy; input never mutated.

    Plan 2026-10-06-re2-portable-tool-schema-patterns, Step 3: the
    anthropic-mode verbatim forward calls this helper, so every dict
    `tools[i]["input_schema"]` must arrive sanitized (pattern value and
    patternProperties key), other tool/body fields must be preserved
    verbatim, and the returned body must be a fresh object — the parsed
    client body is never mutated in place.
    """
    print("\n--- Test: Sanitize Body Tools Sanitized Copy ---")
    import copy
    body = {
        "model": "sonnet",
        "messages": [{"role": "user", "content": "hi"}],
        "tools": [{"name": "mcp__exa__agent_run",
                   "description": "run a research agent",
                   "input_schema": {"type": "object",
                                    "properties": {"query": {"type": "string",
                                                             "pattern": r"^agent\_run\_"}},
                                    "patternProperties": {r"^k\-": {"type": "string"}}}},
                  {"name": "plain", "input_schema": {"type": "object",
                                                     "properties": {}}}],
    }
    snapshot = copy.deepcopy(body)
    out = _sanitize_body_tools(body)
    if out is body:
        fail("returned body is the input itself (must be a copy)")
        return
    if body != snapshot:
        fail("input body was mutated: {!r}".format(body))
        return
    if out["tools"][0] is body["tools"][0]:
        fail("tool entry shared with input (shallow), not rebuilt")
        return
    schema = out["tools"][0]["input_schema"]
    if schema["properties"]["query"]["pattern"] != "^agent_run_":
        fail("input_schema.pattern not sanitized, got {!r}".format(
            schema["properties"]["query"]["pattern"]))
        return
    if list(schema["patternProperties"].keys())[0] != "^k-":
        fail("patternProperties key not sanitized, got {!r}".format(
            list(schema["patternProperties"].keys())))
        return
    if out["tools"][0]["description"] != "run a research agent":
        fail("tool description lost: {!r}".format(out["tools"][0].get("description")))
        return
    if out["tools"][1] != {"name": "plain",
                           "input_schema": {"type": "object", "properties": {}}}:
        fail("pattern-free tool altered: {!r}".format(out["tools"][1]))
        return
    if out.get("model") != "sonnet" or out.get("messages") != body["messages"]:
        fail("non-tool body fields altered: {!r}".format(out))
        return
    pass_("body copied with sanitized tool schemas; other fields and input preserved")




def test_sanitize_body_tools_totality():
    """_sanitize_body_tools is total: malformed bodies pass through unchanged.

    Step 3's helper must never raise on the request path: a non-dict body,
    a missing or non-list `tools`, a non-dict tool entry, and a non-dict
    `input_schema` all pass through (the parsed client body may be any
    valid JSON), and none of them mutate their input.
    """
    print("\n--- Test: Sanitize Body Tools Totality ---")
    import copy
    cases = [
        ("non-dict body (list)", [1, 2, 3]),
        ("non-dict body (str)", "not a body"),
        ("absent tools", {"model": "sonnet", "messages": []}),
        ("non-list tools", {"model": "sonnet", "tools": "oops"}),
        ("null tools", {"model": "sonnet", "tools": None}),
        ("non-dict tool entries", {"tools": ["garbage", 42, None]}),
        ("tool without input_schema", {"tools": [{"name": "bare"}]}),
        ("non-dict input_schema", {"tools": [{"name": "t", "input_schema": "notdict"}]}),
    ]
    for label, body in cases:
        snapshot = copy.deepcopy(body)
        out = _sanitize_body_tools(body)
        if body != snapshot:
            fail("{}: input was mutated: {!r}".format(label, body))
            return
        if out != body:
            fail("{}: expected passthrough, got {!r}".format(label, out))
            return
    pass_("all 8 malformed-body cases pass through unchanged, input untouched")




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
        {"role": "assistant", "content": "Let me look it up."},
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
    ("anthropic-to-chat-messages-transform", test_anthropic_to_chat_messages_transform),
    ("anthropic-to-chat-messages-thinking-stripped", test_anthropic_to_chat_messages_thinking_stripped),
    ("anthropic-to-chat-messages-redacted-thinking-trace", test_anthropic_to_chat_messages_redacted_thinking_trace),
    ("anthropic-to-chat-messages-tool-use-to-tool-calls", test_anthropic_to_chat_messages_tool_use_to_tool_calls),
    ("anthropic-to-chat-messages-tool-result-to-role-tool", test_anthropic_to_chat_messages_tool_result_to_role_tool),
    ("anthropic-to-chat-messages-mixed-text-and-tool-use", test_anthropic_to_chat_messages_mixed_text_and_tool_use),
    ("anthropic-to-chat-messages-mixed-text-and-tool-result", test_anthropic_to_chat_messages_mixed_text_and_tool_result),
    ("anthropic-to-chat-messages-interleaved-thinking-tool-use", test_anthropic_to_chat_messages_interleaved_thinking_tool_use),
    ("chat-transform-emits-only-selected-field", test_chat_transform_emits_only_selected_field),
    ("anthropic-to-chat-messages-string-content-passthrough", test_anthropic_to_chat_messages_string_content_passthrough),
    ("anthropic-to-chat-messages-cache-control-stripped", test_anthropic_to_chat_messages_cache_control_stripped),
    ("anthropic-to-chat-messages-non-list-guarded", test_anthropic_to_chat_messages_non_list_guarded),
    ("anthropic-to-chat-messages-non-dict-entries-skipped", test_anthropic_to_chat_messages_non_dict_entries_skipped),
    ("anthropic-to-chat-messages-null-user-content", test_anthropic_to_chat_messages_null_user_content),
    ("anthropic-to-chat-tools-transform", test_anthropic_to_chat_tools_transform),
    ("anthropic-to-chat-tools-cache-control-stripped", test_anthropic_to_chat_tools_cache_control_stripped),
    ("anthropic-to-chat-tools-non-list-guarded", test_anthropic_to_chat_tools_non_list_guarded),
    ("anthropic-to-chat-tools-malformed-entries-skipped", test_anthropic_to_chat_tools_malformed_entries_skipped),
    ("strip-regex-identity-escapes-table", test_strip_regex_identity_escapes_table),
    ("sanitize-schema-patterns-walk", test_sanitize_schema_patterns_walk),
    ("sanitize-schema-patterns-no-mutation", test_sanitize_schema_patterns_no_mutation),
    ("sanitize-schema-patterns-value-positions", test_sanitize_schema_patterns_value_positions),
    ("sanitize-schema-patterns-collision-merge", test_sanitize_schema_patterns_collision_merge),
    ("anthropic-to-chat-tools-pattern-sanitized", test_anthropic_to_chat_tools_pattern_sanitized),
    ("sanitize-body-tools-sanitized-copy", test_sanitize_body_tools_sanitized_copy),
    ("sanitize-body-tools-totality", test_sanitize_body_tools_totality),
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
    ("chat-zero-arg-tool", test_chat_anthropic_to_chat_zero_arg_tool),
]


if __name__ == "__main__":
    run_cli(ALL_TESTS, "claude-retry-proxy tests: test_chat_transform")
