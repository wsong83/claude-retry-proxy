# claude-retry-proxy

A local HTTP retry proxy for the Claude API. It listens on `localhost`, forwards
requests to your upstream `ANTHROPIC_BASE_URL`, retries `429` (Too Many
Requests) and `503` (Service Unavailable) responses with jittered exponential
backoff, and logs every request to a JSONL trace file.

It works with **any** `ANTHROPIC_BASE_URL` — official Anthropic, a third-party
provider, or a self-hosted gateway. The proxy is provider-agnostic.

Stdlib-only. Zero runtime dependencies. Python 3.8+. MIT licensed.

## Why

Some upstream endpoints return `503` under load or `429` when rate-limiting.
Claude Code treats a `503` as a hard failure, so a transiently-busy provider
interrupts your session. This proxy sits between Claude Code and the upstream,
transparently retrying `429`s, `503`s, and connection errors with jittered
exponential backoff so a busy provider doesn't abort your work. Jitter
(±25% per delay, de-synchronized per thread) prevents concurrent sessions
from re-stampeding the upstream in lockstep.

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
2. It checks the trace log and prunes entries older than 5 days, printing a
   one-line summary (best-effort; a failure does not block startup).
3. It saves the original URL to a lock file (`~/.claude/proxy/base-url.lock`).
4. It rewrites `ANTHROPIC_BASE_URL` in `settings.json` to
   `http://localhost:<port>`.
5. It launches the proxy server, which forwards requests to the original URL
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
claude-retry-proxy start --all            # log full request bodies (+ error response bodies)
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
| `PROXY_MAX_RETRIES` | `10` | 1–100 | Max retry attempts per request (shared by 429 and 503) |
| `PROXY_INITIAL_DELAY` | `1` | 1–60 | First backoff delay, seconds |
| `PROXY_MAX_DELAY` | `30` | 1–300 | Backoff cap, seconds. Applied before jitter; 429 retries use this directly. |
| `PROXY_MAX_BODY_SIZE` | `10485760` | 1024–100 MiB | Request body size cap (bytes); larger → 413. Also caps the upstream error body drain on retry exhaustion. |
| `PROXY_LOG_ALL` | unset | `1` to enable | Log full request bodies; response bodies on error paths only (streamed 2xx bodies are not captured) |
| `PROXY_TRACE_FILE` | `~/.claude/logs/proxy-trace.jsonl` | path | Trace log location |

Backoff is `PROXY_INITIAL_DELAY * 2**attempt`, capped at `PROXY_MAX_DELAY`.
**429** responses retry using `PROXY_MAX_DELAY` directly (maximal latency);
**503** and connection errors use the exponential. Every retry delay then gets
**±25% uniform jitter** (integer seconds), drawn from a per-thread RNG, so
concurrent sessions de-synchronize instead of retrying in lockstep.

> **Worst case:** jitter raises the per-retry upper bound to `1.25 *
> PROXY_MAX_DELAY` (the cap is applied before the ±25%). With the max bounds
> (`PROXY_MAX_RETRIES=100`, `PROXY_MAX_DELAY=300`), a single request that keeps
> getting `429`/`503` can block a worker thread for up to ~10.4 hours. With the
> defaults (10 retries, 30 s cap) the worst case is about 3.8 minutes per
> request.
>
> Note: with integer-second rounding, ±25% jitter is ineffective for delays of
> 1–2 s (the range lands in one integer bucket); de-sync becomes effective from
> ~3 s onward. The 429 path uses `PROXY_MAX_DELAY` (default 30 s), so it
> de-syncs from the first retry.

## Trace log

Default location: `~/.claude/logs/proxy-trace.jsonl` (one JSON object per line).

Each request logs: timestamp, method, path, model, status, http_status, retry
count, total latency, first-byte latency, and a sanitized error. Lifecycle
markers (`proxy_start`, `proxy_stop`) and per-retry events are also logged.
When a client disconnects mid-response (e.g. timed out during a long retry
storm), a `client_disconnect` event is logged (with `request_id`,
`http_status`, `retries`) instead of printing a traceback.

Entries older than 5 days are pruned on each `claude-retry-proxy start`.

When retries are exhausted on a `429`/`503`, the upstream's error body is
preserved and returned to the client (capped at `PROXY_MAX_BODY_SIZE`).
On connection-error exhaustion, a synthesized `upstream_unreachable` body is
logged to the trace.

Use `--all` (or `PROXY_LOG_ALL=1`) to include full request bodies; response
bodies are captured on the buffered (error) path only — streamed 2xx success
bodies are not stored.

### Analyzing the trace log

A utility script is provided for analyzing proxy trace data:

```bash
python scripts/analyze_proxy_trace.py --days 3
```

This prints per-model statistics including request count, average retries,
query success rate, attempt success rate, and geomean TTFT/latency. Models are
auto-detected from the trace (no hardcoded names). Outliers (latency >30 min,
max retries + failure) are filtered automatically.

Run with `--help` for all options:

```bash
python scripts/analyze_proxy_trace.py --help
```

### ⚠️ Data exposure with `--all` / `PROXY_LOG_ALL`

With `--all`, the trace file contains **raw prompts** (plus error-path
response bodies) in plaintext; streamed 2xx success bodies are not captured.
The proxy applies `0600` permissions to the trace and state files on
**POSIX** systems. On **Windows**, `chmod` is effectively a no-op (it only
toggles the read-only attribute; there is no Unix group/other model), so you
must restrict the trace directory's ACL yourself, e.g.:

```powershell
icacls "$env:USERPROFILE\.claude\logs" /inheritance:r /grant:r "$env:USERNAME:(OI)(CI)F"
```

Point `PROXY_TRACE_FILE` at a directory with restrictive permissions regardless
of platform if you enable `--all`.

## Features

- **Automatic retries** — `429`, `503`, and connection errors retried with
  jittered exponential backoff (default 10 attempts). `429`s back off at the
  maximal delay; jitter de-synchronizes concurrent sessions.
- **Error body preservation** — exhausted retries on `429`/`503` return the
  upstream error body to the client; connection-error exhaustion returns a
  synthesized `upstream_unreachable` body (visible in the trace log).
- **Graceful disconnect handling** — client disconnects mid-response are
  logged as `client_disconnect` trace events; no tracebacks.
- **Trace pruning** — `start` removes entries older than 5 days from the
  trace log and prints a one-line summary.
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
| `logs/proxy-trace.jsonl` | The JSONL request trace (pruned of entries >5 days on each `start`) |

## Testing

```bash
pip install -e .
python tests/test_claude_proxy.py
```

The suite has 36 tests. **12 of them exercise the CLI's URL swap and require
`ANTHROPIC_BASE_URL` in `~/.claude/settings.json` to be a non-localhost URL**
(the proxy correctly rejects localhost to avoid proxying to itself). Set it to a
real upstream or a mock before running the full suite. The other 24 tests start
the server directly with mock upstreams and pass regardless (these include the
streaming delivery, mid-stream failure, CRLF header filter, jitter/429 retry,
body preservation, disconnect catch, and trace prune tests).

> The tests back up and restore `~/.claude/settings.json`, but during a run your
> live config is temporarily altered. Don't run the suite while a Claude Code
> session is active against the same settings file, and avoid interrupting it
> mid-test (a crash can leave `settings.json` pointing at localhost — run
> `claude-retry-proxy stop` to recover).

## License

MIT. See [LICENSE](LICENSE).
