# Plan: Drop the dead `failed_confirmations` field from the persisted compatibility entry

**Project:** D:\proj\claude-retry-proxy ($PWD)
**Plan ID:** 2026-09-23-drop-dead-failed-confirmations-field
**Created:** 2026-09-23

## Issue Log

Rows ordered newest-first (latest issues at top). New issues are prepended; resolved issues stay in place with updated status.

| Issue | Status | Found | Resolved | Resolved By |
|-------|--------|-------|----------|-------------|
| [compat-entry-failed-confirmations-dead-field](./tmp/reports/defer-issue-compat-entry-failed-confirmations-dead-field.json) | Resolved | 2026-09-12 | 2026-09-23 | [tester](./tmp/reports/2026-09-23-drop-dead-failed-confirmations-field-tester-2026-09-23.json) + planner close-out |

## Guidance for Coder

**Files to modify:** `src/claude_retry_proxy/compat.py` (only)

**Critical distinction — read before editing.** Two different things share the name `failed_confirmations`:

| Thing | Fate in this plan |
|---|---|
| The **persisted entry field** — a dict key written into state-file entries | **Removed** (this is the defect) |
| The **in-memory counter** — `_CompatState.failed_confirmations` (a dict attribute, `compat.py:55`) plus `_compat_record_failed_confirmation` / `_compat_reset_failed_confirmations` / `_compat_suppressed` / `_compat_note_suppressed_request` | **Untouched — do not rename, move, or delete.** It is the live throttle and works correctly |

The in-memory attribute keeps its name (user decision, 2026-09-23). Do not "tidy" it.

**Step-by-step with verification:** each step below carries coder checks tagged `(auto)` or `(scripted)`. The coder self-verifies `(auto)` checks and runs the provided script for `(scripted)` checks. Tester owns the behavioral checks.

1. **Step 1:** In `_compat_validate_entry` (`compat.py`), stop reading, type-checking, and re-emitting the persisted `failed_confirmations` field. Three edits in the function:
   - delete the line `failed_confirmations = entry.get("failed_confirmations", 0)` (was `:150`)
   - in the type-check loop, change `for v in (strip_counter, probation_successes, failed_confirmations):` to `for v in (strip_counter, probation_successes):` (was `:151`)
   - delete `"failed_confirmations": 0,` from the returned dict literal (was `:166`)
   → coder verify (auto): the string `failed_confirmations` **with the `"entry"`/persisted sense** — i.e. any `entry.get("failed_confirmations"...)`, any `"failed_confirmations":` literal inside `_compat_validate_entry` or `_compat_learn` — no longer appears in `compat.py`, while `state.failed_confirmations` (attribute access, no quotes) still appears in `_compat_record_failed_confirmation`, `_compat_reset_failed_confirmations`, `_compat_suppressed`, and `_compat_note_suppressed_request`. Read those four functions and confirm they are unchanged.
   → coder verify (scripted): `./tmp/verification/2026-09-23-drop-dead-failed-confirmations-field-step1.py` — run from the repo root, no arguments. **It currently fails (exit 1); that is correct**, since it is calibrated against the pre-change tree. It goes green only after Steps 1–3 are all done, because it also checks the tester's allowlist fixture.
   → tester verify: loading a state file whose entry carries `"failed_confirmations"` is unaffected by that field's value — including a value that would previously have failed type-validation.

2. **Step 2:** Delete the new-entry field literal in `_compat_learn` (`compat.py`): remove the line `"failed_confirmations": 0,` from the dict returned by `mutate` for the not-yet-learned branch (was `:355`). **Leave the call `_compat_reset_failed_confirmations(key, state=state)` immediately after `_compat_update(...)` in place** — it clears the *in-memory* counter on a successful learn and is load-bearing.
   → coder verify (auto): `_compat_learn`'s new-entry dict literal has exactly 9 keys — `schema_version`, `provider`, `mode`, `actual_model`, `feature`, `state`, `threshold`, `strip_counter`, `probation_successes` — and the `_compat_reset_failed_confirmations(key, state=state)` call is still present after the `_compat_update(key, mutate, state=state)` call.
   → tester verify: an end-to-end learn cycle still writes a 9-field entry and still strips the feature on the next request.

