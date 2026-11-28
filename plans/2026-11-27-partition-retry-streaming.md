# Plan: Partition tests/test_retry_streaming.py into feature-area test files

**Plan ID:** 2026-11-27-partition-retry-streaming
**Created:** 2026-11-27

## Issue Log

| Issue | Status | Found | Resolved | Resolved By |
|-------|--------|-------|----------|-------------|

## Guidance for Coder

None. Test-file changes are tester-lane exclusively; no coder steps.

## Guidance for Tester

**Tests to create:** none — this plan moves tests and helpers byte-verbatim; no test's behavior changes.

**Verification scripts to create:** none by the tester — the planner-authored gate at `./tmp/verification/2026-11-27-partition-retry-streaming-gate.py` is the scripted check; reference any behavioral script you add in the session report.

**Files to modify (tester lane):**
- `tests/test_retry_streaming.py` (kept: header rewritten, 10 tests + 1 helper remain)
- `tests/test_retry_streaming_count_tokens.py` (new: 6 members)
- `tests/test_retry_streaming_flow.py` (new: 5 members)
- `tests/test_retry_streaming_concurrency.py` (new: 4 members)
- `tests/test_retry_streaming_disconnects.py` (new: 6 members — 3 tests + 3 helpers)
- `tests/test_retry_streaming_transport.py` (new: 4 members)

**Files to modify (planner lane, Step 2):** `doc/test-catalog.html` (Catalog sync)

**Step-by-step with verification:**

1. **Step 1 (tester): Partition.** Move the 36 pinned members byte-verbatim per the Move Inventory below (32 tests + 4 helpers; `ALL_TESTS` is restructured per its own section) — each member is exactly `ast.get_source_segment(HEAD:tests/test_retry_streaming.py, member)`. Every riding comment block moves **with the member it precedes** in the source's own geometry — the block lines, then one blank line, then the def/class line (the gate pins block adjacency at that exact offset, preserving the byte-verbatim form). There are 13 riding blocks: 11 three-line `# ====` banners (all single-test-scoped, carrying per-test historical labels — unlike test_compat.py's multi-test section banners, which that partition deleted) plus 2 provenance comments pinned in the Move Inventory (a 2-line `# --- extra_request_headers retry stability ---` block above `test_retry_stability_extra_header`, kept; a 1-line `# --- Sink guard: retry-loop misclassification (plan 2026-09-10-guard-trace-state-sinks) ---` above `_oversized_json_responder`, disconnects). Member order within each destination file preserves the source def order (the Move Inventory order). Separators: exactly **2 blank lines between top-level members in every destination file** (uniform convention; a riding block sits inside its member's block, block lines counted as content). The 2-blank rule also pins three seams the source heterogeneity would not predict — last-import→first-member, last-member→`ALL_TESTS`, and `ALL_TESTS`→footer (only intra-import seams are unpinned; the green-sim generator's emitted form is the reference geometry). Build each file's import block from its pinned Derived Imports table below (stdlib sorted as in source, single `_harness` block). Each new test module ends with its own `ALL_TESTS` list (exactly its pinned pairs, same `("slug", name)` form, with the pinned riding section comments where listed) and the pinned `__main__` footer. The kept file's `ALL_TESTS` becomes its own 10 pairs followed by `+ COUNT_TOKENS_TESTS + FLOW_TESTS + CONCURRENCY_TESTS + DISCONNECTS_TESTS + TRANSPORT_TESTS` from five new pinned intra-test imports (see ALL_TESTS restructure). **The aggregator `tests/test_claude_proxy.py` is untouched byte-for-byte** (chained registration, the catalog-documented `tests/test_compat.py` pattern). A drifted or zero-length source range on re-verification is a stop-and-report.
   → tester verify (scripted): `python3 ./tmp/verification/2026-11-27-partition-retry-streaming-gate.py --tests` exits 0 (the test-file checks; the catalog checks are Step-2-gated and excluded here).
   → tester verify: `python tests/test_claude_proxy.py` exits 0 (full suite green — during-plan the corpus is populated by the gate script, so the spawn-isolation corpus hook passes; see Baseline).
   → tester verify: each new module standalone: `python tests/test_retry_streaming_count_tokens.py --list` (6 slugs), `…_flow.py --list` (5), `…_concurrency.py --list` (4), `…_disconnects.py --list` (3), `…_transport.py --list` (4); plus one single-test run per new module proving the standalone import path, each PASSED: `python tests/test_retry_streaming_count_tokens.py -t disable-retry-count-tokens-invalid-type`, `python tests/test_retry_streaming_flow.py -t response-mode-swap-aborts-sse-fallback`, `python tests/test_retry_streaming_concurrency.py -t proxy-listen-backlog`, `python tests/test_retry_streaming_disconnects.py -t trace-write-failure-does-not-duplicate-upstream-request`, `python tests/test_retry_streaming_transport.py -t upstream-accept-encoding-identity`.
   → tester verify: `python tests/test_retry_streaming.py --list` — 32 slugs (10 own + 22 concatenated), the concatenated order the pinned kept-then-siblings sequence.
   → tester verify: `python tests/test_claude_proxy.py --list` — the aggregator-level registration proof the catalog's §Adding-a-test step 3 demands: the full list runs and the 32 retry-streaming slugs appear contiguously at the `RETRY_STREAMING_TESTS` position.
   → tester verify: `python scripts/check_spawn_isolation.py` PASS (precondition: the stale iteration-1 sim residue `tmp/verification/green-sim/` has been removed by the user hand-off — see Baseline).

2. **Step 2 (planner): Catalog sync.** Re-section `doc/test-catalog.html` per Guidance for Planner → What to sync (Category 2 six sections, module-map rows, the `_drain_child_stderr` count-free reword), then `python3 ./tmp/verification/2026-11-27-partition-retry-streaming-gate.py` exits 0 (the full gate — catalog checks pass only after this step) and `python scripts/check_doc_anchors.py` exits 0. No other doc changes: CLAUDE.md's `tests/` line ("per-area test modules + aggregator") stays true; the catalog's §Adding-a-test step 3 already documents the chained pattern (compat partition, 2026-11-26).

### Move Inventory

