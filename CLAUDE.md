# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Purpose

`claude-retry-proxy` is a stdlib-only HTTP retry proxy for the Claude API. It
listens on localhost, forwards requests to the upstream `ANTHROPIC_BASE_URL`
(read from `~/.claude/settings.json`), retries `503` responses with exponential
backoff, and logs every request to a JSONL trace file. A CLI manager swaps the
`ANTHROPIC_BASE_URL` in `~/.claude/settings.json` to `http://localhost:<port>`
while the proxy runs and restores it on stop.

Extracted from the personal `claude-config` repo into a standalone, public,
pip-installable package. Zero runtime dependencies; Python 3.8+.

## Structure

```
src/claude_retry_proxy/
  __init__.py     __version__
  server.py       the HTTP retry proxy server (ThreadingHTTPServer, retry/backoff, trace logging)
  cli.py          the claude-retry-proxy CLI: start / stop / status (URL swap, lock files, crash recovery)
tests/
  test_claude_proxy.py   24 behavioral tests (ported + cleaned from claude-config)
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
  URL to `http://localhost:<port>`, spawn the server via
  `python -m claude_retry_proxy.server --upstream-url <original>`, write a lock
  with the server PID, TCP-probe the port for readiness (2s), rollback on
  failure. Cross-platform PID liveness/kill via `ctypes` on Windows (`OpenProcess`
  + `WaitForSingleObject` / `TerminateProcess`), `os.kill` on POSIX.
- **Server**: `ThreadingHTTPServer` on 127.0.0.1. Per request: filter
  whitelisted headers, forward to upstream, retry on 503 / connection error with
  exponential backoff (`PROXY_INITIAL_DELAY * 2**attempt`, capped at
  `PROXY_MAX_DELAY`), stream the response back, log a JSONL trace entry.
  `/admin/shutdown` (localhost-only) triggers graceful shutdown → `finally`
  block writes a `proxy_stop` marker and removes `proxy-state.json`.
- **Upstream URL resolution** happens in `server.py main()` at runtime (not
  import time): `--upstream-url` if given, else `read_upstream_url()` from
  settings.json. Direct invocation emits a clean, source-attributed error if the
  URL can't be parsed.

## Environment Variables (server)

| Variable | Default | Description |
|----------|---------|-------------|
| `PROXY_PORT` | 8080 | Listen port (1024-65535) |
| `PROXY_MAX_RETRIES` | 10 | Max retry attempts (1-100) |
| `PROXY_INITIAL_DELAY` | 1 | First backoff delay, seconds (1-60) |
| `PROXY_MAX_DELAY` | 30 | Backoff cap, seconds (1-300) |
| `PROXY_MAX_BODY_SIZE` | 10485760 | Request body size cap, bytes (1024-100MiB) → 413 |
| `PROXY_LOG_ALL` | "" | Set to `1` to log full request/response bodies |
| `PROXY_TRACE_FILE` | `~/.claude/logs/proxy-trace.jsonl` | Trace log path |

Runtime artifacts (all under `~/.claude/`, hardcoded — see Gotchas):
`proxy/base-url.lock`, `proxy/url-swap.lock`, `proxy/proxy-state.json`,
`proxy/proxy-stderr.log`, `logs/proxy-trace.jsonl`.

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
- **Worst-case retry hold**: with env maxes (`PROXY_MAX_RETRIES=100`,
  `PROXY_MAX_DELAY=300`), a single 503-ing request can block a worker thread
  for ~8.3h. Defaults (10 retries, 30s cap) give ~5min worst case.

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

- [ ] **Response body has no size cap** — `forward_request` streams the entire
  upstream response into memory (8 KB chunk loop, appended to a list) with no
  size limit. Only the *request* body is capped (`PROXY_MAX_BODY_SIZE`,
  default 10 MB → 413). An abnormally large response (huge `max_tokens`,
  misconfigured/untrusted upstream) can grow the proxy's memory until the OS
  kills it (OOM), taking down all concurrent sessions. `ThreadingHTTPServer`
  has no thread-pool cap, so concurrent large responses compound the pressure.
  - **Location:** `src/claude_retry_proxy/server.py` `forward_request`
    (response read loop). Upstream, ported near-verbatim.
  - **Fix sketch:** cap streamed response bytes (a `PROXY_MAX_RESPONSE_SIZE`
    knob mirroring `PROXY_MAX_BODY_SIZE`); past the cap, abort the upstream
    read and return an error to the client. Optionally bound
    `ThreadingHTTPServer`'s thread pool.
  - **Tracking:** issue `response-streaming-no-size-cap` (Open in the plan's
    `## Issue Log`; no separate report file — identified during mega-audit
    iteration 1, audit ref M32).
