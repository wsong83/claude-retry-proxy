"""Upstream forward path for the Claude retry gateway.

Owns everything between "the client body has arrived" and "the upstream
response is returned": the transport and policy helpers, the retry loop, the
compatibility and reasoning retries, the response-rewrite helpers, and the
config-swap drain protocol's state. The chat retry-nudge marker store lives in
chat_nudge.py and is re-exported here. The parent module imports this one;
this module never imports its parent.
"""

import httpx2
import json
import math
import random
import re
import sys
import threading
import time

from urllib.parse import urlparse

from .compat import (COMPAT_FEATURE, COMPAT_FEATURES,
                     COMPAT_MAX_RETRIES_PER_REQUEST,
                     COMPAT_REASONING_SELECTIONS,
                     _compat_get, _compat_key, _compat_learn,
                     _compat_merge_retries, _compat_note_suppressed_request,
                     _compat_probe_inconclusive, _compat_probe_rejected,
                     _compat_probe_success, _compat_record_failed_confirmation,
                     _compat_record_strip, _compat_rejection_match,
                     _compat_reset_strip_counter, _compat_retry_lock,
                     _compat_stripped_body, _compat_suppressed,
                     _feature_for_mode, _reasoning_advance_selection,
                     _reasoning_credit_on_2xx, _reasoning_credit_on_complaint,
                     _reasoning_entry_selection, _reasoning_next_candidate)
from .config import reasoning_roundtrip_models, reasoning_switch_params
from .keys import vendor_key_entries
from .nesting import check_payload_nesting, nesting_event
from .sanitize import sanitize_error
from .settings import SETTINGS
from .chat_nudge import (_retry_nudge_arm, _retry_nudge_check,
                         _retry_nudge_messages_bytes, _retry_nudge_remember,
                         RETRY_NUDGE_TTL_SECONDS)
from .sinks import increment_retried, log_trace
from .transforms_chat import _anthropic_to_chat, _chat_to_anthropic
from .transforms_common import _sanitize_body_tools, _transform_and_guard
from .transforms_response import _anthropic_to_response, _response_to_anthropic


# Client-disconnect errors: raised when the client closed the connection
# before we finished writing the response (e.g. it timed out during a long
# retry storm). These are expected under load; we log a single line and a
# trace event instead of letting socketserver print a traceback per request.
# ConnectionAbortedError covers Windows WinError 10053; ConnectionResetError
# covers WinError 10054 and POSIX ECONNRESET; BrokenPipeError covers POSIX EPIPE.
_DISCONNECT_ERRORS = (ConnectionResetError, BrokenPipeError, ConnectionAbortedError)


# Thread-safe config access (read by worker threads, written by admin API)
_config_lock = threading.RLock()


# Drain-and-swap state for config changes (prevents race with in-flight requests)
_inflight_count = 0  # Number of requests currently in-flight
_config_swapping = False  # True when config swap is in progress
_swap_done = threading.Event()  # Signaled when swap completes
_config_epoch = 0  # Incremented on every successful config swap
_last_upstream_activity = 0.0  # Timestamp of the most recent upstream byte, any request
_swap_started_at = None  # Timestamp of the current press; None when no swap runs
_swap_evictions = 0  # Evictions since the last press; `drained` == 0 of them

# The drain's total-quiet window exceeds the armed stream wake (both keyed to
# the same shared clock) by this margin, so an evictable straggler is always
# evicted before the drain exits and `drained` stays a fact rather than a race.
_SWAP_QUIET_GRACE = 2.0


# Thread-local RNG — the module-global random is not thread-safe under
# ThreadingHTTPServer worker threads (Mersenne Twister state is shared).
_rng_local = threading.local()

def _rng():
    """Per-thread random.Random instance, lazily created."""
    r = getattr(_rng_local, "rng", None)
    if r is None:
        r = random.Random()
        _rng_local.rng = r
    return r


# ---------------------------------------------------------------------------
# Config-swap drain helpers
# ---------------------------------------------------------------------------
#
# The drain replaces the old wall-clock deadline: new admissions pause (the
# existing _config_swapping gate) while the drain waits for the in-flight set
# to empty on count alone, or for the SHARED activity clock to read total
# quiet for a full budget plus _SWAP_QUIET_GRACE. Retry-backoff chains abandon
# at the press instead of being waited out, and silent stragglers are evicted
# with a retryable config_swap_restart once the epoch bumps.
#
# ACCEPTED RISK: an unbounded drain blocks every new admission for as long as
# it runs (forward_request waits on _swap_done with no timeout). The escape
# hatches are `claude-retry-proxy stop` (kills the process) and
# POST /admin/shutdown (never checks _config_swapping); nothing else releases
# writers. The residual scenario that never terminates is an upstream that is
# stuck but keeps sending bytes, keeping the clock fresh forever. Rollback for
# this design is `git revert` of its commit plus a restart — there is no env
# var that restores the old bounded drain (PROXY_SWAP_SILENCE_TIMEOUT tunes
# the budget; it cannot re-introduce the 30 s wall-clock abort).

def _touch_upstream_activity():
    """Record the most recent upstream byte from any in-flight request.

    The drain reads this single shared clock to decide when everything left
    is silent. A bare store with no lock: a stale read only makes the drain
    wait marginally longer, and one assignment cannot tear under the GIL.
    """
    global _last_upstream_activity
    _last_upstream_activity = time.time()


def _drain_for_swap():
    """Pause admissions and wait for in-flight work to drain (Phases 1-2).

    Single-flight: the guard and the press share ONE lock acquisition, so a
    second press arriving at any point cannot pass — there is no window
    between deciding and pressing in which a concurrent press could slip
    through. Returns None when a swap is already in progress; the caller
    returns its 409 refusal and enters no drain. Otherwise returns
    (drained, inflight_at_press, waited_s):
      - `drained` is `_swap_evictions == 0` — "nothing was evicted", NOT
        "the count reached zero". A post-press eviction can decrement the
        count before the poll sees it, so keying on the exit branch would
        make the field a race rather than a fact.
      - `inflight_at_press` is the count at the press, independent of which
        exit fires.
      - `waited_s` is the drain wall-clock.

    Two exits, both by construction safe: count zero (everything left the
    set), or no upstream byte from anyone for budget + _SWAP_QUIET_GRACE —
    at which point every remaining request is silent >= budget, because the
    clock resets on ANY byte. No wall-clock total: live work is waited to
    completion however long it takes.

    OPERATIONAL NOTE — the accepted risk this creates: while this drain runs,
    every new admission is blocked (forward_request waits on _swap_done with
    no timeout). The immediate escapes are `claude-retry-proxy stop` (kills
    the process) and `POST /admin/shutdown` (never checks _config_swapping);
    nothing else releases writers. The systemic escape is reverting this
    change (`git revert` of its commit) plus a restart:
    PROXY_SWAP_SILENCE_TIMEOUT tunes the budget only — no env var restores
    the old bounded drain.
    """
    global _config_swapping, _swap_started_at, _swap_evictions, _last_upstream_activity
    with _config_lock:
        if _config_swapping:
            # Single-flight refusal: an owner already holds the swap. Taken
            # under the SAME acquisition that sets the flag below, so the
            # check-then-act window that let two presses both enter a drain
            # is gone.
            return None
        _config_swapping = True
        _swap_done.clear()
        started_at = time.time()
        _last_upstream_activity = started_at
        _swap_started_at = started_at
        inflight_at_press = _inflight_count
        _swap_evictions = 0
    quiet_window = SETTINGS.swap_silence_timeout + _SWAP_QUIET_GRACE
    while True:
        with _config_lock:
            inflight = _inflight_count
            last_activity = _last_upstream_activity
            evictions = _swap_evictions
        if inflight == 0:
            break
        if time.time() - last_activity >= quiet_window:
            break
        time.sleep(0.1)
    return evictions == 0, inflight_at_press, time.time() - started_at


