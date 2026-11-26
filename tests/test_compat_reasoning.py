"""reasoning_field credit-learner live tests: walk candidates, complaint
counting and matcher shapes, the demanding-turn presence gate, the rescue
passes, and admin-swap parameter carry."""

import json
import os
import shutil

from _harness import (
    _admin_post,
    _mode_tiers,
    _trace_events_named,
    fail,
    find_free_port,
    pass_,
    run_cli,
)

from _compat_support import (
    REASONING_MESSAGE_400,
    REJECTED_BODY_CORPUS,
    _chat_ok_response,
    _chat_vendor,
    _compat_trace_events,
    _entries,
    _entry_values,
    _make_state_dir,
    _read_state_file,
    _reasoning_request,
    _rescue_trace_events,
    _send,
    _sent_reasoning_field,
    _start_compat_proxy,
)

from claude_retry_proxy.nesting import MAX_JSON_NESTING_DEPTH


def _forwarded_assistant_fields(info, field="reasoning_content"):
    """Every assistant message's value for `field` in the body the proxy sent.

    Returns (values, every_message_carries_it). Empty values + False when the
    body is unparseable or carries no assistant message.
    """
    try:
        body = json.loads(info["body"])
    except Exception:
        return [], False
    msgs = [m for m in body.get("messages", [])
            if isinstance(m, dict) and m.get("role") == "assistant"]
    values = [m.get(field) for m in msgs]
    return values, bool(msgs) and all(field in m for m in msgs)


def _reasoning_upstream(policy, log=None):
    """A chat-mode mock upstream that validates the echoed reasoning field.

    policy["accept"] is a tuple of accepted values: field names, plus the
    literal "none" for a request that carries no reasoning field at all. A
    request sending anything outside that tuple gets the message-form 400.
    policy["accept"] is read per request, so the test can change the upstream's
    convention mid-conversation. Every request is appended to `log` when given.
    """
    def responder(info):
        if log is not None:
            log.append(info)
        sent = _sent_reasoning_field(info) or "none"
        if sent in policy.get("accept", ()):
            return _chat_ok_response(info)
        return 400, "application/json", REASONING_MESSAGE_400
    return responder


def _reasoning_entry(state_path, model="claude-sonnet-5", provider="p"):
    """The persisted reasoning_field entry for a pair, or None."""
    state = _read_state_file(state_path)
    if not state:
        return None
    for entry in _entry_values(_entries(state)):
        if (isinstance(entry, dict)
                and entry.get("feature") == "reasoning_field"
                and entry.get("provider") == provider
                and entry.get("actual_model") == model):
            return entry
    return None


def _seed_reasoning_state(state_path, selection,
                          model="claude-sonnet-5", provider="p"):
    """Write a state file carrying one learned reasoning_field selection."""
    entry = {
        "schema_version": 1, "provider": provider, "mode": "chat",
        "actual_model": model, "feature": "reasoning_field",
        "selection": selection,
    }
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump({"schema_version": 1,
                   "entries": {"\x1f".join(
                       (provider, "chat", model, "reasoning_field")): entry}},
                  f)


def _start_reasoning_proxy(responders, state_path, reasoning_field_switch=None):
    """Start a chat-mode proxy backed by one mock upstream, with an isolated
    compatibility state file and an optional reasoning_field_switch policy in
    the fixture's models.json."""
    vendors = {"p": _chat_vendor(find_free_port())}
    return _start_compat_proxy(responders, state_path, vendors=vendors,
                               reasoning_field_switch=reasoning_field_switch)


def test_reasoning_walk_sends_advanced_candidate():
    """A walk step from a persisted `reasoning_content` selection sends exactly
    `reasoning`; from a persisted `reasoning` selection the first step wraps to
    "none", which has no field name to write — the pass sends the entry's
    current selection instead (the forced-repair fallback) and reports it as
    `effective_field`, then advances to `reasoning_content`.

    The wrap step is still the pin for the sentinel collision: the pass re-sends
    a field rather than re-resolving the request's selection from scratch (a
    resolver keyed on the parameter's value rather than on None would forget
    which selection this request started from).
    """
    print("\n--- Test: Reasoning Walk Sends Advanced Candidate ---")
    for seeded, accepted, expect_sent, expect_candidates, \
            expect_effective, label in (
            ("reasoning_content", "reasoning",
             ["reasoning_content", "reasoning"],
             ["reasoning"], ["reasoning"],
             "reasoning_content -> reasoning"),
            ("reasoning", "reasoning_content",
             ["reasoning", "reasoning", "reasoning_content"],
             ["none", "reasoning_content"], ["reasoning", "reasoning_content"],
             "reasoning -> none (entry selection sent) -> reasoning_content")):
        state_dir, state_path = _make_state_dir()
        _seed_reasoning_state(state_path, seeded)
        policy = {"accept": (accepted,)}
        log = []
        responders = {"p": _reasoning_upstream(policy, log=log)}
        temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
            _start_reasoning_proxy(responders, state_path)
        if proc is None:
            shutil.rmtree(state_dir, ignore_errors=True)
            fail("Failed to set up test (%s)" % label)
            return
        try:
            status, _ = _send(proxy_port, _reasoning_request(demanding=True))
            if status != 200:
                fail("%s: walk was not served (%s)" % (label, status))
                return
            sent = [_sent_reasoning_field(i) for i in log]
            if sent != expect_sent:
                fail("%s: expected %r, upstream saw %r — the wrap step "
                     "re-resolved instead of using the fallback field"
                     % (label, expect_sent, sent))
                return
            events = _rescue_trace_events(trace_file)
            pairs = [(e.get("candidate"), e.get("effective_field"))
                     for e in events]
            if pairs != list(zip(expect_candidates, expect_effective)):
                fail("%s: expected (candidate, effective_field) %r, got %r"
                     % (label, list(zip(expect_candidates, expect_effective)),
                        pairs))
                return
            pass_("walk advanced %s" % label)
        finally:
            cleanup()
            shutil.rmtree(state_dir, ignore_errors=True)


