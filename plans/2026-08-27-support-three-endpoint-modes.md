# Plan: Support three endpoint modes in proxy (chat + response)
**Project:** D:\proj\claude-retry-proxy
**Plan ID:** 2026-08-27-support-three-endpoint-modes
**Created:** 2026-08-27

## Issue Log

| Issue | Status | Found | Resolved | Resolved By |
|-------|--------|-------|----------|-------------|
| [review-sse-missing-event-line](./tmp/reports/2026-08-27-support-three-endpoint-modes-review-sse-missing-event-line.json) | Resolved | 2026-08-27 | 2026-08-27 | [tester](./tmp/reports/2026-08-27-support-three-endpoint-modes-tester-2026-08-27.json) |
| [review-sse-tool-calls-stop-reason-mismatch](./tmp/reports/2026-08-27-support-three-endpoint-modes-review-sse-tool-calls-stop-reason-mismatch.json) | Resolved | 2026-08-27 | 2026-08-27 | [tester](./tmp/reports/2026-08-27-support-three-endpoint-modes-tester-2026-08-27.json) |
| [missing-verification-scripts](./tmp/reports/2026-08-27-support-three-endpoint-modes-missing-verification-scripts.json) | Resolved | 2026-08-27 | 2026-08-27 | [coder](./tmp/reports/2026-08-27-support-three-endpoint-modes-coder-2026-08-27.json) |
| [support-three-endpoint-modes](./tmp/reports/defer-issue-support-three-endpoint-modes.json) | Resolved | 2026-08-27 | 2026-08-27 | [tester](./tmp/reports/2026-08-27-support-three-endpoint-modes-tester-2026-08-27.json) |

## Guidance for Coder

**Files to modify:**
- `src/claude_retry_proxy/server.py`
- `src/claude_retry_proxy/admin.html`

### Step-by-step with verification

Each step has coder checks tagged `(auto)`. The coder self-verifies `(auto)` checks via grep, line-read, and build verification. Tester owns the behavioral checks.

1. **Step 1:** Read `mode` from vendor entry in `_forward_request_impl`, default to `"anthropic"` when absent. After extracting `api_key = vendor["key"]`, read `mode = vendor.get("mode", "anthropic")`. Validate that mode is one of `{"anthropic", "chat", "response"}` — return 500 with `"invalid_provider_mode"` error if not. Treat `None`, empty string, and missing keys as `"anthropic"`. Keep `mode` as a local variable in `_forward_request_impl` — do NOT thread it into the return tuple (the dispatch is internal per Step 9). Add mode validation at startup: in `load_keys_file`, validate that any present `mode` field is in the allowed set, and emit a stderr warning when a non-standard or absent mode is used (matching the existing plain-keys warning pattern). Log a trace event when a non-anthropic mode is dispatched for observability.
   → coder verify (auto): `mode = vendor.get("mode", "anthropic")` appears in `_forward_request_impl` after the `api_key` line; invalid mode returns 500 with `"invalid_provider_mode"` in the error JSON; `load_keys_file` validates mode enum; stderr warning emitted for absent/unknown mode; trace event logged for non-anthropic mode dispatch
      → tester verify: `test_mode_defaults_to_anthropic` — vendor without `mode` field is treated as `"anthropic"`; `test_mode_invalid_rejected` — vendor with `mode: "unknown"` returns 500; `test_mode_null_defaults_to_anthropic` — vendor with `mode: null` treated as `"anthropic"`

2. **Step 2:** Dispatch auth header based on mode. In the header-building section of `_forward_request_impl`, after the existing `fwd_headers["x-api-key"] = api_key` line:
   - If `mode == "anthropic"`: keep existing behavior (`x-api-key` header, drop `authorization`)
   - If `mode in ("chat", "response")`: inject `Authorization: Bearer <api_key>` instead of `x-api-key`, still drop the original `authorization` and `x-api-key` headers
   → coder verify (auto): `if mode == "anthropic":` branch sets `x-api-key`; `else:` branch sets `Authorization: Bearer`; original `authorization` and `x-api-key` headers are dropped in both branches
   → tester verify: `test_auth_header_anthropic_mode` — request forwarded with `x-api-key` header; `test_auth_header_chat_mode` — request forwarded with `Authorization: Bearer` header; `test_auth_header_response_mode` — request forwarded with `Authorization: Bearer` header

3. **Step 3:** Dispatch path construction based on mode. In the upstream-path construction section:
   - If `mode == "anthropic"`: `upstream_path = path_prefix + path if path_prefix else path` (existing behavior — append original request path, e.g. `/v1/messages`)
   - If `mode == "chat"`: strip a trailing `/v1` from `path_prefix` if present (to avoid double `/v1/v1/chat/completions` when the URL already ends in `/v1`), then `upstream_path = path_prefix + "/v1/chat/completions"`
   - If `mode == "response"`: same trailing-`/v1` stripping, then `upstream_path = path_prefix + "/v1/responses"`
   This way `url = "https://opencode.ai/zen/go"` + `"/v1/chat/completions"` → `/zen/go/v1/chat/completions`, and `url = "https://api.openai.com/v1"` + `"/v1/chat/completions"` → `/v1/chat/completions` (not `/v1/v1/chat/completions`).
   - **count_tokens handling:** For `chat` and `response` modes, if the incoming path is `/v1/messages/count_tokens`, return 400 with `{"error": "count_tokens not supported in chat/response mode"}` — the `/v1/chat/completions` and `/v1/responses` endpoints have no token-counting equivalent.
   → coder verify (auto): path construction guarded by `if mode == "anthropic":` / `elif mode == "chat":` / `elif mode == "response":`; chat appends `"/v1/chat/completions"`; response appends `"/v1/responses"`; trailing `/v1` stripped from path_prefix; count_tokens returns 400 for chat/response modes
   → tester verify: `test_path_anthropic_mode` — upstream path includes original request path; `test_path_chat_mode` — upstream path is `path_prefix + "/v1/chat/completions"`; `test_path_response_mode` — upstream path is `path_prefix + "/v1/responses"`; `test_path_double_v1_prevention` — URL ending in `/v1` doesn't produce `/v1/v1/`; `test_count_tokens_rejected_chat_mode` — count_tokens returns 400 in chat mode

4. **Step 4:** Add `_anthropic_to_chat(body_json)` function. Transform an Anthropic Messages request body into an OpenAI Chat Completions request body. Rules:
   - `model` → `model` (pass through, already rewritten)
   - `messages` → `messages` (pass through)
   - `system` (string) → prepend `{"role": "system", "content": system}` to messages array
   - `system` (list of content blocks) → concatenate `text`-type blocks with newline separator, prepend system message; drop non-text blocks
   - `max_tokens` → `max_tokens` (pass through if present)
   - `temperature` → `temperature` (pass through if present)
   - `stop_sequences` → `stop` (rename if present, value is list of strings)
   - `stream` → `stream` (pass through if present)
   - `top_p` → `top_p` (pass through if present)
   - Drop: `thinking`, `tools`, `tool_choice`, `metadata`, `top_k`
   Return the transformed dict.
   → coder verify (auto): `_anthropic_to_chat` defined in `server.py`; accepts one argument (dict); returns dict; system string becomes first message; system list concatenates text blocks; `stop_sequences` renamed to `stop`; `top_k`/`thinking`/`tools`/`tool_choice`/`metadata` absent from output
      → tester verify: `test_anthropic_to_chat_basic` — messages, model, max_tokens, temperature mapped correctly; `test_anthropic_to_chat_system_string` — system string prepended as system message; `test_anthropic_to_chat_system_list` — system content blocks concatenated; `test_anthropic_to_chat_dropped_fields` — thinking, tools, metadata, top_k absent; `test_anthropic_to_chat_stop_sequences` — renamed to stop

