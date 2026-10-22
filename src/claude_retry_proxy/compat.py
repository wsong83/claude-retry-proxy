"""Compatibility learner for the Claude retry proxy: learns per-provider-key
upstream incompatibilities behind a registry of features (`COMPAT_FEATURES`).

Two features:
  - `context_management` (anthropic mode): strips the feature and retries on a
    confirmed rejection, doubling the strip threshold on repeated rejection.
    It holds the subsystem's only retry lock (`_compat_retry_lock`).
  - `reasoning_field` (chat mode): a saturating per-key credit learner fed by
    the top-level attempt-1 outcomes (a success credits +1 up to
    `saturation_max`; a matched complaint drains −1, and the edge to 0
    advances the entry one step in the candidate cycle and re-arms the credit
    at `saturation_on_switch`), plus a lock-free, key-free rescue that re-rolls
    the candidates for any matched complaint. Learning evidence is attempt 1
    only — rescue outcomes teach nothing.

Both share the storage envelope and the persistence/lock plumbing; each owns
its own entry field set and state vocabulary. Persisted state is
metadata-only; the 0o600 chmod is POSIX-only — Windows users must restrict the
state directory ACL manually.
"""

import json
import os
import re
import sys
import threading
import time
import uuid

from .sanitize import sanitize_error
from .sinks import log_trace
from .settings import SETTINGS

# ---------------------------------------------------------------------------
# Feature compatibility learning (registry: name -> descriptor)
# ---------------------------------------------------------------------------

# Maintainer-tunable policy constants (no user-facing configuration surface).
COMPAT_INITIAL_THRESHOLD = 32      # strips before first revalidation probe
COMPAT_PROBATION_THRESHOLD = 8     # strips between probation probes
COMPAT_BACKOFF_MULTIPLIER = 2      # threshold multiplier on repeated rejection
COMPAT_MAX_THRESHOLD = 4096        # maximum strip threshold
COMPAT_DELISTING_SUCCESSES = 2     # successful probes to delist
COMPAT_MAX_RETRIES_PER_REQUEST = 1 # maximum compatibility retries per client request
COMPAT_FAILED_CONFIRMATION_SUPPRESSION = 3  # failed confirmations before suppression

# reasoning_field policy: the rescue's candidate re-rolls per matched
# complaint (the initial attempt plus up to two rescue passes).
COMPAT_REASONING_MAX_RETRIES_PER_REQUEST = 2

# The legacy singleton constant: server.py imports it and the existing trace
# events emit it. It names the anthropic-mode feature; the registry is keyed by
# feature name, and each descriptor owns the feature's mode scope.
COMPAT_FEATURE = "context_management"
COMPAT_SCHEMA_VERSION = 1

COMPAT_STATE_UNSUPPORTED = "unsupported"
COMPAT_STATE_PROBATION = "probation"

# The reasoning-echo field vocabulary. Field names are our own constants;
# upstream text is only ever matched against patterns built from them.
COMPAT_REASONING_FIELDS = ("reasoning_content", "reasoning")
# Persisted selections are a subset: "none" is never persisted (an absent entry
# means none).
COMPAT_REASONING_SELECTIONS = ("reasoning_content", "reasoning")


# Owned compatibility state. The singleton `_state` is stored exactly once
# (module level, below) and never rebound; state-touching functions take a
# `state=_state` default parameter so explicit injection isolates state.
class _CompatState(object):
    """Learned state shared by every registered feature: the four
    context_management dicts, the reasoning_field stores, and the single
    retry lock the anthropic feature holds."""

    def __init__(self):
        # In-memory learned state: {key_string: entry_dict}
        self.entries = {}
        # Per-key in-memory failed-confirmation counters: {key_string: int}
        self.failed_confirmations = {}
        # Per-key counters of matching requests seen while suppression is
        # active: re-enters discovery after COMPAT_INITIAL_THRESHOLD matching
        # requests.
        self.suppressed_seen = {}
        # Rate limiter for compatibility_persist_failed trace events:
        # {key_string: ts}
        self.persist_warned = {}
        # reasoning_field: per-key in-memory learning credit (the saturating
        # capacitor fed by attempt-1 outcomes). An absent key reads as the
        # operator's saturation_on_switch (config.py policy).
        self.reasoning_credit = {}
        # Fast lock: protects every dict above and serializes persistence I/O
        # (built under the lock).
        self.lock = threading.Lock()
        # Slow-path lock: at most one in-flight compatibility retry/probe for
        # the anthropic feature. Acquired with blocking=False; held for the
        # duration of the upstream HTTP call; released in finally on every
        # outcome.
        self.retry_lock = threading.Lock()


