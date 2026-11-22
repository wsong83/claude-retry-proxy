# Plan: Bounded-scan the anthropic SSE tier rewrite (ping-first vendors)

**Plan ID:** 2026-11-22-sse-scan-ping-first
**Created:** 2026-11-22

<!-- ## Immediate Actions: absent from initial plans. Populated by /update-plan for revised plans, replaced (not accumulated) on each revision. Contains per-role action-only directives (no rationale) telling agents what to do next. Agents read the full plan for context. -->
<!-- The post-review Immediate Actions section was removed 2026-11-22 (finalize /update-plan): coder and tester directives executed; the planner directives (guidance fix, catalog entry, doc precision) executed in the same session. -->


## Issue Log

Rows ordered newest-first (latest issues at top). New issues are prepended; resolved issues stay in place with updated status.

| Issue | Status | Found | Resolved | Resolved By |
|-------|--------|-------|----------|-------------|
<!-- UPDATED 2026-11-22 (/update-plan post-coder): step1-gate-isolation added and resolved in-session — isolation block + sinks.configure() in both gate scripts; gates re-run green, stderr clean. -->
<!-- UPDATED 2026-11-22 (Phase 6 review): review-nonobject-message-start filed from the review Warning; fixed via the Step 1 isinstance guard this revision. -->
<!-- UPDATED 2026-11-22 (/update-plan post-tester round 2): review-nonobject-message-start Resolved (tester); guidance-nonobject-contract filed and resolved (planner text fix). -->
| [guidance-nonobject-contract](./tmp/reports/2026-11-22-sse-scan-ping-first-guidance-nonobject-contract.json) | Resolved | 2026-11-22 | 2026-11-22 | planner (Guidance for Tester bullet corrected per the gated contract; the implemented test already pinned it) |
| [review-nonobject-message-start](./tmp/reports/2026-11-22-sse-scan-ping-first-review-2026-11-22.json) | Resolved | 2026-11-22 | 2026-11-22 | [tester](./tmp/reports/2026-11-22-sse-scan-ping-first-tester-2026-11-22.json) (546/546; teeth test RED-calibrated end-to-end against HEAD source) |
| [step1-gate-isolation](./tmp/reports/2026-11-22-sse-scan-ping-first-step1-gate-isolation.json) | Resolved | 2026-11-22 | 2026-11-22 | planner (both gates re-run: exit 0, stderr 0 bytes, idempotent) |
| [sse-rewrite-ping-first](./tmp/reports/defer-issue-sse-rewrite-ping-first.json) | Resolved | 2026-11-20 | 2026-11-22 | [tester](./tmp/reports/2026-11-22-sse-scan-ping-first-tester-2026-11-22.json) (545/545; ping-first, keep-scanning, budget tests all pass with documented teeth) |

## Guidance for Coder

**Files to modify:**
- `src/claude_retry_proxy/forwarder.py`
- `src/claude_retry_proxy/server.py`

**Step-by-step with verification:** each step below carries coder checks tagged `(auto)` or `(scripted)`. The coder self-verifies `(auto)` checks and runs the provided script for `(scripted)` checks. See coder Prime Directive 4.

Constraints (do-nots):
- Never touch test files or documentation files — not yours.
- Never rename trace event names (`sse_buffer_cap_exceeded`, `sse_rewrite_malformed_json`, and the `sse_first_event` nesting site stay as-is).
- Never alter the remainder-forwarding loop (server.py:465-492), the non-SSE path (server.py:493-524), or the `_DISCONNECT_ERRORS` handling (server.py:526-528).
- No new trace events, no new env vars, no new module-level state.

### Step-by-step

1. **Step 1 (forwarder.py:1803-1908): rename `_rewrite_sse_first_event` to `_rewrite_sse_event` and add a boolean to every return path.** The boolean reports whether the event *is* the message_start event — determined exactly as today's `is_message_start` (SSE `event:` line OR parsed JSON `type` field), evaluated on every path: an event that cannot be parsed still reports its `event:` line's verdict; a data-only unparseable event reports `False` (the scan continues). Replace the whole function with:

