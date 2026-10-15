# Plan: Make proxy shutdown and `stop` report the truth
**Project:** D:\proj\claude-retry-proxy
**Plan ID:** 2026-10-15-posix-shutdown-and-stop-reporting
**Created:** 2026-10-15

## Issue Log

| Issue | Status | Found | Resolved | Resolved By |
|-------|--------|-------|----------|-------------|
| [review3-harness-both-signal-handlers-windows](./tmp/reports/defer-issue-harness-ready-marker-comment-windows.json) | Deferred | 2026-10-15 | — | planner — deferred to [2026-10-15-test-harness-robustness](./tmp/plans/2026-10-15-test-harness-robustness.md) Step 4, which already owns `tests/_harness.py`; its gate is verified red pre-fix. One-word comment fix, not worth a separate round here |
| [review3-step4-gate-token-presence](./tmp/reports/2026-10-15-posix-shutdown-and-stop-reporting-review3-2026-10-15.json) | Resolved | 2026-10-15 | 2026-10-15 | planner — step-4 gate conditions 2 and 3 rewritten as AST walks (a comment satisfies a regex but does not exist in an AST); calibration proves the comment-only pin now fails |
| [review3-step4-gate-timestamp-dead-code](./tmp/reports/2026-10-15-posix-shutdown-and-stop-reporting-review3-2026-10-15.json) | Resolved | 2026-10-15 | 2026-10-15 | planner — step-4 gate condition 1 now selects the enclosing `log_trace({...})` literal; `step4-calibration.py` drives it RED on a format change and on a missing timestamp, and the old text condition was reproduced returning PASS on a comment-only pin |
| [review2-posix-test-missing-rc-assertion](./tmp/reports/2026-10-15-posix-shutdown-and-stop-reporting-review2-2026-10-15.json) | Resolved | 2026-10-15 | 2026-10-15 | planner — step-4 gate asserts a real rc check inside the POSIX test (exit 0); the assertion itself skips on this box |
| [review2-proxy-ready-field-set-drift](./tmp/reports/2026-10-15-posix-shutdown-and-stop-reporting-review2-2026-10-15.json) | Resolved | 2026-10-15 | 2026-10-15 | planner — `proxy_ready` now carries `pid` + `port` with the siblings' `.000Z` format; step-4 gate exit 0 |
| [review2-proxy-ready-no-runnable-pin](./tmp/reports/2026-10-15-posix-shutdown-and-stop-reporting-review2-2026-10-15.json) | Resolved | 2026-10-15 | 2026-10-15 | planner — pinned in `tests/test_trace.py::test_trace_markers`, which runs on Windows; `trace-markers: PASSED` in the 420/0 run |
| [review2-harness-ready-marker-comment-stale](./tmp/reports/2026-10-15-posix-shutdown-and-stop-reporting-review2-2026-10-15.json) | Resolved | 2026-10-15 | 2026-10-15 | planner — comment corrected by reading; no behaviour involved |
| [review2-liveness-comment-vs-sigterm](./tmp/reports/2026-10-15-posix-shutdown-and-stop-reporting-review2-2026-10-15.json) | Resolved | 2026-10-15 | 2026-10-15 | planner — comment now states the SIGTERM is best-effort on unverified liveness and why that is accepted; verified by reading |
| [review-posix-sigterm-test-readiness-race](./tmp/reports/2026-10-15-posix-shutdown-and-stop-reporting-review-2026-10-15.json) | Resolved | 2026-10-15 | 2026-10-15 | planner — sync rewritten to poll `proxy_ready` (Step 3 was added to give the test a positive post-registration signal); the POSIX branch itself skips on this Windows box, so its behaviour is verified by reading, not execution |
| [review-cmd-stop-wall-clock-wait-bounds](./tmp/reports/2026-10-15-posix-shutdown-and-stop-reporting-review-2026-10-15.json) | Resolved | 2026-10-15 | 2026-10-15 | planner — step-2 gate asserts no `time.time()` remains in `cmd_stop` (exit 0); full suite 420/0 |
| [review-pid-aba-race-on-sigkill-escalation](./tmp/reports/2026-10-15-posix-shutdown-and-stop-reporting-review-2026-10-15.json) | Resolved | 2026-10-15 | 2026-10-15 | planner — SIGKILL escalation removed on user direction; step-2 gate now asserts its **absence** (exit 0) and `cli-stop-returns-one-and-keeps-state-when-proxy-survives` PASSED |
| [cli-stop-always-returns-zero](./tmp/reports/defer-issue-cli-stop-always-returns-zero.json) | Resolved | 2026-10-05 | 2026-10-15 | planner — independent verification, no tester report (round ended before writing one): `cli-stop-returns-one-and-keeps-state-when-proxy-survives` PASSED |
| [posix-sigterm-shutdown-deadlock](./tmp/reports/defer-issue-posix-sigterm-shutdown-deadlock.json) | Resolved | 2026-10-04 | 2026-10-15 | planner — independent verification, no tester report: `sigterm-shutdown-is-graceful-on-posix` PASSED (POSIX-gated; skips by design on this Windows box) + source-shape gate exit 0 |

## Guidance for Coder

**Files to modify:** `src/claude_retry_proxy/server.py`, `src/claude_retry_proxy/cli.py`

Two defects, one theme: the proxy's shutdown path and the CLI's report of it
both lie. Fix them together — the second hides the first.

**Do not** change any other CLI subcommand, the admin API, or the swap/drain
machinery. `cmd_status`'s exit codes are already correct and stay as they are.

### Step 1: dispatch the signal handler's shutdown onto another thread

Replace the synchronous call in `_shutdown_handler` (currently
`src/claude_retry_proxy/server.py:3973-3974`) with a daemon-thread dispatch,
and correct the stale comment above it (lines 3969-3972 currently claim
`server.shutdown()` "causes serve_forever() to return normally", which is true
only when it is not called *from* the `serve_forever` thread).

The correct idiom already exists in this file — the admin handler's
`_delayed_shutdown` (around line 3343). Mirror it:

```python
    def _shutdown_handler(signum, frame):
        # socketserver.BaseServer.shutdown() blocks until serve_forever()
        # returns, and a Python signal handler runs ON the serve_forever
        # thread — calling it inline is the documented deadlock. Dispatch it,
        # mirroring the admin path's _delayed_shutdown.
        threading.Thread(target=server.shutdown, daemon=True).start()
```

