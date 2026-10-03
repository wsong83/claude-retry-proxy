# Plan: Isolate the test suite's state file per run so a recycled PID cannot wedge the suite

**Project:** D:\proj\claude-retry-proxy ($PWD)
**Plan ID:** 2026-10-03-stale-test-state-file-pid-reuse
**Created:** 2026-10-03
**Revised:** 2026-10-03 (revision 1 — the round's implementation landed but stalled: the tester was killed at the 3600 s launcher cap mid-suite and wrote no session report, and the planner's Step 4 never ran. Independent verification of the landed diff found Step 2's fix **incomplete** — it patched only the three wrapper closures, while the actual leak flows through `_start_proxy_server_directly` (the shared spawn helper, 31 call sites) which it did not touch; a per-run state file was reproduced left in `%TEMP%` after a `test_config_keys` run. Step 2 is corrected to remove the file at the single point every module shares, `run_cli`'s per-test loop; Step 4's doc counts are corrected to 363 / 16.)

## Immediate Actions

**Tester — Step 5 only.** The Phase 6 review returned 0 Critical / 2 Warning / 3 Suggestion. Two were doc defects and the planner has already fixed them. The three remaining findings are yours, all in files this plan already owns. Do not re-implement Steps 1–4; they are landed and verified.

1. Fix `review-guard-posix-hard-kill`: in `tests/test_cli.py`'s `leak_test` (inside `test_run_cli_loop_clears_direct_spawn_state_file`), change `proc.terminate()` to `proc.kill()` so the hard-kill premise holds on POSIX too (SIGKILL) as well as Windows (TerminateProcess). Make the same change in `tmp/verification/2026-10-03-stale-test-state-file-pid-reuse-step2.py`'s `CHILD_RUN_CLI`. Leave pre-existing `terminate()` call sites in unmodified test bodies alone.
2. Fix `review-removal-helper-duplication`: extract a module-level `_remove_test_state_file()` helper in `tests/_harness.py` (guarded `os.remove(PROXY_STATE_FILE)` + the shared rationale comment) and call it from all four sites (`:648`, `:745`, `:986`, `:1332`). **The `run_cli` call must stay in its current position** — after `func()`, before the pass/fail tally. Update the Step 2 gate's Part A textual checks in the same change, or they will fail on the refactor (Part A looks for the literal `os.remove(PROXY_STATE_FILE)` inside each closure body and the `run_cli` body).
3. Fix `review-import-removal-comment`: the comment at `tests/_harness.py:81-89` claims a failed import-time removal is "reported by the tests that assert on the path" — no test does. Prefer adding the guard: assert no file exists at `PROXY_STATE_FILE` at import time. If that proves flaky, reword the comment to name what actually surfaces the symptom (the CLI start tests' PID-gate refusal).
4. Re-run both gates (`…-step1.py`, `…-step2.py` — both must exit 0) and the full suite (background, then **wait for it — do not end your turn while it runs**). Confirm no new per-run state file.
5. Write a fresh session report `./tmp/reports/2026-10-03-stale-test-state-file-pid-reuse-tester-2026-10-04.json` covering Step 5 only.

**Planner:**
- After the round: resolve Step 5's three Issue Log rows, re-run the Phase 6 reviewer on the new diff, then write `## Final Results` and present for commit approval.

## Issue Log

Rows ordered newest-first (latest issues at top). New issues are prepended; resolved issues stay in place with updated status.

| Issue | Status | Found | Resolved | Resolved By |
|-------|--------|-------|----------|-------------|
| [review-guard-posix-hard-kill](./tmp/reports/2026-10-03-stale-test-state-file-pid-reuse-review-guard-posix-hard-kill.json) | Resolved | 2026-10-04 | 2026-10-04 | [tester round 7](./tmp/reports/2026-10-03-stale-test-state-file-pid-reuse-review-2026-10-04.json) — `proc.kill()` now used in both new-guard sites (`tests/test_cli.py:1520`, gate `CHILD_RUN_CLI`), so the hard-kill premise holds on POSIX (SIGKILL) as well as Windows; confirmed by the Phase 6 re-review, which re-ran both gates. |
| [review-import-removal-comment](./tmp/reports/2026-10-03-stale-test-state-file-pid-reuse-review-import-removal-comment.json) | Resolved | 2026-10-04 | 2026-10-04 | [tester round 7](./tmp/reports/2026-10-03-stale-test-state-file-pid-reuse-review-2026-10-04.json) — solved with a real guard rather than a reworded comment: `_STATE_FILE_PRESENT_AFTER_IMPORT` (`tests/_harness.py:109`) captures whether anything survived the import-time removal, and `test_state_file_path_is_per_run_isolated` asserts it is False. |
| [review-removal-helper-duplication](./tmp/reports/2026-10-03-stale-test-state-file-pid-reuse-review-removal-helper-duplication.json) | Resolved | 2026-10-04 | 2026-10-04 | [tester round 7](./tmp/reports/2026-10-03-stale-test-state-file-pid-reuse-review-2026-10-04.json) — `_remove_test_state_file()` (`tests/_harness.py:82`) called from all five plan-introduced sites (`:108`, `:666`, `:763`, `:1003`, `:1345`); the Step 2 gate's Part A rewritten to follow the helper (A0/A1/A2); re-review confirmed no site missed and the `run_cli` ordering preserved. |
| [posix-sigterm-shutdown-deadlock](./tmp/reports/defer-issue-posix-sigterm-shutdown-deadlock.json) | Deferred | 2026-10-04 | — | — (pre-existing: `server.py`'s SIGTERM handler calls `server.shutdown()` on the `serve_forever` thread; reproduced by the planner 2026-10-04, POSIX-only, user chose "defer" on 2026-10-04) |
| [cli-pre-existing-remove-idiom-copies](./tmp/reports/defer-issue-cli-pre-existing-remove-idiom-copies.json) | Deferred | 2026-10-04 | — | — (pre-existing: the 8 hand-rolled guarded-removal blocks in `tests/test_cli.py` test bodies, one file over from the helper Step 5 introduced; user chose "defer" on 2026-10-04) |
| [operate-round-ends-turn-before-waiting](./tmp/reports/defer-issue-operate-round-ends-turn-before-waiting.json) | Deferred | 2026-10-04 | — | — (cross-repo: `target_repo: "claude-config"` — the unattended-round launcher ended its turn with the background suite in flight in 4 of this plan's 7 rounds; not a claude-retry-proxy defect) |
| [step2-leak-incomplete-direct-spawn](./tmp/reports/2026-10-03-stale-test-state-file-pid-reuse-step2-leak-incomplete-direct-spawn.json) | Resolved | 2026-10-03 | 2026-10-03 | [tester round 6](./tmp/reports/2026-10-03-stale-test-state-file-pid-reuse-tester-2026-10-03.json) — `run_cli` loop removal landed (round 5) and verified: Step 2 gate Part C (direct spawn through `run_cli`, file gone) exit 0, `test_config_keys` 17/17 leaving no leftover, full suite 364/364 leaving no leftover. |
| [step2-closure-list-incomplete](./tmp/reports/2026-10-03-stale-test-state-file-pid-reuse-step2-closure-list-incomplete.json) | Resolved | 2026-10-03 | 2026-10-03 | [tester round 6](./tmp/reports/2026-10-03-stale-test-state-file-pid-reuse-tester-2026-10-03.json) — superseded framing defect; the chokepoint replaces the closure-list approach, so no future helper can silently re-open the leak. Same verification as the row above. |
| [tester-round-killed-no-report](./tmp/reports/2026-10-03-stale-test-state-file-pid-reuse-tester-round-killed-no-report.json) | Resolved | 2026-10-03 | 2026-10-03 | [tester round 6](./tmp/reports/2026-10-03-stale-test-state-file-pid-reuse-tester-2026-10-03.json) — the missing session report now exists with `overall_result: "SUCCESS"`; rounds 3–5 produced none (round 5 landed the changes but ended its turn with its suite in flight). The Immediate Actions were rewritten to warn against that exact failure mode. |
| [stale-test-state-file-pid-reuse](./tmp/reports/defer-issue-stale-test-state-file-pid-reuse.json) | Resolved | 2026-10-03 | 2026-10-03 | [tester round 6](./tmp/reports/2026-10-03-stale-test-state-file-pid-reuse-tester-2026-10-03.json) — per-run state path + import-time removal + `run_cli`-loop chokepoint; the original failure (`test_start_rejects_uncatalogued_model_selector_at_cli` refused by a recycled dead PID) can no longer be fed by a completed run. Deferred-issue close-out is Step 4. |

## Guidance for Coder

**Files to modify:** none — this plan changes no source code and no product behavior.

The defect's only required fix is in test infrastructure (`tests/_harness.py`), which is the tester's lane. The product-side hardening that would also make `cli.py`'s `is_pid_alive()` gate robust against a recycled PID was **explicitly declined by the user on 2026-10-03** (won't-fix; see Summary → "Out of scope"). Do not touch `cli.py`, `server.py`, or any other source file.

## Guidance for Tester

**Files to modify:** `tests/_harness.py`, `tests/test_cli.py`

**Tests to create:**
- **Permanent:** `test_state_file_path_is_per_run_isolated` (in `tests/test_cli.py`; place it near the other state-file tests) — asserts the harness state path is per-run unique: its basename matches `claude-retry-proxy-test-state-<runner_pid>.json` for the current runner pid, and is therefore distinct from the legacy fixed name `claude-retry-proxy-test-state.json`. This is the regression guard against a future revert to a fixed machine-global path. **Landed** (verified: `python tests/test_cli.py` → 16 passed, 0 failed).
- **Permanent:** a regression guard for Step 2's chokepoint — after a direct `_start_proxy_server_directly` spawn inside a `run_cli`-driven test, no file remains at `PROXY_STATE_FILE`. This is the guard the original closure-list fix lacked; without it a future revert of the `run_cli`-loop removal would go unnoticed. Place it in `tests/_harness.py`'s verification path or as a `test_cli` test that spawns directly.
- **Temporary:** none.

**Tests to investigate for retirement:**
- Planner candidates: **none.** No test is tied to the fixed path — a repo-wide search for `claude-retry-proxy-test-state.json` returns only `tests/_harness.py` (the definition) and one historical plan document. The `tests/test_cli.py:1041-1077` test that patches `cli_mod.PROXY_STATE_FILE` to its own temp file is unaffected (it overrides the constant itself).
- Tester may identify additional candidates during test work.

**Retirement procedure:** For each candidate, verify the test exercises code being removed/changed. If obsolete: delete and note in session report. If still valid: document why in session report.

**Step-by-step with verification:**

1. **Step 1:** In `tests/_harness.py`, make the state-file isolation path per-run and self-cleaning.
   - Replace the fixed path at `:45-46` (`os.path.join(tempfile.gettempdir(), "claude-retry-proxy-test-state.json")`) with `os.path.join(tempfile.gettempdir(), "claude-retry-proxy-test-state-%d.json" % os.getpid())`. **Use this exact form** — the Step-1 gate and the Step-3 test both assert the `claude-retry-proxy-test-state-<runner-pid>.json` basename, so a different scheme (`mkstemp`, a uuid, etc.) would fail them. The discriminator must be **per-process (runner PID), not per-test** — the path has to stay identical for the in-process harness, every spawned CLI subprocess, and every spawned server, because they all inherit it through `os.environ.copy()` (the harness comment at `:68-70` states this requirement).
   - Immediately after `PROXY_STATE_FILE = os.environ["PROXY_STATE_FILE"]` (`:70`), best-effort remove any pre-existing file at that path (`try: os.remove(PROXY_STATE_FILE) except OSError: pass`), so every run starts from a clean slate instead of inheriting the previous run's entry through `_backup_proxy_state()` / `_restore_proxy_state()`.
   - **Leave alone:** `_backup_proxy_state()` (`:125`) and `_restore_proxy_state()` (`:135`) — they still guard against a file created earlier in the *same* run and must not be removed.
   → tester verify (scripted): `./tmp/verification/2026-10-03-stale-test-state-file-pid-reuse-step1.py` — run from the repo root, no arguments. Part A confirms the path carries a per-process discriminator; Part B plants a stale file at the harness path in a child interpreter and confirms re-executing the harness module scope removes it.
   → tester verify: `python tests/test_cli.py` passes (16/16) on a machine where a stale fixed-name file exists, and the state file created during the run carries the runner PID in its name.

2. **Step 2:** In `tests/_harness.py`, remove the per-run state file at the **single point every test shares** — the per-test loop in `run_cli` (`:1312-1329`), after `func()` returns and before the pass/fail tally.
   - **The landed round patched the wrong layer.** It added `os.remove(PROXY_STATE_FILE)` to three wrapper `cleanup()` closures only: `_setup_tier_routing_test` (`:641`), `_start_admin_proxy` (`:742`), `_start_mode_proxy` (`:983`). Those cover the wrapper tests, but the actual leak flows through `_start_proxy_server_directly` (`:415`) — the shared spawn helper called **directly** at 31 sites across `test_config_keys` (12), `test_admin` (5), `test_cli` (6), `test_tier_routing` (2), `test_retry_streaming` (2), `test_chat_sse` (2) — whose tests never call a wrapper `cleanup()`. Reproduced on 2026-10-03: after `python tests/test_config_keys.py`, a file `claude-retry-proxy-test-state-<pid>.json` remained in `%TEMP%`, written by the spawned server (a different pid than the runner).
   - **Why the closures cannot fix it even if extended to `_start_proxy_server_directly`:** that helper returns `(proc, probe_ok)` and six modules unpack the 2-tuple, so its contract must not change. And a `cleanup()` that removes the file *before* killing the child races the child's own write — the server writes the state file at startup and every 30 s from its heartbeat. Removing the file after the test body has fully returned is the only ordering that is not a race.
   - **The edit:** in `run_cli`'s loop, after the `try/except` around `func()` and before the `if errors:` tally, add a best-effort `try: os.remove(PROXY_STATE_FILE) except OSError: pass`. Every test in every module passes through this loop, so this closes the leak for all of them at once.
   - **Keep the three landed closures** — they are correct, cover the wrapper tests, and cost nothing; do not revert them. **Leave `_start_proxy_server_directly`'s signature alone.**
   → tester verify (scripted): `./tmp/verification/2026-10-03-stale-test-state-file-pid-reuse-step2.py` — extended to three parts. Part A (structural): the three closures *and* the `run_cli` loop each remove `PROXY_STATE_FILE` guarded by `except OSError`. Part B (behavioral): through the real `_setup_tier_routing_test` closure. Part C (behavioral, the regression that matters): a direct `_start_proxy_server_directly` spawn, driven through `run_cli`'s loop, leaves no file.
   → tester verify: after `python tests/test_config_keys.py` (a direct-spawn module) no file remains at `PROXY_STATE_FILE`; and a full-suite run leaves no file at the per-run path.

3. **Step 3:** Add the permanent regression test `test_state_file_path_is_per_run_isolated` to `tests/test_cli.py` and register it in that module's `ALL_TESTS` list. It asserts `os.path.basename(PROXY_STATE_FILE)` equals `"claude-retry-proxy-test-state-{}.json".format(os.getpid())`, i.e. the path is keyed to the runner process and cannot collide across runs or with the legacy fixed name.
   → tester verify: the new test passes alone (`python tests/test_cli.py -t state-file-path-is-per-run-isolated`) and the module's total rises from 15 (pre-plan) to 17 (this plan adds the path test here and the Step 2 chokepoint guard).

4. **Step 4 (planner):** Update `doc/test-catalog.html` and close out the deferred issue in `CLAUDE.md`. Details in "Guidance for Planner".
   → Evidence: diff of `doc/test-catalog.html` showing the isolation section and the "safe alongside a live proxy" note updated; diff of `CLAUDE.md` showing the `stale-test-state-file-pid-reuse` row removed from the `## Unresolved Deferred Issues` JSON index and the `## Future Work — TODO` prose updated (count 8 → 7); `python scripts/check_doc_anchors.py` exits 0.

## Summary

**Problem.** `tests/_harness.py:45-46` pins the suite's state file to one **fixed machine-global** path, `%TEMP%\claude-retry-proxy-test-state.json`. Two consequences compound:

1. **Cross-run inheritance.** The file is never removed at exit, and `_backup_proxy_state()` reads it at test entry while `_restore_proxy_state()` writes it back verbatim at exit, so a dead-proxy PID from a previous run propagates forward.
2. **The CLI start gate cannot tell a recycled PID from a real proxy.** `is_pid_alive()` (`cli.py:46-104`) checks liveness of the PID *number*, and Windows recycles PID numbers aggressively. When the stale number is reused by an unrelated live process, `cmd_start` step 6 (`cli.py:422-428`) prints `ERROR: Proxy already running (PID <n>)` and returns 1.

The observed failure is `tests/test_cli.py::test_start_rejects_uncatalogued_model_selector_at_cli`, whose clean-config sanity start (was `:709-724`) is the only assertion that reaches step 6. **Reproduced deterministically on 2026-10-03**: the leftover file held `{"pid": 1824, ...}`, `is_pid_alive(1824)` returned `True` (a recycled live process), and the test reported `Results: 0 passed, 1 failed` with exactly that error.

**Root cause of the leak (answering "why doesn't the test's `finally` clean up?").** Not a test-side `finally` failure. The harness's shared `cleanup()` uses `proc.terminate()`; on Windows that is `TerminateProcess`, an immediate kill that runs **no** Python cleanup — verified: a child with an `atexit`/`finally` handler left its marker file behind and its cleanup never ran (exit code 1). So the server's own `finally: os.remove(SETTINGS.state_file)` (`server.py:2893-2900`) is unreachable in every direct-spawn test. And the harness cleanup never removes the file itself, because the file lives in `%TEMP%` while the cleanup only `rmtree`s `temp_dir`. Most of the suite spawns servers directly and never calls `stop` (`test_admin` 25 spawns / 0 stops, `test_mode_dispatch` 23/6, `test_config_keys` 15/0, `test_tier_routing` 11/0), so the leak is systematic, not incidental.

**Approach.** Three edits in the harness, one new regression test, one doc update:

```
before:  %TEMP%\claude-retry-proxy-test-state.json        (fixed, machine-global, never removed)
after:   %TEMP%\claude-retry-proxy-test-state-<pid>.json  (per-run, removed at import + after every test)
```

- **Step 1** gives the path a per-process discriminator (stable within the run, so the harness, CLI subprocesses, and servers still agree) and deletes any leftover at import.
- **Step 2** removes the file after every test in `run_cli`'s loop, closing the intra-run leak for **all** modules — including the direct-spawn modules whose tests never call a wrapper `cleanup()`. (The landed round patched only the three wrapper closures; that is a subset, and the leak was reproduced through `_start_proxy_server_directly` after the patch.)
- **Step 3** pins the invariant with a permanent test.
- **Step 4** documents the isolation accurately and closes the deferred issue.

**Alternatives considered.**
- *Delete-at-import only, keep the fixed path* — simpler, but two concurrent runs of this suite would still share one file and clobber each other. Rejected: the per-PID suffix removes that collision for free.
- *Route cleanup through `claude-retry-proxy stop` so the server's `finally` runs* — would make tests slower and would exercise the very gate under test. Rejected.
- *Per-test unique paths* — breaks the harness↔subprocess↔server agreement the comment at `:68-70` requires. Rejected.

**Explicitly out of scope — the declined product fix (user decision, 2026-10-03, won't-fix).** A force-killed production proxy (Task Manager, `taskkill /F`, crash, power loss) also leaves `~/.claude/proxy/proxy-state.json` behind holding a dead PID, and a later `claude-retry-proxy start` can be refused with `Proxy already running` once Windows recycles that PID to an unrelated live process. Three candidate fixes were presented and all were declined:

- **P1 — advisory port probe** (when the state file says "alive", also verify the recorded port serves the admin API). Declined.
- **P2 — identity via OS process creation time** recorded in the state file. Declined.
- **P3 — won't-fix.** Chosen.

Rationale recorded for the record: the production window is narrow (it requires an ungraceful kill, which is outside the supported `claude-retry-proxy stop` path), the consequences are recoverable (delete the stale file, or let `stop` clean up), and process-name matching — the user's suggested alternative — was empirically ruled out because the proxy runs as `python.exe`, indistinguishable from every other Python process. The server's own port-bind guard (`server.py:2826-2833`) already refuses a genuine second proxy. This plan therefore fixes only the test-isolation layer; the production behavior is unchanged and is documented as a known limitation in Step 4.

## Repo Mode

Public

*Detected at plan creation. Determines: plan archival path, commit-message content, staged files.*

## Document Overrides

| Document | Rule Overridden | Reason |
|----------|----------------|--------|

## Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| Per-run state files orphan in `%TEMP%` across runs (each run uses a new name and only removes its own) | Temp-directory clutter; no correctness impact | Accepted for **crashed/killed** runs — a run that is `kill -9`'d cannot remove its own file, and the alternative (a reaper) adds machinery for no functional gain. A **completed** run is now covered by Step 2's `run_cli`-loop removal. Two legacy files from the stalled round's killed runs (`…-test-state.json`, `…-test-state-22912.json`) remain for the user to delete. |
| A test somewhere assumes the fixed state-file name | Silent misread of the wrong file | Planner-verified: a repo-wide search finds the fixed name only in `tests/_harness.py` and one historical plan doc. Step 1's scripted check plus the full-suite run cover it. |
| The `run_cli`-loop removal could delete a file a later test in the same run expects to inherit | Cross-test state bleed or a false pass | Planner-verified: the harness already clears the file at import (`:81-89`), and every test that needs a clean slate calls `_backup_proxy_state()`/`_restore_proxy_state()` itself (all 11 CLI tests, plus `test_config_keys`'s heartbeat test). No test asserts the file *survives* a prior test. The full-suite run is the authoritative check. |
| `importlib.reload` in the Step-1 verification script behaves differently than a fresh process | False pass/fail in the gate | The script also runs Part A (structural) and the tester's behavioral run is the authoritative check; the reload is an additional, not sole, signal. |

## Proposed Changes

Each step includes verification checks tagged with confidence (see Prime Directive 4).
`(auto)` = mechanical, coder self-verifies. `(scripted)` = deterministic multi-step, coder runs provided script.
Every step must have at least one verification check executable by its owner (coder steps: coder checks; tester steps: tester verify; planner steps: Evidence).
Steps MUST use this numbered-list format exactly. The `### Step N:` heading format is deprecated and must not be used.

1. **Step 1:** In `tests/_harness.py`, give the state-file isolation path a per-process discriminator and delete any leftover file at import, keeping the path stable within a run.
   → tester verify (scripted): `./tmp/verification/2026-10-03-stale-test-state-file-pid-reuse-step1.py` (structural check + plant-then-reimport behavioral check), exit 0
   → tester verify: `python tests/test_cli.py` passes 16/16 even with a stale fixed-name file present, and the run's state file carries the runner PID

2. **Step 2:** In `tests/_harness.py`, remove the per-run state file at the **single point every test shares** — the per-test loop in `run_cli` (`:1312-1329`), after `func()` returns and before the pass/fail tally. This is the correction: the landed round patched only the three wrapper `cleanup()` closures (`_setup_tier_routing_test`, `_start_admin_proxy`, `_start_mode_proxy`), but the leak flows through `_start_proxy_server_directly` (`:415`) — the shared spawn helper called directly at 31 sites across `test_config_keys`, `test_admin`, `test_cli`, `test_tier_routing`, `test_retry_streaming`, and `test_chat_sse`, whose tests never call a wrapper `cleanup()`. A direct `_start_proxy_server_directly` spawn writes the state file from a *server child* pid, so a `cleanup()` that removes `PROXY_STATE_FILE` before the child has written it does not close the race either. The `run_cli` loop is strictly after every test body, so the server is already killed and the file (if any) is orphaned.
   **Keep the three landed closures** (they are correct and cover the wrapper tests; do not revert them). **Also leave `_start_proxy_server_directly`'s `(proc, probe_ok)` contract unchanged** — do not add a cleanup there: the six direct-call modules unpack a 2-tuple, and changing the return shape would break them.
   → tester verify (scripted): `./tmp/verification/2026-10-03-stale-test-state-file-pid-reuse-step2.py` (extended: Part A structural — the three closures *and* the `run_cli` loop each remove `PROXY_STATE_FILE` guarded; Part B behavioral — through the real `_setup_tier_routing_test` closure; Part C behavioral — a direct `_start_proxy_server_directly` spawn's file is removed by the `run_cli` loop), exit 0
   → tester verify: after `python tests/test_config_keys.py` (a direct-spawn module) no file remains at `PROXY_STATE_FILE`; and a full-suite run leaves no per-run file

3. **Step 3:** Add the permanent regression test `test_state_file_path_is_per_run_isolated` to `tests/test_cli.py` and its `ALL_TESTS` list, asserting the path is keyed to the runner PID and distinct from the legacy fixed name.
   → tester verify: the new test passes alone and `tests/test_cli.py` reports 17 total

4. **Step 4 (planner):** Update `doc/test-catalog.html`'s isolation section, its `test_cli.py` counts (15 → **17**) and grand total (362 → **364**), and the "safe alongside a live proxy" note, and close out the deferred issue in `CLAUDE.md`.
   → Evidence: `doc/test-catalog.html` and `CLAUDE.md` diffs; `python scripts/check_doc_anchors.py` exits 0
   → **Done 2026-10-03**: anchors 168 resolved exit 0, doc-structure 9 files no violations exit 0, catalog sums balance at 364/17, deferred index 8 → 7.

5. **Step 5 (tester):** Address the three non-blocking Phase 6 review findings that fall in this plan's test files — `proc.terminate()` → `proc.kill()` in the chokepoint guard and the Step 2 gate's child (finding `review-guard-posix-hard-kill`); extract `_remove_test_state_file()` and call it from all four removal sites (finding `review-removal-helper-duplication`); and give the import-time removal a real guard or a truthful comment (finding `review-import-removal-comment`). Full detail in `## Immediate Actions`.
   → tester verify (scripted): `./tmp/verification/2026-10-03-stale-test-state-file-pid-reuse-step2.py` exits 0 after the refactor (Part A's textual checks must be updated to follow the helper)
   → tester verify: full suite passes with the same total, and `test_run_cli_loop_clears_direct_spawn_state_file` still fails if the `run_cli` loop removal is reverted

## Guidance for Planner

Documentation tasks you will execute yourself (not the coder):

- **Doc files to create/update:**
  - `doc/test-catalog.html` — in the `#isolation` section (`:53-74`), state that `PROXY_STATE_FILE` points at a **per-run** temp path (`…-test-state-<runner-pid>.json`) that is removed at harness import and again after every test in `run_cli`'s loop, so runs neither inherit a previous run's entry nor collide with a concurrent run. **Recount**: the two new tests (`test_state_file_path_is_per_run_isolated` and `test_run_cli_loop_clears_direct_spawn_state_file`) make `test_cli.py` **17** tests and the suite grand total **364** (`grep -cE 'def (test_|doc_)' tests/*.py`) — update the per-file row (`:104`), the per-file heading (`:527`), add both tests to the `test_cli.py` per-test index, and update every grand-total site (the `:21-22` prose and the `:78` "same snapshot" note), the same three-representation discipline the sibling plans used. In the "safe to run alongside a live proxy" note (`:46-51`), keep the claim but attribute it to the per-run path. Bump the page's `<footer>Last updated:</footer>` (`:733`) and the `<strong>Last updated:</strong>` line (`:13`) to the completion date.
  - `CLAUDE.md` — (a) the "Test suite is safe alongside a live proxy" gotcha under `## Gotchas`: adjust the wording from "session temp paths" to "per-run temp paths" if needed for accuracy. (b) **Deferred-issue close-out:** remove the `stale-test-state-file-pid-reuse` row from the `## Unresolved Deferred Issues` JSON index, update the `## Future Work — TODO` prose (the count goes 8 → 7, and the sentence naming this issue must go), and flip the report file `tmp/reports/defer-issue-stale-test-state-file-pid-reuse.json` to a resolution report (`type: "resolution"`, `status: "Resolved"`, `resolved_by`, `resolution`, `changes_made`, `verification`) mirroring the shape of the sibling resolved reports.
  - **Document the declined production behavior honestly** in `doc/test-catalog.html`'s isolation section (a short note): a proxy killed outside `claude-retry-proxy stop` can leave `~/.claude/proxy/proxy-state.json` holding a dead PID, and `start`'s gate treats a live recycled PID as a running proxy — a known, accepted limitation (user decision 2026-10-03). Keep it to one or two sentences; it is a limitation note, not a feature description.
- **`.claude/mega-audit-files.json`:** does not exist in this repo — no entries to add or retire.
- **When:** after the tester finishes (the doc describes the isolation behavior that must already be in place).
- **What to sync:** no `README.md` change — it does not document test isolation (verified: the isolation gotcha lives in `CLAUDE.md` and `doc/test-catalog.html` only).
- **Post-completion:** write `## Final Results`; this plan has no `## Cross-References to Prior Plans` rows unless the reviewer surfaces one.

## History

One row per event (spec revision / mega-audit / review / implementation round). Conclusion = one-sentence outcome or what changed. Dismissed = compact dismissed-findings list for the reviewer — verbatim issue slugs linked as `[<slug>](<report-path>)`, no prose-only entries (the update-and-commit cross-ref and the reviewer both match these cells verbatim). Link to report files; never restate findings inline.

| Date | Event | Conclusion | Dismissed |
|------|-------|------------|-----------|
| 2026-10-03 | Initial plan | Test-isolation fix only: per-run state path + import-time removal + cleanup-closure removal; the production `is_pid_alive` hardening is a user-confirmed won't-fix, documented as a known limitation. | — |
| 2026-10-03 | Tester round (stalled) | Steps 1–3 landed in the worktree (`tests/_harness.py`, `tests/test_cli.py`), but the round was killed at the 3600 s launcher cap mid-full-suite (launcher pid 2916, log ends 20:16) and wrote **no session report**. No `/update-plan` ran; the round never closed. Left a stale `tester.lock` and orphaned run outputs. | — |
| 2026-10-03 | Planner verification + revision 1 | Independent verification of the frozen worktree: Step-1 gate exit 0, Step-2 gate exit 0, `tests/test_cli.py` 16/16. Found Step 2 **incomplete** — the fix patched only the three wrapper closures while the leak flows through `_start_proxy_server_directly` (31 direct call sites); reproduced a leftover per-run state file after `test_config_keys`. Step 2 corrected to remove the file in `run_cli`'s per-test loop (the single point all modules share); Step 4's counts corrected 362→363 / 15→16. | — |
| 2026-10-03 | Tester rounds 3–5 (stop-short) | Rounds `-3` (21:57, 3.5 min) and `-4` (22:09, 1.5 min) exited 0 having only narrated their next step — no edits, no report. Round `-5` (22:32–22:54, 22 min) **did land the work**: the `run_cli`-loop removal (`tests/_harness.py:1321`), the extended three-part Step 2 gate, and a second permanent test `test_run_cli_loop_clears_direct_spawn_state_file`; it then exited while its own background full-suite run was still in flight, so that run was killed and **no session report was written**. Counts move to 364 / 17. Three consecutive rounds have now failed to produce a report. | — |
| 2026-10-03 | Revision 2 | Step 4's counts corrected again (363→364, 16→17) after round `-5` added the second test; planner re-ran the full suite as independent gate evidence because no tester round has produced a report. | — |
| 2026-10-03 | Tester round 6 (`/update-plan` exit) | [SUCCESS — 364/364](./tmp/reports/2026-10-03-stale-test-state-file-pid-reuse-tester-2026-10-03.json), 0 failed, 0 skipped: both gates exit 0 (Step 2's Part C covers the direct-spawn regression issues `step2-leak-incomplete-direct-spawn`/`step2-closure-list-incomplete` demanded), `test_cli` 17/17, `test_config_keys` 17/17 with no leftover, and no new `%TEMP%` state file after the completed suite. Nothing re-implemented; no issue reports filed. The round's job was verification + the report, which rounds 3–5 had failed to produce. All four Issue Log rows Resolved; remaining work is the planner's Step 4 doc sync. | — |
| 2026-10-03 | Step 4 executed (planner) | Documentation reconciled: `doc/test-catalog.html` isolation section rewritten (per-run path, import clear, `run_cli` chokepoint, `%TEMP%` orphan note, declined-production limitation), counts 15→17 / 362→364 across all three representations with the per-file index balanced, and `CLAUDE.md` (gotcha, deferred index 8→7, Future Work prose). Evidence: `check_doc_anchors.py` 168 resolved exit 0; doc-structure 9 files, no violations, exit 0. Deferred report flipped to a resolution report. | — |
| 2026-10-04 | Review (Phase 6) | [Review — non-blocking](./tmp/reports/2026-10-03-stale-test-state-file-pid-reuse-review-2026-10-03.json): **0 Critical / 2 Warning / 3 Suggestion**, commit gate passes. Warning 1 (catalog note over-claimed "per-run" for all three paths) and Suggestion 5 (`CLAUDE.md` first sentence said "session temp paths") were planner doc defects introduced in Step 4 and are **fixed**. Warnings/Suggestions 2–4 (POSIX hard-kill premise in the new guard, the over-claiming import-removal comment, the 4× copy-pasted removal block) are handed to Step 5 by user decision 2026-10-04. | `[review-posix-sigterm-deadlock-hunch](./tmp/reports/2026-10-03-stale-test-state-file-pid-reuse-review-2026-10-03.json)` (pre-existing, outside this diff — to be filed separately), `[review-guard-strength-argued-not-executed](./tmp/reports/2026-10-03-stale-test-state-file-pid-reuse-review-2026-10-03.json)` (guard strength argued from analysis; gate Part C is the executable evidence) |
| 2026-10-04 | Revision 3 | Step 5 added for the three non-blocking review findings in the test files (user decision 2026-10-04); three Issue Log rows opened. Doc fixes applied. Metadata `steps` and `verification_scripts` updated. | — |
| 2026-10-04 | Tester round 7 (Step 5, stop-short) | Round `-7` (00:20–00:37, 17 min) **landed all of Step 5**: `_remove_test_state_file()` extracted into `tests/_harness.py:82` and called from all five sites, `proc.kill()` replacing `terminate()` in the new guards, `_STATE_FILE_PRESENT_AFTER_IMPORT` as a real import-time guard, and the Step 2 gate rewritten to Parts A0/A1/A2/B/C; it also ran a live revert experiment (`:1345` removed → guard fails). It then exited while its own background suite was still in flight — the third round to do so — so the run was killed and **again no session report was written**. Fourth stop-short round of seven; filed cross-repo as `operate-round-ends-turn-before-waiting`. | — |
| 2026-10-04 | Planner gate re-run (Step 5 evidence) | No tester report existed for Step 5, so the planner re-established the evidence directly: Step 1 gate exit 0, Step 2 gate exit 0 (A0/A1/A2/B/C), full suite `tmp/planner-fullsuite-step5.txt` = **364 passed / 0 failed / 364 total**, exit 0, with no new `%TEMP%` state file after the completed run; `check_doc_anchors.py` 168 resolved exit 0; doc-structure 9 files no violations exit 0. User waived the missing session report on 2026-10-04 (recorded under Deviations in Final Results). | — |
| 2026-10-04 | Review (Phase 6 re-review) | [Review — non-blocking](./tmp/reports/2026-10-03-stale-test-state-file-pid-reuse-review-2026-10-04.json): **0 Critical / 0 Warning / 1 Suggestion**, commit gate passes. All three handed findings judged RESOLVED on an independent re-run of both gates and both guard tests. The one new Suggestion is a pre-existing 8-copy instance of the guarded-remove idiom in `tests/test_cli.py` (lines 57, 158, 175, 360, 456, 907, 965, 1092) left deliberately outside Step 5's four-site scope. | `[review-cli-pre-existing-remove-idiom-copies](./tmp/reports/2026-10-03-stale-test-state-file-pid-reuse-review-2026-10-04.json)` (pre-existing, untouched by this diff — the plan's one open disposition), `[review-posix-sigterm-deadlock-hunch](./tmp/reports/2026-10-03-stale-test-state-file-pid-reuse-review-2026-10-03.json)` (carried forward from the 2026-10-03 review, still awaiting the user's disposition), `[review-embedded-child-program-duplication](./tmp/reports/2026-10-03-stale-test-state-file-pid-reuse-review-2026-10-04.json)` (test-body child program vs the Step 2 gate's `CHILD_RUN_CLI`; both plan-created, harmless while the gate is a throwaway), `[review-leak-test-wait-timeout-swallowed](./tmp/reports/2026-10-03-stale-test-state-file-pid-reuse-review-2026-10-04.json)` (pathological-only), `[review-posix-hard-kill-argued-not-executed](./tmp/reports/2026-10-03-stale-test-state-file-pid-reuse-review-2026-10-04.json)` (Windows dev box; the failure mode is structurally eliminated by `proc.kill()`), `[review-final-results-placeholder](./tmp/reports/2026-10-03-stale-test-state-file-pid-reuse-review-2026-10-04.json)` (resolved by this closeout) |

| 2026-10-04 | Planner investigation (SIGTERM hunch) | Investigated the carried-forward `review-posix-sigterm-deadlock-hunch` on the user's question. Confirmed it is a real defect, not a hunch: `socketserver.BaseServer.shutdown()` documents the deadlock, and `server.py:2881-2882` calls it from a signal handler — which runs on the `serve_forever` thread. Reproduced both halves: `tmp/repro_shutdown_same_thread.py` deadlocks in `same-thread` and `signal` modes and returns in 1.02 s in the `other-thread` control; `tmp/repro_sigterm_delivery_child.py` shows Windows exits the child with code 15 and never runs the handler, so the failure is POSIX-only. The codebase already uses the correct idiom at `server.py:2286-2293` (admin shutdown spawns a thread). Also corrected an earlier review premise: SIGTERM does not remove the state file on POSIX either, so the Step 5 `proc.kill()` change is right for a stronger reason than stated. **Deferred 2026-10-04** by user decision. | — |

## Plan Metadata

Fenced ```json block — the machine contract read by `parsePlanContext` (JSON-first, regex fallback). **Update it on every revision** — the rule-enforcer lens files a Medium finding when it is missing, invalid, or out of sync with the prose sections. Field semantics: `steps` = one title per `## Proposed Changes` step (numbering + first phrase; extra prose detail on either side is not a mismatch); `tester_files` = Tests to create + Verification scripts to create + Tests to investigate for retirement (mirrors the fallback's three-marker union); `doc_files` = the planner's `**Files to modify:**` list; `verification_scripts` entries shaped `./tmp/verification/<name>.py`; `repo_mode` = `Private` or `Public`; `document_overrides` = the `## Document Overrides` rows as formatted strings.

```json
{
  "plan_id": "2026-10-03-stale-test-state-file-pid-reuse",
  "steps": ["Step 1: In tests/_harness.py, give the state-file isolation path a per-process discriminator", "Step 2: In tests/_harness.py, remove the per-run state file in run_cli's per-test loop so every module leaves none behind", "Step 3: Add the permanent regression test test_state_file_path_is_per_run_isolated", "Step 4 (planner): Update doc/test-catalog.html's isolation section and close out the deferred issue in CLAUDE.md", "Step 5 (tester): Address the three non-blocking Phase 6 review findings that fall in this plan's test files"],
  "coder_files": [],
  "tester_files": ["tests/_harness.py", "tests/test_cli.py"],
  "doc_files": ["doc/test-catalog.html", "CLAUDE.md"],
  "verification_scripts": ["./tmp/verification/2026-10-03-stale-test-state-file-pid-reuse-step1.py", "./tmp/verification/2026-10-03-stale-test-state-file-pid-reuse-step2.py"],
  "repo_mode": "Public",
  "document_overrides": []
}
```

## Audit Accumulation

*Counters reset when mega-audit runs. Used by Phase 5 entry trigger.*

| Counter | Value | Last Updated |
|---------|-------|--------------|
| issues_resolved_since_audit | 7 | 2026-10-04 |
| steps_changed_since_audit | 2 | 2026-10-04 |
| files_changed_since_audit | 0 | 2026-10-04 |

*2026-10-03 `/update-plan` (round-6 exit): 4 issues resolved, no mega-audit (steps_changed 1, files_changed 0). 2026-10-04 revision 3: 3 new review issues opened (0 resolved this session), Step 5 added (+1 step) → 2/2/0. 2026-10-04 closeout: all 3 Step 5 issues resolved → 4+3 = 7. Trigger check — `issues_resolved ≥ 3` **AND** (`steps_changed ≥ 3` **OR** `files_changed ≥ 3`) — is 7/2/0, so **no mega-audit trigger**; the plan is complete and the counters retire with it.*

## Documentation

- `doc/test-catalog.html` — isolation section and the "safe alongside a live proxy" note updated to describe the per-run, self-cleaning state path (removed at import and after every test in `run_cli`), the `test_cli.py` count (15 → 17) and grand total (362 → 364), plus a one-line note on the declined production limitation (planner-owned, Step 4).
- `CLAUDE.md` — the "Test suite is safe alongside a live proxy" gotcha wording, the `## Unresolved Deferred Issues` index entry, and the `## Future Work — TODO` prose (planner-owned, Step 4).
- `README.md` — no change required (does not document test isolation).
- Source of truth for this plan: `./tmp/reports/defer-issue-stale-test-state-file-pid-reuse.json`.

## Final Results

**Status:** COMPLETED (2026-10-04)

The deferred issue `stale-test-state-file-pid-reuse` — a dead proxy PID recycled
by Windows could false-positive `cli.py`'s "Proxy already running" gate because
the test suite's state file was a fixed, machine-global path that survived every
run — is resolved. The test harness now uses a per-run state path, clears it at
import, and removes it after every test in `run_cli`'s per-test loop, so a
completed run cannot feed a stale PID to the next one.

### Steps

| Step | Lane | Outcome | Evidence |
|------|------|---------|----------|
| 1 — per-process state path + import-time removal | tester | Landed | `tmp/verification/…-step1.py` exit 0 |
| 2 — `run_cli`-loop removal (the chokepoint every module shares) | tester | Landed, after two corrections (see below) | `tmp/verification/…-step2.py` exit 0 — Parts A0/A1/A2/B/C |
| 3 — `test_state_file_path_is_per_run_isolated` + `test_run_cli_loop_clears_direct_spawn_state_file` | tester | Landed | suite 364/364; `test_cli.py` 17/17 |
| 4 — doc reconciliation + deferred-issue close-out | planner | Landed | `check_doc_anchors.py` 168 resolved exit 0; `doc_structure_check.py` 9 files, no violations, exit 0 |
| 5 — the three non-blocking review findings | tester | Landed | both gates re-run exit 0; suite 364/364; re-review judged all three RESOLVED |

### Verification evidence

| Check | Result |
|-------|--------|
| Step 1 gate | exit 0 |
| Step 2 gate (A0/A1/A2/B/C) | exit 0 |
| Full suite (`tmp/planner-fullsuite-step5.txt`) | **364 passed, 0 failed, 364 total**, exit 0 |
| `%TEMP%` state-file residue after a completed run | none |
| `check_doc_anchors.py` | 168 anchors resolved, exit 0 |
| `doc_structure_check.py` | 9 files, no violations, exit 0 |
| Test counts (code count = doc count) | 364 total / 17 in `test_cli.py` |
| `CLAUDE.md` deferred index | 7 entries, matching the "Seven deferred issues remain" prose |

### Review verdicts

| Date | Report | Verdict |
|------|--------|---------|
| 2026-10-04 (Step 5 diff) | [review-2026-10-04](./tmp/reports/2026-10-03-stale-test-state-file-pid-reuse-review-2026-10-04.json) | **0 Critical / 0 Warning / 1 Suggestion** — commit gate passes |
| 2026-10-04 (Step 4 diff) | [review-2026-10-03](./tmp/reports/2026-10-03-stale-test-state-file-pid-reuse-review-2026-10-03.json) | **0 Critical / 2 Warning / 3 Suggestion** — non-blocking; the 2 planner doc defects were fixed at once, the other 3 handed to Step 5 |

The re-review verified the Step 5 findings against their specific acceptance
criteria, re-ran both gates and both new guard tests, and recounted the suite
independently. It reports high confidence and judges that a further round would
"almost certainly not surface anything new."

### Issues

All rows in the Issue Log are Resolved except one Deferred row
(`operate-round-ends-turn-before-waiting`, cross-repo to `claude-config`).

Two corrections were needed during implementation, both found by planner
verification rather than by a round:

- **Step 2's first landing was incomplete** (`step2-leak-incomplete-direct-spawn`).
  It patched only the three wrapper `cleanup()` closures, but the leak also flows
  through `_start_proxy_server_directly`'s 31 direct call sites; a leftover
  `…-test-state-14348.json` was reproduced after `test_config_keys`. Corrected to
  the `run_cli` per-test loop — the single point all modules pass through — which
  makes the fix structural instead of a list to maintain
  (`step2-closure-list-incomplete`).
- **Step 4's counts were stale twice** (362/15 → 363/16 → 364/17) as tests landed.
  Final counts are reconciled across all three representations in
  `doc/test-catalog.html`.

One deferred issue was closed in this plan (the index went 8 → 7 entries), and
one new deferred issue was filed against `claude-config`
(`operate-round-ends-turn-before-waiting`).

### Deviations

1. **No tester session report exists for Step 5.** Tester round 7 (2026-10-04)
   landed all of Step 5 — the `_remove_test_state_file()` extraction, `proc.kill()`
   in both new guards, `_STATE_FILE_PRESENT_AFTER_IMPORT`, and the rewritten
   Step 2 gate — but then ended its turn while its own background full-suite run
   was still in flight, which terminated the session and killed the run. Four of
   this plan's seven rounds failed the same way; the round launcher's print-mode
   transport ends the session when the model emits a message with no tool call.
   **The user waived the report on 2026-10-04.** The planner re-established the
   evidence directly instead (the gate and suite results in the table above, run
   under the planner's own session), and the Phase 6 reviewer independently
   re-ran both gates and both guard tests against the finished tree. The
   plan-level gate — at least one tester session report with
   `overall_result: SUCCESS` — is satisfied by round 6's report
   (`…-tester-2026-10-03.json`), which covers Steps 1–3; Step 5's own report is
   the waived item.
2. **No coder lane, by design.** `coder_files` is empty: this plan changes no
   source code and no product behavior. The product-side hardening of
   `cli.py`'s `is_pid_alive()` gate against a recycled PID was declined by the
   user on 2026-10-03 and is documented as a known limitation in
   `doc/test-catalog.html`'s isolation section.
3. **The tester's Step 2 gate script was modified during Step 5.** A pure
   refactor to a shared helper would have broken gate Part A's textual checks, so
   the plan required the gate to be updated in the same change; Part A is now
   A0/A1/A2 and follows `_remove_test_state_file`.

### Open dispositions carried out of this plan

- `review-cli-pre-existing-remove-idiom-copies` (Suggestion, pre-existing):
  `tests/test_cli.py` still holds 8 verbatim copies of the guarded-remove idiom
  (lines 57, 158, 175, 360, 456, 907, 965, 1092) that could now call the shared
  helper. Deliberately outside Step 5's four-site scope. **Deferred 2026-10-04**
  by user decision → `./tmp/reports/defer-issue-cli-pre-existing-remove-idiom-copies.json`.
- `review-posix-sigterm-deadlock-hunch` (pre-existing, from the 2026-10-03
  review): `server.py`'s SIGTERM handler calls `server.shutdown()` on the
  `serve_forever` thread, which `socketserver` documents as a deadlock.
  Reproduced 2026-10-04 by the planner (see the plan's History) and **deferred
  2026-10-04** by user decision →
  `./tmp/reports/defer-issue-posix-sigterm-shutdown-deadlock.json`.

### Known limitations

- The POSIX branch of the hard-kill guard is argued from construction
  (`proc.kill()` is SIGKILL, so the server's `finally` cannot run) rather than
  executed — this is a Windows dev box.
- Full-suite runs completed during the workshop warn once, pre-existing and
  unrelated: `No proxy_stop event in trace` (tracked as
  `no-proxy-stop-trace-warning`).
