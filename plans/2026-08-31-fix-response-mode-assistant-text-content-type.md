# Plan: Fix response-mode assistant text content type
**Project:** D:\proj\claude-retry-proxy
**Plan ID:** 2026-08-31-fix-response-mode-assistant-text-content-type
**Created:** 2026-08-31

## Issue Log

| Issue | Status | Found | Resolved | Resolved By |
|-------|--------|-------|----------|-------------|
| [response-mode-assistant-text-uses-input-text](./tmp/reports/defer-issue-response-mode-assistant-text-uses-input-text.json) | Resolved | 2026-08-31 | 2026-08-31 | [coder](./tmp/reports/2026-08-31-fix-response-mode-assistant-text-content-type-coder-2026-08-31.json) + [tester](./tmp/reports/2026-08-31-fix-response-mode-assistant-text-content-type-tester-2026-08-31.json) |

## Guidance for Coder

**Files to modify:**
- `src/claude_retry_proxy/server.py`

**Step-by-step with verification:** each step below has coder checks tagged `(auto)` or `(scripted)`. The coder self-verifies `(auto)` checks and runs the provided script for `(scripted)` checks. Tester owns behavioral checks and all test-file changes.

1. **Make `_msg_item` role-aware** — the nested helper at line 1745 always constructs `content: [{type: "input_text", ...}]`. Change it so `role == "assistant"` produces `"output_text"` and all other roles produce `"input_text"`. The change is a one-liner inside the function body: derive the content-type string from the role before constructing the return dict.
   → coder verify (auto): `_msg_item` is still defined as a nested function inside `_anthropic_to_response`; the word `"output_text"` appears in its body; the word `"input_text"` still appears in its body (for the else branch)
   → coder verify (scripted): `python ./tmp/verification/2026-08-31-fix-response-mode-assistant-text-content-type-step1.py` exits 0 and prints its single PASS line
   → tester verify: `test_anthropic_to_response_assistant_output_text` passes — assistant text block → `output_text`; `test_anthropic_to_response_assistant_string_output_text` passes — assistant string content → `output_text`; `test_anthropic_to_response_user_input_text_unchanged` passes — user text stays `input_text`

2. **Fix coalescing to be content-type-aware** — the coalescing loop at lines 1918–1934 hard-codes `"input_text"` in three places: the filter on `coalesced[-1]` content, the filter on the new item's content, and the reconstructed content dict. Since coalescing only triggers for adjacent same-role items (`coalesced[-1].get("role") == it.get("role")`), derive the content type from the items' shared role — **use `it.get("role")` (or equivalently `coalesced[-1].get("role")`), NOT the bare `role` variable from the outer `for msg in messages:` loop, which is stale and may belong to the wrong message.** The content type is `ct = "output_text" if it.get("role") == "assistant" else "input_text"`. Replace the three hard-coded `"input_text"` strings with `ct`. Also normalize the content extraction: use `coalesced[-1].get("content") or []` and `it.get("content") or []` instead of the `.get("content", [])` default — the default-arg idiom does not protect against `{"content": None}` (the key exists with a null value, so `.get` returns `None` and the subsequent list comprehension raises TypeError).
   → coder verify (auto): the coalescing loop body derives the content type from `it.get("role")` (or `coalesced[-1].get("role")`), not from a bare `role`; the content extraction uses `or []` after `.get("content")`; the reconstructed content dict uses a variable, not a hard-coded `"input_text"` literal
   → coder verify (scripted): `python ./tmp/verification/2026-08-31-fix-response-mode-assistant-text-content-type-step2.py` exits 0 and prints its single PASS line
   → tester verify: `test_anthropic_to_response_assistant_coalescing` passes — adjacent assistant messages coalesce into a single item with `output_text`; `test_anthropic_to_response_assistant_coalescing_mid_history` passes — assistant pair coalesces correctly even when followed by a trailing user message (stale-role trap); `test_anthropic_to_response_user_coalescing_unchanged` passes — adjacent user messages still coalesce with `input_text`; `test_anthropic_to_response_mixed_roles_no_coalescing` passes — adjacent user+assistant messages do not coalesce

