# Plan: Surface the /admin/api/config 500 — committed coverage + admin page guard

**Plan ID:** 2026-11-01-admin-config-500-surface
**Created:** 2026-11-01

<!-- ## Immediate Actions: absent from initial plans. Populated by /update-plan for revised plans, replaced (not accumulated) on each revision. -->

## Immediate Actions

**Coder:**
- Execute Step 6: add `removeStatusKey('attach-wait');` as the first statement of the terminal failed-re-read else-branch in the attach watcher (shipped admin.html:662-669). Run `python tmp/verification/2026-11-01-admin-config-500-surface-step4.py` — must print 22/22 PASS, GATE GREEN.

**Tester:**
- Execute Step 7 after the coder round: the attach-exit pin (source-shape row) + the Node behavioral probe (409 hand-off + failed re-read ends with the terminal line alone); full suite; session report.

**Planner:**
- After Step 7: sync the `test_admin_html_status_stack_keyed_removal` catalog entry (the attach terminal branch is now also an exit) and confirm the operations.html stack sentence holds unqualified; fresh Phase 6 review (round 3, delta-scoped); Final Results.

ssue Log

Rows ordered newest-first (latest issues at top). New issues are prepended; resolved issues stay in place with updated status.

| Issue | Status | Found | Resolved | Resolved By |
|-------|--------|-------|----------|-------------|
| [review2-attach-wait-terminal-exit-missing](./tmp/reports/2026-11-01-admin-config-500-surface-review-2026-11-01-2.json) | Resolved | 2026-11-01 | 2026-11-01 | [tester](./tmp/reports/2026-11-01-admin-config-500-surface-tester-2026-11-01-3.json) — Step 6 call pinned as the terminal branch's first statement; the frozen-line scenario measured fixed (terminal line alone) with the removal-deleted mutant reproducing the defect |
| [step4-showstatus-undefined-key-collision](./tmp/reports/2026-11-01-admin-config-500-surface-step4-showstatus-undefined-key-collision.json) | Resolved | 2026-11-01 | 2026-11-01 | [planner](./tmp/reports/2026-11-01-admin-config-500-surface-step4-showstatus-undefined-key-collision.json) — Step 4 block normalizes omitted `key` to `null`, exact call sites and CSS literals supplied, gate check 12 pins the normalization line (re-proven RED 0/12); the coder's own Node probe measured the corrected predicate at stack depth 2 |
| [review-load-line-overwritten](./tmp/reports/2026-11-01-admin-config-500-surface-review-2026-11-01.json) | Resolved | 2026-11-01 | 2026-11-01 | [tester](./tmp/reports/2026-11-01-admin-config-500-surface-tester-2026-11-01-2.json) — measured fixed on the shipped page: the guard's diagnostic stays rendered beneath the newer re-read line (status-stack model, Step 4) |
| [step1-gate-rendertiers-comment-collision](./tmp/reports/2026-11-01-admin-config-500-surface-step1-gate-rendertiers-comment-collision.json) | Resolved | 2026-11-01 | 2026-11-01 | [planner](./tmp/reports/2026-11-01-admin-config-500-surface-step1-gate-rendertiers-comment-collision.json) — gate hardened to comment-stripped matching; re-run 8/8 PASS GATE GREEN, exit 0 |
| [admin-page-loadconfig-ignores-response-ok](./tmp/reports/defer-issue-admin-page-loadconfig-ignores-response-ok.json) | Resolved | 2026-10-27 | 2026-11-01 | [tester](./tmp/reports/2026-11-01-admin-config-500-surface-tester-2026-11-01.json) — Step 1 edit verified byte-identical to the plan block; `test_admin_html_load_config_status_guard` pins the guard on the served page |
| [config-serialize-500-no-committed-coverage](./tmp/reports/defer-issue-config-serialize-500-no-committed-coverage.json) | Resolved | 2026-10-26 | 2026-11-01 | [tester](./tmp/reports/2026-11-01-admin-config-500-surface-tester-2026-11-01.json) — `test_admin_config_serialize_failure_500` committed and passing; 489/489 suite green |

Both rows are adoptions of standalone deferrals filed by plan `2026-10-25-guard-totality-and-blank-admin` (Phase 6 reviews). This plan is the adopting plan: when a row reaches `Resolved`, `/update-and-commit` Step 9.6 retires the linked report.

## Guidance for Coder

**Files to modify:**

| File | Change |
|------|--------|
| `src/claude_retry_proxy/admin.html` | `loadConfig()`: guard the `/admin/api/config` response status before the document reaches the global `config` / `renderTiers()` |

**Step-by-step with verification:** each step above has coder checks tagged `(auto)` or `(scripted)`. The coder self-verifies `(auto)` checks and runs the provided script for `(scripted)` checks. Tester owns the behavioral checks.

**Step 1 — the exact edit** (current lines 116–132; apply the guard, keep everything else byte-identical):

```javascript
        async function loadConfig() {
            try {
                const [configResp, providersResp] = await Promise.all([
                    fetch('/admin/api/config'),
                    fetch('/admin/api/providers')
                ]);
                const configResult = await configResp.json();
                if (!configResp.ok) {
                    // A non-OK body is still valid JSON, so without this guard
                    // the tiers-less document explodes later in renderTiers()
                    // as a TypeError and the server's diagnostic never reaches
                    // the operator. Same contract as save/reload: surface
                    // errorText(result).
                    showStatus('error', 'Failed to load config: ' + errorText(configResult));
                    checkInFlightSwapOnLoad();
                    return;
                }
                config = configResult;
                const providersData = await providersResp.json();
                providers = providersData.providers || [];
                // Optional endpoint — a failing fetch must not brick the page.
                await loadProviderModes();
                renderTiers();
            } catch (e) {
                showStatus('error', 'Failed to load config: ' + e.message);
            }
            checkInFlightSwapOnLoad();
        }
```

