# Plan: Fix buffered Responses API tool-call round trips
**Project:** D:\proj\claude-retry-proxy
**Plan ID:** 2026-08-31-fix-response-mode-tool-roundtrip
**Created:** 2026-08-31

## Issue Log

Rows ordered newest-first (latest issues at top). New issues are prepended; resolved issues stay in place with updated status.

| Issue | Status | Found | Resolved | Resolved By |
|-------|--------|-------|----------|-------------|
| [response-temperature-passthrough](./tmp/reports/defer-issue-response-temperature-passthrough.json) | Resolved | 2026-08-31 | 2026-08-31 | [planner](./tmp/reports/defer-issue-response-temperature-passthrough.json) |

## Guidance for Coder

**Files to modify:**
- `src/claude_retry_proxy/server.py`

**Step-by-step with verification:** each step below has coder checks tagged `(auto)` or `(scripted)`. The coder self-verifies `(auto)` checks and runs the provided script for `(scripted)` checks. Tester owns behavioral checks and all test-file changes.

1. Extend `_anthropic_to_response()` to emit a complete buffered Responses API request for text and client-tool conversations rather than extracting only the last user string. Keep `stream: false`. Convert the full message history in order: user/assistant text becomes an exact Responses message item shaped `{"type":"message","role":...,"content":[{"type":"input_text","text":...}]}`; assistant `tool_use` becomes a `function_call` input item with `call_id`, `name`, and strict JSON-string `arguments`; user `tool_result` becomes `function_call_output` with the same `call_id` and a string `output`. Preserve parallel calls and multiple results in their original order. Track the set of call IDs actually emitted by preceding valid `function_call` items; emit a `function_call_output` only when its `tool_use_id` belongs to that set and has not already been consumed, otherwise drop it with a bounded metadata-only diagnostic. This prevents orphan, duplicate, or invalidated call outputs from causing an upstream 400. Convert Anthropic tool definitions to the Responses API's flat function-tool shape (`type`, `name`, optional `description`, `parameters`) and map tool choices (`auto`, `any`, `tool`, `none`) only against the validated emitted tool-name set; a named choice whose tool was dropped is omitted rather than sent as an invalid reference. Continue mapping `system` to `instructions` and `max_tokens` to `max_output_tokens`. Do not mutate the input object.
   - Unsupported content remains narrowly scoped: retain textual content; do not add image, thinking, redacted-thinking, or server-tool support in this plan. Drop unsupported blocks with bounded metadata-only diagnostics, reusing existing trace-event conventions and never logging tool names, arguments, results, or API keys. If a message has no retained text or tool items (including `None`, `[]`, or unsupported-only content), omit it; then coalesce adjacent retained message items with the same role so dropped turns cannot create an invalid role sequence. Function-call items remain in their original relative positions between message items.
   - Validate tool names, IDs, and schemas before emitting items. Serialize `tool_use.input` with `json.dumps(..., allow_nan=False)` and require a dictionary; `{}` is valid for zero-argument tools. On invalid input, omit the invalid `function_call`, emit the existing user-visible serialization-failure placeholder as assistant text, and log `tool_args_parse_failure`. Because only emitted IDs enter the known-call set, any following result for that omitted call is also dropped. Convert `tool_result.content` strings or lists of text blocks to a string; preserve an error result's text even though Responses has no direct `is_error` equivalent.
   → coder verify (auto): `_anthropic_to_response` still forces `stream` to false and accepts the existing request dict; generated function tools use a flat object with `name` and `parameters`, not a nested `function` object; no test or documentation file is modified by the coder
   → coder verify (scripted): `python ./tmp/verification/2026-08-31-fix-response-mode-tool-roundtrip-step1.py` exits 0 and prints its single PASS line
   → tester verify: request-transform tests cover exact message-item shape, full ordered text history, empty/`None` and unsupported-only turns with role coalescing, one and parallel `tool_use` calls, matching/orphan/duplicate `tool_result` items, invalid tool call followed by its result, mixed text/tool blocks, tool definitions, all supported tool choices including a named dropped tool alongside another valid tool, cache-control removal, malformed schemas/IDs/inputs, NaN/non-dict inputs, valid empty-dict inputs, error results, no input mutation, and `stream: false`

