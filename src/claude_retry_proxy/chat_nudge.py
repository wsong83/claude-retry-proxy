"""Chat retry-nudge marker store (extracted from forwarder.py 2026-11-24).

Owns the single-use, in-memory recovery markers for the chat-mode
unfinished-turn retry (see the banner comment below). The parent module
(forwarder.py) imports this one; this module never imports its parent.
"""

import hashlib
import json
import threading
import time


# ---------------------------------------------------------------------------
# Retry-nudge marker store (chat-mode unfinished-turn recovery)
# ---------------------------------------------------------------------------
#
# Single-use, in-memory markers: _retry_nudge_remember stores an unarmed
# entry per chat request at entry; _retry_nudge_arm marks it when the stream
# closes the turn with the retryable error; _retry_nudge_check recognizes the
# client's recovery request (exact body re-issue or strict conversation
# extension) and CONSUMES the entry on match. Only armed entries age-expire,
# on a TTL anchored at arm (unarmed entries are never age-swept — the cap's
# oldest-unarmed-first eviction bounds them), so a long generation cannot
# expire its own marker. Bounded by RETRY_NUDGE_MAX_ENTRIES entries, each
# holding only a body hash, a prefix digest and the prefix's byte count — no
# messages copy; cleared on restart, never persisted. Helpers never raise:
# an internal failure returns None/False and mutates nothing (the sinks'
# discipline).
RETRY_NUDGE_TTL_SECONDS = 180
RETRY_NUDGE_MAX_ENTRIES = 64


