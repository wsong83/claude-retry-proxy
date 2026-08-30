# Plan: Fix Chat-Mode SSE Tool Calls
**Project:** D:\proj\claude-retry-proxy
**Plan ID:** 2026-08-30-fix-chat-sse-tool-calls
**Created:** 2026-08-30

## Issue Log

| Issue | Status | Found | Resolved | Resolved By |
|-------|--------|-------|----------|-------------|
| [streaming-tool-call-deltas](../reports/defer-issue-streaming-tool-call-deltas.json) | Resolved | 2026-08-29 | 2026-08-30 | tester |

## Guidance for Coder

**Files to modify:** `src/claude_retry_proxy/server.py`

Implement only the Chat Completions SSE response path. Do not change the already-working non-streaming request/response transforms, Anthropic-mode streaming, response mode, image handling, or provider configuration.

**Required stream state:**

- Keep the existing scalar content-block state for `thinking` and `text`, where at most one scalar block is open.
- Add tool-call state keyed by the upstream OpenAI `delta.tool_calls[].index`. Each state records the non-empty string `id`, non-empty string function `name`, assigned Anthropic content-block index, pending argument fragments received before metadata is complete (capped at 64 KB per tool), whether `content_block_start` was emitted, and whether the block was closed.
- Cap tracked tool indexes at 32, cap concurrently open tool blocks at 32; on overflow, drop the entry through the coalesced malformed trace event and never claim `tool_use` for that tool.
- Allocate Anthropic indices from a single monotonic counter incremented **only on `content_block_start` emission** (never on close), guaranteeing contiguity (0, 1, 2, …). Never reuse the upstream tool index as the emitted Anthropic index.
- Before emitting the first tool block, close the current thinking/text block and set `current_block_type = None`. After the first tool block is open, any scalar delta (thinking, text) is dropped with a counted diagnostic in the coalesced trace event — tool blocks are never interleaved with re-opened scalar blocks.
- Tool blocks are closed in ascending Anthropic-index order. Tool indices are stored in a separate ordered collection from the scalar `open_blocks` stack so scalar close pops never touch tool blocks.
- For each tool-call delta, merge metadata without replacing a valid existing `id` or `name` with empty/malformed values. If a later delta on an existing index presents a valid-but-different `id` or `name`, treat the entry as malformed (coalesced trace, no `tool_use` emitted). Once both `id` and `name` are available, emit exactly one `content_block_start` with `content_block: {type: "tool_use", id, name, input: {}}`, then emit buffered and subsequent non-empty string argument fragments as `content_block_delta` events with `delta: {type: "input_json_delta", partial_json: fragment}`.
- **Intra-frame ordering:** within any frame, all delta fragments (reasoning, content, tool_calls) are fully processed before the `finish_reason` path finalizes. This preserves the last argument fragment that shares the finish chunk.
- At a normal `finish_reason: "tool_calls"`, close every started tool block exactly once in ascending Anthropic-index order, validate accumulated argument strings via `json.loads` (on parse failure, degrade to null stop reason and log the coalesced diagnostic), then emit `message_delta.stop_reason: "tool_use"` if at least one valid, parseable tool block was emitted. Retain `null` degradation in all other cases: zero tool blocks emitted, all blocks malformed, no tool deltas observed, or accumulated arguments unparseable.
- At a non-`"tool_calls"` finish reason (`"stop"`, `"length"`, `"content_filter"`) arriving while tool blocks are open, route through the single idempotent close path, map the finish reason normally (never `tool_use`), and log the coalesced trace event.
- At EOF, truncation, or response-size cutoff: close any emitted blocks ascending, emit `message_delta` with `stop_reason: null` when any valid tool block was emitted (incomplete, not runnable), `stop_reason: "end_turn"` when no tool deltas were observed, and emit the coalesced malformed-tool trace event if counts are non-zero.
- **Explicitly update the two live degradation sites** (L2229–2230: `if tool_calls_seen and sr == "tool_use": sr = None`; L2276–2278: `sr = "end_turn"; if tool_calls_seen: sr = None`). Replace the `tool_calls_seen` flag with an `emitted_tool_use` flag set only when at least one complete, parseable tool_use block was written. Force `stop_reason: None` when `tool_calls_seen` is true but `emitted_tool_use` is false.
- `isinstance`-guard every `delta.tool_calls` field access (index, id, name, function dict, arguments); malformed shapes (non-dict `tool_calls`, null/string entries, non-dict `function`, non-list `delta.tool_calls`) are logged in the coalesced trace event and the frame is skipped without propagating.
- Non-empty argument fragments with missing/out-of-range/duplicate-ambiguous index are dropped, counted in the coalesced trace event; streams that dropped any non-empty fragments do not claim `tool_use` at finish.
- Log one bounded metadata-only trace event per stream for malformed/dropped streamed tool-call entries. Include `request_id` and fixed reason strings + integer counts; never include `tool_name`, `tool_id`, `arguments`, `partial_json`, fragment text, free-form error strings, or request/response bodies. Emit from the shared terminal path (normal finish, EOF, cap cutoff) whenever counts are non-zero.
- Remove `tool_calls_seen` logic that unconditionally discards tool calls and nulls a valid `tool_use` stop reason. Remove now-unused scalar state such as `first_content_block` if it has no remaining purpose.

