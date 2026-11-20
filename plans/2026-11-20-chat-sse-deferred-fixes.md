# Plan: Fix the deferred chat_sse.py defects (shape guard, counter, late frames, comment)

**Plan ID:** 2026-11-20-chat-sse-deferred-fixes
**Created:** 2026-11-20

## Immediate Actions

*(none — all steps and review follow-ups complete; plan finalized, awaiting user approval)*

## Issue Log

## Issue Log

| Issue | Status | Found | Resolved | Resolved By |
|-------|--------|-------|----------|-------------|
| [on-done-stale-comment](./tmp/reports/2026-11-20-chat-sse-deferred-fixes-review-2026-11-20.json) | Resolved | 2026-11-20 | 2026-11-20 | [tester](./tmp/reports/2026-11-20-chat-sse-deferred-fixes-tester-2026-11-20-2.json) |
| [coalesced-test-fixture-nondeterministic](./tmp/reports/2026-11-20-chat-sse-deferred-fixes-review-2026-11-20.json) | Resolved | 2026-11-20 | 2026-11-20 | [tester](./tmp/reports/2026-11-20-chat-sse-deferred-fixes-tester-2026-11-20-2.json) |
| [gate-anchor-defects](./tmp/reports/2026-11-20-chat-sse-deferred-fixes-gate-anchor-defects.json) | Resolved | 2026-11-20 | 2026-11-20 | [planner](./tmp/reports/2026-11-20-chat-sse-deferred-fixes-gate-anchor-defects.json) |
| [chat-sse-choices-shape-guard](./tmp/reports/defer-issue-chat-sse-choices-shape-guard.json) | Resolved | 2026-11-17 | 2026-11-20 | [tester](./tmp/reports/2026-11-20-chat-sse-deferred-fixes-tester-2026-11-20.json) |
| [chat-tool-degradation-counter-disposition](./tmp/reports/defer-issue-chat-tool-degradation-counter-disposition.json) | Resolved | 2026-11-17 | 2026-11-20 | [tester](./tmp/reports/2026-11-20-chat-sse-deferred-fixes-tester-2026-11-20.json) |
| [chat-sse-coalesced-late-frames](./tmp/reports/defer-issue-chat-sse-coalesced-late-frames.json) | Resolved | 2026-11-17 | 2026-11-20 | [tester](./tmp/reports/2026-11-20-chat-sse-deferred-fixes-tester-2026-11-20.json) |
| [chat-sse-test-comment-stale-cap-location](./tmp/reports/defer-issue-chat-sse-test-comment-stale-cap-location.json) | Resolved | 2026-11-17 | 2026-11-20 | [tester](./tmp/reports/2026-11-20-chat-sse-deferred-fixes-tester-2026-11-20.json) |
| [response-cap-stderr-print-raises](./tmp/reports/defer-issue-response-cap-stderr-print-raises.json) | Resolved | 2026-11-17 | 2026-11-20 | planner — evidence-based resolution (no code change), user-confirmed 2026-11-20; evidence in the Issue Log note below |

The gate-anchor row: the coder applied Steps 1-3 byte-for-byte (all `(auto)`
checks pass) but the group gate could not reach 7/7 — two unsatisfiable
site-anchored assertions (an off-by-one slice length including a phantom
trailing colon, and a 600-char window shorter than the mandated block's
offsets 504/539/592-end-624). Planner fixed the gate in the same session
(correct slice length; window widened to 800), confirmed GREEN 7/7 on the
post-edit tree, and re-verified the revised assertions RED against the exact
pre-change blob (`git show HEAD:src/.../chat_sse.py`) — calibration honest in
both directions. A cosmetic follow-up (detail strings printing on PASS) was
applied with the gate still 7/7. The code under test needed no change.

