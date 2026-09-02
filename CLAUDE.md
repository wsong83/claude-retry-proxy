# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Purpose

`claude-retry-proxy` is a multi-provider HTTP retry gateway for the Claude API.
It listens on localhost, routes requests by model tier (haiku/sonnet/opus) to
different upstream providers, retries `429` and `503` responses with jittered
exponential backoff, and logs every request to a JSONL trace file. Tier routing
is configured via `~/.claude/proxy/config.json`; provider credentials are stored
encrypted in `~/.claude/keys-index.json` (vim blowfish2) and decrypted at
startup via a passphrase prompt. An admin HTML page at `/admin/` allows
hot-switching tier mappings at runtime.

Extracted from the personal `claude-config` repo into a standalone, public,
pip-installable package. Runtime dependency: `cryptography` (for vim blowfish2
decryption). Python 3.8+.

## Structure

```
src/claude_retry_proxy/
  __init__.py           __version__
  server.py             the HTTP retry gateway server (ThreadingHTTPServer, tier routing, model rewriting, admin API, retry/backoff, trace logging)
  cli.py                the claude-retry-proxy CLI: start / stop / status / reload (passphrase prompt, config validation, no URL swap)
  vimcrypt.py           vim blowfish2 (VimCrypt~03!) decryption (derived from claude-config bin/vimcrypt.py)
  admin.html            admin page for hot-switching tier mappings (served at /admin/)
src/templates/
  config.json  template for ~/.claude/proxy/config.json (copied on first start)
tests/
  test_claude_proxy.py  test suite aggregator (entry point: `python tests/test_claude_proxy.py`)
  _harness.py           shared test harness (env isolation, helper functions, proxy lifecycle)
  test_compat.py        compatibility learning tests (persistence, detector, state machine, concurrency)
  test_admin.py         admin API tests
  test_chat_sse.py      chat-mode SSE streaming tests
  test_chat_transform.py  chat-mode request/response transform tests
  test_cli.py           CLI lifecycle tests (start/stop/status)
  test_config_keys.py   config validation and key decryption tests
  test_mode_dispatch.py mode dispatch and auth header tests
  test_response_transform.py  response-mode transform tests
  test_retry_streaming.py  retry, streaming, and buffered-response-cap tests
  test_tier_routing.py  tier routing and model resolution tests
  test_trace.py         trace logging and analysis tests
  test_unit.py          unit-level tests (jitter, delay, helpers)
scripts/
  analyze_proxy_trace.py  trace log analysis tool (model stats, latency, success rates)
pyproject.toml   setuptools src-layout, console scripts, cryptography dependency
LICENSE          MIT
```

Two console scripts (defined in `pyproject.toml` `[project.scripts]`):
- `claude-retry-proxy` → `claude_retry_proxy.cli:main` — the manager.
- `claude-retry-proxy-server` → `claude_retry_proxy.server:main` — direct server invocation.

## Build / Test / Run

```bash
pip install -e .                              # editable install (needs setuptools>=64)
claude-retry-proxy start                      # start the proxy (passphrase prompt + config validation + launch server)
claude-retry-proxy status                     # show running/stopped/stale + tier mapping
claude-retry-proxy stop                       # stop the proxy
claude-retry-proxy reload                     # reload config.json from disk into running proxy
python tests/test_claude_proxy.py             # run the test suite
python -m claude_retry_proxy.cli --help       # PATH-independent invocation
python -m claude_retry_proxy.server --help
```

Start options: `--port` (default 8080), `--log <path>` (trace file; relative
paths resolve against cwd), `--all` (log full request/response bodies),
`--config-path <path>` (config.json location), `--keys-path <path>`
(keys-index.json location).

## Architecture

- **`settings.json` is static.** The user configures `ANTHROPIC_BASE_URL=http://localhost:8080`,
  standard tier model names (`ANTHROPIC_DEFAULT_SONNET_MODEL=sonnet`, etc.),
  and a dummy API key. The proxy NEVER reads or writes `settings.json`.
