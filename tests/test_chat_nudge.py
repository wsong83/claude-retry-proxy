"""Chat-mode retry-nudge family tests.

Part of the claude-retry-proxy suite; runnable standalone.
"""

import json
import time
from _harness import (
    _cc,
    _chat_sse_fetch_frames,
    _mode_tiers,
    _sse_frames_with_type,
    _sse_stop_reason,
    _sse_stream_chunks,
    _sse_types,
    _start_mode_proxy,
    fail,
    find_free_port,
    pass_,
    run_cli,
)
from test_chat_sse_drain import _trace_events_named


# --- Retry-nudge: the unfinished-turn detector acts (2026-10-05 plan) ---
# The fixtures and helpers below serve the chat-retry-nudge family. The
# feature is ON by default (PROXY_CHAT_RETRY_NUDGE unset -> default text);
# only test_chat_retry_nudge_disabled_by_empty_env turns it off.

NUDGE_MARK = "[proxy nudge]"  # substring of settings.DEFAULT_CHAT_RETRY_NUDGE


def _nudge_stall_sse_body(text="Now running the suite:"):
    """The unfinished-turn fixture: prose ending in ':' + finish stop + [DONE]."""
    chunks = [_cc({"role": "assistant", "content": text}),
              _cc({}, finish="stop")]
    return _sse_stream_chunks(chunks) + b"data: [DONE]\n\n"


def _nudge_tool():
    """The tools declaration that satisfies the detector's tools_declared gate."""
    return {"name": "lookup", "description": "look things up",
            "input_schema": {"type": "object", "properties": {}}}


def _events_for_request(trace_file, event_name, request_id):
    """Trace events of one name belonging to one request."""
    return [e for e in _trace_events_named(trace_file, event_name)
            if e.get("request_id") == request_id]


def _wait_for_event_count(trace_file, event_name, count, timeout_s=3.0):
    """Poll until at least `count` events of that name exist; return them.

    Complements _wait_for_trace_events (which stops at >=1): several of these
    tests must reach an exact per-stage count before asserting an absence.
    """
    deadline = time.time() + timeout_s
    while True:
        out = _trace_events_named(trace_file, event_name)
        if len(out) >= count or time.time() >= deadline:
            return out
        time.sleep(0.05)


def _assert_nudge_trailing(messages, context):
    """The upstream messages list ends with the nudge as a user message, exactly once."""
    if not messages or messages[-1].get("role") != "user" \
            or NUDGE_MARK not in json.dumps(messages[-1].get("content")):
        fail("{}: nudge must be the trailing user message, got {!r}".format(
            context, messages[-1] if messages else None))
        return False
    hits = sum(1 for m in messages if NUDGE_MARK in json.dumps(m.get("content")))
    if hits != 1:
        fail("{}: nudge must appear exactly once upstream, got {} copies".format(context, hits))
        return False
    return True


def _nudge_canonical(messages):
    import json as _j
    return _j.dumps(messages, separators=(",", ":"), sort_keys=True)


