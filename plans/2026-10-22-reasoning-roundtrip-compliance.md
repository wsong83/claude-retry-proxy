# Plan: Make chat-mode bodies comply with the DeepSeek reasoning round-trip
**Plan ID:** 2026-10-22-reasoning-roundtrip-compliance
**Created:** 2026-10-22

> **Revision 2 (2026-10-23):** revised against the pre-implementation mega-audit
> (`./tmp/reports/2026-10-22-reasoning-roundtrip-compliance-mega-audit-2026-10-23.json`,
> 10 High / 24 Medium / 28 Low). Every High and Medium is addressed below; the
> dispositions are in `## History`.

## Immediate Actions

**Revision 2026-10-24 — pre-commit.** Both rounds are done, all three Issue Log rows are
`Resolved`, the delta re-review is in (0 Critical / 0 Warning / 1 Suggestion, fixed in place) and
`## Final Results` is written, so every coder, tester and planner directive is spent and removed.
One action remains, and it is the operator's call to start it.

**Planner:**
- On the operator's word, run `/update-and-commit`: it retires the session, review and
  verification artifacts to the dated quarantine, deletes the resolved flake report, writes the
  `## Commit Log`, and commits the 18 changed files.
- The `claude-config` commit of the same `models.json` key stays the operator's (recorded in
  `## Final Results`).

## Issue Log

| Issue | Status | Found | Resolved | Resolved By |
|-------|--------|-------|----------|-------------|
| [review-reasoning-placeholder-flag-not-cleared](./tmp/reports/2026-10-22-reasoning-roundtrip-compliance-review-2026-10-23.json) — `reasoning_is_placeholder` is never cleared when a real `thinking` block supersedes the redacted placeholder, so a `[redacted_thinking, thinking, tool_use]` turn forwards the real reasoning text yet is classified as a placeholder: the event reports `real=0, empty=0, placeholder=1` and fires on a request that filled nothing blank, which `doc/trace-log.html` and `doc/provider-modes.html` describe as impossible. Reviewer Suggestion (Correctness), reproduced. Fixed by **Step 8**. | Resolved | 2026-10-24 | 2026-10-24 | tester |
| [review-e2e-unflagged-leg-cannot-detect-leak](./tmp/reports/2026-10-22-reasoning-roundtrip-compliance-review-2026-10-23.json) — the e2e test's `send("haiku")` leg cannot observe the policy leaking beyond its `(provider, model)` key, which its docstring and `doc/test-catalog.html:318` claim it verifies: the haiku tier's model carries no learned selection, so the transform emits no field for it even if the policy matched by provider alone. Reviewer Suggestion (Testability). Tester-lane repair this round. | Resolved | 2026-10-24 | 2026-10-24 | tester |
| [review-delist-repaired-bytes-claim](./tmp/reports/2026-10-22-reasoning-roundtrip-compliance-review-2026-10-23.json) — `test_reasoning_delist_on_none_success`'s docstring claims the *repaired* bytes served the client, but its fixture's single assistant turn already carries thinking and the mock serves every later call regardless of content, so the claim cannot fail. Reviewer Suggestion (Testability). Tester-lane repair this round. | Resolved | 2026-10-24 | 2026-10-24 | tester |
| [preexisting-compat-single-retry-flake](./tmp/reports/2026-10-22-reasoning-roundtrip-compliance-preexisting-compat-single-retry-flake.json) — `test_compat_single_retry_global` asserted an interleaving-dependent `>= 5` rescue count; provenance pinned by `git log -S` to commit 92b5977 (plan `2026-10-22-reasoning-field-credit-rescue`), reproduced 2/5 on the pristine pre-change tree. Fixed in this plan's tester lane: the count assertion became "≥1 event, all scoped to `reasoning_field`", with the mechanism recorded in a comment. | Resolved | 2026-10-23 | 2026-10-23 | tester |

## Guidance for Coder

**Files to modify:**

- `./src/claude_retry_proxy/transforms_chat.py`
- `./src/claude_retry_proxy/compat.py`
- `./src/claude_retry_proxy/config.py`
- `./src/claude_retry_proxy/server.py`
- `./src/claude_retry_proxy/templates/models.json`

**Step-by-step with verification:** each step below carries coder checks tagged `(auto)` or `(scripted)`. Run the scripted checks with `python3 ./tmp/verification/<name>.py` from the project root.

**Do not:** change `_anthropic_to_chat`'s positional parameter order (`reasoning_always` is appended keyword-defaulted); remove the `reasoning` field option or alter `COMPAT_REASONING_SELECTIONS`; touch the response direction (`_chat_to_anthropic`); write anything under `tests/`. `tests/` belongs to the tester; `CLAUDE.md`, `README.md` and `doc/**` belong to the planner.

## Guidance for Tester

**Files to modify (module per test):**

- `./tests/test_chat_transform.py`
- `./tests/test_compat.py`
- `./tests/test_config_split.py`
- `./tests/test_mode_dispatch.py`
- `./tests/test_admin.py` — the extended carry-across test (see below)
- `./tests/_harness.py` — only if the e2e mode-dispatch test needs a helper (2026-10-23: the previous round added one here)

**Register every new test in its module's `ALL_TESTS` list** — `doc/test-catalog.html` states the aggregator never picks up an unregistered test, so one that is not listed simply never runs.

**Tests to create (prefer extending the existing owner over a parallel test):**

- **Permanent, in `test_chat_transform.py`:** rewrite `test_anthropic_to_chat_messages_mixed_text_and_tool_use` (L217) to the collapsed expectation **in place** — do NOT add a second test for the same turn shape (audit `test-impact`, High: a parallel `..._text_and_tool_use_single_message` would duplicate it).
- **Permanent, in `test_chat_transform.py`:** extend the existing selection-matrix test `test_chat_transform_emits_only_selected_field` (L311) with a `reasoning_always` axis: real text where a thinking block exists, `""` where none does, inert without any tool-call turn, inert when the selection is `none`.
- **Permanent, in `test_chat_transform.py`:** `test_anthropic_to_chat_nan_placeholder_with_valid_tool_use` — a malformed `tool_use` input alongside a valid one yields one assistant message whose `content` carries the placeholder text and whose `tool_calls` carries the surviving call (the collapse applies here too; the planner updates `doc/provider-modes.html`'s two-message paragraph).
- **Permanent, in `test_chat_transform.py`:** `test_anthropic_to_chat_injection_trace_counts` — the event reports `real`, `empty` and `placeholder` counts and fires only when `empty + placeholder > 0`; a redacted-thinking placeholder is counted as `placeholder`, never `real`.
- **Permanent, in `test_config_split.py`:** add `reasoning_roundtrip` rows to the existing bad-shapes table (`test_models_doc_bad_shapes_collapse_to_value_error`, L191) — non-object value, a value other than `"always"` — each error naming the key; and extend `test_merged_load_with_optional_keys` with the pass-through plus `reasoning_roundtrip_models` resolution (a `"provider/model"` key resolves to that pair; malformed resolves to empty). Do NOT add a standalone resolution test.
- **Permanent, in `test_config_split.py`:** a `validate_config` case that a `reasoning_roundtrip` key naming an unknown provider, or a known provider with an unknown model, is rejected (mirroring the `extra_request_headers` unknown-provider rule).
- **Permanent, in `test_compat.py`:** `test_reasoning_present_gates_on_demanding_turn` — the bare demanding turn over a reasoned history is False; a reasoned demanding turn is True; reasoning with no tool-call turn anywhere is False; totality guards hold. Include the divergence case: an assistant message *after* the tool-call turn (a later assistant turn without `tool_use`) must not change the verdict — the algorithm scans past it.
- **Permanent, in `test_compat.py`:** a test that a rescue pass's **forwarded body** carries the injected field (real where available, `""` otherwise) — focus on the repaired bytes; do NOT re-assert credit-inertness (that is `test_reasoning_rescued_success_does_not_teach`'s job), and do NOT assert per-pass `candidate` labels without also asserting the effective field.
- **Permanent, in `test_admin.py`:** extend the existing carry-across test (L922) so a `/admin/api/switch` preserves `reasoning_roundtrip` and a `/admin/api/reload` installs a changed value — the repo's existing regression test for exactly this mechanism.
- **Permanent, in `test_mode_dispatch.py`:** an end-to-end chat-mode request with the policy set for its provider carries the field on every assistant message of the forwarded body.

