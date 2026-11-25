"""The `swap_drain._drain` singleton's invariants, on fresh local instances.

Part of the claude-retry-proxy suite; runnable standalone.
"""
from _harness import (
    fail,
    pass_,
    run_cli,
)
import threading


# ---------------------------------------------------------------------------
# Config-swap drain: singleton invariants (plan 2026-11-25-extract-swap-drain)
#
# The drain state is now owned by one process-global `_SwapDrain` singleton.
# These tests pin the class's own invariants on FRESH LOCAL instances so they
# never leave a pressed singleton behind — a process-global `_drain` left with
# `swapping=True` would wedge every later `admit()` forever (the completion
# wait has no timeout).
# ---------------------------------------------------------------------------

def _fresh_drain():
    """A fresh local drain instance for the pure-state invariant tests.

    Resolved as the singleton's TYPE rather than importing `_SwapDrain` by
    name: the class's home module changes with the planned extraction
    (forwarder today, swap_drain.py after it), while the re-exported `_drain`
    singleton is the one handle guaranteed stable across that move.
    """
    import claude_retry_proxy.forwarder as forwarder
    return type(forwarder._drain)()


def test_drain_admit_snapshot_under_lock():
    """admit() snapshots inside the admitting lock acquisition, BEFORE it
    increments the in-flight counter.

    Two invariants, both load-bearing for the reviewer-drain-swap-race fix and
    the phantom-admission guard:

      - While the snapshot callback runs, the drain lock is held (a
        non-blocking acquire from another thread fails) — so config, vendors,
        and epoch are read in one atomic admission, and no swap can interleave
        with a snapshot read.
      - The snapshot runs BEFORE the counter increment, so a callback that
        raises propagates with the in-flight counter untouched and cannot leak
        a phantom admission the caller's `release()` would then drive negative.
    """
    print("\n--- Test: Drain admit() Snapshots Under the Lock ---")
    drain = _fresh_drain()

    inside = threading.Event()
    proceed = threading.Event()
    observed = {}

    def snapshot():
        # Runs inside admit()'s admitting acquisition.
        observed["count_at_snapshot"] = drain._inflight_count
        inside.set()
        proceed.wait(5)
        return ("cfg", "vendors")

    admitted = {}

    def worker():
        try:
            admitted["value"] = drain.admit(snapshot)
        except Exception as e:  # surfaced through the assertions below
            admitted["error"] = e

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    try:
        if not inside.wait(5):
            fail("the snapshot callback never ran — admit() did not invoke it "
                 "inside the admitting acquisition")
            return
        if observed.get("count_at_snapshot") == 0:
            pass_("the snapshot callback runs BEFORE the in-flight counter is "
                  "incremented (a raising callback cannot leak a phantom "
                  "admission)")
        else:
            fail("the counter was already {} when the snapshot callback ran — "
                 "the increment precedes the snapshot, so a raising callback "
                 "would leak a phantom admission".format(
                     observed.get("count_at_snapshot")))

        got_lock = drain.lock.acquire(blocking=False)
        if got_lock:
            drain.lock.release()
            fail("the admitting acquisition does NOT hold the drain lock while "
                 "the snapshot callback runs — a swap could interleave with "
                 "the config/vendors snapshot")
        else:
            pass_("the drain lock is held while the snapshot callback runs")

        proceed.set()
        t.join(5)
        if t.is_alive():
            fail("admit() did not return within 5 s after its snapshot callback "
                 "released it")
            return
        if "error" in admitted:
            fail("admit() raised on a non-raising snapshot_fn: {!r}".format(
                admitted["error"]))
            return
        expected = ("cfg", "vendors", drain._config_epoch)
        if admitted.get("value") == expected:
            pass_("admit() returned (config, vendors, epoch) after the callback")
        else:
            fail("admit() returned {!r}, expected the three-tuple {!r}".format(
                admitted.get("value"), expected))
    finally:
        proceed.set()
        t.join(5)
        # Mirror the caller protocol so the local instance is left at rest.
        if drain._inflight_count:
            drain.release()

    # Second half: a raising snapshot_fn propagates and leaves the count alone.
    drain2 = _fresh_drain()
    before = drain2._inflight_count

    def boom():
        raise ValueError("boom")

    try:
        drain2.admit(boom)
    except ValueError:
        if drain2._inflight_count == before:
            pass_("a raising snapshot_fn propagated and left the in-flight "
                  "counter unchanged ({} -> {})".format(
                      before, drain2._inflight_count))
        else:
            fail("a raising snapshot_fn leaked a phantom admission: counter "
                 "{} -> {}".format(before, drain2._inflight_count))
    else:
        fail("admit() swallowed the snapshot_fn's exception instead of "
             "propagating it")


