"""Chat-mode transform tests: the Anthropic-to-Chat request conversion's
message pipeline — thinking blocks, tool_use/tool_result, cache_control,
the reasoning-selection matrix, and the coalesced trace-count contract.

The tools/tool-choice, pattern-sanitization, Chat-to-Anthropic response,
and image-block clusters live in their own modules
(test_chat_transform_tools, test_chat_transform_patterns,
test_chat_transform_chat_to_anthropic, test_chat_transform_images),
chained through this module's ALL_TESTS
(plan 2026-11-28-partition-chat-transform).

Part of the claude-retry-proxy suite; runnable standalone."""

import uuid
from _harness import _require_server_func, _trace_events_for_request, fail, pass_, run_cli
from test_chat_transform_tools import ALL_TESTS as TOOLS_TESTS
from test_chat_transform_patterns import ALL_TESTS as PATTERNS_TESTS
from test_chat_transform_chat_to_anthropic import ALL_TESTS as CHAT_TO_ANTHROPIC_TESTS
from test_chat_transform_images import ALL_TESTS as IMAGES_TESTS


def test_anthropic_to_chat_messages_transform():
    """Full message array (thinking/text/tool_use/tool_result) -> valid OpenAI Chat messages.

    One Anthropic assistant turn becomes ONE OpenAI assistant message: the
    joined text and the tool_calls share the same message.
    """
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
        {"role": "assistant", "content": "Let me check.", "tool_calls": [
            {"id": "toolu_1", "type": "function",
             "function": {"name": "get_weather", "arguments": '{"city": "SF"}'}}]},
        {"role": "tool", "tool_call_id": "toolu_1", "content": "60F"},
        {"role": "user", "content": "thanks"},
    ]
    if out != expected:
        fail("full transform mismatch, got {!r}".format(out))
    else:
        pass_("full message array transformed to the collapsed shape")


def test_anthropic_to_chat_messages_thinking_stripped():
    """thinking is dropped by default (no reasoning echo); redacted_thinking blocks are dropped like empty thinking."""
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
        fail("default selection must emit no reasoning field, got {!r}".format(out))
    else:
        pass_("default emits no reasoning field; redacted_thinking dropped")


