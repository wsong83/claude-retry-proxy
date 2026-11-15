# Plan: Migrate the upstream transport to httpx2 and rework the streaming read layer

**Plan ID:** 2026-11-15-httpx2-transport-sse
**Created:** 2026-11-15

## Immediate Actions

**Planner:**
- Execute the Guidance for Planner doc reconciliation in full (CLAUDE.md, README.md, doc/architecture.html, doc/provider-modes.html, doc/operations.html, doc/configuration.html, doc/trace-log.html, doc/test-catalog.html), including the tester- and review-flagged entries; then write Final Results (with retire_inventory) and present for approval.

**Coder / Tester:** (no directives — implementation and verification complete)

## Issue Log

Rows ordered newest-first (latest issues at top). New issues are prepended; resolved issues stay in place with updated status.

| Issue | Status | Found | Resolved | Resolved By |
|-------|--------|-------|----------|-------------|
| [review-ipv6-literal-base-url](./tmp/reports/2026-11-15-httpx2-transport-sse-review-2026-11-15.json) | Resolved | 2026-11-15 | 2026-11-15 | [tester](./tmp/reports/2026-11-15-httpx2-transport-sse-tester-2026-11-15-2.json) |
| [review-retry-drain-uncapped-decode](./tmp/reports/2026-11-15-httpx2-transport-sse-review-2026-11-15.json) | Resolved | 2026-11-15 | 2026-11-15 | [tester](./tmp/reports/2026-11-15-httpx2-transport-sse-tester-2026-11-15-2.json) |
| [review-init-version-stale](./tmp/reports/2026-11-15-httpx2-transport-sse-review-2026-11-15.json) | Resolved | 2026-11-15 | 2026-11-15 | [tester](./tmp/reports/2026-11-15-httpx2-transport-sse-tester-2026-11-15-2.json) |
| [buffered-size-cap-four-sites-miscount](./tmp/reports/2026-11-15-httpx2-transport-sse-buffered-size-cap-four-sites-miscount.json) | Resolved | 2026-11-15 | 2026-11-15 | [planner](./tmp/reports/2026-11-15-httpx2-transport-sse-coder-2026-11-15-2.json) |
| [forward-request-docstring-tuple-arity](./tmp/reports/2026-11-15-httpx2-transport-sse-forward-request-docstring-tuple-arity.json) | Resolved | 2026-11-15 | 2026-11-15 | [tester](./tmp/reports/2026-11-15-httpx2-transport-sse-tester-2026-11-15.json) |
| [step7-code-block-unbound-tuple-members](./tmp/reports/2026-11-15-httpx2-transport-sse-step7-code-block-unbound-tuple-members.json) | Resolved | 2026-11-15 | 2026-11-15 | [tester](./tmp/reports/2026-11-15-httpx2-transport-sse-tester-2026-11-15.json) |
| [drain-byte-budget-chunk-granularity](./tmp/reports/2026-11-15-httpx2-transport-sse-drain-byte-budget-chunk-granularity.json) | Resolved | 2026-11-15 | 2026-11-15 | [tester](./tmp/reports/2026-11-15-httpx2-transport-sse-tester-2026-11-15.json) |
| [buffered-size-cap-single-chunk](./tmp/reports/2026-11-15-httpx2-transport-sse-buffered-size-cap-single-chunk.json) | Resolved | 2026-11-15 | 2026-11-15 | [tester](./tmp/reports/2026-11-15-httpx2-transport-sse-tester-2026-11-15.json) |
| [do-post-no-outer-exception-guard](./tmp/reports/2026-11-15-httpx2-transport-sse-do-post-no-outer-exception-guard.json) | Resolved | 2026-11-15 | 2026-11-15 | [tester](./tmp/reports/2026-11-15-httpx2-transport-sse-tester-2026-11-15.json) |
| [eventsource-eof-sentinel-drop](./tmp/reports/2026-11-15-httpx2-transport-sse-eventsource-eof-sentinel-drop.json) | Resolved | 2026-11-15 | 2026-11-15 | [tester](./tmp/reports/2026-11-15-httpx2-transport-sse-tester-2026-11-15.json) |
| [upstream-header-value-encoding](./tmp/reports/2026-11-15-httpx2-transport-sse-upstream-header-value-encoding.json) | Resolved | 2026-11-15 | 2026-11-15 | [tester](./tmp/reports/2026-11-15-httpx2-transport-sse-tester-2026-11-15.json) |
| [iter-raw-chunk-coalescing](./tmp/reports/2026-11-15-httpx2-transport-sse-iter-raw-chunk-coalescing.json) | Resolved | 2026-11-15 | 2026-11-15 | [tester](./tmp/reports/2026-11-15-httpx2-transport-sse-tester-2026-11-15.json) |
| [httpx2-native-sse-transport](./tmp/reports/defer-issue-httpx2-native-sse-transport.json) | Resolved | 2026-09-27 | 2026-11-15 | [tester](./tmp/reports/2026-11-15-httpx2-transport-sse-tester-2026-11-15.json) |

## Guidance for Coder

**Files to modify:** `src/claude_retry_proxy/server.py`, `src/claude_retry_proxy/settings.py`, `pyproject.toml`

**Step-by-step with verification:** the six steps in `## Proposed Changes` carry
coder checks tagged `(auto)`; the coder self-verifies them. Tester owns the
behavioral checks. See coder Prime Directive 4.

The client-facing server (`http.server.ThreadingHTTPServer`), all body transforms
(`transforms_*.py`), the compat learner, sinks, config/keys pipelines, and the admin
surface are **out of scope and must not change**. Only the *upstream-direction*
transport and the *upstream-response* read loops move.

External facts — **empirically verified against the installed httpx2 2.13.1** by the
2026-11-15 mega-audit lenses (probes recorded in
[the audit report](./tmp/reports/2026-11-15-httpx2-transport-sse-mega-audit-2026-11-15.json)):
`dict(httpx2.Headers)` LOWERCASES keys and comma-joins duplicate values — the raw
wire pairs live only in `Headers.raw`; `iter_bytes()` decodes according to the
RESPONSE's Content-Encoding header (a gzip-responding upstream yields decompressed
bytes under a forwarded `Content-Encoding: gzip` — corruption), while
`iter_raw()` yields undecoded bytes unconditionally and installs no decoder (no
`DecodingError` surface); an httpx2 response stream is single-consumption — a
second `iter_bytes()`/`iter_raw()` call raises `StreamConsumed` (a `StreamError`,
a `RuntimeError` — NOT a TransportError), so one iterator object must serve all
phases; `httpx2.EventSource(response, max_event_size=...)` EXISTS — response-bound
SSE parsing over an already-open Response (default max_event_size 1048576), raising
`SSEError` on oversize (and on content-type mismatch); `SSEError` subclasses
`TransportError`; `DecodingError` sits under `RequestError`, OUTSIDE the
TransportError family; `Response.read()` still exists; with `trust_env=False`,
`SSL_CERT_FILE`/`SSL_CERT_DIR` are IGNORED (env CA overrides are trust_env-gated).
Exception names and any remaining semantics MUST be re-verified against the
installed package source before wiring (Step 3 pre-check).

**Coder pre-check (before Step 3):** read the installed httpx2/httpcore2 source and
record in the session report: (a) the exception surface the read paths can raise —
`RequestError` (covering `TransportError` and `DecodingError`), `StreamError`
(`StreamConsumed`, `StreamClosed`), `SSEError`, `InvalidURL` — with their exact
names and parent chains as installed; (b) `Headers.raw` pair semantics and that the
latin-1 dict comprehension preserves casing and last-wins duplicates; (c) that
`iter_raw()` can be created once and consumed across loop phases on one Response
(the single-consumption rule); (d) `EventSource` availability and behavior at the
pinned floor (`>=2.13.1`): constructor signature, `max_event_size` disposition
(SSEError raise vs skip), whether SSEError carries the oversize size, iteration
protocol over an already-open streaming Response; (e) `Response.read()` semantics
on a streaming response. Step 5(b)'s primary shape depends on (d); the fallback
(scanner retained) applies only if (d) fails at the floor.

## Guidance for Tester

**Test isolation:** every new test that spawns or imports the proxy follows the
canonical spawn-isolation block (PROXY_TRACE_FILE / PROXY_FEATURE_COMPAT_FILE /
PROXY_STATE_FILE to session-temp paths at module load, before the first import or
spawn). Tests pinning `PROXY_READ_TIMEOUT` do so in the spawned server's
environment (and `SETTINGS` for in-process checks), using values ≥ 10 — the
validation floor refuses smaller values by design (they fall back to 120).