def test_chat_sse_unfinished_turn_errors_and_nudges_retry():
    """A tools-declaring turn ending in ':' with no tool call closes with a
    retryable api_error (no terminal frames), and the client's
    conversation-extending recovery gets the nudge injected upstream with a
    chat_retry_nudge event naming the errored request; the recovery's own
    stall passes through with terminal frames. A THIRD extension shows no
    nudge (the marker is consumed on match — single-use) and errors as a
    fresh stall; a byte-identical re-POST of that third request then matches
    the exact-hash branch. Carries the retired shadow test's field pins and
    its no-tools negative half.
    """
    print("\n--- Test: Chat SSE Unfinished Turn Errors And Nudges Retry ---")
    tool = _nudge_tool()
    upstream_port = find_free_port()
    tiers = _mode_tiers()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port),
                     "key": "K", "mode": "chat"}}
    sse_body = _nudge_stall_sse_body()  # answers every request: each stall re-fires
    responders = {"p": lambda info: (200, "text/event-stream", sse_body)}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
        _start_mode_proxy(tiers, vendors, responders=responders)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        # --- Request 1: the stall itself errors and arms its marker. ---
        body1 = {"model": "sonnet", "stream": True, "tools": [tool],
                 "messages": [{"role": "user", "content": "go"}]}
        frames1 = _chat_sse_fetch_frames(proxy_port, body=body1)
        if frames1 is None:
            return
        types1 = _sse_types(frames1)
        errs1 = _sse_frames_with_type(frames1, "error")
        if len(errs1) != 1 or (errs1[0].get("error") or {}).get("type") != "api_error":
            fail("stalled turn must close with exactly one api_error frame, "
                 "got {!r} ({})".format(errs1, types1))
            return
        present1 = [t for t in ("message_delta", "message_stop") if t in types1]
        if present1:
            fail("errored turn must not emit {}; got {}".format(present1, types1))
            return
        unfinished = _wait_for_event_count(trace_file, "chat_sse_unfinished_turn", 1)
        if len(unfinished) != 1:
            fail("expected exactly one chat_sse_unfinished_turn after stream 1, "
                 "got {}".format(len(unfinished)))
            return
        ev1 = unfinished[0]
        rid1 = ev1.get("request_id")
        # Field pins folded in from the retired shadow test.
        if ev1.get("rule") != "colon_after_prose":
            fail("unfinished-turn rule must be colon_after_prose, got {!r}".format(ev1.get("rule")))
            return
        if ev1.get("finish_reason") != "stop":
            fail("unfinished-turn finish_reason must be stop, got {!r}".format(ev1.get("finish_reason")))
            return
        if ev1.get("tools_declared") != 1:
            fail("tools-declaring request must log tools_declared 1, got {!r}".format(ev1.get("tools_declared")))
            return
        if ev1.get("tool_calls_seen") != 0 or ev1.get("emitted_tool_use") != 0:
            fail("detector predicates on no tool frames: got tool_calls_seen {!r}, "
                 "emitted_tool_use {!r}".format(ev1.get("tool_calls_seen"), ev1.get("emitted_tool_use")))
            return
        if not isinstance(ev1.get("text_tail_len"), int) or ev1.get("text_tail_len") <= 0:
            fail("text_tail_len must be a positive int, got {!r}".format(ev1.get("text_tail_len")))
            return
        if "provider" not in ev1 or "key" not in ev1:
            fail("unfinished-turn event must carry provider and key, got keys {}".format(sorted(ev1)))
            return
        drain1 = _events_for_request(trace_file, "chat_sse_drain", rid1)
        if len(drain1) != 1 or drain1[0].get("tools_declared") != 1:
            fail("stream 1 must log exactly one chat_sse_drain with tools_declared 1, "
                 "got {!r}".format(drain1))
            return
        nudges = _wait_for_event_count(trace_file, "chat_retry_nudge", 1, timeout_s=1.0)
        if nudges:  # the original request must never be nudged
            fail("request 1 must not log chat_retry_nudge, got {}".format(len(nudges)))
            return

        # --- Request 2: conversation-extending recovery -> prefix-branch nudge. ---
        body2 = {"model": "sonnet", "stream": True, "tools": [tool],
                 "messages": body1["messages"] + [
                     {"role": "assistant",
                      "content": [{"type": "text", "text": "Now running the suite:"}]},
                     {"role": "user", "content": "continue"}]}
        frames2 = _chat_sse_fetch_frames(proxy_port, body=body2)
        if frames2 is None:
            return
        up2 = json.loads(mock_servers["p"]["requests"][1]["body"])
        msgs2 = up2.get("messages")
        if not isinstance(msgs2, list) or len(msgs2) != len(body2["messages"]) + 1:
            fail("recovery upstream must carry the client's messages plus exactly one "
                 "nudge, got {} messages".format(len(msgs2) if isinstance(msgs2, list) else msgs2))
            return
        if not _assert_nudge_trailing(msgs2, "recovery (prefix branch)"):
            return
        nudges = _wait_for_event_count(trace_file, "chat_retry_nudge", 1)
        if len(nudges) != 1:
            fail("expected exactly one chat_retry_nudge after the recovery, "
                 "got {}".format(len(nudges)))
            return
        if nudges[0].get("original_request_id") != rid1:
            fail("chat_retry_nudge.original_request_id must be the errored request "
                 "{!r}, got {!r}".format(rid1, nudges[0].get("original_request_id")))
            return
        rid2 = nudges[0].get("request_id")
        # The recovery's own stall passes through: terminal frames, no error.
        types2 = _sse_types(frames2)
        if _sse_frames_with_type(frames2, "error"):
            fail("the recovery must not error (loop guard); got error frames in {}".format(types2))
            return
        missing2 = [t for t in ("message_delta", "message_stop") if t not in types2]
        if missing2:
            fail("recovery must terminal normally; missing {} ({})".format(missing2, types2))
            return
        if _sse_stop_reason(frames2) != "end_turn":
            fail("recovery must stop with end_turn, got {!r}".format(_sse_stop_reason(frames2)))
            return

        # --- Request 3: a second extension — marker consumed, no nudge, errors fresh. ---
        body3 = {"model": "sonnet", "stream": True, "tools": [tool],
                 "messages": body2["messages"] + [
                     {"role": "assistant",
                      "content": [{"type": "text", "text": "Now running the suite:"}]},
                     {"role": "user", "content": "continue again"}]}
        frames3 = _chat_sse_fetch_frames(proxy_port, body=body3)
        if frames3 is None:
            return
        unfinished3 = _wait_for_event_count(trace_file, "chat_sse_unfinished_turn", 3)
        if len(unfinished3) != 3:
            fail("expected three chat_sse_unfinished_turn events after request 3 "
                 "(its own fresh stall errors), got {}".format(len(unfinished3)))
            return
        rid3 = unfinished3[2].get("request_id")
        if not _sse_frames_with_type(frames3, "error"):
            fail("request 3 is a fresh stall with its own marker; it must error "
                 "(no match -> no passthrough)")
            return
        nudges = _trace_events_named(trace_file, "chat_retry_nudge")
        if len(nudges) != 1:
            fail("the consumed marker must not nudge request 3 (single-use); "
                 "expected 1 chat_retry_nudge, got {}".format(len(nudges)))
            return

        # --- Request 4: byte-identical re-POST of request 3 -> exact-hash branch. ---
        frames4 = _chat_sse_fetch_frames(proxy_port, body=body3)
        if frames4 is None:
            return
        nudges = _wait_for_event_count(trace_file, "chat_retry_nudge", 2)
        if len(nudges) != 2:
            fail("byte-identical re-POST must match the exact-hash branch; "
                 "expected 2 chat_retry_nudge, got {}".format(len(nudges)))
            return
        if nudges[1].get("original_request_id") != rid3:
            fail("exact-hash nudge must name request 3 {!r}, got {!r}".format(
                rid3, nudges[1].get("original_request_id")))
            return
        up4 = json.loads(mock_servers["p"]["requests"][3]["body"])
        if not _assert_nudge_trailing(up4.get("messages"), "exact-hash re-POST"):
            return
        types4 = _sse_types(frames4)
        if _sse_frames_with_type(frames4, "error"):
            fail("the matched re-POST must not error again (loop guard); "
                 "got error frames in {}".format(types4))
            return
        if _sse_stop_reason(frames4) != "end_turn" or "message_stop" not in types4:
            fail("matched re-POST must terminal normally with end_turn, got {}".format(types4))
            return
        # Request 4 also passes through the detector: it logs its own
        # unfinished-turn event (the fourth), so the no-tools request below
        # must leave the count at four.
        unfinished4 = _wait_for_event_count(trace_file, "chat_sse_unfinished_turn", 4)
        if len(unfinished4) != 4:
            fail("expected four chat_sse_unfinished_turn events after the matched "
                 "re-POST (two errors + two passthroughs), got {}".format(len(unfinished4)))
            return
        # The two unmatched upstream bodies carry no nudge at all.
        for idx in (0, 2):
            if NUDGE_MARK.encode() in mock_servers["p"]["requests"][idx]["body"]:
                fail("request {} was never matched; its upstream body must not "
                     "carry the nudge".format(idx + 1))
                return

        # --- Negative half (from the shadow test): no tools -> no detector. ---
        body_no_tools = {"model": "sonnet", "stream": True,
                         "messages": [{"role": "user", "content": "negative"}]}
        frames5 = _chat_sse_fetch_frames(proxy_port, body=body_no_tools)
        if frames5 is None:
            return
        unfinished5 = _trace_events_named(trace_file, "chat_sse_unfinished_turn")
        if len(unfinished5) != 4:
            fail("a request without tools must not fire the detector; expected 4 "
                 "events, got {}".format(len(unfinished5)))
            return
        if _sse_frames_with_type(frames5, "error"):
            fail("no-tools request must not error, got {!r}".format(
                _sse_frames_with_type(frames5, "error")))
            return
        if _sse_stop_reason(frames5) != "end_turn" or "message_stop" not in _sse_types(frames5):
            fail("no-tools request must terminal normally with end_turn, got {}".format(
                _sse_types(frames5)))
            return
        drains = _wait_for_event_count(trace_file, "chat_sse_drain", 5)
        zero_drains = [d for d in drains if d.get("tools_declared") == 0]
        if len(drains) != 5 or len(zero_drains) != 1:
            fail("expected 5 chat_sse_drain events with exactly one tools_declared 0 "
                 "(the no-tools request), got total {} zero {}".format(
                     len(drains), len(zero_drains)))
            return
        if NUDGE_MARK.encode() in mock_servers["p"]["requests"][4]["body"]:
            fail("no-tools request upstream body must not carry the nudge")
            return
        pass_("errored turn + prefix nudge + single-use + exact-hash + no-tools negative")
    finally:
        cleanup()


