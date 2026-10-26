"""Payload-nesting policy tests: the depth scanner and the guards it backs.

Plan 2026-10-25-json-nesting-limit, Step 7 (scanner/limit and guard units),
Step 15 (the degraded diagnostic's bounded walk, its three named degrades,
and the parent-link path reconstruction) and Step 18 (the bytes fast path,
the str/bytes/bytearray differential, and the single-sourced trace event).
Families:

  - Scanner/limit units for ``claude_retry_proxy.nesting`` — acceptance at
    exactly the limit on both the count fast path and the slow state machine,
    rejection past it (depth, crossing offset, ``$``-rooted path), totality on
    every input shape, and the bounded diagnostic fallbacks (repair cap, node
    budget, failed repair) with their retained-memory ceiling.
  - Fast path and type contract: an accepted bytes-like payload is decided by
    two byte counts and never decoded; ``str``, ``bytes`` and ``bytearray``
    agree on every fixture; ``memoryview`` still passes (the parser rejects
    one, so the scanner does too).
  - Degrade units: each ``degrade`` reason is reported on the violation and
    distinguishable in the 400 message; a long-key fan under the budget still
    resolves its path through the parent-link reconstruction.
  - Event units: one pure builder produces every ``nesting_limit_exceeded``
    event, so the fixed field set — ``degrade`` included — is identical at
    every emission point, and ``NESTING_SITES`` is the single vocabulary that
    the documentation's list must match.
  - Deterministic guard units: the four parse/encode fences that must return
    their documented fallback rather than raise, proven with monkeypatched
    ``json.dumps`` / ``json.loads`` so they hold on any interpreter — they no
    longer depend on a measured recursion ceiling.

Every depth is derived from ``MAX_JSON_NESTING_DEPTH``; no literal 500.

Part of the claude-retry-proxy suite; runnable standalone.
"""

import json
import os
import re
import tracemalloc
import unittest.mock

from _harness import fail, pass_, run_cli

from claude_retry_proxy.nesting import (MAX_JSON_NESTING_DEPTH,
                                        NESTING_SITES,
                                        NestingViolation,
                                        _REPAIR_MAX_NODES,
                                        _REPAIR_MAX_OFFSET,
                                        check_payload_nesting,
                                        nesting_event)

LIMIT = MAX_JSON_NESTING_DEPTH


def _opens(text):
    """Total open-bracket count — the scanner's fast-path predicate."""
    return text.count("[") + text.count("{")


def test_nesting_scanner_accepts_at_limit():
    """A body at exactly the limit is accepted on both scanner paths.

    The count fast path decides when the total open-bracket count is <= the
    limit — a chain of limit-1 arrays under the root reaches exactly the
    limit with exactly `limit` opens. The slow state machine must also accept
    the same depth: two sibling chains under the root push the total opens
    past the limit (so the fast path cannot decide) while the maximum depth
    is still exactly the limit.
    """
    print("\n--- Test: Nesting Scanner Accepts At The Limit ---")
    fast = '{"x":' + "[" * (LIMIT - 1) + "]" * (LIMIT - 1) + "}"
    if _opens(fast) > LIMIT:
        fail("fast-path fixture has {} opens, over the limit {} — "
             "it would take the slow path".format(_opens(fast), LIMIT))
        return
    got = check_payload_nesting(fast)
    if got is not None:
        fail("fast path: body at exactly the limit rejected: {!r}".format(got))
        return
    pass_("fast path: {} opens, max depth {} -> accepted".format(_opens(fast), LIMIT))

    slow = ('{"a":' + "[" * (LIMIT - 1) + "]" * (LIMIT - 1)
            + ',"b":' + "[" * (LIMIT - 1) + "]" * (LIMIT - 1) + "}")
    if _opens(slow) <= LIMIT:
        fail("slow-path fixture has only {} opens — the fast path would "
             "decide it".format(_opens(slow)))
        return
    got = check_payload_nesting(slow)
    if got is not None:
        fail("slow path: two sibling chains at max depth {} rejected: "
             "{!r}".format(LIMIT, got))
        return
    pass_("slow path: {} opens, max depth {} -> accepted".format(_opens(slow), LIMIT))


def test_nesting_scanner_rejects_past_limit():
    """A body at limit+1 is rejected with its crossing offset and depth.

    The offset is the character index of the bracket that crossed the limit
    (the limit-th nested opener); the depth is limit+1 — a lower bound on the
    body's true depth, since the scan early-exits at the first crossing.
    """
    print("\n--- Test: Nesting Scanner Rejects Past The Limit ---")
    prefix = '{"x":'
    body = prefix + "[" * LIMIT + "]" * LIMIT + "}"
    got = check_payload_nesting(body)
    if not isinstance(got, NestingViolation):
        fail("body at limit+1 was not rejected: {!r}".format(got))
        return
    expected_offset = len(prefix) + (LIMIT - 1)
    if got.depth != LIMIT + 1:
        fail("expected depth {!r}, got {!r}".format(LIMIT + 1, got.depth))
        return
    if got.offset != expected_offset:
        fail("expected crossing offset {}, got {}".format(expected_offset, got.offset))
        return
    if not (isinstance(got.path, str) and got.path.startswith("$.x[0]")):
        fail("expected a $-rooted path naming the chain, got {!r}".format(got.path))
        return
    pass_("limit+1: depth {}, crossing offset {}, path {!r}".format(
        got.depth, got.offset, got.path[:40] + "..."))

    far = "[" * (LIMIT * 10)
    got = check_payload_nesting(far)
    if not isinstance(got, NestingViolation):
        fail("far-past-limit body was not rejected: {!r}".format(got))
        return
    if got.depth != LIMIT + 1 or got.offset != LIMIT:
        fail("far-past-limit: expected depth {} offset {}, got {!r}".format(
            LIMIT + 1, LIMIT, got))
        return
    pass_("far past the limit: still the FIRST crossing (depth {}, offset {})".format(
        got.depth, got.offset))


