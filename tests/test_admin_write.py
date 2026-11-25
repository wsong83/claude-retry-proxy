"""Admin write-path invariants, in-process: serialization failures, nesting-gate ordering, and the apply/re-check pair.

Part of the claude-retry-proxy suite; runnable standalone.
"""
from _harness import (
    fail,
    pass_,
    run_cli,
)
import io
import json
import os
import shutil
import tempfile


def _drive_post_in_process(srv, path, body_bytes, client_port=55557):
    """Invoke `do_POST` for an admin path with no socket, capturing the response.

    The `object.__new__(srv.ProxyHandler)` pattern the reload-stale gate above
    already uses: the handler's globals are module state, so these tests can put
    the exact interleaving they need on it rather than racing a live server.
    Returns the list of (status, body) tuples `_send_response` was called with.
    """
    captured = []
    handler = object.__new__(srv.ProxyHandler)
    handler.path = path
    handler.client_address = ("127.0.0.1", client_port)
    handler.headers = {
        "Content-Length": str(len(body_bytes)),
        "Origin": "http://127.0.0.1:{}".format(srv.SETTINGS.port),
    }
    handler.rfile = io.BytesIO(body_bytes)
    handler.wfile = io.BytesIO()
    handler._send_response = (
        lambda status, body, headers=None: captured.append((status, body)))
    handler.do_POST()
    return captured


def _drive_get_in_process(srv, path, client_port=55559):
    """Invoke `do_GET` for an admin path with no socket, capturing the response.

    The GET analogue of `_drive_post_in_process` above, for the branches no live
    proxy can reach: `/admin/api/config`'s serialize-failure arm needs
    `_current_config` to hold a document that decodes but cannot re-encode,
    which startup validation would never admit. Returns the list of
    (status, body) tuples `_send_response` was called with.

    It has NO try/except: a handler exception propagates to the caller rather
    than coming back as an empty list. That propagation IS the pre-guard
    failure mode (an unguarded `json.dumps` aborts `do_GET` with no HTTP
    response at all), so callers wrap the call to tell "answered nothing" apart
    from "raised", and the `captured` list is empty only when the handler
    genuinely sent no response.
    """
    captured = []
    handler = object.__new__(srv.ProxyHandler)
    handler.path = path
    handler.client_address = ("127.0.0.1", client_port)
    handler.headers = {}
    handler.wfile = io.BytesIO()
    handler._send_response = (
        lambda status, body, headers=None: captured.append((status, body)))
    handler.do_GET()
    return captured


def test_admin_config_serialize_failure_500():
    """GET /admin/api/config answers 500 — and stays usable — when the in-memory
    config decodes but cannot re-encode (plan 2026-11-01-admin-config-500-surface,
    adopting defer-issue-config-serialize-500-no-committed-coverage).

    The branch is reachable in real state: the encoder's stack ceiling sits below
    the decoder's (~15,505 vs ~16,915 on the shipping interpreter), so a
    hand-edited config.json inside that band starts fine, serves every other
    endpoint, and 500s this one. Until now it was covered only by transient
    `./tmp/verification/` scripts the post-commit sweep retires, so a regression
    would have been silent.

    No deep-nesting fixture: a tier carrying an unknown per-tier key whose value
    is a `set` reaches `json.dumps` and raises `TypeError`, the same
    `except Exception:` a `RecursionError` reaches — and it measures this code
    rather than the interpreter's stack, so it cannot go flaky across machines.

    Four assertions, each with a reachable failing branch on an unguarded
    handler: the response ARRIVES (an unguarded handler raises out of `do_GET`
    instead of answering), the status is 500, the body is exactly the
    documented refusal, and a second GET answers 200 with the restored document
    once a serializable one is in place.
    """
    print("\n--- Test: Admin API Config Serialize Failure Is a 500 ---")
    import claude_retry_proxy.server as srv
    import claude_retry_proxy.runtime_state as runtime_state

    provider = "p1"
    model = "claude-sonnet-5"
    tiers = ("haiku", "sonnet", "opus")
    saved = runtime_state._current_config
    # {1, 2} is the unserializable value: a set has no JSON encoder.
    poisoned = {
        "tiers": {t: {"provider": provider, "model": model, "key": "",
                      "poison": {1, 2}} for t in tiers},
        "models": {provider: [model]},
    }
    try:
        runtime_state._current_config = poisoned
        try:
            captured = _drive_get_in_process(srv, "/admin/api/config")
        except Exception as e:
            fail("the config handler raised instead of answering ({0}: {1}) — an "
                 "unguarded json.dumps aborts do_GET with no HTTP response at "
                 "all, so a client watches a hung request".format(
                     type(e).__name__, e))
            return
        if not captured:
            fail("the config handler sent no response for a document that "
                 "decodes but cannot re-encode")
            return
        status, body = captured[-1]
        text = body.decode("utf-8", "replace")
        if status != 500:
            fail("a config that decodes but cannot re-encode must answer 500; "
                 "got {} ({})".format(status, text[:300]))
            return
        pass_("an unserializable config answered 500")
        try:
            parsed = json.loads(text)
        except Exception as e:
            fail("the 500 body is not JSON: {} ({!r})".format(e, text[:300]))
            return
        expected = {"error": "the configuration could not be serialized"}
        if parsed != expected:
            fail("the 500 body is not the documented refusal (the admin surface "
                 "deliberately carries the flat {{error}} shape, not the "
                 "Anthropic envelope); got {!r}".format(parsed))
            return
        pass_("the 500 body is exactly {\"error\": \"the configuration could "
              "not be serialized\"}")
    finally:
        runtime_state._current_config = saved

    # Survival: the guard must not wedge the endpoint. The document is set to a
    # LITERAL serializable one rather than "restored" from `saved`: in this
    # test's context `saved` is `None` (server.py initializes the global to
    # None and no in-process server ever runs here), so restoring it would
    # assert 200 on `json.dumps(None)` — a document no proxy ever serves — and
    # prove nothing about a real config coming back.
    restored = {
        "tiers": {t: {"provider": provider, "model": model, "key": ""}
                  for t in tiers},
        "models": {provider: [model]},
    }
    try:
        runtime_state._current_config = restored
        try:
            captured = _drive_get_in_process(srv, "/admin/api/config")
        except Exception as e:
            fail("the handler raised on the GET that followed the failed "
                 "serialization ({0}: {1})".format(type(e).__name__, e))
            return
        if not captured:
            fail("the handler sent no response after a serializable config was "
                 "restored")
            return
        status, body = captured[-1]
        if status != 200:
            fail("the endpoint did not recover once a serializable config was "
                 "restored; got {} ({!r})".format(status, body[:200]))
            return
        try:
            served = json.loads(body.decode("utf-8", "replace"))
        except Exception as e:
            fail("the recovered 200 body is not JSON: {} ({!r})".format(
                e, body[:200]))
            return
        if served != restored:
            fail("the recovered 200 body is not the restored document; got "
                 "{!r}".format(served))
            return
        pass_("the endpoint answers 200 again with the restored document once a "
              "serializable config is back")
    finally:
        runtime_state._current_config = saved


