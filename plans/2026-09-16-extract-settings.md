# Plan: Extract the settings cluster out of server.py into settings.py (settings object + cli.py de-duplication)

**Project:** D:/proj/claude-retry-proxy
**Plan ID:** 2026-09-16-extract-settings
**Created:** 2026-09-16

<!-- ## Immediate Actions: absent from initial plans. Populated by /update-plan for revised plans, replaced (not accumulated) on each revision. Contains per-role action-only directives (no rationale) telling agents what to do next. Agents read the full plan for context. -->

## Issue Log

Rows ordered newest-first (latest issues at top). New issues are prepended; resolved issues stay in place with updated status.

| Issue | Status | Found | Resolved | Resolved By |
|-------|--------|-------|----------|-------------|
| [step2-abs-arg-check-unsatisfiable](./tmp/reports/2026-09-16-extract-settings-step2-abs-arg-check-unsatisfiable.json) | Resolved | 2026-09-16 | 2026-09-16 | planner — fixed the fixture to a cwd-rooted absolute path; step2.py exits 0 against the coder's current tree |

## Guidance for Coder

**Files to modify:**
- `src/claude_retry_proxy/settings.py` (created)
- `src/claude_retry_proxy/server.py` (modified)
- `src/claude_retry_proxy/cli.py` (modified)

**Step-by-step with verification:** each step below carries coder checks tagged `(auto)` or `(scripted)`. The coder self-verifies `(auto)` and runs the provided script for `(scripted)`. Tester owns the behavioral checks.

This plan is **behavior-preserving in Step 1**, a **mechanical rename** in Step 2, and **behavior-preserving in Step 3 except for the two declared env-surface deltas** (see asymmetry 4 below — both confirmed by the user on 2026-09-16; they make the CLI honor the same documented env vars the server honors). Apart from those declarations, every value, every default, every fallback must come out identical. Do not "improve" anything — no new env vars, no warning output, no validation changes, no f-strings replacing `.format()`, no reordering of the derivation.

Four load-bearing asymmetries to preserve exactly, plus two declared deltas. Get an asymmetry wrong and the suite passes while the proxy silently changes behavior:

1. **`state_file` passthrough.** `STATE_FILE = os.environ.get("PROXY_STATE_FILE", ...)` returns `""` when the variable is set-but-empty — unlike the trace path, which maps `""` to the default via `_env_str`. The sinks plan (`2026-09-11-extract-sinks.md`, Step 2) documented why this matters: `configure()` tests paths with `is not None`, so an empty path is passed through, not silently replaced. `settings.py` must reproduce `os.environ.get` for the state file verbatim — do not "unify" it onto `_env_str`.
2. **Out-of-range `_env_int` falls back to the default, not to the bound.** `PROXY_PORT` set to `10` must resolve to `8080`, not `1024`. Reproduce `_env_int`'s three-branch body verbatim (empty → default; unparseable → default; out of `[min, max]` → default).
3. **Call-time env read in the trace resolver.** `cli.py`'s `resolve_trace_path` reads `$PROXY_TRACE_FILE` at **call** time (`cli.py:149`), not import time. The consolidated `settings.resolve_trace_file(log_arg)` must keep `cli.py`'s shape verbatim — **`if log_arg:` truthiness included**: `log_arg` first (made absolute against cwd), then `os.environ.get("PROXY_TRACE_FILE", "")`, then `SETTINGS.trace_file` as the default. The one divergent input is server-side `--log ""`: today `main()`'s `if args.log is not None:` joins the empty string against the cwd (trace file = cwd), while the consolidated resolver falls through to env/default. That single pathological input is a **declared, accepted delta** (saner outcome on both sides; the CLI side is unchanged) — see Risks. No other input diverges: for every non-empty `--log` and for `None`, both processes behave exactly as today.
4. **The two declared Step-3 env-surface deltas** — documented, not buried: (a) `--port` default becomes `SETTINGS.port`, so with `$PROXY_PORT` set and no `--port`, the CLI-spawned server now receives the env-selected port instead of the hardcoded `8080` (the approved scope text named this hardcode); (b) `KEYS_FILE` aliases `SETTINGS.keys_path`, so with `$PROXY_KEYS_PATH` set, the CLI now validates against and spawns with the env-selected keys file instead of `~/.claude/keys-index.json` regardless. Previously the CLI could validate keys file A while the spawned server resolved keys file B — the unification is the point. Neither delta fires under an unset env; the harness sets neither var. Both are confirmed design decisions recorded in History; the tester's T2 gate adds a spawn-env check covering them.

### The 14 legacy names and their attribute mapping

These are the settings-category names that move. The mapping below is authoritative for Step 2; the scripts assert it.

| Legacy name (leaves `server.py`) | `SETTINGS` attribute | Current readers (before Step 2) |
|---|---|---|
| `PROXY_PORT` | `.port` | `main` ×6, `do_POST` ×3 |
| `PROXY_MAX_RETRIES` | `.max_retries` | `_forward_core` ×1 |
| `PROXY_INITIAL_DELAY` | `.initial_delay` | `compute_delay` ×1 |
| `PROXY_MAX_DELAY` | `.max_delay` | `compute_delay` ×1, `_forward_core` ×1 |
| `PROXY_MAX_BODY_SIZE` | `.max_body_size` | `_forward_request_impl`, `_forward_core`, `_compat_rejection_match`, `do_POST` |
| `PROXY_MAX_RESPONSE_SIZE` | `.max_response_size` | `_forward_core` ×6, `_stream_upstream_response` ×4, `_stream_chat_sse_to_anthropic` ×2, `_log_response_cap_exceeded` ×1 |
| `PROXY_LOG_ALL` | `.log_all` | `do_POST` ×1 |
| `PROXY_TRACE_FILE` | `.trace_file` | `main` ×2 |
| `PROXY_KEYS_PATH` | `.keys_path` | `main` ×1 |
| `DEFAULT_CONFIG_PATH` | `.config_path` | `main` ×1 |
| `CONFIG_TEMPLATE_PATH` | `.config_template_path` | `install_template` ×1 |
| `STATE_FILE` | `.state_file` | `main` ×3 |
| `PROXY_FEATURE_COMPAT_FILE` | `.feature_compat_file` | `_load_compat_state` ×1, `_persist_compat_state_locked` ×4 |
| `MODE_VALUES` | `.mode_values` | `_forward_request_impl` ×2, `load_keys_file` ×1, `do_GET` ×1 |

Total: **50 read sites** — 48 inside function bodies (per the per-function AST scan) plus 2 at module level (`sinks.configure(trace_path=PROXY_TRACE_FILE, state_path=STATE_FILE)` at `server.py:747`); **25 of them sit in the risk zone** (`do_POST`, `_forward_core`, `_forward_request_impl`, the two `_stream_*` loops, `_log_response_cap_exceeded`, `_compat_rejection_match`). Every site is a mechanical `NAME` → `SETTINGS.attr` substitution — no signature changes, no reordering, no control-flow edits.