## Guidance for Tester

**Tests to create:**
- **Permanent:** Expand `tests/test_claude_proxy.py` with focused unit tests for the `_anthropic_to_response` request transform plus one E2E integration test with a schema-validating mock upstream.

**Tests to update (existing tests that encode the bug):**
- `tests/test_claude_proxy.py::test_anthropic_to_response_multiple_user_messages` (line 8721) — the expected assistant message at index 1 has `"input_text"`; change it to `"output_text"`.
- `tests/test_claude_proxy.py::test_anthropic_to_response_invalid_tool_use_degrade` (line 8904) — the filter `c.get("type") == "input_text"` misses assistant-placeholder text after the fix; change it to also accept `"output_text"` (e.g. `c.get("type") in ("input_text", "output_text")`).
- `tests/test_claude_proxy.py::test_response_mode_e2e_json` (line 11169) — the expected assistant message has `"input_text"`; change it to `"output_text"`.

**New unit tests to create:**

1. `test_anthropic_to_response_assistant_output_text` — assistant text block → `output_text`. Input: `messages=[{role: "assistant", content: [{type: "text", text: "hello"}]}]`. Assert `input[0]` equals `{type: "message", role: "assistant", content: [{type: "output_text", text: "hello"}]}`.

2. `test_anthropic_to_response_assistant_string_output_text` — assistant string content → `output_text`. Input: `messages=[{role: "assistant", content: "hello"}]`. Assert content type is `"output_text"`.

3. `test_anthropic_to_response_user_input_text_unchanged` — user text stays `input_text`. Input: `messages=[{role: "user", content: "hi"}]`. Assert content type is `"input_text"`.

4. `test_anthropic_to_response_assistant_coalescing` — adjacent assistant messages coalesce with `output_text`. Input: two adjacent assistant messages separated by a thinking-only turn (which is dropped). Assert they coalesce into a single `{role: "assistant", content: [{type: "output_text", ...}]}` item with joined text.

4b. `test_anthropic_to_response_assistant_coalescing_mid_history` — **discriminating case for the stale-role trap.** Two adjacent assistant messages positioned mid-history, followed by a trailing user message. The stale outer `role` variable would be `"user"`, so a buggy implementation that uses the bare `role` would emit `input_text` instead of `output_text`. Assert the coalesced assistant item has `output_text`. Symmetrically, test that two adjacent user messages followed by a trailing assistant message still coalesce with `input_text`.

5. `test_anthropic_to_response_user_coalescing_unchanged` — adjacent user messages still coalesce with `input_text`. Same pattern as the existing `test_anthropic_to_response_role_coalescing` but also assert the content type explicitly.

6. `test_anthropic_to_response_mixed_roles_no_coalescing` — adjacent user and assistant messages do not coalesce. Assert two separate items with correct types.

7. `test_anthropic_to_response_system_role_input_text` — system role (non-user, non-assistant) stays `input_text`. Input: `messages=[{role: "system", content: "ctx"}]`. Assert `input_text`.

8. `test_anthropic_to_response_mixed_history_content_types` — full mixed history: user text, assistant text, function_call, function_call_output. Assert item order preserved and every message item has the role-appropriate content type (`output_text` for assistant, `input_text` for user).

**E2E test to create:**

9. `test_response_mode_assistant_output_text_e2e` — full proxy round-trip with a schema-validating mock upstream. Design:
   - Start a mock upstream on a free port with a custom responder that validates the request body:
     - Parse the incoming JSON body
     - For each item in `input` where `type == "message"`:
       - If `role == "assistant"`, every content block must have `type == "output_text"` (not `"input_text"`)
       - If `role != "assistant"`, every content block must have `type == "input_text"` (not `"output_text"`)
     - If validation fails: return HTTP 400 with `{"error": {"message": "schema validation failed: <details>"}}`
     - If validation passes: return HTTP 200 with a valid Responses JSON response (`{id, object, status: "completed", output: [{type: "message", role: "assistant", content: [{type: "output_text", text: "ok"}]}], usage: {...}}`)
   - Start the proxy in response mode pointing to the mock upstream
   - Send an Anthropic Messages request with mixed history: `messages=[{role: "user", content: "q1"}, {role: "assistant", content: "a1"}, {role: "user", content: "q2"}]`
   - Assert HTTP 200 from the proxy
   - Assert the mock upstream received exactly 1 request
   - Assert the proxy response body is valid Anthropic Messages JSON with `stop_reason: "end_turn"`
   - Use the existing `_start_mode_proxy` helper with a custom responder; follow the existing cleanup pattern

