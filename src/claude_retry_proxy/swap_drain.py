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

import threading
import time

from .error_body import _error_body
from .settings import SETTINGS
from .sinks import log_trace


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

# The drain's total-quiet window: quiet for budget + _SWAP_QUIET_GRACE means
# every survivor has been silent >= budget on the shared clock — silent by
# construction at quiet exit. A straggler silent at the press has no armed
# wake before its next read boundary (<= PROXY_READ_TIMEOUT): it wakes and
# dies retryably AFTER the drain exit, at the post-bump epoch checkpoint.
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