3. **Do not proceed to Step 3** until Steps 1–2 pass: the test sweep in Step 3 makes the fixtures stop carrying the field, so a partially edited source tree will produce a confusing mixed failure.

## Guidance for Tester

**Tests to create:**
- **Permanent:** none.
- **Temporary:** none.

User decision (2026-09-23): fixtures only, no new test coverage. The regression guard is deliberately *not* being added in this plan — the metadata-only test remains an upper-bound key check. If you identify a genuine coverage gap while working (e.g. you judge that nothing pins the persisted schema), report it in your session report rather than adding a test; do not expand scope.

**Step-by-step with verification:**

4. **Step 3:** Trim the dead field out of the test-side fixtures that mirror what the code actually writes. Four edits in `tests/test_compat.py`:
   - `ALLOWED_STATE_KEYS` (was `:80-84`) — drop `"failed_confirmations"` from the set, leaving 9 names on 3 lines (re-flow as needed).
   - the `_persist_compat_state_locked` fixture entry (was `~:1044-1052`) — drop `"failed_confirmations": 0,` from the `compat._state.entries` dict literal.
   - the foreign-feature load fixture (was `~:545-554`) — drop the line, so the on-disk foreign entry matches the current schema shape.
   - the injection-isolation `stub_entry` (was `~:945-951`) — drop the line.
   → tester verify: `python tests/test_claude_proxy.py` — the full suite passes, with the compat tests exercising both the in-memory suppression path and the persisted-entry schema path.

   **Leave alone:** the `"stub-provider\x1fanthropic\x1fstub-model\x1fcontext_management"` string near `stub_entry` — that `\x1f` is a key delimiter, not a field, and has nothing to do with this change. Apply judgment anywhere else: trim only fixtures that *mirror what the code writes*; leave incidental dicts that merely happen to carry the name.

**Tests to investigate for retirement:**

- Planner candidates: **none.**
  `identical-persisted-field-rejection-test` was considered and ruled out: no existing test pins rejection on a malformed `failed_confirmations` value. The one invalid-entry test (`test_compat.py:~442-522`, "One Bad Entry Keeps Valid") corrupts `entry["state"]` to `"bogus-state-value"` — a field this plan does not touch — so it remains valid and must not be modified.
- Tester may identify additional candidates during test work.

**Retirement procedure:** For each candidate, verify the test exercises code being removed/changed. If obsolete: delete and note in session report. If still valid: document why in session report.

## Summary

**Problem.** Every persisted entry in `~/.claude/proxy/feature-compatibility.json` carries a `"failed_confirmations": 0` field that no code path ever increments. It reads like a live counter to anyone inspecting the file — a consumer could read "zero failures" for a key that is in fact fully suppressed. The counter that actually drives suppression is a **separate in-memory dict** (`_CompatState.failed_confirmations`), which the code already declares restart-scoped by design. So the persisted field is pure noise in an inspection artifact, and it has already cost real documentation overhead: `doc/compatibility.html` carries a paragraph ("A vestigial field") that exists solely to tell readers to ignore it.

**Origin.** The field was born dead. The originating plan (`plans/2026-09-01-learn-context-management-compatibility.md`) contradicts itself — its state-model table lists `failed_confirmations` as a persisted per-entry field (line 26), while its discovery prose (line 43) and risk table (line 376) specify an *in-memory* per-key counter. The implementation followed the prose; the schema entry was written from the table and never wired up. `git log -S failed_confirmations` confirms it entered with the feature's first commit (`c850941`) and was only carried verbatim by the extraction (`b42b31c`). This is not a regression.

**Approach.** Delete the field from the persisted schema; leave the in-memory throttle exactly as it is. Three source edits in `compat.py` (validate read, validate literal, learn literal), four fixture edits in `tests/test_compat.py`, and the removal of the now-obsolete doc paragraph.

**Why not persist the counter instead.** The counter is a rate limiter, not a durable fact. It is cleared automatically after 32 suppressed requests (`compat.py:333-335`) and is deliberately zeroed on every load. Persisting it would be a behavior change (suppression surviving restarts), not a schema cleanup, and it buys back at most ~3 wasted upstream calls per provider per restart after a failing stretch — the case where a provider rejects even the stripped retry, which is never learned and therefore never persisted in the first place. The state file's job is to remember the *verdict* ("this provider rejects the feature"), which it does.