**FIXTURE MIGRATION — required before the credit tests can pass (audit High ×2):**
`_reasoning_request()` (`test_compat.py:168-187`) builds an assistant turn with `thinking` + `text` and **no `tool_use`**, so under Step 5's narrowed gate the body is gate-false, `reasoning_active` is False, no credit or selection moves, and every credit/switch assertion fails. Give the fixture a demanding turn (assistant `thinking` + `tool_use`, answered by a trailing `tool_result`) or add a `demanding=True` variant and use it in the tests that depend on learning. Enumerate and re-baseline at least: `test_reasoning_rescued_success_does_not_teach` (L3235), the credit/switch tests around it, and any test asserting `sent == [None, None]`.

**Tests to investigate for retirement / rewrite:**
- Rewrite (not delete), all in `tests/test_chat_transform.py`, because they pin the two-message split:
  - `test_anthropic_to_chat_messages_transform` (L28; expected list at 46-53)
  - `test_anthropic_to_chat_messages_mixed_text_and_tool_use` (L217)
  - `test_anthropic_to_chat_messages_interleaved_thinking_tool_use` (L273 — also pins the default-selection no-echo behavior; keep that axis)
  - `test_anthropic_to_chat_integration` (L1047; expectation at 1078-1087)
  - `test_anthropic_to_chat_nan_placeholder_with_valid_tool_use` (L1257)
- Explicitly NOT a candidate: `test_chat_to_anthropic_reasoning_content_with_tool_calls` (L1493) — response direction, unchanged.
- Tester may identify further candidates during test work, and must re-run the whole of `test_chat_transform.py` after Step 1.

## Summary

**Problem.** `opencode-go-chat` (chat mode → `deepseek-v4.1-flash`) intermittently returns `400 [invalid_request_error] The reasoning_content in the thinking mode must be passed back to the API.`, killing the client session. DeepSeek's rule: *for turns that do perform tool calls, `reasoning_content` must be fully passed back in all subsequent requests*. Our transform violates it two ways: the **split** emits `[assistant(text), assistant(content:null, tool_calls)]` and deliberately leaves the tool_calls message clean, and turns where the vendor emitted no reasoning carry no field anywhere.

**Evidence (probe, 2026-10-22).** Synthetic content-free bodies sent direct to `opencode-go-chat`, 2 sessions × 2 rounds. Bare bodies 400'd 4/8; the *same shapes* carrying `reasoning_content: ""` were 200 8/8, paired within the same session and round (A 400 → B 200, E 400 → F 200, twice each). The collapsed shape (`content` string + `tool_calls`) was accepted 8/8. An accumulated 4-turn history changed nothing. The vendor checks **presence, not content**. Supporting analysis: the client never drops thinking (verified off the wire), and the proxy never drops post-tool reasoning (`scalar_after_tools_dropped` = 0 across ~80k trace rows).

**Approach.** Four parts:

```
client body ──> [C] credit gate: demanding turn only
       │
       └──> transform: [A] collapse the split  (all chat mode)
                      [B] always-present field (policy-flagged provider/model pairs)
                      └──> upstream
       └──> on a matched complaint: [D] rescue repairs + re-rolls
```

**A. Collapse the split (all chat mode).** One assistant message per Anthropic assistant turn: `content` (joined text, or `null` when the turn has none), `tool_calls` when present, and the reasoning field on that same message. Probe-validated (C/D, 8/8). The path that emits a placeholder for a malformed `tool_use` input collapses the same way — that is a deliberate change to behavior `doc/provider-modes.html` currently documents as two messages, and the planner updates that paragraph. The no-text/no-tool_calls branch keeps today's `""` (`transforms_chat.py:242`) — unchanged, and pinned by the shape script.

**B. Always-present field (policy-scoped).** New `models.json` key `reasoning_roundtrip`: a **`"provider/model"` → policy** map, default absent (off). Keyed at provider *and* model because the provider is heterogeneous — the live catalog gives `opencode-go-chat` eighteen models, and the policy must not reach `mimo-v2.6-flash` (the haiku tier) on no evidence. Under `"always"`, once the transformed list contains an assistant message with `tool_calls`, **every** assistant message carries the selected field — the real thinking text where a thinking block exists, `""` where none does. Inert when the learned selection is `none` (no field name to write; that state means the learner concluded no echo is wanted, and Part C is what keeps that verdict honest).

**C. Narrow the credit gate to the demanding turn.** `_reasoning_present` scans the whole body today, so a history full of thinking makes it true even when the demanding turn carries none; such a complaint is a *missing-field* complaint, carries no information about the field *name*, yet drains the credit and walks the selection toward `none`. New rule: true only when the **last assistant message carrying a `tool_use` block** also carries a non-empty `thinking` (or `redacted_thinking`) block. The algorithm scans past later assistant messages that carry no `tool_use`, which is the operative definition everywhere in this plan and in the docs — the Summary no longer says "that the trailing `tool_result` answers", because the algorithm never checks that. The gate reads the **raw client body**, deliberately mirroring the client's own reasoning rather than the transform's keep rules.

**D. Rescue repairs instead of re-rolling an unchanged body.** Each rescue pass forces the always-present behavior on, so an unflagged provider that complains self-heals without a config edit. Two scope notes, both from the audit: the repair applies **only when the body carries a tool-call turn** (a body with none is still a same-body re-roll, unchanged), and the pass budget's `"none"` candidate cannot inject — so a repairing pass whose candidate is `"none"` uses the entry's current selection, or `reasoning_content` if that is also `none`, and reports the field it actually used as `effective_field` on the event. The pass still cannot move the credit.

**Alternatives rejected.** (1) *Retain and refill the vendor's real reasoning* — unnecessary: `""` satisfies the check, and retention needs per-turn state with no evidence it helps. (2) *Flag the provider* — reaches 18 models including the haiku tier's `mimo-v2.6-flash`, with no evidence. (3) *Silence the complaint client-side* — the client already behaves correctly. (4) *Change the tier mapping* — treats the symptom and abandons the provider.

**Out of scope.** The `x-should-retry` client hint, tier re-pointing, the anthropic-mode qwen path (0 complaints in 8,841 requests), any retention cache, and `opencode-zen-chat` (6 requests of evidence).

## Repo Mode

Public

## Document Overrides

| Document | Rule Overridden | Reason |
|----------|----------------|--------|
| — | — | — |

## Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| The collapse changes a wire shape that was "confirmed working against live opencode-go" | A chat provider could reject a single `content`+`tool_calls` message | Probe-validated 8/8 against the live provider before this plan; it is the ordinary OpenAI form |
| The collapse is unconditional for every chat-mode provider (no config gate) | A provider that needed the two-message form breaks | No such provider is known: the split was never a vendor requirement, only a workaround for discarded text; the chat-mode set is three opencode providers, all probe-able |
| Injecting a nonstandard field where a backend rejects unknown fields | New 400 class on a clean model | Policy defaults off; keyed per (provider, model) so `mimo-v2.6-flash` is untouched; `deepseek-v4.1-flash`'s acceptance of `""` is probe-validated 8/8 |
| The rescue's forced repair injects the field for **any** chat provider whose 400 body merely mentions `reasoning_content`/`reasoning`, including unflagged ones | An operator who deliberately left a provider unflagged still gets the field after a complaint | Accepted and documented: the repair fires only after a matched complaint, never on the happy path; the event records `effective_field` so the injection is never invisible |
| The `""` fill masks genuine reasoning loss | The vendor's complaint stops being an alarm for a dropped field | Never prefer `""` where a thinking block exists; the injection event separates `real` / `empty` / `placeholder` (a redacted-thinking placeholder counts as `placeholder`, not `real`); `content_block_dropped` remains the alarm |
| The narrowed gate freezes learning for a provider whose demanding turns legitimately carry no thinking | The selection stops moving | Intended: such a complaint is unlearnable by construction. Note that a gate-false turn skips the 2xx credit too, so the selection neither drains nor refills and simply holds |
| The policy is inert until an operator flags the pair, and `models.json` is deploy-owned (`update-claude-env` replaces it wholesale) | The shipped fix does not act on the live install | Named explicitly as Step 7 (activation, operator-owned); until then Part D is the self-healing path, and the plan says so rather than implying the flag is live |

## Rollback

Part A is the only unconditional change. To revert: restore the split in
`_transform_anthropic_messages_to_chat` and re-run `-shape.py`, which pins the
collapsed shape and will go red on the restored split. Part B reverts by
removing the policy key (or setting it to `{}`) and reloading; Part C/D revert by
restoring the whole-body gate and dropping the rescue's forced flag. The failure
signature to watch for after deployment is a rise in `transform_failure` or a new
400 class on a chat provider's trace rows — the immediate mitigation is tier
re-pointing (`qwen` serves the same `deepseek-v4.1-flash` in anthropic mode with
0 complaints in 8,841 requests) or reverting this change.

## Proposed Changes

1. **Step 1: Collapse the split in `_transform_anthropic_messages_to_chat`** (`transforms_chat.py`, the `tool_calls and text_parts` / `elif tool_calls` / `elif text_parts` / `else` block, ~L220-242). Emit one assistant message per Anthropic assistant turn: `content` = the joined text parts, or `None` when the turn has text-less tool calls. Keep the existing `else` branch's `content: ""` for a turn with neither text nor tool calls, and keep the malformed-argument placeholder on the same message as the surviving `tool_calls`. All per-block handling (cache_control stripping, tool_result pairing, redacted_thinking placeholder, dropped counters) is untouched.
   → coder verify (auto): the module emits at most one `{"role": "assistant", ...}` entry per Anthropic assistant message on the normal path; the `else` branch still yields `content: ""`; the placeholder path puts the placeholder text and the surviving `tool_calls` on one message
   → coder verify (scripted): `python3 ./tmp/verification/2026-10-22-reasoning-roundtrip-compliance-shape.py`
   → tester verify: the five rewritten tests in `test_chat_transform.py` pass, and the whole file is re-run

2. **Step 2: Add the always-present injection + its trace event** (`transforms_chat.py`). Add `reasoning_always=False` to `_anthropic_to_chat` and `_transform_anthropic_messages_to_chat`, forwarded through. **Implement the injection as a final pass over the fully built message list, after the per-message loop** — the predicate is global (does the list contain an assistant message with `tool_calls`?) and a per-message `_assistant_msg` hook cannot express it. When true AND the predicate holds AND `reasoning_selection in COMPAT_REASONING_FIELDS` (import the constant from `compat.py` and use it in `_assistant_msg` too, so the field set stays single-sourced): set the selected field on every assistant message — the real reasoning text where one exists, `""` otherwise. Emit one `reasoning_field_injected` event (`request_id`, `provider`, `tier`, `mode`, `real`, `empty`, `placeholder`) only when `empty + placeholder > 0`.
   → coder verify (auto): the injection runs as a post-loop pass over the built list; the trigger reads the transformed list; `COMPAT_REASONING_FIELDS` is imported from `compat` and used in both places; the event has three counters under an `if empty_count or placeholder_count:` guard
   → coder verify (scripted): `python3 ./tmp/verification/2026-10-22-reasoning-roundtrip-compliance-shape.py`
   → tester verify: the injection-matrix rows and `test_anthropic_to_chat_injection_trace_counts` pass

3. **Step 3: Add the `reasoning_roundtrip` policy and wire every pass-through site** (`config.py`, `server.py`, `templates/models.json`). Five sites, all of them required:
   - `load_models_document` (config.py): shape/value validation in the same block that validates `reasoning_field_switch` (~L122-143) — an object whose values are the string `"always"`, else `ValueError` naming the key; plus the `out[...]` pass-through assignment beside the existing two (~L137-145). Update the docstrings in `load_models_document` / `load_config` / `_load_config_documents` that enumerate the carried keys.
   - `validate_config` (~L527-532): mirror `extra_request_headers`' provider check — every key must be `"provider/model"` naming a configured provider *and* one of that provider's catalog models, else an error naming the entry.
   - `_LEFTOVER_KEYS` (config.py ~L55-56): add `reasoning_roundtrip` so a key misplaced into `config.json` warns like its three siblings. (This tuple is a *config.json leftover-warning* list, not the models.json pass-through — do not rely on it for carry-through.)
   - `/admin/api/switch` carry-over (server.py ~L3604-3608) and `/admin/api/reload` candidate assembly (server.py ~L3688-3692): both hardcode the three carried keys. Add `reasoning_roundtrip` to both, and **single-source the carried-key tuple into one module constant used by all three sites** so a fourth knob cannot repeat this omission.
   - `templates/models.json`: ship the key as `{}`.
   - Resolver `reasoning_roundtrip_models(config)` beside `reasoning_switch_params` (~L148): returns a `frozenset` of `"provider/model"` strings, total and never raising (absent/malformed → empty).
   → coder verify (auto): all five sites name `reasoning_roundtrip`; the two server tuples read one shared constant; the resolver returns a `frozenset`
   → coder verify (scripted): `python3 ./tmp/verification/2026-10-22-reasoning-roundtrip-compliance-config.py`
   → tester verify: the bad-shapes rows, the unknown-provider case, and the extended carry-across test in `test_admin.py` all pass — the last one is the regression test for this exact omission

4. **Step 4: Thread the policy into the chat transform call** (`server.py`). Resolve the policy set once per request from the config snapshot (beside the `reasoning_switch_params` resolution at ~L1145) and pass the **OR of the two sources** at the `_anthropic_to_chat` call site (~L1223-1226):
   `reasoning_always=reasoning_always or ("{}/{}".format(provider_name, actual_model) in policy_set)`.
   Add `reasoning_always=False` to `_forward_request_impl`'s signature. The OR is load-bearing: a literal `reasoning_always=(provider in set)` would make every rescue pass re-enter with the policy-off body and Part D inert.
   → coder verify (auto): the call-site expression ORs the parameter with the policy lookup (read the expression, not a file-wide substring); `_forward_request_impl` accepts the flag with a `False` default
   → coder verify (scripted): `python3 ./tmp/verification/2026-10-22-reasoning-roundtrip-compliance-config.py`
   → tester verify: the end-to-end chat-mode test passes, and an unflagged provider's rescue pass really carries the field

