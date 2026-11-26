"""Chat-mode stream tests across a config swap.

Part of the claude-retry-proxy suite; runnable standalone.
"""

import threading
import time
from _harness import (
    _admin_post,
    _cc,
    _mode_tiers,
    _parse_sse_frames,
    _send_proxy_request_stream,
    _sse_frame_type,
    _sse_stream_chunks,
    _start_mode_proxy,
    _trace_events_named,
    _wait_admin_swapping,
    _wait_for_trace_events,
    _wait_upstream_request,
    fail,
    find_free_port,
    pass_,
    run_cli,
)


# ===========================================================================
# Chat-mode streams across a config swap (plan 2026-10-12-swap-silence-drain)
# ===========================================================================

# The swap tests drive a 2 s silence budget; the 30 s default would make every
# one of them silently run at 30 s. The drain's quiet window is budget + 2 s.
_CHAT_SWAP_BUDGET_ENV = {"PROXY_SWAP_SILENCE_TIMEOUT": "2"}


_CHAT_SWITCH_TO_Q = {"tiers": {
    "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
    "sonnet": {"provider": "q", "model": "claude-sonnet-5"},
    "opus": {"provider": "p", "model": "claude-opus-5"},
}}


def _chat_swap_proxy(p_streamer, extra_env=None):
    """Start a chat-mode two-provider proxy: sonnet -> p, q for the switch.

    `extra_env` merges over the 2 s swap budget — the swap eviction tests pin
    PROXY_READ_TIMEOUT there so the read-boundary eviction is deterministic
    rather than waiting out the 120 s default.

    Returns (proxy_port, trace_file, mock_servers, cleanup), or (None,)*4 on
    failure.
    """
    tiers = _mode_tiers()
    vendors = {
        "p": {"url": "http://127.0.0.1:{}".format(find_free_port()),
              "key": "K", "mode": "chat"},
        "q": {"url": "http://127.0.0.1:{}".format(find_free_port()),
              "key": "K", "mode": "chat"},
    }
    env = dict(_CHAT_SWAP_BUDGET_ENV)
    if extra_env:
        env.update(extra_env)
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(
        tiers, vendors, streamers={"p": p_streamer}, extra_env=env)
    if proc is None:
        return None, None, None, None
    return proxy_port, trace_file, mock_servers, cleanup


def _chat_stream_in_thread(port, out):
    """POST a streaming chat request on a background thread into out['result']."""
    def worker():
        try:
            out["result"] = _send_proxy_request_stream(
                port, {"model": "sonnet", "stream": True,
                       "messages": [{"role": "user", "content": "hi"}]})
        except Exception as e:
            out["result"] = (0, "", str(e).encode())

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    return t