def test_chat_sse_retry_passthrough_no_second_error():
    """The recovery of an already-errored turn that stalls AGAIN passes
    through: no second error frame, a normal end_turn terminal, the nudge in
    its upstream body, and chat_retry_passthrough carrying the first
    request's id — the passthrough loop guard."""
    print("\n--- Test: Chat SSE Retry Passthrough No Second Error ---")
    tool = _nudge_tool()
    upstream_port = find_free_port()
    tiers = _mode_tiers()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port),
                     "key": "K", "mode": "chat"}}
    sse_body = _nudge_stall_sse_body()
    responders = {"p": lambda info: (200, "text/event-stream", sse_body)}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
        _start_mode_proxy(tiers, vendors, responders=responders)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        # Request 1: stall -> error (arms the marker).
        body1 = {"model": "sonnet", "stream": True, "tools": [tool],
                 "messages": [{"role": "user", "content": "go"}]}
        frames1 = _chat_sse_fetch_frames(proxy_port, body=body1)
        if frames1 is None:
            return
        errs1 = _sse_frames_with_type(frames1, "error")
        if len(errs1) != 1 or (errs1[0].get("error") or {}).get("type") != "api_error":
            fail("stream 1 must close with exactly one api_error, got {!r}".format(errs1))
            return
        unfinished = _wait_for_event_count(trace_file, "chat_sse_unfinished_turn", 1)
        if len(unfinished) != 1:
            fail("expected one chat_sse_unfinished_turn after stream 1, got {}".format(len(unfinished)))
            return
        rid1 = unfinished[0].get("request_id")

        # Request 2: the recovery also stalls — must pass through, not error.
        body2 = {"model": "sonnet", "stream": True, "tools": [tool],
                 "messages": body1["messages"] + [
                     {"role": "assistant",
                      "content": [{"type": "text", "text": "Now running the suite:"}]},
                     {"role": "user", "content": "continue"}]}
        frames2 = _chat_sse_fetch_frames(proxy_port, body=body2)
        if frames2 is None:
            return
        if _sse_frames_with_type(frames2, "error"):
            fail("a repeat stall with retry_original_id set must pass through without "
                 "a second error, got {!r}".format(_sse_frames_with_type(frames2, "error")))
            return
        types2 = _sse_types(frames2)
        missing2 = [t for t in ("message_delta", "message_stop") if t not in types2]
        if missing2:
            fail("passthrough must terminal normally; missing {} ({})".format(missing2, types2))
            return
        if _sse_stop_reason(frames2) != "end_turn":
            fail("passthrough must stop with end_turn, got {!r}".format(_sse_stop_reason(frames2)))
            return
        up2 = json.loads(mock_servers["p"]["requests"][1]["body"])
        if not _assert_nudge_trailing(up2.get("messages"), "passthrough request"):
            return
        nudges = _wait_for_event_count(trace_file, "chat_retry_nudge", 1)
        if len(nudges) != 1:
            fail("expected exactly one chat_retry_nudge, got {}".format(len(nudges)))
            return
        passes = _wait_for_event_count(trace_file, "chat_retry_passthrough", 1)
        if len(passes) != 1:
            fail("expected exactly one chat_retry_passthrough, got {}".format(len(passes)))
            return
        if passes[0].get("original_request_id") != rid1:
            fail("chat_retry_passthrough must carry the first request's id {!r}, "
                 "got {!r}".format(rid1, passes[0].get("original_request_id")))
            return
        # Both streams logged the detector (the second one passed through).
        unfinished2 = _wait_for_event_count(trace_file, "chat_sse_unfinished_turn", 2)
        if len(unfinished2) != 2:
            fail("the repeat stall must still log chat_sse_unfinished_turn; "
                 "expected 2, got {}".format(len(unfinished2)))
            return
        pass_("repeat stall passes through: nudge + passthrough event, no second error")
    finally:
        cleanup()