No `time.sleep` is needed here (the admin path sleeps 0.1 s only to let its
HTTP response flush first). Keep both `signal.signal` registrations unchanged.

→ coder verify (auto): read `_shutdown_handler` — its body is a single
  `threading.Thread(target=server.shutdown, daemon=True).start()`; no bare
  `server.shutdown()` call remains in the handler
→ coder verify (scripted): `python ./tmp/verification/2026-10-15-posix-shutdown-and-stop-reporting-step1.py`
  (exit 0 required)
→ tester verify: on POSIX, a spawned proxy that receives SIGTERM exits within
  the wait budget, its state file is gone, and its trace ends with `proxy_stop`.
  Gated `os.name == "posix"` — this does not run on the Windows dev box.

### Step 2: make cmd_stop's exit code and state-file lifetime truthful

`cmd_stop` (`src/claude_retry_proxy/cli.py:629`) returns 0 on every path, and it
removes `PROXY_STATE_FILE` at step 3 (line ~676) *before* force-killing at step
4 (line ~684). When the kill fails, the PID record is already destroyed, so no
later `stop` can ever find the orphan.

Reorder and re-report, keeping the existing graceful HTTP shutdown and its
5-second wait untouched:

1. Read state. **Absent state file stays `return 0`** with the existing
   `"Proxy: not running (no state file)"` message — stopping a stopped proxy is
   a successful no-op, and this leaves idempotent stop scripts working.
2. Graceful `POST /admin/shutdown` and the 5 s exit wait — unchanged.
3. Force-kill if the PID is still alive:
   - **win32:** `kill_process_windows(pid)`, then the existing `time.sleep(0.3)`.
   - **POSIX:** `os.kill(pid, signal.SIGTERM)`, then a bounded wait (poll
     `is_pid_alive(pid)` every 0.3 s up to 5 s). A `ProcessLookupError`/
     `OSError` from the kill means the process is already gone — treat it as
     exit, not failure. **Do not escalate to `SIGKILL`** (see Step 2's
     revision comment below).

<!-- UPDATED 2026-10-15 (/update-plan, post-review): the SIGKILL escalation this
     step originally specified has been REMOVED on user direction. PID liveness
     is not proxy identity — is_pid_alive is os.kill(pid, 0), which answers
     "does something hold this PID", not "is it our proxy", and returns True for
     an unreaped zombie. A recycled PID would be SIGKILLed, and because a failed
     stop deliberately PRESERVES the state file, every later `stop` would
     re-escalate against that PID and repeat the harm. The deadlock this
     escalation once defended against is fixed by Step 1, so it was
     defence-in-depth for a case that no longer exists. A proxy that survives
     SIGTERM is now reported (rc 1, WARNING naming the PID, state file
     preserved) and left for a human. -->
<!-- UPDATED 2026-10-15 (/update-plan, post-review): ALL THREE wait deadlines in
     cmd_stop now use time.monotonic(), not time.time() — the two waits this step
     adds AND the pre-existing graceful-exit wait (~lines 662-664), which has the
     identical wall-clock weakness. Only converting the new two would leave one
     clock-sensitive bound in the same function. The change is interval
     arithmetic only, so monotonic is strictly correct. -->

**Deadline rule for this step:** every `deadline = <clock>() + N` / `<clock>() < deadline`
pair in `cmd_stop` uses `time.monotonic()`. No `time.time()` remains in the
function.
4. **Re-check liveness.** If the PID is still alive: print a diagnostic to
   stderr naming the PID, **leave `PROXY_STATE_FILE` in place** (so a later
   `stop`, or a human, can still find it), and `return 1`.
5. Only now remove `PROXY_STATE_FILE` (best-effort, as today), print
   `"Proxy: stopped"`, and `return 0`.

Two contract points the tests pin:
- `"Proxy: stopped"` must move to the success path — it must NOT print when the
  stop failed.
- The removal must be best-effort *and* last: if the proxy exited gracefully the
  server has already removed the file, so `os.remove` raising `OSError` there is
  expected and still a success.

Bounds are literals local to `cmd_stop` (5 s wait, 0.3 s poll). Do not add a new
`SETTINGS` field or env var for them.

→ coder verify (auto): read `cmd_stop` — a `return 1` exists on the
  still-alive path; the `os.remove(PROXY_STATE_FILE)` call appears after the
  final `is_pid_alive` re-check; `"Proxy: stopped"` sits on the success path
  only; a bounded wait follows SIGTERM on the POSIX branch; **no `SIGKILL`
  anywhere**; **no `time.time()` anywhere** (all three deadlines are
  `time.monotonic()`)
→ coder verify (scripted): `python ./tmp/verification/2026-10-15-posix-shutdown-and-stop-reporting-step2.py`
  (exit 0 required)
→ tester verify: (a) the happy path still exits 0, leaves no state file, and
  leaves no live proxy; (b) the failure path is exercised by the child-driver
  test below and returns 1 while preserving the state file.

### Step 3: make readiness post-date signal-handler registration

In `src/claude_retry_proxy/server.py`'s `main()`, `print("READY", flush=True)`
sits at line 3968, **before** the `signal.signal(signal.SIGTERM, ...)`
registration at line 3976. READY therefore advertises a proxy that will kill
itself outright if signalled — the default SIGTERM action runs no `finally`
block, so the `proxy_stop` marker is never written and the state file is never
removed. This is what forced the POSIX regression test to cover the gap with a
`time.sleep(0.5)`.

Two changes at the same site:

1. **Move `print("READY", flush=True)` to after the `signal.signal(...)` calls**
   (after line 3980, before the `try: server.serve_forever()`). READY now means
   "fully initialised". It is one line moved and still precedes
   `serve_forever()`, so the CLI's readiness contract and its two-phase
   detection are unchanged.
2. **Emit a pollable `proxy_ready` trace event at that same point**, so a test
   can synchronise on a positive signal instead of a sleep:

```python
    log_trace({
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "event": "proxy_ready",
        "port": SETTINGS.port,
    })
```

   Metadata-only (no bodies), matching every other lifecycle marker.

<!-- UPDATED 2026-10-15 (/update-plan, post-review2): the snippet above was
     WRONG about matching its siblings, and the implementer followed it
     faithfully. proxy_start/proxy_stop (sinks.py) carry `pid` and use the
     timestamp format "%Y-%m-%dT%H:%M:%S.000Z"; this snippet carried only
     `port` and used "%SZ". The corrected form is in Step 4 below — apply it
     there, do not re-emit from this snippet. -->