**Step-by-step with verification:** each coder step has a mechanical `(auto)` check. Tester owns all behavioral verification and test execution.

1. Refactor `_stream_chat_sse_to_anthropic()` around shared monotonic block-index allocation, scalar-block closing, and per-tool state keyed by OpenAI tool index.
   → coder verify (auto): `server.py` contains one per-request tool-state mapping indexed by validated upstream tool index; tool state contains `id`, `name`, assigned Anthropic index, pending arguments, started, and closed state; no code uses the upstream tool index as an emitted Anthropic index

2. Convert `delta.tool_calls` into Anthropic `tool_use` starts and `input_json_delta` fragments, including metadata/argument fragmentation and parallel calls.
   → coder verify (auto): `_stream_chat_sse_to_anthropic()` emits the literal block/delta types `tool_use` and `input_json_delta`; each tool start uses `input: {}`; argument payloads appear only under `partial_json`; the old branch that only sets `tool_calls_seen = True` is absent

3. Finalize tool blocks and terminal stop reasons safely on normal finish and degraded termination paths.
   → coder verify (auto): normal `finish_reason == "tool_calls"` can produce `stop_reason == "tool_use"` only after at least one tool block start; emitted tool blocks are closed through a single idempotent close path; EOF/truncation cannot claim `tool_use`; no remaining comment says tool deltas are untransformed

4. Add coalesced trace diagnostics for streamed tool deltas that cannot form valid Anthropic tool blocks.
   → coder verify (auto): the new trace event includes `request_id` and bounded counts/reasons, does not include `arguments`, `partial_json`, or request/response bodies, and is emitted once per affected stream rather than once per fragment

## Guidance for Tester

**Tests to create:**

