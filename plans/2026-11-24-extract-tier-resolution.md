# Plan: Extract the tier-resolution pair into tier_resolution.py

**Plan ID:** 2026-11-24-extract-tier-resolution
**Created:** 2026-11-24

## Issue Log

Rows ordered newest-first (latest issues at top). New issues are prepended; resolved issues stay in place with updated status.

| Issue | Status | Found | Resolved | Resolved By |
|-------|--------|-------|----------|-------------|
| [forwarder-docstring-stale](./tmp/reports/2026-11-24-extract-tier-resolution-forwarder-docstring-stale.json) | Resolved | 2026-11-24 | 2026-11-24 | [coder round 3](./tmp/reports/2026-11-24-extract-tier-resolution-coder-2026-11-24.json) — Step 5 applied per pin, step-2 gate 13/13 proving line-neutrality |
| arch-doc-extract-model-contract — pre-existing doc/code imprecision (tester prose, no report): architecture.html Step 1 box claimed extract_model returns "unknown" for unparseable bodies; the code returns (None, "invalid_json") | Resolved | 2026-11-24 | 2026-11-24 | planner — Step 1 box rewritten to the five-outcome contract (this session) |
| trace-doc-extract-model-parenthetical — pre-existing doc/code imprecision (tester prose, no report): trace-log.html model-field parenthetical read "returns None" as covering the no-string-model case, which returns ("unknown", None) | Resolved | 2026-11-24 | 2026-11-24 | planner — parenthetical corrected to the per-case returns (this session) |
| [step2-d1-linecount](./tmp/reports/2026-11-24-extract-tier-resolution-step2-d1-linecount.json) | Resolved | 2026-11-24 | 2026-11-24 | [coder round 2](./tmp/reports/2026-11-24-extract-tier-resolution-coder-2026-11-24.json) — corrected gate 13/13 (also planner-verified pre-launch); tester re-runs both gates in Step 3 |

## Guidance for Coder

**Files to modify:**
- `src/claude_retry_proxy/tier_resolution.py` (new)
- `src/claude_retry_proxy/forwarder.py`

**Step-by-step with verification:** each step below has coder checks tagged `(auto)` or `(scripted)`. The coder self-verifies `(auto)` checks and runs the provided script for `(scripted)` checks. Tester owns the behavioral checks. See coder Prime Directive 4.

**Module-surface count table (whole plan):**

| Kind | Change | Count |
|---|---|---|
| Behavioral | none — bodies byte-identical | 0 |
| Module-surface | `forwarder.py`: −2 top-level `FunctionDef`s (`extract_model`, `resolve_tier`), −1 section banner (3 lines, moves verbatim), +1 `from .tier_resolution import (…)` re-export line carrying both names | −2 defs / −1 banner / +1 import |
| Module-surface | `tier_resolution.py`: +1 module, +2 top-level `FunctionDef`s, +1 banner (moved verbatim), imports per the pinned whitelist (`import json` only) | +2 defs |
| Names resolvable through `forwarder` | unchanged — both names attribute-resolve via re-export (server.py's import/call and forwarder's internal call sites are untouched) | 0 |
| Implementation | none — verbatim move | 0 |

**Frozen-surface evidence lines (names re-exported because callers read them):**
- `server.py` L54 imports `extract_model` from `.forwarder` and calls it at L615 — unchanged.
- `forwarder.py` calls both internally (L700 `extract_model`, L711 `resolve_tier`, inside `_forward_request_impl`) — unchanged; the names resolve through the re-export.
- No test imports either name (grep verified 2026-11-24: `tests/test_cli.py` L820, `tests/test_admin.py` L1670, `admin_api.py` L305, `config.py` L475 mention `resolve_tier` in comments only). No test or script imports anything via `from claude_retry_proxy.forwarder import …`.

**Import whitelist for `tier_resolution.py` (pinned; anything else is a plan revision):**

```python
import json
```

One absolute import, zero from-imports — `resolve_tier` needs nothing external and the module never imports its parent or any sibling. `json` keeps its forwarder reader (`_error_body` L274 `json.dumps`), so forwarder's import block gains one line and loses none.

