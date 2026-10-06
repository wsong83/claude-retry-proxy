# Plan: Retry the stalled chat-mode turn — error the unfinished turn and nudge the retry

**Project:** /home/wsong83/proj/claude-retry-proxy
**Plan ID:** 2026-10-05-chat-retry-nudge
**Created:** 2026-10-05

## Summary

**The failure this plan addresses.** The chat-mode upstream models occasionally end an
agentic turn with prose only — announcing the next action — while never emitting a
tool call on the wire (`finish_reason: "stop"`, no `tool_calls` bytes anywhere). The
proxy maps that faithfully to `end_turn`; the client cannot distinguish "done" from
"meant to call a tool". Interactively the user must nudge ("were you planning any tool
calls?"); unattended `--operate` rounds die silently with `exit 0` and no session
report. Measured in the 2026-10-04/05 investigation
(`./tmp/research/2026-10-05-text-only-turn-stall-and-no-report.md`): 885 chat turns →
88 stopped with no tool call (9.9%); 19 flagged by the existing log-only
`chat_sse_unfinished_turn` detector with 100% precision (each maps to a user nudge or a
dead round); 2 more stalls escaped the colon-rule detector (period endings); 5
unattended round deaths on 2026-10-05 alone. The tool-call-loss bug itself is fixed and
out of scope — 801/801 `tool_calls` streams converted correctly in the window.

**The mechanism (user-chosen Option A, design recorded in
`plans/2026-10-04-truncation-error-and-drain-trace.md` History row 2026-10-04 #5).**
When the detector fires on a turn whose tools were declared and no tool call ever
arrived: close the stream with the retryable `api_error` (the same wire shape the cut
path already uses) instead of a synthesized `end_turn`, and record the request in a
short-TTL marker store. The client then recovers by continuing the turn — in a headless
`-p` run the documented behavior is an automatic continuation of a cut-off response
that contains text but no tool calls (up to three times;
code.claude.com/docs/en/errors.md), and interactively the user's `continue` does the
same job. Either way the recovery request extends the conversation, so the store's
messages-prefix branch recognizes it (the exact-hash branch covers a same-body
re-issue, documented for failures before any completed block); the proxy injects a
config-texted nudge into the upstream request copy before the chat transform (so the
transform stays the single mapping authority). If the recovery request's turn *also*
ends unfinished, it passes through without a second error (loop guard). Both prior
blockers are now resolved: (a) detector precision measured at 19/19; (b) the client's
recovery after a mid-stream `api_error` is confirmed — session `067b9574` (a headless
`-p` round) continued 8 s after its cut and completed its work, and the docs describe
the non-interactive continuation for this response shape.

**Inherited deferred issue.** `unfinished-turn-detector-ignores-degraded-tool` was
assigned to this follow-on by the truncation plan; this plan's predicate change
(`not tool_calls_seen`) closes it.

**Out of scope.** Widening the predicate beyond `colon_after_prose` (measure first);
launcher-side hardening in claude-config (separate repo — missing-report ⇒ non-zero
exit, auto-resume nudge); response-mode providers; the other two deferred chat-SSE
issues (`chat-sse-done-framing-assumption`, `chat-sse-late-frame-offsets-unasserted`);
stalls closing via the `[DONE]`-without-`finish_reason` (`saw_done`) path, which keeps
today's synthesized `end_turn` — a recorded boundary, not a silent omission (its
frequency is unmeasured: zero `saw_done: 1` events in the current trace window); and
buffered (non-streaming) chat responses — the detector lives only in the chat SSE path,
so `stream: false` clients keep today's behavior.

## Issue Log

| Issue | Status | Found | Resolved | Resolved By |
|-------|--------|-------|----------|-------------|
| [preexisting-cli-admin-urllib-proxy-403](./tmp/reports/2026-10-05-chat-retry-nudge-preexisting-cli-admin-urllib-proxy-403.json) (pre-existing; CLI localhost admin POSTs honored `HTTP_PROXY` — 3 `test_cli` failures; fixed in coder round 9 (proxy-less `_LOCAL_OPENER`), verified by the final full-suite run) | Resolved | 2026-10-05 | 2026-10-05 | tester |
| [preexisting-cli-state-exdev](./tmp/reports/2026-10-05-chat-retry-nudge-preexisting-cli-state-exdev.json) (pre-existing; `cli.py` `_write_state` temp file cross-device — 7 `test_cli` failures; fixed in coder round 8 (target-dir temp), verified by the final full-suite run) | Resolved | 2026-10-05 | 2026-10-05 | tester |
| [communicate-closed-stdin](./tmp/reports/2026-10-05-chat-retry-nudge-preexisting-communicate-closed-stdin.json) (pre-existing Linux-only defect, 16 tests; fixed in tester round 6 (`_close_child_stdin`), verified by the final full-suite run) | Resolved | 2026-10-05 | 2026-10-05 | tester |
| [tier-routing-double-bind](./tmp/reports/2026-10-05-chat-retry-nudge-preexisting-tier-routing-double-bind.json) (pre-existing Linux-only defect, 3 tests; fixed in tester round 12 (tolerant bind), verified by the final full-suite run) | Resolved | 2026-10-05 | 2026-10-05 | tester |
| [models-chmod-restore-order](./tmp/reports/2026-10-05-chat-retry-nudge-preexisting-models-chmod-restore-order.json) (pre-existing POSIX-only defect, 1 test; fixed in tester round 12 (restore after the assertion), verified by the final full-suite run) | Resolved | 2026-10-05 | 2026-10-05 | tester |
| [unfinished-turn-detector-ignores-degraded-tool](./tmp/reports/defer-issue-unfinished-turn-detector-ignores-degraded-tool.json) (inherited; report reconstructed 2026-10-05 — the original file was absent from `./tmp/reports/`) | Resolved | 2026-10-04 | 2026-10-05 | tester |
| [researcher-cannot-run-mega-audit](./tmp/reports/defer-issue-researcher-cannot-run-mega-audit.json) (cross-repo: claude-config) | Deferred | 2026-10-05 | — | — |
| [plan-reader-transcription-fidelity](./tmp/reports/defer-issue-plan-reader-transcription-fidelity.json) (reopened; cross-repo: claude-config) | Deferred | 2026-10-05 | — | — |

## Guidance for Coder

**Files to modify:** `src/claude_retry_proxy/settings.py`,
`src/claude_retry_proxy/server.py`, `scripts/analyze_proxy_trace.py` — no other source
file changes **for Steps 1-6**; Steps 8-9 (added 2026-10-05) additionally modify
`src/claude_retry_proxy/cli.py`, and Steps 10-11 (added 2026-10-06, post-implementation
mega-audit fixes) modify `src/claude_retry_proxy/server.py` and
`scripts/analyze_proxy_trace.py` again.

**Turn discipline (this plan's rounds are exposed to the very failure it fixes).**
Emit each Edit in the same message as its text. Do not end a turn on a sentence
describing the next edit. If a round stops at a narration, relaunch/nudge and resume at
the first unfinished sub-step — the stall loses no applied edits.

**Leave-safety ordering.** Apply Step 1 before Step 2; Steps 2–3 before Step 4. The
live proxy must never read an unset state: define the store and its helpers before any
call site references them, and thread `retry_original_id` — a **new** value this plan
introduces (no symbol of that name exists in the repo today) — through **three
signatures and five call sites** in one coherent edit (Step 3's enumerated list is the
authority). The parameter is keyword-with-`None`-default, so a missed call site is not
a `NameError` but the more dangerous failure mode: the marker silently switched off on
that path.

---

**Step 1 — `settings.py`: the nudge-text env knob.** Add `DEFAULT_CHAT_RETRY_NUDGE`
(module constant) and, in `ProxySettings.__init__` beside `log_all` (line ~44),
`self.chat_retry_nudge = os.environ.get("PROXY_CHAT_RETRY_NUDGE",
DEFAULT_CHAT_RETRY_NUDGE)` — read with **`os.environ.get`, not `_env_str`**: the
kill switch needs "set but empty" to be distinguishable from "unset", and
`_env_str` maps both to the default (`return val if val else default`).
Empty string **disables the whole feature** (kill switch); a **whitespace-only** value
counts as the empty form (disabled), and a value longer than 4096 characters is also
treated as disabled (it would otherwise be appended unbounded to every matched
upstream body — the client-body cap is checked before injection). Default text, exact:

```
[proxy nudge] Your previous turn ended without a tool call. If you intended to call a tool, emit that tool call now and continue the task.
```

→ coder verify (scripted by step1.py): `SETTINGS.chat_retry_nudge` equals the default
when the env var is unset; `""` when set to `""`; `""` for a whitespace-only value; `""`
for a >4096-char value; the custom text verbatim when set normally.

**Step 2 — `server.py`: the marker store (module level, near the other per-process
state).**

- Constants: `RETRY_NUDGE_TTL_SECONDS = 180`, `RETRY_NUDGE_MAX_ENTRIES = 32`,
  `RETRY_NUDGE_MAX_MESSAGES_BYTES = 1024 * 1024`.
- State: `_retry_nudge_lock = threading.Lock()`, `_retry_nudge_entries = {}` keyed by
  `request_id`. **Lock discipline: every read and write of `_retry_nudge_entries` —
  including the sweep and the eviction scan — runs under `with _retry_nudge_lock:`.
  `remember`/`arm`/`check` each acquire exactly once; `_retry_nudge_sweep()` is
  lock-held-internal — it never acquires (its callers hold the lock), so there is no
  re-entrancy and no self-deadlock on the non-reentrant `Lock`.**
- Helpers (module-level, **no-raise** — any internal failure returns `None`/`False`
  and mutates nothing, matching the sinks' discipline):
  - `_retry_nudge_sweep()` — under the caller's held lock, drop entries past their
    freshness bound: **an armed entry expires the TTL after arm** (`stored_at` is
    refreshed by `arm` — the TTL measures the post-error recovery window, never the
    original request's start). **Unarmed entries are not age-expired** (post-implementation
    mega-audit findings 2/14: age-expiring them let any concurrent eligible request's
    sweep delete a long generation's own marker before its `arm`, silently disengaging
    the feature — this supersedes the original spec, which expired both); they are
    bounded by the cap's oldest-unarmed-first eviction instead. Called only from
    `_retry_nudge_remember` and `_retry_nudge_check`.
  - `_retry_nudge_remember(request_id, body, body_json)` — skip (mutating nothing)
    when `request_id` is falsy **or already present** (a compat/reasoning re-entry of
    the same request must not clobber an entry armed earlier in its lifecycle), or when
    `messages` is not a non-empty list of dicts, or when its serialization exceeds
    `RETRY_NUDGE_MAX_MESSAGES_BYTES`. Otherwise store
    `{hash: sha256(body), messages_json: json.dumps(messages,
    separators=(",", ":")), armed: False, stored_at: time.time()}` and enforce the cap
    by **evicting unarmed entries first (oldest first); armed entries only as a last
    resort** — armed entries are the ones with imminent recoveries.
  - `_retry_nudge_arm(request_id) -> bool` — set `armed = True` and refresh
    `stored_at = time.time()`; return `True` iff an entry was armed, `False` when none
    exists (never creates one). The bool is load-bearing for Step 4's arm gate.
  - `_retry_nudge_check(body, body_json) -> original_request_id | None` — sweep, then
    scan **armed** entries in two passes: (1) exact `sha256(body)` equality across all
    armed entries first; (2) structural prefix — parse `messages_json` and match when
    `new_messages[:len(stored)] == stored` **and `len(new_messages) > len(stored)`**
    (a strict extension: the realistic recovery shape appends the interrupted turn and
    its continuation prompt; a byte-identical re-send belongs to the exact-hash branch,
    and the strictness keeps an equal-length non-identical list from matching).
    **On a match, consume the entry (delete it under the lock) before returning the
    stored `request_id`** — the marker is single-use, so later turns of the recovering
    conversation are neither nudged with now-false "previous turn" text nor silently
    routed into the passthrough loop guard; the recovery request's own passthrough
    decision never re-consults the store (`retry_original_id` is computed once at
    request entry), so the loop guard still holds for that recovery.
- → coder verify (scripted): the planner's step script drives remember/arm/check
  directly (exact match; strict-extension prefix match; unarmed ⇒ no match; a second
  check after a match does not match — consume-on-match; TTL expiry of unarmed entries;
  an entry backdated past the TTL is still armable and fresh after arm; eviction at the
  cap preserves armed entries; lock discipline via AST: `with _retry_nudge_lock:` in
  remember/arm/check, none in sweep).

**Step 3 — `server.py`: request-entry wiring (`_forward_request_impl`).**

- Gate: `if mode == "chat" and tools_declared and SETTINGS.chat_retry_nudge:` then,
  after the `tools_declared` derivation (line ~620):
  `_retry_nudge_remember(request_id, body, body_json)` and
  `retry_original_id = _retry_nudge_check(body, body_json)`; otherwise
  `retry_original_id = None`. Remember strictly first (it no-ops on an id already
  stored — a compat/reasoning re-entry of the same request — and the fresh entry is
  unarmed, so `check` cannot match the request against itself).
- Injection, inside the `if mode == "chat":` transform branch (line ~680) **before**
  the `_anthropic_to_chat(...)` call: when `retry_original_id` is set, append to the
  parsed body's `messages` list:
  `{"role": "user", "content": [{"type": "text", "text": SETTINGS.chat_retry_nudge}]}`
  (guard the list type; skip when `messages` is absent). The mutation touches only the
  parsed copy that becomes the upstream body — the client's bytes are never modified,
  the client response never carries the nudge, and the built bytes are the ones the
  retry loop re-sends (built once, never re-transformed). Log `chat_retry_nudge` with
  `{timestamp, event, request_id, original_request_id, tier, provider, key}` **after
  `rewritten_body` is successfully built** (post-transform, same branch) — a transform
  failure falls back to the client's original bytes, and the event must never claim a
  nudge the upstream did not see.
- Thread `retry_original_id` through **three signatures and five call sites** —
  **exactly mirroring the `tools_declared` threading the truncation plan built**:
  keyword parameter `=None` on `_forward_core` (line ~872),
  `_stream_upstream_response` (line ~1347), `_stream_chat_sse_to_anthropic`
  (line ~1526); passed as `retry_original_id=retry_original_id` at all five call sites
  — 753 and 764 (impl→core), 955 and 1048 (core→stream), 1388 (the chat-SSE call in
  `_stream_upstream_response`; a miss here silently disables the loop guard). Do not
  change any return tuple.
- → coder verify (scripted): AST — the parameter exists on all three functions and is
  passed at **every** call site of the three; (auto) a chat request without a marker
  logs no `chat_retry_nudge` and its upstream body is unchanged.

**Step 4 — `server.py`: the action in `_stream_chat_sse_to_anthropic`.**

- **Predicate change** (closes the inherited deferred issue): add `and not
  tool_calls_seen` to the detector condition (lines ~2134-2136). A tool call the proxy
  saw but could not start a block for is proxy-side degradation, not a model omission
  — it must neither be counted as an unfinished turn nor error the turn.
- **Sentinel alignment (required for the predicate to mean what it says):** change the
  drain-mode seen-test `if delta.get("tool_calls") is not None:` (line ~1939) to the
  truthiness form `if delta.get("tool_calls"):`, matching the pre-finish path (line
  ~1949) and the flag's documented contract (tests/test_chat_sse.py:1479-1480: "set
  only when delta.tool_calls is truthy"). An empty `tool_calls: []` sentinel frame must
  not mark a tool call seen on either path — otherwise a genuine prose-only stall in a
  sentinel-bearing stream is silently downgraded and can never be detected.
- Replace the stale comment above the predicate (server.py:2131-2133: "Shadow detector:
  log-only, no effect on the response …") with the new semantics: the detector acts
  when `PROXY_CHAT_RETRY_NUDGE` is non-empty (errors the unarmed turn, passes the armed
  one through) and remains a pure measurement when the value is empty.
- Extract the `chat_sse_drain` logging block (lines ~2167-2183) plus the
  `post_finish_suppressed` block (~2184-2190) into local helpers so every path logs
  each event exactly once.
- New behavior when the predicate fires (inside `if finish_reason_seen is not None:`,
  after `start_message()`):
  - **Error path** — `retry_original_id is None`, `SETTINGS.chat_retry_nudge`
    non-empty, **and `_retry_nudge_arm(request_id)` returned `True`** (arm runs as
    part of the gate, so it precedes the error write; short-circuit order matters):
    log `chat_sse_unfinished_turn` (field set unchanged); log the drain event; log
    `post_finish_suppressed` if any; `close_all_blocks()`; `log_degradation_if_needed()`;
    then write `{"type": "error", "error": {"type": "api_error", "message": "upstream
    ended the turn without a tool call after tools were declared"}}` and return
    `first_byte_ms` — **no `message_delta`, no `message_stop`**, identical wire shape
    and write ordering to the cut path (trace writes precede the client-visible error;
    the error write is outside the read-loop try, so client-disconnect semantics are
    the same as the cut path). **The arm gate is load-bearing**: when no marker could
    be stored (oversized or malformed messages), the turn passes through instead — a
    conversation that can never be matched must never be errored, or every stall on it
    becomes a repeated-error loop until the client's auto-continue budget is spent.
  - **Passthrough path** — predicate fired and not errored above (a repeat stall with
    `retry_original_id` set, the arm returned `False`, or the feature disabled): log
    `chat_sse_unfinished_turn` as today, plus — only when `retry_original_id is not
    None` — `chat_retry_passthrough` with `{timestamp, event, request_id,
    original_request_id, tier, provider, key}`; then fall through to the existing
    `tool_calls` / `emitted_tool_use` / `terminal` branches unchanged.
- → coder verify (scripted): needle checks — the new predicate clause, the drain
  truthiness form (no `is not None` seen-test on `delta.get("tool_calls")` anywhere),
  the arm-gated error path with arm preceding the error write, the absence of
  `message_delta` on the new path; (auto) the module compiles; the coder does **not**
  run the test suite (tester owns it).

**Step 5 — `scripts/analyze_proxy_trace.py`.** Register `chat_retry_nudge` and
`chat_retry_passthrough` in the input filter tuple (`if _ev not in (…)`, line ~124 —
allowlisting alone is not enough), and give each event an **explicit branch in the
per-event dispatch, each ending `continue`** — otherwise they fall through into
`drain_total += 1` and inflate the drained-stream diagnostics. Add a retry-recovery
section: join each `chat_retry_nudge` to the retry request's own
`chat_sse_drain.emitted_tool_use` and report per-provider retry-success counts (this
join is the regression channel the staged design exists to provide). Dangling keys are
accounted explicitly: a nudged request with no observed drain (errored again,
disconnected, never re-issued, or outside the `--days` window) is reported as its own
count and **excluded from the success denominator**; entries are **deduplicated by
`request_id`** — the guard against multiple armed entries matching one request (the
cross-prefix collision) and belt-and-braces for the once-per-matching-entry rule
(post-implementation mega-audit finding 15: under consume-on-match a compat/reasoning
re-entry cannot re-log the nudge, so the shipped comment's "up to three times"
rationale is stale — reword it, Step 11). Follow the file's existing section style.

**Step 6 — run the planner's step scripts.** `python
./tmp/verification/2026-10-05-chat-retry-nudge-step{1,2}.py` — require exit 0 from
each. These two are the coder's step scripts; the fixture sweep is the plan's third
verification artifact (`./tmp/verification/2026-10-05-chat-retry-nudge-fixture-sweep.py`,
tester-run — see Guidance for Tester); steps 3–5's behavioral coverage is
the tester's suite (Guidance for Tester).

---

## Guidance for Tester

**Tests to create (permanent; register in `ALL_TESTS`):**

- `test_chat_sse_unfinished_turn_errors_and_nudges_retry` — fixture: tools declared in
  the request body, upstream chunks ending text `"Now running the suite:"` +
  `finish_reason: "stop"` + `[DONE]`. Assert (on the FIRST stream only — the re-POST
  below produces a second drain and a second `chat_sse_unfinished_turn`): the stream
  closes with an `error` frame (`error.type == "api_error"`), **no**
  `message_delta`/`message_stop`; a `chat_sse_unfinished_turn` event is logged; exactly
  one `chat_sse_drain` event. Then re-POST with the conversation EXTENDED the way the
  client recovers — the original messages plus an assistant message carrying the
  narration text and a user `"continue"` — and assert the mock upstream's second
  recorded request (`mock_servers["p"]["requests"][1]["body"]`) contains the nudge text
  as a trailing user message; assert a `chat_retry_nudge` event whose
  `original_request_id` equals the first request's id; assert the second stream's
  frames terminal normally. **Then send a THIRD conversation-extending request**: it
  must show **no** `chat_retry_nudge` (the marker is consumed on match — single-use).
  Also cover the exact-hash branch: a byte-identical re-POST injects the nudge too.
  **Harness routing (mandatory):** build this test (and tests 2 and 5) on
  `_start_mode_proxy(..., extra_env=...)` directly — it exposes `mock_servers` and
  supports `extra_env`. `_start_chat_sse_proxy(chunks, add_done=True)` supports
  neither, and extending its 3-tuple return would break its ~42 unpacking call sites;
  do not extend it.
- `test_chat_sse_retry_passthrough_no_second_error` — the same marker flow, but the
  retry's stream again ends unfinished: assert **no** error frame (terminal `end_turn`
  as today), `chat_retry_passthrough` logged with the first request's id, the nudge
  present in the passthrough request's upstream body, and no second error.
- `test_chat_sse_unfinished_turn_predicate_ignores_degraded_tool` — the inherited
  deferred-issue pin: a `tool_calls` delta with an id but no `name` (tracked, never
  started) plus a colon-ending text and `finish_reason: "stop"`: assert **no** error
  frame, **no** `chat_sse_unfinished_turn` event, and the existing degradation event
  still fires. **Second half — the drain-sentinel case:** a colon-ending
  `finish_reason: "stop"` stream with **no** tool call and a late `tool_calls: []`
  sentinel frame still **errors** (an empty array is not a tool call — the drain
  seen-test is truthiness-based after the Step 4 alignment); assert the error frame
  fires and a `chat_sse_unfinished_turn` event is logged.
- `test_chat_sse_no_nudge_without_marker` — request A (tools declared, colon-ending,
  `finish_reason: "stop"`) **is errored and arms its marker** — that is the mechanism
  under test, so make no assertion that A avoids the error frame. Request B — a
  different conversation, sent afterwards — must show **no** `chat_retry_nudge` event,
  an unchanged upstream body, and a normal terminal.
- `test_chat_retry_nudge_disabled_by_empty_env` — start the proxy via
  `_start_mode_proxy` with `extra_env={"PROXY_CHAT_RETRY_NUDGE": ""}`: the
  unfinished-turn stream terminals as today (no error frame), and no marker/nudge
  machinery fires.

**Fixture sweep (do not skip).** The predicate now acts; audit every existing
`tests/test_chat_sse.py` fixture for the collision condition — the request body
declares `tools`, the upstream ends with `finish_reason: "stop"`, the emitted text's
tail (rstripped) ends with `":"`, and no tool call was emitted. **Exactly one fixture
is known to collide by design: `test_chat_sse_unfinished_turn_shadow_logged`**
(tests/test_chat_sse.py:2625, registered as `chat-sse-unfinished-turn-shadow-logged` at
:2997) — its fixture is `"Running the check: "` + `stop` + tools declared + no tool
call, and it asserts the old shadow contract (message_delta/message_stop present, no
error frame, `end_turn`), which the acting predicate deletes. Treat it as a **premise
rewrite, not a fixture tweak**: either migrate its assertions to the new error path, or
retire it into test 1 while carrying over its still-valid event-field pins
(`rule == "colon_after_prose"`, `tools_declared`, `text_tail_len`, provider/key
presence) and its no-tools negative half. Verify every remaining fixture by grep and
record the sweep in the session report — and note that a plain grep for the collision
shape is not authoritative here, because the plan's own test-1 narration text matches
it. Do not silently edit any other fixture.

**Existing tests to check, not change:** the cut-path tests
(`...truncation_still_works`, `...truncation_with_tool_block_emits_error_event`,
`...tool_degradation_on_cut_stream`) and the drain tests — the new error path and the
drain-truthiness alignment must leave them green. The detector's *trigger* gains `not
tool_calls_seen` and its *response* changes by design; the shadow test above is the one
deliberate rewrite, and `test_chat_sse_eof_empty_tool_calls_sentinel`
(tests/test_chat_sse.py:1476) should stay green — the Step 4 truthiness alignment makes
the drain branch match that test's documented contract.

**Step 7 — pre-existing defect repairs (added 2026-10-05 by user decision; tester lane):**
fix the three Linux-conditional defects the module-wise suite run exposed; each has a
filed evidence report with exact sites, root-cause commits, and suggested fixes:

- **`preexisting-communicate-closed-stdin`** (16 tests): `tests/_harness.py` and
  `tests/test_cli.py` write the passphrase, close the child's stdin, then later call
  `proc.communicate()` — which flushes the closed stdin and raises `ValueError` on POSIX
  (test_config_keys swallows it and asserts against `err = ""`; test_cli crashes). Fix at
  the sites (don't close stdin before `communicate` — let it close, or guard with
  `try/except ValueError` and read `proc.stderr` directly); a shared harness helper
  de-duplicates the pattern. **Preserve the passphrase-pipe protocol** (the child must
  still receive its passphrase line and its EOF semantics — check `cli.py`/`server.py`'s
  stdin handling before choosing the form) and prefer the minimal, behavior-preserving
  fix; verify by running `test_config_keys` and `test_cli` modules.
- **`preexisting-tier-routing-double-bind`** (3 tests): `_setup_tier_routing_test`
  unconditionally binds a mock upstream on the vendor URL's port, but the three
  SSE-rewrite tests have already bound their own listener there (EADDRINUSE on Linux).
  Make the harness tolerate a caller-provided listener (skip the second bind) or
  restructure the three tests to register their SSE handler with the harness.
- **`preexisting-models-chmod-restore-order`** (1 test): in
  `tests/test_config_split.py`, move the chmod-0000 restore out of the probe block's
  `finally` so the mode is still 0000 when `load_config` runs (restore in the outer
  `finally` after the assertion).

After the fixes, re-run the four affected modules plus the full suite module-wise to a
green baseline. Do not touch `doc/` (planner-owned) — if the catalog's harness/testing
notes need a platform line, note it in the session report for the planner's doc pass.

**Step 10-11 coverage (added 2026-10-06; permanent, register in `ALL_TESTS`):**

- `test_chat_sse_nudge_reentry_walk_stall_passthrough` — a nudge recovery whose first
  attempt is compatibility-rejected (or reasoning-walk-re-entered) and whose served
  attempt ends in the colon-ending stall: assert the served stream carries **no** error
  frame (the loop guard holds across re-entry — post-implementation mega-audit finding
  1/21) and the served upstream body **contains the nudge text** (injection survives
  re-entry).
- a store-level pin for the production sweep ordering (finding 2/14): backdate an
  **unarmed** entry → run a sweep via a second request's `remember` → `arm` must still
  return True and the recovery must still match; and the armed-entry TTL still expires
  (both halves in one test or two, per the file's style).
- `test_chat_retry_nudge_ineligible_request_does_not_consume` (added 2026-10-06 by
  Step 12): arm a marker; send an **ineligible** matching request (a chat request
  WITHOUT tools whose body strict-extends the armed entry); then send the eligible
  recovery and assert the nudge still fires — `chat_retry_nudge` logged and the nudge
  text present in the served upstream body — i.e., the ineligible request did not
  consume the single-use marker.

**Discipline:** use the existing helpers (`_sse_stream_chunks`, `_cc`,
`_trace_events_named`, `_chat_sse_fetch_frames`, `_sse_stop_reason`; start every new
test's proxy via `_start_mode_proxy`); run each new test standalone (`-t`) **and** in
the full suite with a live proxy running; do not touch `doc/` (planner-owned). Also
correct the stale isolation comment at `tests/_harness.py:47-56` (it still explains the
state path via `mkstemp(dir=PROXY_DIR)`; Step 8 changed that — post-implementation
mega-audit finding 4). Also
update the stale attribute-count docstring in `tests/test_settings.py`
(`test_settings_object_shape` pins "All 15 attributes"; this plan adds a 16th,
`chat_retry_nudge` — the assertion itself passes, only the count text is stale).

## Guidance for Planner

**Doc updates (public tree — keep provider- and project-agnostic):**
- `doc/provider-modes.html` — (a) **rewrite the `#chat-sse-unfinished-turn` section**
  (lines ~417-444): it currently says the turn "arrives with end_turn", "the proxy
  relays exactly what it received", the remedy is "routing rather than repair", and the
  detector is "written to the trace without acting on it — a shadow-mode measurement" —
  all superseded: the detector now errors the unarmed turn (retryable `api_error`, no
  terminal frames), arms a short-TTL single-use marker, injects the nudge on the
  recovery, passes through on a repeated stall, and the empty env value restores the old
  passthrough. (b) Update the degradation/event-table row for
  `chat_sse_unfinished_turn` ("log only — it changes no response" → the acted
  behavior). (c) Annotate the `finish_reason → stop_reason` mapping table's `stop` row
  (lines ~239-246, "otherwise end_turn (see below)") with the new exception: when the
  detector fires and the feature is enabled, the stream closes with a retryable error
  instead of an `end_turn` terminal sequence. (d) The `#chat-sse-drain` subsection
  addition as previously scoped (marker, nudge, passthrough loop guard, kill switch;
  the error box wording), plus a note that the marker store retains conversation
  `messages` in process memory for up to 180 s (bounded 32 × ≤1 MiB, in-process only —
  no log/API path exposes it).
- `doc/trace-log.html` — register `chat_retry_nudge` and `chat_retry_passthrough` in
  the event inventory; **rewrite the `chat_sse_unfinished_turn` row AND its prose
  paragraph** (lines ~127-130 and ~181-192) — the "log only / changes no response /
  shadow-mode stage of the rollout" claims become false — describing the acted
  behavior (the error path arms the marker; a matched repeat stall passes through and
  logs `chat_retry_passthrough`), while keeping the degraded-tool predicate nuance
  (never fires for a tool call seen on the wire); the exhaustiveness rule.
- `doc/configuration.html#env-vars` — the `PROXY_CHAT_RETRY_NUDGE` row (default text;
  empty, whitespace-only, or >4096 chars = disabled) + the prose table copy.
- `README.md` — one clause in the chat-mode Limitations paragraph, **scoped to the
  predicate** ("a tool-bearing turn whose stream ends in a colon with no tool call is
  closed with a retryable error and its continuation retried with an injected nudge" —
  not a blanket "a stalled turn"), plus the `PROXY_CHAT_RETRY_NUDGE` row in the Server
  environment variables table (parity with the other `PROXY_*` variables; this is the
  user-facing kill switch).
- `CLAUDE.md` — the env table row + one row in "Moved out of this section"; **and the
  deferred-issue closeout when the predicate lands**: flag it to the user first (global
  rule — never silently delete) and, on approval, remove the
  `unfinished-turn-detector-ignores-degraded-tool` entry from the Unresolved Deferred
  Issues JSON, change "Thirteen deferred issues remain" to "Twelve", and rewrite the
  Future Work clause that names this issue as inherited/unresolved.
- `doc/test-catalog.html` — recount against the landed suite, add the new entries, AND
  update invalidated existing entries: at minimum
  `test_chat_sse_unfinished_turn_shadow_logged`'s "log-only … changes no response"
  description (rewritten or retired per Guidance for Tester). **This reconciliation
  lands in the same (final squashed) commit as the test additions** — the plan's commit
  is a single per-plan squash, which is what satisfies the catalog's same-commit rule
  across the tester/planner lane split (post-implementation mega-audit finding 11).
- **Deferred-issue retirement:** `./tmp/reports/defer-issue-unfinished-turn-detector-ignores-degraded-tool.json`
  still exists while the Issue Log row is `Resolved` — correct per the lifecycle
  (presence = open; deletion is the close) but the retirement must be **scheduled**:
  `/update-and-commit` Step 9.6 deletes it when it processes the Resolved row
  (post-implementation mega-audit finding 13). The CLAUDE.md closeout (flag first,
  then remove the JSON entry and change "Thirteen" → "Twelve") is enumerated above.
- Spot-check `doc/architecture.html` and `doc/content.html` at sync time — not
  enumerated above, but architecture.html may reference the detector or the chat SSE
  dispositions.

**Step scripts (already authored and dry-run — they fail cleanly pre-implementation):**
`./tmp/verification/2026-10-05-chat-retry-nudge-step1.py` (steps 1–3: settings field
incl. whitespace/oversize forms, store helpers via direct import incl. consume-on-match,
TTL-at-arm and lock discipline, AST threading) and `-step2.py` (step 4: predicate
clause, drain truthiness, arm-gated/error ordering, no `message_delta` on the new path,
drain-event single logging, analyzer filter tuple). The pin the coder could get wrong:
arm before the error write.

## Repo Mode

Public

## Document Overrides

| Document | Rule Overridden | Reason |
|----------|----------------|--------|
| — | — | — |

## Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| False positive: a legit final turn ends with `":"` | One wasted upstream generation; the nudge-injected retry could alter a legit continuation | Measured precision 19/19; the predicate requires tools declared, no tool call on the wire, and a colon-ending tail; a resolving retry ends as `end_turn`; `PROXY_CHAT_RETRY_NUDGE=""` disables instantly |
| Client's recovery request never matches the marker | User sees a retryable error instead of a silent stall (no worse than today; no nudge delivered) | The documented/observed recovery strictly extends the conversation, which the prefix branch matches; the TTL is anchored at **arm** (180 s from the error, not from the request start — a long generation cannot expire its own marker); `-p` runs also auto-continue (up to 3×); an interactive `continue` slower than the TTL misses the nudge and errors again — friction equal to today's nudge, now with an explanatory error; rollback is one env var |
| Marker matches a non-retry — same body re-sent, or **two conversations sharing an identical strict prefix** (e.g. the same launch prompt relaunched within the TTL) | Nudge injected into a fresh/other request (operator-authored text only); the other conversation's own stall would pass through instead of erroring | Match requires an *armed* entry (set only when that conversation was errored), a **strict** extension (`len(new) > len(stored)`), TTL 180 s from arm, cap 32 (unarmed evicted first), and the entry is **consumed on match** (single-use); the cross-prefix residual is accepted and bounded |
| Consecutive user-role messages upstream (nudge appended after a user turn) | Some providers could reject or merge | The transform stays the single mapping authority (it emits one message per source message — no merging, so the shape is real at the wire); covered by the tester's upstream-body assertions; chat backends generally accept consecutive user turns — revisit if a provider 400s |
| Store memory (messages JSON per entry) | Bounded: 32 entries × ≤1 MiB; ordinary chat+tools traffic is retained in process memory up to 180 s | Per-entry size cap skips oversized conversations; nothing logs, serves, or errors with the stored JSON (no leak path — posture note documented in the provider-modes update); the store is not persisted and clears on restart |
| Oversized or malformed-messages conversations | Never nudged AND never errored — behavior degrades to today's passthrough | `_retry_nudge_remember` skips >1 MiB or non-list messages; the Step 4 error path requires `_retry_nudge_arm` to have succeeded — "cannot ever be nudged" implies "do not error" |
| In-memory marker lost to a proxy restart between the stall and the recovery | The recovery proceeds without a nudge (today's behavior; benign — the client already received the retryable signal) | In-memory by design; no persistence, no migration |
| Round stalls (the very failure under fix) | Coder rounds die mid-plan | Turn discipline in Guidance for Coder; a stall loses no applied edits |

## Rollback

Set `PROXY_CHAT_RETRY_NUDGE=""` (restart or relaunch) to disable erroring and nudging
in one step — the detector returns to a pure measurement: turns pass through to today's
terminal synthesis and `chat_sse_unfinished_turn` logging continues. Two deliberate
carve-outs survive the env-only rollback and require the code revert: the predicate's
`not tool_calls_seen` clause and the drain-mode truthiness alignment (both are bug
fixes, independent of the feature). A restart also clears in-memory markers (benign —
no user-visible effect). Code rollback: revert the plan's commit.

## Proposed Changes

1. **Step 1:** `settings.py` — `PROXY_CHAT_RETRY_NUDGE` → `SETTINGS.chat_retry_nudge`
   (empty/whitespace-only/>4096 chars = disabled; unset = default text).
2. **Step 2:** `server.py` — marker store: locked, capped request memory with
   `remember`/`arm`/`check` — consume-on-match, TTL anchored at arm, arm returns bool,
   eviction preserves armed entries, strict-extension prefix match; no-raise.
3. **Step 3:** `server.py` — wire it at request entry: remember/check for
   chat+tools requests; inject the nudge user message before the chat transform on a
   match and log `chat_retry_nudge` post-transform; thread `retry_original_id` (3
   signatures, 5 call sites) to the stream function.
4. **Step 4:** `server.py` — detector predicate gains `not tool_calls_seen`; drain
   seen-test aligned to truthiness; stale shadow comment replaced; on fire, the
   **arm-gated** error path (log drain, close blocks, write the retryable `api_error`,
   no terminal frames) or `chat_retry_passthrough` + normal terminal.
5. **Step 5:** `scripts/analyze_proxy_trace.py` — the two events (filter tuple +
   explicit branches) + the retry-recovery join with dangling/dedup accounting.
6. **Step 6:** run the planner's step scripts (exit 0 each).
7. **Step 7 (tester lane; added 2026-10-05 by user decision):** repair the three
   pre-existing Linux-conditional test defects — closed-stdin `communicate()`
   (`tests/_harness.py` + `tests/test_cli.py` sites; **done** in round 6),
   tier-routing double-bind (`_setup_tier_routing_test`), models.json chmod
   restore order (`tests/test_config_split.py`) — per their evidence reports, then
   re-run the affected modules and the full suite module-wise to a green baseline.
8. **Step 8 (coder lane; added 2026-10-05 after tester round 7):** `cli.py`
   `_write_state` — create the temp file in the **target's** directory
   (`os.path.dirname(PROXY_STATE_FILE) or "."`, with makedirs) instead of the
   hardcoded `PROXY_DIR`, mirroring `sinks.py:198`; makes the documented
   `PROXY_STATE_FILE` override work on any device (clears the 7 `test_cli`
   EXDEV failures). **Done** in coder round 8.
9. **Step 9 (coder lane; added 2026-10-05 after coder round 8):** `cli.py`'s
   localhost admin calls — `cmd_reload`'s POST (≈757-763) and `cmd_stop`'s
   shutdown POST (≈637-644) — must bypass ambient proxy env: route them through
   a proxy-less opener (`urllib.request.build_opener(urllib.request.ProxyHandler({}))`)
   so `HTTP_PROXY` with an empty `no_proxy` cannot send 127.0.0.1 admin traffic
   to an external proxy (403 on this box). No behavior change on proxy-free
   environments; Origin/CSRF handling unchanged.
10. **Step 10 (coder lane; added 2026-10-06 by the post-implementation
    mega-audit, findings 1/21):** thread the entry-time marker decision through
    re-entered forwards. Compute the `_retry_nudge_check` lookup **once at the true
    request entry** (`forward_request`, which wraps every re-entry call) and pass the
    result into `_forward_request_impl(...)` as an optional parameter that the compat
    probe (≈539), the reasoning walk (≈580), and the discovery retry (≈1059) forward
    unchanged; the entry wiring honors a non-None parent value instead of re-calling
    `_retry_nudge_check` (mirroring how `reasoning_selection` is injected and never
    re-resolved). Restores the loop guard across re-entries (a stalled walk attempt of
    a recovery passes through instead of being errored a second time) and the nudge
    re-injection on every rebuilt upstream body.
11. **Step 11 (coder lane; added 2026-10-06 by the post-implementation
    mega-audit, findings 2/14/15):** (a) `_retry_nudge_sweep` age-expires **armed**
    entries only — unarmed entries survive the sweep (cap-bounded), so a generation
    longer than the TTL cannot lose its own marker to a concurrent eligible request;
    update the `_retry_nudge_arm` docstring's freshness claim to match. (b) Reword the
    analyzer's `chat_retry_nudge` dedup comment (`scripts/analyze_proxy_trace.py:114-116`)
    to the cross-prefix rationale (finding 15) — no analyzer behavior change.
12. **Step 12 (coder lane; added 2026-10-06 by the Phase 6 review, Warning 1):**
    remove the ungated entry-time `_retry_nudge_check` block in `forward_request`
    (`src/claude_retry_proxy/server.py` ~515-529) — the check must run only inside
    `_forward_request_impl`'s eligibility gate (`mode == "chat" and tools_declared and
    SETTINGS.chat_retry_nudge`, ~839-844), where the mode/tools context exists and where
    the value already threads into every re-entry (Step 10). Step 10 added the entry
    block before it was known the gate's value reaches re-entries; it is now redundant
    **and harmful**: it consumes a matched marker for ANY request (a count_tokens call
    on the same conversation, a no-tools chat request, any mode) that structurally
    matches an armed entry, destroying the single-use marker without delivering the
    nudge or the loop guard — a plausible silent-miss path in the client's
    count-before-send flow. Update the comments to name the gate as the single
    resolution point.

## Immediate Actions

**Coder:**
- Round 16 (continued — **report only; one Write call, nothing else**): Step 12 is applied and verified in the tree — the ungated entry-time block is gone (`forward_request` calls `_forward_request_impl` with no marker argument), `_retry_nudge_check` remains only in the eligibility gate (~825), comments updated; verification green (both step scripts PASS, `chat_sse` 61/61, compile clean). **Do not re-run anything.**
  1. Write `./tmp/reports/2026-10-05-chat-retry-nudge-coder-2026-10-06.json` (canonical path — replaces the round-14 report; carry its Steps 10-11 summary forward): Steps 1-6 and 8-12 complete, `build_result: pass`, this round's verification results, files modified (`src/claude_retry_proxy/server.py`).
  2. Nothing else — no source edits, no test runs, no `tests/` touches.

**Tester (after the coder round):**
- Round 17: add `test_chat_retry_nudge_ineligible_request_does_not_consume` per the Guidance for Tester's Step 10-11 coverage block (arm a marker; the ineligible matching request must not consume it; the eligible recovery still nudges) and register it; then run the affected modules + the FULL module-wise suite (plain env, foreground, `./tmp/full_suite_final3.log`) — expect **379/379** — and write `./tmp/reports/2026-10-05-chat-retry-nudge-tester-2026-10-06.json` (canonical path — replace; carry the fixture-sweep record and the live-proxy deviation forward) with `overall_result: SUCCESS`.

## History

| Date | Event | Conclusion | Dismissed |
|------|-------|------------|-----------|
| 2026-10-05 | Initial plan | Implement the user-chosen Option A: error the unfinished turn with a retryable `api_error`, recognize the client's re-issue via a short-TTL marker, inject a config-texted nudge before the chat transform, pass through on a repeated stall; close the inherited `unfinished-turn-detector-ignores-degraded-tool` deferred issue. Evidence: `./tmp/research/2026-10-05-text-only-turn-stall-and-no-report.md` (19/19 detector precision; client re-issue confirmed). | — |
| 2026-10-05 | Evidence refinement (CC error-recovery semantics) | Verified against `https://code.claude.com/docs/en/errors.md` + specimen `067b9574`: the client recovers from a mid-stream error after a completed block by continuing the turn (non-interactive auto-continue up to 3× for text-but-no-tools; interactive needs a `continue`), issued as a conversation-extending request — matched by the marker's messages-prefix branch; the exact-hash branch is kept for version drift. Affects Summary, Step 2 wording, Tester test 1, Risks; no step-structure change. | — |
| 2026-10-05 | Pre-launch review fix (spec revision) | Step 1's env read switched from `_env_str` to `os.environ.get` — `_env_str` maps "set but empty" to the default, which made the documented `PROXY_CHAT_RETRY_NUDGE=""` kill switch (and the step's own verify) unsatisfiable as written; Step 3's call-site list extended to name the fifth site (~1388, `_stream_upstream_response` → `_stream_chat_sse_to_anthropic`) so all three functions' parameters are threaded at every call site. No other step affected. | — |
| 2026-10-05 | Mega-audit attempt 1 — aborted at pre-read (reader normalization) | Run wf_35cd662c-e27 failed `PLAN_READ_FAILED` / `LENGTH_MISMATCH`: the plan-reader (haiku) deterministically returned 19756 non-blank chars vs the file's 19757 (3/3 attempts; char-diff found two normalization edits — the count-affecting Summary `tool_calls` → `tool calls` and the count-neutral Step 4 `upstream` → `Upstream`). File unchanged; a production abort under the won't-fix's own reopen trigger → `plan-reader-transcription-fidelity` reopened (target claude-config) and filed. Trigger shape removed from the Summary text per the 2026-10-04 sweep plan's precedent (identifier backticked); audit relaunched. No design step changed. | — |
| 2026-10-05 | Mega-audit (iteration 1, 9 lenses) — report: [2026-10-05-chat-retry-nudge-mega-audit-2026-10-05](./tmp/reports/2026-10-05-chat-retry-nudge-mega-audit-2026-10-05.json) | 46 findings (4 High / 19 Medium / 23 Low), verdict "plan needs revision". All 4 High + 19 Medium fixed in place; all 23 Low also folded in. Headline fixes: (1) **marker had no consuming transition** — one armed entry matched every later turn of the conversation (stale nudges, silent passthroughs for genuine stalls, inflated Step 5 metric) → **consume-on-match** (single-use, with a third-request tester assertion); (2) **TTL anchored at request entry** — a long generation could expire its own marker before the arm → arm refreshes `stored_at`; (3) **error path errored when nothing could ever match** (oversized conversations) → **arm-gated error path** (no marker ⇒ passthrough); (4) **fixture sweep's "none collide" was false** — `test_chat_sse_unfinished_turn_shadow_logged` collides by construction → named as the one deliberate premise rewrite, with harness routing mandated to `_start_mode_proxy`; (5) **three doc pages' "log only / changes no response" claims** (provider-modes `#chat-sse-unfinished-turn` + table rows, trace-log row + prose, test-catalog entry) → enumerated; (6) **CLAUDE.md deferred-issue closeout** (JSON entry, "Thirteen"→"Twelve", Future Work clause) → added with the global flag-before-removal rule. Also folded: lock discipline pinned, threading counts unified to three signatures / five call sites, strict-extension prefix matching, no-clobber on re-entry, post-transform event logging, **drain seen-test truthiness** (`is not None` → truthy, matching its own documented contract), analyzer filter tuple + explicit branches + dangling/dedup accounting, whitespace/>4096 env forms disabled, `ProxySettings` naming, citation #6→#5, and the lost `unfinished-turn-detector-ignores-degraded-tool` report re-filed (reconstructed). **0 High remain — no re-iteration.** | Lows/hunches not actioned: [refactor-split-local-helpers-out-of-scope](./tmp/reports/2026-10-05-chat-retry-nudge-mega-audit-2026-10-05.json) (local helper extraction inside one function; nothing moves out of the file), [trace-event-inventory-unpinned](./tmp/reports/2026-10-05-chat-retry-nudge-mega-audit-2026-10-05.json), [step-scripts-gitignored-vs-committed](./tmp/reports/2026-10-05-chat-retry-nudge-mega-audit-2026-10-05.json) (sanctioned by the rule's own "plan-authored verification scripts" clause), [audit-informational-hunches](./tmp/reports/2026-10-05-chat-retry-nudge-mega-audit-2026-10-05.json), [audit-areas-not-fully-verified](./tmp/reports/2026-10-05-chat-retry-nudge-mega-audit-2026-10-05.json) (client recovery semantics, provider sentinel frequency, `saw_done` frequency, test-file read cap) |
| 2026-10-05 | Coder round 1 — stalled mid-Step-4, no report | Started 17:19:00, applied 17 edits, ended its turn 17:34:13 with `exit 0` and no session report (`Report: none written since launch`); `scripts/analyze_proxy_trace.py` untouched. Landed work verified: `step1.py` exit 0 (settings knob, full marker store, wiring, 3-signature/5-site threading); `log_drain()`/`log_post_finish_suppressed()` helpers created but the original inline sites not yet swapped (each literal appears twice); the drain seen-test truthiness edit landed. This is the plan's own stall failure mode — the round is exposed to the bug it fixes. `## Immediate Actions` regenerated with the exact residual list (outside `/update-plan`, per the truncation plan's precedent); round relaunched; applied edits survive the stall. | — |
| 2026-10-05 | Coder round 2 — SUCCESS | Report [coder-2026-10-05](./tmp/reports/2026-10-05-chat-retry-nudge-coder-2026-10-05.json): all 6 steps complete, `build_result: pass`, no issues filed; both step scripts independently re-run green by the planner. | — |
| 2026-10-05 | Tester round 1 — stalled before any edit, no report | Started 17:45:50, ran 15 min of reconnaissance (plan, server.py, tests, the runner, shadow-test/attribute-count greps, live-proxy status), ended its turn 18:00:21 with `exit 0` and no session report; `tests/` untouched (all mtimes pre-round). Same stall mode as coder round 1. Also recorded: the live proxy is not running (stale state since 10:01 today; encrypted keys ⇒ unattended rounds cannot start it) — the residual list records the deviation path. `## Immediate Actions` regenerated (Tester-only; coder directives dropped as stale); tester run relaunched. | — |
| 2026-10-05 | Tester round 2 — all test work landed, stalled before report | Started 18:03:04. Wrote all five tests + `ALL_TESTS` registrations, rewrote the shadow test away, updated the settings docstring, ran every new test standalone (one fix-and-rerun on test 1), ran the whole `chat_sse` module (59/59), then launched the full suite (376 tests) in the background and ended its turn 18:34:16 at Test 27/376 — the run was killed with the round (`tmp/full_suite_20261005.log` ends mid-run). No report. Transcript diagnosis: its last words were "I'll write the session report as soon as it completes" — the model believed a finished background task would re-invoke it; it does not (the `operate-round-ends-turn-before-waiting` deferred issue, target claude-config). `## Immediate Actions` regenerated; round relaunched. | — |
| 2026-10-05 | Tester round 3 — stalled before the suite run, no report | Started 18:35:19; re-verified the landed state, ran all five plan tests standalone green (transcript: "All five plan tests pass standalone"), then ended its turn 18:39:13 mid-sentence (`Running the revised settings-shape test:`) — no report, no suite run. Residual re-scoped to a stall-resistant method: module-wise foreground suite runs (all 17 modules are directly runnable; each run appends to `tmp/full_suite_round4.log`), evidence first, report last. `## Immediate Actions` regenerated; round relaunched. | — |
| 2026-10-05 | Tester round 4 — full module-wise suite evidence captured; killed at the 3600 s cap before the report | Started 18:41:56; swept fixtures, ran the five plan tests standalone green, then all 17 modules foreground (aggregator order) appending to `tmp/full_suite_round4.log`. **20 unique failures, all in unmodified plan-irrelevant code**, diagnosed as three pre-existing platform-conditional defects and filed: [communicate-closed-stdin](./tmp/reports/2026-10-05-chat-retry-nudge-preexisting-communicate-closed-stdin.json) (16 — test_config_keys ×6 + test_cli ×10; POSIX `communicate()` after a closed stdin raises `ValueError`; root c850941), [tier-routing-double-bind](./tmp/reports/2026-10-05-chat-retry-nudge-preexisting-tier-routing-double-bind.json) (3 — EADDRINUSE on Linux, reproduced twice; root c850941), [models-chmod-restore-order](./tmp/reports/2026-10-05-chat-retry-nudge-preexisting-models-chmod-restore-order.json) (1 — chmod restored before the assertion; root d0fd1b8). Every plan-relevant module green (`chat_sse` 59/59, `settings` 4/4, `docs` 11/11). Killed 19:41:56 (`timeout: killed after 3600s`) while extracting module results for the session report; no session report. Residual: the report alone. Historical green baselines were Windows-produced; this box is Linux. | — |
| 2026-10-05 | Tester round 5 — SUCCESS (report-only) | Report [tester-2026-10-05](./tmp/reports/2026-10-05-chat-retry-nudge-tester-2026-10-05.json): `overall_result: FAILURE` — 356/376 with all 20 failures pre-existing and attributed to the three `preexisting-*` reports; plan-relevant modules green (`chat_sse` 59/59 incl. the five plan tests, `settings` 4/4, `docs` 11/11); fixture sweep re-run for the record (only collision was the retired shadow test; no other fixture collides); both step scripts re-run PASS. It also corrected a planner directive detail (the log's second result block is `test_unit`, not a settings standalone run). | — |
| 2026-10-05 | Spec revision (/update-plan) | Processed the tester's round-5 report. No plan-body change: the three pre-existing Linux-only suite defects ([communicate-closed-stdin](./tmp/reports/defer-issue-communicate-closed-stdin.json), [tier-routing-double-bind](./tmp/reports/defer-issue-tier-routing-double-bind.json), [models-chmod-restore-order](./tmp/reports/defer-issue-models-chmod-restore-order.json)) were **deferred by the user's decision (2026-10-05)** — re-filed as defer-issue reports and logged as Deferred rows; the inherited [unfinished-turn-detector-ignores-degraded-tool](./tmp/reports/defer-issue-unfinished-turn-detector-ignores-degraded-tool.json) is **Resolved** (predicate change landed, pinned by `test_chat_sse_unfinished_turn_predicate_ignores_degraded_tool`). Deferrals normalized to `Deferred` status. `verification_scripts` metadata extended with the fixture-sweep script. No in-scope issues remain → finalize path (Phase 6). | — |
| 2026-10-05 | Spec revision (/update-plan) — user-directed un-defer (scope expansion) | Phase 6's prerequisite (a tester report with `overall_result: SUCCESS`) cannot be met while the 20 pre-existing Linux-only failures are deferred, and tester doctrine forbids declaring success with non-skipped failures — presented to the user, who chose **"fix the defects now"**. The three defer-issue records were retired (presence = open, so the files were deleted) and their Issue Log rows flipped to **Open**; the repairs are the new **Step 7** assigned to the tester lane (`tester_files` extended by five test files). Originating plans verified COMPLETED-green (253/253 on 2026-09-02; all-steps on 2026-09-24), so these are platform-conditional tests, not regressions. Next: one tester round on `--timeout 7200` (the 3600 s default killed round 4 mid-report) doing fixes + the full module-wise suite + the report, then Phase 6. | — |
| 2026-10-05 | Tester round 6 — closed-stdin fix applied, stalled before the rest | Launched 21:23:24 (7200 s cap). In 9 minutes: read the plan + evidence reports, located every stdin-close/communicate site, verified the subprocess flush behavior and the passphrase-pipe protocol in `cli.py`/`keys.py`, then applied the fix — a new shared `_close_child_stdin(proc, line=None)` in `tests/_harness.py` (write line → close → `proc.stdin = None`, so a later `communicate()` cannot flush a closed handle) with all five harness sites and both `test_cli.py` sites swapped. Both files compile; the remaining `stdin.close()` sites (test_trace, test_retry_streaming) were already green in the module runs and need no change. Ended its turn 21:32:38 mid-flow: no report, tier-routing and chmod fixes unstarted. Residual regenerated; round relaunched. | — |
| 2026-10-05 | Tester round 7 — stdin fix verified, EXDEV defect discovered; stalled mid-work | Launched 21:33:45 (7200 s cap). `test_config_keys` **17/17** (stdin fix verified); `test_cli` 10/17 — the remaining 7 fail on a newly diagnosed defect: `cli.py`'s `_write_state` creates its temp file in `~/.claude/proxy` and `os.replace`s onto `PROXY_STATE_FILE`, which is cross-device (EXDEV) when the per-run test state path is under `/tmp` → report [preexisting-cli-state-exdev](./tmp/reports/2026-10-05-chat-retry-nudge-preexisting-cli-state-exdev.json). It also cleaned orphaned test proxies and inert leftover state files from earlier killed rounds, and corrected `%TEMP%` comments in `tests/_harness.py`. Ended its turn 21:54:52: no report; tier-routing and chmod fixes unstarted. | — |
| 2026-10-05 | Spec revision (/update-plan) — Step 8 added (src-side EXDEV fix) | Round 7's discovery is source-side (`cli.py`), so the fix is the new **Step 8** in the coder lane (`coder_files` extended with `src/claude_retry_proxy/cli.py`); the plan-unanticipated discovery is treated as in-scope under the user's standing "fix the defects now" direction — the final diff still goes through the Phase 6 approval gate. Next: coder round 8, then a tester round finishing Step 7's remaining two fixes + the full suite. Counters: `steps_changed` 2, `files_changed` 6. | — |
| 2026-10-05 | Coder round 8 — SUCCESS (Step 8: EXDEV fix; third cause uncovered) | Report [coder-2026-10-05](./tmp/reports/2026-10-05-chat-retry-nudge-coder-2026-10-05.json) (same-day path, supersedes round 2 with its summary carried forward): `build_result: pass`; Step 8 applied exactly as specified (temp file in the target's directory, comment citing `sinks.py:198`; `os.replace` and cleanup byte-unchanged). Verified: step scripts pass; `test_cli` 14/17 plain — all 7 EXDEV failures cleared — with the 3 remainder root-caused to a **third layered cause**: this box's `HTTP_PROXY=http://localhost:3128` + empty `no_proxy` makes urllib route the CLI's localhost admin POSTs through the sandbox proxy → 403; proven by `-t cli-reload` FAIL plain / PASS with `no_proxy`, and 17/17 with it neutralized. Filed [preexisting-cli-admin-urllib-proxy-403](./tmp/reports/2026-10-05-chat-retry-nudge-preexisting-cli-admin-urllib-proxy-403.json) with a planner decision requested. | — |
| 2026-10-05 | Spec revision (/update-plan) — Step 9 added (localhost admin proxy bypass) | Chose the report's **product-side** form (b): localhost admin traffic must never be delegated to an ambient proxy — the robust answer, a small mechanical change in `cli.py` (already in `coder_files`), and it makes the tests' existing correct expectation pass without test-side env hacks. New **Step 9** (coder lane). Next: coder round 9 (fix + plain-env `test_cli` 17/17), then the tester's final round (Step 7 remainder + full suite + SUCCESS report). Counters: `steps_changed` 3, `files_changed` 6. | — |
| 2026-10-05 | Coder round 9 — Step 9 applied and verified green; stalled before the report | Launched 22:15:30. Applied `_LOCAL_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))` module-level in `cli.py`, used at `cmd_stop`'s shutdown POST and `cmd_reload`; step scripts PASS; plain-env runs **`test_cli` 17/17** and **`test_config_keys` 17/17**, no FAILED lines; stray-process sweep clean. Ended its turn 22:27:21 with "Now updating the coder session report" as its last line — no report. Residual: the report update alone (round 10 re-verifies and writes it). | — |
| 2026-10-05 | Coder round 10 — stalled in reconnaissance (1 minute) | Launched 22:28:26; read the plan/report, checked the tree and the proxy env snapshot, exited 22:29:30 with no work applied and no report. Residual narrowed to a one-Write report update (the re-runs are redundant — the tester's final full-suite round re-verifies end-to-end). | — |
| 2026-10-05 | Coder round 11 — SUCCESS (report edit) | Report updated in place (22:32): Step 9 added to `steps_completed`, `build_result: pass`, the supersession note and rounds 1-8 summary carried forward. **Coder lane complete**: Steps 1-6, 8, 9. | — |
| 2026-10-05 | Tester round 12 — final two fixes applied and verified; stalled before the full suite | Launched 22:32:43. Made `_setup_tier_routing_test` tolerate the caller's pre-bound listener and moved the chmod-0000 restore after the assertion; ran both affected modules: **`test_tier_routing` 11/11**, **`test_config_split` 10/10** — the last two previously-failing modules now green. Ended its turn 22:41:55 one step short of the full suite; no report. Residual: the full module-wise suite + the report. | — |
| 2026-10-05 | Tester round 13 — SUCCESS: the full suite is green | Report [tester-2026-10-05](./tmp/reports/2026-10-05-chat-retry-nudge-tester-2026-10-05.json): **`overall_result: SUCCESS`** — **376/376 passed, 0 failed, 0 skipped**, all 17 modules exit 0, zero FAILED lines (`./tmp/full_suite_final.log`, plain environment, no `no_proxy` override). Every repaired module green: `test_config_keys` 17/17, `test_cli` 17/17, `test_tier_routing` 11/11, `test_config_split` 10/10 — the round-5 baseline's 20 failures fully cleared. The five fixes are documented with their sites; the fixture-sweep record and the live-proxy deviation are carried forward. | — |
| 2026-10-05 | Spec revision (/update-plan) | Round-13 report processed: all five pre-existing-defect issues flipped to **Resolved** (tester, 2026-10-05). Counters: `issues_resolved` 6 / `steps_changed` 3 / `files_changed` 6 — the audit trigger fires (≥3 resolved AND ≥3 steps changed) → the post-implementation mega-audit runs in this `/update-plan` session (report `-r2` per the same-date dedup rule). | — |
| 2026-10-06 | Mega-audit (post-implementation, 10 lenses) — report: [mega-audit-r2](./tmp/reports/2026-10-05-chat-retry-nudge-mega-audit-2026-10-05-r2.json) | 23 findings — **0 High** / 12 Medium / 11 Low, verdict "Issues found — non-blocking" (0 High ⇒ no re-iteration; counters reset). All 12 Mediums processed: **two code defects become Steps 10-11** — the marker decision is lost on re-entered forwards (findings 1/21: the loop guard is defeated and the nudge dropped from rebuilt bodies on the compat/reasoning walk path) and the sweep age-expires unarmed entries (findings 2/14: a long generation loses its own marker to any concurrent eligible request, silently disengaging the feature); plan-text syncs applied — Guidance for Coder files list + "No other source file changes" scoped to Steps 1-6 (8/16), `tester_files` trimmed to the five files actually modified (5/9), Step 6's "only step scripts" reworded + the fixture-sweep path named (10/18), the same-commit statement for the catalog reconciliation (11), the deferred-issue retirement scheduled for /update-and-commit Step 9.6 (13), Step 2's sweep spec aligned to Step 11 (14), Step 5's dedup rationale reworded (15). **Coverage gap:** 3 lenses failed on upstream stream errors (edge-case-explorer, boundary-checker, test-impact) — the audit hard cap (1 per /update-plan) allows no re-run this session. Next: coder round 14 (Steps 10-11), then tester round 15 (the two coverage tests, the `_harness.py:47-56` comment fix, the full suite), then another /update-plan. | Lows acknowledged: [3](./tmp/reports/2026-10-05-chat-retry-nudge-mega-audit-2026-10-05-r2.json) fixture-sweep exit contract, [4](./tmp/reports/2026-10-05-chat-retry-nudge-mega-audit-2026-10-05-r2.json) stale `_harness.py` comment (folded into round 15), [5](./tmp/reports/2026-10-05-chat-retry-nudge-mega-audit-2026-10-05-r2.json) modified-files list (resolved by the tester_files trim), [6/7/22/23](./tmp/reports/2026-10-05-chat-retry-nudge-mega-audit-2026-10-05-r2.json) verification notes and accepted residuals, [12](./tmp/reports/2026-10-05-chat-retry-nudge-mega-audit-2026-10-05-r2.json) doc pass (executed in Phase 6, same session), [17/18/19/20](./tmp/reports/2026-10-05-chat-retry-nudge-mega-audit-2026-10-05-r2.json) plan-text drift (Immediate Actions regenerated; History reordered; stale line-number authorities acknowledged as historical) |
| 2026-10-06 | Coder round 14 — audit fixes (Steps 10-11) applied and verified green; stalled before the report | Launched 00:05:05. Implemented Step 10 (entry-time `retry_original_id` computed once in `forward_request` ~527-534, threaded through `_forward_request_impl` ~704 honoring a non-None parent at ~841-844, and forwarded by both re-entry helpers ~566/~612) and Step 11 (`_retry_nudge_sweep` age-expires armed entries only ~137-139 with the docstring updated; the analyzer dedup comment reworded ~114; the step-1 script's unarmed-TTL pin updated to the superseded-rule replacement). Verification green: both step scripts PASS, `chat_sse` **59/59**, compile clean. Ended its turn 00:26:04 with "Writing the session report" as its last line — no report. Residual: the report alone. | — |
| 2026-10-06 | Tester round 15 — SUCCESS: audit coverage landed, the suite is green at 378 | Report [tester-2026-10-06](./tmp/reports/2026-10-05-chat-retry-nudge-tester-2026-10-06.json): **`overall_result: SUCCESS`** — **378/378 passed, 0 failed, 0 skipped**, zero FAILED lines (`./tmp/full_suite_final2.log`, plain environment). Both audit-coverage tests landed and pass: `test_chat_sse_nudge_reentry_walk_stall_passthrough` (the loop guard holds across a re-entered walk and the nudge survives in the served upstream body — findings 1/21) and `test_chat_retry_nudge_sweep_expires_armed_only` (the production sweep ordering — findings 2/14). The `_harness.py:47-56` isolation comment was corrected. Steps 10-11 verified end-to-end; no in-scope issues remain → Phase 6 finalize path. | — |
| 2026-10-06 | Review (Phase 6 quality gate) — report: [review-2026-10-06](./tmp/reports/2026-10-05-chat-retry-nudge-review-2026-10-06.json) | Verdict: **issues found — non-blocking, 0 Critical** (2 Warning / 4 Suggestion) → the commit gate passes. The reviewer independently re-ran the step scripts, the fixture sweep, `py_compile`, and both Step 10-11 tests (all pass) and verified the threading, log-helper extraction, lock discipline, arm-gate ordering, consume-on-match, and the armed-only sweep against the plan. **Warning 1** (the ungated entry-time `_retry_nudge_check` consumes markers on ineligible matches) → **fixed**: new **Step 12** (the check moves wholly into the eligibility gate) plus a tester pin — the fix is a small, spec-aligned removal. **Warning 2** (the harness's per-run state file was relocated into `~/.claude/proxy` by an earlier round, unenumerated; three doc lines still say `%TEMP%`) → relocation **kept** (functional; the PID-keyed name separates it from the live file; reverting would cost a re-verified round for no functional gain) and the stale doc lines are corrected in this plan's doc pass. | Suggestions deferred: [s1](./tmp/reports/2026-10-05-chat-retry-nudge-review-2026-10-06.json) default-on duplicate body parse on the hot path, [s2](./tmp/reports/2026-10-05-chat-retry-nudge-review-2026-10-06.json) entry check outside the inflight try/finally (moot after Step 12), [s3](./tmp/reports/2026-10-05-chat-retry-nudge-review-2026-10-06.json) the env disable-forms pinned only by the gitignored step script, [s4](./tmp/reports/2026-10-05-chat-retry-nudge-review-2026-10-06.json) the analyzer retry-recovery join has no committed test |
| 2026-10-06 | Coder round 16 — Step 12 (review fix) applied and verified green; stalled before the report | Launched 01:46:00. Removed the ungated entry-time marker block (`forward_request` calls `_forward_request_impl` with no marker argument; `_retry_nudge_check` now appears only in the eligibility gate at ~825) and updated the comments. Verification green: both step scripts PASS, `chat_sse` **61/61** (59 + the two round-15 tests), compile clean. Ended its turn 02:06:03 one step short of the report. Residual: the report alone. | — |
| 2026-10-06 | Coder round 16 (continued — report-only) — SUCCESS | Launched 02:07:00. Re-verified the Step 12 sites (the eligibility gate ~822-825; `_retry_nudge_check` resolves only there) and wrote the canonical report [coder-2026-10-06](./tmp/reports/2026-10-05-chat-retry-nudge-coder-2026-10-06.json) (02:08): Steps 1-6 and 8-12 complete, `build_result: pass`, verification results carried forward. **Coder lane complete.** | — |
| 2026-10-06 | Tester round 17 — SUCCESS: the Step 12 pin lands; the suite is green at 379 | Report [tester-2026-10-06](./tmp/reports/2026-10-05-chat-retry-nudge-tester-2026-10-06.json): **`overall_result: SUCCESS`** — **379/379 passed, 0 failed, 0 skipped**, all 17 modules foreground with zero FAILED lines (`./tmp/full_suite_final3.log`, plain environment). `test_chat_retry_nudge_ineligible_request_does_not_consume` proves the review's Warning-1 consumption path is gone — an ineligible strict-extension request leaves the marker intact and the eligible recovery still nudges (it fails against the pre-Step-12 tree). Both step scripts and the fixture sweep re-run PASS, the sweep's registration list extended to all eight plan-added tests. One assertion was corrected mid-round before the green run: the untouched-upstream check is a message-count plus nudge-marker-absence pin, not byte-equality — the chat transform maps content blocks to plain strings upstream, so the first form was the wrong instrument (the mechanism was never at fault). No issues filed; no tests skipped or removed. | — |
| 2026-10-06 | Focused re-review of the post-review delta (Step 12 + its pin) — report: [review-2026-10-06-r2](./tmp/reports/2026-10-05-chat-retry-nudge-review-2026-10-06-r2.json) | Verdict: **issues found — non-blocking** (0 Critical / 0 Warning / 2 Suggestion). Independently verified: **Step 12 fully closes Warning 1** (AST-confirmed single `_retry_nudge_check` call site inside the gate; every marker-consuming path accounted for — sweep expiry, cap eviction, and the check's own two consumption sites; `count_tokens` 400s *before* the gate; both re-entry helpers and the discovery retry only thread an inherited value; the `else` drop and the Step 10 threading hold) and **the new test is a genuine pre-Step-12 failure pin** (the load-bearing assertion is request 3's nudge count; the mid-round-corrected upstream check is non-vacuous — request 3's positive control proves the instrument detects an injected nudge). No dead code, no unused parameters, no regression. Re-ran: the new test standalone PASS, both step scripts PASS, the fixture sweep PASS, the suite log re-parsed to 379/379 across 17 modules. The re-review's second finding (metadata Step 10 string naming `forward_request`) is fixed in this revision — plan text is the planner's lane. | Deferred: the first finding — `_retry_nudge_check`'s docstring "(retry_original_id is computed once at request entry)" (server.py:233) still names the removed block's location; readability only (the substance — computed once, never re-resolved — remains true of the gate) and fixing it would invalidate the 379/379 verification evidence for a wording nit. |

## Plan Metadata

```json
{
  "plan_id": "2026-10-05-chat-retry-nudge",
  "steps": [
    "Step 1: settings.py — PROXY_CHAT_RETRY_NUDGE env knob (default text; empty/whitespace/>4096 disables)",
    "Step 2: server.py — the marker store (locked, capped, consume-on-match, TTL anchored at arm) with remember/arm/check",
    "Step 3: server.py — request-entry wiring: remember/check, nudge injection before the chat transform, post-transform chat_retry_nudge event, thread retry_original_id (3 signatures, 5 call sites)",
    "Step 4: server.py — the stream action: predicate gains not tool_calls_seen, drain seen-test truthiness, arm-gated error path (drain log first), chat_retry_passthrough otherwise",
    "Step 5: scripts/analyze_proxy_trace.py — the two new events (filter tuple + explicit branches) and the retry-recovery join with dangling/dedup accounting",
    "Step 6: run the planner's step scripts — exit 0 each",
    "Step 7 (tester): repair the three pre-existing Linux-conditional test defects (closed-stdin communicate, tier-routing double-bind, models.json chmod restore order) and re-run the suite to a green baseline",
    "Step 8 (coder): cli.py _write_state — temp file in the target's directory (same-device atomic replace; mirrors sinks.py:198)",
    "Step 9 (coder): cli.py localhost admin calls bypass ambient proxy env (proxy-less opener for cmd_reload/cmd_stop POSTs)",
    "Step 10 (coder; audit fix): thread the entry-time marker decision through re-entered forwards (resolved once per request — the eligibility gate, where Step 12 later moved it; passed into _forward_request_impl and the re-entry helpers)",
    "Step 11 (coder; audit fix): _retry_nudge_sweep age-expires armed entries only; reword the analyzer dedup comment",
    "Step 12 (coder; review fix): remove the ungated entry-time _retry_nudge_check; the check runs only in the eligibility gate"
  ],
  "coder_files": [
    "src/claude_retry_proxy/settings.py",
    "src/claude_retry_proxy/server.py",
    "scripts/analyze_proxy_trace.py",
    "src/claude_retry_proxy/cli.py"
  ],
  "tester_files": [
    "tests/test_chat_sse.py",
    "tests/test_settings.py",
    "tests/_harness.py",
    "tests/test_cli.py",
    "tests/test_config_split.py"
  ],
  "doc_files": [
    "doc/provider-modes.html",
    "doc/trace-log.html",
    "doc/configuration.html",
    "README.md",
    "CLAUDE.md",
    "doc/test-catalog.html"
  ],
  "verification_scripts": [
    "./tmp/verification/2026-10-05-chat-retry-nudge-step1.py",
    "./tmp/verification/2026-10-05-chat-retry-nudge-step2.py",
    "./tmp/verification/2026-10-05-chat-retry-nudge-fixture-sweep.py"
  ],
  "repo_mode": "Public",
  "document_overrides": []
}
```

## Audit Accumulation

*Counters reset when mega-audit runs. Used by Phase 5 entry trigger.*

| Counter | Value | Last Updated |
|---------|-------|--------------|
| issues_resolved_since_audit | 0 | 2026-10-06 |
| steps_changed_since_audit | 5 | 2026-10-06 |
| files_changed_since_audit | 2 | 2026-10-06 |

## Final Results

**Status: COMPLETED** — 2026-10-06.

### What shipped

The chat-mode unfinished-turn detector — until now a log-only shadow measurement — now acts.
When a turn declares tools, sees no tool call on the wire, emits no `tool_use` block, reports
`finish_reason: "stop"` and ends its text with a colon, the proxy closes the turn with a
retryable `api_error` (no terminal frames, the same wire disposition as a cut stream) instead of
letting it arrive as a quiet `end_turn`, and arms a single-use in-memory marker for the request.
The client's recovery — a byte-identical re-issue, or the conversation extended strictly past the
stored messages — consumes the marker and gets the nudge text appended as a trailing user message
to the **upstream copy only** (`chat_retry_nudge` logged post-transform; the client's bytes and
the client response never carry it). A recovery that stalls again is not errored a second time: it
logs `chat_retry_passthrough` and closes with the normal terminal synthesis — the loop guard. The
marker decision is resolved once per request and threaded through every re-entered forward (the
compat probe, the reasoning walk, the discovery retry). The store is bounded and in-process only:
32 entries × ≤1 MiB, TTL 180 s anchored at the error, armed-only age sweep, consumed on match,
never persisted, never logged, never served. `PROXY_CHAT_RETRY_NUDGE=""` is the kill switch — the
detector returns to a pure measurement (every fired turn passes through; the event keeps
logging). Two predicate bug fixes ship independently of the feature: the `not tool_calls_seen`
clause (a proxy-side tool-block degradation is no longer counted as a model omission — the
inherited `unfinished-turn-detector-ignores-degraded-tool` issue) and the drain seen-test
truthiness alignment. The analyzer gained the two events and the retry-recovery join with
dangling/dedup accounting.

Alongside the feature, the plan repaired **five pre-existing test-suite defects** that stood
between it and a green suite on Linux (Steps 7-9), each with an evidence report: closed-stdin
`communicate()` (16 tests), tier-routing double-bind (3), models.json chmod restore order (1),
`cli.py` `_write_state` cross-device temp file (7), and CLI localhost admin POSTs honoring
`HTTP_PROXY` (3).

### Files changed

| File | What |
|---|---|
| `src/claude_retry_proxy/settings.py` | `PROXY_CHAT_RETRY_NUDGE` → `SETTINGS.chat_retry_nudge` (default text; empty/whitespace/>4096 disables) |
| `src/claude_retry_proxy/server.py` | the marker store (locked, capped, consume-on-match, TTL at arm, armed-only sweep), the entry wiring (remember, gate-resolved check, nudge injection before the chat transform, post-transform `chat_retry_nudge`), `retry_original_id` threaded through 3 signatures / 5 call sites, the detector's `not tool_calls_seen` clause, the arm-gated error path and the `chat_retry_passthrough` loop guard |
| `scripts/analyze_proxy_trace.py` | the two new events (filter tuple + explicit dispatch branches) and the retry-recovery join with dangling/dedup accounting |
| `src/claude_retry_proxy/cli.py` | `_write_state` temp file beside its target (same-device atomic replace); `_LOCAL_OPENER` so localhost admin POSTs bypass ambient proxy env |
| `tests/test_chat_sse.py` | 8 tests added, 1 retired-in-place (the shadow test rewritten as the acted-behaviour pin) |
| `tests/test_settings.py`, `tests/_harness.py`, `tests/test_cli.py`, `tests/test_config_split.py` | the five pre-existing-defect repairs (`_close_child_stdin`, tolerant tier-routing bind, chmod restore order, per-run state path) |
| `doc/provider-modes.html` | `#chat-sse-unfinished-turn` rewritten to the acted behaviour (predicate, error path, marker/nudge/loop guard, store bounds, kill switch), the `stop` mapping-table row annotated, three `#degradation` event rows |
| `doc/trace-log.html` | `chat_retry_nudge` and `chat_retry_passthrough` registered, the `chat_sse_unfinished_turn` row and prose rewritten off the "log only / shadow-mode" claims |
| `doc/configuration.html` | the `PROXY_CHAT_RETRY_NUDGE` row and the note's exception to the ignore-and-default rule |
| `doc/test-catalog.html` | recounted to 379 / 62, 8 new entries, the retired shadow entry replaced, the state-path lines corrected |
| `README.md` | the chat-mode Limitations clause (scoped to the predicate) and the env-table row |
| `CLAUDE.md` | the env-table row, a "Moved out of this section" row, the stale `%TEMP%` state-path correction, and the deferred-issue closeout (pending user approval of the removal) |

### Test evidence

- **Tester round 17 (final):** **379/379 passed, 0 failed, 0 skipped**, all 17 modules foreground
  in a plain environment, zero `FAILED` lines — `./tmp/full_suite_final3.log`. Both step scripts
  and the fixture sweep re-run PASS; the sweep's registration list now pins all eight
  plan-added tests.
- Progression: round 13 **376/376** (after the five repairs), round 15 **378/378** (after the
  two audit-fix pins), round 17 **379/379** (the Step-12 pin).
- **Verification apparatus:** `./tmp/verification/2026-10-05-chat-retry-nudge-step1.py`,
  `-step2.py`, `-fixture-sweep.py` (dry-run proof included); each was re-run by the Phase 6
  reviewer, the delta re-reviewer, and the final tester round.
- **Doc gates:** `scripts/check_doc_anchors.py` PASS (175 anchors resolved, 8 files scanned, no
  secret shapes); `~/.claude/scripts/doc_structure_check.py` PASS (9 files); `test_docs` 11/11
  in-suite.
- **Known warning:** `No proxy_stop event in trace` on abrupt termination
  ([defer-issue-no-proxy-stop-trace-warning](./tmp/reports/defer-issue-no-proxy-stop-trace-warning.json)).

### Issues resolved

| Issue | Resolved by |
|---|---|
| [preexisting-cli-admin-urllib-proxy-403](./tmp/reports/2026-10-05-chat-retry-nudge-preexisting-cli-admin-urllib-proxy-403.json) | tester, 2026-10-05 |
| [preexisting-cli-state-exdev](./tmp/reports/2026-10-05-chat-retry-nudge-preexisting-cli-state-exdev.json) | tester, 2026-10-05 |
| [communicate-closed-stdin](./tmp/reports/2026-10-05-chat-retry-nudge-preexisting-communicate-closed-stdin.json) | tester, 2026-10-05 |
| [tier-routing-double-bind](./tmp/reports/2026-10-05-chat-retry-nudge-preexisting-tier-routing-double-bind.json) | tester, 2026-10-05 |
| [models-chmod-restore-order](./tmp/reports/2026-10-05-chat-retry-nudge-preexisting-models-chmod-restore-order.json) | tester, 2026-10-05 |
| [unfinished-turn-detector-ignores-degraded-tool](./tmp/reports/defer-issue-unfinished-turn-detector-ignores-degraded-tool.json) (inherited; report reconstructed 2026-10-05) | tester, 2026-10-05 |

### Deferred issues

Each is a completed disposition, cross-repo, and none blocks this plan.

- **[researcher-cannot-run-mega-audit](./tmp/reports/defer-issue-researcher-cannot-run-mega-audit.json)** (claude-config) — the
  researcher role cannot run the mega-audit workflow it is asked to operate.
- **[plan-reader-transcription-fidelity](./tmp/reports/defer-issue-plan-reader-transcription-fidelity.json)** (claude-config; reopened
  2026-10-05 when its documented reopen trigger fired) — the plan-reader normalizes text while
  transcribing plans (underscore→space, sentence-casing), tripping or silently evading the
  length gate.

### Post-implementation mega-audit

[mega-audit-r2](./tmp/reports/2026-10-05-chat-retry-nudge-mega-audit-2026-10-05-r2.json) — 23 findings (0 High / 12 Medium / 11 Low),
triggered by the round-13 counters. All 12 Mediums processed: **two code defects became Steps
10-11** (the marker decision lost on re-entered forwards; the sweep age-expiring unarmed entries)
with tester pins, the rest plan-text syncs. The 11 Lows are acknowledged in the History row.
**Coverage gap recorded:** three lenses (edge-case-explorer, boundary-checker, test-impact)
failed on upstream stream errors; the audit's hard cap (1 per `/update-plan`) allowed no re-run
this session.

### Phase 6 review

[review-2026-10-06](./tmp/reports/2026-10-05-chat-retry-nudge-review-2026-10-06.json) — **0 Critical / 2 Warning / 4 Suggestion**
(non-blocking; the commit gate passed). **Warning 1** (the ungated entry-time `_retry_nudge_check`
consumed markers for ineligible requests) → fixed as **Step 12** plus the
`test_chat_retry_nudge_ineligible_request_does_not_consume` pin — a pre-Step-12 failure pin, per
the delta re-review. **Warning 2** (the harness's per-run state file relocated into
`~/.claude/proxy` by an earlier round, unenumerated, with three doc lines still saying `%TEMP%`)
→ relocation kept (functional; the PID-keyed name separates it from the live file) and the doc
lines corrected in this plan's doc pass (`CLAUDE.md`, `doc/test-catalog.html`).

**Delta re-review:** [review-2026-10-06-r2](./tmp/reports/2026-10-05-chat-retry-nudge-review-2026-10-06-r2.json) — **0 Critical / 0 Warning / 2 Suggestion**. Independently confirmed that Step 12 fully closes Warning 1 and that the pin is genuine; no dead code or regression. Both Suggestions are wording residues: the metadata Step 10 string (fixed in the plan) and `_retry_nudge_check`'s docstring "at request entry" (`server.py:233`) — **deferred** (readability only; the substance remains true of the gate, and editing source would invalidate the 379/379 evidence for a wording nit).

**Four Suggestions deferred** (all from the Phase 6 review): the default-on hot-path duplicate
body parse; the entry check outside the inflight `try/finally` (moot after Step 12); the env
disable-forms pinned only by the gitignored step script; the analyzer retry-recovery join without
a committed test.

### Known caveats

- The nudge's effect on a retried generation is not itself measured — only the predicate's
  precision was (19/19 on the plan's sample). The kill switch is the mitigation.
- The cross-prefix residual (two conversations sharing an identical strict prefix within the
  180 s window) is accepted and bounded in the Risks table.
- The doc pass ran after the Phase 6 review; its changes are enumerated above and were validated
  by both doc gates.
