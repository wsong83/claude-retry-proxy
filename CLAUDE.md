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

This file is the operational summary. The `doc/` tree holds the deep reference —
rationale, mechanisms, and edge cases — and is indexed by
[doc/content.html](doc/content.html).

## Structure

```
src/claude_retry_proxy/
  __init__.py           __version__
  server.py             the HTTP retry gateway server (ThreadingHTTPServer, tier routing, model rewriting, admin API, retry/backoff)
  sanitize.py           error-text redaction leaf: `sanitize_error`, the chokepoint for text reaching stderr, trace `error` fields and client-facing error bodies
  sinks.py              sink class family: private `_Sink` base, `TraceSink` (JSONL append + counters + markers), `StateSink` (atomic state document), shared `_SinkHealth` failure reporter, process-wide pair + `configure()`
  cli.py                the claude-retry-proxy CLI: start / stop / status / reload (passphrase prompt, config validation, no URL swap)
  vimcrypt.py           vim blowfish2 (VimCrypt~03!) decryption (derived from claude-config bin/vimcrypt.py)
  admin.html            admin page for hot-switching tier mappings (served at /admin/)
src/templates/
  config.json     template for ~/.claude/proxy/config.json (copied on first start)
  keys-index.json template for ~/.claude/keys-index.json (single-key `key` string
                  or multi-key `keys` name→payload object)
tests/            per-area test modules + aggregator; see doc/test-catalog.html
scripts/
  analyze_proxy_trace.py  trace log analysis tool (model stats, latency, success rates)
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
claude-retry-proxy reload                     # reload config.json from disk into running proxy
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

- **CLI `start`:** ensure `~/.claude/proxy/config.json` exists (else copy the
  template, exit 1); prompt the passphrase via `vimcrypt.prompt_hidden`; decrypt
  the keys file; validate the config against the decrypted vendors; prune the
  trace log (>5 days); spawn `python -m claude_retry_proxy.server --port <port>
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
     bytes. (The compatibility retry is the exception: it strips the feature
     from the *client* body and re-enters the forward path, so that one does
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
  payloads); `POST /admin/api/switch` and `/reload`; `POST /admin/shutdown`.
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

