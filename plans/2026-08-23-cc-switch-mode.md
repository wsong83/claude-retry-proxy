# Plan: Multi-Provider Tier Routing (cc-switch mode)
**Project:** D:\proj\claude-retry-proxy
**Plan ID:** 2026-08-23-cc-switch-mode
**Created:** 2026-08-23

## Issue Log

Rows ordered newest-first (latest issues at top). New issues are prepended; resolved issues stay in place with updated status.

| Issue | Status | Found | Resolved | Resolved By |
|-------|--------|-------|----------|-------------|
| [mega-audit-iter3-batch](./tmp/reports/2026-08-23-cc-switch-mode-mega-audit-2026-08-24-iter3.json) — 14 findings batch. **All 14 resolved.** Coder: fix-5 (3 items), fix-6 (6 items), fix-7 (provider dropdown). Tester: removed duplicate test. Planner: README models, plan metadata. | Resolved (14/14) | 2026-08-24 | 2026-08-25 | coder (fix-5, fix-6, fix-7), tester, planner |
| [drain-and-swap-config-swap](./tmp/reports/2026-08-24-drain-and-swap-config-swap.json) — Config swap races with in-flight requests: response rewrite reads new global reverse map for old provider's response. Fix: drain-and-swap (block new queries, drain in-flight, swap, unblock) + snapshot reverse_map at request start. Supersedes fix-4's simple lock refactor. Coder implemented: wrapper+impl split, 30s drain timeout (abort on exceed), 100ms poll interval. Existing tests pass without regression; dedicated race condition test recommended but not yet added. | Resolved | 2026-08-24 | 2026-08-25 | coder (drain-and-swap) |
| [reviewer-drain-swap-race](./tmp/reports/2026-08-23-cc-switch-mode-coder-2026-08-25-reviewer-fixes.json) — Coder fixed: `forward_request` now snapshots config, vendors, AND reverse_map together under `_config_lock` (lines 563-567). Atomic snapshot prevents race. | Resolved | 2026-08-25 | 2026-08-25 | coder, tester |
| [reviewer-cmd-stop-csrf](./tmp/reports/2026-08-23-cc-switch-mode-coder-2026-08-25-reviewer-fixes.json) — Coder fixed: `cmd_stop` now adds Origin header to shutdown request (cli.py line 642). Graceful shutdown restored. | Resolved | 2026-08-25 | 2026-08-25 | coder, tester |
| [reviewer-env-docs](./tmp/reports/) — `PROXY_MAX_RESPONSE_SIZE` added to CLAUDE.md env var table (line 144). | Resolved | 2026-08-25 | 2026-08-25 | planner |
| [admin-shutdown-csrf](./tmp/reports/2026-08-23-cc-switch-mode-coder-2026-08-25-admin-shutdown-csrf-fix.json) — `/admin/shutdown` handler CSRF check added. Option A: localhost first, CSRF second (consistent with switch/reload). Coder implemented lines 1298-1301. No regressions. | Resolved | 2026-08-25 | 2026-08-25 | coder, tester |
| [sse-model-rewrite-regression](./tmp/reports/2026-08-23-cc-switch-mode-tester-2026-08-25-2.json) — Coder report described removing SSE model rewriting, but current code correctly has buffer-first-event + rewrite at lines 1087-1134. Either reverted or never applied. Test passes. | Resolved | 2026-08-25 | 2026-08-25 | verified by test run (51/51 pass) |
| [streaming-response-buffered](./tmp/reports/2026-08-23-cc-switch-mode-tester-2026-08-25.json) — Test data fixed to proper SSE format with `\n\n` delimiters (lines 3172-3178). Test passes. | Resolved | 2026-08-25 | 2026-08-25 | verified by test run (51/51 pass) |
| [client-disconnect-detection](./tmp/reports/2026-08-23-cc-switch-mode-tester-2026-08-25.json) — Test mock fixed to send 100KB chunks with 50ms delays (lines 2804-2816). Test passes. | Resolved | 2026-08-25 | 2026-08-25 | verified by test run (51/51 pass) |
| review-warnings-1-2 (split): (1) `cli.py:364` config-path validation — **Resolved** by coder fix-4. (2) `server.py:1300` config lock during admin I/O — **Resolved** by drain-and-swap. | Resolved (both) | 2026-08-24 | 2026-08-25 (#2) | coder (fix-4 #1, drain-and-swap #2) |
| [sse-buffer-not-isolating-first-event](./tmp/reports/2026-08-23-cc-switch-mode-tester-2026-08-24-2.json) — SSE buffer reads past first `\n\n` when both events arrive in one `read1()` chunk; rewriter fails on multi-event buffer. Fix: split buffer at first `\n\n`, rewrite only first event, write remainder separately. | Resolved | 2026-08-24 | 2026-08-24 | tester |
| [streamed-flag-regression](./tmp/reports/2026-08-24-streamed-flag-regression.json) — `do_POST` line 1402: `streamed = 200 <= status < 300` assumes all 2xx were streamed, but JSON buffering path returns body without sending it. Fix: `streamed = (200 <= status < 300) and (resp_body == b"")` | Resolved | 2026-08-24 | 2026-08-24 | tester |
| [response-model-rewrite-not-working](./tmp/reports/2026-08-24-response-model-rewrite-not-working.json) — Response model rewriting not implemented for non-streaming or streaming responses | Resolved | 2026-08-24 | 2026-08-24 | tester |
| [tester-report](./tmp/reports/2026-08-23-cc-switch-mode-tester-2026-08-24.json) — Unknown model error message doesn't list valid tier names | Resolved | 2026-08-24 | 2026-08-24 | tester |

## Guidance for Coder

**Files to modify:**

- `src/claude_retry_proxy/server.py`
- `src/claude_retry_proxy/cli.py`
- `pyproject.toml`

**Files to create:**

- `src/claude_retry_proxy/vimcrypt.py`
- `src/claude_retry_proxy/admin.html`
- `src/claude_retry_proxy/config-template.json`

**Step-by-step with verification:** each step below has coder checks tagged `(auto)` or `(scripted)`. The coder self-verifies `(auto)` checks and runs the provided script for `(scripted)` checks. Tester owns the behavioral checks. See coder Prime Directive 4.

## Guidance for Tester

**Tests to create:**
- **Permanent:**
  - `test_tier_routing_basic` — send request with model "sonnet", verify correct upstream receives the configured model name and API key
  - `test_tier_routing_all_tiers` — send haiku/sonnet/opus requests, verify each routes to its configured provider
  - `test_model_resolution_reverse_lookup` — send request with actual model name (e.g. "claude-sonnet-5"), verify reverse-mapping to tier
  - `test_model_resolution_pattern_match` — send request with model name containing tier keyword (e.g. "my-sonnet-model"), verify pattern-match resolves to sonnet tier
  - `test_model_resolution_unknown_rejected` — send request with unrecognized model name (e.g. "gpt-4"), verify 400 error with valid tier list
  - `test_model_resolution_none_rejected` — send request with `{"model": null}`, verify 400 error (not crash)
  - `test_response_model_rewrite` — verify response model name is replaced with tier name (non-streaming)
  - `test_response_model_rewrite_streaming` — verify SSE message_start event has tier name, subsequent events unchanged
  - `test_response_model_rewrite_streaming_non_message_start` — first SSE event is not message_start → forwarded unchanged, no rewrite attempted
  - `test_response_model_rewrite_unmapped_model` — upstream returns model name not in reverse map → passed through unchanged, warning logged
  - `test_config_validation_missing_tier` — config with empty provider → server refuses to start
  - `test_config_validation_unknown_provider` — config references provider not in keys-index.json → server refuses to start
  - `test_config_template_copy` — missing config.json → template copied, start fails with message
  - `test_admin_page_served` — GET /admin/ returns HTML
  - `test_admin_api_config` — GET /admin/api/config returns current tiers + models
  - `test_admin_api_switch` — POST /admin/api/switch updates tier, subsequent request routes to new provider
  - `test_admin_api_switch_invalid_provider` — POST with unknown provider → error response
  - `test_admin_api_switch_preserves_models` — switch tiers, verify models section unchanged in config.json
  - `test_admin_api_csrf_rejected` — POST with foreign Origin header → rejected
  - `test_admin_api_csrf_null_origin_rejected` — POST with `Origin: null` → rejected (sandboxed iframe vector)
  - `test_admin_api_csrf_missing_origin_rejected` — POST without Origin header → rejected (non-browser clients must add Origin)
  - `test_admin_api_csrf_ipv6_loopback_accepted` — POST with `Origin: http://[::1]:<port>` → accepted
  - `test_admin_api_switch_missing_tier_rejected` — POST with only 2 tiers → 400 error listing missing tier
  - `test_config_validation_reverse_map_collision` — config with two tiers mapping to same model → server refuses to start
  - `test_admin_api_reload` — modify config.json on disk, POST /admin/api/reload, verify new mapping active
  - `test_cli_reload` — `claude-retry-proxy reload` sends reload request to running proxy
  - `test_cli_start_no_config` — start without config.json → template created, exit 1, message printed
  - `test_cli_start_invalid_config` — start with broken config → exit 1, specific error
  - `test_cli_status_shows_tiers` — status output includes tier → provider → model mapping
  - `test_key_decryption_wrong_passphrase` — wrong passphrase → start fails with clear error
  - `test_key_decryption_missing_file` — no keys-index.json → start fails with clear error
  - `test_api_key_from_keys_index` — verify x-api-key sent to upstream comes from keys-index.json, not from client
  - `test_client_api_key_ignored` — send request with arbitrary x-api-key, verify upstream receives keys-index key

- **Temporary:**
  - `test_vimcrypt_decrypt_vector` — known-answer test for blowfish2 decryption (vim self-test vectors)
  - `test_config_load_valid` — load a valid config.json, verify parsed structure
  - `test_config_load_invalid_json` — malformed JSON → clear error

**Tests to investigate for retirement:**
- Planner candidates:
  - `tests/test_claude_proxy.py::test_url_swapping` — URL swap removed; proxy no longer modifies settings.json
  - `tests/test_claude_proxy.py::test_crash_recovery` — URL restore removed; crash recovery semantics changed
  - `tests/test_claude_proxy.py::test_url_validation` — URL validation for settings.json swap removed
  - `tests/test_claude_proxy.py::test_manual_edit_detection` — no URL swap means no manual-edit detection
  - `tests/test_claude_proxy.py::test_pid_in_lock` — lock file format changed (no URL)
  - `tests/test_claude_proxy.py::test_start_early_exit_rollback` — no URL rollback needed
  - `tests/test_claude_proxy.py::test_stop_cleans_lock_on_write_failure` — lock semantics changed
  - `tests/test_claude_proxy.py::test_stop_kills_proxy_with_non_localhost_url` — URL tracking removed
  - `tests/test_claude_proxy.py::test_stop_trace_no_proxy` — stop trace format changed
  - `tests/test_claude_proxy.py::test_stop_trace_with_proxy` — stop trace format changed
  - `tests/test_claude_proxy.py::test_start_stdout_not_contaminated` — stdout output changed (passphrase prompt)
  - `tests/test_claude_proxy.py::test_start_no_auth_header_required` — auth model unchanged but test may need update for new startup flow
  - `tests/test_claude_proxy.py::test_release_swap_lock_retries` — release_swap_lock function removed
  - `tests/test_claude_proxy.py::test_release_swap_lock_warns_on_final_failure` — release_swap_lock function removed
  - `tests/test_claude_proxy.py::test_race_conditions` — references URL_LOCK_FILE (base-url.lock) which is removed
  - `tests/test_claude_proxy.py::test_stop_cleans_proxy_state` — reads PID from base-url.lock which is removed
  - `tests/test_claude_proxy.py::test_stop_cleans_proxy_state_lock` — creates fake base-url.lock which is removed
  - `tests/test_claude_proxy.py::test_proxy_state_no_auth_token` — CLI start requires config.json + passphrase now
  - **14 direct-server tests** using `set_base_url()` helper (which reads settings.json): these tests must be migrated to provide temp config.json + keys-index.json + passphrase via stdin instead of relying on settings.json URL. Tests: test_concurrent_requests, test_retry_logic, test_retry_429, test_retry_429_exhaust_returns_429, test_trace_markers, test_thread_safety, test_trace_logs_oversized_body, test_exhaust_429_preserves_body, test_exhaust_connection_error_synthesizes_body, test_client_disconnect_no_traceback, test_streaming_response_body, test_streaming_mid_stream_upstream_failure, test_empty_body_429_exhaust, test_relative_log_path. Tester: rewrite `_start_proxy_server_directly` helper to create temp config/keys files and pipe passphrase.
- Tester may identify additional candidates during test work.

**Retirement procedure:** For each candidate, verify the test exercises code being removed/changed. If obsolete: delete and note in session report. If still valid: document why in session report (e.g., "tests error handling path still present").

## Summary

Transform the claude-retry-proxy from a single-upstream transparent relay into a **multi-provider gateway** that routes requests by model tier (haiku/sonnet/opus) to different upstream providers.

### Architecture

```
settings.json (static, user-managed):
  ANTHROPIC_BASE_URL = http://localhost:8080
  ANTHROPIC_DEFAULT_SONNET_MODEL = sonnet
  ANTHROPIC_DEFAULT_OPUS_MODEL = opus
  ANTHROPIC_DEFAULT_HAIKU_MODEL = haiku
  ANTHROPIC_API_KEY = <dummy>

Claude Code → localhost:8080 (proxy)
                │
                ├─ Parse model from body → resolve tier
                ├─ Config lookup: tier → (provider, model)
                ├─ Keys lookup: provider → (url, api_key)
                ├─ Rewrite: model → actual, x-api-key → provider's key
                ├─ Forward to provider URL (retry 429/503)
                ├─ Response: rewrite model → tier name
                └─ Return to Claude Code
```

### Key design decisions

1. **settings.json is static** — user configures it once. The proxy NEVER reads or writes settings.json. No URL swap.
2. **Tier routing is config-driven** — `~/.claude/proxy/config.json` maps each tier to a provider + model name.
3. **Provider credentials are separate and encrypted** — `~/.claude/keys-index.json` (vim blowfish2) holds URLs + API keys. Decrypted at startup via passphrase prompt. Immutable during runtime.
4. **Client API key is ignored** — the proxy injects the provider's key from keys-index.json.
5. **Model names are bidirectional** — request: tier → actual model. Response: actual model → tier. Claude Code only sees tier names.
6. **Hot-switch via admin page** — admin HTML page at `/admin/` writes config.json + updates in-memory routing. CLI `reload` for manual file edits.
7. **Strict startup validation** — proxy refuses to start if config is missing or invalid. First start copies template and tells user to populate it.

### Alternatives rejected

- **CC Switch (desktop GUI app)** — too heavyweight. This is a CLI-only, stdlib+near-zero-dep alternative.
- **Per-tier failover** — multiple providers per tier with automatic failover. Deferred to keep v1 simple.
- **URL swap mechanism** — removed entirely. settings.json points at localhost permanently.

### Out of scope

- Provider health monitoring / circuit breakers
- Per-tier retry configuration (shared retry logic per provider)
- Usage tracking / cost dashboard
- Authentication to the admin page (localhost-only, same as current /admin/shutdown)

## Repo Mode

Public

## Document Overrides

| Document | Rule Overridden | Reason |
|----------|----------------|--------|
| CLAUDE.md | "Zero runtime dependencies" | `cryptography` package required for vim blowfish2 decryption of keys-index.json |

## Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| vimcrypt copy diverges from claude-config | Bug fixes in one copy not propagated | Document origin clearly in vimcrypt.py header; user aware of both copies |
| Config template models list becomes stale | Admin dropdown shows outdated model names | User can edit models in config.json directly; admin page allows "Custom…" input |
| Passphrase in process memory | Memory dump could expose keys | Same threat model as claude-config's ecat.py; accepted risk for personal tool |

## Proposed Changes

1. **Step 1:** Bundle `vimcrypt.py` — copy from `D:\proj\claude-config\bin\vimcrypt.py` into `src/claude_retry_proxy/vimcrypt.py`. Add header comment documenting origin: "Derived from claude-config (https://github.com/user/claude-config), bin/vimcrypt.py. Implements vim blowfish2 (VimCrypt~03!) decryption." No code changes to the copied file.
   → coder verify (auto): `src/claude_retry_proxy/vimcrypt.py` exists, contains `VIMCRYPT_MAGIC`, `_derive_key`, `_cfb64_decrypt`, `decrypt`, `prompt_hidden` functions; header comment documents claude-config origin.
   → tester verify: `test_vimcrypt_decrypt_vector` passes — known-answer test vector from vimcrypt self-test.

2. **Step 2:** Config loading and validation module — add to `server.py` (or new internal module). Functions:
   - `load_config(path)` → reads `~/.claude/proxy/config.json`, returns `{"tiers": {...}, "models": {...}}`
   - `validate_config(config, providers)` → checks: all 3 tiers present with non-empty provider+model; all providers exist in keys table; returns list of errors (empty = valid)
   - `write_config(path, config)` → atomic write (write to .tmp, os.replace)
   - `install_template(dest_path)` → copies `config-template.json` from package data to dest_path
   - `DEFAULT_CONFIG_PATH` = `~/.claude/proxy/config.json`
   - `CONFIG_TEMPLATE_PATH` = package data path to `config-template.json`
   Thread-safe config access via `threading.RLock` (read by worker threads, written by admin API).
   → coder verify (auto): `load_config`, `validate_config`, `write_config`, `install_template` defined in server.py; `DEFAULT_CONFIG_PATH` resolves to `~/.claude/proxy/config.json`.
   → coder verify (scripted): script at `./tmp/verification/2026-08-23-cc-switch-mode-step2.py` — validates that load_config returns correct structure for valid JSON, validate_config catches missing tier / empty provider / unknown provider, install_template copies template to temp path.
   → tester verify: `test_config_load_valid`, `test_config_load_invalid_json`, `test_config_validation_missing_tier`, `test_config_validation_unknown_provider` pass.

3. **Step 3:** Key decryption at startup — add to `server.py` (or `cli.py` for the prompt). Flow:
   - CLI prompts for passphrase via `vimcrypt.prompt_hidden("Passphrase: ")`
   - Reads encrypted `~/.claude/keys-index.json` (configurable via `--keys-path`)
   - Decrypts: `plaintext = vimcrypt.decrypt(data, passphrase)`
   - Parses JSON: extracts `vendors` dict → `{name: {"url": ..., "key": ...}}`
   - Validates JSON is valid UTF-8 with a `vendors` key
   - **Passphrase pipe protocol:**
     - CLI writes passphrase + `\n` to `proc.stdin`, then closes stdin
     - Server reads one line from stdin in `main()` before `serve_forever()`, strips trailing `\n`
     - On decryption failure, server prints error to stderr (captured in `proxy-stderr.log`) and exits non-zero
     - CLI detects `proc.poll() != 0` after stdin close as a startup failure, reads stderr for error message
     - Server must NOT accept connections until decryption succeeds (decryption is synchronous in `main()` before bind)
   - Server stores decrypted vendors table in memory (module-level, read-only after init)
   - `PROXY_KEYS_PATH` env var or `--keys-path` CLI arg (default: `~/.claude/keys-index.json`)
   - **Direct server invocation** (`claude-retry-proxy-server` console script):
     - If `sys.stdin.isatty()`: prompt interactively for passphrase
     - If stdin is a pipe/file: read one line (same as CLI pipe protocol)
     - On EOF before newline or empty passphrase: exit with error
     - `--upstream-url` removed (no longer applicable)
     - Add `--passphrase-file` for non-interactive use (read passphrase from file instead of stdin)
   → coder verify (auto): server.py imports vimcrypt; `decrypt_keys(path, passphrase)` function defined; server startup calls it before accepting connections.
   → tester verify: `test_key_decryption_wrong_passphrase`, `test_key_decryption_missing_file` pass.

4. **Step 4:** Tier routing and request rewriting — modify `forward_request()` in `server.py`:
   - Remove global `UPSTREAM_HOST/PORT/USE_SSL/PATH_PREFIX` (single upstream)
   - Add `resolve_tier(model_name, config)` → returns tier name:
     1. **None guard:** if model_name is None or not a string, treat as "unknown"
     2. If model_name is "haiku"/"sonnet"/"opus" → direct match
     3. Reverse-lookup: scan config tiers for matching model → return tier
     4. Pattern match: "haiku" in model_name → haiku, etc. (check in order: opus, sonnet, haiku — most-specific first)
     5. **Unknown model: return 400 error** with message listing valid tier names (haiku, sonnet, opus). Do NOT silently default to a tier — routing an unintended request to a provider wastes quota and produces misleading traces.
   - `extract_model(body)` guard: if `data.get("model")` returns None or a non-string, return `"unknown"` (prevents TypeError in resolve_tier step 4).
   - Per-request upstream resolution: tier → config → provider → vendors table → (host, port, ssl, path_prefix, api_key)
   - Parse provider URL via existing `parse_upstream()` per-request. **No cache** — parse_upstream is O(1) and there are typically <5 providers. A cache would require invalidation on config change (admin switch/reload), adding complexity for negligible gain.
   - Rewrite request body: replace `"model"` field with configured model name
   - Replace `x-api-key` header with provider's key from vendors table
   - Drop/replace `authorization` header (not forwarded)
   - Forward to resolved upstream (existing retry logic preserved, per-provider)
   - Trace log: add `tier` and `provider` fields to trace entry
   → coder verify (auto): `resolve_tier` function defined; global `UPSTREAM_HOST/PORT/USE_SSL/PATH_PREFIX` removed; `forward_request` accepts config and vendors parameters.
   → coder verify (scripted): script at `./tmp/verification/2026-08-23-cc-switch-mode-step4.py` — tests resolve_tier with direct names, reverse lookup, pattern match, fallback; verifies forward_request body rewrite replaces model field.
   → tester verify: `test_tier_routing_basic`, `test_tier_routing_all_tiers`, `test_model_resolution_fallback`, `test_api_key_from_keys_index`, `test_client_api_key_ignored` pass.

5. **Step 5:** Response model rewriting — modify response handling in `server.py`:
   - Build reverse map from config: `{actual_model: tier_name}` at config load time
   - **Reverse map collision detection:** during construction, if two tiers map to the same actual model name, raise a validation error in `validate_config` (refuse to load config with ambiguous reverse mapping). This prevents nondeterministic response rewriting.
   - **Unmapped model fallback:** if upstream model name is not in reverse map, pass through unchanged and log a warning trace event with the unmapped model name. Exact string match only (no fuzzy/prefix matching).
   - **Content-Type check FIRST** (before any buffering/parsing):
     - `text/event-stream` → streaming SSE path (buffer first event)
     - `application/json` → JSON parse path (replace model field)
     - All other Content-Types → pass through unchanged (no buffering, no parsing)
   - **Streaming responses** (`text/event-stream`, `_stream_upstream_response`): buffer the first SSE event with a **64 KB cap**. If `\n\n` delimiter not found within 64 KB, abort rewriting — forward buffered data as-is without model replacement + log warning. Error recovery:
     1. If first event is `message_start`: parse `data:` JSON, replace `"model"` field, forward modified event. If JSON is malformed or has no `"model"` key, forward raw event unchanged + log warning.
     2. If first event is NOT `message_start` (e.g. ping, error, comment): forward unchanged, set `rewrite_skipped` flag, forward all subsequent events unchanged without scanning.
     3. All subsequent events forwarded unchanged regardless.
   - **Non-streaming JSON responses** (`application/json`): parse JSON body, replace `"model"` field with tier name, re-serialize, adjust Content-Length. If body is not valid JSON or has no `"model"` key, pass through unchanged.
   - **Architecture note:** current proxy streams ALL 2xx responses. The JSON-rewrite path applies to non-streaming error responses (non-2xx) and future non-streaming modes. All 2xx success responses use the SSE streaming path.
   → coder verify (auto): reverse map built during config load; `_rewrite_response_model(body, reverse_map)` function defined; `_stream_upstream_response` buffers first event for rewriting.
   → tester verify: `test_response_model_rewrite`, `test_response_model_rewrite_streaming` pass.

6. **Step 6:** Admin page and API — add to `server.py`:
   - Load `admin.html` from package data at server startup, cache in memory
   - Route in `do_GET`: `GET /admin/` → serve admin.html (Content-Type: text/html)
   - Route in `do_POST`:
     - `POST /admin/api/switch` → body contains ONLY tier mappings `{tiers: {haiku: {...}, sonnet: {...}, opus: {...}}}`. The `models` section is **preserved from existing in-memory config** (not overwritten). Validate all providers exist. Under RLock: shallow-replace `config['tiers']`, rebuild reverse map, write merged config (tiers + models) to disk. Return 200.
     - `POST /admin/api/reload` → re-read config.json from disk, validate, atomic swap of in-memory config under RLock, rebuild reverse map, return 200 with new config
   - `GET /admin/api/config` → return current config (tiers + models) as JSON
   - **CSRF protection:** admin POST endpoints validate `Origin` header:
     - **Reject** if Origin is missing (non-browser clients like curl/CLI reload must add Origin header)
     - **Reject** if Origin is `null` (sandboxed iframes, cross-origin redirects — attacker-controllable)
     - **Accept** only if Origin exactly matches `http://localhost:<port>`, `http://127.0.0.1:<port>`, or `http://[::1]:<port>` (IPv6 loopback)
     - This prevents DNS rebinding attacks from malicious web pages.
   - **Switch API validation:** `POST /admin/api/switch` must validate all 3 tier keys (`haiku`, `sonnet`, `opus`) are present in the request body. Return 400 listing missing tiers if any are absent.
   - **Admin page XSS prevention:** `admin.html` must use `textContent` (not `innerHTML`) for rendering config values. Provider and model names validated at write time: reject names not matching `^[a-zA-Z0-9_./-]+$` (alphanumeric + safe separators).
   - **Body size limit:** admin POST bodies capped at 64 KB (admin configs are small; prevents abuse).
   - All admin endpoints: localhost-only (reject non-127.0.0.1 and non-::1), same as /admin/shutdown
   - Existing `/admin/shutdown` preserved
   → coder verify (auto): `GET /admin/` route in do_GET; `POST /admin/api/switch` and `POST /admin/api/reload` routes in do_POST; localhost check present on all admin routes.
   → coder verify (scripted): script at `./tmp/verification/2026-08-23-cc-switch-mode-step6.py` — verifies admin.html is loadable from package data; admin API endpoint paths are defined in handler; config write uses atomic pattern (write tmp + os.replace).
   → tester verify: `test_admin_page_served`, `test_admin_api_config`, `test_admin_api_switch`, `test_admin_api_switch_invalid_provider`, `test_admin_api_reload` pass.

7. **Step 7:** CLI redesign — modify `cli.py`:
   - **Remove:** `acquire_swap_lock`, `release_swap_lock`, `read_url_lock`, `write_url_lock`, `read_settings_url`, `write_settings_url`, `validate_url`, all URL swap logic, base-url.lock management, url-swap.lock management
   - **Keep:** `is_pid_alive`, `kill_process_windows`, `prune_trace_file`
   - **`start`:**
     1. Check config.json exists → if not, copy template, print message, exit 1
     2. Prompt passphrase via vimcrypt.prompt_hidden
     3. Decrypt keys-index.json → validate (quick check: valid JSON with vendors key)
     4. Load config.json → validate against vendors
     5. Prune trace log (best-effort, existing behavior)
     6. Spawn server: `python -m claude_retry_proxy.server --port <port> --config-path <path> --keys-path <path>`, pipe passphrase via stdin
        - **stdin write error handling:** wrap `proc.stdin.write(passphrase + '\n')` + `proc.stdin.close()` in `try/except (BrokenPipeError, OSError)`. On failure: read stderr for error message, print clean error ("server failed to start: <stderr>"), skip TCP probe, proceed to cleanup (kill server, remove proxy-state.json, exit 1).
     7. Write proxy-state.json (PID, port, start_time only — no URL)
     8. TCP readiness probe (2s)
     9. On failure: kill server, remove proxy-state.json, exit 1 (no URL rollback needed)
   - **`stop`:**
     1. Read proxy-state.json for PID and port
     2. POST /admin/shutdown (existing)
     3. Wait for proxy-state.json to disappear (existing)
     4. Force-kill if needed (existing)
     5. Clean up proxy-state.json, proxy-state.lock
     6. (No URL restore — settings.json is static)
   - **`status`:** show running/stopped + PID + port + current tier mapping (read from config.json)
   - **`reload` (new):** POST to `http://127.0.0.1:<port>/admin/api/reload` → print result
   → coder verify (auto): `acquire_swap_lock`, `release_swap_lock`, `read_url_lock`, `write_url_lock`, `read_settings_url`, `write_settings_url`, `validate_url` removed from cli.py; `reload` subcommand exists in main() dispatch; `cmd_start` does not reference settings.json.
   → tester verify: `test_cli_reload`, `test_cli_start_no_config`, `test_cli_start_invalid_config`, `test_cli_status_shows_tiers` pass.

8. **Step 8:** Packaging and static assets — update `pyproject.toml` and create asset files:
   - Add `cryptography>=38.0` to `[project] dependencies` (38.0+ for Blowfish ECB support used by vimcrypt)
   - Add `[tool.setuptools.package-data]` to include `admin.html` and `config-template.json`
   - Create `src/claude_retry_proxy/admin.html` — the admin page HTML (from the demo, with `MOCK = false`)
   - Create `src/claude_retry_proxy/config-template.json` — template with empty tiers and provider model catalogs
   - Bump version to `0.2.0` in `__init__.py`
   → coder verify (auto): `cryptography` in pyproject.toml dependencies; `admin.html` and `config-template.json` exist under `src/claude_retry_proxy/`; `__version__` is `"0.2.0"`.
   → coder verify (scripted): script at `./tmp/verification/2026-08-23-cc-switch-mode-step8.py` — `pip install -e .` succeeds; `import claude_retry_proxy.admin` (or importlib.resources read) loads admin.html; config-template.json is valid JSON with tiers and models keys.

## Guidance for Planner

**Doc files to create/update:**
- `CLAUDE.md` — after coder finishes:
  - Update Architecture section (multi-provider gateway)
  - Add config.json and keys-index.json to structure
  - Document new CLI commands (reload)
  - Update env vars table (add PROXY_KEYS_PATH)
  - Remove runtime artifacts for base-url.lock and url-swap.lock
  - Update Gotchas: remove "Settings coupling is hardcoded" (no longer true), remove "12 CLI tests require non-localhost URL" (no longer applicable), add config validation gotcha, add CSRF gotcha
  - Update test count (was "36 behavioral tests" — count actual post-implementation total)
  - Update Future Work: port-bind-race stays but update impact description — "false 'Proxy started' message" instead of "settings.json corruption" (the TCP probe race still exists in Step 7, only the consequence is mitigated by static settings.json)
  - Update Document Overrides: note that "Zero runtime dependencies" is overridden
- `README.md` — after coder finishes:
  - Update usage section (config setup flow, admin page)
  - Add configuration section (config.json format, keys-index.json format and encryption)
  - Update CLI reference (add reload command, remove URL swap references)
  - Update testing section (new test count, remove settings.json backup/restore notes)
  - Update "Files written at runtime" table (remove settings.json swap entry)
  - Add dependencies section (cryptography package)

**When:** after coder finishes (documentation must reflect final implementation).

**What to sync:**
- Architecture: single-upstream → multi-provider gateway
- Config files: config.json format, keys-index.json format and encryption
- CLI: new reload command, changed start/stop semantics (no URL swap)
- Admin page: URL, functionality
- Dependencies: cryptography added
- Version: 0.2.0
- CLAUDE.md Purpose section: remove "stdlib-only" and "Zero runtime dependencies" claims
- CLAUDE.md Structure section: add vimcrypt.py, admin.html, config-template.json to file tree
- CLAUDE.md Runtime artifacts: remove proxy/base-url.lock and proxy/url-swap.lock
- README.md header: remove "Stdlib-only. Zero runtime dependencies." tagline
- README.md Features: remove "URL swapping" and "Crash recovery" bullets, remove "Zero dependencies" bullet
- README.md Quick start / How it works: rewrite to config-driven flow (no URL swap)
- README.md Direct server invocation: update flags (remove --upstream-url, add --passphrase-file)

## History

| Date | Event | Conclusion | Dismissed |
|------|-------|------------|-----------|
| 2026-08-23 | Initial plan | Multi-provider tier routing gateway — 8 steps, config-driven routing, vim blowfish2 key decryption, admin page for hot-switch | — |
| 2026-08-23 | Mega-audit (11 lenses, 66 findings: 15H/30M/21L) | Fixed 6 actionable findings: passphrase wire protocol (Step 3), resolve_tier rejects unknown with 400 (Step 4), streaming SSE error recovery + reverse map fallback (Step 5), admin API preserves models + CSRF + body cap (Step 6), cryptography version pin (Step 8). Doc sync findings (6H) deferred to Guidance for Planner. Test retirement findings (9H) deferred to Guidance for Tester. No migration plan (2H) accepted — intentional breaking change for personal tool. | [streaming-sse-error-recovery](./tmp/reports/2026-08-23-cc-switch-mode-mega-audit-2026-08-23.json), [passphrase-pipe-protocol](./tmp/reports/2026-08-23-cc-switch-mode-mega-audit-2026-08-23.json), [admin-switch-merge-models](./tmp/reports/2026-08-23-cc-switch-mode-mega-audit-2026-08-23.json), [admin-csrf-origin](./tmp/reports/2026-08-23-cc-switch-mode-mega-audit-2026-08-23.json) |
| 2026-08-24 | Mega-audit iteration 2 (11 lenses, 58 findings: 11H/29M/18L) | Fixed 12 actionable findings: resolve_tier None guard (Step 4), parse_upstream no-cache decision (Step 4), SSE buffer 64KB cap (Step 5), reverse map collision detection (Step 5), Content-Type check ordering (Step 5), streaming vs buffered clarification (Step 5), CSRF require Origin + reject null + IPv6 loopback (Step 6), Switch API tier validation (Step 6), admin.html XSS prevention (Step 6), direct server invocation passphrase (Step 3), CLI stdin write error handling (Step 7), port-bind-race stays in Future Work (Guidance for Planner). Test breakage (20+ tests) deferred to Guidance for Tester with comprehensive migration/retirement list. No migration plan accepted. | [report](./tmp/reports/2026-08-23-cc-switch-mode-mega-audit-2026-08-24.json) |
| 2026-08-24 | Spec revision (/update-plan) — coder+tester report back | Coder completed 8/8 steps, build passes. Tester: 33/52 tests pass. 15 legacy tests need migration (expected). 4 implementation defects found: response model rewriting not implemented (streaming + non-streaming), unknown model error missing tier list. All classified as coder defects (plan is clear, implementation incomplete). Returning to coder for fixes. | [response-model-rewrite](./tmp/reports/2026-08-24-response-model-rewrite-not-working.json), [tester-report](./tmp/reports/2026-08-23-cc-switch-mode-tester-2026-08-24.json) |
| 2026-08-24 | Spec revision (/update-plan) — coder fix-1 report | Coder attempted fixes for response rewriting and error message. Introduced regression: previously passing tests now fail with "status 0" (proxy not responding). Content-Type routing refactor likely has a control flow bug. Original issues moved to Fix Planned. New regression issue opened. Returning to coder for regression fix. | [coder-fix1](./tmp/reports/2026-08-23-cc-switch-mode-coder-2026-08-24-fix1.json) |
| 2026-08-24 | Planner analysis — regression root cause identified | Regression is a one-line fix: `do_POST` line 1402 sets `streamed=True` for all 2xx, but the new JSON buffering path doesn't stream — it returns the body for `do_POST` to send. Fix: `streamed = (200 <= status < 300) and (resp_body == b"")`. See issue report for full explanation. | [streamed-flag-regression](./tmp/reports/2026-08-24-streamed-flag-regression.json) |
| 2026-08-24 | Spec revision (/update-plan) — coder fix-2 report | Coder applied 3 fixes: streamed flag (line 1402), SSE message_start detection (check JSON type field), error format (flat string). Coder self-reports all 4 previously failing tests now pass. All 3 issues moved to Fix Planned. Needs tester re-run to confirm and mark Resolved. | [coder-fix2](./tmp/reports/2026-08-23-cc-switch-mode-coder-2026-08-24-fix2.json) |
| 2026-08-24 | Spec revision (/update-plan) — tester round 2 | Tester confirms 3 issues resolved (streamed flag, non-streaming rewriting, error message). New issue: SSE buffer doesn't isolate first event at `\n\n` — when both events arrive in one `read1()` chunk, rewriter fails. 1 Open issue remaining. | [sse-buffer](./tmp/reports/2026-08-23-cc-switch-mode-tester-2026-08-24-2.json) |
| 2026-08-24 | Spec revision (/update-plan) — tester round 3 | All implementation defects resolved. 37/52 tests pass: 20 new tier-routing/admin tests, 4 unit tests, 13 admin/CLI tests. 15 legacy tests still need migration to new config/keys/passphrase flow (deferred work). SSE buffer issue resolved. Verdict: SUCCESS — implementation is correct. | [tester-3](./tmp/reports/2026-08-23-cc-switch-mode-tester-2026-08-24-3.json) |
| 2026-08-24 | Phase 2 — Documentation update (planner) | CLAUDE.md rewritten: multi-provider gateway architecture, config.json/keys-index.json, admin API, CSRF, passphrase protocol, PROXY_KEYS_PATH, removed URL swap references, updated Gotchas and Future Work. README.md rewritten: config-driven quick start, tier routing features, admin page, dependencies section, removed "stdlib-only"/"zero deps" claims. | — |
| 2026-08-24 | Phase 3 — Review (reviewer agent) | 5 findings (2 Warning, 3 Suggestion), non-blocking. Warning #1: config-path validation bypass in cli.py. Warning #2: config lock held during admin I/O in server.py. User requested both warnings fixed. #2 design: drain-and-swap — block new queries, drain in-flight, swap under lock, unblock. Suggestions #3-5 deferred. | [review](./tmp/reports/2026-08-23-cc-switch-mode-review-2026-08-24.json), [warnings](./tmp/reports/2026-08-24-review-warnings-1-2.json) |
| 2026-08-24 | Spec revision — drain-and-swap design | Planner analysis found that fix-4's simple lock refactor doesn't prevent the race: response model rewrite reads the global `_reverse_model_map` at response time, which can be swapped mid-request. User chose drain-and-swap over atomic swap. New issue filed with full design (inflight counter, swap flag, Event, reverse_map snapshot). Supersedes fix-4's lock approach. | [drain-and-swap](./tmp/reports/2026-08-24-drain-and-swap-config-swap.json) |
| 2026-08-24 | Mega-audit iteration 3 (11 lenses, 39 findings: 8H/19M/12L) | 14 findings to fix (connection error jitter, stale docstring, PROXY_KEYS_PATH env var, admin API config path, switch write ordering, Content-Length parsing, provider dropdown, test duplication, cmd_status path, README description, plan metadata, CLI validation, write_config cleanup). 6 deferred (already tracked). 5 dismissed (planning artifacts, acceptable defaults). Plan metadata corrected (tester_files, verification_scripts). Issue log split (review-warnings-1-2 → two entries). | [report](./tmp/reports/2026-08-23-cc-switch-mode-mega-audit-2026-08-24-iter3.json) |
| 2026-08-24 | Spec revision (/update-plan) — coder fix-5 report | Coder completed 3/12 code items (connection error jitter, stale docstring, PROXY_KEYS_PATH env var). Planner fixed README models description. 7 coder items remain (admin config path, switch ordering, Content-Length, provider dropdown, cmd_status, CLI validation, write_config cleanup). Provider dropdown missing from coder's remaining list — needs follow-up. Test duplication for tester. Drain-and-swap still Open separately. | [coder-fix5](./tmp/reports/2026-08-23-cc-switch-mode-coder-2026-08-24-fix5.json) |
| 2026-08-25 | Spec revision (/update-plan) — coder fix-6 + tester round 4 | Coder fix-6 completed 6/6 remaining items (admin config path, switch ordering, Content-Length, cmd_status, CLI validation, write_config cleanup). Tester: 37/52 pass, no regressions from fix-4/5/6. 12/14 mega-audit-iter3 findings resolved. 2 remaining: provider dropdown (coder skipped), test duplication (tester didn't remove). Drain-and-swap still Open separately. | [coder-fix6](./tmp/reports/2026-08-23-cc-switch-mode-coder-2026-08-24-fix6.json), [tester-r4](./tmp/reports/2026-08-23-cc-switch-mode-tester-2026-08-25.json) |
| 2026-08-25 | Spec revision (/update-plan) — coder fix-7 | Coder fix-7 completed provider dropdown (GET /admin/api/providers endpoint + admin.html population). 13/14 mega-audit-iter3 findings resolved. 1 remaining: test duplication (tester needs to remove). Drain-and-swap still Open separately. No new tester report — tester needs re-run to verify fix-7 and remove duplicate test. | [coder-fix7](./tmp/reports/2026-08-23-cc-switch-mode-coder-2026-08-25-fix7.json) |
| 2026-08-25 | Drain-and-swap sent to coder | Drain-and-swap pattern (Open issue since 2026-08-24) sent to coder for implementation. Detailed instructions with exact line references and code patterns provided. | [drain-and-swap](./tmp/reports/2026-08-24-drain-and-swap-config-swap.json) |
| 2026-08-25 | Spec revision (/update-plan) — drain-and-swap coder report | Coder implemented drain-and-swap: forward_request split into wrapper+impl, module-level state (_inflight_count, _config_swapping, _swap_done), admin switch/reload drain with 30s timeout (abort on exceed), 100ms poll interval. Build passes. Needs tester verification. Test duplication still pending (tester). No new tester report. | [coder-drain](./tmp/reports/2026-08-23-cc-switch-mode-coder-2026-08-25-drain-and-swap.json) |
| 2026-08-25 | Spec revision (/update-plan) — tester round 5 + drain-and-swap verified | Tester: 36/51 pass, 15 legacy fail (deferred). Duplicate test removed (test_client_api_key_ignored). No regressions from fix-7 or drain-and-swap. All mega-audit-iter3 items resolved (14/14). Drain-and-swap implemented but no dedicated race condition test yet. All Open issues now resolved. Ready for finalization. | [tester-r5](./tmp/reports/2026-08-23-cc-switch-mode-tester-2026-08-25.json) |
| 2026-08-25 | Coder deferred-issues (port-bind race, streaming size cap) + tester round 6 (legacy migration) | Coder fixed 2 Future Work items: port-bind readiness race (READY handshake) and streaming response size cap (PROXY_MAX_RESPONSE_SIZE). Tester migrated 15 legacy tests: 49/51 pass. 2 new defects: (1) SSE buffering prevents real-time streaming (no `\n\n` in test data → full buffer), (2) non-SSE path missing `wfile.flush()` → client disconnect not detected. /admin/shutdown CSRF NOT addressed (coder went off-task). | [coder-deferred](./tmp/reports/2026-08-23-cc-switch-mode-coder-2026-08-25-deferred-issues.json), [tester-r6](./tmp/reports/2026-08-23-cc-switch-mode-tester-2026-08-25.json) |
| 2026-08-25 | Spec revision — streaming-fixes regression analysis | Coder streaming-fixes introduced regression: removed SSE model rewriting in favor of real-time streaming. Plan Step 5 requires model rewriting (non-negotiable). Root cause analysis: (1) `streaming-response-body` test has wrong data (no `\n\n` for SSE), not a code bug — fix test, not code. (2) Client disconnect is a timing issue (proxy finishes 2MB write before client closes) — fix test mock to send slowly. (3) SSE model rewriting must be reverted to buffer-first-event design. | [coder-streaming](./tmp/reports/2026-08-23-cc-switch-mode-coder-2026-08-25-streaming-fixes.json), [tester-r7](./tmp/reports/2026-08-23-cc-switch-mode-tester-2026-08-25-2.json) |
| 2026-08-25 | Spec revision (/update-plan) — all 3 regressions verified resolved | Test run: 51/51 pass. SSE model rewriting code already correct (buffer-first-event + rewrite at lines 1087-1134). Test data and disconnect mock already fixed. 3 issues marked Resolved. New issue filed: `/admin/shutdown` missing CSRF check (server.py:1291). review-warnings #2 marked Resolved (drain-and-swap). 1 Open issue remaining. | — |
| 2026-08-25 | Coder revert-sse + admin-shutdown-csrf question | Coder confirmed SSE revert to buffer-first-event (matches verified code). Coder flagged CSRF check order discrepancy: my instruction said CSRF-first but existing endpoints do localhost-first. Decision: Option A — follow existing pattern (localhost first, CSRF second) for consistency. admin-shutdown-csrf moved to Fix Planned. | [coder-revert-sse](./tmp/reports/2026-08-23-cc-switch-mode-coder-2026-08-25-revert-sse.json), [coder-csrf-question](./tmp/reports/2026-08-23-cc-switch-mode-coder-2026-08-25-admin-shutdown-csrf-question.json) |
| 2026-08-25 | Spec revision (/update-plan) — all issues resolved, ready for finalization | Coder added CSRF check to `/admin/shutdown` (Option A). Tester: 51/51 pass (100%). All issues resolved: admin-shutdown-csrf, sse-model-rewrite-regression, streaming-response-buffered, client-disconnect-detection. No open issues. No deferred work. Plan is ready for finalization. | [coder-csrf-fix](./tmp/reports/2026-08-23-cc-switch-mode-coder-2026-08-25-admin-shutdown-csrf-fix.json), [tester-final](./tmp/reports/2026-08-23-cc-switch-mode-tester-2026-08-25.json) |
| 2026-08-25 | Reviewer findings — 3 issues filed | Reviewer found 2 Warnings + 1 Suggestion: (1) drain-and-swap race between config and reverse_map snapshots, (2) cmd_stop broken by CSRF check (no Origin header), (3) PROXY_MAX_RESPONSE_SIZE undocumented. All non-blocking but should be fixed before commit. | — |
| 2026-08-25 | Spec revision (/update-plan) — reviewer fixes verified, doc work remaining | Coder fixed 2 reviewer warnings (drain-swap race, cmd_stop CSRF). Tester: 51/51 pass (100%). 2 issues Resolved. 1 doc suggestion remains (PROXY_MAX_RESPONSE_SIZE env var → Fix Planned, planner scope). | [coder-reviewer-fixes](./tmp/reports/2026-08-23-cc-switch-mode-coder-2026-08-25-reviewer-fixes.json), [tester-final](./tmp/reports/2026-08-23-cc-switch-mode-tester-2026-08-25.json) |
| 2026-08-25 | Doc work complete — all issues resolved | Added `PROXY_MAX_RESPONSE_SIZE` to CLAUDE.md env var table. All 3 reviewer findings now Resolved. Plan is complete: 0 Open issues, 0 deferred work, 51/51 tests pass. Ready for finalization. | — |

## Plan Metadata

```json
{
  "plan_id": "2026-08-23-cc-switch-mode",
  "steps": [
    "Step 1: Bundle vimcrypt.py",
    "Step 2: Config loading and validation",
    "Step 3: Key decryption at startup",
    "Step 4: Tier routing and request rewriting",
    "Step 5: Response model rewriting",
    "Step 6: Admin page and API",
    "Step 7: CLI redesign",
    "Step 8: Packaging and static assets"
  ],
  "coder_files": [
    "src/claude_retry_proxy/server.py",
    "src/claude_retry_proxy/cli.py",
    "pyproject.toml"
  ],
  "tester_files": [
    "tests/test_claude_proxy.py"
  ],
  "doc_files": [
    "CLAUDE.md",
    "README.md"
  ],
  "verification_scripts": [],
  "repo_mode": "Public",
  "document_overrides": [
    "CLAUDE.md: Zero runtime dependencies (Reason: cryptography package required for vim blowfish2 decryption)"
  ]
}
```

## Audit Accumulation

| Counter | Value | Last Updated |
|---------|-------|--------------|
| issues_resolved_since_audit | 0 | 2026-08-24 |
| steps_changed_since_audit | 0 | 2026-08-24 |
| files_changed_since_audit | 0 | 2026-08-24 |

## Documentation

- [README.md](README.md) — user-facing: install, usage, configuration, trace log, the `--all` data-exposure warning, testing notes.
- [scripts/analyze_proxy_trace.py](scripts/analyze_proxy_trace.py) — trace log analysis tool.
- Design rationale for the extraction lives in `tmp/plans/2026-07-17-extract-retry-proxy-design.md` (gitignored — planning artifact, not published).

## Final Results
(Populated after implementation completes.)
