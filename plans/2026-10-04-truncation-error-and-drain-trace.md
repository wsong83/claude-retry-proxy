# Plan: Signal a cut chat-mode stream as an error, and make the post-finish drain self-describing

**Project:** D:\proj\claude-retry-proxy
**Plan ID:** 2026-10-04-truncation-error-and-drain-trace
**Created:** 2026-10-04

## Immediate Actions

*Rounds 1 and 2 both ended their turn with `stop_reason: end_turn` on a text-only message that announced the next action instead of performing it (round 1: after stating adoption; round 2: after three Edits, on "Now splitting `terminal()` into shared helpers (step 1b):"). Neither wrote a session report. Round 2's three edits are applied and inert; everything else in Steps 1–2 is outstanding. Round 3 completes Steps 1–2 only.*

**Coder:**
- **3 of Step 1's edits are already applied** in `src/claude_retry_proxy/server.py` — the method docstring, `saw_done = False` (line ~1557), and `saw_done = True` + `drain_exit = "done"` in the read loop's `[DONE]` dispatch (line ~1998). **Do not re-apply them.** `saw_done` and `drain_exit` are currently written and never read, so the tree behaves exactly as HEAD.
- **Emit each Edit in the same message as its text.** Do not end a turn on a sentence describing the next edit.
- **Order the edits so a stall is always safe.** Do every initialisation (2(a), 2(d)'s parameter, 2(e)'s four fields and `frames_seen`) *before* any event emission that reads it: a stop between them would leave the live proxy raising `NameError` on its next chat-mode drain. If you must stop early, stop at a sub-step boundary, never between an emission and its state.
- Step 1(b): extract `close_all_blocks()` and `log_degradation_if_needed(force_log=False)` immediately above `def terminal(`; move the unstarted-tool counting loop into the helper; `terminal()` becomes `close_all_blocks()` … `log_degradation_if_needed(force_log)`.
- Step 1(c): replace the truncation tail with the `if saw_done:` / else-error split, calling `close_all_blocks()` and `log_degradation_if_needed()` before the error write and adding `"saw_done": 1 if saw_done else 0` to the `chat_sse_truncated` event.
- Step 2(a): add `drain_exit = None` and `drain_ended_at = None` beside `drain_bytes = 0` (line ~1570).
- Step 2(b): assign `drain_exit` at the six remaining exits, split `except socket.timeout:` (→ `"time_budget"`) **before** the combined tuple (→ `"read_error"`), and capture `drain_ended_at = time.time()` after the read loop.
- Step 2(c): emit the `chat_sse_drain` event with the coerced `_fr`.
- Step 2(d): thread `tools_declared` through `_stream_upstream_response` → `_stream_chat_sse_to_anthropic` (both call sites in `forward_request`) and put it on the `chat_sse_drain` event.
- Step 2(e): add the `frames_seen` counter and the four late-frame fields (`late_frames`, `first_late_ms`, `last_late_ms`, `late_tool_call_ms`) to `chat_sse_drain`.
- Step 2(f): add `text_emitted` / bounded `text_tail` state and the `chat_sse_unfinished_turn` **log-only** event. It must not alter the response in any way.
- Step 2(g): add the unfinished-turn and late-frame section to `scripts/analyze_proxy_trace.py`.
- Run both step scripts — `python ./tmp/verification/2026-10-04-truncation-error-and-drain-trace-step{1,2}.py` — and require exit 0 from each.

## Issue Log

Rows ordered newest-first (latest issues at top). New issues are prepended; resolved issues stay in place with updated status.

| Issue | Status | Found | Resolved | Resolved By |
|-------|--------|-------|----------|-------------|
| [tools-declared-scope-premise-wrong](./tmp/reports/2026-10-04-truncation-error-and-drain-trace-tools-declared-scope-premise-wrong.json) | Resolved | 2026-10-04 | 2026-10-04 | tester |
| [unfinished-turn-provider-key-threading](./tmp/reports/2026-10-04-truncation-error-and-drain-trace-unfinished-turn-provider-key-threading.json) | Resolved | 2026-10-04 | 2026-10-04 | tester |
| [truncation-masks-upstream-failure](./tmp/reports/2026-10-04-truncation-error-and-drain-trace-truncation-masks-upstream-failure.json) | Resolved | 2026-10-04 | 2026-10-04 | tester |
| [upstream-silent-tool-call-omission](./tmp/reports/2026-10-04-truncation-error-and-drain-trace-upstream-silent-tool-call-omission.json) | Won't fix | 2026-10-04 | 2026-10-04 | user — observability chosen over a fix (upstream defect, not reachable from the proxy) |

## Guidance for Coder

**Files to modify:** `src/claude_retry_proxy/server.py` — the two steps below. No other source file changes.

**Step-by-step with verification:** each step carries coder checks tagged `(auto)` or `(scripted)`. The coder self-verifies `(auto)` checks and runs the provided script for `(scripted)` checks. Tester owns the behavioral checks.

**The step scripts are self-tested.** `./tmp/verification/_dryrun-step1-step2.py` applies these two steps' edits to a throwaway copy of `server.py` and runs both step scripts against it across nine arms — unfixed (both must fail), fixed (both must pass), and one reverted guard per script (the matching script must fail). It currently passes. Run it first when a step script reports an unexpected failure: if it passes, the script is sound and the failure is in your edit; if it fails, the script itself drifted. It writes and deletes only `./tmp/verification/_dryrun-server.py`.

**Do not touch tests.** Two tests in `tests/test_chat_sse.py` assert the old behavior on the cut-stream path; migrating them is the tester's work (see Guidance for Tester). The other two end-of-stream tests are **expected to keep passing unchanged** — their fixtures carry a `[DONE]` sentinel and therefore take the protocol-complete branch. If either of those goes red, the `saw_done` wiring is wrong; fix the code, do not touch the test.

---

## Guidance for Tester

**Tests to create:**
- **Permanent:** `test_chat_sse_done_without_finish_reason_is_terminal` — a stream that delivers content, then `[DONE]`, and never a `finish_reason`. Assert the stream closes with `content_block_stop` + `message_delta` + `message_stop` and **no** `error` frame, and that the logged `chat_sse_truncated` event carries `saw_done: 1`. This pins the protocol-complete branch — the contract that keeps a provider which omits `finish_reason` but terminates properly from being turned into a retry storm.
- **Permanent:** `test_chat_sse_truncation_with_tool_block_emits_error_event` — a tool_call delta followed by EOF with **no** `[DONE]` and no `finish_reason`. Assert an `error` frame with `error.type == "api_error"` closes the stream, no `message_delta`/`message_stop` follows, and the emitted tool block is still closed by `content_block_stop`. This is *not* a duplicate of `test_chat_sse_tool_call_eof_without_finish` case (a): that fixture carries `[DONE]` and takes the protocol-complete branch, so the cut-with-tool-block shape is otherwise uncovered.
- **Permanent:** `test_chat_sse_drain_event_on_done` — a normal stream ending `finish_reason` → `[DONE]`. Assert one `chat_sse_drain` event carrying `finish_reason`, `drain_exit: "done"`, `drain_bytes`, `drain_ms`, `tool_calls_seen`, `emitted_tool_use`.
- **Permanent:** `test_chat_sse_drain_event_trailing_tool_calls` — a stream whose `finish_reason` precedes the tool_call frames. Assert `tool_calls_seen: 1` and `emitted_tool_use: 1` in `chat_sse_drain` — this is the evidence channel the plan exists to provide.

**Assertions to fold into existing tests rather than new ones** (same fixtures, same proxy startup — adding parallel tests would double the startup cost for one extra field):
- `drain_exit == "time_budget"` into `test_chat_sse_drain_time_deadline` (it already drives the silent-provider socket-timeout path — **keep it driving that path**, not the pre-read `remaining <= 0` check, so the timeout-clause ordering is observable).
- `drain_exit == "byte_budget"` into `test_chat_sse_drain_byte_budget`.
- `drain_exit == "eof"` and the absence of any `chat_sse_drain` event on a cut stream into the migrated `test_chat_sse_truncation_still_works`.

<!-- UPDATED 2026-10-04 (/update-plan): this clause was self-contradictory and the tester correctly split it. A cut stream never reaches the drain, so it logs no chat_sse_drain event at all — "assert drain_exit == 'eof'" and "assert the absence of any chat_sse_drain event" cannot both hold on the same fixture. The tester kept the absence assertion in the migrated test (which is what pins the drain-vs-cut boundary) and covered the "eof" exit with a purpose-built test_chat_sse_drain_event_eof_exit, where the EOF exit is actually reachable. Recorded rather than rewritten so the guidance is not left reading as an instruction that was ignored; see the tester report ./tmp/reports/2026-10-04-truncation-error-and-drain-trace-tester-2026-10-04.json. -->

Use the file's existing helpers (`_trace_events_named`, `_sse_stop_reason`, `_sse_types`, `_sse_tool_use_blocks`, `_chat_sse_fetch_frames`, `_start_chat_sse_proxy`) rather than writing new ones. Note that `_start_chat_sse_proxy(chunks)` appends `[DONE]` by default — pass `add_done=False` (or build the body with `_sse_stream_chunks`, as `test_chat_sse_truncation_still_works` does) for any cut-stream fixture. Register every new test in `ALL_TESTS`.

**Five tests reach the truncation path** — all other fixtures deliver a non-null `finish_reason`. Two migrate (no `[DONE]`), three keep passing unchanged (`[DONE]` present, so they take the protocol-complete branch). Check all five explicitly; if an unchanged one goes red, the `saw_done` wiring is wrong.

**Per `doc/test-catalog.html#adding-tests` step 4:** each new and each migrated test must be run standalone (`-t <name>`) as well as in the full suite, and the full suite must pass with a live proxy running. Report both results.