5. **Step 5:** Add `_chat_to_anthropic(chat_body, tier)` function. Transform an OpenAI Chat Completions JSON response into an Anthropic Messages JSON response. All field access MUST use `.get()` chains with defaults — never bare subscripts — to survive malformed upstream responses without crashing the worker thread. Rules:
   - `id` → `id` = `"msg_" + chat_body.get("id", str(uuid.uuid4()))`
   - `model` = `tier` (rewrite to tier name)
   - `type` = `"message"` (hardcoded)
   - `role` = `"assistant"` (hardcoded)
   - `choices` = `chat_body.get("choices", [])`; if empty or missing, return minimal valid response
   - `message` = `choices[0].get("message", {})` if choices non-empty
   - `content` = `message.get("content")`; if isinstance(content, str): `content = [{"type": "text", "text": content}]`; elif isinstance(content, list): map each `{"type": "text", ...}` part individually; if null/empty: `content = []`
   - `tool_calls` = `message.get("tool_calls")`; if present, add `tool_use` content blocks to `content` array (map `function.name` → `name`, `function.arguments` → `input` (try `json.loads`, fallback to `{}` on any parse error + trace event), `id` → `id`)
   - `finish_reason` = `choices[0].get("finish_reason")`; map to `stop_reason`: `"stop"` → `"end_turn"`, `"length"` → `"max_tokens"`, `"tool_calls"` → `"tool_use"`, `"content_filter"` → `null` (not a valid Anthropic stop_reason), anything else → `null`
   - `stop_sequence` = `null` (hardcoded)
   - `usage` = `chat_body.get("usage", {})`; `usage.input_tokens` = `usage.get("prompt_tokens", 0)`; `usage.output_tokens` = `usage.get("completion_tokens", 0)`
   - Wrap the entire function body in try/except (JSONDecodeError, KeyError, TypeError, IndexError, AttributeError): on failure, log a trace event (`transform_failure`) and return the original body unchanged (passthrough fallback, matching `_rewrite_json_response`'s pattern at server.py:1068-1071)
   → coder verify (auto): `_chat_to_anthropic` defined in `server.py`; accepts two arguments (dict, str); returns dict; all field access uses `.get()`; `content_filter` maps to `null`; usage uses `.get()` with zero defaults; tool_calls `json.loads` wrapped in try/except; outer try/except returns original body on failure + trace event
      → tester verify: `test_chat_to_anthropic_basic` — content, model, stop_reason, usage mapped correctly; `test_chat_to_anthropic_empty_choices` — returns minimal valid response; `test_chat_to_anthropic_tool_calls` — tool calls mapped to content blocks; `test_chat_to_anthropic_finish_reason_mapping` — all finish_reason values mapped correctly; `test_chat_to_anthropic_usage_absent` — handles missing usage gracefully; `test_chat_to_anthropic_content_array` — handles array content; `test_chat_to_anthropic_malformed_tool_args` — malformed JSON arguments don't crash

6. **Step 6:** Add `_anthropic_to_response(body_json)` function. Transform an Anthropic Messages request body into an OpenAI Responses request body. Rules:
   - `model` → `model` (pass through, already rewritten)
   - Force `"stream": false` — do NOT pass through the client's `stream` flag. Response-mode SSE is not yet implemented (see Out of scope), so the upstream must return JSON. Hardcode `"stream": false` in the output.
   - Extract `input` from the last user message: find the last message with `role: "user"`, concatenate all text content blocks from it. If `content` is a string, use it directly. If `content` is an array, join `text`-type blocks with newline. If no user message exists: return `input: ""` (empty string).
   - `system` (string or list) → `instructions` (string; if list, concatenate text blocks)
   - `max_tokens` → `max_output_tokens` (rename if present)
   - `temperature` → `temperature` (pass through if present)
   - `top_p` → `top_p` (pass through if present)
   - Drop: `messages`, `thinking`, `tools`, `tool_choice`, `metadata`, `stop_sequences`, `top_k`
   - **Note:** response mode is single-turn only — it extracts only the last user message as `input` and discards the full conversation history. This is a known limitation documented in Out of scope.
   → coder verify (auto): `_anthropic_to_response` defined in `server.py`; accepts one argument (dict); returns dict; `"stream": false` is hardcoded in output; `input` is string from last user message; `system` → `instructions`; `max_tokens` → `max_output_tokens`; `messages` absent from output; no-user-message → `input: ""`
      → tester verify: `test_anthropic_to_response_basic` — model, input, instructions, stream mapped correctly; `test_anthropic_to_response_system_list` — system list concatenated to instructions; `test_anthropic_to_response_multiple_user_messages` — last user message used for input; `test_anthropic_to_response_no_user_message` — returns `input: ""`; `test_anthropic_to_response_stream_forced_false` — stream is always false regardless of input

7. **Step 7:** Add `_response_to_anthropic(resp_body, tier)` function. Transform an OpenAI Responses JSON response into an Anthropic Messages JSON response. All field access MUST use `.get()` chains. Rules:
   - `id` → `id` (pass through — Responses API uses `resp_` prefix, which is fine)
   - `model` = `tier` (rewrite to tier name)
   - `type` = `"message"` (hardcoded)
   - `role` = `"assistant"` (hardcoded)
   - `output` = `resp_body.get("output", [])`; if empty or missing, return minimal valid response
   - For each output item of `type: "message"`, extract `content` blocks; map `output_text` → `{"type": "text", "text": ...}`. Drop non-text content blocks.
   - `status` = `resp_body.get("status")`; derive `stop_reason`: `"completed"` → `"end_turn"`, `"incomplete"` → `null`, anything else → `null`
   - `stop_sequence` = `null`
   - `usage` = `resp_body.get("usage", {})`; `usage.input_tokens` = `usage.get("input_tokens", 0)`; `usage.output_tokens` = `usage.get("output_tokens", 0)`
   - Wrap the entire function body in try/except (JSONDecodeError, KeyError, TypeError, IndexError, AttributeError): on failure, log a trace event (`transform_failure`) and return the original body unchanged (passthrough fallback)
   → coder verify (auto): `_response_to_anthropic` defined in `server.py`; accepts two arguments (dict, str); returns dict; all field access uses `.get()`; stop_reason derived from `status` field; outer try/except returns original body on failure + trace event
      → tester verify: `test_response_to_anthropic_basic` — content, model, usage mapped correctly; `test_response_to_anthropic_empty_output` — returns minimal valid response; `test_response_to_anthropic_multiple_output` — first message output used for content; `test_response_to_anthropic_status_completed` — stop_reason derived from status; `test_response_to_anthropic_usage_absent` — handles missing usage gracefully

8. **Step 8:** Add SSE transformation for chat mode. In `_stream_upstream_response`, when `mode == "chat"` and `is_sse` is true:
   - **Frame assembly:** All SSE events (first and subsequent) MUST be assembled by accumulating bytes until `\n\n` delimiter found, then processing the complete event. Never parse partial SSE frames. Malformed JSON in a data line → skip-and-log (trace event `chat_sse_malformed_json`), continue to next event.
   - **Buffer limit:** First event capped at 64 KB (same as existing SSE path). If cap exceeded before `\n\n`: emit synthetic `message_start` with `id = "msg_" + str(uuid.uuid4())` and `model = tier`, emit `content_block_start`, forward the raw buffer as-is (matching the `rewrite_skipped` pattern for anthropic mode at server.py:1171-1179).
   - **First event:** Parse the first `data:` line to extract `id` and `model` from the first chat completion chunk. Also scan for `choices[0].delta.content` — if the first chunk carries actual text content (some providers like DeepSeek), emit it as a `content_block_delta` after the synthetic events.
   - **Synthetic events:** Emit `message_start` (with `id = "msg_" + chat_id` if available, else `"msg_" + str(uuid.uuid4())`), then `content_block_start`. All synthetic event payloads MUST be built as dicts and serialized via `json.dumps` — never raw string interpolation of provider-controlled fields (SSE injection prevention, matching `_rewrite_sse_first_event`'s safe pattern at server.py:1047-1053).
   - **SSE wire format — `event:` line REQUIRED:** `_sse_event()` MUST emit `event: <type>\ndata: <json>\n\n` — NOT `data:`-only. The Anthropic Python SDK and TypeScript SDK dispatch streaming events solely on the SSE `event:` field against a hardcoded whitelist (`message_start`, `message_delta`, `message_stop`, `content_block_*`). When no `event:` line is present the decoder's event is `None`, which matches no whitelist branch, so every event is silently dropped. Claude Code uses the TS SDK → `stream.finalMessage()` throws "request ended without sending any chunks". Extract the event type from `payload["type"]` and emit it as the `event:` line. <!-- UPDATED: review-sse-missing-event-line -->
   - **Tool call delta tracking:** `handle_frame()` MUST track whether `delta.tool_calls` was seen in any frame. The SSE path does not transform `delta.tool_calls` into `tool_use` content blocks (tool-use SSE transformation is out of scope), but the terminal maps `finish_reason "tool_calls"` → `stop_reason "tool_use"`. When `delta.tool_calls` was seen but not transformed, degrade the terminal `stop_reason` from `"tool_use"` to `null` to prevent a mid-session tool hang (Claude Code sees `stop_reason="tool_use"` with zero `tool_use` content blocks). Track with a `tool_calls_seen` boolean, set `True` when `delta.get("tool_calls") is not None`; in the terminal path, if `tool_calls_seen and sr == "tool_use"` → `sr = None`. <!-- UPDATED: review-sse-tool-calls-stop-reason-mismatch -->
   - **Subsequent events:** For each complete SSE event: parse `data: {...}`, guard `choices` access (`choices = chunk.get("choices", [])`; if empty, check for `usage` and accumulate it for the terminal `message_delta`). Extract `choices[0].get("delta", {}).get("content")` — if present, emit `content_block_delta`. Never index `choices[0]` unguarded.
   - **Terminal events:** When `choices[0].get("finish_reason")` is non-null OR end-of-stream (EOF/read error without finish_reason): emit `content_block_stop`, `message_delta` (with `stop_reason` mapped per Step 5 + accumulated `usage` if present), `message_stop`. This ensures the Anthropic SSE stream always terminates even if the upstream closes without sending a finish_reason chunk.
   - Skip `[DONE]` sentinel.
   - First-byte latency is measured from the first upstream chunk received.
   → coder verify (auto): chat-mode SSE path exists in `_stream_upstream_response`; all SSE events assembled via `\n\n` delimiter; synthetic events use `json.dumps`; `choices[0]` access guarded with `.get()`; empty-choices chunk handled without crash; terminal events synthesized on EOF; `[DONE]` skipped; first-event content delta emitted if present; cap-exceed fallback uses uuid; `_sse_event()` emits `event:` line with type from `payload["type"]`; `tool_calls_seen` flag tracked in `handle_frame()`; terminal `stop_reason` degraded to `null` when `tool_calls_seen and sr == "tool_use"`
      → tester verify: `test_chat_sse_basic_streaming` — simulated OpenAI SSE chunks produce valid Anthropic SSE events; `test_chat_sse_finish_reason_mapping` — finish_reason maps correctly in message_delta; `test_chat_sse_no_content_delta` — chunks without content delta don't produce content_block_delta; `test_chat_sse_empty_choices_usage_chunk` — empty-choices usage chunk doesn't crash; `test_chat_sse_eof_without_finish_reason` — terminal events synthesized on EOF; `test_chat_sse_first_event_has_content` — first-chunk content delta emitted; `test_chat_sse_event_line_present` — every data-bearing SSE frame has an `event:` line matching the JSON `type` field; `test_chat_sse_tool_calls_stop_reason_null` — tool_calls finish_reason maps to null stop_reason when tool_calls deltas were seen but not transformed

9. **Step 9:** Wire transformations into `_forward_request_impl`. In the request/response handling sections:
   - **Request body rewriting:** Build `rewritten_body` once BEFORE the retry loop (alongside `fwd_headers`), sourcing mode from the vendor snapshot. After the existing `body_json["model"] = actual_model` line: if `mode == "chat"`: `rewritten_body = json.dumps(_anthropic_to_chat(body_json)).encode("utf-8")`; elif `mode == "response"`: `rewritten_body = json.dumps(_anthropic_to_response(body_json)).encode("utf-8")`; else (anthropic): keep existing model-only rewrite. Never re-transform inside the retry loop — the pre-built `rewritten_body` is reused on every attempt.
   - **JSON response rewriting (2xx buffered path only):** After buffering the JSON response body, replace the existing `resp_body = _rewrite_json_response(...)` line with a dispatch: if `mode == "chat"`: `resp_body = _transform_and_guard(resp_body, tier, _chat_to_anthropic, request_id)`; elif `mode == "response"`: `resp_body = _transform_and_guard(resp_body, tier, _response_to_anthropic, request_id)`; else: `resp_body = _rewrite_json_response(resp_body, tier, request_id)`. Define `_transform_and_guard(raw_body, tier, transform_fn, request_id)` as a helper that accepts raw bytes: first try `parsed = json.loads(raw_body)` INSIDE the try/except; then try `json.dumps(transform_fn(parsed, tier)).encode("utf-8")`; on any exception (JSONDecodeError, KeyError, TypeError, IndexError, AttributeError), log a trace event (`transform_failure`) and return the original `raw_body` unchanged (passthrough-on-failure, matching `_rewrite_json_response`'s pattern at server.py:1068-1071 where `json.loads` is inside the guard). Called as `_transform_and_guard(resp_body, tier, _chat_to_anthropic, request_id)` — the raw bytes, not pre-parsed JSON.
   - **Non-2xx path:** Do NOT transform. Pass the upstream body through byte-for-byte without any mode dispatch. The existing `_rewrite_json_response` for anthropic mode is kept; for chat/response modes, skip all transformation on non-2xx. This matches the Summary: "Error responses pass through untransformed."
   - **SSE streaming (2xx path):** Pass `mode` to `_stream_upstream_response`; the existing SSE path handles `anthropic` mode; the new chat SSE path (Step 8) handles `chat` mode; `response` mode: Step 6 forces `stream: false` so the upstream returns JSON, not SSE — the 2xx JSON buffered path handles it.
   - **Non-SSE/non-JSON 2xx path:** For `chat` and `response` modes, if the upstream returns a non-SSE, non-JSON content type, buffer and transform as JSON via `_transform_and_guard` (since OpenAI APIs always return JSON or SSE).
   - **Content-Length:** After transformation, recompute `Content-Length` on the rewritten body (already done by existing code at server.py:823, 861 — ensure the new transform paths also update it).
   → coder verify (auto): request body built once before retry loop; JSON response transform only on 2xx; non-2xx passes through untransformed; `_transform_and_guard` helper defined; response mode SSE prevented by `stream: false`; Content-Length recomputed after transform
      → tester verify: `test_chat_mode_e2e_json` — end-to-end chat mode request/response through proxy; `test_response_mode_e2e_json` — end-to-end response mode request/response through proxy; `test_anthropic_mode_unchanged` — existing behavior preserved; `test_chat_mode_non_2xx_passthrough` — chat mode error body passes through untransformed; `test_transform_failure_passthrough` — malformed JSON response body passes through with trace event; `test_retry_does_not_double_transform` — 429 retry sends single-transformed body

10. **Step 10:** Update admin page to display mode per provider. Two changes:
    - **Server-side (`server.py`):** Add `GET /admin/api/providers-detail` endpoint in `do_GET`. Returns `{"providers": {"name": {"mode": "anthropic|chat|response"}, ...}}` — mode only, no keys. Validate mode against `{anthropic, chat, response}` before returning (default `"anthropic"` for absent/unknown). Localhost-only, no CSRF needed for GET. The `_vendors` table is read-only after init, so no drain-and-swap needed for this read-only endpoint.
    - **Client-side (`admin.html`):** Fetch from `/admin/api/providers-detail` alongside the existing config/providers fetches. Append the mode to each provider name in the dropdown (e.g., `"test-provider (chat)"`) using `opt.textContent` (never `innerHTML` — XSS prevention). The mode label is read-only.
    → coder verify (auto): `GET /admin/api/providers-detail` handler exists in `do_GET`; returns `{"providers": {...}}` with mode per provider; mode validated against allowed set; mode label appended to provider dropdown options via `textContent`; endpoint is localhost-only
    → tester verify: `test_admin_providers_detail` — endpoint returns mode per provider without keys; `test_admin_providers_detail_no_mode` — providers without mode return `"anthropic"`; `test_admin_providers_detail_forbidden` — non-localhost rejected; `test_admin_providers_detail_invalid_mode_normalized` — unknown mode normalized to `"anthropic"`

## Guidance for Tester

**Tests to create:**
- **Permanent:**
  - `test_mode_defaults_to_anthropic` — vendor dict without `mode` key → treated as `"anthropic"`
  - `test_mode_invalid_rejected` — vendor with `mode: "unknown"` returns 500 with `"invalid_provider_mode"`
  - `test_auth_header_anthropic_mode` — anthropic mode uses `x-api-key` header
  - `test_auth_header_chat_mode` — chat mode uses `Authorization: Bearer` header
  - `test_auth_header_response_mode` — response mode uses `Authorization: Bearer` header
  - `test_path_anthropic_mode` — upstream path includes original `/v1/messages` path
  - `test_path_chat_mode` — upstream path is `path_prefix + "/v1/chat/completions"`
  - `test_path_response_mode` — upstream path is `path_prefix + "/v1/responses"`
  - `test_anthropic_to_chat_basic` — messages, model, max_tokens, temperature mapped correctly
  - `test_anthropic_to_chat_system_string` — system string prepended as system message
  - `test_anthropic_to_chat_system_list` — system content blocks concatenated
  - `test_anthropic_to_chat_dropped_fields` — thinking, tools, metadata, top_k absent from output
  - `test_anthropic_to_chat_stop_sequences` — renamed to stop
  - `test_chat_to_anthropic_basic` — content, model, stop_reason, usage mapped correctly
  - `test_chat_to_anthropic_empty_choices` — returns minimal valid response
  - `test_chat_to_anthropic_tool_calls` — tool calls mapped to content blocks
  - `test_chat_to_anthropic_finish_reason_mapping` — all finish_reason values mapped correctly
  - `test_anthropic_to_response_basic` — model, input, instructions, stream mapped correctly
  - `test_anthropic_to_response_system_list` — system list concatenated to instructions
  - `test_anthropic_to_response_multiple_user_messages` — last user message used for input
  - `test_response_to_anthropic_basic` — content, model, usage mapped correctly
  - `test_response_to_anthropic_empty_output` — returns minimal valid response
  - `test_response_to_anthropic_multiple_output` — first message output used for content
  - `test_chat_sse_basic_streaming` — simulated OpenAI SSE chunks produce valid Anthropic SSE events
  - `test_chat_sse_finish_reason_mapping` — finish_reason maps correctly in message_delta
  - `test_chat_sse_no_content_delta` — chunks without content delta don't produce content_block_delta
  - `test_chat_mode_e2e_json` — end-to-end chat mode request/response through live proxy
  - `test_response_mode_e2e_json` — end-to-end response mode request/response through live proxy
  - `test_anthropic_mode_unchanged` — existing behavior preserved (backward compat)
  - `test_admin_providers_detail` — endpoint returns mode per provider without keys
  - `test_admin_providers_detail_no_mode` — providers without mode return `"anthropic"`
  - `test_admin_providers_detail_forbidden` — non-localhost rejected
  - `test_admin_providers_detail_invalid_mode_normalized` — unknown mode in keys normalized to `"anthropic"`
  - `test_mode_null_defaults_to_anthropic` — vendor with `mode: null` treated as `"anthropic"`
  - `test_count_tokens_rejected_chat_mode` — count_tokens returns 400 in chat mode
  - `test_count_tokens_rejected_response_mode` — count_tokens returns 400 in response mode
  - `test_chat_to_anthropic_usage_absent` — handles missing usage gracefully
  - `test_chat_to_anthropic_content_array` — handles array content (multi-part)
  - `test_chat_to_anthropic_malformed_tool_args` — malformed tool arguments don't crash
  - `test_response_to_anthropic_usage_absent` — handles missing usage gracefully
  - `test_response_to_anthropic_status_completed` — stop_reason derived from status field
  - `test_anthropic_to_response_no_user_message` — no user message → `input: ""`
  - `test_anthropic_to_response_stream_forced_false` — stream always false
  - `test_path_double_v1_prevention` — URL ending in `/v1` doesn't produce `/v1/v1/`
  - `test_chat_sse_empty_choices_usage_chunk` — empty-choices usage chunk doesn't crash
  - `test_chat_sse_eof_without_finish_reason` — terminal events synthesized on EOF
  - `test_chat_sse_first_event_has_content` — first-chunk content delta emitted
  - `test_chat_sse_event_line_present` — every data-bearing SSE frame has an `event:` line matching the JSON `type` field <!-- UPDATED: review-sse-missing-event-line -->
  - `test_chat_sse_tool_calls_stop_reason_null` — tool_calls finish_reason maps to null stop_reason when tool_calls deltas were seen but not transformed <!-- UPDATED: review-sse-tool-calls-stop-reason-mismatch -->
  - `test_chat_mode_non_2xx_passthrough` — chat mode error body passes through untransformed
  - `test_transform_failure_passthrough` — malformed JSON response body passes through with trace event
  - `test_retry_does_not_double_transform` — 429 retry sends single-transformed body
- **Temporary:** None

**Tests to investigate for retirement:**
- No test obsolescence identified. No existing tests are tied to functions or behaviors being removed. The `_rewrite_json_response` and `_rewrite_sse_first_event` functions remain in use for the anthropic mode path.

## Summary

**Problem:** The proxy currently only handles the Anthropic Messages API format. OpenCode Zen (and potentially other providers) expose three distinct API formats requiring different request/response transformations. The `mode` field has already been added to the live `keys-index.json` but the proxy ignores it.

**Approach:** Read `mode` from each vendor entry in `keys-index.json` (default `"anthropic"`). Based on mode, dispatch:
- **Auth header:** `x-api-key` (anthropic) vs `Authorization: Bearer` (chat/response)
- **Path construction:** append original request path (anthropic) vs append `/v1/chat/completions` (chat) vs append `/v1/responses` (response)
- **Request body:** model-only rewrite (anthropic) vs full Anthropic→Chat transform (chat) vs full Anthropic→Responses transform (response)
- **Response body:** model-only rewrite (anthropic) vs Chat→Anthropic transform (chat) vs Responses→Anthropic transform (response)
- **SSE streaming:** existing Anthropic SSE rewrite (anthropic) vs OpenAI SSE→Anthropic SSE transform (chat); response mode forces `stream: false` and returns JSON

Error responses pass through untransformed (non-2xx responses skip all mode dispatch; only 2xx responses are transformed). Retry logic (429/503) is unaffected — it operates on HTTP status codes, not body content. All transformation functions use defensive `.get()` chains and are wrapped in try/except with passthrough-on-failure fallback + trace events.

**Architecture overview:**
```
do_POST
  └─ forward_request
       └─ _forward_request_impl
            ├─ extract_model → resolve_tier → tier_config
            ├─ vendor = vendors[provider]
            ├─ mode = vendor.get("mode", "anthropic")        [NEW]
            ├─ validate mode ∈ {anthropic, chat, response}   [NEW]
            ├─ Dispatch auth header per mode                 [NEW]
            ├─ Dispatch path construction per mode           [NEW]
            ├─ Dispatch request body transform per mode      [NEW]
            ├─ HTTP request to upstream (retry loop, unchanged)
            └─ Response handling:
                 ├─ 2xx + SSE:     _stream_upstream_response(mode=...)  [mode dispatch]
                 ├─ 2xx + JSON:    buffer → dispatch transform per mode [NEW]
                 ├─ 2xx + other:   buffer → dispatch transform per mode [NEW]
                 └─ non-2xx:       buffer → passthrough (no transform)    [NEW]
```

**Alternatives considered:**
- **Separate transformation module:** Rejected — the transformation functions are small (20-50 lines each) and tightly coupled to the request/response flow. A separate file adds indirection without benefit at this scale.
- **Provider-specific plugin system:** Rejected — over-engineered. Three modes cover the known API surface; a plugin system would be speculative.
- **Path per mode from config:** Rejected — the user's approach of configuring the full URL in keys-index.json is simpler and more flexible.

**Out of scope:**
- Error response transformation (non-retryable errors pass through in upstream format — user sees the raw error; the proxy's retry logic on 429/503 is unaffected)
- Response mode SSE streaming (response mode forces `stream: false` and returns JSON; SSE can be added later)
- Response mode conversation history (response mode is single-turn — it extracts only the last user message as `input`; multi-turn history is dropped)
- count_tokens endpoint for chat/response modes (returns 400 — the OpenAI endpoints have no token-counting equivalent)
- Tool use transformation for chat mode (tool calls are mapped in response, but Anthropic→OpenAI tool definitions are not transformed — Claude Code tool use with chat-mode providers is not expected to work)
- `top_k` field mapping (no OpenAI equivalent)
- `thinking` field mapping (Anthropic-specific, no OpenAI equivalent)
- `stop_sequences` length limit (Anthropic allows unlimited stop sequences; OpenAI caps at 4 — pass-through may cause upstream 400)
- Messages content sanitization (Anthropic content blocks like `tool_use`/`tool_result`/`thinking` passed through verbatim may cause upstream 400)

## Repo Mode

Public

## Document Overrides

*None — every documented rule in CLAUDE.md and doc/* is in force.*

## Proposed Changes

1. **Step 1:** Read `mode` from vendor entry in `_forward_request_impl`, default to `"anthropic"` when absent. After extracting `api_key = vendor["key"]`, read `mode = vendor.get("mode", "anthropic")`. Validate that mode is one of `{"anthropic", "chat", "response"}` — return 500 with `"invalid_provider_mode"` error if not. Treat `None`, empty string, and missing keys as `"anthropic"`. Keep `mode` as a local variable in `_forward_request_impl` — do NOT thread it into the return tuple (the dispatch is internal per Step 9). Add mode validation at startup: in `load_keys_file`, validate that any present `mode` field is in the allowed set, and emit a stderr warning when a non-standard or absent mode is used (matching the existing plain-keys warning pattern). Log a trace event when a non-anthropic mode is dispatched for observability.
   → coder verify (auto): `mode = vendor.get("mode", "anthropic")` appears in `_forward_request_impl` after the `api_key` line; invalid mode returns 500 with `"invalid_provider_mode"` in the error JSON; `load_keys_file` validates mode enum; stderr warning emitted for absent/unknown mode; trace event logged for non-anthropic mode dispatch
      → tester verify: `test_mode_defaults_to_anthropic` — vendor without `mode` field is treated as `"anthropic"`; `test_mode_invalid_rejected` — vendor with `mode: "unknown"` returns 500; `test_mode_null_defaults_to_anthropic` — vendor with `mode: null` treated as `"anthropic"`

2. **Step 2:** Dispatch auth header based on mode. In the header-building section of `_forward_request_impl`, after the existing `fwd_headers["x-api-key"] = api_key` line:
   - If `mode == "anthropic"`: keep existing behavior (`x-api-key` header, drop `authorization`)
   - If `mode in ("chat", "response")`: inject `Authorization: Bearer <api_key>` instead of `x-api-key`, still drop the original `authorization` and `x-api-key` headers
   → coder verify (auto): `if mode == "anthropic":` branch sets `x-api-key`; `else:` branch sets `Authorization: Bearer`; original `authorization` and `x-api-key` headers are dropped in both branches
   → tester verify: `test_auth_header_anthropic_mode` — request forwarded with `x-api-key` header; `test_auth_header_chat_mode` — request forwarded with `Authorization: Bearer` header; `test_auth_header_response_mode` — request forwarded with `Authorization: Bearer` header

3. **Step 3:** Dispatch path construction based on mode. In the upstream-path construction section:
   - If `mode == "anthropic"`: `upstream_path = path_prefix + path if path_prefix else path` (existing behavior — append original request path, e.g. `/v1/messages`)
   - If `mode == "chat"`: strip a trailing `/v1` from `path_prefix` if present (to avoid double `/v1/v1/chat/completions` when the URL already ends in `/v1`), then `upstream_path = path_prefix + "/v1/chat/completions"`
   - If `mode == "response"`: same trailing-`/v1` stripping, then `upstream_path = path_prefix + "/v1/responses"`
   This way `url = "https://opencode.ai/zen/go"` + `"/v1/chat/completions"` → `/zen/go/v1/chat/completions`, and `url = "https://api.openai.com/v1"` + `"/v1/chat/completions"` → `/v1/chat/completions` (not `/v1/v1/chat/completions`).
   - **count_tokens handling:** For `chat` and `response` modes, if the incoming path is `/v1/messages/count_tokens`, return 400 with `{"error": "count_tokens not supported in chat/response mode"}` — the `/v1/chat/completions` and `/v1/responses` endpoints have no token-counting equivalent.
   → coder verify (auto): path construction guarded by `if mode == "anthropic":` / `elif mode == "chat":` / `elif mode == "response":`; chat appends `"/v1/chat/completions"`; response appends `"/v1/responses"`; trailing `/v1` stripped from path_prefix; count_tokens returns 400 for chat/response modes
   → tester verify: `test_path_anthropic_mode` — upstream path includes original request path; `test_path_chat_mode` — upstream path is `path_prefix + "/v1/chat/completions"`; `test_path_response_mode` — upstream path is `path_prefix + "/v1/responses"`; `test_path_double_v1_prevention` — URL ending in `/v1` doesn't produce `/v1/v1/`; `test_count_tokens_rejected_chat_mode` — count_tokens returns 400 in chat mode

4. **Step 4:** Add `_anthropic_to_chat(body_json)` function. Transform an Anthropic Messages request body into an OpenAI Chat Completions request body. Rules:
   - `model` → `model` (pass through, already rewritten)
   - `messages` → `messages` (pass through)
   - `system` (string) → prepend `{"role": "system", "content": system}` to messages array
   - `system` (list of content blocks) → concatenate `text`-type blocks with newline separator, prepend system message; drop non-text blocks
   - `max_tokens` → `max_tokens` (pass through if present)
   - `temperature` → `temperature` (pass through if present)
   - `stop_sequences` → `stop` (rename if present, value is list of strings)
   - `stream` → `stream` (pass through if present)
   - `top_p` → `top_p` (pass through if present)
   - Drop: `thinking`, `tools`, `tool_choice`, `metadata`, `top_k`
   Return the transformed dict.
   → coder verify (auto): `_anthropic_to_chat` defined in `server.py`; accepts one argument (dict); returns dict; system string becomes first message; system list concatenates text blocks; `stop_sequences` renamed to `stop`; `top_k`/`thinking`/`tools`/`tool_choice`/`metadata` absent from output
      → tester verify: `test_anthropic_to_chat_basic` — messages, model, max_tokens, temperature mapped correctly; `test_anthropic_to_chat_system_string` — system string prepended as system message; `test_anthropic_to_chat_system_list` — system content blocks concatenated; `test_anthropic_to_chat_dropped_fields` — thinking, tools, metadata, top_k absent; `test_anthropic_to_chat_stop_sequences` — renamed to stop

5. **Step 5:** Add `_chat_to_anthropic(chat_body, tier)` function. Transform an OpenAI Chat Completions JSON response into an Anthropic Messages JSON response. All field access MUST use `.get()` chains with defaults — never bare subscripts — to survive malformed upstream responses without crashing the worker thread. Rules:
   - `id` → `id` = `"msg_" + chat_body.get("id", str(uuid.uuid4()))`
   - `model` = `tier` (rewrite to tier name)
   - `type` = `"message"` (hardcoded)
   - `role` = `"assistant"` (hardcoded)
   - `choices` = `chat_body.get("choices", [])`; if empty or missing, return minimal valid response
   - `message` = `choices[0].get("message", {})` if choices non-empty
   - `content` = `message.get("content")`; if isinstance(content, str): `content = [{"type": "text", "text": content}]`; elif isinstance(content, list): map each `{"type": "text", ...}` part individually; if null/empty: `content = []`
   - `tool_calls` = `message.get("tool_calls")`; if present, add `tool_use` content blocks to `content` array (map `function.name` → `name`, `function.arguments` → `input` (try `json.loads`, fallback to `{}` on any parse error + trace event), `id` → `id`)
   - `finish_reason` = `choices[0].get("finish_reason")`; map to `stop_reason`: `"stop"` → `"end_turn"`, `"length"` → `"max_tokens"`, `"tool_calls"` → `"tool_use"`, `"content_filter"` → `null` (not a valid Anthropic stop_reason), anything else → `null`
   - `stop_sequence` = `null` (hardcoded)
   - `usage` = `chat_body.get("usage", {})`; `usage.input_tokens` = `usage.get("prompt_tokens", 0)`; `usage.output_tokens` = `usage.get("completion_tokens", 0)`
   - Wrap the entire function body in try/except (JSONDecodeError, KeyError, TypeError, IndexError, AttributeError): on failure, log a trace event (`transform_failure`) and return the original body unchanged (passthrough fallback, matching `_rewrite_json_response`'s pattern at server.py:1068-1071)
   → coder verify (auto): `_chat_to_anthropic` defined in `server.py`; accepts two arguments (dict, str); returns dict; all field access uses `.get()`; `content_filter` maps to `null`; usage uses `.get()` with zero defaults; tool_calls `json.loads` wrapped in try/except; outer try/except returns original body on failure + trace event
      → tester verify: `test_chat_to_anthropic_basic` — content, model, stop_reason, usage mapped correctly; `test_chat_to_anthropic_empty_choices` — returns minimal valid response; `test_chat_to_anthropic_tool_calls` — tool calls mapped to content blocks; `test_chat_to_anthropic_finish_reason_mapping` — all finish_reason values mapped correctly; `test_chat_to_anthropic_usage_absent` — handles missing usage gracefully; `test_chat_to_anthropic_content_array` — handles array content; `test_chat_to_anthropic_malformed_tool_args` — malformed JSON arguments don't crash

6. **Step 6:** Add `_anthropic_to_response(body_json)` function. Transform an Anthropic Messages request body into an OpenAI Responses request body. Rules:
   - `model` → `model` (pass through, already rewritten)
   - Force `"stream": false` — do NOT pass through the client's `stream` flag. Response-mode SSE is not yet implemented (see Out of scope), so the upstream must return JSON. Hardcode `"stream": false` in the output.
   - Extract `input` from the last user message: find the last message with `role: "user"`, concatenate all text content blocks from it. If `content` is a string, use it directly. If `content` is an array, join `text`-type blocks with newline. If no user message exists: return `input: ""` (empty string).
   - `system` (string or list) → `instructions` (string; if list, concatenate text blocks)
   - `max_tokens` → `max_output_tokens` (rename if present)
   - `temperature` → `temperature` (pass through if present)
   - `top_p` → `top_p` (pass through if present)
   - Drop: `messages`, `thinking`, `tools`, `tool_choice`, `metadata`, `stop_sequences`, `top_k`
   - **Note:** response mode is single-turn only — it extracts only the last user message as `input` and discards the full conversation history. This is a known limitation documented in Out of scope.
   → coder verify (auto): `_anthropic_to_response` defined in `server.py`; accepts one argument (dict); returns dict; `"stream": false` is hardcoded in output; `input` is string from last user message; `system` → `instructions`; `max_tokens` → `max_output_tokens`; `messages` absent from output; no-user-message → `input: ""`
      → tester verify: `test_anthropic_to_response_basic` — model, input, instructions, stream mapped correctly; `test_anthropic_to_response_system_list` — system list concatenated to instructions; `test_anthropic_to_response_multiple_user_messages` — last user message used for input; `test_anthropic_to_response_no_user_message` — returns `input: ""`; `test_anthropic_to_response_stream_forced_false` — stream is always false regardless of input

7. **Step 7:** Add `_response_to_anthropic(resp_body, tier)` function. Transform an OpenAI Responses JSON response into an Anthropic Messages JSON response. All field access MUST use `.get()` chains. Rules:
   - `id` → `id` (pass through — Responses API uses `resp_` prefix, which is fine)
   - `model` = `tier` (rewrite to tier name)
   - `type` = `"message"` (hardcoded)
   - `role` = `"assistant"` (hardcoded)
   - `output` = `resp_body.get("output", [])`; if empty or missing, return minimal valid response
   - For each output item of `type: "message"`, extract `content` blocks; map `output_text` → `{"type": "text", "text": ...}`. Drop non-text content blocks.
   - `status` = `resp_body.get("status")`; derive `stop_reason`: `"completed"` → `"end_turn"`, `"incomplete"` → `null`, anything else → `null`
   - `stop_sequence` = `null`
   - `usage` = `resp_body.get("usage", {})`; `usage.input_tokens` = `usage.get("input_tokens", 0)`; `usage.output_tokens` = `usage.get("output_tokens", 0)`
   - Wrap the entire function body in try/except (JSONDecodeError, KeyError, TypeError, IndexError, AttributeError): on failure, log a trace event (`transform_failure`) and return the original body unchanged (passthrough fallback)
   → coder verify (auto): `_response_to_anthropic` defined in `server.py`; accepts two arguments (dict, str); returns dict; all field access uses `.get()`; stop_reason derived from `status` field; outer try/except returns original body on failure + trace event
      → tester verify: `test_response_to_anthropic_basic` — content, model, usage mapped correctly; `test_response_to_anthropic_empty_output` — returns minimal valid response; `test_response_to_anthropic_multiple_output` — first message output used for content; `test_response_to_anthropic_status_completed` — stop_reason derived from status; `test_response_to_anthropic_usage_absent` — handles missing usage gracefully

8. **Step 8:** Add SSE transformation for chat mode. In `_stream_upstream_response`, when `mode == "chat"` and `is_sse` is true:
   - **Frame assembly:** All SSE events (first and subsequent) MUST be assembled by accumulating bytes until `\n\n` delimiter found, then processing the complete event. Never parse partial SSE frames. Malformed JSON in a data line → skip-and-log (trace event `chat_sse_malformed_json`), continue to next event.
   - **Buffer limit:** First event capped at 64 KB (same as existing SSE path). If cap exceeded before `\n\n`: emit synthetic `message_start` with `id = "msg_" + str(uuid.uuid4())` and `model = tier`, emit `content_block_start`, forward the raw buffer as-is (matching the `rewrite_skipped` pattern for anthropic mode at server.py:1171-1179).
   - **First event:** Parse the first `data:` line to extract `id` and `model` from the first chat completion chunk. Also scan for `choices[0].delta.content` — if the first chunk carries actual text content (some providers like DeepSeek), emit it as a `content_block_delta` after the synthetic events.
   - **Synthetic events:** Emit `message_start` (with `id = "msg_" + chat_id` if available, else `"msg_" + str(uuid.uuid4())`), then `content_block_start`. All synthetic event payloads MUST be built as dicts and serialized via `json.dumps` — never raw string interpolation of provider-controlled fields (SSE injection prevention, matching `_rewrite_sse_first_event`'s safe pattern at server.py:1047-1053).
   - **SSE wire format — `event:` line REQUIRED:** `_sse_event()` MUST emit `event: <type>\ndata: <json>\n\n` — NOT `data:`-only. The Anthropic Python SDK and TypeScript SDK dispatch streaming events solely on the SSE `event:` field against a hardcoded whitelist (`message_start`, `message_delta`, `message_stop`, `content_block_*`). When no `event:` line is present the decoder's event is `None`, which matches no whitelist branch, so every event is silently dropped. Claude Code uses the TS SDK → `stream.finalMessage()` throws "request ended without sending any chunks". Extract the event type from `payload["type"]` and emit it as the `event:` line. <!-- UPDATED: review-sse-missing-event-line -->
   - **Tool call delta tracking:** `handle_frame()` MUST track whether `delta.tool_calls` was seen in any frame. The SSE path does not transform `delta.tool_calls` into `tool_use` content blocks (tool-use SSE transformation is out of scope), but the terminal maps `finish_reason "tool_calls"` → `stop_reason "tool_use"`. When `delta.tool_calls` was seen but not transformed, degrade the terminal `stop_reason` from `"tool_use"` to `null` to prevent a mid-session tool hang (Claude Code sees `stop_reason="tool_use"` with zero `tool_use` content blocks). Track with a `tool_calls_seen` boolean, set `True` when `delta.get("tool_calls") is not None`; in the terminal path, if `tool_calls_seen and sr == "tool_use"` → `sr = None`. <!-- UPDATED: review-sse-tool-calls-stop-reason-mismatch -->
   - **Subsequent events:** For each complete SSE event: parse `data: {...}`, guard `choices` access (`choices = chunk.get("choices", [])`; if empty, check for `usage` and accumulate it for the terminal `message_delta`). Extract `choices[0].get("delta", {}).get("content")` — if present, emit `content_block_delta`. Never index `choices[0]` unguarded.
   - **Terminal events:** When `choices[0].get("finish_reason")` is non-null OR end-of-stream (EOF/read error without finish_reason): emit `content_block_stop`, `message_delta` (with `stop_reason` mapped per Step 5 + accumulated `usage` if present), `message_stop`. This ensures the Anthropic SSE stream always terminates even if the upstream closes without sending a finish_reason chunk.
   - Skip `[DONE]` sentinel.
   - First-byte latency is measured from the first upstream chunk received.
   → coder verify (auto): chat-mode SSE path exists in `_stream_upstream_response`; all SSE events assembled via `\n\n` delimiter; synthetic events use `json.dumps`; `choices[0]` access guarded with `.get()`; empty-choices chunk handled without crash; terminal events synthesized on EOF; `[DONE]` skipped; first-event content delta emitted if present; cap-exceed fallback uses uuid; `_sse_event()` emits `event:` line with type from `payload["type"]`; `tool_calls_seen` flag tracked in `handle_frame()`; terminal `stop_reason` degraded to `null` when `tool_calls_seen and sr == "tool_use"`
      → tester verify: `test_chat_sse_basic_streaming` — simulated OpenAI SSE chunks produce valid Anthropic SSE events; `test_chat_sse_finish_reason_mapping` — finish_reason maps correctly in message_delta; `test_chat_sse_no_content_delta` — chunks without content delta don't produce content_block_delta; `test_chat_sse_empty_choices_usage_chunk` — empty-choices usage chunk doesn't crash; `test_chat_sse_eof_without_finish_reason` — terminal events synthesized on EOF; `test_chat_sse_first_event_has_content` — first-chunk content delta emitted; `test_chat_sse_event_line_present` — every data-bearing SSE frame has an `event:` line matching the JSON `type` field; `test_chat_sse_tool_calls_stop_reason_null` — tool_calls finish_reason maps to null stop_reason when tool_calls deltas were seen but not transformed

9. **Step 9:** Wire transformations into `_forward_request_impl`. In the request/response handling sections:
   - **Request body rewriting:** Build `rewritten_body` once BEFORE the retry loop (alongside `fwd_headers`), sourcing mode from the vendor snapshot. After the existing `body_json["model"] = actual_model` line: if `mode == "chat"`: `rewritten_body = json.dumps(_anthropic_to_chat(body_json)).encode("utf-8")`; elif `mode == "response"`: `rewritten_body = json.dumps(_anthropic_to_response(body_json)).encode("utf-8")`; else (anthropic): keep existing model-only rewrite. Never re-transform inside the retry loop — the pre-built `rewritten_body` is reused on every attempt.
   - **JSON response rewriting (2xx buffered path only):** After buffering the JSON response body, replace the existing `resp_body = _rewrite_json_response(...)` line with a dispatch: if `mode == "chat"`: `resp_body = _transform_and_guard(resp_body, tier, _chat_to_anthropic, request_id)`; elif `mode == "response"`: `resp_body = _transform_and_guard(resp_body, tier, _response_to_anthropic, request_id)`; else: `resp_body = _rewrite_json_response(resp_body, tier, request_id)`. Define `_transform_and_guard(raw_body, tier, transform_fn, request_id)` as a helper that accepts raw bytes: first try `parsed = json.loads(raw_body)` INSIDE the try/except; then try `json.dumps(transform_fn(parsed, tier)).encode("utf-8")`; on any exception (JSONDecodeError, KeyError, TypeError, IndexError, AttributeError), log a trace event (`transform_failure`) and return the original `raw_body` unchanged (passthrough-on-failure, matching `_rewrite_json_response`'s pattern at server.py:1068-1071 where `json.loads` is inside the guard). Called as `_transform_and_guard(resp_body, tier, _chat_to_anthropic, request_id)` — the raw bytes, not pre-parsed JSON.
   - **Non-2xx path:** Do NOT transform. Pass the upstream body through byte-for-byte without any mode dispatch. The existing `_rewrite_json_response` for anthropic mode is kept; for chat/response modes, skip all transformation on non-2xx. This matches the Summary: "Error responses pass through untransformed."
   - **SSE streaming (2xx path):** Pass `mode` to `_stream_upstream_response`; the existing SSE path handles `anthropic` mode; the new chat SSE path (Step 8) handles `chat` mode; `response` mode: Step 6 forces `stream: false` so the upstream returns JSON, not SSE — the 2xx JSON buffered path handles it.
   - **Non-SSE/non-JSON 2xx path:** For `chat` and `response` modes, if the upstream returns a non-SSE, non-JSON content type, buffer and transform as JSON via `_transform_and_guard` (since OpenAI APIs always return JSON or SSE).
   - **Content-Length:** After transformation, recompute `Content-Length` on the rewritten body (already done by existing code at server.py:823, 861 — ensure the new transform paths also update it).
   → coder verify (auto): request body built once before retry loop; JSON response transform only on 2xx; non-2xx passes through untransformed; `_transform_and_guard` helper defined; response mode SSE prevented by `stream: false`; Content-Length recomputed after transform
      → tester verify: `test_chat_mode_e2e_json` — end-to-end chat mode request/response through proxy; `test_response_mode_e2e_json` — end-to-end response mode request/response through proxy; `test_anthropic_mode_unchanged` — existing behavior preserved; `test_chat_mode_non_2xx_passthrough` — chat mode error body passes through untransformed; `test_transform_failure_passthrough` — malformed JSON response body passes through with trace event; `test_retry_does_not_double_transform` — 429 retry sends single-transformed body

10. **Step 10:** Update admin page to display mode per provider. Two changes:
    - **Server-side (`server.py`):** Add `GET /admin/api/providers-detail` endpoint in `do_GET`. Returns `{"providers": {"name": {"mode": "anthropic|chat|response"}, ...}}` — mode only, no keys. Validate mode against `{anthropic, chat, response}` before returning (default `"anthropic"` for absent/unknown). Localhost-only, no CSRF needed for GET. The `_vendors` table is read-only after init, so no drain-and-swap needed for this read-only endpoint.
    - **Client-side (`admin.html`):** Fetch from `/admin/api/providers-detail` alongside the existing config/providers fetches. Append the mode to each provider name in the dropdown (e.g., `"test-provider (chat)"`) using `opt.textContent` (never `innerHTML` — XSS prevention). The mode label is read-only.
    → coder verify (auto): `GET /admin/api/providers-detail` handler exists in `do_GET`; returns `{"providers": {...}}` with mode per provider; mode validated against allowed set; mode label appended to provider dropdown options via `textContent`; endpoint is localhost-only
    → tester verify: `test_admin_providers_detail` — endpoint returns mode per provider without keys; `test_admin_providers_detail_no_mode` — providers without mode return `"anthropic"`; `test_admin_providers_detail_forbidden` — non-localhost rejected; `test_admin_providers_detail_invalid_mode_normalized` — unknown mode normalized to `"anthropic"`

## Guidance for Planner

Documentation tasks to execute after coder completes:

- **Doc files to update:** `CLAUDE.md`, `README.md`
- **When:** After coder finishes all steps
- **What to sync:**
  - `CLAUDE.md`: Add `mode` field to the keys-index.json description in Architecture; add a "Mode dispatch" section describing the three modes, auth headers, path behavior, and transformation rules; add mode to the Gotchas section (default `"anthropic"`, error passthrough caveat, response-mode single-turn limitation, count_tokens rejection); revise the per-request numbered flow: step 4 must qualify that `x-api-key` is for anthropic mode while `Authorization: Bearer` is for chat/response modes; step 6 must note that model-name rewrite applies to anthropic mode only, while chat mode uses the OpenAI-SSE-to-Anthropic-SSE transform and chat/response JSON paths use full body transforms; add `GET /admin/api/providers-detail` to the Admin API endpoint enumeration
  - `README.md`: Add a "Provider Modes" section under Configuration documenting the three modes (`anthropic`, `chat`, `response`), how to configure them in `keys-index.json`, and the URL configuration pattern for each mode (note: chat/response modes use the URL as the base path and the proxy appends the endpoint path)

## History

| Date | Event | Conclusion | Dismissed |
|------|-------|------------|-----------|
| 2026-08-27 | Initial plan | Plan created from deferred issue `support-three-endpoint-modes` | — |
| 2026-08-27 | Mega-audit (pre-implementation) | 8 High, 30 Medium, 14 Low findings. Fixed: response mode forces `stream:false`, non-2xx passthrough, defensive `.get()` chains, SSE frame assembly + terminal-on-EOF, count_tokens short-circuit, trailing-`/v1` stripping, startup mode validation, remove tuple threading, `_transform_and_guard` helper, admin server-side endpoint, SSE injection safety. | See [mega-audit report](./tmp/reports/2026-08-27-support-three-endpoint-modes-mega-audit-2026-08-27.json) |
| 2026-08-27 | Mega-audit iteration 2 (pre-implementation) | 4 High, 31 Medium, 24 Low. Fixed: `_transform_and_guard` accepts raw bytes (json.loads inside guard), architecture diagram non-2xx line corrected to passthrough. Dismissed: reality-checker "no vendor has mode" — user confirmed mode field is already in live keys-index.json; existing loaders accept extra fields. | [reality-checker-mode-field](.) — false positive, `mode` already exists in live keys; [cap-exceed-raw-openai-bytes](.) — Medium, acknowledged, chat-mode SSE edge case under 64KB cap is rare; [sse-tool-calls-delta](.) — Medium, tool use in SSE is Out of scope; [synthetic-message-start-payload](.) — Medium, acknowledged, coder should fill full payload per Anthropic SSE spec referencing existing `message_start` format at server.py:1043-1053 |
| 2026-08-27 | Spec revision (/update-plan) | Downgraded 7 (scripted) checks to (auto) — verification scripts did not exist and planner cannot write to `./tmp/verification/`. All (auto) checks already have detailed inline criteria. | — |
| 2026-08-27 | Spec revision (/update-plan) | Coder and tester reports back. Fixed stale `_transform_and_guard(json.loads(...))` call site in Step 9 prose. Coder implemented 3 defensive behaviors beyond plan spec (CRLF-normalized SSE frame assembly, full message_start payload per Anthropic SSE contract, response_sse_unexpected fallback for response-mode upstream ignoring stream:false) — acknowledged as implementation hardening; no plan changes needed. | — |
| 2026-08-27 | Review (Phase 6) | 2 Critical, 6 Warning, 4 Suggestion. Critical: SSE events missing `event:` line (SDK drops all events), tool_calls SSE stop_reason mismatch. Filed as Open issues. Plan not ready to commit. | [review-report](./tmp/reports/2026-08-27-support-three-endpoint-modes-review-2026-08-27.json) |
| 2026-08-27 | Spec revision (/update-plan) | Review gate complete — 2 Critical findings. Step 8 updated: `_sse_event()` MUST emit `event:` line (Anthropic SDK dispatches on SSE `event:` field, not JSON `type`); `handle_frame()` MUST track `delta.tool_calls` and degrade terminal `stop_reason` from `tool_use` to `null` when tool_calls were seen but not transformed. Added 2 new tester-verify checks: `test_chat_sse_event_line_present`, `test_chat_sse_tool_calls_stop_reason_null`. Both issues status: Fix Planned. | — |
| 2026-08-27 | Spec revision (/update-plan) | Coder and tester report back after review fixes. Both Critical issues resolved: `_sse_event()` now emits `event: <type>\ndata: <json>\n\n` (verified by `test_chat_sse_event_line_present`); `handle_frame()` tracks `tool_calls_seen` and degrades stop_reason (verified by `test_chat_sse_tool_calls_stop_reason_null`). Tester: 121/121 pass (53 new mode-dispatch tests + 68 pre-existing). No open issues remain. Implementation complete. | — |
| 2026-08-27 | Review round 2 (Phase 6) | 0 Critical, 4 Warning, 4 Suggestion. Both Critical fixes confirmed correct. 2 prior Warnings disproven (JSON content-type claim, first-message-scan false positive). 4 prior Warnings remain as documented residuals. No new issues introduced by fixes. Independent full-suite re-run: 121/121 pass. Ready to commit. | [review-r2 report](./tmp/reports/2026-08-27-support-three-endpoint-modes-review-2026-08-27-r2.json) |

## Plan Metadata

```json
{
  "plan_id": "2026-08-27-support-three-endpoint-modes",
  "steps": [
    "Step 1: Read mode from vendor entry",
    "Step 2: Dispatch auth header based on mode",
    "Step 3: Dispatch path construction based on mode",
    "Step 4: Add _anthropic_to_chat() request transformation",
    "Step 5: Add _chat_to_anthropic() response transformation",
    "Step 6: Add _anthropic_to_response() request transformation",
    "Step 7: Add _response_to_anthropic() response transformation",
    "Step 8: Add SSE transformation for chat mode",
    "Step 9: Wire transformations into _forward_request_impl",
    "Step 10: Update admin page to display mode per provider"
  ],
  "coder_files": [
    "src/claude_retry_proxy/server.py",
    "src/claude_retry_proxy/admin.html"
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
  "document_overrides": []
}
```

## Audit Accumulation

| Counter | Value | Last Updated |
|---------|-------|--------------|
| issues_resolved_since_audit | 2 | 2026-08-27 |
| steps_changed_since_audit | 1 | 2026-08-27 |
| files_changed_since_audit | 0 | 2026-08-27 |

## Final Results

**Status:** COMPLETED — 2026-08-27

**Implementation:** All 10 plan steps implemented. Two Critical review findings fixed after initial implementation.

| What | Detail |
|------|--------|
| Files changed | `src/claude_retry_proxy/server.py` (+~750 lines), `src/claude_retry_proxy/admin.html` (+21 lines), `tests/test_claude_proxy.py` (+~1950 lines) |
| Test results | 121/121 passed (53 new mode-dispatch tests, 68 pre-existing unaffected) |
| Issues resolved | 4 (support-three-endpoint-modes, missing-verification-scripts, review-sse-missing-event-line, review-sse-tool-calls-stop-reason-mismatch) |
| Open issues | 0 |

**What was implemented:**

- **Mode dispatch:** `mode` field read from vendor entry in `keys-index.json` (default `"anthropic"`). Three modes: `anthropic`, `chat`, `response`. Invalid mode returns 500. Startup validation with stderr warnings.
- **Auth header dispatch:** `x-api-key` for anthropic mode, `Authorization: Bearer` for chat/response modes.
- **Path construction:** Original path for anthropic, `/v1/chat/completions` for chat, `/v1/responses` for response. Trailing `/v1` stripped from URL prefix. `count_tokens` returns 400 for chat/response modes.
- **Request transforms:** `_anthropic_to_chat()` (system→messages, stop_sequences→stop, drop thinking/tools/metadata/top_k), `_anthropic_to_response()` (input from last user message, system→instructions, stream forced false, max_tokens→max_output_tokens).
- **Response transforms:** `_chat_to_anthropic()` (id→msg_ prefix, choices→content, finish_reason→stop_reason, usage remapping, tool_calls→tool_use blocks), `_response_to_anthropic()` (output→content, status→stop_reason). Both wrapped in try/except with passthrough-on-failure + trace events.
- **SSE streaming:** `_stream_chat_sse_to_anthropic()` — frame assembly on `\n\n`, synthetic message_start/content_block_start/content_block_stop/message_delta/message_stop, content_block_delta for text content. **Critical fix:** `_sse_event()` emits `event: <type>\ndata: <json>\n\n` (Anthropic SDK dispatches on SSE `event:` field). **Critical fix:** `tool_calls_seen` tracking degrades terminal stop_reason from `tool_use` to `null` when tool_calls were seen but not transformed.
- **Wiring:** `_transform_and_guard()` helper (raw bytes, json.loads inside guard). Request body built once before retry loop. Response transform only on 2xx. Non-2xx passes through untransformed.
- **Admin:** `GET /admin/api/providers-detail` returns mode per provider. Admin page shows mode label in provider dropdown.

**Out of scope (documented):**
- Error response transformation (non-2xx passthrough)
- Response mode SSE streaming (forces `stream: false`)
- Response mode conversation history (single-turn, last user message only)
- Tool use SSE delta transformation (tool_calls seen but not transformed; stop_reason degraded to null)
- count_tokens for chat/response (returns 400)

**Review history:**
- 2 mega-audit iterations (pre-implementation): 8 High → 4 High → 0 High after fixes
- 1 review (post-implementation): 2 Critical, 6 Warning, 4 Suggestion
- Both Critical findings fixed and verified: `event:` line on SSE events, tool_calls stop_reason degradation
- 121/121 tests pass, 0 open issues

## Documentation