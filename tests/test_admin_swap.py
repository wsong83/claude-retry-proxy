"""Config-swap drain races, process level: silence eviction, single-flight presses, and the stale-candidate guard.

Part of the claude-retry-proxy suite; runnable standalone.
"""
from _harness import (
    _admin_get,
    _admin_post,
    _send_proxy_request,
    _send_proxy_request_stream,
    _start_admin_proxy,
    _trace_events_named,
    _trace_file_in,
    _wait_admin_swapping,
    _wait_for_trace_events,
    _wait_upstream_request,
    fail,
    find_free_port,
    pass_,
    run_cli,
)
import io
import json
import os
import shutil
import tempfile
import threading
import time


# ===========================================================================
# Config-swap drain: silence-based drain, retryable eviction, single-flight
# (plan 2026-10-12-swap-silence-drain)
# ===========================================================================

# The swap tests drive a 2 s silence budget; the 30 s default would make every
# one of them silently run at 30 s (and read budget_s 30 from the status
# endpoint). The drain's quiet window is budget + _SWAP_QUIET_GRACE(2 s).
_SWAP_BUDGET_ENV = {"PROXY_SWAP_SILENCE_TIMEOUT": "2"}


def _anthropic_sse(*events):
    """Serialize anthropic-mode SSE frames (`event: <type>` + data + blank line)."""
    out = bytearray()
    for ev in events:
        out += ("event: " + ev["type"] + "\ndata: " + json.dumps(ev) + "\n\n").encode()
    return bytes(out)


def _msg_start(model="claude-sonnet-5"):
    return {"type": "message_start", "message": {
        "id": "msg_swap", "type": "message", "role": "assistant",
        "content": [], "model": model, "stop_reason": None, "stop_sequence": None,
        "usage": {"input_tokens": 1, "output_tokens": 0}}}


def _text_delta(text, index=0):
    return {"type": "content_block_delta", "index": index,
            "delta": {"type": "text_delta", "text": text}}


def _msg_stop():
    return {"type": "message_stop"}


