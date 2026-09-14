# Plan: Commit the doc-anchor checker and stop hot-linking the README
**Project:** D:\proj\claude-retry-proxy
**Plan ID:** 2026-09-14-commit-doc-anchor-check
**Created:** 2026-09-14

## Issue Log

| Issue | Status | Found | Resolved | Resolved By |
|-------|--------|-------|----------|-------------|
| [test-docs-temp-tree-leak](./tmp/reports/2026-09-14-commit-doc-anchor-check-test-docs-temp-tree-leak.json) | Resolved | 2026-09-14 | 2026-09-14 | [tester](./tmp/reports/2026-09-14-commit-doc-anchor-check-test-docs-temp-tree-leak.json) |
| [no-proxy-stop-trace-warning](./tmp/reports/defer-issue-no-proxy-stop-trace-warning.json) | Open | 2026-09-14 | — | — |
| [parity-figure-stale](./tmp/reports/2026-09-14-commit-doc-anchor-check-parity-figure-stale.json) | Resolved | 2026-09-14 | 2026-09-14 | [tester](./tmp/reports/2026-09-14-commit-doc-anchor-check-parity-figure-stale.json) |
| [review-anchor-resolver-not-committed](./tmp/reports/defer-issue-review-anchor-resolver-not-committed.json) | Resolved | 2026-09-13 | 2026-09-14 | [tester](./tmp/reports/2026-09-14-commit-doc-anchor-check-tester-2026-09-14.json) |
| [review-content-readme-link-raw-markdown](./tmp/reports/defer-issue-review-content-readme-link-raw-markdown.json) | Resolved | 2026-09-13 | 2026-09-14 | planner |

## Guidance for Coder

**Files to modify:** `scripts/check_doc_anchors.py` (new)

**Do not:** alter any check body, regex, allowlist, or marker list beyond Step 1's
three sanctioned changes. Write tests, edit doc/test files, or touch
`doc/content.html` — those lanes belong to the tester and planner. The current
tree is verified healthy (229 anchors resolve, 8 pages scanned, exit 0), so an
exit-0 failure during your port means a port regression or an out-of-plan doc
edit — report it, do not "fix" doc content.

Steps and verification: `## Proposed Changes` Step 1.

## Guidance for Tester

**Tests to create:**
- **Permanent:** `tests/test_docs.py` — a per-area module of cases invoking the
  committed checker `scripts/check_doc_anchors.py`: a real-tree success case
  (the regression net for every CLAUDE.md/README.md/doc anchor, with a
  positive anchor-count floor) and a planted-failure suite on a temp doc tree
  covering every failure class including the exit-2 statuses. Detailed case
  list in `## Proposed Changes` Step 2.
- **Modify:** `tests/test_claude_proxy.py` — import `ALL_TESTS` from
  `test_docs` and append it at the end of the aggregator tuple.

**Tests to investigate for retirement:** No test obsolescence identified.
(Adding a module and an aggregator import retires nothing.)

Steps and verification: `## Proposed Changes` Step 2.

## Summary

Two open deferred issues from the 2026-09-12 doc-tree review, both fixed here.

**#1 — nothing committed catches a dead doc anchor.** In the 2026-09-14
baseline run, CLAUDE.md and README.md carry ~92 references into the tree and
the doc pages carry ~65 of their own — 157 total, the committed checker's
steady-state count (~132 of them `#id`-fragment pointers). The original
one-shot run's 229 counted 72 more references from a still-on-disk staged
CLAUDE.md copy that the committed checker deliberately trims. <!-- UPDATED: 229 vs 157 clarification per parity-figure-stale --> The one tool that resolves them
(`tmp/verification/2026-09-12-build-doc-tree-step9.py`) is gitignored and
one-shot. The doc-structure gate never reads CLAUDE.md and never
resolves an href to an `id`. Fix: commit that script as
`scripts/check_doc_anchors.py` (port with three sanctioned changes — rewritten
permanent docstring, `REFERRERS` trimmed to `["CLAUDE.md", "README.md"]`, logic
moved into a `run(root)` function for testability) and run it from a new,
permanent `tests/test_docs.py` module wired into the aggregator. The
credential-shape scan rides along intact (user-confirmed whole-script scope):
the repo is public and its docs show key/config schemas, so the check that no
real credential shape leaked into `doc/` becomes permanent instead of dying
with the tmp artifact. Conventions note (user-confirmed): the personal
`~/.claude/scripts/doc_structure_check.py` gate is explicitly out of scope.