def test_switch_nesting_gate_precedes_key_echo():
    """`/admin/api/switch` refuses a >limit body at the NESTING GATE, before the
    `key` echo — and the echo branch is still live for containers that pass it.

    Adopts `defer-issue-switch-key-name-container-echo` by construction. Every
    failure branch on this path formats the raw value — the isinstance test is
    the branch's trigger, not a guard — so a deeply nested container in `key`,
    `provider` or `model` would reach `str()`, which recurses per nesting level,
    and a RecursionError there has no enclosing try: the request would die with
    no HTTP response at all. (Tier names are exempt only by JSON grammar, which
    makes object keys strings.) What closes that class is not the
    interpreter's repr headroom but the ORDER: `check_payload_nesting` runs at
    the top of the branch, so any body past `MAX_JSON_NESTING_DEPTH` is refused
    `400 nesting_limit_exceeded`, bounding a `key` container to <= 497 levels
    (root -> tiers -> tier). Nothing drove a deep `key` through this handler
    before this test, so a reorder or a removed gate would reopen the abort
    class with the suite green.

    The DEEP half is the pin, and it DISCRIMINATES the two orderings rather than
    green-lighting anything: with the gate gone (removed, or moved after
    validation) the SAME body reaches the echo and answers `invalid key name`.
    The body therefore carries all three required tiers, deep container last —
    a one-tier body would answer `missing tiers` instead, which is a different
    rejection and would leave the pin pointing at the wrong rule. The SHALLOW
    half keeps it non-vacuous — a container that PASSES the gate is still
    echoed, proving the echo branch is alive and sits AFTER the gate.

    In-process (`_drive_post_in_process`) rather than over a socket: both
    branches fire before the first catalog read, so no proxy, vendor or model
    catalog is needed, and an abort-class failure raises here instead of
    surfacing as a transport error the caller could mistake for a timeout.

    The deep half asserts only the DELTA this test uniquely proves: a response
    exists at all, and it does not carry the key echo. The shared gate
    branch's status, flat `{"error","code"}` shape, `nesting_limit_exceeded`
    code and limit-naming message are pinned end-to-end over a real proxy by
    `test_nesting_limit_admin_body` (test_tier_routing.py); repeating them here
    would read as two independent pins of one branch. What only this test can
    show is the ORDER, and `invalid key name`'s absence is the assertion that
    carries it — a handler reordered to validate first, or a gate removed,
    answers with the echo instead.
    """
    print("\n--- Test: Switch Nesting Gate Precedes Key Echo ---")
    import claude_retry_proxy.server as srv
    import claude_retry_proxy.forwarder as forwarder
    import claude_retry_proxy.runtime_state as runtime_state

    limit = srv.MAX_JSON_NESTING_DEPTH
    # A real container, not a string of brackets: brackets inside a JSON string
    # do not count as nesting (the scanner is string-aware), so a bracketed
    # string would sail through the gate and prove nothing. Depth in the body
    # reaches limit + 103 — the root object, `tiers`, the tier object, then the
    # list itself.
    #
    # ALL THREE required tiers are present, with the deep container LAST. That is
    # load-bearing for the discriminant: the required-tier check runs BEFORE the
    # per-tier loop, so a one-tier deep body would answer `missing tiers` rather
    # than the echo once the gate is gone — the pin would then discriminate the
    # tier check, not the `key` echo this deferral is about. Measured both ways;
    # see the round's discriminant script.
    deep = json.loads("[" * (limit + 100) + "]" * (limit + 100))
    deep_body = json.dumps({"tiers": {
        "haiku": {"provider": "p", "model": "m", "key": "k"},
        "sonnet": {"provider": "p", "model": "m", "key": "k"},
        "opus": {"provider": "p", "model": "m", "key": deep}}}).encode("utf-8")

    # Both bodies are refused before any install, so nothing is mutated today.
    # The regression this test guards — gate removed or moved after validation —
    # is precisely a run where the handler could proceed past the field checks,
    # and a red run must not leave the process-global config state changed for
    # every later test in the same process. Snapshot/restore the neighbours'
    # way, and assert the refusal left the epoch alone (a refusal must never
    # advance it).
    saved_srv = {name: getattr(runtime_state, name) for name in (
        "_config_path", "_current_config", "_vendors")}
    saved_fwd = {name: getattr(forwarder._drain, name) for name in (
        "_config_epoch", "_config_swapping", "_inflight_count")}
    epoch_before = forwarder._drain._config_epoch
    try:
        try:
            captured = _drive_post_in_process(srv, "/admin/api/switch",
                                              deep_body)
        except Exception as e:
            fail("the switch handler RAISED on a >limit body instead of "
                 "answering ({0}: {1}) — the abort class this ordering "
                 "closes".format(type(e).__name__, e))
            return
        if not captured:
            fail("the switch handler sent NO response at all for a >limit body "
                 "— the request dies with no HTTP answer")
            return
        _status, body = captured[-1]
        text = body.decode("utf-8", "replace")
        if "invalid key name" in text:
            fail("the key echo answered a body the gate must refuse FIRST — the "
                 "echo runs before, or without, the nesting gate: {}".format(
                     text[:300]))
            return
        pass_("a >limit body was answered without the key echo — the nesting "
              "gate ran first")

        # Non-vacuity: a CONTAINER key that passes the gate is still echoed.
        # Without this half, a handler that rejected every container `key`
        # before the echo — or an echo branch deleted outright — would leave
        # the deep half green.
        shallow_body = json.dumps({"tiers": {
            name: {"provider": "p", "model": "m", "key": ["a"]}
            for name in ("haiku", "sonnet", "opus")}}).encode("utf-8")
        try:
            captured = _drive_post_in_process(srv, "/admin/api/switch",
                                              shallow_body)
        except Exception as e:
            fail("the switch handler raised on a shallow container key ({0}: "
                 "{1})".format(type(e).__name__, e))
            return
        if not captured:
            fail("the switch handler sent no response for a shallow container "
                 "key")
            return
        status, body = captured[-1]
        text = body.decode("utf-8", "replace")
        if status != 400:
            fail("a container key that passes the gate must be refused 400 by "
                 "the name check; got {} ({})".format(status, text[:300]))
            return
        if "invalid key name: ['a']" not in text:
            fail("the echo branch did not answer for a container key that "
                 "passes the gate — expected \"invalid key name: ['a']\" in the "
                 "body: {}".format(text[:300]))
            return
        if "nesting_limit_exceeded" in text:
            fail("a body WITHIN the nesting limit was refused by the gate: "
                 "{}".format(text[:300]))
            return
        pass_("a container key within the limit is still echoed "
              "\"invalid key name: ['a']\" — the echo branch is live and runs "
              "after the gate")

        if forwarder._drain._config_epoch != epoch_before:
            fail("a refused switch must not advance the config epoch; {} -> "
                 "{}".format(epoch_before, forwarder._drain._config_epoch))
            return
        pass_("both refusals left the config epoch unchanged")
    finally:
        runtime_state._config_path = saved_srv["_config_path"]
        runtime_state._current_config = saved_srv["_current_config"]
        runtime_state._vendors = saved_srv["_vendors"]
        forwarder._drain._config_epoch = saved_fwd["_config_epoch"]
        forwarder._drain._config_swapping = saved_fwd["_config_swapping"]
        forwarder._drain._inflight_count = saved_fwd["_inflight_count"]