def test_drain_complete_invariant():
    """complete() clears the swapping flag and the press timestamp together.

    The status endpoint guards `waited_s` on its own source precisely so a
    `time.time() - None` can never 500 it; that guard is pointless if
    `complete()` can still expose swapping=True beside a None started_at. A
    real press (inflight 0, so it exits at count-zero immediately) is completed
    and the post-complete snapshot must read swapping=False with waited_s=None.
    """
    print("\n--- Test: Drain complete() Invariant ---")
    drain = _fresh_drain()
    press = drain.drain()
    try:
        if press is None:
            fail("the first press on a fresh instance was refused")
            return
        swapping, waited_s, _inflight, _silence_s = drain.status_snapshot()
        if swapping is True and waited_s is not None:
            pass_("a live press reads swapping=True with a numeric waited_s")
        else:
            fail("a live press must read swapping=True with a numeric "
                 "waited_s; got swapping={!r} waited_s={!r}".format(
                     swapping, waited_s))
    finally:
        drain.complete()

    swapping, waited_s, _inflight, _silence_s = drain.status_snapshot()
    if swapping is False and waited_s is None:
        pass_("after complete(): swapping=False and waited_s=None")
    else:
        fail("after complete() the status must read swapping=False with "
             "waited_s=None; got swapping={!r} waited_s={!r}".format(
                 swapping, waited_s))
    if drain._config_swapping is False and drain._swap_started_at is None:
        pass_("the raw fields agree: swapping False, started_at None")
    else:
        fail("complete() left a half-cleared press: swapping={!r} "
             "started_at={!r}".format(drain._config_swapping,
                                      drain._swap_started_at))


def test_drain_bump_epoch_reentrant():
    """bump_epoch() succeeds inside an already-held drain lock (RLock).

    Both admin Phase-3 install sections hold `_drain.lock` across a larger
    compare-and-install span and bump the epoch inside it, so the lock MUST be
    reentrant (a plain Lock would deadlock there). Reentrancy is measured with a
    same-thread non-blocking re-acquire — which returns True only for an RLock
    and cannot itself hang — and then the bump is taken inside an open `with`.
    """
    print("\n--- Test: Drain bump_epoch() Reentrancy ---")
    drain = _fresh_drain()

    with drain.lock:
        reentrant = drain.lock.acquire(blocking=False)
        if reentrant:
            drain.lock.release()
    if not reentrant:
        fail("the drain lock is not reentrant: a same-thread re-acquire failed "
             "— bump_epoch() inside an open lock section would deadlock")
        return
    pass_("the drain lock is reentrant (same-thread re-acquire succeeded)")

    before = drain._config_epoch
    try:
        with drain.lock:
            drain.bump_epoch()
    except RuntimeError as e:
        fail("bump_epoch() raised inside a held lock ({}: {})".format(
            type(e).__name__, e))
        return
    if drain._config_epoch == before + 1:
        pass_("bump_epoch() took exactly one bump from inside an open lock "
              "section")
    else:
        fail("bump_epoch() inside a held lock moved the epoch {} -> {}, "
             "expected exactly +1".format(before, drain._config_epoch))