- **CLI `start`**: check `~/.claude/proxy/config.json` exists (if not, copy
  template and exit 1 with instructions), prompt passphrase via
  `vimcrypt.prompt_hidden`, decrypt `~/.claude/keys-index.json`, validate
  config against decrypted vendors, **prune the trace log** (entries older
  than 5 days), spawn the server via `python -m claude_retry_proxy.server
  --port <port> --config-path <path> --keys-path <path>`, pipe passphrase
  via stdin, write `proxy-state.json` (PID, port, start_time), TCP-probe
  the port for readiness (2s), rollback on failure. Cross-platform PID
  liveness/kill via `ctypes` on Windows (`OpenProcess` +
  `WaitForSingleObject` / `TerminateProcess`), `os.kill` on POSIX.
- **Server**: `ThreadingHTTPServer` on 127.0.0.1. Per request:
  1. Extract model name from request body → `resolve_tier` (direct name,
     reverse lookup, pattern match, or 400 error for unknown)
  2. Config lookup: tier → (provider, model name)
  3. Keys lookup: provider → (url, api_key, mode) from decrypted vendors table.
     `mode` defaults to `"anthropic"` when absent; valid values are `"anthropic"`,
     `"chat"`, `"response"`.
  4. **Mode dispatch** — auth header, path, and body transforms depend on mode:
     - **Auth:** `x-api-key` for anthropic; `Authorization: Bearer` for chat/response.
     - **Path:** original path for anthropic; `/v1/chat/completions` for chat;
       `/v1/responses` for response (trailing `/v1` stripped from URL prefix).
       `count_tokens` returns 400 for chat/response modes.
     - **Request body:** model-only rewrite for anthropic; full
       Anthropic→Chat-Completions transform for chat; Anthropic→Responses
       transform for response (buffered: full text/tool history, stream forced false).
     - **Response body (2xx only):** model-only rewrite for anthropic;
       Chat-Completions→Anthropic transform for chat; Responses→Anthropic
       transform for response. Error responses (non-2xx) pass through untransformed.
     - **SSE streaming:** anthropic mode forwards+rewrites upstream SSE; chat mode
       synthesizes Anthropic SSE from OpenAI SSE (frame-assembled, terminal
       synthesized on EOF); response mode forces `stream: false` and returns JSON.
  5. Forward to resolved upstream, retry on **429** and **503** /
     connection error with jittered exponential backoff (same logic as
     before: `PROXY_INITIAL_DELAY * 2**attempt`, capped at `PROXY_MAX_DELAY`,
     ±25% jitter, thread-local RNG). **429 retries use `PROXY_MAX_DELAY`**
     directly; 503 and connection errors use the exponential. Request body is
     built once before the retry loop — never re-transformed on retry. A
     compatibility-retry stripped variant is derived from the already-transformed
     outbound body after a recognized 400 rejection (single-attempt, same
     config/vendors snapshot, `suppress_compat=True`).
  6. **Response model rewriting**: the tier name is resolved from the request
     body at entry and threaded through the call chain. For anthropic-mode SSE
     (`text/event-stream`): buffer first event (64 KB cap), rewrite `model` in
     `message_start` event to the tier name, forward remainder + subsequent
     events unchanged. For anthropic-mode JSON (`application/json`): parse body,
     replace `model` with tier name, re-serialize. Chat/response modes use full
     body transforms (see Step 4). Other Content-Types pass through unchanged.
     Content-Type checked FIRST before any buffering/parsing.
  7. **`do_POST` streamed flag**: `streamed = (200 <= status < 300) and
     (resp_body == b"")` — streaming paths return `b""`, buffering paths
     return actual body. Only buffered responses call `_send_response`.
  8. Log a JSONL trace entry with `tier`, `provider`, and `mode` fields.
  - `/admin/shutdown` (localhost-only) triggers graceful shutdown.
  - **Admin page** (`GET /admin/`): serves `admin.html` from package data.
  - **Admin API** (localhost-only, CSRF-protected via Origin validation):
    - `GET /admin/api/config` — return current tiers + models
    - `GET /admin/api/providers` — return list of available provider names
    - `GET /admin/api/providers-detail` — return mode per provider (read-only, no keys)
    - `POST /admin/api/switch` — update tier mappings (preserves models
      catalog), validate all 3 tiers present, validate provider names,
      drain-and-swap pattern (block new queries, drain in-flight, swap,
      unblock)
    - `POST /admin/api/reload` — re-read config.json from disk, validate,
      drain-and-swap pattern
  - **Drain-and-swap pattern:** config changes use `_config_swapping` flag
    + `_inflight_count` counter + `_swap_done` Event. New requests wait if
    swap in progress. Admin waits for in-flight to drain (30s timeout,
    100ms poll), swaps under lock, signals completion. `forward_request`
    snapshots config state at entry under lock, uses snapshots
    throughout (immune to mid-request config changes).
  - CSRF: reject missing Origin, reject `null`, accept only
    `http://localhost:<port>`, `http://127.0.0.1:<port>`, `http://[::1]:<port>`.
  - Admin POST bodies capped at 64 KB.
  - **Client disconnect catch:** `_send_response` wrapped in
    `try/except _DISCONNECT_ERRORS`; on disconnect, a `client_disconnect`
    trace event is logged. `_stream_upstream_response` has the same outer
    handler plus inner try/except for upstream read errors.
  - **Give-up body preservation:** when retries are exhausted on 429/503,
    `forward_request` drains the upstream error body (capped at
    `PROXY_MAX_BODY_SIZE` via `_read_capped`) and returns it to the client.
    On connection-error exhaustion, a synthesized `upstream_unreachable`
    JSON body is returned.