_state = _CompatState()

# Module-level lock aliases (re-export surface for server.py): they alias the
# singleton's locks and are never rebound.
_compat_state_lock = _state.lock
_compat_retry_lock = _state.retry_lock


def _compat_validate_constants():
    """Validate tuning-constant relationships at startup; warn and clamp."""
    global COMPAT_INITIAL_THRESHOLD, COMPAT_BACKOFF_MULTIPLIER, \
        COMPAT_DELISTING_SUCCESSES
    if COMPAT_BACKOFF_MULTIPLIER < 2:
        print("[proxy] WARNING: COMPAT_BACKOFF_MULTIPLIER must be >= 2 — "
              "clamped to 2", file=sys.stderr)
        COMPAT_BACKOFF_MULTIPLIER = 2
    if COMPAT_DELISTING_SUCCESSES < 2:
        print("[proxy] WARNING: COMPAT_DELISTING_SUCCESSES must be >= 2 — "
              "clamped to 2", file=sys.stderr)
        COMPAT_DELISTING_SUCCESSES = 2
    if COMPAT_INITIAL_THRESHOLD > COMPAT_MAX_THRESHOLD:
        print("[proxy] WARNING: COMPAT_INITIAL_THRESHOLD exceeds "
              "COMPAT_MAX_THRESHOLD — clamped", file=sys.stderr)
        COMPAT_INITIAL_THRESHOLD = COMPAT_MAX_THRESHOLD
    seen_modes = {}
    for descriptor in COMPAT_FEATURES.values():
        if descriptor.mode in seen_modes:
            print("[proxy] WARNING: compatibility features {!r} and {!r} both "
                  "claim mode {!r} — _feature_for_mode is ambiguous".format(
                      seen_modes[descriptor.mode], descriptor.name,
                      descriptor.mode), file=sys.stderr)
        else:
            seen_modes[descriptor.mode] = descriptor.name


def _compat_key(provider, mode, actual_model, feature):
    """Build the in-memory state key for a learned entry."""
    return (provider, mode, actual_model, feature)


def _compat_file_key(key):
    """Serialize a state key tuple for the persisted dict (unambiguous separator)."""
    return "\x1f".join(key)


def _compat_normalize_threshold(threshold):
    """Snap an arbitrary threshold onto the doubling ladder [initial, max].

    Returns the largest ladder element (initial * multiplier^k) that does not
    exceed min(threshold, max), floored at COMPAT_INITIAL_THRESHOLD.
    """
    t = COMPAT_INITIAL_THRESHOLD
    while t * COMPAT_BACKOFF_MULTIPLIER <= min(threshold, COMPAT_MAX_THRESHOLD):
        t *= COMPAT_BACKOFF_MULTIPLIER
    return t


def _context_management_present(body_json):
    """True when the client body carries the feature at top level."""
    return isinstance(body_json, dict) and COMPAT_FEATURE in body_json


def _compat_validate_context_management_entry(entry):
    """context_management's entry validator. Total: None or a body dict."""
    try:
        if not isinstance(entry, dict):
            return None
        state = entry.get("state")
        if state not in (COMPAT_STATE_UNSUPPORTED, COMPAT_STATE_PROBATION):
            return None
        threshold = entry.get("threshold")
        if not isinstance(threshold, int) or isinstance(threshold, bool):
            return None
        strip_counter = entry.get("strip_counter", 0)
        probation_successes = entry.get("probation_successes", 0)
        for v in (strip_counter, probation_successes):
            if not isinstance(v, int) or isinstance(v, bool):
                return None
        return {
            "state": state,
            "threshold": _compat_normalize_threshold(threshold),
            # Counters are in-memory-only: restart resets them to zero
            # (fail-safe direction — over-stripping, never under-stripping).
            "strip_counter": 0,
            "probation_successes": 0,
        }
    except Exception:
        return None


