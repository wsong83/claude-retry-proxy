# Plan: Extract the response-model-rewrite pair into model_rewrite.py

**Plan ID:** 2026-11-24-extract-model-rewrite
**Created:** 2026-11-24

## Issue Log

Rows ordered newest-first (latest issues at top). New issues are prepended; resolved issues stay in place with updated status.

| Issue | Status | Found | Resolved | Resolved By |
|-------|--------|-------|----------|-------------|
| [forwarder-docstring-stale](./tmp/reports/2026-11-24-extract-model-rewrite-forwarder-docstring-stale.json) | Resolved | 2026-11-24 | 2026-11-24 | [tester](./tmp/reports/2026-11-24-extract-model-rewrite-tester-2026-11-24.json) |

## Guidance for Coder

**Files to modify:**
- `src/claude_retry_proxy/model_rewrite.py` (new)
- `src/claude_retry_proxy/forwarder.py`

**Step-by-step with verification:** each step below has coder checks tagged `(auto)` or `(scripted)`. The coder self-verifies `(auto)` checks and runs the provided script for `(scripted)` checks. Tester owns the behavioral checks. See coder Prime Directive 4.

**Module-surface count table (whole plan):**

| Kind | Change | Count |
|---|---|---|
| Behavioral | none — bodies byte-identical | 0 |
| Module-surface | `forwarder.py`: −2 top-level `FunctionDef`s (`_rewrite_sse_event`, `_rewrite_json_response`), −1 `from .nesting import …` line (both names' sole readers move), +1 `from .model_rewrite import (…)` re-export line carrying both names | −2 defs / −1 import / +1 import |
| Module-surface | `model_rewrite.py`: +1 module, +2 top-level `FunctionDef`s, imports per the pinned whitelist | +2 defs |
| Module-surface | `forwarder.py` Step 5: module docstring lines 4–8 rewritten — drops the stale "response-rewrite helpers" ownership claim, names both re-exported siblings — **line-count-neutral** (9 docstring lines before and after, forwarder stays 1602 lines) | 0 net lines |
| Names resolvable through `forwarder` | unchanged — both rewrite names attribute-resolve via re-export (`server.py`'s import block and `tests/test_nesting.py`'s `srv._rewrite_*` calls are untouched) | 0 |
| Implementation | none — verbatim move | 0 |

**Frozen-surface evidence lines (names re-exported because callers/tests read them):**
- `server.py` L44–54 imports both `_rewrite_json_response` and `_rewrite_sse_event` from `.forwarder` — unchanged.
- `tests/test_nesting.py` L849/L899 call `srv._rewrite_json_response(...)` / `srv._rewrite_sse_event(...)` — attribute access through server's namespace, unchanged.
- `tests/test_nesting.py` L48–49 imports `check_payload_nesting`/`nesting_event` from `claude_retry_proxy.nesting` directly — unaffected by forwarder's import deletion (grep verified 2026-11-24: no test or script imports anything via `from claude_retry_proxy.forwarder import …`).

**Import whitelist for `model_rewrite.py` (pinned; anything else is a plan revision):**

```python
import json
import time

from .nesting import check_payload_nesting, nesting_event
from .sinks import log_trace
```

Never import `.forwarder` or `.server` — parent→sibling is the only legal direction, and the whitelist above is complete (the moved bodies read exactly `json`, `time`, `check_payload_nesting`, `nesting_event`, `log_trace`).

**Deletion range and seam (Step 2):** before cutting, re-verify every landmark on the live file — L1602 == `    return "unknown"`, L1603 == blank, L1604 == blank, L1605 == `def _rewrite_sse_event(event_bytes, tier, request_id):`, L1746 == `        return body_bytes`, total 1746 lines. A drifted file, or a zero-length remaining range, is a **stop-and-report**, never an improvisation. Delete lines 1603–1746 (the two separator blanks plus both functions, through EOF) so forwarder ends at L1602 with a single trailing newline and no trailing blanks. Banner comments: none head the moved defs (verified 2026-11-24 — the cluster directly follows `resolve_tier` and is the file tail).

**Untracked-file rule:** `git add src/claude_retry_proxy/model_rewrite.py` the moment Step 1's file exists.

1. **Step 1: Create `src/claude_retry_proxy/model_rewrite.py` — the rewrite pair byte-verbatim behind the pinned import whitelist**
   - New module with a short module docstring (new scaffolding — state the concept: the anthropic-mode model projection; chat/response modes get the model from their body transforms; this module never imports its parent), then the pinned import block (see whitelist above), then the two functions copied byte-identically from `forwarder.py` L1605–1711 (`_rewrite_sse_event`) and L1714–1746 (`_rewrite_json_response`), separated by exactly two blank lines, file ends with a single trailing newline. No renames, no reordering, no docstring or comment edits inside the moved bodies, no bug fixes.
   - Run `git add src/claude_retry_proxy/model_rewrite.py`.
   - → coder verify (auto): module compiles — `python3 -m py_compile src/claude_retry_proxy/model_rewrite.py` exits 0; the file is git-tracked (`git status --porcelain` shows it staged, not untracked).
   - → coder verify (scripted): `python3 tmp/verification/2026-11-24-extract-model-rewrite-step1.py` exits 0.
     Evidence (baseline RED, 2026-11-24 pre-change tree, script unedited): `FAIL module file exists`, `FAIL segment sha256 _rewrite_sse_event -- module absent`, `FAIL segment sha256 _rewrite_json_response -- module absent`, `SUMMARY: FAIL (3)`, exit 1.

2. **Step 2: Excise the cluster from `forwarder.py`; re-export both names; relocate the reader-less nesting import**
   - Edit A (import surgery): replace line 37 `from .nesting import check_payload_nesting, nesting_event` with `from .model_rewrite import (_rewrite_json_response, _rewrite_sse_event)`. Both nesting names' sole readers are the moved functions (grep verified 2026-11-24: no other reference outside L1605–1746), so the `.nesting` line is deleted, not narrowed — imports follow their readers. `json`, `time`, and `log_trace` keep readers in forwarder and stay.
   - Edit B (tail excision): after re-verifying the landmarks above, delete lines 1603–1746 through EOF.
   - Post-conditions: forwarder.py is 1602 lines ending `    return "unknown"` + newline; the suite-facing surface is unchanged (server.py and test_nesting.py resolve both names through forwarder's re-export).
   - → coder verify (auto): import smoke with the canonical isolation env — `PROXY_TRACE_FILE=$(mktemp -d)/t.jsonl PROXY_STATE_FILE=$(mktemp -d)/s.json PROXY_FEATURE_COMPAT_FILE=$(mktemp -d)/f.json python3 -c "import claude_retry_proxy.server"` exits 0.
   - → coder verify (scripted): `python3 tmp/verification/2026-11-24-extract-model-rewrite-step2.py` exits 0.
     Evidence (baseline RED, 2026-11-24 pre-change tree, script unedited): checks A1, B1, B2, C1, C2, D1–D4, F FAIL (forwarder still defines the pair at 1746 lines, no re-export, nesting import present, module absent); E1/E2 PASS (counts that hold both before and after); `SUMMARY: FAIL (11)`, exit 1. After Step 1 lands, F alone flips green while A–D stay red — the intended Step-2 baseline.

**Step 5 edit (docstring, line-count-neutral) — exact old→new line replacements:**

Old lines 4–8 of `src/claude_retry_proxy/forwarder.py`:
```
response is returned": the transport and policy helpers, the retry loop, the
compatibility and reasoning retries, the response-rewrite helpers, and the
config-swap drain protocol's state. The chat retry-nudge marker store lives in
chat_nudge.py and is re-exported here. The parent module imports this one;
this module never imports its parent.
```

New lines 4–8:
```
response is returned": the transport and policy helpers, the retry loop,
the compatibility and reasoning retries, and the config-swap drain
protocol's state. The chat retry-nudge marker store (chat_nudge.py) and
the anthropic-mode model projection (model_rewrite.py) are re-exported here.
The parent module imports this one; this module never imports its parent.
```

Before editing, re-verify the landmarks: the file's docstring is 9 lines (L1 `"""Upstream forward path for the Claude retry gateway.` through L9 `"""`), and the five old lines above sit verbatim at L4–L8. Drifted text or a different line layout is a **stop-and-report**, never an improvisation.

## Guidance for Tester

**Tests to create:**
- **Permanent:** none — the move is byte-identical and the existing suites are the regression net (the `test_response_model_rewrite_*` family covers behavior end-to-end; the `nesting-guard-rewrite-json-response` / `nesting-guard-rewrite-sse-first-event` gates cover the degrade paths in-process).
- **Temporary:** none.

**Tests to investigate for retirement:**
- Planner candidates: none — no behavior is removed or changed. **No test obsolescence identified.**
- Tester may identify additional candidates during test work.

**What to run (Step 3):** `python tests/test_claude_proxy.py` — the full suite must pass with the test count identical to the pre-change run (record both numbers in the session report). Spotlight assertions: the `test_response_model_rewrite_*` family and the two nesting-guard tests pass unchanged. The aggregator (`tests/test_claude_proxy.py`) and every `ALL_TESTS` list are untouched by this plan; a count change is a defect, not a result.

3. **Step 3: Full suite green, count preserved**
   → tester verify: `python tests/test_claude_proxy.py` exits 0; test count equals the pre-change count (no `ALL_TESTS` edits anywhere); the rewrite-family and nesting-guard tests pass.

## Summary

**Problem.** `forwarder.py` is the repo's only source file over the 1,000-line threshold (1,746 measured 2026-11-24). This is plan 1 of a size-reduction + modularity campaign identified by the 2026-11-24 `/refactor-split` survey; the survey's blast-radius ordering picked this cluster first because it is the largest verbatim-safe extraction with zero edits in the risky region (retry loop, streaming loops).

**What moves.** The response-model-rewrite pair — `_rewrite_sse_event` (L1605–1711) and `_rewrite_json_response` (L1714–1746) — into a new leaf `src/claude_retry_proxy/model_rewrite.py`, byte-identical, re-exported through forwarder. The pair is one concept (rewrite the upstream model name to the tier name in anthropic-format responses) behind two encodings (SSE event / JSON body). Both bodies read only leaves (`nesting`, `sinks`, `json`, `time`), so the two-direction closure holds: the moved bodies read nothing the parent keeps, and the new module never imports its parent. Callers are textually untouched: forwarder's two internal call sites (L1373, L1479) and server.py's streaming-loop call site (L293) resolve through the re-export. Anthropic mode is the only consumer — chat/response modes get the model written by their body transforms (verified at all three call sites 2026-11-24).

**Import surgery.** forwarder's `from .nesting import check_payload_nesting, nesting_event` line deletes outright — after the move both names have zero readers in forwarder (the gate asserts zero remaining references). `model_rewrite.py` carries its own pinned import whitelist. `json`/`time`/`log_trace` keep forwarder readers and stay.

**Alternatives considered and rejected:**
- Combine with `transforms_response.py` — different mode plumbing and task (response-mode format conversion vs anthropic-passthrough tier projection); co-location would be proximity, not concept.
- Fold in tier resolution (`extract_model`/`resolve_tier`) — request-side policy vs response-side projection is an honest conjunction, i.e. two clusters, and one cluster per plan forbids batching.
- Do the swap-drain owned-state conversion first — it is the repo's declared follow-up but touches ~17 retry-loop sites, admin_api's attribute writes, and ~30 test patch sites; blast-radius ordering puts this safe extraction first (user confirmed 2026-11-24).

**Out of scope:** the swap-drain owned-state conversion and `runtime_state`'s five globals (declared follow-up, campaign plan 3); tier-resolution extraction (plan 2); test-side partitions (10 files over the 1,500-line threshold, parallel track); the two monolith functions (`_forward_request_impl`, `_forward_core` — the forward path itself, no cluster); trace-field helpers (fail the utility-cluster cross-cutting criterion — single consumer). `doc/**` needs no change: `provider-modes.html#response-rewrite` and `architecture.html` describe behavior, not module layout (grep verified 2026-11-24).

**Not triggered:** mega-audit — 4 steps, 2 source files (< 5 / < 5 thresholds).

## Repo Mode

Public

*Detected at plan creation (`detect_repo_mode.py`, 2026-11-24). Determines: plan archival path, commit-message content, staged files.*

## Document Overrides

If the plan intentionally contradicts a documented rule (in `CLAUDE.md` or `doc/*`), declare the override here. An empty or absent table means zero tolerance — every documented rule is in force.

| Document | Rule Overridden | Reason |
|----------|----------------|--------|

## Proposed Changes

Each step includes verification checks tagged with confidence (see Prime Directive 4).
`(auto)` = mechanical, coder self-verifies. `(scripted)` = deterministic multi-step, coder runs provided script.
Every step must have at least one verification check executable by its owner (coder steps: coder checks; tester steps: tester verify; planner steps: Evidence).
Steps MUST use this numbered-list format exactly. The `### Step N:` heading format is deprecated and must not be used.

1. **Step 1: Create `model_rewrite.py` — rewrite pair byte-verbatim behind the pinned import whitelist**
   → coder verify (auto): `python3 -m py_compile src/claude_retry_proxy/model_rewrite.py` exits 0; file staged in git, not untracked
   → coder verify (scripted): `python3 tmp/verification/2026-11-24-extract-model-rewrite-step1.py` exits 0 — baseline RED recorded in Guidance for Coder

2. **Step 2: Excise the cluster from `forwarder.py`; re-export both names; relocate the reader-less nesting import**
   → coder verify (auto): isolation-env import smoke `python3 -c "import claude_retry_proxy.server"` exits 0
   → coder verify (scripted): `python3 tmp/verification/2026-11-24-extract-model-rewrite-step2.py` exits 0 — baseline RED recorded in Guidance for Coder

   <!-- UPDATED 2026-11-24 (/update-plan): Steps 1–2 completed by coder round 1 — gates GREEN unedited (11/11, 13/13), build pass. Step 5 added below from the coder-filed issue forwarder-docstring-stale. The Step 2 gate is a step-local snapshot; it is NOT re-run after Step 5 (though the Step 5 edit is line-count-neutral, so its D1 pin stays true regardless). -->

5. **Step 5: Fix `forwarder.py`'s module docstring — the in-source parallel of Step 4's CLAUDE.md row edit** (issue [forwarder-docstring-stale](./tmp/reports/2026-11-24-extract-model-rewrite-forwarder-docstring-stale.json))
   - Replace docstring lines 4–8 exactly as pinned in Guidance for Coder (Step 5 edit). Line-count-neutral: 9 docstring lines before and after; forwarder stays 1602 lines. No other line of the file changes.
   - → coder verify (auto): the docstring contains `model_rewrite.py` and no longer contains `response-rewrite helpers`; `python3 -m py_compile src/claude_retry_proxy/forwarder.py` exits 0; `wc -l src/claude_retry_proxy/forwarder.py` still reports 1602.

3. **Step 3: Full suite green, count preserved**
   → tester verify: `python tests/test_claude_proxy.py` exits 0; test count identical to pre-change; rewrite-family and nesting-guard tests pass

4. **Step 4: CLAUDE.md structure sync (planner)**
   → Evidence: `git diff CLAUDE.md` shows exactly the three planned hunks — the forwarder.py row edit, the new `model_rewrite.py` row, and the Refactoring-section sentence; no other doc files change

<!-- UPDATED 2026-11-24 (/update-plan): Step 5 added — coder round 2 (docstring fix, issue forwarder-docstring-stale). Step numbering jumps 2→5 to keep Steps 3–4 (tester/planner) stable; execution order is 1, 2, 5, 3, 4. -->

## Guidance for Planner

Documentation tasks executed by the planner (not the coder):

- **Files to modify:**
  - `./CLAUDE.md`
- **When:** after the coder finishes (Step 4), before the tester round's `/update-plan` lands `## Final Results`.
- **What to sync:**
  - Structure list: edit the `forwarder.py` row — remove "response model rewriting" from its mechanism list and add model_rewrite to its re-export sentence (alongside the existing chat_nudge one).
  - Insert a `model_rewrite.py` row immediately after the `forwarder.py` row: the anthropic-mode model projection (`_rewrite_sse_event` SSE message_start rewrite under server.py's 64 KB scan + `_rewrite_json_response` buffered-body rewrite); leaf imports only (json/time/nesting/sinks), never imports its parent; production callers reach it through forwarder's re-export.
  - Refactoring section: one sentence recording the 2026-11-24 model_rewrite extraction (campaign plan 1; forwarder.py 1,746 → 1,602 measured lines, byte-verbatim, re-exported) — no exact counts beyond this dated snapshot.
  - Checked and requiring no change (grep verified 2026-11-24): `doc/provider-modes.html#response-rewrite`, `doc/architecture.html`, `doc/test-catalog.html` (names functions, not modules), `README.md`.
- **`.claude/mega-audit-files.json`:** no declared-audit changes (file does not exist in this repo).

## History

One row per event (spec revision / mega-audit / review / implementation round). Conclusion = one-sentence outcome or what changed. Dismissed = compact dismissed-findings list for the reviewer — verbatim issue slugs linked as `[<slug>](<report-path>)`, no prose-only entries. Link to report files; never restate findings inline.

| Date | Event | Conclusion | Dismissed |
|------|-------|------------|-----------|
| 2026-11-24 | Initial plan | Campaign plan 1 (of the 2026-11-24 refactor-split survey): extract the response-rewrite pair from forwarder.py (1,746 lines) into model_rewrite.py — byte-verbatim, re-exported; both gates calibrated RED against the pre-change tree | — |
| 2026-11-24 | Spec revision (/update-plan) | Coder round 1 completed (both gates GREEN unedited, build pass); added Step 5 (coder, line-neutral forwarder.py docstring fix) from [forwarder-docstring-stale](./tmp/reports/2026-11-24-extract-model-rewrite-forwarder-docstring-stale.json), classified Plan Gap — doc-sync sweep missed in-source module docstrings | — |
| 2026-11-24 | Implementation round (coder) | Round 1: Steps 1–2 landed; step-1 gate GREEN 11/11, step-2 gate GREEN 13/13, unedited from the RED baseline; import smoke passes; forwarder.py 1,602 lines; report [session-coder](./tmp/reports/2026-11-24-extract-model-rewrite-coder-2026-11-24.json) | — |
| 2026-11-24 | Implementation round (coder) | Round 2: Step 5 landed per the pinned docstring lines; line-count-neutral (1,602 lines); gates correctly not re-run; report [session-coder](./tmp/reports/2026-11-24-extract-model-rewrite-coder-2026-11-24.json) | — |
| 2026-11-24 | Planner doc sync (Step 4) | CLAUDE.md: forwarder.py row edit + model_rewrite.py row inserted + Refactoring-section campaign sentence; doc/** and README verified to need no change (grep 2026-11-24) | — |
| 2026-11-24 | Implementation round (tester) | SUCCESS — 550/550 passed, count preserved (len(ALL_TESTS)==550); rewrite family 8/8 + both nesting guards green; both plan gates independently re-verified PASS; frozen re-export surface proven by namespace identity; [session-tester](./tmp/reports/2026-11-24-extract-model-rewrite-tester-2026-11-24.json) | — |
| 2026-11-24 | Issue resolution | forwarder-docstring-stale → Resolved on the tester report's confirmation (Step 5 verified in-tree and in the suite run) | — |
| 2026-11-24 | Review | Verdict: Issues found — non-blocking (0 Critical, 1 Warning, 3 Suggestions), plan ready to commit; byte-verbatim claim re-derived independently (HEAD-blob segment hashes, re-export namespace identity, consumer sweep). Fixed before Final Results: retire_inventory populated (8 entries incl. the tester scratch runner), CLAUDE.md counts parenthetical dropped, Step 4 Evidence line extended to the three-hunk reality. Report: [review](./tmp/reports/2026-11-24-extract-model-rewrite-review-2026-11-24.json) | [namespace-patch-hunch](./tmp/reports/2026-11-24-extract-model-rewrite-review-2026-11-24.json), [counters-semantics](./tmp/reports/2026-11-24-extract-model-rewrite-review-2026-11-24.json), [review-coverage-limits](./tmp/reports/2026-11-24-extract-model-rewrite-review-2026-11-24.json) |

## Plan Metadata

Fenced ```json block — the machine contract read by `parsePlanContext` (JSON-first, regex fallback). **Update it on every revision.**

```json
{
  "plan_id": "2026-11-24-extract-model-rewrite",
  "steps": [
    "Step 1: Create model_rewrite.py — rewrite pair byte-verbatim behind the pinned import whitelist",
    "Step 2: Excise the cluster from forwarder.py; re-export both names; relocate the reader-less nesting import",
    "Step 5: Fix forwarder.py's module docstring — the in-source parallel of Step 4's CLAUDE.md row edit",
    "Step 3: Full suite green, count preserved",
    "Step 4: CLAUDE.md structure sync (planner)"
  ],
  "coder_files": [
    "src/claude_retry_proxy/model_rewrite.py",
    "src/claude_retry_proxy/forwarder.py"
  ],
  "tester_files": [],
  "doc_files": ["./CLAUDE.md"],
  "verification_scripts": [
    "./tmp/verification/2026-11-24-extract-model-rewrite-step1.py",
    "./tmp/verification/2026-11-24-extract-model-rewrite-step2.py"
  ],
  "retire_inventory": [
    "./tmp/reports/2026-11-24-extract-model-rewrite-coder-2026-11-24.json",
    "./tmp/reports/2026-11-24-extract-model-rewrite-tester-2026-11-24.json",
    "./tmp/reports/2026-11-24-extract-model-rewrite-tester-2026-11-24-suite.log",
    "./tmp/reports/2026-11-24-extract-model-rewrite-review-2026-11-24.json",
    "./tmp/verification/2026-11-24-extract-model-rewrite-step1.py",
    "./tmp/verification/2026-11-24-extract-model-rewrite-step2.py",
    "./tmp/verification/__pycache__",
    "./tmp/run_full_suite.py"
  ],
  "repo_mode": "Public",
  "document_overrides": []
}
```

## Audit Accumulation

*Counters reset when mega-audit runs. Used by Phase 5 entry trigger.*

| Counter | Value | Last Updated |
|---------|-------|--------------|
| issues_resolved_since_audit | 0 | 2026-11-24 |
| steps_changed_since_audit | 1 | 2026-11-24 |
| files_changed_since_audit | 0 | 2026-11-24 |

## Documentation

Plan-authored gate scripts live at `./tmp/verification/2026-11-24-extract-model-rewrite-step{1,2}.py`; both are static-analysis gates (AST + pinned sha256 segments) that never import the package, so they need no spawn isolation. The survey backing this campaign: `/refactor-split` survey run 2026-11-24 (thresholds: code 1,000 / tests 1,500, measured `wc -l` physical lines); no file-size deferred-issue report exists — the survey is the living tracker.

## Final Results

**Status: COMPLETED** — 2026-11-24

**What was built.** The response-model-rewrite pair (`_rewrite_sse_event`, `_rewrite_json_response`) moved byte-verbatim from `forwarder.py` (former L1605–1746) into the new leaf `src/claude_retry_proxy/model_rewrite.py`, re-exported through forwarder's import block; forwarder's reader-less `.nesting` import was replaced by the re-export (both names had zero remaining forwarder readers); forwarder.py went 1,746 → 1,602 lines and its module docstring was rewritten line-neutrally (Step 5, issue fix). `./CLAUDE.md` structure list + Refactoring section synced (Step 4). All five steps (1, 2, 5, 3, 4) completed across two coder rounds, one tester round, and the planner doc pass.

**Verification.** Both static gates GREEN unedited from their RED baselines (Step 1: 11/11 — sha256-pinned byte identity + import whitelist; Step 2: 13/13 — seam, re-export, zero stray references), independently re-verified by the tester and re-derived by the reviewer against the HEAD blob. Full suite: **550/550 passed, 0 failed, 0 skipped; count preserved** (no `ALL_TESTS` edits). Frozen re-export surface proven by namespace identity (`srv`/`fwd`/`mr` attribute equality). Import smoke and `py_compile` clean. Reviewer: **0 Critical, 1 Warning, 3 Suggestions** — the Warning (retire_inventory) and two Suggestions fixed pre-Final-Results; report at [review](./tmp/reports/2026-11-24-extract-model-rewrite-review-2026-11-24.json).

**Known caveats (reviewer hunches + coverage limits, acknowledged):**
- Namespace-patch trap for future test authors: the moved pair now binds `log_trace`/`check_payload_nesting`/`nesting_event` in `model_rewrite`'s namespace — patching `forwarder.<name>` would not reach them. No current test does this; flagged for the next test author.
- Packaging verified by configuration only: `[tool.setuptools.packages.find]` with `where = ['src']` picks the module up by directory and the in-process import resolved to the repo's src copy; no wheel build was run.
- No linter run; moved bodies are byte-identical to HEAD, so any style deviation is pre-existing.
- The reviewer re-read the suite log rather than re-running the suite (the tester ran it: 550/550).

**Deferred issues.** None from this plan. The two standing deferrals (`admin-body-read-timeout`, `sink-warning-in-process-unit-tests`) predate this plan, are unrelated to it, and remain open on disk. No prior-plan deferred issue was resolved by this work (no Cross-References section).

**Transient artifacts (retire_inventory, for the post-commit sweep).** 8 entries recorded in Plan Metadata: 4 reports (coder, tester, suite log, review), 2 gate scripts, `tmp/verification/__pycache__`, and the tester scratch runner `tmp/run_full_suite.py` (named per the reviewer's finding, giving it a sweep owner). The issue report `forwarder-docstring-stale` is not in the inventory — as a Resolved issue it retires via `/update-and-commit` Step 9.6, not the terminal sweep.
