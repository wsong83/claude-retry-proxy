# claude-retry-proxy

A local HTTP retry gateway for the Claude API. It listens on `localhost`, routes
requests by model tier (haiku/sonnet/opus) to different upstream providers,
retries `429` (Too Many Requests) and `503` (Service Unavailable) responses with
jittered exponential backoff, rewrites model names bidirectionally (tier ↔
actual), and logs every request to a JSONL trace file.

It works with **any** upstream provider — official Anthropic, third-party
gateways, or self-hosted endpoints. Different tiers can route to different
providers simultaneously.

Python 3.8+. `cryptography` package required (for encrypted key storage; plain JSON keys files don't need it). MIT licensed.

## Why

Some upstream endpoints return `503` under load or `429` when rate-limiting.
Claude Code treats a `503` as a hard failure, so a transiently-busy provider
interrupts your session. This proxy sits between Claude Code and your upstream
providers, transparently retrying `429`s, `503`s, and connection errors with
jittered exponential backoff so a busy provider doesn't abort your work. Jitter
(±25% per delay, de-synchronized per thread) prevents concurrent sessions
from re-stampeding the upstream in lockstep.

Additionally, the proxy enables **multi-provider routing**: send lightweight
tasks (haiku) to a cheaper provider, standard tasks (sonnet) to your primary
provider, and complex tasks (opus) to a premium provider — all from a single
proxy with hot-switchable tier mappings via an admin page.

## Install

From git (editable, for development):

```bash
pip install -e .
```

Requires `setuptools >= 64` (for PEP 660 src-layout editable installs). Python
3.8 or newer.

## Quick start

```bash
# 1. Configure ~/.claude/settings.json (once, manually):
#    ANTHROPIC_BASE_URL = http://localhost:8080
#    ANTHROPIC_DEFAULT_SONNET_MODEL = sonnet
#    ANTHROPIC_DEFAULT_OPUS_MODEL = opus
#    ANTHROPIC_DEFAULT_HAIKU_MODEL = haiku
#    ANTHROPIC_API_KEY = <any value — the proxy injects the real key>

# 2. Prepare ~/.claude/keys-index.json with your provider URLs and API keys.
#    Can be plain JSON (convenient for testing/automation) or encrypted
#    with `vim -n -x` (blowfish2, VimCrypt~03!, recommended for production).

# 3. Start the proxy (prompts for passphrase if keys are encrypted;
#    starts immediately if keys are plain JSON)
claude-retry-proxy start

# 4. Use Claude Code as usual — its traffic now flows through the proxy

# 5. Hot-switch tier mappings via the admin page
#    Open http://localhost:8080/admin/ in your browser

# 6. Stop the proxy
claude-retry-proxy stop
```

Check state at any time:

```bash
claude-retry-proxy status     # running/stopped + tier mapping
claude-retry-proxy reload     # reload config.json from disk
```

## How it works

When you run `claude-retry-proxy start`:

1. It checks that `~/.claude/proxy/config.json` exists. On first run, it copies
   a template and tells you to populate it with your tier→provider mappings.
2. It prompts for your passphrase and decrypts `~/.claude/keys-index.json`
   (provider URLs and API keys, vim blowfish2 encrypted).
3. It validates the config: all 3 tiers present with valid provider references,
   every provider in `config.models` has a corresponding entry in `keys-index.json`,
   every provider in `config.models` has at least one valid model name, and every
   tier-referenced provider has a models entry.
4. It checks the trace log and prunes entries older than 5 days.
5. It launches the proxy server, piping the passphrase via stdin.

For each request from Claude Code:

1. The model name is resolved to a tier (haiku/sonnet/opus)
2. The config maps the tier to a specific provider and model name
3. The request body's `model` field is rewritten to the actual model name
4. The provider's API key is injected (replacing the client's dummy key)
5. The request is forwarded to the provider's URL with retry handling
6. The response model name is rewritten back to the tier name

`settings.json` is never touched — it points at `localhost:8080` permanently.

## Usage

```
Usage: claude-retry-proxy <command> [options]

Commands:
  start   Start the proxy (passphrase prompt + config validation + launch server)
  stop    Stop the proxy
  status  Show proxy status + current tier mapping
  reload  Reload config.json from disk into running proxy
```

### `start` options

```
claude-retry-proxy start [-h] [--port PORT] [--log LOG] [--all]
                         [--config-path PATH] [--keys-path PATH]

  --port, -p PORT         Port to listen on (default: 8080)
  --log, -l LOG           Trace log file path
  --all, -a               Log full request/response bodies
  --config-path PATH      Config file path (default: ~/.claude/proxy/config.json)
  --keys-path PATH        Keys file path (default: ~/.claude/keys-index.json)
```

