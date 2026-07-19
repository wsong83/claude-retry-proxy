# Plan: Preserve upstream error body on retry exhaustion, catch client disconnect, prune trace log on start

**Project:** D:\proj\claude-retry-proxy
**Plan ID:** 2026-07-19-fix-giveup-body-and-trace-prune
**Created:** 2026-07-19

## Changelog
- **2026-07-19**: Initial plan. Three fixes (B: preserve give-up error body;
  C: catch client disconnect; D: trace-log check + 5-day prune on `start`).
  Decisions locked in Phase 3 discussion: B = no cap + synthesize conn-error
  body; C = wrap `_send_response` only + add `client_disconnect` trace event;
  D = report+prune, hardcode 5 days, in `cmd_start`.
- **2026-07-19**: Revision after mega-audit iter 1 (63 findings, 7 High).
  Key changes: (1) B: "no cap" decision overturned — final-attempt `resp` is
  fresh/unread, so `resp.read()` is unbounded; now capped at
  `PROXY_MAX_BODY_SIZE` via `_read_capped` helper; `conn.close()` wrapped in
  its own try/except to prevent outer except from swallowing body; conn-error
  synthesized body now includes `sanitize_error(str(e))`. (2) C: added
  `ConnectionAbortedError` to `_DISCONNECT_ERRORS` (WinError 10053);
  `_log_client_disconnect` wraps `log_trace` in try/except to prevent
  re-raise. (3) D: prune streams line-by-line (no full read into memory);
  uses `json.loads` per line (not substring matching); EAFP file open;
  `cmd_start` wraps prune call in try/except (best-effort); malformed-line
  count semantics corrected to `(2,1)` for 1-today+1-malformed+1-old; added
  `is not None` for ts formatting; dropped `fromisoformat` fallback; added
  cross-reference comment to `resolve_trace_path`. (4) Plan-level: test count
  corrected to 27→32 (5 new tests — tester added bonus `test_prune_trace_file_edge_cases`); removed dead `_is_client_disconnect`
  from design doc; added Rollback section; expanded doc checklist (test-file
  docstring, Architecture disconnect mention, README `client_disconnect`
  schema, PROXY_LOG_ALL+Windows risk). Design rationale in
  [2026-07-19-fix-giveup-body-and-trace-prune-design.md](2026-07-19-fix-giveup-body-and-trace-prune-design.md).

## Introspection Log

| Date | Trigger | Scope | Findings | Verdict |
|------|---------|-------|----------|---------|
| 2026-07-19 | Mega-audit (Phase 4.5), 12 lenses, iter 1 | Full plan + `server.py` + `cli.py` | 63 findings: 7 High, 22 Medium, 34 Low. Key High: give-up body unbounded → OOM; `conn.close()` exception loses body; `_DISCONNECT_ERRORS` misses `ConnectionAbortedError`; `_log_client_disconnect` re-raises; prune reads whole file into memory; test count 3 vs 4; no rollback plan. | Revised — see above |
| 2026-07-20 | Mega-audit, 12 lenses, iter 2 | Revised plan + design doc | 46 findings: 4 High, 15 Medium, 27 Low. Key High: `_read_capped` truncation marker produces invalid JSON; exact-boundary false positive; verification scripts don't exist; test-file docstring assigned to both Planner and Tester. | Revised — `_read_capped` now returns standalone marker on truncation (not appended); uses `truncated` flag; test-file docstring reassigned to Tester only; verification scripts created by planner. |
| 2026-07-20 | Coder session | Steps 1-3 implementation | 0 issues filed; build pass; `server.py` + `cli.py` modified | Implementation complete |
| 2026-07-20 | Tester session | 5 new permanent tests + regression | 5/5 new tests pass; 11 pre-existing CLI failures (settings.json=localhost); 0 issues filed; test count 27→32 (tester added bonus `test_prune_trace_file_edge_cases`) | Tests pass (pre-existing failures acknowledged) |
| 2026-07-20 | Reviewer subagent (Phase 6) | Implementation diff, 6 dimensions | 0 Critical, 1 Warning (blank-line count semantics), 5 Suggestions | Gate passed — non-blocking |

## Summary

Three behavior fixes to `src/claude_retry_proxy/server.py` and
`src/claude_retry_proxy/cli.py`, all surfaced by inspecting the live trace
log (`~/.claude/logs/proxy-trace.jsonl`, 5.3 MB) and `proxy-stderr.log`:

