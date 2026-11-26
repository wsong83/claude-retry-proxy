# Plan: Consolidate the trace-polling helpers into tests/_harness.py

**Plan ID:** 2026-11-26-consolidate-trace-helpers
**Created:** 2026-11-26

## Issue Log

| Issue | Status | Found | Resolved | Resolved By |
|-------|--------|-------|----------|-------------|

## Guidance for Coder

None. Test-file changes are tester-lane exclusively; no coder steps.

## Guidance for Tester

**Tests to create:** none — this plan moves helpers, it changes no test's behavior.

**Verification scripts to create:** none by the tester — the planner-authored gate at `./tmp/verification/2026-11-26-consolidate-trace-helpers-gate.py` is the scripted check; reference any behavioral script you add in the session report.

**Files to modify:**
- `tests/_harness.py` (gains `_message_delta_usage`; `_wait_for_trace_events` docstring upgraded to the chat-specific rationale)
- `tests/test_chat_sse_drain.py` (the three local trace helpers deleted; harness import block gains their names)
- `tests/test_chat_sse.py` (sibling line deleted; harness block gains 3 names)
- `tests/test_chat_sse_tools.py` (sibling line deleted; harness block gains 2 names)
- `tests/test_chat_nudge.py` (sibling line deleted; harness block gains 1 name)
- `tests/test_chat_sse_swap.py` (sibling line deleted; harness block gains 2 names)

**Step-by-step with verification:**