def _note_swap_eviction(phase, request_id, **fields):
    """Count one eviction and log its swap_abort trace event.

    Called immediately before an evicted request returns its retryable
    error. The stream phase carries tier + provider and no model — the
    stream helpers do not receive actual_model.
    """
    global _swap_evictions
    with _config_lock:
        _swap_evictions += 1
    event = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "event": "swap_abort",
        "phase": phase,
        "request_id": request_id,
    }
    event.update(fields)
    log_trace(event)


def _swap_epoch_changed(entry_epoch):
    """True when a swap completed after this request was admitted.

    Such a request must never deliver an old-routing result. Reads the
    epoch without the lock — a single int read is atomic under the GIL,
    and a stale read only defers the eviction to the next checkpoint.
    """
    return entry_epoch is not None and _config_epoch != entry_epoch


def _swap_chain_abort(entry_epoch):
    """True when a retry-backoff chain must abandon toward the left provider.

    Chains additionally abandon at the press, not only at the completed
    swap: they are proxy-managed idling with no generation work, and
    waiting them out is what made a swap issued under rate limiting fail.
    """
    return _config_swapping or _swap_epoch_changed(entry_epoch)


def _interruptible_sleep(seconds, epoch):
    """Sleep up to `seconds`, in slices, aborting on a swap press.

    Returns True when the chain must abandon (a swap started at any point
    during the wait), False when the full delay elapsed normally.
    """
    deadline = time.time() + seconds
    while True:
        if _swap_chain_abort(epoch):
            return True
        remaining = deadline - time.time()
        if remaining <= 0:
            return False
        time.sleep(min(0.25, remaining))


def _swap_abort_tuple(request_id, total_start, retries, tier, provider_name,
                      actual_model):
    """The retryable give-up result for a request evicted by a config swap.

    Mirrors the 429/503 give-up return-tuple shape exactly (nine elements,
    empty headers, no streamed body), so do_POST's streamed flag and
    _send_response handle it identically.
    """
    return (503, {}, _error_body(
        "api_error", "config_swap_restart",
        "config swap in progress: this request was restarted; the client should retry",
        request_id),
        None, time.time() - total_start, retries, tier, provider_name, actual_model)


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


# Whitelisted paths and methods
ALLOWED_PATH_RE = re.compile(r"^/v1/")
ALLOWED_METHODS = {"POST", "OPTIONS"}

# Headers forwarded to upstream
FORWARD_HEADERS = {"authorization", "x-api-key", "content-type",
                   "anthropic-version", "accept", "anthropic-beta",
                   "user-agent"}


# ---------------------------------------------------------------------------
# Upstream URL parsing
# ---------------------------------------------------------------------------

def parse_upstream(url):
    """Parse upstream URL into (host, port, use_ssl, path_prefix). Returns None on failure."""
    if not url:
        return None
    try:
        parsed = urlparse(url)
        host = parsed.hostname
        if not host:
            return None
        # urlparse defers the port check to attribute access, so an
        # out-of-range or non-numeric port raises here rather than at the
        # urlparse call; a malformed IPv6 authority raises out of urlparse.
        port = parsed.port
    except ValueError:
        return None
    if parsed.scheme == "https":
        port = port or 443
        use_ssl = True
    elif parsed.scheme == "http":
        port = port or 80
        use_ssl = False
    else:
        return None
    path_prefix = parsed.path.rstrip("/") if parsed.path else ""
    return (host, port, use_ssl, path_prefix)


def resolve_api_key(vendor, tier_config):
    """Resolve the (payload, name) for a request against a tier config.

    Exact-name match on a non-empty string tier_config["key"]; any other
    selection (absent/None/""/non-string, or a non-dict tier_config) falls
    back to the first entry. Total and pure.
    """
    entries = vendor_key_entries(vendor)
    if isinstance(tier_config, dict):
        selected = tier_config.get("key")
        if isinstance(selected, str) and selected:
            for name, payload in entries:
                if name == selected:
                    return (payload, name)
    return (entries[0][1], entries[0][0])


def compute_delay(attempt):
    """Exponential backoff: 2^attempt seconds, capped at SETTINGS.max_delay."""
    delay = SETTINGS.initial_delay * (2 ** attempt)
    return min(delay, SETTINGS.max_delay)


def compute_jittered_delay(base):
    """±25% uniform jitter on base, unbiased half-up rounded to an integer second, floored at 0.

    Uses floor(x + 0.5), NOT round(): Python 3 round() is banker's rounding,
    which collapses small even base values to a constant.
    """
    if base <= 0:
        return 0
    jitter = _rng().uniform(-0.25, 0.25) * base
    return max(0, math.floor(base + jitter + 0.5))


def _read_capped(resp, max_bytes, request_id=None):
    """Read up to max_bytes from resp. Truncate past the cap with a marker.

    Drains the response body so the connection can be closed cleanly, but
    bounds memory: if the body exceeds max_bytes, stop reading and return a
    standalone truncation marker. Returns the full body unchanged if it fits
    within max_bytes.

    ONE raw iterator serves both the capped read and the drain-and-discard:
    an httpx2 response stream is single-consumption (a second iter_raw raises
    StreamConsumed), so the cap crossing is handled inside a single loop with
    a discard flag. iter_raw delivers the entity bytes undecoded, and the
    slice preserves the never-overshoot truncation guarantee of a capped read.
    """
    if max_bytes <= 0:
        return b''
    chunks = []
    total = 0
    # Track whether we actually read tail data to distinguish "exactly at
    # cap" from "truncated".
    truncated = False
    try:
        for chunk in resp.iter_raw():
            _touch_upstream_activity()
            if truncated:
                continue
            if total < max_bytes:
                keep = chunk[:max_bytes - total]
                chunks.append(keep)
                total += len(keep)
                if len(keep) < len(chunk):
                    truncated = True
            else:
                truncated = True
    except (httpx2.RequestError, OSError):
        pass
    if truncated:
        # error.type tracks the status this body is returned under, so a
        # rate-limit/overload give-up keeps its taxonomy category.
        if resp.status_code == 429:
            err_type = "rate_limit_error"
        elif resp.status_code == 503:
            err_type = "overloaded_error"
        else:
            err_type = "api_error"
        return _error_body(err_type, "upstream_body_truncated",
                           "[proxy: response body truncated]", request_id)
    return b"".join(chunks)


def _compat_probe_outcome(result, key, request_id, tier, method, path,
                          headers, body, handler, config, vendors, epoch,
                          retry_original_id=None):
    """Process an unstripped probe response under the state machine.

    2xx records a probation success (evidence recorded at status receipt;
    mid-stream failures do not roll back). The same exact 400 doubles the
    threshold and returns the stripped retry result. Anything else is
    inconclusive. The caller owns _compat_retry_lock. retry_original_id is
    forwarded unchanged to the stripped retry, so the entry-time marker
    decision (loop guard + nudge) survives the re-entry. epoch rides along
    unchanged too, so a compat re-issue inside one client request stays on
    one logical snapshot.
    """
    status = result[0]
    if 200 <= status < 300:
        _compat_probe_success(key, request_id, tier)
        return result
    if status == 400 and _compat_rejection_match(status, result[2]):
        _compat_probe_rejected(key, request_id, tier)
        stripped_body = _compat_stripped_body(body)
        if stripped_body is None:
            return result
        for _attempt in range(COMPAT_MAX_RETRIES_PER_REQUEST):
            retry_result = _forward_request_impl(
                method, path, headers, stripped_body, handler, request_id,
                config, vendors, epoch, suppress_compat=True,
                retry_original_id=retry_original_id)
            return _compat_merge_retries(result, retry_result)
        return result
    _compat_probe_inconclusive(key, request_id, tier)
    return result


