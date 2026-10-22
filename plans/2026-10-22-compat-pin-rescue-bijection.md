# Plan: Restate the reasoning-rescue pin over the mock's own complaint record
**Plan ID:** 2026-10-22-compat-pin-rescue-bijection
**Created:** 2026-10-22

<!-- ## Immediate Actions: absent from initial plans. Populated by /update-plan for revised plans, replaced (not accumulated) on each revision. Contains per-role action-only directives (no rationale) telling agents what to do next. Agents read the full plan for context. -->

## Issue Log

Rows ordered newest-first (latest issues at top). New issues are prepended; resolved issues stay in place with updated status.

| Issue | Status | Found | Resolved | Resolved By |
|-------|--------|-------|----------|-------------|
| [defer-issue-compat-single-retry-global-intermittent](./tmp/reports/defer-issue-compat-single-retry-global-intermittent.json) | Resolved | 2026-10-22 | 2026-10-22 | tester |

This plan **adopts** the deferral above; the operator chose this fix-first
ordering at plan 2026-10-22-chat-mode-image-blocks' Phase 6 gate on 2026-10-22
(the image plan's tester verdict is a strict FAILURE only because of this one
out-of-scope test). The fix content is operator-confirmed: the deferral's
`suggested_fix` (bijection against the mock's own record, keep the 5/5-served
and switch assertions, one honest docstring sentence) was agreed with the
operator before the final update; nothing here is new design.

## Guidance for Tester

**Files to modify:** `tests/test_compat.py` — the ONLY work product. No source,
no docs, no other tests. This is a **test-only plan**: there is no coder step
and no coder report.

**Round completion — read this before you start.** Run any command that can spawn
a proxy or run a test with an explicit `timeout`, and **write your session report
before you end your turn, whatever the result.**

### Step 1 — replace the per-served rescue assertion with a complaint bijection

One surgical edit inside `test_compat_single_retry_global` (the reasoning half,
`tests/test_compat.py:2474-2480`), plus one docstring sentence. The final
assertion block text is given once below — apply it verbatim.

```python
        complaints = [r for r in mock_servers["q"]["requests"]
                      if _sent_reasoning_field(r) != "reasoning_content"]
        rescues = _rescue_trace_events(trace_file)
        if not complaints or len(rescues) != len(complaints):
            fail("expected exactly one reasoning_rescue event per complaint "
                 "the mock received, got %d for %d complaints"
                 % (len(rescues), len(complaints)))
            return
        pass_("one reasoning_rescue event per complaint the mock received "
              "(%d/%d)" % (len(rescues), len(complaints)))
```

Docstring: the test's docstring sentence "the post-switch re-arm makes the
exact end state interleaving-dependent, so the switch itself is the assertion."
stays. After it, add one sentence in the docstring's own voice: how many of
the five clients are served directly through the already-advanced selection is
interleaving-dependent by design, so the rescue count is pinned to the
complaints the mock actually received, never to the served count.

Nothing else in the test changes: `chat_responder`, the sleeps, the 5-thread
staging, the `n_ok == 5` assertion (all five served), and the switch-event
assertion are all untouched and must all still pass.

**Why bijection (for your reasoning, not for the test):** the mock answers
exactly the requests whose sent field is not `reasoning_content` with the
400-complaint body — so `complaints` above IS the complainer set, observed on
the wire. Each complainer runs exactly one lock-free rescue pass that emits
exactly one `reasoning_rescue` trace event, and the rescue body carries
`reasoning_content`, which the mock accepts (200, never a second complaint).
A direct-serve request (its selection resolved to `reasoning_content` at
request start, after the third complaint advanced the shared entry) is served
without ever complaining: it appears in neither set. `len(rescues) ==
len(complaints)` therefore holds on every interleaving, including the two the
deferral measured (5/5 and 4/4 with one direct serve).

**Division of labour.** Do not restage the concurrency harness — its 5/5-served
and switch-drained guarantees are what this test exists to pin, and the
deferral's mechanism trace is complete. Your lane is the assertion swap itself
plus honest measurement.

### Step 1 verification

