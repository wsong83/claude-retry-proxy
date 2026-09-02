"""Response-mode transform tests: Anthropic-to-Responses input item
conversion and Responses-to-Anthropic output conversion.

Part of the claude-retry-proxy suite; runnable standalone.
"""

import json

from _harness import (
    _require_server_func,
    fail,
    pass_,
    run_cli,
)




# --- Step 6: _anthropic_to_response ---

def test_anthropic_to_response_basic():
    """model, input items, instructions, max_output_tokens, stream mapped."""
    print("\n--- Test: Anthropic To Response Basic ---")
    fn = _require_server_func("_anthropic_to_response")
    if fn is None:
        return
    inp = {"model": "sonnet",
           "messages": [{"role": "user", "content": "hi"}],
           "system": "Be concise",
           "max_tokens": 50,
           "temperature": 0.5,
           "top_p": 0.9,
           "stream": True}
    out = fn(inp)
    if not isinstance(out, dict):
        fail("_anthropic_to_response must return a dict")
        return
    expected_input = [{"type": "message", "role": "user",
                       "content": [{"type": "input_text", "text": "hi"}]}]
    checks = [
        (out.get("model") == "sonnet", "model pass-through"),
        (out.get("stream") is False, "stream forced false"),
        (out.get("input") == expected_input, "input is full-history message items"),
        (out.get("instructions") == "Be concise", "system -> instructions"),
        (out.get("max_output_tokens") == 50, "max_tokens -> max_output_tokens"),
        (out.get("temperature") == 0.5, "temperature pass-through"),
        (out.get("top_p") == 0.9, "top_p pass-through"),
        ("messages" not in out, "messages dropped"),
    ]
    for ok, label in checks:
        if not ok:
            fail("basic response mapping failed: {}".format(label))
    if all(ok for ok, _ in checks):
        pass_("anthropic->response basic mapping correct")




def test_anthropic_to_response_system_list():
    """system content block list concatenates into instructions."""
    print("\n--- Test: Anthropic To Response System List ---")
    fn = _require_server_func("_anthropic_to_response")
    if fn is None:
        return
    inp = {"model": "sonnet",
           "messages": [{"role": "user", "content": "hi"}],
           "system": [{"type": "text", "text": "A"}, {"type": "text", "text": "B"}]}
    out = fn(inp)
    if out.get("instructions") != "A\nB":
        fail("expected instructions 'A\\nB', got {!r}".format(out.get("instructions")))
    else:
        pass_("system list concatenated to instructions")




def test_anthropic_to_response_multiple_user_messages():
    """Full ordered history becomes message items (not last-user-only)."""
    print("\n--- Test: Anthropic To Response Multiple User Messages ---")
    fn = _require_server_func("_anthropic_to_response")
    if fn is None:
        return
    inp = {"model": "sonnet",
           "messages": [{"role": "user", "content": "first"},
                        {"role": "assistant", "content": "resp"},
                        {"role": "user", "content": [{"type": "text", "text": "secX"},
                                                     {"type": "text", "text": "secY"}]}]}
    out = fn(inp)
    expected = [
        {"type": "message", "role": "user",
         "content": [{"type": "input_text", "text": "first"}]},
        {"type": "message", "role": "assistant",
         "content": [{"type": "output_text", "text": "resp"}]},
        {"type": "message", "role": "user",
         "content": [{"type": "input_text", "text": "secX\nsecY"}]},
    ]
    if out.get("input") != expected:
        fail("expected full ordered history items, got {!r}".format(out.get("input")))
    else:
        pass_("full history preserved in order as message items")




def test_anthropic_to_response_no_user_message():
    """Empty or absent messages yield input: []."""
    print("\n--- Test: Anthropic To Response No User Message ---")
    fn = _require_server_func("_anthropic_to_response")
    if fn is None:
        return
    out = fn({"model": "sonnet", "messages": []})
    if out.get("input") != []:
        fail("expected input [] for empty messages, got {!r}".format(out.get("input")))
    else:
        pass_("empty messages -> input []")
    out = fn({"model": "sonnet"})
    if out.get("input") != []:
        fail("expected input [] for absent messages, got {!r}".format(out.get("input")))
    else:
        pass_("absent messages -> input []")




def test_anthropic_to_response_stream_forced_false():
    """stream is always false regardless of the client's stream flag."""
    print("\n--- Test: Anthropic To Response Stream Forced False ---")
    fn = _require_server_func("_anthropic_to_response")
    if fn is None:
        return
    ok = True
    for stream_flag in (True, False):
        inp = {"model": "sonnet",
               "messages": [{"role": "user", "content": "hi"}],
               "stream": stream_flag}
        out = fn(inp)
        if out.get("stream") is not False:
            fail("stream should be false, input flag was {!r}".format(stream_flag))
            ok = False
    inp_missing = {"model": "sonnet", "messages": [{"role": "user", "content": "hi"}]}
    out = fn(inp_missing)
    if out.get("stream") is not False:
        fail("stream should be false when flag absent")
        ok = False
    if ok:
        pass_("response mode always forces stream:false")




def test_anthropic_to_response_parallel_tool_use():
    """Parallel tool_use blocks become function_call items in original order."""
    print("\n--- Test: Anthropic To Response Parallel Tool Use ---")
    fn = _require_server_func("_anthropic_to_response")
    if fn is None:
        return
    inp = {"model": "sonnet",
           "messages": [
               {"role": "user", "content": "run both"},
               {"role": "assistant", "content": [
                   {"type": "tool_use", "id": "t1", "name": "get_weather",
                    "input": {"city": "SF"}},
                   {"type": "tool_use", "id": "t2", "name": "get_time",
                    "input": {"tz": "PT"}},
               ]},
           ]}
    out = fn(inp)
    items = out.get("input")
    if not isinstance(items, list) or len(items) != 3:
        fail("expected 3 input items, got {!r}".format(items))
        return
    ok1 = items[0] == {"type": "message", "role": "user",
                       "content": [{"type": "input_text", "text": "run both"}]}
    ok2 = (items[1].get("type") == "function_call"
           and items[1].get("call_id") == "t1"
           and items[1].get("name") == "get_weather"
           and json.loads(items[1].get("arguments", "null")) == {"city": "SF"})
    ok3 = (items[2].get("type") == "function_call"
           and items[2].get("call_id") == "t2"
           and items[2].get("name") == "get_time"
           and json.loads(items[2].get("arguments", "null")) == {"tz": "PT"})
    if ok1 and ok2 and ok3:
        pass_("parallel tool_use -> ordered function_call items")
    else:
        fail("parallel tool_use mapping wrong: {!r}".format(items))




