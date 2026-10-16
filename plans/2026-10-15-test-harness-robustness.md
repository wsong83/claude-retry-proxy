# Plan: Make the test harness self-diagnosing and the state-file policy single-sourced
**Project:** D:\proj\claude-retry-proxy
**Plan ID:** 2026-10-15-test-harness-robustness
**Created:** 2026-10-15

> **This plan has no coder lane.** Every file it touches is a test file
> (`tests/**`), and the coder never writes, revises, or touches tests. All five
> steps are tester-owned. The round sequence for this plan is a **tester round
> only** — there is no coder round to run first.

## Immediate Actions

**Verification-only round. Steps 1–6 have all landed and their gates are green.**
There is no outstanding implementation work in this plan — **change nothing in
`tests/`.**

**Do not re-apply Step 6.** It is already in the tree. Applying it a second time
would install a *second* `_drain_child_stderr(proc)` at each of the 21 spawn
sites, which puts two reader threads on one pipe and splits the child's stderr
between them — the exact defect class this step exists to remove, reintroduced
by a rerun.

Round 3 (2026-10-16) landed Step 6 — 6a, 6b and 6c, **plus** a read-site reroute
the step's own text did not prescribe (Step 6b below now carries it; see the
Issue Log). **That round was killed by its launcher's wrapper at 15:39, before it
wrote its session report**, so this plan's Step 6 rows rest on the round's own
gate runs and on the planner's independent re-runs — every gate exits 0, the
declared suite is 424/0 — **not** on a tester report. Producing that report is
this round's whole purpose.

1. Re-run every gate script named in `## Plan Metadata`, and report each exit
   code separately. Step 6's gate has three companions round 3 wrote —
   `…-step6-drain-probe.py`, `…-step6-retention.py`,
   `…-step6-import-redproof.py` — run those too.
2. Run the declared full suite in the **foreground**.
3. **Write your session report before you end your turn.** Round reliability is
   this repo's weak point — the preceding plan's eight tester rounds all produced
   code and none produced a report — so a round that writes nothing is treated as
   failed even when its edits landed. Round 3 is the third round of this plan to
   demonstrate it.

### Round log

- **Round 1 (2026-10-16), Steps 1–4** — `overall_result: SUCCESS`, report at
  `tmp/reports/2026-10-15-test-harness-robustness-tester-2026-10-16.json`. Found
  and fixed a real defect in Step 2's spec before it reached the tree (see the
  Issue Log); suite 424/424; the `No proxy_stop event in trace` warning retired.
- **Round 2 (2026-10-16), Step 5** — `overall_result: SUCCESS`, report at
  `tmp/reports/2026-10-15-test-harness-robustness-tester-2026-10-16-2.json`.
  Suite 424/424, every earlier gate re-run green; found a real defect in the
  planner's Step 5 calibration, repaired post-round (see History and Final
  Results).
- **Phase 6 review (2026-10-16)** — report at
  `tmp/reports/2026-10-15-test-harness-robustness-review-2026-10-16.json`.
  Verdict "Issues found — non-blocking": 5 findings, 1 Low and 4 Suggestions,
  no Critical and no High. It independently re-ran the full suite (424/0) and
  all 12 gate checks, refuted three of its own five hunches by measurement, and
  confirmed the plan's evidence lines. Four findings became Step 6; the fifth
  (a doc over-claim) the planner fixed directly.
- **Round 3 (2026-10-16), Step 6** — **no session report; killed by its
  launcher's wrapper at 15:39 while it was still working.** All of Step 6 landed
  and every gate it wrote exits 0 (the planner re-ran each — see History), but
  the round died before writing
  `tmp/reports/2026-10-15-test-harness-robustness-tester-2026-10-16-3.json`, so
  nothing attests the work except the round's own progress log
  (`tmp/logs/…-tester-2026-10-16-3.log`) and the planner's re-runs. It also
  found a real gap in Step 6b's spec **by measurement** — see the Issue Log — and
  fixed it beyond what the step said. This round exists to close that gap in the
  record.

### Already landed in rounds 1–3 (do not redo)

Steps 1–6 are **done and gate-green**. They are kept below for the record only.

1. ~~**REPLACE** `_admin_post` …~~ — landed; `_admin_post` now returns
   `(0, str(e))` on a transport abort.
2. ~~**ADD** the drain registries and `_drain_child_stderr` …~~ — landed, plus
   the call-site adaptation the plan had missed (11 `communicate()` stderr reads
   across `test_cli.py` and `test_config_keys.py` now go through
   `_read_child_stderr`).
3. ~~**REPLACE** the 8 hand-rolled state-file removals …~~ — landed, and
   `test_trace_markers` now stops the proxy via `POST /admin/shutdown`.
4. ~~**REWRITE** the `_READY_MARKER` comment …~~ — landed.
5. ~~**DELETE** `_start_proxy_with_flag`, **REPLACE** `_assert_startup_aborted`
   …~~ — landed.
6. ~~**BIND** the drain registries to the child (`weakref`), **INSERT**
   `_drain_child_stderr(proc)` at the 21 remaining long-lived spawn sites,
   **RETAIN** rather than pop the drained buffer …~~ — landed by round 3, *plus*
   the read-site reroute Step 6b's text was missing: `tests/_harness.py` and both
   test files are already edited, both test files import `_drain_child_stderr`
   and `_read_child_stderr`, `tests/test_retry_streaming.py` has 17 drain calls
   and `tests/test_trace.py` 4, the two direct `proc.stderr.read()` diagnostics
   in `test_retry_streaming.py` now read through `_read_child_stderr(proc,
   timeout=5)`, and the gate plus its calibration and three companions all exit
   0. See the Issue Log for the gap and the History row for the diagnosis.

## Issue Log

| Issue | Status | Found | Resolved | Resolved By |
|-------|--------|-------|----------|-------------|
| [orphaned-test-state-files](./tmp/reports/defer-issue-orphaned-test-state-files.json) | Open (deferred) | 2026-10-16 | — | deferred — filed at the user's direction from round 4's third out-of-scope observation, rather than fixed here. The finding is that `~/.claude/proxy/` held **36** per-run `claude-retry-proxy-test-state-<pid>.json` files, oldest 2026-10-13, and that **this plan's own verification scripts are a systematic source**: they spawn a proxy child directly, so they never pass through `run_cli`'s per-test removal loop and each invocation can leave one behind. Nothing is broken — the PID-keyed per-run name is what removed the old machine-global false-"Proxy already running" hazard, CLAUDE.md already records the files as inert and hand-deletable, and the child's own state write is correct. So this is accumulation hygiene, not a defect in the state-file design, and the deferral's `suggested_fix` prefers pointing `PROXY_STATE_FILE` at each script's own temp directory over adding a cleanup step. It is deliberately **not** folded into this plan: the plan's write scope is `tests/` plus one doc, and the sources are under `tmp/verification/`. Note for the cycle's last plan: this raises the deferral corpus to 30 files |
| step6b-drain-steals-direct-stderr-reads | Resolved | 2026-10-16 | 2026-10-16 | tester — found by **measurement**, by round 3, and it is a gap in *this plan's* Step 6b spec rather than in the round's work. Step 6b said to insert the drain call and "insert nothing else and move no existing line", which is exactly what the round did; the full suite it then ran at 15:20–15:29 came back **423 passed, 1 failed** — `client-disconnect-no-traceback`, on `FAIL: stderr does NOT contain '[proxy] client disconnected mid-response'`. The mechanism is not a race and not load: once a reader thread owns the child's stderr pipe, `proc.stderr.read()` returns `""`, so the assertion that reads stderr directly is handed an empty diagnostic. The log confirms the mechanism by *signature* rather than by inference — in that same run `streaming-mid-stream-upstream-failure` PASSED all four of its stderr checks while reading the same stolen pipe, because every one of its assertions is **negative** ("no `Traceback`", "no `client_disconnect` event"): an empty read satisfies them vacuously. The four assertions are durable evidence — they are in `tests/test_retry_streaming.py` and can be re-read at any time — but **the suite log that showed them passing on the stolen pipe is not**: `tmp/verification/2026-10-15-test-harness-robustness-full-suite.log` was overwritten by round 4's own 424/0 run at 16:23, so the citation is deliberately to the source and to round 3's progress log rather than to a log path that no longer holds the run it describes. That is the same trap as the sentence below, one level down: **a verification artifact is only evidence while it still holds the run it names.** `client-disconnect-no-traceback` is the suite's only **positive** stderr-content assertion, which is why it was the only casualty — and why this defect could otherwise have shipped as a silent loss of coverage in four assertions. Round 3 diagnosed it and rerouted both direct reads in `test_retry_streaming.py` to `_read_child_stderr(proc, timeout=5)` at 15:31, then re-ran the two stderr-reading tests green; the planner's independent full-suite run is 424/0 and the declared test passes 12/12 standalone. The planner's first reading of that stale 423/1 log — as an unexplained load-sensitive flake — was wrong, and the correction came from round 3's own progress log (`tmp/logs/…-tester-2026-10-16-3.log`, lines 81-85 against line 69: the reroute landed *after* the suite run, not before it) |
| harness-dead-spawn-helper (observation 1 of the [2026-10-16 tester report](./tmp/reports/2026-10-15-test-harness-robustness-tester-2026-10-16.json)) | Resolved | 2026-10-16 | 2026-10-16 | tester — Step 5a landed. `_start_proxy_with_flag` is deleted from `tests/_harness.py`; the Step 5 gate finds no definition and no reference in any `tests/*.py`, `_create_test_config_with_flag` and the three other survivors are intact, and the leftover blank run is back to the file's standard two lines. Step 2's gate was narrowed to match (`LONG_LIVED = ("_start_proxy_server_directly",)`) — a contract change, and Step 5's gate re-runs that gate as a subprocess so the narrowing cannot hide a regression; the gate's own docstring and PASS line were corrected so they no longer name the retired helper. Suite unchanged at 424/424, so the deletion cost zero coverage. A repo-wide scan confirms its only references were its own definition and this plan's Step 2 gate: no test reached it, and this plan nonetheless *modified* it to satisfy that gate — the gate driving the code rather than the code driving the gate. It is also stale independently of being dead (its own inline 10 s TCP probe predates the READY-marker readiness rework, and it drops the `cwd` the live helper passes). Its deadness was first recorded in [plans/2026-08-25-fix-windows-readiness-probe.md](./plans/2026-08-25-fix-windows-readiness-probe.md) §"Phase 2" item 4, which told that plan's coder "Do NOT update it" — so this closes a two-month-old known condition |
| startup-abort-stdout-assertion-vacuous (observation 2 of the [2026-10-16 tester report](./tmp/reports/2026-10-15-test-harness-robustness-tester-2026-10-16.json)) | Resolved | 2026-10-16 | 2026-10-16 | tester — Step 5b landed. `_assert_startup_aborted` is now `(proc, probe_ok, blocked, label)` and asserts `if not probe_ok:` in place of the unfailable `"READY" not in stdout` check; both call sites bind `probe` instead of the discarded `_probe` and pass it; `_drain_after_exit`'s now-false docstring clause was corrected (the gate checks the claim is gone **and** that `stdout` survives, so deleting the sentence instead of fixing it fails). Both abort tests still PASSED, green for the right reason — `server never signalled readiness` **and** the stderr diagnostic naming the blocked path. The replacement was proven reachable rather than assumed: the calibration shows a healthy child on a **writable** path reports `probe_ok=True`, and `step5-probe-redproof.py` shows a scratch mirror handing both call sites `True` turns both abort tests red on the readiness branch while the unmodified mirror passes. This removes the same false-pass class Step 3b eliminated one file over |
| [harness-ready-marker-comment-windows](./tmp/reports/defer-issue-harness-ready-marker-comment-windows.json) | Resolved | 2026-10-15 | 2026-10-16 | tester — this deferral's whole stated reason was "scoped into 2026-10-15-test-harness-robustness (Step 4), which already owns `tests/_harness.py`", so Step 4 landing closes it. The comment now reads "registered its signal handlers — SIGTERM on every platform, SIGINT additionally on POSIX" and the rationale sentence (READY post-dates `signal.signal()`, so a signalled proxy runs the graceful-shutdown handler) survives intact. Step 4's gate, re-run against the landed comment, exits 0 |
| [step2-drain-breaks-existing-communicate-stderr-reads](./tmp/reports/2026-10-15-test-harness-robustness-step2-drain-breaks-existing-communicate-stderr-reads.json) | Resolved | 2026-10-16 | 2026-10-16 | tester — found by **measurement before the code reached the tree**, so the broken shape never landed. Step 2's drain thread owns the child's stderr pipe, but `_start_proxy_server_directly`'s own callers read it via plain `proc.communicate()`, which returns `""` once a reader has drained it: 3 sites in `test_cli.py` and 8 in `test_config_keys.py`, i.e. 11 assertions that would have gone red with empty diagnostics — precisely the risk this plan's own Risk table named. All 11 were routed through `_read_child_stderr(proc, timeout=...)`. Direct behavioural proof: those tests assert specific diagnostic substrings (`has no entry in keys-index.json`, `passphrase`, `is not writable`), so their passing means the drain buffer delivered real child text. Also fixed the now-false `_await_child_ready_marker` docstring sentence |
| [no-proxy-stop-trace-warning](./tmp/reports/defer-issue-no-proxy-stop-trace-warning.json) | Resolved | 2026-09-14 | 2026-10-16 | tester — Step 3b switched `test_trace_markers` to a graceful `POST /admin/shutdown` and elevated a missing `proxy_stop` from `warn()` to `fail()`. The `No proxy_stop event in trace` warning is **gone from the full-suite summary** (424/0, 0 warnings), and the marker is now pinned rather than tolerated |
| [cli-pre-existing-remove-idiom-copies](./tmp/reports/defer-issue-cli-pre-existing-remove-idiom-copies.json) | Resolved | 2026-10-04 | 2026-10-16 | tester — all 8 hand-rolled `os.remove(PROXY_STATE_FILE)` blocks in `test_cli.py` (lines 87, 188, 205, 600, 696, 1161, 1216, 1343) now call the shared `_remove_test_state_file()`, each rationale comment preserved; `_remove_test_state_file`'s own docstring gained `test_cli.py` among its call sites, which its own Step 3 gate required |
| [suite-load-admin-connection-abort](./tmp/reports/defer-issue-suite-load-admin-connection-abort.json) | Resolved | 2026-10-13 | 2026-10-16 | tester — Step 1 wrapped `_admin_post`'s request/getresponse/read in the same `try/except` its sibling `_send_proxy_request` uses, returning `(0, str(e))` (a `str`, not the sibling's `bytes`, to match `_admin_post`'s own decoded-`str` contract). A transport abort now surfaces as a **failed assertion carrying the error text** instead of `Test crashed` with no diagnostic; a fault-injection check confirms it returns rather than raises. This makes the flake diagnosable — it does not make it pass, and the plan says so |