def test_nesting_scanner_str_bytes_agree():
    """str and bytes inputs agree on every field for an ASCII payload."""
    print("\n--- Test: Nesting Scanner str/bytes Agreement ---")
    text = '{"x":' + "[" * LIMIT + "]" * LIMIT + "}"
    as_str = check_payload_nesting(text)
    as_bytes = check_payload_nesting(text.encode("ascii"))
    if as_str != as_bytes:
        fail("str and bytes disagree: {!r} vs {!r}".format(as_str, as_bytes))
        return
    if as_str is None:
        fail("the agreement fixture was accepted by both — nothing to compare")
        return
    pass_("identical violation for str and bytes (offset {})".format(as_str.offset))


def test_nesting_scanner_non_text_inputs():
    """Only the parser's types are scanned; every other type passes as non-JSON.

    The scanner covers exactly what ``json.loads`` parses — ``str``, ``bytes``
    and ``bytearray`` — so every other type is treated as non-JSON and passes
    without raising. ``bytearray`` deliberately does NOT belong here since
    Step 16 (it used to pass unscanned; it is now scanned as the equivalent
    ``bytes``, which ``test_nesting_scanner_type_differential`` pins).
    ``memoryview`` does belong: it stays unscanned because the parser rejects
    one too, so the scanner's contract matches the parser's rather than
    exceeding it.
    """
    print("\n--- Test: Nesting Scanner Non-Text Inputs ---")
    for label, value in (("None", None),
                         ("int", 500),
                         ("float", 3.5),
                         ("dict", {"x": "[" * (LIMIT * 2)}),
                         ("list", ["[" * (LIMIT * 2)]),
                         ("memoryview", memoryview(b"[" * (LIMIT * 2))),
                         ("object", object())):
        try:
            got = check_payload_nesting(value)
        except Exception as e:
            fail("{} input raised {!r} instead of returning None".format(label, e))
            return
        if got is not None:
            fail("{} input returned {!r}, expected None".format(label, got))
            return
    pass_("non-str/bytes/bytearray inputs all return None without raising")


def test_nesting_scanner_type_differential():
    """str, bytes and bytearray agree on every fixture; memoryview passes.

    Step 18's differential pins Step 16's type contract:

      - ``str``, ``bytes`` and ``bytearray`` yield IDENTICAL verdicts (equal
        offsets on ASCII fixtures) for deep, shallow, malformed, wide and
        empty payloads — no call shape can diverge;
      - an under-limit ``bytearray`` is accepted, as its ``bytes`` twin is;
      - ``memoryview`` still passes unscanned, even when deep, because
        ``json.loads`` rejects a memoryview and the scanner mirrors the parser.

    ``bytearray``'s verdict changed INTENTIONALLY in Step 16: it returned
    ``None`` unscanned before (a latent hole — the parser would have parsed
    what the scanner never saw) and is now scanned exactly as ``bytes`` is.
    """
    print("\n--- Test: Nesting Scanner Type Differential ---")
    fixtures = (
        ("deep", '{"x":' + "[" * LIMIT + "]" * LIMIT + "}"),
        ("shallow", '{"x":[1,2,3]}'),
        ("malformed", '{"x":' + "[" * (LIMIT + 1)),
        ("wide", "[" + ",".join(['{"a":1}'] * 3000) + "]"),
        ("empty", ""),
    )
    for label, text in fixtures:
        as_str = check_payload_nesting(text)
        as_bytes = check_payload_nesting(text.encode("ascii"))
        as_bytearray = check_payload_nesting(bytearray(text.encode("ascii")))
        if not (as_str == as_bytes == as_bytearray):
            fail("{}: str/bytes/bytearray disagree: {!r} / {!r} / {!r}".format(
                label, as_str, as_bytes, as_bytearray))
            return
        pass_("{}: str == bytes == bytearray ({})".format(
            label, "accepted" if as_str is None else
            "rejected at offset {}".format(as_str.offset)))

    if check_payload_nesting(bytearray(b'{"x":[1,2,3]}')) is not None:
        fail("an under-limit bytearray was rejected")
        return
    pass_("under-limit bytearray accepted (scanned as bytes)")

    deep_bytes = ('{"x":' + "[" * LIMIT + "]" * LIMIT + "}").encode("ascii")
    if check_payload_nesting(memoryview(deep_bytes)) is not None:
        fail("a memoryview was scanned — the parser rejects one, so the "
             "scanner's contract should not exceed the parser's")
        return
    pass_("deep memoryview passes unscanned (matches the parser)")


