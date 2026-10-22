# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Purpose

`claude-retry-proxy` is a multi-provider HTTP retry gateway for the Claude API.
It listens on localhost, routes requests by model tier (haiku/sonnet/opus) to
different upstream providers, retries `429` and `503` responses with jittered
exponential backoff, and logs every request to a JSONL trace file. Tier routing
is configured via `~/.claude/proxy/config.json`, and the provider catalog in its
sibling `~/.claude/proxy/models.json`; provider credentials are stored
encrypted in `~/.claude/keys-index.json` (vim blowfish2) and decrypted at
startup via a passphrase prompt. An admin HTML page at `/admin/` allows
hot-switching tier mappings at runtime.

Extracted from the personal `claude-config` repo into a standalone, public,
pip-installable package. Runtime dependency: `cryptography` (for vim blowfish2
decryption). Python 3.8+.

This file is the operational summary. The `doc/` tree holds the deep reference —
rationale, mechanisms, and edge cases — and is indexed by
[doc/content.html](doc/content.html).

## Structure

```
src/claude_retry_proxy/
  __init__.py           __version__
  server.py             the HTTP retry gateway server (ThreadingHTTPServer, tier routing, model rewriting, admin API, retry/backoff)
  compat.py             the compatibility learner: the `COMPAT_FEATURES` registry (two features — `context_management` in anthropic mode, `reasoning_field` in chat mode) whose descriptors own their mode, presence test, matcher, field set and retry budget; COMPAT_* policy constants; the owned `_CompatState` state object (default-param `state=` injection); the `context_management` state machine with its 400-shape matchers and its retry lock, and the `reasoning_field` credit learner (a per-key in-memory credit; the switch thresholds are `models.json` policy, `reasoning_field_switch`) with its lock-free, key-free rescue and matcher (extracted from server.py; the probe-outcome + retry orchestration slice stays in server.py)
  sanitize.py           error-text redaction leaf: `sanitize_error`, the chokepoint for text reaching stderr, trace `error` fields and client-facing error bodies
  sinks.py              sink class family: private `_Sink` base, `TraceSink` (JSONL append + counters + markers), `StateSink` (atomic state document), shared `_SinkHealth` failure reporter, process-wide pair + `configure()`
  settings.py           env-derived settings singleton: `SETTINGS` value object (the `PROXY_*` limits/flags, runtime paths incl. state/compat files, mode values) + `resolve_trace_file` — built at import from env, adjusted by `main()` at startup; imported by both the server and the CLI
  config.py             the config.json + models.json document pair: `models_path_for` / `load_models_document` / `load_config` / `validate_config` (the canonical validation policy) / `write_config` / `install_template` + extra-header specs; serves the server and the CLI
  keys.py               keys-index pipeline: `vendor_key_entries`/`vendor_key_names`, `_validate_vendor_keys_shape`, `load_keys_file` (encrypted or plain), `read_passphrase_from_stdin`
  safety.py             task-shaped utility leaf: string-emission-safety predicates (`_validate_admin_name` charset allowlist); docstring indexes the stay-behind safety idioms
  transforms_common.py  shared endpoint-mode transform mechanism: `_transform_and_guard` (passthrough-on-failure response guard) + `_request_transform_timestamp` helper + the tool-schema pattern sanitizers `_strip_regex_identity_escapes` / `_sanitize_schema_patterns` / `_sanitize_body_tools` (see doc/provider-modes.html#pattern-normalization)
  transforms_chat.py    Anthropic↔Chat (OpenAI chat-completions) body transforms, both directions
  transforms_response.py Anthropic↔Responses body transforms, both directions
  cli.py                the claude-retry-proxy CLI: start / stop / status / reload (passphrase prompt, two-file template provisioning, canonical validation shared with config.py/keys.py, no URL swap; `reload` refreshes the provider catalog only)
  vimcrypt.py           vim blowfish2 (VimCrypt~03!) decryption (derived from claude-config bin/vimcrypt.py)
  admin.html            admin page for hot-switching tier mappings (served at /admin/)
  templates/            shipped inside the package, so they survive a wheel install
    config.json     template for ~/.claude/proxy/config.json (copied on first start)
    models.json     template for ~/.claude/proxy/models.json (catalog + header rules
                    + the count-tokens flag)
    keys-index.json template for ~/.claude/keys-index.json (single-key `key` string
                    or multi-key `keys` name→payload object)
tests/            per-area test modules + aggregator; see doc/test-catalog.html
scripts/
  analyze_proxy_trace.py  trace log analysis tool (model stats, latency, success rates)
  check_doc_anchors.py    doc anchor + credential-shape checker (invoked by the test suite)
doc/              human-facing HTML reference, indexed by content.html
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
claude-retry-proxy stop                       # stop the proxy (exit 1 + state file kept if the process survives)
claude-retry-proxy reload                     # refresh the provider catalog from models.json
python tests/test_claude_proxy.py             # run the test suite
python -m claude_retry_proxy.cli --help       # PATH-independent invocation
python -m claude_retry_proxy.server --help
```