2. Extend `_response_to_anthropic()` to inspect every Responses output item in order. Map `message`/`output_text` content to Anthropic text blocks and each valid `function_call` item to an Anthropic `tool_use` block (`call_id` → `id`, `name` → `name`, parsed JSON-object `arguments` → `input`). Preserve mixed text and parallel function calls. Set `stop_reason: "tool_use"` whenever at least one valid function call is emitted; otherwise retain the current completed-text mapping to `end_turn` and incomplete/unknown mapping to null.
   - Parse `arguments` as follows: accept an already-parsed dictionary directly; otherwise require a string and parse it with `json.loads`; accept `{}` as a valid zero-argument input but reject non-object results. A malformed entry becomes a user-visible failure text block plus a metadata-only `tool_args_parse_failure` trace event. Track both whether any `function_call` item was seen and whether any valid tool block was emitted. If calls were seen but all were malformed, force `stop_reason: null` even when upstream status is `completed`; never report either `tool_use` or `end_turn` for a placeholder-only degraded call response. Ignore unsupported output-item types without crashing, and retain guarded passthrough-on-transform-failure behavior.
   → coder verify (auto): `_response_to_anthropic` has an explicit `function_call` branch that builds `tool_use` blocks and only assigns `stop_reason: "tool_use"` when a valid tool block was emitted
   → coder verify (scripted): `python ./tmp/verification/2026-08-31-fix-response-mode-tool-roundtrip-step2.py` exits 0 and prints its single PASS line
   → tester verify: response-transform tests cover one and parallel calls, mixed text/calls, all output items without an early break, output ordering, valid string and dict argument objects including `{}`, malformed/non-object arguments, missing IDs/names, all-malformed completed response yielding null stop reason, missing usage, completed text-only output, and unsupported output items

3. Keep response-mode dispatch buffered and ensure both richer converters receive trace context. Thread `request_id`, `mode`, `provider`, and `tier` into `_anthropic_to_response()` and use the existing arguments already available to `_response_to_anthropic()`, following the established chat-transform pattern. Build the transformed request once before the retry loop, preserve byte-for-byte non-2xx passthrough, recompute `Content-Length` after successful response conversion, and leave anthropic/chat behavior unchanged.
   → coder verify (auto): the response-mode request transform remains before the retry loop; `_anthropic_to_response` receives trace context at its sole production call site; no response-mode SSE transformer is introduced; non-2xx chat/response bodies still bypass transforms
   → tester verify: mocked proxy integration confirms retries do not duplicate input items, transformed request headers/path remain correct, a two-turn tool loop completes through `/v1/messages`, and existing anthropic/chat tests remain green

## Guidance for Tester

**Tests to create:**
- **Permanent:** Expand `tests/test_claude_proxy.py` with focused request/response transform coverage from Steps 1–2 and a mocked two-request E2E tool loop. The E2E mock must inspect the first upstream request for flat tools and full Responses input, return a `function_call`, verify the client receives Anthropic `tool_use` plus `stop_reason: "tool_use"`, inspect the second request for matching `function_call` and `function_call_output`, then return final text and verify `stop_reason: "end_turn"`.
- **Temporary:** Create `tests/temp/test_response_mode_tool_roundtrip_integration.py`. It must start an isolated proxy with isolated config, state, keys, and trace files; target `apinebula-codex` in response mode; obtain the provider URL, model, and API key only from environment variables; define a deterministic harmless tool; force or clearly prompt the first turn to call it; submit the matching tool result; assert a non-empty final answer; and assert response-mode dispatch with no transform-failure/tool-degradation events. It must print bounded diagnostics with no request/response bodies or credentials. Create all artifacts under a dedicated temporary directory and remove keys, config, state, trace, and the directory in `finally` even on assertion failure, interruption, or upstream error. Explicitly clear inherited `PROXY_LOG_ALL`, never pass `--all`, restrict the temporary keys file to the current Windows user with `icacls` for the duration of the run, verify the keys path is absent after cleanup, and remove the test source after a successful live run.

