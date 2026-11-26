"""context_management switch-policy tests: the strip-threshold ladder,
rejection doubling, probation, delisting, and probe-counter semantics."""

import json
import shutil

from _harness import (
    fail,
    pass_,
    run_cli,
)

from _compat_support import (
    _bootstrap_learned_state,
    _cm_count,
    _cm_request,
    _entries,
    _entry_values,
    _make_state_dir,
    _mutate_entry,
    _ok_response,
    _read_state_file,
    _reject_unstripped_responder,
    _send,
    _start_compat_proxy,
    _walk_strips,
)


def test_compat_initial_threshold_probe():
    """Exactly 32 strips precede the first unstripped probe; the request
    whose strip count reaches the threshold IS the probe (unstripped), and
    its rejected result is retried stripped for its own client."""
    print("\n--- Test: Compat Initial Threshold Probe ---")
    state_dir, state_path = _bootstrap_learned_state()
    try:
        responders = {"p": _reject_unstripped_responder()}
        temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
            _start_compat_proxy(responders, state_path)
        if proc is None:
            fail("restart proxy failed to start")
            return
        try:
            # Fresh learned entry: counter 0, threshold 32. Requests 1-31
            # stripped (1 upstream call each).
            for i in range(31):
                before = len(mock_servers["p"]["requests"])
                status, _ = _send(proxy_port, _cm_request())
                reqs = mock_servers["p"]["requests"][before:]
                if status != 200 or len(reqs) != 1 or _cm_count(reqs) != 0:
                    fail("stripped request %d unexpected (%s, %d calls, %d "
                         "with cm)" % (i + 1, status, len(reqs),
                                       _cm_count(reqs)))
                    return
            pass_("31 requests stripped before any probe")
            # Request 32 reaches the threshold: it IS the unstripped probe
            # (400) followed by its own stripped retry (2xx).
            before = len(mock_servers["p"]["requests"])
            status, _ = _send(proxy_port, _cm_request())
            reqs = mock_servers["p"]["requests"][before:]
            if len(reqs) == 2 and _cm_count(reqs) == 1 and status == 200:
                pass_("request 32 was the unstripped probe (400) followed by "
                      "stripped retry (2xx)")
            else:
                fail("probe pattern wrong: %d calls, %d with cm, status %s"
                     % (len(reqs), _cm_count(reqs), status))
                return
            # Request 33: stripped again (counter reset at probe start).
            before = len(mock_servers["p"]["requests"])
            status, _ = _send(proxy_port, _cm_request())
            reqs = mock_servers["p"]["requests"][before:]
            if len(reqs) == 1 and _cm_count(reqs) == 0 and status == 200:
                pass_("request 33 stripped again after probe")
            else:
                fail("post-probe request not stripped: %d calls" % len(reqs))
        finally:
            cleanup()
    finally:
        shutil.rmtree(state_dir, ignore_errors=True)


def test_compat_rejection_doubles_threshold():
    """A rejected probe doubles the threshold (capped at max) and persists
    the doubled value."""
    print("\n--- Test: Compat Rejection Doubles Threshold ---")
    # Sub-case 1: 32 -> 64. Walk 31 stripped requests, then the 32nd reaches
    # the threshold and IS the probe.
    state_dir, state_path = _bootstrap_learned_state()
    try:
        responders = {"p": _reject_unstripped_responder()}
        temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
            _start_compat_proxy(responders, state_path)
        if proc is None:
            fail("restart proxy failed to start")
            return
        try:
            if not _walk_strips(proxy_port, mock_servers["p"], 31):
                return
            status, _ = _send(proxy_port, _cm_request())  # probe -> retry
            if status != 200:
                fail("probe request failed (%s)" % status)
                return
            state = _read_state_file(state_path)
            entry = next((e for e in _entry_values(_entries(state))
                          if isinstance(e, dict)
                          and e.get("feature") == "context_management"), None)
            if entry is None:
                fail("entry missing after probe rejection")
                return
            if entry.get("threshold") == 64:
                pass_("threshold doubled 32 -> 64 on rejection")
            else:
                fail("threshold after rejection = %r (expected 64)"
                     % entry.get("threshold"))
                return
        finally:
            cleanup()

        # Sub-case 2: cap at max. Thresholds persist across restarts (only
        # counters reset), so seed threshold 4096 directly and reach the
        # probe through a probation cycle (quantum 8): 7 strips, then the
        # 8th is the probe; its rejection doubles into the cap.
        state_dir2, state_path2 = _bootstrap_learned_state()

        def _at_cap(entry):
            entry["state"] = "probation"
            entry["threshold"] = 4096
            entry["probation_successes"] = 1
            entry["strip_counter"] = 0

        try:
            _mutate_entry(state_path2, _at_cap)
            responders = {"p": _reject_unstripped_responder()}
            temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
                _start_compat_proxy(responders, state_path2)
            if proc is None:
                fail("cap proxy failed to start")
                return
            try:
                if not _walk_strips(proxy_port, mock_servers["p"], 7):
                    return
                status, _ = _send(proxy_port, _cm_request())  # probe -> retry
                if status != 200:
                    fail("capped probe request failed (%s)" % status)
                    return
                state = _read_state_file(state_path2)
                entry = next((e for e in _entry_values(_entries(state))
                              if isinstance(e, dict)
                              and e.get("feature") == "context_management"),
                             None)
                if entry is None:
                    fail("entry missing after capped probe")
                    return
                if entry.get("threshold") == 4096:
                    pass_("threshold capped at 4096 (not doubled past max)")
                else:
                    fail("threshold after capped rejection = %r (expected "
                         "4096)" % entry.get("threshold"))
            finally:
                cleanup()
        finally:
            shutil.rmtree(state_dir2, ignore_errors=True)
    finally:
        shutil.rmtree(state_dir, ignore_errors=True)