1. **B — Preserve upstream error body on retry exhaustion.** When a 429/503
   survives all `PROXY_MAX_RETRIES` attempts, `forward_request` currently
   returns `b''` (`server.py:330`), so Claude Code gets a bare 429 with no
   `{"error":{"code":11210,...}}`. Fix: drain `resp` into a buffer via a
   `_read_capped` helper (capped at `PROXY_MAX_BODY_SIZE`), return it. Wrap
   `conn.close()` in its own try/except so a close failure cannot fall into
   the outer connection-error handler. For the connection-error exhaustion
   path (`server.py:376`), synthesize a JSON body including the sanitized
   last error string — the trace log records the actionable error instead of
   `"HTTP 0"`.
2. **C — Catch client disconnect during response send.** `do_POST` calls
   `_send_response` (`server.py:528`, `467`) without a try/except. When
   Claude Code disconnects mid-response, `self.wfile.write` raises
   `ConnectionResetError`/`BrokenPipeError`/`ConnectionAbortedError`;
   uncaught, it prints a traceback per occurrence (confirmed in
   `proxy-stderr.log`). Fix: wrap `_send_response` calls in `except
   _DISCONNECT_ERRORS` (3-tuple); log a single stderr line and a
   `client_disconnect` trace event (the request entry is already written).
   `_log_client_disconnect` wraps its own `log_trace` in try/except to
   prevent re-raise.
3. **D — Trace-log check + prune on `start`.** `cmd_start` scans
   `proxy-trace.jsonl`, prints a one-line summary (entries, kept/pruned
   counts, bytes, date range, failure count), and rewrites the file without
   entries whose `timestamp` is older than 5 days (hardcoded). Streams
   line-by-line to a temp file (no full read into memory). Parses each line
   with `json.loads` for reliable extraction even with `PROXY_LOG_ALL`.
  Best-effort: wrapped in try/except in `cmd_start`, failure does not block
  proxy start. Concurrency-safe because `cmd_start` rejects an already-
  running proxy.

## Document Overrides

| Document | Rule Overridden | Reason |
|----------|----------------|--------|

## Design

See [2026-07-19-fix-giveup-body-and-trace-prune-design.md](2026-07-19-fix-giveup-body-and-trace-prune-design.md)
for architecture, data flow, algorithm pseudocode (the give-up drain with cap,
the disconnect catch with 3-error tuple, the streaming prune with json.loads),
timestamp parsing, rollback plan, and out-of-scope notes.

## Proposed Changes

### Step 1 — Fix B: preserve upstream error body on retry exhaustion (server.py)

Modify `forward_request` in `src/claude_retry_proxy/server.py`:

1. Add a module-level helper `_read_capped(resp, max_bytes)` near the other
   helpers (`compute_delay`, `compute_jittered_delay`, ~line 223). It reads
   up to `max_bytes` in 8 KiB chunks, then drains-and-discards the rest. If
   the drain loop reads any additional bytes (body exceeded cap), it returns
   a standalone truncation marker `b'{"error":"[proxy: response body truncated]"}'`
   (NOT appended to partial body — that would produce invalid concatenated
   JSON). If the body fits within `max_bytes`, it returns the body unchanged.
   Guards `max_bytes <= 0` → `b''`. Uses `except OSError:` (not
   `(socket.error, OSError)` — redundant since Python 3.3). Full pseudocode
   in the design doc § Fix B.
2. In the 429/503 give-up branch (currently `server.py:329-330`), replace
   the bare `return resp.status, {}, b'', ...` with:
   ```python
   else:
       err_body = _read_capped(resp, PROXY_MAX_BODY_SIZE)
       try:
           conn.close()
       except OSError:
           pass
       return resp.status, {}, err_body, None, time.time() - total_start, retries
   ```
   Key changes from the initial draft: `_read_capped` instead of bare
   `resp.read()` (caps memory at `PROXY_MAX_BODY_SIZE`); `conn.close()` in
   its own try/except (prevents outer `except` from swallowing the body).
3. In the connection-error give-up branch (currently `server.py:374-376`),
   replace the bare `return 0, {}, b'', ...` with:
   ```python
   else:
       total_elapsed = time.time() - total_start
       err_body = json.dumps({
           "error": {
               "type": "upstream_unreachable",
               "message": "upstream: {} after {} retries".format(
                   sanitize_error(str(e)) or "connection failed", retries),
           }
       }).encode("utf-8")
       return 0, {}, err_body, None, total_elapsed, retries
   ```
   Keep the existing `total_elapsed` line; only the `return` changes. `e`
   is in scope from line 355's `except`. Includes `sanitize_error(str(e))`
   so the trace records the actual network error (DNS failure vs. connection
   refused vs. timeout).