def test_chat_sse_unfinished_turn_predicate_ignores_degraded_tool():
    """(a) A tool call seen on the wire but never started (id, no name) is
    proxy-side degradation: no error frame, no chat_sse_unfinished_turn, and
    the existing degradation event still fires — the inherited
    unfinished-turn-detector-ignores-degraded-tool pin. (b) A late empty
    tool_calls [] sentinel is not a tool call (truthiness-based drain
    seen-test), so a genuine prose-only stall in a sentinel-bearing stream
    still errors."""
    print("\n--- Test: Chat SSE Unfinished Turn Predicate Ignores Degraded Tool ---")
    tool = _nudge_tool()
    upstream_port = find_free_port()
    tiers = _mode_tiers()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port),
                     "key": "K", "mode": "chat"}}
    degraded_chunks = [_cc({"role": "assistant", "content": "Running the check:"}),
                       _cc({"tool_calls": [{"index": 0, "id": "call_degraded"}]}),
                       _cc({}, finish="stop")]
    sentinel_chunks = [_cc({"role": "assistant", "content": "Now continuing:"}),
                       _cc({}, finish="stop"),
                       _cc({"tool_calls": []})]
    bodies = [_sse_stream_chunks(degraded_chunks) + b"data: [DONE]\n\n",
              _sse_stream_chunks(sentinel_chunks) + b"data: [DONE]\n\n"]
    served = {"n": 0}

    def responder(info):
        i = served["n"]
        served["n"] += 1
        return 200, "text/event-stream", bodies[min(i, len(bodies) - 1)]

    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
        _start_mode_proxy(tiers, vendors, responders={"p": responder})
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        # (a) Degraded tool (tracked, never started) blocks the predicate.
        body_a = {"model": "sonnet", "stream": True, "tools": [tool],
                  "messages": [{"role": "user", "content": "go"}]}
        frames_a = _chat_sse_fetch_frames(proxy_port, body=body_a)
        if frames_a is None:
            return
        if _sse_frames_with_type(frames_a, "error"):
            fail("a tool call seen on the wire must not error the turn, "
                 "got {!r}".format(_sse_frames_with_type(frames_a, "error")))
            return
        if _sse_stop_reason(frames_a) != "end_turn" or "message_stop" not in _sse_types(frames_a):
            fail("degraded-tool stream must terminal normally with end_turn, "
                 "got {}".format(_sse_types(frames_a)))
            return
        degraded = _wait_for_event_count(trace_file, "chat_sse_tool_degradation", 1)
        if len(degraded) != 1 or degraded[0].get("malformed_tool_count") != 1:
            fail("the tracked-but-unstarted tool must still fire the degradation "
                 "event with malformed_tool_count 1, got {!r}".format(degraded))
            return
        if _trace_events_named(trace_file, "chat_sse_unfinished_turn"):
            fail("proxy-side degradation must not count as a model omission; "
                 "chat_sse_unfinished_turn fired anyway")
            return

        # (b) An empty tool_calls sentinel is not a tool call: stall still errors.
        body_b = {"model": "sonnet", "stream": True, "tools": [tool],
                  "messages": [{"role": "user", "content": "a different conversation"}]}
        frames_b = _chat_sse_fetch_frames(proxy_port, body=body_b)
        if frames_b is None:
            return
        errs_b = _sse_frames_with_type(frames_b, "error")
        if len(errs_b) != 1 or (errs_b[0].get("error") or {}).get("type") != "api_error":
            fail("an empty tool_calls [] sentinel must not downgrade a prose-only "
                 "stall; expected one api_error, got {!r}".format(errs_b))
            return
        unfinished = _wait_for_event_count(trace_file, "chat_sse_unfinished_turn", 1)
        if len(unfinished) != 1:
            fail("expected exactly one chat_sse_unfinished_turn (the sentinel "
                 "stream), got {}".format(len(unfinished)))
            return
        if unfinished[0].get("tool_calls_seen") != 0:
            fail("the empty sentinel must not mark tool calls seen, got "
                 "tool_calls_seen {!r}".format(unfinished[0].get("tool_calls_seen")))
            return
        pass_("degraded tool blocks the predicate; empty [] sentinel does not")
    finally:
        cleanup()


def test_chat_sse_no_nudge_without_marker():
    """Request A (stalled, tools declared) is errored — the mechanism under
    test, so no assertion that it avoids the error. Request B, a different
    conversation sent afterwards with no marker match, gets no
    chat_retry_nudge event, an unchanged upstream body, and a normal
    terminal."""
    print("\n--- Test: Chat SSE No Nudge Without Marker ---")
    tool = _nudge_tool()
    upstream_port = find_free_port()
    tiers = _mode_tiers()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port),
                     "key": "K", "mode": "chat"}}
    stall = _nudge_stall_sse_body()
    normal = _sse_stream_chunks(
        [_cc({"role": "assistant", "content": "All checks passed."}),
         _cc({}, finish="stop")]) + b"data: [DONE]\n\n"
    served = {"n": 0}

    def responder(info):
        served["n"] += 1
        # First request stalls (arms its marker); later requests finish normally.
        return 200, "text/event-stream", stall if served["n"] == 1 else normal

    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
        _start_mode_proxy(tiers, vendors, responders={"p": responder})
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        body_a = {"model": "sonnet", "stream": True, "tools": [tool],
                  "messages": [{"role": "user", "content": "go"}]}
        frames_a = _chat_sse_fetch_frames(proxy_port, body=body_a)
        if frames_a is None:
            return
        if not _sse_frames_with_type(frames_a, "error"):
            fail("request A is the stall itself; it must error to arm the marker, "
                 "got types {}".format(_sse_types(frames_a)))
            return
        if not _wait_for_event_count(trace_file, "chat_sse_unfinished_turn", 1):
            fail("request A must log chat_sse_unfinished_turn")
            return

        body_b = {"model": "sonnet", "stream": True, "tools": [tool],
                  "messages": [{"role": "user", "content": "a different conversation"}]}
        frames_b = _chat_sse_fetch_frames(proxy_port, body=body_b)
        if frames_b is None:
            return
        # Normal terminal on B: its upstream never received a nudge.
        if _sse_frames_with_type(frames_b, "error"):
            fail("request B must terminal normally, got {!r}".format(
                _sse_frames_with_type(frames_b, "error")))
            return
        if _sse_stop_reason(frames_b) != "end_turn" or "message_stop" not in _sse_types(frames_b):
            fail("request B must stop with end_turn, got {}".format(_sse_types(frames_b)))
            return
        nudges = _wait_for_event_count(trace_file, "chat_retry_nudge", 1, timeout_s=1.0)
        if nudges:
            fail("an unmatched conversation must log no chat_retry_nudge, "
                 "got {}".format(len(nudges)))
            return
        up_b = json.loads(mock_servers["p"]["requests"][1]["body"])
        if up_b.get("messages") != [{"role": "user", "content": "a different conversation"}]:
            fail("unmatched upstream body must be unchanged, got {!r}".format(
                up_b.get("messages")))
            return
        pass_("no marker match -> no nudge event, unchanged upstream body")
    finally:
        cleanup()