# Every read and write of the store's entries — including the sweep and the
# eviction scan — runs under this lock. remember/arm/check each acquire it
# exactly once; the store's _sweep is lock-held-internal (its callers hold
# it), so the non-reentrant Lock is never re-acquired.
class _NudgeStore:
    """Owns the marker lock and the bounded entry dict."""

    def __init__(self):
        self._lock = threading.Lock()
        self._entries = {}

    def _sweep(self):
        """Drop armed entries past the recovery-window bound.

        Lock-held-internal: the caller (remember or check) already holds the
        store lock — never acquire here. Only ARMED entries age-expire: the
        TTL runs from arm (arm refreshes stored_at), so it measures the
        post-error recovery window, never the original request's start.
        Unarmed entries are not age-expired — a generation longer than the
        TTL must not lose its own marker to a concurrent request's sweep
        before its arm; the cap's oldest-unarmed-first eviction bounds them.
        """
        now = time.time()
        expired = [rid for rid, entry in self._entries.items()
                   if entry.get("armed")
                   and now - entry.get("stored_at", 0.0) > RETRY_NUDGE_TTL_SECONDS]
        for rid in expired:
            del self._entries[rid]

    def remember(self, request_id, body, body_json):
        """Store an unarmed marker for this chat request. True iff stored.

        Skips (mutating nothing) when request_id is falsy or already present (a
        compat/reasoning re-entry of the same request must not clobber an entry
        armed earlier in its lifecycle), or when messages is not a non-empty
        list of dicts. The marker holds a body hash, the prefix length, a
        prefix digest and the prefix's byte count — never a copy of the
        messages. At the entry cap, unarmed entries are evicted first (oldest
        first) and armed only as a last resort — armed entries are the ones
        with imminent recoveries.
        """
        if not request_id:
            return False
        messages = body_json.get("messages") if isinstance(body_json, dict) else None
        if not isinstance(messages, list) or not messages:
            return False
        if not all(isinstance(m, dict) for m in messages):
            return False
        try:
            canonical = json.dumps(messages, separators=(",", ":"), sort_keys=True)
            body_hash = hashlib.sha256(body).hexdigest()
            prefix_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        except (TypeError, ValueError, RecursionError):
            return False
        with self._lock:
            if request_id in self._entries:
                return False
            self._sweep()
            self._entries[request_id] = {
                "hash": body_hash,
                "prefix_len": len(messages),
                "prefix_hash": prefix_hash,
                "messages_bytes": len(canonical.encode("utf-8")),
                "armed": False,
                "stored_at": time.time(),
            }
            # Enforce the cap: evict unarmed entries first (oldest first), armed
            # only as a last resort. The entry just stored is never the victim.
            while len(self._entries) > RETRY_NUDGE_MAX_ENTRIES:
                victim = None
                for _armed_pref in (False, True):
                    for rid, entry in self._entries.items():
                        if rid == request_id or bool(entry.get("armed")) != _armed_pref:
                            continue
                        if victim is None or entry["stored_at"] < victim[1]["stored_at"]:
                            victim = (rid, entry)
                    if victim is not None:
                        break
                if victim is None:
                    break
                del self._entries[victim[0]]
        return True

    def arm(self, request_id):
        """Set the marker's armed flag and re-anchor its TTL at arm.

        Returns True iff an entry was armed, False when none exists (never
        creates one). The bool is load-bearing: the stream errors the turn only
        when arming succeeded. No sweep here by design, and no age barrier
        before arm either — the sweep exempts unarmed entries, so an entry
        older than the TTL at arm time is still present and armable; arm
        refreshes stored_at, and the recovery window starts when the error is
        written, not when the request arrived.
        """
        if not request_id:
            return False
        with self._lock:
            entry = self._entries.get(request_id)
            if entry is None:
                return False
            entry["armed"] = True
            entry["stored_at"] = time.time()
            return True

    def messages_bytes(self, request_id):
        """The stored prefix's byte count for this request, or None if no marker.

        Read-only diagnostic companion to the fire event: a None here means the
        marker was never stored for this request (an ineligible body — falsy id,
        or messages not a non-empty list of dicts), while a number is the size of
        the serialized messages array the marker was built from. This is the
        quantity the removed messages-size cap measured, kept on the trace so a
        future skip is visible on the wire rather than inferred from session
        transcripts.
        """
        if not request_id:
            return None
        with self._lock:
            entry = self._entries.get(request_id)
            return entry.get("messages_bytes") if entry is not None else None

    def check(self, body, body_json):
        """Find the armed marker this request recovers; consume it on match.

        Two passes over the (swept) armed entries: exact sha256(body) first (a
        byte-identical re-issue), then the strict-extension prefix (the new
        messages list starts with the stored prefix AND is longer — the realistic
        recovery appends the interrupted turn and its continuation prompt; a
        byte-identical re-send belongs to the exact-hash branch, and the
        strictness keeps an equal-length non-identical list from matching).
        Returns the stored request_id on a match, None otherwise. The entry is
        consumed (deleted) before returning: the marker is single-use, so later
        turns of the recovering conversation are neither nudged with now-false
        "previous turn" text nor routed into the passthrough loop guard — the
        recovery request's own passthrough decision never re-consults the store
        (retry_original_id is computed once at request entry). No-raise: an
        internal failure returns None and mutates nothing.
        """
        if not body:
            return None
        try:
            body_hash = hashlib.sha256(body).hexdigest()
        except (TypeError, ValueError):
            return None
        with self._lock:
            self._sweep()
            armed = [(rid, entry) for rid, entry in self._entries.items()
                     if entry.get("armed")]
            # Pass 1: exact body re-issue wins over any prefix match.
            for rid, entry in armed:
                if entry.get("hash") == body_hash:
                    del self._entries[rid]
                    return rid
            # Pass 2: strict extension of the stored conversation prefix — the
            # recovery's messages start with the stored prefix AND are longer.
            # The store keeps a digest, not a copy, so re-serialize the candidate
            # prefix with the same canonical form remember used.
            messages = body_json.get("messages") if isinstance(body_json, dict) else None
            if not isinstance(messages, list) or not messages:
                return None
            if not all(isinstance(m, dict) for m in messages):
                return None
            for rid, entry in armed:
                prefix_len = entry.get("prefix_len")
                if not isinstance(prefix_len, int) or prefix_len <= 0:
                    continue
                if len(messages) <= prefix_len:
                    continue
                try:
                    canonical = json.dumps(messages[:prefix_len],
                                           separators=(",", ":"), sort_keys=True)
                    prefix_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
                except (TypeError, ValueError, RecursionError):
                    continue
                if prefix_hash == entry.get("prefix_hash"):
                    del self._entries[rid]
                    return rid
        return None


_store = _NudgeStore()


def _retry_nudge_remember(request_id, body, body_json):
    return _store.remember(request_id, body, body_json)


def _retry_nudge_arm(request_id):
    return _store.arm(request_id)


def _retry_nudge_messages_bytes(request_id):
    return _store.messages_bytes(request_id)


def _retry_nudge_check(body, body_json):
    return _store.check(body, body_json)