The fifth row's "fix" is an evidence-based resolution, not a code change: the
claimed raise is unreachable in production (`main()` installs
`_BestEffortStderr` over `sys.stderr` before serving — server.py:1629 on the
post-casing tree; the class sits at server.py:125; executed 2026-11-20: the
wrapper swallows both `OSError` and `UnicodeEncodeError` out of the underlying
stream's write). The user confirmed the no-code-change disposition on
2026-11-20. The row flips to `Resolved` when this evidence is recorded here
and the deferral report retires via `/update-and-commit` Step 9.6.

Note for the record: the deferral report itself carries a self-contradiction —
its parenthetical says call sites "chat_sse.py:395, 863, 867 all pass
validate=False" while the same paragraph says the tool_calls disposition passes
`validate=True` (863). The latter is correct (395/867 pass `False`, 863 passes
`True`); this plan's description is authoritative, and the contradiction is
noted here so it does not survive into the durable record.

## Guidance for Coder

**Files to modify:**

- `src/claude_retry_proxy/chat_sse.py`

**Do not:** touch any test file, `CLAUDE.md`, `README.md`, or `doc/**`. All
four edits are in `_stream_chat_sse_to_anthropic`'s closure scope — no new
module-level state, no signature changes, no behavior change on the wire
except that malformed `choices` frames now degrade instead of raising.

**Step-by-step with verification:**

1. **Step 1: Shape-guard the `choices` payload in `handle_frame`**

   chat_sse.py:560-564 — every sibling payload shape is type-guarded; these two
   are the gap, and both raise on malformed input (executed 2026-11-20:
   `choices` dict → `KeyError: 0`; `choices[0]` str/list → `AttributeError`).
   Degrade with a bare `return None`, mirroring the non-dict-`chunk` guard at
   555-556. The skip is uncounted by design (parity with the chunk guard); the
   unfinished-turn detector's premise stays literally true — a frame degraded
   before delta parsing never carried a tool call the transform could read —
   and Step 5 documents that explicitly.

   Old (exact):

   ```python
               choices = chunk.get("choices") or []
               if not choices:
                   return None
               choice = choices[0] or {}
               delta = choice.get("delta") or {}
   ```

   New (exact):

   ```python
               choices = chunk.get("choices") or []
               if not isinstance(choices, list) or not choices:
                   return None
               choice = choices[0] or {}
               if not isinstance(choice, dict):
                   return None
               delta = choice.get("delta") or {}
   ```

   (`choices[0] or {}` still degrades a `None` element harmlessly — execution-
   verified 2026-11-20 — and that behavior is kept.)

   → coder verify (auto): both pinned guards present in `chat_sse.py`
     (`if not isinstance(choices, list) or not choices:` and
     `if not isinstance(choice, dict):`).
   → coder verify (scripted): part of the group gate
     `./tmp/verification/2026-11-20-chat-sse-deferred-fixes-chatsse.py`
     (run after Step 3; assertions `choices_guard_non_list`,
     `choices_guard_non_dict_element`, `chatsse_compiles`).

2. **Step 2: Make the degradation counter finish-disposition-independent; drop the unused `valid` return**

   chat_sse.py:868-869 — the `elif emitted_tool_use:` disposition (finish
   `stop`/`length` with an emitted tool block) passes `validate=False`, so
   `unparseable_arg_count` is structurally 0 for exactly the fragments it
   exists to surface. Validate there too — diagnostic-only, zero wire change:
   the block is emitted whatever its arguments, the counts only feed the
   coalesced `chat_sse_tool_degradation` event.

   Old (exact):

   ```python
               elif emitted_tool_use:
                   close_open_tool_blocks(validate=False)
   ```

   New (exact):

   ```python
               elif emitted_tool_use:
                   # Diagnostic validation runs here too: the degradation
                   # counter must not depend on which finish disposition
                   # closed the stream.
                   close_open_tool_blocks(validate=True)
   ```

   Scope note (documented in Step 5, not widened in code): only the two
   finish-bearing dispositions validate (chat_sse.py:865 and this site). The
   non-finish close paths — cut stream, oversize frame, retry-nudge error,
   `[DONE]`-without-finish — close tool blocks via
   `close_all_blocks(validate=False)` and never count. Likewise a block that
   was started and later dropped is skipped by the
   `validate and not st["dropped"]` condition; both residuals stay documented
   rather than fixed (outside the deferral's scope).

   Also drop `close_open_tool_blocks`' unused return (chat_sse.py:258, 282,
   283): every call site discards it and no future site wants a dead count.

   Remove these three lines from inside `close_open_tool_blocks` (12-space
   body indent; the annotations in parentheses are positional, the gate pins
   are unanchored substrings):

   - `            valid = 0` (line 258 — the accumulator init),
   - `                    valid += 1` (line 282 — 20-space, inside the
     validate branch),
   - `            return valid` (line 283).

   The function's `return` disappears entirely (implicit `None`); the `for`
   loop and the `continue` statements stay.

   → coder verify (auto): `close_open_tool_blocks(validate=True)` occurs
     exactly twice in `chat_sse.py` (the two finish dispositions);
     `close_open_tool_blocks(validate=False)` occurs exactly once (the
     `close_all_blocks` sweep); `return valid`, `valid = 0`, and `valid += 1`
     have zero matches.
   → coder verify (scripted): group gate assertions
     `counter_validate_at_emitted_disposition`, `valid_return_dropped`,
     `chatsse_compiles`.

3. **Step 3: Capture the late-frame trio at finish discovery; exclude the `[DONE]` sentinel from frame counting**

   Two edits, one semantic unit.

   **3a. Discovery capture** — chat_sse.py:715-718. When the finish frame and
   trailing frames share one `iter_raw` chunk, the chunk-top capture (688-695)
   ran before the finish was discovered, `_off` stays `None`, and the
   post-loop accounting (736-743) never sees the tail: `late_frames: 0`, null
   offsets — which `doc/provider-modes.html` defines as "no frame followed the
   finish signal". Capture the trio where the finish is discovered; same-chunk
   tail frames then count as late frames with offset 0.0 (`finish_seen_at` is
   set on the immediately preceding line, so the offset of same-chunk frames
   is 0 by construction). `frames_seen` was already incremented for the finish
   frame itself (707), so `_frames_before` bounds exactly the frames *after*
   it. Later chunks keep the existing chunk-top capture; per-chunk accounting
   is unchanged. Both capture sites assign the trio together, and the
   accounting block runs only when `_off` is non-None — no new unbound-name
   path; the initialization block (~134) needs no change.

   Old (exact):

   ```python
                   if isinstance(result, tuple) and result[0] == "finish":
                       finish_reason_seen = result[1]
                       finish_seen_at = time.time()
                       continue  # enter drain mode
   ```

   New (exact):

   ```python
                   if isinstance(result, tuple) and result[0] == "finish":
                       finish_reason_seen = result[1]
                       finish_seen_at = time.time()
                       # Frames trailing the finish inside this same coalesced
                       # chunk are late frames with a ~0 offset: capture now,
                       # or the post-loop accounting below never sees them —
                       # the chunk-top capture ran before the finish was
                       # discovered.
                       _off = 0.0
                       _frames_before = frames_seen
                       _tools_before = tool_calls_seen
                       continue  # enter drain mode
   ```

   **3b. Sentinel exclusion** — chat_sse.py:706-707. `frames_seen` increments
   for every extracted frame, `[DONE]` included, before the result dispatch.
   Without this edit, 3a alone would make the most common coalesced shape —
   finish and `[DONE]` with NO trailing usage/tool frame — report a spurious
   late frame (`late_frames: 1`, offsets 0), breaking the pinned
   `test_chat_sse_drain_event_on_done` and contradicting the documented
   0/null semantics. The `[DONE]` sentinel is protocol bookkeeping, not a
   frame that followed the finish: exclude it. This also makes the frame and
   byte accounts symmetric — the `done` branch already breaks before
   `drain_bytes` accumulation, so today `[DONE]` counts as a frame but not as
   bytes (mega-audit hunch, resolved by this edit). `frames_seen`'s only
   consumers are the late-frame accounting (grep-verified: 129, 694, 707,
   737), so the guard changes nothing else.

   Old (exact):

   ```python
                       result = handle_frame(frame)
                       frames_seen += 1
   ```

   New (exact):

   ```python
                       result = handle_frame(frame)
                       if result != "done":
                           # The [DONE] sentinel is protocol bookkeeping, not a
                           # frame that "followed the finish signal": counting
                           # it would make the most common coalesced shape
                           # (finish + [DONE], no trailing usage/tool frame)
                           # report a spurious late frame. drain_bytes already
                           # excludes it (the done branch breaks before
                           # accumulation), so the frame and byte accounts
                           # stay symmetric.
                           frames_seen += 1
   ```

   → coder verify (auto): `_off = 0.0` present in `chat_sse.py`;
     `if result != "done":` present; `frames_seen += 1` occurs exactly once
     (inside the guard); `_frames_before = frames_seen` and
     `_tools_before = tool_calls_seen` each occur exactly twice (chunk top +
     finish discovery).
   → coder verify (scripted): group gate exits 0 — all seven assertions PASS,
     including the site-anchored `late_capture_at_finish_discovery`,
     `sentinel_excluded_from_frames`, and `chatsse_compiles` (RED baseline
     recorded in History; the gate's two anchor bugs were revised mid-plan per
     [gate-anchor-defects](./tmp/reports/2026-11-20-chat-sse-deferred-fixes-gate-anchor-defects.json)
     — the revised anchors verified RED against the pre-change blob).

## Guidance for Tester

**Tests to create:**

- **Permanent** (suggest `tests/test_chat_sse.py`, reusing its established
  fake-response/stream fixtures). **Fixture discipline:** chunk boundaries
  are transport accidents — never rely on TCP flush behavior to produce a
  coalesced read. Drive the coalesced shapes by injecting a fake response
  whose `iter_raw` yields one pre-built chunk (the existing chat_sse fixtures
  support this); drive the separated shapes with explicit multi-chunk
  sequences. A test built on the default `_start_chat_sse_proxy` fixture
  (single write, `add_done=True`) exercises the coalesced shape by definition.
  1. `test_choices_non_list_degrades_frame` — a chunk shaped
     `{"choices": {"delta": {}}}` is skipped without raising; the stream
     continues and closes normally.
  2. `test_choices_non_dict_element_degrades_frame` — a chunk shaped
     `{"choices": ["x"]}` is skipped without raising.
  3. `test_choices_none_element_still_degrades_harmlessly` —
     `{"choices": [None]}` behaves as today (empty delta, no raise).
  4. `test_coalesced_finish_tail_counted_as_late_frames` — one injected chunk
     carrying finish frame + trailing usage frame (+ `[DONE]`):
     `chat_sse_drain` reports `late_frames >= 1`, `first_late_ms == 0`,
     `last_late_ms` populated (pre-fix: 0/null). Cross-reference
     `test_chat_sse_drain_late_tool_call_time_budget` (the separate-chunk
     capture branch is already pinned there, including the ordering invariant
     `first_late_ms <= late_tool_call_ms <= last_late_ms`) — share or mirror
     its assertion helper so the two late-frame branches stay consistent.
  5. `test_true_no_tail_still_reports_null` (control) — the coalesced
     finish + `[DONE]`-only shape (default fixture: content + finish +
     `[DONE]` in one read, no usage/tool tail) still reports
     `late_frames: 0` and null offsets: the documented null-case semantics
     hold after both Step 3 edits.

- **Permanent — extend an existing test rather than adding parallels** (the
  stop/length disposition is already exercised by
  `test_chat_sse_non_tool_calls_finish_with_tool_blocks`, whose stop case at
  ~1223 closes blocks and asserts the tool_use upgrade with valid args):
  parameterize or extend it with an invalid-arguments variant asserting
  `unparseable_arg_count >= 1` and a valid-arguments variant asserting
  `unparseable_arg_count == 0` (no false positives).

- **Do NOT add** a tool_calls-disposition counting test — proposed during
  planning and dropped: it exact-duplicates
  `test_chat_sse_unparseable_arguments_at_close` (~1356), same branch, same
  inputs, same assertion.

**Regression obligation (explicit):** `test_chat_sse_drain_event_on_done`
(~2593, null assertion 2639-2643) MUST stay green unchanged after Step 3 — the
sentinel exclusion (3b) exists precisely to keep its coalesced finish+[DONE]
fixture in the true-null class. Verify it passes; if it fails, the coder edits
are wrong, not the test.

**Tests to investigate for retirement:**

- Planner candidates: none — no test obsolescence identified. The sentinel
  exclusion keeps every existing pinned behavior intact (the audit's
  test-breakage findings were against the original capture-only design and
  are dissolved by Step 3b); the stale comment at tests/test_chat_sse.py:4751
  is fixed below, not retired.
- Tester may identify additional candidates during test work.

**Retirement procedure:** n/a (no candidates).

**Test-file comment fix (tester-owned):** tests/test_chat_sse.py:4751 —
rewrite `(The cap is a local constant in server.py (2 MB))` to name
`chat_sse.py`'s `MAX_EVENT_BUFFER` local (defined at chat_sse.py:99 inside
`_stream_chat_sse_to_anthropic`); no assertion changes.