**Tests to create / extend:**
- **Permanent:**
  - `test_env_int_fallback_semantics` (tests/test_settings.py, EXTEND — do not add
    a parallel test; the existing table-driven test already pins the same
    `_env_int` branch matrix for PROXY_SWAP_SILENCE_TIMEOUT): add a
    `_READ_TIMEOUT_CASES` block (valid 30, boundary 10/600, below-min 5,
    above-max 900, unparseable "abc", unset → 120) plus the live
    `SETTINGS.read_timeout == 120` default assertion, mirroring the existing
    swap-silence block.
  - `test_upstream_accept_encoding_identity` (tests/test_retry_streaming.py): the
    upstream stub asserts the forwarded request carries `Accept-Encoding: identity`
    (kept as defence-in-depth assertion even though correctness no longer rests on
    it — read sites use iter_raw).
  - `test_upstream_cookie_isolation` (tests/test_retry_streaming.py): stub responds
    `Set-Cookie: k=v` to request 1; request 2 to the same provider carries NO
    `Cookie` header (per-chain client lifetime; the mirror of today's stateless
    forwarding).
  - `test_chat_sse_first_frame_oversize_errors_loud` (tests/test_chat_sse.py): stub
    sends a >2 MB first frame with no delimiter → client receives `message_start`
    then `event: error` with `error.code == "upstream_frame_oversize"`, and NO
    `message_delta`/`message_stop`; trace carries BOTH `chat_sse_frame_oversize`
    (with the `bytes` field) and `chat_sse_truncated` (the invariant event).
  - `test_chat_sse_drain_window_frame_oversize_drops_and_completes`
    (tests/test_chat_sse.py): healthy frames, `finish_reason`, then one >2 MB
    frame mid-drain → the turn still completes with the normal terminal sequence
    (`message_delta` + `message_stop`), the oversize frame is not translated, the
    trace carries `chat_sse_frame_oversize` (with `bytes`), and
    `chat_sse_tool_degradation.frame_dropped == 1` (the narrowed drain-window
    meaning).
  - `test_stream_read_timeout_bounds_stall` (tests/test_retry_streaming.py): with
    `PROXY_READ_TIMEOUT=10` (the floor — smaller values are refused), a stub that
    opens an SSE stream then goes silent ends the client-visible stream promptly
    (≤ ~15 s), not at a 300 s hang.
  - `test_chat_sse_drain_read_timeout_completes_turn` (tests/test_chat_sse.py):
    frames + `finish_reason`, then silence, with `PROXY_READ_TIMEOUT=10` → the
    client still receives the normal terminal sequence (≤ ~15 s) and
    `chat_sse_drain.drain_exit == "read_timeout"` (the new enum value).
  - `test_connection_error_retry_mapping` (tests/test_retry_streaming.py): stub
    accepts then resets mid-response → a `retry` trace event with
    `reason: "connection_error"` lands. (The exhaustion/502 half is deliberately
    NOT re-pinned — `test_exhaust_connection_error_synthesizes_body` and
    `test_disable_retry_count_tokens_conn_error` already cover it.)
  - `test_forward_failure_returns_envelope` (tests/test_retry_streaming.py, for
    Step 7): inject a forwarding exception (e.g. a stub URL that makes the
    transport raise a non-tuple type, or monkeypatched `forward_request`
    raising) → the client receives the 502 Anthropic envelope with
    `error.code == "upstream_unreachable"` (never a closed connection with no
    response), and a `forward_failed` trace entry lands.
  - `test_ipv6_provider_url_routes` (tests/test_retry_streaming.py, for Step 8):
    a provider URL with an IPv6 literal authority (`http://[::1]:<port>/v1`
    against a local stub) is routed — the request reaches the stub (the bracketed
    base_url constructs; no 502-before-attempt).
  - `test_version_consistency` (tests/test_settings.py or the aggregator, for
    Step 8): `claude_retry_proxy.__version__` equals the version in
    pyproject.toml (pin the 0.3.0 pairing and the general equality).
  - `test_429_drain_bounded` (tests/test_retry_streaming.py, for Step 8): a 429
    whose body exceeds `PROXY_MAX_BODY_SIZE` (and carries a Content-Encoding)
    still retries — the bounded non-decoding drain neither hangs nor crashes,
    and the retry trace event lands.
- **Temporary:** none anticipated.

**Tests to investigate for retirement / rework (named by the audit):**
- Planner candidates:
  - `tests/test_admin.py::test_switch_evicts_silent_stream` — built on the deleted
    30 s armed wake; re-base on the read-boundary residual: pin
    `PROXY_READ_TIMEOUT=10` in the spawned `_swap_proxy` env, re-baseline the
    elapsed window on read-boundary semantics (the eviction lands at the next read
    boundary, ≤ read timeout, not within the quiet window), and record the new
    timing basis in the session report rather than weakening the eviction
    assertion.
  - `tests/test_admin.py::test_switch_silent_before_press_is_late_exit` —
    assertions survive; correct the stale "armed at the connection's 300 s
    timeout" wording to the `PROXY_READ_TIMEOUT` basis.
  - `tests/test_chat_sse.py::test_chat_sse_drain_time_deadline` and
    `::test_chat_sse_drain_late_tool_call_time_budget` — pin
    `PROXY_READ_TIMEOUT=10` in their spawned env, widen the client deadline to
    ~20 s, and expect `drain_exit == "read_timeout"` for the silent-provider
    shape (the per-chunk `MAX_DRAIN_SECONDS` check survives, so a chatty-slow
    drain still exits `"time_budget"`).
  - `tests/test_chat_sse.py::test_chat_sse_swap_drain_pin_taken_mid_swap` —
    drain_pin() is deleted; rework to assert the drain completes at the read
    boundary with `PROXY_READ_TIMEOUT=10` pinned, or retire if its premise (the
    conditional pin) is gone.
  - `tests/test_chat_sse.py::test_chat_sse_swap_evicts_pre_finish` and
    `::test_chat_sse_eviction_stranded_sentinel_never_flushes` — pin
    `PROXY_READ_TIMEOUT=10` so the read-boundary eviction is exercised
    deterministically, or retire if the armed-wake client-visible eviction is
    accepted as gone.
  - `tests/test_chat_sse.py::test_chat_sse_swap_abort_in_drain_window` —
    assertions should still hold; correct the docstring narrative that reasons
    from the 5 s pin.
  - `tests/test_chat_sse.py::test_chat_sse_frame_dropped_guard` — the pre-finish
    drop disposition it asserts no longer exists (superseded by
    `test_chat_sse_first_frame_oversize_errors_loud`); update or retire.
  - `tests/test_parse_guards.py::test_parse_guard_gate_python38_portable` — pins
    `requires-python = ">=3.8"`, which Step 2 changes; the test is vacuous under
    the 3.10 floor. Rewrite against the new floor or retire, and note the
    doc/test-catalog.html index entries (Category 13 row and the per-test entry).
  - Grep the suite for http.client-internal assertions (`IncompleteRead`,
    `RemoteDisconnected`, `fp.raw`, `read1`) — any test reaching into the response
    object's internals needs rework or retirement; none are known to exist (the
    suite asserts wire behavior through spawned proxies).
- Tester may identify additional candidates during test work.

**Retirement procedure:** For each candidate, verify the test exercises code being
removed/changed. If obsolete: delete and note in session report. If still valid:
document why in session report.