**Do not move these, even though they sit in or near the settings region of `server.py`:**

| Name | Line | Why it stays |
|------|------|--------------|
| `_config_lock`, `_current_config`, `_config_path`, `_inflight_count`, `_config_swapping`, `_swap_done`, `_startup_state`, `_vendors` | 89-108 | Runtime-mutated state (§5 category 2). They are rebound under lock and by tests; they are not settings. Their eventual home is the forwarder/handler waves, not `settings.py`. |
| `_rng`, `_rng_local` | 108-119 | Thread-local RNG for backoff jitter. Backoff machinery, not configuration. |
| `ADMIN_BODY_LIMIT` | 120 | Admin-domain constant; rides with the admin cluster in a later wave. |
| `COMPAT_INITIAL_THRESHOLD` … `COMPAT_SCHEMA_VERSION` | 856-869 | Compat feature constants; ride with the compat cluster in wave 4. |

**Rollback.** Steps 1 and 3 are additive-green and revert independently. Step 2 and the tester's re-point (Steps T1–T2) are one reviewable unit: revert the single commit that closes it (`git revert`), nothing else. No data or artifact migration — the settings are derived from env at import in every process, exactly as today.

**How the scripts were validated.** All four were run by the planner against the pre-change tree (2026-09-16) and each fails on exactly the not-yet-done conditions: `step1.py` exits early with "settings.py missing" (its module did not exist; its in-script predicates were control-checked against the current `server.py:45-87` block, which the pinned fragments match byte-for-byte today); `step2.py` fails on exactly the calibrated baseline — **50 legacy `Name` loads** at the enumerated sites (including `:747`), zero `SETTINGS` attribute loads, zero `SETTINGS`-based configure calls, `global` declarations naming the three legacy constants in `main()`, settings missing; `step3.py` fails on exactly 2 `os.environ` reads, the MUST-mirror comment, the `resolve_trace_path` def and its 1 call site, `TRACE_FILE_DEFAULT`, a non-`SETTINGS` `--port` default, and the co-import; `t2.py` fails on exactly **22 legacy reference sites** across `tests/` — which is how the plan discovered its first inventory had missed `tests/test_unit.py`'s six bare-name comparisons. A gate that passes before the work is done checks nothing — these fail before it.

## Guidance for Tester

**Tests to create:**
- **Permanent:** `tests/test_settings.py` — direct unit tests of the settings module, reachable only after this plan (nothing could import the object before). Register the module in `tests/test_claude_proxy.py` (import + append to `ALL_TESTS`) — **the aggregator imports each module explicitly and does no discovery, so an unregistered file never runs.**
  - `test_env_int_fallback_semantics` — the five `_env_int` cases (valid in-range, unparseable → default, below-min → default, above-max → default, empty/unset → default) against a fresh name (e.g. `CLAUDE_RETRY_PROXY_TEST_UNSET_*` with `os.environ` saved, set, restored in `finally`). These cases have no existing coverage anywhere; everything else drives them indirectly through spawn-env.
  - `test_env_str_fallback_semantics` — set → value; set-but-empty → default.
  - `test_settings_object_shape` — `srv.SETTINGS is settings.SETTINGS` (the same object — the patch-coherence guarantee); all 15 attributes present with the pinned types (`mode_values == ("anthropic", "chat", "response")`, the ints are ints, the paths are strings).
  - `test_resolve_trace_file_chain` — absolute `log_arg` wins; relative `log_arg` joins the cwd; `log_arg=None` + env set at call time returns the env value; `log_arg=None` + env empty returns `SETTINGS.trace_file`. (The env cases can set `os.environ` at test time because the resolver reads env at call time — save/restore in `finally`.)
- **Temporary:** none.

**Tests to re-point (Steps T2):** the suite's in-process patches to the legacy names must target `SETTINGS` attributes instead. Rebind-by-assignment becomes attribute mutation — save/assign/restore patterns all survive because the tests already save and restore:

- `tests/test_retry_streaming.py` — `test_retry_path_print_failure_does_not_misclassify` (region 2769-2816): the saved tuple gains `srv.SETTINGS.max_retries, srv.SETTINGS.initial_delay, srv.SETTINGS.max_delay`; the three assignment lines become `srv.SETTINGS.max_retries = 1` etc.; the restore stays tuples.
- `tests/test_compat.py` — six sites of `srv.PROXY_FEATURE_COMPAT_FILE` (561, 564, 576, 949, 952, 974) → `srv.SETTINGS.feature_compat_file`, same save/assign/restore shape.
- `tests/test_config_keys.py:294` — `state_path = srv.STATE_FILE` → `state_path = srv.SETTINGS.state_file`.
- `tests/test_unit.py` — the import line (`:26-27`) pulls `PROXY_INITIAL_DELAY` / `PROXY_MAX_DELAY` from `server` as bare names and six read-only comparisons use them (`:99`, `:100`, `:102`, `:104`, `:105`, `:107` — `compute_delay(0) == PROXY_INITIAL_DELAY`-style). Drop them from the import and re-point the six comparisons to `srv.SETTINGS.initial_delay` / `srv.SETTINGS.max_delay` (or bring `SETTINGS` into whatever name the module uses — the t2 gate only requires zero legacy references). No assertion changes.