def test_chat_retry_nudge_disabled_by_empty_env():
    """PROXY_CHAT_RETRY_NUDGE="" is the kill switch: the unfinished-turn
    stream terminals exactly as today (no error frame), the detector still
    logs (pure measurement), and no marker/nudge machinery fires."""
    print("\n--- Test: Chat Retry Nudge Disabled By Empty Env ---")
    tool = _nudge_tool()
    upstream_port = find_free_port()
    tiers = _mode_tiers()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port),
                     "key": "K", "mode": "chat"}}
    sse_body = _nudge_stall_sse_body()
    responders = {"p": lambda info: (200, "text/event-stream", sse_body)}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
        _start_mode_proxy(tiers, vendors, responders=responders,
                          extra_env={"PROXY_CHAT_RETRY_NUDGE": ""})
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        body = {"model": "sonnet", "stream": True, "tools": [tool],
                "messages": [{"role": "user", "content": "go"}]}
        frames = _chat_sse_fetch_frames(proxy_port, body=body)
        if frames is None:
            return
        if _sse_frames_with_type(frames, "error"):
            fail("with the feature disabled the stalled turn must terminal as "
                 "today, got {!r}".format(_sse_frames_with_type(frames, "error")))
            return
        types = _sse_types(frames)
        missing = [t for t in ("message_delta", "message_stop") if t not in types]
        if missing:
            fail("disabled detector must not alter the response; missing {} ({})".format(missing, types))
            return
        if _sse_stop_reason(frames) != "end_turn":
            fail("disabled detector stream must stop with end_turn, got {!r}".format(_sse_stop_reason(frames)))
            return
        events = _wait_for_event_count(trace_file, "chat_sse_unfinished_turn", 1)
        if len(events) != 1:
            fail("the detector must still log as a pure measurement; expected 1 "
                 "chat_sse_unfinished_turn, got {}".format(len(events)))
            return
        if events[0].get("rule") != "colon_after_prose" or events[0].get("tools_declared") != 1:
            fail("measurement event must keep its field shape, got {!r}".format(events[0]))
            return
        for name in ("chat_retry_nudge", "chat_retry_passthrough"):
            if _trace_events_named(trace_file, name):
                fail("{} must not fire when the feature is disabled".format(name))
                return
        pass_("empty env: detector logs, response unchanged, no marker/nudge machinery")
    finally:
        cleanup()


def test_chat_sse_nudge_reentry_walk_stall_passthrough():
    """Step 10 pin (post-implementation mega-audit finding 1/21): a nudge
    recovery whose FIRST upstream attempt is rejected with a matched
    reasoning-field complaint is re-entered by the reasoning_field rescue, and
    the SERVED attempt (the rescue's own forward) still carries the entry-time
    marker decision. Asserts the served stream carries no error frame (the
    loop guard survives re-entry — without the entry-time threading the
    re-entry re-resolves an already-consumed marker to None and closes the
    turn with a second api_error) and the served upstream body contains the
    nudge text exactly once as its trailing user message (injection re-runs
    on the inherited decision — without it the rescue serves the client body
    un-nudged). The 3-request upstream count pins that a rescue pass actually
    happened, so neither assertion can pass vacuously.
    """
    print("\n--- Test: Chat SSE Nudge Reentry Walk Stall Passthrough ---")
    tool = _nudge_tool()
    upstream_port = find_free_port()
    tiers = _mode_tiers()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port),
                     "key": "K", "mode": "chat"}}
    stall = _nudge_stall_sse_body()
    complaint = json.dumps({"error": {
        "message": "Unknown field reasoning_content is not supported"}}).encode()
    served = {"n": 0}

    def responder(info):
        i = served["n"]
        served["n"] += 1
        if i == 1:
            # Recovery's first attempt: a matched reasoning-field complaint
            # that drives the reasoning_field rescue's candidate cycle.
            return 400, "application/json", complaint
        # Request 1 and the rescue's first candidate: the colon-ending stall.
        return 200, "text/event-stream", stall

    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
        _start_mode_proxy(tiers, vendors, responders={"p": responder})
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        # --- Request 1: the stall errors and arms its marker. ---
        body1 = {"model": "sonnet", "stream": True, "tools": [tool],
                 "messages": [{"role": "user", "content": "go"}]}
        frames1 = _chat_sse_fetch_frames(proxy_port, body=body1)
        if frames1 is None:
            return
        errs1 = _sse_frames_with_type(frames1, "error")
        if len(errs1) != 1 or (errs1[0].get("error") or {}).get("type") != "api_error":
            fail("stream 1 must close with exactly one api_error, got {!r}".format(errs1))
            return
        unfinished = _wait_for_event_count(trace_file, "chat_sse_unfinished_turn", 1)
        if len(unfinished) != 1:
            fail("expected one chat_sse_unfinished_turn after stream 1, "
                 "got {}".format(len(unfinished)))
            return
        rid1 = unfinished[0].get("request_id")

        # --- Request 2: conversation-extending recovery carrying a thinking
        # block (arms the reasoning_field dispatch) -> first attempt 400,
        # walk candidate serves the client. ---
        body2 = {"model": "sonnet", "stream": True, "tools": [tool],
                 "messages": body1["messages"] + [
                     {"role": "assistant",
                      "content": [{"type": "thinking",
                                   "thinking": "I should run the suite next"},
                                  {"type": "text",
                                   "text": "Now running the suite:"}]},
                     {"role": "user", "content": "continue"}]}
        frames2 = _chat_sse_fetch_frames(proxy_port, body=body2)
        if frames2 is None:
            return

        # The walk really happened: initial attempt (400) + one candidate.
        n_up = len(mock_servers["p"]["requests"])
        if n_up != 3:
            fail("expected 3 upstream calls (stall, complaint, walk candidate), "
                 "got {} — the reasoning walk never re-entered".format(n_up))
            return

        # The SERVED stream is the walk candidate's: loop guard holds.
        types2 = _sse_types(frames2)
        errs2 = _sse_frames_with_type(frames2, "error")
        if errs2:
            fail("the walk-served recovery must pass through without a second "
                 "error (loop guard across re-entry); got {!r} ({})".format(errs2, types2))
            return
        missing2 = [t for t in ("message_delta", "message_stop") if t not in types2]
        if missing2:
            fail("walk-served recovery must terminal normally; missing {} ({})".format(
                missing2, types2))
            return
        if _sse_stop_reason(frames2) != "end_turn":
            fail("walk-served recovery must stop with end_turn, got {!r}".format(
                _sse_stop_reason(frames2)))
            return

        # The SERVED upstream body carries the nudge (injection survived re-entry).
        up_served = json.loads(mock_servers["p"]["requests"][2]["body"])
        if not _assert_nudge_trailing(up_served.get("messages"),
                                      "walk-served recovery"):
            return

        # Events: nudge(s) and exactly one passthrough, all naming request 1.
        nudges = _wait_for_event_count(trace_file, "chat_retry_nudge", 1)
        if not nudges:
            fail("expected at least one chat_retry_nudge for the recovery")
            return
        wrong = [n for n in nudges if n.get("original_request_id") != rid1]
        if wrong:
            fail("every chat_retry_nudge must name request 1 {!r}; got {!r}".format(
                rid1, [n.get("original_request_id") for n in wrong]))
            return
        passes = _wait_for_event_count(trace_file, "chat_retry_passthrough", 1)
        if len(passes) != 1 or passes[0].get("original_request_id") != rid1:
            fail("expected exactly one chat_retry_passthrough naming request 1 "
                 "{!r}, got {!r}".format(rid1, passes))
            return
        # The served stall also logs the detector (second event overall).
        unfinished2 = _wait_for_event_count(trace_file, "chat_sse_unfinished_turn", 2)
        if len(unfinished2) != 2:
            fail("the rescue-served stall must still log chat_sse_unfinished_turn; "
                 "expected 2, got {}".format(len(unfinished2)))
            return
        pass_("re-entry rescue serves the recovery: loop guard + nudge survive re-entry")
    finally:
        cleanup()