**Deletion range and seam (Step 2):** before cutting, re-verify every landmark on the live file — L1534 == `        client.close()`, L1535 == blank, L1536 == blank, L1537–1539 == the banner (`# ---------------------------------------------------------------------------` / `# Model extraction and tier resolution` / `# ---------------------------------------------------------------------------`), L1540 == blank, L1541 == `def extract_model(body_bytes):`, L1568 == `def resolve_tier(model_name, config):`, L1602 == `    return "unknown"`, total 1602 lines. A drifted file, or a zero-length remaining range, is a **stop-and-report**, never an improvisation. Delete lines 1535–1602 (the two separator blanks plus banner plus blank plus both functions, through EOF) so forwarder's last line is the pre-edit L1534 content (`        client.close()`) and the file totals **1535** lines (1602 baseline + 1 import line from Edit A − 68 deleted; the import insertion shifts the surviving tail down one position). The banner moves **verbatim into the new module** (by decision, not accident — it heads exactly this cluster).

**Step 5 edit (docstring, line-count-neutral) — exact old→new line replacements:** (added by the 2026-11-24 post-tester spec revision, issue forwarder-docstring-stale)

Old lines 6–8 of `src/claude_retry_proxy/forwarder.py`:
```
protocol's state. The chat retry-nudge marker store (chat_nudge.py) and
the anthropic-mode model projection (model_rewrite.py) are re-exported here.
The parent module imports this one; this module never imports its parent.
```

New lines 6–8:
```
protocol's state. Re-exported here: the nudge store (chat_nudge.py), the
model projection (model_rewrite.py), the tier pair (tier_resolution.py).
The parent module imports this one; this module never imports its parent.
```

Line-count-neutral: the docstring stays 9 lines (L1 opener, L2 blank, L3–L8 body, L9 closer) and forwarder stays **1535** lines (the equation stands: 1602 + 1 import − 68 deleted = 1535 — D1 needs no re-derivation). Before editing, re-verify the landmarks: docstring is 9 lines, the three old lines sit verbatim at L6–L8. Drifted text is a **stop-and-report**. Only these three lines change; no other line of the file is touched. (Second recurrence of the campaign's donor-docstring gap — plan 1 hit the identical gap; the durable checklist entry is recorded in planner memory: extraction plans sweep the donor module's in-source docstring.)

**Untracked-file rule:** `git add src/claude_retry_proxy/tier_resolution.py` the moment Step 1's file exists.

**New-module scaffolding (Step 1) — the module docstring and spacing are new; everything from the banner down is moved bytes. Exact text:**

```python
"""Request model/tier resolution for the Claude retry gateway.

extract_model(body_bytes) pulls the client-requested model name out of the
request body (total: exactly five outcomes, never raising). resolve_tier(
model_name, config) maps that name onto a serving tier — direct match,
reverse lookup over the configured tiers, then keyword pattern match. Pure
policy leaves consumed by server.py at request entry and by forwarder's
forward path (whose compat/reasoning retries re-enter it). Stdlib-only
(json); this module never imports its parent or any sibling domain module.
"""

import json


# ---------------------------------------------------------------------------
# Model extraction and tier resolution
# ---------------------------------------------------------------------------

<extract_model — byte-verbatim from forwarder L1541–1565>

<two blank lines>

<resolve_tier — byte-verbatim from forwarder L1568–1602>
```

