"""Client-facing error bodies in the Anthropic standard envelope.

Shared leaf: every error the proxy generates itself — forwarder give-up
paths, stream error frames, admin refusals — serializes through
`_error_body`. Stdlib-only (json); imported by forwarder (and, from
Step 8, by swap_drain), re-exported through forwarder for server,
chat_sse, and admin_api; imports none of its consumers.
"""

import json


def _error_body(error_type, code, message, request_id=None):
    """Build a client-facing error body in the Anthropic standard envelope.

    Returns bytes for
    {"type":"error","error":{"type":…,"code":…,"message":…},"request_id":…}.
    The top-level shape (type/error/request_id) is the Anthropic standard
    error envelope; error.type is a coarse taxonomy category while
    error.code is the proxy-discriminator extension carrying the fine
    detail (the former nested type strings ride there verbatim).
    The request_id key is omitted entirely (not null) when None.
    Serialized with json.dumps — never string interpolation — because
    message carries client-controlled text (unrecognized_model) and
    exception text (upstream_unreachable); both must stay JSON-escaped.
    """
    envelope = {
        "type": "error",
        "error": {"type": error_type, "code": code, "message": message},
    }
    if request_id is not None:
        envelope["request_id"] = request_id
    return json.dumps(envelope).encode("utf-8")
