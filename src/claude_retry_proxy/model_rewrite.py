"""Anthropic-mode response model projection (extracted from forwarder.py 2026-11-24).

Rewrites the upstream model name in anthropic-format responses to the
request's resolved tier name, behind two encodings: ``_rewrite_sse_event``
handles one SSE event (the ``message_start`` frame, located by the scan in
server.py), and ``_rewrite_json_response`` handles a buffered JSON body. Chat
and response modes get the model written by their own body transforms, so this
module serves anthropic mode only. The parent module (forwarder.py) imports
this one and re-exports both names; this module never imports its parent.
"""

import json
import time

from .nesting import check_payload_nesting, nesting_event
from .sinks import log_trace


def _rewrite_sse_event(event_bytes, tier, request_id):
    """Rewrite model in one SSE event if it is a message_start event.

    The anthropic-mode stream scan (server.py) splits the buffered prefix
    into complete events and runs each through this function until the
    message_start event is found — vendors may open with keep-alive frames
    (e.g. qwen sends event:ping first), so the rewrite cannot assume
    position. The boolean reports whether this event WAS message_start (by
    the SSE event: line or the parsed JSON type field), telling the scan to
    stop; an event that cannot be parsed still reports its event: line's
    verdict, and a data-only unparseable event reports False so the scan
    continues with the next one.

    Args:
        event_bytes: raw bytes of one complete SSE event (including its
            trailing blank line)
        tier: tier name to rewrite model to
        request_id: for logging

    Returns:
        (bytes, bool): possibly rewritten event, and whether the event is
        message_start
    """
    # Parse SSE event - look for event: and data: lines
    event_text = event_bytes.decode("utf-8", errors="replace")
    lines = event_text.split("\n")
    event_type = None
    data_lines = []

    for line in lines:
        if line.startswith("event:"):
            event_type = line[6:].strip()
        elif line.startswith("data:"):
            data_lines.append(line[5:].strip())

    # Parse JSON from data lines
    if not data_lines:
        return event_bytes, event_type == "message_start"

    json_text = "\n".join(data_lines)
    _nesting = check_payload_nesting(json_text)
    if _nesting is not None:
        # Forward the event unchanged rather than parsing it; the scan
        # continues, so the client sees the upstream model name from this
        # event only if no later event is message_start.
        log_trace(nesting_event("sse_first_event", _nesting,
                                request_id=request_id, tier=tier))
        return event_bytes, event_type == "message_start"
    try:
        data = json.loads(json_text)
    except Exception:  # total per compat._compat_guarded_parse (RecursionError is not a ValueError)
        # Malformed JSON - forward unchanged with warning
        log_trace({
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "event": "sse_rewrite_malformed_json",
            "request_id": request_id,
        })
        return event_bytes, event_type == "message_start"

    # Check if this is a message_start event
    # Check both SSE event type and JSON type field (SSE events can omit event: line)
    json_type = data.get("type") if isinstance(data, dict) else None
    is_message_start = (event_type == "message_start") or (json_type == "message_start")

    if not is_message_start:
        # Not a message_start event - forward unchanged
        return event_bytes, False

    # A message_start event: line over a non-object payload (e.g. "[1,2]"):
    # nothing is rewritable — the scan ends here, degraded, never crashing
    # (a non-dict would make data.get below raise AttributeError; every
    # branch of this function must degrade, not raise).
    if not isinstance(data, dict):
        return event_bytes, True

    # Check for model field and rewrite
    message = data.get("message", {})
    if not isinstance(message, dict):
        return event_bytes, True

    upstream_model = message.get("model")
    if not upstream_model:
        return event_bytes, True

    # Rewrite model to tier name
    message["model"] = tier
    data["message"] = message

    # Rebuild SSE event - preserve original format. The re-serialize runs in
    # its own guard (mirroring transforms_common._transform_and_guard's
    # decode/encode pair): an encode failure degrades to the original event
    # rather than escape unfenced and abort the stream. Kept as
    # defence-in-depth — check_payload_nesting bounds what json.loads is ever
    # shown, so depth no longer reaches the encoder — and kept separate from
    # the decode guard so an encode failure does not log
    # sse_rewrite_malformed_json — the JSON parsed fine.
    try:
        new_json = json.dumps(data)
        if event_type:
            # Had explicit event: line
            new_event = "event: {}\ndata: {}\n\n".format(event_type, new_json)
        else:
            # Data-only format
            new_event = "data: {}\n\n".format(new_json)
        return new_event.encode("utf-8"), True
    except Exception:  # total per compat._compat_guarded_parse (RecursionError is not a ValueError)
        return event_bytes, True


def _rewrite_json_response(body_bytes, tier, request_id):
    """Rewrite model field in JSON response body.

    Args:
        body_bytes: raw response body
        tier: tier name to rewrite model to
        request_id: for logging

    Returns:
        bytes: possibly rewritten body
    """
    _nesting = check_payload_nesting(body_bytes)
    if _nesting is not None:
        log_trace(nesting_event("response_rewrite", _nesting,
                                request_id=request_id, tier=tier))
        return body_bytes
    try:
        data = json.loads(body_bytes)
        if not isinstance(data, dict):
            return body_bytes
        upstream_model = data.get("model")
        if not upstream_model or not isinstance(upstream_model, str):
            return body_bytes
        data["model"] = tier
        # The re-serialize stays INSIDE this guard: an encode failure must
        # return the original body rather than escape unfenced and abort the
        # response. Kept as defence-in-depth — check_payload_nesting bounds
        # what json.loads is ever shown, so depth no longer reaches the
        # encoder — and it still fences non-depth encode failures (e.g. an
        # unserializable value type).
        return json.dumps(data).encode("utf-8")
    except Exception:  # total per compat._compat_guarded_parse (RecursionError is not a ValueError)
        return body_bytes
