# Plan: Record the client User-Agent on the request trace entry
**Plan ID:** 2026-10-21-trace-client-user-agent
**Created:** 2026-10-21
**Verification state:** the figures below describe the **pre-reopen close** of
2026-10-21 and are a historical record, not the current state. By operator
decision the plan was reopened the same day to close its one self-inflicted
deferral — `traced-ua-duplicate-header-first-vs-last` — **in-plan** rather than
later; **Step 6** (coder: the traced value now mirrors the forwarding path's
resolution) and **Step 7** (tester: the regression test)
**both landed and were verified**, and the deferral is **retired**. The current
readings replace the ones below: the Step-1 gate **32/32** (was 25/25), the module
**16/16**, the suite **424 passed / 8 failed / 432 total**, and the end-to-end
probe **4/4** (was 1/4). `## Final Results` carries the post-fix record. At the
pre-reopen close recorded here: the Step-1 gate reads **25/25 PASS, exit 0** against the shipped `src/claude_retry_proxy/server.py`. `tests/test_trace.py` reads **15/15**, and the module ran **16/16 clean** for the tester plus **4/4** independently for the planner, after the review's flake fix — against a measured **6/8** before it. The full suite reads **423 passed / 8 failed / 431 total**, exactly the frozen pre-existing baseline of 8 (+3 passed / +3 total over the clean-tree baseline of 420/8/428), with none of the eight in the touched module. Both doc gates PASS: `scripts/check_doc_anchors.py` (206 anchors resolved, no secret shapes) and `doc_structure_check.py` (9 files, no violations). Six files changed, 407 insertions / 23 deletions. Reviewer verdict: **Issues found — non-blocking** (0 Critical / 2 Warning / 6 Suggestion), report `./tmp/reports/2026-10-21-trace-client-user-agent-review-2026-10-21.json`; four findings fixed, one deferred, the rest recorded.

<!-- ## Immediate Actions: absent from initial plans. Populated by /update-plan for revised plans, replaced (not accumulated) on each revision. Contains per-role action-only directives (no rationale) telling agents what to do next. Agents read the full plan for context. -->

<!-- This plan is COMPLETE and carries no pending action for any role: both rounds
of the reopen are closed, the deferral is retired, the re-run Phase 6 review is
dispositioned, and `## Final Results` records the post-fix state. The only
outstanding step is the operator's `/update-and-commit`, which this session
deliberately did not run. -->

## Issue Log

Rows ordered newest-first (latest issues at top). New issues are prepended; resolved issues stay in place with updated status.

| Issue | Status | Found | Resolved | Resolved By |
|-------|--------|-------|----------|-------------|
| [defer-issue-traced-ua-duplicate-header-first-vs-last](./tmp/reports/defer-issue-traced-ua-duplicate-header-first-vs-last.json) | Resolved | 2026-10-21 | 2026-10-21 | [coder](./tmp/reports/2026-10-21-trace-client-user-agent-coder-2026-10-21.json) + [tester](./tmp/reports/2026-10-21-trace-client-user-agent-tester-2026-10-21.json) |
| [defer-issue-suite-json-recursion-profile-py314](./tmp/reports/defer-issue-suite-json-recursion-profile-py314.json) | Open | 2026-10-21 | — | — |
| [defer-issue-analyze-trace-model-terminal-escape](./tmp/reports/defer-issue-analyze-trace-model-terminal-escape.json) | Open | 2026-10-21 | — | — |
| [defer-issue-proxy-own-server-date-headers](./tmp/reports/defer-issue-proxy-own-server-date-headers.json) | Open | 2026-10-21 | — | — |

**The newest row is RESOLVED, not deferred — this plan adopted its own deferral.** By
operator decision the plan was reopened and **Steps 6 and 7** fixed it: the traced
value now mirrors the forwarding path's collapse, and
`test_client_user_agent_duplicate_headers_match_forwarded` pins it against the
upstream's own record of the lines it received. `Resolved By` names the fix
(coder) and its pin (tester), not the review, which runs after the close. Its
report is **deleted in the same act** — presence means open, and the report's
deletion *is* the close — so the link above is the row's record of what was
retired. **No other plan has adopted a row for this issue**, so nothing else
points at the retired report.

The remaining three rows are **deferrals** — completed dispositions, not
unfinished work of this plan. The third is the draft's "Separate item"; the
second is a terminal-escape exposure surfaced by resolving this plan's own
log-injection risk note (see `## Risks`); the first is the suite's 8 pre-existing
failures under Python 3.14, found while the planner recorded the baseline (see
`## Summary`). **Do not fix any of the three in this plan, and do not delete
their reports.** Per the live planner doctrine a deferral is *standalone* — a
filing session adds no row, an adopting plan adds one, and that row is the
retirement trigger; these three rows predate that change (they were added under
the superseded Branch-A shape) and are retained deliberately, because the
operator directed that they stay exactly as they are and the finalization gate
still counts an issue as deferred when its report is on disk.

## Guidance for Coder

**Files to modify:** `src/claude_retry_proxy/server.py`

**Round completion — read this before you start.** Run any command that can spawn
a proxy or run a test with an explicit `timeout`, and **write your session report
before you end your turn, whatever the result.** A round that reports nothing is
treated as a failed round even when its code landed.

One cohesive change, two edits to one file: a pair of policy constants and a pure
helper near `_resolve_extra_request_headers`, and one guarded assignment in
`do_POST`'s `trace_entry`. The wire is untouched — no request header changes, no
response header or body changes, no new retry, no retry-policy change. Those four
are settled operator decisions (the draft's "Decisions already taken"), and this
plan does not reopen them.

### Step 1 — the field, its cap, and its call site

**Edit 1 — the constants and the helper (`server.py`, immediately after
`_resolve_extra_request_headers`'s `return resolved`, which is line 928; the next
thing in the file is the blank-line run before `def _forward_request_impl`).**
Insert verbatim. **This block shows the FINAL text** — the paragraph after it
records what Step 6 changed from the form Step 1 first landed:

```python
# --- the client User-Agent on the request trace entry ------------------------
# The proxy forwards the client's User-Agent upstream, so a UA-based edge
# refusal (Cloudflare's `1010` browser-signature block) is only legible next to
# the UA that produced it. This field records that value -- the last one the
# forwarding path sends -- never rewritten, so it names the INBOUND string,
# unlike `extra_request_headers`, which records resolved OUTBOUND values. A UA
# is client-controlled and otherwise unbounded, so it is capped, visibly.
CLIENT_USER_AGENT_MAX_CHARS = 512
CLIENT_USER_AGENT_TRUNCATION_MARKER = "[proxy: user-agent truncated]"


def _client_user_agent(headers):
    """The User-Agent the proxy forwards, capped; None when absent or empty.

    `headers` is the request's header mapping -- an `email.message.Message`,
    whose keys keep the casing the client sent. The parser strips a header's
    leading whitespace and normalizes a whitespace-only header to "", so such a
    header is omitted rather than recorded as blank; a non-empty value keeps its
    trailing whitespace.

    Resolution MIRRORS THE FORWARDING PATH, because the field exists to name the
    UA that produced an upstream refusal, so a value the upstream never received
    is worse than no value at all. `do_POST` hands `forward_request` a plain dict
    built from `self.headers.items()`, and `http.client` then sends that dict in
    order: same-cased duplicates collapse to the last value (the single line the
    upstream receives), while differently-cased ones survive as separate keys
    and put two lines on the wire. Taking the collapse's last value names the
    last UA line forwarded. When the request carried one casing -- the ordinary
    case, and the only one in which a single value is a well-defined mirror --
    that is exactly the line on the wire.

    No sanitizing: the value IS the diagnostic, and `sanitize_error` exists for
    error text (it redacts home-directory paths and IPv4 literals and caps at
    200 chars), none of which applies to a UA.

    A value longer than the cap keeps its head -- the informative prefix, e.g.
    "Python-urllib/3.11" -- and gains a visible marker, so a truncated UA is
    never mistaken for a genuine one. The result is at most
    CLIENT_USER_AGENT_MAX_CHARS characters; `http.server` decodes header values
    as latin-1, so one character is one byte and that is also the byte bound.
    """
    forwarded = {k: v for k, v in headers.items() if k.lower() == "user-agent"}
    values = list(forwarded.values())
    value = values[-1] if values else None
    if not value:
        return None
    if len(value) <= CLIENT_USER_AGENT_MAX_CHARS:
        return value
    keep = CLIENT_USER_AGENT_MAX_CHARS - len(CLIENT_USER_AGENT_TRUNCATION_MARKER)
    return value[:keep] + CLIENT_USER_AGENT_TRUNCATION_MARKER
```

**Step 6 revised three things in this block**, which Step 1 had landed in an
earlier form. The record of why is in the `## History`; the operational summary
is: the docstring's opening line and its new *Resolution* paragraph, the block
comment's "records that value — the last one the forwarding path sends" clause,
and **the resolution itself**, which was `value = headers.get("User-Agent")` —
`Message.get` returns the *first* of a set of same-cased duplicates, a value the
upstream never received. Everything else, including the cap arithmetic and the
`return None` contract, is byte-identical to what Step 1 landed.

Contract points the gate pins:
- **The resolution mirrors the forwarding path, and the gate recomputes that
  path rather than restating it.** `do_POST` passes
  `{k: v for k, v in self.headers.items()}` to `forward_request`; the dict keeps
  the **last** value per distinct key, and `http.client` sends that dict's items
  in insertion order. So the helper applies the same collapse, filters it to
  `user-agent` keys, and takes its **last** value. Measured end-to-end by
  `./tmp/verification/2026-10-21-trace-client-user-agent-duplicate-ua-probe.py`,
  which reads the mock upstream's own inbound header lines:
  same-cased duplicates put **one** line on the wire carrying the last value,
  and mixed casings put **two**. Do **not** substitute `headers.get_all(...)[-1]`
  — it is the request's last UA *line*, which the collapse can **reorder**
  (`User-Agent: a`, `user-agent: b`, `User-Agent: c` forwards `['c', 'b']`,
  whose last line is `b`, not `c`).
- **`headers.get("User-Agent")` must not appear anywhere in the helper**, comments
  included — check 5 asserts its absence precisely because the shape it pins is
  the fix.
- **`return None` on the falsy path, never `""`.** The caller's `is not None`
  guard is what omits the key; an empty string would be recorded as `""` and
  break the omit-when-absent convention. An empty value on the *last* duplicate
  omits the field too — the resolved value is what the contract is stated over,
  not the first one.
- **Case-insensitivity is now by `k.lower()`, not by `Message.get`.** The filter
  is `k.lower() == "user-agent"` — the same test the forwarding path's own
  `FORWARD_HEADERS` membership applies. A client sending `user-agent` or
  `USER-AGENT` is still found; the gate asserts it.
- **The cap is on the whole stored value, marker included.** `keep` is
  `512 - len(marker)` = 483, so a truncated value is exactly 512 characters —
  never 512 + marker. The gate asserts the exact output, not a `<=`.
- **Characters are bytes here, and the plan says why.** Header values reach the
  handler latin-1-decoded (verified on a live handler: a raw `0xFF` byte arrives
  as `U+00FF`, `0xC3` as `U+00C3`), so `len(value)` is `len(value.encode("latin-1"))`.
  Do **not** add an `encode`/`decode` round-trip to "fix" this — the gate's
  non-ASCII feed (`"é" * 600`) fails if the coupling is ever broken, which is the
  point of asserting it rather than assuming it.
- **No `.strip()`, no `.lower()`, no rewriting of the value.** The value is what
  the client sent. `email` has already stripped the outer edges.

**Edit 2 — the call site (`server.py`, in `do_POST`, immediately after the
`if resolved_extra:` block that ends at line 3804, before the `try:` that
re-resolves the key name).** Insert verbatim:

```python
        # The client's User-Agent as received. Recorded on every request, not
        # only under --all -- like extra_request_headers above, and unlike the
        # bodies. It is the input a UA-based edge refusal keys on, and the one
        # thing the entry otherwise omits when a 403 comes back carrying
        # nothing but `error code: 1010`.
        _client_ua = _client_user_agent(self.headers)
        if _client_ua is not None:
            trace_entry["client_user_agent"] = _client_ua
```

Contract points the gate pins:
- **Exactly one assignment site.** `grep -n 'client_user_agent' src/claude_retry_proxy/server.py`
  returns this line and the docstring/comment mentions — no second
  `trace_entry[...] =` site anywhere.
- **Not inside `if SETTINGS.log_all:`.** The field is ungated, deliberately: it
  is the diagnostic for a failure whose whole point is that it happens on a
  normal request, and gating it behind `--all` would make it absent exactly when
  it is needed. `extra_request_headers` is the established precedent for an
  ungated field.
- **The 413 early-return entry is NOT extended.** The literal `log_trace({...})`
  at `server.py:3741-3752` (the payload-too-large rejection) is written *before*
  routing and is already documented as a reduced-shape entry (it carries no
  `tier` and no `provider`). A client's UA cannot influence a 413, and this plan
  is deliberately one call site — the operator's integration table names exactly
  one. `doc/trace-log.html` gains the exclusion in its existing exception box.
  **Do not "fix" this by adding the field there.**
- **`mode_dispatch` is untouched.** The field lands on the `request` entry only.
- Every other line of `do_POST`, and every other `log_trace` payload in the file,
  is unchanged.

→ coder verify (auto): `grep -n "CLIENT_USER_AGENT_MAX_CHARS\|CLIENT_USER_AGENT_TRUNCATION_MARKER\|_client_user_agent\|client_user_agent" src/claude_retry_proxy/server.py` shows the two constants, one `def _client_user_agent(headers):`, the `forwarded`/`values`/`values[-1]` resolution, `return None`, `keep = CLIENT_USER_AGENT_MAX_CHARS - len(CLIENT_USER_AGENT_TRUNCATION_MARKER)`, and exactly one `trace_entry["client_user_agent"] =`; `python3 -c "import claude_retry_proxy.server"` exits 0; `python3 -c "import claude_retry_proxy.server as s; print(s.__file__)"` prints this repo's `src/claude_retry_proxy/server.py` (the install is still editable — **use `python3`, a bare `python` is not on PATH here**)
→ coder verify (scripted): `python3 ./tmp/verification/2026-10-21-trace-client-user-agent-step1.py` → exit 0 (32 checks: 12 structural, 20 algorithmic — the algorithmic half covers the single-header, cap, marker, byte-bound and control-character cases plus the seven duplicate-resolution cases added by Step 6). **It is red against the pre-change tree — calibrated: 8 FAIL, exit 1**, and it was red again on 2026-10-21 at the same 8 FAIL against the tree carrying the Step-1 form. The planner has separately calibrated the plan's *own two code blocks* through this gate: `python3 ./tmp/verification/2026-10-21-trace-client-user-agent-step1-calibration.py` reads the blocks **out of the plan file**, splices them into the **HEAD revision** of `server.py` (not the working tree, so the instrument survives the change landing), and reads the gate green, with every plan line asserted present verbatim in the spliced text.
→ tester verify: the three new tests in `tests/test_trace.py` pass end-to-end (through a live proxy, asserting on the JSONL file), and the full suite's count rises by exactly the number of tests added

### Step 6 — resolve the User-Agent the forwarding path sends

**Why this step exists.** The trace field's whole purpose is to name the UA that
produced an upstream refusal. Step 1 resolved it with `Message.get`, which returns
the **first** of a set of same-cased duplicates — and the forwarding path does not
send the first. `do_POST` passes `{k: v for k, v in self.headers.items()}` to
`forward_request`; that dict keeps the **last** value per distinct key, and
`http.client` sends its items in order. **Measured end-to-end** by
`./tmp/verification/2026-10-21-trace-client-user-agent-duplicate-ua-probe.py`,
which sends each case over a raw socket and reads the mock upstream's own inbound
lines:

| request's UA headers | traced (Step-1 form) | upstream received |
|---|---|---|
| `User-Agent: solo/1.0` | `solo/1.0` | `['solo/1.0']` |
| `User-Agent: one`, `User-Agent: two` | **`one`** | `['two']` |
| `User-Agent: one`, `user-agent: two` | **`one`** | `['one', 'two']` |
| `User-Agent: a`, `user-agent: b`, `User-Agent: c` | **`a`** | `['c', 'b']` |

Row 2 is the defect this step closes: the recorded value was a UA the upstream
never received at all. Rows 3 and 4 name the residual — with mixed casings the
wire carries **two** lines, so no single value is a complete mirror; the rule
below names the **last** of them, which is the most a single value can be.

**Edit — the resolution, in `_client_user_agent` (`server.py`, the helper added
by Step 1).** Replace its one resolution line

```python
    value = headers.get("User-Agent")
```

with the forwarding path's own collapse:

```python
    forwarded = {k: v for k, v in headers.items() if k.lower() == "user-agent"}
    values = list(forwarded.values())
    value = values[-1] if values else None
```

Then update two pieces of prose to match — § Step 1's block carries the final
text, so copy the docstring and the constants' block comment from there. The
docstring's second paragraph ("Resolution MIRRORS THE FORWARDING PATH…") and the
block comment's "records that value — the last one the forwarding path sends"
clause are new; the rest is Step 1's wording.

Contract points the gate pins:
- **The collapse is the forwarding path's, not a lookalike.** The comprehension
  is the same one `do_POST` evaluates (`{k: v for k, v in ... .items()}`), with
  the `FORWARD_HEADERS` membership narrowed to the one header this helper is
  about. The gate does not restate the rule — `wire_ua_lines()` in the gate
  **recomputes** it from the request's headers and asserts the helper equals that
  list's last element, so the two cannot drift apart.
- **`values[-1] if values else None`, not `get_all(...)[-1]`.** `get_all` returns
  the request's UA lines in request order; the collapse can **reorder** them
  (row 4: the request's last line is `c`, the wire's last line is `b`). The gate
  has a case that fails on `get_all` and passes on the collapse.
- **The rest of the helper is untouched.** The `if not value: return None`
  guard, the cap comparison and `value[:keep] + CLIENT_USER_AGENT_TRUNCATION_MARKER`
  stay byte-identical; the single-header case's contract (verbatim under the cap,
  head + visible marker over it, `None` when absent or empty) is unchanged and
  is what the algorithmic half's first thirteen checks cover.