**#2 — `doc/content.html` sends newcomers to raw Markdown.** Lines 22, 51, 64
hyperlink `../README.md`, which a browser renders as plain text locally. The
page's own Conventions already say "a URL you need is shown as code rather than
as a hyperlink" — option (c) chosen: convert the three links to code-styled
`README.md` references. No gate conflict (a code tag carries no href), offline
safe, zero maintenance.

Alternatives rejected: anchors-only checker extraction (user chose whole
script); a `readme.html` mirror (content duplication + sync burden); linking
the GitHub page (absolute href — violates the gate's relative-only cross-ref
rule and breaks offline viewing).

Out of scope: the personal doc-structure gate, the CLAUDE.md deferred-issues
index and Future Work counts (owned by `/update-and-commit` at commit time),
README.md itself, and cleanup of the historical tmp/ verification artifacts.

## Repo Mode

Public

*Detected at plan creation. Determines: plan archival path, commit-message content, staged files.*

## Document Overrides

| Document | Rule Overridden | Reason |
|----------|----------------|--------|

## Risks

| Risk | Impact | Mitigation |
|-------|--------|------------|
| Porting silently weakens a check | Suite believes anchors healthy while coverage dropped | Step 1 `(auto)` greps bound the changes to the three sanctioned ones; Step 2's planted cases exercise every failure class end-to-end |
| `test_docs.py` depends on repo-relative CWD | False failures/false passes when the suite runs elsewhere | Step 2 contract: derive the repo root from `__file__`, never CWD |
| Planner doc sync (Step 4) introduces a broken anchor after the tester's green run | Red suite discovered only at the next run | Step 4 re-runs the checker and the full suite immediately after the edits |

**Rollback:** the whole change set lands as one commit — `git revert` restores it. The checker script and test module are new files (no pre-existing behavior to restore), and the doc edits self-invert.

## Proposed Changes

Each step includes verification checks tagged with confidence (see Prime Directive 4).
`(auto)` = mechanical, coder self-verifies. `(scripted)` = deterministic multi-step, coder runs provided script.
Every step must have at least one verification check executable by its owner (coder steps: coder checks; tester steps: tester verify; planner steps: Evidence).

