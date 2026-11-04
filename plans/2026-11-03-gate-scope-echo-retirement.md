# Plan: Widen the parse-guard gate's scan scope and retire the switch-echo deferral by construction
**Plan ID:** 2026-11-03-gate-scope-echo-retirement
**Created:** 2026-11-03

<!-- ## Immediate Actions: absent from initial plans. Populated by /update-plan for revised plans, replaced (not accumulated) on each revision. -->

## Immediate Actions

<!-- Zero directives: all five rounds complete, all findings dispositioned, Final Results v4 written. Awaiting operator approval → /update-and-commit. Populated by /update-plan for revised plans, replaced (not accumulated) on each revision. -->

## Issue Log

Rows ordered newest-first (latest issues at top). New issues are prepended; resolved issues stay in place with updated status.

| Issue | Status | Found | Resolved | Resolved By |
|-------|--------|-------|----------|-------------|
| [parse-guard-read-error-permanent-pin](./tmp/reports/defer-issue-parse-guard-read-error-permanent-pin.json) | Resolved | 2026-11-04 | 2026-11-04 | [tester](./tmp/reports/2026-11-03-gate-scope-echo-retirement-tester-2026-11-04-3.json) |
| [readiness-wait-socket-leak-on-refusal](./tmp/reports/defer-issue-readiness-wait-socket-leak-on-refusal.json) | Resolved | 2026-11-04 | 2026-11-04 | [tester](./tmp/reports/2026-11-03-gate-scope-echo-retirement-tester-2026-11-04-3.json) |
| [test-docstring-echo-uniqueness-claim](./tmp/reports/defer-issue-test-docstring-echo-uniqueness-claim.json) | Resolved | 2026-11-03 | 2026-11-04 | [tester](./tmp/reports/2026-11-03-gate-scope-echo-retirement-tester-2026-11-04.json) |
| [suite-readiness-probe-timeout-recurrence](./tmp/reports/defer-issue-suite-readiness-probe-timeout-recurrence.json) | Resolved | 2026-11-03 | 2026-11-04 | [tester](./tmp/reports/2026-11-03-gate-scope-echo-retirement-tester-2026-11-04.json) |
| [parse-guard-gate-top-level-scope](./tmp/reports/defer-issue-parse-guard-gate-top-level-scope.json) | Resolved | 2026-10-27 | 2026-11-03 | [tester](./tmp/reports/2026-11-03-gate-scope-echo-retirement-tester-2026-11-03.json) |
| [switch-key-name-container-echo](./tmp/reports/defer-issue-switch-key-name-container-echo.json) | Resolved | 2026-10-26 | 2026-11-03 | [tester](./tmp/reports/2026-11-03-gate-scope-echo-retirement-tester-2026-11-03.json) |

The two `Fix Planned` rows **adopt standalone deferrals filed 2026-11-03** (operator
decision at the approval gate, 2026-11-04: fix both in this plan rather than leave
them open — Phase 6 step 7). When they reach `Resolved`, Step 9.6 retires their
reports like the rows below. Both originally-resolved rows also **adopt standalone
deferrals** (filed with `plan_id: "defer-issue"`, no plan row at
filing). This plan is the adopting plan: when each row reaches `Resolved`,
`/update-and-commit` Step 9.6 retires the linked report file — presence-means-open
ends there. Adoption provenance: the parse-guard gap was filed by plan
2026-10-25-guard-totality-and-blank-admin's Phase 6 review (re-raised by its
iteration-3 mega-audit); the switch-echo deferral was filed by that same plan's
Phase 6 review iteration 2 and explicitly deferred in iteration 3. The switch-echo
disposition (operator decision, 2026-11-03, Phase 3): **close by construction —
pinning test only, no `server.py` change**; the `type(key).__name__` fallback was
presented and rejected as belt-and-braces on a path the nesting gate already closes.

## Guidance for Coder

**No coder steps — this plan touches no source files.** Both code changes live in
`tests/` (tester lane) and the docs live in `doc/` (planner lane). Do not
modify `src/**` for this plan.

## Guidance for Tester

**Tests to create:**
- **Permanent:** `test_parse_guards.py` — the subpackage-walk pin (Step 1): proves
  the site enumeration recurses into subpackages, with the red-before/green-after
  calibration against the flat enumerator. *(landed 2026-11-03)*
- **Permanent:** `test_admin.py` — the switch-path pinning test (Step 2): proves
  the 500-level nesting gate answers *before* the key-name echo on
  `/admin/api/switch`, and that the echo branch itself is live for containers
  that pass the gate. *(landed 2026-11-03)*
- **Permanent:** `test_cli.py` — the readiness-wait contract tests (Step 5): the
  liveness-gated extension grants exactly one extra window to a still-alive child
  (slow-alive → succeeds in window 2; dead → fails fast with no extension;
  hung-alive → bounded at two windows). *(landed 2026-11-04)*
- **Also tester-edited (Step 5, infrastructure not a test):** `tests/_harness.py` —
  the readiness wait moved verbatim into `_wait_for_readiness`; listed here so the
  tester-files union the metadata contract reads stays complete.

**Temporary:** none.

**Tests to investigate for retirement:**
- Planner candidates:
  - None identified. No function, endpoint, or behavior is removed or superseded;
    all changes widen coverage without replacing tests. (The existing string-key
    rejection test near `test_admin.py:1364` stays as-is — the new test extends
    the neighborhood with container cases, it does not replace it.)
- Tester may identify additional candidates during test work.

**Retirement procedure:** For each candidate, verify the test exercises code being removed/changed. If obsolete: delete and note in session report. If still valid: document why in session report.

**Suite notes:** run via `python tests/test_claude_proxy.py`. New test *functions* in
existing modules **must be registered in that module's per-function registry** — each
module's `ALL_TESTS` list feeds both the `-t` choices and `run_cli`'s iteration, so an
unregistered function never runs in the suite (corrected 2026-11-04: the original note
here claimed the opposite; the round-2 tester registered the three Step 5 functions in
`test_cli.py`'s `ALL_TESTS`). The four-High aggregator trap from the 2026-10-25 plan
was a *whole-module* omission — a different shape of the same registration discipline.
The suite is safe alongside a live proxy (`PROXY_STATE_FILE`/`PROXY_TRACE_FILE`
isolation is harness-owned).

## Summary

Two standalone deferrals, one small plan, zero `src/` changes.

**Problem 1 — the parse-guard gate is blind to subpackages** (`parse-guard-gate-top-level-scope`).
`tests/test_parse_guards.py` enforces the repo's JSON-guard doctrine (every
`json.loads`/`json.load` site sits in a `try` with a *total* handler, because
`RecursionError` is a `RuntimeError` and `UnicodeDecodeError` is a sibling of
`JSONDecodeError`, so narrow handlers let both escape and abort a request with no
response). The site enumerator is flat:

```python
# tests/test_parse_guards.py:245
files = sorted(f for f in os.listdir(src_dir) if f.endswith(".py"))
```

`os.listdir` does not recurse: a future subpackage (`src/claude_retry_proxy/<pkg>/`)
is filtered out by the `.endswith(".py")` test, and its parse sites become invisible
to the gate — silently, with the suite green (the non-zero site count still passes on
the remaining top-level sites). Latent today (baseline verified 2026-11-03: the
package tree is flat — `templates/` holds only `.json`), plausible tomorrow: the
/refactor-split survey tracks the router/forwarder and admin/handler extractions as
remaining work. Fix: sorted `os.walk`, `.py` only, plus a synthetic nested-site test —
because on a flat tree the walk and the list are indistinguishable, so only the
synthetic case proves the change (red against the flat enumerator, green after,
test unedited between runs).

**Problem 2 — the switch-echo deferral's premise is void; what remains is unpinned**
(`switch-key-name-container-echo`). The `/admin/api/switch` handler's four sibling
field checks (tier/provider/model) isinstance-check *before* building their error
message, so only strings reach `format()`. The `key` check inverts this: when the
type check fails, the message still stringifies the original object
(`server.py:3698-3704`), so a container in `key` is echoed into the 400 body. The
filed danger: `str()` on a deeply nested container raises `RecursionError` inside a
handler with no enclosing try → the request dies with no HTTP response. The deferral
measured the window on CPython 3.14.3 (decode ~16915; `str()` dies at ~10900 for
dicts) and concluded "safe on this interpreter only". **Commit `6d4b4ff` — filed the
same day — voided that premise**: the handler now runs `check_payload_nesting` at
`server.py:3615`, *before* parse and validation, so any body deeper than 500 levels
is refused `400 nesting_limit_exceeded` and `key` is bounded to ≤497 levels (root →
tiers → tier). Measured on this machine 2026-11-03
(`./tmp/verification/2026-11-03-gate-scope-echo-retirement-evidence.py`): `str()`
headroom is 20682 levels for both list and dict — **41.6× the 497-level bound**;
decode ceiling 16921. The abort path is closed by construction on any interpreter,
not by margin. What is *not* closed is the pin: the safety is an ordering (gate at
3615 before the echo at 3702) and no committed test drives a deep `key` through the
switch handler (`test_admin.py` deliberately avoids deep-nesting fixtures). A future
reorder or gate removal would silently reopen the abort class with the suite green.
Fix: one committed test pinning the ordering, plus both-branch non-vacuity (a
shallow container in `key` must still echo `invalid key name`, proving the echo
branch is live and sits *after* the gate).

