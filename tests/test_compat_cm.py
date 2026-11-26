"""context_management live-loop tests: the 400-shape detector and the
learn/strip/suppress/passthrough flow through a live proxy."""

import json
import shutil

from _harness import (
    fail,
    find_free_port,
    pass_,
    run_cli,
)

from _compat_support import (
    ERROR_MARKER,
    OBSERVED_400_BODY,
    REJECTED_BODY_CORPUS,
    _cm_count,
    _cm_request,
    _compat_trace_events,
    _entries,
    _entry_values,
    _make_state_dir,
    _read_state_file,
    _reject_unstripped_responder,
    _send,
    _start_compat_proxy,
)


# Structured variant: extra_forbidden validation data locating the top-level
# field (pydantic-style loc inside the Anthropic error envelope).
STRUCTURED_400_BODY = json.dumps({
    "type": "error",
    "error": {
        "type": "invalid_request_error",
        "message": "Extra inputs are not permitted",
        "code": "extra_forbidden",
        "loc": ["body", "context_management"],
    },
}).encode()


def _always_400_responder():
    def responder(info):
        return 400, "application/json", OBSERVED_400_BODY
    return responder


def _detector_scenario(body, content_type="application/json",
                       include_cm=True, status=400):
    """Run one request against an upstream that always returns the given
    status/body. Returns (status, n_upstream_calls, n_with_cm)."""
    state_dir, state_path = _make_state_dir()

    def responder(info):
        return status, content_type, body

    responders = {"p": responder}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
        _start_compat_proxy(responders, state_path)
    try:
        if proc is None:
            fail("Failed to set up test")
            return 0, -1, -1
        status, _ = _send(proxy_port, _cm_request(include_cm=include_cm))
        reqs = mock_servers["p"]["requests"]
        return status, len(reqs), _cm_count(reqs)
    finally:
        try:
            cleanup()
        except Exception:
            pass
        shutil.rmtree(state_dir, ignore_errors=True)


def test_compat_detector_message_form():
    """The exact observed message-form 400 triggers exactly one stripped
    compatibility retry."""
    print("\n--- Test: Compat Detector Message Form ---")
    status, calls, with_cm = _detector_scenario(OBSERVED_400_BODY)
    if status != 400:
        fail("expected original 400 returned to client, got %s" % status)
    elif calls == 2 and with_cm == 1:
        pass_("message-form 400 triggered one stripped retry (2 upstream "
              "calls, 1 unstripped)")
    else:
        fail("message-form 400: expected 2 calls (1 unstripped), got %d "
             "calls (%d unstripped)" % (calls, calls - with_cm))


def test_compat_detector_structured():
    """A structured extra_forbidden 400 identifying the top-level field
    triggers exactly one stripped compatibility retry."""
    print("\n--- Test: Compat Detector Structured ---")
    status, calls, with_cm = _detector_scenario(STRUCTURED_400_BODY)
    if status != 400:
        fail("expected original 400 returned to client, got %s" % status)
    elif calls == 2 and with_cm == 1:
        pass_("structured extra_forbidden 400 triggered one stripped retry")
    else:
        fail("structured 400: expected 2 calls (1 unstripped), got %d calls "
             "(%d unstripped)" % (calls, calls - with_cm))


def test_compat_detector_nested_path_rejected():
    """A nested-path rejection (tools.0.input.context_management) does not
    trigger a compatibility retry."""
    print("\n--- Test: Compat Detector Nested Path Rejected ---")
    nested = json.dumps({
        "type": "error",
        "error": {
            "type": "invalid_request_error",
            "message": "tools.0.input.context_management: "
                       "Extra inputs are not permitted",
        },
    }).encode()
    status, calls, with_cm = _detector_scenario(nested)
    if status != 400:
        fail("expected 400 passthrough, got %s" % status)
    elif calls == 1:
        pass_("nested-path 400 passed through with no compatibility retry")
    else:
        fail("nested-path 400 triggered %d upstream calls (expected 1)"
             % calls)
        return
    # Structured variant: a nested loc path must not match either.
    structured_nested = json.dumps({
        "type": "error",
        "error": {
            "type": "invalid_request_error",
            "code": "extra_forbidden",
            "loc": ["body", "tools", "0", "context_management"],
        },
    }).encode()
    status, calls, with_cm = _detector_scenario(structured_nested)
    if calls == 1:
        pass_("structured nested loc passed through with no retry")
    else:
        fail("structured nested loc triggered %d upstream calls (expected 1)"
             % calls)