Constraints (all deliberate, do not deviate):

- **Do not** change the `providersResp` handling — the providers fetch is not in scope; its `|| []` guard already exists.
- **Do not** retry on 500 — the document cannot be served until the config changes; a retry would spin.
- **Do not** drop `checkInFlightSwapOnLoad()` from the non-OK path — it is reachable today even when the `catch` fires, and this edit must preserve that reachability exactly once per `loadConfig()` call (non-OK path: called inside the guard, then `return`; success and catch paths: fall through to the tail call).
- **Do not** restructure the other loaders, reorder `Promise.all`, or alter any other function in the file.
- The file's idiom is single-quoted JS strings — keep `showStatus('error'` as written.

**Do not** write tests or documentation files.

**Step 4 — the status-stack model** (user-directed 2026-11-01, superseding the skip-the-probe option; current `showStatus` at admin.html:459-467 is one element, last-write-wins, single 5 s `statusTimer`). Replace `showStatus` and add two helpers — the exact block:

```javascript
        // Status stack: failures stack newest-on-top instead of replacing; any
        // success clears the stack and shows itself; a keyed entry (the ticking
        // wait lines) is removed and re-inserted at the top on every update.
        // Re-painting a message identical to a stacked unkeyed entry updates it
        // in place rather than duplicating.
        function showStatus(type, message, sticky, key) {
            if (key === undefined) { key = null; }
            if (type === 'success') {
                statusEntries.forEach(function (e) {
                    if (e.timer !== null) { clearTimeout(e.timer); }
                });
                statusEntries = [];
            } else {
                const reuseAt = statusEntries.findIndex(function (e) {
                    return (key !== null && e.key === key) ||
                           (key === null && e.key === null && e.text === message);
                });
                if (reuseAt !== -1) {
                    if (statusEntries[reuseAt].timer !== null) {
                        clearTimeout(statusEntries[reuseAt].timer);
                    }
                    statusEntries.splice(reuseAt, 1);
                }
            }
            const entry = { type: type, text: message, key: key, sticky: sticky, timer: null };
            statusEntries.unshift(entry);
            if (!sticky) {
                entry.timer = setTimeout(function () { removeStatusEntry(entry); }, 5000);
            }
            renderStatus();
        }

        function removeStatusEntry(entry) {
            const at = statusEntries.indexOf(entry);
            if (at !== -1) {
                statusEntries.splice(at, 1);
                renderStatus();
            }
        }

        // Keyed removal: the exit for a keyed entry whose owner reached a
        // terminal state without a repaint or success (a failed Apply must not
        // leave the frozen 'applying — …' line as the page's only status —
        // mega-audit 2026-11-01, defect-tracer High).
        function removeStatusKey(key) {
            const at = statusEntries.findIndex(function (e) { return e.key === key; });
            if (at !== -1) {
                if (statusEntries[at].timer !== null) { clearTimeout(statusEntries[at].timer); }
                statusEntries.splice(at, 1);
                renderStatus();
            }
        }

        function renderStatus() {
            const el = document.getElementById('status');
            el.className = 'status' + (statusEntries.length ? ' ' + statusEntries[0].type : '');
            el.innerHTML = '';
            statusEntries.forEach(function (e) {
                const line = document.createElement('div');
                line.className = 'status-line ' + e.type;
                line.textContent = e.text;
                el.appendChild(line);
            });
        }
```

Plus, in the same file:

- Declare `let statusEntries = [];` beside the old `statusTimer` declaration, and **remove `statusTimer` entirely** — every reference (the old `showStatus` body's is the only one; grep to confirm) goes away, replaced by per-entry timers.
- Call `removeStatusKey('swap-wait')` **unconditionally in `saveConfig`'s and `reloadConfig`'s `finally` blocks** (before the unlock logic). Every entry needs an exit: without this, a failed Apply leaves the sticky keyed 'applying — …' line with no repaint, no success, and no timer — it resurfaces as the page's only, permanently false status once the terminal error fades (the 409 hand-off is fine: the finally removal runs after `attachToInFlightSwap` has painted, and by key it cannot touch the attach family's lines). On success the stack is already empty, so the call is a no-op.
- Make the load-failure guard line sticky — the failure persists until a success clears it or the page reloads; a 5 s fade would lose it again under the sticky re-read line:
  `showStatus('error', 'Failed to load config: ' + errorText(configResult), true);`
- Amend `loadConfig` (three deliberate changes, all inside the existing structure — the step-1 gate, the shape test, and the reachability gate stay green unedited):
  1. Parse the providers response and run `loadProviderModes()` **before** the `configResp.ok` branch, so a failed config load no longer discards the provider list the page already paid for (the two fetches resolve together in `Promise.all`).
  2. Tolerant config parse — a non-JSON body must not throw into the generic catch and masquerade as a network error: `try { configResult = await configResp.json(); } catch (err) { configResult = null; }` (the guard then renders `errorText(null)` → `'Unknown error'`).
  3. The catch branch's paint becomes sticky too — it is the same "this page cannot be configured" terminal state: `showStatus('error', 'Failed to load config: ' + e.message, true);`