def _reasoning_rescue(result, selection, request_id, tier, provider_name,
                      actual_model, mode, method, path, headers, body, handler,
                      config, vendors, epoch, retry_original_id=None):
    """Re-roll a matched reasoning_field complaint, lock-free and key-free.

    Every rescue pass re-enters the forward path from the ORIGINAL client body
    with the feature suppressed, so it is a single upstream attempt that can
    never recurse into this function. Up to the descriptor's budget of passes
    cycle the candidate from the selection the request actually sent, and each
    pass emits one metadata-only ``reasoning_rescue`` event.

    Merge semantics: ``_compat_merge_retries(A, B)`` returns B's fields with
    the two retry counts summed, so a 2xx pass is served as
    ``_compat_merge_retries(result, pass_result)`` while a non-complaint pass
    and budget exhaustion hand the client attempt 1's ORIGINAL error as
    ``_compat_merge_retries(pass_result, result)``. A rescue pass that hits
    429/503 is such a non-complaint (one attempt under suppress_compat): the
    rescue stops and attempt 1's error is served. Rescues teach nothing and
    persist nothing; ``selection`` may be None (an unparseable body never
    resolved), in which case the first candidate is "none".

    Every pass forces the always-present field on, so a complaining provider
    that is not flagged in models.json repairs itself without a config edit.
    The candidate cycle still lands on "none", which has no field name to
    write: such a pass sends the entry's current selection for its field (or
    ``reasoning_content`` when that is also none) and reports the field it
    actually used as ``effective_field`` beside ``candidate``.
    """
    feature = COMPAT_FEATURES["reasoning_field"]
    rescue_result = result
    candidate = selection
    for attempt in range(1, feature.max_retries_per_request + 1):
        candidate = _reasoning_next_candidate(candidate)
        effective_field = candidate
        if candidate == "none":
            # A "none" candidate has no field name to write. Fall back to the
            # selection this request sent (the entry's current selection, read
            # at request entry — keeps this path lock-free and key-free), or
            # reasoning_content when that is also none.
            effective_field = (selection
                               if selection in COMPAT_REASONING_SELECTIONS
                               else "reasoning_content")
        rescue_result = _forward_request_impl(
            method, path, headers, body, handler, request_id,
            config, vendors, epoch, suppress_compat=True,
            reasoning_selection=effective_field, reasoning_always=True,
            retry_original_id=retry_original_id)
        rescue_status = rescue_result[0]
        if 200 <= rescue_status < 300:
            outcome = "served"
        elif feature.complaint_match(rescue_status, rescue_result[2]):
            outcome = "complaint"
        else:
            outcome = "other"
        log_trace({
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "event": "reasoning_rescue",
            "request_id": request_id,
            "provider": provider_name,
            "mode": mode,
            "actual_model": actual_model,
            "tier": tier,
            "feature": feature.name,
            "attempt": attempt,
            "candidate": candidate,
            "effective_field": effective_field,
            "outcome": outcome,
            "http_status": rescue_status,
        })
        if outcome == "served":
            return _compat_merge_retries(result, rescue_result)
        if outcome == "other":
            return _compat_merge_retries(rescue_result, result)
    return _compat_merge_retries(rescue_result, result)


def _resolve_extra_request_headers(headers, provider_name, config, request_id):
    """Resolve outbound extra request headers for a provider from config rules.

    Pure helper — no globals. Total: unexpected shapes (missing top-level key,
    unknown/None provider, malformed rules, non-string fields, request_id None
    with the token fallback) degrade to a skipped rule / {}; never raises.
    Config validation is the strict gate; this is defense-in-depth, not a
    second gate.

    Inbound `from` names are matched case-insensitively over a plain dict
    (both call sites pass plain dicts, so we compare k.lower() ourselves);
    the first non-empty stripped value wins and the emitted value is the
    stripped value. `fallback` is a literal string or the exact case-sensitive
    token "request_id", which resolves to the `request_id` argument (None
    yields nothing for that rule). Rules whose resolved value contains CR/LF
    are skipped.
    """
    if not provider_name or not isinstance(config, dict):
        return {}
    extra = config.get("extra_request_headers")
    if not isinstance(extra, dict):
        return {}
    rules = extra.get(provider_name)
    if not isinstance(rules, list):
        return {}
    inbound = {}
    for k, v in headers.items():
        if isinstance(k, str):
            lk = k.lower()
            if lk not in inbound:
                inbound[lk] = v
    resolved = {}
    for spec in rules:
        if not isinstance(spec, dict):
            continue
        header = spec.get("header")
        if not isinstance(header, str) or not header:
            continue
        value = None
        from_list = spec.get("from")
        if isinstance(from_list, list):
            for name in from_list:
                if not isinstance(name, str):
                    continue
                candidate = inbound.get(name.lower())
                if candidate is None:
                    continue
                stripped = candidate.strip() if isinstance(candidate, str) else None
                if stripped:
                    value = stripped
                    break
        if value is None:
            fallback = spec.get("fallback")
            if isinstance(fallback, str):
                if fallback == "request_id":
                    if request_id is not None:
                        value = request_id
                elif fallback.strip():
                    value = fallback.strip()
        if value is None:
            continue
        if "\r" in value or "\n" in value:
            continue
        resolved[header] = value
    return resolved


# --- the client User-Agent on the request trace entry ------------------------
# The proxy forwards the client's User-Agent upstream, so a UA-based edge
# refusal (Cloudflare's `1010` browser-signature block) is only legible next to
# the UA that produced it. This field records that value -- the last one the
# forwarding path sends -- never rewritten, so it names the INBOUND string,
# unlike `extra_request_headers`, which records resolved OUTBOUND values. A UA
# is client-controlled and otherwise unbounded, so it is capped, visibly.
CLIENT_USER_AGENT_MAX_CHARS = 512
CLIENT_USER_AGENT_TRUNCATION_MARKER = "[proxy: user-agent truncated]"

TRACE_MODEL_MAX_CHARS = 512
TRACE_MODEL_TRUNCATION_MARKER = "[proxy: model truncated]"


def _client_user_agent(headers):
    """The User-Agent the proxy forwards, capped; None when absent or empty.

    `headers` is the request's header mapping -- an `email.message.Message`,
    whose keys keep the casing the client sent. The parser strips a header's
    leading whitespace and normalizes a whitespace-only header to "", so such a
    header is omitted rather than recorded as blank; a non-empty value keeps its
    trailing whitespace.

    Resolution MIRRORS THE FORWARDING PATH, because the field exists to name the
    UA that produced an upstream refusal, so a value the upstream never received
    is worse than no value at all. `do_POST` hands `forward_request` a plain dict
    built from `self.headers.items()`, and the upstream transport then sends
    that dict in order (httpx2 puts each key on one wire line): same-cased
    duplicates collapse to the last value (the single line the
    upstream receives), while differently-cased ones survive as separate keys
    and put two lines on the wire. Taking the collapse's last value names the
    last UA line forwarded. When the request carried one casing -- the ordinary
    case, and the only one in which a single value is a well-defined mirror --
    that is exactly the line on the wire.

    No sanitizing: the value IS the diagnostic, and `sanitize_error` exists for
    error text (it redacts home-directory paths and IPv4 literals and caps at
    200 chars), none of which applies to a UA.

    A value longer than the cap keeps its head -- the informative prefix, e.g.
    "Python-urllib/3.11" -- and gains a visible marker, so a truncated UA is
    never mistaken for a genuine one. The result is at most
    CLIENT_USER_AGENT_MAX_CHARS characters; `http.server` decodes header values
    as latin-1, so one character is one byte and that is also the byte bound.
    """
    forwarded = {k: v for k, v in headers.items() if k.lower() == "user-agent"}
    values = list(forwarded.values())
    value = values[-1] if values else None
    if not value:
        return None
    if len(value) <= CLIENT_USER_AGENT_MAX_CHARS:
        return value
    keep = CLIENT_USER_AGENT_MAX_CHARS - len(CLIENT_USER_AGENT_TRUNCATION_MARKER)
    return value[:keep] + CLIENT_USER_AGENT_TRUNCATION_MARKER