- **Do not write the literal `headers.get("User-Agent")` anywhere in the helper**,
  comments included — the gate asserts its absence, deliberately: that shape is
  the defect.

→ coder verify (auto): `grep -n "forwarded\|values\[-1\]\|headers.get" src/claude_retry_proxy/server.py` shows the three new lines inside `_client_user_agent` and **no** `headers.get` in that helper; `text.count("def _client_user_agent(") == 1`; `python3 -c "import claude_retry_proxy.server"` exits 0 and reports this repo's `src/` path
→ coder verify (scripted): `python3 ./tmp/verification/2026-10-21-trace-client-user-agent-step1.py` → **32/32 PASS, exit 0**. It read **8 FAIL / exit 1** against the Step-1 tree (measured 2026-10-21), all eight in the duplicate-resolution dimension.
→ tester verify: the Step-7 regression test passes — the traced value equals the last `User-Agent` line the upstream received, for the same-cased and mixed-cased cases alike; and `test_client_user_agent_in_trace`, `test_client_user_agent_control_characters_stay_one_line` and `test_client_user_agent_ungated_and_entry_scoped` still pass unchanged (no contract change for a single-header request)

## Guidance for Tester

**Files to modify:** `tests/test_trace.py` only. Do not touch
`src/claude_retry_proxy/server.py` (Steps 1 and 6 are the coder's lane) and do not
touch `doc/**`, `README.md` or `CLAUDE.md` (planner-owned).

**Round completion — read this before you start.** Bound every command that can
spawn a proxy or run a test with an explicit `timeout`, run the full suite in the
**foreground**, and **write your session report before you end your turn.**

**Where these go.** `tests/test_trace.py` already carries the exact analogue —
`test_extra_request_headers_in_trace` (`:839`) with its module-level
`_read_request_events(trace_file)` helper (`:820`) and the `_start_mode_proxy`
harness entry point — and `ALL_TESTS` is at `:1345`. Append the three functions
after `test_trace_includes_key_name_not_payload` and register them at the end of
`ALL_TESTS`. **You will need to add `_trace_events_named` and
`_wait_for_trace_events` to the `_harness` import block at the top of the file**
(they exist at `tests/_harness.py:1403` and `:1424`); neither is currently
imported there.

**Division of labour — read this before writing anything.** The pure rule (the
cap arithmetic, the marker, the omit-on-falsy branch, the case-insensitive
lookup, the chars-are-bytes coupling) is pinned by the **coder's Step-1 gate**,
which feeds the shipped `_client_user_agent` a known-input truth table. **Your
lane is everything the gate cannot see**: that the value survives the whole path
into the JSONL file, that the file stays one-entry-per-line under hostile input,
that the field is ungated, and that it lands on the right entry and only there.
Do not re-implement the gate's truth table as a test — if you find a gap in it,
add a case, and say so in your report.

**Settled facts about the transport, so you do not have to rediscover them**
(all measured on this interpreter, Python 3.14):

- `http.client` encodes header values as **latin-1** and rejects only raw `\r`
  and `\n`; `\x00`, `\x1b`, `\x07` and `\x9b` pass through
  `_send_proxy_request(headers={...})`. So every control-character case except
  the CRLF-fold one goes through the normal helper.
- `_send_proxy_request(..., headers={"User-Agent": "é" * 600})` sends the
  latin-1 bytes — the non-ASCII case needs no raw socket.
- A client can still get a literal CRLF into the value **via obs-fold**: a header
  continuation line makes `email` return `"line1\r\n continuation"`. That is the
  only case needing a raw socket. Raw-socket sending already has precedent in
  `tests/test_trace.py` (see the readiness probes).
- An empty or whitespace-only UA arrives as `""` (the `email` parser strips the
  outer whitespace), so both must omit the key.
- `json.dumps` in `TraceSink._emit` uses `ensure_ascii=True` (the default), so
  every control character and every non-ASCII codepoint is escaped on disk —
  `\x1b` becomes the six characters `\u001b`. The file is pure ASCII.

```python
def test_client_user_agent_in_trace():
    """The request entry carries the client User-Agent as received: verbatim
    when short, truncated to exactly 512 characters with a visible marker when
    long, and OMITTED entirely (not null) when absent, empty or whitespace-only.
    The cap is characters, which for latin-1-decoded header values is bytes."""
    print("\n--- Test: client User-Agent in trace events ---")
    import claude_retry_proxy.server as srv
    cap = srv.CLIENT_USER_AGENT_MAX_CHARS
    marker = srv.CLIENT_USER_AGENT_TRUNCATION_MARKER
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(
        _mode_tiers(), {"p": {"url": "http://127.0.0.1:{}".format(find_free_port()),
                              "key": "K"}})
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        def ua_of(headers):
            """Send one request and return (status, its own request entry).

            The trace write precedes the response on this path (`log_trace` at
            server.py:3848, `_send_response` at :3852), so `events[-1]` is
            deterministic — but assert the entry count grew by exactly one, so
            a stale read can never pass silently.
            """
            before = len(_read_request_events(trace_file))
            status, _ = _send_proxy_request(proxy_port, headers=headers)
            events = _read_request_events(trace_file)
            if len(events) != before + 1:
                fail("expected exactly one new request entry, {} -> {}".format(
                    before, len(events)))
                return status, None
            return status, events[-1]

        # (a) a short UA is recorded verbatim
        status, ev = ua_of({"User-Agent": "Python-urllib/3.11"})
        if status != 200 or ev is None:
            fail("short-UA request expected 200 + a trace entry, got {}".format(status))
            return
        if ev.get("client_user_agent") != "Python-urllib/3.11":
            fail("expected the UA verbatim, got {!r}".format(ev.get("client_user_agent")))
            return
        pass_("short UA recorded verbatim")

        # (b) no UA -> the key is ABSENT, not null
        status, ev = ua_of({})
        if status != 200 or ev is None:
            fail("no-UA request expected 200 + a trace entry, got {}".format(status))
            return
        if "client_user_agent" not in ev:
            pass_("absent UA omits the key")
        else:
            fail("expected the key to be omitted for a UA-less request, got {!r}".format(
                ev.get("client_user_agent")))
            return

        # (c) empty and whitespace-only UA -> also absent
        for label, sent in (("empty", ""), ("whitespace-only", "   ")):
            status, ev = ua_of({"User-Agent": sent})
            if ev is None or "client_user_agent" in ev:
                fail("{} UA must omit the key, got {!r}".format(
                    label, ev.get("client_user_agent") if ev else None))
                return
        pass_("empty and whitespace-only UA omit the key")

        # (d) an oversize ASCII UA -> exactly the cap, head preserved, marker last
        sent = "A" * (cap + 88)
        status, ev = ua_of({"User-Agent": sent})
        got = (ev or {}).get("client_user_agent")
        if not isinstance(got, str) or len(got) != cap:
            fail("oversize UA must truncate to exactly {} chars, got {!r}".format(
                cap, len(got) if isinstance(got, str) else got))
            return
        if not got.endswith(marker) or got != "A" * (cap - len(marker)) + marker:
            fail("expected head + marker, got {!r}".format(got))
            return
        pass_("oversize ASCII UA truncated to exactly {} chars with the marker".format(cap))

        # (e) an oversize NON-ASCII UA pins the byte bound: 512 chars == 512
        #     latin-1 bytes. http.client sends these as latin-1 bytes, and the
        #     handler decodes them back latin-1, so a 600-char feed must come
        #     back as exactly 512 characters AND 512 bytes.
        status, ev = ua_of({"User-Agent": "é" * (cap + 88)})
        got = (ev or {}).get("client_user_agent")
        if not isinstance(got, str) or len(got) != cap:
            fail("non-ASCII oversize UA must be {} chars, got {!r}".format(
                cap, len(got) if isinstance(got, str) else got))
            return
        if len(got.encode("latin-1")) != cap:
            fail("the cap must be {} latin-1 BYTES, got {}".format(
                cap, len(got.encode("latin-1"))))
            return
        pass_("non-ASCII oversize UA is exactly {} chars == {} latin-1 bytes".format(cap, cap))
    finally:
        cleanup()


def test_client_user_agent_control_characters_stay_one_line():
    """A hostile UA cannot forge a trace line. Control bytes (NUL, ESC, BEL, C1
    CSI) sent through the normal helper, and a literal CRLF injected by a header
    continuation line over a raw socket, must all leave the JSONL file with
    exactly one physical line per entry, parse as JSON, and round-trip to the
    value the client actually sent."""
    print("\n--- Test: client User-Agent — control characters stay one line ---")
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(
        _mode_tiers(), {"p": {"url": "http://127.0.0.1:{}".format(find_free_port()),
                              "key": "K"}})
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        # (a) control bytes that http.client accepts
        hostile = "x\x00y\x1b[31mz\x07w\x9bv"
        status, _ = _send_proxy_request(proxy_port, headers={"User-Agent": hostile})
        if status != 200:
            fail("hostile-UA request expected 200, got {}".format(status))
            return
        events = _read_request_events(trace_file)
        got = events[-1].get("client_user_agent") if events else None
        if got != hostile:
            fail("control characters must survive verbatim, got {!r}".format(got))
            return
        pass_("NUL / ESC / BEL / C1-CSI survive verbatim in the entry")

        # (b) a literal CRLF via obs-fold, over a raw socket — http.client
        #     refuses to send this, so build the request by hand.
        raw = (b"POST /v1/messages HTTP/1.1\r\n"
               b"Host: 127.0.0.1\r\n"
               b"User-Agent: foldhead\r\n foldtail\r\n"
               b"Content-Type: application/json\r\n"
               b"Content-Length: " + str(len(REQUEST_BODY)).encode() +
               b"\r\n\r\n" + REQUEST_BODY)
        s = socket.create_connection(("127.0.0.1", proxy_port), timeout=10)
        try:
            s.sendall(raw)
            s.recv(65536)
        finally:
            s.close()

        # (c) the file is intact: one physical line per entry, every line parses.
        #     `TraceSink._emit` writes json.dumps(payload) + "\n", so the number
        #     of newlines equals the number of entries -- a raw newline smuggled
        #     in through the UA would show up here as a surplus, and the torn
        #     halves would fail to parse.
        with open(trace_file, "rb") as f:
            raw_bytes = f.read()
        physical = [ln for ln in raw_bytes.split(b"\n") if ln.strip()]
        parsed = []
        for i, ln in enumerate(physical):
            try:
                parsed.append(json.loads(ln))
            except Exception as e:
                fail("physical line {} does not parse as JSON: {}".format(i, e))
                return
        if raw_bytes.count(b"\n") != len(physical):
            fail("entry count and newline count disagree ({} vs {}) — a raw "
                 "newline reached the file".format(raw_bytes.count(b"\n"), len(physical)))
            return
        for i, obj in enumerate(parsed):
            if not isinstance(obj, dict) or "event" not in obj or "timestamp" not in obj:
                fail("physical line {} is not a trace entry: {!r}".format(i, obj))
                return
        folded = [e for e in parsed if str(e.get("client_user_agent", "")).startswith("foldhead")]
        if not folded:
            fail("the obs-fold request produced no request entry")
            return
        if folded[-1].get("client_user_agent") != "foldhead\r\n foldtail":
            fail("expected the folded value with its literal CRLF, got {!r}".format(
                folded[-1].get("client_user_agent")))
            return
        # every line is pure ASCII: json.dumps escapes control chars and non-ASCII
        for i, ln in enumerate(physical):
            try:
                ln.decode("ascii")
            except UnicodeDecodeError:
                fail("physical line {} carries raw non-ASCII bytes — the sink's "
                     "json.dumps no longer escapes them".format(i))
                return
        pass_("obs-fold CRLF escaped; every line parses and is pure ASCII")
    finally:
        cleanup()


def test_client_user_agent_ungated_and_entry_scoped():
    """The field is NOT gated by --all (a normal request carries it while
    request_body does not), it lands on the `request` entry and NOT on
    `mode_dispatch`, and it is absent from the pre-routing 413 entry — whose
    reduced shape is a documented exclusion, not an oversight."""
    print("\n--- Test: client User-Agent — ungated and entry-scoped ---")
    # PROXY_MAX_BODY_SIZE is lowered to its 1024-byte minimum so part (c) can
    # reach the 413 path with a 1.5 KB body; the same idiom as
    # test_trace_logs_oversized_body (tests/test_trace.py:432-436).
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(
        _mode_tiers(), {"p": {"url": "http://127.0.0.1:{}".format(find_free_port()),
                              "key": "K", "mode": "chat"}},
        extra_env={"PROXY_MAX_BODY_SIZE": "1024"})
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        # (a) present on a normal request, with --all off (the default)
        status, _ = _send_proxy_request(proxy_port, headers={"User-Agent": "gated/probe"})
        if status != 200:
            fail("chat-mode request expected 200, got {}".format(status))
            return
        events = _read_request_events(trace_file)
        if not events:
            fail("no request trace entry")
            return
        ev = events[-1]
        if ev.get("client_user_agent") != "gated/probe":
            fail("the field must be present without --all, got {!r}".format(
                ev.get("client_user_agent")))
            return
        if "request_body" in ev:
            fail("this test assumes --all is OFF; request_body is present")
            return
        pass_("present without --all (and request_body correctly absent)")

        # (b) the mode_dispatch event for the same request does NOT carry it
        dispatches = _trace_events_named(trace_file, "mode_dispatch")
        if not dispatches:
            fail("chat mode produced no mode_dispatch event")
            return
        if any("client_user_agent" in d for d in dispatches):
            fail("mode_dispatch must not carry the field")
            return
        pass_("mode_dispatch carries no client_user_agent")

        # (c) the pre-routing 413 entry omits it (documented exclusion).
        #     The body must exceed the lowered 1024-byte cap; 1500 does.
        huge = json.dumps({"model": "sonnet",
                           "messages": [{"role": "user", "content": "x" * 1500}]}).encode()
        import http.client as _hc
        conn = _hc.HTTPConnection("127.0.0.1", proxy_port, timeout=10)
        conn.request("POST", "/v1/messages", body=huge,
                     headers={"Content-Type": "application/json",
                              "User-Agent": "oversize/probe"})
        resp = conn.getresponse()
        resp.read()
        conn.close()
        if resp.status != 413:
            fail("expected 413 for an oversized body, got {}".format(resp.status))
            return
        # The 413 path RESPONDS first and writes its trace entry second, so a
        # client that returns as soon as the response lands can outrun the
        # write. Poll rather than read once.
        ev413 = [e for e in _wait_for_trace_events(trace_file, "request")
                 if e.get("http_status") == 413]
        if not ev413:
            fail("no 413 request entry in the trace")
            return
        if "client_user_agent" in ev413[-1]:
            fail("the 413 entry must omit the field — its absence is documented; "
                 "if this is deliberate, update doc/trace-log.html and this test together")
            return
        pass_("413 entry omits the field, as documented")
    finally:
        cleanup()
```

Two module-level fixtures the third test leans on — `REQUEST_BODY` for the
fold test and the oversized body for the 413 probe. Define `REQUEST_BODY` once,
near the top of the new block:

```python
REQUEST_BODY = json.dumps({"model": "sonnet",
                           "messages": [{"role": "user", "content": "hi"}]}).encode()
```


### Step 7 — pin the duplicate-header resolution

**Why this step exists.** Step 6 changed what the field *records* for a request
carrying more than one `User-Agent` header. The three shipped tests all send a
single header, so none of them can see that change — the whole defect lived in a
case no test covered. This test covers it, and it asserts against the **upstream's
own record** of the headers it received, not against a restatement of the rule:
`mock_servers["p"]["requests"][i]["headers"]["user-agent"]` is a **list** of the
UA lines the mock upstream got (`tests/_harness.py`'s `_record_request_headers`,
`:312`). That is what makes "equal to the forwarded one" a real assertion.

**What to send, and why a raw socket.** `http.client` cannot send a duplicate
header, so build the request by hand — exactly as
`test_client_user_agent_control_characters_stay_one_line` already does for its
obs-fold case. Three cases, measured end-to-end by the planner on 2026-10-21 with
`./tmp/verification/2026-10-21-trace-client-user-agent-duplicate-ua-probe.py`:

| sent | UA lines the upstream receives | traced value must be |
|---|---|---|
| `User-Agent: one`, `User-Agent: two` | `['two']` — **one** line; same-cased duplicates collapse | `two` |
| `User-Agent: one`, `user-agent: two` | `['one', 'two']` — two lines, two casings | `two` (the last) |
| `User-Agent: a`, `user-agent: b`, `User-Agent: c` | `['c', 'b']` — the collapse **reorders** | `b` (the last) |

Case 1 is the defect: the Step-1 form recorded `one`, a UA the upstream never
received. Case 3 is the rule's guard rail: the request's own last UA line is `c`,
so it fails on `headers.get_all("User-Agent")[-1]` and passes only on the
forwarding path's collapse — pinning the rule the fix chose, not a lookalike.

**Test to add** (`tests/test_trace.py`, after the three existing client-UA tests,
and register it at the end of `ALL_TESTS`):

```python
def test_client_user_agent_duplicate_headers_match_forwarded():
    """With more than one User-Agent header, the traced value names the line the
    forwarding path actually sends. `do_POST` hands `forward_request` a plain
    dict built from `self.headers.items()`, which keeps the LAST value per
    distinct key, and `http.client` then sends that dict in order: same-cased
    duplicates reach the upstream as ONE line carrying the second value, and
    differently-cased ones as TWO lines. The entry records the last of them --
    never the first, which for same-cased duplicates the upstream never received.

    Duplicate headers cannot be sent by `http.client`, so these go over a raw
    socket, as the obs-fold case above already does."""
    print("\n--- Test: client User-Agent — duplicates match what was forwarded ---")
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(
        _mode_tiers(), {"p": {"url": "http://127.0.0.1:{}".format(find_free_port()),
                              "key": "K"}})
    if proc is None:
        fail("Failed to set up test")
        return

    def raw_ua_request(pairs):
        """POST REQUEST_BODY with the given User-Agent header lines, by hand."""
        lines = [b"POST /v1/messages HTTP/1.1",
                 b"Host: 127.0.0.1",
                 b"Content-Type: application/json",
                 b"Content-Length: " + str(len(REQUEST_BODY)).encode()]
        for k, v in pairs:
            lines.append(("{}: {}".format(k, v)).encode("latin-1"))
        raw = b"\r\n".join(lines) + b"\r\n\r\n" + REQUEST_BODY
        s = socket.create_connection(("127.0.0.1", proxy_port), timeout=15)
        try:
            s.sendall(raw)
            s.recv(65536)
        finally:
            s.close()

    try:
        cases = (
            # (label, header lines to send, how many UA lines must reach upstream)
            ("same-cased duplicates", [("User-Agent", "one"),
                                       ("User-Agent", "two")], 1),
            ("mixed-cased duplicates", [("User-Agent", "one"),
                                        ("user-agent", "two")], 2),
            ("interleaved casings", [("User-Agent", "a"), ("user-agent", "b"),
                                     ("User-Agent", "c")], 2),
        )
        for _label, pairs, _n in cases:
            raw_ua_request(pairs)

        # Each raw request completes before the next is sent, and this path
        # writes the trace entry BEFORE the response (log_trace precedes
        # _send_response), so the last len(cases) entries are these requests.
        entries = _read_request_events(trace_file)[-len(cases):]
        reqs = mock_servers["p"]["requests"][-len(cases):]
        if len(entries) != len(cases) or len(reqs) != len(cases):
            fail("expected {} request entries and {} upstream requests, got {} and {}"
                 .format(len(cases), len(cases), len(entries), len(reqs)))
            return
        for i, (label, _pairs, n_lines) in enumerate(cases):
            wire = ((reqs[i].get("headers") or {}).get("user-agent"))
            if wire is None or len(wire) != n_lines:
                fail("{}: expected {} user-agent line(s) at the upstream, got {!r}"
                     .format(label, n_lines, wire))
                return
            traced = entries[i].get("client_user_agent")
            if traced != wire[-1]:
                fail("{}: the entry records {!r} but the upstream received {!r} — the "
                     "traced value must name the UA that was forwarded".format(
                         label, traced, wire))
                return
        pass_("duplicate User-Agent headers: the traced value is the last line forwarded")
    finally:
        cleanup()
```

Contract points this step pins:
- **Assert against the upstream's record, never against the helper.** A test that
  recomputed the rule would pass even if the *forwarding path* changed, which is
  the one thing this field must track. `mock_servers[...]["headers"]["user-agent"]`
  is the wire's own testimony.
- **Case 3 is not decoration.** It is the only case that distinguishes the chosen
  collapse from `get_all()[-1]`; without it, a later "simplification" to `get_all`
  would keep every test green while the field again named a UA that was not the
  last one sent.
- **No new import.** This test reads the trace synchronously after each response,
  so it needs neither `_wait_for_trace_events` nor a poll — `socket` and the
  `_harness` names it uses are already imported at the top of the file. Do not
  re-add `_wait_for_trace_events` to that import block.
- **Do not touch the wire.** Source changes are the coder's lane (Step 6); this
  step adds one test function and one `ALL_TESTS` entry.

→ tester verify: `test_client_user_agent_duplicate_headers_match_forwarded` passes;
  `tests/test_trace.py`'s registered count rises **15 → 16** and the full suite's
  total **431 → 432**; the three existing client-UA tests and
  `test_extra_request_headers_in_trace` pass unchanged; the suite's failure count
  stays at the recorded baseline of **8**. The report states the **measured**
  before/after counts. **The red side was measured by the planner, not by you**:
  the same three cases read `one` / `one` / `a` (against wire `['two']` /
  `['one','two']` / `['c','b']`) before Step 6 landed, which the end-to-end probe
  scored **1/4** and the Step-1 gate scored **8 FAIL**. Step 6 landed at 20:13
  today, so this test passes on its first run — say that plainly in the report
  rather than claiming you observed it fail.

**Tests to create:**
- **Permanent:** the four tests above. `test_client_user_agent_in_trace` (the
  presence/omission/truncation matrix), and
  `test_client_user_agent_control_characters_stay_one_line` are the plan's
  contract; `test_client_user_agent_ungated_and_entry_scoped` pins the three
  deliberate boundaries (ungated, `request`-only, 413-excluded) so a later
  "consistency fix" has to change the doc and the test together; and
  `test_client_user_agent_duplicate_headers_match_forwarded` (Step 7) pins the
  resolution against the upstream's own record.

**Tests to investigate for retirement:**
- **No test obsolescence identified.** Nothing is removed, and the three shipped
  client-UA tests keep their meaning: Step 6 changes the resolution only for a
  request carrying more than one `User-Agent` header, which none of them sends, so
  they cannot go stale from it — they pin the single-header contract that Step 6
  explicitly leaves untouched, and they must keep passing.
  `test_extra_request_headers_in_trace` (`:839`) is the nearest neighbour and
  exercises a *different* field on the same entry — it must keep passing
  untouched. `test_extra_request_headers_attach_matrix` and
  `test_user_agent_forwarded_all_modes` in `tests/test_mode_dispatch.py`
  exercise the outbound wire, which this plan does not touch — verify they still
  pass; do not edit them.
- Tester may identify additional candidates during test work.

**Retirement procedure:** For each candidate, verify the test exercises code being
removed/changed. If obsolete: delete and note in session report. If still valid:
document why in session report (e.g., "tests error handling path still present").

→ tester verify: the three new tests pass; `tests/test_trace.py`'s registered
  count rises from **12 to 15** and the full suite's total rises from **428 to
  431**; the pre-existing trace tests pass unchanged; **the failure count must
  not rise above the recorded pre-existing baseline of 8** — this plan adds no
  failing test, and a new failure is a finding, not a baseline artefact. The
  report states the **measured** before/after counts (do not infer them).
  **These are Step 2's own counts, measured when it landed; Step 7 supersedes
  them for the reopened plan with 15 → 16 and 431 → 432.**

**The suite's recorded baseline, measured by the planner on 2026-10-21 against
the clean tree (`git status` clean, `master` @ `bf3f8f2`):
`420 passed, 8 failed, 428 total`.** The 8 pre-existing failures are **not
caused by this plan and are not this plan's work** — they are dispositioned in
the `## Issue Log` and `## Summary`. Do **not** attempt to fix them, do not
attribute them to this plan, and do not let them change the pass/fail expectation
above.

## Summary

**The problem.** The proxy relays the client's `User-Agent` upstream verbatim, and
some User-Agent strings are refused at the edge. Diagnosing such a refusal today
requires a controlled experiment, because the trace never records the UA. Measured
against the live proxy on 2026-10-21 with model, tier and headers held fixed and
only the UA varied: `Python-urllib/3.x` took `403 error code: 1010` (Cloudflare's
browser-signature block) **3/3**, while `claude-cli/2.1.278 (external, cli)`, a
Mozilla browser UA, `paper-agent/0.1.0`, `curl/8.5.0` and `python-requests/2.31.0`
all returned 200. The block is also intermittent — an unidentified `/v1/messages`
client took `1010` twice at 03:06–03:07 while sibling requests succeeded.

The trace entry for a refused request already carries everything *except* the
offending input:

```
{"timestamp": "2026-10-21T03:06:41Z", "event": "request", "tier": "haiku",
 "provider": "opencode-go-chat", "status": "failure", "http_status": 403,
 "retries": 0, "error": "error code: 1010\n"}
```

**The change — one field, one file, nothing on the wire.** The `request` trace
entry gains `client_user_agent`: the inbound `User-Agent` as the proxy forwards
it — resolved the way that path resolves a repeated header, so the recorded value
is the last line sent upstream — capped at 512 bytes with a visible marker,
omitted when that resolved value is empty, and recorded regardless of `--all`.

```
do_POST
  └─ trace_entry = {...}                      (server.py:3775)
     ├─ trace_entry["extra_request_headers"]  (existing: resolved OUTBOUND values)
     ├─ trace_entry["client_user_agent"]      ← NEW: the INBOUND value, as forwarded
     │     _client_user_agent(self.headers)
     │       forwarded = {k: v for k, v in headers.items()
     │                    if k.lower() == "user-agent"}   (the forwarding path's own
     │       value = list(forwarded.values())[-1]          collapse, mirrored — the
     │               if forwarded else None                last line sent upstream)
     │       absent / empty  → None              → the key is omitted, not null
     │       len(value) <= 512 → verbatim
     │       otherwise         → value[:483] + "[proxy: user-agent truncated]"
     └─ trace_entry["key"]                    (existing)
  └─ log_trace(trace_entry)  →  TraceSink._emit: json.dumps(payload) + "\n"
```

**Design decisions, and why.**

- **D1 — the field is named `client_user_agent`.** `extra_request_headers`
  records **resolved outbound** values while this field records an **inbound
  client** value; naming it `user_agent` next to that map would make the entry
  ambiguous the moment a UA override is ever added upstream of this field. The
  longer name is self-disambiguating and needs no comment to hold its meaning.
- **D2 — the truncation marker is visible.** Silent truncation would make a very
  long UA indistinguishable from a genuine one that happens to end there, and the
  repo's convention is a visible marker (`[proxy: response body truncated]`,
  `response_size_cap_exceeded`). The marker is appended to the kept head, sized
  so the stored value is **exactly** the cap — not cap-plus-marker.