1. **Step 1:** Port `tmp/verification/2026-09-12-build-doc-tree-step9.py` to `scripts/check_doc_anchors.py` with exactly three sanctioned changes: (a) the module docstring is rewritten for permanence — no plan or `tmp/` references; it states what the checker verifies (references from `CLAUDE.md`, `README.md`, and the pages themselves resolve to real files and `id` values — root files use the `doc/page.html#frag` form, pages use the bare sibling `page.html#frag` form, and fragment ids must match `[A-Za-z0-9_-]+`; no credential-shaped string appears in the **`doc/` pages** without a placeholder marker), its exit codes 0/1/2 including the exit-2 no-tree and no-referrers conditions, and the `ALLOWED_HOSTS` maintenance contract for future doc examples; (b) `REFERRERS` drops the `tmp/verification/CLAUDE.md.staged` entry, leaving exactly `["CLAUDE.md", "README.md"]`; (c) the checks move out of `main()` into `run(root)` returning `(status, failures, anchors_checked, secrets_scanned)` where `status` is `"ok"`, `"no-tree"` (no `doc/` directory), or `"no-referrers"` (no `CLAUDE.md`/`README.md` under root — a zero-referrer run must never report a vacuous PASS), and `main()` becomes a thin CLI wrapper accepting an optional root path (default CWD) that maps `status`/failures to the exit codes 0/1/2 (both abnormal statuses → 2). Every check body, regex, allowlist, and marker list stays verbatim; no new check is added; the no-tree/no-referrers guard is wrapper contract, not a check body.
   → coder verify (auto): file exists at `scripts/check_doc_anchors.py`; `python scripts/check_doc_anchors.py` from the repo root prints `## Doc Verification: PASS` and exits 0; `grep -n "build-doc-tree\|tmp/verification"` over the file returns empty; the `REFERRERS` list is exactly `["CLAUDE.md", "README.md"]`; `run(root)` returns a 4-tuple whose first element is one of `"ok"`, `"no-tree"`, `"no-referrers"` and `main()` returns 0/1/2 to the shell; parity — running the original `tmp/verification/2026-09-12-build-doc-tree-step9.py` and the port against the same healthy tree both exit 0 with the identical secrets count (8), and the anchor counts differ by exactly the staged referrer's reference total: the original also counts `tmp/verification/CLAUDE.md.staged`, which sanctioned change (b) trims, so on the current tree the original reports 229 and the port 157 (delta 72 = 50 fragment + 22 bare from the staged file; if that file is ever removed, both report 157) <!-- UPDATED: coder parity-figure-stale — pinned (229 / 8) was unreachable post-trim -->.
   → tester verify: Step 2's real-tree success case passes; each planted-failure case detects its class.

