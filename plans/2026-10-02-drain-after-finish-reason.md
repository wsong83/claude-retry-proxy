# Plan: Drain SSE stream after finish_reason to capture trailing usage and tool_call frames

**Project:** D:\proj\claude-retry-proxy
**Plan ID:** 2026-10-02-drain-after-finish-reason
**Created:** 2026-10-02
**Revised:** 2026-10-03 (Option B — expanded to capture both usage and tool_call frames after finish_reason; iteration 3 — fixed 66 pre-implementation mega-audit findings; revision 4 — post-implementation mega-audit: 36 findings triaged, doc-count arithmetic corrected, `stream_options` mechanism and socket-timeout steps re-specified, 4 decisions raised and resolved; revision 5 — **D4 reversed by user ruling**: the parseability gate is dropped in both chat paths, adding step 11 and a doc-sync pass; coder round 3 and tester round 3 landed against it, and the planner reconciled the documentation)

## Immediate Actions

*Rounds 3 (coder and tester) are COMPLETE. The planner doc reconciliation is COMPLETE. The
Phase 6 re-review is COMPLETE (commit gate PASSES, non-blocking) and its two Warnings — both
documentation defects from the planner's own doc-sync pass — are fixed.

**Rounds 4 (coder and tester, one each) are COMPLETE**, ruled by the user to close the two items
the re-review left open. Both landed; the planner doc follow-up for the narrowed last-wins rule
and the round-4 recount are done. **All work is complete — what remains is the user's commit
approval.***

**Coder — sub-step 12 (round 4; the fine sub-steps run 1-11, this continues them):**
- In `src/claude_retry_proxy/server.py`, at the drain-mode revision guard inside `handle_frame` (**line 1887**), change `if revised is not None:` to `if revised:`, so a trailing empty-string `finish_reason` is not accepted as a revision of an already-resolved one.
- **Do not touch the initial assignment** at `server.py:1988`, nor `handle_frame`'s `if finish_reason is not None:` gate at 1936-1938. Those are what record a genuinely empty reason when it *is* the provider's answer; `test_chat_sse_empty_finish_reason_no_change` pins that they stay as they are.
- Keep the existing comment and extend it: the reason a falsy value is refused is that the drain's revision path exists to honour a provider *correcting itself* — `"stop"` to `"tool_calls"` — and an empty string is the absence of an answer, not a correction. A `null` on every non-final chunk is already excluded by the same guard; this closes the empty-string case beside it.
- Scope: this one line plus its comment. No other behavior in the drain changes.

**Tester — round 4:**
- Add a permanent test for the guard: a stream that resolves `finish_reason: "tool_calls"` with a tool block emitted, then sends a later frame carrying `finish_reason: ""`. Assert the emitted `stop_reason` is `tool_use` (the resolved value survives the empty revision) and that no `chat_sse_tool_degradation` event is logged — the spurious degradation the reviewer identified must be gone. Register it in `ALL_TESTS`.
- Confirm `test_chat_sse_empty_finish_reason_no_change` still passes untouched — the initial-empty case must still record the empty value.
- **Fix the stale rationale in the test docstring at `tests/test_chat_sse.py:2077-2078`**: it says the suppressed deltas' "blocks are closed by the terminal sequence", which is the same false mechanism step 10 removed — `terminal()` runs *after* the drain, so nothing is closed while it runs. Restate it as the policy choice the docstring's siblings now use. This is a tester-lane file; the planner cannot edit it.
- Re-run the module, then the full suite with a live proxy, and report both counts.

**Coder — DONE (round 3, 15:26–15:30, exit 0, build pass):**
- Step 8: in the `finish_reason == "tool_calls"` branch, replace the parseability gate with `sr = "tool_use" if emitted_tool_use else None`. Keep `close_open_tool_blocks(validate=True)` (it still feeds the `chat_sse_tool_degradation` counters) and keep every counter incrementing — only the `if` condition changes. **Landed and verified in source (server.py:2053-2059).**
- Step 11: in `transforms_chat.py`, drop the `or parsed_args == {}` term from the buffered guard (`if parsed_args is None:`) so a zero-argument tool call is emitted as a real `tool_use` block. Leave `transforms_response.py` alone — it already accepts `{}`. **Landed and verified (transforms_chat.py:468).**
- Step 10: correct the drain paragraph of the `_stream_chat_sse_to_anthropic` docstring and the drain-mode guard comment — the "Anthropic client rejects deltas on a closed block" mechanism is false (`terminal()` now runs after the drain); restate it as a policy choice. **Landed — a repo-wide search for the stale rationale now returns nothing in `server.py`, `transforms_chat.py`, or `doc/provider-modes.html`.**
- Leave the EOF/truncation path, the `stream_options` handling, and the socket-timeout work as they stand — all verified landed and passing.

**Tester — DONE (round 3, 15:31–15:53, exit 0; report `2026-10-02-drain-after-finish-reason-tester-2026-10-03-2.json`):**
- Six candidate tests flipped to `tool_use` (`unparseable_arguments_at_close`, `fragments_missing_index`, `too_many_parallel_tools`, `mixed_parseable_unparseable_finish`, `non_dict_arguments_at_close`, `frame_dropped_guard`). The two zero-block candidates (`malformed_tool_call_degrades`, `conflicting_metadata`) and the `no_deltas_tool_calls_finish` guard verified to stay `null`.
- The four other-path tests (`tool_call_eof_without_finish`, `pending_buffer_cap_exceeded`, `empty_finish_reason_no_change`, `unmapped_finish_with_tools`) left at `null`.
- `test_chat_anthropic_to_chat_zero_arg_tool` added to `tests/test_chat_transform.py`, registered as `chat-zero-arg-tool`.
- Verified alone, per-module (SSE 46/46, transform 43/43) and as a full suite with a live proxy running: **361/361, 0 failed, 0 skipped**. The single warning is the known deferred issue `no-proxy-stop-trace-warning`.
- Direct evidence the flips are coupled to the code: before the tester's edits the landed coder change made exactly the six candidates fail with "... must degrade stop_reason to null, got 'tool_use'".

**Planner — DONE (this revision):**
- Recounted with `grep -cE 'def (test_|doc_)' tests/*.py` → **46 / 43 / 361** and updated all three `doc/test-catalog.html` count sites (grand total 360→361, per-file row 42→43, per-file heading 42→43).
- Rewrote the `#malformed-args` section of `doc/provider-modes.html` per the two Document Overrides — `{}` is no longer listed as malformed, and the `null` stop-reason rule is rescoped to zero emitted blocks with the buffered/streaming split stated.
- Applied the tester's two flagged doc-vs-test contradictions: six stale per-test descriptions in `doc/test-catalog.html` updated, the truncated name `test_chat_sse_empty_finish_reason` corrected to `test_chat_sse_empty_finish_reason_no_change`, and the new `chat-zero-arg-tool` entry added.
- Fixed a pre-existing defect found while verifying the count arithmetic: `doc/test-catalog.html` listed **26** entries under a heading declaring **25** for `test_admin.py`. The extra entry, `test_admin_reload_validates_key_names`, names a test that exists **nowhere** in `tests/` (verified by a scan of every test module) and asserts a behavior the code does not have — the reload handler validates the *in-memory* tier set against in-memory vendor key names (`server.py:2546-2551`) and never re-reads tiers from disk (`server.py:2471-2475`). The orphan was deleted; all 17 per-file sections now balance against their headings and the page sum equals the source count.
- Compensated for the one **irreducible ambiguity** carried into this round: the plan said eight candidate tests but only six have fixtures that emit a tool block. The tester resolved it by fixture inspection rather than by count, and the two zero-block candidates were verified to stay `null` — the outcome the plan's own guard sentence demands.

## Issue Log

| Issue | Status | Found | Resolved | Resolved By |
|-------|--------|-------|----------|-------------|
| [trailing-usage-chunk-never-read](./tmp/reports/defer-issue-trailing-usage-chunk-never-read.json) | Resolved | 2026-10-02 | 2026-10-03 | This plan — the drain reads trailing frames to EOF/`[DONE]`/bound and captures the usage chunk; `stream_options: {include_usage: true}` is now sent for streaming chat requests. Verified by `chat-sse-usage-after-finish-reason` and `chat-sse-usage-and-tool-calls-after-finish`. |
| [finish-before-tool-calls-dropped](./tmp/reports/defer-issue-finish-before-tool-calls-dropped.json) | Resolved | 2026-10-02 | 2026-10-03 | This plan — the drain captures `tool_calls` deltas arriving after `finish_reason` and the stop reason is upgraded to `tool_use`. Verified by `chat-sse-tool-calls-after-finish-reason` (stop_reason is `tool_use`). |
| [drain-deadline-not-enforced-on-blocking-read](./tmp/reports/2026-10-02-drain-after-finish-reason-drain-deadline-not-enforced-on-blocking-read.json) | Resolved | 2026-10-03 | 2026-10-03 | This plan, coder round 2 — steps 5-6 install a socket read timeout tracking the remaining drain budget and step 8 restores it. Verified: `python tests/test_chat_sse.py --test chat-sse-drain-time-deadline` → PASS "drain bounded, terminal emitted in 5.0s" (was FAIL "no message_stop within 20s"). |
| [stale-test-state-file-pid-reuse](./tmp/reports/defer-issue-stale-test-state-file-pid-reuse.json) | Open | 2026-10-03 | — | — (out of scope: test-infrastructure isolation, predates this plan) |
| coder-auto-tag-on-a-test-run | Resolved | 2026-10-03 | 2026-10-03 | This plan — coder round 4 flagged that `Guidance for Coder` tags a *test invocation* (`python tests/test_chat_sse.py --test chat-sse-drain-time-deadline`) as `coder verify (auto)`, which the coder lane is barred from executing, so the check never ran as tagged. The check itself did run, in the tester lane. Fixed by annotating the line in place (an Issue Log row plus a note at the tag) rather than rewriting it — the guidance block is the historical record of what the coder was asked to do. The lesson is a plan-authoring one: `(auto)` reads as machine-executable and must not be applied to lane-forbidden actions. |
| drain-bound-test-precision | **Won't fix — confirmed by user 2026-10-03** | 2026-10-03 | 2026-10-03 | The tester's `DRAIN_BOUND_TEST_SECONDS = 20` (`tests/test_chat_sse.py:47`) cannot distinguish a 5 s drain from a 19 s one, so `chat-sse-drain-time-deadline` proves the `MAX_DRAIN_SECONDS` bound only to within 4× the asserted figure. Raised by the mega-audit's edge-case-explorer, repeated by the Phase 6 re-review and the tester. **User ruled: won't fix** — the test's discriminating job is *bounded vs the 300 s upstream pin*, and 20 s separates those two by more than an order of magnitude; tightening it would buy precision against a failure mode nothing has observed while adding flakiness risk on a loaded machine. The ruling was explicitly requested and given, not assumed. |
| buffered-path-stop-no-upgrade | **Won't fix — confirmed by user 2026-10-03** | 2026-10-03 | 2026-10-03 | The buffered `_chat_to_anthropic` maps `finish_reason: "stop"` plainly (`transforms_chat.py:491-494`), so a buffered response carrying a tool block reports `end_turn` where the same turn streamed reports `tool_use` (the streaming upgrade lives at `server.py:2060-2066`). Surfaced by the Phase 6 re-review as its first Warning — filed there as a *documentation-accuracy* defect, since the doc asserted the upgrade unqualified in the buffered section. The doc is fixed; the behavior is **pre-existing and untouched by this plan** (this plan's only buffered change is the `{}` check at step 11), and the divergence is narrow because `tool_calls` is what providers normally send alongside tool calls and that row agrees on both paths. **User ruled: won't fix, documented only** — the mapping table now states the divergence by path so it cannot surprise a reader. |

## Guidance for Coder

**Files to modify:**
- `src/claude_retry_proxy/server.py` — the `_stream_chat_sse_to_anthropic` method
- `src/claude_retry_proxy/transforms_chat.py` — add `stream_options: {include_usage: true}` to the chat-mode request

**Context:**

The chat-mode SSE read loop in `_stream_chat_sse_to_anthropic` returns from the stream the moment it processes a `finish_reason` chunk (line 1949: `return first_byte_ms`). This causes two bugs:

1. **Trailing usage chunk never read** (deferred issue `trailing-usage-chunk-never-read`): OpenAI documents `stream_options.include_usage` as emitting the usage chunk as the final data frame, AFTER the chunk carrying `finish_reason`. The proxy never sees that usage; `terminal()` synthesizes `message_delta` with zeros. Additionally, the proxy never sends `stream_options: {include_usage: true}` in the request, so some providers may not emit usage at all.