def test_compat_probation_cycle():
    """After a successful probe, the entry enters probation: 8 strips, then
    the next probe; one success keeps probation."""
    print("\n--- Test: Compat Probation Cycle ---")
    state_dir, state_path = _make_state_dir()

    def ok_responder(info):
        return _ok_response(info)

    # Learn via a rejecting upstream first, then flip to always-2xx (provider
    # recovered) — but seeding is simpler: bootstrap-learn against a
    # rejecting upstream, then restart with the healthy responder.
    responders = {"p": _reject_unstripped_responder()}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
        _start_compat_proxy(responders, state_path)
    if proc is None:
        shutil.rmtree(state_dir, ignore_errors=True)
        fail("Failed to set up test")
        return
    try:
        status, _ = _send(proxy_port, _cm_request())
        if status != 200:
            fail("bootstrap learn failed (%s)" % status)
            return
    finally:
        cleanup()
    # Now the provider has recovered: always 2xx.
    responders = {"p": ok_responder}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
        _start_compat_proxy(responders, state_path)
    if proc is None:
        shutil.rmtree(state_dir, ignore_errors=True)
        fail("restart proxy failed to start")
        return
    try:
        # Requests 1-31 stripped; request 32 reaches the threshold and IS
        # the probe -> 2xx -> one probation success -> probation state.
        for i in range(31):
            before = len(mock_servers["p"]["requests"])
            _send(proxy_port, _cm_request())
            reqs = mock_servers["p"]["requests"][before:]
            if len(reqs) != 1 or _cm_count(reqs) != 0:
                fail("stripped request %d not stripped (%d calls)"
                     % (i + 1, len(reqs)))
                return
        before = len(mock_servers["p"]["requests"])
        status, _ = _send(proxy_port, _cm_request())
        reqs = mock_servers["p"]["requests"][before:]
        if not (len(reqs) == 1 and _cm_count(reqs) == 1 and status == 200):
            fail("request 32 not an unstripped successful probe (%d calls)"
                 % len(reqs))
            return
        state = _read_state_file(state_path)
        entry = next((e for e in _entry_values(_entries(state))
                      if isinstance(e, dict)
                      and e.get("feature") == "context_management"), None)
        if entry is None:
            fail("entry missing after first successful probe")
            return
        if entry.get("state") != "probation" or \
                entry.get("probation_successes") not in (0, 1):
            fail("after 1 success expected probation state, got %r/%r"
                 % (entry.get("state"), entry.get("probation_successes")))
            return
        pass_("first successful probe transitions to probation")
        # Probation quantum 8: 7 strips, then request 40 reaches 8 and IS
        # the probe -> 2xx -> second success -> delisted.
        for i in range(7):
            before = len(mock_servers["p"]["requests"])
            _send(proxy_port, _cm_request())
            reqs = mock_servers["p"]["requests"][before:]
            if len(reqs) != 1 or _cm_count(reqs) != 0:
                fail("probation strip %d not stripped (%d calls)"
                     % (i + 1, len(reqs)))
                return
        before = len(mock_servers["p"]["requests"])
        status, _ = _send(proxy_port, _cm_request())
        reqs = mock_servers["p"]["requests"][before:]
        if not (len(reqs) == 1 and _cm_count(reqs) == 1):
            fail("probation probe not unstripped (%d calls)" % len(reqs))
            return
        state = _read_state_file(state_path)
        entry = next((e for e in _entry_values(_entries(state))
                      if isinstance(e, dict)
                      and e.get("feature") == "context_management"), None)
        if entry is None:
            pass_("second success delisted the entry")
        else:
            fail("entry still present after 2 successes: %r" % entry)
    finally:
        cleanup()
        shutil.rmtree(state_dir, ignore_errors=True)


