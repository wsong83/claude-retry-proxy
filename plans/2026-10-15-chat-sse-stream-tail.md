# Plan: Honour a `[DONE]` stranded at EOF, and pin the drain's late-frame offsets
**Project:** D:\proj\claude-retry-proxy
**Plan ID:** 2026-10-15-chat-sse-stream-tail
**Created:** 2026-10-15

## Immediate Actions

<!-- REWRITTEN 2026-10-16. The previous version targeted the tester and
     described Steps 1–2, which are DONE and verified. Leaving it in place
     would have sent the next round to redo finished work. -->

**Steps 1–2 are complete and verified — do not redo them.** Two rounds remain,
both added 2026-10-16 by the Phase 6 review. Full detail in Steps 3 and 4 below;
this is the short form.

**Coder — `src/claude_retry_proxy/server.py` only, Step 3, then run
`python ./tmp/verification/2026-10-15-chat-sse-stream-tail-step3.py` (exit 0
required) and write your report.**

1. **ADD** the swap-epoch checkpoint to the two unguarded exits of the read loop
   in `_stream_chat_sse_to_anthropic`: the
   `except (IncompleteRead, RemoteDisconnected, socket.error, OSError)` handler
   and the `if not chunk:` block. Both need
   `if _swap_epoch_changed(epoch): return evict_swap()` **before** their
   `drain_exit = ...` assignment, using the epoch test alone — **not**
   `_config_swapping` — matching the data path at `server.py:2857`.
2. **REPLACE** the two copies of the sentinel parse with a single nested
   `sentinel_of(text)` helper defined above `handle_frame`; both
   `handle_frame` (`server.py:2711-2716`) and the flush (`server.py:3075-3080`)
   call it. Pure refactor — `handle_frame`'s observable behaviour must not
   change.

**Tester — `tests/test_chat_sse.py` only, Step 4, then the full suite in the
foreground and your report.**

3. **COPY THREE TEST FUNCTIONS AND THREE REGISTRATIONS VERBATIM FROM STEP 4.**
   They are complete code in that section — not a description. Paste them in
   after `test_chat_sse_swap_evicts_pre_finish` (ends at `tests/test_chat_sse.py:4465`)
   and register them beside its entry at `:4768`. **Do not re-derive them from
   the harness and do not read the probes for guidance** — six rounds failed on
   this step by doing exactly that and running out of turn before writing
   anything. The assertions are already measured against the current tree, and
   the expected values are tabulated in Step 4.
4. **RUN** `python tests/test_chat_sse.py` (expect 73 passed), then the **full
   suite in the foreground** (expect 424 passed), then write your session
   report. If a new test fails, report the failure rather than editing the
   assertion to match observed output — the expected values are ground truth
   from a post-fix measurement, so a mismatch means something real.

**Both rounds: write your session report before you end your turn.** Round
reliability is this plan's weak point — five tester attempts and one reviewer
round have already been lost to stalls mid-cycle. If you are reading this after
a relaunch, go straight to your numbered edit rather than re-deriving anything.

## Issue Log

| Issue | Status | Found | Resolved | Resolved By |
|-------|--------|-------|----------|-------------|
| [review-f4-eviction-never-flushes-unpinned](./tmp/reports/2026-10-15-chat-sse-stream-tail-review-2026-10-16.json) | Resolved | 2026-10-16 | 2026-10-16 | tester — `chat-sse-eviction-stranded-sentinel-never-flushes` PASSED, asserting `saw_done == 0` **jointly with** `pending_bytes == 13` so the pair, not the bare zero, is the evidence the flush was skipped. Module 73/73; planner re-ran the full suite 424/0 |
| [review-f3-duplicate-sentinel-parse](./tmp/reports/2026-10-15-chat-sse-stream-tail-review-2026-10-16.json) | Resolved | 2026-10-16 | 2026-10-16 | coder — the two copies are now one nested `sentinel_of(text)` above `handle_frame`, called from both it and the flush. Verified a pure refactor: `None` iff no `data:` lines, identical joined-stripped string otherwise, including the empty-`data:`-line case that still reaches `json.loads`; module 71/71 unchanged at the time of the change |
| [review-f2-flush-prose-missing-from-sse-section](./tmp/reports/2026-10-15-chat-sse-stream-tail-review-2026-10-16.json) | Resolved | 2026-10-16 | 2026-10-16 | planner — added the stranded-sentinel paragraph to `provider-modes.html`'s `saw_done: 1` bullet, so the event-table row's link now lands on prose that actually describes the flush |
| [review-f1-swap-epoch-checkpoint-gap](./tmp/reports/2026-10-15-chat-sse-stream-tail-review-2026-10-16.json) | Resolved | 2026-10-16 | 2026-10-16 | coder — `_swap_epoch_changed(epoch) -> return evict_swap()` added before the `drain_exit` assignment on both the `read_error` and `eof` exits, using the epoch test alone to match the data path. Confirmed behaviourally by the review's own probes, whose expectations the fix **inverted**: `probe_stranded_swap_straggler` went from `message_stop=True / saw_done=1 / swap_abort=0` to `message_stop=False / saw_done=0 / swap_abort=1` (4 checks now fail because they assert the old defect); the eviction probe still passes 7/7, so the eviction path was not disturbed. Regression test `chat-sse-post-swap-straggler-dies-retryably` covers both sentinel shapes |
| [chat-sse-done-framing-assumption](./tmp/reports/defer-issue-chat-sse-done-framing-assumption.json) | Resolved | 2026-10-04 | 2026-10-15 | tester — `chat-sse-done-without-trailing-blank-line` PASSED and measured load-bearing (it FAILS against `server.py` at `HEAD` in the shadow-tree calibration); `chat-sse-partial-frame-at-eof-is-not-flushed` PASSED as the negative control. Full suite 422/0 |
| [chat-sse-late-frame-offsets-unasserted](./tmp/reports/defer-issue-chat-sse-late-frame-offsets-unasserted.json) | Resolved | 2026-10-04 | 2026-10-15 | tester — both drain fixtures extended and PASSED by name (`chat-sse-drain-event-on-done` both-null; `chat-sse-drain-late-tool-call-time-budget` sandwich). These are the first assertions anywhere in `tests/` on either field; planner re-verified 71/71 in the module |

## Guidance for Coder

**Files to modify:** `src/claude_retry_proxy/server.py`

**Round completion — read this before you start.** Seven rounds in this cycle
ended their turn while a `run_in_background=True` full-suite run was still in
flight. The launcher then killed the run, so the round left no session report
and its work had to be re-verified by hand. Do not repeat it: run the suite in
the **foreground**, or if you background it, **wait for it to exit** before you
end your turn. Write your session report before you stop, whatever the result —
a round that reports nothing is treated as a failed round even when its code
landed.

Three changes now — Step 1 (the flush) already landed; Step 3 was added by the
Phase 6 review. **Do not** touch the `\n\n` framing rule itself, the drain
budget, or the finish_reason handling — all of those are load-bearing and
unchanged. Step 3b does touch `handle_frame`, but only to lift its sentinel
parse into a shared helper: its observable behaviour must not change.

### Step 1: flush a stranded `[DONE]` sentinel at EOF

The frame loop assembles a frame only once `buf.find(SSE_EVENT_DELIMITER)`
(the `b"\n\n"` delimiter) succeeds. A provider that writes `data: [DONE]\n` and
then closes leaves the sentinel sitting unparsed at EOF: `handle_frame` never
sees it, `saw_done` stays `False`, and the stream takes the cut-stream branch —
closed with a retryable `api_error` instead of a synthesised terminal. A
protocol-complete stream is therefore errored and the client re-issues a request
that already succeeded.

Insert a flush **immediately before** the `if not message_started:` /
`start_message()` pair at `src/claude_retry_proxy/server.py:3071-3072` — i.e.
after the frame-assembly `while` loop ends (line 2925) and before the
`chat_sse_truncated` `log_trace` at line 3073. At that point `buf` holds at most
the single frame that arrived without its terminating delimiter.

The anchor is a **two-line** statement. This plan's first draft quoted it as
`if not message_started: start_message()` on one line, which does **not** appear
verbatim in the file — so land it with
`grep -n "if not message_started" src/claude_retry_proxy/server.py` and use the
`3071` hit, not a string search for the joined form. The surrounding lines are
the `# EOF reached without a finish_reason chunk` comment above and the
`log_trace({` below; both are unchanged and unambiguous.