def test_chat_sse_swap_evicts_pre_finish():
    """A chat-mode stream evicted pre-finish (a byte after the press, then
    silence) closes with the retryable config_swap_restart error and emits
    chat_sse_truncated, keeping the trace invariant (exactly one of
    chat_sse_drain / chat_sse_truncated).

    The eviction now lands at the stream's next READ BOUNDARY (the request read
    timeout, pinned to 10 s here) rather than at the retired 30 s armed wake;
    by then the swap itself has usually completed, so the epoch check — not the
    in-progress flag — is what closes it.
    """
    print("\n--- Test: Chat SSE Pre-Finish Swap Eviction ---")
    post_press_byte = threading.Event()

    def streamer(handler, info):
        handler.send_response(200)
        handler.send_header("Content-Type", "text/event-stream")
        handler.end_headers()
        handler.wfile.write(_sse_stream_chunks(
            [_cc({"role": "assistant", "content": "hi"})]))
        handler.wfile.flush()
        # A byte AFTER the press, then silence: the loop's next read then
        # blocks until the request read timeout, with the drain's swapping
        # flag (or the completed swap's epoch) owning the wake.
        post_press_byte.wait(15)
        handler.wfile.write(_sse_stream_chunks([_cc({"content": "more"})]))
        handler.wfile.flush()
        time.sleep(30)  # hold silently

    # The wake is the request read timeout (there is no armed wake any more),
    # so it is pinned to its 10 s floor to keep the test bounded; the swap's
    # quiet window (budget 2 + grace 2) still expiring first is fine — the
    # completed swap's epoch check owns the wake either way.
    proxy_port, trace_file, mock_servers, cleanup = _chat_swap_proxy(
        streamer, extra_env={"PROXY_READ_TIMEOUT": "10"})
    if proxy_port is None:
        fail("Failed to set up test")
        return
    try:
        out = {}
        client = _chat_stream_in_thread(proxy_port, out)
        if not _wait_upstream_request(mock_servers, "p"):
            fail("upstream never received the stream request")
            return
        switch_out = {}
        sw = threading.Thread(
            target=lambda: switch_out.update(zip(
                ("status", "data"),
                _admin_post(proxy_port, "/admin/api/switch", _CHAT_SWITCH_TO_Q))),
            daemon=True)
        sw.start()
        if _wait_admin_swapping(proxy_port) is None:
            fail("swap never became visible on /admin/api/swap-status")
            return
        post_press_byte.set()
        sw.join(20)
        client.join(20)
        if switch_out.get("status") != 200:
            fail("switch returned {}: {}".format(
                switch_out.get("status"), switch_out.get("data")))
            return
        cstatus, _ctype, raw = out.get("result", (0, "", b""))
        if cstatus != 200:
            fail("client stream status {}, expected 200".format(cstatus))
            return
        if b"config swap in progress" not in raw:
            fail("evicted chat stream must end with the retryable error: {!r}".format(raw[-300:]))
            return
        if "error" not in [_sse_frame_type(f) for f in _parse_sse_frames(raw)]:
            fail("evicted chat stream must carry an SSE error frame")
            return
        if b"message_stop" in raw:
            fail("a pre-finish eviction must not synthesize a terminal")
            return
        truncated = _wait_for_trace_events(trace_file, "chat_sse_truncated")
        drains = _trace_events_named(trace_file, "chat_sse_drain")
        if len(truncated) != 1 or drains:
            fail("expected exactly one chat_sse_truncated and no chat_sse_drain, "
                 "got {} / {}".format(len(truncated), len(drains)))
            return
        phases = {e.get("phase") for e in _wait_for_trace_events(trace_file, "swap_abort")}
        if "stream" not in phases:
            fail("swap_abort phases {} must include stream".format(phases))
            return
        pass_("pre-finish eviction: one chat_sse_truncated, retryable error, no terminal")
    finally:
        cleanup()