- **Bijection reachability** (the replacement's failing branch must be able to
  fire — do not skip): instrument once by shadow-copying the test file into
  `tests/temp/`, editing the copy so `_rescue_trace_events` is filtered to drop
  one event (e.g. skip the first), and run the copy — it must FAIL with the new
  assertion text. Delete the copy afterwards; nothing may remain in
  `tests/temp/`.
- **Gate:** `python ./tmp/verification/2026-10-22-compat-pin-rescue-bijection-step1.py`
  — 5/5 isolated runs of `compat-single-retry-global`, exit 0.
- **Module:** `python tests/test_compat.py` fully green (its baseline on the
  clean pre-change tree is 53/53 on this machine's Python 3.14.3 whenever this
  one test passes; the module's own total is unchanged — this plan edits one
  assertion, it adds no test).
- **Full suite:** `python tests/test_claude_proxy.py` must read **437 passed /
  0 failed / 437 total, exit 0** — zero failures, because the tree also carries
  plan 2026-10-22-chat-mode-image-blocks' landed but uncommitted code and tests
  (that plan is paused at its Phase 6 gate awaiting exactly this green suite).
  Report the measured counts as before/after (the image plan's tester measured
  436/1/437 as the before).
- The planner's row-keep rule: the passing 5/5-served assertion, the switch
  assertion, and `n_ok == 5` are the load-bearing pins — verify they all still
  pass in the module run, and say so in the report.

## Summary

**The problem (traced, not guessed).** `compat-single-retry-global`'s reasoning
half asserts "at least one `reasoning_rescue` event per served complainer" for
five concurrent chat requests against a mock that 400s anything not carrying
`reasoning_content`. The reasoner-field credit learner resolves each request's
selection from the shared per-key entry at request start; the third complaint
advances that entry, and a thread whose request starts afterwards is served
directly — no complaint, no rescue event. 5 served / 4 rescues is the learner
working as designed, and the per-served assertion is false in general. Measured
on Python 3.14.3 it fails in the full suite and in 2/3 isolated runs
(interleaving/load-dependent — the tester of plan
2026-10-22-chat-mode-image-blocks measured PASS then FAIL on identical
commands, refining the deferral's earlier determinism claim).

**The fix (test-only, operator-confirmed).** Replace the per-served assertion
with a bijection against the mock's own record: count the requests the fake
upstream answered with the 400-complaint body (re-derive each recorded request
via `_sent_reasoning_field`) and assert `len(rescues) == len(complaints)` with
complaints non-zero. Keep the "all 5 served" and "a switch landed" assertions —
the rescue fires exactly once per complaint the provider received, race-free on
both measured interleavings. One docstring sentence notes that the direct-serve
count is interleaving-dependent by design.

**Out of scope.** Any change to the learner (src/compat.py, src/server.py), any
restaging of the harness, and the image-blocks work itself — this plan exists
only so that plan can pass its Phase 6 gate honestly.

## Repo Mode

Public

## Document Overrides

None

## Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| The bijection miscounts because a complainer's single rescue somehow reaches the mock twice (e.g. a retry arm the trace-verified mechanism does not show) — the new assertion fails where the old one passed | Test red in CI/dev; false alarm on a green learner | Mitigated by the wire-level mechanism trace in the deferral (one rescue pass per complaint, rescue body accepted → no second 400) and by the 5/5-isolated + full-suite gates; if it ever fires, the trace event inventory is the first place to look |

## Proposed Changes

1. **Step 1:** In `test_compat_single_retry_global`, replace the per-served
   rescue-count assertion with the complaint bijection (verbatim block above)
   and add the one docstring sentence (tester-owned; test-only plan)
   → verify: gate 5/5 exit 0; module green; full suite **437 passed / 0 failed
   / 437 total, exit 0**; report carries the measured before/after counts

## Guidance for Planner

- **Deferral bookkeeping.** When Step 1 is verified, the `/update-plan` takes
  the `compat-single-retry-global-intermittent` row to `Resolved`; the report
  `./tmp/reports/defer-issue-compat-single-retry-global-intermittent.json` is
  deleted by `/update-and-commit` Step 9.6 in the same act that commits this
  plan — do not delete it earlier.
- **Phase 6 prerequisite note (test-only plan).** No coder step exists, so the
  absent-coder-report tolerance applies; the tester report must read
  `overall_result: "SUCCESS"` — reachable now, because the tree carries the
  fix.
- **Unblock the image plan.** After this plan's Phase 6 completes, return to
  plan 2026-10-22-chat-mode-image-blocks: re-run its tester round (the suite
  is now fully green) for a strict SUCCESS verdict, then its Phase 6 review.
  Record the detour in the image plan's History.

## History

| Date | Event | Conclusion | Dismissed |
|------|-------|------------|-----------|
| 2026-10-22 | Initial plan | Written at the operator's "fix the pin first" decision (2026-10-22, the image plan's Phase 6 gate). The fix content is not new design — it is the operator-confirmed `suggested_fix` of [defer-issue-compat-single-retry-global-intermittent](./tmp/reports/defer-issue-compat-single-retry-global-intermittent.json): bijection against the mock's wire-observed complaints, keep the 5/5-served and switch assertions, one honest docstring sentence. Test-only plan — one tester step, one test file, so the mega-audit thresholds (≥5 steps / ≥5 source files) do not trigger. | — |
| 2026-10-22 | Gate calibration (pre-change) | `./tmp/verification/2026-10-22-compat-pin-rescue-bijection-step1.py` run against the pre-change tree: **5/5 runs exit 1** with the identical pre-fix assertion (`expected at least one reasoning_rescue event per served complainer, got 4`) — RED confirmed, and on this machine it failed all five consecutively even though the mechanism is interleaving-dependent. Output: background task log `bartplvz6` (2026-10-22). | — |