def test_reasoning_non_complaint_errors_are_not_counted():
    """A 401/403/500, an unparseable body, and an unrelated 400 naming no
    reasoning field never change the credit, advance the selection, or emit a
    learner event. A non-complaint result inside a rescue stops the rescue and
    returns the ORIGINAL top-level result to the client."""
    print("\n--- Test: Reasoning Non-Complaint Errors Are Not Counted ---")
    state_dir, state_path = _make_state_dir()
    runner = {"mode": "500", "n": 0}

    def upstream(info):
        runner["n"] += 1
        mode = runner["mode"]
        if mode == "complaint":
            if (_sent_reasoning_field(info) or "none") == "reasoning_content":
                return _chat_ok_response(info)
            return 400, "application/json", REASONING_MESSAGE_400
        if mode == "complaint_then_500":
            if runner["n"] == 1:
                return 400, "application/json", REASONING_MESSAGE_400
            return 500, "application/json", b'{"error":"boom"}'
        if mode == "500":
            return 500, "application/json", b'{"error":"boom"}'
        if mode == "401":
            return 401, "application/json", b'{"error":"unauthorized"}'
        if mode == "403":
            return 403, "application/json", b'{"error":"forbidden"}'
        if mode == "unparseable":
            return 400, "application/json", b"this is not json at all"
        if mode == "unrelated_400":
            return 400, "application/json", json.dumps({
                "type": "error",
                "error": {"type": "invalid_request_error",
                          "message": "Invalid request payload"},
            }).encode()
        raise AssertionError("unknown upstream mode %r" % mode)

    def set_mode(mode):
        runner["mode"] = mode
        runner["n"] = 0

    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
        _start_reasoning_proxy({"p": upstream}, state_path)
    if proc is None:
        shutil.rmtree(state_dir, ignore_errors=True)
        fail("Failed to set up test")
        return
    try:
        def send(model="sonnet"):
            before = len(mock_servers["p"]["requests"])
            status, _ = _send(proxy_port,
                              _reasoning_request(model=model, demanding=True))
            return status, len(mock_servers["p"]["requests"]) - before

        # Every non-complaint shape passes straight through: no rescue.
        for mode, model, expect in (("500", "sonnet", 500),
                                    ("401", "sonnet", 401),
                                    ("403", "sonnet", 403),
                                    ("unparseable", "sonnet", 400),
                                    ("unrelated_400", "sonnet", 400)):
            set_mode(mode)
            status, calls = send()
            if status != expect:
                fail("%s: client saw %s, expected %s" % (mode, status, expect))
                return
            if calls != 1:
                fail("%s: expected 1 upstream call (no rescue), got %d"
                     % (mode, calls))
                return
        pass_("401/403/500/unparseable/unrelated-400 never started a rescue")

        # Two 500s must not touch the credit: the switch still needs three
        # complaints from here (the absent credit reads as the default
        # saturation_on_switch).
        set_mode("500")
        send()
        send()
        if _reasoning_entry(state_path) is not None:
            fail("a non-complaint error mutated the credit or persisted "
                 "state")
            return
        set_mode("complaint")
        for i in (1, 2):
            status, _ = send()
            if status != 200:
                fail("complaint %d not served (%s)" % (i, status))
                return
        if _reasoning_entry(state_path) is not None:
            fail("the 500s counted toward the credit: the switch landed "
                 "after only two real complaints")
            return
        status, _ = send()
        if status != 200:
            fail("third complaint not served (%s)" % status)
            return
        if _reasoning_entry(state_path) is None:
            fail("three real complaints did not persist the switch")
            return
        pass_("non-complaint errors did not count toward the credit")

        # A non-complaint result inside a rescue stops it and returns the
        # ORIGINAL top-level result, not the rescue's error.
        set_mode("complaint_then_500")
        status, calls = send(model="haiku")
        if status != 400:
            fail("a stopped rescue returned %s to the client; it must return "
                 "the original 400 it provoked" % status)
            return
        if calls != 2:
            fail("expected the rescue to stop after 1 pass (2 calls), got %d"
                 % calls)
            return
        if _reasoning_entry(state_path, model="claude-haiku-4-5") is not None:
            fail("a stopped rescue persisted state")
            return
        pass_("a non-complaint rescue pass stopped the rescue and returned "
              "the original result")
    finally:
        cleanup()
        shutil.rmtree(state_dir, ignore_errors=True)


def test_compat_guarded_parse_nesting_limit():
    """A >limit error body is refused unparsed and logged at compat_error_body.

    Both complaint matchers route through _compat_guarded_parse, so one check
    covers the whole family. The event carries the shared builder's full field
    set — site, depth, offset, path, degrade (plus the shared timestamp) —
    and deliberately no request_id/tier/mode/provider: the helper is called
    from matcher contexts that do not thread one. ``degrade`` is null here
    because the crossing is well-formed, so a path resolves. Asserted against
    the trace bytes appended by this call alone, so a session-shared trace file
    cannot satisfy it from another test's event.
    """
    print("\n--- Test: Compat Guarded Parse Nesting Limit ---")
    # Importing server binds the process-wide trace sink to PROXY_TRACE_FILE
    # (server.py's import-time sinks.configure); compat alone leaves the sink
    # pathless, so the event under test would never reach the file.
    import claude_retry_proxy.server as _srv  # noqa: F401
    import claude_retry_proxy.compat as compat

    trace_file = os.environ.get("PROXY_TRACE_FILE")
    if not trace_file or not os.path.exists(trace_file):
        fail("expected PROXY_TRACE_FILE to be set to an existing temp path, got {!r}".format(
            trace_file))
        return
    start = os.path.getsize(trace_file)

    limit = MAX_JSON_NESTING_DEPTH
    body = (b'{"error":{"message":"invalid","deep":'
            + b"[" * (limit + 1) + b"]" * (limit + 1) + b"}}")
    got = compat._compat_guarded_parse(body)
    if got is not None:
        fail("a >limit error body was parsed instead of refused: {!r}".format(got))
        return

    appended = []
    with open(trace_file) as f:
        f.seek(start)
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                appended.append(json.loads(line))
            except Exception:
                continue
    events = [e for e in appended if e.get("event") == "nesting_limit_exceeded"]
    if len(events) != 1:
        fail("expected exactly one nesting_limit_exceeded event for this call, "
             "got {!r}".format([e.get("event") for e in appended]))
        return
    ev = events[0]
    if ev.get("site") != "compat_error_body":
        fail("expected site compat_error_body, got {!r}".format(ev.get("site")))
        return
    # The shared builder's field set, verbatim: an exact-set assertion is
    # exactly what a single-sourced field set changes, so this is the one
    # place the full shape is pinned.
    expected_keys = {"timestamp", "event", "site", "depth", "offset", "path",
                     "degrade"}
    if set(ev) != expected_keys:
        fail("compat_error_body event must carry exactly {}, got {!r}".format(
            sorted(expected_keys), sorted(ev)))
        return
    if not isinstance(ev.get("path"), str):
        fail("expected a resolved path for a well-formed crossing, got "
             "{!r}".format(ev.get("path")))
        return
    if ev.get("degrade") is not None:
        fail("expected degrade null when a path resolved, got {!r}".format(
            ev.get("degrade")))
        return
    if ev.get("depth") != limit + 1:
        fail("expected depth {}, got {!r}".format(limit + 1, ev.get("depth")))
        return
    if not isinstance(ev.get("offset"), int) or ev["offset"] <= 0:
        fail("expected a positive crossing offset, got {!r}".format(ev.get("offset")))
        return
    pass_(">limit error body -> None with a compat_error_body event "
          "(depth {}, offset {})".format(ev["depth"], ev["offset"]))


