# Plan: Extract Claude retry proxy into a standalone pip-installable package
**Project:** $PWD (D:\proj\claude-retry-proxy)
**Plan ID:** 2026-07-17-extract-retry-proxy
**Created:** 2026-07-17

## Changelog
- **2026-07-17**: Initial plan. Greenfield extraction of `root/proxy/claude-proxy-server.py` and `bin/claude-proxy` from `D:/proj/claude-config` into a new pip-installable package `claude-retry-proxy`.
- **2026-07-18**: Post-implementation `/update-plan` (coder + tester round 1). Coder completed Steps 1, 2, 3, 5 (build passes); tester ported Step 4 (12/24 pass — 12 CLI tests fail on environment, 1 `trace_markers` fails on a port fidelity regression). Three items addressed:
  - Fixed planner-owned step1 verify script: `parse_toml_text` read scripts from `data["project_scripts"]` but tomllib nests at `data["project"]["scripts"]` → both console-script checks false-failed on Python 3.11+; regex fallback `^`-anchor missed indented `[project.scripts]` entries. ([step1-verify-tomllib-key-mismatch](./tmp/reports/2026-07-17-extract-retry-proxy-step1-verify-tomllib-key-mismatch.json))
  - Added environment precondition: 12 CLI-dependent tests require `ANTHROPIC_BASE_URL` in `~/.claude/settings.json` to be a **non-localhost** URL (the CLI correctly rejects localhost to prevent proxy-to-self). Not a code bug. ([tests-require-non-localhost-upstream](./tmp/reports/2026-07-17-extract-retry-proxy-tests-require-non-localhost-upstream.json))
  - Directed tester to fix two Step-4 port-fidelity regressions in `test_trace_markers`: (a) missing-`proxy_stop` was downgraded from upstream's `warn()` to `fail()` — on Windows `proc.terminate()` hard-kills (bypasses the server's `finally`/`proxy_stop` write), which is exactly the abrupt-termination case upstream tolerated with `warn()`; (b) the port checks the wrong field name `total_requests` — the server writes `requests_total`. (Tester prose blocking_failure, not separately filed.)
- **2026-07-18 (round 2)**: Post-implementation `/update-plan` (tester round 2). Tester applied both `test_trace_markers` fixes → test 6 now passes (`PASSED (warn: no proxy_stop — Windows terminate() hard-kill)`). The 12 CLI tests now pass (environment precondition met — `ANTHROPIC_BASE_URL` set to non-localhost). **Result: 23/24 pass (overall SUCCESS).** Sole remaining failure: `test_start_early_exit_rollback` (test 12) — the pre-existing upstream port-bind race (audit iter3 H6) where the CLI's TCP readiness probe races past the server's asynchronous bind failure on Windows. Tester filed it `pre_existing: true`, explicitly out of scope for the extraction. **Resolution: acknowledge as pre-existing, document, leave Open for a future hardening plan.** No code/test change in this round. ([start-early-exit-rollback-port-bind-race](./tmp/reports/2026-07-17-extract-retry-proxy-start-early-exit-rollback-port-bind-race.json))

## Introspection Log
*Auto-generated after significant plan revisions. See Phase 5 for the audit checklist.*