### Direct server invocation

The server can also be run directly (the `start` subcommand normally does this
for you):

```bash
claude-retry-proxy-server --port 8080 --config-path ~/.claude/proxy/config.json --keys-path ~/.claude/keys-index.json
# or
python -m claude_retry_proxy.server --port 8080 --config-path ... --keys-path ...
```

The server prompts for the passphrase on stdin. Use `--passphrase-file <path>`
for non-interactive use.

## Configuration

### Config file (`~/.claude/proxy/config.json`)

Maps each tier to a provider and model name. Editable via the admin page or
directly on disk (use `claude-retry-proxy reload` after manual edits).

```json
{
  "tiers": {
    "haiku":  { "provider": "provider-a", "model": "claude-haiku-4-5-20251001" },
    "sonnet": { "provider": "provider-b", "model": "claude-sonnet-5" },
    "opus":   { "provider": "provider-c", "model": "claude-opus-5" }
  },
  "models": {
    "provider-a": ["claude-haiku-4-5-20251001", "model-x"],
    "provider-b": ["claude-sonnet-5", "model-y"],
    "provider-c": ["claude-opus-5", "model-z"]
  },
  "disable_retry_claude_count_token": true
}
```

The `models` section populates the admin page dropdowns. Each key is a provider
name (matching the provider names in the tiers section); the value is a list of
model names shown in the admin page dropdown when that provider is selected.

### `disable_retry_claude_count_token` (optional, boolean)

When `true`, the proxy does not retry the `/v1/messages/count_tokens` endpoint
on failure — it attempts exactly once and returns the result immediately.
Claude Code sends this for token accounting, but most third-party providers
don't support it. Defaults to `false` when absent (retry as normal). The
shipped config template sets it to `true`.

```json
"disable_retry_claude_count_token": true
```

### Keys file format (`~/.claude/keys-index.json`)

The keys file can be either:

- **Encrypted** (recommended for production): Encrypt with `vim -n -x
  keys-index.json` using the default blowfish2 method (`VimCrypt~03!`).
  The server and CLI will prompt for the passphrase. Use
  `--passphrase-file` for non-interactive starts.

- **Plain JSON** (convenient for testing/automation): A standard JSON file
  with a `"vendors"` key. No passphrase is required. The server emits a
  warning to stderr when plain keys are loaded. On Windows, restrict the
  file ACL with `icacls` since `chmod` is a near-no-op.

The format is auto-detected by checking for the `VimCrypt~03!` magic bytes
at the start of the file. The JSON structure is the same in both cases:

```json
{
  "vendors": {
    "provider-a": {
      "url": "https://api.anthropic.com",
      "key": "sk-ant-api03-your-key-here"
    },
    "provider-b": {
      "url": "https://api.openai.com/v1",
      "key": "sk-your-openai-key",
      "mode": "chat"
    }
  }
}
```

### Provider Modes

Each vendor entry in `keys-index.json` may carry an optional `mode` field
controlling which API format the proxy uses when routing to that provider.
Three modes are supported:

| Mode | API Endpoint | Auth Header | Description |
|------|-------------|-------------|-------------|
| `anthropic` | `{url}/v1/messages` | `x-api-key` | Anthropic Messages API (default). Request/response body is model-name-rewritten only. SSE streaming forwarded+rewritten verbatim. |
| `chat` | `{url}/v1/chat/completions` | `Authorization: Bearer` | OpenAI Chat Completions API. Request body transformed from Anthropic Messages to Chat Completions format; response body transformed back to Anthropic Messages. SSE streaming is synthesized from OpenAI SSE. `count_tokens` returns 400. |
| `response` | `{url}/v1/responses` | `Authorization: Bearer` | OpenAI Responses API. Request body transformed from Anthropic Messages to Responses format (single-turn, stream forced false); response body transformed back to Anthropic Messages. `count_tokens` returns 400. |

When `mode` is absent, `null`, or empty, it defaults to `"anthropic"`.
Invalid modes return a 500 error at request time. Startup validates the
mode enum and emits a stderr warning for each vendor without an explicit
mode.

**URL configuration:** For chat and response modes, the proxy appends the
API endpoint path (`/v1/chat/completions` or `/v1/responses`) to the
vendor's `url`. If the URL already ends in `/v1`, the trailing `/v1` is
stripped first to avoid doubling (e.g., `https://api.openai.com/v1` →
`https://api.openai.com/v1/chat/completions`, not
`/v1/v1/chat/completions`).

