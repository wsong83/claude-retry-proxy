# Plan: Learn the per-provider reasoning-echo field instead of sending both
**Project:** D:\proj\claude-retry-proxy
**Plan ID:** 2026-09-29-chat-reasoning-field-learner
**Created:** 2026-09-29

## Issue Log

Rows ordered newest-first (latest issues at top). New issues are prepended; resolved issues stay in place with updated status.

| Issue | Status | Found | Resolved | Resolved By |
|-------|--------|-------|----------|-------------|
| [dead-compat-feature-mode-constant](./tmp/reports/2026-09-29-chat-reasoning-field-learner-dead-compat-feature-mode-constant.json) | Resolved | 2026-09-30 | 2026-09-30 | coder (Step 7) — **deleted.** `COMPAT_FEATURE_MODE` was dead code *and* a second declaration of the learner's mode scope, which the registry now owns via the `context_management` descriptor. It had been raised as a Low by **all three** mega-audit rounds without a revision ever dispositioning it; the coder filed it after Step 5, and Step 7 removed it (verified: `grep -rn COMPAT_FEATURE_MODE src/` returns nothing). `doc/compatibility.html:62-65` still lists it and **must lose that entry in the sweep** — see Guidance for Planner |
| [unused-compat-imports-server](./tmp/reports/2026-09-29-chat-reasoning-field-learner-unused-compat-imports-server.json) | Resolved | 2026-09-30 | 2026-09-30 | reviewer — **invalid as filed.** Its premise ("no such consumer was found in src/ or tests/") is wrong. The three names are deliberate re-exports the suite consumes *through the server module*: `tests/test_compat.py:1145-1146` asserts `hasattr(srv, "_compat_state_lock")`, `:1177` asserts the alias identity against `_state.lock`, `:1266` calls `srv._compat_normalize_threshold(value)`, and `:1296` calls `srv._persist_compat_state_locked()`. Removing them as the issue proposes would break four test assertions. Left importable, with this row as the record of why |
| [client-body-recursionerror-no-response](./tmp/reports/2026-09-29-chat-reasoning-field-learner-review-2026-09-30.json) | Open | 2026-09-30 | — | — (pre-existing, surfaced by the code review: `json.loads(body)` at `server.py:603` is guarded by `(JSONDecodeError, UnicodeDecodeError, ValueError)` only, so a `RecursionError` from a deeply nested **client** body escapes `_forward_request_impl` — and `forward_request` calls it unguarded while `do_POST` has no outer `try`, so the request aborts with no HTTP response. The same narrow guard recurs at `:517`, `:1122`, `:1265` and `compat.py:787`. This is the identical failure the plan hardened the *upstream*-body parse against (`_compat_guarded_parse`), left unfixed on the client path — which now also feeds the new `_reasoning_present` gate. Shared fix; deferred rather than folded in) |
| [image-content-blocks-chat-mode](./tmp/reports/defer-issue-image-content-blocks-chat-mode.json) | Open | 2026-08-29 | — | — (pre-existing deferred issue; this plan modifies `transforms_chat.py` but does NOT fold it in — different concern, see Summary) |
| [no-proxy-stop-trace-warning](./tmp/reports/defer-issue-no-proxy-stop-trace-warning.json) | Open | 2026-09-14 | — | — (pre-existing deferred issue; untouched by this plan) |
| [proxy-stderr-append-stale-tail](./tmp/reports/defer-issue-proxy-stderr-append-stale-tail.json) | Open | 2026-09-18 | — | — (pre-existing deferred issue; this plan adds one more stderr warning line to that file, which does not change the issue's substance) |
| [port-default-collision-hazard](./tmp/reports/defer-issue-port-default-collision-hazard.json) | Open | 2026-09-18 | — | — (pre-existing deferred issue; untouched by this plan) |
| [extract-model-raises-on-non-object-json](./tmp/reports/defer-issue-extract-model-raises-on-non-object-json.json) | Open | 2026-09-12 | — | — (pre-existing deferred issue; untouched by this plan) |

## Guidance for Coder

**Files to modify:**
- `src/claude_retry_proxy/compat.py`
- `src/claude_retry_proxy/transforms_chat.py`
- `src/claude_retry_proxy/server.py`

The coder NEVER writes tests — all test changes are in Guidance for Tester. The coder does not rename or update any test function.

**Constraints:**
- `context_management` behaviour must not change. **No existing compat test may need changes beyond those enumerated in Guidance for Tester** — that list is the whole licence to touch that suite, and the coder changes no test file at all. In particular `COMPAT_MAX_RETRIES_PER_REQUEST` stays 1 for it.
- The reasoning feature must NOT call `_compat_suppressed`, `_compat_note_suppressed_request`, `_compat_record_failed_confirmation`, `_compat_learn`, or any other `context_management` probe/threshold/learn helper. Those read and write `context_management`'s state, hardcode its constants, and construct its fixed entry field set; the two policies share only the storage envelope and the persistence/lock plumbing. `_compat_learn` is the seductive one — it early-returns `(entry, False)` ("already learned") when an entry exists, so a revision through it is a silent no-op, and its first-persist path builds a `context_management`-shaped field set with no `selection`. The reasoning descriptor owns its own learn/switch persistence, which {updates an existing entry rather than early-returning, and writes `selection` in its own field set}.
- Never copy upstream error text into state keys, entry fields, trace fields, **or stderr**. Upstream text is only ever matched against patterns built from our own constants (`compat.py:35-37`), and stderr is a redaction chokepoint (`sanitize.py:1`, restated in `CLAUDE.md`): `proxy-stderr.log` is plaintext, append-only, and not covered by the sinks' POSIX-only `chmod`, so any interpolated exception text goes through `sanitize_error` (`compat.py:186-188` is the precedent) and the latch warning carries metadata only.
- Do not add an import from `transforms_chat.py` to `compat.py`. The selection reaches the transform as a parameter.
- Keep `COMPAT_FEATURE = "context_management"` importable — `server.py:36` imports it and the existing trace events emit it.
- `_reasoning_present` and `_reasoning_complaint_match` must be **total**: they may never raise. This is an **exception contract, not a shape to mirror**: the guarded parse must catch `Exception` (or at least name `json.JSONDecodeError`, `UnicodeDecodeError`, `ValueError`, **and `RecursionError`** — which is not a `ValueError` and which `json.loads` raises on deeply nested input). `_compat_rejection_match` (`compat.py:529-546`) catches only the first three; copying it verbatim would leave the stated property false. The call-site family is unguarded (`server.py:689`), `forward_request` is invoked unguarded (`server.py:2405`), and `do_POST` has no outer `try`, so an escape aborts the request with no HTTP response. Extract that guarded parse as **one shared total helper used by both matchers** — the exception contract is what is shared, not the shape. `_compat_rejection_match` carries the same crash surface today (`compat.py:536-543`), and hardening only the new matcher would leave the anthropic path exposed to the identical input. For well-formed bodies nothing changes, so the "no existing compat test may need changes" constraint still holds; the only behavioural difference is on a body that currently aborts a request with no response, and it moves in the fail-open direction the module already documents.
- The same totality clause applies to each descriptor's **entry validator** (Step 1): it returns `None` for anything it cannot validate and never raises. Entry text comes from a file that can be hand-edited, restored from a backup, or written by another version, and `_load_compat_state` is called at `server.py:2601` — before `sys.stderr` is wrapped at `server.py:2643` — so a raising validator converts the documented fail-open policy into an unhandled startup crash.

## Guidance for Tester

**Suite registration (applies to every test below).** The suite has no auto-discovery: `run_cli(all_tests)` (`tests/_harness.py:1242`) executes exactly the list it is given, `--test` uses that list as argparse `choices`, and the aggregator concatenates each module's `ALL_TESTS` (`tests/test_claude_proxy.py:28-46`). Append one row per new test to `tests/test_compat.py`'s `ALL_TESTS` (starts `:2483`) and the new case to `tests/test_chat_transform.py`'s (`starts :1348`), then confirm the suite total rises by the number of tests added. An unregistered test silently never runs, which makes every "the test passes" verify step below green while proving nothing.

**Tests to update (in-place, keep existing names):**
- **Permanent:** `tests/test_chat_transform.py` pins the removed dual write in the request-direction transform. The sites named in earlier revisions (L42, L72, L101, L291, L626) are illustrative, **not exhaustive** — grep the file for both field names and update every request-direction site to the **new default only** (no reasoning field). Do **not** add one case per selection at those sites: `test_chat_transform_emits_only_selected_field` owns the whole selection matrix, and pinning it twice only guarantees the two copies drift.
- **Permanent:** `tests/test_compat.py:80-83` `ALLOWED_STATE_KEYS` and its consumer at `:740` (`extra = set(entry) - ALLOWED_STATE_KEYS`, inside the metadata-only state test, which iterates every entry across every feature with no filter). The invariant that assertion pins — "the state file carries only `context_management`'s key set, ever" — is exactly the invariant this plan changes. Make it per-feature (a `feature -> key set` mapping; the reasoning entry adds exactly `selection`) rather than a flat set, and keep the assertion firing.
- **Permanent:** `test_compat_state_roundtrip` (`tests/test_compat.py:384`) becomes descriptor-parameterized — a `context_management` entry, a `reasoning_field` entry, and an absent entry resolving to the descriptor's default — instead of gaining a `test_reasoning_selection_survives_reload` sibling. It already asserts that a persisted entry round-trips and its behaviour resumes immediately; what is genuinely new is only the per-descriptor validation branch.
- **Permanent:** `test_compat_single_retry_global` (`tests/test_compat.py:2097-2154`) gains the reasoning assertions — no counter mutated, persisted selection unchanged — instead of a `test_reasoning_retry_under_lock_contention` sibling. Its fixture is a multi-second concurrency harness that already drives 5 concurrent requests against a held lock; a sibling pays for that fixture again to add one assertion.
- **Permanent:** any other `tests/test_compat.py` case constructing an entry literal directly, if the envelope gains a per-descriptor field set. Update in place; do not delete.

**Tests to create:**
Module assignment: every test below is added to `tests/test_compat.py`, except `test_chat_transform_emits_only_selected_field`, which is added to `tests/test_chat_transform.py` (and the temporary end-to-end test, which goes where the tester's mock-upstream harness fits best).

Harness: these are the first **chat-mode** tests in `tests/test_compat.py`, whose own fixtures are anthropic-mode. Use the shared `_start_mode_proxy(tiers, vendors, responders=…)` from `tests/_harness.py` with a `{"mode": "chat"}` vendor — `tests/test_chat_sse.py:42-55` is the working precedent — plus a stateful responder that returns the complaint for the first N requests and 2xx afterwards.

Assertion channel: the counter and the latch are in-memory **inside the spawned proxy process**, so the test process cannot read them. Assert on what is observable: the HTTP result the client receives, the trace events, and the persisted selection read back from the compat state file (whose path the suite isolates per test). Express "the counter survived the walk" as the three-complaint sequence in `test_reasoning_switch_needs_three_consecutive_complaints` — if a walk's success reset the count, the switch would never arrive — rather than as a direct read of the counter. Do not assert on an internal call record.
- **Permanent:** `test_reasoning_switch_needs_three_consecutive_complaints` — the selection changes only on the third consecutive matched complaint against it; an intervening 2xx-ended request resets the count to zero; and **after a persisted switch**, two further complaints must not advance the selection again (the count restarts at 1 against the new selection). The last clause is the pin for the post-switch collapse. The reset clauses need one more case: **a thinking-free successful turn must NOT reset** — complaint, thinking-free 200, complaint, complaint must still reach the switch.
- **Permanent:** `test_reasoning_transient_complaint_does_not_switch` — a single matched complaint followed by 2xx-ended requests leaves the persisted selection unchanged. This is the pin for the default-never-settles defect.
- **Permanent:** `test_reasoning_success_serves_client_during_learning` — while the count is below the threshold, a complaint is absorbed by an in-request retry and the client receives a 200 although the persisted selection has not changed (read the persisted value from the state file). The mock upstream must be **strict about the echoed field**, so a retry that re-sent the resolved selection instead of the advanced candidate fails here rather than passing quietly.
- **Permanent:** `test_reasoning_walk_sends_advanced_candidate` — a walk step from a persisted `reasoning` selection (whose next candidate is the literal string `"none"`) and from `reasoning_content` must each send **exactly** the advanced candidate's field. This is the pin for the sentinel collision: a resolver keyed on the parameter's value rather than on `None` re-resolves at the wrap step and the assertions fail. Assert on the body the mock upstream actually received, not on an internal call record.
- **Permanent:** `test_reasoning_full_walk_latches` — one request whose walk has all three candidates complain does **not** latch; the same on the immediately next request does; thereafter matching requests issue no retry and send `none`; the persisted selection is unchanged by the latch; and a fresh process (reloaded module state) does not latch. Add the consecutiveness pin: full walk, then a **successful** thinking-bearing request, then another full walk must **not** latch — the case the old "a walk that does not end in all three complaining resets the counter" wording missed, since a success runs no walk at all.
- **Permanent:** `test_reasoning_non_complaint_errors_are_not_counted` — a 401/403/500, an unparseable body, and an unrelated 400 (one naming **no** reasoning field) do not increment the counter, do not advance, and do not latch. A walk step returning one of these stops the walk and returns the **original** top-level result to the client.
- **Permanent:** `test_reasoning_matcher_shapes` — accepts every shape that names a field: the pass-back form, the both-fields form, a field named with no policy prose, the **sentence-final** form (`unknown field reasoning_content.`), and the **structured form** (an `extra_forbidden` node whose `loc` ends with a field name, at message depth such as `["messages", 0, "reasoning_content"]`). Rejects a 500, a 2xx, an unparseable body, an empty body, a JSON array body, a 400 naming no field in either shape, and the dotted nested path `messages.0.reasoning_content` **as prose**. Matches a field name inside a parsed `message` value while **not** matching one buried in a body that merely echoes the request as nested JSON (the traversal pin). Also covers a deeply nested body (`RecursionError` on `json.loads`) returning False rather than raising — for **both** matchers, since the shared parse helper is what makes that true.
- **Permanent:** `test_reasoning_delist_on_none_success` — a walk whose advanced candidate is the literal `"none"` and which succeeds removes the entry rather than writing `selection: "none"`, so the next load resolves the default from absence.
- **Permanent:** `test_chat_transform_emits_only_selected_field` — no reasoning field for `none` (default, explicit, `None`, and unrecognized values); only `reasoning_content` for that selection; only `reasoning` for that selection; never both.
- **Temporary:** an end-to-end test through the suite's own mock-upstream harness driving a multi-turn conversation with thinking blocks to a 200 via learning, asserting the upstream call count is bounded (a pair that complains on every candidate must not produce unbounded nested calls — the recursion-fence pin). Do NOT write a test that reaches the real `opencode-go-chat` / `glm-5.3-flash` pair — the suite's isolation contract forbids reaching a live upstream. Delete after the plan completes.

**Tests to investigate for retirement:**
- Planner candidates: none. The dual-write assertions are updated in place — at the new default they pin "no field", which is the invariant this plan introduces.
- Share one table-driven rejected-body corpus (a helper parameterized by matcher, or a shared list of `(label, status, body_bytes)` tuples) between `test_reasoning_matcher_shapes` and the existing `_compat` detector tests (`tests/test_compat.py:1174`, `:1212`, `:1233` cover the nested path, content-type-agnostic, and unrelated-400 rejections). The two corpora are structurally parallel by design, so one shared table is what keeps them from drifting apart on the next matcher change. Keep the accept-side cases separate — they differ by field-name constant.
- Tester may identify additional candidates during test work.

## Summary

### Problem

Chat mode echoes an assistant message's thinking back to the upstream as **both** `reasoning_content` and `reasoning` (`transforms_chat.py:210-212`). That dual write is a deliberate hedge from plan `2026-08-29-fix-chat-mode-thinking-roundtrip` — the proxy cannot know whether a backend reads the DeepSeek/GLM-style name or the vLLM-style name, so it writes both.

Two costs, both confirmed against the live trace (`~/.claude/logs/proxy-trace.jsonl`):

1. **Strict gateways reject the pair with a hard 400.** 17 occurrences since 2026-09-25 of `invalid_request_error: assistant reasoning and reasoning_content cannot both be specified`, all on tier `sonnet` / `glm-5.3-flash`, `retries: 0` (the proxy retries only 429/503, so the 400 propagates to the agent as `API Error: 400`). The most recent was 2026-09-29T12:45:58Z — it killed a mega-audit lens mid-run. The failure is per-request and transient: the same session returned 200 eight seconds earlier and 200 on its next request.
2. **The reasoning text is serialized twice** whenever it is echoed, doubling those bytes in the request body.

Neither the user nor the proxy can know a given pair's convention in advance, and the failure is invisible — it surfaces only as an agent dying.

### Approach

Replace the always-both hedge with a **learned per-pair selection**, defaulting to **no echo at all**. The learning is a second feature on the existing compatibility learner, which already keys state by `(provider, mode, actual_model, feature)`.

**The whole model is three pieces of state and one rule.**

```
selection    persisted   "reasoning_content" | "reasoning"
                         (an ABSENT entry means "none" — the default is never written)
complaints   in-memory   (for_selection, count) — consecutive matched complaints
                         counted against that one selection
latched      in-memory   set once the full-walk outcome has been seen on TWO
                         separate requests
```

> Send `selection`. On a **matched complaint**, increment `complaints` and **try** the next
> candidate inside the same request so the client is still served — but **persist** a switch
> only once `complaints` reaches 3. `complaints` resets to 0 when a request's own forwarding
> pass **ends** 2xx — an upstream 429/503 the retry loop carried to a 2xx counts — and only
> for a request that actually carried a thinking block; a walk candidate's success neither
> resets nor increments it. If the full walk — all three
> candidates complaining — is seen on **two consecutive requests**, **latch** to `none` and
> stop retrying until the process restarts.

**The counter belongs to a selection.** `complaints` is not a bare integer: it is the pair
`(for_selection, count)`, and every read-modify-write is taken under the learner's state
lock. Let `S` be the selection the request **actually sent** — resolved at request entry and
used unchanged for the whole request, including any walk. One rule governs both the increment
and the reset: if `S` is not the **stored** `for_selection`, the count restarts at 1 and the
stored pair becomes `(S, 1)`; otherwise the count increments. Comparing `S` against the
stored value — never against the entry's current selection — is what makes a persisted switch
reset the counter *implicitly*: the moment a switch lands, the next complaint carries a
different `S`, so it is the first complaint against the new selection, and the three-strike
protection is restored without a second reset rule to keep in sync. It is also what keeps a
complaint attached to the selection it was aimed at when a switch lands concurrently: a
request that resolved `S` before the switch files its strike against `S`, not against
whatever the entry became.

The explicit reset is the other half, and it is **evaluated only when the feature is active
for that request** — chat mode, a thinking block present, not suppressed, not latched: the
same conditions that permit an increment. Under those conditions, a request whose own
forwarding pass **ends** 2xx sets the count to 0 — a request the retry loop served after a
429/503 counts, because it was served. A walk candidate's 2xx does neither — that walk is
the mechanism that serves the client while learning, so treating it as a success would zero
the ladder on every request and no switch could ever persist. A thinking-free turn mutates
nothing at all: it neither exercises the selection nor proves anything about it, and letting
it reset the ladder would make the threshold unreachable for any pair that interleaves
ordinary chat with thinking-bearing turns.

`latched` **is** a session-scoped flag — exhaustion genuinely needs one, and there is no way
to express "stop trying for the rest of this process" without it. What makes it tractable is
that nothing inside the session clears it: a restart is the only reset. That removes the
clearing rule which was the previous design's undoing, while keeping the signal.

There is no cross-request tried-set, no first-contact-versus-revision split, and no
dependency on `context_management`'s counters or constants. "Try now, persist later" is what
lets one rule cover both learning a new pair and revising an old one.

**Why absent means `none`.** The default requires no entry, so there is nothing to settle and
nothing to persist on a plain success. This is what closes the defect where the default was
the only state that could not be protected: a lone transient complaint increments the counter
to 1, the in-request retry serves the client, the next request is served 2xx and
**resets the count to 0** — so nothing flips. The same rule protects a settled
`reasoning_content` and a settled `reasoning`, including across a persisted switch (the
counter restarts because the selection it was counting against has changed); every state,
including the default, is covered by one mechanism.

**A complaint is not an error.** The matcher requires status 400 and one of two content
shapes, both built from our own field-name constants and nothing else. **Message form:** a
`message` value of the parsed body names a field. **Structured form:** a validation node
carries a `loc`/`location` list whose last element is a field name — the shape these gateways
use when they report a rejected field purely as a structured location, with no field name in
any message string at all. There is deliberately **no phrase matching** in either shape: the
prose is upstream-authored and will drift, whereas an upstream complaining about the
reasoning field must name the field. Together the two shapes cover both directions of
complaint ("you must send it" and "you must not send it"), which are the only two ways a
selection can be wrong. A 401/403 (account disabled), a 500 (gateway blip), an unparseable
body, or a 400 naming no field in either shape is **not** a complaint: nothing is counted,
nothing advances, nothing latches, and the error passes through untouched.

The message-form match runs over the **`message` values of the parsed body** — the
explicit-stack walk `_compat_message_match` performs (`compat.py:495-507`), which inspects
`node["message"]` at every dict it visits — never over the raw body and never over bare keys,
so a gateway that echoes the offending request as nested JSON inside its error payload cannot
hand the matcher its own request text. A *stringified* echo — the request text pasted into a
message string — would still match; that hole is recorded in the threat model rather than
closed, because closing it would mean pattern-matching on prose again. The feature is
additionally inert unless the request actually carries a thinking block, so a 400 on an
ordinary chat turn is never a complaint either.

Recall is favoured over precision on purpose — a missed complaint means the pair never
learns, which is the status quo, while a false positive costs one increment and needs two
more consecutive ones before anything moves. The trigger is therefore **keyword-grade, not
field-reference-grade**: `reasoning_content` is unambiguous, but the bare English noun
`reasoning` also matches prose such as `max_tokens must be greater than the reasoning
budget`. That is the accepted cost of the recall bias, not an oversight. It is bounded by
the three-strike switch rule, the two-request latch rule, the presence gate above, and a
three-value vocabulary whose worst outcome is a pair that sends a field the upstream ignores.

**Latching is terminal for the process.** A full walk is **one observation, not three**: the
three candidates are examined inside a single request under a single upstream condition, so
a uniform 400 that has nothing to do with the field repeats identically across all three. One
such request must therefore not latch a pair for its lifetime — the same "one forged
complaint cannot move anything" reasoning that governs a switch has to govern the latch too.
The latch is earned the way a switch is: **the full walk must recur on two consecutive
requests**. Only then does "no candidate works" carry more confidence than a single blip can
supply, and two consecutive full walks is exactly the evidence a genuinely field-independent
failure produces. *Consecutive* is load-bearing and needs its own rule: the full-walk counter
is cleared by **any feature-active success — the request's own 2xx pass *or a walk candidate's
own 2xx***, because a success at either level is positive evidence that some selection works, and
that is precisely the evidence the two-consecutive-full-walks rule exists to require. Without
that reset, two full walks separated by a request whose walk succeeded would still latch a
pair permanently, on two non-consecutive requests — the opposite of what the consecutiveness
claim asserts. A non-complaint error (a 500, a connection error) leaves the counter alone: it
is no evidence either way, exactly as it is never counted as a complaint. This is the one
counter a walk candidate's outcome *does* touch; `complaints` — the strike ladder — is still
never affected by a walk step.
Latching means the field selection is not the problem, so re-walking the
chain on every request would spend three upstream calls to re-derive a known answer. A
latched pair sends `none`, issues no retries, mutates no counter, and **leaves the persisted
selection untouched** — the latch is a decision about this process, not a rewrite of what was
learned, so the next run starts from the last known-good state. It emits a rate-limited
`compatibility_latched` trace event (provider, mode, actual_model, feature, tier) plus a
rate-limited stderr warning carrying that same metadata set and nothing upstream-derived. The
client-visible errors are the notice. A restart clears it, which is the natural retry point
for a config or upstream change.

**Registry generalization.** `COMPAT_FEATURE` (a singleton constant) becomes a registry
`COMPAT_FEATURES` (name → descriptor). Each descriptor declares its mode scope, presence
test, complaint matcher, learning policy, its **own entry field set and state vocabulary**,
and its retry budget. `_compat_validate_entry` currently does not pass entries through — it
*constructs* a fixed 8-key dict (`compat.py:153-165`) that `_load_compat_state` then stores,
so any field outside that set is silently discarded on every load. Validation and
normalization must therefore become **per-descriptor**, or a persisted selection is written
to disk and dropped on each restart. `COMPAT_SCHEMA_VERSION` stays `1` — unknown feature keys
are already skipped for forward-compat (`compat.py:206-217`).

**The selection is resolved in exactly one place.** `_forward_request_impl` resolves it from
the learned entry at request entry and passes that value down. The parameter's `None` default
marks "unresolved", so an explicit candidate string — including the literal `"none"` the
cycle wraps to — is never mistaken for the sentinel. The nested discovery retry passes an
**explicit** candidate and must not re-resolve, or it would overwrite the candidate it is
retrying with and re-send the same failing body.

```
request entry ── resolve S ──> _forward_request_impl(selection=S)
                                  │
                   mode == "chat" ├─> _anthropic_to_chat(selection=S)
                                  │      └─> _transform_anthropic_messages_to_chat
                                  │            emits per S (none | reasoning_content | reasoning)
                                  ▼
            400 + matched complaint ──> acquire the feature's retry lock (non-blocking)
                                  │        contended -> return the upstream error,
                                  │        no counter mutated
                                  ▼
                            complaints += 1 ──> try next candidate in-request
                                  │      (suppress_compat=True, explicit selection,
                                  │       ORIGINAL client body, budget 2)
                                  │        walk candidate 2xx -> client served;
                                  │          persist only at count 3 (delist if it is "none")
                                  ├─> full walk (all three complained) -> full-walk counter;
                                  │      two consecutive -> latch until restart
                                  └─> non-complaint, non-2xx walk result OR an exhausted
                                         budget -> stop the walk, return the ORIGINAL
                                         top-level result with its merged retry count
```

**Honest guarantee.** Each feature owns its own retry lock (acquired non-blocking), so a
chat-mode walk cannot deny an `anthropic`-mode probe: the two policies never contend with
each other. Within a feature, under contention no retry is issued and the client receives the
upstream error, with no counter mutated. The walk's cost is bounded but not small: it is the
initial attempt plus up to two retries, each opened with the 300 s socket timeout
(`server.py:773`), so a stuck chat upstream can occupy one worker thread and its feature lock
for ~15 minutes. Two consequences follow and are accepted: `context_management` probes are
never blocked by it (separate lock), but a concurrent admin switch or reload can hit its 30 s
drain timeout and abort while the walk is in flight. So the guarantee is: **the client is
served transparently while a pair is learning, except when the retry lock is contended, the
walk itself fails, or the walk's own attempts exceed the client's patience** — not "never
sees an error".

### Alternatives rejected

- **Keep sending both** — the status quo; it is what produces the observed 400.
- **Always send only `reasoning_content`** — fixes the observed case and no others; a backend wanting `none` or `reasoning` has no recourse.
- **Static per-provider config in `models.json`** — rejected by the user: users cannot know these details in advance, and the failure is invisible to them.
- **One-way latch per pair** — rejected by the user: upstreams change behaviour, so the selection must be revisable. (The latch here is different: it triggers only when *no* candidate works.)
- **Dropping the echo entirely** — would re-break what plan `2026-08-29-fix-chat-mode-thinking-roundtrip` fixed; DeepSeek-class backends hard-require the echo.
- **A cross-request "episode" tried-set with a re-entry threshold** — designed, audited, and withdrawn. It required a second counter, a flag with its own clearing rule, and a dependency on `context_management`'s suppression helpers, and produced three High findings across two audit rounds. The per-request walk plus a process-lifetime latch expresses the same behaviour with one rule.

### Threat model for the learner's input

The learner's only input is upstream error text, which is attacker-adjacent: a hostile upstream
can emit a body matching the complaint pattern and thereby **steer** the persisted selection
for that pair. Mitigations: the matcher is built from our own constants and never copies
upstream text into state; a switch needs **three consecutive** complaints, so one forged
complaint cannot move anything; a non-complaint error is never counted; a full walk must
recur on two **consecutive** requests before it latches, rather than oscillating; and the
message-form match reads parsed `message` values, not bare keys and not the raw body, so an
echoed request cannot feed it as nested JSON. Residual risks, all accepted and recorded here
rather than closed: the trigger's breadth is keyword-grade rather than field-reference-grade
(see "A complaint is not an error"), so the barrier is three consecutive complaints plus two
consecutive full walks, not perfect precision; a *stringified* echo inside a `message` value
would match; a gateway reporting the same condition with a status other than 400 (a 422, say)
produces no complaint at all, so such a pair silently stays at `none` with no trace signal;
and an upstream that complains falsely three times running *and* then accepts the wrong
candidate, or repeats a uniform 400 naming a reasoning field across two consecutive full
walks, can still move or latch the pair — but such an upstream already controls the request's
outcome.

### Explicitly out of scope

- `image-content-blocks-chat-mode` (deferred issue, same file, different concern — recorded in the Issue Log, deliberately not folded in).
- Surfacing learned or latched state in `claude-retry-proxy status` or the admin API — the user chose diagnostics-only.
- Threshold/probation/delist re-probing for the new feature; it has no probe ladder at all.
- Forwarding `thinking.budget_tokens` (still deferred).
- The response-direction conversion (`reasoning`/`reasoning_content` → `thinking` block) is unchanged.

## Repo Mode

Public

*Detected at plan creation. Determines: plan archival path, commit-message content, staged files.*

## Document Overrides

| Document | Rule Overridden | Reason |
|----------|----------------|--------|
| `doc/compatibility.html` — "The learner applies to `anthropic`-mode providers only. Chat and response modes never run it." | The new `reasoning_field` feature runs in **chat** mode | The rule described a single-feature learner whose one feature was Anthropic-specific; the registry makes mode a per-feature property |
| `doc/provider-modes.html#compat-retry` — the same "applies to `anthropic` mode only" statement, and "The compatibility retry is a **single** upstream attempt." | Same mode scope; and the attempt count is now a descriptor property (1 for `context_management`, 2 for `reasoning_field`) | Second and third copies of claims this plan invalidates |
| `doc/compatibility.html` — "One field is common enough to be worth handling automatically: `context_management`" / single-feature framing | The learner now carries N features | Generalization the user directed |
| `doc/compatibility.html` — "There are exactly **two** states:" and the persistence field table at 211-221, which presents one unqualified field set as "the" state-file schema | Each descriptor owns its state vocabulary and entry fields | Per-descriptor validation |
| `doc/compatibility.html` — "All ten events below are emitted by the learner." | The plan adds `compatibility_latched` and the learned/switch events | Event count changes |
| `doc/provider-modes.html:130` — request-direction rule "`thinking` blocks → `reasoning_content` on the assistant message" | Emission is selection-dependent and defaults to none | The dual write is removed |
| `doc/provider-modes.html:226` — "`reasoning_content` field — or `reasoning`, which vLLM uses" | Still true for the *response* direction; the request direction no longer mirrors both | Response side unchanged |

## Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| Default changes for **every** chat-mode provider: the eager echo becomes opt-in per learned pair | A backend that tolerated the pair now receives no echo until the learner reaches it | The in-request retry serves the client during learning, with a budget of 2 so the third candidate is reachable inside one request |
| A pair latches on a bad request (all three candidates complained in one walk) | That pair sends `none` with no retries until restart, so a DeepSeek-class backend stays broken for the process lifetime | The latch requires the full walk on **two consecutive requests**, and the full-walk counter is cleared by any feature-active success in between. A single walk is one observation repeated three times — the same upstream condition examined with only the field differing — so it is not evidence enough on its own. The latch is per-pair, in-memory, leaves the persisted selection untouched, and is cleared by a restart — the natural point after a config or upstream change |
| A walk that never reaches a per-candidate verdict (429/503, connection error, timeout) | Nothing can persist — a switch needs a candidate's own 2xx — while each complaint still spends up to two extra upstream calls, so a pair under sustained rate-limit pressure learns slowly and adds load to the tier that is already failing | Deliberate: counting an upstream-load error toward the latch would latch a pair for the process lifetime over a transient condition. The walk **stops** on the first such result rather than advancing, so the amplification is bounded at one extra call per complaining request in that state — and the per-feature lock means it can never deny `context_management` a retry |
| A walking client request re-emits its per-request trace events | `mode_dispatch` and the chat transform's events (`cache_control_stripped`, `redacted_thinking_passthrough`, `tool_args_parse_failure`, `content_block_dropped`) fire again on every nested walk step, so per-request trace accounting is inflated for that request (`mode_dispatch` and the transform events only — **not** `analyze_proxy_trace.py`'s per-model counts, which read `event == "request"` entries that nested walk calls never emit; see Guidance for Planner) | Documented and swept into `doc/trace-log.html` (see Guidance for Planner). The multiplicity is bounded by the walk budget (≤3 images for one client request) and occurs only while a pair is actively learning — present, complaining, not latched — so it is self-limiting |
| The complaint matcher is the least-determined piece | A misattributed complaint advances the cycle wrongly | Patterns built from our own constants only, matched inside parsed error-message values with a word-boundary guard; inert unless the request carries a thinking block; three consecutive complaints required, so one forgery cannot move anything; a non-complaint error is never counted. The trigger is keyword-grade: the bare noun `reasoning` matches unrelated prose, so the bound is the strike counts, not precision |
| A walk against a stuck upstream | One worker thread and the feature's retry lock are held for up to ~15 min (3 attempts × the 300 s socket timeout), and a concurrent admin switch/reload can hit its 30 s drain timeout and abort | Accepted and stated in the "Honest guarantee". Each feature owns its lock, so `context_management` is never denied a retry by a chat-mode walk; the drain abort leaves the in-flight request to finish normally |
| Concurrent requests spanning a switch, or a contended retry lock | A complaint counted against the wrong selection, or no retry at all | The selection is resolved once at request entry and used for the counter update; `complaints` carries the selection it counts against, so a complaint aimed at a different selection restarts the count instead of adding to it; every counter read-modify-write is taken under the learner's state lock; lock contention is documented as a bounded, state-free degradation |
| The registry generalization perturbs the most behaviourally intricate module (`doc/compatibility.html:21-23`) | Regression in `context_management`, or a silently-dropped persisted field | Its policy is not rewritten — only wired behind a descriptor; the existing compat suite must pass unmodified; Step 1 requires per-descriptor validation so a selection survives reload |
| The pre-implementation mega-audit for this plan runs through a degraded tier | Lens failure mid-audit | Mitigated in practice by running the audit on `opus` |

## Rollback

Revert the single commit; `feature-compatibility.json` stays at `schema_version` 1.

- A file written by the new code contains `reasoning_field` entries. The old code's load path skips unknown feature keys silently (`compat.py:206-217`), so an old binary starts cleanly and simply re-learns nothing.
- Deleting `~/.claude/proxy/feature-compatibility.json` resets all learned state, including `context_management`'s — the learner re-discovers from scratch, its designed cold-start behaviour.
- Nothing in `config.json` or `models.json` is touched, so no config change is required in either direction.

## Proposed Changes

Each step includes verification checks tagged with confidence (see Prime Directive 4).
`(auto)` = mechanical, coder self-verifies. `(scripted)` = deterministic multi-step, coder runs provided script.
Every step must have at least one verification check executable by its owner (coder steps: coder checks; tester steps: tester verify; planner steps: Evidence).

1. **Step 1:** Generalize `compat.py` into a feature registry WITHOUT changing `context_management` behaviour.
   - Introduce a module-level registry dict `COMPAT_FEATURES` mapping feature name → descriptor. A descriptor carries: `name`, `mode`, a presence test over the client body, a complaint matcher, its learning policy, its **own entry field set and state vocabulary**, its entry-validation function, its `max_retries_per_request`, and its **own retry lock** — so one feature's in-flight retry can never deny another feature a retry. **Pin the descriptor attribute names** as `name`, `mode`, `present`, `complaint_match`, `validate_entry`, `max_retries_per_request`, `retry_lock`, and keep the module-level state object named `_state`; the scripted check addresses them by name.
   - Register `"context_management"` with `mode="anthropic"`, its current policy unchanged, and `max_retries_per_request = COMPAT_MAX_RETRIES_PER_REQUEST` (1); register `"reasoning_field"` with `mode="chat"` and `max_retries_per_request = 2` (descriptor body lands in Step 2).
   - Keep `COMPAT_FEATURE = "context_management"` importable (`server.py:36` imports it).
   - `_compat_key(provider, mode, actual_model, feature_name)` takes the feature name. This is a **signature change**: today it takes three arguments and hardcodes the constant (`compat.py:98-100`), so both call sites (`server.py:564`, `server.py:691`) must be updated to pass `COMPAT_FEATURE` explicitly — or the new parameter must carry a default. Half-applying it is a `TypeError` at request time, so the auto-check asserts it.
   - Add a `_feature_for_mode(mode)` lookup returning the single registered feature whose `mode` matches, or `None`. **The registry holds at most one feature per mode** — a second one would make the lookup ambiguous — and `_compat_validate_constants()` (`compat.py:80-94`, called at `server.py:2600`) gains a startup warning if two registered features claim the same mode. This lookup is what `active_feature` means everywhere in Step 5: never `COMPAT_FEATURES[mode]`, since the registry is keyed by feature name.
   - **Validation and normalization become per-descriptor.** `_compat_validate_entry` (`compat.py:124-165`) must dispatch to the entry's descriptor and preserve that descriptor's fields — it currently constructs a fixed **nine**-key dict (`compat.py:153-165`, matching the nine members of `ALLOWED_STATE_KEYS` at `tests/test_compat.py:80-83`) and discards everything else. The shared envelope (`schema_version`, `provider`, `mode`, `actual_model`, `feature`) stays validated in common; a descriptor additionally **validates its own values**, not merely preserves its fields (so an out-of-vocabulary `selection` is rejected, not loaded). Each descriptor's validator is **total** — it returns `None` for anything it cannot validate and never raises (see Constraints).
   - **`_load_compat_state` (`compat.py:168-219`)** needs three changes beyond the registry lookup:
     - Unknown features remain silently skipped.
     - **Bind the entry to its key.** The loop stores `loaded[_compat_parse_file_key(key_str)] = parsed`: the key comes from the *file key string* while validation inspects only the entry body, and nothing binds the two. That was harmless while `_compat_validate_entry` required `feature == COMPAT_FEATURE`, so a mismatch could not exist. With two registered features it becomes reachable — a state file whose key says `context_management` but whose body says `feature: "reasoning_field"` (hand-edited, corrupt, or written by a buggy revision) loads under the wrong key and is re-persisted forever; the anthropic path then calls `_compat_record_strip` on a reasoning-shaped entry, which indexes `strip_counter`/`state`/`threshold`, and the `KeyError` is swallowed by `server.py:608-609` — silently forwarding the **untransformed** client body upstream instead of failing loudly. **Derive the in-memory key from the entry's own `(provider, mode, actual_model, feature)` and stop using the file key as a key at all** — preferred, because it also removes an arity hazard: `_compat_parse_file_key` splits on `\x1f` without checking arity (`compat.py:108-109`), so a hand-edited key such as `"oops"` yields a 1-tuple and indexing its feature component raises `IndexError` — an escape at `server.py:2601`, before stderr is wrapped, i.e. an unhandled startup crash. If the file key is kept as a cross-check instead, length-check the parsed tuple before indexing and place the check inside the same guard as the dispatch.
     - **Fix the drop diagnostic.** The warn-or-stay-silent gate at `compat.py:211-214` compares the entry's feature to the single `COMPAT_FEATURE` constant; left alone, a corrupt `reasoning_field` entry is dropped without the redacted warning `doc/compatibility.html` promises. Change the gate to `feature not in COMPAT_FEATURES`: unknown features stay silent, a registered feature with an invalid entry warns.
     - Belt-and-braces: wrap the descriptor dispatch **inside** the loop, so a raising validator degrades to a dropped entry plus the existing warning rather than escaping `_load_compat_state` (called at `server.py:2601`, before `sys.stderr` is wrapped at `:2643`).
   - `COMPAT_SCHEMA_VERSION` stays `1`; no migration.
   → coder verify (auto): `COMPAT_FEATURES` keys are exactly `{"context_management", "reasoning_field"}`; `COMPAT_FEATURE == "context_management"` still holds; `_compat_validate_entry` rejects an unregistered feature name, accepts each registered name, dispatches through the registry rather than a single fixed field set, and delegates value validation to the descriptor; `_compat_key` accepts a feature name; `context_management`'s descriptor reports `max_retries_per_request == 1`. Additionally: both `_compat_key` call sites pass the feature name (a three-argument call would raise); `_feature_for_mode("chat")` returns the reasoning descriptor and `_feature_for_mode("response")` returns `None`; a descriptor validator returns `None` (never raises) for a non-dict, a `None`, and a value of the wrong type; an entry whose file key names a different feature than its body is never stored under the mismatched key, and a malformed key string (no `\x1f` separators) does not raise; a corrupt registered-feature entry is dropped *with* a warning while an unknown feature is dropped silently.
   → coder verify (scripted): script at ./tmp/verification/2026-09-29-chat-reasoning-field-learner-step1.py
   → tester verify: the existing `tests/test_compat.py` suite passes, with changes confined to the sites enumerated in Guidance for Tester; the extended `test_compat_state_roundtrip` (descriptor-parameterized) and the per-feature `ALLOWED_STATE_KEYS` assertion pass.

2. **Step 2:** Implement the `reasoning_field` descriptor and its policy in `compat.py`.
   - Pin these names so the scripted check can address them: `_reasoning_present(body_json)`, `_reasoning_complaint_match(status, resp_body)`, `_reasoning_next_candidate(current)`, `COMPAT_REASONING_SWITCH_THRESHOLD`, and the entry field `selection`. Extend `_compat_validate_constants()` (`compat.py:80-94`, called at `server.py:2600`) with a clamp-and-warn for `COMPAT_REASONING_SWITCH_THRESHOLD`, the way every other policy constant in the module is guarded: a value below 2 collapses the three-strike rule the whole design leans on, and a non-int would raise inside the request path (the counter update sits under no totality clause). Everything else inside the policy is the coder's choice.
   - **Presence test:** true when any assistant message in the client body carries a `thinking` block with non-empty `thinking`, or a `redacted_thinking` block with non-empty `data`. When false the feature is inert for that request. Returns False (never raises) for a non-dict or malformed body.
   - **Complaint matcher.** Status must be `400`; body within `SETTINGS.max_body_size`; parse guarded by the shared total helper (see Constraints). Two accepted content shapes, both keyed on our field-name constants:
     - **Message form.** A **`message` value of the parsed body** names a field, matched with a **word-boundary guard, not a locus anchor**: `(?<![\w.])(?:reasoning_content|reasoning)(?![\w])`, searched within that string. The traversal is the explicit-stack walk `_compat_message_match` performs (`compat.py:495-507`: inspect `node["message"]` at every dict visited, descend into values and list items) — **not** the raw body and **not** bare keys, either of which would let a gateway that echoes the offending request as nested JSON hand the matcher its own request text.
       - The lookahead excludes a following word character but **not a period**, deliberately. The lookbehind already rejects the dotted path (`messages.0.reasoning_content` — the preceding `.` fails `(?<![\w.])`), so keeping `.` in the lookahead would cost recall on the ordinary sentence-final mention (`unknown field reasoning_content.`) and buy nothing. The dotted prose path stays rejected; the sentence-final form matches.
     - **Structured form.** A node carrying `extra_forbidden` (in its `type` or `code`) whose `loc`/`location` list **ends with** one of our field-name constants. Mirror `_compat_structured_match` (`compat.py:510-526`) in discipline — same explicit-stack walk, same constants, nothing upstream-derived — but **not in its depth guard**: that helper requires `len(loc) <= 2` with `loc[0] in ("body", "request")` because `context_management` is a top-level body field. The reasoning field lives *inside* an assistant message, so a gateway reporting it structurally reports a deeper path; this guard accepts the constant as the last element at any depth and requires nothing of the prefix.
       - This branch is not optional polish. A walk step that sends the wrong candidate field is the canonical "extra inputs are not permitted" rejection, and these gateways often report it only structurally, with no field name in any message string. Without the branch such a pair never registers a complaint — no switch, no latch, no trace signal — and keeps sending the wrong field while spending up to two extra upstream calls per request indefinitely. That is precisely the never-learns-never-gives-up state the latch exists to end.
     - **No phrase matching.** Requiring a phrase such as `must be passed back` would break silently the first time the upstream rewords its message, and a silent break here means the pair never learns. The field name is the reliable half: an upstream complaining about the reasoning field must name it.
     - The guard is what keeps the dotted nested path (`messages.0.reasoning_content`) from matching. It deliberately does **not** reuse `_COMPAT_MESSAGE_RE`'s locus anchoring (`compat.py:490`, `(?:^|(?<=: )|(?<=\] ))`) — that anchor exists to reject nested paths and would reject the observed complaint shapes too, since they name the field mid-sentence (`The reasoning_content in the thinking mode must be passed back to the API.`).
     - The `cannot both be specified` shape therefore matches, as a **consequence** of the field-name rule rather than a targeted phrase. That is acceptable: the design never sends both fields, so the proxy cannot provoke it, and if it ever appeared it would genuinely be a reasoning-field problem.
   - **Candidate cycle:** `none → reasoning_content → reasoning → none`, as the string values `"none"`, `"reasoning_content"`, `"reasoning"`. `_reasoning_next_candidate(current)` returns the next in cycle order (wrapping), and for an unknown, `None`, or non-string input returns the **string** `"none"` — never `None`. That matters beyond tidiness: the walk feeds this return value straight into the resolver parameter, where `None` means "resolve me from the learned entry" (Step 4), so a `None` return would re-resolve and re-send the body that just failed. The cycle is the ladder walked inside one request; it is not a persisted cursor.
   - **Switch rule:** a persisted switch requires `complaints >= COMPAT_REASONING_SWITCH_THRESHOLD` (3). `complaints` is in-memory, per pair, stored as the pair `(for_selection, count)`, and updated only by a **matched complaint** or by the request's own **2xx outcome** — and only when the feature is active for the request. Let `S` be the selection the request actually sent: resolved at request entry (Step 4) and fixed for the whole request, including any walk. Both the increment and the reset follow one rule, taken under the learner's state lock: if `S` is not the **stored** `for_selection`, store `(S, 1)`; otherwise store `(for_selection, count + 1)`. Comparing `S` against the **stored** value — never against the entry's current selection — is what makes a persisted switch reset the counter without a second reset rule, and what keeps a complaint attached to the selection it was aimed at when a switch lands concurrently. A top-level 2xx stores `(S, 0)` — the request's own forwarding pass, so an upstream 429/503 the retry loop carried to a 2xx counts; a walk candidate's 2xx does not. A walk candidate's outcome — 2xx or complaint — never touches `complaints`.
   - **Persistence:** a switch writes the candidate **whose own attempt returned 2xx** in this request's walk — never a candidate that just complained. When that candidate is the literal `"none"`, the entry is **delisted** (removed) rather than written with `selection: "none"`, preserving the absent-means-`none` invariant. A walk in which no candidate succeeded persists nothing.
   - **Latch:** if one request's walk has all three candidates produce a matched complaint, count that as one **full walk** in an in-memory, session-scoped, per-pair counter. Only when a **second, consecutive request** produces another full walk does the pair set its `latched` flag. The full-walk counter is cleared by **any feature-active success: the request's own 2xx pass, or a walk candidate's own 2xx** — a success at either level is positive evidence that some selection works, which is what keeps the two-consecutive-full-walks rule honest. It is left **unchanged** by a non-complaint error (no evidence either way) and is never advanced by a walk that ends without all three complaining. `complaints` is untouched by a walk candidate's outcome; the full-walk counter is the one counter a walk success clears. While latched: send `none`, issue no retries, mutate no counters, leave the **persisted selection untouched**, and emit a rate-limited `compatibility_latched` trace event (provider, mode, actual_model, feature, tier) plus a rate-limited stderr warning carrying that same metadata set and no upstream-derived text (any interpolated exception text goes through `sanitize_error`). Cleared only by process restart.
   - **Pin the new state and its limiter.** The three stores live on `_CompatState` (`compat.py:48-69`) beside the existing four dicts, under its `lock`: the counter pair, the full-walk counter, and the latch flag — e.g. `reasoning_complaints`, `reasoning_full_walks`, `reasoning_latched`. Pin the names so the scripted and auto checks can address them. The rate limiter for the latch/switch events belongs there too, as one more dict keyed like `persist_warned` (60 s per key) — **not** a module global, which would escape the state-injection contract that keeps tests isolated.
   - Called only when `_reasoning_present` is true, and never through any `context_management` helper.
   → coder verify (auto): the descriptor is registered with `mode == "chat"` and `max_retries_per_request == 2`; the absence of any call to `_compat_suppressed`, `_compat_note_suppressed_request`, `_compat_record_failed_confirmation`, or `_compat_learn` from the reasoning path; `_reasoning_present` returns False for a body with no thinking blocks, a non-dict, and `None`; `_reasoning_next_candidate` wraps `reasoning → none` and returns the string `"none"` (never `None`) for an unknown or non-string input; the matcher accepts every shape that names a field — the pass-back form, the both-fields form, the sentence-final form, and the structured `loc` form — and rejects a 500, a 2xx, an unparseable body, an empty body, a JSON array body, a 400 naming no field in either shape, and the dotted nested path; a field name appearing only in an echoed request payload as nested JSON (not in a parsed `message` value) does **not** match; a deeply nested body returns False rather than raising; latching requires two **consecutive** full-walk requests, is cleared by a feature-active success in between, leaves the persisted selection untouched, and emits its trace event.
   → coder verify (scripted): script at ./tmp/verification/2026-09-29-chat-reasoning-field-learner-step2.py
   → tester verify: `test_reasoning_switch_needs_three_consecutive_complaints`, `test_reasoning_full_walk_latches`, `test_reasoning_non_complaint_errors_are_not_counted`, `test_reasoning_matcher_shapes`, and `test_reasoning_delist_on_none_success` pass, each registered in its module's `ALL_TESTS`.

3. **Step 3:** Parameterize the chat request transform's reasoning emission by the selection.
   - `_transform_anthropic_messages_to_chat` (`transforms_chat.py:79`) gains a `reasoning_selection` parameter. Values are the strings `"none"`, `"reasoning_content"`, `"reasoning"`; the default is `"none"`, and `None` or any unrecognized value must behave as `"none"` **without raising**. Pin the transform's contract as **value-based**: it emits a field only when the argument is exactly one of the two field-name strings, so every other value — `None`, garbage, an omitted argument — is the no-echo default. The transform never resolves anything and never reads state; the `None`-means-"resolve me" sentinel belongs to the resolver in Step 4 and must not leak into this signature.
   - Replace the dual write at `transforms_chat.py:210-212` with a single-field emit: `none` → no reasoning field; `reasoning_content` → that field only; `reasoning` → that field only. Never both.
   - `_anthropic_to_chat` (`transforms_chat.py:17`) gains and forwards the parameter.
   - Update both docstrings (the module description at `transforms_chat.py:84-91` says thinking blocks are "converted to reasoning_content on the assistant message").
   - The response-direction code (`transforms_chat.py:413-421`) is UNCHANGED.
   → coder verify (auto): no occurrence of `m["reasoning"] = ` remains in `transforms_chat.py`; `reasoning_selection` appears in both transform signatures with default `"none"` (these two only — the resolver parameter in Step 4 defaults to `None`, deliberately); the response-direction block at ~413-421 is unchanged.
   → coder verify (scripted): script at ./tmp/verification/2026-09-29-chat-reasoning-field-learner-step3.py
   → tester verify: `test_chat_transform_emits_only_selected_field` passes; every updated request-direction assertion in `tests/test_chat_transform.py` passes.

4. **Step 4:** Resolve the selection exactly once, at request entry.
   - `_forward_request_impl` resolves the selection from the learned entry at entry and passes that value down; this is the **only** resolution site.
   - The function's `reasoning_selection` parameter defaults to **`None`, meaning "unresolved — resolve me from the learned entry"**. The three-value vocabulary uses the strings `"none"`/`"reasoning_content"`/`"reasoning"`, so `None` is not a member of it and the discriminator is unambiguous: the resolver runs only when the parameter **is** `None`, and a caller passing the literal string `"none"` gets no echo and no resolution. This matters because `"none"` is a real cycle value — `_reasoning_next_candidate("reasoning")` returns it — so a resolver keyed on the *string* would overwrite the wrap-around candidate with the persisted selection and re-send the body that just failed. **Do not give the parameter the default `"none"`.**
- The nested discovery retry always passes an **explicit** candidate string and must NOT re-resolve; it also arrives with `suppress_compat=True`, a second and independent guarantee that the resolver does not run.
- The chat transform call site (`server.py:598-601`) forwards the resolved value into `_anthropic_to_chat` after resolution; the transform's own default is the string `"none"`, and it never sees `None` from this path.
- The same resolved value is what the complaint path attributes against.
- The `mode == "response"` and anthropic paths are untouched.
   → coder verify (auto): exactly one resolution site exists; `_forward_request_impl`'s `reasoning_selection` default is `None`, **not** `"none"`; the call site at ~598-601 forwards the resolved value; the retry path passes an explicit candidate and contains no second resolution; calling `_forward_request_impl` with `suppress_compat=True, reasoning_selection="none"` sends no reasoning field (the sentinel-collision check).
   → tester verify: `test_reasoning_success_serves_client_during_learning` and `test_reasoning_walk_sends_advanced_candidate` pass — the retry sends the advanced candidate, including the wrap step whose candidate is the literal `"none"`.

5. **Step 5:** Wire the reasoning complaint path and generalize the mode guard.
   - The compat short-circuit at `server.py:684` becomes dispatch on the **active feature's** mode scope rather than a hardcoded `"anthropic"`. Keep the `suppress_compat` clause **first** — it is the structural recursion fence: `_forward_request_impl`'s docstring records it ("compatibility retries call this function with the flag set, so recursion is structurally impossible", `server.py:443-446`), and the walk recurses with `suppress_compat=True`. Rewriting the expression around the feature's mode and dropping that clause would let each nested call's matched complaint re-enter the walk with a fresh budget: unbounded recursion and unbounded upstream POSTs on a persistently complaining pair. Write the condition **once**, in the form the next bullet pins — `if suppress_compat or not compat_outbound_present or _is_count_tokens: return` — which already carries the mode scope and the presence test through `active_feature`.
   - **`compat_outbound_present` (`server.py:596-597`) must be generalized too.** It is computed as `COMPAT_FEATURE in body_json` and gates the same early return; left alone it is False for every chat-mode reasoning request, making the reasoning path unreachable dead code. Compute it from the **active feature's presence test**, `None`-safely: `compat_outbound_present = active_feature is not None and active_feature.present(body_json)`. The `None` case is load-bearing rather than defensive — the computation sits inside the transform `try` whose `except` clause catches `AttributeError` (`server.py:608-609`), so a bare `active_feature.present(...)` raises for every `response`-mode request, the exception is swallowed, and line 619 falls back to `rewritten_body = body`: the raw Anthropic body is POSTed to `/v1/responses` on every request, visible only as a `transform_failure` event.
   - The early return then reads `if suppress_compat or not compat_outbound_present or _is_count_tokens: return` — **one** rendering of the condition. `compat_outbound_present` already folds in both `active_feature is None` and the presence test, so it is written once rather than duplicated next to the dispatch.
   - The pre-send path (`server.py:562-597`) resolves and passes the selection for the reasoning feature; when no entry exists the value is the `none` default.
   - **The walk re-enters with the ORIGINAL client `body`**, never `rewritten_body`. The existing anthropic retry passes a *derived* body because it strips a field (`server.py:719-724`); the reasoning feature strips nothing, and the retry's whole purpose is to re-run the chat transform with the new candidate. Passing the already-chat-shaped JSON would leave `_transform_anthropic_messages_to_chat` with no `thinking` block to convert, so every walk step would emit no reasoning field at all and the ladder would silently never advance while the code looked correct.
   - On a matched complaint: increment the counter, then walk the next candidate with `suppress_compat=True`, an **explicit** candidate string, the original body, and up to the **feature's** budget (2).
   - **Walk outcomes have three cases, and all three are specified.** (i) A candidate returns 2xx: the client is served; persist a switch **only** if the threshold is met, and persist **that candidate** (delisting when it is `"none"`). (ii) A candidate returns a matched complaint: advance to the next. (iii) Anything else — a 401/403, a 429/503 (the walk is a single attempt, so there is no 429 backoff), a 500, a connection error, an unparseable body — **stops the walk, mutates no counter and no state**, and returns the **original top-level result** to the client, with `_compat_merge_retries` applied once against it. Returning the walk's error instead would hand the client a 500/401 it never provoked in place of its own informative 400, and would corrupt the merged retry accounting.
   - **Latch and persist cannot co-fire, so no precedence rule is needed.** The premise that once seemed to justify one is false: walk candidates never touch `complaints` (Step 2), so a full walk leaves the counter at whatever its **first** attempt set — 1 on a cold pair — not at 3. What separates the branches is structural: persisting requires a candidate whose own attempt returned 2xx, and a full walk by definition has none. The latch is therefore a pure function of the full-walk counter (two consecutive), **never gated on `COMPAT_REASONING_SWITCH_THRESHOLD`**, and a walk that exhausts its budget persists nothing.
   - **The exhausted walk is an exit too.** When the budget runs out with the last candidate still complaining, the walk is over and `_forward_request_impl` must still return its tuple. Return the **original top-level result** exactly as case (iii) does, then apply the full-walk bookkeeping. The three cases above describe a *candidate's* result and do not cover this exit; leaving it unstated forces the coder to invent whether the client sees the first 400 or the last one, and whether the retry count is merged.
   - If a walk ends with all three candidates complaining, record one full walk (Step 2) and latch **only** on the second such request; after that, stop retrying for the process.
   - **Order matters, and the order is: lock first.** Acquire the feature's own retry lock — `COMPAT_FEATURES["reasoning_field"].retry_lock`, **never** the module alias `_compat_retry_lock` (= `_state.retry_lock`, `compat.py:77`), which is `context_management`'s — with `blocking=False`, **before** touching any counter. On failure, return the upstream result with **no counter mutation and no state change**. Only after a successful acquire do the `(for_selection, count)` read-modify-write under the state lock, and only then enter the walk. This inverts the nearest precedent — `server.py:566-567` mutates the strip counter *before* the non-blocking acquire, deliberately counting concurrent strips — so it has to be stated rather than inferred. The two bullets here previously conflicted, one ordering the increment first and the other forbidding any mutation on contention, and the tester's assertion pins the stricter reading.
   - **Wire the reset explicitly.** When the feature is active for the request and the request's own forwarding pass **ends** 2xx, store `(S, 0)` for `complaints` and clear the full-walk counter, under the state lock, before returning. Step 5 is the step that wires the path, and the reset lives nowhere else: a coder reading only the walk outcomes builds a complaint path with no reset at all, and a pair that once reached two complaints would then switch on a single isolated complaint much later — the transient-complaint defect this design claims to close.
   - Every counter read-modify-write is taken under the learner's state lock.
   - Emit a metadata-only trace event per transition, mirroring `compatibility_learned` (`compat.py:357-368`), with distinct meanings rather than one name reused: `compatibility_learned` when the persist **creates** an entry (a cold pair), `compatibility_switched` when it **changes** an existing entry's `selection`, `compatibility_delisted` when the write **removes** the entry (the successful `"none"` candidate), and `compatibility_latched` on the latch. All carry the same field set (provider, mode, actual_model, feature, tier), plus the selection where one applies — never upstream text.
   - **Nested walk steps re-emit the chat path's per-request events.** Each walk step is a nested `_forward_request_impl` call, so `mode_dispatch` (`server.py:504-513`) and the transform's `cache_control_stripped` / `redacted_thinking_passthrough` / `tool_args_parse_failure` / `content_block_dropped` fire once per step — up to three images for one client request, which the anthropic compatibility retry never produces (its mode branch is skipped). Suppressing them would mean threading another flag into the transform, so this is **documented rather than fixed**: state the bound in `doc/trace-log.html` and note that per-request trace accounting — including `analyze_proxy_trace.py`'s per-model request counts — is inflated for a request that walks.
   - **`_compat_merge_retries` argument order is a trap.** `_compat_merge_retries(original_result, retry_result)` returns the **second** argument's tuple with only index 5 summed (`compat.py:549-553`), so the natural-looking `_compat_merge_retries(result, walk_result)` returns the *walk's* error — the exact outcome the walk-outcome bullet forbids. To return the original result with the retry counts merged, call it as `_compat_merge_retries(walk_result, result)`, or use an equivalent that preserves the original payload.
   → coder verify (auto): the `"anthropic"` literal is gone from both ~684 and the `compat_outbound_present` gate at ~597, **and the `suppress_compat` clause still leads the ~684 condition**; a `response`-mode request still produces a transformed body (the `None`-safe presence check); the walk acquires `COMPAT_FEATURES["reasoning_field"].retry_lock` — not the `_compat_retry_lock` alias — with `blocking=False` **before** any counter mutation, and a contended request mutates no counter and no state; the walk's loop actually iterates up to the budget, so the third candidate is reachable (copying the existing `for _attempt in range(MAX): … break` idiom would silently make budget 2 behave as 1); the retry re-enters with `body`, not `rewritten_body`; the retry passes an explicit candidate; the non-complaint branch **and** the exhausted-budget exit both return the original top-level result via `_compat_merge_retries(walk_result, result)`; a full walk leaves the counter at +1 and persists nothing; the latch is not gated on `COMPAT_REASONING_SWITCH_THRESHOLD`; the end-of-pass 2xx reset is wired for both counters; a trace event exists for each of learned / switched / delisted / latched, with distinct triggers.
   → tester verify: `test_reasoning_transient_complaint_does_not_switch`, `test_reasoning_walk_sends_advanced_candidate`, and the extended `test_compat_single_retry_global` pass; the temporary end-to-end test's bounded-upstream-call assertion holds; all `context_management` behaviours still pass.

6. **Step 6:** Build verification.
   → coder verify (auto): `pip install -e .` succeeds; `python -c "from claude_retry_proxy.server import _forward_request_impl; from claude_retry_proxy.compat import COMPAT_FEATURE, COMPAT_FEATURES; print(sorted(COMPAT_FEATURES))"` succeeds.
   → tester verify: the full suite passes via the custom runner (`python tests/test_claude_proxy.py`), not pytest, **and its total has risen by the number of tests added** — an unregistered test never runs, so a green suite that did not grow proves nothing.

7. **Step 7:** Remediate the six code-review findings against the implementation that Steps 1–6 already produced. These are surgical: every change stays local to the site named, and nothing here restructures the walk or the registry. See the History row for the review report.
   - **W1 — make the threshold clamp real.** `server.py:38` binds `COMPAT_REASONING_SWITCH_THRESHOLD` **by value** at import, so the clamp in `_compat_validate_constants()` (`compat.py:133-138`) rebinds compat's global while the comparison at `server.py:409` keeps the un-clamped value — verified by probe (compat's binding reads 2, server's still reads 1, and stderr says "clamped to 2"). Reference the constant through the module at the comparison site (`compat.COMPAT_REASONING_SWITCH_THRESHOLD`), or have the clamp return the effective value the server stores. Either way the clamp must be **observable where the decision is made** — a guard that warns without guarding is worse than no guard.
   - **W2 — re-read the counter at the persist decision.** Walk entry captures `count = _reasoning_note_complaint(key, selection)` and, as much as ~10 minutes later, persists on that stale local. A concurrent feature-active 2xx request during the walk zeroes the counters under `state.lock` (`server.py:760-761`) but cannot cancel the persist, so the switch lands against a ladder that was just reset — defeating exactly the transient-condition evidence the reset exists to capture. Take the read **and** the comparison under `state.lock` at the decision point: the persist function re-checks the threshold itself, so a reset landing mid-walk wins.
   - **W3 — clear the full-walk counter on a walk candidate's success** (rule change, confirmed with the user; Step 2's latch bullet is the normative statement). Nested walk calls run with `suppress_compat=True`, so `reasoning_active` is False and a walk candidate's 2xx never reaches the reset: full walk → a request whose first attempt complains but whose walk candidate succeeds → full walk latches the pair on two **non-consecutive** requests. Extend the clearing rule to any feature-active success, including a walk candidate's own 2xx. `complaints` stays untouched by walk steps.
   - **S1 — dispatch on the feature name, not by exclusion.** `if active_feature.name != COMPAT_FEATURE:` reads as "anything that is not `context_management` is the reasoning feature". A third chat-mode feature would be routed into the reasoning walk while `_feature_for_mode` keeps silently returning the first match — mis-dispatched *and* unreachable. Match the descriptor's own name, and leave an unregistered feature inert.
   - **S2 — a descriptor must not shadow the shared envelope.** `envelope.update(body)` (`compat.py:253`) merges the descriptor's fields *over* the validated envelope, so a descriptor that echoes `provider`/`mode`/`actual_model`/`feature`/`schema_version` can spoof identity on load — and the state file is the durable artifact. Merge only the descriptor's own fields, or reject a descriptor body that carries an envelope key.
   - **S3 — remove the unreachable limiter, or fix its order.** `reasoning_warned` (`compat.py:920`) can never fire: `_reasoning_latch_notice` sets the latch under the lock and the dispatch path returns early for a latched pair, so the notice runs at most once per key per process. The state-object comment also claims it covers switch events, which `_reasoning_persist_switch` never uses it for. And if the branch ever did fire it would `return` **before** the `compatibility_latched` trace event and stderr warning — dropping the notice the plan requires while still setting the latch. Dropping the dict and its comment is the simplest correct fix.
   - **H1 — validate the entry's `mode` against its descriptor's.** `compat.py:240-245` dispatches on `feature` alone, so an entry carrying `feature: "reasoning_field"` with `mode: "anthropic"` validates and loads under a key no chat request can ever reach. Descriptor validation rejects an entry whose `mode` is not the descriptor's.
   - **H2 — the reset trigger, and the reading this plan now states everywhere.** The implementation resets when the request's own forwarding pass **ends** 2xx, so an upstream 429/503 that the retry loop carried to a 2xx counts. That is the reading adopted: a served request is a served request, and the narrower "only a first-attempt 2xx" alternative would reset the ladder only for requests that never needed the retry loop at all — making the ladder depend on the upstream's transient load rather than on whether the selection works. Keep the code comment and Step 2 in agreement; every occurrence of "first attempt" as the reset trigger has been replaced with the end-of-pass wording.
   → coder verify (auto): setting the threshold constant below 2 and running `_compat_validate_constants()` leaves the **comparison site** reading the clamped value; the persist decision takes its counter read under `state.lock`; a walk candidate's 2xx clears the full-walk counter while leaving `complaints` untouched; dispatch matches the feature name and an unregistered feature is inert; no descriptor field can overwrite an envelope key on load; `reasoning_warned` is gone (or its branch no longer precedes the trace/stderr emission); an entry whose `mode` disagrees with its descriptor is rejected; the reset trigger is stated in the code and matches Step 2.
   → tester verify: a test covers the **persist-via-second-candidate** path (walk step 2 returning 2xx at or above the threshold) — no current test reaches it, both persistence tests persist via step 1 — and the W3 case (full walk, then a walk-succeeded request, then a full walk, must **not** latch).

