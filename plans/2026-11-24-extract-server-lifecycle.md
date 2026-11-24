# Plan: Extract the server lifecycle into lifecycle.py

**Plan ID:** 2026-11-24-extract-server-lifecycle
**Created:** 2026-11-24

<!-- ## Immediate Actions: absent from initial plans. Populated by /update-plan for revised plans, replaced (not accumulated) on each revision. -->

## Immediate Actions

**Coder:**
- None — Steps 1–3 complete with gates green; do not touch the tree.

**Tester:**
- None — round SUCCESS (550/550, per-module reconciled; new module registered and teeth-proven; harness issue fixed).

**Planner:**
- Execute Step 5 doc sync now (unblocked): the sweep + CLAUDE.md rows and rewrites, doc/test-catalog.html (catalog table row, per-test entries, and the :737 `main()`'s-finally imprecision the tester flagged), doc/operations.html:123, README sweep evidence; then Phase 6 review and Final Results.

## Issue Log

| Issue | Status | Found | Resolved | Resolved By |
|-------|--------|-------|----------|-------------|
| [harness-stale-source-comment](./tmp/reports/2026-11-24-extract-server-lifecycle-harness-stale-source-comment.json) | Resolved | 2026-11-24 | 2026-11-24 | [tester](./tmp/reports/2026-11-24-extract-server-lifecycle-tester-2026-11-24.json) |

## Guidance for Coder

**Files to modify:**
- `src/claude_retry_proxy/lifecycle.py` (NEW)
- `src/claude_retry_proxy/server.py`

**Never touched by the coder:** `tests/**`, `pyproject.toml` (its console-script line is asserted unchanged by the gates), `doc/**`, `README.md`, `CLAUDE.md`.

**Baseline pin:** all byte-identity gates read the pre-change text from git object `a17ea22697b0dfdf599f18f0b5c41415803e888e` (the plan-start commit; tree verified clean). If `git show <sha>:src/claude_retry_proxy/server.py` ever fails, stop and report — never substitute a different SHA or the live tree.

**Move discipline:** moved bodies are byte-identical to the baseline except the two declared edits in Step 2 (def line; one token) and the declared rename in Step 3. No renames, reordering, rewrites, annotation or f-string edits, no bug fixes inside moved bodies. Import relocation follows the pinned lists — an unplanned import is a plan revision, not a silent addition. Banner/seam handling is pinned per step; re-verify each range's landmarks before cutting (line numbers below are the baseline's and WILL drift after earlier steps — locate by landmark text, and a zero-length remaining range is a stop-and-report).

