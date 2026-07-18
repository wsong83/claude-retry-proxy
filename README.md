# claude-retry-proxy

A local HTTP retry proxy for the Claude API. It listens on `localhost`, forwards
requests to your upstream `ANTHROPIC_BASE_URL`, retries `503` (Service
Unavailable) responses with exponential backoff, and logs every request to a
JSONL trace file.

It works with **any** `ANTHROPIC_BASE_URL` — official Anthropic, a third-party
provider, or a self-hosted gateway. The proxy is provider-agnostic.

Stdlib-only. Zero runtime dependencies. Python 3.8+. MIT licensed.

## Why

Some upstream endpoints return `503` under load. Claude Code treats a `503` as a
hard failure, so a transiently-busy provider interrupts your session. This proxy
sits between Claude Code and the upstream, transparently retrying `503`s (and
connection errors) with exponential backoff so a busy provider doesn't abort
your work.

## Install

From git (editable, for development):

```bash
pip install -e .
```

Requires `setuptools >= 64` (for PEP 660 src-layout editable installs). Python
3.8 or newer.

## Quick start

```bash
# 1. Make sure ANTHROPIC_BASE_URL in ~/.claude/settings.json points at a real
#    (non-localhost) upstream, e.g. https://api.anthropic.com

# 2. Start the proxy (swaps settings.json to http://localhost:8080 while running)
claude-retry-proxy start

# 3. Use Claude Code as usual — its traffic now flows through the proxy

# 4. Stop the proxy (restores the original URL)
claude-retry-proxy stop
```

Check state at any time:

```bash
claude-retry-proxy status
```

## How it works

When you run `claude-retry-proxy start`:

1. It reads the current `ANTHROPIC_BASE_URL` from `~/.claude/settings.json` and
   validates it (rejects localhost — the proxy cannot proxy to itself).
2. It saves the original URL to a lock file (`~/.claude/proxy/base-url.lock`).
3. It rewrites `ANTHROPIC_BASE_URL` in `settings.json` to
   `http://localhost:<port>`.
4. It launches the proxy server, which forwards requests to the original URL
   with retry handling.

`claude-retry-proxy stop` reverses this: graceful HTTP shutdown of the server,
then the original URL is restored to `settings.json` and the lock is removed.

Because the URL lives in `settings.json`, **the proxy is coupled to Claude
Code's config** — it reads and writes `ANTHROPIC_BASE_URL` there. This is
deliberate; there is no env-var fallback or `--settings-path` flag.

## Usage

```
Usage: claude-retry-proxy <command> [options]

Commands:
  start   Start the proxy (URL swap + launch proxy server)
  stop    Stop the proxy and restore original URL
  status  Show proxy status
```

### `start` options

```
claude-retry-proxy start [-h] [--port PORT] [--log LOG] [--all]

  --port, -p PORT  Port to listen on (default: 8080)
  --log, -l LOG    Trace log file path
  --all, -a        Log full request/response bodies
```

Examples:

```bash
claude-retry-proxy start --port 9090
claude-retry-proxy start --log /tmp/trace.jsonl
claude-retry-proxy start --all            # log full request + response bodies
```

### Direct server invocation

The server can also be run directly (the `start` subcommand normally does this
for you):

```bash
claude-retry-proxy-server --port 8080 --upstream-url https://api.anthropic.com
# or
python -m claude_retry_proxy.server --port 8080 --upstream-url https://api.anthropic.com
```

`--upstream-url` overrides what the server would otherwise read from
`settings.json`. Without it, the server reads `ANTHROPIC_BASE_URL` from
`~/.claude/settings.json`.

## Configuration

All knobs are environment variables (read by the server at startup). Defaults
are safe; override only if you need to.

| Variable | Default | Range | Description |
|----------|---------|-------|-------------|
| `PROXY_PORT` | `8080` | 1024–65535 | Port to listen on |
| `PROXY_MAX_RETRIES` | `10` | 1–100 | Max retry attempts per request |
| `PROXY_INITIAL_DELAY` | `1` | 1–60 | First backoff delay, seconds |
| `PROXY_MAX_DELAY` | `30` | 1–300 | Backoff cap, seconds |
| `PROXY_MAX_BODY_SIZE` | `10485760` | 1024–100 MiB | Request body size cap (bytes); larger → 413 |
| `PROXY_LOG_ALL` | unset | `1` to enable | Log full request **and** response bodies |
| `PROXY_TRACE_FILE` | `~/.claude/logs/proxy-trace.jsonl` | path | Trace log location |