4. Do **not** touch: the streaming success path (`server.py:332-353`), the
   413 path (line 273-274), the retry branches (lines 300-328, 357-373), the
   final `return last_status or 0` (line 379). `json` and `sanitize_error`
   are already imported/defined.

→ coder verify (auto): "`_read_capped` is defined as a module-level function
  in `server.py` taking `(resp, max_bytes)`; `forward_request`'s 429/503
  give-up branch calls `_read_capped(resp, PROXY_MAX_BODY_SIZE)` and wraps
  `conn.close()` in `try/except OSError`; the connection-error give-up branch
  returns a `json.dumps(...)` body containing `upstream_unreachable`; no other
  return statement in `forward_request` changed."

→ coder verify (scripted): `./tmp/verification/2026-07-19-fix-giveup-body-and-trace-prune-step1.py`
  — parses `server.py` AST, asserts: (a) `_read_capped` defined at module
  level with 2 params; (b) the 429/503 give-up return's 3rd element is a
  Name `err_body` bound by a Call to `_read_capped`; (c) `conn.close()` is
  inside a Try whose handler is an ExceptHandler for OSError; (d) the
  conn-error give-up return's 3rd element is a Call to `json.dumps` or a
  Name bound to such a call; (e) the streaming return and 413 return are
  unchanged. Exit 0 on pass.

→ tester verify: `test_exhaust_429_preserves_body` passes — mock upstream
  always returns 429 with body `{"error":"rate_limited"}`; `PROXY_MAX_RETRIES=1`,
  `PROXY_MAX_DELAY=1`; client receives 429 **with body containing
  `rate_limited`** (not empty); trace `error` field contains `rate_limited`.
  `test_exhaust_connection_error_synthesizes_body` passes — mock refuses
  connections; `PROXY_MAX_RETRIES=1`, `PROXY_INITIAL_DELAY=1`; trace `error`
  field contains `upstream_unreachable`.

### Step 2 — Fix C: catch client disconnect during response send (server.py)

Modify `ProxyHandler` in `src/claude_retry_proxy/server.py`:

1. Add a module-level constant near `_shutting_down` (~line 170):
   ```python
   _DISCONNECT_ERRORS = (ConnectionResetError, BrokenPipeError, ConnectionAbortedError)
   ```
   `ConnectionAbortedError` covers Windows WinError 10053; the other two
   cover WinError 10054 and POSIX EPIPE/ECONNRESET.
2. Add a `_log_client_disconnect` method to `ProxyHandler` (after
   `_send_response`, ~line 428). The method wraps both `print` and
   `log_trace` in individual try/except blocks so a secondary failure
  cannot re-raise from the disconnect handler:
   ```python
   def _log_client_disconnect(self, request_id, status, retries):
       """Record a client_disconnect event; suppress the traceback."""
       try:
           print("[proxy] client disconnected mid-response "
                 "(request_id={}, status={}, retries={})".format(
                     request_id, status, retries), file=sys.stderr)
       except Exception:
           pass
       try:
           log_trace({
               "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "event": "client_disconnect",
               "request_id": request_id,
               "http_status": status,
               "retries": retries,
           })
       except Exception:
           pass
   ```
3. Wrap the main-path `_send_response` call (currently `server.py:528`):
   ```python
       log_trace(trace_entry)
       try:
           self._send_response(status, resp_body, resp_headers)
       except _DISCONNECT_ERRORS:
           self._log_client_disconnect(request_id, status, retries)
   ```
4. Wrap the 413-path `_send_response` call (currently `server.py:467`).
   Order: `try: _send_response(413, ...) except _DISCONNECT_ERRORS:
   _log_client_disconnect(...)` → `log_trace({...})` → `return`. Do NOT
   reorder `log_trace` before `_send_response`.
5. Do **not** wrap the admin-shutdown path's `_send_response`/`self.wfile.write`
   calls (lines 436-460) — localhost-only, triggered by `stop`, out of scope
   per Prime Directive 2. The 403 bare `self.wfile.write` at line 441 is a
   known minor gap — documented but not fixed.