- **Passphrase pipe protocol**: When keys are encrypted (`VimCrypt~03!`),
  CLI writes passphrase + `\n` to `proc.stdin`, closes stdin. Server reads
  one line from stdin in `main()` before `serve_forever()`. On decryption
  failure, server prints error to stderr and exits non-zero. CLI detects
  `proc.poll() != 0` as startup failure. When keys are plain JSON, no
  passphrase is sent — CLI closes stdin immediately, and the server skips
  stdin read entirely. `--passphrase-file` passes the passphrase via the
  server command line (instead of stdin) for non-interactive encrypted-key
  starts. Direct invocation: prompts interactively when `sys.stdin.isatty()`,
  supports `--passphrase-file` for non-interactive use.

## Environment Variables (server)

| Variable | Default | Description |
|----------|---------|-------------|
| `PROXY_PORT` | 8080 | Listen port (1024-65535) |
| `PROXY_MAX_RETRIES` | 10 | Max retry attempts (1-100). Shared by 429 and 503. |
| `PROXY_INITIAL_DELAY` | 1 | First backoff delay, seconds (1-60) |
| `PROXY_MAX_DELAY` | 30 | Backoff cap, seconds (1-300). Applied *before* jitter, so actual sleeps can exceed it by up to 25%. 429 retries use this value directly (jittered). |
| `PROXY_MAX_BODY_SIZE` | 10485760 | Request body size cap, bytes (1024-100MiB) → 413. Also caps the upstream error body drain on retry exhaustion (give-up path) via `_read_capped`. |
| `PROXY_MAX_RESPONSE_SIZE` | 104857600 | Streaming response size cap, bytes (1024-1GiB). Responses exceeding this are truncated with a `response_size_cap_exceeded` warning trace event. |
| `PROXY_LOG_ALL` | "" | Set to `1` to log full request/response bodies |
| `PROXY_TRACE_FILE` | `~/.claude/logs/proxy-trace.jsonl` | Trace log path |
| `PROXY_KEYS_PATH` | `~/.claude/keys-index.json` | Keys file path (encrypted or plain JSON) |
| `PROXY_STATE_FILE` | `~/.claude/proxy/proxy-state.json` | State file path override (added 2026-08-28). The server heartbeat writes PID/port/start_time to this file; `claude-retry-proxy stop`/`status`/`reload` read it. Override for test isolation. |
| `PROXY_FEATURE_COMPAT_FILE` | `~/.claude/proxy/feature-compatibility.json` | Compatibility state file path (added 2026-09-02). Stores learned per-provider field incompatibility. Override for test isolation. |

Runtime artifacts (all under `~/.claude/`, paths overridable via env vars — see table above):
`proxy/config.json`, `proxy/proxy-state.json`,
`proxy/proxy-stderr.log`, `logs/proxy-trace.jsonl`,
`proxy/feature-compatibility.json`. The trace log is pruned of
entries older than 5 days on each `claude-retry-proxy start` (best-effort;
does not block startup on failure).

## Gotchas