def test_chat_sse_swap_abort_in_drain_window():
    """An epoch change inside the post-finish drain window closes via the
    api_error path with chat_sse_drain carrying drain_exit 'swap_abort', and
    never synthesizes a terminal — the invariant holds (exactly one
    chat_sse_drain, no chat_sse_truncated).

    The finish frame is written at handler entry, i.e. BEFORE the press, so the
    stream is already in the post-finish drain when the swap runs. The drain
    itself has no timer any more: a SILENT drain is bounded only by the request
    read timeout (120 s here, unpinned), and the per-chunk MAX_DRAIN_SECONDS
    check fires only when chunks keep arriving. What ends this stream is
    therefore the released late frame: the swap's quiet window
    (budget + _SWAP_QUIET_GRACE = 4 s at this suite's 2 s budget) completes the
    swap first, and the frame then hits the drain's post-read epoch check —
    the disposition this test pins, independent of any drain timer."""
    print("\n--- Test: Chat SSE Drain-Window Swap Abort ---")
    late_frame = threading.Event()

    def streamer(handler, info):
        handler.send_response(200)
        handler.send_header("Content-Type", "text/event-stream")
        handler.end_headers()
        handler.wfile.write(_sse_stream_chunks([
            _cc({"role": "assistant", "content": "hi"}),
            _cc({}, finish="stop")]))
        handler.wfile.flush()
        late_frame.wait(20)
        handler.wfile.write(_sse_stream_chunks([
            {"id": "c1", "object": "chat.completion.chunk", "created": 1,
             "model": "gpt-4o", "choices": [],
             "usage": {"prompt_tokens": 3, "completion_tokens": 4}}]))
        handler.wfile.flush()

    proxy_port, trace_file, mock_servers, cleanup = _chat_swap_proxy(streamer)
    if proxy_port is None:
        fail("Failed to set up test")
        return
    try:
        out = {}
        client = _chat_stream_in_thread(proxy_port, out)
        if not _wait_upstream_request(mock_servers, "p"):
            fail("upstream never received the stream request")
            return
        switch_out = {}
        sw = threading.Thread(
            target=lambda: switch_out.update(zip(
                ("status", "data"),
                _admin_post(proxy_port, "/admin/api/switch", _CHAT_SWITCH_TO_Q))),
            daemon=True)
        sw.start()
        if _wait_admin_swapping(proxy_port) is None:
            fail("swap never became visible on /admin/api/swap-status")
            return
        sw.join(20)
        if switch_out.get("status") != 200:
            fail("switch returned {}: {}".format(
                switch_out.get("status"), switch_out.get("data")))
            return
        # The swap is complete (epoch bumped); release the late frame so the
        # chat drain's post-read epoch check fires inside its window.
        late_frame.set()
        client.join(20)
        cstatus, _ctype, raw = out.get("result", (0, "", b""))
        if cstatus != 200:
            fail("client stream status {}, expected 200".format(cstatus))
            return
        drains = _wait_for_trace_events(trace_file, "chat_sse_drain")
        if len(drains) != 1:
            fail("expected exactly one chat_sse_drain, got {}".format(len(drains)))
            return
        if drains[0].get("drain_exit") != "swap_abort":
            fail("drain_exit must be 'swap_abort', got {!r}".format(drains[0].get("drain_exit")))
            return
        if _trace_events_named(trace_file, "chat_sse_truncated"):
            fail("the drain-window close must not emit chat_sse_truncated")
            return
        if b"config swap in progress" not in raw:
            fail("drain-window close must carry the retryable error: {!r}".format(raw[-300:]))
            return
        if b"message_stop" in raw:
            fail("the drain-window swap close must not synthesize a terminal")
            return
        pass_("drain-window epoch change closed with drain_exit 'swap_abort' and no terminal")
    finally:
        cleanup()