def test_compat_detector_content_type_agnostic():
    """Detection is content-type-agnostic: a JSON body with a text/plain
    Content-Type still matches; a non-JSON body is inconclusive."""
    print("\n--- Test: Compat Detector Content Type Agnostic ---")
    status, calls, with_cm = _detector_scenario(
        OBSERVED_400_BODY, content_type="text/plain")
    if calls == 2 and with_cm == 1:
        pass_("text/plain Content-Type with JSON body still matched")
    else:
        fail("content-type-agnostic detection failed: %d calls (%d "
             "unstripped)" % (calls, calls - with_cm))
        return

    status, calls, with_cm = _detector_scenario(
        b"this is not json at all", content_type="application/json")
    if calls == 1:
        pass_("non-JSON 400 body inconclusive (no retry)")
    else:
        fail("non-JSON body triggered %d upstream calls (expected 1)" % calls)


def test_compat_detector_unrelated_400_rejected():
    """Broad invalid-request, auth, model, quota, and context-limit 400s
    never trigger a compatibility retry or learning, and neither does any
    entry of the shared rejected-body corpus."""
    print("\n--- Test: Compat Detector Unrelated 400 Rejected ---")
    unrelated = [
        ("broad-invalid-request", 400, {
            "type": "error",
            "error": {"type": "invalid_request_error",
                      "message": "Invalid request payload"},
        }),
        ("auth-error", 400, {
            "type": "error",
            "error": {"type": "authentication_error",
                      "message": "invalid x-api-key"},
        }),
        ("model-not-found", 400, {
            "type": "error",
            "error": {"type": "not_found_error",
                      "message": "model not found: claude-sonnet-5"},
        }),
        ("quota", 400, {
            "type": "error",
            "error": {"type": "billing_error",
                      "message": "quota exceeded for this project"},
        }),
        ("context-limit", 400, {
            "type": "error",
            "error": {"type": "invalid_request_error",
                      "message": "prompt is too long: 250000 tokens > "
                                 "200000 maximum"},
        }),
    ]
    corpus = [(label, status, json.dumps(payload).encode())
              for label, status, payload in unrelated]
    corpus += REJECTED_BODY_CORPUS
    for label, resp_status, body in corpus:
        got, calls, with_cm = _detector_scenario(body, status=resp_status)
        if calls != 1:
            fail("%s (status %d) triggered %d upstream calls (expected 1, "
                 "no compatibility retry)" % (label, resp_status, calls))
            return
        if got != resp_status:
            fail("%s: client saw status %d, expected the upstream's %d"
                 % (label, got, resp_status))
            return
    pass_("all unrelated forms and every shared-corpus reject passed "
          "through with no retry")


def test_compat_detector_presence_required():
    """A matching 400 for a request whose body lacks context_management does
    not trigger a compatibility retry."""
    print("\n--- Test: Compat Detector Presence Required ---")
    status, calls, with_cm = _detector_scenario(
        OBSERVED_400_BODY, include_cm=False)
    if calls == 1:
        pass_("no compatibility retry when the field is absent")
    else:
        fail("absent-field request produced %d upstream calls (expected 1)"
             % calls)


def test_compat_learn_on_400_stripped_2xx():
    """Initial 400 followed by a 2xx stripped retry learns unsupported
    state; the next matching request is stripped."""
    print("\n--- Test: Compat Learn On 400 Stripped 2xx ---")
    state_dir, state_path = _make_state_dir()
    responders = {"p": _reject_unstripped_responder()}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
        _start_compat_proxy(responders, state_path)
    if proc is None:
        shutil.rmtree(state_dir, ignore_errors=True)
        fail("Failed to set up test")
        return
    try:
        status, body = _send(proxy_port, _cm_request())
        if status != 200:
            fail("learning request returned %s (expected 2xx from stripped "
                 "retry)" % status)
            return
        reqs = mock_servers["p"]["requests"]
        if len(reqs) != 2 or _cm_count(reqs) != 1:
            fail("expected 400 + stripped 2xx (2 calls, 1 unstripped), got "
                 "%d calls (%d unstripped)" % (len(reqs),
                                               len(reqs) - _cm_count(reqs)))
            return
        pass_("discovery: 400 then successful stripped retry")
        if _read_state_file(state_path) is None:
            fail("state file not written after learning")
            return
        learned = _compat_trace_events(trace_file, "compatibility_learned")
        if not learned:
            fail("no compatibility_learned trace event")
            return
        pass_("compatibility_learned trace event emitted")
    finally:
        cleanup()
        shutil.rmtree(state_dir, ignore_errors=True)