- **`~/.claude/settings.json` is static.** The user configures it once with
  `ANTHROPIC_BASE_URL=http://localhost:8080` and standard tier model names.
  The proxy never reads or writes it.
- **`--all` / `PROXY_LOG_ALL` writes raw prompts and completions** to the
  plaintext trace file. Note: **streamed 2xx success response bodies are NOT
  captured** even with `--all` (deliberate reduction in data-at-rest exposure;
  error-path bodies still are). `log_trace` and `write_state` apply
  `os.chmod(0o600)` on **POSIX only** (guarded by `os.name == 'posix'`) — on
  Windows `chmod` is a near-no-op (read-only bit only; no group/other model).
  Windows users must restrict the trace/state directory ACL manually
  (`icacls`).
- **Config validation is strict.** The proxy refuses to start if config.json
  is missing (copies template and tells user to populate it), has empty
  provider/model fields, or references unknown providers. Validation flows
  config→keys, not keys→config: every provider in `config.models` must have a
  corresponding entry in `keys-index.json`; every provider in `config.models`
  must have at least one valid model name (non-empty list of non-empty strings);
  every provider referenced by a tier must have an entry in `config.models`.
  Providers in `keys-index.json` that aren't in `config.models` and aren't
  referenced by any tier are silently ignored. Two tiers may map to the same model
  name; response rewriting uses the per-request tier, not a reverse map.
- **Heartbeat state is in-memory.** The server keeps its startup state
  (pid, port, etc.) in a module-level `_startup_state` variable. The heartbeat
  thread updates `last_heartbeat` on this in-memory copy and writes it to disk
  — it never reads from disk. If `proxy-state.json` is deleted externally, the
  next heartbeat recreates it with all fields intact within 30s.
- **Admin API CSRF protection.** Admin POST endpoints validate the Origin
  header. Non-browser clients (curl, CLI `reload`) must include an Origin
  header matching `http://localhost:<port>` or `http://127.0.0.1:<port>` or
  `http://[::1]:<port>`. Origin: null and missing Origin are rejected.
- **`PROXY_IDLE_TIMEOUT` is a dead env var** some tests still set — the server
  defines no idle-timeout feature. Harmlessly ignored.
- **Worst-case retry hold**: with jitter the *expected* sleep is unchanged but
  the upper bound per retry is `1.25 * PROXY_MAX_DELAY` (cap applied before
  the ±25% jitter). With env maxes (`PROXY_MAX_RETRIES=100`,
  `PROXY_MAX_DELAY=300`), a single 429/503-ing request can block a worker
  thread for ~10.4h. Defaults (10 retries, 30s cap) give ~3.8 min worst case.
- **Integer-second jitter is degenerate for small delays.** With ±25% rounded
  to an integer second, `base ∈ {1, 2}` get **zero** de-sync (the ±0.5s range
  lands in one integer bucket); de-sync is effective from `base ≥ 3` onward.
  On the 503 path that means the 3rd retry onward; the 429 path uses
  `PROXY_MAX_DELAY` (default 30), so it de-syncs from the first 429.
  Sub-second jitter was considered and rejected (integer rounding requested).
- **Give-up error body preservation:** when retries are exhausted on 429/503,
  the upstream error body is drained (capped at `PROXY_MAX_BODY_SIZE` via
  `_read_capped`) and returned to the client instead of `b''`. On
  connection-error exhaustion, a synthesized `upstream_unreachable` JSON body
  is returned. Preserved bodies flow into the `--all` trace log — on Windows
  the trace file is world-readable (see `--all` gotcha above).
- **Response size caps** are applied at `PROXY_MAX_RESPONSE_SIZE` on all four
  streaming loops (silently writing the response, client-disconnect aware,
  and the two audit paths) and on all three buffered read loops in
  `_forward_core` (2xx application/json, 2xx other-content-type for
  chat/response, and non-2xx). Each truncation emits a
  `response_size_cap_exceeded` trace event. The give-up drain remains capped
  at `PROXY_MAX_BODY_SIZE` via `_read_capped`.