- Key the ticking wait paints with a 4th argument — **exact call sites** (numbers from the pre-edit file; locate by content, the attach sites shift once the new `showStatus` block lands):
  - `'swap-wait'`: the four drain/press wait paints in `saveConfig`/`reloadConfig` (pre-edit admin.html:299, 319, 376, 396 — every `showStatus('pending', swapWaitText(...), true)` in those two handlers).
  - `'attach-wait'`: the attach watcher's initial paint and its 1 Hz tick, plus `noteAttachPollFailure`'s line (pre-edit admin.html:544, 595, 612).
  - **Explicitly unkeyed:** the terminal failed-re-read line (pre-edit admin.html:590) — it is a terminal state, not a ticking progress line, and Step 5's keyed-tick test needs this boundary pinned.
  - No other call site changes (all stay 2–3 arguments; the `key === undefined` normalization at the top of `showStatus` is what makes unkeyed calls stack rather than replace — without it `undefined !== null` routes every unkeyed paint down the keyed arm and the model silently degrades to last-write-wins, issue `step4-showstatus-undefined-key-collision`).
- CSS — exact rules to add beside the existing `.status.*` block (same palette values as admin.html:31-33):

```css
        .status-line { padding: 0.15rem 0; }
        .status-line.success { background: #1b5e20; }
        .status-line.error { background: #b71c1c; }
        .status-line.pending { background: #0f3460; }
```

Constraints (all deliberate, do not deviate):

- Rendering is `createElement` + `textContent` only — no interpolated `innerHTML` (the one constant `el.innerHTML = ''` clear is fine).
- `loadConfig` changes are **exactly** the four named above (sticky guard flag, providers-before-guard, tolerant parse, sticky catch) — the guard's shape (`ok`-check before the `config =` assignment and `renderTiers()`, `errorText`, one `checkInFlightSwapOnLoad()` inside the non-OK branch, early return) is untouched, and the step-1 gate, the round-1 shape test, and the reachability gate must stay green unedited.
- **Do not** touch `swapWaitText`, or the swap/attach handlers' logic beyond the two `finally` blocks' `removeStatusKey('swap-wait')` calls **and** the Step 6 `removeStatusKey('attach-wait')` call in the terminal failed-re-read branch, or any test/doc file.

## Guidance for Tester

**Tests to create:**