**Live-test credential contract:**
- Required environment variables: `PROXY_E2E_RESPONSE_URL`, `PROXY_E2E_RESPONSE_MODEL`, `PROXY_E2E_RESPONSE_API_KEY`.
- The tester must request the API key only when ready to execute the live test. The key must never appear in command arguments, source, config retained after cleanup, trace bodies, reports, or terminal output. After the run, the tester must unset all three `PROXY_E2E_RESPONSE_*` variables from the test process/session and verify cleanup even when the E2E fails.
- Missing variables produce an explicit SKIP for an ordinary local run. During final verification, a skip is not success: the tester reports the missing prerequisite and waits for the user-provided environment value.

**Tests to investigate for retirement:**
- Planner candidates:
  - `tests/test_claude_proxy.py::test_anthropic_to_response_basic` — its plain-string `input == "hi"` assertion must become an exact full-history message-item assertion while preserving sampling/system field checks.
  - `tests/test_claude_proxy.py::test_anthropic_to_response_multiple_user_messages` — its current last-user-only expectation encodes the behavior being replaced; revise it into a full-history assertion rather than deleting response-mode coverage.
  - `tests/test_claude_proxy.py::test_anthropic_to_response_no_user_message` — re-evaluate its `input: ""` expectation against full-history conversion; retain a malformed/empty-history test if still meaningful.
  - `tests/test_claude_proxy.py::test_response_to_anthropic_multiple_output` — its current first-message-only expectation conflicts with ordered mixed output processing; revise rather than delete.
  - `tests/test_claude_proxy.py::test_response_mode_e2e_json` — its upstream `input == "three"` assertion encodes last-user-only behavior; revise it to assert the full item list or fold its coverage into the new mocked two-request tool-loop E2E.
- Tester may identify additional candidates during test work.

**Retirement procedure:** For each candidate, verify the test exercises behavior being replaced. If obsolete, revise or delete it and note the disposition in the tester report. If still valid, document why. Do not retain assertions for the former single-turn/first-message-only limitation.

**Regression command:** `python tests/test_claude_proxy.py`. Baseline before implementation: 180 passed, 0 failed on 2026-08-31.

## Summary

The proxy currently sends `apinebula-codex` through `/v1/responses`, but its response-mode converters deliberately discard tools and conversation history and ignore upstream `function_call` items. Claude Code therefore receives valid text-only messages ending in `end_turn`, so commands and review launches finish without executing tools.

This plan replaces that limited conversion with a buffered, stateless two-way adapter:

```text
Anthropic Messages request
  tools + full text/tool history
        │
        ▼
OpenAI Responses request (stream:false)
  message | function_call | function_call_output items
        │
        ▼
OpenAI Responses output
  message/output_text | function_call
        │
        ▼
Anthropic response
  text | tool_use, with end_turn | tool_use
```

Each proxy request still contains the complete Anthropic conversation, so the converter reconstructs the corresponding Responses input items on every turn; no server-side response ID or conversation state is introduced. This is simpler and matches the proxy's existing stateless architecture.

**Alternatives considered:**
- Switch `apinebula-codex` to chat mode: rejected because Codex and this provider use the Responses API, and it would avoid rather than fix the broken mode.
- Add Responses SSE conversion now: rejected by user choice; buffered conversion restores tool execution without the substantially larger streaming state machine.
- Use `previous_response_id`: rejected because it would add provider-side conversational state, complicate retries and routing, and is unnecessary when Claude Code already sends complete history.

**Out of scope:** Responses SSE; images; thinking/reasoning item round trips; hosted/server tools; provider-specific extensions; changing retry behavior; changing `count_tokens` behavior.

## Repo Mode

Public

*Detected at plan creation. Determines: plan archival path, commit-message content, staged files.*