Banner, blank, first def (matching the moved region's internal spacing L1539→1540→1541); two blank lines between the functions (L1566–1567); file ends with `    return "unknown"` + a single trailing newline.

1. **Step 1: Create `src/claude_retry_proxy/tier_resolution.py` — the resolution pair byte-verbatim behind the pinned one-line import whitelist**
   - Assemble per the scaffolding block above; no renames, no reordering, no docstring or comment edits inside the moved bodies, no bug fixes.
   - Run `git add src/claude_retry_proxy/tier_resolution.py`.
   - → coder verify (auto): `python3 -m py_compile src/claude_retry_proxy/tier_resolution.py` exits 0; the file is git-tracked (`git status --porcelain` shows it staged, not untracked).
   - → coder verify (scripted): `python3 tmp/verification/2026-11-24-extract-tier-resolution-step1.py` exits 0.
     Evidence (baseline RED, 2026-11-24 pre-change tree, script unedited): `FAIL module file exists`, `FAIL segment sha256 extract_model -- module absent`, `FAIL segment sha256 resolve_tier -- module absent`, `FAIL banner segment sha256 -- module absent`, `SUMMARY: FAIL (4)`, exit 1.

2. **Step 2: Excise the cluster from `forwarder.py`; re-export both names**
   - Edit A (import addition): insert `from .tier_resolution import (extract_model, resolve_tier)` immediately after line 37 `from .model_rewrite import (_rewrite_json_response, _rewrite_sse_event)` — a pure addition; no import line is deleted or narrowed (json/time keep readers in forwarder).
   - Edit B (tail excision): after re-verifying the landmarks above, delete lines 1535–1602 through EOF.
   - Post-conditions: forwarder.py is **1535** lines (1602 + 1 import − 68 deleted) ending `        client.close()` + newline; the suite-facing surface is unchanged (server.py and forwarder's internal calls resolve through the re-export).
   - → coder verify (auto): import smoke with the canonical isolation env — `PROXY_TRACE_FILE=$(mktemp -d)/t.jsonl PROXY_STATE_FILE=$(mktemp -d)/s.json PROXY_FEATURE_COMPAT_FILE=$(mktemp -d)/f.json python3 -c "import claude_retry_proxy.server"` exits 0.
   - → coder verify (scripted): `python3 tmp/verification/2026-11-24-extract-tier-resolution-step2.py` exits 0.
     Evidence (baseline RED, 2026-11-24 pre-change tree, script unedited): checks A1, B1, B2, B3, D1–D4, F FAIL (forwarder still defines the pair at 1602 lines, no re-export, module absent); E1/E2/E3 PASS (counts that hold from Step 1 on); `SUMMARY: FAIL (10)`, exit 1. After Step 1 lands, F alone flips green while A–D stay red — the intended Step-2 baseline.

## Guidance for Tester

**Tests to create:**
- **Permanent:** none — the move is byte-identical and the existing suites are the regression net (`test_tier_routing.py` exercises tier resolution end-to-end; `test_admin.py`/`test_lifecycle.py` cover the request entry).
- **Temporary:** none.

**Tests to investigate for retirement:**
- Planner candidates: none — no behavior is removed or changed. **No test obsolescence identified.**
- Tester may identify additional candidates during test work.

**What to run (Step 3):** `python tests/test_claude_proxy.py` — the full suite must pass with the test count identical to the pre-change run (record both numbers in the session report; the count must be 550, unchanged by this plan — no `ALL_TESTS` edits landed). Spotlight: the tier-routing family (direct match, reverse lookup, pattern match, unknown-model 400) passes unchanged.

3. **Step 3: Full suite green, count preserved**
   → tester verify: `python tests/test_claude_proxy.py` exits 0; test count equals the pre-change count (550); the tier-routing family passes.

## Summary

**Problem.** `forwarder.py` remains the only source file over the 1,000-line threshold (1,602 after plan 1). This is **plan 2 of the size-reduction + modularity campaign** identified by the 2026-11-24 `/refactor-split` survey and approved by the user; the survey's blast-radius ordering sequenced it here as the minimum-read cluster.

**What moves.** The tier-resolution pair — `extract_model` (L1541–1565) and `resolve_tier` (L1568–1602, file tail) — plus its section banner into a new leaf `src/claude_retry_proxy/tier_resolution.py`, byte-identical, re-exported through forwarder. **Membership: utility cluster (second genus)** — the family path fails (no shared caller API; the functions never call each other and share no helpers), and the four criteria admit: task identity (one nameable task — "resolve the request's model name and serving tier" — with `extract_model` the input leg and `resolve_tier` the mapping leg; the repo's own vocabulary and `doc/architecture.html#tier-resolution` already treat them as one mechanism), leaf purity (`extract_model` reads only `json`; `resolve_tier` is fully pure — verified), cross-cutting (consumed by two independent domain modules: server.py L615 and forwarder.py L700/L711), bounded size. The two-consumer structure is also what forbids merging into either consumer.

**Closure.** The moved bodies read only `json` (and nothing, for `resolve_tier`) — the strictest closure of the campaign: `import json` is the entire import whitelist, zero repo imports, so no import-cycle risk exists. Import surgery is a pure addition: `json` keeps its forwarder reader (`_error_body`), no line is deleted. Callers are textually untouched under the re-export.

**Alternatives considered and rejected:** merge into `model_rewrite.py` (request-side vs response-side — two clusters); merge into `config.py` (task mismatch — config pipeline vs consumer of the config dict); merge into `server.py` (fails the single-consumer rule AND creates an import cycle); keep in forwarder (the over-threshold file being reduced); split the pair into two files (fragments one decision across two import surfaces; each leg has the same two consumers). Name: `tier_resolution.py` (user-confirmed) — matches the repo's existing "tier resolution" vocabulary, paralleling plan 1's `model_rewrite.py`.

**Out of scope:** swap-drain owned-state conversion (plan 3, declared follow-up); swap-drain cluster extraction (plan 4); test-side partitions (12 files over the 1,500-line threshold, parallel track); `resolve_api_key` (stays — it reads vendor entries, part of the forward path, not this cluster); the two monolith functions. `doc/` needs no change: `architecture.html#tier-resolution` and `trace-log.html` name the functions, not the module (grep verified 2026-11-24). CLAUDE.md Refactoring sentence carries **no line counts** (plan 1's review finding applied).

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

1. **Step 1: Create `tier_resolution.py` — resolution pair byte-verbatim behind the pinned import whitelist**
   → coder verify (auto): `python3 -m py_compile src/claude_retry_proxy/tier_resolution.py` exits 0; file staged in git, not untracked
   → coder verify (scripted): `python3 tmp/verification/2026-11-24-extract-tier-resolution-step1.py` exits 0 — baseline RED recorded in Guidance for Coder

2. **Step 2: Excise the cluster from `forwarder.py`; re-export both names**
   → coder verify (auto): isolation-env import smoke `python3 -c "import claude_retry_proxy.server"` exits 0
   → coder verify (scripted): `python3 tmp/verification/2026-11-24-extract-tier-resolution-step2.py` exits 0 — baseline RED recorded in Guidance for Coder

3. **Step 3: Full suite green, count preserved**
   → tester verify: `python tests/test_claude_proxy.py` exits 0; test count identical to pre-change (550); tier-routing family passes

<!-- UPDATED 2026-11-24 (/update-plan post-tester): Steps 1–4 executed (rounds 1–2 coder; tester SUCCESS 550/550; planner doc sync). Step 5 added from [forwarder-docstring-stale](./tmp/reports/2026-11-24-extract-tier-resolution-forwarder-docstring-stale.json) — coder round 3, line-neutral docstring fix. Execution order 1, 2, 5, 3, 4. -->

5. **Step 5: Fix `forwarder.py`'s module docstring — the third re-export leaf** (issue [forwarder-docstring-stale](./tmp/reports/2026-11-24-extract-tier-resolution-forwarder-docstring-stale.json))
   - Replace docstring lines 6–8 exactly as pinned in Guidance for Coder (Step 5 edit). Line-count-neutral: forwarder stays 1535 lines; both gates' expectations unchanged.
   - → coder verify (auto): the docstring contains `tier_resolution.py` and no longer contains `marker store`; `python3 -m py_compile src/claude_retry_proxy/forwarder.py` exits 0; line count still 1535; `python3 tmp/verification/2026-11-24-extract-tier-resolution-step2.py` exits 0 (13/13 — proves line-neutrality mechanically).

4. **Step 4: CLAUDE.md structure sync + tester-surfaced doc fixes (planner)**
   → Evidence: `git diff CLAUDE.md` shows exactly the three planned hunks (forwarder row, new tier_resolution row, Refactoring sentence); `git diff doc/` shows exactly the two tester-surfaced contract fixes (architecture.html Step-1 box, trace-log.html model-field parenthetical); no other doc files change

## Guidance for Planner

Documentation tasks executed by the planner (not the coder):

- **Files to modify:**
  - `./CLAUDE.md`
  - `./doc/architecture.html`
  - `./doc/trace-log.html`
- **When:** after the coder finishes (Step 4), before the tester round's `/update-plan` lands `## Final Results`.
- **What to sync:**
  - Structure list: edit the `forwarder.py` row — remove "`extract_model`/`resolve_tier` tier resolution" from its mechanism list and add tier_resolution to its re-export sentence (alongside chat_nudge and model_rewrite).
  - Insert a `tier_resolution.py` row immediately after the `model_rewrite.py` row: the request model/tier resolution leaf (`extract_model` total five-outcome body parse + `resolve_tier` four-rule tier mapping — direct, reverse lookup, pattern); utility-cluster leaf (json-only imports), never imports its parent; consumed by server.py at request entry and forwarder's forward path, reaching it through forwarder's re-export.
  - Refactoring section: one sentence recording the 2026-11-24 tier-resolution extraction (campaign plan 2, byte-verbatim, re-exported) — **no line counts** (the section's standing no-counts rule; plan 1's review finding).
  - Checked and fixed this session (tester-surfaced pre-existing imprecisions, Issue Log rows 2–3): `doc/architecture.html` Step-1 box rewritten to extract_model's five-outcome contract; `doc/trace-log.html` model-field parenthetical corrected to the per-case returns. `README.md` unaffected (grep verified 2026-11-24).
- **`.claude/mega-audit-files.json`:** no declared-audit changes (file does not exist in this repo).

## History

One row per event (spec revision / mega-audit / review / implementation round). Conclusion = one-sentence outcome or what changed. Dismissed = compact dismissed-findings list for the reviewer — verbatim issue slugs linked as `[<slug>](<report-path>)`, no prose-only entries. Link to report files; never restate findings inline.

| Date | Event | Conclusion | Dismissed |
|------|-------|------------|-----------|
| 2026-11-24 | Initial plan | Campaign plan 2: extract the tier-resolution pair from forwarder.py (1,602 lines) into tier_resolution.py — utility-cluster leaf, byte-verbatim, re-exported; both gates calibrated RED against the pre-change tree (step 1: FAIL(4); step 2: FAIL(10) with E1–E3 green) | — |
| 2026-11-24 | Implementation round (coder) | Round 1: Step 1 complete (Step-1 gate GREEN — segments + banner byte-identical); Step 2 edits applied correctly per plan prose (re-export wired, landmarks matched, import smoke green) but **blocked at the Step-2 scripted gate**: D1 pinned 1534 while the mandated Edit A+B arithmetic yields 1535 — an unsatisfiable gate, plan defect; 12/13 checks passed; filed [step2-d1-linecount](./tmp/reports/2026-11-24-extract-tier-resolution-step2-d1-linecount.json); report [session-coder](./tmp/reports/2026-11-24-extract-tier-resolution-coder-2026-11-24.json) | — |
| 2026-11-24 | Spec revision (/update-plan) | [step2-d1-linecount](./tmp/reports/2026-11-24-extract-tier-resolution-step2-d1-linecount.json) classified **Plan Error** (planner arithmetic dropped Edit A's +1) and fixed: gate `EXPECTED_LINES` 1534 → 1535 (+docstring), plan post-condition prose corrected (Guidance for Coder seam paragraph + Step 2); corrected gate verified **13/13 GREEN on the applied tree** by the planner, still RED-valid against the pre-change tree (1602 ≠ 1535); no source change required | — |
| 2026-11-24 | Implementation round (coder) | Round 2: no source changes; Step-1 gate PASS, corrected Step-2 gate 13/13 (D1 = 1535), build pass, import smoke green resolving to the repo src copy; report [session-coder](./tmp/reports/2026-11-24-extract-tier-resolution-coder-2026-11-24.json); step2-d1-linecount → Resolved on this evidence | — |
| 2026-11-24 | Implementation round (tester) | SUCCESS — 550/550 passed, count preserved; tier-routing family green incl. the unknown-model 400 path; both gates independently re-verified (step1 PASS, step2 13/13, D1=1535); runtime namespace identity proven (forwarder.extract_model is tier_resolution.extract_model); internal call sites at L701/L712 (+1 import shift, not drift); filed [forwarder-docstring-stale](./tmp/reports/2026-11-24-extract-tier-resolution-forwarder-docstring-stale.json) (docstring names 2 of 3 re-exported leaves — second recurrence of the campaign's donor-docstring gap); report [session-tester](./tmp/reports/2026-11-24-extract-tier-resolution-tester-2026-11-24.json) | — |
| 2026-11-24 | Spec revision (/update-plan) | Added Step 5 (coder, line-neutral forwarder docstring fix naming the third re-export leaf) from the tester-filed issue; planner applied the two tester-surfaced pre-existing doc fixes in-tree this session (architecture.html five-outcome contract, trace-log.html parenthetical — Issue Log rows 2–3 Resolved); Guidance for Planner/Step 4 Evidence extended to the two doc hunks; campaign checklist lesson recorded in planner memory (extraction plans sweep the donor module's in-source docstring) | — |
| 2026-11-24 | Implementation round (coder) | Round 3: Step 5 applied per the pinned lines (old text verified verbatim at L6–L8 pre-edit); docstring names tier_resolution.py, "marker store" gone; forwarder stays 1535 lines; step-2 gate 13/13 (line-neutrality proven); build pass; report [session-coder](./tmp/reports/2026-11-24-extract-tier-resolution-coder-2026-11-24.json); forwarder-docstring-stale → Resolved on this evidence | — |
| 2026-11-24 | Review | Verdict: Issues found — non-blocking (0 Critical, 1 Warning, 2 Suggestions), ready to commit; byte-identity re-derived from the git-diff-deleted region, campaign-recurrence sweep clean (no stale ownership/re-export prose anywhere). Fixed pre-Final-Results: retire_inventory populated (6 shape-valid entries; the 2 issue reports excluded — Step 9.6 owns them) and the architecture.html five-outcomes box now enumerates all five (reviewer count nit). Dispositions: the reviewer's parse-guards hunch measured CONFIRMED (stale `test_deep_nested_body_invalid_json` refs) and deferred standalone as [defer-issue-parse-guards-stale-test-ref](./tmp/reports/defer-issue-parse-guards-stale-test-ref.json) — test-file lane, no plan row at filing; plan-1 sweep residue (suite.log + run_full_suite.py) acknowledged, still awaiting the user's explicit word. Report: [review](./tmp/reports/2026-11-24-extract-tier-resolution-review-2026-11-24.json) | [import-block-ordering](./tmp/reports/2026-11-24-extract-tier-resolution-review-2026-11-24.json), [no-direct-contract-unit-tests](./tmp/reports/2026-11-24-extract-tier-resolution-review-2026-11-24.json) |

## Plan Metadata

Fenced ```json block — the machine contract read by `parsePlanContext` (JSON-first, regex fallback). **Update it on every revision.**

```json
{
  "plan_id": "2026-11-24-extract-tier-resolution",
  "steps": [
    "Step 1: Create tier_resolution.py — resolution pair byte-verbatim behind the pinned import whitelist",
    "Step 2: Excise the cluster from forwarder.py; re-export both names",
    "Step 5: Fix forwarder.py's module docstring — the third re-export leaf",
    "Step 3: Full suite green, count preserved",
    "Step 4: CLAUDE.md structure sync + tester-surfaced doc fixes (planner)"
  ],
  "coder_files": [
    "src/claude_retry_proxy/tier_resolution.py",
    "src/claude_retry_proxy/forwarder.py"
  ],
  "tester_files": [],
  "doc_files": ["./CLAUDE.md", "./doc/architecture.html", "./doc/trace-log.html"],
  "verification_scripts": [
    "./tmp/verification/2026-11-24-extract-tier-resolution-step1.py",
    "./tmp/verification/2026-11-24-extract-tier-resolution-step2.py"
  ],
  "retire_inventory": [
    "./tmp/reports/2026-11-24-extract-tier-resolution-coder-2026-11-24.json",
    "./tmp/reports/2026-11-24-extract-tier-resolution-tester-2026-11-24.json",
    "./tmp/reports/2026-11-24-extract-tier-resolution-review-2026-11-24.json",
    "./tmp/verification/2026-11-24-extract-tier-resolution-step1.py",
    "./tmp/verification/2026-11-24-extract-tier-resolution-step2.py",
    "./tmp/verification/__pycache__"
  ],
  "repo_mode": "Public",
  "document_overrides": []
}
```

## Audit Accumulation

*Counters reset when mega-audit runs. Used by Phase 5 entry trigger.*

| Counter | Value | Last Updated |
|---------|-------|--------------|
| issues_resolved_since_audit | 4 | 2026-11-24 |
| steps_changed_since_audit | 2 | 2026-11-24 |
| files_changed_since_audit | 2 | 2026-11-24 |

## Documentation

Plan-authored gate scripts live at `./tmp/verification/2026-11-24-extract-tier-resolution-step{1,2}.py`; both are static-analysis gates (AST + pinned sha256 segments + pinned seam) that never import the package. The campaign context: plan 1 (`2026-11-24-extract-model-rewrite`) landed the response-rewrite leaf; this plan is the survey's minimum-read cluster; plans 3–4 (swap-drain owned-state conversion, then cluster extraction) and the test-partition track remain.

## Final Results

**Status: COMPLETED** — 2026-11-24

**What was built.** The tier-resolution pair (`extract_model`, `resolve_tier`) plus its section banner moved byte-verbatim from `forwarder.py` (former L1537–1602) into the new utility-cluster leaf `src/claude_retry_proxy/tier_resolution.py`, re-exported through forwarder's import block (one added line; no import lost its reader). forwarder.py: 1,602 → **1,535 lines** (1602 + 1 import − 68 deleted). The module docstring's re-export enumeration now names all three leaf surfaces (Step 5). CLAUDE.md synced (forwarder row, new `tier_resolution.py` row, count-free Refactoring sentence); two tester-surfaced pre-existing doc imprecisions fixed (`doc/architecture.html` five-outcome contract, `doc/trace-log.html` parenthetical). All five steps (1, 2, 5, 3, 4) completed across three coder rounds, one tester round, and the planner doc pass.

**Verification.** Step-1 gate PASS (segments + banner sha256 byte-identical; import whitelist exactly `{json}`, zero from-imports); Step-2 gate 13/13 (re-export, seam, D1 = 1535) — independently run by coder round 2, the tester, and the planner; full suite **550/550 passed, 0 failed, count preserved**; runtime namespace identity proven (`forwarder.extract_model is tier_resolution.extract_model`, same for `resolve_tier`). Round-1's blocking defect was a planner gate-arithmetic error (D1 pinned 1534, omitting Edit A's +1) — the coder filed it, the spec revision fixed it, and the equation is now stated beside the pin. Reviewer: **0 Critical, 1 Warning, 2 Suggestions** — the Warning (retire_inventory) and the enumeration nit fixed pre-Final-Results; report at [review](./tmp/reports/2026-11-24-extract-tier-resolution-review-2026-11-24.json).

**Known caveats (acknowledged, non-blocking):**
- The five-outcome/four-rule contracts are covered end-to-end only (tier-routing family through a live proxy); no direct unit test exercises them in isolation — tester's domain, reviewer hunch acknowledged.
- forwarder's import block stays non-alphabetical by plan-pinned position (extracted-leaf imports grouped after their anchors).
- Plan-1 sweep residue survives awaiting the user's explicit word: `tmp/reports/2026-11-24-extract-model-rewrite-tester-2026-11-24-suite.log` and `tmp/run_full_suite.py` (both shape-rejected at plan 1's sweep authoring; retiring them needs only your instruction).

**Deferred issues.** One filed by this plan's review, standalone (no plan row at filing): [defer-issue-parse-guards-stale-test-ref](./tmp/reports/defer-issue-parse-guards-stale-test-ref.json) — stale test-name cross-references in `tests/test_parse_guards.py` (test-file lane; a natural adoption for the test-partition track). Standing unrelated deferrals remain open on disk: `admin-body-read-timeout`, `sink-warning-in-process-unit-tests`. No prior-plan deferred issue was resolved by this work (no Cross-References section).

**Transient artifacts (retire_inventory, for the post-commit sweep).** 6 shape-valid entries recorded in Plan Metadata: 3 reports (coder, tester, review), 2 gate scripts, `tmp/verification/__pycache__`. The two issue reports (`step2-d1-linecount`, `forwarder-docstring-stale`) are excluded by design — as Resolved issues they retire via `/update-and-commit` Step 9.6, not the terminal sweep.
