# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Purpose

`claude-retry-proxy` is a stdlib-only HTTP retry proxy for the Claude API. It
listens on localhost, forwards requests to the upstream `ANTHROPIC_BASE_URL`
(read from `~/.claude/settings.json`), retries `429` and `503` responses with
jittered exponential backoff, and logs every request to a JSONL trace file.
A CLI manager swaps the `ANTHROPIC_BASE_URL` in `~/.claude/settings.json` to
`http://localhost:<port>` while the proxy runs and restores it on stop.

Extracted from the personal `claude-config` repo into a standalone, public,
pip-installable package. Zero runtime dependencies; Python 3.8+.

## Structure

```
src/claude_retry_proxy/
  __init__.py     __version__
  server.py       the HTTP retry proxy server (ThreadingHTTPServer, retry/backoff, trace logging)
  cli.py          the claude-retry-proxy CLI: start / stop / status (URL swap, lock files, crash recovery)
tests/
  test_claude_proxy.py   32 behavioral tests (ported + cleaned from claude-config; +3 for jitter/429; +5 for body preservation, disconnect catch, trace prune)
pyproject.toml   setuptools src-layout, console scripts, zero deps
LICENSE          MIT
```

Two console scripts (defined in `pyproject.toml` `[project.scripts]`):
- `claude-retry-proxy` → `claude_retry_proxy.cli:main` — the manager.
- `claude-retry-proxy-server` → `claude_retry_proxy.server:main` — direct server invocation.

## Build / Test / Run

```bash
pip install -e .                              # editable install (needs setuptools>=64)
claude-retry-proxy start                      # start the proxy (URL swap + launch server)
claude-retry-proxy status                     # show running/stopped/stale
claude-retry-proxy stop                       # stop + restore original URL
python tests/test_claude_proxy.py             # run the test suite
python -m claude_retry_proxy.cli --help       # PATH-independent invocation
python -m claude_retry_proxy.server --help
```

Start options: `--port` (default 8080), `--log <path>` (trace file; relative
paths resolve against cwd), `--all` (log full request/response bodies).

## Architecture

- **CLI `start`**: read+validate `ANTHROPIC_BASE_URL` from `~/.claude/settings.json`
  (reject localhost — proxy-to-self), acquire a swap lock (`O_EXCL`), swap the
  URL to `http://localhost:<port>`, **check and prune the trace log** (entries
  older than 5 days are removed; a one-line summary is printed), spawn the server via
  `python -m claude_retry_proxy.server --upstream-url <original>`, write a lock
  with the server PID, TCP-probe the port for readiness (2s), rollback on
  failure. Cross-platform PID liveness/kill via `ctypes` on Windows (`OpenProcess`
  + `WaitForSingleObject` / `TerminateProcess`), `os.kill` on POSIX.
- **Server**: `ThreadingHTTPServer` on 127.0.0.1. Per request: filter
  whitelisted headers, forward to upstream, retry on **429** and **503** /
  connection error with jittered exponential backoff
  (`PROXY_INITIAL_DELAY * 2**attempt`, capped at `PROXY_MAX_DELAY`, then ±25%
  uniform jitter, integer seconds). **429 retries use `PROXY_MAX_DELAY`**
  directly (maximal latency); 503 and connection errors use the exponential.
  Jitter draws from a **thread-local `random.Random()`** (the module-global
  `random` is not thread-safe under worker threads). Stream the response back,
  log a JSONL trace entry.
  `/admin/shutdown` (localhost-only) triggers graceful shutdown → `finally`
  block writes a `proxy_stop` marker and removes `proxy-state.json`.
  **Client disconnect catch:** `_send_response` is wrapped in
  `try/except _DISCONNECT_ERRORS` (`ConnectionResetError`,
  `BrokenPipeError`, `ConnectionAbortedError`); on disconnect, a
  `client_disconnect` trace event is logged instead of printing a
  traceback per occurrence. The `_log_client_disconnect` method wraps
  its own `log_trace` call in try/except to prevent re-raise.
  **Give-up body preservation:** when retries are exhausted on 429/503,
  `forward_request` drains the upstream error body (capped at
  `PROXY_MAX_BODY_SIZE` via `_read_capped`) and returns it to the client
  instead of `b''`. On connection-error exhaustion, a synthesized
  `upstream_unreachable` JSON body is returned (includes the sanitized
  last error string).
- **Upstream URL resolution** happens in `server.py main()` at runtime (not
  import time): `--upstream-url` if given, else `read_upstream_url()` from
  settings.json. Direct invocation emits a clean, source-attributed error if the
  URL can't be parsed.

## Environment Variables (server)

| Variable | Default | Description |
|----------|---------|-------------|
| `PROXY_PORT` | 8080 | Listen port (1024-65535) |
| `PROXY_MAX_RETRIES` | 10 | Max retry attempts (1-100). Shared by 429 and 503. |
| `PROXY_INITIAL_DELAY` | 1 | First backoff delay, seconds (1-60) |
| `PROXY_MAX_DELAY` | 30 | Backoff cap, seconds (1-300). Applied *before* jitter, so actual sleeps can exceed it by up to 25%. 429 retries use this value directly (jittered). |
| `PROXY_MAX_BODY_SIZE` | 10485760 | Request body size cap, bytes (1024-100MiB) → 413. Also caps the upstream error body drain on retry exhaustion (give-up path) via `_read_capped`. |
| `PROXY_LOG_ALL` | "" | Set to `1` to log full request/response bodies |
| `PROXY_TRACE_FILE` | `~/.claude/logs/proxy-trace.jsonl` | Trace log path |