**Migration.** None required, and `schema_version` stays `1`. Both directions are already tolerant: an old reader of a new file falls back to its `.get(..., 0)` default, and a new reader silently ignores the field if an old file still carries it — `_compat_validate_entry` builds its returned dict explicitly rather than copying the input, so a legacy field is dropped on the first load and is gone from the next write.

**Alternatives considered.**
- *Move the live counter into the entry* — makes the field honest, but changes restart semantics. Rejected: the restart-resets behavior is deliberate and fail-safe.
- *Rename the in-memory attribute to avoid the name collision* — churns `compat.py` and its test file for zero functional gain. Rejected by user decision.
- *Bump `schema_version`* — rejected: no reader behavior depends on the field, so a bump would force a fail-closed reload path where a tolerant one already exists.

**Explicitly out of scope.** The in-memory counter and every function around it; the dead `Returns the count` contract on `_compat_record_failed_confirmation` (user decision: leave it); new test coverage (user decision); the untracked build/scratch copies at `build/lib/claude_retry_proxy/server.py` and `tmp/HEAD-server.py`, which are gitignored artifacts, not live code.

## Repo Mode

Public

*Detected at plan creation. Determines: plan archival path, commit-message content, staged files.*

## Document Overrides

| Document | Rule Overridden | Reason |
|----------|----------------|--------|

## Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| A partially edited tree (source trimmed, fixtures not) yields confusing mixed test failures | Tester misreads a half-done change as a behavioral regression | Step 3 is gated on Steps 1–2 passing; the Coder section states the ordering explicitly |
| The two same-named things are conflated during editing, deleting the live in-memory counter | Suppression breaks silently — the learner would retry forever instead of throttling after 3 failures | The Coder section leads with a two-row disambiguation table; Step 2's check verifies the `_compat_reset_failed_confirmations` call survives |

## Proposed Changes

Each step includes verification checks tagged with confidence (see Prime Directive 4).
`(auto)` = mechanical, coder self-verifies. `(scripted)` = deterministic multi-step, coder runs provided script.
Every step must have at least one verification check executable by its owner (coder steps: coder checks; tester steps: tester verify; planner steps: Evidence).
Steps MUST use this numbered-list format exactly. The `### Step N:` heading format is deprecated and must not be used.

1. **Step 1:** In `compat.py`'s `_compat_validate_entry`, stop reading, type-checking, and re-emitting the persisted `failed_confirmations` field (three edits: the `.get` read, the type-check tuple, the returned dict literal).
   → coder verify (auto): no persisted-sense `failed_confirmations` remains in `_compat_validate_entry`; `state.failed_confirmations` attribute access still present and unchanged in the four in-memory functions
   → coder verify (scripted): `./tmp/verification/2026-09-23-drop-dead-failed-confirmations-field-step1.py`
   → tester verify: an entry's `failed_confirmations` value — including a previously-invalid one — does not affect loading

2. **Step 2:** In `compat.py`'s `_compat_learn`, delete the `"failed_confirmations": 0,` line from the new-entry dict literal; keep the `_compat_reset_failed_confirmations(key, state=state)` call.
   → coder verify (auto): the new-entry literal has exactly the 9 expected keys; the reset call is still present after `_compat_update`
   → tester verify: an end-to-end learn cycle writes a 9-field entry and still strips on the next request

3. **Step 3:** Trim the dead field from the four test-side fixtures in `tests/test_compat.py` that mirror what the code writes (`ALLOWED_STATE_KEYS`, the persist fixture entry, the foreign-feature load fixture, the injection-isolation `stub_entry`).
   → tester verify: `python tests/test_claude_proxy.py` passes in full

4. **Step 4:** Remove the obsolete "A vestigial field" note from `doc/compatibility.html` (`:238-244`), whose only purpose was to explain the wart being deleted.
   → Evidence: file diff showing the `<div class="note">` block removed; a repo-wide grep for `vestigial` in `doc/` returning zero matches; `python scripts/check_doc_anchors.py` exits 0

## Guidance for Planner

Documentation tasks you will execute yourself (not the coder):