def _trace_model(actual_model, model):
    """The model name recorded on the request trace entry, capped.

    The resolved tier name (config-controlled, short) wins; the fallback
    is the raw client-supplied string -- unbounded client text of the
    same class _client_user_agent bounds. A value longer than the cap
    keeps its head and gains a visible marker, so a truncated model name
    is never mistaken for a genuine one; the body-size cap bounds the
    raw input, this bounds its at-rest record.
    """
    value = actual_model or model or "unknown"
    if len(value) <= TRACE_MODEL_MAX_CHARS:
        return value
    keep = TRACE_MODEL_MAX_CHARS - len(TRACE_MODEL_TRUNCATION_MARKER)
    return value[:keep] + TRACE_MODEL_TRUNCATION_MARKER


def _forward_request_impl(method, path, headers, body, handler, request_id,
                          config, vendors, epoch, suppress_compat=False,
                          reasoning_selection=None, retry_original_id=None,
                          reasoning_always=False):
    """Internal implementation of forward_request with snapshot config.

    epoch is the config generation snapshotted at admission. It is required
    (no default) at every site that checks it: a missed call site must fail
    loudly at import/run time, never silently disable the swap guards.

    suppress_compat=True bypasses the feature-compatibility subsystem
    entirely — compatibility retries call this function with the flag set,
    so recursion is structurally impossible and the retry is a single
    upstream attempt (never re-enters the 429/503 retry loop).

    reasoning_selection is the chat-mode reasoning echo field. None means
    "unresolved — resolve it from the learned entry at request entry"; every
    other value (including the literal "none") is used as-is, so a rescue
    pass's explicit candidate is never re-resolved.

    reasoning_always forces the always-present field behavior on for this
    pass (the reasoning_roundtrip policy at the top level, the repair on a
    rescue pass).

    retry_original_id is the marker decision resolved once by the
    eligibility gate below — the single resolution point, which runs only
    for eligible requests: a non-None parent value (inherited from a
    compat/reasoning re-entry) is honored as-is — never re-resolved — so
    the re-entered forward keeps the loop guard and the nudge; None (a
    top-level forward_request call) resolves at that gate.
    """
    if method not in ALLOWED_METHODS:
        return 400, {}, _error_body("invalid_request_error", "method_not_allowed",
                                    "Method not allowed", request_id), \
            0, 0, 0, "unknown", None, None

    if not ALLOWED_PATH_RE.match(path):
        return 400, {}, _error_body("invalid_request_error", "path_not_allowed",
                                    "Path not allowed", request_id), \
            0, 0, 0, "unknown", None, None

    if body and len(body) > SETTINGS.max_body_size:
        return 413, {}, _error_body("request_too_large", "payload_too_large",
                                    "Payload too large", request_id), \
            0, 0, 0, "unknown", None, None

    # Resolve tier from model name
    model_name, body_error = extract_model(body)
    if body_error is not None:
        # Body-shape rejection, before tier resolution: the two new codes
        # Step 3 of the envelope plan adds on a path that had no response.
        if body_error == "invalid_body_type":
            message = "Request body must be a JSON object"
        else:  # "invalid_json"
            message = "Request body is not valid JSON"
        return 400, {}, _error_body("invalid_request_error", body_error,
                                    message, request_id), \
            0, 0, 0, "unknown", None, None
    tier = resolve_tier(model_name, config)

    if tier == "unknown":
        # Unknown model - reject with 400 listing valid tiers
        # List in plan-specified order: haiku, sonnet, opus
        valid_tiers = [t for t in ("haiku", "sonnet", "opus") if t in config.get("tiers", {})]
        err_msg = "Unrecognized model: {}. Valid tiers: {}".format(
            model_name, ", ".join(valid_tiers))
        return 400, {}, _error_body("invalid_request_error", "unrecognized_model",
                                    err_msg, request_id), \
            0, 0, 0, "unknown", None, None

    # Look up provider and upstream info
    tier_config = config["tiers"][tier]
    provider_name = tier_config["provider"]
    actual_model = tier_config["model"]
    vendor = vendors[provider_name]
    upstream_url = vendor["url"]
    api_key, key_name = resolve_api_key(vendor, tier_config)

    if not api_key:
        # Degenerate resolution (defense-in-depth behind the load gate — e.g.
        # a string-form "key": "" vendor): fail clearly rather than emitting
        # an empty/x-api-key: None header upstream.
        return 500, {}, _error_body(
            "api_error", "invalid_provider_key",
            "Provider '{}' has no usable API key configured".format(provider_name),
            request_id), 0, 0, 0, tier, provider_name, actual_model

    # Read endpoint mode (None/''/missing normalize to "anthropic")
    mode = vendor.get("mode") or "anthropic"
    if mode not in SETTINGS.mode_values:
        return 500, {}, _error_body(
            "api_error", "invalid_provider_mode",
            "Provider '{}' has invalid mode '{}'. Valid modes: {}".format(
                provider_name, mode, ", ".join(SETTINGS.mode_values)),
            request_id), 0, 0, 0, tier, provider_name, actual_model

    if mode != "anthropic":
        log_trace({
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "event": "mode_dispatch",
            "request_id": request_id,
            "tier": tier,
            "provider": provider_name,
            "mode": mode,
            "key": key_name,
        })

    # Parse upstream URL
    parsed = parse_upstream(upstream_url)
    if parsed is None:
        return 500, {}, _error_body(
            "api_error", "invalid_provider_url",
            "Provider '{}' has invalid URL: {}".format(provider_name, upstream_url),
            request_id), 0, 0, 0, tier, provider_name, actual_model

    host, port, use_ssl, path_prefix = parsed

    # count_tokens has no equivalent on the OpenAI endpoints — reject it for
    # chat/response modes gated on the same tolerant path check used below.
    _is_count_tokens = path.split("?", 1)[0].rstrip("/").endswith(
        "/messages/count_tokens")
    if mode != "anthropic" and _is_count_tokens:
        return 400, {}, _error_body(
            "invalid_request_error", "count_tokens_unsupported",
            "count_tokens not supported in chat/response mode",
            request_id), 0, 0, 0, tier, provider_name, actual_model

    # Parse the request body once. Unparseable bodies skip compatibility
    # logic entirely (the transform below falls back to the original body).
    body_json = None
    if body:
        try:
            body_json = json.loads(body)
        except Exception:  # total per compat._compat_guarded_parse (RecursionError is not a ValueError)
            body_json = None
    # Whether the client declared tools: the denominator that makes
    # chat_sse_drain.emitted_tool_use interpretable, and the input the
    # unfinished-turn detector evaluates at its own decision point.
    _tools = body_json.get("tools") if isinstance(body_json, dict) else None
    tools_declared = isinstance(_tools, list) and bool(_tools)

    # Retry-nudge markers: remember every eligible chat request first (it
    # no-ops on an id already stored — a compat/reasoning re-entry — and the
    # fresh entry is unarmed, so check cannot match this request against
    # itself). This gate is the single resolution point: the check runs
    # only here, for eligible requests — an ineligible request (another
    # mode, no declared tools, or count_tokens, rejected above) never
    # consumes a marker, and it drops any inherited value. A non-None
    # value from a re-entered forward is honored as-is — never re-resolved
    # — so the re-entry keeps the loop guard and the nudge. The id threads
    # to the stream function, where it gates the unfinished-turn error
    # (loop guard) and tags the passthrough.
    if mode == "chat" and tools_declared and SETTINGS.chat_retry_nudge:
        _retry_nudge_remember(request_id, body, body_json)
        if retry_original_id is None:
            retry_original_id = _retry_nudge_check(body, body_json)
    else:
        retry_original_id = None

    # Build request body once before the retry loop (never re-transformed per
    # attempt). Anthropic mode does a model-only rewrite (plus learned
    # conditional stripping of the compatibility feature); chat/response modes
    # run the full body transform. On any failure fall back to the original
    # body and log a transform_failure trace event.
    rewritten_body = body
    compat_decision = None  # None | ("strip", key) | ("probe", key)
    compat_outbound_present = False
    active_feature = _feature_for_mode(mode)
    reasoning_key = None
    reasoning_active = False
    # Reasoning-field_switch policy, resolved once from this request's config
    # snapshot (the same snapshot every forwarding pass below uses), plus the
    # reasoning_roundtrip policy's flagged provider/model pairs.
    s_max, s_sw = reasoning_switch_params(config)
    roundtrip_pairs = reasoning_roundtrip_models(config)
    if body:
        try:
            body_json["model"] = actual_model
            # Compatibility gate: Anthropic mode only, single learnable
            # feature present at top level in the parsed body, never on
            # compatibility retries, count_tokens excluded.
            if (mode == "anthropic" and not _is_count_tokens
                    and not suppress_compat and isinstance(body_json, dict)
                    and COMPAT_FEATURE in body_json):
                _ck = _compat_key(provider_name, mode, actual_model, COMPAT_FEATURE)
                if _compat_get(_ck) is not None:
                    reached = _compat_record_strip(_ck)
                    if reached and _compat_retry_lock.acquire(blocking=False):
                        # Probe owner: send the unstripped body. Counter
                        # resets to 0 at probe start; strips concurrent with
                        # an in-progress probe count toward the next threshold.
                        _compat_reset_strip_counter(_ck)
                        log_trace({
                            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                            "event": "compatibility_probe_started",
                            "request_id": request_id,
                            "provider": provider_name,
                            "mode": mode,
                            "tier": tier,
                            "actual_model": actual_model,
                            "feature": COMPAT_FEATURE,
                        })
                        compat_decision = ("probe", _ck)
                    else:
                        body_json.pop(COMPAT_FEATURE, None)
                        log_trace({
                            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                            "event": "compatibility_field_stripped",
                            "request_id": request_id,
                            "provider": provider_name,
                            "mode": mode,
                            "tier": tier,
                            "actual_model": actual_model,
                            "feature": COMPAT_FEATURE,
                        })
                        compat_decision = ("strip", _ck)
            # The active feature's presence test gates learning eligibility
            # (reasoning_active) and the anthropic discovery below. None-safe:
            # a mode with no registered feature is inert.
            compat_outbound_present = (
                active_feature is not None
                and active_feature.present(body_json))
            if mode == "chat":
                # Gate-free selection: the rescue needs the sent selection even
                # when the body carries no thinking block, so presence gates
                # learning only. Re-entry safety is structural — a re-entry
                # always carries an explicit selection, and suppress_compat
                # excludes the block as well.
                if (reasoning_selection is None and active_feature is not None
                        and not suppress_compat and not _is_count_tokens):
                    reasoning_key = _compat_key(
                        provider_name, mode, actual_model, active_feature.name)
                    reasoning_selection = \
                        _reasoning_entry_selection(reasoning_key)
                    reasoning_active = compat_outbound_present
                if reasoning_selection is None:
                    reasoning_selection = "none"
                # Nudge injection: this request matched an armed marker, so
                # append the config-texted nudge as a trailing user message
                # to the parsed copy only — the client's bytes are never
                # modified and the client response never carries the nudge.
                # The transform stays the single mapping authority (it runs
                # on the mutated copy below, so the shape is real at the
                # wire). Guarded on messages being a list; the match itself
                # guarantees one exists.
                if (retry_original_id is not None
                        and isinstance(body_json.get("messages"), list)):
                    body_json["messages"].append({
                        "role": "user",
                        "content": [{"type": "text",
                                     "text": SETTINGS.chat_retry_nudge}],
                    })
                # The OR is load-bearing: the policy flags this (provider,
                # model) pair, and a rescue pass flags itself. A literal
                # policy lookup would make every rescue pass inert.
                _pair = "{}/{}".format(provider_name, actual_model)
                rewritten_body = json.dumps(_anthropic_to_chat(
                    body_json, request_id=request_id, mode=mode,
                    provider=provider_name, tier=tier,
                    reasoning_selection=reasoning_selection,
                    reasoning_always=reasoning_always or _pair in roundtrip_pairs)).encode("utf-8")
                if retry_original_id is not None:
                    # Post-transform, inside the successful-build branch: a
                    # transform failure falls back to the client's original
                    # bytes, and the event must never claim a nudge the
                    # upstream did not see.
                    log_trace({
                        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        "event": "chat_retry_nudge",
                        "request_id": request_id,
                        "original_request_id": retry_original_id,
                        "tier": tier,
                        "provider": provider_name,
                        "key": key_name,
                    })
            elif mode == "response":
                rewritten_body = json.dumps(_anthropic_to_response(
                    body_json, request_id=request_id, mode=mode,
                    provider=provider_name, tier=tier)).encode("utf-8")
            else:
                rewritten_body = json.dumps(_sanitize_body_tools(body_json)).encode("utf-8")
        except Exception:  # total per compat._compat_guarded_parse (RecursionError is not a ValueError)
            log_trace({
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "event": "transform_failure",
                "request_id": request_id,
                "provider": provider_name,
                "tier": tier,
                "mode": mode,
            })
            # The fallback forwards the untransformed client body, so this
            # request is learning-ineligible (no credit, no key use).
            reasoning_active = False
            rewritten_body = body  # Keep original body if transform/parse fails

    # Build headers for forwarding
    fwd_headers = {}
    for k, v in headers.items():
        if k.lower() in FORWARD_HEADERS:
            # Skip authorization and x-api-key (we inject provider's key)
            if k.lower() in ("authorization", "x-api-key"):
                continue
            fwd_headers[k] = v
    # Inject provider's API key per mode
    if mode == "anthropic":
        fwd_headers["x-api-key"] = api_key
    else:
        fwd_headers["Authorization"] = "Bearer {}".format(api_key)

    # Apply config-driven extra request headers. Runs here, after the
    # per-mode key injection and outside the retry loop, so injected auth
    # wins by construction (validate_config rejects reserved names) and the
    # resolved value is stable across 429/503 retries.
    for _header_name, _header_value in _resolve_extra_request_headers(
            headers, provider_name, config, request_id).items():
        fwd_headers[_header_name] = _header_value

    # httpx2 would send its own accept-encoding set by default; identity is
    # pinned as defence-in-depth (the stdlib transport sent identity too, so
    # this preserves the wire state). Correctness does not rest on it: read
    # sites use iter_raw(), which is byte-faithful regardless of the
    # response's Content-Encoding. Config cannot override the pin:
    # RESERVED_EXTRA_HEADER_NAMES reserves the name.
    fwd_headers["Accept-Encoding"] = "identity"

    # Dispatch upstream path per mode. chat/response modes strip a trailing
    # /v1 from the configured base URL so an OpenAI-style base does not
    # produce a doubled /v1/v1/ prefix.
    if mode == "anthropic":
        upstream_path = path_prefix + path if path_prefix else path
    else:
        if path_prefix.endswith("/v1"):
            path_prefix = path_prefix[:-3]
        endpoint = "/v1/chat/completions" if mode == "chat" else "/v1/responses"
        upstream_path = path_prefix + endpoint

    # Accepted residual (review finding 6): an exotic non-_DISCONNECT
    # client-write OSError during a streamed 2xx probe can re-issue the probe
    # POST after headers were sent; bounded to one spurious threshold doubling,
    # self-heals on the next probe cycle. Documented in CLAUDE.md Gotchas.
    compat_owned = compat_decision is not None and compat_decision[0] == "probe"
    if compat_owned:
        try:
            result = _forward_core(
                method, path, handler, request_id, config, rewritten_body,
                fwd_headers, upstream_path, host, port, use_ssl, tier,
                provider_name, actual_model, mode, _is_count_tokens, epoch,
                tools_declared=tools_declared, key_name=key_name,
                retry_original_id=retry_original_id)
            return _compat_probe_outcome(
                result, compat_decision[1], request_id, tier, method, path,
                headers, body, handler, config, vendors, epoch,
                retry_original_id=retry_original_id)
        finally:
            _compat_retry_lock.release()

    result = _forward_core(
        method, path, handler, request_id, config, rewritten_body,
        fwd_headers, upstream_path, host, port, use_ssl, tier,
        provider_name, actual_model, mode, _is_count_tokens, epoch,
        tools_declared=tools_declared, key_name=key_name,
        max_attempts=1 if suppress_compat else None,
        retry_original_id=retry_original_id)

    # Stripped request: upstream already saw the stripped body — return as-is.
    if compat_decision is not None:
        return result

    # Mode-scoped dispatch on the active feature. The suppress_compat clause
    # leads: every compatibility/rescue retry calls this function with the
    # flag set, so re-entry (and any nested rescue) is structurally
    # impossible. count_tokens never participates. active_feature is None for
    # a mode with no registered feature (response mode) — it must stay inert.
    if suppress_compat or active_feature is None or _is_count_tokens:
        return result

    # Attempt-1 scorekeeping (learning evidence). Sitting BELOW the guard is
    # load-bearing: a re-entry returns above and can never feed the credit.
    # reasoning_active is a second, independent belt — it is set only inside
    # the resolution block, whose conditions include `not suppress_compat`.
    # A success credits +1 (saturating); a matched complaint drains −1 and, on
    # the edge to 0, advances the entry one step and re-arms the credit.
    if reasoning_active:
        if 200 <= result[0] < 300:
            _reasoning_credit_on_2xx(reasoning_key, s_max, s_sw)
        elif active_feature.complaint_match(result[0], result[2]):
            _credit, switch_due = _reasoning_credit_on_complaint(
                reasoning_key, s_max, s_sw)
            if switch_due:
                _reasoning_advance_selection(reasoning_key, request_id, tier)

    if active_feature is not None and active_feature.name == "reasoning_field":
        # Any matched complaint is rescued, gate or no gate — a body with no
        # thinking block is exactly where the rescue is the only thing that
        # can serve.
        if not active_feature.complaint_match(result[0], result[2]):
            return result
        return _reasoning_rescue(
            result, reasoning_selection, request_id, tier, provider_name,
            actual_model, mode, method, path, headers, body, handler,
            config, vendors, epoch, retry_original_id=retry_original_id)

    if not compat_outbound_present or active_feature.name != COMPAT_FEATURE:
        # Presence gates the anthropic discovery below byte-identically, and a
        # registered feature this dispatch does not handle stays inert, so a
        # future third feature is never mis-routed into the paths below.
        return result

    # Discovery: the request carried the feature with no learned entry at
    # send time. On a recognized exact 400, confirm with one stripped retry
    # (single upstream attempt, same snapshot, suppress_compat=True).
    if result[0] != 400:
        return result
    if not _compat_rejection_match(result[0], result[2]):
        return result
    key = _compat_key(provider_name, mode, actual_model, COMPAT_FEATURE)
    log_trace({
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "event": "compatibility_rejection_detected",
        "request_id": request_id,
        "provider": provider_name,
        "mode": mode,
        "tier": tier,
        "actual_model": actual_model,
        "feature": COMPAT_FEATURE,
    })
    if _compat_suppressed(key):
        _compat_note_suppressed_request(key)
        log_trace({
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "event": "compatibility_failed_confirmation_suppressed",
            "request_id": request_id,
            "provider": provider_name,
            "mode": mode,
            "tier": tier,
            "actual_model": actual_model,
            "feature": COMPAT_FEATURE,
        })
        return result
    if not _compat_retry_lock.acquire(blocking=False):
        return result
    try:
        retry_result = None
        stripped_body = _compat_stripped_body(body)
        if stripped_body is not None:
            for _attempt in range(COMPAT_MAX_RETRIES_PER_REQUEST):
                retry_result = _forward_request_impl(
                    method, path, headers, stripped_body, handler,
                    request_id, config, vendors, epoch, suppress_compat=True,
                    retry_original_id=retry_original_id)
                break
        if retry_result is None:
            return result
        retry_result = _compat_merge_retries(result, retry_result)
        if 200 <= retry_result[0] < 300:
            _compat_learn(key, request_id, tier)
            return retry_result
        _compat_record_failed_confirmation(key)
        if _compat_suppressed(key):
            log_trace({
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "event": "compatibility_failed_confirmation_suppressed",
                "request_id": request_id,
                "provider": provider_name,
                "mode": mode,
                "tier": tier,
                "actual_model": actual_model,
                "feature": COMPAT_FEATURE,
            })
        return result
    finally:
        _compat_retry_lock.release()