5. **Step 5: Narrow the credit gate to the demanding turn** (`compat.py`). Rewrite `_reasoning_present` (~L655): scan `messages` from the end for the last `role == "assistant"` message whose content list contains a `tool_use` block (scanning past later assistant messages that carry none); return True only if that message also contains a non-empty `thinking` block or a `redacted_thinking` block with non-empty `data`. Return False when no assistant `tool_use` message exists. Keep it total and update the docstring to state the rule and the raw-body (pre-transform) scope.
   → coder verify (auto): the scan skips assistant messages without `tool_use`; the thinking check is anchored to the found message; the whole-body scan is gone
   → coder verify (scripted): `python3 ./tmp/verification/2026-10-22-reasoning-roundtrip-compliance-gate.py`
   → tester verify: `test_reasoning_present_gates_on_demanding_turn` passes, and the migrated `_reasoning_request` fixture re-baselines the credit suite green

6. **Step 6: Force the repair on rescue passes** (`server.py`, `_reasoning_rescue` ~L799-856). Each pass passes `reasoning_always=True`; when the pass's `candidate` is `"none"`, the effective field is the entry's current selection, or `reasoning_content` when that is also `none` — computed at the call site and reported on the `reasoning_rescue` event as `effective_field` alongside the existing `candidate`. Change nothing else: the budget, the merge semantics, and the metadata-only event stay as they are, and the passes remain credit-inert.
   → coder verify (auto): the rescue's forward call passes `reasoning_always=True`; the `"none"`-candidate fallback resolves to a field name; `effective_field` is emitted; `_compat_merge_retries` is still used on all three outcomes
   → coder verify (scripted): `python3 ./tmp/verification/2026-10-22-reasoning-roundtrip-compliance-gate.py`
   → tester verify: the repaired-bytes test passes for both a field and a `none` candidate