| 2026-10-22 | Implementation round (tester) — exit 0, report SUCCESS | Report `./tmp/reports/2026-10-22-compat-pin-rescue-bijection-tester-2026-10-22.json`. The verbatim bijection block + docstring sentence landed (17 lines, +12/-5, nothing else in the tree's test file). Pre-change isolated run RED with the old assertion (got 4); post-change GREEN (4/4 bijection); reachability instrument shadow FAILED with the new assertion text (got 3 for 4 complaints) and was deleted, `tests/temp/` empty. Gate **5/5 exit 0**; module **53/53**; full suite **437 passed / 0 failed / 437 total, exit 0** (before: 436/1/437). Row-keep rule verified: 5/5-served, `n_ok == 5`, and the switch-event assertion all still pass. Planner followed the flagged catalog observation: one clause of the `test_compat_single_retry_global` row in `doc/test-catalog.html` updated to the tester's suggested wording (the original "no doc surfaces change" declaration reversed); both doc gates re-passed. | — |

| 2026-10-22 | Review (Phase 6) | Verdict **Issues found — non-blocking**: 0 Critical, 0 Warning, 4 Suggestion; ready to commit. Report [2026-10-22-compat-pin-rescue-bijection-review-2026-10-22.json](./tmp/reports/2026-10-22-compat-pin-rescue-bijection-review-2026-10-22.json). The reviewer independently re-verified the bijection mechanism: `complaints` is exactly the mock's 400 set via the same helper path (incl. unparseable bodies — helper reads None, responder 400s identically, no classification gap); nothing retries a 400 upstream (429/503 only; rescue passes run `suppress_compat=True` → `max_attempts=1`), so one complainer cannot appear twice; one complaint cannot produce two events (first candidate from an unlearned "none" is `reasoning_content`, which this mock accepts). | `pin-rev-cardinality`; `pin-rev-stale-messages`; `pin-rev-guard-message` (deferred as future tester-lane improvements); `pin-rev-doc-files-metadata` (fixed in place — see Final Results) |

## Plan Metadata

```json
{
  "plan_id": "2026-10-22-compat-pin-rescue-bijection",
  "steps": [
    "Step 1: Replace the per-served rescue-count assertion in test_compat_single_retry_global with the complaint bijection and add one docstring sentence"
  ],
  "tester_files": ["tests/test_compat.py"],
  "doc_files": ["./doc/test-catalog.html"],
  "verification_scripts": ["./tmp/verification/2026-10-22-compat-pin-rescue-bijection-step1.py"],
  "repo_mode": "Public",
  "document_overrides": []
}
```

## Audit Accumulation

*Counters reset when mega-audit runs. Used by Phase 5 entry trigger.*

| Counter | Value | Last Updated |
|---------|-------|--------------|
| issues_resolved_since_audit | 1 | 2026-10-22 |
| steps_changed_since_audit | 0 | 2026-10-22 |
| files_changed_since_audit | 0 | 2026-10-22 |

## Documentation

No doc surfaces change was the original declaration, reversed on the tester's
flagged observation (2026-10-22): `doc/test-catalog.html`'s
`test_compat_single_retry_global` row still said "each runs its own lock-free
rescue", which the bijection no longer pins under the 4/4 interleaving. The
planner amended that one clause to the tester's suggested text (all five
clients 2xx, direct-serves noted, rescues == complaints received) and verified
`python scripts/check_doc_anchors.py` (PASS, exit 0) and
`python ~/.claude/scripts/doc_structure_check.py` (PASS, exit 0) afterwards.
The deferral's `updates` array carries the interleaving-refinement evidence.