def test_anthropic_to_chat_messages_redacted_thinking_dropped():
    """redacted_thinking is dropped and counted in every data shape (plan 2026-11-19).

    The block is unrepresentable in chat mode, so no reasoning field is ever
    fabricated from it: a non-empty-data redacted-only turn forwards the exact
    bare shape at the default selection, is counted in
    content_block_dropped.redacted_thinking, and fires one
    redacted_thinking_detected tripwire event carrying the per-block shape.
    `data: ""` and a block with no `data` are counted the same way — that
    behavior predates the plan and must not regress. With a selected field and
    reasoning_always on, a demanding turn still carries "" (presence, not a
    placeholder) and the injection event counts real=0, empty=1 with no
    placeholder key.
    """
    print("\n--- Test: Anthropic To Chat Messages Redacted Thinking Dropped ---")
    fn = _require_server_func("_transform_anthropic_messages_to_chat")
    if fn is None:
        return

    # (a) Non-empty data, redacted-only turn, default selection: dropped,
    # counted, tripwire fired, no reasoning field, no passthrough event.
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
        fail("a non-empty-data redacted_thinking turn must forward the bare "
             "shape (no reasoning field at the default selection), got "
             "{!r}".format(out))
        return
    evs = _trace_events_for_request(rid)
    dropped = [e for e in evs if e.get("event") == "content_block_dropped"]
    counts = (dropped[0].get("dropped_counts") or {}) if dropped else {}
    if counts.get("redacted_thinking") != 1:
        fail("non-empty-data redacted_thinking must count in "
             "dropped.redacted_thinking, got {!r}".format(counts))
        return
    stale = [e for e in evs if e.get("event") == "redacted_thinking_passthrough"]
    if stale:
        fail("the removed redacted_thinking_passthrough event must not fire, "
             "got {!r}".format(stale))
        return
    det = [e for e in evs if e.get("event") == "redacted_thinking_detected"]
    if len(det) != 1:
        fail("expected exactly ONE redacted_thinking_detected tripwire event, "
             "got {!r}".format(det))
        return
    ev = det[0]
    if not (ev.get("mode") == "chat" and ev.get("provider") == "p"
            and ev.get("tier") == "sonnet" and ev.get("request_id") == rid):
        fail("redacted_thinking_detected missing correlation fields, got "
             "{!r}".format(ev))
        return
    if (ev.get("reasoning_selection") != "none"
            or ev.get("reasoning_always") is not False
            or ev.get("conversation_has_tool_calls") is not False):
        fail("redacted_thinking_detected must carry the policy facts "
             "(selection 'none', always False, no conversation tool calls), "
             "got {!r}".format(ev))
        return
    blocks = ev.get("blocks")
    if blocks != [{"data_length": 3, "turn_has_thinking": False,
                   "turn_tool_use_seen": False}]:
        fail("redacted_thinking_detected blocks must carry one per-block "
             "record with data_length/turn_has_thinking/turn_tool_use_seen, "
             "got {!r}".format(blocks))
        return

    # (b) Empty/missing data: both count (behavior untouched by this plan),
    # and both are recorded by the one per-request tripwire event.
    rid2 = "T-" + uuid.uuid4().hex[:8]
    messages2 = [
        {"role": "assistant", "content": [
            {"type": "redacted_thinking", "data": "", "signature": "s2"},
            {"type": "redacted_thinking", "signature": "s3"},
            {"type": "text", "text": "x"},
        ]},
    ]
    out2 = fn(messages2, request_id=rid2, mode="chat", provider="p", tier="sonnet")
    if out2 != [{"role": "assistant", "content": "x"}]:
        fail("empty/missing-data redacted_thinking must be dropped, got "
             "{!r}".format(out2))
        return
    dropped2 = [e for e in _trace_events_for_request(rid2)
                if e.get("event") == "content_block_dropped"]
    counts2 = (dropped2[0].get("dropped_counts") or {}) if dropped2 else {}
    if counts2.get("redacted_thinking") != 2:
        fail("empty/missing-data redacted_thinking must count in "
             "dropped.redacted_thinking, got {!r}".format(counts2))
        return
    det2 = [e for e in _trace_events_for_request(rid2)
            if e.get("event") == "redacted_thinking_detected"]
    if (len(det2) != 1 or not isinstance(det2[0].get("blocks"), list)
            or len(det2[0]["blocks"]) != 2):
        fail("two redacted blocks in one request must yield ONE tripwire event "
             "with two block records, got {!r}".format(det2))
        return
    if [b.get("data_length") for b in det2[0]["blocks"]] != [0, None]:
        fail("tripwire data_length must be 0 for empty data and null for "
             "missing data, got {!r}".format(det2[0]["blocks"]))
        return

    # (c) Selection + reasoning_always + a tool call: the field carries "",
    # counted empty=1, real=0 — and no placeholder key survives.
    rid3 = "T-" + uuid.uuid4().hex[:8]
    messages3 = [
        {"role": "assistant", "content": [
            {"type": "redacted_thinking", "data": "enc", "signature": "s1"},
            {"type": "tool_use", "id": "t3", "name": "f", "input": {}},
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t3", "content": "ok"},
        ]},
    ]
    out3 = fn(messages3, request_id=rid3, mode="chat", provider="p",
              tier="sonnet", reasoning_selection="reasoning_content",
              reasoning_always=True)
    assistants3 = [m for m in out3 if m.get("role") == "assistant"]
    if [m.get("reasoning_content") for m in assistants3] != [""]:
        fail("an always-on demanding turn whose only reasoning is redacted "
             "must carry \"\" (presence, not a placeholder), got "
             "{!r}".format(assistants3))
        return
    evs3 = _trace_events_for_request(rid3)
    injected = [e for e in evs3 if e.get("event") == "reasoning_field_injected"]
    if len(injected) != 1 or (injected[0].get("real"),
                              injected[0].get("empty")) != (0, 1):
        fail("injection must count real=0 empty=1, got {!r}".format(injected))
        return
    if "placeholder" in injected[0]:
        fail("reasoning_field_injected must not carry the removed placeholder "
             "key, got {!r}".format(injected[0]))
        return
    dropped3 = [e for e in evs3 if e.get("event") == "content_block_dropped"]
    counts3 = (dropped3[0].get("dropped_counts") or {}) if dropped3 else {}
    if counts3.get("redacted_thinking") != 1:
        fail("the dropped block must still be counted on an always-on turn, "
             "got {!r}".format(counts3))
        return
    det3 = [e for e in evs3 if e.get("event") == "redacted_thinking_detected"]
    if len(det3) != 1:
        fail("expected exactly ONE redacted_thinking_detected event, got "
             "{!r}".format(det3))
        return
    if (det3[0].get("reasoning_always") is not True
            or det3[0].get("conversation_has_tool_calls") is not True
            or det3[0].get("blocks") != [{"data_length": 3,
                                          "turn_has_thinking": False,
                                          "turn_tool_use_seen": True}]):
        fail("tripwire must record the always-flag, the conversation tool-call "
             "presence, and the turn's tool_use shape, got {!r}".format(det3[0]))
        return

    # (d) A request with no redacted block emits no tripwire event.
    rid4 = "T-" + uuid.uuid4().hex[:8]
    fn([{"role": "assistant", "content": [
        {"type": "thinking", "thinking": "t", "signature": "s"},
        {"type": "tool_use", "id": "t4", "name": "f", "input": {}},
    ]}, {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "t4", "content": "ok"},
    ]}], request_id=rid4, mode="chat", provider="p", tier="sonnet",
        reasoning_selection="reasoning_content", reasoning_always=True)
    det4 = [e for e in _trace_events_for_request(rid4)
            if e.get("event") == "redacted_thinking_detected"]
    if det4:
        fail("a request with no redacted block must not fire the tripwire, "
             "got {!r}".format(det4))
        return

    pass_("redacted_thinking is dropped and counted in every data shape; one "
          "tripwire event per request carries per-block turn facts; an "
          "always-on demanding turn still carries \"\"")


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
    """Assistant with both text and tool_use -> ONE message carrying text + tool_calls.

    The two-message split (text message, then content:null + tool_calls) is
    gone: the reasoning field must ride the same message the vendor checks,
    and the collapsed form is the ordinary OpenAI shape.
    """
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
        {"role": "assistant", "content": "I'll look that up.", "tool_calls": [
            {"id": "toolu_2", "type": "function", "function": {"name": "f", "arguments": "{}"}}]},
    ]
    if out != expected:
        fail("text and tool_calls must share one assistant message, got {!r}".format(out))
    else:
        pass_("one assistant message carries both the text and the tool_calls")


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
    """Real-world interleaved pattern: thinking, text, tool_use, text in one assistant turn.

    All text parts join into the single collapsed message; at the default
    selection no reasoning field is emitted at all.
    """
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
         "tool_calls": [
             {"id": "toolu_weather", "type": "function",
              "function": {"name": "get_weather", "arguments": '{"city": "San Francisco"}'}}]},
        {"role": "tool", "tool_call_id": "toolu_weather", "content": "Sunny, 72F"},
    ]
    if out != expected:
        fail("interleaved pattern mismatch, got {!r}".format(out))
        return
    if any("reasoning_content" in m or "reasoning" in m for m in out
           if m.get("role") == "assistant"):
        fail("the default selection must emit no reasoning field, got {!r}".format(out))
        return
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

    # --- reasoning_always axis: the policy-scoped always-present field ------
    # Two demanding turns: the first reasoned, the second bare. With
    # `reasoning_always`, every assistant message carries the selected field —
    # the real text where a thinking block exists, "" where none does.
    demanded = [
        {"role": "assistant", "content": [
            {"type": "thinking", "thinking": "hmm", "signature": "s"},
            {"type": "tool_use", "id": "t1", "name": "f", "input": {}},
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": "ok"},
        ]},
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "t2", "name": "f", "input": {}},
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t2", "content": "ok"},
        ]},
    ]

    def always(b, selection):
        return fn(b, request_id="T-" + uuid.uuid4().hex[:8],
                  mode="chat", provider="p", tier="sonnet",
                  reasoning_selection=selection, reasoning_always=True)

    for field in ("reasoning_content", "reasoning"):
        got = [m for m in always(demanded, field) if m.get("role") == "assistant"]
        if [m.get(field) for m in got] != ["hmm", ""]:
            fail("reasoning_always with selection {!r} must carry the real "
                 "text then \"\" on every assistant message, got {!r}".format(
                     field, got))
            return

    # Inert when the conversation carries no tool call: the always-present
    # pass fills nothing, so a bare assistant turn gets no `""` field. (A turn
    # with a real thinking block still echoes it — that is the ordinary
    # selection-driven path, not the injection.)
    no_tool_turn = [{"role": "assistant", "content": [
        {"type": "text", "text": "visible"},
    ]}]
    got = [m for m in always(no_tool_turn, "reasoning_content")
           if m.get("role") == "assistant"]
    if any("reasoning_content" in m or "reasoning" in m for m in got):
        fail("reasoning_always must be inert without a tool-call turn, got "
             "{!r}".format(got))
        return

    # Inert when the learned selection is "none": there is no field name to
    # write, whatever the policy says.
    got = [m for m in always(demanded, "none") if m.get("role") == "assistant"]
    if any("reasoning_content" in m or "reasoning" in m for m in got):
        fail("reasoning_always must be inert when the selection is none, got "
             "{!r}".format(got))
        return

    pass_("reasoning_always axis: real text where a thinking block exists, "
          "\"\" where none does, inert without a tool-call turn, inert at "
          "selection none")