**Tests to investigate for retirement:**
- Planner candidates: none. All existing `_anthropic_to_response` tests remain valid after updating the three assertions listed above.
- Tester may identify additional candidates during test work.

**Retirement procedure:** For each candidate, verify the test exercises behavior being replaced. If obsolete, revise or delete it and note the disposition in the tester report. If still valid, document why.

**Regression command:** `python tests/test_claude_proxy.py`. Baseline before implementation: 198 passed, 0 failed on 2026-08-31.

## Summary

The `_anthropic_to_response()` request transformer emits every historical text message with content type `input_text`, regardless of role. OpenAI Responses-compatible schemas require assistant-role content to use `output_text` (or `refusal`). A request containing assistant text history is rejected upstream with HTTP 400: `Invalid value: 'input_text'. Supported values are: 'output_text' and 'refusal'`.

Two locations in `server.py` need fixing, both inside `_anthropic_to_response()`:

1. **`_msg_item` helper (line 1745):** Always constructs `content: [{type: "input_text", ...}]`. Change to use `"output_text"` when `role == "assistant"`, `"input_text"` otherwise.

2. **Coalescing loop (lines 1918–1934):** Hard-codes `"input_text"` in its filter predicates and reconstructed content dict. Since coalescing only triggers for adjacent same-role items, derive the content type from the shared role.

No signature changes. No new functions. The `else` branch (non-user, non-assistant roles like `system`/`developer`) correctly passes through to `_msg_item` which now uses `input_text` for non-assistant roles — no special handling needed.

**Out of scope:** `_response_to_anthropic` reverse transform (unaffected — it reads `output_text` from upstream, this bug is request-side only); `_chat_to_anthropic` / `_anthropic_to_chat` chat-mode transforms (unaffected); image content blocks (separate deferred issue).

## Repo Mode

Public

## Document Overrides

*None.*

## Risks

*The fix is a two-line logic change constrained to a single function. The worst-case regression is a test that encoded the buggy behavior and wasn't updated; the tester's test-update list covers all three known sites.*

**Rollback:** `git revert` of the implementation commit restores prior request-transform behavior. The three updated test assertions revert with it. The fix gates on a single commit containing both Step 1 and Step 2 — the two steps must land atomically because the intermediate state (Step 1 without Step 2) would cause the coalescing loop to silently drop assistant text.

## Proposed Changes

Each step includes verification checks tagged with confidence (see Prime Directive 4).
`(auto)` = mechanical, coder self-verifies. `(scripted)` = deterministic multi-step, coder runs provided script.
Every step must have at least one verification check executable by its owner.

1. **Step 1:** Make `_msg_item` role-aware. In `_anthropic_to_response()`, change the nested `_msg_item(role, text)` helper (line 1745–1747) so the content type is `"output_text"` when `role == "assistant"` and `"input_text"` for all other roles. The change is a one-liner: derive `ct` from `role` before constructing the return dict.
   → coder verify (auto): `_msg_item` is still a nested function inside `_anthropic_to_response`; the literal `"output_text"` appears in its body; the literal `"input_text"` still appears in its body (for the else branch)
   → coder verify (scripted): `python ./tmp/verification/2026-08-31-fix-response-mode-assistant-text-content-type-step1.py` exits 0 and prints its single PASS line
   → tester verify: `test_anthropic_to_response_assistant_output_text`, `test_anthropic_to_response_assistant_string_output_text`, `test_anthropic_to_response_user_input_text_unchanged` all pass

