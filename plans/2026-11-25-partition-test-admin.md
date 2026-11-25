# Plan: Partition tests/test_admin.py by feature area

**Plan ID:** 2026-11-25-partition-test-admin
**Created:** 2026-11-25

<!-- ## Immediate Actions: absent from initial plans. Populated by /update-plan for revised plans, replaced (not accumulated) on each revision. Contains per-role action-only directives (no rationale) telling agents what to do next. Agents read the full plan for context. -->

## Issue Log

| Issue | Status | Found | Resolved | Resolved By |
|-------|--------|-------|----------|-------------|

## Guidance for Coder

None. This plan has **no coder steps** — every move is a test-file change, which is tester-lane exclusively (the coder never touches test files).

## Guidance for Tester

**Tests to create:**
- Permanent (partition): `tests/test_admin_switch.py`, `tests/test_admin_swap.py`, `tests/test_admin_write.py`, `tests/test_admin_html.py`, `tests/test_admin_html_status.py`, `tests/test_swap_drain.py` — six new files, byte-verbatim moves per the pinned partition.
- Permanent (modified): `tests/test_admin.py` (shrunk to the 13-test read surface), `tests/test_claude_proxy.py` (aggregator import set + merge tuple).

**Verification scripts to create:** none by the tester — the planner-authored gates below are the scripted checks; the tester may add behavioral scripts if the suite surfaces an issue, and reference them in the session report.

**Files to modify:**
- `tests/test_admin.py` (shrink to the read surface)
- `tests/test_admin_switch.py` (new)
- `tests/test_admin_swap.py` (new)
- `tests/test_admin_write.py` (new)
- `tests/test_admin_html.py` (new)
- `tests/test_admin_html_status.py` (new)
- `tests/test_swap_drain.py` (new)
- `tests/test_claude_proxy.py` (aggregator: import set)

**Step-by-step with verification:** see Proposed Changes. All moves are byte-verbatim function-level relocations from `tests/test_admin.py` (which must equal `HEAD:tests/test_admin.py` at the start of Step 1 — preconditions asserted by the gate). Helper blocks move with their sole area; the one cross-area pair (the two JS parsers) is resolved by the status file's pinned sibling import. Each new file is standalone-runnable and keeps the `run_cli` footer. `git add` each new file the moment it exists. The `ALL_TESTS` lists are new text (not byte-verbatim) but must carry exactly the pinned name↔function pairs in the pinned order.

**Split mechanism (both gates share it):** parse a file with `ast`, take each top-level `FunctionDef`/`Assign` node's `ast.get_source_segment`, and compare per-name sha256 against the same parse of `git show HEAD:tests/test_admin.py`. Byte-identity is name-keyed, not line-keyed — it verifies the result, not the cut.

### Pinned partition (59 tests total; sums verified 2026-11-25)

**`tests/test_admin.py` (kept — admin read surface, 13 tests):**
page/config/CSRF/providers-detail/models + the served-page key-column check.
Defs kept: `test_admin_page_served`, `test_admin_api_config`, `test_admin_api_csrf_rejected`, `test_admin_api_csrf_null_origin_rejected`, `test_admin_api_csrf_missing_origin_rejected`, `test_admin_api_csrf_ipv6_loopback_accepted`, `test_admin_models_provider_keyed`, `test_admin_providers_detail`, `test_admin_providers_detail_no_mode`, `test_admin_providers_detail_forbidden`, `test_admin_providers_detail_invalid_mode_normalized`, `test_admin_providers_detail_returns_key_names`, `test_admin_html_key_column`.
ALL_TESTS names (pinned order): `admin-page-served`, `admin-api-config`, `admin-api-csrf-rejected`, `admin-api-csrf-null-origin-rejected`, `admin-api-csrf-missing-origin-rejected`, `admin-api-csrf-ipv6-loopback-accepted`, `admin-models-provider-keyed`, `admin-providers-detail`, `admin-providers-detail-no-mode`, `admin-providers-detail-forbidden`, `admin-providers-detail-invalid-mode-normalized`, `admin-providers-detail-returns-key-names`, `admin-html-key-column`.

**`tests/test_admin_switch.py` (new — switch/reload validation + key selection, 14 tests):**
Defs moved (original relative order): `test_admin_api_switch`, `test_admin_api_switch_invalid_provider`, `test_admin_api_switch_preserves_models`, `test_admin_api_switch_missing_tier_rejected`, `test_admin_api_reload`, `test_admin_reload_non_dict_extra_tier`, `test_admin_switch_preserves_disable_retry_flag`, `test_admin_switch_with_key_name`, `test_admin_switch_unknown_key_rejected`, `test_admin_switch_invalid_key_type_rejected`, `test_admin_switch_missing_key_defaults`, `test_admin_switch_validates_key_names`, `_switch_tier_mapping`, `_switch_rejection_rows`, `_assert_switch_rejected` (helpers sit directly before their consumer `test_admin_switch_input_rejections`), `test_admin_switch_input_rejections`, `test_admin_switch_extra_tier_persisted`.
ALL_TESTS names (pinned order): `admin-api-switch`, `admin-api-switch-invalid-provider`, `admin-api-switch-preserves-models`, `admin-api-switch-missing-tier-rejected`, `admin-switch-input-rejections`, `admin-switch-extra-tier-persisted`, `admin-api-reload`, `admin-reload-non-dict-extra-tier`, `admin-switch-preserves-disable-retry-flag`, `admin-switch-with-key-name`, `admin-switch-unknown-key-rejected`, `admin-switch-invalid-key-type-rejected`, `admin-switch-missing-key-defaults`, `admin-switch-validates-key-names`.