- **Doc files to create/update:** `doc/compatibility.html` — remove the "A vestigial field" note (`:238-244`). The entry-schema table above it (`:211-221`) already omits `failed_confirmations` and needs no edit. Bump the page's `<footer>Last updated:</footer>` to the completion date.
- **`.claude/mega-audit-files.json`:** does not exist in this repo — no entries to add or retire.
- **When:** after the coder finishes (the note describes code that must already be gone).
- **What to sync:** also update the `## Unresolved Deferred Issues` JSON index and the `## Future Work — TODO` prose in `CLAUDE.md` to drop `compat-entry-failed-confirmations-dead-field` once the fix has landed and the issue is marked Resolved — this is the standard deferred-issue close-out, not part of the doc note removal. Leave the deferred-issue report file itself in `./tmp/reports/` as the historical record.
- No `README.md` change: it does not document the compatibility entry schema (verified by grep).

## History

One row per event (spec revision / mega-audit / review / implementation round). Conclusion = one-sentence outcome or what changed. Dismissed = compact dismissed-findings list for the reviewer — verbatim issue slugs linked as `[<slug>](<report-path>)`, no prose-only entries (the update-and-commit cross-ref and the reviewer both match these cells verbatim). Link to report files; never restate findings inline.

| Date | Event | Conclusion | Dismissed |
|------|-------|------------|-----------|
| 2026-09-23 | Initial plan | Drop the dead persisted field; the in-memory throttle, its name, and its return contract stay untouched, and no new tests are added. | — |
| 2026-09-23 | Verification script calibration | Step 1's gate calibrated against three simulated trees (pre-change exit 1 / compat-only exit 1 / both-files exit 0); an initial cwd-anchored `REPO_ROOT` and an `re.MULTILINE` omission were both found and fixed by that calibration — the script reports 6 failures against the live tree today, as intended. | — |
| 2026-09-23 | Implementation round | Coder completed Steps 1–2 (`build_result: pass`, no issues filed), tester completed Step 3 at 322/322 with no failures and no retirement candidates; planner completed Step 4 and closed out the deferred issue. | — |
| 2026-09-23 | Review | Phase-6 reviewer (Sonnet): verdict "Issues found — non-blocking" — **0 Critical, 1 Warning, 0 Suggestion**; the Warning was the deferred-issue report file's stale `status: Open` metadata, fixed by the planner during close-out ([report](./tmp/reports/2026-09-23-drop-dead-failed-confirmations-field-review-2026-09-23.json)). | — |

## Plan Metadata

Fenced ```json block — the machine contract read by `parsePlanContext` (JSON-first, regex fallback). **Update it on every revision** — the rule-enforcer lens files a Medium finding when it is missing, invalid, or out of sync with the prose sections. Field semantics: `steps` = one title per `## Proposed Changes` step (numbering + first phrase; extra prose detail on either side is not a mismatch); `tester_files` = Tests to create + Verification scripts to create + Tests to investigate for retirement (mirrors the fallback's three-marker union); `doc_files` = the planner's `**Files to modify:**` list; `verification_scripts` entries shaped `./tmp/verification/<name>.py`; `repo_mode` = `Private` or `Public`; `document_overrides` = the `## Document Overrides` rows as formatted strings.

```json
{
  "plan_id": "2026-09-23-drop-dead-failed-confirmations-field",
  "steps": ["Step 1: In compat.py's _compat_validate_entry", "Step 2: In compat.py's _compat_learn", "Step 3: Trim the dead field from the four test-side fixtures", "Step 4: Remove the obsolete \"A vestigial field\" note from doc/compatibility.html"],
  "coder_files": ["src/claude_retry_proxy/compat.py"],
  "tester_files": ["tests/test_compat.py"],
  "doc_files": ["doc/compatibility.html", "CLAUDE.md"],
  "verification_scripts": ["./tmp/verification/2026-09-23-drop-dead-failed-confirmations-field-step1.py"],
  "repo_mode": "Public",
  "document_overrides": []
}
```

## Audit Accumulation

*Counters reset when mega-audit runs. Used by Phase 5 entry trigger.*

| Counter | Value | Last Updated |
|---------|-------|--------------|
| issues_resolved_since_audit | 0 | 2026-09-23 |
| steps_changed_since_audit | 0 | 2026-09-23 |
| files_changed_since_audit | 0 | 2026-09-23 |

## Documentation

