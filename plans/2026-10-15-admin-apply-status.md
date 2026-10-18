# Plan: Admin page — visible apply status, in-flight-swap awareness, and swap-time button locking
**Project:** D:\proj\claude-retry-proxy
**Plan ID:** 2026-10-15-admin-apply-status
**Created:** 2026-10-15

## Immediate Actions

Action-only directives. **Every lane has landed.** Steps 1–4, 4.5 and 4.6 are implemented in `src/claude_retry_proxy/admin.html`; tester round 4 is green (425 passed / 0 failed / 0 skipped, no issues filed); the Step 6 documentation sync landed on 2026-10-17 and its second pass on 2026-10-18, both with the doc gates green; the Phase 6 review returned non-blocking, and every finding of substance it raised is closed. **Every non-deferred row in the `## Issue Log` is `Resolved`; two rows are `Deferred`.**

**Planner — the only remaining work:**
- `## Final Results` is written and the implementation review is presented. Next: `/update-and-commit`.

**Deliberately deferred, not fixed here — enumerated under their own headings in `## Final Results`:** `admin-unrendered-page-apply-throws` (same repo, filed by this plan, pre-existing and adjacent to its subject but outside it), plus the two claude-config deferrals coder round 6 filed — `plan-issue-reports-never-merged-to-resolved` and `deferral-and-plan-scoped-report-coexist`.

**Verification state at close:** `./tmp/verification/2026-10-15-admin-apply-status-step3.py` reads **30/30** and `./tmp/verification/2026-10-15-admin-apply-status-step4.py` reads **42/42** on the shipped `src/claude_retry_proxy/admin.html`. The Step 4 script's calibration holds in both directions: against the pre-fix literal copy under `tmp/pre46/` it fails **exactly the 6** Step 4.6 checks, so the gate is red-capable and satisfiable at the same time.

## Issue Log

Rows ordered newest-first (latest issues at top). New issues are prepended; resolved issues stay in place with updated status.

| Issue | Status | Found | Resolved | Resolved By |
|-------|--------|-------|----------|-------------|
| [step4-gate-stale-load-reread](./tmp/reports/2026-10-15-admin-apply-status-step4-gate-stale-load-reread.json) | Resolved | 2026-10-18 | 2026-10-18 | [planner](./tmp/reports/2026-10-15-admin-apply-status-step4-gate-stale-load-reread.json) |
| [plan-issue-reports-never-merged-to-resolved](./tmp/reports/defer-issue-plan-issue-reports-never-merged-to-resolved.json) (finding: [issue-reports-not-marked-resolved](./tmp/reports/2026-10-15-admin-apply-status-issue-reports-not-marked-resolved.json)) | Deferred | 2026-10-18 | — | — |
| [deferral-and-plan-scoped-report-coexist](./tmp/reports/defer-issue-deferral-and-plan-scoped-report-coexist.json) (finding: [duplicate-deferral-report](./tmp/reports/2026-10-15-admin-apply-status-duplicate-deferral-report.json)) | Deferred | 2026-10-18 | — | — |
| review-final-load-path-re-read-unguarded | Resolved | 2026-10-17 | 2026-10-18 | [coder](./tmp/reports/2026-10-15-admin-apply-status-coder-2026-10-18.json) |
| review-final-load-path-reread-after-await | Resolved | 2026-10-17 | 2026-10-18 | [coder](./tmp/reports/2026-10-15-admin-apply-status-coder-2026-10-18.json) |
| review-final-stale-branch-quote-brittle | Resolved | 2026-10-17 | 2026-10-18 | [tester](./tmp/reports/2026-10-15-admin-apply-status-tester-2026-10-18.json) |
| immediate-actions-contradicts-its-bullets | Resolved | 2026-10-17 | 2026-10-17 | [planner](./tmp/reports/2026-10-15-admin-apply-status-immediate-actions-contradicts-its-bullets.json) |
| step4-gate-stale-reload-stale-branch | Resolved | 2026-10-17 | 2026-10-17 | [planner](./tmp/reports/2026-10-15-admin-apply-status-step4-gate-stale-reload-stale-branch.json) |
| reload-stale-re-read-result-ignored | Resolved | 2026-10-17 | 2026-10-17 | [coder](./tmp/reports/2026-10-15-admin-apply-status-coder-2026-10-17-5.json) |
| attach-settled-inner-guard-unreachable | Resolved | 2026-10-17 | 2026-10-17 | [coder](./tmp/reports/2026-10-15-admin-apply-status-coder-2026-10-17-5.json) |
| step3-gate-stale-config-reload-stale | Resolved | 2026-10-17 | 2026-10-17 | [planner](./tmp/reports/2026-10-15-admin-apply-status-step3-gate-stale-config-reload-stale.json) |
| audit-reload-stale-row-not-refreshed | Resolved | 2026-10-17 | 2026-10-17 | [coder](./tmp/reports/2026-10-15-admin-apply-status-coder-2026-10-17-4.json) |
| audit-attach-settled-repaint | Resolved | 2026-10-17 | 2026-10-17 | [coder](./tmp/reports/2026-10-15-admin-apply-status-coder-2026-10-17-4.json) |
| coder-guidance-stale-step-scope | Resolved | 2026-10-17 | 2026-10-17 | [planner](./tmp/reports/2026-10-15-admin-apply-status-coder-guidance-stale-step-scope.json) |
| attach-settle-double-tick | Resolved | 2026-10-17 | 2026-10-17 | [coder](./tmp/reports/2026-10-15-admin-apply-status-coder-2026-10-17-3.json) |
| step3-gate-stale-attachsettled | Resolved | 2026-10-17 | 2026-10-17 | [planner](./tmp/reports/2026-10-15-admin-apply-status-step3-gate-stale-attachsettled.json) |
| review-unlock-on-failed-rerender | Resolved | 2026-10-17 | 2026-10-17 | [coder](./tmp/reports/2026-10-15-admin-apply-status-coder-2026-10-17-2.json) |
| review-attachsettled-cross-talk | Resolved | 2026-10-17 | 2026-10-17 | [coder](./tmp/reports/2026-10-15-admin-apply-status-coder-2026-10-17-2.json) |
| review-load-path-no-rerender | Resolved | 2026-10-17 | 2026-10-17 | [coder](./tmp/reports/2026-10-15-admin-apply-status-coder-2026-10-17-2.json) |
| [admin-unrendered-page-apply-throws](./tmp/reports/defer-issue-admin-unrendered-page-apply-throws.json) | Deferred | 2026-10-17 | — | — |
| admin-pending-status-invisible | Resolved | 2026-10-15 | 2026-10-17 | [tester](./tmp/reports/2026-10-15-admin-apply-status-tester-2026-10-17.json) |
| admin-page-blind-while-swap-in-flight | Resolved | 2026-10-15 | 2026-10-17 | [tester](./tmp/reports/2026-10-15-admin-apply-status-tester-2026-10-17.json) |

Both motivating issues are `Resolved` on the tester's report at [2026-10-15-admin-apply-status-tester-2026-10-17](./tmp/reports/2026-10-15-admin-apply-status-tester-2026-10-17.json): full suite 425 passed / 0 failed / 0 skipped, both target tests passing alone with a live proxy and inside the suite, and the new assertions proven red-capable against the pre-fix page.

The three `review-*` issues were the Phase 6 reviewer's Warnings, each **reproduced by execution** and each an instance of this plan's own core hazard (a press carrying a pre-swap baseline that reverts a completed swap). All three are `Resolved` by coder round 2's Step 4 (report at [2026-10-15-admin-apply-status-coder-2026-10-17-2](./tmp/reports/2026-10-15-admin-apply-status-coder-2026-10-17-2.json)), with the new Step 4 script passing and the planner confirming the shipped code.

`step3-gate-stale-attachsettled` was filed against the **planner's own** Step 3 script: it still asserted the shared `attachSettled` latch that Step 4(b) deliberately removes, so it reported 1 of 30 FAIL on any correct Step 4 tree — a gate that goes red against its own plan's prescribed change cannot distinguish "later step landed" from "earlier steps regressed". `Resolved` by the planner repointing that one assertion at the per-attach generation guards (the script is `./tmp/verification/`, planner-authored, so fixing it is the planner's lane); it now reports 30/30 on the Step 4 tree.

`attach-settle-double-tick` is `Resolved` by **Step 4(a)'s `settled` flag** (whose necessity Step 4(e) now states), shipped in coder round 3 at [2026-10-15-admin-apply-status-coder-2026-10-17-3](./tmp/reports/2026-10-15-admin-apply-status-coder-2026-10-17-3.json). Coder round 2 implemented Step 4(e) (retaining the interval across the re-render await) exactly as specified, and then measured that the step's own justifying clause was false: the generation guard rejects only a *newer* attach, and no new attach can arm while `attachPollHandle !== null`, so two ticks of the SAME attach both reach the settle branch and both paint a terminal line. Bounded (an unlock only ever follows a *successful* re-render, so no stale-baseline write is reopened) but a misleading line. The plan's rationale was the defect; the fix is the per-attach `settled` flag, declared per attach, set before the await, and asserted by the Step 4 script's three `settled` checks (which were red against the pre-fix tree and are green now).

`coder-guidance-stale-step-scope` was also filed against a **planner** artifact — the second such finding in this plan. `## Guidance for Coder` still scoped the round to "implement Steps 1–3 in order" after the post-review revision added Step 4, so coder round 3 reconstructed its task from the Issue Log and History. Coder round 2 had raised it in prose and the revision that followed left it unfixed, so it is `Resolved` here by rewriting that paragraph to name the outstanding lanes and to point a future round at `## Immediate Actions` as its scope of record.

## Guidance for Coder

**Files to modify:**
- `src/claude_retry_proxy/admin.html`

**Step-by-step with verification:** Steps 1–4, Step 4.5 and Step 4.6 are the coder's sequence (Step 4 across coder rounds 2–3; Step 4.5 in rounds 4–5; **Step 4.6 is the round still to run**). Each coder step carries its own `(auto)` checks and `(scripted)` checks via `./tmp/verification/2026-10-15-admin-apply-status-step3.py` (Steps 1–3, 30 checks) and `./tmp/verification/2026-10-15-admin-apply-status-step4.py` (**42 checks**, covering Steps 4, 4.5 and 4.6). The coder self-verifies `(auto)` checks and runs the provided scripts for the `(scripted)` checks. **A coder round's scope of record is the `## Immediate Actions` block above** — not this line (issue `coder-guidance-stale-step-scope`: this paragraph once scoped the round to "implement Steps 1–3 in order" and went stale when Step 4 was added).

**No coder step remains open.** Step 4.6 landed in coder round 6 (2026-10-18), which implemented the load path's gate verbatim in `src/claude_retry_proxy/admin.html`; the Step 4 script read `FAIL: 6 of 42` before that round and reads **42/42 PASS** after it. The one red that survived the round was a defect in the script itself (`step4-gate-stale-load-reread`), repaired by the planner in the same revision — not an implementation failure, and not something a coder round should be asked to work around.

Lane constraints for this round:

- `admin.html` is the round's ONLY editable file. Do NOT touch `tests/` — `test_admin_html_poll_guard_after_await` currently pins exactly two `setInterval(async …)` blocks and WILL be red after this change; that red is planned and owned by Step 4 (tester lane). Do not edit it, do not "fix" it, and do not restructure the page to keep it green.
- Preserve the existing idioms verbatim: `textContent`-only status rendering (never `innerHTML`), and the two `if (swapSettled)` guards inside each press poll block (top-of-callback + post-await, both before any repaint). Step 2 changes only what it names.
- **Supply the code as written.** The two 409-branch done-texts, `swapWaitText`, `setSwapControlsDisabled`, and `refreshTiersFromServer` are given literally — do not reword them, shorten them, or re-derive a string the plan did not give you. `swapWaitText`'s `typeof st.budget_s === 'number'` guard is required, not decorative.
- The lockout helper must restore `populateKeys`' single-key rule when unlocking (a single-key provider's key select stays disabled), and the unlock must run after the completion re-render — not before, or `renderTiers()` will re-enable the selects after the unlock.
- The live proxy caches `admin.html` in-process (`_admin_html_cache`); that is an operational note for the operator after restart, not a coder step.

## Guidance for Tester