def test_nesting_scanner_bytes_fast_path_skips_decode():
    """An accepted bytes-like payload is decided by two byte counts, no decode.

    Step 16 moved the count fast path ahead of the decode. The proof patches
    ``nesting._as_text`` to raise: an under-limit ``bytes`` or ``bytearray``
    payload must still return ``None`` (the decoder is never reached), and an
    over-limit payload must reach it (the patch fires). The proof is scoped to
    bytes-like input on purpose — for ``str`` the helper is a trivial identity
    return, so there is no wasted decode to prove away.
    """
    print("\n--- Test: Nesting Scanner Bytes Fast Path Skips Decode ---")

    def reached(raw):
        raise AssertionError(
            "the decoder was reached for a payload the byte-count fast path "
            "should have accepted ({})".format(type(raw).__name__))

    with unittest.mock.patch("claude_retry_proxy.nesting._as_text",
                             side_effect=reached):
        for label, value in (("bytes", b'{"x":[1,2,3]}'),
                             ("bytearray", bytearray(b'{"x":[1,2,3]}'))):
            try:
                got = check_payload_nesting(value)
            except AssertionError as e:
                fail("{}: {}".format(label, e))
                return
            if got is not None:
                fail("{}: under-limit payload returned {!r}, expected None".format(
                    label, got))
                return
            pass_("{}: under-limit payload accepted with the decoder patched".format(
                label))

    with unittest.mock.patch("claude_retry_proxy.nesting._as_text",
                             side_effect=reached):
        try:
            check_payload_nesting(b"[" * (LIMIT + 1))
        except AssertionError:
            pass_("over-limit bytes payload DOES reach the decoder")
        else:
            fail("an over-limit bytes payload never reached the decoder — the "
                 "byte-count fast path is deciding payloads it must not")
            return


def test_nesting_scanner_ignores_brackets_in_strings():
    """Brackets inside JSON strings never count toward the depth.

    The fixture carries far more open brackets than the limit *inside* string
    literals (so the count fast path cannot decide), plus a real chain that
    reaches exactly the limit — an accept proves the state machine skipped the
    string content. The negative control then closes the string and opens a
    real chain past the limit, which must still be rejected — an escaped quote
    must not leave the scanner stuck inside a string.
    """
    print("\n--- Test: Nesting Scanner Ignores Brackets In Strings ---")
    chain = "[" * (LIMIT - 1) + "]" * (LIMIT - 1)
    accept = '{"a":"' + "[" * (LIMIT * 2) + '","b":' + chain + "}"
    if _opens(accept) <= LIMIT:
        fail("string fixture has only {} opens — the fast path would decide it".format(
            _opens(accept)))
        return
    got = check_payload_nesting(accept)
    if got is not None:
        fail("brackets inside a string were counted: {!r}".format(got))
        return
    pass_("brackets inside a string ignored; real chain at the limit accepted")

    escaped = '{"a":"q\\"' + "[" * (LIMIT * 2) + '","b":' + chain + "}"
    got = check_payload_nesting(escaped)
    if got is not None:
        fail("an escaped quote inside a string changed the verdict: {!r}".format(got))
        return
    pass_("escaped quote inside the string leaves its content ignored")

    reject = '{"a":"x","b":' + "[" * LIMIT + "]" * LIMIT + "}"
    got = check_payload_nesting(reject)
    if not isinstance(got, NestingViolation) or got.depth != LIMIT + 1:
        fail("a real chain at limit+1 after a closed string was not rejected: "
             "{!r}".format(got))
        return
    pass_("state machine resumes after the string closes; limit+1 rejected")


def test_nesting_scanner_stray_closes_ignored():
    """A close at depth 0 is ignored: the stack never underflows.

    The leading stray closes must neither raise nor mask a genuine violation
    behind them, and on their own they never manufacture one.
    """
    print("\n--- Test: Nesting Scanner Stray Closes ---")
    body = "]" * 4 + "[" * (LIMIT + 1) + "]" * (LIMIT + 1)
    try:
        got = check_payload_nesting(body)
    except Exception as e:
        fail("leading stray closes raised {!r}".format(e))
        return
    if not isinstance(got, NestingViolation):
        fail("a chain past the limit behind stray closes was accepted")
        return
    if got.offset != 4 + LIMIT or got.depth != LIMIT + 1:
        fail("expected offset {} depth {}, got {!r}".format(4 + LIMIT, LIMIT + 1, got))
        return
    pass_("stray closes ignored; the crossing behind them still rejects")

    got = check_payload_nesting("]" * 4 + "[" * LIMIT + "]" * LIMIT)
    if got is not None:
        fail("stray closes plus a chain at the limit rejected: {!r}".format(got))
        return
    pass_("stray closes plus a chain at the limit accepted")


def test_nesting_scanner_mismatched_pairs_total():
    """Mismatched container pairs never raise: the repair simply fails.

    A close pops the type stack blindly, so a mismatched pair either never
    reaches the limit (benign) or produces a repair that is not valid JSON
    (offset-only diagnostic).
    """
    print("\n--- Test: Nesting Scanner Mismatched Pairs ---")
    try:
        got = check_payload_nesting(b"[}" * 300)
    except Exception as e:
        fail("mismatched pairs raised {!r}".format(e))
        return
    if got is not None:
        fail("a mismatched pair pattern that never nests deeply was rejected: "
             "{!r}".format(got))
        return
    pass_("'[}' repeated: total, accepted (depth never exceeds 1)")

    try:
        got = check_payload_nesting(b"{" * (LIMIT + 100) + b"]" * (LIMIT + 100))
    except Exception as e:
        fail("mismatched deep pairs raised {!r}".format(e))
        return
    if not isinstance(got, NestingViolation):
        fail("mismatched deep pairs past the limit were accepted")
        return
    if got.depth != LIMIT + 1 or got.path is not None:
        fail("expected depth {} and an offset-only diagnostic (path None), "
             "got {!r}".format(LIMIT + 1, got))
        return
    pass_("mismatched deep pairs: rejects with offset {}, path None".format(got.offset))