**Alternatives considered and rejected:**
- *`type(key).__name__` fallback in `server.py`* — presented to the operator with
  the defence-in-depth precedent noted; rejected (disposition A) as belt-and-braces
  on a path the gate already closes; the pinning test is the artifact that keeps
  the bound true.
- *Extending the gate's scope to `scripts/` or `tests/`* — out of scope by the
  deferral's own note: the invariant is scoped to the package by design.
- *Fixing `orphaned-test-state-files` or starting `httpx2-native-sse-transport`
  in the same plan* — the former is a hygiene/policy call, the latter a
  high-blast-radius migration wanting its own dedicated plan (and the tenacity
  sequencing decision). Both stay deferred.

**Out of scope:** any `src/**` change; the scanner's documented blind spots
(`import json as j`, try-body narrowness — review obligations, unchanged); the
switch handler's other five rejection messages (all interpolate validated strings).

## Repo Mode

Public

*Detected at plan creation. Determines: plan archival path, commit-message content, staged files.*

## Document Overrides

If the plan intentionally contradicts a documented rule (in `CLAUDE.md` or `doc/*`), declare the override here. An empty or absent table means zero tolerance — every documented rule is in force.

| Document | Rule Overridden | Reason |
|----------|----------------|--------|

## Proposed Changes

Each step includes verification checks tagged with confidence (see Prime Directive 4).
`(auto)` = mechanical, coder self-verifies. `(scripted)` = deterministic multi-step, coder runs provided script.
Every step must have at least one verification check executable by its owner (coder steps: coder checks; tester steps: tester verify; planner steps: Evidence).
Steps MUST use this numbered-list format exactly. The `### Step N:` heading format is deprecated and must not be used.

1. **Step 1:** Make the parse-guard site enumeration recursive and pin it with a synthetic nested-site case — both edits in `tests/test_parse_guards.py`.
   Replace `_scan_dir`'s flat listing (line 245) with a sorted recursive walk; add one test that proves the recursion on a synthetic tree. Sequence the work red-first so the calibration is real:
   ```python
   # _scan_dir — replace:
   files = sorted(f for f in os.listdir(src_dir) if f.endswith(".py"))
   # with (deterministic order, .py only; __pycache__/ and templates/ carry no
   # .py files, so today's file set is identical — verified flat 2026-11-03):
   files = []
   for root, dirs, names in os.walk(src_dir):
       dirs.sort()
       for name in sorted(names):
           if name.endswith(".py"):
               files.append(os.path.join(root, name))
   ```
   The new test (suggested name `test_parse_guard_scanner_walks_subpackages`; match
   the module's `pass_`/`fail` idiom and temp-dir cleanup conventions): build a
   synthetic package in a temp dir —
   ```python
   pkg/__init__.py                     # empty
   pkg/top.py        -> def f(s):      # GUARDED parse at top level
                          try: return json.loads(s)
                          except Exception: return None
   pkg/sub/nested.py -> def g(s):      # UNGUARDED parse one level down
                          return json.loads(s)
   ```
   run `_scan_dir(pkg)` and assert: no fatal, **2 sites found**, exactly **1 site
   failure**, and the failure line names `nested.py` — the nested site is visible
   and the guarded top-level site passes. Then rewrite `nested.py` with the parse
   inside `except Exception:` and assert **2 sites, 0 failures**.
   → tester verify (calibration — run BEFORE applying the walk edit): with the new
   test present and `_scan_dir` still on `os.listdir`, the test FAILS (the nested
   site is invisible → sites ≠ 2 / the failure line never appears); then apply the
   walk edit and the same unedited test PASSES. Record both runs in the session
   report.
   → tester verify: `python tests/test_claude_proxy.py` fully green — the live-tree
   gate's site count is unchanged by the walk (baseline: package flat, same `.py`
   set), proving the enumeration change is behavior-preserving today.

