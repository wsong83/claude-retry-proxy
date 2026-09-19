# Plan: Extract the compatibility learner cluster from server.py into compat.py
**Project:** D:\proj\claude-retry-proxy
**Plan ID:** 2026-09-18-extract-compat
**Created:** 2026-09-18

## Immediate Actions

**User:** Review and approve `## Final Results`; then invoke `/update-and-commit` (it must stage the working tree — the staged compat.py index blob is stale).

## Issue Log

| Issue | Status | Found | Resolved | Resolved By |
|-------|--------|-------|----------|-------------|
| [step1-gate-slice-and-importfrom-defects](./tmp/reports/2026-09-18-extract-compat-step1-gate-slice-and-importfrom-defects.json) | Resolved | 2026-09-19 | 2026-09-19 | [coder](./tmp/reports/2026-09-18-extract-compat-step1-gate-slice-and-importfrom-defects.json) |
| [step1-gate-nested-def-undefined-name](./tmp/reports/2026-09-18-extract-compat-step1-gate-nested-def-undefined-name.json) | Resolved | 2026-09-19 | 2026-09-19 | [coder](./tmp/reports/2026-09-18-extract-compat-step1-gate-nested-def-undefined-name.json) |

## Guidance for Coder

**Files to modify:**
- `src/claude_retry_proxy/server.py`
- `src/claude_retry_proxy/compat.py` (new)

**Step-by-step with verification:** each step has coder checks tagged `(auto)` or `(scripted)`. Run the provided scripts; they were negative-tested against the pre-change tree (they fail there) and their expected sets are calibrated against the real baseline, not memory. **Calibration baseline 2026-09-18: server.py = 3,129 wc lines.** The wc figure is advisory only — the drift test is the landmark match described in Step 1 and the Risks table; if wc and landmarks disagree at execution time, the landmarks win and it is a stop-and-report.

**Module-surface counts** (calibrated 2026-09-18):

| Phase | Behavioral | Module-surface | Implementation |
|-------|-----------|----------------|----------------|
| Step 1 | 0 | 45 names move into compat.py (26 defs, 18 module-level assigns = 12 `COMPAT_*` constants + 4 state dicts + 2 locks, plus `_COMPAT_MESSAGE_RE`); server.py gains a single `from .compat import …` binding 23 names | delete ranges 270–712 and 775–858 in server.py; new compat.py (~540 lines incl. header/imports) |
| Step 2 | 0 | compat.py: 4 module dict names absorbed into `_CompatState`; +1 class, +1 singleton, +2 lock aliases (surface stays 45 names); 15 signatures gain `state=_state`; server.py import drops 1 name (23 → 22) | ~35 internal edits in compat.py; 1 import-line edit in server.py |

**Do-not instructions:**
- Never fix the dead `failed_confirmations` field (`_compat_validate_entry` hardcodes it to 0; `_compat_record_failed_confirmation` increments an in-memory counter that no code reads). It is defect-frozen by the move per the doctrine; it has an open deferred issue (`compat-entry-failed-confirmations-dead-field`) and a follow-up fix plan will target the new leaf module.
- Do not touch `_compat_probe_outcome` (stays in server.py; it calls `_forward_request_impl`, which siblings may not import).
- Do not touch `heartbeat_loop` or the section banners that are not part of the two deletion ranges.
- compat.py must never import server.py (`parent → sibling` is the only legal direction).

## Guidance for Tester

**Tests to create:**
- **Permanent:** `test_compat_state_object_shape` in `tests/test_compat.py` — asserts `claude_retry_proxy.compat._state` is a `_CompatState` instance, that `compat._compat_state_lock is compat._state.lock` and `compat._compat_retry_lock is compat._state.retry_lock`, and that explicit injection isolates state. **Containment constraints for the isolation assertions (do not discover them at failure time):** (a) the "fills `fresh.entries`" assertion runs only against a *valid* state file pinned via `PROXY_FEATURE_COMPAT_FILE` (the `_load_compat_state` failure branches return without assigning entries — add one failure-branch assertion, e.g. unreadable path leaves `fresh.entries` empty and the singleton untouched); (b) the `_compat_update(key, mutate, state=fresh)` assertion must use a mutate returning `persist=False` (as the "already learned" branch does) — a `persist=True` mutate would write the real `SETTINGS.feature_compat_file` even under injection. Register the test in the `ALL_TESTS` list (the aggregator in `tests/test_claude_proxy.py` imports `ALL_TESTS` from `test_compat`).
- **Temporary:** none planned.