def test_anthropic_to_response_tool_result_matching():
    """A tool_result for a known call id becomes function_call_output; list content joined."""
    print("\n--- Test: Anthropic To Response Tool Result Matching ---")
    fn = _require_server_func("_anthropic_to_response")
    if fn is None:
        return
    inp = {"model": "sonnet",
           "messages": [
               {"role": "user", "content": "weather?"},
               {"role": "assistant", "content": [
                   {"type": "tool_use", "id": "t1", "name": "get_weather",
                    "input": {"city": "SF"}}]},
               {"role": "user", "content": [
                   {"type": "tool_result", "tool_use_id": "t1",
                    "content": [{"type": "text", "text": "line1"},
                                {"type": "text", "text": "line2"}]}]},
           ]}
    out = fn(inp)
    items = out.get("input")
    if not isinstance(items, list) or len(items) != 3:
        fail("expected 3 input items, got {!r}".format(items))
        return
    out_item = items[2]
    if (out_item.get("type") == "function_call_output"
            and out_item.get("call_id") == "t1"
            and out_item.get("output") == "line1\nline2"):
        pass_("tool_result -> function_call_output with list content joined")
    else:
        fail("tool_result mapping wrong: {!r}".format(out_item))




def test_anthropic_to_response_tool_result_orphan_duplicate():
    """Orphan and duplicate tool_results are dropped; first valid result kept."""
    print("\n--- Test: Anthropic To Response Tool Result Orphan Duplicate ---")
    fn = _require_server_func("_anthropic_to_response")
    if fn is None:
        return
    inp = {"model": "sonnet",
           "messages": [
               {"role": "assistant", "content": [
                   {"type": "tool_use", "id": "t1", "name": "f", "input": {}}]},
               {"role": "user", "content": [
                   {"type": "tool_result", "tool_use_id": "orphan", "content": "x"},
                   {"type": "tool_result", "tool_use_id": "t1", "content": "first"},
                   {"type": "tool_result", "tool_use_id": "t1", "content": "second"},
               ]},
           ]}
    out = fn(inp)
    items = out.get("input")
    outputs = [it for it in items
               if isinstance(it, dict) and it.get("type") == "function_call_output"]
    if len(outputs) != 1:
        fail("expected exactly 1 function_call_output, got {!r}".format(outputs))
        return
    if outputs[0].get("call_id") != "t1" or outputs[0].get("output") != "first":
        fail("wrong function_call_output kept: {!r}".format(outputs[0]))
    else:
        pass_("orphan and duplicate tool_results dropped; first result kept")




def test_anthropic_to_response_invalid_tool_use_degrade():
    """Non-dict/NaN tool_use.input degrades to placeholder text; results dropped."""
    print("\n--- Test: Anthropic To Response Invalid Tool Use Degrade ---")
    fn = _require_server_func("_anthropic_to_response")
    if fn is None:
        return
    inp = {"model": "sonnet",
           "messages": [
               {"role": "assistant", "content": [
                   {"type": "tool_use", "id": "t1", "name": "f", "input": "oops"},
                   {"type": "tool_use", "id": "t2", "name": "f",
                    "input": {"x": float("nan")}},
               ]},
               {"role": "user", "content": [
                   {"type": "tool_result", "tool_use_id": "t1", "content": "r1"},
                   {"type": "tool_result", "tool_use_id": "t2", "content": "r2"},
               ]},
           ]}
    out = fn(inp)
    items = out.get("input")
    calls = [it for it in items
             if isinstance(it, dict) and it.get("type") == "function_call"]
    outs = [it for it in items
            if isinstance(it, dict) and it.get("type") == "function_call_output"]
    if calls:
        fail("no function_call items expected for invalid inputs, got {!r}".format(calls))
        return
    if outs:
        fail("results for omitted calls must be dropped, got {!r}".format(outs))
        return
    texts = []
    for it in items:
        if isinstance(it, dict) and it.get("type") == "message":
            for c in it.get("content", []):
                if isinstance(c, dict) and c.get("type") in ("input_text", "output_text"):
                    texts.append(c.get("text"))
    joined = "\n".join(t for t in texts if isinstance(t, str))
    ph1 = "[Tool call failed: arguments for 'f' (call t1) could not be serialized as JSON]"
    ph2 = "[Tool call failed: arguments for 'f' (call t2) could not be serialized as JSON]"
    if joined.count(ph1) != 1 or joined.count(ph2) != 1:
        fail("expected user-visible placeholders for both invalid calls, got {!r}".format(texts))
    else:
        pass_("invalid tool_use inputs degrade to placeholders; results dropped")




def test_anthropic_to_response_empty_dict_arguments():
    """A zero-argument tool_use (input {}) serializes to valid JSON object args."""
    print("\n--- Test: Anthropic To Response Empty Dict Arguments ---")
    fn = _require_server_func("_anthropic_to_response")
    if fn is None:
        return
    inp = {"model": "sonnet",
           "messages": [
               {"role": "assistant", "content": [
                   {"type": "tool_use", "id": "t1", "name": "ping", "input": {}}]},
           ]}
    out = fn(inp)
    items = out.get("input")
    if not isinstance(items, list) or len(items) != 1 \
            or items[0].get("type") != "function_call":
        fail("expected a single function_call item, got {!r}".format(items))
        return
    if items[0].get("arguments") != "{}":
        fail("expected arguments '{{}}', got {!r}".format(items[0].get("arguments")))
    else:
        pass_("empty dict input is a valid zero-argument call")