1. **Step 1 (tester): Consolidate and re-point.** In `tests/_harness.py`: replace `_wait_for_trace_events`'s docstring with the drain copy's (pinned below); insert `_message_delta_usage` (verbatim move from the drain file) immediately after `_wait_for_trace_events`'s body, before `_wait_admin_swapping`, flanked by the harness's **4-blank-line separator on both sides** (the drain file's 2-blank convention does not carry over; the gate asserts the parity) — its dependency `_sse_frames_with_type` is already defined at harness L1639. In `tests/test_chat_sse_drain.py`: delete the three local defs `_trace_events_named` (L169–185), `_wait_for_trace_events` (L188–202), `_message_delta_usage` (L205–210) — each from its `def` line through its final body line — and the orphaned separator blanks; add `_message_delta_usage`, `_trace_events_named`, `_wait_for_trace_events` to the existing `from _harness import (...)` block. In the four consumer files: delete the `from test_chat_sse_drain import (...)` statement entirely — a multi-line parenthesized block in `tests/test_chat_sse.py`, `tests/test_chat_sse_tools.py`, and `tests/test_chat_sse_swap.py`, single-line in `tests/test_chat_nudge.py` — and repair the separator blanks it leaves; add the names to the existing harness block — `tests/test_chat_sse.py` gains `_message_delta_usage`, `_trace_events_named`, `_wait_for_trace_events`; `tests/test_chat_sse_tools.py` gains the two trace names; `tests/test_chat_nudge.py` gains `_trace_events_named`; `tests/test_chat_sse_swap.py` gains the two trace names. After this step **no `from test_chat_sse_drain import` remains anywhere in `tests/`** except the aggregator's `ALL_TESTS` import (which is a registration, not a helper dependency).
   → tester verify (scripted): `python3 ./tmp/verification/2026-11-26-consolidate-trace-helpers-gate.py` exits 0.
   → tester verify: `python tests/test_claude_proxy.py` exits 0 (full suite green).

2. **Step 2 (planner): Record resolution.** No doc *edit* is needed — the catalog's `doc/test-catalog.html` "The harness" helper tables are curated/non-exhaustive and none of the three consolidated names appears there (see Documentation); CLAUDE.md and README do not enumerate helper surfaces. The chat-sse plan's recorded follow-up gets **two** records at commit, both during Step 9.6's cross-reference window: (a) the machinery's Route B search covers only Known Caveats, History Conclusion/Dismissed cells, and Issue Log link slugs — the follow-up bullet lives in the prior plan's `### Recorded follow-ups` section, which none of the three covers, so the no-match fallback appends a new `2026-11-26-consolidate-trace-helpers cross-reference — …` row to the prior plan's Issue Log (status Resolved, both copies, with the standard review warning — expected, and reviewed to confirm); (b) the planner additionally annotates the bullet itself in both copies — strikethrough + `Resolved 2026-11-26 by plan 2026-11-26-consolidate-trace-helpers: …` per the Known-Caveats convention — so it no longer reads as open work (the same prior-plan files the sub-step itself writes and stages in that window).

### Pinned edits

**Harness `_wait_for_trace_events` docstring (replace the whole docstring with):**

```
"""Poll trace_file until at least one `event_name` event appears.

A client that returns at message_stop can outrun the proxy's trace write:
the terminal frames are flushed to the wire before chat_sse_drain (or the
detector events) reach the sink, so a single immediate read races the
proxy process. Returns the events found, or [] if none landed within
`timeout_s` seconds.
"""
```

(Body unchanged. This is the drain copy's docstring verbatim — the chat rationale subsumes the generic wording it replaces.)

**`_message_delta_usage` (verbatim move into the harness, from `HEAD:tests/test_chat_sse_drain.py` L205–210):**

```
def _message_delta_usage(frames):
    """Return the usage dict on the first message_delta frame, or None."""
    deltas = _sse_frames_with_type(frames, "message_delta")
    if not deltas:
        return None
    return deltas[0].get("usage")
```

**Post-change import sets (gate-pinned, exact):**

| File | `_harness` block after |
|------|------------------------|
| `test_chat_sse_drain.py` | prior 24 names + `_message_delta_usage`, `_trace_events_named`, `_wait_for_trace_events` = 27 |
| `test_chat_sse.py` | prior 16 + `_message_delta_usage`, `_trace_events_named`, `_wait_for_trace_events` = 19 |
| `test_chat_sse_tools.py` | prior 18 + `_trace_events_named`, `_wait_for_trace_events` = 20 |
| `test_chat_nudge.py` | prior 12 + `_trace_events_named` = 13 |
| `test_chat_sse_swap.py` | prior 14 + `_trace_events_named`, `_wait_for_trace_events` = 16 |

Sibling-import lines: **zero** in all five files (the aggregator's `from test_chat_sse_drain import ALL_TESTS` stays).

**Rollback.** `git restore --source=HEAD --staged --worktree tests/_harness.py tests/test_chat_sse_drain.py tests/test_chat_sse.py tests/test_chat_sse_tools.py tests/test_chat_nudge.py tests/test_chat_sse_swap.py` — one command; nothing untracked among the six test files (the gate script is an untracked verification artifact under `tmp/` and survives rollback by design). **Precondition:** the six files' only uncommitted changes are this plan's edits — a concurrent plan's staged hunks in these files would be discarded by the whole-file restore. After the Step 10 commit a gate re-run no longer reports this RED: it exits 1 with the recorded `HEAD drain defines …` FAIL rows — expected post-commit behavior, not a fault.

### Byte-identity sources

`_trace_events_named` and `_message_delta_usage` segments must be byte-identical to `HEAD:tests/test_chat_sse_drain.py`'s segments (name-keyed sha256). `_wait_for_trace_events` is **AST-equal** with the pinned docstring: the gate strips the docstring from both harness and HEAD-drain definitions and requires AST-dump equality of the remainder (comments and intra-body formatting are not compared), plus the exact pinned docstring text above (`ast.get_docstring`). The two byte-identical helpers stay sha256-pinned.

## Tests to investigate for retirement

None — helpers move, no test's coverage changes.

## Summary

**Problem.** The suite's only cross-file duplication (survey 2026-11-26, plan 2026-11-26-partition-chat-sse's recorded follow-up): `_trace_events_named` and `_wait_for_trace_events` — together ~30 duplicated lines — are defined both in `tests/_harness.py` and locally in `tests/test_chat_sse_drain.py`. Six other files import `_trace_events_named` from the harness (three of them also `_wait_for_trace_events`) — the drain copies are shadow duplicates — and the chat-sse partition left four files importing the drain copies through a sibling-import seam.

**Approach.** Consolidate the duplicated pair into the harness (the already-live shared surface) and dissolve this seam completely by moving `_message_delta_usage` with them — a same-block sibling under §7's test-side consolidation (not a §2 collaborator: it is a same-concept helper with consumers of its own; its dependency `_sse_frames_with_type` is already harness-resolvable) — so no test file imports helpers from `test_chat_sse_drain`. (The pre-existing admin seam — `test_admin_html_status.py` importing two JS-extraction helpers from `test_admin_html.py`, single-sourced and duplication-free — is a different, unrelated seam and stays out of scope.)

**Key decisions.**
- The harness is the home: it already hosts `_trace_events_named` for six files (three of them also `_wait_for_trace_events`); the drain file becomes a consumer like everyone else.
- `_wait_for_trace_events`'s harness docstring adopts the drain copy's chat-specific rationale verbatim (the only body-independent delta); bodies are already identical.
- `_message_delta_usage` rides as a same-block sibling — not duplicated, but part of the same block and required to dissolve the seam (otherwise the kept file keeps a 1-name sibling import).
- Catalog/CLAUDE.md/README need no sync — the catalog's harness helper tables are curated/non-exhaustive and list none of the three names; the resolution of the chat-sse plan's recorded follow-up is recorded per Step 2's two-part mechanism (Route B fallback Issue Log row + direct bullet annotation).

**Out of scope:** the `test_compat.py` partition (immediately next, own plan); any harness refactor beyond the three-helper consolidation.

## Repo Mode

Public

## Document Overrides

| Document | Rule Overridden | Reason |
|----------|----------------|--------|

## Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| A consumer misses the import re-point | `NameError` at import, suite red | Gate asserts each file's exact harness name set and zero sibling lines; full suite run is the gate |
| Harness docstring merge loses a nuance | Maintainer-facing only | The pinned docstring is the drain copy verbatim; gate asserts its exact text |
| Aggregator `ALL_TESTS` import from drain is mistaken for a seam leftover | False-positive cleanup deleting a registration | The gate's sibling-line check excludes the aggregator's `ALL_TESTS` import explicitly |

## Proposed Changes

1. **Step 1 (tester): Consolidate and re-point** — the six-file edit exactly as pinned above.
   → tester verify (scripted): `python3 ./tmp/verification/2026-11-26-consolidate-trace-helpers-gate.py` exits 0.
   → tester verify: `python tests/test_claude_proxy.py` exits 0.
2. **Step 2 (planner): Record resolution** — no doc sync; the follow-up record rides Step 9.6: Route B fallback Issue Log row + direct annotation of the `### Recorded follow-ups` bullet (both copies).

## Guidance for Planner

- **Files to modify:** none directly (no doc sync needed). The `## Cross-References to Prior Plans` table below drives the Route B fallback row; the direct annotation of the prior plan's `### Recorded follow-ups` bullet (both copies) is the planner's own Step 9.6-window act (Step 2).
- **`.claude/mega-audit-files.json`:** no declared audit locations exist in this repo.
- **When:** Step 2 rides `/update-and-commit` Step 9.6 (cross-reference window: Route B fallback row + direct bullet annotation).

## Cross-References to Prior Plans

| Prior Plan | Deferred Issue | Resolution |
|------------|----------------|------------|
| 2026-11-26-partition-chat-sse | Consolidate the byte-identical `_trace_events_named` (and docstring-only `_wait_for_trace_events`) copies between `tests/_harness.py` and the drain file. | Consolidated 2026-11-26: both names (plus the same-block sibling `_message_delta_usage`) are harness-only; the drain file and all four consumers import from `_harness`; the sibling-import seam is dissolved. |

## History

| Date | Event | Conclusion | Dismissed |
|------|-------|------------|-----------|
| 2026-11-26 | Initial plan | Survey (752 functions, 35 files, lenses A/B/D/E) found exactly one cross-file duplication cluster — the recorded chat-sse follow-up; user approved consolidation as its own tiny plan before the test_compat.py partition; harness confirmed as the live shared surface; `_message_delta_usage` rides as a same-block sibling to dissolve the seam entirely; gate RED-calibrated against the pre-change tree (fails on exactly the missing harness definition); the per-file import pins are **exact absolute sets** (baseline ∪ additions, every name enumerated) rather than net deltas — an equality the implementation cannot partially satisfy | `_trace_events_named`'s exists-check/open TOCTOU (audit note: the shared copy could guard `open` with `except OSError: return out`) — dismissed: test-failure visibility is preferred over silent degradation, and changing the body is outside this plan's consolidation scope |
| 2026-11-26 | Mega-audit iteration 1 (pre-implementation, run `wf_be97e71a-1fd`, 9 lenses) | 20 findings (4 High / 4 Medium / 12 Low), report at `./tmp/reports/2026-11-26-consolidate-trace-helpers-mega-audit-2026-11-26.json`. The 4 Highs share one root — the gate's docstring handling was self-contradictory (`strip_docstring` stripped the Module's body[0] instead of the FunctionDef's, so "body-identity" included the docstring, while the pinned-text `startswith` demanded flush-left continuation lines no verbatim copy can carry): `strip_docstring` now unwraps the FunctionDef and strips its first statement, and the pinned check compares `ast.get_docstring` against the dedented pinned text — the two checks are now consistent and both satisfiable. Mediums fixed: deletion ranges corrected to the real def extents (L169–185, L188–202; L205–210 was exact) with the "def line through final body line" wording; the "six files import both names" premise corrected (six import `_trace_events_named`, three also `_wait_for_trace_events`); the end-state claim scoped to the seam this plan dissolves (the admin-html seam named out of scope); the no-doc-sync rationale now acknowledges the catalog's curated harness tables (none of the three names listed → no row, consistent with curation). Lows folded in: read/parse guards in the gate (recorded FAILs instead of escapes), harness-import accumulation across multiple blocks, rollback wording scoped to the six test files, "gate below" replaced with the explicit path | — |
| 2026-11-26 | Mega-audit iteration 2 (pre-implementation, run `wf_f3282298-e4e`, 9 lenses; 18 findings: 0 High / 1 Medium / 17 Low, verdict non-blocking — 0 High exits the iteration loop; report at `./tmp/reports/2026-11-26-consolidate-trace-helpers-mega-audit-2026-11-26-r2.json`) | Medium fixed: Step 2 now records the true Route B mechanics — the sub-step searches only Known Caveats / History Conclusion-Dismissed cells / Issue Log slugs, the follow-up bullet sits in the prior plan's `### Recorded follow-ups` (unsearched), so the no-match fallback appends a `… cross-reference` Issue Log row to the prior plan (expected, reviewed to confirm) and the planner directly annotates the bullet (strikethrough + resolution note, both copies) in the same Step 9.6 window; the collaboration label and Route-B wording updated everywhere they occurred. Gate robustness completed the fold the iteration-1 History over-claimed: the three raw `read_text` calls (EXPECT loop — dead read dropped; sibling scan; aggregator) and the HEAD-derived lookups (parse guard, three presence checks with recorded-FAIL early abort, `drain_wait` node) are now recorded FAILs, the sibling predicate matches any indent, and a 4-blank separator-parity check was added; RED re-verified (fails on exactly `harness defines _message_delta_usage`, HEAD-presence checks green pre-change). Plan-wording fixes: measured six/three premise at Key Decisions, curated-table rationale replacing the false "document tests, not helpers" parenthetical, AST-equal (not byte-equal) wording for the wait-helper body, same-block-sibling label replacing the §2-collaborator mislabel, multi-line sibling-import deletion wording, 4-blank separator pin in Step 1, rollback precondition + post-commit recorded-FAIL note, and the initial row's false citations corrected in place (the doctrine guide contains no gate-teeth/net-delta strings; the survey script defines four lenses A/B/D/E, its five `===` output sections double-print B) | Docstring chat-specific scope (maintainer-facing, Risks-covered, gate pins the exact text — accepted as documented); latent `_message_delta_usage(None)` TypeError (pre-existing, all current callers guard); read-side mid-write partial-line skip, re-poll full-file cost, never-created-file full-timeout spin (all pre-existing, unchanged by the byte-verbatim move); `_wait_for_event_count` intra-file twin (out of scope; future consolidation candidate); relative-import sibling form (unrealistic; opening-line match covers current shapes); gate double-parses (inefficiency only); uncommitted gate script (repo practice: `tmp/verification` scripts are disposable retire_inventory artifacts); audit-accumulation counters (per-audit reset semantics; plan-text edits uncounted); optional catalog `_message_delta_usage` row (section non-exhaustive by design); security lens endorsed the recorded TOCTOU dismissal — no plan change |
| 2026-11-26 | Tester round 1 (launched 12:24:35, exited 0; report `./tmp/reports/2026-11-26-consolidate-trace-helpers-tester-2026-11-26.json`) | Step 1 executed exactly as pinned across the six test files: gate pre-change RED reproduced as calibrated (1 FAIL: `harness defines _message_delta_usage`) then 95/95 PASS post-change; sha256 byte-identity for `_trace_events_named`/`_message_delta_usage`, AST-equality + pinned docstring for `_wait_for_trace_events`; the three names harness-only, 4-blank separators verified both sides, exact import sets (drain 27 / sse 19 / tools 20 / nudge 13 / swap 16), zero sibling imports at any indent, aggregator registration preserved; full suite 555/555 exit 0. Planner-side re-verification: gate 95/95, `check_spawn_isolation` PASS, diffstat 27+/62− over exactly the six planned files | — |
| 2026-11-26 | Phase 6 review (report `./tmp/reports/2026-11-26-consolidate-trace-helpers-review-2026-11-26.json`) | Verdict non-blocking: 0 Critical / 0 Warning / 1 Suggestion. Reviewer independently re-verified the verbatim move (AST source-segment sha256-equal for all three helpers, adopted docstring included), no dead or dropped imports in any of the six files, drain-file post-deletion hygiene (`os.`/`json.` still used, `_sse_frames_with_type` still 8 call sites, 2-blank separation before the Frame-cap banner, docstring accurate), harness insertion ordering + 4-blank separators, seam dissolved repo-wide (only the aggregator's ALL_TESTS registration remains), import counts exactly 27/19/20/13/16, and the no-doc-sync claim (none of the three names in `doc/`, README, CLAUDE.md). Suggestion (cohesion, optional): `_message_delta_usage` is an SSE-frame accessor placed in the trace-polling region between `_wait_for_trace_events` and `_wait_admin_swapping`, ~120 lines from its `_sse_frame_type`/`_sse_frames_with_type`/`_sse_types` siblings — **accepted as-is**: the placement is plan-pinned and gate-asserted (contiguity of the three moved names eases verbatim verification), so relocation now would trade a gate revision for a style nicety against the never-fix-in-a-move doctrine | — |

## Plan Metadata

```json
{
  "plan_id": "2026-11-26-consolidate-trace-helpers",
  "steps": [
    "Step 1: Consolidate and re-point",
    "Step 2: Record resolution"
  ],
  "coder_files": [],
  "tester_files": [
    "tests/_harness.py",
    "tests/test_chat_sse_drain.py",
    "tests/test_chat_sse.py",
    "tests/test_chat_sse_tools.py",
    "tests/test_chat_nudge.py",
    "tests/test_chat_sse_swap.py"
  ],
  "doc_files": [],
  "verification_scripts": [
    "./tmp/verification/2026-11-26-consolidate-trace-helpers-gate.py"
  ],
  "retire_inventory": [
    "./tmp/verification/2026-11-26-consolidate-trace-helpers-gate.py",
    "./tmp/reports/2026-11-26-consolidate-trace-helpers-mega-audit-2026-11-26.json",
    "./tmp/reports/2026-11-26-consolidate-trace-helpers-mega-audit-2026-11-26-r2.json",
    "./tmp/reports/2026-11-26-consolidate-trace-helpers-tester-2026-11-26.json",
    "./tmp/reports/2026-11-26-consolidate-trace-helpers-review-2026-11-26.json"
  ],
  "repo_mode": "Public",
  "document_overrides": []
}
```

## Audit Accumulation

| Counter | Value | Last Updated |
|---------|-------|--------------|
| issues_resolved_since_audit | 0 | 2026-11-26 |
| steps_changed_since_audit | 0 | 2026-11-26 |
| files_changed_since_audit | 6 | 2026-11-26 |

## Documentation

- The catalog's "The harness" section carries curated (not exhaustive) helper tables; none of the three consolidated names is listed there today, so no row is needed and none is added — consistent with the section's existing curation. No other doc names the helper surfaces this plan touches; CLAUDE.md and README do not enumerate them.

## Final Results

**Completed:** 2026-11-26 — **COMPLETED**.

**Implemented.** Step 1 (tester): the suite's only cross-file duplication cluster dissolved — `_trace_events_named` and `_wait_for_trace_events` consolidated into `tests/_harness.py` (the latter's docstring upgraded to the drain copy's chat-specific rationale, body AST-identical), with the same-block sibling `_message_delta_usage` carried along (verbatim sha256-pinned against `HEAD:tests/test_chat_sse_drain.py`, 4-blank separators both sides). The drain file's three local defs deleted; all four consumer files re-pointed to `_harness`; the sibling-import seam is gone — the only remaining `from test_chat_sse_drain import` in `tests/` is the aggregator's `ALL_TESTS` registration. Step 2 (planner) rides `/update-and-commit` Step 9.6: the Route B fallback Issue Log row in the prior plan plus the direct annotation of its `### Recorded follow-ups` bullet (both copies).

**Files changed.** `tests/_harness.py`, `tests/test_chat_sse_drain.py`, `tests/test_chat_sse.py`, `tests/test_chat_sse_tools.py`, `tests/test_chat_nudge.py`, `tests/test_chat_sse_swap.py` — 27+/62−, net −35 lines.

**Test results.** Full suite **555/555 green**, exit 0. Planner gate 95/95 PASS post-change (pre-change RED reproduced as calibrated: exactly `harness defines _message_delta_usage`); byte-identity (sha256) + AST-equality + pinned docstring gate-proven; exact post-change import sets (drain 27 / sse 19 / tools 20 / nudge 13 / swap 16); `scripts/check_spawn_isolation.py` PASS.

**Issues resolved.** Mega-audit iteration 1 (20 findings: 4 High / 4 Medium / 12 Low) and iteration 2 (18 findings: 0 High / 1 Medium / 17 Low, loop exit) — every High and Medium fixed, Lows folded in or recorded dismissed in History. Phase 6 review: 0 Critical / 0 Warning / 1 Suggestion (cohesion placement of `_message_delta_usage`, plan-pinned — accepted as-is).

**Deferred issues.** None filed by this plan.

**Residual records.** The consolidation-follow-up record in the archived chat-sse plan (fallback Issue Log row + direct bullet annotation) lands at commit; the pre-existing admin-html helper seam (`test_admin_html_status.py` ← `test_admin_html.py`, single-sourced, duplication-free) is named out of scope and stays.