def _compat_validate_reasoning_entry(entry):
    """reasoning_field's entry validator. Total: None or a body dict."""
    try:
        if not isinstance(entry, dict):
            return None
        selection = entry.get("selection")
        if selection not in COMPAT_REASONING_SELECTIONS:
            return None
        return {"selection": selection}
    except Exception:
        return None


def _compat_validate_entry(entry):
    """Validate one loaded state entry. Returns a normalized entry or None.

    Total: every shape it cannot validate (including a raising descriptor
    validator) yields None rather than escaping. The shared envelope is
    validated here; the descriptor validates its own values.
    """
    try:
        if not isinstance(entry, dict):
            return None
        provider = entry.get("provider")
        mode = entry.get("mode")
        actual_model = entry.get("actual_model")
        feature = entry.get("feature")
        if not isinstance(provider, str) or not provider:
            return None
        if not isinstance(mode, str) or not mode:
            return None
        if not isinstance(actual_model, str) or not actual_model:
            return None
        if not isinstance(feature, str) or not feature:
            return None
        descriptor = COMPAT_FEATURES.get(feature)
        if descriptor is None:
            return None
        if mode != descriptor.mode:
            # The entry's mode must agree with its descriptor's, or it would
            # load under a key no request path can ever produce.
            return None
        body = descriptor.validate_entry(entry)
        if not isinstance(body, dict):
            return None
        envelope = {
            "schema_version": COMPAT_SCHEMA_VERSION,
            "provider": provider,
            "mode": mode,
            "actual_model": actual_model,
            "feature": feature,
        }
        # The descriptor contributes only its own fields: the envelope wins any
        # key collision, so a descriptor body can never spoof entry identity.
        merged = dict(body)
        merged.update(envelope)
        return merged
    except Exception:
        return None