| Date | Trigger | Scope | Findings | Verdict |
|------|---------|-------|----------|---------|
| 2026-07-18 | Phase 4.5 mega-audit (3rd iteration) | Whole plan + verification scripts | Verdict: "Issues found — plan needs revision" (audit_status: partial). 14 High, 37 Medium, 33 Low. **Triage: only 3 of the 14 Highs were genuine plan/verify-script defects; the rest re-flag pre-existing upstream behavior the plan faithfully preserves ("port near-verbatim"):** H2/H14 (server reads swapped settings.json — by design, CLI passes --upstream-url), H3 (cmd_stop double release_swap_lock — upstream, handles ENOENT), H4 (_shutting_down on restart — new process each start), H5 (write_state os.replace on Windows under AV — upstream), H6 (port-bind race — upstream), H7 (parse_upstream failure on both paths → sys.exit(1) — the *correct* behavior the plan specifies; misread as defect), H8 (retry attempt indexing — upstream, correct), H9 (2s TCP probe — upstream), H10 (rollback proc capture — upstream), H11 (shutdown HTTP behind long request — ThreadingHTTPServer handles /admin/shutdown on a separate thread). **Genuine fixes applied:** H1 (step3 verify `if "claude-proxy" in src` false-positived on `claude-retry-proxy` → regex with negative lookbehind/lookahead), H12 (`tmp/` gitignored but verification scripts "part of this plan" → clarified they're workflow artifacts, not committed), H13 (step1 verify allowed `>=3.7` → reject below 3.8). Medium fixes: prose "≤3.7"/"3.7+" → "3.8+", coder-verify substring wording, source-attributed error message (M5). **Pre-existing upstream behaviors (H2-H11,H14) acknowledged but NOT changed — out of scope for an extraction; documented in design Risks where user-facing.** 3-iteration cap reached; escalating to user. |
| 2026-07-17 | Phase 4.5 mega-audit (2nd iteration) | Whole plan + verification scripts | Verdict: "Issues found — plan needs revision." 12 High (down from 24), 38 Medium, 33 Low. Remaining High clusters: (1) wrong test-name attribution — `[claude-proxy]` prefix grep at line 2204 is in `test_stop_trace_no_proxy`, NOT `test_stop_trace_with_proxy` (H1/H6/H7, 3 lenses); (2) `probe_ok` replacement conflated producer loops vs consumer call-sites that receive `(proc, auth_token)` from the helper — helper must return `(proc, probe_ok)` (H2); (3) missed `claude-proxy stop` print at line 631 + line 668 usage in cli.py rename (H3); (4) src-layout editable install needs setuptools≥64, 3.7 too old → raise floor to 3.8, pin build backend (H4); (5) `os.chmod(0o600)` is a near-no-op on Windows → POSIX-guard only, document Windows ACL (H5/H9); (6) step4 verify `EXPECTED_PRESENT` had 22 names not 24 — missing `test_stop_cleans_proxy_state_lock`, `test_start_stdout_not_contaminated` (H10/H11); (7) two inline `X-Proxy-Auth` headers at ~1175/2103 outside `_send_proxy_request` → NameError after `auth_token` removal; verify only scanned the helper (H12). Medium added: SETTINGS_FILE prereq must be preserved (M4/M32), docstring test-7 enumeration must be removed (truncated iter-1 finding), `--upstream-url` doc in README (M9), 30s stale-lock vs slow-start (M25, pre-existing). | Revised: corrected test attribution; specified helper returns `(proc, probe_ok)` + consumer destructuring; added lines 631/668 to rename + bare-`claude-proxy` grep; raised Python floor to 3.8 + pinned `setuptools>=64`; made 0600 POSIX-guarded + applied to write_state; added 2 missing test names + exactly-24 check; added inline X-Proxy-Auth sites + whole-file scan with no-auth allowlist; preserved SETTINGS_FILE prereq; docstring enumeration removal; design Risks updated (test-7 resolved: dropped; H8 worst-case hold time; Windows chmod no-op). Re-running mega-audit (iteration 3). |
| 2026-07-17 | Phase 4.5 mega-audit (1st iteration) | Whole plan | Verdict: "Issues found — plan needs revision." 24 High, 35 Medium, 34 Low across 12 lenses. Key High clusters: (1) test-runner prerequisite block / `SourceFileLoader` / `sha256` drift break when `CLAUDE_PROXY`/`PROXY_SERVER` become command-lists (H1,H2,H6,H7,H14-H19); (2) "26 tests" wrong — upstream has 25 (H3,H13); (3) deleting `auth_token` leaves readiness guards broken (H4); (4) test 7 deploy_protection non-portable but coder-verify demands it (H5,H8,H18); (5) coder assigned a test file — boundary violation, undocumented (H11,H23); (6) root CLAUDE.md + git init without the mandated "public about Claude tooling?" ask (H12); (7) step4 scripted grep would fail on retained tests 25-26 (H20); (8) no secret scan before publicizing (H21); (9) `--all` logs raw prompts/completions to plaintext, no 0600 (H22); (10) LICENSE double-assigned (H24). Medium added: `PROXY_IDLE_TIMEOUT` dead env var in tests (M8,M16), Windows PATH for console-script smoke (M5), no plan-level rollback (M30), response-streaming has no size cap (M32, pre-existing), public-package tests touch real settings.json (M34, inherent to locked decision). | Revised: moved test-port to tester (resolves boundary violation + test-runner rewrites as tester-owned work); corrected count to 25; concretized test-7 handling; added Document Overrides; added Planner ask for CLAUDE.md git-tracking; added secret-scan + trace-file 0600 + rollback steps; fixed step4 verify script; single-owner LICENSE. Re-running mega-audit. |

## Summary

`D:/proj/claude-config` contains a personal Claude Code config repo. Among its pieces are two proxy-related files:

- `root/proxy/claude-proxy-server.py` — a stdlib-only HTTP retry proxy server (retries 503 with exponential backoff, JSONL trace logging, ThreadingHTTPServer, localhost-only).
- `bin/claude-proxy` — a stdlib-only CLI (`start`/`stop`/`status`) that swaps `ANTHROPIC_BASE_URL` in `~/.claude/settings.json` to `http://localhost:PORT` while the proxy runs, manages a lock file for crash recovery, and kills the server cross-platform (ctypes on Windows).

Both are currently copied into `~/.claude/` by `claude-config/deploy.py`. The goal is to extract them into a **new, standalone, public, pip-installable** repository at `D:/proj/claude-retry-proxy`, so it can be `pip install`-ed and published (git publicized) independently of the personal config repo.

### Locked design decisions (from Phase 3 discussion)

| Decision | Resolution |
|---|---|
| Upstream URL source | Hardcoded `~/.claude/settings.json` `env.ANTHROPIC_BASE_URL`. Server reads it; CLI swaps it. No env-var fallback, no `--settings-path` flag. |
| Package / import name | `claude-retry-proxy` → `import claude_retry_proxy` |
| Console command | `claude-retry-proxy` (renamed from `claude-proxy` to match the package). Subcommands unchanged: `start`, `stop`, `status`. |
| Server entrypoint | Server invoked by the CLI via `python -m claude_retry_proxy.server`. A `claude-retry-proxy-server` console script is also exposed for direct invocation. |
| Auth-token plumbing | Removed from tests. Server-side is already auth-free (confirmed by plan 2026-07-16-remove-proxy-proxy-auth; tests 25-26). |
| claude-config | Untouched. Switch-over is a separate future effort. |
| Python version | 3.8+ (PEP 621 + PEP 660 src-layout editable installs need setuptools ≥64; 3.7's bundled toolchain is too old). Stdlib-only, zero runtime deps. |
| Server startup refactor | Move the module-level `read_upstream_url()` + `parse_upstream()` + `sys.exit(1)` block into `main()` so `--upstream-url` and settings-file read are resolved at runtime, not import time. See Design. |

### Out of scope
- Modifying `claude-config` (deploy.py, README, root/proxy copy) — separate effort.
- PyPI upload automation / CI — out of scope; "git publicized" means the repo is structured for it, not that publishing is automated.
- Adding new proxy features. This is an extraction + packaging task, not a feature task.

## Document Overrides

If the plan intentionally contradicts a documented rule (in `CLAUDE.md` or `doc/*`), declare the override here. An empty or absent table means zero tolerance — every documented rule is in force.

| Document | Rule Overridden | Reason |
|----------|----------------|--------|
| `~/.claude/CLAUDE.md` "Git Commits" + planner.md Core Constraints (coder never touches tests) | None — the original draft violated these by assigning the test file to the coder; **revised**: the test port/clean is now tester-owned (Step 4 is tester work). No override needed. | n/a |
| `~/.claude/CLAUDE.md` "CLAUDE.md Maintenance" / global "Before making a root CLAUDE.md tracked by git" | Planner performs the mandated user-ask before creating/tracking the root CLAUDE.md (Step 6). No override — rule is honored. | n/a |

*No documented rule is overridden by this plan. The coder never writes tests or docs; the tester owns all test work; the planner owns all docs and the CLAUDE.md-tracking ask.*

## Design

See `2026-07-17-extract-retry-proxy-design.md` for architecture, data flow, the server startup refactor, and the auth-token cleanup rationale.

## Proposed Changes

Each step includes verification checks tagged with confidence (see Prime Directive 4).
`(auto)` = mechanical, coder self-verifies. `(scripted)` = deterministic multi-step, coder runs provided script.
Every step must have at least one coder check.

### Step 1: Package skeleton (pyproject.toml, src layout, LICENSE, .gitignore, git init)

Create:
- `pyproject.toml` — setuptools backend, src-layout. Metadata: name `claude-retry-proxy`, python `>=3.8` (PEP 621 declarative metadata needs setuptools ≥61; src-layout PEP 660 editable installs need setuptools ≥64 — Python 3.7's bundled toolchain is too old and unreliable for this; raise the floor to 3.8 and pin the build backend), zero runtime dependencies. `[build-system] requires = ["setuptools>=64", "wheel"]`. `[project.scripts]` exposes `claude-retry-proxy = "claude_retry_proxy.cli:main"` and `claude-retry-proxy-server = "claude_retry_proxy.server:main"`. `[tool.setuptools.packages.find]` where = `["src"]`. (Audit: H4, M15 — pinning the build backend avoids broken editable installs on stock toolchains.)
- `src/claude_retry_proxy/__init__.py` — `__version__ = "0.1.0"`.
- `LICENSE` — MIT (confirmed with user; repo will be git-publicized).
- `.gitignore` — Python defaults (`__pycache__/`, `*.pyc`, `build/`, `dist/`, `*.egg-info/`, `.venv/`, `tmp/`). **`tmp/` is gitignored intentionally** — it holds planning artifacts (plans, reports, verification scripts) that are part of the *planning workflow*, not the published package. The coder runs the verification scripts from the working tree during implementation; they are not committed. (Audit iter3 H12.)
- `git init` the repo.

→ coder verify (auto): "`pyproject.toml` exists at repo root; `[project] name = \"claude-retry-proxy\"`; `[project.scripts]` lists both `claude-retry-proxy` and `claude-retry-proxy-server`; `src/claude_retry_proxy/__init__.py` defines `__version__`."
→ coder verify (scripted): `./tmp/verification/2026-07-17-extract-retry-proxy-step1.py` — parses `pyproject.toml` with `tomllib` (3.11+) or a stdlib regex fallback; asserts package name, both console scripts present, python_requires lower bound is `>=3.8` (rejects below), `[build-system]` pins `setuptools>=64`, no `[project.dependencies]` entries (zero deps). Asserts `src/claude_retry_proxy/__init__.py` imports and has `__version__`. Exits 0 on pass.

### Step 2: Port the server into `src/claude_retry_proxy/server.py` (with startup refactor)

Copy `claude-config/root/proxy/claude-proxy-server.py` → `src/claude_retry_proxy/server.py`. Behavioral content stays near-verbatim (retry logic, trace logging, header forwarding, `/admin/shutdown`, signal handling, ThreadingHTTPServer, all env-var config). Apply **one refactor** (see Design):

- Remove the module-level block (current lines 108-116) that calls `read_upstream_url()` / `parse_upstream()` at import time and `sys.exit(1)` on failure. Move that resolution into `main()` so it runs after argparse, alongside the existing `--upstream-url` override (current lines 519-526). `UPSTREAM_HOST` etc. become module globals assigned inside `main()`. **Explicit resolution logic in `main()`** (audit M2): the upstream `main()` only handles `if args.upstream_url is not None:`; once the module-level read is removed, direct invocation without `--upstream-url` would leave `UPSTREAM_URL` empty. So `main()` must do:
  ```python
  if args.upstream_url is not None:
      UPSTREAM_URL = args.upstream_url
  else:
      UPSTREAM_URL = read_upstream_url()
  parsed = parse_upstream(UPSTREAM_URL)        # unconditional None-check
  if parsed is None:
      if args.upstream_url is not None:
          print("[proxy] ERROR: Invalid --upstream-url: {}".format(UPSTREAM_URL), file=sys.stderr)
      else:
          print("[proxy] ERROR: Could not parse ANTHROPIC_BASE_URL from settings.json: {!r}".format(UPSTREAM_URL), file=sys.stderr)
      sys.exit(1)
  UPSTREAM_HOST, UPSTREAM_PORT, UPSTREAM_USE_SSL, UPSTREAM_PATH_PREFIX = parsed
  ```
  This matches the design doc's code example and the upstream error-message style (lines 523-524). Direct invocation (`claude-retry-proxy-server` with no `--upstream-url`) now reads settings.json at runtime and emits a clean, source-attributed error if it can't parse the URL, instead of failing later at connection time. (Audit iter3 M5 — keep the data source in the message.)
- Update the `--upstream-url` help text and any internal references that assumed the script lives under `~/.claude/proxy/`.
- Keep `STATE_FILE` (`~/.claude/proxy/proxy-state.json`) and `PROXY_TRACE_FILE` default (`~/.claude/logs/proxy-trace.jsonl`) paths as-is — these are runtime artifacts, not config coupling, and match the hardcoded-settings decision.
- **Trace-file / state-file permission hardening (audit H5/H9/M35):** in `log_trace` (for `PROXY_TRACE_FILE`) and in `write_state` (for `STATE_FILE`, which persists the user's real upstream URL — sensitive), apply restrictive perms **on POSIX only**, guarded by `if os.name == 'posix':` (best-effort, wrapped in try/except so a failure never breaks logging). `os.chmod(path, 0o600)` on Windows is a near-no-op (toggles only the read-only attribute bit; no group/other model in NTFS DACLs), so it must NOT be relied upon there. The README (Step 6b) documents this explicitly: the 0600 chmod is a POSIX-only mitigation; **Windows users must restrict the trace/state directory ACL manually** (e.g. `icacls`). Do not imply the chmod alone protects the data on Windows.

→ coder verify (auto): "`src/claude_retry_proxy/server.py` defines `main()`; no module-level call to `read_upstream_url()` or `parse_upstream()` exists at top level (grep for these names outside function defs returns only the def lines + call sites inside `main()`); `if __name__ == \"__main__\": main()` present; `main()` contains an `else:` branch calling `read_upstream_url()` when `args.upstream_url is None`; `log_trace` and `write_state` apply `os.chmod(..., 0o600)` guarded by `os.name == 'posix'`."
→ coder verify (scripted): `./tmp/verification/2026-07-17-extract-retry-proxy-step2.py` — imports `claude_retry_proxy.server` as a module (must NOT sys.exit on import even with a bogus/absent settings.json); confirms `main`, `forward_request`, `ProxyHandler`, `compute_delay`, `log_trace`, `read_upstream_url`, `parse_upstream` are all callable/defined; confirms `main` source has the `else: ... read_upstream_url()` branch and an unconditional `parse_upstream` None-check; confirms `log_trace` and `write_state` sources contain `0o600` and a `posix` guard; confirms `python -m claude_retry_proxy.server --help` exits 0 and prints usage. Exits 0 on pass.
→ tester verify: behavioral — retry-on-503, trace markers, concurrent requests, 413 logging, thread safety (ported tests).

### Step 3: Port the CLI into `src/claude_retry_proxy/cli.py` (rename command)

Copy `claude-config/bin/claude-proxy` → `src/claude_retry_proxy/cli.py`. Keep ALL logic: URL swap locking (O_EXCL + stale detection), `is_pid_alive` (ctypes on Windows + tasklist fallback), `kill_process_windows`, URL lock I/O, settings I/O, `validate_url`, crash recovery, rollback, TCP readiness probe, graceful HTTP shutdown + force-kill ordering. Apply these changes:

- Rename: usage strings, `prog="claude-proxy start"` → `prog="claude-retry-proxy start"`, `print_usage()` header, **and the runtime print at line 631 (`print("  Run 'claude-proxy stop' to clean up")` inside `cmd_status`) and line 668 (`print("Usage: claude-proxy <command> ...")` in `main`'s else-branch)** — both are user-facing and must say `claude-retry-proxy`. The coder must grep `cli.py` for the bare string `claude-proxy` (not just the bracketed `[claude-proxy]` form) and replace every user-facing occurrence. (Audit: H3.)
- Change `PROXY_SCRIPT` resolution: instead of `os.path.join(PROXY_DIR, "claude-proxy-server.py")`, launch via `[sys.executable, "-m", "claude_retry_proxy.server", ...]`. Keep passing `--port`, `--upstream-url`, `--log`, `--all` exactly as before.
- Keep `PROXY_DIR = ~/.claude/proxy`, `SETTINGS_FILE = ~/.claude/settings.json`, all lock file paths unchanged (matches hardcoded-settings decision).
- Keep the `_trace("[claude-proxy] ...")` prefix — **the coder MUST change it to `[claude-retry-proxy]`** (not optional). The tester's ported tests grep stderr/stdout for the prefix and will be written to expect `[claude-retry-proxy]` (Step 4). Leaving `[claude-proxy]` would break tests 22 and 24.

→ coder verify (auto): "`src/claude_retry_proxy/cli.py` defines `main`, `cmd_start`, `cmd_stop`, `cmd_status`; `print_usage()` prints `claude-retry-proxy`; **no occurrence of the bare command `claude-proxy` (as a word, not a substring of `claude-retry-proxy`)** — grep with `(?<!-)claude-proxy(?!-)` returns empty, covering line 631, 668, prog, print_usage, and the trace prefix (which is `[claude-retry-proxy]`); no reference to `PROXY_SCRIPT` as a `.py` file path (grep for `claude-proxy-server.py` returns empty); the proxy launch command uses `\"-m\", \"claude_retry_proxy.server\"`."
→ coder verify (scripted): `./tmp/verification/2026-07-17-extract-retry-proxy-step3.py` — imports `claude_retry_proxy.cli`; confirms `cmd_start` builds a launch list containing `sys.executable`, `"-m"`, `"claude_retry_proxy.server"` and forwards `--upstream-url`; **confirms the bare command `claude-proxy` (regex `(?<!-)claude-proxy(?!-)`, so `claude-retry-proxy` is not a false match) does not appear in `cli.py`** (catches the bare-command prints at lines 631/668, not just the bracketed prefix); confirms the `[claude-retry-proxy]` trace prefix; confirms `python -m claude_retry_proxy.cli --help` and `python -m claude_retry_proxy.cli start --help` exit 0. Exits 0 on pass.
→ tester verify: behavioral — URL swapping, crash recovery, race conditions, PID-in-lock, rollback, stop cleanup, manual edit detection, swap-lock retries (ported tests, Step 4).

### Step 4: Port + clean the test suite into `tests/test_claude_proxy.py` (TESTER-OWNED)

**This step is tester work, not coder work.** The test file is tester-owned per Core Constraints; the planner's mega-audit (iteration 1) found that assigning it to the coder was a boundary violation. The tester performs the mechanical port + cleanup as the file's rightful owner. The coder does **not** touch `tests/`.

The tester copies `claude-config/tests/test_claude_proxy.py` → `tests/test_claude_proxy.py` and applies **all** of the following (each addresses a concrete audit finding):

1. **Path constants + helpers — keep them as launchable command lists, but fix every call site that assumed a file-path string.** Set:
   - `CLAUDE_PROXY` = `[sys.executable, "-m", "claude_retry_proxy.cli"]` (command list).
   - `PROXY_SERVER` = `[sys.executable, "-m", "claude_retry_proxy.server"]` (command list).
   - `DEPLOY_PY` = removed (see item 4).
   - Update `start_proxy`, `stop_proxy`, `proxy_status`, `_start_proxy_server_directly`, and every `subprocess.Popen`/`subprocess.run` site to splice the list (`cmd = CLAUDE_PROXY + ["start", ...]`), not `os.path.join`.

2. **Rewrite the `main()` prerequisite block (upstream lines ~2656-2682).** It currently does `os.path.exists(CLAUDE_PROXY)` / `os.path.exists(PROXY_SERVER)` (TypeError on a list), `os.path.exists(SETTINGS_FILE)` (keep — but it's fine as-is since `SETTINGS_FILE` is still a string path), and a `sha256(PROXY_SERVER) != sha256(DEPLOYED_SERVER)` drift check (`open(list)` TypeError; also the deployed-file concept is obsolete under pip-install). Replace the package-existence checks with an importability probe, **keep** the `SETTINGS_FILE` existence check (it gives a clean "settings.json not found" message rather than confusing FileNotFoundError later), and **delete** the drift block:
   ```python
   import importlib.util
   if importlib.util.find_spec("claude_retry_proxy") is None:
       print("claude-retry-proxy not installed; run: pip install -e .")
       sys.exit(2)
   if not os.path.exists(SETTINGS_FILE):
       print("settings.json not found: {}".format(SETTINGS_FILE))
       sys.exit(2)
   ```
   **Delete the entire `DEPLOYED_SERVER` / `sha256` drift block** — the package is pip-installed; there is no deployed `~/.claude/proxy/claude-proxy-server.py` to drift from. (Audit: H7, H17, H19; M4, M32 — `SETTINGS_FILE` check preserved.)

3. **Replace the three `SourceFileLoader("claude_proxy", CLAUDE_PROXY).load_module()` sites** (tests `test_stop_cleans_lock_on_write_failure`, `test_release_swap_lock_retries`, `test_release_swap_lock_warns_on_final_failure`) with a direct import of the installed module:
   ```python
   import claude_retry_proxy.cli as cpm
   ```
   The existing `cpm.write_settings_url = ...` / `cpm.os.remove = ...` monkeypatch pattern still works because `os` is a module-level name in `cli.py`. **Do not pass `CLAUDE_PROXY` (a list) to `SourceFileLoader`.** (Audit: H1, H14, H15.)

4. **Drop test 7 (`test_deploy_protection`) from the ported suite.** It invokes `claude-config/deploy.py`, which is not part of this repo and is explicitly out of scope. Remove the function, remove it from `ALL_TESTS`, remove the `DEPLOY_PY` constant, **and remove its entry from the docstring's numbered "Covers N test cases" enumeration** (upstream lines 4-33 list tests 1-26). Deploy protection is a `claude-config` concern, not a `claude-retry-proxy` one. (Audit: H5, H8, H18. Resolves Issue Log `deploy-protection-test-portability`.)

5. **Remove auth-token plumbing — but fix the readiness guards, don't just delete them; and split producer vs consumer scopes.** The server prints nothing to stdout. There are two kinds of readiness site:
   - **Producer loops** (inside `_start_proxy_server_directly` and the in-line readiness loops in tests 5, 6, 11, 19/22 etc. — the `try:/sock.connect()/break` blocks): delete `proc.stdout.readline()` and the `auth_token = ...line.strip()` assignment; **add `probe_ok = True` inside the `try:` right after `sock.connect()` succeeds** (alongside the existing `break`); use `proc.poll() is not None` as the server-died signal; the deadline-expiry branch (loop ends without `probe_ok`) is the failure transition.
   - **Consumer call-sites** (upstream lines ~578 and ~1394) that receive a returned tuple from `_start_proxy_server_directly`: **change the helper's return signature from `(proc, auth_token)` to `(proc, probe_ok)`**, and at the two consumer sites destructure `proc, probe_ok` and replace `if proc is None or auth_token is None:` with `if proc is None or not probe_ok:`. These sites have no `try/sock.connect` block, so `probe_ok` must come from the helper. (Audit: H2, H4, M7, M28.)
   - In `_send_proxy_request` and all callers: drop the `X-Proxy-Auth` header and the `auth_token` parameter.
   - **Two inline `X-Proxy-Auth` header constructions outside `_send_proxy_request`** (audit H12): at upstream ~line 1175 (inside `test_thread_safety`) and ~line 2103 (inside `test_trace_logs_oversized_body`), the tests build `conn.request(..., headers={...,"X-Proxy-Auth": auth_token})` manually. After `auth_token` is removed these `NameError`. **Delete the `"X-Proxy-Auth": auth_token` entry from both header dicts.**

6. **Update stderr/stdout-grep assertions** for the new `[claude-retry-proxy]` prefix. The two tests that assert the `[claude-proxy]` prefix are **`test_stop_trace_no_proxy`** (upstream ~line 2204 — `if "[claude-proxy]" in stderr:`; this is in `test_stop_trace_no_proxy` which begins at line 2168, **NOT** `test_stop_trace_with_proxy` which begins at line 2217 and contains no prefix grep) and **`test_start_stdout_not_contaminated`** (~2424/2430). Change both to `[claude-retry-proxy]`. The `cmd_stop: entering` / `read_url_lock` / `returning 0` trace strings stay (content unchanged). (Audit: H1, H6, H7 — corrected test attribution.)

7. **Leave tests 25-26 (`test_start_no_auth_header_required`, `test_proxy_state_no_auth_token`) intact.** They reference `X-Proxy-Auth` / `auth_token` in their **names, docstrings, and assertions** (asserting the *absence* of auth) — those references are correct and must remain. (Audit: H20 — the verification grep must not flag these.)

8. **Update the test-header docstring**: command name `claude-retry-proxy`, run instructions (`pip install -e .` then `python tests/test_claude_proxy.py`), and the test count. **The upstream docstring claims "26 test cases" but the file defines 25 `def test_` functions** (numbering is internally inconsistent upstream). After dropping test 7, the ported suite has **24** tests. State "24" in the docstring and `ALL_TESTS`. (Audit: H3, H13.)

9. **Tests 1-3, 8-10, 12-18 still modify the user's real `~/.claude/settings.json** (backup/restore helpers stay). This is inherent to the locked "hardcode ~/.claude/settings.json" decision and matches upstream; the test header already warns about it. For a *public* package, the tester should add a prominent note in the docstring that these tests mutate live config and should not be run casually by third-party installers. (Audit: M34.)

   <!-- UPDATED 2026-07-18: environment precondition (tests-require-non-localhost-upstream) -->
   **Environment precondition (added 2026-07-18):** 12 CLI-dependent tests (1, 2, 3, 8, 10, 12, 13, 14, 15, 20, 22, 24 — `test_url_swapping`, `test_crash_recovery`, `test_race_conditions`, `test_manual_edit_detection`, `test_pid_in_lock`, `test_start_early_exit_rollback`, `test_stop_cleans_proxy_state`, `test_stop_cleans_lock_on_write_failure`, `test_stop_kills_proxy_with_non_localhost_url`, `test_stop_trace_with_proxy`, `test_start_stdout_not_contaminated`, `test_proxy_state_no_auth_token`) start the proxy via `claude-retry-proxy start`, which reads `ANTHROPIC_BASE_URL` from `~/.claude/settings.json` and **rejects localhost** (proxy-to-self protection). If the live settings.json has a localhost URL, these 12 fail at startup with `Invalid ANTHROPIC_BASE_URL: URL is localhost`. **This is correct CLI behavior, not a bug.** To run the full suite, set `ANTHROPIC_BASE_URL` to a non-localhost URL (e.g. `https://api.anthropic.com`) first. The other 12 tests (direct-server tests) set their own mock upstream via `set_base_url()` and pass regardless. The test-header docstring must state this precondition. ([tests-require-non-localhost-upstream](./tmp/reports/2026-07-17-extract-retry-proxy-tests-require-non-localhost-upstream.json))

10. **Fix two `test_trace_markers` port-fidelity regressions (added 2026-07-18).** The tester's round-1 port diverged from upstream in two ways that cause a hard failure on Windows:
    - **(a) `warn()` → `fail()`:** upstream's missing-`proxy_stop` branch used `warn("No proxy_stop event in trace (may be expected if termination was abrupt)")` — a soft, non-failing warning. The port changed it to `fail("No proxy_stop event in trace")`. On Windows, `proc.terminate()` sends a hard `TerminateProcess` that bypasses the server's `finally` block (which writes `proxy_stop`) — exactly the abrupt-termination case upstream tolerated. **Restore `warn()` for the missing-`proxy_stop` branch** (keep the `pass_()` for the found case). (Tester prose blocking_failure; [trace-markers-stop-marker-port-regression](#) in Issue Log.)
    - **(b) Wrong field name:** the port checks `stop_events[0].get("total_requests")`, but the server writes `"requests_total"` ([server.py:203](src/claude_retry_proxy/server.py)). **Change the check to `requests_total`** so the counter assertion is correct even when a `proxy_stop` event is present. (Upstream used `requests_total`.)
    Both are port-fidelity fixes to the tester's own file — no server/CLI change.

→ coder verify (auto): **N/A — the coder does not touch `tests/`.** (This step has no coder check because it is not coder work. The tester self-verifies.)
→ tester verify (scripted): `./tmp/verification/2026-07-17-extract-retry-proxy-step4.py` — greps `tests/test_claude_proxy.py` for **all 24** expected `def test_` names (must all be present, including `test_stop_cleans_proxy_state_lock` and `test_start_stdout_not_contaminated`; `test_deploy_protection` must be absent); confirms zero `SourceFileLoader`, zero `DEPLOYED_SERVER`, zero `sha256(PROXY_SERVER)`, zero `os.path.exists(CLAUDE_PROXY)`, zero `proc.stdout.readline()`; **scans the WHOLE file for `X-Proxy-Auth` and allows it ONLY inside the two no-auth tests** (`test_start_no_auth_header_required`, `test_proxy_state_no_auth_token`) — it must not appear in `_send_proxy_request`, `test_thread_safety`, or `test_trace_logs_oversized_body` (audit H12); confirms `claude_retry_proxy` is imported (not file-pathed); confirms the `[claude-retry-proxy]` prefix is asserted and `[claude-proxy]` appears nowhere. Exits 0 on pass.
→ tester verify (behavioral): `python tests/test_claude_proxy.py` runs against the pip-installed package; **with `ANTHROPIC_BASE_URL` set to a non-localhost URL, all 24 tests pass** (the 12 CLI tests require this; the 12 direct-server tests pass regardless). `test_trace_markers` must no longer hard-fail on a missing `proxy_stop` event (it warns, matching upstream).

### Step 5: pip install + console-script smoke test (CODER)

After Steps 1-3 (coder source) are done, install the package editable and smoke-test invocation. (Does not depend on Step 4 — the tester can run Step 4 in parallel once the package installs.)

- `pip install -e .` from repo root (must succeed, zero deps).
- `python -m claude_retry_proxy.cli --help` → exit 0 (invocation that does not depend on PATH).
- `python -m claude_retry_proxy.server --help` → exit 0.
- If the console scripts are on PATH: `claude-retry-proxy --help` and `claude-retry-proxy-server --help` → exit 0. (On Windows the Scripts dir may not be on PATH — the scripted check must fall back to `python -m` and not hard-fail on a missing PATH entry. Audit: M5.)

→ coder verify (auto): "`pip install -e .` exits 0; `python -m claude_retry_proxy.cli --help` exits 0; `python -m claude_retry_proxy.server --help` exits 0."
→ coder verify (scripted): `./tmp/verification/2026-07-17-extract-retry-proxy-step5.py` — runs `pip install -e .`; invokes the CLI and server via `python -m ...` (PATH-independent) AND via the console scripts if `shutil.which` finds them (non-fatal if absent on Windows); asserts the `-m` invocations exit 0 with `usage` in output. Exits 0 on pass.

### Step 6: Planner — CLAUDE.md git-tracking ask, README/CLAUDE.md docs, secret scan (PLANNER)

This step is planner work, executed after the coder finishes Steps 1-3 and 5. It has three parts:

**6a. CLAUDE.md git-tracking ask (MANDATORY before any commit).** Per global `~/.claude/CLAUDE.md` ("Before making a root CLAUDE.md tracked by git, explicitly ask the user whether they want the repo to be public about Claude tooling. Do not do this silently."), the planner asks the user:
> "This repo will be git-publicized. The root `CLAUDE.md` documents Claude-facing tooling (build/test commands, the settings.json coupling, gotchas). Should `CLAUDE.md` be (a) git-tracked and public, or (b) gitignored (local-only)?"
Record the answer. If (b), add `CLAUDE.md` to `.gitignore`. (Audit: H12.)

**6b. Documentation.** Create `README.md` (user-facing) and `CLAUDE.md` (Claude-facing) per the Guidance for Planner spec below. **`README.md` must prominently document the data-exposure implication of `--all`/`PROXY_LOG_ALL`** (it writes raw prompts and completions to an unencrypted plaintext trace file) and recommend restricting the trace file's permissions. (Audit: H22, M31.)

**6c. Secret scan before publicizing.** The repo is a fresh `git init` (Step 1) with no inherited history, so historical-secret risk is bounded to the ported files. The planner runs a secret scan (e.g. `gitleaks` / `trufflehog` / a stdlib regex pass for API-key patterns, `sk-`, bearer tokens, and the user's real upstream host) over the new repo's working tree. Any hit must be replaced with a placeholder before the first commit. README/CLAUDE.md examples use `https://api.anthropic.com` (the public default), never a personal upstream. (Audit: H21.)

→ planner verify (auto): "`README.md` and `CLAUDE.md` exist; README mentions `--all`/`PROXY_LOG_ALL` and the plaintext-exposure warning; CLAUDE.md-tracking decision recorded; secret scan run with no unresolved hits."

## Rollback / Revert Strategy

(Audit M30.) This plan creates a **new** repo at `D:/proj/claude-retry-proxy`. It does not modify `claude-config`. Reverting is therefore trivial:

- **Full revert:** delete the `D:/proj/claude-retry-proxy` directory (and `pip uninstall claude-retry-proxy` if installed). No other repo is affected.
- **Partial revert (source only, keep tests):** the tester's `tests/` and the coder's `src/` are independent; either can be discarded without touching the other.
- **`pip install -e .` side effects:** an editable install adds an `.egg-link`/`__editable__` entry to the active Python's site-packages and may add console-script shims to its `Scripts/`/`bin/`. Revert with `pip uninstall claude-retry-proxy`.
- **`~/.claude/` side effects:** running `claude-retry-proxy start` mutates `~/.claude/settings.json`, `~/.claude/proxy/*`, and `~/.claude/logs/proxy-trace.jsonl` — identical to the upstream `claude-proxy` behavior. `claude-retry-proxy stop` restores the URL. This is runtime behavior, not an install-time effect, and is not reverted by uninstalling the package.
- **Breaking-change note (audit M29):** the console command is renamed `claude-proxy` → `claude-retry-proxy`. Existing `claude-config` users who deploy the old `bin/claude-proxy` are unaffected (claude-config is untouched). A future switch-over plan (out of scope here) would handle migrating claude-config users to the new command name.

## Guidance for Planner

Documentation + governance tasks I will execute myself (not the coder, not the tester):

- **Step 6a — CLAUDE.md git-tracking ask**: ask the user before creating/tracking the root `CLAUDE.md`. **When:** after coder Step 5, before first commit.
- **`README.md`** — create. User-facing: what the proxy does, `pip install` (from git + future PyPI), `claude-retry-proxy start/stop/status` usage, `--port`/`--log`/`--all` options, env-var table (`PROXY_PORT`, `PROXY_MAX_RETRIES`, `PROXY_INITIAL_DELAY`, `PROXY_MAX_DELAY`, `PROXY_MAX_BODY_SIZE`, `PROXY_LOG_ALL`, `PROXY_TRACE_FILE`), trace-log location, crash recovery / URL-swap behavior, localhost-only binding, the `~/.claude/settings.json` coupling note, Python 3.8+ / zero-deps. **Prominent `--all`/`PROXY_LOG_ALL` data-exposure warning** (raw prompts + completions to plaintext; recommend 0700 perms / restricted dir). Document both console scripts (`claude-retry-proxy` manager + `claude-retry-proxy-server` direct — audit M12) and the `--upstream-url` flag on the server (audit iter2 M9). **When:** Step 6b.
- **`CLAUDE.md`** — create. Claude-facing: project purpose, src-layout, build/test commands (`pip install -e .`, `python tests/test_claude_proxy.py`), settings.json coupling, server-startup refactor gotcha (settings read moved into `main()`), Windows ctypes liveness/kill rationale, the trace-file 0600 hardening, gotchas (tests 1-3/8-10/12-18 modify real settings.json; `PROXY_IDLE_TIMEOUT` is a dead env var some tests set — ignored by the server). **Test-run prerequisite (added 2026-07-18, tester doc_suggestion):** state that the 12 CLI-dependent tests require `ANTHROPIC_BASE_URL` in `~/.claude/settings.json` to be a non-localhost URL — set it to a real upstream or mock before running the full suite. **When:** Step 6b.
- **Step 6c — secret scan**: run before first commit; ensure only placeholder/example URLs in docs. **When:** Step 6c.
- **`LICENSE`** — the coder creates the MIT file in Step 1 (mechanical); the planner owns the license *choice*, already confirmed with the user as MIT. Single owner of the *choice* = planner; single owner of the *file write* = coder. (Audit: H24 — no double-assignment of the file.)

## Guidance for Coder

**Files to modify:** source code + packaging ONLY — `pyproject.toml`, `src/claude_retry_proxy/__init__.py`, `src/claude_retry_proxy/server.py`, `src/claude_retry_proxy/cli.py`, `LICENSE`, `.gitignore`. Do NOT create or edit `README.md`, `CLAUDE.md`, any `doc/**`, or **anything under `tests/`** — tests are the tester's, docs are the planner's. (Audit: H11, H23 — the test file is no longer in the coder's scope.)

**Step-by-step with verification:** each coder step (1, 2, 3, 5) has checks tagged `(auto)` or `(scripted)`. Run every `(scripted)` check with `python ./tmp/verification/<plan-id>-<stepN>.py` from the repo root. The verification scripts are provided by the planner and are part of this plan.

**Source of truth:** the upstream files to port are at:
- `D:/proj/claude-config/root/proxy/claude-proxy-server.py` → `src/claude_retry_proxy/server.py`
- `D:/proj/claude-config/bin/claude-proxy` → `src/claude_retry_proxy/cli.py`

Port near-verbatim; apply only the changes each step lists. Do not refactor retry logic, trace schema, lock semantics, or Windows process handling beyond what the steps specify.

**Do not:**
- Do not add runtime dependencies. Stdlib only.
- Do not change the trace JSONL schema, lock-file format, or `proxy-state.json` shape (must stay compatible with `claude-config` deploy.py deploy-protection, even though claude-config is untouched here).
- Do not change `~/.claude/settings.json`, `~/.claude/proxy/`, or `~/.claude/logs/` paths.
- Do not touch `tests/`. The tester owns the test port (Step 4).
- Do not write `README.md`, `CLAUDE.md`, or docs — the planner owns those (Step 6).

## Guidance for Tester

**You own Step 4** — the port + cleanup of `tests/test_claude_proxy.py`. Apply all 9 items in Step 4. The file is permanent.

**Run** `pip install -e .` (coder Step 5) then `python tests/test_claude_proxy.py` against the installed package.

**The 24 ported tests** (25 upstream minus dropped test 7) cover: URL swapping, crash recovery, races, concurrent requests, retry logic, trace markers, URL validation, manual edit detection, thread safety, PID-in-lock, relative log path, rollback, stop cleanup, swap-lock retries, 413 logging, trace output, no-auth (tests 25-26). Deploy protection (old test 7) is dropped — it's a `claude-config` concern.

**Permanent vs temporary:** the ported `tests/test_claude_proxy.py` is permanent. Any new tests you add are permanent unless marked temporary.

**Environment caveat:** tests 1-3, 8-10, 12-18 modify the real `~/.claude/settings.json` (with backup/restore). If `ANTHROPIC_BASE_URL` is unset, some tests warn/skip — same as upstream. Add a prominent docstring note that these tests mutate live config (audit M34).

**Known dead env var:** `PROXY_IDLE_TIMEOUT` is set by ~5 tests but the server defines no such feature (removed upstream). The var is harmlessly ignored. Leave as-is for port fidelity (audit M8, M16).

## Documentation

- `README.md` (planner, Step 6b) — usage, install, env vars, trace log, `--all` exposure warning, both console scripts.
- `CLAUDE.md` (planner, Step 6b) — project structure, build/test, gotchas. Git-tracking decided in Step 6a.
- `LICENSE` (coder, Step 1 — MIT; choice confirmed by planner with user).
- `2026-07-17-extract-retry-proxy-design.md` (planner) — this plan's design rationale, linked above.

## Issue Log
| Issue | Status | Found | Resolved | Resolved By |
|-------|--------|-------|----------|-------------|
| deploy-protection-test-portability | Resolved | 2026-07-17 | 2026-07-17 | planner |
| test-runner-prereq-breaks-on-list-constants | Resolved | 2026-07-17 | 2026-07-17 | planner |
| auth-token-removal-leaves-readiness-guards-broken | Resolved | 2026-07-17 | 2026-07-17 | planner |
| coder-assigned-test-file-boundary-violation | Resolved | 2026-07-17 | 2026-07-17 | planner |
| trace-file-plaintext-exposure | Fix Planned | 2026-07-17 | — | coder (server.py 0600) + planner (README warning) |
| response-streaming-no-size-cap | Open | 2026-07-17 | — | — |
| tests-mutate-real-settings-json | Open | 2026-07-17 | — | — |
| [step1-verify-tomllib-key-mismatch](./tmp/reports/2026-07-17-extract-retry-proxy-step1-verify-tomllib-key-mismatch.json) | Fix Planned | 2026-07-18 | — | planner (verify script) |
| [tests-require-non-localhost-upstream](./tmp/reports/2026-07-17-extract-retry-proxy-tests-require-non-localhost-upstream.json) | Resolved | 2026-07-18 | 2026-07-18 | planner (precondition note — environment, not code) |
| trace-markers-stop-marker-port-regression | Resolved | 2026-07-18 | 2026-07-18 | tester (restored `warn()` + `requests_total`) |
| [start-early-exit-rollback-port-bind-race](./tmp/reports/2026-07-17-extract-retry-proxy-start-early-exit-rollback-port-bind-race.json) | Open | 2026-07-18 | — | — |

*Issue notes:*
- *deploy-protection-test-portability* — resolved by dropping test 7 (Step 4 item 4).
- *test-runner-prereq-breaks-on-list-constants* — resolved by Step 4 items 1-2 (importability probes, delete drift block).
- *auth-token-removal-leaves-readness-guards-broken* — resolved by Step 4 item 5 (`probe_ok` guards).
- *coder-assigned-test-file-boundary-violation* — resolved by moving Step 4 to the tester.
- *trace-file-plaintext-exposure* — **Fix Planned (in-plan)**: Step 2 directs the coder to add POSIX-guarded `os.chmod(path, 0o600)` in both `log_trace` (trace file) and `write_state` (state file, which persists the user's real upstream URL); Step 6b directs the planner to add a prominent README warning + Windows-ACL guidance. Closes on coder+planner completion.
- *response-streaming-no-size-cap* (audit M32) — Open, pre-existing upstream behavior (only request body is capped, not response). Faithfully preserved in this extraction. A future plan could cap streamed response size. Not blocking. **Recorded as a TODO in [CLAUDE.md](../../CLAUDE.md) "Future Work"** (issue `response-streaming-no-size-cap`).
- *tests-mutate-real-settings-json* (audit M34) — Open, inherent to the locked "hardcode ~/.claude/settings.json" decision. Mitigated by backup/restore + a docstring warning. Not resolvable without revisiting the locked decision.
- *step1-verify-tomllib-key-mismatch* (found by coder, `pre_existing: true`) — **Fix Planned**: the planner-owned step1 verify script reads scripts from the wrong key on the tomllib path. Fixed in the round-1 update (see Step 1 verify script). Re-ran against the coder's real `pyproject.toml` → PASS. Marking Fix Planned pending a tester/coder re-run confirmation (no separate report yet); the script is planner-owned and self-verifies.
- *tests-require-non-localhost-upstream* (found by tester) — **Resolved (2026-07-18)**: not a code/plan defect; an environment precondition. 12 CLI-dependent tests need `ANTHROPIC_BASE_URL` to be a non-localhost URL (the CLI's localhost-rejection is correct proxy-to-self protection). Documented in Step 4 precondition + Step 6b doc note. Round-2 tester report confirms all 12 CLI tests pass once a non-localhost URL is set.
- *trace-markers-stop-marker-port-regression* (tester round-1 prose) — **Resolved (2026-07-18) by tester**: the tester's port restored `warn()` for the missing-`proxy_stop` branch (Windows `proc.terminate()` hard-kills, bypassing the `finally`/`proxy_stop` write — the abrupt-termination case upstream tolerated) and corrected the field name to `requests_total`. Round-2 report: test 6 `PASSED (warn: no proxy_stop — Windows terminate() hard-kill)`.
- *start-early-exit-rollback-port-bind-race* (found by tester round-2, `pre_existing: true`) — **Open**: `test_start_early_exit_rollback` fails because the CLI's TCP readiness probe races past the server subprocess's asynchronous bind failure on Windows (`SO_REUSEADDR` semantics differ from POSIX) — the CLI reports success (exit 0) on an occupied port. Traced to upstream `bin/claude-proxy` `cmd_start` (the 2s TCP probe + `proc.poll()` check), ported near-verbatim; flagged in mega-audit iteration 3 as H6. **Not a port-fidelity regression** — upstream's test also uses `fail()` here (confirmed at `claude-config/tests/test_claude_proxy.py:1527`). **Out of scope for this extraction** — a fix is a design change (CLI must wait for the subprocess to bind-or-exit before reporting success, e.g. via a readiness handshake on a stdout line or a health-check loop that distinguishes "bound" from "not yet failed"). Deferred to a future hardening plan. Documented in design Risks **and recorded as a TODO in [CLAUDE.md](../../CLAUDE.md) "Future Work"**.

## Final Results
(Populated after implementation completes.)