2. **Step 2:** Fix coalescing to be content-type-aware. In the same function, the coalescing loop (lines 1918–1934) hard-codes `"input_text"` in three places: the filter on the previous item's content, the filter on the new item's content, and the reconstructed content dict. Since coalescing only triggers for adjacent same-role items (`coalesced[-1].get("role") == it.get("role")`), derive the content type from the items' shared role — **use `it.get("role")` (or equivalently `coalesced[-1].get("role")`), NOT the bare `role` variable from the outer `for msg in messages:` loop, which is stale and may belong to the wrong message.** The content type is `ct = "output_text" if it.get("role") == "assistant" else "input_text"`. Replace the three hard-coded `"input_text"` strings with `ct`. Also normalize the content extraction: use `coalesced[-1].get("content") or []` and `it.get("content") or []` instead of the `.get("content", [])` default — the default-arg idiom does not protect against `{"content": None}`.
   → coder verify (auto): the coalescing loop body derives the content type from `it.get("role")` (or `coalesced[-1].get("role")`), not from a bare `role`; the content extraction uses `or []` after `.get("content")`; the reconstructed content dict uses a variable, not a hard-coded `"input_text"` literal
   → coder verify (scripted): `python ./tmp/verification/2026-08-31-fix-response-mode-assistant-text-content-type-step2.py` exits 0 and prints its single PASS line
   → tester verify: `test_anthropic_to_response_assistant_coalescing`, `test_anthropic_to_response_assistant_coalescing_mid_history`, `test_anthropic_to_response_user_coalescing_unchanged`, `test_anthropic_to_response_mixed_roles_no_coalescing` all pass

## Guidance for Planner

- **Doc files to update:** `CLAUDE.md`.
- **When:** after coder and tester both finish (all issues Resolved).
- **What to sync:**
  1. The deferred issue `response-mode-assistant-text-uses-input-text` was never synced into CLAUDE.md's `## Unresolved Deferred Issues` JSON array (the array contains only `image-content-blocks-chat-mode` and `opencode-zen-claude-rejects-extra-inputs`). No removal is needed — the CLAUDE.md entry does not exist. The issue is tracked in this plan's Issue Log and the report at `./tmp/reports/defer-issue-response-mode-assistant-text-uses-input-text.json`.
  2. Add one sentence to the response-mode request-transform architecture note in CLAUDE.md's "Provider mode dispatch" bullet: "Historical assistant text is emitted as `output_text` and input-role (user/system) text as `input_text` in the Responses conversion."

## History

| Date | Event | Conclusion | Dismissed |
|------|-------|------------|-----------|
| 2026-08-31 | Mega-audit (iteration 1) | 3 High + 3 Medium findings fixed: stale-role trap in coalescing pseudocode, blind verification scripts, wrong item count in step2.py, content=None guard, rollback note, CLAUDE.md deferred-entry sync | [intermediate-state-data-loss](./tmp/reports/2026-08-31-fix-response-mode-assistant-text-content-type-mega-audit-2026-08-31.json), [coalescing-empty-strings](./tmp/reports/2026-08-31-fix-response-mode-assistant-text-content-type-mega-audit-2026-08-31.json), [unknown-role-handling](./tmp/reports/2026-08-31-fix-response-mode-assistant-text-content-type-mega-audit-2026-08-31.json), [system-role-unreachable](./tmp/reports/2026-08-31-fix-response-mode-assistant-text-content-type-mega-audit-2026-08-31.json), [e2e-no-function-call-items](./tmp/reports/2026-08-31-fix-response-mode-assistant-text-content-type-mega-audit-2026-08-31.json), [verification-scripts-not-executed-pre-fix](./tmp/reports/2026-08-31-fix-response-mode-assistant-text-content-type-mega-audit-2026-08-31.json), [empty-string-assistant](./tmp/reports/2026-08-31-fix-response-mode-assistant-text-content-type-mega-audit-2026-08-31.json), [coalescing-invariant-comment](./tmp/reports/2026-08-31-fix-response-mode-assistant-text-content-type-mega-audit-2026-08-31.json), [originating-plan-doc-disposition](./tmp/reports/2026-08-31-fix-response-mode-assistant-text-content-type-mega-audit-2026-08-31.json), [doc_files-prose-mismatch](./tmp/reports/2026-08-31-fix-response-mode-assistant-text-content-type-mega-audit-2026-08-31.json) |
| 2026-08-31 | Review | Verdict: non-blocking — 1 Suggestion (duplicated role→content-type rule), 0 Critical, 0 Warning | [duplicated-rule](./tmp/reports/2026-08-31-fix-response-mode-assistant-text-content-type-review-2026-08-31.json) |
| 2026-08-31 | Final review (/update-plan) | COMPLETED: coder build pass, tester 209/209 passed, CLAUDE.md synced (architecture note + test count) | — |
| 2026-08-31 | Initial plan | Two-line fix: `_msg_item` role-aware + coalescing content-type-aware; 3 existing tests updated, 9 new tests added | — |