```python
        # A provider may write `data: [DONE]` and close without the blank
        # line that delimits a frame, stranding the sentinel in the buffer.
        # At EOF the sentinel is unambiguous, so honour it rather than
        # treating a protocol-complete stream as one that was cut.
        if not saw_done and buf is not None:
            _stranded = bytes(buf).decode("utf-8", errors="replace")
            _stranded_data = [ln[5:].strip() for ln in _stranded.splitlines()
                              if ln.startswith("data:")]
            if _stranded_data and "\n".join(_stranded_data).strip() == "[DONE]":
                saw_done = True
```

Contract points the gate pins:
- `buf is not None` is required: `buf is None` is the degraded raw-passthrough
  mode, where no frame parsing happens at all.
- The parse **mirrors `handle_frame`'s own** (`ln[5:].strip()` for a `data:`
  prefix, `"\n".join(...).strip()`), so the two paths cannot disagree about what
  the sentinel means.
- Only the exact sentinel is honoured. A residual that is a *partial JSON
  payload* (`data: {"cho`) or a complete-but-undelimited data frame
  (`data: {"a":1}\n`) is deliberately left alone — those stay in today's
  silently-discarded path, and flushing them would emit new
  `chat_sse_malformed_json` trace events on genuinely truncated streams,
  changing a measurement the drain plans just established.
- `saw_done = True` is all that is needed: the existing branch immediately below
  already synthesises the terminal sequence for a done stream.

→ coder verify (auto): read the inserted block — it sits after the frame loop
  and before the `chat_sse_truncated` log; it guards on `buf is not None`; its
  sentinel parse matches `handle_frame`'s `data:`/join form; no other line in
  the post-loop region changed
→ coder verify (scripted): `python ./tmp/verification/2026-10-15-chat-sse-stream-tail-step1.py`
  (exit 0 required)
→ tester verify: `test_chat_sse_done_without_trailing_blank_line` passes — the
  client receives a synthesised terminal (`message_delta` + `message_stop`), no
  `error` frame, and the trace logs `chat_sse_truncated` with `saw_done: 1`; the
  two existing truncated-stream fixtures are unchanged

### Step 3: checkpoint the swap epoch on the two unguarded exits, and share the sentinel parse

<!-- UPDATED: added by the Phase 6 review, 2026-10-16 — findings 1 (Warning)
     and 3 (Suggestion). See ./tmp/reports/2026-10-15-chat-sse-stream-tail-review-2026-10-16.json -->

Two changes in `server.py`.

**3a — the epoch checkpoint (finding 1).** The read loop checks
`_swap_epoch_changed(epoch)` on three of its five exits but not the other two:

| Exit | Line | Checkpoint |
|---|---|---|
| `socket.timeout`, in drain | :2838 | `_swap_epoch_changed(epoch)` → `evict_swap()` |
| `socket.timeout`, pre-finish | :2846 | `_config_swapping or _swap_epoch_changed(epoch)` → `evict_swap()` |
| **`read_error`** — `IncompleteRead` / `RemoteDisconnected` / `socket.error` / `OSError` | **:2849-2852** | **none — falls straight to `drain_exit = "read_error"; break`** |
| **`eof`** — `not chunk` | **:2853-2855** | **none — falls straight to `drain_exit = "eof"; break`** |
| data path, after `_touch_upstream_activity()` | :2857 | `_swap_epoch_changed(epoch)` → `evict_swap()` |

A pre-finish straggler that survives a completed swap and *then* hits EOF or a
read error skips the checkpoint, falls through to the EOF disposition, and — if
it holds a sentinel — is closed with a **synthesised terminal on old routing
after the swap completed**, with no `swap_abort` and no eviction. That
contradicts the documented invariant ("old-epoch stragglers die retryably at
their next checkpoint, so no old-routing result is delivered after a swap" —
`doc/architecture.html#config-swap`, restated in `CLAUDE.md`). Measured
end-to-end by the review: switch returned 200 at +4.8 s, the client received
`message_delta` + `message_stop` at +8.8 s, `swap_abort` count 0.

Add the same `_swap_epoch_changed(epoch)` test the data path uses at :2857 to
both exits:

```python
                except (http.client.IncompleteRead, http.client.RemoteDisconnected,
                        socket.error, OSError):
                    # A completed swap owns this exit too: dying retryably beats
                    # delivering an old-routing result the client would trust.
                    if _swap_epoch_changed(epoch):
                        return evict_swap()
                    drain_exit = "read_error"
                    break
                if not chunk:
                    if _swap_epoch_changed(epoch):
                        return evict_swap()
                    drain_exit = "eof"
                    break
```

Use **`_swap_epoch_changed(epoch)`, not `_config_swapping`.** The invariant is
about *old routing*, and routing is stale only once the epoch has actually
bumped; a swap merely in progress has re-routed nothing, and the swap owner is
already awaiting the drain. The data path at :2857 — the closest analogue, a
read completing — uses the epoch test alone. Match it.

**Pre-existing, but not thereby out of scope.** The framed-`[DONE]` control
reproduces the same post-swap terminal at `HEAD`, so the *checkpoint gap*
predates this plan. What this plan changed is the gap's reachable input set: at
`HEAD` a *stranded* sentinel left `saw_done` at 0 and took the cut disposition —
the **correct** post-swap outcome — and the flush now routes that same input to
`saw_done: 1` and a terminal. For that one input shape the plan turned a correct
outcome into an incorrect one, which is why the fix belongs here rather than in
a deferral.

**3b — share the sentinel parse (finding 3).** :3075-3080 re-implements
`handle_frame`'s sentinel parse (:2711-2716). The review measured 0 divergences
over 24 inputs today, but two copies can drift. Extract the shared part once,
above `handle_frame`, and call it from both:

```python
        def sentinel_of(text):
            """The frame payload as handle_frame reads it — every `data:` line,
            joined and stripped — or None when the frame carries none at all."""
            data_lines = [ln[5:].strip() for ln in text.splitlines()
                          if ln.startswith("data:")]
            if not data_lines:
                return None
            return "\n".join(data_lines).strip()
```

- `handle_frame` becomes `raw = sentinel_of(text)`, then
  `if raw is None: return None  # comment/event-only frame — skip silently`,
  followed by the existing `if raw == "[DONE]": return "done"` and the
  `json.loads(raw)` that follows.
- the flush becomes
  `if sentinel_of(bytes(buf).decode("utf-8", errors="replace")) == "[DONE]": saw_done = True`.

This is a **pure refactor of the parse**. `handle_frame`'s observable behaviour
must not change — the `None` return for a data-less frame, the `"done"` return
for the sentinel, and the `json.loads(raw)` that follows all stay identical.

→ coder verify (auto): both unguarded exits carry
  `if _swap_epoch_changed(epoch): return evict_swap()` immediately before their
  `drain_exit = ...` assignment; `_config_swapping` appears in neither; exactly
  one `data:`-collecting comprehension remains in the streaming function, inside
  `sentinel_of`, and both former sites call it
→ coder verify (scripted): `python ./tmp/verification/2026-10-15-chat-sse-stream-tail-step3.py`
  (exit 0 required)
→ tester verify: the module's existing SSE tests pass **unchanged**, and the new
  eviction pin in Step 4 passes

## Guidance for Tester

**Files to modify:** `tests/test_chat_sse.py` only. Do not touch
`src/claude_retry_proxy/server.py` (Step 1 already landed and is verified) and do
not touch `doc/**` — documentation is planner-owned and handled separately.

**Round completion — read this before you start.** Seven earlier rounds in this
cycle ended their turn while a `run_in_background=True` full-suite run was still
in flight; the launcher killed the run and the round left no session report, so
its work had to be verified by hand. You are the round most exposed to this,
because the suite is yours to run. Run it in the **foreground**, or if you
background it, **wait for it to exit** before you end your turn. Write your
session report before you stop, whatever the result.

**Also: bound every command.** The previous tester round spent 18 minutes on
reconnaissance, issued two inspection commands, produced no further output for
two hours, and was killed by the watchdog with nothing written. If a command can
touch a socket, spawn a proxy, or run a test, give it an explicit `timeout`. Do
not sit on a command that has gone quiet.

### Reconnaissance is already done — do not repeat it

The previous round's 18 minutes were spent locating helpers that are listed
here. Everything below is verified against the current tree.

**The helpers live in `tests/_harness.py`, not in `test_chat_sse.py`:**

| Helper | Location |
|---|---|
| `_start_mode_proxy(tiers, vendors, responders=None, extra_env=None, extra_headers=None, streamers=None)` | `_harness.py:1158` |
| `_mode_tiers(provider="p", model="claude-sonnet-5")` | `_harness.py:1088` |
| `_sse_stream_chunks(chunks)` → `"".join("data: {}\n\n"...)` | `_harness.py:1444` |
| `_cc(delta, finish=None)` | `_harness.py:1450` |
| `_start_chat_sse_proxy(chunks, add_done=True)` | `_harness.py:1524` |

