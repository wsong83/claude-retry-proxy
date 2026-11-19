# Plan: Drop the redacted_thinking placeholder in chat mode; raise the listener accept backlog

**Plan ID:** 2026-11-19-drop-redacted-thinking-chat-placeholder
**Created:** 2026-11-19

<!-- ## Immediate Actions: populated by /update-plan; replaced (not accumulated) on each revision. -->

## Immediate Actions

**Coder:** (no directives — Steps 1–2 complete; both gates PASS; round 2 report filed)

**Tester:** (no directives — Step 3 complete, SUCCESS, 533/533; both Step 2 behavioral legs green)

**Planner:**
- Execute Step 4 (doc sync: provider-modes.html, trace-log.html, test-catalog.html, operations.html, compatibility.html), then Step 5 (inventory sweeps), then mark `ingress-listen-backlog` and `drop-redacted-thinking-chat-placeholder` Resolved in the Issue Log, and proceed to Phase 6 (reviewer).

## Issue Log

Rows ordered newest-first (latest issues at top). New issues are prepended; resolved issues stay in place with updated status.

| Issue | Status | Found | Resolved | Resolved By |
|-------|--------|-------|----------|-------------|
| [tripwire-turn-facts-order](./tmp/reports/2026-11-19-drop-redacted-thinking-chat-placeholder-tripwire-turn-facts-order.json) | Resolved | 2026-11-19 | 2026-11-19 | [coder](./tmp/reports/2026-11-19-drop-redacted-thinking-chat-placeholder-coder-2026-11-19.json) (round 2; both gates independently re-run PASS by the planner) |
| [ingress-listen-backlog](./tmp/reports/2026-11-19-drop-redacted-thinking-chat-placeholder-ingress-listen-backlog.json) | Resolved | 2026-11-19 | 2026-11-19 | [tester](./tmp/reports/2026-11-19-drop-redacted-thinking-chat-placeholder-tester-2026-11-19.json) (Step 2 + both behavioral legs: 3× thread-safety clean, counters 280→280 zero deltas) |
| [drop-redacted-thinking-chat-placeholder](./tmp/reports/defer-issue-drop-redacted-thinking-chat-placeholder.json) | Resolved | 2026-10-24 | 2026-11-19 | [tester](./tmp/reports/2026-11-19-drop-redacted-thinking-chat-placeholder-tester-2026-11-19.json) (Step 1 drop + tripwire, pinned by Step 3 rewrites; adopting-plan row — the deferral file retires via /update-and-commit Step 9.6) |

The second row is this plan's **adopting row** for the standalone deferral filed 2026-10-24 (filing added no row anywhere; three later archived plans explicitly declined adoption). When it reaches `Resolved`, `/update-and-commit` Step 9.6 retires the deferral file.

## Guidance for Coder

**Files to modify:** `src/claude_retry_proxy/transforms_chat.py`, `src/claude_retry_proxy/server.py`, `src/claude_retry_proxy/compat.py` (docstring one-liner only) — source only; no tests, no docs.

**Step-by-step with verification:** Steps 1–2 below; each has an `(auto)` check and a `(scripted)` gate. The coder self-verifies `(auto)` checks and runs the provided scripts. Do not touch `tests/`, `doc/`, `CLAUDE.md`, or `README.md`. Do not change any function signature.

## Guidance for Tester

**Tests to create:**
- **Permanent:** rewrite three existing tests in `tests/test_chat_transform.py` (Step 3) — same file; plus the new `test_proxy_listen_backlog` pin test in `tests/test_retry_streaming.py` (Step 3). No new test files.
- **Temporary:** none.

**Tests to investigate for retirement:**
- Planner candidates: none — no test is retired. Three tests are *rewritten* because they pin the placeholder behavior that Step 1 removes; their replacements assert the drop.
- No test obsolescence identified beyond the three rewrites above.

**Retirement procedure:** not applicable.

**Unchanged surfaces (verify, don't modify):** `tests/test_compat.py` needs no change — the `_reasoning_present` gate reads the raw client body and is unaffected by the forwarded-body change (its docstring phrase is the coder's one-liner in Step 1).

**Behavioral confirmation for Step 2 (two legs — the run-count alone cannot distinguish a fixed queue from a lucky sample):**
1. `test_thread_safety` (`tests/test_retry_streaming.py`) is the canary that surfaced the backlog defect — post-fix it must pass three consecutive isolated runs (`python3 tests/test_retry_streaming.py -t thread-safety`). Pre-fix it failed 3 of 7 isolated runs on this machine.
2. Kernel-counter measurement — the issue report's own `expected_behavior`: snapshot, burst, re-snapshot, require zero deltas:
   ```
   nstat -az | grep -E "ListenDrops|ListenOverflows" > /tmp/nstat_pre.txt
   python3 tmp/verification/2026-11-19-thread-safety-flake-probe.py
   nstat -az | grep -E "ListenDrops|ListenOverflows" > /tmp/nstat_post.txt
   ```
   The `ListenDrops`/`ListenOverflows` values must be identical pre/post (pre-fix they rose +71 across six bursts). Re-run this on demand any time backlog sufficiency is in question.