def _load_compat_state(state=_state):
    """Load learned compatibility state from SETTINGS.feature_compat_file.

    Missing file → empty state (no warning). Malformed/unreadable file →
    warn to stderr and fail open with empty state. Known schema version with
    invalid individual entries → drop bad entries, keep valid ones, warn per
    entry. Unknown feature names → ignored (forward-compat). Each entry is
    stored under a key derived from its own identity, never from its file key.

    The wholesale `state.entries = loaded` assignment is startup-only and not
    lock-synchronized — any future reload-path caller must hold `state.lock`.
    """
    loaded = {}
    try:
        with open(SETTINGS.feature_compat_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return
    except (OSError, json.JSONDecodeError, UnicodeDecodeError, ValueError) as e:
        print("[proxy] WARNING: compatibility state file unreadable "
              "({}) — failing open with empty state".format(
                  sanitize_error(str(e))), file=sys.stderr)
        return
    if not isinstance(data, dict):
        print("[proxy] WARNING: compatibility state file is not a JSON "
              "object — failing open with empty state", file=sys.stderr)
        return
    version = data.get("schema_version")
    if version != COMPAT_SCHEMA_VERSION:
        print("[proxy] WARNING: compatibility state file has unknown "
              "schema_version {!r} (expected {}) — failing open with "
              "empty state".format(version, COMPAT_SCHEMA_VERSION),
              file=sys.stderr)
        return
    entries = data.get("entries")
    if not isinstance(entries, dict):
        print("[proxy] WARNING: compatibility state file has invalid "
              "'entries' — failing open with empty state", file=sys.stderr)
        return
    for entry in entries.values():
        try:
            parsed = _compat_validate_entry(entry)
        except Exception:
            # Belt-and-braces: a raising validator degrades to a dropped entry
            # below rather than escaping this startup path.
            parsed = None
        if parsed is None:
            feature_name = entry.get("feature") if isinstance(entry, dict) else None
            if feature_name not in COMPAT_FEATURES:
                # Unknown feature keys: ignore silently (forward-compat).
                continue
            print("[proxy] WARNING: dropping invalid compatibility state "
                  "entry (key redacted)", file=sys.stderr)
            continue
        # Derive the in-memory key from the entry's own identity. The file key
        # is never used as a key (and never parsed): a key whose string names
        # one feature while its body names another must not load under the
        # mismatched key, and a hand-edited key without the separator must not
        # raise.
        loaded[(parsed["provider"], parsed["mode"], parsed["actual_model"],
                parsed["feature"])] = parsed
    state.entries = loaded


def _persist_compat_state_locked(state=_state):
    """Atomically persist the learned state. Caller must hold state.lock.

    Keeps successful in-memory updates on failure and emits a rate-limited
    metadata-only compatibility_persist_failed trace event (once per 60s per key).
    """
    payload = {
        "schema_version": COMPAT_SCHEMA_VERSION,
        "entries": {_compat_file_key(k): v for k, v in state.entries.items()},
    }
    d = os.path.dirname(SETTINGS.feature_compat_file)
    tmp = "{}.{}.tmp".format(SETTINGS.feature_compat_file,
                             "{}-{}".format(os.getpid(),
                                            uuid.uuid4().hex[:8]))
    try:
        if d:
            os.makedirs(d, exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        os.replace(tmp, SETTINGS.feature_compat_file)
        if os.name == "posix":
            try:
                os.chmod(SETTINGS.feature_compat_file, 0o600)
            except OSError:
                pass
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        return False
    return True


def _compat_persist_failure_trace(key, state=_state):
    """Rate-limited metadata-only trace for persistence failure (60s per key).

    Inherits the caller-must-hold-state.lock contract from
    _persist_compat_state_locked (its only call site remains inside that
    function, under the lock).
    """
    key_str = _compat_file_key(key)
    now = time.time()
    last = state.persist_warned.get(key_str, 0)
    if now - last < 60:
        return
    state.persist_warned[key_str] = now
    log_trace({
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "event": "compatibility_persist_failed",
        "provider": key[0],
        "mode": key[1],
        "actual_model": key[2],
        "feature": key[3],
    })


def _compat_update(key, mutate, state=_state):
    """Apply mutate(entry_dict) under the state lock and persist on transition.

    mutate receives the current entry dict (or None) and returns
    (new_entry_or_None, persist_flag). new_entry None means delist. Returns
    the resulting entry (or None).
    """
    with state.lock:
        entry = state.entries.get(key)
        new_entry, persist = mutate(entry)
        if new_entry is None:
            state.entries.pop(key, None)
        else:
            state.entries[key] = new_entry
        if persist:
            if not _persist_compat_state_locked(state=state):
                _compat_persist_failure_trace(key, state=state)
        return new_entry


def _compat_get(key, state=_state):
    with state.lock:
        return state.entries.get(key)


def _compat_record_failed_confirmation(key, state=_state):
    """Increment the in-memory failed-confirmation counter. Returns the count."""
    with state.lock:
        n = state.failed_confirmations.get(key, 0) + 1
        state.failed_confirmations[key] = n
        return n


def _compat_reset_failed_confirmations(key, state=_state):
    with state.lock:
        state.failed_confirmations.pop(key, None)


def _compat_suppressed(key, state=_state):
    with state.lock:
        return state.failed_confirmations.get(key, 0) \
            >= COMPAT_FAILED_CONFIRMATION_SUPPRESSION


def _compat_note_suppressed_request(key, state=_state):
    """Count a matching request seen while suppression is active.

    After COMPAT_INITIAL_THRESHOLD matching requests, re-enter discovery by
    clearing the failed-confirmation counter for the key.
    """
    with state.lock:
        n = state.suppressed_seen.get(key, 0) + 1
        if n >= COMPAT_INITIAL_THRESHOLD:
            state.suppressed_seen.pop(key, None)
            state.failed_confirmations.pop(key, None)
        else:
            state.suppressed_seen[key] = n


def _compat_learn(key, request_id, tier, state=_state):
    """Record unsupported state for key after a successful stripped retry."""
    def mutate(entry):
        if entry is not None:
            return entry, False  # already learned
        return ({
            "schema_version": COMPAT_SCHEMA_VERSION,
            "provider": key[0],
            "mode": key[1],
            "actual_model": key[2],
            "feature": key[3],
            "state": COMPAT_STATE_UNSUPPORTED,
            "threshold": COMPAT_INITIAL_THRESHOLD,
            "strip_counter": 0,
            "probation_successes": 0,
        }, True)

    _compat_update(key, mutate, state=state)
    _compat_reset_failed_confirmations(key, state=state)
    log_trace({
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "event": "compatibility_learned",
        "request_id": request_id,
        "provider": key[0],
        "mode": key[1],
        "actual_model": key[2],
        "feature": key[3],
        "tier": tier,
        "state": COMPAT_STATE_UNSUPPORTED,
        "threshold": COMPAT_INITIAL_THRESHOLD,
    })


def _compat_record_strip(key, state=_state):
    """Increment the strip counter. Returns True when the threshold is reached.

    Effective threshold: COMPAT_PROBATION_THRESHOLD (8) in probation state,
    otherwise the entry's (possibly doubled) threshold.
    """
    with state.lock:
        entry = state.entries.get(key)
        if entry is None:
            return False
        entry["strip_counter"] += 1
        if entry["state"] == COMPAT_STATE_PROBATION:
            return entry["strip_counter"] >= COMPAT_PROBATION_THRESHOLD
        return entry["strip_counter"] >= entry["threshold"]


def _compat_reset_strip_counter(key, state=_state):
    with state.lock:
        entry = state.entries.get(key)
        if entry is not None:
            entry["strip_counter"] = 0


def _compat_probe_success(key, request_id, tier, state=_state):
    """Record one probe success; delist at delisting_successes, else probation."""
    existed = True

    def mutate(entry):
        nonlocal existed
        if entry is None:
            existed = False
            return None, False
        entry["probation_successes"] += 1
        entry["strip_counter"] = 0
        if entry["probation_successes"] >= COMPAT_DELISTING_SUCCESSES:
            return None, True
        entry["state"] = COMPAT_STATE_PROBATION
        return entry, True

    result = _compat_update(key, mutate, state=state)
    if not existed:
        return  # entry vanished concurrently — no state change to report
    if result is not None:
        log_trace({
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "event": "compatibility_probe_succeeded",
            "request_id": request_id,
            "provider": key[0],
            "mode": key[1],
            "actual_model": key[2],
            "feature": key[3],
            "tier": tier,
            "probation_successes": result["probation_successes"],
        })
    else:
        log_trace({
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "event": "compatibility_delisted",
            "request_id": request_id,
            "provider": key[0],
            "mode": key[1],
            "actual_model": key[2],
            "feature": key[3],
            "tier": tier,
        })


def _compat_probe_rejected(key, request_id, tier, state=_state):
    """Repeated rejection: reset probation, double the threshold (capped), persist."""
    def mutate(entry):
        if entry is None:
            return None, False
        entry["probation_successes"] = 0
        entry["state"] = COMPAT_STATE_UNSUPPORTED
        entry["strip_counter"] = 0
        entry["threshold"] = min(entry["threshold"] * COMPAT_BACKOFF_MULTIPLIER,
                                 COMPAT_MAX_THRESHOLD)
        return entry, True

    result = _compat_update(key, mutate, state=state)
    if result is not None:
        log_trace({
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "event": "compatibility_probe_rejected",
            "request_id": request_id,
            "provider": key[0],
            "mode": key[1],
            "actual_model": key[2],
            "feature": key[3],
            "tier": tier,
            "threshold": result["threshold"],
        })


def _compat_probe_inconclusive(key, request_id, tier, state=_state):
    """Inconclusive probe: leave state/successes unchanged, reschedule at current."""
    with state.lock:
        entry = state.entries.get(key)
        threshold = entry["threshold"] if entry else COMPAT_INITIAL_THRESHOLD
        if entry is not None:
            entry["strip_counter"] = 0
    log_trace({
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "event": "compatibility_probe_inconclusive",
        "request_id": request_id,
        "provider": key[0],
        "mode": key[1],
        "actual_model": key[2],
        "feature": key[3],
        "tier": tier,
        "threshold": threshold,
    })


# Anchored message-form detector for the observed unsupported-feature 400.
# The feature token must appear at message start or be preceded by ': ' or
# '] ' — dotted nested-path matches (e.g. tools.0.context_management) never
# match. Built from the policy constant; upstream text is only ever matched
# against it, never copied.
_COMPAT_MESSAGE_RE = re.compile(
    r"(?:^|(?<=: )|(?<=\] ))" + re.escape(COMPAT_FEATURE) +
    r": Extra inputs are not permitted$")


def _compat_message_match(data):
    """True if any error message matches the anchored message-form 400 shape."""
    stack = [data]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            msg = node.get("message")
            if isinstance(msg, str) and _COMPAT_MESSAGE_RE.search(msg):
                return True
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return False


def _compat_structured_match(data):
    """True if structured `extra_forbidden` validation data locates the
    feature constant at top level (loc ends with it and is not a nested path)."""
    stack = [data]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            if any(node.get(k) == "extra_forbidden" for k in ("type", "code")):
                loc = node.get("loc", node.get("location"))
                if isinstance(loc, list) and loc:
                    if (loc[-1] == COMPAT_FEATURE and len(loc) <= 2
                            and (len(loc) == 1 or loc[0] in ("body", "request"))):
                        return True
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return False


def _compat_guarded_parse(resp_body):
    """Parse an upstream error body as JSON; None on any failure.

    The shared total helper behind every complaint matcher: it catches
    Exception so a RecursionError (raised by json.loads on deeply nested
    input, and not a ValueError) degrades to None rather than escaping into
    the unguarded call-site family.
    """
    try:
        return json.loads(resp_body)
    except Exception:
        return None


def _compat_rejection_match(status, resp_body):
    """Recognize the two enumerated unsupported-feature 400 shapes.

    Content-type agnostic: the drained body is parsed as JSON regardless of
    the upstream Content-Type header. Bodies exceeding SETTINGS.max_body_size
    or failing to parse are inconclusive (False — never learn).
    """
    if status != 400 or not resp_body:
        return False
    if len(resp_body) > SETTINGS.max_body_size:
        return False
    data = _compat_guarded_parse(resp_body)
    if not isinstance(data, dict):
        return False
    return _compat_message_match(data) or _compat_structured_match(data)


def _reasoning_present(body_json):
    """True when the client body carries an assistant thinking block worth
    echoing (non-empty `thinking`, or a `redacted_thinking` with non-empty
    `data`). Total: any shape it cannot interpret is False."""
    try:
        if not isinstance(body_json, dict):
            return False
        messages = body_json.get("messages")
        if not isinstance(messages, list):
            return False
        for msg in messages:
            if not isinstance(msg, dict) or msg.get("role") != "assistant":
                continue
            content = msg.get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict):
                    continue
                btype = block.get("type")
                if btype == "thinking":
                    if isinstance(block.get("thinking"), str) and block["thinking"]:
                        return True
                elif btype == "redacted_thinking":
                    if isinstance(block.get("data"), str) and block["data"]:
                        return True
        return False
    except Exception:
        return False


# Unanchored (word-boundary) field-name detector for the reasoning complaint.
# The lookbehind rejects a preceding word character or a dot (so the dotted
# nested path `messages.0.reasoning_content` never matches); the lookahead
# rejects a following word character but NOT a period, so the ordinary
# sentence-final mention still matches. Built from our own constants.
_REASONING_FIELD_RE = re.compile(
    r"(?<![\w.])(?:" + "|".join(re.escape(f) for f in COMPAT_REASONING_FIELDS) +
    r")(?![\w])")


def _reasoning_message_match(data):
    """True if any error `message` VALUE names a reasoning field.

    The traversal mirrors _compat_message_match: only the `message` value of
    each visited dict is inspected, so a gateway echoing the offending request
    as nested JSON cannot hand the matcher its own request text.
    """
    stack = [data]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            msg = node.get("message")
            if isinstance(msg, str) and _REASONING_FIELD_RE.search(msg):
                return True
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return False


def _reasoning_structured_match(data):
    """True if a structured `extra_forbidden` node's loc ENDS with a field name.

    Mirrors _compat_structured_match in discipline but not in depth guard: the
    reasoning field lives inside an assistant message, so the loc is deeper
    than context_management's top-level path and nothing is required of the
    prefix.
    """
    stack = [data]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            if any(node.get(k) == "extra_forbidden" for k in ("type", "code")):
                loc = node.get("loc", node.get("location"))
                if isinstance(loc, list) and loc and loc[-1] in COMPAT_REASONING_FIELDS:
                    return True
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return False


def _reasoning_complaint_match(status, resp_body):
    """Recognize a 400 complaining about a reasoning field. Total.

    Two content shapes, both keyed on our field-name constants and carrying no
    phrase matching: a 400 whose parsed body has a `message` value naming a
    field, or a 400 whose body carries an `extra_forbidden` node whose loc ends
    with a field name. A 401/403/500, an unparseable body, or a 400 naming no
    field is not a complaint.
    """
    if status != 400 or not resp_body:
        return False
    if len(resp_body) > SETTINGS.max_body_size:
        return False
    data = _compat_guarded_parse(resp_body)
    if not isinstance(data, dict):
        return False
    return _reasoning_message_match(data) or _reasoning_structured_match(data)


def _reasoning_next_candidate(current):
    """Next candidate in the cycle none -> reasoning_content -> reasoning -> none.

    Returns the string "none" for an unknown, None, or non-string input —
    never None, which the resolver parameter reserves for "resolve me".
    """
    if current == "none":
        return "reasoning_content"
    if current == "reasoning_content":
        return "reasoning"
    return "none"


def _compat_merge_retries(original_result, retry_result):
    """Sum the original forwarding loop's retries with the retry's own."""
    merged = list(retry_result)
    merged[5] = (retry_result[5] or 0) + (original_result[5] or 0)
    return tuple(merged)


def _compat_stripped_body(body):
    """Derive the stripped client body (original minus the feature). None if
    the original body does not parse as a JSON object."""
    try:
        stripped = json.loads(body)
        if not isinstance(stripped, dict):
            return None
        stripped.pop(COMPAT_FEATURE, None)
        return json.dumps(stripped).encode("utf-8")
    except Exception:  # total per _compat_guarded_parse (RecursionError is not a ValueError)
        return None


# ---------------------------------------------------------------------------
# reasoning_field policy
#
# State is two pieces: the persisted `selection` (absent means none) and an
# in-memory per-key credit (absent reads as `saturation_on_switch`). The
# credit is learning evidence at attempt 1 only — the rescue neither reads nor
# writes it. Every credit read-modify-write runs in one state.lock hold; the
# selection advance runs inside one _compat_update call.
# ---------------------------------------------------------------------------

def _reasoning_credit_on_2xx(key, s_max, s_sw, state=_state):
    """One gate-true attempt-1 success: raise the key's credit by one.

    The credit saturates at `s_max`, so a dense run of successes can never
    bank more than one full refill. An absent key reads as `s_sw`: a selection
    arrives with conservative credit, so sustained breakage still drains it
    within ~`s_sw` complaint episodes. Returns the stored credit. Total.
    """
    with state.lock:
        credit = min(state.reasoning_credit.get(key, s_sw) + 1, s_max)
        state.reasoning_credit[key] = credit
        return credit


def _reasoning_credit_on_complaint(key, s_max, s_sw, state=_state):
    """One gate-true attempt-1 matched complaint: drain the credit by one.

    Edge-triggered and atomic: the read, the decrement, the
    ``before > 0 and after == 0`` decision, and the ``s_sw`` reset happen in
    ONE ``state.lock`` hold, so each decrement yields exactly one
    ``switch_due`` — a per-decrement guarantee, not a per-burst one: at
    ``s_sw == 1`` the reset re-arms the stored credit to 1, so every further
    complaint of a sustained episode (concurrent or sequential) legitimately
    fires its own edge. The stored credit is never left at 0 — the reset is
    what makes the next switch cost ``s_sw`` further complaints. Returns
    ``(credit, switch_due)``, ``credit`` being the stored value after the
    episode (``s_sw`` on the switch edge). ``s_max`` is accepted for symmetry
    with the 2xx function; the complaint path never needs a cap. Total.
    """
    with state.lock:
        before = state.reasoning_credit.get(key, s_sw)
        after = max(0, before - 1)
        switch_due = before > 0 and after == 0
        credit = s_sw if switch_due else after
        state.reasoning_credit[key] = credit
        return credit, switch_due


def _reasoning_advance_selection(key, request_id, tier, state=_state):
    """Advance the entry's selection one step in the candidate cycle.

    The one learn-side write this model keeps: called on the edge where the
    credit reaches 0. The ``mutate`` closure runs under ``state.lock`` inside
    ONE ``_compat_update`` call — never a nested ``state.lock``, the lock is
    not reentrant — and re-reads the entry's CURRENT selection under it, so a
    slow in-flight request can never revert a newer switch. Every advance
    changes the entry by cycle construction:

      * next candidate ``"none"`` -> delist the existing entry
        (``compatibility_delisted``)
      * absent entry              -> create it (``compatibility_learned``)
      * existing entry            -> rewrite its selection
        (``compatibility_switched``)

    Emits the same event shape the removed persist-switch helper used
    (``selection`` only when the candidate is not ``"none"``). Returns the
    outcome event name. Total.
    """
    outcome = [None]
    advanced = [None]

    def mutate(entry):
        current = "none"
        if (isinstance(entry, dict)
                and entry.get("selection") in COMPAT_REASONING_SELECTIONS):
            current = entry["selection"]
        candidate = _reasoning_next_candidate(current)
        advanced[0] = candidate
        if candidate == "none":
            outcome[0] = "compatibility_delisted"
            return None, True
        if entry is None:
            outcome[0] = "compatibility_learned"
            return ({
                "schema_version": COMPAT_SCHEMA_VERSION,
                "provider": key[0],
                "mode": key[1],
                "actual_model": key[2],
                "feature": key[3],
                "selection": candidate,
            }, True)
        entry["selection"] = candidate
        outcome[0] = "compatibility_switched"
        return entry, True

    _compat_update(key, mutate, state=state)
    event = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "event": outcome[0],
        "request_id": request_id,
        "provider": key[0],
        "mode": key[1],
        "actual_model": key[2],
        "feature": key[3],
        "tier": tier,
    }
    if advanced[0] != "none":
        event["selection"] = advanced[0]
    log_trace(event)
    return outcome[0]