def test_reasoning_matcher_shapes():
    """The reasoning complaint matcher accepts every shape that names a field
    and rejects everything else — including the echoed-request traversal — and
    a body past the nesting limit is refused unparsed, degrading to False for
    both matchers."""
    print("\n--- Test: Reasoning Matcher Shapes ---")
    import claude_retry_proxy.compat as compat
    match = compat._reasoning_complaint_match

    def envelope(text, **extra):
        err = {"type": "invalid_request_error", "message": text}
        err.update(extra)
        return json.dumps({"type": "error", "error": err}).encode()

    accepted = [
        ("pass-back form",
         envelope("The reasoning_content in the thinking mode must be passed "
                  "back to the API.")),
        ("both-fields form",
         envelope("assistant reasoning and reasoning_content cannot both be "
                  "specified")),
        ("bare field name", envelope("reasoning_content")),
        ("sentence-final form", envelope("unknown field reasoning_content.")),
        ("vllm-style field name", envelope("unknown field reasoning.")),
        ("structured loc form", json.dumps({"type": "error", "error": {
            "type": "invalid_request_error",
            "message": "Extra inputs are not permitted",
            "code": "extra_forbidden",
            "loc": ["messages", 0, "reasoning_content"],
        }}).encode()),
    ]
    for label, body in accepted:
        if not match(400, body):
            fail("matcher rejected the %s: %r" % (label, body))
            return

    rejected = [
        ("dotted nested path as prose", 400,
         envelope("messages.0.reasoning_content")),
        ("field only inside an echoed request payload", 400, json.dumps({
            "type": "error", "error": {
                "type": "invalid_request_error",
                "message": "Invalid request payload",
                "request": {"messages": [
                    {"role": "assistant", "reasoning_content": "x"}]},
            }}).encode()),
        ("structured loc naming another feature's field", 400,
         json.dumps({"type": "error", "error": {
             "code": "extra_forbidden", "loc": ["body", "context_management"],
         }}).encode()),
    ]
    rejected += REJECTED_BODY_CORPUS
    for label, status, body in rejected:
        if match(status, body):
            fail("matcher accepted the %s (status %d): %r"
                 % (label, status, body[:120]))
            return

    # A body far past the nesting limit is refused by the boundary check
    # BEFORE json.loads runs: both matchers degrade to False through the same
    # total helper, and the only thing exercised here is the nesting branch
    # (no RecursionError is involved any more). The dedicated
    # test_compat_guarded_parse_nesting_limit pins the helper's return and
    # event; this case pins that both matchers inherit the verdict.
    deep = b"[" * 100000 + b"]" * 100000
    for name, fn in (("reasoning", match),
                     ("context_management", compat._compat_rejection_match)):
        try:
            got = fn(400, deep)
        except Exception as e:
            fail("%s matcher raised on deeply nested input: %r" % (name, e))
            return
        if got:
            fail("%s matcher matched deeply nested input" % name)
            return

    pass_("matcher shapes: %d accepted, %d rejected, a >limit body degrades "
          "to False for both matchers" % (len(accepted), len(rejected)))


def test_reasoning_delist_on_none_success():
    """A credit-driven switch whose next candidate is the literal "none"
    removes the entry rather than writing selection: "none", so absence is
    what the next load resolves the default from.

    The trigger is the credit edge, not a served walk candidate: with
    saturation_on_switch 1 the seeded entry's absent credit reads as 1, so a
    single matched complaint drains it to 0 and advances one step —
    "reasoning" -> "none" — which delists. The rescue's first pass then wraps
    to the "none" candidate, which cannot inject a field name of its own: it
    sends the entry's current selection ("reasoning", read at request entry)
    and reports it as `effective_field`.

    The conversation carries a trailing bare assistant turn, so attempt 1
    leaves it without the field and the mock serves only a body that fills it:
    the assertion is that the repaired bytes — not a same-body re-roll —
    served the client. The trailing turn has no tool_use, so the demanding-turn
    credit gate still sees the reasoned tool-call turn and the delist trigger
    is unaffected."""
    print("\n--- Test: Reasoning Delist On None Success ---")
    state_dir, state_path = _make_state_dir()
    _seed_reasoning_state(state_path, "reasoning")
    log = []
    calls = {"n": 0}

    def upstream(info):
        log.append(info)
        calls["n"] += 1
        if calls["n"] == 1:
            return 400, "application/json", REASONING_MESSAGE_400
        _values, every = _forwarded_assistant_fields(info, "reasoning")
        if every:
            return _chat_ok_response(info)
        return 400, "application/json", REASONING_MESSAGE_400

    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
        _start_reasoning_proxy(
            {"p": upstream}, state_path,
            reasoning_field_switch={"saturation_on_switch": 1})
    if proc is None:
        shutil.rmtree(state_dir, ignore_errors=True)
        fail("Failed to set up test")
        return
    try:
        conversation = {
            "model": "sonnet",
            "max_tokens": 16,
            "messages": [
                {"role": "user", "content": [{"type": "text", "text": "hi"}]},
                {"role": "assistant", "content": [
                    {"type": "thinking", "thinking": "hmm", "signature": "s"},
                    {"type": "tool_use", "id": "toolu_demand",
                     "name": "lookup", "input": {}},
                ]},
                {"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": "toolu_demand",
                     "content": "ok"}]},
                {"role": "assistant", "content": [
                    {"type": "text", "text": "done"}]},
            ],
        }
        status, _ = _send(proxy_port, conversation)
        if status != 200:
            fail("the complaint was not served by the rescue (%s)" % status)
            return
        first_values, first_every = _forwarded_assistant_fields(
            log[0], "reasoning")
        if first_every:
            fail("attempt 1 already carried the field on every assistant "
                 "message, so the repair is not what served the client: %r"
                 % (first_values,))
            return
        sent = [_sent_reasoning_field(i) for i in log]
        if sent != ["reasoning", "reasoning"]:
            fail("the wrap pass must send the entry's current selection when "
                 "the candidate is 'none', upstream saw %r" % (sent,))
            return
        values, every = _forwarded_assistant_fields(log[1], "reasoning")
        if not every or values != ["hmm", ""]:
            fail("the repaired rescue body must carry the real text then \"\" "
                 "on every assistant message, got %r (every=%r)"
                 % (values, every))
            return
        events = _rescue_trace_events(trace_file)
        if (len(events) != 1 or events[0].get("candidate") != "none"
                or events[0].get("effective_field") != "reasoning"):
            fail("expected one rescue event with candidate 'none' and "
                 "effective_field 'reasoning', got %r"
                 % ([(e.get("candidate"), e.get("effective_field"))
                     for e in events],))
            return
        entry = _reasoning_entry(state_path)
        if entry is not None:
            fail("the credit-driven switch to 'none' should have delisted the "
                 "entry, found %r" % (entry,))
            return
        events = [e.get("event") for e in _compat_trace_events(trace_file)]
        if "compatibility_delisted" not in events:
            fail("no compatibility_delisted event: %r" % (events,))
            return
        pass_("a credit-driven switch to 'none' delisted the entry instead of "
              "writing selection: none")
    finally:
        cleanup()
        shutil.rmtree(state_dir, ignore_errors=True)


