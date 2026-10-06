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
  compat.py             the compatibility learner: the `COMPAT_FEATURES` registry (two features — `context_management` in anthropic mode, `reasoning_field` in chat mode) whose descriptors own their mode, presence test, matcher, field set, retry budget and retry lock; COMPAT_* policy constants; the owned `_CompatState` state object (default-param `state=` injection); the `context_management` state machine with its 400-shape matchers, and the `reasoning_field` selection walk, matcher and latch (extracted from server.py; the probe-outcome + retry orchestration slice stays in server.py)
  sanitize.py           error-text redaction leaf: `sanitize_error`, the chokepoint for text reaching stderr, trace `error` fields and client-facing error bodies
  sinks.py              sink class family: private `_Sink` base, `TraceSink` (JSONL append + counters + markers), `StateSink` (atomic state document), shared `_SinkHealth` failure reporter, process-wide pair + `configure()`
  settings.py           env-derived settings singleton: `SETTINGS` value object (the `PROXY_*` limits/flags, runtime paths incl. state/compat files, mode values) + `resolve_trace_file` — built at import from env, adjusted by `main()` at startup; imported by both the server and the CLI
  config.py             the config.json + models.json document pair: `models_path_for` / `load_models_document` / `load_config` / `validate_config` (the canonical validation policy) / `write_config` / `install_template` + extra-header specs; serves the server and the CLI
  keys.py               keys-index pipeline: `vendor_key_entries`/`vendor_key_names`, `_validate_vendor_keys_shape`, `load_keys_file` (encrypted or plain), `read_passphrase_from_stdin`
  safety.py             task-shaped utility leaf: string-emission-safety predicates (`_validate_admin_name` charset allowlist); docstring indexes the stay-behind safety idioms
  transforms_common.py  shared endpoint-mode transform mechanism: `_transform_and_guard` (passthrough-on-failure response guard) + `_request_transform_timestamp` helper
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
claude-retry-proxy stop                       # stop the proxy
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
     `context_management` stripped retry and the `reasoning_field` candidate
     walk: both re-enter the forward path from the *client* body, so those do
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
  payloads); `POST /admin/api/switch` (writes a **tiers-only** `config.json`) and
  `/reload` (re-reads `models.json` — the provider catalog — and **never** the
  tier mapping); `POST /admin/shutdown`.
  Bodies are capped at 64 KB. Endpoint table and the Origin accept/reject sets:
  [doc/operations.html#admin](doc/operations.html#admin).

- **Drain-and-swap.** Config changes (switch and reload) set `_config_swapping`,
  wait for `_inflight_count` to reach zero (30 s timeout, 100 ms poll), swap
  under lock, and signal `_swap_done`; new requests block during a swap.
  `forward_request` snapshots config and vendors at entry and uses those
  snapshots throughout, so a mid-request change cannot affect it. The timeout
  aborts the swap, leaving the in-flight request to finish normally. **Shutdown
  does not use this path** — see Gotchas.
  [doc/architecture.html#config-swap](doc/architecture.html#config-swap).

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
  (`icacls`). The `extra_request_headers` trace field is NOT gated by `--all`:
  resolved values (e.g. the client's per-conversation session id) are logged on
  every request for providers with rules — the Windows caveat above applies to
  them too. [doc/trace-log.html#all](doc/trace-log.html#all)

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
| Chat mode never substitutes `input: {}` for tool arguments it could not parse — it degrades them to a visible placeholder block | [doc/provider-modes.html#malformed-args](doc/provider-modes.html#malformed-args) |
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
| Drain-and-swap aborts after 30 s if a request is stuck in retry backoff | [doc/architecture.html#config-swap](doc/architecture.html#config-swap) |
| Readiness is two-phase: the `READY` marker (5 s), then a TCP probe (2 s) | [doc/operations.html#readiness](doc/operations.html#readiness) |
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
    suppression) and the `reasoning_field` selection (model, walk, matcher,
    latch), plus the shared persistence and events
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

## Unresolved Deferred Issues

```json
[
{"issue_id": "extract-model-raises-on-non-object-json", "title": "extract_model raises AttributeError on valid JSON that is not an object, so do_POST aborts with no HTTP response; the unguarded call at do_POST pre-empts the whole downstream guard chain", "target_repo": null, "report": "./tmp/reports/defer-issue-extract-model-raises-on-non-object-json.json", "deferred": "2026-09-12", "date_source": "creation"},
{"issue_id": "image-content-blocks-chat-mode", "title": "Chat mode: image content blocks not transformed between Anthropic and OpenAI formats", "target_repo": null, "report": "./tmp/reports/defer-issue-image-content-blocks-chat-mode.json", "deferred": "2026-08-29", "date_source": "creation"},
{"issue_id": "no-proxy-stop-trace-warning", "title": "Full-suite run warns 'No proxy_stop event in trace' when the proxy is terminated abruptly (low priority)", "target_repo": null, "report": "./tmp/reports/defer-issue-no-proxy-stop-trace-warning.json", "deferred": "2026-09-14", "date_source": "creation"},
{"issue_id": "port-default-collision-hazard", "title": "A start on the default port can report success against a pre-existing listener: the readiness TCP probe cannot distinguish the spawned child's socket from a live proxy already on 8080", "target_repo": null, "report": "./tmp/reports/defer-issue-port-default-collision-hazard.json", "deferred": "2026-09-18", "date_source": "creation"},
{"issue_id": "proxy-stderr-append-stale-tail", "title": "proxy-stderr.log is append-only across runs, so read_tail failure diagnostics can surface lines from previous sessions instead of the current attempt", "target_repo": null, "report": "./tmp/reports/defer-issue-proxy-stderr-append-stale-tail.json", "deferred": "2026-09-18", "date_source": "creation"},
{"issue_id": "client-body-recursionerror-no-response", "title": "A deeply nested client body raises RecursionError out of the request path: the parse guards omit it (RecursionError is not a ValueError) and neither forward_request nor do_POST fences the call, so the request aborts with no HTTP response", "target_repo": null, "report": "./tmp/reports/defer-issue-client-body-recursionerror-no-response.json", "deferred": "2026-09-30", "date_source": "creation"},
{"issue_id": "httpx2-native-sse-transport", "title": "Adopt httpx2 for upstream transport and native SSE parsing: client.sse() replaces the hand-rolled SSE frame scanner and obsoletes httpx-sse", "target_repo": null, "report": "./tmp/reports/defer-issue-httpx2-native-sse-transport.json", "deferred": "2026-09-27", "date_source": "creation"},
{"issue_id": "cli-pre-existing-remove-idiom-copies", "title": "tests/test_cli.py still hand-rolls the guarded state-file removal at 8 test-body sites, one file over from the shared _remove_test_state_file() helper that Step 5 introduced to eliminate exactly that hazard", "target_repo": null, "report": "./tmp/reports/defer-issue-cli-pre-existing-remove-idiom-copies.json", "deferred": "2026-10-04", "date_source": "creation"},
{"issue_id": "posix-sigterm-shutdown-deadlock", "title": "server.py's SIGTERM handler calls server.shutdown() on the serve_forever thread, which socketserver documents as a guaranteed deadlock: on POSIX one SIGTERM permanently wedges the proxy while claude-retry-proxy stop reports success", "target_repo": null, "report": "./tmp/reports/defer-issue-posix-sigterm-shutdown-deadlock.json", "deferred": "2026-10-04", "date_source": "creation"},
{"issue_id": "operate-round-ends-turn-before-waiting", "title": "Unattended --operate rounds frequently end their turn while a background full-suite run is still in flight, killing the run and leaving the round with no session report", "target_repo": "claude-config", "report": "./tmp/reports/defer-issue-operate-round-ends-turn-before-waiting.json", "deferred": "2026-10-04", "date_source": "creation"},
{"issue_id": "chat-sse-done-framing-assumption", "title": "A `data: [DONE]` frame without a trailing blank line is never assembled, so saw_done stays 0 and a protocol-complete chat-mode stream is closed with a retryable error instead of a synthesised terminal sequence", "target_repo": null, "report": "./tmp/reports/defer-issue-chat-sse-done-framing-assumption.json", "deferred": "2026-10-04", "date_source": "creation"},
{"issue_id": "chat-sse-late-frame-offsets-unasserted", "title": "first_late_ms and last_late_ms are gated only by the structural step-2 script and never asserted behaviorally, so the null-vs-set distinction — the one that separates a stream that ended at the finish frame from one that drained — is unpinned by any committed test", "target_repo": null, "report": "./tmp/reports/defer-issue-chat-sse-late-frame-offsets-unasserted.json", "deferred": "2026-10-04", "date_source": "creation"}
]```

## Future Work — TODO

Twelve deferred issues remain (see above); the three newest were filed on
2026-10-04 by plan 2026-10-04-truncation-error-and-drain-trace's Phase 6
review, all in the chat-mode SSE path that plan reworked — a `[DONE]` sentinel
with no trailing blank line that never assembles (so a protocol-complete stream
is errored and retried), the two late-frame offset fields asserted only
structurally and never behaviorally, and a detector predicate that counted a
proxy-side tool-block degradation as a model omission, which plan
2026-10-05-chat-retry-nudge resolved on 2026-10-06 with the
`not tool_calls_seen` clause (the nudge it ships errors the unarmed turn and
nudges the recovery — `PROXY_CHAT_RETRY_NUDGE`, kill-switchable; the two
chat-SSE issues above remain open). The
previous three were filed on
2026-10-04 by plan 2026-10-03-stale-test-state-file-pid-reuse's closeout — the
POSIX-only deadlock in the server's SIGTERM handler (it calls
`server.shutdown()` on the `serve_forever` thread, which `socketserver`
documents as a guaranteed hang), the residual hand-rolled state-file removals in
`tests/test_cli.py` that could now call the shared helper, and, against
`claude-config`, the unattended-round launcher ending its turn while a
background suite is still in flight. The previous newest,
`client-body-recursionerror-no-response`, was filed on 2026-09-30 by plan
2026-09-29-chat-reasoning-field-learner's code review — the client-body parse
was left unhardened while the plan's own upstream-body helper was made total
against the same failure class. Plan
2026-10-03-stale-test-state-file-pid-reuse resolved the test-isolation defect
where a fixed machine-global `PROXY_STATE_FILE` survived each run: the path is
now keyed to the runner PID, cleared at harness import and after every test in
`run_cli`'s loop. Plan
2026-09-23-drop-dead-failed-confirmations-field resolved the compatibility
entry's dead `failed_confirmations` field — the persisted schema no longer
carries it, and the in-memory suppression counter it shadowed is unchanged.
Plan
2026-09-15-sanitize-sinks-deferred resolved the five extract-sinks deferred
issues — the `sanitize_error` exponential-backtracking regex and its inert
Windows path redaction, `write_state`'s lock-free concurrent `os.replace`, the
state sink's stray `.tmp` on an empty path, and the POSIX-only sink `chmod`
branch, untested on the Windows dev box. The doc-tree plan's two findings —
the missing committed anchor check and the raw-Markdown `../README.md` link —
were resolved by 2026-09-14-commit-doc-anchor-check. The CodeGraph prompt-hook
entry (indexed 2026-09-13 without a report file) was removed on 2026-09-15 —
resolved by other repos. Unresolved: chat-mode image content block mapping,
the doc-tree plan's surviving finding (`extract_model` raising on
non-object JSON), and the no-`proxy_stop` trace warning. The large source/test file
split and the module-split guidance consolidation were retired 2026-09-16 by
the global refactor-split consolidation (claude-config plan
2026-09-16-refactor-split-skill): the extraction doctrine now lives in the
global guide, and the /refactor-split survey tracks oversized-file state,
superseding the retired break-up backlog report.

The `sanitize.py` + `sinks.py` extraction (2026-09-12) was the first step of the
staged decomposition prescribed by the global refactor-split guidance; the
transforms extraction (`2026-09-14-extract-transforms`) landed 2026-09-15 as
step 2 — `server.py` 4,650 → 3,719 wc lines, with the mode-transform cluster
now in `transforms_common.py` / `transforms_chat.py` / `transforms_response.py`.
The settings extraction (`2026-09-16-extract-settings`) landed 2026-09-16 as
step 3 — `server.py` 3,719 → 3,661 wc lines, with the env-derived `SETTINGS`
value object and the shared `resolve_trace_file` chain in `settings.py`
(imported by both the server and the CLI; the import-time `SETTINGS`
derivation is a declared override of the guide's build-in-`main()` rule,
recorded in that plan's Document Overrides).
The config/keys extraction (`2026-09-17-extract-config-keys`) landed
2026-09-18 as step 4 — `server.py` 3,661 → 3,129 wc lines, with the config
pipeline in `config.py`, the keys pipeline in `keys.py`, the
string-emission-safety utility leaf in `safety.py` (a declared override of the
guide's §2/§3 role-grouping rule — see the plan's Document Overrides; the
doctrine amendment itself is deferred to claude-config), and the CLI's
template/keys/validation single-sourced onto the shared policy.
The compat extraction (`2026-09-18-extract-compat`) landed 2026-09-19 as
step 5 — `server.py` 3,129 → 2,613 wc lines, with the compatibility learner
cluster in `compat.py` (569 wc lines) behind an owned `_CompatState` state
object with default-parameter injection; the extraction was a verbatim move
plus a design step, and the moving plan's two verification gates were
revised twice during implementation (nested-def walkers, HEAD-sourced
byte-identity, dotless ImportFrom matching).
The remaining clusters (router/forwarder, admin/handler) are
tracked by the /refactor-split survey, which replaced the retired break-up
backlog report on 2026-09-16. New deep detail belongs in `doc/`, not here.