Backoff is `PROXY_INITIAL_DELAY * 2**attempt`, capped at `PROXY_MAX_DELAY`.

> **Worst case:** with the max bounds (`PROXY_MAX_RETRIES=100`,
> `PROXY_MAX_DELAY=300`), a single request that keeps getting `503` can block a
> worker thread for up to ~8.3 hours. With the defaults (10 retries, 30 s cap)
> the worst case is about 5 minutes per request.

## Trace log

Default location: `~/.claude/logs/proxy-trace.jsonl` (one JSON object per line).

Each request logs: timestamp, method, path, model, status, http_status, retry
count, total latency, first-byte latency, and a sanitized error. Lifecycle
markers (`proxy_start`, `proxy_stop`) and per-retry events are also logged.

Use `--all` (or `PROXY_LOG_ALL=1`) to include full request and response bodies.

### ⚠️ Data exposure with `--all` / `PROXY_LOG_ALL`

With `--all`, the trace file contains **raw prompts and completions** in
plaintext. The proxy applies `0600` permissions to the trace and state files on
**POSIX** systems. On **Windows**, `chmod` is effectively a no-op (it only
toggles the read-only attribute; there is no Unix group/other model), so you
must restrict the trace directory's ACL yourself, e.g.:

```powershell
icacls "$env:USERPROFILE\.claude\logs" /inheritance:r /grant:r "$env:USERNAME:(OI)(CI)F"
```

Point `PROXY_TRACE_FILE` at a directory with restrictive permissions regardless
of platform if you enable `--all`.

## Features

- **Automatic retries** — `503` and connection errors retried with exponential
  backoff (default 10 attempts).
- **URL swapping** — original `ANTHROPIC_BASE_URL` saved and restored
  automatically; no manual config editing.
- **Crash recovery** — if the proxy is killed without `stop`, a stale lock is
  detected on the next `start` and the original URL is restored.
- **Concurrent sessions** — `ThreadingHTTPServer` handles multiple in-flight
  requests.
- **Localhost-only** — the proxy binds `127.0.0.1`; it is not reachable from
  the network.
- **Provider-agnostic** — works with any `ANTHROPIC_BASE_URL`.
- **Zero dependencies** — Python standard library only.

## Files written at runtime

While the proxy runs, it creates (all under `~/.claude/`):

| Path | Purpose |
|------|---------|
| `settings.json` (`env.ANTHROPIC_BASE_URL`) | Swapped to `http://localhost:<port>` while running, restored on `stop` |
| `proxy/base-url.lock` | The URL-swap lock (original URL, port, server PID) |
| `proxy/url-swap.lock` | Cross-process lock serializing `start`/`stop` |
| `proxy/proxy-state.json` | Runtime state (PID, port, heartbeat); removed on clean shutdown |
| `proxy/proxy-stderr.log` | Server stderr (startup messages, retry notices) |
| `logs/proxy-trace.jsonl` | The JSONL request trace |

## Testing

```bash
pip install -e .
python tests/test_claude_proxy.py
```

The suite has 24 tests. **12 of them exercise the CLI's URL swap and require
`ANTHROPIC_BASE_URL` in `~/.claude/settings.json` to be a non-localhost URL**
(the proxy correctly rejects localhost to avoid proxying to itself). Set it to a
real upstream or a mock before running the full suite. The other 12 tests start
the server directly with mock upstreams and pass regardless.

> The tests back up and restore `~/.claude/settings.json`, but during a run your
> live config is temporarily altered. Don't run the suite while a Claude Code
> session is active against the same settings file, and avoid interrupting it
> mid-test (a crash can leave `settings.json` pointing at localhost — run
> `claude-retry-proxy stop` to recover).

## License

MIT. See [LICENSE](LICENSE).