8. **Step 8:** Remediate the five Step 7-delta code-review findings (report: [review-2026-09-30-2.json](./tmp/reports/2026-09-29-chat-reasoning-field-learner-review-2026-09-30-2.json)). The review ran against the uncommitted worktree scoped to the Step 7 delta — 0 Critical / 0 Warning / 5 Suggestion, verdict "Issues found — non-blocking", and each of the five Step 7 items was re-verified by execution rather than by reading. All five are fixed here rather than deferred: a stale carrier of a rejected reading, and a live-looking dead return, are precisely what a later reader rebuilds the defect from. Surgical — every change stays local to the site named.
   - **L1 — honour the latch where it is acted on, not only where it is checked.** The dispatch site tests the latch at `server.py:781`, *before* `feature.retry_lock` is taken; `_reasoning_outcome` then acquires that lock non-blocking at `:396` and goes straight to `_reasoning_note_complaint` at `:399` with no re-check. A request that reads "not latched" at `:781` while a concurrent request is completing its latching full walk — which latches at `:423-424` while holding that same lock and releases it at `:427` — can acquire the lock the instant the latch owner releases and run one more walk: it advances the strike ladder and, at >= 3 with a 2xx candidate, persists a switch at `:415` on a pair the latch declares terminal. That contradicts Step 2's "while latched: send `none`, issue no retries, mutate no counters, leave the persisted selection untouched". Re-check `_reasoning_is_latched(key)` immediately after the successful acquire and return `result` — the original top-level result, which is what the latch promises the client — when the pair is latched. **The non-latched path must stay byte-identical**, and the dispatch-site check stays: it is what keeps the common latched case from taking the lock at all. The window is narrow and the reviewer could not reproduce it with two live racing requests, so this is hardening, not a fix for an observed failure — but the site is the counter/lock code, which is exactly where a defect survives both a green suite and a source read.
   - **L2 — the last carrier of the superseded reset wording.** `_reasoning_persist_switch`'s docstring (`compat.py:886`) still reads "a concurrent feature-active first-attempt 2xx zeroes the counters in that window". Step 7 H2 adopted the end-of-pass reading everywhere else: `server.py:762-767` and `_reasoning_reset_on_success`'s docstring (`compat.py:826-833`) both say the request's own forwarding pass **ended** 2xx, so an upstream 429/503 the retry loop carried to a 2xx counts. This is the only remaining `first-attempt` occurrence under `src/`, and a future reader taking it literally rebuilds the narrower trigger the plan explicitly rejected. Reword to the end-of-pass phrasing.
   - **L3 — drop the dead return.** `_reasoning_note_complaint` promises "return the new count" (`compat.py:809`) and returns `new_pair[1]` at `:822`, but its only caller — `server.py:399` — discards it, and no test or verification script consumes it. The return existed to feed the walk-entry `count` local that Step 7 W2 removed; leaving a live-looking value invites re-introducing exactly the stale-count capture W2 closed. Drop the return and the docstring clause that promises it.
   - **Not fixed by design — the two correctness hunches, recorded not acted on.** (a) *Reset-on-a-latched-pair:* a request that resolved its selection before a concurrent request latched still reaches `server.py:768` with `reasoning_active` true, so `_reasoning_reset_on_success` can mutate a latched pair's counters. The counters are **unread** while latched and the latch is process-scoped with no in-session clearing, so the mutation has no observable effect — and it is not merely untested but **untestable** through the suite's channels: the plan's own assertion-channel rule (Guidance for Tester) is that these counters live inside the spawned proxy process and cannot be read from the test process. Adding an unobservable behaviour change to the terminal path is edit surface bought with nothing. (b) *Feature-name literal:* `"reasoning_field"` has no named constant, so a drift between `server.py:779`'s literal and the registry key would make the feature silently inert; the end-to-end suite catches that drift, which is why it is a hunch rather than a finding. Both are recorded in Final Results as residuals.
   → coder verify (auto): with the pair latched, calling `_reasoning_outcome` directly — bypassing the dispatch-site check, which is the point — returns the original top-level result and issues **no** upstream call; `grep -rn 'first-attempt\|first attempt' src/claude_retry_proxy/` returns nothing; `_reasoning_note_complaint` returns `None` and its docstring no longer promises a count; the non-latched walk is unchanged, so the three plan verification scripts and the full suite still pass.
   → tester verify: a regression test pins Step 7 **W1**'s core property — the threshold comparison reads the **module binding**, so monkeypatching `compat.COMPAT_REASONING_SWITCH_THRESHOLD` (and the clamp `_compat_validate_constants()` applies) changes the persist outcome, and a by-value binding restored anywhere on that path fails the test. The reviewer's evidence for W1 was the coder round's ad-hoc `tmp/step7-probe.py`, since deleted, so this is the missing durable coverage; case design is the tester's. A deterministic test for **L1** is wanted too — latched pair, `_reasoning_outcome` called directly, no upstream call issued; if the suite's harness makes that infeasible, the tester report must say so explicitly rather than drop the check silently.

