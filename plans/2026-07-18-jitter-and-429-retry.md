# Plan: Add jitter to retry backoff + retry on 429

**Project:** D:\proj\claude-retry-proxy
**Plan ID:** 2026-07-18-jitter-and-429-retry
**Created:** 2026-07-18

## Changelog
- **2026-07-18**: Initial plan.
- **2026-07-18**: Revision after mega-audit iter 1 (6 High, 15 Med, 21 Low).
  Thread-local RNG; unbiased rounding; `resp.read()` before close on retry
  path; doc checklist expanded (test counts); tester trace-file sketch;
  fixed stale line refs and `ALL_TESTS` var name; pre-existing
  `_shutting_down`-during-sleep issue logged as Open and scoped out.
- **2026-07-18**: Revision after mega-audit iter 2 (11/12 lenses cached;
  doc-gap-finder killed mid-run as a straggler — its iter-1 findings already
  addressed). 6 High findings. Corrected the core arithmetic error: with
  ±25% integer jitter, `base=1` and `base=2` get ZERO de-sync (the ±0.5s
  range lands in one integer bucket regardless of rounding mode). Known-edge
  doc, Step-1 scripted assertion, and tester assertion all corrected to
  treat `base ∈ {1,2}` as degenerate and assert de-sync only from `base ≥ 3`.
  Added `base <= 0` guard. Added a Rollback section. User confirmed Option B
  (keep integer rounding, fix docs) over sub-second jitter.
- **2026-07-18**: Relocated plan to `tmp/plans/` (planner.md convention) from
  the session-scoped `~/.claude/plans/` path; split Design content into the
  companion `2026-07-18-jitter-and-429-retry-design.md` per Phase 4.
- **2026-07-18**: Coder session completed — all 3 steps done, `build_result:
  pass`, zero issues filed. Verified the diff matches the plan spec exactly
  (thread-local `_rng()` + `compute_jittered_delay` with `base<=0` guard and
  `math.floor(base+jitter+0.5)`; merged `429/503` dispatch with `elif`/`else`
  defensive structure; `resp.read()` drained before `conn.close()`; exhaustion
  returns `resp.status`; connection-error branch untouched; only
  `server.py` changed). **Awaiting tester session** — plan not yet finalizable
  (no tester SUCCESS report). Coder self-reported Step-1/Step-2 verification
  scripts and `test_retry_logic` pass; behavioral confirmation is the tester's
  job. See report
  [2026-07-18-jitter-and-429-retry-coder-2026-07-18.json](../reports/2026-07-18-jitter-and-429-retry-coder-2026-07-18.json).
- **2026-07-19**: Tester session + Phase 6 reviewer. Tester: 9/9 pass, 0
  issues (12 CLI tests skipped — live proxy running, URL-swap path unchanged).
  Reviewer: 0 Critical, 1 Warning (unreachable defensive `else` — intentional,
  acknowledged), 4 Suggestions (3 source-docstring staleness → coder
  follow-up; 1 design-doc arithmetic `base=3 → {2,3,4}` correction → planner
  DONE). Planner executed doc updates: `CLAUDE.md` (Purpose, Structure 24→27,
  Architecture, env table, Gotchas worst-case + jitter-degenerate +
  `_shutting_down` note), `README.md` (intro, Why, config, backoff, Features,
  test count 24→27), design doc arithmetic fix. Gate passed.
- **2026-07-19**: Coder Step 4 follow-up: items 1–2 (`server.py` module and
  `forward_request` docstrings) applied successfully. Item 3
  (`tests/test_claude_proxy.py` case-5) blocked by coder core constraint
  "Never touch test directories" — correctly filed as issue. Plan revised:
  item 3 reassigned to tester. No behavioral change.
- **2026-07-19**: Tester Step 4 item 3 applied (`tests/test_claude_proxy.py`
  case-5 docstring updated to mention 429 + jittered). Regression gate:
  4/4 pass. Issue `step4-test-docstring-blocked-by-constraint` resolved.
  Step 4 complete — all three docstring sites synced.

## Introspection Log

| Date | Trigger | Scope | Findings | Verdict |
|------|---------|-------|----------|---------|
| 2026-07-18 | Mega-audit (Phase 4.5), 12 lenses, iter 1 | Full plan + `server.py` retry loop | 42 findings: 6 High, 15 Medium, 21 Low | Revised — see below |
| 2026-07-18 | Mega-audit, iter 2 (11/12 lenses; doc-gap-finder killed mid-run — straggler) | Revised plan, arithmetic re-check | 6 High (4 reality violations on the same arithmetic error + 1 completeness + 1 weak edge-case) | Revised — see "iter 2" below |
| 2026-07-18 | Coder session (`/update-plan`: "coder reports back") | `server.py` implementation, 3 steps | 0 issues filed; build pass; diff verified against plan spec | Coder done — awaiting tester (not finalizable yet) |
| 2026-07-19 | Tester session (`/update-plan`: "tester reports back") | 3 new permanent tests + regression | 9/9 pass, 0 fail, 0 issues filed (12 CLI tests skipped — live proxy running, URL-swap path unchanged by this plan) | Tests green — proceeding to Phase 6 reviewer |
| 2026-07-19 | Reviewer subagent (Phase 6) | Implementation diff, 6 dimensions | 0 Critical, 1 Warning, 4 Suggestions | Gate passed — non-blocking; see "Phase 6 review" below |
| 2026-07-19 | Coder session (`/update-plan`: "coder reports back"), Step 4 | Docstring sync, items 1–2 (`server.py`) | 0 issues; items 1–2 applied successfully. Item 3 (`tests/test_claude_proxy.py`) blocked by coder core constraint "Never touch test directories" — correctly filed as issue. Plan revised: item 3 reassigned to tester. | Step 4 items 1–2 done; item 3 pending tester |
| 2026-07-19 | Tester session (`/update-plan`: "tester reports back"), Step 4 item 3 | Docstring sync, item 3 (`tests/test_claude_proxy.py` case-5) + regression gate | 4/4 pass, 0 fail; item 3 applied; issue `step4-test-docstring-blocked-by-constraint` resolved. All three docstring sites now synced. | Step 4 complete — plan fully finalizable |