def test_compat_no_learn_when_retry_fails():
    """When the stripped retry also fails, the client gets the original 400
    (model-rewritten) and nothing is learned."""
    print("\n--- Test: Compat No Learn When Retry Fails ---")
    state_dir, state_path = _make_state_dir()
    responders = {"p": _always_400_responder()}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
        _start_compat_proxy(responders, state_path)
    if proc is None:
        shutil.rmtree(state_dir, ignore_errors=True)
        fail("Failed to set up test")
        return
    try:
        status, body = _send(proxy_port, _cm_request())
        if status != 400:
            fail("expected original 400, got %s" % status)
            return
        if ERROR_MARKER.encode() not in body:
            fail("client did not receive the original upstream error body")
            return
        reqs = mock_servers["p"]["requests"]
        if len(reqs) != 2 or _cm_count(reqs) != 1:
            fail("expected exactly one compatibility retry (2 calls, 1 "
                 "unstripped), got %d calls" % len(reqs))
            return
        pass_("failed confirmation returns original 400 after one retry")
        state = _read_state_file(state_path)
        if state and _entry_values(_entries(state)):
            fail("state learned despite failed confirmation")
        else:
            pass_("no state learned on failed confirmation")
    finally:
        cleanup()
        shutil.rmtree(state_dir, ignore_errors=True)


def test_compat_failed_confirmation_suppression():
    """After 3 failed confirmations, compatibility retries are suppressed;
    discovery re-arms after a request-count interval (the threshold)."""
    print("\n--- Test: Compat Failed Confirmation Suppression ---")
    state_dir, state_path = _make_state_dir()
    responders = {"p": _always_400_responder()}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
        _start_compat_proxy(responders, state_path)
    if proc is None:
        shutil.rmtree(state_dir, ignore_errors=True)
        fail("Failed to set up test")
        return
    try:
        # Requests 1-3: each attempts one compatibility retry (2 calls each).
        for i in range(3):
            _send(proxy_port, _cm_request())
        reqs = mock_servers["p"]["requests"]
        if len(reqs) != 6:
            fail("expected 3 confirmations x 2 calls = 6, got %d" % len(reqs))
            return
        pass_("first 3 matching requests each attempted one retry")
        # Request 4+: suppressed (1 call each).
        _send(proxy_port, _cm_request())
        _send(proxy_port, _cm_request())
        reqs = mock_servers["p"]["requests"]
        if len(reqs) != 8:
            fail("suppressed requests still retrying: %d calls after 5 "
                 "requests (expected 8)" % len(reqs))
            return
        events = _compat_trace_events(
            trace_file, "compatibility_failed_confirmation_suppressed")
        if not events:
            fail("no compatibility_failed_confirmation_suppressed event")
            return
        pass_("retries suppressed after 3 failed confirmations (event "
              "emitted)")
        # Re-entry: after at most `threshold` (32) further matching requests,
        # discovery retries again (a 2-call request appears). Suppressed
        # requests cost 1 call each; the re-armed request costs 2.
        reentered_at = None
        baseline = len(mock_servers["p"]["requests"])
        for i in range(1, 35):
            _send(proxy_port, _cm_request())
            delta = len(mock_servers["p"]["requests"]) - baseline
            if delta >= i + 1:
                reentered_at = i
                break
        if reentered_at is None:
            fail("discovery never re-armed within threshold + margin")
        elif reentered_at <= 33:
            pass_("discovery re-armed after %d suppressed requests (interval "
                  "= threshold)" % reentered_at)
        else:
            fail("discovery re-armed after %d requests (expected <= 33)"
                 % reentered_at)
    finally:
        cleanup()
        shutil.rmtree(state_dir, ignore_errors=True)


def test_compat_strip_immediate_after_learn():
    """Learned state strips on the very next matching request."""
    print("\n--- Test: Compat Strip Immediate After Learn ---")
    state_dir, state_path = _make_state_dir()
    responders = {"p": _reject_unstripped_responder()}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
        _start_compat_proxy(responders, state_path)
    if proc is None:
        shutil.rmtree(state_dir, ignore_errors=True)
        fail("Failed to set up test")
        return
    try:
        _send(proxy_port, _cm_request())  # learn
        for i in range(3):
            before = len(mock_servers["p"]["requests"])
            status, _ = _send(proxy_port, _cm_request())
            reqs = mock_servers["p"]["requests"][before:]
            if status != 200 or len(reqs) != 1 or _cm_count(reqs) != 0:
                fail("post-learn request %d not stripped (%s, %d calls)"
                     % (i + 1, status, len(reqs)))
                return
        pass_("requests 2-4 stripped immediately after learning")
    finally:
        cleanup()
        shutil.rmtree(state_dir, ignore_errors=True)