def test_reasoning_credit_saturates_and_drains():
    """The reasoning_field credit is a saturating capacitor fed by attempt-1
    outcomes: a gate-true success raises it by one up to saturation_max; each
    gate-true matched complaint lowers it by one; the switch persists exactly
    on the edge where it reaches 0, re-arms at saturation_on_switch, and
    advances the entry one step from its CURRENT selection.

    A saturated credit is what makes the cap observable: an uncapped one would
    sit far above saturation_max after the success run and the complaint
    count below could not reach the edge.
    """
    print("\n--- Test: Reasoning Credit Saturates And Drains ---")
    state_dir, state_path = _make_state_dir()
    policy = {"accept": ("none",)}
    responders = {"p": _reasoning_upstream(policy)}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
        _start_reasoning_proxy(
            responders, state_path,
            reasoning_field_switch={"saturation_max": 4,
                                    "saturation_on_switch": 2})
    if proc is None:
        shutil.rmtree(state_dir, ignore_errors=True)
        fail("Failed to set up test")
        return
    try:
        def send():
            before = len(mock_servers["p"]["requests"])
            status, _ = _send(proxy_port, _reasoning_request(demanding=True))
            return status, len(mock_servers["p"]["requests"]) - before

        def switch_events():
            return [e.get("event") for e in _compat_trace_events(trace_file)
                    if e.get("event") in ("compatibility_learned",
                                          "compatibility_switched",
                                          "compatibility_delisted")]

        # (a) Saturate: six gate-true successes move the credit
        # 2 (absent -> saturation_on_switch) -> 3 -> 4 -> 4 -> 4 -> 4.
        for i in range(6):
            status, calls = send()
            if status != 200 or calls != 1:
                fail("saturation success %d: status %s, %d upstream call(s)"
                     % (i + 1, status, calls))
                return
        if _reasoning_entry(state_path) is not None:
            fail("a success alone persisted an entry")
            return
        pass_("six gate-true successes saturated the credit without switching")

        # (b) Drain from saturation_max (4): three complaints must not switch
        # and the fourth (the edge to 0) must.
        policy["accept"] = ("reasoning_content",)
        for i in (1, 2, 3):
            status, calls = send()
            if status != 200 or calls != 2:
                fail("drain complaint %d: status %s, %d upstream call(s) "
                     "(expected 200 served by one rescue pass)"
                     % (i, status, calls))
                return
            if _reasoning_entry(state_path) is not None:
                fail("the switch landed after %d complaint(s); a saturated "
                     "credit of 4 must need 4" % i)
                return
        pass_("three complaints did not switch a saturated credit of 4")

        if send()[0] != 200:
            fail("the fourth complaint was not served by the rescue")
            return
        entry = _reasoning_entry(state_path)
        if entry is None or entry.get("selection") != "reasoning_content":
            fail("the edge to 0 did not advance none -> reasoning_content: %r"
                 % (entry,))
            return
        if switch_events() != ["compatibility_learned"]:
            fail("expected exactly one compatibility_learned event, got %r"
                 % (switch_events(),))
            return
        pass_("the fourth complaint switched (none -> reasoning_content) and "
              "emitted compatibility_learned")

        # (c) The switch re-armed the credit at saturation_on_switch (2), so
        # the next switch needs exactly two further complaints and advances
        # one step from the entry's current selection.
        policy["accept"] = ("reasoning",)
        status, calls = send()
        if status != 200 or calls != 2:
            fail("post-switch complaint: status %s, %d upstream call(s)"
                 % (status, calls))
            return
        entry = _reasoning_entry(state_path)
        if entry is None or entry.get("selection") != "reasoning_content":
            fail("one post-switch complaint switched — the credit was not "
                 "re-armed at saturation_on_switch: %r" % (entry,))
            return
        if send()[0] != 200:
            fail("the second post-switch complaint was not served")
            return
        entry = _reasoning_entry(state_path)
        if entry is None or entry.get("selection") != "reasoning":
            fail("the second post-switch complaint did not advance "
                 "reasoning_content -> reasoning: %r" % (entry,))
            return
        if switch_events() != ["compatibility_learned",
                               "compatibility_switched"]:
            fail("expected learned then switched, got %r"
                 % (switch_events(),))
            return
        pass_("the re-armed credit switched after exactly two complaints, one "
              "step from the entry's current selection")
    finally:
        cleanup()
        shutil.rmtree(state_dir, ignore_errors=True)