def _switch_body(sonnet_provider):
    """A complete three-tier switch body moving sonnet to `sonnet_provider`."""
    return {"tiers": {
        "haiku": {"provider": "p1", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": sonnet_provider, "model": "claude-sonnet-5"},
        "opus": {"provider": "p1", "model": "claude-opus-5"},
    }}


def _swap_proxy(streamers=None, responders=None, extra_env=None,
                provider_names=("p1", "p2"), models=None):
    """Start an admin proxy for the swap tests: sonnet -> p1, p2 (and extras) available.

    `streamers` maps vendor -> handler_fn(handler, info) for a fixture-driven
    streaming upstream; `responders` maps vendor -> responder(info). extra_env
    defaults to a 2 s swap silence budget. `models` overrides the provider
    catalog written to models.json (the concurrent-press test sizes it to widen
    the reload handler's pre-press window deterministically).

    Returns (proxy_port, proc, mock_servers, temp_dir, trace_file, cleanup).
    """
    tiers = {
        "haiku": {"provider": "p1", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "p1", "model": "claude-sonnet-5"},
        "opus": {"provider": "p1", "model": "claude-opus-5"},
    }
    vendors = {}
    for name in provider_names:
        vendors[name] = {"url": "http://127.0.0.1:{}".format(find_free_port()),
                         "key": "k-" + name}
    env = dict(_SWAP_BUDGET_ENV)
    if extra_env:
        env.update(extra_env)
    proxy_port, proc, mock_servers, temp_dir, cleanup = _start_admin_proxy(
        tiers, vendors, models=models, extra_env=env, responders=responders,
        streamers=streamers)
    return (proxy_port, proc, mock_servers, temp_dir,
            _trace_file_in(temp_dir), cleanup)


def _stream_request_in_thread(port, out, body=None):
    """POST a request on a background thread; the result lands in out['result']."""
    if body is None:
        body = {"model": "sonnet", "stream": True,
                "messages": [{"role": "user", "content": "hi"}]}

    def worker():
        try:
            out["result"] = _send_proxy_request_stream(port, body)
        except Exception as e:
            out["result"] = (0, "", str(e).encode())

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    return t


def _admin_get_json(proxy_port, path):
    """GET an admin endpoint and decode JSON; returns (status, payload|None)."""
    status, body, _ = _admin_get(proxy_port, path)
    try:
        return status, json.loads(body)
    except Exception:
        return status, None


def test_switch_succeeds_during_long_live_stream():
    """A continuously-streaming request in flight at the press is waited to
    completion, not killed — the plan's "live work is waited to completion,
    unbounded by wall-clock".

    The stream runs 6.0 s (10 chunks at 0.6 s), deliberately LONGER than the
    drain's quiet window (budget + _SWAP_QUIET_GRACE = 4 s): chunks arrive
    every 0.6 s against a 2 s budget, so the shared activity clock never reads
    quiet and the drain must exit on count == 0 when the stream ends. Asserts
    the switch 200 carries drained True / inflight_at_swap 1, the client
    received the COMPLETE stream, and a post-switch request routes to the new
    provider."""
    print("\n--- Test: Switch Waits Out a Long Live Stream ---")
    n_chunks = 10
    gap = 0.6
    first_chunk = threading.Event()

    def streamer(handler, info):
        handler.send_response(200)
        handler.send_header("Content-Type", "text/event-stream")
        handler.end_headers()
        handler.wfile.write(_anthropic_sse(_msg_start()))
        handler.wfile.flush()
        first_chunk.set()
        for i in range(n_chunks):
            time.sleep(gap)
            handler.wfile.write(_anthropic_sse(_text_delta("chunk-{}".format(i))))
            handler.wfile.flush()
        handler.wfile.write(_anthropic_sse(_msg_stop()))
        handler.wfile.flush()

    proxy_port, proc, mock_servers, temp_dir, trace_file, cleanup = _swap_proxy(
        streamers={"p1": streamer})
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        out = {}
        client = _stream_request_in_thread(proxy_port, out)
        if not first_chunk.wait(5):
            fail("upstream never streamed its first chunk")
            return
        status, data = _admin_post(
            proxy_port, "/admin/api/switch", _switch_body("p2"), timeout=30)
        client.join(20)
        if status != 200:
            fail("switch during a live stream returned {}: {}".format(status, data))
            return
        resp = json.loads(data)
        if resp.get("drained") is not True:
            fail("a waited-out live stream must report drained True, got {!r}".format(
                resp.get("drained")))
            return
        if not isinstance(resp.get("waited_s"), (int, float)) or resp["waited_s"] > 20:
            fail("waited_s must be a small number, got {!r}".format(resp.get("waited_s")))
            return
        if resp.get("inflight_at_swap") != 1:
            fail("inflight_at_swap must be 1, got {!r}".format(resp.get("inflight_at_swap")))
            return
        cstatus, _ctype, raw = out.get("result", (0, "", b""))
        if cstatus != 200:
            fail("client stream status {}, expected 200".format(cstatus))
            return
        missing = [i for i in range(n_chunks)
                   if ("chunk-{}".format(i)).encode() not in raw]
        if missing:
            fail("client stream is incomplete; missing chunks {}".format(missing))
            return
        if b"message_stop" not in raw:
            fail("client stream lacks message_stop")
            return
        if _trace_events_named(trace_file, "swap_abort"):
            fail("a waited-out live stream must not be evicted")
            return
        st, _ = _send_proxy_request(proxy_port, body=json.dumps(
            {"model": "sonnet", "messages": [{"role": "user", "content": "hi"}]}))
        if st == 200 and len(mock_servers["p2"]["requests"]) == 1:
            pass_("switch waited the live stream to completion; client got all {} "
                  "chunks; post-switch routes to p2".format(n_chunks))
        else:
            fail("post-switch routing wrong: status {}, p2 calls {}".format(
                st, len(mock_servers["p2"]["requests"])))
    finally:
        cleanup()


def test_switch_evicts_silent_stream():
    """A stream that emits a byte AFTER the press and then goes silent is
    evicted at its next READ BOUNDARY — inside the drain, so `drained: false`.

    Re-based (plan 2026-11-15-httpx2-transport-sse) from the deleted 30 s armed
    socket wake onto read-boundary semantics: httpx2 has no mid-stream timeout
    API, so a blocked read wakes only at PROXY_READ_TIMEOUT. The timing basis
    is therefore:
      - the request read timeout is pinned to its 10 s validation floor; a
        smaller value is refused by design and falls back to 120;
      - the swap's silence budget is raised to 10 s, so its quiet window
        (budget + _SWAP_QUIET_GRACE = 12 s) OUTLIVES the read boundary. The
        straggler therefore wakes inside the drain, is evicted there, and the
        drain then exits on count zero — which is what makes `drained: false`
        deterministic instead of a race with the quiet window;
      - the switch returns at the read boundary (~10 s), not within the budget.
    If this flakes, the read-boundary wake is not firing (or the quiet window
    is mis-measured) — not a timing accident.
    """
    print("\n--- Test: Switch Evicts a Silent Stream ---")
    read_timeout = 10
    budget = 10  # quiet window budget + 2 must exceed read_timeout
    grace = 2
    post_press_byte = threading.Event()

    def streamer(handler, info):
        handler.send_response(200)
        handler.send_header("Content-Type", "text/event-stream")
        handler.end_headers()
        handler.wfile.write(_anthropic_sse(_msg_start()))
        handler.wfile.flush()
        # The fixture shape matters: a straggler that was already silent before
        # the press is a LATE exit (see the dedicated test). This one emits a
        # byte after the press, so its next read is armed at the read timeout
        # while the drain is still running — its wake is deterministic.
        post_press_byte.wait(15)
        handler.wfile.write(_anthropic_sse(_text_delta("post-press")))
        handler.wfile.flush()
        time.sleep(30)  # hold silently

    proxy_port, proc, mock_servers, temp_dir, trace_file, cleanup = _swap_proxy(
        streamers={"p1": streamer},
        extra_env={"PROXY_READ_TIMEOUT": str(read_timeout),
                   "PROXY_SWAP_SILENCE_TIMEOUT": str(budget)})
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        out = {}
        client = _stream_request_in_thread(proxy_port, out)
        if not _wait_upstream_request(mock_servers, "p1"):
            fail("upstream never received the stream request")
            return
        switch_out = {}
        sw = threading.Thread(
            target=lambda: switch_out.update(
                zip(("status", "data"), _admin_post(
                    proxy_port, "/admin/api/switch", _switch_body("p2"), timeout=40))),
            daemon=True)
        sw.start()
        if _wait_admin_swapping(proxy_port) is None:
            fail("swap never became visible on /admin/api/swap-status")
            return
        post_press_byte.set()
        t0 = time.time()
        sw.join(40)
        elapsed = time.time() - t0
        client.join(30)
        status = switch_out.get("status")
        data = switch_out.get("data")
        if status != 200:
            fail("switch of a silent stream returned {}: {}".format(status, data))
            return
        if not (read_timeout - 1 <= elapsed <= read_timeout + grace + 8):
            fail("switch returned after {:.1f}s, outside [{}s, {}s] — the "
                 "eviction must land at the {}s read boundary".format(
                     elapsed, read_timeout - 1, read_timeout + grace + 8,
                     read_timeout))
            return
        resp = json.loads(data)
        if resp.get("drained") is not False:
            fail("an eviction must report drained False, got {!r}".format(resp.get("drained")))
            return
        if resp.get("inflight_at_swap") != 1:
            fail("inflight_at_swap must be 1, got {!r}".format(resp.get("inflight_at_swap")))
            return
        cstatus, _ctype, raw = out.get("result", (0, "", b""))
        if cstatus != 200:
            fail("client stream status {}, expected 200".format(cstatus))
            return
        if b"post-press" not in raw:
            fail("the post-press chunk must reach the client before eviction")
            return
        if b"config swap in progress" not in raw:
            fail("evicted stream must end with the retryable config_swap_restart error")
            return
        if b"message_stop" in raw:
            fail("an evicted stream must not carry a normal terminal")
            return
        aborts = _wait_for_trace_events(trace_file, "swap_abort")
        stream_aborts = [e for e in aborts if e.get("phase") == "stream"]
        if not stream_aborts:
            fail("no swap_abort event with phase 'stream'; got {}".format(aborts))
            return
        st, _ = _send_proxy_request(proxy_port, body=json.dumps(
            {"model": "sonnet", "messages": [{"role": "user", "content": "hi"}]}))
        if st == 200 and len(mock_servers["p2"]["requests"]) == 1:
            pass_("silent post-press stream evicted in {:.1f}s; drained False; "
                  "client got the retryable error; post-switch routes to p2".format(elapsed))
        else:
            fail("post-switch routing wrong: status {}, p2 calls {}".format(
                st, len(mock_servers["p2"]["requests"])))
    finally:
        cleanup()


def test_switch_silent_before_press_is_late_exit():
    """The accepted late-exit boundary, pinned so it is not mistaken for a bug —
    plus the shared-clock discrimination that stops it passing for the wrong
    reason.

    Boundary: the straggler's upstream sends two chunks then holds the socket
    open silently; the press lands while its loop is ALREADY blocked in its
    read (bounded by PROXY_READ_TIMEOUT — 120 s at this test's default, not the
    swap budget), so the drain cannot evict it. The client-side error lands at
    the straggler's own wake, so this test does not assert its timing — it
    asserts only that the old-routing bytes delivered at that wake are not
    forwarded (the epoch check fires before the forward).

    Clock discrimination: a SECOND request is in flight and keeps emitting a
    sub-budget cadence past the press, for longer than the drain's quiet window
    (budget + _SWAP_QUIET_GRACE). The quiet window is measured from the last
    upstream byte across ALL in-flight requests, so the drain cannot exit while
    that cadence runs: waited_s must exceed the quiet window (a drain reading a
    press-stamped local exits at exactly budget + grace), and the concurrently
    live request must be waited to completion rather than evicted."""
    print("\n--- Test: Silent-Before-Press Stream Is a Late Exit ---")
    quiet_window = 2 + 2      # SETTINGS.swap_silence_timeout + _SWAP_QUIET_GRACE
    live_gap = 0.4
    live_chunks = 13          # 5.2 s — deliberately longer than quiet_window
    late_wake = threading.Event()
    live_first = threading.Event()

    def streamer(handler, info):
        handler.send_response(200)
        handler.send_header("Content-Type", "text/event-stream")
        handler.end_headers()
        if b"STRAGGLER" in info.get("body", b""):
            # Both pre-press chunks land immediately, so the proxy's next read
            # blocks BEFORE the press and is bounded only by PROXY_READ_TIMEOUT
            # (120 s at this test's default) — the un-wakeable read this
            # boundary is about.
            handler.wfile.write(_anthropic_sse(_msg_start(), _text_delta("pre-press")))
            handler.wfile.flush()
            late_wake.wait(30)
            handler.wfile.write(_anthropic_sse(_text_delta("OLD-ROUTING-MARKER")))
            handler.wfile.flush()
            return
        # The concurrently-live request: a sub-budget cadence keeps refreshing
        # the shared activity clock well past the press.
        handler.wfile.write(_anthropic_sse(_msg_start()))
        handler.wfile.flush()
        live_first.set()
        for i in range(live_chunks):
            time.sleep(live_gap)
            handler.wfile.write(_anthropic_sse(_text_delta("live-{}".format(i))))
            handler.wfile.flush()
        handler.wfile.write(_anthropic_sse(_msg_stop()))
        handler.wfile.flush()

    proxy_port, proc, mock_servers, temp_dir, trace_file, cleanup = _swap_proxy(
        streamers={"p1": streamer})
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        live_out = {}
        live = _stream_request_in_thread(proxy_port, live_out, body={
            "model": "sonnet", "stream": True,
            "messages": [{"role": "user", "content": "LIVE"}]})
        if not live_first.wait(5):
            fail("the concurrently-live request never streamed")
            return
        out = {}
        client = _stream_request_in_thread(proxy_port, out, body={
            "model": "sonnet", "stream": True,
            "messages": [{"role": "user", "content": "STRAGGLER"}]})
        deadline = time.time() + 5
        while len(mock_servers["p1"]["requests"]) < 2 and time.time() < deadline:
            time.sleep(0.05)
        if len(mock_servers["p1"]["requests"]) < 2:
            fail("upstream never received both requests")
            return
        time.sleep(0.4)  # let the proxy forward the chunks and block in read
        t0 = time.time()
        status, data = _admin_post(
            proxy_port, "/admin/api/switch", _switch_body("p2"), timeout=30)
        elapsed = time.time() - t0
        if status != 200:
            fail("switch of a late-exit straggler returned {}: {}".format(status, data))
            return
        if elapsed > 20:
            fail("the quiet path must terminate, took {:.1f}s".format(elapsed))
            return
        resp = json.loads(data)
        if resp.get("drained") is not True:
            fail("nothing is evicted during the drain, so drained must be True, got {!r}".format(
                resp.get("drained")))
            return
        if resp.get("inflight_at_swap") != 2:
            fail("both requests are in flight at the press, so inflight_at_swap "
                 "must be 2, got {!r}".format(resp.get("inflight_at_swap")))
            return
        waited = resp.get("waited_s")
        if not isinstance(waited, (int, float)) or waited < quiet_window + 1.5:
            fail("the drain must be measured from the last upstream byte, not "
                 "from the press: waited_s {!r} is inside the {}s quiet window "
                 "while upstream bytes were still arriving".format(
                     waited, quiet_window))
            return
        live.join(20)
        lstatus, _ltype, lraw = live_out.get("result", (0, "", b""))
        if lstatus != 200 or b"message_stop" not in lraw:
            fail("the concurrently-live request must be waited to completion "
                 "(status {}, {} bytes, tail {!r})".format(lstatus, len(lraw), lraw[-160:]))
            return
        if b"config_swap_restart" in lraw:
            fail("the concurrently-live request was evicted by the drain")
            return
        # Drive the straggler's own wake cheaply: the swap is complete, so the
        # marker chunk must be rejected by the epoch check, not forwarded.
        late_wake.set()
        client.join(20)
        cstatus, _ctype, raw = out.get("result", (0, "", b""))
        if cstatus != 200:
            fail("client stream status {}, expected 200".format(cstatus))
            return
        if b"pre-press" not in raw:
            fail("the pre-press chunk must reach the client")
            return
        if b"OLD-ROUTING-MARKER" in raw:
            fail("old-routing bytes were forwarded after the swap")
            return
        if b"config swap in progress" not in raw:
            fail("the straggler must close with the retryable config_swap_restart error")
            return
        st, _ = _send_proxy_request(proxy_port, body=json.dumps(
            {"model": "sonnet", "messages": [{"role": "user", "content": "hi"}]}))
        if st == 200 and len(mock_servers["p2"]["requests"]) == 1:
            pass_("late-exit boundary pinned under the shared clock: switch 200 in "
                  "{:.1f}s, drained True, live stream completed, no old-routing "
                  "bytes after the wake, post-switch routes to p2".format(elapsed))
        else:
            fail("post-switch routing wrong: status {}, p2 calls {}".format(
                st, len(mock_servers["p2"]["requests"])))
    finally:
        late_wake.set()
        cleanup()


def test_switch_abandons_retry_chain():
    """A request sleeping in 429 backoff (PROXY_MAX_DELAY high) abandons at the
    press: it returns 503 config_swap_restart within a sleep slice, well under
    the backoff, the switch returns 200 quickly, a swap_abort event with phase
    'retry_chain' lands, and no 'retry' event is logged for the sleep the chain
    never took (the accounting follows the completed sleep)."""
    print("\n--- Test: Switch Abandons a Retry Chain ---")

    def p1_429(info):
        return (429, "application/json",
                b'{"type":"error","error":{"type":"rate_limit_error","message":"slow down"}}')

    proxy_port, proc, mock_servers, temp_dir, trace_file, cleanup = _swap_proxy(
        responders={"p1": p1_429},
        extra_env={"PROXY_MAX_DELAY": "30", "PROXY_MAX_RETRIES": "5"})
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        out = {}
        client = _stream_request_in_thread(proxy_port, out, body={
            "model": "sonnet", "messages": [{"role": "user", "content": "hi"}]})
        if not _wait_upstream_request(mock_servers, "p1"):
            fail("upstream never received the request")
            return
        time.sleep(0.4)  # the chain is now inside _interruptible_sleep
        t0 = time.time()
        status, data = _admin_post(proxy_port, "/admin/api/switch", _switch_body("p2"))
        switch_elapsed = time.time() - t0
        client.join(15)
        if status != 200:
            fail("switch during a backoff chain returned {}: {}".format(status, data))
            return
        if switch_elapsed > 5:
            fail("switch must return promptly once the chain abandons, took {:.1f}s".format(
                switch_elapsed))
            return
        cstatus, _ctype, raw = out.get("result", (0, "", b""))
        if cstatus != 503:
            fail("abandoned chain must return 503, got {}".format(cstatus))
            return
        if b"config_swap_restart" not in raw:
            fail("abandoned chain body must carry config_swap_restart: {!r}".format(raw[:300]))
            return
        if not _wait_for_trace_events(trace_file, "swap_abort"):
            fail("no swap_abort event for the abandoned chain")
            return
        phases = {e.get("phase") for e in _trace_events_named(trace_file, "swap_abort")}
        if "retry_chain" not in phases:
            fail("swap_abort phases {} must include retry_chain".format(phases))
            return
        retry_events = _trace_events_named(trace_file, "retry")
        if retry_events:
            fail("an abandoned chain must not log a retry it never took: {}".format(retry_events))
            return
        st, _ = _send_proxy_request(proxy_port, body=json.dumps(
            {"model": "sonnet", "messages": [{"role": "user", "content": "hi"}]}))
        if st == 200 and len(mock_servers["p2"]["requests"]) == 1:
            pass_("chain abandoned at the press (503 config_swap_restart in {:.1f}s, "
                  "no phantom retry); re-issue routes to p2".format(switch_elapsed))
        else:
            fail("re-issue routing wrong: status {}, p2 calls {}".format(
                st, len(mock_servers["p2"]["requests"])))
    finally:
        cleanup()


def test_switch_straggler_pre_first_byte_fails_retryably():
    """An upstream that answers long after the quiet-drain swap fails the
    straggler retryably: the switch returns 200 (drained True) on the quiet
    window, and when the upstream finally answers the client gets 503
    config_swap_restart and NEVER the marker body (no old-routing content
    after the swap)."""
    print("\n--- Test: Pre-First-Byte Straggler Fails Retryably ---")
    # Hold past the quiet window (budget + grace = 4 s) so the answer lands
    # after the epoch bump — the pre_first_byte checkpoint.
    hold = 6.0

    def streamer(handler, info):
        time.sleep(hold)
        body = json.dumps({
            "id": "ok", "type": "message", "role": "assistant",
            "model": "claude-sonnet-5",
            "content": [{"type": "text", "text": "MARKER-OLD-ROUTING"}],
            "stop_reason": "end_turn", "stop_sequence": None,
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }).encode()
        handler.send_response(200)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)

    proxy_port, proc, mock_servers, temp_dir, trace_file, cleanup = _swap_proxy(
        streamers={"p1": streamer})
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        out = {}
        client = _stream_request_in_thread(proxy_port, out, body={
            "model": "sonnet", "messages": [{"role": "user", "content": "hi"}]})
        if not _wait_upstream_request(mock_servers, "p1"):
            fail("upstream never received the request")
            return
        time.sleep(0.3)  # the request is blocked in getresponse()
        status, data = _admin_post(proxy_port, "/admin/api/switch", _switch_body("p2"))
        if status != 200:
            fail("switch returned {}: {}".format(status, data))
            return
        resp = json.loads(data)
        if resp.get("drained") is not True:
            fail("nothing is evicted during the drain, so drained must be True, got {!r}".format(
                resp.get("drained")))
            return
        if resp.get("inflight_at_swap") != 1:
            fail("inflight_at_swap must be 1, got {!r}".format(resp.get("inflight_at_swap")))
            return
        client.join(20)
        cstatus, _ctype, raw = out.get("result", (0, "", b""))
        if cstatus != 503:
            fail("straggler must return 503, got {}: {!r}".format(cstatus, raw[:300]))
            return
        if b"config_swap_restart" not in raw:
            fail("straggler body must carry config_swap_restart: {!r}".format(raw[:300]))
            return
        if b"MARKER-OLD-ROUTING" in raw:
            fail("the old-routing marker body reached the client after the swap")
            return
        phases = {e.get("phase") for e in _wait_for_trace_events(trace_file, "swap_abort")}
        if "pre_first_byte" not in phases:
            fail("swap_abort phases {} must include pre_first_byte".format(phases))
            return
        pass_("post-quiet-window answer failed retryably (503 config_swap_restart); "
              "no old-routing body delivered")
    finally:
        cleanup()