## Guidance for Coder

**Files to modify:** none.

This plan changes only files under `tests/`. Do not touch them. If the coder
round is launched against this plan, it should record that it has no work and
exit; the work belongs to the tester.

## Guidance for Tester

**Files to modify:** `tests/_harness.py`, `tests/test_cli.py`, `tests/test_trace.py`,
`tests/test_retry_streaming.py` (and, for its call-site adaptation,
`tests/test_config_keys.py` — see the Issue Log)

Six hardening steps, each with its own gate script, run as its step finished
rather than batched at the end. **Steps 1–5 have landed** (rounds 1–2); Step 6
is the outstanding work.

### Step 1: give `_admin_post` the transport tolerance its sibling already has

`tests/_harness.py:670` `_admin_post` runs `conn.request(...)`,
`conn.getresponse()`, `resp.read()` with no guard. In full-suite run 1 of
2026-10-13 this crashed a test: `ConnectionAbortedError [WinError 10053]`
propagated out of `getresponse()` on
`tests/test_admin.py::test_admin_api_reload`'s last step, escaping the test body
to the harness wrapper and surfacing as `FAIL: Test crashed` — with all ten
preceding assertions passing.

Its sibling `_send_proxy_request` (`tests/_harness.py:641-665`) already wraps the
same sequence in `try/except Exception` and returns `(0, str(e))`. Mirror that:
catch around the request/getresponse/read sequence and return
`(0, str(e))`, so a transient abort surfaces as a **failed assertion carrying
the error text** instead of an unhandled crash.

This converts a crash into a *diagnosable* failure — it does not make the flake
green, and must not be written as if it did.

**Copy this replacement** for the whole `_admin_post` function
(`tests/_harness.py:670-689`). Note the returned error is a **`str`**, not the
`bytes` its sibling returns — `_admin_post`'s own contract is `(status, data)`
with `data` a decoded `str`, and a `bytes` error there would break every
caller's `in`/`format` use of it.

```python
def _admin_post(proxy_port, path, body, origin=None, timeout=10):
    """POST to admin API with CSRF Origin header. Returns (status, data).

    `timeout` bounds the whole exchange. A switch/reload drain is unbounded by
    design (it waits for in-flight work to finish), so a test whose switch
    legitimately waits out a live stream must raise this past the 10 s default
    — otherwise the client gives up while the server-side swap still succeeds.

    Transport failures are tolerated the way `_send_proxy_request` tolerates
    them: the caller receives (0, "<error text>") and fails an assertion that
    carries the reason, rather than an exception escaping the test body and
    surfacing as "Test crashed" with no diagnostic. This makes the flake
    diagnosable; it does not make it pass.
    """
    import http.client as _hc
    conn = _hc.HTTPConnection("127.0.0.1", proxy_port, timeout=timeout)
    headers = {"Content-Type": "application/json"}
    if origin is not None:
        headers["Origin"] = origin
    else:
        headers["Origin"] = "http://127.0.0.1:{}".format(proxy_port)
    try:
        conn.request("POST", path, body=json.dumps(body), headers=headers)
        resp = conn.getresponse()
        data = resp.read().decode()
        status = resp.status
        conn.close()
        return status, data
    except Exception as e:
        conn.close()
        return 0, str(e)
```

→ tester verify: `python ./tmp/verification/2026-10-15-test-harness-robustness-step1.py`
  exits 0; and a deliberate fault-injection check — temporarily point
  `_admin_post` at a closed port and confirm it returns `(0, "<error text>")`
  rather than raising (revert the injection afterwards)

### Step 2: drain long-lived children's stderr for the child's whole life

Both long-lived spawn helpers — `_start_proxy_server_directly`
(`tests/_harness.py:549`) and `_start_proxy_with_flag` (`tests/_harness.py:1016`)
— spawn the proxy with `stderr=subprocess.PIPE`, and nothing reads that pipe
until the test ends. A chatty child under whole-suite load can fill the ~64 KiB
pipe buffer and block. The issue records this as an **unmeasured candidate
mechanism** for the sibling admin flakes, not a confirmed cause — so this step
removes the mechanism rather than claiming it as the diagnosis.

**Copy these three pieces.** `threading` is already imported at
`tests/_harness.py:23`. Place the registry and helper immediately above
`_read_child_stderr` (`:523`).

Piece 1 — the registry and the helper, at module level:

```python
# Children whose stderr is drained by a background reader: proc id -> captured
# text, and proc id -> the reader thread. _read_child_stderr consults these
# when the pipe is no longer the source of truth.
_CHILD_STDERR_BUFFERS = {}
_CHILD_STDERR_READERS = {}


def _drain_child_stderr(proc):
    """Continuously drain a long-lived child's stderr into a buffer.

    The child is spawned with stderr=subprocess.PIPE and outlives the test
    body, so nothing reads that pipe until teardown: a chatty child under
    whole-suite load can fill the buffer and block. A daemon reader thread
    removes the mechanism. The captured text is appended to the module-level
    buffer that _read_child_stderr consults when the pipe is no longer the
    source of truth.
    """
    chunks = []
    _CHILD_STDERR_BUFFERS[id(proc)] = chunks

    def reader():
        try:
            # text=True at both call sites, so readline yields str and "" at EOF.
            for line in iter(proc.stderr.readline, ""):
                chunks.append(line)
        except (OSError, ValueError):
            # The pipe closed under us — teardown killed the child, or the
            # handle was closed. Whatever was read is still the diagnostic.
            pass

    thread = threading.Thread(target=reader, name="stderr-drain", daemon=True)
    thread.start()
    _CHILD_STDERR_READERS[id(proc)] = thread
    return thread
```

Piece 2 — replace `_read_child_stderr` (`:523-546`) with this. The drain path
must **not** call `communicate()`: the reader already owns that pipe, and racing
it for the same file object is the bug this shape avoids.

```python
def _read_child_stderr(proc, timeout=2):
    """Return a child's stderr text, bounded and never blocking.

    For a child spawned by a drain-owning helper the background reader holds
    the pipe, so this waits the child out and returns the captured buffer —
    calling communicate() here would race that reader for the same pipe. For
    every other child it keeps the original path: kill first (this is the
    readiness-failure path, where the child is discarded anyway), then read
    whatever it emitted. A TimeoutExpired or any other error yields "" rather
    than propagating — the diagnostic must never be the thing that fails the
    test.
    """
    key = id(proc)
    if key in _CHILD_STDERR_BUFFERS:
        chunks = _CHILD_STDERR_BUFFERS.pop(key)
        reader = _CHILD_STDERR_READERS.pop(key, None)
        try:
            if proc.poll() is None:
                proc.kill()
        except OSError:
            pass
        if reader is not None:
            reader.join(timeout=timeout)
        return "".join(chunks)
    try:
        if proc.poll() is None:
            proc.kill()
    except OSError:
        pass
    try:
        _, stderr = proc.communicate(timeout=timeout)
        return stderr or ""
    except subprocess.TimeoutExpired:
        try:
            proc.kill()
        except OSError:
            pass
        return ""
    except (OSError, ValueError):
        return ""
```

Piece 3 — one line immediately after **each** long-lived `Popen`, in
`_start_proxy_server_directly` (`:585`, the call whose args span several lines)
and `_start_proxy_with_flag` (`:1042`):

```python
    _drain_child_stderr(proc)
```

Do **not** add it at `:242` or `:262` — those two children are short-lived and
are `communicate()`d on the next line, so a reader there would race it.

→ tester verify: `python ./tmp/verification/2026-10-15-test-harness-robustness-step2.py`
  exits 0; and a leak-of-behaviour check — spawn a proxy through
  `_start_proxy_server_directly`, kill it, and confirm `_read_child_stderr` still
  returns the child's real stderr text (the diagnostic must not regress to `""`)

### Step 3: single-source the state-file removal policy, and assert the stop marker

Two hygiene items in one step.

**(a) The 8 hand-rolled removals.** `tests/test_cli.py` still repeats

```python
try:
    os.remove(PROXY_STATE_FILE)
except OSError:
    pass
```

