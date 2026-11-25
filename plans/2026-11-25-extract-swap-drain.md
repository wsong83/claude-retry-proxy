# Plan: Extract the config-swap drain protocol into swap_drain.py (owned-state conversion, drain half)

**Plan ID:** 2026-11-25-extract-swap-drain
**Created:** 2026-11-25

<!-- ## Immediate Actions: absent — terminal plan; no per-role directives remain. -->

## Issue Log

Rows ordered newest-first (latest issues at top). New issues are prepended; resolved issues stay in place with updated status.

| Issue | Status | Found | Resolved | Resolved By |
|-------|--------|-------|----------|-------------|
| [grace-comment-invariant] | Resolved | 2026-11-25 | 2026-11-25 | [coder r2, Step 8c](./tmp/reports/2026-11-25-extract-swap-drain-coder-2026-11-25-r2.json) |

*(grace-comment-invariant: the grace comment's "evictable straggler is always evicted before the drain exits" claim fails for anthropic-mode silent streams under production defaults — 32 s quiet window vs ≤120 s read boundary; holds only for wakes bounded under the window, e.g. chat-drain budgets. Raised by mega-audit hunch; correction prescribed as Step 8 sub-step 8c.)*

## Guidance for Coder

**Files to modify:** `src/claude_retry_proxy/error_body.py` (new), `src/claude_retry_proxy/forwarder.py`, `src/claude_retry_proxy/server.py`, `src/claude_retry_proxy/admin_api.py`, `src/claude_retry_proxy/chat_sse.py`, `src/claude_retry_proxy/swap_drain.py` (new). Source only — no tests, no docs, no CLAUDE.md/README/doc files.

**Hard boundaries:** never write or edit any file under `tests/`; never write `CLAUDE.md`, `README.md`, or `doc/**`; never "fix" a pre-existing defect inside moved or converted text (file it in the session report instead). `git add` each new module the moment it exists — untracked files do not survive `git clean`.

**Commit discipline (red interval):** *Revised after round 1 — the coder lane's permission layer hard-denies `git commit`, so there are NO interim commits; all of Steps 1–9 land in the working tree and ride the plan's single `/update-and-commit` consolidation commit.* The red interval is a property of the working tree, not of git state: from Step 2 onward `import claude_retry_proxy.server` fails until Step 6 lands, and the suite stays red until Step 7 (tester) lands. Gates are the per-step evidence; the green boundary that matters is tester-green (Step 7) and gate-green (Steps 1, 8).

**Module-surface count table** (exact):

| Kind | Change | Count |
|---|---|---|
| Behavioral | observable behavior changes | **0** — every lock scope, acquisition pairing, atomicity pattern, and value semantics is preserved; new tests add coverage only |
| Module-surface | `error_body.py` created | 1 module, 1 exported name (`_error_body`) |
| Module-surface | forwarder loses top-level drain defs | 7 (`_touch_upstream_activity`, `_drain_for_swap`, `_note_swap_eviction`, `_swap_epoch_changed`, `_swap_chain_abort`, `_interruptible_sleep`→re-homed, `_swap_abort_tuple`→re-homed) |
| Module-surface | forwarder loses module globals | 8 state globals (`_config_lock`, `_inflight_count`, `_config_swapping`, `_swap_done`, `_config_epoch`, `_last_upstream_activity`, `_swap_started_at`, `_swap_evictions`) |
| Module-surface | forwarder gains | `class _SwapDrain` (11 methods + `lock` property), singleton `_drain`, `_SWAP_QUIET_GRACE`, `_interruptible_sleep`, `_swap_abort_tuple` (Steps 2), then re-export `from .swap_drain import (_drain, _interruptible_sleep, _swap_abort_tuple)` (Step 8) |
| Module-surface | server.py from-import shrinks | 3 names removed (`_note_swap_eviction`, `_swap_epoch_changed`, `_touch_upstream_activity`) |
| Module-surface | admin_api.py from-import shrinks | 1 name removed (`_drain_for_swap`) |
| Module-surface | chat_sse.py from-import shrinks | 3 names removed (same trio as server) |
| Module-surface | `swap_drain.py` created (Step 8) | class + singleton + 2 functions + `_SWAP_QUIET_GRACE`; forwarder re-imports exactly 3 names |
| Implementation | `global` statements removed | 3 (forwarder.py:119 `_touch_upstream_activity` ×1 name, :155 `_drain_for_swap` ×4 names, :191 `_note_swap_eviction` ×1 name; `_swap_epoch_changed`/`_swap_chain_abort` carried none; bodies become `self.` field access) |

**Step-by-step with verification:** each step below carries its exact edits. Coder checks are tagged `(auto)` (self-verified) or `(scripted)` (run the named script from the project root). The red-interval steps 2–6 are verified by one shared end-state gate (`-shape.py`), which can only pass once all of Steps 2–6 have landed.

---

1. **Step 1:** Extract `_error_body` verbatim into the new leaf `src/claude_retry_proxy/error_body.py` (prerequisite for Step 8's import direction: `swap_drain` may not import its parent forwarder, and `_swap_abort_tuple` calls `_error_body`).
   - Create `src/claude_retry_proxy/error_body.py` with exactly this content (the function body is byte-identical to forwarder.py's current `def _error_body` block):
     ```python
     """Client-facing error bodies in the Anthropic standard envelope.

     Shared leaf: every error the proxy generates itself — forwarder give-up
     paths, stream error frames, admin refusals — serializes through
     `_error_body`. Stdlib-only (json); imported by forwarder (and, from
     Step 8, by swap_drain), re-exported through forwarder for server,
     chat_sse, and admin_api; imports none of its consumers.
     """

     import json


     def _error_body(error_type, code, message, request_id=None):
         """Build a client-facing error body in the Anthropic standard envelope.

         Returns bytes for
         {"type":"error","error":{"type":…,"code":…,"message":…},"request_id":…}.
         The top-level shape (type/error/request_id) is the Anthropic standard
         error envelope; error.type is a coarse taxonomy category while
         error.code is the proxy-discriminator extension carrying the fine
         detail (the former nested type strings ride there verbatim).
         The request_id key is omitted entirely (not null) when None.
         Serialized with json.dumps — never string interpolation — because
         message carries client-controlled text (unrecognized_model) and
         exception text (upstream_unreachable); both must stay JSON-escaped.
         """
         envelope = {
             "type": "error",
             "error": {"type": error_type, "code": code, "message": message},
         }
         if request_id is not None:
             envelope["request_id"] = request_id
         return json.dumps(envelope).encode("utf-8")
     ```
     Calibration note: the def block above — docstring included — is byte-identical to forwarder's current `_error_body` (verified by diff against HEAD at plan time). The `-errorbody.py` gate pins the whole def segment byte-identically against HEAD's forwarder and pins the two degradation-path literals (`return json.dumps(envelope).encode("utf-8")`, the `if request_id is not None:` branch) as substring checks.
   - In `src/claude_retry_proxy/forwarder.py`: delete the `def _error_body(...)` block (landmark: starts at the `def _error_body(error_type, code, message, request_id=None):` line, ends at the `return json.dumps(envelope).encode("utf-8")` line, followed by two blank lines and the `# Whitelisted paths and methods` comment, which stays) and add to the import block (after `from .model_rewrite import …`):
     ```python
     from .error_body import _error_body
     ```
   - `git add src/claude_retry_proxy/error_body.py` immediately.
   - Consumers (`server.py`, `chat_sse.py`, `admin_api.py`) are **not edited** in this step — their `from .forwarder import …, _error_body, …` lines keep working through the re-export.
   → coder verify (auto): `_error_body` in `error_body.py` accepts `(error_type, code, message, request_id=None)` and returns `json.dumps(envelope).encode("utf-8")`; zero `def _error_body` remaining in `forwarder.py`
   → coder verify (scripted): `python3 ./tmp/verification/2026-11-25-extract-swap-drain-errorbody.py` — exit 0

2. **Step 2:** Replace forwarder's drain region with the `_SwapDrain` class, the `_drain` singleton, and the two retained module functions. **This opens the red interval — commit nothing.**
   - In `src/claude_retry_proxy/forwarder.py`, delete **two disjoint spans** (re-verify landmarks before cutting; a drifted landmark is a stop-and-report, not an improvisation):
     - Span A: from the line `# Thread-safe config access (read by worker threads, written by admin API)` (currently ~line 59) through `_SWAP_QUIET_GRACE = 2.0` (currently ~line 75). The blank lines around the `_rng_local` island that follows stay.
     - Span B: from the banner line `# ---------------------------------------------------------------------------` that opens `# Config-swap drain helpers` (currently ~line 91) through the final line of `_swap_abort_tuple` (`        None, time.time() - total_start, retries, tier, provider_name, actual_model)`, currently ~line 252). The `_DISCONNECT_ERRORS` block above Span A and the `random`/`_rng` island between the spans stay untouched.
   - Insert the following text where Span B was, as ONE contiguous block (Span A is not replaced — its contents now live in `__init__`; the grace comment and `_SWAP_QUIET_GRACE` constant re-home into the new block). **Byte-exact, including comments and docstrings.** The comment blocks are carried from the tree with exactly four declared renames, all in the banner: title "Config-swap drain helpers" → "Config-swap drain protocol"; "the existing `_config_swapping` gate" → "the swapping flag checked inside admit()"; "(forward_request waits on `_swap_done` with no timeout)" → "(admit() waits on the completion event with no timeout)"; "(never checks `_config_swapping`)" → "(never checks the swapping flag)". The grace comment block is carried **verbatim** from forwarder 72–74 — its invariant claim is pre-existing tree text preserved by the plan, not authored here (if it is wrong under production defaults that is a pre-existing doc defect to file separately, not fix in this block). Method docstrings carry the originals with only `global`-era phrasing swapped to field phrasing where the original sentence named a bare global:
     ```python
     # ---------------------------------------------------------------------------
     # Config-swap drain protocol
     # ---------------------------------------------------------------------------
     #
     # The drain replaces the old wall-clock deadline: new admissions pause (the
     # swapping flag checked inside admit()) while the drain waits for the
     # in-flight set to empty on count alone, or for the SHARED activity clock
     # to read total quiet for a full budget plus _SWAP_QUIET_GRACE. Retry-backoff
     # chains abandon at the press instead of being waited out, and silent
     # stragglers are evicted with a retryable config_swap_restart once the epoch
     # bumps.
     #
     # ACCEPTED RISK: an unbounded drain blocks every new admission for as long
     # as it runs (admit() waits on the completion event with no timeout). The
     # escape hatches are `claude-retry-proxy stop` (kills the process) and
     # POST /admin/shutdown (never checks the swapping flag); nothing else
     # releases writers. The residual scenario that never terminates is an
     # upstream that is stuck but keeps sending bytes, keeping the clock fresh
     # forever. Rollback for this design is `git revert` of its commit plus a
     # restart — there is no env var that restores the old bounded drain
     # (PROXY_SWAP_SILENCE_TIMEOUT tunes the budget; it cannot re-introduce the
     # 30 s wall-clock abort).

     # The drain's total-quiet window exceeds the armed stream wake (both keyed to
     # the same shared clock) by this margin, so an evictable straggler is always
     # evicted before the drain exits and `drained` stays a fact rather than a race.
     _SWAP_QUIET_GRACE = 2.0


     class _SwapDrain:
         """Owned state and operations for the config-swap drain protocol.

         One instance exists, the module singleton `_drain` below. Every piece
         of drain state lives on it: the RLock that also guards config-document
         reads and writes, the in-flight counter, the swapping flag, the
         completion event, the epoch, the shared upstream-activity clock, the
         press timestamp, and the eviction counter. Cross-module access is
         attribute-form through the singleton; the state fields themselves are
         never re-exported as module names — a rebound name re-exported as an
         alias would go stale on its next assignment, while the singleton
         reference cannot.
         """

         def __init__(self):
             # Thread-safe config access (read by worker threads, written by
             # the admin API) — the same lock the drain protocol uses, so
             # admissions, presses, and config snapshots stay atomic with
             # each other.
             self._config_lock = threading.RLock()
             self._inflight_count = 0  # Number of requests currently in-flight
             self._config_swapping = False  # True when config swap is in progress
             self._swap_done = threading.Event()  # Signaled when swap completes
             self._config_epoch = 0  # Incremented on every successful config swap
             self._last_upstream_activity = 0.0  # Timestamp of the most recent upstream byte, any request
             self._swap_started_at = None  # Timestamp of the current press; None when no swap runs
             self._swap_evictions = 0  # Evictions since the last press; `drained` == 0 of them

         @property
         def lock(self):
             """The config-swap lock, for sections spanning config and drain state.

             Admin handlers hold it across config-document reads/writes plus
             epoch checks so a swap can never interleave (the Phase 3
             sections in admin_api). Drain-state-only operations take the
             lock inside their methods instead.
             """
             return self._config_lock

         def admit(self, snapshot_fn):
             """Pause behind an in-progress swap, then admit one request.

             Blocks while a swap is in progress (waiting on the completion
             event) and admits only when the swapping flag is clear:
             snapshots (config, vendors) and increments the in-flight
             counter in the SAME lock acquisition — reading config after
             releasing the lock could observe a post-swap document beside a
             pre-swap epoch (reviewer-drain-swap-race fix). snapshot_fn is
             invoked only inside the admitting acquisition and must not
             block; a raise from it propagates BEFORE the counter is
             touched, so no phantom admission can leak (the caller's
             release() only runs after admit() returns). It returns
             (config, vendors). Returns
             (config_snapshot, vendors_snapshot, epoch_snapshot).
             """
             while True:
                 with self._config_lock:
                     if not self._config_swapping:
                         # No swap in progress: snapshot first (a raising
                         # snapshot_fn must not leave a phantom admission),
                         # then increment the counter — all in this one
                         # acquisition.
                         config_snapshot, vendors_snapshot = snapshot_fn()
                         self._inflight_count += 1
                         epoch_snapshot = self._config_epoch
                         return config_snapshot, vendors_snapshot, epoch_snapshot
                 # Swap in progress - wait for it to complete
                 self._swap_done.wait()

         def release(self):
             """Decrement the in-flight counter when a request completes.

             Paired with admit(): under the admission protocol the count
             never goes negative — every release matches one admitted
             request (server's try/finally).
             """
             with self._config_lock:
                 self._inflight_count -= 1

         def touch(self):
             """Record the most recent upstream byte from any in-flight request.

             The drain reads this single shared clock to decide when everything left
             is silent. A bare store with no lock: a stale read only makes the drain
             wait marginally longer, and one assignment cannot tear under the GIL.
             """
             self._last_upstream_activity = time.time()

         def note_eviction(self, phase, request_id, **fields):
             """Count one eviction and log its swap_abort trace event.

             Called immediately before an evicted request returns its retryable
             error. The stream phase carries tier + provider and no model — the
             stream helpers do not receive actual_model.
             """
             with self._config_lock:
                 self._swap_evictions += 1
             event = {
                 "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                 "event": "swap_abort",
                 "phase": phase,
                 "request_id": request_id,
             }
             event.update(fields)
             log_trace(event)

         def epoch_changed(self, entry_epoch):
             """True when a swap completed after this request was admitted.

             Such a request must never deliver an old-routing result. Reads the
             epoch without the lock — a single int read is atomic under the GIL,
             and a stale read only defers the eviction to the next checkpoint.
             """
             return entry_epoch is not None and self._config_epoch != entry_epoch

         def chain_abort(self, entry_epoch):
             """True when a retry-backoff chain must abandon toward the left provider.

             Chains additionally abandon at the press, not only at the completed
             swap: they are proxy-managed idling with no generation work, and
             waiting them out is what made a swap issued under rate limiting fail.
             """
             return self._config_swapping or self.epoch_changed(entry_epoch)

         def drain(self):
             """Pause admissions and wait for in-flight work to drain (Phases 1-2).

             Single-flight: the guard and the press share ONE lock acquisition, so a
             second press arriving at any point cannot pass — there is no window
             between deciding and pressing in which a concurrent press could slip
             through. Returns None when a swap is already in progress; the caller
             returns its 409 refusal and enters no drain. Otherwise returns
             (drained, inflight_at_press, waited_s):
               - `drained` is `_swap_evictions == 0` — "nothing was evicted", NOT
                 "the count reached zero". A post-press eviction can decrement the
                 count before the poll sees it, so keying on the exit branch would
                 make the field a race rather than a fact.
               - `inflight_at_press` is the count at the press, independent of which
                 exit fires.
               - `waited_s` is the drain wall-clock.

             Two exits, both by construction safe: count zero (everything left the
             set), or no upstream byte from anyone for budget + _SWAP_QUIET_GRACE —
             at which point every remaining request is silent >= budget, because the
             clock resets on ANY byte. No wall-clock total: live work is waited to
             completion however long it takes.

             OPERATIONAL NOTE — the accepted risk this creates: while this drain runs,
             every new admission is blocked (admit() waits on the completion event with
             no timeout). The immediate escapes are `claude-retry-proxy stop` (kills
             the process) and `POST /admin/shutdown` (never checks the swapping flag);
             nothing else releases writers. The systemic escape is reverting this
             change (`git revert` of its commit) plus a restart:
             PROXY_SWAP_SILENCE_TIMEOUT tunes the budget only — no env var restores
             the old bounded drain.
             """
             with self._config_lock:
                 if self._config_swapping:
                     # Single-flight refusal: an owner already holds the swap. Taken
                     # under the SAME acquisition that sets the flag below, so the
                     # check-then-act window that let two presses both enter a drain
                     # is gone.
                     return None
                 self._config_swapping = True
                 self._swap_done.clear()
                 started_at = time.time()
                 self._last_upstream_activity = started_at
                 self._swap_started_at = started_at
                 inflight_at_press = self._inflight_count
                 self._swap_evictions = 0
             quiet_window = SETTINGS.swap_silence_timeout + _SWAP_QUIET_GRACE
             while True:
                 with self._config_lock:
                     inflight = self._inflight_count
                     last_activity = self._last_upstream_activity
                     evictions = self._swap_evictions
                 if inflight == 0:
                     break
                 if time.time() - last_activity >= quiet_window:
                     break
                 time.sleep(0.1)
             return evictions == 0, inflight_at_press, time.time() - started_at

         def status_snapshot(self):
             """Atomic read of the swap-status fields for GET /admin/api/swap-status.

             Each nullable field is guarded on its own source, not on
             `swapping`: a `time.time() - None` TypeError would 500 the
             endpoint, and the admin page swallows poll failures — the bug
             would degrade silently into a dead status line. All fields are
             read in ONE lock acquisition.
             Returns (swapping, waited_s, inflight, silence_s).
             """
             with self._config_lock:
                 swapping = self._config_swapping
                 now = time.time()
                 waited_s = (now - self._swap_started_at) \
                     if (swapping and self._swap_started_at is not None) else None
                 silence_s = (now - self._last_upstream_activity) \
                     if (swapping and self._last_upstream_activity) else None
                 inflight = self._inflight_count
             return swapping, waited_s, inflight, silence_s

         def bump_epoch(self):
             """Bump the epoch — the eviction signal for old-snapshot stragglers.

             Reentrant on purpose: both callers hold the config-swap lock
             across a larger install section and call this inside it
             (threading.RLock permits same-thread re-entry).
             """
             with self._config_lock:
                 self._config_epoch += 1

         def complete(self):
             """Phase 4: clear the swap flag and signal completion.

             The timestamp clears in the SAME acquisition: the status
             endpoint must never observe swapping True with a None
             started_at.
             """
             with self._config_lock:
                 self._config_swapping = False
                 self._swap_started_at = None
                 self._swap_done.set()


     _drain = _SwapDrain()


     def _interruptible_sleep(seconds, epoch):
         """Sleep up to `seconds`, in slices, aborting on a swap press.

         Returns True when the chain must abandon (a swap started at any point
         during the wait), False when the full delay elapsed normally.
         """
         deadline = time.time() + seconds
         while True:
             if _drain.chain_abort(epoch):
                 return True
             remaining = deadline - time.time()
             if remaining <= 0:
                 return False
             time.sleep(min(0.25, remaining))


     def _swap_abort_tuple(request_id, total_start, retries, tier, provider_name,
                           actual_model):
         """The retryable give-up result for a request evicted by a config swap.

         Mirrors the 429/503 give-up return-tuple shape exactly (nine elements,
         empty headers, no streamed body), so do_POST's streamed flag and
         _send_response handle it identically.
         """
         return (503, {}, _error_body(
             "api_error", "config_swap_restart",
             "config swap in progress: this request was restarted; the client should retry",
             request_id),
             None, time.time() - total_start, retries, tier, provider_name, actual_model)
     ```
   → coder verify (auto): `class _SwapDrain` defined in `forwarder.py` with methods `admit, release, touch, note_eviction, epoch_changed, chain_abort, drain, status_snapshot, bump_epoch, complete` and property `lock`; `_drain = _SwapDrain()` at module level; zero `global` statements naming any of the 8 state names
   → coder verify (scripted): the shared `-shape.py` gate (runs after Step 6; expected RED until then)

3. **Step 3:** Repoint `src/claude_retry_proxy/server.py` onto the `_drain` surface (exact old→new; line numbers are today's — re-verify by landmark, they may shift if earlier steps touched the file, which they did not):
   - Import block (lines 44–54): from the `from .forwarder import (...)` list remove `_note_swap_eviction`, `_swap_epoch_changed`, `_touch_upstream_activity` (the list re-wraps; the surviving names keep alphabetical order — new list head: `(_DISCONNECT_ERRORS, _client_user_agent, _error_body, _forward_request_impl, _resolve_extra_request_headers, _retry_nudge_arm, _retry_nudge_check, _retry_nudge_messages_bytes, _retry_nudge_remember, _rewrite_json_response, _rewrite_sse_event, _rng, _trace_model, CLIENT_USER_AGENT_MAX_CHARS, CLIENT_USER_AGENT_TRUNCATION_MARKER, RETRY_NUDGE_TTL_SECONDS, compute_delay, …` — everything after `compute_delay` unchanged).
   - Admission block (lines 84–99) — replace the whole comment-plus-while block:
     - OLD:
       ```python
       # Drain-and-swap: snapshot config state at request start
       # If a config swap is in progress, wait for it to complete before proceeding
       # Snapshot config and vendors together under the same lock
       # to prevent race where config is read before lock but vendors is
       # snapshotted inside lock (reviewer-drain-swap-race fix).
       while True:
           with forwarder._config_lock:
               if not forwarder._config_swapping:
                   # No swap in progress - increment counter and snapshot all state together
                   forwarder._inflight_count += 1
                   config_snapshot = runtime_state._current_config
                   vendors_snapshot = runtime_state._vendors
                   epoch_snapshot = forwarder._config_epoch
                   break
           # Swap in progress - wait for it to complete
           forwarder._swap_done.wait()
       ```
     - NEW:
       ```python
       # Drain-and-swap: snapshot config state at request start. The snapshot
       # callback runs inside the admitting lock acquisition — config, vendors,
       # and epoch are read together so a completed swap can never leave this
       # request holding a pre-swap document with a post-swap epoch
       # (reviewer-drain-swap-race fix).
       config_snapshot, vendors_snapshot, epoch_snapshot = forwarder._drain.admit(
           lambda: (runtime_state._current_config, runtime_state._vendors))
       ```
   - Release block (lines 103–106) — OLD:
       ```python
       finally:
           # Decrement counter when request completes (success or failure)
           with forwarder._config_lock:
               forwarder._inflight_count -= 1
       ```
     NEW:
       ```python
       finally:
           # Decrement counter when request completes (success or failure)
           forwarder._drain.release()
       ```
   - Line 207 and line 450: `_note_swap_eviction(` → `forwarder._drain.note_eviction(` (both sites are the `evict_stream`-style closers; keep arguments verbatim).
   - Lines 270, 336, 365, 448: `_touch_upstream_activity()` → `forwarder._drain.touch()`
   - Lines 271, 337, 366, 449: `if _swap_epoch_changed(epoch):` → `if forwarder._drain.epoch_changed(epoch):`
   - Lines 305, 355, 387: `if forwarder._config_swapping or _swap_epoch_changed(epoch):` → `if forwarder._drain.chain_abort(epoch):`
   → coder verify (auto): zero occurrences of the module-attribute chains `forwarder._config_lock|forwarder._config_swapping|forwarder._config_epoch|forwarder._swap_done|forwarder._inflight_count` in `server.py`; zero occurrences of `_note_swap_eviction|_swap_epoch_changed|_touch_upstream_activity` anywhere in `server.py`; exactly 15 `forwarder._drain.` references: `admit(` ×1, `release()` ×1, `note_eviction(` ×2, `touch()` ×4, `epoch_changed(` ×4, `chain_abort(` ×3
   → coder verify (scripted): shared `-shape.py` gate

4. **Step 4:** Repoint `src/claude_retry_proxy/admin_api.py` (line numbers are today's — **re-verify every anchor by landmark before cutting**; this step touches BOTH press handlers: the switch at ~399 and the reload at ~596):
   - Line 27: `from .forwarder import _drain_for_swap, _error_body` → `from .forwarder import _error_body`
   - Status block (lines 147–155) — replace the whole `with forwarder._config_lock:` block and its guard comment:
     - OLD:
       ```python
       # Each nullable field is guarded on its own source, not on
       # `swapping`: a `time.time() - None` TypeError would 500 the
       # endpoint, and the admin page swallows poll failures — the bug
       # would degrade silently into a dead status line.
       with forwarder._config_lock:
           swapping = forwarder._config_swapping
           now = time.time()
           waited_s = (now - forwarder._swap_started_at) \
               if (swapping and forwarder._swap_started_at is not None) else None
           silence_s = (now - forwarder._last_upstream_activity) \
               if (swapping and forwarder._last_upstream_activity) else None
           inflight = forwarder._inflight_count
       ```
     - NEW:
       ```python
       swapping, waited_s, inflight, silence_s = forwarder._drain.status_snapshot()
       ```
     (The guard rationale now lives in `status_snapshot`'s docstring; the following `json.dumps({...})` block is unchanged — its four names plus `budget_s` keep their spellings.)
   - Line 399 (switch press): `drain = _drain_for_swap()` → `drain = forwarder._drain.drain()`; update the adjacent comment line 402–403 "share one lock acquisition inside _drain_for_swap" → "share one lock acquisition inside _drain.drain()".
   - Line 596 (reload press): `drain = _drain_for_swap()` → `drain = forwarder._drain.drain()`; update the adjacent comment line 599 "share one lock acquisition inside _drain_for_swap" → "share one lock acquisition inside _drain.drain()".
   - Lines 121, 357, 415, 520, 611: `with forwarder._config_lock:` → `with forwarder._drain.lock:`
   - Line 358: `validated_epoch = forwarder._config_epoch` → `validated_epoch = forwarder._drain._config_epoch`
   - Line 426: `and forwarder._config_epoch != validated_epoch):` → `and forwarder._drain._config_epoch != validated_epoch):`
   - Line 462: `forwarder._config_epoch += 1` → `forwarder._drain.bump_epoch()`
   - Line 527: `gated_epoch = forwarder._config_epoch` → `gated_epoch = forwarder._drain._config_epoch`
   - Line 612 (reload Phase 3 check): `if forwarder._config_epoch != gated_epoch:` → `if forwarder._drain._config_epoch != gated_epoch:`
   - Line 652 (reload install): `forwarder._config_epoch += 1` → `forwarder._drain.bump_epoch()`
   - Completion blocks (lines 480–483 switch, 658–661 reload) — each becomes one call; the carried comment stays:
     - OLD (both sites):
       ```python
       with forwarder._config_lock:
           forwarder._config_swapping = False
           forwarder._swap_started_at = None
           forwarder._swap_done.set()
       ```
     - NEW (both sites):
       ```python
       forwarder._drain.complete()
       ```
   → coder verify (auto): zero occurrences of the module-attribute chains `forwarder._config_lock|forwarder._config_swapping|forwarder._config_epoch|forwarder._swap_done|forwarder._inflight_count|forwarder._swap_started_at|forwarder._last_upstream_activity` in `admin_api.py`; zero occurrences of `_drain_for_swap` anywhere in `admin_api.py` (code and comments); exactly: `status_snapshot()` ×1, `_drain.drain()` ×2 (switch 399 + reload 596), `_drain.lock` ×5, `_drain._config_epoch` ×4, `bump_epoch()` ×2, `complete()` ×2
   → coder verify (scripted): shared `-shape.py` gate

5. **Step 5:** Repoint `src/claude_retry_proxy/chat_sse.py`:
   - Import (lines 19–21): `from .forwarder import (_DISCONNECT_ERRORS, _error_body, _note_swap_eviction, _retry_nudge_arm, _retry_nudge_messages_bytes, _swap_epoch_changed, _touch_upstream_activity)` → `from .forwarder import (_DISCONNECT_ERRORS, _error_body, _retry_nudge_arm, _retry_nudge_messages_bytes)`
   - Line 489: `_note_swap_eviction("stream", request_id, tier=tier, provider=provider)` → `forwarder._drain.note_eviction("stream", request_id, tier=tier, provider=provider)`
   - Lines 659, 672, 677, 682: `if _swap_epoch_changed(epoch):` → `if forwarder._drain.epoch_changed(epoch):`
   - Line 666: `if forwarder._config_swapping or _swap_epoch_changed(epoch):` → `if forwarder._drain.chain_abort(epoch):`
   - Line 681: `_touch_upstream_activity()` → `forwarder._drain.touch()`
   → coder verify (auto): zero occurrences of the removed import names or `forwarder._config_swapping` in `chat_sse.py`; exactly 7 `forwarder._drain.` references (1 note_eviction, 4 epoch_changed, 1 chain_abort, 1 touch)
   → coder verify (scripted): shared `-shape.py` gate

6. **Step 6:** Repoint forwarder's own call sites onto the module-local `_drain` (bare name — same module; 20 sites):
   - `_swap_epoch_changed(epoch)` → `_drain.epoch_changed(epoch)` at lines 1195, 1222, 1360, 1414, 1470
   - `_note_swap_eviction(` → `_drain.note_eviction(` at lines 1196, 1223, 1262, 1361, 1415, 1471, 1497
   - `_touch_upstream_activity()` → `_drain.touch()` at lines 377 (inside `_read_capped`'s `for chunk in resp.iter_raw():` loop — the give-up path's capped upstream-error-body reader), 1215, 1253, 1331, 1391, 1445
   - `_swap_chain_abort(epoch)` → `_drain.chain_abort(epoch)` at lines 1258, 1493
   - `_interruptible_sleep(` and `_swap_abort_tuple(` call sites (lines 1260, 1495 / 1198, 1225, 1265, 1364, 1418, 1473, 1500) are **unchanged** — both keep their names and signatures.
   → coder verify (auto): zero occurrences of `_swap_epoch_changed|_note_swap_eviction|_touch_upstream_activity|_swap_chain_abort` anywhere in `forwarder.py`; exactly 20 sites repointed (5 epoch_changed, 7 note_eviction, 6 touch, 2 chain_abort); `_interruptible_sleep(`/`_swap_abort_tuple(` call-site counts unchanged (2 and 7)
   → coder verify (scripted): `python3 ./tmp/verification/2026-11-25-extract-swap-drain-shape.py` — must now exit 0 (Steps 2–6 complete). The suite is still RED (tests not yet rewritten) — that is the red interval working as designed; do not commit.

7. **Step 7:** *(tester — see Guidance for Tester; listed here for execution order.)* Rewrite the test surface onto `_drain`, migrate the monkeypatch targets and save-blocks, add the behavioral tests. Ends the red interval (suite green on the working tree).

8. **Step 8:** Move the drain protocol verbatim into the new `src/claude_retry_proxy/swap_drain.py`. Run this step only after Step 7 is green (a commit is NOT required — the byte-identity gate reads HEAD when the class is committed and falls back to the plan's Step-2 canonical block otherwise; `git diff` reconstruction is forbidden — its LCS folds byte-identical lines into context, making the + side lossy).
   - Create `src/claude_retry_proxy/swap_drain.py`:
     - Header (module docstring):
       ```python
       """The config-swap drain protocol: owned state and operations.

       One `_SwapDrain` instance, the module singleton `_drain`: the lock that
       guards config swaps (and config-document sections that pair with them),
       the in-flight counter, the swapping flag, the completion event, the
       epoch, the shared upstream-activity clock, the press timestamp, and the
       eviction counter — plus the two retry-loop collaborators that serve the
       drain (`_interruptible_sleep`, `_swap_abort_tuple`). Cross-module access
       is attribute-form through the re-exported singleton; the state fields
       are never re-exported as module names (a rebound name re-exported as an
       alias would go stale; the singleton reference cannot).
       """
       ```
     - Import block (whitelist — exact, nothing else):
       ```python
       import threading
       import time

       from .error_body import _error_body
       from .settings import SETTINGS
       from .sinks import log_trace
       ```
     - Body: move **byte-verbatim** from forwarder.py (post-Step-2 text): the `# Config-swap drain protocol` banner block, `_SWAP_QUIET_GRACE`, `class _SwapDrain` (complete), `_drain = _SwapDrain()`, `def _interruptible_sleep`, `def _swap_abort_tuple`. No renames, no reordering, no comment edits.
   - In `forwarder.py`: delete the moved region (the same landmarks as Step 2's insertion, from the banner opener through `_swap_abort_tuple`'s final line) and add after the `from .error_body import _error_body` line:
     ```python
     from .swap_drain import (_drain, _interruptible_sleep, _swap_abort_tuple)
     ```
     (`threading`, `time`, `random`, `json`, `SETTINGS`, `log_trace` imports all stay — other code in forwarder uses each of them.)
   - Update forwarder's module docstring, current sentence: `Owns everything between "the client body has arrived" and "the upstream response is returned": the transport and policy helpers, the retry loop, the compatibility and reasoning retries, and the config-swap drain protocol's state. Re-exported here: the nudge store (chat_nudge.py), the model projection (model_rewrite.py), the tier pair (tier_resolution.py).` — replace with: `Owns everything between "the client body has arrived" and "the upstream response is returned": the transport and policy helpers, the retry loop, and the compatibility and reasoning retries. The config-swap drain protocol lives in swap_drain.py (singleton `_drain`). Re-exported here: the drain singleton and its two retry-loop collaborators (swap_drain.py), the error-envelope builder (error_body.py), the nudge store (chat_nudge.py), the model projection (model_rewrite.py), the tier pair (tier_resolution.py).`
   - `git add src/claude_retry_proxy/swap_drain.py` immediately.
   - `swap_drain.py` must NOT import forwarder (parent-import prohibition).
   - **Sub-step 8c (declared post-move comment correction, after the gate):** the grace comment moved verbatim carries a claim the mega-audit flagged (Issue Log row `grace-comment-invariant`): "an evictable straggler is always evicted before the drain exits" does not hold for anthropic-mode silent streams under defaults (quiet window 32 s vs read boundary ≤ `PROXY_READ_TIMEOUT` 120 s) — it holds only for wakes bounded under the window (chat-drain budgets). Replace the three grace-comment lines in `swap_drain.py` with:
     ```python
     # The drain's total-quiet window: quiet for budget + _SWAP_QUIET_GRACE means
     # every survivor has been silent >= budget on the shared clock — silent by
     # construction at quiet exit. A straggler silent at the press has no armed
     # wake before its next read boundary (<= PROXY_READ_TIMEOUT): it wakes and
     # dies retryably AFTER the drain exit, at the post-bump epoch checkpoint.
     ```
   → coder verify (auto): `swap_drain.py` exists with the exact 5-line import whitelist; `forwarder.py` has no `class _SwapDrain`; the re-export line binds `_drain`, `_interruptible_sleep`, `_swap_abort_tuple`; the corrected grace comment is present and the clause "always evicted before the drain exits" is absent from `swap_drain.py`
   → coder verify (scripted): `python3 ./tmp/verification/2026-11-25-extract-swap-drain-move.py` — exit 0 (includes HEAD-or-plan-canonical byte-identity, the §7.3 undefined-name scope gate, and the parent-import prohibition check; run BEFORE sub-step 8c so the byte-identity measures the verbatim move)

## Guidance for Tester

**Tests to create:**
- **Permanent** (all in `tests/test_admin.py` unless noted — it owns the config-swap drain coverage; no aggregator change is needed since new tests join its existing `ALL_TESTS`):
  - Rewrite surface (mechanical, coverage-preserving): all 63 `forwarder._config_epoch` (×25), `forwarder._config_swapping` (×13), `forwarder._inflight_count` (×11), `forwarder._swap_evictions` (×10), `forwarder._swap_started_at` (×4) references become `forwarder._drain._config_epoch` etc. (field names unchanged).
  - **`getattr`-by-string save-blocks (breaks differently — AttributeError at setup, not a stale read):** six tests snapshot/restore state via `saved_fwd = {name: getattr(forwarder, name) for name in (...)}` at lines ~2870, 3206, 3332, 3442, 3578, 3677. Rewrite the dict source to `getattr(forwarder._drain, name)` (the restore side already lands in the 63-reference rewrite). The names inside the tuples are unchanged.
  - Monkeypatch migration (semantic — verify each, don't blind-replace): **10 functional** `admin_api._drain_for_swap` monkeypatch sites (lines ~2873, 2897, 2949, 3422, 3460, 3516, 3674, 3721, 3764, 3791) plus **5 prose/message occurrences** (`_drain_for_swap` in comments/docstrings/assertion strings at 2836, 3392, 3398, 3484, 3657 — 3484 is an assertion-message string). Post-shape the seam is the singleton's method: patch `forwarder._drain.drain` (instance-attribute shadowing on the singleton — the object admin_api calls is the same object tests patch). **Restore by `del forwarder._drain.drain` in the finally** — never assign a bound method back (that leaves a permanent instance-attribute shadow). For each migrated test, confirm the patch still intercepts the intended call and the test's assertion still measures the same behavior (the reload-staleness tests' whole point is intercepting the drain between gate and install).
  - **Singleton hygiene (wedge hazard):** `_drain` is process-global and the suite runs in one interpreter. Any test that leaves `_config_swapping=True` wedges every later `admit()` forever (`_swap_done.wait()` has no timeout). Every new test wraps each press in try/finally ending in `complete()` (or explicit restore of `swapping=False` + `_swap_done.set()`), joins every helper thread, and drives `inflight` to zero; prefer building a **fresh local `_SwapDrain()`** (the `_CompatState` default-param injection precedent) for the pure-state tests and touching the production singleton only where the seam under test is the re-export itself.
  - Prose accuracy: `tests/test_admin.py:5341` (`_swap_done.wait()` in the `test_request_blocked_at_admission_not_evicted` docstring) and `tests/test_admin.py:3392` (`_drain_for_swap()` prose) reword to the singleton phrasing; `tests/test_chat_sse.py` has no functional drain references — its two stale comments are `_config_swapping` at lines 4438 and 4614, reword to the singleton phrasing.
  - New tests (add coverage; each documents the invariant it pins; singleton hygiene applies to all):
    - `test_drain_admit_snapshot_under_lock`: `admit` runs its snapshot_fn under the lock, and a raising snapshot_fn cannot leave a phantom admission. Respec (mega-audit): run `admit()` in a helper thread with a snapshot_fn that signals then blocks briefly; from the main thread, while the callback is inside, assert `forwarder._drain.lock.acquire(blocking=False)` is **False** (the admitting acquisition holds the lock) and that `_drain._inflight_count` is still 0 while the callback runs — the increment happens only after the snapshot returns (snapshot-before-increment; the reviewer round caught this spec text itself carrying the stale incremented-at-callback claim, fixed in Step 9's catalog bullet and here) — then join the helper (bounded timeout), assert admission completed, and release. Separately, a snapshot_fn that raises must propagate with `_inflight_count` unchanged (the snapshot-before-increment ordering). finally: `complete()` / state restore.
    - `test_drain_complete_invariant`: after `complete()`, `status_snapshot()` never reports `swapping=True` with `started_at=None` (sequential, deterministic).
    - `test_drain_bump_epoch_reentrant`: `bump_epoch()` succeeds when called inside an open `with _drain.lock:` block (RLock re-entrancy is load-bearing for both admin Phase 3 sections). Fresh local instance.
    - `test_drain_single_flight_refusal`: a second `drain()` while one runs returns `None` and leaves the first press's state untouched (counters, started_at). Fresh local instance; finally completes the first press.
    - `test_drain_predicate_semantics`: `epoch_changed(None)` is False; `chain_abort` is True when the swapping flag is set even with a matching epoch (press-abandon rule). Fresh local instance.
  - Keep every rewritten test's name unchanged (the per-test catalog and any `-t` invocations reference them). Step 7's completion claim covers **63 attribute refs + 6 getattr-keyed save-blocks + 10 monkeypatch targets + 8 prose/message sites** (5 `_drain_for_swap` prose in test_admin at 2836/3392/3398/3484/3657, the `_swap_done.wait()` docstring at test_admin 5341, and the two `_config_swapping` comments at test_chat_sse 4438/4614); verify the six save-block tests individually (`python tests/test_claude_proxy.py -t <name>` for each) alongside the full-suite run.

**Tests to investigate for retirement:**
- Planner candidates: none — no behavior is removed by this plan ("No test obsolescence identified").
- Tester may identify additional candidates during the rewrite (e.g., a test that exists only to patch `admin_api._drain_for_swap` in a way the method surface makes unreachable). Apply the retirement procedure: verify what each candidate exercises; if obsolete, delete and note in the session report; if still valid, document why.

**Retirement procedure:** For each candidate, verify the test exercises code being removed/changed. If obsolete: delete and note in session report. If still valid: document why in session report.

## Summary

**Problem.** `src/claude_retry_proxy/forwarder.py` is 1,535 lines — the only source file over the 1,000-line threshold (2026-11-25 survey). The 2026-11-24 size-reduction campaign (model_rewrite, tier_resolution) left the config-swap drain protocol as the largest extractable cluster, and the owned-state-object conversion for the drain state is the named open follow-up of plans `2026-11-16-extract-forwarder` / `2026-11-23-extract-admin-api`. This plan executes both: the drain protocol leaves forwarder as `swap_drain.py` with its bare globals converted into an owned object (guide §5: runtime-mutated state belongs on an owned object with its lock, never bare module globals). Net: forwarder sheds the `_error_body` leaf and the whole drain protocol (the survey's next re-measure, recorded in `## Final Results`, carries the figure); the doctrine violation closes, and the campaign's queued follow-up lands its drain half.

**Approach — shape, then move (reversed from the guide's default; see Document Overrides).** Six of the eight drain globals are rebound at runtime (ints/bools). Re-exporting rebound names through forwarder after a verbatim move would alias stale values — `forwarder._config_epoch` would freeze at the import-time int and every epoch read after the first swap would silently misjudge eviction. Shaping first puts the state on a fixed singleton whose re-export is alias-safe, so the move phase becomes pure byte-verbatim relocation with zero cross-module edits and exactly one consumer rewrite.

**Key design decisions.**
- Method surface (user-selected): compound operations become `_SwapDrain` methods with the lock inside — `admit(snapshot_fn)` (blocks behind a swap; snapshots config/vendors/epoch in the admitting acquisition, preserving the reviewer-drain-swap-race fix; the snapshot runs before the counter increment so a raising callback cannot leak a phantom admission), `release()`, `touch()` (deliberately lock-free, as today), `epoch_changed()` / `chain_abort()` (lock-free predicates, as today), `note_eviction()` (counter under lock, `log_trace` outside — exact current split), `drain()` (the press-and-poll protocol, single-flight under one acquisition), `status_snapshot()` (four fields, one acquisition, per-field None-guards verbatim — the endpoint's fifth field, `budget_s`, comes from SETTINGS at the call site), `bump_epoch()` (RLock-reentrant — both callers hold the lock across larger install sections), `complete()` (flag + timestamp + event in one acquisition).
- Field names keep today's global names exactly — the moved bodies stay maximally similar and the ~86 test-site rewrite is a mechanical prefix swap.
- Mixed config+drain sections (admin_api ×5) keep `with forwarder._drain.lock:` — that RLock is also the config-document lock (forwarder.py line 59's original purpose); hiding it behind a callback would obscure, not remove, the coupling. Guarded field reads inside those sections (`_drain._config_epoch` ×4) are plain reads, not compound operations.
- `_error_body` extracts first (Step 1): a utility leaf with one nameable task — "client-facing error bodies in the Anthropic envelope" (stdlib-only); direct consumers are forwarder (and, from Step 8, swap_drain), with server, chat_sse, and admin_api reaching it through forwarder's re-export — and it is a prerequisite for Step 8 because `swap_drain._swap_abort_tuple` calls it and parent→sibling is the only legal import direction.
- `_interruptible_sleep` and `_swap_abort_tuple` keep their names and signatures (9 impl/core call sites unchanged); they are the drain cluster's stateless collaborators (deletion test: no home without it).

**Alternatives rejected.** Move-then-shape: alias hazard above plus two full consumer rewrites (~58 production site edits + ~86 test-site edits each). Raw-field shape (owned object, sites repointed field-by-field): cheaper, but the user explicitly chose the method surface. Fully hidden lock (`exclusive(fn)` callbacks for the five mixed sections): wraps config-document surgery in drain-object indirection. Keeping `_error_body` in forwarder with swap_drain importing the parent: violates the import-direction rule.

**Out of scope.** `runtime_state`'s five globals (the follow-up's other half — next plan, own cluster/own file); the remaining forwarder families (trace-field shaping, extra-headers, upstream plumbing, compat orchestration — tracked by the /refactor-split survey); the ten over-threshold test files (separate campaign); any behavioral change (none is intended; the suite is the guard).

## Repo Mode

Public

*Detected at plan creation. Determines: plan archival path, commit-message content, staged files.*

## Document Overrides

| Document | Rule Overridden | Reason |
|----------|----------------|--------|
| ~/.claude/guides/refactor-split-guidance.md §6 (move-then-shape preference) | Staging reversed to shape-then-move | Six drain globals are rebound at runtime; verbatim-moving them with re-exports aliases stale ints/bools (silent wrong evictions after the first swap). Shaping first re-homes state on a fixed singleton, making the move alias-safe, byte-verbatim, and single-rewrite (~28 production + ~76 test sites once, not twice). |

## Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Red interval spans Steps 2–6 (+ tester Step 7) — imports fail mid-sequence | A partial commit would break the tree for everyone | Explicit no-commit-inside-red-window rule in Guidance for Coder; Steps 2–7 committed as one unit after tester green; interim commits are staging |
| Monkeypatch seam migration (`admin_api._drain_for_swap` → `forwarder._drain.drain`) | A blind find/replace could patch a different lookup path and silently un-exercise the staleness seam | Tester instruction verifies each of the 10 functional sites measures the same behavior; restore via `del forwarder._drain.drain`; the reload-staleness tests are the regression guard |
| Red-interval session death (Steps 2–6 + tester 7 uncommitted, tree does not import) | Broken working tree left behind with no commit to return to | Recovery: restore the last green commit (`git checkout -- src/` — new untracked modules removed with `git clean -f src/claude_retry_proxy/error_body.py` semantics only after confirming no other work is in flight) and restart from Step 2; never commit inside the red interval |
| `bump_epoch()` reentrancy | Deadlock or missed bump if the lock were `Lock` not `RLock`, or a caller moved outside the held section | Field stays `threading.RLock()` (as today); reentrancy asserted by `test_drain_bump_epoch_reentrant`; both call sites are inside existing `with` sections, unchanged in shape |
| `admit(snapshot_fn)` runs client code under the lock | A blocking snapshot_fn would stall admissions | Documented in the method contract ("must not block"); the callback is the two attribute reads the old inline code performed in the same position |
| Byte-identity gate depends on Steps 2–7 being committed before Step 8 | Gate reads HEAD; an uncommitted red window would make it unsatisfiable | Step 8's precondition states the commit requirement; the gate's RED calibration expects exactly this |

## Proposed Changes

Each step includes verification checks tagged with confidence (see Prime Directive 4).
`(auto)` = mechanical, coder self-verifies. `(scripted)` = deterministic multi-step, coder runs provided script.
Every step must have at least one verification check executable by its owner (coder steps: coder checks; tester steps: tester verify; planner steps: Evidence).

1. **Step 1:** Extract `_error_body` into `error_body.py`
   → coder verify (auto): signature + return-expression preserved byte-identically; zero `def _error_body` in forwarder.py; consumers untouched
   → coder verify (scripted): `./tmp/verification/2026-11-25-extract-swap-drain-errorbody.py` exit 0

2. **Step 2:** Introduce `_SwapDrain` and rewrite forwarder's drain region
   → coder verify (auto): class surface (11 methods + property) and singleton assignment present; zero state-name `global` statements
   → coder verify (scripted): `-shape.py` gate (RED until Step 6 completes)

3. **Step 3:** Repoint server.py onto the `_drain` surface
   → coder verify (auto): exact per-site counts (admit ×1, release ×1, note_eviction ×2, touch ×4, epoch_changed ×4, chain_abort ×3); import list shrunk by exactly 3 names
   → coder verify (scripted): `-shape.py` gate

4. **Step 4:** Repoint admin_api.py onto the `_drain` surface
   → coder verify (auto): exact per-site counts (status_snapshot ×1, drain ×2 — switch 399 + reload 596, lock ×5, _config_epoch field reads ×4, bump_epoch ×2, complete ×2); import shrunk by `_drain_for_swap`
   → coder verify (scripted): `-shape.py` gate

5. **Step 5:** Repoint chat_sse.py onto the `_drain` surface
   → coder verify (auto): exactly 7 `forwarder._drain.` references (1 note_eviction, 4 epoch_changed, 1 chain_abort, 1 touch); import shrunk by exactly 3 names
   → coder verify (scripted): `-shape.py` gate

6. **Step 6:** Repoint forwarder impl/core call sites onto `_drain`
   → coder verify (auto): 20 sites repointed (5 epoch_changed, 7 note_eviction, 6 touch, 2 chain_abort); `_interruptible_sleep`/`_swap_abort_tuple` call-site counts unchanged
   → coder verify (scripted): `./tmp/verification/2026-11-25-extract-swap-drain-shape.py` exit 0 (still red-tree for tests — expected)

7. **Step 7:** Rewrite the test surface and add behavioral tests
   → tester verify: full suite green via `python tests/test_claude_proxy.py` with all 63 field refs, 13 monkeypatch targets, and prose mentions migrated; the five new invariant tests pass; no test renamed; per-test coverage of every migrated monkeypatch documented in the session report
   → coder verify: none (tester-owned step)

8. **Step 8:** Move the drain protocol verbatim into `swap_drain.py`
   → coder verify (auto): import whitelist exact; re-export line exact; forwarder docstring enumeration updated
   → coder verify (scripted): `./tmp/verification/2026-11-25-extract-swap-drain-move.py` exit 0

9. **Step 9:** Doc-sync sweep and re-measure *(planner)*
   → Evidence: `git grep -n '_drain_for_swap\|_config_swapping\|_config_lock\|_swap_done\|_config_epoch\|_inflight_count\|_touch_upstream_activity\|_note_swap_eviction\|_swap_epoch_changed\|_swap_chain_abort\|_error_body' -- doc CLAUDE.md README.md` output reviewed and every stale identifier updated or confirmed absent; `wc -l` output for forwarder.py/swap_drain.py/error_body.py recorded in `## Final Results`; CLAUDE.md Structure + Architecture + Future Work edits diffed

## Guidance for Planner

Documentation tasks you will execute yourself (not the coder):

- **Files to modify:**
  - `./CLAUDE.md`
  - `./README.md`
  - `./doc/architecture.html`
  - `./doc/operations.html`
  - `./doc/content.html`
  - `./doc/test-catalog.html`
- **`.claude/mega-audit-files.json`:** no audit-location declarations are added or changed by this plan (the file does not exist in this repo).
- **When:** after Step 8 lands (doc edits reference the final module layout), before Phase 6 review.
- **What to sync:**
  - `CLAUDE.md` Structure section: add `error_body.py` and `swap_drain.py` entries; rewrite `forwarder.py`'s line (drop "the config-swap drain protocol (its state lives here; readers read it attribute-form)"; the frozen-surface re-export enumeration gains BOTH the swap_drain note AND error_body.py's `_error_body` — forwarder re-imports the envelope builder at Step 1 and the three consumers keep importing it through forwarder); Architecture bullet "Drain-and-swap (silence-based)" — the owner is now `swap_drain._drain` (methods named, single-flight under `_drain.drain()`); Future Work: the owned-state conversion's **drain half landed** (this plan), open scope = `runtime_state`'s five globals. Sweep for the renamed identifiers (Step 9 Evidence).
  - `doc/architecture.html`: `#config-swap` section names `_config_swapping`, `_swap_done`, the drain mechanics — update to the method surface (`_drain.drain()`, `admit()`, `complete()`); keep every anchor (`#config-swap` referenced at lines ~104, 254, 347, 356) intact.
  - `doc/operations.html` (~line 327) and `README.md` (~line 546): `_drain_for_swap()` prose → `_drain.drain()`.
  - `doc/test-catalog.html`: Category 8 per-test list — add the five new invariant tests, describing the fresh-instance construction as `type(forwarder._drain)()` (tester round 2's construction — `_SwapDrain` is deliberately NOT in Step 8's re-export surface); update descriptions naming the old monkeypatch target; rephrase the two bare-global phrasings at lines ~714 (`_config_epoch` bump) and ~716 (`_swap_done.wait()`) to the singleton-attribute form.
  - `doc/content.html`: verify whether it lists modules (only doc-page links found in recon — edit only if a module index exists).
  - Donor docstring (forwarder.py) was updated in Step 8 by the coder — verify it in the sweep (campaign lesson: re-export enumerations live in the donor .py too).
  - Documentation must not maintain exact counts: line-count figures go in `## Final Results` only, not into docs.

## History

One row per event (spec revision / mega-audit / review / implementation round). Conclusion = one-sentence outcome or what changed. Dismissed = compact dismissed-findings list for the reviewer — verbatim issue slugs linked as `[<slug>](<report-path>)`, no prose-only entries. Link to report files; never restate findings inline.

| Date | Event | Conclusion | Dismissed |
|------|-------|------------|-----------|
| 2026-11-25 | Initial plan | Surveyed file sizes (forwarder.py 1,535 = only code file over; 10 test files over 1,500); user selected direction A (drain extract + shape), method surface, and shape-then-move staging; `_error_body` leaf extraction added as prerequisite step | — |
| 2026-11-25 | Mega-audit | 43 findings (7 High / 17 Medium / 19 Low) in [report](./tmp/reports/2026-11-25-extract-swap-drain-mega-audit-2026-11-25.json); all fixed in-plan — the two missed call sites (forwarder.py:377 sixth touch site; admin_api.py:596 reload drain press), the six `getattr(forwarder, name)` save-blocks, `admit()` snapshot-before-increment exception safety, banner ACCEPTED-RISK paragraph carried verbatim (four declared renames only), admit-test respec (fresh `_SwapDrain` instances, `del`-restore monkeypatch, wedge-hazard contract), line-number/count corrections (652, 658–661, 44–54, 103–106, 3 globals, 15 server refs, 20 impl/core sites), `retire_inventory` populated, errorbody-gate byte-identity upgraded, move-gate slice extended to the banner; **0 High remain — no re-audit** (iteration 1); hunches + areas_not_fully_verified handed verbatim to the Phase 6 reviewer as obligations | — |
| 2026-11-25 | Implementation round (coder) | [Report](./tmp/reports/2026-11-25-extract-swap-drain-coder-2026-11-25.json): exit 0; Steps 1–6 complete, errorbody 11/11 + shape 16/16 on the working tree, Step 8 correctly blocked, no issues filed. `git commit` denied in the coder lane → no interim commits: plan revised (commit-discipline block, Step 8 gate reads HEAD-or-plan-canonical block — diff reconstruction forbidden, LCS proven lossy; 8c grace-comment correction added; residue + coder report recorded in retire_inventory). Cosmetic Span-A seam collapse (4 blanks → 2) independently verified good | — |
| 2026-11-25 | Implementation round (tester) | [Report](./tmp/reports/2026-11-25-extract-swap-drain-tester-2026-11-25.json): SUCCESS — 555/555 exit 0; full Step-7 inventory landed (63 refs, 6 save-blocks, 10 monkeypatch seats with `del`-restore, 8 prose sites, 5 new invariant tests via `type(forwarder._drain)()`); two transient spawn-isolation failures from this plan's own gates fixed with the documented exemption marker + floor (tester-verified: checker PASS, errorbody 11/11 unchanged, move gate still RED pre-Step-8) — gate edits reviewed by planner: isolation preamble only, zero assertion changes, accepted. Red interval closed; Step 9 catalog note added (`type(forwarder._drain)()` construction) | — |
| 2026-11-25 | Implementation round (coder r2) | [Report](./tmp/reports/2026-11-25-extract-swap-drain-coder-2026-11-25-r2.json): exit 0; Step 8 complete — pre-move block byte-identical to plan canonical (13,473 B), gate 7/10 at 8a (expected 8b REDs), 10/10 at 8b, suite 555/555 after 8b, 8c comment-only (compileall + imports clean; planner re-running the suite post-8c as closing evidence). Final-state gate REDs are design, not regression: `-shape.py` superseded by `-move.py` at Step 8; `-move.py` byte-identity ordered before 8c. `grace-comment-invariant` → Resolved (8c). forwarder.py 1619→1334; swap_drain.py 310 new; error_body.py 33 new. r2 report + tester report added to retire_inventory | — |
| 2026-11-25 | Step 9 doc sweep (planner) | Planner suite re-run post-8c: 555/555 exit 0. Synced: CLAUDE.md (swap_drain.py + error_body.py structure entries, forwarder.py entry re-exports, drain bullet to the `_drain` method surface, both Future Work follow-up notes — drain half landed, open scope = runtime_state five globals); README.md + doc/operations.html `_drain_for_swap()` → `_drain.drain()`; doc/architecture.html config-swap section to the singleton surface + the pre-migration "always evicted before drain exit" claim corrected to the real mechanism (grace ⇒ quiet-exit implies survivors silent ≥ budget; post-exit wakes die retryably at the post-bump checkpoint); doc/test-catalog.html — five new invariant tests documented (`type(forwarder._drain)()` construction), monkeypatch-target and bare-global phrasings updated. Evidence: identifier sweep clean (one deliberate provenance mention retained at catalog:717); `check_doc_anchors.py` 272 anchors resolved, no secret shapes; docs tests 11/11. Re-measure: forwarder 1334 / swap_drain 310 / error_body 33; forwarder still over the 1,000 threshold — remaining families stay on the survey backlog | — |
| 2026-11-25 | Review | [Report](./tmp/reports/2026-11-25-extract-swap-drain-review-2026-11-25.json): verdict ready-to-commit — **0 Critical / 1 Warning / 4 Suggestions**; all six mega-audit obligations CONFIRMED with measurement (gate whitelist-only, no stale counts; corrected grace comment present, stale claim nowhere; site arithmetic exact: 20+16+7+15 = 58; admit/release invariant sound; leaves verified; §7.3 gate PASSES on swap_drain; 2 of 10 monkeypatch seams traced end-to-end; gates' final-state REDs confirmed as declared design). The Warning (catalog bullet claimed count incremented at callback time, contradicting the snapshot-before-increment test) **fixed in place** by the planner in the catalog bullet + the plan's own spec text; docs tests re-run 11/11. Suggestions deferred to the Dismissed cell — non-blocking | [errorbody-planref-docstring](./tmp/reports/2026-11-25-extract-swap-drain-review-2026-11-25.json), [admit-docstring-subject](./tmp/reports/2026-11-25-extract-swap-drain-review-2026-11-25.json), [del-guard-attrerror](./tmp/reports/2026-11-25-extract-swap-drain-review-2026-11-25.json), [freshdrain-stale-docstring](./tmp/reports/2026-11-25-extract-swap-drain-review-2026-11-25.json) |

## Commit Log (optional — conditional)

Populated solely by `/update-and-commit` Step 10 — its single writer. The planner never authors entries; `/update-plan` preserves the section untouched; an absent section means zero SHAs.

## Plan Metadata

Fenced ```json block — the machine contract read by `parsePlanContext` (JSON-first, regex fallback). **Update it on every revision.**

```json
{
  "plan_id": "2026-11-25-extract-swap-drain",
  "steps": [
    "Step 1: Extract _error_body into error_body.py",
    "Step 2: Introduce _SwapDrain and rewrite forwarder's drain region",
    "Step 3: Repoint server.py onto the _drain surface",
    "Step 4: Repoint admin_api.py onto the _drain surface",
    "Step 5: Repoint chat_sse.py onto the _drain surface",
    "Step 6: Repoint forwarder impl/core call sites onto _drain",
    "Step 7: Rewrite the test surface and add behavioral tests",
    "Step 8: Move the drain protocol verbatim into swap_drain.py",
    "Step 9: Doc-sync sweep and re-measure"
  ],
  "coder_files": [
    "src/claude_retry_proxy/forwarder.py",
    "src/claude_retry_proxy/error_body.py",
    "src/claude_retry_proxy/swap_drain.py",
    "src/claude_retry_proxy/server.py",
    "src/claude_retry_proxy/admin_api.py",
    "src/claude_retry_proxy/chat_sse.py"
  ],
  "tester_files": [
    "tests/test_admin.py",
    "tests/test_chat_sse.py"
  ],
  "doc_files": [
    "./CLAUDE.md",
    "./README.md",
    "./doc/architecture.html",
    "./doc/operations.html",
    "./doc/content.html",
    "./doc/test-catalog.html"
  ],
  "verification_scripts": [
    "./tmp/verification/2026-11-25-extract-swap-drain-errorbody.py",
    "./tmp/verification/2026-11-25-extract-swap-drain-shape.py",
    "./tmp/verification/2026-11-25-extract-swap-drain-move.py"
  ],
  "retire_inventory": [
    "./tmp/reports/2026-11-25-extract-swap-drain-mega-audit-2026-11-25.json",
    "./tmp/verification/2026-11-25-extract-swap-drain-errorbody.py",
    "./tmp/verification/2026-11-25-extract-swap-drain-shape.py",
    "./tmp/verification/2026-11-25-extract-swap-drain-move.py",
    "./tmp/extract_blocks_scratch.py",
    "./tmp/splice_spanb_scratch.py",
    "./tmp/blocks_out/",
    "./tmp/forwarder_new.py",
    "./tmp/reports/2026-11-25-extract-swap-drain-coder-2026-11-25.json",
    "./tmp/reports/2026-11-25-extract-swap-drain-coder-2026-11-25-r2.json",
    "./tmp/reports/2026-11-25-extract-swap-drain-tester-2026-11-25.json",
    "./tmp/reports/2026-11-25-extract-swap-drain-review-2026-11-25.json"
  ],
  "repo_mode": "Public",
  "document_overrides": [
    "~/.claude/guides/refactor-split-guidance.md §6: move-then-shape preference reversed to shape-then-move (Reason: six drain globals are rebound at runtime; re-exporting them aliases stale values, and shape-first halves the consumer rewrite)"
  ]
}
```

## Audit Accumulation

*Counters reset when mega-audit runs. Used by Phase 5 entry trigger.*

| Counter | Value | Last Updated |
|---------|-------|--------------|
| issues_resolved_since_audit | 1 | 2026-11-25 |
| steps_changed_since_audit | 3 | 2026-11-25 |
| files_changed_since_audit | 0 | 2026-11-25 |

## Documentation

- [doc/content.html](doc/content.html) — the human-facing reference; indexes the whole tree.
- The config-swap mechanism is documented in [doc/architecture.html](doc/architecture.html)#config-swap; the admin surface in [doc/operations.html](doc/operations.html)#admin.
- Test-suite layout and isolation: [doc/test-catalog.html](doc/test-catalog.html).

## Final Results

**Status: COMPLETED** (2026-11-25)

The config-swap drain protocol left `forwarder.py` as the owned `_SwapDrain` singleton in the new `src/claude_retry_proxy/swap_drain.py`, and `_error_body` left for the new `src/claude_retry_proxy/error_body.py` leaf — the drain half of the campaign's named owned-state conversion, executed shape-then-move (shaped in place behind the frozen re-exports, then moved byte-verbatim behind the alias-safe `_drain` reference). All nine steps completed: coder rounds 1–2 (Steps 1–6, 8a/8b/8c), tester round (Step 7), planner doc sweep (Step 9).

**Verification:**
- Full suite **555 passed / 0 failed** (tester round, twice after the two gate-isolation fixes; re-run independently by the planner post-8c, exit 0). Docs section 11/11; `check_doc_anchors.py` 272 anchors resolved, no secret shapes.
- Step gates: `errorbody.py` 11/11; `shape.py` 16/16 at its step (Steps 2–6); `move.py` 10/10 at 8b with pre-move byte-identity proven against the plan's canonical block (13,473 bytes).
- Reviewer (Phase 6): **ready to commit — 0 Critical / 1 Warning / 4 Suggestions** ([report](./tmp/reports/2026-11-25-extract-swap-drain-review-2026-11-25.json)). The one Warning (a stale count-ordering claim in the new catalog bullet, contradicting the snapshot-before-increment test) was fixed in place by the planner; docs tests re-run green. All six mega-audit obligations confirmed with measurement; the §7.3 scope gate passes on swap_drain.py; two of the ten migrated monkeypatch seams traced end-to-end.

**Deliverables:** forwarder.py 1,619 → 1,334 lines (drain protocol + error leaf out; still over the 1,000 threshold — the remaining families — trace-field shaping, extra-headers, upstream plumbing, compat orchestration — stay on the /refactor-split survey backlog for later plans); swap_drain.py 310 lines; error_body.py 33 lines; test_admin.py 5,482 → 5,796 (63 field refs + 6 getattr save-blocks + 10 monkeypatch seats + 8 prose sites migrated; five new permanent singleton-invariant tests registered in ALL_TESTS).

**Known caveats (all non-blocking):**
- Reviewer Suggestions, deferred: `error_body.py:5` docstring carries a plan-step reference ("from Step 8, by swap_drain") — shipped-docstring style; `swap_drain.py:105` admit() docstring has two adjacent return sentences with an ambiguous subject; `tests/test_admin.py:2948/3515/3789` unconditional `del forwarder._drain.drain` in finally could raise AttributeError and mask a setup exception (guard with `if "drain" in vars(forwarder._drain)`); `tests/test_admin.py:5421` `_fresh_drain()` docstring still says "forwarder today, swap_drain.py after it" — stale post-Step-8. Say the word and a tiny follow-up round closes all four before or after the commit.
- Two gates are intentionally RED against the final tree (design, not regression): `-shape.py` (superseded by `-move.py` at Step 8) and `-move.py`'s byte-identity (ordered before the 8c comment correction; at 8b it was 10/10, and the post-8c diff against the plan canonical block is exactly the 3→5-line grace-comment change).
- `src/claude_retry_proxy.egg-info/PKG-INFO` carries the old README prose until the next install regenerates it (generated artifact, untracked).

**Cross-References to Prior Plans**

| Prior Plan | Deferred Issue | Resolution |
|------------|---------------|------------|
| 2026-11-24-extract-tier-resolution | "swap-drain owned-state conversion (plan 3, declared follow-up)" (Final Results, Out of scope) | This plan is that plan 3: the drain state is the owned `_SwapDrain` singleton in swap_drain.py |
| 2026-11-24-extract-nudge-store | "the open scope is now forwarder's swap-drain state + `runtime_state`'s five globals" (Final Results) | Partially resolved: the swap-drain half landed here; `runtime_state`'s five globals remain the open remainder of the conversion |

**Transient artifacts** are recorded in `## Plan Metadata` → `retire_inventory` (mega-audit report, three verification scripts, three session reports + this review report, and the coder's declared scratch under `./tmp/`); the terminal sweep sweeps exactly that record via the user-executed hand-off.