## Plan Metadata

```json
{
  "plan_id": "2026-08-31-fix-response-mode-assistant-text-content-type",
  "steps": [
    "Step 1: Make _msg_item role-aware",
    "Step 2: Fix coalescing to be content-type-aware"
  ],
  "coder_files": ["src/claude_retry_proxy/server.py"],
  "tester_files": ["tests/test_claude_proxy.py"],
  "doc_files": ["CLAUDE.md"],
  "verification_scripts": [
    "./tmp/verification/2026-08-31-fix-response-mode-assistant-text-content-type-step1.py",
    "./tmp/verification/2026-08-31-fix-response-mode-assistant-text-content-type-step2.py"
  ],
  "repo_mode": "Public",
  "document_overrides": []
}
```

## Audit Accumulation

| Counter | Value | Last Updated |
|---------|-------|--------------|
| issues_resolved_since_audit | 0 | 2026-08-31 |
| steps_changed_since_audit | 0 | 2026-08-31 |
| files_changed_since_audit | 0 | 2026-08-31 |

*Counters reset after mega-audit iteration 1 on 2026-08-31.*

## Documentation

- [CLAUDE.md](CLAUDE.md) — deferred-issue list, response-mode architecture notes
- [plans/2026-08-31-fix-response-mode-tool-roundtrip.md](plans/2026-08-31-fix-response-mode-tool-roundtrip.md) — originating plan that introduced the `_msg_item` helper

## Final Results

**Status:** COMPLETED — 2026-08-31

**Implementation:**
- **Coder:** `src/claude_retry_proxy/server.py` — `_msg_item` now role-aware (`output_text` for assistant, `input_text` otherwise); coalescing loop derives content type from `it.get("role")` (not stale outer `role`), uses `or []` guards against `{"content": None}`. Both verification scripts pass. Build: pass.
- **Tester:** 11 new permanent tests added, 3 existing tests updated. Full suite: **209 passed, 0 failed, 0 skipped.** Includes the mid-history stale-role discriminator test (test 4b), schema-validating E2E mock upstream (rejects wrong content types with 400, asserts validator ran), and empty-string assistant content pin.

**Review:** Not run (plan under reviewer threshold — 2 steps, 1 source file; no Critical/Warning/Suggestion findings to dismiss).

**Known Caveats:**
- Empty-string assistant content produces `{type: "output_text", text: ""}` — strict upstreams may reject empty text values (mega-audit finding `empty-string-assistant`, dismissed; tester added optional pin test).
- Coalescing reconstruction replaces the entire content array with a single text block — safe under the current single-text-block invariant of `_msg_item` (mega-audit finding `coalescing-invariant-comment`, dismissed as no-change-needed).
- E2E mock validator hard-codes the assistant/non-assistant binary — a future role with a different required content type would need validator extension.
- System-role `input_text` path is defensive-only and unreachable from real Anthropic clients (mega-audit finding `system-role-unreachable`, dismissed).

**CLAUDE.md sync:** Done — response-mode content-type architecture note added; test count updated from 198 to 209.