def test_compat_key_isolation_live():
    """Learning through the live flow isolates by (provider, mode, model):
    other providers and models are unaffected."""
    print("\n--- Test: Compat Key Isolation Live ---")
    state_dir, state_path = _make_state_dir()
    p_port = find_free_port()
    q_port = find_free_port()
    tiers = {
        "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
        "opus": {"provider": "q", "model": "claude-opus-5"},
    }
    vendors = {
        "p": {"url": "http://127.0.0.1:%d" % p_port, "key": "K-p"},
        "q": {"url": "http://127.0.0.1:%d" % q_port, "key": "K-q"},
    }
    responders = {"p": _reject_unstripped_responder(),
                  "q": _reject_unstripped_responder()}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
        _start_compat_proxy(responders, state_path, tiers=tiers,
                            vendors=vendors)
    if proc is None:
        shutil.rmtree(state_dir, ignore_errors=True)
        fail("Failed to set up test")
        return
    try:
        # Learn on p/claude-sonnet-5 via the sonnet tier.
        _send(proxy_port, _cm_request(model="sonnet"))
        p_reqs = mock_servers["p"]["requests"]
        if len(p_reqs) != 2 or _cm_count(p_reqs) != 1:
            fail("learning on p failed (%d calls)" % len(p_reqs))
            return
        # Same provider, different model: haiku not stripped (fresh
        # discovery, 2 calls).
        before = len(p_reqs)
        _send(proxy_port, _cm_request(model="haiku"))
        new = p_reqs[before:]
        if len(new) != 2 or _cm_count(new) != 1:
            fail("model key not isolated: haiku made %d calls (%d unstripped)"
                 % (len(new), len(new) - _cm_count(new)))
            return
        pass_("different model on same provider unaffected")
        # Different provider: opus on q — not stripped (fresh discovery).
        _send(proxy_port, _cm_request(model="opus"))
        q_reqs = mock_servers["q"]["requests"]
        if len(q_reqs) == 2 and _cm_count(q_reqs) == 1:
            pass_("different provider unaffected (fresh discovery)")
        else:
            fail("provider isolation broken: q saw %d calls (%d unstripped)"
                 % (len(q_reqs), len(q_reqs) - _cm_count(q_reqs)))
    finally:
        cleanup()
        shutil.rmtree(state_dir, ignore_errors=True)


def test_compat_unknown_field_passthrough():
    """Other unknown fields are never stripped or learned — even when the
    upstream 400 names them with an extra-inputs message."""
    print("\n--- Test: Compat Unknown Field Passthrough ---")
    state_dir, state_path = _make_state_dir()
    other_400 = json.dumps({
        "type": "error",
        "error": {"type": "invalid_request_error",
                  "message": "future_beta_field: "
                             "Extra inputs are not permitted"},
    }).encode()

    def responder(info):
        return 400, "application/json", other_400

    responders = {"p": responder}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
        _start_compat_proxy(responders, state_path)
    if proc is None:
        shutil.rmtree(state_dir, ignore_errors=True)
        fail("Failed to set up test")
        return
    try:
        body = _cm_request(include_cm=False)
        body["future_beta_field"] = {"enabled": True}
        for i in range(2):
            status, _ = _send(proxy_port, body)
            if status != 400:
                fail("expected 400 passthrough, got %s" % status)
                return
        reqs = mock_servers["p"]["requests"]
        if len(reqs) != 2:
            fail("unknown-field 400 triggered %d upstream calls for 2 "
                 "requests (expected 2 — no retry)" % len(reqs))
            return
        state = _read_state_file(state_path)
        if state and _entry_values(_entries(state)):
            fail("state learned for a non-context_management field")
            return
        pass_("unknown field: no retry, no learning (constant-anchored)")
    finally:
        cleanup()
        shutil.rmtree(state_dir, ignore_errors=True)


