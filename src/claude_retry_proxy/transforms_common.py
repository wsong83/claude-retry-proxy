"""Shared mechanism for endpoint-mode response transforms: the passthrough-on-failure guard and the shared trace-timestamp helper."""

import json
import time

from .sinks import log_trace

__all__ = ["_transform_and_guard", "_request_transform_timestamp"]


def _transform_and_guard(raw_body, tier, transform_fn, request_id, mode, provider):
    """Run a response transform on raw JSON bytes with passthrough-on-failure.

    json.loads runs INSIDE the guard: any parse or shape failure logs a
    transform_failure trace event (metadata only — never body content) and
    returns the original raw bytes unchanged.
    """
    try:
        parsed = json.loads(raw_body)
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError):
        log_trace({
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "event": "transform_failure",
            "request_id": request_id,
            "mode": mode,
            "provider": provider,
            "tier": tier,
        })
        return raw_body
    try:
        return json.dumps(transform_fn(parsed, tier, request_id=request_id, mode=mode, provider=provider)).encode("utf-8")
    except (json.JSONDecodeError, KeyError, TypeError, IndexError,
            AttributeError, ValueError):
        log_trace({
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "event": "transform_failure",
            "request_id": request_id,
            "mode": mode,
            "provider": provider,
            "tier": tier,
        })
        return raw_body


def _request_transform_timestamp():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