**Tests to investigate for retirement:**
- Planner candidates — **none retired**; two are *migrated* (intent preserved, assertions flipped), and three are explicitly **not** to be changed:
  - `[tests/test_chat_sse.py::test_chat_sse_eof_without_finish_reason]` — **migrate.** Builds its body without `[DONE]`, so it is a cut stream. Keep the `content_block_stop` assertion (open blocks are still closed before the error frame); flip the `message_delta`/`message_stop` assertions to their absence; add the `error` frame assertion; keep the `chat_sse_truncated` event and assert `saw_done: 0`.
  - `[tests/test_chat_sse.py::test_chat_sse_truncation_still_works]` — **migrate**, identically. It was added by `2026-10-02-drain-after-finish-reason` to pin the *unchanged* truncation path; that plan's decision is deliberately reversed here (see the History table). Keep it — the path it pins still exists, only its closing frame changes.
  - `[tests/test_chat_sse.py::test_chat_sse_tool_call_eof_without_finish]` — **do not change.** Its three cases use `_start_chat_sse_proxy`'s default `add_done=True`, so they are protocol-complete streams and keep their `end_turn`/`null`/`message_stop` and degradation-event assertions. Its case (c) also pins the incomplete-tool-metadata degradation event, which the Step 1 refactor must preserve (see the Risks row).
  - `[tests/test_chat_sse.py::test_chat_sse_eof_empty_tool_calls_sentinel]` — **do not change.** Same reason: `[DONE]` is present, so the `end_turn`-versus-`null` discriminator it was written for survives on the protocol-complete branch.
  - `[tests/test_chat_sse.py::test_chat_sse_pending_buffer_cap_exceeded]` — **do not change.** A fifth truncation-path fixture (`[DONE]` present, no `finish_reason`, tool-call deltas seen), so it stays on the synthesized branch and its `_sse_stop_reason(frames) is not None` assertion keeps asserting a real `null` rather than becoming vacuous. Confirm it, but do not edit it.
- Tester may identify additional candidates during test work.

**Retirement procedure:** For each candidate, verify the test exercises code being removed/changed. If obsolete: delete and note in session report. If still valid: document why in session report (e.g., "tests error handling path still present").

---

**Round 5 addition (2026-10-04, from the Phase 6 review).** One more permanent test, because the Phase 6 reviewer found the H1 fix pinned by no committed test: the unstarted-tool counting loop now lives in `log_degradation_if_needed()` (server.py:1862-1865) rather than in `terminal()`, and the cut path calls it (server.py:2222) — but the only test that reaches that loop, `test_chat_sse_tool_call_eof_without_finish` case (c), uses `_start_chat_sse_proxy`'s default `add_done=True`, i.e. the protocol-complete branch. The pin lives solely in the plan's own `step1.py`, which is under the gitignored `tmp/`; move the loop back into `terminal()` and every committed test stays green. See `./tmp/reports/2026-10-04-truncation-error-and-drain-trace-review-2026-10-04.json` (finding 1, Medium).

- **Permanent:** `test_chat_sse_tool_degradation_on_cut_stream` — case (c)'s fixture, cut instead of complete:

  ```python
  chunks = [
      _cc({"role": "assistant"}),
      _cc({"tool_calls": [{"index": 0, "id": "call_incomplete"}]}),
  ]
  proxy_port, trace_file, cleanup = _start_chat_sse_proxy(chunks, add_done=False)
  ```

  An `id` with no `function.name` never opens a block, so the tool is tracked but never started — which is what makes the counting loop the thing under test.

  Assert, in this order: (1) `_degraded_trace_events(trace_file)` has **exactly one** entry — this is the H1 pin and the reason the test exists; (2) `_sse_content_block_starts(frames)` is empty (still no `tool_use` on the cut path); (3) the stream closes with an `error` frame whose `error.type` is `"api_error"`, with **no** `message_delta` and **no** `message_stop`; (4) the `chat_sse_truncated` event carries `saw_done: 0`.

  **No polling is needed here, unlike the `_wait_for_trace_events` tests:** both trace writes precede the client-visible error frame (`log_degradation_if_needed()` at server.py:2222, `chat_sse_truncated` at :2197, the `error` write at :2223), so a test that reads the client stream to EOF via `_chat_sse_fetch_frames` cannot outrun them. Prefer the EOF read over a poll, and say so in a comment so the next reader does not "fix" it into a poll.

  **Why it must be a cut stream:** the point is the `saw_done: 0` path, which no longer calls `terminal()`. A `[DONE]`-bearing version of this fixture would pass through the old code path and would not pin the refactor at all. Register it in `ALL_TESTS`, and run it standalone (`-t`) as well as in the full suite per the existing instruction above. **Do not touch `doc/`**: the catalogue recount is planner-owned (Step 5), so the tester's round is the test file and its report only — the planner moves the two count sites to 55 and the grand total to 372, and adds the catalogue entry, once the test has landed and its name is final.

---

## Summary

**Problem.** When the chat-mode upstream stream ends without ever delivering a `finish_reason` chunk, the proxy logs `chat_sse_truncated` and then *synthesizes* a terminal sequence with a clean `stop_reason: "end_turn"` (or `null` when tool frames were seen). On the wire the synthesized turn is indistinguishable from one the model actually finished, so the client records a completed message, reports no error, and never retries. The user sees a turn that announced an action and then did nothing, or — when the cut landed before any visible block — Claude Code's own `[Your previous response had no visible output…]` nudge. Post-fix evidence: two occurrences in the 16.8 h after `4b2176c`, one user-visible at `2026-10-03T18:07:37Z` as a `thinking`-only `end_turn` message with **all-zero usage**.

**The distinction that shapes the fix.** "Ended without a `finish_reason`" covers two different things, and treating them alike is itself a hazard:

- The provider sent its `[DONE]` sentinel — the stream is **protocol-complete**, it simply never said why it stopped. Synthesizing is correct here and must be preserved: a provider that always omits `finish_reason` but terminates properly would otherwise turn into a retry storm against a retryable error, replacing a working integration with an outage.
- No `[DONE]` ever arrived — the connection was **cut mid-response**. The response is genuinely incomplete, and a synthesized success is a false one.

That second case is what the observed truncation is: the upstream emits its usage frame immediately before `[DONE]` (`stream_options: {include_usage: true}`), and the failing turn recorded `input_tokens: 0, output_tokens: 0` — so the stream died before the usage frame, and therefore before the sentinel. `saw_done` is tracked and recorded on the trace event so the two cases are distinguishable rather than inferred.

**Approach.** On the cut path, close any open content blocks, emit the degradation summary, and close the stream with an Anthropic `error` SSE event (`type: "api_error"` — the 500-equivalent, retryable type) instead of a synthetic terminal. The error event terminates the stream just as effectively as `message_stop` did, so the original anti-hang rationale is preserved, but the client now knows the response was cut short and re-issues the request. On the protocol-complete path nothing changes. `message_start` is still emitted first when nothing has been written, so the envelope stays legal; no `message_delta` and no `message_stop` follow an error.

Second, the post-finish drain becomes self-describing: one coalesced `chat_sse_drain` event per drained stream records `finish_reason`, why the drain ended (`done` / `eof` / `read_error` / `time_budget` / `byte_budget` / `response_cap`), how many bytes it read, how long it ran, and whether tool frames were seen and emitted. Today a drain that exits on its byte or time bound and a drain that captured nothing leave *identical* evidence — none — so a missing trailing tool call can only be inferred. After this, every chat-mode stream that returned 200 has a logged terminal disposition: `chat_sse_drain` when a `finish_reason` arrived, `chat_sse_truncated` (with `saw_done`) when it did not.

**Why the second step.** The four residual "repeat your proposed tool call" incidents in the window are *not* the proxy's doing — all four are on `longcat-2.5-preview-free`, each carries real usage (so nothing was cut off), the trace holds no diagnostic for them, and every path that drops a tool call is instrumented. They are upstream non-emission (recorded as `upstream-silent-tool-call-omission`, won't-fix). The drain event is what turns the *next* such incident from an inference into a proof.

**Refactor consequence.** `terminal()` is not only a frame emitter: it also closes open blocks and finalizes incomplete-tool bookkeeping before evaluating the degradation predicate. Removing it from the cut path therefore moves two side effects, not one. Both are carried: block closure is extracted as `close_all_blocks()` and called on the cut path, and the unstarted-tool counting loop moves *into* `log_degradation_if_needed()` so every terminal path finalizes identically. Dropping the counting loop was the plan's first draft's error, and it would have silently stopped the `chat_sse_tool_degradation` event firing for a cut stream whose only defect is a tool call that never produced a start.

**Alternatives considered and rejected.** (a) *Retry the upstream POST inside the proxy on truncation* — impossible once bytes have reached the client, and both observed truncations had already streamed a block. (b) *Keep a synthetic terminal but use a distinguishable stop reason* (e.g. `max_tokens`) — a lie of a different shape, and it would corrupt the meaning of a stop reason the client acts on. (c) *Error on every no-`finish_reason` stream, including after `[DONE]`* — creates the retry storm described above. (d) *Error event only when nothing usable was emitted* — leaves the exact "prose then silence" shape looking complete, which is the symptom being fixed. (e) *Per-response drain logging behind a flag* — the event is small and the trace is pruned at five days; a flag would leave it off when the next incident happens.

**Out of scope.** The anthropic-mode path (it forwards upstream SSE bytes unchanged, so a truncation already reaches the client as an incomplete stream) and the buffered chat path (a mid-body drop raises into the retry loop) are both unaffected and unchanged. The five other pre-existing residuals of `2026-10-02-drain-after-finish-reason` stay as dispositioned there. No change to retry policy, backoff, or the admin surface.

## Repo Mode

Public

*Detected at plan creation. Determines: plan archival path, commit-message content, staged files.*

## Document Overrides