- **Permanent:** `test_chat_sse_single_tool_call_fragmented_arguments` — realistic OpenAI chunks split tool `id`/`name` metadata and JSON arguments across frames; assert one Anthropic `tool_use` start, ordered `input_json_delta` fragments, one matching stop, and terminal `stop_reason: "tool_use"`.
- **Permanent:** `test_chat_sse_parallel_tool_calls_interleaved` — two tool indexes arrive in the same and later chunks with interleaved argument fragments; assert distinct monotonically increasing and contiguous Anthropic indices (0, 1, 2, …), correct ID/name/arguments association, ascending close order, and exactly one start/stop per tool.
- **Permanent:** `test_chat_sse_reasoning_text_then_tool_call` — reasoning and/or text deltas precede a tool call; assert each scalar block closes before tool blocks start and all indices are unique and increasing.
- **Permanent:** `test_chat_sse_tool_call_metadata_buffering` — arguments arrive before complete ID/name metadata; assert fragments are retained and emitted in original order after the start becomes valid.
- **Permanent:** `test_chat_sse_malformed_tool_call_degrades` — missing/non-string index, ID, name, function object, or arguments never emits an invalid `tool_use`; assert coalesced metadata-only trace diagnostics (no `tool_name`, `tool_id`, or fragment text in the event) and a null stop reason when no valid tool survives.
- **Permanent:** `test_chat_sse_mixed_valid_and_malformed_tool_calls` — a valid parallel call survives alongside a malformed entry; assert the valid block is emitted and normal `tool_calls` finish maps to `tool_use`, while the malformed entry is diagnosed without contaminating it.
- **Permanent:** `test_chat_sse_tool_call_eof_without_finish` — an upstream stream ends after tool deltas without a normal finish chunk; assert open blocks close ascending, `message_stop` is emitted, `stop_reason` is `null` when valid tool blocks were emitted and `"end_turn"` when no tool deltas were observed, and the coalesced malformed trace event is emitted.
- **Permanent:** `test_chat_sse_non_tool_calls_finish_with_tool_blocks` — a `"length"` or `"stop"` finish reason arrives while tool blocks are open; assert blocks close ascending, finish reason maps normally (never `tool_use`), and the coalesced trace event fires.
- **Permanent:** `test_chat_sse_scalar_delta_after_tool_blocks` — reasoning or content delta after the first tool block start; assert scalar delta is dropped with a counted diagnostic, no new scalar `content_block_start` is emitted, and tool blocks remain un-contaminated.
- **Permanent:** `test_chat_sse_final_fragment_in_finish_frame` — the last argument fragment shares the `finish_reason: "tool_calls"` frame; assert the fragment is emitted before tool blocks close and `stop_reason: "tool_use"` is claimed.
- **Permanent:** `test_chat_sse_no_deltas_tool_calls_finish` — `finish_reason: "tool_calls"` with zero tool-call deltas observed; assert `stop_reason` is `null` (never `tool_use`), not `"end_turn"`.
- **Permanent:** `test_chat_sse_unparseable_arguments_at_close` — valid metadata and normal `tool_calls` finish, but accumulated argument string is not valid JSON; assert `stop_reason` is `null` (not `tool_use`), and the coalesced trace event fires.
- **Permanent:** `test_chat_sse_conflicting_metadata` — a later delta on an existing index presents a valid-but-different `id` or `name`; assert the entry is treated as malformed (coalesced trace, no `tool_use` emitted for that index).
- **Permanent:** `test_chat_sse_fragments_missing_index` — non-empty argument fragments arrive without an index after a tool block was started; assert fragments are dropped, counted in the coalesced trace event, and `stop_reason` is `null` at finish.
- **Permanent:** `test_chat_sse_malformed_delta_shapes` — `tool_calls` as a list of strings, `tool_calls` as a dict (not a list), `delta` non-dict with `tool_calls` present; assert no exception propagates, the frame is skipped, and the coalesced trace event fires.
- **Permanent:** `test_chat_sse_pending_buffer_cap_exceeded` — a tool sends argument fragments exceeding 64 KB with id/name never completing; assert bounded behavior, one trace event on EOF, and `stop_reason` is not `tool_use`.
- **Permanent:** `test_chat_sse_too_many_parallel_tools` — 33+ tool indexes arrive; assert overflow entries are dropped through the coalesced trace event and `stop_reason` is `null`.
- **Permanent:** `test_chat_mode_streamed_tool_command_e2e` — through the test proxy and mock chat upstream, use the trace-derived request shape (`stream: true`, tools present) and return a realistic streamed `Bash` or `Read` call; assert the downstream Anthropic stream accumulates a runnable tool-use block with the exact ID, name, input object, and `stop_reason: "tool_use"`.

**Tests to update:**

- Replace `test_chat_sse_tool_calls_stop_reason_null` and its `ALL_TESTS` registry entry. The old test intentionally preserves the defect by requiring null when tool deltas are present. The replacement coverage must assert: (a) valid tool deltas produce `stop_reason: "tool_use"`, (b) malformed/no-valid-tool deltas degrade to `null`, and (c) `finish_reason: "tool_calls"` with zero tool deltas observed maps to `stop_reason: null` (the old control case at lines 9286–9315 is superseded — `tool_use` is no longer claimed when no blocks were emitted).

