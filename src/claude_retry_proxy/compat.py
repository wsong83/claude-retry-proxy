"""Compatibility learner for the Claude retry proxy: learns per-provider-key
unsupported-`context_management` behavior, strips the feature and retries on a
confirmed rejection, and persists learned state to the feature-compatibility
state file.

Persisted state is metadata-only; the 0o600 chmod is POSIX-only — Windows users
must restrict the state directory ACL manually.
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
# Feature compatibility learning (Anthropic mode, single feature)
# ---------------------------------------------------------------------------

# Maintainer-tunable policy constants (no user-facing configuration surface).
COMPAT_INITIAL_THRESHOLD = 32      # strips before first revalidation probe
COMPAT_PROBATION_THRESHOLD = 8     # strips between probation probes
COMPAT_BACKOFF_MULTIPLIER = 2      # threshold multiplier on repeated rejection
COMPAT_MAX_THRESHOLD = 4096        # maximum strip threshold
COMPAT_DELISTING_SUCCESSES = 2     # successful probes to delist
COMPAT_MAX_RETRIES_PER_REQUEST = 1 # maximum compatibility retries per client request
COMPAT_FAILED_CONFIRMATION_SUPPRESSION = 3  # failed confirmations before suppression

# The single learnable feature. Field names from upstream error bodies are
# compared against this constant and never copied into state keys, strip
# logic, or trace events.
COMPAT_FEATURE = "context_management"
COMPAT_FEATURE_MODE = "anthropic"
COMPAT_SCHEMA_VERSION = 1

COMPAT_STATE_UNSUPPORTED = "unsupported"
COMPAT_STATE_PROBATION = "probation"

# Owned compatibility state. The singleton `_state` is stored exactly once
# (module level, below) and never rebound; state-touching functions take a
# `state=_state` default parameter so explicit injection isolates state.
class _CompatState(object):
    """One feature's in-memory learned state: the four dicts plus both locks."""

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
        # Fast lock: protects entries / failed_confirmations and serializes
        # persistence I/O (built under the lock).
        self.lock = threading.Lock()
        # Slow-path lock: at most one in-flight compatibility retry/probe
        # globally. Acquired with blocking=False; held for the duration of the
        # upstream HTTP call; released in finally on every outcome.
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


def _compat_key(provider, mode, actual_model):
    """Build the in-memory state key for a learned entry."""
    return (provider, mode, actual_model, COMPAT_FEATURE)


def _compat_file_key(key):
    """Serialize a state key tuple for the persisted dict (unambiguous separator)."""
    return "\x1f".join(key)


def _compat_parse_file_key(key_str):
    return tuple(key_str.split("\x1f"))


def _compat_normalize_threshold(threshold):
    """Snap an arbitrary threshold onto the doubling ladder [initial, max].

    Returns the largest ladder element (initial * multiplier^k) that does not
    exceed min(threshold, max), floored at COMPAT_INITIAL_THRESHOLD.
    """
    t = COMPAT_INITIAL_THRESHOLD
    while t * COMPAT_BACKOFF_MULTIPLIER <= min(threshold, COMPAT_MAX_THRESHOLD):
        t *= COMPAT_BACKOFF_MULTIPLIER
    return t


def _compat_validate_entry(entry):
    """Validate one loaded state entry. Returns normalized entry or None."""
    if not isinstance(entry, dict):
        return None
    provider = entry.get("provider")
    mode = entry.get("mode")
    actual_model = entry.get("actual_model")
    feature = entry.get("feature")
    state = entry.get("state")
    threshold = entry.get("threshold")
    if not isinstance(provider, str) or not provider:
        return None
    if not isinstance(mode, str) or not mode:
        return None
    if not isinstance(actual_model, str) or not actual_model:
        return None
    if not isinstance(feature, str) or not feature:
        return None
    if feature != COMPAT_FEATURE:
        return None
    if state not in (COMPAT_STATE_UNSUPPORTED, COMPAT_STATE_PROBATION):
        return None
    if not isinstance(threshold, int) or isinstance(threshold, bool):
        return None
    strip_counter = entry.get("strip_counter", 0)
    probation_successes = entry.get("probation_successes", 0)
    failed_confirmations = entry.get("failed_confirmations", 0)
    for v in (strip_counter, probation_successes, failed_confirmations):
        if not isinstance(v, int) or isinstance(v, bool):
            return None
    return {
        "schema_version": COMPAT_SCHEMA_VERSION,
        "provider": provider,
        "mode": mode,
        "actual_model": actual_model,
        "feature": feature,
        "state": state,
        "threshold": _compat_normalize_threshold(threshold),
        # Counters are in-memory-only: restart resets them to zero
        # (fail-safe direction — over-stripping, never under-stripping).
        "strip_counter": 0,
        "probation_successes": 0,
        "failed_confirmations": 0,
    }


def _load_compat_state(state=_state):
    """Load learned compatibility state from SETTINGS.feature_compat_file.

    Missing file → empty state (no warning). Malformed/unreadable file →
    warn to stderr and fail open with empty state. Known schema version with
    invalid individual entries → drop bad entries, keep valid ones, warn per
    entry. Unknown feature keys → ignored (forward-compat).

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
    for key_str, entry in entries.items():
        if not isinstance(key_str, str):
            continue
        parsed = _compat_validate_entry(entry)
        if parsed is None:
            feature_name = entry.get("feature") if isinstance(entry, dict) else None
            if feature_name != COMPAT_FEATURE:
                # Unknown feature keys: ignore silently (forward-compat).
                continue
            print("[proxy] WARNING: dropping invalid compatibility state "
                  "entry (key redacted)", file=sys.stderr)
            continue
        loaded[_compat_parse_file_key(key_str)] = parsed
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
            "failed_confirmations": 0,
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
    try:
        data = json.loads(resp_body)
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
        return False
    if not isinstance(data, dict):
        return False
    return _compat_message_match(data) or _compat_structured_match(data)


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
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
        return None
    if not isinstance(stripped, dict):
        return None
    stripped.pop(COMPAT_FEATURE, None)
    return json.dumps(stripped).encode("utf-8")
