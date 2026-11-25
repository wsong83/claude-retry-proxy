"""Chat-mode SSE conversion for the proxy HTTP handler.

Extracted verbatim from `server.py` (plan 2026-11-17-extract-chat-sse) as the
`ChatSSEHandlerMixin` the handler inherits. The module converts an OpenAI
chat-completions SSE stream into Anthropic Messages SSE events and owns the
chat-mode frame/drain bounds. Bodies are byte-identical to their pre-move
source; `_sse_event` stays on the handler in `server.py` and resolves through
the class MRO.
"""

import json
import sys
import time
import uuid

import httpx2

from . import forwarder
from .forwarder import (_DISCONNECT_ERRORS, _error_body, _retry_nudge_arm,
                        _retry_nudge_messages_bytes)
from .nesting import check_payload_nesting, nesting_event
from .settings import SETTINGS
from .sinks import log_trace
from .transforms_chat import _map_chat_finish_reason


SSE_EVENT_DELIMITER = b"\n\n"

# Chat-mode SSE tool-call conversion bounds (mirror the per-frame event buffer).
MAX_CHAT_TOOL_PENDING_BYTES = 64 * 1024
MAX_CHAT_TRACKED_TOOL_INDEXES = 32
MAX_CHAT_OPEN_TOOL_BLOCKS = 32

# Post-finish drain bounds: after a finish_reason chunk the read loop keeps
# reading briefly to capture trailing usage / tool_call frames.
MAX_DRAIN_BYTES = 64 * 1024
MAX_DRAIN_SECONDS = 5