```python
def _rewrite_sse_event(event_bytes, tier, request_id):
    """Rewrite model in one SSE event if it is a message_start event.

    The anthropic-mode stream scan (server.py) splits the buffered prefix
    into complete events and runs each through this function until the
    message_start event is found — vendors may open with keep-alive frames
    (e.g. qwen sends event:ping first), so the rewrite cannot assume
    position. The boolean reports whether this event WAS message_start (by
    the SSE event: line or the parsed JSON type field), telling the scan to
    stop; an event that cannot be parsed still reports its event: line's
    verdict, and a data-only unparseable event reports False so the scan
    continues with the next one.

    Args:
        event_bytes: raw bytes of one complete SSE event (including its
            trailing blank line)
        tier: tier name to rewrite model to
        request_id: for logging

    Returns:
        (bytes, bool): possibly rewritten event, and whether the event is
        message_start
    """
    # Parse SSE event - look for event: and data: lines
    event_text = event_bytes.decode("utf-8", errors="replace")
    lines = event_text.split("\n")
    event_type = None
    data_lines = []

    for line in lines:
        if line.startswith("event:"):
            event_type = line[6:].strip()
        elif line.startswith("data:"):
            data_lines.append(line[5:].strip())

    # Parse JSON from data lines
    if not data_lines:
        return event_bytes, event_type == "message_start"

    json_text = "\n".join(data_lines)
    _nesting = check_payload_nesting(json_text)
    if _nesting is not None:
        # Forward the event unchanged rather than parsing it; the scan
        # continues, so the client sees the upstream model name from this
        # event only if no later event is message_start.
        log_trace(nesting_event("sse_first_event", _nesting,
                                request_id=request_id, tier=tier))
        return event_bytes, event_type == "message_start"
    try:
        data = json.loads(json_text)
    except Exception:  # total per compat._compat_guarded_parse (RecursionError is not a ValueError)
        # Malformed JSON - forward unchanged with warning
        log_trace({
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "event": "sse_rewrite_malformed_json",
            "request_id": request_id,
        })
        return event_bytes, event_type == "message_start"

    # Check if this is a message_start event
    # Check both SSE event type and JSON type field (SSE events can omit event: line)
    json_type = data.get("type") if isinstance(data, dict) else None
    is_message_start = (event_type == "message_start") or (json_type == "message_start")

    if not is_message_start:
        # Not a message_start event - forward unchanged
        return event_bytes, False

    # A message_start event: line over a non-object payload (e.g. "[1,2]"):
    # nothing is rewritable — the scan ends here, degraded, never crashing
    # (a non-dict would make data.get below raise AttributeError; every
    # branch of this function must degrade, not raise).
    if not isinstance(data, dict):
        return event_bytes, True

    # Check for model field and rewrite
    message = data.get("message", {})
    if not isinstance(message, dict):
        return event_bytes, True

    upstream_model = message.get("model")
    if not upstream_model:
        return event_bytes, True

    # Rewrite model to tier name
    message["model"] = tier
    data["message"] = message

    # Rebuild SSE event - preserve original format. The re-serialize runs in
    # its own guard (mirroring transforms_common._transform_and_guard's
    # decode/encode pair): an encode failure degrades to the original event
    # rather than escape unfenced and abort the stream. Kept as
    # defence-in-depth — check_payload_nesting bounds what json.loads is ever
    # shown, so depth no longer reaches the encoder — and kept separate from
    # the decode guard so an encode failure does not log
    # sse_rewrite_malformed_json — the JSON parsed fine.
    try:
        new_json = json.dumps(data)
        if event_type:
            # Had explicit event: line
            new_event = "event: {}\ndata: {}\n\n".format(event_type, new_json)
        else:
            # Data-only format
            new_event = "data: {}\n\n".format(new_json)
        return new_event.encode("utf-8"), True
    except Exception:  # total per compat._compat_guarded_parse (RecursionError is not a ValueError)
        return event_bytes, True
```

   → coder verify (auto): "`_rewrite_sse_event` defined in `forwarder.py`, accepts `(event_bytes, tier, request_id)`, every `return` in the function body is a 2-tuple; `_rewrite_sse_first_event` absent from `forwarder.py`"
   → coder verify (scripted): `python3 tmp/verification/2026-11-22-sse-scan-ping-first-step1.py` exits 0. Calibration: RED on the pre-change tree (2026-11-22, unedited script: `FAIL old-name-gone`, `FAIL new-name-present`, exit 1); the script's behavioral assertions measure the new contract and are reachable only post-edit — any post-edit FAIL means the contract above was not implemented as written; report a blocking issue, do not adapt the code to the script.

2. **Step 2 (server.py): replace the first-event-only buffer block with the bounded scan.** Three edits:

   (a) Import (line 54): `_rewrite_sse_first_event, _rng, _swap_epoch_changed,` → `_rewrite_sse_event, _rng, _swap_epoch_changed,`

   (b) `_stream_upstream_response` docstring, replace the anthropic bullet (lines 305-308):