def test_anthropic_to_response_mixed_text_and_tool_use():
    """Mixed text/tool content keeps both kinds and original relative order."""
    print("\n--- Test: Anthropic To Response Mixed Text And Tool Use ---")
    fn = _require_server_func("_anthropic_to_response")
    if fn is None:
        return
    inp = {"model": "sonnet",
           "messages": [
               {"role": "assistant", "content": [
                   {"type": "text", "text": "Let me check"},
                   {"type": "tool_use", "id": "t1", "name": "f", "input": {"a": 1}}]},
               {"role": "user", "content": [
                   {"type": "tool_result", "tool_use_id": "t1", "content": "42"},
                   {"type": "text", "text": "thanks"}]},
           ]}
    out = fn(inp)
    items = out.get("input")
    expected_kinds = ["message", "function_call", "message", "function_call_output"]
    kinds = [it.get("type") for it in items if isinstance(it, dict)]
    if kinds != expected_kinds:
        fail("expected item kinds {!r}, got {!r}".format(expected_kinds, kinds))
        return
    if items[0]["content"][0]["text"] != "Let me check":
        fail("assistant text lost: {!r}".format(items[0]))
        return
    if items[2]["content"][0]["text"] != "thanks":
        fail("user text lost: {!r}".format(items[2]))
        return
    if items[3].get("call_id") != "t1" or items[3].get("output") != "42":
        fail("function_call_output mismatch: {!r}".format(items[3]))
        return
    pass_("mixed text/tool items preserve order and pairing")




def test_anthropic_to_response_role_coalescing():
    """Adjacent same-role message items coalesce; unsupported-only turns vanish."""
    print("\n--- Test: Anthropic To Response Role Coalescing ---")
    fn = _require_server_func("_anthropic_to_response")
    if fn is None:
        return
    inp = {"model": "sonnet",
           "messages": [
               {"role": "user", "content": "a"},
               {"role": "assistant", "content": [
                   {"type": "thinking", "thinking": "hmm", "signature": "s"}]},
               {"role": "user", "content": "b"},
           ]}
    out = fn(inp)
    expected = [{"type": "message", "role": "user",
                 "content": [{"type": "input_text", "text": "a\nb"}]}]
    if out.get("input") != expected:
        fail("expected coalesced single user message, got {!r}".format(out.get("input")))
    else:
        pass_("thinking-only turn dropped; adjacent user messages coalesced")




def test_anthropic_to_response_assistant_output_text():
    """Assistant text block becomes output_text in the Responses input."""
    print("\n--- Test: Anthropic To Response Assistant Output Text ---")
    fn = _require_server_func("_anthropic_to_response")
    if fn is None:
        return
    inp = {"model": "sonnet",
           "messages": [{"role": "assistant",
                         "content": [{"type": "text", "text": "hello"}]}]}
    out = fn(inp)
    expected = [{"type": "message", "role": "assistant",
                 "content": [{"type": "output_text", "text": "hello"}]}]
    if out.get("input") != expected:
        fail("expected assistant output_text item, got {!r}".format(out.get("input")))
    else:
        pass_("assistant text block -> output_text")




def test_anthropic_to_response_assistant_string_output_text():
    """Assistant string content becomes output_text."""
    print("\n--- Test: Anthropic To Response Assistant String Output Text ---")
    fn = _require_server_func("_anthropic_to_response")
    if fn is None:
        return
    out = fn({"model": "sonnet",
              "messages": [{"role": "assistant", "content": "hello"}]})
    items = out.get("input")
    if not isinstance(items, list) or len(items) != 1:
        fail("expected 1 input item, got {!r}".format(items))
        return
    content = items[0].get("content", [])
    if (items[0].get("role") == "assistant" and len(content) == 1
            and content[0].get("type") == "output_text"
            and content[0].get("text") == "hello"):
        pass_("assistant string content -> output_text")
    else:
        fail("expected assistant string content as output_text, got {!r}".format(items[0]))




def test_anthropic_to_response_user_input_text_unchanged():
    """User text stays input_text."""
    print("\n--- Test: Anthropic To Response User Input Text Unchanged ---")
    fn = _require_server_func("_anthropic_to_response")
    if fn is None:
        return
    out = fn({"model": "sonnet",
              "messages": [{"role": "user", "content": "hi"}]})
    items = out.get("input")
    if not isinstance(items, list) or len(items) != 1:
        fail("expected 1 input item, got {!r}".format(items))
        return
    content = items[0].get("content", [])
    if (items[0].get("role") == "user" and len(content) == 1
            and content[0].get("type") == "input_text"
            and content[0].get("text") == "hi"):
        pass_("user text stays input_text")
    else:
        fail("expected user text as input_text, got {!r}".format(items[0]))




def test_anthropic_to_response_assistant_coalescing():
    """Adjacent assistant messages coalesce into a single output_text item."""
    print("\n--- Test: Anthropic To Response Assistant Coalescing ---")
    fn = _require_server_func("_anthropic_to_response")
    if fn is None:
        return
    inp = {"model": "sonnet",
           "messages": [
               {"role": "assistant", "content": "part one"},
               {"role": "assistant", "content": [
                   {"type": "thinking", "thinking": "hmm", "signature": "s"}]},
               {"role": "assistant", "content": "part two"},
           ]}
    out = fn(inp)
    items = out.get("input")
    if not isinstance(items, list) or len(items) != 1:
        fail("expected 1 coalesced assistant item, got {!r}".format(items))
        return
    content = items[0].get("content", [])
    if (items[0].get("role") == "assistant" and len(content) == 1
            and content[0].get("type") == "output_text"
            and content[0].get("text") == "part one\npart two"):
        pass_("adjacent assistant messages coalesced with output_text")
    else:
        fail("expected coalesced assistant item with output_text, got {!r}".format(items[0]))