def test_chat_retry_nudge_sweep_expires_armed_only():
    """Step 11 pin (post-implementation mega-audit finding 2/14), store level:
    the production sweep runs under another request's remember/check, so an
    UNARMED entry backdated past the TTL must survive that sweep — arm still
    returns True (the TTL is anchored at arm) and the recovery still matches
    it — while an ARMED entry backdated past the TTL is expired by the same
    sweep (arm returns False, the recovery matches nothing). Pins the sweep
    ORDERING production relies on: the old rule age-expired both, so a long
    generation lost its own marker to any concurrent eligible request.
    """
    print("\n--- Test: Chat Retry Nudge Sweep Expires Armed Only ---")
    import claude_retry_proxy.server as srv
    from claude_retry_proxy import chat_nudge
    with chat_nudge._store._lock:
        chat_nudge._store._entries.clear()
    try:
        # --- Half 1: backdated UNARMED entry survives another request's sweep. ---
        msgs1 = [{"role": "user", "content": "a very long generation"}]
        body1 = json.dumps({"model": "sonnet", "stream": True,
                            "messages": msgs1}).encode()
        if not srv._retry_nudge_remember("rid-long-generation", body1,
                                         json.loads(body1)):
            fail("remember(long-generation) must store an entry")
            return
        with chat_nudge._store._lock:
            chat_nudge._store._entries["rid-long-generation"]["stored_at"] = \
                time.time() - srv.RETRY_NUDGE_TTL_SECONDS - 60
        # A second eligible request's remember runs the production sweep.
        msgs2 = [{"role": "user", "content": "an unrelated conversation"}]
        body2 = json.dumps({"model": "sonnet", "stream": True,
                            "messages": msgs2}).encode()
        if not srv._retry_nudge_remember("rid-unrelated", body2,
                                         json.loads(body2)):
            fail("remember(unrelated) must store an entry")
            return
        with chat_nudge._store._lock:
            survived = "rid-long-generation" in chat_nudge._store._entries
        if not survived:
            fail("an unarmed entry backdated past the TTL was swept by a "
                 "concurrent remember — a long generation loses its own marker")
            return
        if not srv._retry_nudge_arm("rid-long-generation"):
            fail("arm must still return True for the surviving unarmed entry")
            return
        recov1_msgs = msgs1 + [
            {"role": "assistant",
             "content": [{"type": "text", "text": "Now running the suite:"}]},
            {"role": "user", "content": "continue"}]
        recov1 = json.dumps({"model": "sonnet", "stream": True,
                             "messages": recov1_msgs}).encode()
        match1 = srv._retry_nudge_check(recov1, json.loads(recov1))
        if match1 != "rid-long-generation":
            fail("the recovery must still match the backdated-then-armed "
                 "entry, got {!r}".format(match1))
            return
        pass_("unarmed entry survives the sweep: arm True, recovery matches")

        # --- Half 2: backdated ARMED entry IS expired by the same sweep. ---
        msgsA = [{"role": "user", "content": "armed generation"}]
        bodyA = json.dumps({"model": "sonnet", "stream": True,
                            "messages": msgsA}).encode()
        if not srv._retry_nudge_remember("rid-armed", bodyA, json.loads(bodyA)):
            fail("remember(armed) must store an entry")
            return
        if not srv._retry_nudge_arm("rid-armed"):
            fail("arm(rid-armed) must succeed")
            return
        with chat_nudge._store._lock:
            chat_nudge._store._entries["rid-armed"]["stored_at"] = \
                time.time() - srv.RETRY_NUDGE_TTL_SECONDS - 60
        msgsB = [{"role": "user", "content": "another sweep trigger"}]
        bodyB = json.dumps({"model": "sonnet", "stream": True,
                            "messages": msgsB}).encode()
        srv._retry_nudge_remember("rid-sweep-trigger", bodyB,
                                  json.loads(bodyB))
        with chat_nudge._store._lock:
            armed_present = "rid-armed" in chat_nudge._store._entries
        if armed_present:
            fail("an armed entry past the TTL must be swept, but it survived")
            return
        if srv._retry_nudge_arm("rid-armed"):
            fail("arm on a swept entry must return False")
            return
        recovA_msgs = msgsA + [{"role": "user", "content": "continue"}]
        recovA = json.dumps({"model": "sonnet", "stream": True,
                             "messages": recovA_msgs}).encode()
        matchA = srv._retry_nudge_check(recovA, json.loads(recovA))
        if matchA is not None:
            fail("the swept armed entry must not match its recovery, "
                 "got {!r}".format(matchA))
            return
        pass_("armed entry past the TTL is swept: arm False, recovery matches nothing")
    finally:
        with chat_nudge._store._lock:
            chat_nudge._store._entries.clear()


