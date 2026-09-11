# Plan: Guard the trace and state sinks against I/O failure

**Project:** D:\proj\claude-retry-proxy
**Plan ID:** 2026-09-10-guard-trace-state-sinks
**Created:** 2026-09-10

## Issue Log

Rows ordered newest-first (latest issues at top). New issues are prepended; resolved issues stay in place with updated status.

| Issue | Status | Found | Resolved | Resolved By |
|-------|--------|-------|----------|-------------|
| [startup-abort-guard-not-gated](./tmp/reports/2026-09-10-guard-trace-state-sinks-tester-2026-09-11-2.json) — the tester's finding that the abort test passed with and without Step 6's guard | Resolved | 2026-09-11 | 2026-09-11 | tester — the assertion now checks the CPython `lost sys.stderr` / `object repr` dump on the real fd 2 and **fails against pre-Step-6 code**, where it previously passed |
| [wrapper-len-boundary-hole](./tmp/reports/2026-09-10-guard-trace-state-sinks-tester-2026-09-11-2.json) — mega-audit Low #18, re-flagged by the tester | Resolved | 2026-09-11 | 2026-09-11 | tester — `write(42)` now returns 0; the test **fails against pre-Step-7 code** with the exact `TypeError` the fix removes |
| [test-fixture-duplication](./tmp/reports/2026-09-10-guard-trace-state-sinks-tester-2026-09-11-2.json) — mega-audit Medium #20, re-flagged by the tester | Won't Fix | 2026-09-11 | 2026-09-11 | user — "leave #3", explicit decision. Planner correction on the record: the duplication is **two** copies, not three — `test_retry_path_print_failure_does_not_misclassify` is an in-process test that patches module globals and cannot use the subprocess fixture. The two copies' visible difference (responder + `extra_env`) is precisely what each test exists to distinguish, so a shared helper would hide it. |
| [mega-audit-2026-09-11-mediums](./tmp/reports/2026-09-10-guard-trace-state-sinks-mega-audit-2026-09-11.json) — findings #5, #8, #9, #13, #21, #27 | Resolved | 2026-09-11 | 2026-09-11 | tester — 288/288; the relative-state-path test fails against pre-Step-6 code, and `test_startup_abort_exits_one_with_failing_stderr` is documented as a regression guard rather than a gate (Step 6's print wrap is not externally observable) |
| [review-retry-path-stderr-prints](./tmp/reports/2026-09-10-guard-trace-state-sinks-review-2026-09-11.json) | Resolved | 2026-09-11 | 2026-09-11 | tester — `test_retry_path_print_failure_does_not_misclassify` added; fails against pre-Step-5 code with the `OSError` escaping `forward_request`, passes after |
| [review-doc-rate-limit-claim](./tmp/reports/2026-09-10-guard-trace-state-sinks-review-2026-09-11.json) | Resolved | 2026-09-11 | 2026-09-11 | planner — CLAUDE.md and README now state the per-episode rule (first failure reports; a success closes the episode) |
| [review-doc-sink-mechanism](./tmp/reports/2026-09-10-guard-trace-state-sinks-review-2026-09-11.json) | Resolved | 2026-09-11 | 2026-09-11 | planner — the parenthetical now describes both sinks (`log_trace` append; `write_state` tmp + `os.replace`) |
| [review-guard-stderr-unguarded](./tmp/reports/2026-09-10-guard-trace-state-sinks-review-2026-09-10.json) | Resolved | 2026-09-10 | 2026-09-11 | tester — `test_sink_emission_survives_failing_stderr` fails against pre-Step-4 code (heartbeat thread died), passes after |
| [review-suppressed-count-off-by-one](./tmp/reports/2026-09-10-guard-trace-state-sinks-review-2026-09-10.json) | Resolved | 2026-09-10 | 2026-09-11 | tester — hardened assertion now requires exactly 4 where pre-Step-4 code reported 5 |
| [review-count-assertions-substring](./tmp/reports/2026-09-10-guard-trace-state-sinks-review-2026-09-10.json) | Resolved | 2026-09-10 | 2026-09-11 | tester — both count assertions parse and assert exact integers |
| [tester-guidance-startup-block-contradiction](./tmp/reports/2026-09-10-guard-trace-state-sinks-tester-guidance-startup-block-contradiction.json) | Resolved | 2026-09-10 | 2026-09-10 | tester — revision 1's runtime-blocking procedure implemented; tests pass |
| [retry-misclassification-test-coverage](./tmp/reports/2026-09-10-guard-trace-state-sinks-tester-guidance-startup-block-contradiction.json) — prose-flagged in that report's `out_of_scope`, no separate report filed | Resolved | 2026-09-10 | 2026-09-10 | tester — `test_trace_write_failure_does_not_duplicate_upstream_request` added; fails pre-fix, passes post-fix |
| [stale-non-editable-install](./tmp/reports/2026-09-10-guard-trace-state-sinks-stale-non-editable-install.json) | Resolved | 2026-09-10 | 2026-09-10 | user — reinstalled with `pip install -e .`, verified by planner (resolved module is the working tree) |
| [unguarded-write-state-log-trace-oserror](./tmp/reports/defer-issue-unguarded-write-state-log-trace-oserror.json) | Resolved | 2026-09-07 | 2026-09-10 | tester — 283/283 pass; the 8 gating tests all fail against HEAD's pre-fix `src/` |

## Guidance for Coder

**Files to modify:** `src/claude_retry_proxy/server.py` (only)

No other file changes. No test files, no docs (see the planner section).

<!-- UPDATED 2026-09-10 (revision 2): line-reference note. -->
**On line references:** Treat every line number in this plan as **approximate**. Steps 1–3 cite the pre-implementation positions they were written against; Steps 4–6 and Guidance for Tester were written against later revisions, and each implemented step shifted the numbers again (Steps 1–2 added ~66 lines above the retry loop, Step 4 a further ~7). Locate symbols by name, never by line.

### Step 1 — Add the sink-failure recording helper

Insert immediately after the `STATE_FILE` constant block (`server.py:730-732`) and before `write_state`, under a new section banner (e.g. `# Sink failure recording (thread-safe)`). Both sinks below this point use it, so it reads top-down.

Definitions (exact names — the Step 2 verification script depends on them):

- `SINK_WARN_INTERVAL = 60.0` — module-level float constant.
- `_sink_warn_lock = threading.Lock()` — guards the state dict below.
- `_sink_warn_state = {}` — maps sink name (`"trace"` | `"state"`) to a dict with keys:
  - `failed` (bool) — an un-recovered failure episode is open
  - `last_warn` (float) — epoch seconds of the last warning
  - `episode` (int) — failed writes in the current episode
  - `since_warn` (int) — failures since the last warning
- `_warn_sink_failure(sink, exc)` — increments the counters under `_sink_warn_lock`, then emits **at most one** stderr line per `SINK_WARN_INTERVAL` for that sink. The first failure of an episode always emits immediately. The message carries, at minimum: the literal `[proxy] WARNING:`, the sink name, the sanitized cause via the existing `sanitize_error(str(exc))` helper (defined later in the file; module-global lookup at call time, so **do not move it**), and — when failures were suppressed since the last warning — how many.
- `_note_sink_recovery(sink)` — call on every successful write. If an episode is open for that sink, emit one stderr line containing `resumed` and the episode's failed-write count, then drop the sink's entry from `_sink_warn_state`.

Message wording is otherwise free, with two hard constraints:

- Matchable substrings: `[proxy] WARNING:`, the sink name, and `resumed` must appear as above. The Step 2 script greps for them.
- **Never include the trace payload or entry contents.** Under `--all` a trace entry can carry raw prompts and completions. The warning is sink name + sanitized exception only.

→ coder verify (auto): `SINK_WARN_INTERVAL`, `_sink_warn_lock`, `_sink_warn_state`, `_warn_sink_failure`, `_note_sink_recovery` are all defined at module level in `server.py`; no new imports were added to the import block (`threading`, `time`, `sys`, `os`, `re` are already imported).

### Step 2 — Guard `log_trace` and `write_state`

Wrap the body of each existing function; keep the statement order, the `_trace_lock` usage, the `os.makedirs` call, and the POSIX `chmod` block byte-identical inside the guard.

- `log_trace` (`server.py:794-806`): `try:` around the existing body → on success call `_note_sink_recovery("trace")` and `return True`; `except Exception as e:` → `_warn_sink_failure("trace", e)` and `return False`.
- `write_state` (`server.py:743-754`): same shape with sink name `"state"`.

Constraints:

- `except Exception` — **not** `BaseException`. `KeyboardInterrupt` and `SystemExit` must still propagate.
- Both functions change return type from `None` to `bool`. Every existing caller ignores the return value (the heartbeat at `server.py:1347` and all ~25 `log_trace` call sites) — **no call-site edits**.
- **Do not** narrow, widen, or otherwise touch the retry loop's `except (socket.error, ConnectionError, OSError)` at `server.py:2112`. Guarding the sink is what removes the misclassification; changing this clause is out of scope.
<!-- UPDATED 2026-09-10: enumerated from the coder's Step 2 report. Step 3 is inoperable without this change. -->
- `write_start_marker()` (`server.py:809`) must **return** `log_trace(...)`'s bool. Without it, Step 3's `if not write_start_marker():` aborts *every* startup — the function previously returned `None`, which is falsy. It has exactly one caller (`main`), so the change is contained.
- **Do not** rename the fixed `STATE_FILE + ".tmp"` temp path or add temp-file cleanup on failure. The name is overwritten on the next attempt; changing it is an unrelated behavior change.

→ coder verify (auto): `write_start_marker` returns `log_trace(...)`'s value; `main` is its only caller
→ coder verify (scripted): run `python ./tmp/verification/2026-09-10-guard-trace-state-sinks-step2.py` from the project root — exercises both sinks against blocked paths (directory-in-place-of-file) and good paths, plus the warning rate limit and the recovery notice. Exit 0 = pass. **Verified during /update-plan 2026-09-10: exits 0, 16/16 checks.**

### Step 3 — Fail fast at startup

In `main()`, act on the two startup sink returns. This is the entire fail-fast mechanism — there is no separate preflight check, because the real writes are the check.

- `server.py:4650` — `write_state(state)` becomes:
  `if not write_state(state):` → print `[proxy] ERROR: state file <STATE_FILE> is not writable — aborting startup` to stderr, then `sys.exit(1)`.
- `server.py:4654` — `write_start_marker()` becomes the same shape for `PROXY_TRACE_FILE` (message: `[proxy] ERROR: trace file <PROXY_TRACE_FILE> is not writable — aborting startup`).

The sink's own rate-limited `WARNING` line supplies the sanitized cause; the `ERROR` line states the consequence and names the path. Both appearing is intended.

Nothing else moves: `_startup_state = state`, the heartbeat thread start, the `ThreadingHTTPServer` construction, and the `READY` print all stay in place and in order. An aborted startup exits **before** `READY` is printed, which is what makes the CLI surface it as "Proxy exited during startup" with the stderr tail.

→ coder verify (auto): both call sites are guarded by `if not ...` with `sys.exit(1)` on the failure branch; `print("READY", flush=True)` still appears after both; no other statement in `main()` changed.

### Step 4 — Make the guard's own emission non-raising, and fix the suppressed count

<!-- UPDATED 2026-09-10 (revision 2): added from the Phase 6 review — see the Issue Log rows prefixed `review-`. -->

The Phase 6 reviewer verified empirically that the guard still raises under the plan's own motivating fault: the server's stderr is a file on the same volume as the state file (`cli.py:510` → `~/.claude/proxy/proxy-stderr.log`), so a full disk breaks the sink write **and** the warning print together. With a stderr whose `write()` raises `OSError(28)`, `log_trace`/`write_state` raised out of the guard and a real `heartbeat_loop` thread died — the pre-fix harm returning. The `"Never raises"` docstrings assert something the code does not currently deliver.

- `_warn_sink_failure` (`server.py:779-780`) and `_note_sink_recovery` (`server.py:789-790`): wrap each `print(..., file=sys.stderr)` in `try/except Exception: pass`. The counters are already committed under `_sink_warn_lock`, so emission is best-effort by construction — nothing is lost by swallowing a failure to *report* a failure.
- `_warn_sink_failure` (`server.py:769-770`): the reported suppressed count currently includes the failure being reported. `entry["since_warn"] += 1` runs before `suppressed = entry["since_warn"]`, so 6 failures producing 2 warnings prints `(5 further failures suppressed)` when only 4 writes were actually silent. Compute the suppressed count for the reporting failure before it is added, so the number matches what the plan specifies: failures suppressed **since the last warning**.
- Do **not** restructure the rate limiter, add a second channel, or change the message wording otherwise. Both changes are local to the helper.

→ coder verify (auto): both `print(..., file=sys.stderr)` calls in the two helpers are inside `try/except Exception` blocks; `_warn_sink_failure` no longer increments `since_warn` before the emission decision uses it
→ tester verify: a stderr whose `write` raises `OSError(28)` leaves `log_trace` returning `False` and `write_state` returning `True` without raising, and `heartbeat_loop` surviving a failing write; the rate-limit test asserts the exact suppressed number, not a substring

### Step 5 — Make runtime diagnostics best-effort

<!-- UPDATED 2026-09-11 (revision 4): from the second review's Warning; user selected option A. -->

The second review found that the misclassification this plan removes is **still reachable through the server's own diagnostic prints** in the retry loop — the 429/503 retry notice (`server.py:2023`), the response-size-cap notices (`:2087`, `:2135`, `:2180`), the connection-error notice in the handler (`:2207`), and the two streaming notices (`:3517`, `:3541`). Under an unwritable stderr (the plan's canonical full-disk fault) one of those prints raises, the `except (socket.error, ConnectionError, OSError)` handler at `:2199` reads it as a connection error, and the outcome is a dropped response — the reviewer measured the client receiving **no response for a 200**, with the `OSError` escaping `forward_request` entirely — or a duplicate upstream POST when the fault is intermittent. `server.py` holds 40 stderr prints, and the hazard is every one reachable from that `try`, so a per-site sweep would be repetitive *and* incomplete by construction: the next added print reopens it.

Fix it once, at the stream:

- Add a module-level `_BestEffortStderr` class near the sink helpers. It stores the wrapped stream; `write(data)` delegates and returns `len(data)` on failure; `flush()` delegates and swallows; `__getattr__` delegates everything else so the wrapper stays transparent (`encoding`, `isatty`, `buffer`, …). Both overrides catch `Exception` — **not** `BaseException`.
- In `main()`, install it once: `sys.stderr = _BestEffortStderr(sys.stderr)`.
- **Placement is load-bearing.** Install it *after* the `write_start_marker()` fail-fast block and *before* the heartbeat thread start and `ThreadingHTTPServer` construction. That keeps both fail-fast `ERROR` messages loud (they run before the wrapper exists) while covering everything downstream. `print("READY", flush=True)` writes to **stdout** and must stay untouched — the CLI's readiness probe depends on it.
- Do **not** touch the retry-loop `except` clause, do **not** wrap individual prints, and do **not** wrap `cli.py`'s streams.