The pre-change reference count is **22 sites** (16 `srv.<legacy>` attribute refs + 6 bare-name refs in `test_unit.py`), enumerated by `./tmp/verification/2026-09-16-extract-settings-t2.py` — a grep-based inventory undercounts (the plan's first inventory missed `test_unit.py` entirely).

**Tests to investigate for retirement:**
- Planner candidates: none. Every named test is retained and re-pointed — they change *which object* they patch, not *what* they assert. The env-key surface (`$PROXY_TRACE_FILE`, `$PROXY_STATE_FILE`, …) is untouched by this plan, so every harness/spawn-env test keeps working unchanged.
- Tester may identify additional candidates during test work.

**Retirement procedure:** For each candidate, verify the test exercises code being removed/changed. If obsolete: delete and note in session report. If still valid: document why in session report.

## Summary

**Problem.** `server.py` is 3,719 lines and still holds the settings cluster — env resolution and path defaults — scattered across three regions (`:49-87`, `:741`, `:871`, plus `MODE_VALUES` at `:186`), with `cli.py` carrying a **duplicated copy** of the same derivations in a separate process and a load-bearing "MUST mirror `server.py` main()" comment (`cli.py:26,141-145`). Every later extraction in the doctrine's staged order needs these values importable without touching `server.py`: compat needs `feature_compat_file`, keys needs `mode_values`, the forwarder needs the limits — so this plan is the settings step of the /refactor-split-tracked decomposition (the repo-local `.claude/cluster-extraction-criteria.md` §7 that previously sequenced it was deleted by the 2026-09-16 consolidation into the global guide), and it closes the patch-coherence hazard before any consumer imports from a second module.

This plan follows `~/.claude/guides/refactor-split-guidance.md` (mandated by the repo's `CLAUDE.md` "Refactoring" section as of the 2026-09-16 consolidation; the repo-local cluster-extraction criteria it superseded has been deleted): membership by the Concept/Substitution/Deletion tests, one cluster per plan, move-then-shape, and green commits at every committed boundary.

**What moves, and the shape it lands in.**

```
settings.py   stdlib only — imports nothing from claude_retry_proxy (a true leaf;
              server.py and cli.py both import it)
  __all__ = ["SETTINGS", "ProxySettings", "resolve_trace_file"]

  ProxySettings   a plain-attribute value bag constructed at import from
                  (env, defaults). Owns the 14 legacy values plus proxy_dir:
                  .port .max_retries .initial_delay .max_delay
                  .max_body_size .max_response_size .log_all
                  .trace_file .keys_path .config_path .config_template_path
                  .state_file .feature_compat_file .mode_values .proxy_dir

  SETTINGS        the one instance. server.py binds it via
                  `from .settings import SETTINGS`, so srv.SETTINGS IS
                  settings.SETTINGS — one object, one binding, every process,
                  every future import path.

  resolve_trace_file(log_arg)   the single trace-path chain: --log (abs against
                  cwd) > $PROXY_TRACE_FILE (read at call time) > SETTINGS.trace_file
```

`server.py` gains `from .settings import SETTINGS, resolve_trace_file`; all 50 read sites (48 in function bodies, 2 at the module-level `sinks.configure`, `server.py:747`) become `SETTINGS.<attr>`; `main()` drops its `global PROXY_*` declarations and applies argparse overrides to `SETTINGS.port` / `SETTINGS.trace_file` (`= resolve_trace_file(args.log)`) / `SETTINGS.log_all` — the startup-resolution layer the module docstring documents. `cli.py` imports the same object: its four path constants become aliases (`PROXY_STATE_FILE = SETTINGS.state_file`, `CONFIG_FILE = SETTINGS.config_path`, `KEYS_FILE = SETTINGS.keys_path`, `CONFIG_TEMPLATE_PATH = SETTINGS.config_template_path`, `PROXY_DIR = SETTINGS.proxy_dir` — ~30 usage sites untouched), `resolve_trace_path` is deleted (1 call site, `cli.py:487`, re-pointed to the shared resolver), and argparse's `--port` default becomes `SETTINGS.port`.

**Why an object, not re-exported names.** Test patches and `main()`'s startup rebinds are *rebinding* hazards (the state doctrine, §5 of the global guide): once any later module imports a value directly, `srv.<NAME> = x` patches stop affecting it silently. A shared object whose attributes are written in place has one binding for every reader in every module — patch `SETTINGS.max_delay` and every current and future consumer sees it. Immutability is by convention, not enforcement: production code reads the attributes and only `main()` writes them at startup; tests may write them in place (save/restore). This is the deliberate trade the repo's documented env-at-import contract requires — declared in Document Overrides.

**Key design decisions.**

- **Step 1 is a verbatim move; Step 2 is the shape; Step 3 is the cli de-dup.** Move-then-shape per criteria §6: Step 1 relocates the derivation block into `settings.py` and re-exports all 14 names from `server.py`, so every read site is untouched and the tree is green at the first commit. Step 2 introduces the object and does the 48-site rename. Steps 2 and the tester's re-point form one reviewable unit (red interval documented; no commit inside).
- **The `state_file` empty-string asymmetry is preserved** (see Guidance for Coder): state uses raw `os.environ.get`, trace uses `_env_str`.
- **The trace resolver reads env at call time**, preserving `cli.py`'s current prune-time behavior exactly (its truthiness shape included); for `server.py` it is identical for every input except the single declared edge `--log ""` (today cwd-joined `""`, now falls through to env/default — accepted delta, see Risks).
- **Two declared env-surface deltas in Step 3** — with `$PROXY_PORT` / `$PROXY_KEYS_PATH` set, the CLI now honors the same overrides the server honors (the approved scope text named the hardcoded `8080`; the keys-file unification removes the today-possible validate-A/spawn-B split). Confirmed by the user 2026-09-16; enumerated as asymmetry 4 so the coder cannot "fix" them back and the tester does not chase them as regressions.
- **The runtime-mutated globals stay.** `_current_config`, `_vendors`, drain-and-swap state, `_rng` — §5 category 2; they move in later waves with their owners. Their tests (`srv._current_config` patches in `test_retry_streaming.py` etc.) are untouched by this plan.
- **`settings.py` is a leaf.** It imports only stdlib. The extraction-order discipline (settings before compat, compat before the forwarder) exists precisely so each new module can reach settings without circular imports.

**Module-surface changes.** The 14 legacy names stop resolving on the `server` module (Step 2's script asserts `hasattr(server, <name>)` is False for each); `SETTINGS`, `ProxySettings` and `resolve_trace_file` appear on both `server` and `settings`. Every other `server` name — `srv._current_config`, `srv._vendors`, `srv.forward_request`, the sinks delegates, `STATE_FILE`'s consumers via `SETTINGS` — keeps resolving. This repo's docs and README reference none of the 14 names (verify-only check in Guidance for Planner); the removal is a deliberate, counted surface change, not collateral.

**Alternatives considered and rejected.**

- *Verbatim-only (no rename) and defer the object to the forwarder wave* — keeps plan 1 smaller but leaves the rebinding hazard live through two waves, and the compat wave would inherit 6 test-patch sites that silently break. Renaming at the smallest cluster (110 lines) proves the pattern at minimum cost.
- *Build `SETTINGS` in `main()` per §5's ideal* — a behavior change to the documented env-at-import test contract (`CLAUDE.md` Gotchas; `_harness` sets env before importing `server`), churning the harness for a hazard that is already contained. Rejected; declared as a Document Override. The `main()`-built refactor stays available if the coupling ever hurts.
- *Replace `cli.py`'s constant usages wholesale with `SETTINGS.attr` reads* — ~30 mechanical edits for zero behavioral gain; aliases keep the CLI's own code readable and the diff small.
- *`MODE_VALUES` into `transforms_common.py`* — rejected: it is a config-domain constant read by the keys loader and the admin handler as well as the forwarder; §5 explicitly lists it under settings.
- *Fold `PROXY_DIR` duplication by computing `os.path.dirname(SETTINGS.state_file)` in `cli.py`* — rejected: better to own the path once in settings and alias it.

**Out of scope.** Every other cluster (config, keys, compat, forwarder, handler, admin); function-signature injection of the settings object (`def f(..., settings=SETTINGS)` lands per-wave when a wave's tests actually need an override point); the deferred `image-content-blocks-chat-mode` and `extract-model-raises-on-non-object-json` issues, which touch other code; the test-file split halves of `break-up-large-source-and-test-files`.

## Repo Mode

Public

*Detected at plan creation. Determines: plan archival path, commit-message content, staged files.*

## Document Overrides

| Document | Rule Overridden | Reason |
|----------|----------------|--------|
| `~/.claude/guides/refactor-split-guidance.md` §5 — "Build the settings object in `main()`, not at import" | `SETTINGS` is derived at **import** from env, then adjusted by `main()` at startup | The repo's documented test contract is env-at-import (`CLAUDE.md` Gotchas; `tests/_harness.py` sets `PROXY_*` env vars before importing `cli`/`server`, which is load-bearing for suite isolation). A `main()`-built object would be a second behavioral change grafted onto a structural plan, churning the harness for no current need. Mutability is convention-guarded (docstring: production reads; only `main()` writes at startup; tests may write in place) and upgradeable to `main()`-built later without touching consumers. **Recorded here and in CLAUDE.md's settings entry, not in the shared guide** — the guide is cross-repo doctrine; a project-specific deviation does not belong in its text. (The superseded repo-local criteria doc carried the same rule and is deleted.) |

## Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| **Red interval between Step 2 and the tester's re-point.** The 22 in-process reference sites stop working the moment `server.py` drops the legacy names — and the coder may not edit tests. | The tree is red between the two sessions; no green commit exists at the coder's boundary for that unit. | Step 2 and Steps T1–T2 are **one reviewable unit**: coder renames, tester re-points, suite green, one review, one commit. This is inherent to the coder/tester boundary. Do not commit between them. Steps 1 and 3 are independently green and committed separately. |
| A rename misses a read site, leaving a `NameError` in a branch the suite rarely executes (e.g. a 429 give-up path) | Boom at runtime, invisible in CI | Scripted Step 2 asserts **zero** `Name` loads of any of the 14 legacy names anywhere in `server.py` (AST-based, not text-grepped — comments/docstrings cannot false-pass or false-fail it). 50 sites are enumerated per function so a missed one fails the count. |
| A test patch goes **inert** rather than red — the suite stays green while the test silently stops configuring what it thinks it configures | Loss of test isolation that no gate reports | Step T2's verify is an **AST-based** zero-count script (`2026-09-16-extract-settings-t2.py`) for bare and `srv.<legacy>` loads across `tests/` — per the token-not-text rule, comments cannot false-fail it and wrapped access cannot false-pass it (the sinks plan's grep gate was text-shaped; this is the hardened form). |
| A re-pointed save/assign raises before its restore — the mutated `SETTINGS` attribute leaks into every later test module | Cross-test contamination on the shared singleton (the very hazard the object design exists to close) | T2 mandates try/finally for every re-pointed site and requires the tester to confirm the finally by reading the surrounding block; the t2 script asserts each re-pointed file still contains a restore. |
| The two declared Step-3 env deltas surprise a user or test later (with `$PROXY_PORT`/`$PROXY_KEYS_PATH` set, the CLI behaves differently than today) | A real behavior change shipped as if structural | Declared as asymmetry 4, in Summary, in Risks, with tester spawn-env assertions — and recorded as the plan's explicit semantic-change list rather than left implicit. |
| The consolidated resolver diverges from today's server for `--log ""` (truthiness vs `is not None`) | The pathological empty-string arg now falls through to env/default instead of cwd-joining `""` | Accepted and declared (asymmetry 3 + Summary). It is the only divergent input; every non-empty or absent `--log` is identical across both processes. |
| `resolve_trace_file` derives at import instead of reading env at call time, silently changing the CLI prune path when env is set post-import | The CLI prunes (or fails to prune) a different file than the server writes | Pinned: the resolver reads `os.environ` at call time, exactly matching `cli.py:147-150` today; `test_resolve_trace_file_chain` asserts the call-time env branch directly. |
| `state_file` gets "unified" onto `_env_str` and the set-but-empty `""` passthrough silently vanishes | `configure()` receives a different path for `PROXY_STATE_FILE=""` — a documented, tested behavior | Pinned verbatim in Guidance for Coder and asserted by Step 1's verbatim-block check; the existing `PROXY_STATE_FILE=""` behavior is preserved by construction. |
| `test_settings.py` re-asserts branches the integration suite already covers | Overlap inflation with no new coverage | Scope discipline: only the four `_env_int` branches, `_env_str`, the object identity/shape, and the resolver chain are new — everything else exists only through spawn-env integration today. |

## Proposed Changes

Each step includes verification checks tagged with confidence (see Prime Directive 4).
`(auto)` = mechanical, coder self-verifies. `(scripted)` = deterministic multi-step, coder runs provided script.
Every step must have at least one verification check executable by its owner (coder steps: coder checks; tester steps: tester verify; planner steps: Evidence).

1. **Step 1:** Create `src/claude_retry_proxy/settings.py`. Move the settings derivation block out of `server.py` **verbatim** — the comment header, `_env_int`, `_env_str`, the nine env-derived values, `_default_trace`/`_src_root`/`DEFAULT_CONFIG_PATH`/`CONFIG_TEMPLATE_PATH`/`_default_keys` — plus the three stragglers as module-level names: `STATE_FILE` (with its raw-`os.environ.get` semantics, derived from a new `PROXY_DIR`/`proxy_dir` base the same way `cli.py:19-20` does), `PROXY_FEATURE_COMPAT_FILE` (the `_env_str` pair at `server.py:871-874`), and `MODE_VALUES` (`server.py:186`). The **byte-fidelity requirement applies to the `:45-87` block**; the three stragglers are pinned by *value* (their original definitions were shard-shaped — the `STATE_FILE`/`PROXY_FEATURE_COMPAT_FILE` literals sit on their own lines — and `step1.py` asserts the exact computed values rather than the literal text). Skeleton: `__all__` is not yet used (this step ends with module-level names, so the coder declares nothing; the object arrives in Step 2). In `server.py`: delete the moved definitions — the block at `:45-87` (section comment through `PROXY_KEYS_PATH`), the `MODE_VALUES` def at `:186`, the `STATE_FILE` def at `:741`, the `PROXY_FEATURE_COMPAT_FILE` def at `:871` — **leave the eight runtime-mutated globals at `:89-108` and `_rng`/`_rng_local` in place**, and add one re-export line at the top import block: `from .settings import (PROXY_PORT, PROXY_MAX_RETRIES, PROXY_INITIAL_DELAY, PROXY_MAX_DELAY, PROXY_MAX_BODY_SIZE, PROXY_MAX_RESPONSE_SIZE, PROXY_LOG_ALL, PROXY_TRACE_FILE, PROXY_KEYS_PATH, DEFAULT_CONFIG_PATH, CONFIG_TEMPLATE_PATH, MODE_VALUES, STATE_FILE, PROXY_FEATURE_COMPAT_FILE)`. No read site changes — all 48 sites keep the bare names, now resolving through the re-export. `server.py:747`'s `sinks.configure(trace_path=PROXY_TRACE_FILE, state_path=STATE_FILE)` is untouched and works.
   → coder verify (auto): `settings.py` exists; `server.py` contains no `def _env_int` / `def _env_str` and no `^PROXY_PORT =`-style definition of any of the 14 names; the re-export line is present; `python -c "import claude_retry_proxy.server, claude_retry_proxy.settings as s; [getattr(s, n) for n in [...]]"` resolves all 14 on both modules
   → coder verify (scripted): `./tmp/verification/2026-09-16-extract-settings-step1.py` — asserts: the derivation block appears in `settings.py` **verbatim** (pinned fidelity check); all 14 names re-exported from `server.py` resolve to the identical object as `settings.py`'s (`server.X is settings.X` for every name); the eight runtime globals and `_rng` still resolve on `server` and not on `settings`; `settings.py` imports nothing from `claude_retry_proxy` (stdlib-only leaf); both modules import cleanly
   → tester verify: existing suite green (Step 1 has no behavioral change — every read site is byte-identical)

2. **Step 2:** Introduce the object and do the rename. In `settings.py`: wrap the values in `ProxySettings` — a plain class whose `__init__` performs exactly the derivations the module-level names do today (same order, same expressions, `_env_int`/`_env_str` become its private helpers or module privates called from `__init__`), instantiated once as `SETTINGS = ProxySettings()`. Attributes per the mapping table plus `.proxy_dir`. Module docstring states the mutation contract: derived at import from env; `main()` is the only production writer (port / trace_file / log_all, at startup); tests may write attributes in place. `__all__ = ["SETTINGS", "ProxySettings", "resolve_trace_file"]`. Add `resolve_trace_file(log_arg)` exactly as pinned in Guidance for Coder (call-time env read). In `server.py`: replace the re-export line with `from .settings import SETTINGS, resolve_trace_file`; rename all 50 read sites per the mapping table (including the module-level `sinks.configure` call at `:747` — its two path keywords) — pure mechanical substitution, no line-order or control-flow changes. `main()` deltas (current `server.py:3563-3578`): delete **only the first** `global` statement (`global PROXY_PORT, PROXY_TRACE_FILE, PROXY_LOG_ALL`) — the second (`global _current_config, _vendors, _config_path, _startup_state`) **stays**: those four names remain module globals this wave (`main()` assigns them at `:3612`, `:3619`, `:3620`, `:3669`; `do_POST`, `forward_request` and `heartbeat_loop` read them — deleting the declaration would make the assignments function-locals and silently leave the module globals `None`). Replace the `args.port`/`args.log`/`args.all` blocks with `if args.port is not None: SETTINGS.port = args.port` / `SETTINGS.trace_file = resolve_trace_file(args.log)` / `if getattr(args, "all"): SETTINGS.log_all = True`; `sinks.configure(trace_path=SETTINGS.trace_file, state_path=SETTINGS.state_file)`; `config_path = args.config_path or SETTINGS.config_path`; `keys_path = args.keys_path or SETTINGS.keys_path`. The two remaining `STATE_FILE` reads in `main()`'s error messages (`:3665`, `:3714`) become `SETTINGS.state_file`.
   → coder verify (auto): `grep -nP '(?<!\$)\b(PROXY_PORT|PROXY_MAX_RETRIES|PROXY_INITIAL_DELAY|PROXY_MAX_DELAY|PROXY_MAX_BODY_SIZE|PROXY_MAX_RESPONSE_SIZE|PROXY_LOG_ALL|PROXY_TRACE_FILE|PROXY_KEYS_PATH|DEFAULT_CONFIG_PATH|CONFIG_TEMPLATE_PATH|STATE_FILE|PROXY_FEATURE_COMPAT_FILE|MODE_VALUES)\b' src/claude_retry_proxy/server.py` returns nothing (the negative lookbehind keeps the two argparse help strings — they say `$PROXY_PORT`, the only sanctioned text mentions — from false-positives); `python -c "import claude_retry_proxy.server as srv; print(srv.SETTINGS.max_delay)"` works
   → coder verify (scripted): `./tmp/verification/2026-09-16-extract-settings-step2.py` — AST-based: **zero** `Name` loads of the 14 legacy names in `server.py`; every `SETTINGS.<attr>` load resolves to one of the pinned attribute names; exactly two `sinks.configure(trace_path=SETTINGS.trace_file, state_path=SETTINGS.state_file)` call sites (module level `:747` and `main()`); `main()` holds **no `global` statement naming any of the 14 legacy names** (other globals — the runtime-state names — are legal and expected to remain); `hasattr(server, <legacy-name>)` is False for all 14; `server.SETTINGS is settings.SETTINGS`; `import claude_retry_proxy.server` and `python -m claude_retry_proxy.server --help` both succeed. **Baseline discipline:** the script must fail pre-change on exactly the 50 not-yet-done sites and on none of the counts that should already hold
   → tester verify: none at this boundary (Steps 2 and T1–T2 are one reviewable unit; the tree is expected red until T2 completes — do not run the suite as a gate here)

3. **Step 3:** De-duplicate `cli.py` onto the settings module. Delete `HOME`, `PROXY_DIR`, `PROXY_STATE_FILE`, `CONFIG_FILE`, `KEYS_FILE`, `_src_root`, `CONFIG_TEMPLATE_PATH` (`cli.py:18-24`), the mirror comment block and `TRACE_FILE_DEFAULT` (`:26-28`), and `def resolve_trace_path` (`:140-150`). Add `from .settings import SETTINGS, resolve_trace_file` and five aliases: `PROXY_DIR = SETTINGS.proxy_dir`, `PROXY_STATE_FILE = SETTINGS.state_file`, `CONFIG_FILE = SETTINGS.config_path`, `KEYS_FILE = SETTINGS.keys_path`, `CONFIG_TEMPLATE_PATH = SETTINGS.config_template_path`. **Keep `PRUNE_RETENTION_DAYS`** — it is the CLI's own prune policy, not a server setting. Re-point the single `resolve_trace_path(parsed.log)` call site (`cli.py:487`) to `resolve_trace_file(parsed.log)`. Change argparse's `--port` default (`cli.py:359-360`) to `default=SETTINGS.port` with help text "(default: $PROXY_PORT or ...)". **These two env-surface deltas are the plan's declared semantic changes** (asymmetry 4 in Guidance for Coder) — implement them as specified; do not "compensate" by re-hardcoding. Do not touch any other cli.py code — the ~30 alias-usage sites stay byte-identical.
   → coder verify (auto): `cli.py` contains no `os.environ.get`, no "MUST mirror", no `TRACE_FILE_DEFAULT`, no `def resolve_trace_path`; `resolve_trace_file(parsed.log)` is the only resolver call site
   → coder verify (scripted): `./tmp/verification/2026-09-16-extract-settings-step3.py` — asserts: `cli.PROXY_STATE_FILE == settings.SETTINGS.state_file` (and the other four aliases), `cli.py`'s `--port` argparse default equals `SETTINGS.port`, no legacy env reads remain in `cli.py`, `settings.py` still imports no `claude_retry_proxy` module, and `import claude_retry_proxy.cli, claude_retry_proxy.server, claude_retry_proxy.settings` all succeed together (no circular import)
   → tester verify: existing suite green (Step 3 changes only where the CLI's values come from, not what they are — the suite's CLI tests are the check)

## Guidance for Tester (steps)

1. **Step T1:** Create `tests/test_settings.py` (permanent) with the four cases listed in "Guidance for Tester", and register it in the suite aggregator (`tests/test_claude_proxy.py`): `from test_settings import ALL_TESTS as SETTINGS_TESTS` + append to `ALL_TESTS`.
   → tester verify: `tests/test_settings.py` passes when run alone; `python tests/test_claude_proxy.py --list` includes the new test names

2. **Step T2:** Re-point the legacy-name patches: `tests/test_retry_streaming.py` region 2769-2816 (three names, saved-tuple shape preserved), `tests/test_compat.py` six sites (561, 564, 576, 949, 952, 974), and `tests/test_config_keys.py:294`. Preserve every assertion — change only the patched object. **Every re-pointed save/assign must restore inside `try/finally`** — a raise between save and restore leaks mutated `SETTINGS` attributes into the whole shared suite (the patch-coherence hazard the object design exists to close; a bare end-of-test restore is not acceptable). Confirm each site by reading the surrounding block, not just the line. Then run the repo-wide zero-count script and the full suite.
   → tester verify: full suite green; `python ./tmp/verification/2026-09-16-extract-settings-t2.py` PASS — an AST-based zero-count for legacy-name loads (bare and `srv.<legacy>` attribute form) across `tests/`; per the token-not-text rule, comments cannot false-fail it and wrapped/dynamically-built references cannot false-pass it (a missed site fails loudly instead of going inert)
   → tester verify: the two declared env deltas behave as specified — a subprocess `claude-retry-proxy start` with `$PROXY_PORT` set and no `--port` binds the env port; with `$PROXY_KEYS_PATH` set, the start path validates the env-selected keys file (neither var is set by the harness, so these are new assertions, not reworded ones)

3. **Step T3:** Full-suite gate. Re-count at session start — the previous plans' totals are snapshots, not constants. Record pre-change per-module counts, then confirm every module except the ones this plan changes is unchanged, and that the aggregate moves by exactly the number of genuinely new `test_settings.py` tests. Run twice to shake flake; confirm the unit `test_retry_path_print_failure_does_not_misclassify` and the compat save/restore cases ran (they exercise the re-pointed patches). The suite also covers what no script here does: `tests/test_cli.py`'s startup abort tests drive `main()` in a subprocess through the real `SETTINGS` + `sinks.configure()` startup path, so a miswired default or a dropped `resolve_trace_file` fails there.
   → tester verify: unchanged totals for all other modules; aggregate delta = the new-test count; suite green across two consecutive runs; session report with `overall_result: "SUCCESS"`

## Guidance for Planner

Documentation tasks you will execute yourself (not the coder):

- **Doc files to create/update:** `CLAUDE.md`, `doc/test-catalog.html`, `doc/configuration.html`. Verify-only: `README.md` (env-var *names* are unchanged — expect no edit), `doc/architecture.html:51` (prose only, still true), `doc/trace-log.html`, `doc/compatibility.html:35` (still true — the compat constants remain in `server.py` this wave). **The repo-local `.claude/cluster-extraction-criteria.md` is deleted** (2026-09-16 consolidation) — do not re-create it, and do not amend `~/.claude/guides/refactor-split-guidance.md`: it is cross-repo doctrine; this plan's §5 override is recorded in `## Document Overrides` and in CLAUDE.md's settings entry instead.
- **When:** after the coder finishes, and final verification after the tester reports `overall_result: "SUCCESS"`.
- **What to sync:**
  - **CLAUDE.md Structure tree** — add `settings.py` ("env-derived settings singleton: `SETTINGS` value object built at import, trace-path resolver `resolve_trace_file`, the `PROXY_*` values, runtime paths — shared by the server and the CLI") and update the `server.py` line's parenthetical if it lists concerns that left (it does not currently — verify).
  - **CLAUDE.md Gotchas → "Test suite is safe alongside a live proxy"** — "both bind those env vars to module constants at import time" is now "`settings.py` binds them at import time" (both `cli.py` and `server.py` import `settings.py`). The env-at-import contract itself is unchanged.
  - **CLAUDE.md Future Work → TODO** — the staged-decomposition sentence gains step 3: settings extracted with the `SETTINGS` object; `server.py` wc re-measured after the plan (do not guess — `wc -l` at implementation) and `cli.py` path derivation unified onto `settings.py`.
  - **`doc/test-catalog.html`** — both duties, in the same commit as the tests: (1) the `:61` sentence "`cli.py` and `server.py` bind" → "`settings.py` binds (imported by both `cli.py` and `server.py`)"; (2) **the per-test inventory** (see its "maintained by hand, and nothing verifies it" reconcile rule): a `test_settings.py` section in the catalog table (module + test count) and **one entry per new test** — `test_env_int_fallback_semantics`, `test_env_str_fallback_semantics`, `test_settings_object_shape`, `test_resolve_trace_file_chain` — plus the aggregate test-count snapshot re-counted from the tester's session report (the doc demands a re-count before quoting; do not guess).
  - **`doc/configuration.html` (Environment Variables section intro, ~line 268)** — today it says the env values are "read by the server process at import time"; after this plan `settings.py` derives them at import and **both** `claude_retry_proxy.server` and `claude_retry_proxy.cli` import it. Update the sentence. Also note the two declared deltas live on this env surface — one sentence where the CLI's `--port`/keys resolution is described, if the doc covers the CLI there.
  - **The superseded repo-local criteria file is deleted; the survey is its replacement** (consolidation 2026-09-16, recorded in CLAUDE.md's Refactoring + Future Work sections). The §7/§5 workflows it previously carried are re-pointed: (1) the per-repo extraction-order/backlog record is now the `/refactor-split` survey — run it once after this plan lands and record the post-round `server.py` line count in `## Final Results` (the survey derives the remaining scope itself; nothing in `~/.claude/` stores per-repo progress to update); (2) the §5 override stays declared in `## Document Overrides` and in CLAUDE.md's settings entry — the global guide's text is not amended (cross-repo doctrine; the deleted local doc's specific had no global home).
  - **Do not** edit the `## Unresolved Deferred Issues` JSON block — `/update-and-commit` Step 9.9 is its sole writer. Do not edit `tmp/reports/defer-issue-break-up-large-source-and-test-files.json` — it stays `Open` until the source and test splits are all done.
  - **Do not** claim the file-size problem is addressed — one of four+ source clusters remains to leave.

## History

| Date | Event | Conclusion | Dismissed |
|------|-------|------------|-----------|
| 2026-09-16 | Initial plan | Extract the settings cluster (14 names, 50 read sites incl. the module-level `sinks.configure`, 25 in the risk zone) into `settings.py` as a `SETTINGS` value object with the shared `resolve_trace_file` chain; Step 2 renames all read sites (tester re-points 22 reference sites across 4 test files); Step 3 de-duplicates `cli.py`'s mirrored path derivation. | — |
| 2026-09-16 | Mega-audit (pre-implementation, iteration 1 of 3) | 27 findings: **4 High** / 8 Medium / 15 Low — verdict "plan needs revision". All 4 High and all 8 Medium fixed. Highs: the load-bearing second `global` statement is kept (Step 2 now deletes only the `PROXY_*` line; script gate narrowed to legacy-named globals); T2's grep gate re-engineered as the AST script `t2.py`; test-catalog reconciliation scheduled; the Step-3 env deltas declared as asymmetry 4 and user-confirmed (KEYS_FILE unify = Option A, 2026-09-16). Mediums: KEYS_FILE/`--port` deltas declared; `--log ""` edge declared; try/finally restore discipline mandated + risk row; metadata 48→50 synced; criteria-§5 amendment and `configuration.html:268` edit scheduled; the `t2.py` pre-change run surfaced `tests/test_unit.py`'s 6 bare-name sites (22 total, first inventory undercounted). Highs remaining: **0** — below the 3-High re-audit threshold. Report: `./tmp/reports/2026-09-16-extract-settings-mega-audit-2026-09-16.json`. | Lows acknowledged, not fixed (represented as chapters in the report): [6] rollback coverage is already adequate; [13] the 25-vs-24 risk-zone count reconciles via the planned §7 re-measure; [18] verified false — `:3159`/`:3192` sit inside `do_POST`'s span (`3145-3534`), so the scan's `do_POST ×3` attribution stands; [19] the `(?!\$)` auto-grep can false-fail on legitimate docstring mentions — the scripted AST gate is authoritative; [20] the 22-site break during the red interval is the planned risk, not a defect; [22] module-surface change accepted and counted in Summary (no doc referenced the 14 names); [23] `proxy_dir` derivation is value-identical to today's two derivations; [24] `test_settings` env mutations are in-process and restored in `finally`; [2][4][7][12][14][17][21] were fixed by this round's edits (declared deltas, 48→50 sync, five-case wording, straggler fidelity note). |
| 2026-09-16 | Spec revision (/update-plan) | Coder round 1 reported: Step 1 green (step1.py PASS), Step 2 implemented but its scripted gate hit a planner-authored check defect — the `abs_arg` fixture was relative on every platform, making the isabs pass-through assertion unsatisfiable against the pinned resolver (`step2-abs-arg-check-unsatisfiable`). Fixed the fixture to a cwd-rooted absolute path; re-ran the gate against the coder's tree (exit 0, every condition passes — Step 2's implementation verified complete) and `step3.py` (fails on exactly the not-yet-done cli conditions). Issue Log entry added; Immediate Actions re-issued for the coder (re-run step2 gate, complete Step 3, single-unit commit discipline). | — |
| 2026-09-16 | Spec revision (/update-plan) | Tester round reported `overall_result: "SUCCESS"`: 322/322 on two consecutive runs, aggregate 318→322 = exactly the 4 new `test_settings.py` tests, T2 AST gate PASS, both declared env deltas subprocess-verified (which also evidences the coder's unrecorded Step 3 — planner-run `step3.py` PASS confirms). Doctrine references re-pointed from the deleted repo-local criteria file to the global guide + `/refactor-split` survey; Document Overrides and Metadata re-pointed; the retired `break-up-large-source-and-test-files` defer-issue (now Resolved by the 2026-09-16 consolidation) noted for the Final-Results cross-reference. Report: `./tmp/reports/2026-09-16-extract-settings-tester-2026-09-16.json`. | — |
| 2026-09-16 | Phase 6 review (implementation, adversarial) | **0 Critical / 0 Warning / 2 Suggestion** — verdict "Issues found — non-blocking". Report: `./tmp/reports/2026-09-16-extract-settings-review-2026-09-16.json`. The reviewer independently confirmed every hunt item: the state_file raw-`os.environ.get` passthrough verbatim, `_env_int`'s three-branch fallback byte-identical, the resolver's `if log_arg:` truthiness + call-time env read, the load-bearing second `global` retained in `main()`, both asymmetry-4 deltas exactly as pinned, `settings.py` a stdlib-only leaf; re-ran all 5 gates and the full suite (322/322). | Accepted as non-blocking, not fixed: [2 cli-dead-HOME](tmp/reports/2026-09-16-extract-settings-review-2026-09-16.json) — `cli.py:19` `HOME` is dead (plan Step 3 listed it for deletion; the step3 gate does not assert its absence) and [1 abs-log-guarded-assert](tmp/reports/2026-09-16-extract-settings-review-2026-09-16.json) — `test_settings.py:158` guards its absolute-`--log` assertion with `if os.path.isabs(...)`, silently self-skipping in a hypothetical non-absolute-cwd run; unconditional assert preferred. Also noted: `step1.py` now fails only on its own obsolete Step-1 intermediate-state conditions (stale-by-design once the plan moved past Step 1) — recorded here rather than re-audited. |

## Plan Metadata

```json
{
  "plan_id": "2026-09-16-extract-settings",
  "steps": ["Step 1: Create settings.py (verbatim move + re-exports)", "Step 2: Introduce the SETTINGS object and rename all 50 read sites", "Step 3: De-duplicate cli.py onto the settings module"],
  "coder_files": ["src/claude_retry_proxy/settings.py", "src/claude_retry_proxy/server.py", "src/claude_retry_proxy/cli.py"],
  "tester_files": ["tests/test_settings.py", "tests/test_retry_streaming.py", "tests/test_compat.py", "tests/test_config_keys.py", "tests/test_unit.py", "tests/test_claude_proxy.py"],
  "doc_files": ["CLAUDE.md", "doc/test-catalog.html", "doc/configuration.html"],
  "verification_scripts": ["./tmp/verification/2026-09-16-extract-settings-step1.py", "./tmp/verification/2026-09-16-extract-settings-step2.py", "./tmp/verification/2026-09-16-extract-settings-step3.py", "./tmp/verification/2026-09-16-extract-settings-t2.py", "./tmp/verification/2026-09-16-extract-settings-t2-env-deltas.py"],
  "repo_mode": "Public",
  "document_overrides": ["~/.claude/guides/refactor-split-guidance.md §5: SETTINGS is derived at import from env, not built in main() (Reason: preserves the repo's documented env-at-import test contract; declared upgradeable later)"]
}
```

## Audit Accumulation

*Counters reset when mega-audit runs. Used by Phase 5 entry trigger.*

| Counter | Value | Last Updated |
|---------|-------|--------------|
| issues_resolved_since_audit | 1 | 2026-09-16 |
| steps_changed_since_audit | 0 | 2026-09-16 |
| files_changed_since_audit | 0 | 2026-09-16 |

## Documentation

- [CLAUDE.md](CLAUDE.md) — Structure gains `settings.py`; the env-binding Gotcha re-pointed; Future Work/TODO staged-decomposition updated with step 3 and re-measured wc.
- `~/.claude/guides/refactor-split-guidance.md` — referenced via Document Overrides, not amended (cross-repo doctrine; the superseded repo-local criteria file is deleted). The extraction-order record now lives in the `/refactor-split` survey, run post-landing.
- `doc/test-catalog.html` — the env-binding sentence names `settings.py`; `test_settings.py` added to the catalog table and the per-test inventory (4 entries); aggregate 318 → 322 across 17 → 18 files; the `configuration.html` env-vars intro names the `settings.py` import and the both-processes behavior.

## Final Results

**Status:** COMPLETED — commit pending (owned by `/update-and-commit`).
**Completed:** 2026-09-16 (coder Steps 1–3, tester T1–T3, Phase 6 review, doc reconciliation).

**Files changed**

| File | Change |
|------|--------|
| `src/claude_retry_proxy/settings.py` | **created** (82 wc) — `ProxySettings` + `SETTINGS` singleton, `resolve_trace_file`, stdlib-only leaf |
| `src/claude_retry_proxy/server.py` | modified (3,719 → 3,661 wc) — derivation block and 3 straggler defs removed; 50 read sites renamed to `SETTINGS.<attr>`; `main()` drops the `PROXY_*` globals only, keeps the runtime-state global |
| `src/claude_retry_proxy/cli.py` | modified (868 → 852 wc) — 5 aliases onto `SETTINGS`, mirror resolver deleted, `--port` default from `SETTINGS.port` |
| `tests/test_settings.py` | **created** — 4 permanent tests |
| `tests/test_retry_streaming.py` | modified — saved-tuple patch re-pointed to `srv.SETTINGS.*` |
| `tests/test_compat.py` | modified — 6 `PROXY_FEATURE_COMPAT_FILE` sites → `srv.SETTINGS.feature_compat_file` |
| `tests/test_config_keys.py` | modified — `srv.STATE_FILE` → `srv.SETTINGS.state_file` |
| `tests/test_unit.py` | modified — bare legacy-name import dropped; 6 comparisons → `SETTINGS.initial_delay/max_delay` |
| `tests/test_claude_proxy.py` | modified — `test_settings` registered in the aggregator |
| `CLAUDE.md`, `doc/test-catalog.html`, `doc/configuration.html` | modified — see Documentation above |

**Test results.** 322 passed, 0 failed, 0 skipped — **three** full-suite runs: the tester's two consecutive (flake check), plus the reviewer's independent run. Baseline 318 → 322; the +4 is exactly the new `test_settings.py` tests, every other module unchanged. All gates: `step1.py` PASS, `step2.py` PASS, `step3.py` PASS, `t2.py` PASS (AST zero-reference across `tests/`), `t2-env-deltas.py` PASS (both declared deltas subprocess-verified). The planner independently re-ran step2/step3/t2 (exit 0) after the tester round. The suite's only warning is the known pre-existing `no proxy_stop event` note (deferred issue `no-proxy-stop-trace-warning`).

**Module-surface changes.** The 14 legacy settings names stop resolving on the `server` module (`hasattr` asserted False); `SETTINGS`, `ProxySettings`, `resolve_trace_file` appear on `settings` and are re-bound on `server`. Behavioral changes: **0** beyond the two declared Step-3 env deltas (`$PROXY_PORT`/`$PROXY_KEYS_PATH` now also honored by `claude-retry-proxy start`, user-confirmed 2026-09-16) and the declared `--log ""` edge on the server side, each carried by a dedicated test assertion.

**Issues.** One issue found and fixed (`step2-abs-arg-check-unsatisfiable`, planner-authored verification-script defect) — the only mid-implementation issue; Resolved by the planner with gate-run evidence.

**Survey (post-landing, /refactor-split).** `server.py` 3,661 wc — still the only code file over the 1,000-line threshold; remaining clusters: compat, router/forwarder, admin/handler. Test files over the 1,500-line threshold: `test_retry_streaming.py` (2,852), `test_compat.py` (2,449), `test_chat_sse.py` (1,674) — the test-side split is a separate plan.

**Known caveats.**
- Round-2 coder left no session report; Steps 2–3 completion is evidenced by the planner-run gates (step2/step3 PASS) and the tester's end-to-end env-delta subprocess checks.
- Reviewer Suggestion (accepted, not fixed): `cli.py:19` `HOME` is now dead — plan Step 3 listed it for deletion but no gate asserts its absence.
- Reviewer Suggestion (accepted, not fixed): `test_settings.py:158` guards its absolute-`--log` assertion with `if os.path.isabs(...)`, silently self-skipping under a hypothetical non-absolute cwd; an unconditional assert (or an `else: fail(...)`) is preferred.
- Reviewer hunch (accepted): `step1.py` now fails only on its own obsolete Step-1 intermediate-state conditions — stale-by-design once the plan moved past Step 1; superseded by step2/step3/t2 for any later re-verification.
- Pre-existing suite warning: `No proxy_stop event in trace` — tracked deferred issue `no-proxy-stop-trace-warning`.

## Cross-References to Prior Plans

| Prior Plan | Deferred Issue | Resolution |
|------------|---------------|------------|
| defer-issue-break-up-large-source-and-test-files | "Break up large source and test files into smaller modules" | This plan extracted the settings cluster (a tracked cluster of that report's `server.py` decomposition) into `settings.py`; the report itself was retired 2026-09-16 by the global refactor-split consolidation (survey-tracked state), so the backlog entry it carried is closed in place. |