**Do not use `_start_chat_sse_proxy` for the new test.** It appends
`b"data: [DONE]\n\n"` — always *with* the blank line — so it cannot express the
input under test. Build the responder directly; that is the dominant idiom in
this file (11+ tests do it).

**The sentinel test's body is `test_chat_sse_basic_streaming`
(`test_chat_sse.py:218`) with one character changed.** Its line 237 reads:

```python
    sse_body = _sse_stream_chunks(chunks) + b"data: [DONE]\n\n"
```

Yours is the same line with the trailing blank line removed:

```python
    sse_body = _sse_stream_chunks(chunks) + b"data: [DONE]\n"
    responders = {"p": lambda info: (200, "text/event-stream", sse_body)}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(
        tiers, vendors, responders=responders)
```

with `upstream_port`/`tiers`/`vendors`/`chunks` set up exactly as that test does
(it declares `chunks` inline with the `_cc`-style dicts; `_cc(delta, finish=...)`
is the terse form and is what `test_chat_sse_drain_event_on_done` uses).

**The negative control's body** is the same construction ending in a partial
payload with no delimiter:

```python
    sse_body = _sse_stream_chunks(chunks) + b'data: {"cho'
```

**Where the outcome is asserted.** `chat_sse_truncated` is emitted at
`server.py:3085` and carries `pending_bytes` and `saw_done`. Read it with the
same-file `_trace_events_named(trace_file, "chat_sse_truncated")`
(`test_chat_sse.py:173`). **The late-frame offsets are NOT on this event** — see
the correction in the Summary; they are on `chat_sse_drain`, which is what the
two Step-2 fixtures already read.

### Step 2's helper is in a DIFFERENT file — do not grep `_harness.py` for it

The helper inventory above is Step 1's, and **all of it lives in
`tests/_harness.py`**. Step 2 is the opposite: its helper is defined inside
`tests/test_chat_sse.py` itself, which is where a search for it must look.

| Helper | Location |
|---|---|
| `_start_hanging_chat_proxy(pre_body, hold_s, post_body=None, gap_s=0.0)` | **`tests/test_chat_sse.py:59`** |
| `_read_sse_until_stop(port, timeout)` | `tests/test_chat_sse.py` (used by the late-tool-call fixture) |
| `_wait_for_trace_events(trace_file, name)` | `tests/test_chat_sse.py` (used by the late-tool-call fixture) |
| `_trace_events_named(trace_file, name)` | `tests/test_chat_sse.py:173` |

`_start_hanging_chat_proxy` exists precisely because the harness responder
always sets `Content-Length` and closes, so the proxy's read loop sees EOF
immediately and the stall/drain path is never reached — it streams `pre_body`
over an unterminated HTTP/1.0 response and holds the socket. The two Step-2
fixtures already call it; both already obtain the `chat_sse_drain` event as
`ev = events[0]`, so **the only work is adding assertions on `ev`**.

**Both fixtures already assert the surrounding facts**, so add the new
assertions alongside the existing ones rather than restructuring:
- late-tool-call (`:3548`): it already checks `late_tool_call_ms` is non-`None`
  and non-negative; add the sandwich
  `first_late_ms <= late_tool_call_ms <= last_late_ms` (guard the comparison on
  all three being non-`None` first — comparing against `None` raises on
  Python 3).
- drain-on-done (`:2506`): add the both-`null` check; see the chunking
  explanation in "Tests to modify" above for why it holds.

**Tests to create:**
- **Permanent:** `test_chat_sse_done_without_trailing_blank_line` — in
  `tests/test_chat_sse.py`. The mock upstream writes one content chunk with
  **no finish frame**, then `data: [DONE]\n` **with no trailing blank line**,
  then closes. Assert the client sees a normal terminal sequence (not an SSE
  `error` frame) and that the trace event `chat_sse_truncated` carries
  `saw_done: 1`.

  <!-- CORRECTED 2026-10-15. This bullet previously read "then a finish frame,
       then `data: [DONE]\n`", which is self-contradictory: with a finish frame
       the stream takes the drain disposition and `chat_sse_truncated` is never
       emitted (see the annotation in Immediate Actions for the line numbers).
       The finish frame must NOT be present. The `[DONE]` sentinel is what
       completes the stream in its absence. -->
- **Permanent:** `test_chat_sse_partial_frame_at_eof_is_not_flushed` — the
  negative control for the narrow contract: the upstream closes after
  `data: {"cho` (a truncated payload, no delimiter). Assert `saw_done: 0` and
  the retryable `error` frame, so the flush is proven not to over-reach into
  partial payloads.

**Tests to modify (both fixtures already exist and already read the event):**
- `test_chat_sse_drain_late_tool_call_time_budget` (`tests/test_chat_sse.py:3548`)
  — add `first_late_ms <= late_tool_call_ms <= last_late_ms` for the late case.
- `test_chat_sse_drain_event_on_done` (`tests/test_chat_sse.py:2506`) — assert
  `first_late_ms` and `last_late_ms` are **both null**.

  **Why they are null here, precisely — the naive reason is wrong.** This
  fixture's stream is not "finish frame and nothing after it": `_start_chat_sse_proxy`
  appends `data: [DONE]\n\n`, so a `[DONE]` frame *does* follow the finish
  frame, and `frames_seen += 1` fires for it like any other frame
  (`server.py:2901`). What keeps the offsets null is **read chunking**: the
  harness responder writes the whole body in one `wfile.write`
  (`_harness.py:1122-1124`), so the content frame, the finish frame and `[DONE]`
  all arrive in a single `read1`, and `_off` is only assigned at the top of a
  read iteration when `finish_reason_seen` is *already* set (`server.py:2871`).
  On the one iteration this stream needs, `finish_reason_seen` is still `None`,
  so `_off` stays `None` and the late-frame block at `server.py:2929` is skipped
  outright — `first_late_ms`/`last_late_ms`/`late_frames` are never touched.

  So the assertion is correct but rests on the single-chunk read, not on
  "nothing followed". Do not restate it as the latter, and do not try to make
  the fixture "cleaner" by removing the `[DONE]` — it is load-bearing here
  (`drain_exit` must be `"done"`). The late-tool-call fixture gets non-null
  offsets the opposite way, by forcing a **second** chunk with `gap_s=0.3` over
  a hanging upstream, which is exactly what makes its sandwich assertion
  meaningful.

  The null case is the load-bearing one: those fields exist to answer "did
  anything arrive after the finish signal", and a stream that ended at the
  finish frame must not claim that something did. Today nothing asserts either
  field's value anywhere in `tests/` (verified: zero matches), so a change that
  took `_off` unconditionally — or dropped the `frames_seen > _frames_before`
  guard — would set both on every drained stream and no test would fail.

**Tests to investigate for retirement:**
- No test obsolescence identified: the change adds a disposition for input the
  current tests never send, and the two fixtures are extended rather than
  superseded.
- Tester may identify additional candidates during test work.

**Retirement procedure:** For each candidate, verify the test exercises code
being removed/changed. If obsolete: delete and note in session report. If still
valid: document why in session report.

### Step 4: pin the two swap-tail dispositions Step 3 creates and protects

<!-- UPDATED: added by the Phase 6 review, 2026-10-16 — finding 4 (Suggestion),
     plus the regression test for Step 3a. The review verified both behaviours
     only ad hoc; its probes are in ./tmp/ and are the reference implementations. -->

**Copy these bodies.** Six consecutive rounds failed on this step by spending
their whole turn reverse-engineering the swap harness inside a 4,775-line test
file and never reaching the write. The code below is complete and its
assertions are **measured, not guessed** — every post-fix expectation was
obtained by running the review's probes against the current tree (Step 3a
already landed). Land it, register it, run it. Do not re-derive.

Place both new test functions immediately after
`test_chat_sse_swap_evicts_pre_finish` (ends at `tests/test_chat_sse.py:4465`),
and add the three registrations next to its entry at `:4768`, which reads
`("chat-sse-swap-evicts-pre-finish", test_chat_sse_swap_evicts_pre_finish),`.