**Tests to revise (the red interval's other half — see Steps 1–2):**
- `tests/test_compat.py` — `test_compat_state_unknown_feature_ignored` (def at line 530; state-handle lines 561–577): the test has **three** `srv._compat_state` touch points, all must convert: (1) line 562 save → `saved_entries = compat._state.entries`; (2) line 567 read (the `loaded_features` computation) → `compat._state.entries.values()` (`import claude_retry_proxy.compat as compat`); (3) line 577 restore → `compat._state.entries = saved_entries` (attribute assignment only — never copy-back into the live dict; the singleton object itself is never rebound). The `srv._load_compat_state()` call is unchanged (its default resolves to the singleton). Keep the `SETTINGS.feature_compat_file` save/restore in the same `finally` in its current order.
- `tests/test_compat.py` — `test_compat_temp_file_cleanup` (def at line 942; state-handle lines 949–975): same handle substitution for every line touching the compat state dict — save the current `compat._state.entries` before seeding, seed by direct attribute assignment (`compat._state.entries = {<seed entry>}` — assignment is safe, only the dict object is swapped, never the `_CompatState`), and restore by attribute assignment of the saved entries. `srv._persist_compat_state_locked()` stays as-is (default-param resolves to the singleton).
- `test_compat_locks_present` (def at line 897) needs **no change** — it asserts via `srv._compat_state_lock` / `srv._compat_retry_lock`, which remain live re-exports (aliases to the state object's locks) after Step 2. If it passes unchanged, record that in the session report.
- Do not alter test counts by deletion. The revised tests are the same tests with changed state-handle lines; the suite count grows only by the new permanent test above.

**Tests to investigate for retirement:** none — no test exercises code removed by the move; every referenced name stays reachable either through compat.py directly or through server.py's re-export bindings.

## Summary

**Problem.** server.py (3,129 wc lines) exceeds the 1,000-line threshold and still carries three extractable clusters after the sanitize/sinks, transforms, settings, and config/keys rounds: compat, router/forwarder, admin/handler. Per the one-cluster-per-plan and blast-radius ordering rules, this plan extracts the compatibility learner cluster first: it is the only cluster whose state is fully self-contained (zero writes outside the cluster), whose external dependencies are leaves that never import back, and whose extraction leaves zero touched sites in the request/retry path — a one-import-line rebase beats the 13 write-site re-platforming the forwarder needs and the blocked handler.

**Membership** (all three tests pass; collaborator notation in parentheses):

```
server.py                                    compat.py (new)
270-309  banner + COMPAT_* constants         270-309 verbatim
         + 4 state dicts (incl. the locks
         as the feature's mechanism)         312-710 verbatim
312-710  learner family (21 defs,
         _load_compat_state,
         _persist_compat_state_locked)
775-782  detector comment + _COMPAT_MESSAGE_RE
785-856  matchers (5 defs: message_form/
         structured/rejection/merge/stripped_body)
───────────────────────── stay behind ─────────────────────────
713-731  heartbeat_loop                      (state projection, not compat)
859-884  _compat_probe_outcome               (calls _forward_request_impl;
                                              moves later with router/forwarder)
1078-1261 compat slice inside                (stays verbatim; its 35 references
         _forward_request_impl                resolve through the new import)
```

**Step 2 design** (`move-then-shape`, user-confirmed): private `_CompatState` data object owns the 4 dicts plus both locks as plain attributes (`entries`, `failed_confirmations`, `suppressed_seen`, `persist_warned`, `lock`, `retry_lock`); module singleton `_state = _CompatState()`, constructed once at import, **never rebound** (def-time default-binding discipline — same frozen-singleton pattern as `SETTINGS`); 15 state-touching functions gain an appended `state=_state` parameter (default-param injection; the 11 pure functions don't change); module-level aliases `_compat_state_lock = _state.lock` / `_compat_retry_lock = _state.retry_lock` keep the parent's lock-acquire sites and the unchanged test alive. Internal calls between injected functions thread `state=` explicitly (a bare call would silently hit the singleton, breaking injection isolation). The module-level named dicts disappear; `COMPAT_*` constants stay module-level (they are code-defined tuning constants, clamped once at startup — see Document Overrides).

**Out of scope:** the router/forwarder and admin/handler extractions (later plans, in that forced order); fixing the dead `failed_confirmations` field (own deferred issue); moving `_compat_probe_outcome`; any test-file partition.

## Repo Mode

Public

## Document Overrides

| Document | Rule Overridden | Reason |
|----------|----------------|--------|
| user guide `refactor-split-guidance.md` §5 (state home table: limits/flags → settings object), as routed through the `/refactor-split` command | `COMPAT_*` tuning constants remain module-level in compat.py instead of joining the `SETTINGS` value object | They are code-defined constants, not env/user-derived; `doc/compatibility.html` (constants section, line 34) already documents them as maintainer-tunable with no user-facing configuration surface; moving them into the env-derived settings object would expand the documented surface. The three clamped constants are rebound at startup inside the cluster only (verified: zero parent reads). |

## Rollback

The working tree is git-scoped throughout: `git add src/claude_retry_proxy/compat.py` happens the moment the file exists; the pre-change baseline is the committed HEAD. To abort at any point (stop-and-report on landscape drift, a gate failure, or a review finding):
1. `git restore src/claude_retry_proxy/server.py tests/test_compat.py` — reverts the only two tracked files the unit edits.
2. Remove `src/claude_retry_proxy/compat.py` (untracked, or `git rm --cached` it if staged first).
3. Remove the plan's two verification scripts under `tmp/verification/` if staged.
4. Re-run the step1 gate as the negative test: it must FAIL with "compat.py does not exist", and the pre-change suite count must match the baseline.

No data migration exists: `feature-compatibility.json`'s persist/load format moves verbatim — any file written before the change is read identically after it, and vice versa.

## Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| Red interval: after Step 1, `test_compat_state_unknown_feature_ignored` and `test_compat_temp_file_cleanup` fail (they rebind `srv._compat_state`, a stale alias) until the tester lands Step 3 | Tree is red across Steps 1–3 | Steps 1–3 are ONE reviewable unit: no commit claims inside it; compat.py is `git add`ed immediately on creation; Step 3's suite run is the gate exit |
| The four dict names become stale/redundant in the wrong order (Step 1 needs them re-exported for the red-interval tests; Step 2 absorbs them) | ImportError or silent stale reads | Two scripted gates, one per step, each pinning the exact `.compat` import set for that step (23 names in Step 1, 22 in Step 2) — gates are step-local snapshots, never run cumulatively |
| A rewired function misses its state or the lock (Step 2) | Injection isolation silently broken — tests pass against the singleton while behavior drifts in the object | step2.py gate asserts: exactly 1 module-level `_state` store, the 15 signatures, `state=` keyword on every internal call to an injected function, alias lines, and no remaining `global _compat_state` |
| File drifts before execution (weekly-moving codebase) | Ranges 270–712 / 775–858 no longer match the landmarks | Step 1 re-verifies landmarks first (`_read_capped`'s end / heartbeat banner / `forward_request`'s `finally` / `_compat_probe_outcome` def). A drifted file is a stop-and-report, not an improvisation |
| Deletion eats a separator blank (§7.2 seam parity) | Two blanks collapse to one or three at the seams | R1 = 270–712 (leaves the 268–269 pair before the heartbeat banner), R2 = 775–858 (leaves the 773–774 pair before `_compat_probe_outcome`) — step1.py asserts blank-line parity at both seams |
| Test-count / aggregator regression | An unregistered test never runs; the catalog drifts | Tester registers the new permanent test in `ALL_TESTS`; planner updates the catalog count from the tester's session report |

## Proposed Changes

1. **Step 1:** Create `src/claude_retry_proxy/compat.py` and move the cluster verbatim.
   - compat.py = module docstring, then the pinned import whitelist, then Block 1 (server.py lines 270–710) and Block 2 (server.py lines 775–856) byte-identical, separated by exactly two blank lines. Import whitelist, exact: `import json`, `import os`, `import re`, `import sys`, `import threading`, `import time`, `import uuid` + `from .sanitize import sanitize_error` + `from .sinks import log_trace` + `from .settings import SETTINGS`. The docstring carries one caveat line forward from CLAUDE.md Gotchas: "Persisted state is metadata-only; the 0o600 chmod is POSIX-only — Windows users must restrict the state directory ACL manually."
   - server.py: delete ranges 270–712 and 775–858 inclusive; add ONE `from .compat import (...)` line binding exactly these 23 names: `COMPAT_FEATURE`, `COMPAT_MAX_RETRIES_PER_REQUEST`, `_compat_get`, `_compat_key`, `_compat_learn`, `_compat_merge_retries`, `_compat_note_suppressed_request`, `_compat_probe_inconclusive`, `_compat_probe_rejected`, `_compat_probe_success`, `_compat_record_failed_confirmation`, `_compat_record_strip`, `_compat_rejection_match`, `_compat_reset_strip_counter`, `_compat_retry_lock`, `_compat_state`, `_compat_state_lock`, `_compat_stripped_body`, `_compat_suppressed`, `_compat_validate_constants`, `_load_compat_state`, `_compat_normalize_threshold`, `_persist_compat_state_locked`. (`_compat_state` is test-frozen until Step 2 absorbs it — see Risks.)
   - `git add src/claude_retry_proxy/compat.py` the moment it exists.
   - → coder verify (auto): `from .compat import` is the only compat import in server.py; compat.py contains no `import` of server.py.
   - → coder verify (scripted): `python ./tmp/verification/2026-09-18-extract-compat-step1.py` exits 0 (blocks byte-identical, whitelist exact, undefined-name gate clean, import set exact, moved defs absent from server.py, seam blank parity). The script was negative-tested on the pre-change tree, where it fails. <!-- UPDATED: 2026-09-19 — gate revised for nested FunctionDefs (params were ast.arg, def name never a Name Store), per coder issue step1-gate-nested-def-undefined-name. UPDATED: 2026-09-19 r2 — byte-identity blocks now sourced from pre-change HEAD (`git show HEAD:…`, GIT_BASE split from the live path), compat/sibling ImportFrom matching uses ast's dotless `module` + `level == 1`, and the heartbeat seam landmark is the banner block start (three-line banner), per coder issue step1-gate-slice-and-importfrom-defects. Recalibrated: full simulated Step-1 tree passes the gate (exit 0), pre-change negative test still fails. Re-read the script before running. Step-local snapshot: once Step 2 lands, this gate's byte-identity and 23-name-import checks are intentionally false on the final tree — never re-run it cumulatively or report those as failures. -->
   - → tester verify: Step 3 (red interval — Steps 1–3 are one reviewable unit).

2. **Step 2:** Owned state object inside compat.py (design step — bodies change, this step's gate supersedes Step 1's).
   - Add `class _CompatState` (private; `__init__` sets `entries`, `failed_confirmations`, `suppressed_seen`, `persist_warned` dicts + `lock`/`retry_lock` locks) and module-level `_state = _CompatState()` plus the two aliases `_compat_state_lock = _state.lock`, `_compat_retry_lock = _state.retry_lock`. `_state` is stored exactly once and never rebound.
   - Rewire the 15 state-touching functions: appended `state=_state` parameter (`_load_compat_state`, `_persist_compat_state_locked`, `_compat_persist_failure_trace`, `_compat_update`, `_compat_get`, `_compat_record_failed_confirmation`, `_compat_reset_failed_confirmations`, `_compat_suppressed`, `_compat_note_suppressed_request`, `_compat_learn`, `_compat_record_strip`, `_compat_reset_strip_counter`, `_compat_probe_success`, `_compat_probe_rejected`, `_compat_probe_inconclusive`); replace dict reads with `state.<attr>`, `with _compat_state_lock:` with `with state.lock:`; delete the `global _compat_state` clause (replaced by `state.entries = loaded`); every internal call to an injected function passes `state=state`.
   - **Threading is internal-calls-only:** calls to injected functions made from *server.py* (via the re-export bindings, including `_compat_probe_outcome`'s calls to `_compat_probe_success` / `_compat_probe_rejected` / `_compat_probe_inconclusive`) use the `_state` default and must NOT be touched — the step2 gate scopes its call scan to compat.py for exactly this reason.
   - **Carried contracts (state it in compat.py comments, matching the moved docstrings):** `_compat_persist_failure_trace` inherits the caller-must-hold-`state.lock` contract from `_persist_compat_state_locked` (its only call site remains inside that function, under the lock); `_load_compat_state`'s wholesale `state.entries = loaded` assignment is startup-only and not lock-synchronized — any future reload-path caller must hold `state.lock`.
   - Delete the 4 module-level dict definitions (absorbed into `_state`); keep the module-level `COMPAT_*` constants untouched.
   - server.py: drop exactly `_compat_state` from the `.compat` import line (23 → 22 names).
   - → coder verify (auto): compat.py still contains no import of server.py.
   - → coder verify (scripted): `python ./tmp/verification/2026-09-18-extract-compat-step2.py` exits 0 (state-object shape, exactly-1 `_state` store, 15 signatures with `state=_state`, internal call `state=` threading, aliases present, no remaining module-level compat-dict names, inbound imports still exactly the whitelist, server.py import = exactly the 22-name set). Negative-tested against the Step-1 output shape. <!-- UPDATED: 2026-09-19 r2 — import matching fixed to ast's dotless `module` + `level == 1` (same defect family as step1's checks 4/6, per coder issue step1-gate-slice-and-importfrom-defects); validated exit 0 on the live Step-2 implementation. -->
   - → tester verify: Step 3.

3. **Step 3:** Revise the two state-handle tests and add the shape test; run the suite.
   - Apply the two substitutions in "Tests to revise" (save/restore `compat._state.entries` instead of rebinding `srv._compat_state`); leave `test_compat_locks_present` untouched and record it as passing-unchanged if so; add and register the permanent `test_compat_state_object_shape`.
   - → tester verify: assert `test_compat_state_load_missing_file`, `test_compat_state_roundtrip`, `test_compat_state_concurrent_updates_no_loss`, `test_compat_state_unknown_feature_ignored`, `test_compat_temp_file_cleanup`, `test_compat_locks_present`, `test_compat_normalize_threshold_ladder`, `test_compat_retry_lock_released_on_exception`, `test_compat_config_swap_during_retry`, `test_compat_retry_stream_interaction` all pass, plus `tests/test_claude_proxy.py` aggregator reports the previous total + the one new registered test (no unregistered test, no test lost).
   - → tester verify: full suite green; `test_retry_streaming.py`'s direct `srv._compat_validate_constants()` / `srv._load_compat_state()` calls pass unchanged (evidence that the parent re-export surface stays live).

4. **Step 4:** Documentation sync (planner lane — executed by the planner, not the coder).
   - `doc/compatibility.html`: the location sentence near line 35 reads "top of the compatibility section of `src/claude_retry_proxy/server.py`" — re-point it at `compat.py` and describe the state object (`_CompatState` / `_state`) and the injection convention; re-verify the constants table against the moved module (values unchanged).
   - `CLAUDE.md`: structure list — add the `compat.py` line; Future Work — record this extraction as step 5 of the staged decomposition with re-measured post-move wc counts for server.py and compat.py (measure at execution time, never estimate).
   - `doc/test-catalog.html`: update the test_compat internals description where it names the two revised tests' state handling; add a **per-test inventory entry** (docstring summary) for `test_compat_state_object_shape` in the Category 7 "Compatibility Learner" list (the catalog's own invariant: a test without an entry is missing silently); update the `test_compat.py` test count from the tester's session report AND the suite-total snapshot in the catalog header (currently "321 test functions across 18 files" → the aggregator's tally at execution time, expected 322). The tester's test edit and this inventory reconciliation land in the plan's single consolidated commit (`/update-and-commit` Step 10), which satisfies the catalog's same-commit invariant at commit granularity.
   - → Evidence: `git diff --stat` naming only the four doc files; grep shows zero remaining "compatibility section of `server.py`" phrasing in `doc/`; `python scripts/check_doc_anchors.py` exits 0.

## Guidance for Planner

- **Doc files to create/update:** `doc/compatibility.html`, `CLAUDE.md`, `doc/test-catalog.html`.
- **When:** after the tester's Step 3 report lands (doc sync depends on the final test count and post-move wc numbers).
- **What to sync:** the three bullets in Step 4; no README changes (no user-facing surface change).
- **`.claude/mega-audit-files.json`:** untouched — no repo-local audit locations change.

## History

| Date | Event | Conclusion | Dismissed |
|------|-------|------------|-----------|
| 2026-09-18 | Initial plan | Scope=compat cluster only; shape=verbatim move + owned-state design step (user-confirmed in Phase 3) | — |
| 2026-09-18 | Mega-audit (pre-implementation, iteration 1) | Verdict: non-blocking — 0 High, 7 Medium, 16 Low; all 7 Medium and 14 of 16 Low fixed in place (module-surface arithmetic, stale 3,130 baseline, incomplete test substitutions, rollback section, same-commit catalog reconciliation, injection-test containment, server-side bare-call exception, lock/startup contracts, doc citations). Report: [2026-09-18-extract-compat-mega-audit-2026-09-18.json](./tmp/reports/2026-09-18-extract-compat-mega-audit-2026-09-18.json) | #18 constants-import future drift: recorded by the Document Override, no action; #21 sanitize-docstring authored: whitelist pinning already covers it, no action |
| 2026-09-19 | Spec revision (/update-plan) | Fixed the Step-1 gate's undefined-name walker for nested FunctionDefs and recalibrated (repro + real moved bodies + negative test); step2.py verified unaffected. Report: [2026-09-18-extract-compat-step1-gate-nested-def-undefined-name.json](./tmp/reports/2026-09-18-extract-compat-step1-gate-nested-def-undefined-name.json) | — |
| 2026-09-19 | Spec revision (/update-plan) | Second gate round: byte-identity now sources from pre-change HEAD, dotless ImportFrom matching, banner-block seam landmark — validated by a full simulated Step-1 tree (gate exit 0) plus the unchanged negative test. Report: [2026-09-18-extract-compat-step1-gate-slice-and-importfrom-defects.json](./tmp/reports/2026-09-18-extract-compat-step1-gate-slice-and-importfrom-defects.json) | — |
| 2026-09-19 | Spec revision (/update-plan) | Third gate round: the step2 gate carried the same dotted-ImportFrom family — fixed (r2) and validated exit 0 directly on the coder's live Step-2 implementation; gate1's final-tree failures confirmed as expected step-local snapshots (byte-identity + 23→22 import are Step-1-only properties), and Steps 1–2 declared gate-verified with the tester up next. Report: [2026-09-18-extract-compat-step1-gate-slice-and-importfrom-defects.json](./tmp/reports/2026-09-18-extract-compat-step1-gate-slice-and-importfrom-defects.json) | — |
| 2026-09-19 | Implementation round | Tester SUCCESS (322/322, 0 failed/skipped; aggregator 321→322, test_compat 43→44) — red interval closed; planner executed Step 4 doc sync (compatibility.html, test-catalog.html, CLAUDE.md + anchor check PASS); finalization held pending a coder session report per user decision. Report: [2026-09-18-extract-compat-tester-2026-09-19.json](./tmp/reports/2026-09-18-extract-compat-tester-2026-09-19.json) | — |
| 2026-09-19 | Review (Phase-6 reviewer) | Verdict "Issues found — non-blocking" — 0 Critical / 0 Warning / 1 Suggestion; injection threading, 22-name import completeness, lock discipline, and all freeze constraints verified, gates + test_compat suite re-run live. Report: [2026-09-18-extract-compat-review-2026-09-19.json](./tmp/reports/2026-09-18-extract-compat-review-2026-09-19.json) | [shape-test-snapshot](./tmp/reports/2026-09-18-extract-compat-review-2026-09-19.json) (Suggestion, deferred non-blocking); hunches acknowledged: [am-staging](./tmp/reports/2026-09-18-extract-compat-review-2026-09-19.json) commit hygiene (action for /update-and-commit), clamped-constants latent spindle (Document Override covers), retry_lock doc one-liner (fixed in compatibility.html this round) |

## Plan Metadata

```json
{
  "plan_id": "2026-09-18-extract-compat",
  "steps": ["Step 1: Create compat.py and move the cluster verbatim", "Step 2: Owned state object inside compat.py", "Step 3: Revise the two state-handle tests and run the suite", "Step 4: Documentation sync (planner lane)"],
  "coder_files": ["src/claude_retry_proxy/server.py", "src/claude_retry_proxy/compat.py"],
  "tester_files": ["tests/test_compat.py"],
  "doc_files": ["doc/compatibility.html", "doc/test-catalog.html", "CLAUDE.md"],
  "verification_scripts": ["./tmp/verification/2026-09-18-extract-compat-step1.py", "./tmp/verification/2026-09-18-extract-compat-step2.py"],
  "repo_mode": "Public",
  "document_overrides": ["refactor-split-guidance §5 state home table: COMPAT_* tuning constants stay module-level in compat.py (Reason: code-defined, not env-derived; verbatim move; doc/compatibility.html documents them as maintainer-tunable with no user-facing configuration surface)"]
}
```

## Audit Accumulation

| Counter | Value | Last Updated |
|---------|-------|--------------|
| issues_resolved_since_audit | 2 | 2026-09-19 |
| steps_changed_since_audit | 3 | 2026-09-19 |
| files_changed_since_audit | 0 | 2026-09-19 |

## Documentation

See `## Guidance for Planner` / Step 4.

## Final Results

**Status:** COMPLETED — 2026-09-19

**Implementation** — all four steps landed:
1. Coder Step 1 (verbatim move): `src/claude_retry_proxy/compat.py` created; ranges 270–712 / 775–858 deleted from server.py; 23-name import. Step-1 gate passed at its snapshot.
2. Coder Step 2 (design): owned `_CompatState` + `_state` singleton + lock aliases; 15 injected functions (`state=_state`); import 23→22. Step-2 gate exit 0 on the live tree.
3. Tester Step 3: two state-handle revisions applied exactly per the enumerated touch points; permanent `test_compat_state_object_shape` added and registered; `test_compat_locks_present` passed unchanged (re-export surface live). Full suite **322/322 passed, 0 failed, 0 skipped** (aggregator 321→322).
4. Planner Step 4: doc sync landed — `CLAUDE.md` (structure list + Future Work step 5, re-measured counts), `doc/compatibility.html` (module re-point + state-object description + retry-lock contract), `doc/test-catalog.html` (322 total, 44 in test_compat, new per-test entry, retry-lock sentence). `check_doc_anchors.py` exit 0 (159 anchors, no secret shapes).

**Files changed:** `src/claude_retry_proxy/compat.py` (new, 569 wc lines), `src/claude_retry_proxy/server.py` (3,129 → 2,613 wc lines), `tests/test_compat.py`, `CLAUDE.md`, `doc/compatibility.html`, `doc/test-catalog.html`.

**Review:** Phase-6 reviewer (Sonnet, 2026-09-19) — verdict "Issues found — non-blocking": **0 Critical, 0 Warning, 1 Suggestion**. Verified: injection threading (exactly the 15 declared functions changed, all internal calls thread `state=`), import-set completeness (22 names, no stray refs/rebinds), lock discipline (single `_state` store, alias identity, caller-holds-lock contract carried), all freeze constraints (dead `failed_confirmations` untouched, `_compat_probe_outcome`/`heartbeat_loop` verbatim, no parent import, no behavior change).

**Known caveats:**
- Reviewer Suggestion (deferred, non-blocking): `test_compat_state_object_shape` compares singleton entries against a literal `{}` (`tests/test_compat.py:967, 1004`) — a saved-snapshot comparison would survive future in-process singleton mutations. Optional one-line tester follow-up; does not block this commit.
- Pre-existing suite warning: "No proxy_stop event in trace" — tracked deferred issue `no-proxy-stop-trace-warning`, unrelated to this plan.
- Commit hygiene for `/update-and-commit`: `compat.py` status is `AM` — stage the **working tree**, not the stale index blob (pre-`_CompatState` version).

**Issues resolved:** both coder-filed gate issues — `step1-gate-nested-def-undefined-name` and `step1-gate-slice-and-importfrom-defects` — Resolved 2026-09-19. No new issues during test or review rounds.

**Prior-plan cross-reference scan:** performed — no deferred issue from a prior plan is resolved by this implementation (no Cross-References table added per the rule). The open `compat-entry-failed-confirmations-dead-field` deferred issue remains open by design (frozen in the move; a follow-up fix plan now targets the leaf module).