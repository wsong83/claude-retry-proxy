# Plan: Fix Chat-Mode Request Transform — Anthropic Messages → OpenAI Chat Completions
**Project:** D:\proj\claude-retry-proxy
**Plan ID:** 2026-08-29-fix-chat-mode-request-transform
**Created:** 2026-08-29

## Issue Log

| Issue | Status | Found | Resolved | Resolved By |
|-------|--------|-------|----------|-------------|
| [step6-test-updates-misassigned](./tmp/reports/2026-08-29-fix-chat-mode-request-transform-step6-test-updates-misassigned.json) | Resolved | 2026-08-29 | 2026-08-29 | tester |
| [review-non-dict-tool-use-input](./tmp/reports/2026-08-29-fix-chat-mode-request-transform-review-2026-08-29.json#L29) | Resolved | 2026-08-29 | 2026-08-29 | tester |
| [review-nan-placeholder-discarded](./tmp/reports/2026-08-29-fix-chat-mode-request-transform-review-2026-08-29.json#L36) | Resolved | 2026-08-29 | 2026-08-29 | tester |
| [review-empty-user-message](./tmp/reports/2026-08-29-fix-chat-mode-request-transform-review-2026-08-29.json#L44) | Resolved | 2026-08-29 | 2026-08-29 | tester |
| [review-cache-control-double-fire](./tmp/reports/2026-08-29-fix-chat-mode-request-transform-review-2026-08-29.json#L52) | Resolved | 2026-08-29 | 2026-08-29 | tester |
| [review-dropped-missing-location](./tmp/reports/2026-08-29-fix-chat-mode-request-transform-review-2026-08-29.json#L59) | Resolved | 2026-08-29 | 2026-08-29 | tester |
| [review-tool-result-unknown-count](./tmp/reports/2026-08-29-fix-chat-mode-request-transform-review-2026-08-29.json#L67) | Resolved | 2026-08-29 | 2026-08-29 | tester |
| [review-non-dict-blocks-silent](./tmp/reports/2026-08-29-fix-chat-mode-request-transform-review-2026-08-29.json#L75) | Resolved | 2026-08-29 | 2026-08-29 | tester |
| [review-unguarded-tool-use-id-name](./tmp/reports/2026-08-29-fix-chat-mode-request-transform-review-2026-08-29.json#L83) | Resolved | 2026-08-29 | 2026-08-29 | tester |
| [review-missing-regression-tests](./tmp/reports/2026-08-29-fix-chat-mode-request-transform-review-2026-08-29.json#L91) | Resolved | 2026-08-29 | 2026-08-29 | tester |
| [block-level-cache-control](./tmp/reports/2026-08-29-fix-chat-mode-request-transform-block-level-cache-control.json) | Resolved | 2026-08-29 | 2026-08-29 | tester |
| [nan-tool-use-placeholder](./tmp/reports/2026-08-29-fix-chat-mode-request-transform-nan-tool-use-placeholder.json) | Resolved | 2026-08-29 | 2026-08-29 | tester |
| [user-text-blocks-array](./tmp/reports/2026-08-29-fix-chat-mode-request-transform-user-text-blocks-array.json) | Resolved | 2026-08-29 | 2026-08-29 | tester |
| [streaming-tool-call-deltas](./tmp/reports/defer-issue-streaming-tool-call-deltas.json) | Open | 2026-08-29 | — | — |
| [image-content-blocks-chat-mode](./tmp/reports/defer-issue-image-content-blocks-chat-mode.json) | Open | 2026-08-29 | — | — |

## Guidance for Coder

**Files to modify:**
- `src/claude_retry_proxy/server.py`

### Step-by-step with verification

1. **Step 1:** Add `_transform_anthropic_messages_to_chat(messages, request_id=None, mode=None, provider=None, tier=None, cache_stripped_out=None)` — converts an Anthropic `messages` array to OpenAI Chat Completions `messages` array. Always returns a new list (never mutates the input).
   - **Input guards:** `isinstance(messages, list)` guard; return `[]` if not a list. Each message entry guarded with `isinstance(msg, dict)`; non-dict entries skipped.
   - **Content block handling (assistant messages):**
     - `thinking` blocks → **stripped** with `content_block_dropped` trace event (metadata only — never body content)
     - `redacted_thinking` blocks → **stripped** with `content_block_dropped` trace event
     - `text` blocks → concatenated into `content` string (newline-separated)
     - `tool_use` blocks → converted to `tool_calls[]` entries: `{id, type:"function", function:{name, arguments}}`. `input` (object) → `arguments` (JSON string) via `json.dumps(input, allow_nan=False)`. **Error path:** if `json.dumps` raises `ValueError` (NaN/Infinity) or `TypeError` (non-serializable type): (1) emit a text placeholder `[Tool call failed: arguments for '<name>' (call <id>) could not be serialized as JSON]` — matching the existing degradation pattern in `_chat_to_anthropic` for malformed tool-call arguments; (2) log a `tool_args_parse_failure` trace event with `request_id`, `mode`, `provider`, `tier`, `tool_name`, `tool_id`, `error`; (3) do NOT add a `tool_calls` entry for this block; (4) do NOT increment `dropped["unknown"]` — this is a degradation to a visible text placeholder, not a silent drop. If text blocks are also present, `content` is set to `null` (OpenAI requires `content: null` when `tool_calls` is present; non-null content alongside tool_calls is rejected by many providers). If no text blocks, `content` is `null`.
     - Blocks with unknown types → **stripped** with `content_block_dropped` trace event
   - **Content block handling (user messages):**
     - `text` blocks → joined to a `content` string with newlines. (OpenAI Chat supports both string and array content on user messages; the string form is more widely compatible with third-party providers, and joining with newlines preserves all text information.)
     - `tool_result` blocks → converted to separate `role: "tool"` messages with `tool_call_id` = `block.tool_use_id` and `content` (string). If `tool_result.content` is a list, join text blocks with newlines. Multiple `tool_result` blocks in one user message become multiple consecutive `role: "tool"` messages (consecutive tool messages are valid OpenAI — each carries its own `tool_call_id`). Pairing is by `tool_use_id`: each emitted `role: "tool"` message's `tool_call_id` must match a `tool_use.id` from a preceding assistant message. If no match exists, drop with `content_block_dropped`.
     - If a user message has both `tool_result` and `text` blocks, emit the `tool_result` blocks as `role: "tool"` messages first, then emit the remaining text as a `role: "user"` message.
     - `image` blocks → **stripped** with `content_block_dropped` trace event (deferred: `defer-issue-image-content-blocks-chat-mode`)
   - **String content pass-through:** If `content` is already a string, pass through unchanged (wrapped in a new message dict — never mutate the input).
   - **cache_control** on any block → **stripped**. Log a `cache_control_stripped` trace event (separate from `content_block_dropped` — cache_control is a field, not a block type). **IMPORTANT: check `block.get("cache_control")` in each block loop** (both assistant and user), NOT `"cache_control" in msg` on the message dict. Anthropic places `cache_control` on individual content blocks (e.g. `{"type":"text","text":"...","cache_control":{"type":"ephemeral"}}`), not on the message envelope. When present, set `cache_stripped = True` and strip the field from the output block. The `cache_control_stripped` trace event is emitted once per request (coalesced), not per block.
   - **`content: null` on user messages:** If user content is `null`/empty after stripping, keep the message with `content: ""` (OpenAI requires non-null content for user messages).
   → coder verify (auto): `_transform_anthropic_messages_to_chat` defined in `server.py`, signature `(messages, request_id=None, mode=None, provider=None, tier=None, cache_stripped_out=None)`, returns `list`
   → coder verify (scripted): `./tmp/verification/2026-08-29-fix-chat-mode-request-transform-step1.py`

2. **Step 2:** Add `_transform_anthropic_tools_to_chat(tools, request_id=None, mode=None, provider=None, tier=None, cache_stripped_out=None)` — converts Anthropic tool definitions to OpenAI Chat format.
   - **Input guards:** `isinstance(tools, list)` guard; return `[]` if not a list. `tools: null` treated as absent.
   - `input_schema` → `parameters`
   - `name` → `function.name`
   - `description` → `function.description`
   - Wrap in `{"type": "function", "function": {...}}`
   - **Skip malformed entries:** entries missing `name` or `input_schema` → skip with `content_block_dropped` trace event. Non-dict entries → skip with trace event.
   - `cache_control` on tool definitions → **stripped** with `cache_control_stripped` trace event
   → coder verify (auto): `_transform_anthropic_tools_to_chat` defined in `server.py`, signature `(tools, request_id=None, mode=None, provider=None, tier=None, cache_stripped_out=None)`, returns `list`
   → coder verify (scripted): `./tmp/verification/2026-08-29-fix-chat-mode-request-transform-step2.py`

3. **Step 3:** Add `_transform_anthropic_tool_choice_to_chat(tool_choice)` — converts Anthropic tool_choice to OpenAI format.
   - `{type: "none"}` → `"none"`
   - `{type: "auto"}` → `"auto"`
   - `{type: "any"}` → `"required"`
   - `{type: "tool", name: "x"}` (name present) → `{"type": "function", "function": {"name": "x"}}`
   - `{type: "tool"}` with missing/`None` name → omitted (return `None`)
   - `None`/absent → `None`
   - Malformed (non-dict, unknown type, empty dict) → `None` (omitted, defensive)
   - **Only emit tool_choice when tools array is non-empty:** the caller (Step 4) gates emission on `tools` being present and non-empty.
   → coder verify (auto): `_transform_anthropic_tool_choice_to_chat` defined in `server.py`, accepts `(tool_choice: dict | None)` and returns `str | dict | None`
   → coder verify (scripted): `./tmp/verification/2026-08-29-fix-chat-mode-request-transform-step3.py`

4. **Step 4:** Rewire `_anthropic_to_chat(body_json, request_id=None, mode=None, provider=None, tier=None)` to use the three new transforms. **Do not mutate `body_json`** — build `out` without side effects.
   - Replace `out["messages"] = body_json["messages"]` with `out["messages"] = _transform_anthropic_messages_to_chat(body_json.get("messages", []), request_id=request_id, mode=mode, provider=provider, tier=tier)`
   - Add `tools` transform: `if "tools" in body_json and isinstance(body_json.get("tools"), list): out["tools"] = _transform_anthropic_tools_to_chat(body_json["tools"], request_id=request_id, mode=mode, provider=provider, tier=tier)`
   - Add `tool_choice` transform (only when tools present and non-empty): `tc = _transform_anthropic_tool_choice_to_chat(body_json.get("tool_choice")); if tc is not None and "tools" in out: out["tool_choice"] = tc`
   - **Transformed fields:** `tools`, `tool_choice`, `messages` (now actively transformed, not dropped)
   - **Still dropped:** `top_k`, `metadata`, `thinking` (request-level config — Anthropic-specific). The `thinking` request-level config is stripped by omission (not included in `out`); do NOT `del body_json["thinking"]` (would mutate caller's dict).
   - **Preserve existing behavior:** system string/list handling, field passthrough (max_tokens, temperature, stream, top_p, stop_sequences→stop)
   - Update the call site at `_forward_request_impl` line 750 to pass `request_id=request_id, mode=mode, provider=provider_name, tier=tier` to `_anthropic_to_chat()`.
   → coder verify (auto): `_anthropic_to_chat` calls `_transform_anthropic_messages_to_chat`, `_transform_anthropic_tools_to_chat`, `_transform_anthropic_tool_choice_to_chat`; `out["messages"]` is not `body_json["messages"]`; `body_json` is not mutated (verify with `id(body_json["messages"]) != id(out["messages"])` or equivalent)
   → coder verify (scripted): `./tmp/verification/2026-08-29-fix-chat-mode-request-transform-step4.py`

5. **Step 5:** Add trace event logging for dropped content blocks and stripped fields in the request transform functions (Steps 1, 2). Two distinct event types:
   - **`content_block_dropped`** — when an entire content block is dropped (thinking, redacted_thinking, image, unknown block types). Event shape: `{"timestamp": ..., "event": "content_block_dropped", "request_id": ..., "block_type": "thinking|redacted_thinking|image|unknown", "location": "assistant_message|user_message|tool_definition", "mode": "chat", "provider": ..., "tier": ...}`. Per-request: coalesce into a single event with `dropped_counts: {thinking: N, redacted_thinking: N, image: N, unknown: N}` to bound log amplification.
   - **`cache_control_stripped`** — when `cache_control` is removed from a block that is otherwise kept. Event shape: `{"timestamp": ..., "event": "cache_control_stripped", "request_id": ..., "location": "message_block|tool_definition", "mode": "chat", "provider": ..., "tier": ...}`. Logged once per request (boolean), not per block.
   - The `request_id`, `mode`, `provider`, `tier` are threaded through `_anthropic_to_chat` → all three transform functions from `_forward_request_impl` (Step 4 wires the call site).
   → coder verify (auto): `content_block_dropped` and `cache_control_stripped` appear as valid event strings in `log_trace` call sites within the transform functions
   → coder verify (auto): `content_block_dropped` uses coalesced `dropped_counts` map, not per-block events
   → tester verify: `test_anthropic_to_chat_content_block_dropped_trace` — verify trace event logged when thinking blocks are encountered in chat mode
   → tester verify: `test_anthropic_to_chat_cache_control_stripped_trace` — verify trace event logged when cache_control is stripped from blocks

6. **Step 6 (reviewer fixes):** Address 9 reviewer findings (3 Warnings + 6 Suggestions) from the Phase 6 code-quality review. All changes in `_transform_anthropic_messages_to_chat()`, `_transform_anthropic_tools_to_chat()`, and `_anthropic_to_chat()`.

   **6a. Validate tool_use input is a dict** (Warning 1, line 1327):
   Currently `input_val = block.get("input")` passes any value to `json.dumps`. A string `"hello"` → `"\"hello\""` (valid JSON, not a JSON object). OpenAI requires `arguments` to be a JSON object string.
   Fix — add `isinstance(input_val, dict)` check BEFORE `json.dumps`:
   ```python
   input_val = block.get("input")
   if not isinstance(input_val, dict):
       # Degrade: same path as NaN below
       text_parts.append("[Tool call failed: arguments for '{}' (call {}) "
                         "could not be serialized as JSON]".format(...))
       log_trace({... "event": "tool_args_parse_failure" ...})
       continue
   try:
       arguments = json.dumps(input_val, allow_nan=False)
   except (ValueError, TypeError) as exc:
       ...  # existing NaN path
   ```
   The `isinstance` check must come BEFORE the try/except — `json.dumps("hello")` does NOT raise ValueError, it produces `"\"hello\""` which is a valid JSON string (not object).

   **6b. Preserve text when valid tool_use coexists** (Warning 2, line 1362-1369):
   Currently when `tool_calls` is non-empty, `content` is forced to `None` and ALL `text_parts` (including failure placeholders) are silently discarded. The plan's "visible placeholder" contract is violated.
   Fix — when `tool_calls` is non-empty AND `text_parts` is non-empty, emit `text_parts` as a SEPARATE `role: "assistant"` message BEFORE the tool_calls message:
   ```python
   # After the block loop, replace the current if/else:
   if tool_calls and text_parts:
       # Emit text (including placeholders) as separate message first
       out.append({"role": "assistant",
                   "content": "\n".join(t for t in text_parts if isinstance(t, str))})
   if tool_calls:
       out.append({"role": "assistant", "content": None, "tool_calls": tool_calls})
   elif text_parts:
       out.append({"role": "assistant",
                   "content": "\n".join(t for t in text_parts if isinstance(t, str))})
   else:
       out.append({"role": "assistant", "content": ""})
   ```
   This is a net improvement: it ALSO preserves regular text (e.g. "Let me look that up") that was previously silently dropped by `content: null`. OpenAI accepts consecutive assistant messages. The `content: null` requirement is maintained on the tool_calls message itself.

   **6c. Drop empty user messages** (Warning 3, line 1397-1398):
   Currently `elif not tool_messages: out.append({"role": role, "content": ""})` emits an empty user message when all blocks are dropped. OpenAI rejects `content: ""` ("must be a non-empty string").
   Fix — simply remove the `elif not tool_messages:` branch. When all blocks are dropped (no tool_messages, no text_parts), the user message is silently dropped from the output. The earlier `content is None or content == []` → `content: ""` fallback (line 1304-1306) is preserved — that handles the literal null/empty case which is the plan's original intent.
   ```python
   out.extend(tool_messages)
   if text_parts:
       text = "\n".join(t for t in text_parts if isinstance(t, str))
       out.append({"role": role, "content": text})
   # REMOVED: elif not tool_messages: out.append(...)
   ```

   **6d. Coalesce `cache_control_stripped` across transform functions** (Suggestion 4, lines 1401-1410, 1471-1477):
   Currently `_transform_anthropic_messages_to_chat` and `_transform_anthropic_tools_to_chat` each emit their own `cache_control_stripped` event. The plan says "once per request."
   Fix — remove the `log_trace` calls from both transform functions. Instead, return the `cache_stripped` flag to `_anthropic_to_chat` via an optional out-parameter (a `list` that gets appended to). This avoids changing the return type and keeps backward compatibility for direct callers (tests):
   ```python
   # In _transform_anthropic_messages_to_chat:
   # Remove the `if cache_stripped: log_trace(...)` block at the end.
   # Instead, at the end of the function:
   if cache_stripped and cache_stripped_out is not None:
       cache_stripped_out.append("messages")
   return out

   # In _transform_anthropic_tools_to_chat:
   # Same pattern — remove the log_trace, append to out-param:
   if cache_stripped and cache_stripped_out is not None:
       cache_stripped_out.append("tools")
   return out

   # In _anthropic_to_chat:
   cache_locations = []
   out["messages"] = _transform_anthropic_messages_to_chat(
       ..., cache_stripped_out=cache_locations)
   # ...
   out["tools"] = _transform_anthropic_tools_to_chat(
       ..., cache_stripped_out=cache_locations)
   # Emit ONE event after both transforms:
   if cache_locations:
       log_trace({"event": "cache_control_stripped", "locations": cache_locations, ...})
   ```
   **Signature change:** Add `cache_stripped_out=None` parameter to both `_transform_anthropic_messages_to_chat` and `_transform_anthropic_tools_to_chat`. The plan's Step 1 and Step 2 signatures in the summary should be updated to reflect this.

   **6e. Add `location` to messages-level `content_block_dropped`** (Suggestion 5, line 1411):
   The messages-level event omits `location` while the tools-level event has `location: "tool_definition"`. Add `"location": "message"` to the messages-level event dict for schema consistency.

   **6f. Add `tool_result` counter to `dropped_counts`** (Suggestion 6, line 1382):
   Currently `dropped["unknown"] += 1` when `_transform_tool_result_to_chat_tool` returns None (unmatched tool_use_id). This mislabels a known block type as "unknown."
   Fix:
   - Add `"tool_result": 0` to the `dropped` dict initialization (line 1292)
   - Change `dropped["unknown"] += 1` to `dropped["tool_result"] += 1` at line 1382
   - Update `dropped_counts` enum to `{thinking, redacted_thinking, image, tool_result, unknown}`

   **6g. Trace non-dict content blocks** (Suggestion 7, lines 1313-1314, 1374-1375):
   Currently `if not isinstance(block, dict): continue` silently skips non-dict blocks without incrementing `dropped`.
   Fix — add `dropped["unknown"] += 1` before `continue` in both the assistant loop (line 1314) and the user loop (line 1375).

   **6h. Guard non-string tool_use id/name** (Suggestion 8, line 1347-1356):
   Currently `tool_id` is guarded for the pairing set (`isinstance(tool_id, str) and tool_id`) but the emitted `tool_calls` entry always includes `id` and `name` regardless of type. A non-string `id` (e.g. `123`) would never match a downstream `tool_result` and could cause upstream issues.
   Fix — after the NaN/non-dict guards and `json.dumps`:
   ```python
   # Guard: id must be a non-empty string
   if not isinstance(tool_id, str) or not tool_id:
       dropped["unknown"] += 1
       continue
   tool_use_ids.add(tool_id)
   # Guard: name falls back to "" if not a string
   if not isinstance(tool_name, str):
       tool_name = ""
   tool_calls.append({
       "id": tool_id,
       "type": "function",
       "function": {"name": tool_name, "arguments": arguments},
   })
   ```
   Note: the `tool_use_ids.add(tool_id)` moved AFTER the guard (previously it was before the guard but conditional — now it's always added after validation).

   **6i. Add regression tests for the two 400-prone paths** (Suggestion 9):
   Tests handled by tester — see Guidance for Tester below.

   **Impact on existing tests:**
   - `test_anthropic_to_chat_cache_control_stripped_trace`: the event shape changes from `location: "message_block"` to `locations: ["messages"]` (or `["messages", "tools"]`). The tester must update this test's assertion.
   - `test_anthropic_to_chat_tools_cache_control_stripped`: same — event now emitted from `_anthropic_to_chat`, not from `_transform_anthropic_tools_to_chat`. The test calls `_transform_anthropic_tools_to_chat` directly, so the `cache_control_stripped` event will no longer appear. The test must be updated to call `_anthropic_to_chat` or to check the out-parameter instead.
   - `test_anthropic_to_chat_messages_cache_control_stripped`: same — test calls `_transform_anthropic_messages_to_chat` directly. Event now emitted from `_anthropic_to_chat`. Update test accordingly.
   - `test_anthropic_to_chat_messages_null_user_content`: should still pass (6c preserves the literal null/empty case).
   - `test_anthropic_to_chat_no_input_mutation`: should still pass.
   - `test_anthropic_to_chat_content_block_dropped_trace`: should still pass (the event shape changes only by adding `location`).

   → coder verify (auto): `tool_result` in `dropped_counts`; `location` on messages `content_block_dropped`; `isinstance(input_val, dict)` before `json.dumps`; non-dict blocks increment `dropped["unknown"]`; `id` guarded as non-empty string; `cache_control_stripped` emitted from `_anthropic_to_chat` not the individual transforms; `cache_stripped_out` parameter on both transform functions
   → coder verify (scripted): `./tmp/verification/2026-08-29-fix-chat-mode-request-transform-step6.py` (new — create this)
   → tester verify: `test_anthropic_to_chat_tool_use_non_dict_input` — string/None/number input → placeholder + tool_args_parse_failure
   → tester verify: `test_anthropic_to_chat_nan_placeholder_with_valid_tool_use` — NaN + valid tool_use coexistence → placeholder as separate message + tool_calls
   → tester verify: update `test_anthropic_to_chat_cache_control_stripped_trace` for `locations: [...]` shape
   → tester verify: update `test_anthropic_to_chat_tools_cache_control_stripped` to call `_anthropic_to_chat` instead of `_transform_anthropic_tools_to_chat` directly
   → tester verify: update `test_anthropic_to_chat_messages_cache_control_stripped` for the new event emission location

## Guidance for Tester

**Tests to create:**
- **Permanent:** `test_anthropic_to_chat_messages_transform` — full message array with thinking, text, tool_use, tool_result blocks → valid OpenAI Chat messages
- **Permanent:** `test_anthropic_to_chat_messages_thinking_stripped` — thinking and redacted_thinking blocks removed from assistant messages
- **Permanent:** `test_anthropic_to_chat_messages_tool_use_to_tool_calls` — tool_use block → tool_calls with JSON-stringified arguments (allow_nan=False)
- **Permanent:** `test_anthropic_to_chat_messages_tool_result_to_role_tool` — tool_result block in user message → separate role:tool message
- **Permanent:** `test_anthropic_to_chat_messages_mixed_text_and_tool_use` — assistant message with both text and tool_use → content:null + tool_calls (text elided per OpenAI requirement)
- **Permanent:** `test_anthropic_to_chat_messages_mixed_text_and_tool_result` — user message with both text and tool_result → tool messages first, then user text message
- **Permanent:** `test_anthropic_to_chat_messages_interleaved_thinking_tool_use` — real-world interleaved pattern from trace log
- **Permanent:** `test_anthropic_to_chat_messages_string_content_passthrough` — string content passes through unchanged (new message dict returned)
- **Permanent:** `test_anthropic_to_chat_messages_cache_control_stripped` — cache_control removed from blocks, `cache_control_stripped` trace event logged. Verifies per-block (not per-message) cache_control detection via `block.get("cache_control")`. Multiple user text blocks with cache_control stripped are joined to a string, not kept as an array.
- **Permanent:** `test_anthropic_to_chat_messages_non_list_guarded` — non-list messages returns []
- **Permanent:** `test_anthropic_to_chat_messages_non_dict_entries_skipped` — non-dict message entries skipped
- **Permanent:** `test_anthropic_to_chat_messages_null_user_content` — null user content becomes ""
- **Permanent:** `test_anthropic_to_chat_tools_transform` — Anthropic tools → OpenAI tools (input_schema→parameters)
- **Permanent:** `test_anthropic_to_chat_tools_cache_control_stripped` — cache_control on tool definitions stripped
- **Permanent:** `test_anthropic_to_chat_tools_non_list_guarded` — non-list tools returns []
- **Permanent:** `test_anthropic_to_chat_tools_malformed_entries_skipped` — missing name/input_schema entries skipped with trace
- **Permanent:** `test_anthropic_to_chat_tool_choice_mapping` — all 4 tool_choice variants mapped correctly
- **Permanent:** `test_anthropic_to_chat_tool_choice_none_omitted` — None/absent tool_choice omitted from output
- **Permanent:** `test_anthropic_to_chat_tool_choice_malformed_omitted` — malformed/unknown tool_choice → None
- **Permanent:** `test_anthropic_to_chat_tool_choice_only_with_tools` — tool_choice omitted when tools array is empty
- **Permanent:** `test_anthropic_to_chat_integration` — full Anthropic request with system, tools, tool_choice, multi-turn messages with tool_use/tool_result → valid OpenAI Chat request
- **Permanent:** `test_anthropic_to_chat_content_block_dropped_trace` — verify coalesced content_block_dropped trace event with dropped_counts
- **Permanent:** `test_anthropic_to_chat_cache_control_stripped_trace` — verify cache_control_stripped trace event
- **Permanent:** `test_anthropic_to_chat_nan_infinity_arguments_rejected` — tool_use.input with NaN/Infinity raises ValueError via allow_nan=False, degraded to a text placeholder `[Tool call failed: arguments for '<name>' (call <id>) could not be serialized as JSON]` with a `tool_args_parse_failure` trace event (not silently dropped)
- **Permanent:** `test_anthropic_to_chat_tool_result_list_content` — tool_result.content as list of text blocks → joined string
- **Permanent:** `test_anthropic_to_chat_no_input_mutation` — verify _anthropic_to_chat does not mutate the input dict or its nested structures
- **Permanent:** `test_anthropic_to_chat_tool_use_non_dict_input` — tool_use.input with non-dict value (string, None, number) → degraded to text placeholder with tool_args_parse_failure (not silently passed through as a non-object arguments string)
- **Permanent:** `test_anthropic_to_chat_nan_placeholder_with_valid_tool_use` — NaN tool_use + valid tool_use in same assistant message → placeholder emitted as separate assistant message before tool_calls message (content: null), not silently discarded
- **Temporary:** None

**Tests to update (existing tests that need behavioral changes):**
- `test_anthropic_to_chat_dropped_fields` (line 7337) — currently asserts `tools`, `tool_choice` are dropped. After the fix, these fields are TRANSFORMED (not dropped). Update the test to assert `tools` and `tool_choice` are present in output with correct transformed values, and that `thinking`, `metadata`, `top_k` remain dropped.
- `test_anthropic_to_chat_basic` (line 7268) — no change needed (simple text message pass-through still works)
- `test_anthropic_to_chat_system_string` (line 7295) — no change needed
- `test_anthropic_to_chat_system_list` (line 7313) — no change needed
- `test_anthropic_to_chat_stop_sequences` (line 7360) — no change needed
- `test_anthropic_to_chat_cache_control_stripped_trace` (line 7935) — **Step 6d:** event shape changes from `location: "message_block"` to `locations: ["messages"]` (or `["messages", "tools"]` when both have cache_control). Update assertion.
- `test_anthropic_to_chat_tools_cache_control_stripped` (line 7698) — **Step 6d:** `cache_control_stripped` event is now emitted from `_anthropic_to_chat`, not from `_transform_anthropic_tools_to_chat`. Direct calls to the transform function will no longer produce the event. Update the test to call `_anthropic_to_chat` instead, or to check the `cache_stripped_out` parameter.
- `test_anthropic_to_chat_messages_cache_control_stripped` (line 7606) — **Step 6d:** same as above — event now emitted from `_anthropic_to_chat`. Update the test to call `_anthropic_to_chat` with a body dict containing messages, or to check the `cache_stripped_out` parameter.
- `test_anthropic_to_chat_messages_mixed_text_and_tool_use` (line 7505) — **Step 6b:** previously asserted text elided when tool_calls present (content:null). Now text is emitted as a separate assistant message before the tool_calls message. Update assertion.
- `test_anthropic_to_chat_messages_interleaved_thinking_tool_use` (line 7556) — **Step 6b:** previously asserted the interleaved pattern collapses to a single tool_calls message. Now text blocks are joined and emitted as a separate assistant message before the tool_calls message. Update assertion.
- `test_anthropic_to_chat_messages_transform` (line 7385) — **Step 6b:** may need update if it asserts the old text-elision behavior.
- `test_anthropic_to_chat_integration` (line 7830) — **Step 6b:** may need update if it asserts the old text-elision behavior.

**Tests to investigate for retirement:**
- Planner candidates:
  - `test_anthropic_to_chat_dropped_fields` (line 7337) — test updated (see above), not retired. The updated test validates the field-level presence of transformed tools/tool_choice alongside still-dropped fields.
- No test obsolescence identified.

## Summary

### Problem
`_anthropic_to_chat()` passes Anthropic messages through to the upstream OpenAI Chat API with zero transformation. Anthropic `content` arrays contain block types (`thinking`, `tool_use`, `tool_result`) that the OpenAI Chat API rejects. Proven by three 400 errors from opencode-go: `unknown variant 'thinking'`, `186 validation errors`, `38 validation errors`.

### Approach
Build three new transform functions and wire them into `_anthropic_to_chat()`, replacing the raw passthrough:

```
Anthropic Messages request
    │
    ├─ system (string/list) ──────► role: "system" message (existing)
    ├─ messages ──► _transform_anthropic_messages_to_chat() ──► OpenAI messages
    │                  • thinking/redacted_thinking → stripped (content_block_dropped trace)
    │                  • text → content string
    │                  • tool_use → tool_calls (input obj → arguments JSON string, allow_nan=False)
    │                  • tool_result → role: "tool" message (paired by tool_use_id)
    │                  • cache_control → stripped (cache_control_stripped trace)
    │                  • content: null when tool_calls present (OpenAI requirement)
    ├─ tools ────► _transform_anthropic_tools_to_chat() ───► OpenAI tools
    │                  • input_schema → parameters
    │                  • {name, description, input_schema} → {type:"function", function:{...}}
    │                  • malformed entries skipped with trace
    ├─ tool_choice ► _transform_anthropic_tool_choice_to_chat() ► OpenAI tool_choice
    │                  • {type:"auto"} → "auto", {type:"any"} → "required", etc.
    │                  • malformed/unknown → omitted
    │                  • only emitted when tools array is non-empty
    └─ model, max_tokens, temperature, stream, top_p, stop_sequences → passthrough (existing)
```

### Deliberately dropped (with rationale)

| Feature | Disposition | Rationale |
|---------|-------------|-----------|
| `thinking` blocks | Stripped | Internal reasoning visible only in Anthropic. Inflates tokens (often thousands), pollutes assistant voice, can't be round-tripped. Upstream model only needs tool_use + tool_result + visible text to continue the conversation. |
| `redacted_thinking` blocks | Stripped | Encrypted thinking — same as above, plus unreadable anyway. |
| `cache_control` | Stripped | Anthropic per-block cache markers. No OpenAI equivalent; `prompt_cache_key` is request-level, not block-level. OpenAI automatic caching handles the common case. |
| `top_k` | Stripped | Anthropic-specific sampling parameter. |
| `image` blocks | Deferred | `defer-issue-image-content-blocks-chat-mode` — Anthropic `{type:image, source:{type:base64,...}}` ↔ OpenAI `{type:image_url, image_url:{url:...}}` mapping possible but deferred. |
| Streaming tool call deltas | Deferred | `defer-issue-streaming-tool-call-deltas` — `input_json_delta` ↔ `function.arguments` delta streaming requires per-block argument buffering, multi-index content_block_start/stop, and stop_reason restoration. The full streaming solution is deferred; the non-streaming path handles tool use correctly. |

### Out of scope
- Streaming tool call argument deltas (`input_json_delta` ↔ `function.arguments` deltas)
- Image content block mapping (Anthropic ↔ OpenAI)
- `response_format` / `output_config` mapping
- `thinking` budget/config mapping to `reasoning_effort`
- SSE content_block_start for tool_use in chat-mode streaming (deferred to `defer-issue-streaming-tool-call-deltas`)

## Repo Mode

Public

## Document Overrides

| Document | Rule Overridden | Reason |
|----------|----------------|--------|
| CLAUDE.md (Gotchas > Provider mode dispatch) | "Tool-use SSE deltas are not transformed (stop_reason degraded to null when tool_calls are seen)" | This rule remains true for the streaming path. The non-streaming path (this plan) now correctly transforms tool_use/tool_result in request messages and tool_calls in response bodies. The SSE limitation is unchanged. |
| README.md (Provider Modes > Limitations) | "Tool-use SSE deltas are not transformed in chat-mode streaming" | Same as above — unchanged. This plan only affects non-streaming request/response transforms. |

## Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| Tool call `arguments` JSON serialization with NaN/Infinity | `json.dumps(input)` with default `allow_nan=True` emits literal `NaN`/`Infinity` tokens — invalid strict JSON that reaches the upstream provider. | Use `json.dumps(input, allow_nan=False)` which raises `ValueError` on non-finite floats. Catch in try/except, emit a text placeholder `[Tool call failed: arguments for '<name>' (call <id>) could not be serialized as JSON]` (matching the existing `_chat_to_anthropic` degradation pattern), log `tool_args_parse_failure` trace event. See Step 1 tool_use error path for detailed instructions. |
| Assistant content + tool_calls rejection | OpenAI requires `content: null` when `tool_calls` is present. Emitting a string content alongside tool_calls may cause upstream 400. | Set `content: null` when tool_calls are present. Text content from the same assistant turn is elided (the text is typically transitional like "I'll look that up" — the tool call conveys the intent). |
| `content_block_dropped` log amplification | A single request with many dropped blocks could flood the trace log. | Coalesce into a single `content_block_dropped` event per request with `dropped_counts: {thinking: N, ...}`. |
| `tool_result` content as list | Anthropic `tool_result.content` can be a list of text blocks, not just a string. | Join text blocks with newlines; if non-text blocks present, extract text only. |
| Input mutation | `del body_json["thinking"]` would mutate the caller's dict. | Build `out` without side effects; never mutate `body_json`. |

## Proposed Changes

1. **Step 1:** Add `_transform_anthropic_messages_to_chat(messages, request_id=None, mode=None, provider=None, tier=None, cache_stripped_out=None)` — converts Anthropic `messages` array to OpenAI Chat Completions messages. Always returns a new list.
   → coder verify (auto): `_transform_anthropic_messages_to_chat` defined in `server.py`, signature `(messages, request_id=None, mode=None, provider=None, tier=None, cache_stripped_out=None)`, returns `list`
   → coder verify (scripted): `./tmp/verification/2026-08-29-fix-chat-mode-request-transform-step1.py`

2. **Step 2:** Add `_transform_anthropic_tools_to_chat(tools, request_id=None, mode=None, provider=None, tier=None, cache_stripped_out=None)` — converts Anthropic tool definitions to OpenAI Chat format.
   → coder verify (auto): `_transform_anthropic_tools_to_chat` defined in `server.py`, signature `(tools, request_id=None, mode=None, provider=None, tier=None, cache_stripped_out=None)`, returns `list`
   → coder verify (scripted): `./tmp/verification/2026-08-29-fix-chat-mode-request-transform-step2.py`

3. **Step 3:** Add `_transform_anthropic_tool_choice_to_chat(tool_choice)` — converts Anthropic tool_choice to OpenAI format.
   → coder verify (auto): `_transform_anthropic_tool_choice_to_chat` defined in `server.py`, accepts `(tool_choice: dict | None)` and returns `str | dict | None`
   → coder verify (scripted): `./tmp/verification/2026-08-29-fix-chat-mode-request-transform-step3.py`

4. **Step 4:** Rewire `_anthropic_to_chat(body_json, request_id=None, mode=None, provider=None, tier=None)` to use the three new transforms. Build output without mutating input. Update `_forward_request_impl` call site to pass metadata.
   → coder verify (auto): `_anthropic_to_chat` calls `_transform_anthropic_messages_to_chat`, `_transform_anthropic_tools_to_chat`, `_transform_anthropic_tool_choice_to_chat`; `out["messages"]` is not `body_json["messages"]`; `body_json` is not mutated
   → coder verify (scripted): `./tmp/verification/2026-08-29-fix-chat-mode-request-transform-step4.py`

5. **Step 5:** Add `content_block_dropped` (coalesced, with `dropped_counts`) and `cache_control_stripped` trace event logging in the request transform functions. Thread `request_id`/`mode`/`provider`/`tier` from `_forward_request_impl` through `_anthropic_to_chat` to all three transforms.
   → coder verify (auto): `content_block_dropped` and `cache_control_stripped` appear as valid event strings in `log_trace` call sites
   → coder verify (auto): `content_block_dropped` uses coalesced `dropped_counts` map
   → tester verify: `test_content_block_dropped_trace_event` — verify coalesced trace event with dropped_counts
   → tester verify: `test_cache_control_stripped_trace_event` — verify trace event logged

6. **Step 6:** Fix 9 reviewer findings (3 Warnings + 6 Suggestions) in `_transform_anthropic_messages_to_chat()`, `_transform_anthropic_tools_to_chat()`, and `_anthropic_to_chat()`. Add `cache_stripped_out` parameter, validate dict input, preserve text with tool_calls, drop empty user messages, coalesce cache_control events, add location/tool_result fields, guard id/name.
   → coder verify (auto): `isinstance(input_val, dict)` check; `tool_result` in dropped_counts; `location` on messages event; non-dict blocks traced; id/name guarded; `cache_control_stripped` in `_anthropic_to_chat`
   → coder verify (scripted): `./tmp/verification/2026-08-29-fix-chat-mode-request-transform-step6.py`
   → tester verify: `test_anthropic_to_chat_tool_use_non_dict_input` — non-dict input → placeholder
   → tester verify: `test_anthropic_to_chat_nan_placeholder_with_valid_tool_use` — NaN + valid coexistence
   → tester verify: update 3 cache_control tests for new event emission location

## Guidance for Planner

- **Doc files to update:** `CLAUDE.md`, `README.md`
- **When:** after coder finishes
- **What to sync:**
  - `CLAUDE.md`: Document the chat-mode request transform rules (what's mapped, what's dropped, what's deferred). Add `content_block_dropped` and `cache_control_stripped` trace event schemas. Update test count from 123 to ~149 (123 + 26 new permanent tests). Update the "Tool-use SSE deltas are not transformed" gotcha to clarify the split between non-streaming (now transformed) and streaming (deferred).
  - `README.md`: Update the chat-mode limitation text to clarify that tool_use/tool_result are now transformed in non-streaming requests; SSE streaming tool call deltas remain deferred.

## Rollback

Single-commit revert of the transform functions and `_anthropic_to_chat` rewire. Restore the pre-existing `_anthropic_to_chat` that passes messages through unchanged. Note: `test_anthropic_to_chat_dropped_fields` would need its original assertion restored (tools/tool_choice dropped) on revert.

## History

| Date | Event | Conclusion | Dismissed |
|------|-------|------------|-----------|
| 2026-08-29 | Initial plan | 6-step plan: messages/tools/tool_choice transforms, rewire _anthropic_to_chat, SSE content_block_start, trace events. Two deferred issues. | — |
| 2026-08-29 | Spec revision (/update-plan) | Coder+tester round 1: 146/149 pass. 3 plan-compliance failures. **Issue 1 (block-level-cache-control):** plan is correct — coder must fix implementation to check `block.get("cache_control")` per-block, not `"cache_control" in msg` per-message. Added explicit per-block guidance to Step 1. **Issue 2 (nan-tool-use-placeholder):** plan gap — Step 1's tool_use branch now includes the full error path (text placeholder + `tool_args_parse_failure` event) matching the existing `_chat_to_anthropic` degradation pattern. **Issue 3 (user-text-blocks-array):** plan over-spec — user text blocks now join to a string (simpler, more provider-compatible), replacing the "array if multiple" spec. Fixed Step 5 test name drift (Guidance for Tester names now authoritative). | — |
| 2026-08-29 | Coder+tester round 2 | All 3 issues resolved. Coder: per-block cache_control detection, NaN text placeholder + tool_args_parse_failure event, plan revision for string join (no code change). Tester: 149/149 PASS (0 fail). Two test revisions: string-join user text blocks expected output, NaN placeholder format. | — |
| 2026-08-29 | Phase 6 review + spec revision | Reviewer found 0 Critical, 3 Warnings, 6 Suggestions. All 9 accepted as valid and beneficial. Added Step 6 covering: (W1) non-dict tool_use input validation, (W2) NaN placeholder preservation with valid tool_use, (W3) drop empty user messages instead of `content:""`, (S4) coalesce cache_control_stripped across functions, (S5) add location to messages content_block_dropped, (S6) tool_result counter in dropped_counts, (S7) trace non-dict blocks, (S8) guard non-string tool_use id/name, (S9) 2 new regression tests. | — |
| 2026-08-29 | Coder+tester round 3 (Step 6) | All 9 reviewer findings resolved. Coder: implemented 6a-6h, filed plan-gap issue (2 tests omitted from Impact list). Tester: 151/151 PASS (0 fail). 2 new tests + 7 revised tests. Plan gap (step6-test-updates-misassigned) closed — tester independently identified and updated the 2 missing tests. | [step6-test-updates-misassigned] |
| 2026-08-29 | Mega-audit (pre-implementation) | 13 High, 18 Medium, 3 Low findings. Dropped SSE Step 5 (deferred to streaming-tool-call-deltas). Fixed NaN risk (allow_nan=False), content+tool_calls (null), tool_result pairing (by tool_use_id), cache_control event type (separate from content_block_dropped), input mutation (build out without side effects), log amplification (coalesced dropped_counts), non-list guards, malformed entry guards, tool_choice gating on tools non-empty, consecutive tool messages (keep separate, not merged), plan metadata alignment, document overrides, rollback section. 5 steps, 26 new tests. | [step5-sse-unclosed-blocks], [step5-stop-reason-contradiction], [step5-index-collision], [step6-threading-false-premise], [verification-scripts-not-exist], [step5-rule-violation], [step5-block-conflict], [step5-terminal-no-close], [step5-stop-reason-null-conflict], [step5-empty-input-regression], [nan-risk-noop], [test-dropped-fields-will-fail], [test-count-stale], [missing-tool_result-pairing], [content-tool_calls-rejection], [cache_control-block-type], [consecutive-tool-messages-merge], [input-mutation-del], [test-obsolescence], [claude-md-sse-stale], [readme-sse-stale], [metadata-doc_files-sync], [metadata-tester_files-sync], [self-contradictory-dropped-fields], [system-block-drops-silent], [non-list-messages-guard], [malformed-tool_choice-guard], [tools-edge-cases], [string-content-identity-check], [deferred-issue-sse-scope], [content_block_dropped-per-block-amplification], [tool_result-list-content], [missing-rollback-section], [response-image-drops-asymmetric], [hunch-client-hang-empty-input], [hunch-interleaved-text-tool_calls] |

## Plan Metadata

```json
{
  "plan_id": "2026-08-29-fix-chat-mode-request-transform",
  "steps": [
    "Step 1: Add _transform_anthropic_messages_to_chat()",
    "Step 2: Add _transform_anthropic_tools_to_chat()",
    "Step 3: Add _transform_anthropic_tool_choice_to_chat()",
    "Step 4: Rewire _anthropic_to_chat() to use transforms",
    "Step 5: Add content_block_dropped and cache_control_stripped trace event logging",
    "Step 6: Fix 9 reviewer findings (3 Warnings + 6 Suggestions)"
  ],
  "coder_files": ["src/claude_retry_proxy/server.py"],
  "tester_files": [
    "tests/test_claude_proxy.py"
  ],
  "doc_files": ["CLAUDE.md", "README.md"],
  "verification_scripts": [
    "./tmp/verification/2026-08-29-fix-chat-mode-request-transform-step1.py",
    "./tmp/verification/2026-08-29-fix-chat-mode-request-transform-step2.py",
    "./tmp/verification/2026-08-29-fix-chat-mode-request-transform-step3.py",
    "./tmp/verification/2026-08-29-fix-chat-mode-request-transform-step4.py",
    "./tmp/verification/2026-08-29-fix-chat-mode-request-transform-step6.py"
  ],
  "repo_mode": "Public",
  "document_overrides": [
    "CLAUDE.md: Tool-use SSE deltas are not transformed (Reason: unchanged — this plan only affects non-streaming request/response transforms. The SSE limitation remains true.)",
    "README.md: Tool-use SSE deltas are not transformed in chat-mode streaming (Reason: same as above — unchanged.)"
  ]
}
```

## Audit Accumulation

| Counter | Value | Last Updated |
|---------|-------|--------------|
| issues_resolved_since_audit | 0 | 2026-08-29 |
| steps_changed_since_audit | 0 | 2026-08-29 |
| files_changed_since_audit | 0 | 2026-08-29 |

## Final Results

**Completed:** 2026-08-29
**Status:** COMPLETED

### Files Changed

| File | Lines | Description |
|------|-------|-------------|
| `src/claude_retry_proxy/server.py` | +298 / -8 | Three new transform functions + rewire `_anthropic_to_chat()` + trace events + 8 reviewer fixes |
| `tests/test_claude_proxy.py` | +808 / -0 | 28 new permanent tests + 1 revised + 7 tests updated for Step 6 behavior |

### Implementation

1. **`_transform_anthropic_messages_to_chat()`** (new) — Converts Anthropic `messages` array to OpenAI Chat format. Strips thinking/redacted_thinking/image/cache_control. Transforms tool_use→tool_calls (dict input validated, NaN/non-dict→placeholder), tool_result→role:tool (paired by tool_use_id). User text blocks joined to string. Empty user messages dropped. Assistant text preserved as separate message when tool_calls present. Non-dict blocks traced. Tool_use id/name guarded.

2. **`_transform_anthropic_tools_to_chat()`** (new) — Converts Anthropic tools: `input_schema`→`parameters`, wraps in `{type:"function", function:{...}}`. Skips malformed entries. Strips cache_control.

3. **`_transform_anthropic_tool_choice_to_chat()`** (new) — Maps `{type:"auto"}`→`"auto"`, `{type:"any"}`→`"required"`, `{type:"tool"}`→`{type:"function",function:{name}}`. Malformed→None. Only emitted when tools non-empty.

4. **`_anthropic_to_chat()` rewire** — Replaced raw passthrough with calls to the three transforms. Coalesces `cache_control_stripped` into one event per request with `locations: [...]`.

5. **Trace events** — `content_block_dropped` (coalesced, `dropped_counts: {thinking, redacted_thinking, image, tool_result, unknown}`, `location`), `cache_control_stripped` (once per request, `locations: [...]`), `tool_args_parse_failure` (on NaN/non-dict input).

6. **Reviewer fixes** — 9 findings (3 Warnings + 6 Suggestions) all resolved. Non-dict input validation, placeholder preservation, empty message drop, event coalescing, location field, tool_result counter, non-dict block tracing, id/name guards.

### Test Results

- **151 tests total, 151 passed, 0 failed**
- 28 new permanent tests + 1 revised test + 7 tests updated for Step 6
- Pre-existing 123-test suite passes unchanged
- 3 rounds: round 1 (146/149, 3 plan-compliance issues), round 2 (149/149, all resolved), round 3 (151/151, reviewer fixes verified)

### Issues Resolved (13 total)

| Issue | Resolution |
|-------|-----------|
| [block-level-cache-control](./tmp/reports/2026-08-29-fix-chat-mode-request-transform-block-level-cache-control.json) | Coder: per-block `block.get("cache_control")` detection |
| [nan-tool-use-placeholder](./tmp/reports/2026-08-29-fix-chat-mode-request-transform-nan-tool-use-placeholder.json) | Coder: text placeholder + `tool_args_parse_failure` event |
| [user-text-blocks-array](./tmp/reports/2026-08-29-fix-chat-mode-request-transform-user-text-blocks-array.json) | Plan revised: string join accepted |
| [step6-test-updates-misassigned](./tmp/reports/2026-08-29-fix-chat-mode-request-transform-step6-test-updates-misassigned.json) | Tester: updated 2 tests omitted from Impact list |
| 9 reviewer findings | Coder + tester: all fixed and verified |

### Deferred (not in scope)

| Issue | Reason |
|-------|--------|
| [streaming-tool-call-deltas](./tmp/reports/defer-issue-streaming-tool-call-deltas.json) | SSE input_json_delta ↔ function.arguments delta streaming |
| [image-content-blocks-chat-mode](./tmp/reports/defer-issue-image-content-blocks-chat-mode.json) | image ↔ image_url mapping |

### Deliberately Dropped

| Feature | Rationale |
|---------|-----------|
| `thinking` blocks | Internal reasoning, inflates tokens, can't round-trip |
| `redacted_thinking` blocks | Encrypted thinking, unreadable |
| `cache_control` | Anthropic per-block cache markers, no OpenAI equivalent |
| `top_k` | Anthropic-specific sampling parameter |
| `metadata` | Anthropic request-level metadata field |