```python
def test_chat_sse_swap_evict_stranded_never_flushes():
    """A pre-finish eviction whose residual buffer already holds a STRANDED
    `data: [DONE]` (no delimitng blank line) must not run the EOF flush: the
    eviction closes the turn retryably and `saw_done` stays 0 with the sentinel
    demonstrably still in `buf`."""
    print("\n--- Test: Chat SSE Stranded Sentinel Does Not Survive Eviction ---")
    post_press_byte = threading.Event()

    def streamer(handler, info):
        handler.send_response(200)
        handler.send_header("Content-Type", "text/event-stream")
        handler.end_headers()
        handler.wfile.write(_sse_stream_chunks(
            [_cc({"role": "assistant", "content": "hi"})]))
        handler.wfile.flush()
        # The stranded sentinel arrives AFTER the press, so it lands in buf
        # while _config_swapping is True and the loop's next read is armed at
        # the swap silence budget -- the timing test_chat_sse_swap_evicts_pre_finish
        # uses, but with a sentinel left in buf.
        post_press_byte.wait(15)
        handler.wfile.write(b"data: [DONE]\n")
        handler.wfile.flush()
        time.sleep(30)  # hold silently

    proxy_port, trace_file, mock_servers, cleanup = _chat_swap_proxy(streamer)
    if proxy_port is None:
        fail("Failed to set up test")
        return
    try:
        out = {}
        client = _chat_stream_in_thread(proxy_port, out)
        if not _wait_upstream_request(mock_servers, "p"):
            fail("upstream never received the stream request")
            return
        switch_out = {}
        sw = threading.Thread(
            target=lambda: switch_out.update(zip(
                ("status", "data"),
                _admin_post(proxy_port, "/admin/api/switch", _CHAT_SWITCH_TO_Q))),
            daemon=True)
        sw.start()
        if _wait_admin_swapping(proxy_port) is None:
            fail("swap never became visible on /admin/api/swap-status")
            return
        post_press_byte.set()
        sw.join(20)
        client.join(25)
        if switch_out.get("status") != 200:
            fail("switch returned {}: {}".format(
                switch_out.get("status"), switch_out.get("data")))
            return
        cstatus, _ctype, raw = out.get("result", (0, "", b""))
        if cstatus != 200:
            fail("client stream status {}, expected 200".format(cstatus))
            return
        if b"config swap in progress" not in raw:
            fail("evicted chat stream must end with the retryable error: {!r}"
                 .format(raw[-300:]))
            return
        frame_types = [_sse_frame_type(f) for f in _parse_sse_frames(raw)]
        if "error" not in frame_types:
            fail("evicted chat stream must carry an SSE error frame")
            return
        if b"message_stop" in raw or b"message_delta" in raw:
            fail("an eviction must not synthesise a terminal, got {}"
                 .format(frame_types))
            return
        truncated = _wait_for_trace_events(trace_file, "chat_sse_truncated")
        drains = _trace_events_named(trace_file, "chat_sse_drain")
        if len(truncated) != 1 or drains:
            fail("expected exactly one chat_sse_truncated and no chat_sse_drain, "
                 "got {} / {}".format(len(truncated), len(drains)))
            return
        ev = truncated[0]
        # The PAIR is the assertion. `saw_done == 0` alone passes vacuously on
        # an empty buffer, so pin that the 13-byte sentinel really was in buf.
        if ev.get("pending_bytes") != 13:
            fail("expected the 13-byte stranded sentinel still in buf, got "
                 "pending_bytes={!r}".format(ev.get("pending_bytes")))
            return
        if ev.get("saw_done") != 0:
            fail("the flush ran pre-eviction: saw_done={!r} with pending_bytes={!r}"
                 .format(ev.get("saw_done"), ev.get("pending_bytes")))
            return
        phases = {e.get("phase")
                  for e in _wait_for_trace_events(trace_file, "swap_abort")}
        if "stream" not in phases:
            fail("swap_abort phases {} must include stream".format(phases))
            return
        pass_("eviction with a stranded sentinel in buf: flush skipped, saw_done 0")
    finally:
        cleanup()


def _post_swap_straggler_case(sentinel):
    """Shared body for the two straggler shapes. `sentinel` is what the
    upstream appends before holding silently: the stranded form (no trailing
    blank line) or the framed form (`\\n\\n`)."""
    post_press_byte = threading.Event()

    def streamer(handler, info):
        handler.send_response(200)
        handler.send_header("Content-Type", "text/event-stream")
        handler.end_headers()
        handler.wfile.write(_sse_stream_chunks(
            [_cc({"role": "assistant", "content": "hi"})]) + sentinel)
        handler.wfile.flush()
        # No byte AFTER the press: the reader keeps its original socket
        # timeout, so the swap's silence drain completes around it and the
        # epoch bumps. Returning then closes the upstream -> EOF at the proxy.
        post_press_byte.wait(15)
        time.sleep(8)  # hold past budget(2)+grace(2)

    proxy_port, trace_file, mock_servers, cleanup = _chat_swap_proxy(streamer)
    if proxy_port is None:
        fail("Failed to set up test")
        return
    try:
        out = {}
        client = _chat_stream_in_thread(proxy_port, out)
        if not _wait_upstream_request(mock_servers, "p"):
            fail("upstream never received the stream request")
            return
        switch_out = {}
        sw = threading.Thread(
            target=lambda: switch_out.update(zip(
                ("status", "data"),
                _admin_post(proxy_port, "/admin/api/switch", _CHAT_SWITCH_TO_Q))),
            daemon=True)
        sw.start()
        if _wait_admin_swapping(proxy_port) is None:
            fail("swap never became visible on /admin/api/swap-status")
            return
        post_press_byte.set()
        sw.join(20)
        if switch_out.get("status") != 200:
            fail("switch returned {} -- the swap must COMPLETE for this case"
                 .format(switch_out.get("status")))
            return
        client.join(30)
        cstatus, _ctype, raw = out.get("result", (0, "", b""))
        if cstatus != 200:
            fail("client stream status {}, expected 200".format(cstatus))
            return
        # The whole point: an old-epoch straggler dies retryably instead of
        # delivering a terminal on the OLD routing after the swap completed.
        if b"message_stop" in raw or b"message_delta" in raw:
            fail("old-epoch straggler synthesised a terminal after the swap: {}"
                 .format([_sse_frame_type(f) for f in _parse_sse_frames(raw)]))
            return
        if b"config swap in progress" not in raw:
            fail("straggler must close with the retryable swap error: {!r}"
                 .format(raw[-300:]))
            return
        if not _trace_events_named(trace_file, "swap_abort"):
            fail("expected a swap_abort event for the evicted straggler")
            return
        pass_("post-swap straggler closed retryably, no old-routing terminal")
    finally:
        cleanup()


def test_chat_sse_post_swap_straggler_dies_retryably():
    """A pre-finish straggler that outlives a COMPLETED swap must not deliver a
    synthesised terminal on the old routing -- it dies retryably at the epoch
    checkpoint on the eof exit. Stranded sentinel shape."""
    print("\n--- Test: Chat SSE Post-Swap Straggler (stranded sentinel) ---")
    _post_swap_straggler_case(b"data: [DONE]\n")


def test_chat_sse_post_swap_straggler_dies_retryably_framed():
    """The framed control. At HEAD the framed form already misbehaved and the
    stranded form did not; after the epoch checkpoint neither may deliver an
    old-routing terminal."""
    print("\n--- Test: Chat SSE Post-Swap Straggler (framed sentinel) ---")
    _post_swap_straggler_case(b"data: [DONE]\n\n")
```

Registrations to add beneath `:4768`:

```python
    ("chat-sse-swap-evict-stranded-never-flushes",
     test_chat_sse_swap_evict_stranded_never_flushes),
    ("chat-sse-post-swap-straggler-dies-retryably",
     test_chat_sse_post_swap_straggler_dies_retryably),
    ("chat-sse-post-swap-straggler-dies-retryably-framed",
     test_chat_sse_post_swap_straggler_dies_retryably_framed),
```