class ChatSSEHandlerMixin:
    """Chat-mode SSE conversion methods for ProxyHandler.

    Mixed into `server.ProxyHandler` ahead of `BaseHTTPRequestHandler`; the
    methods of this class resolve `_sse_event` through the MRO and use the
    handler's `wfile` instance attribute, installed by
    `BaseHTTPRequestHandler.__init__`.
    """

    def _stream_chat_sse_to_anthropic(self, resp, request_id, tier, first_byte_start,
                                      epoch, tools_declared=False, provider=None, key=None,
                                      retry_original_id=None):
        """Transform an OpenAI chat-completions SSE stream into Anthropic Messages SSE.

        Frames are assembled on the \\n\\n delimiter (CRLF-normalized) — never
        split mid-frame. A synthetic message_start opens the stream; the first
        content_block_start is deferred until the first delta's type is known
        (reasoning_content/reasoning deltas open a thinking block at index 0,
        content deltas a text block). Deltas become content_block_delta, and
        terminal events (content_block_stop, message_delta, message_stop) are
        emitted exactly once — after the post-finish drain, or at EOF for a
        stream that ended without a finish_reason but received the [DONE]
        sentinel (protocol-complete: the provider simply never said why it
        stopped). A stream cut before [DONE] closes instead with an SSE error
        event (error.type: api_error) and no message_delta/message_stop, so
        the client knows the response was cut short and can retry rather than
        recording a completed turn. The two dispositions are discriminated by
        the [DONE] sentinel, recorded as `saw_done` on chat_sse_truncated.

        A finish_reason chunk does not end the read: the loop drains trailing
        frames until EOF, [DONE], or the MAX_DRAIN_BYTES / MAX_DRAIN_SECONDS
        bound, then emits the terminal sequence. The per-chunk
        MAX_DRAIN_SECONDS check cuts a CHATTY drain; a SILENT drain is bounded
        by the request read timeout (PROXY_READ_TIMEOUT), which is recorded as
        `drain_exit: "read_timeout"` so the residual is measurable. The drain
        captures the usage chunk and tool_calls (each tool call opening its own
        content block); content and reasoning deltas arriving after the finish
        signal are dropped by policy and counted. [DONE] ends the drain and is
        otherwise skipped, as are non-data frames.

        A frame larger than MAX_EVENT_BUFFER (2 MB) is dispositioned by phase:
        before the finish signal the stream is terminated with a retryable
        `upstream_frame_oversize` error and no terminal sequence (the turn was
        never terminal-signaled); inside the drain window the frame is dropped,
        counted in `frame_dropped`, and the drain continues, because failing a
        turn that already has its terminal signal would force a full client
        re-run for data the client never needed.

        OpenAI delta.tool_calls are converted into Anthropic tool_use content
        blocks: per-upstream-index state buffers argument fragments until valid
        id+name metadata exists, and all Anthropic block indices come from the
        shared monotonic allocator (incremented only on content_block_start,
        never on close, so indices stay contiguous). A normal "tool_calls"
        finish closes open tool blocks in ascending index order and claims
        stop_reason "tool_use" iff a tool_use block was emitted (whatever its
        arguments); the malformed/dropped variants are still counted and
        reported via one bounded metadata-only trace event per stream.
        """
        MAX_EVENT_BUFFER = 2 * 1024 * 1024
        buf = bytearray()
        usage = {}
        chat_id = None
        message_started = False
        saw_done = False
        text_emitted = False
        text_tail = ""
        first_frame = True
        tool_calls_seen = False
        emitted_tool_use = False
        bytes_streamed = 0
        first_byte_ms = None
        block_index = 0
        current_block_type = None
        current_block_index = None
        open_blocks = []
        tool_states = {}
        tools_started = 0
        malformed_tool_count = 0
        overflow_tool_count = 0
        dropped_fragment_count = 0
        unparseable_arg_count = 0
        scalar_after_tools_dropped = 0
        frame_dropped = 0
        degradation_logged = False
        finish_reason_seen = None
        drain_bytes = 0
        drain_exit = None
        drain_ended_at = None
        frames_seen = 0
        late_frames = 0
        first_late_ms = None
        last_late_ms = None
        late_tool_call_ms = None
        _off = None
        drain_done = False
        drain_cut = False
        finish_seen_at = None
        post_finish_suppressed = 0

        def write(payload):
            nonlocal bytes_streamed, first_byte_ms
            data = self._sse_event(payload, request_id)
            self.wfile.write(data)
            self.wfile.flush()
            bytes_streamed += len(data)
            if first_byte_ms is None:
                first_byte_ms = (time.time() - first_byte_start) * 1000

        def start_message():
            nonlocal message_started
            if message_started:
                return
            mid = ("msg_" + chat_id) if chat_id else ("msg_" + str(uuid.uuid4()))
            write({
                "type": "message_start",
                "message": {
                    "id": mid,
                    "type": "message",
                    "role": "assistant",
                    "content": [],
                    "model": tier,
                    "stop_reason": None,
                    "stop_sequence": None,
                    "usage": {"input_tokens": 0, "output_tokens": 0},
                },
            })
            message_started = True

        def alloc_index():
            nonlocal block_index
            idx = block_index
            block_index += 1
            return idx

        def close_scalar_block():
            nonlocal current_block_type, current_block_index
            if current_block_type is not None:
                write({"type": "content_block_stop", "index": open_blocks[-1]})
                open_blocks.pop()
                current_block_type = None
                current_block_index = None

        def open_text_block():
            nonlocal current_block_type, current_block_index
            if current_block_type == "text":
                return
            close_scalar_block()
            idx = alloc_index()
            write({
                "type": "content_block_start",
                "index": idx,
                "content_block": {"type": "text", "text": ""},
            })
            open_blocks.append(idx)
            current_block_type = "text"
            current_block_index = idx

        def open_thinking_block():
            nonlocal current_block_type, current_block_index
            if current_block_type == "thinking":
                return
            close_scalar_block()
            idx = alloc_index()
            write({
                "type": "content_block_start",
                "index": idx,
                "content_block": {"type": "thinking", "thinking": "",
                                  "signature": ""},
            })
            open_blocks.append(idx)
            current_block_type = "thinking"
            current_block_index = idx

        def new_tool_state():
            return {
                "id": None,
                "name": None,
                "index": None,
                "started": False,
                "closed": False,
                "dropped": False,
                "pending": [],
                "pending_bytes": 0,
                "arg_parts": [],
            }

        def start_tool_block(state):
            nonlocal tools_started, emitted_tool_use
            if tools_started >= MAX_CHAT_OPEN_TOOL_BLOCKS:
                return False
            close_scalar_block()
            idx = alloc_index()
            write({
                "type": "content_block_start",
                "index": idx,
                "content_block": {"type": "tool_use",
                                  "id": state["id"],
                                  "name": state["name"],
                                  "input": {}},
            })
            state["index"] = idx
            state["started"] = True
            tools_started += 1
            emitted_tool_use = True
            for frag in state["pending"]:
                write({"type": "content_block_delta", "index": idx,
                       "delta": {"type": "input_json_delta",
                                 "partial_json": frag}})
                state["arg_parts"].append(frag)
            state["pending"] = []
            state["pending_bytes"] = 0
            return True

        def close_open_tool_blocks(validate):
            nonlocal unparseable_arg_count
            candidates = [st for st in tool_states.values()
                          if st["started"] and not st["closed"]]
            for st in sorted(candidates, key=lambda s: s["index"]):
                write({"type": "content_block_stop", "index": st["index"]})
                st["closed"] = True
                if validate and not st["dropped"]:
                    # The arguments ride inside a JSON string, so no outer
                    # body scan sees their depth: bound them here.
                    _nesting = check_payload_nesting("".join(st["arg_parts"]))
                    if _nesting is not None:
                        log_trace(nesting_event("tool_args", _nesting,
                                                request_id=request_id, tier=tier))
                        unparseable_arg_count += 1
                        continue
                    try:
                        parsed = json.loads("".join(st["arg_parts"]))
                    except Exception:  # total per compat._compat_guarded_parse (RecursionError is not a ValueError)
                        # RecursionError counts as unparseable: the deep
                        # content rides inside a JSON string, so the frame
                        # itself parses even when these arguments do not.
                        unparseable_arg_count += 1
                        continue
                    if not isinstance(parsed, dict):
                        unparseable_arg_count += 1
                        continue

        def log_tool_degradation_summary():
            nonlocal degradation_logged
            if degradation_logged:
                return
            degradation_logged = True
            log_trace({
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "event": "chat_sse_tool_degradation",
                "request_id": request_id,
                "malformed_tool_count": malformed_tool_count,
                "overflow_tool_count": overflow_tool_count,
                "dropped_fragment_count": dropped_fragment_count,
                "unparseable_arg_count": unparseable_arg_count,
                "scalar_after_tools_dropped": scalar_after_tools_dropped,
                # Drain-window oversize-frame drops only (a pre-finish trip
                # errors the stream out instead of dropping).
                "frame_dropped": frame_dropped,
            })

        def process_tool_calls(tool_calls):
            nonlocal malformed_tool_count, overflow_tool_count, dropped_fragment_count
            if not isinstance(tool_calls, list):
                malformed_tool_count += 1
                return
            for tc in tool_calls:
                if not isinstance(tc, dict):
                    malformed_tool_count += 1
                    continue
                index = tc.get("index")
                if not isinstance(index, int) or isinstance(index, bool):
                    # Missing index: a non-empty argument fragment cannot be
                    # associated with any tool — counted as a dropped fragment so
                    # the stream never claims tool_use; other entries are malformed.
                    fn0 = tc.get("function")
                    args0 = fn0.get("arguments") if isinstance(fn0, dict) else None
                    if isinstance(args0, str) and args0:
                        dropped_fragment_count += 1
                    else:
                        malformed_tool_count += 1
                    continue
                fn = tc.get("function")
                if fn is not None and not isinstance(fn, dict):
                    malformed_tool_count += 1
                    continue
                fn = fn if isinstance(fn, dict) else {}
                state = tool_states.get(index)
                if state is None:
                    if len(tool_states) >= MAX_CHAT_TRACKED_TOOL_INDEXES:
                        overflow_tool_count += 1
                        continue
                    state = new_tool_state()
                    tool_states[index] = state
                if state["dropped"]:
                    continue
                id_ = tc.get("id")
                name_ = fn.get("name")
                if isinstance(id_, str) and id_:
                    if state["id"] is not None and state["id"] != id_:
                        malformed_tool_count += 1
                        state["dropped"] = True
                        state["pending"] = []
                        state["pending_bytes"] = 0
                        continue
                    state["id"] = id_
                if isinstance(name_, str) and name_:
                    if state["name"] is not None and state["name"] != name_:
                        malformed_tool_count += 1
                        state["dropped"] = True
                        state["pending"] = []
                        state["pending_bytes"] = 0
                        continue
                    state["name"] = name_
                args = fn.get("arguments")
                if args is not None and not isinstance(args, str):
                    malformed_tool_count += 1
                    state["dropped"] = True
                    state["pending"] = []
                    state["pending_bytes"] = 0
                    continue
                if not state["started"] and state["id"] and state["name"] \
                        and not state["dropped"]:
                    if not start_tool_block(state):
                        overflow_tool_count += 1
                        state["dropped"] = True
                        state["pending"] = []
                        state["pending_bytes"] = 0
                        continue
                if isinstance(args, str) and args:
                    if state["started"]:
                        state["arg_parts"].append(args)
                        write({
                            "type": "content_block_delta",
                            "index": state["index"],
                            "delta": {"type": "input_json_delta",
                                      "partial_json": args},
                        })
                    else:
                        if state["pending_bytes"] + len(args.encode("utf-8")) \
                                > MAX_CHAT_TOOL_PENDING_BYTES:
                            malformed_tool_count += 1
                            state["dropped"] = True
                            state["pending"] = []
                            state["pending_bytes"] = 0
                            continue
                        state["pending"].append(args)
                        state["pending_bytes"] += len(args.encode("utf-8"))

        def close_all_blocks():
            """Close every open content block — scalar and tool — exactly once."""
            while open_blocks:
                idx = open_blocks.pop()
                write({"type": "content_block_stop", "index": idx})
            close_open_tool_blocks(validate=False)

        def log_degradation_if_needed(force_log=False):
            """Finalize tool bookkeeping, then emit the coalesced degradation
            summary when any counter is set.

            The unstarted-tool pre-pass lives here rather than in terminal() so
            every terminal path — including the cut-stream error path, which no
            longer calls terminal() — finalizes identically.
            """
            nonlocal malformed_tool_count
            for st in tool_states.values():
                if not st["started"] and not st["dropped"]:
                    malformed_tool_count += 1
                    st["dropped"] = True
            if force_log or malformed_tool_count or overflow_tool_count \
                    or dropped_fragment_count or unparseable_arg_count \
                    or scalar_after_tools_dropped or frame_dropped:
                log_tool_degradation_summary()

        def terminal(stop_reason, force_log=False):
            close_all_blocks()
            delta_usage = {"input_tokens": 0, "output_tokens": 0}
            # usage is stored unvalidated from the upstream frame, so the
            # copy must type-check: only ints enter the payload, and anything
            # else — bools included, despite isinstance(True, int) — keeps
            # the 0 default. The rule dates from a nested structure deep
            # enough to parse but not to re-encode raising RecursionError on
            # the message_delta re-encode, which escaped as a silent clean EOF
            # with no terminal events; check_payload_nesting now bounds what
            # json.loads is ever shown, so that depth is unreachable, but the
            # type rule still guards against malformed upstream usage.
            pt = usage.get("prompt_tokens")
            if isinstance(pt, int) and not isinstance(pt, bool):
                delta_usage["input_tokens"] = pt
            ct = usage.get("completion_tokens")
            if isinstance(ct, int) and not isinstance(ct, bool):
                delta_usage["output_tokens"] = ct
            write({
                "type": "message_delta",
                "delta": {"stop_reason": stop_reason, "stop_sequence": None},
                "usage": delta_usage,
            })
            write({"type": "message_stop"})
            log_degradation_if_needed(force_log)

        def log_drain():
            """Emit the per-stream drain event.

            Extracted so every disposition that reaches it — the normal
            terminal path and the unfinished-turn error path — logs it
            exactly once, from a single literal.
            """
            _fr = finish_reason_seen if isinstance(finish_reason_seen, str) else "<non-string>"
            log_trace({
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "event": "chat_sse_drain",
                "request_id": request_id,
                "finish_reason": _fr[:64],
                "drain_exit": drain_exit,
                "drain_bytes": drain_bytes,
                "drain_ms": int((drain_ended_at - finish_seen_at) * 1000) if drain_ended_at else 0,
                "tool_calls_seen": 1 if tool_calls_seen else 0,
                "emitted_tool_use": 1 if emitted_tool_use else 0,
                "tools_declared": 1 if tools_declared else 0,
                "late_frames": late_frames,
                "first_late_ms": int(first_late_ms) if first_late_ms is not None else None,
                "last_late_ms": int(last_late_ms) if last_late_ms is not None else None,
                "late_tool_call_ms": int(late_tool_call_ms) if late_tool_call_ms is not None else None,
            })

        def log_post_finish_suppressed():
            """Emit the post-finish suppression count when any delta was
            dropped — guarded and extracted for the same single-literal,
            exactly-once discipline as log_drain()."""
            if post_finish_suppressed:
                log_trace({
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "event": "chat_sse_post_finish_suppressed",
                    "request_id": request_id,
                    "count": post_finish_suppressed,
                })

        def evict_swap():
            """Close a chat stream evicted by a config swap.

            Pre-finish: the ungated cut-stream close — close the open blocks,
            then the retryable api_error, and no synthesized terminal — with
            chat_sse_truncated emitted exactly once, keeping the trace
            invariant (every 200 stream ends with exactly one of
            chat_sse_drain / chat_sse_truncated).
            In the drain window: the same close with drain_exit set to
            "swap_abort", emitted through the drain's own event.
            """
            nonlocal drain_exit, drain_ended_at
            forwarder._drain.note_eviction("stream", request_id, tier=tier, provider=provider)
            if not message_started:
                start_message()
            if finish_reason_seen is not None:
                drain_exit = "swap_abort"
                drain_ended_at = time.time()
                close_all_blocks()
                log_degradation_if_needed()
                log_drain()
                log_post_finish_suppressed()
            else:
                log_trace({
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "event": "chat_sse_truncated",
                    "request_id": request_id,
                    "pending_bytes": len(buf),
                    "saw_done": 1 if saw_done else 0,
                })
                close_all_blocks()
                log_degradation_if_needed()
            write({
                "type": "error",
                "error": {"type": "api_error",
                          "message": "config swap in progress: this request was "
                                     "restarted; the client should retry"},
            })
            return first_byte_ms

        def sentinel_of(text):
            """The frame payload as handle_frame reads it — every `data:` line,
            joined and stripped — or None when the frame carries none at all."""
            data_lines = [ln[5:].strip() for ln in text.splitlines()
                          if ln.startswith("data:")]
            if not data_lines:
                return None
            return "\n".join(data_lines).strip()

        def handle_frame(frame):
            nonlocal chat_id, usage, first_frame, tool_calls_seen, scalar_after_tools_dropped, malformed_tool_count
            nonlocal finish_reason_seen, post_finish_suppressed
            nonlocal text_emitted, text_tail
            text = frame.decode("utf-8", errors="replace")
            raw = sentinel_of(text)
            if raw is None:
                return None  # comment/event-only frame — skip silently
            if raw == "[DONE]":
                return "done"
            _nesting = check_payload_nesting(raw)
            if _nesting is not None:
                # Same skip path the malformed-frame guard takes, but this is
                # not a malformed frame: no chat_sse_malformed_json here.
                log_trace(nesting_event("chat_frame", _nesting,
                                        request_id=request_id, tier=tier))
                return None
            try:
                chunk = json.loads(raw)
            except Exception:  # total per compat._compat_guarded_parse (RecursionError is not a ValueError)
                log_trace({
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "event": "chat_sse_malformed_json",
                    "request_id": request_id,
                })
                return None
            if not isinstance(chunk, dict):
                return None
            u = chunk.get("usage")
            if isinstance(u, dict):
                usage = u
            choices = chunk.get("choices") or []
            if not isinstance(choices, list) or not choices:
                return None
            choice = choices[0] or {}
            if not isinstance(choice, dict):
                return None
            delta = choice.get("delta") or {}
            if first_frame:
                first_frame = False
                cid = chunk.get("id")
                if isinstance(cid, str) and cid:
                    chat_id = cid
                start_message()
            if finish_reason_seen is not None:
                # Drain mode: only tool_calls, usage and a revised
                # finish_reason are still meaningful. Content / reasoning
                # deltas arriving after the finish signal are dropped by
                # policy, not by protocol — terminal() runs after the drain,
                # so nothing is closed yet. Tool calls arrive as their own block.
                # A revision is accepted only for a truthy reason: this path
                # exists to honour a provider correcting itself ("stop" to
                # "tool_calls"), and an empty string is the absence of an
                # answer, not a correction. The `is not None` form would let a
                # trailing "" overwrite a resolved reason; null on every
                # non-final chunk is already excluded by this same guard.
                revised = choice.get("finish_reason")
                if revised:
                    finish_reason_seen = revised
                if isinstance(delta, dict):
                    if delta.get("tool_calls"):
                        tool_calls_seen = True
                        process_tool_calls(delta["tool_calls"])
                    # Suppress content and reasoning deltas
                    if (isinstance(delta.get("content"), str) and delta.get("content")) or \
                            (isinstance(delta.get("reasoning_content"), str) and delta.get("reasoning_content")) or \
                            (isinstance(delta.get("reasoning"), str) and delta.get("reasoning")):
                        post_finish_suppressed += 1
                return None
            if isinstance(delta, dict):
                if delta.get("tool_calls"):
                    tool_calls_seen = True
                reasoning = delta.get("reasoning_content")
                if not (isinstance(reasoning, str) and reasoning):
                    reasoning = delta.get("reasoning")
                if isinstance(reasoning, str) and reasoning:
                    if emitted_tool_use:
                        scalar_after_tools_dropped += 1
                    else:
                        if current_block_type != "thinking":
                            open_thinking_block()
                        write({
                            "type": "content_block_delta",
                            "index": current_block_index,
                            "delta": {"type": "thinking_delta", "thinking": reasoning},
                        })
                content = delta.get("content")
                if isinstance(content, str) and content:
                    if emitted_tool_use:
                        scalar_after_tools_dropped += 1
                    else:
                        if current_block_type != "text":
                            open_text_block()
                        write({
                            "type": "content_block_delta",
                            "index": current_block_index,
                            "delta": {"type": "text_delta", "text": content},
                        })
                        text_emitted = True
                        text_tail = (text_tail + content)[-200:]
                tool_calls = delta.get("tool_calls")
                if tool_calls is not None:
                    process_tool_calls(tool_calls)
            elif delta:
                # Non-dict delta shape (e.g. a string or list): cannot be a
                # valid tool-call frame — the frame is skipped and counted in
                # the degradation diagnostics rather than raising mid-stream.
                malformed_tool_count += 1
            finish_reason = choice.get("finish_reason")
            if finish_reason is not None:
                return ("finish", finish_reason)
            return None

        # ONE raw iterator serves the pre-finish scan and the post-finish
        # drain: an httpx2 response stream is single-consumption (a second
        # iter_raw raises StreamConsumed). The read bound is the client's
        # PROXY_READ_TIMEOUT, applied per read, so both a pre-finish stall and
        # a silent drain end here instead of holding the worker thread.
        chunks = resp.iter_raw()
        try:
            while True:
                try:
                    chunk = next(chunks)
                except StopIteration:
                    chunk = b""
                except httpx2.ReadTimeout:
                    if finish_reason_seen is not None:
                        # The drain's own bound: a silent provider cannot hold
                        # the worker past the read timeout, and the exit is
                        # recorded so the residual is measurable. A completed
                        # swap still owns this wake: close with the retryable
                        # error instead of synthesizing a terminal on old
                        # routing.
                        if forwarder._drain.epoch_changed(epoch):
                            return evict_swap()
                        drain_exit = "read_timeout"
                        break
                    # Pre-finish: a read timeout is terminal, so the only
                    # question is how to close. A swap owns this wake — evict;
                    # otherwise the stall cuts the stream.
                    if forwarder._drain.chain_abort(epoch):
                        return evict_swap()
                    break
                except (httpx2.RequestError, httpx2.StreamError, OSError):
                    # A completed swap owns this exit too: dying retryably beats
                    # delivering an old-routing result the client would trust.
                    if forwarder._drain.epoch_changed(epoch):
                        return evict_swap()
                    drain_exit = "read_error"
                    break
                if not chunk:
                    if forwarder._drain.epoch_changed(epoch):
                        return evict_swap()
                    drain_exit = "eof"
                    break
                forwarder._drain.touch()
                if forwarder._drain.epoch_changed(epoch):
                    # A completed swap: no old-routing bytes reach the client.
                    # In the drain window the epoch rule applies too — close
                    # instead of synthesizing a terminal.
                    return evict_swap()
                if finish_reason_seen is not None:
                    remaining = MAX_DRAIN_SECONDS - (time.time() - finish_seen_at)
                    if remaining <= 0:
                        drain_exit = "time_budget"
                        break
                    _off = (time.time() - finish_seen_at) * 1000
                    _frames_before = frames_seen
                    _tools_before = tool_calls_seen
                if first_byte_ms is None:
                    first_byte_ms = (time.time() - first_byte_start) * 1000
                chunk = chunk.replace(b"\r\n", b"\n")
                buf.extend(chunk)
                while True:
                    idx = buf.find(SSE_EVENT_DELIMITER)
                    if idx < 0:
                        break
                    frame = bytes(buf[:idx])
                    del buf[:idx + 2]
                    result = handle_frame(frame)
                    if result != "done":
                        # The [DONE] sentinel is protocol bookkeeping, not a
                        # frame that "followed the finish signal": counting
                        # it would make the most common coalesced shape
                        # (finish + [DONE], no trailing usage/tool frame)
                        # report a spurious late frame. drain_bytes already
                        # excludes it (the done branch breaks before
                        # accumulation), so the frame and byte accounts
                        # stay symmetric.
                        frames_seen += 1
                    if result == "done":
                        if finish_reason_seen is not None:
                            drain_done = True
                            drain_exit = "done"
                            break
                        saw_done = True
                        continue
                    if isinstance(result, tuple) and result[0] == "finish":
                        finish_reason_seen = result[1]
                        finish_seen_at = time.time()
                        # Frames trailing the finish inside this same coalesced
                        # chunk are late frames with a ~0 offset: capture now,
                        # or the post-loop accounting below never sees them —
                        # the chunk-top capture ran before the finish was
                        # discovered.
                        _off = 0.0
                        _frames_before = frames_seen
                        _tools_before = tool_calls_seen
                        continue  # enter drain mode
                    if finish_reason_seen is not None:
                        # Drain accounting is per FRAME, not per chunk: frames
                        # following finish_reason inside the same coalesced
                        # iter_raw chunk must count against both bounds, or a
                        # large post-finish tail runs to EOF unmeasured.
                        drain_bytes += len(frame) + len(SSE_EVENT_DELIMITER)
                        if drain_bytes > MAX_DRAIN_BYTES:
                            drain_exit = "byte_budget"
                            drain_cut = True
                            break
                        if MAX_DRAIN_SECONDS - (time.time() - finish_seen_at) <= 0:
                            drain_exit = "time_budget"
                            drain_cut = True
                            break
                # Late-frame offsets: how far past finish_reason this chunk's
                # frames arrived — the evidence for whether the 5 s drain
                # budget is generous or binding.
                if _off is not None:
                    if frames_seen > _frames_before:
                        if first_late_ms is None:
                            first_late_ms = _off
                        last_late_ms = _off
                        late_frames += 1
                    if tool_calls_seen and not _tools_before:
                        late_tool_call_ms = _off
                if drain_done or drain_cut:
                    break
                # Memory guard for a frame with no delimiter. The disposition
                # depends on the phase: PRE-finish the turn has not been
                # terminal-signaled yet, so an oversize frame is a loud,
                # retryable error (the cut-stream close shape: blocks closed,
                # degradation finalized, one error frame, and NO
                # message_delta/message_stop). In the DRAIN window the turn is
                # already terminal-signaled — failing it would force a full
                # client re-run for data the client never needed — so the frame
                # is dropped and counted, and the drain continues.
                if len(buf) > MAX_EVENT_BUFFER:
                    oversize_bytes = len(buf)
                    buf.clear()
                    log_trace({
                        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        "event": "chat_sse_frame_oversize",
                        "request_id": request_id,
                        "bytes": oversize_bytes,
                    })
                    if finish_reason_seen is None:
                        # The invariant event: every 200 chat stream ends with
                        # exactly one of chat_sse_drain / chat_sse_truncated.
                        log_trace({
                            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                            "event": "chat_sse_truncated",
                            "request_id": request_id,
                            "pending_bytes": 0,
                            "saw_done": 1 if saw_done else 0,
                        })
                        if not message_started:
                            start_message()
                        close_all_blocks()
                        log_degradation_if_needed()
                        self.wfile.write(b"event: error\ndata: " + _error_body(
                            "api_error", "upstream_frame_oversize",
                            "upstream sent an SSE frame larger than 2 MB; "
                            "stream terminated",
                            request_id) + b"\n\n")
                        self.wfile.flush()
                        return first_byte_ms
                    frame_dropped += 1
                if bytes_streamed > SETTINGS.max_response_size:
                    drain_exit = "response_cap"
                    self._log_response_cap_exceeded(request_id, bytes_streamed)
                    break
        except _DISCONNECT_ERRORS:
            raise
        drain_ended_at = time.time()
        # finish_reason was seen: the drain above ran to EOF, [DONE], or a
        # bound. Emit the terminal sequence now, so trailing usage and tool_call
        # frames captured during the drain are accounted for.
        if finish_reason_seen is not None:
            if not message_started:
                start_message()
            # The detector acts when PROXY_CHAT_RETRY_NUDGE is non-empty: an
            # unarmed stalled turn is closed with the retryable api_error (the
            # marker arm gates the error), while an armed one — the recovery
            # request of an already-errored turn — passes through to the normal
            # terminal synthesis below. With the value empty the detector is a
            # pure measurement: every fired turn passes through, unchanged.
            # `not tool_calls_seen` keeps proxy-side degradation (a tool call
            # seen on the wire but never started as a block) from counting as
            # a model omission.
            if (tools_declared and not emitted_tool_use
                    and not tool_calls_seen
                    and finish_reason_seen == "stop"
                    and text_emitted and text_tail.rstrip().endswith(":")):
                messages_bytes = _retry_nudge_messages_bytes(request_id)
                log_trace({
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "event": "chat_sse_unfinished_turn",
                    "request_id": request_id,
                    "tier": tier,
                    "provider": provider,
                    "key": key,
                    "finish_reason": finish_reason_seen,
                    "tool_calls_seen": 1 if tool_calls_seen else 0,
                    "emitted_tool_use": 1 if emitted_tool_use else 0,
                    "tools_declared": 1 if tools_declared else 0,
                    "text_tail_len": len(text_tail),
                    "messages_bytes": messages_bytes,
                    "rule": "colon_after_prose",
                })
                if (retry_original_id is None
                        and SETTINGS.chat_retry_nudge
                        and _retry_nudge_arm(request_id)):
                    # Arm-gated error path: same wire shape and write ordering
                    # as the cut path below — trace writes first, then the
                    # retryable api_error, and no terminal sequence follows.
                    # The arm must succeed before the error is written: a turn
                    # whose marker could never be stored (a malformed messages
                    # array, or one already armed earlier in the request's
                    # lifecycle) must pass through, never error, or every stall
                    # on that conversation becomes a repeated-error loop.
                    log_drain()
                    log_post_finish_suppressed()
                    close_all_blocks()
                    log_degradation_if_needed()
                    write({
                        "type": "error",
                        "error": {
                            "type": "api_error",
                            "message": "upstream ended the turn without a tool call after tools were declared",
                        },
                    })
                    return first_byte_ms
                if retry_original_id is not None:
                    log_trace({
                        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        "event": "chat_retry_passthrough",
                        "request_id": request_id,
                        "original_request_id": retry_original_id,
                        "tier": tier,
                        "provider": provider,
                        "key": key,
                    })
            if finish_reason_seen == "tool_calls":
                # Diagnostic only: validate still counts unparseable arguments for
                # the coalesced chat_sse_tool_degradation event, but the counts no
                # longer gate the stop reason (Resolved Decision D4).
                close_open_tool_blocks(validate=True)
                sr = "tool_use" if emitted_tool_use else None
                terminal(sr)
            elif emitted_tool_use:
                # Diagnostic validation runs here too: the degradation
                # counter must not depend on which finish disposition
                # closed the stream.
                close_open_tool_blocks(validate=True)
                mapped = _map_chat_finish_reason(finish_reason_seen)
                # Provider signalled finish before the tool_call frames: claim
                # tool_use rather than letting the client stop for user input.
                sr = "tool_use" if mapped == "end_turn" else mapped
                terminal(sr, force_log=True)
            else:
                terminal(_map_chat_finish_reason(finish_reason_seen))
            log_drain()
            log_post_finish_suppressed()
            return first_byte_ms
        # EOF reached without a finish_reason chunk. Two dispositions: with
        # [DONE] the stream is protocol-complete and just never said why it
        # stopped; without it the connection was cut mid-response.
        # A provider may write `data: [DONE]` and close without the blank
        # line that delimits a frame, stranding the sentinel in the buffer.
        # At EOF the sentinel is unambiguous, so honour it rather than
        # treating a protocol-complete stream as one that was cut.
        if not saw_done:
            if sentinel_of(bytes(buf).decode("utf-8", errors="replace")) == "[DONE]":
                saw_done = True
        if not message_started:
            start_message()
        log_trace({
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "event": "chat_sse_truncated",
            "request_id": request_id,
            "pending_bytes": len(buf),
            "saw_done": 1 if saw_done else 0,
        })
        if saw_done:
            # The provider closed the stream properly, it just never said why:
            # protocol-complete, so close it with a terminal sequence.
            sr = "end_turn"
            if tool_calls_seen:
                sr = None
            terminal(sr)
            return first_byte_ms
        # No [DONE] ever arrived: the connection was cut mid-response and the
        # response is incomplete. Close it with an SSE error event, not a
        # synthesized terminal — a synthesized end_turn is indistinguishable, on
        # the wire, from a turn the model actually finished, so the client
        # records a completed message, reports no error and never retries.
        # `api_error` is the retryable 500-equivalent, so the client re-issues
        # the request. Close open blocks first so the partial turn is a
        # well-formed stream up to the error, and finalize the degradation
        # diagnostics — terminal() would have done both.
        close_all_blocks()
        log_degradation_if_needed()
        write({
            "type": "error",
            "error": {
                "type": "api_error",
                "message": "upstream stream ended without a finish_reason",
            },
        })
        return first_byte_ms

    def _log_response_cap_exceeded(self, request_id, bytes_streamed):
        log_trace({
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "event": "response_size_cap_exceeded",
            "request_id": request_id,
            "bytes_streamed": bytes_streamed,
            "limit": SETTINGS.max_response_size,
        })
        print("[proxy] Response size limit exceeded ({} bytes)".format(
            bytes_streamed), file=sys.stderr)