def test_reasoning_present_gates_on_demanding_turn():
    """The reasoning presence gate is DEMANDING-TURN scoped.

    It is True only when the LAST assistant message carrying a tool_use block
    also carries non-empty reasoning (a thinking block, or a redacted_thinking
    with non-empty data). A history full of reasoning does not rescue a bare
    demanding turn; reasoning with no tool call anywhere is not learnable; and
    an assistant message AFTER the tool-call turn (which carries no tool_use)
    must not change the verdict — the scan past it is the divergence the
    whole-body scan got wrong. Total: any shape it cannot interpret is False.
    """
    print("\n--- Test: Reasoning Present Gates On Demanding Turn ---")
    import claude_retry_proxy.compat as compat
    present = compat._reasoning_present

    def text(t):
        return {"type": "text", "text": t}

    def thinking(t):
        return {"type": "thinking", "thinking": t, "signature": ""}

    def tool_use(call_id="t1"):
        return {"type": "tool_use", "id": call_id, "name": "t", "input": {}}

    def tool_result(call_id="t1"):
        return {"type": "tool_result", "tool_use_id": call_id, "content": "ok"}

    def body(messages):
        return {"messages": messages}

    bare_demanding = body([
        {"role": "user", "content": [text("hi")]},
        {"role": "assistant", "content": [thinking("old reasoning"),
                                          tool_use("t1")]},
        {"role": "user", "content": [tool_result("t1")]},
        {"role": "assistant", "content": [text("now I write"),
                                          tool_use("t2")]},
        {"role": "user", "content": [tool_result("t2")]},
    ])
    if present(bare_demanding) is not False:
        fail("a bare demanding turn over a reasoned history must be False "
             "(a missing-field complaint says nothing about the field name), "
             "got %r" % (present(bare_demanding),))
        return
    pass_("a bare demanding turn over a reasoned history is not learnable")

    reasoned_demanding = body([
        {"role": "user", "content": [text("hi")]},
        {"role": "assistant", "content": [thinking("old reasoning"),
                                          tool_use("t1")]},
        {"role": "user", "content": [tool_result("t1")]},
        {"role": "assistant", "content": [thinking("this turn reasoned"),
                                          tool_use("t2")]},
        {"role": "user", "content": [tool_result("t2")]},
    ])
    if present(reasoned_demanding) is not True:
        fail("a reasoned demanding turn must be True, got %r"
             % (present(reasoned_demanding),))
        return
    pass_("a reasoned demanding turn is learnable")

    no_tool_call = body([
        {"role": "user", "content": [text("hi")]},
        {"role": "assistant", "content": [thinking("thinking, no tool"),
                                          text("hello")]},
    ])
    if present(no_tool_call) is not False:
        fail("reasoning with no tool-call turn anywhere must be False, got %r"
             % (present(no_tool_call),))
        return
    pass_("reasoning without any tool call is not learnable")

    # Divergence case: a later reasoned assistant turn without tool_use must
    # not rescue the bare tool-call turn before it — the scan skips past it.
    divergent = body([
        {"role": "user", "content": [text("hi")]},
        {"role": "assistant", "content": [tool_use("t1")]},
        {"role": "user", "content": [tool_result("t1")]},
        {"role": "assistant", "content": [thinking("later reasoning"),
                                          text("no tool here")]},
    ])
    if present(divergent) is not False:
        fail("a later reasoned assistant turn must not rescue a bare "
             "tool-call turn, got %r" % (present(divergent),))
        return
    pass_("a later tool_use-less assistant turn does not change the verdict")

    redacted = body([
        {"role": "assistant", "content": [
            {"type": "redacted_thinking", "data": "enc", "signature": "s"},
            tool_use("t1")]},
    ])
    if present(redacted) is not True:
        fail("a demanding turn with redacted_thinking data must be True, got "
             "%r" % (present(redacted),))
        return
    empty_redacted = body([
        {"role": "assistant", "content": [
            {"type": "redacted_thinking", "data": "", "signature": "s"},
            tool_use("t1")]},
    ])
    if present(empty_redacted) is not False:
        fail("an empty redacted_thinking data block must not count as "
             "reasoning, got %r" % (present(empty_redacted),))
        return
    empty_thinking = body([
        {"role": "assistant", "content": [thinking(""), tool_use("t1")]},
    ])
    if present(empty_thinking) is not False:
        fail("an empty thinking block must not count as reasoning, got %r"
             % (present(empty_thinking),))
        return
    pass_("non-empty thinking or redacted_thinking data gates; empty does not")

    for label, value in (
            ("a non-dict body", None),
            ("a body with no messages", {}),
            ("messages not a list", {"messages": "nonsense"}),
            ("uninterpretable message shapes",
             {"messages": ["nonsense", 42, {"role": "assistant"}]}),
            ("a string assistant content",
             {"messages": [{"role": "assistant", "content": "hi"}]})):
        if present(value) is not False:
            fail("totality: %s must be False, got %r"
                 % (label, present(value)))
            return
    pass_("totality guards: every uninterpretable shape is False")


def test_reasoning_rescued_success_does_not_teach():
    """A rescue-served 2xx is not learning evidence: each episode's attempt 1
    complains (draining the credit) and the rescue serves the client, yet the
    credit still reaches 0 and switches after exactly saturation_on_switch
    such episodes. A refill wired to the merged result would stall the drain
    and fail here."""
    print("\n--- Test: Reasoning Rescued Success Does Not Teach ---")
    state_dir, state_path = _make_state_dir()
    policy = {"accept": ("reasoning_content",)}
    responders = {"p": _reasoning_upstream(policy)}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
        _start_reasoning_proxy(
            responders, state_path,
            reasoning_field_switch={"saturation_max": 3,
                                    "saturation_on_switch": 2})
    if proc is None:
        shutil.rmtree(state_dir, ignore_errors=True)
        fail("Failed to set up test")
        return
    try:
        for i in (1, 2):
            before = len(mock_servers["p"]["requests"])
            status, _ = _send(proxy_port,
                              _reasoning_request(demanding=True))
            calls = len(mock_servers["p"]["requests"]) - before
            if status != 200:
                fail("episode %d: the rescue did not serve the client (%s)"
                     % (i, status))
                return
            if calls != 2:
                fail("episode %d: expected attempt 1 + one rescue pass "
                     "(2 upstream calls), got %d" % (i, calls))
                return
            if i == 1 and _reasoning_entry(state_path) is not None:
                fail("episode 1 switched: a credit of saturation_on_switch 2 "
                     "must need 2 complaints, and a rescued 2xx must not "
                     "refill it: %r" % (_reasoning_entry(state_path),))
                return
        entry = _reasoning_entry(state_path)
        if entry is None or entry.get("selection") != "reasoning_content":
            fail("two rescued episodes did not drain the credit to the switch "
                 "edge (a rescued 2xx refilled it): %r" % (entry,))
            return
        outcomes = [e.get("outcome") for e in _rescue_trace_events(trace_file)]
        if outcomes != ["served", "served"]:
            fail("expected one served rescue per episode, got %r"
                 % (outcomes,))
            return
        pass_("two rescued 2xx episodes drained the credit to 0 and switched")
    finally:
        cleanup()
        shutil.rmtree(state_dir, ignore_errors=True)