| Document | Rule Overridden | Reason |
|----------|----------------|--------|
| doc/provider-modes.html | The `#chat-sse` section's "Two details shape the output" bullet states "Terminal events are emitted exactly once — after the post-finish drain, or synthesised at EOF or on truncation. An Anthropic client that never receives message_stop hangs, so the synthesis is unconditional" | This is where the unconditional-synthesis claim actually lives (the `#chat-sse-drain` subsection does not carry it). The bullet must be rewritten: terminal events are emitted once after the post-finish drain; a stream that ends without a `finish_reason` is closed either by a terminal sequence (when `[DONE]` was received) or by an SSE `error` event (when it was not), and the anti-hang property now rests on the error event terminating the stream |
| doc/provider-modes.html | The `#chat-sse-drain` section's closing paragraph says a never-finished stream "is unaffected … still takes the EOF path and reports `chat_sse_truncated`" | The path is no longer unaffected — it now closes with an error event when `[DONE]` never arrived. The paragraph must state the two dispositions and the `saw_done` discriminator |
| doc/provider-modes.html | The `#malformed-args` error box's closing sentence states that "a stream that ends without any finish_reason reports `null` when tool-call deltas were seen rather than `end_turn`" | That `null`-versus-`end_turn` discriminator survives only when `[DONE]` was received. On a cut stream with tool-call deltas there is no stop reason at all. The sentence must be rescoped to the protocol-complete case |
| doc/provider-modes.html | The `#degradation` event table (line 486) groups `chat_sse_truncated` with `chat_sse_malformed_json` and the cap events as "an SSE frame was truncated, malformed, or exceeded a buffer bound" | That is the same routine-framing the trace-log override removes, and it is now wrong: `chat_sse_truncated` is the "no `finish_reason`" disposition for a whole stream, discriminated by `saw_done`, not a per-frame defect. The row must move `chat_sse_truncated` out of that group (or point at trace-log.html for its real meaning)
| doc/provider-modes.html | The `finish_reason` → `stop_reason` mapping table's intro reads as though it governs every stream | The table is keyed entirely by a *delivered* `finish_reason` (rows `stop`/`length`/`tool_calls`/anything else) and has no row for a finish-less stream, so it must be scoped to streams that delivered one — a cut stream reports no stop reason because no `message_delta` is emitted, not because the table mapped it |
| doc/provider-modes.html | The `#malformed-args` error box's closing sentence states that "a stream that ends without any finish_reason reports `null` when tool-call deltas were seen rather than `end_turn`" | That `null`-versus-`end_turn` discriminator survives only when `[DONE]` was received. On a cut stream with tool-call deltas there is no stop reason at all. The sentence must be rescoped to the protocol-complete case |
| doc/trace-log.html | The event inventory describes `chat_sse_truncated` as a routine terminal event alongside `chat_sse_malformed_json` and the cap events | It is now the "no `finish_reason`" diagnostic for both dispositions, discriminated by the new `saw_done` field, and on the cut path the stream closes with an error. The row must say so, and the new `chat_sse_drain` event must be registered with its fields and the exhaustiveness rule |

## Risks

| Risk | Impact | Mitigation |
|------|--------|----------|
| Clients that treat a mid-stream `error` event as fatal rather than retryable | A cut turn becomes a visible failed turn instead of a silent one | That is the intended trade — the current behavior is a silent *false success*, which is strictly worse. `api_error` is documented retryable (500-equivalent); the tester pins the emitted frame's `error.type`. The plan's rationale ("the client re-issues the request") is verified against the client on the first post-landing cut stream, not asserted here |
| A provider that omits `finish_reason` but terminates with `[DONE]` would be turned into a retry storm | A working integration becomes an outage | This is why the cut path requires `saw_done == 0`. Pinned by `test_chat_sse_done_without_finish_reason_is_terminal` and by the two existing `[DONE]`-bearing tests, which must keep passing unchanged |
| `socket.timeout` is a subclass of `OSError`, so a separate `except socket.timeout` clause placed after the existing tuple would be dead code | The drain reports `read_error` for its own deadline, conflating "upstream died" with "we stopped waiting" | Step 2 orders the clauses `socket.timeout` **first**; the step-2 script asserts the literal clause exists *and* that its line precedes the combined tuple's, and Guidance for Tester requires `test_chat_sse_drain_time_deadline` to keep driving the socket-timeout path so the ordering is observable end-to-end. Behavior is unchanged either way — both clauses `break` exactly as the single `OSError` clause did before |
| Removing `terminal()` from the cut path drops two side effects, not one: block closure and the unstarted-tool counting loop that feeds the degradation predicate | A cut stream with an incomplete tool call stops firing `chat_sse_tool_degradation`, and open blocks are left unclosed (an ill-formed stream for any client that streams blocks) | Step 1 extracts `close_all_blocks()` and calls it on the cut path before the error frame, and moves the counting loop into `log_degradation_if_needed()` so every terminal path finalizes identically. Both are asserted by the step-1 script, and the two `[DONE]`-bearing tests that assert block closure and the degradation event must keep passing |
| `chat_sse_drain` adds one trace entry per streamed chat response (~1 per successful chat request, on top of the existing `request` / `mode_dispatch` / `cache_control_stripped` trio) | Trace file grows ~30% faster | Accepted: the trace is pruned of entries older than 5 days on every `start`, and a conditional variant would be absent exactly when the next incident is being diagnosed. If volume becomes a problem, the emission predicate can be narrowed later without changing the schema |
| `chat_sse_drain.finish_reason` would carry an upstream-controlled value verbatim | An unbounded or non-string value (a multi-KB string, or a bool/number/list) would be written into the trace, since `handle_frame` accepts any truthy `finish_reason` and the drain-revision path accepts any truthy replacement | Step 2 coerces the logged field: a `str` is logged truncated to 64 chars, anything else becomes `"<non-string>"`. The raw value is still what the stop-reason logic consumes — only the trace projection is bounded |
| `drain_ms` measured at emission rather than at the drain's end | The field is documented as the drain's duration, but emission follows the terminal writes (up to six client-bound frames plus a possible degradation trace write), so the value would include the write cost and silently overstate drain time | Step 2 captures `drain_ended_at` at the read loop's exit and measures from `finish_seen_at` to that, so the field means what it says |

## Rollback

The change is atomic and reverts as a unit: `src/claude_retry_proxy/server.py` (steps 1–2), `tests/test_chat_sse.py`, and the four doc surfaces (steps 3–5) move in lockstep, because the docs quote `drain_exit` values, the `saw_done` field, and the error-event shape that only exist once the code lands. Reverting `server.py` alone leaves the two migrated tests asserting an `error` frame that is no longer emitted, and reverting the tests alone leaves the doc pages describing behavior the code no longer has. There is no data migration and no configuration change: no persisted artifact carries a schema this plan touches (`feature-compatibility.json` is untouched), and the server's public surface — CLI, config files, admin API, environment variables — is unchanged. To roll back, revert the whole commit; the two tests revert with the code, and the doc pages revert to describing the unconditional synthesis. No flag, dual-write, or staged rollout is needed: the changed behavior is confined to streams that were already being cut short, and the pre-change behavior (a silent false success) is worse than either the new behavior or a clean revert.

## Proposed Changes

Each step includes verification checks tagged with confidence (see Prime Directive 4).
`(auto)` = mechanical, coder self-verifies. `(scripted)` = deterministic multi-step, coder runs provided script.
Every step must have at least one verification check executable by its owner (coder steps: coder checks; tester steps: tester verify; planner steps: Evidence).
Steps MUST use this numbered-list format exactly. The `### Step N:` heading format is deprecated and must not be used.

1. **Step 1:** In `_stream_chat_sse_to_anthropic` (`src/claude_retry_proxy/server.py`), split the end-of-stream disposition on whether `[DONE]` was received, close blocks and finalize diagnostics on the cut path, and refactor `terminal()`'s two side effects into shared helpers.

   (a) **Track the sentinel.** Initialize `saw_done = False` alongside `message_started = False`. In the read loop's frame dispatch, record it on the non-drain branch:

   ```python
                    if result == "done":
                        if finish_reason_seen is not None:
                            drain_done = True
                            drain_exit = "done"
                            break
                        saw_done = True
                        continue
   ```

   (b) **Split `terminal()`.** Immediately above `def terminal(`, add two helpers and remove the moved statements from `terminal()`'s body:

   ```python
        def close_all_blocks():
            """Close every open content block — scalar and tool — exactly once."""
            while open_blocks:
                idx = open_blocks.pop()
                write({"type": "content_block_stop", "index": idx})
            close_open_tool_blocks(validate=False)

        def log_degradation_if_needed(force_log=False):
            """Finalize tool bookkeeping, then emit the coalesced degradation
            summary when any counter is set.

            The unstarted-tool pre-pass lives here rather than in terminal() so
            every terminal path — including the cut-stream error path, which no
            longer calls terminal() — finalizes identically.
            """
            nonlocal malformed_tool_count
            for st in tool_states.values():
                if not st["started"] and not st["dropped"]:
                    malformed_tool_count += 1
                    st["dropped"] = True
            if force_log or malformed_tool_count or overflow_tool_count \
                    or dropped_fragment_count or unparseable_arg_count \
                    or scalar_after_tools_dropped or frame_dropped:
                log_tool_degradation_summary()
   ```

   `terminal()` then becomes: `close_all_blocks()`, the usage/message_delta/`message_stop` writes exactly as they are today, then `log_degradation_if_needed(force_log)` as its last statement. Its observable behavior is unchanged — only the ordering of a counter mutation relative to the frame writes differs, and that is not on the wire.

   (c) **Rewrite the truncation path.** Locate it by its leading comment `# EOF reached without a finish_reason chunk:` — it follows the post-drain block and is the last thing in the method before `return first_byte_ms`. Keep the existing comment's replacement explanation, and replace the trailing `sr = "end_turn"` / `if tool_calls_seen: sr = None` / `terminal(sr)` with:

   ```python
        if saw_done:
            # The provider closed the stream properly, it just never said why:
            # protocol-complete, so close it with a terminal sequence.
            sr = "end_turn"
            if tool_calls_seen:
                sr = None
            terminal(sr)
            return first_byte_ms
        # No [DONE] ever arrived: the connection was cut mid-response and the
        # response is incomplete. Close it with an SSE error event, not a
        # synthesized terminal — a synthesized end_turn is indistinguishable, on
        # the wire, from a turn the model actually finished, so the client
        # records a completed message, reports no error and never retries.
        # `api_error` is the retryable 500-equivalent, so the client re-issues
        # the request. Close open blocks first so the partial turn is a
        # well-formed stream up to the error, and finalize the degradation
        # diagnostics — terminal() would have done both.
        close_all_blocks()
        log_degradation_if_needed()
        write({
            "type": "error",
            "error": {
                "type": "api_error",
                "message": "upstream stream ended without a finish_reason",
            },
        })
        return first_byte_ms
   ```

   Add `"saw_done": 1 if saw_done else 0` to the existing `chat_sse_truncated` `log_trace` call, and restate its comment. Do **not** emit `message_delta` or `message_stop` on the error path, and do **not** call `terminal()` on it — `close_all_blocks()` and `log_degradation_if_needed()` are already idempotent, but a second `terminal()` would duplicate `message_delta`/`message_stop` on the `saw_done` branch.

   (d) **Update the method docstring** (`_stream_chat_sse_to_anthropic`), whose terminal-events paragraph still says terminal events are "emitted exactly once — after the post-finish drain, or synthesized at EOF/truncation so the Anthropic client never hangs". Describe the two dispositions (terminal sequence after a `finish_reason` or after a `[DONE]`-terminated stream; SSE `error` with `error.type: api_error` on a cut stream, with no `message_delta`/`message_stop`). Leave the drain paragraph unchanged.

   → coder verify (auto): `grep -n 'sr = "end_turn"' src/claude_retry_proxy/server.py` lists only hits inside the `if saw_done:` branch, and `grep -c 'saw_done' src/claude_retry_proxy/server.py` ≥ 4
   → coder verify (scripted): `python ./tmp/verification/2026-10-04-truncation-error-and-drain-trace-step1.py` exits 0
   → tester verify: `test_chat_sse_eof_without_finish_reason` and `test_chat_sse_truncation_still_works` (migrated), `test_chat_sse_truncation_with_tool_block_emits_error_event` and `test_chat_sse_done_without_finish_reason_is_terminal` (new) pass; `test_chat_sse_tool_call_eof_without_finish` and `test_chat_sse_eof_empty_tool_calls_sentinel` pass **unchanged**