def test_anthropic_to_chat_injection_trace_counts():
    """reasoning_field_injected separates real from empty fills.

    Three demanding turns — real reasoning, a redacted-thinking-only turn (its
    block dropped, so the turn behaves as bare), and a bare one — yield
    real=1, empty=2, and the event fires because the empty fill is non-zero.
    The event carries no placeholder key. A conversation whose every assistant
    turn carries real reasoning fills nothing, so it emits no event and its
    trace cannot be mistaken for a masked-loss alarm.
    """
    print("\n--- Test: Anthropic To Chat Injection Trace Counts ---")
    fn = _require_server_func("_transform_anthropic_messages_to_chat")
    if fn is None:
        return
    messages = [
        {"role": "assistant", "content": [
            {"type": "thinking", "thinking": "real one", "signature": "s"},
            {"type": "tool_use", "id": "t1", "name": "f", "input": {}},
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": "ok"},
        ]},
        {"role": "assistant", "content": [
            {"type": "redacted_thinking", "data": "enc", "signature": "s2"},
            {"type": "tool_use", "id": "t2", "name": "f", "input": {}},
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t2", "content": "ok"},
        ]},
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "t3", "name": "f", "input": {}},
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t3", "content": "ok"},
        ]},
    ]
    rid = "T-" + uuid.uuid4().hex[:8]
    out = fn(messages, request_id=rid, mode="chat", provider="p",
             tier="sonnet", reasoning_selection="reasoning_content",
             reasoning_always=True)
    assistants = [m for m in out if m.get("role") == "assistant"]
    sent = [m.get("reasoning_content") for m in assistants]
    if sent != ["real one", "", ""]:
        fail("injection must fill real text, then \"\" for the redacted-only "
             "turn (its block is dropped) and the bare turn, got "
             "{!r}".format(sent))
        return
    evs = [e for e in _trace_events_for_request(rid)
           if e.get("event") == "reasoning_field_injected"]
    if len(evs) != 1:
        fail("expected exactly ONE reasoning_field_injected event, got {!r}"
             .format(evs))
        return
    ev = evs[0]
    if (ev.get("real"), ev.get("empty")) != (1, 2):
        fail("reasoning_field_injected counters must be real=1 empty=2 (the "
             "redacted-only turn is a bare empty fill, never a placeholder), "
             "got {!r}".format(ev))
        return
    if "placeholder" in ev:
        fail("reasoning_field_injected must not carry the removed placeholder "
             "key, got {!r}".format(ev))
        return
    if not (ev.get("mode") == "chat" and ev.get("provider") == "p"
            and ev.get("tier") == "sonnet" and ev.get("request_id") == rid):
        fail("reasoning_field_injected missing correlation fields, got {!r}"
             .format(ev))
        return

    # All-real conversation: the fill count is zero, so no event fires.
    rid2 = "T-" + uuid.uuid4().hex[:8]
    all_real = [
        {"role": "assistant", "content": [
            {"type": "thinking", "thinking": "real one", "signature": "s"},
            {"type": "tool_use", "id": "t1", "name": "f", "input": {}},
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": "ok"},
        ]},
    ]
    out2 = fn(all_real, request_id=rid2, mode="chat", provider="p",
              tier="sonnet", reasoning_selection="reasoning_content",
              reasoning_always=True)
    got2 = [m for m in out2 if m.get("role") == "assistant"]
    if got2 != [{"role": "assistant", "content": None,
                 "reasoning_content": "real one",
                 "tool_calls": [{"id": "t1", "type": "function",
                                 "function": {"name": "f",
                                              "arguments": "{}"}}]}]:
        fail("the all-real case must still carry the real field, got {!r}"
             .format(got2))
        return
    evs2 = [e for e in _trace_events_for_request(rid2)
            if e.get("event") == "reasoning_field_injected"]
    if evs2:
        fail("an all-real injection fills nothing and must not emit the "
             "event, got {!r}".format(evs2))
        return
    pass_("injection event counts real/empty and fires only when empty > 0")