def test_chat_retry_nudge_ineligible_request_does_not_consume():
    """Step 12 pin (Phase 6 review Warning 1): the marker check runs only
    inside _forward_request_impl's eligibility gate (mode == chat and tools
    declared), so an INELIGIBLE request whose body strict-extends an armed
    entry must not consume the single-use marker. Request 1 (tools, colon
    stall) errors and arms its marker; request 2 — the same conversation
    WITHOUT tools, which the pre-gate entry-time check consumed — must be
    served un-nudged with an unchanged upstream body and leave the marker
    intact; request 3, the eligible recovery, then fires chat_retry_nudge
    naming request 1 with the nudge text trailing the served upstream body.
    """
    print("\n--- Test: Chat Retry Nudge Ineligible Request Does Not Consume ---")
    tool = _nudge_tool()
    upstream_port = find_free_port()
    tiers = _mode_tiers()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port),
                     "key": "K", "mode": "chat"}}
    stall = _nudge_stall_sse_body()
    normal = _sse_stream_chunks(
        [_cc({"role": "assistant", "content": "All checks passed."}),
         _cc({}, finish="stop")]) + b"data: [DONE]\n\n"
    served = {"n": 0}

    def responder(info):
        served["n"] += 1
        # Request 1 stalls (arms its marker); later requests finish normally.
        return 200, "text/event-stream", stall if served["n"] == 1 else normal

    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
        _start_mode_proxy(tiers, vendors, responders={"p": responder})
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        # --- Request 1: tools-declaring stall -> api_error + armed marker. ---
        body1 = {"model": "sonnet", "stream": True, "tools": [tool],
                 "messages": [{"role": "user", "content": "go"}]}
        frames1 = _chat_sse_fetch_frames(proxy_port, body=body1)
        if frames1 is None:
            return
        errs1 = _sse_frames_with_type(frames1, "error")
        if len(errs1) != 1 or (errs1[0].get("error") or {}).get("type") != "api_error":
            fail("stream 1 must close with exactly one api_error, got {!r}".format(errs1))
            return
        unfinished = _wait_for_event_count(trace_file, "chat_sse_unfinished_turn", 1)
        if len(unfinished) != 1:
            fail("expected one chat_sse_unfinished_turn after stream 1, "
                 "got {}".format(len(unfinished)))
            return
        rid1 = unfinished[0].get("request_id")

        # --- Request 2: INELIGIBLE match — same conversation, no tools. ---
        # The pre-Step-12 entry-time check consumed the marker here (it ran
        # for every mode/method); the eligibility gate must leave it armed.
        body2 = {"model": "sonnet", "stream": True,
                 "messages": body1["messages"] + [
                     {"role": "assistant",
                      "content": [{"type": "text", "text": "Now running the suite:"}]},
                     {"role": "user", "content": "continue"}]}
        frames2 = _chat_sse_fetch_frames(proxy_port, body=body2)
        if frames2 is None:
            return
        if _sse_frames_with_type(frames2, "error"):
            fail("the ineligible request must terminal normally, got {!r}".format(
                _sse_frames_with_type(frames2, "error")))
            return
        if _sse_stop_reason(frames2) != "end_turn" or "message_stop" not in _sse_types(frames2):
            fail("the ineligible request must stop with end_turn, got {}".format(
                _sse_types(frames2)))
            return
        nudges = _wait_for_event_count(trace_file, "chat_retry_nudge", 1, timeout_s=1.0)
        if nudges:
            fail("an ineligible request must never be nudged, got {}".format(len(nudges)))
            return
        up2 = json.loads(mock_servers["p"]["requests"][1]["body"])
        msgs2 = up2.get("messages")
        if not isinstance(msgs2, list) or len(msgs2) != len(body2["messages"]):
            fail("ineligible upstream must carry the client's messages unchanged, "
                 "got {!r}".format(msgs2))
            return
        if NUDGE_MARK.encode() in mock_servers["p"]["requests"][1]["body"]:
            fail("ineligible request must not receive the nudge (no injection "
                 "outside the eligibility gate)")
            return

        # --- Request 3: the eligible recovery — the marker must still match. ---
        body3 = {"model": "sonnet", "stream": True, "tools": [tool],
                 "messages": body2["messages"]}
        frames3 = _chat_sse_fetch_frames(proxy_port, body=body3)
        if frames3 is None:
            return
        nudges = _wait_for_event_count(trace_file, "chat_retry_nudge", 1)
        if len(nudges) != 1:
            fail("the ineligible request must not have consumed the marker: "
                 "expected 1 chat_retry_nudge after the eligible recovery, "
                 "got {}".format(len(nudges)))
            return
        if nudges[0].get("original_request_id") != rid1:
            fail("chat_retry_nudge.original_request_id must be the errored "
                 "request {!r}, got {!r}".format(rid1, nudges[0].get("original_request_id")))
            return
        up3 = json.loads(mock_servers["p"]["requests"][2]["body"])
        if not _assert_nudge_trailing(up3.get("messages"), "eligible recovery"):
            return
        if _sse_frames_with_type(frames3, "error"):
            fail("the eligible recovery must not error (loop guard); got {!r}".format(
                _sse_frames_with_type(frames3, "error")))
            return
        if _sse_stop_reason(frames3) != "end_turn" or "message_stop" not in _sse_types(frames3):
            fail("the eligible recovery must stop with end_turn, got {}".format(
                _sse_types(frames3)))
            return
        pass_("ineligible match leaves the marker armed: recovery still nudges")
    finally:
        cleanup()