**Limitations:** Response mode is single-turn only (extracts only the last
user message as `input`, discards conversation history). Tool-use SSE
deltas are not transformed in chat-mode streaming (stop_reason is degraded
to null when tool calls are detected). Error responses (non-2xx) pass
through untransformed in the upstream format.

### Admin page (`http://localhost:8080/admin/`)

A browser-based admin panel for hot-switching tier mappings. Changes are
written to `config.json` and take effect immediately. The admin page is
localhost-only with CSRF protection (Origin header validation).

### Server environment variables

| Variable | Default | Range | Description |
|----------|---------|-------|-------------|
| `PROXY_PORT` | `8080` | 1024–65535 | Port to listen on |
| `PROXY_MAX_RETRIES` | `10` | 1–100 | Max retry attempts per request (shared by 429 and 503) |
| `PROXY_INITIAL_DELAY` | `1` | 1–60 | First backoff delay, seconds |
| `PROXY_MAX_DELAY` | `30` | 1–300 | Backoff cap, seconds. Applied before jitter; 429 retries use this directly. |
| `PROXY_MAX_BODY_SIZE` | `10485760` | 1024–100 MiB | Request body size cap (bytes); larger → 413. Also caps the upstream error body drain on retry exhaustion. |
| `PROXY_MAX_RESPONSE_SIZE` | `104857600` | 1024–1 GiB | Streaming response size cap (bytes); larger → truncated with a warning trace event. |
| `PROXY_LOG_ALL` | unset | `1` to enable | Log full request bodies; response bodies on error paths only (streamed 2xx bodies are not captured) |
| `PROXY_TRACE_FILE` | `~/.claude/logs/proxy-trace.jsonl` | path | Trace log location |
| `PROXY_KEYS_PATH` | `~/.claude/keys-index.json` | path | Keys file location (encrypted or plain JSON) |
| `PROXY_STATE_FILE` | `~/.claude/proxy/proxy-state.json` | path | State file path override. The server heartbeat writes PID/port/start_time here; `claude-retry-proxy stop`/`status`/`reload` read it. Override for test isolation. |

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

## Trace log

Default location: `~/.claude/logs/proxy-trace.jsonl` (one JSON object per line).

Each request logs: timestamp, method, path, model, tier, provider, status,
http_status, retry count, total latency, first-byte latency, and a sanitized
error. Lifecycle markers (`proxy_start`, `proxy_stop`) and per-retry events
are also logged. When a client disconnects mid-response, a `client_disconnect`
event is logged instead of printing a traceback.

Entries older than 5 days are pruned on each `claude-retry-proxy start`.

### Analyzing the trace log

```bash
python scripts/analyze_proxy_trace.py --days 3
```

This prints per-model statistics including request count, average retries,
query success rate, attempt success rate, and geomean TTFT/latency. Models are
auto-detected from the trace (no hardcoded names). Outliers (latency >30 min,
max retries + failure) are filtered automatically.

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

## Features

- **Multi-provider tier routing** — route haiku/sonnet/opus to different
  upstream providers. Hot-switchable via admin page.
- **Model name rewriting** — request: tier → actual model. Response: actual
  model → tier. Claude Code only sees tier names.
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
- **Admin page** — browser-based tier switching at `http://localhost:8080/admin/`.
  CSRF-protected, localhost-only.
- **Encrypted key storage** — provider credentials stored in vim blowfish2
  encrypted `keys-index.json`, decrypted at startup via passphrase.
- **Concurrent sessions** — `ThreadingHTTPServer` handles multiple in-flight
  requests.
- **Localhost-only** — the proxy binds `127.0.0.1`; it is not reachable from
  the network.

## Files written at runtime

While the proxy runs, it creates (all under `~/.claude/`):

| Path | Purpose |
|------|---------|
| `proxy/config.json` | Tier→provider mapping (editable via admin page or manually) |
| `proxy/proxy-state.json` | Runtime state (PID, port, heartbeat); removed on clean shutdown |
| `proxy/proxy-stderr.log` | Server stderr (startup messages, retry notices) |
| `logs/proxy-trace.jsonl` | The JSONL request trace (pruned of entries >5 days on each `start`) |

## Testing

```bash
pip install -e .
python tests/test_claude_proxy.py
```

The suite covers tier routing, model rewriting, admin API, config validation,
key decryption, retry logic, streaming delivery, disconnect handling, and trace
logging. Tests use mock upstream servers and temporary config/keys files — no
live `~/.claude/settings.json` mutation required.

## Dependencies

- `cryptography` (>= 38.0) — Blowfish ECB for vim blowfish2 decryption of
  `keys-index.json`
- Python standard library — all other functionality

## License

MIT. See [LICENSE](LICENSE).