- **Permanent:** `test_admin_config_serialize_failure_500` (name at tester's discretion, in `tests/test_admin.py`) — commits the GET `/admin/api/config` serialize-failure branch. Shape:
  - Drive `do_GET` in-process via the `object.__new__(srv.ProxyHandler)` pattern the module already uses (`_drive_post_in_process` at tests/test_admin.py:2918 is the POST template; this is its GET analogue — `handler.path = "/admin/api/config"`, `client_address = ("127.0.0.1", <port>)`, `wfile = io.BytesIO()`; add whatever header state `do_GET` reads).
  - Fixture: save `srv._current_config`, set it to a document carrying a value `json.dumps` cannot serialize — a `set` inside a per-tier dict (the module precedent: `test_admin_reload_serialize_failure_500`, tests/test_admin.py:2942). **No deep-nesting fixture** — it measures the interpreter's stack and goes flaky across machines; `TypeError` lands in the same `except Exception` a `RecursionError` reaches, which is the property under test.
  - Assert: the response **arrives** (`captured` non-empty — no-response-at-all is the pre-guard failure mode), status is `500`, and the body is exactly `{"error": "the configuration could not be serialized"}`.
  - Survival assertion: restore `srv._current_config` in a `finally`, then drive a second in-process GET with the restored (valid) config and assert `200` — the handler answers normally after the guard fires.
- **Permanent:** a source-shape test pinning the Step 1 page guard on the HTML the proxy serves or the shipped file, following the module's established admin.html assertion pattern (`test_admin_html_key_column`, tests/test_admin.py:1726). Assert at minimum: `loadConfig` contains the `configResp.ok` check; it precedes both the `config =` assignment and `renderTiers()`; the non-OK path carries `errorText(`.
- **Permanent (Step 5):** coverage for the status-stack model, in the same served-page style: (a) a failure followed by another failure leaves BOTH lines rendered, newest first (the warning scenario: the guard's `errorText` line stays visible beneath the re-read line); (b) a success call clears the stack and shows only the success line; (c) a keyed tick re-paint moves that entry to the top and does not grow the stack; (d) re-painting an identical unkeyed message does not duplicate the entry; (e) the sticky guard line carries `true`; (f) **the keyed-entry dead-end regression** (mega-audit High, measured): a press-pending 'swap-wait' paint followed by a terminal failure and the 5 s expiry leaves the status area EMPTY — never the frozen 'applying — …' line. Where the assertion would depend on async repaint order, measure by executing the page script (Node-stub DOM/fetch, the method the Phase 6 reviewer used) — but **only in throwaway probes under `./tmp/verification/`**: permanent tests are pure-Python source-shape pins on the served page, per the suite's conventions. Register each new test in `tests/test_admin.py`'s `ALL_TESTS` with an `admin-html-status-stack*` name (module precedent, tests/test_admin.py:4699); the sticky-guard row may join the existing `_load_config_guard_checks` helper as one more assertion rather than a separate test (tester's call). Note: the two Step 2 tests are already delivered and passing — this round executes only the Step 5 scope; the recovery GET in `test_admin_config_serialize_failure_500` should set `_current_config` to a literal serializable document before its second in-process GET (not restore `None`) — a small in-place strengthening of that test is in scope.

**Tests to investigate for retirement:**

- No test obsolescence identified. (`test_admin_html_apply_requires_rendered_row`'s premise — the nine tier selects don't exist when the config fetch fails — remains true after the fix: the non-OK path returns before `renderTiers()`, so the selects still never render.)

**Retirement procedure:** For each candidate, verify the test exercises code being removed/changed. If obsolete: delete and note in session report. If still valid: document why in session report.

## Summary

**Problem.** The GET `/admin/api/config` handler answers `500 {"error": "the configuration could not be serialized"}` when the in-memory config decodes but cannot re-encode (real state: the encoder's recursion ceiling sits below the decoder's — ~15,505 vs ~16,915 on the shipping interpreter — and a hand-edited config inside that band starts fine, serves, and 500s this endpoint). Two gaps surround that branch, both filed by the parent plan's Phase 6 reviews and deferred 2026-10-26/27:

1. **No committed test** — the branch is covered only by transient `./tmp/verification/` scripts the post-commit sweep retires; the identical *reload*-handler branch got a committed test (`test_admin_reload_serialize_failure_500`), this one didn't.
2. **The admin page mishandles the response** — `loadConfig()` parses without testing `resp.ok`; the error body is valid JSON, so `config` becomes `{error: ...}`, `renderTiers()` throws `TypeError` on `config.tiers[tier]`, and the operator sees the generic catch message instead of the server's diagnostic.

**Approach.** One small plan closing both: the coder adds the status guard to `loadConfig()` (mirroring the page's own save/reload idiom — parse, branch on `ok`, surface `errorText(result)`); the tester commits the 500-branch test plus a source-shape test pinning the page guard; docs sync afterward. Fixing either half alone leaves the story half-done: the test without the page fix still blinds the operator; the page fix without the test rots silently if the 500's shape drifts.

**Out of scope:** retrying on 500 (pointless — the document cannot be served until the config changes); the other five switch-rejection messages — whose bodies interpolate the raw rejected client values by design (naming the offender), rendered safe by textContent-only status rendering, the loopback-only bind, and the exact-match Origin allowlist (corrected per mega-audit 2026-11-01; the earlier "validated strings" claim here was wrong); the SSE frame-encode failure path (different handler, already fenced and cataloged); serving a serializable config subset instead of 500 (wider design question).

## Repo Mode

Public

*Detected at plan creation. Determines: plan archival path, commit-message content, staged files.*

## Document Overrides

| Document | Rule Overridden | Reason |
|----------|----------------|--------|

## Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| `loadConfig()` control-flow edit disturbs the swap-lock attach path (`checkInFlightSwapOnLoad` unreachable, or double-called) | The page's in-flight-swap lock UI misbehaves after a failed config load | The Step 1 gate asserts the guard path carries exactly one `checkInFlightSwapOnLoad(` call and returns; `test_admin_html_apply_requires_rendered_row` and the swap tests must stay green in the tester round |

## Proposed Changes

Each step includes verification checks tagged with confidence. `(auto)` = mechanical, coder self-verifies. `(scripted)` = deterministic multi-step, coder runs provided script. Every step has at least one verification check executable by its owner.

1. **Step 1: Guard `loadConfig` against a non-OK `/admin/api/config` response** — apply the exact edit in Guidance for Coder to `src/claude_retry_proxy/admin.html`.
   <!-- UPDATED 2026-11-01 (×2): (1) /update-plan — calibration sentence rewritten, the gate was hardened between the RED and GREEN runs (issue step1-gate-rendertiers-comment-collision), so "unedited between the two runs" was false as written. (2) Phase 6 review — check 8 hardened from membership to count == 1 (review Design finding: the Risks row credits the gate with exactly one swap-lock call); re-run 8/8 PASS GATE GREEN exit 0. -->
   → coder verify (scripted): run `python tmp/verification/2026-11-01-admin-config-500-surface-step1.py` from the repo root; it must print 8/8 PASS, `GATE GREEN`. Calibration: RED on the pre-change tree, measured 2026-11-01 — 7/8 checks FAIL (`configResp.ok` absent). The gate was then hardened twice — ordering checks on a comment-stripped slice (its raw-text `renderTiers()` find matched the mandated guard comment above the return), then check 8 to `count == 1` — and GREEN was measured with the current script against the applied edit, 8/8 PASS, exit 0. RED property is unaffected by either hardening: on the pre-change tree `configResp.ok` is absent and check 2 fails regardless.
   → tester verify: the source-shape test from Guidance for Tester passes against the served/shipped page.

2. **Step 2: Commit the `/admin/api/config` 500 coverage and pin the page guard** — tester adds the two permanent tests to `tests/test_admin.py` per Guidance for Tester and runs the suite.
   → tester verify: both new tests pass; the full suite reports no new failures; session report records the run.

3. **Step 3: Sync documentation for the new tests and page behavior** — planner-owned; first pass executed after the round-1 tester round; a second pass follows Step 5 (restore the strong `operations.html` sentence — the stack model makes it true — and add catalog entries for the Step 5 tests).
   <!-- UPDATED 2026-11-01: executed; sentence narrowed per Phase 6 review finding 1 — the original claimed the status line carries the server's message, but the reviewer MEASURED that the load-time swap-status probe repaints over it (see History, Review row). SECOND PASS executed after Step 4/5: the strong sentence restored (the stack model makes it true), six catalog entries added for the stack tests, the serialize-failure entry's recovery wording updated to match the tester's in-place strengthening, both docs' Last-updated stamps bumped to 2026-11-01. -->
   → Evidence: `doc/test-catalog.html` carries one `<li>` per new test in the admin category — two from round 1, six `admin-html-status-stack-*` entries from the second pass — and the `test_admin_config_serialize_failure_500` entry's recovery wording now matches the test; `doc/operations.html` `#admin-incomplete-view`'s `/admin/api/config` row states the stack behavior (diagnostic visible beneath the newer line; success clears; tick pins to top); both docs' stamps read 2026-11-01; `python scripts/check_doc_anchors.py` → `PASS — 258 anchor reference(s) resolved, 8 html file(s) scanned` (exit 0, second pass, 2026-11-01). No counts maintained in either doc.

4. **Step 4: Stack status messages — failures stack, success clears, the ticking wait pins to the top** — apply the Step 4 block in Guidance for Coder to `src/claude_retry_proxy/admin.html`.
   <!-- ADDED 2026-11-01: user-directed revision superseding the skip-the-probe option for the review Warning; the guard edit itself is unchanged. REVISED same day (issue step4-showstatus-undefined-key-collision, filed by coder round 2): the supplied block tested `key !== null` while every call site binds `key` to `undefined`, so unkeyed paints took the keyed arm and still replaced — measured by the coder under Node (stack depth 1 defective, 2 normalized). The block now normalizes (`key === undefined → null`), names the exact call sites, and supplies CSS literals; the gate gained the normalization pin. REVISED again after the post-implementation mega-audit (2026-11-01, 38 findings): keyed entries gained `removeStatusKey` + unconditional finally calls (defect-tracer High: a failed Apply left the sticky 'applying — …' line permanently frozen as the page's only status — measured under Node); the unkeyed dedupe arm was scoped to unkeyed entries (an identical-text unkeyed paint could splice out a keyed entry and grow the stack); loadConfig gained the providers-before-guard, tolerant-parse, and sticky-catch amendments. Gate re-proven RED 1/21 (the pass is the loadConfig-found precondition). -->
   → coder verify (scripted): run `python tmp/verification/2026-11-01-admin-config-500-surface-step4.py` from the repo root; it must print 21/21 PASS, `GATE GREEN`. Calibration: RED on the pre-change tree, measured 2026-11-01 across three gate revisions — 0/11, then 0/12, then 1/21 as checks were added, each with the script unedited per revision; on every version every added check fails pre-change.
   → tester verify: the Step 5 stack-model tests pass, including the warning-scenario assertion (guard line visible beneath the re-read line).

5. **Step 5: Test the status-stack model** — tester adds the permanent stack-model tests per Guidance for Tester and runs the suite.
   → tester verify: new tests pass; the full suite reports no new failures; the Step 1 shape test and the tester's 12/12 reachability gate still pass unedited; session report records the run.

6. **Step 6: Give the attach family its keyed exit** — in the attach watcher's terminal failed-re-read branch (the `else` after `refreshTiersFromServer()` returns false, shipped admin.html:662-669), add `removeStatusKey('attach-wait');` as the branch's first statement, before the terminal paint:
   <!-- ADDED 2026-11-01: user-directed fix of review-2 Warning (measured: after a 409 hand-off + failed re-read the frozen keyed line persisted above the terminal line; the press-family exit was not generalized). -->
   ```javascript
                        } else {
                            removeStatusKey('attach-wait');
                            // The tier row could not be re-read, so it may
                            // still be one swap behind. Stay locked and say
                            // so — unlocking here would let a press write
                            // that stale baseline back over the swap.
                            showStatus('pending', prefix +
                                'the config could not be re-read — reload this page before applying', true);
                        }
   ```
   → coder verify (scripted): the step-4 gate's two attach-exit pins pass — `removeStatusKey('attach-wait')` appears exactly once, `'attach-wait'` literals total 4 (3 paints + 1 removal); all prior checks stay PASS. Run `python tmp/verification/2026-11-01-admin-config-500-surface-step4.py`: 22/22 PASS, `GATE GREEN`. Calibration: the two new checks are RED pre-change, measured 2026-11-01 — 20/22 on the unfixed tree, every prior check GREEN.
   → tester verify: the Step 7 attach-exit pin passes; the dead-end behavioral scenario (409 hand-off + failed re-read) leaves exactly the terminal line.

7. **Step 7: Pin the attach-family exit** — tester extends the keyed-removal coverage: one permanent row asserting the terminal failed-re-read branch carries the `removeStatusKey('attach-wait')` call (source-shape, comment-stripped like its siblings), plus a Node-probe behavioral check (throwaway, under `./tmp/verification/`) that the 409-hand-off-then-failed-re-read scenario ends with the terminal line alone — the exact scenario review-2 measured as frozen. Run the full suite; session report.
   → tester verify: new/extended rows pass; suite reports no new failures; session report records the run.

## Guidance for Planner

Documentation tasks executed by the planner (not the coder):

- **Files to modify:**
  - `doc/test-catalog.html`
  - `doc/operations.html`
- **`.claude/mega-audit-files.json`:** no declared audit locations added, renamed, or retired by this plan.
- **When:** after each round that adds tests or changes page behavior — first pass done 2026-11-01; second pass after Step 5.
- **What to sync:**
  - `doc/test-catalog.html`: one entry per new permanent test in the admin-API/admin-page area, matching the existing one-line `<li><code>test_name</code>: description.</li>` format; no exact test counts (documentation must not maintain counts). **Conditional on Step 4 landing:** after it lands, the `test_admin_html_load_config_status_guard` entry's "surfaces the server's diagnostic on the status line" wording becomes true as written (the diagnostic stays visible beneath newer lines); before it lands the wording overstates — keep the pre-Step-4 sentence qualified.
  - `doc/operations.html`: `#admin-incomplete-view`'s `/admin/api/config` row — **conditional on Step 4 landing:** after it, the status area is a stack (the server's diagnostic stays visible beneath the newer re-read line; a success clears the stack; the ticking wait line pins to the top); until then the current narrowed sentence (generic re-read message wins) is the true one. Also update both docs' "Last updated" stamps (`operations.html` line 13 and its footer, `test-catalog.html` line 13) on this pass.
  - `doc/content.html`: no change needed (it indexes files, not sections; this plan adds no doc file) — disposition recorded here so the sweep is auditable.
  - `CLAUDE.md` / `README.md`: no change needed — the 500 is documented in `doc/operations.html` (lines 162, 182), which is the deep reference CLAUDE.md points at.

## History

| Date | Event | Conclusion | Dismissed |
|------|-------|------------|-----------|
| 2026-11-01 | Initial plan | Paired plan drafted from two deferred Phase 6-review findings; approach confirmed by the user 2026-10-31 ("go ahead"); step-1 gate proven RED pre-change (7/8 FAIL) | — |
| 2026-11-01 | Implementation round (coder) | exit 0, report present, no retry spent; edit applied byte-identically to Guidance for Coder; gate reported 7/8 RED via its own comment collision — coder filed [step1-gate-rendertiers-comment-collision](./tmp/reports/2026-11-01-admin-config-500-surface-step1-gate-rendertiers-comment-collision.json) instead of touching the gate or the edit | — |
| 2026-11-01 | Spec revision (/update-plan) | Gate hardened to comment-stripped matching (planner-owned script), issue resolved 8/8 GREEN exit 0, step-1 calibration sentence corrected in Proposed Changes; tester round directed via Immediate Actions | — |
| 2026-11-01 | Implementation round (tester) | exit 0, report present; [SUCCESS](./tmp/reports/2026-11-01-admin-config-500-surface-tester-2026-11-01.json) — both permanent tests pass, suite 489/489, zero skips/warnings; tester's own 12/12 reachability gate proves every new assertion's failing branch fires (HEAD-literal + five single-property mutants); coder edit re-measured byte-identical to the plan block; no issues filed | — |
| 2026-11-01 | Spec revision (/update-plan) | Both adopted deferrals marked Resolved on the tester SUCCESS evidence; finalize path entered — Phase 6 review launched; remaining planner work: Step 3 doc sync (test-catalog entries; operations.html #admin-incomplete-view sentence, location pinpointed by the tester) | — |
| 2026-11-01 | Review | Verdict ["Issues found — non-blocking"](./tmp/reports/2026-11-01-admin-config-500-surface-review-2026-11-01.json): 0 Critical / 1 Warning / 4 Suggestion. Actioned in-plan: operations.html sentence narrowed to the measured terminal behavior (Warning: the guard's line is repainted over by the load-time swap-status probe — order [guard → checkInFlightSwapOnLoad → refreshTiersFromServer → second 500 → repaint], verified under Node); step-1 gate check 8 hardened to `count == 1`, re-run 8/8 GREEN. Ordering-fix decision raised to the user at approval | [review-load-line-overwritten](./tmp/reports/2026-11-01-admin-config-500-surface-review-2026-11-01.json), [review-drive-get-docstring](./tmp/reports/2026-11-01-admin-config-500-surface-review-2026-11-01.json), [review-recovery-restores-null](./tmp/reports/2026-11-01-admin-config-500-surface-review-2026-11-01.json), [review-tail-swap-call-unpinned](./tmp/reports/2026-11-01-admin-config-500-surface-review-2026-11-01.json) |
| 2026-11-01 | Spec revision (/update-plan) | User directed the status-stack model (failures stack newest-on-top; success clears; keyed tick lines pin to the top) superseding the skip-the-probe option; Steps 4–5 added (coder stack model, tester stack coverage), review Warning → Fix Planned, step-4 gate written and proven RED 0/11; Final Results superseded pending the new rounds; audit trigger evaluated: steps_changed 2 < 3 → not fired | [review-drive-get-docstring](./tmp/reports/2026-11-01-admin-config-500-surface-review-2026-11-01.json), [review-recovery-restores-null](./tmp/reports/2026-11-01-admin-config-500-surface-review-2026-11-01.json), [review-tail-swap-call-unpinned](./tmp/reports/2026-11-01-admin-config-500-surface-review-2026-11-01.json) |
| 2026-11-01 | Implementation round (coder, ordinal 2) | exit 0, report present, no retry spent; step 4 BLOCKED before any edit — coder measured the supplied block's `key !== null` vs `undefined` defect under Node and filed [step4-showstatus-undefined-key-collision](./tmp/reports/2026-11-01-admin-config-500-surface-step4-showstatus-undefined-key-collision.json) instead of applying it; admin.html untouched; round-1 work intact (gate1 8/8) | — |
| 2026-11-01 | Spec revision (/update-plan) | Step 4 block corrected (normalize `key===undefined→null`, exact call sites 299/319/376/396→swap-wait and 544/595/612→attach-wait with 590 explicitly unkeyed, CSS literals from the real palette), gate check 12 added and re-proven RED 0/12, key-collision issue resolved; steps_changed reaches 3 → post-implementation mega-audit fires (cap 1) | — |
| 2026-11-01 | Mega-audit (post-implementation, iteration 1) | [Report](./tmp/reports/2026-11-01-admin-config-500-surface-mega-audit-2026-11-01.json), verdict "plan needs revision": 38 findings (3 High / 16 Medium / 19 Low). Highs: swap-wait keyed-entry dead-end **fixed** (removeStatusKey + unconditional finally calls + Step 5 regression test + gate pins; the frozen 'applying — …' line was measured under Node); the two "Step 4 absent from tree" findings **dismissed** — the audit ran mid-revision by design, the implementation round is queued. All 16 Mediums fixed (unkeyed dedupe scoped, loadConfig providers-before-guard + tolerant parse + sticky catch, gate grown to 21 checks re-proven RED 1/21, tester/planner guidance, metadata, doc-sync conditionals, out-of-scope sentence corrected). Counters reset | [mega-audit-step4-not-yet-applied](./tmp/reports/2026-11-01-admin-config-500-surface-mega-audit-2026-11-01.json), [mega-audit-steps-4-5-absent-pending-round](./tmp/reports/2026-11-01-admin-config-500-surface-mega-audit-2026-11-01.json), [mega-audit-error-text-suffix](./tmp/reports/2026-11-01-admin-config-500-surface-mega-audit-2026-11-01.json), [mega-audit-rollback-row](./tmp/reports/2026-11-01-admin-config-500-surface-mega-audit-2026-11-01.json), [mega-audit-verdict-provisional-pre-round](./tmp/reports/2026-11-01-admin-config-500-surface-mega-audit-2026-11-01.json), [mega-audit-files-table-step4-row](./tmp/reports/2026-11-01-admin-config-500-surface-mega-audit-2026-11-01.json), [mega-audit-stack-cap-speculative](./tmp/reports/2026-11-01-admin-config-500-surface-mega-audit-2026-11-01.json), [mega-audit-type-allowlist](./tmp/reports/2026-11-01-admin-config-500-surface-mega-audit-2026-11-01.json), [mega-audit-poll-guard-catalog-node-mention](./tmp/reports/2026-11-01-admin-config-500-surface-mega-audit-2026-11-01.json) |
| 2026-11-01 | Implementation round (coder, ordinal 3) | exit 0, report present; Step 4 applied byte-identically (64-line block) — gate 21/21 GREEN, step-1 gate and the tester's 12/12 reachability gate re-verified GREEN, page script parses under `node --check`; no issues filed; three benign observations recorded in [the report](./tmp/reports/2026-11-01-admin-config-500-surface-coder-2026-11-01-3.json); Step 5 unblocked | — |
| 2026-11-01 | Implementation round (tester, ordinal 2) | exit 0, report present; [SUCCESS](./tmp/reports/2026-11-01-admin-config-500-surface-tester-2026-11-01-2.json) — six permanent `admin-html-status-stack-*` tests (assertions (a)–(f) one each), 26 live rows with HEAD discrimination + 14 single-property mutants + Node behavioral measurement including the dead-end; `test_admin_config_serialize_failure_500` strengthened in place; suite 495/495, zero skips; all four gates re-run GREEN unedited; review Warning measured fixed → Issue Log row Resolved | — |
| 2026-11-01 | Spec revision (/update-plan) | Step 3 second doc pass executed (strong sentence restored, six catalog entries, recovery wording synced, stamps bumped; anchor check PASS); finalize path re-entered — fresh Phase 6 review launched over the full diff | — |
| 2026-11-01 | Review (round 2) | Verdict ["Issues found — non-blocking"](./tmp/reports/2026-11-01-admin-config-500-surface-review-2026-11-01-2.json): 0 Critical / 1 Warning / 3 Suggestion. Warning (measured): the attach watcher's terminal failed-re-read branch never removes its keyed `attach-wait` entry — after a 409 hand-off + failed re-read the page permanently holds the frozen "waiting for in-flight request(s)… (no need to refresh)" line above the terminal line; the press-family `removeStatusKey` exit was not generalized to the attach family, and the plan's constraint forbade the coder from touching that branch. Fix-or-dismiss raised to the user at approval; the fix is one `removeStatusKey('attach-wait')` call in the terminal branch + a pinning test row (Suggestion 4). Step-4 block confirmed faithfully applied; round-1 guard intact; entry lifecycle sound under measurement; all gates re-run GREEN on the tree | [review2-attach-wait-terminal-exit-missing](./tmp/reports/2026-11-01-admin-config-500-surface-review-2026-11-01-2.json), [review2-recovered-load-sticky-line](./tmp/reports/2026-11-01-admin-config-500-surface-review-2026-11-01-2.json), [review2-keyed-repaint-raw-count](./tmp/reports/2026-11-01-admin-config-500-surface-review-2026-11-01-2.json), [review2-attach-exit-unpinned](./tmp/reports/2026-11-01-admin-config-500-surface-review-2026-11-01-2.json) |
| 2026-11-01 | User decision (approval round) | The user chose "Fix the attach exit, then commit": review-2 Warning becomes `review2-attach-wait-terminal-exit-missing` (Fix Planned); Suggestions 2-3 stay recorded, not adopted |
| 2026-11-01 | Spec revision (/update-plan) | Steps 6-7 added (coder: `removeStatusKey('attach-wait')` in the terminal failed-re-read branch; tester: attach-exit pin + behavioral probe); constraint amended to permit exactly that call; gate's attach pins added — re-proven RED 20/22 (the two new checks fail, all prior GREEN); Final Results superseded pending the rounds |
| 2026-11-01 | Implementation round (coder, ordinal 4) | exit 0, report present; Step 6 applied exactly as specified (one call in the terminal else-branch) — gate 22/22 GREEN with both new pins passing, `node --check` clean; no issues filed; [report](./tmp/reports/2026-11-01-admin-config-500-surface-coder-2026-11-01-4.json) | — |
| 2026-11-01 | Implementation round (tester, ordinal 3) | exit 0, report present; [SUCCESS](./tmp/reports/2026-11-01-admin-config-500-surface-tester-2026-11-01-3.json) — keyed-removal coverage 9→13 rows (four attach-family pins incl. first-statement position), frozen-line scenario measured fixed both ways (live page vs removal-deleted mutant), gate 18/18, all gates re-run GREEN, suite 495/495; review-2 Warning Resolved | — |
| 2026-11-01 | Spec revision (/update-plan) | Step 3 doc touch-up executed (keyed-removal catalog entry names both families' exits); finalize path re-entered — Phase 6 review round 3 (delta-scoped) launched | — |
| 2026-11-01 | Review (round 3, delta-scoped) | Verdict ["Issues found — non-blocking — ready to commit"](./tmp/reports/2026-11-01-admin-config-500-surface-review-2026-11-01-3.json): 0 Critical / 0 Warning / 2 Suggestion. Fix verified as exactly one pure insertion at the terminal branch's first statement; four pin rows' failing branches fire (18/18 gate with two mutants); the frozen-line scenario re-measured (terminal line alone vs both on the mutant); no regression. Catalog wording corrected by the planner (above→beneath; attach-family consequence clause); the parallel test-diagnostic wording left as a dismissed suggestion | [review3-test-diagnostic-above-beneath](./tmp/reports/2026-11-01-admin-config-500-surface-review-2026-11-01-3.json), [review3-catalog-above-beneath](./tmp/reports/2026-11-01-admin-config-500-surface-review-2026-11-01-3.json) |

## Plan Metadata

```json
{
  "plan_id": "2026-11-01-admin-config-500-surface",
  "steps": [
    "Step 1: Guard loadConfig against a non-OK /admin/api/config response",
    "Step 2: Commit the /admin/api/config 500 coverage and pin the page guard",
    "Step 3: Sync documentation for the new tests and page behavior",
    "Step 4: Stack status messages — failures stack, success clears, the ticking wait pins to the top",
    "Step 5: Test the status-stack model"
  ],
  "coder_files": ["src/claude_retry_proxy/admin.html"],
  "tester_files": ["tests/test_admin.py"],
  "doc_files": ["doc/test-catalog.html", "doc/operations.html"],
  "verification_scripts": [
    "./tmp/verification/2026-11-01-admin-config-500-surface-step1.py",
    "./tmp/verification/2026-11-01-admin-config-500-surface-step2.py",
    "./tmp/verification/2026-11-01-admin-config-500-surface-step4.py",
    "./tmp/verification/2026-11-01-admin-config-500-surface-step5.py"
  ],
  "repo_mode": "Public",
  "document_overrides": []
}
```

## Audit Accumulation

*Counters reset when mega-audit runs. Used by Phase 5 entry trigger.*

| Counter | Value | Last Updated |
|---------|-------|--------------|
| issues_resolved_since_audit | 2 | 2026-11-01 |
| steps_changed_since_audit | 2 | 2026-11-01 |
| files_changed_since_audit | 0 | 2026-11-01 |

*Counter convention: the tables track plan-side changes (Issue Log resolutions, step text, the declared file sets) during planner sessions — not the working tree, which lags the plan until its round runs.*

## Documentation

Human-facing reference: [doc/content.html](doc/content.html) indexes the tree. Doc changes for this plan are planner-owned and listed in Guidance for Planner.

## Final Results

**Status: COMPLETED — 2026-11-01**

### What was built

1. **Step 1 (coder):** the `loadConfig()` status guard — a non-OK `/admin/api/config` response routes through `errorText` and returns before `renderTiers()`. Byte-identical to the plan block; gate 8/8; pinned by `test_admin_html_load_config_status_guard`.
2. **Step 2 (tester):** `test_admin_config_serialize_failure_500` commits the GET 500 branch (in-process, set-valued fixture); strengthened in place (recovery GET uses a literal serializable document).
3. **Steps 4-5 (user-directed status-stack model):** failures stack newest-on-top; success clears; the ticking wait lines are keyed and pin to the top; keyed entries have exits in both press handlers' `finally` blocks **and** in the attach watcher's terminal failed-re-read branch; per-entry timers replaced the single `statusTimer`. Gate 22/22; six permanent `admin-html-status-stack-*` tests with mutant-proven reachable failing branches plus Node behavioral measurement; the round-1 review Warning (diagnostic repainted over) is measured fixed.
4. **Step 6-7 (review-2 fix, user-directed):** `removeStatusKey('attach-wait')` as the attach terminal branch's first statement; four attach-family pin rows (exactly-once, branch containment, first-statement, before-paint) with two single-property mutants; the frozen-line scenario measured fixed both ways (terminal line alone on the live page; both lines on the removal-deleted mutant).
5. **Step 3 (planner, two passes + touch-up):** eight test-catalog entries, the `#admin-incomplete-view` stack sentence, stamps; anchor check PASS (258 anchors, 8 files).

**Test results:** suite 495 passed / 0 failed / 0 skipped; all gates GREEN on the final tree (step1 8/8, step2 12/12, step4 22/22, step5 45/45, step7 18/18).

**Review verdicts:** round 1 — 0 Critical / 1 Warning / 4 Suggestion (the Warning drove the stack model); round 2 — 0 Critical / 1 Warning / 3 Suggestion (the Warning drove Step 6-7); round 3 — 0 Critical / 0 Warning / 2 Suggestion, "ready to commit".

### Known caveats

1. A recovered load (re-read success) leaves the sticky "Failed to load config" line painted — reachable only in a narrow window (swap completing between two back-to-back GETs, or a transient failure the re-read recovers). Review-2 Suggestion, explicitly not adopted (user chose the attach-exit fix only).
2. One test row's diagnostic says the frozen wait line sits "above" the terminal line; renderStatus appends newest-first, so it renders beneath (review-3 Suggestion — wording only; the ordering row and the measurement both pin the true order). The catalog wording was corrected; the test-diagnostic wording is left for a future touch-up.
3. Visual artifacts noted by the coder rounds (container tinted by the top entry's type; contiguous color bands) — cosmetic, by design of the plan's CSS literals.

### Deferred issues

This plan defers nothing. Both adopted deferrals are `Resolved`. Still open in the repo, unadopted (visibility only): `parse-guard-gate-top-level-scope`, `switch-key-name-container-echo`, `orphaned-test-state-files`, `httpx2-native-sse-transport`.

### Cross-References to Prior Plans

| Prior Plan | Deferred Issue | Resolution |
|------------|---------------|------------|
| 2026-10-25-guard-totality-and-blank-admin | `defer-issue-admin-page-loadconfig-ignores-response-ok` | This plan's Step 1 added the `loadConfig` status guard (now stack-backed so the diagnostic stays visible); `test_admin_html_load_config_status_guard` pins it on the served page |
| 2026-10-25-guard-totality-and-blank-admin | `defer-issue-config-serialize-500-no-committed-coverage` | This plan's Step 2 committed `test_admin_config_serialize_failure_500` (in-process GET, unserializable-value fixture) |