- **D3 — the cap is 512 bytes.** A UA is client-controlled and otherwise
  unbounded; 512 bytes is far beyond any real UA (the longest in the measured
  evidence, `claude-cli/2.1.278 (external, cli)`, is 35) while costing almost
  nothing per entry. The number is not load-bearing — the *mechanism* is.
- **The cap is a character count that is also a byte count**, because
  `http.server` decodes header values as latin-1 (measured: a raw `0xFF` byte
  arrives as `U+00FF`). This is asserted rather than assumed — the Step-1 gate
  and the tester both feed a 600-character non-ASCII UA and check the stored
  value is exactly 512 latin-1 bytes.
- **Not gated by `--all`, following `extra_request_headers`.** The failure being
  diagnosed happens on ordinary requests; a diagnostic that requires `--all` would
  be absent exactly when it is wanted.
- **No `sanitize_error` on the field.** That chokepoint is for *error text* — it
  redacts home-directory paths and IPv4 literals and caps at 200 chars. The UA is
  the diagnostic itself; redacting parts of it defeats the point, and its own cap
  already bounds it. `extra_request_headers` values are likewise unsanitized.
- **No new trace event for truncation.** The marker in the value is
  self-describing; a new event would add a doc-table row, a consumer contract and
  a vocabulary for no diagnostic gain.