→ coder verify (auto): in `main()`, the `signal.signal(signal.SIGTERM, ...)`
  line precedes both `print("READY"` and the `"proxy_ready"` event; `READY` still
  precedes `server.serve_forever()`; the event carries only `timestamp`, `event`
  and `port`
→ coder verify (scripted): `python ./tmp/verification/2026-10-15-posix-shutdown-and-stop-reporting-step3.py`
  (exit 0 required)
→ tester verify: the POSIX test syncs on the `proxy_ready` trace event (bounded
  poll of the trace file) instead of `time.sleep(0.5)`; the full suite stays
  green and every spawned proxy's trace carries the new event

### Step 4: close the re-review's two source findings

**4a — `proxy_ready` must match its lifecycle siblings.** Step 3's snippet was
wrong; the implementer followed it exactly. Replace the emission in
`server.py`'s `main()` with the sibling-consistent form:

```python
    log_trace({
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
        "event": "proxy_ready",
        "port": SETTINGS.port,
        "pid": os.getpid(),
    })
```

`proxy_start` and `proxy_stop` (`src/claude_retry_proxy/sinks.py`) both carry
`pid` and both use the `.000Z` millisecond format. `os` is already imported in
`server.py`.

**4b — the no-SIGKILL comment contradicts the line above it.** In `cli.py`'s
POSIX branch (~line 688) the new comment argues "PID liveness is not proxy
identity" to justify *not* escalating, while the `os.kill(pid, signal.SIGTERM)`
one line above acts on exactly that unverified liveness. Reword so the comment
states what is actually true: SIGTERM is sent on a best-effort basis (a wrong
target that ignores SIGTERM is unharmed, and if it dies the next `stop` simply
re-checks), whereas an unrecoverable SIGKILL would be a different matter. Do not
change the behaviour.

→ coder verify (auto): `proxy_ready` carries `timestamp` (`.000Z`), `event`,
  `port`, `pid`; the `cli.py` comment no longer claims liveness is verified
  identity while SIGTERMming on it
→ coder verify (scripted): `python ./tmp/verification/2026-10-15-posix-shutdown-and-stop-reporting-step4.py`
  (exit 0 required — it also covers the tester's half; a partial pass is
  expected until Step 4c-4e land)
→ tester verify: `proxy_ready` in a spawned proxy's trace carries `pid` and the
  sibling timestamp format

## Guidance for Tester

<!-- UPDATED 2026-10-15: ownership boundary added after the first tester round spent its whole turn (20 min, ~12 tool calls) investigating doc/test-catalog.html's validation and regeneration convention, then ended without writing any test. The question the plan never answered: who updates the catalog. It is the planner, after the round. Do not investigate it. -->

**Scope boundary — read this first.** `doc/test-catalog.html` is **planner-owned**:
the planner updates it after your round, from your session report. Do **not**
read the catalog tooling, investigate whether its counts are validated, or edit
it — there is nothing you need to know about it to do the work below. Likewise,
`tests/test_trace.py`'s `No proxy_stop event` warning belongs to a *different*
plan (`2026-10-15-test-harness-robustness`): do not change that assertion here.

**Your entire job is two new tests in `tests/test_cli.py` plus one session
report.** The two gates for this plan were already run at the end of the last
attempt and pass — the coder's work is intact and verified. Do not re-litigate
the source diff; go straight to writing the tests.

**Tests to create:**
- **Permanent:** `test_stop_returns_one_and_keeps_state_file_when_proxy_survives`
  — in `tests/test_cli.py`. Drive it with the file's established child-driver
  pattern (`python -c "<driver source>"` with `PROXY_STATE_FILE` in `env`; see
  `test_startup_abort_exits_one_with_failing_stderr` around line 1375 for the
  shape). The driver imports `claude_retry_proxy.cli`, points
  `cli._read_state` at a fake `{"pid": <live-looking>, "port": 1}` (port 1 makes
  the graceful HTTP attempt fail fast), stubs `cli.is_pid_alive` to return
  `True` and the platform kill helper to a no-op, then calls `cli.cmd_stop(None)`
  and prints the return code plus whether `cli.PROXY_STATE_FILE` still exists.
  Assert **rc == 1** and **the state file was NOT removed**. This is the direct
  pin on both halves of the Step 2 contract and it is platform-independent.
- **Permanent:** `test_sigterm_shutdown_is_graceful_on_posix` — gated on
  `os.name == "posix"`. Spawn a proxy, send SIGTERM, assert it exits within the
  budget, its state file is gone, and its trace ends with a `proxy_stop` event.
  It will not execute on this machine; it exists so a POSIX run has coverage.

  <!-- UPDATED 2026-10-15 (/update-plan, post-review): the readiness sync is
       rewritten. The existing test waits for the state file to appear and then
       sleeps a fixed 0.5 s, because READY is printed before signal.signal()
       registers the handler — on a loaded POSIX box SIGTERM can therefore
       arrive pre-registration, take the default action, kill the child with no
       finally block, and fail the test spuriously. That flake is unobservable
       on this Windows box, which is exactly where a POSIX regression guard is
       least useful. Step 3 makes the child emit a `proxy_ready` trace event
       after registration; poll for THAT (bounded deadline, e.g. 10 s) instead
       of sleeping, and drop the fixed sleep entirely. -->

  **Readiness sync (revised):** poll the trace file for the `proxy_ready` event
  (bounded, ~10 s) and only then send SIGTERM. Do not sleep a fixed interval and
  do not sync on the state file — both precede handler registration.

### Step 4 (tester half): close the re-review's coverage findings

**4c — assert the exit code.** `test_sigterm_shutdown_is_graceful_on_posix`
currently *prints* `rc` inside a `pass_(...)` message but never asserts it. A
handler that crashes yet still runs `main()`'s `finally` (writing `proxy_stop`
and removing the state file) exits **rc=1** and passes all three existing
assertions — so the one behavioural pin for Step 1 cannot catch the regression
it exists for. Add a hard assertion that `proc.returncode == 0` on the
SIGTERM-exit path.

**4d — pin `proxy_ready` in a test that actually runs here.** The only current
reference to the event lives inside the POSIX-gated test, which skips on this
Windows box — so removing or renaming the event would go unnoticed by anything
runnable. Add the assertion to a test that executes on every platform (a
`test_cli.py` spawn test that already reads the trace, or `test_trace.py`):
assert a spawned proxy's trace contains a `proxy_ready` event carrying `pid` and
`port`.

