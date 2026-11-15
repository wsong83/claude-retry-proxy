# Plan: Verification-script runtime isolation + corpus retirement

**Plan ID:** 2026-11-14-verification-runtime-isolation
**Created:** 2026-11-14

<!-- ## Immediate Actions: populated by /update-plan 2026-11-14 (post-coder revision; substantive — Guidance text changed). Replaced, not accumulated, on each revision. -->

## Immediate Actions

**Coder (review-fix round): DONE** — `[report](./tmp/reports/2026-11-14-verification-runtime-isolation-coder-2026-11-14-2.json)`: all four fixes landed (exempt branch enforces checks 1+2+5 via shared `check_isolation_dir`/`ordering_violations`; token-naming check-5 message; shape-describing check-1 zero-match diagnostic; `import tempfile` dropped), RED calibration clean on the three exemption teeth, corpus 2 EXEMPT / 0 FAIL preserved, tester 4(b)/4(c) expectations preserved. One tester-lane issue filed: [teeth-spawn-call-substring](./tmp/reports/2026-11-14-verification-runtime-isolation-teeth-spawn-call-substring.json).

**Tester (review-fix round):** update `tests/test_spawn_isolation.py` — (0) fix [teeth-spawn-call-substring](./tmp/reports/2026-11-14-verification-runtime-isolation-teeth-spawn-call-substring.json): cases 1(e)/1(f) required substring `"spawn call"` → `"spawn-API token"` (optionally also assert the named boundary token, e.g. `(subprocess.run)`); (1) verify fixtures 4(a)/(d) satisfy checks 1+2+5 under the strengthened exemption (adjust if not); (2) add the exempt teeth: live-`_ISOLATION_DIR` + marker → FAIL (`not derived from tempfile.mkdtemp`), `_ISOLATION_DIR = ""` variant → FAIL, post-spawn canonical pair + marker → FAIL (`must precede the first spawn-API token`) — RED-calibrated against the pre-fix checker in the coder's round, so pin the new messages as green-capable now; (3) F6 — give the satisfiability green fixture a real top-level `import claude_retry_proxy` line after the block so the docstring's raw-text discrimination is true, keeping the PASS; (4) F7 — run the default-root no-arg case with cwd at the test's own temp dir; (5) F9 — add the control-character exemption-reason sub-assertion. Re-run the full suite (exit 0), prove the corpus-hook precondition (2 EXEMPT / 0 FAIL), record `--list`/targeted transcripts, and report.

## Issue Log

Rows ordered newest-first (latest issues at top). New issues are prepended; resolved issues stay in place with updated status.

| Issue | Status | Found | Resolved | Resolved By |
|-------|--------|-------|----------|-------------|
| [teeth-spawn-call-substring](./tmp/reports/2026-11-14-verification-runtime-isolation-teeth-spawn-call-substring.json) | Resolved | 2026-11-14 | 2026-11-14 | tester — cases 1(e)/1(f) required substring moved to the plan-mandated `spawn-API token (<token>)` message; sibling forbidden pins at 1(c)/1(d) moved to `spawn-API token`; verified in the targeted battery and the 512/512 suite |
| [blanking-offset-basis-claim](./tmp/reports/2026-11-14-verification-runtime-isolation-blanking-offset-basis-claim.json) | Resolved | 2026-11-14 | 2026-11-14 | planner — spec-text fix (parenthetical reworded); the implementation already satisfied the correct invariant, smoke-verified per the coder's report |
| [orphaned-test-state-files](./tmp/reports/defer-issue-orphaned-test-state-files.json) | Resolved | 2026-10-16 | 2026-11-14 | planner — adopted by this plan: mechanism closed (env overrides + mkdtemp convention), enforced (checker + suite hook), documented; dated leftover-check in Final Results |

## Guidance for Coder

**Files to modify:**

| File | Change |
|------|--------|
| `scripts/check_spawn_isolation.py` | NEW — committed corpus checker (see Step 3 spec) |

No other source files. No test files (tests belong to the tester). No docs (planner lane).

**Step-by-step with verification:** see Proposed Changes Step 3.

### Step 3 spec — `scripts/check_spawn_isolation.py`