→ tester verify: the five new tests pass (the control among them); the
  parameterized stop-disposition extension passes in both variants;
  `test_chat_sse_drain_event_on_done` passes unchanged; the full suite
  (`python tests/test_claude_proxy.py`) is green; line 4751's comment names
  `chat_sse.py`.

## Summary

**Problem.** Four deferred defects in `chat_sse.py`, all independently
verified on 2026-11-20 (two by execution, two by deterministic code trace):

1. `handle_frame` type-guards every payload shape except `choices` itself and
   its first element — a malformed `choices` payload raises
   KeyError/TypeError/AttributeError mid-stream, past
   `except _DISCONNECT_ERRORS`, into do_POST's total guard after response
   headers are already committed.
2. `unparseable_arg_count` increments only inside the `validate` branch, and
   only the `finish_reason == "tool_calls"` disposition validates — the
   stop/length-with-emitted-tool-block disposition structurally reports 0.
3. The late-frame trio (`_off`/`_frames_before`/`_tools_before`) is captured
   only at chunk top gated on the finish already being seen — a coalesced
   finish+tail chunk reports "nothing followed", contradicting the documented
   semantics of those fields.
4. A stale test comment names `server.py` as the 2 MB cap's home (now
   `chat_sse.py`'s `MAX_EVENT_BUFFER`).