## Document Overrides

| Document | Rule Overridden | Reason |
|----------|----------------|--------|

## Rollback

Abort before live E2E if either structural verifier or the permanent suite fails. Abort the live E2E on timeout, malformed tool conversion, missing cleanup evidence, or any credential-exposure concern. Back out only the scoped `server.py` changes in `_anthropic_to_response`, `_response_to_anthropic`, and their response-mode call site; restore the revised permanent tests to their pre-plan assertions if the implementation is abandoned. No config, template, key-format, or persisted-state migration is involved. Re-run the 180-test baseline after backout.

## Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| Responses item ordering or call-ID pairing is wrong | Tool results cannot be associated with calls, especially for parallel tools | Preserve transcript order and IDs; unit-test mixed and parallel calls plus a two-turn mocked E2E |
| A malformed upstream call is exposed as a valid empty tool | Claude Code may execute the wrong action or hang on `tool_use` | Require a named call, ID, and non-empty JSON-object arguments; degrade visibly and suppress `tool_use` stop reason when no valid call survives |
| Live provider differs from the standard Responses schema | Mock tests pass but `apinebula-codex` still fails | Run the temporary environment-authenticated E2E and inspect only bounded, secret-free diagnostics before completion |
| Full history increases request size | Long sessions consume more upstream input tokens than the current lossy last-turn conversion | This is required for correctness; retain the existing proxy body cap and avoid adding server-side duplicated state |

## Proposed Changes

Each step includes verification checks tagged with confidence.
`(auto)` = mechanical, coder self-verifies. `(scripted)` = deterministic multi-step, coder runs the provided script.

1. **Step 1:** Replace last-user-only Responses request conversion with ordered text and client-tool history, flat function tools, and tool-choice mapping.
   → coder verify (auto): `_anthropic_to_response` still forces buffered mode and emits flat Responses function-tool definitions
   → coder verify (scripted): `python ./tmp/verification/2026-08-31-fix-response-mode-tool-roundtrip-step1.py`
   → tester verify: focused request-conversion tests pass for normal, parallel, mixed, and malformed cases

2. **Step 2:** Convert Responses `function_call` output items into Anthropic `tool_use` blocks with strict argument validation and correct stop reasons.
   → coder verify (auto): valid function calls produce `tool_use`; no valid function call means `stop_reason` is not `tool_use`
   → coder verify (scripted): `python ./tmp/verification/2026-08-31-fix-response-mode-tool-roundtrip-step2.py`
   → tester verify: focused response-conversion tests pass for text, calls, mixed output, parallel output, and degradation cases

3. **Step 3:** Wire trace context into the buffered response-mode transform without changing retry, error-passthrough, chat, or anthropic behavior.
   → coder verify (auto): production call passes trace context, request transform remains outside retries, and response mode still forces `stream: false`
   → tester verify: permanent mocked two-turn tool-loop E2E passes and the complete permanent suite reports zero failures

4. **Step 4:** Run a temporary live two-turn tool-loop E2E against `apinebula-codex`, then remove the temporary test.
   → tester verify: with the three `PROXY_E2E_RESPONSE_*` variables supplied, the first turn returns a valid Anthropic `tool_use`, the second turn accepts its result and returns non-empty final text, isolated trace diagnostics contain response dispatch and no transform failure, `PROXY_LOG_ALL` was cleared and `--all` absent, the temporary keys/config/state/trace paths are absent after cleanup, and `tests/temp/test_response_mode_tool_roundtrip_integration.py` is absent afterward

5. **Step 5:** Synchronize user and maintainer documentation after the implementation and tests are final.
   → Evidence: after the required removal approval, `git diff -- README.md CLAUDE.md` shows the approved single-turn/text-only claims replaced and buffered Responses tool/history mappings plus the remaining SSE limitation documented; `grep` finds no stale claim that response mode is single-turn or unusable for tools; `CLAUDE.md` links the archived plan

## Guidance for Planner

Documentation tasks you will execute yourself (not the coder):