## Immediate Actions

Step 7 is complete (coder round `-coder-2026-09-30-2`, tester round `-tester-2026-09-30-3`, suite 345/345 exit 0, doc sweep landed 13:22-13:29). Step 8 is the current round.

**Coder:** Execute Step 8 — L1 (re-check the latch immediately after the retry-lock acquire in `_reasoning_outcome`, returning the original top-level result while latched), L2 (reword the `_reasoning_persist_switch` docstring's "first-attempt 2xx" clause to the end-of-pass phrasing), L3 (drop `_reasoning_note_complaint`'s dead return and the docstring clause promising it). Run the Step 8 auto-checks and re-run the three plan verification scripts. Do **not** touch the two recorded hunches — Step 8 states why they are recorded rather than fixed.

**Tester:** Add the Step 8 coverage — a regression test pinning **W1**'s core property (the threshold comparison reads the module binding, so a monkeypatched `compat.COMPAT_REASONING_SWITCH_THRESHOLD` changes the persist outcome), and, if the harness permits it, a deterministic **L1** test (latched pair, `_reasoning_outcome` called directly, no upstream call issued). Register both in `tests/test_compat.py`'s `ALL_TESTS`, re-run the full suite, and confirm the registered count equals the defined count. If the L1 test proves infeasible with the suite's harness, say so in the tester report rather than dropping it silently.