def test_chat_sse_eviction_stranded_sentinel_never_flushes():
    """A genuine eviction carrying a stranded `data: [DONE]\\n` in the residual
    buffer never runs the EOF flush: evict_swap returns before the flush, so
    the pre-finish close stays the cut-stream disposition with the retryable
    config_swap_restart error.

    Pins the eviction-never-flushes invariant (doc/trace-log.html): saw_done
    must stay 0 WITH pending_bytes == 13 — the 13-byte sentinel is sitting in
    buf, so saw_done 0 is evidence the flush did not run, not evidence the
    buffer was empty. Either assertion alone could pass vacuously.
    """
    print("\n--- Test: Chat SSE Eviction With Stranded Sentinel Never Flushes ---")
    post_press_byte = threading.Event()

    def streamer(handler, info):
        handler.send_response(200)
        handler.send_header("Content-Type", "text/event-stream")
        handler.end_headers()
        handler.wfile.write(_sse_stream_chunks(
            [_cc({"role": "assistant", "content": "hi"})]))
        handler.wfile.flush()
        # The stranded sentinel arrives AFTER the press, so it lands in buf
        # while the drain's swapping flag is set; the next read then blocks
        # until the request read timeout (pinned to 10 s below) and wakes into
        # the pre-finish eviction arm.
        post_press_byte.wait(15)
        handler.wfile.write(b"data: [DONE]\n")
        handler.wfile.flush()
        time.sleep(30)  # hold silently

    # The eviction wakes at the next read boundary, so the request read timeout
    # is pinned to its 10 s floor: without the pin this waits out the 120 s
    # default and the client join gives up before the eviction lands.
    proxy_port, trace_file, mock_servers, cleanup = _chat_swap_proxy(
        streamer, extra_env={"PROXY_READ_TIMEOUT": "10"})
    if proxy_port is None:
        fail("Failed to set up test")
        return
    try:
        out = {}
        client = _chat_stream_in_thread(proxy_port, out)
        if not _wait_upstream_request(mock_servers, "p"):
            fail("upstream never received the stream request")
            return
        switch_out = {}
        sw = threading.Thread(
            target=lambda: switch_out.update(zip(
                ("status", "data"),
                _admin_post(proxy_port, "/admin/api/switch", _CHAT_SWITCH_TO_Q))),
            daemon=True)
        sw.start()
        if _wait_admin_swapping(proxy_port) is None:
            fail("swap never became visible on /admin/api/swap-status")
            return
        post_press_byte.set()
        sw.join(20)
        client.join(25)
        if switch_out.get("status") != 200:
            fail("switch returned {}: {}".format(
                switch_out.get("status"), switch_out.get("data")))
            return
        cstatus, _ctype, raw = out.get("result", (0, "", b""))
        if cstatus != 200:
            fail("client stream status {}, expected 200".format(cstatus))
            return
        if b"message_stop" in raw or b"message_delta" in raw:
            fail("an eviction must never synthesize a terminal: {!r}".format(raw[-300:]))
            return
        if b"config swap in progress" not in raw:
            fail("evicted chat stream must end with the retryable error: {!r}".format(raw[-300:]))
            return
        if "error" not in [_sse_frame_type(f) for f in _parse_sse_frames(raw)]:
            fail("evicted chat stream must carry an SSE error frame")
            return
        truncated = _wait_for_trace_events(trace_file, "chat_sse_truncated")
        drains = _trace_events_named(trace_file, "chat_sse_drain")
        if len(truncated) != 1 or drains:
            fail("expected exactly one chat_sse_truncated and no chat_sse_drain, "
                 "got {} / {}".format(len(truncated), len(drains)))
            return
        ev = truncated[0]
        # The two assertions are ONE invariant: pending_bytes 13 proves the
        # sentinel sat in buf, so saw_done 0 proves the flush did not run.
        if not (ev.get("saw_done") == 0 and ev.get("pending_bytes") == 13):
            fail("the stranded sentinel must sit unparsed at eviction: saw_done={!r} "
                 "pending_bytes={!r} (expected 0 and 13)".format(
                     ev.get("saw_done"), ev.get("pending_bytes")))
            return
        phases = {e.get("phase") for e in _wait_for_trace_events(trace_file, "swap_abort")}
        if "stream" not in phases:
            fail("swap_abort phases {} must include stream".format(phases))
            return
        pass_("eviction with a stranded sentinel: flush never ran (saw_done 0 / "
              "pending_bytes 13), retryable error, no terminal, swap_abort stream")
    finally:
        cleanup()