def test_compat_non_matching_400_passthrough():
    """A non-matching 400 on a context_management request passes through
    with no compatibility retry and no state change."""
    print("\n--- Test: Compat Non Matching 400 Passthrough ---")
    state_dir, state_path = _make_state_dir()
    nonmatching = json.dumps({
        "type": "error",
        "error": {"type": "invalid_request_error",
                  "message": "messages.2: Field required"},
    }).encode()

    def responder(info):
        return 400, "application/json", nonmatching

    responders = {"p": responder}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
        _start_compat_proxy(responders, state_path)
    if proc is None:
        shutil.rmtree(state_dir, ignore_errors=True)
        fail("Failed to set up test")
        return
    try:
        status, body = _send(proxy_port, _cm_request())
        if status != 400:
            fail("expected 400, got %s" % status)
            return
        if b"Field required" not in body:
            fail("upstream error body not passed through to client")
            return
        reqs = mock_servers["p"]["requests"]
        if len(reqs) != 1:
            fail("non-matching 400 triggered %d upstream calls (expected 1)"
                 % len(reqs))
            return
        state = _read_state_file(state_path)
        if state and _entry_values(_entries(state)):
            fail("state learned from a non-matching 400")
            return
        pass_("non-matching 400: single call, body preserved, no learning")
    finally:
        cleanup()
        shutil.rmtree(state_dir, ignore_errors=True)


def test_compat_one_retry_cap():
    """At most one compatibility retry per client request
    (COMPAT_MAX_RETRIES_PER_REQUEST = 1)."""
    print("\n--- Test: Compat One Retry Cap ---")
    state_dir, state_path = _make_state_dir()
    responders = {"p": _always_400_responder()}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
        _start_compat_proxy(responders, state_path)
    if proc is None:
        shutil.rmtree(state_dir, ignore_errors=True)
        fail("Failed to set up test")
        return
    try:
        status, _ = _send(proxy_port, _cm_request())
        reqs = mock_servers["p"]["requests"]
        if len(reqs) != 2:
            fail("expected exactly 2 upstream calls (original + 1 retry), "
                 "got %d" % len(reqs))
            return
        pass_("exactly one compatibility retry per client request")
    finally:
        cleanup()
        shutil.rmtree(state_dir, ignore_errors=True)


def test_compat_count_tokens_excluded():
    """count_tokens requests skip compatibility processing entirely."""
    print("\n--- Test: Compat Count Tokens Excluded ---")
    state_dir, state_path = _make_state_dir()
    responders = {"p": _always_400_responder()}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
        _start_compat_proxy(responders, state_path)
    if proc is None:
        shutil.rmtree(state_dir, ignore_errors=True)
        fail("Failed to set up test")
        return
    try:
        status, _ = _send(proxy_port, _cm_request(),
                          path="/v1/messages/count_tokens")
        reqs = mock_servers["p"]["requests"]
        if len(reqs) != 1:
            fail("count_tokens 400 triggered %d upstream calls (expected 1, "
                 "no compatibility retry)" % len(reqs))
            return
        state = _read_state_file(state_path)
        if state and _entry_values(_entries(state)):
            fail("state learned from a count_tokens request")
            return
        pass_("count_tokens excluded from compatibility processing")
    finally:
        cleanup()
        shutil.rmtree(state_dir, ignore_errors=True)


ALL_TESTS = [
    # B. Detector
    ("compat-detector-message-form", test_compat_detector_message_form),
    ("compat-detector-structured", test_compat_detector_structured),
    ("compat-detector-nested-path-rejected", test_compat_detector_nested_path_rejected),
    ("compat-detector-content-type-agnostic", test_compat_detector_content_type_agnostic),
    ("compat-detector-unrelated-400-rejected", test_compat_detector_unrelated_400_rejected),
    ("compat-detector-presence-required", test_compat_detector_presence_required),
    # C. Learn/strip flow
    ("compat-learn-on-400-stripped-2xx", test_compat_learn_on_400_stripped_2xx),
    ("compat-no-learn-when-retry-fails", test_compat_no_learn_when_retry_fails),
    ("compat-failed-confirmation-suppression", test_compat_failed_confirmation_suppression),
    ("compat-strip-immediate-after-learn", test_compat_strip_immediate_after_learn),
    ("compat-key-isolation-live", test_compat_key_isolation_live),
    ("compat-unknown-field-passthrough", test_compat_unknown_field_passthrough),
    ("compat-non-matching-400-passthrough", test_compat_non_matching_400_passthrough),
    ("compat-one-retry-cap", test_compat_one_retry_cap),
    ("compat-count-tokens-excluded", test_compat_count_tokens_excluded),
]


if __name__ == "__main__":
    run_cli(ALL_TESTS, "claude-retry-proxy tests: test_compat_cm")