**Tests to create:**
- **Permanent (revision):** update `tests/test_admin.py::test_admin_html_poll_guard_after_await` — the page now carries THREE `setInterval(async () => {…}, 1000);` blocks (saveConfig, reloadConfig, and the new attach watcher). Assert the per-block guard **by block identity, positionally** — identify each callback by the function that ENCLOSES it (`_POLL_BLOCK_OWNERS`) and assert `if (swapSettled)` twice for the saveConfig and reloadConfig blocks and `if (myGeneration !== attachGeneration)` twice for the `attachToInFlightSwap` block, keeping the two-guard requirement and the post-await guard-before-repaint ordering check. **(Superseded: the earlier candidate-set derivation `("swapSettled", "attachSettled")` — Step 4(b) removed that latch, so a literal implementation is red on a correct tree, which the tester measured.)** Update the docstring (what it pins + the unchanged honest limit that it pins source ordering, not runtime behaviour).
- **Permanent (new):** add `tests/test_admin.py::test_admin_html_pending_status_styled` — serves the page via the existing `_start_admin_proxy` pattern and asserts on the served HTML: (a) a `.status.pending` CSS rule whose body contains `display: block`; (b) the disabled-button rule's selector list contains `button.secondary:disabled:hover` as well as `button:disabled` (the plain `button:disabled` alone does NOT outrank `button.secondary:hover`); (c) no `showStatus(''` / `showStatus(""` empty-type call remains (this call shape is the exact defect this plan fixes — nothing else in the suite would have caught it); (d) `showStatus('pending'` occurs at ≥ 6 call sites (2 press entry paints + 2 press repaints + 2 attach-watcher paints — a threshold of 4 is satisfied by the press sites alone and would pass with the watcher's paints deleted); (e) `attachToInFlightSwap` and `checkInFlightSwapOnLoad` are defined and invoked; (f) both button ids (`apply-btn`, `reload-btn`) are present; (g) the lockout helper disables the tier selects as well as the buttons, and restores the single-key rule on unlock (`populateKeys`' `keys.length <= 1`); (h) `noteAttachPollFailure` is defined and invoked, and its threshold constant appears; (i) `refreshTiersFromServer` is invoked from the attach completion; (j) the pending line carries the "no need to refresh" guidance and the poll-failure line tells the operator to reload. Register it in the module's aggregator list at the bottom of `test_admin.py` (~line 2828).

**Tests to investigate for retirement:** none — the one existing structural test is revised, not retired.

**Reviewer-driven hardening (Step 5).** The Phase 6 review found three of the new pins weaker than they read. Close them:

- **Which flag belongs to which block (reviewer Suggestion 6).** The done-flag derivation accepts any single candidate occurring ≥ 2 times, so a mutant where all three blocks guard on the same flag passes — and in that mutant both press paths lose their real `swapSettled` re-check. Assert the flag **by block identity**. Identity must be **positional — the function that encloses the callback** (`_POLL_BLOCK_OWNERS`), not a marker inside the block: neither press callback contains its handler's fetch (the switch/reload POST sits outside the `setInterval`), and the two press callbacks are byte-identical, so no in-block marker can distinguish them — and a name marker *could* be forged by any block, whereas an enclosing function cannot. Assert `if (swapSettled)` twice for each press block and `if (myGeneration !== attachGeneration)` twice for the attach block (Step 4(b) removed the `attachSettled` latch this once keyed on).
- **The press-entry lock is unpinned (Suggestion 7).** Deleting `setSwapControlsDisabled(true);` from `reloadConfig()` leaves every probe green, and the coder-lane script's `>= 6` threshold against 7 actual call sites misses it too. Assert that **both** press handlers call `setSwapControlsDisabled(true)` before their fetch — assert it by block, not by a file-wide count.
- **Dead disjunct (Suggestion 9).** In the re-render-before-unlock check, `unlock_at` is searched from `refresh_at + 1`, so the `refresh_at > unlock_at` disjunct can never be true. Drop it and compare the two positions directly after a single search of the body.
- **Quote-literal brittleness (Suggestion 10).** The pending call-site count and the lockout field-list probe match exact single-quoted literals, so a cosmetic re-quote fails the suite with a misleading message. Make those patterns quote-agnostic and match the field list loosely. The file's pre-existing pins are already quote-insensitive code-structure patterns; match that idiom.
- **New assertion for the failed re-read (Warning 1).** Add a probe pinning that a **failed** `refreshTiersFromServer` leaves the controls locked and does not paint the success text — the correction the reviewer's Warning 1 requires, which nothing currently guards.

Run the full suite (`python tests/test_claude_proxy.py`); it must be green (the doc-anchor check runs inside it). Per `doc/test-catalog.html`'s "Adding a test" checklist, also run the new test **alone** (`python tests/test_claude_proxy.py -t admin-html-pending-status-styled`) and confirm it passes with a live proxy running — an ordering-dependent test is a documented anti-pattern in that same page. Report the two test names and the suite counts (test functions and files) so the planner can sync `doc/test-catalog.html`, including its front-matter suite total.

**Tester round 3 scope (landed 2026-10-17 — SUCCESS, 425 passed / 0 failed / 0 skipped, no issues filed).** It added the **reload-stale-locked** probe — Step 4.5(c)/(d)'s correction. The hazard: on `409 config_reload_stale` the tier row is one swap behind by construction (server.py emits it only when a concurrent switch *completed*), so unlocking on a **failed** re-read would leave a stale baseline actionable — the plan's own core hazard. It pinned:

- the `config_reload_stale` branch in `reloadConfig` captures the re-read result (`const refreshed = await refreshTiersFromServer();`) rather than discarding it;
- its failure path sets `reloadStaleUnresolved = true` and paints the sticky "reload this page before applying" line — **not** the "has been refreshed" success text;
- `reloadConfig`'s `finally` holds the lock when that flag is set (`if (attachPollHandle === null && !reloadStaleUnresolved)`), so the failed-re-read path does **not** call `setSwapControlsDisabled(false)`.

*(Retained as the record of what that round pinned; it is complete, not pending.)*

**Tester round 4 scope (the only outstanding test lane).** Three items, all keyed to the final Phase 6 review's findings and to the Step 4.6 fix the coder round will land:

- **F4 — the quote-literal brittleness (Suggestion).** At `tests/test_admin.py:3131` the `config_reload_stale` discriminator is matched against an exact single-quoted literal, so a cosmetic re-quote fails the suite with a misleading message. Make the pattern **quote-agnostic** (`['"]config_reload_stale['"]`, or a match on the identifier with the quote class) and keep the surrounding assertion unchanged. The file's pre-existing pins are already quote-insensitive code-structure patterns; match that idiom.
- **Probe (q) — the load path gates on its re-read (Warning F1).** Pin that `checkInFlightSwapOnLoad`'s no-swap branch captures the re-read result, and that a **failed** re-read locks the controls (leaving them locked rather than unlocked), paints the sticky "reload this page before applying" line, and **returns** instead of falling through. This is the same hazard the attach and reload-stale sites already gate against: server.py installs `_current_config` *after* the drain, and `/admin/api/switch` has **no** staleness guard, so an unlocked pre-swap row would write that baseline back.
- **Probe (r) — the post-await press-guard re-check (Suggestion F2).** Pin that the load path re-asserts `setSwapControlsDisabled(true)` **after** its re-read await when `swapPollHandle !== null || attachPollHandle !== null || swapSettled`. `renderTiers()` rebuilds the nine selects as fresh enabled nodes, so a press that started inside that fetch has just had its lock destroyed; without the re-check this call site is the only re-render that unlocks.

Prove each new assertion **red-capable** against the pre-fix shape (the bare `await refreshTiersFromServer();` with no gate) — a pin whose failing branch cannot fire is not a pin (see `doc/test-catalog.html`'s anti-patterns). Note that Step 4.6 adds a **tenth** `showStatus('pending'` call site; any `≥ N` threshold check remains green, but the planner must move `doc/test-catalog.html`'s recorded count **9 → 10** in the same pass.

Then re-run the full suite and report the counts.

Deliverables to report back: the test names touched/added, the suite counts (functions and files), and the pass/fail of the alone-run with a live proxy. This is the last lane before the planner's Step 6 doc sync.

## Summary

**Problem.** An operator press of Apply during a live drain shows nothing at all. Root cause, verified in the served page: the pending line is emitted as `showStatus('', …)` → `className = 'status '` — and the stylesheet only assigns `display: block` to `.status.success` / `.status.error`, so every pending message (initial line and every 1 Hz update) renders invisible. The live incident of 2026-10-15 (haiku mimo→deepseek, `config.json` written 11:03, zero `swap_abort` events = clean drain) additionally showed: a page refresh loses the press's waiter entirely (the server-side swap continues, but the page is blind); a second press during the in-flight swap is refused `409 config_swap_in_progress` and dead-ends in a 5 s red line; and the buttons stay pressable throughout.

**Approach (user-confirmed scope 1+2+lockout; lockout covers the selects too).**
1. Give the pending state its own styled class and make it sticky (terminal success/error keep the 5 s auto-hide). `showStatus` manages a single timer (clear-then-schedule), which also fixes a stale timer being able to hide a later sticky line.
2. Lock the **entire switch surface** — both buttons *and* all nine tier selects — from the moment a swap is in play (this page's press, a detected swap, or an attached one) until it ends. The pending line carries the operator guidance.
3. Detect an in-flight swap the page did not press — on page load, and when a press is refused `409 config_swap_in_progress` — and hand off to an **attach watcher** that keeps the pending line repainting at 1 Hz until the server reports `swapping: false`, then re-renders the tier row from the server and unlocks.

```
press ──► controls locked (2 buttons + 9 selects) ──► sticky pending line ──► poll /admin/api/swap-status 1 Hz
   ├─ 200 → success line + drain detail            → controls unlocked (finally)
   ├─ 409 config_swap_in_progress → attach watcher (controls stay locked;
   │        its completion: re-fetch the tier row, unlock, "…make your changes again")
   └─ other error → error line                     → controls unlocked (finally)

page load ──► one-shot swap-status ── swapping? ──► attach watcher ──► re-fetch tier row ──► unlock
                                            └─ no → nothing changes
```

**Key design decisions.**
- **The lockout covers the selects, not just the buttons**, and that is what makes the completion re-render safe: with no edit possible while a swap is in play, refreshing the tier row cannot discard the operator's work.
- **The attach watcher RE-RENDERS the tier row on completion, from both origins.** During a drain `_current_config` is still the pre-swap document (the switch installs it at `server.py:3518`, after the drain), so a page that loaded mid-drain paints the mapping the drain is about to replace; `/admin/api/switch` has no staleness guard, so a press from those values would silently revert the swap the page just announced as finished. Re-rendering is uniform — one rule, no per-origin special case — and the consequence is stated in the completion text: the operator's un-applied edits are discarded and re-entered against a truthful baseline.
- Only `config_swap_in_progress` attaches; `config_reload_stale` (reload path only) keeps its plain error line — no swap is in progress for that refusal.
- No auto-retry of a refused press (option 3 was offered and declined): the attach watcher reports the in-flight swap and re-renders; the operator presses again.
- The pending line says **"no need to refresh — this page follows the switch"**, not "do not refresh". A mid-swap refresh is harmless here: the fresh page's one-shot check attaches and re-locks. It was also the wrong instruction to pair with the poll-failure line, which has to tell the operator that reloading *is* the way out.
- A persistently failing `/admin/api/swap-status` is **not** cosmetically swallowed on the attach path (it is the watcher's only exit). After 5 consecutive failures the line says the proxy is unreachable and that reloading is now safe; the controls stay locked, because an unreadable status is not evidence that no swap is running.
- Server side unchanged: `/admin/api/swap-status` and the 409 envelope already carry everything the page needs.
- Rejected alternative: implementing the third poll with a non-`async` callback to dodge the structural test's regex — that would hide the new block from the test that pins the guard ordering, which is the wrong trade.
- Out of scope: auto-retry; any change to `server.py`; a JS test harness. **Split out to a follow-up plan:** single-active-page enforcement (claim-on-load session, `409 admin_session_retired` on every write, token in swap-status) — agreed with the user on 2026-10-17 and deliberately deferred so this one-file change can land first.

**Operational note.** The running proxy serves `admin.html` from a process-lifetime in-memory cache — after this plan lands and commits, the operator must restart the proxy (`claude-retry-proxy stop` → `start`) before the new page is served.

## Repo Mode

Public

*Detected at plan creation. Determines: plan archival path, commit-message content, staged files.*

## Document Overrides

| Document | Rule Overridden | Reason |
|----------|----------------|--------|

## Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| The page's JS has no runtime test harness, so a defect in the new attach/press interplay ships verified only structurally | The operator's next live press misbehaves in the same silent way this plan exists to fix | Keep the new code to the file's existing idioms, small self-contained callbacks; committed structural pins (3 poll blocks + per-block guards, styled pending class, no empty-type calls, attach + load-check present, select-inclusive lockout, the poll-failure signal, the completion re-render); the Step 3 scripted check; operator smoke-test of the live page after restart |
| Controls can remain locked if the page can never observe `swapping: false` (e.g. the proxy is stopped mid-swap) | The whole switch surface is unusable from that page until recovery | Bounded and signalled in the normal case: after 5 consecutive poll failures the line says the proxy is unreachable and that reloading is now safe, while retrying continues. A page reload always recovers (a fresh load's one-shot check finds no swap and leaves the controls enabled) — recorded in the README text. A drain that legitimately runs long keeps succeeding, so the line stays truthful and the elapsed/silence readout shows it is still progressing |
| The structural test is red between the coder and tester steps (it pins 2 poll blocks) | Round noise / an apparent regression in the coder report | Stated in Guidance for Coder: the red is planned, owned by Step 4 (tester), and the coder must not touch tests |

## Proposed Changes

Each step includes verification checks tagged with confidence.
`(auto)` = mechanical, coder self-verifies. `(scripted)` = deterministic multi-step, coder runs provided script.
Every step must have at least one verification check executable by its owner.

1. **Step 1:** `admin.html` — pending-status CSS and control ids. In the `<style>` block, after the `.status.error` rule (line 29), add `.status.pending { background: #0f3460; display: block; }`. After the existing `button.secondary:hover` rule (line 26), add:
   ```css
   button:disabled,
   button.secondary:disabled,
   button.secondary:disabled:hover { background: #3a3a4a; color: #9a9a9a; cursor: not-allowed; }
   ```
   The `button.secondary:disabled` / `:disabled:hover` selectors are **required, not defensive**: `button.secondary:hover` scores (0,2,1) and beats a bare `button:disabled` (0,1,1) regardless of source order, so without them a disabled *Reload* button under the pointer keeps painting the enabled hover colour `#607d8b`. (A bare `button:disabled` does suffice for Apply, whose plain `button:hover` ties at (0,1,1) and loses to the later rule — which is why the ordering this step previously described looked sufficient.) In the markup (lines 45–46), add `id="apply-btn"` to the Apply button and `id="reload-btn"` to the Reload button; change nothing else. No new CSS is needed for the selects — `select:disabled` already greys them (line 20).
   → coder verify (auto): the served file contains a `.status.pending` rule whose body has `display: block`; the disabled rule's selector list contains `button.secondary:disabled:hover` as well as `button:disabled`; `id="apply-btn"` and `id="reload-btn"` present.
   → coder verify (scripted): covered by the Step 3 script's CSS assertions.

2. **Step 2:** `admin.html` — sticky status helper, lockout helper, and the press-path changes.
   (a) Add module state beside `swapPollHandle`/`swapSettled`:
   ```js
   let attachPollHandle = null;
   let attachPollFailures = 0;
   let statusTimer = null;
   ```
   (**`let attachSettled = false;` belonged here in the original plan and is deliberately absent:** Step 4(b) replaced that shared latch with a per-attach `attachGeneration` counter plus a closure-scoped `settled` flag, so the latch is never declared. Do not add it back.)
   (b) Replace `showStatus` with a version that manages a single timer (clear-then-schedule). Terminal lines keep the 5 s auto-hide; a sticky line is never hidden by a timer scheduled for an earlier line:
   ```js
   function showStatus(type, message, sticky) {
       const el = document.getElementById('status');
       if (statusTimer !== null) { clearTimeout(statusTimer); statusTimer = null; }
       el.className = 'status ' + type;
       el.textContent = message;
       if (!sticky) {
           statusTimer = setTimeout(() => { el.className = 'status'; statusTimer = null; }, 5000);
       }
   }
   ```
   (c) Add three helpers:
   ```js
   // Live pending line from a swap-status payload. prefix differs by context:
   // 'applying — ' (a press) vs 'config swap in progress — ' (a swap this
   // page did not press). Falls back to the base text when no detail is
   // available (initial paint, or a transient zero in-flight reading).
   // Every numeric field is guarded before interpolation — including
   // budget_s, whose absence must fall back rather than render "… / null s…".
   function swapWaitText(st, prefix) {
       const tail = ' (no need to refresh — this page follows the switch)';
       if (st && typeof st.inflight === 'number' && st.inflight > 0 &&
           st.silence_s !== null && typeof st.budget_s === 'number') {
           return prefix + 'waiting for ' + st.inflight + ' in-flight request(s), silence ' +
               Math.floor(st.silence_s) + 's / ' + st.budget_s + 's…' + tail;
       }
       return prefix + 'waiting for in-flight requests…' + tail;
   }

   // Lock the entire switch surface — both buttons AND all nine tier
   // selects — for as long as a swap is in play. Locking the selects is
   // what makes the completion re-render safe: no edit can be in flight.
   function setSwapControlsDisabled(disabled) {
       for (const id of ['apply-btn', 'reload-btn']) {
           const el = document.getElementById(id);
           if (el) { el.disabled = disabled; }
       }
       TIERS.forEach(tier => {
           for (const field of ['provider', 'model', 'key']) {
               const el = document.getElementById(tier + '-' + field);
               if (!el) { continue; }
               if (disabled) {
                   el.disabled = true;
               } else if (field === 'key') {
                   // Unlocking must RESTORE populateKeys' rule, not blanket-
                   // enable: a single-key provider's key select stays disabled.
                   const prov = document.getElementById(tier + '-provider');
                   const keys = providerKeys[(prov && prov.value) || ''] || [];
                   el.disabled = (keys.length <= 1);
               } else {
                   el.disabled = false;
               }
           }
       });
   }

   // Re-read the tier row from the server. Called on attach completion: the
   // document this page loaded may predate the swap that just installed.
   async function refreshTiersFromServer() {
       try {
           const resp = await fetch('/admin/api/config');
           if (!resp.ok) { return; }
           config = await resp.json();
           renderTiers();
       } catch (e) {
           // Cosmetic — the tier row keeps the values it already shows.
       }
   }
   ```
   (d) In BOTH `saveConfig()` and `reloadConfig()`, change exactly:
   - after `swapSettled = false;` add `setSwapControlsDisabled(true);`
   - the initial pending line becomes `showStatus('pending', swapWaitText(null, 'applying — '), true);`
   - inside the poll callback, the repaint becomes `showStatus('pending', swapWaitText(st, 'applying — '), true);` — the enclosing condition `if (st.swapping && st.inflight > 0 && st.silence_s !== null)` and both `if (swapSettled)` guards stay exactly as they are;
   - in the terminal handling, insert before the final `else`, with **both done-texts written out literally** (the reloadConfig string is not an ellipsis — the coder must not invent it). saveConfig:
   ```js
   } else if (result && result.error && result.error.code === 'config_swap_in_progress') {
       // Single-flight refusal: a swap this page did not press is in flight.
       // Hand off to the attach watcher — the controls stay locked and its
       // progress stays visible; the watcher re-renders the tier row on
       // completion, so the operator re-enters their changes against a
       // baseline that matches the server.
       attachToInFlightSwap('a config swap is already in progress — ',
           'the in-flight config swap completed — the tier list has been refreshed; make your changes again');
   }
   ```
   reloadConfig:
   ```js
   } else if (result && result.error && result.error.code === 'config_swap_in_progress') {
       attachToInFlightSwap('a config swap is already in progress — ',
           'the in-flight config swap completed — press Reload Providers again to refresh');
   }
   ```
   **Only `config_swap_in_progress` attaches** — `config_reload_stale` must fall through to the plain error line. The remaining `else` and the `catch` branch are unchanged.
   - in the `finally`, after `swapPollHandle = null;`:
   ```js
   // The 409 branch hands off to the attach watcher, which owns the locked
   // state until that swap ends; every other terminal path unlocks here.
   if (attachPollHandle === null) {
       setSwapControlsDisabled(false);
   }
   ```
   → coder verify (auto): no `showStatus(''` call remains in the file; `showStatus('pending'` count ≥ 6; `statusTimer` appears in the clear/schedule branches; `config_swap_in_progress` present in both handlers; `attachPollHandle === null` present in both `finally` blocks; `if (swapSettled)` still appears exactly 4 times; `setSwapControlsDisabled(true)` present before each press fetch; `button.secondary:disabled:hover` present in the disabled rule.
   → coder verify (scripted): `python ./tmp/verification/2026-10-15-admin-apply-status-step3.py` (its press-path and CSS assertions cover this step).

3. **Step 3:** `admin.html` — the attach watcher and the load-time swap check.
   (a) Add:
   ```js
   // SUPERSEDED AS A LITERAL — DO NOT TYPE THIS BLOCK VERBATIM.
   // This is Step 3's original code, kept as the historical record of what
   // Step 3 delivered. Step 4 (below) and Step 4.5 replaced its guards and
   // its completion: the shared `attachSettled` latch is gone (per-attach
   // `attachGeneration` + a closure `settled` flag instead), the completion
   // gates its unlock on a successful re-read, and a `settled` bail sits
   // before the `swapping === true` repaint. Step 4's supplied block is the
   // authoritative shape; a coder round must not reintroduce the latch.
   // Watch a swap this page did not press — detected on load, or refused 409
   // on a press. The controls stay locked and the pending line repaints at
   // 1 Hz until the server reports swapping false. Idempotent: a second call
   // is a no-op. Completion RE-RENDERS the tier row from the server: the
   // document this page loaded may predate the swap that just installed, so a
   // press from the values still on screen would write back a pre-swap
   // baseline (the same hazard the 409 refusal used to prevent by refusing).
   function attachToInFlightSwap(prefix, doneText) {
       if (attachPollHandle !== null) {
           return;
       }
       attachSettled = false;
       attachPollFailures = 0;
       setSwapControlsDisabled(true);
       showStatus('pending', swapWaitText(null, prefix), true);
       attachPollHandle = setInterval(async () => {
           if (attachSettled) {
               return;
           }
           try {
               const resp = await fetch('/admin/api/swap-status');
               if (!resp.ok) {
                   noteAttachPollFailure(prefix);
                   return;
               }
               const st = await resp.json();
               if (attachSettled) {
                   // Post-await re-check: a late response must never repaint
                   // over the terminal line.
                   return;
               }
               attachPollFailures = 0;
               if (!st.swapping) {
                   attachSettled = true;
                   clearInterval(attachPollHandle);
                   attachPollHandle = null;
                   await refreshTiersFromServer();
                   setSwapControlsDisabled(false);
                   showStatus('success', doneText);
                   return;
               }
               showStatus('pending', swapWaitText(st, prefix), true);
           } catch (e) {
               noteAttachPollFailure(prefix);
           }
       }, 1000);
   }

   // A poll failure is NOT cosmetic on this path, unlike in the press path:
   // a successful `swapping: false` read is the watcher's only exit and
   // nothing else unlocks the controls, so a persistent failure would leave
   // the page locked while still narrating progress. After 5 consecutive
   // failures (~5 s) the line says so and names the way out. Retrying
   // continues, and the controls stay locked — an unreadable status is not
   // evidence that no swap is running.
   function noteAttachPollFailure(prefix) {
       attachPollFailures += 1;
       if (attachPollFailures === 5) {
           showStatus('pending', prefix +
               'cannot reach the proxy — the switch may still be running; ' +
               'reload this page when it is back', true);
       }
   }
   ```
   (b) Add, and call it at the END of `loadConfig()` — after the `try`/`catch` block's closing brace, NOT inside the `try`. Inside the `try` it sits after `renderTiers()` and is skipped entirely when a config fetch rejects, which is precisely the case where the page most needs the lockout; after the `try`/`catch` it runs either way (`loadConfig` ends with `renderTiers(); }` at line 116–119, and the file's last block was an `innerHTML` template with no other trailing statements). Fire-and-forget is fine — it carries its own catch:
   ```js
   // A page loaded while a swap is in flight must say so immediately, not
   // only after the operator presses Apply and collects a 409.
   async function checkInFlightSwapOnLoad() {
       if (swapPollHandle !== null || attachPollHandle !== null) {
           return;
       }
       try {
           const resp = await fetch('/admin/api/swap-status');
           if (!resp.ok) {
               return;
           }
           const st = await resp.json();
           // Three conditions, and the third is the load-bearing one: the
           // handler checks catch a press that is RUNNING, while swapSettled
           // catches one that started AND finished inside this one-shot's
           // fetch→parse window — otherwise a swap this very page performed
           // would be re-attached, overwriting its own success line and
           // re-locking the controls. The pre-fetch handler check is
           // unreachable from today's single call site (`loadConfig` runs once,
           // before any press can exist) and is kept only as a cheap guard
           // against a future second caller.
           if (swapPollHandle !== null || attachPollHandle !== null || swapSettled) {
               return;
           }
           if (st.swapping) {
               attachToInFlightSwap('config swap in progress — ',
                   'the in-flight config swap completed — the tier list has been refreshed');
           }
       } catch (e) {
           // Cosmetic — a failed check must not brick the page.
       }
   }
   ```
   → coder verify (auto): `setInterval(async () => {` appears exactly 3 times; `function attachToInFlightSwap(` present and `attachToInFlightSwap(` total ≥ 4 (definition + both 409 branches + the load check); `checkInFlightSwapOnLoad` ≥ 2 occurrences; `if (attachSettled)` present ≥ 2 times; `noteAttachPollFailure` and `refreshTiersFromServer` each present ≥ 2 times; `setSwapControlsDisabled` present ≥ 6 times (definition + 2 press entries + 2 press finallies + attach entry + attach settle).
   → coder verify (scripted): `python ./tmp/verification/2026-10-15-admin-apply-status-step3.py` — 30 structural assertions over `admin.html`: the styled pending rule and the compound disabled-button selector, no empty-type calls, the sticky signature and single timer, exactly 3 poll blocks with their per-block done-flags, the attach watcher and load check at every call site (with the load check asserted OUTSIDE `loadConfig`'s `try`), both button ids, the select-inclusive lockout helper asserted **inside its own body** and its single-key restore, the 409 discriminator as a real branch condition in BOTH handlers with `config_reload_stale` absent, both literal done-texts, the preserved press repaint condition, the completion re-render asserted to precede the unlock **inside the attach block**, the poll-failure counter/threshold/message, and the no-refresh guidance. Prints one `ok`/`FAIL` evidence line per check plus a final `PASS:` summary; exits 0 on pass. Proven red against the pre-change tree (27 of 30 fail; the 3 greens are the pre-existing invariants the plan must preserve — the 4 `if (swapSettled)` guards, the absent `config_reload_stale`, and the press repaint condition).
   → tester verify: `test_admin_html_pending_status_styled` and the updated `test_admin_html_poll_guard_after_await` pass (Step 4).

4. **Step 4:** `admin.html` — close the Phase 6 reviewer's three Warnings (each reproduced by execution; report at [2026-10-15-admin-apply-status-review-2026-10-17](./tmp/reports/2026-10-15-admin-apply-status-review-2026-10-17.json)). All three are the same hazard: a press carrying a pre-swap baseline that reverts a completed swap.
   (a) **`review-unlock-on-failed-rerender`** — the completion unlocks and claims success even when the re-read failed (`refreshTiersFromServer` returns silently on `!resp.ok` at line 448 and swallows throws at 451–453, while the caller unlocks at 493 and paints the done-text at 494). Make the re-read report success and gate the unlock on it:
   ```js
   // Re-read the tier row from the server. Called on attach completion: the
   // document this page loaded may predate the swap that just installed.
   // Returns true only when the row was actually re-rendered — the caller
   // must NOT unlock on a failed read, or the operator re-enters the very
   // pre-swap baseline this re-render exists to replace.
   async function refreshTiersFromServer() {
       try {
           const resp = await fetch('/admin/api/config');
           if (!resp.ok) { return false; }
           config = await resp.json();
           renderTiers();
           return true;
       } catch (e) {
           return false;
       }
   }
   ```
   and in the attach settle branch (shown with (b)'s generation guard and (e)'s `settled` flag — see those clauses):
   ```js
   function attachToInFlightSwap(prefix, doneText) {
       if (attachPollHandle !== null) {
           return;
       }
       const myGeneration = ++attachGeneration;
       let settled = false;
       attachPollFailures = 0;
       setSwapControlsDisabled(true);
       showStatus('pending', swapWaitText(null, prefix), true);
       attachPollHandle = setInterval(async () => {
           if (myGeneration !== attachGeneration) {
               // A later attach owns the page now: only ever bail out.
               return;
           }
           try {
               const resp = await fetch('/admin/api/swap-status');
               if (!resp.ok) {
                   noteAttachPollFailure(prefix);
                   return;
               }
               const st = await resp.json();
               if (myGeneration !== attachGeneration) {
                   // Post-await re-check: a late response from a stale
                   // watcher must never repaint over the terminal line.
                   return;
               }
               attachPollFailures = 0;
               if (!st.swapping) {
                   // Per-attach settledness. The generation guard covers a
                   // NEWER attach; it cannot cover a second tick of THIS one,
                   // and the interval deliberately survives the await below
                   // (so the poll-failure signal keeps working), so without
                   // this flag two ticks would both settle and the later
                   // terminal line would win regardless of which re-read was
                   // truthful. Cleared implicitly: a new attach makes a new
                   // closure.
                   if (settled) {
                       return;
                   }
                   settled = true;
                   const refreshed = await refreshTiersFromServer();
                   clearInterval(attachPollHandle);
                   attachPollHandle = null;
                   if (refreshed) {
                       setSwapControlsDisabled(false);
                       showStatus('success', doneText);
                   } else {
                       // The tier row could not be re-read, so it may
                       // still be one swap behind. Stay locked and say
                       // so — unlocking here would let a press write
                       // that stale baseline back over the swap.
                       showStatus('pending', prefix +
                           'the config could not be re-read — reload this page before applying', true);
                   }
                   return;
               }
               showStatus('pending', swapWaitText(st, prefix), true);
           } catch (e) {
               noteAttachPollFailure(prefix);
           }
       }, 1000);
   }
   ```
   (b) **`review-attachsettled-cross-talk`** — `attachSettled` is one shared latch reset by every new attach (declared line 69, reset line 467), so a stale tick from a settled attach that resolves after the next attach arms passes the post-await check at 482 and settles the NEW watcher. Give each attach its own generation and compare that instead:
   - add module state beside `attachPollHandle`: `let attachGeneration = 0;`
   - in `attachToInFlightSwap`, replace the `attachSettled = false;` line with a per-attach capture:
   ```js
   const myGeneration = ++attachGeneration;
   ```
   - replace BOTH `if (attachSettled)` checks in the callback with `if (myGeneration !== attachGeneration)` (top-of-callback and post-await), keeping the existing comments' intent;
   - **remove `attachSettled` entirely** — it is referenced nowhere outside the attach body (verified: its only occurrences are the declaration and the attach callback; the press path uses `swapSettled` and `attachPollHandle === null`), so (a)'s code block below must be typed **with `attachSettled = true;` omitted**. (a) and (b) are otherwise one edit; where they appear to conflict, (b) wins and the scripted check enforces it.
   The effect: a stale callback can only ever bail out — it can no longer clear the current watcher's interval, unlock mid-swap, or paint a previous attach's done-text.
   (c) **`review-load-path-no-rerender`** — `checkInFlightSwapOnLoad` re-renders only when it attaches, so a drain ending between `loadConfig`'s config read (line 116) and this function's swap-status read (527) leaves the pre-swap row displayed with unlocked controls. Re-render on the no-swap branch too:
   ```js
   if (st.swapping) {
       attachToInFlightSwap('config swap in progress — ',
           'the in-flight config swap completed — the tier list has been refreshed');
   } else {
       // The drain may have completed between loadConfig's config read and
       // this read, which would leave the row one swap behind. Re-read it.
       await refreshTiersFromServer();
   }
   ```
   (d) **Suggestion 4 (cheap, do it):** in `swapWaitText`, guard `silence_s` with `typeof st.silence_s === 'number'` instead of `st.silence_s !== null`, for symmetry with the `inflight`/`budget_s` guards in the same condition (an omitted field would otherwise render `silence NaNs`).
   (e) **Suggestion 5 (cheap, do it):** in the attach settle branch, move the `clearInterval(attachPollHandle); attachPollHandle = null;` pair to **after** `await refreshTiersFromServer()`, so a never-settling config fetch cannot leave the page locked with no watcher and no poll-failure signal. That move is what makes the `settled` flag in (a) **required rather than defensive**: with the interval still live across the await, a second tick of the same attach would otherwise re-enter the settle branch and repaint a terminal line over the first (issue `attach-settle-double-tick`, found in coder round 2). The generation guard alone does NOT cover this — it rejects only a *newer* attach, and no new attach can arm while `attachPollHandle !== null`.
   (f) **Suggestion 8 (do it):** add a comment above the module-level state declaring each attach's generation, and a comment on the `settled` flag stating that the interval survives the re-render await deliberately, which is why per-attach settledness is needed on top of the generation guard.
   → coder verify (auto): `refreshTiersFromServer` returns `false` on both the `!resp.ok` and `catch` paths and `true` after `renderTiers()`; the settle branch reads `const refreshed = await refreshTiersFromServer();` and calls `setSwapControlsDisabled(false)` **only** inside `if (refreshed)`; `attachGeneration` is declared, incremented once per attach, and both callback checks compare `myGeneration !== attachGeneration`; no `attachSettled` remains anywhere in the file; `let settled = false;` is declared per attach and the settle branch returns early when it is already true; `checkInFlightSwapOnLoad` has an `else { await refreshTiersFromServer(); }` branch on `st.swapping`; `typeof st.silence_s === 'number'` present; in the settle branch `clearInterval(attachPollHandle)` appears **after** `await refreshTiersFromServer()`; comments document the generation and the settled flag.
   → coder verify (scripted): `python ./tmp/verification/2026-10-15-admin-apply-status-step4.py` — asserts the (a)–(f) invariants structurally, including that no unlock is reachable on a failed re-read, that the settle branch is enterable at most once per attach, and that the interval is retained across the re-render await. Exits 0 with one `PASS:` line.
   → tester verify: the Step 6 assertions pin the corrected shapes (see "Guidance for Tester"), including that a **failed** re-read leaves the controls locked.

5. **Step 4.5:** `admin.html` — close the post-implementation audit's two behavioural findings (report at [2026-10-15-admin-apply-status-mega-audit-2026-10-17-post](./tmp/reports/2026-10-15-admin-apply-status-mega-audit-2026-10-17-post.json)). Both are instances of the same hazard this plan exists to close, and both were **verified in the shipped code by the planner**.
   (a) **`config_reload_stale` leaves a stale row unlocked** (Medium, defect-tracer). The Summary claimed `config_reload_stale` needs no handling because "no swap is in progress for that refusal" — that reasons about the wrong condition. `server.py:3667-3678` emits it *because* a concurrent `/admin/api/switch` completed between the reload's gated tier read and its compare-and-install, so the page's row is one swap behind **by construction**. Shipped behaviour: it falls to `showStatus('error', 'Error: …')` (non-sticky, auto-hides) and the `finally` unlocks because `attachPollHandle === null` — leaving an unlocked, stale, unlabelled surface whose next Apply writes the pre-switch mapping back. It is the one asymmetric survivor of Step 4(c)'s rule. Fix: give this branch the same treatment — re-read the row before unlocking. In `reloadConfig`'s error handling, insert before the final `else`:
   ```js
   } else if (result && result.error && result.error.code === 'config_reload_stale') {
       // A concurrent switch completed while this reload's candidate was
       // being prepared, so the tier row on screen predates it. Re-read the
       // row before unlocking, or the next Apply writes that pre-switch
       // baseline back — the same hazard the attach path closes. This is a
       // terminal refusal with no swap to watch, so the controls unlock
       // right after the re-read; the row is what must not be stale.
       await refreshTiersFromServer();
       showStatus('error', 'The configuration changed while reloading — the ' +
           'tier list has been refreshed; press Reload Providers again');
   }
   ```
   Note this branch is **reload-only**: `/admin/api/switch` has no stale-candidate guard, so `saveConfig` needs no counterpart. `config_reload_stale` must still never *attach* — but the claim that "Step 3's check 17 stays true" was **false**: check 17 was a whole-file absence assertion, which this step makes unsatisfiable by putting the literal into the page. It is repointed to the surviving invariant (asserted against the branch body, not the file) in the same act (issue `step3-gate-stale-config-reload-stale`).
   (b) **The attach callback can repaint over its own terminal line** (Medium, edge-case-explorer — a regression introduced by Step 4(b)). `settled` is consulted only inside `if (!st.swapping)`. The `st.swapping === true` repaint now runs for any response passing the post-await check, and that check compares `myGeneration !== attachGeneration`, which is **false for the same attach** — so a tick whose response was generated while the swap still ran but is delivered after a sibling tick settled repaints the sticky pending line over the terminal line, with the interval already cleared and nothing to correct it. Pre-Step-4 the shared latch covered this incidentally. Fix: add an early bail after the post-await generation check, before the `!st.swapping` branch:
   ```js
   if (settled) {
       // A sibling tick of THIS attach already settled: its terminal line
       // stands, and the interval is cleared so nothing would correct a
       // repaint here.
       return;
   }
   ```
   The flag is per-closure, so no cross-attach cross-talk returns; the check must sit **after** the awaits because `clearInterval` cannot stop an already-queued tick.
   (c) **`reload-stale-re-read-result-ignored`** — (a) above is wrong as written: it calls `refreshTiersFromServer()` as a bare statement, discarding the boolean that Step 4(a) added *precisely* so no caller could unlock on a failed re-read. On a failed re-read it therefore still unlocked **and** still claimed "the tier list has been refreshed" — the same defect class as the Phase 6 Warnings, on the reload path. Replace (a)'s branch with a gated version, and teach the `finally` to hold the lock. In `reloadConfig`, declare the flag immediately **before** its `try {`:
   ```js
   // Set when a stale-refusal's tier re-read FAILED: the row may still be one
   // swap behind, so the finally below must not hand back an actionable
   // surface. Mirrors the attach path's failed-re-read contract.
   let reloadStaleUnresolved = false;
   try {
   ```
   replace (a)'s branch body with:
   ```js
   } else if (result && result.error && result.error.code === 'config_reload_stale') {
       // A concurrent switch completed while this reload's candidate was
       // being prepared, so the tier row on screen predates it. Re-read it
       // before unlocking, or the next Apply writes that pre-switch baseline
       // back — the same hazard the attach path closes.
       const refreshed = await refreshTiersFromServer();
       if (refreshed) {
           showStatus('error', 'The configuration changed while reloading — the ' +
               'tier list has been refreshed; press Reload Providers again');
       } else {
           reloadStaleUnresolved = true;
           showStatus('pending', 'The configuration changed while reloading, and ' +
               'the tier list could not be re-read — reload this page before applying',
               true);
       }
   }
   ```
   and in the same function's `finally`, extend the existing condition:
   ```js
   if (attachPollHandle === null && !reloadStaleUnresolved) {
       setSwapControlsDisabled(false);
   }
   ```
   (`saveConfig` gets no counterpart — `/admin/api/switch` has no stale-candidate guard, so it can never see this code. `reloadStaleUnresolved` is a per-press local, so no cross-press state leaks.)
   (d) **`attach-settled-inner-guard-unreachable`** — Step 4.5(b)'s bail makes Step 4(a)'s inner `settled` guard dead: no `await` and no write to `settled` sits between them, so the inner guard's failing branch can never fire, while the Step 4 script was pinning it. **Retire Step 4(a)'s inner guard** — delete the `if (settled) { return; }` that sits inside `if (!st.swapping)` (keep its explanatory comment above the surviving `settled = true;` if it still reads correctly there), and keep only Step 4.5(b)'s earlier bail, which covers the same condition *and* additionally covers the `st.swapping === true` repaint the inner guard never protected. The Step 4 script's superseded `settled flag set inside the settle branch` check is retired with it (its two ordering checks already pin the surviving bail).
   → coder verify (auto): in `reloadConfig`, `let reloadStaleUnresolved = false;` appears before the `try {`, the `config_reload_stale` branch reads `const refreshed = await refreshTiersFromServer();` and sets `reloadStaleUnresolved = true` **only** in its else, and the `finally`'s unlock condition reads `attachPollHandle === null && !reloadStaleUnresolved`; in the attach body exactly **one** `if (settled)` remains and it sits before `if (!st.swapping)`.
   → coder verify (scripted): `python ./tmp/verification/2026-10-15-admin-apply-status-step4.py` — the retired check is replaced by ones asserting the gated reload unlock and that exactly one (pre-`!st.swapping`) `settled` bail exists.
   → tester verify: `test_admin_html_pending_status_styled` gains a probe that the reload-stale failure path leaves the controls locked; the suite stays green.
   → tester verify: `test_admin_html_pending_status_styled` gains probes for the reload-stale re-read branch and the pre-repaint `settled` bail (see "Guidance for Tester"); the suite stays green.

5b. **Step 4.6:** `admin.html` — close the **final Phase 6 review's** Warning and its companion Suggestion at one call site (report at [2026-10-15-admin-apply-status-review-2026-10-17-final](./tmp/reports/2026-10-15-admin-apply-status-review-2026-10-17-final.json)). Both are the same call site — `checkInFlightSwapOnLoad`'s `else` branch — and both are the plan's own core hazard: the reviewer **reproduced them by execution** in a stub DOM/fetch harness (`./tmp/verification/2026-10-17-review-final-harness.js`, scenarios T4 and T7). This is the **third asymmetric survivor** of the guard discipline Step 4(a) and Step 4.5(c) applied at the other two call sites, so the fix is the shape already used twice — not a new design.
   (a) **`review-final-load-path-re-read-unguarded`** (Warning, correctness, `admin.html:602`). `checkInFlightSwapOnLoad` calls `refreshTiersFromServer()` as a bare statement, throwing away the success flag Step 4(a) added *precisely so no caller could act on a failed re-read*. `refreshTiersFromServer` returns `false` on `!resp.ok` and in its `catch`; the reload-stale site (line 385) and the attach-settle site (line 532) both gate on it. When this re-read fails, the page keeps the row `loadConfig` read — which, in the branch this code exists for, is the **pre-swap** document (`server.py:3518`/`3672` install `_current_config` *after* the drain) — unlocked, unlabelled and pressable; `/admin/api/switch` has no staleness guard (only reload does), so the operator's next Apply writes the pre-swap baseline back over the swap that just completed. Reachability is narrow (both GETs are loopback, so `/admin/api/config` must fail after a successful `/admin/api/swap-status` read) — but narrow is exactly the profile of the two hazards this plan already closed.
   (b) **`review-final-load-path-reread-after-await`** (Suggestion, correctness). The same call site re-checks the press guards *before* the swap-status fetch but not *after* `await refreshTiersFromServer()`, and `renderTiers()` rebuilds the nine selects as fresh, enabled nodes. A press that starts inside that one fetch window therefore has its select lock destroyed and its in-progress edit re-rendered away (measured: the buttons stay locked, because `renderTiers` never touches them, but the selects come back editable and the row reverts to the server's baseline — the pre-press document in that window).
   **Supplied fix** — replace the load path's `} else { … }` branch (currently `admin.html:598-603`) with exactly this:
   ```js
   } else {
       // The drain may have completed between loadConfig's config read and
       // this read, which would leave the row one swap behind. Re-read it —
       // but gate on the result: a failed re-read must NOT leave a
       // possibly-pre-swap row unlocked and pressable, because
       // /admin/api/switch has no staleness guard and the next Apply would
       // write that baseline back. Same discipline as the reload-stale and
       // attach-completion sites.
       const refreshed = await refreshTiersFromServer();
       if (!refreshed) {
           setSwapControlsDisabled(true);
           showStatus('pending', 'the tier list could not be re-read — ' +
               'reload this page before applying', true);
           return;
       }
       // renderTiers() rebuilt the selects as fresh enabled nodes, so a press
       // that started inside that fetch has just had its lock dropped.
       // Re-assert the guards now, after the await, or the load path is the
       // only re-render site that can unlock a press.
       if (swapPollHandle !== null || attachPollHandle !== null || swapSettled) {
           setSwapControlsDisabled(true);
       }
   }
   ```
   Note the ordering in the failure branch: lock **then** paint, and `return` so the post-await guard block cannot run and re-unlock. The success path keeps the re-check (b) requires. `showStatus`'s third argument is `sticky`, so the pending line does not auto-hide.
   → coder verify (auto): at `checkInFlightSwapOnLoad`'s `else` branch, `const refreshed = await refreshTiersFromServer();` is captured (not discarded); an `if (!refreshed)` branch immediately follows and calls **both** `setSwapControlsDisabled(true)` and `showStatus('pending', … , true)` before a `return`; and a second press-guard check (`swapPollHandle !== null || attachPollHandle !== null || swapSettled`) sits **after** that await, whose only body is `setSwapControlsDisabled(true)`.
   → coder verify (scripted): `python ./tmp/verification/2026-10-15-admin-apply-status-step4.py` — the script grew **34 → 42** checks; the eight additions cover the load-path body, the captured re-read result, the failure branch (exists, locks, does not unlock, paints the sticky line, returns), and the post-await guard block's position. It read **`FAIL: 6 of 42`** against the pre-Step-4.6 tree and the same six against the pre-fix literal copy under `tmp/pre46/` — measured, not assumed — and reads **42/42 PASS** once the round landed the branch. (Two of the eight pass on the pre-fix tree too: "load-path body extracted" — the function exists — and "failure branch does not unlock" — an absent branch trivially lacks the call. They are guard checks for the extracted-shape checks beside them, not independent RED evidence.) **The same revision had to repoint Step 4(c)'s `no-swap branch re-reads the tier row`,** which pinned the bare `await` this step replaces (issue `step4-gate-stale-load-reread`); it now matches either spelling, so the script can actually reach 42/42.
   → tester verify: `test_admin_html_pending_status_styled` gains probes (q) the load path's failure branch locks and paints the sticky reload line without claiming a refresh, and (r) the post-await guard block sits after the re-read await; both proven red-capable against the pre-fix literal. The suite stays green.

6. **Step 5:** Tester — structural test updates and the full-suite run. Revise `tests/test_admin.py::test_admin_html_poll_guard_after_await` for three poll blocks with per-block done-flags (see "Guidance for Tester"), add `test_admin_html_pending_status_styled` covering assertions (a)–(j), register it in the module aggregator, run it alone with a live proxy (`-t admin-html-pending-status-styled`), then run `python tests/test_claude_proxy.py` to green. Additionally close the reviewer's test-hardening Suggestions 6, 7, 9 and 10, add the Step 4.5 probes, **add the Step 4.6 probes (q)/(r), and close the final review's `review-final-stale-branch-quote-brittle`** — the (m)/(n)/(o) probes enter the stale branch through the single-quoted literal `"code === 'config_reload_stale')"`, so a behaviour-identical re-quote blanks the extraction and fails with a diagnosis that is not true. Match it quote-agnostically instead, as (g) already does for its field list:
   ```python
   stale_at = re.search(r"code\s*===\s*['\"]config_reload_stale['\"]", reload_body)
   stale_branch = _js_braced_block(reload_body, stale_at.start()) if stale_at else ""
   ```
   (see "Guidance for Tester").
   → tester verify: both tests pass, individually and in the full suite; the full suite reports 0 failed; the two test names plus the suite counts (test functions and files) are reported for the doc-catalog sync.

7. **Step 6:** Planner — documentation sync once Steps 1–5 have landed. Anchors below were re-measured on 2026-10-17 (the three doc files moved in commits `e080d73` / `5ddfaa3` / `80a4ffe` after this plan was written; locate by content, not by number): `doc/operations.html` §admin (the single-flight 409 paragraph, now lines 201–209, gains the page's attach behavior; the swap-status/status-line paragraph, now 211–219, gains "the page polls at 1 Hz while a press is pending **or** an in-flight swap is detected (on load / after a 409 refusal), locking both buttons and all nine tier selects meanwhile, and re-renders the tier row from the server when the swap ends"); `doc/test-catalog.html` — this page carries the touched count in **three** places, all of which must move together: the front-matter table's `test_admin.py` row (line 131, reads **34** today), the `tests/test_admin.py (N tests)` section header (line 577, reads **36** today), and the front-matter **suite total** in the warn box (line 21, "424 test functions across 19 files"). `test_admin.py` registers 37 tests after Step 5 and the suite counts 425 across 19 files (verified with the doc's own recipe `grep -cE 'def (test_|doc_)' tests/*.py`). Follow the warn box's own convention for the total: move 424 into the drift-history chain ("It read 424 across 19 before this recount, …") and set the headline to 425 — **and move the drift COUNT in the same sentence from "fifteen times" to "sixteen times"**, since the chain becomes 16 entries (post-implementation audit, High: the count was not enumerated, so the page would have contradicted itself — the documented recurring failure here). Also update the revised `test_admin_html_poll_guard_after_await` entry (now line 614) and the new `test_admin_html_pending_status_styled` entry, and refresh the `test_admin.py` "Covers" cell to mention the attach watcher, the select-inclusive lockout, and the completion re-render. `README.md` §Admin page (now lines 398–417 — add the live status line, the locks on both buttons and the tier selects while any swap is in flight, the **409 origin** (a refused press attaches to the in-flight swap and stays locked; reword the existing "a second press … is refused with `409` and changes nothing" so the *config* changes nothing while the page follows the swap), the automatic re-attach after a refresh, the "no need to refresh" guidance, the poll-failure message, the "locked until a verified re-read" contract, and the two facts a reader needs: that the page's lockout is an affordance and the real single-flight guard is server-side in `_drain_for_swap`, and that the running proxy serves `admin.html` from a process-lifetime in-memory cache so the proxy must be restarted before the new page is served). **`CLAUDE.md` DOES need two changes** (reverse of the earlier "no change" claim, per the audit): add the new deferral `admin-unrendered-page-apply-throws` to the `Unresolved Deferred Issues` JSON block, and move the Future Work prose from "Nine deferred issues remain" to ten — CLAUDE.md's own invariant is that every report on disk is listed, and the block currently lists 9 against 10 files. Its admin-api bullet needs no page-UX change beyond that. Bump the "Last updated" stamps on touched pages.
   → planner Evidence: `git diff --stat` naming exactly the four doc files (`README.md`, `CLAUDE.md`, `doc/operations.html`, `doc/test-catalog.html`); the reconciled `test_admin.py` counts (front-matter row and section header) and the suite total each match a fresh run of the doc's own recipe; the doc-anchor check's PASS output (N anchors resolved) from a suite run.

## Guidance for Planner

Documentation tasks you will execute yourself (not the coder):

- **Files to modify:**
  - `./README.md`
  - `./CLAUDE.md` — **two edits** (the `Unresolved Deferred Issues` block gains `admin-unrendered-page-apply-throws`; the Future Work prose moves "Nine deferred issues remain" → ten). The earlier "No `CLAUDE.md` change" line in this section was wrong and is superseded: the plan files a deferral, and CLAUDE.md's own invariant is that every report on disk is listed.
  - `doc/operations.html`
  - `doc/test-catalog.html`
- **`.claude/mega-audit-files.json`:** no change — the file is absent in this repo and no declared audit location is added, renamed, or retired.
- **When:** after the coder and tester rounds land (Step 5), before final closeout.
- **What to sync:** the three items in Step 5 — `doc/operations.html` (#admin: the 409 paragraph and the swap-status/status-line paragraph, including the lockout's reach over the tier selects and the completion re-render), `doc/test-catalog.html` (the revised structural test's entry, the new test's entry, the `test_admin.py` count in both the front-matter row and the section header, the `test_admin.py` "Covers" cell, and the front-matter suite total moved to 425 across 19 with 424 appended to the drift chain **and the drift count moved from "fifteen times" to "sixteen times"**), `README.md` (§Admin page: status line, locks covering the buttons and the selects, re-attach after refresh, "no need to refresh", the poll-failure message, the reload-stale locked-until-a-verified-re-read contract, the server-side single-flight fact, and the proxy-restart requirement). Bump "Last updated" stamps.

## History

One row per event (spec revision / mega-audit / review / implementation round). Conclusion = one-sentence outcome or what changed. Dismissed = compact dismissed-findings list for the reviewer — verbatim issue slugs linked as `[<slug>](<report-path>)`, no prose-only entries.

| Date | Event | Conclusion | Dismissed |
|------|-------|------------|-----------|
| 2026-10-18 | Spec revision (user instruction, pre-commit) | User, on being shown the closeout: "we no longer maintain a deferred issues list in CLAUDE.md, remove it in the following /update-and-commit." Applied. The `## Unresolved Deferred Issues` section (heading + JSON block, 4,982 chars) and the three deferred-issue paragraphs that opened `## Future Work — TODO` (3,621 chars) are deleted; that section's refactor-backlog prose is untouched. `CLAUDE.md` 39,957 → 31,354 chars. **This removes four edits this plan made rather than superseding them** — Step 6 added one entry, then the post-coder-6 revision grew the block to twelve — so the plan is now the only record that the index existed, and `## Documentation` and `## Final Results` were corrected to say so instead of pointing at a section that is gone. Independently justified, not merely obeyed: `planner.md`'s "Deferred-issue awareness" step defines the corpus as `./tmp/reports/defer-issue-*.json` with **presence meaning open** and states that reports are machine-local, so the `CLAUDE.md` block was a second hand-maintained copy of a list the command surface had already stopped writing. Deleting it removes the class of drift this plan spent two rounds correcting. | [CLAUDE.md-edit-superseded](./tmp/plans/2026-10-15-admin-apply-status.md) — recorded that a plan whose Step 6 writes into a file another lane is simultaneously retiring leaves a plan-text trail that must be corrected at close, here twice (the `## Documentation` bullet and `## Final Results`). |
| 2026-10-18 | Spec revision (/update-plan, post-tester 4) | Tester round 4 closed the last open issue; `review-final-stale-branch-quote-brittle` moved `Fix Planned` → `Resolved` and **every non-deferred row in the Issue Log is now `Resolved`**. Step 6 documentation re-opened for the measured discrepancies the round reported and closed: `doc/test-catalog.html`'s `test_admin_html_pending_status_styled` entry moved **20 → 22 evidence lines** and `(a)–(p)` → `(a)–(r)`, the pending call-site count moved **9 → 10** with its own parenthetical enumeration gaining the load path's failed-re-read term (the count and its enumeration would otherwise have contradicted each other — the exact self-contradiction that page's warn box names), and the closing sentence now credits **both** mutation-based proof scripts rather than round 3's alone. Folded the load path into the "locked until a verified re-read" contract in `README.md` and `doc/operations.html`, which named only the reload-stale and attach sites; both doc stamps moved to 2026-10-18. Audit counters advanced to **4 / 2 / 0** with the trigger check recorded — 4 ≥ 3 resolved but 2 steps and 0 files < 3, so no re-audit. | — |
| 2026-10-18 | Implementation round (tester) — 4, succeeded | `overall_result: SUCCESS`; suite **425 passed / 0 failed / 0 skipped**, both doc gates green (doc-structure 9 files no violations; doc-anchor 204 anchors, run inside the suite). All three items landed in `tests/test_admin.py::test_admin_html_pending_status_styled`, taking it to **22 evidence lines (a)–(r)**: (F4) the `config_reload_stale` discriminator is matched quote-agnostically, so a behaviour-identical re-quote can no longer blank the (m)–(o) extraction and fail with a diagnosis that was not true; (q) the load path's gated re-read, pinned across six independent clauses; (r) its post-await press-guard re-check, pinned positionally. No issue filed. Report at [2026-10-15-admin-apply-status-tester-2026-10-18](./tmp/reports/2026-10-15-admin-apply-status-tester-2026-10-18.json). Red-capability was established by execution, not assertion: round 4's own proof script runs the same predicates over **13 cases** — the live page, a pre-fix shape derived by programmatic reversal of Step 4.6's branch and required to be byte-identical to the plan's own literal, and 11 anchored mutants. | [proof-script-head-baseline](./tmp/reports/2026-10-15-admin-apply-status-tester-2026-10-18.json) — round 2's proof script uses `git show HEAD:…admin.html` as its PRE case, still correct because nothing is committed; once `/update-and-commit` lands, HEAD becomes the post-plan page and that script's "new" probes would read green against what is then the fixed tree. Flagged for the planner's closeout rather than fixed. [no-runtime-harness](./tmp/reports/2026-10-15-admin-apply-status-tester-2026-10-18.json) — the honest limit is unchanged and now uniform across all three call sites: the admin-HTML tests pin source ordering on the served page, not runtime JS behaviour; the reviewer's stub DOM/fetch harness `./tmp/verification/2026-10-17-review-final-harness.js` remains the plan's only runtime evidence. |
| 2026-10-18 | Spec revision (/update-plan, post-coder 6) | Coder round 6 completed Step 4.6, closing the final review's Warning F1 and its companion Suggestion F2; both `review-final-*` rows moved `Fix Planned` → `Resolved`. **Repointed the Step 4 script's Step 4(c) check `no-swap branch re-reads the tier row`** (issue `step4-gate-stale-load-reread`): it pinned the BARE `await refreshTiersFromServer();` that Step 4.6 replaces with the CAPTURED form, so it was green PRE-fix and red on a tree implementing Step 4.6 verbatim — 42 of 42 was unreachable, and the next reader would have read that red as an implementation regression. It now asserts the branch's intent against the brace-extracted branch, which holds for both spellings; the script reads **42/42 PASS** on the shipped tree and **6 of 42** red (exactly the Step 4.6 checks) against the pre-fix literal. **Two corpus-hygiene findings deferred to `claude-config`** (`plan-issue-reports-never-merged-to-resolved`, `deferral-and-plan-scoped-report-coexist`), with `CLAUDE.md`'s `Unresolved Deferred Issues` block and the Future Work prose moved 10 → 12 entries and "three of the ten" → "five of the twelve". Immediate Actions and Guidance rewritten: tester round 4 is the only lane left. | `deferral-and-plan-scoped-report-coexist` — recorded that filing these two deferrals reproduces the shape that issue describes: each new deferral sits beside the coder's plan-scoped finding for the same topic, so the Issue Log rows link both files rather than leaving one orphaned. |
| 2026-10-18 | Implementation round (coder) — 6, succeeded | Exit 0; Step 4.6 implemented verbatim — `checkInFlightSwapOnLoad`'s `} else {` branch grows 6 → 23 lines (+21/−4), capturing the re-read result, gating on it, and re-checking the press guards after the await. `build_result: pass`; `admin.html` the only file modified. Report at [2026-10-15-admin-apply-status-coder-2026-10-18](./tmp/reports/2026-10-15-admin-apply-status-coder-2026-10-18.json). The round filed THREE issues, each verified by measurement rather than asserted. `step4-gate-stale-load-reread` is a defect in the **planner's** Step 4 script — the **fourth** stale gate this plan has produced and the **seventh** finding against a planner artifact — proven in both directions by re-running the script with its `ADMIN` constant overridden: **41 of 42** post-fix with that one check red, **6 of 42** pre-fix with that same check **green**, so no single file can satisfy both it and the Step 4.6 code. The other two are corpus-bookkeeping findings (`issue-reports-not-marked-resolved`, `duplicate-deferral-report`), neither touching this plan's deliverables; both are now `Deferred`. | [gate-defect-not-implementation-defect](./tmp/reports/2026-10-15-admin-apply-status-step4-gate-stale-load-reread.json) — the sole residual red was the gate, and the shipped branch matches the plan's supplied code verbatim apart from indentation; no source change was warranted, and the coder correctly declined to restructure the branch to dodge the regex. |
| 2026-10-17 | Spec revision (/update-plan, post-final-review) — user-directed one more round | The final review's verdict was non-blocking, and the user directed one more round rather than finalizing with caveats. First fixed its four documentation nits (F5–F8), all in text this plan had just written. Then added **Step 4.6** with the fix supplied as exact code, closing the Warning **F1** (`review-final-load-path-re-read-unguarded`) and its companion Suggestion **F2** (`review-final-load-path-reread-after-await`) — one call site, `checkInFlightSwapOnLoad`'s `else` branch, the **third asymmetric survivor** of the guard discipline Step 4(a) and Step 4.5(c) applied at the other two. The three `review-final-*` issues move `Open` → `Fix Planned`. Tester round 4 scope written into `## Guidance for Tester`: **F4**'s quote-agnostic discriminator at `tests/test_admin.py:3131`, plus probes **(q)/(r)** pinning both halves of the Step 4.6 fix; the round-3 scope paragraph retained as the record of what that (landed) round pinned. `## Immediate Actions`, `## Guidance for Coder` and the Plan Metadata `steps` array rewritten to match, since all three still described round 3 or the doc sync as outstanding. **The Step 4 script grew 34 → 42 checks, and its RED was calibrated in both directions**: `FAIL: 6 of 42` against the live pre-Step-4.6 tree and the same six against the pre-fix literal copy under `tmp/pre46/` (the two non-failing additions are guard checks beside the extracted-shape checks, not independent evidence). Note for the doc sync that Step 4.6 makes the pending call-site count **9 → 10**, so `doc/test-catalog.html`'s recorded count must move with it. | — |
| 2026-10-17 | Review (Phase 6, final pass) | `Issues found — non-blocking` — **0 Critical, 1 Warning, 7 Suggestions**, at [2026-10-15-admin-apply-status-review-2026-10-17-final](./tmp/reports/2026-10-15-admin-apply-status-review-2026-10-17-final.json). The reviewer closed the first pass's suite-not-re-run gap (ran the full suite: 425/0/0, matching tester round 3) and **discharged all four of the first review's hunches and its five `areas_not_fully_verified` items by measurement**, building a stub DOM/fetch/timer harness (`./tmp/verification/2026-10-17-review-final-harness.js`, 40 checks) that executes the page's real `<script>` text — the browser-level evidence four prior passes could not produce. It confirmed the Step 4.5 code by measurement, not reading: flipping the `settled` bail to `if (false)` makes a late sibling repaint the progress line over the terminal success line with the interval already cleared, so the bail is load-bearing; exactly one `if (settled)` survives, before `if (!st.swapping)`; `reloadStaleUnresolved` is a per-invocation `let` with no cross-talk (concurrent presses are unreachable — both handlers lock the whole surface synchronously before their first await); the extended `finally` holds the lock on the only path that sets the flag; `attachGeneration` cannot overflow in any reachable lifetime. Doc counts re-derived independently (37; 425 across 19; 16-entry drift chain). | [review-final-F1](./tmp/reports/2026-10-15-admin-apply-status-review-2026-10-17-final.json) — **Warning, `admin.html:602`**: the load path's tier re-read discards the boolean (`await refreshTiersFromServer();`), so a failed re-read leaves a possibly **pre-swap** row unlocked, unlabelled and pressable — the third asymmetric survivor of the discipline Step 4(a)/4.5(c) applied at the other two call sites, and this plan's own core hazard. Reproduced by execution (harness T4: the row keeps the pre-swap model, controls enabled, status element empty, and a subsequent `saveConfig()` posts it and gets 200). Reachable only when the loopback `/admin/api/config` GET fails after a successful swap-status read; unpinned by the suite. **Not fixed in this pass — presented to the user for the fix-or-accept decision** (a coder-lane one-line change of the shape already used twice, plus a tester pin). [F2](./tmp/reports/2026-10-15-admin-apply-status-review-2026-10-17-final.json) — the same call site is not re-guarded after its await, so a press starting inside that fetch has its select lock dropped and its edits blanked. [F3](./tmp/reports/2026-10-15-admin-apply-status-review-2026-10-17-final.json) — terminal "reload this page" lines are painted with the in-progress `pending` class; the reviewer **refuted** the first pass's entanglement rationale (stickiness is now a separate argument), promoting it from hunch to finding. [F4](./tmp/reports/2026-10-15-admin-apply-status-review-2026-10-17-final.json) — the new (m)/(n) probes extract the stale branch through a single-quoted literal, re-opening Suggestion 10 at a new site. [F5](./tmp/reports/2026-10-15-admin-apply-status-review-2026-10-17-final.json) — README says the 1 Hz repaint shows "how long it has waited"; it renders `silence_s`/`budget_s` (`waited_s` is terminal-line only). [F6](./tmp/reports/2026-10-15-admin-apply-status-review-2026-10-17-final.json) — the new test's catalog entry mis-enumerates the pending call-site probe and omits (k)/(l). [F7](./tmp/reports/2026-10-15-admin-apply-status-review-2026-10-17-final.json) — CLAUDE.md's "that last one" now reads as the newly inserted non-cross-repo deferral. [F8](./tmp/reports/2026-10-15-admin-apply-status-review-2026-10-17-final.json) — Step 6's Evidence line says "the three doc files" while the sync's scope is four. |
| 2026-10-17 | Spec revision (/update-plan, post-coder 5) | Closed the last two open issues — both planner artifacts, both already `Resolved`: the duplicate Issue Log row for `attach-settled-inner-guard-unreachable` (Resolved + a stale Fix Planned twin) and the round-5 History row that a heredoc escape mangled into three pipes. Then repaired four further stale artifacts this same revision exposed, per the gates-track-what-they-pin rule: `## Immediate Actions` still directed coder round 5 (it landed), `## Guidance for Coder` still reported the Step 4 script at 23 checks (it is 34), its `## Immediate Actions` pointer said "below" for a section that sits above, `## Audit Accumulation` carried a superseded paragraph contradicting its own correction, and `## Documentation` still claimed `CLAUDE.md` needed no change (it needs two). Test scope for round 3 written into `## Guidance for Tester`. Also recorded round 5's completion and the exit of the Phase 4.6 loop cap. No design change; no source change. | — |
| 2026-10-17 | Implementation round (coder) — 5, succeeded | Exit 0; Step 4.5(c) and (d) implemented verbatim (4 edits: the `reloadStaleUnresolved` declaration, the gated stale branch, the extended `finally` condition, and the retired inner guard). Both scripts now green: Step 3 **30/30**, Step 4 **34/34** (after the planner's fix below). Report at [2026-10-15-admin-apply-status-coder-2026-10-17-5](./tmp/reports/2026-10-15-admin-apply-status-coder-2026-10-17-5.json). The round filed two issues, **both against planner artifacts and both Resolved by the planner**. `step4-gate-stale-reload-stale-branch`: the Step 4 script extracted the stale branch with the non-greedy regex `(.*?)\n\s*\} else`, which stops at the FIRST `} else` — and Step 4.5(c) introduces exactly that inner delimiter, so `reloadStaleUnresolved = true;` fell outside the capture and the check could never fire. Fixed by brace-balanced extraction (the script's existing `function_body`), proven non-vacuous: the branch now yields 990 chars containing the flag and demonstrably contains a nested `} else`. `immediate-actions-contradicts-its-bullets`: the `## Immediate Actions` block opened by asserting no coder or tester round was outstanding while its own first bullet directed coder round 5 — and the line **survived the revision that made it more wrong**, having been recorded in prose by round 4. Opening line rewritten to name the actual lanes. This is the fourth and fifth planner-artifact finding this plan has produced, and the third stale-gate; the implementation has been green since round 3. | [gate-defect-not-implementation-defect](./tmp/reports/2026-10-15-admin-apply-status-step4-gate-stale-reload-stale-branch.json) — the one residual red was a gate defect, and the shipped code already satisfied Step 4.5(c)'s auto-verify line as written; no code change was warranted. |
| 2026-10-17 | Spec revision (/update-plan, post-coder 4) — user-directed beyond the loop cap | The Phase 4.6 loop cap (4 iterations) was reached with two issues open; the user directed one more round rather than finalizing with caveats. Step 4.5 gains **(c)** and **(d)** with the fixes supplied as exact code: (c) gates the reload-stale unlock on the re-read's boolean (`const refreshed = …`, a `reloadStaleUnresolved` local declared before the `try`, and an extended `finally` condition), closing `reload-stale-re-read-result-ignored`; (d) retires Step 4(a)'s inner `settled` guard, which Step 4.5(b) made unreachable, closing `attach-settled-inner-guard-unreachable`. The Step 4 script retires its dead-guard check and adds five (c)/(d) checks — 5 of 33 red on the current tree, all genuine. | [loop-cap-overrun](./tmp/reports/2026-10-15-admin-apply-status-coder-2026-10-17-4.json) — recorded as a deliberate user decision, not an oversight; the fourth consecutive round in which findings landed against planner artifacts rather than the implementation. |
| 2026-10-17 | Implementation round (coder) — 4, succeeded | Exit 0; Step 4.5 implemented (Step 4 script 26/29 on entry — exactly the three Step 4.5 checks red — 29/29 after; +17 lines, 0 removed). Both audit Mediums' fixes landed. Report at [2026-10-15-admin-apply-status-coder-2026-10-17-4](./tmp/reports/2026-10-15-admin-apply-status-coder-2026-10-17-4.json). The round filed THREE issues, all verified by the planner. `step3-gate-stale-config-reload-stale` (against the planner's Step 3 script, the third stale-gate this plan has produced): check 17 asserted `config_reload_stale` was absent page-wide, which Step 4.5(a) makes impossible by putting the literal into the page; repointed to the surviving invariant (asserted against the branch body, non-vacuously — the branch extracts at 753 chars and genuinely lacks an attach call) and **Resolved**. The other two are defects in the code **the planner supplied in Step 4.5**: `reload-stale-re-read-result-ignored` — Step 4.5(a) discards `refreshTiersFromServer()`'s boolean, so a FAILED re-read still unlocks AND still claims 'the tier list has been refreshed', reintroducing on the reload path the exact hazard Step 4(a) closed on the attach path; and `attach-settled-inner-guard-unreachable` — Step 4.5(b)'s bail makes Step 4(a)'s inner `settled` guard dead (no await or write between them), and **a Step 4 script check pins that now-unfirable guard**. Both `Fix Planned`; see `## Immediate Actions`. | [step3-check-17-scope](./tmp/reports/2026-10-15-admin-apply-status-step3-gate-stale-config-reload-stale.json) — the whole-file absence shape was the defect, not the intent; the intent is preserved and tightened. [loop-cap-approached](./tmp/reports/2026-10-15-admin-apply-status-coder-2026-10-17-4.json) — this is coder round 4 inside the Phase 4.6 loop, at the cap; the remaining two findings are escalated to the user rather than auto-continued. |
| 2026-10-17 | Mega-audit (post-implementation) + spec revision | 10 lenses, 1 High + 8 Medium + 21 Low, at [2026-10-15-admin-apply-status-mega-audit-2026-10-17-post](./tmp/reports/2026-10-15-admin-apply-status-mega-audit-2026-10-17-post.json). This audit was **mandated and had been silently not firing**: the Audit Accumulation table read 2/0/0 while the History recorded 5 then 7 resolved and 3 steps changed, so each `/update-plan` concluded the Phase 5 trigger unmet. Counters corrected to 8/3/0 and the audit run. Two Mediums are real behavioural defects the Ph6 review missed, both verified in the shipped code by the planner: **`config_reload_stale` leaves a stale row unlocked** (`server.py:3667` emits it *because* a switch completed, so the row is one swap behind by construction — the one asymmetric survivor of Step 4(c)'s rule) and **the attach callback can repaint over its own terminal line** (a regression Step 4(b) introduced: `settled` gates only `!st.swapping`, while the post-await generation check is false for the same attach). Both closed by new **Step 4.5**. The High is the doc drift COUNT (`fifteen times` must become `sixteen`) — added to Step 6. Also fixed three stale plan-text sites that still prescribed the removed `attachSettled` latch (Guidance for Tester's derivation, Step 2(a)'s state block, Step 3(a)'s code block marked superseded, Step 3's auto-verify line), and **added the `## Immediate Actions` block** the previous revision pointed at while it did not exist (the same defect with a different target). Counters reset by this audit. | [medium-8-providerkeys-empty-advisory](./tmp/reports/2026-10-15-admin-apply-status-mega-audit-2026-10-17-post.json) — a failed `providers-detail` leaves `providerKeys` empty so a press re-pins every multi-key tier to its first key; pre-existing (the same empty map disables the key selects today) and out of this plan's scope, but recorded rather than dropped. [low-27-boundary-claude-md](./tmp/reports/2026-10-15-admin-apply-status-mega-audit-2026-10-17-post.json) — the deferred-issue index gap is fixed by Step 6, not deferred. [low-3-summary-diagram](./tmp/reports/2026-10-15-admin-apply-status-mega-audit-2026-10-17-post.json) — the Summary flow diagram predates Step 4(c)'s else-branch; cosmetic. [low-extra](./tmp/reports/2026-10-15-admin-apply-status-mega-audit-2026-10-17-post.json) — the remaining Lows (swapWaitText endpooint drift guard, comment-density, an unreachable pre-fetch guard, doc-anchor/count spot-checks) are acknowledged, none blocking. |
| 2026-10-17 | Spec revision (/update-plan, post-tester 2) | Tester round 2 closed all five reviewer Suggestions; no issues filed. Corrected the **Audit Accumulation counters**, which had read 2/0/0 while the History recorded 5 then 7 resolved and 3 steps changed: the Phase 5 re-audit trigger (≥3 resolved AND ≥3 steps or files) was met and had been silently not firing for two revisions. Counters corrected to 8/3/0 and the post-implementation mega-audit launched. Also corrected the Step 5 identity-marker text the tester proved unworkable (the plan prescribed an in-block marker; identity must be positional, by enclosing function). | — |
| 2026-10-17 | Implementation round (tester) — 2, succeeded | `overall_result: SUCCESS`; suite 425 passed / 0 failed / 0 skipped, both tests passing alone with a live proxy and in the suite. All five reviewer Suggestions this step absorbed are closed and MEASURED. The round-1 revision's declared red was reproduced by running it (`Step 4(b)` removed the `attachSettled` latch, so the candidate scan found no flag for the third callback) and is closed by asserting the guard PER BLOCK, identified by its enclosing function. `test_admin_html_pending_status_styled` gained (k) both press handlers arm the lock before their own fetch, and (l) a failed re-read stays locked, skips the success line and tells the operator to reload. Report at [2026-10-15-admin-apply-status-tester-2026-10-17-2](./tmp/reports/2026-10-15-admin-apply-status-tester-2026-10-17-2.json). | [suggestion-6-marker-does-not-work](./tmp/reports/2026-10-15-admin-apply-status-tester-2026-10-17-2.json) — the plan's prescribed in-block identity marker ("the blocks containing saveConfig/reloadConfig's fetch") cannot work: neither press callback contains its handler's fetch and the two are byte-identical, so identity had to be positional (the enclosing function) — strictly stronger, since an enclosing function cannot be forged. Plan text corrected to say so. [exact-call-site-count-not-added](./tmp/reports/2026-10-15-admin-apply-status-tester-2026-10-17-2.json) — the count alternative to Suggestion 7 was declined in favour of the by-block assertion, which is stronger (the count is satisfied by the press sites alone). |
| 2026-10-17 | Spec revision (/update-plan, post-coder 3) | Coder round 3 closed `attach-settle-double-tick` with the per-attach `settled` flag; both scripts green (Step 3 30/30, Step 4 23/23) and the planner confirmed the shipped code (flag declared per attach, set before the await, guarding the settle branch). Filed and resolved [coder-guidance-stale-step-scope](./tmp/reports/2026-10-15-admin-apply-status-coder-guidance-stale-step-scope.json) — the second finding against a planner artifact this plan has produced: `## Guidance for Coder` still scoped the round to "implement Steps 1–3 in order" after Step 4 was added, so round 3 had to reconstruct its task from the Issue Log and History. Guidance rewritten to name the outstanding lanes and to state that a future round's scope is the `## Immediate Actions` block; the superseded sentence is retired so the two cannot drift again. Counters: `issues_resolved_since_audit` 7, `steps_changed_since_audit` 3, `files_changed_since_audit` 0 — the Phase 5 re-audit trigger needs ≥3 resolved AND ≥3 steps or files, so no post-implementation audit. | — |
| 2026-10-17 | Spec revision (/update-plan, post-coder 2) | Coder round 2 completed Step 4 (three Warnings closed; Step 4 script 20/20) and filed two findings, both verified by the planner. [step3-gate-stale-attachsettled](./tmp/reports/2026-10-15-admin-apply-status-step3-gate-stale-attachsettled.json) — the planner's OWN Step 3 script still asserted the shared `attachSettled` latch that Step 4(b) removes, so it read 1 of 30 FAIL on a correct Step 4 tree; fixed by repointing that assertion at the per-attach generation guards (script now 30/30). [attach-settle-double-tick](./tmp/reports/2026-10-15-admin-apply-status-attach-settle-double-tick.json) — Step 4(e)'s supplied rationale ('the per-generation guard makes the extra ticks harmless') is false for two ticks of the SAME attach, since no new attach can arm while `attachPollHandle !== null`; closed by Step 4(a)'s per-attach `settled` flag, whose necessity (e) now states. Also repaired a textual contradiction the planner authored: Step 4(a)'s code block set `attachSettled = true;` while 4(b) mandates removing that latch — (a) and (b) are now one supplied code block that omits it, and the plan says (b) wins. Step 4's script extended with three `settled` checks (red against the current tree). Counters: `issues_resolved_since_audit` 5, `steps_changed_since_audit` 3, `files_changed_since_audit` 0 — the Phase 5 re-audit trigger needs ≥3 resolved AND ≥3 steps or files, so no post-implementation audit. | — |
| 2026-10-17 | Review (Phase 6) | `Issues found — non-blocking` — 0 Critical, 3 Warning, 7 Suggestion, at [2026-10-15-admin-apply-status-review-2026-10-17](./tmp/reports/2026-10-15-admin-apply-status-review-2026-10-17.json). All three Warnings were reproduced by execution and are the SAME hazard this plan exists to prevent (a press carrying a pre-swap baseline reverting a completed swap), so they are closed rather than accepted as caveats. Each of the six load-bearing claims was falsified or confirmed by running the shipped functions; the implementation matches the plan's supplied code verbatim, and no `innerHTML` or doc modification was introduced. | [hunches-and-unverified-areas](./tmp/reports/2026-10-15-admin-apply-status-review-2026-10-17.json) — 4 hunches (unbounded press POST, edit-loss with no dirty tracking, two plan-supplied copy nits) and 6 `areas_not_fully_verified` (no browser JS harness; real-world reachability of delayed status delivery; the suite was not re-run by the reviewer) carried forward for the next reviewer rather than fixed here. |
| 2026-10-17 | Spec revision (/update-plan, post-review) | New **Step 4** closes the three Warnings: gate the completion's unlock on a successful re-read (`refreshTiersFromServer` now returns a boolean), give each attach its own `attachGeneration` so a stale callback can only bail out, and re-render on the load path's no-swap branch. Adds the two cheap Correctness Suggestions (`typeof` guard on `silence_s`; retain the interval across the re-render await) and the readability comment. Tester step renumbered to 5 and extended with the four test-hardening Suggestions; planner step to 6. New script `./tmp/verification/2026-10-15-admin-apply-status-step4.py`, proven red (19 of 20 checks fail pre-fix). Counters: `issues_resolved_since_audit` 2, `steps_changed_since_audit` 3, `files_changed_since_audit` 0 — the Phase 5 re-audit trigger needs ≥3 resolved AND ≥3 steps or files, so no post-implementation audit. | — |
| 2026-10-17 | Implementation round (tester) — 1, succeeded | `overall_result: SUCCESS`; suite 425 passed / 0 failed / 0 skipped with the doc-anchor gate green, both target tests passing alone with a live proxy and inside the suite. The plan's declared red was reproduced by running it (2-block pin vs 3 blocks) and closed by the planned revision; the new 14 assertions were proven RED-CAPABLE against the pre-fix page read via `git show`. No issue filed — no non-skipped failure, no deviation from the plan, no pre-existing failure. Report at [2026-10-15-admin-apply-status-tester-2026-10-17](./tmp/reports/2026-10-15-admin-apply-status-tester-2026-10-17.json). | [orphaned-test-state-files](./tmp/reports/defer-issue-orphaned-test-state-files.json) — RUN 5 left one per-run state file (`claude-retry-proxy-test-state-12504.json`); referenced against the already-open deferral rather than re-filed, per the dedup rule. [step3-vs-step4-proof-scripts](./tmp/reports/2026-10-15-admin-apply-status-tester-2026-10-17.json) — the two verification artifacts overlap in intent but not mechanism (file-wide assertion vs red-on-the-pre-fix-literal); the reusable one is Step 4's proof script. |
| 2026-10-17 | Spec revision (/update-plan, post-tester) | Issue Log: both motivating issues `Fix Planned` → `Resolved` (tester report). Audit Accumulation: `issues_resolved_since_audit` 0 → 2, `steps_changed_since_audit` 0, `files_changed_since_audit` 0 — below the Phase 5 re-audit trigger (needs ≥3 resolved AND ≥3 steps or files changed), so no post-implementation audit runs. No Proposed Changes, Guidance, or metadata change. | — |
| 2026-10-17 | Implementation round (coder) — 1, succeeded | Exit 0 with a fresh report; Steps 1–3 completed, `build_result: pass`, `admin.html` +201/−12. Independently verified by the planner: the Step 3 script passes 30/30 on the coder's tree (it was proven red at 27/30 failures before the round). No plan error or gap found; the plan's declared red (`test_admin_html_poll_guard_after_await` pins 2 poll blocks, the page now has 3) is owned by Step 4. Report at [2026-10-15-admin-apply-status-coder-2026-10-17](./tmp/reports/2026-10-15-admin-apply-status-coder-2026-10-17.json). | [attach-watcher-settle-ownership](./tmp/reports/2026-10-15-admin-apply-status-mega-audit-2026-10-17.json) — the coder measured the interleaving unreachable (the settle branch holds both buttons disabled across `await refreshTiersFromServer()`, and the only other arm site runs once at load), so it was not filed as a defect; the audit itself already recorded real-world reachability as unverified. [four-bare-state-declarations](./tmp/reports/2026-10-15-admin-apply-status-coder-2026-10-17.json) — the four new module-level `let`s carry no explanatory comment while their siblings `swapPollHandle`/`swapSettled` do; the plan supplied them bare and required the code be used as written, so this is a provenance artifact, not a deviation, and is left for the Phase 6 reviewer. [dismissed-column-convention](./tmp/reports/2026-10-15-admin-apply-status-coder-2026-10-17.json) — the Dismissed cell lists adjudicated findings, not all 26; noted as a convention question, no plan change. |
| 2026-10-17 | Spec revision (/update-plan, post-coder) | Issue Log: both motivating issues `Open` → `Fix Planned` (implemented; `Resolved` awaits the tester report); the coder's pre-existing finding recorded as `Deferred` with its report at [defer-issue-admin-unrendered-page-apply-throws](./tmp/reports/defer-issue-admin-unrendered-page-apply-throws.json), traced to `74fcf5a` (the repo's initial commit, not a regression). Audit Accumulation: `issues_resolved_since_audit` 0 → 0 (no issue reached `Resolved` this session); `steps_changed_since_audit` 0 → 0; `files_changed_since_audit` 0 → 0. No Proposed Changes, Guidance, or metadata change — nothing to revise. | — |
| 2026-10-17 | Mega-audit (pre-implementation, iteration 1) | 9/9 lenses, 1 High + 5 Medium + 22 Low, confidence High, report at [2026-10-15-admin-apply-status-mega-audit-2026-10-17](./tmp/reports/2026-10-15-admin-apply-status-mega-audit-2026-10-17.json). All High + Medium fixed: the load-origin stale baseline (Medium, [admin-page-blind-while-swap-in-flight](./tmp/reports/2026-10-15-admin-apply-status-mega-audit-2026-10-17.json)) by making the completion re-render from both origins, which the user's select-inclusive lockout makes safe; the red-incapable gate for the 409 discriminator by asserting the branch inside each handler rather than a bare substring; the unbounded silent poll failure by adding the 5-failure signal; the doc's suite total (the High) by adding it, and the front-matter `test_admin.py` row, to Step 5's reconciliation scope. The CSS specificity Low was also fixed because the plan's own rationale was false for the Reload button. <3 High remain, so no re-audit. | [css-disabled-secondary-hover](./tmp/reports/2026-10-15-admin-apply-status-mega-audit-2026-10-17.json) (also fixed), [pre-fetch-guard-unreachable](./tmp/reports/2026-10-15-admin-apply-status-mega-audit-2026-10-17.json) (claim corrected, guard kept), [xss-posture-ungated](./tmp/reports/2026-10-15-admin-apply-status-mega-audit-2026-10-17.json), [test-impact-confirms-single-breakage](./tmp/reports/2026-10-15-admin-apply-status-mega-audit-2026-10-17.json), [no-rollback-section](./tmp/reports/2026-10-15-admin-apply-status-mega-audit-2026-10-17.json) |
| 2026-10-17 | Spec revision (user design direction) | Lockout extended to cover all nine tier selects, not just the buttons — which is what makes the completion re-render safe. Pending-line wording settled as "no need to refresh" (a mid-swap refresh is harmless; the poll-failure line is the one that must recommend reloading). Single-active-page enforcement (claim-on-load session, `409 admin_session_retired` on every write, CLI claims a session, generation in swap-status, retirement detected on operator action) agreed and **split out to a follow-up plan** rather than absorbed here. | — |
| 2026-10-17 | Plan-accuracy pass | Refreshed Step 5's stale doc line anchors (the three doc files moved in commits `e080d73`/`5ddfaa3`/`80a4ffe` after the plan was written) and recorded the pre-existing `test_admin.py` count disagreement (front-matter table 34 vs section header 36, against 36 registered tests) as a reconciliation target for Step 5. No design change. | — |
| 2026-10-15 | Initial plan | Diagnosed the invisible pending status (the empty-type `showStatus` call hitting the unstyled `.status` class) and the refresh/409 blindness; scope 1+2+button-lockout confirmed interactively by the user. | — |

## Plan Metadata

Fenced json block — the machine contract read by `parsePlanContext`. `steps` = one title per step; `coder_files`/`tester_files`/`doc_files` mirror the respective `**Files to modify:**` markers; `verification_scripts` entries shaped `./tmp/verification/<name>.py`.

```json
{
  "plan_id": "2026-10-15-admin-apply-status",
  "steps": [
    "Step 1: admin.html — pending-status CSS and control ids",
    "Step 2: admin.html — sticky status helper, lockout helper, and the press-path changes",
    "Step 3: admin.html — the attach watcher and the load-time swap check",
    "Step 4: admin.html — close the Phase 6 reviewer's three Warnings",
    "Step 4.5: admin.html — close the post-implementation audit's two behavioural findings",
    "Step 4.6: admin.html — gate the load path's re-read and re-check the press guards after it",
    "Step 5: Tester — structural test updates, reviewer-driven hardening, and the full suite",
    "Step 6: Planner — documentation sync"
  ],
  "coder_files": [
    "src/claude_retry_proxy/admin.html"
  ],
  "tester_files": [
    "tests/test_admin.py"
  ],
  "doc_files": [
    "./README.md",
    "./CLAUDE.md",
    "doc/operations.html",
    "doc/test-catalog.html"
  ],
  "verification_scripts": [
    "./tmp/verification/2026-10-15-admin-apply-status-step3.py",
    "./tmp/verification/2026-10-15-admin-apply-status-step4.py"
  ],
  "repo_mode": "Public",
  "document_overrides": []
}
```

## Audit Accumulation

*Counters reset when mega-audit runs. Used by Phase 5 entry trigger.*

| Counter | Value | Last Updated |
|---------|-------|--------------|
| issues_resolved_since_audit | 4 | 2026-10-18 |
| steps_changed_since_audit | 2 | 2026-10-18 |
| files_changed_since_audit | 0 | 2026-10-18 |

*Advanced 2026-10-18 by this revision, not left at the post-audit reset. `issues_resolved_since_audit` = 4: `review-final-load-path-re-read-unguarded` and `review-final-load-path-reread-after-await` (coder round 6's Step 4.6), `review-final-stale-branch-quote-brittle` (tester round 4's quote-agnostic discriminator), and `step4-gate-stale-load-reread` (the planner's repoint of the Step 4 script's Step 4(c) check). `steps_changed_since_audit` = 2 (Step 4.6 added; Step 5's item re-worded to carry the (q)/(r) probes and the F4 fix). `files_changed_since_audit` = 0 — the coder's "Files to modify" is still the single `admin.html`, unchanged. **Trigger check: 4 ≥ 3 resolved, but 2 steps < 3 and 0 files < 3, so the Phase 5 re-audit trigger is NOT met and no post-implementation mega-audit runs.** The two further findings coder round 6 filed — `plan-issue-reports-never-merged-to-resolved` and `deferral-and-plan-scoped-report-coexist` — reached `Deferred`, a completed disposition, and are not counted here. The counters are recorded at their true values rather than re-zeroed, because the paragraph below documents how a stale `0/0/0` here made this gate silently not fire once already.*

*Reset to 0 on 2026-10-17 when the pre-implementation mega-audit ran (iteration 1 of a cap of 3). Both trigger conditions were met by 2026-10-17 — 13 issues resolved (≥3) against 3 steps changed (4, 5, 6) and 2 files changed — so the **post-implementation** mega-audit ran before finalization, as did the Phase 6 review and one post-review `/update-plan`. **The table read 0/0/0 from that point while the History rows went on recording resolved issues and changed steps:** the counters were never advanced as the plan was revised, and each `/update-plan` invocation read the stale table and concluded the trigger was unmet. That is a gate silently not firing — the exact shape the plan's own Step 5 hardening exists to prevent.*

## Documentation

**Landed 2026-10-17 (planner lane), re-opened and extended 2026-10-18.** Both doc gates pass on the final tree, re-run after the second pass: `~/.claude/scripts/doc_structure_check.py` (9 files, no violations) and `scripts/check_doc_anchors.py` (204 anchors resolved, no secret shapes). The full suite is green afterwards (425 passed / 0 failed / 0 skipped).

**Second pass, 2026-10-18** — driven by tester round 4's measured `documentation_discrepancies`, not by inspection:

- `doc/test-catalog.html` — the `test_admin_html_pending_status_styled` entry moved **20 → 22 evidence lines** and **(a)–(p) → (a)–(r)**, with a new clause for the load path's own gate (its captured re-read, its five-clause failure branch, and the pre-await/post-await press-guard pair, read through the same `_js_function_body`/`_js_braced_block` extractors as the other two sites); the pending call-site count moved **9 → 10** *and* its parenthetical enumeration gained the load path's failed-re-read term, or the count and its own enumeration would have contradicted each other — the self-contradiction that page's front-matter warn box exists to name; and the closing red-capability sentence now credits **both** mutation-based proof scripts (round 3's 8-mutant script and round 4's 11-mutant one) instead of round 3's alone, which had become true-but-incomplete. Date stamp moved to 2026-10-18.
- `doc/operations.html` — the #admin "locked until a **successful** re-read" sentence, which named only the reload-stale and attach sites, now covers the third site (a page that loads with no swap running) and states plainly why it matters: `/admin/api/switch` carries **no** staleness guard, only the reload path has one. Date stamp moved to 2026-10-18.
- `./README.md` — the same contract sentence gained the load path, in the same terms.

- `./README.md` — §Admin page: live status line, locks on both buttons and all nine tier selects while any swap is in flight, re-attach after refresh, the "no need to refresh" guidance, the poll-failure message, the reload-stale "locked until a verified re-read" contract, the server-side single-flight fact behind the page's lockout, and the proxy-restart requirement for the served page.
- `doc/operations.html` — #admin: the single-flight 409 paragraph (now naming the page's attach behaviour and the `_drain_for_swap()` enforcement behind the lockout), a new swap-time-behaviour paragraph (the 1 Hz line, the select-inclusive lock, "no need to refresh", the completion re-render and why it precedes the unlock, the 5-failure signal, the failed-re-read lock), and the proxy-restart note.
- `doc/test-catalog.html` — revised `test_admin_html_poll_guard_after_await` entry (now pinning all three poll blocks by enclosing-function identity), new `test_admin_html_pending_status_styled` entry (20 evidence lines, (a)–(p)), the `test_admin.py` per-module count moved **34 → 37** in both places it appears, the "Covers" cell extended with the attach watcher, the select-inclusive lockout and the completion re-render, and the front-matter suite total moved **424 → 425 across 19** with 424 appended to the drift chain and the drift count moved **"fifteen times" → "sixteen times"**. Both "Last updated" stamps bumped on this page and on `doc/operations.html`.
- `./CLAUDE.md` — **two edits landed** (reversing an earlier "no change needed" claim recorded at planning time): `admin-unrendered-page-apply-throws` added to the `Unresolved Deferred Issues` JSON block, and the Future Work prose moved "Nine deferred issues remain" → ten with a paragraph describing the new deferral. **Amended 2026-10-18:** the block was grown to **12** entries against **12** `defer-issue-*.json` files on disk, the prose moved ten → twelve, and "**Three** of the ten are cross-repo" moved to "**Five** of the twelve" — each verified by counting the JSON block's entries against the files on disk. **Then removed entirely, on the user's instruction of 2026-10-18: this repo no longer maintains a deferred-issues list in `CLAUDE.md`.** The `## Unresolved Deferred Issues` section (heading + JSON block, 4,982 chars) and the three deferred-issue paragraphs that opened `## Future Work — TODO` (3,621 chars) are gone; that section's refactor-backlog prose is untouched, so it still begins at the source/test file split. This is a **deletion, not a drift**, and it removes four edits rather than superseding them — the plan is therefore the last record that the index existed. Justified rather than incidental: `planner.md`'s "Deferred-issue awareness" step already defines the corpus as `./tmp/reports/defer-issue-*.json` with **presence meaning open**, and states that reports are machine-local, so the `CLAUDE.md` block was a second, hand-maintained copy of a list the command surface had stopped writing. Removing it eliminates the class of drift this plan spent two rounds correcting.

## Final Results

**Completion date:** 2026-10-18
**Status:** COMPLETED

### What shipped

The admin page at `/admin/` now reports what a press is doing instead of looking inert, and cannot be used to write a stale tier mapping back over a swap that has already completed.

- A **sticky pending line** (`display: block`; the empty-type `showStatus('')` call that rendered nothing is gone) reports the drain live at 1 Hz from `/admin/api/swap-status`, carrying "no need to refresh" while a swap is in play and a distinct "reloading is now safe" line after 5 consecutive poll failures. Ten `showStatus('pending'…)` call sites.
- **Lockout covers both buttons and all nine tier selects** for as long as any swap is in play — this page's own press, one detected on load, or one the page was refused into — which is what makes the completion re-render safe. The single-key rule is restored on unlock.
- **Every re-render that precedes an unlock gates on a successful re-read.** All three call sites (attach completion, `409 config_reload_stale`, and the load path's one-shot check) capture `refreshTiersFromServer()`'s boolean; a failed re-read leaves the controls **locked** and says so, because `/admin/api/switch` carries no staleness guard of its own. This is the plan's core hazard, and it was closed three times — once per call site, each time after a reviewer or auditor showed the other two had it and the third did not.
- **In-flight-swap awareness**: a `409 config_swap_in_progress` no longer dead-ends; the page attaches to the running swap, keeps reporting it, and unpolls itself with a per-attach generation so a stale callback can only bail out.

### Files changed

| File | Change |
|---|---|
| `src/claude_retry_proxy/admin.html` | +286 — the whole page-side change (Steps 1–4.6) |
| `tests/test_admin.py` | +768 — the 3-block `test_admin_html_poll_guard_after_await` revision and `test_admin_html_pending_status_styled` (22 evidence lines, (a)–(r)) |
| `README.md`, `doc/operations.html`, `doc/test-catalog.html` | the Step 6 sync and its 2026-10-18 second pass |
| `CLAUDE.md` | the deferral index (12 entries) and the Future Work prose |

### Test results

- **Full suite: 425 passed / 0 failed / 0 skipped**, re-run by the planner on the final tree. The doc-anchor gate runs inside it.
- **Doc gates:** `~/.claude/scripts/doc_structure_check.py` — 9 files, no violations. `scripts/check_doc_anchors.py` — 204 anchors resolved, 8 pages scanned, no secret shapes.
- **Plan verification scripts:** `…-step3.py` 30/30; `…-step4.py` 42/42.
- **Red-capability, measured not asserted:** the Step 4 script fails **exactly 6 of 42** against the pre-fix literal at `tmp/pre46/` — the six Step 4.6 checks, and only those. The tester's round-4 proof script runs the same predicates over 13 cases (live page, a pre-fix shape derived by reversal and required to be byte-identical to the planner's own literal, and 11 mutants): every probe green on the live page, red on the pre-fix shape, red on the mutant that breaks exactly what it asserts.

### Issues resolved

**19 rows `Resolved`** — 2 motivating issues (`admin-pending-status-invisible`, `admin-page-blind-while-swap-in-flight`); 6 from the two Phase 6 review passes (`review-load-path-no-rerender`, `review-attachsettled-cross-talk`, `review-unlock-on-failed-rerender`, `review-final-load-path-re-read-unguarded`, `review-final-load-path-reread-after-await`, `review-final-stale-branch-quote-brittle`); 3 found by coder rounds (`attach-settle-double-tick`, `reload-stale-re-read-result-ignored`, `attach-settled-inner-guard-unreachable`); 2 from the post-implementation mega-audit (`audit-reload-stale-row-not-refreshed`, `audit-attach-settled-repaint`); 2 planner-artifact findings from coder rounds (`coder-guidance-stale-step-scope`, `immediate-actions-contradicts-its-bullets`); and 4 stale-gate defects in this plan's own verification scripts (`step3-gate-stale-attachsettled`, `step3-gate-stale-config-reload-stale`, `step4-gate-stale-reload-stale-branch`, `step4-gate-stale-load-reread`).

Two honest observations, recorded because they cost the plan real rounds. **Eight of the nineteen findings landed against planner artifacts or planner-supplied code rather than the implementation** — six against the plan's own text and verification scripts, and two (`reload-stale-re-read-result-ignored`, `attach-settled-inner-guard-unreachable`) against a code block the plan supplied verbatim for Step 4.5. The implementation itself was correct from coder round 3 onward, and every later red was a gate, a guidance line, or a supplied snippet. And **four of the nineteen were the same defect** — a verification script pinning a shape that a later step supersedes, which is why each revision now re-reads its predecessor's checks before adding its own.

### Deferred issues

Neither is a failure of this plan; both are recorded rather than dropped. **There is no longer a `CLAUDE.md` index of these** — on the user's instruction of 2026-10-18 the block was removed from that file, leaving `./tmp/reports/defer-issue-*.json` (presence means open) as the only record, which is what `planner.md`'s deferred-issue awareness step already scans.

#### `admin-unrendered-page-apply-throws` (same repo, filed by this plan)

A failed initial config load leaves the admin page with no tier rows while both buttons stay pressable, so pressing Apply or Reload throws an uncaught `TypeError` and gives the operator no feedback. Pre-existing (traced to the repo's initial commit `74fcf5a`, not a regression), adjacent to this plan's subject but not inside it — the plan locks the controls while a swap is in play, not while the page has nothing to apply. Report: `./tmp/reports/defer-issue-admin-unrendered-page-apply-throws.json`.

#### `plan-issue-reports-never-merged-to-resolved` (targets `claude-config`)

`report-schemas.md` documents an `Open → Fix Planned → Resolved` merge into plan-scoped issue report files "managed by `/update-plan`", but the command edits only the plan's `## Issue Log` table — so the two documents disagree and the command's behaviour wins. Measured corpus-wide: 53 `Open`, 8 `Fix Planned`, 14 `Resolved`, 2 `Won't fix` across 77 plan-scoped issue reports. This plan's twelve files all read `Open`, nine of them beside log rows that mark their topic `Resolved`. Filed by coder round 6. Report: `./tmp/reports/defer-issue-plan-issue-reports-never-merged-to-resolved.json`.

#### `deferral-and-plan-scoped-report-coexist` (targets `claude-config`)

`/defer-issue`'s dedup checks only the `defer-issue-<slug>.json` filename, so deferring a topic that already has a plan-scoped finding leaves two `Open` records for one issue and no sanctioned step retires the orphan. `admin-unrendered-page-apply-throws` is the corpus's only such pair. Filed by coder round 6. Report: `./tmp/reports/defer-issue-deferral-and-plan-scoped-report-coexist.json`.

### Known limits

- **No runtime JS evidence in the committed suite.** The admin-HTML tests pin source ordering on the HTML the proxy actually serves, not executed behaviour. Both docstrings say so. The closest thing to runtime evidence this plan produced is the Phase 6 reviewer's stub DOM/fetch/timer harness (`./tmp/verification/2026-10-17-review-final-harness.js`, 40 checks), which is a reviewer artifact, not a committed test.
- **`review-final-F3` was accepted, not fixed**: terminal "reload this page" lines are painted with the in-progress `pending` class. The reviewer refuted the first pass's entanglement rationale (stickiness is now a separate argument) and rated it a Suggestion; the line's *text* is unambiguous and its stickiness is required, so the class name is cosmetic.
- **The plan's own proof scripts date themselves against `HEAD`.** `tmp/verification/2026-10-15-admin-apply-status-step5-proof.py` uses `git show HEAD:…admin.html` as its PRE case, which is correct only while nothing is committed. After `/update-and-commit` lands, HEAD becomes the post-plan page and that script's "new" probes read green against what is then the fixed tree. The planner's Step 3/Step 4 scripts are unaffected — their pre-fix baseline is the literal copy under `tmp/pre46/`, not HEAD.

### Cross-references to prior plans

None. No issue resolved by this plan matches a deferral filed by a prior plan: every `defer-issue-*.json` on disk at close was checked against this plan's `## Issue Log`, and the two entries this plan added are its own new findings, not pickups.