**Spawn isolation:** the diagnostic probe already carries the canonical spawn-isolation block (doc/test-catalog.html#pattern-spawn-isolation); any tester-authored script that spawns or imports the proxy must carry the same block before its first proxy import AND its first process spawn.

## Summary

**Problem 1 (the adopted deferral).** In chat mode, an Anthropic `redacted_thinking` block with non-empty `data` on a turn carrying no real thinking text is converted into the literal string `[redacted_thinking: data not available]` in the forwarded `reasoning_content`/`reasoning` field, with a dedicated `redacted_thinking_passthrough` trace event and a `placeholder` counter on `reasoning_field_injected`. The operator decided on 2026-10-24 to remove the substitution: the block is unrepresentable in chat mode, a fabricated string in a field a model may read as its own prior reasoning is the *less* honest option, and the placeholder axis is the sole source of a known misreport class. Zero occurrences in every retained trace window (re-confirmed 2026-11-19 on the post-copy trace: 0 events in the retained window). `transforms_response.py` already drops the block unconditionally — this change makes chat mode match response mode.

**Presence is conditional, not automatic** (mega-audit findings 0/3/8/20, verified against `forwarder.py:1079-1111`): the always-present `""` fill runs only when `reasoning_always` is on — a rescue pass, or a (provider, model) pair flagged in `reasoning_roundtrip` (template default `{}`). With only a learned selection and no flag, a redacted-only demanding turn previously carried the placeholder via the per-message write in `_assistant_msg` (gated on `reasoning_text is not None` alone, no always-flag); post-change it forwards **no reasoning field at attempt 1**. The backstop is the reasoning_field rescue: the matched complaint decrements credit, the rescue re-entry forces `reasoning_always=True` and writes `""` — the client is still served, at the cost of one extra upstream round trip per redacted-only demanding turn, and the complaint steers the selection cycle on evidence that says nothing about the field name (the gate classifies the raw body gate-true). The DeepSeek 400 rejects a *missing* field, not empty content.

**Operator direction 2026-11-19 (capture-first, superseding the A/B fork):** any presence fix designed today would rest on untestable assumptions — redacted blocks originate from real Anthropic models, none of which this deployment currently routes through chat mode; the realistic arrival path is a mid-conversation hot-switch from an Anthropic tier into a chat provider. So the delta is accepted **and instrumented**: every request that drops a `redacted_thinking` block emits a `redacted_thinking_detected` event carrying the facts a future patch needs (identity, learned selection, always-flag, per-block turn shapes), correlating by `request_id` with the existing request/rescue/credit events — the full episode, ready to design from. The standing design note lives in `doc/provider-modes.html` (kept in sync by doctrine), the drop-branch code comment points at it, and the Final Results Known Caveats carry it for the archived-plan cross-reference sweep. No deferral is filed — this is a standing watch, not owed work. The alternative design (a learned selection implying the always-present fill) remains deliberately not taken.

**Problem 2 (found in this plan's Phase 1 baseline).** The proxy's listening socket inherits socketserver's `request_queue_size = 5`. A burst of simultaneous connections overflows the kernel accept queue; dropped connections retransmit the SYN after 1 s and usually connect late, but sometimes get RST — the client sees `ConnectionResetError` at ~1.05 s and, because the proxy never sees the request, **no trace entry and no upstream accept exist**. Measured via kernel counters (`ListenDrops`/`ListenOverflows` +71 across six 20-request bursts); the suite's `test_thread_safety` flaked ~30-50% on this machine post-copy while the bare-server control passed. Fix: one class attribute raising the backlog to 128. The issue report carries the full evidence.

**Alternatives rejected:** client-side retries (the client is Claude Code, not this repo); sysctl tuning (`tcp_abort_on_overflow`/`somaxconn` — machine-local, not portable to the Windows host); keeping the placeholder but fixing its counter (contradicts the recorded operator decision); a separate plan for the backlog (folded in on operator approval 2026-11-19 — the ~50% flake rate would otherwise poison this plan's own verification rounds).

**Out of scope:** client keep-alive/connection pooling; trace instrumentation of never-accepted connections (impossible — the proxy never sees them); changes to `tests/test_compat.py` or to `_reasoning_present`'s **predicate** (its behavior is load-bearing post-change — it is what makes the rescue fire on redacted-only turns; a one-line docstring phrase update is in Step 1's scope); any change to the response-mode transform.

## Repo Mode

Public

*Detected at plan creation. Determines: plan archival path, commit-message content, staged files.*

## Document Overrides

| Document | Rule Overridden | Reason |
|----------|----------------|--------|

## Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| Presence delta on unflagged pairs (mega-audit findings 0/3/8/20): with a learned `reasoning_selection` and no `reasoning_roundtrip` flag, a redacted-only demanding turn forwards no field at attempt 1 — one extra rescue round trip per such turn, credit decrement, and selection-steering evidence from a name that was never wrong (the gate reads the raw body, so the complaint is misclassified as name evidence) | Slower requests and possible selection cycling on affected providers | Empirically cold: 0 `redacted_thinking` occurrences and 0 `reasoning_field_injected` events in every retained trace window (re-verified 2026-11-19); the rescue always repairs, the client is never unserved; flagging an affected pair in `reasoning_roundtrip` restores attempt-1 presence without a code change. Accepted per operator direction with the `redacted_thinking_detected` tripwire (Step 1) and the standing design note in `doc/provider-modes.html` — the episode, when it ever fires, carries everything needed to design the real patch |
| The live proxy keeps running pre-change code until restarted (editable install; changes reach it only on restart) | Step 1/2 have no production effect until then | Noted in Final Results; restart is a user action, never the agents' |

## Rollback and Trace-Contract Compatibility

The trace-schema change in Step 1 is **breaking by design**: `redacted_thinking_passthrough` (and its `data_length` field) disappears, and `reasoning_field_injected` loses its `placeholder` key.

- **Historical rows:** retained JSONL (≤5 days, the CLI prune window) keeps carrying the old event/keys until pruned; `doc/trace-log.html` post-Step 4 describes only the new schema. Mixed-schema windows in personal trace archives are expected and accepted.
- **External consumers:** the event never fired in any retained trace window (0 occurrences since tracing began on this machine), so no dashboard or archived analyser can have observed it; the operator accepts the break on that evidence (2026-11-19). The in-repo analyzer references neither identifier (verified by grep).
- **Rollback:** `git revert` the plan's commit, then restart the proxy (`claude-retry-proxy stop && claude-retry-proxy start`) — the editable install means a restart alone restores the prior behavior of the reverted tree. The tests rewritten in Step 3 revert with the same commit (they live in it).

## Proposed Changes

Each step includes verification checks tagged with confidence. `(auto)` = mechanical, coder self-verifies. `(scripted)` = deterministic multi-step, coder runs provided script.
Every step must have at least one verification check executable by its owner (coder steps: coder checks; tester steps: tester verify; planner steps: Evidence).

1. **Step 1:** Remove the redacted_thinking placeholder and add the `redacted_thinking_detected` tripwire (`src/claude_retry_proxy/transforms_chat.py`)
   - Docstring (~L107-112): replace the sentences *"none does (a redacted-thinking placeholder counts as a placeholder, never as real). redacted_thinking blocks with non-empty data are converted to a placeholder;"* with *"none does. redacted_thinking blocks are dropped and counted (content_block_dropped) — the block is unrepresentable in chat mode;"*
   - Delete line ~127 `passthrough = {"redacted_thinking": 0}`.
   - Comment block ~L131-135: `{id(message): (text or None, is_redacted_placeholder)}` → `{id(message): text-or-None}`; drop the "redacted placeholder" clause.
   - Delete line ~153 `reasoning_is_placeholder = False`.
   - Thinking branch ~L161-170: delete the supersede comment (~L165-166) and `reasoning_is_placeholder = False` (~L167); keep `reasoning_text = thinking`.
   - Redacted branch ~L171-188: replace the whole `if isinstance(data, str) and data and reasoning_text is None:` / placeholder-assignment / `log_trace(redacted_thinking_passthrough …)` / `else:` structure with an unconditional:
     ```python
                     if btype == "redacted_thinking":
                         # Unrepresentable in chat mode (the payload is opaque
                         # encrypted material): dropped and counted, matching
                         # transforms_response.py. Presence for a demanding
                         # turn is preserved by the always-present pass ("")
                         # when the policy is active (reasoning_always, a
                         # rescue pass, or a reasoning_roundtrip pair); with
                         # only a learned selection this turn forwards no
                         # field, and the reasoning_field rescue repairs the
                         # complaint if the provider demands presence. Each
                         # dropped block is recorded — turn OUTPUT index and
                         # payload length only — for the per-request
                         # redacted_thinking_detected tripwire, whose
                         # turn-scoped facts are computed after the loop (see
                         # the standing design note in doc/provider-modes.html).
                         dropped["redacted_thinking"] += 1
                         redacted_turns.append((len(out),
                                                len(data) if isinstance(data, str) else None))
                         continue
     ```
     Issue `tripwire-turn-facts-order` (coder round 1): the originally specified per-block dict recorded the turn facts mid-scan, so `[redacted_thinking, tool_use]` recorded `turn_tool_use_seen: false` and the gate could not pass. The fix defers the turn-scoped facts to the emission site, where both accumulators are final.
   - Tripwire (unthrottled, one event per request that dropped any redacted block — operator direction 2026-11-19): initialize `redacted_turns = []` beside the `dropped` dict; after the message loop, next to the `content_block_dropped` emission, add — the turn facts come from the BUILT message and the final `reasoning_by_msg` entry, so block order within a turn is irrelevant:
     ```python
         if dropped["redacted_thinking"] > 0:
             blocks = []
             for turn_index, data_length in redacted_turns:
                 m = out[turn_index]
                 _t = reasoning_by_msg.get(id(m))
                 blocks.append({
                     "data_length": data_length,
                     "turn_has_thinking": isinstance(_t, str) and bool(_t),
                     "turn_tool_use_seen": bool(m.get("tool_calls")),
                 })
             log_trace({
                 "timestamp": _request_transform_timestamp(),
                 "event": "redacted_thinking_detected",
                 "request_id": request_id,
                 "mode": mode,
                 "provider": provider,
                 "tier": tier,
                 "reasoning_selection": reasoning_selection,
                 "reasoning_always": bool(reasoning_always),
                 "conversation_has_tool_calls": bool(tool_use_ids),
                 "blocks": blocks,
             })
     ```
     (`len(out)` recorded at the branch is exactly the index the current assistant turn's message will occupy — the assistant branch appends precisely one message, after its block loop; two redacted blocks in one turn record the same index and both resolve to the same built message.) The upstream's answer needs no new capture: the existing `request` event, the reasoning_field credit/rescue events, and any 400-complaint carry the same `request_id` and complete the episode.
   - Line ~269: `reasoning_by_msg[id(m)] = (reasoning_text, reasoning_is_placeholder)` → `reasoning_by_msg[id(m)] = reasoning_text`.
   - Always-present pass ~L341-364: `text, is_placeholder = reasoning_by_msg.get(id(m), (None, False))` → `text = reasoning_by_msg.get(id(m))`; delete `placeholder_count` from the counter init and the `if is_placeholder:` branch (real_count gains the increment unconditionally); event guard `if empty_count or placeholder_count:` → `if empty_count:`; delete the `"placeholder": placeholder_count,` event key.
   - `src/claude_retry_proxy/compat.py` ~L661-673, `_reasoning_present` docstring only (the predicate is untouched and must keep returning True for redacted turns — it is what lets the rescue fire on such turns post-change): the phrase *"carries reasoning worth echoing (a non-empty thinking block, or a redacted_thinking with non-empty data)"* → *"carries reasoning material whose absence a demanding provider may reject (a non-empty thinking block, or a redacted_thinking with non-empty data)"*.
   → coder verify (auto): grep confirms `redacted_thinking_passthrough`, `reasoning_is_placeholder`, and `[redacted_thinking: data not available]` are absent from the module; the redacted branch is an unconditional count + index/length record, with the tripwire's turn facts computed post-loop from the built messages (order-independent); the `reasoning_field_injected` event dict carries exactly `real` and `empty`; a request dropping any redacted block emits exactly one `redacted_thinking_detected`; the `_reasoning_present` predicate body is byte-identical to pre-change (docstring only); `python3 -c "import claude_retry_proxy.transforms_chat, claude_retry_proxy.compat"` succeeds.
   → coder verify (scripted): `python3 tmp/verification/2026-11-19-drop-redacted-thinking-chat-placeholder-step1.py` — RED calibration 2026-11-19 on the pre-change tree: FAIL (8) before the tripwire was added to the gate, **FAIL (12) after** (the five tripwire checks fail pre-change: the event does not exist; the two legitimately-true checks pass for the right reason). Must print `SUMMARY: PASS` post-change, unedited. The gate carries the canonical spawn-isolation block (doc/test-catalog.html#pattern-spawn-isolation) above its first proxy import; any revision to it must preserve that block.
   → tester verify: the Step 3 rewrites pass (they assert exactly this behavior).

2. **Step 2:** Raise the listener accept backlog on `_ProxyHTTPServer` (`src/claude_retry_proxy/server.py`)
   - In the class body at ~L1459-1471, directly under `allow_reuse_address = sys.platform != "win32"`, add:
     ```python
         # socketserver's default accept backlog is 5; a burst of
         # simultaneous connections (parallel tool fan-outs, test
         # concurrency) overflows it and the kernel drops SYNs — measured
         # 2026-11-19 via TcpExtListenDrops/ListenOverflows deltas (+71)
         # during six 20-request bursts (evidence: plan
         # 2026-11-19-drop-redacted-thinking-chat-placeholder, issue
         # ingress-listen-backlog). A dropped connection never reaches the
         # handler: the client sees a ~1 s SYN-retransmit stall or a
         # ConnectionResetError, and leaves no trace entry. 128 gives
         # realistic fan-outs 25x headroom; somaxconn clamps beyond that.
         request_queue_size = 128
     ```
   → coder verify (auto): `python3 -c "from claude_retry_proxy.server import _ProxyHTTPServer; print(_ProxyHTTPServer.request_queue_size)"` prints `128`; `python3 -c "import claude_retry_proxy.server"` succeeds.
   → coder verify (scripted): `python3 tmp/verification/2026-11-19-drop-redacted-thinking-chat-placeholder-step2.py` — RED calibration 2026-11-19 on the pre-change tree: FAIL (1) — got 5. Must print `SUMMARY: PASS` post-change, unedited. The gate carries the canonical spawn-isolation block above its first proxy import (it imports `claude_retry_proxy.server`); any revision must preserve it.
   → tester verify: `test_thread_safety` passes three consecutive isolated runs, AND the kernel-counter measurement in Guidance for Tester shows zero `ListenDrops`/`ListenOverflows` deltas across the probe bursts (see Guidance for Tester).

3. **Step 3:** Rewrite the placeholder-pinning tests (`tests/test_chat_transform.py` and one new pin test in `tests/test_retry_streaming.py` — tester lane; the coder never touches these files)
   - `test_anthropic_to_chat_messages_redacted_thinking_trace` → rename `test_anthropic_to_chat_messages_redacted_thinking_dropped`; update the aggregator entry (~L2548) accordingly. **Load-bearing assertions** (the discriminating ones — a negative "no passthrough event" check cannot fail once the producer is deleted, so it is belt-and-braces only): `content_block_dropped` carries `dropped_counts.redacted_thinking == 1` for a non-empty-data redacted-only turn, and the exact forwarded message shape (no reasoning field at default selection). Carry over the old test's empty/missing-data leg (old L143-164): `data: ""` and a block with no `data` both count, `dropped_counts.redacted_thinking == 2` — that behavior is untouched by this plan and must not silently regress. Also keep: with a selection + `reasoning_always` + a tool call, the forwarded field is `""` and `reasoning_field_injected` counts `real=0, empty=1` with **no `placeholder` key**.
   - `test_anthropic_to_chat_injection_trace_counts` (~L446): the redacted turn fixture now behaves as a bare turn — expect `real=1, empty=2` and no `placeholder` key; drop the `placeholder_text` fixture.
   - `test_anthropic_to_chat_real_thinking_supersedes_placeholder` (~L543) → rename `test_anthropic_to_chat_real_thinking_and_redacted_dropped`; update the aggregator entry (~L2556). Part (a) keeps (real text forwarded, no injected event) — its fixture content order `[redacted_thinking, thinking, tool_use]` is also the pin for turn-scoped tripwire facts: the event for this request must carry `blocks[0].turn_has_thinking == true` (the real text wins regardless of block order). Part (b) counts `real=1, empty=1` with no `placeholder` key. Part (c) becomes the drop guard: a redacted-only demanding turn forwards `""`, is counted `empty=1`, and fires `content_block_dropped` with `dropped_counts.redacted_thinking == 1`.
   - Tripwire assertions (fold into the renamed redacted test): a request dropping one redacted block emits exactly one `redacted_thinking_detected` carrying `reasoning_selection`, `reasoning_always`, `conversation_has_tool_calls`, and a `blocks` list whose length equals the dropped count with the per-block shape keys (`data_length`, `turn_has_thinking`, `turn_tool_use_seen`); a two-redacted-block fixture yields one event with `len(blocks) == 2`; a request with no redacted blocks emits none.
   - New case (mega-audit findings 8/20): **selection active + `reasoning_always=False`** (the unflagged-pair state): a redacted-only demanding turn forwards **no reasoning field**, is counted in `content_block_dropped`, fires the tripwire event, and fires no `reasoning_field_injected` event — pinning the accepted presence delta (attempt-1 absence; the rescue is the backstop). Fixture: `reasoning_selection="reasoning_content"`, omit `reasoning_always`.
   - `test_anthropic_to_chat_messages_thinking_stripped` (~L68): docstring AND the `fail`/`pass_` messages — "redacted_thinking non-empty data is folded into the same default" → "redacted_thinking blocks are dropped like empty thinking"; the L84 fail text ("real thinking still wins over the redacted placeholder") → "default selection must emit no reasoning field"; the L86 pass label ("redacted_thinking placeholder suppressed by real thinking") → "default emits no reasoning field; redacted_thinking dropped". Assertions unchanged.
   - New permanent pin test `test_proxy_listen_backlog` in `tests/test_retry_streaming.py`: asserts `from claude_retry_proxy.server import _ProxyHTTPServer; _ProxyHTTPServer.request_queue_size == 128` — pins Step 2 in the suite forever, so a future refactor reverting the backlog cannot pass silently (the step-2 gate script retires with this plan). Register it in the module's `ALL_TESTS`.
   → tester verify: the rewritten tests and the new pin test pass under `python3 tests/test_chat_transform.py` and `python3 tests/test_retry_streaming.py -t proxy-listen-backlog`; `test_thread_safety` passes 3 consecutive isolated runs (`python3 tests/test_retry_streaming.py -t thread-safety`); `python3 scripts/check_spawn_isolation.py` exits 0 (corpus measured before the suite); the full suite (`python3 tests/test_claude_proxy.py`) is green.

4. **Step 4:** Documentation sync (planner lane — executed after the coder round)
   - `doc/provider-modes.html` ~L131: the request-direction row header loses "with non-empty `data`" (post-change every `redacted_thinking` is dropped regardless of data); the row states the block is dropped and counted in `content_block_dropped`, exactly as in response mode; the always-present pass fills such a turn with `""` **when the policy is active** (always-present flag, rescue pass, or `reasoning_roundtrip` pair); with only a learned selection the turn carries no reasoning field and the rescue is the backstop; no placeholder is fabricated. Directly after the row, add the **standing design note** (operator direction 2026-11-19, no deferral filed): presence behavior for redacted-only turns is deliberately undetermined pending observation — when `redacted_thinking_detected` first fires, correlate by `request_id` with the request/rescue/credit events and design the presence patch from the captured episode. ~L699: delete the `redacted_thinking_passthrough` event row; add the `redacted_thinking_detected` row (a request dropped one or more redacted_thinking blocks; carries the learned selection, the always-flag, conversation tool-call presence, and per-block shapes — the tripwire behind the standing design note). ~L700: rewrite the `reasoning_field_injected` row in full — carries `real` and `empty` only; fires only when at least one blank was filled; delete both "placeholder" phrases.
   - `doc/trace-log.html` ~L153: delete the `redacted_thinking_passthrough` row; add the `redacted_thinking_detected` row. ~L154: the injection-event row → `real`/`empty` only, guard fires on a non-zero empty fill. ~L317: remove the old event name from the chat-mode event list and add the new one.
   - `doc/test-catalog.html` ~L397, ~L433-434: update the three test-index entries to the new names and drop behavior; add an entry for `test_proxy_listen_backlog`.
   - `doc/operations.html` readiness section: one sentence — the listener's accept backlog is 128 (burst tolerance); a connection the kernel drops under extreme overload never reaches the handler, so it leaves no trace entry; the drops are measurable on demand via `nstat -az | grep -E "ListenDrops|ListenOverflows"` deltas around a burst.
   - `doc/compatibility.html` gate paragraph ("What the gate reads", ~L274-284): after the sentence about reading the raw client body, add the post-change divergence — a demanding turn whose only reasoning is a `redacted_thinking` block stays gate-true while the chat transform drops the block, so the forwarded body carries no reasoning field unless the always-present policy fills `""`; the matched complaint then runs the usual credit decrement and the rescue (which repairs with `""`), so the credit behavior is unchanged. The gate's own description (non-empty `thinking`, or `redacted_thinking` with non-empty `data`) is unchanged.
   - `CLAUDE.md` / `README.md`: verified no redacted-placeholder mentions (2026-11-19 grep) — no change.
   → Evidence: `git grep -nE "redacted_thinking_passthrough|reasoning_is_placeholder" -- doc/` returns empty; `git grep -n "redacted_thinking" -- doc/compatibility.html` shows only the gate's unchanged input conditions plus the added divergence sentence; `git grep -nE "supersedes_placeholder|redacted_thinking_trace" -- doc/ tests/` returns empty (no stale test names).

5. **Step 5:** Inventory sweep and metadata finalization (planner lane — executed at Final Results)
   - Verify the trace-event inventory has no remaining producer or consumer of the removed identifiers outside archived plans: `git grep -nE "redacted_thinking_passthrough|reasoning_is_placeholder" -- src tests doc scripts README.md CLAUDE.md` must be empty (the `-E` flag makes the alternation portable; an error exit is a failure, not a pass), and no stale test names remain: `git grep -nE "supersedes_placeholder|messages_redacted_thinking_trace" -- src tests doc` must be empty.
   - Record `retire_inventory` in Plan Metadata: this plan's round reports and the three transient `tmp/verification` artifacts — the two step gates (`-step1.py`, `-step2.py`) and the diagnostic probe (`2026-11-19-thread-safety-flake-probe.py`).
   → Evidence (executed 2026-11-19): sweep 1 (`git grep -nE "redacted_thinking_passthrough|reasoning_is_placeholder" -- src tests doc scripts README.md CLAUDE.md`) returns exactly two lines, both negative absence-assertions in the rewritten `tests/test_chat_transform.py` ("the removed redacted_thinking_passthrough event must not fire") — zero producer or consumer sites; sweep 2 (stale test names) returns empty; `check_doc_anchors.py` PASS (271 anchors resolved, 8 files scanned, no secret shapes); `redacted_thinking_detected` present in src (2), tests (14), and all four edited doc pages.

## Guidance for Planner

Documentation tasks you will execute yourself (not the coder):

- **Files to modify:** `./doc/provider-modes.html`, `./doc/trace-log.html`, `./doc/test-catalog.html`, `./doc/operations.html`, `./doc/compatibility.html`
- **When:** after the coder round completes (Step 4), and Step 5 at Final Results.
- **What to sync:** the rows and sections listed in Step 4, matching the implemented behavior exactly — including the conditional presence wording (policy-active fill; learned-selection absence with the rescue backstop) — no exact counts (no test counts, no measured figures beyond the constant 128 and the kernel-counter measure-on-demand command).

## History

| Date | Event | Conclusion | Dismissed |
|------|-------|------------|-----------|
| 2026-11-19 | Initial plan | Adopted the 2026-10-24 deferral (operator decision recorded in the report; re-confirmed live 2026-11-19 — placeholder axis intact, 0 trace occurrences, response-mode parity verified); Phase 1 baseline surfaced `ingress-listen-backlog` via the thread-safety flake (kernel-counter evidence in the issue report), folded in on operator approval; verification scripts authored and calibrated RED (step1: FAIL (8), step2: FAIL (1)) | — |
| 2026-11-19 | Mega-audit ([report](./tmp/reports/2026-11-19-drop-redacted-thinking-chat-placeholder-mega-audit-2026-11-19.json)) | 30 unique findings (1 High, 11 Medium, 18 Low): all addressed in this revision — the High (isolation requirement unstated in the plan) and the Mediums (conditional presence claim corrected across Summary/Step 1 comment/doc rows + accepted-delta Risks row; rollback/trace-compatibility section added; permanent `request_queue_size` pin test; kernel-counter behavioral gate; metadata unions synced; provider-modes edit instructions expanded; `doc/compatibility.html` added to the doc surface; sweep greps made portable and extended to stale test names) — the 18 Lows were folded into the same edits (gate docstrings, test message strings, empty-data leg carried over, durable comment citation, load-bearing-assertion note, report filename convention); zero findings dismissed without action | — |
| 2026-11-19 | Spec revision (operator direction, pre-round) | Capture-first supersedes the A/B fork: the presence delta stays accepted but is instrumented — Step 1 adds the unthrottled per-request `redacted_thinking_detected` tripwire (per-block shapes inside); the patch-design remark lives as a standing note in `doc/provider-modes.html` + the drop-branch comment + Final Results caveats, **not** as a deferral (deferral semantics would owe a resolution the observation schedule does not guarantee); rationale: redacted blocks originate from real Anthropic models, absent from this deployment's chat-mode traffic — realistic arrival path is a mid-conversation hot-switch from an Anthropic tier; step1 gate extended with tripwire checks and re-calibrated RED (see below) | — |
| 2026-11-19 | Spec revision (/update-plan, post-coder-round-1) | Coder round 1 blocked on `tripwire-turn-facts-order` (coder-filed, verified against the tree): the tripwire's turn facts were recorded mid-scan, so `[redacted_thinking, tool_use]` recorded `turn_tool_use_seen: false` and the gate could not pass unedited; Step 1's snippets revised — the branch records only the turn's output index + payload length, and the emission site computes turn-scoped facts from the built messages and final `reasoning_by_msg`; step1 gate gains the `[redacted_thinking, thinking]` ordering check (turn_has_thinking leg, the issue's second uncaught instance) and Step 3's part (a) names its fixture as that pin; rounds 2 proceeds | — |
| 2026-11-19 | Implementation round (coder, round 2) | SUCCESS — Steps 1 and 2 complete; step1 gate PASS (17 checks incl. the ordering check), step2 gate PASS, build pass; planner independently re-ran both gates (PASS) and confirmed the tree (`request_queue_size = 128` at server.py:1482; three files modified); `tripwire-turn-facts-order` marked Resolved; no new issues filed ([report](./tmp/reports/2026-11-19-drop-redacted-thinking-chat-placeholder-coder-2026-11-19.json)) | — |
| 2026-11-19 | Implementation round (tester) | SUCCESS — Step 3 complete (three rewrites with pre-rewrite baseline proving the new assertions discriminate; new `redacted_selection_without_always` delta pin; `test_proxy_listen_backlog` pin); Step 2 behavioral legs both green: thread-safety 3× consecutive 20/20 (ex-flake gone) and kernel counters 280→280 zero deltas across six probe bursts (pre-fix +71); full suite 533/533 incl. thread-safety; spawn isolation exit 0; no issues filed ([report](./tmp/reports/2026-11-19-drop-redacted-thinking-chat-placeholder-tester-2026-11-19.json)) | — |
| 2026-11-19 | Review ([report](./tmp/reports/2026-11-19-drop-redacted-thinking-chat-placeholder-review-2026-11-19.json)) | Verdict non-blocking — 0 Critical / 1 Warning / 4 Suggestion; the reviewer independently re-ran the five rewritten/new chat-transform tests (5/5 PASS), the backlog pin (PASS), and check_doc_anchors (PASS), and verified the post-loop tripwire's order-independence, the drop-vs-gate/rescue interaction, and the backlog attribute wiring as correct. The Warning (test-catalog index entry for `test_proxy_listen_backlog` missing — a Step 4 gap) and two doc-clarity Suggestions (per-pass event wording; compatibility credit-behavior phrasing) were FIXED in the doc surfaces immediately; anchors re-verified PASS (272) | [review-per-pass-wording](./tmp/reports/2026-11-19-drop-redacted-thinking-chat-placeholder-review-2026-11-19.json) fixed; [review-credit-behavior-phrasing](./tmp/reports/2026-11-19-drop-redacted-thinking-chat-placeholder-review-2026-11-19.json) fixed; [review-turn-invariant-comment](./tmp/reports/2026-11-19-drop-redacted-thinking-chat-placeholder-review-2026-11-19.json) Suggestion deferred — an inline invariant comment/bounds guard on `out[turn_index]` in source is the coder lane with no round running; recorded as a follow-up improvement, behavior verified correct; [review-backlog-comment-precision](./tmp/reports/2026-11-19-drop-redacted-thinking-chat-placeholder-review-2026-11-19.json) Suggestion deferred — "25x" is vs the old default 5 and "somaxconn" is Linux-specific; cosmetic comment precision in source, same lane; reviewer hunches recorded in Final Results Known Caveats |

## Plan Metadata

Fenced ```json block — the machine contract read by `parsePlanContext` (JSON-first, regex fallback). **Update it on every revision.**

```json
{
  "plan_id": "2026-11-19-drop-redacted-thinking-chat-placeholder",
  "steps": ["Step 1: Remove the redacted_thinking placeholder and add the redacted_thinking_detected tripwire", "Step 2: Raise the listener accept backlog on _ProxyHTTPServer", "Step 3: Rewrite the placeholder-pinning tests", "Step 4: Documentation sync", "Step 5: Inventory sweep and metadata finalization"],
  "coder_files": ["src/claude_retry_proxy/transforms_chat.py", "src/claude_retry_proxy/server.py", "src/claude_retry_proxy/compat.py"],
  "tester_files": ["tests/test_chat_transform.py", "tests/test_retry_streaming.py"],
  "doc_files": ["./doc/provider-modes.html", "./doc/trace-log.html", "./doc/test-catalog.html", "./doc/operations.html", "./doc/compatibility.html"],
  "verification_scripts": ["./tmp/verification/2026-11-19-drop-redacted-thinking-chat-placeholder-step1.py", "./tmp/verification/2026-11-19-drop-redacted-thinking-chat-placeholder-step2.py", "./tmp/verification/2026-11-19-thread-safety-flake-probe.py"],
  "retire_inventory": ["./tmp/reports/2026-11-19-drop-redacted-thinking-chat-placeholder-mega-audit-2026-11-19.json", "./tmp/reports/2026-11-19-drop-redacted-thinking-chat-placeholder-coder-2026-11-19.json", "./tmp/reports/2026-11-19-drop-redacted-thinking-chat-placeholder-tester-2026-11-19.json", "./tmp/reports/2026-11-19-drop-redacted-thinking-chat-placeholder-review-2026-11-19.json", "./tmp/verification/2026-11-19-drop-redacted-thinking-chat-placeholder-step1.py", "./tmp/verification/2026-11-19-drop-redacted-thinking-chat-placeholder-step2.py", "./tmp/verification/2026-11-19-thread-safety-flake-probe.py"],
  "repo_mode": "Public",
  "document_overrides": []
}
```

## Audit Accumulation

*Counters reset when mega-audit runs. Used by Phase 5 entry trigger.*

| Counter | Value | Last Updated |
|---------|-------|--------------|
| issues_resolved_since_audit | 1 | 2026-11-19 (tripwire-turn-facts-order resolved by coder round 2) |
| steps_changed_since_audit | 1 | 2026-11-19 (Step 1 snippets revised post-round-1) |
| files_changed_since_audit | 0 | 2026-11-19 |

## Documentation

Deep reference lives in `doc/` (indexed by `doc/content.html`). This plan's doc surfaces are listed in Step 4; `doc/test-catalog.html` indexes the suite.

## Final Results

**Status: COMPLETED** (2026-11-19)

**What was built:** chat mode drops `redacted_thinking` blocks outright (matching response mode), with the unthrottled `redacted_thinking_detected` tripwire capturing identity, learned selection, always-flag, tool-call presence, and per-block turn-scoped shapes per forward pass; the per-request `""`-fill presence semantics are unchanged and the accepted presence delta (learned-selection-only turns forward no field at attempt 1; the rescue repairs) is instrumented by the tripwire and documented as a standing design note (`doc/provider-modes.html#redacted-standing-note`); `_ProxyHTTPServer.request_queue_size = 128` ends the ingress-burst resets (kernel-counter-verified: `ListenDrops`/`ListenOverflows` 280→280 across six 20-request bursts, pre-fix +71); `compat.py`'s `_reasoning_present` docstring phrase updated, predicate untouched; three placeholder-pinning tests rewritten under new names with a pre-rewrite baseline proving they discriminate, a new delta pin (`redacted_selection_without_always`), and a permanent backlog pin (`test_proxy_listen_backlog`); five doc pages synced (provider-modes, trace-log, test-catalog, operations, compatibility), anchors PASS (272).

**Rounds:** coder ×2 (round 1 blocked on `tripwire-turn-facts-order` — the gate caught the plan's own mid-scan turn-fact design; revised and completed in round 2), tester ×1 — SUCCESS. Review: non-blocking (0 Critical / 1 Warning / 4 Suggestion); the Warning (missing test-catalog index entry) and two doc-clarity Suggestions fixed immediately; two source-comment Suggestions recorded as follow-ups (planner lane cannot edit source; behavior verified correct).

**Test results:** 533/533 passing, 0 failed, 0 skipped (full suite incl. `test_thread_safety` — the ex-flake that surfaced the backlog defect now passes deterministically: 3× isolated 20/20 plus in-suite). Both step gates PASS. Spawn-isolation corpus: 2 spawners, 0 fail, 7 skip.

**Review verdict:** non-blocking (see History). Reviewer independently re-ran the rewritten tests and the pin.

**Known Caveats:**
- **Standing redacted_thinking design note** (operator direction 2026-11-19): presence behavior for redacted-only turns is deliberately undetermined pending observation — when `redacted_thinking_detected` first fires (realistic path: a mid-conversation hot-switch from an Anthropic tier into a chat provider), design the presence patch from the captured episode. Note also that the event is per forward *pass*: a rescued client request re-emits it (up to three).
- The tripwire's `conversation_has_tool_calls` (from the request-level `tool_use_ids` set) and the always-present pass's per-message `tool_calls` are different signals by design; `turn_tool_use_seen` reflects *valid* built tool_calls (a degraded `tool_use` reads false).
- Reviewer hunches (unaddressed, not findings): `tests/_harness.py` `_MockHTTPServer` keeps socketserver's backlog 5 while its docstring claims to mirror `_ProxyHTTPServer` (now 128) — a future burst test against a harness mock would exercise the old default; the plan's Immediate-Actions cycle left no round to touch test helpers.
- Two source-comment Suggestions deferred (turn-index invariant comment; backlog comment "25x/somaxconn" precision) — cosmetic, behavior verified correct.
- The live proxy runs pre-change code until restarted (editable install); restart is a user action.

**Deferred issues adopted and resolved:** `drop-redacted-thinking-chat-placeholder` (2026-10-24) — resolved by this plan; its report file retires via `/update-and-commit` Step 9.6 (the adopting-plan row above is the trigger). `ingress-listen-backlog` was found and resolved within this plan. No prior completed plan deferred an item this implementation resolves (the adopted deferral was standalone; the remaining open deferrals on disk are unrelated to this plan's surfaces), so no Cross-References section is emitted.