def test_anthropic_to_response_assistant_coalescing_mid_history():
    """Coalesced assistant item keeps output_text even with a trailing user message.

    Discriminating case for the stale-role trap: the outer messages loop leaves
    `role` bound to the last message ("user"), so a buggy implementation reading
    the bare `role` variable would emit input_text here.
    """
    print("\n--- Test: Anthropic To Response Assistant Coalescing Mid History ---")
    fn = _require_server_func("_anthropic_to_response")
    if fn is None:
        return
    # Assistant pair mid-history, followed by a trailing user message.
    inp = {"model": "sonnet",
           "messages": [
               {"role": "assistant", "content": "part one"},
               {"role": "assistant", "content": [
                   {"type": "thinking", "thinking": "hmm", "signature": "s"}]},
               {"role": "assistant", "content": "part two"},
               {"role": "user", "content": "trailing"},
           ]}
    out = fn(inp)
    items = out.get("input")
    if not isinstance(items, list) or len(items) != 2:
        fail("expected 2 items (coalesced assistant + trailing user), got {!r}".format(items))
        return
    first = items[0]
    first_content = first.get("content", [])
    if (first.get("role") == "assistant" and len(first_content) == 1
            and first_content[0].get("type") == "output_text"
            and first_content[0].get("text") == "part one\npart two"):
        pass_("mid-history assistant pair coalesced with output_text")
    else:
        fail("expected mid-history assistant coalescing with output_text, got {!r}".format(first))
        return
    # Symmetric: user pair mid-history, followed by a trailing assistant message.
    inp2 = {"model": "sonnet",
            "messages": [
                {"role": "user", "content": "a"},
                {"role": "assistant", "content": [
                    {"type": "thinking", "thinking": "hmm", "signature": "s"}]},
                {"role": "user", "content": "b"},
                {"role": "assistant", "content": "trailing"},
            ]}
    out2 = fn(inp2)
    items2 = out2.get("input")
    if not isinstance(items2, list) or len(items2) != 2:
        fail("expected 2 items (coalesced user + trailing assistant), got {!r}".format(items2))
        return
    first2 = items2[0]
    first2_content = first2.get("content", [])
    if (first2.get("role") == "user" and len(first2_content) == 1
            and first2_content[0].get("type") == "input_text"
            and first2_content[0].get("text") == "a\nb"):
        pass_("mid-history user pair coalesced with input_text")
    else:
        fail("expected mid-history user coalescing with input_text, got {!r}".format(first2))




def test_anthropic_to_response_user_coalescing_unchanged():
    """Adjacent user messages still coalesce with input_text."""
    print("\n--- Test: Anthropic To Response User Coalescing Unchanged ---")
    fn = _require_server_func("_anthropic_to_response")
    if fn is None:
        return
    inp = {"model": "sonnet",
           "messages": [
               {"role": "user", "content": "a"},
               {"role": "assistant", "content": [
                   {"type": "thinking", "thinking": "hmm", "signature": "s"}]},
               {"role": "user", "content": "b"},
           ]}
    out = fn(inp)
    items = out.get("input")
    if not isinstance(items, list) or len(items) != 1:
        fail("expected 1 coalesced user item, got {!r}".format(items))
        return
    content = items[0].get("content", [])
    if (items[0].get("role") == "user" and len(content) == 1
            and content[0].get("type") == "input_text"
            and content[0].get("text") == "a\nb"):
        pass_("adjacent user messages coalesced with input_text")
    else:
        fail("expected coalesced user item with input_text, got {!r}".format(items[0]))




def test_anthropic_to_response_mixed_roles_no_coalescing():
    """Adjacent user and assistant messages do not coalesce."""
    print("\n--- Test: Anthropic To Response Mixed Roles No Coalescing ---")
    fn = _require_server_func("_anthropic_to_response")
    if fn is None:
        return
    inp = {"model": "sonnet",
           "messages": [
               {"role": "user", "content": "q"},
               {"role": "assistant", "content": "a"},
           ]}
    out = fn(inp)
    items = out.get("input")
    if not isinstance(items, list) or len(items) != 2:
        fail("expected 2 items (no cross-role coalescing), got {!r}".format(items))
        return
    user_item, asst_item = items[0], items[1]
    ok = (user_item.get("role") == "user"
          and user_item.get("content", [{}])[0].get("type") == "input_text"
          and asst_item.get("role") == "assistant"
          and asst_item.get("content", [{}])[0].get("type") == "output_text")
    if ok:
        pass_("adjacent user+assistant items kept separate with correct types")
    else:
        fail("unexpected items, got {!r}".format(items))




def test_anthropic_to_response_system_role_input_text():
    """System role (non-user, non-assistant) stays input_text."""
    print("\n--- Test: Anthropic To Response System Role Input Text ---")
    fn = _require_server_func("_anthropic_to_response")
    if fn is None:
        return
    out = fn({"model": "sonnet",
              "messages": [{"role": "system", "content": "ctx"}]})
    items = out.get("input")
    if not isinstance(items, list) or len(items) != 1:
        fail("expected 1 input item, got {!r}".format(items))
        return
    content = items[0].get("content", [])
    if (items[0].get("role") == "system" and len(content) == 1
            and content[0].get("type") == "input_text"
            and content[0].get("text") == "ctx"):
        pass_("system role stays input_text")
    else:
        fail("expected system role as input_text, got {!r}".format(items[0]))




