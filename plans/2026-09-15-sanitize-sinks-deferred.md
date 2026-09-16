# Plan: Resolve the sanitize/sinks deferred cluster (issues #3–#7)
**Project:** D:\proj\claude-retry-proxy
**Plan ID:** 2026-09-15-sanitize-sinks-deferred
**Created:** 2026-09-15

<!-- ## Immediate Actions: absent from initial plans. Populated by /update-plan for revised plans, replaced (not accumulated) on each revision. Contains per-role action-only directives (no rationale) telling agents what to do next. Agents read the full plan for context. -->

## Issue Log

Rows ordered newest-first (latest issues at top). New issues are prepended; resolved issues stay in place with updated status.

| Issue | Status | Found | Resolved | Resolved By |
|-------|--------|-------|----------|-------------|

## Guidance for Coder

**Files to modify:**
- `src/claude_retry_proxy/sanitize.py` — rewrite `sanitize_error` (Steps 1 only)
- `src/claude_retry_proxy/sinks.py` — rewrite `StateSink._emit` (Step 2 only)

Do NOT touch tests (all of `tests/`), docs (`CLAUDE.md`, `doc/**`), or any other
source module. Do NOT change `sanitize_error`'s signature or contract: same
single `msg` parameter, `None` for falsy input, `str` out, `[:200]` truncation
applied last. Do NOT add a lock to `StateSink` — the unique-temp design makes
one unnecessary. The two verification scripts must FAIL against pre-fix `src/`;
they are gating by design, run them after your edits.

**Step-by-step with verification:** each step above has coder checks tagged `(auto)` or `(scripted)`. The coder self-verifies `(auto)` checks and runs the provided script for `(scripted)` checks. Tester owns the behavioral checks. See coder Prime Directive 4.