def test_drain_single_flight_refusal():
    """A second drain() while one is in progress returns None.

    That None is the single-flight 409 config_swap_in_progress refusal's whole
    mechanism: the guard and the press share ONE lock acquisition, so a second
    press cannot pass and must leave the first press's counters and timestamp
    untouched. A fresh instance's first press exits at count-zero immediately
    (inflight 0) and stays owned until complete().
    """
    print("\n--- Test: Drain Single-Flight Refusal ---")
    drain = _fresh_drain()
    try:
        first = drain.drain()
        if first is None:
            fail("the first press was refused — the fresh instance was "
                 "already owned")
            return
        if first[0] is True and first[1] == 0:
            pass_("the first press returned (drained=True, inflight_at_press=0)")
        else:
            fail("the first press returned {!r}, expected drained=True with "
                 "inflight_at_press=0".format(first))
        started_at = drain._swap_started_at
        evictions_at_press = drain._swap_evictions

        second = drain.drain()
        if second is None:
            pass_("a second press returned None (the 409 single-flight refusal)")
        else:
            fail("a second press entered a drain while one was in progress: "
                 "{!r}".format(second))

        if (drain._swap_started_at == started_at
                and drain._swap_evictions == evictions_at_press
                and drain._config_swapping is True):
            pass_("the refused press left the first press's state untouched")
        else:
            fail("the refused press mutated the live press: started_at {!r} -> "
                 "{!r}, evictions {} -> {}, swapping={!r}".format(
                     started_at, drain._swap_started_at, evictions_at_press,
                     drain._swap_evictions, drain._config_swapping))
    finally:
        drain.complete()


def test_drain_predicate_semantics():
    """epoch_changed() and chain_abort() predicate semantics.

    Three rules the retry loop relies on:
      - epoch_changed(None) is False — a request admitted with no epoch is
        never an old-snapshot straggler;
      - epoch_changed() is True only once the epoch has moved off the entry
        value;
      - chain_abort() is True at the PRESS even when the epoch still matches —
        retry chains abandon at the press, not only at the completed swap.
    """
    print("\n--- Test: Drain Predicate Semantics ---")
    drain = _fresh_drain()
    baseline = drain._config_epoch

    if drain.epoch_changed(None) is False:
        pass_("epoch_changed(None) is False")
    else:
        fail("epoch_changed(None) must be False — a None entry epoch is not a "
             "straggler")
    if drain.epoch_changed(baseline) is False:
        pass_("epoch_changed(current epoch) is False")
    else:
        fail("epoch_changed() returned True on a matching epoch")
    if drain.epoch_changed(baseline + 1) is True:
        pass_("epoch_changed(entry epoch) is True once the epoch has moved")
    else:
        fail("epoch_changed() did not detect a moved epoch")
    if drain.chain_abort(baseline) is False:
        pass_("chain_abort() is False when no swap runs and the epoch matches")
    else:
        fail("chain_abort() returned True with no press and a matching epoch")

    drain._config_swapping = True
    try:
        if drain.chain_abort(baseline) is True:
            pass_("chain_abort() is True at the press even with a matching "
                  "epoch")
        else:
            fail("chain_abort() did not abandon at the press — retry chains "
                 "would keep sleeping through a swap")
    finally:
        drain._config_swapping = False

    drain.bump_epoch()
    if drain.chain_abort(baseline) is True:
        pass_("chain_abort() is True after a completed swap moved the epoch")
    else:
        fail("chain_abort() did not abandon after a completed swap")
    if drain.epoch_changed(None) is False:
        pass_("epoch_changed(None) stays False after a bump")
    else:
        fail("epoch_changed(None) became True after a bump")


ALL_TESTS = [
    ("drain-admit-snapshot-under-lock", test_drain_admit_snapshot_under_lock),
    ("drain-complete-invariant", test_drain_complete_invariant),
    ("drain-bump-epoch-reentrant", test_drain_bump_epoch_reentrant),
    ("drain-single-flight-refusal", test_drain_single_flight_refusal),
    ("drain-predicate-semantics", test_drain_predicate_semantics),
]


if __name__ == "__main__":
    run_cli(ALL_TESTS, "claude-retry-proxy tests: test_swap_drain")