def test_anthropic_to_response_mixed_history_content_types():
    """Mixed history preserves order with role-appropriate content types."""
    print("\n--- Test: Anthropic To Response Mixed History Content Types ---")
    fn = _require_server_func("_anthropic_to_response")
    if fn is None:
        return
    inp = {"model": "sonnet",
           "messages": [
               {"role": "user", "content": "run it"},
               {"role": "assistant", "content": [
                   {"type": "text", "text": "Let me check"},
                   {"type": "tool_use", "id": "t1", "name": "f", "input": {"a": 1}},
               ]},
               {"role": "user", "content": [
                   {"type": "tool_result", "tool_use_id": "t1", "content": "42"},
                   {"type": "text", "text": "thanks"},
               ]},
           ]}
    out = fn(inp)
    items = out.get("input")
    if not isinstance(items, list) or len(items) != 5:
        fail("expected 5 items, got {!r}".format(items))
        return
    expected_kinds = ["message", "message", "function_call", "message",
                      "function_call_output"]
    kinds = [it.get("type") for it in items if isinstance(it, dict)]
    if kinds != expected_kinds:
        fail("expected item kinds {!r}, got {!r}".format(expected_kinds, kinds))
        return
    checks = [
        (items[0], "user", "input_text", "run it"),
        (items[1], "assistant", "output_text", "Let me check"),
        (items[3], "user", "input_text", "thanks"),
    ]
    ok = True
    for item, role, ct, text in checks:
        content = item.get("content", [])
        if not (item.get("role") == role and len(content) == 1
                and content[0].get("type") == ct
                and content[0].get("text") == text):
            fail("expected {} item with {} {!r}, got {!r}".format(role, ct, text, item))
            ok = False
    if items[2].get("call_id") != "t1":
        fail("expected function_call for t1, got {!r}".format(items[2]))
        ok = False
    if items[4].get("call_id") != "t1" or items[4].get("output") != "42":
        fail("expected function_call_output for t1, got {!r}".format(items[4]))
        ok = False
    if ok:
        pass_("mixed history preserves order with role-appropriate content types")




def test_anthropic_to_response_assistant_empty_string_content():
    """Empty-string assistant content is emitted as an output_text item."""
    print("\n--- Test: Anthropic To Response Assistant Empty String Content ---")
    fn = _require_server_func("_anthropic_to_response")
    if fn is None:
        return
    out = fn({"model": "sonnet",
              "messages": [{"role": "assistant", "content": ""}]})
    items = out.get("input")
    if not isinstance(items, list) or len(items) != 1:
        fail("expected 1 input item, got {!r}".format(items))
        return
    content = items[0].get("content", [])
    if (items[0].get("role") == "assistant" and len(content) == 1
            and content[0].get("type") == "output_text"
            and content[0].get("text") == ""):
        pass_("empty-string assistant content -> output_text with empty text")
    else:
        fail("expected empty assistant string as output_text, got {!r}".format(items[0]))




def test_anthropic_to_response_flat_tools():
    """Anthropic tools become flat Responses function tools (no nested function)."""
    print("\n--- Test: Anthropic To Response Flat Tools ---")
    fn = _require_server_func("_anthropic_to_response")
    if fn is None:
        return
    schema = {"type": "object", "properties": {}}
    inp = {"model": "sonnet",
           "messages": [{"role": "user", "content": "hi"}],
           "tools": [{"name": "get_weather", "description": "d",
                      "input_schema": schema}],
           "tool_choice": {"type": "auto"}}
    out = fn(inp)
    tools = out.get("tools")
    expected = [{"type": "function", "name": "get_weather", "description": "d",
                 "parameters": schema}]
    if tools != expected:
        fail("expected flat function tools, got {!r}".format(tools))
        return
    if any(isinstance(t, dict) and "function" in t for t in tools):
        fail("tools must not use chat's nested function shape: {!r}".format(tools))
    else:
        pass_("flat Responses function tool shape emitted")




def test_anthropic_to_response_tool_choice_mapping():
    """tool_choice maps auto/any/none/tool; named unknown tool omitted."""
    print("\n--- Test: Anthropic To Response Tool Choice Mapping ---")
    fn = _require_server_func("_anthropic_to_response")
    if fn is None:
        return
    base_msgs = [{"role": "user", "content": "hi"}]
    tools = [{"name": "f", "input_schema": {"type": "object", "properties": {}}}]
    cases = [
        ({"type": "auto"}, "auto"),
        ({"type": "any"}, "required"),
        ({"type": "none"}, "none"),
        ({"type": "tool", "name": "f"}, {"type": "function", "name": "f"}),
    ]
    ok = True
    for tc, expected in cases:
        inp = {"model": "sonnet", "messages": base_msgs,
               "tools": tools, "tool_choice": tc}
        out = fn(inp)
        if out.get("tool_choice") != expected:
            fail("tool_choice {!r} -> {!r}, expected {!r}".format(
                tc, out.get("tool_choice"), expected))
            ok = False
    inp = {"model": "sonnet", "messages": base_msgs, "tools": tools,
           "tool_choice": {"type": "tool", "name": "unknown_tool"}}
    out = fn(inp)
    if "tool_choice" in out:
        fail("named choice for unknown tool must be omitted, got {!r}".format(
            out.get("tool_choice")))
        ok = False
    if ok:
        pass_("tool_choice mapping correct incl. dropped-tool omission")




def test_anthropic_to_response_no_input_mutation():
    """The input body_json object is not mutated."""
    print("\n--- Test: Anthropic To Response No Input Mutation ---")
    import copy
    fn = _require_server_func("_anthropic_to_response")
    if fn is None:
        return
    inp = {"model": "sonnet",
           "system": [{"type": "text", "text": "S"}],
           "messages": [
               {"role": "user", "content": [{"type": "text", "text": "hi"}]},
               {"role": "assistant", "content": [
                   {"type": "tool_use", "id": "t1", "name": "f", "input": {"a": 1}},
                   {"type": "text", "text": "x"}]},
               {"role": "user", "content": [
                   {"type": "tool_result", "tool_use_id": "t1", "content": "r",
                    "cache_control": {"type": "ephemeral"}}]},
           ],
           "tools": [{"name": "f", "input_schema": {"type": "object"},
                      "cache_control": {"type": "ephemeral"}}],
           "tool_choice": {"type": "tool", "name": "f"}}
    snapshot = copy.deepcopy(inp)
    fn(inp)
    if inp != snapshot:
        fail("input object was mutated")
    else:
        pass_("input object not mutated")