A fifth deferral (`response-cap-stderr-print-raises`) is resolved in this plan
by evidence, without code change (see Issue Log).

**Approach.** Four surgical edits in `chat_sse.py` (Steps 1-3; 3 is two edits
— the discovery capture plus the sentinel exclusion that keeps it truthful),
one tester round (Step 4: five new tests + one parameterized extension + the
comment + the on-done regression obligation), one planner doc pass (Step 5).
All four code edits are trace-only or degrade-instead-of-raise; none changes a
well-formed stream's wire output.

**Design decisions (planner-owned, with rationale):**
- *Bare `return None` for the `choices` guards* (not counted): mirrors the
  non-dict-`chunk` sibling; a frame degraded before delta parsing carries no
  readable tool call, so the unfinished-turn detector's premise stays
  literally true — Step 5 documents the class explicitly.
- *`validate=True` at the emitted-tool_use disposition, `valid` dropped*:
  measurement-only; the block is emitted regardless of argument validity, so
  validation changes only what the trace reports. The return is dead — every
  call site discards it. Residuals stay documented, not widened: non-finish
  close paths (cut stream, oversize, retry-nudge error, `[DONE]`-without-
  finish) and started-then-dropped blocks remain unvalidated.
- *Capture at finish discovery, offset 0.0*: same-chunk frames follow a
  `finish_seen_at` set one line earlier, so 0 is the truthful offset; later
  chunks keep chunk-top capture, and per-chunk accounting is untouched.
- *`[DONE]` excluded from `frames_seen`* (Step 3b — introduced by the
  pre-implementation mega-audit, 8 corroborating High findings): without it,
  the discovery capture counts the sentinel as a trailing frame and the most
  common coalesced shape reports a spurious late frame. The sentinel is
  protocol bookkeeping; `drain_bytes` already excludes it, so exclusion makes
  the frame and byte accounts symmetric and keeps
  `test_chat_sse_drain_event_on_done`'s pinned null case true unchanged.
  `frames_seen`'s only consumers are the late-frame accounting
  (grep-verified).