def test_reasoning_rescue_runs_without_thinking():
    """A matched complaint on a gate-false body (no thinking block) still gets
    the rescue: a stateful mock that 400s the first call and 200s the second
    yields a client 200 plus a reasoning_rescue event, and several such
    episodes leave the persisted selection untouched — gate-false complaints
    are not learning evidence.

    Every rescue pass on a thinking-free body is a same-body re-roll (no
    thinking block means the transform emits no echo for any candidate), so
    neither the attempt nor its rescue may carry a reasoning field."""
    print("\n--- Test: Reasoning Rescue Runs Without Thinking ---")
    state_dir, state_path = _make_state_dir()
    log = []
    calls = {"n": 0}

    def upstream(info):
        log.append(info)
        calls["n"] += 1
        if calls["n"] % 2 == 1:
            return 400, "application/json", REASONING_MESSAGE_400
        return _chat_ok_response(info)

    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
        _start_reasoning_proxy({"p": upstream}, state_path)
    if proc is None:
        shutil.rmtree(state_dir, ignore_errors=True)
        fail("Failed to set up test")
        return
    try:
        for i in (1, 2, 3):
            before = len(log)
            status, _ = _send(proxy_port, _reasoning_request(
                with_thinking=False))
            sent = [_sent_reasoning_field(x) for x in log[before:]]
            if status != 200:
                fail("gate-false episode %d: the rescue did not serve the "
                     "client (%s)" % (i, status))
                return
            if len(sent) != 2:
                fail("gate-false episode %d: expected attempt 1 + one rescue "
                     "pass (2 upstream calls), got %d" % (i, len(sent)))
                return
            if sent != [None, None]:
                fail("gate-false episode %d: a pass emitted a reasoning field "
                     "on a thinking-free body: %r" % (i, sent))
                return
        if _reasoning_entry(state_path) is not None:
            fail("gate-false complaints taught a selection: %r"
                 % (_reasoning_entry(state_path),))
            return
        rescues = _rescue_trace_events(trace_file)
        if len(rescues) != 3 or any(e.get("outcome") != "served"
                                    for e in rescues):
            fail("expected 3 served reasoning_rescue events, got %r"
                 % ([(e.get("attempt"), e.get("outcome")) for e in rescues],))
            return
        if _compat_trace_events(trace_file):
            fail("a gate-false complaint emitted a compatibility_ learner "
                 "event: %r" % (_compat_trace_events(trace_file),))
            return
        pass_("gate-false complaints are rescued, teach nothing, and emit no "
              "learner event")
    finally:
        cleanup()
        shutil.rmtree(state_dir, ignore_errors=True)