def test_anthropic_to_response_error_result():
    """An error tool_result's text is preserved as the output string."""
    print("\n--- Test: Anthropic To Response Error Result ---")
    fn = _require_server_func("_anthropic_to_response")
    if fn is None:
        return
    inp = {"model": "sonnet",
           "messages": [
               {"role": "assistant", "content": [
                   {"type": "tool_use", "id": "t1", "name": "f", "input": {}}]},
               {"role": "user", "content": [
                   {"type": "tool_result", "tool_use_id": "t1",
                    "content": "boom", "is_error": True}]},
           ]}
    out = fn(inp)
    items = out.get("input")
    outs = [it for it in items
            if isinstance(it, dict) and it.get("type") == "function_call_output"]
    if len(outs) != 1 or outs[0].get("output") != "boom":
        fail("expected error result text preserved as output, got {!r}".format(outs))
    else:
        pass_("error tool_result text preserved (Responses has no is_error)")




# --- Step 7: _response_to_anthropic ---

def test_response_to_anthropic_basic():
    """content, model, id, usage mapped correctly."""
    print("\n--- Test: Response To Anthropic Basic ---")
    fn = _require_server_func("_response_to_anthropic")
    if fn is None:
        return
    resp = {"id": "resp_123", "object": "response", "created_at": 1, "model": "gpt-4o",
            "status": "completed",
            "output": [{"type": "message", "role": "assistant",
                        "content": [{"type": "output_text", "text": "Hello", "annotations": []}]}],
            "usage": {"input_tokens": 4, "output_tokens": 2, "total_tokens": 6}}
    out = fn(resp, "sonnet")
    if not isinstance(out, dict):
        fail("_response_to_anthropic must return a dict")
        return
    checks = [
        (out.get("id") == "resp_123", "id passed through"),
        (out.get("model") == "sonnet", "model rewritten to tier"),
        (out.get("type") == "message", "type hardcoded"),
        (out.get("role") == "assistant", "role hardcoded"),
        (out.get("content") == [{"type": "text", "text": "Hello"}], "output_text -> text block"),
        (out.get("stop_reason") == "end_turn", "status completed -> end_turn"),
        (out.get("usage") == {"input_tokens": 4, "output_tokens": 2}, "usage mapped"),
    ]
    for ok, label in checks:
        if not ok:
            fail("basic response->anthropic mapping failed: {}".format(label))
    if all(ok for ok, _ in checks):
        pass_("response->anthropic basic mapping correct")




def test_response_to_anthropic_empty_output():
    """Empty output returns a minimal valid Anthropic message."""
    print("\n--- Test: Response To Anthropic Empty Output ---")
    fn = _require_server_func("_response_to_anthropic")
    if fn is None:
        return
    resp = {"id": "resp_1", "output": [], "status": "completed", "model": "gpt-4o"}
    out = fn(resp, "sonnet")
    if not isinstance(out, dict):
        fail("empty output must still return a dict")
        return
    if out.get("type") != "message" or out.get("role") != "assistant" or out.get("model") != "sonnet":
        fail("minimal response missing core fields: {!r}".format(out))
    if out.get("content") != []:
        fail("minimal response expected content=[], got {!r}".format(out.get("content")))
    if out.get("type") == "message" and out.get("role") == "assistant" and out.get("content") == []:
        pass_("empty output returns minimal valid message")




def test_response_to_anthropic_multiple_output():
    """All output items processed in order (texts + function_call)."""
    print("\n--- Test: Response To Anthropic Multiple Output ---")
    fn = _require_server_func("_response_to_anthropic")
    if fn is None:
        return
    resp = {"id": "resp_1", "status": "completed", "model": "gpt-4o",
            "output": [
                {"type": "message", "role": "assistant",
                 "content": [{"type": "output_text", "text": "First", "annotations": []}]},
                {"type": "message", "role": "assistant",
                 "content": [{"type": "output_text", "text": "Second", "annotations": []}]},
                {"type": "function_call", "call_id": "c1", "name": "f", "arguments": "{}"},
            ]}
    out = fn(resp, "sonnet")
    expected = [
        {"type": "text", "text": "First"},
        {"type": "text", "text": "Second"},
        {"type": "tool_use", "id": "c1", "name": "f", "input": {}},
    ]
    if out.get("content") != expected:
        fail("expected ordered mixed content, got {!r}".format(out.get("content")))
    elif out.get("stop_reason") != "tool_use":
        fail("expected stop_reason 'tool_use', got {!r}".format(out.get("stop_reason")))
    else:
        pass_("all output items processed in order; stop_reason tool_use")




def test_response_to_anthropic_status_completed():
    """stop_reason derived from the status field."""
    print("\n--- Test: Response To Anthropic Status Completed ---")
    fn = _require_server_func("_response_to_anthropic")
    if fn is None:
        return
    cases = [("completed", "end_turn"), ("incomplete", None), ("failed", None), (None, None)]
    ok = True
    for status, expected in cases:
        resp = {"id": "r", "status": status,
                "output": [{"type": "message", "role": "assistant",
                            "content": [{"type": "output_text", "text": "hi"}]}]}
        out = fn(resp, "sonnet")
        if out.get("stop_reason") != expected:
            fail("status {!r} -> stop_reason {!r}, expected {!r}".format(status, out.get("stop_reason"), expected))
            ok = False
    if ok:
        pass_("status->stop_reason mapping correct")




def test_response_to_anthropic_usage_absent():
    """Missing usage maps to zero input/output tokens."""
    print("\n--- Test: Response To Anthropic Usage Absent ---")
    fn = _require_server_func("_response_to_anthropic")
    if fn is None:
        return
    resp = {"id": "r", "status": "completed",
            "output": [{"type": "message", "role": "assistant",
                        "content": [{"type": "output_text", "text": "hi"}]}]}
    out = fn(resp, "sonnet")
    if out.get("usage") != {"input_tokens": 0, "output_tokens": 0}:
        fail("expected usage {input_tokens:0, output_tokens:0}, got {!r}".format(out.get("usage")))
    else:
        pass_("missing usage handled with zero defaults")