- **Only the main `trace_entry` site is extended.** The pre-routing 413 entry at
  `server.py:3741-3752` is a different, already-reduced-shape entry written before
  routing, and a client's UA cannot influence a 413. The exclusion is documented
  in `doc/trace-log.html`'s existing exception box and pinned by a test.

**The log-injection question, resolved.** The draft asked whether a consumer of
the trace could print an attacker-influenced UA into a terminal. **It cannot.**
The only committed consumer, `scripts/analyze_proxy_trace.py`, reads `event`,
`timestamp`, `provider`, `request_id`, `original_request_id`, `drain_exit`, the
chat-SSE fields, `model`, `total_latency_sec`, `retries`, `status` and
`first_byte_latency_ms` — it never reads a UA field, so this change creates no
terminal-escape path. Independently, the value cannot carry a raw escape into the
file either: `TraceSink._emit` writes `json.dumps(payload) + "\n"` with
`ensure_ascii=True` (the default), so `\x1b` becomes the six literal characters
`\u001b`, `\x00` becomes `\u0000`, an obs-fold CRLF becomes `\r\n`, and the file
stays pure ASCII with one physical line per entry. Both halves are pinned by the
tester's control-character test. Sweeping the consumers for that question did
surface a **pre-existing, unrelated** exposure in a *different* field — the
client-supplied `model` string on a pre-routing 400 is printed unescaped by the
analyzer — which is filed as
[defer-issue-analyze-trace-model-terminal-escape](./tmp/reports/defer-issue-analyze-trace-model-terminal-escape.json)
rather than fixed here.

**Alternatives considered.**
- *Rewrite or spoof the upstream UA* — rejected by the operator: it is spoofing,
  Cloudflare's `1010` keys on the whole browser signature (TLS/JA3, HTTP/2
  settings, header order) rather than the UA alone, and it carries
  terms-of-service risk. An honest-but-unusual UA already passes.
- *Echo the UA back in a response header, or change the response body* —
  rejected: a `1010` already reaches the client as `403` + `error code: 1010\n` +
  `Server: cloudflare` + `CF-RAY: <id>`; the requester already knows what it sent.
- *Retry `403`* — rejected: a `403` is a policy answer (geo and tier refusals are
  deterministic), so a retry would burn a full backoff budget to receive the same
  answer.
- *Record the UA on every trace event* — rejected: `mode_dispatch` and the retry
  events are per-pass, not per-request, and the UA is a property of the client
  request. One field, on one entry.
- *Give `client_user_agent` to the 413 entry too, for uniformity* — rejected: it
  would be a second call site for a value a 413 cannot be caused by, and the
  operator's integration table names exactly one. The exclusion is documented and
  pinned instead.
- *Store a hash, or the UA length only* — rejected: the UA string itself is the
  diagnostic; `Python-urllib/3.11` versus `claude-cli/2.1.278` is the whole
  finding, and a hash would not have made the `1010` bug legible.

**The suite's pre-existing failures, dispositioned.** Recording the baseline for
this plan surfaced that the full suite reads **420 passed / 8 failed / 428 total**
on this machine's interpreter, Python **3.14.7**. All eight share one root cause
and it is the *interpreter*, not the source: the suite's `json`-recursion fixtures
and its decode-ok/encode-fails band probes were calibrated against the Python 3.12
profile (decoder `RecursionError` near depth 16,920, encoder near 15,501), and
3.14's accelerated `json` no longer has that profile — measured on 3.14.7,
`json.loads` parses a 20,000-deep array without raising, `json.dumps` re-encodes
the loaded object without raising, and a sweep of depths 500–60,000 finds **zero**
band pairs. So five band probes fail on their own precondition guard
(`could not locate a decode-succeeds/encode-fails band on this interpreter`), one
deep-body test now gets `invalid_body_type` where it expected `invalid_json`
(because the fixture parses), and two chat-SSE tests see a deep frame delivered
where they expected it skipped or degraded. **Not a regression and not caused by
any commit** — the fixtures were correct for the interpreter they were written
against, which is still installed alongside as `python3.12`; the working
interpreter changed. Filed as
[defer-issue-suite-json-recursion-profile-py314](./tmp/reports/defer-issue-suite-json-recursion-profile-py314.json),
which also records that `CLAUDE.md`'s ceiling row and
`doc/architecture.html#error-envelope` now state a 3.12-era fact as current.
**This plan neither causes nor fixes any of it**, and the tester's failure-count
expectation is the frozen baseline of 8.

**Out of scope** (settled operator decisions and unrelated findings, deliberately
untouched):
- Any change to what the requester receives on the wire — no response-body
  change, no diagnostic response header.
- Any UA rewriting, substitution or normalization.
- Any new retry, and any change to the retry policy.
- The proxy emitting its own `Server`/`Date` alongside the forwarded upstream
  ones — [defer-issue-proxy-own-server-date-headers](./tmp/reports/defer-issue-proxy-own-server-date-headers.json).
- The analyzer's unescaped printing of a client-supplied `model` —
  [defer-issue-analyze-trace-model-terminal-escape](./tmp/reports/defer-issue-analyze-trace-model-terminal-escape.json).
- The 8 interpreter-dependent suite failures —
  [defer-issue-suite-json-recursion-profile-py314](./tmp/reports/defer-issue-suite-json-recursion-profile-py314.json).
- ~~Duplicate-`User-Agent` first-vs-last divergence between the traced and the
  forwarded value — this plan's own reviewer finding, recorded and deliberately
  **not** fixed here because it changes the field's observable content.~~
  **Reversed by operator decision: reopened and fixed in-plan** (Step 6). The
  resolution now mirrors the forwarding path's collapse, so the recorded value is
  the last line the proxy sends upstream, and the deferral was retired as
  resolved. See `## Final Results` and the Step 6 History row.

## Repo Mode

Public

*Detected at plan creation via `python3 ~/.claude/scripts/detect_repo_mode.py` → `public`.*

## Document Overrides

| Document | Rule Overridden | Reason |
|----------|----------------|--------|

No overrides. The plan contradicts no documented rule: the field is ungated by
`--all` exactly as `extra_request_headers` already is, and the docs are updated to
match rather than left behind.

## Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| The UA is client-controlled and now sits in an always-on field, so the trace grows and records text the client chose | Larger trace file; attacker-influenced text at rest | The field's **value** is bounded at 512 latin-1 bytes (a real UA is ~35 bytes), and the **file's** growth is bounded too but larger than that: `ensure_ascii=True` expands a 512-character non-ASCII UA to roughly 3 KB of JSONL, so the on-disk bound is ~6× the value bound, still bounded and still far below the bodies `--all` writes. `~/.claude/logs/` is already `chmod 0600` on POSIX, and the Windows `icacls` caveat already applies to `extra_request_headers` for the same reason. The doc note names both fields. *(Wording corrected after the Phase 6 review: the original said "bounded by the 512-byte cap", which is true of the value and understates the file's growth.)* |
| Attacker-influenced text reaching the operator's terminal | ANSI/OSC escape injection into a terminal | **Resolved, not deferred**: no committed consumer reads the field (`scripts/analyze_proxy_trace.py`'s field list does not include it), and the sink's `json.dumps(..., ensure_ascii=True)` escapes every control character and non-ASCII codepoint on disk, so `cat`/`less`/`jq` see escapes. Pinned by `test_client_user_agent_control_characters_stay_one_line`. The adjacent pre-existing exposure in the `model` field is filed as a deferral |
| The field's name becomes ambiguous if a UA override is ever added upstream of it | A future reader misreads inbound as outbound | D1's name is self-disambiguating, the constants' block comment states "records that value — the last one the forwarding path sends — never rewritten" and contrasts it with `extra_request_headers`'s resolved outbound values, and `doc/trace-log.html`'s row carries the same wording |
| The "512 bytes" cap silently becomes a 512-*character* cap if a future interpreter decodes headers as UTF-8 | The stated byte bound becomes false, and the cap silently doubles for non-ASCII | The relation is asserted rather than assumed in two places: the Step-1 gate's non-ASCII feed, and `test_client_user_agent_in_trace`'s explicit `len(got.encode("latin-1")) == 512` assertion. Both fail if the decoding ever changes |
| A future reader "fixes" the 413 entry's missing field or the missing `--all` gate as an inconsistency | An unrecorded contract change | Both are deliberate, stated in the coder guidance and in the doc, and pinned by `test_client_user_agent_ungated_and_entry_scoped` |
| A request carrying `User-Agent` in **more than one casing** puts two lines on the wire, so the single traced value names only the last of them | The field is a partial mirror for that request — but it was recorded as `one`/`a` before Step 6, which named a line the upstream never received, so the change is a strict improvement in every case | Not fixable by any single-value rule: the wire genuinely carries two values. The rule records the **last** line the forwarding path sends, which is exact whenever the request carried one casing — the ordinary case, and the only one in which "the UA" is well defined. Stated in the helper's docstring, in Step 6's table, and in `## Final Results`' known caveats. Measured by `...-duplicate-ua-probe.py`; Step 7's interleaved case pins the rule so a later "simplification" to `get_all()[-1]` cannot pass |
| A later reader "simplifies" the resolution to `headers.get_all("User-Agent")[-1]`, which reads as the same thing | The field silently goes back to naming a line that was not the last one sent, for reordered duplicates | Step 7 pins the interleaved case, which is exactly where the two rules disagree (`get_all` gives the request's last line `c`; the wire's last line is `b`) |

## Proposed Changes

Each step includes verification checks tagged with confidence (see Prime Directive 4).
`(auto)` = mechanical, coder self-verifies. `(scripted)` = deterministic multi-step, coder runs provided script.
Every step must have at least one verification check executable by its owner (coder steps: coder checks; tester steps: tester verify; planner steps: Evidence).
Steps MUST use this numbered-list format exactly. The `### Step N:` heading format is deprecated and must not be used.

1. **Step 1:** Add `CLIENT_USER_AGENT_MAX_CHARS = 512` and `CLIENT_USER_AGENT_TRUNCATION_MARKER = "[proxy: user-agent truncated]"` plus the pure helper `_client_user_agent(headers)` to `src/claude_retry_proxy/server.py` (after `_resolve_extra_request_headers`), and wire it into `do_POST`'s `trace_entry` as one None-guarded assignment immediately after the `extra_request_headers` block — the 413 literal entry, `mode_dispatch` and every other `log_trace` payload left untouched
   → coder verify (auto): the two module-level constants present with exactly those values; `text.count("def _client_user_agent(") == 1`; the helper returns `None` on the falsy path and carries `keep = CLIENT_USER_AGENT_MAX_CHARS - len(CLIENT_USER_AGENT_TRUNCATION_MARKER)`; exactly one `trace_entry["client_user_agent"] =` site, behind `if _client_ua is not None:`; `python3 -c "import claude_retry_proxy.server"` exits 0 and reports this repo's `src/` path. *(The resolution line itself was superseded by **Step 6** — it read `headers.get("User-Agent")` at this step and reads the forwarding path's collapse after it.)*
   → coder verify (scripted): `python3 ./tmp/verification/2026-10-21-trace-client-user-agent-step1.py` → exit 0 (32 checks: 12 structural + 20 algorithmic, seven of them added by Step 6). It read 10 FAIL against the pre-change tree at this step and **8 FAIL** against the Step-1 tree once the duplicate cases existed; the plan's own two code blocks are separately calibrated green through it by `...-step1-calibration.py`, which splices them into the **HEAD revision** of `server.py`
   → tester verify: the three new tests pass end-to-end, asserting on the JSONL file through a live proxy

2. **Step 2:** Pin the field end-to-end with three tests in `tests/test_trace.py` — the presence/omission/truncation matrix, the control-character single-line guarantee (including the obs-fold CRLF that only a raw socket can send), and the three deliberate boundaries (ungated by `--all`, `request`-entry-only, 413-excluded) (tester-owned; no coder work)
   → tester verify: `test_client_user_agent_in_trace`, `test_client_user_agent_control_characters_stay_one_line` and `test_client_user_agent_ungated_and_entry_scoped` all pass; `tests/test_trace.py` and the full suite each rise by exactly 3 over the recorded baseline; `test_extra_request_headers_in_trace`, `test_extra_request_headers_attach_matrix` and `test_user_agent_forwarded_all_modes` pass unchanged

3. **Step 3:** Reconcile the documentation with the landed code — `doc/trace-log.html` (the entry-schema table row, the 413 exception box, the `--all` not-gated note), `README.md` and `CLAUDE.md` (the always-on trace-field list alongside `extra_request_headers`), `doc/test-catalog.html` (the three new per-test rows and the measured suite counts) (planner-owned; no coder or tester work)
   → Evidence: `doc/trace-log.html` carries a `client_user_agent` row reading "only present when the client sent a non-empty UA", the exception box names the 413 entry, and the not-gated note names both ungated fields — evidence is a `grep -n client_user_agent doc/trace-log.html README.md CLAUDE.md doc/test-catalog.html` output showing all four files and the exact row/line text; `python3 scripts/check_doc_anchors.py` exits 0; `python3 ~/.claude/scripts/doc_structure_check.py` exits 0