def test_anthropic_to_chat_real_thinking_and_redacted_dropped():
    """A real `thinking` block still wins on a turn that also carries a
    redacted_thinking block, which is dropped (plan 2026-11-19).

    A `[redacted_thinking, thinking, tool_use]` turn forwards the REAL text and
    fires no `reasoning_field_injected` event: nothing blank was filled. The
    drop is still recorded: `content_block_dropped` counts the block, and the
    tripwire's turn-scoped facts are order-independent —
    `turn_has_thinking` is true because the real text wins wherever the
    redacted block sits in the turn. When a bare turn is present the event does
    fire, and the real-text turn is counted `real=1`.

    Guard: a redacted-only demanding turn forwards `""` (the always-present
    fill), is counted `empty=1` with no placeholder key, and fires
    `content_block_dropped` with `dropped_counts.redacted_thinking == 1`.
    """
    print("\n--- Test: Anthropic To Chat Real Thinking And Redacted Dropped ---")
    fn = _require_server_func("_transform_anthropic_messages_to_chat")
    if fn is None:
        return

    def superseded_turn(call_id):
        return {"role": "assistant", "content": [
            {"type": "redacted_thinking", "data": "enc", "signature": "s1"},
            {"type": "thinking", "thinking": "REAL TEXT", "signature": "s2"},
            {"type": "tool_use", "id": call_id, "name": "f", "input": {}},
        ]}

    def bare_turn(call_id):
        return {"role": "assistant", "content": [
            {"type": "tool_use", "id": call_id, "name": "f", "input": {}},
        ]}

    def tool_result(call_id):
        return {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": call_id, "content": "ok"},
        ]}

    # (a) Superseded turn alone: real text forwarded, nothing blank filled, so
    # no injection event fires. The redacted block is still dropped and
    # counted, and the tripwire's turn facts are order-independent: the real
    # text makes turn_has_thinking true even though the redacted block came
    # FIRST in the turn.
    rid = "T-" + uuid.uuid4().hex[:8]
    out = fn([superseded_turn("t1"), tool_result("t1")], request_id=rid,
             mode="chat", provider="p", tier="sonnet",
             reasoning_selection="reasoning_content", reasoning_always=True)
    assistants = [m for m in out if m.get("role") == "assistant"]
    if [m.get("reasoning_content") for m in assistants] != ["REAL TEXT"]:
        fail("the real thinking text must be forwarded on a turn that also "
             "carried a redacted block, got {!r}".format(assistants))
        return
    evs = [e for e in _trace_events_for_request(rid)
           if e.get("event") == "reasoning_field_injected"]
    if evs:
        fail("nothing blank was filled, so no injection event may fire, got "
             "{!r}".format(evs))
        return
    dropped = [e for e in _trace_events_for_request(rid)
               if e.get("event") == "content_block_dropped"]
    counts = (dropped[0].get("dropped_counts") or {}) if dropped else {}
    if counts.get("redacted_thinking") != 1:
        fail("the dropped redacted block must be counted even when real "
             "thinking supersedes it, got {!r}".format(counts))
        return
    det = [e for e in _trace_events_for_request(rid)
           if e.get("event") == "redacted_thinking_detected"]
    if len(det) != 1:
        fail("expected exactly ONE redacted_thinking_detected event, got "
             "{!r}".format(det))
        return
    if det[0].get("blocks") != [{"data_length": 3,
                                 "turn_has_thinking": True,
                                 "turn_tool_use_seen": True}]:
        fail("the tripwire must record turn_has_thinking true for a "
             "[redacted_thinking, thinking, tool_use] turn — block order is "
             "irrelevant, got {!r}".format(det[0].get("blocks")))
        return

    # (b) Superseded turn plus a bare turn: the event fires with real=1,
    # empty=1 and no placeholder key.
    rid2 = "T-" + uuid.uuid4().hex[:8]
    out2 = fn([superseded_turn("t1"), tool_result("t1"),
               bare_turn("t2"), tool_result("t2")], request_id=rid2,
              mode="chat", provider="p", tier="sonnet",
              reasoning_selection="reasoning_content", reasoning_always=True)
    assistants2 = [m for m in out2 if m.get("role") == "assistant"]
    if [m.get("reasoning_content") for m in assistants2] != ["REAL TEXT", ""]:
        fail("the superseded turn must forward real text and the bare turn "
             "\"\", got {!r}".format(assistants2))
        return
    evs2 = [e for e in _trace_events_for_request(rid2)
            if e.get("event") == "reasoning_field_injected"]
    if len(evs2) != 1:
        fail("expected exactly ONE reasoning_field_injected event, got {!r}"
             .format(evs2))
        return
    if (evs2[0].get("real"), evs2[0].get("empty")) != (1, 1):
        fail("a superseded turn is counted real=1, empty=1, got {!r}"
             .format(evs2[0]))
        return
    if "placeholder" in evs2[0]:
        fail("reasoning_field_injected must not carry the removed placeholder "
             "key, got {!r}".format(evs2[0]))
        return

    # (c) Drop guard: a redacted-only demanding turn forwards "" (the
    # always-present fill), is counted empty, and its block is dropped and
    # counted — never a placeholder.
    rid3 = "T-" + uuid.uuid4().hex[:8]
    redacted_only = {"role": "assistant", "content": [
        {"type": "redacted_thinking", "data": "enc", "signature": "s1"},
        {"type": "tool_use", "id": "t3", "name": "f", "input": {}},
    ]}
    out3 = fn([redacted_only, tool_result("t3")], request_id=rid3,
              mode="chat", provider="p", tier="sonnet",
              reasoning_selection="reasoning_content", reasoning_always=True)
    assistants3 = [m for m in out3 if m.get("role") == "assistant"]
    if [m.get("reasoning_content") for m in assistants3] != [""]:
        fail("a redacted-only demanding turn must forward \"\" (presence), "
             "got {!r}".format(assistants3))
        return
    evs3 = [e for e in _trace_events_for_request(rid3)
            if e.get("event") == "reasoning_field_injected"]
    if len(evs3) != 1 or (evs3[0].get("real"),
                          evs3[0].get("empty")) != (0, 1):
        fail("a redacted-only turn is counted real=0, empty=1, got {!r}"
             .format(evs3))
        return
    if "placeholder" in evs3[0]:
        fail("reasoning_field_injected must not carry the removed placeholder "
             "key, got {!r}".format(evs3[0]))
        return
    dropped3 = [e for e in _trace_events_for_request(rid3)
                if e.get("event") == "content_block_dropped"]
    counts3 = (dropped3[0].get("dropped_counts") or {}) if dropped3 else {}
    if counts3.get("redacted_thinking") != 1:
        fail("a redacted-only demanding turn must count its dropped block, "
             "got {!r}".format(counts3))
        return
    pass_("real thinking wins on a mixed turn (order-independent tripwire "
          "facts, real=1); a redacted-only turn forwards \"\", counted "
          "empty=1 with the block dropped and counted")