`pip install -e .` must be an **editable** install. The console script, the
spawned `python -m claude_retry_proxy.server`, and therefore the running proxy
all resolve `claude_retry_proxy` through the interpreter's path — never through
the working directory. A non-editable (snapshot) install silently runs a frozen
copy of `src/`, so edits have no effect in the CLI, in the live proxy, *and* in
the test suite, which exercises both routes. Verify with
`python -c "import claude_retry_proxy.server as s; print(s.__file__)"` — it must
print this repo's `src/claude_retry_proxy/server.py`. With an editable install,
any `src/` change reaches the live proxy on its next restart.

Start options: `--port` (default 8080), `--log <path>` (trace file; relative
paths resolve against cwd), `--all` (log full request/response bodies),
`--config-path <path>` (config.json location), `--keys-path <path>`
(keys-index.json location).

## Architecture

Mechanisms, rationale, and edge cases live in
[doc/architecture.html](doc/architecture.html) and
[doc/provider-modes.html](doc/provider-modes.html). This section is the
operational summary — enough to reason about a change in place, with pointers
for the rest.

- **`settings.json` is static.** The user configures `ANTHROPIC_BASE_URL`,
  standard tier model names, and a dummy API key. The proxy never reads or
  writes it. (See Gotchas.)

- **CLI `start`:** ensure `~/.claude/proxy/config.json` **and its sibling
  `models.json`** both exist (else install via the shared `install_template`,
  which existence-gates both writes and provisions only what is absent, exit 1);
  prompt the passphrase via
  `vimcrypt.prompt_hidden`; load the keys via `load_keys_file` (its shape
  validation and mode-warning diagnostics surface at the command); validate with
  the canonical `validate_config` — single policy with the server, aggregated
  error list; prune the trace log (>5 days); spawn `python -m
  claude_retry_proxy.server --port <port>
  --config-path <path> --keys-path <path>`; pipe the passphrase via stdin; write
  `proxy-state.json`; probe readiness; roll back on failure. PID liveness/kill
  uses `ctypes` on Windows, `os.kill` on POSIX. Readiness:
  [doc/operations.html#readiness](doc/operations.html#readiness).

- **Server**: `ThreadingHTTPServer` on 127.0.0.1. Per request:
  1. Extract the model name from the body → `resolve_tier` (direct name,
     reverse lookup, pattern match, or 400 for an unknown model). See
     [doc/architecture.html#tier-resolution](doc/architecture.html#tier-resolution).
  2. Config lookup: tier → (provider, model name).
  3. Keys lookup: provider → (url, key or keys, mode). The tier's `key`
     selector picks the payload; absent/`""` means the first key in file order.
     A selector naming no key of its provider fails startup/reload/switch
     validation; an unresolvable vendor key at request time yields 500
     `invalid_provider_key`.
  4. **Mode dispatch** — `anthropic` (default), `chat`, or `response`: auth
     header, path, and both body transforms differ; `count_tokens` returns 400
     for the latter two. [doc/provider-modes.html](doc/provider-modes.html).
     Config-driven `extra_request_headers` apply here too — after provider-key
     injection, outside the retry loop — as `{header, from, fallback}` specs
     whose `fallback` may be the token `"request_id"`.
     [doc/configuration.html#extra-headers](doc/configuration.html#extra-headers).
  5. Forward upstream; retry **429** and **503** / connection errors with
     jittered exponential backoff. **The outgoing body is built once, before
     the retry loop, and never re-transformed** — the loop re-sends the same
     bytes. (Two compatibility retries are the exception — the
     `context_management` stripped retry and the `reasoning_field` rescue
     passes: both re-enter the forward path from the *client* body, so those do
     re-run the transform.) See
     [doc/architecture.html#retry](doc/architecture.html#retry).
  6. **Response model rewriting.** The tier name is resolved from the request
     body at entry and threaded through the call chain. Rewriting uses that
     per-request tier, not a reverse map — two tiers may share a model name.
     Anthropic-mode SSE: buffer the first event (64 KB cap), rewrite `model` in
     `message_start`, forward the remainder unchanged. Anthropic-mode JSON:
     parse, replace `model`, re-serialize. Chat/response modes use full body
     transforms. Other Content-Types pass through untouched.
     **Content-Type is checked FIRST, before any buffering or parsing.**
  7. **`do_POST` streamed flag:** `streamed = (200 <= status < 300) and
     (resp_body == b"")` — streaming paths return `b""`, buffering paths return
     the actual body. Only buffered responses call `_send_response`.
  8. Log a JSONL trace entry carrying `tier`, `provider`, and `key` (the
     resolved key *name*; omitted when resolution is impossible). The mode is
     **not** on this entry — it rides on the separate `mode_dispatch` event,
     which is emitted only for non-anthropic modes.
     Requests to a provider with `extra_request_headers` rules also carry the
     resolved map, omitted when empty. Full field list and event inventory:
     [doc/trace-log.html](doc/trace-log.html).
  - `/admin/shutdown` (localhost-only) triggers a graceful shutdown.

- **Admin API** (localhost-only, CSRF-protected via Origin validation): the page
  at `GET /admin/` is served from package data; `GET /admin/api/config`,
  `/providers`, `/providers-detail` (mode + key *names* per provider — never
  payloads), `/swap-status` (live drain state); `POST /admin/api/switch` (writes
  a **tiers-only** `config.json`) and `/reload` (re-reads `models.json` — the
  provider catalog — and **never** the tier mapping); `POST /admin/shutdown`.
  Bodies are capped at 64 KB. Endpoint table and the Origin accept/reject sets:
  [doc/operations.html#admin](doc/operations.html#admin). Two distinct 409s guard
  the press paths: `config_swap_in_progress` (single-flight — a press arrived
  while a swap was in progress) and `config_reload_stale` (a reload's gated
  candidate was read before a concurrent switch completed a swap, so installing
  it would revert that switch).
  **The page mirrors that server-side contract.** While any swap is in play it
  locks both buttons *and* all nine tier selects, reports the drain live at 1 Hz
  from `/admin/api/swap-status`, and re-reads the tier row before unlocking —
  unlocking only on a **successful** re-read, at all three call sites (attach
  completion, `config_reload_stale`, and the one-shot load check). This matters
  because `/admin/api/switch` carries **no** staleness guard; only the reload
  path has one, so an unlocked pre-swap row would write its baseline back over a
  completed swap. Same section:
  [doc/operations.html#admin](doc/operations.html#admin).

- **Drain-and-swap (silence-based).** Config changes (switch and reload) are
  **single-flight** — a second press while one is in progress is refused `409`
  `config_swap_in_progress`, and the check-and-set is atomic under one
  `_config_lock` acquisition in `_drain_for_swap()` (a `None` return is the
  refusal signal). The owner pauses new admissions, stamps the shared
  `_last_upstream_activity` clock, snapshots `_inflight_count`, and drains while
  the count is non-zero **and** an upstream byte arrived within
  `PROXY_SWAP_SILENCE_TIMEOUT` (default 30 s); quiet for `budget + 2 s`
  (`_SWAP_QUIET_GRACE`) means every survivor is silent by construction. There is
  **no wall-clock cap** — live work is waited to completion — and retry chains
  abandon at the press with a retryable `503 config_swap_restart` instead of
  being awaited. The swap then bumps `_config_epoch` under lock and signals
  `_swap_done`; old-epoch stragglers die retryably at their next checkpoint, so
  no old-routing result is delivered after a swap. `forward_request` snapshots
  config, vendors **and** the epoch at entry and threads them throughout.
  **Shutdown does not use this path** — see Gotchas.
  [doc/architecture.html#config-swap](doc/architecture.html#config-swap).

- **`GET /admin/api/swap-status`** reports a swap in progress live
  (`swapping`, `inflight`, `waited_s`, `silence_s`, `budget_s`; the two time
  fields are `null` when idle). Successful switch/reload responses carry the
  drain's detail — `drained` (meaning **"nothing was evicted"**, not "the count
  reached zero"), `waited_s`, `inflight_at_swap` (the count *at the press*).

- **Sinks never raise.** `log_trace` / `write_state` delegate to `TraceSink` /
  `StateSink`, sharing one never-raising implementation in the private `_Sink`
  base — so trace and state cannot drift apart. Each returns `True`/`False`.
  This is load-bearing: an `OSError` escaping a trace write would be caught by
  the retry loop's `except (socket.error, ConnectionError, OSError)` clause and
  misread as a connection error, re-issuing the upstream POST; in
  `heartbeat_loop` it would kill that thread permanently. Both sinks redo their
  work every call, so transient faults self-heal — but entries written during
  an outage are **lost, not buffered**. Reporting policy, the stderr wrapper,
  and the startup fail-fast:
  [doc/architecture.html#sinks](doc/architecture.html#sinks).

- **Passphrase pipe protocol.** Encrypted keys: the CLI writes
  `<passphrase>\n` to the child's stdin and closes it; the server reads one line
  in `main()` before `serve_forever()`. Plain JSON: nothing is sent, the CLI
  closes stdin, and the server skips the read. A decryption failure is a
  non-zero server exit, which the CLI reports as a startup failure.
  `--passphrase-file` passes it on the command line instead — visible to
  same-host process listings.
  [doc/operations.html#passphrase](doc/operations.html#passphrase).

## Environment Variables (server)

| Variable | Default | Description |
|----------|---------|-------------|
| `PROXY_PORT` | 8080 | Listen port (1024-65535) |
| `PROXY_MAX_RETRIES` | 10 | Max retry attempts (1-100). Shared by 429 and 503. |
| `PROXY_INITIAL_DELAY` | 1 | First backoff delay, seconds (1-60) |
| `PROXY_MAX_DELAY` | 30 | Backoff cap, seconds (1-300). Applied *before* jitter, so actual sleeps can exceed it by up to 25%. 429 retries use this value directly (jittered). |
| `PROXY_MAX_BODY_SIZE` | 10485760 | Request body size cap, bytes (1024-100MiB) → 413. Also caps the upstream error body drain on retry exhaustion (give-up path). |
| `PROXY_MAX_RESPONSE_SIZE` | 104857600 | Streaming response size cap, bytes (1024-1GiB). Responses exceeding this are truncated with a `response_size_cap_exceeded` warning trace event. |
| `PROXY_SWAP_SILENCE_TIMEOUT` | 30 | Per-request silence budget for the config-swap drain, seconds (1-300; blank/invalid → 30). The drain exits when no upstream byte has arrived from *any* in-flight request for this long, then evicts the remainder retryably (`config_swap_restart`). Also bounds a streamed read's socket arm while a swap is in progress, and is reported as `budget_s` by `/admin/api/swap-status`. Read at startup. |
| `PROXY_LOG_ALL` | "" | Set to `1` to log full request/response bodies |
| `PROXY_TRACE_FILE` | `~/.claude/logs/proxy-trace.jsonl` | Trace log path |
| `PROXY_KEYS_PATH` | `~/.claude/keys-index.json` | Keys file path (encrypted or plain JSON) |
| `PROXY_STATE_FILE` | `~/.claude/proxy/proxy-state.json` | State file path override (added 2026-08-28). The server heartbeat writes PID/port/start_time to this file; `claude-retry-proxy stop`/`status`/`reload` read it. Override for test isolation. |
| `PROXY_FEATURE_COMPAT_FILE` | `~/.claude/proxy/feature-compatibility.json` | Compatibility state file path (added 2026-09-02). Stores learned per-provider field incompatibility. Override for test isolation. |
| `PROXY_CHAT_RETRY_NUDGE` | the `[proxy nudge] …` text | Retry-nudge text (added 2026-10-06), chat mode: appended as a trailing user message to a retry that recovers an errored unfinished tool turn. Unset = default text; empty, whitespace-only, or >4096 chars **disables the feature** (`""` is the kill switch — unlike the numeric vars, blank/oversize is not defaulted). Read at startup. |

[doc/configuration.html#env-vars](doc/configuration.html#env-vars) is the
authoritative reference and carries the same table with prose.

Runtime artifacts (all under `~/.claude/`, paths overridable via env vars — see
table above): `proxy/config.json`, `proxy/models.json`, `proxy/proxy-state.json`,
`proxy/proxy-stderr.log`, `logs/proxy-trace.jsonl`,
`proxy/feature-compatibility.json`. The trace log is pruned of entries older
than 5 days on each `claude-retry-proxy start` (best-effort; does not block
startup on failure).

## Gotchas

- **`~/.claude/settings.json` is static.** The user configures it once with
  `ANTHROPIC_BASE_URL=http://localhost:8080` and standard tier model names. The
  proxy never reads or writes it.

- **`--all` / `PROXY_LOG_ALL` writes raw prompts and completions** to the
  plaintext trace file. Note: **streamed 2xx success response bodies are NOT
  captured** even with `--all` (deliberate reduction in data-at-rest exposure;
  error-path bodies still are). `log_trace` and `write_state` apply
  `os.chmod(0o600)` on **POSIX only** (guarded by `os.name == 'posix'`) — on
  Windows `chmod` is a near-no-op (read-only bit only; no group/other model).
  Windows users must restrict the trace/state directory ACL manually
  (`icacls`). Two trace fields are NOT gated by `--all`: `extra_request_headers`
  (resolved values, e.g. the client's per-conversation session id, logged on
  every request for providers with rules) and `client_user_agent` (the inbound
  User-Agent as the proxy forwards it — a repeated header resolves to the last
  line sent upstream — capped at 512 bytes with a visible marker, and omitted
  when that resolved value is empty; its value is arbitrary raw client text with
  no allowlist, and `method`/`path`/`model` are client strings too). The Windows
  caveat above applies to both.
  [doc/trace-log.html#all](doc/trace-log.html#all)

- **Admin API CSRF protection.** Admin POST endpoints validate the Origin
  header. Non-browser clients (curl, CLI `reload`) must include an Origin
  header matching `http://localhost:<port>` or `http://127.0.0.1:<port>` or
  `http://[::1]:<port>`. Origin: null and missing Origin are rejected.

- **`PROXY_IDLE_TIMEOUT` is a dead env var** some tests still set — the server
  defines no idle-timeout feature. Harmlessly ignored.

- **Worst-case retry hold**: with jitter the *expected* sleep is unchanged but
  the upper bound per retry is `1.25 * PROXY_MAX_DELAY` (cap applied before the
  ±25% jitter). With env maxes (`PROXY_MAX_RETRIES=100`, `PROXY_MAX_DELAY=300`),
  a single 429/503-ing request can block a worker thread for ~10.4h. Defaults
  (10 retries, 30s cap) give ~3.8 min worst case.

- **Test suite is safe alongside a live proxy.** The suite sets
  `PROXY_TRACE_FILE` and `PROXY_FEATURE_COMPAT_FILE` to session temp paths, and
  `PROXY_STATE_FILE` to a per-run path (see below), at module load —
  *before* importing `cli.py` or `server.py`
  (`settings.py` binds those env vars at import — both modules import it). A test proxy
  therefore cannot touch the live proxy's files, and the old docstring warning
  about not running tests alongside a live proxy is obsolete.
  `PROXY_STATE_FILE` goes further: it is a **per-run** path keyed to the runner
  PID (`~/.claude/proxy/claude-retry-proxy-test-state-<pid>.json` — the live
  directory, a distinct name), cleared at harness import and again after every
  test in `run_cli`'s loop. The fixed machine-global name it replaced let a dead
  proxy's PID survive across runs, and Windows recycles PID numbers, so
  `start`'s `is_pid_alive()` gate could report an unrelated live process as
  `Proxy already running`. A hard-killed run can still orphan its own file (no
  cleanup can run); those are inert and may be deleted from `~/.claude/proxy` by
  hand.
  [doc/test-catalog.html#isolation](doc/test-catalog.html#isolation)

### Moved out of this section

These were Gotchas bullets. The mechanism now lives in `doc/`; the one-liner is
what you need in context, and the link has the rest.

| In one line | Detail |
|---|---|
| Provider mode dispatch — `anthropic`/`chat`/`response` differ in auth header, path, and both body transforms | [doc/provider-modes.html](doc/provider-modes.html) |
| Tool-schema `pattern` regexes are normalized (ECMA identity escapes stripped) in **all three modes** before forwarding — anthropic mode included, via `_sanitize_body_tools` on its verbatim forward — so strict backends accept MCP/Zod tool schemas | [doc/provider-modes.html#pattern-normalization](doc/provider-modes.html#pattern-normalization) |
| Chat mode never substitutes `input: {}` for tool arguments it could not parse — it degrades them to a visible placeholder block | [doc/provider-modes.html#malformed-args](doc/provider-modes.html#malformed-args) |
| Chat mode maps `image` blocks — top-level and `tool_result`-nested — to `image_url` parts (base64 → `data:` URI, url verbatim, merged text part first); inconvertible images (incl. the Files-API `file` source) are dropped and counted, and there is deliberately no reverse mapping | [doc/provider-modes.html#image-content-blocks](doc/provider-modes.html#image-content-blocks) |
| A chat-mode stream that goes silent after `finish_reason` waits up to 5 s before the terminal event, not the upstream socket timeout | [doc/provider-modes.html#chat-sse-drain](doc/provider-modes.html#chat-sse-drain) |
| A chat-mode stream that ends with no `finish_reason` closes differently depending on whether `[DONE]` arrived | [doc/provider-modes.html#chat-sse](doc/provider-modes.html#chat-sse) |
| A chat-mode turn that declared tools, ends its text in a colon and emitted no tool call is closed with a retryable error and its retry nudged (`PROXY_CHAT_RETRY_NUDGE=""` disables); a repeated stall passes through | [doc/provider-modes.html#chat-sse-unfinished-turn](doc/provider-modes.html#chat-sse-unfinished-turn) |
| A vendor carries either `key` (string) or `keys` (name→payload); a tier's `key` selector picks one | [doc/configuration.html#multi-key](doc/configuration.html#multi-key) |
| The keys file may be plain JSON — convenient, but the keys then sit unencrypted on disk | [doc/configuration.html#encryption](doc/configuration.html#encryption) |
| Validation flows config→keys, not the reverse, and is strict — single-sourced in `config.py`/`keys.py`, enforced by both the server and CLI `start` | [doc/configuration.html#validation](doc/configuration.html#validation) |
| `disable_retry_claude_count_token` skips retrying `count_tokens` (template default `true`) | [doc/configuration.html#count-tokens-flag](doc/configuration.html#count-tokens-flag) |
| Trace/state I/O failures degrade the proxy; they never stop it — except at startup, which fails fast | [doc/architecture.html#sinks](doc/architecture.html#sinks) |
| Responses are truncated at `PROXY_MAX_RESPONSE_SIZE` with a `response_size_cap_exceeded` event | [doc/architecture.html#size-caps](doc/architecture.html#size-caps) |
| On 429/503 exhaustion the upstream error body is preserved and returned; connection errors get a synthesized body, now with status `502` rather than a literal `0` | [doc/architecture.html#give-up](doc/architecture.html#give-up) |
| Every error the proxy generates itself uses the Anthropic envelope (`error.type` taxonomy + `error.code` discriminator + `request_id`); the admin surface is deliberately excluded | [doc/architecture.html#error-envelope](doc/architecture.html#error-envelope) |
| The decode and encode ceilings differ (`json.loads` ≈16,920 vs `json.dumps` ≈15,501), so a band of payloads parses and then fails to re-encode — guards are verified by `try`-**enclosure**, never by grepping `except` | [doc/architecture.html#error-envelope](doc/architecture.html#error-envelope) |
| Integer-second jitter is degenerate for `base ∈ {1, 2}` — zero de-sync; effective from `base ≥ 3` | [doc/architecture.html#jitter](doc/architecture.html#jitter) |
| Heartbeat state is in-memory; `proxy-state.json` is a projection rewritten every 30 s | [doc/architecture.html#heartbeat](doc/architecture.html#heartbeat) |
| Shutdown kills in-flight requests — it does not drain them, and the killed request's trace entry never lands | [doc/operations.html#shutdown](doc/operations.html#shutdown) |
| `stop` exits **1** and **keeps** `proxy-state.json` when the process survives its force-kill (that file is what makes the orphan findable); it never escalates to `SIGKILL`, because PID liveness is not proxy identity and a recycled PID would be signalled | [doc/operations.html#stop-contract](doc/operations.html#stop-contract) |
| A SIGTERM handler runs *on* the `serve_forever` thread, so `server.shutdown()` must be dispatched to another thread; `READY` and the `proxy_ready` trace event post-date handler registration, so wait on either before signalling a starting proxy | [doc/architecture.html#sigterm](doc/architecture.html#sigterm) |
| A swap has **no wall-clock cap**: live work is waited to completion and only silence is evicted (retryably, `config_swap_restart`) — the consequence being that an unbounded drain blocks all new admissions, with `stop` / `/admin/shutdown` as the escape hatches | [doc/architecture.html#config-swap](doc/architecture.html#config-swap) |
| Readiness is two-phase: the `READY` marker (5 s), then a TCP probe (2 s); a port held by another listener is refused before `READY` (POSIX `SO_REUSEADDR`, Windows plain bind — Windows `SO_REUSEADDR` would permit a second `LISTEN`), and start-failure diagnostics read only the current attempt's stderr window | [doc/operations.html#readiness](doc/operations.html#readiness) |
| A client-write `OSError` outside `_DISCONNECT_ERRORS` can be misread as a connection error and re-issue the POST | [doc/architecture.html#disconnects](doc/architecture.html#disconnects) |

## Refactoring

- **Before planning any code split — extracting a module, a class family, or a
  cluster of functions out of a large file — run `/refactor-split` and read
  `~/.claude/guides/refactor-split-guidance.md` first.** Together they carry
  the membership tests, the state doctrine, the blast-radius ordering rule,
  the move mechanics, the gate disciplines, and the staging discipline this
  repo's extractions follow. Deliberately not inlined here: it is needed only
  when a refactor is on the table, not in every session.

## Documentation

- **[doc/content.html](doc/content.html) — the human-facing reference.** Start
  here; it indexes the whole tree.
  - [architecture.html](doc/architecture.html) — request path, tier resolution,
    retry/backoff, error responses and the Anthropic envelope, give-up, size
    caps, disconnects, config swap, heartbeat, sinks, shutdown
  - [provider-modes.html](doc/provider-modes.html) — the three endpoint modes,
    auth, paths, request/response transforms, SSE, tool-call degradation
  - [configuration.html](doc/configuration.html) — `config.json`,
    `models.json`, `keys-index.json`, environment variables, validation
  - [operations.html](doc/operations.html) — CLI, readiness, passphrase, admin
    API and CSRF, shutdown, runtime artifacts
  - [compatibility.html](doc/compatibility.html) — the learner registry: the
    `context_management` state machine (constants, states, transitions,
    suppression) and the `reasoning_field` credit learner (selection, credit
    rule, rescue), plus the shared persistence and events
  - [trace-log.html](doc/trace-log.html) — entry schema, event inventory,
    `--all`, permissions, pruning, analysis
  - [test-catalog.html](doc/test-catalog.html) — suite layout, the per-test
    index of the whole suite, harness, isolation, testing patterns,
    anti-patterns
- [README.md](README.md) — user-facing: install, usage, configuration, trace
  log, the `--all` data-exposure warning.
- [scripts/analyze_proxy_trace.py](scripts/analyze_proxy_trace.py) — trace log
  analysis: per-model request count, retries, success rates, TTFT, latency.
- [plans/](plans/) — completed implementation plans, one per feature, with
  design rationale, issue log, and test results.
- Extraction design rationale lives in
  `tmp/plans/2026-07-17-extract-retry-proxy-design.md` (gitignored — planning
  artifact, not published). Multi-provider gateway design lives in
  `tmp/plans/2026-08-23-cc-switch-mode.md` (gitignored).

No other supplementary docs.

## Future Work — TODO

The large source/test file
split and the module-split guidance consolidation were retired 2026-09-16 by
the global refactor-split consolidation (claude-config plan
2026-09-16-refactor-split-skill): the extraction doctrine now lives in the
global guide, and the /refactor-split survey tracks oversized-file state,
superseding the retired break-up backlog report.

The `sanitize.py` + `sinks.py` extraction (2026-09-12) was the first step of the
staged decomposition prescribed by the global refactor-split guidance. Four more
followed. The transforms extraction (`2026-09-14-extract-transforms`, step 2)
moved the mode-transform cluster into `transforms_common.py` /
`transforms_chat.py` / `transforms_response.py`. The settings extraction
(`2026-09-16-extract-settings`, step 3) moved the env-derived `SETTINGS` value
object and the shared `resolve_trace_file` chain into `settings.py` (imported by
both the server and the CLI; the import-time `SETTINGS` derivation is a declared
override of the guide's build-in-`main()` rule, recorded in that plan's Document
Overrides). The config/keys extraction (`2026-09-17-extract-config-keys`, step 4)
moved the config pipeline into `config.py`, the keys pipeline into `keys.py`, and
the string-emission-safety utility leaf into `safety.py` (a declared override of
the guide's §2/§3 role-grouping rule — see the plan's Document Overrides; the
amendment landed in claude-config as the utility-cluster genus, commit
`4210166`), and single-sourced the
CLI's template/keys/validation onto the shared policy. The compat extraction
(`2026-09-18-extract-compat`, step 5) moved the compatibility learner cluster
into `compat.py` behind an owned `_CompatState` state object with
default-parameter injection; it was a verbatim move plus a design step, and its
two verification gates were revised twice during implementation (nested-def
walkers, HEAD-sourced byte-identity, dotless ImportFrom matching).

Per-step line counts are deliberately not repeated here — they rot, and the plan
archives hold them. The remaining clusters (router/forwarder, admin/handler) are
tracked by the /refactor-split survey, which replaced the retired break-up
backlog report on 2026-09-16. New deep detail belongs in `doc/`, not here.