**Spawn isolation (mandatory for all three gates):** every script under `tmp/verification/` is corpus-classified by `scripts/check_spawn_isolation.py`, which enforces the canonical isolation block (`_ISOLATION_DIR = tempfile.mkdtemp(...)` plus the three `PROXY_*_FILE` assignments) before any proxy import or process spawn. All three gates ship with the block; `python3 scripts/check_spawn_isolation.py` must report `0 fail` (it is also run suite-wide by tests/test_spawn_isolation.py, so a non-compliant gate is red even where the step's own checks pass). If the checker ever reports a fail for these scripts, stop and report — never weaken or specialize the block.

**Step-by-step with verification:**

1. **Step 1: Create `lifecycle.py`; move `_BestEffortStderr` and `_ProxyHTTPServer` byte-identically; server.py re-imports them.**
   - Create `src/claude_retry_proxy/lifecycle.py` with this exact header (final form, created once):
     ```python
     """Process lifecycle for the retry proxy.

     Holds the process startup/serve/teardown sequence and its two private
     mechanisms: the listening server class (`_ProxyHTTPServer`) and the
     best-effort stderr wrapper (`_BestEffortStderr`). server.py binds the
     handler class into the sequence and remains the entry surface (the
     console script `claude_retry_proxy.server:main` and the
     `python -m claude_retry_proxy.server` invocation).
     """
     ```
   - Move the `_BestEffortStderr` class (baseline lines 68–99) and the `_ProxyHTTPServer` class (baseline lines 805–828) byte-identically into lifecycle.py, in that order, separated by exactly two blank lines. Neither class references any other server.py name (verified: `_ProxyHTTPServer` touches only `sys.platform`; `_BestEffortStderr` is a pure leaf). No import statements beyond `import http.server` and `import sys` this step.
   - Delete the two class definitions from server.py. Seam parity: deleting `_BestEffortStderr` (68–99) collapses the surrounding blanks to exactly two between the `sinks.configure(...)` statement and the `# HTTP request forwarding` banner; deleting `_ProxyHTTPServer` leaves the `# Main` banner (801–803) in place — it heads `main()` until Step 2.
   - Add to server.py's import block, immediately after the `from .forwarder import (...)` block closes: `from .lifecycle import _BestEffortStderr, _ProxyHTTPServer`.
   - Frozen-surface evidence (why these names are re-imported with zero further server.py changes): `srv._BestEffortStderr` is read by tests/test_trace.py:1667,1697,1712 and tests/test_retry_streaming.py:2939; `srv._ProxyHTTPServer` by tests/test_cli.py:2070,2085 and tests/test_retry_streaming.py:3543 (`from claude_retry_proxy.server import _ProxyHTTPServer`).
   - `git add src/claude_retry_proxy/lifecycle.py` the moment the file exists.
   → coder verify (auto): `python3 -c "import ast,subprocess,sys; ..."` not required — run the step gate instead.
   → coder verify (scripted): `python3 tmp/verification/2026-11-24-extract-server-lifecycle-step1.py` exits 0 (RED baseline recorded 2026-11-24: failed only on `lifecycle.py exists`, all baseline preconditions PASS; gate proven GREEN + teeth-proven against a synthetic end-state — byte-flip, whitelist-drop, and wrapper-revert mutations each failed exactly where intended).
   → tester verify: full suite (`python tests/test_claude_proxy.py`) green at the round.

2. **Step 2: Move `main()` to lifecycle.py as `main(handler_class)` (the two declared edits); relocate its exclusive imports; install the no-arg wrapper in server.py.**
   - lifecycle.py gains the full pinned import whitelist (exact lines, exact order — the gate canonicalizes and compares):
     ```python
     import argparse
     import http.server
     import json
     import os
     import signal
     import socket
     import sys
     import threading
     import time

     from . import runtime_state
     from . import sinks
     from .compat import _compat_validate_constants, _load_compat_state
     from .config import load_config, validate_config
     from .keys import load_keys_file, read_passphrase_from_stdin, vendor_key_names
     from .settings import SETTINGS, resolve_trace_file
     from .sinks import log_trace, write_state, write_start_marker, write_stop_marker
     ```
   - Move the `main()` body (baseline lines 831–1015) byte-identically EXCEPT the two declared edits: (a) `def main():` → `def main(handler_class):`; (b) the single occurrence of `ProxyHandler` at the server construction (baseline line 976: `server = _ProxyHTTPServer(("127.0.0.1", SETTINGS.port), ProxyHandler)`) becomes `handler_class`. The baseline body contains exactly one `ProxyHandler` reference (gate-verified precondition); anything else must not change.
   - server.py: delete the old `main()` **and** the orphaned `# Main` banner (baseline lines 801–803) it headed; insert in its place, after two blank lines following the `ProxyHandler` class:
     ```python
     def main():
         # CLI entry -- the console script (claude_retry_proxy.server:main), the
         # `python -m claude_retry_proxy.server` invocation, and in-process test
         # spawns all bind this name; the lifecycle implementation is
         # lifecycle.run_server.
         return lifecycle.main(handler_class=ProxyHandler)
     ```
   - The wrapper propagates the callee's return value: today both functions return `None` on every path (startup failures exit via `sys.exit`, normal shutdown falls off the end), so the `return` is behavior-identical — it exists so a future non-zero status return cannot be silently swallowed into an implicit `None`/exit 0. The step-3 gate proves propagation with a stubbed sentinel.
   - server.py import relocation (delete from server, definitions follow their readers):
     - Delete module imports: `argparse`, `os`, `signal`, `socket`, `threading` (zero remaining readers — gate-verified against baseline).
     - `from .config import load_config, validate_config` → `from .config import validate_config`
     - Delete `from .keys import load_keys_file, read_passphrase_from_stdin, vendor_key_names` (whole line).
     - `from .settings import SETTINGS, resolve_trace_file` → `from .settings import SETTINGS`
     - `from .sinks import (log_trace, write_state, increment_total,\n                    write_start_marker, write_stop_marker)` → `from .sinks import (log_trace, write_state, increment_total)`
     - Add `from . import lifecycle` immediately after `from . import runtime_state`.
   - **Test-surface retention (do NOT remove — zero production readers survive in server.py, tests read them through `srv.*`):** `validate_config` (srv.validate_config), `write_state` (srv.write_state), and the six-name compat import block (`_compat_normalize_threshold`, `_compat_retry_lock`, `_compat_state_lock`, `_compat_validate_constants`, `_load_compat_state`, `_persist_compat_state_locked` — the first three and last had no server.py reader even before this plan; gate asserts the block stays whole). `SETTINGS`, `log_trace`, `increment_total`, `json`, `sys`, `time`, `uuid`, `http.server`, `httpx2`, `sinks`, `admin_api`, `runtime_state`, `forwarder` and all forwarder re-exports keep their existing readers and stay.
   - Import-time policy stays single-copy: the module-level `sinks.configure(trace_path=..., state_path=...)` (baseline lines 63–65) remains in server.py only; lifecycle.py must NOT configure sinks at module level (main() calls `sinks.configure` itself after adjusting SETTINGS — baseline line 854, moved verbatim).
   → coder verify (scripted): `python3 tmp/verification/2026-11-24-extract-server-lifecycle-step2.py` exits 0. Calibration (2026-11-24, post-audit-fix): RED against the pre-change tree — fails only on `lifecycle.py readable`, baseline preconditions PASS (including the exactly-one-ProxyHandler pin); GREEN 52/52 against a regenerated synthetic Step-2 end-state built from the real baseline `main()` body, the corrected whitelist, and the `return` wrapper; teeth-proven. The pre-audit GREEN record for this step was stale (it had been taken against the Step-3 gate only, which does not exercise this step's checks) — this bullet supersedes it.
   → tester verify: full suite green at the round; the test_cli.py:1626 spawned `s.main()` path still passes (it binds the wrapper).

3. **Step 3: Rename lifecycle's `main` → `run_server`; the wrapper's call line follows.**
   - lifecycle.py: `def main(handler_class):` → `def run_server(handler_class):`. Nothing else in the body changes.
   - server.py wrapper call: `lifecycle.main(handler_class=ProxyHandler)` → `lifecycle.run_server(handler_class=ProxyHandler)`. The wrapper's def line, docstring/comment, and the `__main__` guard are unchanged.
   - After this step nothing references `lifecycle.main` (gate asserts zero call sites). The inner function's rename breaks no external binding: every reference in the repo (pyproject `claude_retry_proxy.server:main`, the `__main__` guard, tests/test_cli.py:1626's spawned `s.main()`) binds server.py's wrapper, which keeps the name `main`.
   → coder verify (scripted): `python3 tmp/verification/2026-11-24-extract-server-lifecycle-step3.py` exits 0. Calibration (2026-11-24, post-audit-fix): RED against the pre-change tree — fails only on `lifecycle.py readable`; GREEN 28/28 against a regenerated synthetic final state, including the undefined-Load check (ported from Step 2), the wrapper-return sentinel check, and a real entry-path spawn — a valid probe config/keys/models triple under the isolation dir; the spawn must print READY, shut down cleanly on SIGTERM, and leave the `proxy_ready` event in the isolated trace. That spawn is the body-execution evidence: `--help` is an import/argparse short-circuit and is labeled as such in the gate; the test_cli.py:1626 abort path exits at `write_start_marker` before the body's deep half. Teeth-proven: a log_trace whitelist drop fails four checks at once (whitelist, undefined-Load, live-spawn exit, missing proxy_ready event), byte drift fails byte-identity, a swallowed return fails the sentinel check.
   → tester verify: full suite green at the round.

## Guidance for Tester

**Tests to create:**
- **Permanent:** new module `tests/test_lifecycle.py` (follow the suite's per-area-module conventions: `_harness` import, module-level `ALL_TESTS` list, aggregator registration in tests/test_claude_proxy.py — append the import in historical section order and merge its `ALL_TESTS`). Contents:
  1. `lifecycle.run_server` exists; its signature is `(handler_class)` with no default; lifecycle.py defines no `main`.
  2. `srv.main` is the entry wrapper: callable, signature takes zero required arguments — scoped as the fast-fail complement; the behavioral pin for the no-arg entry binding is the spawned `s.main()` path (test_cli.py:1626), not this assertion.
  3. Frozen surface identity: `srv._BestEffortStderr is lifecycle._BestEffortStderr` and `srv._ProxyHTTPServer is lifecycle._ProxyHTTPServer` (re-export, not a copy).
  4. Subprocess smoke: `python -m claude_retry_proxy.server --help` exits 0 (spawn via the harness's conventions; the suite's module-level PROXY_* isolation covers it) — scoped as the help-branch net only. Entry wiring is already pinned by the existing direct-spawn tests (test_cli.py:1978 and the PROXY_SERVER spawns in test_trace.py / test_retry_streaming.py), and body-execution coverage lives in the step-3 gate's READY spawn; do not present this as either of those.
- **Temporary:** none.

**Verification scripts to create:**
- `./tmp/verification/2026-11-24-extract-server-lifecycle-step1.py`
- `./tmp/verification/2026-11-24-extract-server-lifecycle-step2.py`
- `./tmp/verification/2026-11-24-extract-server-lifecycle-step3.py`
  (planner-authored step gates; the tester re-runs any whose step the round touches and attaches the exit status to the session report.)
- `./tmp/verification/2026-11-24-extract-server-lifecycle-tester-per-module.py` and `./tmp/verification/2026-11-24-extract-server-lifecycle-tester-teeth.py` (added by the tester round: suite-result reconciliation across the 23 registered modules, and mutation-proven teeth for the four new surface checks).

**Tests to investigate for retirement:**
- Planner candidates: **none** — no test obsolescence identified. Every existing test touching the moved names reads them through `srv.*` re-exports (test_trace.py:1667/1697/1712 and test_retry_streaming.py:2939 for `_BestEffortStderr`; test_cli.py:2070/2085 and test_retry_streaming.py:3543 for `_ProxyHTTPServer`; test_cli.py:1626 for `s.main()`), and all remain valid without modification.
- Tester may identify additional candidates during test work; same retirement procedure applies.

**Retirement procedure:** For each candidate, verify the test exercises code being removed/changed. If obsolete: delete and note in session report. If still valid: document why in session report. (No candidates identified this round; the procedure stands for tester-identified ones.)

**Round verification:** run the full suite (`python tests/test_claude_proxy.py`) and report per-module results; note any test that patches `claude_retry_proxy.server` attributes by name (setattr on moved names) — the re-export keeps them working, but flag any that patched `server.main` directly (none known at plan time).

## Summary

**Problem.** The 2026-11-23 admin/handler extraction (step 8) left `server.py` at 1,018 lines — marginally over the repo's 1,000-line code threshold — and named its own follow-up: the server-lifecycle extraction. This plan lands it.

**Survey context (measured 2026-11-24, `wc -l`):** `forwarder.py` 1,944 and `server.py` 1,018 are the only source files over the 1,000 threshold; ten test files exceed the 1,500 test threshold. This plan addresses `server.py` only (user-directed front (a)); forwarder and the test partitions remain surveyed backlog for later, separately-planned rounds (one cluster per plan).

**Approach.** The lifecycle cluster — `_BestEffortStderr` (68–99), `_ProxyHTTPServer` (805–828), `main()` (831–1015), ≈214 lines — moves to a new `lifecycle.py`. Membership is deletion-test-clean: each member's only consumer is the lifecycle sequence itself (`_ProxyHTTPServer`'s sole production caller and `_BestEffortStderr`'s sole installer are `main()`), while `ProxyHandler`, `forward_request`, and `_crlf_safe` survive intact as the request path and stay behind. Post-extraction: server.py ≈ 800 lines (HTTP surface: handler + forwarding shim + header guard + mixin assembly + entry wrapper), lifecycle.py ≈ 250 lines.

**The one design change (user-confirmed 2026-11-24).** `main()` cannot move verbatim — line 976 constructs the server with `ProxyHandler`, which stays, and the new module may not import its parent. Resolution: parameter injection — the moved function becomes `run_server(handler_class)` (byte-identical body except the def line and that one token), and server.py keeps a no-arg wrapper:

```python
def main():
    return lifecycle.run_server(handler_class=ProxyHandler)
```

The console script (`claude_retry_proxy.server:main`), the `python -m claude_retry_proxy.server` invocation, the `__main__` guard, and the spawned-subprocess test (test_cli.py:1626) all bind the wrapper and keep working unchanged. Naming (user-confirmed): file = role (`lifecycle.py`); the moved function gets an honest name (`run_server`) because `main`'s original justification ("this module is the program") died with the CLI's takeover of process management; the conventional name survives only at the wrapper, where entry-point-ness is still true.

**Alternatives considered and rejected:**
- *main() alone in its own file, classes stay* — requires a sibling→parent import (circular with server.py's needed `main` binding) or three-parameter injection wiring that leaves dead squatters in server.py.
- *Move only the two classes (~53 lines)* — closes the threshold by luck, admits no real cluster (classes without their consumer), leaves the named follow-up undone.
- *Fold ProxyHandler/forward_request into the move* — a conjunction of two clusters (request path + lifecycle) and violates first-extraction blast-radius discipline (zero request-path code must move).
- *Weaker verbatim-only variant of the main move* — rejected in favor of the declared one-token design change, reviewed through byte-identity gates.

**State doctrine.** No state pattern changes. The moved bodies' runtime-mutated writes (`runtime_state._vendors/_current_config/_config_path/_startup_state` attribute-form, `SETTINGS` mutations, the `sys.stderr` replacement) are preserved verbatim; the owned-state-object conversion (guide §5; forwarder swap-drain + nudge state AND runtime_state's five globals) remains the separate, already-named follow-up plan family.

**Out of scope:** forwarder.py's extraction campaign; the test-file partitions; the owned-state conversions; any behavior change; `pyproject.toml` edits; any fix for the open deferrals (`admin-body-read-timeout`, `sink-warning-in-process-unit-tests` — visibility only).

## Repo Mode

Public

*Detected at plan creation (2026-11-24, `detect_repo_mode.py`). Determines: plan archival path, commit-message content, staged files.*

## Document Overrides

| Document | Rule Overridden | Reason |
|----------|----------------|--------|

## Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| Entry-path regression (console script / `-m` / spawned subprocess) | Proxy cannot start | Wrapper keeps every binding; step-3 gate runs the `--help` subprocess smoke; the suite's CLI start path exercises the full spawn chain |
| Byte drift inside the moved 185-line body | Silent behavior change in startup | Byte-identity gate against pinned baseline sha a17ea22, proven teeth-on for one-word drift |
| Import whitelist drift (extra/missing module imports) | Hidden coupling, potential cycles | Exact whitelist pinned per file; gate fails on any delta |
| Test-surface loss (`srv.*` reads) | Suite breakage | Re-export asserted by identity checks in the step-3 gate + permanent surface test (tester step) |

## Proposed Changes

Each step includes verification checks tagged with confidence (see Prime Directive 4).
`(auto)` = mechanical, coder self-verifies. `(scripted)` = deterministic multi-step, coder runs provided script.
Every step must have at least one verification check executable by its owner.

1. **Step 1: Create `lifecycle.py`; move `_BestEffortStderr` + `_ProxyHTTPServer` byte-identically; server.py re-imports them**
   → coder verify (scripted): `python3 tmp/verification/2026-11-24-extract-server-lifecycle-step1.py` exits 0
   → tester verify: full suite green at the round (per-module results in the session report)

2. **Step 2: Move `main()` as `main(handler_class)` (two declared edits); relocate exclusive imports; install the no-arg wrapper**
   → coder verify (scripted): `python3 tmp/verification/2026-11-24-extract-server-lifecycle-step2.py` exits 0
   → tester verify: full suite green; the test_cli.py:1626 spawned `s.main()` path passes

3. **Step 3: Rename lifecycle's `main` → `run_server`; update the wrapper call**
   → coder verify (scripted): `python3 tmp/verification/2026-11-24-extract-server-lifecycle-step3.py` exits 0
   → tester verify: full suite green

4. **Step 4: Tester round — full suite + new permanent `tests/test_lifecycle.py` surface module (aggregator-registered)**
   → tester verify: `tests/test_lifecycle.py` created with the four checks from Guidance for Tester; full suite green; session report lists per-module results and confirms no test obsolescence

5. **Step 5: Planner doc sync (after coder + tester rounds)**
   → Evidence: sweep executed 2026-11-24 — `git grep "run_server\|server\.main"` had zero doc hits pre-edit (the identifiers are new); all flagged `main()` sites rewritten: CLAUDE.md settings.py row → "adjusted by the startup sequence (`lifecycle.run_server`)", CLAUDE.md passphrase bullet → the startup sequence reads the line (wrapper named), doc/operations.html:123 state diagram → names `lifecycle.run_server` + wrapper, doc/test-catalog.html:747 `main()`'s-finally → `lifecycle.run_server`'s finally; CLAUDE.md structure list carries the rewritten `server.py` row + the new `lifecycle.py` row; CLAUDE.md Future Work step-8 follow-up records the extraction landed (no line counts); doc/test-catalog.html carries the `test_lifecycle.py` catalog-table row + the four per-test entries; README.md targeted sweep 0 hits (no change — grep `_ProxyHTTPServer|_BestEffortStderr|run_server|server\.main|lifecycle\.py`); `python3 scripts/check_doc_anchors.py` PASS (272 anchors, 8 html files, no secret shapes)

## Guidance for Planner

Documentation tasks executed by the planner (Step 5, after the tester round):

- **Files to modify:**
  - `./CLAUDE.md`
  - `./doc/test-catalog.html`
  - `./doc/operations.html`
  - `./doc/content.html` (only if the sweep shows its structure index names server.py internals)
  - `./doc/architecture.html` (only on sweep hits)
  - `./README.md` — sweep only; expected no change (no user-facing interface or module enumeration found at plan time); record the grep evidence in the Step-5 Evidence line.
- **When:** after the tester round completes, before `## Final Results`.
- **What to sync:**
  - CLAUDE.md Structure list: add the `lifecycle.py` row; rewrite the `server.py` row (drop "CLI entry", keep the MRO/mode-dispatch description, note the entry wrapper + lifecycle re-exports); update the step-8 follow-up note in Future Work and the Refactoring section (server-lifecycle extraction landed 2026-11-24; owned-state conversion remains).
  - CLAUDE.md settings.py row: "adjusted by `main()` at startup" → "adjusted by the startup sequence (`lifecycle.run_server`)" — the wrapper named `main` performs no SETTINGS adjustment.
  - CLAUDE.md passphrase pipe protocol bullet: "the server reads one line in `main()` before `serve_forever()`" → the startup sequence (`lifecycle.run_server`) reads it; server.py's `main` is the entry wrapper.
  - doc/operations.html passphrase protocol state diagram: "server reads exactly one line from stdin in `main()`, before serving" → name the startup sequence (`lifecycle.run_server`).
  - doc/test-catalog.html: add the new test module's per-test entries AND a `tests/test_lifecycle.py` row in the catalog module table (the table is the page's complete module list; per-test entries alone leave the catalog incomplete); the four existing `_ProxyHTTPServer`/`_BestEffortStderr` mentions stay textually true (tests read `srv.*` re-exports) — verify each still passes before leaving it untouched.
  - Sweep discipline: `git grep -n` every changed identifier (`run_server`, `lifecycle`, `_BestEffortStderr`, `_ProxyHTTPServer`, `server.main`) across doc surfaces, docstrings, and CLAUDE.md; re-measure every quoted line count at write time; no exact test counts in prose.
  - `.claude/mega-audit-files.json`: not modified (file absent; no entries added).

## History

| Date | Event | Conclusion | Dismissed |
|------|-------|------------|-----------|
| 2026-11-24 | Initial plan | Surveyed the repo (2 source + 10 test files over threshold); user picked front (a) server-lifecycle extraction; resolved naming (lifecycle.py) and design (run_server(handler_class) + wrapper) in Phase 3; three step gates authored, RED-calibrated, and satisfiability/teeth-proven on a synthetic end-state | — |
| 2026-11-24 | Mega-audit pre-read | Two launches failed PLAN_READ_FAILED/LENGTH_MISMATCH: all six plan-reader transcriptions altered one plural-possessive sentence in the Step-1 gate line (grammar-correction drift at char 4232, 2 chars each read); disk proven unchanged across both attempts (sha a226ca9d…, count 19,110 at each launch); the sentence reworded possessive-free and the count re-pinned; relaunched fresh. Failed pre-reads carry no iteration count | — |
| 2026-11-24 | Mega-audit | 40 unique findings — 10 High, 11 Medium, 19 Low; verdict "plan needs revision" ([report](./tmp/reports/2026-11-24-extract-server-lifecycle-mega-audit-2026-11-24.json)); root causes: the pinned lifecycle whitelist omitted `log_trace` (five lenses converged; the pinned state was unsatisfiable, proven empirically), two Step-2-only gate defects (handler_class count, bare-relative import matcher) that the original satisfiability probe missed because it exercised only the Step-3 gate, gates missing the canonical spawn-isolation block (checker 3 fail → suite-wide red), wrapper without `return`, entry-path evidence never reaching the moved body, doc-sync scope gaps | [dt#4 name-inventory](./tmp/reports/2026-11-24-extract-server-lifecycle-mega-audit-2026-11-24.json), [dt#5 docstring deps](./tmp/reports/2026-11-24-extract-server-lifecycle-mega-audit-2026-11-24.json), [dt#6 cluster-size](./tmp/reports/2026-11-24-extract-server-lifecycle-mega-audit-2026-11-24.json), [oc#8 residual readers](./tmp/reports/2026-11-24-extract-server-lifecycle-mega-audit-2026-11-24.json), [oc#9 rollback heading](./tmp/reports/2026-11-24-extract-server-lifecycle-mega-audit-2026-11-24.json), [oc#10 handler guard](./tmp/reports/2026-11-24-extract-server-lifecycle-mega-audit-2026-11-24.json), [rc#12 docstring deps](./tmp/reports/2026-11-24-extract-server-lifecycle-mega-audit-2026-11-24.json), [cr#16 cluster-size](./tmp/reports/2026-11-24-extract-server-lifecycle-mega-audit-2026-11-24.json), [cr#17 seam blanks](./tmp/reports/2026-11-24-extract-server-lifecycle-mega-audit-2026-11-24.json), [cr#18 docstring deps](./tmp/reports/2026-11-24-extract-server-lifecycle-mega-audit-2026-11-24.json), [cr#19 gate divergence](./tmp/reports/2026-11-24-extract-server-lifecycle-mega-audit-2026-11-24.json), [ec#23 seam blanks](./tmp/reports/2026-11-24-extract-server-lifecycle-mega-audit-2026-11-24.json), [ec#24 forward-dated comment](./tmp/reports/2026-11-24-extract-server-lifecycle-mega-audit-2026-11-24.json), [ec#25 handler guard](./tmp/reports/2026-11-24-extract-server-lifecycle-mega-audit-2026-11-24.json), [sec#30 residual imports](./tmp/reports/2026-11-24-extract-server-lifecycle-mega-audit-2026-11-24.json), [bc#36 isolation list](./tmp/reports/2026-11-24-extract-server-lifecycle-mega-audit-2026-11-24.json), [bc#37 isolation modules](./tmp/reports/2026-11-24-extract-server-lifecycle-mega-audit-2026-11-24.json), [bc#38 stop-marker exit](./tmp/reports/2026-11-24-extract-server-lifecycle-mega-audit-2026-11-24.json), [bc#39 tester_files](./tmp/reports/2026-11-24-extract-server-lifecycle-mega-audit-2026-11-24.json) |
| 2026-11-24 | Audit fixes | All 10 High + 11 Medium fixed: `log_trace` added to the whitelist (plan + both gates), handler_class count == 2, bare-relative import matcher corrected, canonical isolation block in all three gates (`check_spawn_isolation.py` 3 spawners 0 fail PASS), wrapper returns the callee value (+ gate sentinel check), step-3 gate gained the undefined-Load check and a real READY-spawn over a generated probe config/keys/models triple (proxy_ready asserted in the isolated trace), Step-2/3 gates re-calibrated RED/GREEN/teeth on regenerated synthetic states (52/52 and 28/28), tester scoping + `**Verification scripts to create:**` marker + doc-sync scope (settings row, passphrase bullet, operations diagram, catalog table row, README sweep entry, `server.main` sweep token) updated | — |
| 2026-11-24 | Implementation round (coder) | Exit 0; all 3 steps passed their gates (18/52/28 checks), build pass, editable install verified, isolation checker PASS; post-extraction counts: server.py 770, lifecycle.py 274 (both under threshold); 1 issue filed ([harness-stale-source-comment](./tmp/reports/2026-11-24-extract-server-lifecycle-harness-stale-source-comment.json), Fix Planned → tester); no commit — staging lands via /update-and-commit per repo flow ([report](./tmp/reports/2026-11-24-extract-server-lifecycle-coder-2026-11-24.json)) | — |
| 2026-11-24 | Implementation round (tester) | Exit 0; overall SUCCESS — full suite 550/550 (23 modules, per-module reconciled), new permanent tests/test_lifecycle.py (4 checks, aggregator-registered, mutation-proven), harness issue FIXED (Issue Log → Resolved), step-3 final gate 28/28, step-1/2 step-scoped snapshot failures are by-design supersessions, isolation checker 0 fail, no test obsolescence, no new issues ([report](./tmp/reports/2026-11-24-extract-server-lifecycle-tester-2026-11-24.json)) | — |
| 2026-11-24 | Review — verdict "Issues found — non-blocking"; [report](./tmp/reports/2026-11-24-extract-server-lifecycle-review-2026-11-24.json) | No Critical, no Warning, 2 Suggestions; ready to commit. Independently verified: byte-identity of both moved classes + run_server body against a17ea22 (one-token edit confirmed, exactly-one-ProxyHandler precondition held); wrapper return propagation with all failure paths on sys.exit and the bare-`main()` guard (nothing swallowed); import-relocation completeness by AST residual-load scan (zero survivors); test-surface retention justified with live-reader evidence (mega-audit hunch #15 refuted); re-export surface, entry wiring, doc-sync claims, isolation checker, and stale-comment fix (hunch #17 refuted) all confirmed; mega-audit hunches #4/#5 refuted by measurement | [Suggestion #1](./tmp/reports/2026-11-24-extract-server-lifecycle-review-2026-11-24.json) server.py:10 module docstring still lists stdlib modules now imported by lifecycle.py (mega-audit Low acknowledged; a source-tree doc-accuracy touch-up for a future hygiene plan — editing post-review would change the reviewed tree); [Suggestion #2](./tmp/reports/2026-11-24-extract-server-lifecycle-review-2026-11-24.json) CLAUDE.md server.py row leads with "ThreadingHTTPServer" though the class now lives in lifecycle.py (row is otherwise accurate; fold into the same future touch-up) |

## Plan Metadata

```json
{
  "plan_id": "2026-11-24-extract-server-lifecycle",
  "steps": [
    "Step 1: Create lifecycle.py; move _BestEffortStderr + _ProxyHTTPServer byte-identically; server.py re-imports them",
    "Step 2: Move main() as main(handler_class) (two declared edits); relocate exclusive imports; install the no-arg wrapper",
    "Step 3: Rename lifecycle's main -> run_server; update the wrapper call",
    "Step 4: Tester round — full suite + new permanent tests/test_lifecycle.py surface module (aggregator-registered)",
    "Step 5: Planner doc sync (after coder + tester rounds)"
  ],
  "coder_files": [
    "src/claude_retry_proxy/lifecycle.py",
    "src/claude_retry_proxy/server.py"
  ],
  "tester_files": [
    "tests/test_lifecycle.py",
    "./tmp/verification/2026-11-24-extract-server-lifecycle-step1.py",
    "./tmp/verification/2026-11-24-extract-server-lifecycle-step2.py",
    "./tmp/verification/2026-11-24-extract-server-lifecycle-step3.py",
    "./tmp/verification/2026-11-24-extract-server-lifecycle-tester-per-module.py",
    "./tmp/verification/2026-11-24-extract-server-lifecycle-tester-teeth.py"
  ],
  "doc_files": [
    "./CLAUDE.md",
    "./doc/test-catalog.html",
    "./doc/operations.html",
    "./doc/content.html",
    "./doc/architecture.html",
    "./README.md"
  ],
  "verification_scripts": [
    "./tmp/verification/2026-11-24-extract-server-lifecycle-step1.py",
    "./tmp/verification/2026-11-24-extract-server-lifecycle-step2.py",
    "./tmp/verification/2026-11-24-extract-server-lifecycle-step3.py"
  ],
  "retire_inventory": [
    "./tmp/reports/2026-11-24-extract-server-lifecycle-mega-audit-2026-11-24.json",
    "./tmp/reports/2026-11-24-extract-server-lifecycle-coder-2026-11-24.json",
    "./tmp/reports/2026-11-24-extract-server-lifecycle-tester-2026-11-24.json",
    "./tmp/reports/2026-11-24-extract-server-lifecycle-review-2026-11-24.json",
    "./tmp/verification/2026-11-24-extract-server-lifecycle-step1.py",
    "./tmp/verification/2026-11-24-extract-server-lifecycle-step2.py",
    "./tmp/verification/2026-11-24-extract-server-lifecycle-step3.py",
    "./tmp/verification/2026-11-24-extract-server-lifecycle-tester-per-module.py",
    "./tmp/verification/2026-11-24-extract-server-lifecycle-tester-teeth.py"
  ],
  "repo_mode": "Public",
  "document_overrides": []
}
```

## Audit Accumulation

*Counters reset when mega-audit runs. Used by Phase 5 entry trigger.*

| Counter | Value | Last Updated |
|---------|-------|--------------|
| issues_resolved_since_audit | 1 | 2026-11-24 |
| steps_changed_since_audit | 0 | 2026-11-24 |
| files_changed_since_audit | 0 | 2026-11-24 |

## Documentation

Doc-sync scope and discipline live in **Guidance for Planner** (Step 5). The deep reference (doc/ tree) is the sync target; CLAUDE.md is the operational summary.

## Final Results

**COMPLETED** — 2026-11-24

**What was built.** The server-lifecycle extraction: `run_server(handler_class)` (the full process startup/serve/teardown sequence), `_ProxyHTTPServer`, and `_BestEffortStderr` moved out of `server.py` into the new `lifecycle.py`; server.py keeps the zero-arg `main()` entry wrapper (`return lifecycle.run_server(handler_class=ProxyHandler)`) plus the request path and the frozen-surface re-exports. Both files now sit under the 1,000-line code threshold (server.py 770, lifecycle.py 274 at round exit). The one declared design change is the handler_class injection; moved bodies are byte-identical to baseline `a17ea22` except the def lines and the single declared token, gate-verified and reviewer-confirmed.

**Steps completed.** All five: Step 1 (classes move — gate 18/18), Step 2 (`main(handler_class)` move + import relocation + wrapper — gate 52/52), Step 3 (`run_server` rename — gate 28/28, including the READY-spawn body-execution evidence: probe config/keys/models triple under the isolation dir → READY printed → clean SIGTERM exit → `proxy_ready` in the isolated trace), Step 4 (tester round), Step 5 (planner doc sync — CLAUDE.md structure/settings/passphrase/Future Work, doc/test-catalog.html catalog row + 4 per-test entries + the `run_server` finally reference, doc/operations.html passphrase diagram, README sweep clean, `check_doc_anchors.py` PASS).

**Test results.** Full suite 550/550 green (exit 0; 23 modules reconciled per-module — every slug PASSED exactly once). New permanent `tests/test_lifecycle.py` (4 checks: run_server signature pin, zero-arg wrapper pin, frozen-surface re-export identity, help-branch smoke), aggregator-registered and mutation-proven. Isolation checker: 3 spawners, 0 fail. No test obsolescence; no `setattr` patching of moved names.

**Review verdict.** "Issues found — non-blocking": no Critical, no Warning, 2 Suggestions (dismissed above as deferred doc-accuracy touch-ups). The reviewer independently re-verified byte-identity, wrapper exit-code semantics, import-relocation completeness (AST residual-load scan), test-surface retention with live-reader evidence, the re-export surface, entry wiring, and the doc-sync claims; mega-audit hunches #4/#5/#15/#17 refuted or confirmed by measurement.

**Known caveats.** The 2 reviewer Suggestions (server.py:10 docstring stdlib list; CLAUDE.md server.py row leading with `ThreadingHTTPServer`) — cosmetic, deferred to a future doc-accuracy plan. Step-1/2 gates are step-scoped snapshots and red against the final tree by design (their surviving invariants are asserted by the green step-3 final-state gate).

**Open deferrals (visibility; none adopted by this plan).** `defer-issue-admin-body-read-timeout.json` (deferred 2026-11-23) and `defer-issue-sink-warning-in-process-unit-tests.json` (deferred 2026-11-22) remain open standalone deferrals on disk — presence means open; neither is resolved or adopted here.

**Resolution notes contain no secrets.**

## Cross-References to Prior Plans

| Prior Plan | Deferred Issue | Resolution |
|------------|---------------|------------|
| 2026-11-23-extract-admin-api | "server.py lands ≈1,040 lines — still over threshold (corrected estimate from the ≈990 first quoted). Full retirement needs the server-lifecycle extraction (`main` + `_ProxyHTTPServer`), which this plan names as the follow-up rather than batching (one cluster per plan)." | This plan performed exactly that extraction: `run_server(handler_class)` + the two classes moved into `lifecycle.py`; server.py dropped below the 1,000-line code threshold (770 lines at round exit), completing the threshold retirement the prior plan's caveat named. |