**4e — fix the stale harness comment.** `tests/_harness.py:477`'s
`_READY_MARKER` comment says READY is emitted "just after the
ThreadingHTTPServer construction". After Step 3 it follows the heartbeat-thread
start **and** both `signal.signal` registrations. That comment is the harness's
stated readiness contract — correct it.

→ tester verify: `python ./tmp/verification/2026-10-15-posix-shutdown-and-stop-reporting-step4.py`
  exits 0 (all three conditions); and the new `proxy_ready` pin is
  load-bearing — temporarily rename the event in a scratch edit and confirm the
  test goes red on this platform

**Tests to investigate for retirement:**
- `tests/test_cli.py`'s existing stop coverage (the `stop_result` guards around
  lines 144 and 238) — check whether either already asserts the state-file
  lifetime. If one does, extend it rather than adding a second test; if the new
  failure-path test supersedes a narrow existing assertion, retire the narrow
  one and say so in the session report.
- Tester may identify additional candidates during test work.

**Retirement procedure:** For each candidate, verify the test exercises code
being removed/changed. If obsolete: delete and note in session report. If still
valid: document why in session report.

**Do not** write a test that tries to kill a protected system process (e.g.
Windows PID 4) to provoke the failure path — the child-driver stub is the
sanctioned way to reach that branch.

## Summary

Two shipped defects make the proxy's lifecycle dishonestly reported, and each
one hides the other.

**1. SIGTERM deadlocks the proxy on POSIX.** `_shutdown_handler` calls
`server.shutdown()` inline. `socketserver.BaseServer.shutdown()` blocks until
`serve_forever()` returns, and a Python signal handler runs on the main thread —
which is exactly where `serve_forever()` is executing. The handler therefore
waits on an event that can only fire after the handler returns. The process is
unrecoverable short of SIGKILL, and because `serve_forever()`'s `finally` never
runs, `write_stop_marker()` never emits `proxy_stop` and the state file is never
removed. Windows is unaffected (`os.kill(pid, SIGTERM)` there is
`TerminateProcess`, which never runs the handler), which is why this survived on
a Windows dev box with no CI.

**2. `cmd_stop` cannot report failure.** It returns 0 on every path, including
after printing *"WARNING: Proxy PID … may still be running"*. Worse, it deletes
`proxy-state.json` *before* attempting the force-kill, so when the kill fails
the only record of the PID is already gone. The suite's one leak-guard
(`subprocess.run(CLAUDE_PROXY + ["stop"])` then `if returncode != 0`) can
therefore never fire. A real orphaned proxy was observed live on 2026-10-05
whose state file had already been cleared by the time anyone looked.

**Approach.** Fix both in place: dispatch the signal handler's shutdown to a
daemon thread (the idiom the admin path already uses), and reorder `cmd_stop` so
the state file is removed only after liveness is confirmed, with a truthful exit
code and a bounded SIGTERM wait on POSIX. The two fixes compose: after them,
`stop` is both able to shut the proxy down and able to say so when it cannot.

<!-- UPDATED 2026-10-15 (/update-plan, post-review): the original approach
     escalated to SIGKILL after the bounded SIGTERM wait. That was removed on
     user direction after the Phase 6 reviewer showed PID liveness is not proxy
     identity — see Step 2's revision comment. A third step was added in the
     same revision: move READY (and add a `proxy_ready` trace event) to
     post-date signal-handler registration, which is what let the POSIX
     regression test sync on a sleep instead of a positive signal. -->

```
  SIGTERM ──► _shutdown_handler ──► Thread(server.shutdown) ──► serve_forever returns
                                                                      │
  cmd_stop ──► graceful HTTP ──► wait 5s ──► force-kill ──► re-check ──┴──► finally:
                                                │                    proxy_stop marker
                                                │                    + state removed
                                                └─ still alive? ──► keep state, exit 1
```

**Alternatives considered.** (a) *Drop the signal handler entirely* — rejected:
the graceful path is what writes the `proxy_stop` marker and cleans up state.
(b) *Handle SIGTERM by setting a flag that `serve_forever` polls* — rejected as
more machinery than the one-line thread dispatch, for no gain. (c) *Make
`cmd_stop` SIGKILL unconditionally* — rejected: it would skip the graceful
shutdown that the marker and state cleanup depend on.

**Out of scope.** Whether the test harness should key `PROXY_STATE_FILE`
per-test rather than per-run; whether the CLI should track spawned proxies by
some means other than the state file; and the `client-write OSError` and
`port-default-collision-hazard` families, which are separate issues.

## Repo Mode

Public

## Document Overrides

| Document | Rule Overridden | Reason |
|----------|----------------|--------|

## Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| The POSIX fix is unverifiable on this machine (Windows dev box, no CI, no POSIX runner) | A wrong POSIX idiom could ship unexercised — the same gap that let this defect live since 2026-07-17 | The fix mirrors an in-repo idiom already correct in production (`_delayed_shutdown`); a source-shape gate pins it; a POSIX-gated test is added for any future POSIX run; the gap is stated plainly rather than papered over |
| Dropping the SIGKILL escalation leaves a SIGTERM-proof proxy unrecoverable by `stop` | A wedged proxy needs a manual `kill -9` | Accepted deliberately: the only known cause of a SIGTERM-proof proxy was the deadlock Step 1 fixes. `stop` still reports rc 1 with a WARNING naming the PID and preserves the state file, so the proxy is findable and a human can kill it. The alternative — escalating on a PID that liveness cannot prove is *our* process — was rejected as the worse trade (see Step 2's revision comment) |
| Moving `READY` later shifts when the CLI's readiness wait can succeed | `start` could report a timeout where it previously succeeded | The move is a few microseconds (past two `signal.signal` calls) and still precedes `serve_forever()`. The CLI's budget is 5 s and the harness's READY deadline is generous; both are unaffected in practice |
| The new `proxy_ready` trace event adds a row to a documented schema | `doc/trace-log.html`'s event inventory drifts | Named in this plan's "Guidance for Planner" — the planner adds it to the inventory when reconciling docs |
| Moving the state-file removal later changes `stop` timing on the happy path | A caller that relied on the file disappearing early | The graceful path removes it server-side in `serve_forever`'s `finally`, so on the happy path the file is gone before `cmd_stop` reaches its own removal — already true today |

## Proposed Changes

1. **Step 1:** Dispatch `_shutdown_handler`'s `server.shutdown()` onto a daemon thread in `src/claude_retry_proxy/server.py`, and correct the stale comment above it
   → coder verify (auto): `_shutdown_handler`'s body is exactly a `threading.Thread(target=server.shutdown, daemon=True).start()`; no inline `server.shutdown()` call remains; both `signal.signal` registrations unchanged
   → coder verify (scripted): `./tmp/verification/2026-10-15-posix-shutdown-and-stop-reporting-step1.py` exit 0
   → tester verify: POSIX-gated `test_sigterm_shutdown_is_graceful_on_posix` — SIGTERM'd proxy exits, state file gone, `proxy_stop` in trace

2. **Step 2:** Reorder `cmd_stop` in `src/claude_retry_proxy/cli.py` so the state file is removed only after liveness is confirmed, the exit code reports a failed stop as 1, and the POSIX branch waits a bounded interval on SIGTERM with **no SIGKILL escalation**; convert all three deadline pairs in the function to `time.monotonic()`
   → coder verify (auto): `return 1` exists on the still-alive path; `os.remove(PROXY_STATE_FILE)` occurs after the final `is_pid_alive` re-check; `"Proxy: stopped"` only on the success path; bounded wait follows SIGTERM; no `SIGKILL`; no `time.time()`
   → coder verify (scripted): `./tmp/verification/2026-10-15-posix-shutdown-and-stop-reporting-step2.py` exit 0
   → tester verify: `test_stop_returns_one_and_keeps_state_file_when_proxy_survives` passes (rc 1, state file preserved); happy-path stop still exits 0 with no state file and no live proxy
3. **Step 3:** Move `print("READY", flush=True)` in `src/claude_retry_proxy/server.py`'s `main()` to after the `signal.signal(...)` registrations, and emit a metadata-only `proxy_ready` trace event there, so readiness post-dates handler registration and is pollable by tests
   → coder verify (auto): the SIGTERM registration precedes both `print("READY"` and the `"proxy_ready"` event; `READY` still precedes `serve_forever()`; the event carries only `timestamp`, `event`, `port`
   → coder verify (scripted): `./tmp/verification/2026-10-15-posix-shutdown-and-stop-reporting-step3.py` exit 0
   → tester verify: the POSIX test polls the trace for `proxy_ready` instead of sleeping; every spawned proxy's trace carries the event; full suite green
4. **Step 4:** Close the re-review's findings — `proxy_ready` gains `pid` and the sibling `.000Z` timestamp format; the `cli.py` no-SIGKILL comment stops asserting what the line above it contradicts (**coder**); the POSIX test asserts `returncode == 0`, a Windows-runnable test pins `proxy_ready`, and `tests/_harness.py`'s stale `_READY_MARKER` comment is corrected (**tester**)
   → coder verify (auto): `proxy_ready` carries `timestamp` (`.000Z`), `event`, `port`, `pid`; the `cli.py` comment no longer claims verified identity
   → coder verify (scripted): `./tmp/verification/2026-10-15-posix-shutdown-and-stop-reporting-step4.py` exit 0 — note it spans both lanes, so it passes only once the tester's half lands too
   → tester verify: same gate exits 0; the POSIX test fails if `returncode != 0`; renaming `proxy_ready` in a scratch edit turns a Windows-runnable test red

## Guidance for Planner

Documentation tasks you will execute yourself (not the coder):

- **Files to modify:**
  - `./doc/operations.html`
  - `./doc/architecture.html`
  - `./doc/trace-log.html`
- **When:** after coder finishes
- **What to sync:**
  - `doc/operations.html` — the command table row for `stop` (line ~26) and the
    shutdown section (~line 249): document that `stop` exits 1 when the proxy
    survives, that the state file is deliberately preserved in that case, and
    the POSIX bounded SIGTERM wait (5 s) — **with no SIGKILL escalation**, and
    why a surviving proxy is left for a human.
  - `doc/trace-log.html` — add the new `proxy_ready` lifecycle event to the
    event inventory, alongside `proxy_start` / `proxy_stop`: emitted once per
    run, immediately after the signal handlers are registered, carrying `port`.
  - `doc/operations.html#readiness` — the READY marker now post-dates signal
    handler registration, so "ready" means handlers are installed too.
  - `doc/architecture.html` — the `shutdown` section (~line 610): record that
    the SIGTERM handler dispatches to a thread because `socketserver` documents
    an inline `shutdown()` on the `serve_forever` thread as a deadlock.
  - **Not in this plan:** `CLAUDE.md`'s "Unresolved Deferred Issues" block. It is
    rewritten wholesale by plan `2026-10-15-deferred-corpus-sweep`, which is the
    single writer for the whole cycle — do not edit it here, or the two plans
    will disagree about which rows exist.

## History

| Date | Event | Conclusion | Dismissed |
|------|-------|------------|-----------|
| 2026-10-15 | Initial plan | Two compounding lifecycle defects (POSIX SIGTERM deadlock; cmd_stop's always-zero exit and premature state-file removal) fixed in one plan; both gates calibrated red against the pre-change tree. | — |
| 2026-10-15 | Implementation round (coder) — `build_result: pass` | Both steps landed in `server.py` and `cli.py`; coder filed zero issues and reported no build warnings ([report](./tmp/reports/2026-10-15-posix-shutdown-and-stop-reporting-coder-2026-10-15.json)). The planner independently re-ran both gates after the round — exit 0 each, previously exit 1 — and read the diff: the handler dispatches to a daemon thread with the stale comment corrected, and `cmd_stop` now force-kills before the liveness re-check, returns 1 preserving the state file when the PID survives, and removes the file last on the success path only. No plan revision required. | — |
| 2026-10-15 | Implementation round (tester) — failed round; retry used (1) | Both attempts exited 0 with no report and no tree change ([attempt 1](./tmp/logs/2026-10-15-posix-shutdown-and-stop-reporting-tester-2026-10-15.log) ended `[10:42:31] exit 0 (no report, no tree change — relaunching)`; the launcher's silent relaunch ran a second full attempt, terminal sentinel `[11:02:36] exit 0`). Attempt 2 was reconnaissance-only and wrote nothing. This is the `operate-round-ends-turn-before-waiting` failure mode; retaining the round's ordinal for the retry cap. | — |
| 2026-10-15 | Implementation round (tester, retry) — report-less round; planner-verified instead | The retry **did the work** (178 lines in `tests/test_cli.py`: both tests plus `ALL_TESTS` wiring at lines 1799-1800), then launched the full suite with `run_in_background=True` at 12:05:17 and exited 18 s later at 12:06:02 with it still in flight — the exact `operate-round-ends-turn-before-waiting` pattern, leaving a 0-byte suite log and no report. Since the artifacts existed, another round was not spent: the planner read both tests against the plan's contract, ran `tests/test_cli.py` (19 passed, 0 failed; both new labels PASSED) and the full suite (420 passed, 0 failed, up from the 418 baseline). Recorded here as the substitute evidence Phase 6 permits for a report-less round. | — |
| 2026-10-15 | Review | Phase 6 reviewer verdict **"Issues found — non-blocking"**, 0 Critical / 2 Warning / 1 Suggestion ([report](./tmp/reports/2026-10-15-posix-shutdown-and-stop-reporting-review-2026-10-15.json)). Reviewer confirmed the two briefed soft spots it could settle: the child-driver test is **not** a tautology (hand-traced against pre-fix `cmd_stop`, both `rc==1` and state-preserved assertions fail there), and the `cmd_stop` exit-path trace introduces **no** new way to orphan a live proxy — every exit path's process/state-file state is accounted for. | [review-pid-aba-race-on-sigkill-escalation](./tmp/reports/2026-10-15-posix-shutdown-and-stop-reporting-review-2026-10-15.json) (Warning: escalation treats PID liveness as proxy identity; a recycled PID would be SIGKILLed), [review-posix-sigterm-test-readiness-race](./tmp/reports/2026-10-15-posix-shutdown-and-stop-reporting-review-2026-10-15.json) (Warning: POSIX test syncs on `time.sleep(0.5)` after READY, which precedes handler registration), [review-cmd-stop-wall-clock-wait-bounds](./tmp/reports/2026-10-15-posix-shutdown-and-stop-reporting-review-2026-10-15.json) (Suggestion: both 5 s bounds use `time.time()`, not `time.monotonic()`) |
| 2026-10-15 | Spec revision (/update-plan, post-review) | User-directed revision of all three reviewer findings. **(1)** SIGKILL escalation **removed** from Step 2 — PID liveness is not proxy identity, and a preserved state file would make every later `stop` re-escalate against a recycled PID; the deadlock it defended against is fixed by Step 1. **(2)** all three `cmd_stop` deadlines converted to `time.monotonic()` (the two the reviewer flagged plus the pre-existing graceful-exit wait at ~662-664, same defect class in the same function). **(3)** new **Step 3**: move `READY` and add a `proxy_ready` trace event to post-date `signal.signal()` registration — the gap that forced the POSIX test to sync on a fixed sleep. Step-2 gate inverted (it previously *asserted* SIGKILL existed); new Step-3 gate added; both calibrated red. `doc/trace-log.html` added to the planner's doc targets. | — |
| 2026-10-15 | Implementation round (coder, revision) — report-less round; planner-verified instead | Same `operate-round-ends-turn-before-waiting` shape a fourth time: the round made all three changes, launched its suite with `run_in_background=True` at 12:52:31, and exited 23 s later at 12:53:04 with it in flight — no report. Planner verification instead: **all three gates pass** (step1 threaded handler; step2 no SIGKILL + `time.monotonic` bounds + removal ordering; step3 READY and `proxy_ready` both post-dating registration at line 3976), the source diff was read in full and matches the revision exactly, and the two risk-carrying modules were re-run — `test_cli.py` 19/0 (the `READY` move did not break readiness) and `test_trace.py` 12/0. | — |
| 2026-10-15 | Implementation round (tester, revision) — report-less round; planner-verified instead | Fifth round to end with its suite in flight: the sync rewrite landed, the file was syntax-checked at 13:04:47, the suite was launched at 13:04:56 (with an explicit `timeout=3600000`, so the brief's warning was acted on), and the round exited 62 s later at 13:05:58 with no report. Planner verification instead: all three gates exit 0, the rewrite was read in full (bounded ~10 s poll of the trace file for `proxy_ready`, live-child check, and a loud refusal to SIGTERM when registration cannot be confirmed), and the full suite ran to completion — **420 passed, 0 failed**, with both Plan-A labels PASSED by name (`cli-stop-returns-one-and-keeps-state-when-proxy-survives`, `sigterm-shutdown-is-graceful-on-posix`). | — |
| 2026-10-15 | Review (re-review) | Second Phase 6 pass on the post-revision tree: verdict **"Issues found — non-blocking"**, 0 Critical / 1 Warning / 4 Suggestion ([report](./tmp/reports/2026-10-15-posix-shutdown-and-stop-reporting-review2-2026-10-15.json)). It confirmed all three prior findings resolved and answered the briefed questions favourably: removing the SIGKILL escalation leaves no state worse than pre-plan (rc 0 + destroyed record → rc 1 + preserved record), and the `READY` move breaks no consumer (CLI 5 s budget, harness 30 s + TCP fallback, exactly-one-stdout-line invariant, fail-fast-before-READY ordering all verified). Added **Step 4** closing all five on user direction. Two of them are **this plan's own spec defects**, not implementation errors: Step 3's `proxy_ready` snippet claimed to match its lifecycle siblings but omitted `pid` and used a different timestamp format, and the tester-verify spec never asked for an exit-code assertion. | — |
| 2026-10-15 | Spec revision (/update-plan, post-review2) | Added Step 4 (five findings) and a step-4 gate, calibrated red on all three of its conditions. Annotated Step 3's snippet as wrong rather than editing it in place, so the record shows what the implementer followed. | — |
| 2026-10-15 | Implementation round (coder, Step 4a/4b) — report-less round; planner-verified instead | Sixth round to exit without a report (ran the step 1-3 gates at 14:04:43, exited at 14:04:57). Its half landed correctly and was verified by reading: `proxy_ready` now carries `port` **and** `pid` with the siblings' `"%Y-%m-%dT%H:%M:%S.000Z"` format, and the `cli.py` comment now states plainly that the SIGTERM above it is sent on best-effort liveness alone — accepted, since a SIGTERM-ignoring target is unharmed — while SIGKILL is rejected as the different matter. The step-4 gate's field-set condition no longer fails; only the two tester conditions remain. | — |
| 2026-10-15 | Implementation round (tester, Step 4c/4d/4e) — report-less round; planner-verified instead | Seventh round to end with its suite in flight (launched 14:18:50, exited 16 s later at 14:19:06). The work landed: **the step-4 gate now exits 0 on all three conditions**, the runnable pin is `tests/test_trace.py::test_trace_markers`, the POSIX test carries a real `returncode` assertion, and the `_READY_MARKER` comment now reads "bound its listening socket, started the heartbeat thread, and registered both signal handlers … still before serve_forever()". Planner verification: full suite **420 passed, 0 failed** with `trace-markers`, `cli-stop-returns-one-and-keeps-state-when-proxy-survives` and `sigterm-shutdown-is-graceful-on-posix` all PASSED by name. | — |
| 2026-10-15 | Spec revision (/update-plan) | Closed a Plan Gap in "Guidance for Tester": it never stated who owns `doc/test-catalog.html`. The failed round spent ~12 tool calls and most of its turn resolving that ownership question, then ended without writing a test. Added an explicit scope boundary (catalog is planner-owned; `test_trace.py`'s `No proxy_stop event` warning belongs to another plan) and a "go straight to the two tests" directive. Also emitted `## Immediate Actions`. No step, file, or verification-script change; Issue Log statuses unchanged. | — |
| 2026-10-15 | Review (third pass) | Third Phase 6 pass, on the Step-4 tree: verdict **"Issues found — non-blocking"**, 0 Critical / 1 Warning / 2 Suggestion ([report](./tmp/reports/2026-10-15-posix-shutdown-and-stop-reporting-review3-2026-10-15.json)). It verified all five Step-4 fixes are correctly applied — 4a `proxy_ready` carries `port` + `pid` with the siblings' `"%Y-%m-%dT%H:%M:%S.000Z"` format byte-matching `sinks.py`; 4b the `cli.py` comment is substantively accurate; 4c `test_cli.py:546` holds a real, reachable `returncode == 0` assertion; 4d `test_trace.py:158-178` runs on this box inside `test_trace_markers`; 4e `_harness.py:476-481` matches `main()`'s actual order. Its Warning lands on **this plan's own gate, not the implementation**: `step4.py`'s condition 1 was dead code. | [review-step4-gate-timestamp-dead-code](./tmp/reports/2026-10-15-posix-shutdown-and-stop-reporting-review3-2026-10-15.json) (Warning → **fixed**, see next row), [review-step4-gate-token-presence](./tmp/reports/2026-10-15-posix-shutdown-and-stop-reporting-review3-2026-10-15.json) (Suggestion → **fixed**, same row), [review-harness-both-signal-handlers-windows](./tmp/reports/2026-10-15-posix-shutdown-and-stop-reporting-review3-2026-10-15.json) (Suggestion → **deferred by design**: `_harness.py`'s "both signal handlers" is false on Windows, where `signal.signal(SIGINT, …)` is POSIX-gated at `server.py:3977`; folded into `2026-10-15-test-harness-robustness`, which already owns that file, rather than spending a round on one comment) |
| 2026-10-15 | Verification-script revision (step-4 gate) | Hardened `step4.py` against both gate findings. **Condition 1** now selects the enclosing `log_trace({...})` literal containing `proxy_ready` instead of capturing the text after the `"event"` key — the old span began *after* `"event"`, but `"timestamp"` precedes it in the dict, so `ready_ts` was always `None` and the format comparison silently skipped; it now fails loudly when no format can be read, so the check cannot skip rather than pass. **Conditions 2 and 3** were rewritten from text regexes to **AST** walks, because a comment satisfies a regex but does not exist in an AST — condition 2 now requires an `if <x>.returncode <cmp> <n>:` whose subtree reaches a `fail()` call, and condition 3 counts only real string constants in non-`posix`-gated tests (excluding docstrings). New `step4-calibration.py` measures the claim instead of asserting it: **5 simulated regressions** — format change, timestamp key removed, rc branch reduced to a print, pin replaced by a **comment**, pin deleted outright — each required to drive the gate RED with the specific diagnostic, plus the real tree required GREEN and the gating required to exclude the POSIX-gated `test_cli.py` pin. The comment case was additionally reproduced against the *old* text condition, which returned PASS with `'# proxy_ready is pinned here'` as the sole remaining mention — confirming the review's finding was a real false pass, not a theoretical one. | — |

## Plan Metadata

```json
{
  "plan_id": "2026-10-15-posix-shutdown-and-stop-reporting",
  "steps": [
    "Step 1: Dispatch _shutdown_handler's server.shutdown() onto a daemon thread in src/claude_retry_proxy/server.py",
    "Step 2: Reorder cmd_stop in src/claude_retry_proxy/cli.py",
    "Step 3: Move READY and add a proxy_ready trace event to post-date signal-handler registration in src/claude_retry_proxy/server.py",
    "Step 4: Close the re-review's findings"
  ],
  "coder_files": ["src/claude_retry_proxy/server.py", "src/claude_retry_proxy/cli.py"],
  "tester_files": ["tests/test_cli.py", "tests/_harness.py", "tests/test_trace.py"],
  "doc_files": ["./doc/operations.html", "./doc/architecture.html", "./doc/trace-log.html"],
  "verification_scripts": [
    "./tmp/verification/2026-10-15-posix-shutdown-and-stop-reporting-step1.py",
    "./tmp/verification/2026-10-15-posix-shutdown-and-stop-reporting-step2.py",
    "./tmp/verification/2026-10-15-posix-shutdown-and-stop-reporting-step3.py",
    "./tmp/verification/2026-10-15-posix-shutdown-and-stop-reporting-step4.py",
    "./tmp/verification/2026-10-15-posix-shutdown-and-stop-reporting-step4-calibration.py"
  ],
  "repo_mode": "Public",
  "document_overrides": []
}
```

## Audit Accumulation

| Counter | Value | Last Updated |
|---------|-------|--------------|
| issues_resolved_since_audit | 0 | 2026-10-15 |
| steps_changed_since_audit | 3 | 2026-10-15 |
| files_changed_since_audit | 2 | 2026-10-15 |

## Documentation

- `doc/operations.html` — `stop` exit-code contract, state-file preservation on
  failure, POSIX escalation.
- `doc/architecture.html` — SIGTERM handler threading rationale.

## Final Results

**Completion date:** 2026-10-15
**Status:** COMPLETED

Two compounding lifecycle defects, both of the same kind: the proxy reported
success it had not achieved. A POSIX `SIGTERM` landed in a signal handler that
deadlocked against the very call it was interrupting, and `stop` exited 0 on
every path while deleting the state file before confirming the process was
gone — so the one record that could have found a surviving orphan was destroyed
by the command that failed to kill it.

### Files changed

| File | Change |
|---|---|
| `src/claude_retry_proxy/server.py` | Step 1: `_shutdown_handler` dispatches `server.shutdown` onto a daemon thread instead of calling it inline. Step 3: `READY` and the new `proxy_ready` trace event moved to post-date `signal.signal()` registration. Step 4a: `proxy_ready` carries `pid` alongside `port` and uses the lifecycle siblings' `"%Y-%m-%dT%H:%M:%S.000Z"` format |
| `src/claude_retry_proxy/cli.py` | Step 2: `cmd_stop` force-kills before the final liveness check, removes the state file last, returns 1 preserving it when the PID survives; all three deadlines on `time.monotonic()`; no SIGKILL escalation. Step 4b: comment corrected to state the SIGTERM is sent on unverified liveness and why that is accepted |
| `tests/test_cli.py` | Two tests: `test_stop_returns_one_and_keeps_state_file_when_proxy_survives` (child-driver with stubs) and `test_sigterm_shutdown_is_graceful_on_posix` (POSIX-gated; syncs on `proxy_ready`, asserts `returncode == 0`). Wired into `ALL_TESTS` |
| `tests/test_trace.py` | `test_trace_markers` pins `proxy_ready` (pid + port) — the only pin that runs on Windows |
| `tests/_harness.py` | `_READY_MARKER` comment updated (see the deferral below for its residual inaccuracy) |
| `doc/operations.html` | New **stop contract** section: the exit-code contract, state-file preservation on failure, and why there is no SIGKILL escalation; `stop` row in the CLI table |
| `doc/architecture.html` | New **signal path** section: why `shutdown()` must be dispatched off the `serve_forever` thread, and why readiness post-dates handler registration |
| `doc/trace-log.html` | `proxy_ready` added to the lifecycle-marker table and the event inventory, with what it promises that `proxy_start` does not |

### Verification

**Test suite: 420 passed, 0 failed, 420 total** (baseline 418; +2 new tests),
1 warning. `trace-markers`, `cli-stop-returns-one-and-keeps-state-when-proxy-survives`
and `sigterm-shutdown-is-graceful-on-posix` all PASSED by name. The single
remaining warning is `No proxy_stop event in trace`, which is the target of
`2026-10-15-test-harness-robustness` Step 3 — not a regression from this plan.

**All five verification artifacts exit 0:** `step1` (handler dispatch, AST),
`step2` (no SIGKILL, `time.monotonic`, removal ordering), `step3` (READY and
`proxy_ready` post-date registration), `step4` (field set, timestamp format,
rc assertion, runnable pin), `step4-calibration`.

**Calibration disclosure.** The step-4 gate was found by the third-pass review
to be **false-passing** on its timestamp condition — it captured only the text
following the `"event"` key while `"timestamp"` precedes it, so the comparison
silently skipped. It was rebuilt (condition 1 now selects the enclosing
`log_trace({...})` literal; conditions 2 and 3 read the AST rather than the
text) and `step4-calibration.py` now *measures* the claim instead of asserting
it: five simulated regressions must each drive the gate RED with a specific
diagnostic, the real tree must be GREEN, and the gating must exclude the
POSIX-gated pin. The old text condition was additionally reproduced returning
PASS on a comment-only pin, confirming the finding was a real false pass. The
same class of trap was then avoided in Plan C's new gate, which requires an
uppercase word-boundary `POSIX`/`Windows` qualifier precisely because the
comment contains the lowercase `posix` of a plan id.

**Three of the four source steps are POSIX-behavioural but Windows-verified.**
Steps 1 and the POSIX `stop` escalation only execute on POSIX; this is a Windows
dev box, so they are pinned by source-shape gates plus a POSIX-gated test that
skips here by design. That gap is the reason the original defect survived, and
it is recorded here rather than papered over.

### Issues resolved

Ten Issue Log rows, all `Resolved`: the two original deferrals
(`cli-stop-always-returns-zero`, `posix-sigterm-shutdown-deadlock`), the first
review's three, and the second review's five. Every one is closed on
planner-side evidence; see the Issue Log for the per-row basis.

### Deferred

- **[harness-ready-marker-comment-windows](./tmp/reports/defer-issue-harness-ready-marker-comment-windows.json)**
  — the `_READY_MARKER` comment this plan introduced still ends "registered both
  signal handlers", which is false on Windows (SIGINT registration is
  POSIX-gated at `server.py:3977`). Deferred by design to
  [`2026-10-15-test-harness-robustness`](./tmp/plans/2026-10-15-test-harness-robustness.md)
  **Step 4**, which already owns `tests/_harness.py`; its gate is verified red
  pre-fix and its calibration harness verifies both directions (it rejects four
  half-fixes, including a comment qualified only by a plan id's lowercase
  `posix`, and accepts a correct rewrite). The finding is a non-blocking
  Suggestion and a wording fix — the load-bearing claim that READY post-dates
  handler registration is true and stays.

### Process note — seven report-less rounds

Every implementation round in this plan (two coder, two tester, then three more
after each revision) ended its turn while a full-suite run was still in flight,
killing the run and writing no session report. That is the
`operate-round-ends-turn-before-waiting` failure mode filed against
`claude-config`. Rather than spend further rounds, each was closed with the
substitute evidence Phase 6 permits: the planner re-ran the gates, read the
diffs in full, and ran the suite to completion, recording the basis in the
History rows. The artifacts are complete and independently verified; the
missing piece throughout was the round's own report, not its work.

### Cycle dependencies

- `CLAUDE.md`'s deferred-issue index still lists `posix-sigterm-shutdown-deadlock`,
  which this plan resolves. That block is deliberately **not** touched here —
  it is rewritten wholesale by
  [`2026-10-15-deferred-corpus-sweep`](./tmp/plans/2026-10-15-deferred-corpus-sweep.md),
  which must run last in the cycle. The interim window is expected.
- `/update-and-commit` Step 9.6 retires each report whose Issue Log row is
  `Resolved`, so this plan's two deferral reports are retired by its own commit.