def test_chat_retry_nudge_large_conversation_is_nudgeable():
    """A conversation whose serialized messages exceed the old 1 MiB cap must
    still be remembered, armed, and matched. Regression for the size cap that
    silently killed the feature on every real chat-mode body."""
    print("\n--- Test: Chat Retry Nudge — Large Conversation Is Nudgeable ---")
    import claude_retry_proxy.server as srv
    from claude_retry_proxy import chat_nudge
    with chat_nudge._store._lock:
        chat_nudge._store._entries.clear()
    messages = [
        {"role": "user", "content": "x" * 1_500_000},
        {"role": "assistant", "content": "Now running the suite:"},
    ]
    body = json.dumps({"messages": messages}).encode("utf-8")
    size = len(_nudge_canonical(messages).encode("utf-8"))
    if size <= 1024 * 1024:
        fail("fixture must exceed the old 1 MiB cap, got {} bytes".format(size))
        return
    if not srv._retry_nudge_remember("rid-big", body, json.loads(body)):
        fail("a >1 MiB conversation must be remembered (the cap is removed)")
        return
    if srv._retry_nudge_messages_bytes("rid-big") != size:
        fail("the stored messages_bytes must equal the serialized prefix size")
        return
    if not srv._retry_nudge_arm("rid-big"):
        fail("remembered entry must arm")
        return
    extended = messages + [{"role": "user", "content": "[proxy nudge]"}]
    ebody = json.dumps({"messages": extended}).encode("utf-8")
    if srv._retry_nudge_check(ebody, json.loads(ebody)) != "rid-big":
        fail("the strict-extension recovery of a large conversation must match")
        return
    pass_(">1 MiB conversation remembered, armed, and matched")


def test_chat_retry_nudge_prefix_digest_matches_strict_extension():
    """The digest Pass 2 matches a strict extension and rejects the two
    near-misses: a same-length different-content body and a shorter body."""
    print("\n--- Test: Chat Retry Nudge — Prefix Digest Pass 2 ---")
    import claude_retry_proxy.server as srv
    from claude_retry_proxy import chat_nudge
    with chat_nudge._store._lock:
        chat_nudge._store._entries.clear()
    messages = [{"role": "user", "content": "alpha"},
                {"role": "assistant", "content": "beta"}]
    body = json.dumps({"messages": messages}).encode("utf-8")
    if not srv._retry_nudge_remember("rid-digest", body, json.loads(body)):
        fail("remember must store the entry")
        return
    if not srv._retry_nudge_arm("rid-digest"):
        fail("entry must arm")
        return
    # (a) same length, different content -> no match, entry survives
    same_len = [{"role": "user", "content": "alpha"},
                {"role": "assistant", "content": "GAMMA"}]
    sbody = json.dumps({"messages": same_len}).encode("utf-8")
    if srv._retry_nudge_check(sbody, json.loads(sbody)) is not None:
        fail("a same-length non-identical body must not match the prefix digest")
        return
    with chat_nudge._store._lock:
        if "rid-digest" not in chat_nudge._store._entries:
            fail("the non-match must not consume the marker")
            return
    # (b) shorter -> no match
    short = messages[:1]
    hbody = json.dumps({"messages": short}).encode("utf-8")
    if srv._retry_nudge_check(hbody, json.loads(hbody)) is not None:
        fail("a shorter body must not match the strict-extension prefix")
        return
    # (c) strict extension -> match and consume
    extended = messages + [{"role": "user", "content": "continue"}]
    ebody = json.dumps({"messages": extended}).encode("utf-8")
    if srv._retry_nudge_check(ebody, json.loads(ebody)) != "rid-digest":
        fail("a strict extension must match")
        return
    with chat_nudge._store._lock:
        if "rid-digest" in chat_nudge._store._entries:
            fail("a match must consume the single-use marker")
            return
    pass_("prefix digest: extension matches; same-length and shorter rejected")


def test_chat_retry_nudge_evicts_at_sixty_four_entries():
    """The entry cap is 64: storing a 65th distinct entry evicts the oldest
    unarmed one and the store never exceeds the cap."""
    print("\n--- Test: Chat Retry Nudge — Eviction At 64 Entries ---")
    import claude_retry_proxy.server as srv
    from claude_retry_proxy import chat_nudge
    with chat_nudge._store._lock:
        chat_nudge._store._entries.clear()
    for i in range(65):
        messages = [{"role": "user", "content": "conv-%d" % i}]
        body = json.dumps({"messages": messages}).encode("utf-8")
        if not srv._retry_nudge_remember("rid-%d" % i, body, json.loads(body)):
            fail("remember(rid-%d) must store" % i)
            return
    with chat_nudge._store._lock:
        n = len(chat_nudge._store._entries)
        oldest = "rid-0" in chat_nudge._store._entries
        newest = "rid-64" in chat_nudge._store._entries
    if n != 64:
        fail("store must hold exactly 64 entries, got {}".format(n))
        return
    if oldest:
        fail("the oldest unarmed entry must be the eviction victim")
        return
    if not newest:
        fail("the newest entry must survive")
        return
    pass_("store capped at 64; oldest unarmed evicted, newest kept")


ALL_TESTS = [
    ("chat-sse-unfinished-turn-errors-and-nudges-retry", test_chat_sse_unfinished_turn_errors_and_nudges_retry),
    ("chat-sse-retry-passthrough-no-second-error", test_chat_sse_retry_passthrough_no_second_error),
    ("chat-sse-unfinished-turn-predicate-ignores-degraded-tool", test_chat_sse_unfinished_turn_predicate_ignores_degraded_tool),
    ("chat-sse-no-nudge-without-marker", test_chat_sse_no_nudge_without_marker),
    ("chat-retry-nudge-disabled-by-empty-env", test_chat_retry_nudge_disabled_by_empty_env),
    ("chat-sse-nudge-reentry-walk-stall-passthrough", test_chat_sse_nudge_reentry_walk_stall_passthrough),
    ("chat-retry-nudge-sweep-expires-armed-only", test_chat_retry_nudge_sweep_expires_armed_only),
    ("chat-retry-nudge-ineligible-request-does-not-consume", test_chat_retry_nudge_ineligible_request_does_not_consume),
    ("chat-retry-nudge-large-conversation-is-nudgeable", test_chat_retry_nudge_large_conversation_is_nudgeable),
    ("chat-retry-nudge-prefix-digest-matches-strict-extension", test_chat_retry_nudge_prefix_digest_matches_strict_extension),
    ("chat-retry-nudge-evicts-at-sixty-four-entries", test_chat_retry_nudge_evicts_at_sixty_four_entries),
]


if __name__ == "__main__":
    run_cli(ALL_TESTS, "claude-retry-proxy tests: test_chat_nudge")