## Final Results

**Status: Complete — ready for operator approval and `/update-and-commit`.**

- **Steps:** Step 1 (the complaint-bijection assertion + docstring sentence)
  landed by the tester; no coder step exists (test-only plan). The tester's
  `overall_result` is **SUCCESS**; the sole work product is a 17-line diff
  (+12/−5) in `tests/test_compat.py` plus the one
  `doc/test-catalog.html` clause amended by the planner on the tester's
  flagged observation.
- **Test results (tester-measured):** pre-change isolated run RED with the old
  assertion (`got 4`); post-change isolated run GREEN (4/4 bijection);
  reachability shadow FAILED with the new assertion text and was deleted
  (`tests/temp/` empty); declared gate **5/5 exit 0**; module **53/53**; full
  suite **437 passed / 0 failed / 437 total, exit 0** (the image plan's
  tester had measured 436/1/437 as before). The row-keep rule is satisfied:
  the 5/5-served, `n_ok == 5`, and switch-event pins all still pass.
- **Review verdict:** *Issues found — non-blocking* — 0 Critical, 0 Warning,
  4 Suggestion. Report
  [2026-10-22-compat-pin-rescue-bijection-review-2026-10-22.json](./tmp/reports/2026-10-22-compat-pin-rescue-bijection-review-2026-10-22.json).
  The reviewer independently re-verified the bijection mechanism (complaint
  set = mock's 400 set via the same helper; no 400 retry path; one event per
  complaint; equality on every reachable interleaving).

**Known caveats (reviewer Suggestions — deferred improvements, non-blocking):**

- `pin-rev-cardinality` — the assertion pins aggregate cardinality, not
  per-complainer correspondence; adding
  `len({e["request_id"] for e in rescues}) == len(rescues)` would also catch
  a double-emit/lost-event swap. Deferred to a future tester-lane plan.
- `pin-rev-stale-messages` — the test's own pass/fail text still says "all 5
  concurrent complainers were served", which the 4/4 interleaving makes
  imprecise. Deferred with the above.
- `pin-rev-guard-message` — the `not complaints` guard shares the
  count-mismatch message, so an empty-complaint regression would print an
  uninformative "0 for 0". Unreachable in a healthy run; deferred with the
  above.
- `pin-rev-doc-files-metadata` — Plan Metadata `doc_files` is now
  `["./doc/test-catalog.html"]`, matching the Documentation section. Fixed in
  place.

**Deferred issues**

- [defer-issue-compat-single-retry-global-intermittent](./tmp/reports/defer-issue-compat-single-retry-global-intermittent.json)
  — **Resolved by this plan** (Issue Log row above; `Resolved By: tester`).
  The report file is deleted by `/update-and-commit` Step 9.6 when this plan
  commits; it must not be deleted earlier.

No other deferred issues touch this plan's scope, and this plan resolved no
deferral that a prior plan itself deferred (the deferral was standalone-filed,
not a prior plan's caveat), so there is no Cross-References section.