**Planner:** The doc sweep is complete for Steps 1–7. Step 8's one doc-side item — the self-contradicting sentence at `doc/compatibility.html:80`, which describes the Step 7 clamp fix in the present tense and so contradicts its own next sentence — is fixed by the planner, not the coder.

## Guidance for Planner

Documentation tasks you will execute yourself (not the coder):

- **Doc files to create/update:** `CLAUDE.md`, `README.md`, `doc/compatibility.html`, `doc/provider-modes.html`, `doc/trace-log.html`, `doc/test-catalog.html`, `doc/architecture.html`, `doc/content.html`
- **`.claude/mega-audit-files.json`:** not modified — this plan adds no declared audit locations.
- **When:** after coder and tester finish, with `CLAUDE.md`'s `compat.py` line updated in the same pass.
- **What to sync — sweep, do not enumerate.** Two audit rounds found the earlier spot-lists missing new copies of claims this plan invalidates. For each doc, grep the claim family and reconcile **every** hit; the line numbers below are those already confirmed, not the full set.
  - `doc/compatibility.html` — reframe to the registry; document `reasoning_field` (the switch rule, the `(for_selection, count)` counter and its reset predicate, the **two-consecutive-request** latch and its metadata-only stderr warning, absent-means-none, the keyword-grade matcher and its recall bias, the threat model); update the **states** claim at `:84` ("exactly **two** states"), the **persistence table** at 211-221 (per-descriptor field sets), and the **event count** at `:240` ("All ten events"). **Remove the `COMPAT_FEATURE_MODE` entry from the named-constant list at `:62-65`** — the constant was deleted in Step 7, so the page would otherwise document a name that no longer exists. Two behaviour notes the rewrite must carry, both created by Step 7: the strike threshold is compared **at persist time under the state lock**, not captured at walk entry (so a concurrent reset wins); and a walk candidate's 2xx **clears the full-walk counter** while leaving the strike ladder untouched. Bump "Last updated".
  - `doc/provider-modes.html` — the request-direction row at ~130 **and its adjacent `redacted_thinking` row at ~131** (it promises a placeholder `reasoning_content`, which is now selection-dependent; the `redacted_thinking_passthrough` event itself is unchanged); response-direction prose at ~226; and **`#compat-retry` at 397-414**, which carries three stale claims: "applies to `anthropic` mode only", "A single learnable feature (`context_management`)", and "**a single** upstream attempt".
  - `doc/trace-log.html:96` — repeats the learner event count and asserts list completeness; moves in lockstep with the compatibility.html table. This page also carries the **per-request semantics** of `mode_dispatch` and the chat transform's events, which a walking request now emits up to three times: state the bound and note the effect on per-request accounting for a request that walks. **Precision from the code review, correcting an earlier draft of this bullet:** what a walk multiplies is `mode_dispatch` (`server.py:566`, emitted once per `_forward_request_impl` call) and the chat transform's events — **not** `analyze_proxy_trace.py`'s per-model counts. That tool counts only entries whose `event == "request"` (`scripts/analyze_proxy_trace.py:111`), and `request` events are emitted in `do_POST` alone (`server.py:2482`, `:2516`), which nested walk calls never reach. Documenting the analyzer claim would have described behaviour the code does not have.
  - `doc/test-catalog.html` — the per-test entries at 277-279 still document the removed dual write; add entries for the new tests. On the counts: `:21` **is** a grand total ("334 test functions across 19 files"), and the page's own warn box says it moves with the suite and must be re-counted before quoting — it had already drifted once (322/18). So re-count it (`grep -cE 'def (test_|doc_)' tests/*.py`) rather than leaving it, and update the per-file counts at 80-83, 275, 408, 410.
  - `doc/architecture.html:36-37` — the overview bullet describing the compatibility learner; this file was absent from the earlier doc list entirely.
  - `doc/content.html:38` — the page-index row describing the compatibility page.
  - `CLAUDE.md` — the `compat.py` structure line; the chat-mode request-transform description; the Architecture bullet describing the compatibility retry as the exception to build-once; the doc-index bullet at 312-313.
  - `README.md` — any statement that chat mode echoes thinking as `reasoning_content`, and the "Going deeper" doc-index row at ~555.