4. **Step 4:** Correct the `_client_user_agent` docstring's whitespace premise in `src/claude_retry_proxy/server.py` — it currently claims the header mapping "has already stripped the surrounding whitespace of the value it holds", but only a *whitespace-only* value normalizes to `""`; trailing whitespace on a non-empty value is preserved. Comment-only, no behaviour change
   → coder verify (auto): the docstring no longer claims general surrounding-whitespace stripping; it states that a whitespace-only value arrives as `""` and that a non-empty value keeps its trailing whitespace; `python3 -c "import claude_retry_proxy.server"` exits 0; the helper's BODY is unchanged (the `if not value: return None` branch, the cap comparison and `value[:keep] + CLIENT_USER_AGENT_TRUNCATION_MARKER` are byte-identical)
   → coder verify (scripted): `python3 ./tmp/verification/2026-10-21-trace-client-user-agent-step1.py` reads **25/25 PASS, exit 0** at this step (the gate's duplicate cases did not exist yet; it is **32/32** after Step 6) — the gate asserts the rule, not the prose
   → tester verify: no behavioural change is expected; the module stays at 15 registered tests and the three client-UA tests still pass

5. **Step 5:** Fix the three review findings in `tests/test_trace.py` — make the 413 poll actually wait for the 413 entry instead of returning on an already-satisfied condition, correct the two stale line references in the `ua_of` docstring, and pin the literal `512` and `"[proxy: user-agent truncated]"` once so a constant change cannot leave three documents stale while the tests stay green (tester-owned; no coder work)
   → tester verify: `test_client_user_agent_ungated_and_entry_scoped` no longer flakes — run `tests/test_trace.py` at least **8 times** and report the pass count (it failed **2 of 8** before this fix, measured by the planner on 2026-10-21); the module reads 15/15; the three tests still pass; the suite's failure count stays at the frozen baseline of 8

6. **Step 6:** Make `_client_user_agent`'s resolution mirror the forwarding path in `src/claude_retry_proxy/server.py` — replace `value = headers.get("User-Agent")` with the same dict collapse `do_POST` hands `forward_request` (`{k: v for k, v in headers.items() if k.lower() == "user-agent"}`, then that collapse's **last** value), and update the helper's docstring and the constants' block comment to match. Comment and resolution only; the cap, marker and omit-when-empty contract are untouched, and the wire is untouched (coder-owned)
   → coder verify (auto): `grep -n "headers.get" src/claude_retry_proxy/server.py` returns **no hit inside `_client_user_agent`**; the helper carries `forwarded = {k: v for k, v in headers.items() if k.lower() == "user-agent"}` and `value = values[-1] if values else None`; `text.count("def _client_user_agent(") == 1`; `python3 -c "import claude_retry_proxy.server"` exits 0 and reports this repo's `src/` path
   → coder verify (scripted): `python3 ./tmp/verification/2026-10-21-trace-client-user-agent-step1.py` → **32/32 PASS, exit 0** (12 structural + 20 algorithmic; the algorithmic half recomputes the forwarding rule rather than restating it). Measured **8 FAIL / exit 1** against the tree carrying the Step-1 form, all eight in the duplicate-resolution dimension
   → tester verify: the Step-7 test passes, and the three shipped client-UA tests still pass — the single-header contract is unchanged

7. **Step 7:** Add one permanent test to `tests/test_trace.py` pinning the duplicate-header resolution against the **upstream's own record** — `test_client_user_agent_duplicate_headers_match_forwarded`, three raw-socket cases: same-cased duplicates (upstream receives **one** line, the traced value equals it), mixed-cased duplicates (two lines, the traced value is the last), and interleaved casings (two lines reordered to `['c', 'b']`, the traced value is `b`) (tester-owned; no coder work)
   → tester verify: `test_client_user_agent_duplicate_headers_match_forwarded` passes; `tests/test_trace.py` rises **15 → 16** and the suite **431 → 432** (measured, not inferred); the three existing client-UA tests and `test_extra_request_headers_in_trace` pass unchanged; the failure count stays at the recorded baseline of **8**. The red side was measured by the planner before Step 6 landed (the end-to-end probe scored **1/4**, the gate **8 FAIL**), so this test is expected to pass on its first run


## Guidance for Planner

Documentation tasks you will execute yourself (not the coder):

- **Files to modify:**
  - `./doc/trace-log.html`
  - `./README.md`
  - `./CLAUDE.md`
  - `./doc/test-catalog.html`