- **Doc files to create/update:** `README.md`, `CLAUDE.md`
- **When:** After coder and tester finish, using the final implementation and reports
- **What to sync:** Replace response mode's single-turn/text-only description with full buffered text/tool history conversion; document flat Responses function tools, `function_call`/`function_call_output` mapping, `tool_use` stop behavior, malformed-argument degradation, and the remaining `stream: false`/no-Responses-SSE limitation. Update the test-count statement if the permanent suite count changes. Add `plans/2026-08-31-fix-response-mode-tool-roundtrip.md` to `CLAUDE.md`'s Documentation list after archival. Do not document the temporary live test after it is deleted; retain only general guidance that credentials must be supplied via environment variables if a live-provider check is described.
- **Required removal approval:** Before editing `CLAUDE.md`, quote to the user the exact stale claims proposed for removal or replacement—at minimum the response-mode `single-turn`/last-user-only statements and any obsolete test-count statement—and obtain explicit approval. If approval is not received, add accurate adjacent clarification without deleting the old text and leave documentation reconciliation open; do not mark Final Results complete.

## History

| Date | Event | Conclusion | Dismissed |
|------|-------|------------|-----------|
| 2026-08-31 | Review r2 | [Review r2 report](../reports/2026-08-31-fix-response-mode-tool-roundtrip-review-2026-08-31-r2.json) — 0 Critical, 0 Warning, 1 Suggestion. Doc sync verified; suite re-run 198/198. Ready to commit. | [review-r2-temperature-validation](.) — single Suggestion (temperature passthrough type validation), non-blocking. |
| 2026-08-31 | Review | [Review report](../reports/2026-08-31-fix-response-mode-tool-roundtrip-review-2026-08-31.json) — 0 Critical, 2 Warnings, 3 Suggestions, 4 Hunches. Gate passes. Core round-trip logic (call-ID correlation, ordered items, stop-reason rules, degradation paths) traced clean end-to-end. | [review-unvalidated-role](.) — each Warning/Suggestion/Hunch acknowledged as non-blocking edge-case hardening; scope fits a follow-up pass. |
| 2026-08-31 | Spec revision (/update-plan) | Coder and tester report back. Coder: Steps 1-3 complete, build passes, no issues filed. Tester: 198/198 green (18 new permanent, 5 revised, all retirement candidates revised). Temp live E2E passed against apinebula-codex (response mode, model gpt-5.4): turn 1 returned tool_use, turn 2 received final answer; trace clean; temp test self-removed; credentials verified absent from disk. Temperature passthrough issue resolved. All plan steps verified. | — |
| 2026-08-31 | Mega-audit | [Mega-audit](../reports/2026-08-31-fix-response-mode-tool-roundtrip-mega-audit-2026-08-31.json) found 2 High, 19 Medium, and 22 Low items. Fixed call-ID correlation, item/role shapes, named-tool validation, malformed-call stop handling, zero-argument/dict arguments, trace context, affected-test inventory, rollback, credential cleanup, documentation approval, and plan indexing. No High findings remain. | Low findings acknowledged in the linked report. |
| 2026-08-31 | Initial plan | User selected buffered Responses tool round trips and a temporary live-provider E2E; Responses SSE remains out of scope. | — |

## Plan Metadata

```json
{
  "plan_id": "2026-08-31-fix-response-mode-tool-roundtrip",
  "steps": [
    "Step 1: Replace last-user-only Responses request conversion",
    "Step 2: Convert Responses function_call output items",
    "Step 3: Wire trace context into buffered response-mode transforms",
    "Step 4: Run and remove a temporary live tool-loop E2E",
    "Step 5: Synchronize user and maintainer documentation"
  ],
  "coder_files": [
    "src/claude_retry_proxy/server.py"
  ],
  "tester_files": [
    "tests/test_claude_proxy.py",
    "tests/temp/test_response_mode_tool_roundtrip_integration.py"
  ],
  "doc_files": [
    "README.md",
    "CLAUDE.md"
  ],
  "verification_scripts": [
    "./tmp/verification/2026-08-31-fix-response-mode-tool-roundtrip-step1.py",
    "./tmp/verification/2026-08-31-fix-response-mode-tool-roundtrip-step2.py"
  ],
  "repo_mode": "Public",
  "document_overrides": []
}
```