**`tests/test_admin_swap.py` (new — config-swap drain races, process level, 10 tests):**
Defs moved (original relative order): `_SWAP_BUDGET_ENV` (module-level assignment; its 3-line rationale comment at HEAD L1795–1797 moves with it as new text immediately above the assignment), `_anthropic_sse`, `_msg_start`, `_text_delta`, `_msg_stop`, `_switch_body`, `_swap_proxy`, `_stream_request_in_thread`, `_admin_get_json`, `test_switch_succeeds_during_long_live_stream`, `test_switch_evicts_silent_stream`, `test_switch_silent_before_press_is_late_exit`, `test_switch_abandons_retry_chain`, `test_switch_straggler_pre_first_byte_fails_retryably`, `test_swap_status_endpoint`, `test_second_press_refused_409`, `test_concurrent_presses_single_flight`, `test_reload_does_not_revert_concurrent_switch`, `test_request_blocked_at_admission_not_evicted`.
ALL_TESTS names (pinned order): `admin-switch-waits-long-live-stream`, `admin-switch-evicts-silent-stream`, `admin-switch-silent-before-press-late-exit`, `admin-switch-abandons-retry-chain`, `admin-switch-pre-first-byte-straggler`, `admin-swap-status-endpoint`, `admin-second-press-refused-409`, `admin-concurrent-presses-single-flight`, `admin-reload-stale-candidate-guard`, `admin-admission-blocked-not-evicted`.

**`tests/test_admin_write.py` (new — write-path invariants, in-process, 6 tests):**
Defs moved (original relative order): `_drive_post_in_process`, `_drive_get_in_process`, `test_admin_config_serialize_failure_500`, `test_switch_nesting_gate_precedes_key_echo`, `test_admin_reload_serialize_failure_500`, `test_admin_reload_serializability_probe_precedes_drain`, `test_admin_switch_apply_rewrites_tier_map`, `test_admin_switch_rechecks_catalog_after_epoch_move`.
ALL_TESTS names (pinned order): `admin-config-serialize-failure-500`, `admin-switch-nesting-gate-precedes-key-echo`, `admin-reload-serialize-failure-500`, `admin-reload-serializability-probe-precedes-drain`, `admin-switch-apply-rewrites-tier-map`, `admin-switch-rechecks-catalog-after-epoch-move`.