7. **Step 7 (planner/operator-owned): activate the policy.** The template ships `{}`, and `install_template` is existence-gated, so no existing install gains the key — and `doc/configuration.html` records that `models.json` is deploy-owned (`update-claude-env` replaces it wholesale). After the coder and tester finish, the flagged pair is added to the durable `models.json` (the user's proxy copy, or the shared repo's source of truth, whichever owns it) as
   `"reasoning_roundtrip": {"opencode-go-chat/deepseek-v4.1-flash": "always"}`
   followed by `claude-retry-proxy reload`. The live file is outside this repo's write lanes, so the planner records the exact edit and the required reload rather than performing it.
   → Evidence: the `load_models_document` output for the edited file shows the key, `/admin/api/providers-detail` still resolves the provider, and one live chat-mode request carries `reasoning_content` on every assistant message in the forwarded body (verified from the trace's injection event, whose `empty` count is non-zero on a conversation with a bare turn).

8. <!-- UPDATED 2026-10-24: added by the /update-plan revision that un-dismissed the review's three Suggestions. --> **Step 8: Clear the placeholder flag when real reasoning supersedes it** (`transforms_chat.py`, the `thinking` branch ~L154-160). Reviewer finding `review-reasoning-placeholder-flag-not-cleared`: the branch assigns `reasoning_text = thinking` for a non-empty block but leaves `reasoning_is_placeholder` set by an earlier `redacted_thinking` block, so a turn whose content orders `[redacted_thinking, thinking, tool_use]` forwards the **real** text while the injection pass classifies it as a placeholder — emitting `real=0, empty=0, placeholder=1` and firing the event on a request that filled nothing blank. Set `reasoning_is_placeholder = False` in the branch that keeps non-empty real text, so the flag always describes the value actually kept. Change nothing else: the `redacted_thinking` branch, the three counters and the event guard stay as they are — removing the placeholder outright is the separately-deferred `defer-issue-drop-redacted-thinking-chat-placeholder`, not this step (which that future plan will delete along with the flag itself).
   → coder verify (auto): the `thinking` branch clears the flag on the path that assigns non-empty text; the `redacted_thinking` branch, the counters and the `empty_count or placeholder_count` guard are unchanged
   → coder verify (scripted): `python3 ./tmp/verification/2026-10-22-reasoning-roundtrip-compliance-step8.py`
   → tester verify: the new pinning test passes (real text forwarded, counted `real=1, placeholder=0`, no event fired), the redacted-only guard case stays green, and the five affected modules re-run clean

**Verification baselines (pre-change, run 2026-10-22 against the tree at plan time — each script is unedited between its RED run and the coder's GREEN run; scripts edited during this revision are re-run and re-recorded below):**

*(Re-recorded 2026-10-23 after the audit revision edited two scripts; the earlier run's numbers — shape 7 / config 10 / gate 3 — are superseded, and each script is unedited between this RED run and the coder's GREEN run.)*

| Script | RED result | Failures, each for the intended reason |
|--------|-----------|----------------------------------------|
| `-shape.py` | FAIL (10), exit 1 | the split emits 2 assistant messages for a text+tool_use turn (and 2 for the malformed-argument placeholder path); `reasoning_always` raises `TypeError`; `reasoning_field_injected` absent; the three counters absent |
| `-config.py` | FAIL (15), exit 1 | the pass-through drops the key; `"sometimes"` and a non-object policy are both accepted; the resolver is missing; `validate_config` accepts an unknown provider/model pair; `_LEFTOVER_KEYS` omits the key; server.py still holds 2 parallel literal carry-over tuples; no `reasoning_always=` OR-expression; the template lacks the key |
| `-gate.py` | FAIL (5), exit 1 | a bare demanding turn over a reasoned history returns `True`; reasoning without any tool call returns `True`; a later reasoned assistant turn rescues a bare tool-call turn (`True`); the rescue passes no repair flag and has no `effective_field` |

Guards that pass on both sides of the change (present so a green run cannot come from an over-broad assertion): the tool_use-only single-message shape, the empty-turn `content: ""` branch, the reasoned demanding turn returning `True`, `_reasoning_present`'s totality guards, the clean synthetic `validate_config` baseline, and the rescue's merge/budget lines.

**Step 8's gate** (`-step8.py`) was calibrated 2026-10-24 against the post-implementation tree, which is its RED baseline: **FAIL (3), exit 1** — the forwarded field already carries `REAL TEXT` (PASS), while the run emits `reasoning_field_injected` with `real=0, empty=0, placeholder=1` (two failures: the event fires on a request that filled nothing blank, and a real-text turn is counted as a placeholder) and the `thinking` branch does not clear the flag (third failure). Both guard checks — a redacted-only turn still forwards the placeholder and is counted `placeholder=1, real=0` — pass on both sides, so a green run cannot come from removing the placeholder instead of fixing the flag.

## Guidance for Planner

- **Files to modify:**
  - `./doc/provider-modes.html`
  - `./doc/configuration.html`
  - `./doc/compatibility.html`
  - `./doc/trace-log.html`
  - `./doc/test-catalog.html`
  - `./CLAUDE.md`
  - `./README.md`
- **`.claude/mega-audit-files.json`:** no change — this plan adds no new declared audit location.
- **When:** after the coder finishes and the tester's suite is green (docs describe shipped behavior).
- **What to sync (targets verified against the files by the audit; the four `doc_suggestions` from the coder round folded in 2026-10-23):**
  - `doc/provider-modes.html`: the thinking-block request row (~L130) gains the policy-scoped always-present behavior and the `""` fill; the **event table** gains a `reasoning_field_injected` row (fires when the fill count is non-zero; carries `real`/`empty`/`placeholder`); the malformed-argument paragraph (~L628-634) is corrected from two assistant messages to one, and must state that when **every** tool call in the turn was degraded the placeholder stays plain text with no `tool_calls` key — the collapse must not imply one survives. This page contains no split description and no DeepSeek mention — do not invent targets.
  - `doc/configuration.html`: show `reasoning_roundtrip` in the models.json sample (~L94-101); add a validation-rules row (present but not an object whose values are the string `always` → startup refusal naming the key; a key naming an unknown provider/model → refusal); note that the **reload gate re-runs the provider/model check**, so a typo'd pair is refused at reload rather than installed as a silently inert policy; note the key's activation in Step 7 and that `models.json` is deploy-owned.
  - `doc/compatibility.html`: restate the `reasoning_field` gate as demanding-turn-scoped and record why (a missing-field complaint is unlearnable), stating explicitly that it reads the **raw client body (pre-transform)**; describe the rescue's repair, its `"none"`-candidate fallback, and the documented no-tool-call case where the passes remain same-body re-rolls.
  - `doc/trace-log.html`: add `reasoning_field_injected` to the inventory **and** to the rescue's per-pass event list (`mode_dispatch`, one `reasoning_rescue`, `cache_control_stripped`, …), noting which events multiply per client request; record that the existing `reasoning_rescue` event gains **`effective_field`** beside `candidate`, and that on a `"none"` candidate `candidate` differing from the field actually sent is the normal case, not an anomaly.
  - `doc/test-catalog.html`: update the five rewritten split-test descriptions and the malformed-argument test line; per the repo-wide no-exact-counts rule, replace the snapshot totals with the page's measure-on-demand recount command rather than bumping numbers.
  - `CLAUDE.md`: the `compat.py` Structure one-liner (the learner's gate) and the `transforms_chat.py` one-liner (the collapsed shape + the policy); the `templates/models.json` tree line (~L46) that enumerates the catalog's contents. There is no "Moved out of this section" reasoning row and no split/gate text in the two Structure lines today — add, do not "update".
  - `README.md`: the pre-spawn validation list (~L100-105) gains `reasoning_roundtrip`; the artifact row (~L639) gains the key; the chat-mode behavior description (~L402-403) gains the policy-scoped always-present field (real reasoning where present, `""` otherwise). Do not invent a models.json key table if the section has none.

## History

| Date | Event | Conclusion | Dismissed |
|------|-------|------------|-----------|
| 2026-10-22 | Initial plan | Root cause established by wire capture + probe; plan covers the collapse, the scoped always-present policy, the demanding-turn gate, and the rescue repair. | — |
| 2026-10-23 | Implementation round (coder) | All six coder steps complete ([report](./tmp/reports/2026-10-22-reasoning-roundtrip-compliance-coder-2026-10-23.json)); all three verification gates GREEN on the planner's own re-run (shape/config/gate, exit 0 each); `build_result: pass`, 0 issues filed, 0 pre-existing defects in the touched code. Residual notes, both surfaced rather than waived: (a) `pip install -e .` cannot run in the default interpreter — setuptools and the build frontend are absent, an environment condition rather than a repo defect — so the build check was `compileall` plus an import smoke test of every touched module; (b) the shared carried-keys constant lives in `server.py` while `load_models_document` keeps its explicit `out[...]` assignments, matching that function's style for every optional key, so a fifth models.json knob would need both places. Both are recorded here; the second is also why the `-config.py` gate pins the literal in `server.py` (a gate artifact noted for the reviewer). | — |
| 2026-10-23 | Mega-audit (pre-implementation) | 10 High / 24 Medium / 28 Low from 9 lenses ([report](./tmp/reports/2026-10-22-reasoning-roundtrip-compliance-mega-audit-2026-10-23.json)); all High + Medium addressed in Revision 2 — the pass-through sites (now five, single-sourced), the call-site OR, the `none`-candidate repair, the fixture migration, the three extra split tests, the NaN-placeholder reconciliation, and the duplicated new tests. | Low findings, all addressed by Revision 2 rather than waived: `_LEFTOVER_KEYS` misread (×3 lenses), empty-turn `content` value, unknown-provider validation, the demanding-turn wording divergence in Summary vs Step 5 (×3 lenses), missing activation step for the live `models.json`, injection as a post-loop pass, `none`-candidate inertness (×2 lenses), no Rollback section, dropped/degraded `tool_use` vs the gate's view (×2 lenses), placeholder counted as `real`, no-tool-call rescue scope, rescue's forced flag reaching unflagged providers, precedence wording (×2 lenses), `validate_config` value-check placement, `transforms_chat → compat` import edge, `_reasoning_request` fixture/baseline note, tester module-naming in metadata, `ALL_TESTS` registration, coder boundary wording, and the five doc-sync targets that named text the files do not contain ([report](./tmp/reports/2026-10-22-reasoning-roundtrip-compliance-mega-audit-2026-10-23.json)) |
| 2026-10-23 | Implementation round (tester) — failed round; retry used (1) | Killed at the 3600 s cap (`timeout: killed after 3600s`, 01:22:07; no `tree not confirmed dead` suffix, so the retry rule applies) mid-calibration: all prescribed tests authored across six `tests/` files — 41 edits, **zero** to `src/` — passing in isolation and in-suite, all compiling, three gates GREEN on the planner's re-run, no scaffolding left behind, and **no report written**; relaunched under an assess-and-brief. Two consistency fixes rode along: `tests/_harness.py` was edited for e2e support but was absent from both the Guidance for Tester file list and the metadata, and `tests/test_admin.py` was in the metadata but not the prose list — both now name it. | — |
| 2026-10-23 | Implementation round (tester) — failed round; retry used (2) | Died at exit 1 two minutes in, killed by the very defect under repair — `API Error: 400 Upstream request failed: [invalid_request_error] The reasoning_content in the thinking mode must be passed back to the API` (request_id `fbfac9f2-3757-41c5-b54e-b3e01c05c608`), the third round lost to it. It made no edits and wrote no report, so nothing was lost. Root cause was environmental, not the plan: Step 7 (deployed-policy activation) was still unperformed, leaving the implemented fix inert in the live config. Step 7 is now done and verified live (probe 4/4 HTTP 200, 3 injection events — see `## Immediate Actions`), so this relaunch runs against the activated policy. | — |
| 2026-10-23 | Implementation round (tester) | **SUCCESS** ([report](./tmp/reports/2026-10-22-reasoning-roundtrip-compliance-tester-2026-10-23.json)): 430 passed / 8 failed / 438 total, where the 8 are exactly the frozen Python 3.14 baseline the previous plan measured (425/8/433) with this plan's five added tests accounting for the delta — **0 new failures**; all five affected modules individually green (`test_chat_transform` 52/52, `test_compat` 55/55, `test_config_split` 11/11, `test_mode_dispatch` 30/30, `test_admin` 37/37); every new test registered in its module's `ALL_TESTS`; the three verification gates re-run green on the current tree (15/15, 17/17, 10/10). The suite is shown to genuinely enforce the plan rather than merely pass: **17 prescribed tests are RED against a pre-change `src/` shadow built from HEAD blobs** (7 `test_chat_transform`, 3 `test_config_split`, 1 `test_mode_dispatch`, 5 `test_compat`, 1 `test_admin`), while the four migrated compat tests are GREEN on both trees as expected for behaviour the plan preserves. `verdict`: GREEN against the acceptance condition; no test skipped or removed. The pre-change tree was exercised by shadow-copy rather than a worktree — worktree creation needs an approval an unattended round does not have — and the shadow was removed after calibration. | [defer-issue-suite-json-recursion-profile-py314](./tmp/reports/defer-issue-suite-json-recursion-profile-py314.json) — the frozen Python 3.14 json-recursion baseline (8 failures), pre-existing and deferred, untouched by this plan; docs not yet synced, the planner's own pending post-green work Resolved 2026-10-26 by plan 2026-10-25-json-nesting-limit: the proxy now enforces its own 500-level nesting limit, which makes the interpreter's json/recursion ceilings unreachable by construction — the eight interpreter-profile tests were rewritten, re-fixtured or retired, the stale 16,920/15,501 ceiling figures were replaced with the limit policy, and the suite is green at 475/0/475 on Python 3.14.7. |
| 2026-10-23 | Review | **Issues found — non-blocking: 0 Critical / 0 Warning / 4 Suggestion** ([report](./tmp/reports/2026-10-22-reasoning-roundtrip-compliance-review-2026-10-23.json)). All 18 changed files read; every one of the plan's six coder Steps verified against the code rather than the gate scripts, and the collapse/injection/rescue paths exercised directly to confirm the emitted bytes and events — including that `effective_field` reaches all three merge outcomes and that the load-bearing call-site OR is present. Step 7's activation independently corroborated from the live trace: **420 injection events from real traffic** with zero `transform_failure`. Reviewer confidence high on the shipped logic, medium on residual live-provider behaviour; `process_quality` notes a further round would be unlikely to find new production-impacting defects. Two doc-lane Suggestions fixed by the planner at once (the rescue's byte-identical-exclusivity overclaim, and a stale "on-disk config" phrase the tester's own revised docstring already contradicted); the two source/test-lane Suggestions are recorded as deferred improvements below. | Four Suggestions, each a linked slug: [review-reasoning-placeholder-flag-not-cleared](./tmp/reports/2026-10-22-reasoning-roundtrip-compliance-review-2026-10-23.json) — a real but trace-only defect (coder lane): a `[redacted_thinking, thinking, tool_use]` turn forwards the real reasoning yet is counted `placeholder=1, real=0`, and the event fires although nothing was filled, which the two doc pages describe as impossible; the forwarded bytes are correct and the 400 fix is unaffected. [review-rescue-identical-body-exclusivity-claim](./tmp/reports/2026-10-22-reasoning-roundtrip-compliance-review-2026-10-23.json) — **fixed by the planner**: a flagged pair has a second byte-identical case (attempt 1 already forces the field on, so a `none`-candidate fallback rebuilds those same bytes and spends a budget slot on a known-rejected body); the page now names both cases. [review-e2e-unflagged-leg-cannot-detect-leak](./tmp/reports/2026-10-22-reasoning-roundtrip-compliance-review-2026-10-23.json) — deferred (tester lane): the e2e test's unflagged-model leg cannot observe provider-level policy leakage, because that model carries no learned selection and so emits no field regardless. [review-delist-repaired-bytes-claim](./tmp/reports/2026-10-22-reasoning-roundtrip-compliance-review-2026-10-23.json) — deferred (tester lane): one test's docstring claims the repaired bytes served the client, but its fixture's turn already carries reasoning and the mock serves on content-blind retry, so that claim cannot fail. Hunches recorded, none promoted: the `_CARRIED_MODELS_KEYS`/`load_models_document` duplication (already a plan residual); `validate_config`'s non-`"always"` branch being unreachable via the normal load path (defensible as canonical-validator parity); `reasoning_field_injected` carrying no forced-origin marker (accepted in the Risks table); the pre-existing "on-disk config" phrase (**fixed by the planner**). |
| 2026-10-24 | Spec revision (/update-plan) | Operator directed that the review's three non-blocking Suggestions be fixed rather than carried as deferred improvements, so implementation re-opened for one coder round and one tester round: **Step 8** added (`review-reasoning-placeholder-flag-not-cleared` — the `thinking` branch clears `reasoning_is_placeholder` whenever it keeps non-empty real text, leaving the redacted branch, the counters and the event guard untouched) plus two tester-lane repairs (`review-e2e-unflagged-leg-cannot-detect-leak`, `review-delist-repaired-bytes-claim`); all three gained `## Issue Log` rows at `Fix Planned`, and `-step8.py` was calibrated RED against the post-implementation tree — FAIL (3), every failure for finding 1's reason. Filed standalone from this session, with no row here: [defer-issue-drop-redacted-thinking-chat-placeholder](./tmp/reports/defer-issue-drop-redacted-thinking-chat-placeholder.json) — the operator deferred the placeholder's outright removal in chat mode to a future plan, which adds the adopting row that retires it. | — |
| 2026-10-24 | Implementation round (coder) | Step 8 implemented and verified ([report](./tmp/reports/2026-10-22-reasoning-roundtrip-compliance-coder-2026-10-24.json)): the `thinking` branch now clears `reasoning_is_placeholder` on the non-empty-text path (two added lines plus a one-line comment), and `git diff` shows the `redacted_thinking` branch, the three counters and the `empty_count or placeholder_count` guard untouched — the placeholder was deliberately not removed, that being the deferred plan's work. `build_result: pass`, `files_modified` is exactly `transforms_chat.py` (confirmed by mtime: no test-lane write this round), 0 issues filed, 0 pre-existing defects in the touched code, no doc need (the two doc pages' counter description now matches the behaviour in both block orders). `-step8.py` RED at entry exactly as calibrated (FAIL (3)) → **PASS (5/5)** after the edit, and the three existing gates re-ran GREEN on the planner's own re-run (shape 15/15, config 17/17, gate 10/10). Residual, previously recorded and unchanged: `pip install -e .` is un-runnable in the default interpreter (setuptools and the build frontend absent — environment, not a repo defect), so the build check was `compileall` plus an import smoke test of every touched module. | — |
| 2026-10-24 | Implementation round (tester) | **SUCCESS** ([report](./tmp/reports/2026-10-22-reasoning-roundtrip-compliance-tester-2026-10-24.json)): **431 passed / 8 failed / 439 total** — the 8 are exactly the frozen Python 3.14 `json`-recursion baseline (438 → 439 with this round's one added test), so **0 new failures**, nothing skipped or removed; all five affected modules green individually and all four verification gates green. Each of the round's three items is calibrated rather than merely green: the new `test_anthropic_to_chat_real_thinking_supersedes_placeholder` is RED against a pre-Step-8 `src/` shadow (failing exactly on the finding's message), the strengthened e2e leg is RED once the policy is flagged for the haiku pair too — proving it can now observe a provider-scoped leak — and the repaired `reasoning-delist-on-none-success` fixture serves only a body carrying the field on every assistant message, asserting attempt 1 did not already carry it. The three Issue Log rows are marked `Resolved` on this report. Residuals, both planner-lane: two `doc/test-catalog.html` discrepancies (below) and the unchanged `pip install -e .` environment condition; the 8 py3.14 failures remain the untouched pre-existing deferral. | — |
| 2026-10-24 | Review (delta, r2) | **Issues found — non-blocking: 0 Critical / 0 Warning / 1 Suggestion** ([report](./tmp/reports/2026-10-22-reasoning-roundtrip-compliance-review-2026-10-24.json)). Delta-only re-review (the r1 review predates Step 8), its scope confirmed by mtime: `transforms_chat.py`'s flag clear, the new pinning test, the two strengthened tests, and the two doc rows. Adversarial verification passed: the invariant "the flag is True only when the kept value is the placeholder" now holds for every block order — redacted-then-thinking clears it, thinking-then-redacted never sets it (the redacted branch requires `reasoning_text is None`), multiple non-empty `thinking` blocks keep it False, an empty `thinking` after a placeholder leaves the placeholder and the flag True — and the change moves only the counters, never the forwarded bytes; the event contract holds (a real-text-only conversation fires none, a superseded turn counts `real`, a redacted-only turn still `placeholder=1, real=0`); each strengthened test fails without the behaviour it pins; and no doc contradicted the code beyond the one Suggestion. It accepted the suite run, the verification gates and the live-proxy behaviour from the round reports rather than re-running them (recorded as a hunch), so the planner's own re-runs — four gates PASS, the three touched modules green, doc gates PASS — stand as that evidence. | One Suggestion, a linked slug: [review-supersede-clause-implies-an-event](./tmp/reports/2026-10-22-reasoning-roundtrip-compliance-review-2026-10-24.json) — the clause the planner had just added to `doc/provider-modes.html` said the injection event counts a superseded turn `real`, without saying that a superseded-only conversation fires no event; **fixed by the planner** in place, the clause now carrying the firing condition and naming the no-event case. |

## Plan Metadata

```json
{
  "plan_id": "2026-10-22-reasoning-roundtrip-compliance",
  "steps": [
    "Step 1: Collapse the split in _transform_anthropic_messages_to_chat",
    "Step 2: Add the always-present injection + its trace event",
    "Step 3: Add the reasoning_roundtrip policy and wire every pass-through site",
    "Step 4: Thread the policy into the chat transform call",
    "Step 5: Narrow the credit gate to the demanding turn",
    "Step 6: Force the repair on rescue passes",
    "Step 7: Activate the policy (planner/operator-owned)",
    "Step 8: Clear the placeholder flag when real reasoning supersedes it"
  ],
  "coder_files": [
    "src/claude_retry_proxy/transforms_chat.py",
    "src/claude_retry_proxy/compat.py",
    "src/claude_retry_proxy/config.py",
    "src/claude_retry_proxy/server.py",
    "src/claude_retry_proxy/templates/models.json"
  ],
  "tester_files": [
    "tests/test_chat_transform.py",
    "tests/test_compat.py",
    "tests/test_config_split.py",
    "tests/test_mode_dispatch.py",
    "tests/test_admin.py",
    "tests/_harness.py"
  ],
  "doc_files": [
    "doc/provider-modes.html",
    "doc/configuration.html",
    "doc/compatibility.html",
    "doc/trace-log.html",
    "doc/test-catalog.html",
    "CLAUDE.md",
    "README.md"
  ],
  "verification_scripts": [
    "./tmp/verification/2026-10-22-reasoning-roundtrip-compliance-shape.py",
    "./tmp/verification/2026-10-22-reasoning-roundtrip-compliance-config.py",
    "./tmp/verification/2026-10-22-reasoning-roundtrip-compliance-gate.py",
    "./tmp/verification/2026-10-22-reasoning-roundtrip-compliance-suite.py",
    "./tmp/verification/2026-10-22-reasoning-roundtrip-compliance-red.py",
    "./tmp/verification/2026-10-22-reasoning-roundtrip-compliance-flake.py",
    "./tmp/verification/2026-10-22-reasoning-roundtrip-compliance-step8.py"
  ],
  "repo_mode": "Public",
  "document_overrides": []
}
```

## Audit Accumulation

| Counter | Value | Last Updated |
|---------|-------|--------------|
| issues_resolved_since_audit | 0 | 2026-10-24 |
| steps_changed_since_audit | 1 | 2026-10-24 |
| files_changed_since_audit | 0 | 2026-10-24 |

## Documentation

Deep reference for the mechanisms this plan changes: `doc/provider-modes.html`
(the chat-mode transforms and their event table), `doc/compatibility.html` (the
feature registry and the `reasoning_field` learner), `doc/configuration.html`
(models.json keys and validation), `doc/trace-log.html` (the event inventory).
The planner syncs all four plus `CLAUDE.md`, `README.md`, and
`doc/test-catalog.html` after the tester's suite is green.

## Final Results

**Status: COMPLETED — 2026-10-24.** Two loop iterations (steps 6–10) closed to green. *First
iteration:* coder round (exit 0, all six Steps, `build_result: pass`); tester round retried twice
under the retry rule (round 1 killed at its wall-clock cap at 01:22:07 mid-calibration, round 2
killed at exit 1 by the very defect under repair at 01:29:19 — the live proxy was still
unactivated — and round 3 **SUCCESS** at 18:26:38); r1 review: **0 Critical / 0 Warning /
4 Suggestion** against all 18 changed files, with every one of the six coder Steps verified from
the code rather than from the gate scripts and the collapse/injection/rescue paths exercised
directly to confirm the emitted bytes. *Second iteration:* the operator directed that the review's
three non-blocking Suggestions be fixed rather than carried as deferred improvements, so the plan
re-opened for a Step-8 round — coder (one file: the flag clear in the `thinking` branch) then
tester (the pinning test plus the two strengthened tests), both exit 0 with fresh reports — closing
with the **r2 delta review: 0 Critical / 0 Warning / 1 Suggestion**, a doc clause the planner fixed
in place.

**What landed.**

- **Part A — the collapse.** Each assistant turn becomes *one* chat message (its text and its
  `tool_calls` together), so the tool-calls message is no longer bare by construction — the shape
  the vendor's round-trip rule is about. The empty-turn `content: ""` and the all-degraded
  placeholder case (plain text, no `tool_calls` key) are pinned by tests.
- **Part B — the policy.** `reasoning_roundtrip` in `models.json`: a `"provider/model"` →
  `"always"` map, absent by default. For a flagged pair, every assistant message of a tool-calling
  conversation carries the learned echo field — the real reasoning where one exists, `""` where it
  does not, because those gateways check *presence*, not content. Inert while the pair's selection
  is `none`; reported by the `reasoning_field_injected` event (`real` / `empty` / `placeholder`).
- **Part C — the narrowed gate.** `_reasoning_present` reads the *last* `tool_use`-bearing
  assistant turn from the raw client body; a missing-field complaint is unlearnable and no longer
  pollutes the credit.
- **Part D — the repairing rescue.** Rescue passes force the always-present behavior on, resolve an
  `effective_field` when the candidate is `none`, and report it beside `candidate`.
- **Step 8 — the superseding fix (2026-10-24).** A real `thinking` block on the same turn now
  clears the placeholder flag, so a `[redacted_thinking, thinking, tool_use]` turn is accounted for
  as what it sends — `real`, never `placeholder` — and a conversation whose only filled turn is
  that superseded one fires no injection event, since nothing blank was filled. The fix closes the
  r1 review's one Correctness Suggestion and changes only the counters, never the forwarded bytes;
  the placeholder path itself is untouched, its outright removal being deferred (see below).
- **Step 7 — activation (operator-owned, done).** The probe that carried the plan also became its
  regression check: the failing production shape returned **4/4 HTTP 200** through the live proxy
  with 3 `reasoning_field_injected` events (`real=0, empty=1, placeholder=0`) while the
  tool-call-free control emitted none. The reviewer then corroborated it from the live trace
  independently: **420 injection events from real traffic** (e.g. `real=41, empty=8`), zero
  `transform_failure` events.

**Step 7's durability.** Both copies now carry the key, and the two documents are content-identical
throughout (a flattened comparison reports **0 differing entries**): the deployed
`~/.claude/proxy/models.json` and the shared source of truth
`claude-config/personal/proxy/models.json`. `update-claude-env` copies the latter over the former
unconditionally — `bin/update-claude-env`'s `COPY_MAP` pair `personal/proxy/models.json →
~/.claude/proxy/models.json`, with no existence gate — so the next deploy **installs** the
activation rather than reverting it, and the Risks row this plan named is closed.

One step remains, outside this plan's write lanes and therefore recorded rather than taken: in
`claude-config` the key is a **working-tree change, not a commit** — `git show
HEAD:personal/proxy/models.json` reads it ABSENT and `git log -S 'reasoning_roundtrip'` finds no
commit — so the source of truth holds it only until that file is committed. **The operator has
confirmed that commit is planned in `claude-config`**, so this item is theirs to close and no
action is outstanding here. That repo also carries an unrelated pre-existing dirty tree
(`CLAUDE.md`, `README.md`, `bin/*`, `chunzhen/*`), which `update-claude-env`'s own pre-flight aborts
on ("has uncommitted tracked changes"), so its next run needs a clean tree from that work in any
case.

**Part D is no longer the only active path** — for `opencode-go-chat/deepseek-v4.1-flash` the
policy is live and has fired 420 times on real traffic. For every other pair, Part D remains the
self-healing path, as designed.

**Files changed** (18, the same set the r1 reviewer diffed; now **1,471 insertions / 216
deletions** — the r1 summary read 1,303/215 and the Step-8 round added 168 insertions):
`src/claude_retry_proxy/` — `transforms_chat.py`, `compat.py`, `config.py`, `server.py`,
`templates/models.json`; `tests/` — `test_chat_transform.py`, `test_compat.py`,
`test_config_split.py`, `test_mode_dispatch.py`, `test_admin.py`, `_harness.py`; docs — `CLAUDE.md`,
`README.md`, and `doc/{provider-modes,configuration,compatibility,trace-log,test-catalog}.html`.

**Test results.** Full suite (**431 passed / 8 failed / 439 total**, run 2026-10-24) — the 8 are
exactly the frozen Python 3.14 `json`-recursion baseline (previous plan: 425/8/433; this plan adds
six tests), so **0 new failures**, nothing skipped, nothing removed. Every affected module green on
its own (`test_chat_transform` 53/53, `test_compat` 55/55, `test_config_split` 11/11,
`test_mode_dispatch` 30/30, `test_admin` 37/37 — the planner re-ran the three touched modules
independently), and every new test registered in its module's `ALL_TESTS`. The suite is shown to
*enforce* the plan rather than merely pass: **17 prescribed tests are RED against a pre-change
`src/` shadow built from HEAD blobs** (7 `test_chat_transform`, 3 `test_config_split`,
1 `test_mode_dispatch`, 5 `test_compat`, 1 `test_admin`), the four migrated compat tests stay green
on both trees as expected for behaviour the plan preserves, and the Step-8 round's tests carry the
same calibration — the new `test_anthropic_to_chat_real_thinking_supersedes_placeholder` is RED
against a pre-Step-8 shadow (failing on the finding's own message), the strengthened e2e leg is RED
once the policy is flagged for the haiku pair too, and the repaired delist fixture serves only a
body carrying the field on every assistant message. Verification gates on the final tree: shape
15/15, config 17/17, gate 10/10 and the new step-8 gate 5/5 — all PASS on the planner's own re-run.
Doc gates after the planner's sync: structure PASS (9 files), anchors PASS (217 references),
`tests/test_docs.py` 11/11.

**Review verdicts.** *r1 (2026-10-23):* issues found — non-blocking, 0 Critical / 0 Warning /
4 Suggestion, all dispositioned in the `## History` review row. Two doc-lane Suggestions were fixed
by the planner on the spot (the rescue's byte-identical-exclusivity overclaim, and a stale "on-disk
config" phrase the tester's own revised docstring already contradicted); the two source/test-lane
Suggestions were then *fixed* rather than carried, at the operator's direction, in the Step-8 round
— all three now `Resolved` in the `## Issue Log`. *r2 delta (2026-10-24):* issues found —
non-blocking, **0 Critical / 0 Warning / 1 Suggestion** on the delta (Step 8's flag clear, the new
pinning test, the two strengthened tests, the two doc rows; scope confirmed by mtime). The reviewer
verified the flag-clear invariant for every block order — redacted-then-thinking clears it,
thinking-then-redacted never sets it, multiple non-empty `thinking` blocks keep it False, an empty
`thinking` after a placeholder leaves the placeholder and the flag set — and confirmed each
strengthened test is falsifiable without the behaviour it pins. Its one Suggestion (the
`doc/provider-modes.html` supersede clause implying an event on a superseded-only turn) was fixed by
the planner in place.

**Known caveats (non-blocking).** No reviewer finding is outstanding: r1's four Suggestions and
r2's one are all resolved — three fixed in the Step-8 round (the counter defect and the two
under-asserting tests), two by the planner in place (the rescue's exclusivity overclaim, the r2
supersede clause). Hunches recorded across both reviews, none promoted and none blocking: the
`_CARRIED_MODELS_KEYS` / `load_models_document` duplication (a plan residual — a fifth
`models.json` knob needs both places); `validate_config`'s non-`"always"` branch being unreachable
through the normal load path (defensible as canonical-validator parity); `reasoning_field_injected`
carrying no forced-origin marker (accepted in the Risks table); `redacted_thinking_passthrough`
still firing for a placeholder a later `thinking` block supersedes (the event's wording stays
literally true, and the deferred removal below deletes it); whitespace-only `thinking` treated as
real text (pre-existing, unchanged here).

**Deferred issues (enumerated — presence on disk is the open state).**

- ~~**Python 3.14 `json` recursion profile** —
  [defer-issue-suite-json-recursion-profile-py314](./tmp/reports/defer-issue-suite-json-recursion-profile-py314.json):
  the 8 frozen failures above; unchanged and unowned by this plan.~~ Resolved 2026-10-26 by plan 2026-10-25-json-nesting-limit: the proxy now enforces its own 500-level nesting limit, which makes the interpreter's json/recursion ceilings unreachable by construction — the eight interpreter-profile tests were rewritten, re-fixtured or retired, the stale 16,920/15,501 ceiling figures were replaced with the limit policy, and the suite is green at 475/0/475 on Python 3.14.7.
- **`analyze_proxy_trace.py` model-field terminal escapes** —
  [defer-issue-analyze-trace-model-terminal-escape](./tmp/reports/defer-issue-analyze-trace-model-terminal-escape.json):
  untouched by this plan.
- **Proxy's own `Date`/`Server` headers** —
  [defer-issue-proxy-own-server-date-headers](./tmp/reports/defer-issue-proxy-own-server-date-headers.json):
  untouched by this plan.
- **Drop `redacted_thinking` in chat mode instead of substituting a placeholder** —
  [defer-issue-drop-redacted-thinking-chat-placeholder](./tmp/reports/defer-issue-drop-redacted-thinking-chat-placeholder.json):
  filed from this plan's session at the operator's direction; it records the decision (with the
  evidence — 0 `redacted_thinking_passthrough` events and 0 redacted entries in any
  `content_block_dropped` count across the whole retained trace window) to remove the placeholder
  substitution and its counter axis in a future plan. It is **standalone**: it has no Issue Log row
  here, and that future plan adds the adopting row that retires it. Note for that plan: Step 8's
  flag clear is deleted along with the flag it maintains, not undone.

**No `## Cross-References to Prior Plans` section.** The prior plan
(`2026-10-22-reasoning-field-credit-rescue`) declared the upstream's own root cause *out of scope*
rather than deferring it, and closed its one adopted deferral as Resolved; its other recorded items
(dead walk machinery, retired test candidates) are untouched here. This plan resolved the
**client-side trigger** of that incident — the non-compliant body — while the vendor gateway's
route-dependent strictness remains theirs, so no prior-plan deferred item is resolved by this work.