def _upstream_header_value(value):
    """Coerce a forwarded header value into h11's legal field-value shape.

    The stdlib transport sent header values verbatim (it refused only a bare
    CR/LF), so a hostile client header — a NUL, other C0 whitespace, an
    obs-folded line — reached the upstream unchanged. h11 refuses those bytes
    outright and would turn such a request into a transport error, which the
    retry loop would then retry. The upstream copy is therefore flattened the
    way an obs-fold is meant on the wire: NUL is dropped, other refused
    whitespace becomes a single space, and the leading/trailing whitespace h11
    also refuses is stripped. The trace field keeps the client's raw value.
    """
    return re.sub(r"[\x00]", "", re.sub(r"[\r\n\f\v]+", " ", value)).strip(" \t")


def _forward_core(method, path, handler, request_id, config,
                  rewritten_body, fwd_headers, upstream_path,
                  host, port, use_ssl, tier, provider_name, actual_model,
                  mode, is_count_tokens, epoch, tools_declared=False, key_name=None,
                  max_attempts=None, retry_original_id=None):
    """Forwarding pass: 429/503/connection retry loop and response handling.

    max_attempts=None derives the attempt count from config (SETTINGS.max_retries,
    count_tokens exclusion); an explicit value overrides both — compatibility
    retries pass 1 so a compat retry is a single upstream attempt.

    epoch is the admission-time config generation. Backoff chains abandon at a
    swap press (retryable 503 config_swap_restart); every read boundary is
    epoch-checked so no old-routing result is delivered after a swap.
    """
    total_start = time.time()
    last_status = None
    retries = 0

    # Skip retry for count_tokens when disabled (avoids wasting bandwidth
    # on providers that don't support this Anthropic-specific endpoint)
    if max_attempts is None:
        disable_retry = config.get("disable_retry_claude_count_token", False)
        max_attempts = 1 if (disable_retry and is_count_tokens) \
                       else SETTINGS.max_retries + 1

    # ONE client per retry chain. Retry attempts reuse a pooled connection
    # (attempt isolation now by pool lifecycle rather than by opening a fresh
    # socket), while the per-chain lifetime keeps connection state from
    # accumulating across proxied requests — cookies cannot be replayed into a
    # later request because the client dies with this chain. trust_env=False
    # keeps ambient HTTP_PROXY/.netrc settings from silently rerouting upstream
    # calls; the accepted cost is that the SSL_CERT_FILE / SSL_CERT_DIR
    # ambient CA overrides are ignored (documented wire delta). The timeout is
    # uniform over connect/read/write/pool — the closest equivalent of the old
    # single socket timeout.
    # urlparse strips the brackets from an IPv6 authority; httpx2's
    # base_url requires them back (an unbracketed literal reads as an
    # invalid port).
    host_part = "[{}]".format(host) if ":" in host else host
    client = httpx2.Client(
        base_url="{}://{}:{}".format("https" if use_ssl else "http", host_part, port),
        timeout=httpx2.Timeout(SETTINGS.read_timeout),
        trust_env=False,
        follow_redirects=False,
    )
    try:
        for attempt in range(max_attempts):
            # Retry-loop head: an epoch change means a swap completed while this
            # request was getting here. Epoch ONLY — an in-progress drain must
            # not abort an immediate compat single-shot re-issue, which is live
            # work (test_compat_config_swap_during_retry pins that boundary).
            if _swap_epoch_changed(epoch):
                _note_swap_eviction("retry_chain", request_id, tier=tier,
                                    provider=provider_name, model=actual_model)
                return _swap_abort_tuple(request_id, total_start, retries, tier,
                                         provider_name, actual_model)
            try:
                # The stream context releases the response on every exit path:
                # retry `continue`, give-up return, SSE dispatch, buffered
                # return, and any exception. Header names/values are passed as
                # latin-1 bytes: httpx2 encodes `str` header values as ASCII and
                # would reject a non-ASCII User-Agent that the stdlib transport
                # forwarded, so the encoding the old transport applied is
                # reproduced here (a value outside latin-1 still raises, exactly
                # as before). Values are flattened to h11's legal shape first —
                # see _upstream_header_value.
                with client.stream(method, upstream_path,
                                   content=rewritten_body,
                                   headers={k.encode("latin-1"):
                                            _upstream_header_value(v).encode("latin-1")
                                            for k, v in fwd_headers.items()}) as resp:
                    _touch_upstream_activity()

                    # A response that landed after a completed swap is an
                    # old-routing result: fail it retryably before any byte
                    # reaches the client. httpx2 cannot be woken while blocked
                    # on the response headers, so this is the accepted
                    # late-exit checkpoint.
                    if _swap_epoch_changed(epoch):
                        _note_swap_eviction("pre_first_byte", request_id, tier=tier,
                                            provider=provider_name, model=actual_model)
                        return _swap_abort_tuple(request_id, total_start, retries, tier,
                                                 provider_name, actual_model)

                    if resp.status_code in (429, 503):
                        last_status = resp.status_code
                        if attempt < max_attempts - 1:
                            if resp.status_code == 429:
                                delay = compute_jittered_delay(SETTINGS.max_delay)
                                reason = "429"
                            elif resp.status_code == 503:
                                delay = compute_jittered_delay(compute_delay(attempt))
                                reason = "503"
                            else:  # defensive — future expansion must add a branch here
                                delay = compute_jittered_delay(compute_delay(attempt))
                                reason = str(resp.status_code)
                            try:
                                # Drain the error body before close, raw and
                                # bounded: iter_raw installs no decoder, so an
                                # upstream that ignored the identity pin cannot
                                # expand a compressed body into worker memory,
                                # and the cap keeps the discard finite.
                                drained = 0
                                for chunk in resp.iter_raw():
                                    drained += len(chunk)
                                    if drained > SETTINGS.max_body_size:
                                        break
                            except (httpx2.RequestError, OSError):
                                pass
                            _touch_upstream_activity()
                            # A backoff chain abandons at the press: sleep in slices
                            # and leave the stream context on the way out, so every
                            # abandoned chain releases its upstream connection (the
                            # exact traffic a switch under rate limiting produces).
                            aborted = _swap_chain_abort(epoch)
                            if not aborted:
                                aborted = _interruptible_sleep(delay, epoch)
                            if aborted:
                                _note_swap_eviction("retry_chain", request_id, tier=tier,
                                                    provider=provider_name,
                                                    model=actual_model)
                                return _swap_abort_tuple(request_id, total_start, retries,
                                                         tier, provider_name, actual_model)
                            # Accounting follows the completed sleep: an abandoned
                            # chain must never log a retry it did not take.
                            retries += 1
                            increment_retried()
                            print("[proxy] {} on attempt {}/{}, model={}, provider={}, rid={}, retrying in {}s".format(
                                reason, attempt + 1, max_attempts, actual_model,
                                provider_name, request_id, delay), file=sys.stderr)
                            log_trace({
                                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                "event": "retry",
                                "attempt": attempt + 1,
                                "delay_s": delay,
                                "reason": reason,
                                "model": actual_model,
                                "provider": provider_name,
                                "request_id": request_id,
                                "path": path,
                            })
                            continue
                        else:
                            err_body = _read_capped(resp, SETTINGS.max_body_size, request_id)
                            return resp.status_code, {}, err_body, None, time.time() - total_start, retries, tier, provider_name, actual_model

                    # Non-retryable response. Headers are mapped from
                    # Headers.raw — the only carrier of the raw wire pairs:
                    # dict(resp.headers) lowercases keys and comma-joins
                    # duplicate values, which would change every forwarded
                    # header's casing. This comprehension reproduces today's
                    # dict(resp.getheaders()) exactly: received casing,
                    # last-wins duplicates.
                    resp_headers = {k.decode("latin-1"): v.decode("latin-1")
                                    for k, v in resp.headers.raw}
                    # Dispatch lookup is case-insensitive per RFC 9110
                    # field-name rules: HTTP/2 connections and some gateways
                    # emit lowercased names, which a canonical-spelling
                    # lookup on the received-casing dict above would miss.
                    # Forwarding keeps received casing; only the dispatch
                    # value is normalized (lowercased keys, last-wins).
                    content_type = {k.lower(): v
                                    for k, v in resp_headers.items()}.get(
                                        "content-type", "").lower()

                    # Determine response handling strategy based on status and Content-Type
                    if handler is not None and 200 <= resp.status_code < 300:
                        # 2xx response - check Content-Type to decide streaming vs buffering
                        if "text/event-stream" in content_type:
                            # SSE: stream with mode-appropriate rewriting/transform
                            first_byte_ms = handler._stream_upstream_response(
                                resp, resp.status_code, resp_headers, request_id, retries,
                                epoch=epoch, content_type=content_type, tier=tier, mode=mode,
                                tools_declared=tools_declared,
                                provider=provider_name, key=key_name,
                                retry_original_id=retry_original_id)
                            return (resp.status_code, resp_headers, b"",
                                    first_byte_ms, time.time() - total_start, retries, tier, provider_name, actual_model)
                        elif "application/json" in content_type:
                            # JSON: buffer, then dispatch mode-appropriate transform
                            first_byte_start = time.time()
                            chunks = []
                            first_byte = True
                            first_byte_elapsed = None
                            total_bytes = 0

                            for chunk in resp.iter_raw():
                                _touch_upstream_activity()
                                if first_byte:
                                    first_byte_elapsed = (time.time() - first_byte_start) * 1000
                                    first_byte = False
                                # Slice before appending: iter_raw chunks are
                                # wire-sized, so one chunk can cross the cap by
                                # any amount. Appending first and testing after
                                # would return a cap-busting body whole.
                                keep = chunk[:SETTINGS.max_response_size - total_bytes]
                                chunks.append(keep)
                                total_bytes += len(chunk)
                                if len(keep) < len(chunk):
                                    log_trace({
                                        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                        "event": "response_size_cap_exceeded",
                                        "request_id": request_id,
                                        "bytes_read": total_bytes,
                                        "limit": SETTINGS.max_response_size,
                                    })
                                    print("[proxy] Response size limit exceeded ({} bytes), rid={}".format(
                                        total_bytes, request_id), file=sys.stderr)
                                    break

                            total_elapsed = time.time() - total_start
                            resp_body = b"".join(chunks)

                            # Buffered bodies cannot be woken mid-read; their stall
                            # exits late and then fails this checkpoint (recorded
                            # boundary). The swap's result must not reach the client.
                            if _swap_epoch_changed(epoch):
                                _note_swap_eviction("buffered", request_id, tier=tier,
                                                    provider=provider_name,
                                                    model=actual_model)
                                return _swap_abort_tuple(request_id, total_start, retries,
                                                         tier, provider_name, actual_model)

                            if mode == "chat":
                                resp_body = _transform_and_guard(
                                    resp_body, tier, _chat_to_anthropic, request_id, mode, provider_name)
                            elif mode == "response":
                                resp_body = _transform_and_guard(
                                    resp_body, tier, _response_to_anthropic, request_id, mode, provider_name)
                            else:
                                resp_body = _rewrite_json_response(
                                    resp_body, tier, request_id)
                            resp_headers["Content-Length"] = str(len(resp_body))

                            return (resp.status_code, resp_headers, resp_body,
                                    first_byte_elapsed, total_elapsed, retries, tier, provider_name, actual_model)
                        else:
                            # Other content types: chat/response modes buffer and
                            # transform as JSON (OpenAI APIs return JSON or SSE);
                            # anthropic mode streams unchanged (existing behavior).
                            if mode in ("chat", "response"):
                                first_byte_start = time.time()
                                chunks = []
                                first_byte = True
                                first_byte_elapsed = None
                                total_bytes = 0
                                for chunk in resp.iter_raw():
                                    _touch_upstream_activity()
                                    if first_byte:
                                        first_byte_elapsed = (time.time() - first_byte_start) * 1000
                                        first_byte = False
                                    # Slice before appending: iter_raw chunks
                                    # are wire-sized, so one chunk can cross
                                    # the cap by any amount.
                                    keep = chunk[:SETTINGS.max_response_size - total_bytes]
                                    chunks.append(keep)
                                    total_bytes += len(chunk)
                                    if len(keep) < len(chunk):
                                        log_trace({
                                            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                            "event": "response_size_cap_exceeded",
                                            "request_id": request_id,
                                            "bytes_read": total_bytes,
                                            "limit": SETTINGS.max_response_size,
                                        })
                                        print("[proxy] Response size limit exceeded ({} bytes), rid={}".format(
                                            total_bytes, request_id), file=sys.stderr)
                                        break
                                total_elapsed = time.time() - total_start
                                resp_body = b"".join(chunks)
                                if _swap_epoch_changed(epoch):
                                    _note_swap_eviction("buffered", request_id, tier=tier,
                                                        provider=provider_name,
                                                        model=actual_model)
                                    return _swap_abort_tuple(request_id, total_start, retries,
                                                             tier, provider_name, actual_model)
                                transform_fn = _chat_to_anthropic if mode == "chat" else _response_to_anthropic
                                resp_body = _transform_and_guard(
                                    resp_body, tier, transform_fn, request_id, mode, provider_name)
                                resp_headers["Content-Length"] = str(len(resp_body))
                                return (resp.status_code, resp_headers, resp_body,
                                        first_byte_elapsed, total_elapsed, retries, tier, provider_name, actual_model)
                            else:
                                first_byte_ms = handler._stream_upstream_response(
                                    resp, resp.status_code, resp_headers, request_id, retries,
                                    epoch=epoch, content_type=content_type, tier=tier, mode=mode,
                                    tools_declared=tools_declared,
                                    provider=provider_name, key=key_name,
                                    retry_original_id=retry_original_id)
                                return (resp.status_code, resp_headers, b"",
                                        first_byte_ms, time.time() - total_start, retries, tier, provider_name, actual_model)

                    # Non-2xx or no handler — buffer the body so upstream error content
                    # stays in the trace log.
                    first_byte_start = time.time()
                    chunks = []
                    first_byte = True
                    first_byte_elapsed = None
                    total_bytes = 0

                    for chunk in resp.iter_raw():
                        _touch_upstream_activity()
                        if first_byte:
                            first_byte_elapsed = (time.time() - first_byte_start) * 1000
                            first_byte = False
                        # Slice before appending: iter_raw chunks are
                        # wire-sized, so one chunk can cross the cap by any
                        # amount.
                        keep = chunk[:SETTINGS.max_response_size - total_bytes]
                        chunks.append(keep)
                        total_bytes += len(chunk)
                        if len(keep) < len(chunk):
                            log_trace({
                                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                "event": "response_size_cap_exceeded",
                                "request_id": request_id,
                                "bytes_read": total_bytes,
                                "limit": SETTINGS.max_response_size,
                            })
                            print("[proxy] Response size limit exceeded ({} bytes)".format(
                                total_bytes), file=sys.stderr)
                            break

                    total_elapsed = time.time() - total_start

                    resp_body = b"".join(chunks)
                    if _swap_epoch_changed(epoch):
                        _note_swap_eviction("buffered", request_id, tier=tier,
                                            provider=provider_name, model=actual_model)
                        return _swap_abort_tuple(request_id, total_start, retries, tier,
                                                 provider_name, actual_model)

                    # Non-2xx error path: anthropic mode keeps the model rewrite it had before;
                    # chat/response modes pass upstream error bodies through
                    # byte-for-byte untransformed.
                    if "application/json" in content_type and mode == "anthropic":
                        resp_body = _rewrite_json_response(
                            resp_body, tier, request_id)
                        resp_headers["Content-Length"] = str(len(resp_body))

                    return (resp.status_code, resp_headers, resp_body,
                            first_byte_elapsed, total_elapsed, retries, tier, provider_name, actual_model)

            except (httpx2.RequestError, httpx2.StreamError, OSError) as e:
                last_status = 0
                if attempt < max_attempts - 1:
                    delay = compute_jittered_delay(compute_delay(attempt))
                    # Same abandonment rule as the 429/503 site; there is no open
                    # connection to close here (its next statement is `continue`).
                    aborted = _swap_chain_abort(epoch)
                    if not aborted:
                        aborted = _interruptible_sleep(delay, epoch)
                    if aborted:
                        _note_swap_eviction("retry_chain", request_id, tier=tier,
                                            provider=provider_name,
                                            model=actual_model)
                        return _swap_abort_tuple(request_id, total_start, retries,
                                                 tier, provider_name, actual_model)
                    retries += 1
                    increment_retried()
                    print("[proxy] Connection error on attempt {}/{}, model={}, provider={}, rid={}: {}, retrying in {}s".format(
                        attempt + 1, max_attempts, actual_model, provider_name,
                        request_id, e, delay), file=sys.stderr)
                    log_trace({
                        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        "event": "retry",
                        "attempt": attempt + 1,
                        "delay_s": delay,
                        "reason": "connection_error",
                        "model": actual_model,
                        "provider": provider_name,
                        "request_id": request_id,
                        "error": sanitize_error(str(e)),
                        "path": path,
                    })
                    continue
                else:
                    total_elapsed = time.time() - total_start
                    err_body = _error_body(
                        "api_error", "upstream_unreachable",
                        "upstream: {} after {} retries".format(
                            sanitize_error(str(e)) or "connection failed", retries),
                        request_id)
                    return 502, {}, err_body, None, total_elapsed, retries, tier, provider_name, actual_model

        total_elapsed = time.time() - total_start
        return (last_status or 502), {}, _error_body(
            "api_error", "upstream_unreachable",
            "upstream: connection failed after {} retries".format(retries),
            request_id), None, total_elapsed, retries, tier, provider_name, actual_model
    finally:
        client.close()