This cluster resolves five deferred issues:
`sanitize-error-path-redaction-inert-on-windows` (#4),
`sanitize-error-regex-catastrophic-backtracking` (#5),
`write-state-no-lock-concurrent-replace` (#3),
`state-sink-empty-path-stray-tmp` (#7), and
`sink-chmod-branch-untested-outside-posix` (#6) — all filed from plan
2026-09-11-extract-sinks. The fix designs were validated by direct probe on
2026-09-15; the exact target code carries the validation.

## Guidance for Tester

**Tests to create:**
- **Permanent:** `tests/test_sanitize.py` — new cluster module (Step 4): table-driven redaction cases, boundary cases, truncation, and the linear-time bound.
- **Permanent:** additions to `tests/test_sinks.py` (Step 5): POSIX-gated chmod mode/swallow test, empty-path rejection with no stray file, concurrent-writer integrity test.
- **Permanent:** register `test_sanitize.py` in the aggregator `tests/test_claude_proxy.py` (import `ALL_TESTS as SANITIZE_TESTS`, append to the combined list following the existing per-module pattern).

**Tests to investigate for retirement:**
- Planner candidates: none — no existing test references `sanitize_error` (verified by repo-wide scan during planning), and the `StateSink` contract (write returns True/False, no leftover after replace) is unchanged. Explicitly: **No test obsolescence identified.**
- Tester may identify additional candidates during test work.

**Retirement procedure:** For each candidate, verify the test exercises code being removed/changed. If obsolete: delete and note in session report. If still valid: document why in session report (e.g., "tests error handling path still present").

**Harness notes:** no skip convention exists in `_harness.py` — for the POSIX-gated chmod test, use an inline platform check (`if os.name != "posix": pass_(...); return`) with a message + docstring stating the skip on the Windows dev box is by design (a future reader must not delete a permanently-skipped test). Patch `claude_retry_proxy.sinks.os.chmod` via `unittest.mock` for the swallow case. For the timing-bound test, follow Step 4's recipe exactly — a subprocess with a hard timeout; never a thread + `join` (a regressed exponential match holds the GIL for the whole match and hangs the suite).

## Summary

Five defects filed from the 2026-09-12 sanitize/sinks extraction (`extract-sinks`), all in the two leaf modules it created, are resolved in one pass:

- **#4 Windows-inert path redaction:** `sanitize_error`'s first regex arm requires a forward slash, so native Windows OSError paths (`C:\Users\wsong\.claude\...`) — the exact message class the sink-failure warning emits on Windows — pass through unredacted, and forward-slash Windows paths leak a `C:` remnant.
- **#5 ReDoS:** the same arm's `(?:/[^\s"]*)+` nests a `*` inside a `+` over an overlapping class, backtracking exponentially (measured 2026-09-15: 16 slashes 0.003 s → 24 slashes 0.70 s; ~40 slashes is unbounded). Upstream-controlled error bodies can pin a worker thread.
- **#3 interleaving state writes:** `StateSink._emit` writes through a fixed `"<path>.tmp"` with no lock, so the heartbeat and start threads can truncate/interleave each other before `os.replace`.
- **#7 stray `.tmp`:** with an empty state path, `open(".tmp", "w")` succeeds in the CWD and only the final replace fails, stranding an ungitignored `.tmp` at the repo root.
- **#6 untested chmod branch:** the POSIX-only `os.chmod(0o600)` in `_Sink.write` has never executed under test on the Windows dev box.

**Approach.** One rewrite fixes both sanitize defects: split error text on whitespace/double-quote delimiters and replace any token containing a separator-prefixed sensitive dotdir segment (`.claude`, `.ssh`, `.gnupg`, `.aws`, `.azure`, `.config`, `.local`, word-bounded) with `[redacted-path]`. The token scan has no nested quantifiers — linear in input length by construction (measured 2026-09-15: 200k slashes/backslashes/letters ≈ 3–8 ms; the prototype matched every verified case). Whole-token semantics (confirmed with the user) deliberately err toward more redaction: native Windows paths now redact fully, the `C:` remnant is gone, attached prefixes (`error:`) and the stray-quote artifact in `Permission denied: '[redacted-path]` are cleaned up, and a new `\b` guard stops `.claudefoo`-style false positives. The IP arm, the `[:200]` truncation, and the `None`-for-empty contract are unchanged. The rewrite is Python 3.8-safe (no atomic groups).

The state sink fix (confirmed with the user: mkstemp over a lock) makes writes mutually safe without a mutex: unique per-write temp names via `tempfile.mkstemp` in the target directory eliminate interleaving, `os.replace` stays atomic (last writer wins), a fast-fail on an empty path stops any file from ever being created (raising `ValueError`, which the existing `_Sink.write` swallow converts to the normal `False` + rate-limited stderr warning), and a failed serialization now unlinks its temp file. mkstemp's default `0600` also means the temp is never world-readable on POSIX, complementing #6's concern. #6 itself is closed by a POSIX-gated test pair pinning both properties (landed mode `0600`, chmod-failure swallow).

```
sanitize_error (rewritten, sanitize.py)          StateSink._emit (rewritten, sinks.py)
  split on \s+ | "                                 not path             -> raise ValueError (caught -> False+warning)
  per token: [/\\]\.(claude|ssh|gnupg|aws|         mkstemp(dir=dirname)   -> unique temp, 0600
             azure|config|local)\b ?               fdopen/write json      -> unlink tmp on failure
  yes -> whole token "[redacted-path]"             os.replace             -> atomic, last writer wins
  IP re.sub (unchanged)
  [:200] (unchanged, last)
```

**Alternatives rejected:** (1) a lock + fixed temp name for #3 — more code, same observable behavior, still needs the empty-path guard; (2) a regex-only redaction rewrite keeping nested quantifiers — no such pattern can be both linear and separator-agnostic, because any overlapping prefix/separator classes re-introduce a quadratic-or-worse scan over adversarial runs.

**Rollback:** the changes are confined to two leaf modules with unchanged public signatures. Rollback is a single `git revert` of the implementation commit; the CLAUDE.md/doc edits (Steps 6–7) live in the same commit, so a revert undoes them together. After a revert, the two verification scripts fail against the restored code by design — exclude them from gating rather than leaving them red; the new permanent tests fail too for the same reason and go out with the same revert.

**Explicitly out of scope:** issue #9 (`extract_model` raising on non-object JSON — different module and defect family), all other remaining deferred issues, and the larger `break-up-large-source-and-test-files` decomposition.

## Repo Mode

Public

*Detected at plan creation. Determines: plan archival path, commit-message content, staged files.*

## Proposed Changes

Each step includes verification checks tagged with confidence (see Prime Directive 4).
`(auto)` = mechanical, coder self-verifies. `(scripted)` = deterministic multi-step, coder runs provided script.
Every step must have at least one verification check executable by its owner (coder steps: coder checks; tester steps: tester verify; planner steps: Evidence).
Steps MUST use this numbered-list format exactly. The `### Step N:` heading format is deprecated and must not be used.

Steps 4–5 require Steps 1–2 landed first (the tests assert the fixed behavior; the Step 1–2 scripts fail against pre-fix `src/` by design, so a stale checkout is caught before the tester starts).

1. **Step 1:** Rewrite `sanitize_error` in `src/claude_retry_proxy/sanitize.py` to the token-scan design (fixes #4 and #5). Replace the current two-`re.sub` body with the exact target below, keeping the module docstring's first line accurate and adding the function docstring shown:

   ```python
   # IGNORECASE: Windows paths (the class issue #4 is about) are case-insensitive,
   # so a capitalized dotdir (.CLAUDE) is still a sensitive segment.
   _SENSITIVE_SEGMENT_RE = re.compile(
       r"[\\/]\.(?:claude|ssh|gnupg|aws|azure|config|local)\b", re.IGNORECASE)


   def sanitize_error(msg):
       """Redact sensitive home-directory paths and IPv4 addresses from error text.

       Path redaction runs on whitespace- and double-quote-delimited tokens: a
       token containing a separator-prefixed sensitive dotdir segment (`.claude`,
       `.ssh`, `.gnupg`, `.aws`, `.azure`, `.config`, `.local`, any casing) is
       replaced whole. The token scan is linear in the input length — no nested
       quantifiers — so adversarial error text cannot trigger exponential
       backtracking. A message object whose `__str__` itself raises propagates:
       every internal caller passes an already-`str()`-ed exception, and any
       future direct caller must guard accordingly.
       """
       if not msg:
           return None
       msg = str(msg)
       msg = "".join(
           "[redacted-path]" if _SENSITIVE_SEGMENT_RE.search(part) else part
           for part in re.split(r'(\s+|")', msg))
       msg = re.sub(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b",
                    "[redacted-ip]", msg)
       return msg[:200]
   ```

   The IP `re.sub` arm and the `[:200]` truncation are unchanged by design; the first (path) arm is replaced entirely by the split+scan above; `re.sub` remains used (IP arm), so keep `import re`.
   → coder verify (auto): `_SENSITIVE_SEGMENT_RE` defined at module level before `sanitize_error` (read the lines); `def sanitize_error(msg):` is the unchanged signature and the body's first statement is `if not msg:` returning `None` (read the first three body lines)
   → coder verify (auto): the old pattern string `(?:/[^\s"]*)+` appears nowhere in `src/claude_retry_proxy/sanitize.py` (grep → 0 matches); the module still imports `re` only
   → coder verify (scripted): run `python ./tmp/verification/2026-09-15-sanitize-sinks-deferred-step1.py` from the project root — exit 0 and prints the single-line PASS (the full redaction table: every dotdir × every path shape, upper-case variants, `\b` boundary cases, IP arm, truncation, None/empty, `0` → None; plus a subprocess-guarded 200k-slash timing bound — a subprocess with a hard timeout, because a regressed exponential match holds the GIL and would starve any in-process probe). It must FAIL against the pre-fix module first
   → tester verify: the `tests/test_sanitize.py` cluster (Step 4) passes — every table case, the boundary cases, and the 64-slash threaded timing bound

2. **Step 2:** Rewrite `StateSink._emit` in `src/claude_retry_proxy/sinks.py` (fixes #3 and #7). Add `import tempfile` to the imports, replace the class docstring and `_emit` body with:

   ```python
   class StateSink(_Sink):
       """Atomic replace of one JSON document. Unique per-write temp names make
       concurrent writers safe without a mutex; an empty path is rejected before
       any file is created."""

       def __init__(self, path, name="state", health=None):
           super().__init__(path, name, health)

       def _emit(self, payload):
           if not self._path:
               raise ValueError("state sink path is empty")
           fd, tmp = tempfile.mkstemp(dir=os.path.dirname(self._path))
           try:
               try:
                   f = os.fdopen(fd, "w", encoding="utf-8")
               except Exception:
                   os.close(fd)
                   raise
               with f:
                   json.dump(payload, f)
               os.replace(tmp, self._path)
           except Exception:
               try:
                   os.unlink(tmp)
               except OSError:
                   pass
               raise
   ```

   Every failure path — `fdopen`, serialization, *and* `os.replace` — unlinks the unique temp before re-raising, so no failure can strand a `mkstemp` file (a replace failure is realistic on Windows when a reader holds the state file open; with unique names each such failure would otherwise accumulate a permanent orphan). The `os.close(fd)` arm covers a raising `fdopen` without leaking the descriptor. `encoding="utf-8"` makes the serialization locale-independent (non-ASCII state survives on non-UTF-8 Windows locales). `mkstemp(dir=...)` inherits `_Sink.write`'s existing `os.makedirs` pre-emit self-heal, so a missing parent directory is still re-created before the temp lands — the only new rejections are the empty path and genuine filesystem failures, both of which already ride the documented swallow.

   Relative paths keep today's semantics (install into `os.getcwd()`), because both `mkstemp(dir="")` and `os.replace` resolve against the CWD exactly as the old `<path>.tmp` did. Leave `_Sink.write`'s POSIX `chmod(0o600)` branch untouched — that is #6's territory, closed by tests in Step 5, not by a source change. Do NOT add a lock.
   → coder verify (auto): `import tempfile` in the imports; `if not self._path:` is the first statement of `StateSink._emit`, before any filesystem call (read the body); `tempfile.mkstemp(` and `os.fdopen(fd, "w")` and `os.replace(tmp, self._path)` each appear exactly once in `sinks.py`; the string `self._path + ".tmp"` appears nowhere in `sinks.py` (grep → 0 matches)
   → coder verify (scripted): run `python ./tmp/verification/2026-09-15-sanitize-sinks-deferred-step2.py` from the project root — exit 0 and prints the single-line PASS (round-trip incl. a non-ASCII payload, + no leftovers after success; empty path → `False` with no file created in the CWD; unserializable payload → `False` with the temp unlinked; patched-`os.replace` failure → `False` with no leftover temp; 100-thread concurrent writes → file holds exactly one complete payload, no leftovers). It must FAIL against the pre-fix module first (the deterministic empty-path/leftover sub-checks guarantee the script-level gate even though the concurrency sub-check alone is timing-dependent)
   → tester verify: the three new `tests/test_sinks.py` tests (Step 5) pass, including the concurrency smoke test

3. **Step 3:** Build + import sanity. Run `pip install -e .` (the repo's documented build; must remain the editable install) and confirm the leaf modules import and resolve into this repo's `src/`.
   → coder verify (auto): `pip install -e .` exits 0; `python -c "import claude_retry_proxy.sanitize as s, claude_retry_proxy.sinks as k; print(s.__file__); print(k.__file__)"` prints both paths under this repo's `src/` (not site-packages)

4. **Step 4:** Create `tests/test_sanitize.py` and register it in the aggregator (tester). Follow `tests/test_sinks.py`'s module shape: import `pass_`, `fail`, `warn` from `_harness`; export `ALL_TESTS = [...]` of `(name, func)` pairs; register in `tests/test_claude_proxy.py` as `from test_sanitize import ALL_TESTS as SANITIZE_TESTS` appended into the combined list. Direct-import style: `from claude_retry_proxy.sanitize import sanitize_error` and build Windows-separator inputs with `chr(92)` joins, never literal escapes (quoting-independent, matching the issue reports' reproduction convention). Required cases (the planner-validated table — assert exact outputs):
   - each sensitive dotdir (`claude`, `ssh`, `gnupg`, `aws`, `azure`, `config`, `local`) × 3 shapes (`/home/wsong/.D/x`, native `C:\Users\wsong\.D\x`, forward-slash `C:/Users/wsong/.D/x`) → `[redacted-path]`
- case variants (from the `re.IGNORECASE` compile): `/home/wsong/.CLAUDE/x` → `[redacted-path]`; native `C:\Users\WSONG\.Claude\x` → `[redacted-path]`
   - `[Errno 13] Permission denied: '/home/wsong/.claude/logs/proxy-trace.jsonl'` → `[Errno 13] Permission denied: [redacted-path]` (no stray quote)
   - `error:/home/u/.claude/x err` → `[redacted-path] err`; `see/.aws/x` → `[redacted-path]`; `visit .aws.amazon.com docs` → unchanged; `x/.claudefoo/y` → unchanged (`\b` guard); `.claude` as a bare token → unchanged (no preceding separator)
   - IP arm: `ip 192.168.1.50 here` → `ip [redacted-ip] here`; `nope 1234.56.78.90` → unchanged (5-digit first octet fails `\b\d{1,3}`)
   - both arms together: a message carrying an IP and a Windows `.gnupg` path redacts both
   - `sanitize_error(None)`, `sanitize_error("")`, and `sanitize_error(0)` → `None` (the falsy-input contract, pinned so a future edit can't drift it); a 300-char plain message → exactly its first 200 chars; an `OSError` instance whose text contains a path → redacted (non-str input via `str()`). No test for a `__str__`-raising object — that propagation is documented in the function docstring, not pinned in the table
   - linear-time bound (the ReDoS tripwire): run `sanitize_error("/" * 64)` in a **subprocess with a hard timeout** — `subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, timeout=20)` with the probe printing the elapsed seconds; FAIL on `TimeoutExpired` or `returncode != 0`; PASS with the measured ms when fast. Do NOT use a thread + join: a regressed exponential match holds the GIL for the whole match, starving the main thread and hanging the suite instead of failing it. The pre-fix regex on 64 slashes is effectively unbounded (2^64 partitions)
   → tester verify: standalone cluster run passes (`python tests/test_claude_proxy.py -t <new names>`); every assertion uses the harness `fail()` so a mismatch registers as a FAIL, not a crash

5. **Step 5:** Add four tests to `tests/test_sinks.py` (tester), reusing its existing `_FakeClock`/`_FakeReport` helpers where needed:
   - `test_chmod_posix_mode_and_swallow` — POSIX-gated: if `os.name != "posix"`, emit `pass_("skipped on Windows — POSIX chmod branch by design; see test docstring")` and return. On POSIX: (a) after `TraceSink.write` and `StateSink.write` to separate temp paths, `stat.S_IMODE(os.stat(path).st_mode) == 0o600` for both; (b) with `unittest.mock.patch("claude_retry_proxy.sinks.os.chmod", side_effect=OSError(...))`, `write()` still returns `True` and the payload landed (read back the file). Docstring must state the skip rationale.
   - `test_state_sink_empty_path_rejected_no_stray_tmp` — name-pinned assertion: after `StateSink("").write({...})` returns `False`, the file `.tmp` does not exist at `os.getcwd()` (whatever the CWD is — never assume the repo root; this catches the pre-fix stray `.tmp` deterministically, where a before/after set-diff snapshot could be tripped by any concurrent CWD writer). An optional set-diff snapshot is allowed as a secondary signal, not the primary assertion.
   - `test_state_sink_replace_failure_leaves_no_temp` — `unittest.mock.patch("claude_retry_proxy.sinks.os.replace", side_effect=PermissionError(13, "denied"))`; `write()` returns `False`; and no `mkstemp`-named leftover remains in the target directory (pins the `os.replace`-inside-try unlink arm).
   - `test_state_sink_concurrent_writes_last_writer_wins` — N threads (≥16) each writing a distinct payload through one `StateSink` to one temp path; join all; the file must parse as JSON and equal exactly one of the payloads (no interleaving/corruption), and the target directory holds no leftover temp files afterwards.
   → tester verify: all four new tests pass on the dev box (the chmod pair skips with notice on Windows); full suite run remains green — re-derive the expected total from `python tests/test_claude_proxy.py --list` at run time (never carry a remembered figure), 0 failed, only the known `No proxy_stop event in trace` warning (deferred issue #12, unrelated)

6. **Step 6:** Update `doc/test-catalog.html` (planner). Every figure the plan's changes make stale: (1) the snapshot banner's test count and file count (`N test functions across 17 files` — the new `tests/test_sanitize.py` is file 17; N re-derived from `python tests/test_claude_proxy.py --list`, never from memory); (2) the per-module catalog table — bump the `test_sinks.py` row to its new test count and add a `test_sanitize.py` row; (3) add per-test index entries for every new test from Steps 4–5 in the existing format, noting the chmod pair is skipped-on-Windows by design in its entry line; (4) refresh the Last-updated footer.
   → Evidence: `python scripts/check_doc_anchors.py` exits 0; `grep -c` over test-catalog.html shows one entry per new test name; the banner total equals the `--list` count captured by the command output and the file count reads 17; the `test_sinks.py` table row matches its actual `ALL_TESTS` length

7. **Step 7:** Update `CLAUDE.md` (planner): remove the five rows `write-state-no-lock-concurrent-replace`, `sanitize-error-path-redaction-inert-on-windows`, `sanitize-error-regex-catastrophic-backtracking`, `state-sink-empty-path-stray-tmp`, `sink-chmod-branch-untested-outside-posix` from the `## Unresolved Deferred Issues` JSON (7 remain), and revise the Future Work paragraph: count five as resolved by this plan, keep the unchanged list accurate. The five `defer-issue-*.json` reports stay in `tmp/reports/` as resolution history (matching the six already-unindexed resolved reports — do not delete them).
   → Evidence: `python -c "<parse the fenced JSON block>"` exits 0 printing 7 entries with none of the five ids present; `grep -c` on the five `issue_id`s in CLAUDE.md → 0 matches each

## Guidance for Planner

Documentation tasks you will execute yourself (not the coder):

- **Doc files to create/update:** `doc/test-catalog.html` (Step 6), `CLAUDE.md` (Step 7)
- **When:** after the tester's final session report shows the suite green (Steps 4–5 both verified). Nothing before coder starts — no doc claims the current defective behavior, so nothing would rot during implementation (`doc/architecture.html`'s "writes a temporary file, and renames it into place" formulation stays true under mkstemp; no doc pins the fixed `.tmp` name or the old regex).
- **What to sync:** the test catalog's banner counts, per-module table, per-test index, and footer (Step 6's full list); CLAUDE.md's deferred-issue index and Future Work prose. `doc/architecture.html` is deliberately NOT changed — evidence: `grep -n` of `doc/architecture.html` for the fixed temp-name residue (`.tmp`) returns 0 matches, and its "writes a temporary file, and renames it into place" formulation stays true under mkstemp (capture both command outputs when executing Step 6). At plan completion, verify the five `defer-issue-*.json` report statuses are flipped to resolution-type records per the defer-issue lifecycle (as the six unindexed resolved reports are) when the commit flow runs.

## History

One row per event (spec revision / mega-audit / review / implementation round). Conclusion = one-sentence outcome or what changed. Dismissed = compact dismissed-findings list for the reviewer — verbatim issue slugs linked as `[<slug>](<report-path>)`, no prose-only entries (the update-and-commit cross-ref and the reviewer both match these cells verbatim). Link to report files; never restate findings inline.

| Date | Event | Conclusion | Dismissed |
|------|-------|------------|-----------|
| 2026-09-15 | Initial plan | Resolves the five extract-sinks deferred issues (#3–#7): token-scan sanitize rewrite (Windows redaction + linear-time), mkstemp state-sink hardening (interleaving + stray .tmp), POSIX-gated chmod tests; scope and both fix designs confirmed by the user | — |
| 2026-09-15 | Mega-audit | 0 High, 6 distinct Medium, remainder Low; all Mediums fixed (replace-failure unlink + fd hygiene, subprocess-vs-thread contradiction, rollback note, catalog figures, CWD pin); Low fixes folded in (IGNORECASE, utf-8, `0`→None pin, count-free descriptions); report: ./tmp/reports/2026-09-15-sanitize-sinks-deferred-mega-audit-2026-09-15.json | [hardcoded-dotdir-allowlist](./tmp/reports/2026-09-15-sanitize-sinks-deferred-mega-audit-2026-09-15.json), [whitespace-in-path-partial-redaction](./tmp/reports/2026-09-15-sanitize-sinks-deferred-mega-audit-2026-09-15.json) |
| 2026-09-16 | Review | Verdict: Issues found — non-blocking (0 Critical, 0 Warning, 2 Suggestions); both rewritten modules match the plan's target code verbatim and the failure-unlink/fd-hygiene arms from the mega-audit are present; report: ./tmp/reports/2026-09-15-sanitize-sinks-deferred-review-2026-09-16.json | [codegraph-row-removal-outside-step-7](./tmp/reports/2026-09-15-sanitize-sinks-deferred-review-2026-09-16.json), [dead-module-level-run-cli-import](./tmp/reports/2026-09-15-sanitize-sinks-deferred-review-2026-09-16.json) |

## Plan Metadata

Fenced ```json block — the machine contract read by `parsePlanContext` (JSON-first, regex fallback). **Update it on every revision** — the rule-enforcer lens files a Medium finding when it is missing, invalid, or out of sync with the prose sections. Field semantics: `steps` = one title per `## Proposed Changes` step (numbering + first phrase; extra prose detail on either side is not a mismatch); `tester_files` = Tests to create + Verification scripts to create + Tests to investigate for retirement (mirrors the fallback's three-marker union); `doc_files` = the planner's `**Files to modify:**` list; `verification_scripts` entries shaped `./tmp/verification/<name>.py`; `repo_mode` = `Private` or `Public`; `document_overrides` = the `## Document Overrides` rows as formatted strings.

```json
{
  "plan_id": "2026-09-15-sanitize-sinks-deferred",
  "steps": [
    "Step 1: Rewrite sanitize_error in src/claude_retry_proxy/sanitize.py",
    "Step 2: Rewrite StateSink._emit in src/claude_retry_proxy/sinks.py",
    "Step 3: Build + import sanity",
    "Step 4: Create tests/test_sanitize.py and register it in the aggregator",
    "Step 5: Add four tests to tests/test_sinks.py",
    "Step 6: Update doc/test-catalog.html",
    "Step 7: Update CLAUDE.md"
  ],
  "coder_files": [
    "src/claude_retry_proxy/sanitize.py",
    "src/claude_retry_proxy/sinks.py"
  ],
  "tester_files": [
    "tests/test_sanitize.py",
    "tests/test_sinks.py",
    "tests/test_claude_proxy.py"
  ],
  "doc_files": [
    "doc/test-catalog.html",
    "CLAUDE.md"
  ],
  "verification_scripts": [
    "./tmp/verification/2026-09-15-sanitize-sinks-deferred-step1.py",
    "./tmp/verification/2026-09-15-sanitize-sinks-deferred-step2.py"
  ],
  "repo_mode": "Public",
  "document_overrides": []
}
```

## Audit Accumulation

*Counters reset when mega-audit runs. Used by Phase 5 entry trigger.*

| Counter | Value | Last Updated |
|---------|-------|--------------|
| issues_resolved_since_audit | 0 | 2026-09-15 |
| steps_changed_since_audit | 0 | 2026-09-15 |
| files_changed_since_audit | 0 | 2026-09-15 |

## Documentation

- `./tmp/verification/2026-09-15-sanitize-sinks-deferred-step1.py` — coder `(scripted)` check for Step 1: the full redaction table (every dotdir × every path shape, upper-case variants, boundary cases, IP arm, truncation, None/empty/0) + subprocess-guarded 200k-slash linear-time bound. Stdlib only; exit 0 = single-line PASS; must FAIL against pre-fix `src/`.
- `./tmp/verification/2026-09-15-sanitize-sinks-deferred-step2.py` — coder `(scripted)` check for Step 2: round-trip (incl. non-ASCII) + leftover scan, empty-path CWD scan, failure-unlink (unserializable payload and patched-`os.replace`), 100-thread concurrency integrity. Stdlib only; exit 0 = single-line PASS; must FAIL against pre-fix `src/` — script-level determinism comes from the empty-path/leftover sub-checks, which hold regardless of whether the timing-dependent concurrency sub-check fires alone.

## Final Results

**Status: COMPLETED** (2026-09-16)

Implementation, testing, review, and documentation reconciliation are all
complete. Coder report (Steps 1–3 done, `build_result: pass`, both scripted
gates PASS post-fix and FAIL pre-fix): ./tmp/reports/2026-09-15-sanitize-sinks-deferred-coder-2026-09-15.json.
Tester report (`overall_result: SUCCESS`): ./tmp/reports/2026-09-15-sanitize-sinks-deferred-tester-2026-09-15.json.
Full suite: **318 passed, 0 failed** (1 POSIX-gated pass-with-notice by design,
not a failure); the only warning is the known `No proxy_stop` (deferred issue
`no-proxy-stop-trace-warning`, unrelated). One tester-side first-run failure
(over-asserted concurrency contract) was a test bug, not a plan issue;
revised and re-run green. Reviewer verdict: non-blocking — 0 Critical,
0 Warning, 2 Suggestions (acknowledged in the Review History row).

Known caveats: the POSIX chmod branch executes only under its POSIX-gated test
(skipped with notice on the Windows dev box by design — verified by inspection
plus the tester's gated test); the CLAUDE.md edit for this plan rides in the
same working tree as the earlier user-approved `codegraph-prompt-hook` index
removal (reviewer Suggestion, acknowledged); `tests/test_sanitize.py` carries a
dead module-level `run_cli` import (reviewer Suggestion, acknowledged).

## Cross-References to Prior Plans

| Prior Plan | Deferred Issue | Resolution |
|------------|---------------|------------|
| 2026-09-11-extract-sinks | `sink-chmod-branch-untested-outside-posix` | POSIX-gated chmod test added — landed mode 0600 pinned for both sinks, chmod failure swallowed (test_chmod_posix_mode_and_swallow) |
| 2026-09-11-extract-sinks | `state-sink-empty-path-stray-tmp` | Empty state path is rejected before any filesystem call — no stray `.tmp` can be created (test_state_sink_empty_path_rejected_no_stray_tmp) |
| 2026-09-11-extract-sinks | `sanitize-error-regex-catastrophic-backtracking` | Token-scan rewrite, linear in input length; subprocess-guarded timing tripwire in both the verifier and the permanent test |
| 2026-09-11-extract-sinks | `sanitize-error-path-redaction-inert-on-windows` | Token-scan rewrite redacts native Windows and forward-slash Windows paths fully, IGNORECASE included (6 test cases across the redaction table) |
| 2026-09-11-extract-sinks | `write-state-no-lock-concurrent-replace` | mkstemp unique temps + atomic os.replace — concurrent writers cannot interleave and need no mutex; 100-thread last-writer-wins test added |