2. **Step 2:** Pin the switch path's gate-before-echo ordering with a committed deep-key test — in `tests/test_admin.py`, reusing `_drive_post_in_process` (line 2918) and the neighboring admin tests' server setup. No catalog/vendor setup is needed: both the gate (server.py:3615) and the echo (server.py:3698-3704) fire *before* the first catalog read (server.py:3707).
   The test (suggested name `test_switch_nesting_gate_precedes_key_echo`; match the module's idiom) carries both branches, which is what makes it non-vacuous. Deviation as landed (recorded by the tester): the deep body must carry **all three required tiers with the deep container LAST** — a one-tier body answers `missing tiers` once the gate is gone (measured via the discriminant script below), which would point the pin at the tier-presence rule instead of the key echo:
   ```python
   # deep half: a real container, not a string of brackets — brackets inside a
   # JSON string don't count as nesting (the scanner is string-aware)
   deep = json.loads("[" * 600 + "]" * 600)          # 600-deep list; body
                                                     # depth reaches ~605 with
                                                     # the three-tier nesting
   tiers = {"haiku":  {"provider": "p", "model": "m", "key": "k"},
            "sonnet": {"provider": "p", "model": "m", "key": "k"},
            "opus":   {"provider": "p", "model": "m", "key": deep}}   # LAST
   body = json.dumps({"tiers": tiers}).encode("utf-8")
   captured = _drive_post_in_process(srv, "/admin/api/switch", body)
   # assert: captured non-empty (the abort class leaves NO response);
   #         status == 400; body parses; code == "nesting_limit_exceeded";
   #         message contains "nesting depth exceeds the limit of 500";
   #         "invalid key name" NOT in the body text.
   # shallow half (non-vacuity): the echo branch is live and AFTER the gate
   # (three tiers here too — the required-tier check precedes the field loops,
   # so a one-tier body answers `missing tiers`, never reaching the echo)
   shallow = {"haiku":  {"provider": "p", "model": "m", "key": "k"},
              "sonnet": {"provider": "p", "model": "m", "key": "k"},
              "opus":   {"provider": "p", "model": "m", "key": ["a"]}}
   body2 = json.dumps({"tiers": shallow}).encode("utf-8")
   captured2 = _drive_post_in_process(srv, "/admin/api/switch", body2)
   # assert: status == 400; body contains "invalid key name: ['a']" —
   #         a container that passes the gate IS echoed, so the pin discriminates
   #         the two orderings rather than green-lighting anything.
   ```
   → tester verify: both halves green on the current tree; state the deep half's
   discriminant in the session report — a handler reordered to validate before the
   gate, or a gate removed from the admin path, flips the deep half to
   `invalid key name` (or to no response at all), so the test fails rather than
   passing vacuously. Discriminant MEASURED, not assumed, via the tester's
   script `tmp/verification/2026-11-03-gate-scope-echo-retirement-discriminant.py`:
   with the gate disabled in-process the same body answers
   `400 invalid key name: [[[[…`, proving the committed assertion's failing
   branch is reachable; gate restored, the body is refused by the gate again
   (4 of 4 checks passed).
   → tester verify: `python tests/test_claude_proxy.py` fully green (no regression
   in the neighboring switch-validation tests, including the string-key test near
   line 1364).

3. **Step 3:** Record the by-construction evidence and reconcile the docs — planner-owned, after the tester round. Run the evidence script (written and first-run 2026-11-03, before this plan's test changes — the numbers below are the record) and update `doc/test-catalog.html` where it describes the gate:
   ```
   python tmp/verification/2026-11-03-gate-scope-echo-retirement-evidence.py
   ```
   → Evidence: script exit 0 — `PASS str() survives a 497-deep list`, `PASS str()
   survives a 497-deep dict`, `PASS str() headroom >= 1.5x the 497-level bound —
   list 20682 / dict 20682 / decode 16921 / ratio 41.6x`, `evidence: PASS — 3 of 3
   gates passed` (CPython 3.14.3, recursion limit 1000; re-run on a future
   interpreter re-derives the numbers — the script is idempotent and tree-independent;
   the ceiling search wobbles a few levels run-to-run under stack conditions, so the
   ratio is the stable record — and it held 41.6× across three runs).
   → Evidence: `doc/test-catalog.html` diff — (a) the `test_parse_guards.py` table
   row (lines 154-159) states the scan **walks the whole package tree, subpackages
   included** (the current wording, "in the package", is accurate only under the new
   enumerator); (b) the per-test inventory of **Category 13 — Static Source
   Invariants** (lines 816-828; the plan's original "Category 12" was the deferral's
   stale number — corrected per the tester's report) gains a one-line entry for
   `test_parse_guard_scanner_walks_subpackages`, while `test_switch_nesting_gate_
   precedes_key_echo` gets its entry in the **admin category's** per-test list —
   it tests `test_admin.py`, not the static-invariants module; (c) no counts are
   restated (the Documentation-must-not-maintain-counts rule) — describe behavior,
   and where a figure is tempting, point at the measure-on-demand command.
   → Evidence: `git diff doc/test-catalog.html` shows only the reconciliations
   above plus the Guidance for Planner's declared adds — no undeclared edits.
   **Extended 2026-11-04 (post-implementation audit M9/M1/M11/M26, M16, M24-doc,
   L27):** the doc deliverable now also covers the re-opened plan's work — (d) the
   harness section's Proxy lifecycle table names `_start_proxy_server_directly` /
   `_wait_for_readiness` and describes the readiness contract persistently (READY
   marker primary, TCP fallback, one liveness-gated extension window, dead children
   fail fast, hung-alive bounded at two windows — no timing figures); (e) Category
   9's `test_cli.py` list gains one-line entries for the three landed contract tests
   (`readiness-wait-grants-second-window-to-slow-alive-child`,
   `readiness-wait-returns-false-fast-for-dead-child`,
   `readiness-wait-bounds-hung-alive-child`); (f) the admin entry's two
   `tmp/verification/...` references are reworded to stable artifacts (the test
   command itself; dated provenance in the plan's history) — verification scripts
   are transient by the report-lifecycle rules, so the durable doc must not cite
   them as runnable commands; (g) the admin entry cross-references
   `test_nesting_limit_admin_body` as the live-proxy pin of the same gate branch;
   (h) both `Last updated` stamps advance. Evidence: `check_doc_anchors.py` green
   (258 anchors, no secret shapes, 2026-11-04).

4. **Step 4:** Correct the pinning test's docstring to the reviewed account — in `tests/test_admin.py`, `test_switch_nesting_gate_precedes_key_echo` (adopting `defer-issue-test-docstring-echo-uniqueness-claim`; prose only, no assertion changes). The docstring's second paragraph currently says the `key` check "inverts its three siblings" with `provider`/`model` "isinstance-tested BEFORE their message is built, so only strings reach `format()`". That is structurally false — those guards have the identical shape (`if not isinstance(x, str) or not _validate_admin_name(x): ...format(x)...` — the isinstance test is the branch's trigger, not a guard), which is why the Phase 6 review flagged the same claim in the doc entry. Replace the paragraph's opening with:
   ```python
       """... Every failure branch on this path formats the raw value — the
       isinstance test is the branch's trigger, not a guard — so a deeply
       nested container in `key`, `provider` or `model` would reach `str()`,
       which recurses per nesting level, and a RecursionError there has no
       enclosing try: the request would die with no HTTP response at all.
       (Tier names are exempt only by JSON grammar, which makes object keys
       strings.) What closes that class is not the interpreter's repr headroom
       but the ORDER: ...
   ```
   keeping the docstring's remaining sentences (the ORDER paragraph and the
   both-halves description) unchanged. Mirror the same correction wherever the
   test's comments repeat the claim.
   → tester verify: `grep -n "inverts its three siblings\|isinstance-tested BEFORE" tests/test_admin.py` returns no matches, and the docstring still describes the ORDER mechanism (`check_payload_nesting` before validation).
   → tester verify: `python tests/test_admin.py -t admin-switch-nesting-gate-precedes-key-echo` still 1/1 (a prose-only change cannot move behavior; this proves it).

5. **Step 5:** Grant the readiness wait one liveness-gated extension — in `tests/_harness.py`, adopting `defer-issue-suite-readiness-probe-timeout-recurrence` (the full-suite SETUP flake: a healthy child whose import+bind exceeded `_READY_DEADLINE_SECONDS` under whole-suite load failed its test without an assertion running).
   Verbatim-move the wait loop (`tests/_harness.py:704-724`) into a module-level helper so the contract is deterministically testable, and grant exactly one extra window when the first expires with the child still alive:
   ```python
   def _wait_for_readiness(proc, port, ready_event, window_s=_READY_DEADLINE_SECONDS):
       """Probe for child readiness within `window_s`; one liveness-gated retry.

       Returns True when the READY marker arrives or the TCP probe connects.
       A child that outlives the first window under whole-suite load is slow,
       not dead — dead children exit the wait via proc.poll() and never earn
       a second window. Worst case for a hung-alive child is bounded: exactly
       two windows, then failure with the same probe_ok=False contract.
       """
       for _attempt in (1, 2):
           deadline = time.time() + window_s
           while time.time() < deadline:
               if ready_event.is_set():
                   return True
               if proc.poll() is not None:
                   return False
               try:
                   sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                   sock.settimeout(1)
                   sock.connect(("127.0.0.1", port))
                   sock.close()
                   return True
               except (socket.error, ConnectionRefusedError):
                   time.sleep(0.1)
           if proc.poll() is not None:
               return False   # died during the window — no extension helps
       return False
   ```
   `_start_proxy_server_directly` then calls `probe_ok = _wait_for_readiness(proc, port, ready_event)` and carries its existing comment (updated to note the single liveness-gated extension and that the stderr diagnostic on ultimate failure is unchanged). Behavior preservation: a healthy child succeeds in window 1 exactly as before; a dead child returns False immediately exactly as before; only the alive-but-slow case gains the second window.
   Contract tests in `tests/test_cli.py` (the harness-spawn tests' home), deterministic via a fake proc — no real child, no multi-second waits:
   ```python
   class _FakeProc:
       def __init__(self, poll_result=None): self._poll = poll_result
       def poll(self): return self._poll
   # A: slow-alive child — fake proc poll()→None; a daemon thread binds a
   #    listening socket at ~1.5x window; window_s=0.3 → asserts probe_ok True
   #    and, on the pre-change tree, this FAILS (no second window exists).
   # B: dead child — fake proc poll()→1 → asserts probe_ok False AND fast
   #    return (measured well under one window — pins "no extension for the
   #    dead"; passes on both trees).
   # C: hung-alive child — fake proc poll()→None, nothing ever binds →
   #    asserts probe_ok False after ~two windows (timing assert with
   #    generous slack, e.g. [1.5, 4.0] x window on wall clock; RED on the
   #    pre-change single-window tree, GREEN after).
   ```
   → tester verify (calibration — run BEFORE applying the harness edit): with the
   contract tests present and the wait still inline/single-window, cases A and C
   FAIL and case B passes; then apply the helper extraction and the same unedited
   tests pass. Record both runs in the session report.
   → tester verify: `python tests/test_claude_proxy.py` fully green — including the
   real-child spawn tests (the helper's call site is the only behavioral seam; all
   readiness consumers keep the same probe_ok contract).

   Deviation as landed (recorded by the tester, round 2): the plan's sketch assumed
   a connect to a closed localhost port refuses instantly — measured on this host,
   it black-holes for the full 1 s socket timeout, so real-socket timing is
   non-deterministic here (each window costs ~1.1 s, and a delayed real listener
   can even let window 1's in-flight connect complete after the deadline, making
   case A non-discriminating). The landed tests therefore drive the READY event
   for case A — the harness's primary readiness signal and the exact shape of the
   real flake — and swap `_harness.socket` for an always-refusing stub (restored
   in `__exit__`) for all three cases: measured 0.50 s / 0.00 s / 0.60 s,
   deterministic, no host-SYN dependence. The three functions are registered in
   `test_cli.py`'s `ALL_TESTS` (see Suite notes).

6. **Step 6:** Mega-audit fixes (audit 2026-11-04: 0 High, 10 Medium, 17 Low — report [2026-11-03-gate-scope-echo-retirement-mega-audit-2026-11-04.json](./tmp/reports/2026-11-03-gate-scope-echo-retirement-mega-audit-2026-11-04.json); the planner lane findings are fixed separately and recorded in History; this step carries the tester-lane ones). All edits are in `tests/test_parse_guards.py` and `tests/test_admin.py` / `tests/test_cli.py`:
   - **`_scan_dir` error routing (audit M2+M19, oversight-catcher, Medium):** the recursive enumeration calls `os.walk(src_dir)` with the default `onerror=None`, so an unlistable subdirectory (permission denied, a dir replaced by a file mid-scan, a locked dir on Windows) is silently dropped — re-opening the exact silent-hole class Step 1 exists to close, while the non-zero site count keeps the gate green on the remaining files. Route the error into the existing `fatal` channel:
     ```python
     unlistable = []
     for root, dirs, names in os.walk(src_dir,
                                      onerror=unlistable.append):
         ...
     for exc in unlistable:
         fatal.append("{}: cannot list ({})".format(
             getattr(exc, "filename", None) or src_dir, exc))
     lines.append((False, fatal[-1]))
     ```
     and extend the same discipline to the per-file read: the current `except OSError` misses a valid-Python module that is not decodable as UTF-8 (`UnicodeDecodeError` from `fh.read()` is a `ValueError` sibling, not an `OSError` — audit L20) — widen to `except (OSError, ValueError)`. A scan error must be a visible `fatal`, never a silent narrowing of the file set.
   - **Unlistable-directory test half (M2's calibration):** extend `test_parse_guard_scanner_walks_subpackages` with a third half that makes a subdirectory unlistable and asserts the scan reports a `fatal` naming it (portable form: monkeypatch-free — pass a stub `onerror`-triggering tree, or on POSIX `os.chmod(sub, 0o000)` restored in `finally`; the portable stub of the walk's error path is acceptable per the audit). RED calibration: with the `onerror` wiring absent (walk reverted to default `onerror=None` — the pre-fix shape), the new half FAILS (no fatal surfaces); GREEN with the wiring. If the host cannot make a directory unlistable reliably, drive the error path through a stubbed `os.walk` and say so in the session report.
   - **Deep-half assertion trim (audit M24, test-impact, Medium):** `test_nesting_limit_admin_body` (`tests/test_tier_routing.py`) already POSTs a >limit body to `/admin/api/switch` and asserts the same gate branch — status 400, flat `{"error","code"}` shape, `code == "nesting_limit_exceeded"`, message naming the limit. The new test's deep half duplicates those assertions on the same branch; trim it to the delta only it proves: a response EXISTS, the body does NOT contain `invalid key name`, and (with the shallow half unchanged) the ordering discriminant. The shared gate branch stays covered by the live-proxy test; cross-reference the two in the doc (done planner-side 2026-11-04).
   - **Snapshot/restore idiom (audit L3, oversight-catcher, Low):** the switch pin mutates nothing on the way in and restores nothing on the way out, unlike every neighboring handler-driving test — benign today (the refusal precedes any install), but the regression it guards (gate removed or reordered) is exactly a case where the handler proceeds past the field checks; a failing run would then leave `srv._current_config`/`_config_epoch`/`_config_path`/`_vendors` mutated for every later test. Wrap both `_drive_post_in_process` calls in the neighbors' snapshot/restore idiom (`try:`/`finally:`), and assert `srv._config_epoch` is unchanged after both halves — which also strengthens the pin: a refusal must not advance the epoch.
   - **Stub invariant comment (audit L4, oversight-catcher, Low):** `_always_refusing` (tests/test_cli.py) replaces `_harness.socket` process-globally for the sub-second case windows; state the safety invariant in a comment at the context manager — "no live daemon thread touches `_harness.socket` while a case window is open" — so a future reader knows what would break.
   → tester verify (calibration): with the `onerror` wiring reverted to the default (pre-fix shape), the unlistable-dir half FAILS (no fatal); with the wiring, it PASSES — record both runs.
   → tester verify: the trimmed deep half still fails the abort class (no response) and the reordered-gate case (echo appears) — i.e. its remaining assertions still discriminate; run `python tests/test_claude_proxy.py -t admin-switch-nesting-gate-precedes-key-echo` and `-t nesting-limit-admin-body` (both green, now complementary rather than duplicative).
   → tester verify: `python tests/test_claude_proxy.py` fully green; the three new `fatal`/trim/idiom changes are all registered tests or in-place edits with no new module (register any new test function in `ALL_TESTS` per Suite notes).

7. **Step 7:** Close the two micro-deferrals in place (operator direction at the gate, 2026-11-04: "fix now"). Both fixes are tester lane, both files already touched by this plan.
   - **Socket closure on the refusal path** (adopting `defer-issue-readiness-wait-socket-leak-on-refusal`; `tests/_harness.py`): restructure `_wait_for_readiness`'s probe so every created socket is closed exactly once, on both paths:
     ```python
     sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
     try:
         sock.settimeout(1)
         sock.connect(("127.0.0.1", port))
         return True
     except (socket.error, ConnectionRefusedError):
         time.sleep(0.1)
     finally:
         sock.close()
     ```
     Note for the contract tests: the `_always_refusing` stub replaces `_harness.socket`, so the stub's objects must tolerate `close()` (add a no-op if the stub lacks one).
   - **Permanent pin for the read-error routing** (adopting `defer-issue-parse-guard-read-error-permanent-pin`; `tests/test_parse_guards.py`): extend `test_parse_guard_scanner_walks_subpackages` (or add one registered function per Suite notes) with a case whose synthetic tree carries a module that is valid Python but declares a non-UTF-8 coding (e.g. `# -*- coding: latin-1 -*-` with a 0xE9 byte) — assert `_scan_dir` reports a `fatal` naming that file instead of raising. RED calibration: with the guard narrowed back to `except OSError` (the pre-Step-6 shape), the scan RAISES and the case fails; GREEN with the widened guard, test unedited.
   → tester verify: socket part — the three contract tests still 1/1 each (the stub seam tolerates `close()`); read `_wait_for_readiness` and confirm no path creates a socket without closing it exactly once.
   → tester verify: pin part — RED/GREEN recorded for the narrowed-guard mutant and the landed tree, test unedited between runs.
   → tester verify: `python tests/test_claude_proxy.py` fully green; any new test function registered in `ALL_TESTS`.
   - **S3 — annotate the extension's race gate** (review pass 2, Suggestion; operator option (a)): the between-windows `if proc.poll() is not None: return False` in `_wait_for_readiness` is unpinned — deleting it leaves all three contract tests green. The reviewer offered "pin with a call-counting fake, or annotate as a race guard"; the fake route was analyzed and is **behaviorally impossible**: once a real process dies, `poll()` stays non-None (monotonic), so window 2's own in-loop check observes the same death on every real input — the reviewer's own note ("case B exits via the in-loop poll") says the same. Take the annotate route: the comment states the check is the extension's explicit gate — a child that died during window 1 must never earn window 2 — and that it is redundant with window 2's in-loop poll *under today's loop shape* but load-bearing under refactor (a changed extension count, or a window-2 loop that stops polling, would make it the only guard).
   - **S4 — tighten the unlistable half's assertion** (review pass 2, Suggestion): the half currently passes on "some fatal names the directory" — but a read-error fatal on `sub/nested.py` also contains the `sub` path and is also a FAIL line, so the half could green without the `onerror` wiring it exists to pin. Assert the fatal carries the "cannot list" marker (the `onerror` branch's own format string) and that the scan still counted both sites (`sites == 2` — errors report, they do not silently narrow). The existing RED calibration (no wiring → no fatal at all) already fails the tightened assertion.
   - **S5 — widen case A's fixture slack** (review pass 2, Suggestion): the READY marker fires at 1.5×window while window 2 closes at 2×window — ~0.15 s of slack, so a late timer thread could false-FAIL the very test that exists to stop load flakes. Move the marker firing earlier inside window 2 while keeping the elapsed assertion's meaning (success provably from window 2: elapsed ≥ one full window) — e.g. fire at 1.2×window with the elapsed lower bound still one window, or enlarge `window_s`; whichever shape, the comment records the slack budget and the deterministic-band reasoning.
   → tester verify (S3): the annotation names the gate's role and its redundancy-under-today's-shape; grep confirms the check still sits between the windows.
   → tester verify (S4): the tightened half still passes GREEN and still fails the no-wiring RED run; a synthetic read-error fatal on the nested module does NOT satisfy the "cannot list" assertion (demonstrate once in the session report).
   → tester verify (S5): case A still 1/1 standalone and in-suite; the marker/window timing leaves ≥0.3 s of slack by the fixture's own arithmetic, stated in a comment.
   → tester verify (all): `python tests/test_claude_proxy.py` fully green.

8. **Step 8:** Third-pass fixes (operator-directed round 5, exceeding the 4-iteration cap on the operator's explicit "option a" — recorded in History). All in `tests/test_cli.py` and `tests/_harness.py`:
   - **S1 — committed regression guard for the socket-leak fix** (review pass 3, Suggestion; the reviewer notes it is the same shape Step 7 already fixed once for the read-error routing): `_RefusingSocket.close()` is a no-op and no contract test counts sockets, so deleting the `finally` restores the leak with the suite green. Give the stub counted creation/closure — class-level counters reset by the test — and extend the hung-alive case (the one that actually drives refusal-path probes: alive child, stub refuses, two windows) to assert `created == closed` and `created >= 1` after the wait. Deleting the `finally` makes `created > closed` → the assertion fails.
     → tester verify (calibration): with the `finally` removed (the leak shape, tests unedited), the extended case FAILS (created > closed); restored, it PASSES. Record both runs.
   - **S2 — correct the closure-protocol comment** (`tests/_harness.py`): it says "the refusal path closes before its sleep"; the code sleeps in `except` and closes in `finally` — i.e. after. Reword to what the code does: every created socket is closed exactly once by the `finally` — on success after the connect returns, on refusal after the handler's 0.1 s sleep.
   - **S3 — refresh the stale section header** (`tests/test_cli.py`): it still says the cases finish "well under a second (window_s=0.3)"; case A now runs `window_s=0.4` with a 0.8 s two-window budget. State the actual budget honestly (longest case ≈ the two-window bound).
   → tester verify: the extended case green in-suite; the two wording fixes match the code by inspection; `python tests/test_claude_proxy.py` fully green; no new test function beyond the extended case (register in `ALL_TESTS` if a new function is introduced).

## Guidance for Planner

Documentation tasks you will execute yourself (not the coder):

- **Files to modify:** `./doc/test-catalog.html`
- **`.claude/mega-audit-files.json`:** no declared audit locations are added, renamed, or retired by this plan.
- **When:** after the tester round completes (Step 3) — the doc entries must name the tests as landed, not as planned.
- **What to sync:** the `test_parse_guards.py` table row's scope wording (walks the package tree); the Category 13 per-test inventory (one new entry: the subpackage-walk test) and the admin category's per-test list (one new entry: the switch-path pin — different section, per the tester's report); verify the Category 13 "What this category does not cover" paragraph needs no change (the shape-check caveat and the `import json as j` blind spot are unaffected). *(done 2026-11-03)* **Re-opened plan adds:** the harness section of `doc/test-catalog.html` gains the readiness wait's single liveness-gated extension, described persistently (no timing figures), plus per-test entries for the Step 5 contract tests as landed. No `README.md` or `CLAUDE.md` impact: neither describes the gate's enumeration scope or the harness readiness contract, and no user-facing behavior changes.

## History

One row per event (spec revision / mega-audit / review / implementation round). Conclusion = one-sentence outcome or what changed. Dismissed = compact dismissed-findings list for the reviewer — verbatim issue slugs linked as `[<slug>](<report-path>)`, no prose-only entries (the update-and-commit cross-ref and the reviewer both match these cells verbatim). Link to report files; never restate findings inline.

| Date | Event | Conclusion | Dismissed |
|------|-------|------------|-----------|
| 2026-11-03 | Implementation round (tester) | **Success** — [report](./tmp/reports/2026-11-03-gate-scope-echo-retirement-tester-2026-11-03.json): both steps landed, 497/497 on the authoritative run (exit 0); Step 1 calibrated red-before/green-after on an unedited test (RED: "1 site in a package holding 2 — the enumeration does not reach subpackages"), live-tree equivalence 15/15 files, 23/23 sites guarded; Step 2's pin discriminant measured via `…-discriminant.py` (gate disabled in-process → echo answers, 4/4). One recorded deviation: the deep body needs all three tiers with the deep container LAST (one-tier body would answer `missing tiers` once the gate is gone) — Step 2's snippet corrected to match. Planner's independent verification of the round's artifacts (substitute for the absent coder report — this plan has no coder steps): both new tests re-run green (`parse-guard-scanner-walks-subpackages` 1/1, `admin-switch-nesting-gate-precedes-key-echo` 1/1) and the evidence script re-run PASS (41.6×). Tester's pre-existing finding (`suite-readiness-probe-timeout-recurrence`, Low, harness lane, 1/2 full-suite runs, cleared on re-run, out of this plan's scope) transferred to the standalone deferral `defer-issue-suite-readiness-probe-timeout-recurrence.json` — no adopting row in this plan. Tester's three doc discrepancies folded into Step 3 (Category 13 not 12; admin-category placement for the switch test; scope wording). | — |
| 2026-11-03 | Review (Phase 6 — reviewer subagent) | Verdict **Issues found — non-blocking**: **0 Critical, 1 Warning, 2 Suggestions** — the commit gate passes. Report [2026-11-03-gate-scope-echo-retirement-review-2026-11-03.json](./tmp/reports/2026-11-03-gate-scope-echo-retirement-review-2026-11-03.json). The Warning's substance supersedes the deferral's own framing (and the plan Summary's): "only `key` stringifies the raw object" is structurally false — the provider/model failure branches have the identical shape, so a container in any of the three reaches `str()`; the abort analysis stands because the 500-level gate refuses every over-limit body before *any* validation, and the key-side pin transitively pins that ordering. All three findings were fixed in the planner's own artifacts this round, not dismissed: the doc entry rewritten (uniqueness claim removed; derived figures now described derivationally — `limit + 100` / `MAX_JSON_NESTING_DEPTH` minus enclosing structure — with the measure-on-demand pointer, per the Readability Suggestion); the plan's Step 2 shallow-half snippet corrected to three tiers (per the Correctness Suggestion). The evidence script was re-run a third time post-review: PASS, ratio 41.6× (answers the reviewer's hunch about the figure). The test-docstring mirror (tester lane — the planner cannot edit test files) is deferred as standalone `defer-issue-test-docstring-echo-uniqueness-claim.json`; no adopting row in this plan. | [review-warning-echo-uniqueness-claim-false](./tmp/reports/2026-11-03-gate-scope-echo-retirement-review-2026-11-03.json), [review-suggestion-derived-figures-restated](./tmp/reports/2026-11-03-gate-scope-echo-retirement-review-2026-11-03.json), [review-suggestion-shallow-snippet-single-tier](./tmp/reports/2026-11-03-gate-scope-echo-retirement-review-2026-11-03.json) |
| 2026-11-04 | Spec revision (/update-plan, operator-directed) | **Plan re-opened at the approval gate**: the operator asked to fix the two same-day deferrals rather than leave them open ("fixing two issues while filing two new ones seems unproductive"). Both adopted as `Fix Planned` rows (their `defer-issue-*.json` reports now retire at Step 9.6 alongside the resolved pair — net new open deferrals zero). **Step 4** corrects the pinning test's docstring to the reviewed account (prose-only, tester lane). **Step 5** grants the readiness wait one liveness-gated extension: the wait loop moves verbatim into `_wait_for_readiness(proc, port, ready_event, window_s=…)`; a second window runs only when the first expired with the child still alive (dead children return False immediately, hung-alive children bounded at two windows); contract tests in `test_cli.py` drive a fake proc — deterministic, no real-child or multi-second waits; cases A (slow-alive → window-2 success) and C (hung → bounded) calibrate red-before/green-after. Design decision ratified by the operator at the gate: liveness-gated retry over a larger fixed deadline. Counters: steps_changed +2 (→ 5), files_changed +1 (`tests/_harness.py`); Final Results v1 marked SUPERSEDED. Mega-audit NOT re-triggered this revision (issues_resolved 2 < 3); the post-implementation audit is expected to trigger after the round resolves the two rows (4 ≥ 3, steps ≥ 3), cap 1. | — |
| 2026-11-04 | Implementation round (tester, round 2) | **Success** — [report](./tmp/reports/2026-11-03-gate-scope-echo-retirement-tester-2026-11-04.json): **500 passed, 0 failed, 500 total** (exit 0; three new tests up from 497); the 2026-11-03 SETUP flake did not recur. Step 4 prose-only and behavior-neutral (false framing gone from the whole tree by grep; pinning test still 1/1). Step 5's helper calibrated red-before/green-after on UNEDITED tests via a single-window mutant (`for _attempt in (1,)` — cases A and C fail with named diagnostics, B passes by design), then restored byte-identically (sha256 verified both sides). One recorded deviation: the host black-holes refused localhost connects (1 s per attempt), so the contract tests drive the READY event (case A) and stub `_harness.socket` with an always-refusing stub (all cases) — 0.50/0.00/0.60 s deterministic; Step 5's text carries the deviation note. The tester also corrected the plan's wrong Suite-notes claim (per-function `ALL_TESTS` registration IS required — plan text fixed this session). Out-of-scope observation dispositioned: the moved loop's refusal-path socket leak (pre-existing, harmless at scale) deferred as standalone `defer-issue-readiness-wait-socket-leak-on-refusal.json` — no adopting row. Planner's independent verification of the round's artifacts (substitute for the absent coder report): all three contract tests re-run green standalone (1/1 each), the pinning test 1/1, `_harness.py` parses with `_wait_for_readiness` present. | — |
| 2026-11-04 | Mega-audit (post-implementation) | Verdict **Issues found**: **0 High, 10 Medium, 17 Low** across 10 lenses — no re-iteration (needs ≥3 High; counters reset to 0 before fixes). Report [2026-11-03-gate-scope-echo-retirement-mega-audit-2026-11-04.json](./tmp/reports/2026-11-03-gate-scope-echo-retirement-mega-audit-2026-11-04.json) (written from the workflow result, validated by `report_check`). All 10 Mediums valid and dispositioned: **M1+M9+M11+M26** (one finding, four lenses) — the Step 5 planner-lane doc deliverable was unexecuted; fixed planner-side this session (harness contract row, three Category 9 entries, M16 reword, M24-doc cross-ref, stamps; `check_doc_anchors.py` green) and Step 3's evidence extended to name it. **M2+M19** (one finding, two lenses) — `os.walk`'s default `onerror=None` silently drops unlistable subdirectories, re-opening Step 1's silent-hole class; valid defect → **Step 6** (onerror→fatal + unlistable-dir test half, round 3). **M24** — deep-half overlaps `test_nesting_limit_admin_body`'s assertions on the same gate branch; disposition (b): trim the new test's deep half to its unique delta (response exists, no echo) → **Step 6**, doc cross-reference done planner-side. **M8** — `tests/_harness.py` invisible to the tester-files union → named under Tests-to-create. **M12** — Immediate Actions stale → regenerated. **M16** — doc cited transient `tmp/verification/` scripts as runnable commands → reworded to stable artifacts. Lows: L3 (snapshot/restore idiom) and L20 (read-error routing) folded into Step 6 alongside M24 — same files, no extra round; L4 (stub invariant comment) folded; L6 fixed planner-side (script comment); L14/L17 fixed in Step 3's evidence text; L27 fixed (stamps). L5/L7/L10/L18/L21/L22/L23/L25 acknowledged without fix (see below). | [audit-l5-no-rollback-section](./tmp/reports/2026-11-03-gate-scope-echo-retirement-mega-audit-2026-11-04.json) (test-only plan; git revert is the rollback — 2026-10-25 precedent), [audit-l7-str-headroom-figures-unreconciled](./tmp/reports/2026-11-03-gate-scope-echo-retirement-mega-audit-2026-11-04.json) (dated provenance from different machines/conditions, both recorded with sources), [audit-l10-adding-a-test-checklist](./tmp/reports/2026-11-03-gate-scope-echo-retirement-mega-audit-2026-11-04.json) (the contract tests were verified alone and in-suite; round 3 runs the suite again), [audit-l18-final-results-v1-deferred-table](./tmp/reports/2026-11-03-gate-scope-echo-retirement-mega-audit-2026-11-04.json) (v1 is marked SUPERSEDED; v2 rewrites), [audit-l21-window-s-unvalidated](./tmp/reports/2026-11-03-gate-scope-echo-retirement-mega-audit-2026-11-04.json) (single caller passes the constant; zero/negative degrades to immediate False, which is safe), [audit-l22-wall-clock-bands](./tmp/reports/2026-11-03-gate-scope-echo-retirement-mega-audit-2026-11-04.json) (bands carry generous slack; the READY-event drive + socket stub already removed the host-dependent timing the finding targets), [audit-l23-l25-doc-sync-unexecuted](./tmp/reports/2026-11-03-gate-scope-echo-retirement-mega-audit-2026-11-04.json) (duplicates of M1/M9/M11/M26 — fixed) |
| 2026-11-04 | Implementation round (tester, round 3) | **Success** — [report](./tmp/reports/2026-11-03-gate-scope-echo-retirement-tester-2026-11-04-2.json): **500 passed, 0 failed, 500 total** (exit 0), run with a live proxy up and untouched (isolation held). All five Step 6 items landed, each calibrated: (1) `_scan_dir` wires `os.walk`'s `onerror` into `fatal` (third test half RED against the default-`onerror` shape via a stubbed walk — the sanctioned portable route, since `chmod 0o000` is a no-op on Windows — GREEN after the wiring, test function byte-identical between runs, diff confined to `_scan_dir`); (2) read guard widened to `(OSError, ValueError)` for L20, RED/GREEN calibrated via the standalone script with sha256-verified restore; (3) deep half trimmed to its unique delta, discriminant re-measured post-trim (4/4 — the echo appears when the gate is disabled); (4) snapshot/restore idiom + epoch-unchanged assert on the switch pin; (5) `_always_refusing` states its process-global invariant. One deviation, recorded: the plan's snippet had `lines.append((False, fatal[-1]))` OUTSIDE the unlistable loop — IndexError in the common case and last-error-only otherwise; the landed code appends inside the loop (the planner's snippet bug, caught by the tester). Out-of-scope follow-up dispositioned: the read-error routing's permanent pin deferred as standalone `defer-issue-parse-guard-read-error-permanent-pin.json` (the branch is calibrated by the round's transient script only). Tester's doc discrepancy fixed planner-side: the Category 13 entry and module table row now state the fatal-routing behavior (`check_doc_anchors.py` green). Planner's independent verification: parse-guards module 4/4, the trimmed switch pin 1/1, the hung-alive contract test 1/1. | — |
| 2026-11-04 | Review (Phase 6 re-review, second pass) | Verdict **Issues found — non-blocking**: **0 Critical, 0 Warning, 5 Suggestions** — the commit gate passes; the reviewer's own closing line is "Ready to commit: yes". Report [2026-11-03-gate-scope-echo-retirement-review-2026-11-04.json](./tmp/reports/2026-11-03-gate-scope-echo-retirement-review-2026-11-04.json). The reviewer verified the launch's hunt list as sound: the trimmed deep half still discriminates the reordering (traced to server.py:3698-3704, not assumed), the shallow half keeps the echo branch live so the pair cannot green-light an echo-dropping handler, the stubbed walk cannot pass vacuously absent an unrelated fault, the harness helper is behavior-identical for real children except the intended second window, and the doc entries match the landed code. **S1+S2 (doc-side, planner lane) fixed immediately this session**: the headroom figure reworded to dated provenance (the test prints no measurements — the reviewer re-ran it to confirm), and the deep-half description rewritten to the post-trim delta; `check_doc_anchors.py` green after. **S3/S4/S5 (test-side hardening)** acknowledged and presented to the operator at the approval gate with an explicit round-4 option — the loop cap's final iteration: (S3) the died-during-window liveness check is unpinned (deleting it leaves all three contract tests green); (S4) the unlistable half's substring assertion could green via an unrelated read-error fatal that also names the sub path; (S5) case A's fixture carries ~0.15 s of scheduling slack, so a late Timer thread could false-FAIL the very test that exists to stop a load flake. Report hunches recorded for future plans: the walk's scope admits any `.py` under a non-module package directory; the pin constrains gate-before-echo but not gate-before-drain; two derived figures restated in test prose; `_READY_DEADLINE_SECONDS`'s comment still reads as a single bound. | [review2-s1-headroom-pointer-false](./tmp/reports/2026-11-03-gate-scope-echo-retirement-review-2026-11-04.json) (fixed this session), [review2-s2-deep-half-description-stale](./tmp/reports/2026-11-03-gate-scope-echo-retirement-review-2026-11-04.json) (fixed this session), [review2-s3-died-during-window-unpinned](./tmp/reports/2026-11-03-gate-scope-echo-retirement-review-2026-11-04.json) (operator decision pending), [review2-s4-unlistable-half-ambiguous-fatal](./tmp/reports/2026-11-03-gate-scope-echo-retirement-review-2026-11-04.json) (operator decision pending), [review2-s5-case-a-fixture-slack](./tmp/reports/2026-11-03-gate-scope-echo-retirement-review-2026-11-04.json) (operator decision pending) |
| 2026-11-04 | Spec revision (/update-plan, operator-directed) | At the approval gate the operator directed "fix now" for the two open micro-deferrals — both adopted as `Fix Planned` rows and **Step 7** written (socket closure on the refusal path via try/finally; permanent read-error pin as a RED/GREEN-calibrated test case). The round-4 question (review-2 S3/S4/S5, all Suggestions) was restated with options all-three / S4-only / acknowledge; the operator chose **(a) all three**, folded into Step 7 — round 4 is the loop cap's final iteration. On S3 the plan records the analysis: the call-counting-fake pin is behaviorally impossible (poll() is monotonic on a real process, so window 2's in-loop check observes the same death), so the reviewer's annotate route is taken. | — |
| 2026-11-04 | Implementation round (tester, round 4 — final cap iteration) | **Success** — [report](./tmp/reports/2026-11-03-gate-scope-echo-retirement-tester-2026-11-04-3.json): **500 passed, 0 failed, 500 total** (exit 0). All five Step 7 items landed with calibration: (1) socket closure via try/finally, MEASURED 6 created / 6 closed on the refusal path and 1/1 on success by the round's evidence script (10/10 checks) — the deferral's leak is closed by committed code, not narrative; one recorded deviation from the plan's snippet (creation kept inside the try with a None guard, preserving the retry-on-create-failure behavior — the planner's second snippet bug this plan, caught by the tester); (2) the read-error pin is a committed FOURTH half of `test_parse_guard_scanner_walks_subpackages` (PEP 263 latin-1 module → visible fatal), RED against `except OSError` with sha256-verified restore — the branch now survives this plan's retirement; (3) S3's annotation names the between-windows check as the extension's gate, redundant under today's loop shape, load-bearing under refactor; (4) S4's tightened half demands the `cannot list` marker + `sites == 2`, DEMONSTRATED to reject a read-error fatal that a bare substring match would have accepted; (5) S5 widened case A's slack to 0.32 s (window 0.4, marker at 1.2×) with the elapsed lower bound pinned at one full window. Both adopted rows → `Resolved`; their reports retire at Step 9.6 with the other four. Tester's doc discrepancy fixed planner-side: the Category 13 entry now names all four halves (doc gate green). Planner's independent verification: parse-guards module 4/4 (five PASS lines across the halves), case A 1/1. **Review decision:** the plan's pre-round note proposed skipping a third review pass; the flow-prescribed default (reviewer after the final round) is taken instead — the reviewer runs over the round-4 delta, superseding that note. | — |
| 2026-11-04 | Review (Phase 6, third pass — round-4 delta) | Verdict **Issues found — non-blocking**: **0 Critical, 0 Warning, 4 Suggestions** — "Ready to commit: yes". Report [2026-11-03-gate-scope-echo-retirement-review-2026-11-04-2.json](./tmp/reports/2026-11-03-gate-scope-echo-retirement-review-2026-11-04-2.json). All three of the launch's specific questions verified sound: the harness deviation (creation inside the try with the None guard) preserves the pre-change retry-on-create-failure path; the fourth scanner half cannot pass vacuously (`cannot read` is emitted only by the read branch, keyed to the exact path); the S5 arithmetic holds (1.2× marker can never be observed inside window 1). The four Suggestions: **(1)** the socket-leak fix has no committed regression guard — deleting the `finally` leaves the suite green, only the transient script measures 6/6 (the reviewer notes this is exactly the shape Step 7 judged insufficient for the sibling read-error routing); **(2)** the closure-protocol comment says "closes before its sleep" — the code closes after (finally); **(3)** a section header still says `window_s=0.3`; **(4)** Final Results v3 said "three halves" — fixed planner-side immediately this session (four halves, plan line ~505). Items 1-3 are tester-lane; the loop cap (4 iterations) is exhausted, so per the cap rule the planner stops and reports — the operator decides: one directed micro-round for all four, commit as-is, or defer item 1. | [review3-s1-socket-fix-unpinned](./tmp/reports/2026-11-03-gate-scope-echo-retirement-review-2026-11-04-2.json) (operator decision pending at the cap), [review3-s2-closure-comment-order](./tmp/reports/2026-11-03-gate-scope-echo-retirement-review-2026-11-04-2.json) (operator decision pending), [review3-s3-stale-window-header](./tmp/reports/2026-11-03-gate-scope-echo-retirement-review-2026-11-04-2.json) (operator decision pending), [review3-s4-final-results-three-halves](./tmp/reports/2026-11-03-gate-scope-echo-retirement-review-2026-11-04-2.json) (fixed this session) |
| 2026-11-04 | Spec revision (/update-plan, operator-directed cap override) | At the cap the operator chose **option (a)**: one directed micro-round (round 5) for all three tester-lane Suggestions. **Step 8** written: a counted-socket regression guard on the hung-alive case (the stub's `close()` gains class-level counters reset per test; the case asserts `created == closed`, `created >= 1`; RED-calibrated against the removed `finally` — the leak shape makes `created > closed`), the closure-comment correction (closes after the sleep, in `finally`), and the stale `window_s=0.3` header refresh. Counters: steps_changed +1. | [review3-s1-socket-fix-unpinned](./tmp/reports/2026-11-03-gate-scope-echo-retirement-review-2026-11-04-2.json), [review3-s2-closure-comment-order](./tmp/reports/2026-11-03-gate-scope-echo-retirement-review-2026-11-04-2.json), [review3-s3-stale-window-header](./tmp/reports/2026-11-03-gate-scope-echo-retirement-review-2026-11-04-2.json) (all three → Step 8, round 5 on operator direction) |
| 2026-11-04 | Implementation round (tester, round 5 — cap-override round) | **Success** — [report](./tmp/reports/2026-11-03-gate-scope-echo-retirement-tester-2026-11-04-4.json): **500 passed, 0 failed, 500 total** (exit 0). All three Step 8 items landed with calibration: (1) the socket-leak fix now has its committed regression guard — `_RefusingSocket` gained class-level created/closed counters surviving the module swap, and the hung-alive case (the only one driving two full windows of refusal-path probes) asserts `created == closed`, `created >= 1`; RED-measured against the removed `finally` ("the probe leaked 6 socket(s) (6 created / 0 closed)") with sha256-verified restore, GREEN after (6/6); no new test function (ALL_TESTS still 27 — the case was extended); (2) the closure comment states the real order (close in `finally`, after the 0.1 s sleep); (3) the header states each case's own two-window budget instead of the stale single-`window_s` claim. Round-5 evidence script: 19/19. Tester's doc discrepancy fixed planner-side: the Category 9 hung-alive entry now records the socket-hygiene pin (doc gate green). Planner's independent verification: the extended case 1/1 standalone, the full test_cli module 27/27. | — |

## Plan Metadata

Fenced ```json block — the machine contract read by `parsePlanContext` (JSON-first, regex fallback). **Update it on every revision.**

```json
{
  "plan_id": "2026-11-03-gate-scope-echo-retirement",
  "steps": ["Step 1: Make the parse-guard site enumeration recursive and pin it with a synthetic nested-site case", "Step 2: Pin the switch path's gate-before-echo ordering with a committed deep-key test", "Step 3: Record the by-construction evidence and reconcile the docs", "Step 4: Correct the pinning test's docstring to the reviewed account", "Step 5: Grant the readiness wait one liveness-gated extension", "Step 6: Mega-audit fixes — scanner error routing, deep-half trim, snapshot idiom, stub invariant", "Step 7: Close the two micro-deferrals — socket closure on the refusal path, permanent read-error pin", "Step 8: Third-pass fixes — committed socket-leak guard, closure-comment order, stale header"],
  "coder_files": [],
  "tester_files": ["tests/test_parse_guards.py", "tests/test_admin.py", "tests/_harness.py", "tests/test_cli.py"],
  "doc_files": ["./doc/test-catalog.html"],
  "verification_scripts": ["./tmp/verification/2026-11-03-gate-scope-echo-retirement-evidence.py", "./tmp/verification/2026-11-03-gate-scope-echo-retirement-discriminant.py"],
  "repo_mode": "Public",
  "document_overrides": []
}
```

## Audit Accumulation

*Counters reset when mega-audit runs. Used by Phase 5 entry trigger.*

| Counter | Value | Last Updated |
|---------|-------|--------------|
| issues_resolved_since_audit | 0 | 2026-11-04 |
| steps_changed_since_audit | 0 | 2026-11-04 |
| files_changed_since_audit | 0 | 2026-11-04 |

## Documentation

- [doc/test-catalog.html](doc/test-catalog.html) — reconciled in Step 3 (scope wording + per-test inventory).
- The deferral reports themselves are the reference for both issues'
  discovery context; they retire at `/update-and-commit` Step 9.6 once the
  Issue Log rows above reach `Resolved`.

## Final Results

**Status: COMPLETED (v4, 2026-11-04 — updated after round 5)**

> v2 covered steps 1-6; v3 added round 4 (Step 7); this refresh adds round 5
> (Step 8 — the cap-override round) and closes its pending caveats. History rows are
> the authoritative per-event record.

### What was built

Eight steps across five tester rounds and planner-lane doc work; **zero `src/` changes**
(operator decision, disposition A). Six standalone deferrals adopted and resolved —
all six retire at `/update-and-commit` Step 9.6; zero new open deferrals.

1. **Parse-guard gate walks the package tree** (`tests/test_parse_guards.py`): sorted
   `os.walk` replaces flat `os.listdir`; scan errors are visible — an unlistable
   subdirectory or an undecodable module surfaces as a `fatal` naming the path
   (`onerror` wired into the existing `fatal` channel; per-file read guard widened to
   the `OSError`/`ValueError` siblings), never a silent narrowing of the file set.
   Pinned by `test_parse_guard_scanner_walks_subpackages` (four halves: nested-site
   visibility, guarded variant, unlistable-dir fatal, undecodable-module fatal — each
   calibrated red against the pre-fix shape).
2. **Switch-path gate-before-echo ordering pinned** (`tests/test_admin.py`):
   `test_switch_nesting_gate_precedes_key_echo` proves, in-process, that the 500-level
   nesting gate answers before the switch branch's field validations echo their raw
   values. After the audit's deduplication trim the deep half asserts exactly its
   unique delta (a response exists; no `invalid key name`) — the shared gate branch's
   status/code/message stay pinned live-proxy-side by `test_nesting_limit_admin_body`,
   cross-referenced in the doc. The echo branch's liveness is kept by the shallow
   half; the discriminant was measured reachable (gate disabled in-process → the echo
   answers, 4/4). Closes `defer-issue-switch-key-name-container-echo` by construction:
   the gate bounds any wire container to `MAX_JSON_NESTING_DEPTH` minus its enclosing
   structure — measured 41.6× inside this interpreter's `str()` headroom, stable
   across three runs of the evidence script.
3. **Readiness wait gains one liveness-gated extension** (`tests/_harness.py`):
   `_wait_for_readiness` grants a still-alive child exactly one extra window after
   the first expires; dead children fail fast; hung-alive children are bounded at two
   windows. Three contract tests (`tests/test_cli.py`, fake proc + refusing-socket
   stub with a stated invariant) pin all three branches, calibrated red against a
   single-window mutant. Closes
   `defer-issue-suite-readiness-probe-timeout-recurrence` — the load-timing SETUP
   flake that failed 1 of 2 full-suite runs on 2026-11-03 did not recur in rounds 2
   or 3.
4. **Socket hygiene + permanent read-error pin + review-pass-2 hardenings (round 4,
   Step 7)**: `_wait_for_readiness` closes every probe socket exactly once on both
   paths (measured 6/6 refusal, 1/1 success); the read-error routing gained a
   committed fourth test half (PEP 263 undecodable module → visible fatal, RED against
   the pre-Step-6 guard); the extension's race gate is annotated (S3); the unlistable
   half demands the `cannot list` marker + `sites == 2`, demonstrated to reject an
   unrelated read-error fatal (S4); case A's fixture slack widened to 0.32 s (S5).
   Closes `defer-issue-readiness-wait-socket-leak-on-refusal` and
   `defer-issue-parse-guard-read-error-permanent-pin` — by committed code and a
   committed test, not transient scripts.
4b. **Round 5 (Step 8, cap-override round)**: the socket-leak fix gained its committed
   regression guard — the stub counts created/closed sockets and the hung-alive case
   (the only one driving two full windows of refusal-path probes) asserts
   `created == closed`; RED-measured against the removed `finally` (6 created /
   0 closed), sha256-verified restore. The closure comment and section header now
   match the code. Closes review-pass-3's three Suggestions.
5. **Docstring corrected** (`tests/test_admin.py`): the false "only key stringifies
   the raw object" framing replaced with the reviewed account (every failure branch
   formats its raw value; the isinstance test is the trigger, not a guard). Closes
   `defer-issue-test-docstring-echo-uniqueness-claim`.
6. **Docs reconciled across all passes** (`doc/test-catalog.html`): scope wording +
   four-half scanner pin description, harness contract row, Category 13 / admin /
   Category 9 entries, references to transient verification scripts reworded to stable
   artifacts, `Last updated` stamps advanced. `check_doc_anchors.py` green throughout.

### Test results

- Round 1 (Steps 1-2): 497 passed, 0 failed (authoritative run 2 of 2; run 1 carried
  the pre-existing readiness flake this plan then fixed).
- Round 2 (Steps 4-5): 500 passed, 0 failed, exit 0.
- Round 3 (Step 6): 500 passed, 0 failed, exit 0 — run with a live proxy up, isolation
  held.
- Round 4 (Step 7): 500 passed, 0 failed, exit 0; the round's own evidence script
  adds 10/10 checks (socket create/close counts on both paths; the tightened
  assertion demonstrated to reject an unrelated read-error fatal; the slack
  arithmetic stated).
- Round 5 (Step 8): 500 passed, 0 failed, exit 0; evidence script 19/19 (the guard's
  RED run measured "6 created / 0 closed" against the leak shape before the
  sha256-verified restore).
- Planner's independent verification each round (substitute for the absent coder
  report, recorded in the History rows): targeted re-runs green every time.
- Reviewer's second-pass spot checks: the trimmed switch pin 1/1, parse-guards 4/4
  (23/23 sites guarded), doc anchors green.

### Review verdicts

- First pass (2026-11-03): non-blocking — 0 Critical, 1 Warning, 2 Suggestions; all
  three fixed in planner artifacts the same round (the Warning superseded the
  deferral's "only key" framing).
- Mega-audit (2026-11-04, post-implementation): 0 High, 10 Medium, 17 Low; all 10
  Mediums fixed (four planner-side, the rest via Step 6), select cheap Lows folded
  into Step 6, the rest acknowledged with reasons.
- Second pass (2026-11-04): non-blocking — 0 Critical, 0 Warning, 5 Suggestions; the
  two doc-side ones fixed immediately, three test-side hardenings acknowledged and
  presented to the operator with a round-4 option (see Known caveats).

### Known caveats

- None open from this plan. Review-pass-3's three Suggestions landed in round 5 (the
  operator-directed cap-override round); every review pass and the mega-audit returned
  zero Critical findings; every finding across all passes is fixed or explicitly
  dispositioned in History.
- Pre-existing, observed, not filed: the doc's older entries (2026-10-12/2026-10-15
  eras) also cite `tmp/verification/` proof scripts as provenance — the same
  transient-reference family as audit M16, outside this plan's diff.

### Deferred issues (corpus state at completion)

| Deferral | State |
|---|---|
| `defer-issue-parse-guard-gate-top-level-scope` | **Adopted, Resolved** — retires at Step 9.6 |
| `defer-issue-switch-key-name-container-echo` | **Adopted, Resolved** — retires at Step 9.6 |
| `defer-issue-suite-readiness-probe-timeout-recurrence` | **Adopted, Resolved** — retires at Step 9.6 |
| `defer-issue-test-docstring-echo-uniqueness-claim` | **Adopted, Resolved** — retires at Step 9.6 |
| `defer-issue-readiness-wait-socket-leak-on-refusal` | **Adopted, Resolved** — retires at Step 9.6 |
| `defer-issue-parse-guard-read-error-permanent-pin` | **Adopted, Resolved** — retires at Step 9.6 |
| `defer-issue-httpx2-native-sse-transport` | Open, untouched (its own future plan) |
| `defer-issue-orphaned-test-state-files` | Open, untouched |

## Cross-References to Prior Plans

| Prior Plan | Deferred Issue | Resolution |
|------------|---------------|------------|
| 2026-10-25-guard-totality-and-blank-admin | defer-issue-parse-guard-gate-top-level-scope | Step 1 made `_scan_dir` walk the package tree and pinned the recursion with a synthetic nested-site test; Step 6 (audit) added the error-routing fatal so the walk cannot silently narrow the file set |
| 2026-10-25-guard-totality-and-blank-admin | defer-issue-switch-key-name-container-echo | Step 2 pinned the gate-before-echo ordering on the switch path and closed the deferral by construction (disposition A; the 500-level gate from commit 6d4b4ff had already bounded the path) |