36 members (32 tests + 4 helpers, per HEAD's AST inventory); 25 leave the kept file (6+5+4+6+4 across the five new files); `ALL_TESTS` is restructured, not moved. Source line numbers are `HEAD:tests/test_retry_streaming.py` spans (`ast` top-level `FunctionDef` / single-`ClassDef`), re-verified before cutting. Riding comment blocks (13: the 11 `====` banners + 2 provenance comments) are listed per member; every top-level statement of the source file lands in exactly one destination.

**`tests/test_retry_streaming.py` (kept) — 12 members (11 byte-verbatim + `ALL_TESTS` restructured), 983 member-lines (the 11 byte-verbatim members' span sum; the restructured `ALL_TESTS` excluded):**

| Member | Kind | Source lines | Riding block |
|---|---|---|---|
| `test_retry_logic` | def | 186–310 | L182–184 `Test Case 5: Retry Logic` |
| `test_retry_429` | def | 319–462 | L315–317 `Test Case 5c: 429 Retry (3x 429 then 200)` |
| `test_retry_429_exhaust_returns_429` | def | 471–591 | L467–469 `Test Case 5d: 429 Exhaustion Returns 429` |
| `test_exhaust_429_preserves_body` | def | 876–1025 | — |
| `test_exhaust_connection_error_synthesizes_body` | def | 1034–1145 | L1030–1032 `Test Case 26: Exhaust Connection Error Synthesizes Body (Step 1 — Fix B, conn-error path)` |
| `test_empty_body_429_exhaust` | def | 1755–1857 | L1751–1753 `Test Case 31: Empty Body 429 Exhaust (plan 2026-08-12-streaming-proxy, Step 3 regression guard)` |
| `_truncating_429_responder` | def | 2094–2098 | — |
| `test_give_up_truncated_body_envelope` | def | 2101–2149 | — |
| `test_retry_stability_extra_header` | def | 2715–2795 | L2712–2713 (2 lines) `# --- extra_request_headers retry stability ---` / `# (plan 2026-09-06-opencode-session-header)` |
| `test_connection_error_retry_mapping` | def | 3231–3278 | — |
| `test_forward_failure_returns_envelope` | def | 3281–3325 | — |
| `ALL_TESTS` | const | 3556–3593 | (restructured, see below) |

**`tests/test_retry_streaming_count_tokens.py` (new) — 6 members, 638 member-lines:**

| Member | Kind | Source lines | Riding block |
|---|---|---|---|
| `test_disable_retry_count_tokens_503` | def | 1862–1970 | — |
| `test_disable_retry_count_tokens_conn_error` | def | 1975–2091 | — |
| `test_disable_retry_count_tokens_normal_path_unaffected` | def | 2154–2257 | — |
| `test_disable_retry_count_tokens_false_retries` | def | 2262–2366 | — |
| `test_disable_retry_count_tokens_path_anchoring` | def | 2371–2497 | — |
| `test_disable_retry_count_tokens_invalid_type` | def | 2502–2577 | — |

**`tests/test_retry_streaming_flow.py` (new) — 5 members, 637 member-lines:**

| Member | Kind | Source lines | Riding block |
|---|---|---|---|
| `test_streaming_response_body` | def | 1388–1540 | L1384–1386 `Test Case 29: Streaming Response Body (plan 2026-08-12-streaming-proxy, Step 1)` |
| `test_streaming_mid_stream_upstream_failure` | def | 1549–1746 | L1545–1547 `Test Case 30: Streaming Mid-Stream Upstream Failure (plan 2026-08-12-streaming-proxy, Step 1)` |
| `test_buffered_response_size_cap` | def | 2580–2709 | — |
| `test_response_mode_swap_aborts_sse_fallback` | def | 2972–3065 | — |
| `test_stream_read_timeout_bounds_stall` | def | 3167–3228 | — |

**`tests/test_retry_streaming_concurrency.py` (new) — 4 members, 413 member-lines:**

| Member | Kind | Source lines | Riding block |
|---|---|---|---|
| `test_concurrent_requests` | def | 51–177 | — |
| `test_thread_safety` | def | 600–759 | L596–598 `Test Case 9: Thread Safety` |
| `test_429_drain_bounded` | def | 3426–3525 | — |
| `test_proxy_listen_backlog` | def | 3528–3553 | — |

**`tests/test_retry_streaming_disconnects.py` (new) — 6 members, 388 member-lines:**

| Member | Kind | Source lines | Riding block |
|---|---|---|---|
| `test_client_disconnect_no_traceback` | def | 1154–1379 | L1150–1152 `Test Case 27: Client Disconnect No Traceback (Step 2 — Fix C)` |
| `_oversized_json_responder` | def | 2800–2817 | L2798 (1 line) `# --- Sink guard: retry-loop misclassification (plan 2026-09-10-guard-trace-state-sinks) ---` |
| `test_trace_write_failure_does_not_duplicate_upstream_request` | def | 2820–2862 | — |
| `_RaisingStderr` | class | 2865–2876 | — |
| `_responder_503` | def | 2879–2881 | — |
| `test_retry_path_print_failure_does_not_misclassify` | def | 2884–2969 | — |

Helper affinity is mechanically derived at HEAD and gate-checked: `_truncating_429_responder` → `test_give_up_truncated_body_envelope` (kept, L2117); `_oversized_json_responder` → `test_trace_write_failure_does_not_duplicate_upstream_request` (disconnects, L2838 — note: **not** the size-cap test, despite its name and file position); `_RaisingStderr` (L2939) and `_responder_503` (L2907) → `test_retry_path_print_failure_does_not_misclassify` (disconnects). Cross-destination member references: NONE (every helper single-consumer; no test calls another test).

**`tests/test_retry_streaming_transport.py` (new) — 4 members, 291 member-lines:**

| Member | Kind | Source lines | Riding block |
|---|---|---|---|
| `test_start_no_auth_header_required` | def | 768–871 | L764–766 `Test Case 23: Start No Auth Header Required` |
| `test_upstream_accept_encoding_identity` | def | 3072–3106 | L3068–3070 `httpx2 transport migration (plan 2026-11-15-httpx2-transport-sse)` |
| `test_upstream_cookie_isolation` | def | 3109–3164 | — |
| `test_ipv6_provider_url_routes` | def | 3328–3423 | — |

### ALL_TESTS restructure

Source `ALL_TESTS` (L3556–3593) is one list of 32 `("slug", name)` pairs in **chronological, not cluster-contiguous, order** (concurrency pairs interleave with retry pairs). No per-module concatenation can reproduce that interleaving, so the global execution order deliberately changes to kept-then-siblings; within each file the pairs preserve their source relative order. The gate asserts each file's pairs as a name-and-slug-exact subsequence of HEAD's list, the total at 32, and slug-set equality — never the source's global order.

- `tests/test_retry_streaming.py` (kept) — own 10 pairs, source order: `retry-logic`, `retry-429`, `retry-429-exhaust-returns-429`, `exhaust-429-preserves-body`, `exhaust-connection-error-synthesizes-body`, `empty-body-429-exhaust`, `give-up-truncated-body-envelope`, `retry-stability-extra-header`, `connection-error-retry-mapping`, `forward-failure-returns-envelope`; then `+ COUNT_TOKENS_TESTS + FLOW_TESTS + CONCURRENCY_TESTS + DISCONNECTS_TESTS + TRANSPORT_TESTS` from five new pinned intra-test imports placed after the `_harness` import block:
  ```python
  from test_retry_streaming_count_tokens import ALL_TESTS as COUNT_TOKENS_TESTS
  from test_retry_streaming_flow import ALL_TESTS as FLOW_TESTS
  from test_retry_streaming_concurrency import ALL_TESTS as CONCURRENCY_TESTS
  from test_retry_streaming_disconnects import ALL_TESTS as DISCONNECTS_TESTS
  from test_retry_streaming_transport import ALL_TESTS as TRANSPORT_TESTS
  ```
  (consecutive lines, the form the GREEN proof generates; the gate pins only the module/alias sequence, not blank separation between these five)
- `tests/test_retry_streaming_count_tokens.py` (6): `disable-retry-count-tokens-503`, `disable-retry-count-tokens-conn-error`, `disable-retry-count-tokens-normal-path-unaffected`, `disable-retry-count-tokens-false-retries`, `disable-retry-count-tokens-path-anchoring`, `disable-retry-count-tokens-invalid-type`.
- `tests/test_retry_streaming_flow.py` (5): `streaming-response-body`, `streaming-mid-stream-upstream-failure`, `buffered-response-size-cap`, then the riding comment `# Config-swap drain (plan 2026-10-12-swap-silence-drain)` above `response-mode-swap-aborts-sse-fallback`, then `stream-read-timeout-bounds-stall`.
- `tests/test_retry_streaming_concurrency.py` (4): `concurrent-requests`, `thread-safety`, `429-drain-bounded`, then the riding comment `# Listener accept backlog (plan 2026-11-19-drop-redacted-thinking-chat-placeholder)` above `proxy-listen-backlog`.
- `tests/test_retry_streaming_disconnects.py` (3): `client-disconnect-no-traceback`, `trace-write-failure-does-not-duplicate-upstream-request`, `retry-path-print-failure-does-not-misclassify`.
- `tests/test_retry_streaming_transport.py` (4): `start-no-auth-header-required`, then the riding comment `# httpx2 transport migration (plan 2026-11-15-httpx2-transport-sse)` above `upstream-accept-encoding-identity`, then `upstream-cookie-isolation`, then the riding comment `# Step 8 review-Warning fixes (same plan, revision 6)` above `ipv6-provider-url-routes`.
- Each new module keeps the `if __name__ == "__main__":` footer with its own slug: `run_cli(ALL_TESTS, "claude-retry-proxy tests: test_retry_streaming_count_tokens")` / `…_flow` / `…_concurrency` / `…_disconnects` / `…_transport`. Kept: `run_cli(ALL_TESTS, "claude-retry-proxy tests: test_retry_streaming")` unchanged.

### Pinned file docstrings

- `tests/test_retry_streaming.py` (replaces the source docstring):
  ```
  """Retry/backoff and 429/503 exhaustion tests: the retry loop, backoff
  pacing, exhaustion envelopes, give-up body preservation, and the
  connection-error retry mapping.

  The streaming/flow, concurrency, disconnect, count-tokens, and
  upstream-transport clusters live in their own modules
  (test_retry_streaming_flow, test_retry_streaming_concurrency,
  test_retry_streaming_disconnects, test_retry_streaming_count_tokens,
  test_retry_streaming_transport), chained through this module's ALL_TESTS
  (plan 2026-11-27-partition-retry-streaming).

  Part of the claude-retry-proxy suite; runnable standalone."""
  ```
- `tests/test_retry_streaming_count_tokens.py`:
  ```
  """count_tokens retry-flag tests: disable_retry_claude_count_tokens across
  503 and connection-error failures, path anchoring, type validation, the
  retry-on-false default, and the unaffected normal path."""
  ```
- `tests/test_retry_streaming_flow.py`:
  ```
  """Streaming and response-flow tests: streamed bodies, mid-stream upstream
  failure, buffered response-size caps, read-timeout stall bounding, and the
  response-mode swap-abort SSE fallback."""
  ```
- `tests/test_retry_streaming_concurrency.py`:
  ```
  """Concurrency and listener tests: concurrent request handling, retry-path
  thread safety, 429 drain bounding, and the listener accept backlog."""
  ```
- `tests/test_retry_streaming_disconnects.py`:
  ```
  """Disconnect and failure-classification tests: client disconnects without
  tracebacks, trace-write failure not duplicating the upstream request, and
  retry-path stderr writes not misclassified as connection errors."""
  ```
- `tests/test_retry_streaming_transport.py`:
  ```
  """Upstream transport tests: proxy entry without an auth header,
  Accept-Encoding identity, cookie isolation, and IPv6 provider URLs."""
  ```

### Derived Imports (gate-pinned, exact)

Per-file import blocks. Stdlib sorted as in source; one `_harness` block, names alphabetical with `PROXY_SERVER` first as in source. `run_cli` rides every footer-bearing module's `_harness` set (the pinned `__main__` footer calls it; the derivation is footer-aware). Function-local imports inside member bodies are body-verbatim and never appear here. **Delivered physical form (Phase 6 review, 2026-11-28):** every file's `_harness` import is a single-line unseparated statement (the green-sim generator's reference geometry; the gate pins subjects/order, not blank separation or line-wrapping) — a deliberate deviation from HEAD's blank-separated multi-line parenthesized convention, accepted per the compat partition's Phase 6 precedent (cosmetic; no file/gate churn).

| File | stdlib | `_harness` |
|---|---|---|
| `test_retry_streaming.py` (kept) | http, json, os, shutil, socket, subprocess, tempfile, threading, time | `PROXY_SERVER`, `_create_test_config`, `_create_test_keys`, `_drain_child_stderr`, `_mode_tiers`, `_send_proxy_request`, `_start_mode_proxy`, `_wait_for_trace_events`, `fail`, `find_free_port`, `info`, `pass_`, `run_cli`, `warn` + the five intra-test `ALL_TESTS` imports |
| `test_retry_streaming_count_tokens.py` | http, json, os, shutil, socket, subprocess, tempfile, threading, time | `PROXY_SERVER`, `_create_test_config_with_flag`, `_create_test_keys`, `_derive_models_from_tiers`, `_drain_child_stderr`, `_send_proxy_request`, `fail`, `find_free_port`, `pass_`, `run_cli` |
| `test_retry_streaming_flow.py` | http, json, os, shutil, socket, subprocess, tempfile, threading, time | `PROXY_SERVER`, `_admin_post`, `_create_test_config`, `_create_test_keys`, `_create_test_keys_plain`, `_drain_child_stderr`, `_mode_tiers`, `_read_child_stderr`, `_send_proxy_request`, `_send_proxy_request_stream`, `_start_mode_proxy`, `_start_proxy_server_directly`, `_trace_events_named`, `_wait_admin_swapping`, `_wait_for_trace_events`, `_wait_upstream_request`, `fail`, `find_free_port`, `pass_`, `run_cli` |
| `test_retry_streaming_concurrency.py` | http, json, os, shutil, socket, subprocess, tempfile, threading, time | `PROXY_SERVER`, `_create_test_config`, `_create_test_keys`, `_drain_child_stderr`, `_mode_tiers`, `_send_proxy_request`, `_start_mode_proxy`, `_wait_for_trace_events`, `fail`, `find_free_port`, `pass_`, `run_cli` |
| `test_retry_streaming_disconnects.py` | http, json, os, shutil, socket, subprocess, sys, tempfile, threading, time | `PROXY_SERVER`, `_create_test_config`, `_create_test_keys`, `_drain_child_stderr`, `_mode_tiers`, `_read_child_stderr`, `_send_proxy_request`, `_start_mode_mock_upstream`, `_start_mode_proxy`, `fail`, `find_free_port`, `pass_`, `run_cli` |
| `test_retry_streaming_transport.py` | http, json, os, shutil, socket, subprocess, sys, tempfile, threading, time | `PROXY_SERVER`, `_create_test_config`, `_create_test_keys`, `_create_test_keys_plain`, `_drain_child_stderr`, `_mode_tiers`, `_send_proxy_request`, `_spawn_proxy_with_bind_retry`, `_start_mode_proxy`, `fail`, `find_free_port`, `pass_`, `run_cli` |

The sets are derived mechanically from member bodies at HEAD by a scope-aware free-name scan (Load-context `Name` nodes and attribute roots, minus locally bound names — params of any nested def or lambda, Store targets, local import asnames, except aliases), intersected with the stdlib and `_harness` candidate universes; the gate re-derives the same sets from the working-tree member bodies and asserts exact equality with this table, and additionally asserts that no member references a member housed in another file (helper affinity, gate-checked). Two naive-scan ghosts are deliberately absent from the tables: `errors` in count_tokens and `info` in concurrency are local shadows (`errors = validate_config(...)`; a nested `def streamer(handler, info)` parameter), not `_harness` loads — the tester must not import them, and finding them "unused" is not a stop-and-report trigger. A member-derived name the tester finds genuinely unused after a real edit is a stop-and-report, never a silent import drop. The five intra-test imports in the kept file are pinned as ordered (count_tokens, flow, concurrency, disconnects, transport).

### Catalog sync (planner lane, Step 2)

`doc/test-catalog.html`:

1. **Category 2** (`<h4>` sections): the current single section anchors on `<h4><code>tests/test_retry_streaming.py</code> — retry, streaming, size caps</h4>` (L364, under `<h3 id="cat-2">Category 2 — Retry, Streaming, and Size Caps</h3>` at L360 — not Category 7, which is the compat area). Replace it with six `<h4>` sections in this order, each with a **descriptive, count-free prose suffix** (the per-section pair counts below are plan-side annotations, never written into the catalog): `tests/test_retry_streaming.py` — retry backoff and exhaustion envelopes (10 `<li>`); `tests/test_retry_streaming_count_tokens.py` — the count-tokens retry flag (6); `tests/test_retry_streaming_flow.py` — streaming and response flow (5); `tests/test_retry_streaming_concurrency.py` — concurrency and listener (4); `tests/test_retry_streaming_disconnects.py` — disconnects and stderr classification (3); `tests/test_retry_streaming_transport.py` — upstream transport (4). Per-section `<li>` order is the module's def order (Move Inventory order) — a deliberate reorder from the current catalog's historical order; entries move byte-identical.
2. **Module-map table**: split the `<tr><td><code>test_retry_streaming.py</code></td><td>Retry behaviour, streaming, response-size caps</td></tr>` row (L196–197) into six rows in the same order — kept: "Retry backoff, 429/503 exhaustion envelopes, give-up body preservation (kept module; chains the five sub-module `<code>ALL_TESTS</code>` lists)" (the chaining annotation mirroring the `test_compat.py` kept row's form); count_tokens: "The `disable_retry_claude_count_tokens` flag across failure paths, anchoring, and types"; flow: "Streaming bodies, mid-stream failure, response-size caps, stall bounds, swap-abort SSE fallback"; concurrency: "Concurrent requests, retry-path thread safety, 429 drain bounding, accept backlog"; disconnects: "Client disconnects, trace-write failure, stderr misclassification guards"; transport: "Entry auth, Accept-Encoding identity, cookie isolation, IPv6 URLs". Table cells carry bare filenames (`<td><code>test_retry_streaming_flow.py</code></td>`); the `tests/` prefix stays on the Category 2 `<h4>` headings.
3. **The `_drain_child_stderr` doc row** (module-map region; the row spans L1207–1208, its `<tr>` opening on the first line, the counts prose on the second) carries exact counts ("21 long-lived spawn sites … 17 in `test_retry_streaming.py`, 4 in `test_trace.py`") — reword count-free per the documentation no-exact-counts rule: the spawn sites are "spread across the retry-streaming test modules and `test_trace.py`". Never re-count.

Then: full gate exits 0; `python scripts/check_doc_anchors.py` exits 0. Do not refresh any other counts.

### Rollback

`git restore --source=HEAD --staged --worktree tests/test_retry_streaming.py` (Step 1's tracked file) and — once Step 2 has touched it — `git restore --source=HEAD --staged --worktree doc/test-catalog.html`; **precondition:** each tracked file's only uncommitted changes are this plan's edits. The five new test files are untracked and are **left in place** by rollback — inert for the aggregator (unused by the restored kept file) and untracked; note that corpus-external tooling (`check_spawn_isolation.py --path tests/`) would still classify them by the spawner standard, though the suite's corpus hook never scans `tests/`. Their eventual removal is the user's, never a scripted `rm` (file-deletion doctrine). The gate script and green-sim generator under `tmp/verification/` and the generated tree at `tmp/green-sim/` are untracked verification artifacts and survive by design; the stale iteration-1 residue at `tmp/verification/green-sim/` rides `retire_inventory` for the post-commit sweep (and is removed by the user hand-off before Step 1 — see Baseline). The gate is a pre-change-HEAD tool: after the Step 10 commit a re-run aborts at its HEAD-calibration check (the committed HEAD no longer carries the 36-member source) — expected post-commit behavior, not a fault.

### Byte-identity sources

Every moved def/const segment is byte-identical to `HEAD:tests/test_retry_streaming.py`'s same-named segment (name-keyed sha256; `_RaisingStderr` compared as its `ClassDef` statement source). Riding comment blocks are gate-checked positionally adjacent above their member in the source's block/blank/def geometry and text-identical to HEAD's block (13 blocks total; the gate conserves each full block exactly once across the partition — the httpx2 banner's label is byte-identical to its ALL_TESTS section comment, so bare-label counting would be unsatisfiable). New-file-only text (docstrings, import blocks, footers, `ALL_TESTS` restructures) is pinned above, not sha-pinned. The kept file's 11 moved members are sha-identical to their HEAD segments; its 12th member, `ALL_TESTS`, is the pinned restructure.

## Tests to investigate for retirement

None — members move, no test's coverage changes.

## Summary

**Problem.** `tests/test_retry_streaming.py` is the suite's largest module (3,597 lines, 32 tests) — the next over-threshold target of the /refactor-split test-partition campaign after the compat partition closed the previous largest. Its docstring names the mixed areas ("Retry/backoff, exhaustion, disconnect, streaming, thread-safety, concurrency, and count-tokens retry-flag tests"); four single-consumer helpers and 13 riding comment blocks (11 per-test banners + 2 provenance comments) ride inside one file.

**Approach.** Partition into a kept retry/exhaustion file + five feature-area files, following the compat partition's mechanics (byte-verbatim member moves, name-keyed sha256 gates, catalog re-section) and its chained-ALL_TESTS registration (aggregator byte-identical; the kept file imports its siblings' tuples — the catalog-documented pattern since 2026-11-26, so no Document Override). Single-consumer helpers move with their readers (scope-aware derivation, gate-checked); all 13 riding comment blocks move with their tests (the banners are per-test historical labels, unlike compat's deleted multi-test section markers; the 2 provenance comments are plan references preserved verbatim).

**Key decisions.**
- Cluster membership follows the docstring's own taxonomy plus the user-approved grouping: retry core + exhaustion envelopes stay; count-tokens flag, streaming/flow, concurrency, disconnects, and upstream transport become siblings.
- The source `ALL_TESTS` order is chronological, not cluster-contiguous — the global execution order deliberately becomes kept-then-siblings; the gate pins each file's pairs as exact subsequences plus slug-set equality, never the interleaved source order. Tests are independent — most spawn their own proxy on a free port; `test_proxy_listen_backlog` instead imports the server class and asserts `request_queue_size` directly — so execution order is not load-bearing.
- `buffered_response_size_cap` rides the flow file (response-size behavior, user-approved); `429_drain_bounded` rides concurrency (retry pacing under drain, user-approved).
- Spawn isolation: the corpus mechanics are root-scoped — `check_spawn_isolation.py`'s default root and the corpus hook's `--path` are `tmp/verification` only. Test modules in `tests/` satisfy the suite's isolation through the `_harness` import (the assignments live at `_harness.py`'s header) and are never corpus-scanned; artifacts placed inside `tmp/verification/` are held to the stricter spawner standard, which is why both planner scripts there carry the canonical block and why the green-sim tree lives at `tmp/green-sim/`, outside the corpus.

**Baseline (measured 2026-11-27 at HEAD a0d8ce2):** full suite 554 passed / 1 failed / 555. The single failure is `spawn-isolation-corpus-hook`, **pre-existing and by design**: the live `tmp/verification/` corpus held no `.py` files at measurement time (prior plans' verification scripts retired post-commit), and the test deliberately treats a vacuous live corpus as a visible failure ("non-hermetic by design"; its census precondition "2 EXEMPT / 0 FAIL" reflects the workspace as it was when written). During this plan's rounds the corpus holds exactly two planner artifacts — the gate script and the green-sim generator (`tmp/verification/2026-11-27-partition-retry-streaming-gate.py`, `…-green-sim.py`); the gate carries the canonical mkdtemp + three-assignment isolation block and classifies as a compliant spawner, the generator spawns only `git` (no proxy tokens), so the corpus verdict is clean — and Step 1's full-suite verify and bare `check_spawn_isolation.py` run pass, **provided the planner-era sim residue is retired first**: the iteration-1 GREEN proof generated its tree into `tmp/verification/green-sim/`, inside the scanned corpus, where the seven generated test modules classify as FAIL spawners; the generator now writes to `tmp/green-sim/` (outside the corpus — the checker's default root and the corpus hook's `--path` are `tmp/verification` only), and the stale `tmp/verification/green-sim/` residue is removed by the user-executed hand-off script before Step 1 (and listed in `retire_inventory` as sweep residue). **After the post-commit sweep** the corpus empties and the hook reverts to failing-by-design until the next plan seeds it. This is a workflow consequence to disposition separately (defer / won't-fix / adjust the test's vacuity contract in its own plan); it is not fixed inside this verbatim move.

**Out of scope:** the remaining over-threshold test modules (`test_chat_transform.py` 2,827, `test_cli.py` 2,572, `test_tier_routing.py` 2,087, `_harness.py` 2,045, `test_trace.py` 1,744, `test_mode_dispatch.py` 1,612) — each its own plan; the corpus-hook vacuity contract; any harness refactor; forwarder.py's terminal-state decision (separate track, user-selected sequencing).

## Repo Mode

Public

## Document Overrides

| Document | Rule Overridden | Reason |
|----------|----------------|--------|

## Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| A moved member misses a dependency in its new file | `NameError` at import, suite red | Derived-import tables are gate-pinned exact per file; full suite + standalone `--list` verifies are the gate; cross-destination references verified NONE at HEAD |
| Separator/banner drift makes the move non-verbatim | Gate byte-checks fail, red round | 2-blank separators pinned; banners gate-checked adjacent + text-identical; per-member sha256 vs HEAD |
| ALL_TESTS concatenation breaks count or slugs | Suite count/slug drift | Gate asserts per-file exact pairs vs HEAD-filtered subsequences, total 32, slug-set equality; aggregator untouched |
| Catalog sync drops, duplicates, or reorders an `<li>` | Doc/test catalog desync | 1:1 distribution pinned (10/6/5/4/3/4) in def order; gate asserts per-section name sequences + module-map rows; `check_doc_anchors.py` in Step 2 |
| Post-sweep corpus-hook failure mistaken for a plan regression | False alarm in a later session | Baseline section documents the designed vacuity failure and its during-plan vs post-sweep behavior |

## Proposed Changes

1. **Step 1 (tester): Partition** — the six-file edit exactly as pinned above.
   → tester verify (scripted): `python3 ./tmp/verification/2026-11-27-partition-retry-streaming-gate.py --tests` exits 0 (test-file checks; catalog checks are Step-2-gated).
   → tester verify: `python tests/test_claude_proxy.py` exits 0.
   → tester verify: standalone `--list` per new module (6/5/4/3/4, pinned slugs); kept `--list` 32; one single-test run per new module, each PASSED.
   → tester verify: `python scripts/check_spawn_isolation.py` PASS.
2. **Step 2 (planner): Catalog sync** — `doc/test-catalog.html` per the Catalog sync section, then the full gate exits 0 and `check_doc_anchors.py` exits 0.

## Guidance for Planner

- **Files to modify (What to sync):** `doc/test-catalog.html` — the Catalog sync section above is the spec (planner lane; both precedent partitions assigned the catalog to the planner in a dedicated step). CLAUDE.md's `tests/` line stays true; no other doc names the retry-streaming helper surfaces. The `_drain_child_stderr` doc-row counts are reworded count-free (Catalog sync item 3).
- **`doc/architecture.html`, `doc/trace-log.html`, `README.md`:** reviewed — neither names test modules; no update needed.
- **`.claude/mega-audit-files.json`:** no declared audit locations exist in this repo.
- **Gate authoring:** done — `./tmp/verification/2026-11-27-partition-retry-streaming-gate.py` is authored, RED-calibrated (91 PASS / 35 FAIL `--tests`, 92 / 53 full — every FAIL an exact not-yet-done condition; post-iteration-2 values, which added 28 passing-by-construction checks — symmetric ALL_TESTS-comment conservation + guarded reads — to the iteration-1 63/98 totals; the FAIL counts 35/53 are the stable calibration invariant), spawn-isolation-compliant (canonical mkdtemp + three-assignment block before its subprocess spawns), carries the `--tests` phase gating catalog checks to the full run (the compat gate's iteration-2 lesson), a synthetic BinOp-shape self-check (aborts, not fails — the RED run cannot exercise the restructured kept ALL_TESTS), scope-aware import re-derivation, helper-affinity checks, plain-List shape checks on the sibling ALL_TESTS (r3), guarded working-tree reads, and generalized riding-block handling. The GREEN state is proven by `./tmp/verification/2026-11-27-partition-retry-streaming-green-sim.py`, which mechanically generates the pinned post-partition tree (six test files + HEAD's aggregator and `_harness` + the synced catalog) under `tmp/green-sim/` — outside the spawn-isolation corpus (the checker's default root and the corpus hook's `--path` are `tmp/verification` only); the full gate exits 0 there (260/260) and the sim kept/sibling modules `--list` live. The stale iteration-1-era tree at `tmp/verification/green-sim/` is removed by the user hand-off (`tmp/verification/retire-stale-green-sim.sh`) before Step 1 and rides `retire_inventory`.
- **Pre-implementation mega-audit:** ≥5 test files change — the compat precedent runs the mega-audit before implementation; schedule it after gate calibration, before the tester round.
- **When:** Step 2 runs after Step 1's green verifies, before `/update-and-commit`.

## Cross-References to Prior Plans

| Prior Plan | Deferred Issue | Resolution |
|------------|----------------|------------|
| 2026-11-26-partition-test-compat | — | Mechanics, chained registration, and gate disciplines adopted wholesale; catalog step-3 wording already describes the chained pattern |
| 2026-11-26-partition-chat-sse | — | Five-file feature-area shape precedent |
| 2026-11-26-consolidate-trace-helpers | — | `_harness.py` is the shared-helper home this partition imports from; no new support module needed (no cross-cluster helpers exist here — all four helpers are single-consumer) |

## History

| Date | Event | Conclusion | Dismissed |
|------|-------|------------|-----------|
| 2026-11-27 | Initial plan | Survey: 3,597 lines, 32 tests, 4 single-consumer helpers, 11 single-test banners, 32-pair chronological ALL_TESTS (interleaved, not cluster-contiguous). User approved the test-partition track first (of four proposed tracks), then the 5-sibling grouping as proposed. Mechanical derivation: helper affinity (`_oversized_json_responder`'s consumer is the trace-write-failure test, not the size-cap test — position misled, scan corrected), zero cross-destination references, per-file stdlib/harness import tables (sys only in disconnects+transport), 4 riding ALL_TESTS section comments located. Baseline 554/555 recorded with the corpus-hook vacuity failure attributed (pre-existing, by design, workspace-state not code). Design decisions: chained registration (catalog-documented), kept-then-siblings global order pinned as deliberate, banner ride-along rule (per-test labels preserved, unlike compat's deleted multi-test banners), no support module (no cross-cluster helpers) | Streaming sibling named `_flow` over `_streams`/`_sse` (user approved as proposed); `_harness.py` partition (2,045) — just consolidated into, helper module not feature-partitionable; park |
| 2026-11-27 | Gate authored + RED-calibrated (`./tmp/verification/2026-11-27-partition-retry-streaming-gate.py`, planner lane) | Final RED: `--tests` 59 PASS / 34 FAIL (20 source-heterogeneity separators + 14 exact not-yet-done conditions); full 60 PASS / 52 FAIL (+18 catalog). Every already-holding invariant passes (36/36 member byte-identity, 11/11 riding-banner adjacency, 11/11 banner conservation, footer slugs, 32-pair totals, slug-set equality, aggregator byte-identity). Calibration caught and fixed three real gate defects: (1) pair parse — `ast.literal_eval` on the whole `("slug", name)` tuple fails on the Name-node half, silently yielding 0 pairs; evaluate the slug half only; (2) banner geometry — the source separates every banner from its def with one blank line (rule/label/rule/blank/def); the gate and the plan's Step 1 now pin that exact offset (byte-verbatim form preserved) instead of "directly above"; (3) banner conservation by label count is unsatisfiable — the httpx2 banner label is byte-identical to its ALL_TESTS section comment (pre-existing at HEAD); the check now counts full 3-line blocks | Direct-adjacency banner pinning (would have forced the tester to deviate from the source's own form) |
| 2026-11-27 | Mega-audit iteration 1 (pre-implementation, run `wf_4603c1c2-3fb`, 9 lenses; 29 findings: 4 High / 6 Medium / 19 Low, verdict needs-revision; report at `./tmp/reports/2026-11-27-partition-retry-streaming-mega-audit-2026-11-27.json`) | The 4 Highs are one root seen by four lenses (defect-tracer, oversight-catcher, conflict-resolver, reality-checker): the gate's `all_tests_pairs` reads `value.elts` only on a plain List, but the pinned kept ALL_TESTS is a BinOp (`[10 pairs] + 5 aliases`) — three checks fail forever on a correct GREEN tree while RED cannot see it (HEAD's list is a plain List). Fixed: the extractor descends the BinOp left spine to the leaf List; a synthetic BinOp-shape self-check now aborts the gate if the class regresses (RED cannot exercise that shape); and a green-sim GREEN proof (below) exercises the real shape. Mediums fixed: (1–3, one root) the plan's "the gate re-derives imports from the working tree" and "helper affinity is gate-checked" claims were unimplemented — the gate now derives scope-aware free-name sets per file from member bodies and asserts equality with the pinned tables, and asserts no cross-file member references; (4) Category 7 → Category 2 in all four places (the retry-streaming h4 lives under `<h3 id="cat-2">`; Category 7 is the compat area); (5) two top-level comment blocks the inventory missed (a 2-line extra_request_headers block above `test_retry_stability_extra_header`, a 1-line Sink-guard block above `_oversized_json_responder`) — riding-block detection is generalized to any column-0 comment block in the source geometry (an unlisted block now fails the separator check instead of being silently deleted), and both are pinned as riding in the Move Inventory; (6) duplicate of (1–3). Lows fixed beyond severity: "26 leave" corrected to 25 everywhere (36 − 11 kept = 25); `errors` (count_tokens) and `info` (concurrency) dropped from the pinned `_harness` tables (scope-aware derivation proves both are local shadows — a local `errors = validate_config(...)` assignment and a nested `def streamer(handler, info)` parameter — not harness loads); the independence justification reworded (`test_proxy_listen_backlog` imports the server class, spawns no proxy); the catalog `_drain_child_stderr` reword check re-anchored on the row's unique "daemon reader" prose within a line window (the row's code cell sits on a prior line). GREEN-state proof: `2026-11-27-partition-retry-streaming-green-sim.py` mechanically generates the pinned post-partition tree (six files + HEAD aggregator + `_harness` + synced catalog); the full gate exits 0 there and the sim kept/sibling modules `--list` live. (Path as-run was `tmp/verification/green-sim/`, 232/232 — relocated to `tmp/green-sim/` and re-proven 260/260 in iteration 2.) RED re-calibrated post-fixes: `--tests` 63/35, full 64/53, every FAIL an exact not-yet-done condition | Three sim-shakedown findings folded into the fixes: the generator's missing block/def blank (caught by 13 adjacency FAILs), the catalog anchor window, and `_harness.py` absent from the sim (caught by the live `--list` proof). Remaining Lows acknowledged, no fix: the catalog `<li>` reorder is deliberate and stated; `test_lifecycle`/`test_response_headers` docstrings pointing at `tests/test_retry_streaming.py` for context are historical pointers left as-is (editing other test files' docstrings is out-of-lane scope creep; the catalog is the maintained index); the count_tokens span note records independently verified arithmetic |
| 2026-11-27 | Mega-audit iteration 2 (pre-implementation, run `wf_141bca55-75f`, 9 lenses; 24 findings: 4 High / 3 Medium / 17 Low, verdict needs-revision; report at `./tmp/reports/2026-11-27-partition-retry-streaming-mega-audit-2026-11-27-r2.json`; ≥3 High → iteration 3 scheduled, the cap's last run) | The 4 Highs are one root seen by three lenses (+1 variant): the iteration-1 GREEN proof generated its tree into `tmp/verification/green-sim/` — inside the spawn-isolation corpus — where the seven generated test modules classify as FAIL spawners, making Step 1's full-suite and bare-checker verifies unsatisfiable and falsifying the Baseline's during-round corpus claim (reproduced live: `check_spawn_isolation.py --path tmp/verification` = "8 spawners, 7 fail"). Fixed: the generator now writes to `tmp/green-sim/` (outside the corpus; the checker's default root and the corpus hook's `--path` are `tmp/verification` only); the Baseline, Summary spawn-isolation bullet, Rollback, Guidance-for-Planner, and `retire_inventory` restate the corpus census truthfully (gate + generator are the only in-corpus artifacts, both canonical-block compliant spawners); the stale `tmp/verification/green-sim/` residue rides `retire_inventory` and a user-executed hand-off script (`tmp/verification/retire-stale-green-sim.sh`) removes it before Step 1. Mediums fixed: (1) the gate's working-tree reads/parses are guarded (per-file "parses" FAIL instead of a mid-run traceback; aggregator, `--derive`, block-conservation, and catalog reads included); (2) the corpus-accounting contradiction between the Baseline claim and the artifact inventory is resolved by (1)'s truthful census; (3) the catalog checks fail closed when `HEAD:doc/test-catalog.html` is unreadable (explicit FAIL, never a silent skip), and `git_show` catches OSError/UnicodeDecodeError. Lows fixed beyond severity: the ALL_TESTS section-comment conservation is now symmetric (no invented comment above an uncommented-at-HEAD pair); the intra-test import fence aligned to the generator's consecutive-line form with an explicit "gate pins sequence, not blanks" note; the kept module-map row carries the compat-style chaining annotation ("kept module; chains the five sub-module `ALL_TESTS` lists"), pinned in gate + generator; the aggregator-level `--list` registration proof added to Step 1 (the catalog's §Adding-a-test step 3 demand); the `_drain_child_stderr` row citation corrected to its two-line span (L1207–1208); the kept-file header's 983 clarified as the byte-verbatim members' sum; slug interpolation in the generator is shape-validated (`[a-z0-9-]+`); the generator's replace-anchors carry re-derive hints in their assert messages. GREEN re-proven at the new path: full gate 260/260 (grew with the symmetric comment checks), sim kept/sibling `--list` live. Acknowledged Lows, no fix: stale docstring pointers in `test_lifecycle.py`/`test_response_headers.py` (out-of-lane; r1 disposition stands); the execution-order-risk note (the full-suite Step-1 verify executes every moved test in the new order — that IS the confirmation); the `--path tests/` classification observation (corrected in the Key-decisions bullet; the corpus hook never scans `tests/`); the gate's isolation-block adequacy note (assurance, no defect) | The relocation over deletion: `tmp/green-sim/` keeps the proof inspectable and gitignored, while the stale corpus residue needs the user's hand-off (agents never delete; the deny layer correctly refused `rm -rf`) |
| 2026-11-27 | Mega-audit iteration 3 (pre-implementation, run `wf_d97e7ead-4b7`, 9 lenses; 20 findings: 0 High / 1 Medium / 19 Low, verdict **non-blocking** — 0 High exits the iteration loop at the cap; report at `./tmp/reports/2026-11-27-partition-retry-streaming-mega-audit-2026-11-27-r3.json`) | The Medium fixed: the gate's non-keep ALL_TESTS branch never asserted the value is a plain List (a BinOp with an undefined alias passed the pair check, deferring a NameError to runtime) — a plain-List shape check now FAILs the gate. Lows fixed: RED counts refreshed (91/35 `--tests`, 92/53 full — the post-iteration-2 measurements; the FAIL counts 35/53 are the stable invariant, and the History rows' earlier numbers are as-measured-at-the-time records, not stale claims); the Step-1 separator rule now names the three extra 2-blank seams the gate pins (last-import→first-member, member→ALL_TESTS, ALL_TESTS→footer; intra-import seams unpinned; the green-sim generator's form is the reference geometry); `head_state`'s HEAD parse is guarded so a corrupted HEAD read routes to the exit-2 calibration abort instead of a traceback; the generator's `git_show` mirrors the gate's OSError/UnicodeDecodeError handling; the Baseline's in-corpus census reworded to the observable truth (the gate is the classified compliant spawner; the generator spawns only git); the post-sweep vacuity claim scoped; `tmp/verification/baseline-suite.log` added to `retire_inventory`; the retire hand-off script now resolves the repo root from its own location and its guard comment matches what it checks. Acknowledged Lows, no fix: the within-kept docstring cross-reference in `test_connection_error_retry_mapping` to the moved count_tokens conn-error test (stale-pointer class, r1 disposition stands); the tester-section contract-marker shape note (the metadata block parses valid; the three markers are present); the count-free-reword substring heuristic (an absence check over a windowed region — adequate for a reword whose replacement text is pinned verbatim in the green-sim generator, which the full gate proves byte-exact) | The audit converged: 4→4→0 High across the three capped iterations; the plan is implementation-ready |
| 2026-11-28 | Coder round 1 (no-op; report at `./tmp/reports/2026-11-27-partition-retry-streaming-coder-2026-11-28.json`) | SUCCESS — the plan declares zero coder work ("Guidance for Coder: None"); both steps skipped, working tree untouched, no issues filed. The session pre-verified the tester round's preconditions read-only: newest mega-audit is r3 (non-blocking, 0 High) with a matching History row; the `tmp/verification/green-sim/` residue is absent (the user hand-off ran 2026-11-28); bare `check_spawn_isolation.py` PASS; the gate's RED calibration measures exactly 91/35 `--tests` as pinned; package imports clean. Residual adopted: `tmp/verification/__pycache__/` (gate bytecode, skipped by the checker as non-Python) added to `retire_inventory` so the post-commit sweep removes it | — |
| 2026-11-28 | Tester round 1 (Step 1 Partition; report at `./tmp/reports/2026-11-27-partition-retry-streaming-tester-2026-11-28.json`) | SUCCESS — full suite **555/555** (count unchanged from HEAD; improves on the 554/1 baseline: the corpus hook passes during-plan because the live corpus holds the compliant gate script, census "1 spawners, 0 fail, 0 exempt, 1 skip"), gate `--tests` **246/246 exit 0** on the real tree (all 36 members exact membership + def order, 36/36 byte-identical to HEAD, 13/13 riding blocks adjacent), RED precondition reproduced exactly (91/35), standalone `--list` 6/5/4/3/4 + kept 32, one single-test run per new module each PASSED, aggregator `--list` shows the 32 slugs contiguously at the `RETRY_STREAMING_TESTS` position, `check_spawn_isolation.py` PASS, aggregator byte-untouched. Implementation route: the tester regenerated `tmp/green-sim/` via the planner generator and copied the emitted files into `tests/` — the gate independently re-reads HEAD and re-verifies every byte, so the route is sound by construction | — |
| 2026-11-28 | Step 2: Catalog sync (planner lane) | `doc/test-catalog.html` synced: Category 2 re-sectioned into six `<h4>` sections in plan order (10/6/5/4/3/4 `<li>`, def order, entries byte-identical incl. the ` (added …)` annotations), module-map `test_retry_streaming.py` row split into the six rows with the compat-style chaining annotation on the kept row, `_drain_child_stderr` row reworded count-free per the Catalog sync spec. Verifies: full gate **265/265 exit 0** on the real tree (byte-identical checks to the green-sim proof), `check_doc_anchors.py` PASS (272 anchors, 8 files, no secret shapes) | — |
| 2026-11-28 | Phase 6 implementation review (report at `./tmp/reports/2026-11-27-partition-retry-streaming-review-2026-11-28.json`) | Verdict **Issues found — non-blocking (commit-ready)** — 0 Critical / 0 Warning / 1 Suggestion. The reviewer independently re-verified beyond the gate: all 36 members sha256-identical to HEAD and each present exactly once (own name-keyed AST check), chained ALL_TESTS resolves at import time (32 entries, 32 unique, kept-then-siblings order as pinned), all six modules import cleanly, aggregator diff vs HEAD empty, delivered files byte-identical to the green-sim reference tree, catalog `<li>` texts byte-identical to HEAD with per-section def order and counts 10/6/5/4/3/4, six module-map rows in plan order, the `_drain_child_stderr` row count-free with no residue, Category-2 and whole-doc HTML tag balance clean, and no stale references to the old combined module anywhere in doc/, README.md, or CLAUDE.md. The single Suggestion (Readability): the six delivered files use a single-line unseparated `_harness` import where HEAD and the 36-module repo convention use a blank-separated multi-line parenthesized block — nothing pins physical form (the gate asserts subjects/order only). Resolved in the planner lane per the compat Phase 6 precedent: the Derived Imports section now documents the delivered single-line form as a deliberate accepted deviation; no file, gate, or generator churn for a cosmetic | Two reviewer hunches dismissed as whitespace-only: no blank line before catalog sections 2–6's `<h4>` elements (renders identically, tag balance verified); the kept module-map row wraps its `<td>` across two lines vs the sim's one-liner (renders identically) |

## Plan Metadata

```json
{
  "plan_id": "2026-11-27-partition-retry-streaming",
  "steps": [
    "Step 1: Partition",
    "Step 2: Catalog sync"
  ],
  "coder_files": [],
  "tester_files": [
    "tests/test_retry_streaming.py",
    "tests/test_retry_streaming_count_tokens.py",
    "tests/test_retry_streaming_flow.py",
    "tests/test_retry_streaming_concurrency.py",
    "tests/test_retry_streaming_disconnects.py",
    "tests/test_retry_streaming_transport.py"
  ],
  "doc_files": [
    "doc/test-catalog.html"
  ],
  "verification_scripts": [
    "./tmp/verification/2026-11-27-partition-retry-streaming-gate.py",
    "./tmp/verification/2026-11-27-partition-retry-streaming-green-sim.py"
  ],
  "retire_inventory": [
    "./tmp/verification/2026-11-27-partition-retry-streaming-gate.py",
    "./tmp/verification/2026-11-27-partition-retry-streaming-green-sim.py",
    "./tmp/verification/retire-stale-green-sim.sh",
    "./tmp/verification/__pycache__/",
    "./tmp/green-sim/",
    "./tmp/verification/green-sim/",
    "./tmp/verification/baseline-suite.log",
    "./tmp/reports/2026-11-27-partition-retry-streaming-mega-audit-2026-11-27.json",
    "./tmp/reports/2026-11-27-partition-retry-streaming-mega-audit-2026-11-27-r2.json",
    "./tmp/reports/2026-11-27-partition-retry-streaming-mega-audit-2026-11-27-r3.json",
    "./tmp/reports/2026-11-27-partition-retry-streaming-coder-2026-11-28.json",
    "./tmp/reports/2026-11-27-partition-retry-streaming-tester-2026-11-28.json",
    "./tmp/reports/2026-11-27-partition-retry-streaming-review-2026-11-28.json"
  ],
  "repo_mode": "Public",
  "document_overrides": []
}
```

## Audit Accumulation

| Counter | Value | Last Updated |
|---------|-------|--------------|
| issues_resolved_since_audit | 0 | 2026-11-27 |
| steps_changed_since_audit | 0 | 2026-11-27 |
| files_changed_since_audit | 0 | 2026-11-27 |

## Documentation

- `doc/test-catalog.html` Category 2 re-sections in Step 2, planner lane (six file sections, 1:1 `<li>` distribution in def order, byte-identical descriptions, six module-map rows, the `_drain_child_stderr` count-free reword). No other doc names retry-streaming test modules; CLAUDE.md's `tests/` line stays true; README does not enumerate test modules.

## Final Results

**Completed 2026-11-28 — status COMPLETED.**

**Files changed:**
- `tests/test_retry_streaming.py` — kept module: 12 members (11 sha-verbatim + the restructured chained `ALL_TESTS`)
- `tests/test_retry_streaming_count_tokens.py` — new, 6 members
- `tests/test_retry_streaming_flow.py` — new, 5 members
- `tests/test_retry_streaming_concurrency.py` — new, 4 members
- `tests/test_retry_streaming_disconnects.py` — new, 6 members (3 tests + 3 single-consumer helpers)
- `tests/test_retry_streaming_transport.py` — new, 4 members
- `doc/test-catalog.html` — Step 2 catalog sync (Category 2 re-sectioned into six `<h4>` sections in def order, six module-map rows with the kept-row chaining annotation, the `_drain_child_stderr` count-free reword)
- `tests/test_claude_proxy.py` — untouched, byte-identical to HEAD (reviewer-verified: empty diff)

**Test results:** full suite **555/555 passed** (count unchanged from HEAD; the plan's 554/1 baseline failure — the spawn-isolation corpus hook's designed vacuity signal — passes during-plan because the live corpus holds the compliant gate script); verification gate `--tests` **246/246**, full gate **265/265**, exit 0; standalone `--list` 6/5/4/3/4 + kept 32; five single-test standalone runs PASSED; aggregator-level `--list` shows the 32 slugs contiguously at the `RETRY_STREAMING_TESTS` position; `scripts/check_spawn_isolation.py` PASS; `scripts/check_doc_anchors.py` PASS (272 anchors, 8 files). Every moved member independently verified sha256-identical to HEAD (gate + reviewer).

**Issues resolved:** none — the plan adopted no deferrals and filed none; the Issue Log stayed empty through three audit iterations and two rounds.

**Deferred issues:** none.

**Review:** Phase 6 non-blocking, commit-ready — 0 Critical / 0 Warning / 1 Suggestion (the single-line `_harness` import form, documented in the Derived Imports section as a deliberate accepted deviation per the compat precedent).

**Mega-audit:** 3 capped iterations (4 High → 4 High → 0 High / non-blocking); reports at `./tmp/reports/2026-11-27-partition-retry-streaming-mega-audit-2026-11-27{-r2,-r3}.json`.