- **Streaming disconnect catch is scoped to `_DISCONNECT_ERRORS`.** A
  non-standard client-write `OSError` outside that tuple (e.g.
  WSAENOBUFS/WSAENOTSOCK/ENOTCONN) can propagate into `forward_request`'s
  retry `except` after headers were sent, re-issuing the upstream POST. All
  realistic disconnect classes are caught; accepted residual (reviewer
  Warning, non-blocking). **Compatibility probe impact:** if this residual
  fires during a streamed probe response (probe owner holds
  `_compat_retry_lock`), the retry loop re-issues the unstripped probe POST,
  and a duplicate outcome can spuriously double the threshold or reset
  probation. Probability is negligible (exotic WSAENOBUFS-class, Windows
  only); consequence is bounded (one spurious doubling, next probe cycle
  revalidates). Accepted residual — documented for awareness.
- **`/admin/shutdown` can block during retry sleep.** Graceful shutdown waits
  for in-flight requests to finish, and a request mid-retry-backoff holds its
  worker thread for up to `PROXY_MAX_RETRIES * jittered_max_delay`, so shutdown
  can take that long to drain. Tracked as Open issue `shutdown-during-retry-sleep`
  in the jitter plan's Issue Log for a future hardening pass.
- **Drain-and-swap timeout during retry sleep.** Admin switch/reload drain
  waits up to 30s for in-flight requests to complete. A request stuck in
  retry backoff (worst case ~3.8 min with defaults) exceeds this timeout —
  the swap is **aborted** (returns 503 to admin client) rather than waiting
  indefinitely. The in-flight request continues with its original config
  snapshot and completes normally. Same root cause as
  `shutdown-during-retry-sleep`.
- **Two-phase readiness protocol.** `claude-retry-proxy start` uses a
  two-phase readiness check: (1) wait for the server to print `READY` to
  stdout (5s timeout), detected via a daemon thread reading `proc.stdout`
  lines (cross-platform — the prior `select.select()` approach did not
  work with pipe fds on Windows); (2) TCP probe the listen port (2s
  timeout). Phase 1 catches early crashes (bad passphrase, config errors)
  before the socket is bound; Phase 2 confirms the server is accepting
  connections. The `READY` marker is printed by `server.py main()` after
  `ThreadingHTTPServer(...)` construction but before `serve_forever()`.
- **`disable_retry_claude_count_token` (default `false`).** Set to `true` in
  `config.json` to skip retrying the `count_tokens` endpoint. Most third-party
  providers return 503/connection-errors for this Anthropic-specific endpoint.
  Without this flag, the proxy retries up to `PROXY_MAX_RETRIES` times
  (default 10), wasting bandwidth and provider quota. The shipped template
  defaults to `true`. Admin Apply preserves the flag; Reload reads it from disk.
- **Keys file can be plain JSON (no encryption).** The server and CLI
  auto-detect the format: if the file starts with `VimCrypt~03!` it is
  decrypted with the passphrase; otherwise it is parsed as plain JSON
  directly (no passphrase prompt). The server emits a stderr warning
  (`[proxy] WARNING: keys file is plain JSON — API keys are stored
  unencrypted on disk`) when plain keys are loaded. Plain files are
  convenient for testing and automation but leave API keys unencrypted on
  disk — restrict the file ACL on Windows with `icacls` (on POSIX
  `os.chmod(0o600)` is applied automatically). The recommended approach for
  production is to encrypt with `vim -n -x` (blowfish2, `VimCrypt~03!`, the
  default). The `--passphrase-file` CLI option is only used when keys are
  encrypted; with plain keys it is ignored.