**`tests/test_admin_html.py` (new — served-page JS contract, 5 tests):**
Defs moved (original relative order): `_js_braced_block`, `_js_function_body`, `_POLL_BLOCK_OWNERS` (module-level tuple; its 16-line rationale comment at HEAD L3838–3853 moves with it as new text immediately above the assignment — the gate checks the assignment's segment, not the comment), `test_admin_html_poll_guard_after_await`, `test_admin_html_pending_status_styled`, `_save_config_body`, `_save_config_requires_rendered_row_checks`, `_save_config_requires_key_list_checks`, `test_admin_html_apply_requires_rendered_row`, `test_admin_html_apply_requires_key_list`, `_load_config_guard_checks`, `test_admin_html_load_config_status_guard`.
ALL_TESTS names (pinned order): `admin-html-poll-guard-after-await`, `admin-html-pending-status-styled`, `admin-html-apply-requires-rendered-row`, `admin-html-apply-requires-key-list`, `admin-html-load-config-status-guard`.

**`tests/test_admin_html_status.py` (new — status-stack repaint contract, 6 tests):**
Defs moved (original relative order): `_served_admin_page`, `_status_fn`, `_status_success_block`, `_finally_block`, `_attach_terminal_branch`, `_status_stack_failure_checks`, `_status_stack_success_checks`, `_status_stack_keyed_repaint_checks`, `_status_stack_dedupe_checks`, `_status_stack_sticky_checks`, `_status_stack_keyed_removal_checks`, `_run_status_stack_checks`, `test_admin_html_status_stack_failures`, `test_admin_html_status_stack_success_clears`, `test_admin_html_status_stack_keyed_repaint`, `test_admin_html_status_stack_unkeyed_dedupe`, `test_admin_html_status_stack_sticky`, `test_admin_html_status_stack_keyed_removal`.
ALL_TESTS names (pinned order): `admin-html-status-stack-failures`, `admin-html-status-stack-success-clears`, `admin-html-status-stack-keyed-repaint`, `admin-html-status-stack-unkeyed-dedupe`, `admin-html-status-stack-sticky`, `admin-html-status-stack-keyed-removal`.

**`tests/test_swap_drain.py` (new — `swap_drain._drain` singleton unit invariants, 5 tests):**
Defs moved (original relative order): `_fresh_drain`, `test_drain_admit_snapshot_under_lock`, `test_drain_complete_invariant`, `test_drain_bump_epoch_reentrant`, `test_drain_single_flight_refusal`, `test_drain_predicate_semantics`.
ALL_TESTS names (pinned order): `drain-admit-snapshot-under-lock`, `drain-complete-invariant`, `drain-bump-epoch-reentrant`, `drain-single-flight-refusal`, `drain-predicate-semantics`.

Sum: 13 + 14 + 10 + 6 + 5 + 6 + 5 = **59** (the pre-change `ALL_TESTS` count — gate-pinned).

### Pinned import blocks (measured by AST free-variable resolution, 2026-11-25)

Each new file: module docstring (one line stating the area + the house line `Part of the claude-retry-proxy suite; runnable standalone.`), then `from _harness import (...)` FIRST among imports (spawn isolation rides on `_harness` import order), then any sibling test import (status file only), then stdlib imports, then ALL_TESTS, then the footer. `run_cli` is imported in every file (footer use). In-function `import claude_retry_proxy.*` statements move verbatim inside their test bodies — never hoisted to module level.

The blocks below are the **exact free-variable resolution** of each group's defs (Load-context names minus the guide §7.3 local scope, resolved against HEAD's `_harness` import set, HEAD's stdlib import set, and the partition groups). The first map the plan shipped was over-approximated and missed `_admin_post` for the kept file — this table supersedes it, and both gates now assert these sets verbatim.

| File | stdlib imports | `_harness` names |
|------|----------------|------------------|
| `test_admin.py` (kept) | `json`, `shutil`, `subprocess`, `tempfile` | `_admin_get`, `_admin_post`, `_create_test_config`, `_create_test_keys`, `_mode_tiers`, `_setup_tier_routing_test`, `_start_admin_proxy`, `_start_proxy_server_directly`, `fail`, `find_free_port`, `pass_`, `run_cli` |
| `test_admin_switch.py` | `json`, `os`, `shutil`, `subprocess`, `tempfile`, `time` | `_admin_get`, `_admin_post`, `_create_test_config`, `_create_test_config_with_flag`, `_create_test_keys`, `_create_test_keys_plain`, `_derive_models_from_tiers`, `_mode_tiers`, `_send_proxy_request`, `_start_admin_proxy`, `_start_mock_upstream`, `_start_proxy_server_directly`, `fail`, `find_free_port`, `pass_`, `run_cli` |
| `test_admin_swap.py` | `io`, `json`, `os`, `shutil`, `tempfile`, `threading`, `time` | `_admin_get`, `_admin_post`, `_send_proxy_request`, `_send_proxy_request_stream`, `_start_admin_proxy`, `_trace_events_named`, `_trace_file_in`, `_wait_admin_swapping`, `_wait_for_trace_events`, `_wait_upstream_request`, `fail`, `find_free_port`, `pass_`, `run_cli` |
| `test_admin_write.py` | `io`, `json`, `os`, `shutil`, `tempfile` | `fail`, `pass_`, `run_cli` |
| `test_admin_html.py` | `re` | `_admin_get`, `_mode_tiers`, `_start_admin_proxy`, `fail`, `find_free_port`, `pass_`, `run_cli` |
| `test_admin_html_status.py` | `re` | `_admin_get`, `_mode_tiers`, `_start_admin_proxy`, `fail`, `find_free_port`, `pass_`, `run_cli` — plus the pinned sibling line `from test_admin_html import _js_braced_block, _js_function_body` |
| `test_swap_drain.py` | `threading` | `fail`, `pass_`, `run_cli` |

Notes. (1) `errors` and `warn` are imported by the HEAD monolith but referenced by **no** def anywhere — they are dead in HEAD and drop out of every partition file. (2) The sibling import in the status file is the mega-audit's lowest-risk resolution of the one real cross-area dependency (the four status-stack builder helpers call the two JS parsers); `_harness` stays the first import, so isolation ordering is preserved. (3) If the dependency-resolution gate reports an unresolved name, or the suite reports a `NameError` from a missing harness name, that is an import-block defect in this plan — file it, never widen the import block silently.

### Red interval

Step 2 is one reviewable unit: shrinking `tests/test_admin.py` and switching the aggregator land in the same step, verified only at the step's end (between the two writes the aggregator's count transiently dips below 59 — no test fails red, but no commit inside the interval).