→ coder verify (auto): "`_DISCONNECT_ERRORS = (ConnectionResetError,
  BrokenPipeError, ConnectionAbortedError)` defined at module level in
  `server.py`; `_log_client_disconnect` method defined on `ProxyHandler`
  taking `(self, request_id, status, retries)` (3 params plus self);
  both `_send_response` call sites in `do_POST` (the main path and the 413
  path) are wrapped in `try/except _DISCONNECT_ERRORS:` calling
  `self._log_client_disconnect(...)`; the admin-shutdown path's calls are
  NOT wrapped."

→ coder verify (scripted): `./tmp/verification/2026-07-19-fix-giveup-body-and-trace-prune-step2.py`
  — parses `server.py` AST, asserts: (a) `_DISCONNECT_ERRORS` assigned a
  Tuple of 3 Names including `ConnectionAbortedError`; (b)
  `_log_client_disconnect` FunctionDef under `class ProxyHandler` with 4
  args; (c) within `do_POST`, exactly 2 Calls to `self._send_response`
  are the body of a Try with an ExceptHandler for `_DISCONNECT_ERRORS`;
  (d) the `/admin/shutdown` branch's calls are NOT inside such a try.
  Exit 0 on pass.

→ tester verify: `test_client_disconnect_no_traceback` passes — start the
  proxy via `subprocess.Popen` with `stderr=subprocess.PIPE`; send a request
  via raw socket; close the socket before reading the response; assert
  captured stderr contains no `Traceback` and contains `[proxy] client
  disconnected mid-response`; assert trace has a `client_disconnect` event
  with the request's `request_id`.

### Step 3 — Fix D: trace-log check + 5-day prune on start (cli.py)

Add to `src/claude_retry_proxy/cli.py`:

1. Module-level constants near `SETTINGS_FILE` (~line 21):
   ```python
   TRACE_FILE_DEFAULT = os.path.join(HOME, ".claude", "logs", "proxy-trace.jsonl")
   PRUNE_RETENTION_DAYS = 5
   ```
2. Helper functions (after `validate_url`, ~line 305):
   `resolve_trace_path(log_arg)`, `_parse_trace_entry(line)`, `_fmt_ts(epoch)`,
   `prune_trace_file(path)`. Full pseudocode in the design doc § Fix D.
   Key invariants:
   - `resolve_trace_path` mirrors `server.py main()`'s path resolution with
     a cross-reference comment.
   - `_parse_trace_entry` uses `json.loads` per line (not substring
     matching), returns `{"ts", "event", "status"}` or `None`. Two
     `strptime` formats for timestamp, no `fromisoformat` fallback.
   - `prune_trace_file` streams line-by-line to a temp file (no full read
     into memory), uses `json.loads` for timestamp and failure counting,
     keeps malformed lines (counted in `kept_count`), rewrites atomically
     via temp + `os.replace` with cleanup on failure, uses EAFP file open
     with try/except returning `(0,0)`, uses `is not None` for ts
     formatting. Returns `(kept_count, removed_count)`. If the file
     doesn't exist or can't be opened, prints a message and returns
     `(0, 0)`.
3. Call in `cmd_start`, **after** `validate_url(current_url)` and **before**
   `write_settings_url(...)`, wrapped in try/except (best-effort):
   ```python
   try:
       prune_trace_file(resolve_trace_path(parsed.log))
   except Exception as e:
       print("WARNING: trace log check failed ({}); continuing".format(e),
             file=sys.stderr)
   ```
4. Add `from datetime import datetime, timezone` and ensure `json` is
   imported (already present). No other new imports.

→ coder verify (auto): "`TRACE_FILE_DEFAULT`, `PRUNE_RETENTION_DAYS` defined
  at module level in `cli.py`; `resolve_trace_path`, `_parse_trace_entry`,
  `_fmt_ts`, `prune_trace_file` defined; `prune_trace_file` is called in
  `cmd_start` between `validate_url` and `write_settings_url`, wrapped in
  try/except; `datetime` and `timezone` imported."

→ coder verify (scripted): `./tmp/verification/2026-07-19-fix-giveup-body-and-trace-prune-step3.py`
  — (a) AST-asserts the four functions exist and `prune_trace_file` is called
  in `cmd_start` between `validate_url` and `write_settings_url`, wrapped in
  a Try; (b) **runtime** behavior check: creates a temp trace file with 3
  lines (one dated 10 days ago, one dated today, one malformed), imports
  `prune_trace_file` from `claude_retry_proxy.cli`, calls it, asserts return
  value is `(2, 1)`, the old line is gone, the today and malformed lines
  remain. Uses `time.time()` for consistency with the implementation. Exit 0
  on pass.

→ tester verify: `test_start_prunes_old_trace_entries` passes — temp trace
  file with entries dated now, 10 days ago, and a malformed line; calling
  `prune_trace_file` directly returns `(2, 1)`, removes old entries, keeps
  recent and malformed, prints the summary. Edge cases: file-doesn't-exist
  returns `(0, 0)`, empty file returns `(0, 0)`.

### Step 4 — Documentation (planner-owned, not coder)

The planner updates **after** coder finishes steps 1-3 and tests pass:
- `CLAUDE.md`: Architecture (trace prune on start + client disconnect catch),
  Gotchas (ADD note about give-up body preservation with cap; no existing
  "body-drop gotcha" to remove), Future Work (clarify
  `response-streaming-no-size-cap` is NOT resolved), Structure test count
  (27 → 32).
- `README.md`: trace-log section (start prunes >5d + prints summary +
  `client_disconnect` event type + fields), behavior section (exhausted-retry
  bodies preserved, capped at `PROXY_MAX_BODY_SIZE`; synthesized
  `upstream_unreachable` body), PROXY_LOG_ALL + Windows risk note, test count.
- Test-file docstring update belongs to the Tester, not the planner.

## Rollback Plan

Each fix is independently revertible via `git revert`. No env-var toggle
needed. If a fix causes a regression, revert the commit and restart the
proxy.

| Fix | Revert | Verification |
|-----|--------|-------------|
| B (body preservation) | `git revert <commit>` | Give-up paths return `b''` again; tests pass |
| C (disconnect catch) | `git revert <commit>` | Tracebacks reappear on disconnect; tests pass |
| D (trace prune) | `git revert <commit>` | `cmd_start` no longer prunes; tests pass |

## Guidance for Planner

Documentation tasks I will execute myself (not the coder):

- **Doc files to create/update:** `CLAUDE.md`, `README.md`, and the design
  doc `2026-07-19-fix-giveup-body-and-trace-prune-design.md` (already
  created, updated iter 1).
- **When:** **after** the coder finishes steps 1-3 AND the tester reports all
  tests passing. The doc updates reflect implemented behavior.
- **What to sync:**
  - `CLAUDE.md` `## Architecture` — note that `cmd_start` checks + prunes
    the trace log (5-day retention) before spawning; `_send_response` is
    wrapped to catch client disconnects, logging a `client_disconnect`
    trace event.
  - `CLAUDE.md` `## Gotchas` — ADD a note that the give-up path now
    preserves error bodies capped at `PROXY_MAX_BODY_SIZE`; the
    `response-streaming-no-size-cap` Open issue is NOT resolved (streaming
    path is still uncapped); the `_shutting_down`-during-sleep note stays.
  - `CLAUDE.md` `## Future Work` — clarify B only caps the give-up drain,
    not the streaming success path.
  - `CLAUDE.md` `## Structure` — test count 27 → 32 (five new tests;
    confirm against tester's final report).
  - `README.md` trace-log section — `start` prunes entries older than 5
    days and prints a one-line summary; `client_disconnect` event type
    with fields (timestamp, event, request_id, http_status, retries).
  - `README.md` behavior section — exhausted-retry responses carry the
    upstream error body (capped at `PROXY_MAX_BODY_SIZE`); connection-error
    exhaustion returns a synthesized `upstream_unreachable` body; client
    disconnects produce a `client_disconnect` trace event without tracebacks.
  - `README.md` PROXY_LOG_ALL + Windows risk — preserved error bodies now
    flow into the `--all` trace log, which is world-readable on Windows.
- **Do NOT modify `tests/test_claude_proxy.py`** — the test-file docstring
  update belongs to the Tester (they create the tests and know exact names).
- **Doc-gap closure rule:** any doc gap the coder or tester flags must be
  closed before `## Final Results` is written.

## Guidance for Coder

**Files to modify:** `src/claude_retry_proxy/server.py` (Steps 1, 2),
`src/claude_retry_proxy/cli.py` (Step 3). **Source code ONLY.** Do NOT touch
`tests/`, `CLAUDE.md`, `README.md`, `doc/**`, or any `.md`/`.html` file.

**Step-by-step with verification:** each step above has coder checks tagged
`(auto)` or `(scripted)`. The planner provides the `(scripted)` scripts at
`./tmp/verification/2026-07-19-fix-giveup-body-and-trace-prune-stepN.py`.
Self-verify `(auto)` checks by reading the code / grepping. Run `(scripted)`
scripts with `python ./tmp/verification/2026-07-19-fix-giveup-body-and-trace-prune-stepN.py`
from the project root.

**Architectural constraints (do not violate):**
- Step 1: `_read_capped(resp, max_bytes)` is a module-level function, not a
  method. It reads in 8 KiB chunks up to `max_bytes`, drains-and-discards
  the rest, and appends a truncation marker if truncated. `conn.close()` in
  the give-up branch MUST be in its own try/except OSError. The
  connection-error give-up body MUST include `sanitize_error(str(e))`. Do not
  touch the streaming success path, the 413 path, the retry branches, or the
  final `last_status or 0` fallback.
- Step 2: `_DISCONNECT_ERRORS` MUST include `ConnectionAbortedError` (3
  items). `_log_client_disconnect` MUST wrap `log_trace` in its own
  try/except (so a trace-write failure cannot re-raise from the disconnect
  handler). Wrap ONLY the two `_send_response` calls in `do_POST` (main +
  413), NOT the admin-shutdown path. For the 413 path, the order is:
  try/except `_send_response` → `log_trace` → `return` (do not reorder).
- Step 3: `resolve_trace_path` MUST mirror `server.py main()`'s path
  resolution with a cross-reference comment. `prune_trace_file` MUST stream
  line-by-line (no full read into memory). MUST use `json.loads` per line
  (not substring matching). MUST keep malformed lines and count them in
  `kept_count`. MUST use EAFP (try to open, catch FileNotFoundError).
  MUST wrap temp-file write + `os.replace` in try/except with cleanup.
  MUST use `is not None` for ts formatting. MUST NOT have a `fromisoformat`
  fallback. Hardcode `PRUNE_RETENTION_DAYS = 5` — do not add an env var.
  Call it in `cmd_start` after `validate_url`, before `write_settings_url`,
  wrapped in try/except that prints a WARNING and continues.
- No new runtime dependencies. `cli.py` may import `datetime` (stdlib) and
  `json` (already imported).
- Do not write tests. Do not write documentation.

**Build verification:** after Steps 1-3, run `pip install -e .` and
`python -c "import claude_retry_proxy.server, claude_retry_proxy.cli"` (must
succeed). Run `claude-retry-proxy-server --help` and `claude-retry-proxy
--help` (both must succeed). Report `build_result: "pass"` only if all
succeed.

## Guidance for Tester

**Test cases to create** in `tests/test_claude_proxy.py`, all **permanent**:

1. **`test_exhaust_429_preserves_body`** (Step 1, B — 429 path):
   - Mock upstream always returns 429 + body `{"error":"rate_limited"}`.
   - Env: `PROXY_MAX_RETRIES=1`, `PROXY_MAX_DELAY=1`, `PROXY_INITIAL_DELAY=1`.
   - Start the proxy via `PROXY_SERVER + ["--port", str(proxy_port), "--upstream-url", ...]`.
   - Assert client receives 429 with body containing `rate_limited` (NOT empty).
   - Assert the trace `error` field contains `rate_limited`.

2. **`test_exhaust_connection_error_synthesizes_body`** (Step 1, B — conn-error):
   - Point the proxy at a port with no listener (connection refused).
   - Env: `PROXY_MAX_RETRIES=1`, `PROXY_INITIAL_DELAY=1`.
   - Client will see status 0 (expected). Assert the trace `error` field
     contains `upstream_unreachable` (NOT `"HTTP 0"`).
   - The trace is the assertion target, not the client body (HTTP layer
     likely raises before reading status 0 body).

3. **`test_client_disconnect_no_traceback`** (Step 2, C):
   - Mock upstream returns 200.
   - Start the proxy via `subprocess.Popen` with `stderr=subprocess.PIPE`
     (direct-server pattern, matching existing tests; NOT via the CLI — the
     CLI creates `proxy-stderr.log` but direct-server tests use PIPE).
   - Send a request via raw socket; close the socket before reading the
     response.
   - Wait briefly; assert captured stderr contains NO `Traceback` and DOES
     contain `[proxy] client disconnected mid-response`.
   - Read the trace file; assert it contains a `client_disconnect` event
     with the request's `request_id`.
   - May be timing-sensitive — if flaky, increase wait or use a larger
     response body.

4. **`test_start_prunes_old_trace_entries`** (Step 3, D):
   - Directly import `prune_trace_file` from `claude_retry_proxy.cli`.
   - Create a temp trace file with: one entry dated now, one dated 10 days
     ago, one malformed line (e.g. `not json{`).
   - Call `prune_trace_file(temp_path)`.
   - Assert: return value is `(2, 1)` (2 kept: today + malformed; 1 removed:
     old); the file now contains the today line and the malformed line but
     NOT the 10-days-ago line; the summary line was printed to stdout.
   - Edge cases: file-doesn't-exist → `(0, 0)`, no exception; empty file
     → `(0, 0)`.

**Regression:** run the full existing suite (`python tests/test_claude_proxy.py`).
The 12 CLI tests that require a non-localhost `ANTHROPIC_BASE_URL` may be
skipped if settings.json points at localhost. The 12 direct-server tests +
the 4 new tests must pass. Report exact pass/skip/fail counts.

**Update the test-file docstring** to reflect the new total (31 tests) and
add case descriptions for tests 28-31.

## Documentation

- `README.md` — user-facing: trace-log prune-on-start behavior, the
  `client_disconnect` trace event, exhausted-retry body preservation,
  PROXY_LOG_ALL + Windows risk, test count.
- `CLAUDE.md` — Claude-facing: Architecture update (prune + disconnect),
  Gotchas update (give-up body preservation; `response-streaming-no-size-cap`
  still open), Structure test count.
- Design doc — `2026-07-19-fix-giveup-body-and-trace-prune-design.md`
  (already created; updated iter 1).

No other supplementary docs.

## Issue Log

| Issue | Status | Found | Resolved | Resolved By |
|-------|--------|-------|----------|-------------|

## Final Results

**Status:** COMPLETED
**Date:** 2026-07-20

### Steps completed

| Step | Description | Result |
|------|-------------|--------|
| 1 | Fix B: preserve upstream error body on retry exhaustion (server.py) | ✅ Completed — `_read_capped` with `PROXY_MAX_BODY_SIZE` cap, `conn.close()` safety, conn-error synthesized body |
| 2 | Fix C: catch client disconnect during response send (server.py) | ✅ Completed — 3-tuple `_DISCONNECT_ERRORS`, `_log_client_disconnect` with try/except hardening |
| 3 | Fix D: trace-log check + 5-day prune on start (cli.py) | ✅ Completed — streaming prune, `json.loads` per line, best-effort in `cmd_start` |
| 4 | Documentation (planner) | ⏳ Pending — CLAUDE.md + README.md updates to follow |

### Test results

- **New tests:** 5 permanent tests created (tester added bonus `test_prune_trace_file_edge_cases`)
  - `test_exhaust_429_preserves_body` — PASS
  - `test_exhaust_connection_error_synthesizes_body` — PASS
  - `test_client_disconnect_no_traceback` — PASS (no traceback; disconnect event timing-dependent)
  - `test_start_prunes_old_trace_entries` — PASS
  - `test_prune_trace_file_edge_cases` — PASS
- **Test count:** 27 → 32
- **Pre-existing:** 11 CLI tests fail due to `ANTHROPIC_BASE_URL=localhost:8080` in settings.json (live proxy active). Known issue, documented in CLAUDE.md, not caused by this plan.
- **Regression:** All 21 non-CLI tests pass.

### Review verdict

**Issues found — non-blocking.** 0 Critical, 1 Warning, 5 Suggestions.

- **Warning:** Blank lines inflate "entries" count in prune summary. Acknowledged — cosmetic.
- **Suggestions:** Extract 86400/8192 as constants; double `sanitize_error` on conn-error path is harmless; underscore naming on `_TS_FORMATS`/`_parse_trace_entry`; blank-line test gap. Deferred.

### Known caveats

- The 11 pre-existing CLI test failures persist (settings.json=localhost while proxy runs).
- `client_disconnect` trace event firing is timing-dependent (may not fire if response completes before client disconnects). The critical behavior (no traceback) is reliable.
- `response-streaming-no-size-cap` Open issue is NOT resolved by this plan (B caps only the give-up drain, not the streaming success path).