def test_reasoning_rescue_events_and_merge():
    """A full rescue emits one metadata-only reasoning_rescue event per
    attempt, with the documented key set; on exhaustion the client receives
    attempt 1's ORIGINAL error (status and bytes); a 429/503 on a rescue pass
    is a non-complaint that stops the rescue and serves attempt-1's error; and
    the request entry's `retries` field keeps its 429/503-only meaning.

    The mock's three complaint bodies differ, so "the client got attempt 1's
    error" is distinguishable from any rescue pass's error rather than
    passing on identical bytes."""
    print("\n--- Test: Reasoning Rescue Events And Merge ---")
    state_dir, state_path = _make_state_dir()
    attempt1_body = REASONING_MESSAGE_400
    pass1_body = json.dumps({"type": "error", "error": {
        "type": "invalid_request_error",
        "message": "Extra inputs are not permitted",
        "code": "extra_forbidden",
        "loc": ["messages", 0, "reasoning_content"],
    }}).encode()
    pass2_body = json.dumps({"type": "error", "error": {
        "type": "invalid_request_error",
        "message": "unknown field reasoning.",
    }}).encode()
    runner = {"mode": "exhaust", "n": 0}

    def upstream(info):
        runner["n"] += 1
        if runner["mode"] == "exhaust":
            return 400, "application/json", (attempt1_body, pass1_body,
                                             pass2_body)[
                min(runner["n"], 3) - 1]
        if runner["mode"] == "503stop":
            if runner["n"] == 1:
                return 400, "application/json", attempt1_body
            return 503, "application/json", b'{"error":"unavailable"}'
        raise AssertionError("unknown upstream mode %r" % runner["mode"])

    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
        _start_reasoning_proxy({"p": upstream}, state_path)
    if proc is None:
        shutil.rmtree(state_dir, ignore_errors=True)
        fail("Failed to set up test")
        return
    try:
        def episode(mode):
            runner["mode"] = mode
            runner["n"] = 0
            before_ev = len(_rescue_trace_events(trace_file))
            before_req = len(mock_servers["p"]["requests"])
            status, body = _send(proxy_port,
                                 _reasoning_request(demanding=True))
            events = _rescue_trace_events(trace_file)[before_ev:]
            calls = len(mock_servers["p"]["requests"]) - before_req
            return status, body, events, calls

        def request_entry(request_id):
            for ev in _trace_events_named(trace_file, "request"):
                if ev.get("request_id") == request_id:
                    return ev
            return None

        status, body, events, calls = episode("exhaust")
        if status != 400 or body != attempt1_body:
            fail("exhaustion served the rescue's error, not attempt 1's "
                 "(status %s, body %r)" % (status, body[:120]))
            return
        if calls != 3:
            fail("expected attempt 1 + 2 rescue passes (3 upstream calls), "
                 "got %d" % calls)
            return
        if len(events) != 2:
            fail("expected one reasoning_rescue event per rescue attempt, "
                 "got %d" % len(events))
            return
        expected_keys = {"timestamp", "event", "request_id", "provider",
                         "mode", "actual_model", "tier", "feature", "attempt",
                         "candidate", "effective_field", "outcome",
                         "http_status"}
        for ev, attempt, candidate in zip(events, (1, 2),
                                          ("reasoning_content", "reasoning")):
            if set(ev) != expected_keys:
                fail("reasoning_rescue key set drifted: unexpected %s, "
                     "missing %s"
                     % (sorted(set(ev) - expected_keys),
                        sorted(expected_keys - set(ev))))
                return
            if (ev.get("event") != "reasoning_rescue"
                    or ev.get("attempt") != attempt
                    or ev.get("candidate") != candidate
                    or ev.get("outcome") != "complaint"
                    or ev.get("http_status") != 400):
                fail("rescue event %d is wrong: %r" % (attempt, ev))
                return
            # A non-"none" candidate is also the field actually sent; the two
            # differ only on a "none" candidate, where the pass falls back to
            # the entry's selection.
            if ev.get("effective_field") != candidate:
                fail("rescue event %d sent a different field than its "
                     "candidate without an effective_field record: %r"
                     % (attempt, ev))
                return
            if (ev.get("provider") != "p" or ev.get("mode") != "chat"
                    or ev.get("tier") != "sonnet"
                    or ev.get("actual_model") != "claude-sonnet-5"
                    or ev.get("feature") != "reasoning_field"
                    or not ev.get("request_id")):
                fail("rescue event metadata is wrong: %r" % (ev,))
                return
        if events[0].get("request_id") != events[1].get("request_id"):
            fail("the two rescue attempts name different requests")
            return
        pass_("exhaustion: one metadata-only event per attempt, exact key set; "
              "the client received attempt 1's exact error")

        # `retries` keeps its 429/503-only meaning: the full rescue took no
        # retry and the request entry says so.
        entry = request_entry(events[0].get("request_id"))
        if entry is None:
            fail("no request trace entry for %r"
                 % (events[0].get("request_id"),))
            return
        if entry.get("retries") != 0:
            fail("the request entry counted a rescue pass as a retry: %r"
                 % (entry.get("retries"),))
            return
        pass_("the request entry's retries stayed 0 across a two-pass rescue")

        # A 429/503 on a rescue pass is a non-complaint: the rescue stops and
        # attempt 1's error is served.
        status, body, events, calls = episode("503stop")
        if status != 400 or body != attempt1_body:
            fail("a 503 rescue pass did not hand the client attempt 1's "
                 "error (status %s, body %r)" % (status, body[:120]))
            return
        if calls != 2:
            fail("a 503 rescue pass did not stop the rescue (%d upstream "
                 "calls, expected 2 — the pass is a single attempt)" % calls)
            return
        if (len(events) != 1 or events[0].get("outcome") != "other"
                or events[0].get("http_status") != 503
                or events[0].get("attempt") != 1):
            fail("the 503 stop's rescue event is wrong: %r"
                 % ([{k: e.get(k) for k in ("attempt", "outcome",
                                            "http_status")}
                     for e in events],))
            return
        entry = request_entry(events[0].get("request_id"))
        if entry is None or entry.get("retries") != 0:
            fail("the 503-on-rescue request entry counted a retry: %r"
                 % (entry.get("retries") if entry else None,))
            return
        pass_("a 503 rescue pass stopped the rescue and served attempt 1's "
              "error with retries 0")
    finally:
        cleanup()
        shutil.rmtree(state_dir, ignore_errors=True)


def test_reasoning_rescue_repairs_forwarded_body():
    """A rescue pass FORCES the always-present field on, so an UNFLAGGED
    provider repairs itself without a models.json edit.

    Two episodes, neither carrying a reasoning_roundtrip policy: (a) no
    persisted entry, so the first candidate is `reasoning_content`; (b) a
    seeded `reasoning` entry, so the first candidate wraps to "none" — which
    has no field name to write, and the pass sends the entry's selection
    instead, reporting it as `effective_field`.

    The assertion is on the REPAIRED BYTES the proxy actually forwarded:
    attempt 1 leaves at least one assistant message bare, the rescue pass
    carries the field on EVERY assistant message — the real thinking text on
    the reasoned turn, "" on the bare one.
    """
    print("\n--- Test: Reasoning Rescue Repairs Forwarded Body ---")

    def demanding_conversation():
        return {
            "model": "sonnet",
            "max_tokens": 16,
            "messages": [
                {"role": "user",
                 "content": [{"type": "text", "text": "hi"}]},
                {"role": "assistant", "content": [
                    {"type": "thinking", "thinking": "the real reasoning",
                     "signature": "s"},
                    {"type": "tool_use", "id": "t1", "name": "lookup",
                     "input": {}},
                ]},
                {"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": "t1",
                     "content": "ok"}]},
                {"role": "assistant", "content": [
                    {"type": "tool_use", "id": "t2", "name": "lookup",
                     "input": {}},
                ]},
                {"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": "t2",
                     "content": "ok"}]},
            ],
        }

    for seeded, field, expect_candidate, expect_effective, label in (
            (None, "reasoning_content", "reasoning_content",
             "reasoning_content", "no entry -> first candidate injects"),
            ("reasoning", "reasoning", "none", "reasoning",
             "seeded entry -> the 'none' candidate falls back to its selection")):
        state_dir, state_path = _make_state_dir()
        if seeded is not None:
            _seed_reasoning_state(state_path, seeded)
        log = []

        def upstream(info, _field=field):
            log.append(info)
            if len(log) == 1:
                return 400, "application/json", REASONING_MESSAGE_400
            _values, every = _forwarded_assistant_fields(info, _field)
            if every:
                return _chat_ok_response(info)
            return 400, "application/json", REASONING_MESSAGE_400

        temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
            _start_reasoning_proxy({"p": upstream}, state_path)
        if proc is None:
            shutil.rmtree(state_dir, ignore_errors=True)
            fail("Failed to set up test (%s)" % label)
            return
        try:
            status, _ = _send(proxy_port, demanding_conversation())
            if status != 200:
                fail("%s: the repair did not serve the client (%s)"
                     % (label, status))
                return
            if len(log) != 2:
                fail("%s: expected attempt 1 + one rescue pass, got %d "
                     "upstream call(s)" % (label, len(log)))
                return
            first_values, first_every = _forwarded_assistant_fields(
                log[0], field)
            if first_every:
                fail("%s: attempt 1 already carried the field on every "
                     "assistant message, so the repair is not what served the "
                     "client: %r" % (label, first_values))
                return
            values, every = _forwarded_assistant_fields(log[1], field)
            if not every or values != ["the real reasoning", ""]:
                fail("%s: the forwarded rescue body must carry the real text "
                     "then \"\" on every assistant message, got %r (every=%r)"
                     % (label, values, every))
                return
            events = _rescue_trace_events(trace_file)
            if (len(events) != 1
                    or events[0].get("candidate") != expect_candidate
                    or events[0].get("effective_field") != expect_effective
                    or events[0].get("outcome") != "served"):
                fail("%s: expected one served rescue event with candidate %r "
                     "and effective_field %r, got %r"
                     % (label, expect_candidate, expect_effective,
                        [(e.get("candidate"), e.get("effective_field"),
                          e.get("outcome")) for e in events]))
                return
            pass_("%s: the repaired bytes carry %r on every assistant message"
                  % (label, field))
        finally:
            cleanup()
            shutil.rmtree(state_dir, ignore_errors=True)