**Rollback.** Step 1: `git restore --staged tests/test_swap_drain.py tests/test_admin_html.py tests/test_admin_html_status.py tests/test_admin_switch.py tests/test_admin_swap.py tests/test_admin_write.py` — the six files are then untracked and inert (the aggregator never imports them); their eventual removal is the user's, never a scripted `rm`. Step 2: `git restore tests/test_admin.py tests/test_claude_proxy.py` — safe because Step 2 asserts `tests/test_admin.py` byte-equal to HEAD before cutting, and the aggregator has no other in-step edits.

## Tests to investigate for retirement

No test obsolescence identified — verbatim relocations, no behavior under test changes.

## Summary

**Problem.** `tests/test_admin.py` is the repo's largest file (5,796 lines, 59 tests) and the largest of the ten test files over the 1,500-line survey threshold (survey re-run 2026-11-25; code 1,000 / tests 1,500, `wc -l` physical lines). It has grown by accretion across at least three feature campaigns (admin API, the 2026-10-12 config-swap drain, the 2026-11-25 swap-drain singleton invariants — both named in its own `ALL_TESTS` comments).

**Approach.** Feature-area partition into six sibling files plus a shrunk `tests/test_admin.py`, per guide §8/§9 (test threshold → feature-area partition preserving suite count and aggregator registration). The areas follow the file's own seams: read surface, switch/reload validation, swap races, write invariants, HTML contract, status-stack contract, drain singleton. The original survey's "zero cross-area helper usage" claim was **falsified by the mega-audit**: the first consumer map missed one module-level constant and one cross-file helper pair. A full AST free-variable resolution (re-measured 2026-11-25, guide §7.3 scope formula) now covers every module-level name and shows exactly one cross-area dependency: the status-stack helpers call the two JS-text parsers that live with the HTML contract area — `test_admin_html_status.py` imports them from its sibling with a pinned `from test_admin_html import ...` line (single copy, no duplication, no `_harness` growth). Every other helper moves with its sole area.