## History

| Date | Event | Conclusion | Dismissed |
|------|-------|------------|-----------|
| 2026-09-30 | Code review #2 (reviewer, Step 7 delta) | 5 findings — **0 Critical / 0 Warning / 5 Suggestion**; verdict "Issues found — non-blocking", ready to commit. Scoped to the Step 7 delta against the **uncommitted worktree**, with the HEAD trap called out to the reviewer (`HEAD` is still `d0fd1b8` because nothing is committed, so its prior-review heuristic would otherwise have reported the review "still current"). The reviewer re-verified all five Step 7 items **by execution** rather than by reading, since the coder's evidence (`tmp/step7-probe.py`) had been deleted: W1's clamp reaches the comparison site (forced the constant to 1, ran `_compat_validate_constants()`, confirmed a stored count of 1 does not persist and 2 does), W2's `mutate` closure runs under `state.lock`, W3's reset zeroes only the full-walk counter, S1's dispatch is a name equality with the `active_feature is None` arm unreachable, and S2/H1 hold. It independently re-ran the suite (345/345, exit 0, 345 registered == 345 defined, 0 duplicates), reproducing the tester's result on the unchanged `src/`. Dispositioned as **Step 8**: L1 (re-check the latch after the retry-lock acquire), L2 (the last `first-attempt` occurrence under `src/`), L3 (the dead return). **Recorded, not fixed, with reasons in Step 8:** the reset-on-a-latched-pair hunch — unobservable *and* untestable, since the counters are unread while latched and live inside the spawned proxy, which the plan's own assertion-channel rule forbids the test process from reading — and the feature-name-literal hunch, whose drift the end-to-end suite catches. Report: [review-2026-09-30-2.json](./tmp/reports/2026-09-29-chat-reasoning-field-learner-review-2026-09-30-2.json). | — |
| 2026-09-30 | Code review (reviewer, uncommitted diff) | 8 findings — 4 Warning / 4 Suggestion, none Critical; verdict "Issues found — non-blocking", ready to commit once the counter findings are dispositioned. Verified clean: the registry generalization preserves `context_management` behaviour, the recursion fence holds, `_compat_merge_retries` argument order is correct at all three exits, `_reasoning_present` and the transform's emit condition agree exactly, and the matcher is total for its reachable inputs. Dispositioned in this revision: `unused-compat-imports-server` is **invalid as filed**; the doc-sweep instruction naming `analyze_proxy_trace.py` was **wrong** and is corrected; the pre-existing client-body `RecursionError` gained an Issue Log row. Report: [review-2026-09-30.json](./tmp/reports/2026-09-29-chat-reasoning-field-learner-review-2026-09-30.json). | [unused-compat-imports-server](./tmp/reports/2026-09-29-chat-reasoning-field-learner-unused-compat-imports-server.json) |
| 2026-09-30 | Targeted lens re-check (3 lenses, post-cap) | defect-tracer + conflict-resolver + edge-case-explorer re-run on the revised plan, opus: **1 High / 20 Medium / 12 Low**, against 6/27/19 for the same full round earlier the same day. The one High is a leftover from the pre-fix revision — a Step 5 paragraph claiming "a full walk satisfies `count >= 3` by construction", false ever since walk candidates stopped touching the counter; all three lenses flagged it independently, and the persist/latch branches turn out to be mutually exclusive rather than overlapping. Three more defects drew all three lenses: the counter comparator's operand (compare the **sent** selection against the **stored** one, never the entry's current value); the full-walk counter having no reset on a request that runs no walk, so two non-consecutive walks could latch a pair permanently; and the lock-ordering conflict with the `server.py:566-567` precedent, which mutates before the non-blocking acquire. Adopted on the user's call: the structured `loc` matcher branch, without which a gateway reporting a rejected field only structurally produces no complaint at all. | — |
| 2026-09-30 | Mega-audit iteration 3 (the cap) | 12/12 agents, 0 errors, ~21 min. 6 High / 27 Medium / 19 Low. Report: [mega-audit-2026-09-30-iter3.json](./tmp/reports/2026-09-29-chat-reasoning-field-learner-mega-audit-2026-09-30-iter3.json). Four lenses independently found the same defect: the `complaints` reset predicate was stated three ways, and the literal reading makes the threshold unreachable while the loose reading collapses the three-strike rule after the first switch — fixed by keying the counter to `(for_selection, count)` under the state lock and giving the resolver a `None` sentinel. Two more targeted the latch: one request's walk is one observation repeated three times, not three independent ones, and the matcher's traversal target was unspecified (a raw-body search would match an echoed request). Fixed by requiring two separate full-walk requests and by matching parsed error-message values only. | — |
| 2026-09-30 | Spec revision (redesign) | Withdrew the cross-request episode/tried-set model after four High findings across two audit rounds traced to its interactions with the switch rule and the existing learner's counters. Replaced by the three-state model (selection / complaints / latched) with one rule: try in-request, persist a switch only at 3 consecutive complaints, absent means `none`, and a full failed walk latches to `none` until restart. Removes the two-phase split, the re-entry threshold, and the flag's in-session clearing rule (the session-scoped `latched` flag remains — restart is its only reset). Also drops phrase matching from the complaint matcher in favour of a field-name-only test: the message prose is upstream-authored and drifts, while the field names are our own constants. | — |
| 2026-09-30 | Mega-audit iteration 2 | 12/12 agents, 0 errors, ~24 min. 4 High / 28 Medium / 30 Low. Report: [mega-audit-2026-09-30-iter2.json](./tmp/reports/2026-09-29-chat-reasoning-field-learner-mega-audit-2026-09-30-iter2.json). Highs: the default could never settle (fixed by absent-means-`none` plus the uniform switch rule); the re-entry path was unreachable because `_compat_note_suppressed_request` is gated by `context_management`'s constant (fixed by removing re-entry entirely); a script/spec value conflict on the revision threshold (fixed by removing that constant); and `provider-modes.html`'s "single upstream attempt" (added to the sweep). | — |
| 2026-09-30 | Mega-audit iteration 1 | 12/12 agents, 0 errors, ~17 min. 7 High / 33 Medium / 23 Low. Report: [mega-audit-2026-09-30.json](./tmp/reports/2026-09-29-chat-reasoning-field-learner-mega-audit-2026-09-30.json). All High + Medium were addressed in the following revision, which is itself superseded by the redesign above. | — |
| 2026-09-29 | Initial plan | Replaces the always-both reasoning echo with a learned per-pair selection defaulting to none, generalizing the compatibility learner into a feature registry; five user design decisions recorded in the Summary. | — |