```
        For SSE (text/event-stream):
          - anthropic mode: scans the stream's leading events under a 64 KB
            total budget and rewrites model in the first message_start event
            to the tier name (vendors may open with keep-alive frames, e.g.
            event:ping). Events before and after it forward unchanged; past
            the budget the stream forwards unscanned (the degrade).
```

   (c) Replace the block from the comment `# SSE path (anthropic mode): buffer first event for model` (line 391) through `first_chunk = False` (line 463) with — verbatim, including comments; the remainder loop starting `# Stream remaining events unchanged.` (line 465) is NOT touched:

```python
                # SSE path (anthropic mode): scan the stream's leading events
                # for the message_start rewrite. Vendors may open with
                # keep-alive frames (qwen sends event:ping before
                # message_start), so the rewrite targets the first
                # message_start event at any position, under a total byte
                # budget — past it the scan gives up and the stream forwards
                # unscanned (the documented degrade).
                scanned = bytearray()   # events processed by the rewrite scan
                pending = bytearray()   # unprocessed tail: complete-but-unscanned events + partial event
                MAX_SCAN_BUDGET = 64 * 1024  # total scanned bytes before the rewrite gives up
                scan_capped = False

                # ONE raw iterator serves the scan and the remainder loop: an
                # httpx2 response stream is single-consumption (a second
                # iter_raw raises StreamConsumed), so both phases consume
                # this same object.
                chunks = resp.iter_raw()
                try:
                    for chunk in chunks:
                        _touch_upstream_activity()
                        if _swap_epoch_changed(epoch):
                            # A completed swap: never forward old-routing bytes.
                            evict_stream()
                            return first_byte_ms
                        pending.extend(chunk)

                        # Split complete events (\n\n-delimited) off the front
                        # and run each through the rewrite until message_start
                        # or the budget ends the scan. The budget check runs
                        # before each split, so scan work stays bounded by the
                        # budget regardless of chunk size or event count.
                        scan_over = False
                        while True:
                            if len(scanned) + len(pending) > MAX_SCAN_BUDGET:
                                scan_capped = True
                                scan_over = True
                                break
                            idx = pending.find(b"\n\n")
                            if idx < 0:
                                break  # no complete event yet; keep reading
                            event_bytes = bytes(pending[:idx + 2])
                            del pending[:idx + 2]
                            rewritten, is_message_start = _rewrite_sse_event(
                                event_bytes, tier, request_id)
                            scanned.extend(rewritten)
                            if is_message_start:
                                scan_over = True
                                break
                        if scan_over:
                            break
                except httpx2.ReadTimeout:
                    # The read bound is the client timeout. A swap in progress
                    # owns this wake (evict retryably); otherwise the stall is
                    # what ends the stream.
                    if forwarder._config_swapping or _swap_epoch_changed(epoch):
                        evict_stream()
                        return first_byte_ms
                except (httpx2.RequestError, httpx2.StreamError, OSError):
                    pass

                if scan_capped:
                    log_trace({
                        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        "event": "sse_buffer_cap_exceeded",
                        "request_id": request_id,
                        "bytes": len(scanned) + len(pending),
                    })

                if scanned or pending:
                    # Flush the scan window: the rewritten message_start (if
                    # found) or the verbatim degrade, plus whatever trailed it
                    # in the final chunk. A partial trailing event is never
                    # parsed — it forwards as received and is completed by the
                    # remainder loop below.
                    head = bytes(scanned) + bytes(pending)
                    self.wfile.write(head)
                    self.wfile.flush()
                    bytes_streamed += len(head)
                    first_byte_ms = (time.time() - first_byte_start) * 1000
                    first_chunk = False
```

   → coder verify (auto): `python -c "import claude_retry_proxy.server"` succeeds; `python -c "import claude_retry_proxy.forwarder"` succeeds
   → coder verify (scripted): `python3 tmp/verification/2026-11-22-sse-scan-ping-first-step2.py` exits 0. Calibration: RED on the pre-change tree (2026-11-22, unedited script: `FAIL old-import-gone`, `FAIL old-flag-gone`, `FAIL new-import-present`, `FAIL new-call-present`, `FAIL scan-budget-literal`, exit 1).

## Guidance for Tester

**Tests to create:**

