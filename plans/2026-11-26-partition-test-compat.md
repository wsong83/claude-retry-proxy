# Plan: Partition tests/test_compat.py into feature-area test files

**Plan ID:** 2026-11-26-partition-test-compat
**Created:** 2026-11-26

## Issue Log

| Issue | Status | Found | Resolved | Resolved By |
|-------|--------|-------|----------|-------------|
| [gate-unsatisfiable-checks](./tmp/reports/2026-11-26-partition-test-compat-gate-unsatisfiable-checks.json) — two gate checks fail a plan-correct partition (support self-import demanded; ALL_TESTS excluded from new-module membership while another check requires it); tester fixed both in-gate with teeth preserved | Resolved | 2026-11-26 | 2026-11-26 | [tester](./tmp/reports/2026-11-26-partition-test-compat-tester-2026-11-26.json) — planner ratified: both fixes are minimal false-negative removals (import-order still ordered; membership still exact modulo the plan-required ALL_TESTS the gate itself asserts elsewhere), verified green by the full-gate runs |

## Guidance for Coder

None. Test-file changes are tester-lane exclusively; no coder steps.

## Guidance for Tester

**Tests to create:** none — this plan moves tests and helpers byte-verbatim; no test's behavior changes.

**Verification scripts to create:** none by the tester — the planner-authored gate at `./tmp/verification/2026-11-26-partition-test-compat-gate.py` is the scripted check; reference any behavioral script you add in the session report.

**Files to modify (tester lane):**
- `tests/test_compat.py` (kept: header rewritten, 22 members remain)
- `tests/_compat_support.py` (new: 29 shared members)
- `tests/test_compat_cm.py` (new: 18 members)
- `tests/test_compat_policy.py` (new: 6 members)
- `tests/test_compat_retry.py` (new: 5 members)
- `tests/test_compat_reasoning.py` (new: 17 members)

**Files to modify (planner lane, Step 2):** `doc/test-catalog.html` (Catalog sync)

**Step-by-step with verification:**