- **`.claude/mega-audit-files.json`:** does not exist in this repo — nothing to update.
- **When:** after the coder and tester finish (the prose must match the landed
  code, and the catalog must carry the tester's *measured* counts).
- **What to sync:**
  - `doc/trace-log.html` — the authoritative entry-schema surface, three edits:
    1. **The entry-schema table** (the `<tr>` list at ~lines 31–48, beside the
       `extra_request_headers` row at :47). Add a row for `client_user_agent`:
       type `string`; meaning "the client's inbound `User-Agent` as received —
       **omitted entirely** when the client sent none, and truncated to 512 bytes
       with a visible `[proxy: user-agent truncated]` marker when longer". State
       explicitly that this is the **inbound** value, unlike
       `extra_request_headers`, which records resolved **outbound** values —
       that contrast is the whole reason for the field's name.
    2. **The exception box** (~lines 51–58). It currently reads "the 'present on
       every entry' invariant above has **two** exceptions". Append the third:
       the oversized-body 413 entry, written before routing, omits
       `client_user_agent` as well as `tier` and `provider`. (The field's own
       omit-when-absent rule is a *field* condition, already stated in the table
       row, not one of these entry-shape exceptions.)
    3. **The not-gated note** (~lines 293–298, the `<div class="note">` that
       currently names only `extra_request_headers`). Name both ungated fields,
       and say why the UA is one of them: it is the diagnostic for a refusal that
       happens on ordinary requests, so gating it behind `--all` would make it
       absent exactly when it is wanted. The Windows-ACL warning at :280-291
       applies to it too — its "error text and resolved extra-header values are
       recorded regardless" clause now covers the UA as well.
  - `README.md` — the "Trace log" section's field list at **line 488-494**
    enumerates the entry's fields in prose; add `client_user_agent` there with the
    same inbound-versus-outbound distinction. The data-exposure block at
    **lines 533-539** names `extra_request_headers` as ungated; add the UA
    alongside it. Do not add a new section — this is a one-clause change in each
    of two paragraphs.
  - `CLAUDE.md` — the `--all` / `PROXY_LOG_ALL` **Gotchas** bullet
    ("`--all` / `PROXY_LOG_ALL` writes raw prompts and completions…") and the
    `extra_request_headers` sentence it ends with: name the new field alongside
    it as the second field not gated by `--all`, and note that the Windows ACL
    caveat applies to it too. **One clause; keep the bullet compact per the
    CLAUDE.md-maintenance rule, and do not delete anything.**
  - `doc/test-catalog.html` — four edits, all with the counts **taken from the
    tester's session report; do not guess them**:
    1. **Line 21-22 — the suite total.** It currently reads "**428 test functions
       across 19 files**" with a chain of prior counts ("It read *424 across 19*
       before this recount, *422 across 19* before that, …"). Update the headline
       to the new total and **prepend** `428 across 19` as the newest "before
       that" entry. Do not rewrite the chain — it is a deliberate history.
    2. **Line 142 — the per-module table row** for `test_trace.py`: its
       `<td class="num">12</td>` becomes the new module count.
    3. **Line 652 — the section heading** `<h4><code>tests/test_trace.py</code>
       (12 tests) — trace log and analysis</h4>`: same count, and add one
       `<li><code>test_x</code>: description.</li>` row for each of the three new
       tests, in the file's existing form.
    4. **Line 779 — leave alone.** The "21 long-lived spawn sites whose children
       nothing else reads … 4 in `test_trace.py`" figure counts *direct*
       `subprocess.Popen` sites in the module (verified: `tests/test_trace.py`
       lines 89, 280, 438, 741). The new tests reach the proxy through the
       `_start_mode_proxy` harness helper — which already drains its child — so
       they add no site to that list and the figure stays 4.
  - **Not in this plan:** `doc/architecture.html`, `doc/provider-modes.html`,
    `doc/operations.html`, `doc/configuration.html`, `doc/compatibility.html`.
    Nothing in this change touches their subject matter — the request path,
    retry/backoff, modes, CLI and config are all unmodified. `scripts/analyze_proxy_trace.py`'s
    `--days` help and `README.md`'s "Analyzing the trace log" section are also
    untouched: the analyzer's output does not change.
- **Deferral bookkeeping — this is where the reopen lands.** After Step 6 and
  Step 7 are verified:
  1. Move the `traced-ua-duplicate-header-first-vs-last` row to **`Resolved`**
     (date 2026-10-21; `Resolved By` = **both** the coder report and the tester
     report for the reopened rounds — the fix and its regression pin are the
     resolving artifacts, and naming the *review* would point at an instrument
     that runs after the close) and **delete
     `./tmp/reports/defer-issue-traced-ua-duplicate-header-first-vs-last.json`
     in the same act** — presence means open, so the file's deletion *is* the
     close. Use the guarded mechanics `/update-and-commit` Step 9.6 uses:
     validate the basename against `^defer-issue-[A-Za-z0-9._-]+\.json$`, resolve
     the canonical `$REPO_ROOT/tmp/reports/<basename>` path, and **check the exit
     status** — on a delete failure, keep the row `Resolved` and surface the
     failure rather than reporting a close that did not happen. Step 9.6
     tolerates an already-absent file ("the report is already retired"), so
     deleting it here does not break the later `/update-and-commit`.
  2. **The other three deferrals are untouched.** Two were filed by this plan and
     are in the `## Issue Log` (Branch A of `/defer-issue`):
     `./tmp/reports/defer-issue-proxy-own-server-date-headers.json` and
     `./tmp/reports/defer-issue-analyze-trace-model-terminal-escape.json`; the
     third is `./tmp/reports/defer-issue-suite-json-recursion-profile-py314.json`.
     None is resolved by this plan — **do not** mark the rows `Resolved` and
     **do not** delete the reports. All three are enumerated in `## Final Results`
     under their own headings so they stay visible rather than merely absent.
- **Step 6's doc reconciliation — the resolution rule is now part of the field's
  contract, so the two places that describe the value must state it.** These are
  edits to text this plan already wrote; do them **after** the coder's round, and
  only to the extent the wording has drifted:
  1. `doc/trace-log.html`, the entry-schema row for `client_user_agent`
     (`:48`). Its "the client's inbound `User-Agent` *as received*" is now
     imprecise: the value is the one the proxy **forwards**, which for a
     duplicate-header request is not necessarily the first one received. Keep the
     inbound-versus-outbound contrast (it is still the right contrast), and add
     one clause naming the rule — duplicates resolve the way the forwarding path
     resolves them, so the recorded value names the last `User-Agent` line the
     request produces upstream. Do **not** turn the row into a paragraph: the
     field is one string and this is one clause.
  2. `README.md`, the trace-log field list (`~:488`): the same clause, in the same
     one-sentence register. `CLAUDE.md`'s `--all` Gotchas bullet needs **no**
     change — it names the field and its gating, not its resolution.
  3. Do **not** document the mixed-casing residual as a feature or a caveat in the
     operator-facing docs: it is a property of a request no real client sends
     (three UA headers, alternating case), no consumer parses the field, and the
     doc's job here is to say which value is recorded. The residual is recorded in
     the plan (Step 6's table and `## Final Results`' known caveats) where a
     maintainer will find it.
  4. Re-run **both** doc gates and record their output:
     `python3 scripts/check_doc_anchors.py` and
     `python3 ~/.claude/scripts/doc_structure_check.py`.

## History

| Date | Event | Conclusion | Dismissed |
|------|-------|------------|-----------|
| 2026-10-21 | Initial plan | Restructured the operator's draft into a plan: `client_user_agent` recorded on the `request` trace entry, capped at 512 bytes with a visible marker, omitted when absent, not gated by `--all`; one field, one source file, nothing on the wire. D1/D2/D3 resolved to the draft's own recommendations. Three pre-existing side-findings routed to deferrals instead of scope. Mega-audit not triggered (3 steps, 1 source file). | — |
| 2026-10-21 | Review (Phase 6, **re-run** post-reopen) | Verdict **Issues found — non-blocking**: **0 Critical / 0 Warning / 2 Suggestion** (the pre-reopen pass read 0 / 2 / 6), plus 1 hunch and 3 areas not fully verified — report [2026-10-21-trace-client-user-agent-review-2026-10-21.json](./tmp/reports/2026-10-21-trace-client-user-agent-review-2026-10-21.json) (**overwritten** as instructed; the prior pass's findings survive verbatim in this plan's earlier History row and Dismissed cell). The reviewer did not trust the plan's claims and re-derived them: **18 raw-socket cases** against a live proxy plus a mock upstream (the planner's 4 plus obs-fold duplicates top-level and mid-list, tab-fold, three- and four-way interleaved casings, an empty final duplicate, a whitespace-only final duplicate, trailing-whitespace values, a comma-containing value, lower/upper-only names, same-value duplicates) — in **every** case the traced value equalled the upstream's *own* recorded last `user-agent` line, the sole exception being the documented one (an empty resolved value omits the field while the wire carries one empty line); it re-derived the single-header contract on the shipped helper (absent/empty/whitespace-only → `None`; exactly 512 verbatim; 513 → 483 + 29 = exactly 512 chars = 512 latin-1 bytes); it **closed the one path that could reorder the wire's UA lines** — an `extra_request_headers` rule naming `User-Agent` — via `RESERVED_EXTRA_HEADER_NAMES` at `config.py:29-34`, validated at startup and reload; it confirmed the Step-7 test is **not** self-fulfilling (it compares against `mock_servers[...]["headers"]["user-agent"]`, never a restated rule) and fails loudly on a short slice; it re-ran both doc gates (206 anchors / 9 files) and the Step-1 gate; it confirmed the static count (432 across 19, 16 in `tests/test_trace.py`) and that the server diff is exactly two hunks and the test diff three, nothing out of plan. **Prerequisite reading, recorded rather than waved through:** Phase 6 prerequisite 2 asks for a tester report with `overall_result: "SUCCESS"` and the report reads **`PARTIAL`** — read as met via the doctrine's own deferred-exemption, because the *only* `blocking_failures` entry is `pre_existing: true` (the frozen 8, a completed deferral) and this plan passed the identical gate at its pre-reopen close in that same state. **Infrastructure:** the reviewer's *first* launch died before doing any work on the same upstream provider 400 that killed this plan's coder round 1 and tester round 4 — `reasoning_content in the thinking mode must be passed back to the API`, request_id `e6caecbc-1661-4993-b07b-6072383f4cc3` — the **third occurrence today and the first to hit the reviewer**; relaunched, it completed. | Three findings, all dispositioned: **fixed by this revision** — [review-presence-wording-client-side](./tmp/reports/2026-10-21-trace-client-user-agent-review-2026-10-21.json) (Suggestion/Readability; the presence rule was stated over what the *client sent* while Step 6 moved the decision to the *resolved* value — a request sending `User-Agent: one` then an empty `User-Agent:` omits the field even though a non-empty UA was sent; the planner **re-measured the reviewer's case end-to-end itself** before acting, confirming the wire carried `['']` and the entry omitted the field, then restated the rule over the resolved value in `doc/trace-log.html:48`, `README.md:494-500` and `CLAUDE.md:272-274` and re-ran both doc gates: PASS). **Recorded, not fixed** — [review-callsite-as-received-comment](./tmp/reports/2026-10-21-trace-client-user-agent-review-2026-10-21.json) (Suggestion/Readability; the call-site comment at `server.py:3858` still opens "The client's User-Agent as received", the phrase Step 6 retired from the block comment and the doc row. The coder's report had **explicitly left it for this review to disposition**, and this is the disposition: it is a **source** file, so fixing it is the coder's lane and the planner will not write it — one comment line, flagged to the operator, and the block comment six lines above already states the correct rule, so it is a local inconsistency rather than a false contract. `doc/test-catalog.html:666` keeps the same phrasing **deliberately**, because it mirrors `test_client_user_agent_in_trace`'s own docstring and that test sends a single header, for which "as received" is exact). **Hunch recorded** — [review-empty-resolved-duplicate-unpinned](./tmp/reports/2026-10-21-trace-client-user-agent-review-2026-10-21.json) (Testability; no permanent test covers a duplicate whose *resolved* last value is empty, so that omission branch is pinned only by the gitignored Step-1 gate's `duplicate-empty-last-value-omits` check — behaviour measured correct, and closing it would need another tester round plus a re-review for a case no real client produces, so it is flagged rather than actioned). |
| 2026-10-21 | Implementation round (tester) — Step 7, round 5 (the retry of round 4) | Succeeded: **exit 0, single attempt, fresh report** (log `...-tester-2026-10-21-5.log`, terminal `exit 0` at 20:46:21, no relaunch). Step 7's test had **already landed** in the report-less round 4, so this round verified rather than re-implemented — it read the test against § Step 7 (identical, including the three-case table and the assert-against-the-upstream contract), confirmed its `ALL_TESTS` registration (`tests/test_trace.py:1734`), and measured. **Measured counts**: module `tests/test_trace.py` **16/16, exit 0**; full suite **424 passed / 8 failed / 432 total, 0 skipped** — the 431→432 and 15→16 rises the plan requires, with the failure count unchanged at the frozen baseline of 8 and none of the eight in the touched module. It independently re-ran the Step-1 gate (**32/32 PASS**) and the end-to-end probe (**4/4**, up from the 1/4 the planner measured pre-fix), and reported **no documentation discrepancy** — `doc/trace-log.html:48`, `README.md:494-500/549` and `CLAUDE.md:272-273` all match the landed behaviour. **No source, test or doc file was touched this round** (`files_modified` is its own log and this report). `overall_result: PARTIAL`, solely for the eight pre-existing failures — the same eight it re-confirmed as single-root-cause (Python 3.14's json recursion profile) and already filed as [defer-issue-suite-json-recursion-profile-py314](./tmp/reports/defer-issue-suite-json-recursion-profile-py314.json); it did not duplicate that deferral, per the dedup rule. It stated plainly that it did **not** observe the red side, as briefed, rather than claiming an observation. Report: [2026-10-21-trace-client-user-agent-tester-2026-10-21.json](./tmp/reports/2026-10-21-trace-client-user-agent-tester-2026-10-21.json). | Three out-of-scope observations, none actioned: (1) `doc/test-catalog.html` still read 431/`seventeen`/15 while this round ran — the planner's Immediate Action scheduled those bumps, and this revision applied them, so they were pending rather than stale-by-omission; (2) the eight pre-existing failures remain an Open deferral **with no owner yet**, and will keep every round's `overall_result` at PARTIAL until that work is scheduled; (3) the suite wrapper's log is rewritten per run, so the log beside the report is this round's output, not the prior one's. |
| 2026-10-21 | Environment change (deploy) — the toolchain was updated MID-SESSION at 20:22 | The operator deployed claude-config **`2fb2da9`** (committed 07:14 that morning, undeployed when this session began): both launchers, `claude_utils.py`, and all three agent doctrines. Two of its changes bind this session, and both were adapted to rather than worked around: **(1) `--operate` now requires `--project-root <path>`**, verified against the launcher's CWD *before* any lock, log or prompt — the tester's relaunch was refused **exit 2** with no `started` line until the flag was added, and the refused attempt wrote **no log and no lock**, so it consumed no round and no retry; the corrected launch used the doctrine's exact form, resolving the root inline in the same command. **(2) The plan-content `Project` line is retired** ("launch identity is explicit"), so it was removed from this plan's header — verified first that no deployed command or script parses it. The same commit also deployed the **report validity gate** (`~/.claude/scripts/report_check.py`), which the live `/update-plan` makes mandatory: run separately as `--plan` (3 plan-scoped reports) and with the adopted deferral passed explicitly, **both PASS, exit 0**. Its deferral model (a deferral is *standalone*; an adopting plan's row is the retirement trigger) is the one this revision followed when retiring `traced-ua-duplicate-header-first-vs-last`. | — |
| 2026-10-21 | Implementation round (tester) — failed round; retry used (4) | Round 4 ran ~11.5 minutes and **did the work but wrote no session report**. `tests/test_trace.py` is **+76 lines** against the round's own `.prestate` (301 → 377 added-lines vs HEAD) and is **the only file it touched** (`server.py` `+0`) — the Step-7 test landed verbatim from the plan at `:1297` and is registered in `ALL_TESTS` at `:1733`. The terminal line is `[2026-10-21 20:28:33] exit 1`, with **the child itself exiting 1** — the log carries a `started` line, so this is not a launch refusal — and the launcher printed "Report: none written since launch". Log shape: the module run, then six minutes of heartbeats (20:20:53–20:26:53), then the tally/neighbour reads at 20:28:15 and death nine seconds after the Step-1 gate returned; the same class as the two earlier report-less deaths on this plan (both upstream-provider-caused), and **the third report-less round on this plan**. **Assessed before spending the retry, per the doctrine**: the prestate delta shows the work landed, so the planner measured the landed state directly rather than trusting the dead round — module **16/16 clean, exit 0** (re-run by the planner), full suite **424 passed / 8 failed / 432 total** — exactly the predicted +1/+1 over 423/8/431, with the same eight pre-existing json-recursion failures and none of them in the touched module. **The only thing missing is the report**, so the relaunch is briefed to verify and report rather than re-implement. | — |
| 2026-10-21 | Implementation round (coder) — Step 6 | Succeeded: **exit 0, single attempt, fresh report** (round 4; log `./tmp/logs/2026-10-21-trace-client-user-agent-coder-2026-10-21-4.log`, terminal `exit 0` at 20:13:49, no relaunch). The resolution now mirrors the forwarding path — `forwarded = {k: v for k, v in headers.items() if k.lower() == "user-agent"}`, `values = list(forwarded.values())`, `value = values[-1] if values else None` — with the constants' block comment and the helper docstring updated to match. `src/claude_retry_proxy/server.py` is the only file the round touched; the diff is **+61 / −0 over HEAD** (Step 1's 48 lines plus Step 6's 13: the docstring's *Resolution* paragraph, the block comment's new clause, and the two extra resolution lines). `build_result: "pass"`, `issues_filed: []`. **Independently re-verified by the planner, not taken from the report**: the Step-1 gate reads **32/32 PASS, exit 0** (it read 8 FAIL before the round); all 44 non-blank lines of the plan's Block 1 are present verbatim in the landed helper with exactly one Block-1 candidate in the plan; `git diff` confirms the change is confined to the `_client_user_agent` block — **`fwd_headers`, `FORWARD_HEADERS`, the `do_POST` forwarding call and the call site are untouched, so the wire is unchanged**; and the end-to-end probe now reads **4/4** against a measured **1/4** before the fix (`same-case-dup` `one`→`two`, `mixed-case-dup` `one`→`two`, `mixed-interleaved` `a`→`b`, each now equal to the last line the upstream received). Report: [2026-10-21-trace-client-user-agent-coder-2026-10-21.json](./tmp/reports/2026-10-21-trace-client-user-agent-coder-2026-10-21.json). | One item considered and **left**, recorded so it is not a silent miss: the call-site comment in `do_POST` still opens "The client's User-Agent as received." Step 6's scope was the helper's docstring and the constants' block comment (both updated, and the block comment six lines above the call site now states the rule), so the phrase is a locally-true short form rather than a false claim — the value is a UA the client sent. Not worth a coder round for one comment; if the re-run review flags it as an inconsistency, it will be dispositioned there. |
| 2026-10-21 | Spec revision (/update-plan) — **reopen**, operator decision | **The plan was reopened to fix its own deferral in-plan.** The operator reversed `traced-ua-duplicate-header-first-vs-last` ("fix in plan"), so the row moves `Open` → `Fix Planned` and **Step 6** (coder: the resolution) + **Step 7** (tester: the regression test) carry it; the report is deleted when the row reaches `Resolved`. Nothing is committed (`master` @ `bf3f8f2`, six modified files), so this is a revision of an uncommitted plan, not a reopening of a closed one. **The measurement before writing anything**: `...-duplicate-ua-probe.py` sends single, same-cased, mixed-cased and interleaved-casing UA headers over raw sockets through a live proxy and reads the mock upstream's own inbound lines — the Step-1 form records `one` where the upstream received `['two']` (a UA never sent at all), and `['c', 'b']`'s last line is `b` while the request's own last UA line is `c`. That second row is the wrinkle the reviewer did not capture: **`headers.get_all(...)[-1]` is NOT a mirror** — the forwarding dict updates a key in place, so it *reorders*. Step 6 therefore mirrors the collapse itself, and the gate **recomputes** the forwarding rule instead of restating it. A single value still cannot mirror the mixed-casing case (the wire carries two lines); that residual is stated in the plan, not filed as a new deferral, per the operator's instruction that the deferral count is to go down. `steps_changed_since_audit = 4`; mega-audit entry threshold (`issues_resolved ≥ 3` **and** (`steps_changed ≥ 3` **or** `files_changed ≥ 3`)) still not met — no Issue Log row has reached `Resolved` yet, and no coder or tester file list changed. **Not triggered.** | — |
| 2026-10-21 | Implementation round (tester) — iteration 2, Step 5 | Succeeded: **exit 0 with a fresh report**. All three review findings fixed in `tests/test_trace.py` (301 insertions / 0 deletions over HEAD; the only file this round touched). **The flake is gone**: the 413 poll now waits on `http_status == 413` under a 5 s deadline instead of calling `_wait_for_trace_events(trace_file, "request")`, and the module ran **16/16 clean** where the planner had measured **6/8** before the fix; the planner independently re-ran it **4/4 clean** afterwards. The two stale line references were replaced by a code-shape description, and the documented literals `512` and `"[proxy: user-agent truncated]"` are now pinned at module level and asserted against the server constants — with a **negative control** that monkeypatches the constant to 1024 and confirms the assertion fires loudly before any proxy spawns (the reviewer's exact concern: a constant change could have kept every test green while three documents went stale). Full suite **423 passed / 8 failed / 431 total**, unchanged from the previous round and exactly the frozen baseline; none of the 8 is in the touched module. `overall_result: PARTIAL`, solely for those eight. Report: [2026-10-21-trace-client-user-agent-tester-2026-10-21.json](./tmp/reports/2026-10-21-trace-client-user-agent-tester-2026-10-21.json). | One reported deviation, accepted: `_wait_for_trace_events` was dropped from the `_harness` import block because the corrected poll no longer calls it and it had no other use in the file — left in place it would have been an unused import. Three out-of-scope observations, none actioned: the module-scope `REQUEST_BODY`/`PINNED_*` names follow the file's existing idiom; the ungated test still assumes `PROXY_LOG_ALL` is unset and fails loudly rather than silently if it is; the 413 wait's 5 s deadline is generous against a measured sub-100 ms write. |
| 2026-10-21 | Implementation round (coder) — iteration 2, Step 4 | Succeeded: **exit 0 with a fresh report**. The `_client_user_agent` docstring's premise was narrowed to the parser's real behaviour — it now reads "The parser strips a header's leading whitespace and normalizes a whitespace-only header to `\"\"`, so such a header is omitted rather than recorded as blank; a non-empty value keeps its trailing whitespace" — replacing the over-broad "has already stripped the surrounding whitespace of the value it holds". **Comment-only**: the helper body is byte-identical (the `if not value: return None` branch, the cap comparison and `value[:keep] + CLIENT_USER_AGENT_TRUNCATION_MARKER` all unchanged), and the Step-1 gate re-reads **25/25 PASS, exit 0** — it asserts the rule, not the prose. Report: [2026-10-21-trace-client-user-agent-coder-2026-10-21.json](./tmp/reports/2026-10-21-trace-client-user-agent-coder-2026-10-21.json). | — |
| 2026-10-21 | Spec revision (/update-plan) — post-review | Opened **iteration 2** for four of the review's eight findings, after measuring one of them: the review's Warning 1 (`review-413-poll-noop`) is **not theoretical**. Repeated `python3 tests/test_trace.py` runs read **2 failures in 8** — always `client-user-agent-ungated-and-entry-scoped`, the test whose 413 poll returns on an already-satisfied condition — so a flaky test is in the committed suite and must be fixed rather than merely recorded. Revision adds **Step 4** (coder: narrow the helper docstring's whitespace premise, comment-only) and **Step 5** (tester: make the 413 poll actually wait, correct the two stale line references, pin the two literals). `steps_changed_since_audit = 2`; mega-audit still not triggered. The remaining findings keep their dispositions: `review-duplicate-ua-first-vs-last` deferred (it changes observable content), `review-marker-uniqueness` recorded. | — |
| 2026-10-21 | Review (Phase 6) | Verdict **Issues found — non-blocking**: **0 Critical** / 2 Warning / 6 Suggestion, plus 2 hunches and 3 areas not fully verified — report [2026-10-21-trace-client-user-agent-review-2026-10-21.json](./tmp/reports/2026-10-21-trace-client-user-agent-review-2026-10-21.json). The reviewer worked adversarially and **re-derived every transport claim against the running interpreter** rather than accepting the plan's: it independently confirmed latin-1 header decoding (`http.client._parse_header_lines` is iso-8859-1; raw `0xFF`→U+00FF), obs-fold yielding `'foldhead\\r\\n foldtail'`, whitespace-only headers normalizing to `""`, case-insensitive lookup, `json.dumps(ensure_ascii=True)` escaping NUL/ESC/BEL/C1-CSI/CRLF **and lone surrogates**, the exact `483 + 29 = 512` arithmetic with no marker loss or duplication, that no path can emit a `null` or empty-string value, and that `scripts/analyze_proxy_trace.py` has **zero** UA references. It also re-ran the gates: Step-1 **25/25 PASS exit 0**, `check_doc_anchors.py` PASS, `doc_structure_check.py` PASS, and all 44 non-blank lines of the plan's two code blocks present verbatim in `server.py`. Its process note: the surviving findings are "in documentation accuracy and in one test's synchronization, not in the field's logic; another round would be unlikely to surface a correctness defect in the source." **Four of the eight were fixed by this revision** (all documentation, all planner-owned — see Dismissed) and one became a deferral. | Nine findings, dispositions given: **fixed by this revision** — `review-ua-superlative-false` (Warning; the false claim that `client_user_agent` is "the one field whose value the *client* chooses" — corrected in all three files to name `method`/`path`/`model`/`extra_request_headers` as equally client-derived), `review-readme-413-contradiction` ("Every request also logs" → "Every routed request", with the 413 exception stated), `review-catalog-drift-counter` ("sixteen times" → "seventeen", the 17th stale total having been prepended by this plan), `review-jsonl-size-wording` (hunch; the Risks row said "bounded by the 512-byte cap", true of the value and understating the JSONL's ~3 KB worst case). **Deferred** — `review-duplicate-ua-first-vs-last` (Suggestion/Correctness; changes observable field content, so fixing it post-review would invalidate the review — filed as [defer-issue-traced-ua-duplicate-header-first-vs-last](./tmp/reports/defer-issue-traced-ua-duplicate-header-first-vs-last.json)). **Recorded, not fixed — presented to the operator and each cheap if wanted**: [review-413-poll-noop](./tmp/reports/2026-10-21-trace-client-user-agent-review-2026-10-21.json) (Warning; the 413 poll is a no-op because `_wait_for_trace_events` returns as soon as *any* request event exists and part (a) already wrote one — a latent flake, provable by reading, un-reproduced in 3 runs), [review-stale-line-refs](./tmp/reports/2026-10-21-trace-client-user-agent-review-2026-10-21.json) (two line numbers in a test docstring moved by this change's own insertion), [review-strip-premise-overbroad](./tmp/reports/2026-10-21-trace-client-user-agent-review-2026-10-21.json) (the helper docstring's whitespace-stripping premise is broader than the parser: trailing whitespace on a non-empty value is preserved), [review-literals-unpinned](./tmp/reports/2026-10-21-trace-client-user-agent-review-2026-10-21.json) (the tests read the cap and marker from the module, so the documented literals are pinned only by the gitignored gate), [review-marker-uniqueness](./tmp/reports/2026-10-21-trace-client-user-agent-review-2026-10-21.json) (hunch; a client-supplied marker inside the kept head could appear twice — contrived, no consumer parses it). Not re-derived in the reviewer's lane: the full-suite counts (taken from the tester report; the three new tests were exercised individually and all passed) and the calibration script's recorded green (it refuses to run against a tree already carrying the change; the verbatim-block check was substituted). |
| 2026-10-21 | Implementation round (tester) — round 2 (retry) | Succeeded: **exit 0 with a fresh report**. Step 2 landed as three permanent tests in `tests/test_trace.py` (**274 insertions / 0 deletions** — pure addition, so nothing was retired): `test_client_user_agent_in_trace`, `test_client_user_agent_control_characters_stay_one_line`, `test_client_user_agent_ungated_and_entry_scoped`. Module `tests/test_trace.py` reads **15/15**, registered count 12 → 15. Full suite **423 passed / 8 failed / 431 total** — measured movement **+3 passed / +3 total over the recorded baseline (420/8/428), failure count unchanged at the frozen 8**, exactly as the plan predicted. `overall_result: PARTIAL`, solely because those eight non-skipped tests fail; they are the plan's frozen pre-existing baseline (interpreter-caused, one root cause, already deferred) and **none is in the touched module** — the tester independently re-confirmed the same eight names and single root cause. Neighbours that must keep passing did (`test_extra_request_headers_in_trace`, `extra-request-headers-attach-matrix`, `user-agent-forwarded-all-modes`). No temporary tests created, promoted or removed; none skipped. Report: [2026-10-21-trace-client-user-agent-tester-2026-10-21.json](./tmp/reports/2026-10-21-trace-client-user-agent-tester-2026-10-21.json). | Two acknowledged observations, neither a defect and neither actioned: (1) the ungated test assumes the ambient environment does not export `PROXY_LOG_ALL=1`, and fails **loudly** with its own explicit message if it does — the trade-off the plan chose over a silent pass; (2) `doc/trace-log.html` still says the entry-shape exception list has two exceptions while the new tests pin a third (the 413 entry) — that is this plan's Step 3, pending, not a discrepancy. Also noted, not actioned: the tester persisted its suite output at `./tmp/verification/2026-10-21-trace-client-user-agent-suite.log` (runner `...-suite.py`) because the Bash tool truncates long output and the tally would otherwise be lost. |
| 2026-10-21 | Implementation round (tester) — failed round; retry used (1) | Round 1 stopped **60 s in with nothing landed**: `git status` shows only the coder's `M src/claude_retry_proxy/server.py`, no test file touched, **no session report**. Cause, from the round's own transcript tail: the **same upstream provider 400** that killed the coder's first round — `invalid_request_error: The reasoning_content in the thinking mode must be passed back to the API` (request_id `d522d586-db10-4cfd-ad5e-9b2fa79555fa`) — in a different role's session. **This is the second occurrence of the same infrastructure failure across two rounds and two roles**, so it is flagged for the operator in `## Final Results`; it is intermittent rather than deterministic, since the coder's own retry ran clean end-to-end on the same provider minutes earlier. Assessed before spending the retry: the tree carries no partial tester work, so the retry starts from scratch. Brief in `## Immediate Actions`. | — |
| 2026-10-21 | Implementation round (coder) — round 2 (retry) | Succeeded: **exit 0 with a fresh report**, `build_result: "pass"`, `issues_filed: []`, one file changed. Re-confirmed the landed tree rather than re-editing it — both edits still match the plan's code blocks byte-for-byte (constants at `server.py:938-939`, helper at `:942-966`, call site at `:3849-3851`; diff **47 insertions / 0 deletions**), the auto checks pass, `python3 -c "import claude_retry_proxy.server as s; print(s.__file__)"` exits 0 reporting this repo's `src/` path (editable install intact), and **no test or doc file was touched**. The Step-1 gate was not re-run per the brief; its recorded result against this exact tree is **25/25 PASS, exit 0**. Report: [2026-10-21-trace-client-user-agent-coder-2026-10-21.json](./tmp/reports/2026-10-21-trace-client-user-agent-coder-2026-10-21.json). No new defects observed. | — |
| 2026-10-21 | Implementation round (coder) — failed round; retry used (1) | Round 1 landed BOTH Step-1 edits byte-exactly (47 insertions / 0 deletions in `src/claude_retry_proxy/server.py`, no test or doc file touched) and then died 65 s in with **no session report**. Cause, from the round's own transcript tail: an **upstream provider 400** — `invalid_request_error: The reasoning_content in the thinking mode must be passed back to the API` (request_id `cff9062b-f5d1-4db4-90a0-edae61cee9f1`) — an infrastructure failure in the coder's own provider session, not a plan or code defect. Assessed before spending the retry: tree diffed against the round's `.prestate`, both edits match the plan's code blocks byte-for-byte, and the planner re-ran the Step-1 gate against the landed tree — **25/25 PASS, exit 0**. Retry briefed in `## Immediate Actions`: the code is done, only the report remains. | — |
| 2026-10-21 | Baseline measurement (planner) | Recorded the clean-tree suite baseline — **420 passed / 8 failed / 428 total** on Python 3.14.7 — and diagnosed all 8 failures to a single root cause: the interpreter's `json` recursion profile no longer has the decode-ok/encode-fails band the tests probe, nor the ~16,920-depth decoder ceiling the deep fixtures rely on. Verified by direct probe (`json.loads` handles depth 20,000; `json.dumps` re-encodes it; zero band pairs across depths 500–60,000) and by the fixtures being green on the 3.12 env still installed alongside. Filed as a deferral; the plan neither causes nor fixes it. The tester's failure-count expectation is frozen at the baseline 8. | — |

## Plan Metadata

```json
{
  "plan_id": "2026-10-21-trace-client-user-agent",
  "steps": [
    "Step 1: Add CLIENT_USER_AGENT_MAX_CHARS and CLIENT_USER_AGENT_TRUNCATION_MARKER plus the pure helper _client_user_agent(headers) to src/claude_retry_proxy/server.py and wire it into do_POST's trace_entry as one None-guarded assignment",
    "Step 2: Pin the field end-to-end with three tests in tests/test_trace.py",
    "Step 3: Reconcile doc/trace-log.html, README.md, CLAUDE.md and doc/test-catalog.html with the landed code",
    "Step 4: Correct the _client_user_agent docstring's whitespace premise in src/claude_retry_proxy/server.py",
    "Step 5: Fix the three review findings in tests/test_trace.py — the no-op 413 poll, the stale line references, and the unpinned literals",
    "Step 6: Make _client_user_agent's resolution mirror the forwarding path in src/claude_retry_proxy/server.py — the same dict collapse do_POST hands forward_request, then that collapse's last value — updating the docstring and block comment to match",
    "Step 7: Add one permanent test to tests/test_trace.py pinning the duplicate-header resolution against the upstream's own record (same-cased, mixed-cased and interleaved-casing cases, over a raw socket)"
  ],
  "coder_files": ["src/claude_retry_proxy/server.py"],
  "tester_files": ["tests/test_trace.py"],
  "doc_files": ["./doc/trace-log.html", "./README.md", "./CLAUDE.md", "./doc/test-catalog.html"],
  "verification_scripts": ["./tmp/verification/2026-10-21-trace-client-user-agent-step1.py", "./tmp/verification/2026-10-21-trace-client-user-agent-step1-calibration.py", "./tmp/verification/2026-10-21-trace-client-user-agent-step5.py", "./tmp/verification/2026-10-21-trace-client-user-agent-flake.py", "./tmp/verification/2026-10-21-trace-client-user-agent-suite.py", "./tmp/verification/2026-10-21-trace-client-user-agent-duplicate-ua-probe.py"],
  "repo_mode": "Public",
  "document_overrides": []
}
```

## Audit Accumulation

| Counter | Value | Last Updated |
|---------|-------|--------------|
| issues_resolved_since_audit | 1 | 2026-10-21 |
| steps_changed_since_audit | 4 | 2026-10-21 |
| files_changed_since_audit | 0 | 2026-10-21 |

Neither revision changed a coder or tester file list. The first changed no step;
the second added two (**Steps 4 and 5**, the Phase 6 review's fixable findings);
the third added two more (**Steps 6 and 7**, the reopened duplicate-header fix),
giving `steps_changed_since_audit = 4`. This revision changes no step and no file
list — it moves one Issue Log row to `Resolved` (one step, +1) and retires the
report — so **`issues_resolved_since_audit` is now 1**. Mega-audit entry
threshold (`issues_resolved ≥ 3` **and** (`steps_changed ≥ 3` **or**
`files_changed ≥ 3`)) still **not met — not triggered**: the conjunction fails on
its first term whatever the step count, and the *plan-size* threshold in Phase 4.5
(≥5 steps **or** ≥5 source files) is a **write-time** trigger that was not met
when the plan was written (3 steps, 1 source file) — an `/update-plan` revision is
governed by this accumulation gate instead, which is what is applied here. The
plan now carries **7 steps**, which a reviewer should read as the outcome of three
revisions, not as a plan that evaded its audit: the added work is two review
findings and one in-plan fix, each individually small and each verified by its own
gate.

## Documentation

All four surfaces are reconciled with the **landed post-Step-6 code** and both doc
gates PASS after the final edit (`check_doc_anchors.py`: 206 anchors resolved, no
secret shapes; `doc_structure_check.py`: 9 files, no violations).

- `doc/trace-log.html` — the `client_user_agent` row in the entry-schema table
  (inbound-vs-outbound against `extra_request_headers`, the 512-byte cap and
  marker, the omit-when-unsent rule, and now the **resolution rule** — "as
  forwarded" plus "a repeated header resolves to the last line the proxy sends
  upstream"), the 413 exclusion in the reduced-shape exception box, the not-gated
  note naming both ungated fields, and the client-derived-text caution naming
  `method`/`path`/`model`/`extra_request_headers` alongside it.
- `README.md` — the trace-log field list ("Every **routed** request", the 413
  exception, and the repeated-header rule stated in one sentence so the field
  still reads as naming the UA that produced the response) and the `--all`
  data-exposure block.
- `CLAUDE.md` — the `--all` Gotchas bullet's always-on-field clause: both ungated
  fields, the repeated-header rule in one clause, nothing deleted.
- `doc/test-catalog.html` — the three original per-test rows **plus one for the
  Step-7 test**, the suite total 431 → **432** with `431 across 19` prepended to
  the count chain, `test_trace.py` 15 → **16** in both the table row and the
  section heading, and the drift counter "seventeen" → "**eighteen**" (the 18th
  stale total being the one this plan prepended). All counts are the tester's
  **measured** figures (432 total / 424 passed / 8 failed; module 16/16).

**Not documented, deliberately.** The multi-casing residual — a request carrying
`User-Agent` in two casings puts two lines on the wire, so the single traced value
names only the last — is recorded in the plan (Step 6's table, `## Risks`, and
`## Final Results`' known caveats) but **not** in the operator-facing docs. The
docs' job here is to say which value is recorded, and they now say it exactly; the
residual is a property of a request no real client sends, and no consumer parses
the field.

- `doc/trace-log.html` — the `client_user_agent` row in the entry-schema table
  (inbound-vs-outbound against `extra_request_headers`, the 512-byte cap and
  marker, the omit-when-unsent rule), the 413 exclusion added to the reduced-shape
  exception box, the not-gated note now naming both ungated fields, and the
  client-derived-text caution corrected to name `method`/`path`/`model`/
  `extra_request_headers` alongside it. Last-updated bumped to 2026-10-21.
- `README.md` — the trace-log field list ("Every **routed** request", with the 413
  exception stated) and the `--all` data-exposure block.
- `CLAUDE.md` — the `--all` Gotchas bullet's always-on-field clause, naming both
  ungated fields and keeping the bullet compact (nothing was deleted).
- `doc/test-catalog.html` — three per-test rows for the new tests, the suite total
  428 → 431 with `428 across 19` prepended to the count chain, `test_trace.py`
  12 → 15 in both the table row and the section heading, and the drift counter
  corrected to "seventeen times". Last-updated bumped to 2026-10-21.

## Final Results

**Status: COMPLETED** — 2026-10-21, **post-reopen**. The plan was completed and
reviewed earlier the same day, reopened by operator decision to fix its own
deferral in-plan, and completed again; the pre-reopen readings are preserved in
the `## History` rows and the review's Dismissed cells, and are **replaced** here.

**Outcome.** The `request` trace entry records `client_user_agent`: the client's
`User-Agent` **as the proxy forwards it** — the same value the forwarding path
puts on the wire, resolved the way that path resolves duplicates — capped at 512
bytes with a visible `[proxy: user-agent truncated]` marker, omitted when the
resolved value is empty, and recorded regardless of `--all`. The wire is
untouched — no request-header change, no response change, no new retry, no
retry-policy change — exactly the four settled operator decisions the draft
recorded. The problem it solves is concrete: a burst of `403 error code: 1010`
(Cloudflare's browser-signature block) on 2026-10-21 took a controlled
one-header-at-a-time experiment to diagnose, because the trace carried everything
about the refused request *except* the input that caused the refusal.

The reopen closed the field's one fidelity defect: the first form resolved the
header with `Message.get`, which returns the **first** of a set of same-cased
duplicates — a UA the upstream never received at all. Measured over raw sockets
through a live proxy, against the mock upstream's **own** record of the lines it
received:

| request's UA headers | traced, pre-fix | traced, post-fix | upstream received |
|---|---|---|---|
| `User-Agent: solo/1.0` | `solo/1.0` | `solo/1.0` | `['solo/1.0']` |
| `User-Agent: one`, `User-Agent: two` | `one` | **`two`** | `['two']` |
| `User-Agent: one`, `user-agent: two` | `one` | **`two`** | `['one', 'two']` |
| `User-Agent: a`, `user-agent: b`, `User-Agent: c` | `a` | **`b`** | `['c', 'b']` |

The probe scored **1/4 → 4/4**. Row 4 is why the fix mirrors the forwarding
*pipeline* rather than the request: the collapse updates a key in place, so it
**reorders**, and `get_all(...)[-1]` (the request's own last line, `c`) is not the
wire's last line (`b`).

**Outcome.** The `request` trace entry now records `client_user_agent`: the
client's inbound `User-Agent` exactly as received, capped at 512 bytes with a
visible `[proxy: user-agent truncated]` marker, omitted entirely when the client
sent none (or sent only whitespace), and recorded regardless of `--all`. The wire
is untouched — no request-header change, no response change, no new retry, no
retry-policy change — exactly the four settled operator decisions the draft
recorded. The problem it solves is concrete: a burst of `403 error code: 1010`
(Cloudflare's browser-signature block) on 2026-10-21 took a controlled
one-header-at-a-time experiment to diagnose, because the trace carried everything
about the refused request *except* the input that caused the refusal.

**Landed.**

| File | Change |
|------|--------|
| `src/claude_retry_proxy/server.py` | +61 / −0 — two module-level constants, the pure helper `_client_user_agent(headers)` after `_resolve_extra_request_headers` (its resolution now mirroring the forwarding path's own collapse), and one None-guarded assignment in `do_POST`'s `trace_entry` |
| `tests/test_trace.py` | +377 / −0 — four permanent tests, registered in `ALL_TESTS` (module 12 → 16) |
| `doc/trace-log.html` | entry-schema row (inbound-as-forwarded, the repeated-header resolution rule), the 413 exclusion in the exception box, the not-gated note naming both ungated fields, and the client-derived-text caution |
| `README.md` | the trace-log field list (the 413 exception, the repeated-header rule, the resolved-value presence rule) and the data-exposure block |
| `CLAUDE.md` | the `--all` Gotchas bullet's always-on-field clause |
| `doc/test-catalog.html` | four per-test rows, the counts 432 / 16, and the drift-counter fix |

Six files, **500 insertions / 23 deletions** (407 / 23 at the pre-reopen close;
the reopen added 13 source lines, 76 test lines and 4 doc lines). The change is
one field on one entry; the rest is the test net and the documentation that
describes it.

**Verification.**

- **Step-1 gate** `./tmp/verification/2026-10-21-trace-client-user-agent-step1.py`
  — **32/32 PASS, exit 0** against the shipped tree (12 structural + 20
  algorithmic), re-run by the planner, the tester and the reviewer. Its duplicate
  half **recomputes** the forwarding rule (`wire_ua_lines()`) instead of restating
  it, so the gate and the forwarding path cannot drift apart; the interleaved case
  is the one that fails on a `get_all(...)[-1]` lookalike. It read **8 FAIL**
  against the tree carrying the Step-1 form — the calibration that made the
  reopen's red side measurable — and the plan's own two code blocks are proven
  green through it by `...-step1-calibration.py`, which extracts them **from the
  plan file** and splices them into the **HEAD** revision (so the instrument
  survives the change landing).
- **`tests/test_trace.py`** — **16/16, exit 0**, measured by the tester and
  independently by the planner. The new case reports `the traced value is the
  last line forwarded`.
- **Full suite** — **424 passed / 8 failed / 432 total, 0 skipped**, measured by
  the tester and cross-checked by the planner. Movement over the clean-tree
  baseline (`420/8/428`): **+4 passed, +4 total, failure count unchanged** — the
  eight are the frozen pre-existing interpreter failures and **none is in the
  touched module**.
- **End-to-end probe** `...-duplicate-ua-probe.py` — **4/4**, against a measured
  **1/4** before the fix.
- **Doc gates** — `scripts/check_doc_anchors.py` PASS (206 anchors resolved, no
  secret shapes); `doc_structure_check.py` PASS (9 files, no violations). Both
  re-run **after** the re-run review's wording fix.
- **Report validity gate** — `~/.claude/scripts/report_check.py`, deployed
  mid-session with the new doctrine and mandatory under the live `/update-plan`:
  PASS on both invocation forms (`--plan`, 3 plan-scoped reports; and with the
  adopted deferral passed explicitly).

**Review (Phase 6, re-run post-reopen).** Verdict **Issues found — non-blocking**:
**0 Critical**, **0 Warning**, **2 Suggestion**, plus 1 hunch and 3 areas not fully
verified. Report:
`./tmp/reports/2026-10-21-trace-client-user-agent-review-2026-10-21.json`
(overwritten by the re-run, as instructed). The pre-reopen pass read 0 / 2 / 6;
its findings and their dispositions survive verbatim in this plan's earlier
History row.

The reviewer did not trust the plan and re-derived the load-bearing claim: a live
proxy plus a mock upstream over **18 raw-socket cases** — the planner's four plus
obs-fold duplicates (top-level and mid-list), tab-fold, three- and four-way
interleaved casings, an empty final duplicate, a whitespace-only final duplicate,
trailing-whitespace values, a comma-containing value, lower/upper-only names and
same-value duplicates. In **every** case the traced value equalled the upstream's
own recorded last `user-agent` line; the sole exception is the documented one (an
empty resolved value omits the field while the wire carries one empty line). It
re-derived the single-header contract on the shipped helper (absent/empty/
whitespace-only → `None`; exactly 512 verbatim; 513 → 483 + 29 = exactly 512
chars = 512 latin-1 bytes; 600 non-ASCII chars → 512 / 512), and it **closed the
one path that could reorder the wire's UA lines** — a config `extra_request_headers`
rule naming `User-Agent` — via `RESERVED_EXTRA_HEADER_NAMES` at `config.py:29-34`,
validated at both startup and reload. It confirmed the new test is **not**
self-fulfilling (it compares against `mock_servers[...]["headers"]["user-agent"]`,
never a restated rule) and fails loudly on a short slice, re-ran both doc gates and
the Step-1 gate, verified the static counts (432 across 19; 16 in
`tests/test_trace.py`), and confirmed the diff is confined to plan scope (server:
two hunks; tests: three).

**How the three findings were dispositioned — nothing blocks, and none is silent.**

*Fixed, in this plan* — **`review-presence-wording-client-side`** (Suggestion/
Readability): the presence rule was stated over what the *client sent* while
Step 6 moved the decision to the *resolved* value, so a request sending
`User-Agent: one` followed by an empty `User-Agent:` omits the field even though a
non-empty UA was sent. The planner **re-measured the reviewer's case end-to-end
itself** before acting — the wire carried `['']`, the entry omitted the field —
then restated the rule over the resolved value in `doc/trace-log.html:48`,
`README.md:494-500` and `CLAUDE.md:272-274`, and re-ran both doc gates: PASS.

*Recorded, not fixed* — **`review-callsite-as-received-comment`** (Suggestion/
Readability): the call-site comment at `server.py:3858` still opens "The client's
User-Agent as received", the phrase Step 6 retired from the block comment and the
doc row. The coder's Step-6 report had explicitly left this for the re-run review
to disposition, and this is the disposition: it is a **source** file, fixing it is
the coder's lane, and the planner does not write source. One comment line; the
block comment six lines above states the correct rule, so it is a local
inconsistency rather than a false contract. **Flagged to the operator.**
`doc/test-catalog.html:666` keeps the same phrasing **deliberately** — it mirrors
`test_client_user_agent_in_trace`'s own docstring, and that test sends a single
header, for which "as received" is exact.

*Hunch recorded* — **`review-empty-resolved-duplicate-unpinned`** (Testability):
no permanent test covers a duplicate whose *resolved* last value is empty, so that
omission branch is pinned only by the gitignored Step-1 gate's
`duplicate-empty-last-value-omits` check. Behaviour is measured correct; closing
it would need another tester round plus a re-review for a case no real client
produces, so it is flagged rather than actioned.

**Deferred issues (three `Open` — a deferral is a completed disposition, not
unfinished work).** A **fourth** was retired by this plan: see below.

1. **[defer-issue-suite-json-recursion-profile-py314](./tmp/reports/defer-issue-suite-json-recursion-profile-py314.json)**
   — the suite's 8 failures on Python 3.14.7. Pre-existing, interpreter-caused,
   and not this plan's: the fixtures and band probes were calibrated against the
   3.12 recursion profile (decoder ≈16,920 / encoder ≈15,501), and 3.14's
   accelerated `json` has no such band — measured, `json.loads` parses a
   20,000-deep array and `json.dumps` re-encodes it, with zero band pairs across
   depths 500–60,000. The deferral also records that `CLAUDE.md`'s ceiling row and
   `doc/architecture.html#error-envelope` state the 3.12-era numbers as current;
   those were left alone because replacing a stale number with an unmeasured one
   is worse. The tester re-confirmed the same eight names and single root cause
   in the reopened round.

2. **[defer-issue-analyze-trace-model-terminal-escape](./tmp/reports/defer-issue-analyze-trace-model-terminal-escape.json)**
   — `scripts/analyze_proxy_trace.py` prints the client-supplied `model` string
   into a terminal unescaped on the pre-routing rejection paths. Found while
   resolving this plan's own log-injection question (whose answer for the *new*
   field is a clean no: no consumer reads it, and the sink escapes everything on
   disk). Pre-existing and in a different field.

3. **[defer-issue-proxy-own-server-date-headers](./tmp/reports/defer-issue-proxy-own-server-date-headers.json)**
   — the draft's "Separate item": the proxy emits its own
   `Server: BaseHTTP/0.6 Python/<version>` and `Date` alongside the forwarded
   upstream ones, duplicating both and disclosing the Python version. The
   deferral carries the operator's critical constraint **verbatim**: the fix must
   suppress only the proxy's *own* auto-emitted headers and must **not** stop
   forwarding the upstream's `Server` — `Server: cloudflare` is the evidence that
   a refusal came from the edge, and it is what made the `1010` finding legible.

**Retired in this plan.**
`defer-issue-traced-ua-duplicate-header-first-vs-last` — this plan's **own**
artifact, found by its first review, deferred while its fix would have invalidated
that review, then **reopened and fixed in-plan** by operator decision. The Issue
Log row is `Resolved` (`Resolved By` = the coder's Step-6 report and the tester's
Step-7 report) and the report file is **deleted** — presence means open, so the
deletion *is* the close. The fix is Step 6 (the resolution mirrors the forwarding
path) plus Step 7 (the regression test); the measurements are in the table above.

**Known caveats.**
- **A duplicated UA header cannot always be fully mirrored.** A request carrying
  `User-Agent` in **more than one casing** puts two lines on the wire, so the
  single traced value names only the **last** of them. That is a strict
  improvement on the pre-fix behaviour (which named the *first* line, a value the
  upstream never received) and it is exact whenever the request carried one casing
  — the ordinary case, and the only one in which "the UA" is well defined. Stated
  in the helper's docstring, in Step 6's table and `## Risks`; deliberately **not**
  in the operator-facing docs, whose job is to say which value is recorded.
- **`review-callsite-as-received-comment` is open.** One source comment line; the
  planner cannot write it. See the disposition above.
- **`review-empty-resolved-duplicate-unpinned` is open.** The omission branch for
  an empty *resolved* value is pinned by the plan's gate, not by the permanent
  suite.
- The field's content is client-controlled raw text. It is the diagnostic, so it
  is recorded rather than sanitized — and the docs now say plainly that it is not
  the only such field.
- The 512-byte bound rests on `http.server` decoding header values as latin-1, so
  one character is one byte. That coupling is *asserted*, not assumed: both the
  Step-1 gate and the shipped test feed a 600-character non-ASCII UA and check the
  stored value is exactly 512 latin-1 bytes, so a future interpreter switching to
  UTF-8 fails loudly instead of silently halving the cap.
- The on-disk cost is larger than the value bound: `ensure_ascii=True` expands a
  512-character non-ASCII UA to roughly 3 KB of JSONL. The Risks table states both
  bounds.
- The tester reported one deliberate deviation, accepted: `_wait_for_trace_events`
  was dropped from the `_harness` import block in `tests/test_trace.py`, because
  the corrected 413 poll no longer calls it and it had no other use there.
- **Process: the toolchain was redeployed mid-session** (claude-config
  `2fb2da9`, 20:22), which required adapting the launch form (`--project-root`)
  and removing the then-retired plan-content `Project` line. See the `## History`.
- **Process: three rounds died report-less on the same upstream provider 400**
  (`reasoning_content in the thinking mode must be passed back to the API`) —
  the coder's round 1, the tester's round 4, and the reviewer's first launch. Each
  was assessed and recovered (retry, or relaunch for the reviewer); the failures
  are infrastructure, not plan or code. **Flagged for the operator**: it is the
  same provider fault on every role and it is intermittent, not deterministic.

**Audit scope.** The mega-audit entry threshold (≥5 steps **or** ≥5 source files)
was **not** met at plan time (3 steps, 1 source file); the `/update-plan`
accumulation gate — `issues_resolved ≥ 3` **and** (`steps_changed ≥ 3` **or**
`files_changed ≥ 3`) — was never met either (it reached 1 resolved / 4 steps / 0
files, failing on the first term), so the mega-audit was **not triggered** at any
revision. The plan now carries **7 steps**, all verified by their own gates and
examined by two review passes.

**Next.** `/update-and-commit` — to reconcile and commit. **Not run by this
session**, by operator instruction: the tree is deliberately left uncommitted and
the commit remains the operator's call.