- **Permanent** (in `tests/test_tier_routing.py`, mirroring the existing harness patterns of `test_response_model_rewrite_streaming` at :393 — mock upstream SSE server + `_setup_tier_routing_test`; follow the spawn-isolation pattern at doc/test-catalog.html#pattern-spawn-isolation):
  - `test_response_model_rewrite_streaming_ping_first` — the qwen shape: upstream streams `data: {"type": "ping"}` then `data: {"type":"message_start","message":{"model":"claude-sonnet-5"}}` then a delta. Assert: ping frame forwarded byte-identical, the message_start event carries `"model": "sonnet"` (tier), and `"claude-sonnet-5"` is absent from the response.
  - `test_response_model_rewrite_malformed_leading_event` — pins the user-confirmed keep-scanning rule: upstream streams `event: ping` with malformed data (`data: not-json`), then a clean message_start. Assert the message_start is still rewritten to the tier.
  - `test_response_model_rewrite_scan_budget_exhausted` — leading events totalling > 64 KB (repeat ping frames past 65536 bytes, or one padding event over the budget) then a message_start. Assert: upstream model name preserved (no rewrite), the message_start forwarded verbatim, the stream completes with all events present, and a `sse_buffer_cap_exceeded` trace event is recorded (read via the harness's trace file; mirror the `_wait_for_trace_events` usage in `test_nesting_limit_sse_first_event_forwarded` at :1403).
  - `test_response_model_rewrite_nonobject_message_start` (added post-review 2026-11-22) — the review Warning's input end-to-end: upstream streams `event: message_start` with a non-object payload (`data: [1,2]`), then a clean `data: {"type":"message_start",...}`. Assert: the response is a single 200 stream (no 502, no corrupt wire), the degraded event forwards byte-identically, and the later message_start forwards verbatim with the upstream model name kept (the scan ends at the non-object message_start — its `event:` line still declares message_start). <!-- UPDATED 2026-11-22: final clause corrected per guidance-nonobject-contract — the earlier text wrongly claimed the later message_start is rewritten; the gated contract returns (event_bytes, True), ending the scan. -->

**Tests to revise:**

  - `test_response_model_rewrite_streaming_non_message_start` (:472) — same ping-first fixture; today it asserts only that the ping is forwarded unchanged (true before and after the fix). Strengthen: also assert the following message_start IS rewritten to the tier and the upstream model name is absent. Update its docstring ("no rewrite attempted" no longer holds — the rewrite now targets the message_start at any position).
  - `test_nesting_guard_rewrite_sse_first_event` (tests/test_nesting.py:885) — calls the primitive via `srv.`; update to the new name and tuple return: under `json.dumps` patched to raise, `srv._rewrite_sse_event(event, "sonnet", "req-nesting-guard-sse")` returns `(event, True)` (encode-fault degrade on a recognized message_start).

**Keep-green verification** (run after revisions; these must pass UNCHANGED — if any fails, the scan changed documented behavior: file a blocking issue, do not adapt the test):
  - `test_response_model_rewrite_streaming` (:393) — message_start-first happy path.
  - `test_nesting_limit_sse_first_event_forwarded` (:1403) — nesting-violating data-only first event: byte-identity assertions hold under the scan (the violating event forwards verbatim; its fixture has no later parseable message_start).
  - `test_lowercase_resp_content_type_anthropic_sse_rewrites_message_start` (tests/test_response_headers.py:532).
  - Full `tests/test_tier_routing.py` and `tests/test_nesting.py` modules green.

**Tests to investigate for retirement:**
- Planner candidates: none — no test is deleted; two are revised (above).
- Tester may identify additional candidates during test work.

**Retirement procedure:** For each candidate, verify the test exercises code being removed/changed. If obsolete: delete and note in session report. If still valid: document why in session report.

## Summary

**Problem.** The anthropic-mode SSE response rewrite (client's tier alias restored into `message_start.message.model`) buffers only the FIRST `\n\n`-delimited upstream event (64 KB cap) and rewrites it only if it is a `message_start`. Vendors that open with a keep-alive frame — measured live on the qwen tier (`event: ping` before `message_start`, 2026-11-16) — therefore get no rewrite at all: the client sees the upstream model name on every streamed response ([defer-issue-sse-rewrite-ping-first](./tmp/reports/defer-issue-sse-rewrite-ping-first.json), which this plan adopts and resolves). The JSON path is unaffected.

**Approach.** Turn the first-event-only consumer into a bounded scan in `server.py`'s existing buffer loop: complete `\n\n`-delimited events are split off the buffer front and each runs through the per-event rewrite primitive (forwarder.py, renamed `_rewrite_sse_event`, now also reporting "this was message_start" as a boolean). The scan ends when a message_start is found (that one event rewritten; everything before and after forwards verbatim), when a **64 KB total budget** on scanned+buffered bytes is exhausted (everything forwards verbatim; the existing `sse_buffer_cap_exceeded` trace event; the stream continues unscanned), or at EOF (the buffered tail forwards verbatim — note an unterminated final event is no longer parsed, a deliberate delta on a broken-stream edge, see Risks). The remainder-forwarding loop, the non-SSE path, per-chunk swap-epoch checks, ReadTimeout-while-swapping eviction, and `_touch_upstream_activity` are retained verbatim — the scan writes nothing until it concludes, so there is no new interaction with the config-swap drain.

**Key decisions** (Phase 3, user-confirmed 2026-11-22):
- Budget = **64 KB total, buffer-size accounting** (one check before each event split): reuses today's constant, comparison direction (`>`), trace event, and documented bound; bounds the proxy's buffered memory exactly. An event fully in hand at the moment the budget crosses is not processed — accepted; real vendors sit a ping's-length inside the budget.
- **Unparseable leading events do not end the scan** (malformed JSON / nesting-violating): forwarded byte-identically, scan continues, a later clean message_start is still rewritten. `event:` line still ends the scan on an unparseable message_start-lined event (per-event verdict, matching today's recognition order).
- Trace event names unchanged (`sse_buffer_cap_exceeded`, `sse_rewrite_malformed_json`, nesting site `sse_first_event`) — renaming would churn a green test asserting the site string for zero behavior gain.

**Alternatives rejected:** per-event cap + event-count cap (two knobs; subsumed by the byte budget); smaller budget (new constant, diverges from documented 64 KB); scan without a budget (unbounded memory, unbounded first-byte delay); stop-scanning on unparseable events (user-rejected: one weird frame would still kill the rewrite).

**Out of scope:** CRLF-delimited SSE streams (`\r\n\r\n` never matches the `\n\n` delimiter — pre-existing bypass, no vendor observed needing it); chat/response modes (full body transforms already rewrite); the JSON path.

## Repo Mode

Public

*Detected at plan creation. Determines: plan archival path, commit-message content, staged files.*

## Document Overrides

| Document | Rule Overridden | Reason |
|----------|----------------|--------|

## Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| Suite red between Steps 1 and 3: `test_nesting.py:885` calls the old name | Coder round ends with a known-red unit test | Staging is expected; the coder never runs the suite; Step 3 restores green. Coder gates (both scripts) are suite-independent |
| EOF-mid-event delta: an unterminated final `message_start` (stream died before its blank line) is no longer parsed/rewritten — it forwards verbatim (today the undelimited buffer went through the rewrite) | Broken-stream edge only; the response is truncated regardless | Accepted deliberately; tester's keep-green list must not assert the old edge behavior |
| CRLF-only streams bypass the rewrite | Pre-existing, unchanged by this plan | Documented as out of scope; separate plan if a vendor ever needs it |

## Proposed Changes

Each step includes verification checks tagged with confidence (see Prime Directive 4).
`(auto)` = mechanical, coder self-verifies. `(scripted)` = deterministic multi-step, coder runs provided script.
Every step must have at least one verification check executable by its owner (coder steps: coder checks; tester steps: tester verify; planner steps: Evidence).
Steps MUST use this numbered-list format exactly. The `### Step N:` heading format is deprecated and must not be used.

1. **Step 1: Generalize the SSE rewrite primitive into `_rewrite_sse_event` (tuple return)** — forwarder.py:1803-1908; full replacement text in Guidance for Coder Step 1.
   → coder verify (auto): `_rewrite_sse_event` defined in `forwarder.py` accepting `(event_bytes, tier, request_id)`; every return in its body is a 2-tuple; `_rewrite_sse_first_event` absent from `forwarder.py`
   → coder verify (scripted): `python3 tmp/verification/2026-11-22-sse-scan-ping-first-step1.py` exits 0 (RED calibration on pre-change tree recorded 2026-11-22: 2 FAILs, exit 1, script unedited)
   → tester verify: `test_nesting_guard_rewrite_sse_first_event` (revised) passes — encode-fault degrade returns `(event, True)`; the step-1 gate's eleven behavioral assertions all PASS, including `message-start-line-nonobject-true` (RED calibration 2026-11-22 post-review: `primitive-raised` AttributeError + 1 FAIL, script unedited)

2. **Step 2: Replace the first-event buffer with the bounded scan in `server.py`** — import line 54, docstring bullet, block at lines 391-463; full replacement text in Guidance for Coder Step 2.
   → coder verify (auto): `python -c "import claude_retry_proxy.server"` and `python -c "import claude_retry_proxy.forwarder"` succeed
   → coder verify (scripted): `python3 tmp/verification/2026-11-22-sse-scan-ping-first-step2.py` exits 0 (RED calibration on pre-change tree recorded 2026-11-22: 5 FAILs, exit 1, script unedited)
   → tester verify: `test_response_model_rewrite_streaming_ping_first` and `test_response_model_rewrite_malformed_leading_event` pass; `test_response_model_rewrite_streaming` (:393) stays green unchanged

3. **Step 3: Tests — pin the scan (ping-first, keep-scanning, budget) and revise the two shaped tests** — details in Guidance for Tester.
   → tester verify: the three new permanent tests pass; both revisions pass; the keep-green list passes unchanged; full `test_tier_routing.py` + `test_nesting.py` green

4. **Step 4: Documentation sync — scan semantics replace first-event wording** — details in Guidance for Planner.
   → Evidence: `git diff --stat -- CLAUDE.md doc/` shows only the five doc files touched; `git grep -n "first event\|first-event" doc/ CLAUDE.md` returns only intentional occurrences (budget prose or chat-mode text), each cited in the session output; `doc/test-catalog.html` carries entries for the new tests and updated text for the revised ones

## Guidance for Planner

Documentation tasks you will execute yourself (not the coder):

- **Files to modify:**
  - `./CLAUDE.md`
  - `doc/provider-modes.html`
  - `doc/trace-log.html`
  - `doc/architecture.html`
  - `doc/test-catalog.html`
- **`.claude/mega-audit-files.json`:** no declared-location changes in this plan.
- **When:** after the coder and tester rounds complete (test-catalog entries depend on final test names; mechanism docs may be drafted earlier but land together).
- **What to sync:**
  - `CLAUDE.md` (~line 149): "Anthropic-mode SSE: buffer the first event (64 KB cap), rewrite `model` in `message_start`, forward the remainder unchanged." → bounded-scan wording (leading events, 64 KB total budget, first `message_start` at any position, verbatim degrade past the budget).
  - `doc/provider-modes.html`: mode-table row (~242-243); the "covers the first event only" paragraph (~257-261) — replace with the scan description and DROP the `defer-issue-sse-rewrite-ping-first` reference (resolved by this plan); trace-event row (~755): "64 KB first-event bound" → "64 KB scan budget"; streaming-table row (~362) — verify wording still holds ("first `message_start` event's `model`" is now literally accurate), adjust only if it contradicts the scan.
  - `doc/trace-log.html`: nesting-site list (~163) and event descriptions (~217-218) — `sse_buffer_cap_exceeded` becomes the scan budget's degrade; `sse_rewrite_malformed_json` / `sse_first_event` fire per leading event within the scan window.
  - `doc/architecture.html`: the bounded-parse list (~390) and the "Upstream buffered body, SSE first event" row (~405-407) — the claim "for the SSE first event the client therefore sees the upstream model name" must become the scan semantics (a nesting-violating leading event forwards verbatim but no longer kills the rewrite; a later message_start is still rewritten).
  - `doc/test-catalog.html`: update entries for `test_response_model_rewrite_streaming_non_message_start` (~255), the nesting-limit entry (~262), the guard entry (~870 — new name), verify the lowercase-content-type entry (~972-974); add entries for the three new tests.
  - Doc-sync sweep: `git grep` the changed identifiers (`_rewrite_sse_event`, `rewrite_skipped`) and the phrase family ("first event", "first-event") across `doc/`, `CLAUDE.md`, README.md, and docstrings; collect test counts from the working tree, never prose.

## History

| Date | Event | Conclusion | Dismissed |
|------|-------|------------|-----------|
| 2026-11-22 | Spec revision (/update-plan, post-tester round 2 — finalize) | [Tester SUCCESS](./tmp/reports/2026-11-22-sse-scan-ping-first-tester-2026-11-22.json): 546/546 suite; the new `test_response_model_rewrite_nonobject_message_start` passes in-suite and standalone, teeth-calibrated RED end-to-end against reconstructed HEAD source (reproduces the corrupt 502-in-SSE-body); gates 12/12 + 11/11 re-run; [review-nonobject-message-start](./tmp/reports/2026-11-22-sse-scan-ping-first-review-2026-11-22.json) → Resolved (tester); [guidance-nonobject-contract](./tmp/reports/2026-11-22-sse-scan-ping-first-guidance-nonobject-contract.json) filed (tester) and resolved (planner: Guidance for Tester final clause corrected to the gated contract); test-catalog entry added; provider-modes/architecture keep-scanning wording made precise (event-line message_start ends the scan); Immediate Actions removed — no remaining directives | — |
| 2026-11-22 | Spec revision (/update-plan, post-coder round 2) | [Coder report](./tmp/reports/2026-11-22-sse-scan-ping-first-coder-2026-11-22.json): guard applied verbatim (forwarder.py:1871-1876), build pass, step-1 gate 12/12 (the new teeth check flipped RED→GREEN), step-2 gate 11/11, both stderr-clean; review-nonobject-message-start stays Fix Planned pending tester confirmation; Step 1 line-range citations corrected to 1803-1908 (coder-flagged staleness); coder scratch artifact `verbatim-check.py` noted for retire_inventory | — |
| 2026-11-22 | Review | [Report](./tmp/reports/2026-11-22-sse-scan-ping-first-review-2026-11-22.json): "Issues found — non-blocking" (0 Critical / 0 High / 1 Warning / 1 Suggestion); both fixed in this revision — the Warning ([review-nonobject-message-start](./tmp/reports/2026-11-22-sse-scan-ping-first-review-2026-11-22.json): non-object message_start AttributeError, corrupt-wire path) via the Step 1 `isinstance` guard + new teeth test, the Suggestion via the scoped Evidence command; coder + tester rounds relaunched; hunch 1 (input untested) addressed by that teeth test; areas_not_fully_verified: suite re-run covered by the relaunched tester round, live qwen stream remains mock-covered only | [scan-delimiter-chunk-o2](./tmp/reports/2026-11-22-sse-scan-ping-first-review-2026-11-22.json) — 64 KB-bounded, configured-upstream-only, reviewer noted without reproduction; [scan-flag-readability](./tmp/reports/2026-11-22-sse-scan-ping-first-review-2026-11-22.json) — plan-mandated verbatim structure; [eof-mid-event-unpinned](./tmp/reports/2026-11-22-sse-scan-ping-first-review-2026-11-22.json) — behavior accepted in Risks, coverage note only |
| 2026-11-22 | Spec revision (/update-plan, post-tester) | [Tester SUCCESS](./tmp/reports/2026-11-22-sse-scan-ping-first-tester-2026-11-22.json): 545/545 suite, 3 new + 2 revised tests pass with documented teeth, keep-green list green, gates re-run green; sse-rewrite-ping-first → Resolved (tester); the two pre-existing in-process sink-warning observations deferred standalone as [defer-issue-sink-warning-in-process-unit-tests](./tmp/reports/defer-issue-sink-warning-in-process-unit-tests.json) (no plan row); Step 4 doc sync executed — five surfaces (CLAUDE.md, provider-modes, trace-log, architecture, test-catalog), sweep clean (old name survives only as the kept test name/site string; `rewrite_skipped` zero; anchors 272 resolved), Immediate Actions removed (no remaining role directives) | — |
| 2026-11-22 | Spec revision (/update-plan) | Post-coder ([session report](./tmp/reports/2026-11-22-sse-scan-ping-first-coder-2026-11-22.json): Steps 1-2 completed, build pass, both gates 11 PASS): [step1-gate-isolation](./tmp/reports/2026-11-22-sse-scan-ping-first-step1-gate-isolation.json) fixed — canonical isolation block plus `sinks.configure(trace_path=…)` added to both gate scripts before the proxy imports (assertions untouched; RED calibration unaffected); both gates re-run exit 0 with clean stderr, idempotent | — |
| 2026-11-22 | Initial plan | Adopted defer-issue-sse-rewrite-ping-first; bounded-scan design with 64 KB total budget and keep-scanning degrade, both user-confirmed in Phase 3; both step gates calibrated RED on the pre-change tree (step 1: 2 FAILs; step 2: 5 FAILs, scripts unedited) | — |

## Plan Metadata

```json
{
  "plan_id": "2026-11-22-sse-scan-ping-first",
  "steps": [
    "Step 1: Generalize the SSE rewrite primitive into _rewrite_sse_event (tuple return)",
    "Step 2: Replace the first-event buffer with the bounded scan in server.py",
    "Step 3: Tests — pin the scan (ping-first, keep-scanning, budget) and revise the two shaped tests",
    "Step 4: Documentation sync — scan semantics replace first-event wording"
  ],
  "coder_files": ["src/claude_retry_proxy/forwarder.py", "src/claude_retry_proxy/server.py"],
  "tester_files": ["tests/test_tier_routing.py", "tests/test_nesting.py"],
  "doc_files": ["./CLAUDE.md", "doc/provider-modes.html", "doc/trace-log.html", "doc/architecture.html", "doc/test-catalog.html"],
  "verification_scripts": [
    "./tmp/verification/2026-11-22-sse-scan-ping-first-step1.py",
    "./tmp/verification/2026-11-22-sse-scan-ping-first-step2.py"
  ],
  "retire_inventory": [
    "./tmp/reports/2026-11-22-sse-scan-ping-first-coder-2026-11-22.json",
    "./tmp/reports/2026-11-22-sse-scan-ping-first-tester-2026-11-22.json",
    "./tmp/reports/2026-11-22-sse-scan-ping-first-review-2026-11-22.json",
    "./tmp/verification/2026-11-22-sse-scan-ping-first-step1.py",
    "./tmp/verification/2026-11-22-sse-scan-ping-first-step2.py",
    "./tmp/verification/2026-11-22-sse-scan-ping-first-fullsuite.py",
    "./tmp/verification/2026-11-22-sse-scan-ping-first-teeth-nonobject.py",
    "./tmp/verification/2026-11-22-sse-scan-ping-first-verbatim-check.py"
  ],
  "repo_mode": "Public",
  "document_overrides": []
}
```

## Audit Accumulation

*Counters reset when mega-audit runs. Used by Phase 5 entry trigger.*

| Counter | Value | Last Updated |
|---------|-------|--------------|
| issues_resolved_since_audit | 4 | 2026-11-22 |
| steps_changed_since_audit | 1 | 2026-11-22 |
| files_changed_since_audit | 0 | 2026-11-22 |

## Documentation

Doc synchronization is specified in **Guidance for Planner** (five surfaces; lands after the coder and tester rounds).

## Final Results

**COMPLETED — 2026-11-22.**

- **Implemented:** the anthropic-mode SSE tier rewrite now scans the stream's leading events under a 64 KB total budget and rewrites `model` in the first `message_start` at any position (ping-first vendors fixed — `defer-issue-sse-rewrite-ping-first`, adopted and Resolved); unparseable leading events forward byte-identically without ending the scan (unless their `event:` line reads `message_start`); a non-object `message_start` payload degrades without raising (post-review `isinstance` guard); past-budget streams forward unscanned with `sse_buffer_cap_exceeded`. Steps 1-2 (coder, two rounds), Step 3 (tester, two rounds), Step 4 (planner doc sync, five surfaces) all executed.
- **Test results:** full suite 546/546 (`python3 tests/test_claude_proxy.py`); six new permanent tests (ping-first, malformed-leading-event, budget-exhausted, non-object-message-start + the non-object end-to-end teeth test), two tests revised; every new/revised test teeth-calibrated against the pre-change tree; keep-green list green across both rounds; plan gates (12/12 + 11/11) green; spawn-isolation corpus checker PASS.
- **Review:** "Issues found — non-blocking" (0 Critical / 0 High / 1 Warning / 1 Suggestion); both findings fixed and tester-verified; three hunches dismissed in History, hunch 1 addressed.
- **Issues:** 4 resolved (step1-gate-isolation, review-nonobject-message-start, guidance-nonobject-contract, sse-rewrite-ping-first). Plan-scoped issue reports retire via the `/update-and-commit` Step 9.6 hand-off.
- **Documentation:** CLAUDE.md, provider-modes.html, trace-log.html, architecture.html, test-catalog.html synced to the scan semantics; identifier/phrase sweep clean; anchor checker PASS (272 anchors).
- **Known caveats:** an unterminated final `message_start` (stream died before its blank line) forwards verbatim, never rewritten (accepted, Risks); the live qwen stream remains mock-covered only (no live upstream in any round); strictly CRLF-delimited streams bypass the rewrite (pre-existing, out of scope).

**Deferred issues:**

- [sse-rewrite-ping-first](./tmp/reports/defer-issue-sse-rewrite-ping-first.json) — adopted by this plan, **Resolved** 2026-11-22; its report retires via the Step 9.6 hand-off at commit.
- [sink-warning-in-process-unit-tests](./tmp/reports/defer-issue-sink-warning-in-process-unit-tests.json) — standalone **Open** deferral (two pre-existing cosmetic stderr warnings from in-process unit tests with unconfigured sinks; test hygiene only, zero verdict impact); stays on disk until a future plan adopts it.

## Cross-References to Prior Plans

| Prior Plan | Deferred Issue | Resolution |
|------------|---------------|------------|
| 2026-11-20-fix-response-content-type-casing | tracked as \`defer-issue-sse-rewrite-ping-first\` | This plan implemented the bounded leading-event scan that resolves the gap; the deferral was adopted into this plan's Issue Log and is Resolved (2026-11-22) |