- **Provider mode dispatch.** Each vendor entry in `keys-index.json` may
  carry a `mode` field (`"anthropic"`, `"chat"`, or `"response"`). Defaults
  to `"anthropic"` when absent. Startup validates the mode enum and emits a
  stderr warning for each vendor without an explicit mode. Invalid modes
  return 500 at request time. Chat mode transforms the request to OpenAI
  Chat Completions format and the response back to Anthropic Messages
  format; response mode transforms to OpenAI Responses format (buffered:
  full text/tool history, stream forced false). Error responses (non-2xx)
  pass through untransformed. `count_tokens` returns 400 for chat/response
  modes (no OpenAI equivalent).
  **Response-mode request transform:** the full conversation history is
  converted to ordered Responses input items: text becomes `message` items
  (historical assistant text is emitted as `output_text`; input-role text
  — user, system, developer — as `input_text`),
  `tool_use` becomes `function_call` with validated arguments, `tool_result`
  becomes `function_call_output` only when its `tool_use_id` matches a
  preceding emitted call. Anthropic tool definitions are converted to flat
  Responses function-tool shape (`type`, `name`, `description`, `parameters`);
  `tool_choice` is mapped against validated emitted tool names.
  **Response-mode response transform:** every output item is inspected in
  order; `function_call` items map to `tool_use` blocks with strict argument
  validation (dict-accepted, `{}` valid for zero-arg tools, malformed
  arguments degrade to visible placeholder + metadata-only trace event).
  `stop_reason` is `"tool_use"` when at least one valid function call was
  emitted; `null` when calls were seen but all degraded; otherwise
  `"end_turn"` (completed) or `null` (other status).
  **Chat-mode request transform:** messages are converted via
  `_transform_anthropic_messages_to_chat()` (thinking blocks converted to
  `reasoning_content` on the assistant message, redacted_thinking with non-empty
  `data` converted to a placeholder `reasoning_content` with a
  `redacted_thinking_passthrough` trace event, image blocks stripped,
  tool_use→tool_calls with dict-validated input and NaN/non-dict→placeholder,
  tool_result→role:tool paired by tool_use_id, cache_control stripped per-block);
  tools are converted via `_transform_anthropic_tools_to_chat()` (input_schema→parameters);
  tool_choice is mapped via `_transform_anthropic_tool_choice_to_chat()`.
  Request-level `thinking`, `metadata`, and `top_k` are dropped.
  When a message has both text and tool_calls, the split structure is preserved:
  `reasoning_content` rides on the text assistant message; the `content: null`
  tool_calls message does not receive `reasoning_content`.
  **Chat-mode response transform:** `_chat_to_anthropic()` converts
  `reasoning_content` (or `reasoning` for vLLM compat) to a `thinking` content
  block (`signature: ""`) inserted first in the content array, before any text
  or tool_use blocks.
  **Chat-mode SSE streaming:** `reasoning`/`reasoning_content` deltas are
  transformed to `thinking_delta` events with proper block-index management
  (thinking block at index 0, text block at index 1; deferred
  `content_block_start` until first delta type is known). Tool-use SSE deltas are now converted to Anthropic `tool_use` content
  blocks (per-index state, parallel/interleaved support, dict-only
  `json.loads` validation at close, and conservative degradation on
  malformed/truncated streams). A bounded metadata-only
  `chat_sse_tool_degradation` trace event (no tool names, IDs, or
  arguments) fires once per affected stream when any tool delta cannot
  form a valid `tool_use` block. The non-streaming path correctly
  transforms tool_use/tool_result in both request and response. Image
  content blocks are deferred (see `tmp/reports/defer-issue-*.json`). Response mode
  is buffered-only (forces `stream: false`) and converts the full conversation
  history including text, tools, tool_use, and tool_result items to the
  Responses API format; upstream `function_call` output items are mapped back
  to Anthropic `tool_use` blocks. Chat-mode
  SSE is synthesized from OpenAI SSE (frame-assembled on `\n\n`, terminal
  synthesized on EOF).
- **Malformed tool arguments in chat mode.** When `_chat_to_anthropic` encounters tool-call arguments that cannot be parsed as a JSON dict (including `json.JSONDecodeError`, non-dict parse results, empty dicts, non-dict `function` values, and non-dict tool-call entries), it emits a user-visible text block `[Tool call failed: arguments for '<name>' (call <id>) could not be parsed as JSON]` instead of a `tool_use` block with `input: {}`. A `tool_args_parse_failure` trace event is also logged. When all tool calls in a response are malformed, `stop_reason` is forced to `None` to prevent the client from hanging on `stop_reason: "tool_use"` with zero tool_use blocks. **Request-transform path:** `_transform_anthropic_messages_to_chat` applies the same degradation pattern for NaN/Infinity/non-dict `tool_use.input` values (rejected by `json.dumps(input, allow_nan=False)`), emitting the placeholder `[Tool call failed: arguments for '<name>' (call <id>) could not be serialized as JSON]` and a `tool_args_parse_failure` trace event. When a failed tool_use coexists with valid tool_use(s) in the same assistant message, the placeholder is emitted as a separate assistant message before the tool_calls message (content: null). (Behavior changes landed 2026-08-28 and 2026-08-29.)
- **Test suite is safe alongside a live proxy.** The test suite sets `os.environ["PROXY_STATE_FILE"]` and `os.environ["PROXY_FEATURE_COMPAT_FILE"]` to session temp paths at module load time (mirroring the existing `PROXY_TRACE_FILE` isolation). `cli.py` and `server.py` read these env vars at import time, so test proxies use isolated state files and can never touch the live proxy's `~/.claude/proxy/proxy-state.json` or `~/.claude/proxy/feature-compatibility.json`. The old docstring warning about not running tests alongside a live proxy is obsolete. The full suite (253 tests across 12 modules: `tests/_harness.py` + `tests/test_compat.py` + 10 cluster modules + `tests/test_claude_proxy.py` aggregator) passes with the live proxy up (landed 2026-08-28, updated 2026-09-02).