Runtime artifacts (all under `~/.claude/`, hardcoded — see Gotchas):
`proxy/base-url.lock`, `proxy/url-swap.lock`, `proxy/proxy-state.json`,
`proxy/proxy-stderr.log`, `logs/proxy-trace.jsonl`. The trace log is pruned of
entries older than 5 days on each `claude-retry-proxy start` (best-effort;
does not block startup on failure).

## Gotchas

- **Settings coupling is hardcoded.** The proxy reads and swaps
  `ANTHROPIC_BASE_URL` in `~/.claude/settings.json`. There is no env-var
  fallback and no `--settings-path` flag (deliberate design decision).
- **`--all` / `PROXY_LOG_ALL` writes raw prompts and completions** to the
  plaintext trace file. `log_trace` and `write_state` apply `os.chmod(0o600)`
  on **POSIX only** (guarded by `os.name == 'posix'`) — on Windows `chmod` is a
  near-no-op (read-only bit only; no group/other model). Windows users must
  restrict the trace/state directory ACL manually (`icacls`).
- **Tests mutate the live `~/.claude/settings.json`.** 12 of the 24 tests
  exercise the CLI's URL swap; backup/restore protects the file, but a crash
  mid-test can leave settings pointing at localhost. Don't run the suite while a
  Claude Code session is active against the same settings.
- **12 CLI tests require a non-localhost `ANTHROPIC_BASE_URL`** in settings.json
  (the CLI correctly rejects localhost). Set it to a real upstream or mock
  before running the full suite; the 12 direct-server tests pass regardless.
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
- **`response-streaming-no-size-cap` is partially addressed.** The give-up
  drain is capped, but the **streaming success path** (the normal response
  read loop in `forward_request`) is still uncapped. The Open issue tracked
  in `## Future Work` remains open for the streaming path.
  out of scope of the jitter/429 plan) — a mid-retry request blocks
  `/admin/shutdown` for up to `MAX_RETRIES * jittered_max_delay`. Tracked as
  Open issue `shutdown-during-retry-sleep` in the jitter plan's Issue Log for
  a future hardening pass.

## Documentation

- [README.md](README.md) — user-facing: install, usage, configuration, trace
  log, the `--all` data-exposure warning, testing notes.
- Design rationale for the extraction lives in
  `tmp/plans/2026-07-17-extract-retry-proxy-design.md` (gitignored — planning
  artifact, not published).

No other supplementary docs.

## Future Work — TODO

Pre-existing upstream behaviors carried over from the `claude-config` extraction
(`src/claude_retry_proxy/server.py`, `src/claude_retry_proxy/cli.py`, ported
near-verbatim). Each is documented in
`tmp/plans/2026-07-17-extract-retry-proxy-design.md` (Risks) and tracked as an
Open issue in the plan's `## Issue Log`. Not blocking normal operation; deferred
to a future hardening plan.

- [ ] **Port-bind readiness race (Windows)** — `claude-retry-proxy start`'s TCP
  readiness probe can report success (exit 0) when the target port is already
  occupied, because the server's asynchronous bind failure races past the CLI's
  2s TCP probe (Windows `SO_REUSEADDR` semantics differ from POSIX). Result: a
  false "Proxy started" with `settings.json` pointing at `localhost:<port>`
  served by whatever was already there, not the retry proxy.
  - **Location:** `src/claude_retry_proxy/cli.py` `cmd_start` (spawn + TCP probe
    + `proc.poll()`). Upstream `bin/claude-proxy`, ported near-verbatim.
  - **Fix sketch:** make the CLI wait for the server subprocess to either bind
    successfully or exit with an error before reporting success — e.g. a
    readiness handshake on a stdout line the server prints once bound, or a
    health-check loop that distinguishes "bound" from "not yet failed".
  - **Tracking:** issue `start-early-exit-rollback-port-bind-race`
    ([report](tmp/reports/2026-07-17-extract-retry-proxy-start-early-exit-rollback-port-bind-race.json)).

- [ ] **Response body has no size cap (streaming path)** — `forward_request`
  streams the entire upstream success response into memory (8 KB chunk loop,
  appended to a list) with no size limit. Only the *request* body is capped
  (`PROXY_MAX_BODY_SIZE`, default 10 MB → 413), and the retry-exhaustion
  give-up drain is now also capped (via `_read_capped`). But the streaming
  success path remains uncapped. An abnormally large response (huge
  `max_tokens`, misconfigured/untrusted upstream) can grow the proxy's
  memory until the OS kills it (OOM). `ThreadingHTTPServer` has no
  thread-pool cap, so concurrent large responses compound the pressure.
  - **Location:** `src/claude_retry_proxy/server.py` `forward_request`
    (response read loop). Upstream, ported near-verbatim.
  - **Fix sketch:** cap streamed response bytes (a `PROXY_MAX_RESPONSE_SIZE`
    knob mirroring `PROXY_MAX_BODY_SIZE`); past the cap, abort the upstream
    read and return an error to the client. Optionally bound
    `ThreadingHTTPServer`'s thread pool.
  - **Tracking:** issue `response-streaming-no-size-cap` (Open in the plan's
    `## Issue Log`; no separate report file — identified during mega-audit
    iteration 1, audit ref M32).