## Plan Metadata

```json
{
  "plan_id": "2026-09-29-chat-reasoning-field-learner",
  "steps": [
    "Step 1: Generalize compat.py into a feature registry",
    "Step 2: Implement the reasoning_field descriptor and policy",
    "Step 3: Parameterize the chat request transform emission by selection",
    "Step 4: Resolve the selection exactly once at request entry",
    "Step 5: Wire the reasoning complaint path and generalize the mode guard",
    "Step 6: Build verification",
    "Step 7: Remediate the six code-review findings",
    "Step 8: Remediate the five Step 7-delta code-review findings"
  ],
  "coder_files": [
    "src/claude_retry_proxy/compat.py",
    "src/claude_retry_proxy/transforms_chat.py",
    "src/claude_retry_proxy/server.py"
  ],
  "tester_files": [
    "tests/test_chat_transform.py",
    "tests/test_compat.py"
  ],
  "doc_files": [
    "CLAUDE.md",
    "README.md",
    "doc/compatibility.html",
    "doc/provider-modes.html",
    "doc/trace-log.html",
    "doc/test-catalog.html",
    "doc/architecture.html",
    "doc/content.html"
  ],
  "verification_scripts": [
    "./tmp/verification/2026-09-29-chat-reasoning-field-learner-step1.py",
    "./tmp/verification/2026-09-29-chat-reasoning-field-learner-step2.py",
    "./tmp/verification/2026-09-29-chat-reasoning-field-learner-step3.py"
  ],
  "repo_mode": "Public",
  "document_overrides": [
    "doc/compatibility.html: learner applies to anthropic-mode providers only (Reason: reasoning_field runs in chat mode)",
    "doc/provider-modes.html#compat-retry: learner applies to anthropic mode only, and the compatibility retry is a single upstream attempt (Reason: per-feature mode scope and per-feature retry budget)",
    "doc/compatibility.html: single learnable feature framing (Reason: generalized to a registry at the user's direction)",
    "doc/compatibility.html: exactly two states / one state-file field set (Reason: per-descriptor state vocabulary and entry fields)",
    "doc/compatibility.html: All ten events below are emitted by the learner (Reason: compatibility_latched and the learned/switch events change the count)",
    "doc/provider-modes.html: request-direction rule thinking blocks -> reasoning_content (Reason: emission is now selection-dependent, default none)",
    "doc/provider-modes.html: reasoning/reasoning_content recognized on the response side (Reason: response side unchanged; request side no longer mirrors both)"
  ]
}
```

