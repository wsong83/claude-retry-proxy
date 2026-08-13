# Plan: Convert Proxy to Streaming Response Delivery
**Project:** D:\proj\claude-retry-proxy
**Plan ID:** 2026-08-12-streaming-proxy
**Created:** 2026-08-12

## Changelog
- **2026-08-12**: Initial plan
- **2026-08-12**: Revised after mega-audit iteration 1 — 8 High findings fixed: extended `_stream_upstream_response` signature (request_id/retries plumbing), replaced `if resp_body:` guard with explicit `streamed` flag, pinned header filter set, split upstream/client exception handling, added `IncompleteRead` catch, moved streaming call outside retry except scope, enumerated test-count doc updates
- **2026-08-12**: Added Step 5 — CR/LF header filtering (`_crlf_safe` helper) applied to both `_send_response` and the streaming path (user decision Q4, response-splitting hardening)
- **2026-08-13**: Fixed tester blocking issue [`stream-read-buffers-to-eof`](./tmp/reports/2026-08-12-streaming-proxy-stream-read-buffers-to-eof.json) — Plan Error: Step 1's `resp.read(8192)` cannot stream (`http.client` `read(amt)` fills amt bytes or EOF before returning). Read loop changed to `resp.read1(8192)` (at most one underlying socket read; returns data as it arrives; de-chunking preserved; available since Python 3.3 — verified empirically). Corrected the IncompleteRead claim in tester guidance (truncation: EOF branch on close-delimited, `IncompleteRead` on chunked `read1`); extended test 30 with a chunked mock variant; updated step1 verification script Check G to enforce `resp.read1(`.
- **2026-08-13**: Resolution confirmed — issue `stream-read-buffers-to-eof` **Resolved** ([resolution](./tmp/reports/2026-08-12-streaming-proxy-stream-read-buffers-to-eof.json), tester round 2: 14/14 pass; test 29 first byte 22ms while upstream still generating; test 30 covers both truncation modes). Coder applied the read1 fix, steps 2–5 re-verified unchanged, build pass.

## Introspection Log
*Auto-generated after significant plan revisions. See Phase 5 for the audit checklist.*

