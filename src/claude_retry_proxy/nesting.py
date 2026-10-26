"""Payload-nesting policy leaf: the proxy's own JSON depth limit.

The proxy parses untrusted JSON in many places — client request bodies,
buffered upstream bodies, upstream SSE frames, and JSON carried inside
strings (tool-call arguments, error bodies). The interpreter's recursion
limits alone do not bound that safely:

  - ``json``'s C decoder survives tens of thousands of levels (measured
    2026-10-25 on Python 3.14.7: ~52,150 levels in the C decoder, ~9,997
    in the 3.12 pure-Python fallback), and
  - the tool-schema walker (``transforms_common._sanitize_schema_patterns``)
    spends one Python frame per schema level, so it is the *binding* ceiling:
    it survives ~955 levels in situ before the transform's total guard
    swallows the RecursionError — which would silently ship an untransformed
    body upstream.

This module therefore defines the proxy's own policy, enforced by scanning
the payload BEFORE every parse of untrusted JSON:

    MAX_JSON_NESTING_DEPTH = 500

500 is ~2x below the walked-in-situ ceiling (>= 450 frames of margin), ~20x
below the json C ceiling, and ~80x deeper than real traffic (~6 levels).
Real bodies relaxed this bound; pathological ones are now rejected with a
deterministic, documented error instead of an interpreter-dependent failure.
The existing ``RecursionError`` / total-parse guards stay exactly as they
are: with the limit in place they are unreachable by construction, and they
remain as defence-in-depth.

The scan
--------
``check_payload_nesting`` is total on every input (it never raises, and it
returns ``None`` for a type it does not handle). It scans exactly the types
``json.loads`` parses — ``str``, ``bytes`` and ``bytearray`` — and nothing
else: a ``memoryview`` passes through, as it does to the parser. ``str`` is
scanned directly; ``bytes`` and ``bytearray`` are counted as bytes first and
only then decoded with ``json.detect_encoding`` — falling back to ``utf-8``
with ``errors="replace"`` — so the scan sees what ``json.loads`` will see.
A count-based fast path (total open brackets ``<= limit``) skips the scan
entirely for small payloads, and for bytes-like input it runs before any
decode: the count can only be an over-estimate (brackets inside strings
inflate it), so the fast path never hides a violation, and a bracket is a
bracket *byte* in every encoding ``json.detect_encoding`` returns (``utf-8``,
``utf-16``, ``utf-32``), so counting bytes cannot change a verdict. The
slow path is a string/escape state machine: brackets inside strings never
count, a close at depth 0 is ignored (the stack never underflows), every
close pops the type stack blindly (a mismatched pair simply makes the repair
parse fail later), and the walk early-exits at ``limit + 1``.

``offset`` is the character index into the decoded text of the opening
bracket that crossed the limit; it equals the byte offset for ASCII payloads.
``depth`` is that bracket's depth, i.e. ``limit + 1`` — a lower bound on the
body's true depth.

The trace event
---------------
``nesting_event`` builds the single ``nesting_limit_exceeded`` event every
enforcement site logs, from a violation plus the identity fields that site
has in scope (``request_id``; ``tier``; ``mode``/``provider``). It is pure —
the caller hands it to ``log_trace`` — so this module keeps no dependency on
the trace layer. ``NESTING_SITES`` is the site vocabulary, in the order of
the enforcement map in ``doc/architecture.html#nesting-limit``.

The diagnostic
--------------
On rejection the scanner knows the crossing offset and the types of the open
containers on the way. Appending the matching close sequence to
``text[:offset + 1]`` yields valid JSON at exactly ``limit + 1`` levels —
parseable on every supported interpreter — and an iterative walk (explicit
stack, no recursion) to its deepest node names the first structure over the
limit. The walk retains one small record per visited node — depth, parent
record, and the component (the parsed key object itself, never a copy, or a
list index) — so its retained memory is O(``_REPAIR_MAX_NODES``) whatever the
path length; only the winning leaf's path is rendered, by following the
parent links once at the end. Components render as ``.key`` when the key
matches ``[A-Za-z_][A-Za-z0-9_]*``, else as ``["<json-escaped key>"]``; a
path longer than 200 characters is truncated to
``path[:140] + "…" + path[-40:]``. Three bounded fallbacks keep the reject
path cheap and total: the repair is skipped entirely when the crossing offset
exceeds 1 MiB, the walk materializes at most ``_REPAIR_MAX_NODES`` records (a
wide fan of scalars would otherwise retain a path per element), and any
repair failure yields no path. Each degrade names itself on the violation's
``degrade`` field (``"cap"``, ``"budget"`` or ``"parse"``) while ``path``
stays ``None``; the offset is therefore always reported.

Cost (slow path; the fast path is two C-level counts — of characters for
``str``, of bytes for bytes-like input)
----------------------------------------------------------------------------
Measured 2026-10-25 on Python 3.14.7 (conda ``dev``): 13 ms at 0.29 MiB,
131 ms at 2.9 MiB, 420 ms at the 9.65 MiB body cap — against 4 / 46 / 158 ms
for the ``json.loads`` the same payload needs anyway (roughly 3x the parse
cost on wide-and-large bodies). The deep case costs microseconds because of
the early exit, and only payloads that are about to be parsed are scanned.
Verify on the current host/body mix by measuring on demand from the project
root::

    python3 - <<'EOF'
    import time, claude_retry_proxy.nesting as n
    body = b"[" + b",".join([b'{"a":{"b":"c"}}'] * 140000) + b"]"
    t = time.perf_counter(); n.check_payload_nesting(body)
    print("%.0f ms for %.2f MiB" % ((time.perf_counter() - t) * 1e3, len(body) / 2**20))
    EOF

Stdlib only, no package imports, no recursion.
"""