## Audit Accumulation

*Counters reset when mega-audit runs. Used by Phase 5 entry trigger.*

| Counter | Value | Last Updated |
|---------|-------|--------------|
| issues_resolved_since_audit | 46 | 2026-09-30 |
| steps_changed_since_audit | 8 | 2026-09-30 |
| files_changed_since_audit | 13 | 2026-09-30 |

*Counters reflect the targeted 3-lens re-check (33) plus the two code reviews whose findings were dispositioned and remediated since (8 + 5 = 13). Everything after that re-check — the Steps 1–7 implementation, the first code review and its Step 7 remediation, the doc sweep, the second code review and its Step 8 remediation — is unaudited by any mega-audit round. **This plan is post-implementation**: 13 files are modified in the worktree against a frozen `HEAD` (`d0fd1b8`), nothing committed.*

## Documentation

Live trace evidence is from `~/.claude/logs/proxy-trace.jsonl` (line 54109 and the 17 matching entries); the originating design is `plans/2026-08-29-fix-chat-mode-thinking-roundtrip.md`; the learner precedent is `tmp/plans/2026-09-01-learn-context-management-compatibility.md`; the latency evidence for the degraded tier (49.9% of requests ≥10 s, 3.8% ≥100 s over 26,013 requests) is aggregate across all tiers.