def test_response_to_anthropic_parallel_calls():
    """Parallel function_call items become tool_use blocks in order."""
    print("\n--- Test: Response To Anthropic Parallel Calls ---")
    fn = _require_server_func("_response_to_anthropic")
    if fn is None:
        return
    resp = {"id": "r", "status": "completed",
            "output": [
                {"type": "function_call", "call_id": "c1", "name": "f1",
                 "arguments": "{}"},
                {"type": "function_call", "call_id": "c2", "name": "f2",
                 "arguments": '{"x": 1}'},
            ],
            "usage": {"input_tokens": 1, "output_tokens": 1}}
    out = fn(resp, "sonnet")
    expected = [
        {"type": "tool_use", "id": "c1", "name": "f1", "input": {}},
        {"type": "tool_use", "id": "c2", "name": "f2", "input": {"x": 1}},
    ]
    if out.get("content") != expected:
        fail("expected parallel tool_use blocks in order, got {!r}".format(out.get("content")))
    elif out.get("stop_reason") != "tool_use":
        fail("expected stop_reason 'tool_use', got {!r}".format(out.get("stop_reason")))
    else:
        pass_("parallel function_calls -> ordered tool_use blocks")




def test_response_to_anthropic_mixed_text_calls():
    """Mixed message/function_call output items all processed in order."""
    print("\n--- Test: Response To Anthropic Mixed Text Calls ---")
    fn = _require_server_func("_response_to_anthropic")
    if fn is None:
        return
    resp = {"id": "r", "status": "completed",
            "output": [
                {"type": "message", "role": "assistant",
                 "content": [{"type": "output_text", "text": "Hello"}]},
                {"type": "function_call", "call_id": "c1", "name": "f",
                 "arguments": "{}"},
                {"type": "message", "role": "assistant",
                 "content": [{"type": "output_text", "text": "Done"}]},
            ]}
    out = fn(resp, "sonnet")
    expected = [
        {"type": "text", "text": "Hello"},
        {"type": "tool_use", "id": "c1", "name": "f", "input": {}},
        {"type": "text", "text": "Done"},
    ]
    if out.get("content") != expected:
        fail("expected ordered mixed content, got {!r}".format(out.get("content")))
    elif out.get("stop_reason") != "tool_use":
        fail("expected stop_reason 'tool_use', got {!r}".format(out.get("stop_reason")))
    else:
        pass_("mixed text/call output processed in order without early break")




def test_response_to_anthropic_valid_args_dict_and_string():
    """Dict arguments accepted directly; string arguments parsed; {} valid."""
    print("\n--- Test: Response To Anthropic Valid Args Dict And String ---")
    fn = _require_server_func("_response_to_anthropic")
    if fn is None:
        return
    cases = [
        ({"a": 1}, {"a": 1}),
        ('{"b": 2}', {"b": 2}),
        ("{}", {}),
    ]
    ok = True
    for args, expected_input in cases:
        resp = {"id": "r", "status": "completed",
                "output": [{"type": "function_call", "call_id": "c1",
                            "name": "f", "arguments": args}]}
        out = fn(resp, "sonnet")
        content = out.get("content") if isinstance(out.get("content"), list) else []
        blocks = [b for b in content
                  if isinstance(b, dict) and b.get("type") == "tool_use"]
        if len(blocks) != 1 or blocks[0].get("input") != expected_input:
            fail("arguments {!r} -> input {!r}, expected {!r}".format(
                args, blocks[0].get("input") if blocks else None, expected_input))
            ok = False
    if ok:
        pass_("dict, string, and empty-dict arguments all map to tool_use input")




def test_response_to_anthropic_malformed_args_degrade():
    """Malformed/non-object arguments degrade; all-malformed completed -> null stop."""
    print("\n--- Test: Response To Anthropic Malformed Args Degrade ---")
    fn = _require_server_func("_response_to_anthropic")
    if fn is None:
        return
    resp = {"id": "r", "status": "completed",
            "output": [
                {"type": "function_call", "call_id": "c1", "name": "f",
                 "arguments": "not json"},
                {"type": "function_call", "call_id": "c2", "name": "g",
                 "arguments": "[1, 2]"},
            ]}
    out = fn(resp, "sonnet")
    content = out.get("content") if isinstance(out.get("content"), list) else []
    tool_blocks = [b for b in content if isinstance(b, dict) and b.get("type") == "tool_use"]
    ph1 = "[Tool call failed: arguments for 'f' (call c1) could not be parsed as JSON]"
    ph2 = "[Tool call failed: arguments for 'g' (call c2) could not be parsed as JSON]"
    texts = [b.get("text") for b in content
             if isinstance(b, dict) and b.get("type") == "text"]
    if tool_blocks:
        fail("malformed arguments must not produce tool_use blocks, got {!r}".format(tool_blocks))
    elif ph1 not in texts or ph2 not in texts:
        fail("expected user-visible placeholders, got {!r}".format(texts))
    elif out.get("stop_reason") is not None:
        fail("all-malformed completed response must force stop_reason null, got {!r}".format(
            out.get("stop_reason")))
    else:
        pass_("malformed args degrade to placeholders; completed all-malformed -> null stop")