def test_nesting_scanner_wide_body():
    """A wide body (3,000 sibling objects) passes — depth, not size, is bounded."""
    print("\n--- Test: Nesting Scanner Wide Body ---")
    body = b"[" + b",".join([b'{"a":1}'] * 3000) + b"]"
    got = check_payload_nesting(body)
    if got is not None:
        fail("a 3,000-object wide body was rejected: {!r}".format(got))
        return
    pass_("{} opens across 3,000 siblings, max depth 2 -> accepted".format(
        body.count(b"[") + body.count(b"{")))


def test_nesting_scanner_degraded_path_diagnostic():
    """A malformed crossing prefix still rejects, with the offset and no path.

    The repair parse fails on the malformed prefix, so the diagnostic degrades
    to offset-only — the offset is always reported.
    """
    print("\n--- Test: Nesting Scanner Degraded Path Diagnostic ---")
    prefix = b'{"a" '
    body = prefix + b"[" * (LIMIT + 100)
    got = check_payload_nesting(body)
    if not isinstance(got, NestingViolation):
        fail("a deep chain after a malformed prefix was accepted")
        return
    if got.offset != len(prefix) + (LIMIT - 1):
        fail("expected crossing offset {}, got {}".format(
            len(prefix) + LIMIT - 1, got.offset))
        return
    if got.path is not None:
        fail("expected path None for an unrepaired prefix, got {!r}".format(got.path))
        return
    pass_("malformed prefix: offset {} reported, path None".format(got.offset))


def test_nesting_scanner_repair_cap():
    """A crossing beyond the 1 MiB cap degrades to an offset-only diagnostic."""
    print("\n--- Test: Nesting Scanner Repair Cap ---")
    pad = b"x" * (1024 * 1024 + 64)
    head = b'{"pad":"'
    middle = b'","x":'
    body = head + pad + middle + b"[" * (LIMIT + 1)
    got = check_payload_nesting(body)
    if not isinstance(got, NestingViolation):
        fail("a late-crossing body was accepted")
        return
    if got.offset != len(head) + len(pad) + len(middle) + (LIMIT - 1):
        fail("expected crossing offset {}, got {}".format(
            len(head) + len(pad) + len(middle) + LIMIT - 1, got.offset))
        return
    if got.offset <= 1024 * 1024:
        fail("fixture does not cross past the 1 MiB repair cap (offset {})".format(
            got.offset))
        return
    if got.path is not None:
        fail("expected path None past the repair cap, got {!r}".format(got.path))
        return
    pass_("crossing at offset {}: repair skipped, path None".format(got.offset))


def _longkey_fan_body(fan, key_len=200):
    """A scalar fan at depth behind long-key dict/array pairs.

    ``LIMIT`` opens come from ``LIMIT // 2`` ``{"<key>":[`` units, the
    innermost array holds ``fan`` scalars, and the trailing ``[`` is the
    crossing bracket. Every visited node's path carries all the ancestor keys,
    which is the amplification shape (bytes of body x path length) the
    record-based repair walk exists to bound: nodes x path length, not just
    nodes.
    """
    key = "k" * key_len
    unit = '{"%s":[' % key
    half = LIMIT // 2
    return unit * half + "1," * fan + "[" + "]" + "]}" * half


def test_nesting_scanner_budget_degrade():
    """A long-key fan past the node budget degrades to the offset-only form.

    The body is VALID JSON (json.loads accepts it) whose crossing sits well
    below the 1 MiB repair cap, so the only reason no path is reported is the
    walk's node budget. The violation says so on its own ``degrade`` field
    ("budget"), and the message names the budget rather than claiming the body
    may be malformed — the class of inaccuracy the 2026-10-26 issues
    ``budget-skip-message-inaccurate`` / ``cap-skip-message-inaccurate`` fixed.
    """
    print("\n--- Test: Nesting Scanner Budget Degrade ---")
    from claude_retry_proxy.server import _nesting_limit_message

    body = _longkey_fan_body(_REPAIR_MAX_NODES + LIMIT)
    try:
        json.loads(body)
    except Exception as e:
        fail("the budget fixture must be valid JSON, got {!r}".format(e))
        return
    got = check_payload_nesting(body)
    if not isinstance(got, NestingViolation):
        fail("a long-key fan past the node budget was accepted")
        return
    if got.degrade != "budget":
        fail("expected degrade 'budget', got {!r} (path {!r})".format(
            got.degrade, got.path))
        return
    if got.path is not None:
        fail("a budget skip must not report a path, got {!r}".format(got.path))
        return
    if got.offset > _REPAIR_MAX_OFFSET:
        fail("fixture crossed past the repair cap (offset {} > {}) — it would "
             "test the cap degrade, not the budget".format(
                 got.offset, _REPAIR_MAX_OFFSET))
        return
    message = _nesting_limit_message(got)
    if "node scan budget" not in message or str(_REPAIR_MAX_NODES) not in message:
        fail("the budget tail must name the node scan budget ({}), got "
             "{!r}".format(_REPAIR_MAX_NODES, message))
        return
    if "may not be valid JSON" in message:
        fail("a valid-JSON body told its body may not be valid JSON: {!r}".format(
            message))
        return
    pass_("valid {} KiB fan past the {} record budget -> degrade 'budget', "
          "offset {}, no path".format(len(body) // 1024, _REPAIR_MAX_NODES,
                                      got.offset))