def test_swap_status_endpoint():
    """GET /admin/api/swap-status: during a held-stream drain it reports
    swapping True, inflight >= 1, numeric waited_s/silence_s and the configured
    budget_s; when idle it reports swapping False with both nullable fields
    null (asserted as null, not a TypeError-shaped 500 — the per-field guard
    is what buys that).

    Clock discrimination: the fixture keeps a sub-budget upstream cadence alive
    for LONGER than the drain's quiet window (budget + _SWAP_QUIET_GRACE) and
    the status is polled again after that window has elapsed. A drain reading a
    press-stamped local has exited by then — swapping False, and the live
    stream cut with the retryable error; a drain reading the shared activity
    clock (which any upstream byte refreshes) is still waiting, so swapping
    must still be True with silence_s reading fresh. Asserted against the
    plan's semantics, never against the current behaviour."""
    print("\n--- Test: Swap Status Endpoint ---")
    budget = 2
    quiet_window = budget + 2      # budget + _SWAP_QUIET_GRACE
    first_chunk = threading.Event()
    stop_streaming = threading.Event()

    def streamer(handler, info):
        handler.send_response(200)
        handler.send_header("Content-Type", "text/event-stream")
        handler.end_headers()
        handler.wfile.write(_anthropic_sse(_msg_start()))
        handler.wfile.flush()
        first_chunk.set()
        i = 0
        # A sub-budget cadence: every read returns a byte well inside the armed
        # budget, and every byte refreshes the shared activity clock.
        while not stop_streaming.is_set():
            time.sleep(0.4)
            handler.wfile.write(_anthropic_sse(_text_delta("live-{}".format(i))))
            handler.wfile.flush()
            i += 1
        handler.wfile.write(_anthropic_sse(_msg_stop()))
        handler.wfile.flush()

    proxy_port, proc, mock_servers, temp_dir, trace_file, cleanup = _swap_proxy(
        streamers={"p1": streamer})
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        out = {}
        client = _stream_request_in_thread(proxy_port, out)
        if not first_chunk.wait(5):
            fail("upstream never streamed")
            return
        switch_out = {}
        sw = threading.Thread(
            target=lambda: switch_out.update(
                zip(("status", "data"), _admin_post(
                    proxy_port, "/admin/api/switch", _switch_body("p2"),
                    timeout=30))),
            daemon=True)
        sw.start()
        during = _wait_admin_swapping(proxy_port)
        if during is None:
            fail("swap never became visible on /admin/api/swap-status")
            return
        if during.get("inflight", 0) < 1:
            fail("during a held drain inflight must be >= 1, got {!r}".format(during.get("inflight")))
            return
        for field in ("waited_s", "silence_s"):
            val = during.get(field)
            if isinstance(val, (int, float)) and not isinstance(val, bool) and val >= 0:
                pass_("during drain: {} is numeric ({:.2f})".format(field, val))
            else:
                fail("during drain: {} must be numeric, got {!r}".format(field, val))
                return
        if during.get("budget_s") != budget:
            fail("budget_s must read the configured {}s, got {!r}".format(
                budget, during.get("budget_s")))
            return
        # Poll again once a press-stamped drain would have exited, with the
        # cadence still running: the shared clock must read fresh.
        time.sleep(quiet_window + 1.0)
        after = _admin_get_json(proxy_port, "/admin/api/swap-status")[1] or {}
        if after.get("swapping") is not True:
            fail("swapping must still be True once the quiet window has elapsed "
                 "while upstream bytes keep arriving (a press-stamped drain "
                 "reads itself quiet by then); got {!r}".format(after))
            return
        silence = after.get("silence_s")
        if not isinstance(silence, (int, float)) or isinstance(silence, bool) or silence >= budget:
            fail("silence_s must read the shared clock as fresh while bytes "
                 "arrive, got {!r}".format(silence))
            return
        pass_("clock discrimination: swapping still True and silence_s {:.2f}s "
              "after {:.1f}s of continuous upstream bytes".format(
                  silence, quiet_window + 1.0))
        stop_streaming.set()
        sw.join(30)
        if switch_out.get("status") != 200:
            fail("switch returned {}: {}".format(
                switch_out.get("status"), switch_out.get("data")))
            return
        resp = json.loads(switch_out.get("data"))
        if resp.get("drained") is not True or resp.get("inflight_at_swap") != 1:
            fail("a waited-out live stream must report drained True and "
                 "inflight_at_swap 1, got {!r}".format(resp))
            return
        client.join(20)
        cstatus, _ctype, raw = out.get("result", (0, "", b""))
        if cstatus != 200 or b"message_stop" not in raw:
            fail("the live stream must be waited to completion (status {}, "
                 "{} bytes, tail {!r})".format(cstatus, len(raw), raw[-160:]))
            return
        if b"config_swap_restart" in raw:
            fail("a waited-out live stream must never be evicted")
            return
        status, idle = _admin_get_json(proxy_port, "/admin/api/swap-status")
        if status != 200:
            fail("idle swap-status returned {} (a per-field guard failure 500s it)".format(status))
            return
        if idle.get("swapping") is not False:
            fail("idle swapping must be False, got {!r}".format(idle.get("swapping")))
            return
        if idle.get("waited_s") is not None or idle.get("silence_s") is not None:
            fail("idle nullable fields must be null, got waited_s={!r} silence_s={!r}".format(
                idle.get("waited_s"), idle.get("silence_s")))
            return
        pass_("swap-status reports live drain detail, null idle fields, and a "
              "waited-out live stream")
    finally:
        stop_streaming.set()
        cleanup()