2. **Late tool_call frames dropped** (deferred issue `finish-before-tool-calls-dropped`): The `opencode-go-chat` provider (model `longcat-2.5-preview-free`) sometimes sends `finish_reason: "stop"` on a chunk that arrives before the tool_call frames. The proxy reads `finish_reason: "stop"`, maps it to `end_turn`, calls `terminal()`, and returns — dropping the tool_call frames that follow. The Claude Code client sees `end_turn` and waits for user input, forcing the user to type "continue".

**The fix (Option B — drain with tool_call capture):**

Replace the immediate `return` at the `finish_reason` chunk with a **two-phase approach**:

**Phase 1 — Normal streaming** (current behavior): Process frames normally. When `finish_reason` is seen, record it in `finish_reason_seen` but DON'T return. Instead, switch to drain mode.

**Phase 2 — Drain mode**: Keep reading frames until EOF, `[DONE]`, byte budget, or time deadline. During drain:
- **Still process** `tool_calls` deltas (capture late tool calls — these get their own `content_block_start`)
- **Still capture** `usage` chunks (capture trailing usage)
- **Suppress** `content` and `reasoning` deltas (don't emit text/thinking after finish — the Anthropic client rejects deltas on closed blocks)
- **Stop** at `[DONE]` or EOF or byte budget or time deadline

After the drain, call `terminal()` with the correct stop reason. If tool calls were captured during drain, upgrade the stop reason to `"tool_use"`.

**Why suppress text/reasoning but capture tool_calls?**

The Anthropic SSE protocol expects: `content_block_start` → `content_block_delta` (many) → `content_block_stop` → `message_delta` → `message_stop`. If we emit text deltas AFTER `terminal()` has closed the block, the client sees deltas on a closed block — a protocol violation. Tool calls are different: they get their own `content_block_start` when the tool metadata (id + name) arrives, so a tool call that starts during drain is a new block, not a delta on a closed block.

**Key constraints:**

- `finish_reason_seen` holds the finish reason VALUE (possibly `""` or an unmapped string). Test with `is not None`, NEVER with truthiness.
- The drain must suppress `content` and `reasoning`/`reasoning_content` deltas. Use a NEW counter `post_finish_suppressed` (not `scalar_after_tools_dropped`, which has a different meaning).
- The drain MUST still process `tool_calls` deltas via `process_tool_calls()`.
- The drain MUST still capture `usage` from trailing chunks.
- The drain MUST stop at `[DONE]` — use a `drain_done` flag checked at the top of the OUTER read loop (a `break` inside the inner frame loop only exits the inner loop).
- The drain MUST be bounded by BOTH a byte budget (`MAX_DRAIN_BYTES = 64 * 1024`) AND a time deadline (`MAX_DRAIN_SECONDS = 5`). The time deadline is the primary bound — it must be well under the 30 s drain-and-swap timeout.
- **The time deadline MUST be enforced at the point of blocking, not only after a read returns.** A provider that sends `finish_reason` and then goes silent holds the socket open; the upstream connection is opened with `timeout=300` (server.py:889/891), so a post-read check alone leaves the worker thread — and `_inflight_count` — pinned for up to 300 s. The drain installs a socket read timeout tracking the remaining budget (step 5), recomputes it per chunk (step 6), and restores the original value after the drain (step 8).
- The drain MUST respect the existing size cap (`SETTINGS.max_response_size`) and disconnect error handling (`_DISCONNECT_ERRORS`).
- `terminal()` must be called AFTER the drain, not before.
- `terminal()` has no idempotence latch — ensure it is called exactly once per stream. The post-drain terminal logic returns immediately; the existing truncation path only runs when `finish_reason_seen is None`.
- The existing truncation path (EOF without `finish_reason`) is unchanged.
- The existing `chat_sse_malformed_json` trace event must still fire for unparseable frames during drain.
- The `[DONE]` sentinel during drain must set `drain_done = True` and break the OUTER read loop.
- The post-drain stop-reason logic MUST preserve the existing three-way branch: (1) `finish_reason == "tool_calls"` → validate and claim `tool_use`; (2) `emitted_tool_use` → close without validate, map finish reason with `force_log=True`; (3) else → map finish reason. The upgrade to `"tool_use"` applies only in branch (2) — which the split already restricts to a finish reason that is NOT `"tool_calls"` — and only when the mapped finish reason is `"end_turn"`. That branch fires for tool blocks captured during the drain AND for blocks already open when the finish frame arrived — both upgrade (Resolved Decision D1). A finish reason that maps to `None` (`""` or an unmapped string) still emits `stop_reason: null` even when tool blocks were emitted (Resolved Decision D3).
- A `finish_reason` carried by a frame that arrives DURING the drain MUST update `finish_reason_seen` (last value wins). The drain guard returns before the normal finish-reason extraction, so without an explicit update a provider that sends `"stop"` and later revises to `"tool_calls"` — or `"length"` and later `"tool_calls"` — leaves the stale first value in place.
- If a disconnect error occurs during drain, `terminal()` is NOT called (matching current behavior for disconnects). The exception is re-raised.
- If the first frame of a stream carries `finish_reason` (no prior content), `start_message()` must still be called before `terminal()`.

**Detailed step-by-step:**

1. **Add `MAX_DRAIN_BYTES = 64 * 1024` and `MAX_DRAIN_SECONDS = 5`** as module-level constants alongside `MAX_CHAT_TOOL_PENDING_BYTES` etc. (line 1195-1197).

2. **Add `stream_options: {include_usage: true}` to the chat-mode request** in `_anthropic_to_chat`, after the pass-through tuple loop (transforms_chat.py lines 74-77). Do **not** add `"stream_options"` to the `for field in (...)` tuple: the Anthropic request body carries no such key, so the copy would be inert for this feature while forwarding a client-supplied `stream_options` verbatim on non-streaming requests — which chat-completions rejects as an unknown parameter. Emit the key explicitly instead:
   ```python
   if body_json.get("stream"):
       out["stream_options"] = {"include_usage": True}
   ```
   The `stream` guard is required: only streaming requests may carry `stream_options`. A streaming request emits `{"stream_options": {"include_usage": true}}`; a non-streaming request omits the key entirely.

3. **Add `finish_reason_seen = None`, `drain_bytes = 0`, `drain_done = False`, `finish_seen_at = None`, `post_finish_suppressed = 0`, `_orig_timeout = None`, and `_timeout_saved = False`** at the `_stream_chat_sse_to_anthropic` level (alongside `usage`, `chat_id`, `tool_calls_seen`, etc. at lines 1567-1571). `_orig_timeout` / `_timeout_saved` back the drain's socket-read bound (step 5) and its restore (step 8); the boolean distinguishes "no timeout was captured" from "the captured timeout was `None`" (blocking mode). Add `finish_reason_seen` and `post_finish_suppressed` to `handle_frame()`'s nonlocal statement (line 1842).

4. **Modify `handle_frame()`** — add a drain-mode guard AFTER `delta = choice.get("delta") or {}` but BEFORE `if isinstance(delta, dict):` (the guard sits at the current line 1876, where the non-drain tool-call handling begins at 1890). The guard reads:
   ```python
   if finish_reason_seen is not None:
       # Drain mode: only tool_calls, usage and a revised finish_reason are
       # still meaningful. Content / reasoning deltas are suppressed — their
       # blocks were closed by terminal(), and the Anthropic client rejects
       # deltas on a closed block. Tool calls arrive as their own block.
       revised = choice.get("finish_reason")
       if revised is not None:
           finish_reason_seen = revised
       if isinstance(delta, dict):
           if delta.get("tool_calls") is not None:
               tool_calls_seen = True
               process_tool_calls(delta["tool_calls"])
           # Suppress content and reasoning deltas
           if (isinstance(delta.get("content"), str) and delta.get("content")) or \
              (isinstance(delta.get("reasoning_content"), str) and delta.get("reasoning_content")) or \
              (isinstance(delta.get("reasoning"), str) and delta.get("reasoning")):
               post_finish_suppressed += 1
       return None
   ```
   This guard must be placed AFTER `delta = choice.get("delta") or {}` so `delta` is defined. It must be BEFORE the normal `if isinstance(delta, dict):` block so it intercepts the normal processing. The `tool_calls_seen = True` and `process_tool_calls()` calls ensure late tool calls are captured. The `revised` update keeps `finish_reason_seen` at the LAST value the provider sent (last-wins), which the drain guard would otherwise freeze at the first. The suppression counter uses `isinstance(x, str) and x` to match the existing code's idiom.

5. **Modify the finish branch in the read loop** (lines 1972-1975): instead of calling `terminal()` and returning immediately, record the finish reason, install a socket read timeout for the drain, and continue the loop:
   ```python
   if isinstance(result, tuple) and result[0] == "finish":
       finish_reason_seen = result[1]
       finish_seen_at = time.time()
       # Bound the drain at the point of blocking: without this, a provider
       # that goes silent after finish_reason pins resp.read1() for the full
       # upstream socket timeout (300 s). The value tracks the REMAINING
       # drain budget (recomputed per chunk in step 6) and is restored
       # after the drain (step 8).
       try:
           _orig_timeout = resp.fp.raw._sock.gettimeout()
           resp.fp.raw._sock.settimeout(max(1, MAX_DRAIN_SECONDS))
           _timeout_saved = True
       except (AttributeError, OSError):
           _timeout_saved = False
       continue  # enter drain mode
   ```
   Do NOT call `terminal()` here. Do NOT return.

   The `try`/`except (AttributeError, OSError)` is required, not decorative: `resp.fp.raw._sock` is a CPython private path — `hasattr(resp.fp, 'raw')` alone does not guarantee `_sock` exists — and the socket may already be closed. When the install fails, `_timeout_saved` stays `False`, no timeout is restored in step 8, and the drain falls back to the post-read deadline check only.

6. **Add drain byte counting, the time deadline, and the timeout recompute** in the read loop: after `chunk = resp.read1(8192)` (line 1935) and the `if not chunk: break` check (lines 1939-1940), add:
   ```python
   if finish_reason_seen is not None:
       drain_bytes += len(chunk)
       if drain_bytes > MAX_DRAIN_BYTES:
           break
       remaining = MAX_DRAIN_SECONDS - (time.time() - finish_seen_at)
       if remaining <= 0:
           break
       if _timeout_saved:
           try:
               resp.fp.raw._sock.settimeout(max(1, remaining))
           except (AttributeError, OSError):
               _timeout_saved = False
   ```
   The socket timeout (set in step 5) ensures `resp.read1()` returns within the remaining budget even if the provider is silent, so the time deadline is enforced at the point of blocking, not just after a read returns. Recomputing the budget per chunk keeps the TOTAL drain bounded by `MAX_DRAIN_SECONDS` rather than by `2 × MAX_DRAIN_SECONDS` (a read that only returns on timeout is followed by a deadline check that must also be able to fire before the next read). `max(1, remaining)` is applied because a sub-second socket timeout is not reliable for a blocked read; the resulting overshoot is under 1 s.

   When the byte budget breaks the drain, the crossing chunk is discarded unparsed — the bound is checked per chunk, not per frame. The break landing mid-tool-call still claims `tool_use` (Resolved Decision D4).

7. **Modify the `[DONE]` handler** (lines 1929-1930): when `finish_reason_seen` is set, set `drain_done = True` and break the inner loop, then check the flag after the inner loop to break the outer loop:
   ```python
   if result == "done":
       if finish_reason_seen is not None:
           drain_done = True
           break  # break inner frame loop
       continue
   ```
   Then immediately after the inner `while True` frame loop (after line 1949, before the memory guards at line 1950), add:
   ```python
   if drain_done:
       break  # break outer read loop
   ```

8. **Add post-drain terminal logic** after the read loop exits and after the `except _DISCONNECT_ERRORS: raise` block (line 1982), BEFORE the existing truncation path (line 1983):
   ```python
   if finish_reason_seen is not None:
       if not message_started:
           start_message()
       if finish_reason_seen == "tool_calls":
           # Diagnostic only: validate still counts unparseable arguments for
           # the coalesced chat_sse_tool_degradation event, but the counts no
           # longer gate the stop reason (Resolved Decision D4).
           close_open_tool_blocks(validate=True)
           sr = "tool_use" if emitted_tool_use else None
           terminal(sr)
       elif emitted_tool_use:
           close_open_tool_blocks(validate=False)
           mapped = _map_chat_finish_reason(finish_reason_seen)
           if mapped == "end_turn":
               sr = "tool_use"
           else:
               sr = mapped
           terminal(sr, force_log=True)
       else:
           terminal(_map_chat_finish_reason(finish_reason_seen))
       if post_finish_suppressed:
           log_trace({
               "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "event": "chat_sse_post_finish_suppressed",
               "request_id": request_id,
               "count": post_finish_suppressed,
           })
       return first_byte_ms
   ```
   This preserves the existing three-way branch. The upgrade to `"tool_use"` only applies when `emitted_tool_use` is True AND the mapped finish reason is `"end_turn"`. Note that this branch fires whether the tool blocks were captured during the drain or were already open when the finish frame arrived — both upgrade (Resolved Decision D1). The `force_log=True` is preserved on the `emitted_tool_use` branch. The `chat_sse_post_finish_suppressed` trace event fires when content/reasoning deltas were suppressed during drain.

   **In the `"tool_calls"` branch the gate is `emitted_tool_use`, not parseability (Resolved Decision D4, revised).** The previous gate demanded `valid > 0` **and** `dropped_fragment_count == 0` **and** `overflow_tool_count == 0` **and** `unparseable_arg_count == 0` **and** `not (frame_dropped and emitted_tool_use)`. Every one of those extra conditions describes a tool block that **was emitted to the client** but whose arguments are degraded in some way. Forcing `null` there told the client "no tool turn" while handing it a `tool_use` block — the worst of both signals, and the exact inversion of the documented rationale, which is about the case where **zero** `tool_use` blocks were emitted (the client waits forever for a tool result that cannot arrive). The rule is now: **`"tool_use"` iff at least one `tool_use` block was emitted, otherwise `null`.** The malformed/dropped/overflow/unparseable counters keep their diagnostic role — `unparseable_arg_count` still feeds the coalesced `chat_sse_tool_degradation` event — but they no longer decide the stop reason. A client that receives a tool block with unparseable arguments can surface the parse failure and continue; `null` risked it stopping for user input instead.
   The counters must still be **incremented** (the trace event's fields depend on them); only the `if` condition changes.
   The EOF/truncation path (step 9) is **not** changed: it still reports `null` for an emitted-but-unfinished tool block, because there the stream was cut with no `finish_reason` at all.

   Before the post-drain terminal logic, restore the original socket timeout:
   ```python
   if finish_reason_seen is not None and _timeout_saved:
       try:
           resp.fp.raw._sock.settimeout(_orig_timeout)
       except (OSError, AttributeError):
           pass
   ```
   The `_timeout_saved` flag — not a `_orig_timeout is not None` test — gates the restore: a captured timeout of `None` (blocking mode) is a legitimate value that must be restored as-is.

9. **The existing truncation path** (lines 1983-1997) remains unchanged — it only runs when `finish_reason_seen is None`.

10. **Update the `_stream_chat_sse_to_anthropic` docstring** — the drain paragraph currently reads "drains trailing frames until EOF, [DONE], or the MAX_DRAIN_BYTES / MAX_DRAIN_SECONDS bound". Extend the time-bound clause to say the bound is enforced by a socket read timeout at the point of blocking, so a silent provider cannot hold the worker thread past it.
    Also correct the stale rationale in the docstring's drain paragraph and the drain-mode guard comment: both currently say content/reasoning deltas are suppressed because "the Anthropic client rejects deltas on a closed block". Since `terminal()` now runs AFTER the drain, nothing is closed during it — the suppression is a policy choice (see `doc/provider-modes.html`), not a protocol constraint. State the policy, not the false mechanism.

11. **Drop the empty-dict over-check in the buffered chat transform** (`transforms_chat.py:468`). The guard currently reads:
    ```python
    if parsed_args is None or parsed_args == {}:
    ```
    `parsed_args == {}` rejects a **legitimate zero-argument tool call** — upstream `arguments: "{}"` is valid JSON and a valid Anthropic `input` — and replaces it with the `[Tool call failed: …]` text placeholder. Change it to:
    ```python
    if parsed_args is None:
    ```
    `transforms_response.py:377` already has no `== {}` term (`if parsed_args is None or not isinstance(name, str) or not name …`), so response mode accepts zero-argument calls; this aligns chat mode with it. **Keep** the placeholder for genuinely unparseable arguments: the buffered path rebuilds a complete Anthropic message, and `tool_use.input` must be a JSON object, so a malformed arguments string has no representation to forward. (The streaming path has no such constraint — it forwards the upstream's fragments verbatim — which is why dropping the parseability gate there (step 8) really does hand the raw call to the client.)

**Verification:**

→ coder verify (auto): `MAX_DRAIN_BYTES = 64 * 1024` and `MAX_DRAIN_SECONDS = 5` are module-level constants
→ coder verify (auto): `_anthropic_to_chat` emits `out["stream_options"] = {"include_usage": True}` when the request is streaming, and omits the key when it is not — inspect the EMITTED upstream body, not the source text
→ coder verify (auto): `"stream_options"` is NOT present in the `for field in (...)` pass-through tuple in `_anthropic_to_chat`
→ coder verify (auto): `finish_reason_seen`, `drain_bytes`, `drain_done`, `finish_seen_at`, `post_finish_suppressed`, `_orig_timeout`, `_timeout_saved` declared at `_stream_chat_sse_to_anthropic` level
→ coder verify (auto): `finish_reason_seen` and `post_finish_suppressed` added to `handle_frame()`'s nonlocal statement
→ coder verify (auto): `handle_frame()` has the drain-mode guard after `delta = choice.get("delta") or {}` and before the normal `if isinstance(delta, dict):` block
→ coder verify (auto): the guard updates `finish_reason_seen` from `choice.get("finish_reason")` when present (last-wins), checks `finish_reason_seen is not None`, calls `process_tool_calls()` for tool_calls, and increments `post_finish_suppressed` for content/reasoning
→ coder verify (auto): the finish branch sets `finish_reason_seen = result[1]` and `finish_seen_at = time.time()` and uses `continue` instead of `return`
→ coder verify (auto): `terminal()` is NOT called inside the finish branch
→ coder verify (auto): the finish branch captures the socket timeout via `gettimeout()` and installs `settimeout()` inside a `try`/`except (AttributeError, OSError)`, setting `_timeout_saved`
→ coder verify (auto): the socket timeout is recomputed from the REMAINING budget on each drain chunk
→ coder verify (auto): the socket timeout is restored from `_orig_timeout` after the drain, gated on `_timeout_saved`
→ coder verify (auto): `drain_bytes += len(chunk)` and the time deadline check are in the read loop
→ coder verify (auto): the `[DONE]` handler sets `drain_done = True` and breaks the inner loop when `finish_reason_seen is not None`
→ coder verify (auto): `if drain_done: break` is after the inner frame loop and before the memory guards
→ coder verify (auto): the post-drain terminal logic checks `if finish_reason_seen is not None:` and calls `terminal()` exactly once and returns
→ coder verify (auto): the post-drain logic preserves the three-way branch (`finish_reason == "tool_calls"`, `emitted_tool_use`, else)
→ coder verify (auto): the upgrade to `"tool_use"` only applies when `mapped == "end_turn"` and `emitted_tool_use` is True
→ coder verify (auto): `force_log=True` is preserved on the `emitted_tool_use` branch
→ coder verify (auto): `chat_sse_post_finish_suppressed` trace event fires when `post_finish_suppressed > 0`
→ coder verify (auto): in the `finish_reason == "tool_calls"` branch the stop reason is `"tool_use" if emitted_tool_use else None` — the parseability and drop/overflow counters no longer gate it
→ coder verify (auto): the counters (`unparseable_arg_count`, `dropped_fragment_count`, `overflow_tool_count`, `frame_dropped`) are still INCREMENTED and still reach the coalesced `chat_sse_tool_degradation` event
→ coder verify (auto): `transforms_chat.py`'s buffered guard reads `if parsed_args is None:` — the `or parsed_args == {}` term is gone, and `transforms_response.py` is unchanged
→ coder verify (auto): the `[Tool call failed: …]` placeholder still fires for genuinely unparseable arguments in the buffered path
→ coder verify (auto): the existing truncation path (EOF without finish_reason) is unchanged
→ coder verify (auto): `pip install -e .` succeeds with no syntax or import errors
→ coder verify (auto): `python tests/test_chat_sse.py --test chat-sse-drain-time-deadline` passes — a silent provider must yield `message_stop` well inside the test's 20 s bound, not the upstream 300 s socket timeout
  - **MIS-TAGGED — see Issue Log `coder-auto-tag-on-a-test-run`.** This line tags a *test invocation* as `coder verify (auto)`, but the coder lane is barred from running test code, so it never executed as tagged. The check itself did run — in the tester lane, which executes this module every round and reported `chat-sse-drain-time-deadline` PASS at 5.0 s. The tag is annotated rather than rewritten: this block is the historical record of what the coder was asked to do, and editing it to say `tester verify` would falsify that record.

## Guidance for Tester

**Tests to create:**

All new tests must be registered in the `ALL_TESTS` list at the bottom of `tests/test_chat_sse.py` (line 1636-1670). Each test is a `("kebab-case-name", test_function_name)` tuple.

- **Permanent: `test_chat_sse_usage_after_finish_reason`** — A stream where the usage chunk arrives AFTER the finish_reason chunk (OpenAI's documented `stream_options.include_usage` ordering). Verify that `message_delta` carries the real usage values, not zeros. Register as `("chat-sse-usage-after-finish-reason", test_chat_sse_usage_after_finish_reason)`.

- **Permanent: `test_chat_sse_tool_calls_after_finish_reason`** — A stream where `finish_reason: "stop"` arrives, followed by tool_call delta frames, followed by `[DONE]`. Verify that the tool_call frames are captured and the stream ends with `stop_reason: "tool_use"` (not `end_turn`). Register as `("chat-sse-tool-calls-after-finish-reason", test_chat_sse_tool_calls_after_finish_reason)`.

- **Permanent: `test_chat_sse_usage_and_tool_calls_after_finish_reason`** — A stream where `finish_reason: "stop"` arrives, followed by tool_call delta frames, then a usage chunk, then `[DONE]`. Verify both the tool_calls and the usage are captured. Register as `("chat-sse-usage-and-tool-calls-after-finish", test_chat_sse_usage_and_tool_calls_after_finish_reason)`.

- **Permanent: `test_chat_sse_finish_reason_last_chunk_no_drain`** — A stream where `finish_reason` is genuinely the last chunk (no trailing data). Verify the behavior is unchanged: `terminal()` is called with the correct stop reason, and no extra frames are emitted. Register as `("chat-sse-finish-reason-last-chunk", test_chat_sse_finish_reason_last_chunk_no_drain)`.

- **Permanent: `test_chat_sse_truncation_still_works`** — A stream that ends WITHOUT any `finish_reason` (truncation — EOF, no finish_reason chunk). Verify the existing truncation path still fires correctly: `chat_sse_truncated` trace event, `terminal("end_turn")` or `terminal(None)`. Register as `("chat-sse-truncation-still-works", test_chat_sse_truncation_still_works)`.

- **Permanent: `test_chat_sse_drain_time_deadline`** — A stream where `finish_reason` is followed by a provider that sends nothing (connection stays open). Verify the drain stops at `MAX_DRAIN_SECONDS` (5 s) and `terminal()` is called. Register as `("chat-sse-drain-time-deadline", test_chat_sse_drain_time_deadline)`.

- **Permanent: `test_chat_sse_done_terminates_drain`** — A stream where `finish_reason` is followed by `[DONE]` then the connection stays open. Verify the drain stops at `[DONE]` and the proxy returns promptly. Register as `("chat-sse-done-terminates-drain", test_chat_sse_done_terminates_drain)`.

- **Permanent: `test_chat_sse_text_after_finish_suppressed`** — A stream where `finish_reason: "stop"` is followed by content deltas. Verify the content is suppressed (no `content_block_delta` emitted after finish) and a `chat_sse_post_finish_suppressed` trace event fires. Register as `("chat-sse-text-after-finish-suppressed", test_chat_sse_text_after_finish_suppressed)`.

- **Permanent: `test_chat_sse_stream_options_include_usage`** — Verify that the chat-mode request transform includes `stream_options: {include_usage: true}` in the upstream request body. Register as `("chat-sse-stream-options-include-usage", test_chat_sse_stream_options_include_usage)`.

- **Permanent: `test_chat_sse_drain_byte_budget`** — Drive the drain past `MAX_DRAIN_BYTES` (64 KB) with a tool call whose argument fragments straddle the budget boundary, then EOF. Verify the drain stops at the budget and the emitted stop reason is `tool_use` (Resolved Decision D4). Register as `("chat-sse-drain-byte-budget", test_chat_sse_drain_byte_budget)`.

- **Permanent: `test_chat_sse_first_frame_finish`** — A stream whose FIRST data frame carries `finish_reason` (no prior content chunk): the post-drain logic must call `start_message()` before `terminal()`, so the client sees a well-formed `message_start` → … → `message_stop`. Register as `("chat-sse-first-frame-finish", test_chat_sse_first_frame_finish)`.

- **Permanent: `test_chat_sse_empty_finish_reason_no_change`** — A stream whose `finish_reason` is `""` (or an unmapped string such as `"content_filter"`) with no tool calls: `finish_reason_seen` must be recorded (the `is not None` discipline) and the emitted `stop_reason` must follow the mapping for that value (`null` for `""`). This pins the `is not None` rule against a future truthiness regression. Register as `("chat-sse-empty-finish-reason", test_chat_sse_empty_finish_reason_no_change)`.

- **Permanent: `test_chat_sse_unmapped_finish_with_tools`** — `finish_reason: ""` during drain plus captured tool calls: assert the stream ends with `stop_reason: null` (Resolved Decision D3 — the unmapped reason's `None` mapping is NOT upgraded by the presence of tool blocks). Register as `("chat-sse-unmapped-finish-with-tools", test_chat_sse_unmapped_finish_with_tools)`.

**Existing tests to update for the D4-revised stop-reason rule — MANDATORY:**

The `finish_reason == "tool_calls"` branch now claims `"tool_use"` iff a `tool_use` block was emitted. Every test that pairs a `tool_calls` finish with a `null` assertion **and** emits at least one `tool_use` block flips to `"tool_use"`. Worked out against the tree (verify each by reading its fixture — do not apply the list blindly):

| Test | Was | Now | Why |
|---|---|---|---|
| `test_chat_sse_unparseable_arguments_at_close` | `null` | `tool_use` | block emitted, args unparseable — no longer gated |
| `test_chat_sse_mixed_parseable_unparseable_finish` | `null` | `tool_use` | one valid block emitted; the unparseable sibling no longer forces null |
| `test_chat_sse_non_dict_arguments_at_close` | `null` | `tool_use` | block emitted, args parse to a non-dict |
| `test_chat_sse_fragments_missing_index` | `null` | `tool_use` | a block was started before the index-less fragments were dropped |
| `test_chat_sse_too_many_parallel_tools` | `null` | `tool_use` | blocks were emitted before the >32-index overflow |
| `test_chat_sse_frame_dropped_guard` | `null` | `tool_use` | an oversized frame was dropped, but the tool block was emitted |
| `test_chat_sse_malformed_tool_call_degrades` | `null` | `tool_use` | confirm from the fixture that a `tool_use` block is actually emitted; if it is not, it stays `null` — the zero-block case still degrades |
| `test_chat_sse_conflicting_metadata` | `null` | `tool_use` | confirm from the fixture whether a block was emitted first |

**`test_chat_sse_no_deltas_tool_calls_finish` MUST keep `null`** — `finish_reason: "tool_calls"` with zero tool-call deltas emits no block, so `emitted_tool_use` is False. This test is the guard that the original rationale survives where it applies; if it starts failing, the change is wrong, not the test.

**Tests on other paths are NOT affected** — leave their `null` assertions alone: `test_chat_sse_tool_call_eof_without_finish`, `test_chat_sse_pending_buffer_cap_exceeded` (EOF/truncation path), `test_chat_sse_empty_finish_reason_no_change`, `test_chat_sse_unmapped_finish_with_tools` (the `emitted_tool_use` branch, D3).

The counters must still be asserted where the tests already check them (`unparseable_arg_count`, `frame_dropped`, the coalesced `chat_sse_tool_degradation` event) — only the **stop-reason** expectation changes.

**New test for the zero-argument over-check (step 11):**

- **Permanent: `test_chat_anthropic_to_chat_zero_arg_tool`** — a **buffered** chat-mode upstream response carrying one tool call with `arguments: "{}"`: assert the proxy emits a `tool_use` block with `input == {}` (NOT the `[Tool call failed: …]` text placeholder) and no `tool_args_parse_failure` trace event. Add a companion assertion that a genuinely unparseable `arguments` string still produces the placeholder. Put this in `tests/test_chat_transform.py` (it is a transform-level test, not an SSE one) and register it in that module's `ALL_TESTS`. Register as `("chat-zero-arg-tool", test_chat_anthropic_to_chat_zero_arg_tool)`.

**Existing tests to update — MANDATORY, not optional:**

- `test_chat_sse_non_tool_calls_finish_with_tool_blocks` (tests/test_chat_sse.py:958) asserts `stop finish should map to end_turn (never tool_use)`. That assertion is **obsolete under this plan**: the `emitted_tool_use` branch now upgrades a `"stop"` finish reason to `tool_use` whenever tool blocks were emitted. Rewrite the assertion to expect `tool_use` and document the new expectation in the test's own comment. This is the one existing test whose expectation this plan changes — an earlier revision of this plan claimed "no test obsolescence identified", which was wrong.

**Tests to investigate for retirement:**

- `test_chat_sse_eof_without_finish_reason` (tests/test_chat_sse.py:364) is close to subsumed by the new `test_chat_sse_truncation_still_works`: both drive one content chunk then EOF with no `finish_reason` and no `[DONE]`, and the new test asserts a superset. **Keep both.** The older test is the long-standing regression pin for the truncation path taken against the pre-drain code; deleting it widens this plan's blast radius for no coverage gain, and it costs one cheap test. Note the redundancy in the new test's docstring rather than removing either.
- `test_anthropic_to_chat_integration` (tests/test_chat_transform.py:649) covers `_anthropic_to_chat` at the transform level with `stream: false`; the new `test_chat_sse_stream_options_include_usage` covers the same function with `stream: true` plus the forwarded-upstream assertion. **Keep both**: the new test's value is the end-to-end assertion that the proxy actually forwards `stream_options`, which no transform-level test can make. State that boundary in the new test's docstring.

**Test-adding procedure (from doc/test-catalog.html — do not omit):**

- Verify each new test runs **alone**: `python tests/test_chat_sse.py --test <kebab-name>`.
- Verify each new test runs as part of the **full module**: `python tests/test_chat_sse.py`.
- Verify the **full suite passes with a live proxy running**: `python tests/test_claude_proxy.py`.
- Verify the updated `test_chat_sse_non_tool_calls_finish_with_tool_blocks` passes both alone and in the module.

**Test placement:** Add the new tests to `tests/test_chat_sse.py` and register each in `ALL_TESTS`. The list holds **42** entries on the current tree (33 pre-existing + the 9 already written for this plan); these additions took it to **46**. The registered count, not this sentence, is what `doc/test-catalog.html` must quote. Step 11 adds no SSE test — it adds one transform-level test to `tests/test_chat_transform.py` (42 → 43), taking the suite from 360 to **361**.

## Summary

The chat-mode SSE read loop in `_stream_chat_sse_to_anthropic` returns from the stream the moment it processes a `finish_reason` chunk. This drops any trailing frames — both the usage chunk (OpenAI's documented ordering) and tool_call frames (from providers that send `finish_reason: "stop"` before the tool_call deltas).

The fix replaces the immediate return with a two-phase approach: record the finish reason, keep draining frames until EOF/`[DONE]`/byte-budget/time-deadline (capturing tool_calls and usage but suppressing text/reasoning), then call `terminal()` after the drain. The time deadline is enforced at the point of blocking by a socket read timeout that tracks the remaining drain budget — without it, a provider that goes silent after `finish_reason` would pin the worker thread for the upstream socket timeout (300 s), defeating the bound entirely. If tool calls were emitted, the stop reason is upgraded to `"tool_use"` (only when the mapped finish reason is `"end_turn"`).

This fixes both the zero-usage-reporting bug and the "continue" problem (Claude stopping prematurely when the provider sends `finish_reason` before tool_call frames).

The fix also adds `stream_options: {include_usage: true}` to the chat-mode request, so providers that require the explicit flag will emit usage chunks.

The truncation-retry feature (uncommitted, now reverted) was a workaround for the same provider bug. With this fix, the proxy handles the root cause directly. Genuine truncations (connection drop without any `finish_reason`) are still handled by the existing EOF path.

## Repo Mode

Public

## Document Overrides

| Document | Rule Overridden | Reason |
|----------|----------------|--------|
| doc/provider-modes.html | "Terminal events are emitted exactly once — on the `finish_reason` chunk, or synthesised at EOF or on truncation" | This fix moves terminal emission to after the post-finish drain. The doc must be updated to describe the new emission point, the drain behavior, the byte budget, the time deadline, and the tool_call capture during drain |
| doc/provider-modes.html | "[DONE] sentinels and non-data frames are skipped" | This fix makes `[DONE]` a drain terminator during drain mode. The doc must be updated to describe this new behavior |
| doc/provider-modes.html | The chat-mode `finish_reason` → `stop_reason` mapping table maps `"stop"` → `end_turn` unconditionally | The `emitted_tool_use` branch now upgrades a `"stop"` finish reason to `tool_use` whenever tool blocks were emitted (whether captured during drain or already open at the finish frame). The mapping table and its prose must state the exception, not only the chat-SSE section |
| doc/trace-log.html | Event inventory table does not include `chat_sse_post_finish_suppressed` | This fix introduces a new trace event. The doc must be updated to register it in the event inventory |
| doc/provider-modes.html | The `#malformed-args` section's rule "When every tool call in a response is malformed, `stop_reason` is forced to `null`", justified by "a client seeing `stop_reason: "tool_use"` with zero `tool_use` blocks waits for a tool result that will never come" | Resolved Decision D4 (revised). The rationale describes the **zero-block** case, but the gate was implemented on *parseability*, so it fired when a block **was** emitted. The stop reason now follows block emission, not argument parseability. The section must be rewritten to state the new rule and keep the `null` case scoped to zero emitted blocks |
| doc/provider-modes.html | The `#malformed-args` section lists "an empty dict" among the arguments that are refused as malformed | A zero-argument tool call (`arguments: "{}"`) is valid JSON and a valid `tool_use.input`; only the chat-mode buffered transform refused it (step 11). Response mode already accepted it. The section must stop listing `{}` as malformed |
| doc/test-catalog.html | The `test_admin.py` per-test inventory lists an entry, `test_admin_reload_validates_key_names`, that names no test in `tests/` — the section declares 25 tests and listed 26, so the page's per-file counts did not balance | Pre-existing drift, unrelated to this plan's behavior change, found while verifying that the grand total reconciles (the section sum was 361 against a claimed 360). Reload validates the in-memory tier set against in-memory vendor key names and never re-reads tiers from disk, so the entry's claim ("an unknown key on disk refuses the reload") describes a path the handler does not have. The orphan was deleted. The rule overridden is the page's own invariant that every listed entry corresponds to a real test |
| doc/test-catalog.html | The per-test inventory descriptions for the six flipped SSE tests state the pre-D4 stop-reason behavior ("unparseable args degrade the stop reason", "are dropped, counted, and block tool_use", "degrades the whole stream to a null stop reason", "blocks the tool_use claim") | Resolved Decision D4 (revised). Those six tests now assert `tool_use`, so the descriptions contradict both the code and the tests they index. Each must be restated as block-emission-driven and carry the page's existing "(changed 2026-10-03 …)" marker. Two further catalogue defects were found in the same pass and corrected: `test_chat_sse_empty_finish_reason` was an abbreviated name for the real `test_chat_sse_empty_finish_reason_no_change`, and the new `test_chat_anthropic_to_chat_zero_arg_tool` needed an entry |
| doc/provider-modes.html | The "post-finish drain" bullet currently states that the last non-`null` `finish_reason` wins and closes with "Any other value, including an empty string, counts as a revision" | Step 12 narrows the revision rule to the last **non-empty** value, which makes that closing sentence false. The bullet must state that a falsy value — `null` *or* an empty string — is not treated as a revision, while a genuinely empty reason as the provider's *first* answer is still recorded |

## Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| Provider never sends EOF or [DONE] after finish_reason | Proxy hangs waiting for drain | The drain is bounded by `MAX_DRAIN_SECONDS` (5 s) and `MAX_DRAIN_BYTES` (64 KB). The read loop breaks when either bound is reached. The time bound is enforced **at the point of blocking** by the socket read timeout (steps 5-6) — a post-read check alone would leave a silent provider pinning the worker thread for the 300 s upstream socket timeout. 5 s is well under the 30 s drain-and-swap timeout. |
| Provider sends text/reasoning deltas after finish_reason | Extra content appears in the client | The drain-mode guard in `handle_frame()` suppresses content and reasoning deltas (counted via `post_finish_suppressed`). |
| Provider sends tool_calls after finish, then more text | Tool calls captured, text suppressed | Tool calls get their own `content_block_start` (new block). Text deltas are suppressed. The client sees tool_use blocks and waits for tool results. Correct. |
| `terminal()` called twice | Duplicate `message_delta`/`message_stop` on the wire | The post-drain terminal logic returns immediately. The existing truncation path only runs when `finish_reason_seen is None`. |
| Drain byte/time budget too small | Large tool call arguments truncated | 64 KB is generous: a usage chunk is ~100 bytes, a tool call with arguments is typically < 1 KB. 64 KB allows multiple tool calls with large arguments. 5 s is enough for the provider to send trailing frames. |
| Admin switch/reload during drain | Drain-and-swap waits for in-flight to reach zero | The drain is bounded (5 s + 64 KB), so the in-flight window is limited to 5 s. The 30 s drain-and-swap timeout is sufficient. |
| Disconnect during drain | `terminal()` not called, client hangs | This matches current behavior for disconnects (the exception is re-raised). The client handles disconnects by timing out. |
| First frame carries finish_reason | No `message_start` emitted | The post-drain terminal logic calls `start_message()` if `message_started` is False. |
| A chat provider rejects the injected `stream_options` field | Every streaming chat request to that provider 400s (400 is not retried — only 429/503 are) | The guard limits the field to streaming requests. Accepted as a residual risk (Resolved Decision D2); the field is standard OpenAI and the configured chat providers are OpenAI-compatible gateways. A 400 naming the field would surface immediately in the trace, at which point a compat path can be added. |
| Drain captured tool calls whose arguments the byte budget cut mid-fragment | Client receives a `tool_use` block whose `input_json_delta` stream is invalid partial JSON | Accepted (Resolved Decision D4 — the block still claims `tool_use`). The byte bound is checked per chunk, so the crossing chunk is discarded unparsed and the only signal is the existing `chat_sse_tool_degradation` trace event. |
| A provider sends a trailing `finish_reason: ""` after a resolved one | The empty string overwrites the resolved value (drain last-wins), so a stream whose tool block already reached the client reports `stop_reason: null` and logs a spurious degradation event | **CLOSED in step 12 (round 4), ruled by the user.** The Phase 6 re-review's explicit verdict was *defect, not per-spec* behaviour, contrary to the coder's reading: the drain's revision path exists to honour a provider *correcting itself* (`"stop"` → `"tool_calls"`), and an empty string is the absence of an answer rather than a correction. The guard becomes `if revised:` on the revision path only; the initial assignment at `server.py:1988` keeps `is not None` so a genuinely empty reason is still recorded when it is the provider's answer (`test_chat_sse_empty_finish_reason_no_change` pins that). The narrowed rule — **the last non-empty `finish_reason` wins** — is a documentation change too, so the planner updates the "post-finish drain" bullet in `doc/provider-modes.html` after the round lands |
| The change misbehaves in production and must be backed out | — | There is no env/config kill switch: the drain, the `stream_options` injection and the stop-reason upgrade are unconditional. Rollback is a `git revert` of the coder commit plus a proxy restart. Accepted because the plan is a bug fix on an already-broken path (the pre-fix code drops the frames outright), and because a kill switch would itself need its own test surface. |

## Proposed Changes

1. **Step 1:** Add constants, modify `handle_frame()` with drain-mode guard, modify finish branch to record and continue, install the socket read timeout bounding the drain at the point of blocking, add drain bounds, make `[DONE]` terminate drain, add post-drain terminal logic with three-way branch preservation, add `stream_options` to request
   → coder verify (auto): `MAX_DRAIN_BYTES = 64 * 1024` and `MAX_DRAIN_SECONDS = 5` are module-level constants
   → coder verify (auto): `_anthropic_to_chat` emits `stream_options: {include_usage: true}` for streaming requests and omits the key otherwise (inspect the emitted body)
   → coder verify (auto): `"stream_options"` is NOT in the `for field in (...)` pass-through tuple
   → coder verify (auto): `finish_reason_seen`, `drain_bytes`, `drain_done`, `finish_seen_at`, `post_finish_suppressed`, `_orig_timeout`, `_timeout_saved` declared at `_stream_chat_sse_to_anthropic` level
   → coder verify (auto): `finish_reason_seen` and `post_finish_suppressed` in `handle_frame()`'s nonlocal
   → coder verify (auto): drain-mode guard after `delta = choice.get("delta") or {}`, before the normal `if isinstance(delta, dict):` block
   → coder verify (auto): guard updates `finish_reason_seen` from the frame's `finish_reason` (last-wins), calls `process_tool_calls()`, increments `post_finish_suppressed`
   → coder verify (auto): finish branch sets `finish_reason_seen` and `finish_seen_at`, uses `continue`
   → coder verify (auto): `terminal()` NOT called in finish branch
   → coder verify (auto): socket timeout captured and installed in the finish branch under `try`/`except (AttributeError, OSError)`, recomputed per drain chunk from the remaining budget, restored after the drain
   → coder verify (auto): `drain_bytes` incremented, time deadline checked
   → coder verify (auto): `[DONE]` sets `drain_done = True`, `if drain_done: break` after inner loop
   → coder verify (auto): post-drain logic checks `finish_reason_seen is not None`, preserves three-way branch, upgrades to `"tool_use"` only when `mapped == "end_turn"`, preserves `force_log=True`
   → coder verify (auto): `chat_sse_post_finish_suppressed` trace event when `post_finish_suppressed > 0`
   → coder verify (auto): existing truncation path unchanged
   → coder verify (auto): `pip install -e .` succeeds
   → tester verify: `test_chat_sse_drain_time_deadline` passes — this is the gate for the socket-timeout work; it FAILS on the currently landed code
   → tester verify: `test_chat_sse_usage_after_finish_reason` passes
   → tester verify: `test_chat_sse_tool_calls_after_finish_reason` passes — stop_reason is "tool_use"
   → tester verify: `test_chat_sse_usage_and_tool_calls_after_finish_reason` passes
   → tester verify: `test_chat_sse_finish_reason_last_chunk_no_drain` passes
   → tester verify: `test_chat_sse_truncation_still_works` passes
   → tester verify: `test_chat_sse_done_terminates_drain` passes
   → tester verify: `test_chat_sse_text_after_finish_suppressed` passes
   → tester verify: `test_chat_sse_stream_options_include_usage` passes
   → tester verify: `test_chat_sse_drain_byte_budget` passes
   → tester verify: `test_chat_sse_first_frame_finish` passes
   → tester verify: `test_chat_sse_empty_finish_reason_no_change` passes
   → tester verify: `test_chat_sse_unmapped_finish_with_tools` passes — stop_reason is null
   → tester verify: `test_chat_sse_non_tool_calls_finish_with_tool_blocks` passes with its UPDATED `tool_use` expectation
   → tester verify: all other existing tests in `test_chat_sse.py` continue to pass
   → tester verify: each new test passes both alone (`--test <kebab-name>`) and in the full module, and the full suite passes with a live proxy running

2. **Step 2:** Update `doc/provider-modes.html` — chat-SSE section, the chat-mode `finish_reason` → `stop_reason` mapping table, AND the `#malformed-args` section
   → Evidence: read the chat-SSE section and verify the "Terminal events are emitted exactly once — on the `finish_reason` chunk" sentence describes post-drain emission, the drain bounds (64 KB + socket-enforced 5 s), tool_call capture, and the `[DONE]` drain terminator; verify the `"stop"` → `end_turn` mapping row carries the emitted-tool-blocks exception; verify the chat-SSE "Degradation and trace events" table registers `chat_sse_post_finish_suppressed`
   → Evidence: read the `#malformed-args` section and verify (a) the error box no longer claims `stop_reason` is forced to `null` "when every tool call is malformed" — it must state that the stop reason follows **block emission** (`tool_use` iff a `tool_use` block was emitted), with `null` scoped to zero emitted blocks; (b) "an empty dict" is no longer listed among the malformed arguments; (c) the placeholder paragraph still correctly covers genuinely unparseable arguments in the **buffered** path, and now distinguishes it from the streaming path, where fragments are forwarded verbatim
   → Evidence: verify the section states the content/reasoning suppression rationale as **policy**, not as the "closed block" protocol claim

3. **Step 3:** Update `doc/trace-log.html` event inventory
   → Evidence: read the event inventory table and verify `chat_sse_post_finish_suppressed` is registered

4. **Step 4:** Update `doc/test-catalog.html` with the recounted test figures and the new entries
   → Evidence: run the page's own recipe, `grep -cE 'def (test_|doc_)' tests/*.py`, and verify **all three count sites** quote the recounted value: the per-file catalog-table row for `test_chat_sse.py`, the Category 6 heading, and the page's grand total and file count. Re-count rather than transcribing a number from this plan — after this plan's rounds the tree holds 46 functions in `test_chat_sse.py` and 361 across 19 files (`test_chat_transform.py` 43), all counts re-verified by the tester. Verify every new test has a per-test inventory entry and that `test_chat_sse_non_tool_calls_finish_with_tool_blocks`'s changed expectation is recorded
   → Evidence: verify the two "Last updated" indicators on each of the three pages are bumped to the sync date (`doc/provider-modes.html` currently carries a pre-existing 2026-09-12 header / 2026-09-30 footer mismatch — reconcile both to the same date)

5. **Step 5:** Drop the parseability gate from the `finish_reason == "tool_calls"` stop-reason branch (it is `emitted_tool_use` now) and the `or parsed_args == {{}}` over-check from the buffered chat transform
   → coder verify (auto): the branch reads `sr = "tool_use" if emitted_tool_use else None`; the counters still increment and still reach the coalesced event
   → coder verify (auto): `transforms_chat.py`'s guard reads `if parsed_args is None:`
   → tester verify: the eight candidate tests flip to `tool_use`; `test_chat_sse_no_deltas_tool_calls_finish` stays `null`
   → tester verify: `test_chat_anthropic_to_chat_zero_arg_tool` passes; an unparseable arguments string still yields the placeholder
6. **Step 12 (round 4; the fine sub-step numbers run to 11, and this continues them):** Refuse an empty-string `finish_reason` as a *revision* during the post-finish drain — `server.py:1887`, `if revised is not None:` → `if revised:` — and restate the stale rationale in the test docstring at `tests/test_chat_sse.py:2077-2078`
   → coder verify (auto): the drain-mode revision guard reads `if revised:`; the initial assignment at `server.py:1988` and `handle_frame`'s `if finish_reason is not None:` gate at 1936-1938 are **unchanged**
   → tester verify: a resolved `tool_calls` followed by a trailing `finish_reason: ""` still reports `tool_use` and logs no degradation event; `test_chat_sse_empty_finish_reason_no_change` still passes untouched (the initial-empty case must keep recording the empty value)
   → tester verify: the docstring at `tests/test_chat_sse.py:2077-2078` no longer states that the terminal sequence closes the blocks

## Guidance for Planner

- **Doc files to create/update:**
  - `doc/provider-modes.html` — chat-SSE section: terminal emission timing, drain behavior, byte bounds, the **socket-enforced** time bound, tool_call capture, `[DONE]` drain terminator; the chat-mode `finish_reason` → `stop_reason` mapping table: the emitted-tool-blocks exception; the chat-SSE Degradation-and-trace-events table: register `chat_sse_post_finish_suppressed`; the `stream_options` request field; both `Last updated` indicators (reconcile the pre-existing 2026-09-12 / 2026-09-30 mismatch)
  - `doc/trace-log.html` — register `chat_sse_post_finish_suppressed` in the event inventory table; bump both `Last updated` indicators
  - `doc/test-catalog.html` — re-count with the page's own recipe (`grep -cE 'def (test_|doc_)' tests/*.py`) and update **all three count sites**: the per-file catalog-table row for `test_chat_sse.py`, the Category 6 heading, and the grand total + file count; add per-test inventory entries for every new test; record the changed expectation of `test_chat_sse_non_tool_calls_finish_with_tool_blocks`; bump both `Last updated` indicators
- **When:** after the coder round that lands steps 5-6 (the socket timeout) — the doc text describes the socket-enforced bound, so writing it before that code lands would publish a statement the code does not yet satisfy
- **What to sync:** all three docs must reflect the new drain behavior, the new trace event, the stop-reason exception, and the new tests. Quote only re-counted figures — never a number transcribed from this plan.

## Resolved Decisions

Raised by the post-implementation mega-audit (2026-10-03, report `./tmp/reports/2026-10-02-drain-after-finish-reason-mega-audit-2026-10-03-2.json`), ruled on by the user 2026-10-03. **All four keep the behavior of the code as it stands** — the coder round implements none of them as a change. Each ruling is pinned by a test so a later edit cannot drift it silently.

**D1 — the `end_turn` → `tool_use` upgrade applies to ANY emitted tool blocks, not only drain-captured ones. RULED: upgrade always.**
The `elif emitted_tool_use` branch upgrades whenever tool blocks were emitted and the mapped reason is `end_turn`, including a stream where `finish_reason` is the last chunk and the drain captures nothing. Anthropic reports `tool_use` whenever `tool_use` blocks are present, so this is the protocol-correct signal; reporting `end_turn` for a stream that emitted tool blocks is the very confusion this plan exists to remove. The narrower "only drain-captured calls" alternative was rejected: it would have left the no-drain path mis-signalling. Client-visible consequence accepted: a `"stop"` finish with open tool blocks now reports `tool_use` for every chat-mode provider. This is what rewrote `test_chat_sse_non_tool_calls_finish_with_tool_blocks`.
Pinned by: `test_chat_sse_non_tool_calls_finish_with_tool_blocks` (updated expectation), `test_chat_sse_tool_calls_after_finish_reason`, `test_chat_sse_finish_reason_last_chunk_no_drain`.

**D2 — the injected `stream_options` is accepted as-is; no per-provider opt-out and no compat-learner path. RULED: accept, risk recorded.**
`stream_options: {include_usage: true}` is unconditional for streaming chat requests. `include_usage` is a standard OpenAI field and the configured chat providers are OpenAI-compatible gateways. The rejection risk is recorded in `## Risks` (a provider that rejects unknown fields would 400, which is not retried), and a `400` naming the field would surface immediately in the trace, at which point a compat path can be added. The token-spend of the two rejected alternatives (a `models.json` flag needing config-schema work; a third compat feature) was not justified on the evidence available.
NOT pinned by a test (the risk is upstream behavior, not proxy behavior).

**D3 — an unmapped/empty `finish_reason` with emitted tool blocks reports `stop_reason: null`. RULED: keep null.**
`_map_chat_finish_reason("")` returns `None`, so a drained `finish_reason: ""` plus captured tool calls emits `tool_use` blocks with `stop_reason: null`, matching the EOF-without-finish path. The rejected alternative — widening to `emitted_tool_use and finish_reason_seen != "tool_calls"` — would also have overwritten an informative `max_tokens` (from `finish_reason: "length"`) with `tool_use`.
Pinned by: `test_chat_sse_empty_finish_reason_no_change`, `test_chat_sse_unmapped_finish_with_tools`.

**D4 — a `tool_use` block that was emitted is signalled as `tool_use`, whatever its arguments. RULED: claim `tool_use`; REVISED 2026-10-03 to drop the parseability gate everywhere, not only on the `emitted_tool_use` branch.**
Originally ruled as "the byte budget cutting the drain mid-tool-call still claims `tool_use`" — which the code honored only on the `emitted_tool_use` branch. The Phase 6 reviewer reproduced the mismatch: identical streams give `tool_use` for `finish_reason: "stop"` and `null` for `finish_reason: "tool_calls"`, because that branch's gate demanded parseable arguments before it would claim the stop reason.

On review the user inverted the design question: *if the proxy forwards the tool block either way, why does the stop reason depend on parseability? Claude can judge a malformed call itself; the proxy cannot tell a rogue call from a degraded one.* The investigation confirmed the objection. The gate's documented rationale — "a client seeing `stop_reason: "tool_use"` with **zero** `tool_use` blocks waits for a tool result that will never come" — describes the *zero-block* case, and the extra conditions it was implemented with (`unparseable_arg_count`, `dropped_fragment_count`, `overflow_tool_count`, `frame_dropped`) all fire when a block **was** emitted. The gate was over-applied relative to its own stated purpose.

**Revised rule:** in the `finish_reason == "tool_calls"` branch, `stop_reason` is `"tool_use"` iff `emitted_tool_use`, else `null`. `emitted_tool_use` is set at exactly the point a `tool_use` `content_block_start` is written (server.py:1681), so it is precisely "a block reached the client". The counters remain diagnostics and still feed the coalesced `chat_sse_tool_degradation` event. The zero-block case (`test_chat_sse_no_deltas_tool_calls_finish`) keeps `null`, so the original rationale is preserved where it actually applies. The EOF/truncation path is unchanged.

Scope note: this edits **pre-existing, documented, tested** behavior from plan `2026-08-30-fix-chat-sse-tool-calls`, which specified the null degradation deliberately and pinned it with seven tests; eight now change (see Guidance for Tester) and the `## Malformed arguments` section of `doc/provider-modes.html` must be rewritten. The user chose to make this change inside this plan rather than defer it.
Pinned by: `test_chat_sse_drain_byte_budget` (unchanged, still `tool_use`) plus the eight updated tests.

## History

| Date | Event | Conclusion | Dismissed |
|------|-------|------------|-----------|
| 2026-10-02 | Initial plan | Plan to fix the chat-SSE read loop to drain trailing frames after finish_reason | — |
| 2026-10-03 | Mega-audit (iteration 1) | 14 High findings: plan internally contradictory, drain unbounded, truncation-retry path breaks, Document Override misattributes doc, terminal() not idempotent, [DONE] not a terminator | — |
| 2026-10-03 | Revision (Option B) | Expanded plan to capture both usage and tool_call frames during drain. Added drain byte budget, stop-reason upgrade logic, [DONE] as drain terminator, terminal() idempotence guard, post-finish suppression trace event, and corrected Document Override. Truncation-retry reverted by user. | — |
| 2026-10-03 | Mega-audit (iteration 2) | 24 High findings: guard references delta before defined, [DONE] break exits wrong loop, no wall-clock drain bound, stop-reason logic drops existing branches, stream_options never sent, doc scope incomplete, tests not registered, line number drift, suppression counter undecided, step ordering | — |
| 2026-10-03 | Revision (iteration 3) | Fixed all 66 findings: guard placement after delta definition, drain_done flag for outer loop, MAX_DRAIN_SECONDS=5 time deadline, three-way branch preservation with force_log, stream_options in request, doc/trace-log.html and doc/test-catalog.html added to scope, ALL_TESTS registration, post_finish_suppressed counter, start_message guard for first-frame finish | — |
| 2026-10-03 | Coder round 1 + tester round | Coder landed step 1 (build pass) and filed `drain-deadline-not-enforced-on-blocking-read`; tester added 9 tests to `test_chat_sse.py` (42 registered, `test_chat_sse_drain_time_deadline` failing). Coder report timestamp 10:44 precedes the plan revision at 10:47 that added the socket-timeout step, so the implementation is stale against the plan for that one item only. | — |
| 2026-10-03 | D4 REVISED by user (scope expanded) | The reviewer's `d4-scope-tool-calls-branch` Warning prompted a design question rather than a wording fix: *if the proxy forwards the tool block either way, why does the stop reason depend on argument parseability?* The documented rationale for the `null` gate — "a client seeing `stop_reason: "tool_use"` with **zero** `tool_use` blocks waits for a tool result that will never come" — describes the zero-block case, but the gate was implemented on parseability and fired when a block **was** emitted. **Ruled: drop the parseability gate entirely.** The `tool_calls` branch now claims `tool_use` iff `emitted_tool_use`; the counters stay diagnostic and still feed the coalesced event; the zero-block case keeps `null`. Extended by the user to the buffered path, where the proxy cannot forward a malformed arguments string (`tool_use.input` must be an object) — the `or parsed_args == {}` over-check is dropped there, so a legitimate zero-argument tool call is no longer replaced by the failure placeholder, while genuinely unparseable arguments keep it. Scope: a deliberate, tested prior decision from `2026-08-30-fix-chat-sse-tool-calls` is being changed inside this plan; eight tests flip, one must stay. |
| 2026-10-03 | Phase 6 review — report: [2026-10-02-drain-after-finish-reason-review-2026-10-03.json](./tmp/reports/2026-10-02-drain-after-finish-reason-review-2026-10-03.json) | Verdict **"Issues found — non-blocking"**: 0 Critical, 2 Warning, 5 Suggestion — the commit gate passes. Diff: 6 files, +938/−46. All seven scrutiny items answered; `terminal()`-once, the bound interaction, and the sentinel/overshoot analysis all came back clean; D1/D2/D3 verified matching the code. **Warning `d4-scope-tool-calls-branch`**: D4 is implemented only on the `emitted_tool_use` branch — with `finish_reason: "tool_calls"` the validating branch runs first, so a budget cut mid-arguments degrades to `null` while a closed tool block is emitted (reproduced: identical streams give `tool_use` for `"stop"`, `None` for `"tool_calls"`). D4's body scopes itself to that branch but its headline and the catalog entry do not. **Warning `closed-block-rationale-false`**: the "Anthropic protocol rejects deltas on a closed block" rationale is wrong — `terminal()` runs after the drain (server.py:2062-2071), so nothing is closed during it; suppression is policy, not protocol. Fixed in `doc/provider-modes.html` this revision; the same stale rationale survives in `server.py:1885` and the docstring at `server.py:1532-1534` (coder lane). | Suggestions (linked slugs): `sock-private-fallback-silent` (the `_timeout_saved = False` fallback is unexercised and emits no signal — the drain silently reverts to the 300 s pin), `drain-lastwins-accepts-empty` (a trailing `finish_reason: ""` can overwrite a resolved one and downgrade `tool_use` to `null`), `timeout-saved-meaning-shift`, `five-second-per-request-latency-floor` (a provider that ends without `[DONE]` and without closing costs 5 s per request), `stale-closed-block-comment` (same as the Warning, code-comment half) |
| 2026-10-03 | Tester round 2 (14:09-14:27) | `overall_result: SUCCESS` — the round finally wrote its session report (its previous three attempts died at the 30-minute limit before doing so). Added the 4 remaining permanent tests (`drain_byte_budget`/D4, `first_frame_finish`, `empty_finish_reason`, `unmapped_finish_with_tools`/D3), registered each in `ALL_TESTS`, and confirmed the round-1 rewrite of `test_chat_sse_non_tool_calls_finish_with_tool_blocks` (now expects `tool_use`). Module 46/46; **full suite 360/360**, 0 skipped; no blocking failures; no issues filed. Independently verified the plan's arithmetic (46 / 360). Caught one plan inconsistency — Immediate Actions listed 3 test additions while Guidance for Tester lists 4 — now fixed. | — |
| 2026-10-03 | Doc sync (planner, steps 2-4) | `doc/provider-modes.html`: terminal events now described as emitted after the post-finish drain; new "The post-finish drain" section (tool_calls/usage captured, content+reasoning suppressed and counted, later `finish_reason` last-wins, 64 KB byte budget, socket-enforced 5 s time budget, `[DONE]` as drain terminator, truncation unaffected); new "Requesting usage" section for `stream_options`; the `stop` row of the `finish_reason` → `stop_reason` table carries the emitted-tool-blocks exception; `chat_sse_post_finish_suppressed` registered in the degradation table; the pre-existing 2026-09-12/2026-09-30 date mismatch reconciled. `doc/trace-log.html`: event registered. `doc/test-catalog.html`: all three count sites recounted (grand total 347→360, per-file row 33→46, Category 6 heading 33→46), 13 missing per-test entries added, the changed `non_tool_calls` expectation recorded. All three pages' date indicators bumped to 2026-10-03. Gates: `doc_structure_check.py` PASS (9 files, no violations); `test_docs.py` 11/11. | — |
| 2026-10-03 | Coder round 2 (13:19-13:36) | Step 1 re-run against revision 4: landed steps 5-6 (socket read timeout captured via `gettimeout()`, installed under `try`/`except (AttributeError, OSError)` with a `_timeout_saved` sentinel, recomputed from the remaining budget per drain chunk), the step 8 restore, the step 4 drain-time `finish_reason` last-wins update, the step 2 `stream_options` pass-through tuple removal, and the step 10 docstring line. Build pass; no issues filed. Independently verified by the planner: all six edits present in the source, and `chat-sse-drain-time-deadline` now PASSES at 5.0s where it failed at 20s. The `drain-deadline-not-enforced-on-blocking-read` deferred issue closes. The round's full-suite run reported 1 failure which it could not identify; the planner diagnosed it as a stale machine-global test state file plus Windows PID reuse (see the Issue Log row for `stale-test-state-file-pid-reuse`) — not a regression from this plan. Evidence: the test passes alone and as a whole module (15/15), and a clean full-suite run by the planner gave 356/0. An earlier diagnosis blaming a concurrent suite run was retracted. | — |
| 2026-10-03 | Decisions D1-D4 resolved by user | All four rulings keep the code as it stands: D1 upgrade `end_turn`→`tool_use` for ANY emitted tool blocks (not only drain-captured); D2 accept the unconditional `stream_options`, risk recorded, no opt-out; D3 keep `null` for an unmapped/empty finish reason even with tool blocks; D4 keep `tool_use` when the byte budget cuts mid-tool-call. Four tests pin the rulings (`test_chat_sse_non_tool_calls_finish_with_tool_blocks` updated, plus `drain_byte_budget`, `empty_finish_reason_no_change`, `unmapped_finish_with_tools`); `test_chat_sse_tool_calls_after_finish_reason` and `test_chat_sse_finish_reason_last_chunk_no_drain` also cover D1. Coder scope narrows to the socket timeout (steps 5-6, step 8 restore), the drain-time `finish_reason` update, the `stream_options` tuple removal, and the docstring line. Test count 42 → 46; suite 356 → 360. | — |
| 2026-10-03 | Mega-audit (post-implementation) — report: [2026-10-02-drain-after-finish-reason-mega-audit-2026-10-03-2.json](./tmp/reports/2026-10-02-drain-after-finish-reason-mega-audit-2026-10-03-2.json) | 36 findings (9 High / 19 Medium / 8 Low). The 9 High collapse to two root causes. (1) **Stale implementation — socket timeout absent** (7 findings: defect-tracer, oversight-catcher, reality-checker, conflict-resolver, edge-case-explorer, test-impact, security): the plan's step 5/6/8 socket-timeout work is not in the landed code, so `MAX_DRAIN_SECONDS` is checked only after `resp.read1()` returns and a silent provider pins the worker thread for the 300 s upstream socket timeout. Verified directly: `python tests/test_chat_sse.py --test chat-sse-drain-time-deadline` FAILS ("no message_stop within 20s"), `grep -rn settimeout src/` returns nothing, and `server.py` (mtime 10:43:46) predates the plan revision (10:47:04) that added the step — one coder re-run against the revised plan closes all 7. (2) **Doc-count arithmetic** (2 findings: rule-enforcer, boundary-checker): the plan pinned "33 → 41, 8 new tests" while its own tester section lists 9, so following it would have published a wrong catalog count. Fixed in this revision: step 2's `stream_options` mechanism (the inert pass-through copy and its non-streaming leak), the step 5/6 socket-timeout install/recompute/restore with a `_timeout_saved` sentinel, the drain-time `finish_reason` last-wins update, `## Resolved Decisions` D1-D4, a Document Override for the `stop_reason` mapping, Risks rows for `stream_options` / D4 / rollback, tester guidance carrying the migrated existing-test assertion + 3 new boundary tests + the isolated-run/full-suite procedure, and the doc-sync steps re-specified to **recount all three count sites** rather than transcribe a number. | Dismissed Low findings (report #3, #6, #7, #12, #15, #24, #25, #26): #6 (client-supplied `stream_options` on non-streaming) and #25 (drain-time `finish_reason` frozen at first value) are **fixed** in this revision; #3 (unmapped finish reason + tool blocks) is resolved as Decision D3 (keep null) and pinned by two tests; #7 (no rollback section) is answered by a new Risks row; #12/#24 (count arithmetic) are fixed with #13/#32; #15 (missing isolated-run/full-suite verification) is fixed in Guidance for Tester; #26 (first-frame-finish and empty-finish-reason untested) is fixed by two new tests |

| 2026-10-03 | Coder round 3 (15:26-15:30) — report: [2026-10-02-drain-after-finish-reason-coder-2026-10-03-3.json](./tmp/reports/2026-10-02-drain-after-finish-reason-coder-2026-10-03-3.json) | Step 8 (drop the parseability gate from the `tool_calls` branch), step 11 (drop the `or parsed_args == {}` over-check) and step 10 (docstring/comment rationale) landed; build pass, exit 0, no issues filed. Planner verified all three in source. The coder flagged one in-lane judgment call — it also corrected the docstring sentence documenting the removed gate, which step 8 had made say the opposite of the adjacent code — and argued `drain-lastwins-accepts-empty` is per-spec rather than a defect. The planner disagrees on the second point and records it as a carried-forward hardening question, not a defect: the drain guard's `if revised is not None:` lets a trailing `finish_reason: ""` overwrite a resolved `"tool_calls"`, after which the stream falls to the `elif emitted_tool_use:` branch, maps `""` to `None`, and reports `null` for a stream whose tool block reached the client — the exact inversion D4-revised rules out. Verified against the source: `_map_chat_finish_reason("")` returns `None` (`transforms_chat.py:376-381`), so the `elif emitted_tool_use:` branch computes `sr = None` and calls `terminal(None)` with `force_log=True` (`server.py:2060-2068`) — the degradation event fires for a stream that did not degrade. One-word fix (`if revised:` on the revision path only; the initial assignment must keep `is not None`, which `test_chat_sse_empty_finish_reason_no_change` pins). **Not applied: the round had ended and the change is the user's call.** | — |
| 2026-10-03 | Tester round 3 (15:31-15:53) — report: [2026-10-02-drain-after-finish-reason-tester-2026-10-03-2.json](./tmp/reports/2026-10-02-drain-after-finish-reason-tester-2026-10-03-2.json) | `overall_result: SUCCESS`. Six tests flipped to `tool_use` by fixture inspection, not by count; the two zero-block candidates and the `no_deltas` guard verified to stay `null`; four other-path tests left alone. `test_chat_anthropic_to_chat_zero_arg_tool` added and registered as `chat-zero-arg-tool`. SSE 46/46, transform 43/43, **full suite 361/361** (0 failed, 0 skipped) with a live proxy on port 8080; the one warning is the deferred `no-proxy-stop-trace-warning`. No blocking failures, no issues filed. It also recorded two doc-vs-test contradictions against `doc/provider-modes.html#malformed-args` and the catalogue's per-test descriptions — both already the planner's pending sync — and supplied its own recount (46 / 43 / 361), which the planner reproduced independently. | — |
| 2026-10-03 | Doc sync 2 (planner, steps 2-4 continuations) | Rewrote `doc/provider-modes.html#malformed-args` per the two D4-revised Document Overrides: `{}` removed from the malformed list and explicitly stated to be a valid zero-argument call, and the `null` stop-reason rule rescoped to **zero emitted blocks** with the buffered/streaming split spelled out (buffered replaces an unparseable call with the placeholder so it emits no block; streaming forwards fragments verbatim so a block *is* emitted and still claims `tool_use`). Updated `doc/test-catalog.html`: all three count sites recounted to 46 / 43 / 361, six stale per-test descriptions rewritten with the page's "(changed 2026-10-03 …)" marker, `test_chat_sse_empty_finish_reason` corrected to `..._no_change`, and the `chat-zero-arg-tool` entry added. **New defect found and fixed:** the `test_admin.py` section declared 25 tests and listed 26 — the extra entry named a test present nowhere in `tests/` and described a reload path the handler does not have; the orphan was deleted. Verified: all 17 per-file sections balance, page sum 361 = source count 361. Gates: `doc_structure_check.py` PASS (9 files, no violations, exit 0); `test_docs.py` 11/11. | — |

| 2026-10-03 | Planner verification of the final state | Independent re-runs after the doc reconciliation, by the planner rather than the round that authored the changes: `python tests/test_claude_proxy.py` → **361 passed, 0 failed, 361 total** (exit 0; the single warning is the deferred `no-proxy-stop-trace-warning`), matching the tester's figure; `python ~/.claude/scripts/doc_structure_check.py` → PASS, 9 files, no violations, exit 0; `python tests/test_docs.py` → 11/11; a purpose-written section-balance scan → all 17 per-file catalogue sections match their declared counts and the page sum (361) equals the source count (361); all 7 report links in this plan resolve on disk. | — |

| 2026-10-03 | Phase 6 re-review — report: [2026-10-02-drain-after-finish-reason-review-2026-10-03-2.json](./tmp/reports/2026-10-02-drain-after-finish-reason-review-2026-10-03-2.json) | Verdict **"Issues found — non-blocking"** — **commit gate PASSES** (0 Critical, 2 Warning, 2 Suggestion). The previous review's two Warnings are both verified fixed (`d4-scope-tool-calls-branch` landed at `server.py:2053-2058`; `closed-block-rationale-false` landed in the docstring, the guard comment and `doc/provider-modes.html`). **Both new Warnings are documentation defects introduced by the planner's own doc-sync pass, not code defects — both fixed in this revision.** (1) `doc/provider-modes.html` documented the `stop`→`tool_use` upgrade in the *buffered* section unqualified, but the buffered path does not upgrade (`transforms_chat.py:491-494` maps `stop`→`end_turn`); the reviewer reproduced it by executing `_chat_to_anthropic`. Fixed by splitting the `stop` row by path and stating the divergence explicitly. (2) The `#malformed-args` error box claimed "zero `tool_use` blocks emitted means `stop_reason` is `null`" without the precondition — false for a call-free response, which keeps its ordinary mapping — and closed with the invalid converse "only a call that never opened a block at all can do that", contradicted by the truncation path (`server.py:2087-2090`) and by D3. Rewritten with the precondition stated and the two further `null` cases named. Scrutiny (a) confirmed the zero-block predicate **is** equivalent across both chat paths and no third path is inconsistent; (d) confirmed all seven flipped tests are coupled to the code (each falsified by the condition removed from `server.py`) with no weak test. | **Open items carried to the commit decision:** Suggestion `finish_reason:""-overwrites-resolved` — the reviewer's explicit verdict is **defect, not per-spec**, narrow and disclosed, already in `## Risks` as the user's call; and a stale rationale in a test docstring at `tests/test_chat_sse.py:2077-2078` ("their blocks are closed by the terminal sequence"), which is the same false mechanism step 10 removed but sits in a **tester-lane** file, so it needs a tester round or acceptance — the planner cannot edit it |

| 2026-10-03 | Coder round 4 (16:2x-16:34) — report: [2026-10-02-drain-after-finish-reason-coder-2026-10-03-4.json](./tmp/reports/2026-10-02-drain-after-finish-reason-coder-2026-10-03-4.json) | Sub-step 12 landed: `server.py:1893` now reads `if revised:`, with the guard's comment extended to carry the rationale. Build pass, exit 0, no issues filed. Planner verified all three requirements in source: the condition, the initial assignment `finish_reason_seen = result[1]` unchanged, and `handle_frame`'s `if finish_reason is not None:` gate unchanged — a diff scan confirms no other line in the region moved. The coder flagged a **plan-tagging nit** worth recording: the step's `python tests/test_chat_sse.py --test chat-sse-drain-time-deadline` check is tagged `coder verify (auto)`, but the coder lane is barred from running test code, so that check never executes as tagged. Harmless here (it pins round-2 socket-timeout work step 12 does not touch, and tester round 4 runs the module and the suite), but the `(auto)` tag reads as machine-executable when it is not — a plan-authoring pattern to avoid rather than a defect. | — |
| 2026-10-03 | Doc sync 3 (planner, step 12 follow-up) | The "post-finish drain" bullet in `doc/provider-modes.html` narrowed per Document Override #9: "the last non-`null` value wins" → **"the last non-empty value wins"**, with the rationale stated (the revision path honours a provider *correcting itself*; an empty reason is the absence of an answer, and accepting it would let a trailing `""` overwrite a resolved `"tool_calls"`) and the scope made explicit (a genuinely empty reason as the provider's *first* answer is still recorded; the rule governs only what may overwrite a resolved value). Written **after** the coder round landed, per the plan's own rule that doc text must not describe code that does not yet exist. | — |

| 2026-10-03 | Tester round 4 (16:4x-16:52) — report: [2026-10-02-drain-after-finish-reason-tester-2026-10-03-3.json](./tmp/reports/2026-10-02-drain-after-finish-reason-tester-2026-10-03-3.json) | `overall_result: SUCCESS`. Added `test_chat_sse_empty_revision_does_not_downgrade` (registered `chat-sse-empty-revision-no-downgrade`): it resolves `tool_calls` with a block emitted, sends a trailing `finish_reason: ""`, and asserts `tool_use` survives with **no** `chat_sse_tool_degradation` event — both signals the reviewer showed invert on the pre-step-12 guard. Confirmed `test_chat_sse_empty_finish_reason_no_change` passes untouched, so the initial-empty case still records the empty value. Fixed the stale rationale at `tests/test_chat_sse.py:2077-2078`; no assertion changed. SSE module 47/47; **full suite 362/362**, 0 failed, 0 skipped, with a live proxy verified running before *and* after. No blocking failures, no issues filed. Its stale-rationale sweep found one surviving "closed by the terminal sequence" phrase at `tests/test_chat_sse.py:1869` and judged it **correct rather than stale** — the planner verified independently: that line asserts a drained block *is* closed, and `close_open_tool_blocks` does run inside the terminal branch, so it is a different claim from the retired "blocks are closed *during* the drain" mechanism. | — |
| 2026-10-03 | Doc sync 4 (planner, round-4 recount) | `doc/test-catalog.html` recounted against the tree: grand total 361→**362**, the per-file catalog-table row for `test_chat_sse.py` 46→**47**, the Category 6 per-file heading 46→**47**, and a per-test inventory entry added for `test_chat_sse_empty_revision_does_not_downgrade` — written as the companion to `empty_finish_reason_no_change` (an empty reason is recorded when it is the provider's *first* answer, but may not overwrite a resolved one). Verified with a purpose-written section-balance scan that **all three count representations now agree at 362** — the 17 per-file section sums, the 17 catalog-table rows, and the grand-total claim — and that every section balances against its own heading. Gates: `doc_structure_check.py` PASS (9 files, no violations); `test_docs.py` 11/11. The tester had flagged these counts as pending-planner work and deliberately did not touch them, which is the lane split working as intended. | — |

## Plan Metadata

```json
{
  "plan_id": "2026-10-02-drain-after-finish-reason",
  "steps": [
    "Step 1: Add constants, modify handle_frame() with drain-mode guard, modify finish branch to record and continue, install the socket read timeout bounding the drain at the point of blocking, add drain bounds, make [DONE] terminate drain, add post-drain terminal logic with three-way branch preservation, add stream_options to request",
    "Step 2: Update doc/provider-modes.html chat-SSE section and finish_reason -> stop_reason mapping table",
    "Step 3: Update doc/trace-log.html event inventory",
    "Step 4: Update doc/test-catalog.html with recounted test figures and entries",
    "Step 5: Drop the parseability gate from the tool_calls stop-reason branch and the empty-dict over-check from the buffered chat transform",
    "Step 6: Refuse an empty-string finish_reason as a revision during the post-finish drain (server.py drain revision guard) and restate the stale block-closure rationale in the test docstring"
  ],
  "coder_files": ["src/claude_retry_proxy/server.py", "src/claude_retry_proxy/transforms_chat.py"],
  "tester_files": ["tests/test_chat_sse.py", "tests/test_chat_transform.py"],
  "doc_files": ["doc/provider-modes.html", "doc/trace-log.html", "doc/test-catalog.html"],
  "verification_scripts": [],
  "repo_mode": "Public",
  "document_overrides": [
    "doc/provider-modes.html: Terminal events are emitted exactly once — on the finish_reason chunk (Reason: this fix moves terminal emission to after the post-finish drain)",
    "doc/provider-modes.html: [DONE] sentinels and non-data frames are skipped (Reason: this fix makes [DONE] a drain terminator during drain mode)",
    "doc/provider-modes.html: chat-mode finish_reason -> stop_reason mapping table maps stop to end_turn unconditionally (Reason: the emitted_tool_use branch upgrades stop to tool_use when tool blocks were emitted)",
    "doc/provider-modes.html: the #malformed-args rule 'When every tool call in a response is malformed, stop_reason is forced to null' (Reason: the gate was implemented on argument parseability, but its rationale describes the zero-block case; the stop reason now follows block emission, not parseability)",
    "doc/provider-modes.html: the #malformed-args list counts 'an empty dict' as malformed arguments (Reason: a zero-argument tool call with arguments {} is valid JSON and a valid tool_use input; only the chat-mode buffered transform refused it)",
    "doc/trace-log.html: Event inventory table does not include chat_sse_post_finish_suppressed (Reason: this fix introduces a new trace event)",
    "doc/test-catalog.html: the per-test inventory descriptions for the six flipped SSE tests state the pre-D4 stop-reason behavior (Reason: those tests now assert tool_use, so the descriptions contradict the code and the tests they index; the same pass also corrected two abbreviated/missing entry names)",
    "doc/test-catalog.html: the test_admin.py inventory lists an entry naming no test in tests/ — 25 declared against 26 listed (Reason: pre-existing drift found while verifying the grand total reconciles; reload validates the in-memory tier set and never re-reads tiers from disk, so the entry's claim is unreachable, and the orphan was deleted)",
    "doc/provider-modes.html: the post-finish drain bullet states that the last non-null finish_reason wins and that 'any other value, including an empty string, counts as a revision' (Reason: step 12 narrows the revision rule to the last non-empty value, so that sentence becomes false; a falsy value — null or an empty string — is not a revision, while an empty reason as the provider's first answer is still recorded)"
  ]
}
```


## Audit Accumulation

*Counters reset when mega-audit runs. Used by Phase 5 entry trigger.*

| Counter | Value | Last Updated |
|---------|-------|--------------|
| issues_resolved_since_audit | 7 | 2026-10-03 |
| steps_changed_since_audit | 6 | 2026-10-03 |
| files_changed_since_audit | 7 | 2026-10-03 |

Counted since the post-implementation mega-audit of 2026-10-03 13:04 (report
`./tmp/reports/2026-10-02-drain-after-finish-reason-mega-audit-2026-10-03-2.json`), which reset
them to 0. Named, so the count is auditable rather than asserted:

- **issues resolved (7):** the reviewer's Warning `d4-scope-tool-calls-branch` (step 8); the
  reviewer's Warning `closed-block-rationale-false` (step 10); the tester-flagged
  `#malformed-args` doc-vs-test contradiction (this revision); the tester-flagged six stale
  per-test catalogue descriptions (this revision); the phantom `test_admin.py` catalogue entry
  (found by the planner during count verification, this revision); the re-review's two new
  Warnings — the unqualified buffered `stop`-upgrade claim and the unqualified zero-blocks
  rule, both **introduced by the planner's own doc-sync pass** and both fixed; and the
  `finish_reason:""` inversion (step 12, ruled by the user).
- **steps changed (6):** step 8 (parseability gate dropped), step 10 (rationale restated),
  step 11 (added — the buffered `{}` over-check), step 4 (doc sync re-specified to recount
  rather than transcribe), step 12 (added — the empty-string revision guard), and the step 2
  doc re-specification forced by the re-review's two Warnings.
- **files changed (7):** `server.py`, `transforms_chat.py`, `tests/test_chat_sse.py`,
  `tests/test_chat_transform.py`, `doc/provider-modes.html`, `doc/test-catalog.html`, and
  step 12's further edit to `server.py` + `tests/test_chat_sse.py`.
  (`doc/trace-log.html` was also edited, but before the audit, and was inside its scope.)

**The Phase 5 re-audit trigger is over threshold and is deliberately not spent.** With a
design reversal (D4-revised) plus coder and tester rounds landing after a non-blocking review,
the user's explicit ruling was the **Phase 6 reviewer path, then commit** — so the gate that
covers this revision is the reviewer re-run, not a fourth audit iteration. The counters stand
recorded here so that decision is visible rather than implied.

**Trigger state: FIRES** (7 ≥ 3 AND 6 ≥ 3) and is **deliberately not spent**, by user ruling: the
gate chosen for this revision is the Phase 6 reviewer re-run (which passed the commit gate), plus
coder and tester rounds 4, plus an independent planner full-suite run (the figure is in
`## Final Results`, not asserted here). A fourth audit iteration would re-audit prose those gates
have already exercised. No open in-scope issues remain.

## Final Results

**Status: complete.** All 6 steps landed (fine sub-steps 1–12). The chat-mode SSE read loop no
longer returns at the `finish_reason` chunk — it drains trailing frames to EOF, `[DONE]`, a 64 KB
byte budget, or a socket-enforced 5 s bound — and the stop reason now follows the blocks actually
emitted to the client rather than the proxy's judgement of their arguments. **Nothing is
committed** — 7 files are modified in the worktree against a frozen `HEAD` (`acb71de`),
1190 insertions / 100 deletions, and the worktree is the artifact.

### What shipped

| Area | Change |
|---|---|
| `src/claude_retry_proxy/server.py` | Two-phase read loop (normal, then drain); drain-mode guard with bounds; `[DONE]` as a drain terminator; socket read timeout installed at the point of blocking and recomputed per chunk from the remaining budget, restored after the drain; three-way post-drain terminal preservation; `emitted_tool_use` as the stop-reason predicate; the drain revision guard narrowed to a truthy reason |
| `src/claude_retry_proxy/transforms_chat.py` | `stream_options: {include_usage: true}` on streaming chat requests; the buffered guard's `or parsed_args == {}` over-check dropped, so a zero-argument call is a real `tool_use` block |
| `tests/test_chat_sse.py`, `tests/test_chat_transform.py` | 17 tests added or revised across four tester rounds — drain behavior, both budgets, the stop-reason rule and its guards, the empty-revision guard |
| Docs | `doc/provider-modes.html`, `doc/trace-log.html`, `doc/test-catalog.html` swept; the catalogue recounted and re-balanced |

### Gate evidence

| Gate | Result |
|---|---|
| Tester round 4 full suite (`python tests/test_claude_proxy.py`) | **362 passed, 0 failed, 362 total**, exit 0, live proxy verified running before *and* after |
| **Independent planner re-run** of the full suite on the frozen final state | **362 passed, 0 failed, 362 total**, exit 0 — the same figure re-derived by a different lane rather than restated from the round's own report |
| SSE module / transform module | 47/47 and 43/43 |
| Catalogue reconciliation | 17 per-file sections balance against their headings; all three count representations agree at **362** (section sums, catalogue-table rows, grand-total claim), equal to `grep -cE 'def (test_\|doc_)' tests/*.py` |
| Doc-structure checker | PASS — 9 files, no violations, exit 0 |
| Doc-anchor checker (`test_docs.py`) | 11/11 |
| Plan-file integrity | Metadata JSON valid (6 steps, 9 Document Overrides); all 11 linked reports resolve on disk |
| Lane integrity | The 7 changed files map exactly onto the declared `coder_files` / `tester_files` / `doc_files` sets — no strays, no undeclared change |

### Review and audit record

Three pre-implementation mega-audit iterations (14 / 24 / 66 findings) shaped the design, and one
post-implementation audit (36 findings, 9 High collapsing to two root causes: a stale coder run
and doc-count arithmetic) drove revision 4. Two Phase 6 reviews followed: the first returned
0 Critical / 2 Warning / 5 Suggestion, and the **re-review of the post-D4-revision diff returned
0 Critical / 2 Warning / 2 Suggestion with the commit gate passing.** Both of the re-review's
Warnings were documentation defects **introduced by the planner's own doc-sync pass** — an
unqualified buffered-path claim about the `stop` upgrade, and an unqualified zero-blocks rule —
and both are fixed. Every finding from both reviews is dispositioned: 4 Warnings fixed, 2
Suggestions fixed (`drain-lastwins-accepts-empty` as step 12, the stale test docstring in round
4), and the remainder carried below with reasons.

### Residuals — stated, not smoothed over

1. **The buffered path does not perform the `stop` → `tool_use` upgrade that the streaming path
   does** — `tool_use` over SSE, `end_turn` buffered, for the same turn. Pre-existing and
   untouched by this plan; surfaced while fixing the re-review's first Warning. Now documented
   honestly in the mapping table by path, and dispositioned **won't-fix with the user's explicit
   confirmation** (Issue Log `buffered-path-stop-no-upgrade`). It remains the same "a tool block
   reached Claude but the signal says no tool turn" shape the user reversed D4 over, so it is
   recorded as a deliberate acceptance rather than a silent one.
2. **`DRAIN_BOUND_TEST_SECONDS = 20` cannot distinguish a 5 s drain from a 19 s one**, so
   `chat-sse-drain-time-deadline` proves the time bound only to within 4× the asserted figure.
   Dispositioned **won't-fix with the user's explicit confirmation** (Issue Log
   `drain-bound-test-precision`): the test's discriminating job is *bounded vs the 300 s upstream
   pin*, which 20 s separates by more than an order of magnitude.
3. **Three reviewer Suggestions carried, not fixed** (non-blocking, recorded in History):
   `sock-private-fallback-silent` — the `resp.fp.raw._sock` capture failure path is silent, so if
   that CPython internal ever moves the drain quietly reverts to the 300 s pin with no trace
   event and no failing test; `timeout-saved-meaning-shift`; and
   `five-second-per-request-latency-floor` — a provider that ends without `[DONE]` and without
   closing costs 5 s per request.
4. **The step-12 scenario's real-world trigger is unverified.** Reproducing an empty-string
   revision needs a provider to put a non-null empty `finish_reason` on a chunk that still
   carries `choices`, after a resolved reason. The scenario is constructible with the suite's
   fixtures and the trace from the old guard to the inverted signal is deterministic, but no live
   provider or captured trace was available to confirm a real provider emits it. The tester noted
   the same limitation.
5. **Test-coupling for step 12 is a code trace, not a mutation run.** The tester lane may not
   modify source to revert the guard, so the new test's coupling rests on the trace (old guard →
   `""` overwrites → `emitted_tool_use` branch → `terminal(None, force_log=True)`), which the
   Phase 6 re-review reached independently. Every other flipped test *was* shown coupled — six
   failed with `must degrade stop_reason to null, got 'tool_use'` before the flips.
6. **One pre-existing issue remains open, out of scope:** `stale-test-state-file-pid-reuse`
   (test-infrastructure isolation; predates this plan) has its own deferred-issue report and
   Issue Log row.
7. **`.codegraph/` is untracked in the tree and must not be staged.**

**Commit:** not made.