import json
import re
import time
from typing import NamedTuple, Optional

__all__ = ["MAX_JSON_NESTING_DEPTH", "NESTING_SITES", "NestingViolation",
           "check_payload_nesting", "nesting_event"]

# The proxy's accepted JSON nesting depth. A module constant by design: this
# is a policy of the proxy, not a user-facing knob. Before raising it,
# re-measure the Python-recursion ceiling of the schema walkers (the command
# lives in the module docstring) and keep >= 450 frames of margin.
MAX_JSON_NESTING_DEPTH = 500

# The nesting event's site vocabulary, in the order of the enforcement map
# (doc/architecture.html#nesting-limit). Every emitted event carries one.
NESTING_SITES = (
    "request_body",
    "admin_body",
    "response_transform",
    "response_rewrite",
    "sse_first_event",
    "chat_frame",
    "compat_error_body",
    "tool_args",
    "response_body_capture",
)

# Repair-parse bound: beyond this crossing offset the diagnostic skips the
# repaired-prefix parse and reports the offset alone.
_REPAIR_MAX_OFFSET = 1024 * 1024

# Repair-walk bound: node records materialized per diagnostic. A record is
# small — its component is a reference to the parsed key, not a rendered path
# string — so this bounds the walk's retained memory as well as its work, for
# every body shape. Far above any realistic schema, far below a pathological
# fan; on exhaustion the diagnostic degrades to the offset alone
# (degrade="budget").
_REPAIR_MAX_NODES = 20000

# Path truncation: longer than _PATH_MAX renders as head + ellipsis + tail.
_PATH_MAX = 200
_PATH_HEAD = 140
_PATH_TAIL = 40

_CLOSE = {"[": "]", "{": "}"}
_IDENT_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


class NestingViolation(NamedTuple):
    """The first structure in a payload that exceeds the nesting limit."""

    offset: int          # character index of the crossing open bracket
    depth: int           # that bracket's depth (limit + 1 — a lower bound)
    path: Optional[str]  # $-rooted location, or None when the locator degraded
    degrade: Optional[str] = None  # why path is None: "cap", "budget", "parse"


def check_payload_nesting(raw, limit=MAX_JSON_NESTING_DEPTH):
    """Return the payload's first nesting violation, or None.

    ``raw`` is ``str``, ``bytes`` or ``bytearray`` — the types ``json.loads``
    parses; any other type is treated as non-JSON and passes. Total: no
    input makes this raise.
    """
    if isinstance(raw, (bytes, bytearray)):
        # Count BYTES before decoding: a decoded "[" or "{" always comes from
        # a 0x5B / 0x7B byte in every encoding json.detect_encoding returns,
        # so the byte count is an upper bound on the character count and the
        # verdict cannot change — only a decode that would be wasted goes away.
        if raw.count(b"[") + raw.count(b"{") <= limit:
            return None
        if isinstance(raw, bytearray):
            raw = bytes(raw)
    text = _as_text(raw)
    if text is None:
        return None
    try:
        # Fast path: the bracket count bounds the depth from above (brackets
        # inside strings only inflate it), so a small payload passes outright.
        if text.count("[") + text.count("{") <= limit:
            return None
        crossed = _crossing(text, limit)
        if crossed is None:
            return None
        offset, open_types = crossed
        path, degrade = _deepest_path(text, offset, open_types)
        return NestingViolation(offset, limit + 1, path, degrade)
    except Exception:  # total: the scan must never raise into a request path
        return None