# ---------------------------------------------------------------------------
# Model extraction and tier resolution
# ---------------------------------------------------------------------------

def extract_model(body_bytes):
    """Extract model name from request body.

    Returns a 2-tuple (model_name, body_error). The contract is total —
    exactly five outcomes:
      - empty body: ("unknown", None) — early return, never reaches json.loads
        (empty bodies continue to surface as unrecognized_model)
      - object body, usable model: (name, None)
      - object body, model missing/None/non-string: ("unknown", None)
      - parses but is not a dict: (None, "invalid_body_type")
      - does not parse: (None, "invalid_json")
    """
    if not body_bytes:
        return "unknown", None
    try:
        data = json.loads(body_bytes)
    except Exception:  # total per compat._compat_guarded_parse (RecursionError is not a ValueError)
        return None, "invalid_json"
    if not isinstance(data, dict):
        return None, "invalid_body_type"
    model = data.get("model")
    # Guard against None or non-string model values
    if model is None or not isinstance(model, str):
        return "unknown", None
    return model, None


def resolve_tier(model_name, config):
    """Resolve a model name to a tier name.

    Resolution order:
    1. None guard: if model_name is None or not a string, return "unknown"
    2. Direct match: if model_name is "haiku"/"sonnet"/"opus"
    3. Reverse lookup: scan config tiers for matching model
    4. Pattern match: check if tier keyword is in model_name (opus, sonnet, haiku order)

    Returns:
        str: tier name ("haiku", "sonnet", "opus") or "unknown" if unresolvable
    """
    # 1. None guard
    if model_name is None or not isinstance(model_name, str):
        return "unknown"

    # 2. Direct match
    if model_name in ("haiku", "sonnet", "opus"):
        return model_name

    # 3. Reverse lookup: find tier whose configured model matches
    tiers = config.get("tiers", {})
    for tier_name, tier_config in tiers.items():
        if isinstance(tier_config, dict):
            configured_model = tier_config.get("model")
            if configured_model and configured_model == model_name:
                return tier_name

    # 4. Pattern match: check in order opus, sonnet, haiku (most-specific first)
    model_lower = model_name.lower()
    for tier in ("opus", "sonnet", "haiku"):
        if tier in model_lower:
            return tier

    return "unknown"


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