## Final Results

**Status: complete.** All 8 steps landed. The chat-mode reasoning echo is now a learned per-pair selection instead of an unconditional dual write. **Nothing is committed** — 13 files are modified in the worktree against a frozen `HEAD` (`d0fd1b8`), 2304 insertions / 224 deletions, and the worktree is the artifact.

### What shipped

| Area | Change |
|---|---|
| `src/claude_retry_proxy/compat.py` | The learner generalized into the `COMPAT_FEATURES` registry; the `reasoning_field` descriptor (presence test, field-name matcher with a structured `loc` branch, candidate ladder, switch rule, latch); per-descriptor validation and state vocabulary |
| `src/claude_retry_proxy/server.py` | The candidate walk, the once-per-request selection resolution, name-based dispatch, the post-acquire latch re-check |
| `src/claude_retry_proxy/transforms_chat.py` | The dual write replaced by a selection-parameterized single-field emit |
| `tests/test_compat.py`, `tests/test_chat_transform.py` | The reasoning suite plus the two Step 8 regression tests; `context_management` coverage preserved |
| Docs | `CLAUDE.md`, `README.md`, and the 8 `doc/` pages swept; `test-catalog.html` re-counted |

### Gate evidence

| Gate | Result |
|---|---|
| Full suite (`python tests/test_claude_proxy.py`) | **347 passed, 0 failed, 347 total**, exit 0 — 1 known pre-existing warning (`no-proxy-stop-trace-warning`, a deferred issue) |
| Registration | 347 registered == 347 defined, 0 duplicates (`--list` vs `grep -cE '^def (test_\|doc_)'`) |
| Plan verification scripts | step1 / step2 / step3 all PASS, exit 0 |
| Step 8 probe (`tmp/step8-probe.py`, retained) | 4/4 PASS — including `L1b`, which pins that the non-latched walk is unchanged |
| Mutation check (`tmp/verification/…-t-mutation-step8.py`) | 5/5 — both controls pass, all three mutations caught (def-time threshold capture, by-value copy in `server.py`, latch re-check dropped) |
| Doc-structure checker | PASS — 9 files, no violations |
| Doc anchor checker | PASS — 166 references resolved, 8 files secret-scanned, no secret shapes |
| `pip install -e .` | **Not executed this round** — it needs interactive approval an unattended round cannot supply. The editable install is confirmed live by other means (`import claude_retry_proxy.server` resolves to this repo's `src/`, not a snapshot copy), so the Step 6 auto-check is satisfied by evidence rather than by execution. |

### Review and audit record

Three mega-audit iterations (7 / 4 / 6 High) and one targeted 3-lens re-check (1 High) shaped the design before implementation; the re-check's single High was a residue of my own fix, not a design flaw. Two code reviews followed implementation — the first on the diff (8 findings: 4 Warning / 4 Suggestion), the second scoped to the Step 7 delta (5 findings, all Suggestion, verdict "ready to commit"). **Every finding from both reviews was dispositioned**: 8 remediated in Step 7, 3 in Step 8, 2 recorded as hunches with reasons, 1 resolved as invalid-as-filed (`unused-compat-imports-server` — the names are deliberate re-exports the suite consumes through the server module), and 1 carried as the open `client-body-recursionerror-no-response` issue.

### Residuals — stated, not smoothed over

1. **Step 8 shipped without a third review pass.** Its three items are the reviewer's own suggestions, one of them a comment, and the reviewer had already returned "ready to commit"; the suite, the verification scripts, the probe, and the mutation check are the gate instead. This is a judgment call, not a verified equivalence.
2. **A ragged docstring wrap at `compat.py:886`** — my L2 reword left `counters in that window. A` / `reset landing mid-walk must win`. Content is correct; only the line breaking is ugly. The planner's edit to `src/` is denied by permission settings, so it was left rather than routed around.
3. **Two correctness hunches recorded, not fixed,** each with its reason in Step 8: the reset-on-a-latched-pair mutation (unobservable — counters are unread while latched — and untestable through the plan's own assertion channel) and the unnamed `"reasoning_field"` literal (drift is caught by the end-to-end suite).
4. **Steps 1–6 were authored by a coder round that exited without writing a report.** No step therefore rests on an unreported round's self-assertion: the following coder round verified it independently, both reviews read it, and the suite exercises it.
5. **The temporary end-to-end test is retained** at `tests/temp/test_reasoning_e2e_2026-09-30.py` (1/1 separately; deliberately outside the aggregator). Its cleanup condition — "delete after the plan completes" — has now been reached.
6. **Audit Accumulation shows 46 issues / 8 steps / 13 files changed with no mega-audit round since**, because every mega-audit ran pre-implementation. A re-audit now would audit plan prose the reviews have already superseded, so it was not run; the counters are left honest rather than reset.
7. **Pre-existing deferred issues are untouched** — `image-content-blocks-chat-mode`, `no-proxy-stop-trace-warning`, `proxy-stderr-append-stale-tail`, `port-default-collision-hazard`, `extract-model-raises-on-non-object-json`, plus the `client-body-recursionerror-no-response` this plan filed.

**Commit:** not made. Untracked in the tree is `.codegraph/` (the CodeGraph index), which should not be staged.