def test_nesting_scanner_path_reconstruction():
    """A fan UNDER the budget still resolves the correct path.

    The regression pin for Step 14's parent-link reconstruction (the walk now
    stores small records and renders the winning path once, instead of
    concatenating a path per node):

      - at the real limit, the 54.4 KiB long-key fan resolves a path equal to
        an independently reconstructed component walk — key rendering, list
        indices, ordering and the crossing leaf's index — in the documented
        140 + ellipsis + 40 truncated form;
      - at a small limit derived from MAX_JSON_NESTING_DEPTH the path is short
        enough to compare EXACTLY, so the reconstruction cannot pass on a
        matching head and tail alone.
    """
    print("\n--- Test: Nesting Scanner Path Reconstruction ---")

    key = "k" * 200
    fan = 2000
    body = _longkey_fan_body(fan)
    got = check_payload_nesting(body)
    if not isinstance(got, NestingViolation):
        fail("the long-key fan under the budget was rejected without a violation")
        return
    if got.degrade is not None:
        fail("a fan under the budget must not degrade, got {!r} (path {!r})".format(
            got.degrade, got.path))
        return
    # Components: HALF-1 dict/array pairs rendered as ".k[0]", the innermost
    # dict's key, then the crossing bracket — the repaired empty array that
    # follows the fan's own scalars 0..fan-1.
    expected = ("$" + ("." + key + "[0]") * (LIMIT // 2 - 1)
                + "." + key + "[{}]".format(fan))
    truncated = expected[:140] + "…" + expected[-40:]
    if got.path != truncated:
        fail("reconstructed path does not match the component walk: got "
             "{!r}...{!r}, expected ...{!r}".format(
                 (got.path or "")[:60], (got.path or "")[-50:], truncated[-50:]))
        return
    if len(got.path) != 140 + 1 + 40:
        fail("expected the 181-char truncated form, got {} chars".format(
            len(got.path)))
        return
    pass_("under-budget fan: path matches the component walk ({} chars, "
          "truncated)".format(len(got.path)))

    small = max(4, (LIMIT // 100) * 2)
    key8 = "k" * 8
    unit = '{"%s":[' % key8
    pairs = small // 2
    small_body = unit * pairs + "1," + "[" + "]" + "]}" * pairs
    got = check_payload_nesting(small_body, limit=small)
    if not isinstance(got, NestingViolation):
        fail("limit={}: the fixture was accepted".format(small))
        return
    exact = "$" + ("." + key8 + "[0]") * (pairs - 1) + "." + key8 + "[1]"
    if got.path != exact:
        fail("limit={}: exact reconstruction mismatch: got {!r}, expected "
             "{!r}".format(small, got.path, exact))
        return
    pass_("limit={}: exact path {!r} (dict keys, list indices, order)".format(
        small, exact))


def test_nesting_limit_message_three_tails():
    """The 400 message names WHICH locator degrade fired, end to end.

    ``path is None`` has three causes and each gets its own tail: "cap" (the
    crossing is past the 1 MiB repair bound), "budget" (the walk exhausted its
    record budget) and "parse" (the repaired prefix could not be parsed —
    the only case where the body itself may be malformed). The three messages
    must be distinct, so a valid body can never be told it is not valid JSON.
    """
    print("\n--- Test: Nesting Limit Message Three Tails ---")
    from claude_retry_proxy.server import _nesting_limit_message

    cap_body = ('{"pad":"' + "x" * (_REPAIR_MAX_OFFSET + 64)
                + '","x":' + "[" * (LIMIT + 1))
    budget_body = _longkey_fan_body(_REPAIR_MAX_NODES + LIMIT)
    parse_body = '{"a" ' + "[" * (LIMIT + 100)

    messages = {}
    for label, body, want_degrade in (("cap", cap_body, "cap"),
                                      ("budget", budget_body, "budget"),
                                      ("parse", parse_body, "parse")):
        got = check_payload_nesting(body)
        if not isinstance(got, NestingViolation):
            fail("{}: fixture was accepted".format(label))
            return
        if got.degrade != want_degrade or got.path is not None:
            fail("{}: expected degrade {!r} with path None, got {!r}/{!r}".format(
                label, want_degrade, got.degrade, got.path))
            return
        message = _nesting_limit_message(got)
        if "offset {}".format(got.offset) not in message:
            fail("{}: message does not carry the offset: {!r}".format(label, message))
            return
        if "limit of {} levels".format(LIMIT) not in message:
            fail("{}: message does not name the limit: {!r}".format(label, message))
            return
        messages[label] = message
        pass_("{}: degrade {!r}, offset in the message".format(label, got.degrade))

    if "repair cap" not in messages["cap"] or \
            str(_REPAIR_MAX_OFFSET // (1024 * 1024)) + " MiB" not in messages["cap"]:
        fail("cap tail does not name the repair cap: {!r}".format(messages["cap"]))
        return
    if "node scan budget" not in messages["budget"] or \
            str(_REPAIR_MAX_NODES) not in messages["budget"]:
        fail("budget tail does not name the scan budget: {!r}".format(
            messages["budget"]))
        return
    if "may not be valid JSON" not in messages["parse"]:
        fail("parse tail does not carry the may-not-be-valid-JSON wording: "
             "{!r}".format(messages["parse"]))
        return
    for label in ("cap", "budget"):
        if "may not be valid JSON" in messages[label]:
            fail("{}: a locator skip must not claim the body may be invalid: "
                 "{!r}".format(label, messages[label]))
            return
    if len(set(messages.values())) != 3:
        fail("the three degrades do not render three distinct messages: {!r}".format(
            messages))
        return
    pass_("three tails are distinct and name their own degrade")


def test_nesting_scanner_repair_walk_memory_bounded():
    """The repaired-prefix walk's retained memory is bounded for long keys.

    The 54.4 KiB long-key fan is the shape that peaked at 97.7 MiB before
    Step 14 (a full path string retained per visited node, each carrying every
    ancestor key). The record-based walk retains a bounded number of small
    records and renders one path, so the peak stays near the repaired prefix's
    own parse size. The ceiling is deliberately generous (several MiB) — it
    pins the class of fix, not a machine-specific figure.
    """
    print("\n--- Test: Nesting Scanner Repair Walk Memory Bounded ---")

    body = _longkey_fan_body(2000)
    ceiling = 8 * 1024 * 1024
    tracemalloc.start()
    try:
        got = check_payload_nesting(body)
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    if not isinstance(got, NestingViolation) or got.path is None:
        fail("the bounded-walk fixture must still resolve a path, got {!r}".format(got))
        return
    if peak > ceiling:
        fail("repair walk peaked at {:.1f} MiB for a {:.1f} KiB body; the "
             "record walk must stay under {:.0f} MiB (pre-Step-14 shape: "
             "97.7 MiB)".format(peak / (1024.0 * 1024.0),
                                len(body) / 1024.0, ceiling / (1024.0 * 1024.0)))
        return
    pass_("{:.1f} KiB body, path resolved, peak {:.2f} MiB under the {:.0f} MiB "
          "ceiling".format(len(body) / 1024.0, peak / (1024.0 * 1024.0),
                           ceiling / (1024.0 * 1024.0)))


def test_nesting_scanner_path_rendering():
    """Path components render as .ident, ["quoted.key"], or [index]."""
    print("\n--- Test: Nesting Scanner Path Rendering ---")
    ident = '{"alpha":' + "[" * LIMIT + "]" * LIMIT + "}"
    got = check_payload_nesting(ident)
    if got is None or not got.path.startswith("$.alpha[0]"):
        fail("identifier key not rendered as .alpha with an index: {!r}".format(
            got.path if got else got))
        return
    pass_("identifier key renders as .alpha; arrays as [0]")

    dotted = '{"a.b":{"c":' + "[" * (LIMIT - 1) + "]" * (LIMIT - 1) + "}}"
    got = check_payload_nesting(dotted)
    if got is None or not got.path.startswith('$["a.b"].c[0]'):
        fail("a key containing '.' must render as [\"a.b\"], got {!r}".format(
            got.path if got else got))
        return
    pass_("key containing '.' renders as [\"a.b\"]")


def test_nesting_scanner_truncation():
    """A path longer than 200 characters renders as 140 + ellipsis + 40."""
    print("\n--- Test: Nesting Scanner Path Truncation ---")
    body = '{"alpha":' + "[" * LIMIT + "]" * LIMIT + "}"
    got = check_payload_nesting(body)
    if got is None or got.path is None:
        fail("expected a long path for the deep chain, got {!r}".format(got))
        return
    path = got.path
    if len(path) != 141 + 40:
        fail("expected the 140+1+40 truncated form (181 chars), got {} chars: "
             "{!r}".format(len(path), path[:60]))
        return
    if path[140] != "…":
        fail("expected the ellipsis at index 140, got {!r}".format(path[135:145]))
        return
    if not path.startswith("$.alpha[0]") or not path.endswith("[0]"):
        fail("truncated path lost its head or tail: {!r}".format(path))
        return
    pass_("long path truncated to head+ellipsis+tail (181 chars)")


def test_nesting_event_field_set():
    """One pure builder emits the whole shared field set, degrade included.

    Step 17 replaced eleven hand-written event dicts with
    ``nesting_event(site, violation, **fields)``. This pins the contract every
    emission point inherits by construction:

      - the fixed fields are exactly timestamp, event, site, depth, offset,
        path and degrade — so ``degrade`` is present on every site's event and
        is null when a path was produced;
      - the caller's identity fields merge in after them (here request_id,
        tier, mode and provider together, as the mode transforms pass them);
      - building an event is pure — it writes nothing to the trace itself, so
        the policy leaf keeps no dependency on the trace layer and each site
        keeps its own ``log_trace`` call.
    """
    print("\n--- Test: Nesting Event Field Set ---")
    # Importing server binds the process-wide trace sink to PROXY_TRACE_FILE,
    # which makes the purity check below meaningful.
    import claude_retry_proxy.server as _srv  # noqa: F401

    fixed = {"timestamp", "event", "site", "depth", "offset", "path", "degrade"}

    located = NestingViolation(offset=42, depth=LIMIT + 1, path="$.a[0]")
    ev = nesting_event("request_body", located)
    if set(ev) != fixed:
        fail("a bare event must carry exactly {}, got {!r}".format(
            sorted(fixed), sorted(ev)))
        return
    if ev["event"] != "nesting_limit_exceeded":
        fail("expected event nesting_limit_exceeded, got {!r}".format(ev["event"]))
        return
    if ev["site"] != "request_body":
        fail("expected the caller's site, got {!r}".format(ev["site"]))
        return
    if (ev["offset"], ev["depth"], ev["path"], ev["degrade"]) != (
            42, LIMIT + 1, "$.a[0]", None):
        fail("violation fields not mapped: {!r}".format(
            {k: ev[k] for k in ("offset", "depth", "path", "degrade")}))
        return
    if not re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\Z", ev["timestamp"]):
        fail("timestamp is not the trace format: {!r}".format(ev["timestamp"]))
        return
    pass_("fixed field set with degrade null when a path resolved")

    degraded = NestingViolation(offset=7, depth=LIMIT + 1, path=None,
                                degrade="budget")
    ev = nesting_event("compat_error_body", degraded)
    if ev["path"] is not None or ev["degrade"] != "budget":
        fail("a degraded violation must carry path None and its reason, got "
             "path {!r} degrade {!r}".format(ev["path"], ev["degrade"]))
        return
    pass_("degrade carried on the event when the locator gave up")

    ev = nesting_event("tool_args", located, request_id="req-1",
                       tier="sonnet", mode="chat", provider="p")
    if set(ev) != fixed | {"request_id", "tier", "mode", "provider"}:
        fail("caller identity fields did not merge in: {!r}".format(sorted(ev)))
        return
    if (ev["request_id"], ev["tier"], ev["mode"], ev["provider"]) != (
            "req-1", "sonnet", "chat", "p"):
        fail("merged identity fields are wrong: {!r}".format(
            {k: ev[k] for k in ("request_id", "tier", "mode", "provider")}))
        return
    pass_("identity fields merge in after the fixed set")

    trace_file = os.environ.get("PROXY_TRACE_FILE")
    before = (os.path.getsize(trace_file)
              if trace_file and os.path.exists(trace_file) else 0)
    nesting_event("request_body", located, request_id="req-purity")
    after = (os.path.getsize(trace_file)
             if trace_file and os.path.exists(trace_file) else 0)
    if after != before:
        fail("the event builder wrote to the trace file ({} -> {} bytes); it "
             "must stay pure and let the caller log".format(before, after))
        return
    pass_("builder is pure — no trace write of its own")


def test_nesting_event_vocabulary():
    """NESTING_SITES is the one site vocabulary, and the docs must match it.

    Step 17 makes the nine site values a module constant so tests can check
    that every value the code emits is known and documented. The documented
    list — the ``site`` field's parenthetical on
    ``doc/trace-log.html``'s ``nesting_limit_exceeded`` row — is parsed and
    compared in order, so a site added to the code without the trace-log entry
    (or a doc entry naming a site the code never emits) fails here rather than
    drifting silently.
    """
    print("\n--- Test: Nesting Event Vocabulary ---")
    expected = ("request_body", "admin_body", "response_transform",
                "response_rewrite", "sse_first_event", "chat_frame",
                "compat_error_body", "tool_args", "response_body_capture")
    if tuple(NESTING_SITES) != expected:
        fail("NESTING_SITES must be the nine enforcement-map sites in order, "
             "got {!r}".format(NESTING_SITES))
        return
    if len(set(NESTING_SITES)) != len(NESTING_SITES):
        fail("NESTING_SITES carries duplicates: {!r}".format(NESTING_SITES))
        return
    pass_("nine unique site values in enforcement-map order")

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    doc_path = os.path.join(root, "doc", "trace-log.html")
    try:
        with open(doc_path, encoding="utf-8") as f:
            doc = f.read()
    except OSError as e:
        fail("cannot read doc/trace-log.html to compare the vocabulary: {!r}".format(e))
        return
    anchor = doc.find("<code>nesting_limit_exceeded</code>")
    if anchor < 0:
        fail("doc/trace-log.html has no nesting_limit_exceeded row")
        return
    site_at = doc.find("<code>site</code>", anchor)
    open_at = doc.find("(", site_at)
    close_at = doc.find(")", open_at)
    if site_at < 0 or open_at < 0 or close_at < 0:
        fail("the nesting event row does not list its site values in a "
             "parenthetical — the vocabulary comparison cannot run")
        return
    documented = tuple(re.findall(r"<code>([a-z_]+)</code>",
                                  doc[open_at + 1:close_at]))
    if documented != tuple(NESTING_SITES):
        fail("doc/trace-log.html's site list and NESTING_SITES disagree: "
             "documented {!r}, code {!r}".format(documented, NESTING_SITES))
        return
    pass_("documented site list matches NESTING_SITES ({})".format(
        len(documented)))


def test_nesting_guard_rewrite_json_response():
    """_rewrite_json_response returns the original bytes on a parse/encode fault.

    Both fences are exercised: a patched ``json.loads`` covers the decode
    branch, a patched ``json.dumps`` the encode branch — deterministic, with
    no dependence on the interpreter's recursion profile.
    """
    print("\n--- Test: Guard — _rewrite_json_response ---")
    import claude_retry_proxy.server as srv

    body = b'{"model":"claude-sonnet-5","content":[]}'
    with unittest.mock.patch("json.dumps", side_effect=RecursionError):
        out = srv._rewrite_json_response(body, "sonnet", "req-nesting-guard-encode")
    if out != body:
        fail("encode fault: expected the original bytes, got {!r}".format(out[:120]))
        return
    pass_("patched json.dumps: original bytes returned, no raise")

    with unittest.mock.patch("json.loads", side_effect=RecursionError):
        out = srv._rewrite_json_response(body, "sonnet", "req-nesting-guard-decode")
    if out != body:
        fail("decode fault: expected the original bytes, got {!r}".format(out[:120]))
        return
    pass_("patched json.loads: original bytes returned, no raise")


def test_nesting_guard_transform_and_guard_encode():
    """_transform_and_guard returns the raw bytes when its ENCODE step fails.

    Encode branch only: the decode branch is covered by
    ``test_transform_failure_passthrough`` (test_mode_dispatch.py), which drives
    it on malformed wire bytes. Here the decode succeeds and the re-serialize
    is what faults.
    """
    print("\n--- Test: Guard — _transform_and_guard (encode branch) ---")
    from claude_retry_proxy.transforms_common import _transform_and_guard

    raw = b'{"id":"msg_1","content":[]}'
    with unittest.mock.patch("json.dumps", side_effect=RecursionError):
        out = _transform_and_guard(
            raw, "sonnet", lambda parsed, tier, **kw: parsed,
            "req-nesting-guard-transform", "chat", "p")
    if out != raw:
        fail("encode fault: expected the raw bytes, got {!r}".format(out[:120]))
        return
    pass_("patched json.dumps: raw bytes returned, no raise")


def test_nesting_guard_rewrite_sse_first_event():
    """_rewrite_sse_first_event forwards the original event on an encode fault."""
    print("\n--- Test: Guard — _rewrite_sse_first_event ---")
    import claude_retry_proxy.server as srv

    event = (b'event: message_start\n'
             b'data: {"type":"message_start","message":{"model":"claude-sonnet-5"}}\n\n')
    with unittest.mock.patch("json.dumps", side_effect=RecursionError):
        out = srv._rewrite_sse_first_event(event, "sonnet", "req-nesting-guard-sse")
    if out != event:
        fail("encode fault: expected the original event, got {!r}".format(out[:120]))
        return
    pass_("patched json.dumps: original event returned, no raise")


def test_nesting_guard_sse_event_encode():
    """_sse_event degrades to the encode-failure error frame instead of raising.

    The fault is scoped to the target payload (a side effect that raises only
    for the object under test): the fallback itself serializes a small fixed
    envelope, so a blanket ``side_effect=RecursionError`` would test an
    unrealistic double failure rather than the fence.
    """
    print("\n--- Test: Guard — _sse_event ---")
    import claude_retry_proxy.server as srv

    payload = {"type": "message_delta", "usage": {"input_tokens": {1, 2},
                                                  "output_tokens": 7}}
    real_dumps = json.dumps

    def dumps_for_test(obj, *args, **kwargs):
        if obj is payload:
            raise RecursionError("simulated encode overflow")
        return real_dumps(obj, *args, **kwargs)

    handler = object.__new__(srv.ProxyHandler)
    with unittest.mock.patch("json.dumps", side_effect=dumps_for_test):
        try:
            out = handler._sse_event(payload, request_id="req-nesting-guard-frame")
        except Exception as e:
            fail("_sse_event raised {!r} instead of degrading".format(e))
            return
    if not isinstance(out, bytes) or not out.startswith(b"event: error\n"):
        fail("expected an 'event: error' frame, got {!r}".format(out[:120]))
        return
    data_line = [ln for ln in out.decode("utf-8").splitlines()
                 if ln.startswith("data: ")][0]
    env = json.loads(data_line[len("data: "):])
    if (env.get("error") or {}).get("code") != "response_frame_encode_failure":
        fail("expected error.code response_frame_encode_failure, got {!r}".format(env))
        return
    if env.get("request_id") != "req-nesting-guard-frame":
        fail("request_id not threaded into the degraded frame: {!r}".format(env))
        return
    pass_("encode fault -> event: error with response_frame_encode_failure")


ALL_TESTS = [
    ("nesting-scanner-accepts-at-limit", test_nesting_scanner_accepts_at_limit),
    ("nesting-scanner-rejects-past-limit", test_nesting_scanner_rejects_past_limit),
    ("nesting-scanner-str-bytes-agree", test_nesting_scanner_str_bytes_agree),
    ("nesting-scanner-non-text-inputs", test_nesting_scanner_non_text_inputs),
    ("nesting-scanner-type-differential", test_nesting_scanner_type_differential),
    ("nesting-scanner-bytes-fast-path-skips-decode", test_nesting_scanner_bytes_fast_path_skips_decode),
    ("nesting-scanner-ignores-brackets-in-strings", test_nesting_scanner_ignores_brackets_in_strings),
    ("nesting-scanner-stray-closes-ignored", test_nesting_scanner_stray_closes_ignored),
    ("nesting-scanner-mismatched-pairs-total", test_nesting_scanner_mismatched_pairs_total),
    ("nesting-scanner-wide-body", test_nesting_scanner_wide_body),
    ("nesting-scanner-degraded-path-diagnostic", test_nesting_scanner_degraded_path_diagnostic),
    ("nesting-scanner-repair-cap", test_nesting_scanner_repair_cap),
    ("nesting-scanner-budget-degrade", test_nesting_scanner_budget_degrade),
    ("nesting-scanner-path-reconstruction", test_nesting_scanner_path_reconstruction),
    ("nesting-limit-message-three-tails", test_nesting_limit_message_three_tails),
    ("nesting-scanner-repair-walk-memory-bounded", test_nesting_scanner_repair_walk_memory_bounded),
    ("nesting-scanner-path-rendering", test_nesting_scanner_path_rendering),
    ("nesting-scanner-truncation", test_nesting_scanner_truncation),
    ("nesting-guard-rewrite-json-response", test_nesting_guard_rewrite_json_response),
    ("nesting-event-field-set", test_nesting_event_field_set),
    ("nesting-event-vocabulary", test_nesting_event_vocabulary),
    ("nesting-guard-transform-and-guard-encode", test_nesting_guard_transform_and_guard_encode),
    ("nesting-guard-rewrite-sse-first-event", test_nesting_guard_rewrite_sse_first_event),
    ("nesting-guard-sse-event-encode", test_nesting_guard_sse_event_encode),
]


if __name__ == "__main__":
    run_cli(ALL_TESTS, "claude-retry-proxy tests: test_nesting")