Stdlib-only Python (`argparse`, `html`, `os`, `re`, `sys`, `tempfile` — nothing third-party, `requires-python` 3.8+). CLI: `python scripts/check_spawn_isolation.py`, with optional `--path <dir>` (scan an arbitrary directory instead of the default — fixture/corpus inspection only; production and test trees isolate by other mechanisms and FAIL by design under this checker) and optional `--quarantine <dir>` (override the quarantine root for hermetic tests; default: the repo's `tmp/retired-artifacts`). The checker's own file is excluded by identity, not by a marker; no header marker is required on it.

**Default scan root:** `<repo-root>/tmp/verification`, derived with the tests' idiom — `os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tmp", "verification")` — **never from cwd**, no `pathlib` normalization of user input. State the resolved root in `--help` and name it in every run's summary line.

**Root gating (pinned precedence, one lattice):**
1. Raw-argument pre-check on the EXPLICIT `--path` string only: empty or whitespace-only → exit 2 (stderr). Nothing else is decidable from the raw string.
2. `os.path.isdir(root)` gate BEFORE the walk: a missing root → `corpus absent` summary, exit 0 (default AND explicit alike — a typed-path typo is visible in the summary's `root=` field); an explicit root that exists but is not a directory (regular file, symlink-to-file) → exit 2 (stderr). An existing-but-unreadable explicit root → exit 2.
3. `os.walk(root, followlinks=False, onerror=<handler>)` runs only on a verified directory. The `onerror` handler classifies by comparing `os.path.normcase(os.path.abspath(err.filename))` to the normalized root: a failure on the ROOT itself (permission/IO on an existing root; `FileNotFoundError` on the root is unreachable past the isdir gate) → `ERROR` + exit 2; a failure on a subdirectory → `FileNotFoundError` → `SKIP <dir>: vanished during scan` (not counted — the corpus is a live workspace), any other OSError → `FAIL <dir>: unreadable directory (<exception class>)`, counted toward exit 1.

**Per-directory descent guards (both rules, checked in order):**
1. **Reparse points:** a subdirectory that is a reparse point (junction/symlink-dir — `os.path.isjunction` when available via guarded import, else `os.stat(...).st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT` on Windows) is NEVER descended: `SKIP <dir>: reparse point not descended` (visible census; kills junction cycles and out-of-tree escapes at once).
2. **Containment (defense-in-depth):** before descending any subdirectory, `os.path.normcase(os.path.realpath(dir))` must fall under the normalized real scan root; otherwise `SKIP <dir>: escapes scan root`.
3. **Quarantine prune:** a path under the resolved, normcase-realpathed quarantine root (`--quarantine` override or `<repo>/tmp/retired-artifacts`) is pruned; each pruned directory emits `SKIP <dir>: retired-artifacts` so a fully-pruned scan is visibly vacuous. The self-identity and quarantine checks share one `normcase(realpath(...))` helper so they cannot drift.
4. A non-`.py` file (casefolded suffix test) → `SKIP <relative-path>: not scanned (non-Python)`; the residual gap that `.js`/`.ps1`/`.bat`/`.sh` spawners are invisible to the compliance rule is documented in the Step 5 doc text.
5. A `.py` file above 5 MB → `SKIP <relative-path>: oversize, not scanned` (availability bound for a permanent gate; the corpus is author-controlled text).

**Detection — which files are "spawners":** a scanned `.py` file is a spawner when its RAW text (before any comment blanking) contains AT LEAST ONE launch token AND AT LEAST ONE spawn-API token:

1. Launch tokens (any of): `claude_retry_proxy` (subsumes the `.server`/`.cli` spellings and in-process imports), `claude-retry-proxy` (covers `-server` and `.exe`), `PROXY_SERVER`, `CLAUDE_PROXY`.
2. Spawn-API tokens (any of): `Popen(`, `subprocess.run`, `subprocess.call`, `subprocess.check_call`, `subprocess.check_output`, `os.system`, `os.spawn`, `os.exec`, `os.popen(`, `subprocess.getoutput(`, `subprocess.getstatusoutput(`, `os.posix_spawn`, `os.posix_spawnp`, `multiprocessing.Process(`, `asyncio.create_subprocess_exec`, `asyncio.create_subprocess_shell`, and the prefix `from subprocess import` (any from-import of subprocess is spawn-capable — safe-side).

Detection runs on raw text deliberately (a token only inside a `#` comment still counts — overflag is safe-side; case 5 pins both the docstring and comment-only variants). Classification results, one line each:
- launch AND spawn → **spawner** (compliance checks apply);
- launch, no spawn → `SKIP <path>: launch tokens without a spawn API` (an in-process importer with no spawn call — visible, not enforced; the doc text tells authors to use the block whenever a proxy module is imported at all);
- spawn, no launch → `SKIP <path>: spawn API without proxy tokens` (a helper shelling out to the suite — non-enforced, visible);
- neither → `SKIP <path>: no proxy tokens`.

**Processing pipeline (pinned order):** read raw text → exemption-marker detection on raw text (below) → spawner classification on raw text → for spawners only, comment-blank (each `#`-first-non-space line is replaced by the EMPTY string, keeping its newline — blanking preserves line structure only, NOT raw byte offsets; every offset below is measured on the blanked text, the pipeline's single coordinate space, and is never compared against a raw-text offset) → the five compliance checks on the blanked text.

**Exemption:** a file whose raw text contains a line whose first non-space character is `#` and which starts with the exact prefix `# spawn-isolation: exempt:` is exempt. The reason is the remainder after the FULL PREFIX (`line.split("# spawn-isolation: exempt:", 1)[1]` — never the first colon of the line), `.strip()`ed for both the emptiness test and the emitted EXEMPT line; `reason.strip() == ""` (including whitespace-only) → `FAIL <path>: exempt marker without reason`. **Exemption waives checks 3 and 4 ONLY — the trace and compatibility assignments.** Checks 1 (mkdtemp derivation), 2 (state assignment) and 5 (ordering) stay enforced under the marker: the state anchor is the join shape PLUS the temp-dir derivation PLUS correct ordering, because a live-path `_ISOLATION_DIR`, a missing state assignment, or a block placed after the first spawn-API token or proxy import would each let a spawned child inherit the live state path (review F1, 2026-11-14, and the ordering extension the planner added in processing it). An exempt spawner failing check 2 emits `FAIL <path>: exempt-without-state-isolation` (label unchanged); exempt failures of checks 1/5 emit the standard check messages, aggregated into the file's one FAIL line. The sanctioned narrow remedy (`--log <tempdir>` trace redirection) is documented in the Step 5 doc text as trace-only: a proxy-spawning script is never exemptible on trace grounds alone. The corpus's two exempt scripts satisfy 1+2+5 (verified statically at revision time); the corpus-hook precondition (2 EXEMPT / 0 FAIL) must hold under the strengthened checker.

**Compliance rule (non-exempt spawners) — the canonical block.** The canonical block is the plan's single source of truth (§Canonical compliant block). On the blanked text, ALL of:

1. **mkdtemp derivation, exactly-once pair:** exactly ONE match of `(?m)^\s*_ISOLATION_DIR\s*=` (line-anchored, word-boundary safe) AND that single assignment line matches `_ISOLATION_DIR\s*=\s*tempfile\.mkdtemp\(` — a second `_ISOLATION_DIR` assignment in any form (e.g. a reassignment to a live path) fails here; the zero-match diagnostic describes the required verbatim one-line shape (annotated or parenthesised derivations do not match — safe-side) rather than asserting an assignment count the file contradicts (review F11);
2. `os\.environ\[["']PROXY_STATE_FILE["']\]\s*=\s*os\.path\.join\(\s*_ISOLATION_DIR\s*,\s*["']state\.json["']\s*,?\s*\)` — and the count of `os\.environ\[["']PROXY_STATE_FILE["']\]\s*=` matches on blanked text must be EXACTLY 1 (a later reassignment — e.g. to a live `~/.claude/...` path — fails; last-match offsets alone cannot catch a reassignment placed before the spawn);
3. the same shape + exactly-once for `PROXY_TRACE_FILE` / `"trace.jsonl"`;
4. the same shape + exactly-once for `PROXY_FEATURE_COMPAT_FILE` / `"feature-compat.json"`;
5. **Ordering check, one coordinate space:** let `latest` be the MAXIMUM match offset among checks 1–4 and let `import_first` be the first offset of `(?m)^\s*(?:from|import)\s+claude_retry_proxy`, both measured on the SAME blanked text as everything else (blanking is position-preserving — mixing stripped and raw offsets is the mixed-basis bug and is impossible by construction here). Then `latest` must precede BOTH `import_first` (when the file has an in-process proxy import; none → comparator (a) vacuous) AND `spawn_first` (the first spawn-API token offset on the blanked text; the file has one, being a spawner). The spawn-side FAIL message names the matched boundary token (e.g. `ordering: the isolation assignments must precede the first spawn-API token (from subprocess import)`) instead of asserting a spawn call that may not exist — the from-import prefix is a plan-pinned spawn token and a compliant script using that import form must be able to diagnose itself (review F3). Rationale: `settings.py` binds ALL THREE paths from env at import (trace included — the sinks are configured from `SETTINGS` at import; `resolve_trace_file`'s call-time re-read is an additional net, not the sink binding), and a spawned child inherits the env it is forked with — the block must precede both.

Declared textual limitations (restated in the Step 5 doc text): the checker proves token presence and position, not execution — a docstring quoting the block passes when no real block exists (mimicry), and fails the exactly-once checks when the real block is also present; cleanup is not checker-verifiable; non-Python spawners are not scanned; fully dynamic module construction defeats literal tokens; a hard-killed script still orphans its `proxy-probe-*` temp dir (OS temp cleaners own it — measure on demand: `ls %TEMP%/proxy-probe-*`; no "no residue" claim is made). The realistic threat is forgetfulness, not mimicry.

**File reading:** every scanned file is read with `encoding="utf-8-sig", errors="replace"` (never raises on decode). **Encoding-defect detection:** if the first 4096 bytes contain a NUL byte or a UTF-16/UTF-32 BOM, emit `FAIL <path>: undecodable encoding (utf-16 suspected)` instead of silently token-scanning NUL-interleaved text. Per-file fault classification: `FileNotFoundError` → `SKIP <path>: vanished during scan` (benign concurrent deletion, not counted); any other `OSError` → `FAIL <path>: unreadable (<exception class>)`, counted. **Torn-read guard:** a FAIL verdict (compliance or unreadable) is re-read ONCE after a 0.5 s pause; the re-read result replaces the first verdict entirely (re-read `FileNotFoundError` → SKIP vanished; other re-read OSError → FAIL unreadable; re-read PASS → PASS); SKIP/PASS/EXEMPT verdicts are final and never re-read. Output encoding: `sys.stdout.reconfigure(errors="replace")` wrapped in `try/except Exception: pass` (best-effort, never an abort condition).

**Output contract:** one line per file considered —
- `PASS <relative-path>` — spawner, all five checks green;
- `FAIL <relative-path>: <all violated checks, aggregated in one line>` — one FAIL line per file, naming every violated check / missing canonical line;
- `EXEMPT <relative-path>: <reason>` — exemption honored (check 2 passing);
- `SKIP <relative-path>: <reason>` — every non-spawner disposition above.
`<relative-path>` is relative to the scan root, always emitted with `/` separators (`replace(os.sep, "/")`), no leading `./`. The sanitizer applies to EVERY variable field in every line — relative path, exemption reason, FAIL detail, and the summary's root — stripping ALL C0 control characters (< 0x20) plus DEL (0x7F), so evidence lines stay one line and the trail cannot be forged by content. Then exactly one summary line: `check_spawn_isolation: root=<root> | <n> spawners, <n> fail, <n> exempt, <n> skip | PASS|FAIL` — ASCII in its fixed literals; `<root>` is emitted raw under the reconfigure guard. Root-visibility: a missing root (default or explicit) → `check_spawn_isolation: root=<root> | corpus absent | PASS`; an existing directory yielding zero `.py` files → `| corpus empty | PASS` — both exit 0, both visible; vacuity is never indistinguishable from a real scan.

**Exit codes:** 0 — clean, including `corpus absent`/`corpus empty`; 1 — any FAIL; 2 — a bad explicit `--path` (empty/whitespace string; exists-but-not-a-directory; existing-but-unreadable root; raw-string check where decidable) or an abnormal run (top-level `except Exception` → stderr message, exit 2 — a crash must never masquerade as exit 1). Idempotent. Every subprocess invocation across the plan (checker invocations from the gate and the tests, `tasklist` probes) uses list-form arguments with no shell and carries an explicit `timeout=`.

## Canonical compliant block

This block is the plan's single source of truth. Tester case 2 builds its GREEN fixture from it; Step 5(b) lands it verbatim in `doc/test-catalog.html`; the `-landed.py` gate pins its fragments (built from concatenated string parts so the gate's own source never contains a second complete canonical assignment) and re-runs the checker against a fixture built from the *landed doc text* (HTML-unescaped) plus appended spawner lines — so doc-text and checker-pass are bound.

```python
import atexit
import os
import shutil
import tempfile

# Spawned or imported proxy code must never touch live runtime state. These
# three overrides must execute BEFORE the first `import claude_retry_proxy`
# line AND before the first process spawn: settings.py binds ALL THREE paths
# from the environment at import (state, trace, and compat — the sinks are
# configured from SETTINGS at import), and a spawned child inherits the env
# it is forked with.
_ISOLATION_DIR = tempfile.mkdtemp(prefix="proxy-probe-")
os.environ["PROXY_STATE_FILE"] = os.path.join(_ISOLATION_DIR, "state.json")
os.environ["PROXY_TRACE_FILE"] = os.path.join(_ISOLATION_DIR, "trace.jsonl")
os.environ["PROXY_FEATURE_COMPAT_FILE"] = os.path.join(_ISOLATION_DIR, "feature-compat.json")
# Best-effort cleanup once this script exits (children are waited on first):
atexit.register(shutil.rmtree, _ISOLATION_DIR, True)
```

## Guidance for Tester

**Tests to create:**

- **Permanent:** `tests/test_spawn_isolation.py` — per-area module exposing `ALL_TESTS`, registered in `tests/test_claude_proxy.py`'s aggregator (the tester edits BOTH files: the new module and the aggregator's import + `ALL_TESTS` concatenation). Repo-root resolution uses the established per-module idiom `REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))` (as in `tests/test_docs.py`), NOT a harness anchor (`tests/_harness.py` exports none). All fixtures are synthetic files built in the test's own temp space — never inside `tmp/`. Every checker subprocess capture uses `subprocess.run(..., capture_output=True, text=True, errors="replace", timeout=120)` — a timeout is a loud FAIL naming the case, never a hang. Every teeth fixture carries BOTH a launch token and a spawn-API token so it reaches the compliance checks rather than a SKIP branch.
  1. **Teeth (RED calibration, seven fixtures):** (a) a spawner with none of the three env assignments → exit 1, one aggregated FAIL line naming the file and the missing canonical lines; (b) a spawner whose `PROXY_STATE_FILE` is hardcoded to a `~/.claude/...` path and which `mkdtemp`s something unrelated → exit 1, FAIL; (c) ordering, import side: the full canonical block placed *after* a top-level `import claude_retry_proxy...` line → exit 1, FAIL names the ordering check; (d) ordering, split shape: the state assignment before the import line, trace + compat after it → exit 1, FAIL names the ordering check (distinguishes the all-assignments comparator from a broken earliest-offset one); (e) ordering, spawn side: spawn call at the top, complete canonical block at the bottom, no in-process import → exit 1, FAIL names the spawn comparator; (f) ordering, comment-skew shape: a large `#` header block plus comment lines interleaved between the spawn call and the canonical block → exit 1, FAIL (this catches a mixed-basis implementation whose offsets span raw and blanked texts); (g) exactly-once: the canonical block PLUS a later `os.environ["PROXY_STATE_FILE"] = os.path.expanduser("~/.claude/proxy/proxy-state.json")` reassignment before the spawn → exit 1, FAIL names the exactly-once check.
  2. **Satisfiability (GREEN):** the canonical compliant block, copied verbatim from this plan's §Canonical compliant block, in a file that also spawns → exit 0, PASS line. Proves the gate satisfiable.
  3. **False-positive guard:** a file that does `from claude_retry_proxy.transforms_chat import …` in-process with no spawn-API token anywhere → `SKIP` line (`launch tokens without a spawn API`), exit 0.
  4. **Exemption:** (a) a spawner carrying `# spawn-isolation: exempt: trace redirected via --log to the script's own temp dir` AND a passing state assignment (trace genuinely redirected) → `EXEMPT` line, exit 0; (b) a marker with whitespace-only reason → FAIL `exempt marker without reason`; (c) a marker with no state assignment → FAIL `exempt-without-state-isolation`; (d) a reason containing a second colon (`exempt: see docs: note`) → the reason text after the PREFIX cut, not `exempt: see docs`.
  5. **Prose-overflag pin:** a file with `claude-retry-proxy` only inside a docstring plus an unrelated `subprocess.run(...)` → flagged spawner → FAIL; and a variant with both tokens only inside `#` comments → still flagged (raw-text detection).
  6. **Encoding:** (a) a non-compliant spawner containing an em-dash and a leading UTF-8 BOM → exactly one aggregated FAIL line naming it (no traceback, exit 1); (b) a UTF-16LE-encoded spawner → FAIL `undecodable encoding` (never a silent no-tokens SKIP).
  7. **Default root and bad paths:** run with NO `--path` from the repo root → exit 0, summary names the resolved root (asserted via `os.path.normcase(os.path.realpath(...))` on BOTH sides — the checker derives its root with abspath, so compare in one coordinate space); explicit `--path` variants: empty string → exit 2; whitespace-only → exit 2; a regular file → exit 2; a nonexistent path → exit 0 with `corpus absent`.
  8. **Corpus hook:** first verify the anchor — assert `scripts/check_spawn_isolation.py` exists relative to `REPO_ROOT` (a broken anchor is a loud test failure, never a pass). Then run the checker with `--path <REPO_ROOT>/tmp/verification` → exit 0 with 0 FAIL; the post-sweep corpus holds exactly this plan's two exempt scripts (expected: 2 EXEMPT, 0 FAIL — recorded as the case's precondition); absent directory → `corpus absent`; empty → `corpus empty` — vacuity visible in every run. The corpus is the live gitignored workflow space: this hook is deliberately non-hermetic (a red result means a non-compliant script sits in `tmp/verification`); the torn-read race is mitigated by the checker's single re-read; the coupling is stated in the Step 5 doc text.
  9. **Checker self-scan:** `--path <REPO_ROOT>/scripts` → the checker's own file yields `SKIP ...: checker itself`, exit 0 (identity via the shared normcase-realpath helper).
  10. **Unreadable directory (where constructible):** on platforms permitting a no-read directory, a spawner beneath it yields `FAIL ...: unreadable directory` and exit 1; skipped where the OS refuses the construct.
  11. **Quarantine prune (hermetic):** with `--quarantine <fixture-dir>`, a fixture root containing a pruned subtree with a deliberately non-compliant spawner inside → the subtree's `SKIP <dir>: retired-artifacts` lines, the spawner unreported, exit 0 — hermetic coverage for the normcase/realpath prune logic.
  12. **Spawn-only classification:** a file with `subprocess.run` and no proxy token → `SKIP ...: spawn API without proxy tokens`, exit 0.
- **While in `tests/`:** refresh the two stale docstring citations in `tests/test_admin.py` (the entries citing `tmp/verification/2026-10-25-guard-totality-and-blank-admin-admin-page.py` and `tmp/verification/2026-11-01-admin-config-500-surface-step5.py` — both scripts are already absent from disk and are swept by Step 1): drop the paths, keep the described measurements, preserve each sentence's subject (docstring-only edit, tester lane).
- **No temporary tests anticipated.**

**Tests to investigate for retirement:**

- No test obsolescence identified — this plan modifies no source behavior; no existing suite test exercises script-corpus hygiene.

**Retirement procedure:** standard (verify the test exercises removed/changed code; none identified).

## Summary

**Problem.** Standalone verification/diagnostic scripts (`tmp/verification/*.py`, authored by planner/tester/reviewer rounds as step gates) spawn throwaway proxy children outside the test suite. The suite isolates its children via env overrides set at harness import (`PROXY_STATE_FILE`, `PROXY_TRACE_FILE`, `PROXY_FEATURE_COMPAT_FILE`); scripts bypass that loop. Measured 2026-11-14 with the plan's final token lists (launch: `claude_retry_proxy`, `claude-retry-proxy`, `PROXY_SERVER`, `CLAUDE_PROXY`; spawn-API: the seventeen pinned tokens; spawner = launch AND spawn) over `tmp/verification`'s 225 `.py` files: **159 files carry a launch token; 46 are spawners; of those, 43 lack a `PROXY_STATE_FILE` assignment, 43 lack `PROXY_TRACE_FILE`, 45 lack `PROXY_FEATURE_COMPAT_FILE`**; 113 files are launch-only (visible SKIPs), 19 spawn-only, 47 clean. Reproduce with the pinned token lists + the conjunction over `tmp/verification/**/*.py`; the counts are illustrative — the design claim (the exposure class exists) does not depend on them. The user-visible residue: 35 orphan `claude-retry-proxy-test-state-<pid>.json` files in `~/.claude/proxy` (deferred issue `orphaned-test-state-files`, 36 by 2026-10-16 per the deferral). The mechanism needs no code change: `settings.py` binds all three paths from env at import and the sinks are configured from `SETTINGS` at import; `cli.py`'s `_write_state` mkstemp's beside its own target (the server's `StateSink`/`write_state` always did), so any directory works — and the spawned server deletes its state file at shutdown, which is why an unisolated child can also remove the live `proxy-state.json`.

**User-directed approach (2026-11-14, Phase 3):** retirement-first ordering, then a helping-files audit, then the fix with enforced binding (tier 2). Explicitly decided: no cross-repo generalization to the agent definitions (the issue is repo-local; in-repo docs plus mechanical teeth suffice).

**Design.** One rule binds the exposures at authoring time — enforced scope: any script that spawns a proxy child (and any script that both mentions proxy modules and spawns processes) sets all three env vars under a temp dir it creates, before the first proxy import AND the first spawn — the canonical compliant block in this plan. Import-only scripts (no spawn call) are skipped visibly and remain a documented residual gap. Enforcement is mechanical: a committed corpus checker (`scripts/check_spawn_isolation.py`, same pattern as the committed `scripts/check_doc_anchors.py`) invoked by a permanent suite test — every suite run re-scans the corpus, so a non-compliant script fails its own plan's tester round. The plan's own two surviving corpus scripts (the `-retire.py` hand-off and the `-landed.py` gate) are themselves classified spawners (the retire script spawns `tasklist`; the gate spawns the checker) and therefore carry the canonical state pair alongside their exemption markers. The existing corpus is retired first (user-directed): no file in it is live evidence for an active round — with the carve-out for this plan's own two scripts (excluded from the sweep by exact filename). The corpus's scripts belong to plans that are terminal or never started (one exception named in Step 1: `2026-10-17-admin-single-active-page` is "(Not started)" and its review-harness artifact is swept under the user's blanket direction, recoverable from quarantine); strays (`_dryrun*`, `CLAUDE.md.staged`, a nested dry-run source tree) belong to no plan at all and are swept the same way. Quarantine-copy with byte verification precedes every deletion.

**Flow.** Step 1 (sweep hand-off, user executes) → Step 2 (doc audit) → Steps 3–4 (checker + suite hook land on a corpus reduced to this plan's own two exempt scripts) → Step 5 (docs) → Step 6 (adoption, Final Results).

**Out of scope:** `tmp/reports/` residue (separate corpus, separate sweep), cross-repo agent-definition changes, any `src/` change, tenacity/httpx2 adoption (tracked by the other open deferral, sequenced after this plan).

**Alternatives rejected:** harness-import sweep of stale state files — touches shipped test code, needs a concurrency guard for concurrent suite runs, misses scripts that never import the harness; fixing the legacy scripts in place — they are inert residue awaiting this sweep; docs-only convention (original proposal) — under-binds, replaced by the user's enforcement tier.

## Repo Mode

Public

*Detected 2026-11-14 via `detect_repo_mode.py`. Determines: plan archival path (`plans/`), commit-message content, staged files.*

## Document Overrides

| Document | Rule Overridden | Reason |
|----------|----------------|--------|
| ~/.claude/CLAUDE.md (Agent Reports and Tracing) | Retirement scope is the plan's own `retire_inventory`; artifacts outside the record stay until the user instructs otherwise; the hand-off contract names a bash script shape (`rm -v --`, `bash -n`, ordinal/self-delete mechanics) | The user directed blanket retirement-first of the dead verification corpus on 2026-11-14. The swept files belong to other (terminal or never-started) plans and to no plan at all; none is recorded in this plan's inventory. Quarantine-copy with byte verification precedes every delete (recoverable); the one non-terminal plan's artifact (`2026-10-17-admin-single-active-page` review harness) is named at hand-off. **Deviation declared, not compliance claimed:** the hand-off script is authored in Python (`os.unlink`, no `bash -n`, no predecessor-ordinal sweep) because the deny list covers both shapes and Python is this repo's cross-platform convention. The codified five checks are satisfied as follows: identity = validated scope (resolved containment under `tmp/verification` + the two exact-filename exclusions + the Section B basename pattern — no per-basename pattern for Section A, which sweeps a tree); status = post-sweep listing; shape = pattern-matched Section B targets and tree-contained Section A targets; freshness = size + mtime_ns + content-hash recheck pre-delete; sibling exclusion = the two plan-owned scripts. |

## Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| Corpus sweep deletes untracked evidence files (irreversible for untracked content) | A terminal (or unstarted) plan's gate script is gone | Quarantine-copy with per-file byte verification precedes every delete (recoverable; restore = copy the quarantine subtree back — repo files to the repo root, Section B files to `~/.claude/proxy/` from the quarantine's `home/.claude/proxy/` mapping — see ## Rollback); the quarantine is outside sweep and checker scope (realpath rule) and must never be treated as corpus; freshness recheck (size + mtime_ns + content hash; mtime as fast pre-filter) immediately before each delete; delete faults retry once then `SKIP ...: locked` and continue; quarantine-stage COPY faults (locked source) skip the file from the deletion set and continue (abort-on-first stays for integrity faults: byte mismatch, mkdir failure, symlink re-creation failure); the sweep script and landed gate excluded by exact filename; user-executed; the script writes a RESTORE note into the quarantine |
| Sweep runs while a round is live elsewhere on this checkout | A gate script in flight is deleted mid-run; a `.log` is truncated under a writer | Explicit precondition printed by `--dry-run` and stated in the hand-off summary: run while no round is live on this checkout; freshness recheck bounds the residual race; Section B's PID-liveness guard covers the state files; re-runs never happen after Step 5 |
| PID probe misreads a live process as dead | A live run's state file is deleted | Probe contract (self-pinned, fail-toward-ALIVE per the engineering-doctrine default-branch rule): Windows — ctypes OpenProcess with both access masks; a null handle falls through to a LIST-FORM `tasklist /FO CSV /NH /FI "PID eq <pid>"` invocation (never a shell; `timeout=` carried); the CSV output containing the PID in its first data field ⇒ ALIVE; header-only/no-data-row output (the localized no-match shape) ⇒ DEAD (sweep candidate); non-zero exit, exception, or unparseable output ⇒ ALIVE; an over-range or unparseable PID value ⇒ ALIVE (OpenProcess failing already reads so). POSIX `os.kill(pid, 0)`: `ProcessLookupError` ⇒ dead; `PermissionError`/any other `OSError`/`OverflowError`/`ValueError` ⇒ alive, skip (never crash); `pid <= 0` ⇒ skip, not a PID. A recycled PID is indistinguishable and is reported as a skip |
| Suite hook is non-hermetic (scans the live gitignored corpus) | A concurrent round's leaky script fails an unrelated plan's suite; a torn read false-fails a compliant file | The leaky-script case is the intended teeth (the authoring round owns compliance); torn reads get one delayed re-read and vanished files a benign SKIP; the coupling is stated in `doc/test-catalog.html`; this plan's own two `tmp/verification` scripts carry exemption markers AND the canonical state pair (retire: spawns only the tasklist liveness probe; landed gate: spawns only the checker itself); if the sweep aborts part-way, the user re-runs it (idempotent) BEFORE Steps 3–4 |
| Checker overflags | Author friction | Bare-substring + raw-text detection chosen deliberately (safe-side): a docstring mention plus an unrelated spawn call is flagged (case 5 pins the docstring and comment-only variants); the exemption marker (state-anchored) is the remedy; false-positive guard (case 3) pins the import-only shape as SKIP; spawn-only helpers get their own visible SKIP (case 12) |

## Rollback

The sweep's only irreversible act is deleting untracked corpus files and orphan state files. Recovery: every deleted file exists byte-verified under `./tmp/retired-artifacts/2026-11-14-verification-runtime-isolation-<YYYY-MM-DD>-<HHMMSS>[-<n>]/`. Section A files keep their repo-relative paths (restore: copy back under the repo root). Section B files are mapped to `home/.claude/proxy/<basename>` inside the quarantine (basenames cannot collide — the PID is embedded — and the containment assert applies to the MAPPED target; restore: copy back to `~/.claude/proxy/`). The chosen quarantine directory is printed by both `--dry-run` and the real run, and a RESTORE note naming the copy-back procedure is written into it by the script. The quarantine directory is excluded from the checker's scan and from any future sweep — it must never be treated as corpus. This section is the durable record; it survives plan archival.

## Proposed Changes

Each step includes verification checks tagged with confidence (see Prime Directive 4).
`(auto)` = mechanical, coder self-verifies. `(scripted)` = deterministic multi-step, coder runs provided script.
Every step must have at least one verification check executable by its owner (coder steps: coder checks; tester steps: tester verify; planner steps: Evidence).

1. **Step 1:** Author the guarded hand-off script `./tmp/verification/2026-11-14-verification-runtime-isolation-retire.py` (planner-authored, USER-executed — `python *retire*.py` is deny-listed in every agent lane, so neither the `--dry-run` nor the real run can be invoked by the planner; execution is the user's trigger act, and the discretionary `--dry-run` preview is offered for safety beyond the codified no-list-review contract). It carries the marker `# spawn-isolation: exempt: spawns only the tasklist liveness probe` AND the canonical state pair (`_ISOLATION_DIR = tempfile.mkdtemp(prefix="proxy-probe-")` + `os.environ["PROXY_STATE_FILE"] = os.path.join(_ISOLATION_DIR, "state.json")` before any spawn — the state-anchored exemption requires it; the script is a classified spawner via its Section B pattern literal and `tasklist` invocation). Two independent sections sharing one guard battery (see Document Overrides for the codified-check mapping): repo-root resolution precondition; quarantine-copy FIRST into `./tmp/retired-artifacts/2026-11-14-verification-runtime-isolation-<YYYY-MM-DD>-<HHMMSS>/` created with `os.makedirs` and a bounded `-1`/`-2` suffix retry on `FileExistsError` (exhaustion → `ERROR: no free quarantine directory (tried <base>, -1, -2)`, exit non-zero, no deletion; never probe-then-create; never overwrite a prior run's backups; the chosen directory printed by both modes; a RESTORE note naming the copy-back — including Section B's `home/.claude/proxy/` reverse mapping — written into it) preserving relative paths (Section B files under `home/.claude/proxy/<basename>` — basenames cannot collide, the PID is embedded; the realpath containment assert applies to the MAPPED target) with per-file byte verification before any delete and pinned link semantics (walk with a per-directory guard: reparse-point directories are NEVER descended — skipped with a warning; before listing any subdirectory its normcase-realpath must fall under the resolved corpus root, else skip-with-warning; a file symlink is re-created as a link via its readlink target, and on `OSError` from `os.symlink` (Windows privilege) the file's CONTENTS are copied with a `COPY-OF-LINK` warning noted in the RESTORE note; deletion of a link is via `os.unlink`, never through it); freshness recheck (size + mtime_ns + content hash of the byte-verified read; mtime as fast pre-filter) immediately before each delete — mismatch → `SKIP <path>: changed since scan`; already-gone files reported as already retired; quarantine-stage COPY faults (locked/unreadable source) → `SKIP <path>: locked during quarantine (<exception class>)`, excluded from the deletion set, section continues, exit non-zero at section end with the skipped list — abort-on-first stays for INTEGRITY faults (byte-verification mismatch, mkdir failure, symlink re-creation failure) where continuing could lose data; delete faults retry ONCE then `SKIP <path>: locked (<exception class>)`, continue, exit non-zero with named skips (a successor run sweeps the remainder; idempotent; Steps 3–4 proceed only when the skipped set holds no non-exempt `.py` file); emptied directories removed bottom-up best-effort (`os.rmdir`, failures `SKIP <dir>: not empty (<class>)`, non-fatal). **Section A** sweeps the whole `tmp/verification/` corpus under the user's 2026-11-14 blanket retirement-first direction, EXCLUDING by exact filename this plan's own two scripts (`2026-11-14-verification-runtime-isolation-retire.py`, `2026-11-14-verification-runtime-isolation-landed.py` — the gate is authored and RED-proven as of 2026-11-14 and its baseline must survive unedited). Accuracy note: not every corpus file belongs to a terminal plan — `2026-10-17-review-final-harness.js` correlates with the NOT-started plan `2026-10-17-admin-single-active-page`; it is swept under the blanket direction, named in the one-line hand-off summary, and recoverable from quarantine. **Section B** sweeps orphan state files in `~/.claude/proxy/` matching `^claude-retry-proxy-test-state-\d+\.json$`, each gated by the PID-liveness contract from the Risks table (fail toward ALIVE; list-form CSV `tasklist` with `timeout=`; localized no-match ⇒ DEAD; `pid <= 0` and unparseable values ⇒ skip); the live `proxy-state.json` cannot match the pattern. Summary lines carry actual found/swept/skipped counts — no promised count. `--dry-run` prints the full would-sweep list plus the banner `precondition: run while no plan round is live on this checkout` and deletes nothing. Post-sweep verification: no files other than the two plan scripts remain under `tmp/verification/` (leftover empty directories are acceptable residue the script could not remove); if the sweep aborted part-way, the user re-runs it (idempotent) BEFORE Steps 3–4.
   → Evidence: planner-lane verification is static only (the authored script read line-by-line against this spec, including a check that the state pair precedes Section B's first spawn — the deny list forbids executing it); the USER's `--dry-run` transcript (full list + banner, exit 0, nothing deleted) and real-run output (per-file retired/skipped lines + final summary with actual counts) are the execution evidence, recorded in the session summary.

2. **Step 2:** Helping-files audit — `git grep` (and read, where hits are ambiguous) `CLAUDE.md`, `README.md`, and every `doc/*.html` for statements about: `PROXY_STATE_FILE`, `PROXY_TRACE_FILE`, `PROXY_FEATURE_COMPAT_FILE`, `proxy-state.json`, test-state files, orphans, trace isolation, verification scripts, "Override for test isolation" phrasing (including `doc/operations.html`'s runtime-artifacts paragraph), the suite catalog/inventory surfaces, the conventions checker enumeration, and the isolation history. Produce a findings table: each claim → still-true / needs-update / stale, with the exact landing text (feeds Step 5). Known landing targets (found by the mega-audits, to be confirmed): CLAUDE.md `## Structure` scripts/ block; CLAUDE.md env-table rows (`PROXY_STATE_FILE`, `PROXY_FEATURE_COMPAT_FILE` → "Override for test and script isolation."); `doc/configuration.html` env-var rows; `doc/operations.html` runtime-artifacts paragraph; `README.md` env rows (including the MISSING `PROXY_FEATURE_COMPAT_FILE` row) and suite-safety paragraph; `doc/content.html` conventions bullet; `doc/test-catalog.html` — Isolation orphan paragraph (cross-link), suite-safety note (non-hermetic clause), the three stranded proof-script citations (path-free AND slug-free rewrite), catalog table + per-test inventory + both `Last updated` stamps; the CLAUDE.md Gotchas orphan paragraph. `tests/test_admin.py`'s two stale docstring citations are dispositioned to the tester. Every audited surface gets an explicit row even when the verdict is "no change". No exact counts in doc output — behavior + measure-on-demand command.
   → Evidence: the findings table recorded in the step's History-adjacent note, each row carrying the grep hit that justified it.

   **Step 2 findings table (recorded 2026-11-14, during execution):**

   | Surface | Grep hit | Verdict | Landing |
   |---------|----------|---------|---------|
   | CLAUDE.md:244 `PROXY_STATE_FILE` row | "Override for test isolation." | needs-update | widen → "Override for test and script isolation." (5a) |
   | CLAUDE.md:245 `PROXY_FEATURE_COMPAT_FILE` row | "Override for test isolation." | needs-update | widen (5a) |
   | CLAUDE.md Gotchas test-suite bullet | "may be deleted from ~/.claude/proxy by hand" | still-true + missing convention | additive convention sentence + checker command (5a) |
   | CLAUDE.md `## Structure` scripts/ block | only `analyze_proxy_trace.py` + `check_doc_anchors.py` named | missing entry | checker line (5a) |
   | README.md:577 `PROXY_STATE_FILE` row | "Override for test isolation." | needs-update | widen (5f) |
   | README.md env table (570-580) | no `PROXY_FEATURE_COMPAT_FILE` row | stale (missing) | add row mirroring configuration.html (5f) |
   | README.md:752 suite-safety | "The suite is safe to run while a proxy is live: it redirects its state," | still-true + missing clause | corpus-hook clause (5f) |
   | doc/configuration.html:439,441 | "Override for test isolation." ×2 | needs-update | widen + both stamps (13, 521) (5c) |
   | doc/operations.html:472-476 | "which is how the test suite keeps its proxies isolated" | needs-update | widen + cross-link + both stamps (13, 490) (5e) |
   | doc/content.html:91-95 | "A committed checker, `scripts/check_doc_anchors.py`" | under-describes | name both committed checkers + both stamps (13, 104) (5d) |
   | doc/test-catalog.html:43-48 suite-safety note | harness-redirect-only wording | still-true + missing clause | corpus-hook clause (5b) |
   | doc/test-catalog.html:84-90 orphan paragraph | "may be deleted by hand at any time" | still-true + missing cross-link | cross-link + command (5b) |
   | doc/test-catalog.html:639,641 | three `tmp/verification/…` proof-script citations | will strand after Step 1 | path-free AND slug-free rewrite (5b) |
   | doc/test-catalog.html:108 catalog table; :169 inventory | no `test_spawn_isolation` row/entries | missing | row + Category 14 + per-test entries (5b) |
   | doc/test-catalog.html:13,973; :169 comment | stamps 2026-11-04; "extended … 2026-10-26" | stale after edit | bump all three (5b) |
   | tests/test_admin.py docstrings (2 sites) | citations to scripts already absent from disk | stale | tester lane: path-free refresh (Step 4) |
   | Test obsolescence | none — no source behavior changes | none identified | — |

   **Step 1 execution evidence (recorded here because the step's session-summary line lives in chat):** the user executed the dry-run (291 Section A files listed, 35 Section B orphans listed, 34 dead + 1 alive-claimed, exit 0) and the real run (quarantine `tmp/retired-artifacts/2026-11-14-verification-runtime-isolation-2026-11-14-160323`; 291 + 34 retired byte-verified; `SKIP claude-retry-proxy-test-state-51168.json: alive (pid 51168)` — remaining, alive-skipped; 0 skipped at quarantine, 0 at delete → exit 0). Post-sweep `ls tmp/verification/` shows exactly the two plan-owned scripts; emptied directories (`logs/`, `__pycache__/`, `_dryrun_arg/`) removed. The alive-skip remains on disk and will be named in Step 6's dated closure.

3. **Step 3:** Coder implements `scripts/check_spawn_isolation.py` exactly per the Guidance-for-Coder spec above (root-gating lattice, descent guards, detection tokens, marker pipeline, state-anchored exemption, canonical-block compliance with exactly-once and the single-coordinate-space ordering check, encoding-defect detection, fault classification, output lines, exit codes, timeouts).
   → coder verify (auto): the file exists at `scripts/check_spawn_isolation.py`; imports are stdlib-only; `--help` exits 0 and states the default root and the fixture/corpus-only scope of `--path`; with no args from a foreign cwd the summary names the same root (cwd-independence); explicit `--path` empty/whitespace string or a regular file → exit 2; a nonexistent root (default or explicit) → exit 0 with `corpus absent`; an existing empty root → `corpus empty`.
   → tester verify: Step 4's cases 1–12.

4. **Step 4:** Tester creates `tests/test_spawn_isolation.py` per the Guidance-for-Tester cases 1–12 and registers it in `tests/test_claude_proxy.py` (import + `ALL_TESTS` concatenation) and refreshes the two stale `tests/test_admin.py` docstring citations. Runs the full suite, then proves registration per `doc/test-catalog.html` "Adding a test" step 3 (the anti-green MUST): `python tests/test_claude_proxy.py --list` must list the new slugs, and a targeted run must print `>> <slug>: PASSED` for at least one teeth case — `-t` takes a SPACE-SEPARATED LIST, not a repeated flag.
   → tester verify: full suite passes (exit 0); `--list` output and the targeted transcript recorded; case-1 RED evidence quoted (the seven teeth fixtures' FAIL line texts); case 8's green run recorded with the 2-EXEMPT/0-FAIL precondition verified.

5. **Step 5:** Planner lands the docs per Step 2's audit table: (a) `CLAUDE.md` — Gotchas: ADDITIVE amendment (append the convention sentence — three env vars under a `tempfile.mkdtemp()` dir, before the first proxy import AND the first spawn, canonical block at `doc/test-catalog.html#pattern-spawn-isolation` — and the measure-on-demand command `python scripts/check_spawn_isolation.py`; the existing orphan guidance stays); baseline and re-count the section's MUST/NEVER/ALWAYS keywords; env table: widen the two rows to "Override for test and script isolation."; `## Structure`: extend `scripts/` with `check_spawn_isolation.py` (corpus runtime-isolation checker, invoked by the test suite); (b) `doc/test-catalog.html` — new `<h3 id="pattern-spawn-isolation">` subsection carrying the canonical block VERBATIM (mkdtemp, three assignments, atexit line), the ordering rationale, the enforced scope and import-only residual gap, the declared textual limitations (mimicry, cleanup, non-Python spawners, dynamic construction, hard-killed `proxy-probe-*` residue + its measure-on-demand command), the exemption marker with its state-anchored limit and the trace-only `--log` remedy note, and the non-hermetic corpus-hook sentence; PLUS the Isolation cross-link, the suite-safety clause, the catalog-table row, the Category 14 heading + per-test entries, both `Last updated` stamps + the inventory `extended` comment, and the three stranded citations rewritten path-free AND slug-free; (c) `doc/configuration.html` — widen the two env-row descriptions; bump both `Last updated` stamps; (d) `doc/content.html` — extend the conventions bullet to name both committed checkers; bump both stamps; (e) `doc/operations.html` — rewrite the runtime-artifacts paragraph's isolation sentence to cover the test suite AND verification scripts, cross-linking `test-catalog.html#pattern-spawn-isolation`; bump both stamps; (f) `README.md` — add the missing `PROXY_FEATURE_COMPAT_FILE` env row (mirroring `doc/configuration.html`), widen the `PROXY_STATE_FILE` row, add the corpus-hook clause to the suite-safety paragraph. Any example URL uses a reserved TLD or an ALLOWED_HOSTS entry.
   → Evidence: the scripted gate `./tmp/verification/2026-11-14-verification-runtime-isolation-landed.py` passes — its RED baseline, quoted here as the owning record: **recorded 2026-11-14 post-iter3-revision, exit 1, 0/21 checks pass, first failing line `FAIL checker-exists: scripts/check_spawn_isolation.py`** (21 landing checks, all failing pre-change; the gate is authored and excluded from Step 1's sweep by exact filename). The gate pins: the convention fragments in `CLAUDE.md` (mkdtemp + checker command + widened env rows + the Structure line), the `pattern-spawn-isolation` anchor, the canonical block's five lines in the doc text (HTML-unescape applied before comparison), the exemption-marker text, the checker-command census (≥ 2 on the page), the `cat-14` anchor, the module's name in the catalog, the aggregator registration, the checker's existence, the two stranded citations' absence from `doc/test-catalog.html`, and the two stale citations' absence from `tests/test_admin.py`; it re-runs the checker (60 s timeout) against a spawner fixture built from the doc-extracted canonical lines + appended launch/spawn lines and asserts the fixture's `PASS` line. GREEN after Step 5's edits, script unedited between the runs. Additionally: `python tests/test_claude_proxy.py -t doc-real-tree-success doc-cli-exit-codes` passes (single `-t`, space-separated list); the corpus-hook test re-runs green after the gate is written; `doc_structure_check.py` clean.

6. **Step 6:** Adoption and closure bookkeeping — leftover check first: the closure evidence is a DATED SNAPSHOT from the user's dry-run output (zero Section-B orphans at that timestamp, with alive-PID skips explicitly listed and accepted — never claimed as a durable zero; later suite runs can mint new orphans; measure-on-demand: `ls ~/.claude/proxy | grep -c claude-retry-proxy-test-state`); then set the Issue Log row to `Resolved` (the linked `defer-issue-orphaned-test-state-files.json` retires via `/update-and-commit` Step 9.6's hand-off); record `retire_inventory` in Plan Metadata; write `## Final Results`; present for approval.
   → Evidence: the dated leftover-check output with alive-skips listed (user-supplied); Issue Log row `Resolved` with the report link; `## Final Results` status line present; metadata `retire_inventory` non-empty.

## Guidance for Planner

Documentation tasks you will execute yourself (not the coder):

- **Files to modify:**
  - `./CLAUDE.md`
  - `./doc/test-catalog.html`
  - `./doc/configuration.html`
  - `./doc/operations.html`
  - `./doc/content.html`
  - `./README.md` — audited in Step 2; landing targets include its env rows (including the missing `PROXY_FEATURE_COMPAT_FILE` row) and its suite-safety paragraph
  - `./tmp/verification/2026-11-14-verification-runtime-isolation-retire.py` (authored in Step 1 — deliverable hand-off script, planner lane by the File Deletion rule; carries the marker AND the canonical state pair; tracked under verification_scripts, not doc_files — it is gitignored and never staged)
  - `./tmp/verification/2026-11-14-verification-runtime-isolation-landed.py` (authored and RED-proven as of 2026-11-14 — see Step 5 Evidence for the quoted baseline; excluded from Step 1's sweep by exact filename; carries the marker AND the canonical state pair; tracked under verification_scripts for the same reason)
- **`.claude/mega-audit-files.json`:** no declared audit locations exist and this plan declares none — no update.
- **When:** the landed gate already exists (authored 2026-11-14, before Step 1, so the sweep can exclude it); audit (Step 2) before the coder round; doc landing (Step 5) after the tester round; hand-off script (Step 1) before everything.
- **What to sync:** the Gotchas orphan paragraph (additive convention + checker pointer); the CLAUDE.md env-table rows; the `## Structure` `scripts/` listing; `doc/test-catalog.html` — the subsection, cross-link, suite-safety clause, catalog row, Category 14 entries, both stamps, the stranded-citation rewrites; `doc/configuration.html` rows + stamps; `doc/operations.html` isolation sentence + stamps; `doc/content.html` bullet + stamps; `README.md` env rows + suite-safety clause; verify no doc surface still implies scripts are exempt from runtime isolation. Doc text must not carry exact counts — behavior + measure-on-demand command only. After doc edits, run the real-tree doc tests and the doc-structure checker so `/update-and-commit` Step 9.8's gate is not surprised.

## History

One row per event (spec revision / mega-audit / review / implementation round). Conclusion = one-sentence outcome or what changed. Dismissed = compact dismissed-findings list for the reviewer — verbatim issue slugs linked as `[<slug>](<report-path>)`, no prose-only entries. Link to report files; never restate findings inline.

| Date | Event | Conclusion | Dismissed |
|------|-------|------------|-----------|
| 2026-11-14 | Initial plan | Drafted from deferred issue `orphaned-test-state-files` after Phase 3: retirement-first ordering, tier-2 enforcement (committed corpus checker + suite hook), docs convention, orphan cleanup; cross-repo generalization explicitly skipped by the user; per-plan-gate clause dropped as redundant with the suite hook. | — |
| 2026-11-14 | Mega-audit iteration 1 (`[report](./tmp/reports/2026-11-14-verification-runtime-isolation-mega-audit-2026-11-14.json)`) | 9 High / 35 Medium / 23 Low; ALL fixed, zero dismissals: canonical block single-sourced with three env vars, default root pinned, detection broadened, encoding/IO contracts pinned, the false "all 56 plans terminal" premise corrected, sweep liveness fail-toward-ALIVE, doc landings enumerated, metadata aligned, gate re-proven RED. | — |
| 2026-11-14 | Mega-audit iteration 2 (`[report](./tmp/reports/2026-11-14-verification-runtime-isolation-mega-audit-2026-11-14-iter2.json)`) | 11 High / 30 Medium / 32 Low; ALL fixed, zero dismissals. Ordering comparator corrected to all-assignments-before-both-import-and-spawn with the import-binding rationale fixed; bare `claude_retry_proxy` launch token added (corpus re-measured); exemption made state-anchored after the server's shutdown state-file deletion was found; sweep excludes the plan's own landed gate; retire-script execution identified as deny-listed (user runs it); gate total-guarded; `corpus absent`/`corpus empty` visibility unified; four more doc surfaces landed; gate re-proven RED (0/19). | — |
| 2026-11-14 | Mega-audit iteration 3 — FINAL under the cap (`[report](./tmp/reports/2026-11-14-verification-runtime-isolation-mega-audit-2026-11-14-iter3.json)`) | 16 High / 30 Medium / 25 Low; ALL fixed, zero dismissals; per the 3-audit cap these fixes are verified by the gate's RED/GREEN and the tester's teeth, not by a fourth audit. Load-bearing: (1) the plan's own two scripts failed their own state-anchored exemption — both now carry the canonical state pair, the retire script's "spawns nothing" marker reason corrected (it spawns tasklist), the landed gate's quoted-fragment mimicry replaced with a real pair + fragmented pin literals; (2) the ordering comparator's mixed offset bases eliminated — comment blanking is position-preserving and every comparator lives in one coordinate space, with new teeth fixtures (comment-skew, split-block, spawn-side); (3) exactly-once extended to checks 2–4 (a live-path reassignment cannot pass) and check 1 given the two-counter formulation; (4) the explicit-`--path` exit lattice pinned once (empty/whitespace/file/unreadable → 2; missing → corpus absent 0; empty dir → corpus empty 0); (5) exemption-reason extraction fixed (prefix cut, not first colon — the whitespace-reason branch was unreachable); (6) spawn-token list extended (+popen/getoutput/getstatusoutput/posix_spawn/multiprocessing/from-subprocess-import; corpus re-measured: 46 spawners, 43/43/45 unisolated); (7) junction/reparse-point guards on both walks with realpath containment; (8) Section B quarantine mapping + rollback reverse mapping; (9) tasklist CSV form with the localized no-match ⇒ DEAD classification; (10) timeouts on every checker invocation; (11) `doc/operations.html` added to the doc landing (+ its stamps), README's missing compat row added; (12) cross-references fixed (Step 5b lettering), `-t` list form, dry-run contract contradiction resolved, engineering-doctrine.md read and its traps applied (gate satisfiability/teeth, bounded re-read, fail-toward-safe defaults, evidence snapshots). Fresh RED baseline recorded: exit 1, 0/21 checks pass (quoted in Step 5 Evidence). | — |
| 2026-11-14 | Step 1 executed; Step 2 audit recorded; coder round 1 (`[report](./tmp/reports/2026-11-14-verification-runtime-isolation-coder-2026-11-14.json)`) | User executed the sweep (quarantine `…-2026-11-14-160323`: 291 corpus files + 34 orphans retired byte-verified; 1 alive-skip `test-state-51168.json` remains; exit 0). Step 2 findings table recorded (17 rows). Coder round: SUCCESS — Step 3 complete, `scripts/check_spawn_isolation.py` landed, build pass, auto-battery green, live-corpus precondition holds (2 spawners / 2 exempt / 0 fail). One issue filed ([blanking-offset-basis-claim](./tmp/reports/2026-11-14-verification-runtime-isolation-blanking-offset-basis-claim.json)) — Plan Error, spec-text only; fixed by rewording the blanking parenthetical (implementation already correct, smoke-verified). Revision: parenthetical reword + Issue Log row + this History row + Immediate Actions created. | — |
| 2026-11-14 | Tester round complete (`[report](./tmp/reports/2026-11-14-verification-runtime-isolation-tester-2026-11-14.json)`); Steps 5–6 executed (planner); plan finalized | Tester: SUCCESS — 12 permanent cases in `tests/test_spawn_isolation.py`, aggregator registration proven (`--list` + targeted `-t`), full suite 512/512, both stale `tests/test_admin.py` citations rewritten; one doc-clarity note (skip counter denominator) folded into the Step 5 text. Planner doc landing: all six surfaces per the Step 2 table; landed gate RED→GREEN (21/21, script unedited); targeted battery 4/4 (`doc-real-tree-success`, `doc-cli-exit-codes`, corpus-hook re-run, checker-self-scan); `doc_structure_check.py` PASS. Adoption: `orphaned-test-state-files` → Resolved with dated leftover-check (34 retired at sweep + the alive-skip named; measure-on-demand → 1 on 2026-11-14); retire_inventory populated (9 artifacts); Final Results written. No new issues. | — |
| 2026-11-14 | Phase 6 review ([report](./tmp/reports/2026-11-14-verification-runtime-isolation-review-2026-11-14.json)) processed; fix round scoped | Reviewer verdict: non-blocking — 1 High / 2 Medium / 8 Low + 6 hunches; evidence re-verified (gate 21/21 unedited, targeted 4/4, corpus 2/0). Dispositions: **F1 (High)** — spec strengthened rather than claim weakened: exemption waives only checks 3+4; checks 1/2/5 stay enforced under the marker (closes the live-`_ISOLATION_DIR` hole and, in processing, the reviewer-unnoticed ordering hole — a post-spawn pair under the marker was equally green-lit); both corpus exempt scripts verified compliant (retire: pair 66–67, first spawn 304; gate: pair 45–46). **F2/F4/F5/F10 + the F1/F3 doc sides** — planner doc fixes landed this revision (configuration mechanism claim; operations/content enforcement scope; corpus-hook assertion wording; exact fixture counts; exemption paragraph rewritten to the strengthened rule; from-import rule documented; deliberate-tampering limitation folded from hunches 1–2). **F3 code side** — the check-5 spawn message names the matched boundary token. **F8/F11** — checker polish (unused import; shape-describing check-1 diagnostics). **F6/F7/F9** — tester round (real import line in the satisfiability fixture; foreign-cwd default-root run; control-char sanitizer sub-assertion). Hunches 3–6 recorded, not actioned (hand-run availability notes / out-of-scope shapes). Fix rounds sequenced in Immediate Actions. | — |
| 2026-11-14 | Coder review-fix round complete (`[report](./tmp/reports/2026-11-14-verification-runtime-isolation-coder-2026-11-14-2.json)`) | All four checker fixes landed; no src/ change. RED calibration: live-iso / empty-iso / post-spawn exempt fixtures each exit 1 with the new messages. GREEN: corpus stays 2 EXEMPT / 0 FAIL (both plan scripts satisfy 1+2+5), tester 4(b)/4(c) preserved, satisfiable + self-scan + root lattice unchanged. One tester-lane issue filed ([teeth-spawn-call-substring](./tmp/reports/2026-11-14-verification-runtime-isolation-teeth-spawn-call-substring.json) — cases 1(e)/(f) pin the old "spawn call" substring; plan-mandated message change, added to this revision as Fix Planned). Tester round launched. | — |
| 2026-11-14 | Tester attempt 1 killed (launcher timeout, no report); fresh relaunch | `round_fault_check.py` verdict: cap-or-stop — launcher heartbeat and child activity froze together at 17:32 (five minutes into the suite run), 3-hour wall gap to the 3600s kill: the host slept (modern standby), freezing round, launcher, and monitors alike; the launcher's timer fired on wake. Not a plan, provider, or test failure. Tree delta checked before relaunch per the runbook: six coherent edits to `tests/test_spawn_isolation.py` landed 17:25–17:26 (the teeth-substring fix work) before the stall; no lock file remained. Relaunched identically (fresh, never resume); the failed attempt does not consume iteration caps. | — |
| 2026-11-14 | Tester review-fix round complete, attempt 2 (`[report](./tmp/reports/2026-11-14-verification-runtime-isolation-tester-2026-11-14-2.json)`); plan finalized | SUCCESS — Immediate Actions (0)–(5) all landed and verified: teeth-substring pins moved to the token-naming message ([teeth-spawn-call-substring](./tmp/reports/2026-11-14-verification-runtime-isolation-teeth-spawn-call-substring.json) → Resolved); fixtures 4(a)/(d) hold 1+2+5; the three exempt teeth (live/empty `_ISOLATION_DIR`, post-spawn pair) and the control-char reason sub-assertion added; the satisfiability fixture gained a real proxy import (F6); the default-root run moved to a foreign cwd (F7). Every new assertion mutation-calibrated red against a checker carrying its defect. Full suite 512/512 (634 s); corpus 2 EXEMPT / 0 FAIL; landed gate re-run 21/21 by the tester. One advisory landed by the planner: the catalog's exemption entry now enumerates the three exempt-teeth shapes. Final Results updated; approval pending. | — |

## Commit Log (optional — conditional)

Populated solely by `/update-and-commit` Step 10 — its single writer. The planner never authors entries; `/update-plan` preserves the section untouched; an absent section means zero SHAs.

## Plan Metadata

Fenced ```json block — the machine contract read by `parsePlanContext` (JSON-first, regex fallback). Updated on every revision.

```json
{
  "plan_id": "2026-11-14-verification-runtime-isolation",
  "steps": [
    "Step 1: Author the guarded hand-off script",
    "Step 2: Helping-files audit",
    "Step 3: Coder implements scripts/check_spawn_isolation.py",
    "Step 4: Tester creates tests/test_spawn_isolation.py",
    "Step 5: Planner lands the docs",
    "Step 6: Adoption and closure bookkeeping"
  ],
  "coder_files": ["scripts/check_spawn_isolation.py"],
  "tester_files": ["tests/test_spawn_isolation.py", "tests/test_claude_proxy.py", "tests/test_admin.py"],
  "doc_files": [
    "./CLAUDE.md",
    "./doc/test-catalog.html",
    "./doc/configuration.html",
    "./doc/operations.html",
    "./doc/content.html",
    "./README.md"
  ],
  "verification_scripts": [
    "./tmp/verification/2026-11-14-verification-runtime-isolation-landed.py",
    "./tmp/verification/2026-11-14-verification-runtime-isolation-retire.py"
  ],
  "retire_inventory": [
    "./tmp/verification/2026-11-14-verification-runtime-isolation-landed.py",
    "./tmp/verification/2026-11-14-verification-runtime-isolation-retire.py",
    "./tmp/reports/2026-11-14-verification-runtime-isolation-mega-audit-2026-11-14.json",
    "./tmp/reports/2026-11-14-verification-runtime-isolation-mega-audit-2026-11-14-iter2.json",
    "./tmp/reports/2026-11-14-verification-runtime-isolation-mega-audit-2026-11-14-iter3.json",
    "./tmp/reports/2026-11-14-verification-runtime-isolation-coder-2026-11-14.json",
    "./tmp/reports/2026-11-14-verification-runtime-isolation-tester-2026-11-14.json",
    "./tmp/logs/2026-11-14-verification-runtime-isolation-coder-2026-11-14.log",
    "./tmp/logs/2026-11-14-verification-runtime-isolation-tester-2026-11-14.log",
    "./tmp/reports/2026-11-14-verification-runtime-isolation-review-2026-11-14.json",
    "./tmp/reports/2026-11-14-verification-runtime-isolation-coder-2026-11-14-2.json",
    "./tmp/reports/2026-11-14-verification-runtime-isolation-tester-2026-11-14-2.json",
    "./tmp/logs/2026-11-14-verification-runtime-isolation-coder-2026-11-14-2.log",
    "./tmp/logs/2026-11-14-verification-runtime-isolation-tester-2026-11-14-2.log",
    "./tmp/logs/2026-11-14-verification-runtime-isolation-tester-2026-11-14-3.log"
  ],
  "repo_mode": "Public",
  "document_overrides": [
    "~/.claude/CLAUDE.md (Agent Reports and Tracing): retirement scope limited to the plan's retire_inventory; hand-off authored in Python, not the codified bash shape (Reason: user-directed blanket retirement of the dead verification corpus, 2026-11-14; quarantine-first, recoverable; deviation declared and the five codified checks mapped in the Document Overrides row)"
  ]
}
```

*The two `tmp/verification/` scripts in `verification_scripts` are gitignored planner-lane deliverables; `doc_files` deliberately carries only committable doc surfaces (repo convention, cf. plan 2026-11-03; recorded here so machine extraction and prose agree on the convention rather than drifting).*

## Audit Accumulation

*Counters reset when mega-audit runs. Used by Phase 5 entry trigger.*

| Counter | Value | Last Updated |
|---------|-------|--------------|
| issues_resolved_since_audit | 1 | 2026-11-14 |
| steps_changed_since_audit | 0 | 2026-11-14 |
| files_changed_since_audit | 0 | 2026-11-14 |

## Documentation

- `CLAUDE.md` — Gotchas test-suite-safety bullet amended additively (Step 5a); `## Structure` scripts/ listing gains the checker; env-table rows widened.
- `doc/test-catalog.html` — new `pattern-spawn-isolation` subsection; Isolation cross-link; suite-safety clause; catalog-table row; Category 14 entries; stamps bumped; stranded citations rewritten (Step 5b).
- `doc/configuration.html` — env-row descriptions widened; both stamps bumped (Step 5c).
- `doc/operations.html` — runtime-artifacts isolation sentence widened + cross-link; both stamps bumped (Step 5e).
- `doc/content.html` — conventions bullet names both committed checkers; both stamps bumped (Step 5d).
- `README.md` — missing `PROXY_FEATURE_COMPAT_FILE` row added; `PROXY_STATE_FILE` row widened; suite-safety clause (Step 5f).

## Final Results

**Status: COMPLETED — 2026-11-14** (after the Phase 6 review and its fix rounds). All six steps executed; the full suite passes 512/512 on the corrected checker; the landed gate is GREEN (21/21) with the script unedited between its RED baseline and the post-landing run.

### What was implemented

1. **Step 1 — corpus sweep (user-executed).** The guarded hand-off script retired the dead verification corpus: 291 files under `tmp/verification/` (belonging to terminal or never-started plans, or to no plan) plus 34 orphan `claude-retry-proxy-test-state-<pid>.json` files, quarantined to `tmp/retired-artifacts/2026-11-14-verification-runtime-isolation-2026-11-14-160323/` with per-file byte verification before delete; 1 orphan skipped as alive (`test-state-51168.json` — its PID was live at sweep time); exit 0.
2. **Step 2 — helping-files audit.** 17-row findings table (recorded in Proposed Changes): every audited doc surface dispositioned with exact landing text, feeding Step 5.
3. **Step 3 — the committed checker.** `scripts/check_spawn_isolation.py`: stdlib-only corpus checker enforcing the canonical isolation block (§Canonical compliant block) on proxy-spawning scripts, with the state-anchored exemption, encoding-defect detection, torn-read guard, and visible corpus-absent/empty roots. Live-corpus precondition: 2 spawners / 2 exempt / 0 fail.
4. **Step 4 — the suite hook.** `tests/test_spawn_isolation.py`: twelve permanent cases, registered in the aggregator (round 1: 512/512).
5. **Step 5 — docs landed (planner).** All six surfaces per the Step 2 table (see Documentation). Landed gate RED→GREEN (21/21, script unedited); targeted battery 4/4; `doc_structure_check.py` PASS; CLAUDE.md rule-keyword count unchanged (0/0/0).
6. **Step 6 — adoption.** `orphaned-test-state-files` resolved (mechanism closed, enforced, documented). Leftover check (dated snapshot, never a durable zero): the 2026-11-14 sweep retired 34 orphans; post-adoption measure-on-demand → 1 (the alive-skip, dies with its process; deletable by hand thereafter). New orphans can only be minted by scripts that skip the convention, which the suite hook flags every pass.

### Phase 6 review and fix rounds

The reviewer (non-blocking: 1 High / 2 Medium / 8 Low + 6 hunches) found the exemption's state anchor insufficient — the landed doc's central guarantee was false. **Disposition: spec strengthened, not claim weakened.** The exemption now waives only the trace/compatibility assignments; the mkdtemp derivation, the state assignment, and ordering stay enforced under the marker — closing the reviewer's live-`_ISOLATION_DIR` hole and, in processing, the ordering hole (a post-spawn pair under the marker was equally green-lit). Coder fix round: all four checker changes landed with RED calibration (round report `-coder-…-2.json`); one tester-lane issue filed and closed. Tester fix round (attempt 2; attempt 1 was killed by a host sleep — see History): teeth-substring pins moved to the token-naming message, exempt teeth + control-char sanitizer sub-assertion added, the satisfiability fixture's import comparator made real (F6), the default-root run moved to a foreign cwd (F7) — every new assertion mutation-calibrated against a checker carrying its defect. Full suite after the fixes: **512 passed, 0 failed** (634 s); corpus 2 EXEMPT / 0 FAIL; landed gate 21/21 re-confirmed. Reviewer hunches 1–2 folded into the doc's declared limitations (deliberate tampering out of scope); hunches 3–6 recorded, not actioned (hand-run availability notes / out-of-scope shapes).

### Test results

- Full suite: 512 passed, 0 failed, exit 0 (post-fix round, 634 s); 1 documented platform note (`spawn-isolation-unreadable-directory`, POSIX-only construct; executes its pass-skip branch on Windows).
- Landed gate: 21/21 checks pass, exit 0 (RED baseline 0/21 recorded pre-landing; re-confirmed after the review-fix doc edits).
- Doc real-tree: 263 anchors checked across 8 pages, status ok; doc-structure checker PASS.

### Issues resolved

- `blanking-offset-basis-claim` — Resolved (planner, spec-text fix; see Issue Log).
- `teeth-spawn-call-substring` — Resolved (tester; plan-mandated message change invalidated two teeth substring pins).
- `orphaned-test-state-files` — Resolved (this plan's adoption; its report retires via `/update-and-commit` Step 9.6's hand-off).

### Deferred issues

- None outstanding from this plan. (The standalone deferral `defer-issue-httpx2-native-sse-transport.json` belongs to no plan; the user sequenced it after this one.)

### Retire inventory

See Plan Metadata `retire_inventory` (14 artifacts: 2 verification scripts, 3 mega-audit reports, the review report, 4 session reports, 4 round logs; issue reports ride Step 9.6 via their Issue Log links). Retained gitignored scratch, not plan artifacts: the tester's `tmp/suite_capture.py`/`tmp/suite_wait.py` helpers, the coder's `tmp/spawn-iso-fix/` fixtures, the tester's `tmp/spawn-iso-mutation/` calibration harness, and a stale `scripts/__pycache__/` entry from importing the checker.