| Date | Trigger | Scope | Findings | Verdict |
|------|---------|-------|----------|---------|
| 2026-08-12 | Mega-audit (user-invoked, iteration 1) | Whole plan | 41 findings (8 High, 15 Medium, 18 Low). All 8 High fixed: (1) `_stream_upstream_response` signature extended to carry `request_id`/`retries` for `_log_client_disconnect`; (2) `if resp_body:` guard replaced with explicit `streamed` flag (empty-body error responses keep their status line); (3)+(4) streaming call placed outside retry except scope + outer `_DISCONNECT_ERRORS` handler swallows without re-raise (no retry after first byte); (5) `IncompleteRead`/upstream read errors caught in inner handler (no traceback on upstream truncation); (6) header filter pinned: exclude `{transfer-encoding, content-length, connection}`, forward `content-type` verbatim; (7) stale test counts enumerated for CLAUDE.md + README.md sync. Medium/Low findings folded into the same fixes (header filter, conn.close after streaming, total_sec from total_start, split try blocks, header-phase disconnect coverage, test overlap with Test 27, `--all` response_body omission documented, fall-through return acknowledged). Dismissed as false positive: "missing test functions" (tests are to-be-created tester work, not pre-existing references). Acknowledged Low: doc/*.* reference removed from Document Overrides; rollback via git revert (single-file change, no state migration) noted implicitly in completeness; trace-entry-on-shutdown ordering caveat accepted as pre-existing behavior. | All High fixed; <3 High remain — proceed |
| 2026-08-12 | User decision Q4 | CRLF header sanitization | Security-lens CR/LF response-splitting concern originally marked out-of-scope (pre-existing in `_send_response`); user chose to fix now. Step 5 added: `_crlf_safe()` helper applied to both header-forwarding surfaces. Test counts re-derived: 36 total (32 existing + 3 streaming + 1 CRLF unit), 24 direct-server/unit bucket. | In scope — proceed |
| 2026-08-13 | Tester session report (blocking issue `stream-read-buffers-to-eof`) | Step 1 read mechanism + tester guidance + step1 verification script | 14 plan-relevant tests: 13 passed, 1 failed (`test_streaming_response_body` — first byte arrived only after generation completed). Root cause: Plan Error — `http.client.HTTPResponse.read(amt)` fills amt-or-EOF, so the prescribed `resp.read(8192)` delivered bodies all-at-once-at-EOF for responses < 8192 bytes; coder implementation was faithful, the plan's mechanism was wrong (mega-audit shared the false assumption). Empirically re-verified on Python 3.14: `read(8192)` blocked 0.80s and returned everything at once; `read1(8192)` returned per-arrival on both close-delimited and chunked paths. Fix: Step 1 loop → `resp.read1(8192)`; chunked truncation raises `IncompleteRead` (inner catch live), close-delimited truncation stays on the EOF branch. Acknowledged non-blocking: Test-6 `proxy_stop` warning (pre-existing abrupt-termination harness quirk); coder's residual write-error edge (mega-audit accepted); coder's `streamed`-flag adaptation in do_POST (equivalent — handler is always self there). | Plan Error fixed in plan — await coder re-run + tester re-run |
| 2026-08-13 | Tester round-2 report + resolution (no open issues) | Whole plan — finalization | Tester re-ran after the read1 revision: **14/14** plan-relevant tests pass. `test_streaming_response_body` first byte 22ms (pre-fix: 269ms at EOF) — real-time streaming confirmed; test 30 covers both truncation paths (close-delimited EOF branch, chunked `IncompleteRead` inner-except). Coder re-run: read1 applied, build pass, steps 2–5 re-verified unchanged, no new issues. Non-blocking warnings acknowledged: Test-6 `proxy_stop` (pre-existing abrupt-termination harness quirk); 12 CLI URL-swap tests excluded from execution scope (live `~/.claude/settings.json` backs this session — untouched by this plan, per project CLAUDE.md warning). | Ready for Phase 6 final review |
| 2026-08-13 | Phase 6 reviewer subagent | Full implementation diff (server.py + tests) | Verdict: **Issues found — non-blocking** (0 Critical, 2 Warning, 4 Suggestion). Warnings acknowledged (see Final Results Known Caveats): (1) truncated streams traced as success — mid-stream truncation traces `status: success, error: None`, overcounting success rates in `analyze_proxy_trace.py` (deferred to future hardening); (2) client-write OSError outside `_DISCONNECT_ERRORS` can escape into `forward_request`'s retry except after headers sent (accepted residual, now documented in CLAUDE.md Gotchas). Suggestions deferred: Test 29 doesn't assert forwarded `Content-Type: text/event-stream`; Test 27 phase 1 now exercises the streaming path, leaving `_send_response`'s buffered-path disconnect handler uncovered; `streamed` flag duplicates the streaming-branch condition across do_POST/forward_request; streamed-path `client_disconnect` trace event can precede the request entry. Verified sound: retry-safety invariant end-to-end, header filtering + `_crlf_safe`, read1 mechanism, thread safety, Python 3.8+ compatibility. | Gate passed — proceed to Final Results |

## Audit Accumulation

*Counters reset when mega-audit runs. Used by Phase 5 entry trigger.*

| Counter | Value | Last Updated |
|---------|-------|--------------|
| issues_resolved_since_audit | 1 | 2026-08-13 (stream-read-buffers-to-eof → Resolved) |
| steps_changed_since_audit | 1 | 2026-08-13 (Step 1 read mechanism revised) |
| files_changed_since_audit | 0 | 2026-08-12 (reset after mega-audit iteration 1) |

## Summary

**Problem:** `forward_request()` buffers the entire upstream response body in memory
before returning it to `do_POST()`, which then writes it to the client in one shot.
For long streaming generations (Claude API with `stream: true`), the client receives
zero bytes for the entire generation duration — causing Claude Code's HTTP client to
time out and report "API Error: Connection lost mid-response."

**Fix:** Stream response body chunks from upstream to the client as they arrive,
writing HTTP status and headers immediately once the upstream responds with a
non-retryable **2xx** status. Non-2xx upstream responses (other than 429/503,
which are retried) stay on the buffered path so upstream error bodies remain
available for trace logging. Retry logic is unchanged — 429/503 retries and
connection-establishment retries happen *before* any data reaches the client;
once the first byte is delivered, mid-stream failures abort the stream (never
retry).

**Architecture:**

```
Before (buffered):
  do_POST → forward_request [buffers ALL chunks into list] → _send_response [one big write]
  Client sees: [entire generation duration of silence] → sudden burst of all data

After (streaming):
  do_POST → forward_request [retry loop] → handler._stream_upstream_response()
    → send_response(status) + send_header(...) + end_headers()   [headers sent immediately]
    → while chunk = resp.read1(8192): wfile.write(chunk); wfile.flush()  [streamed in real time]
  Client sees: headers arrive instantly, then SSE events arrive as generated
```

**Key design decisions:**
- Stream **2xx** responses only. Non-2xx upstream responses stay buffered so their
  error bodies remain in the trace. 429/503 retry before streaming; retries never
  occur after the first byte reaches the client.
- Flush after each `resp.read1(8192)` return. `read1` does at most one underlying
  socket read and returns as soon as data arrives (up to 8192 bytes, de-chunking
  preserved). `resp.read(8192)` is NOT usable here: `http.client`'s `read(amt)`
  fills amt bytes or EOF before returning, so bodies < 8192 bytes would still
  arrive all-at-once-at-EOF (the original buffering defect). Header bytes ride
  the first chunk's flush, so first-byte timing is measured on the first chunk
  write, matching what the client actually sees.
- Mid-stream upstream connection drop → client connection closes (no recovery
  possible — data was already sent to client). Upstream read errors (`IncompleteRead`,
  `RemoteDisconnected`, `socket.error`) are caught inside `_stream_upstream_response`
  and never propagate into the retry loop.
- Client-side write errors (`_DISCONNECT_ERRORS`) are caught by an outer handler
  that logs `client_disconnect` and returns — never re-raised, never retried.
- Pass the `ProxyHandler` instance (`self`) plus `request_id` to `forward_request`
  so the streaming method can log disconnect events with matching request_id.
- Keep `_send_response()` for error paths (400, 413, 429/503 exhausted, non-2xx) —
  those bodies are short and already buffered. `do_POST` discriminates via an
  explicit `streamed` flag (`handler is not None and 200 <= status < 300`), never
  body truthiness.
- Response size cap (`response-streaming-no-size-cap`) is **out of scope** — tracked
  as a pre-existing known issue in CLAUDE.md. The streaming read loop structure makes
  adding a cap straightforward in a follow-up, but this plan targets the
  connection-lost-during-generation defect only.
- CR/LF header hardening **in scope** (Step 5): `_crlf_safe()` skips any response
  header whose name or value contains `\r`/`\n`, applied to both the streaming path
  and `_send_response`. Guarantees the client's parser sees exactly the header set
  the proxy parsed (parser-differential response-splitting guard; cf.
  CVE-2019-9740/CVE-2019-9947 family).

**Alternatives considered:**
- **Chunked Transfer-Encoding:** Rejected — `http.server` doesn't natively support
  it; implementing it manually adds complexity without benefit for a localhost proxy.
  HTTP/1.0-style connection-close termination works identically over loopback.
- **Dual-path (keep buffering + add streaming):** Rejected — adds branching
  complexity. Replace buffering entirely for the success path; no caller needs the
  old behavior.

## Repo Mode

Public

## Document Overrides

*None — this plan follows all documented rules in CLAUDE.md.*

## Proposed Changes

1. **Step 1:** Add `_stream_upstream_response()` method to `ProxyHandler` in `server.py`
   → coder verify (auto): `_stream_upstream_response` is defined on `ProxyHandler`, accepts `(self, resp, status, resp_headers, request_id, retries)`, returns `first_byte_ms` (float or None). Method calls `self.send_response(status)`, then iterates `resp_headers` and forwards them via `self.send_header()` after filtering: **exclude** `transfer-encoding`, `content-length`, and `connection` (hop-by-hop headers — http.client already de-chunked the upstream body; the response is close-delimited via HTTP/1.0). **Forward** all other headers verbatim including `content-type` (required for `text/event-stream` SSE responses). Additionally pass `resp_headers` through the new module-level helper `_crlf_safe()` (defined in this step) which skips any header whose name or value contains `\r` or `\n` — guarantees the client's parser sees exactly the header set the proxy parsed (parser-differential response-splitting guard; cf. CVE-2019-9740/CVE-2019-9947 family). Calls `self.end_headers()`. The **entire method body** (header writes + body loop) is wrapped in a single outer `try/except _DISCONNECT_ERRORS` that calls `self._log_client_disconnect(request_id, status, retries)` and returns `None` (does NOT re-raise). Inside that outer try, the body loop reads via `resp.read1(8192)` in a `while True` loop — `read1` performs **at most one underlying socket read** and returns data as soon as it arrives (up to 8192 bytes), with chunked de-framing preserved. (`resp.read(8192)` is NOT acceptable: `http.client`'s `read(amt)` fills amt bytes or EOF before returning, so responses under 8192 bytes would still be delivered all-at-once-at-EOF — the original buffering defect; tester issue `stream-read-buffers-to-eof`.) Each returned chunk is written to `self.wfile` followed by `self.wfile.flush()`. Upstream-side read errors (`http.client.IncompleteRead`, `http.client.RemoteDisconnected`, `socket.error`, `OSError`) are caught in a **separate inner try/except** around `resp.read1()` only — on upstream failure, break the loop and return `first_byte_ms`. Truncation detection is dual-path: a chunked upstream body truncated mid-chunk makes `read1` raise `IncompleteRead` (caught by the inner handler); a close-delimited body truncated early surfaces as a clean `b''` EOF and the `if not chunk: break` branch ends the loop — both signal truncation to the client via connection close. First-byte timing is measured on the first successful chunk write+flush (not the first read — that overstates client-visible TTFB; headers are buffered until the first chunk flush pushes them). After the loop, `conn.close()` is NOT called here — the caller owns the connection lifecycle.
   → coder verify (scripted): verify method signature with 6 params, flush call presence, split try/except (inner for upstream reads, outer for client writes), IncompleteRead caught, header exclusion set `{transfer-encoding, content-length, connection}`, content-type forwarded, and `end_headers` call — script at `./tmp/verification/2026-08-12-streaming-proxy-step1.py`
   → tester verify: streaming response body content matches upstream (test sends request to proxy → mock upstream streams chunks with delays → client receives all chunks in order)

2. **Step 2:** Modify `forward_request()` to accept `handler=None, request_id=None` and stream on non-retryable 2xx responses
   → coder verify (auto): `forward_request` signature is `(method, path, headers, body, handler=None, request_id=None)`. On non-retryable **2xx** response with `handler` provided: the existing buffered read loop at lines 384-404 is replaced with a call to `handler._stream_upstream_response(resp, resp.status, dict(resp.getheaders()), request_id, retries)`. This call is placed **outside** the retry `try/except (socket.error, ConnectionError, OSError)` block — inside the `try` body but after the read-loop position, so connection-establishment errors still retry but mid-stream failures do not (headers were already sent to client). After `_stream_upstream_response` returns, `conn.close()` is called (the caller owns connection lifecycle), and `forward_request` returns `(resp.status, dict(resp.getheaders()), b"", first_byte_ms, time.time() - total_start, retries)` — `total_sec` is computed from `total_start` (set before the retry loop) so it includes retry backoff time, preserving the field's existing semantics. Non-2xx responses (including upstream 4xx/5xx that aren't 429/503) stay on the buffered path to preserve upstream error body in trace logging. When `handler` is None, the existing buffering behavior for 2xx is unchanged. With `handler=None` (or on error paths), the existing buffering / error-return behavior is unchanged. All 5 existing error return paths (400 method, 400 path, 413 size, 429/503 exhaust, connection exhaust) are untouched. The fall-through return at line 437 `(last_status or 0, {}, b'', None, total_elapsed, retries)` is also untouched.
   → coder verify (scripted): verify all 5 error return paths unchanged, verify success path branches on `handler is not None and 200 <= resp.status < 300`, verify body is `b""` when handler is used, verify `conn.close()` is called after streaming, verify `total_sec = time.time() - total_start` includes retry time — script at `./tmp/verification/2026-08-12-streaming-proxy-step2.py`
   → tester verify: existing retry tests (5, 5c, 5d, 25, 26) pass unchanged — retry logic unaffected

3. **Step 3:** Update `do_POST()` to pass `handler=self, request_id=request_id` and handle streamed-vs-buffered response
   → coder verify (auto): `do_POST` line calling `forward_request` passes `handler=self, request_id=request_id` as keyword arguments. After `forward_request` returns, the response is sent to the client via `_send_response` **only when the response was NOT streamed**. Discrimination uses an explicit boolean, not body truthiness: `streamed = (handler is not None and 200 <= status < 300)`. When `streamed` is True, skip `_send_response` (headers+body already delivered by `_stream_upstream_response`). When `streamed` is False (error paths, empty-body exhaust, non-2xx buffered responses), call `_send_response(status, resp_body, resp_headers)` as before — this preserves the existing behavior where empty-body error responses still receive a proper HTTP status line and `Content-Length: 0`. Trace entry is built and logged after `forward_request` returns, same as before. The `try/except _DISCONNECT_ERRORS` around `_send_response` is preserved for the error path.
   → coder verify (scripted): verify `handler=self, request_id=request_id` are passed, verify the `streamed` flag discriminates on `handler is not None and 200 <= status < 300`, verify `_send_response` is called only when `not streamed`, verify trace entry is logged in both paths — script at `./tmp/verification/2026-08-12-streaming-proxy-step3.py`
   → tester verify: `test_concurrent_requests` passes (10 parallel requests all return 200 with correct body). `test_thread_safety` passes (20 requests, 20 trace entries, no corruption). New regression test: upstream returns 429 with empty body until exhaustion → client receives proper HTTP 429 status line (not connection close).

4. **Step 4:** Update trace logging in `do_POST()` for the streaming response path
   → coder verify (auto): trace `error` field is `None` when status is 2xx (success path). `--all` body logging: when `streamed` is True (2xx, handler consumed the response), `response_body` is **omitted** from the trace entry — streamed response bodies are not captured (this is a deliberate reduction in data-at-rest exposure; noted in documentation). `request_body` is still logged when `PROXY_LOG_ALL` is true regardless of streaming path. `total_latency_sec` and `first_byte_latency_ms` are populated from `forward_request` return values — same fields, same types; `total_sec` includes retry backoff time (computed from `total_start` in `forward_request`). For non-2xx responses (buffered path), the existing trace body-logging behavior is unchanged.
   → coder verify (scripted): verify trace entry shape for streaming vs error paths, verify `--all` flag behavior with streamed response, verify `error` is `None` for 2xx — script at `./tmp/verification/2026-08-12-streaming-proxy-step4.py`
   → tester verify: trace markers test (Test 6) passes — start marker, request events, stop marker with counters all present

5. **Step 5:** Add `_crlf_safe()` helper and apply it to `_send_response()` in `server.py`
   → coder verify (auto): module-level function `_crlf_safe(headers)` is defined near `_send_response`, returns a dict omitting any entry whose name or value contains `\r` or `\n`; handles `None`/empty input by returning `{}` (or the call site keeps the existing `if headers:` guard — either is acceptable, both are checked). `_send_response`'s header loop (lines 478-482) now iterates `_crlf_safe(headers).items()` (or applies the equivalent inline check) so the buffered path gets the same guard as the streaming path — the existing skip-set `{content-type, transfer-encoding, content-length, connection}` behavior is unchanged. Signature stays `(self, status, body_bytes, headers=None)`.
   → coder verify (scripted): verify `_crlf_safe` is defined, verify `_send_response` uses it (or contains the equivalent CR/LF check), verify the existing skip-set filter still present, verify no CR/LF check leaks into header *values* written for `Content-Type`/`Content-Length` constants — script at `./tmp/verification/2026-08-12-streaming-proxy-step5.py`
   → tester verify: unit test `test_crlf_header_filter` — `_crlf_safe({"X-Ok": "fine"})` keeps the entry; `_crlf_safe({"X-Bad": "a\r\nSet-Cookie: injected=1"})` omits it; name with `\n` omitted; `None` → `{}`; mixed dict keeps only clean entries. Behavioral test via mock upstream is NOT feasible — modern `http.client` parses raw CR/LF header lines into separate clean headers before the proxy sees them (parser differential is the whole point of the guard), so the unit test is the authoritative check.

## Guidance for Planner

- **Doc files to create/update:** `CLAUDE.md`, `README.md`.
- **When:** after coder and tester finish
- **What to sync:**
  - `CLAUDE.md` Structure section (line 25): change "32 behavioral tests" to "36" and append "+4 for streaming delivery + CRLF hardening" to the parenthetical breakdown. Also correct the stale "12 of the 24 tests" → "12 of the 36 tests" and "the 12 direct-server tests" → "the 24 direct-server/unit tests" (pre-existing drift — fix while touching the file).
  - `CLAUDE.md` Gotchas section: remove the buffering-on-success description; add a note that the success path now streams response chunks to the client in real time.
  - `CLAUDE.md` `response-streaming-no-size-cap` Future Work entry: update the Location field to reference `_stream_upstream_response` (the new streaming method) instead of the old `forward_request` read loop.
  - `CLAUDE.md` `--all` / `PROXY_LOG_ALL` gotcha: note that streamed success response bodies are no longer captured in the trace (reduction in data-at-rest exposure).
  - `README.md` Testing section (line 250): change "The suite has 32 tests" to "36" and "20 tests start the server directly" to "24" (the 4 new tests: 3 server-side streaming + 1 in-process CRLF unit test).

## Guidance for Coder

**Files to modify:** `src/claude_retry_proxy/server.py`

**Step-by-step with verification:** each step above has coder checks tagged `(auto)` or `(scripted)`. The coder self-verifies `(auto)` checks and runs the provided script for `(scripted)` checks. Tester owns the behavioral checks.

**Do not:**
- Do not change the retry logic (429/503 backoff, jitter, exhaustion handling)
- Do not change the trace log field names or top-level keys — the only allowed change is omitting `response_body` from streamed success entries under `PROXY_LOG_ALL` (Step 4)
- Do not change the `_send_response` method signature — Step 5 modifies only its header loop to apply the CR/LF filter
- Do not change `do_OPTIONS` or the `/admin/shutdown` handler
- Do not change `extract_model`, `sanitize_error`, `log_trace`, or any thread-safety primitives
- Do not add new environment variables or CLI flags
- Do not add a response size cap — that is out of scope for this plan
- Do not place the `_stream_upstream_response` call inside the retry `except` scope — mid-stream failures must never trigger a retry

## Guidance for Tester

**Tests to create:**
- **Permanent:** `test_streaming_response_body` — mock upstream streams 5 chunks with 50ms delays between them; proxy forwards to client; client reads chunks incrementally and verifies: (a) first byte arrives within 1 second (TTFB << total generation time), (b) all 5 chunks received in order, (c) concatenated body matches upstream, (d) HTTP status is 200. Uses `_send_proxy_request`-style helper but reads response in chunks instead of `resp.read()` all at once.
- **Permanent:** `test_streaming_mid_stream_upstream_failure` — mock upstream sends 2 chunks then closes connection abruptly. Run **two mock modes**: (a) **close-delimited** with a Content-Length larger than the bytes actually sent — truncation surfaces as a clean `b''` EOF from `read1` and is detected via the `if not chunk: break` branch (note: `read(amt)`/`read1(amt)` return `b''` on short read; only bare `read()` raises `IncompleteRead`); (b) **chunked** (`Transfer-Encoding: chunked`) with the connection dropped mid-chunk — `read1` raises `http.client.IncompleteRead`, exercising the inner except. Proxy forwards 2 chunks to client then closes; client receives 2 chunks then gets truncated response (connection close). Verify no traceback in proxy stderr AND that no `client_disconnect` trace event is logged (upstream failure must not be misattributed as a client disconnect).
- **Permanent:** `test_empty_body_429_exhaust` — mock upstream returns 429 with `Content-Length: 0` (empty body) through all retries; client must receive a proper HTTP 429 status line (not a bare connection close). Regression guard for the `streamed` flag discrimination in Step 3.
- **Permanent:** `test_crlf_header_filter` — in-process unit test of `_crlf_safe` (import from `claude_retry_proxy.server`, no subprocess): clean headers pass through; header value containing `\r\n` is omitted; header name containing `\n` is omitted; `None` input returns `{}`; mixed dict keeps only clean entries. Behavioral testing via mock upstream is infeasible (modern `http.client` parses raw CR/LF lines into separate clean headers before the proxy sees them) — the unit test is authoritative.
- **Temporary:** None

**Tests to extend:**
- Extend `test_client_disconnect_no_traceback` (Test 27) instead of adding a new `test_streaming_client_disconnect`: add a phase where the client reads headers then closes mid-stream (the streaming-path disconnect scenario). Test 27 already asserts no traceback + `client_disconnect` trace event with matching request_id; the new phase reuses those assertions. This avoids duplicating the disconnect-coverage assertions in a parallel test.

**Tests to investigate for retirement:**
- Planner candidates: None — no tests are directly tied to the buffering behavior being changed. All existing tests should continue to pass because they either mock at the HTTP level (where buffering vs streaming is invisible to the client) or test retry/error paths (which are unchanged).
- Tester may identify additional candidates during test work.

**Retirement procedure:** For each candidate, verify the test exercises code being removed/changed. If obsolete: delete and note in session report. If still valid: document why in session report.

**Existing tests that must still pass:** All 32 existing tests (1–28b). Key regression risks:
- Test 4 (concurrent requests) — streaming must be thread-safe
- Test 5/5c/5d (retry logic, 429) — retry path unchanged
- Test 6 (trace markers) — trace events still present and correctly shaped
- Test 9 (thread safety) — 20 concurrent requests, trace entries intact
- Test 25 (exhaust 429 preserves body) — give-up path unchanged
- Test 26 (exhaust connection error) — give-up path unchanged
- Test 27 (client disconnect no traceback) — disconnect handling intact (and extended per above)

## Documentation

- `CLAUDE.md` — Structure test count (32 → 36, plus stale 12/24 → 12/36 and 12 → 24 direct-server/unit corrections); Gotchas streaming note; `response-streaming-no-size-cap` entry Location update; `--all` data-exposure note. Details in Guidance for Planner.
- `README.md` — Testing section test counts (32 → 36, 20 → 24). Details in Guidance for Planner.

## Issue Log

| Issue | Status | Found | Resolved | Resolved By |
|-------|--------|-------|----------|-------------|
| [stream-read-buffers-to-eof](./tmp/reports/2026-08-12-streaming-proxy-stream-read-buffers-to-eof.json) | Resolved | 2026-08-13 | 2026-08-13 | [tester](./tmp/reports/2026-08-12-streaming-proxy-stream-read-buffers-to-eof.json) |

## Final Results

- **Completion date:** 2026-08-13
- **Status:** COMPLETED
- **Files changed:** `src/claude_retry_proxy/server.py` (coder), `tests/test_claude_proxy.py` (tester), `CLAUDE.md` + `README.md` (planner doc sync)
- **Test results:** tester round 2 — **14/14** plan-relevant tests pass (4 new permanent tests: streaming response body, mid-stream upstream failure [2 modes], empty-body 429 exhaust, CRLF header filter; extended Test 27 client-disconnect; regression risks 4/5/5c/5d/6/9/25/26 green). Round 1 caught a Plan Error (`resp.read(8192)` buffers to EOF — no streaming); fixed via the `resp.read1(8192)` revision and re-verified. Test 29 confirms real-time delivery: first byte 22ms while the upstream is still generating. 12 CLI URL-swap tests excluded from execution scope (live settings.json — untouched by this plan).
- **Review verdict:** Issues found — non-blocking. 0 Critical, 2 Warning, 4 Suggestion (report: [`2026-08-12-streaming-proxy-review-2026-08-13.json`](./tmp/reports/2026-08-12-streaming-proxy-review-2026-08-13.json)).
- **Known caveats (reviewer Warnings, acknowledged non-blocking):**
  1. **Truncated streams traced as success** — a mid-stream upstream truncation is traced `status: success, error: None`, indistinguishable from a complete stream in `analyze_proxy_trace.py`. Deferred to a future hardening plan (trace truncation marker).
  2. **Client-write OSError outside `_DISCONNECT_ERRORS` can escape into the retry loop** — rare non-disconnect socket errors (e.g., WSAENOBUFS/WSAENOTSOCK/ENOTCONN) on a client write after headers were sent could re-issue the upstream POST. Accepted residual (mega-audit accepted, coder documented); now noted in CLAUDE.md Gotchas.
- **Issues resolved:** `stream-read-buffers-to-eof` — Resolved by tester, 2026-08-13.