at lines 87, 188, 205, 390, 486, 951, 1006, 1133 — while `tests/_harness.py`
owns the shared, documented `_remove_test_state_file()` (`tests/_harness.py:99`)
and `test_cli.py` already imports from `_harness`. Replace all 8 sites with calls
to the helper, and note that `test_cli.py` already has one more reference,
bringing the total to 9.

Two details matter:
- **Keep the local rationale comments.** Line 1133's force-kill/"so the restore
  reliably puts back the pre-test backup" explanation, and the "Ensure cmd_start
  doesn't refuse with 'Proxy already running'" comments, document *why* that
  specific test needs the clear. A bare helper call would lose them.
  <!-- CORRECTED 2026-10-16: this said "the 7 … comments". Measured against the
  tree, exactly THREE sites carry that comment (tests/test_cli.py:86, :198,
  :590); the rest carry none, or a different rationale. The instruction itself
  was honoured in full — every comment that existed was preserved — and the
  published doc never repeated the wrong count (doc/test-catalog.html:80-82
  describes the split functionally). The number was the planner's, and the
  round-4 tester report caught it: this row's own History entry records it.
  -->
- **Widen `_remove_test_state_file`'s docstring.** It currently enumerates only
  the harness-side sites ("harness import, the three wrapper cleanup() closures,
  and run_cli's per-test loop"), so a reader would conclude the policy is
  centralized when it is not. Add `test_cli.py`'s test bodies to that list.

**(b) The trace test's stop marker.** `tests/test_trace.py`'s lifecycle test
kills the proxy with `proc.terminate()` (line 135) and then, at line 174,
downgrades the missing marker to `warn("No proxy_stop event in trace (may be
expected if termination was abrupt)")`. On Windows `terminate()` is
`TerminateProcess`, so the graceful path never runs and the warning is
*guaranteed* — the test cannot fail, so it cannot catch a regression in
`write_stop_marker`.

Change the test to stop the proxy through the graceful path it conceptually
targets — `POST /admin/shutdown` with the CSRF `Origin` header (use
`_admin_post`) — and elevate the missing marker back to a hard `fail(...)`.
Assert the `proxy_stop` event and its `requests_total` counter.

Note the coupling: this test then depends on the graceful path, and Plan
`2026-10-15-posix-shutdown-and-stop-reporting` fixes a POSIX deadlock in the
SIGTERM handler. This test does **not** depend on that plan landing — it uses the
admin path, which is already correct on every platform — but do not "simplify" it
back to `terminate()` afterwards.

→ tester verify: `python ./tmp/verification/2026-10-15-test-harness-robustness-step3.py`
  exits 0; the full suite runs green with the `No proxy_stop event in trace`
  warning **gone** from the summary (the baseline on 2026-10-15 was
  `418 passed, 0 failed, 418 total` with exactly that 1 warning), and the new
  hard assertion is proven load-bearing by temporarily removing the
  `write_stop_marker()` call in a scratch edit and confirming the suite goes red

<!-- UPDATED: added 2026-10-15 from the third-pass review of
     2026-10-15-posix-shutdown-and-stop-reporting
     (review-harness-both-signal-handlers-windows). The comment is false on
     Windows and this plan already owns tests/_harness.py, so the fix costs no
     extra round here. -->

### Step 4: make the `_READY_MARKER` comment true on Windows

`tests/_harness.py`'s `_READY_MARKER` comment (around line 476) now ends
"…registered **both** signal handlers". That is false on Windows: `server.py`
registers the SIGTERM handler unconditionally but gates the SIGINT one behind
`if sys.platform != "win32"` (`server.py:3977`), because on Windows Ctrl+C
arrives as `KeyboardInterrupt` and is handled by `main()`'s `try/except`. So on
the Windows dev box this suite mostly runs on, exactly **one** handler is
registered at the point READY is printed.

Fix the wording, not the code: say the handlers — SIGTERM on every platform,
SIGINT additionally on POSIX — are registered before READY. The load-bearing
claim (READY post-dates handler registration, so a consumer acting on it can
safely deliver SIGTERM) stays exactly as it is; only the count is wrong.

This is a comment-accuracy fix on a line Plan A deliberately introduced. Do not
restructure the comment or move READY.

→ tester verify: `python ./tmp/verification/2026-10-15-test-harness-robustness-step4.py`
  exits 0; the comment must not claim two handlers unconditionally, and the
  SIGTERM coverage claim must survive (the gate asserts both directions — that
  the over-claim is gone **and** that the still-true part was not deleted
  wholesale)

**Tests to investigate for retirement:**
- The `warn(...)` branch itself is retired by Step 3(b) — it is replaced by a
  `fail(...)`, not kept alongside it.
- `tests/test_cli.py`'s existing `stop_result` guards (around lines 144 and 238)
  — check whether any asserts the state-file lifetime; if one does, it may be
  superseded by Plan `2026-10-15-posix-shutdown-and-stop-reporting`'s new
  failure-path test. Coordinate: that plan owns the `cmd_stop` contract test.
- Tester may identify additional candidates during test work.

**Retirement procedure:** For each candidate, verify the test exercises code
being removed/changed. If obsolete: delete and note in session report. If still
valid: document why in session report.

<!-- UPDATED: Step 4 added 2026-10-15 from the third-pass review of
     2026-10-15-posix-shutdown-and-stop-reporting. The count below went three
     -> four; Step 4 is the one item here that is a comment-accuracy fix rather
     than a harness behaviour fix. -->

### Step 5: retire the dead spawn helper, and stop asserting on an always-empty stdout

Both items are the 2026-10-16 round's own `out_of_scope_observations`
([tester report](./tmp/reports/2026-10-15-test-harness-robustness-tester-2026-10-16.json)).
Both sit in files this plan already declares, and both are its subject matter, so
they are folded here rather than deferred — that report's third observation (the
Step 4 calibration's one-shot measurement) the round fixed itself and needs
nothing further.

#### 5a — delete `_start_proxy_with_flag` (`tests/_harness.py`)

The helper is dead. A repo-wide scan finds exactly two references to the name:
its own definition, and this plan's Step 2 gate, which enumerated it as a
long-lived spawn helper. Step 2 therefore added a `_drain_child_stderr(proc)`
call to it **to satisfy a gate** — a change to code nothing calls, which is the
gate driving the code rather than the code driving the gate. It is independently
stale: it rolls its own 10 s TCP readiness probe instead of the READY-marker path
`_start_proxy_server_directly` uses, and it omits the `cwd` that helper passes to
`Popen`. Its deadness was already recorded on 2026-08-25 in
[plans/2026-08-25-fix-windows-readiness-probe.md](./plans/2026-08-25-fix-windows-readiness-probe.md)
("Do NOT update it"), so this is a known condition finally being closed, not a
new discovery.

`_create_test_config_with_flag` — the reusable half, used by four modules — stays.

**The edit is a line-range deletion.** Delete **`tests/_harness.py` lines
1082–1132 inclusive**. That range is exactly:

- 1082–1083 — two of the four blank lines that follow
  `_create_test_config_with_flag`'s `    return path` (line 1079)
- 1084–1128 — `def _start_proxy_with_flag(...)` through its closing
  `    return proc, probe_ok`
- 1129–1132 — the four blank lines that follow it

Stopping at 1132 rather than 1128 is what leaves **exactly two** blank lines
between `    return path` and the `# ===…` banner that follows — the spacing
every other top-level definition in the file uses. The resulting shape is:

```python
    return path


# ===========================================================================
# Mode dispatch tests (plan 2026-08-27-support-three-endpoint-modes)
```

Do **not** delete `_create_test_config_with_flag` (through line 1079) or
`_require_server_func`; the gate checks both survived.

**Then update Step 2's gate.** `./tmp/verification/2026-10-15-test-harness-robustness-step2.py`
enumerates both long-lived spawn helpers in its `LONG_LIVED` tuple, so retiring
one turns that gate red. Change line 21 to

```python
LONG_LIVED = ("_start_proxy_server_directly",)
```

This is a contract change, not a bypass: the gate still requires the surviving
helper to call `_drain_child_stderr`, and Step 5's own gate re-runs the Step 2
gate as a subprocess and refuses to pass while it is red.

#### 5b — make the startup-abort assertion able to fail (`tests/test_cli.py`)

`_assert_startup_aborted` (line 1410) asserts `"READY" not in (stdout or "")`.
It cannot fail. Its `stdout` comes from `_drain_after_exit`'s
`proc.communicate()`, and the child's stdout has already been read to EOF by the
`_await_child_ready_marker` daemon thread `_start_proxy_server_directly` starts at
spawn — so `communicate()` returns `""` and the branch takes `pass_`
unconditionally. Verified by reading both helpers, not inferred.

The readiness signal that *is* computed is the `probe_ok` the spawn helper
returns; both call sites bind it today as `_probe` and discard it. Thread it in.

**Edit 1 — replace `_assert_startup_aborted` (`tests/test_cli.py:1410-1425`)**
with exactly:

```python
def _assert_startup_aborted(proc, probe_ok, blocked, label):
    """Assert a direct server invocation exited before READY, naming `blocked`.

    Readiness is asserted from `probe_ok`, the signal
    _start_proxy_server_directly actually computes -- not from the child's
    stdout, which that helper's _await_child_ready_marker daemon thread has
    already read to EOF, so the communicate() in _drain_after_exit returns ""
    and a READY-marker check against stdout could never fail.
    """
    _, stderr = _drain_after_exit(proc)
    if proc.returncode not in (0, None):
        pass_("{}: server exited non-zero ({})".format(label, proc.returncode))
    else:
        fail("{}: expected non-zero exit, got {}".format(label, proc.returncode))
    if not probe_ok:
        pass_("{}: server never signalled readiness".format(label))
    else:
        fail("{}: server signalled readiness despite the unwritable path".format(label))
    if "is not writable" in (stderr or "") and blocked in (stderr or ""):
        pass_("{}: stderr ERROR names the unwritable path".format(label))
    else:
        fail("{}: expected an ERROR naming {!r}, got: {!r}".format(
            label, blocked, (stderr or "")[-400:]))
```

**Edit 2 — `_drain_after_exit`'s docstring** (same file, line 1396). Its last
sentence — "stdout still comes from communicate(), which is what the callers
assert on" — becomes false. The edit is a **clause swap**: replace the clause

```
which is what the callers assert on
```

with

```
whose closing of the child's stdout pipe is still needed; no caller asserts
on stdout any more -- the readiness signal they need is the spawn's probe_ok
```

so the sentence reads "stdout still comes from communicate(), whose closing of
the child's stdout pipe is still needed; no caller asserts on stdout any more —
the readiness signal they need is the spawn's probe_ok."

`_drain_after_exit` itself is otherwise **unchanged**: its `communicate()` call is
what reaps the child and closes its stdout pipe, so it stays even though its
stdout element is now discarded. The gate checks the docstring's claim is gone
**and** that the word `stdout` survives in it, so deleting the sentence instead of
correcting it fails.

**Edit 3 — the two call sites.** At `:1455` and `:1494`, change
`proc, _probe = _start_proxy_server_directly(` to
`proc, probe = _start_proxy_server_directly(`; at `:1459` and `:1498`, pass it:

```python
        _assert_startup_aborted(proc, probe, blocked, "unwritable trace path")
```

```python
        _assert_startup_aborted(proc, probe, blocked, "unwritable state path")
```

→ tester verify: `python ./tmp/verification/2026-10-15-test-harness-robustness-step5.py`
  exits 0. Every check but the blank-line one is AST-based — comments do not exist
  in an AST — so no wording shortcut satisfies it.

→ tester verify **calibration**:
  `python ./tmp/verification/2026-10-15-test-harness-robustness-step5-calibration.py`
  exits 0. It drives the gate against synthetic trees built from **pinned
  literals**, not from the live file, so it stays meaningful after the fix lands
  (the one-shot defect the round had to repair in the Step 4 calibration). Nine
  variant directions: the prescribed fix and a **re-wrapped** version of it must
  come back GREEN, and the pre-fix tree plus **six** half-fixes must each come
  back RED *for the stated reason* — stdout check kept, blank run left at four,
  `_create_test_config_with_flag` taken with it, no `fail()` anywhere, `_probe`
  passed instead of `probe`, and the stale `_drain_after_exit` sentence left in
  place. The re-wrapped direction is deliberate: Step 5b's deliverable is the
  claim, not its line breaks, so the gate must accept the same correction
  wrapped differently.

→ tester verify **live-text independence**: the same script's independence
  section re-wraps the live `_drain_after_exit` docstring a third way and requires
  every verdict above to be unchanged, with a **negative control** that
  reproduces the old `.replace()`-based construction's false GREEN on that tree.
  Both `_drain_after_exit` states are pinned literals spliced by AST span, so a
  cosmetic re-wrap cannot reach a variant.

→ tester verify **the new assertion is not vacuous in the other direction**: the
  same calibration's last check spawns a real child on a **writable** path and
  requires `probe_ok is True`. Without it, a `probe_ok` that is always False would
  make the replacement assertion exactly as unfailable as the one it replaces.
  `./tmp/verification/2026-10-15-test-harness-robustness-step5-probe-redproof.py`
  measures the same property against the **committed** tests: a scratch mirror
  handing both call sites `True` must turn both abort tests red on the readiness
  branch, while the unmodified mirror passes.

**Expect no change to the suite counts**: 424 passed, 0 failed, nothing added or
removed — this step rewrites harness code and one assertion; it adds no coverage.
`test_startup_aborts_on_unwritable_trace_path` and
`test_startup_aborts_on_unwritable_state_path` must both still PASSED, and green
for the right reason: `probe_ok` False **and** the stderr diagnostic naming the
blocked path. A scratch mirror whose `_assert_startup_aborted` is handed
`probe_ok=True` must FAIL on the readiness check; do that in a mirror, never by
editing the committed test.

<!-- UPDATED: Step 6 added 2026-10-16 from the Phase 6 review
     (tmp/reports/2026-10-15-test-harness-robustness-review-2026-10-16.json),
     which ran after Steps 1-5 landed. Verdict: "Issues found - non-blocking",
     5 findings, no Critical and no High. Four are addressed here; the fifth
     (a doc over-claim about which test bodies clear the state file first) is
     planner-owned and was fixed directly in doc/test-catalog.html. -->

### Step 6: bind the drain to the child, and drain the 21 children Step 2 missed

Source: the Phase 6 review of this plan,
[tmp/reports/2026-10-15-test-harness-robustness-review-2026-10-16.json](./tmp/reports/2026-10-15-test-harness-robustness-review-2026-10-16.json).
Every claim below was **measured** by that review, not inferred; where a
measurement refuted its own hunch, the finding says so.

**The one that matters** is 6b: the review counted the sites that spawn a
long-lived proxy child with `stderr=subprocess.PIPE` and never read it, and
found **22** — of which Step 2 drains **one**. `tests/test_retry_streaming.py`
has 17 (lines 96, 241, 376, 516, 641, 802, 924, 1064, 1208, 1438, 1588, 1791,
1890, 1992, 2187, 2294, 2403) and `tests/test_trace.py` has 4 (lines 90, 280,
437, 739); neither file contains a single `communicate()`, and every one of
those children runs for a whole test body — a retry loop, a 429 exhaustion, a
concurrent-request burst. So the pipe-full mechanism Step 2 exists to remove
**survives in 21 places**, and the doc row this plan added reads as though it
does not.

#### 6a — Finding 1: the registry is keyed by `id(proc)`

`_CHILD_STDERR_BUFFERS` / `_CHILD_STDERR_READERS` are address-keyed, and nothing
releases an entry on a child's **success** path: only `_read_child_stderr` pops,
and its callers are the failure paths. Measured over 8 success-path spawns
through `_start_proxy_server_directly`: 3 entries left behind, **0** of which
still matched a live `Popen` — the reader thread clears `_target` when it exits,
so the registry does not pin the child, and the int key becomes a stale address.
`Popen` id reuse in that process is the norm (17/19 and 19/19 back-to-back;
57/60 in a 60-spawn control). The review could not produce a wrong-buffer read
(a 300-spawn probe never landed a new `Popen` on a stale key, and every
committed caller passes a re-registered child, whose registration overwrites the
key) — so this is filed as retention, **not** as a demonstrated wrong read. It
is still worth fixing before 6b adds 21 more registrations, and the branch is
selected by id-membership rather than by "is drain-owned", which is what makes
the current code contradict its own docstring for a stale key.

**Edit 1 — the two registries** (`tests/_harness.py`, currently at 527-531).
Add `import weakref` to the module's imports, then replace the two module-level
dicts and their comment with:

```python
# Children whose stderr is drained by a background reader, keyed BY THE CHILD
# (not by id(proc) — CPython reuses id() values once an object is collected, so
# an address-keyed entry that outlives its child can be found again by a later,
# unrelated child). A WeakKeyDictionary releases the entry when the child goes,
# which is also what makes the retention here bounded.
_CHILD_STDERR_BUFFERS = weakref.WeakKeyDictionary()
_CHILD_STDERR_READERS = weakref.WeakKeyDictionary()
```

**Edit 2 — `_drain_child_stderr`**, the two registry stores:

```python
    chunks = []
    _CHILD_STDERR_BUFFERS[proc] = chunks
```
```python
    _CHILD_STDERR_READERS[proc] = thread
```

The word `id(` must not survive anywhere in the function.

#### 6b — Finding 5: drain the 21 remaining long-lived children

Mechanical, and the only judgement is where the line goes: **immediately after
the child's `subprocess.Popen(...)` statement, at the same indentation as that
statement's closing `)`** — which is 4 spaces at every site except
`test_retry_streaming.py:1588`, where it is 8:

```python
    _drain_child_stderr(proc)
```

Both files already import from `_harness` through a multi-line `from _harness
import (...)` block; add `_drain_child_stderr,` to each in alphabetical position.
The local variable is `proc` at all 21 sites — verified.

#### 6b-correction — **not** "insert nothing else" (added 2026-10-16)

**This step originally ended "Insert nothing else and move no existing line."
That was wrong, and the wrongness cost a suite run.** A drain reader takes
ownership of the child's stderr pipe, so any test that reads that pipe *directly*
is handed `""`: the reader has already consumed it. Two sites in
`tests/test_retry_streaming.py` did exactly that and had to be rerouted in the
same step:

```python
        # Collect stderr through the harness accessor: this child's stderr pipe
        # is owned by the drain reader _drain_child_stderr installed at spawn,
        # so a direct proc.stderr.read() here returns "" and the assertion below
        # would fail on an empty diagnostic rather than on a real one.
        stderr_output = _read_child_stderr(proc, timeout=5)
```

The second site (in `test_streaming_mid_stream_upstream_failure`, 4 spaces
deeper) carries the same three-line rationale and the same call. Both replace a
`try: stderr_output = proc.stderr.read() if proc.stderr else "" / except
Exception: stderr_output = ""` block, and both files must add `_read_child_stderr,`
to their `_harness` import in alphabetical position.

**The lesson, and the reason this is recorded rather than quietly patched:** the
failure this omission produced was *not* the loud one. `client-disconnect-no-traceback`
went red because it asserts stderr **content positively**. The four assertions in
`test_streaming_mid_stream_upstream_failure` are **negative** — "no `Traceback`",
"no `client_disconnect` event" — and an empty read satisfies a negative assertion
perfectly: they passed, **vacuously**, in the same run. A step that installs a
reader on a pipe must enumerate every existing reader of that pipe, because the
assertions that break silently are the ones that check for absence.

**Do not touch** `tests/test_cli.py`'s 3 spawns or `tests/_harness.py`'s: those
`communicate()` (5 calls and 4 calls respectively), so their pipes are read —
and they were already adapted to `_read_child_stderr` by Step 2 (see the Issue
Log), which is the same lesson one step earlier.

#### 6c — Findings 2 and 3: make the drain read idempotent, and say what it promises

Two contract gaps in `_read_child_stderr`, both measured unreachable today but
both real:

- **Single-shot.** The drain branch pops, so a second call for the same child
  falls through to `communicate()`, finds the pipe already drained, and returns
  `""` — silently, in 0.00 s, with no exception and no hang. (That measurement
  **refutes** the review's own hunch that a second call would race or block.)
  No committed caller reads a child twice, so the risk is that the accessor's
  answer depends on how many times it is called.
- **Best-effort.** When `reader.join(timeout)` expires the call returns whatever
  arrived so far; measured `""` at `timeout=0.001` on a live child that had
  written. Every committed call site reads after the child is dead, or waits it
  out first, so nothing depends on it today.

**Edit — `_read_child_stderr`'s drain branch.** With the registry now bounded by
the child's own lifetime (6a), retaining the chunks is safe and makes a repeat
read return the same text instead of `""`. Replace the branch with:

```python
    if proc in _CHILD_STDERR_BUFFERS:
        chunks = _CHILD_STDERR_BUFFERS[proc]
        reader = _CHILD_STDERR_READERS.get(proc)
        try:
            if proc.poll() is None:
                proc.kill()
        except OSError:
            pass
        if reader is not None:
            # join() is idempotent, so a repeat read returns immediately.
            reader.join(timeout=timeout)
        # The entry is released by the WeakKeyDictionary when the child goes,
        # not here: popping it would make a second read fall through to
        # communicate() and silently return "".
        return "".join(chunks)
```

and extend its docstring with both contracts:

```
    The read is repeatable: the buffer belongs to the child and is released when
    the child is collected, so calling this twice returns the same text rather
    than falling through to communicate() and returning "". It is best-effort
    only in one direction -- if the reader has not reached EOF within `timeout`
    (possible only for a child that survived the kill), the text captured so far
    is what comes back.
```

#### 6d — the doc row, after 6b makes its claim true

`doc/test-catalog.html`'s `_drain_child_stderr` row currently reads as a general
property of long-lived children while the reader was installed at one site. Once
6b lands the claim is true; the planner then re-reads the row and scopes it to
name the files and to say what is still **not** drained — a child's **stdout**,
which the review raised as a hunch and could not turn into a finding (the server
writes exactly one stdout line today, so there is no blocking scenario yet).

→ tester verify: `python ./tmp/verification/2026-10-15-test-harness-robustness-step6.py`
  exits 0. AST-based throughout: registry construction, key expression, the
  absence of `id(` in the drain helper, repeat-read retention, the per-file
  drain-call counts (17 and 4), and both import lists.

→ tester verify **calibration**:
  `python ./tmp/verification/2026-10-15-test-harness-robustness-step6-calibration.py`
  exits 0 — GREEN for the prescribed fix (including a re-wrapped docstring), RED
  for the pre-fix tree and for each half-fix *for the stated reason*: weakrefs
  declared but the helper still keyed by `id(proc)`; the drain added to only one
  of the two files; the chunks still popped; the import line missing.

→ tester verify **the 21 insertions are real, not just counted**: re-run the
  full suite (424/0 expected, no test added or removed) and confirm the drain
  readers actually start — a probe that spawns one of the newly drained children
  and shows its stderr arriving in the buffer, since a call placed after the
  child is already dead would satisfy the gate and drain nothing.

**Expect no change to the suite counts**: this step rewrites harness internals
and adds 21 call sites; it adds no test.

## Summary

Six defects in the test harness itself. None affects production behaviour;
all six affect whether the suite can *tell you* something is wrong — which is
what makes them worth fixing together. (Step 4 is the narrowest: a comment that
asserts something false on Windows, the platform this suite mostly runs on.
Step 5 is next: dead code the plan's own gate forced a change into, and an
assertion that could never fail. Step 6 arrived last, from the Phase 6 review,
and is the largest in scope: the drain Step 2 added reaches one of the 22
children that need it.)

**1. `_admin_post` crashes instead of failing.** The admin path's request/read
sequence is unguarded, so a transient `ConnectionAbortedError` (WinError 10053)
on a whole-suite run escapes the test body and is reported as `Test crashed`,
with no error text and no assertion context. Its sibling `_send_proxy_request`
already degrades this correctly.

**2. Long-lived children's stderr is never drained.** The proxy children use
`stderr=subprocess.PIPE` and outlive the test body, so nothing reads the pipe
until teardown. A child that writes more than the ~64 KiB pipe buffer blocks. The
issue is explicit that this is an unmeasured candidate mechanism, so this step
removes the mechanism and does not claim it as the cause.

**3. The state-file removal policy has nine sites across two files, and the
trace lifecycle test cannot fail.** Eight hand-rolled copies sit in
`test_cli.py` next to the shared helper whose docstring says the policy is
centralized. Separately, the trace test kills the proxy abruptly and *warns*
about the missing `proxy_stop` marker — a warning that is guaranteed on Windows,
so the assertion can never fire.

```
  _admin_post ──► [NEW] try/except ──► (0, "WinError 10053")  ──► diagnosable FAIL
  long-lived child ──► stderr=PIPE ──► [NEW] daemon reader ──► cannot block
  test_cli.py × 8 ──► [NEW] _remove_test_state_file() ──► one policy, one place
  test_trace.py ──► terminate() + warn ──► [NEW] /admin/shutdown + fail
  _start_proxy_with_flag ──► no callers ──► [NEW] deleted
  "READY" not in stdout ──► always "" ──► [NEW] `if not probe_ok: fail(...)`
```

**5. Dead weight and an unfailable assertion** (added 2026-10-16, from the
step-1–4 round's own out-of-scope notes). `_start_proxy_with_flag` has no callers
— its only other reference is this plan's Step 2 gate, which is why Step 2
changed it at all. And `_assert_startup_aborted` checks a stdout string that the
readiness reader has already consumed to EOF, so it passes unconditionally; the
`probe_ok` the spawn helper actually computes is bound and thrown away. **This is
the same false-pass class Step 3b removes one file over**, which is why it is
folded here rather than deferred.

**6. Long-lived children's stderr is never drained — for 21 of 22 of them**
(added 2026-10-16, from the Phase 6 review). Step 2 above drains the children
`_start_proxy_server_directly` and `_start_proxy_with_flag` spawn. The review
counted every other site that spawns a proxy child with `stderr=subprocess.PIPE`
and never reads it: **17 in `tests/test_retry_streaming.py`, 4 in
`tests/test_trace.py`, zero `communicate()` calls in either file.** Each of those
children runs a whole test body — a retry loop, a 429 exhaustion, a
concurrent-request burst. So the mechanism item 2 describes survives in 21
places, and the doc row this plan added reads as though it does not. The same
review found the registries are keyed by `id(proc)` and leak on the success path
(measured: 3 stale entries after 8 spawns, none still matching a live `Popen`),
and that the drain read is single-shot — all three are Step 6.

**Alternatives considered.** (a) *Transport tolerance only, leave stderr alone* —
defensible, since the pipe-full mechanism is unconfirmed; rejected because
removing a plausible blocker is cheap and the diagnostic gap was named in the
same issue. (b) *Redirect children's stderr to per-child temp files* — removes the
pipe mechanism outright, but has a wider blast radius across the spawn sites and
the readers. (c) *Leave the `warn` in place and assert the marker's absence
explicitly* — honest, but abandons coverage of `write_stop_marker` entirely,
which is the thing the test was written for.

**Out of scope.** Root-causing the admin readiness/abort flakes (this plan makes
them diagnosable, not fixed); whether `PROXY_STATE_FILE` should be keyed
per-test rather than per-run; the `cmd_stop` exit-code contract itself (owned by
`2026-10-15-posix-shutdown-and-stop-reporting`); giving the harness a second
capture buffer for a child's **stdout** (Step 5 removes the one assertion that
would have wanted it, and the readiness signal it needs is already computed —
if a future test genuinely needs the child's stdout text, that is its own
change).

## Repo Mode

Public

## Document Overrides

| Document | Rule Overridden | Reason |
|----------|----------------|--------|

## Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| The stderr drain changes how `_read_child_stderr` sources its text | Existing failure-path diagnostics could silently become empty strings, making future failures harder to diagnose — the opposite of the intent | The step's verifier includes a leak-of-behaviour check: spawn, kill, and confirm real stderr text still comes back; the fallback path is preserved, not deleted |
| Consolidating the 8 removal sites loses the reason each test needed a clear | A future reader removes the call and reintroduces the flake | The step explicitly requires keeping every local rationale comment and widening the helper's docstring |
| The admin flake may still be red after this plan | The suite stays intermittently red, and this plan is read as having "fixed" it | Stated here and in the issue log: this makes the failure *diagnosable*, it does not claim to make it green. The baseline (418/418, 1 warning) is recorded so a post-change red is unambiguous |
| Step 5b swaps one unfailable assertion for another | The abort tests would look like they check readiness while checking nothing — the defect being fixed, reintroduced | The calibration's last check is exactly this: a healthy child on a **writable** path must report `probe_ok=True`, so the new `fail(...)` branch is reachable in practice, not just in principle |
| Step 5a's deletion takes a neighbour with it | `_create_test_config_with_flag` backs four modules; losing it turns the whole suite red | The gate names it and three other survivors explicitly, and one of the six calibration half-fixes is exactly "the retirement took a survivor" |
| Step 6b's 21 insertions satisfy the gate without draining anything | The gate counts call sites; a call placed where the child is already dead would pass it while doing nothing | The plan requires a probe that spawns one of the newly drained children and shows its stderr landing in the buffer, and the reviewer's Finding-5 measurement is the baseline the probe is checked against |
| The `weakref` registry releases an entry while a caller still needs it | A later `_read_child_stderr` would fall through to `communicate()` and return `""` where it used to return text | A caller passing `proc` holds a strong reference for the duration of the call, so the entry cannot be collected under it; `_start_proxy_server_directly` also keeps the child in its caller's scope. The gate pins the key expression rather than the mechanism, so a different binding (an attribute on the proc) is also acceptable |

## Proposed Changes

1. **Step 1:** Give `_admin_post` in `tests/_harness.py` the transport tolerance its sibling `_send_proxy_request` already has, returning `(0, str(e))` instead of raising (tester-owned)
   → tester verify: `./tmp/verification/2026-10-15-test-harness-robustness-step1.py` exits 0; fault-injection check returns `(0, "<error text>")` against a closed port
2. **Step 2:** Add a daemon `_drain_child_stderr(proc)` reader in `tests/_harness.py` and call it from both long-lived spawn helpers, so a chatty child cannot block on a full stderr pipe (tester-owned)
   → tester verify: `./tmp/verification/2026-10-15-test-harness-robustness-step2.py` exits 0; the spawn-kill-read check still returns the child's real stderr text
3. **Step 3:** Replace `test_cli.py`'s 8 hand-rolled state-file removals with `_harness._remove_test_state_file()` (keeping each local rationale comment) and widen that helper's docstring; then switch `test_trace.py`'s lifecycle test to a graceful `/admin/shutdown` and elevate the missing `proxy_stop` marker to a hard failure (tester-owned)
   → tester verify: `./tmp/verification/2026-10-15-test-harness-robustness-step3.py` exits 0; full suite green with the `No proxy_stop event in trace` warning gone; removing `write_stop_marker()` in a scratch edit turns the suite red
4. **Step 5:** Retire the dead `_start_proxy_with_flag` from `tests/_harness.py` and replace `_assert_startup_aborted`'s unfailable `"READY" not in stdout` check with the `probe_ok` the spawn helper actually computes (tester-owned)
   → tester verify: `./tmp/verification/2026-10-15-test-harness-robustness-step5.py` exits 0, and `./tmp/verification/2026-10-15-test-harness-robustness-step5-calibration.py` exits 0 — the gate accepts the prescribed fix, rejects the pre-fix tree plus six half-fixes for the stated reasons, and a healthy child on a writable path reports `probe_ok=True` so the new `fail(...)` branch is reachable
5. **Step 6:** Bind the stderr-drain registry to the child rather than `id(proc)`, drain the 21 long-lived spawns `tests/test_retry_streaming.py` and `tests/test_trace.py` contain, and make the drain read repeatable (tester-owned)
   → tester verify: `./tmp/verification/2026-10-15-test-harness-robustness-step6.py` exits 0 against the final tree, and `./tmp/verification/2026-10-15-test-harness-robustness-step6-calibration.py` exits 0 — it reconstructs the pre-fix tree from pinned literals, accepts the prescribed fix and a re-wrapped version of it, rejects the pre-fix tree plus four half-fixes each for the stated reason, and fails on any transform that silently no-ops
   → tester verify: a probe that spawns one of the newly drained children and shows its stderr text arriving in the drain buffer — the gate counts call sites, and a call placed where the child is already dead would satisfy it while draining nothing

## Guidance for Planner

Documentation tasks you will execute yourself (not the coder):

- **Files to modify:**
  - `./doc/test-catalog.html`
- **When:** after the tester finishes
- **What to sync:**
  - `doc/test-catalog.html` — the isolation section enumerates the state-file
    removal sites ("harness import, the three wrapper cleanup() closures, and
    run_cli's per-test loop"); add `test_cli.py`'s test bodies so the page matches
    the helper's widened docstring.
  - `doc/test-catalog.html` — the per-test index: update the entry for the trace
    lifecycle test (it no longer terminates abruptly; it stops via
    `/admin/shutdown` and asserts `proxy_stop`), and note that the
    `No proxy_stop event in trace` warning is retired. Add entries for any new
    test the tester creates.
  - **Not in this plan:** `CLAUDE.md`'s "Unresolved Deferred Issues" block — it
    is rewritten wholesale by plan `2026-10-15-deferred-corpus-sweep`. Note that
    `CLAUDE.md`'s Gotchas section cites the trace warning indirectly through the
    `no-proxy-stop-trace-warning` index row; the sweep plan removes that row.

## History

| Date | Event | Conclusion | Dismissed |
|------|-------|------------|-----------|
| 2026-10-15 | Initial plan | Tester-lane-only plan (no coder work): `_admin_post` transport tolerance, a daemon stderr drain for long-lived children, and test hygiene (9 removal sites single-sourced; trace lifecycle test made able to fail). All three gates calibrated red against the pre-change tree. | — |
| 2026-10-15 | Spec revision (pre-launch pre-flight) | Line references re-verified against the tree as it stands after `2026-10-15-posix-shutdown-and-stop-reporting` landed (`e080d73`). Plan A edited `tests/_harness.py` **above** every function this plan cites (its `_READY_MARKER` comment, +5/−2 net **+3**), so all five `_harness.py` references had drifted by exactly +3 and are now corrected: `_admin_post` 667→**670**, `_send_proxy_request` 638-662→**641-665**, `_start_proxy_server_directly` 546→**549**, `_start_proxy_with_flag` 1013→**1016**, `_read_child_stderr` 520→**523**. Two references were checked and are **unchanged**: `_remove_test_state_file` at 99 (above Plan A's edit) and `server.py:3977` for the win32 SIGINT gate (Plan A's `server.py` edits sit below it). Note for future revisions: the function **names** are the durable anchor here — the line numbers are a convenience and this plan's file is edited by other plans in the same cycle, so re-verify before launching rather than trusting the numbers. | — |
| 2026-10-15 | Spec revision (/update-plan) | Added **Step 4** on direction carried over from the third-pass review of `2026-10-15-posix-shutdown-and-stop-reporting` ([report](./tmp/reports/2026-10-15-posix-shutdown-and-stop-reporting-review3-2026-10-15.json), finding `review-harness-both-signal-handlers-windows`). That plan's Step 4e introduced the `_READY_MARKER` comment claiming the child "registered both signal handlers"; it is false on Windows, where `signal.signal(SIGINT, …)` is POSIX-gated at `server.py:3977` and only SIGTERM is registered. Folded here rather than into a round of its own — this plan already owns `tests/_harness.py`, so the fix rides along at no extra round cost. Wording only; READY's position and the comment's load-bearing claim are untouched. New gate `step4.py` (red pre-fix) plus `step4-calibration.py`, which measures both directions: the gate must reject the current comment and four half-fixes — including a comment still saying "both handlers" whose only "qualifier" is the lowercase `posix` inside the plan id, the false-pass class the sibling gate was just caught committing — and must accept a correct rewrite, since an unsatisfiable gate would block the round. | — |
| 2026-10-16 | Spec revision (pre-launch pre-flight, planner) | **Steps 1 and 2 carried their edits only in prose, and were rewritten to carry complete code** — the same defect that cost the preceding plan seven tester rounds. Step 1 gained the full replacement `_admin_post` (noting the error return is a `str`, not the `bytes` its sibling returns); Step 2 gained the two registries, the full `_drain_child_stderr` body (previously only its docstring), the full `_read_child_stderr` replacement, and the two call sites — with an explicit "those two only" for the short-lived children at `:242`/`:262`, whose readers would race the `communicate()` on the next line. Also added an `## Immediate Actions` short-form, and corrected the header's "Three independent hardening steps" to four. | — |
| 2026-10-16 | Implementation round (tester) — **`overall_result: SUCCESS`, report written**, all four gates green | The first round in this plan's life, and the first in this cycle to complete every step **and** write its session report. Full suite **424 passed, 0 failed**, and the plan's recorded `No proxy_stop event in trace` warning is **gone** from the summary. **The round found a real defect in Step 2's spec and fixed it before the code ever reached the tree**: the drain thread owns the child's stderr pipe, but `_start_proxy_server_directly`'s own callers read it through plain `proc.communicate()`, which returns `""` once a reader has drained it — 3 sites in `test_cli.py` and 8 in `test_config_keys.py`, 11 assertions that would have gone red with empty diagnostics, exactly the risk this plan's Risk table named. The plan reasoned about the two short-lived children and correctly excluded them, then missed the long-lived helper's *callers*. All 11 were routed through `_read_child_stderr`; the file set widened to `tests/test_config_keys.py`, recorded in the metadata and in the round's own `out_of_scope`. The round also corrected a neighbouring docstring (`_await_child_ready_marker`) that this change made false — a knock-on the plan had not noticed. Three doc discrepancies filed, all planner-owned and fixed; three out-of-scope observations recorded. | — |
| 2026-10-16 | Spec revision (/update-plan) — **Step 5 added** | The round's two surviving out-of-scope observations were **folded into this plan rather than deferred**, because both sit in files it already declares and both are the class its Steps 1–3 target. (The third — the Step 4 calibration's one-shot measurement — the round repaired itself; nothing further is owed on it.) **5a:** `_start_proxy_with_flag` is dead, and Step 2 modified it *to satisfy a gate* — the gate driving the code. Recorded dead since [plans/2026-08-25-fix-windows-readiness-probe.md](./plans/2026-08-25-fix-windows-readiness-probe.md); retired now, with Step 2's `LONG_LIVED` tuple narrowed to match (a contract change, and Step 5's gate re-runs Step 2's gate so the narrowing cannot hide a regression). **5b:** `_assert_startup_aborted`'s `"READY" not in stdout` check cannot fail — the readiness reader has already consumed stdout to EOF, so `communicate()` returns `""` — and it is replaced by the `probe_ok` the spawn helper computes and both call sites currently discard. **The residual risk in 5b is swapping one unfailable assertion for another**, so the calibration measures the direction that matters: a healthy child on a *writable* path must report `probe_ok=True`, i.e. the new `fail(...)` branch is reachable. Both new scripts are calibration-proof against the one-shot defect: they build their variants from **pinned literals**, never from the live file, so they still mean something once the fix lands. Seven directions measured — GREEN for the prescribed fix, RED for the pre-fix tree and six half-fixes, each for the stated reason. | — |
| 2026-10-16 | Implementation round (tester, attempt 2) — **`overall_result: SUCCESS`, report written**, both Step 5 gates green | Step 5 landed in ~17 minutes with no step failure. Reports `424 passed, 0 failed, 0 skipped` — exactly the count the plan predicted, since the step rewrites harness code and one assertion and adds no coverage — and both abort tests PASSED for the right reason. Every earlier gate was re-run afterwards (step1, step1-calibration, step2, step3, step3-redproof, step4, step4-calibration — all green), because the synthetic-tree gates copy the two files this round edited. The round added one thing the plan had not asked for and should have: `step5-probe-redproof.py`, which proves the new assertion is load-bearing **against the committed tests** — a scratch mirror handing both call sites `True` turns both abort tests red, while the unmodified mirror passes. **It also found a real defect in the planner's calibration** (see the next row). Two out-of-scope observations and one doc discrepancy recorded. | — |
| 2026-10-16 | Post-round repair (planner) — **calibration de-coupled from the live file; doc row de-pluralised** | The round measured a genuine false-GREEN in the Step 5 calibration this plan supplied: its `stale-docstring` direction reverted the corrected sentence by `.replace()`-ing **the live file's text**, so the moment that sentence was re-wrapped the replace became a silent no-op, the variant collapsed into the "fixed" one, and a half-fix came back GREEN. The row above had claimed both new scripts "build their variants from pinned literals, never from the live file" — true of the harness helper, **false of `_drain_after_exit`**. Fixed by pinning both `_drain_after_exit` states as literals and splicing them by AST span, exactly as `PREFIX_HELPER` already was; the old `.replace()`-based construction is kept **only** as the independence check's negative control, which now demonstrates the hazard (old construction GREEN, pinned construction RED on the same re-wrapped tree) rather than asserting it. Two directions were added to the calibration in the same pass: `rewrapped-docstring`, requiring the correction to be accepted when wrapped differently — Step 5b's deliverable is the claim, not its line breaks — and the live-text-independence section. Both new scripts still exit 0 on the real tree after the change, and the gate itself was not implicated. Also fixed the one doc discrepancy the round filed: `doc/test-catalog.html`'s `_drain_child_stderr` row said "the spawn helpers" where Step 5a leaves exactly one. | — |
| 2026-10-16 | **Phase 6 review** (report `tmp/reports/2026-10-15-test-harness-robustness-review-2026-10-16.json`) — verdict "Issues found — non-blocking" | Run because this plan, like the preceding one, was authored with no review step and that gap had just paid off once already. It re-ran the full suite independently (424/0) and all 12 gate checks, confirmed the plan's evidence lines, and refuted three of its own five hunches **by measurement** — the `id(proc)` collision does not produce a wrong-buffer read (a 300-spawn probe never landed on a stale key), a second drain read neither races nor hangs (it silently returns `""`), no reader is left against a closed pipe, `_admin_post`'s `str` return breaks none of its 38 call sites, and `probe_ok`'s TCP fallback cannot fire in the abort tests because the child exits before binding. **The finding that matters is one no round had looked for**: 22 sites spawn a long-lived proxy child with `stderr=subprocess.PIPE` and never read it, and Step 2 drains **one**. `test_retry_streaming.py` has 17 (`communicate()` count: 0) and `test_trace.py` has 4 (0). So the pipe-full mechanism Step 2 exists to remove survives in 21 places, and the doc row this plan added reads as though it does not. Also found: the registries are address-keyed and leak on the success path (measured: 3 stale entries after 8 spawns, 0 still matching a live `Popen`); the drain read is single-shot and its result best-effort; and one doc sentence over-claims which `test_cli.py` bodies clear the state file first — `test_start_rejects_uncatalogued_model_selector_at_cli` clears at its *end*, not its start (verified independently). Severity was not inflated: 1 Low, 4 Suggestions, no Critical or High, and the review says so itself. | — |
| 2026-10-16 | Spec revision (/update-plan) — **Step 6 added from the review** | Four of the five findings become Step 6; the doc over-claim was fixed directly by the planner. **6a** binds the two registries to the child (`weakref.WeakKeyDictionary`) instead of `id(proc)` — done before 6b adds 21 more registrations, because more entries that are never released is exactly the retention the review measured. **6b** drains the 21 missing sites; the instruction is mechanical and anchors on each `Popen`'s own closing paren. **6c** retains the buffer instead of popping it, which makes the accessor repeatable, and documents the one direction in which it is still best-effort. The gate is AST-based and cross-checks each file's drain calls against its own **spawn** count rather than a magic number, so a future spawn without a drain goes red rather than unnoticed. Its calibration **reconstructs the pre-fix tree from pinned literals** — idempotently, so it runs before and after the fix — and fails loudly on any transform that silently no-ops, which is the general form of the very defect Step 5's calibration had to be repaired for. Eight directions measured, including GREEN for a re-wrapped docstring, since 6c's deliverable is the contract and not its line breaks. | — |
| 2026-10-16 | Implementation round (tester, attempt 3) — **all of Step 6 landed, every gate green, `overall_result` unknown: no session report** | Steps 6a/6b/6c reached the tree at 15:12–15:13 and the gate, its calibration and three companion probes (`-step6-drain-probe.py`, `-step6-retention.py`, `-step6-import-redproof.py`) were all green by 15:20 — the planner re-ran every one of them afterwards and they still exit 0. The suite it ran at 15:20–15:29 came back **423 passed, 1 failed**: `client-disconnect-no-traceback`, whose assertion is fed by a *direct* `proc.stderr.read()`. The round diagnosed this as Step 6b's own omitted consequence — a drain reader owns the pipe, so the direct read returns `""` — rerouted both direct reads at 15:31, and re-ran the two stderr-reading tests green. **It was then killed at 15:39 by the Bash wrapper's 30-minute default, while the launcher's own `--timeout` was 3600** — the wrapper was the killer, not the round's budget — so it never wrote `tmp/reports/2026-10-15-test-harness-robustness-tester-2026-10-16-3.json`. This is the third round of this plan to end without a report, and the first where the *work* is complete: the only thing missing is the attestation. Independently re-verified by the planner: all gates exit 0, the declared suite is **424 passed, 0 failed**, and the once-failing test passes **12/12** standalone. | — |
| 2026-10-16 | Spec revision (/update-plan) — **Step 6b corrected; Immediate Actions rewritten as verification-only** | Two changes, both consequences of the round above. **(1)** Step 6b said "Insert nothing else and move no existing line", which is what the round did and what produced the 423/1 suite: the step now carries the read-site reroute as part of itself, in code, with the reason a store must enumerate every *reader* of a pipe whose ownership it is about to change — and with the sharper half recorded, that the four assertions which broke silently are the **negative** ones ("no `Traceback`", "no `client_disconnect` event"), which an empty read satisfies perfectly. **(2)** The Immediate Actions section no longer asks for Step 6 to be applied. It is in the tree, and a rerun would install a **second** drain reader at each of the 21 sites and split the child's stderr between two threads — the defect class the step exists to remove, reintroduced by re-running it. The section now asks for a verification-only round whose whole purpose is the missing report. The planner's own first reading of that 423/1 log — as an unexplained load-sensitive flake, and as grounds for a possible Step 7 — was **wrong**; round 3's progress log (`tmp/logs/…-tester-2026-10-16-3.log`) timestamps the reroute *after* the suite run, which is what refuted it. A stale suite log is a snapshot of an intermediate state, not a verdict on the tree. | — |
| 2026-10-16 | Implementation round (tester, attempt 4, **verification-only**) — **`overall_result: SUCCESS`, report written**; the missing attestation is closed | Report at `tmp/reports/2026-10-15-test-harness-robustness-tester-2026-10-16-3.json`, written 16:31, ~23 minutes after launch. This round exists for one reason — round 3's step landed without a report — and it did that job on **independent** evidence rather than by restating the plan. **Nothing in `tests/` changed**: `git status --porcelain` is byte-identical before and after, which is also the check that Step 6 was not re-applied (a rerun would have put a second reader thread on each of the 21 drained pipes). All 21 verification scripts named in the metadata were re-run as discrete, individually-reported calls: **20 exit 0**, and the single exit-1 (`step2-communicate-interaction.py`) is a *measurement* whose non-zero outcome is its designed result — it demonstrates the pipe handover round 1 diagnosed, and its own docstring says it is not a pass/fail of the plan. The declared runner, in the foreground: **424 passed, 0 failed, 0 warnings**, with the baseline `No proxy_stop event in trace` warning gone and the marker positively pinned instead. The evidence is not only counts: the two Step 5 abort tests pass for the right reason (`probe_ok` False **and** the diagnostic naming the blocked path), and the 21 Step 6 insertions are shown to drain a **live** child by behavioural probe rather than merely counted — the plan's own named risk. The once-red `client-disconnect-no-traceback` is green in the suite, 3/3 standalone, and passing the positive stderr assertion that a drained-pipe direct read would fail. The round also verified claims no gate could: the retirement candidates are not obsolete (`test_cli.py:149-152` tests the dead-PID success branch while the sibling plan's new test owns the surviving-process branch), `tests/temp/` is empty so no cleanup was owed, no test was removed or skipped, and the doc rows match the landed code. Two **Low** doc notes and three out-of-scope observations recorded; no issue report was warranted, because nothing failed. | — |
| 2026-10-16 | Spec revision (/update-plan) — **round 4's two doc notes fixed; the stale-log citation corrected** | Both notes were planner-owned and both are fixed. **(1)** The plan's Step 3(a) prose claimed the eight consolidated sites carried "the 7 'Ensure cmd_start doesn't refuse with Proxy already running' comments"; measured against the tree, exactly **three** sites carry that comment (`tests/test_cli.py:86`, `:198`, `:590`). The instruction was honoured in full — every comment that existed was preserved — and the published doc never repeated the count, so this was a false claim in the plan and nothing worse; corrected in place with the correction marked. **(2)** `doc/test-catalog.html`'s `_admin_post` row said only "Hit the admin API with a correct Origin by default", while its two neighbours document their contracts at length; it now carries the transport-tolerance contract Step 1 gave it, including the `str`-not-`bytes` detail. **(3)** A citation the planner had written into the Issue Log — line numbers in `tmp/verification/…-full-suite.log` for the vacuous-pass signature — was **already stale when written**: round 4 overwrote that log with its own 424/0 run, so the row now cites the assertions in `tests/test_retry_streaming.py` and round 3's progress log instead. Round 4 flagged the same property one level out, in `adapted-sites.py`, which parses that log rather than running anything — noted under *Observed, deliberately not changed*. | — |
| 2026-10-16 | Step 9.9 disposition (user decision) — **orphaned-state-file accumulation deferred** | Round 4's second out-of-scope observation — 36 per-run state files in `~/.claude/proxy/`, with this plan's verification scripts a systematic source — was presented to the user rather than disposed of by the planner, because "no plan owns this" is not a disposition under this plan's own rule that every dismissal ends in fix, defer, or an explicit human confirmation. **The user chose defer.** Filed as [defer-issue-orphaned-test-state-files](./tmp/reports/defer-issue-orphaned-test-state-files.json) (`status: Open`, `deferred: 2026-10-16`, `target_repo: null`) with an Issue Log row and a `### Deferred` entry above. The deferral raises the corpus to **30 files**, which the cycle's last plan must pick up in its counts. | — |

## Plan Metadata

```json
{
  "plan_id": "2026-10-15-test-harness-robustness",
  "steps": [
    "Step 1: Give _admin_post in tests/_harness.py the transport tolerance its sibling _send_proxy_request already has",
    "Step 2: Add a daemon _drain_child_stderr(proc) reader in tests/_harness.py and call it from both long-lived spawn helpers",
    "Step 3: Replace test_cli.py's 8 hand-rolled state-file removals and switch test_trace.py's lifecycle test to a graceful /admin/shutdown",
    "Step 4: Correct the _READY_MARKER comment in tests/_harness.py, which claims both signal handlers are registered although SIGINT is POSIX-gated",
    "Step 5: Retire the dead _start_proxy_with_flag from tests/_harness.py, and replace _assert_startup_aborted's unfailable stdout check with the spawn helper's probe_ok",
    "Step 6: Bind the stderr-drain registry to the child instead of id(proc), drain the 21 long-lived spawns Step 2 missed in tests/test_retry_streaming.py and tests/test_trace.py, and make the drain read repeatable"
  ],
  "coder_files": [],
  "tester_files": ["tests/_harness.py", "tests/test_cli.py", "tests/test_trace.py", "tests/test_config_keys.py", "tests/test_retry_streaming.py"],
  "doc_files": ["./doc/test-catalog.html"],
  "verification_scripts": [
    "./tmp/verification/2026-10-15-test-harness-robustness-step1.py",
    "./tmp/verification/2026-10-15-test-harness-robustness-step2.py",
    "./tmp/verification/2026-10-15-test-harness-robustness-step3.py",
    "./tmp/verification/2026-10-15-test-harness-robustness-step4.py",
    "./tmp/verification/2026-10-15-test-harness-robustness-step4-calibration.py",
    "./tmp/verification/2026-10-15-test-harness-robustness-step5.py",
    "./tmp/verification/2026-10-15-test-harness-robustness-step5-calibration.py",
    "./tmp/verification/2026-10-15-test-harness-robustness-step5-probe-redproof.py",
    "./tmp/verification/2026-10-15-test-harness-robustness-step6.py",
    "./tmp/verification/2026-10-15-test-harness-robustness-step6-calibration.py",
    "./tmp/verification/2026-10-15-test-harness-robustness-step2.py (revised: LONG_LIVED narrowed per Step 5a)"
  ],
  "verification_scripts_added_by_round": [
    "./tmp/verification/2026-10-15-test-harness-robustness-step1-calibration.py",
    "./tmp/verification/2026-10-15-test-harness-robustness-step1-fault-injection.py",
    "./tmp/verification/2026-10-15-test-harness-robustness-step2-communicate-interaction.py",
    "./tmp/verification/2026-10-15-test-harness-robustness-step2-leak-of-behaviour.py",
    "./tmp/verification/2026-10-15-test-harness-robustness-step3-redproof.py",
    "./tmp/verification/2026-10-15-test-harness-robustness-adapted-sites.py",
    "./tmp/verification/2026-10-15-test-harness-robustness-baseline-delta.py",
    "./tmp/verification/2026-10-15-test-harness-robustness-full-suite.py",
    "./tmp/verification/2026-10-15-test-harness-robustness-step6-drain-probe.py",
    "./tmp/verification/2026-10-15-test-harness-robustness-step6-retention.py",
    "./tmp/verification/2026-10-15-test-harness-robustness-step6-import-redproof.py"
  ],
  "repo_mode": "Public",
  "document_overrides": []
}
```

## Audit Accumulation

| Counter | Value | Last Updated |
|---------|-------|--------------|
| issues_resolved_since_audit | 1 | 2026-10-16 |
| steps_changed_since_audit | 2 | 2026-10-16 |
| files_changed_since_audit | 3 | 2026-10-16 |

Counted against the Phase 6 review (`tmp/reports/2026-10-15-test-harness-robustness-review-2026-10-16.json`,
14:48), which is this plan's last audit. Everything counted here landed **after**
it: **Step 6 was written from that review's findings and then corrected once**
(two step changes), one issue was resolved in the Issue Log
(`step6b-drain-steals-direct-stderr-reads`), and the three files Step 6 landed in
are `tests/_harness.py`, `tests/test_retry_streaming.py` and
`tests/test_trace.py`. So the review audited the plan, not the code that answers
it — the Step 6 gate, its calibration and the three companion probes are what
stand in for an audit of the change itself, and round 3's missing session report
is the residue.

`steps_changed_since_audit` counts Step 5, added 2026-10-16 after the initial
plan; `files_changed_since_audit` counts `tests/test_config_keys.py`, which the
round's Step 2 adaptation had to reach and the plan had not declared.
`issues_resolved_since_audit` stays 0 — this plan has had no mega-audit, and its
seven resolved rows are its own work, not drift discovered against an audited
baseline.

## Documentation

- `doc/test-catalog.html` — the state-file removal-site enumeration, the trace
  lifecycle test's new graceful-stop path, and the retired warning.
- **Step 5 changes exactly one documentation row.** Neither
  `_start_proxy_with_flag` nor `_assert_startup_aborted` nor `_drain_after_exit`
  appears anywhere under `doc/`, `README.md`, or `CLAUDE.md` — checked by name
  across all three — so retiring the first and rewriting the second leaves no doc
  reference dangling. The one row that did need an edit is the harness-helper
  table's `_drain_child_stderr` entry, whose "Called by the spawn helpers" became
  singular when 5a left exactly one long-lived spawn helper; the tester round
  filed it and the planner fixed it. Its `_read_child_stderr` neighbour, added in
  the first round, stayed accurate through Step 5.
- **Step 6 rewrites both of those rows, and the `_read_child_stderr` one is the
  reason the doc is in this plan's file set at all.** The `_drain_child_stderr`
  row's "called by the one long-lived spawn helper … never by tests" became false
  the moment Step 6b drained 21 spawn sites *from the test bodies themselves*, so
  the row now names the 21 and says why they are drained. The
  `_read_child_stderr` row carried "a plain `proc.communicate()` on such a child
  returns `""`" — true, and now deliberately widened to *any* direct read,
  because Step 6's own failure was a `proc.stderr.read()` and the general rule is
  the transferable part: **the reader owns the pipe; an assertion that reads it
  directly is asserting on an empty string**, and if it is phrased negatively it
  will pass.

## Final Results

**Completed:** 2026-10-16
**Status:** COMPLETED.
**Plan ID:** 2026-10-15-test-harness-robustness
**Rounds:** 4 tester rounds (2026-10-16). No coder round — this plan has no
coder lane. Rounds 1, 2 and 4 wrote reports (round 4 a verification-only round,
launched to attest Step 6 after round 3's work landed but its report did not).

### What shipped

Six changes, all inside the test harness. Nothing here touches production
behaviour; every one of them changes whether the suite can *tell you* something
is wrong.

| Step | Change | File |
|------|--------|------|
| 1 | `_admin_post` gets its sibling's transport tolerance — a `ConnectionAbortedError` now surfaces as a failed assertion carrying the error text instead of `Test crashed` | `tests/_harness.py` |
| 2 | `_drain_child_stderr` gives every long-lived child a daemon stderr reader, so a chatty child cannot block on a full pipe | `tests/_harness.py` |
| 2 (knock-on) | The 11 stderr reads of a drain-owning child route through `_read_child_stderr` — 3 in `test_cli.py`, 8 in `test_config_keys.py` | `tests/test_cli.py`, `tests/test_config_keys.py` |
| 3 | The 8 hand-rolled state-file removals become `_remove_test_state_file()` calls, each rationale comment preserved | `tests/test_cli.py` |
| 3 | The trace lifecycle test stops the proxy via `POST /admin/shutdown` and the missing `proxy_stop` marker is a hard failure, not a warning | `tests/test_trace.py` |
| 4 | The `_READY_MARKER` comment stops claiming both signal handlers are registered | `tests/_harness.py` |
| 5 | The dead `_start_proxy_with_flag` is retired (Step 2's gate was narrowed to match) | `tests/_harness.py` |
| 5 | `_assert_startup_aborted` asserts the computed `probe_ok` instead of an unfailable stdout string | `tests/test_cli.py` |
| 6 | The drain registries become `weakref.WeakKeyDictionary`, keyed by the child instead of by `id(proc)`, and the drain read is retained rather than popped so a repeat read returns the same text | `tests/_harness.py` |
| 6 | The **21** long-lived spawn sites Step 2 missed are drained — 17 in `test_retry_streaming.py`, 4 in `test_trace.py` | `tests/test_retry_streaming.py`, `tests/test_trace.py` |
| 6 (knock-on) | The two direct `proc.stderr.read()` diagnostics in `test_retry_streaming.py` route through `_read_child_stderr` — a drain reader owns the pipe, so a direct read returns `""` | `tests/test_retry_streaming.py` |

**Files changed:** `tests/_harness.py`, `tests/test_cli.py`,
`tests/test_config_keys.py`, `tests/test_trace.py`,
`tests/test_retry_streaming.py`, `doc/test-catalog.html`. Neither
`tests/test_config_keys.py` (Step 2's knock-on) nor `tests/test_retry_streaming.py`
(Step 6's) was in the plan's originally declared file set; the Issue Log explains
why each adaptation had to reach its file.

### Test results

**424 passed, 0 failed, 0 skipped** — the plan's declared runner,
`python tests/test_claude_proxy.py`, run in the foreground. The count did not
move: this plan adds no coverage, it makes the coverage it already had able to
fail. The suite's `No proxy_stop event in trace` warning — the plan's own
recorded baseline — is **gone from the summary**.

**One intermediate run in round 3 was 423/1, and it is recorded rather than
smoothed over.** That run (15:20–15:29) predates the round's own read-site
reroute, which landed at 15:31; the red was Step 6b's omitted consequence, is
diagnosed in the Issue Log, and was fixed inside the same round. The final state
is green — 424/0 in the planner's independent full-suite re-run, and the once-red
`client-disconnect-no-traceback` passes **12/12** standalone.

### Issues resolved

Eight rows in the Issue Log, all `Resolved`:

- `step2-drain-breaks-existing-communicate-stderr-reads` — found by the round by
  **measurement before the code reached the tree**
- `no-proxy-stop-trace-warning`
- `cli-pre-existing-remove-idiom-copies`
- `suite-load-admin-connection-abort`
- `harness-ready-marker-comment-windows`
- `harness-dead-spawn-helper`
- `startup-abort-stdout-assertion-vacuous`
- `step6b-drain-steals-direct-stderr-reads` — Step 6's own knock-on, found by the
  round by **measurement** (a 423/1 suite run) and fixed in the same round

### Deferred

**One deferral.**

- **`orphaned-test-state-files`** —
  [report](./tmp/reports/defer-issue-orphaned-test-state-files.json). Round 4's
  third out-of-scope observation: 36 per-run `claude-retry-proxy-test-state-<pid>.json`
  files had accumulated in `~/.claude/proxy/`, and this plan's own verification
  scripts are a systematic source, because they spawn a proxy child directly and
  so never pass through `run_cli`'s per-test removal loop. Inert by design — the
  per-run PID-keyed name is what removed the old machine-global false-"Proxy
  already running" hazard — but it accumulates, and no plan owned it. Filed at
  the user's direction rather than folded in here, because the sources live under
  `tmp/verification/` and this plan's write scope is `tests/` plus one doc.

Everything else this plan touched was real and in-scope, so it was fixed rather
than deferred. The four resolved `defer-issue-*.json` reports above are retired
at commit time.

### Verification

- **Six step gates** (one per step) plus the calibrations, each run as its step
  finished rather than batched at the end. Step 6 adds its gate, its calibration,
  and three companion probes round 3 wrote: `-step6-drain-probe.py` (the drain is
  bound to a real child, repeatable, sentinel present), `-step6-retention.py`
  (four spawns leave zero entries after drop-and-gc — the property 6a is for), and
  `-step6-import-redproof.py` (the gate's import check is load-bearing).
  **Every script exits 0 against the final tree.**
- **The Step 6 gap is closed.** Round 3 landed all of Step 6 and every gate
  above, then was killed by its launcher wrapper at 15:39 before writing a
  session report. Round 4 was launched for that one purpose and delivered it:
  `tmp/reports/2026-10-15-test-harness-robustness-tester-2026-10-16-3.json`,
  `overall_result: SUCCESS`, on the declared runner in the foreground — 424/0 —
  with all 21 verification scripts re-run as discrete calls (20 exit 0; the one
  exit-1 is a designed measurement, not a failure) and `tests/` byte-identical
  before and after. So every step in this plan now rests on a written tester
  report, and Step 6 rests on two independent confirmations rather than one:
  round 3's gates and round 4's attestation.
- Step 5's gate is AST-based — comments do not exist in an AST — and its
  calibration builds every variant from **pinned literals**, measures the
  prescribed fix GREEN, the pre-fix tree and six half-fixes RED each *for the
  stated reason*, accepts a re-wrapped correction, and demonstrates its own
  independence from the live text with a negative control.
- Both abort tests are green for the right reason, not merely green:
  `probe_ok` False **and** the stderr diagnostic naming the blocked path.
  `step5-probe-redproof.py` shows the assertion is load-bearing by turning both
  tests red in a scratch mirror.

### Three corrections this plan made to its own work

1. **Step 2's spec was defective and the round caught it.** The drain thread owns
   the child's stderr pipe, but `_start_proxy_server_directly`'s own callers read
   it through a plain `communicate()`, which returns `""` once a reader has
   drained it — 11 assertions that would have gone red with empty diagnostics.
   The plan reasoned about the two short-lived children and correctly excluded
   them, then missed the long-lived helper's *callers*. Measured before the code
   landed, adapted in the same round.
2. **Step 5's calibration was defective and the round caught that too.** Its
   `stale-docstring` direction reverted the corrected sentence by
   `.replace()`-ing the live file's text, so a cosmetic re-wrap made the revert a
   silent no-op and a half-fix came back GREEN. Both `_drain_after_exit` states
   are now pinned literals spliced by AST span, and the old construction is kept
   only as the negative control that shows the hazard was real. The planner fixed
   this one post-round.
3. **Step 6b's spec was defective, and the round caught that too — it is the
   third instance of the same failure mode.** The step said to install a drain
   reader at 21 sites and "insert nothing else", and installing a reader changes
   who *owns* the pipe: the two tests that read it directly are then handed `""`.
   The round measured the consequence (423/1), diagnosed it, and rerouted both
   reads — beyond what the step said. Step 6b now carries the reroute in code.
   The three corrections are one defect wearing three hats: **a change to how a
   resource is owned must enumerate every existing user of that resource**, and
   this plan has now paid for that lesson at a helper's callers (2), a
   calibration's anchors (5's follow-up), and a pipe's readers (6).

### Observed, deliberately not changed

Three findings from the rounds that this plan leaves alone. Each is recorded here
rather than silently dropped.

- **A ~110-column line inside `_drain_after_exit`'s docstring**
  (`tests/test_cli.py:1396`). Cosmetic: the repo enforces no line length (no lint
  config in `pyproject.toml`, and the doc gates pass), and the gate is indifferent
  to wrapping — the calibration now proves that with its `rewrapped-docstring`
  direction. Left as the plan's literal so the plan, the tree and the calibration
  agree verbatim. **Disposition: won't fix.**
- **`tests/test_cli.py:1640`'s `test_startup_abort_exits_one_with_failing_stderr`
  also asserts `"READY" not in stdout`** — the same *text* Step 5b removed, but
  **not** the same defect. That test spawns its own `python -c` driver and does
  its own `communicate()`, so nothing has consumed the child's stdout and the
  assertion is reachable; it is belt-and-braces beside the test's primary
  exit-code assertion. Verified by reading the test body. Flagged so a later
  reader does not "consistently" strip it. **Disposition: won't fix — verified
  correct as written.**
- **The admin readiness/abort flakes are still not root-caused.** Step 1 makes
  them *diagnosable*; it does not claim to make them green. Unchanged from the
  plan's stated scope.

Three more, from round 4. Same treatment: recorded, not silently dropped.

- **`tmp/verification/…-adapted-sites.py` reads a log instead of running
  anything**, so its verdict is only as fresh as whatever last wrote
  `…-full-suite.log`. Round 4 measured both readings — it printed `423` against
  the 15:29 intermediate log and `424` against its own — and both agreed, because
  the script only checks that the 8 adapted sites are not `FAILED`, and they never
  were. So its PASS was survivable, but the *shape* is the trap this plan's own
  History row records the planner falling into: an artifact from an earlier tree
  state read as a verdict on the current one. **Disposition: won't fix, and the
  distinction is deliberate** — the script's claim is scoped to the 8 adapted
  sites, which is a static question about the tree, and widening it to "the whole
  suite is green" would make a cheap check depend on a 10-minute run. The plan's
  declared runner is the suite itself; this script is a convenience beside it.
- **Orphaned per-run state files are accumulating, and this plan's own
  verification scripts are a systematic source.** `~/.claude/proxy/` held 36
  `claude-retry-proxy-test-state-<pid>.json` files at round 4, running back to
  2026-10-13. The per-run PID-keyed name is what removed the old machine-global
  false-"Proxy already running" hazard, and CLAUDE.md already records these as
  inert and hand-deletable — so nothing is broken and **no plan owns this**. The
  narrower fact is new: scripts that spawn children directly (Step 1's
  fault-injection success path, Step 6's drain and retention probes, the pre-fix
  mirrors) never pass through `run_cli`'s per-test removal loop, so each
  invocation can leave one behind. **Disposition: recorded, surfaced to the user
  for a decision** — cleanup is `~/.claude/proxy/`, outside this plan's write
  scope, and filing it would change the deferral corpus's counts, which the
  cycle's last plan (2026-10-15-deferred-corpus-sweep) is currently reconciling.
- **`…-step6-drain-probe.py` prints a live `RuntimeError: simulated upstream
  crash` traceback and `[proxy] WARNING:` lines.** Both are the expected
  emissions of the tests it drives (deliberate fault injection and the
  sink-failure tests), not damage. Recorded so a future reader does not mistake
  the probe's output for a failure — the same class of noise round 2 flagged in
  the suite log's tail.