[doc/configuration.html#env-vars](doc/configuration.html#env-vars) is the
authoritative reference and carries the same table with prose.

Runtime artifacts (all under `~/.claude/`, paths overridable via env vars — see
table above): `proxy/config.json`, `proxy/proxy-state.json`,
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
  `PROXY_TRACE_FILE`, `PROXY_STATE_FILE`, and `PROXY_FEATURE_COMPAT_FILE` to
  session temp paths at module load, *before* importing `cli.py` or `server.py`
  (both bind those env vars to module constants at import time). A test proxy
  therefore cannot touch the live proxy's files, and the old docstring warning
  about not running tests alongside a live proxy is obsolete.
  [doc/test-catalog.html#isolation](doc/test-catalog.html#isolation)

### Moved out of this section

These were Gotchas bullets. The mechanism now lives in `doc/`; the one-liner is
what you need in context, and the link has the rest.

| In one line | Detail |
|---|---|
| Provider mode dispatch — `anthropic`/`chat`/`response` differ in auth header, path, and both body transforms | [doc/provider-modes.html](doc/provider-modes.html) |
| Chat mode degrades unparseable tool arguments to a visible placeholder block, never `input: {}` | [doc/provider-modes.html#malformed-args](doc/provider-modes.html#malformed-args) |
| A vendor carries either `key` (string) or `keys` (name→payload); a tier's `key` selector picks one | [doc/configuration.html#multi-key](doc/configuration.html#multi-key) |
| The keys file may be plain JSON — convenient, but the keys then sit unencrypted on disk | [doc/configuration.html#encryption](doc/configuration.html#encryption) |
| Validation flows config→keys, not the reverse, and is strict | [doc/configuration.html#validation](doc/configuration.html#validation) |
| `disable_retry_claude_count_token` skips retrying `count_tokens` (template default `true`) | [doc/configuration.html#count-tokens-flag](doc/configuration.html#count-tokens-flag) |
| Trace/state I/O failures degrade the proxy; they never stop it — except at startup, which fails fast | [doc/architecture.html#sinks](doc/architecture.html#sinks) |
| Responses are truncated at `PROXY_MAX_RESPONSE_SIZE` with a `response_size_cap_exceeded` event | [doc/architecture.html#size-caps](doc/architecture.html#size-caps) |
| On 429/503 exhaustion the upstream error body is preserved and returned; connection errors get a synthesized body | [doc/architecture.html#give-up](doc/architecture.html#give-up) |
| Integer-second jitter is degenerate for `base ∈ {1, 2}` — zero de-sync; effective from `base ≥ 3` | [doc/architecture.html#jitter](doc/architecture.html#jitter) |
| Heartbeat state is in-memory; `proxy-state.json` is a projection rewritten every 30 s | [doc/architecture.html#heartbeat](doc/architecture.html#heartbeat) |
| Shutdown kills in-flight requests — it does not drain them, and the killed request's trace entry never lands | [doc/operations.html#shutdown](doc/operations.html#shutdown) |
| Drain-and-swap aborts after 30 s if a request is stuck in retry backoff | [doc/architecture.html#config-swap](doc/architecture.html#config-swap) |
| Readiness is two-phase: the `READY` marker (5 s), then a TCP probe (2 s) | [doc/operations.html#readiness](doc/operations.html#readiness) |
| A client-write `OSError` outside `_DISCONNECT_ERRORS` can be misread as a connection error and re-issue the POST | [doc/architecture.html#disconnects](doc/architecture.html#disconnects) |

## Refactoring

- **Before planning any code split — extracting a module, a class family, or a
  cluster of functions out of a large file — read
  [`.claude/cluster-extraction-criteria.md`](.claude/cluster-extraction-criteria.md)
  first.** It carries the membership tests, the state doctrine, the blast-radius
  ordering rule, and the staging discipline this repo's extractions follow.
  Deliberately not inlined here: it is needed only when a refactor is on the
  table, not in every session.

## Documentation

- **[doc/content.html](doc/content.html) — the human-facing reference.** Start
  here; it indexes the whole tree.
  - [architecture.html](doc/architecture.html) — request path, tier resolution,
    retry/backoff, give-up, size caps, disconnects, config swap, heartbeat,
    sinks, shutdown
  - [provider-modes.html](doc/provider-modes.html) — the three endpoint modes,
    auth, paths, request/response transforms, SSE, tool-call degradation
  - [configuration.html](doc/configuration.html) — `config.json`,
    `keys-index.json`, environment variables, validation
  - [operations.html](doc/operations.html) — CLI, readiness, passphrase, admin
    API and CSRF, shutdown, runtime artifacts
  - [compatibility.html](doc/compatibility.html) — the `context_management`
    learner: constants, states, transitions, suppression, persistence, events
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
{"issue_id": "image-content-blocks-chat-mode", "title": "Chat mode: image content blocks not transformed between Anthropic and OpenAI formats", "target_repo": null, "report": "./tmp/reports/defer-issue-image-content-blocks-chat-mode.json", "deferred": "2026-08-29", "date_source": "creation"},
{"issue_id": "break-up-large-source-and-test-files", "title": "Break up large source and test files into smaller modules", "target_repo": null, "report": "./tmp/reports/defer-issue-break-up-large-source-and-test-files.json", "deferred": "2026-09-01", "date_source": "creation"},
{"issue_id": "write-state-no-lock-concurrent-replace", "title": "write_state takes no lock and writes through a fixed temp path, so concurrent writers can interleave before os.replace", "target_repo": null, "report": "./tmp/reports/defer-issue-write-state-no-lock-concurrent-replace.json", "deferred": "2026-09-11", "date_source": "creation"},
{"issue_id": "sanitize-error-path-redaction-inert-on-windows", "title": "sanitize_error's path-redaction arm requires a forward slash, so it silently does nothing for native Windows paths", "target_repo": null, "report": "./tmp/reports/defer-issue-sanitize-error-path-redaction-inert-on-windows.json", "deferred": "2026-09-12", "date_source": "creation"},
{"issue_id": "sanitize-error-regex-catastrophic-backtracking", "title": "sanitize_error's first regex arm backtracks exponentially, so upstream-controlled error text can hang a worker thread", "target_repo": null, "report": "./tmp/reports/defer-issue-sanitize-error-regex-catastrophic-backtracking.json", "deferred": "2026-09-12", "date_source": "creation"},
{"issue_id": "sink-chmod-branch-untested-outside-posix", "title": "The sink chmod 0o600 branch is POSIX-only, so no test on the Windows dev box ever executes it", "target_repo": null, "report": "./tmp/reports/defer-issue-sink-chmod-branch-untested-outside-posix.json", "deferred": "2026-09-12", "date_source": "creation"},
{"issue_id": "state-sink-empty-path-stray-tmp", "title": "An empty state path makes the state sink leave a stray .tmp file in the process working directory", "target_repo": null, "report": "./tmp/reports/defer-issue-state-sink-empty-path-stray-tmp.json", "deferred": "2026-09-12", "date_source": "creation"},
{"issue_id": "compat-entry-failed-confirmations-dead-field", "title": "The persisted compatibility entry carries a failed_confirmations field that is never incremented, so it always reads 0", "target_repo": null, "report": "./tmp/reports/defer-issue-compat-entry-failed-confirmations-dead-field.json", "deferred": "2026-09-12", "date_source": "creation"},
{"issue_id": "extract-model-raises-on-non-object-json", "title": "extract_model raises AttributeError on valid JSON that is not an object, so do_POST aborts with no HTTP response; the unguarded call at do_POST pre-empts the whole downstream guard chain", "target_repo": null, "report": "./tmp/reports/defer-issue-extract-model-raises-on-non-object-json.json", "deferred": "2026-09-12", "date_source": "creation"},
{"issue_id": "extraction-criteria-link-dead-in-public", "title": "CLAUDE.md tells the reader to read .claude/cluster-extraction-criteria.md first, but that file is untracked in a public repo", "target_repo": null, "report": "./tmp/reports/defer-issue-extraction-criteria-link-dead-in-public.json", "deferred": "2026-09-12", "date_source": "creation"},
{"issue_id": "review-anchor-resolver-not-committed", "title": "No committed check keeps the doc anchors referenced from CLAUDE.md and README.md valid", "target_repo": null, "report": "./tmp/reports/defer-issue-review-anchor-resolver-not-committed.json", "deferred": "2026-09-13", "date_source": "creation"},
{"issue_id": "review-content-readme-link-raw-markdown", "title": "doc/content.html links ../README.md, which renders as raw Markdown in a browser", "target_repo": null, "report": "./tmp/reports/defer-issue-review-content-readme-link-raw-markdown.json", "deferred": "2026-09-13", "date_source": "creation"}
]```

## Future Work — TODO

Twelve deferred issues remain (see above). Five are newly indexed: the doc-tree
plan's two — no committed check keeps the anchors CLAUDE.md cites into `doc/` valid,
and the raw-Markdown `../README.md` link — plus three pre-existing defects catalogued
for the first time (`extract_model` raising on non-object JSON, the compatibility
entry's dead `failed_confirmations` field, and the dead extraction-criteria link).
The other seven are unchanged: chat-mode image content block mapping, the large
source/test file split, `sanitize_error`'s exponential-backtracking regex and its
inert Windows path redaction, `write_state`'s lock-free concurrent `os.replace`, the
state sink's stray `.tmp` on an empty path, and the POSIX-only sink `chmod` branch,
untested on the Windows dev box.

The `sanitize.py` + `sinks.py` extraction (2026-09-12) was the first step of the
staged decomposition in `.claude/cluster-extraction-criteria.md`. New deep
detail belongs in `doc/`, not here.