**Measured post-fix expectations** (do not substitute your own — these came from
running the review's probes against the current tree):

| Case | terminal | error frame | `swap_abort` | `chat_sse_truncated` |
|---|---|---|---|---|
| eviction, stranded in buf | none | `config swap in progress` | `phase: "stream"` | 1, `saw_done: 0`, `pending_bytes: 13` |
| straggler, stranded | none | `config swap in progress` | present | 1, `saw_done: 0`, `pending_bytes: 13` |
| straggler, framed | none | `config swap in progress` | present | 1, `saw_done: 1`, `pending_bytes: 0` |

The review's probes in `./tmp/` are **pre-fix references and now fail on
purpose** — `probe_stranded_swap_straggler` reports 4 failed checks and
`probe_framed_swap_straggler` 3, each because the fix inverted what they
assert. That is the proof Step 3a works; do not "fix" the probes to match, and
do not copy their assertions.

→ tester verify: both new tests pass; the module's pre-existing SSE tests are
  unchanged; the full suite's count rises by exactly **2** from the pre-Step-4
  figure.

<!-- AS BUILT 2026-10-16: the round landed TWO tests, not the three specified
     above — it folded both straggler shapes into one test with a `run_shape`
     helper instead of splitting them into two. That is a better design (one
     scenario, two parameterisations) and strictly covers the same ground; the
     module went 71 -> 73, not 71 -> 74. The three bodies above remain the
     specification of what must be asserted; the helper-based single test is an
     accepted authoring difference, not a gap. -->

## Summary

The chat-mode SSE reader has one framing rule — a frame exists only once the
`\n\n` delimiter is seen — and everything else hangs off it. Two survivors of
that region's last two reworks are both in its tail.

**1. A stranded `[DONE]` is discarded.** The disposition a stream gets at EOF
was changed on 2026-10-04 from "synthesise anyway" to "if no `[DONE]` arrived,
this was cut — close it with a retryable error". That change made a previously
invisible framing assumption the trigger for a client-visible retry: a provider
that writes `data: [DONE]\n` and closes without the blank line is
protocol-complete, but `saw_done` stays 0, so the proxy errors the stream and
the client re-issues a request that already succeeded.

**2. The drain's late-frame offsets are unasserted.** `first_late_ms` and
`last_late_ms` are emitted on the **`chat_sse_drain`** event to record how far
past `finish_reason` late frames arrived, and are `None` when nothing did. No
test anywhere asserts either field's value or its null case, so the one
distinction they exist to make — a stream that ended at the finish frame versus
one that drained — is unpinned.

> **Event-name correction (pre-launch pre-flight).** An earlier draft of this
> Summary said these fields are emitted on `chat_sse_truncated`. They are not.
> `server.py:2623` logs them from `log_drain()`, whose event is
> **`chat_sse_drain`**; `chat_sse_truncated` (`server.py:3085`) carries only
> `pending_bytes` and `saw_done`. The two events are mutually exclusive by
> design — a stream that reached a `finish_reason` gets `chat_sse_drain`, and
> one that did not gets `chat_sse_truncated`. Guidance for Tester was already
> correct (both fixtures it names read `chat_sse_drain`), but the mislabel was
> load-bearing: asserting `.get("first_late_ms")` against a
> `chat_sse_truncated` event yields `None` unconditionally, so the "both null"
> assertion would have **passed vacuously** on a stream that never produced the
> event at all — the exact false-pass shape this plan exists to close.

**Approach.** One narrow parser change plus two assertion lines. The flush is
deliberately sentinel-only: at EOF the `[DONE]` sentinel is unambiguous, while a
partial JSON payload is not, and a general residual flush would emit new
`chat_sse_malformed_json` events on genuinely truncated streams — changing the
measurement rather than the behaviour.

```
  frame loop:  buf.find(b"\n\n") ──► handle_frame ──► saw_done = True
                      │
                      └─ no delimiter found ──► loop exits with buf holding
                                                one undelimited frame
                                                      │
  EOF disposition: ◄──────────────────────────────────┘
     NEW: buf is exactly `data: [DONE]` ──► saw_done = True ──► terminal sequence
          anything else ──────────────────► unchanged (cut-stream branch)
```

**Alternatives considered.** (a) *General residual flush* — feed every complete
line through `handle_frame`; rejected because it repairs a case nobody reported
at the cost of new trace events on truncated streams. (b) *Document the
assumption only* — the issue's own cheapest option; rejected because it leaves a
working stream being errored and retried, which is a client-visible defect, not
just an unrecorded assumption. (c) *Drop the `\n\n` rule and use a
line-oriented parser* — rejected as a rewrite of load-bearing framing for one
sentinel.

**Out of scope.** Which providers actually omit the trailing blank line (not
determinable from here, and the fix is correct either way); the per-read
granularity of `late_frames`; and the two resolved siblings of this region
(`finish-before-tool-calls-dropped`, `trailing-usage-chunk-never-read`).

## Repo Mode

Public

## Document Overrides

| Document | Rule Overridden | Reason |
|----------|----------------|--------|

## Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| The flush could over-reach and treat a truncated payload as terminal | A genuinely cut stream would be synthesised as a finished turn — the exact failure the 2026-10-04 change was made to prevent | The match is an exact `[DONE]` on the joined `data:` lines, mirroring `handle_frame`; the negative-control test pins the partial-payload case |
| Changing EOF behaviour could alter existing truncated-stream tests | Red suite | The two existing truncated fixtures are named in Guidance for Tester and asserted unchanged; the new path only fires on input they never send |

## Proposed Changes

1. **Step 1:** Flush a `[DONE]` sentinel stranded in the buffer at EOF, before the cut-stream disposition, in `src/claude_retry_proxy/server.py`
   → coder verify (auto): the inserted block sits between the frame-assembly loop's end and the `chat_sse_truncated` event; guards on `buf is not None`; mirrors `handle_frame`'s `data:`-line parse; no other line in the post-loop region changed
   → coder verify (scripted): `./tmp/verification/2026-10-15-chat-sse-stream-tail-step1.py` exit 0
   → tester verify: `test_chat_sse_done_without_trailing_blank_line` passes with a synthesised terminal and `saw_done: 1`; `test_chat_sse_partial_frame_at_eof_is_not_flushed` still errors with `saw_done: 0`

2. **Step 2:** Pin the drain's late-frame offsets in the two existing drain fixtures — `first_late_ms <= late_tool_call_ms <= last_late_ms` for the late case, and both fields null for a stream that ended at the finish frame (tester-owned; no coder work)
   → tester verify: both fixtures pass with the new assertions, and the assertions are shown load-bearing by a **shadow-tree calibration** — copy the package to a scratch tree, reset its `server.py` to `HEAD`, and run the module with `PYTHONPATH` pointed at it (`tests/_harness.py` spawns children through `os.environ.copy()`, so the shadow reaches the proxies; keep every scratch path under `./tmp/`).
   <!-- CORRECTED 2026-10-15, twice over. (a) The original text asked the tester
        to invert the `frames_seen > _frames_before` guard "in a scratch edit" —
        a source edit, which is outside the tester's write boundary. The
        shadow-tree recipe above achieves the same measurement without touching
        `src/`, and was executed by the planner: with `server.py` at `HEAD`,
        `chat-sse-done-without-trailing-blank-line` FAILS while
        `chat-sse-partial-frame-at-eof-is-not-flushed` still passes (70/71).
        (b) The tester correctly noted the original description was imprecise on
        its own terms: inverting the guard alone would NOT flip the on-done
        fixture, because `_off` itself is `None` on that single-chunk stream.
        The load-bearing precondition is the `_off` stamping at
        `server.py:2871`, not the guard at :2930. -->

## Guidance for Planner

Documentation tasks you will execute yourself (not the coder):

- **Files to modify:**
  - `./doc/provider-modes.html`
- **When:** after coder finishes
- **What to sync:**
  - `doc/provider-modes.html` — the `chat_sse_truncated` disposition prose
    (~lines 405-415) currently states that `saw_done: 0` means "no `[DONE]` ever
    arrived". That is no longer quite true: a `[DONE]` without its trailing blank
    line is now honoured, so `saw_done: 0` means "no `[DONE]` was seen, including
    as an EOF-stranded sentinel". Record the sentinel-only flush and the explicit
    non-goal (a partial payload at EOF is still discarded).
  - `doc/provider-modes.html` — **two different events, do not conflate them.**
    (a) The `chat_sse_truncated` event-table row (~line 636, it carries
    `pending_bytes` and `saw_done`) takes the sentinel change. (b) The
    late-frame field list at ~line 441 belongs to the **`chat_sse_drain`**
    paragraph — it already names `late_frames`, `first_late_ms`,
    `last_late_ms` and `late_tool_call_ms` — and takes the note that
    `first_late_ms`/`last_late_ms` are `null` when no frame followed the finish
    signal, with that null case now pinned by tests. Editing the wrong one of
    these two rows is the failure mode here: the offsets are documented 200
    lines away from the event that carries them, and a `chat_sse_truncated`
    row edited to talk about offsets would be simply false.
  - **Not in this plan:** `CLAUDE.md`'s "Unresolved Deferred Issues" block — it
    is rewritten wholesale by plan `2026-10-15-deferred-corpus-sweep`.

## History

| Date | Event | Conclusion | Dismissed |
|------|-------|------------|-----------|
| 2026-10-15 | Initial plan | Stranded-`[DONE]`-at-EOF flush (narrow, sentinel-only) plus two assertions pinning the drain's late-frame offsets; gate calibrated red against the pre-change tree and proven green on a simulated fixed tree. | — |
| 2026-10-15 | Spec revision (pre-launch pre-flight) | Two corrections found by verifying the plan against the tree as it stands after `2026-10-15-posix-shutdown-and-stop-reporting` landed (`e080d73`). **(1)** Step 1's insertion anchor was quoted as the single line `if not message_started: start_message()`, which does **not** appear verbatim — the statement is two lines at `server.py:3071-3072`. The cited line number was still correct (Plan A's `server.py` edits are at ~3976, below this region), but a coder landing the anchor by string search would have hunted for text that isn't there. The anchor is now stated as a line pair with the matching `grep`, and the insertion point is named relative to the `chat_sse_truncated` `log_trace` at 3073. **(2)** Added a round-completion directive to Guidance for Coder: seven rounds in this cycle ended their turn with a `run_in_background=True` suite still in flight, were killed by the launcher, and left no session report — so the directive requires the suite to finish before the turn ends and the report to be written regardless of outcome. Gate re-confirmed RED against the current tree (exit 1, both conditions). | — |
| 2026-10-15 | Implementation round (coder) — `build_result: pass`, **report written** | The first round in this cycle to write its session report and exit cleanly ([report](./tmp/reports/2026-10-15-chat-sse-stream-tail-coder-2026-10-15.json)): 15:55:56 started → 16:01:26 exit 0, zero issues filed, zero build warnings, Step 1 `done`. The round-completion directive added in the preceding revision was effective — it ran the scripted gate, confirmed placement, compiled, and wrote the report before exiting. It did **not** run the full suite, which is correct (tester's lane). Planner independent verification: **(1)** the step-1 gate now exits 0 (it was red on both conditions before the round); **(2)** the diff is exactly the plan's snippet at `server.py:3071`, ten lines, no other line in the post-loop region touched; **(3)** the `saw_done` binding is sound — the store at 3080 and the reads at 3088/3090 are in the same function (`_stream_chat_sse_to_anthropic`, 2229-3116) and `saw_done` is `nonlocal`-declared nowhere, so the assignment genuinely reaches the `chat_sse_truncated` trace; **(4)** the parse mirrors `handle_frame`'s arm exactly — same `decode("utf-8", errors="replace")`, same `ln[5:].strip()` over `data:` lines, same `"\n".join(...).strip()`, same exact `== "[DONE]"`, with `if _stranded_data and` standing in for `handle_frame`'s `if not data_lines: return None`; **(5)** `tests/test_chat_sse.py` runs **69 passed / 0 failed**, so the narrow flush regressed nothing in the module it touches. | — |
| 2026-10-15 | Spec revision (pre-launch pre-flight, before the tester round) | **Plan Error corrected: this plan named the wrong event for the late-frame offsets.** The Summary claimed `first_late_ms`/`last_late_ms` are emitted on `chat_sse_truncated`; `server.py:2623` logs them from `log_drain()`, whose event is **`chat_sse_drain`**, while `chat_sse_truncated` (`server.py:3085`) carries only `pending_bytes` and `saw_done`. Found by verifying the tester-guidance fixtures against the source before launching: both fixtures it names read `chat_sse_drain`, which is what first exposed the contradiction. Guidance for Tester was already correct, so no step changed — but the mislabel was **load-bearing**, because `chat_sse_drain` and `chat_sse_truncated` are mutually exclusive per stream: a test asserting `first_late_ms is None` against a `chat_sse_truncated` event would have passed unconditionally on a stream that never emitted the drain event, i.e. a vacuous assertion — the precise false-pass shape this plan exists to close. Also sharpened Guidance for Planner so the doc-sync cannot edit the wrong row: the two target rows are ~200 lines apart in `provider-modes.html`, and the offsets belong to the `chat_sse_drain` paragraph at ~441, not the `chat_sse_truncated` row at ~636. Tester fixture anchors re-verified exactly (`test_chat_sse.py:2506`, `:3548`; file otherwise untouched by the cycle). | — |
| 2026-10-15 | Implementation round (tester) — **failed round**; retry used (1) | The round **hung**. 16:11:42 started, then 48 log lines of genuine reconnaissance through 16:29:23 (reading `test_chat_sse.py` at many offsets, `_harness.py`, `server.py`, two codegraph calls, greps), then two inspection commands and **no output at all for 2h10m** until the launcher's watchdog killed it at 18:40:07 (`timeout: killed after 3600s`). Outcome: **no session report, no test written, the tree untouched** — `git status` still shows only the coder's `server.py` change. No lock file left behind, so a relaunch is not blocked. This is a new failure mode for this cycle: seven earlier rounds *ended their turn* with work done but unrecorded; this one did nothing and stalled. Assess-and-brief before the retry: the 18 minutes were spent locating helpers that all live in `tests/_harness.py` rather than `test_chat_sse.py` (`_start_mode_proxy` 1158, `_mode_tiers` 1088, `_sse_stream_chunks` 1444, `_cc` 1450, `_start_chat_sse_proxy` 1524), and the key fact — that `_start_chat_sse_proxy` cannot express the input under test because it always appends `[DONE]` *with* the blank line — is now written into Guidance for Tester as a ready recipe, so the retry goes straight to writing rather than re-deriving it. Guidance also now requires an explicit `timeout` on any command that can touch a socket, spawn a proxy, or run a test. | — |
| 2026-10-15 | Implementation round (tester, retry) — **failed round; same wedge, planner-stopped** | Log `...-tester-2026-10-15-2.log` (retries get a `-N` suffix). 18:50:30 started, 34 log lines through 19:22:54, then **no log growth for 5.5 min while the child was demonstrably alive** (`python.exe` pid 35228, per the lock's `pid=`; 13.8 MB RSS — idle, not working). That is the identical signature to attempt 1, which never resumed across 2h10m, so rather than let it sit to the 3600 s cap the planner used the documented kill lever (`tmp/logs/<plan-id>-<role>.stop`): `[19:29:16] stopped: killed after 2325s (planner stop file)`, exit 4. **No report, no test written, tree untouched**; the stop file was consumed by the launcher and no lock remains, so the next attempt is not blocked. Planner verification that nothing was lost: the coder's `server.py` change is intact (`_stranded_data` present) and the step-1 gate still exits 0. **Diagnosis:** both attempts wedged *after* long reconnaissance, and both were reading the 4,628-line `test_chat_sse.py` at many offsets — this attempt spent its last 30 minutes grepping `_harness.py` for Step 2's helper, which is defined in `test_chat_sse.py` instead. The likely mechanism is context bloat from that repeated reading, not a fault in the plan's change. The preceding revision's recipe covered Step 1 only; **Guidance for Tester now carries a complete, file-located recipe for both steps**, which is intended to collapse the reconnaissance (and therefore the context) that preceded both wedges. | — |
| 2026-10-15 | Escalation (user-authorized third attempt) | Two tester rounds had wedged, so the one-retry budget was spent and the planner surfaced the decision rather than spending more rounds on its own judgment. User chose a **third attempt with the completed recipe**. This row records that authorization explicitly, since a third round exceeds the standard retry cap. Launch also fixes an operational error of the planner's from attempt 2: the launcher's `--timeout` governs the round's wall clock and the Bash `timeout:` does **not** extend it (attempt 2 died at exactly 3600 s with the Bash limit set to 7200 s), so the third attempt passes `--timeout` to the launcher itself. | — |
| 2026-10-15 | Implementation round (tester, attempt 5) — **`overall_result: SUCCESS`, report written** | After four attempts that wrote nothing, this one completed the work. Log `...-tester-2026-10-15-5.log`: 21:42:41 started, first `Edit` 22:04:04, both new tests added and registered in `ALL_TESTS` (4747-4748), the module compile-checked and run, the full suite run in the **foreground**, every command carrying an explicit `timeout=` (the directive added after attempt 1 wedged), and the report written at 22:38:27 ([report](./tmp/reports/2026-10-15-chat-sse-stream-tail-tester-2026-10-15.json)). The planner's stop file landed 26 s after that write, so **the 16-minute silence before the report was slow generation, not a wedge — the planner's wedge call was wrong**, and the round's own `SUCCESS` report is the evidence. Planner independent verification: full suite **422 passed / 0 failed**; the four plan labels PASSED by name; module 71/71; and a **shadow-tree calibration** — the package copied to a scratch tree with `server.py` reset to `HEAD` makes `chat-sse-done-without-trailing-blank-line` FAIL while the negative control still passes (70/71), so the positive test is measurably load-bearing and the control measurably pins the fix's narrowness. The tester could not run the plan's scratch source inversion (outside its write boundary) and neither can the planner; the shadow tree substitutes for it without touching `src/`. | [tester-deviation-1](report) — the plan's own test recipe was **wrong** and the round was right: a body with a finish frame takes the drain disposition (`server.py:2986-3067` returns before the `chat_sse_truncated` log at :3083), so `saw_done` on `chat_sse_truncated` is unobtainable there. Accepted; the plan text is corrected below. [tester-deviation-2](report) — the plan's Step-2 calibration recipe is imprecise (inverting the `frames_seen` guard alone would not flip the on-done fixture, since `_off` itself is `None` on a single-chunk stream). Accepted; the round's correction is right. |
| 2026-10-16 | Spec revision (/update-plan, post-Phase-6-review) | Phase 6 review ([report](./tmp/reports/2026-10-15-chat-sse-stream-tail-review-2026-10-16.json)) returned **Issues found — non-blocking**: 0 Critical, 1 Warning, 3 Suggestions, and refuted all four of the planner's hunches by measurement. The Warning is a real correctness gap, so the plan gains two steps rather than shipping. **(1)** *Finding 1 (Warning)* — `server.py:2849-2855`: the `read_error` and `eof` exits are the only two of the loop's five exits with no swap-epoch checkpoint, so a pre-finish straggler that survives a completed swap and then EOFs is closed with a synthesised terminal on **old routing**, contradicting the documented no-old-routing-result invariant (measured: switch 200 at +4.8 s, `message_stop` at +8.8 s, `swap_abort` 0). The gap pre-exists at `HEAD` — the framed-`[DONE]` control reproduces it — but the flush widened its reachable input set to the stranded form, and for that input it converted a *correct* post-swap outcome into an incorrect one. New **Step 3a** adds `_swap_epoch_changed(epoch)` before both exits. **(2)** *Finding 3 (Suggestion)* — :3075-3080 duplicates `handle_frame`'s sentinel parse; new **Step 3b** lifts it into one `sentinel_of()` helper (0 divergences measured today, but the copies can drift). **(3)** *Finding 4 (Suggestion)* — the eviction-never-flushes behaviour and the post-swap straggler were proven by probe but left uncommitted; new **Step 4** pins both. **(4)** *Finding 2 (Suggestion)* — the plan's own prose edit to the `saw_done` bullets was never made, leaving the new event-table row's "(see the SSE section)" link pointing at a section that never mentioned the flush; fixed by the planner in `doc/provider-modes.html` and marked `Resolved`. Steps 1 and 2 are unchanged and already verified. | — |
| 2026-10-16 | Implementation rounds (coder Step 3, tester Step 4) — **both steps landed; no tester session report written** | **Coder**: round 1 landed Step 3a and exited without a report; the launcher auto-relaunched, and round 2 correctly identified 3a as already present and matching the plan snippet, completed 3b, and wrote its report (`build_result: pass`, `issues_filed: []`). Step 3 gate PASS on all 8 AST checks. **Tester**: **eight rounds, seven of which wrote nothing.** Attempts 1–6 each spent their whole turn reverse-engineering the swap harness inside a 4,775-line test file and never reached the write; the launcher exhausted its relaunch budget (4 attempts, 3 silent relaunches, "Report: none written since launch" every time). Diagnosed as a **plan-authoring defect, not a round defect**: Step 3 succeeded on its first effective attempt because it carried the exact code to insert, while Step 4 described its tests only in prose. After Step 4 was rewritten to carry three complete test bodies with pre-measured assertions, attempt 7 landed the straggler test and attempt 8 the eviction test. Two tests landed rather than three — both straggler shapes folded into one driven by a `run_shape` helper, which the plan records as an accepted authoring difference (module 71 → 73, not 74). Full suite 424/0, module 73/73, both gates PASS, and Step 3a independently confirmed by the review's probes inverting. **No `tester-2026-10-16` session report exists** for either step; the evidence is planner-run and the plan says so. | — |

## Plan Metadata

```json
{
  "plan_id": "2026-10-15-chat-sse-stream-tail",
  "steps": [
    "Step 1: Flush a [DONE] sentinel stranded in the buffer at EOF, before the cut-stream disposition, in src/claude_retry_proxy/server.py",
    "Step 2: Pin the drain's late-frame offsets in the two existing drain fixtures",
    "Step 3: Checkpoint the swap epoch on the eof/read_error exits, and share the sentinel parse between handle_frame and the flush (added 2026-10-16 by the Phase 6 review, findings 1 and 3)",
    "Step 4: Pin the eviction-never-flushes disposition and the post-swap straggler's retryable close, as three complete test bodies carried verbatim in this plan (added 2026-10-16 by the Phase 6 review, finding 4 and the Step 3a regression; the bodies were added after six tester rounds failed to reach the write step, and their post-fix expectations were measured by running the review's probes against the fixed tree)"
  ],
  "coder_files": ["src/claude_retry_proxy/server.py"],
  "tester_files": ["tests/test_chat_sse.py"],
  "doc_files": ["./doc/provider-modes.html", "./doc/test-catalog.html", "./README.md"],
  "verification_scripts": [
    "./tmp/verification/2026-10-15-chat-sse-stream-tail-step1.py",
    "./tmp/verification/2026-10-15-chat-sse-stream-tail-step3.py"
  ],
  "repo_mode": "Public",
  "document_overrides": []
}
```

## Audit Accumulation

| Counter | Value | Last Updated |
|---------|-------|--------------|
| issues_resolved_since_audit | 0 | 2026-10-15 |
| steps_changed_since_audit | 0 | 2026-10-15 |
| files_changed_since_audit | 0 | 2026-10-15 |

## Documentation

- `doc/provider-modes.html` — the `saw_done` contract at EOF, the sentinel-only
  flush, and the pinned null case for the late-frame offset fields.

## Final Results

**Completion date:** 2026-10-16 (Steps 1–2 on 2026-10-15; Steps 3–4 added by the
Phase 6 review on 2026-10-16)
**Status:** COMPLETED — all four steps landed and verified; all six Issue Log
rows `Resolved`, none `Open` or `Fix Planned`

Four things shipped. **Step 1** honours a `data: [DONE]` sentinel stranded at
EOF without its delimiting blank line, so a protocol-complete stream is no
longer errored and retried. **Step 2** pins the drain's late-frame offsets,
which no committed test had ever asserted. **Steps 3 and 4** come from the
Phase 6 review, which found a real Warning the plan had not anticipated.

### Verification

| Check | Result |
|---|---|
| Full suite | **424 passed, 0 failed, 424 total** (was 422; +2) |
| Module `test_chat_sse.py` | **73 passed, 0 failed** (was 71) |
| Step 1 gate | PASS (exit 0) |
| Step 3 gate (8 AST checks) | PASS — and calibrated **RED against the pre-change tree**, failing 5 checks with `found 2: handle_frame@2711, (fn)@3077` naming the duplication precisely |
| Doc-structure gate | PASS — 9 files, 0 violations |
| Anchor checker | PASS |
| Suite warning | 1 — `No proxy_stop event in trace`, the known `no-proxy-stop-trace-warning` deferral owned by plan `2026-10-15-test-harness-robustness`, not this plan |

**Step 3a is confirmed by the reviewer's own probes, whose expectations the fix
inverted.** `probe_stranded_swap_straggler` measured `message_stop=True`,
`saw_done=1`, `swap_abort=0` before the change and `message_stop=False`,
`saw_done=0`, `swap_abort=1` after — it now reports 4 failing checks precisely
*because* it asserts the defect it was written to demonstrate.
`probe_framed_swap_straggler` likewise flipped 3 checks. `probe_evict_stranded_true`
still passes 7/7, confirming the eviction path was not disturbed. A probe that
passed while asserting the bug, and fails now, is stronger evidence than any
assertion added by the same change.

### Steps 3–4 — the Phase 6 review, and what it cost

The review returned *Issues found — non-blocking* (0 Critical, 1 Warning, 3
Suggestions) and refuted all four of the planner's hunches by measurement. The
Warning was real: `server.py:2849-2855`, the `read_error` and `eof` exits were
the only two of the loop's five exits with no swap-epoch checkpoint, so a
pre-finish straggler that outlived a completed swap was closed with a
synthesised terminal on **old routing** — contradicting the documented
no-old-routing-result invariant, measured as switch 200 at +4.8 s and
`message_stop` at +8.8 s with `swap_abort` count 0.

The gap pre-existed at `HEAD` (the framed-`[DONE]` control reproduces it), but
this plan widened its reachable input set: at `HEAD` a *stranded* sentinel left
`saw_done` at 0 and took the cut disposition — the correct post-swap outcome —
and the flush routed that same input to `saw_done: 1` and a terminal. For that
one shape the plan turned a correct outcome into an incorrect one, so the user
directed it be fixed here rather than deferred.

**Step 4 took eight rounds.** Seven failed without writing: attempts 1–6 never
reached the write step, spending their whole turn reverse-engineering the swap
harness inside a 4,775-line test file, and the launcher exhausted its budget
(4 attempts, 3 silent relaunches, "Report: none written since launch" each
time). This was a defect in the plan's own authoring, not in the rounds: Step 3
succeeded on its first effective attempt because it carried the exact code to
insert, while Step 4 described its tests only in prose. Once Step 4 was rewritten
to carry three complete test bodies with **pre-measured** assertions, attempt 7
landed the straggler test and attempt 8 the eviction test.

**The round then improved on the spec.** Two tests landed rather than three — it
folded both straggler shapes into one test driven by a `run_shape` helper. That
is better design and covers identical ground; the plan records it as an accepted
authoring difference, with the three bodies retained as the statement of what
must be asserted. The module went 71 → 73, not 71 → 74.

### Known gap — no tester session report for Steps 3–4

**There is no `tester-2026-10-16` session report.** Eight rounds on 2026-10-16
produced code but none wrote one; the newest tester report for this plan remains
`tester-2026-10-15` (SUCCESS), which covers Steps 1–2 only. The evidence for
Steps 3–4 is therefore **planner-run**: the full suite (424/0), the module
(73/73), the two gates, and the probe inversions above. That is real evidence and
was produced by commands whose output is in the record, but it is not the
artifact the process expects, and a later reader should not read the green suite
as implying a report that does not exist. The two new test bodies are themselves
the durable evidence: they are committed, they fail against the pre-fix tree, and
they do not depend on any probe left in `./tmp/`.

### Legacy warning — the review's probes are pre-fix references

`./tmp/probe_stranded_swap_straggler_2026-10-16.py` and
`./tmp/probe_framed_swap_straggler_2026-10-16.py` **now fail on purpose** — they
assert the Step 3a defect and were the instrument that demonstrated it. Do not
"fix" them to match current behaviour, and do not reuse them as a spec.
`probe_evict_stranded_true_2026-10-16.py` remains valid (7/7, both before and
after).

### Steps 1–2 (2026-10-15)

A provider that writes `data: [DONE]\n` and closes *without* the blank line that
delimits a frame leaves the sentinel stranded in the buffer. The frame loop only
assembles a frame once it sees `\n\n`, so `handle_frame` never saw it,
`saw_done` stayed `False`, and a protocol-complete stream was closed with a
retryable `api_error` — the client then re-issued a request that had already
succeeded. The flush is deliberately sentinel-only: at EOF an exact `[DONE]` is
unambiguous, while a partial payload is not, and a general residual flush would
emit new `chat_sse_malformed_json` events on genuinely truncated streams,
changing a measurement the drain plans had just established.

The second half of the plan was coverage: `first_late_ms` and `last_late_ms`
existed to record how far past `finish_reason` late frames arrived, and **no test
anywhere in `tests/` asserted either field or its null case** — so the one
distinction they exist to draw was unpinned.

### Files changed (all four steps)

| File | Change |
|---|---|
| `src/claude_retry_proxy/server.py` | **Step 1** — the EOF flush (10 lines), placed after the frame loop and before the `chat_sse_truncated` log, guarded on `buf is not None`. **Step 3a** — `_swap_epoch_changed(epoch) -> return evict_swap()` added before the `drain_exit` assignment on the `read_error` and `eof` exits. **Step 3b** — the sentinel parse lifted into one nested `sentinel_of(text)` above `handle_frame`, called from both it and the flush (pure refactor; observable behaviour unchanged) |
| `tests/test_chat_sse.py` | **Step 2** — `test_chat_sse_done_without_trailing_blank_line`, `test_chat_sse_partial_frame_at_eof_is_not_flushed`, and late-frame assertions in both drain fixtures. **Step 4** — `test_chat_sse_eviction_stranded_sentinel_never_flushes` (`:4698`) and `test_chat_sse_post_swap_straggler_dies_retryably` (`:4791`, covering both sentinel shapes via a `run_shape` helper), plus registrations at `:4972-4973` |
| `doc/provider-modes.html` | The `chat_sse_truncated` row records the stranded-sentinel disposition and the explicit non-goal; the `chat_sse_drain` field list records the null case and the ordering; the `saw_done: 1` bullet gains the stranded-sentinel paragraph (review finding 2) |
| `doc/test-catalog.html` | Count 420 → 422, `test_chat_sse.py` 69 → 71, two new per-test rows, notes on the two extended fixtures — **and a further 422 → 424 / 71 → 73 update for Step 4** |
| `README.md` | The chat-mode streaming passage records that the sentinel is honoured even without its delimiting blank line |

### Steps 1–2 verification (2026-10-15)

**Full suite: 422 passed, 0 failed, 422 total** (up from 420; +2 tests), run
independently by the planner and not only reported. The four plan labels PASSED
by name; the module is 71/71.

**The step-1 gate exits 0** — and it was re-confirmed RED before the change, so
it can actually fail.

**Shadow-tree calibration (measured, not asserted).** The plan asked for the new
assertions to be proven load-bearing via a scratch source inversion — which is
outside the tester's write boundary, and outside the planner's too. Substituted a
measurement that touches no source: the package was copied to a scratch tree,
its `server.py` reset to the preceding commit, and the module run with
`PYTHONPATH` pointed there (`tests/_harness.py` spawns children through
`os.environ.copy()`, so the shadow reaches the proxies). Result: **70 passed /
1 failed** — `test_chat_sse_done_without_trailing_blank_line` FAILS without the
fix, so it genuinely pins it, while the negative control still passes, which is
exactly what proves the flush does not over-reach. The scratch tree was removed
afterwards and the working tree was confirmed unchanged by the exercise.

### Issues resolved

**All six Issue Log rows are `Resolved`** — none `Open`, none `Fix Planned`:

- The two deferred issues this plan was written for:
  `chat-sse-done-framing-assumption` and `chat-sse-late-frame-offsets-unasserted`.
- The four findings the Phase 6 review added, each with its evidence in the
  table: `review-f1` (the swap-epoch checkpoint gap — a real correctness defect,
  fixed rather than deferred), `review-f2` (the flush prose the plan's own
  Guidance-for-Planner called for and the planner had omitted), `review-f3` (the
  duplicated sentinel parse), and `review-f4` (the unpinned eviction
  disposition).

Both `defer-issue-*.json` reports for the first pair were retired on 2026-10-16
by `/update-and-commit` Step 9.6, with the user's explicit approval; this Issue
Log and the archived plan are the surviving record of the disposition.

### Two plan defects the round found — and was right about

Both were defects in **this plan's own text**, and the round overrode them on the
strength of the assertions, which is the correct precedence:

1. **The test recipe was unobtainable.** The plan said to write a body with a
   finish frame and assert `saw_done: 1` on `chat_sse_truncated`. Those are
   mutually exclusive: a finish frame takes the drain disposition
   (`server.py:2986` returns at :3067), so the `chat_sse_truncated` log at :3083
   is never reached. The round declared no finish frame and the tests pass. The
   original Guidance for Tester contained this contradiction before the
   checklist inherited it.
2. **The Step-2 calibration recipe was imprecise on its own terms.** Inverting
   the `frames_seen > _frames_before` guard would not flip the on-done fixture,
   because `_off` itself is `None` on that single-chunk stream; the load-bearing
   precondition is the `_off` stamping at `server.py:2871`.

Both are annotated in place rather than silently rewritten, so the record shows
what a round had to overcome.

### Process note — five tester attempts, and a wrong call by the planner

The tester half took **five attempts**. Attempts 1 and 2 wedged (2h10m and 5.5m
of silence with the process alive); the launcher's own invocation then ran two
more that exited after ~4 minutes of reconnaissance having written nothing. The
planner escalated rather than continuing to spend rounds, and on the user's
direction retried — which succeeded. The most likely cause of the four failures
is transient API degradation rather than anything about this plan: the same
plan, recipe and launcher worked on the fifth attempt, and Bash's permission
classifier reported `sonnet is temporarily unavailable` mid-session.

**One planner call was wrong and is recorded as such:** the planner diagnosed the
16-minute silence before the fifth attempt's report as a wedge and fired the stop
file — which landed 26 seconds *after* the round wrote its report. It was slow
generation, not a wedge. The `SUCCESS` report is the evidence.

### Cycle dependencies

- `CLAUDE.md`'s deferred-issue index still lists both issues this plan resolves;
  that block is rewritten wholesale by
  [`2026-10-15-deferred-corpus-sweep`](./tmp/plans/2026-10-15-deferred-corpus-sweep.md),
  which runs last in the cycle.
- `/update-and-commit` Step 9.6 retires each report whose Issue Log row is
  `Resolved`, so this plan's two deferral reports are retired by its own commit.