def nesting_event(site, violation, **fields):
    """Build the shared ``nesting_limit_exceeded`` trace event.

    Pure: the caller passes the result to ``log_trace``, so this module stays
    free of any dependency on the trace layer. ``site`` is one of
    ``NESTING_SITES``; ``fields`` carries exactly the identity fields that
    site has in scope (``request_id``; ``tier``; ``mode``/``provider``).
    """
    event = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "event": "nesting_limit_exceeded",
        "site": site,
        "depth": violation.depth,
        "offset": violation.offset,
        "path": violation.path,
        "degrade": violation.degrade,
    }
    event.update(fields)
    return event


def _as_text(raw):
    """Decode bytes-like the way json.loads will; scan str directly; else None."""
    if isinstance(raw, str):
        return raw
    if not isinstance(raw, (bytes, bytearray)):
        return None
    if isinstance(raw, bytearray):
        raw = bytes(raw)
    try:
        return raw.decode(json.detect_encoding(raw))
    except Exception:
        return raw.decode("utf-8", errors="replace")


def _crossing(text, limit):
    """Walk text until the nesting depth exceeds limit.

    Returns (offset, open_types) for the crossing bracket — the offset into
    text and the stack of open container types on the way — or None.
    """
    open_types = []
    in_string = False
    escaped = False
    for i, ch in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
        elif ch == '"':
            in_string = True
        elif ch in "[{":
            open_types.append(ch)
            if len(open_types) > limit:
                return i, open_types
        elif ch in "]}":
            if open_types:
                open_types.pop()  # blind pop: a mismatched pair fails later
    return None


def _deepest_path(text, offset, open_types):
    """Name the deepest structure of the repaired prefix.

    Returns ``(path, degrade)``: the $-rooted path with ``degrade`` None, or
    ``(None, reason)`` where reason is ``"cap"`` (crossing past the repair
    cap), ``"budget"`` (walk past ``_REPAIR_MAX_NODES``) or ``"parse"`` (the
    repaired prefix did not parse). The walk retains one record per node —
    ``(depth, parent_index, component, is_dict_key)`` — and renders only the
    deepest leaf's path, so memory is bounded by the record budget rather
    than by records x path length.
    """
    if offset > _REPAIR_MAX_OFFSET:
        return None, "cap"
    repaired = text[:offset + 1] + "".join(
        _CLOSE[opener] for opener in reversed(open_types))
    try:
        data = json.loads(repaired)
    except Exception:
        return None, "parse"
    records = [(0, -1, None, False)]  # index 0 is the root ("$")
    best_index = 0
    deepest = 0
    budget = _REPAIR_MAX_NODES
    stack = [(0, 0, data)]
    while stack:
        depth, record, node = stack.pop()
        pushed = False
        if isinstance(node, dict):
            for key, value in node.items():
                if budget <= 0:
                    return None, "budget"
                budget -= 1
                records.append((depth + 1, record, key, True))
                stack.append((depth + 1, len(records) - 1, value))
                pushed = True
        elif isinstance(node, list):
            for index, value in enumerate(node):
                if budget <= 0:
                    return None, "budget"
                budget -= 1
                records.append((depth + 1, record, index, False))
                stack.append((depth + 1, len(records) - 1, value))
                pushed = True
        if not pushed and depth > deepest:
            deepest = depth
            best_index = record
    return _truncate_path(_render_path(records, best_index)), None


def _render_path(records, index):
    """Reconstruct the $-rooted path that ends at records[index]."""
    parts = []
    while index > 0:
        _depth, parent, component, is_key = records[index]
        if is_key:
            parts.append(_render_key(component))
        else:
            parts.append("[{}]".format(component))
        index = parent
    parts.append("$")
    parts.reverse()
    return "".join(parts)


def _render_key(key):
    """Render one dict key as a path component."""
    if isinstance(key, str) and _IDENT_KEY.match(key):
        return "." + key
    return "[" + json.dumps(key) + "]"


def _truncate_path(path):
    """Cap an over-long path at the head+ellipsis+tail form."""
    if len(path) <= _PATH_MAX:
        return path
    return path[:_PATH_HEAD] + "…" + path[-_PATH_TAIL:]
