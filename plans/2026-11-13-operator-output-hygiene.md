# Plan: Operator-output hygiene — analyzer escape, response headers, trace model cap
**Plan ID:** 2026-11-13-operator-output-hygiene
**Created:** 2026-11-13

<!-- ## Immediate Actions: absent from initial plans. Populated by /update-plan for revised plans, replaced (not accumulated) on each revision. Contains per-role action-only directives (no rationale) telling agents what to do next. Agents read the full plan for context. -->

## Issue Log

Rows ordered newest-first (latest issues at top). New issues are prepended; resolved issues stay in place with updated status.

| Issue | Status | Found | Resolved | Resolved By |
|-------|--------|-------|----------|-------------|
| [analyze-trace-model-terminal-escape](./tmp/reports/defer-issue-analyze-trace-model-terminal-escape.json) | Resolved | 2026-10-21 | 2026-11-13 | tester |
| [proxy-own-server-date-headers](./tmp/reports/defer-issue-proxy-own-server-date-headers.json) | Resolved | 2026-10-21 | 2026-11-13 | tester |

Both rows are adoptions: this plan implements the deferred reports' fixes, and
each row is the retirement trigger for its report.

## Guidance for Coder

**Files to modify:** `scripts/analyze_proxy_trace.py`, `src/claude_retry_proxy/server.py`.

**Constraints:**
- `src/claude_retry_proxy/server.py`: only the three edits below (override, two skip-set entries, model cap). Do not change `_send_response`'s or `_stream_upstream_response`'s structure beyond the skip-set entries; do not touch any other response path.
- The upstream `Server` header must remain forwarded verbatim — `Server: cloudflare` is a load-bearing diagnostic (the Cloudflare `1010` investigation; see the opencode UA-block memory). Nothing here may filter, rewrite, or drop it.
- Do not write or modify tests (tester's lane) or documentation (planner's lane).

**Step-by-step with verification:** each step carries `(auto)` checks (grep/read, self-verify) and a `(scripted)` gate run at the end of the source group. Behavioral checks belong to the tester.

**Verification scripts** (planner-authored, both proven before launch):
`./tmp/verification/2026-11-13-operator-output-hygiene-structure.py` is the structure gate — RED on the pre-change tree (every post-change check FAIL, exit 1) and full PASS on copies carrying exactly this plan's literal edits. Its satisfiability was proven by `./tmp/verification/2026-11-13-operator-output-hygiene-teeth-probe.py`, which also byte-verifies that each plan edit anchor occurs exactly once in the pristine source (exit 0, 2026-11-13). The coder runs the **structure gate** per Steps 1–4; the teeth probe is the planner's pre-implementation evidence and is **not** re-run after the edits (its old-block anchors are consumed by the edits by design).

## Guidance for Tester

**Files to modify:** `tests/test_response_headers.py` (new), `tests/test_claude_proxy.py` (aggregator registration), and — for the analyzer/cap tests — whichever module fits the suite's layout best (`tests/test_response_headers.py` can carry all of it; see Step 6).

**Operational discipline:** every command that spawns a proxy or runs a test module carries an explicit `timeout`. Step 5 carries one complete reference body (`test_response_headers_buffered`) — the remaining tests are specified by their listed assertions (semantics fixed, structure free); adapt registration names, not semantics.