def test_second_press_refused_409():
    """Swaps are single-flight: while a drain runs a second press (switch or
    reload) is refused 409 config_swap_in_progress and enters no drain. The
    first press's effect is the only one that lands — asserted through its
    observable trace, since the epoch itself is not exposed: the refused press
    changes no routing (two successive post-swap checks both route to p2) and
    p3 receives nothing.

    The in-flight stream deliberately outlives the drain's quiet window, so
    "the in-flight stream must be unaffected" is asserted against a drain that
    would otherwise have evicted it."""
    print("\n--- Test: Second Press Refused 409 ---")
    first_chunk = threading.Event()

    def streamer(handler, info):
        handler.send_response(200)
        handler.send_header("Content-Type", "text/event-stream")
        handler.end_headers()
        handler.wfile.write(_anthropic_sse(_msg_start()))
        handler.wfile.flush()
        first_chunk.set()
        # ~5 s of live work, deliberately LONGER than the drain's quiet window
        # (budget + _SWAP_QUIET_GRACE = 4 s), so "the in-flight stream must be
        # unaffected" is a real assertion rather than a timing accident: a drain
        # reading a press-stamped clock exits at the quiet window and evicts it.
        for i in range(13):  # 13 x 0.4 s = 5.2 s
            time.sleep(0.4)
            handler.wfile.write(_anthropic_sse(_text_delta("live-{}".format(i))))
            handler.wfile.flush()
        handler.wfile.write(_anthropic_sse(_msg_stop()))
        handler.wfile.flush()

    proxy_port, proc, mock_servers, temp_dir, trace_file, cleanup = _swap_proxy(
        streamers={"p1": streamer}, provider_names=("p1", "p2", "p3"))
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        out = {}
        client = _stream_request_in_thread(proxy_port, out)
        if not first_chunk.wait(5):
            fail("upstream never streamed its first chunk")
            return
        first = {}
        t1 = threading.Thread(
            target=lambda: first.update(
                zip(("status", "data"), _admin_post(
                    proxy_port, "/admin/api/switch", _switch_body("p2")))),
            daemon=True)
        t1.start()
        if _wait_admin_swapping(proxy_port) is None:
            fail("first swap never became visible")
            return
        s2, d2 = _admin_post(proxy_port, "/admin/api/switch", _switch_body("p3"))
        if s2 == 409 and b"config_swap_in_progress" in d2.encode():
            pass_("second switch refused 409 config_swap_in_progress")
        else:
            fail("second switch must be refused 409, got {}: {}".format(s2, d2))
        s3, d3 = _admin_post(proxy_port, "/admin/api/reload", {})
        if s3 == 409 and b"config_swap_in_progress" in d3.encode():
            pass_("concurrent reload refused 409 (shared single-flight)")
        else:
            fail("reload must share the single-flight guard, got {}: {}".format(s3, d3))
        t1.join(20)
        client.join(20)
        if first.get("status") != 200:
            fail("first switch returned {}: {}".format(first.get("status"), first.get("data")))
            return
        cstatus, _ctype, raw = out.get("result", (0, "", b""))
        if cstatus != 200 or b"message_stop" not in raw:
            fail("the in-flight stream must be unaffected (status {}, {} bytes, tail {!r})".format(
                cstatus, len(raw), raw[-160:]))
            return
        checks = []
        for _ in range(2):
            st, _ = _send_proxy_request(proxy_port, body=json.dumps(
                {"model": "sonnet", "messages": [{"role": "user", "content": "hi"}]}))
            checks.append((st, len(mock_servers["p2"]["requests"]),
                           len(mock_servers["p3"]["requests"])))
        if all(st == 200 and p2 >= 1 and p3 == 0 for st, p2, p3 in checks):
            pass_("only the first press landed: two successive checks route to p2, p3 untouched")
        else:
            fail("routing wrong across the two checks: {}".format(checks))
    finally:
        cleanup()