def test_reasoning_switch_params_carried_across_admin():
    """The reasoning_field_switch policy survives both admin swaps: after
    /admin/api/switch and after /admin/api/reload, a fresh key still switches
    on its FIRST complaint (saturation_on_switch 1) — behaviour the dropped
    knob (default 3) cannot produce. A reload whose models.json carries a
    structurally invalid knob is refused 400 and installs nothing."""
    print("\n--- Test: Reasoning Switch Params Carried Across Admin ---")
    state_dir, state_path = _make_state_dir()
    policy = {"accept": ("reasoning_content",)}
    responders = {"p": _reasoning_upstream(policy)}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
        _start_reasoning_proxy(
            responders, state_path,
            reasoning_field_switch={"saturation_max": 4,
                                    "saturation_on_switch": 1})
    if proc is None:
        shutil.rmtree(state_dir, ignore_errors=True)
        fail("Failed to set up test")
        return
    tiers = _mode_tiers()
    models_path = os.path.join(temp_dir, "models.json")
    try:
        def one_complaint_episode(model, label):
            """One gate-true complaint on a key with no credit yet: with
            saturation_on_switch 1 it must switch on that single complaint."""
            status, _ = _send(proxy_port,
                              _reasoning_request(model=model, demanding=True))
            if status != 200:
                fail("%s: the rescue did not serve the client (%s)"
                     % (label, status))
                return False
            entry = _reasoning_entry(state_path,
                                     model=tiers[model]["model"])
            if entry is None or entry.get("selection") != "reasoning_content":
                fail("%s: a single complaint did not switch — the "
                     "reasoning_field_switch knob was dropped by the admin "
                     "swap (default saturation_on_switch 3): %r"
                     % (label, entry))
                return False
            return True

        # /admin/api/switch carries the knob into its in-memory rebuild.
        status, data = _admin_post(proxy_port, "/admin/api/switch",
                                   {"tiers": tiers})
        if status != 200:
            fail("admin switch failed: %s %s" % (status, data))
            return
        pass_("admin switch accepted")
        if not one_complaint_episode("haiku", "after /admin/api/switch"):
            return
        pass_("the switch kept the knob in effect (haiku switched on one "
              "complaint)")

        # /admin/api/reload carries it from the reloaded models.json.
        status, data = _admin_post(proxy_port, "/admin/api/reload", {})
        if status != 200:
            fail("admin reload failed: %s %s" % (status, data))
            return
        pass_("admin reload accepted")
        if not one_complaint_episode("opus", "after /admin/api/reload"):
            return
        pass_("the reload kept the knob in effect (opus switched on one "
              "complaint)")

        # A structurally invalid knob is refused at reload, before any drain.
        with open(models_path, "r", encoding="utf-8") as f:
            saved = f.read()
        try:
            doc = json.loads(saved)
            doc["reasoning_field_switch"] = ["not", "an", "object"]
            with open(models_path, "w", encoding="utf-8") as f:
                json.dump(doc, f)
            status, data = _admin_post(proxy_port, "/admin/api/reload", {})
            if status != 400 or "reasoning_field_switch" not in data:
                fail("a structurally invalid reasoning_field_switch was not "
                     "refused 400: %s %s" % (status, data))
                return
            pass_("reload refused a non-object reasoning_field_switch with 400")
        finally:
            with open(models_path, "w", encoding="utf-8") as f:
                f.write(saved)

        # The refused reload installed nothing: a third fresh key still
        # switches on one complaint.
        if not one_complaint_episode("sonnet", "after the refused reload"):
            return
        pass_("the refused reload left the knob in effect")
    finally:
        cleanup()
        shutil.rmtree(state_dir, ignore_errors=True)


ALL_TESTS = [
    # G. reasoning_field (chat mode)
    ("reasoning-walk-sends-advanced-candidate", test_reasoning_walk_sends_advanced_candidate),
    ("reasoning-non-complaint-errors-are-not-counted", test_reasoning_non_complaint_errors_are_not_counted),
    ("reasoning-matcher-shapes", test_reasoning_matcher_shapes),
    ("compat-guarded-parse-nesting-limit", test_compat_guarded_parse_nesting_limit),
    ("reasoning-present-gates-on-demanding-turn", test_reasoning_present_gates_on_demanding_turn),
    ("reasoning-delist-on-none-success", test_reasoning_delist_on_none_success),
    ("reasoning-credit-saturates-and-drains", test_reasoning_credit_saturates_and_drains),
    ("reasoning-rescued-success-does-not-teach", test_reasoning_rescued_success_does_not_teach),
    ("reasoning-rescue-runs-without-thinking", test_reasoning_rescue_runs_without_thinking),
    ("reasoning-rescue-events-and-merge", test_reasoning_rescue_events_and_merge),
    ("reasoning-rescue-repairs-forwarded-body", test_reasoning_rescue_repairs_forwarded_body),
    ("reasoning-switch-params-carried-across-admin", test_reasoning_switch_params_carried_across_admin),
]


if __name__ == "__main__":
    run_cli(ALL_TESTS, "claude-retry-proxy tests: test_compat_reasoning")