def test_chat_sse_post_swap_straggler_dies_retryably():
    """A pre-finish straggler whose upstream closes AFTER a config swap has
    completed dies retryably at the EOF exit's epoch checkpoint — it must not
    deliver an old-routing terminal.

    Both sentinel shapes, because the epoch checkpoint is what makes them
    agree: the stranded form (data: [DONE]\\n without the blank line,
    pending_bytes 13, saw_done 0 — the flush never runs, the eviction
    pre-empts it) and the framed control (data: [DONE]\\n\\n, pending_bytes 0,
    saw_done 1 — handle_frame consumed the sentinel before the swap).
    Reference: ./tmp/probe_stranded_swap_straggler_2026-10-16.py and
    ./tmp/probe_framed_swap_straggler_2026-10-16.py assert the PRE-FIX
    behaviour (terminal synthesised, no swap_abort) and pass while asserting
    the defect; the assertions here are their inverse.
    """
    print("\n--- Test: Chat SSE Post-Swap Straggler Dies Retryably ---")

    def run_shape(label, sentinel, expect_pending, expect_saw_done):
        post_press_byte = threading.Event()

        def streamer(handler, info):
            handler.send_response(200)
            handler.send_header("Content-Type", "text/event-stream")
            handler.end_headers()
            handler.wfile.write(
                _sse_stream_chunks([_cc({"role": "assistant", "content": "hi"})])
                + sentinel)
            handler.wfile.flush()
            # No byte after the press: the reader stays on its original
            # timeout while the swap's silence drain completes around it;
            # the close below is then an EOF on an already-bumped epoch.
            post_press_byte.wait(15)
            time.sleep(8)  # hold silently past budget(2)+grace(2)
            # returning closes the upstream response -> EOF at the proxy

        proxy_port, trace_file, mock_servers, cleanup = _chat_swap_proxy(streamer)
        if proxy_port is None:
            fail("{}: failed to set up test".format(label))
            return False
        try:
            out = {}
            client = _chat_stream_in_thread(proxy_port, out)
            if not _wait_upstream_request(mock_servers, "p"):
                fail("{}: upstream never received the stream request".format(label))
                return False
            switch_out = {}
            sw = threading.Thread(
                target=lambda: switch_out.update(zip(
                    ("status", "data"),
                    _admin_post(proxy_port, "/admin/api/switch", _CHAT_SWITCH_TO_Q))),
                daemon=True)
            sw.start()
            if _wait_admin_swapping(proxy_port) is None:
                fail("{}: swap never became visible on /admin/api/swap-status".format(label))
                return False
            post_press_byte.set()
            sw.join(20)
            client.join(30)
            if switch_out.get("status") != 200:
                fail("{}: switch returned {}: {}".format(
                    label, switch_out.get("status"), switch_out.get("data")))
                return False
            cstatus, _ctype, raw = out.get("result", (0, "", b""))
            if cstatus != 200:
                fail("{}: client stream status {}, expected 200".format(label, cstatus))
                return False
            if b"message_stop" in raw or b"message_delta" in raw:
                fail("{}: a post-swap straggler must not deliver an old-routing "
                     "terminal: {!r}".format(label, raw[-300:]))
                return False
            if b"config swap in progress" not in raw:
                fail("{}: straggler must close with the retryable error: {!r}".format(
                    label, raw[-300:]))
                return False
            if "error" not in [_sse_frame_type(f) for f in _parse_sse_frames(raw)]:
                fail("{}: straggler close must carry an SSE error frame".format(label))
                return False
            truncated = _wait_for_trace_events(trace_file, "chat_sse_truncated")
            drains = _trace_events_named(trace_file, "chat_sse_drain")
            if len(truncated) != 1 or drains:
                fail("{}: expected exactly one chat_sse_truncated and no "
                     "chat_sse_drain, got {} / {}".format(
                         label, len(truncated), len(drains)))
                return False
            ev = truncated[0]
            if not (ev.get("pending_bytes") == expect_pending
                    and ev.get("saw_done") == expect_saw_done):
                fail("{}: truncated event must show the sentinel shape: "
                     "pending_bytes={!r} saw_done={!r} (expected {} and {})".format(
                         label, ev.get("pending_bytes"), ev.get("saw_done"),
                         expect_pending, expect_saw_done))
                return False
            phases = {e.get("phase") for e in _wait_for_trace_events(trace_file, "swap_abort")}
            if "stream" not in phases:
                fail("{}: swap_abort phases {} must include stream".format(label, phases))
                return False
            return True
        finally:
            cleanup()

    ok_stranded = run_shape("stranded", b"data: [DONE]\n", 13, 0)
    ok_framed = run_shape("framed", b"data: [DONE]\n\n", 0, 1)
    if ok_stranded and ok_framed:
        pass_("post-swap stragglers die retryably in both sentinel shapes: "
              "stranded (pending 13 / saw_done 0) and framed (pending 0 / "
              "saw_done 1), retryable error, no terminal, swap_abort stream")


ALL_TESTS = [
    # Config-swap drain (plan 2026-10-12-swap-silence-drain)
    ("chat-sse-swap-evicts-pre-finish", test_chat_sse_swap_evicts_pre_finish),
    ("chat-sse-swap-abort-in-drain-window", test_chat_sse_swap_abort_in_drain_window),
    ("chat-sse-eviction-stranded-sentinel-never-flushes", test_chat_sse_eviction_stranded_sentinel_never_flushes),
    ("chat-sse-post-swap-straggler-dies-retryably", test_chat_sse_post_swap_straggler_dies_retryably),
]


if __name__ == "__main__":
    run_cli(ALL_TESTS, "claude-retry-proxy tests: test_chat_sse_swap")