def test_response_to_anthropic_missing_id_name():
    """Missing call_id or name degrades to a placeholder, not a fake empty tool."""
    print("\n--- Test: Response To Anthropic Missing Id Name ---")
    fn = _require_server_func("_response_to_anthropic")
    if fn is None:
        return
    resp = {"id": "r", "status": "completed",
            "output": [
                {"type": "function_call", "name": "f", "arguments": "{}"},
                {"type": "function_call", "call_id": "c2", "arguments": "{}"},
            ]}
    out = fn(resp, "sonnet")
    content = out.get("content") if isinstance(out.get("content"), list) else []
    tool_blocks = [b for b in content if isinstance(b, dict) and b.get("type") == "tool_use"]
    texts = [b.get("text") for b in content
             if isinstance(b, dict) and b.get("type") == "text"]
    placeholders = [t for t in texts
                    if isinstance(t, str) and t.startswith("[Tool call failed:")]
    if tool_blocks:
        fail("missing id/name must not produce tool_use blocks, got {!r}".format(tool_blocks))
    elif len(placeholders) != 2:
        fail("expected 2 placeholder blocks for missing id/name, got {!r}".format(texts))
    elif out.get("stop_reason") is not None:
        fail("degraded calls must not claim tool_use stop_reason, got {!r}".format(
            out.get("stop_reason")))
    else:
        pass_("missing id/name degrade to placeholders with null stop_reason")




def test_response_to_anthropic_unsupported_items_ignored():
    """Unsupported output item types are ignored without crashing."""
    print("\n--- Test: Response To Anthropic Unsupported Items Ignored ---")
    fn = _require_server_func("_response_to_anthropic")
    if fn is None:
        return
    resp = {"id": "r", "status": "completed",
            "output": [
                "junk",
                {"type": "web_search_call", "id": "w1"},
                {"type": "function_call_output", "call_id": "c1", "output": "x"},
                {"type": "message", "role": "assistant",
                 "content": [{"type": "output_text", "text": "hi"}]},
            ]}
    out = fn(resp, "sonnet")
    if out.get("content") != [{"type": "text", "text": "hi"}]:
        fail("expected only the message item's text, got {!r}".format(out.get("content")))
    elif out.get("stop_reason") != "end_turn":
        fail("expected stop_reason 'end_turn' for completed text-only, got {!r}".format(
            out.get("stop_reason")))
    else:
        pass_("unsupported output items ignored; text mapping intact")


ALL_TESTS = [
    ("anthropic-to-response-basic", test_anthropic_to_response_basic),
    ("anthropic-to-response-system-list", test_anthropic_to_response_system_list),
    ("anthropic-to-response-multiple-user-messages", test_anthropic_to_response_multiple_user_messages),
    ("anthropic-to-response-no-user-message", test_anthropic_to_response_no_user_message),
    ("anthropic-to-response-stream-forced-false", test_anthropic_to_response_stream_forced_false),
    ("response-to-anthropic-basic", test_response_to_anthropic_basic),
    ("response-to-anthropic-empty-output", test_response_to_anthropic_empty_output),
    ("response-to-anthropic-multiple-output", test_response_to_anthropic_multiple_output),
    ("response-to-anthropic-status-completed", test_response_to_anthropic_status_completed),
    ("response-to-anthropic-usage-absent", test_response_to_anthropic_usage_absent),
    ("anthropic-to-response-parallel-tool-use", test_anthropic_to_response_parallel_tool_use),
    ("anthropic-to-response-tool-result-matching", test_anthropic_to_response_tool_result_matching),
    ("anthropic-to-response-tool-result-orphan-duplicate", test_anthropic_to_response_tool_result_orphan_duplicate),
    ("anthropic-to-response-invalid-tool-use-degrade", test_anthropic_to_response_invalid_tool_use_degrade),
    ("anthropic-to-response-empty-dict-arguments", test_anthropic_to_response_empty_dict_arguments),
    ("anthropic-to-response-mixed-text-and-tool-use", test_anthropic_to_response_mixed_text_and_tool_use),
    ("anthropic-to-response-role-coalescing", test_anthropic_to_response_role_coalescing),
    ("anthropic-to-response-assistant-output-text", test_anthropic_to_response_assistant_output_text),
    ("anthropic-to-response-assistant-string-output-text", test_anthropic_to_response_assistant_string_output_text),
    ("anthropic-to-response-user-input-text-unchanged", test_anthropic_to_response_user_input_text_unchanged),
    ("anthropic-to-response-assistant-coalescing", test_anthropic_to_response_assistant_coalescing),
    ("anthropic-to-response-assistant-coalescing-mid-history", test_anthropic_to_response_assistant_coalescing_mid_history),
    ("anthropic-to-response-user-coalescing-unchanged", test_anthropic_to_response_user_coalescing_unchanged),
    ("anthropic-to-response-mixed-roles-no-coalescing", test_anthropic_to_response_mixed_roles_no_coalescing),
    ("anthropic-to-response-system-role-input-text", test_anthropic_to_response_system_role_input_text),
    ("anthropic-to-response-mixed-history-content-types", test_anthropic_to_response_mixed_history_content_types),
    ("anthropic-to-response-assistant-empty-string-content", test_anthropic_to_response_assistant_empty_string_content),
    ("anthropic-to-response-flat-tools", test_anthropic_to_response_flat_tools),
    ("anthropic-to-response-tool-choice-mapping", test_anthropic_to_response_tool_choice_mapping),
    ("anthropic-to-response-no-input-mutation", test_anthropic_to_response_no_input_mutation),
    ("anthropic-to-response-error-result", test_anthropic_to_response_error_result),
    ("response-to-anthropic-parallel-calls", test_response_to_anthropic_parallel_calls),
    ("response-to-anthropic-mixed-text-calls", test_response_to_anthropic_mixed_text_calls),
    ("response-to-anthropic-valid-args-dict-and-string", test_response_to_anthropic_valid_args_dict_and_string),
    ("response-to-anthropic-malformed-args-degrade", test_response_to_anthropic_malformed_args_degrade),
    ("response-to-anthropic-missing-id-name", test_response_to_anthropic_missing_id_name),
    ("response-to-anthropic-unsupported-items-ignored", test_response_to_anthropic_unsupported_items_ignored),
]


if __name__ == "__main__":
    run_cli(ALL_TESTS, "claude-retry-proxy tests: test_response_transform")