def test_admin_reload_serialize_failure_500():
    """The reload answers 500 — and installs nothing — when its success body
    cannot be serialized (plan 2026-10-25, Step 8 coder edit 3).

    The success body embeds `candidate`, whose `tiers` are the IN-MEMORY
    document (`_current_config.get("tiers", {})`), so the branch needs no
    deep-nesting fixture: a tier carrying an unknown per-tier key whose value is
    a `set` passes the membership gate and `validate_config` (which ignores
    unknown per-tier keys) and then raises `TypeError` inside `json.dumps`.
    That is the same `except Exception:` a `RecursionError` would reach — the
    property the guard exists for — and it measures this code rather than the
    interpreter's stack, so it cannot go flaky across machines.

    THREE assertions, each with a reachable failing branch on the pre-Step-8
    tree: serializing after the install would leave the swap applied and the
    epoch bumped while the client got NO response at all (the exception
    propagates out of `do_POST`), so this test would error rather than pass; a
    rebuilt-but-equal document fails the identity check (`is`, not `==`); and a
    stray epoch bump fails the last one.
    """
    print("\n--- Test: Admin Reload Serialize Failure Is a 500 ---")
    import claude_retry_proxy.server as srv
    import claude_retry_proxy.forwarder as forwarder
    import claude_retry_proxy.runtime_state as runtime_state

    provider = "p1"
    model = "claude-sonnet-5"
    tiers = ("haiku", "sonnet", "opus")
    temp_dir = tempfile.mkdtemp()
    saved_srv = {}
    saved_fwd = {}
    try:
        with open(os.path.join(temp_dir, "models.json"), "w",
                  encoding="utf-8") as f:
            json.dump({"models": {provider: [model]}}, f)
        config_path = os.path.join(temp_dir, "config.json")
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump({"tiers": {t: {"provider": provider, "model": model}
                                 for t in tiers}}, f)

        # A document that JSON-decodes, validates, and then cannot re-encode.
        poisoned = {
            "tiers": {t: {"provider": provider, "model": model, "key": "",
                          "poison": {1, 2}} for t in tiers},
            "models": {provider: [model]},
        }

        saved_srv = {name: getattr(runtime_state, name) for name in (
            "_config_path", "_current_config", "_vendors")}
        saved_fwd = {name: getattr(forwarder._drain, name) for name in (
            "_config_epoch", "_config_swapping", "_inflight_count",
            "_swap_evictions", "_swap_started_at")}
        runtime_state._config_path = config_path
        runtime_state._current_config = poisoned
        forwarder._drain._config_epoch = 5
        runtime_state._vendors = {provider: {"url": "http://127.0.0.1:1", "key": "k-p1"}}
        forwarder._drain._config_swapping = False
        forwarder._drain._inflight_count = 0
        forwarder._drain._swap_evictions = 0

        captured = _drive_post_in_process(srv, "/admin/api/reload", b"")
        if not captured:
            fail("the reload handler sent no response (the serialize failure "
                 "escaped do_POST — the pre-Step-8 behaviour)")
            return
        status, body = captured[-1]
        text = body.decode("utf-8", "replace")
        if status != 500:
            fail("a candidate that decodes but cannot re-encode must answer 500; "
                 "got {} ({})".format(status, text[:300]))
            return
        pass_("reload of an unserializable candidate answered 500")
        if "the configuration could not be serialized" not in text:
            fail("the 500 does not carry the message: {}".format(text[:300]))
            return
        pass_("the 500 names the serialization failure")
        if runtime_state._current_config is not poisoned:
            fail("the 500 branch installed a config — _current_config is no "
                 "longer the poisoned document ({}); a truthful 500 installs "
                 "nothing".format(type(runtime_state._current_config).__name__))
            return
        pass_("nothing was installed (_current_config is still the poisoned doc)")
        if forwarder._drain._config_epoch != 5:
            fail("a refused reload must not bump the epoch; got {}".format(
                forwarder._drain._config_epoch))
            return
        pass_("no epoch bump was taken")
    finally:
        # Guarded: the snapshots above populate INSIDE the try, so a setup
        # failure before that point leaves the dicts empty — an unguarded
        # restore would raise KeyError and mask the real exception.
        if saved_srv:
            runtime_state._config_path = saved_srv["_config_path"]
            runtime_state._current_config = saved_srv["_current_config"]
            runtime_state._vendors = saved_srv["_vendors"]
        if saved_fwd:
            forwarder._drain._config_epoch = saved_fwd["_config_epoch"]
            forwarder._drain._config_swapping = saved_fwd["_config_swapping"]
            forwarder._drain._inflight_count = saved_fwd["_inflight_count"]
            forwarder._drain._swap_evictions = saved_fwd["_swap_evictions"]
            forwarder._drain._swap_started_at = saved_fwd["_swap_started_at"]
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_admin_reload_serializability_probe_precedes_drain():
    """The reload decides its success body is serializable BEFORE the press
    (plan 2026-10-25, Step 10 coder edit B; Step 11 Part B).

    Step 8's guard made the serialize failure answer `500` instead of aborting
    with no response — but it did so AFTER `forwarder._drain.drain()`, which
    pauses every new admission, waits with no wall-clock cap, and abandons retry
    chains. A press that can never succeed therefore still performed a
    disruptive press. The probe added ahead of the drain makes the refusal free.

    The assertion that makes this a test of ORDERING rather than of the guard is
    the invocation count: `forwarder._drain.drain` is reached through the
    singleton the handler calls, so shadowing it on the instance with a counting
    stand-in measures whether the press happened at all. The post-drain guard is
    still there and is pinned separately by
    `test_admin_reload_serialize_failure_500` — this test would pass with the
    probe present even if that guard were removed, and would FAIL on the
    pre-Step-10 tree where the same 500 arrives after a drain (count 1).

    The poisoned document is the same fixture the post-drain test uses: a tier
    carrying an unknown per-tier key whose value is a `set` passes the
    membership gate and `validate_config`, then raises `TypeError` in
    `json.dumps`. `TypeError` and `RecursionError` both reach the same
    `except Exception:`, so this measures the guard's property without a
    stack-depth fixture that would go flaky across machines.
    """
    print("\n--- Test: Admin Reload Serializability Probe Precedes the Drain ---")
    import claude_retry_proxy.server as srv
    import claude_retry_proxy.forwarder as forwarder
    import claude_retry_proxy.runtime_state as runtime_state

    provider = "p1"
    model = "claude-sonnet-5"
    tiers = ("haiku", "sonnet", "opus")
    temp_dir = tempfile.mkdtemp()
    real_drain = forwarder._drain.drain
    saved_srv = {}
    saved_fwd = {}
    try:
        with open(os.path.join(temp_dir, "models.json"), "w",
                  encoding="utf-8") as f:
            json.dump({"models": {provider: [model]}}, f)
        config_path = os.path.join(temp_dir, "config.json")
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump({"tiers": {t: {"provider": provider, "model": model}
                                 for t in tiers}}, f)

        poisoned = {
            "tiers": {t: {"provider": provider, "model": model, "key": "",
                          "poison": {1, 2}} for t in tiers},
            "models": {provider: [model]},
        }

        saved_srv = {name: getattr(runtime_state, name) for name in (
            "_config_path", "_current_config", "_vendors")}
        saved_fwd = {name: getattr(forwarder._drain, name) for name in (
            "_config_epoch", "_config_swapping", "_inflight_count",
            "_swap_evictions", "_swap_started_at")}
        runtime_state._config_path = config_path
        runtime_state._current_config = poisoned
        forwarder._drain._config_epoch = 5
        runtime_state._vendors = {provider: {"url": "http://127.0.0.1:1", "key": "k-p1"}}
        forwarder._drain._config_swapping = False
        forwarder._drain._inflight_count = 0
        forwarder._drain._swap_evictions = 0

        drain_calls = []

        def counting_drain():
            """Record the press, then run the real drain."""
            drain_calls.append(1)
            return real_drain()

        forwarder._drain.drain = counting_drain

        captured = _drive_post_in_process(srv, "/admin/api/reload", b"")
        if not captured:
            fail("the reload handler sent no response (the serialize failure "
                 "escaped do_POST)")
            return
        status, body = captured[-1]
        text = body.decode("utf-8", "replace")
        if status != 500:
            fail("an unserializable candidate must answer 500; got {} "
                 "({})".format(status, text[:300]))
            return
        pass_("reload of an unserializable candidate answered 500")
        if "the configuration could not be serialized" not in text:
            fail("the 500 does not carry the message: {}".format(text[:300]))
            return
        pass_("the 500 names the serialization failure")
        if drain_calls:
            fail("the reload drained {} time(s) before refusing — a press that "
                 "can never succeed must not pause admissions or abandon retry "
                 "chains".format(len(drain_calls)))
            return
        pass_("no drain ran: the refusal happened before the press "
              "(forwarder._drain.drain invocations = 0)")

        # POSITIVE CONTROL. `len(drain_calls) == 0` means nothing unless the
        # counting stand-in can ever observe a press. Drive the SAME handler,
        # with the same rebinding, over a candidate that serializes: the drain
        # must now run exactly once and the reload must succeed. Without this
        # case a stand-in that silently never fires would pass the assertion
        # above.
        runtime_state._current_config = {
            "tiers": {t: {"provider": provider, "model": model, "key": ""}
                      for t in tiers},
            "models": {provider: [model]},
        }
        captured = _drive_post_in_process(srv, "/admin/api/reload", b"")
        if not captured:
            fail("positive control: the reload handler sent no response")
            return
        status, body = captured[-1]
        if status != 200:
            fail("positive control: a serializable candidate must reload 200; "
                 "got {} ({})".format(
                     status, body.decode("utf-8", "replace")[:300]))
            return
        pass_("positive control: a serializable candidate reloaded 200")
        if len(drain_calls) == 1:
            pass_("positive control: the counting stand-in observed exactly one "
                  "press — the zero count above is a measurement")
        else:
            fail("positive control: the counting stand-in observed {} press(es); "
                 "the zero-count assertion above cannot be trusted".format(
                     len(drain_calls)))
    finally:
        del forwarder._drain.drain
        # Guarded: the snapshots above populate INSIDE the try, so a setup
        # failure before that point leaves the dicts empty — an unguarded
        # restore would raise KeyError and mask the real exception. The drain
        # stand-in and the temp-dir removal stay unconditional.
        if saved_srv:
            runtime_state._config_path = saved_srv["_config_path"]
            runtime_state._current_config = saved_srv["_current_config"]
            runtime_state._vendors = saved_srv["_vendors"]
        if saved_fwd:
            forwarder._drain._config_epoch = saved_fwd["_config_epoch"]
            forwarder._drain._config_swapping = saved_fwd["_config_swapping"]
            forwarder._drain._inflight_count = saved_fwd["_inflight_count"]
            forwarder._drain._swap_evictions = saved_fwd["_swap_evictions"]
            forwarder._drain._swap_started_at = saved_fwd["_swap_started_at"]
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_admin_switch_apply_rewrites_tier_map():
    """Apply rewrites the tier map to the three standard tiers — the documented
    contract, pinned so a change to it fails loudly (plan 2026-10-25, Step 10
    edit D; Step 11 Part C).

    The page's `saveConfig` builds `newConfig.tiers` from `TIERS` — the three
    standard tiers only — so a documented EXTRA tier present in the live config
    is deleted by the next Apply press. That was measured during the
    iteration-3 audit and the operator chose to DOCUMENT it rather than seed the
    build from `config.tiers`, because seeding makes every Apply press 400
    whenever a preserved extra names a model absent from the live catalog.

    THIS PINS A DELIBERATE, DOCUMENTED BEHAVIOUR, NOT A BUG. If a later change
    ever round-trips extras through the page (or otherwise makes Apply preserve
    them), this test fails, and whoever made that change must update
    `doc/operations.html`'s "Apply rewrites the tier map" paragraph in the same
    change — update the doc, not this assertion, unless the contract itself is
    being re-decided.

    The contrast with `test_admin_switch_extra_tier_persisted` is deliberate and
    they do not contradict: the API honours and persists a fourth tier when the
    client SENDS one; the page sends only three. Do not "reconcile" them.
    """
    print("\n--- Test: Admin Switch Apply Rewrites the Tier Map ---")
    import claude_retry_proxy.server as srv
    import claude_retry_proxy.forwarder as forwarder
    import claude_retry_proxy.runtime_state as runtime_state

    provider = "p1"
    model = "claude-sonnet-5"
    standard = ("haiku", "sonnet", "opus")
    temp_dir = tempfile.mkdtemp()
    saved_srv = {}
    saved_fwd = {}
    try:
        four_tiers = {t: {"provider": provider, "model": model}
                      for t in standard}
        four_tiers["ghost-tier"] = {"provider": provider, "model": model}
        config_path = os.path.join(temp_dir, "config.json")
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump({"tiers": four_tiers}, f)

        saved_srv = {name: getattr(runtime_state, name) for name in (
            "_config_path", "_current_config", "_vendors")}
        saved_fwd = {name: getattr(forwarder._drain, name) for name in (
            "_config_epoch", "_config_swapping", "_inflight_count",
            "_swap_evictions", "_swap_started_at")}
        runtime_state._config_path = config_path
        runtime_state._current_config = {
            "tiers": {t: dict(cfg) for t, cfg in four_tiers.items()},
            "models": {provider: [model]},
        }
        forwarder._drain._config_epoch = 5
        runtime_state._vendors = {provider: {"url": "http://127.0.0.1:1", "key": "k-p1"}}
        forwarder._drain._config_swapping = False
        forwarder._drain._inflight_count = 0
        forwarder._drain._swap_evictions = 0

        # Page-identical: `saveConfig` builds exactly provider/model/key per
        # standard tier, with `key: value || ''`.
        page_body = {"tiers": {
            t: {"provider": provider, "model": model, "key": ""}
            for t in standard
        }}
        captured = _drive_post_in_process(
            srv, "/admin/api/switch", json.dumps(page_body).encode("utf-8"))
        if not captured:
            fail("the switch handler sent no response")
            return
        status, resp = captured[-1]
        text = resp.decode("utf-8", "replace")
        if status != 200:
            fail("a page-identical three-tier press must answer 200; got {} "
                 "({})".format(status, text[:300]))
            return
        pass_("page-identical press returned 200")

        expected = set(standard)
        with open(config_path) as fh:
            disk = json.load(fh).get("tiers", {})
        if set(disk) == expected:
            pass_("the persisted tier map is exactly the three standard tiers "
                  "(the extra tier was rewritten away, as documented)")
        else:
            fail("the persisted tier map is {!r}, expected exactly {!r} — if "
                 "Apply now preserves extra tiers, update doc/operations.html's "
                 "'Apply rewrites the tier map' paragraph in the same "
                 "change".format(sorted(disk), sorted(expected)))
        if set(runtime_state._current_config.get("tiers", {})) == expected:
            pass_("the in-memory tier map is exactly the three standard tiers")
        else:
            fail("the in-memory tier map is {!r}, expected exactly {!r}".format(
                sorted(runtime_state._current_config.get("tiers", {})),
                sorted(expected)))
        if disk.get("haiku", {}).get("key") == "default":
            pass_("the empty key selector resolved to the provider's first key")
        else:
            fail("the persisted key selector did not resolve: {!r}".format(
                disk.get("haiku")))
    finally:
        # Guarded: the snapshots above populate INSIDE the try, so a setup
        # failure before that point leaves the dicts empty — an unguarded
        # restore would raise KeyError and mask the real exception.
        if saved_srv:
            runtime_state._config_path = saved_srv["_config_path"]
            runtime_state._current_config = saved_srv["_current_config"]
            runtime_state._vendors = saved_srv["_vendors"]
        if saved_fwd:
            forwarder._drain._config_epoch = saved_fwd["_config_epoch"]
            forwarder._drain._config_swapping = saved_fwd["_config_swapping"]
            forwarder._drain._inflight_count = saved_fwd["_inflight_count"]
            forwarder._drain._swap_evictions = saved_fwd["_swap_evictions"]
            forwarder._drain._swap_started_at = saved_fwd["_swap_started_at"]
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_admin_switch_rechecks_catalog_after_epoch_move():
    """The switch re-checks the LIVE catalog when the epoch moves during its
    drain (plan 2026-10-25, Step 8 coder edit 2).

    The press validates against a catalog snapshot taken before it owns the
    swap, while Phase 3 carries the LIVE catalog forward — so a reload that
    completes in between can leave the switch persisting a tier the Reload path
    then refuses. `forwarder._drain.drain` is reached through the singleton the
    switch handler calls, so shadowing it on the instance puts this test exactly
    inside that window with no scheduling race.

    Two cases, and the second is what makes the first meaningful: refusing
    whenever the epoch moved would pass case 1 and fail case 2, and would be
    wrong — nothing about a catalog that still lists the model is stale.
    """
    print("\n--- Test: Admin Switch Re-checks the Catalog After an Epoch Move ---")
    import claude_retry_proxy.server as srv
    import claude_retry_proxy.forwarder as forwarder
    import claude_retry_proxy.runtime_state as runtime_state

    provider = "p1"
    model = "claude-sonnet-5"
    tiers = ("haiku", "sonnet", "opus")
    real_drain = forwarder._drain.drain
    saved_srv = {name: getattr(runtime_state, name) for name in (
        "_config_path", "_current_config", "_vendors")}
    saved_fwd = {name: getattr(forwarder._drain, name) for name in (
        "_config_epoch", "_config_swapping", "_inflight_count",
        "_swap_evictions", "_swap_started_at")}
    temp_dirs = []
    try:
        def fresh_state():
            """A distinct temp config per case, plus the process state around it."""
            import claude_retry_proxy.forwarder as forwarder
            temp_dir = tempfile.mkdtemp()
            temp_dirs.append(temp_dir)
            config_path = os.path.join(temp_dir, "config.json")
            baseline = {t: {"provider": provider, "model": model} for t in tiers}
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump({"tiers": baseline}, f)
            runtime_state._config_path = config_path
            runtime_state._current_config = {
                "tiers": {t: dict(cfg) for t, cfg in baseline.items()},
                "models": {provider: [model]},
            }
            forwarder._drain._config_epoch = 5
            runtime_state._vendors = {provider: {"url": "http://127.0.0.1:1",
                                       "key": "k-p1"}}
            forwarder._drain._config_swapping = False
            forwarder._drain._inflight_count = 0
            forwarder._drain._swap_evictions = 0
            return config_path, baseline

        def disk_tiers(config_path):
            with open(config_path) as f:
                return json.load(f).get("tiers", {})

        switch_tiers = {t: {"provider": provider, "model": model} for t in tiers}
        switch_tiers["ghost-tier"] = {"provider": provider, "model": model}
        body = json.dumps({"tiers": switch_tiers}).encode("utf-8")

        # --- Case 1: a reload lands during the drain and drops the model. ----
        config_path, baseline = fresh_state()

        def reload_lands_dropping_model():
            import claude_retry_proxy.forwarder as forwarder
            forwarder._drain._config_epoch += 1                 # a reload completed here...
            runtime_state._current_config["models"] = {provider: []}   # ...minus the model
            return real_drain()

        forwarder._drain.drain = reload_lands_dropping_model
        captured = _drive_post_in_process(srv, "/admin/api/switch", body)
        if not captured:
            fail("case 1: the switch handler sent no response")
            return
        status, resp = captured[-1]
        text = resp.decode("utf-8", "replace")
        if status != 400:
            fail("case 1: a catalog that lost the model during the drain must "
                 "refuse 400; got {} ({})".format(status, text[:300]))
            return
        pass_("case 1: refused 400 instead of persisting a tier Reload rejects")
        if ("unknown model '{}' for provider '{}'".format(model, provider)
                not in text):
            fail("case 1: the 400 does not name the model and provider: "
                 "{}".format(text[:300]))
            return
        named_tier = [t for t in tiers if "tier '{}'".format(t) in text]
        if not named_tier:
            fail("case 1: the 400 does not name the offending tier: "
                 "{}".format(text[:300]))
            return
        pass_("case 1: the 400 names tier '{}', the model and the provider".format(
            named_tier[0]))
        if disk_tiers(config_path) != baseline:
            fail("case 1: the refused switch wrote to config.json: {!r}".format(
                disk_tiers(config_path)))
            return
        pass_("case 1: the persisted config.json is untouched")
        if forwarder._drain._config_epoch != 6:
            fail("case 1: the refused switch took its own epoch bump; got "
                 "{}".format(forwarder._drain._config_epoch))
            return
        pass_("case 1: no install and no epoch bump of its own")

        # --- Case 2: the epoch moves, but the catalog still lists the model. -
        config_path, baseline = fresh_state()

        def reload_lands_keeping_model():
            import claude_retry_proxy.forwarder as forwarder
            forwarder._drain._config_epoch += 1                 # a reload completed here...
            return real_drain()                    # ...and the model survived

        forwarder._drain.drain = reload_lands_keeping_model
        captured = _drive_post_in_process(srv, "/admin/api/switch", body)
        if not captured:
            fail("case 2: the switch handler sent no response")
            return
        status, resp = captured[-1]
        text = resp.decode("utf-8", "replace")
        if status != 200:
            fail("case 2: an epoch move whose catalog still lists the model is "
                 "NOT stale and must succeed; got {} ({})".format(status,
                                                                  text[:300]))
            return
        pass_("case 2: answered 200 (the re-check gates on the catalog, not on "
              "the epoch alone)")
        persisted = disk_tiers(config_path)
        ghost = persisted.get("ghost-tier")
        if not isinstance(ghost, dict) or ghost.get("model") != model:
            fail("case 2: the applied tier did not reach config.json: {!r}".format(
                ghost))
            return
        pass_("case 2: the extra tier reached the persisted config.json")
        if runtime_state._current_config.get("models") != {provider: [model]}:
            fail("case 2: the live catalog was not carried forward: {!r}".format(
                runtime_state._current_config.get("models")))
            return
        pass_("case 2: the live catalog was carried forward")
    finally:
        del forwarder._drain.drain
        runtime_state._config_path = saved_srv["_config_path"]
        runtime_state._current_config = saved_srv["_current_config"]
        runtime_state._vendors = saved_srv["_vendors"]
        forwarder._drain._config_epoch = saved_fwd["_config_epoch"]
        forwarder._drain._config_swapping = saved_fwd["_config_swapping"]
        forwarder._drain._inflight_count = saved_fwd["_inflight_count"]
        forwarder._drain._swap_evictions = saved_fwd["_swap_evictions"]
        forwarder._drain._swap_started_at = saved_fwd["_swap_started_at"]
        for temp_dir in temp_dirs:
            shutil.rmtree(temp_dir, ignore_errors=True)


ALL_TESTS = [
    ("admin-config-serialize-failure-500",
     test_admin_config_serialize_failure_500),
    ("admin-switch-nesting-gate-precedes-key-echo",
     test_switch_nesting_gate_precedes_key_echo),
    ("admin-reload-serialize-failure-500",
     test_admin_reload_serialize_failure_500),
    ("admin-reload-serializability-probe-precedes-drain",
     test_admin_reload_serializability_probe_precedes_drain),
    ("admin-switch-apply-rewrites-tier-map",
     test_admin_switch_apply_rewrites_tier_map),
    ("admin-switch-rechecks-catalog-after-epoch-move",
     test_admin_switch_rechecks_catalog_after_epoch_move),
]


if __name__ == "__main__":
    run_cli(ALL_TESTS, "claude-retry-proxy tests: test_admin_write")