def test_compat_delist_after_two_successes():
    """A seeded probation entry earns two successful probes and is delisted;
    afterwards requests are no longer stripped.

    probation_successes is in-memory-only (reset on load, per plan), so both
    successes are earned in one session from the seeded probation state.
    """
    print("\n--- Test: Compat Delist After Two Successes ---")
    state_dir, state_path = _bootstrap_learned_state()
    try:
        # Seed the probation STATE (persists across restarts); the provider
        # has recovered: every upstream call returns 2xx, so probes succeed.
        def _probation(entry):
            entry["state"] = "probation"
            entry["threshold"] = 32
            entry["probation_successes"] = 0
            entry["strip_counter"] = 0

        _mutate_entry(state_path, _probation)
        responders = {"p": _ok_response}
        temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
            _start_compat_proxy(responders, state_path)
        if proc is None:
            fail("restart proxy failed to start")
            return
        try:
            # Probation quantum 8: walk 7 stripped requests, the 8th IS the
            # first successful probe.
            if not _walk_strips(proxy_port, mock_servers["p"], 7):
                return
            before = len(mock_servers["p"]["requests"])
            status, _ = _send(proxy_port, _cm_request())
            reqs = mock_servers["p"]["requests"][before:]
            if not (len(reqs) == 1 and _cm_count(reqs) == 1 and status == 200):
                fail("first probe not unstripped 2xx (%d calls, status %s)"
                     % (len(reqs), status))
                return
            state = _read_state_file(state_path)
            entry = next((e for e in _entry_values(_entries(state))
                          if isinstance(e, dict)
                          and e.get("feature") == "context_management"), None)
            if entry is None or entry.get("probation_successes") != 1:
                fail("after first success expected probation_successes=1, "
                     "got %r" % (entry,))
                return
            pass_("first probe success recorded (probation continues)")
            # Second cycle: 7 strips, 8th IS the second successful probe ->
            # delist.
            if not _walk_strips(proxy_port, mock_servers["p"], 7):
                return
            before = len(mock_servers["p"]["requests"])
            status, _ = _send(proxy_port, _cm_request())
            reqs = mock_servers["p"]["requests"][before:]
            if not (len(reqs) == 1 and _cm_count(reqs) == 1 and status == 200):
                fail("second probe not unstripped 2xx (%d calls, status %s)"
                     % (len(reqs), status))
                return
            state = _read_state_file(state_path)
            entry = next((e for e in _entry_values(_entries(state))
                          if isinstance(e, dict)
                          and e.get("feature") == "context_management"), None)
            if entry is not None:
                fail("entry not delisted after second success: %r" % entry)
                return
            pass_("second success delisted the entry")
            # Post-delist: request goes out unstripped (discovery path, 2xx,
            # nothing learned from a 2xx).
            before = len(mock_servers["p"]["requests"])
            status, _ = _send(proxy_port, _cm_request())
            reqs = mock_servers["p"]["requests"][before:]
            if len(reqs) == 1 and _cm_count(reqs) == 1 and status == 200:
                pass_("post-delist request forwarded unstripped")
            else:
                fail("post-delist request unexpected: %d calls (%d with cm)"
                     % (len(reqs), _cm_count(reqs)))
        finally:
            cleanup()
    finally:
        shutil.rmtree(state_dir, ignore_errors=True)