def test_concurrent_presses_single_flight():
    """Single-flight in the CONCURRENT window — the race
    `test_second_press_refused_409` cannot see, because that test issues its
    second press only after the first press has landed.

    A reload is issued first and a switch ~20 ms later, while a silent stream
    holds the in-flight count. The reload handler performs models.json file I/O
    plus the membership/validate gate BEFORE it presses, so any guard that is a
    separate step from the press is passed by BOTH presses inside that gap —
    the reviewer's probe opened it at 3 ms. Only an atomic check-and-set refuses
    one. The reload's catalog is sized so its pre-press work measures ~90 ms
    rather than a coin-flip few ms, while the switch — pressing early, inside
    that gap — holds the single-flight flag for the drain's whole quiet window
    (budget + _SWAP_QUIET_GRACE, i.e. 4 s at the 2 s test budget). The switch
    therefore still holds the flag when the reload reaches its press, which is
    the ordering the filler below drives.

    Asserts (the two branch comments carry the per-outcome detail):
      - the outcome is one 200 + one 409, or — if a scheduling flip put the
        switch's ENTIRE cycle before the reload's gated tier read, so the two
        swaps were sequential rather than concurrent — two sequential 200s;
      - every 409 carries the Anthropic error envelope (type=error,
        error.type=api_error, a non-empty error.code and a request_id) and its
        code is one of the two legitimate refusals: the single-flight
        `config_swap_in_progress`, or `config_reload_stale` (the reload's
        Phase-3 epoch guard refusing a candidate that predates a switch that
        completed in its gate-to-install window);
      - in the one-200 outcome the epoch bumped exactly once. It is not exposed
        on the admin surface, so it is pinned by its two observable
        consequences: exactly one 200 is exactly one bump (the increment lives
        only in the 200 swap body — the 409 and 400 refusals return before
        Phase 3, and the 500 disk-failure path performs no swap and no bump),
        and the survivor's mapping is in force;
      - the surviving press's mapping is the one in force afterwards, checked
        twice over: a leaked second press applies its own (stale) mapping after
        the first — the silent revert the reviewer measured — which moves the
        routing off the survivor's provider. That mapping check is what catches
        the revert in both outcomes.
    """
    print("\n--- Test: Concurrent Presses Are Single-Flight ---")
    quiet_window = 2 + 2      # SETTINGS.swap_silence_timeout + _SWAP_QUIET_GRACE
    # A catalog big enough that the reload handler's load + membership gate
    # reliably outlasts the second press's arrival (measured ~90 ms here against
    # a press gap whose jitter is tens of ms).
    filler = ["m%06d" % i for i in range(400000)]
    tier_models = ["claude-haiku-4-5", "claude-sonnet-5", "claude-opus-5"]
    models = {"p1": tier_models + filler, "p2": list(tier_models)}

    def streamer(handler, info):
        if b"SILENT" not in info.get("body", b""):
            # A route-check probe: answer promptly so EITHER survivor's
            # provider can be probed after the swap.
            body = json.dumps({
                "id": "ok", "type": "message", "role": "assistant",
                "model": "claude-sonnet-5",
                "content": [{"type": "text", "text": "ok"}],
                "stop_reason": "end_turn", "stop_sequence": None,
                "usage": {"input_tokens": 1, "output_tokens": 1},
            }).encode()
            handler.send_response(200)
            handler.send_header("Content-Type", "application/json")
            handler.send_header("Content-Length", str(len(body)))
            handler.end_headers()
            handler.wfile.write(body)
            return
        handler.send_response(200)
        handler.send_header("Content-Type", "text/event-stream")
        handler.end_headers()
        handler.wfile.write(_anthropic_sse(_msg_start()))
        handler.wfile.flush()
        time.sleep(30)  # hold silently: the drain exits on the quiet window

    proxy_port, proc, mock_servers, temp_dir, trace_file, cleanup = _swap_proxy(
        streamers={"p1": streamer, "p2": streamer}, models=models)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        out = {}
        client = _stream_request_in_thread(proxy_port, out, body={
            "model": "sonnet", "stream": True,
            "messages": [{"role": "user", "content": "SILENT"}]})
        if not _wait_upstream_request(mock_servers, "p1"):
            fail("upstream never received the stream request")
            return

        reload_out = {}
        switch_out = {}

        def do_reload():
            try:
                reload_out.update(zip(("status", "data"), _admin_post(
                    proxy_port, "/admin/api/reload", {}, timeout=30)))
            except Exception as e:
                reload_out["error"] = str(e)

        def do_switch():
            try:
                switch_out.update(zip(("status", "data"), _admin_post(
                    proxy_port, "/admin/api/switch", _switch_body("p2"),
                    timeout=30)))
            except Exception as e:
                switch_out["error"] = str(e)

        tr = threading.Thread(target=do_reload, daemon=True)
        tr.start()
        # A head start sized well inside the reload's measured pre-press gap
        # (~90 ms) but comfortably past the inter-thread scheduling jitter, so
        # the guard ORDER is deterministic and the race — not the jitter — is
        # what the assertions exercise.
        time.sleep(0.02)
        ts = threading.Thread(target=do_switch, daemon=True)
        ts.start()
        tr.join(40)
        ts.join(40)

        reload_status = reload_out.get("status")
        switch_status = switch_out.get("status")
        statuses = sorted(c for c in (reload_status, switch_status) if c is not None)
        # Two outcomes are consistent with an atomic single-flight guard:
        #   [200, 409] — the switch pressed inside the reload's pre-press window
        #                and the reload was refused. This is the ordering the
        #                filler below drives.
        #   [200, 200] — a scheduling flip put the switch's ENTIRE cycle before
        #                the reload's gated tier read, so the two swaps were
        #                sequential rather than concurrent and both landed
        #                legitimately. Rejecting this would misattribute a
        #                scheduling change on a correct tree to the
        #                single-flight defect (the re-review's finding 2).
        # Anything else — a 500, a hung press, a missing status — is a real
        # failure.
        if statuses not in ([200, 409], [200, 200]):
            fail("concurrent presses must be one 200 + one 409 (a refusal) or two "
                 "sequential 200s (the switch completed before the reload pressed); "
                 "anything else means a drain failed or two drains ran concurrently "
                 "for one logical change; got reload={} switch={}".format(
                     reload_status, switch_status))
            return
        if 409 in statuses:
            refused = reload_out if reload_status == 409 else switch_out
            # Either 409 code is a correct refusal: the single-flight
            # config_swap_in_progress, or the stale-candidate
            # config_reload_stale the reload's Phase-3 epoch guard emits when a
            # switch completed between its gated tier read and its install
            # (the reload handler's `gated_epoch` capture, then its compare).
            # Asserting the envelope
            # SHAPE rather than one code by name keeps a correct refusal from
            # being misdiagnosed as the single-flight defect.
            try:
                env = json.loads(refused.get("data", ""))
            except Exception:
                env = None
            err = env.get("error") if isinstance(env, dict) else None
            if not isinstance(err, dict) or env.get("type") != "error" \
                    or err.get("type") != "api_error" or not err.get("code") \
                    or not env.get("request_id"):
                fail("the refused press must carry the Anthropic error envelope "
                     "(type=error, error.type=api_error, a non-empty error.code and a "
                     "request_id): {!r}".format(refused.get("data", "")))
                return
            if err["code"] not in ("config_swap_in_progress", "config_reload_stale"):
                fail("the refused press carries 409 code {!r}; expected "
                     "config_swap_in_progress (single-flight) or config_reload_stale "
                     "(stale candidate)".format(err["code"]))
                return
            winner = switch_out if switch_status == 200 else reload_out
            survivor_provider = "p2" if switch_status == 200 else "p1"
            resp = json.loads(winner.get("data", "{}"))
            if resp.get("inflight_at_swap") != 1:
                fail("the in-flight stream must be counted at the press, got {!r}".format(
                    resp.get("inflight_at_swap")))
                return
            if not isinstance(resp.get("waited_s"), (int, float)) or resp["waited_s"] < 3:
                fail("the winning drain must have waited out the quiet window while "
                     "the silent stream held the count, got waited_s {!r}".format(
                         resp.get("waited_s")))
                return
            outcome = "exactly one 200 + one 409 ({})".format(err["code"])
        else:
            # Both swaps landed, sequentially: the switch installed sonnet -> p2,
            # and the reload's candidate — read from _current_config after that
            # install, or the reload's own Phase-3 guard would have refused it
            # config_reload_stale — carries the SAME mapping. The mapping in
            # force must therefore still be p2.
            survivor_provider = "p2"
            outcome = ("two sequential 200s (the switch completed before the reload "
                       "pressed)")

        # The epoch is not exposed; its consequences are. In the one-200 outcome
        # that is one bump plus the survivor's mapping in force; in the two-200
        # outcome it is two bumps — one per landed press, both legitimate because
        # the presses were sequential — and again the surviving mapping in force.
        # Checked twice over: a leaked second press applies its own (stale)
        # mapping after the first, the silent revert the reviewer measured, which
        # shows as routing moving off the survivor's provider.
        p1_before = len(mock_servers["p1"]["requests"])
        p2_before = len(mock_servers["p2"]["requests"])
        for _ in range(2):
            st, _b = _send_proxy_request(proxy_port, body=json.dumps(
                {"model": "sonnet", "messages": [{"role": "user", "content": "hi"}]}))
            if st != 200:
                fail("post-swap route check returned {}".format(st))
                return
            time.sleep(0.1)
        p1_after = len(mock_servers["p1"]["requests"]) - p1_before
        p2_after = len(mock_servers["p2"]["requests"]) - p2_before
        if survivor_provider == "p2":
            ok = (p2_after == 2 and p1_after == 0)
            detail = "the switch's mapping is in force, so both checks must reach p2"
        else:
            ok = (p1_after == 2 and p2_after == 0)
            detail = "the reload survived (tiers unchanged), so both checks must stay on p1"
        if not ok:
            fail("{}; got p1={} p2={} — routing moved off the surviving press's "
                 "mapping (a leaked second press reverting it)".format(
                     detail, p1_after, p2_after))
            return
        # The straggler pieces are parked; cleanup kills the proxy.
        client.join(0.1)
        pass_("concurrent presses: {}; both route checks stayed on {} (mapping "
              "not reverted)".format(outcome, survivor_provider))
    finally:
        cleanup()


