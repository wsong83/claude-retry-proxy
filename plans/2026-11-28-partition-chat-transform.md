# Plan: Partition tests/test_chat_transform.py into feature-area test files

**Plan ID:** 2026-11-28-partition-chat-transform
**Created:** 2026-11-28

## Issue Log

| Issue | Status | Found | Resolved | Resolved By |
|-------|--------|-------|----------|-------------|

## Guidance for Coder

None. Test-file changes are tester-lane exclusively; no coder steps.

## Guidance for Tester

**Tests to create:** none — this plan moves tests byte-verbatim; no test's behavior changes.

**Verification scripts to create:** none by the tester — the planner-authored gate at `./tmp/verification/2026-11-28-partition-chat-transform-gate.py` is the scripted check; reference any behavioral script you add in the session report.

**Files to modify (tester lane):**
- `tests/test_chat_transform.py` (kept: header rewritten, 17 tests + 1 const remain)
- `tests/test_chat_transform_tools.py` (new: 17 members)
- `tests/test_chat_transform_patterns.py` (new: 8 members)
- `tests/test_chat_transform_chat_to_anthropic.py` (new: 14 members)
- `tests/test_chat_transform_images.py` (new: 4 members)

**Step-by-step with verification:**

1. **Step 1 (tester): Partition.** Partition the 61 pinned members byte-verbatim — **43 move** to the four new files, **18 stay** byte-verbatim in the kept file (17 tests + the `_OMIT` const); `ALL_TESTS` is restructured per its own section. Each member is exactly `ast.get_source_segment(HEAD:tests/test_chat_transform.py, member)`. Each riding comment block moves **with the member it precedes** in the source's own geometry — the two blocks differ, and the gate pins each at its exact offset: the `_OMIT` sentinel is **directly adjacent** to its assign (HEAD L427 comment, L428 assign, no blank), while the Step-5 banner has **one blank** between banner and def (HEAD L1879 banner, L1880 blank, L1881 def). Both preserve the byte-verbatim form. There are 2 riding blocks: the 1-line `# Sentinel for "the caller omitted reasoning_selection entirely".` above `_OMIT` (kept) and the 1-line `# --- Step 5: _chat_to_anthropic ---` section banner above `test_chat_to_anthropic_basic` (chat_to_anthropic). Member order within each destination file preserves the source def order (the Move Inventory order). Separators: exactly **2 blank lines between top-level members in every destination file** (uniform convention; a riding block sits inside its member's block, block lines counted as content). The 2-blank rule also pins three seams the source heterogeneity would not predict — last-import→first-member, last-member→`ALL_TESTS`, and `ALL_TESTS`→footer (only intra-import seams are unpinned; the green-sim generator's emitted form is the reference geometry). Build each file's import block from its pinned Derived Imports table below (stdlib sorted as in source, single `_harness` block, one package-import line where pinned). Each new test module ends with its own `ALL_TESTS` list (exactly its pinned pairs, same `("slug", name)` form) and the pinned `__main__` footer. The kept file's `ALL_TESTS` becomes its own 17 pairs followed by `+ TOOLS_TESTS + PATTERNS_TESTS + CHAT_TO_ANTHROPIC_TESTS + IMAGES_TESTS` from four new pinned intra-test imports (see ALL_TESTS restructure). **The aggregator `tests/test_claude_proxy.py` is untouched byte-for-byte** (chained registration, the catalog-documented `tests/test_compat.py` pattern). A drifted or zero-length source range on re-verification is a stop-and-report.
   → tester verify (scripted): `python3 ./tmp/verification/2026-11-28-partition-chat-transform-gate.py --tests` exits 0 (the test-file checks; the catalog checks are Step-2-gated and excluded here).
   → tester verify: `python tests/test_claude_proxy.py` exits 0 (full suite green — during-plan the corpus holds this plan's two compliant planner scripts, so the spawn-isolation corpus hook passes; see Baseline). The catalog's §Adding-a-test step-5 "with a live proxy running" clause is satisfied by construction: the harness isolation (trace/compat/state overrides at module load) makes the suite safe alongside a live proxy — documented in project CLAUDE.md — and a byte-verbatim partition changes no behavior the clause guards.
   → tester verify: each new module standalone: `python tests/test_chat_transform_tools.py --list` (17 slugs), `…_patterns.py --list` (8), `…_chat_to_anthropic.py --list` (14), `…_images.py --list` (4); plus one single-test run per new module proving the standalone import path, each PASSED: `python tests/test_chat_transform_tools.py -t chat-zero-arg-tool`, `python tests/test_chat_transform_patterns.py -t sanitize-body-tools-totality`, `python tests/test_chat_transform_chat_to_anthropic.py -t chat-to-anthropic-nesting-guard-total`, `python tests/test_chat_transform_images.py -t chat-to-anthropic-image-parts-filtered`.
   → tester verify: `python tests/test_chat_transform.py --list` — 60 slugs (17 own + 43 concatenated), the concatenated order the pinned kept-then-siblings sequence.
   → tester verify: `python tests/test_claude_proxy.py --list` — the aggregator-level registration proof the catalog's §Adding-a-test step 3 demands: the full list runs and the 60 chat-transform slugs appear contiguously at the `CHAT_TRANSFORM_TESTS` position (the aggregated list resolves through the kept file's chained imports).
   → tester verify: one aggregator-level targeted run through the chained registration, e.g. `python tests/test_claude_proxy.py -t chat-zero-arg-tool` — PASSED.
   → tester verify: `python scripts/check_spawn_isolation.py` PASS.

2. **Step 2 (planner): Catalog sync.** Re-section `doc/test-catalog.html` per Guidance for Planner → What to sync (Category 4 five sections, module-map rows), then `python3 ./tmp/verification/2026-11-28-partition-chat-transform-gate.py` exits 0 (the full gate — catalog checks pass only after this step) and `python scripts/check_doc_anchors.py` exits 0. No other doc changes: CLAUDE.md's `tests/` line ("per-area test modules + aggregator") stays true.

### Move Inventory

61 members (60 tests + 1 const, per HEAD's AST inventory at `eb6b3d0`); 43 leave the kept file (17+8+14+4 across the four new files); `ALL_TESTS` is restructured, not moved. Source line numbers are `HEAD:tests/test_chat_transform.py` spans (`ast` top-level `FunctionDef` / `Assign`), re-verified before cutting. Riding comment blocks (2) are listed per member; every top-level statement of the source file lands in exactly one destination. The source has **no helper functions** (every non-test top-level def is absent; the only non-test member is the `_OMIT` const) and **zero cross-destination member references** (mechanically scanned: no test calls another test; `_OMIT`'s sole consumer is `test_chat_transform_emits_only_selected_field`, kept alongside it).

**`tests/test_chat_transform.py` (kept) — 19 members (18 byte-verbatim + `ALL_TESTS` restructured), 874 member-lines (the 18 byte-verbatim members' span sum; the restructured `ALL_TESTS` excluded):**

| Member | Kind | Source lines | Riding block |
|---|---|---|---|
| `test_anthropic_to_chat_messages_transform` | def | 31–63 | — |
| `test_anthropic_to_chat_messages_thinking_stripped` | def | 68–86 | — |
| `test_anthropic_to_chat_messages_redacted_thinking_dropped` | def | 91–267 | — |
| `test_anthropic_to_chat_messages_tool_use_to_tool_calls` | def | 272–292 | — |
| `test_anthropic_to_chat_messages_tool_result_to_role_tool` | def | 297–320 | — |
| `test_anthropic_to_chat_messages_mixed_text_and_tool_use` | def | 325–350 | — |
| `test_anthropic_to_chat_messages_mixed_text_and_tool_result` | def | 355–380 | — |
| `test_anthropic_to_chat_messages_interleaved_thinking_tool_use` | def | 385–422 | — |
| `_OMIT` | const | 428 | L427 (1 line) `# Sentinel for "the caller omitted reasoning_selection entirely".` |
| `test_chat_transform_emits_only_selected_field` | def | 431–545 | — |
| `test_anthropic_to_chat_injection_trace_counts` | def | 548–646 | — |
| `test_anthropic_to_chat_real_thinking_and_redacted_dropped` | def | 649–791 | — |
| `test_anthropic_to_chat_redacted_selection_without_always` | def | 794–863 | — |
| `test_anthropic_to_chat_messages_string_content_passthrough` | def | 866–883 | — |
| `test_anthropic_to_chat_messages_cache_control_stripped` | def | 888–915 | — |
| `test_anthropic_to_chat_messages_non_list_guarded` | def | 920–931 | — |
| `test_anthropic_to_chat_messages_non_dict_entries_skipped` | def | 936–947 | — |
| `test_anthropic_to_chat_messages_null_user_content` | def | 952–963 | — |
| `ALL_TESTS` | const | 2762–2823 | (restructured, see below) |

**`tests/test_chat_transform_tools.py` (new) — 17 members, 520 member-lines:**

| Member | Kind | Source lines | Riding block |
|---|---|---|---|
| `test_anthropic_to_chat_tools_transform` | def | 968–989 | — |
| `test_anthropic_to_chat_tools_cache_control_stripped` | def | 994–1016 | — |
| `test_anthropic_to_chat_tools_non_list_guarded` | def | 1021–1032 | — |
| `test_anthropic_to_chat_tools_malformed_entries_skipped` | def | 1037–1061 | — |
| `test_anthropic_to_chat_tool_choice_mapping` | def | 1458–1475 | — |
| `test_anthropic_to_chat_tool_choice_none_omitted` | def | 1480–1497 | — |
| `test_anthropic_to_chat_tool_choice_malformed_omitted` | def | 1502–1513 | — |
| `test_anthropic_to_chat_tool_choice_only_with_tools` | def | 1518–1539 | — |
| `test_anthropic_to_chat_integration` | def | 1544–1600 | — |
| `test_anthropic_to_chat_content_block_dropped_trace` | def | 1605–1641 | — |
| `test_anthropic_to_chat_cache_control_stripped_trace` | def | 1646–1675 | — |
| `test_anthropic_to_chat_nan_infinity_arguments_rejected` | def | 1680–1712 | — |
| `test_anthropic_to_chat_tool_use_non_dict_input` | def | 1717–1748 | — |
| `test_anthropic_to_chat_nan_placeholder_with_valid_tool_use` | def | 1753–1807 | — |
| `test_anthropic_to_chat_tool_result_list_content` | def | 1812–1838 | — |
| `test_anthropic_to_chat_no_input_mutation` | def | 1843–1874 | — |
| `test_chat_anthropic_to_chat_zero_arg_tool` | def | 2443–2507 | — |

**`tests/test_chat_transform_patterns.py` (new) — 8 members, 360 member-lines:**

| Member | Kind | Source lines | Riding block |
|---|---|---|---|
| `test_strip_regex_identity_escapes_table` | def | 1066–1104 | — |
| `test_sanitize_schema_patterns_walk` | def | 1109–1158 | — |
| `test_sanitize_schema_patterns_no_mutation` | def | 1163–1187 | — |
| `test_sanitize_schema_patterns_value_positions` | def | 1192–1262 | — |
| `test_sanitize_schema_patterns_collision_merge` | def | 1267–1320 | — |
| `test_anthropic_to_chat_tools_pattern_sanitized` | def | 1325–1360 | — |
| `test_sanitize_body_tools_sanitized_copy` | def | 1365–1419 | — |
| `test_sanitize_body_tools_totality` | def | 1424–1453 | — |

**`tests/test_chat_transform_chat_to_anthropic.py` (new) — 14 members, 512 member-lines:**

| Member | Kind | Source lines | Riding block |
|---|---|---|---|
| `test_chat_to_anthropic_basic` | def | 1881–1910 | L1879 (1 line) `# --- Step 5: _chat_to_anthropic ---` |
| `test_chat_to_anthropic_reasoning_content_to_thinking` | def | 1915–1939 | — |
| `test_chat_to_anthropic_reasoning_field_compat` | def | 1944–1974 | — |
| `test_chat_to_anthropic_reasoning_content_empty` | def | 1979–2006 | — |
| `test_chat_to_anthropic_reasoning_content_with_tool_calls` | def | 2011–2038 | — |
| `test_chat_to_anthropic_empty_choices` | def | 2043–2063 | — |
| `test_chat_to_anthropic_tool_calls` | def | 2068–2098 | — |
| `test_chat_to_anthropic_finish_reason_mapping` | def | 2103–2148 | — |
| `test_chat_to_anthropic_usage_absent` | def | 2153–2166 | — |
| `test_chat_to_anthropic_content_array` | def | 2171–2187 | — |
| `test_chat_to_anthropic_malformed_tool_args_text_block` | def | 2192–2278 | — |
| `test_chat_to_anthropic_nesting_limit_tool_args` | def | 2283–2360 | — |
| `test_chat_to_anthropic_nesting_guard_total` | def | 2363–2402 | — |
| `test_chat_to_anthropic_malformed_tool_args_mixed` | def | 2405–2440 | — |

**`tests/test_chat_transform_images.py` (new) — 4 members, 242 member-lines:**

| Member | Kind | Source lines | Riding block |
|---|---|---|---|
| `test_anthropic_to_chat_image_blocks_converted` | def | 2512–2602 | — |
| `test_anthropic_to_chat_tool_result_images_converted` | def | 2605–2704 | — |
| `test_anthropic_to_chat_image_blocks_no_mutation` | def | 2707–2731 | — |
| `test_chat_to_anthropic_image_parts_filtered` | def | 2734–2759 | — |

### ALL_TESTS restructure

Source `ALL_TESTS` (L2762–2823) is one plain list of 60 `("slug", name)` pairs whose order **interleaves the clusters** (the `emits_only_selected_field` pair sits inside the message-pair run; the two nesting pairs sit inside the chat_to_anthropic run, between the two malformed-args pairs; the `chat-zero-arg-tool` and image pairs are last), so no per-module concatenation can reproduce it. The global execution order deliberately changes to kept-then-siblings; within each file the pairs preserve their source relative order. The gate asserts each file's pairs as a name-and-slug-exact subsequence of HEAD's list, the total at 60, and slug-set equality — never the source's global order. Tests are independent (each drives its own transform call; no shared state), so execution order is not load-bearing.

- `tests/test_chat_transform.py` (kept) — own 17 pairs, source order: `anthropic-to-chat-messages-transform`, `anthropic-to-chat-messages-thinking-stripped`, `anthropic-to-chat-messages-redacted-thinking-dropped`, `anthropic-to-chat-messages-tool-use-to-tool-calls`, `anthropic-to-chat-messages-tool-result-to-role-tool`, `anthropic-to-chat-messages-mixed-text-and-tool-use`, `anthropic-to-chat-messages-mixed-text-and-tool-result`, `anthropic-to-chat-messages-interleaved-thinking-tool-use`, `chat-transform-emits-only-selected-field`, `anthropic-to-chat-injection-trace-counts`, `anthropic-to-chat-real-thinking-and-redacted-dropped`, `anthropic-to-chat-redacted-selection-without-always`, `anthropic-to-chat-messages-string-content-passthrough`, `anthropic-to-chat-messages-cache-control-stripped`, `anthropic-to-chat-messages-non-list-guarded`, `anthropic-to-chat-messages-non-dict-entries-skipped`, `anthropic-to-chat-messages-null-user-content`; then `+ TOOLS_TESTS + PATTERNS_TESTS + CHAT_TO_ANTHROPIC_TESTS + IMAGES_TESTS` from four new pinned intra-test imports placed after the `_harness` import block:
  ```python
  from test_chat_transform_tools import ALL_TESTS as TOOLS_TESTS
  from test_chat_transform_patterns import ALL_TESTS as PATTERNS_TESTS
  from test_chat_transform_chat_to_anthropic import ALL_TESTS as CHAT_TO_ANTHROPIC_TESTS
  from test_chat_transform_images import ALL_TESTS as IMAGES_TESTS
  ```
  (consecutive lines, the form the GREEN proof generates; the gate pins only the module/alias sequence, not blank separation between these four)
- `tests/test_chat_transform_tools.py` (17): `anthropic-to-chat-tools-transform`, `anthropic-to-chat-tools-cache-control-stripped`, `anthropic-to-chat-tools-non-list-guarded`, `anthropic-to-chat-tools-malformed-entries-skipped`, `anthropic-to-chat-tool-choice-mapping`, `anthropic-to-chat-tool-choice-none-omitted`, `anthropic-to-chat-tool-choice-malformed-omitted`, `anthropic-to-chat-tool-choice-only-with-tools`, `anthropic-to-chat-integration`, `anthropic-to-chat-content-block-dropped-trace`, `anthropic-to-chat-cache-control-stripped-trace`, `anthropic-to-chat-nan-infinity-arguments-rejected`, `anthropic-to-chat-tool-use-non-dict-input`, `anthropic-to-chat-nan-placeholder-with-valid-tool-use`, `anthropic-to-chat-tool-result-list-content`, `anthropic-to-chat-no-input-mutation`, `chat-zero-arg-tool`.
- `tests/test_chat_transform_patterns.py` (8): `strip-regex-identity-escapes-table`, `sanitize-schema-patterns-walk`, `sanitize-schema-patterns-no-mutation`, `sanitize-schema-patterns-value-positions`, `sanitize-schema-patterns-collision-merge`, `anthropic-to-chat-tools-pattern-sanitized`, `sanitize-body-tools-sanitized-copy`, `sanitize-body-tools-totality`.
- `tests/test_chat_transform_chat_to_anthropic.py` (14): `chat-to-anthropic-basic`, `chat-to-anthropic-reasoning-content-to-thinking`, `chat-to-anthropic-reasoning-field-compat`, `chat-to-anthropic-reasoning-content-empty`, `chat-to-anthropic-reasoning-content-with-tool-calls`, `chat-to-anthropic-empty-choices`, `chat-to-anthropic-tool-calls`, `chat-to-anthropic-finish-reason-mapping`, `chat-to-anthropic-usage-absent`, `chat-to-anthropic-content-array`, `chat-to-anthropic-malformed-tool-args-text-block`, `chat-to-anthropic-nesting-limit-tool-args`, `chat-to-anthropic-nesting-guard-total`, `chat-to-anthropic-malformed-tool-args-mixed`.
- `tests/test_chat_transform_images.py` (4): `anthropic-to-chat-image-blocks-converted`, `anthropic-to-chat-tool-result-images-converted`, `anthropic-to-chat-image-blocks-no-mutation`, `chat-to-anthropic-image-parts-filtered`.
- Each new module keeps the `if __name__ == "__main__":` footer with its own slug: `run_cli(ALL_TESTS, "claude-retry-proxy tests: test_chat_transform_tools")` / `…_patterns` / `…_chat_to_anthropic` / `…_images`. Kept: `run_cli(ALL_TESTS, "claude-retry-proxy tests: test_chat_transform")` unchanged.

### Pinned file docstrings

- `tests/test_chat_transform.py` (replaces the source docstring):
  ```
  """Chat-mode transform tests: the Anthropic-to-Chat request conversion's
  message pipeline — thinking blocks, tool_use/tool_result, cache_control,
  the reasoning-selection matrix, and the coalesced trace-count contract.

  The tools/tool-choice, pattern-sanitization, Chat-to-Anthropic response,
  and image-block clusters live in their own modules
  (test_chat_transform_tools, test_chat_transform_patterns,
  test_chat_transform_chat_to_anthropic, test_chat_transform_images),
  chained through this module's ALL_TESTS
  (plan 2026-11-28-partition-chat-transform).

  Part of the claude-retry-proxy suite; runnable standalone."""
  ```
- `tests/test_chat_transform_tools.py`:
  ```
  """Chat-mode request-transform tool tests: the tools-array conversion,
  tool_choice mapping, end-to-end request traces, tool-argument edge cases
  (NaN/Infinity, non-dict input, list content, zero-arg calls), and input
  non-mutation."""
  ```
- `tests/test_chat_transform_patterns.py`:
  ```
  """Pattern-sanitization tests for the shared transform sanitizers:
  _strip_regex_identity_escapes, _sanitize_schema_patterns, and
  _sanitize_body_tools — their tables, walks, non-mutation, value
  positions, and collision merges — plus the chat-mode end-to-end
  confirmation."""
  ```
- `tests/test_chat_transform_chat_to_anthropic.py`:
  ```
  """Chat-to-Anthropic response-conversion tests: content/usage/stop_reason
  mapping, reasoning_content recognition, tool-call degradation to the
  visible placeholder, and the nesting-limit guards."""
  ```
- `tests/test_chat_transform_images.py`:
  ```
  """Image content-block tests: user-message and tool_result-nested image
  conversion to image_url parts, conversion non-mutation, and the
  response-direction image filtering."""
  ```

### Derived Imports (gate-pinned, exact)

Per-file import blocks. Stdlib sorted as in source; one `_harness` block, names alphabetical with underscore names first as in source; one `claude_retry_proxy` line where pinned. `run_cli` rides every footer-bearing module's `_harness` set (the pinned `__main__` footer calls it; the derivation is footer-aware). Function-local imports inside member bodies are body-verbatim and never appear here: eight `import copy` statements exist at HEAD inside member bodies (L1166/1204/1278/1337/1376/1433 — six patterns members from `no_mutation` through `totality`; L1849 `no_input_mutation` in tools; L2714 `image_blocks_no_mutation` in images) and move with their members; the scope-aware derivation binds local Import aliases as locals, so the derived tables correctly exclude `copy` everywhere. Delivered physical form: every `_harness` import is a single-line unseparated statement (the green-sim generator's reference geometry; the gate pins subjects/order, not blank separation or line-wrapping) — the documented deviation from HEAD's blank-separated multi-line parenthesized convention, following the retry-streaming partition's accepted single-line form (the compat partition's modules use multi-line imports; chained registration, which this plan does share with compat, is a separate precedent).

| File | stdlib | `_harness` | `claude_retry_proxy` |
|---|---|---|---|
| `test_chat_transform.py` (kept) | uuid | `_require_server_func`, `_trace_events_for_request`, `fail`, `pass_`, `run_cli` + the four intra-test `ALL_TESTS` imports | — |
| `test_chat_transform_tools.py` | uuid | `_require_server_func`, `_trace_events_for_request`, `fail`, `pass_`, `run_cli` | — |
| `test_chat_transform_patterns.py` | uuid | `_require_server_func`, `fail`, `pass_`, `run_cli` | `_sanitize_body_tools`, `_sanitize_schema_patterns`, `_strip_regex_identity_escapes` (from `transforms_common`) |
| `test_chat_transform_chat_to_anthropic.py` | json, os, unittest.mock, uuid | `_require_server_func`, `fail`, `pass_`, `run_cli` | `MAX_JSON_NESTING_DEPTH` (from `nesting`) |
| `test_chat_transform_images.py` | uuid | `_require_server_func`, `_trace_events_for_request`, `fail`, `pass_`, `run_cli` | — |

The sets are derived mechanically from member bodies at HEAD by a scope-aware free-name scan (Load-context `Name` nodes and attribute roots, minus locally bound names — params of any nested def or lambda, Store targets, local import asnames, except aliases), intersected with the stdlib, `_harness`, and package candidate universes; the gate re-derives the same sets from the working-tree member bodies and asserts exact equality with this table, and additionally asserts that no member references a member housed in another file (`_OMIT` affinity, gate-checked). Known scan caveat, stated where the guarantee is claimed: the subtraction is a flat per-member scope set — nested-scope shadowing is not modeled — adequate for this source (no shadowed free names exist) and proven by the GREEN derivation-equality pass. Headline derivations worth stating: `json`, `os`, and `unittest.mock` are used by **only** the chat_to_anthropic members (`malformed_tool_args_text_block` L2254/2265, `nesting_limit_tool_args` L2324–2336, `nesting_guard_total` L2384 — the sole `unittest.mock` site in the file), and `MAX_JSON_NESTING_DEPTH` by only `nesting_limit_tool_args` L2298; the kept and images files import none of them. A member-derived name the tester finds genuinely unused after a real edit is a stop-and-report, never a silent import drop. The four intra-test imports in the kept file are pinned as ordered (tools, patterns, chat_to_anthropic, images).

### Catalog sync (planner lane, Step 2)

`doc/test-catalog.html`:

1. **Category 4** (`<h3 id="cat-4">Category 4 — Chat Completions Transforms</h3>`, current h4 at L474): the current single section anchors on `<h4><code>tests/test_chat_transform.py</code> — Anthropic → Chat request and response transforms</h4>` and holds all 60 `<li>` entries. Replace it with five `<h4>` sections in this order, each with a descriptive prose suffix (the per-section pair counts below are plan-side annotations, never written into the catalog): `tests/test_chat_transform.py` — Anthropic → Chat request messages (17 `<li>`); `tests/test_chat_transform_tools.py` — tools, tool_choice, and request traces (17); `tests/test_chat_transform_patterns.py` — pattern sanitization (8); `tests/test_chat_transform_chat_to_anthropic.py` — Chat → Anthropic response conversion (14); `tests/test_chat_transform_images.py` — image content blocks (4). Per-section `<li>` order is the module's def order (Move Inventory order) — a deliberate reorder from the current catalog's historical order; entries move **byte-identical** (including the two entries whose `<code>` cell carries the slug form `chat-to-anthropic-nesting-limit-tool-args` / `chat-to-anthropic-nesting-guard-total` instead of the test-name form — a pre-existing catalog inconsistency acknowledged here, deliberately not fixed inside a verbatim move).
2. **Module-map table**: replace the `<tr><td><code>test_chat_transform.py</code></td>
    <td>Anthropic → Chat Completions request and response transforms</td></tr>` row (L166–167) with five rows in the same order — kept: "Anthropic → Chat request message conversion (kept module; chains the four sub-module `<code>ALL_TESTS</code>` lists)" (the chaining annotation mirroring the `test_compat.py` kept row's form); tools: "Tools array, tool_choice mapping, request traces, tool-argument edge cases"; patterns: "The shared pattern-sanitization helpers — unit tests plus the chat-mode confirmation"; chat_to_anthropic: "Chat → Anthropic response conversion, tool-args degradation, nesting guards"; images: "Image content blocks, both directions". Row emission form is pinned (the form the module map already uses and the green-sim generator emits): each row is `<tr><td><code>FILE</code></td>` + newline + four spaces + `<td>DESC</td></tr>`, DESC on one physical line; each filename cell occurs exactly once in the table. Table cells carry bare filenames; the `tests/` prefix stays on the Category 4 `<h4>` headings.

Then: full gate exits 0; `python scripts/check_doc_anchors.py` exits 0. Do not refresh any other counts. No helper-doc row references this module (checked — unlike `_drain_child_stderr`, no catalog row carries chat-transform counts). The catalog's `BEGIN per-test inventory` provenance marker (L277) is left unchanged, matching the chat-sse and retry-streaming partitions' precedent.

### Rollback

`git restore --source=HEAD --staged --worktree tests/test_chat_transform.py` (Step 1's tracked file) and — once Step 2 has touched it — `git restore --source=HEAD --staged --worktree doc/test-catalog.html`; **precondition:** each tracked file's only uncommitted changes are this plan's edits. The four new test files are untracked and are **left in place** by rollback — inert for the aggregator (unused by the restored kept file) and untracked. Their eventual removal is the user's, never a scripted `rm` (file-deletion doctrine). The gate script and green-sim generator under `tmp/verification/` and the generated tree at `tmp/green-sim-chat/` are untracked verification artifacts and survive by design. The gate is a pre-change-HEAD tool: after the Step 10 commit a re-run aborts at its HEAD-calibration check (the committed HEAD no longer carries the 61-member source) — expected post-commit behavior, not a fault.

### Byte-identity sources

Every moved def/const segment is byte-identical to `HEAD:tests/test_chat_transform.py`'s same-named segment (name-keyed sha256; `_OMIT` compared as its `Assign` statement source). Riding comment blocks (2) are gate-checked positionally adjacent above their member in the source's block/blank/def geometry and text-identical to HEAD's block, each conserved exactly once across the partition. New-file-only text (docstrings, import blocks, footers, `ALL_TESTS` restructures) is pinned above, not sha-pinned. The kept file's 18 moved members are sha-identical to their HEAD segments; its 19th member, `ALL_TESTS`, is the pinned restructure.

## Tests to investigate for retirement

None — members move, no test's coverage changes.

## Summary

**Problem.** `tests/test_chat_transform.py` is the suite's largest module (2,827 lines, 60 tests) — the next over-threshold target of the /refactor-split test-partition campaign after the retry-streaming partition closed the previous largest. Its docstring names the mixed directions ("Anthropic-to-Chat request conversion and Chat-to-Anthropic response conversion"); the pattern-sanitization cluster unit-tests `transforms_common` helpers inside a chat-mode file; the image-block cluster spans both directions. One module const (`_OMIT`) and 2 riding comment blocks ride inside one file.

**Approach.** Partition into a kept request-messages file + four feature-area files, following the retry-streaming partition's mechanics (byte-verbatim member moves, name-keyed sha256 gates, catalog re-section) and its chained-ALL_TESTS registration (aggregator byte-identical; the kept file imports its siblings' lists — the catalog-documented pattern since 2026-11-26, so no Document Override). The const is single-consumer and moves with its reader (gate-checked); both riding comment blocks move with their members.

**Key decisions** (user-approved grouping, 2026-11-28).
- Kept file: the messages pipeline — the request direction's core, including the reasoning-selection matrix (`emits_only_selected_field` + `_OMIT`) and the trace-count contract.
- tools sibling: the tools-array conversion, `tool_choice` mapping, and the request e2e/trace cluster — 7 of those 8 tests are tool-argument behavior — plus `zero_arg_tool` (a request-direction tool test despite its odd `test_chat_` prefix).
- patterns sibling: the `transforms_common` sanitizers' unit tests plus their chat-mode e2e confirmation (`tools_pattern_sanitized`) — one feature, `doc/provider-modes.html#pattern-normalization`.
- chat_to_anthropic sibling: the response direction; `json`, `os`, `unittest.mock`, and `MAX_JSON_NESTING_DEPTH` are used only here and move wholesale.
- images sibling: the image-block feature across both directions — `image_parts_filtered` rides here on feature affinity (same doc anchor) over direction affinity.
- The source `ALL_TESTS` order interleaves the clusters — the global execution order deliberately becomes kept-then-siblings; the gate pins each file's pairs as exact subsequences plus slug-set equality, never the interleaved source order.

**Baseline (measured 2026-11-28 at HEAD `eb6b3d0`, pre-change tree):** full suite **555 passed / 0 failed / 555 total**, exit 0 (log at `tmp/verification/baseline-suite-chat-transform.log`; the retry-streaming partition's committed count reproduced). The corpus holds this plan's two planner scripts — the gate and the green-sim generator, both carrying the canonical spawn-isolation block, census "2 spawners, 0 fail" — so the corpus hook passes; it reverts to failing-by-design after the post-commit sweep until the next plan seeds it (the workflow consequence already documented in the retry-streaming plan's Baseline, dispositioned separately, not here).

**Out of scope:** the remaining over-threshold test modules (`test_cli.py` 2,572, `test_tier_routing.py` 2,087, `_harness.py` 2,045, `test_trace.py` 1,744, `test_mode_dispatch.py` 1,612) — each its own plan; the corpus-hook vacuity contract; any harness refactor; forwarder.py's terminal-state decision (separate track, user-selected sequencing).

## Repo Mode

Public

## Document Overrides

| Document | Rule Overridden | Reason |
|----------|----------------|--------|

## Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| A moved member misses a dependency in its new file | `NameError` at import, suite red | Derived-import tables are gate-pinned exact per file; full suite + standalone `--list` verifies are the gate; cross-destination references verified NONE at HEAD |
| Separator/banner drift makes the move non-verbatim | Gate byte-checks fail, red round | 2-blank separators pinned; the 2 riding blocks gate-checked adjacent + text-identical; per-member sha256 vs HEAD |
| ALL_TESTS concatenation breaks count or slugs | Suite count/slug drift | Gate asserts per-file exact pairs vs HEAD-filtered subsequences, total 60, slug-set equality; aggregator untouched |
| Catalog sync drops, duplicates, or reorders an `<li>` | Doc/test catalog desync | 1:1 distribution pinned (17/17/8/14/4) in def order; gate asserts per-section name sequences + module-map rows; `check_doc_anchors.py` in Step 2 |
| Post-sweep corpus-hook failure mistaken for a plan regression | False alarm in a later session | Baseline section documents the designed vacuity behavior and its during-plan vs post-sweep state; carried from the retry-streaming plan |

## Proposed Changes

1. **Step 1 (tester): Partition** — the five-file edit exactly as pinned above.
   → tester verify (scripted): `python3 ./tmp/verification/2026-11-28-partition-chat-transform-gate.py --tests` exits 0 (test-file checks; catalog checks are Step-2-gated).
   → tester verify: `python tests/test_claude_proxy.py` exits 0.
   → tester verify: standalone `--list` per new module (17/8/14/4, pinned slugs); kept `--list` 60; one single-test run per new module, each PASSED.
   → tester verify: `python scripts/check_spawn_isolation.py` PASS.
2. **Step 2 (planner): Catalog sync** — `doc/test-catalog.html` per the Catalog sync section, then the full gate exits 0 and `check_doc_anchors.py` exits 0.

## Guidance for Planner

- **Files to modify (What to sync):** `doc/test-catalog.html` — the Catalog sync section above is the spec (planner lane; both precedent partitions assigned the catalog to the planner in a dedicated step). CLAUDE.md's `tests/` line stays true; no other doc names the chat-transform test modules.
- **`doc/architecture.html`, `doc/provider-modes.html`, `README.md`:** reviewed — none names test modules; no update needed.
- **`.claude/mega-audit-files.json`:** no declared audit locations exist in this repo.
- **Gate authoring:** `./tmp/verification/2026-11-28-partition-chat-transform-gate.py` — RED-calibrated against the pre-change tree (every FAIL an exact not-yet-done condition), spawn-isolation-compliant (canonical mkdtemp + three-assignment block + atexit cleanup before its subprocess spawns; the checker classifies both planner scripts as compliant spawners, census "2 spawners, 0 fail"), carries `--tests` phase gating catalog checks to the full run, BinOp left-spine descent + synthetic-shape selfcheck for the restructured kept `ALL_TESTS` (aborts, not fails — RED cannot exercise that shape), plain-List shape checks on sibling `ALL_TESTS`, AST `__main__`-guard footer checks (guard presence + exact pinned call — a bare top-level `run_cli` would execute a sibling's list at aggregator import time), scope-aware import re-derivation, `_OMIT`-affinity check, guarded working-tree reads, riding-block handling with per-block geometry (decorator-aware member lines), a visible Phase-C wholesale-skip note when any destination file is unparsable, and HEAD-parse guarding routed to the exit-2 calibration abort. GREEN state proven by `./tmp/verification/2026-11-28-partition-chat-transform-green-sim.py` — itself carrying the same canonical block — which mechanically generates the pinned post-partition tree (five test files + HEAD's aggregator and `_harness` + the synced catalog) into a staging directory renamed atomically to `tmp/green-sim-chat/` (outside the spawn-isolation corpus — the checker's default root and the corpus hook's `--path` are `tmp/verification` only) and stamps a completion marker the gate's `--root` mode requires before trusting the tree; the full gate exits 0 there and the sim kept/sibling modules `--list` live.
- **Pre-implementation mega-audit:** ≥5 test files change — the compat and retry-streaming precedents run the mega-audit before implementation; schedule it after gate calibration, before the tester round.
- **When:** Step 2 runs after Step 1's green verifies, before `/update-and-commit`.

## Cross-References to Prior Plans

| Prior Plan | Deferred Issue | Resolution |
|------------|----------------|------------|
| 2026-11-27-partition-retry-streaming | — | Mechanics, chained registration, gate disciplines, green-sim location (outside the corpus), and the single-line `_harness` import precedent adopted wholesale |
| 2026-11-26-partition-test-compat | — | Chained-ALL_TESTS origin; the catalog §Adding-a-test step-3 wording already describes the chained pattern |
| 2026-11-26-partition-chat-sse | — | Feature-area shape precedent (this file's SSE-side sibling cluster was partitioned there) |

## History

| Date | Event | Conclusion | Dismissed |
|------|-------|------------|-----------|
| 2026-11-28 | Initial plan | Survey at `eb6b3d0`: 2,827 lines, 60 tests, no helper functions, one const (`_OMIT`, sole consumer `test_chat_transform_emits_only_selected_field`), 60-pair plain-List `ALL_TESTS` with interleaved cluster order, 2 riding comment blocks (the `_OMIT` sentinel line; the `# --- Step 5: _chat_to_anthropic ---` section banner). User approved the 5-file grouping with four judgment calls (zero-arg-tool → tools; image_parts_filtered → images on feature affinity; tools_pattern_sanitized → patterns as the e2e confirmation; the request e2e/trace cluster rides tools). Mechanical derivation: zero cross-destination references; `json`/`os`/`unittest.mock`/`MAX_JSON_NESTING_DEPTH` used only by chat_to_anthropic members; per-file import tables derived scope-aware. Catalog region mapped: one h4 (`cat-4`) with all 60 `<li>`, one module-map row (L166–167), no helper-doc row | 6-file variant (separate request-traces sibling) — user chose 5 files; catalog's two slug-form `<code>` cells on the nesting entries — pre-existing inconsistency, moved byte-identical, fix out of lane |
| 2026-11-28 | Gate authored + RED-calibrated + GREEN proven (`./tmp/verification/2026-11-28-partition-chat-transform-gate.py`, `…-green-sim.py`, planner lane) | RED: `--tests` 13 PASS / 4 FAIL, full 18 PASS / 11 FAIL (the 7 extra are the Step-2-gated catalog checks) — every FAIL an exact not-yet-done condition (four sibling files absent / catalog unsynced); all HEAD preconditions PASS. GREEN: the sim generator built the pinned tree under `tmp/green-sim-chat/` (outside the spawn-isolation corpus); full gate **79/79 exit 0** there; sim modules `--list` live (kept 60 = 17 own + 43 chained resolving through the four sibling imports; tools 17 / patterns 8 / chat_to_anthropic 14 / images 4). Calibration caught and fixed four real gate defects: (1) REPO_ROOT derived one dirname short from `tmp/verification/` (resolved to `tmp/`) — replaced with `git rev-parse --show-toplevel` + three-dirname fallback; (2) riding-geometry slice off by one AND the two blocks' geometries differ — the `_OMIT` sentinel is directly adjacent (L427/L428, no blank) while the Step-5 banner carries one blank (L1879/L1880/L1881); RIDING_BLOCKS now pin per-block `blanks_between` (0 and 1) and the plan's Step 1 corrected to the same per-block pinning; (3) the BinOp alias spine descends root-first (Python left-associativity) — aliases reversed to source order, selfcheck expectation updated, synthetic BinOp selfcheck (exit 2) retained; (4) the last-import→first-member seam check was not riding-aware — the Step-5 banner sits in the first member's block (sim caught it); the seam now expects `[2 blanks] + block + [block blanks]` for a riding first member. Generator caught and fixed: kept's slug/test-member zip misaligned on `_OMIT` (slug count guard added), a `tests/` double-prefix on the catalog section lookup | — |
| 2026-11-28 | Mega-audit iteration 1 (pre-implementation, run `wf_26753ea2-e18`, 9 lenses; 24 findings: 3 High / 3 Medium / 18 Low, verdict needs-revision; report at `./tmp/reports/2026-11-28-partition-chat-transform-mega-audit-2026-11-28.json`; ≥3 High → iteration 2 scheduled) | The 3 Highs are one root seen by three lenses (conflict-resolver, edge-case-explorer, test-impact): both planner scripts' isolation blocks named the compat override `"compat.json"` instead of the canonical `"feature-compat.json"`, failing the spawn-isolation checker. Fixed: filename corrected in gate + generator and the canonical block completed with the documented atexit cleanup; verified live — `check_spawn_isolation.py` "2 spawners, 0 fail, 0 exempt, 0 skip" PASS, gate GREEN re-proven **81/81 exit 0** on the regenerated sim, RED reproduced (13/4 `--tests`, 19/11 full — +1 check), sim `--list` 60/17/8/14/4 live. Mediums fixed: (1) the generator's `REPO_ROOT` was an unguarded `git rev-parse` (raw traceback on git loss; empty root → `OUT` CWD-relative and a recursive `rmtree` at an arbitrary path) — the gate's guarded `_repo_root()` ported, plus sanity asserts before any write (REPO_ROOT is the checkout with `tests/`; OUT under REPO_ROOT via `commonpath`); (2) the gate's catalog working-tree read was the one unguarded read (TOCTOU/decode errors died as a bare exit-1 traceback) — wrapped, with an explicit `D.working-catalog-readable` FAIL; (3) the Baseline/Step-1 census reworded to the truthful two in-corpus spawners. Lows fixed beyond severity: c2a member-lines 473 → **512** (annotation arithmetic; spans verified correct, nothing consumes the total); the "no function-local imports exist at HEAD" claim corrected — eight `import copy` sites verified and pinned in the Derived Imports note; the ALL_TESTS interleaving parenthetical corrected (nesting pairs sit inside the chat_to_anthropic run between the malformed-args pairs; zero-arg + images last); module-map check hardened to the exact emitted five-row block with per-filename once-counts and the row emission form pinned in Catalog sync; the generator's old cat-4 span now shape-asserted and the mapped `<li>` names asserted equal to the FILE_MEMBERS test-name union; the sim tree builds into a staging directory renamed atomically with a completion marker the gate's `--root` mode requires; the aggregator-level targeted run (`-t chat-zero-arg-tool`) added to Step 1; the Gate-authoring bullet states the generator's canonical block; calibration/aggregator/derive git reads widened to `subprocess.SubprocessError` and `read_parsed` catches decode errors; the planner-lane doc line moved out of the tester block; the catalog provenance-marker statement added. Acknowledged, no fix: the security lens's forward-looking harness note (keep the `_harness`-first import order pinned at the next harness refactor — advisory, out of this plan's lane); 39 coverage gaps are residual lens-scope limits (per-lens `areas_not_fully_verified`), as in the precedent partitions | — |
| 2026-11-28 | Mega-audit iteration 2 (pre-implementation, run `wf_5730d09d-0fd`, 9 lenses; 13 findings: 0 High / 1 Medium / 12 Low, verdict **non-blocking** — 0 High exits the iteration loop at 2 of the 4-cap; report at `./tmp/reports/2026-11-28-partition-chat-transform-mega-audit-2026-11-28-r2.json`) | The Medium fixed and negative-tested: the gate never verified the `__main__` guard's presence — `footer_label_of` text-matches a bare top-level `run_cli` too, and the separator seam check silently skipped when the guard was absent, so a bare-call footer would execute a sibling's test list at aggregator import time while passing both checks. Added `C.footer-guard-<file>` (AST: the `If` present, body the single pinned `run_cli` call) and made the seam check FAIL instead of skip — which exposed a latent dead check: the guard detector matched `ast.Name` but the real test is `ast.Compare` (`__name__ == "main"`), so `footer_line` had been None since the first calibration and the ALL_TESTS→footer seam never ran; both detectors fixed, GREEN re-proven **86/86**, RED 13/5 `--tests` / 19/12 full, and the mutation test confirms the teeth (bare `run_cli` → 84/2 with both FAILs; regenerated → 86/86). Lows fixed: staging build wrapped with on-failure rmtree + the `staging-*` glob added to `retire_inventory` + `tmp/` makedirs + `commonpath` ValueError guard; `git_show` decodes `errors="replace"` in both scripts and the derive/catalog guards widened; the generator's gate-module import wrapped with an explicit abort message; the §Adding-a-test step-5 live-proxy clause closed by stating the harness-isolation makes it moot; Step 1's opening reworded to the 43-move/18-stay split; the single-line `_harness` attribution corrected to retry-streaming only (compat modules use multi-line imports; only chained registration cites compat); the scope-scan flat-subtraction caveat stated where the guarantee is claimed; `--root` comparison normalized via `realpath`; member lines decorator-aware; a visible `C.phase-c-block-skipped` FAIL emitted when the wholesale guard trips. Acknowledged, no fix: per-file Phase-C gating (visible-skip note preserves the evidence; exit correctness unaffected) | — |
| 2026-11-28 | Baseline measured + tester round 1 (Step 1 Partition; report at `./tmp/reports/2026-11-28-partition-chat-transform-tester-2026-11-28.json`) | Baseline run first-hand at HEAD `eb6b3d0` pre-change: **555 passed / 0 failed / 555 total**, exit 0 (log `tmp/verification/baseline-suite-chat-transform.log`, pinned in Baseline + `retire_inventory`). Tester round SUCCESS — implementation route: the tester regenerated the planner's green-sim reference tree (full gate on the regenerated sim **86/0**), reproduced the RED calibration pre-change (`--tests` 13/5), delivered the five test files from the sim, then verified on the real tree: gate `--tests` **72/0** exit 0 (86 checks minus the 14 Step-2-gated catalog checks), full suite **555/555** exit 0, standalone `--list` tools 17 / patterns 8 / chat_to_anthropic 14 / images 4 / kept 60, one single-test run per new module PASSED, aggregator-level targeted run PASSED, `check_spawn_isolation.py` PASS, aggregator byte-untouched. No test created, retired, or skipped | — |
| 2026-11-28 | Step 2: Catalog sync (planner lane) | `doc/test-catalog.html` synced: Category 4 re-sectioned into five `<h4>` sections in plan order (kept 17 / tools 17 / patterns 8 / chat_to_anthropic 14 / images 4 `<li>`, per-section def order, entries byte-identical incl. the two slug-form nesting entries and the ` (added …)` annotations), module-map row replaced by the five rows with the kept-row chaining annotation, provenance marker untouched. Verifies: full gate **85/85 exit 0** on the real tree, `check_doc_anchors.py` PASS (272 anchors resolved, no unresolved, no secret shapes), and the synced catalog is **byte-identical** to the green-sim reference (`diff` clean) | — |
| 2026-11-28 | Phase 6 implementation review (report at `./tmp/reports/2026-11-28-partition-chat-transform-review-2026-11-28.json`) | Verdict **COMMIT READY — 0 Critical / 0 Warning / 0 Suggestion**, 17 verifications, no findings. The reviewer independently re-derived beyond the gate (own AST scripts): all 61 moved members sha256-identical to HEAD (name-keyed, not a sample) and each present exactly once; both riding blocks conserved at their per-block geometry (0-blank sentinel, 1-blank banner); chained ALL_TESTS resolves to 60/60 unique in kept-then-siblings order with per-name slug mapping equal to HEAD; aggregator byte-identical with the 60 slugs contiguous (indices 221–280); imports match the pinned tables with zero cross-file references; all five docstrings and `ast.Compare` `__main__` guards exact; 2-blank geometry clean, no trailing whitespace; catalog hunks confined to the module-map block + cat-4 with the 60-entry multiset byte-identical to HEAD and the two pre-existing slug-form nesting entries preserved; no stale references in doc/, README.md, CLAUDE.md; full suite 555/555; both checkers PASS; the five test files and the catalog byte-identical to the green-sim reference | Reviewer hunches none; areas not re-verified stated in the report (the 85-check gate's substance re-derived independently rather than re-run; per-module single-test smokes covered by the suite; post-commit gate-abort behavior is expected calibration loss, not exercised) |

## Plan Metadata

```json
{
  "plan_id": "2026-11-28-partition-chat-transform",
  "steps": [
    "Step 1: Partition",
    "Step 2: Catalog sync"
  ],
  "coder_files": [],
  "tester_files": [
    "tests/test_chat_transform.py",
    "tests/test_chat_transform_tools.py",
    "tests/test_chat_transform_patterns.py",
    "tests/test_chat_transform_chat_to_anthropic.py",
    "tests/test_chat_transform_images.py"
  ],
  "doc_files": [
    "doc/test-catalog.html"
  ],
  "verification_scripts": [
    "./tmp/verification/2026-11-28-partition-chat-transform-gate.py",
    "./tmp/verification/2026-11-28-partition-chat-transform-green-sim.py"
  ],
  "retire_inventory": [
    "./tmp/verification/2026-11-28-partition-chat-transform-gate.py",
    "./tmp/verification/2026-11-28-partition-chat-transform-green-sim.py",
    "./tmp/green-sim-chat/",
    "./tmp/green-sim-chat.staging-*/",
    "./tmp/verification/baseline-suite-chat-transform.log",
    "./tmp/verification/__pycache__/",
    "./tmp/reports/2026-11-28-partition-chat-transform-mega-audit-2026-11-28.json",
    "./tmp/reports/2026-11-28-partition-chat-transform-mega-audit-2026-11-28-r2.json",
    "./tmp/reports/2026-11-28-partition-chat-transform-tester-2026-11-28.json",
    "./tmp/reports/2026-11-28-partition-chat-transform-review-2026-11-28.json"
  ],
  "repo_mode": "Public",
  "document_overrides": []
}
```

## Audit Accumulation

| Counter | Value | Last Updated |
|---------|-------|--------------|
| issues_resolved_since_audit | 0 | 2026-11-28 |
| steps_changed_since_audit | 0 | 2026-11-28 |
| files_changed_since_audit | 0 | 2026-11-28 |

## Documentation

- `doc/test-catalog.html` Category 4 re-sections in Step 2, planner lane (five file sections, 1:1 `<li>` distribution in def order, byte-identical descriptions, five module-map rows). No other doc names chat-transform test modules; CLAUDE.md's `tests/` line stays true; README does not enumerate test modules.

## Final Results

**Completed 2026-11-28 — status COMPLETED.**

**Files changed:**
- `tests/test_chat_transform.py` — kept module: 19 members (18 sha-verbatim + the restructured chained `ALL_TESTS`)
- `tests/test_chat_transform_tools.py` — new, 17 members
- `tests/test_chat_transform_patterns.py` — new, 8 members
- `tests/test_chat_transform_chat_to_anthropic.py` — new, 14 members
- `tests/test_chat_transform_images.py` — new, 4 members
- `doc/test-catalog.html` — Step 2 catalog sync (Category 4 re-sectioned into five `<h4>` sections in def order, five module-map rows with the kept-row chaining annotation); byte-identical to the green-sim reference
- `tests/test_claude_proxy.py` — untouched, byte-identical to HEAD

**Test results:** baseline at HEAD **555/0/555**, full suite after Step 1 **555/555 passed** (count unchanged); gate `--tests` **72/0** on the real tree, full gate **85/85**, exit 0; standalone `--list` 17/8/14/4 + kept 60; one single-test run per new module PASSED; aggregator-level targeted run PASSED; `scripts/check_spawn_isolation.py` PASS ("2 spawners, 0 fail"); `scripts/check_doc_anchors.py` PASS (272 anchors). Every moved member independently verified sha256-identical to HEAD (gate, name-keyed).

**Issues resolved:** none — the plan adopted no deferrals and filed none; the Issue Log stayed empty through two audit iterations and one tester round.

**Deferred issues:** none.

**Review:** Phase 6 **COMMIT READY** — 0 Critical / 0 Warning / 0 Suggestion, 17 verifications (report at `./tmp/reports/2026-11-28-partition-chat-transform-review-2026-11-28.json`); all 61 members independently sha-verified, chained ALL_TESTS resolves 60/60, catalog hunks confined to the pinned regions, suite 555/555.

**Mega-audit:** 2 iterations, converged (r1 3 High / 3 Medium / 18 Low → all fixed; r2 0 High / 1 Medium / 12 Low, non-blocking); reports at `./tmp/reports/2026-11-28-partition-chat-transform-mega-audit-2026-11-28.json` and `…-r2.json`.