def test_compat_inconclusive_reschedules():
    """An inconclusive probe (non-matching 500) resets the strip counter and
    reschedules at the current threshold without doubling."""
    print("\n--- Test: Compat Inconclusive Reschedules ---")
    state_dir, state_path = _bootstrap_learned_state()
    try:
        def responder(info):
            try:
                has_cm = "context_management" in json.loads(info["body"])
            except Exception:
                has_cm = False
            if has_cm:
                return 500, "application/json", b'{"error":"internal"}'
            return _ok_response(info)

        responders = {"p": responder}
        temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
            _start_compat_proxy(responders, state_path)
        if proc is None:
            fail("restart proxy failed to start")
            return
        try:
            # Walk 31 stripped requests (2xx); request 32 reaches the
            # threshold and IS the probe — an unstripped 500 (inconclusive).
            if not _walk_strips(proxy_port, mock_servers["p"], 31):
                return
            before = len(mock_servers["p"]["requests"])
            status, _ = _send(proxy_port, _cm_request())
            reqs = mock_servers["p"]["requests"][before:]
            if not (len(reqs) == 1 and _cm_count(reqs) == 1 and status == 500):
                fail("probe not unstripped or result not passed through "
                     "(%d calls, status %s)" % (len(reqs), status))
                return
            state = _read_state_file(state_path)
            entry = next((e for e in _entry_values(_entries(state))
                          if isinstance(e, dict)
                          and e.get("feature") == "context_management"), None)
            if entry is None:
                fail("entry missing after inconclusive probe")
                return
            if entry.get("threshold") != 32:
                fail("inconclusive probe changed threshold to %r (expected "
                     "32)" % entry.get("threshold"))
                return
            pass_("inconclusive probe: threshold unchanged (no doubling)")
            # Counter reset to zero: 31 more stripped requests, then the
            # next probe.
            if not _walk_strips(proxy_port, mock_servers["p"], 31):
                return
            before = len(mock_servers["p"]["requests"])
            _send(proxy_port, _cm_request())
            reqs = mock_servers["p"]["requests"][before:]
            if len(reqs) == 1 and _cm_count(reqs) == 1:
                pass_("probe rescheduled after a full threshold of strips")
            else:
                fail("next probe not rescheduled at current threshold (%d "
                     "calls)" % len(reqs))
        finally:
            cleanup()
    finally:
        shutil.rmtree(state_dir, ignore_errors=True)


def test_compat_probe_counter_semantics():
    """Repeated rejection from probation resets probation to zero but keeps
    (and further doubles) the threshold — it never resets to base."""
    print("\n--- Test: Compat Probe Counter Semantics ---")
    state_dir, state_path = _bootstrap_learned_state()
    try:
        def _doubled_probation(entry):
            entry["state"] = "probation"
            entry["threshold"] = 64
            entry["probation_successes"] = 1
            entry["strip_counter"] = 0

        _mutate_entry(state_path, _doubled_probation)
        responders = {"p": _reject_unstripped_responder()}
        temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
            _start_compat_proxy(responders, state_path)
        if proc is None:
            fail("restart proxy failed to start")
            return
        try:
            # 7 probation strips (counter 1..7), then request 8 reaches the
            # probation quantum of 8 and IS the probe -> observed 400.
            for i in range(7):
                before = len(mock_servers["p"]["requests"])
                _send(proxy_port, _cm_request())
                reqs = mock_servers["p"]["requests"][before:]
                if len(reqs) != 1 or _cm_count(reqs) != 0:
                    fail("probation strip %d not stripped (%d calls)"
                         % (i + 1, len(reqs)))
                    return
            before = len(mock_servers["p"]["requests"])
            status, _ = _send(proxy_port, _cm_request())
            reqs = mock_servers["p"]["requests"][before:]
            if not (len(reqs) == 2 and _cm_count(reqs) == 1 and status == 200):
                fail("rejected probe pattern wrong (%d calls, status %s)"
                     % (len(reqs), status))
                return
            state = _read_state_file(state_path)
            entry = next((e for e in _entry_values(_entries(state))
                          if isinstance(e, dict)
                          and e.get("feature") == "context_management"), None)
            if entry is None:
                fail("entry missing after repeated rejection")
                return
            if entry.get("threshold") != 128:
                fail("rejection from probation: threshold %r (expected 128 = "
                     "64 doubled, not reset to base 32)"
                     % entry.get("threshold"))
                return
            if entry.get("state") != "unsupported" or \
                    entry.get("probation_successes") != 0:
                fail("rejection from probation: state=%r successes=%r "
                     "(expected unsupported/0)"
                     % (entry.get("state"), entry.get("probation_successes")))
                return
            pass_("repeated rejection: probation reset, threshold kept and "
                  "doubled (64 -> 128)")
        finally:
            cleanup()
    finally:
        shutil.rmtree(state_dir, ignore_errors=True)


ALL_TESTS = [
    # D. Thresholds / state machine
    ("compat-initial-threshold-probe", test_compat_initial_threshold_probe),
    ("compat-rejection-doubles-threshold", test_compat_rejection_doubles_threshold),
    ("compat-probation-cycle", test_compat_probation_cycle),
    ("compat-delist-after-two-successes", test_compat_delist_after_two_successes),
    ("compat-inconclusive-reschedules", test_compat_inconclusive_reschedules),
    ("compat-probe-counter-semantics", test_compat_probe_counter_semantics),
]


if __name__ == "__main__":
    run_cli(ALL_TESTS, "claude-retry-proxy tests: test_compat_policy")