2. **Step 2:** Create `tests/test_docs.py` following the suite conventions — read `tests/_harness.py` and a sibling module (e.g. `tests/test_unit.py`) first. It defines `ALL_TESTS`; every case name carries a `doc_` prefix to stay unique suite-wide (the aggregator's `run_cli` builds a name-indexed test map). Load the checker via `importlib.util.spec_from_file_location` pointing at the repo-root script path derived from `__file__` (`Path(__file__).resolve().parents[1]`) — never from CWD, and never a package-relative `import scripts...` (the tests/ dir is `sys.path[0]` when the aggregator runs); cases assert on `run(root)` directly, plus one subprocess CLI case for the exit-code mapping. Cases: (1) real tree — `run(REPO_ROOT)` reports `status == "ok"`, zero failures, and `anchors_checked >= 1` (healthy-tree baseline 157 post-trim — a floor, never a pinned high-water mark) so a referrer wipe cannot silently green; <!-- UPDATED: post-trim baseline per parity-figure-stale --> (2) planted-failure suite — under `tempfile.TemporaryDirectory()`, build a stub `CLAUDE.md`, `README.md`, and minimal `doc/` pages; stub URLs may only use localhost or reserved-TLD hosts (`.invalid`, `.test`, `.example`) so no case trips a second failure class. One case per defect class: a root-referrer anchor to a missing file (`doc/ghost.html#x`); a root-referrer fragment not matching any `id` on an existing page; a root-referrer bare `doc/ghost.html` link (no fragment); a doc-page sibling anchor `sibling.html#missing`; a bare sibling `href="ghost.html"` link; a secret-shaped string without a placeholder marker is flagged — use the exact literal `sk-ant-api03-abcdefghijklmnopqrstuvwx` (the `sk-` pattern needs a ≥20-char tail; a short sample would pass the field for the wrong reason); the same literal with a placeholder marker (`sk-ant-api03-YOUR-KEY-PLACEHOLDER`) is not flagged; a URL whose host is neither allowlisted nor reserved-TLD (e.g. `https://acme.com/x`) is flagged; a reserved/allowlisted URL pair (`https://api.example.invalid`, `https://api.anthropic.com`) is not flagged; a root with no `doc/` returns `"no-tree"` (and the CLI exits 2); a root with `doc/` but no `CLAUDE.md`/`README.md` returns `"no-referrers"` (CLI exits 2). Each case asserts its class (and only it). Then wire the module into `tests/test_claude_proxy.py`: import `ALL_TESTS` from `test_docs` and append it at the end of the tuple. Run the full suite from the repo root — all modules green, aggregated output includes the new tests.
   → tester verify: each planted case reports its class (and only it); the real-tree case passes with `anchors_checked >= 1`; `python tests/test_claude_proxy.py` exits 0 with all pre-existing modules green; temp trees self-clean (TemporaryDirectory context manager).

3. **Step 3:** (planner, now) In `doc/content.html`: replace the three `../README.md` hyperlinks (lines 22, 51, 64) with code-styled references in the page's voice — e.g. `the <code>README.md</code> in the repository root`; extend the Conventions list with a bullet stating the committed checker (`scripts/check_doc_anchors.py`) verifies every `doc/*.html#id` reference from `CLAUDE.md`, `README.md`, and the pages themselves, so a renamed heading fails the test suite; bump the two "Last updated" indicators (line 13 and the footer) to 2026-09-14.
   → Evidence: `grep -n 'href="../README.md"' doc/content.html` returns nothing; `grep -c "<code>README.md</code>" doc/content.html` returns 3; the diff against HEAD touches only the three link sites, the Conventions list, and the two date indicators. (The checker re-run after this edit rides on Step 4's evidence, since the script lands in Step 1.)

4. **Step 4:** (planner, after Steps 1–2) Sync the doc surfaces: (a) `CLAUDE.md` Structure block — extend the `scripts/` entry with `check_doc_anchors.py` (doc anchor + credential-shape checker, invoked by the test suite); (b) `doc/test-catalog.html` — add `test_docs.py` to the module index table, add its `h4` section in the existing per-module format documenting its cases (test count taken from the final module), re-count the suite-size snapshot with the page's own recipe (`grep -c 'def test_' tests/*.py` plus its per-file column) and update the snapshot line to the final number across 16 files, and bump the page's two `Last updated` indicators to 2026-09-14 (mirroring Step 3's date treatment). Do **not** touch the CLAUDE.md `## Unresolved Deferred Issues` index or the Future Work counts — `/update-and-commit` maintains those from this plan's Issue Log rows at commit time. Then re-run the full verification once, after all doc edits.
   → Evidence: `python tests/test_claude_proxy.py` exits 0 with the full aggregated output; `python scripts/check_doc_anchors.py` exits 0; grep shows the new CLAUDE.md structure line, the test-catalog table row, and the `h4` section for `test_docs.py`; grep pins the revised snapshot figure line (final count and `16 files`), the two bumped `2026-09-14` date indicators on the page, and the new module's row count matching the `h4` count.

## Guidance for Planner

- **Doc files to create/update:** `doc/content.html`, `CLAUDE.md`, `doc/test-catalog.html`
- **When:** `doc/content.html` now (Step 3, before the coder starts); `CLAUDE.md` and `doc/test-catalog.html` after Steps 1–2 land (Step 4)
- **What to sync:** Step 3 — the three link sites, one new Conventions bullet, two date indicators. Step 4 — the CLAUDE.md `scripts/` structure line and the test-catalog module index (table row + per-module section + the suite-size snapshot figure re-counted to its final number across 16 files + the page's two `Last updated` indicators bumped to 2026-09-14).
- **Deferred-issue bookkeeping:** the two `defer-issue-*.json` reports are closed in place by `/update-and-commit` Step 9.6 once the Issue Log rows above reach `Resolved`, and the CLAUDE.md deferred-issues index is pruned by the same flow — no manual report or index edits. The gitignored `tmp/verification/2026-09-12-build-doc-tree-step9.py` stays as a historical plan artifact.

## History

| Date | Event | Conclusion | Dismissed |
|------|-------|------------|-----------|
| 2026-09-14 | Spec revision (/update-plan) | Tester rounded the reviewer's Warning fix — [test-docs-temp-tree-leak](./tmp/reports/2026-09-14-commit-doc-anchor-check-test-docs-temp-tree-leak.json) Resolved: _make_tree nests under the caller TemporaryDirectory, 56 leaked dirs purged, standalone 11/11 and full suite 304/304 with zero leaks before/after — [tester report](./tmp/reports/2026-09-14-commit-doc-anchor-check-tester-2026-09-14-2.json) | — |
| 2026-09-14 | Review | Verdict "Issues found — non-blocking" (0 Critical, 1 Warning, 1 Suggestion) — the Correctness Warning was opened as [test-docs-temp-tree-leak](./tmp/reports/2026-09-14-commit-doc-anchor-check-test-docs-temp-tree-leak.json) on user direction (fix first) and the Readability Suggestion was absorbed into the catalog snapshot note — [2026-09-14-commit-doc-anchor-check-review-2026-09-14.json](./tmp/reports/2026-09-14-commit-doc-anchor-check-review-2026-09-14.json) | — |
| 2026-09-14 | Spec revision (/update-plan) | Final gate round — Steps 3–4 closed and verified (checker exit 0 at 157 anchors after the doc edits; full suite 304/304), defer-issues review-anchor-resolver-not-committed and review-content-readme-link-raw-markdown moved to Resolved; [no-proxy-stop-trace-warning](./tmp/reports/defer-issue-no-proxy-stop-trace-warning.json) stays Open as the user-dispositioned low-priority defer | — |
| 2026-09-14 | Spec revision (/update-plan) | Tester round closed Step 2 — full suite 304/304 — resolving [parity-figure-stale](./tmp/reports/2026-09-14-commit-doc-anchor-check-parity-figure-stale.json) and deferring the pre-existing trace warning as [no-proxy-stop-trace-warning](./tmp/reports/defer-issue-no-proxy-stop-trace-warning.json) per the [tester report](./tmp/reports/2026-09-14-commit-doc-anchor-check-tester-2026-09-14.json) | — |
| 2026-09-14 | Spec revision (/update-plan) | Fixed the Step 1 parity clause per [parity-figure-stale](./tmp/reports/2026-09-14-commit-doc-anchor-check-parity-figure-stale.json): counts re-expressed as identical secrets + anchor delta equal to the trimmed staged referrer's total; Step 2 and Summary re-based from 229 to the 157 post-trim steady state | — |
| 2026-09-14 | Mega-audit (pre-implementation) | All 9 Medium findings fixed — pinned `run()` status contract with exit-2 no-tree/no-referrers cases, planted cases now cover every failure class, tester file-set markers aligned with the metadata, docstring claims narrowed to the implemented scan set, test-catalog date/snapshot evidence added; 12 of 16 Low findings absorbed into the same edits — [2026-09-14-commit-doc-anchor-check-mega-audit-2026-09-14.json](./tmp/reports/2026-09-14-commit-doc-anchor-check-mega-audit-2026-09-14.json) | [F3 doc-prefixed-form-blindspot](./tmp/reports/2026-09-14-commit-doc-anchor-check-mega-audit-2026-09-14.json), [F21 secret-prefix-echoed-to-log](./tmp/reports/2026-09-14-commit-doc-anchor-check-mega-audit-2026-09-14.json), [F22 marker-suppression-scope](./tmp/reports/2026-09-14-commit-doc-anchor-check-mega-audit-2026-09-14.json), [F23 id-regex-scope](./tmp/reports/2026-09-14-commit-doc-anchor-check-mega-audit-2026-09-14.json) |
| 2026-09-14 | Initial plan | Commits the step9 checker as `scripts/check_doc_anchors.py` run by the suite, and converts the three content.html README links per option (c) | — |

## Plan Metadata

```json
{
  "plan_id": "2026-09-14-commit-doc-anchor-check",
  "steps": [
    "Step 1: Port the step9 checker to scripts/check_doc_anchors.py",
    "Step 2: Add tests/test_docs.py and wire the aggregator",
    "Step 3: Convert content.html README links to code text",
    "Step 4: Sync CLAUDE.md and test-catalog.html after implementation"
  ],
  "coder_files": ["scripts/check_doc_anchors.py"],
  "tester_files": ["tests/test_docs.py", "tests/test_claude_proxy.py"],
  "doc_files": ["doc/content.html", "doc/test-catalog.html", "CLAUDE.md"],
  "verification_scripts": [],
  "repo_mode": "Public",
  "document_overrides": []
}
```

## Audit Accumulation

*Counters reset when mega-audit runs. Used by Phase 5 entry trigger.*

| Counter | Value | Last Updated |
|---------|-------|--------------|
| issues_resolved_since_audit | 4 | 2026-09-14 |
| steps_changed_since_audit | 2 | 2026-09-14 |
| files_changed_since_audit | 0 | 2026-09-14 |

## Documentation

The doc surfaces this plan touches are listed under "Guidance for Planner".
Deep reference and reading order: `doc/content.html`. Suite layout conventions:
`doc/test-catalog.html`. No interim plan documents beyond this file.

## Final Results

**Completion date:** 2026-09-14
**Status:** COMPLETED — all four steps implemented and verified; the two target deferred issues resolved; the reviewer's Correctness Warning fixed and re-verified; one issue (no-proxy-stop-trace-warning) dispositioned by the user as a low-priority defer and left Open.

**Files changed:**
- `scripts/check_doc_anchors.py` (new) — the committed doc-anchor + credential-shape checker, a verbatim port of the step9 verification script with exactly three sanctioned changes (rewritten docstring with the exit-code and `ALLOWED_HOSTS` contracts, `REFERRERS` trim, `run(root)` status contract + `main()` exit mapping).
- `tests/test_docs.py` (new) — 11 permanent `doc_` cases: real-tree success with an anchor-count floor, one planted case per failure class, and the CLI exit-code mapping; planted trees nest under the caller's `TemporaryDirectory` (post-review fix).
- `tests/test_claude_proxy.py` — aggregator import + tuple append.
- `doc/content.html` — three `../README.md` links converted to code text, the checker Conventions bullet, date bumps.
- `doc/test-catalog.html` — Category 11 inventory (11 cases), module table row, snapshot re-counted to 304 test functions across 16 files with an authoritative-tally note, date bumps.
- `CLAUDE.md` — `scripts/` structure line for the checker.

**Test results:** full aggregated suite 304 passed / 0 failed, exit 0 — twice: after the final doc edits (planner run) and after the reviewer-fix tester round (with a zero-leak check, `leftover-after-run=0`). `tests/test_docs.py` standalone: 11/11. Checker: exit 0, 157 anchors resolved / 8 pages scanned.

**Issues resolved:** parity-figure-stale (tester), test-docs-temp-tree-leak (tester), review-anchor-resolver-not-committed (tester), review-content-readme-link-raw-markdown (planner). Each carries a resolution report. One reviewer Readability Suggestion absorbed into the catalog snapshot note.

**Review:** Phase 6 reviewer verdict "Issues found — non-blocking" — 0 Critical, 1 Warning (fixed by the tester round and re-verified), 1 Suggestion (absorbed). Three cosmetic hunches noted in the report, no action.

**Known caveats:** [no-proxy-stop-trace-warning](./tmp/reports/defer-issue-no-proxy-stop-trace-warning.json) remains Open — pre-existing, unrelated to this plan, user-deferred at low priority on 2026-09-14. The checker's verbatim-port message asymmetry (bare vs `doc/`-prefixed failure targets) ships as documented behaviour.

## Cross-References to Prior Plans

| Prior Plan | Deferred Issue | Resolution |
|------------|----------------|------------|
| 2026-09-12-build-doc-tree | review-anchor-resolver-not-committed | Committed scripts/check_doc_anchors.py (the step9 checker) and wired it into the test suite via tests/test_docs.py, so every CLAUDE.md/README.md/doc anchor is re-verified on each suite run |
| 2026-09-12-build-doc-tree | review-content-readme-link-raw-markdown | doc/content.html now presents README.md as a code-styled path (option c) instead of a hot link, matching the page's own relative-only convention |