### Phase 6 review — findings and disposition (2026-07-19)

Reviewer verdict: **"Issues found — non-blocking"**, 0 Critical → gate passes. Report: [2026-07-18-jitter-and-429-retry-review-2026-07-19.json](../reports/2026-07-18-jitter-and-429-retry-review-2026-07-19.json).

1. **Warning — unreachable `else` in the 429/503 dispatch** (`server.py:305`). This `else` is the defensive branch the mega-audit's defect-tracer lens *explicitly requested* in iter 1 (Med: "change bare `else` to `elif` + defensive `else`"). It's unreachable *today* by design — it exists to catch a future tuple expansion. **Acknowledged, non-blocking.** The reviewer's alternative (`raise AssertionError`) is a reasonable stylistic choice; not changing the implementation for this — the defensive `else` is intentional and documented. Under the 5-Warning threshold; not escalated.
2. **Suggestion — `server.py` module docstring stale** (still "503 only"). **Valid.** Planner-owned — but the docstring lives in a source file, so it's the **coder's** to edit, not mine. Filed as a small coder follow-up below (boundary: planner edits only `CLAUDE.md`/`README.md`/`tmp/plans/`/`doc/`, not `server.py`).
3. **Suggestion — `forward_request` docstring stale.** Same — coder follow-up.
4. **Suggestion — `tests/test_claude_proxy.py` module docstring (line 9) stale; test-count updated but case-5 description not.** This one I *missed* in my checklist (I had CLAUDE.md/README test-counts but not the test file's own docstring). Same boundary — coder follow-up.
5. **Suggestion — design doc claimed `base=3 → {2,3}`, actual is `{2,3,4}`.** **Valid — planner-owned and DONE.** Empirically verified (`set(... for _ in range(200000)) == {2,3,4}`); the `+0.5` half-up shift widens the low end by one bucket. Corrected in the design doc and the plan's two mirroring annotations. Code and the `≥2 distinct values` test assertion are unaffected (3 values still satisfies `≥2`); the assertion's *threshold* was loose enough to pass against the real range. This was a doc inaccuracy I introduced in iter 2 — the iter-2 reality-checker lenses flagged the *rounding* but not this specific off-by-one, and I asserted the wrong set without empirical check. Lesson noted.

**Planner-owned doc updates executed (before Final Results):** `CLAUDE.md` (Purpose, Structure 24→27, Architecture/Server, env table `PROXY_MAX_RETRIES`/`PROXY_MAX_DELAY`, Gotchas worst-case recompute + integer-jitter-degenerate note + `_shutting_down` note), `README.md` (intro, Why, config table, backoff paragraph + worst-case + small-delay note, Features bullet, test count 24→27 + split 12/15), design doc arithmetic correction.

**Coder follow-up (source docstrings — planner cannot edit source):** update the `server.py` module docstring (line 2), `forward_request` docstring (line ~263), and `tests/test_claude_proxy.py` module docstring (line 9) to mention 429 + jittered backoff. Trivial, non-blocking; can be folded into the commit or a one-line follow-up. Not a gate failure.

### iter 2 — High findings and disposition

1. **`base=1` always yields 1, not {0,1}** (reality-checker, 2 findings) — my Known-edge doc claimed `base=1` could produce 0 or 1; the math is `floor([1.25, 1.75]) = 1` always. **FIXED:** doc corrected.
2. **`base=2` always yields 2, not {1,2,3}** (reality-checker, 2 findings) — the ±25% range on `base=2` is only `±0.5`; after the `+0.5` half-up shift, `floor([2.0, 3.0)) = 2` always. This is the **same degenerate collapse** half-up was meant to fix — the failure is the *narrow jitter range* at small bases, not the rounding mode. **FIXED:** doc corrected; `base=2` removed from the multi-value test assertion; de-sync asserted only from `base ≥ 3` (503 reaches `base=4` at attempt 2 → de-sync from the 3rd retry; 429 uses `MAX_DELAY`=30 → de-syncs from the first 429). User confirmed keeping integer rounding (Option B) over sub-second jitter.
3. **Step-1 / tester assertion "base=2 produces ≥2 distinct values" would always fail** (reality-checker, 1 finding) — direct consequence of #2. **FIXED:** assertion now checks `base=3` and `base=4` are multi-value, and `base ∈ {1,2}` are single-value (documents the degenerate case). Added `compute_jittered_delay(0)==0` and `(-5)==0` checks for the guard.
4. **`base=0` / negative guard missing** (edge-case-explorer, 1 finding) — weak (env clamps make `base=0` unreachable today), but the one-line guard is free self-defense. **FIXED:** `if base <= 0: return 0` added.
5. **No rollback plan** (completeness, 1 finding) — distinct from the iter-1 backward-compat/opt-out I rejected. A revert procedure for a behavioral change is legitimate. **FIXED:** added `## Rollback` section.

> doc-gap-finder was killed mid-run in iter 2 (stuck reading, 558 KB transcript, the only straggler). Its iter-1 findings (the two doc-gap Highs) were already folded into the iter-1 revision. No new doc gaps expected; if iter-3 is run, doc-gap-finder's absence is a known coverage gap.

### iter 1 — High findings — disposition

1. **`random.uniform()` is not thread-safe** (oversight-catcher + edge-case-explorer, corroborated) — `forward_request` runs under `ThreadingHTTPServer` worker threads; the module-global Mersenne Twister is not thread-safe. **FIXED in Step 1:** switch to a thread-local `random.Random()` instance.
2. **Banker's rounding kills jitter for small even `base`** (edge-case-explorer) — `round(2.5)==2` in Py3, so `base=2`/`base=4` get zero jitter, undermining the de-sync mitigation exactly where tests run (`PROXY_MAX_DELAY=2`). **FIXED in Step 1:** use `math.floor(base + jitter + 0.5)` (unbiased half-up) instead of `round()`.
3. **CLAUDE.md / README.md don't mention 429 or jitter** (doc-gap-finder, 2 findings) — **Partially valid.** The plan already owned these updates in "Guidance for Planner"; the lens compared current-doc state to the future-plan state. It did surface two genuinely-missed specifics: the CLAUDE.md **Structure** "24 behavioral tests" count (→27) and README's Features/test-count bullets. **FIXED:** both folded into the doc checklist.
4. **No backward-compat / semver / opt-out** (completeness) — **Dismissed as over-engineering.** Pre-1.0 (`0.1.0`) personal local-mode proxy, no user base depending on deterministic timing, no CI pinning a version. A semver bump, deprecation period, and `PROXY_JITTER_ENABLED` opt-out flag are exactly the "flexibility the user didn't ask for" Prime Directive 2 forbids; the plan already explicitly rejected a jitter env-var. Not revised.

### Pre-existing issue surfaced (logged, NOT scoped in)

- **`_shutting_down` not checked during retry `time.sleep`** (oversight-catcher, Med #4) — a request mid-retry sleeps through the full jittered delay per remaining attempt, delaying `/admin/shutdown`. This race exists in the *current* 503/connection-error sleep loop — pre-existing, not introduced here. Per Prime Directive 3, **out of scope**; tracked as a new Open issue in `## Issue Log` for a future hardening plan.

### Medium findings folded into the revision

- `TESTS` → `ALL_TESTS` (actual var name in `tests/test_claude_proxy.py`).
- Stale line refs: `import` insertion `~24`→18; connection-error `315-339`→`315-336`; `test_retry_logic` `635-734`→`635-739`.
- Scripted-verify scripts: clarified the coder creates them.
- Added a `(scripted)` coder check for Step 2 that runs `test_retry_logic` (behavioral gate, not grep-only).
- Tester guidance for `test_retry_429`: pointed at the `test_trace_markers` trace-file pattern with a code sketch.
- Rationale for connection-error asymmetry (one sentence).
- Read/discard response body before `conn.close()` in the 429/503 path (one-liner robustness).

### Acknowledged-but-not-revised (Medium/Low, non-blocking)

- Med #5 (jitter ineffective for `base` < 3) — subsumed by the High #2 rounding fix; remaining `base=1` edge documented in Step 1.
- Med #9 (`log_trace` lock on retry critical path) — pre-existing, not introduced here; noted.
- Med #11 / #13 (fragile-invariant comment on `last_status` vs `resp.status`) — cosmetic; the exhaustion `return` already uses `resp.status` explicitly.
- The 21 Low findings are line-number nits and stylistic suggestions; not individually enumerated here, available in the audit report at `./tmp/reports/2026-07-18-jitter-and-429-retry-mega-audit-2026-07-18.json`.

## Context

The retry proxy's `forward_request` (`src/claude_retry_proxy/server.py`) currently
retries only on HTTP `503` and connection errors, using a pure exponential
backoff (`PROXY_INITIAL_DELAY * 2**attempt`, capped at `PROXY_MAX_DELAY`) with
**no jitter**. Two problems with this:

1. **No jitter → thundering herd.** When the upstream returns 503, every
   concurrent Claude Code session hitting the proxy backs off on the *same*
   deterministic schedule and re-stampedes the upstream in lockstep. This is
   the exact failure mode the proxy exists to ride out; deterministic backoff
   undermines it.
2. **429 not retried.** A `429 Too Many Requests` streams straight back to the
   client with no retry, even though 429 is the more common Claude-API rate
   signal and is, semantically, "try again later."

This plan adds (a) ±25% uniform jitter to every retry delay (rounded to an
integer second), and (b) 429 handling that retries using the maximal delay
(`PROXY_MAX_DELAY`) rather than the exponential attempt delay, otherwise
mirroring the 503 path.

Intended outcome: retries de-synchronize across concurrent sessions, and 429
responses are ridden out like 503s instead of failing the request immediately.

## Scope and explicit decisions

- **Jitter formula:** for a base delay `d`, `final = max(0, floor(d + uniform(-0.25, 0.25) * d + 0.5))`. Unbiased half-up rounding (Python's `round()` is banker's rounding, which collapses small even `base` like 2 and 4 to a constant — see Introspection Log High #2). The 0.25 factor is a fixed constant in code — **no new env var** (user did not request configurability; adding one is scope creep).
- **Thread safety:** jitter draws use a **thread-local `random.Random()` instance**, not the module-global `random.uniform`. `forward_request` runs under `ThreadingHTTPServer` worker threads; the module-global Mersenne Twister is not thread-safe (see Introspection Log High #1).
- **429 delay:** uses `PROXY_MAX_DELAY` (the configured cap) directly — *not*
  `compute_delay(attempt)`. This is the literal reading of "directly using
  the maximal latency." So a 429 at attempt 0 waits `MAX_DELAY` (jittered),
  not `INITIAL_DELAY`.
- **429 retry budget:** identical to 503 — same `PROXY_MAX_RETRIES`, same
  counter increment, same trace shape (with `reason:"429"`). On exhaustion,
  the **429** status is returned to the client (not 503). The connection-error
  branch is **unchanged**.
- **Jitter applies to 429 too** (consistent with "treated like 503"): the
  `MAX_DELAY` value is jittered ±25% and integer-rounded.

## Design

See `2026-07-18-jitter-and-429-retry-design.md` (same directory) for
architecture, data flow, the `compute_jittered_delay` algorithm, the
thread-local `_rng()` accessor, the Known-edge arithmetic (which `base`
values actually de-sync), and the new imports. Not inlined here, per the
planner.md Phase 4 convention — the design doc is for human reading.

## Proposed Changes

### Step 1 — Add imports, thread-local RNG, and `compute_jittered_delay`

In `src/claude_retry_proxy/server.py`:

- Add `import math` and `import random` to the import block (`math` after `json`, `random` after `os` — both stdlib).
- Add the module-level `_rng_local = threading.local()` and the `_rng()` accessor near the other globals (after `PROXY_TRACE_FILE`).
- Define `compute_jittered_delay(base)` immediately after `compute_delay` (after line 211). See the design doc's Algorithm section for the exact body (thread-local `_rng()`, `math.floor(base + jitter + 0.5)`, `max(0, ...)`, `if base <= 0: return 0` guard).

  → coder verify (auto): "`import math` and `import random` present in `server.py` import block; `_rng_local` / `_rng()` defined near module globals; `compute_jittered_delay` defined directly after `compute_delay`, accepts one arg `base`"
  → coder verify (scripted): `./tmp/verification/2026-07-18-jitter-and-429-retry-step1.py` — unit-checks the helper: for `base in [1, 2, 3, 4, 8, 16, 30, 300]`, run 5000 draws each; assert every result is an `int`, `>= 0`, `<= math.floor(base * 1.25 + 0.5)`, `>= math.floor(base * 0.75 + 0.5) - 1`, and that the empirical mean is within ±15% of `base` (catches sign-flip or missing-multiply). **De-sync regression guards (corrected after iter-2 audit — `base=2` is degenerate and must NOT be asserted multi-value):** assert `base=3` produces ≥2 distinct values (`{2,3,4}`), `base=4` produces ≥2 distinct values (`{3,4,5}`), and `base in (1, 2)` each produce exactly 1 distinct value (documents the known degenerate small-delay case). Also assert `compute_delay(0) == PROXY_INITIAL_DELAY` and `compute_delay(100) == PROXY_MAX_DELAY` (unchanged). Assert `compute_jittered_delay(0) == 0` and `compute_jittered_delay(-5) == 0` (the `base <= 0` guard). Assert `_rng()` returns the same object within one thread and distinct objects across two threads (thread-local correctness).
  → tester verify: a new permanent test exercising `compute_jittered_delay` over many draws for bounds, rounding, and the de-sync pattern on small `base` (see Guidance for Tester).

### Step 2 — Wire jitter into the 503 branch

In `forward_request` (lines 270–290), the 503 retry currently does:
```python
delay = compute_delay(attempt)
```
Change to:
```python
delay = compute_jittered_delay(compute_delay(attempt))
```
Everything else in the 503 branch (`retries += 1`, `increment_retried()`,
stderr print, `log_trace` with `delay_s=delay`, `time.sleep(delay)`,
`continue`) stays identical.

  → coder verify (auto): "in `forward_request`, the line computing `delay` in the `if resp.status == 503:` branch calls `compute_jittered_delay(compute_delay(attempt))`; no other line in that branch changed (grep `503` branch shows `reason":"503"` trace unchanged)"
  → coder verify (scripted): run `python tests/test_claude_proxy.py` and assert `test_retry_logic` passes (the existing 503-3x-then-200 test is a behavioral gate — it catches an accidentally-broken exhaustion return, retry counter, or delay formula that a grep check would miss). The script greps the test runner output for the `retry-logic` PASS line and exits non-zero on FAIL. (The coder runs the existing suite here — it does **not** write or modify tests.)
  → tester verify: existing `test_retry_logic` still passes (request succeeds after 3 mock 503s; jitter doesn't break the count-based assertion because `PROXY_MAX_DELAY=2` keeps the test fast regardless of ±25%).

### Step 3 — Add a 429 branch mirroring 503 with maximal delay

In `forward_request`, change the status check from:
```python
if resp.status == 503:
    last_status = 503
    ...
```
to:
```python
if resp.status in (429, 503):
    last_status = resp.status
    if attempt < PROXY_MAX_RETRIES:
        if resp.status == 429:
            delay = compute_jittered_delay(PROXY_MAX_DELAY)
            reason = "429"
        elif resp.status == 503:
            delay = compute_jittered_delay(compute_delay(attempt))
            reason = "503"
        else:  # defensive — the outer tuple is (429, 503); future expansion must add a branch here, not silently fall into 503
            delay = compute_jittered_delay(compute_delay(attempt))
            reason = str(resp.status)
        try:
            resp.read()  # drain response body before close (robustness — see Med #10)
        except (socket.error, OSError):
            pass
        retries += 1
        increment_retried()
        print("[proxy] {} on attempt {}/{}, retrying in {}s".format(
            reason, attempt + 1, PROXY_MAX_RETRIES + 1, delay), file=sys.stderr)
        log_trace({
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "event": "retry",
            "attempt": attempt + 1,
            "delay_s": delay,
            "reason": reason,
            "path": path,
        })
        time.sleep(delay)
        conn.close()
        continue
    else:
        return resp.status, {}, b'', None, time.time() - total_start, retries
```

Notes:
- `last_status = resp.status` (not hardcoded `503`) so exhaustion returns the *actual* upstream status to the client. `resp.status` is an int cached at `getresponse()` time; safe to read even though the body is drained.
- The inner dispatch uses `elif resp.status == 503:` + a defensive `else:` (not `else`-implies-503), so a future expansion of the outer tuple can't silently misroute into the 503 branch (Introspection Log, defect-tracer Med).
- `resp.read()` drains the response body before `conn.close()` — improves both 503 and 429 paths (429 bodies often carry rate-limit diagnostics; leaving them unread can half-close the connection on some Python versions). Wrapped in `try/except` so a read failure doesn't abort the retry.
- The exhaustion `return` uses `resp.status` so a 429 exhaust returns 429, not 503.
- The connection-error branch (lines 315–336) is **untouched**.

  → coder verify (auto): "`if resp.status in (429, 503):` is the status check in `forward_request`; inner dispatch is `if resp.status == 429: / elif resp.status == 503: / else:`; both retry branches set `delay` via `compute_jittered_delay`; 429 uses `PROXY_MAX_DELAY`, 503 uses `compute_delay(attempt)`; `resp.read()` is called before `conn.close()`; exhaustion `return` uses `resp.status` not literal `503`; connection-error `except` block unchanged"
  → coder verify (scripted): `./tmp/verification/2026-07-18-jitter-and-429-retry-step3.py` — static check: reads `server.py`, confirms (a) the status check line is `if resp.status in (429, 503):`, (b) `last_status = resp.status`, (c) the inner dispatch has `elif resp.status == 503:` (not bare `else`), (d) `resp.read()` appears before `conn.close()` in the retry path, (e) the exhaustion return passes `resp.status`, (f) no `if resp.status == 503:` remains, (g) the `except (socket.error, ...)` block still contains `"connection_error"` unchanged.
  → tester verify: a new permanent test `test_retry_429` modeled on `test_retry_logic` — mock upstream returns 429 N times then 200; assert request succeeds, upstream received N+1 calls, and a `retry` trace line with `reason:"429"` exists. Plus a test that a 429 exhaust (mock always returns 429) returns 429 to the client.

### Step 4 — Sync stale source docstrings (reviewer follow-up, post-Phase-6)

**Scope:** documentation-only. **No behavioral change, no logic touched.** Three source docstrings still describe the pre-change behavior (503-only, no jitter). Items 1 and 2 are in `server.py` (coder-owned); item 3 is in `tests/test_claude_proxy.py` (tester-owned). Surfaced by the Phase 6 reviewer (3 of the 4 Suggestions); the planner's `CLAUDE.md`/`README.md`/design-doc updates are already done.

1. **`src/claude_retry_proxy/server.py` module docstring (line 2):**
   - Current: `"""HTTP retry proxy for Claude API. Listens on localhost and forwards requests to the upstream endpoint, retrying on 503 (Service Unavailable) with exponential backoff. Logs all requests to a JSONL trace file.`
   - Change `retrying on 503 (Service Unavailable) with exponential backoff` → `retrying on 429 (Too Many Requests) and 503 (Service Unavailable) with jittered exponential backoff`.
2. **`src/claude_retry_proxy/server.py` `forward_request` docstring (line 263):**
   - Current: `On 503, retries with exponential backoff.`
   - Change to: `On 429 and 503, retries with jittered exponential backoff. 429 uses the maximal delay (PROXY_MAX_DELAY); 503 uses the exponential.`
3. **`tests/test_claude_proxy.py` module docstring (line 9, case-5 description):**
   - Current: `5. Retry logic: 503 retries with exponential backoff`
   - Change to: `5. Retry logic: 429 and 503 retried with jittered exponential backoff`
   - **Owner:** tester (not coder — the coder's core constraints forbid touching test directories).

**Do not** touch any code logic, the `else` defensive branch (see Introspection Log Warning — intentional), or any other line. This is a literal docstring text swap at three named sites. Items 1–2 are in `server.py` (coder); item 3 is in `tests/test_claude_proxy.py` (tester — the coder's core constraints forbid touching test directories).

  → coder verify (auto): "the two named `server.py` docstring lines now mention `429` and `jittered`; no other source line changed (`git diff src/claude_retry_proxy/server.py` shows only the two docstring edits plus the already-committed Step 1–3 changes)"
  → coder verify (scripted): `./tmp/verification/2026-07-18-jitter-and-429-retry-step4a.py` — reads `server.py`, asserts (a) server module docstring contains `429` and `jittered`, (b) `forward_request` docstring contains `429 and 503` and `jittered`, (c) no behavioral source lines changed beyond the docstrings. Exit 0 on pass.
  → tester verify: update the test file docstring (item 3 — `tests/test_claude_proxy.py` line 9, case-5: `5. Retry logic: 429 and 503 retried with jittered exponential backoff`). Re-run the existing suite — `test_retry_logic`, `test_retry_429`, `test_retry_429_exhaust_returns_429`, `test_compute_jittered_delay_bounds` still pass (docstring edits must not change behavior; this is a regression guard, not new tests).

## Guidance for Planner (documentation — owned by planner, not coder)

Doc files to update **after coder finishes, before tester sign-off**:

- **`CLAUDE.md`** (project root):
  - "Architecture / Server" paragraph: note that retries now cover 503 *and* 429, and that backoff has ±25% jitter (thread-local RNG, no lock contention).
  - **Structure** section: update "test_claude_proxy.py 24 behavioral tests" → "27 behavioral tests" (3 new permanent tests added).
  - Environment Variables table: no new vars, but add a one-line note under `PROXY_MAX_DELAY` that the cap is applied pre-jitter (so actual sleeps can exceed it by up to 25%). Add a note under `PROXY_MAX_RETRIES` that 429 and 503 share the same budget.
  - Gotchas / "Worst-case retry hold": recompute the worst case. With jitter the *expected* sleep is unchanged but the upper bound per retry is `1.25 * MAX_DELAY`. Update the ~5min / ~8.3h figures to reflect the +25% ceiling (defaults: ~`1.25 * 30 = 37.5s` per capped retry; ~3.8 min total; env maxes: ~10.4h).
  - Gotchas: add a one-line note that jitter uses a **thread-local `random.Random()`** (the module-global `random` is not thread-safe under `ThreadingHTTPServer`).
- **`README.md`**:
  - Features section: the "Automatic retries on 503" bullet becomes "Automatic retries on 429 and 503" (add 429).
  - Configuration / retry section: mention 429 is now retried (previously only 503) and that delays include ±25% uniform jitter; note the cap is applied pre-jitter so actual delays may exceed `PROXY_MAX_DELAY` by up to 25%; give jitter-aware worst-case bounds (~3.8 min defaults / ~10.4h env maxes).
  - Test count: update the "24 tests" / "the suite has 24 tests" mention (if present) to 27.
  - Self-contained doc — must not assume the reader has CLAUDE.md.
- **`server.py` module docstring (lines 2–3):** update "retrying on 503 (Service Unavailable) with exponential backoff" → "retrying on 429 (Too Many Requests) and 503 (Service Unavailable) with jittered exponential backoff". (Source-level docstring is a planner doc-sync task — the coder does not touch docstrings.)
- **`forward_request` docstring (line ~237):** update the "On 503, retries with exponential backoff" line → "On 429 and 503, retries with jittered exponential backoff".
- **No `doc/` directory exists** in this repo (confirmed: only `README.md`, `LICENSE`, `pyproject.toml`, `src/`, `tests/`). No `doc/**` sync needed.

## Guidance for Coder

**Files to modify:** `src/claude_retry_proxy/server.py` ONLY.

No test files, no CLAUDE.md, no README.md, no doc/* — those are the planner's.
The only non-source artifact you write is `./tmp/reports/*.json` session
reports (communication, not documentation).

**Step-by-step:** see "Proposed Changes" above. Three edits in one file:
(1) add `import math` + `import random`, the `_rng_local`/`_rng()` thread-local
helper, and `compute_jittered_delay`; (2) wire jitter into the 503 branch;
(3) merge 503/429 into one branch with maximal delay for 429, drain the
response body before close, and use a defensive `elif`/`else` dispatch.

**Do not:**
- Do not add a `PROXY_JITTER_*` env var. The 25% is a fixed constant.
- Do not use the module-global `random.uniform` — use the thread-local `_rng()` accessor (thread-safety, Introspection Log High #1).
- Do not use `round()` for the jitter rounding — use `math.floor(base + jitter + 0.5)` (Introspection Log High #2).
- Do not change `compute_delay`'s formula or its `min(..., MAX_DELAY)` cap.
- Do not touch the connection-error (`except`) branch.
- Do not change `forward_request`'s return signature or tuple ordering.
- Do not add jitter to the connection-error branch in this plan (see "Optional follow-up" — out of scope).

**Build verification:** `pip install -e .` succeeds; `python -c "import
claude_retry_proxy.server as s; s._rng(); print(s.compute_jittered_delay(32))"`
succeeds with no import error and returns an int.

## Guidance for Tester

Create **permanent** tests in `tests/test_claude_proxy.py` (extend the
existing suite; match its `pass_/fail/info` style, not pytest):

1. **`test_compute_jittered_delay_bounds`** — unit test of the helper (import `compute_jittered_delay`, `compute_delay`, `_rng` from `claude_retry_proxy.server`). For `base` in `[1, 2, 3, 4, 8, 16, 30, 300]`, draw 2000 times; assert every result is an `int`, `0 <= result <= math.floor(base*1.25 + 0.5)`, `result >= math.floor(base*0.75 + 0.5) - 1`, and `abs(mean - base) < 0.15*base` (jitter is unbiased). **De-sync pattern (corrected after iter-2 audit):** assert `base=3` produces ≥2 distinct values (`{2,3,4}`) and `base=4` produces ≥2 distinct values (`{3,4,5}`); assert `base in (1, 2)` each produce exactly 1 distinct value — this documents the known degenerate small-delay case (±25% of 1 or 2 is ≤0.5s, which lands in one integer bucket after half-up). Do NOT assert `base=2` is multi-value — that assertion would always fail. Also assert `compute_jittered_delay(0) == 0` and `compute_jittered_delay(-5) == 0` (the `base <= 0` guard). Assert `compute_delay(0) == PROXY_INITIAL_DELAY` and `compute_delay(100) == PROXY_MAX_DELAY` (regression guard on the unchanged exponential). Assert `_rng()` returns the same object within one thread and distinct objects across two threads (thread-local correctness).

2. **`test_retry_429`** — modeled on `test_retry_logic` (lines 635–739). Mock upstream returns `429` for the first 3 requests then `200`. Start proxy with `PROXY_MAX_RETRIES="5"`, `PROXY_INITIAL_DELAY="1"`, `PROXY_MAX_DELAY="2"`. Assert the client gets `200`, the upstream received 4 calls, and (by reading the trace file) at least one `retry` line has `reason == "429"`. The 429 path uses `MAX_DELAY` (=2s here), so total test time ≈ 3 × ~2s ≈ 6s — acceptable. **For the trace-file assertion**, follow the `test_trace_markers` pattern (around line 775): create a temp trace file with `tempfile.mkstemp(suffix=".jsonl")`, pass it via `PROXY_TRACE_FILE` env var, and after the test parse the JSONL lines:
   ```python
   fd, trace_path = tempfile.mkstemp(suffix=".jsonl")
   os.close(fd)
   env["PROXY_TRACE_FILE"] = trace_path
   # ... run proxy, send request ...
   with open(trace_path) as f:
       entries = [json.loads(line) for line in f if line.strip()]
   assert any(e.get("event") == "retry" and e.get("reason") == "429" for e in entries)
   ```

3. **`test_retry_429_exhaust_returns_429`** — mock upstream *always* returns 429; `PROXY_MAX_RETRIES="2"`, `PROXY_MAX_DELAY="1"`. Assert the client receives `429` (not 503, not 0), and the proxy did not retry beyond `MAX_RETRIES+1` total attempts.

4. **`test_retry_logic` regression** — the existing test (503 3x then 200) must still pass unchanged after the jitter wiring.

Add the three new tests to the suite's `ALL_TESTS` list (around line 2528 — the variable is `ALL_TESTS`, not `TESTS`) following the existing `("retry-logic", test_retry_logic)` tuple pattern.

**Reminder:** tests mutate live `~/.claude/settings.json` — follow the
existing `backup_settings()`/`restore_settings()` discipline used in
`test_retry_logic`. The 12-CLI-test caveat in CLAUDE.md (requires non-localhost
`ANTHROPIC_BASE_URL`) does not affect these direct-server tests, but the test
must set a localhost mock upstream via `set_base_url(...)` exactly as
`test_retry_logic` does.

## Verification (end-to-end)

```bash
# 1. Build / import sanity
pip install -e .
python -c "import claude_retry_proxy.server as s; s._rng(); print(s.compute_jittered_delay(32))"

# 2. Coder's scripted checks (provided in plan)
python tmp/verification/2026-07-18-jitter-and-429-retry-step1.py
python tmp/verification/2026-07-18-jitter-and-429-retry-step3.py

# 3. Full test suite (includes the 3 new permanent tests + existing retry regression)
python tests/test_claude_proxy.py

# 4. Manual smoke (optional, needs a non-localhost ANTHROPIC_BASE_URL for CLI path):
#    Start the proxy, send a request, observe retry trace lines in
#    ~/.claude/logs/proxy-trace.jsonl show jittered delay_s values and
#    reason "503" or "429" as appropriate.
```

## Rollback

The three `server.py` edits are additive and self-contained — no data migration, no schema change, no config-file format change. To revert if the implementation misbehaves (jitter rounding bug, thread-local RNG defect, 429/503 branch edge case):

1. `claude-retry-proxy stop` — if the proxy is running, this restores `~/.claude/settings.json` to the original upstream URL and tears down the server process. Do this **before** reverting code so the live proxy isn't left swapping against a reverted binary.
2. `git revert <commit>` (or `git checkout HEAD~1 -- src/claude_retry_proxy/server.py`) — restore `server.py` to the pre-change state.
3. `pip install -e .` — reinstall so the console scripts point at the reverted module.
4. Restart normally with `claude-retry-proxy start`.

No lock-file or state-file cleanup is needed beyond what `stop` already does (`proxy-state.json`, `proxy-stderr.log`, and the swap locks are all managed by `stop`). The trace log at `~/.claude/logs/proxy-trace.jsonl` is append-only and unaffected by revert.

**Note:** if deterministic backoff timing matters to any workflow (e.g. a test that asserts exact retry counts), pin the prior version (`pip install claude-retry-proxy==0.1.0`) until that workflow is updated for the jittered/429 behavior. The test suite's own `test_retry_logic` uses `PROXY_MAX_DELAY=2`, which is a degenerate jitter case (see Known edge) and so is unaffected by jitter — but external consumers should verify.

## Optional follow-up (out of scope — flag, don't do)

- **Jitter on the connection-error branch.** For consistency, the
  `except (socket.error, ...)` branch (line 318) should arguably also jitter.
  This plan leaves it un-jittered to keep the change surgical and because the
  user specified "503" / "429" handling. **Rationale for the asymmetry being
  safe:** connection errors are typically per-session (local network partition,
  DNS failure, the proxy host can't reach upstream) rather than per-upstream
  load-shedding, so the concurrent-session thundering-herd that motivates
  jitter for 503/429 is less likely. Worth a separate one-line plan if desired.
- **Respect `Retry-After` header.** The mock upstream in `test_retry_logic`
  sends `Retry-After: 1` (line 658); the proxy ignores it. Out of scope here.
- **Post-jitter hard cap on `PROXY_MAX_DELAY`.** If the cap should be a hard
  ceiling after jitter, change `compute_jittered_delay` to clamp the upper
  bound: `min(MAX_DELAY, max(0, math.floor(base + jitter + 0.5)))` for the 503
  path only. Flagging for user decision — current plan allows jittered sleeps
  to exceed `MAX_DELAY` by up to 25%, consistent with the user's confirmed
  "cap is pre-jitter" choice.

## Document Overrides

No documented rules overridden. The CLAUDE.md Gotchas "worst-case retry hold"
figure is being *updated* (it's stale after this change), not overridden —
updating it is the planner's doc-sync duty, not a rule violation.

| Document | Rule Overridden | Reason |
|----------|----------------|--------|
| `CLAUDE.md` § Core Constraints (coder) | "Never touch test directories" | Step 4 item 3 (`tests/test_claude_proxy.py` line 9 docstring) is a one-line text swap in a file the tester already owns and edited in the prior session. Reassigning it to the coder was a plan error — the coder's core constraint correctly blocked it. The plan now assigns item 3 to the tester and the coder owns only items 1–2 (`server.py`). This override is **not needed** — the plan was revised to respect the constraint instead. |

## Issue Log

| Issue | Status | Found | Resolved | Resolved By |
|-------|--------|-------|----------|-------------|
| [shutdown-during-retry-sleep](./tmp/reports/defer-issue-shutdown-during-retry-sleep.json) — `_shutting_down` flag not checked during `time.sleep(delay)` in `forward_request` retry loop; a mid-retry request blocks `/admin/shutdown` for up to `MAX_RETRIES * jittered_max_delay` (~38s default, ~375s env maxes). Pre-existing — affects current 503 and connection-error sleep paths, not introduced by this plan. Out of scope here per Prime Directive 3; tracked for a future hardening plan. | Won't fix | 2026-07-18 | 2026-09-11 | user — explicit decision (2026-09-11). Planner correction on the record: the filed premise is **disproven**. `ThreadingHTTPServer.daemon_threads = True`, so `server_close()` joins nothing — shutdown returns in ~1s regardless of in-flight retries and the process exits with them still running (measured: 1.62s process exit with a 20s sleep in flight). The gap itself is real — `_shutting_down` is never read on the request path, so the sleeps at `server.py:2069` / `:2254` are uninterruptible — but its consequence is the **inverse** of the filing: in-flight requests are killed mid-flight, not awaited. Accepted as intended; `CLAUDE.md` Gotcha corrected. [report](./tmp/reports/defer-issue-shutdown-during-retry-sleep.json) |

## Final Results

**Status:** COMPLETED
**Completed:** 2026-07-19
**Plan ID:** 2026-07-18-jitter-and-429-retry

### What was built

Two-file change (uncommitted in working tree as of this writing):

- **`src/claude_retry_proxy/server.py`** (+46/−8): added `import math`, `import random`; a thread-local RNG accessor (`_rng_local`/`_rng()` — per-thread `random.Random()`, since the module-global `random` is not thread-safe under `ThreadingHTTPServer`); `compute_jittered_delay(base)` (±25% uniform jitter, `base<=0` guard, unbiased half-up via `math.floor(base+jitter+0.5)` — not `round()` which is banker's rounding). Merged the status check in `forward_request` to `if resp.status in (429, 503):` with a defensive `if 429/elif 503/else` dispatch; 429 retries use `compute_jittered_delay(PROXY_MAX_DELAY)` (maximal latency, per user spec), 503 uses `compute_jittered_delay(compute_delay(attempt))` (jittered exponential); `resp.read()` drains the body before `conn.close()`; exhaustion returns `resp.status` (429 stays 429). Connection-error branch untouched (deliberately un-jittered — see Optional follow-up).
- **`tests/test_claude_proxy.py`** (+363): three new permanent tests — `test_compute_jittered_delay_bounds` (33 assertions: bounds, rounding, de-sync pattern, degenerate `base∈{1,2}`, guard clauses, thread-local RNG), `test_retry_429` (3×429-then-200 + `reason:"429"` trace), `test_retry_429_exhaust_returns_429` (always-429 returns 429). Registered in `ALL_TESTS`. Existing `test_retry_logic` regression passes.

### Test results

Tester report [2026-07-18-jitter-and-429-retry-tester-2026-07-18.json](../reports/2026-07-18-jitter-and-429-retry-tester-2026-07-18.json): **overall_result SUCCESS, 9/9 passed, 0 failed, 0 skipped.** The 12 CLI tests (URL-swap path) were skipped because the user's live proxy was running — those tests mutate `~/.claude/settings.json` and exercise a code path **unchanged by this plan**, so the skip doesn't undermine the verdict for this scope. No issues filed.

### Review verdict

Phase 6 reviewer report [2026-07-18-jitter-and-429-retry-review-2026-07-19.json](../reports/2026-07-18-jitter-and-429-retry-review-2026-07-19.json): **0 Critical, 1 Warning, 4 Suggestions — "non-blocking", gate passed.** Correctness/Design/Security/Performance/Testability all clean. The Warning (unreachable defensive `else` in the dispatch) is the intentional guard the mega-audit requested — acknowledged, not changed. Three Suggestions are source-docstring staleness handed to a coder follow-up (planner cannot edit `server.py`/test source); one was a design-doc arithmetic error the planner corrected.

### Documentation updated (planner-owned, done before completion)

- `CLAUDE.md`: Purpose (429+jitter), Structure (24→27 tests), Architecture/Server (429, jitter, thread-local RNG), env table (`PROXY_MAX_RETRIES` shared, `PROXY_MAX_DELAY` pre-jitter + 429-uses-it), Gotchas (worst-case recompute ~3.8min/~10.4h, integer-jitter-degenerate-small-delay note, `_shutting_down` note).
- `README.md`: intro, Why, config table, backoff paragraph (+429-uses-MAX_DELAY, +jitter, +worst-case, +small-delay note), Features (429+jitter), test count 24→27 (split 12 CLI / 15 direct-server).
- Design doc `2026-07-18-jitter-and-429-retry-design.md`: corrected `base=3 → {2,3,4}` (was wrongly `{2,3}`).

### Known caveats (non-blocking)

- **Integer-second jitter is degenerate for `base ∈ {1, 2}`** (no de-sync; effective from `base ≥ 3`). On the 503 path, de-sync starts at the 3rd retry; on the 429 path, from the first retry (`MAX_DELAY` default 30). Accepted per user's Option B choice (keep integer rounding, fix docs) over sub-second jitter.
- **Source docstrings stale** — **RESOLVED.** All three docstring sites synced:
  - `server.py` module docstring (item 1): applied by coder.
  - `server.py` `forward_request` docstring (item 2): applied by coder.
  - `tests/test_claude_proxy.py` case-5 (item 3): applied by tester after
    plan revision (coder core constraint blocked it; correctly reassigned).
  No behavioral change. Issue `step4-test-docstring-blocked-by-constraint`
  closed.
- **`shutdown-during-retry-sleep`** — pre-existing Open issue (Issue Log), out of scope, unchanged by this plan. **Closed `Won't fix` 2026-09-11** — the filed premise (a blocking drain) was tested against the code and disproven; see the Issue Log row.

### Carried-forward issue (closed 2026-09-11, not blocking this plan)

- `shutdown-during-retry-sleep` — found 2026-07-18; **closed `Won't fix` 2026-09-11** by explicit user decision. Tested against the code and disproven as filed: shutdown does not drain in-flight requests, it exits and kills them. See the Issue Log row and the [report](./tmp/reports/defer-issue-shutdown-during-retry-sleep.json).

### Next step

Implementation is complete, tested green, review-gate passed, and all
docstrings synced. The change is uncommitted in the working tree. Run
`/update-and-commit` to sync docs and commit all changed files.