## Documentation

- [README.md](README.md) — user-facing: install, usage, configuration, trace
  log, the `--all` data-exposure warning, testing notes.
- [scripts/analyze_proxy_trace.py](scripts/analyze_proxy_trace.py) — trace log
  analysis tool: calculates per-model stats (request count, retries, success
  rates, TTFT, latency) for a configurable time window, with outlier filtering.
- [plans/](plans/) — completed implementation plans (one per feature, with
  design rationale, issue log, and test results).
- [plans/2026-08-29-fix-chat-mode-request-transform.md](plans/2026-08-29-fix-chat-mode-request-transform.md) — chat-mode
  request transform: Anthropic Messages → OpenAI Chat Completions conversion
  with content block transforms, tool mapping, and trace events.
- [plans/2026-08-29-fix-chat-mode-thinking-roundtrip.md](plans/2026-08-29-fix-chat-mode-thinking-roundtrip.md) — chat-mode
  thinking/reasoning round-trip: thinking blocks → reasoning_content on
  request, reasoning_content → thinking blocks on response, SSE reasoning
  delta handling, redacted_thinking passthrough with trace events.
- [plans/2026-08-30-fix-chat-sse-tool-calls.md](plans/2026-08-30-fix-chat-sse-tool-calls.md) — chat-mode
  streaming tool-call delta conversion: `delta.tool_calls` → Anthropic
  `tool_use` SSE with per-index state, dict-only validation, and
  metadata-only degradation diagnostics.
- [plans/2026-08-31-fix-response-mode-tool-roundtrip.md](plans/2026-08-31-fix-response-mode-tool-roundtrip.md) — response-mode
  buffered tool-call round trips: full text/tool history → Responses items,
  `function_call` → `tool_use`, flat function tools, strict validation, and
  correct stop reasons.
- [plans/2026-09-01-learn-context-management-compatibility.md](plans/2026-09-01-learn-context-management-compatibility.md) — per-upstream
  `context_management` compatibility learner: automatic detection, stripping,
  request-count revalidation, and two-success delisting for Anthropic-mode
  third-party providers.
- [plans/2026-08-27-support-three-endpoint-modes.md](plans/2026-08-27-support-three-endpoint-modes.md) — three-endpoint-mode
  dispatch (anthropic/chat/response) with full request/response transformation
  and SSE streaming.
- Design rationale for the extraction lives in
  `tmp/plans/2026-07-17-extract-retry-proxy-design.md` (gitignored — planning
  artifact, not published).
- Multi-provider gateway design lives in
  `tmp/plans/2026-08-23-cc-switch-mode.md` (gitignored — planning artifact).

No other supplementary docs.

## Unresolved Deferred Issues

```json
[
  {"issue_id": "image-content-blocks-chat-mode", "title": "Chat mode: image content blocks not transformed between Anthropic and OpenAI formats", "deferred": "2026-08-29", "target_repo": null}
]
```

## Future Work — TODO

The original `claude-config` extraction deferred issues are all resolved.
The chat-mode thinking/reasoning round-trip is now implemented
(thinking blocks → reasoning_content, reasoning_content → thinking blocks,
SSE reasoning delta handling — landed 2026-08-30). The chat-mode SSE
streaming tool-call delta conversion is now implemented (landed
2026-08-30). One chat-mode deferred issue remains (see
`## Unresolved Deferred Issues` above): image content block mapping.
Future hardening work can also focus on additional features or
performance optimizations.