**Tests to create:**
- **Permanent** (all in `tests/test_response_headers.py`, registered in the aggregator):
  - `response-headers-buffered-single-date-no-self-server` — a buffered proxied response carries exactly one `Date`, exactly one `Server` (the upstream's, verbatim), and no `BaseHTTP`/`Python` disclosure.
  - `response-headers-streamed-single-date-no-self-server` — same contract on a streamed SSE response.
  - `response-headers-proxy-generated-no-server-one-date` — a proxy-generated 400 (unknown model) carries exactly one `Date` and NO `Server` at all.
  - `response-headers-options-one-date-no-server` — the OPTIONS preflight carries exactly one `Date` and no `Server`.
  - `response-headers-upstream-no-date` — an upstream that sends no `Date` still yields exactly one `Date` (the proxy's own) on the buffered path.
  - `trace-model-field-capped` — rejected requests' client model strings are capped at 512 with the visible marker: 512 chars unchanged, 513/600 truncated head-kept.
  - `analyzer-model-escape` — the analyzer renders a control-character and lone-surrogate model name with escaped forms, exits 0, and emits no raw ESC byte.

**Tests to investigate for retirement:**
- Planner candidates: **none.** No existing test asserts on `Server`/`Date` headers (grepped `BaseHTTP`, `getheader("Server"`, `'Server'` across `tests/` — zero behavioral matches) and no existing test covers the analyzer or the trace `model` field's length. No test obsolescence identified.
- Tester may identify additional candidates during test work.

**Retirement procedure:** For each candidate, verify the test exercises code being removed/changed. If obsolete: delete and note in session report. If still valid: document why in session report.

## Summary

Two deferred operator-facing defects, both filed 2026-10-21, plus the field-bound decision the first deferral left open (user-approved 2026-11-13):

1. **Terminal escape injection** (`analyze-trace-model-terminal-escape`): `scripts/analyze_proxy_trace.py` prints the trace entry's `model` field — on pre-routing 400s the raw client-supplied string — into the operator's terminal unescaped. A crafted `"\x1b]0;pwned\x07"` model name is replayed verbatim by `analyze_proxy_trace.py --days N`. Fix: a `_term_safe()` helper that escapes terminal-hostile characters only (C0, DEL, C1 → `\xNN`; lone UTF-16 surrogates → `\uNNNN` — a client-reachable `"\ud800"` model survives the json round-trip and crashes `print()` on a strict-UTF-8 stdout otherwise), applied at the single client-derived print site (line 284). Legitimate names — including non-ASCII — stay byte-identical; whole-string `repr()` was rejected as over-broad.

2. **Duplicate `Server`/`Date` + version disclosure** (`proxy-own-server-date-headers`): `ProxyHandler` inherits `BaseHTTPRequestHandler.send_response`, which auto-emits `Server: BaseHTTP/0.6 Python/<ver>` and `Date` before the handler's headers; the two upstream-forwarding loops then forward the upstream's own pair on top. Fix: one override — `send_response` becomes `log_request` + `send_response_only` + an explicit single `Date` — and both forwarding loops add `"date"` to their skip sets. Net per response: exactly one `Date`, zero proxy `Server`, and on the two forwarding loops the upstream `Server` forwarded verbatim (the `cloudflare` diagnostic survives). The 429/503 give-up path passes an empty headers dict downstream (pre-existing shape), so it delivers the upstream error body under proxy-generated headers — one `Date`, no `Server` — which is exactly the deferral's no-disclosure intent; upstream-identity forwarding is a forwarding-loop property, not a give-up one. Proxy-generated responses (admin surface, OPTIONS, errors) gain the one-Date/no-Server contract automatically through the override. The Date design substitutes the proxy's own Date for the upstream's (whose value is not diagnostically load-bearing) — this satisfies the deferral's expected behavior ("exactly one Date … discloses nothing") with two skip-set entries instead of per-path Date logic at ~12 response sites.

3. **Trace `model` field cap** (the deferral's open decision, user-approved): `"model": actual_model or model or "unknown"` (server.py:4112) writes unbounded client text into the JSONL trace. Mirroring the User-Agent precedent (`CLIENT_USER_AGENT_MAX_CHARS = 512` + marker + helper): `TRACE_MODEL_MAX_CHARS = 512` with `[proxy: model truncated]`, head-kept. Bounds the field at rest; the body-size cap already bounds the input, this bounds the record.

```
client ──POST──▶ proxy ──▶ upstream
                │              │
   every response: override sends Date once, never Server;
   forwarding loops drop upstream "date", pass upstream Server verbatim
   trace entry: model = _trace_model(actual, raw)  ← 512-cap + marker
   analyzer: print(_term_safe(model))              ← control chars + surrogates escaped
```

Alternatives rejected: whole-string `repr()` escaping (mangles legitimate non-ASCII); per-path "emit Date only if upstream sent none" (~12 sites, error-prone); dropping the upstream `Server` (destroys the `cloudflare` evidence); capping the model field inside the analyzer only (leaves the unbounded at-rest record).

Out of scope: the remaining deferral `drop-redacted-thinking-chat-placeholder`; any change to `client_user_agent`/`extra_request_headers` trace fields; the mock-upstream harness (Plan A, done).

## Repo Mode

Public

*Detected at plan creation. Determines: plan archival path, commit-message content, staged files.*

## Document Overrides

If the plan intentionally contradicts a documented rule (in `CLAUDE.md` or `doc/*`), declare the override here. An empty or absent table means zero tolerance — every documented rule is in force.

| Document | Rule Overridden | Reason |
|----------|----------------|--------|

## Risks

| Risk | Impact | Mitigation |
|---|---|---|
| The `send_response` override changes every response path at once | A mistake breaks all responses | The override is exactly three calls (`log_request`, `send_response_only`, `send_header("Date")`) mirroring the stdlib's own two-plus-logging shape; the full suite exercises every response path; the header-contract tests pin buffered, streamed, proxy-generated, and OPTIONS shapes. |
| Overriding `send_response` interacts with `send_response_only`'s HTTP/0.9 guard | None expected — the proxy only speaks HTTP/1.x | `send_response_only` is the stdlib's own guarded writer; calling it directly is the documented idiom for suppressing default headers. |
| Dropping the upstream `Date` (substituting the proxy's) changes a header some client reads | Negligible — Date's value is not load-bearing for proxy clients; it is not used for caching decisions here | The contract "exactly one Date" is what the deferral demands; whose value it carries is unspecified there. |
| Model cap changes the trace field's content for >512-char names | Only affects names over 512 chars (no legitimate model name observed is near it) | Head-kept + visible marker, exactly like the User-Agent cap; the raw body is still bounded by `PROXY_MAX_BODY_SIZE`. |
| **Rollback.** A client turns out to depend on the upstream `Date` value, or an escalation surfaces post-deploy | Wire-visible header substitution on every response | The change is code-only — no config, state, or data migration — so reverting the single implementation commit restores prior behavior; the header-contract tests fail loudly if a partial revert leaves the override and the skip sets inconsistent. |

## Proposed Changes

Each step includes verification checks tagged with confidence. `(auto)` = mechanical, coder self-verifies. `(scripted)` = coder runs the provided gate. Behavioral checks are the tester's. Baseline: full suite 503 passed / 0 failed on 2026-11-13 (runs of plan 2026-11-12-test-harness-port-hardening).

1. **Step 1: `_term_safe()` in the analyzer, applied at the model print**

   In `scripts/analyze_proxy_trace.py`, insert immediately after `def geomean(values):`'s function (i.e., immediately before `def parse_args():`):

   ```python
   def _term_safe(value):
       """Escape terminal-hostile characters for operator output.

       The per-model table's key is client-supplied text read back from the
       trace: on pre-routing rejections the trace's model field is the raw
       client string, and a CSI/OSC sequence in it would otherwise be
       replayed verbatim into the operator's terminal. Escaped: the C0, DEL
       and C1 control ranges (as \\xNN), and lone UTF-16 surrogates
       (U+D800-U+DFFF, as \\uNNNN) — a surrogate survives the json
       round-trip (a client may send {"model": "\\ud800"}; json.dumps writes
       the ASCII escape, the analyzer's json.loads decodes it back), but
       print() of one raises UnicodeEncodeError on a strict-UTF-8 stdout,
       so unescaped it is a client-controlled crash of the analyzer.
       Legitimate model names — including non-ASCII ones — stay
       byte-identical. A non-string value (hand-edited or third-party
       trace) is coerced, not crashed on.
       """
       if not isinstance(value, str):
           value = str(value)
       out = []
       for ch in value:
           o = ord(ch)
           if 0xD800 <= o <= 0xDFFF:
               out.append("\\u{:04x}".format(o))
           elif o < 0x20 or o == 0x7F or 0x80 <= o <= 0x9F:
               out.append("\\x{:02x}".format(o))
           else:
               out.append(ch)
       return "".join(out)
   ```

   And the single print site (the only client-derived print in the file):

   ```python
   # old
           print(f"{model:<20} {req_count:>10} {avg_retries:>12.4f} {query_success_rate:>14.2f}% {attempt_success_rate:>16.2f}% {geo_ttft:>11.2f}s {geo_latency:>11.2f}s")
   # new
           print(f"{_term_safe(model):<20} {req_count:>10} {avg_retries:>12.4f} {query_success_rate:>14.2f}% {attempt_success_rate:>16.2f}% {geo_ttft:>11.2f}s {geo_latency:>11.2f}s")
   ```

   → coder verify (auto): `_term_safe` defined before `def parse_args():`; the per-model print is the only print that interpolates `model`; `python -c "import ast; ast.parse(open('scripts/analyze_proxy_trace.py').read())"` succeeds
   → coder verify (scripted): `timeout 120 python ./tmp/verification/2026-11-13-operator-output-hygiene-structure.py` — assertion 1 prints PASS (gate exit stays 1 until Step 4)
   → tester verify: `analyzer-model-escape` (Step 6) passes

2. **Step 2: `send_response` override — no proxy `Server`, exactly one `Date`**

   In `src/claude_retry_proxy/server.py`, immediately after `class ProxyHandler(http.server.BaseHTTPRequestHandler):` (and before `    def _send_response(self, status, body_bytes, headers=None):`):

   ```python
       def send_response(self, code, message=None):
           """send_response minus BaseHTTPRequestHandler's auto-emitted pair.

           The stock method emits "Server: BaseHTTP/0.6 Python/<version>" --
           an implementation disclosure -- and its own "Date" before the
           handler's headers, which the upstream-forwarding loops then
           duplicate. This override emits no Server ever (the upstream's is
           forwarded verbatim by the loops) and exactly one Date (the
           proxy's own; the loops skip the upstream's). log_request is
           preserved: the stderr access-log behavior is unchanged.
           """
           self.log_request(code)
           self.send_response_only(code, message)
           self.send_header("Date", self.date_time_string())
   ```

   → coder verify (auto): the override is the first method in `ProxyHandler`; every `self.send_response(` call site in `server.py` is unchanged (12 sites, single-arg or with default); the only `BaseHTTP` mentions in `server.py` are the class-declaration line (`class ProxyHandler(http.server.BaseHTTPRequestHandler):`) and comments/docstrings — **none of them emitted on the wire**: the override suppresses the stock auto-pair, and the structure gate's `no-explicit-server-header` check separately enforces zero `send_header("Server", ...)` calls anywhere in the file
   → coder verify (scripted): structure gate — assertion 2 prints PASS
   → tester verify: `response-headers-*` tests (Step 5) pass

3. **Step 3: both forwarding loops skip the upstream `date`**

   ```python
   # old (_send_response, server.py:2089-2090)
               for k, v in _crlf_safe(headers).items():
                   if k.lower() not in {"content-type", "transfer-encoding",
                                        "content-length", "connection"}:
   # new
               for k, v in _crlf_safe(headers).items():
                   if k.lower() not in {"content-type", "transfer-encoding",
                                        "content-length", "connection", "date"}:
   ```

   ```python
   # old (_stream_upstream_response, ~server.py:2205-2206)
               for k, v in _crlf_safe(resp_headers).items():
                   if k.lower() not in {"transfer-encoding", "content-length",
                                        "connection"}:
   # new
               for k, v in _crlf_safe(resp_headers).items():
                   if k.lower() not in {"transfer-encoding", "content-length",
                                        "connection", "date"}:
   ```

   (The upstream `server` header passes through both loops untouched — that is deliberate; do not add it to either skip set.)

   → coder verify (auto): both skip sets contain `"date"`; neither contains `"server"`; the two loops are the only `_crlf_safe(...)` consumers with skip sets (grep)
   → coder verify (scripted): structure gate — assertion 3 prints PASS
   → tester verify: `response-headers-buffered-*` and `response-headers-streamed-*` pass

4. **Step 4: trace `model` field cap (mirrors the User-Agent cap)**

   Constants beside the UA pair (`CLIENT_USER_AGENT_MAX_CHARS = 512` / `CLIENT_USER_AGENT_TRUNCATION_MARKER`):

   ```python
   # old
   CLIENT_USER_AGENT_MAX_CHARS = 512
   CLIENT_USER_AGENT_TRUNCATION_MARKER = "[proxy: user-agent truncated]"
   # new
   CLIENT_USER_AGENT_MAX_CHARS = 512
   CLIENT_USER_AGENT_TRUNCATION_MARKER = "[proxy: user-agent truncated]"

   TRACE_MODEL_MAX_CHARS = 512
   TRACE_MODEL_TRUNCATION_MARKER = "[proxy: model truncated]"
   ```

   Helper immediately after `_client_user_agent`'s body (before `def _forward_request_impl`):

   ```python
   def _trace_model(actual_model, model):
       """The model name recorded on the request trace entry, capped.

       The resolved tier name (config-controlled, short) wins; the fallback
       is the raw client-supplied string -- unbounded client text of the
       same class _client_user_agent bounds. A value longer than the cap
       keeps its head and gains a visible marker, so a truncated model name
       is never mistaken for a genuine one; the body-size cap bounds the
       raw input, this bounds its at-rest record.
       """
       value = actual_model or model or "unknown"
       if len(value) <= TRACE_MODEL_MAX_CHARS:
           return value
       keep = TRACE_MODEL_MAX_CHARS - len(TRACE_MODEL_TRUNCATION_MARKER)
       return value[:keep] + TRACE_MODEL_TRUNCATION_MARKER
   ```

   Write site (server.py:4112, inside the trace-entry dict):

   ```python
   # old
               "model": actual_model or model or "unknown",
   # new
               "model": _trace_model(actual_model, model),
   ```

   → coder verify (auto): `TRACE_MODEL_MAX_CHARS = 512` and the marker defined; `_trace_model` defined after `_client_user_agent`; the literal `actual_model or model or "unknown"` appears exactly once in `server.py` (inside `_trace_model`); the trace-entry dict uses `_trace_model(actual_model, model)`
   → coder verify (scripted): `timeout 120 python ./tmp/verification/2026-11-13-operator-output-hygiene-structure.py` — **exit 0, all assertions PASS** (this step completes the gate)
   → tester verify: `trace-model-field-capped` (Step 6) passes

5. **Step 5: response-header contract tests (tester)**

   Create `tests/test_response_headers.py` with this content (registration follows in the same step). Verified against the current harness: `_spawn_proxy_with_bind_retry(port, **kwargs)` returns the **3-tuple** `(port, proc, probe_ok)` — the port can change on a bind-race retry, so always use the returned port; plain keys pair with `passphrase=None` (the `_setup_tier_routing_test` precedent); trace reads use the harness's `_trace_events_named(trace_file, "request")` (with `_wait_for_trace_events` when a poll is needed) — both exist in `_harness.py`; the mock upstreams **drain the request body before responding** (the suite idiom — an undrained HTTP/1.0 close can RST the response and flake the retry loop); and the module carries an `ALL_TESTS` tuple + `run_cli` main block so `python tests/test_response_headers.py` actually runs (a module without them executes nothing and exits 0):

   ```python
   """Response-header contracts: exactly one Date, no proxy Server, the
   upstream Server forwarded verbatim (plan 2026-11-13-operator-output-hygiene)."""
   import http.client
   import http.server
   import json
   import shutil
   import tempfile
   import threading

   from _harness import (
       _create_test_config,
       _create_test_keys_plain,
       _spawn_proxy_with_bind_retry,
       fail,
       find_free_port,
       pass_,
   )

   _TIERS = {
       "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
       "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
       "opus": {"provider": "p", "model": "claude-opus-5"},
   }
   _UPSTREAM_SERVER = "cloudflare-test"
   _UPSTREAM_DATE = "Mon, 01 Jan 2024 00:00:00 GMT"


   class _HeadersUpstream(http.server.BaseHTTPRequestHandler):
       """Buffered upstream: one distinctive Server, one fixed Date.

       send_response_only (not send_response) so the mock itself emits no
       BaseHTTP Server/Date pair -- the response the proxy sees carries
       exactly the headers below, so "the proxy forwarded the upstream
       Server" cannot pass by accident.
       """
       def do_POST(self):
           content_len = int(self.headers.get("Content-Length", 0))
           if content_len:
               self.rfile.read(content_len)  # drain: undrained HTTP/1.0 close RSTs
           body = json.dumps({
               "id": "ok", "type": "message", "model": "m",
               "content": [{"type": "text", "text": "x"}],
               "stop_reason": "end_turn", "stop_sequence": None,
               "usage": {"input_tokens": 1, "output_tokens": 1},
           }).encode()
           self.send_response_only(200)
           self.send_header("Content-Type", "application/json")
           self.send_header("Server", _UPSTREAM_SERVER)
           self.send_header("Date", _UPSTREAM_DATE)
           self.send_header("Content-Length", str(len(body)))
           self.end_headers()
           self.wfile.write(body)

       def log_message(self, fmt, *args):
           pass


   class _HeadersUpstreamNoDate(http.server.BaseHTTPRequestHandler):
       """Upstream that sends no Date at all (HTTP/1.0-origin shape):
       the proxy must still emit exactly one Date — its own."""
       def do_POST(self):
           content_len = int(self.headers.get("Content-Length", 0))
           if content_len:
               self.rfile.read(content_len)
           body = json.dumps({
               "id": "ok", "type": "message", "model": "m",
               "content": [{"type": "text", "text": "x"}],
               "stop_reason": "end_turn", "stop_sequence": None,
               "usage": {"input_tokens": 1, "output_tokens": 1},
           }).encode()
           self.send_response_only(200)
           self.send_header("Content-Type", "application/json")
           self.send_header("Server", _UPSTREAM_SERVER)
           self.send_header("Content-Length", str(len(body)))
           self.end_headers()
           self.wfile.write(body)

       def log_message(self, fmt, *args):
           pass


   class _HeadersUpstreamSSE(_HeadersUpstream):
       """Streamed upstream: same distinctive headers, an SSE body.

       The event sequence mirrors the suite's existing SSE mocks (see
       tests/test_retry_streaming.py); only the headers differ.
       """
       def do_POST(self):
           content_len = int(self.headers.get("Content-Length", 0))
           if content_len:
               self.rfile.read(content_len)  # drain: undrained HTTP/1.0 close RSTs
           events = (
               b'event: message_start\ndata: {"type": "message_start", "message": {"model": "m"}}\n\n',
               b'event: content_block_start\ndata: {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}\n\n',
               b'event: content_block_stop\ndata: {"type": "content_block_stop", "index": 0}\n\n',
               b'event: message_delta\ndata: {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 1}}\n\n',
               b'event: message_stop\ndata: {"type": "message_stop"}\n\n',
           )
           self.send_response_only(200)
           self.send_header("Content-Type", "text/event-stream")
           self.send_header("Server", _UPSTREAM_SERVER)
           self.send_header("Date", _UPSTREAM_DATE)
           self.end_headers()
           for ev in events:
               self.wfile.write(ev)
           self.wfile.flush()


   def _get_headers(port, method, path, body=None):
       conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
       conn.request(method, path, body=body,
                    headers={"Content-Type": "application/json"})
       resp = conn.getresponse()
       headers = resp.getheaders()
       resp.read()
       conn.close()
       return resp.status, headers


   def _dates(headers):
       return [v for k, v in headers if k.lower() == "date"]


   def _servers(headers):
       return [v for k, v in headers if k.lower() == "server"]


   def _start_env(temp_dir, upstream_port):
       config = _create_test_config(temp_dir, _TIERS)
       keys = _create_test_keys_plain(temp_dir, {"p": {
           "url": "http://127.0.0.1:{}".format(upstream_port), "key": "k"}})
       import os
       trace_fd, trace_file = tempfile.mkstemp(suffix=".jsonl", dir=temp_dir)
       os.close(trace_fd)
       port, proc, probe_ok = _spawn_proxy_with_bind_retry(
           find_free_port(), config_path=config, keys_path=keys,
           passphrase=None, trace_file=trace_file)
       return port, proc, probe_ok, trace_file


   def test_response_headers_buffered():
       print("\n--- Test: Response Headers Buffered ---")
       temp_dir = tempfile.mkdtemp(prefix="hdr_buffered_")
       upstream = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _HeadersUpstream)
       threading.Thread(target=upstream.serve_forever, daemon=True).start()
       try:
           port, proc, probe_ok, _trace = _start_env(
               temp_dir, upstream.server_address[1])
           if not probe_ok:
               fail("buffered: proxy failed to start")
               return
           try:
               status, headers = _get_headers(
                   port, "POST", "/v1/messages",
                   json.dumps({"model": "sonnet",
                               "messages": [{"role": "user", "content": "hi"}]}))
               if status != 200:
                   fail("buffered: expected 200, got {}".format(status))
                   return
               if len(_dates(headers)) != 1:
                   fail("buffered: expected exactly 1 Date, got {!r}".format(
                       _dates(headers)))
                   return
               if _servers(headers) != [_UPSTREAM_SERVER]:
                   fail("buffered: expected only the upstream Server {!r}, "
                        "got {!r}".format(_UPSTREAM_SERVER, _servers(headers)))
                   return
               pass_("buffered: one Date, upstream Server only, no disclosure")
           finally:
               proc.terminate()
               proc.wait(timeout=5)
       finally:
           upstream.shutdown()
           upstream.server_close()
           shutil.rmtree(temp_dir, ignore_errors=True)


   ALL_TESTS = (
       ("response-headers-buffered-single-date-no-self-server", test_response_headers_buffered),
       ("response-headers-streamed-single-date-no-self-server", None),        # Step 5 NOTE
       ("response-headers-proxy-generated-no-server-one-date", None),         # Step 5 NOTE
       ("response-headers-options-one-date-no-server", None),                 # Step 5 NOTE
       ("response-headers-upstream-no-date", None),                           # Step 5 NOTE
       ("trace-model-field-capped", None),                                    # Step 6
       ("analyzer-model-escape", None),                                       # Step 6
   )
   # The None entries are filled by the remaining test functions (Step 5
   # NOTE + Step 6); a module lacking this tuple + main block runs NOTHING
   # on direct invocation — the trap this block exists to close.

   if __name__ == "__main__":
       from _harness import run_cli
       run_cli(ALL_TESTS, "response-header contracts / trace model cap / analyzer escape")
   ```

   NOTE for the tester — the module's contract split: `test_response_headers_buffered` above is the **one complete reference body**; the remaining four header tests are specified by their assertions only (structure free, semantics fixed), each following the reference shape with its own upstream class. `response-headers-streamed-single-date-no-self-server` swaps `_HeadersUpstreamSSE` in (assert status 200, one Date, `_servers(headers) == [_UPSTREAM_SERVER]`); `response-headers-proxy-generated-no-server-one-date` posts `{"model": "no-such-model", ...}` to the same proxy and asserts status 400, one Date, `_servers(headers) == []`; `response-headers-options-one-date-no-server` sends `OPTIONS /v1/messages` (via `_get_headers(port, "OPTIONS", "/v1/messages")` — no body) and asserts one Date and no Server; `response-headers-upstream-no-date` swaps `_HeadersUpstreamNoDate` in and asserts status 200, `_servers(headers) == [_UPSTREAM_SERVER]`, and exactly one Date (the proxy's own — an upstream that sent none must not produce a double Date). Fill the `None` entries in `ALL_TESTS` with the real functions. Align the SSE event sequence and module registration with the suite's existing idiom (`tests/test_retry_streaming.py`, aggregator import + tuple append as `HARNESS_HARDENING_TESTS` does). The two Step-6 tests join this same module.

   Register in `tests/test_claude_proxy.py` (import + tuple append, same pattern as `HARNESS_HARDENING_TESTS`).

   → tester verify: `timeout 60 python tests/test_claude_proxy.py --list` prints the new slugs; `timeout 600 python tests/test_response_headers.py` all green; full suite green with 0 failed

6. **Step 6: analyzer-escape and model-cap tests (tester)**

   Both join `tests/test_response_headers.py` (same module, same registration).

   `trace-model-field-capped`: start a proxy via Step 5's `_start_env` (any upstream; the request never reaches it), post three requests → 400 `unrecognized_model` each, then read the trace with the harness's `_trace_events_named(trace_file, "request")` and find the `event == "request"` entries with `http_status == 400`; assert the cap's **boundaries**, not just a smoke length: `{"model": "A" * 512}` → `entry["model"] == "A" * 512` (unchanged, no marker); `{"model": "B" * 513}` → `"B" * (512 - len("[proxy: model truncated]")) + "[proxy: model truncated]"`; `{"model": "C" * 600}` → the same shape with `C`. (Precondition, verified in source: on the unknown-model path `actual_model` is `None` and `model` is the raw client string, so the trace entry carries the raw name before the cap and the capped value after. The 512/513 pair is what discriminates an off-by-one in the guard or the `keep` arithmetic; 600 alone cannot.)

   `analyzer-model-escape`: write a one-line trace JSONL to a temp file — the analyzer's ingestion (verified: `model = entry.get("model")` with a `continue` when absent; `status`, `retries`, and a timestamp within the `--days` window are the other fields read) needs:
   ```json
   {"timestamp": "<now, %Y-%m-%dT%H:%M:%SZ UTC>", "event": "request", "request_id": "r1", "model": "\u001b]0;pwned\u0007\ud800sonnet", "status": "failure", "http_status": 400, "retries": 0, "total_latency_sec": 0}
   ```
   (generate the timestamp with `datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")` so it is inside the window; the `\ud800` in the model is a lone surrogate — it survives the json round-trip, and pre-fix it crashes the analyzer's `print()` with `UnicodeEncodeError`, which is the regression this test pins). Then run `timeout 60 python scripts/analyze_proxy_trace.py --trace-file <tmp> --days 1` as a subprocess with stdout captured (`text=True`, `errors="backslashreplace"` on the read side so a pre-fix crash is observed as output, not as a test-side read error), and assert: (a) `returncode == 0`; (b) no raw `\x1b` byte appears in stdout (`"\x1b" not in out`); (c) the escaped label appears — the literal text `\\x1b]0;pwned\\x07\\ud800sonnet` (backslash-escaped forms, in order) is present in stdout.

   → tester verify: both pass standalone and in the full suite; `timeout 900 python tests/test_claude_proxy.py` — 0 failed

## Guidance for Planner

Documentation tasks you will execute yourself (not the coder):

- **Files to modify:**
  - `./doc/trace-log.html`
  - `./doc/architecture.html`
  - `./doc/test-catalog.html`
  - `./README.md`
  - `./CLAUDE.md` (one sentence — only if the check below finds it stale)
- **`.claude/mega-audit-files.json`:** not touched (absent; no declared audit locations change).
- **When:** after tester finishes.
- **What to sync:**
  - `doc/trace-log.html`:
    - the entry-schema row for the `model` field (~line 42) is corrected AND gains the cap note: its current text ("The upstream model actually requested") is wrong for pre-routing rejections — the field is the tier's configured upstream model when resolved, else the **raw client-supplied string**, else `"unknown"`; and it is capped at 512 characters, head kept, with the `[proxy: model truncated]` marker (the same treatment as `client_user_agent`; state the unit as characters, not bytes).
    - the `--all` note (~line 364): the sentence "`method`, `path` and `model` are also verbatim client strings" — extend with the cap + marker clause (the same extension CLAUDE.md's copy gets).
    - the analyzer section (~385): the per-model label is terminal-escaped for operator safety — control characters (C0/DEL/C1) and lone surrogates render as `\xNN`/`\uNNNN`; legitimate names, non-ASCII included, are unchanged.
  - `doc/architecture.html`: the response-path prose (near the error-envelope / response sections) states the header contract **scoped to the two forwarding loops**: exactly one `Date` (the proxy's own; the upstream's is dropped at the loops), zero proxy `Server`, the upstream's `Server` forwarded verbatim on forwarded responses — and why the upstream `Server` is preserved (edge-vs-origin diagnosis, the Cloudflare `1010` case). State the give-up path's shape separately: on 429/503 exhaustion the upstream error body is delivered under proxy-generated headers (one `Date`, no `Server`) — its empty headers dict never forwarded upstream identity.
  - `doc/test-catalog.html`: the per-test index is hand-reconciled in the same commit as the tests it documents — add a module-table row for `tests/test_response_headers.py`, per-test inventory entries for all seven slugs (`response-headers-buffered-single-date-no-self-server`, `response-headers-streamed-single-date-no-self-server`, `response-headers-proxy-generated-no-server-one-date`, `response-headers-options-one-date-no-server`, `response-headers-upstream-no-date`, `trace-model-field-capped`, `analyzer-model-escape`), and bump the page's last-updated stamps.
  - `README.md`:
    - Trace log section: after the `client_user_agent` cap sentence, add the `model` cap + `[proxy: model truncated]` marker sentence (the exact precedent this change mirrors).
    - `--all` exposure paragraph: the sentence "`method`, `path` and `model` are verbatim client strings too" — extend with the cap + marker clause, same as CLAUDE.md's copy.
  - `CLAUDE.md` check: the `--all` gotcha's sentence "`method`/`path`/`model` are client strings too" — now that `model` is capped, extend that clause with the cap + marker (one clause, not a new bullet).
  - Doc-sync sweep: `git grep` the changed identifiers (`_term_safe`, `send_response_only`, `TRACE_MODEL_MAX_CHARS`, `TRACE_MODEL_TRUNCATION_MARKER`, `_trace_model`, `test_response_headers`, `[proxy: model truncated]`, and the seven test slugs) across `doc/`, `CLAUDE.md`, `README.md`, and archived `plans/`, and reconcile every hit; bump `doc/trace-log.html`'s, `doc/architecture.html`'s, and `doc/test-catalog.html`'s last-modified stamps if they carry them.

## History

One row per event (spec revision / mega-audit / review / implementation round). Conclusion = one-sentence outcome or what changed. Dismissed = compact dismissed-findings list for the reviewer — verbatim issue slugs linked as `[<slug>](<report-path>)`, no prose-only entries. Link to report files; never restate findings inline.

| Date | Event | Conclusion | Dismissed |
|------|-------|------------|-----------|
| 2026-11-13 | Review (Phase 6) | Verdict "Issues found — non-blocking": 0 Critical, 1 Warning, 4 Suggestions — [report](./tmp/reports/2026-11-13-operator-output-hygiene-review-2026-11-13.json). Source-side verification clean (override routes all 12 `send_response` sites; one Date emission site; zero `send_header("Server", ...)`; both loops skip `date` keep `server`; cap arithmetic exact; escape coverage correct; gate + anchor checker re-run PASS). **Warning addressed in-plan**: the trace-log `model` row my doc-sync wrote named "invalid JSON body" as a raw-client path — reviewer traced `extract_model` returning `(None, "invalid_json")` → the trace records `"unknown"` there; the row is corrected to scope the raw-client case to the `unrecognized_model` path (verified against server.py:1892-1902). | Suggestions acknowledged, non-blocking: (1) tests/test_response_headers.py:197+231/269/303/334/380 — the six proxy tests `return` before cleanup on `probe_ok=False`, leaking the handed-back child (suite idiom stops `proc` in the outer `finally`); (2) :437 — `analyzer-model-escape` pins only the C0 + surrogate arms, leaving DEL/C1/non-str unexercised; (3) server.py:1041 — `_trace_model`'s docstring says "resolved tier name" where the value is the configured model name (plan-authored wording, verified); (4) :123 — `_get_headers`/`_get_headers_body` duplicate six lines. Recorded for a future round; none block the commit gate. |
| 2026-11-13 | Implementation round (tester) | Round 1 SUCCESS — 510/510 (503 baseline + 7 new), all seven tests pass standalone and in the full suite — [report](./tmp/reports/2026-11-13-operator-output-hygiene-tester-2026-11-13.json). Both adopted rows → Resolved (tester). One Plan Error fixed in the record: the Step 5 reference SSE mock's `events` tuple lacked commas between its bytes literals (a literal copy concatenates one bytes object, iterating ints → TypeError); the tester landed the corrected tuple plus a body-level `message_stop` assertion, and the plan skeleton now carries the commas so a future copy cannot reintroduce it. No test retirement (no existing Server/Date, analyzer, or trace-model-length assertions exist). | — |
| 2026-11-13 | Implementation round (coder) | Round 1 clean — all four source steps pass, structure gate exit 0 (RED-first, incremental PASS), zero issues filed — [report](./tmp/reports/2026-11-13-operator-output-hygiene-coder-2026-11-13.json). Report verifies `_trace_model`'s unguarded `len(value)` is safe (extract_model's contract is str-or-"unknown") and audits the analyzer's remaining prints as non-client-derived. Doc suggestions folded into Guidance for Planner. Steps 5–6 to the tester. | — |
| 2026-11-13 | Mega-audit (pre-implementation) | 26 findings (1 High, 10 Medium, 15 Low) across 9 lenses — [report](./tmp/reports/2026-11-13-operator-output-hygiene-mega-audit-2026-11-13.json). High fixed: lone-surrogate arm + non-str guard in `_term_safe` (three lenses, live-reproduced `UnicodeEncodeError` crash; gate + probe updated and re-proven RED/teeth). Mediums fixed: `doc/test-catalog.html` + `README.md` + trace-log `--all`-note/model-row + architecture give-up-path scoping added to the planner lane; mock upstreams drain the request body (RST flake class); Step 5 skeleton gains `ALL_TESTS` + `run_cli` main block; teeth probe referenced in the coder guidance. Lows fixed: BaseHTTP check reworded to its satisfiable form, cap boundary cases (512/513), rollback row, `_trace_events_named` pointer, recipes/assertions wording. 1 High < 3 → no re-audit. | [edge-case-explorer #20, 429-exhaustion header-test variant](./tmp/reports/2026-11-13-operator-output-hygiene-mega-audit-2026-11-13.json) — declined: the give-up path returns an empty headers dict downstream (no upstream headers ride it), so its client-visible shape (one Date, no Server) is exactly what `response-headers-proxy-generated-no-server-one-date` already asserts; the skip-set edit lives in `_send_response`, which the buffered 200 test covers; the added `response-headers-upstream-no-date` test covers the one genuinely distinct assertion from the same finding. |
| 2026-11-13 | Initial plan | Adopts two 2026-10-21 deferrals (`analyze-trace-model-terminal-escape`, `proxy-own-server-date-headers`) plus the model-cap decision the first left open (user-approved 2026-11-13): analyzer control-char escaping, one `send_response` override + two skip-set entries for the header contract, 512-char trace-model cap mirroring the UA precedent. Baseline: full suite 503/503 on 2026-11-13. | — |

## Plan Metadata

```json
{
  "plan_id": "2026-11-13-operator-output-hygiene",
  "steps": [
    "Step 1: _term_safe() in the analyzer, applied at the model print",
    "Step 2: send_response override — no proxy Server, exactly one Date",
    "Step 3: both forwarding loops skip the upstream date",
    "Step 4: trace model field cap (mirrors the User-Agent cap)",
    "Step 5: response-header contract tests (tester)",
    "Step 6: analyzer-escape and model-cap tests (tester)"
  ],
  "coder_files": [
    "scripts/analyze_proxy_trace.py",
    "src/claude_retry_proxy/server.py"
  ],
  "tester_files": [
    "tests/test_response_headers.py",
    "tests/test_claude_proxy.py"
  ],
  "doc_files": [
    "./doc/trace-log.html",
    "./doc/architecture.html",
    "./doc/test-catalog.html",
    "./README.md",
    "./CLAUDE.md"
  ],
  "verification_scripts": [
    "./tmp/verification/2026-11-13-operator-output-hygiene-structure.py",
    "./tmp/verification/2026-11-13-operator-output-hygiene-teeth-probe.py"
  ],
  "retire_inventory": {
    "reports": [
      "./tmp/reports/2026-11-13-operator-output-hygiene-coder-2026-11-13.json",
      "./tmp/reports/2026-11-13-operator-output-hygiene-tester-2026-11-13.json",
      "./tmp/reports/2026-11-13-operator-output-hygiene-mega-audit-2026-11-13.json",
      "./tmp/reports/2026-11-13-operator-output-hygiene-review-2026-11-13.json"
    ],
    "verification": [
      "./tmp/verification/2026-11-13-operator-output-hygiene-structure.py",
      "./tmp/verification/2026-11-13-operator-output-hygiene-teeth-probe.py",
      "./tmp/verification/teeth-probe/"
    ]
  },
  "repo_mode": "Public",
  "document_overrides": []
}
```

## Audit Accumulation

*Counters reset when mega-audit runs. Used by Phase 5 entry trigger.*

| Counter | Value | Last Updated |
|---------|-------|--------------|
| issues_resolved_since_audit | 2 | 2026-11-13 |
| steps_changed_since_audit | 1 | 2026-11-13 |
| files_changed_since_audit | 0 | 2026-11-13 |

## Documentation

See "Guidance for Planner" — `doc/trace-log.html` (model-row correction + cap,
`--all`-note clause, analyzer escape note), `doc/architecture.html` (header
contract, give-up-path shape), `doc/test-catalog.html` (module row + seven
per-test entries + stamps), `README.md` (trace-log cap sentence + `--all`
clause), and a one-clause `CLAUDE.md` check.

## Final Results

**Status: COMPLETED — 2026-11-13.** Awaiting user approval for `/update-and-commit`.

### What was implemented

All six steps landed. Coder (round 1, clean): `_term_safe()` in the analyzer — C0/DEL/C1
escaped as `\xNN`, lone surrogates as `\uNNNN`, non-str coerced — at the single client-derived
print; the `ProxyHandler.send_response` override (log_request + send_response_only + exactly
one `Date`) ending the `BaseHTTP/0.6 Python/<ver>` disclosure on every path; `"date"` in both
forwarding-loop skip sets (the upstream `Server` still forwards verbatim — the `cloudflare`
edge diagnostic survives); `TRACE_MODEL_MAX_CHARS = 512` + `[proxy: model truncated]` +
`_trace_model()` mirroring the User-Agent cap. Tester (round 1, SUCCESS): seven permanent
tests in the new `tests/test_response_headers.py` — the header contract on buffered, streamed,
proxy-generated, and OPTIONS responses; upstream-without-Date; the cap's 512/513/600
boundaries; the analyzer's escape (including the pre-fix `UnicodeEncodeError` crash
regression) — all registered in the aggregator. Doc-sync (planner lane): trace-log.html
(model-row correction + cap + `--all` clause + analyzer note), architecture.html (response-
headers step-box scoped to the forwarding loops, give-up shape stated), test-catalog.html
(module row + Category 15), README.md, CLAUDE.md.

### Test results

- Full suite: **510 passed, 0 failed** (baseline 503 + 7 new) — [tester report](./tmp/reports/2026-11-13-operator-output-hygiene-tester-2026-11-13.json)
- Structure gate: PASS, 25 checks (RED-first proven) — teeth probe exit 0 pre-launch
- Anchor checker: 260 references resolved; `tests/test_docs.py` 11/11 after doc-sync

### Review

Phase 6 reviewer: **0 Critical, 1 Warning, 4 Suggestions** — non-blocking,
[report](./tmp/reports/2026-11-13-operator-output-hygiene-review-2026-11-13.json). The one
Warning (my trace-log row claimed the invalid-JSON path records raw client text; it records
`"unknown"`) was verified and **fixed in-plan**. The Suggestions are test-hygiene and
docstring-wording improvements, recorded in the History Dismissed cell.

### Issues resolved

- [analyze-trace-model-terminal-escape](./tmp/reports/defer-issue-analyze-trace-model-terminal-escape.json) — **Resolved** (tester)
- [proxy-own-server-date-headers](./tmp/reports/defer-issue-proxy-own-server-date-headers.json) — **Resolved** (tester)

Both reports retire via `/update-and-commit` Step 9.6 (their Issue Log rows above are the
trigger).

### Deferred issues (visibility)

- [drop-redacted-thinking-chat-placeholder](./tmp/reports/defer-issue-drop-redacted-thinking-chat-placeholder.json) — **still open, unadopted** (filed 2026-10-21): a decided
  design change (drop the redacted-thinking placeholder in chat transforms), no urgency; no
  plan row here — it remains on disk per presence-means-open.

### Known caveats (from the review, all non-blocking)

- The six proxy-spawning tests return before cleanup on a startup failure — a live child could
  leak in that failure path (suite idiom stops `proc` in an outer `finally`).
- `analyzer-model-escape` pins the C0 and surrogate arms; DEL/C1/non-str are unexercised.
- `_trace_model`'s docstring says "resolved tier name" where the value is the configured model
  name (plan-authored wording — needs a coder round for a one-word fix; recorded, not done).
- `_get_headers`/`_get_headers_body` in the test module duplicate six lines.

### Files changed (uncommitted)

Source (coder): `scripts/analyze_proxy_trace.py`, `src/claude_retry_proxy/server.py`
· Tests (tester): `tests/test_response_headers.py` (new), `tests/test_claude_proxy.py`
· Docs (planner): `doc/trace-log.html`, `doc/architecture.html`, `doc/test-catalog.html`,
`README.md`, `CLAUDE.md`