1. **Step 1 (tester): Partition.** Move the 97 pinned members byte-verbatim per the Move Inventory below (96 moved as-is; `ALL_TESTS` is restructured per its own section) — each member is exactly `ast.get_source_segment(HEAD:tests/test_compat.py, member)`; each module-level constant moves together with its full preceding contiguous comment block (the comment lines immediately above the assignment, e.g. L38–40 for `OBSERVED_400_BODY`, L63–67 for `REJECTED_BODY_CORPUS`, L102–104 for `ENVELOPE_STATE_KEYS`). Member order within each destination file preserves the source order of its members (the order listed in the Move Inventory). Separators: exactly **2 blank lines between top-level members in every destination file, with each constant's preceding comment block riding inside its member block** (blank lines counted, comment lines excluded). This is a deliberate uniform convention, not the source's — the source's own gaps are heterogeneous (re-measured 2026-11-26), and the gate asserts the uniform 2-blank form. The helpers-region banner (`# -------…` / `# Helpers` / `# -------…`, source L116–118) moves verbatim to `tests/_compat_support.py` above its helper region and is deleted from the kept file. **The other eight section banners are deleted, not carried** (their labels survive in each file's docstring and the `ALL_TESTS` section comments): the six test-region banners — `# A. Persistence / state` (L500–502), `# B. Detector` (L1412–1414), `# C. Learn/strip flow (live proxy)` (L1594–1596), `# D. Thresholds / state machine` (L1957–1959), `# E. Concurrency / robustness` (L2399–2401), `# F. Trace privacy` (L2826–2828) — the G banner with its prose block (L2878–2886), and the `# reasoning_field (chat mode) helpers` banner (L153–155). The gate asserts each deleted banner absent as its full 3-line block (dashed rule + label + dashed rule) — a contiguous block cannot collide with the indented single-line `ALL_TESTS` section comments the pin above keeps verbatim. Note C's qualifier drops with its banner: the surviving `ALL_TESTS` comment reads `# C. Learn/strip flow`, without the banner's ` (live proxy)` suffix. Build each file's import block from its pinned Derived Imports table below (stdlib sorted as in source, `_harness` block before `_compat_support` block, then `claude_retry_proxy.nesting` where pinned, then — kept file only — the four intra-test `ALL_TESTS` imports). Each new test module ends with its own `ALL_TESTS` list (exactly its pinned entries, same `("slug", name)` pairs and section comments as the source's corresponding ALL_TESTS sections) and the pinned `__main__` footer; `tests/_compat_support.py` has no `__main__` footer. The kept file's `ALL_TESTS` becomes its own 18 entries followed by `+ CM_TESTS + POLICY_TESTS + RETRY_TESTS + REASONING_TESTS`, preserving the source tuple's exact 56-slug sequence. **The aggregator `tests/test_claude_proxy.py` is untouched byte-for-byte** (it still imports `ALL_TESTS` from `tests/test_compat.py`). Def order within a file and its `ALL_TESTS` order legitimately differ where they differed at HEAD (the reasoning module's `test_reasoning_matcher_shapes` precedes `test_compat_guarded_parse_nesting_limit` in the ALL_TESTS list but follows it in def order) — both orders are pinned as-is.
   → tester verify (scripted): `python3 ./tmp/verification/2026-11-26-partition-test-compat-gate.py --tests` exits 0 (the test-file checks; the catalog checks are Step-2-gated and excluded here).
   → tester verify: `python tests/test_claude_proxy.py` exits 0 (full suite green).
   → tester verify: each new module standalone: `python tests/test_compat_cm.py --list` (and policy/retry/reasoning) — slugs exactly the pinned members' slugs, counts 15 / 6 / 5 / 12; plus one single-test run per new module proving the standalone import path, each PASSED: `python tests/test_compat_cm.py -t compat-detector-message-form`, `python tests/test_compat_policy.py -t compat-probation-cycle`, `python tests/test_compat_retry.py -t compat-trace-metadata-only`, `python tests/test_compat_reasoning.py -t reasoning-matcher-shapes`.
   → tester verify: `python tests/test_compat.py --list` — 56 slugs (18 own + 38 concatenated), the concatenated order matching the source tuple's sequence.
   → tester verify: `python scripts/check_spawn_isolation.py` PASS.

2. **Step 2 (planner): Catalog sync.** Re-section `doc/test-catalog.html` per Guidance for Planner → What to sync (Category 7 five sections, module-map rows), then `python3 ./tmp/verification/2026-11-26-partition-test-compat-gate.py` exits 0 (the full gate — the catalog checks pass only after this step) and `python scripts/check_doc_anchors.py` exits 0 (the catalog's anchor + credential-shape checker, run after any catalog edit). No other doc changes: CLAUDE.md's `tests/` line ("per-area test modules + aggregator") stays true and no doc enumerates compat helper surfaces. No prior-plan cross-references.

### Move Inventory

97 members (56 tests + 27 helpers + 14 module constants, per HEAD's AST inventory); 75 leave the kept file, 96 move byte-verbatim (`ALL_TESTS` is restructured, not moved). Source line numbers are `HEAD:tests/test_compat.py` spans (`ast` top-level `FunctionDef` / single-`Assign`), re-verified before cutting; **a drifted or zero-length range is a stop-and-report**.

**`tests/test_compat.py` (kept) — 22 members (21 byte-verbatim + `ALL_TESTS` restructured), 942 member-lines:**

| Member | Kind | Source lines |
|---|---|---|
| `ENVELOPE_STATE_KEYS` (+comment L102–104) | const | 105–107 |
| `ALLOWED_STATE_KEYS_BY_FEATURE` | const | 108–113 |
| `test_compat_state_load_missing_file` | def | 504–535 |
| `test_compat_state_load_corrupt_fails_open` | def | 538–566 |
| `test_compat_state_load_unreadable_fails_open` | def | 569–598 |
| `VALID_ENTRY_BODIES` (+comment L601–602) | const | 603–613 |
| `test_compat_state_roundtrip` | def | 616–729 |
| `test_compat_state_one_bad_entry_keeps_valid` | def | 732–818 |
| `test_compat_state_unknown_feature_ignored` | def | 821–893 |
| `test_compat_state_higher_version_fails_open` | def | 896–933 |
| `test_compat_state_invalid_entries_normalized` | def | 936–968 |
| `test_compat_state_atomic_write` | def | 971–1012 |
| `test_compat_state_write_metadata_only` | def | 1015–1044 |
| `test_compat_state_persist_failure_retains_memory` | def | 1047–1093 |
| `test_compat_state_concurrent_updates_no_loss` | def | 1096–1146 |
| `test_compat_state_key_isolation` | def | 1149–1191 |
| `test_compat_locks_present` | def | 1194–1218 |
| `test_compat_state_object_shape` | def | 1221–1307 |
| `test_compat_normalize_threshold_ladder` | def | 1310–1325 |
| `test_compat_temp_file_cleanup` | def | 1328–1362 |
| `test_compat_field_stripped_trace_accuracy` | def | 1365–1409 |
| `ALL_TESTS` | const | 4059–4123 (restructured, see below) |

**`tests/_compat_support.py` (new) — 29 members, 293 member-lines + banner:**

| Member | Kind | Source lines |
|---|---|---|
| `STATE_ENV` | const | 36 |
| `OBSERVED_400_BODY` (+comment L38–40) | const | 41–49 |
| `REJECTED_BODY_CORPUS` (+comment L63–67) | const | 68–80 |
| `CM_VALUE` | const | 82 |
| `CM_MARKER` | const | 83 |
| `ERROR_MARKER` | const | 84 |
| `UPSTREAM_ERROR_MARKER` | const | 85 |
| `SSE_BODY` | const | 87–100 |
| `_cm_request` | def | 120–128 |
| `_send` | def | 131–132 |
| `_make_state_dir` | def | 135–137 |
| `_read_state_file` | def | 140–145 |
| `_write_state_file` | def | 148–150 |
| `REASONING_MESSAGE_400` | const | 160–167 |
| `_reasoning_request` | def | 170–211 |
| `_sent_reasoning_field` | def | 214–230 |
| `_chat_ok_response` | def | 249–263 |
| `_chat_vendor` | def | 314–316 |
| `_entries` | def | 328–329 |
| `_entry_values` | def | 332–333 |
| `_reject_unstripped_responder` | def | 336–349 |
| `_ok_response` | def | 358–374 |
| `_cm_count` | def | 377–387 |
| `_compat_trace_events` | def | 390–413 |
| `_rescue_trace_events` | def | 416–418 |
| `_start_compat_proxy` | def | 421–435 |
| `_bootstrap_learned_state` | def | 438–461 |
| `_mutate_entry` | def | 464–479 |
| `_walk_strips` | def | 482–497 |

(`REASONING_MESSAGE_400`'s own comment block — L157–159, `400 bodies naming a reasoning field…` — rides with it into support per the general rule; the `# reasoning_field (chat mode) helpers` banner at L153–155 is one of the eight deleted banners. Members absent from this table — `_forwarded_assistant_fields` etc. — appear in the other files' tables below; every top-level statement of the source file lands in exactly one destination.)

**`tests/test_compat_cm.py` (new) — 18 members, 518 member-lines:**

| Member | Kind | Source lines |
|---|---|---|
| `STRUCTURED_400_BODY` (+comment L51–52) | const | 53–61 |
| `_always_400_responder` | def | 352–355 |
| `_detector_scenario` | def | 1416–1440 |
| `test_compat_detector_message_form` | def | 1443–1455 |
| `test_compat_detector_structured` | def | 1458–1469 |
| `test_compat_detector_nested_path_rejected` | def | 1472–1507 |
| `test_compat_detector_content_type_agnostic` | def | 1510–1528 |
| `test_compat_detector_unrelated_400_rejected` | def | 1531–1578 |
| `test_compat_detector_presence_required` | def | 1581–1591 |
| `test_compat_learn_on_400_stripped_2xx` | def | 1598–1633 |
| `test_compat_no_learn_when_retry_fails` | def | 1636–1669 |
| `test_compat_failed_confirmation_suppression` | def | 1672–1729 |
| `test_compat_strip_immediate_after_learn` | def | 1732–1756 |
| `test_compat_key_isolation_live` | def | 1759–1811 |
| `test_compat_unknown_field_passthrough` | def | 1814–1856 |
| `test_compat_non_matching_400_passthrough` | def | 1859–1900 |
| `test_compat_one_retry_cap` | def | 1903–1925 |
| `test_compat_count_tokens_excluded` | def | 1928–1954 |

**`tests/test_compat_policy.py` (new) — 6 members, 426 member-lines:**

| Member | Kind | Source lines |
|---|---|---|
| `test_compat_initial_threshold_probe` | def | 1961–2010 |
| `test_compat_rejection_doubles_threshold` | def | 2013–2095 |
| `test_compat_probation_cycle` | def | 2098–2189 |
| `test_compat_delist_after_two_successes` | def | 2192–2270 |
| `test_compat_inconclusive_reschedules` | def | 2273–2333 |
| `test_compat_probe_counter_semantics` | def | 2336–2396 |

**`tests/test_compat_retry.py` (new) — 5 members, 461 member-lines:**

| Member | Kind | Source lines |
|---|---|---|
| `test_compat_single_retry_global` | def | 2403–2544 |
| `test_compat_retry_lock_released_on_exception` | def | 2547–2619 |
| `test_compat_config_swap_during_retry` | def | 2622–2711 |
| `test_compat_retry_stream_interaction` | def | 2714–2823 |
| `test_compat_trace_metadata_only` | def | 2830–2875 |

**`tests/test_compat_reasoning.py` (new) — 17 members, 1,210 member-lines:**

| Member | Kind | Source lines |
|---|---|---|
| `_forwarded_assistant_fields` | def | 233–246 |
| `_reasoning_upstream` | def | 266–282 |
| `_reasoning_entry` | def | 285–296 |
| `_seed_reasoning_state` | def | 299–311 |
| `_start_reasoning_proxy` | def | 319–325 |
| `test_reasoning_walk_sends_advanced_candidate` | def | 2888–2944 |
| `test_reasoning_non_complaint_errors_are_not_counted` | def | 2947–3065 |
| `test_compat_guarded_parse_nesting_limit` | def | 3068–3146 |
| `test_reasoning_matcher_shapes` | def | 3149–3226 |
| `test_reasoning_delist_on_none_success` | def | 3229–3333 |
| `test_reasoning_credit_saturates_and_drains` | def | 3336–3447 |
| `test_reasoning_present_gates_on_demanding_turn` | def | 3450–3576 |
| `test_reasoning_rescued_success_does_not_teach` | def | 3579–3630 |
| `test_reasoning_rescue_runs_without_thinking` | def | 3633–3697 |
| `test_reasoning_rescue_events_and_merge` | def | 3700–3855 |
| `test_reasoning_rescue_repairs_forwarded_body` | def | 3858–3964 |
| `test_reasoning_switch_params_carried_across_admin` | def | 3967–4056 |

### ALL_TESTS restructure

Source `ALL_TESTS` (L4059–4123) is one list of 56 `("slug", name)` pairs under section comments A–G. After the partition:

- `tests/_compat_support.py`: no `ALL_TESTS`.
- Each new test module owns exactly its members' pairs with their section comments, verbatim: `test_compat_cm.py` = sections B + C (15 pairs), `test_compat_policy.py` = section D (6), `test_compat_retry.py` = sections E + F (5), `test_compat_reasoning.py` = section G (12).
- `tests/test_compat.py` (kept): its own section A pairs (18) followed by `+ CM_TESTS + POLICY_TESTS + RETRY_TESTS + REASONING_TESTS` where the aliases come from new pinned imports:
  ```python
  from test_compat_cm import ALL_TESTS as CM_TESTS

  from test_compat_policy import ALL_TESTS as POLICY_TESTS

  from test_compat_retry import ALL_TESTS as RETRY_TESTS

  from test_compat_reasoning import ALL_TESTS as REASONING_TESTS
  ```
  The concatenated sequence equals the source tuple's 56-slug order exactly. The four intra-test imports appear in the kept file in this pinned (non-alphabetical, source-section) order — cm, policy, retry, reasoning — matching the gate's ordered comparison.
- Def order and `ALL_TESTS` order are pinned independently and legitimately differ where they differed at HEAD (noted in Step 1).
- Each new test module keeps the `if __name__ == "__main__":` footer with its own slug:
  `run_cli(ALL_TESTS, "claude-retry-proxy tests: test_compat_cm")` / `…test_compat_policy` / `…test_compat_retry` / `…test_compat_reasoning`. Kept: `run_cli(ALL_TESTS, "claude-retry-proxy tests: test_compat")` unchanged.

### Pinned file docstrings

Each destination file's module docstring (kept file: replaces the source docstring; new files: new):

- `tests/test_compat.py`:
  ```
  """Compatibility-learning tests for claude-retry-proxy: the _CompatState
  persistence layer — fail-open loading, schema normalization, atomic writes,
  concurrency, key isolation, locks, and metadata-only trace accuracy.

  The live-loop clusters live in their own modules (test_compat_cm,
  test_compat_policy, test_compat_retry, test_compat_reasoning) with shared
  fixtures in _compat_support (plan 2026-11-26-partition-test-compat).

  Part of the claude-retry-proxy suite; runnable standalone."""
  ```
- `tests/_compat_support.py`:
  ```
  """Shared fixtures for the compatibility-learning tests.

  The cross-cluster constants (the 400-body constants, the shared
  rejected-body corpus, the reasoning complaint body) and the fixture helpers
  every compat test module drives the live learning flow with. Members moved
  byte-verbatim from tests/test_compat.py (plan
  2026-11-26-partition-test-compat); single-cluster helpers live in their
  cluster files."""
  ```
- `tests/test_compat_cm.py`:
  ```
  """context_management live-loop tests: the 400-shape detector and the
  learn/strip/suppress/passthrough flow through a live proxy."""
  ```
- `tests/test_compat_policy.py`:
  ```
  """context_management switch-policy tests: the strip-threshold ladder,
  rejection doubling, probation, delisting, and probe-counter semantics."""
  ```
- `tests/test_compat_retry.py`:
  ```
  """Compatibility retry orchestration tests: the global single-retry lock,
  release on exception, the entry-time config snapshot under config swaps,
  stream interaction, and metadata-only trace privacy."""
  ```
- `tests/test_compat_reasoning.py`:
  ```
  """reasoning_field credit-learner live tests: walk candidates, complaint
  counting and matcher shapes, the demanding-turn presence gate, the rescue
  passes, and admin-swap parameter carry."""
  ```

### Derived Imports (gate-pinned, exact)

Per-file import blocks. `_harness` and `_compat_support` names alphabetical; stdlib sorted; `claude_retry_proxy.nesting` where pinned; intra-test imports kept-file only. `run_cli` rides every footer-bearing module's `_harness` set (the pinned `__main__` footer calls it; the derivation is footer-aware).

| File | stdlib | `_harness` | `_compat_support` | other |
|---|---|---|---|---|
| `_compat_support.py` | json, os, shutil, tempfile | `_mode_tiers`, `_send_proxy_request`, `_start_mode_proxy`, `fail`, `find_free_port`, `warn` | — | — |
| `test_compat.py` (kept) | json, os, shutil, tempfile, threading | `fail`, `pass_`, `run_cli`, `warn` | `CM_MARKER`, `ERROR_MARKER`, `UPSTREAM_ERROR_MARKER`, `_bootstrap_learned_state`, `_cm_count`, `_cm_request`, `_compat_trace_events`, `_entries`, `_entry_values`, `_make_state_dir`, `_mutate_entry`, `_read_state_file`, `_reject_unstripped_responder`, `_send`, `_start_compat_proxy`, `_walk_strips`, `_write_state_file` | 4 intra-test ALL_TESTS imports (above) |
| `test_compat_cm.py` | json, shutil | `fail`, `find_free_port`, `pass_`, `run_cli` | `ERROR_MARKER`, `OBSERVED_400_BODY`, `REJECTED_BODY_CORPUS`, `_cm_count`, `_cm_request`, `_compat_trace_events`, `_entries`, `_entry_values`, `_make_state_dir`, `_read_state_file`, `_reject_unstripped_responder`, `_send`, `_start_compat_proxy` | — |
| `test_compat_policy.py` | json, shutil | `fail`, `pass_`, `run_cli` | `_bootstrap_learned_state`, `_cm_count`, `_cm_request`, `_entries`, `_entry_values`, `_make_state_dir`, `_mutate_entry`, `_ok_response`, `_read_state_file`, `_reject_unstripped_responder`, `_send`, `_start_compat_proxy`, `_walk_strips` | — |
| `test_compat_retry.py` | json, shutil, threading, time | `_admin_post`, `_send_proxy_request_stream`, `fail`, `find_free_port`, `pass_`, `run_cli` | `CM_MARKER`, `ERROR_MARKER`, `OBSERVED_400_BODY`, `REASONING_MESSAGE_400`, `UPSTREAM_ERROR_MARKER`, `_bootstrap_learned_state`, `_chat_ok_response`, `_chat_vendor`, `_cm_count`, `_cm_request`, `_compat_trace_events`, `_entries`, `_entry_values`, `_make_state_dir`, `_ok_response`, `_read_state_file`, `_reasoning_request`, `_reject_unstripped_responder`, `_rescue_trace_events`, `_send`, `_sent_reasoning_field`, `_start_compat_proxy`, `_walk_strips` | — |
| `test_compat_reasoning.py` | json, os, shutil | `_admin_post`, `_mode_tiers`, `_trace_events_named`, `fail`, `find_free_port`, `pass_`, `run_cli` | `REASONING_MESSAGE_400`, `REJECTED_BODY_CORPUS`, `_chat_ok_response`, `_chat_vendor`, `_compat_trace_events`, `_entries`, `_entry_values`, `_make_state_dir`, `_read_state_file`, `_reasoning_request`, `_rescue_trace_events`, `_send`, `_sent_reasoning_field`, `_start_compat_proxy` | `from claude_retry_proxy.nesting import MAX_JSON_NESTING_DEPTH` |

The sets are derived mechanically from member bodies at HEAD (word-boundary scan); the gate re-derives them from the working tree and asserts exact equality with this table. A member-derived name the tester finds unused after a real edit is a stop-and-report, never a silent import drop.

### Catalog sync (planner lane, Step 2)

`doc/test-catalog.html` Category 7 (`<h3 id="cat-7">…`): the current single section anchors on `<h4><code>tests/test_compat.py</code> — the compatibility learner</h4>` (the catalog's dominant h4 convention appends ` — <prose>` after `</code>`). Replace it with five `<h4>` sections in this order, each with a **descriptive, count-free prose suffix** (the counts below are plan-side annotations, never written into the catalog): `tests/test_compat.py` — the `_CompatState` persistence layer (18 `<li>`); `tests/test_compat_cm.py` — context_management live loop (15); `tests/test_compat_policy.py` — context_management switch policy (6); `tests/test_compat_retry.py` — retry orchestration and trace privacy (5); `tests/test_compat_reasoning.py` — reasoning_field credit learner (12). Per-section `<li>` order is the module's def order (Move Inventory order) — for the reasoning section this differs from the current catalog order, in which two entries are hoisted; the re-section relocates them to def order. `<li>` entries move byte-identical — the seven reasoning-region entries carrying ` (added YYYY-MM-DD)` annotations and the one pre-existing slug-form entry (`<code>compat-guarded-parse-nesting-limit</code>` instead of the function name — a known catalog bug, tolerated as-is this partition) move verbatim; the gate normalizes both forms when checking. Also split the module-map table row (`test_compat.py`) into the five test-file rows (per-file Covers prose in the existing style, `compatibility.html` cross-reference preserved on the kept-file row; table cells carry bare filenames — `<td><code>_compat_support.py</code></td>` — with the `tests/` prefix reserved for the Category 7 `<h4>` headings) and add a sixth row for `tests/_compat_support.py` in the `_harness.py` row's non-test-module style ("Not a test module. Shared compatibility-learning fixtures and constants…"). Because this partition establishes the chained-ALL_TESTS registration (aggregator untouched; the kept file imports its siblings), also reword the catalog's L37–40 entry-point sentence and §Adding a test step 3 to describe that pattern — see the Document Overrides row. Do not refresh any counts.

### Rollback

`git restore --source=HEAD --staged --worktree tests/test_compat.py` (Step 1's tracked file) and — once Step 2 has touched it — `git restore --source=HEAD --staged --worktree doc/test-catalog.html`; **precondition:** each tracked file's only uncommitted changes are this plan's edits. The five new test files are untracked and are **left in place** by rollback — inert, untracked, and unused by the restored kept file — and their eventual removal is the user's, never a scripted `rm` (file-deletion doctrine). The gate script under `tmp/verification/` is an untracked verification artifact and survives by design. The gate is a pre-change-HEAD tool: after the Step 10 commit a re-run aborts at `gate aborted: HEAD calibration failed` (the committed HEAD no longer carries the 97-member source) — expected post-commit behavior, not a fault.

### Byte-identity sources

Every moved def/const segment is byte-identical to `HEAD:tests/test_compat.py`'s same-named segment (name-keyed sha256; module-level constants compared as their `Assign` statement source; a constant's preceding comment block rides and is gate-checked positionally adjacent and text-identical to HEAD's block). New-file-only text (docstrings, import blocks, footers, `ALL_TESTS` restructures) is pinned above, not sha-pinned. The kept file's 21 moved members are sha-identical to their HEAD segments; its 22nd member, `ALL_TESTS`, is the pinned restructure.

## Tests to investigate for retirement

None — members move, no test's coverage changes.

## Summary

**Problem.** `tests/test_compat.py` is the suite's largest module (4,127 lines, 56 tests) — the next over-threshold target of the /refactor-split campaign after the chat-sse partition closed the previous largest. Its own `ALL_TESTS` section comments (A. Persistence / state, B. Detector, C. Learn/strip flow, D. Thresholds / state machine, E. Concurrency / robustness, F. Trace privacy, G. reasoning_field) already name the clusters; the file mixes the `_CompatState` persistence layer, two features' live loops, and 27 shared helpers in one module.

**Approach.** Partition into a kept persistence file + four feature-area files + one support module, following the chat-sse partition's mechanics (byte-verbatim member moves, name-keyed sha256 gates, catalog re-section) with one design upgrade: the 29 cross-cluster helpers/constants go to a dedicated `tests/_compat_support.py` instead of living in a member file — the trace-helper consolidation (2026-11-26-consolidate-trace-helpers) just paid to remove a sibling-import seam, so this partition has no seam from day one. Single-cluster helpers move with their readers. The aggregator is untouched: the kept file's `ALL_TESTS` concatenates the four new modules' tuples, so `tests/test_claude_proxy.py` stays byte-identical.

**Key decisions.**
- Cluster membership follows the file's own ALL_TESTS sections and `doc/compatibility.html`'s taxonomy: persistence (A) stays; detector+learn/strip (B+C) merge into `test_compat_cm.py` (one feature's live loop); thresholds (D) become `test_compat_policy.py`; concurrency+trace (E+F) become `test_compat_retry.py`; reasoning_field (G) becomes `test_compat_reasoning.py`.
- `_compat_support.py` is a §7 test-side support leaf: task-shaped (compat learning-flow fixtures), imports only stdlib + `_harness`, imported by all five test files.
- Constants distribute by reader: constants read by more than one destination file (the 400 bodies, the shared rejected-body corpus, the markers, `REASONING_MESSAGE_400`) ride support, as do support-internal fixture constants whose only readers live in the support leaf (`STATE_ENV`, `CM_VALUE`, `SSE_BODY`); single-file constants (`STRUCTURED_400_BODY`, the state-key sets, `VALID_ENTRY_BODIES`) ride their file.
- `test_compat_guarded_parse_nesting_limit` rides the reasoning file (its section and neighbors), despite the `test_compat_` name — the name is pre-existing; moves never rename (§5).
- Catalog Category 7 re-sections 1:1 with byte-identical descriptions; CLAUDE.md needs no edit.

**Out of scope:** the remaining over-threshold test modules (`test_retry_streaming.py` 3,597, `test_chat_transform.py` 2,827, `test_cli.py` 2,572, `test_tier_routing.py` 2,087, `_harness.py` 2,045) — each its own plan; any harness refactor; the admin-html helper seam.

## Repo Mode

Public

## Document Overrides

| Document | Rule Overridden | Reason |
|----------|----------------|--------|
| doc/test-catalog.html §Adding a test, step 3 (and the L37–40 entry-point sentence) | Register each new test module in `tests/test_claude_proxy.py` | This partition deliberately keeps the aggregator byte-identical: the kept file's `ALL_TESTS` concatenates the four new modules' tuples (chained registration), so the aggregator imports one compat surface, not four. Step 2's catalog sync rewords both spots to describe the chained pattern; the override row records the deviation from the catalog's own convention |

## Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| A moved member misses a dependency in its new file | `NameError` at import, suite red | Derived-import tables are gate-pinned exact per file; full suite + standalone `--list` verifies are the gate |
| Separator/comment drift makes the move non-verbatim | Gate byte-checks fail, red round | 2-blank separators pinned; comment-block ride-along pinned per constant; per-member sha256 vs HEAD |
| ALL_TESTS order breaks under concatenation | Suite count/slug drift | Gate asserts the kept concatenation equals the source tuple's 56-slug sequence; aggregator untouched |
| Catalog sync drops, duplicates, or reorders an `<li>` | Doc/test catalog desync | 1:1 distribution pinned (18/15/6/5/12) in def order; gate normalizes the ` (added …)` and slug-form entries and asserts per-section name sequences + module-map rows; ul-balance check |

## Proposed Changes

1. **Step 1 (tester): Partition** — the six-file edit exactly as pinned above.
   → tester verify (scripted): `python3 ./tmp/verification/2026-11-26-partition-test-compat-gate.py --tests` exits 0 (test-file checks; catalog checks are Step-2-gated).
   → tester verify: `python tests/test_claude_proxy.py` exits 0.
   → tester verify: standalone `--list` per new module (15/6/5/12, pinned slugs); kept `--list` 56.
   → tester verify: `python scripts/check_spawn_isolation.py` PASS.
2. **Step 2 (planner): Catalog sync** — `doc/test-catalog.html` per the Catalog sync section, then the full gate exits 0.

## Guidance for Planner

- **Files to modify (What to sync):** `doc/test-catalog.html` — the Catalog sync section above is the spec (planner lane; both precedent partitions assigned the catalog to the planner in a dedicated step). CLAUDE.md's `tests/` line stays true; no other doc.
- **`doc/compatibility.html`:** reviewed — it carries no test-file references (its catalog cross-link target is maintained by the module-map row above); no update needed.
- **`README.md`:** reviewed — its Testing section and doc table enumerate no test modules; no update needed.
- **`.claude/mega-audit-files.json`:** no declared audit locations exist in this repo.
- **When:** Step 2 runs after Step 1's green verifies, before `/update-and-commit`; nothing rides the commit beyond Step 9.6's archival.

## Cross-References to Prior Plans

| Prior Plan | Deferred Issue | Resolution |
|------------|----------------|------------|

## History

| Date | Event | Conclusion | Dismissed |
|------|-------|------------|-----------|
| 2026-11-26 | Initial plan | Survey: 4,127 lines, 56 tests, 27 helpers, 14 module constants (97 top-level members); the file's own ALL_TESTS sections (A–G) name the clusters, matching doc/compatibility.html's taxonomy; user approved the 6-file scheme (kept persistence + `_compat_support.py` + cm/policy/retry/reasoning); support module chosen over a sibling-import seam (the trace-helper consolidation just removed one); aggregator untouched via kept-file ALL_TESTS concatenation; gate RED-calibrated against the pre-change tree (fails on exactly the not-yet-done conditions: 5 missing files, kept still holding the moved 75, source import sets/separator heterogeneity) | `test_compat_guarded_parse_nesting_limit`'s cross-feature name — moves with its section, no rename (§5) |
| 2026-11-26 | Mega-audit iteration 1 (pre-implementation, run `wf_eae3b613-118`, 9 lenses; 57 findings: 18 High / 17 Medium / 22 Low, verdict needs-revision; report at `./tmp/reports/2026-11-26-partition-test-compat-mega-audit-2026-11-26.json`) | The 18 Highs collapse into five roots, all fixed: (1) `run_cli` absent from every footer-bearing module's pinned `_harness` set — the footer calls it, the member-body derivation never saw it; added to all five sets in plan + gate, and the gate's derivation is now footer-aware; (2) the kept-ALL_TESTS check regexed 56 pairs out of a literal that post-partition holds only 18 + aliases — redesigned as three checks (18 own slugs == HEAD's first 18; alias tail regex; 18+38==56); (3) the reasoning module's ALL_TESTS check demanded BOTH HEAD-section-G order and def order, which already differ at HEAD — the def-order conjunct dropped (the slug-sequence check is the invariant); (4) the catalog checks matched neither the real h4 convention (` — <prose>` suffix — regex relaxed), nor 8 reasoning `<li>` forms (7 carry ` (added …)` annotations, 1 is the pre-existing slug-form bug — gate now normalizes both, entries move byte-identical); and (5) the gate itself broke the spawn-isolation corpus (subprocess + proxy tokens, no isolation block) making two Step-1 verifies unsatisfiable — the canonical mkdtemp + three-assignment block added; `check_spawn_isolation` now PASSes with the gate a classified spawner. Other Highs fixed: catalog sync moved to the planner lane (Step 2, `doc_files`; both precedent partitions' shape). Mediums fixed: kept `--list` expectation corrected to 56 (the concatenation design's own consequence); the eight unplaced section banners pinned as DELETED with gate absence checks (A–G + reasoning-helpers; labels survive in docstrings and ALL_TESTS comments); REASONING_MESSAGE_400's note corrected (L153–155 is the deleted helpers banner, L157–159 is its own riding comment); the policy docstring reworded to context_management (the six threshold tests drive `_cm_request`/`_walk_strips` on cm entries — reality lens verified against doc/compatibility.html); comment ride-alongs now positional (contiguous block adjacent above the constant, byte-equal to HEAD's block) replacing the substring test, with the kept fragments fixed (the old kept fragment was a test docstring, vacuous; ENVELOPE's fragment moved from support to kept); member count corrected 89→97 / moved 67→75; catalog `<li>` per-section order pinned to def order; the false "source block's order" import wording corrected to alphabetical; VALID_ENTRY_BODIES annotated with its L601–602 comment; rollback rewritten doctrine-conformant (no scripted `rm` — untracked new files left in place, user removes); post-commit gate behavior described accurately (calibration abort). Lows folded in: kept byte-identity restated 21/22 (ALL_TESTS excluded), line counts corrected (4,127; harness 2,045), "absent from every table" wording, gate KeyError guards + aggregator except broadened, module-map table row check added (five test rows + `_compat_support.py` row), gate docstring counts. Gate re-calibrated: exit 1 on the untouched tree with 32 FAILs, every one an exact not-yet-done condition (including the eight now-correctly-fragmented banner absence checks); all calibration checks pass; spawn-isolation corpus clean | Six of the 18 Highs were one root seen by six lenses (dedup keeps them separate by location) — counted individually per the report's findings list, fixed once |
| 2026-11-26 | Mega-audit iteration 2 (pre-implementation, run `wf_4b1bb02c-a33`, 9 lenses; 31 findings: 8 High / 6 Medium / 17 Low, verdict needs-revision; report at `./tmp/reports/2026-11-26-partition-test-compat-mega-audit-2026-11-26-r2.json`) | Highs fixed: (1) the banner-absence checks were unsatisfiable post-change — six label-line fragments are substrings of the indented `ALL_TESTS` section comments the plan keeps verbatim (RED could not expose it: the destination files do not exist pre-change); the check now matches the full 3-line banner block, which an indented single-line comment can never contain, and C's dropped qualifier is noted; (2) the policy-docstring gate/plan desync — the iteration-1 gate edit for the context_management reword had silently no-opped (unasserted replace); applied and verified; (3) the gate could not exit 0 at Step 1 because the catalog checks ride in it while the catalog is Step-2 work — the gate gained a `--tests` phase (Step 1's verify) with the catalog + module-map checks gated to the full run (Step 2's verify); (4) the docstring member-count fix had also silently no-opped — applied (97). Mediums fixed: the module-map region now splits on the catalog's real `<!-- BEGIN per-test inventory` marker (the invented marker matched nothing, unbinding the row checks) with a presence check; Step 2's rollback gained its own heading, the catalog restore, and the precondition; the five `<h4>` suffixes pinned as descriptive count-free prose (the per-section counts are plan-side annotations, never catalog text); the reasoning section's `<li>`-order change from the current catalog order stated explicitly; `doc/compatibility.html` given a reviewed-no-update planner line; the Documentation section's stale Step-1 reference corrected. Lows folded in: `load()` total guard (except Exception per the repo doctrine), mapping duplicate-membership count check, seg/kseg None guards, kept-file stdlib/harness calibration now derived from HEAD members too, `_detector_scenario` clause dropped, intra-test import order pinned as ordered (matching the gate), post-commit gate-abort wording retained. Gate re-verified post-fixes: `--tests` RED shows 24 FAILs, every one an exact not-yet-done condition; full-gate catalog RED correct; both phases parse and run | Six findings re-reported the two silent iteration-1 no-ops — every batch replacement is now asserted; recorded as the operative lesson |
| 2026-11-26 | Mega-audit iteration 3 (pre-implementation, run `wf_c74d5dbd-f4f`, 9 lenses; 30 findings: 0 High / 8 Medium / 22 Low, verdict non-blocking — 0 High exits the iteration loop at the cap; report at `./tmp/reports/2026-11-26-partition-test-compat-mega-audit-2026-11-26-r3.json`) | Mediums fixed: (1) ALL_TESTS checks compared slug halves only — a correct slug paired with the wrong function passed everything silently; name halves now compared for kept (18 own) and each new module (full pairs vs HEAD-filtered pairs); (2) the full-gate catalog block crashed UnboundLocalError on an unreadable catalog (`csrc` bound only inside a branch) — bound unconditionally; (3) the G banner absence check sliced only 3 of its 9 lines — `DELETED_BANNERS` now checks the full declared span per entry; (4) the aggregator-untouched design deviates from the catalog's own §Adding-a-test step 3 — recorded as a Document Override row and Step 2's catalog sync now rewords the L37–40 entry-point sentence and step 3 to describe the chained-ALL_TESTS pattern; module-map cells pinned to the bare-filename form; `check_doc_anchors.py` added to Step 2's verifies; one `-t <slug>` single-test run per new module added to Step 1's verifies (standalone-import proof); support docstring and Summary bullet reworded ("400-body constants" — kept gate/plan identical); README given a reviewed-no-update planner line; separator re-measure parenthetical simplified (conclusion kept, stale enumeration dropped). Lows folded in: per-module ALL_TESTS section-comment presence checks pinned; ordered import-subject-sequence check; exact top-level membership per file + support-defines-no-ALL_TESTS; per-file 1,500-line ceiling check; separator boundary extended to the last-import→first-member gap; dead `std_used` removed; `<li>` byte-identity left as normalize-and-order checks (full-line sha deferred to the per-section name-sequence equality, which pins position exactly). Gate re-verified post-fixes: both phases parse and run, `--tests` RED 28 FAILs (every one an exact not-yet-done condition incl. the new ceiling/membership/order checks), 11 calibration checks green | The `<li>` full-line sha comparison (edge-case #21) — the per-section ordered name-sequence check already pins position and the normalized-name equality pins identity; residual drift surface is the annotation/slug forms the gate deliberately tolerates |
| 2026-11-26 | Tester round 1 (Step 1 Partition; report at `./tmp/reports/2026-11-26-partition-test-compat-tester-2026-11-26.json`) | SUCCESS — full suite 555/555 (count unchanged from HEAD; aggregator byte-identical), six files delivered byte-verbatim per the Move Inventory (kept 1,001 / support 387 / cm 609 / policy 480 / retry 529 / reasoning 1,301 lines, all ≤ 1,500), gate `--tests` 367/367 exit 0, standalone `--list` 15/6/5/12 + kept 56, four single-test standalone runs PASSED, `check_spawn_isolation` PASS (gate + generator classified spawners with the canonical block). GATE DEVIATION ratified: the two unsatisfiable checks (issue [gate-unsatisfiable-checks](./tmp/reports/2026-11-26-partition-test-compat-gate-unsatisfiable-checks.json), Issue Log Resolved) — same RED-invisible class as r1/r2's post-change-only defects. r3's hunch #4 cleared by the tester: `run_cli` consumes `(slug, function-object)` pairs via `dict(all_tests)`, so the kept footer resolving 38 concatenated foreign callables standalone is namespace-irrelevant (same code path as the aggregator; no separate run needed) | — |
| 2026-11-26 | Step 2: Catalog sync (planner lane) | `doc/test-catalog.html` synced: Category 7 re-sectioned into the five `<h4>` sections in plan order (18/15/6/5/12 `<li>`, def order, entries byte-identical incl. the seven ` (added …)` annotations and the slug-form entry); module-map `test_compat.py` row split into the five test rows + the `_compat_support.py` non-test row (compatibility.html cross-ref preserved on the kept row); entry-point sentence + §Adding-a-test step 3 reworded to the chained-ALL_TESTS pattern per the Document Overrides row. Verifies: full gate 389/389 exit 0 (pre-sync RED was exactly the 8 expected catalog FAILs); `check_doc_anchors.py` PASS (272 anchors, 8 files, no secret shapes) | — |
| 2026-11-26 | Phase 6 implementation review (report at `./tmp/reports/2026-11-26-partition-test-compat-review-2026-11-26.json`) | Verdict **Issues found — non-blocking** (0 Critical / 0 Warning / 2 Suggestion) — commit-ready; reviewer independently re-verified the ALL_TESTS 56-pair concatenation (slug AND name sequence vs HEAD), every per-file import block vs the Derived Imports table, member counts 29/18/6/5/17/22, footers, banner deletions, aggregator byte-identity (empty diff vs HEAD), and the catalog diff line-by-line. Both Suggestions share one root: the plan's new-file-text fences — the six docstring closings and the kept-file intra-test import blanks — had drifted from the operative forms the gate/generator pinned and the files delivered; the gate is placement-agnostic by construction (`ast.get_docstring` strips closings; the import check asserts subject order, not blank placement), so no gate could catch it. Resolved in the planner lane by amending the plan's fences to the delivered/operative forms (the fenced blocks above now document the shipped bytes) — no file, gate, or generator churn for a closing-quote/blank-line cosmetic; the resulting house-style deviation from `tests/_harness.py` / `test_chat_sse.py`'s own-line docstring closings is accepted. Residual, deliberate: the gate does not assert raw closing placement or import-blank separation — stripped-text and order-level assertions are its design; the raw forms live in these fences for regeneration fidelity | Three review hunches, none promoted: catalog kept-section `<li>` leading indent normalized 2→0 spaces (whitespace-only — covered by the dismissed `<li>` full-line-sha gap); the Helpers banner abuts `_cm_request` with no blank (blank count still 2 under the comment-excluded separator model the gate asserts); the catalog h4 renders `_CompatState` as plain text while the module-map row uses backtick-code (h4 suffixes are pinned count-free prose; no markup pin exists) |

## Plan Metadata

```json
{
  "plan_id": "2026-11-26-partition-test-compat",
  "steps": [
    "Step 1: Partition",
    "Step 2: Catalog sync"
  ],
  "coder_files": [],
  "tester_files": [
    "tests/test_compat.py",
    "tests/_compat_support.py",
    "tests/test_compat_cm.py",
    "tests/test_compat_policy.py",
    "tests/test_compat_retry.py",
    "tests/test_compat_reasoning.py"
  ],
  "doc_files": [
    "doc/test-catalog.html"
  ],
  "verification_scripts": [
    "./tmp/verification/2026-11-26-partition-test-compat-gate.py"
  ],
  "retire_inventory": [
    "./tmp/verification/2026-11-26-partition-test-compat-gate.py",
    "./tmp/verification/2026-11-26-partition-test-compat-generate.py",
    "./tmp/reports/2026-11-26-partition-test-compat-mega-audit-2026-11-26.json",
    "./tmp/reports/2026-11-26-partition-test-compat-mega-audit-2026-11-26-r2.json",
    "./tmp/reports/2026-11-26-partition-test-compat-mega-audit-2026-11-26-r3.json",
    "./tmp/reports/2026-11-26-partition-test-compat-gate-unsatisfiable-checks.json",
    "./tmp/reports/2026-11-26-partition-test-compat-tester-2026-11-26.json",
    "./tmp/reports/2026-11-26-partition-test-compat-review-2026-11-26.json"
  ],
  "repo_mode": "Public",
  "document_overrides": []
}
```

## Audit Accumulation

| Counter | Value | Last Updated |
|---------|-------|--------------|
| issues_resolved_since_audit | 1 | 2026-11-26 |
| steps_changed_since_audit | 2 | 2026-11-26 |
| files_changed_since_audit | 7 | 2026-11-26 |

## Documentation

- `doc/test-catalog.html` Category 7 re-sections in Step 2, planner lane (five file sections, 1:1 `<li>` distribution in def order, byte-identical descriptions, module-map rows). No other doc names compat helper surfaces; CLAUDE.md's `tests/` line stays true; README does not enumerate test modules.

## Final Results

**Completed 2026-11-26 — status COMPLETED.**

**Files changed:**
- `tests/test_compat.py` — kept module: 22 members (21 sha-verbatim + the restructured chained `ALL_TESTS`), 1,001 lines
- `tests/_compat_support.py` — new support leaf, 29 members, 387 lines
- `tests/test_compat_cm.py` — new, 18 members, 609 lines
- `tests/test_compat_policy.py` — new, 6 members, 480 lines
- `tests/test_compat_retry.py` — new, 5 members, 529 lines
- `tests/test_compat_reasoning.py` — new, 17 members, 1,301 lines
- `doc/test-catalog.html` — Step 2 catalog sync (Category 7 re-sectioned into five `<h4>` sections in def order, six module-map rows, chained-ALL_TESTS prose in the entry-point sentence and §Adding-a-test step 3)
- `tests/test_claude_proxy.py` — untouched, byte-identical to HEAD (reviewer-verified: empty diff)

**Test results:** full suite 555/555 passed (count unchanged from HEAD); verification gate `--tests` 367/367, full gate 389/389 exit 0; standalone `--list` 15/6/5/12 + kept 56; four single-test standalone runs PASSED; `scripts/check_spawn_isolation.py` PASS; `scripts/check_doc_anchors.py` PASS (272 anchors, 8 files).

**Issues resolved:** [gate-unsatisfiable-checks](./tmp/reports/2026-11-26-partition-test-compat-gate-unsatisfiable-checks.json) — two plan-authored gate checks failed a plan-correct partition; the tester corrected both in-gate with teeth preserved and the planner ratified (Issue Log Resolved 2026-11-26).

**Deferred issues:** none — this plan adopted no deferrals and filed none.

**Review:** Phase 6 non-blocking — 0 Critical / 0 Warning; the two cosmetic Suggestions (docstring closing placement, intra-test import blank separation) were a plan-fence vs operative-form desync, resolved by amending the plan's fences to the delivered bytes (History; no file/gate churn).