- `doc/compatibility.html` — the "A vestigial field" note is removed by Step 4 (planner-owned); the entry-schema table is already correct.
- `CLAUDE.md` — the deferred-issue index entry and the `## Future Work — TODO` prose are updated at close-out (planner-owned); the file's Structure section and Gotchas do not document the entry schema, so nothing else changes.
- `README.md` — no change required (user-facing install/usage doc; does not cover the state file schema).
- Source of truth for this plan: `./tmp/reports/defer-issue-compat-entry-failed-confirmations-dead-field.json`.

## Final Results

**Status: COMPLETED** — 2026-09-23

**What changed.** The dead `failed_confirmations` field is gone from the persisted compatibility
entry schema. Entries now carry exactly 9 fields. The separate in-memory counter that actually
drives suppression (`_CompatState.failed_confirmations` and its four functions) is untouched, as
is the `_compat_reset_failed_confirmations` call inside `_compat_learn`. The obsolete "A
vestigial field" paragraph is gone from `doc/compatibility.html`, and the deferred issue is
closed in `CLAUDE.md`.

**Steps completed.**

| Step | Owner | Status |
|------|-------|--------|
| 1 — `_compat_validate_entry`: drop the read, type-check slot, and returned-dict literal | Coder | COMPLETE |
| 2 — `_compat_learn`: drop the new-entry literal, keep the reset call | Coder | COMPLETE |
| 3 — Trim the four test-side fixtures | Tester | COMPLETE |
| 4 — Remove the "A vestigial field" note; close the deferred issue | Planner | COMPLETE |

**Files changed.** `src/claude_retry_proxy/compat.py` (3 deletions), `tests/test_compat.py`
(4 fixture trims), `doc/compatibility.html` (note removed, footer date bumped), `CLAUDE.md`
(deferred-issue index entry removed, count 7 → 6, prose updated). Diff: 2 insertions,
8 deletions across the two source/test files; no other source file touched.

**Verification.**

| Check | Result |
|-------|--------|
| Step-1 gate `./tmp/verification/2026-09-23-drop-dead-failed-confirmations-field-step1.py` | exit 0 (calibrated against three simulated trees before implementation) |
| Full suite `python tests/test_claude_proxy.py` | 322 passed, 0 failed, 322 total — run independently by the planner, matching the tester's numbers |
| `scripts/check_doc_anchors.py` | exit 0 — 159 anchors resolved, no secret shapes |
| Phase-6 reviewer (Sonnet) | "Issues found — non-blocking": 0 Critical, 1 Warning, 0 Suggestion |

Suite total is unchanged at 322 — fixtures only, no tests added or removed, per the user's
decision. The 1 warning ("No `proxy_stop` event in trace") is the pre-existing deferred issue
`no-proxy-stop-trace-warning`, unrelated to this plan.

**Known caveats.** None outstanding. The reviewer's single Warning — the deferred-issue report
file still reading `status: "Open"` — was fixed during close-out; the report is now
`type: "resolution"`, `status: "Resolved"`, `resolved_by:
2026-09-23-drop-dead-failed-confirmations-field`, with the standard `resolution` /
`changes_made` / `verification` fields matching the shape of the 13 sibling resolved reports.
The reviewer independently confirmed removal completeness, in-memory throttle integrity,
backward/forward compatibility, absence of orphaned consumers, and that no test became vacuous.

**No deferrals.** No issue was filed during this plan — coder and tester reports both carry empty
`issues_filed` arrays, and none of the pre-existing deferred issues were touched.

## Cross-References to Prior Plans

| Prior Plan | Deferred Issue | Resolution |
|------------|---------------|------------|
| 2026-09-12-build-doc-tree | `compat-entry-failed-confirmations-dead-field` — filed in that plan's Issue Log and History ("Filed `compat-entry-failed-confirmations-dead-field` (a persisted entry field that is never incremented)"), and carried as one of its two surviving findings in `CLAUDE.md`'s Future Work prose | Removed the dead field from the persisted schema (`_compat_validate_entry` + `_compat_learn`), trimmed the four test fixtures, and deleted the "A vestigial field" note that plan's Step 6 tester-verify instruction required `doc/compatibility.html` to carry |

## Commit Log

```
- consolidated — 2026-09-23 — 2 interim commits folded into one
```