**Temporary tests:** None. The trace regression and protocol edge cases are permanent compatibility coverage.

**Tests to investigate for retirement:**

- Planner candidate: `tests/test_claude_proxy.py::test_chat_sse_tool_calls_stop_reason_null` — retire/replace because its asserted degradation is superseded by full streamed tool conversion.
- Tester may identify additional candidates during test work.

**Retirement procedure:** Verify the candidate exercises only the intentionally removed degradation. Replace it with the valid-tool and malformed-tool cases above; record the replacement in the tester session report.

**Behavioral verification:**

- Run focused chat SSE tests with the custom runner, including every new/updated test.
- Run `python tests/test_claude_proxy.py`; all tests must pass. Do not use pytest: this suite records failures in a module-level list that only the custom runner checks.
- Confirm existing thinking-only, thinking→text, plain-text, usage-only, malformed-frame, EOF, response-size-cap, and client-disconnect streaming tests remain green.
- Inspect parsed downstream SSE, not raw substring presence: verify event order, integer indices, per-tool fragment association, exactly-once starts/stops, and terminal stop reason.

## Summary

Chat-mode requests from Claude Code are streamed. The proxy already converts tool definitions and historical tool turns correctly, but `_stream_chat_sse_to_anthropic()` currently discards live OpenAI `delta.tool_calls`, then degrades `finish_reason: "tool_calls"` to a null Anthropic stop reason. The traced `/resolve-plan` and deferred-issue requests therefore returned HTTP 200 without a runnable assistant `tool_use` turn.

The fix is a localized SSE protocol conversion in `server.py`:

```text
OpenAI Chat SSE delta.tool_calls[index]
             │
             ├─ first complete id + function.name
             │      └─ Anthropic content_block_start(tool_use)
             ├─ function.arguments fragments
             │      └─ Anthropic content_block_delta(input_json_delta)
             └─ finish_reason: tool_calls
                    └─ close tool blocks → stop_reason: tool_use
```

Tool state is keyed by OpenAI tool index so parallel and interleaved deltas cannot mix. Anthropic block indices come from one monotonic allocator shared with thinking/text blocks. Incomplete or malformed streams remain conservative: close emitted blocks, log bounded metadata-only diagnostics, and do not falsely advertise runnable tool use.

**Alternative rejected:** force chat mode to non-streaming or buffer the complete response. This would avoid delta conversion but regress time-to-first-token behavior and undermine Claude Code's normal streaming path.

**Out of scope:** image content mapping, Responses-mode streaming, request-level thinking-budget mapping, changes to non-streaming tool conversion, and unrelated untracked files (`.codegraph/`, `recent-5.log`). The existing `image-content-blocks-chat-mode` deferred issue remains open.

## Repo Mode

Public

*Detected at plan creation. Determines: plan archival path, commit-message content, staged files.*

## Document Overrides

| Document | Rule Overridden | Reason |
|----------|----------------|--------|
| `CLAUDE.md` — chat-mode SSE tool-call deltas are not transformed and stop reason is degraded to null | Valid streamed tool calls will be transformed and terminate with `tool_use` | This plan resolves the documented deferred issue. |
| `README.md` — Tool-use SSE deltas are not transformed in chat-mode streaming | Valid streamed tool calls will be fully mapped to Anthropic tool-use SSE | User-facing limitation becomes obsolete after verification. |

## Rollback

The change is confined to `_stream_chat_sse_to_anthropic()` in `server.py` (~L2026–2279) plus one retired test and its `ALL_TESTS` registry entry. No config, CLI, or env surface is touched. Rollback is a two-file git revert of the commit that implements this plan. The old degradation behavior (tool deltas seen → stop reason null) is removed; the `stop_reason: null` path is retained only for malformed/truncated tool metadata where no valid tool block was emitted.

## Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| Parallel OpenAI tool calls interleave argument fragments | Tool input can be assigned to the wrong call | Key state by validated upstream index and test interleaving across frames. |
| Thinking/text/tool transitions reuse or misorder Anthropic indices | Claude Code may reject or mis-accumulate the stream | Use one monotonic allocator with contiguous indices (incremented only on `content_block_start`, never on close); assert exact index sets in tests. |
| Incomplete metadata or truncated JSON is presented as runnable tool use | Client executes malformed input or hangs | Buffer until ID/name exist; require normal `tool_calls` finish before advertising `tool_use`; validate accumulated arguments via `json.loads` at tool close and degrade to null if unparseable; retain null degradation for no-valid-tool cases. |
| Diagnostic logging captures tool arguments | Sensitive tool inputs leak to trace | Log metadata-only bounded counts and fixed reason strings (no `tool_name`, `tool_id`, fragment text, or free-form error strings); tests assert argument fragments are absent from trace events. |
| Unbounded pending-fragment buffer or tool-index tracking | Memory exhaustion from a misbehaving upstream | Cap pending fragments per tool at 64 KB (mirroring `MAX_EVENT_BUFFER`); cap tracked tool indexes at 32; on overflow, drop the tool entry through the coalesced malformed trace event and never claim `tool_use`. |
| Parallel tool blocks exhaust the Anthropic block-index space | Gaps or index overflow | Cap open tool blocks at 32; on overflow, close emitted blocks and degrade to null stop reason. |
| Malformed delta shapes (non-dict `tool_calls`, non-list `delta.tool_calls`, null/string entries) | Unhandled exception mid-stream, client hangs without terminal | `isinstance`-guard every field access; wrap per-frame delta handling so unexpected shapes are logged in the coalesced trace event and the frame is skipped without propagating. |
| Upstream-controlled `id`/`name` injected into SSE frames | SSE frame injection or event-type spoofing | All synthesized events (including `tool_use` `id`/`name` and `partial_json` fragments) are emitted through the existing `write()` → `_sse_event()` → `json.dumps` path, which is the documented SSE injection guard; `id` and `name` are validated as non-empty strings before embedding. |

## Proposed Changes

1. **Step 1:** Update `src/claude_retry_proxy/server.py` to synthesize Anthropic tool-use SSE from OpenAI `delta.tool_calls`, with per-index state, contiguous monotonic Anthropic indices, capped pending-fragment buffers (64 KB per tool, 32 tracked indexes, 32 concurrent open blocks), guarded metadata/argument parsing, parallel-call support, intra-frame ordering (deltas before finish), ascending-index close order, JSON validation of accumulated arguments at tool close, and conservative degraded termination for all non-`tool_calls` finish reasons, EOF/truncation, unparseable arguments, malformed delta shapes, dropped fragments, and conflicting metadata.
   → coder verify (auto): all mechanical checks in Guidance for Coder pass by source inspection including: per-tool state mapping indexed by validated upstream tool index; tool state contains `id`, `name`, assigned Anthropic index, capped pending arguments, started, and closed state; no upstream tool index is used as an emitted Anthropic index; allocator increments only on `content_block_start`; `isinstance` guards on every `delta.tool_calls` field access; `json.loads` validation at tool close; capped buffers and index counts; ascending close order; separate tool-index collection from scalar `open_blocks`; scalar-delta-after-tools is dropped with diagnostic
   → tester verify: focused single, fragmented, parallel, transition, malformed, mixed, EOF, non-tool-calls-finish, and scalar-after-tools stream tests pass with exact parsed event assertions

2. **Step 2:** Replace the degradation-locking SSE tool-call test and add permanent protocol and trace-regression coverage in `tests/test_claude_proxy.py`.
   → tester verify: each listed permanent test is registered in `ALL_TESTS`, the obsolete null-on-valid-tool assertion is absent, the no-deltas-`tool_calls`-finish control case is explicitly covered, and the custom runner reports every focused case passed