**Key decisions.**
- `test_admin.py` survives as the read-surface remainder — no file deletion, no retire hand-off.
- The status-stack family splits to its own file because the undivided HTML area measured 1,536 def-lines (over threshold even before overhead); `_served_admin_page` measured as status-stack-exclusive. The seam's one shared dependency (the two JS parsers) is resolved by a pinned sibling import, per the mega-audit's lowest-risk option.
- Drain singleton tests get `test_swap_drain.py`, mirroring the module name per the repo's per-area naming convention.
- Byte-identity is verified name-keyed against `git show HEAD:tests/test_admin.py` (AST source segments, sha256 per name) — result-verification, immune to line drift; step-local, not cumulative (Step 2's shrink invalidates Step 1's precondition, by design).
- Both gates additionally run a **dependency-resolution pass** (added post-mega-audit): every Load-context name in every moved/kept def must resolve to the destination file's own defs/imports, its pinned `_harness`/stdlib imports, the pinned sibling import, a local (guide §7.3 scope), or a builtin — converting the NameError class of defect into a Step-1 gate FAIL instead of a mid-suite surprise.
- The aggregator keeps `ADMIN_TESTS` from the shrunk `test_admin.py` and gains six imports; total registration stays 59 with zero name changes (the names are `run_cli --test` choices and the catalog's per-test index keys). Per-file `ALL_TESTS` order follows the pinned lists, which regroup HEAD's interleaved order by area — a deliberate execution-order change, declared here; `run_cli` executes sequentially and the tests are fixture-independent by design.
- Two leading comment blocks are design rationale that AST segments cannot see: the 3-line block above `_SWAP_BUDGET_ENV` and the 16-line block above `_POLL_BLOCK_OWNERS` move as new text immediately above their constants in the new files (prose-pinned; the gates check the constants, not comments).

**Alternatives rejected.** Folding the drain singleton tests into `test_admin_swap.py` (user declined — separate unit file approved); partitioning all ten over-threshold test files in one plan (one cluster per plan — `test_admin.py` first, the rest are follow-up plans); moving shared helpers into `_harness.py` (not needed — no cross-area sharing; `_harness.py` is itself over threshold at 2,033 lines and must not grow without cause).

**Out of scope:** the other nine over-threshold test files (parallel track, own plans); any change to `_harness.py`; any behavioral change to any test (the suite is the guard); `CLAUDE.md` (its Structure section enumerates no test files) and `README.md` (user-facing, no test inventory).

**Architecture:** unchanged at runtime — same 59 tests, same names, same suite entry point (`python tests/test_claude_proxy.py`), same per-file standalone entry points.

## Repo Mode

Public

## Document Overrides

| Document | Rule Overridden | Reason |
|----------|----------------|--------|

## Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| A moved test's hidden dependency (module-level side effect order, fixture reuse) breaks at its new import context | Test fails in the partitioned suite while it passed monolithic | Full-suite run at Step 1 and Step 2 is the gate; byte-verbatim moves make behavioral drift impossible; the dependency-resolution gate converts hidden-name defects into Step-1 FAILs; any residual failure is an import-block or ordering defect, filed, not patched |
| Import block miscalculation hides a name a moved test uses | `NameError` at import time, suite red, gate unsatisfiable-as-written | Blocks repinned 2026-11-25 from exact AST free-variable resolution after the mega-audit falsified the first map; both gates assert the pinned sets verbatim and run dependency resolution; the suite run has teeth (import-time failure); plan revision is the remedy, per the note under the import table |
| Aggregator count drifts (imports added but merge tuple not extended) | Suite silently runs fewer tests | finalize.py parses the import set AND runs `tests/test_claude_proxy.py --list`, asserting each of the pinned 59 names appears exactly once |
| New file exceeds the 1,500 threshold as it lands | The partition misses its own goal | Gate asserts every file < 1,500 lines; measured estimates put the largest at ~1,310 |

## Proposed Changes

1. **Step 1 (tester): Create the six new test files** — `tests/test_swap_drain.py`, `tests/test_admin_html.py`, `tests/test_admin_html_status.py`, `tests/test_admin_switch.py`, `tests/test_admin_swap.py`, `tests/test_admin_write.py` — each exactly as pinned above: one-line docstring + house line, `from _harness import (...)` first (pinned names), the status file's pinned `from test_admin_html import _js_braced_block, _js_function_body` line after it, stdlib block (pinned names), the pinned defs moved **byte-verbatim** in the pinned order (carrying the two pinned comment blocks as new text above their constants), the pinned `ALL_TESTS` list (exact name↔function pairs, pinned order), the `if __name__ == "__main__": run_cli(ALL_TESTS, "<file> tests")` footer. `git add` each file the moment it exists. `tests/test_admin.py` is NOT touched in this step.
   → tester verify (scripted): `python3 ./tmp/verification/2026-11-25-partition-test-admin-create.py` — per-file: exists, parses, `_harness` import present and first, pinned import sets exact (stdlib + `_harness`, and the sibling import for the status file), every pinned def byte-identical (name-keyed sha256 vs `git show HEAD:tests/test_admin.py`), **dependency resolution** (every Load-context name in every moved def resolves to the file's own defs/imports, its pinned imports, a §7.3-scope local, or a builtin), `ALL_TESTS` pairs match the pinned list exactly, file < 1,500 lines; plus preconditions: `tests/test_admin.py` still byte-equal to HEAD, aggregator unchanged. Exits 0 only when all six file groups PASS.
   → tester verify: `python tests/test_claude_proxy.py` exits 0 — the unregistered new files must not change the run (still 555 suite tests, all green).

2. **Step 2 (tester — one reviewable unit, no commit inside): Shrink `tests/test_admin.py` to the read surface and switch the aggregator.** Delete from `tests/test_admin.py` every def/assignment whose name appears in the six moved lists above (the file equals HEAD at this point — assert before cutting), remove the orphaned separator blanks those deletions leave, prune imports to the pinned kept-file blocks (stdlib + `_harness`, `_admin_post` included), rewrite the module docstring to state the read-surface scope (keep the house line), rebuild `ALL_TESTS` to the 13 pinned pairs. Then edit `tests/test_claude_proxy.py`: keep `from test_admin import ALL_TESTS as ADMIN_TESTS` and add the six new imports (`ADMIN_SWITCH_TESTS`, `ADMIN_SWAP_TESTS`, `ADMIN_WRITE_TESTS`, `ADMIN_HTML_TESTS`, `ADMIN_HTML_STATUS_TESTS`, `SWAP_DRAIN_TESTS`) into the merge tuple.
   → tester verify (scripted): `python3 ./tmp/verification/2026-11-25-partition-test-admin-finalize.py` — `tests/test_admin.py`: def set == the 13 pinned (all 80 moved names absent), the 13 kept defs byte-identical vs HEAD, `_harness`-first import + pinned kept import sets exact, dependency resolution over the kept defs, `ALL_TESTS` == 13 pinned pairs, < 1,500 lines; aggregator: the seven-module import set present AND `--list` output contains each of the pinned 59 names exactly once (proves the merge tuple, not just the imports); per-file registration: no orphan `test_` def anywhere, every file < 1,500 lines.
   → tester verify: `python tests/test_claude_proxy.py` exits 0 — full suite green, the 59 admin tests included (the aggregator runs the whole suite; the admin subset's green is what this step lands).

3. **Step 3 (tester): Standalone execution and registration gates.** For each of the seven partition files, run `python tests/<file> --list` (standalone enumeration works, lists exactly its pinned count) and one standalone execution per file with a PASSED assertion — the catalog's "Adding a test" rule: a green full-suite exit alone does not prove a test ran. Pinned slugs: `admin-page-served` (test_admin), `admin-switch-input-rejections` (switch), `admin-second-press-refused-409` (swap), `admin-config-serialize-failure-500` (write), `admin-html-apply-requires-key-list` (html), `admin-html-status-stack-failures` (html_status), `drain-predicate-semantics` (swap_drain) — each run must print `>> <slug>: PASSED` and exit 0. The spawn-isolation regression corpus is NOT re-scoped by this plan: `scripts/check_spawn_isolation.py` defaults to `tmp/verification/` and classifies test modules SKIP by design — the new files' isolation rests on the create gate's `_harness`-first assertion plus the suite run; run the checker once (`python scripts/check_spawn_isolation.py`) as a no-regression formality on its own corpus.
   → tester verify (scripted): rerun `./tmp/verification/2026-11-25-partition-test-admin-finalize.py` (still green); `check_spawn_isolation.py` exit 0; the seven `--list` runs exit 0 each printing its pinned count; the seven `-t <slug>` runs each print PASSED and exit 0.
   → tester verify: session report records the fourteen run outputs (exit codes + counts + PASSED lines).

4. **Step 4 (planner): Sync `doc/test-catalog.html`.** The catalog's `tests/test_admin.py` section (the `<h4>` near L680 holding **57** per-test `<li>` items — two of the 59 tests have never had entries) becomes seven file sections with the 57 existing `<li>` items distributed to match the partition; keep every per-test description text unchanged (function and CLI names are unchanged — only file mapping moves); update the section headers' scope phrases; update the file table row near L156 (`test_admin.py` row) to reflect the shrunk file and add rows for the six new files. **Author the two missing entries** — `test_admin_switch_apply_rewrites_tier_map` and `test_admin_reload_serializability_probe_precedes_drain` — into the `tests/test_admin_write.py` section (one `<li>` each, a sentence describing the invariant under test), so the post-split catalog documents all 59. Append the extension date to the inventory's `<!-- BEGIN per-test inventory ... extended ... -->` marker (near L228); leave the page's "Last updated" line alone (repo practice: presence-only). Then sweep: `git grep -n "test_admin\.py" doc/test-catalog.html` (escaped dot — distinguishes the file name from the six `test_admin_*` module names) and verify each of the 59 CLI names appears exactly once, under its correct file section.
   → Evidence: the escaped-dot grep output reviewed — no moved test still attributed to `test_admin.py`; per-name single-attribution check over the seven sections; `python tests/test_claude_proxy.py -t doc-real-tree-success` exits 0 (the real-tree case that runs `scripts/check_doc_anchors.py`); the full suite stays green.

## Guidance for Planner

Documentation tasks you will execute yourself (not the coder):

- **Files to modify:**
  - `./doc/test-catalog.html`
- **`.claude/mega-audit-files.json`:** no declared audit locations exist in this repo; nothing to update.
- **When:** after the tester round completes (Step 4).
- **What to sync:** the test-catalog's file table row (near L156) and the `tests/test_admin.py` section split into seven sections as pinned above, the 57 existing `<li>` entries distributed, the two missing write-invariant entries authored, the inventory's `extended` marker dated; sweep `test_admin.py` attributions across `doc/` with the escaped-dot grep. `CLAUDE.md` needs no change (no test-file enumeration); `README.md` needs no change.

## History

| Date | Event | Conclusion | Dismissed |
|------|-------|------------|-----------|
| 2026-11-25 | Initial plan | Survey re-run 2026-11-25: `tests/test_admin.py` (5,796 lines, 59 tests) is the largest of ten over-threshold test files; partition into six feature-area siblings + shrunk remainder approved by user (6-file scheme, status-stack split included); gates calibrated RED against the pre-change tree | — |
| 2026-11-25 | Gate calibration (planner) | RED baseline recorded, scripts unedited since: `create.py` 2/8 (PASS: both preconditions; FAIL: 6 file-existence), exit 1; `finalize.py` 5/17 (PASS: 13 kept defs present + byte-identical, no orphans, no duplicate names, test_admin exists; FAIL: 79 moved-name leftovers (check label said 84 — label bug, fixed in the gate revision), ALL_TESTS≠13 pairs, >1,500 lines ×2 (admin block + per-file sweep), aggregator import set, 6 file-existence, registration order/union), exit 1; teeth probe: one modified body detected by sha256 segment compare while 12 untouched defs stayed stable | — |
| 2026-11-25 | Mega-audit (pre-implementation, iteration 1) | Report: [2026-11-25-partition-test-admin-mega-audit-2026-11-25.json](../reports/2026-11-25-partition-test-admin-mega-audit-2026-11-25.json) — 14 High / 8 Medium / 17 Low; verdict "plan needs revision". All three underlying High defects fixed pre-implementation: `_POLL_BLOCK_OWNERS` pinned into the html move list (plan + both gates); the html↔status helper pair resolved by a pinned sibling import (lowest-risk option); the kept-file import block repinned from a full AST free-variable re-measurement (`_admin_post` added; dead `errors`/`warn`/`time`/`_mode_tiers` dropped). Mediums fixed: aggregator merge-tuple check via `--list` in finalize.py; dependency-resolution + import-exactness checks in both gates; rollback notes added; Step 3 rewritten to per-file standalone `-t` PASSED runs (catalog rule) with the spawn-isolation scanner claim corrected (its default root is `tmp/verification/`, it never scans `tests/`); Step 4 premise corrected (57 entries, not 59) + two missing write-invariant entries authored + escaped-dot sweep + inventory marker; Step 2 verify reworded (aggregator `--list` prints 555, not 59 — the unsatisfiable check removed); docs evidence command pinned to the real slug `doc-real-tree-success`; tester-guidance markers aligned to the metadata contract. Post-fix High count: 0 — no re-audit needed. All 17 Low findings were also fixed in the same revision (comment-block moves pinned, import tables repinned, counts reconciled to the real 79→80 set, metadata markers added, standalone-execution gates added, docs slug pinned, inventory marker added) | — |
| 2026-11-25 | Gate revision + re-calibration (planner) | Both gates extended (import-set exactness, dependency resolution per guide §7.3, aggregator merge-tuple check via `--list`, MOVED_NAMES 79→80 with the label bug fixed) and re-calibrated RED, scripts unedited since: `create.py` 2/8 (PASS: both preconditions; FAIL: 6 file-existence), exit 1; `finalize.py` 9/26 (PASS: 13 kept present + byte-identical + `_harness`-first + resolution clean + `--list` 59×1 + sibling-none + no orphans + no dups; FAIL: moved-names-absent, kept stdlib/harness exactness, ALL_TESTS≠13, >1,500 ×2, aggregator imports, 6 file-existence, union order), exit 1; predicate probes: full monolith resolves `{}` (satisfiability), injected `nope_missing_xyz` caught with location (teeth) | — |
| 2026-11-25 | Implementation round (tester) — SUCCESS, no retry used | Report: [2026-11-25-partition-test-admin-tester-2026-11-25.json](../reports/2026-11-25-partition-test-admin-tester-2026-11-25.json) — all four tester steps executed; both planner gates green unedited (create 68/68 post-Step-1, finalize 56/56 post-Step-2 and post-Step-3); full suite 555/555 before and after the partition with all 59 pinned slugs PASSED; seven standalone `--list` runs (13/14/10/6/5/6/5) and seven standalone `-t` PASSED runs; `check_spawn_isolation.py` exit 0; tester's independent completeness check: 91 top-level defs partitioned 13+17+18+8+11+18+6 with no duplicates, both module-level assigns in exactly one file each; test_admin.py shrunk to 651 lines, largest new file 1,289 (< 1,500); zero blocking failures, zero issues filed. Deviation noted by the tester: `git add` of the six new files refused twice by the permission layer (headless session) — files remain untracked; `/update-and-commit` stages them. Coder-report substitute evidence (tester-only plan): the planner-authored gates above are the build verification and they pass unedited | — |
| 2026-11-26 | Review (Phase 6) | Verdict: no Critical, no Warning, 1 Suggestion — report [2026-11-25-partition-test-admin-review-2026-11-26.json](../reports/2026-11-25-partition-test-admin-review-2026-11-26.json); gate passes, plan ready to commit. All 7 mega-audit obligations measured: RED ×2 arithmetic confirmed real (two distinct size checks; the hunch was refuted), spawn-isolation scope confirmed, ALL_TESTS order confirmed safe (555/555 green in new order), module-level inventory clean + both comment blocks faithful, seam re-verified mechanically (finalize 56/56 + standalone sibling-import run PASSED), real line counts 651/1168/1289/876/1144/457/332, run_cli exits non-zero on failure. Step 4 doc sync completed by the planner during the review window: catalog split into seven sections, 59 entries distributed (13/14/10/6/5/6/5), 2 entries authored, zero drifted originals among all 488 preserved `<li>` lines, escaped-dot sweep clean, `doc-real-tree-success` PASSED (272 anchors) | [review-untracked-staging](../reports/2026-11-25-partition-test-admin-review-2026-11-26.json) — Suggestion: stage the six untracked files together with the two tracked edits in the plan's single commit (no file left behind at HEAD); also noted, no row: stale `_fresh_drain` docstring preserved byte-verbatim (pre-existing, §8 forbids fixing in a move) |

## Plan Metadata

```json
{
  "plan_id": "2026-11-25-partition-test-admin",
  "steps": [
    "Step 1: Create the six new test files",
    "Step 2: Shrink tests/test_admin.py to the read surface and switch the aggregator",
    "Step 3: Isolation and standalone-runnability gates",
    "Step 4: Sync doc/test-catalog.html"
  ],
  "coder_files": [],
  "tester_files": [
    "tests/test_admin.py",
    "tests/test_admin_switch.py",
    "tests/test_admin_swap.py",
    "tests/test_admin_write.py",
    "tests/test_admin_html.py",
    "tests/test_admin_html_status.py",
    "tests/test_swap_drain.py",
    "tests/test_claude_proxy.py"
  ],
  "doc_files": ["doc/test-catalog.html"],
  "verification_scripts": [
    "./tmp/verification/2026-11-25-partition-test-admin-create.py",
    "./tmp/verification/2026-11-25-partition-test-admin-finalize.py"
  ],
  "retire_inventory": [
    "./tmp/reports/2026-11-25-partition-test-admin-mega-audit-2026-11-25.json",
    "./tmp/reports/2026-11-25-partition-test-admin-tester-2026-11-25.json",
    "./tmp/reports/2026-11-25-partition-test-admin-review-2026-11-26.json",
    "./tmp/verification/2026-11-25-partition-test-admin-create.py",
    "./tmp/verification/2026-11-25-partition-test-admin-finalize.py"
  ],
  "repo_mode": "Public",
  "document_overrides": []
}
```

## Audit Accumulation

| Counter | Value | Last Updated |
|---------|-------|--------------|
| issues_resolved_since_audit | 0 | 2026-11-25 |
| steps_changed_since_audit | 0 | 2026-11-25 |
| files_changed_since_audit | 0 | 2026-11-25 |

## Documentation

- [doc/test-catalog.html](../../doc/test-catalog.html) — the per-test index; Step 4 distributes the 59 entries across the seven file sections.
- The suite entry point and per-file standalone runs are documented in the catalog's harness section; no behavioral text changes.

## Final Results

**Status: COMPLETED — 2026-11-26**

**What was built.** `tests/test_admin.py` (5,796 lines, 59 tests — the repo's largest file) partitioned by feature area into six new sibling files plus a shrunk 651-line read-surface remainder, with the aggregator `tests/test_claude_proxy.py` extended to seven admin-side imports. All moves byte-verbatim (name-keyed sha256 vs `HEAD:tests/test_admin.py`, gate-enforced); test names unchanged (the `run_cli --test` choices and the catalog's keys are stable). Plan 1 of the test-side size campaign (survey 2026-11-24/25): every resulting file is under the 1,500-line test threshold (651 / 1,168 / 1,289 / 876 / 1,144 / 457 / 332).

**Steps completed.** All four (tester steps 1–3 in one successful round; planner Step 4 during the review window):
1. Six new files created — create gate 68/68 PASS (byte-identity, pinned import sets, dependency resolution, pinned ALL_TESTS pairs).
2. `tests/test_admin.py` shrunk + aggregator switched — finalize gate 56/56 PASS; suite 555/555 green after the switch.
3. Standalone gates — seven `--list` runs (13/14/10/6/5/6/5), seven standalone `-t` PASSED runs, `check_spawn_isolation.py` exit 0; finalize gate re-run green.
4. `doc/test-catalog.html` synced — one admin section became seven; 57 existing entries distributed verbatim, 2 missing write-invariant entries authored (59 total); zero drifted originals among all 488 preserved `<li>` lines (byte-verified against HEAD); file table carries seven rows; inventory marker extended 2026-11-26; escaped-dot sweep clean; `doc-real-tree-success` PASSED (272 anchors, 8 pages).

**Test results.** Full suite 555 passed / 0 failed before and after the partition, and again after the catalog sync; all 59 pinned admin/drain slugs PASSED in-suite and standalone. Both planner gates green unedited across three runs.

**Issues.** None filed; the Issue Log is empty. The mega-audit's 14 High / 8 Medium / 17 Low findings were all fixed pre-implementation (2026-11-25 revision); the review found no Critical and no Warning.

**Review verdict.** Non-blocking — 1 Suggestion ([review report](../reports/2026-11-25-partition-test-admin-review-2026-11-26.json)): the six new test files are untracked (the headless round's `git add` was permission-refused) and must be staged together with the two tracked edits in this plan's single commit — `/update-and-commit` stages all eight; nothing may be left behind at HEAD or the suite is un-importable there. All seven mega-audit obligations were confirmed/refuted by measurement during review.

**Deferred issues.** None from this plan. (Cross-references to prior plans: none — this implementation resolves no deferred item from any prior plan.)

**Known caveats.**
- The review's staging Suggestion above — action lives in `/update-and-commit`, not in code.
- A stale `_fresh_drain` docstring ("forwarder today, swap_drain.py after it") moved byte-verbatim per guide §8 — pre-existing, deliberately not fixed in a move.
- Residue outside `retire_inventory`: the tester's scratch helpers under `tmp/` (`partition_gen.py`, `partition_shrink.py`, `run_suite.py`, `suite-step1.log`, `suite-step2.log`) — left in place; retire on explicit user instruction only.
- The accepted status→html sibling-import coupling (`test_admin_html_status.py` imports the two JS parsers from `test_admin_html.py`) — the seam to watch on future JS-parser edits.

**Documentation.** `doc/test-catalog.html` synced (Step 4). `CLAUDE.md` and `README.md` intentionally unchanged — neither enumerates test files.