def _reasoning_entry_selection(key, state=_state):
    """The learned selection for one request, read under one lock.

    Returns the entry's selection, or "none" when no usable entry exists or
    its value is not a known selection. This is the only place the persisted
    selection is read. Total.
    """
    with state.lock:
        entry = state.entries.get(key)
        if (isinstance(entry, dict)
                and entry.get("selection") in COMPAT_REASONING_SELECTIONS):
            return entry["selection"]
        return "none"


class _FeatureDescriptor(object):
    """One learnable feature: its mode scope, presence/complaint tests, entry
    validator, and retry budget."""

    def __init__(self, name, mode, present, complaint_match, validate_entry,
                 max_retries_per_request):
        self.name = name
        self.mode = mode
        self.present = present
        self.complaint_match = complaint_match
        self.validate_entry = validate_entry
        self.max_retries_per_request = max_retries_per_request


# The feature registry. At most one feature may claim a given mode: the
# `_feature_for_mode` lookup would otherwise be ambiguous (warned at startup).
COMPAT_FEATURES = {
    COMPAT_FEATURE: _FeatureDescriptor(
        name=COMPAT_FEATURE,
        mode="anthropic",
        present=_context_management_present,
        complaint_match=_compat_rejection_match,
        validate_entry=_compat_validate_context_management_entry,
        max_retries_per_request=COMPAT_MAX_RETRIES_PER_REQUEST,
    ),
    "reasoning_field": _FeatureDescriptor(
        name="reasoning_field",
        mode="chat",
        present=_reasoning_present,
        complaint_match=_reasoning_complaint_match,
        validate_entry=_compat_validate_reasoning_entry,
        max_retries_per_request=COMPAT_REASONING_MAX_RETRIES_PER_REQUEST,
    ),
}


def _feature_for_mode(mode):
    """The single registered feature whose mode scope matches, or None."""
    for descriptor in COMPAT_FEATURES.values():
        if descriptor.mode == mode:
            return descriptor
    return None