3. **Step 3:** Run the complete behavioral regression suite and confirm non-tool chat streaming plus other provider modes remain unchanged.
   → tester verify: `python tests/test_claude_proxy.py` exits 0 with all tests passed; session report records total/pass/fail counts and confirms no new skipped or pre-existing failures

4. **Step 4:** Reconcile project documentation after implementation and behavioral verification.
   → Evidence: `git diff --check` exits 0; `README.md` and `CLAUDE.md` no longer claim valid tool-call SSE is discarded, both still identify image mapping as deferred, the stale CLAUDE.md gotcha line ~310 is updated to remove "and streaming tool call deltas," and documented test count matches the tester report

## Guidance for Planner

Documentation tasks to execute after coder and tester finish:

- **Doc files to create/update:** `CLAUDE.md`, `README.md`
- **When:** after implementation and full-suite verification
- **What to sync:**
  - Replace the chat-mode streaming limitation with the implemented mapping: `delta.tool_calls` → `content_block_start(tool_use)` + `input_json_delta` + `content_block_stop`, normal `tool_calls` finish → `stop_reason: "tool_use"`.
  - Document conservative malformed/truncated-stream degradation and the new metadata-only trace event.
  - In `CLAUDE.md` Gotchas → Provider mode dispatch (line ~310): remove "and streaming tool call deltas" from the deferred-claim sentence so it reads only "Image content blocks are deferred."
  - Remove `streaming-tool-call-deltas` from `## Unresolved Deferred Issues` and Future Work after its Issue Log row is resolved.
  - Keep `image-content-blocks-chat-mode` open and unchanged.
  - Update the full-suite test count to the tester's verified result.
  - Do not edit or stage the user's untracked `recent-5.log` or `.codegraph/` directory.

## History

| Date | Event | Conclusion | Dismissed |
|------|-------|------------|-----------|
| 2026-08-30 | Mega-audit | 1 High, 18 Medium, 13 Low. High: degradation-site update (oversight). Medium categories: 5 defect-tracer (terminal branches, EOF states, scalar-after-tools, intra-frame order, buffer cap), 4 edge-case (scalar-transition, malformed shapes, index contiguity, JSON validation), 3 conflict (close order, zero-deltas corner, control case), 1 oversight (rollback), 1 security (memory caps), 1 test-impact (breakage), 1 completeness (control case), 1 boundary-checker (stale gotcha). All High + Medium fixed. | [annotated findings](reports/2026-08-30-fix-chat-sse-tool-calls-mega-audit-2026-08-30.json) |
| 2026-08-30 | Coder remediation (R1–R4) | All four source edits applied, build passes, no issues filed. | [coder-2](reports/2026-08-30-fix-chat-sse-tool-calls-coder-2026-08-30-2.json) |
| 2026-08-30 | Tester remediation (4 tests) | 180/180 passed, 0 failed. All four remediation corners verified (empty-sentinel EOF → end_turn, mixed parseable/unparseable → null, non-dict args → null, frame-dropped guard → null). | [tester-2](reports/2026-08-30-fix-chat-sse-tool-calls-tester-2026-08-30-2.json) |
| 2026-08-30 | Reviewer completed | 2 Warning + 3 Suggestion, no Critical. All five accepted for remediation (see Review Remediation section). | [review](reports/2026-08-30-fix-chat-sse-tool-calls-review-2026-08-30.json) |
| 2026-08-30 | Coder completed (Step 1) | All four auto-checks pass, build clean, no issues filed. Two plan ambiguities resolved (incomplete-metadata counting at terminal, overflow degrades entire stream). | — |
| 2026-08-30 | Tester completed (Steps 2–3) | 176/176 passed, 0 failed, 18 new permanent tests, 1 degradation test replaced, E2E streamed Bash tool reconstructs runnable tool_use. | — |
| 2026-08-30 | Initial plan | Trace and source analysis isolated command/tool failure to the already-deferred Chat SSE tool-call conversion; scope explicitly limited to streamed tool calls. | — |

## Plan Metadata