## Audit Accumulation

| Counter | Value | Last Updated |
|---------|-------|--------------|
| issues_resolved_since_audit | 1 | 2026-08-31 |
| steps_changed_since_audit | 0 | 2026-08-31 |
| files_changed_since_audit | 0 | 2026-08-31 |

## Documentation

- `README.md` is the user-facing source for provider-mode behavior and limitations.
- `CLAUDE.md` is the maintainer-facing source for transformation rules, architecture, gotchas, test count, and future-work status.
- `doc/test-catalog.html` is absent in this repository, so no catalog-based duplicate test review was possible; direct test-file inspection found the existing response-mode unit and mocked E2E coverage listed above.

## Final Results

**Status:** COMPLETED — 2026-08-31

| What | Detail |
|------|--------|
| Files changed | `src/claude_retry_proxy/server.py` (+342/-22), `tests/test_claude_proxy.py` (+723/-20) |
| Test results | 198/198 passed (18 new permanent tests, 5 legacy tests revised, +18 from the 180 baseline) |
| Issues resolved | 1 (response-temperature-passthrough) |
| Open issues | 0 |

**What was implemented:**

- **Buffered Responses request conversion:** `_anthropic_to_response` now emits the full conversation as ordered Responses input items: text messages become `{type:"message", role, content:[{type:"input_text", text}]}`; `tool_use` blocks become flat `function_call` items with `call_id`, `name`, and `json.dumps(arguments, allow_nan=False)`; `tool_result` blocks become `function_call_output` items only when their `tool_use_id` matches a preceding emitted call (orphan/duplicate results are dropped). Empty or unsupported-only turns are coalesced to preserve role alternation. Anthropic `tools` definitions are converted to the flat Responses function-tool shape (`type`, `name`, `description`, `parameters`); `tool_choice` is mapped only against validated emitted tool names. `stream: false` is still forced. `temperature` and `top_p` are passed through unchanged.
- **Buffered Responses response conversion:** `_response_to_anthropic` inspects every output item in order without an early break. `message`/`output_text` items map to Anthropic text blocks; each valid `function_call` item maps to a `tool_use` block (`call_id`→`id`, `name`→`name`, parsed `arguments`→`input`). `{}` is accepted as a valid zero-argument input; already-parsed dictionaries are accepted directly. Malformed arguments produce a user-visible failure placeholder and a metadata-only `tool_args_parse_failure` trace event. `stop_reason` is `"tool_use"` when at least one valid function call was emitted; `null` when calls were seen but all degraded; otherwise `"end_turn"` (completed) or `null` (other status).
- **Wiring:** `request_id`, `mode`, `provider`, and `tier` are threaded into the request transform. The transformed request is built once before the retry loop. Non-2xx bodies pass through untransformed. Chat and anthropic mode behavior is unchanged.
- **Live E2E:** A temporary test against `apinebula-codex` (response mode, model `gpt-5.4`) verified a two-turn tool loop: turn 1 returned a valid `tool_use` with `stop_reason: "tool_use"`, and turn 2 accepted the tool result and returned the final answer with `stop_reason: "end_turn"`. The test source self-removed and all credentials were verified absent from disk.

**Out of scope (documented):**
- Responses SSE streaming (still forces `stream: false`)
- Image, thinking, and server-tool round trips
- Provider-specific extensions

**Review history:**
- 1 mega-audit (pre-implementation): 2 High, 19 Medium, 22 Low. All High + Medium fixed.
- 1 review (post-implementation): 0 Critical, 2 Warnings, 3 Suggestions, 4 Hunches. Core round-trip logic traced clean end-to-end. Warnings/Suggestions are non-blocking edge-case hardening items.
- 198/198 tests pass, 0 open issues
