"""Compatibility retry orchestration tests: the global single-retry lock,
release on exception, the entry-time config snapshot under config swaps,
stream interaction, and metadata-only trace privacy."""

import json
import shutil
import threading
import time

from _harness import (
    _admin_post,
    _send_proxy_request_stream,
    fail,
    find_free_port,
    pass_,
    run_cli,
)

from _compat_support import (
    CM_MARKER,
    ERROR_MARKER,
    OBSERVED_400_BODY,
    REASONING_MESSAGE_400,
    UPSTREAM_ERROR_MARKER,
    _bootstrap_learned_state,
    _chat_ok_response,
    _chat_vendor,
    _cm_count,
    _cm_request,
    _compat_trace_events,
    _entries,
    _entry_values,
    _make_state_dir,
    _ok_response,
    _read_state_file,
    _reasoning_request,
    _reject_unstripped_responder,
    _rescue_trace_events,
    _send,
    _sent_reasoning_field,
    _start_compat_proxy,
    _walk_strips,
)


def test_compat_single_retry_global():
    """Concurrent first-time anthropic requests: exactly one compatibility
    retry occurs globally; losers receive the original 400.

    The same contention harness covers the reasoning feature, whose rescue is
    lock-free by design: under the credit model every concurrent complainer
    runs its own rescue and is served — the old contract ("exactly the lock
    holder is served; the rest receive the original 400") was deleted with
    the feature's retry lock. The shared per-key credit is still drained by
    the episode, so a switch lands; the post-switch re-arm makes the exact
    end state interleaving-dependent, so the switch itself is the assertion.
    How many of the five clients are served directly through the
    already-advanced selection is interleaving-dependent by design, so the
    rescue count is pinned to the complaints the mock actually received, never
    to the served count.
    """
    print("\n--- Test: Compat Single Retry Global ---")
    state_dir, state_path = _make_state_dir()

    def responder(info):
        try:
            has_cm = "context_management" in json.loads(info["body"])
        except Exception:
            has_cm = False
        if has_cm:
            time.sleep(1.0)
            return 400, "application/json", OBSERVED_400_BODY
        time.sleep(1.5)  # hold the retry lock wide open for the losers
        return _ok_response(info)

    def chat_responder(info):
        # Accepts only the advanced candidate, slowly, so concurrent
        # complainers overlap inside their rescues.
        if _sent_reasoning_field(info) == "reasoning_content":
            time.sleep(1.5)
            return _chat_ok_response(info)
        return 400, "application/json", REASONING_MESSAGE_400

    tiers = {
        "haiku": {"provider": "q", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
        "opus": {"provider": "p", "model": "claude-opus-5"},
    }
    vendors = {
        "p": {"url": "http://127.0.0.1:%d" % find_free_port(), "key": "K"},
        "q": _chat_vendor(find_free_port()),
    }
    responders = {"p": responder, "q": chat_responder}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
        _start_compat_proxy(responders, state_path, tiers=tiers,
                            vendors=vendors)
    if proc is None:
        shutil.rmtree(state_dir, ignore_errors=True)
        fail("Failed to set up test")
        return
    try:
        results = []

        def worker():
            s, _ = _send(proxy_port, _cm_request())
            results.append(s)

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(60)
        if len(results) != 5:
            fail("only %d/5 concurrent requests completed" % len(results))
            return
        reqs = mock_servers["p"]["requests"]
        unstripped = _cm_count(reqs)
        stripped = len(reqs) - unstripped
        n_ok = sum(1 for s in results if s == 200)
        if unstripped == 5 and stripped == 1 and n_ok == 1:
            pass_("global single-flight: 5 unstripped forwards, exactly 1 "
                  "stripped retry, 1 client succeeded")
        else:
            fail("single-flight broken: %d unstripped, %d stripped, %d/5 "
                 "clients 2xx" % (unstripped, stripped, n_ok))
            return
        state = _read_state_file(state_path)
        if state and _entry_values(_entries(state)):
            pass_("leader learned the entry")
        else:
            fail("leader's successful retry did not learn")
            return

        # --- reasoning feature: the same contention harness, now lock-free ---
        # Every concurrent complainer runs its own rescue, so all five are
        # served. The credit is shared per key and drains during the episode,
        # so a switch lands on the shared entry while they overlap.
        reasoning_results = []

        def reasoning_worker():
            s, _ = _send(proxy_port, _reasoning_request(model="haiku",
                                                        demanding=True))
            reasoning_results.append(s)

        threads = [threading.Thread(target=reasoning_worker)
                   for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(60)
        if len(reasoning_results) != 5:
            fail("only %d/5 concurrent reasoning requests completed"
                 % len(reasoning_results))
            return
        n_ok = sum(1 for s in reasoning_results if s == 200)
        if n_ok != 5:
            fail("the reasoning rescue is lock-free by design: %d/5 clients "
                 "2xx (every concurrent complainer must be served)" % n_ok)
            return
        pass_("all 5 concurrent complainers were served (no lock denial)")

        complaints = [r for r in mock_servers["q"]["requests"]
                      if _sent_reasoning_field(r) != "reasoning_content"]
        rescues = _rescue_trace_events(trace_file)
        if not complaints or len(rescues) != len(complaints):
            fail("expected exactly one reasoning_rescue event per complaint "
                 "the mock received, got %d for %d complaints"
                 % (len(rescues), len(complaints)))
            return
        pass_("one reasoning_rescue event per complaint the mock received "
              "(%d/%d)" % (len(rescues), len(complaints)))

        switch_events = [
            e for e in _compat_trace_events(trace_file)
            if e.get("feature") == "reasoning_field"
            and e.get("event") in ("compatibility_learned",
                                   "compatibility_switched",
                                   "compatibility_delisted")]
        if not switch_events:
            fail("the shared-key credit never reached 0 during five "
                 "complaint episodes: no reasoning_field switch event")
            return
        pass_("the shared-key credit drained during the episode (%d switch "
              "event(s))" % len(switch_events))
    finally:
        cleanup()
        shutil.rmtree(state_dir, ignore_errors=True)


def test_compat_retry_lock_released_on_exception():
    """An upstream failure during the compatibility retry releases the retry
    lock: later requests can still retry and learn."""
    print("\n--- Test: Compat Retry Lock Released On Exception ---")
    state_dir, state_path = _make_state_dir()
    mode = {"fail": True}

    def responder(info):
        try:
            has_cm = "context_management" in json.loads(info["body"])
        except Exception:
            has_cm = False
        if not has_cm:
            if mode["fail"]:
                raise RuntimeError("simulated upstream crash")
            return _ok_response(info)
        return 400, "application/json", OBSERVED_400_BODY

    responders = {"p": responder}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
        _start_compat_proxy(responders, state_path,
                            extra_env={"PROXY_MAX_RETRIES": "1",
                                       "PROXY_INITIAL_DELAY": "1"})
    if proc is None:
        shutil.rmtree(state_dir, ignore_errors=True)
        fail("Failed to set up test")
        return
    try:
        # Request 1: stripped retry crashes mid-flight -> client still gets
        # the original 400, and the lock must be released. PROXY_MAX_RETRIES=1
        # bounds the connection-error loop inside the retry so the test stays
        # fast (the loop itself is tracked in a separate issue).
        status, _ = _send(proxy_port, _cm_request())
        if status != 400:
            fail("expected original 400 after crashed retry, got %s" % status)
            return
        pass_("crashed retry returned the original 400")
        # Single-attempt bound: the compatibility retry must have made exactly
        # ONE upstream call (unstripped + 1 retry = 2 total). More calls mean
        # the compat retry re-entered the connection-error loop — see issue
        # compat-retry-not-single-attempt.
        reqs = mock_servers["p"]["requests"]
        if len(reqs) == 2:
            pass_("compatibility retry made exactly one upstream attempt")
        else:
            fail("compatibility retry made %d upstream calls (expected 2 "
                 "total: unstripped + single retry)" % len(reqs))
            return
        # Request 2: healthy upstream — the retry must be attempted (lock
        # free) and learning must succeed. Delta: unstripped 400 + stripped
        # 2xx = 2 calls, 1 with cm.
        mode["fail"] = False
        before = len(mock_servers["p"]["requests"])
        status, _ = _send(proxy_port, _cm_request())
        reqs = mock_servers["p"]["requests"][before:]
        if status != 200:
            fail("post-crash request failed (%s) — retry lock likely leaked"
                 % status)
            return
        if len(reqs) == 2 and _cm_count(reqs) == 1:
            pass_("lock released: post-crash retry ran and learned")
        else:
            fail("post-crash discovery did not retry correctly (%d calls, %d "
                 "with cm)" % (len(reqs), _cm_count(reqs)))
            return
        state = _read_state_file(state_path)
        if state and _entry_values(_entries(state)):
            pass_("learning recorded after crash recovery")
        else:
            fail("no state learned after recovery")
    finally:
        cleanup()
        shutil.rmtree(state_dir, ignore_errors=True)


def test_compat_config_swap_during_retry():
    """The compatibility retry uses the entry-time config snapshot: the
    in-flight request completes against its original provider, and the admin
    switch (whose silence-based drain waits for the live re-issue rather than
    aborting it) routes new requests elsewhere.

    This pins the boundary of the retry-loop head's epoch-only check: an
    immediate compat re-issue is live work, so an in-progress drain must not
    abort it (only backoff chains abandon at the press)."""
    print("\n--- Test: Compat Config Swap During Retry ---")
    state_dir, state_path = _make_state_dir()
    p_port = find_free_port()
    q_port = find_free_port()
    tiers = {
        "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
        "opus": {"provider": "p", "model": "claude-opus-5"},
    }
    vendors = {
        "p": {"url": "http://127.0.0.1:%d" % p_port, "key": "K-p"},
        "q": {"url": "http://127.0.0.1:%d" % q_port, "key": "K-q"},
    }

    def p_responder(info):
        try:
            has_cm = "context_management" in json.loads(info["body"])
        except Exception:
            has_cm = False
        if has_cm:
            time.sleep(0.8)
            return 400, "application/json", OBSERVED_400_BODY
        return _ok_response(info)

    responders = {"p": p_responder, "q": _ok_response}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
        _start_compat_proxy(responders, state_path, tiers=tiers,
                            vendors=vendors)
    if proc is None:
        shutil.rmtree(state_dir, ignore_errors=True)
        fail("Failed to set up test")
        return
    try:
        result = {}

        def worker():
            s, _ = _send(proxy_port, _cm_request())
            result["status"] = s

        t = threading.Thread(target=worker)
        t.start()
        time.sleep(0.2)  # request is inside p's unstripped 400 hold
        switch_body = {
            "tiers": {
                "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
                "sonnet": {"provider": "q", "model": "claude-sonnet-5"},
                "opus": {"provider": "p", "model": "claude-opus-5"},
            }
        }
        switch_status, switch_data = _admin_post(
            proxy_port, "/admin/api/switch", switch_body)
        t.join(30)
        if switch_status != 200:
            fail("admin switch failed during in-flight retry: %s %s"
                 % (switch_status, switch_data))
            return
        if result.get("status") != 200:
            fail("in-flight request did not complete (status %s)"
                 % result.get("status"))
            return
        p_reqs = mock_servers["p"]["requests"]
        q_reqs = mock_servers["q"]["requests"]
        if len(p_reqs) == 2 and _cm_count(p_reqs) == 1 and not q_reqs:
            pass_("in-flight request completed on its original provider "
                  "(p): unstripped 400 + stripped 2xx")
        else:
            fail("retry routing wrong: p=%d calls (%d with cm), q=%d calls"
                 % (len(p_reqs), _cm_count(p_reqs), len(q_reqs)))
            return
        # Post-switch: sonnet goes to q. q has no learned entry, so the body
        # must arrive unstripped.
        status, _ = _send(proxy_port, _cm_request())
        q_reqs = mock_servers["q"]["requests"]
        if status == 200 and len(q_reqs) == 1 and _cm_count(q_reqs) == 1:
            pass_("post-switch requests route to q and are not stripped")
        else:
            fail("post-switch behavior wrong: status %s, q calls %d (%d with "
                 "cm)" % (status, len(q_reqs), _cm_count(q_reqs)))
    finally:
        cleanup()
        shutil.rmtree(state_dir, ignore_errors=True)


def test_compat_retry_stream_interaction():
    """Interaction with streaming and the existing retry loop: learning works
    from streamed 2xx (status-receipt evidence, no rollback on mid-stream
    failure), and the 429/503 loop composes with the compatibility retry."""
    print("\n--- Test: Compat Retry Stream Interaction ---")
    # (a) streamed 2xx stripped retry learns; next request stripped.
    state_dir, state_path = _make_state_dir()

    def sse_responder(info):
        try:
            has_cm = "context_management" in json.loads(info["body"])
        except Exception:
            has_cm = False
        if has_cm:
            return 400, "application/json", OBSERVED_400_BODY
        return _ok_response(info, "sse")

    responders = {"p": sse_responder}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
        _start_compat_proxy(responders, state_path)
    if proc is None:
        shutil.rmtree(state_dir, ignore_errors=True)
        fail("stream proxy failed to start")
        return
    try:
        status, content_type, raw = _send_proxy_request_stream(
            proxy_port, _cm_request())
        if status != 200 or "text/event-stream" not in content_type:
            fail("streamed learning request wrong (%s, %s)"
                 % (status, content_type))
            return
        before = len(mock_servers["p"]["requests"])
        status, _ = _send(proxy_port, _cm_request())
        reqs = mock_servers["p"]["requests"][before:]
        if status == 200 and len(reqs) == 1 and _cm_count(reqs) == 0:
            pass_("streamed 2xx retry learned; next request stripped")
        else:
            fail("streamed 2xx learning broken: status %s, %d calls"
                 % (status, len(reqs)))
            return
    finally:
        cleanup()
        shutil.rmtree(state_dir, ignore_errors=True)

    # (b) mid-stream failure does not roll back learned state.
    state_dir, state_path = _make_state_dir()
    responders = {"p": _reject_unstripped_responder("truncated-sse")}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
        _start_compat_proxy(responders, state_path)
    if proc is None:
        shutil.rmtree(state_dir, ignore_errors=True)
        fail("truncated proxy failed to start")
        return
    try:
        _send_proxy_request_stream(proxy_port, _cm_request())
        before = len(mock_servers["p"]["requests"])
        status, _ = _send(proxy_port, _cm_request())
        reqs = mock_servers["p"]["requests"][before:]
        if status == 200 and len(reqs) == 1 and _cm_count(reqs) == 0:
            pass_("mid-stream truncation did not roll back learning")
        else:
            fail("truncated stream rolled back learning: status %s, %d calls"
                 % (status, len(reqs)))
            return
    finally:
        cleanup()
        shutil.rmtree(state_dir, ignore_errors=True)

    # (c) 429/503 retry loop composes with the compatibility retry.
    state_dir, state_path = _make_state_dir()
    calls = {"n": 0}
    call_lock = threading.Lock()

    def flaky(info):
        with call_lock:
            calls["n"] += 1
            n = calls["n"]
        try:
            has_cm = "context_management" in json.loads(info["body"])
        except Exception:
            has_cm = False
        if n == 1:
            return 503, "application/json", b'{"error":"unavailable"}'
        if has_cm:
            return 400, "application/json", OBSERVED_400_BODY
        return _ok_response(info)

    responders = {"p": flaky}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
        _start_compat_proxy(responders, state_path,
                            extra_env={"PROXY_INITIAL_DELAY": "1",
                                       "PROXY_MAX_DELAY": "2"})
    if proc is None:
        shutil.rmtree(state_dir, ignore_errors=True)
        fail("flaky proxy failed to start")
        return
    try:
        status, _ = _send(proxy_port, _cm_request())
        reqs = mock_servers["p"]["requests"]
        # Calls: 503 (unstripped), 400 (503-retry, still unstripped),
        # 2xx (compat retry, stripped) — 2 with cm.
        if status == 200 and len(reqs) == 3 and _cm_count(reqs) == 2:
            pass_("503 retry -> 400 discovery -> stripped retry composed "
                  "correctly (3 upstream calls, 2 unstripped)")
        else:
            fail("retry composition wrong: status %s, %d calls (%d with cm)"
                 % (status, len(reqs), _cm_count(reqs)))
    finally:
        cleanup()
        shutil.rmtree(state_dir, ignore_errors=True)


def test_compat_trace_metadata_only():
    """All compatibility_* trace events are metadata-only: no field values,
    no prompt text, no raw upstream error text."""
    print("\n--- Test: Compat Trace Metadata Only ---")
    state_dir, state_path = _bootstrap_learned_state()
    try:
        responders = {"p": _reject_unstripped_responder()}
        temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
            _start_compat_proxy(responders, state_path)
        if proc is None:
            fail("restart proxy failed to start")
            return
        try:
            # Walk 31 stripped requests, then the 32nd is the rejected probe:
            # stripped/probe/rejected events all fire in one scenario.
            if not _walk_strips(proxy_port, mock_servers["p"], 31):
                return
            status, _ = _send(proxy_port, _cm_request())  # probe -> retry
            if status != 200:
                fail("probe request failed (%s)" % status)
                return
            events = _compat_trace_events(trace_file)
            if not events:
                fail("no compatibility_* trace events recorded")
                return
            blob = json.dumps(events)
            for marker in (CM_MARKER, ERROR_MARKER, UPSTREAM_ERROR_MARKER,
                           "hello"):
                if marker in blob:
                    fail("trace events leak content marker %r" % marker)
                    return
            names = {e.get("event") for e in events}
            expected = {"compatibility_field_stripped",
                        "compatibility_probe_started",
                        "compatibility_probe_rejected"}
            missing = expected - names
            if missing:
                fail("missing expected trace events: %s (observed %s)"
                     % (sorted(missing), sorted(names)))
            else:
                pass_("all expected trace events present and metadata-only "
                      "(%d events, %d types)" % (len(events), len(names)))
        finally:
            cleanup()
    finally:
        shutil.rmtree(state_dir, ignore_errors=True)


ALL_TESTS = [
    # E. Concurrency / robustness
    ("compat-single-retry-global", test_compat_single_retry_global),
    ("compat-retry-lock-released-on-exception", test_compat_retry_lock_released_on_exception),
    ("compat-config-swap-during-retry", test_compat_config_swap_during_retry),
    ("compat-retry-stream-interaction", test_compat_retry_stream_interaction),
    # F. Trace privacy
    ("compat-trace-metadata-only", test_compat_trace_metadata_only),
]


if __name__ == "__main__":
    run_cli(ALL_TESTS, "claude-retry-proxy tests: test_compat_retry")