```json
{
  "plan_id": "2026-08-30-fix-chat-sse-tool-calls",
  "steps": [
    "Step 1: Update server.py to synthesize Anthropic tool-use SSE with capped buffers, contiguity, intra-frame ordering, ascending close, JSON validation, and all degraded-terminal rules",
    "Step 2: Replace degradation test and add permanent coverage (17 tests + E2E)",
    "Step 3: Run complete behavioral regression suite",
    "Step 4: Reconcile project documentation"
  ],
  "coder_files": ["src/claude_retry_proxy/server.py"],
  "tester_files": ["tests/test_claude_proxy.py"],
  "doc_files": ["CLAUDE.md", "README.md"],
  "verification_scripts": [],
  "repo_mode": "Public",
  "document_overrides": [
    "CLAUDE.md: chat-mode SSE tool-call deltas are not transformed and stop reason is degraded to null (Reason: this plan resolves the deferred issue)",
    "README.md: Tool-use SSE deltas are not transformed in chat-mode streaming (Reason: the limitation becomes obsolete after verification)"
  ]
}
```

## Audit Accumulation

| Counter | Value | Last Updated |
|---------|-------|--------------|
| issues_resolved_since_audit | 0 | 2026-08-30 |
| steps_changed_since_audit | 0 | 2026-08-30 |
| files_changed_since_audit | 0 | 2026-08-30 |

## Documentation

- Trace evidence: request IDs `4e1b78be-0ec3-4ca6-8664-f3285715989d`, `23e9368f-4df1-4cda-8341-4577a7c82985`, and `58f8475a-6e3a-4fd1-9660-77987d718adf` in `~/.claude/logs/proxy-trace.jsonl`.
- Deferred issue: `./tmp/reports/defer-issue-streaming-tool-call-deltas.json`.
- Originating mode plan: `./plans/2026-08-27-support-three-endpoint-modes.md`.
- Related completed plans: `./plans/2026-08-29-fix-chat-mode-request-transform.md`, `./plans/2026-08-29-fix-chat-mode-thinking-roundtrip.md`.
- Baseline on 2026-08-30: `python tests/test_claude_proxy.py` — 159 passed, 0 failed.

## Review Remediation

Reviewer report: [2026-08-30-fix-chat-sse-tool-calls-review-2026-08-30.json](../reports/2026-08-30-fix-chat-sse-tool-calls-review-2026-08-30.json) — 2 Warning, 3 Suggestion, no Critical. All five accepted.

| # | Severity | Finding | Fix |
|---|----------|---------|-----|
| R1 | Warning (Design) | EOF terminal keys stop-reason off `tool_calls_seen`, which is set on an empty `tool_calls: []` sentinel frame → yields `null` instead of `end_turn` | Only set `tool_calls_seen` on a **non-empty** `delta.tool_calls` field. Add an EOF + `tool_calls: []` test. |
| R2 | Warning (Correctness) | Finish claim condition never checks `unparseable_arg_count` — one parseable + one unparseable parallel tool still claims `tool_use` | Add `unparseable_arg_count == 0` to the finish claim condition. Add a mixed parseable+unparseable finish test. |
| R3 | Suggestion (Correctness) | Close-time `json.loads` accepts any parseable JSON (`"123"`, `"null"`), not just dicts | Require a dict result from `json.loads`; count non-dict as unparseable. Add a non-dict-args-at-close test. |
| R4 | Suggestion (Design) | Start-cap overflow branch leaves `state["pending"]` uncleared (unlike every other drop path) | Clear `state["pending"]` and `state["pending_bytes"]` in the start-failure branch. |
| R5 | Suggestion (Testability) | `frame_dropped` guard, mixed parseable+unparseable finish, and EOF + `tool_calls: []` sentinel are untested | Add tests for all three corners. |

### Guidance for Coder (remediation)

`src/claude_retry_proxy/server.py` only. Four mechanical edits:

1. **R1** (~L2375): change `if delta.get("tool_calls") is not None: tool_calls_seen = True` so `tool_calls_seen` is set only when `delta.get("tool_calls")` is truthy (non-empty). An empty `tool_calls: []` sentinel must not mark the stream as having observed tool deltas.
2. **R2** (~L2451): add `and unparseable_arg_count == 0` to the finish-claim condition (alongside `valid > 0`, `dropped_fragment_count == 0`, `overflow_tool_count == 0`, and `not (frame_dropped and emitted_tool_use)`). One unparseable started tool must degrade the whole stream to `null`.
3. **R3** (~L2202): in `close_open_tool_blocks`, capture `json.loads` result and require `isinstance(parsed, dict)` to count `valid`; a non-dict parse result (number/string/bool/null) increments `unparseable_arg_count` instead.
4. **R4** (~L2287-2290): in the start-failure branch (`if not start_tool_block(state)`), also clear `state["pending"]` and `state["pending_bytes"]` before `continue`, consistent with the other drop paths.

### Guidance for Tester (remediation)

`tests/test_claude_proxy.py` only. Four new permanent tests:

1. **R1** `test_chat_sse_eof_empty_tool_calls_sentinel` — stream sends `tool_calls: []` on the first chunk then EOF with no finish; assert `stop_reason: "end_turn"` (not `null`), no `tool_use` emitted.
2. **R2** `test_chat_sse_mixed_parseable_unparseable_finish` — two parallel started tools, one valid JSON args + one unparseable args, normal `tool_calls` finish; assert `stop_reason` is `null` (not `tool_use`).
3. **R3** `test_chat_sse_non_dict_arguments_at_close` — valid metadata + normal `tool_calls` finish, but accumulated args parse to a non-dict (e.g. `"123"`); assert `stop_reason: "null"` and `unparseable_arg_count == 1`.
4. **R5** `test_chat_sse_frame_dropped_guard` — an oversized non-first frame (>64 KB, no delimiter) mid-tool-stream on a stream that also emits tool blocks; assert `stop_reason` is `null` with `frame_dropped: 1` in the trace event.

Register each in `ALL_TESTS`; run the custom runner then the full suite (`python tests/test_claude_proxy.py`).

## Final Results

- **Status:** COMPLETED
- **Completed:** 2026-08-30
- **Files changed:** `src/claude_retry_proxy/server.py` (+316/-98), `tests/test_claude_proxy.py` (+1176/-98)
- **Test results:** 180/180 passed, 0 failed, 0 skipped (exit 0)
- **Issues resolved:** 1 ([streaming-tool-call-deltas](../reports/defer-issue-streaming-tool-call-deltas.json))
- **Tests added:** 22 new permanent tests (18 initial + 4 remediation), 1 degradation-locking test replaced
- **Review findings fixed:** 5/5 (2 Warning + 3 Suggestion), verified by 4 new tests
- **What changed:** `_stream_chat_sse_to_anthropic()` now synthesizes Anthropic `tool_use` SSE from OpenAI `delta.tool_calls` with per-index state, contiguous monotonic block indices, capped buffers (64 KB per tool, 32 tracked tools, 32 concurrent open blocks), parallel/interleaved support, intra-frame ordering, `json.loads` dict-only validation at close, and conservative degraded termination for all non-`tool_calls` finish reasons, EOF/truncation, unparseable arguments, malformed shapes, dropped fragments, empty-list sentinel, and mixed parseable/unparseable parallel tools. A coalesced `chat_sse_tool_degradation` trace event (metadata-only, no arguments/IDs) fires once per affected stream.
- **Coder reports:** [initial](reports/2026-08-30-fix-chat-sse-tool-calls-coder-2026-08-30.json), [remediation](reports/2026-08-30-fix-chat-sse-tool-calls-coder-2026-08-30-2.json)
- **Tester reports:** [initial](reports/2026-08-30-fix-chat-sse-tool-calls-tester-2026-08-30.json), [remediation](reports/2026-08-30-fix-chat-sse-tool-calls-tester-2026-08-30-2.json)
- **Review:** [2026-08-30-fix-chat-sse-tool-calls-review-2026-08-30.json](reports/2026-08-30-fix-chat-sse-tool-calls-review-2026-08-30.json)