→ coder verify (auto): `_BestEffortStderr` defined at module level with `write`, `flush`, and `__getattr__`; `main()` assigns `sys.stderr` exactly once, positioned after both fail-fast blocks and before `ThreadingHTTPServer(...)`; the `READY` print still targets stdout and is unchanged

### Step 6 — Close the two remaining I/O-safety gaps from the mega-audit

<!-- UPDATED 2026-09-11 (revision 5): from the mega-audit's Medium findings #13 and #5. -->

Both are small, both live in code this plan already touches, and both would otherwise leave a documented promise untrue.

- **Guard the two fail-fast `ERROR` prints** (mega-audit #13). They run *before* the Step 5 wrapper is installed — deliberately, so the abort stays loud — but that means under the plan's canonical fault (full disk; stderr is `~/.claude/proxy/proxy-stderr.log` on the same volume, `cli.py:510`) the `print` raises, `sys.exit(1)` is never reached, and the diagnostic naming the path is lost; the process still exits non-zero via the unhandled traceback, and the CLI prints a partial stderr tail. Wrap **each** of the two `print(..., file=sys.stderr)` calls in `try/except Exception: pass` immediately before its `sys.exit(1)`. The exit path then becomes deterministic and only the message is best-effort.
- **Mirror `log_trace`'s directory guard in `write_state`** (mega-audit #5). `write_state` calls `os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)` with no empty-dirname guard, while `log_trace` guards with `d = os.path.dirname(...); if d:`. `STATE_FILE` comes from raw `os.environ.get`, so `PROXY_STATE_FILE=""` (or a bare relative filename) yields `dirname == ""` and `os.makedirs("")` raises `FileNotFoundError` — which Step 3's fail-fast then reports as "state file … is not writable", pointing at the wrong cause. Add the same `if d:` guard to `write_state`. Do **not** change `STATE_FILE`'s resolution semantics or add relative-path support beyond this — the guard alone removes the misleading failure.

→ coder verify (auto): both fail-fast `ERROR` prints sit inside `try/except Exception` blocks that still reach `sys.exit(1)`; `write_state` contains an `if d:` guard around `os.makedirs`, matching `log_trace`
→ tester verify: with `PROXY_STATE_FILE` set to a bare relative filename and a writable cwd, the server starts (no misleading "not writable" abort) and the state file is written; a stderr whose `write` raises leaves the fail-fast exit code at 1

### Step 7 — Make the stderr wrapper's failure return total

<!-- UPDATED 2026-09-11 (revision 7): user approved the fix for the `len()` boundary hole (mega-audit Low #18, re-flagged by the tester). -->

`_BestEffortStderr.write` swallows a failing stream write, then computes its return value **inside** the `except` branch as a bare `len(data)`. The wrapper's whole purpose is that it never raises; a payload without `__len__` breaks that:

```
w.write("hello")  ->  5                                                    # fine
w.write(42)       ->  TypeError: object of type 'int' has no len()         # the "non-raising" wrapper raises
```

Unreachable through `print` (which always passes a `str`) and therefore theoretical today, but the class exists precisely to guarantee non-raising, and a conditional guarantee is a trap for future code that writes to `sys.stderr` directly.

- In `_BestEffortStderr.write` (`server.py`, in the sink-helpers section), replace the failure return with the generic form: `return len(data) if hasattr(data, "__len__") else 0`.
- Return semantics are unchanged for every payload in use: a sized payload still reports a full write, so a count-checking caller does not turn our swallowed failure back into an error. Only non-sized payloads change, from raising to reporting 0.
- Do **not** change `write`'s success path, `flush`, `__getattr__`, or where the wrapper is installed.

→ coder verify (auto): the `except` branch of `_BestEffortStderr.write` returns `len(data) if hasattr(data, "__len__") else 0`; nothing else in the class changed
→ tester verify: `test_best_effort_stderr_wrapper` extended — with a raising stream, `write(42)` returns 0 without raising, and `write("hello")` still returns 5

## Guidance for Tester

**Files to modify:** `tests/test_trace.py`, `tests/test_retry_streaming.py`, `tests/test_cli.py`

<!-- UPDATED 2026-09-10: precondition added; the runtime-degradation descriptions corrected (they contradicted Step 3's fail-fast); the duplicate-POST coverage gap closed with a new test. -->

**Precondition — the run must exercise the working tree.** The package is installed editable (`pip install -e .`; the stale site-packages snapshot has been removed), so `import claude_retry_proxy.*` and spawned `python -m claude_retry_proxy.server` resolve to `src/`. Confirm before reporting:

```
python -c "import claude_retry_proxy.server as s; print(s.__file__, hasattr(s, 'SINK_WARN_INTERVAL'))"
# expect: D:\proj\claude-retry-proxy\src\claude_retry_proxy\server.py True
```

**Runtime blocking, not startup blocking.** Step 3 fails fast when a sink path is unwritable at startup, so every runtime-degradation test must start the proxy with **healthy** paths and block the path *afterwards*: `os.remove(<path>)`, then `os.mkdir(<path>)`. A proxy started with a blocked path exits before `READY` and never runs. (The `tests/test_compat.py:754` precedent does not transfer — it blocks `PROXY_FEATURE_COMPAT_FILE`, which has no startup check.)

**Tests to create:**

- **Permanent — `tests/test_retry_streaming.py`: `test_trace_write_failure_does_not_duplicate_upstream_request`** *(new in this revision — the only test that gates the retry misclassification)*. Start healthy with `extra_env={"PROXY_MAX_RESPONSE_SIZE": "1024", "PROXY_MAX_RETRIES": "1"}`; the vendor's responder returns a 200 anthropic-shape JSON body larger than 1024 bytes; block the trace path at runtime; send one request. Assert the client got 200 **and** the mock upstream received **exactly one** request. Post-fix the cap logs at `server.py:2072`, `break`s at `:2081`, and `_rewrite_json_response` (`:2399-2402`) returns the truncated body as-is. Pre-fix the same `log_trace` raises, the `except (socket.error, ConnectionError, OSError)` at `:2192` reads it as a connection error, backs off, and re-issues the upstream POST — 2 requests, and the client gets status `0` with an `upstream_unreachable` body. `PROXY_MAX_RETRIES=1` keeps a pre-fix regression to ~1s instead of ~4 minutes of backoff.
- **Permanent — `tests/test_trace.py`: `test_sink_failure_does_not_drop_response`.** Block the trace path at runtime and send one ordinary request. What this actually guards: the `log_trace` on `do_POST`'s response path (outside the retry loop) raising and dropping an otherwise-successful response. The "exactly one upstream request" assertion holds both pre- and post-fix here — this is a *response-drop* gate; the misclassification gate is the test above.
- **Permanent — `tests/test_trace.py`: `test_sink_warning_rate_limit`.** Rapid consecutive failures produce exactly one `[proxy] WARNING:` line for that sink; a later failure past the interval reports the suppressed count.
- **Permanent — `tests/test_trace.py`: `test_sink_recovery_notice`.** After a failure episode, the first successful write emits one line containing `resumed` and the dropped-entry count.
- **Permanent — `tests/test_trace.py`: `test_trace_sink_creates_missing_directories`.** A trace path whose parent directory does not exist still writes successfully (guards the `makedirs` self-heal against regression by the Step 2 wrap).
- **Permanent — `tests/test_trace.py`: `test_heartbeat_survives_failed_state_write`.** Block the state path at runtime; at least one heartbeat cycle completes without the thread dying; once the obstruction is removed, the next cycle rewrites `proxy-state.json` with all fields intact. Drive `heartbeat_loop`'s body directly or shorten the interval — do not add a 30s sleep to the suite. *(Mega-audit #21: keep the thread-survival and `resumed`-notice assertions; drop any field-**presence** re-check — `test_heartbeat_preserves_state` at `tests/test_config_keys.py:280` already asserts the field values, and a presence-only copy is strictly weaker.)*
- **Permanent — `tests/test_cli.py`: `test_startup_aborts_on_unwritable_trace_path` and `test_startup_aborts_on_unwritable_state_path`.** Direct server invocation (harness `_start_proxy_server_directly`, `tests/_harness.py:388`), not the CLI. Assert: non-zero exit, no `READY` on stdout, an `ERROR` line naming the path on stderr. These start with the path *already* blocked — the only tests that should.

The five `tests/test_trace.py` tests and the two `tests/test_cli.py` tests are already written and registered by the tester; they could not exercise the change before the environment was refreshed.

<!-- UPDATED 2026-09-10 (revision 2): added from the Phase 6 review. -->

**Added in this revision (Step 4):**

- **Permanent — `tests/test_trace.py`: `test_sink_emission_survives_failing_stderr`** *(new; gates Step 4's first half)*. Replace `sys.stderr` with an object whose `write` raises `OSError(28, 'No space left on device')`, then: with the trace path blocked, `log_trace(...)` must return `False` without raising; `write_state(...)` must return `True` without raising on the success path and `False` without raising on the blocked path; `_note_sink_recovery` after an episode must not raise. This is the reviewer's empirical repro — pre-Step-4 it raised out of the guard and a real `heartbeat_loop` thread died. Restore `sys.stderr` in a `finally`.
- **Harden — `tests/test_trace.py`: `test_sink_warning_rate_limit` and `test_sink_recovery_notice`.** The count assertions are currently substring checks (`"suppressed" in later[0]`, `"3" in lines[0]`), which is how the off-by-one at `server.py:770` passed the first test round — the tester's report recorded `(5 further failures suppressed)` as correct. Parse the integer out of the message and assert the exact expected value. With N rapid failures (one immediate warning, then N-1 silent), a **further** failure after the interval lapses reports `N - 1` suppressed — the silent ones only, never counting the failure being reported. The recovery line reports the episode's total failed writes, which is unaffected by the off-by-one (3 failures → `resumed after 3 failed write(s)`).

<!-- UPDATED 2026-09-11 (revision 4): added from the second review. -->

**Added in revision 4 (Step 5):**

- **Permanent — `tests/test_trace.py`: `test_best_effort_stderr_wrapper`.** Unit: `_BestEffortStderr(<stream that raises on write>)` — `write` returns a length rather than raising, `flush` is silent, and attribute access delegates (check `encoding` and `isatty()` reach the wrapped stream). Also assert a *healthy* wrapped stream still receives the text.
- **Permanent — `tests/test_trace.py` or `tests/test_retry_streaming.py`: `test_retry_path_print_failure_does_not_misclassify`.** Integration, in-process: replace `sys.stderr` with `_BestEffortStderr(<stream that raises on write>)`, drive a request whose path reaches one of the retry-loop prints (a 503 from the mock upstream is the cheapest), and assert the client still receives the expected response and the upstream saw the expected number of requests — no duplicate re-issue from a misclassified print failure. Restore `sys.stderr` in a `finally`. Note this exercises the wrapper directly; `main()`'s installation of it is covered by the coder's structural check.
- Nothing else installs the wrapper, so the rest of the suite is unaffected by it.

<!-- UPDATED 2026-09-11 (revision 7): Step 7. -->

**Added in revision 7 (Step 7):**

- **Extend — `tests/test_trace.py`: `test_best_effort_stderr_wrapper`.** With the raising stream in place, assert `write(42)` returns `0` and does not raise, alongside the existing `write("hello") -> 5` check. This is the assertion that would have caught the `len()` boundary hole; without it the hole is invisible because `print` only ever passes `str`.
- **Strengthen — `tests/test_cli.py`: `test_startup_abort_exits_one_with_failing_stderr`** *(user-confirmed: the guarded outcome is the behaviour they want, and it currently has no enforcement — the test passes with the guard removed)*. Add an assertion on the child's **real fd 2** — the captured subprocess stderr, which the child's `_Raising()` never touches because it replaces `sys.stderr` only at the Python level. With the guard, nothing is written there: the print raises inside `try/except Exception: pass`, is swallowed, and `sys.exit(1)` runs. Without it, the `OSError` propagates out of `main()`, the interpreter cannot write the traceback to the `_Raising()` stream, and CPython dumps its own internals to fd 2 — measured at 189 bytes: `object address`, `object refcount`, `object type name: OSError`, `object repr`, `lost sys.stderr`. Assert that dump is absent (e.g. `"lost sys.stderr" not in stderr and "object repr" not in stderr`), which is precisely what discriminates the guarded path from the unguarded one.

**Tests to investigate for retirement:**

- No test obsolescence identified. Evidence: no existing test starts a server with an unwritable trace or state path — the only unwritable-path tests target `PROXY_FEATURE_COMPAT_FILE` (`tests/test_compat.py:751`), which stays out of scope with its own existing guard. The harness sets `PROXY_TRACE_FILE`, `PROXY_STATE_FILE`, and `PROXY_FEATURE_COMPAT_FILE` to session temp paths at module load, so the new startup check passes for every existing test.

**Retirement procedure:** For each candidate, verify the test exercises code being removed/changed. If obsolete: delete and note in session report. If still valid: document why in session report.

## Summary

Two background sinks in `server.py` are unguarded, and one of them fails in a worse way than "missing try/except" suggests.

**Problem.** `write_state` (`server.py:743`) is called from `heartbeat_loop` (`server.py:1339`) with no handler: one `OSError` (disk full, permissions, path replaced by a file, a Windows `os.replace` blocked by another process holding the target) terminates the heartbeat thread permanently. `log_trace` (`server.py:794`) is called from 52 sites with no handler. Inside `_forward_core`'s retry loop those calls sit within `except (socket.error, ConnectionError, OSError)` (`server.py:2112`) — and `socket.error` *is* `OSError` in Python 3 — so a trace-write failure is misclassified as a network failure. The loop then either re-issues the upstream POST (a silent duplicate request when the response was already streamed, with the trace log — the thing that would have shown it — broken) or returns status `0` with a synthesized `upstream_unreachable` body for a request the provider answered successfully.

**Approach.** Make the sinks incapable of raising, and keep startup loud.

```
startup:  write_state()/write_start_marker() -> False -> ERROR + sys.exit(1)   [fail fast]
runtime:  log_trace()/write_state() -> guarded -> warning (rate-limited) -> continue
```

Key design points, all confirmed with the user in Phase 3:

1. **Guard the sink, not the call sites.** One guard inside each function covers all 52 `log_trace` call sites and the heartbeat, and it removes every *sink-originated* raise into the retry loop's catch at `server.py:2112`. It is **not** the whole story: the loop's own diagnostic prints were a second, independent path into that same catch, closed by Step 5's stream-level `_BestEffortStderr` rather than by the guard. The accepted streaming client-write residual (a non-`_DISCONNECT_ERRORS` `OSError` after headers are sent) remains, as documented in CLAUDE.md's gotchas.
2. **No error taxonomy.** Broad `except Exception`, one behavior: record and continue. No per-exception-type branches.
3. **Sinks return `True`/`False`.** Runtime callers ignore the value; only the two startup call sites act on it. This mirrors the existing `_persist_compat_state_locked` precedent (`server.py:1076`), which already returns a bool for the same reason. It also means startup uses the *real write* as its check — no synthetic preflight that only tests openability.
4. **Rate-limited on stderr, with a recovery line.** First failure emits immediately; further failures emit at most once per 60s with a suppressed count; the first success after an episode emits one `resumed` line carrying the dropped-entry count. stderr is the only channel with no dependency on the failing artifact (a trace event cannot report a trace-sink failure); it lands in `proxy-stderr.log`.
5. **No recovery machinery.** `log_trace` holds no file handle — every call re-runs `makedirs` and `open(..., "a")` (`server.py:797`, `:799`). A deleted file, deleted directory, transient lock, or freed disk all self-heal on the next call with no state to reset and no human intervention. Only permanent environment faults (ACL never fixed, path replaced by a directory) persist, and no in-process logic could fix those — the startup check catches them when they exist at boot.

**Alternatives rejected.** A separate startup preflight function (more code, weaker check — openability rather than the real write). Narrowing the retry-loop catch at `server.py:2112` instead of guarding the sink (it would not have been sufficient — the diagnostic prints were a second path into that catch, which the Step 5 stream wrapper closes for both; narrowing has a broader blast radius and would leave the prints raising). Buffering dropped trace entries for replay (bounded-memory and replay semantics for a personal proxy — out of proportion). Differentiated handling per exception type (explicitly declined by the user).

**Explicitly out of scope.** `cli.py`'s `_write_state` (`cli.py:291`) and `prune_trace_file` — foreground operations where a loud failure is correct. `_persist_compat_state_locked` — already guarded, and its failure reporter becomes safe for free once `log_trace` stops raising. The stale `last_heartbeat` field and the CLI never reading it. The fixed `.tmp` temp-path name in `write_state`.

**Honest cost.** Entries emitted during an outage are lost, not buffered. The `resumed` line's count is the record of the gap.

## Repo Mode

Public

*Detected at plan creation. Determines: plan archival path, commit-message content, staged files.*

## Document Overrides

An empty table means zero tolerance — every documented rule is in force.

| Document | Rule Overridden | Reason |
|----------|----------------|--------|

## Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| Fail-fast aborts startup where the trace/state path is *temporarily* unwritable at boot (network mount, synced folder). | Proxy cannot start until the path is writable. | The `ERROR` line names the exact path and the `WARNING` above it carries the sanitized cause; the CLI prints the stderr tail. `PROXY_TRACE_FILE`/`PROXY_STATE_FILE` can point elsewhere. |
| `except Exception` in the sinks can present a programming error (e.g. a non-serializable entry raising `TypeError`) as a write failure. | One trace entry dropped. | The warning carries the sanitized exception text, so a `TypeError` is visible as such; the dropped count is reported on recovery. Accepted — narrowing would contradict the agreed "record everything, don't differentiate" rule. |
| Return-type change (`None` → `bool`) on two widely-called functions. | None identified. | Every existing caller discards the return value; verified by reading all call sites. |

## Proposed Changes

1. **Step 1:** Add the sink-failure recording helper — `SINK_WARN_INTERVAL`, `_sink_warn_lock`, `_sink_warn_state`, `_warn_sink_failure(sink, exc)`, `_note_sink_recovery(sink)` — after the `STATE_FILE` constant block, before `write_state`.
   → coder verify (auto): all five names defined at module level in `server.py`; no new imports
   → tester verify: `test_sink_warning_rate_limit` and `test_sink_recovery_notice` pass — one warning per interval with suppressed count, one `resumed` line per episode

2. **Step 2:** Guard `log_trace` (`:794`) and `write_state` (`:743`) with `except Exception`; each returns `True` on success (after `_note_sink_recovery`) and `False` on failure (after `_warn_sink_failure`); statement order, locking, `makedirs`, and the POSIX chmod block unchanged.
   → coder verify (scripted): `python ./tmp/verification/2026-09-10-guard-trace-state-sinks-step2.py` exits 0
   → tester verify: `test_sink_failure_does_not_drop_response` passes — correct 200 body and exactly one upstream request with a blocked trace path; `test_trace_sink_creates_missing_directories` passes

3. **Step 3:** Fail fast at startup — `main()` checks the return of `write_state(state)` (`:4650`) and `write_start_marker()` (`:4654`); on `False`, print an `ERROR` line naming the path to stderr and `sys.exit(1)`.
   → coder verify (auto): both call sites guarded by `if not ...` with `sys.exit(1)`; `print("READY", flush=True)` still follows both; no other statement in `main()` changed
   → tester verify: `test_startup_aborts_on_unwritable_trace_path` and `test_startup_aborts_on_unwritable_state_path` pass — non-zero exit, no `READY`, `ERROR` on stderr

<!-- UPDATED 2026-09-10 (revision 2): added from the Phase 6 review. -->
4. **Step 4:** Make the guard's own emission non-raising and fix the suppressed count — wrap the two `print(..., file=sys.stderr)` calls in `_warn_sink_failure` (`server.py:779-780`) and `_note_sink_recovery` (`:789-790`) in `try/except Exception: pass`; correct the off-by-one so the "further failures suppressed" number excludes the failure being reported (`:769-770`).
   → coder verify (auto): both prints sit inside `try/except Exception`; `since_warn` is not incremented for the failure whose emission uses it
   → tester verify: a stderr whose `write` raises `OSError(28)` leaves `log_trace`/`write_state` non-raising and the heartbeat thread alive; the rate-limit test asserts the exact suppressed count

<!-- UPDATED 2026-09-11 (revision 4): added from the second review, user-selected option A. -->
5. **Step 5:** Make runtime diagnostics best-effort — add a small `_BestEffortStderr` stream wrapper (`write`/`flush` swallow `Exception`, everything else delegates) and install it in `main()` on `sys.stderr` once, immediately after the two fail-fast checks. Every `print(..., file=sys.stderr)` downstream of that point becomes non-raising — which closes the misclassification path through the retry loop's own diagnostic prints without touching the retry loop or enumerating call sites.
   → coder verify (auto): `_BestEffortStderr` defined at module level with `write`/`flush`/`__getattr__`; `main()` assigns `sys.stderr` to it after the `write_start_marker()` fail-fast block and before the server is constructed — so both fail-fast `ERROR` messages and the `READY` stdout marker are unaffected
   → tester verify: with `sys.stderr` replaced by `_BestEffortStderr(<stream that raises on write>)`, a request whose path prints (e.g. the 429/503 retry notice) still returns the upstream's response and the upstream sees no extra request

<!-- UPDATED 2026-09-11 (revision 5): from the mega-audit's Medium findings #13 and #5. -->
6. **Step 6:** Close the two remaining I/O-safety gaps — wrap each of `main()`'s two fail-fast `ERROR` prints in `try/except Exception: pass` so the `sys.exit(1)` path is deterministic even when stderr is the failing artifact (mega-audit #13); and mirror `log_trace`'s `if d:` directory guard in `write_state` so an empty or bare `PROXY_STATE_FILE` cannot make `os.makedirs("")` abort startup with a misleading "not writable" error (mega-audit #5).
   → coder verify (auto): both fail-fast prints are inside `try/except Exception` and still reach `sys.exit(1)`; `write_state` has the same `if d:` guard as `log_trace`
   → tester verify: `PROXY_STATE_FILE` set to a bare relative filename with a writable cwd starts the server and writes the state file; a failing stderr still yields exit code 1 with no `READY`

<!-- UPDATED 2026-09-11 (revision 7): user approved the generic-size fix for the wrapper's failure return. -->
7. **Step 7:** Make the stderr wrapper's failure return total — in `_BestEffortStderr.write`, return `len(data) if hasattr(data, "__len__") else 0` instead of a bare `len(data)`, so a non-sized payload can no longer raise `TypeError` out of the wrapper that exists to never raise.
   → coder verify (auto): the `except` branch uses the guarded form; success path, `flush`, `__getattr__`, and the installation point are untouched
   → tester verify: `test_best_effort_stderr_wrapper` extended — `write(42)` over a raising stream returns 0 without raising; `write("hello")` still returns 5

## Guidance for Planner

Documentation tasks you will execute yourself (not the coder):

**Files to modify:** `CLAUDE.md`, `README.md`

- **When:** after coder finishes
- **What to sync:**
  <!-- UPDATED 2026-09-11 (revision 5): from the mega-audit's Medium findings #27 and #25. -->
  - **Re-count the suite after Step 5 and Step 6's tests land** and update the figure in the Gotcha at `CLAUDE.md:477` ("284 tests across 14 files" → the new total; the file/module counts should not change). Mega-audit #27.
  - **Document the Step 5 `_BestEffortStderr` wrapper** in the same Architecture/Gotchas material: once installed (after the fail-fast checks), runtime diagnostics are best-effort process-wide — a failing stderr silently drops *every* later diagnostic line, not just the sink warnings. This is the deliberate counterpart to the fail-fast ERROR prints, which stay loud by running before the wrapper exists. Mega-audit #25.
  - `CLAUDE.md` — Architecture: the sink guard, the `True`/`False` return contract, the rate-limited warning + recovery line, and the startup fail-fast. Gotchas: the new error-degradation policy (fail fast at startup, degrade at runtime), the deliberate loss of entries during an outage, and the note that no recovery logic is needed because both sinks re-open per call. Remove or update the stale "Two deferred issues remain" wording in Future Work, and drop `unguarded-write-state-log-trace-oserror` from Unresolved Deferred Issues once the fix lands.
  - `README.md` — user-facing: startup aborts if the trace or state path is not writable; at runtime a failing trace/state write degrades with a rate-limited warning on stderr rather than stopping the proxy; entries during an outage are lost and the recovery notice reports the count.
  <!-- UPDATED 2026-09-10: added from the stale-non-editable-install issue. -->
  - `CLAUDE.md` **Build** section — reconcile the documented install step with the environment. Until 2026-09-10 the package was installed non-editable (a site-packages snapshot), so `import claude_retry_proxy`, `python -m claude_retry_proxy.server`, and therefore the running proxy all executed a frozen copy while `src/` edits had no effect — the mismatch that invalidated this plan's first test round and made the CLI's `start`/`stop`/`status` commands run stale code. It is now editable (`pip install -e .`). State that plainly, and note the trade-off: with an editable install any `src/` edit reaches the live proxy on its next restart, with no install gate.

## History

One row per event (spec revision / mega-audit / review / implementation round).

| Date | Event | Conclusion | Dismissed |
|------|-------|------------|-----------|
| 2026-09-10 | Initial plan | 3 steps in `server.py` only: sink-failure recording helper, broad guards on `log_trace`/`write_state` returning bool, startup fail-fast on both returns. Mega-audit not triggered (3 steps, 1 source file). | — |
| 2026-09-10 | Spec revision (/update-plan) | Coder reported all 3 steps complete; install issue resolved by the user's editable reinstall (`pip install -e .`). Revision: corrected the Guidance for Tester startup-block contradiction (start healthy, block at runtime), re-framed `test_sink_failure_does_not_drop_response` to what it actually guards, added `test_trace_write_failure_does_not_duplicate_upstream_request` to cover the retry misclassification, enumerated `write_start_marker`'s bool return in Step 2, added the environment precondition, and added the CLAUDE.md Build-section reconciliation. Audit trigger not met (1 issue resolved, 1 step text-changed). [coder report](./tmp/reports/2026-09-10-guard-trace-state-sinks-coder-2026-09-10.json) \| [tester issue](./tmp/reports/2026-09-10-guard-trace-state-sinks-tester-guidance-startup-block-contradiction.json) \| [install issue](./tmp/reports/2026-09-10-guard-trace-state-sinks-stale-non-editable-install.json) | — |
| 2026-09-10 | Test round | SUCCESS: 283/283 pass (1 pre-existing benign warning), 8 new tests created. All 8 were additionally run against HEAD's pre-fix `src/` and failed, with failure modes matching the plan's predictions — the tests gate the requirement rather than passing vacuously. All four Issue Log rows closed. [tester report](./tmp/reports/2026-09-10-guard-trace-state-sinks-tester-2026-09-10.json) | — |
| 2026-09-10 | Review | Verdict "Issues found — non-blocking"; no Critical, so the commit gate passed. 1 Warning + 3 Suggestions; the Warning (guard's own stderr emission unguarded, verified to kill a real `heartbeat_loop` thread under `OSError(28)`) and two Suggestions (suppressed-count off-by-one; substring count assertions) are filed as `review-*` issues and fixed by revision 2. [review report](./tmp/reports/2026-09-10-guard-trace-state-sinks-review-2026-09-10.json) | [`review-harness-port-probe-10s`](./tmp/reports/2026-09-10-guard-trace-state-sinks-review-2026-09-10.json) (deferred — test throughput, not correctness), [`hunch-rate-limit-flapping`](./tmp/reports/2026-09-10-guard-trace-state-sinks-review-2026-09-10.json) (plan-conformant by design), [`hunch-read-state-dead-code`](./tmp/reports/2026-09-10-guard-trace-state-sinks-review-2026-09-10.json) (pre-existing) |
| 2026-09-10 | Spec revision (/update-plan) | Revision 2 (user chose to iterate rather than accept): added Step 4 — make the guard's own emission non-raising and fix the suppressed count — plus the tester's stderr-failure test and exact-count assertion hardening. Audit trigger not met (steps 2, files 0). | — |
| 2026-09-11 | Test round | SUCCESS: 284/284 pass (1 pre-existing benign warning). Step 4 implemented; the new stderr test and the hardened rate-limit assertion were verified to gate it by running against a reconstructed pre-Step-4 copy of `src/` (working tree untouched) — the stderr test failed there with four errors including a real heartbeat thread death, and the rate-limit assertion reported 5 where 4 is correct. All three `review-*` rows closed. Two deferred items remain open by design: the harness port-probe throughput suggestion and the `read_state()` dead-code hunch. [coder report](./tmp/reports/2026-09-10-guard-trace-state-sinks-coder-2026-09-10-2.json) \| [tester report](./tmp/reports/2026-09-10-guard-trace-state-sinks-tester-2026-09-11.json) | — |
| 2026-09-11 | Review | Second review (Step 4 delta). Verdict "Issues found — non-blocking"; no Critical, so the commit gate passed. Confirmed the Step 4 wrap closes the first review's Warning in every realistic path (OSError/RuntimeError/MemoryError, flush-only failure, `sys.stderr = None`), the suppressed-count arithmetic across all five scenarios, and the new assertions as genuinely gating; independently ran `tests/test_trace.py` (14/14) and `tests/test_cli.py` (12/12) and counted 284 registered tests. Filed 1 Warning (the retry-loop's own diagnostic prints still reach the misclassification) and 2 Suggestions (both inaccuracies in the planner's new CLAUDE.md/README text, corrected by the planner the same round). [review report](./tmp/reports/2026-09-10-guard-trace-state-sinks-review-2026-09-11.json) | [`hunch-broad-try-masks-message-bugs`](./tmp/reports/2026-09-10-guard-trace-state-sinks-review-2026-09-11.json), [`hunch-codegraph-11mb-unpublished`](./tmp/reports/2026-09-10-guard-trace-state-sinks-review-2026-09-11.json) (flagged to the user — pre-commit `.gitignore` decision, not a code issue) |
| 2026-09-11 | Spec revision (/update-plan) | Revision 4 (user selected option A): added Step 5 — a module-level `_BestEffortStderr` installed once in `main()` after the fail-fast blocks, so no runtime print can raise into the retry loop — plus the tester's wrapper and retry-path tests and a structural placement check. **Mega-audit trigger fired** (9 issues resolved, 3 steps changed since counters reset); the 11-lens audit runs per the Phase 5 workflow. | — |
| 2026-09-11 | Mega-audit (post-implementation, iteration 1 of 3) | 29 findings, 0 High / 10 Medium / 19 Low; verdict "Issues found — non-blocking", all 11 lenses succeeded. Fixed in revision 5: **#9** (Summary/Alternatives contradicted Step 5 about whether the guard alone closed the misclassification), **#13** (the two fail-fast `ERROR` prints are themselves unguarded and lose the diagnostic under full disk — now wrapped, and the Risks row corrected), **#5** (write_state calls `os.makedirs` with no `if d:` guard, unlike `log_trace`, so an empty or bare `PROXY_STATE_FILE` aborts startup with a misleading "not writable" error), **#8** (prose↔metadata file-sync markers missing in the tester and planner sections), **#21** (the heartbeat test's field-presence block duplicates a stronger existing check), **#27** (CLAUDE.md's test count will drift once Step 5's tests land — added to What-to-sync). Lows folded in while editing: #10 (Step 5's print-site labels), #11 (line-reference note), #12 ("~25 sites" → 52). [report](./tmp/reports/2026-09-10-guard-trace-state-sinks-mega-audit-2026-09-11.json) | [#4](./tmp/reports/2026-09-10-guard-trace-state-sinks-mega-audit-2026-09-11.json) (the retry-path prints are exactly what Step 5's stream wrapper covers — the finding's per-site resolution is the rejected alternative; unimplemented only because the audit ran before the Step 5 coder round), [#20](./tmp/reports/2026-09-10-guard-trace-state-sinks-mega-audit-2026-09-11.json) (deliberate separation — the two trace-blocked tests gate different call sites), [#22](./tmp/reports/2026-09-10-guard-trace-state-sinks-mega-audit-2026-09-11.json) + [#23](./tmp/reports/2026-09-10-guard-trace-state-sinks-mega-audit-2026-09-11.json) (audit-before-coder-round timing artifacts, prescribed by the Phase 5 workflow), [#24](./tmp/reports/2026-09-10-guard-trace-state-sinks-mega-audit-2026-09-11.json) (no rollback section — all changes are additive and revert with the commit), [#19](./tmp/reports/2026-09-10-guard-trace-state-sinks-mega-audit-2026-09-11.json) (exception text is not newline-normalized — cosmetic, the warning is not machine-parsed), [#26](./tmp/reports/2026-09-10-guard-trace-state-sinks-mega-audit-2026-09-11.json) (sanitize_error call path), and the remaining Low-severity defects/oversights acknowledged but not actioned |
| 2026-09-11 | Test round | SUCCESS: 288/288 pass (1 pre-existing benign warning). Steps 5 and 6 implemented; four tests added and the mega-audit #21 field-presence block dropped. Gate check against a reconstructed pre-Step-5/6 tree: the wrapper unit test, the retry-path integration test (the `OSError` escaping `forward_request`, matching the second review), and the relative-state-path test all fail there — three genuine gates. The fourth, `test_startup_abort_exits_one_with_failing_stderr`, passes both pre- and post-change: CPython's excepthook also fails silently on the raising stderr, so Step 6's print wrap is internal determinism, not observable behavior — recorded honestly by the tester rather than claimed as a gate. Two tester-flagged items filed as `Open` (wrapper `len()` boundary hole; three-way test fixture duplication). [coder report](./tmp/reports/2026-09-10-guard-trace-state-sinks-coder-2026-09-11.json) \| [tester report](./tmp/reports/2026-09-10-guard-trace-state-sinks-tester-2026-09-11-2.json) | — |
| 2026-09-11 | Spec revision (/update-plan) | Revision 7: user approved the generic-size fix for the wrapper's `len()` boundary hole → added Step 7 (`len(data) if hasattr(data, "__len__") else 0`) plus the tester assertion that would have caught it. #2's Step 6 print wrap stays as implemented (user confirmed the guarded outcome — print swallowed, `sys.exit(1)` runs, nothing written — is the behaviour wanted), and gains the missing assertion: the abort test must reject the CPython `lost sys.stderr` dump that the unguarded path emits to the real fd 2, so the guard is now enforced rather than merely present. The fixture-duplication claim was **corrected**: it is two copies (the third test is a different in-process design), and it is left deliberately. Audit trigger not met (2 resolved, 1 step). | — |
| 2026-09-11 | Test round | SUCCESS: 288/288 pass (1 pre-existing benign warning; total unchanged — this round strengthened two tests and added none). Step 7 landed as a one-line change plus a two-line explanatory comment the coder disclosed as beyond the literal instruction (kept: the bare-`len` form had already been "simplified" into a defect once, and the comment is what stops it recurring). Both strengthened tests were verified against a reconstructed pre-change tree and **both now gate**: the wrapper test fails pre-Step-7 with the exact `TypeError`, and the abort test — which passed either way last round — now fails pre-Step-6 on the CPython dump, closing `startup-abort-guard-not-gated`. Root cause of the earlier blind spot, now precise: the unguarded path emits no `Traceback` line, because the excepthook dies on the raising stderr and CPython falls back to dumping the object repr plus `lost sys.stderr` to fd 2 — which is what the new assertion keys on. The tester also retracted the three-copy fixture claim. CLAUDE.md's test count was already 288 (the tester read a stale copy); the `_BestEffortStderr` note's now-obsolete `TypeError` limitation was removed by the planner. [coder report](./tmp/reports/2026-09-10-guard-trace-state-sinks-coder-2026-09-11-2.json) \| [tester report](./tmp/reports/2026-09-10-guard-trace-state-sinks-tester-2026-09-11-3.json) | — |
| 2026-09-11 | Review | Third review (Steps 5–7 delta). Verdict "Issues found — non-blocking": 0 Critical, 0 Warning, 4 Suggestions — **commit gate passed**. Independently re-ran the full suite (288/288), the Step 2 script (16/16), and re-verified both strengthened tests as gating against reconstructed pre-change trees. Confirmed clean: wrapper delegation, `print`'s two-call pattern, `flush`, the dynamic `sys.stderr` lookup (incl. a thread-excepthook probe), the single installation point, no new imports, Steps 1–4 untouched, and the coder's disclosed comment admissible. The 4 Suggestions were accepted as documented caveats by the user's `/update-and-commit` decision. [review report](./tmp/reports/2026-09-10-guard-trace-state-sinks-review-2026-09-11-2.json) | [`sugg-len-total-residual`](./tmp/reports/2026-09-10-guard-trace-state-sinks-review-2026-09-11-2.json) (a payload whose own `__len__` raises still propagates; unreachable — the CLAUDE.md claim was corrected to say "covers everything `print` can produce" rather than "total"), [`sugg-empty-state-path-stray-tmp`](./tmp/reports/2026-09-10-guard-trace-state-sinks-review-2026-09-11-2.json) (`PROXY_STATE_FILE=""` now returns False one step later and leaves a stray `.tmp` in cwd; still a clean fail-fast abort, and only reachable via a misconfigured env var), [`sugg-startup-prints-unguarded`](./tmp/reports/2026-09-10-guard-trace-state-sinks-review-2026-09-11-2.json) (24 startup-path stderr prints run before the wrapper; closing it would move the wrapper earlier and silence the startup diagnostics deliberately kept loud — a design trade, not a defect), [`sugg-abort-test-cpython-coupling`](./tmp/reports/2026-09-10-guard-trace-state-sinks-review-2026-09-11-2.json) (the abort assertion keys on CPython's `lost sys.stderr` / `object repr` wording; gates today on 3.14.3, could de-sensitise on a wording change) |

## Plan Metadata

```json
{
  "plan_id": "2026-09-10-guard-trace-state-sinks",
  "steps": ["Step 1: Add the sink-failure recording helper", "Step 2: Guard log_trace and write_state", "Step 3: Fail fast at startup", "Step 4: Make the guard's own emission non-raising and fix the suppressed count", "Step 5: Make runtime diagnostics best-effort", "Step 6: Close the two remaining I/O-safety gaps", "Step 7: Make the stderr wrapper's failure return total"],
  "coder_files": ["src/claude_retry_proxy/server.py"],
  "tester_files": ["tests/test_trace.py", "tests/test_retry_streaming.py", "tests/test_cli.py"],
  "doc_files": ["CLAUDE.md", "README.md"],
  "verification_scripts": ["./tmp/verification/2026-09-10-guard-trace-state-sinks-step2.py"],
  "repo_mode": "Public",
  "document_overrides": []
}
```

## Audit Accumulation

*Counters reset when mega-audit runs. Used by Phase 5 entry trigger.*

| Counter | Value | Last Updated |
|---------|-------|--------------|
| issues_resolved_since_audit | 4 | 2026-09-11 |
| steps_changed_since_audit | 1 | 2026-09-11 |
| files_changed_since_audit | 0 | 2026-09-11 |

## Documentation

- [CLAUDE.md](CLAUDE.md) — Architecture + Gotchas: sink guard contract, startup fail-fast, runtime degradation policy, deferred-issue table.
- [README.md](README.md) — user-facing startup/runtime I/O failure behavior.

## Final Results

**Status: COMPLETED** — 2026-09-11

**What was built.** Seven steps in `src/claude_retry_proxy/server.py`, all in one file, no new modules:

1. A sink-failure recorder (`SINK_WARN_INTERVAL`, `_sink_warn_lock`, `_sink_warn_state`, `_warn_sink_failure`, `_note_sink_recovery`) that reports at most one line per 60s per failure episode with a suppressed count, plus a `resumed after N failed write(s)` line when writes recover.
2. `log_trace` and `write_state` guarded with a broad `except Exception`, returning `True`/`False` and never raising into their callers — which is what removes the retry-loop misclassification at the `except (socket.error, ConnectionError, OSError)` clause.
3. Startup fail-fast: `main()` acts on both startup sink returns and exits before `READY` if either path is unwritable.
4. The guard's own emission made non-raising (`try/except` around the two helper prints), and the suppressed-count off-by-one fixed.
5. A process-global `_BestEffortStderr` installed once in `main()` after the fail-fast checks, so no runtime `print(..., file=sys.stderr)` — including the retry loop's own notices — can raise into the request path.
6. `write_state`'s `os.makedirs` given the `if d:` guard `log_trace` already had, and the two fail-fast `ERROR` prints wrapped so the abort path is deterministic.
7. `_BestEffortStderr.write`'s failure return made generic (`len(data) if hasattr(data, "__len__") else 0`).

**Files changed:** `src/claude_retry_proxy/server.py` (implementation, +~200 lines), `tests/test_trace.py`, `tests/test_retry_streaming.py`, `tests/test_cli.py` (13 new tests, 2 strengthened), `CLAUDE.md`, `README.md` (documentation).

**Test results.** 288/288 passing across 14 files, 0 failed, 0 skipped, with one pre-existing benign warning (`test_trace_markers`' missing `proxy_stop` marker) unchanged by this plan. Every gate the plan added was verified to *fail* against a reconstructed pre-change copy of `src/` before it was accepted — six tests across the four rounds were shown to genuinely gate rather than pass vacuously, including the retry-misclassification test (where the pre-fix `OSError` escaped `forward_request` entirely) and the abort test that initially passed either way.

**Review history.** Four independent gates: review #1 (1 Warning, 3 Suggestions), mega-audit (11 lenses: 0 High, 10 Medium, 19 Low — its trigger fired only once, at 9 resolved issues and 3 changed steps), review #2 (1 Warning, 2 Suggestions), review #3 (0 Critical, 0 Warning, 4 Suggestions). Every Warning was fixed; the Mediums were fixed; the Lows and Suggestions are dispositioned in the History table's Dismissed cells.

**Issue Log:** 14 rows — 13 Resolved, 1 Won't Fix by explicit user decision (`test-fixture-duplication`).

**Known caveats** (accepted, final-review Suggestions — none affects the shipped behaviour's correctness):

- `_BestEffortStderr.write`'s failure return is generic for any payload lacking `__len__`, but a payload whose *own* `__len__` raises still propagates. Nothing in this codebase writes such an object to stderr.
- `PROXY_STATE_FILE=""` now fails one step later than before and leaves a stray `.tmp` in the server's cwd; it is still a clean fail-fast abort, reachable only via a misconfigured env var.
- 24 other startup-path stderr prints run before the wrapper is installed, so a broken stderr during startup still aborts (exit 1) rather than degrading; closing that would move the wrapper earlier and silence the startup diagnostics deliberately kept loud.
- The abort test asserts on CPython's `lost sys.stderr` / `object repr` wording; it gates on 3.14.3 but could de-sensitise on an interpreter wording change.
- Deferred by design, from an earlier review: the harness port-probe item that costs ~21s per suite run.

## Cross-References to Prior Plans

| Prior Plan | Deferred Issue | Resolution |
|------------|---------------|------------|
| 2026-09-07-break-up-large-files | `unguarded-write-state-log-trace-oserror` | Closed by this plan: `log_trace`/`write_state` are now guarded (Step 2), the heartbeat thread survives a failing state write, and the retry-loop misclassification is removed — gated by `test_trace_write_failure_does_not_duplicate_upstream_request` and `test_heartbeat_survives_failed_state_write`, both verified to fail against pre-fix code. |