def test_anthropic_to_chat_redacted_selection_without_always():
    """Selection active, reasoning_always off: a redacted-only demanding turn
    forwards NO reasoning field at attempt 1 (accepted presence delta, plan
    2026-11-19).

    This is the unflagged-pair state (a learned selection on a (provider,
    model) pair with no reasoning_roundtrip flag): the block is unrepresentable
    and nothing fills the field, so the forwarded message is bare while the
    drop and the tripwire are still recorded. The reasoning_field rescue is the
    backstop at request time; this pin holds the transform-level behavior that
    makes the rescue necessary, and fails if an always-fill is reintroduced
    outside the reasoning_always policy.
    """
    print("\n--- Test: Anthropic To Chat Redacted Selection Without Always ---")
    fn = _require_server_func("_transform_anthropic_messages_to_chat")
    if fn is None:
        return
    rid = "T-" + uuid.uuid4().hex[:8]
    messages = [
        {"role": "assistant", "content": [
            {"type": "redacted_thinking", "data": "enc", "signature": "s1"},
            {"type": "tool_use", "id": "t1", "name": "f", "input": {}},
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": "ok"},
        ]},
    ]
    out = fn(messages, request_id=rid, mode="chat", provider="p",
             tier="sonnet", reasoning_selection="reasoning_content")
    assistants = [m for m in out if m.get("role") == "assistant"]
    if len(assistants) != 1:
        fail("expected one assistant message, got {!r}".format(assistants))
        return
    m = assistants[0]
    if "reasoning_content" in m or "reasoning" in m:
        fail("with a selection but no always-flag, the redacted-only turn must "
             "forward no reasoning field, got {!r}".format(m))
        return
    evs = _trace_events_for_request(rid)
    dropped = [e for e in evs if e.get("event") == "content_block_dropped"]
    counts = (dropped[0].get("dropped_counts") or {}) if dropped else {}
    if counts.get("redacted_thinking") != 1:
        fail("the dropped block must be counted, got {!r}".format(counts))
        return
    det = [e for e in evs if e.get("event") == "redacted_thinking_detected"]
    if len(det) != 1:
        fail("expected exactly ONE redacted_thinking_detected event, got "
             "{!r}".format(det))
        return
    if (det[0].get("reasoning_selection") != "reasoning_content"
            or det[0].get("reasoning_always") is not False
            or det[0].get("conversation_has_tool_calls") is not True):
        fail("the tripwire must capture the learned selection, the absent "
             "always-flag, and the conversation's tool calls, got "
             "{!r}".format(det[0]))
        return
    if det[0].get("blocks") != [{"data_length": 3,
                                 "turn_has_thinking": False,
                                 "turn_tool_use_seen": True}]:
        fail("the tripwire must record the turn's tool_use shape, got "
             "{!r}".format(det[0].get("blocks")))
        return
    injected = [e for e in evs if e.get("event") == "reasoning_field_injected"]
    if injected:
        fail("no always-pass ran, so no reasoning_field_injected event may "
             "fire, got {!r}".format(injected))
        return
    pass_("selection without reasoning_always forwards no field on a "
          "redacted-only demanding turn; the drop and tripwire still fire, "
          "and no injection event does")


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