2. **Step 2:** Make the post-finish drain self-describing — record why the read loop exited and when trailing frames arrived, emit one coalesced `chat_sse_drain` trace event per drained stream, record whether the request declared tools, detect the unfinished turn in shadow mode, and teach the trace analyzer to report all of it.

   (a) Initialize `drain_exit = None` and `drain_ended_at = None` alongside `drain_bytes = 0`.

   (b) Assign `drain_exit` at **every** exit of the read loop (the `while True:` that calls `resp.read1(8192)`). The values are fixed:

   | Exit | Value |
   |------|-------|
   | `if drain_bytes > MAX_DRAIN_BYTES:` | `"byte_budget"` |
   | `if remaining <= 0:` | `"time_budget"` |
   | a `socket.timeout` raised by `resp.read1(...)` | `"time_budget"` |
   | `if not chunk:` (EOF) | `"eof"` |
   | any other `IncompleteRead` / `RemoteDisconnected` / `OSError` from `resp.read1(...)` | `"read_error"` |
   | the drained `[DONE]` branch, next to `drain_done = True` | `"done"` |
   | the degraded-mode branch (`if buf is None:`) next to `_log_response_cap_exceeded` | `"response_cap"` — **inert on drain streams**; see below |
   | `if bytes_streamed > SETTINGS.max_response_size:` at the loop end | `"response_cap"` |

   Both cap exits are **separate** exits and each needs its own assignment: the degraded-mode one carries 20 spaces of indentation, the loop-end one 16, so a patch written for one does not touch the other. The degraded-mode one is nevertheless unreachable whenever `drain_exit` is read — seeing a `finish_reason` implies `message_started`, and `buf = None` is only ever set in the `if not message_started:` branch of the buffer-cap handler, after which `handle_frame` never runs again. Wire it anyway: it is one line, it keeps the "every exit records its reason" invariant literally true (which is what makes the check scriptable), and the loop-end check is the reachable one.

   Record the drain's end where the loop actually ends — the first statement after the read loop's `except _DISCONNECT_ERRORS: raise`, *before* the socket-timeout restore block — so `drain_ms` measures the drain and not the terminal writes that follow it:

   ```python
        drain_ended_at = time.time()
   ```

   Split the read's exception handling so the drain's own deadline is distinguishable from a dead upstream. `socket.timeout` must come **first** — it is a subclass of `OSError`, so the existing tuple would otherwise swallow it:

   ```python
                except socket.timeout:
                    drain_exit = "time_budget"
                    break
                except (http.client.IncompleteRead, http.client.RemoteDisconnected,
                        socket.error, OSError):
                    drain_exit = "read_error"
                    break
   ```

   This changes no behavior: both clauses `break` exactly where the single `OSError` clause did. `drain_exit` is only read when `finish_reason_seen is not None`, so assigning it on the non-drain path is inert.

   (c) Emit the event in the post-drain block (`if finish_reason_seen is not None:`), immediately after the three-way `terminal(...)` dispatch and before the `post_finish_suppressed` block. `finish_reason_seen` is an upstream-controlled value — `handle_frame` accepts any truthy `finish_reason` and the drain-revision path accepts any truthy replacement — so the logged field is coerced rather than written through:

   ```python
            _fr = finish_reason_seen if isinstance(finish_reason_seen, str) else "<non-string>"
            log_trace({
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "event": "chat_sse_drain",
                "request_id": request_id,
                "finish_reason": _fr[:64],
                "drain_exit": drain_exit,
                "drain_bytes": drain_bytes,
                "drain_ms": int((drain_ended_at - finish_seen_at) * 1000) if drain_ended_at else 0,
                "tool_calls_seen": 1 if tool_calls_seen else 0,
                "emitted_tool_use": 1 if emitted_tool_use else 0,
            })
   ```

   Consequence to preserve: a chat-mode stream that returned 200 now ends with exactly one of `chat_sse_drain` or `chat_sse_truncated` — unless the request aborts with an exception, which re-raises before either (a client disconnect, or an unparseable upstream frame shape). That caveat is the wording steps 3–4 must carry; do not narrow it to client disconnect alone.

   (d) **Thread what the drain event and the detector need into the stream handler** — the denominator that makes `emitted_tool_use` interpretable, plus the `provider`/`key` the detector event carries.

   <!-- UPDATED 2026-10-04 (/update-plan): the first draft said the flag is "passed from both call sites in `forward_request` (lines ~947 and ~1039, where the parsed client body is already in scope as `body_json`)". That is wrong about the function: those call sites are inside `_forward_core` (def ~872), while `body_json` and `key_name` are locals of `_forward_request_impl` (def ~503). Taken literally it compiles and then raises NameError on every streamed 2xx response — a total streaming outage. The same draft threaded only `tools_declared` while 2(f)'s event list requires `provider` and `key`. Both defects were found by the round-3 coder and are recorded in ./tmp/reports/2026-10-04-truncation-error-and-drain-trace-tools-declared-scope-premise-wrong.json and ./tmp/reports/2026-10-04-truncation-error-and-drain-trace-unfinished-turn-provider-key-threading.json. -->

   The names live in `_forward_request_impl`; the code that reads them is two frames down, so all three cross the boundary as parameters — never as closures:

   - In `_forward_request_impl`, beside the client-body parse, derive the flag:
     ```python
        _tools = _client_body.get("tools") if isinstance(_client_body, dict) else None
        tools_declared = isinstance(_tools, list) and bool(_tools)
     ```
   - Add `tools_declared=False, key_name=None` to `_forward_core`'s signature and pass both at **both** `_forward_request_impl` → `_forward_core` call sites, mirroring how `provider_name` and `mode` already flow. `provider_name` is already a `_forward_core` parameter, so only the key name needs carrying.
   - Extend the two downstream signatures — `_stream_upstream_response(..., tools_declared=False, provider=None, key=None)` and `_stream_chat_sse_to_anthropic(..., tools_declared=False, provider=None, key=None)` — and pass `tools_declared=tools_declared, provider=provider_name, key=key_name` at **both** `_stream_upstream_response` call sites in `_forward_core`.
   - Add `"tools_declared": 1 if tools_declared else 0` to the `chat_sse_drain` event. One home, and that is the event where it is read — not the `request` event, which would force a join.
   - **Discipline note:** the `do_POST` comment recording that `key` is "never threaded through forward_request's return tuple" governs the *return tuple*. A parameter is not a return value, and the detector event needs the value; threading it is the intended reading, not a violation of that note.
   - **The boundary is enforced, not merely documented.** `./tmp/verification/2026-10-04-truncation-error-and-drain-trace-step2.py` now carries an AST name-resolution check (added 2026-10-04): in each of `_forward_core`, `_stream_upstream_response` and `_stream_chat_sse_to_anthropic`, every read of `tools_declared`, `key_name`, `provider` and `key` must be bound *in that function* — as a parameter, assignment, loop/comprehension target, nested def, import or `except` handler. Text checks cannot see this class of defect: the plan's original literal wording satisfied every `grep` in both scripts and still raised `NameError`. `./tmp/verification/_dryrun-step1-step2.py` proves the new check load-bearing with a `revert-core-param` arm that restores the plan's original wording and must fail step 2.

   The flag stays a 0/1 boolean, not a tool inventory: no content, no `--all` gate.

   (e) **Record how late the trailing frames actually were** — the statistic that decides whether the `MAX_DRAIN_SECONDS` (5 s) budget is generous or binding. Today a drain that waited 5 s and one that caught a tool call at 4.8 s look identical. Add a per-frame counter (`frames_seen`, incremented in the inner frame loop) and, in the read loop's drain branch, take one offset per chunk:

   ```python
                    _off = (time.time() - finish_seen_at) * 1000
   ```

   then, after that chunk's frames are processed: if the chunk yielded frames (`frames_seen` advanced), set `first_late_ms` if unset, always set `last_late_ms = _off`, and increment `late_frames`; and if `tool_calls_seen` transitioned false→true while processing it, set `late_tool_call_ms = _off` — the one number that answers "is the budget long enough?", since it is the arrival latency of a tool call that *would have been lost* without the drain. Initialise all four with the other drain locals and add `late_frames`, `first_late_ms`, `last_late_ms`, `late_tool_call_ms` (null when none arrived late) to the `chat_sse_drain` event.

   (f) **Detect the unfinished turn in shadow mode — log only, no action.** Keep two bounded pieces of state in the transform: `text_emitted` (any text delta has been written) and `text_tail` (the trailing ≤200 chars of the concatenated text deltas — held in memory, never logged). At the decision point, immediately before the terminal dispatch, evaluate:

   ```python
            if (tools_declared and not emitted_tool_use
                    and finish_reason_seen == "stop"
                    and text_emitted and text_tail.rstrip().endswith(":")):
   ```

   When it holds, log one `chat_sse_unfinished_turn` event — `request_id`, `tier`, `provider`, `key`, `finish_reason`, `tool_calls_seen` and `emitted_tool_use` as 0/1, `tools_declared`, `text_tail_len` (an integer; the tail itself is never written), and `rule: "colon_after_prose"` — and **change nothing else**: the terminal sequence is emitted exactly as today. This is the shadow rung: it measures the predicate's precision on real traffic, per provider, before any behaviour depends on it. It must be structurally incapable of acting — no error write, no early return, no `terminal()` suppression.

   (g) **Teach `scripts/analyze_proxy_trace.py` to report it**, so the numbers above are a statistic rather than a grep. Add one section: per provider, the count of `chat_sse_unfinished_turn`; the distribution (min / median / p90 / max) of `late_tool_call_ms` and `last_late_ms`; and the share of drained streams that exited on `drain_exit == "time_budget"` — the last two together answer "is the 5 s budget binding?" directly.

   → coder verify (auto): `grep -c 'drain_exit = "' src/claude_retry_proxy/server.py` ≥ 7; `grep -c 'tools_declared' src/claude_retry_proxy/server.py` ≥ 4; `grep -c 'chat_sse_unfinished_turn' src/claude_retry_proxy/server.py` ≥ 1; `python scripts/analyze_proxy_trace.py --help` still exits 0
   → coder verify (scripted): `python ./tmp/verification/2026-10-04-truncation-error-and-drain-trace-step2.py` exits 0
   → tester verify: `test_chat_sse_drain_event_on_done` and `test_chat_sse_drain_event_trailing_tool_calls` pass, the `drain_exit` assertions folded into `test_chat_sse_drain_time_deadline` and `test_chat_sse_drain_byte_budget` pass, a request carrying a non-empty `tools` list logs `tools_declared: 1` and one without logs `0`, a stream whose prose ends in `:` after `stop` with no tool block logs exactly one `chat_sse_unfinished_turn` **and still terminates with `message_delta`/`message_stop` as before**, and a `time_budget` drain reports a non-null `late_tool_call_ms` when a tool call arrives late