- *No change to the drain-field semantics*: post-fix, "no frame followed the
  finish signal" holds universally — coalesced content tails now count with
  ~0 offsets, and a `[DONE]`-only tail is no frame at all. The pinned
  null-case tests (the on-done test and new test #5) guard both shapes.

**Alternatives rejected:** documenting the late-frame gap instead of fixing it
(leaves the 5 s drain budget's tuning evidence permanently blind to coalescing
providers — user decided 2026-11-20: fix the capture); counting `[DONE]` as a
late frame and rewriting the docs/tests to match (dominated: loses the pinned
null test, breaks the documented semantics, and mis-measures the budget
question the fields exist to answer); consuming `valid` instead of dropping
it (no call site wants the count); routing the cap print through additional
guarding (the `_BestEffortStderr` stream guard is the declared single
mechanism and already covers the site at runtime — user confirmed 2026-11-20:
no code change).

**Out of scope:** any change not enumerated in Steps 1-5 — no other source
files, no test files beyond the five new tests, the parameterized extension,
and the one comment line, no README/CLAUDE.md edits beyond the Step 5 sweep's
findings, no new feature work.

## Repo Mode

Public

*Detected at plan creation (detect_repo_mode.py, 2026-11-20). Determines: plan archival path, commit-message content, staged files.*

## Document Overrides

*(empty — zero tolerance; every documented rule is in force)*

| Document | Rule Overridden | Reason |
|----------|----------------|--------|

## Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| `validate=True` adds JSON parsing + `nesting_limit_exceeded` events in the stop/length disposition | Extra trace events where none fired before | Intended diagnostic surface; ≤ 32 open tool blocks per stream, one nesting scan + one `json.loads` per block at close; fragment size is bounded by the response-size cap (the 64 KiB `MAX_CHAT_TOOL_PENDING_BYTES` caps only the pre-start `pending` buffer — started blocks' `arg_parts` accumulate uncapped); zero wire change |
| Late-frame offset 0.0 for coalesced tails | `first_late_ms == 0` reads as "instant" in analysis | Truthful: same chunk means zero measurable gap; the on-done test and new control pin both null shapes |
| Sentinel exclusion changes drain-chunk accounting for a lone `[DONE]` | Today such a chunk counts one late frame with an elapsed offset; post-fix it counts none | The excluded frame is protocol bookkeeping; the metric's question ("did content follow the finish?") was never about `[DONE]`; no existing test pins the old behavior (audit-verified) |
| Guard changes frame handling for malformed chunks | A previously-raising stream now degrades silently | That is the fix; the skip path matches the existing non-dict-chunk behavior and is tested (Step 4 tests 1-3) |

**Rollback:** all four edits land in the plan's single consolidated commit —
`git revert <sha>` restores the pre-fix behavior wholesale. Revert triggers to
watch in the trace: a sudden volume of `nesting_limit_exceeded`
(`site: "tool_args"`) events from the stop/length disposition, or
`chat_sse_drain` late-frame distributions that diverge from pre-fix baselines
without a corresponding provider change. Confirming observation after revert:
event counts return to the pre-fix shape.

## Proposed Changes

1. **Step 1:** Shape-guard the `choices` payload in `handle_frame` (exact old→new in Guidance for Coder)
   → coder verify (auto): both pinned `isinstance` guards present in `chat_sse.py`
   → coder verify (scripted): group gate `./tmp/verification/2026-11-20-chat-sse-deferred-fixes-chatsse.py` — `choices_guard_non_list`, `choices_guard_non_dict_element` (run in full after Step 3)
   → tester verify: Step 4 tests 1-3 pass
2. **Step 2:** Degradation counter finish-disposition-independent (`validate=True` at the emitted-tool_use disposition); drop the unused `valid` return
   → coder verify (auto): `validate=True` exactly 2 sites, `validate=False` exactly 1 site, zero `return valid` / `valid = 0` / `valid += 1` matches
   → coder verify (scripted): group gate — `counter_validate_at_emitted_disposition`, `valid_return_dropped`
   → tester verify: the parameterized stop-disposition extension passes in both variants (invalid args ≥ 1; valid args == 0)
3. **Step 3:** Late-frame trio captured at finish discovery (offset 0.0) + `[DONE]` sentinel excluded from `frames_seen`
   → coder verify (auto): `_off = 0.0` present; `if result != "done":` present; `frames_seen += 1` exactly once; `_frames_before = frames_seen` / `_tools_before = tool_calls_seen` exactly twice each
   → coder verify (scripted): group gate exits 0 — all seven assertions PASS, including `sentinel_excluded_from_frames` and `chatsse_compiles` (RED baseline recorded in History; script unedited)
   → tester verify: Step 4 tests 4-5 pass; `test_chat_sse_drain_event_on_done` passes unchanged
4. **Step 4:** Regression tests (five permanent tests + the parameterized stop-disposition extension) + the stale comment rewrite
   → tester verify: five new tests pass; extension passes in both variants; full suite green; comment names `chat_sse.py`
5. **Step 5:** Doc sync + deferral lifecycle records
   → Evidence: the four doc surfaces edited per Guidance for Planner; executed sweep
     `git grep -inE 'unparseable_arg_count|late_frames|first_late_ms|last_late_ms|late_tool_call_ms|MAX_EVENT_BUFFER' doc/ CLAUDE.md`
     output reviewed and synced surfaces listed; Issue Log rows updated; the evidence-based resolution of `response-cap-stderr-print-raises` recorded with its citation

## Guidance for Planner

Documentation tasks you will execute yourself (not the coder):

- **Files to modify:**
  - `doc/provider-modes.html`
  - `doc/trace-log.html`
  - `doc/test-catalog.html`
- **`.claude/mega-audit-files.json`:** no changes.
- **When:** after the coder finishes (Steps 1-3), alongside the tester round.
- **What to sync:**
  - `doc/provider-modes.html`, degradation paragraph (~lines 610-616 — note:
    `unparseable_arg_count` appears nowhere in doc/ today; this ADDS the field
    name): state that `unparseable_arg_count` is validated at both
    finish-bearing dispositions (`tool_calls`, and `stop`/`length` with an
    emitted tool block) — whichever finish disposition closes the stream — and
    that a nesting overflow among the fragments logs
    `nesting_limit_exceeded` (`site: "tool_args"`) from either; note the
    residuals (non-finish close paths and started-then-dropped blocks remain
    unvalidated) and that the event's `path` field is an upstream-derived
    structural locator (key names) logged to the 0600 POSIX trace, consistent
    with the existing tool_args site.
  - `doc/provider-modes.html`, unfinished-turn paragraph (~lines 514-522): add
    a clause recording that frames degraded for malformed envelope shapes
    (non-dict chunk, malformed `choices`) are skipped before delta parsing and
    carry no readable tool call — the degradation event's absence stays
    load-bearing.
  - `doc/provider-modes.html`, drain-field paragraph (~lines 484-502): add the
    post-fix clarification — the read carrying the finish itself can also
    carry late frames (offset ~0), and the `[DONE]` sentinel never counts as a
    late frame (symmetric with `drain_bytes`).
  - `doc/trace-log.html` (~line 271): the `late_frames` definition — "drain
    reads that carried frames arriving after the finish signal" — becomes
    "reads that carried content-bearing frames arriving after the finish
    signal, including the read that carried the finish itself when its frames
    shared the chunk"; `[DONE]` excluded.
  - `doc/test-catalog.html`: update the `test_chat_sse_drain_event_on_done`
    entry (~line 567 — its "the late-frame stamping never runs" mechanism
    clause is superseded: the stamping runs but attributes nothing, because
    `[DONE]` is not a counted frame); add one entry per new test (the five
    new tests + the parameterized extension, with `(added 2026-11-20)` stamps).
  - Sweep (closing check, all four surfaces + CLAUDE.md):
    `git grep -inE 'unparseable_arg_count|late_frames|first_late_ms|last_late_ms|late_tool_call_ms|MAX_EVENT_BUFFER' doc/ CLAUDE.md`.
  - Record the Issue Log lifecycle: the four code rows and the comment row flip
    to `Resolved` as their verification lands; the evidence-based row records
    its citation in the Resolved By cell.

## History

| Date | Event | Conclusion | Dismissed |
|------|-------|------------|-----------|
| 2026-11-20 | Spec revision (/update-plan) | Scoped tester round succeeded (exit 0, fresh report [2026-11-20-tester-2](./tmp/reports/2026-11-20-chat-sse-deferred-fixes-tester-2026-11-20-2.json)): overall SUCCESS — `test_coalesced_finish_tail_counted_as_late_frames` rebuilt on a structural injected chunk (in-process mixin drive via `_stream_chat_sse_in_one_read`: content + finish + usage + `[DONE]` in one pre-built `iter_raw` chunk, assertions unchanged — no TCP-coalescing assumption left), `test_chat_sse_drain_event_on_done`'s mechanism comment rewritten to the post-fix truth (no assertion change); both review-Warning rows Resolved; catalog entry updated to state the fixture mechanism. All Issue Log rows Resolved — proceeding to Final Results. | — |
| 2026-11-20 | Review | [Report](./tmp/reports/2026-11-20-chat-sse-deferred-fixes-review-2026-11-20.json): verdict "Issues found — non-blocking" — 0 Critical, 2 Warning, 2 Suggestion; commit-ready. Step 3a+3b accounting traced clean across every shape; validate=True confirmed trace-only; choices guards leave no raise path; gate RED/GREEN re-verified first-hand; all four planner reviewer obligations confirmed. The two Warnings (the on-done test's stale mechanism comment; the coalesced test's non-deterministic fixture vs its catalog claim) are folded in rather than dismissed — one scoped tester round; the two Suggestions are fixed in planner doc surfaces in the same pass. | [no-arg-block-counts-unparseable](./tmp/reports/2026-11-20-chat-sse-deferred-fixes-review-2026-11-20.json) (documented, not code-changed — pre-existing at the tool_calls site, diagnostic-only) |
| 2026-11-20 | Planner Step 5 executed | Doc sync complete across the four surfaces: `provider-modes.html` (degradation paragraph now names `unparseable_arg_count` with finish-disposition independence, the two residuals, and the `path`-provenance sentence; unfinished-turn paragraph records the malformed-envelope-shape exception; drain-field paragraph records the discovery-chunk late frames and the `[DONE]` exclusion), `trace-log.html` (`late_frames` = content-bearing frames, `[DONE]` never counted), `test-catalog.html` (on-done mechanism clause rewritten to "stamps but attributes nothing"; five new entries + the parameterized-extension note; the `test_chat_sse.py` module row already covers the new tests under degradation/drain-telemetry and stays as-is). Sweep executed: `git grep -inE 'unparseable_arg_count\|late_frames\|first_late_ms\|last_late_ms\|late_tool_call_ms\|MAX_EVENT_BUFFER' doc/ CLAUDE.md` — all surfaces verified. Reviewer obligations #3 and #4 closed by this step (exact anchor read before editing; widened sweep covers the catalog class). | — |
| 2026-11-20 | Spec revision (/update-plan) | Tester round succeeded (exit 0, fresh report [2026-11-20-tester](./tmp/reports/2026-11-20-chat-sse-deferred-fixes-tester-2026-11-20.json)): overall SUCCESS — five new tests pass (two by-design pre-and-post controls among them), the parameterized extension passes in both variants, `test_chat_sse_drain_event_on_done` unmodified and green (Step 3b's sentinel exclusion preserved the pinned null case), `test_chat_sse_drain_late_tool_call_time_budget` survives (closing mega-audit reviewer obligations #1-#2), full suite green, line-4751 comment rewritten. All five deferral rows Resolved. Planner Step 5 (doc sync) remains. | — |
| 2026-11-20 | Spec revision (/update-plan) | Coder round succeeded (exit 0, fresh report [2026-11-20-coder](./tmp/reports/2026-11-20-chat-sse-deferred-fixes-coder-2026-11-20.json)): Steps 1-3 complete byte-for-byte, build pass, all `(auto)` checks pass; the scripted gate's two anchor bugs (coder-filed [gate-anchor-defects](./tmp/reports/2026-11-20-chat-sse-deferred-fixes-gate-anchor-defects.json), Plan Error — planner-authored gate, not the code) fixed same-session: gate now GREEN 7/7, revised assertions verified RED against the pre-change blob. Step 3's "script unedited" claim below is superseded by that revision. Proceed to tester round. | — |
| 2026-11-20 | Mega-audit | [Report](./tmp/reports/2026-11-20-chat-sse-deferred-fixes-mega-audit-2026-11-20.json): 37 findings (8 High / 9 Medium / 20 Low), verdict "plan needs revision". All 8 High + 9 Medium addressed in this revision: the [DONE]-conflation flaw (5 lenses) fixed by Step 3b sentinel exclusion, dissolving the test-breakage findings; duplicate test #5 removed; test overlap consolidated into the parameterized extension; fixture determinism + #7/#8 shapes specified; doc file list extended to trace-log.html and test-catalog.html; unfinished-turn premise documented; gate hardened to site-anchored assertions and re-baselined on the pre-change tree (revised script unedited: 6/7 FAIL — all six calibration assertions with anchored teeth, e.g. the `elif emitted_tool_use` block fails while the `close_all_blocks` context passes — `chatsse_compiles` PASS). Trivial factual Lows (baseline wording, indent annotations, stale citation, out-of-scope wording, sweep unification, risk bound, rollback section, doc-anchor note, security provenance sentence) corrected in the same revision. Remaining High count: 0 — no re-audit required (iteration 1). | [choices-skip-uncounted](./tmp/reports/2026-11-20-chat-sse-deferred-fixes-mega-audit-2026-11-20.json) (parity with the chunk guard confirmed as final word), [tuple-choices-tightening](./tmp/reports/2026-11-20-chat-sse-deferred-fixes-mega-audit-2026-11-20.json) (unreachable from JSON, harmless), [finish-reason-unvalidated](./tmp/reports/2026-11-20-chat-sse-deferred-fixes-mega-audit-2026-11-20.json) (pre-existing, untouched by this plan) |
| 2026-11-20 | Initial plan | Adopting four deferred chat_sse.py defects after independent verification (execution + code trace); fifth deferral resolved by evidence per user-confirmed disposition (no code change); mega-audit pending (5 steps → triggered). RED baseline of the ORIGINAL gate on the pre-change tree: assertions 1-5 FAIL / `chatsse_compiles` (check 6) PASS (script unedited). | — |

**Phase 6 reviewer obligations (handoff from the mega-audit — confirm or refute each with measurement, do not re-flag):**
1. Gate script and test fixtures were not executed by the audit (deterministic frame-by-frame traces, not executions) — the tester round executes both.
2. `test_chat_sse_drain_late_tool_call_time_budget` fixture shape (~3780-3842) was verified only via its catalog description + ordering-invariant analysis — the tester reads the body and confirms it survives Step 3 either way.
3. The exact anchor of the degradation paragraph in `doc/provider-modes.html` (~610-616) — the planner verifies at Step 5 before editing.
4. All 68 chat_sse catalog entries were not swept for further null-shape pins — the planner's widened sweep (Step 5) closes this.

## Plan Metadata

```json
{
  "plan_id": "2026-11-20-chat-sse-deferred-fixes",
  "steps": [
    "Step 1: Shape-guard the choices payload in handle_frame",
    "Step 2: Make the degradation counter finish-disposition-independent; drop the unused valid return",
    "Step 3: Capture the late-frame trio at finish discovery; exclude the [DONE] sentinel from frame counting",
    "Step 4: Regression tests (five permanent tests + the parameterized stop-disposition extension) + the stale comment rewrite",
    "Step 5: Doc sync + deferral lifecycle records"
  ],
  "coder_files": ["src/claude_retry_proxy/chat_sse.py"],
  "tester_files": ["tests/test_chat_sse.py"],
  "doc_files": ["doc/provider-modes.html", "doc/trace-log.html", "doc/test-catalog.html"],
  "verification_scripts": ["./tmp/verification/2026-11-20-chat-sse-deferred-fixes-chatsse.py"],
  "retire_inventory": [
    "./tmp/reports/2026-11-20-chat-sse-deferred-fixes-coder-2026-11-20.json",
    "./tmp/reports/2026-11-20-chat-sse-deferred-fixes-tester-2026-11-20.json",
    "./tmp/reports/2026-11-20-chat-sse-deferred-fixes-tester-2026-11-20-2.json",
    "./tmp/reports/2026-11-20-chat-sse-deferred-fixes-mega-audit-2026-11-20.json",
    "./tmp/reports/2026-11-20-chat-sse-deferred-fixes-review-2026-11-20.json",
    "./tmp/verification/2026-11-20-chat-sse-deferred-fixes-chatsse.py"
  ],
  "repo_mode": "Public",
  "document_overrides": []
}
```

## Audit Accumulation

*Counters reset when mega-audit runs. Used by Phase 5 entry trigger.*

| Counter | Value | Last Updated |
|---------|-------|--------------|
| issues_resolved_since_audit | 8 | 2026-11-20 |
| steps_changed_since_audit | 0 | 2026-11-20 |
| files_changed_since_audit | 0 | 2026-11-20 |

## Documentation

The synced surfaces are the degradation-event, unfinished-turn, and
drain-field paragraphs of `doc/provider-modes.html`, the `late_frames`
definition in `doc/trace-log.html`, and the per-test index entries in
`doc/test-catalog.html`. Deep reference lives in `doc/` (indexed by
`doc/content.html`).

## Final Results

**Status: COMPLETED — 2026-11-20** (pending user approval to commit)

**What was implemented.** Four surgical edits in `chat_sse.py`:
1. `handle_frame` shape-guards the `choices` payload (non-list `choices`,
   non-dict first element degrade with a bare `return None`, mirroring the
   non-dict-chunk guard) — a malformed upstream frame no longer kills a
   mid-stream response after headers are committed.
2. The degradation counter is finish-disposition-independent:
   `validate=True` at the emitted-tool_use disposition, the unused `valid`
   return dropped — `unparseable_arg_count` now reports truncated/invalid
   fragments whichever finish disposition closed the stream (trace-only;
   zero wire change; residuals documented).
3. The late-frame trio is captured at finish discovery inside the frame loop
   (offset 0.0 for same-chunk tails), **and** the `[DONE]` sentinel is
   excluded from `frames_seen` — the mega-audit-caught design flaw in the
   original capture is what made the exclusion necessary; the frame and byte
   accounts are now symmetric about `[DONE]`, and the pinned null case holds
   unchanged.
4. The stale test comment names `chat_sse.py`'s `MAX_EVENT_BUFFER`.

**Verification chain.**
- Group gate: RED 6/7 → GREEN 7/7, calibration honest in both directions
  (live pre-change tree, then re-verified against the exact `git show HEAD:`
  blob after the gate's own anchor bugs were fixed — coder-filed, planner-fixed).
- Tester round 1: SUCCESS — five new tests (two by-design controls),
  parameterized extension both variants, `test_chat_sse_drain_event_on_done`
  unmodified and green, `test_chat_sse_drain_late_tool_call_time_budget`
  survives, full suite green.
- Mega-audit (pre-implementation): 37 findings (8 High / 9 Medium / 20 Low),
  all High+Medium addressed in the plan revision; its [DONE]-conflation flaw
  (5 corroborating lenses) is the reason Step 3 exists in its final form.
- Reviewer: non-blocking verdict (0 Critical / 2 Warning / 2 Suggestion);
  3a+3b accounting traced clean across every shape; validate=True confirmed
  trace-only; all four planner reviewer obligations confirmed. Its two
  Warnings were folded in and resolved by the scoped tester round (structural
  injected-chunk fixture; comment rewritten); the two Suggestions fixed in
  the planner doc surfaces.
- Tester round 2 (scoped): SUCCESS — deterministic fixture, comment fix,
  module + full suite green.

**Issues resolved (8):** the four code deferrals + the comment deferral + the
evidence-based `response-cap-stderr-print-raises` resolution (user-confirmed,
no code change) + `gate-anchor-defects` (planner-fixed gate) + the two review
Warnings.

**Deferred issues enumerated:** none open under this plan — the
`[DONE]`-related gap that survives is none; the ping-first SSE rewrite gap is
Plan 1's deferral, not this plan's.

**Out-of-scope observations (documented, not code-changed):** the no-argument
tool call counts as unparseable at both validated dispositions (pre-existing,
diagnostic-only); non-finish close paths and started-then-dropped blocks
remain unvalidated.

**Cross-references to prior plans:** none — the five adopted deferrals were
standalone reports (filed 2026-11-17 from the extract-chat-sse mega-audit,
no prior-plan rows).

**Commit note:** the working tree also carries the sibling
`2026-11-20-fix-response-content-type-casing` workstream (uncommitted);
`doc/provider-modes.html` and `doc/test-catalog.html` hold interleaved hunks
from both plans — `/update-and-commit` must scope each plan's staging
accordingly (hunk-level split of the two shared doc files).