def test_reload_does_not_revert_concurrent_switch():
    """The reload's stale-candidate epoch guard (re-review finding
    review-2-reload-stale-candidate), driven DETERMINISTICALLY in-process.

    The guard closes the window between the reload's gated tier read
    (`gated_epoch = forwarder._drain._config_epoch`, captured in the SAME
    `_drain.lock` acquisition that reads the candidate's tiers) and Phase 3's
    compare-and-install (`if forwarder._drain._config_epoch != gated_epoch:`).
    A /admin/api/switch that completes its whole press -> drain -> swap ->
    release cycle inside that window must not have its mapping silently
    reverted by the reload installing its stale candidate.

    That interleaving cannot be driven from outside the process: the window
    between the gate's lock release and the reload's press is a few bytecodes
    wide, and a test that depended on winning that scheduling race would flake
    on a CORRECT tree — the reviewer could not reproduce it in 15 attempts.
    This test therefore drives the guard's PRECONDITION deterministically
    instead: it monkeypatches `forwarder._drain.drain` — the one call the reload
    handler makes between its gate and Phase 3 — to simulate a switch that
    completed inside the window (clearing the flag, installing the switch's
    tiers, bumping the epoch), then invokes the reload handler in-process via
    the `object.__new__(srv.ProxyHandler)` pattern used elsewhere in the suite.
    Phase 3 must refuse 409 `config_reload_stale`, install nothing and bump
    nothing.

    Deleting the guard (or a defaulted `epoch`) fails this test twice over: the
    status becomes 200, and `_current_config` is reverted to the pre-switch
    tiers. The drain singleton's fields the handler reads are saved and
    restored in a `finally` (with the patched method deleted off the instance)
    so the in-process state cannot leak into a later test.
    """
    print("\n--- Test: Reload Does Not Revert a Concurrent Switch ---")
    import claude_retry_proxy.server as srv
    import claude_retry_proxy.forwarder as forwarder
    import claude_retry_proxy.runtime_state as runtime_state

    temp_dir = tempfile.mkdtemp()
    try:
        original_tiers = _switch_body("p1")["tiers"]
        switch_tiers = _switch_body("p2")["tiers"]
        with open(os.path.join(temp_dir, "models.json"), "w", encoding="utf-8") as f:
            json.dump({"models": {
                "p1": ["claude-haiku-4-5", "claude-sonnet-5", "claude-opus-5"],
                "p2": ["claude-sonnet-5"],
            }}, f)
        config_path = os.path.join(temp_dir, "config.json")
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump({"tiers": original_tiers}, f)

        saved_srv = {name: getattr(runtime_state, name) for name in (
            "_config_path", "_current_config", "_vendors")}
        saved_fwd = {name: getattr(forwarder._drain, name) for name in (
            "_config_epoch", "_config_swapping", "_inflight_count",
            "_swap_evictions")}
        try:
            runtime_state._config_path = config_path
            runtime_state._current_config = {"tiers": original_tiers}
            forwarder._drain._config_epoch = 5
            runtime_state._vendors = {
                "p1": {"url": "http://127.0.0.1:1", "key": "k-p1"},
                "p2": {"url": "http://127.0.0.1:2", "key": "k-p2"},
            }
            forwarder._drain._config_swapping = False
            forwarder._drain._inflight_count = 0
            forwarder._drain._swap_evictions = 0

            def concurrent_switch_completes():
                # The interleaving the guard exists for: a switch presses, swaps
                # and releases entirely between the reload's gated tier read and
                # its Phase-3 install. `candidate` still holds `original_tiers`.
                import claude_retry_proxy.forwarder as forwarder
                forwarder._drain._config_swapping = True
                runtime_state._current_config = {"tiers": switch_tiers}
                forwarder._drain._config_epoch = 6
                forwarder._drain._config_swapping = False
                return (True, 0, 0.0)

            forwarder._drain.drain = concurrent_switch_completes

            captured = []
            handler = object.__new__(srv.ProxyHandler)
            handler.path = "/admin/api/reload"
            handler.client_address = ("127.0.0.1", 55555)
            handler.headers = {
                "Content-Length": "0",
                "Origin": "http://127.0.0.1:{}".format(srv.SETTINGS.port),
            }
            handler.rfile = io.BytesIO(b"")
            handler.wfile = io.BytesIO()
            handler._send_response = (
                lambda status, body, headers=None: captured.append((status, body)))
            handler.do_POST()

            if not captured:
                fail("the reload handler sent no response")
                return
            status, body = captured[-1]
            if status != 409:
                fail("installing a candidate that predates a completed switch must "
                     "be refused 409; got {} (body {!r}) — the epoch guard did not "
                     "fire".format(status, body[:200].decode("utf-8", "replace")))
                return
            try:
                parsed = json.loads(body)
            except Exception as e:
                fail("the refusal body is not JSON: {} ({!r})".format(e, body[:200]))
                return
            err = parsed.get("error") if isinstance(parsed, dict) else None
            if not isinstance(err, dict) or err.get("code") != "config_reload_stale":
                fail("expected the stale-candidate refusal error.code "
                     "config_reload_stale, got {!r}".format(parsed))
                return
            if parsed.get("type") != "error" or err.get("type") != "api_error" \
                    or not parsed.get("request_id"):
                fail("the refusal must carry the Anthropic envelope (type=error, "
                     "error.type=api_error, a request_id): {!r}".format(parsed))
                return
            if runtime_state._current_config != {"tiers": switch_tiers}:
                fail("the reload REVERTED the switch's mapping: _current_config is "
                     "{!r}, expected the switch's tiers {!r}".format(
                         runtime_state._current_config, {"tiers": switch_tiers}))
                return
            if forwarder._drain._config_epoch != 6:
                fail("a refused reload must not bump the epoch; got {}".format(
                    forwarder._drain._config_epoch))
                return
            pass_("reload refused 409 config_reload_stale; the switch's mapping "
                  "survived and no epoch bump was taken")
        finally:
            del forwarder._drain.drain
            runtime_state._config_path = saved_srv["_config_path"]
            runtime_state._current_config = saved_srv["_current_config"]
            runtime_state._vendors = saved_srv["_vendors"]
            forwarder._drain._config_epoch = saved_fwd["_config_epoch"]
            forwarder._drain._config_swapping = saved_fwd["_config_swapping"]
            forwarder._drain._inflight_count = saved_fwd["_inflight_count"]
            forwarder._drain._swap_evictions = saved_fwd["_swap_evictions"]
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_request_blocked_at_admission_not_evicted():
    """A request blocked in the drain's completion-event wait while a swap runs
    must NOT be evicted by the swap it waited on: after the release it is
    admitted with the POST-swap epoch and completes against the new provider,
    never config_swap_restart."""
    print("\n--- Test: Admission-Blocked Request Is Not Evicted ---")
    held = threading.Event()

    def streamer(handler, info):
        handler.send_response(200)
        handler.send_header("Content-Type", "text/event-stream")
        handler.end_headers()
        handler.wfile.write(_anthropic_sse(_msg_start(), _text_delta("straggler")))
        handler.wfile.flush()
        held.set()
        time.sleep(30)  # hold the drain open on the quiet path

    proxy_port, proc, mock_servers, temp_dir, trace_file, cleanup = _swap_proxy(
        streamers={"p1": streamer})
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        out = {}
        straggler = _stream_request_in_thread(proxy_port, out)
        if not held.wait(5):
            fail("upstream never streamed")
            return
        switch_out = {}
        sw = threading.Thread(
            target=lambda: switch_out.update(
                zip(("status", "data"), _admin_post(
                    proxy_port, "/admin/api/switch", _switch_body("p2")))),
            daemon=True)
        sw.start()
        if _wait_admin_swapping(proxy_port) is None:
            fail("swap never became visible")
            return
        # Issued while the swap is in progress: this one blocks at admission.
        blocked = {}
        blk = _stream_request_in_thread(proxy_port, blocked, body={
            "model": "sonnet", "messages": [{"role": "user", "content": "hi"}]})
        sw.join(20)
        if switch_out.get("status") != 200:
            fail("switch returned {}: {}".format(
                switch_out.get("status"), switch_out.get("data")))
            return
        blk.join(20)
        bstatus, _btype, braw = blocked.get("result", (0, "", b""))
        if bstatus != 200:
            fail("admission-blocked request must complete 200 after release, got {}: {!r}".format(
                bstatus, braw[:300]))
            return
        if b"config_swap_restart" in braw:
            fail("the request blocked at admission was evicted by the swap it waited on")
            return
        if len(mock_servers["p2"]["requests"]) == 1 and not mock_servers["p1"]["requests"][1:]:
            pass_("admission-blocked request admitted post-swap on the new provider (p2), "
                  "never evicted")
        else:
            fail("routing wrong: p1 calls {}, p2 calls {}".format(
                len(mock_servers["p1"]["requests"]), len(mock_servers["p2"]["requests"])))
        # The straggler is still parked; cleanup kills the proxy.
        straggler.join(0.1)
    finally:
        cleanup()


ALL_TESTS = [
    ("admin-switch-waits-long-live-stream",
     test_switch_succeeds_during_long_live_stream),
    ("admin-switch-evicts-silent-stream", test_switch_evicts_silent_stream),
    ("admin-switch-silent-before-press-late-exit",
     test_switch_silent_before_press_is_late_exit),
    ("admin-switch-abandons-retry-chain", test_switch_abandons_retry_chain),
    ("admin-switch-pre-first-byte-straggler",
     test_switch_straggler_pre_first_byte_fails_retryably),
    ("admin-swap-status-endpoint", test_swap_status_endpoint),
    ("admin-second-press-refused-409", test_second_press_refused_409),
    ("admin-concurrent-presses-single-flight",
     test_concurrent_presses_single_flight),
    ("admin-reload-stale-candidate-guard",
     test_reload_does_not_revert_concurrent_switch),
    ("admin-admission-blocked-not-evicted",
     test_request_blocked_at_admission_not_evicted),
]


if __name__ == "__main__":
    run_cli(ALL_TESTS, "claude-retry-proxy tests: test_admin_swap")