**Wire-delta awareness (verify no existing test contradicts; do not add tests):**
when the client omits User-Agent, upstream now sees `python-httpx2/<version>`
(today: no UA line); SSL verification moves to the OS trust store via truststore,
and under `trust_env=False` the `SSL_CERT_FILE`/`SSL_CERT_DIR` ambient CA overrides
are IGNORED (today's http.client path honors them) — an accepted, documented delta
for custom-CA operators; duplicate upstream response headers keep today's
last-wins collapse in the forwarded map (the `.raw` mapping reproduces
`dict(resp.getheaders())` semantics exactly — no comma-joining); test stubs are
plain HTTP, so the truststore move is invisible to the suite.

## Summary

**Problem** (from the adopted deferral `defer-issue-httpx2-native-sse-transport`,
2026-09-27): server.py hand-rolls the upstream HTTP transport
(`http.client.HTTPConnection`) and the SSE read loops reach into http.client
internals (`resp.read1`, `resp.fp.raw._sock`, `IncompleteRead`/`RemoteDisconnected`).
httpx2 — the Pydantic-maintained continuation of httpx, the only candidate that
survived the user's 2026-09-27 supply-chain filters — provides the modern
transport. The migration was deferred because it is not drop-in.

**Approach:** one client per retry chain (`trust_env=False`,
`timeout=httpx2.Timeout(SETTINGS.read_timeout)`, `follow_redirects=False`),
`client.stream(content=<prebuilt bytes>)` inside the existing epoch-checked retry
loop; `Accept-Encoding: identity` pinned as defence-in-depth, with every read site
using `iter_raw()` so bytes are byte-faithful BY CONSTRUCTION regardless of
upstream Content-Encoding behavior; ONE raw iterator per response serving all
read phases (single-consumption rule); exceptions map to a total tuple
`(httpx2.RequestError, httpx2.StreamError, OSError)` (RequestError covers
TransportError AND DecodingError; StreamError covers stream-state misuse; OSError
is retained so today's documented client-write residual — a write error outside
`_DISCONNECT_ERRORS` being read as a connection error — is preserved verbatim);
the response object type changes and every upstream read site follows. The
chat-mode frame-cap guard changes disposition from degrade/silent-drop to a loud
terminal error pre-finish; the post-finish drain window keeps a trace-visible
drop (the turn is already terminal-signaled — failing it would force a full
re-run for data the client never needed).

**User decisions recorded 2026-11-15 (Phase 3):**
1. Tenacity: rejected-for-good — the retry loop's complexity is the swap/epoch
   protocol, not backoff math; the dependency fails the four-goal test.
2. `PROXY_READ_TIMEOUT` env var, default 120 s (range 10–600) — 10× the worst TTFT
   the real 5-day trace recorded (11.4 s; p99 first byte 912 ms; zero gaps >30 s).
3. Swap-wake: accept the ≤ read-timeout residual unconditionally — no httpcore2
   internals coupling; the 30 s armed wake dies with `fp.raw._sock`.
4. Chat-mode frame cap: raise 64 KB → 2 MB and error out loud (Anthropic envelope,
   no terminal sequence, retryable turn) instead of raw-splice/silent-drop; frame
   size recorded in the trace event. Audit-scoped extensions of this decision:
   the loud error applies PRE-finish only — a drain-window (post-finish) oversize
   frame keeps a drop-and-continue disposition, now trace-visible via
   `chat_sse_frame_oversize` with its size (the turn already has its terminal
   signal); the anthropic-mode `sse_buffer_cap_exceeded` event gains the same
   `bytes` field (completing what decision 4 asked — "do we record the frame
   size?" — across both modes); `frame_dropped` survives as a trace field with a
   narrowed meaning (drain-window drops only), so the harness's fixed key set is
   untouched; the drain's 64 KB byte-budget crossing keeps its existing
   trace-visible discard (`drain_exit: "byte_budget"` — post-finish data,
   best-effort drain by design, recorded here so the disposition is explicit).

**Engineering defaults applied (review at presentation):** `trust_env=False`
(ambient HTTP_PROXY/.netrc must not silently reroute upstream calls; the accepted
cost: `SSL_CERT_FILE`/`SSL_CERT_DIR` ambient CA overrides are ignored — documented
delta for custom-CA operators); per-chain Client lifetime (cookie isolation;
pooling within a retry chain only — an upgrade, cross-request statelessness
preserved); identity accept-encoding pin (defence-in-depth; iter_raw carries the
correctness); uniform `Timeout(SETTINGS.read_timeout)`; UA/truststore wire deltas
accepted and documented (harmless); header forwarding via `Headers.raw` mapping
preserving today's exact casing and last-wins duplicate semantics.

**Alternatives rejected:** tenacity adoption (see decision 1); watchdog-thread
wake (cross-thread socket interruption unreliable on Windows); httpcore2 internals
probe for per-read timeouts (decision 3 — no internals coupling); request-level
`client.sse()` (cannot own the request without re-plumbing retry/status/epoch out
of `_forward_core`); `iter_bytes()` at read sites (decodes per response headers —
audited corruption path); `dict(resp.headers)` for header mapping (lowercases
keys and comma-joins duplicates — audited); `Headers.multi_items()` forwarding
(would CHANGE duplicate semantics from today's last-wins).

**Out of scope:** the client-facing server and its headers; all body transforms;
the compat learner; the anthropic-mode first-event cap's degrade disposition
(forward-as-is stays; only its trace event gains the `bytes` field); the
tool-args placeholder degradation; buffered-path size caps; the admin surface;
`config.py`/`keys.py` (RESERVED_EXTRA_HEADER_NAMES already reserves
`accept-encoding` and `cookie` — no change needed there).

**Architecture note:** the deferral's headline ("client.sse() replaces the
hand-rolled scanner") does not survive contact with the library: `client.sse()`
is request-level (the proxy deliberately splits transport+retry from response
transformation), and even the response-bound `EventSource(response,
max_event_size=...)` the audit found is unusable here — it drops an EOF-stranded
`[DONE]` sentinel a permanent test pins, iterates a decoder-installing path
(`iter_text`), and yields nothing for comment-only/keepalive frames (breaking
activity tracking) — issue `eventsource-eof-sentinel-drop`. The scanner stays on
the iter_raw port with the new frame-cap disposition; the deferral's
parser-replacement goal is recorded as architecturally inapplicable, and the
transport migration delivers its substance. The deferral's four checklist items
resolve as: (1) accept-encoding → identity pin as defence, iter_raw as the
guarantee (correction recorded: http.client sends `identity` today via
`putrequest`, not "none"); (2) 5 s default timeout → explicit
`Timeout(SETTINGS.read_timeout)`; (3) per-retry reconnect → per-chain pooled
client (attempt isolation now by pool lifecycle, not fresh sockets); (4) CRLF/
[DONE]/auto-reconnect → scanner semantics unchanged (CRLF normalize + sentinel
check stay; auto-reconnect does not exist and must not be introduced).

## Repo Mode

Public

*Detected at plan creation. Determines: plan archival path, commit-message content, staged files.*

## Document Overrides

If the plan intentionally contradicts a documented rule (in `CLAUDE.md` or `doc/*`), declare the override here. An empty or absent table means zero tolerance — every documented rule is in force.

| Document | Rule Overridden | Reason |
|----------|----------------|--------|

## Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| httpx2 exception surface wider than TransportError (DecodingError, StreamError, InvalidURL) | a misclassified or uncaught error skips a retry, mislabels a give-up, or aborts the request with no response (do_POST has no outer try) | total tuple `(httpx2.RequestError, httpx2.StreamError, OSError)` at the retry loop and every read-loop wrapper; pre-check pins the installed hierarchy BEFORE wiring; iter_raw removes the decoder (and DecodingError) from read paths entirely; e2e connection-error tests assert the retry trace event and 502 envelope |
| Attempt isolation moves from fresh-socket-per-attempt to pooled reuse | a poisoned kept-alive connection could affect the next retry attempt | httpx2/httpcore2 discards connections on transport errors by design (coder notes the evidence in the report); retry e2e tests exercise reset-mid-response |
| Streaming read loops change chunk-source semantics (read1/read → iter_raw) | SSE frame assembly regressions (delimiter spanning, truncation, double-consumption) | one iterator per response created once and shared across phases (StreamConsumed audited); logic is boundary-agnostic (buffer-until-delimiter); the ~35 chat-SSE e2e tests and the streaming tests run unchanged against the new source |
| Swap-wake residual (≤ read timeout, was 30 s armed) | a silent in-flight stream delays a swap's straggler eviction | accepted by decision 3; documented in code docstring, doc/architecture.html, and CLAUDE.md Gotchas pointer; named swap tests re-based by the tester |
| Post-finish silent provider holds the worker up to PROXY_READ_TIMEOUT (was 5 s pin) | normal-path latency residual on chat turns lacking [DONE]-or-EOF right after finish_reason | accepted and made measurable: `drain_exit == "read_timeout"` distinguishes it in the trace; the per-chunk MAX_DRAIN_SECONDS check survives for chatty drains; documented in provider-modes.html and CLAUDE.md |
| Frame-cap disposition change alters observable client behavior | existing clients relying on raw-splice degrade (none known) | new tests pin the error-out-loud envelope pre-finish and the drop-and-complete drain window; the superseded test is retired per the Guidance for Tester |
| Cookie/UA/truststore/trust_env wire deltas | provider-side surprises (cookie replay, UA strings, CA source, lost ambient CA override) | neutralized or accepted explicitly (per-chain client, documented deltas); wire-delta awareness block directs the tester to scan existing assertions |

## Rollback

- **Revert set:** the change is confined to `src/claude_retry_proxy/server.py`,
  `src/claude_retry_proxy/settings.py`, `pyproject.toml` (plus tests and docs).
  No persisted-schema changes: the trace log, state file, compat file, config,
  models, and keys formats are untouched (one trace event renamed, one field
  added — old traces remain readable). Revert order: `git revert` the plan's
  single commit; `pip install -e .` restores the pre-plan environment
  (`httpx2` may remain installed — harmless; nothing else imports it).
- **Abort condition (pre-check):** if the Step 3 pre-check shows the installed
  httpx2 diverges from the pinned facts (missing `RequestError`/`StreamError`/
  `EventSource` at `>=2.13.1`, or `Headers.raw`/`iter_raw` semantics differing),
  STOP before editing server.py and surface the divergence to the planner — the
  plan revises rather than improvising around the library.
- **Version/upgrade note:** `version` bumps 0.2.0 → 0.3.0 (Step 2) because the
  release drops Python 3.8/3.9 and adds a mandatory runtime dependency — both
  user-visible breaking changes for installers; README states the new floor.

## Proposed Changes

Each step includes verification checks tagged with confidence. `(auto)` = mechanical,
coder self-verifies. Every step must have at least one verification check executable
by its owner (coder steps: coder checks; tester steps: tester verify; planner steps:
Evidence). Steps use this numbered-list format exactly.

1. **Step 1: settings.py — add `PROXY_READ_TIMEOUT`**
   In `ProxySettings.__init__` (src/claude_retry_proxy/settings.py), immediately
   after the `max_response_size` line (settings.py:51), add:
   ```python
   self.read_timeout = _env_int("PROXY_READ_TIMEOUT", 120, 10, 600)
   ```
   Rationale (user decision 2026-11-15): the hardcoded 300 s stall timeout becomes
   configurable; default 120 s — 10× the worst first-byte latency the 5-day trace
   ever recorded (11.4 s, n=5424); range 10–600 s; blank/invalid/out-of-range →
   default (the `_env_int` convention, no separate kill switch). Values below 10
   are refused by design; the tester's stall tests pin exactly 10.
   → coder verify (auto): `SETTINGS.read_timeout` is 120 with the env var unset;
   `PROXY_READ_TIMEOUT=30` yields 30; `PROXY_READ_TIMEOUT=5`, `=abc`, `=900`, and
   unset all yield 120 (set env per-case in a fresh interpreter).

2. **Step 2: pyproject.toml — dependency, Python floor, version bump**
   - `requires-python = ">=3.8"` → `">=3.10"` (pyproject.toml:12).
   - Delete the `Programming Language :: Python :: 3.8` and `:: 3.9` classifiers
     (pyproject.toml:21-22); keep 3.10+.
   - `dependencies = ["cryptography>=38.0",]` → `dependencies = ["cryptography>=38.0", "httpx2>=2.13.1"]`
     (pyproject.toml:31-33). The floor is the version the mega-audit verified
     empirically in this environment (installed 2.13.1: `EventSource(response,
     max_event_size=...)`, `Headers.raw`, `iter_raw`, the exception hierarchy all
     probed); no earlier release is claimed or relied on.
   - `version = "0.2.0"` → `"0.3.0"` (breaking: Python floor, new mandatory
     dependency — see Rollback).
   → coder verify (auto): grep shows `requires-python = ">=3.10"`, no `:: 3.9` or
   `:: 3.8` classifier, `httpx2>=2.13.1` in dependencies, `version = "0.3.0"`;
   `pip install -e .` succeeds; `python -c "import httpx2; print(httpx2.__version__)"`
   prints ≥ 2.13.1.

3. **Step 3: server.py — `_forward_core` transport swap**
   - Add `import httpx2` to the imports (server.py:17 area); `import http.client`
     is removed in Step 6, not here (stream code still cites it until Step 4/5/6).
   - Run the **coder pre-check** above; wire exception names from what the installed
     source shows. Record the hierarchy in the session report.
   - Delete the per-attempt connection setup (`conn = http.client.HTTPSConnection(host, port, timeout=300)` /
     `HTTPConnection(...)`, server.py:1559-1561) and every `conn.close()`.
   - Replace with ONE client per `_forward_core` call, created before the retry loop
     and closed in a `finally`:
     ```python
     client = httpx2.Client(
         base_url="{}://{}:{}".format("https" if use_ssl else "http", host, port),
         timeout=httpx2.Timeout(SETTINGS.read_timeout),
         trust_env=False,
         follow_redirects=False,
     )
     ```
     Per attempt, inside the loop, open the response with a stream context whose
     body encloses the whole existing branch tree, so every exit path (retry
     `continue`, give-up return, SSE dispatch, buffered return, exception) releases
     the response:
     ```python
     with client.stream(method, upstream_path, content=rewritten_body,
                        headers=fwd_headers) as resp:
         # existing branch tree, ported per the mappings below
     ```
     Constraints: `content=rewritten_body` — never `json=` (the body is pre-built
     bytes; the outgoing body is built once before the loop and never re-transformed,
     per the existing doctrine — compat retries re-enter from the client body and are
     unaffected). The per-chain Client means retry attempts reuse one pooled
     connection (an upgrade over today's fresh-connection-per-attempt) while
     cross-request state stays isolated: trust_env=False (no ambient proxy/.netrc;
     the accepted cost — ambient `SSL_CERT_FILE`/`SSL_CERT_DIR` CA overrides are
     ignored — is a documented wire delta), per-request-chain lifetime (cookies
     cannot accumulate across proxied requests — the Client dies with the chain),
     no limits config needed (one connection in flight per client; PoolTimeout
     unreachable).
   - Mechanical mappings across the loop and its callees — the read primitive is
     `iter_raw()` everywhere (byte-faithful by construction; no decoder installed;
     `iter_bytes()` is NOT used at any site):
     - `resp.status` → `resp.status_code` (retry checks, give-up returns, dispatch).
     - `resp_headers = dict(resp.getheaders())` → 
       `resp_headers = {k.decode("latin-1"): v.decode("latin-1") for k, v in resp.headers.raw}`
       — audited: `dict(resp.headers)` lowercases keys and comma-joins duplicates,
       which would blank every `resp_headers.get("Content-Type", "")` dispatch
       (server.py:1644, :2231) and change forwarded header casing; the `.raw`
       mapping reproduces today's `dict(resp.getheaders())` exactly (received
       casing; last-wins duplicates).
     - Request-header encoding (issue `upstream-header-value-encoding`, already
       implemented in the tree): httpx2 encodes `str` header values as ASCII and
       h11 refuses NUL, interior CR/LF/FF/VT, and leading/trailing whitespace —
       values the stdlib transport forwarded verbatim; a bare `LocalProtocolError`
       would surface as a `RequestError` and be retried as a connection error.
       The mapping: pass forwarded headers as pre-encoded latin-1 bytes —
       `headers={k.encode("latin-1"): _upstream_header_value(v).encode("latin-1") ...}`
       in the `client.stream(...)` call — where `_upstream_header_value`
       normalizes a value into h11's field-value shape (strip edge whitespace);
       a value outside latin-1 still raises, exactly as the stdlib transport did
       (documented residual, not a new failure mode).
     - The 429/503 retry-path drain (server.py:1592-1595): KEEP `resp.read()` (it
       exists on httpx2, now bounded by the client read timeout instead of the
       socket timeout) and port its inner arm `except (socket.error, OSError): pass`
       → `except (httpx2.RequestError, OSError): pass` — preserving today's
       tolerate-drain-failure-and-retry-as-429/503 semantics (an unmapped arm would
       let the failure escape to the outer handler and mislabel the retry).
     - Buffered chunk loops (`resp.read(8192)` / `resp.read(min(8192, ...))`) →
       ONE iterator per response: `chunks = resp.iter_raw()` created once,
       consumed by a `for chunk in chunks:` loop — the loop body (size cap,
       first-byte timing, `_touch_upstream_activity()`) stays; `if not chunk:
       break` lines disappear (the iterator ends normally at EOF).
       NO chunk_size argument (issue `iter-raw-chunk-coalescing`): httpx2 passes
       chunk_size to ByteChunker, which ACCUMULATES until that many bytes before
       yielding — any value >1 buffers small/slow streams (8 KiB-delivered SSE
       frames, first byte after completion). Bare `iter_raw()` yields as bytes
       arrive, preserving streaming.
       CAP INSIDE THE LOOP (issue `buffered-size-cap-single-chunk`): iter_raw
       yields WIRE-SIZED chunks, so a body arriving in one chunk can exceed
       `SETTINGS.max_response_size` wholesale — the old append-then-test shape
       (safe under `read(8192)`, whose chunks were ≤8192) would return the
       cap-busting body whole. At EVERY buffered site, append the SLICED chunk —
       `take = chunk[:SETTINGS.max_response_size - total]` — set the truncation
       flag when `len(chunk) > len(take)`, and break: restoring the
       never-overshoot guarantee (the `_read_capped` pattern) at every buffered
       site — THREE in the tree (server.py:1714, :1774, :1828; issue
       `buffered-size-cap-four-sites-miscount`: the fourth range originally
       cited here is the SSE fallback drain, which deliberately carries no size
       cap — do not add one).
     - `_read_capped` (server.py:694-740) — restructure to a SINGLE loop with a
       discard flag (two loops would need two iterators, and `StreamConsumed`
       forbids that): iterate `resp.iter_raw()` once; take
       `chunk[:max_bytes - total]` while under the cap (preserving the exact
       never-overshoot truncation guarantee of today's `resp.read(min(8192,
       max_bytes - total))`), then flip to discard mode (`truncated = True` on any
       further chunk, chunks discarded); `resp.status` → `resp.status_code`; the
       `except OSError: pass` arms → `except (httpx2.RequestError, OSError): pass`
       (same catch-and-continue shape — preserve today's semantics exactly,
       including the quirk that a mid-body transport error returns the partial
       prefix labeled complete).
   - Exception mapping in the retry loop: `except (socket.error, ConnectionError, OSError) as e:`
     → `except (httpx2.RequestError, httpx2.StreamError, OSError) as e:` — the body
     is unchanged (abandon-at-press via `_swap_chain_abort` + `_interruptible_sleep`,
     `compute_delay(attempt)` jittered delay, retry trace event with
     `reason: "connection_error"` and `sanitize_error(str(e))`, exhaustion → 502
     `_error_body("api_error", "upstream_unreachable", ...)`, post-loop fallthrough
     `(last_status or 502)`). Totality rationale: `RequestError` covers
     `TransportError` (timeouts, resets) AND `DecodingError`; `StreamError` covers
     stream-state misuse (`StreamConsumed`, `StreamClosed`); `OSError` is RETAINED
     so today's documented client-write residual (an OSError outside
     `_DISCONNECT_ERRORS` during a streamed response being caught by the retry
     loop) is preserved verbatim — httpx2 exceptions do not inherit OSError, so
     the tuple members are disjoint and the documented behavior needs no rewrite.
     The per-read 300 s socket timeout becomes the
     `httpx2.Timeout(SETTINGS.read_timeout)` set on the client
     (connect/read/write/pool uniformly — the closest equivalent of today's single
     socket timeout).
   - Accept-encoding pin (defence-in-depth): in `_forward_request_impl`'s header
     assembly, immediately after the extra-headers loop (server.py:1368-1370), add:
     ```python
     # httpx2 would send its own accept-encoding set by default; identity is
     # pinned as defence-in-depth. Correctness does not rest on it: read sites
     # use iter_raw(), which is byte-faithful regardless of the response's
     # Content-Encoding. Config cannot override the pin:
     # RESERVED_EXTRA_HEADER_NAMES reserves the name.
     fwd_headers["Accept-Encoding"] = "identity"
     ```
     (Correction to the deferral record: today http.client *does* send
     `Accept-Encoding: identity` from `putrequest` — FORWARD_HEADERS excludes the
     name, so the stdlib default stood; the pin preserves that wire state, it
     does not introduce it.)
   - Everything else in the loop is preserved verbatim: epoch checkpoints (loop
     head, post-headers "pre_first_byte", post-buffer), the 429/503 delay policy
     (429 → `compute_jittered_delay(SETTINGS.max_delay)`, 503 → `compute_jittered_delay(compute_delay(attempt))`),
     retry accounting and trace events, `_touch_upstream_activity()` call sites,
     the post-buffer eviction, the dispatch tree, and the 9-tuple return shape.
   → coder verify (auto): the pre-check's recorded hierarchy names every class the
     `except` tuples use; `grep -n "HTTPConnection\|HTTPSConnection\|conn\.close" src/claude_retry_proxy/server.py`
     returns empty; `grep -n "Accept-Encoding" src/claude_retry_proxy/server.py`
     shows the pin after the extra-headers loop; the retry-loop except tuple is
     `(httpx2.RequestError, httpx2.StreamError, OSError)`; no `socket.error`-only
     arm remains inside `_forward_core` (grep `socket\.error` in the function
     returns empty); bare `resp.read()` sites inventoried — exactly one (the
     429/503 drain) with the RequestError arm; all three epoch checkpoints remain
     (grep `_swap_epoch_changed` in `_forward_core` shows ≥3 sites); the 9-tuple
     return shape is unchanged (grep `provider_name, actual_model)` return sites);
     the header mapping is the `.raw` comprehension (grep `headers\.raw`).

4. **Step 4: server.py — stream-layer read-loop rework (`_stream_upstream_response`; `_read_capped` done in Step 3)**
   - Delete the timeout-arming machinery in `_stream_upstream_response`:
     `_orig_timeout`/`_timeout_saved` capture (server.py:2172-2178),
     `arm_stream_timeout()` (2180-2195), `restore_stream_timeout()` (2197-2202),
     and every call site. This is the accepted residual (user decision
     2026-11-15): httpx2 has no public mid-stream timeout API and the plan does
     not touch httpcore2 internals. Documented behavior after this plan: a
     no-swap stream's stall tolerance is `PROXY_READ_TIMEOUT` (was 300 s); a
     stream silent at a swap press wakes at its next read boundary (≤ read
     timeout) and dies retryably (was ≤ 30 s armed wake).
   - The three `resp.read1(8192)` loops (first-event scan server.py:2263-2299,
     remainder 2332-2349, passthrough) → ONE iterator per response created at the
     top of the response handling: `chunks = resp.iter_raw()` — the
     first-event loop and the remainder loop consume THE SAME iterator in
     sequence (creating a second iterator raises `StreamConsumed` — audited);
     the passthrough site creates its own where it is the sole consumer. Each
     loop is wrapped in `try:` / `except (httpx2.RequestError, httpx2.StreamError, OSError):`
     with the per-branch semantics preserved:
     - the `socket.timeout` arm becomes an `httpx2.ReadTimeout` check: swap-owning
       wake (`_config_swapping or _swap_epoch_changed(epoch)`) → `evict_stream()`
       + return, else end the loop (today's stall cut);
     - the `(IncompleteRead, RemoteDisconnected, socket.error, OSError)` arm → any
       other exception from the tuple → end the loop (upstream cut). OSError is
       retained for client-write parity (same rationale as Step 3).
     `evict_stream()` itself is client-facing and unchanged.
   - The anthropic-mode first-event machinery keeps its logic UNCHANGED:
     `MAX_FIRST_EVENT_BUFFER` 64 KB cap, `rewrite_skipped` degrade (forward-as-is
     without the model rewrite — benign there: the bytes are already
     Anthropic-format), the `sse_buffer_cap_exceeded` event — WHICH GAINS the
     `"bytes": len(first_event_buffer)` field (audit extension of decision 4: the
     user asked for the size to be traced; it costs one integer and completes the
     same rationale across both modes), and the `_rewrite_sse_first_event` call.
   - Update the docstring: replace the socket-arming paragraphs with the residual
     note above; the "documented 300 s stall tolerance" wording becomes
     `PROXY_READ_TIMEOUT` wording.
   → coder verify (auto): `grep -n "fp\.raw\|arm_stream_timeout\|restore_stream_timeout\|iter_bytes" src/claude_retry_proxy/server.py`
     returns empty; the first-event block still contains `MAX_FIRST_EVENT_BUFFER`
     and `sse_buffer_cap_exceeded` (now with a `bytes` field); exactly ONE
     `iter_raw` iterator is created per response in the SSE path (the first-event
     and remainder loops share it); both loops' exception handlers keep the
     swap-evict check on the ReadTimeout branch.

5. **Step 5: server.py — chat-mode frame-cap disposition + SSE parser adoption**
   - **(a) Frame-cap disposition (user decision 2026-11-15 — behavior change,
     audit-refined):** `MAX_EVENT_BUFFER` 64 KB → 2 MB (server.py:2480, keep it a
     local constant, not config). The cap guard is reachable in BOTH loop phases,
     and the dispositions differ by phase:
     - **Pre-finish trip** (`finish_reason_seen is None`): stop translating and
       terminate the stream with the loud error, mirroring the existing cut-stream
       close shape (server.py:3345-3356) — ordering matters:
       `close_all_blocks()` → `log_degradation_if_needed()` → trace event →
       error frame → `return first_byte_ms` (the return bypasses the post-loop
       terminal/EOF paths, so no `message_delta`/`message_stop` and no second
       error event can follow):
       ```python
       log_trace({..., "event": "chat_sse_frame_oversize", "bytes": len(buf), ...})
       # plus the chat_sse_truncated invariant event, exactly as the pre-finish
       # branch of evict_swap logs it, so "every 200 chat stream ends with
       # exactly one of chat_sse_drain / chat_sse_truncated" still holds
       self.wfile.write(b"event: error\ndata: " + _error_body(
           "api_error", "upstream_frame_oversize",
           "upstream sent an SSE frame larger than 2 MB; stream terminated",
           request_id) + b"\n\n")
       self.wfile.flush()
       return first_byte_ms
       ```
     - **Drain-window trip** (`finish_reason_seen` set): the turn is already
       terminal-signaled — failing it would force a full client re-run for data
       the client never needed. KEEP a drop-and-continue here: drop the frame
       (`buf.clear()`), log `chat_sse_frame_oversize` with `"bytes": len(buf)`,
       increment `frame_dropped`, and continue the drain. The pre-finish
       silent-drop path stops existing; the drain-window drop becomes
       trace-visible (today's `chat_sse_frame_cap_exceeded` carried the size but
       only for this tier; one event now covers both phases).
     - **`frame_dropped` disposition:** the variable and the
       `chat_sse_tool_degradation` field SURVIVE with a narrowed meaning — set
       only by the drain-window drop (tests/_harness.py's fixed key set is
       untouched; doc/trace-log.html notes the narrowed meaning).
     - **Deletion inventory (complete):** the `buf = None` raw-forwarding branch
       (server.py:3123-3132, the assignment at 3198) — silent OpenAI-format raw
       splice stops existing; the pre-finish drop-and-continue path
       (3206-3207); the chat scanner's own timeout machinery — capture
       (2525-2531), pre-finish arm (3054-3060), per-chunk drain re-pin
       (3115-3120), restore (3215-3223), `drain_pin()` (2911-2925) and the
       finish re-pin (3160-3165); and the now-dead `buf is not None` checks
       (2898, 3318) — `buf` is never None after this step, so those guards are
       removed with the branch they guarded.
     - **Drain bounds after the change:** the per-chunk `MAX_DRAIN_SECONDS`
       remaining-budget check (3105-3111) SURVIVES — a chatty drain is still cut
       at 5 wall-clock seconds (`drain_exit: "time_budget"`); `MAX_DRAIN_BYTES`
       keeps its existing trace-visible discard (`drain_exit: "byte_budget"` —
       post-finish data, best-effort drain by design, decision recorded in the
       Summary); a SILENT drain (no chunks arriving) is bounded by the request
       read timeout — its exit gets a NEW `drain_exit` value `"read_timeout"`,
       and other in-drain exceptions keep the existing `"read_error"` label;
       both then fall through to the existing post-loop terminal synthesis (the
       turn completes with the normal `message_delta`/`message_stop` — today's
       shape for a mid-drain read failure).
     - **Drain accounting is per-FRAME, not per-chunk (issue
       `drain-byte-budget-chunk-granularity`):** charging `drain_bytes +=
       len(chunk)` only when a chunk's HEAD is already in drain mode under-counts
       the coalesced iter_raw chunks — frames that follow finish_reason INSIDE
       the same raw chunk escape both the 64 KB byte budget and the 5 s check.
       Account drain bytes from the FRAMES parsed after finish_reason within a
       chunk (split the chunk at the finish frame and charge the remainder, or
       accumulate per-frame sizes as the delimiter loop releases them), and
       apply the same fix to the `remaining` time-budget computation so both
       bounds see exactly the post-finish bytes.
   - **(b) SSE parser decision — RESOLVED: scanner retained (issue
     `eventsource-eof-sentinel-drop`):** the pre-check found `EventSource`
     response-bound parsing exists but is UNUSABLE here, on three evidence-backed
     limits: (a) it never yields a final event for a `data: [DONE]` sentinel
     that lacks the trailing blank line when the stream ends — breaking the
     documented stranded-sentinel disposition and a permanent test;
     (b) it iterates `response.iter_text()` — a decoder-installing path keyed on
     the response's Content-Encoding, contradicting the plan's iter_raw
     byte-faithfulness invariant; (c) it yields nothing for comment-only or
     keepalive frames, so `_touch_upstream_activity()` would stop tracking
     received bytes in the 200 chat path. The scanner STAYS — the iter_raw port
     from Step 4, the new disposition from (a), and the `[DONE]`/EOF semantics
     untouched (the tree already reflects this; no EventSource reference may
     appear in server.py). The deferral's parser-replacement goal is recorded as
     architecturally inapplicable with these three limits as the evidence; the
     transport migration delivers its substance. Deferral checklist item 4
     resolves as: CRLF normalize + sentinel check stay in the scanner;
     auto-reconnect does not exist and must not be introduced.
   → coder verify (auto): `grep -n "chat_sse_buffer_cap_exceeded\|chat_sse_frame_cap_exceeded\|drain_pin\|MAX_EVENT_BUFFER = 64" src/claude_retry_proxy/server.py`
     returns empty; `grep -n "upstream_frame_oversize" src/claude_retry_proxy/server.py`
     shows the error emission and the trace event with a `bytes` field;
     `grep -n "_timeout_saved\|_orig_timeout\|fp\.raw" src/claude_retry_proxy/server.py`
     returns empty (all chat-scanner copies included);
     `grep -n "buf is not None" src/claude_retry_proxy/server.py` returns empty;
     `grep -n "EventSource" src/claude_retry_proxy/server.py` returns empty;
     `MAX_DRAIN_SECONDS` still present (per-chunk check survives); a
     `drain_exit` assignment for `"read_timeout"` exists; the scanner-retention
     decision and EventSource's three limits (with installed-source evidence)
     are stated in the session report.

6. **Step 6: server.py — remaining read sites, cleanup, docstrings**
   - `_stream_response_sse_fallback` (server.py:3358-3411): `resp.read1(8192)` →
     `resp.iter_raw()` (single loop, single iterator, no chunk_size);
     `except (http.client.IncompleteRead, http.client.RemoteDisconnected, socket.error, OSError)`
     → `except (httpx2.RequestError, httpx2.StreamError, OSError)`; the epoch
     check and synthesized terminal sequence stay.
   - Remove `import http.client` (server.py:17); update the module docstring
     dependency statement (server.py:11) to name `httpx2` instead of `http.client`.
   - Reword the server.py:2238 comment ("http.client already de-chunked...") to
     the httpx2 fact: read sites use iter_raw, which delivers the entity bytes
     verbatim regardless of the response's Content-Encoding; transfer framing is
     handled by the library. Touch up the `_client_user_agent` docstring's
     http.client-mention (server.py:1009) only where it names the sending
     mechanism — the mirror logic itself is unchanged (fwd_headers is still a
     plain dict; last-value-wins semantics preserved).
   → coder verify (auto): `grep -n "http\.client\|read1(\|iter_bytes" src/claude_retry_proxy/server.py`
     returns empty; `python -c "import claude_retry_proxy.server"` succeeds;
     `python tests/test_claude_proxy.py` runs (full-suite result is the tester's to
     interpret, but the import and suite must at least execute).

7. **Step 7: server.py — do_POST outer exception guard (issue
   `do-post-no-outer-exception-guard`)** — NOT yet in the tree; the only
   remaining code work.
   The `forward_request(...)` call in `do_POST` (server.py:4056-4059) is
   unguarded: any exception outside the retry loop's tuple — e.g. a
   non-`RequestError`, non-`StreamError`, non-`OSError` httpx2 type such as
   `InvalidURL` — closes the connection with NO HTTP response and no trace
   entry. Wrap the call in a total guard that returns the proxy's envelope and
   leaves a record:
   ```python
   try:
       status, resp_headers, resp_body, first_byte_ms, total_sec, retries, \
           tier, provider, actual_model = forward_request(...)
   except Exception as e:  # total: no request may end with a closed
                           # connection and no record (do_POST has no outer try)
       print("[proxy] forward failed, rid={}: {}".format(request_id,
               sanitize_error(str(e))), file=sys.stderr)
       log_trace({... "event": "forward_failed", "request_id": request_id,
                  "error": sanitize_error(str(e)), "path": self.path ...})
       status = 502
       resp_headers = {}
       resp_body = _error_body("api_error", "upstream_unreachable",
                               "upstream: internal forwarding failure", request_id)
       first_byte_ms = None
       total_sec = 0.0
       retries = 0
       tier = provider = actual_model = None
   ```
   ALL NINE tuple members must be bound in the except body (issue
   `step7-code-block-unbound-tuple-members`): do_POST's trace entry below the
   call reads `tier`, `provider`, `actual_model`, `retries`, and `total_sec`
   too — binding only the first four raises NameError on the very path the
   guard protects. This closes the pre-existing structural gap the transport
   swap makes easier to hit; it does not change any happy-path behavior.
   While in the file (issue `forward-request-docstring-tuple-arity`):
   `forward_request`'s docstring documents an 8-tuple return while every site
   yields 9 — append `, actual_model` to the docstring's return description
   (one-line edit, server.py:772).
   → coder verify (auto): the `forward_request(` call site in `do_POST` is
   enclosed in `try`/`except Exception` binding all nine names and returning
   the 502 envelope; a `forward_failed` trace event exists; the docstring's
   return tuple names nine members; `python -c "import claude_retry_proxy.server"`
   succeeds.

8. **Step 8: review-Warning fixes (three small defects from the Phase 6
   review, [report](./tmp/reports/2026-11-15-httpx2-transport-sse-review-2026-11-15.json))**
   - **IPv6-literal base_url (Warning, server.py:1584):** `parse_upstream`
     yields the bare host, so an IPv6 provider URL (`http://[::1]:8080/v1`)
     produces `base_url="http://::1:8080"` and httpx2 raises `InvalidURL` at
     Client construction — every request to such a provider is a 502 with no
     upstream attempt (the old transport accepted the bare host). Bracket the
     host when it contains a colon:
     ```python
     # urlparse strips the brackets from an IPv6 authority; httpx2's
     # base_url requires them back (an unbracketed literal reads as an
     # invalid port).
     host_part = "[{}]".format(host) if ":" in host else host
     ```
     and build `base_url` from `host_part`.
   - **Bounded, non-decoding 429/503 drain (Warning, server.py:1641):**
     `Response.read()` now decodes (`b"".join(iter_bytes())`), so an error
     body that ignores the identity pin decompresses wholly, uncapped, into
     worker memory on every retry. Replace the bare `resp.read()` drain with
     a bounded raw discard loop inside the existing `try` arm:
     ```python
     drained = 0
     for chunk in resp.iter_raw():
         drained += len(chunk)
         if drained > SETTINGS.max_body_size:
             break
     ```
     keeping the `except (httpx2.RequestError, OSError): pass` arm unchanged
     (bounded in bytes by the body cap, non-decoding by iter_raw).
   - **Stale `__version__` (Warning, src/claude_retry_proxy/__init__.py:1):**
     `__version__ = "0.2.0"` while pyproject is 0.3.0 — bump to `"0.3.0"`.
   → coder verify (auto): `grep -n "host_part" src/claude_retry_proxy/server.py`
     shows the bracketing before the base_url build; the retry-path drain is
     the bounded iter_raw loop (no bare `resp.read()` remains in
     `_forward_core`); `python -c "import claude_retry_proxy; print(claude_retry_proxy.__version__)"`
     prints 0.3.0.

## Guidance for Planner

Documentation tasks you will execute yourself (not the coder):

- **Files to modify:**
  - `./CLAUDE.md` — Purpose line: "Python 3.8+" → "Python 3.10+"; Structure section (server.py line: httpx2 upstream transport, iter_raw read loops, EventSource parsing; settings.py: PROXY_READ_TIMEOUT; pyproject deps + version 0.3.0); env-var table: ADD the `PROXY_READ_TIMEOUT` row, EDIT the `PROXY_SWAP_SILENCE_TIMEOUT` row to drop the "also bounds a streamed read's socket arm while a swap is in progress" clause (keep drain-budget and `budget_s` roles); the "Runtime dependency: cryptography" line (+ httpx2); Architecture "Sinks never raise" bullet: the rationale cites the retry loop's old `(socket.error, ConnectionError, OSError)` clause — restate against the new `(httpx2.RequestError, httpx2.StreamError, OSError)` tuple (the never-raise property itself is unchanged); Gotchas: rewrite the chat-sse-drain moved-out row ("waits up to 5 s" → the post-pin bound: per-chunk 5 s budget for chatty drains, read timeout for silent ones, `drain_exit` records which); update the disconnects residual row if its wording names the old clause; ADD the swap-wake residual Gotchas pointer.
  - `./README.md` — Python ≥ 3.10 requirement; dependency mention (cryptography + httpx2) and version 0.3.0; env table: `PROXY_READ_TIMEOUT` row + drop the socket-arm clause from `PROXY_SWAP_SILENCE_TIMEOUT`; chat-mode streaming overview (449-451): remove the "bounded by a 5-second drain" claim, state the post-pin bounds.
  - `doc/architecture.html` — request path (httpx2 client per chain, identity pin as defence + iter_raw guarantee); retry section (the exception family is now `(httpx2.RequestError, httpx2.StreamError, OSError)` — update every statement naming the old tuple); config-swap section (armed-wake → read-boundary residual); #sinks section (same rationale rewrite as CLAUDE.md); #best-effort-stderr (same); #disconnects (the client-write OSError residual: behavior PRESERVED — OSError stays in the tuple; reword only if the text names the old clause verbatim); size caps (raw-byte caps on iter_raw — unchanged semantics).
  - `doc/provider-modes.html` — SSE sections: stall-tolerance wording (300 s → `PROXY_READ_TIMEOUT`); chat-mode frame-cap disposition (2 MB + pre-finish `upstream_frame_oversize` error / drain-window trace-visible drop; raw-splice and pre-finish silent drop removed); the chat-sse-drain paragraph (424-431): rewrite the time-bound mechanism (the point-of-blocking socket pin is gone; per-chunk 5 s budget survives; silent drains bounded by read timeout; `min(5 s, PROXY_SWAP_SILENCE_TIMEOUT)` wording retired); the event/trace tables: replace `chat_sse_frame_cap_exceeded` + `chat_sse_buffer_cap_exceeded` with `chat_sse_frame_oversize`, and note the narrowed `frame_dropped` meaning; accept-encoding identity pin (defence) + iter_raw (guarantee); pattern-normalization section untouched.
  - `doc/operations.html` — env-var table + prose for `PROXY_READ_TIMEOUT`; `PROXY_SWAP_SILENCE_TIMEOUT` wording if it repeats the socket-arm clause; runtime artifacts unchanged.
  - `doc/configuration.html` — env-var table + prose for `PROXY_READ_TIMEOUT` (+ the SSL_CERT_FILE/DIR-under-trust_env=False delta in the SSL/config prose if present); `PROXY_SWAP_SILENCE_TIMEOUT` socket-arm clause drop; reserved-header note already covers accept-encoding (verify wording).
  - `doc/trace-log.html` — event inventory: `chat_sse_frame_oversize` (with `bytes`) replaces `chat_sse_buffer_cap_exceeded` + `chat_sse_frame_cap_exceeded`; `sse_buffer_cap_exceeded` gains a `bytes` field; `chat_sse_drain`'s `drain_exit` enum: add `"read_timeout"`, keep `"time_budget"` (per-chunk budget) and `"byte_budget"`, note what each now means; `chat_sse_tool_degradation`'s `frame_dropped` field: narrowed meaning; swap_abort's stream phase: remove "or an armed wake".
  - `doc/test-catalog.html` — new/changed tests per the tester's report; rewrite/retire the `test_parse_guard_gate_python38_portable` entry and the Category 13 index row (both cite `requires-python = ">=3.8"`); update the entries describing deleted machinery (test_chat_sse_swap_drain_pin_taken_mid_swap at ~578; test_switch_evicts_silent_stream and test_switch_silent_before_press_is_late_exit at ~678-679).
- **`.claude/mega-audit-files.json`:** no declared list exists in this repo; nothing to update.
- **When:** after coder and tester finish (Phase 6 Step 5 reconciliation).
- **What to sync:** every statement that names `http.client`, the 300 s stall tolerance, `fp.raw._sock` arming, the ≤5 s drain pin, the chat-SSE degrade dispositions, the old retry-loop exception tuple, or the cryptography-only dependency line; server.py's module docstring dependency statement is the coder's (a .py file, Step 6).

## History

One row per event (spec revision / mega-audit / review / implementation round). Conclusion = one-sentence outcome or what changed. Dismissed = compact dismissed-findings list for the reviewer — verbatim issue slugs linked as `[<slug>](<report-path>)`, no prose-only entries (the update-and-commit cross-ref and the reviewer both match these cells verbatim). Link to report files; never restate findings inline.

| Date | Event | Conclusion | Dismissed |
|------|-------|------------|-----------|
| 2026-11-15 | Initial plan | Adopted deferral httpx2-native-sse-transport; four Phase 3 decisions recorded (tenacity rejected; PROXY_READ_TIMEOUT default 120 s; swap-wake residual accepted; frame cap 2 MB + error-out-loud) | — |
| 2026-11-15 | Mega-audit (run 1, pre-implementation) | 81 findings (13H/45M/23L, [report](./tmp/reports/2026-11-15-httpx2-transport-sse-mega-audit-2026-11-15.json)); all 13 High + 45 Medium fixed in revision 2 — headline corrections: iter_raw replaces iter_bytes at every read site (probed decode-on-response-headers corruption), resp.headers.raw for header mapping (probed lowercase+comma-join), response-bound EventSource exists (parser path now primary), total exception tuple (RequestError, StreamError, OSError), one-iterator-per-response (StreamConsumed), drain-window oversize stays a trace-visible drop, floor raised to >=2.13.1 (audit-verified installed version), Rollback section added, tester/doc lists expanded | [23 Low findings acknowledged](./tmp/reports/2026-11-15-httpx2-transport-sse-mega-audit-2026-11-15.json) |
| 2026-11-15 | Implementation round (coder) — failed round; retry used (1) | Round hit the 3600 s launcher wall-clock cap during the full-suite confirmation run (killed mid-run, no `tree not confirmed dead`); implementation was complete in tree with 4 issues filed (iter_raw coalescing, header value encoding, EventSource unusable, do_POST guard); relaunched at 5400 s after revision 3 folded the issues | — |
| 2026-11-15 | Plan revision 3 | Folded the coder's 4 round-1 issues: iter_raw() with no chunk_size (ByteChunker coalescing), latin-1 bytes-headers mapping (already implemented in tree), Step 5(b) resolved to scanner-retained with EventSource's three limits as evidence, new Step 7 do_POST outer guard; drain-window disposition user-confirmed | — |
| 2026-11-15 | Spec revision (/update-plan) | Round 2 completed (build pass, [report](./tmp/reports/2026-11-15-httpx2-transport-sse-coder-2026-11-15.json)); suite 511/522 (9 effective after 2 self-inflicted spawn-isolation fixes): 7 are the plan-listed rework tests, 2 are deterministic new code gaps; revision 4 folds the coder's 4 new issues — buffered sites cap inside the loop (sliced chunk), drain accounting per-frame not per-chunk, Step 7 binds all nine tuple members, forward_request docstring arity — next round is a coder micro-pass, then the tester | — |
| 2026-11-15 | Spec revision (/update-plan) | Coder micro-pass (round 3) completed ([report](./tmp/reports/2026-11-15-httpx2-transport-sse-coder-2026-11-15-2.json)): both code gaps fixed, suite 515/522 — the 7 remaining failures are exactly the plan-listed rework tests; revision 5 adds the coder's wording issue (three buffered sites, not four — the fallback drain carries no cap by design) and hands off to the tester | — |
| 2026-11-15 | Implementation round (tester) — SUCCESS | 528/528 passing, 0 skipped, no blocking failures ([report](./tmp/reports/2026-11-15-httpx2-transport-sse-tester-2026-11-15.json)): 10 permanent tests created, 5 armed-wake/drain-pin tests re-based on the read-boundary residual, 2 superseded tests retired; all 9 code/plan issues and the adopted deferral marked Resolved on this evidence | — |
| 2026-11-15 | Review | Non-blocking: 0 Critical / 3 Warning / 4 Suggestion ([report](./tmp/reports/2026-11-15-httpx2-transport-sse-review-2026-11-15.json)); core mechanics verified correct (tuple totality incl. probed LocalProtocolError, iterator discipline, all 5 epoch checkpoints, both frame-cap phases + trace invariants, nine-name binding, in-loop caps, per-frame drain accounting); the 3 Warnings (IPv6 base_url regression, uncapped decode on the 429/503 drain, stale `__init__.__version__`) are folded as Step 8 in revision 6 rather than dismissed — all are small, live, and one breaks Step 2's deliverable | [sinks-docstring-wording](./tmp/reports/2026-11-15-httpx2-transport-sse-review-2026-11-15.json), [client-user-agent-docstring-inexact](./tmp/reports/2026-11-15-httpx2-transport-sse-review-2026-11-15.json), [do-post-second-response-after-stream-edge](./tmp/reports/2026-11-15-httpx2-transport-sse-review-2026-11-15.json), [path-normalization-and-default-header-wire-deltas](./tmp/reports/2026-11-15-httpx2-transport-sse-review-2026-11-15.json) |
| 2026-11-15 | Spec revision (/update-plan) | Revision 6: review Warnings folded as Step 8 (bracketed IPv6 host_part, bounded non-decoding 429/503 drain, `__version__` 0.3.0), three new permanent tests directed, Suggestions dismissed as linked slugs; next round is a coder micro-pass, then tester verification of Step 8 | — |
| 2026-11-15 | Spec revision (/update-plan) | Coder Step 8 micro-pass (round 4) completed ([report](./tmp/reports/2026-11-15-httpx2-transport-sse-coder-2026-11-15-3.json)): all three Warning fixes implemented and nothing else; revision 7 hands off to the tester for the three Step 8 permanent tests and a full-suite run | — |
| 2026-11-15 | Implementation round (tester) — SUCCESS | 531/531 passing, 0 skipped ([report](./tmp/reports/2026-11-15-httpx2-transport-sse-tester-2026-11-15-2.json)): the three Step 8 permanent tests green and each pins the pre-fix defect behaviorally; all three review Warnings Resolved on this evidence. Implementation and verification complete — planner doc reconciliation next | — |

## Plan Metadata

Fenced ```json block — the machine contract read by `parsePlanContext` (JSON-first, regex fallback). **Update it on every revision** — the rule-enforcer lens files a Medium finding when it is missing, invalid, or out of sync with the prose sections. Field semantics: `steps` = one title per `## Proposed Changes` step (numbering + first phrase; extra prose detail on either side is not a mismatch); `tester_files` = Tests to create + Verification scripts to create + Tests to investigate for retirement (mirrors the fallback's three-marker union); `doc_files` = the planner's `**Files to modify:**` list; `verification_scripts` entries shaped `./tmp/verification/<name>.py`; `retire_inventory` (optional, written at Final Results) = the plan's transient tmp artifacts — evidence reports and verification scripts as repo-relative paths under `./tmp/reports/` or `./tmp/verification/`; the terminal sweep sweeps exactly this record, and anything unrecorded is residue retired only on the user's explicit instruction; `repo_mode` = `Private` or `Public`; `document_overrides` = the `## Document Overrides` rows as formatted strings.

```json
{
  "plan_id": "2026-11-15-httpx2-transport-sse",
  "steps": ["Step 1: settings.py PROXY_READ_TIMEOUT", "Step 2: pyproject dependency, Python floor, version bump", "Step 3: _forward_core transport swap", "Step 4: stream-layer read-loop rework", "Step 5: chat-mode frame-cap disposition and SSE parser adoption", "Step 6: remaining read sites, cleanup, docstrings", "Step 7: do_POST outer exception guard", "Step 8: review-Warning fixes (IPv6 base_url, bounded drain, version)"],
  "coder_files": ["src/claude_retry_proxy/server.py", "src/claude_retry_proxy/settings.py", "pyproject.toml"],
  "tester_files": ["tests/test_settings.py", "tests/test_retry_streaming.py", "tests/test_chat_sse.py", "tests/test_admin.py", "tests/test_parse_guards.py"],
  "doc_files": ["./CLAUDE.md", "./README.md", "doc/architecture.html", "doc/provider-modes.html", "doc/operations.html", "doc/configuration.html", "doc/trace-log.html", "doc/test-catalog.html"],
  "verification_scripts": [],
  "retire_inventory": ["./tmp/reports/2026-11-15-httpx2-transport-sse-mega-audit-2026-11-15.json", "./tmp/reports/2026-11-15-httpx2-transport-sse-coder-2026-11-15.json", "./tmp/reports/2026-11-15-httpx2-transport-sse-coder-2026-11-15-2.json", "./tmp/reports/2026-11-15-httpx2-transport-sse-coder-2026-11-15-3.json", "./tmp/reports/2026-11-15-httpx2-transport-sse-tester-2026-11-15.json", "./tmp/reports/2026-11-15-httpx2-transport-sse-tester-2026-11-15-2.json", "./tmp/reports/2026-11-15-httpx2-transport-sse-review-2026-11-15.json", "./tmp/verification/2026-11-15-httpx2-transport-sse-apply-step3.py", "./tmp/verification/2026-11-15-httpx2-transport-sse-coder-4-suite.py", "./tmp/verification/2026-11-15-httpx2-transport-sse-coder-4-wait.py", "./tmp/verification/2026-11-15-httpx2-transport-sse-header-probe.py", "./tmp/verification/2026-11-15-httpx2-transport-sse-precheck.py", "./tmp/verification/2026-11-15-httpx2-transport-sse-run-suite.py", "./tmp/verification/2026-11-15-httpx2-transport-sse-step1.py", "./tmp/verification/2026-11-15-httpx2-transport-sse-step3-shapes.py", "./tmp/verification/2026-11-15-httpx2-transport-sse-step8.py", "./tmp/verification/2026-11-15-httpx2-transport-sse-tester-2-static.py", "./tmp/verification/2026-11-15-httpx2-transport-sse-tester-2-suite.py", "./tmp/verification/2026-11-15-httpx2-transport-sse-tester-suite.py", "./tmp/verification/2026-11-15-httpx2-transport-sse-wait.py"],
  "repo_mode": "Public",
  "document_overrides": []
}
```

## Audit Accumulation

*Counters reset when mega-audit runs. Used by Phase 5 entry trigger.*

| Counter | Value | Last Updated |
|---------|-------|--------------|
| issues_resolved_since_audit | 0 | 2026-11-15 |
| steps_changed_since_audit | 0 | 2026-11-15 |
| files_changed_since_audit | 0 | 2026-11-15 |

*Counters reset 2026-11-15 after mega-audit run 1 (pre-implementation), before applying revision-2 fixes.*

## Documentation

Consumed from the project docs during planning: doc/architecture.html (retry,
config swap, sinks), doc/provider-modes.html (mode transforms, SSE), doc/
operations.html (CLI, readiness), doc/trace-log.html (entry schema), doc/
test-catalog.html (suite layout, isolation pattern). Post-implementation updates
are listed in Guidance for Planner.

## Final Results

**Status: COMPLETED** (2026-11-15)

**What was built:** the upstream transport of `server.py` migrated from
`http.client` to `httpx2` — one `httpx2.Client` per request chain
(`trust_env=False`, `httpx2.Timeout(PROXY_READ_TIMEOUT)`, bracketed IPv6
`host_part`, `follow_redirects=False`), `iter_raw()`-based read loops at every
site (byte-faithful by construction; `Accept-Encoding: identity` pinned as
defence-in-depth), latin-1 bytes request headers with h11-shape normalization,
a total exception tuple `(httpx2.RequestError, httpx2.StreamError, OSError)`,
`Headers.raw`-based response-header mapping preserving today's casing and
last-wins duplicates, the chat-mode SSE scanner retained (EventSource rejected
on three evidence-backed limits) with the new 2 MB frame-cap disposition
(loud `upstream_frame_oversize` error pre-finish; trace-visible drop-and-count
in the drain window; `frame_dropped` now a count), `drain_exit: "read_timeout"`
added, the anthropic first-event machinery unchanged (its cap event gained
`bytes`), the swap-wake residual accepted and documented (read-boundary wake
≤ `PROXY_READ_TIMEOUT`), and a total do_POST outer guard (`forward_failed`
trace event + 502 envelope). Companion changes: `PROXY_READ_TIMEOUT` env var
(default 120, range 10–600), `pyproject.toml` (`httpx2>=2.13.1`,
`requires-python >=3.10`, version 0.3.0, `__version__` synced), one-line
`forward_request` docstring arity fix.

**Rounds:** coder ×3 (one launcher-cap retry, two micro-passes), tester ×2 —
all SUCCESS at the end. Issue Reports: 13 filed across the rounds, every one
Resolved; the adopted 2026-09-27 deferral `httpx2-native-sse-transport` is
Resolved (its parser-replacement goal recorded as architecturally inapplicable
with evidence; the transport modernization delivered in full).

**Test results:** 531/531 passing, 0 failed, 0 skipped (final tester round);
13 permanent tests created across the plan, 5 re-based on the read-boundary
residual, 2 retired as superseded; spawn-isolation corpus clean.

**Review verdict:** non-blocking — 0 Critical / 3 Warning / 4 Suggestion; the
3 Warnings were fixed as Step 8 and behaviorally pinned by tests that fail on
the pre-fix code; the 4 Suggestions are acknowledged in the History Dismissed
cell.

**Known caveats (cosmetic, non-blocking):** two source docstrings retain
pre-migration wording — `sinks.py:5` cites the old retry-loop clause name and
`server.py`'s `_client_user_agent` docstring narrates the forwarding mechanism
the latin-1 bytes path now implements; both are planner-uneditable source
text, flagged for a future touch-up round. Two accepted wire deltas are
documented (User-Agent default appears when the client omits it; ambient
`SSL_CERT_FILE`/`SSL_CERT_DIR` CA overrides are ignored under
`trust_env=False`).

**Deferred issues:** none — the one deferral this plan adopted
(`httpx2-native-sse-transport`) is Resolved, not deferred.

**Documentation reconciled (planner, this round):** CLAUDE.md (Purpose floor,
Structure, env table +new row, sinks clause, chat-sse-drain row, swap
residual), README.md (floor, deps, env table, drain claim), doc/architecture.html
(stall timeout, retry tuple, disconnects residual, swap residual, sinks
rationale), doc/provider-modes.html (drain bounds, event table), doc/configuration.html
(env rows), doc/trace-log.html (event inventory: `chat_sse_frame_oversize`,
`forward_failed`, `sse_buffer_cap_exceeded` bytes, `drain_exit` enum,
`swap_abort` phase), doc/test-catalog.html (2 retired entries removed, 6
entries rewritten, 10 new entries, parse-guard entry renamed). `check_doc_anchors.py`: PASS.

**Retire inventory** (transient artifacts for the post-commit sweep):
- ./tmp/reports/2026-11-15-httpx2-transport-sse-mega-audit-2026-11-15.json
- ./tmp/reports/2026-11-15-httpx2-transport-sse-coder-2026-11-15.json
- ./tmp/reports/2026-11-15-httpx2-transport-sse-coder-2026-11-15-2.json
- ./tmp/reports/2026-11-15-httpx2-transport-sse-coder-2026-11-15-3.json
- ./tmp/reports/2026-11-15-httpx2-transport-sse-tester-2026-11-15.json
- ./tmp/reports/2026-11-15-httpx2-transport-sse-tester-2026-11-15-2.json
- ./tmp/reports/2026-11-15-httpx2-transport-sse-review-2026-11-15.json
- ./tmp/verification/2026-11-15-httpx2-transport-sse-apply-step3.py
- ./tmp/verification/2026-11-15-httpx2-transport-sse-coder-4-suite.py
- ./tmp/verification/2026-11-15-httpx2-transport-sse-coder-4-wait.py
- ./tmp/verification/2026-11-15-httpx2-transport-sse-header-probe.py
- ./tmp/verification/2026-11-15-httpx2-transport-sse-precheck.py
- ./tmp/verification/2026-11-15-httpx2-transport-sse-run-suite.py
- ./tmp/verification/2026-11-15-httpx2-transport-sse-step1.py
- ./tmp/verification/2026-11-15-httpx2-transport-sse-step3-shapes.py
- ./tmp/verification/2026-11-15-httpx2-transport-sse-step8.py
- ./tmp/verification/2026-11-15-httpx2-transport-sse-tester-2-static.py
- ./tmp/verification/2026-11-15-httpx2-transport-sse-tester-2-suite.py
- ./tmp/verification/2026-11-15-httpx2-transport-sse-tester-suite.py
- ./tmp/verification/2026-11-15-httpx2-transport-sse-wait.py

(The nine resolved issue reports and the adopted deferral report retire via
`/update-and-commit` Step 9.6, not this sweep.)