ALL_TESTS = [
    ("anthropic-to-chat-messages-transform", test_anthropic_to_chat_messages_transform),
    ("anthropic-to-chat-messages-thinking-stripped", test_anthropic_to_chat_messages_thinking_stripped),
    ("anthropic-to-chat-messages-redacted-thinking-dropped", test_anthropic_to_chat_messages_redacted_thinking_dropped),
    ("anthropic-to-chat-messages-tool-use-to-tool-calls", test_anthropic_to_chat_messages_tool_use_to_tool_calls),
    ("anthropic-to-chat-messages-tool-result-to-role-tool", test_anthropic_to_chat_messages_tool_result_to_role_tool),
    ("anthropic-to-chat-messages-mixed-text-and-tool-use", test_anthropic_to_chat_messages_mixed_text_and_tool_use),
    ("anthropic-to-chat-messages-mixed-text-and-tool-result", test_anthropic_to_chat_messages_mixed_text_and_tool_result),
    ("anthropic-to-chat-messages-interleaved-thinking-tool-use", test_anthropic_to_chat_messages_interleaved_thinking_tool_use),
    ("chat-transform-emits-only-selected-field", test_chat_transform_emits_only_selected_field),
    ("anthropic-to-chat-injection-trace-counts", test_anthropic_to_chat_injection_trace_counts),
    ("anthropic-to-chat-real-thinking-and-redacted-dropped", test_anthropic_to_chat_real_thinking_and_redacted_dropped),
    ("anthropic-to-chat-redacted-selection-without-always", test_anthropic_to_chat_redacted_selection_without_always),
    ("anthropic-to-chat-messages-string-content-passthrough", test_anthropic_to_chat_messages_string_content_passthrough),
    ("anthropic-to-chat-messages-cache-control-stripped", test_anthropic_to_chat_messages_cache_control_stripped),
    ("anthropic-to-chat-messages-non-list-guarded", test_anthropic_to_chat_messages_non_list_guarded),
    ("anthropic-to-chat-messages-non-dict-entries-skipped", test_anthropic_to_chat_messages_non_dict_entries_skipped),
    ("anthropic-to-chat-messages-null-user-content", test_anthropic_to_chat_messages_null_user_content),
] + TOOLS_TESTS + PATTERNS_TESTS + CHAT_TO_ANTHROPIC_TESTS + IMAGES_TESTS


if __name__ == "__main__":
    run_cli(ALL_TESTS, "claude-retry-proxy tests: test_chat_transform")