3. **Step 3:** Update `doc/provider-modes.html` — the `#chat-sse` terminal-events bullet, the `#chat-sse-drain` closing paragraph, the `finish_reason` → `stop_reason` mapping table's scope, the `#malformed-args` error box, and the `#degradation` event table row — plus one new row in `CLAUDE.md`'s "Moved out of this section" table.

   Rewrite the `#chat-sse` bullet that currently reads "Terminal events are emitted exactly once — after the post-finish drain, or synthesised at EOF or on truncation … the synthesis is unconditional": terminal events are emitted exactly once after the post-finish drain; a stream ending without a `finish_reason` closes with a terminal sequence if `[DONE]` was received, or with an SSE `error` event (`error.type: "api_error"`) if it was not — and the anti-hang property now rests on the error event terminating the stream. Restate the `#chat-sse-drain` closing paragraph to describe both dispositions and the `saw_done` discriminator. Scope the mapping table's intro to streams that delivered a `finish_reason`; do **not** claim the table has a finish-less row — it has none, which is exactly why a cut stream reports no stop reason at all. Fix the `#malformed-args` error box's closing "reports null … rather than end_turn" sentence to apply only to the protocol-complete case. In the `#degradation` event table, move `chat_sse_truncated` out of the row that groups it with `chat_sse_malformed_json` and the cap events (that row's "an SSE frame was truncated, malformed, or exceeded a buffer bound" is a per-frame framing that no longer fits a whole-stream disposition), giving it its own row or a pointer to trace-log.html. Add the `chat_sse_drain` event to the drain section: emission condition (once per stream that reached a `finish_reason`), its fields, the fixed `drain_exit` values, and the exhaustiveness rule against `chat_sse_truncated` — including the exception caveat (a client disconnect or an unparseable upstream frame shape aborts before either).

   Record the diagnosed upstream failure mode in the same section, in one short paragraph **written provider- and project-agnostically**: no provider or model names, no request ids or timings, no absolute paths, no client project or transcript names, and no link to or copy of the gitignored report that holds them. The paragraph documents the *shape* — a model may end an agentic turn with prose plus `finish_reason: "stop"` and emit no tool_call at all, which the proxy relays faithfully and which is not a proxy defect — so the next investigator recognizes it without re-deriving the analysis.

   In `CLAUDE.md`, add one row to the "Moved out of this section" table (the table has no existing row about truncation synthesis — do not amend the 5-second drain row, which stays accurate): first cell `A chat-mode stream that ends with no finish_reason closes differently depending on whether [DONE] arrived`, second cell a link to `doc/provider-modes.html#chat-sse`.

   Finally, bump the `Last updated: …` header line and footer on every page this plan edits to the landing date (steps 3, 4, and 5 each touch a page).

   → Evidence: `grep -n 'synthesis is unconditional' doc/provider-modes.html` returns empty; `grep -c 'chat_sse_drain' doc/provider-modes.html` ≥ 1; `grep -n 'saw_done' doc/provider-modes.html` ≥ 1; `grep -n 'reports null' doc/provider-modes.html` shows the sentence scoped to the protocol-complete case; `grep -c 'longcat\|space-bunny\|mimo' doc/provider-modes.html` is 0; every edited page's `Last updated` reads the landing date; `python ~/.claude/scripts/doc_structure_check.py` exits 0

4. **Step 4:** Update `doc/trace-log.html` — the event inventory.

   Register `chat_sse_drain` with its fields and its once-per-drained-stream rule; register `chat_sse_unfinished_turn` as a **log-only** diagnostic that changes no response, listing the fields it carries and stating explicitly that it is the shadow-mode measurement of the detector described in `provider-modes.html`; add the late-frame fields with their meaning (the offset from the finish signal at which trailing frames, and specifically a trailing tool call, actually arrived — the evidence for whether the 5 s drain budget is generous or binding, noting that the budget costs latency only when a provider goes silent after `finish_reason`); and rewrite the `chat_sse_truncated` row: it is the "no `finish_reason`" diagnostic, it now carries `saw_done`, and on the `saw_done: 0` path the stream closes with an `error` event and no stop reason. State the exhaustiveness rule: every chat-mode stream that returned 200 and started ends with exactly one of the two, unless the request aborts with an exception (a client disconnect, or an unparseable upstream frame shape). Record the joins that make the set useful: `tools_declared` + `emitted_tool_use` on `chat_sse_drain` is the per-provider rate of tool-bearing turns that emitted no `tool_use`. Bump the page's `Last updated` header and footer.

   → Evidence: `grep -c 'chat_sse_drain' doc/trace-log.html` ≥ 1 and the string appears inside the `#events` table; `grep -c 'chat_sse_unfinished_turn' doc/trace-log.html` ≥ 1; `grep -c 'saw_done' doc/trace-log.html` ≥ 1 in the `chat_sse_truncated` row; `grep -c 'late_tool_call_ms' doc/trace-log.html` ≥ 1; the page's `Last updated` reads the landing date; `python ~/.claude/scripts/doc_structure_check.py` exits 0

5. **Step 5:** Reconcile `doc/test-catalog.html` against the final landed suite.

   Recount rather than transcribe: the two migrated tests keep their names with rewritten descriptions carrying the page's existing `(changed YYYY-MM-DD …)` marker, the four new tests are added as entries, and the four tests whose behavior is unchanged keep their existing descriptions. Update **all** count representations on the page — the grand total, the `test_chat_sse.py` per-file row, and the SSE category heading — and confirm each per-file section balances against its declared count. Bump the page's `Last updated` header and footer.

   → Evidence: the page's grand total equals `python -c "import glob,re;print(sum(len(re.findall(r'^def (?:test_|doc_)',open(f,encoding='utf-8').read(),re.M)) for f in glob.glob('tests/*.py')))"` (note: `grep -c` over multiple files emits one count per file, so it cannot be compared against a total); the `test_chat_sse.py` section's declared count equals its listed entries and equals `grep -cE '^def test_' tests/test_chat_sse.py`; the page's `Last updated` reads the landing date; `python ~/.claude/scripts/doc_structure_check.py` exits 0; `python tests/test_docs.py` reports 11/11

## Guidance for Planner

Documentation tasks you will execute yourself (not the coder):

- **Doc files to create/update:** `doc/provider-modes.html` (step 3), `doc/trace-log.html` (step 4), `doc/test-catalog.html` (step 5), `CLAUDE.md` (folded into step 3).
- **`.claude/mega-audit-files.json`:** does not exist in this repo — no entries to add.
- **When:** after the coder round lands and the tester has reported, so the catalogue recount reflects the final landed test count. Steps 3–4 may be drafted before the round but must not be finalized until the code is frozen, since they quote `drain_exit` values, the `saw_done` field, and the event field set.
- **What to sync:** the `#chat-sse` terminal-events bullet; the `#chat-sse-drain` closing paragraph and drain-event registration; the mapping table's scope; the `#malformed-args` error box's closing sentence; the `#degradation` event table row for `chat_sse_truncated`; one new row in `CLAUDE.md`'s "Moved out of this section" table (the existing 5 s drain row stays as it is); the `doc/trace-log.html` `#events` row for `chat_sse_truncated` plus the new `chat_sse_drain` row; the two migrated and four new per-test descriptions and the three count sites on the catalogue page; and the `Last updated` header and footer on all three edited pages (their staleness is not caught by the doc-structure checker, which verifies presence only).
- **Confidentiality:** `doc/` is published. The upstream-failure paragraph added in step 3 must stay provider- and project-agnostic — the supporting report is gitignored precisely because it names providers, models, request ids, absolute paths, and another project's transcript.
- **`README.md`:** <!-- UPDATED 2026-10-04 at commit time: the original decision below was reversed. It applied the test "did anything in README become false?" — under which it was correct, since README never stated what happens to a finish-less stream. But README's Limitations paragraph already walks the drain mechanics in detail, so it is the natural home for the disposition, and the change is user-visible (a cut stream now reaches the client as a retryable `api_error` where it previously arrived as a completed turn). "Not false" is not "does not need saying" for a user-facing doc. One clause was added to the Limitations paragraph, and this bullet is left below as the original reasoning rather than deleted. --> originally recorded as reviewed with no change needed, on the grounds that it documents user-facing setup, the provider-mode table, and environment variables, does not enumerate trace events (it links to `doc/trace-log.html`), and its chat-mode row describes the request/response transform. One clause was ultimately added — see the note above and the History row.
- **`doc/content.html`:** reviewed, no change needed — its overview counts and page descriptions (e.g. "trace-log.html — … every event name") remain accurate after this plan, since no page is added or retired. Recorded here so the omission reads as a decision rather than an oversight.

## History

| Date | Event | Conclusion | Dismissed |
|------|-------|------------|-----------|
| 2026-10-04 | Initial plan | Fix the truncation path to close with a retryable `api_error` event instead of a synthesized `end_turn`, and add a coalesced `chat_sse_drain` trace event so the post-finish drain is self-describing. **Deliberately reverses** the leave-as-is decision recorded by `2026-10-02-drain-after-finish-reason` ("Genuine truncations (connection drop without any finish_reason) are still handled by the existing EOF path"): the hang that decision guarded against is still guarded, but an SSE `error` event terminates the stream without asserting the turn completed. That plan's pinning test `test_chat_sse_truncation_still_works` is migrated rather than deleted | — |
| 2026-10-04 | Round 1 (coder) — no work, no report | The round launched at 11:11:10 and exited 0 at 11:12:12 having executed nothing: it completed `check-git-root`, repo-mode detection, `operate-plan` adoption, the artifact scan and the plan read, then emitted a 179-char adoption statement as a text-only message with `stop_reason: end_turn` and the session ended. `git status` clean, no `tmp/reports/` artifact written (though `operate-plan.md` requires a blocking report when a coder cannot execute a step). Ruled out by direct check, not assumption: the Stop hook (`sound-notify.py`, `preventedContinuation: False`, no errors — it fired *because* the session ended); a missing `## Immediate Actions` (`planner.md:283` — absent from initial plans by design); plan size (41.8k chars vs the 91.4k plan that ran fine on 2026-10-02); the mega-audit report sitting under the plan-id prefix (the 2026-10-02 round had the same and proceeded); and the launcher's 3600 s cap / stale lock (that is the separate `tester-round-killed-no-report` issue, killed mid-suite). Nothing in the plan blocked it — the worktree was clean and both step scripts pass their dry run | — |
| 2026-10-04 | Round 2 (coder) — partial, no report | Re-run launched 13:32:34, exited 0 at 13:38:38 with **three** Edits applied to `server.py` (11 insertions, 2 deletions): the method docstring, `saw_done = False`, and `saw_done = True` + `drain_exit = "done"`. All three are **inert** — `saw_done`/`drain_exit` are written and never read, the module compiles and imports, and runtime behavior is identical to HEAD. No session report again. Cause is now determined rather than inferred: every assistant message in the round carries `stop_reason: tool_use` **except the last**, which is `stop_reason: end_turn` with THINK + TEXT(57) and no tool call — the model ended the turn itself, on the sentence "Now splitting `terminal()` into shared helpers (step 1b):", rather than being truncated (`max_tokens`), hooked, or killed. Round 1 failed identically (text-only narration → `end_turn`). Both rounds therefore stop the same way: a narration preamble ending the turn in place of the tool call that should follow it. Response: `## Immediate Actions` added (the section a round reads first, per `operate-plan.md` Step 3), carrying the exact residual edit list and the explicit directive to emit each Edit in the same message as its text. Full step detail stays in Steps 1–2; this section is pointers only. Recorded here as a deliberate generation outside `/update-plan`, justified by the plan having already been revised in Phase 4.5 and by `planner.md:527`'s per-role, action-only shape | — |
| 2026-10-04 | Investigation: the rounds' early stop is the user's reported symptom, traced end to end | The user identified the two dead coder rounds as the same defect behind "repeat your proposed tool call". Traced the failing turn to its proxy request (916f7ce4, tier sonnet, opencode-go-chat / mimo-v2.6-flash, ended 05:38:37Z) and established the cause: the **upstream model ended its turn with `finish_reason: "stop"` after narrating the next action**, emitting no tool call at all. The proxy is exonerated by four independent facts — the finish reason mapped to `end_turn`, which the dispatch can only produce when no tool block was emitted *and* the reason was literally "stop" (a dropped tool call yields `null` or `tool_use`); no `chat_sse_tool_degradation` event fired, so no readable `tool_calls` field ever appeared; no `chat_sse_truncated` event fired, so a finish reason did arrive; and usage was real and non-zero (in 104,180 / out 391), so the trailing usage frame arrived and the stream was never cut. The model's own thinking was complete and explicitly intended to continue. This is the same pathology as the four longcat incidents, now on a second unrelated model, and it is reproducible on demand. Consequence for this plan: `chat_sse_drain.emitted_tool_use` was already planned, but alone it answers "did this turn call a tool", not "could it have" — so step 2 gains **(d) a `tools_declared` flag on the `request` trace entry**, which makes "tool-bearing chat turns that emitted no `tool_use`" a countable per-provider rate. That measurement is the only lever that exists here: the proxy cannot make a model call a tool, and the proven remedy is routing away from a noisy provider, as was done for longcat. An automatic proxy-side recovery was considered and rejected as a separate, opt-in design — it would need to buffer every chat-mode response before the first byte reaches the client, and classifying a completed turn as retryable needs a prose heuristic that would fire on legitimate answers. The `upstream-silent-tool-call-omission` report was updated with the second specimen, the four exonerating facts, and the honest residual limit (an upstream using the unread legacy `delta.function_call` field would also be invisible, though its finish reason argues against it). The step scripts and dry run were updated for (d) — the dry run now reads pristine `HEAD` rather than the working tree, so it stays valid however much of the plan a round has already applied | — |
| 2026-10-04 | User chose Option A (client retry) and asked for three additions; plan extended, the action staged | The user selected the error-event approach over a proxy-side re-issue and asked for (1) late-frame latency statistics so the 5 s drain budget can be judged from data, (2) a nudge appended to the retried upstream request so the re-roll is more likely to differ, and (3) trace coverage of the event and its retry count for regression study. All three are feasible; (1) and (3) are pure instrumentation and are now **in this plan** as step 2(e)–(g): late-frame offsets on `chat_sse_drain` (`late_frames`, `first_late_ms`, `last_late_ms`, `late_tool_call_ms` — the last being the arrival latency of a tool call that the drain would otherwise have lost), the unfinished-turn detector as a **log-only** event (`chat_sse_unfinished_turn`, structurally incapable of acting), and a report section in `scripts/analyze_proxy_trace.py`. Step 2(d) was rewritten: `tools_declared` must be threaded into the stream handler (both signatures plus both `forward_request` call sites), not merely computed in `do_POST`, because the detector evaluates it at the decision point. The **action itself is staged as a follow-on plan**, deliberately not in this one: (2) needs a short-TTL marker keyed on a hash of the client body to recognise the retry — the same state the loop guard needs, so one mechanism serves both — and it cannot be tuned until (1) and (3) have measured the detector's precision on real traffic and confirmed the one unvalidated assumption in the whole design (that the client actually re-issues on a mid-stream `api_error`). Its design is recorded in the `upstream-silent-tool-call-omission` report so nothing is lost: absent marker + unfinished turn → error the turn and record the hash; present marker → **pass through without erroring** (the loop guard) and inject a config-texted nudge into a copy of the client body before the chat transform, so the transform stays the single mapping authority. The nudge is proxy-authored content the remote sees and the transcript never records, which is why it must be logged (`chat_retry_nudge`, carrying `original_request_id`; plus `chat_retry_passthrough` when the retry also looks unfinished). Joining detection → nudge → the retry's own `chat_sse_drain.emitted_tool_use` yields the per-provider retry success rate. Both step scripts and the dry run were updated for the extended step 2 (11 event fields; 10 arms, all green) | — |
| 2026-10-04 | Spec revision (/update-plan) — round 3 coder report | Two **plan errors** of mine, both found by the round-3 coder before the code landed and both fixed in-round on the code side, leaving the plan text and my dry run to correct. (1) [tools-declared-scope-premise-wrong](./tmp/reports/2026-10-04-truncation-error-and-drain-trace-tools-declared-scope-premise-wrong.json): Step 2(d) placed the threaded names' origin at "both call sites in `forward_request`", but those call sites are in `_forward_core` while `body_json`/`key_name` are locals of `_forward_request_impl` — read literally, a `NameError` on every streamed 2xx response, i.e. a total outage of every streaming path, and the dry run encoded the identical defect so its "fixed" arm would have produced the same breakage. (2) [unfinished-turn-provider-key-threading](./tmp/reports/2026-10-04-truncation-error-and-drain-trace-unfinished-turn-provider-key-threading.json): 2(f)'s event field list requires `provider` and `key` while 2(d)'s threading spec supplied only `tools_declared`, so the plan was internally inconsistent and also silent on a codebase norm (`do_POST`'s "key is never threaded through forward_request's return tuple"). **Change, by section:** Step 2(d) rewritten — the derivation anchored in `_forward_request_impl`, `_forward_core` seen as the crossing point, all three names threaded as parameters (`tools_declared`, `provider`, `key`, plus `key_name` carried through the core), the return-tuple-note scoped explicitly to return values, and an HTML comment recording the correction and its evidence; Issue Log gained both rows. **Changed:** Step 2(d) only; no step, file, verification-script or override change, so `## Plan Metadata` is unaffected. **Verified, not assumed:** the landed code was read directly (derivation at `server.py:620`; `tools_declared=tools_declared, key_name=key_name` at both impl→core call sites, 757/768; `tools_declared=False, key_name=None` in `_forward_core`'s signature, 875; `tools_declared=tools_declared, provider=provider_name, key=key_name` at both core→stream call sites, 957/1050; all three parameters on `_stream_upstream_response`, 1348, and `_stream_chat_sse_to_anthropic`, 1527) and **both step scripts run against it: step 1 exit 0, step 2 exit 0**. **Dry run repaired and hardened:** `./tmp/verification/_dryrun-step1-step2.py` now encodes the corrected boundary — the two stale `do_POST`/`request`-event edits are gone, `_forward_core` gains both parameters and both impl→core call sites pass them, and the two core→stream call sites pass `provider`/`key` — and step 2 gained an AST name-resolution check, so this defect class is now caught by a gate rather than by review. A new `revert-core-param` arm restores the plan's original wording and fails step 2 with the `NameError` diagnostic (`_forward_core` reads `tools_declared` but never binds it); the dry run is green at 11 arms. The correction can therefore no longer be undone by a later round that follows the plan literally. No test report exists for this plan yet, so both issues stay `Fix Planned` — the tester's round is what resolves them. Round-3 coder report: [coder-2026-10-04](./tmp/reports/2026-10-04-truncation-error-and-drain-trace-coder-2026-10-04.json) — steps 1 and 2 complete, build pass, no tests touched. | — |
| 2026-10-04 | Mega-audit (iteration 1) — report: [2026-10-04-truncation-error-and-drain-trace-mega-audit-2026-10-04.json](./tmp/reports/2026-10-04-truncation-error-and-drain-trace-mega-audit-2026-10-04.json) | 41 findings (3 High / 21 Medium / 17 Low), verdict "plan needs revision". All 41 were dispositioned; 24 required plan changes and the rest were verified as already-resolved in the revision. Root causes, in order of consequence: (1) **`terminal()` has a second side effect** (defect-tracer, test-impact, oversight-catcher, edge-case-explorer — 5 findings, the 3 Highs among them): the unstarted-tool counting loop that feeds the degradation predicate lives inside `terminal()`, so removing `terminal()` from the truncation path silently stopped `chat_sse_tool_degradation` firing for a stream whose only defect is a tracked-but-unstarted tool call — contradicting the plan's own preservation claim. Fixed by folding the loop into `log_degradation_if_needed()`, which every terminal path now shares. (2) **`[DONE]`-without-`finish_reason` was conflated with a cut connection** (edge-case-explorer, conflict-resolver): erroring on both would have turned any provider that omits `finish_reason` but terminates properly into a retry storm, replacing a working integration with an outage. Fixed by tracking `saw_done` and splitting the disposition — which also shrank the test migration from four tests to five-examined/two-migrated, since the three `[DONE]`-bearing truncation-path fixtures now keep passing unchanged (including `test_chat_sse_pending_buffer_cap_exceeded`, a fifth such test the plan had missed entirely). (3) **A duplicate new test** (test-impact): the proposed `test_chat_sse_truncation_emits_error_event` exactly duplicated the migrated `test_chat_sse_truncation_still_works`; dropped, its assertions folded into that test. (4) **Doc-scope misattribution** (6 findings): the unconditional-synthesis claim lives in `#chat-sse`, not `#chat-sse-drain`; the `#degradation` event table row and the `#malformed-args` box also needed rescoping; and one override was factually wrong — the mapping table has no finish-less row at all. (5) **A false dismissal**: the plan's first draft dismissed all 17 Lows as acknowledged-without-change; on review 12 were real and are now fixed — `drain_ms` measured at emission instead of at the drain's end, an unbounded upstream-controlled `finish_reason` written verbatim into the trace, a missing Rollback section, a never-existing `CLAUDE.md` row named as an edit target, a `grep -c` evidence command that cannot yield a cross-file sum, the standalone/live-proxy run requirement from `#adding-tests`, a fifth truncation-path test, a provider-identifying doc paragraph in a published page, and the three edited pages' stale `Last updated`. Remaining after the revision: 0 High, 0 Medium, 0 Low outstanding — **0 of 41 findings open**. Both step verification scripts were rewritten, then self-tested by `_dryrun-step1-step2.py` across nine arms (unfixed / fixed / one reverted guard per script), which itself caught three latent script defects: a needle (`finish_reason == "tool_calls"`) that could never match the source's `finish_reason_seen == "tool_calls"`, the two response-cap exits having different indentation so a single edit covered only one, and a `time.time()` search wide enough to reject a correct implementation (the per-chunk drain budget legitimately calls it) | Dismissed: 5 of the 17 Low findings, each verified during the revision and left unchanged by decision — `chat_sse_truncated` keeps its name (its meaning is unchanged and `saw_done` now discriminates the dispositions); the `chat_sse_drain` volume cost is accepted and recorded as a Risks row; the script's `near()`-multi-occurrence weakness was fixed rather than dismissed, so the only script-shape Lows remaining concern wording; the inert-on-drain `response_cap` assignment is wired anyway (one line, and it keeps the every-exit invariant literally true, which is what makes it scriptable); and the `#chat-sse-drain` five-second-floor and `sock`-private-fallback residuals stay dispositioned by `2026-10-02-drain-after-finish-reason` |
| 2026-10-04 | Tester round — SUCCESS; all three in-scope issues resolved | Round 4 (tester) reported **SUCCESS**: 371 passed / 0 failed / 0 skipped in the full suite **with a live proxy running**, plus both plan verification scripts green (step 1 exit 0; step 2 exit 0, AST name-resolution check included). Seven permanent tests were created and five existing tests were revised exactly as guided (2 truncation migrations, 2 `drain_exit` folds, `ALL_TESTS` registration), and the three unchanged `[DONE]`-bearing truncation-path tests were confirmed passing unchanged — which is the evidence that the `saw_done` wiring discriminates correctly rather than merely not crashing. Three issues moved to **Resolved**: [tools-declared-scope-premise-wrong](./tmp/reports/2026-10-04-truncation-error-and-drain-trace-tools-declared-scope-premise-wrong.json), [unfinished-turn-provider-key-threading](./tmp/reports/2026-10-04-truncation-error-and-drain-trace-unfinished-turn-provider-key-threading.json), [truncation-masks-upstream-failure](./tmp/reports/2026-10-04-truncation-error-and-drain-trace-truncation-masks-upstream-failure.json). One guidance clause could not be implemented as written — a cut stream never reaches the drain, so it logs no `chat_sse_drain` and `drain_exit == "eof"` is unobservable on that fixture; the clause was self-contradictory (it also asked for the assertion that no such event exists) and the tester split it correctly, marked in place under Guidance for Tester rather than silently deviated from. Steps 3–5 remain planner-owned and are now unblocked, the code being frozen. Reports: [tester-2026-10-04](./tmp/reports/2026-10-04-truncation-error-and-drain-trace-tester-2026-10-04.json); suite log [./tmp/reports/_fullsuite-2026-10-04.log](./tmp/reports/_fullsuite-2026-10-04.log). | — |
| 2026-10-04 | Phase 6 review — no High findings; round 5 opened for the one Medium | The Phase 6 adversarial review ([review-2026-10-04](./tmp/reports/2026-10-04-truncation-error-and-drain-trace-review-2026-10-04.json)) returned **no High findings, 1 Medium, 4 Low**, and cleared the plan's own risk list: no path can emit zero terminators, none emits a terminal sequence twice, no degradation diagnostic is lost, `saw_done` discriminates correctly (the three unchanged `[DONE]` fixtures passing is the evidence), and no threaded name is read unbound. **Dispositions:** *(1, Medium)* the H1 fix — the unstarted-tool counting loop now in `log_degradation_if_needed()` — is pinned by **no committed test**; the only pin is the plan's own `step1.py`, which `git check-ignore` confirms is under the gitignored `tmp/`. Verified on the code side that the behaviour is correct (the helper carries the loop at `server.py:1862-1865`, and the cut path calls it at `:2222`), so this is coverage, not behaviour; the user authorized a round-5 tester test and its exact spec is recorded at the end of Guidance for Tester. *(3, Low)* `late_frames` counts drain reads, not frames, while the page published by step 4 said "frames" — **fixed in `doc/trace-log.html`**, since the counter matches the plan's own wording and the doc was the thing that was wrong. *(2, 4, 5)* deferred: [chat-sse-done-framing-assumption](./tmp/reports/defer-issue-chat-sse-done-framing-assumption.json), [chat-sse-late-frame-offsets-unasserted](./tmp/reports/defer-issue-chat-sse-late-frame-offsets-unasserted.json), [unfinished-turn-detector-ignores-degraded-tool](./tmp/reports/defer-issue-unfinished-turn-detector-ignores-degraded-tool.json) — the last folded into the follow-on Option A plan, because a predicate that counts proxy-side degradations as model omissions inflates the very rate the shadow measurement exists to establish. Independent full-suite re-run against the frozen tree with a live proxy running: **371 passed / 0 failed / 371 total**, one known warning. | — |
| 2026-10-04 | Round 5 (tester) — the Phase 6 Medium closed; plan finalized | Round 5 landed exactly one test and nothing else: `test_chat_sse_tool_degradation_on_cut_stream`, registered as `chat-sse-tool-degradation-on-cut-stream`, built from `test_chat_sse_tool_call_eof_without_finish` case (c)'s fixture with `add_done=False`, asserting in the plan's order — exactly one `chat_sse_tool_degradation` (the H1 pin), no block started, an `api_error` frame with no terminal sequence, and `saw_done: 0`. The unstarted-tool counting loop's relocation into `log_degradation_if_needed()` is now pinned by a **committed** test rather than only by the gitignored `step1.py`. Round result: **372 passed / 0 failed / 0 skipped** with a live proxy running, the new test also green standalone, both plan scripts still exit 0, no doc edits (the tester honoured the planner-owned catalogue boundary), no issues filed. The planner then recounted `doc/test-catalog.html` against the landed suite — 372 total and 55 for `test_chat_sse.py`, in both the table and the section heading, plus the new entry — and verified the table sums to the declared total with no per-file row disagreeing. `## Final Results` written; two rounds of tester evidence plus an independent planner re-run are the test record. Report: [tester-2026-10-04-2](./tmp/reports/2026-10-04-truncation-error-and-drain-trace-tester-2026-10-04-2.json); suite log [./tmp/reports/_fullsuite-round5-2026-10-04.log](./tmp/reports/_fullsuite-round5-2026-10-04.log). | — |
| 2026-10-04 | Commit-time amendment — README reversed from "no change needed" | At the `/update-and-commit` gate the user challenged the plan's recorded decision to leave `README.md` alone, and the challenge was upheld. The original call was correct under the test it applied — nothing in README had become *false* — but wrong for a user-facing doc, because README's Limitations paragraph already walks the drain mechanics and the change is user-visible: a cut stream now reaches the client as a retryable `api_error` where it previously arrived as a completed turn. **Change:** one clause added to the chat-mode Limitations paragraph; the superseded reasoning is retained in Guidance for Planner behind an HTML comment rather than deleted, and `## Final Results` gained a README row. No code, test, or gate was touched, so no verification re-run was needed beyond `tests/test_docs.py` (11/11, unaffected by a README edit). This row also records that the plan file was re-archived to `./plans/` after the amendment so the published copy and the working copy agree. | — |

## Plan Metadata

```json
{
  "plan_id": "2026-10-04-truncation-error-and-drain-trace",
  "steps": [
    "Step 1: In `_stream_chat_sse_to_anthropic` (`src/claude_retry_proxy/server.py`), split the end-of-stream disposition on whether `[DONE]` was received, close blocks and finalize diagnostics on the cut path, and refactor `terminal()`'s two side effects into shared helpers",
    "Step 2: Make the post-finish drain self-describing — record why the read loop exited and when trailing frames arrived, emit one coalesced `chat_sse_drain` trace event per drained stream, record whether the request declared tools, detect the unfinished turn in shadow mode, and teach the trace analyzer to report all of it",
    "Step 3: Update `doc/provider-modes.html` — the `#chat-sse` terminal-events bullet, the `#chat-sse-drain` closing paragraph, the `finish_reason` → `stop_reason` mapping table's scope, the `#malformed-args` error box, and the `#degradation` event table row — plus one new row in `CLAUDE.md`'s \"Moved out of this section\" table",
    "Step 4: Update `doc/trace-log.html` — the event inventory",
    "Step 5: Reconcile `doc/test-catalog.html` against the final landed suite"
  ],
  "coder_files": ["src/claude_retry_proxy/server.py", "scripts/analyze_proxy_trace.py"],
  "tester_files": ["tests/test_chat_sse.py"],
  "doc_files": ["doc/provider-modes.html", "doc/trace-log.html", "doc/test-catalog.html", "CLAUDE.md"],
  "verification_scripts": [
    "./tmp/verification/2026-10-04-truncation-error-and-drain-trace-step1.py",
    "./tmp/verification/2026-10-04-truncation-error-and-drain-trace-step2.py",
    "./tmp/verification/_dryrun-step1-step2.py"
  ],
  "repo_mode": "Public",
  "document_overrides": [
    "doc/provider-modes.html: the #chat-sse bullet states terminal events are synthesised at EOF or on truncation and that the synthesis is unconditional (Reason: a cut stream now closes with an SSE error event; only a [DONE]-terminated stream is synthesised)",
    "doc/provider-modes.html: the #chat-sse-drain closing paragraph says a never-finished stream is unaffected and still takes the EOF path (Reason: it now closes with an error event when [DONE] never arrived)",
    "doc/provider-modes.html: the finish_reason -> stop_reason mapping table presents end_turn as the outcome for a stream that ended without a finish reason (Reason: no message_delta is emitted on a cut stream, so no stop reason is reported)",
    "doc/provider-modes.html: the #malformed-args error box states a stream ending without a finish_reason reports null when tool-call deltas were seen (Reason: that discriminator survives only when [DONE] was received)",
    "doc/trace-log.html: the event inventory describes chat_sse_truncated as a routine terminal event (Reason: it is now the no-finish_reason diagnostic, discriminated by saw_done, and chat_sse_drain must be registered)"
  ]
}
```

## Audit Accumulation

*Counters reset when mega-audit runs. Used by Phase 5 entry trigger.*

| Counter | Value | Last Updated |
|---------|-------|--------------|
| issues_resolved_since_audit | 3 | 2026-10-04 |
| steps_changed_since_audit | 1 | 2026-10-04 |
| files_changed_since_audit | 0 | 2026-10-04 |

## Documentation

The `doc/` tree is the deep reference and is indexed by `doc/content.html`. This plan updates three of its pages plus one `CLAUDE.md` row (steps 3–5, planner-owned). The investigation that produced it is recorded in two issue reports under `./tmp/reports/`: `2026-10-04-truncation-error-and-drain-trace-truncation-masks-upstream-failure.json` (the fixable defect, with the trace and transcript evidence) and `2026-10-04-truncation-error-and-drain-trace-upstream-silent-tool-call-omission.json` (the upstream behavior, won't-fix, with the inference and its stated limits). The pre-implementation mega-audit is at `./tmp/reports/2026-10-04-truncation-error-and-drain-trace-mega-audit-2026-10-04.json`.

## Final Results

**Status: COMPLETED** — 2026-10-04.

### What shipped

A chat-mode SSE stream that ends with no `finish_reason` is no longer closed silently. It is now
dispositioned on a new `saw_done` flag: with `[DONE]` the stream is protocol-complete and closed
with a synthesised terminal sequence (unchanged), and without it the connection was cut
mid-response, so open blocks are closed, the degradation diagnostics are finalised, and the stream
is closed by an SSE `error` frame (`error.type: "api_error"`, retryable) with no `message_delta`
and no `message_stop` — so the client re-issues instead of recording a truncated turn as a
finished one. Alongside it, every stream that did reach a `finish_reason` now logs one
`chat_sse_drain` event with 11 fields (six `drain_exit` values, the drain's byte/time cost, three
tool-call flags, four late-frame offsets), and a log-only `chat_sse_unfinished_turn` detector
measures — without acting on — the upstream pathology that started the investigation.

### Files changed

| File | What |
|---|---|
| `src/claude_retry_proxy/server.py` | the `saw_done` split, `close_all_blocks()`/`log_degradation_if_needed()` helpers, all six `drain_exit` assignments with `socket.timeout` ordered ahead of the `OSError` tuple, the `chat_sse_drain` event, late-frame accounting, the shadow detector, and `tools_declared`/`provider`/`key` threaded through `_forward_core` |
| `scripts/analyze_proxy_trace.py` | reports the new event and numbers |
| `tests/test_chat_sse.py` | 8 permanent tests added, 5 revised (2 truncation migrations, 2 `drain_exit` folds, `ALL_TESTS` registration), 3 `[DONE]`-bearing truncation tests confirmed unchanged |
| `doc/provider-modes.html` | both dispositions, the `saw_done` discriminator, the `chat_sse_drain` registration, the scoped mapping table and error box, a `#degradation` row for `chat_sse_truncated`, and a provider-agnostic subsection on the upstream failure mode |
| `doc/trace-log.html` | `chat_sse_drain` and `chat_sse_unfinished_turn` registered, the `chat_sse_truncated` row rewritten, the exhaustiveness rule and the `tools_declared` + `emitted_tool_use` join |
| `doc/test-catalog.html` | recounted to 372 / 55, 2 migrated descriptions marked, 8 new entries |
| `CLAUDE.md` | one row in "Moved out of this section", plus the deferred-issue index rebound to 13 entries (+3) and the matching count/provenance prose |
| `README.md` | one clause in the chat-mode Limitations paragraph: a finish-less stream is closed with a synthesised ending when `[DONE]` arrived and with a retryable `api_error` when the connection was cut first — added at commit time, reversing the plan's original "no change needed" call (see Guidance for Planner) |

### Test evidence

- **Round 4 (tester):** 371 passed / 0 failed / 0 skipped, full suite **with a live proxy running**; both plan verification scripts exit 0.
- **Round 5 (tester):** 372 passed / 0 failed / 0 skipped, live proxy running; the round-5 test passes standalone (`-t chat-sse-tool-degradation-on-cut-stream`) as well as in the suite; both plan scripts exit 0 against the frozen tree.
- **Independent planner re-run** against the frozen tree, live proxy running: 372 passed / 0 failed.
- **Doc gates:** `doc_structure_check.py` PASS (9 files); `tests/test_docs.py` 11/11.
- One known warning in every run: `No proxy_stop event in trace` ([defer-issue-no-proxy-stop-trace-warning](./tmp/reports/defer-issue-no-proxy-stop-trace-warning.json)).
- **Verification apparatus:** `./tmp/verification/2026-10-04-truncation-error-and-drain-trace-step1.py` and `-step2.py`, with `./tmp/verification/_dryrun-step1-step2.py` proving each guard load-bearing across 11 arms (including `revert-core-param`, which reinstates the plan's original threading wording and must fail).

### Issues resolved

| Issue | Resolved by |
|---|---|
| [tools-declared-scope-premise-wrong](./tmp/reports/2026-10-04-truncation-error-and-drain-trace-tools-declared-scope-premise-wrong.json) | tester, 2026-10-04 |
| [unfinished-turn-provider-key-threading](./tmp/reports/2026-10-04-truncation-error-and-drain-trace-unfinished-turn-provider-key-threading.json) | tester, 2026-10-04 |
| [truncation-masks-upstream-failure](./tmp/reports/2026-10-04-truncation-error-and-drain-trace-truncation-masks-upstream-failure.json) | tester, 2026-10-04 |

### Deferred issues

Each is a completed disposition and appears in `CLAUDE.md`'s deferred list; none blocks this plan.

- **[chat-sse-done-framing-assumption](./tmp/reports/defer-issue-chat-sse-done-framing-assumption.json)** — a `data: [DONE]` with no trailing blank line is never assembled, so `saw_done` stays 0 and a protocol-complete stream is errored. The framing rule predates this plan; what is new is that its consequence changed from "synthesised anyway" to "errored and retried". No occurrence is known — the failure is inferred from the parser, not observed.
- **[chat-sse-late-frame-offsets-unasserted](./tmp/reports/defer-issue-chat-sse-late-frame-offsets-unasserted.json)** — `first_late_ms`/`last_late_ms` are structurally gated but never asserted behaviorally, so dropping the `frames_seen > _frames_before` guard would report a late frame for a stream that had none, and no committed test would fail.
- **[unfinished-turn-detector-ignores-degraded-tool](./tmp/reports/defer-issue-unfinished-turn-detector-ignores-degraded-tool.json)** — the detector's predicate omits `not tool_calls_seen`, so a tool call the proxy could not start a block for is counted as a model omission. The event carries `tool_calls_seen`, so it is filterable. **Assigned to the follow-on plan**, because a predicate that conflates the two causes inflates the very rate the shadow measurement exists to establish.

### Won't fix

- **[upstream-silent-tool-call-omission](./tmp/reports/2026-10-04-truncation-error-and-drain-trace-upstream-silent-tool-call-omission.json)** — a model ends an agentic turn with prose plus `finish_reason: "stop"` and emits no tool call at all. Out of the proxy's reach: it cannot invent a tool call the model never emitted. This plan exists to make it measurable (that is what `chat_sse_drain.emitted_tool_use` joined to `tools_declared`, and the `chat_sse_unfinished_turn` detector, are for); the remedy is routing rather than repair. The report carries the full design of the staged follow-on Option A plan — error event plus body-hash loop guard, an injected nudge before the chat transform, and `chat_retry_nudge`/`chat_retry_passthrough` events — to be written once this plan's shadow data exists.

### Phase 6 review

[review-2026-10-04](./tmp/reports/2026-10-04-truncation-error-and-drain-trace-review-2026-10-04.json) — no High findings, 1 Medium and 4 Low. The Medium is closed by the round-5 test above; one Low was fixed in the docs; three are deferred above, with the plan's dispositions recorded in the History table.