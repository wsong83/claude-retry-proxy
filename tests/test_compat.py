"""Compatibility-learning tests for claude-retry-proxy (plan 2026-09-01).

Covers the learned per-upstream `context_management` compatibility subsystem:
state persistence and fail-open loading, the exact error detector, the
learn/strip/probe/backoff/probation/delist state machine, concurrency bounds,
and metadata-only trace privacy. All are permanent tests; the threshold tests
seed near-boundary counters by bootstrapping a learned state file with a
throwaway proxy and mutating plan-pinned fields, so they do not depend on the
implementation's entry-key format.

Part of the claude-retry-proxy suite; runnable standalone.
"""
import json
import os
import shutil
import tempfile
import threading
import time

from _harness import (
    _admin_post,
    fail,
    find_free_port,
    pass_,
    run_cli,
    warn,
    _mode_tiers,
    _send_proxy_request,
    _send_proxy_request_stream,
    _start_mode_proxy,
)

STATE_ENV = "PROXY_FEATURE_COMPAT_FILE"

# The exact 400 body observed from opencode-zen-claude (deferred issue
# opencode-zen-claude-rejects-extra-inputs): message form ending in
# "context_management: Extra inputs are not permitted", token preceded by "] ".
OBSERVED_400_BODY = json.dumps({
    "type": "error",
    "error": {
        "type": "invalid_request_error",
        "message": "Error from provider (Console): Upstream request failed: "
                   "[invalid_request_error] context_management: "
                   "Extra inputs are not permitted",
    },
}).encode()

# Structured variant: extra_forbidden validation data locating the top-level
# field (pydantic-style loc inside the Anthropic error envelope).
STRUCTURED_400_BODY = json.dumps({
    "type": "error",
    "error": {
        "type": "invalid_request_error",
        "message": "Extra inputs are not permitted",
        "code": "extra_forbidden",
        "loc": ["body", "context_management"],
    },
}).encode()

# Rejected-body corpus shared by the context_management detector scenarios and
# the reasoning matcher's unit test: (label, status, body_bytes) triples that
# are NOT complaints for either feature. The two matchers are structurally
# parallel by design, so one table is what keeps them from drifting apart.
# Accept-side cases stay separate — they differ by field-name constant.
REJECTED_BODY_CORPUS = [
    ("http-500", 500, json.dumps({
        "type": "error",
        "error": {"type": "api_error", "message": "upstream exploded"},
    }).encode()),
    ("http-2xx-success", 200, json.dumps({
        "id": "msg_ok", "type": "message", "role": "assistant", "model": "m",
        "content": [], "usage": {"input_tokens": 1, "output_tokens": 1},
    }).encode()),
    ("unparseable-body", 400, b"this is not json at all"),
    ("empty-body", 400, b""),
    ("json-array-body", 400, b'["context_management", "reasoning_content"]'),
]

CM_VALUE = {"edits": [{"type": "clear_tool_uses_20250901"}]}
CM_MARKER = "clear_tool_uses_20250901"
ERROR_MARKER = "Extra inputs are not permitted"
UPSTREAM_ERROR_MARKER = "Error from provider"

SSE_BODY = (
    b"event: message_start\n"
    b'data: {"type":"message_start","message":{"id":"msg_sse","type":"message",'
    b'"role":"assistant","model":"claude-sonnet-5","content":[],"stop_reason":null,'
    b'"usage":{"input_tokens":1,"output_tokens":1}}}\n'
    b"\n"
    b"event: content_block_delta\n"
    b'data: {"type":"content_block_delta","index":0,'
    b'"delta":{"type":"text_delta","text":"hi"}}\n'
    b"\n"
    b"event: message_stop\n"
    b'data: {"type":"message_stop"}\n'
    b"\n"
)

# The persisted schema is per-feature: one shared envelope plus each
# descriptor's own field set. The reasoning entry adds exactly `selection`;
# the default ("none") is never persisted — an absent entry means none.
ENVELOPE_STATE_KEYS = {
    "schema_version", "provider", "mode", "actual_model", "feature",
}
ALLOWED_STATE_KEYS_BY_FEATURE = {
    "context_management": ENVELOPE_STATE_KEYS | {
        "state", "threshold", "strip_counter", "probation_successes",
    },
    "reasoning_field": ENVELOPE_STATE_KEYS | {"selection"},
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cm_request(model="sonnet", include_cm=True, text="hello"):
    body = {
        "model": model,
        "max_tokens": 16,
        "messages": [{"role": "user", "content": [{"type": "text", "text": text}]}],
    }
    if include_cm:
        body["context_management"] = CM_VALUE
    return body


def _send(port, body, path="/v1/messages"):
    return _send_proxy_request(port, path=path, body=json.dumps(body))


def _make_state_dir():
    d = tempfile.mkdtemp(prefix="compat_state_")
    return d, os.path.join(d, "feature-compatibility.json")


def _read_state_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _write_state_file(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f)


# ---------------------------------------------------------------------------
# reasoning_field (chat mode) helpers
# ---------------------------------------------------------------------------

# 400 bodies naming a reasoning field, in the content shapes a real gateway
# uses. All are built from the field-name constants; none carries upstream
# prose the matcher depends on.
REASONING_MESSAGE_400 = json.dumps({
    "type": "error",
    "error": {
        "type": "invalid_request_error",
        "message": "The reasoning_content in the thinking mode must be passed "
                   "back to the API.",
    },
}).encode()

REASONING_SWITCH_THRESHOLD = 3


def _reasoning_request(model="sonnet", with_thinking=True, text="hello"):
    """A chat-mode client request. `with_thinking` appends an assistant turn
    carrying a thinking block — the presence gate that makes the reasoning
    feature active for the request."""
    body = {
        "model": model,
        "max_tokens": 16,
        "messages": [
            {"role": "user", "content": [{"type": "text", "text": text}]},
        ],
    }
    if with_thinking:
        body["messages"].append({
            "role": "assistant",
            "content": [
                {"type": "thinking", "thinking": "hmm", "signature": "s"},
                {"type": "text", "text": "ok"},
            ],
        })
    return body


def _sent_reasoning_field(info):
    """The reasoning field the proxy actually sent upstream, or None.

    Read from the mock upstream's recorded request, so it observes the bytes
    that really left the proxy rather than any internal call record.
    """
    try:
        body = json.loads(info["body"])
    except Exception:
        return None
    for m in body.get("messages", []):
        if not isinstance(m, dict) or m.get("role") != "assistant":
            continue
        for f in ("reasoning_content", "reasoning"):
            if f in m:
                return f
    return None


def _chat_ok_response(info):
    """A minimal OpenAI chat-completions 2xx body."""
    try:
        model = json.loads(info["body"]).get("model", "unknown")
    except Exception:
        model = "unknown"
    return 200, "application/json", json.dumps({
        "id": "chatcmpl-ok", "object": "chat.completion", "created": 1,
        "model": model,
        "choices": [{"index": 0, "message": {"role": "assistant",
                                             "content": "hi"},
                     "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1,
                  "total_tokens": 2},
    }).encode()


def _reasoning_upstream(policy, log=None):
    """A chat-mode mock upstream that validates the echoed reasoning field.

    policy["accept"] is a tuple of accepted values: field names, plus the
    literal "none" for a request that carries no reasoning field at all. A
    request sending anything outside that tuple gets the message-form 400.
    policy["accept"] is read per request, so the test can change the upstream's
    convention mid-conversation. Every request is appended to `log` when given.
    """
    def responder(info):
        if log is not None:
            log.append(info)
        sent = _sent_reasoning_field(info) or "none"
        if sent in policy.get("accept", ()):
            return _chat_ok_response(info)
        return 400, "application/json", REASONING_MESSAGE_400
    return responder


def _reasoning_entry(state_path, model="claude-sonnet-5", provider="p"):
    """The persisted reasoning_field entry for a pair, or None."""
    state = _read_state_file(state_path)
    if not state:
        return None
    for entry in _entry_values(_entries(state)):
        if (isinstance(entry, dict)
                and entry.get("feature") == "reasoning_field"
                and entry.get("provider") == provider
                and entry.get("actual_model") == model):
            return entry
    return None


def _seed_reasoning_state(state_path, selection,
                          model="claude-sonnet-5", provider="p"):
    """Write a state file carrying one learned reasoning_field selection."""
    entry = {
        "schema_version": 1, "provider": provider, "mode": "chat",
        "actual_model": model, "feature": "reasoning_field",
        "selection": selection,
    }
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump({"schema_version": 1,
                   "entries": {"\x1f".join(
                       (provider, "chat", model, "reasoning_field")): entry}},
                  f)


def _chat_vendor(port):
    """A single chat-mode vendor spec pointing at a mock upstream."""
    return {"url": "http://127.0.0.1:%d" % port, "key": "K", "mode": "chat"}


def _start_reasoning_proxy(responders, state_path):
    """Start a chat-mode proxy backed by one mock upstream, with an isolated
    compatibility state file."""
    vendors = {"p": _chat_vendor(find_free_port())}
    return _start_compat_proxy(responders, state_path, vendors=vendors)


def _entries(state):
    return state.get("entries", {})


def _entry_values(entries):
    return list(entries.values()) if isinstance(entries, dict) else []


def _reject_unstripped_responder(ok_body="json"):
    """400 with the observed error for bodies containing context_management,
    2xx otherwise. Drives both discovery (unstripped 400) and stripping."""

    def responder(info):
        try:
            has_cm = "context_management" in json.loads(info["body"])
        except Exception:
            has_cm = False
        if has_cm:
            return 400, "application/json", OBSERVED_400_BODY
        return _ok_response(info, ok_body)

    return responder


def _always_400_responder():
    def responder(info):
        return 400, "application/json", OBSERVED_400_BODY
    return responder


def _ok_response(info, kind="json"):
    try:
        model = json.loads(info["body"]).get("model", "unknown")
    except Exception:
        model = "unknown"
    if kind == "sse":
        return 200, "text/event-stream", SSE_BODY
    if kind == "truncated-sse":
        return 200, "text/event-stream", SSE_BODY[:80]
    body = json.dumps({
        "id": "msg_ok", "type": "message", "role": "assistant",
        "model": model,
        "content": [{"type": "text", "text": "hello"}],
        "stop_reason": "end_turn", "stop_sequence": None,
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }).encode()
    return 200, "application/json", body


def _cm_count(requests):
    """Number of recorded upstream requests whose body contained
    context_management."""
    n = 0
    for r in requests:
        try:
            if "context_management" in json.loads(r["body"]):
                n += 1
        except Exception:
            pass
    return n


def _compat_trace_events(trace_file, name=None):
    out = []
    if not trace_file or not os.path.exists(trace_file):
        return out
    with open(trace_file) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except Exception:
                continue
            ev_name = ev.get("event", "")
            if ev_name.startswith("compatibility_"):
                if name is None or ev_name == name:
                    out.append(ev)
    return out


def _start_compat_proxy(responders, state_path, tiers=None, vendors=None,
                        extra_env=None):
    """Start a proxy with an isolated compatibility state file."""
    if tiers is None:
        tiers = _mode_tiers()
    if vendors is None:
        upstream_port = find_free_port()
        vendors = {"p": {"url": "http://127.0.0.1:%d" % upstream_port,
                         "key": "K"}}
    env = {STATE_ENV: state_path}
    if extra_env:
        env.update(extra_env)
    return _start_mode_proxy(tiers, vendors, responders=responders,
                             extra_env=env)


def _bootstrap_learned_state(model="claude-sonnet-5", state="unsupported"):
    """Start a throwaway proxy and learn context_management-unsupported.

    Returns (state_dir, state_path). The proxy is stopped before returning;
    the caller owns state_dir cleanup. This bootstraps a state file in the
    implementation's own format so later tests can mutate plan-pinned fields
    without knowing the entry-key layout.
    """
    state_dir, state_path = _make_state_dir()
    tiers = _mode_tiers(model=model)
    responders = {"p": _reject_unstripped_responder()}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
        _start_compat_proxy(responders, state_path, tiers=tiers)
    if proc is None:
        shutil.rmtree(state_dir, ignore_errors=True)
        fail("bootstrap proxy failed to start")
        return state_dir, state_path
    try:
        status, _ = _send(proxy_port, _cm_request())
        if status != 200:
            fail("bootstrap learning request returned %s" % status)
    finally:
        cleanup()
    return state_dir, state_path


def _mutate_entry(state_path, mutate, expect_count=1):
    """Apply mutate(entry_dict) to every entry whose feature is
    context_management; write the file back in place."""
    state = _read_state_file(state_path)
    if state is None:
        fail("cannot read bootstrapped state file at %s" % state_path)
        return
    touched = 0
    for entry in _entry_values(_entries(state)):
        if isinstance(entry, dict) and entry.get("feature") == "context_management":
            mutate(entry)
            touched += 1
    if touched != expect_count:
        warn("entry mutation touched %d entries (expected %d)"
             % (touched, expect_count))
    _write_state_file(state_path, state)


def _walk_strips(port, mock, n):
    """Send n matching requests, asserting each is stripped (exactly one
    upstream call whose body lacks context_management).

    Strip counters are in-memory-only (reset to zero on state-file load), so
    threshold tests reach the probe by walking the counter in memory.
    """
    for i in range(n):
        before = len(mock["requests"])
        status, _ = _send(port, _cm_request())
        reqs = mock["requests"][before:]
        if status != 200 or len(reqs) != 1 or _cm_count(reqs) != 0:
            fail("stripped request %d unexpected (%s, %d calls, %d with cm)"
                 % (i + 1, status, len(reqs), _cm_count(reqs)))
            return False
    return True


# ---------------------------------------------------------------------------
# A. Persistence / state
# ---------------------------------------------------------------------------

def test_compat_state_load_missing_file():
    """Missing state file means empty state: discovery still works and no
    startup failure occurs."""
    print("\n--- Test: Compat State Load Missing File ---")
    state_dir, state_path = _make_state_dir()
    responders = {"p": _reject_unstripped_responder()}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
        _start_compat_proxy(responders, state_path)
    if proc is None:
        shutil.rmtree(state_dir, ignore_errors=True)
        fail("Failed to set up test")
        return
    try:
        if os.path.exists(state_path):
            fail("state file should not exist before any request")
        else:
            pass_("state file absent at startup")
        status, _ = _send(proxy_port, _cm_request())
        if status != 200:
            fail("learning request failed with status %s (missing state file "
                 "must fail open, not break the proxy)" % status)
            return
        reqs = mock_servers["p"]["requests"]
        if len(reqs) != 2 or _cm_count(reqs) != 1:
            fail("expected discovery 400 + stripped 2xx (2 upstream calls, 1 "
                 "with context_management), got %d calls (%d with cm)"
                 % (len(reqs), _cm_count(reqs)))
        else:
            pass_("missing state file: discovery and stripped retry proceed")
    finally:
        cleanup()
        shutil.rmtree(state_dir, ignore_errors=True)


def test_compat_state_load_corrupt_fails_open():
    """A corrupt (non-JSON) state file warns and fails open with empty
    state: requests forward unchanged and the proxy does not crash."""
    print("\n--- Test: Compat State Load Corrupt Fails Open ---")
    state_dir, state_path = _make_state_dir()
    with open(state_path, "w") as f:
        f.write("{not valid json!!")
    responders = {"p": _reject_unstripped_responder()}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
        _start_compat_proxy(responders, state_path)
    if proc is None:
        shutil.rmtree(state_dir, ignore_errors=True)
        fail("Failed to set up test (corrupt state file must not prevent "
             "startup)")
        return
    try:
        status, _ = _send(proxy_port, _cm_request())
        if status != 200:
            fail("corrupt state file broke the proxy (status %s)" % status)
            return
        reqs = mock_servers["p"]["requests"]
        if len(reqs) != 2 or _cm_count(reqs) != 1:
            fail("corrupt state: expected discovery + stripped retry, got %d "
                 "calls (%d with cm)" % (len(reqs), _cm_count(reqs)))
        else:
            pass_("corrupt state file fails open with empty state")
    finally:
        cleanup()
        shutil.rmtree(state_dir, ignore_errors=True)


def test_compat_state_load_unreadable_fails_open():
    """An unreadable state path (a directory) fails open with empty state."""
    print("\n--- Test: Compat State Load Unreadable Fails Open ---")
    state_dir = tempfile.mkdtemp(prefix="compat_state_dir_")
    state_path = os.path.join(state_dir, "is-a-directory")
    os.mkdir(state_path)
    responders = {"p": _reject_unstripped_responder()}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
        _start_compat_proxy(responders, state_path)
    if proc is None:
        os.rmdir(state_path)
        shutil.rmtree(state_dir, ignore_errors=True)
        fail("Failed to set up test (unreadable state path must not prevent "
             "startup)")
        return
    try:
        status, _ = _send(proxy_port, _cm_request())
        if status != 200:
            fail("unreadable state path broke the proxy (status %s)" % status)
            return
        reqs = mock_servers["p"]["requests"]
        if len(reqs) != 2 or _cm_count(reqs) != 1:
            fail("unreadable state: expected discovery + stripped retry, got "
                 "%d calls (%d with cm)" % (len(reqs), _cm_count(reqs)))
        else:
            pass_("unreadable state path fails open with empty state")
    finally:
        cleanup()
        os.rmdir(state_path)
        shutil.rmtree(state_dir, ignore_errors=True)


# One valid entry body per registered feature: the shape that feature's own
# validator must accept, expressed in the feature's own vocabulary.
VALID_ENTRY_BODIES = {
    "context_management": {
        "provider": "p", "mode": "anthropic", "actual_model": "m",
        "feature": "context_management", "state": "unsupported",
        "threshold": 32, "strip_counter": 0, "probation_successes": 0,
    },
    "reasoning_field": {
        "provider": "p", "mode": "chat", "actual_model": "m",
        "feature": "reasoning_field", "selection": "reasoning_content",
    },
}


def test_compat_state_roundtrip():
    """A learned entry persists with plan-pinned schema fields and survives a
    proxy restart (stripping resumes immediately); every registered feature's
    entry validates through its own descriptor and an absent entry resolves to
    that descriptor's default."""
    print("\n--- Test: Compat State Roundtrip ---")
    state_dir, state_path = _bootstrap_learned_state()
    try:
        state = _read_state_file(state_path)
        if state is None:
            fail("learned state was not persisted")
            return
        entries = _entry_values(_entries(state))
        if not entries:
            fail("persisted state has no entries")
            return
        entry = [e for e in entries
                 if isinstance(e, dict)
                 and e.get("feature") == "context_management"]
        if not entry:
            fail("no context_management entry in persisted state")
            return
        e = entry[0]
        missing = {"provider", "mode", "actual_model", "feature", "state",
                   "threshold"} - set(e)
        if missing:
            fail("persisted entry missing plan-pinned fields: %s"
                 % sorted(missing))
            return
        if e["state"] != "unsupported":
            fail("expected learned state 'unsupported', got %r" % e["state"])
            return
        pass_("learned entry persisted with identity + state fields")

        # Restart against the same file: stripping must resume immediately.
        responders = {"p": _reject_unstripped_responder()}
        temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
            _start_compat_proxy(responders, state_path)
        if proc is None:
            fail("restart proxy failed to start")
            return
        try:
            status, _ = _send(proxy_port, _cm_request())
            if status != 200:
                fail("post-restart request failed (status %s)" % status)
                return
            reqs = mock_servers["p"]["requests"]
            if len(reqs) == 1 and _cm_count(reqs) == 0:
                pass_("restart: entry reloaded, request stripped immediately")
            else:
                fail("restart: expected 1 stripped upstream call, got %d "
                     "calls (%d with cm)" % (len(reqs), _cm_count(reqs)))
        finally:
            cleanup()

        # Per-descriptor validation branch: every registered feature's entry
        # survives the loader under the key derived from its own identity (the
        # file key it was stored under is never used as a key), and each
        # descriptor's own field set is preserved.
        import claude_retry_proxy.server as srv
        import claude_retry_proxy.compat as compat
        saved_path = srv.SETTINGS.feature_compat_file
        try:
            for feature_name in sorted(compat.COMPAT_FEATURES):
                body = VALID_ENTRY_BODIES[feature_name]
                validated = compat._compat_validate_entry(dict(body))
                if validated is None:
                    fail("%s entry rejected by its own descriptor"
                         % feature_name)
                    return
                missing = set(body) - set(validated)
                if missing:
                    fail("%s entry lost fields in validation: %s"
                         % (feature_name, sorted(missing)))
                    return
                fpath = os.path.join(
                    state_dir, "roundtrip-%s.json" % feature_name)
                with open(fpath, "w", encoding="utf-8") as f:
                    json.dump({"schema_version": 1, "entries": {
                        "not\x1fa\x1freal\x1fkey": dict(body)}}, f)
                srv.SETTINGS.feature_compat_file = fpath
                fresh = compat._CompatState()
                compat._load_compat_state(state=fresh)
                expect_key = (body["provider"], body["mode"],
                              body["actual_model"], body["feature"])
                if list(fresh.entries) != [expect_key]:
                    fail("%s entry did not load under its own identity key: "
                         "%r" % (feature_name, list(fresh.entries)))
                    return
                loaded = fresh.entries[expect_key]
                if set(loaded) != ALLOWED_STATE_KEYS_BY_FEATURE[feature_name]:
                    fail("%s loaded entry key set is wrong: %s"
                         % (feature_name, sorted(loaded)))
                    return
            pass_("per-descriptor validation: every registered feature "
                  "round-trips under its own identity with its own field set")
        finally:
            srv.SETTINGS.feature_compat_file = saved_path

        # An absent entry resolves to the descriptor's own default.
        selection, active = compat._reasoning_entry_selection(
            ("absent-provider", "chat", "absent-model", "reasoning_field"))
        if selection != "none" or not active:
            fail("absent reasoning entry must resolve to the 'none' default, "
                 "got (%r, %r)" % (selection, active))
            return
        if compat._compat_get(("absent-provider", "anthropic",
                               "absent-model",
                               "context_management")) is not None:
            fail("absent context_management entry must resolve to no entry")
            return
        pass_("absent entries resolve to each descriptor's own default")
    finally:
        shutil.rmtree(state_dir, ignore_errors=True)


def test_compat_state_one_bad_entry_keeps_valid():
    """One invalid entry among good ones: the bad entry is dropped (treated
    as absent), the valid entry keeps stripping."""
    print("\n--- Test: Compat State One Bad Entry Keeps Valid ---")
    # Learn entries for two models on the same provider, then corrupt one.
    state_dir, state_path = _bootstrap_learned_state(
        model="claude-sonnet-5")
    try:
        # Bootstrap a second learned entry by directly invoking a second
        # proxy against the same file with a different model.
        tiers = {
            "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
            "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
            "opus": {"provider": "p", "model": "claude-opus-5"},
        }
        responders = {"p": _reject_unstripped_responder()}
        temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
            _start_compat_proxy(responders, state_path, tiers=tiers)
        if proc is None:
            fail("second bootstrap proxy failed to start")
            return
        try:
            status, _ = _send(proxy_port, _cm_request(model="haiku"))
            if status != 200:
                fail("second bootstrap learning request failed (%s)" % status)
                return
        finally:
            cleanup()

        before = _read_state_file(state_path)
        n_cm = sum(1 for e in _entry_values(_entries(before))
                   if isinstance(e, dict)
                   and e.get("feature") == "context_management")
        if n_cm < 2:
            fail("expected 2 learned entries, found %d" % n_cm)
            return

        def corrupt(entry):
            if entry.get("actual_model") == "claude-haiku-4-5":
                entry["state"] = "bogus-state-value"

        _mutate_entry(state_path, corrupt, expect_count=2)
        after = _read_state_file(state_path)
        n_cm_after = sum(1 for e in _entry_values(_entries(after))
                         if isinstance(e, dict)
                         and e.get("feature") == "context_management")
        if n_cm_after < 1:
            fail("corruption pass dropped all entries")
            return

        # Restart: sonnet entry valid -> stripped; haiku entry invalid ->
        # treated as absent -> unstripped.
        responders = {"p": _reject_unstripped_responder()}
        temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
            _start_compat_proxy(responders, state_path, tiers=tiers)
        if proc is None:
            fail("restart proxy failed to start")
            return
        try:
            status, _ = _send(proxy_port, _cm_request(model="sonnet"))
            if status != 200:
                fail("valid-entry request failed (%s)" % status)
                return
            reqs = mock_servers["p"]["requests"]
            if len(reqs) == 1 and _cm_count(reqs) == 0:
                pass_("valid entry still strips after one-bad-entry load")
            else:
                fail("valid entry not honored (%d calls, %d with cm)"
                     % (len(reqs), _cm_count(reqs)))
                return

            status, _ = _send(proxy_port, _cm_request(model="haiku"))
            if status != 200:
                fail("invalid-entry request failed (%s)" % status)
                return
            reqs = mock_servers["p"]["requests"]
            # haiku request: unstripped -> 400 -> compat retry stripped 2xx
            # (discovery runs fresh because the bad entry was dropped).
            if len(reqs) == 3 and _cm_count(reqs) == 1:
                pass_("invalid entry treated as absent (fresh discovery)")
            else:
                fail("invalid entry not dropped: %d calls, %d with cm"
                     % (len(reqs), _cm_count(reqs)))
        finally:
            cleanup()
    finally:
        shutil.rmtree(state_dir, ignore_errors=True)


def test_compat_state_unknown_feature_ignored():
    """A foreign-feature entry in the state file is tolerated (forward-compat)
    and never affects context_management behavior."""
    print("\n--- Test: Compat State Unknown Feature Ignored ---")
    state_dir, state_path = _bootstrap_learned_state()
    try:
        state = _read_state_file(state_path)
        if state is None:
            fail("bootstrap state unreadable")
            return
        # Inject an entry for a feature the policy registry does not define.
        # The loader must keep the file's valid entries and treat the foreign
        # entry as inert — context_management behavior is unaffected.
        foreign_key = "foreign-provider\x1fanthropic\x1fforeign-model\x1fsome_future_beta_field"
        state.setdefault("entries", {})[foreign_key] = {
            "schema_version": 1,
            "provider": "foreign-provider",
            "mode": "anthropic",
            "actual_model": "foreign-model",
            "feature": "some_future_beta_field",
            "state": "unsupported",
            "threshold": 32,
            "strip_counter": 0,
            "probation_successes": 0,
        }
        _write_state_file(state_path, state)

        # The foreign entry must not be loaded into state at all (plan load
        # contract: "unknown feature keys -> ignore (forward-compat)").
        import claude_retry_proxy.server as srv
        import claude_retry_proxy.compat as compat
        saved_path = srv.SETTINGS.feature_compat_file
        saved_entries = compat._state.entries
        try:
            srv.SETTINGS.feature_compat_file = state_path
            srv._load_compat_state()
            loaded_features = [e.get("feature")
                               for e in compat._state.entries.values()]
            if "some_future_beta_field" in loaded_features:
                fail("foreign-feature entry was loaded into state")
                return
            if "context_management" not in loaded_features:
                fail("learned context_management entry not loaded")
                return
            pass_("foreign-feature entry not loaded; learned entry loaded")
        finally:
            srv.SETTINGS.feature_compat_file = saved_path
            compat._state.entries = saved_entries

        responders = {"p": _reject_unstripped_responder()}
        temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
            _start_compat_proxy(responders, state_path)
        if proc is None:
            fail("restart proxy failed to start")
            return
        try:
            status, _ = _send(proxy_port, _cm_request())
            if status != 200:
                fail("request failed (%s)" % status)
                return
            reqs = mock_servers["p"]["requests"]
            # The learned context_management entry still applies (stripped,
            # 1 call); the foreign entry neither breaks loading nor strips.
            if len(reqs) == 1 and _cm_count(reqs) == 0:
                pass_("foreign-feature entry inert; learned entry still "
                      "strips")
            else:
                fail("foreign-feature entry changed behavior: %d calls (%d "
                     "with cm)" % (len(reqs), _cm_count(reqs)))
        finally:
            cleanup()
    finally:
        shutil.rmtree(state_dir, ignore_errors=True)


def test_compat_state_higher_version_fails_open():
    """Unknown or absent top-level schema_version: warn + fail open with
    empty state; fresh learning still works."""
    print("\n--- Test: Compat State Higher Version Fails Open ---")
    for label, mutate in (
        ("higher-version", lambda s: s.__setitem__("schema_version", 999)),
        ("absent-version", lambda s: s.pop("schema_version", None)),
    ):
        state_dir, state_path = _bootstrap_learned_state()
        try:
            state = _read_state_file(state_path)
            if state is None:
                fail("bootstrap state unreadable (%s)" % label)
                return
            mutate(state)
            _write_state_file(state_path, state)
            responders = {"p": _reject_unstripped_responder()}
            temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
                _start_compat_proxy(responders, state_path)
            if proc is None:
                fail("restart proxy failed to start (%s)" % label)
                return
            try:
                status, _ = _send(proxy_port, _cm_request())
                if status != 200:
                    fail("request failed (%s, status %s)" % (label, status))
                    return
                reqs = mock_servers["p"]["requests"]
                if len(reqs) == 2 and _cm_count(reqs) == 1:
                    pass_("%s: fail-open empty state, fresh discovery ran"
                          % label)
                else:
                    fail("%s: expected fresh discovery, got %d calls (%d with "
                         "cm)" % (label, len(reqs), _cm_count(reqs)))
            finally:
                cleanup()
        finally:
            shutil.rmtree(state_dir, ignore_errors=True)


def test_compat_state_invalid_entries_normalized():
    """Out-of-range counters and off-ladder thresholds do not disable the
    entry: values are normalized and the entry keeps stripping."""
    print("\n--- Test: Compat State Invalid Entries Normalized ---")
    state_dir, state_path = _bootstrap_learned_state()
    try:
        def _degrade(entry):
            entry["strip_counter"] = -5
            entry["threshold"] = 50
            entry["probation_successes"] = 99

        _mutate_entry(state_path, _degrade)
        responders = {"p": _reject_unstripped_responder()}
        temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
            _start_compat_proxy(responders, state_path)
        if proc is None:
            fail("restart proxy failed to start")
            return
        try:
            status, _ = _send(proxy_port, _cm_request())
            if status != 200:
                fail("request failed (%s)" % status)
                return
            reqs = mock_servers["p"]["requests"]
            if len(reqs) == 1 and _cm_count(reqs) == 0:
                pass_("degenerate entry normalized, still strips")
            else:
                fail("degenerate entry disabled stripping: %d calls (%d with "
                     "cm)" % (len(reqs), _cm_count(reqs)))
        finally:
            cleanup()
    finally:
        shutil.rmtree(state_dir, ignore_errors=True)


def test_compat_state_atomic_write():
    """State writes are atomic with a unique temp name: after state-machine
    transitions, the state directory holds only the final file and it is
    valid JSON."""
    print("\n--- Test: Compat State Atomic Write ---")
    state_dir, state_path = _bootstrap_learned_state()
    try:
        responders = {"p": _reject_unstripped_responder()}
        temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
            _start_compat_proxy(responders, state_path)
        if proc is None:
            fail("restart proxy failed to start")
            return
        try:
            # Walk 31 stripped requests, then the 32nd (counter-reaching) is
            # the probe whose rejection doubles the threshold (a persisted
            # write).
            if not _walk_strips(proxy_port, mock_servers["p"], 31):
                return
            status, _ = _send(proxy_port, _cm_request())
            if status != 200:
                fail("probe request failed (%s)" % status)
                return
            reqs = mock_servers["p"]["requests"]
            if not (len(reqs) == 33 and _cm_count(reqs) == 1):
                fail("probe pattern wrong: %d calls (%d with cm)"
                     % (len(reqs), _cm_count(reqs)))
                return
            state = _read_state_file(state_path)
            if state is None:
                fail("state file is not valid JSON after transitions")
                return
            files = os.listdir(state_dir)
            if files != [os.path.basename(state_path)]:
                fail("state directory has leftover temp files: %s" % files)
            else:
                pass_("atomic write: no temp remnants, file valid after "
                      "learning + threshold-doubling writes")
        finally:
            cleanup()
    finally:
        shutil.rmtree(state_dir, ignore_errors=True)


def test_compat_state_write_metadata_only():
    """Persisted state contains no request values, no prompt text, no raw
    error bodies — schema fields only."""
    print("\n--- Test: Compat State Write Metadata Only ---")
    state_dir, state_path = _bootstrap_learned_state()
    try:
        with open(state_path, "r", encoding="utf-8") as f:
            raw = f.read()
        for marker in (CM_MARKER, ERROR_MARKER, UPSTREAM_ERROR_MARKER,
                       "hello"):
            if marker in raw:
                fail("persisted state leaks content marker %r" % marker)
                return
        state = json.loads(raw)
        for entry in _entry_values(_entries(state)):
            if not isinstance(entry, dict):
                continue
            allowed = ALLOWED_STATE_KEYS_BY_FEATURE.get(entry.get("feature"))
            if allowed is None:
                fail("persisted entry has an unregistered feature: %r"
                     % (entry.get("feature"),))
                return
            extra = set(entry) - allowed
            if extra:
                fail("persisted entry for feature %r has unexpected keys: %s"
                     % (entry.get("feature"), sorted(extra)))
                return
        pass_("persisted state is metadata-only (schema fields, no content)")
    finally:
        shutil.rmtree(state_dir, ignore_errors=True)


def test_compat_state_persist_failure_retains_memory():
    """When persistence fails (unwritable path), in-memory learning still
    works and compatibility_persist_failed is rate-limited."""
    print("\n--- Test: Compat State Persist Failure Retains Memory ---")
    state_dir = tempfile.mkdtemp(prefix="compat_state_unwritable_")
    # A directory used AS the state file: loads fail (unreadable -> fail
    # open) and os.replace onto it fails with OSError on every persist — on
    # both POSIX and Windows.
    state_path = os.path.join(state_dir, "state-is-a-directory")
    os.mkdir(state_path)
    responders = {"p": _reject_unstripped_responder()}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
        _start_compat_proxy(responders, state_path)
    if proc is None:
        shutil.rmtree(state_dir, ignore_errors=True)
        fail("Failed to set up test")
        return
    try:
        status, _ = _send(proxy_port, _cm_request())
        if status != 200:
            fail("learning request failed (%s)" % status)
            return
        status, _ = _send(proxy_port, _cm_request())
        if status != 200:
            fail("second request failed (%s)" % status)
            return
        reqs = mock_servers["p"]["requests"]
        # With persistence broken, learning still works in memory: request 2
        # is stripped (1 call). If persistence failure aborted learning,
        # request 2 would re-run discovery (2 calls).
        if len(reqs) == 3 and _cm_count(reqs) == 1:
            pass_("persist failure: in-memory learning retained (request 2 "
                  "stripped)")
        else:
            fail("persist failure lost in-memory state: %d calls (%d with cm)"
                 % (len(reqs), _cm_count(reqs)))
            return
        events = _compat_trace_events(trace_file, "compatibility_persist_failed")
        if not events:
            warn("no compatibility_persist_failed event observed (write may "
                 "have silently succeeded)")
        else:
            pass_("compatibility_persist_failed emitted (%d event(s))"
                  % len(events))
    finally:
        cleanup()
        shutil.rmtree(state_dir, ignore_errors=True)


def test_compat_state_concurrent_updates_no_loss():
    """Concurrent stripped requests keep counter integrity: every client gets
    a 2xx, no more than the expected probe requests go unstripped, and state
    stays valid."""
    print("\n--- Test: Compat State Concurrent Updates No Loss ---")
    state_dir, state_path = _bootstrap_learned_state()
    try:
        responders = {"p": _reject_unstripped_responder()}
        temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
            _start_compat_proxy(responders, state_path)
        if proc is None:
            fail("restart proxy failed to start")
            return
        try:
            results = []

            def worker():
                s, _ = _send(proxy_port, _cm_request())
                results.append(s)

            threads = [threading.Thread(target=worker) for _ in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(30)
            if len(results) != 8:
                fail("only %d/8 concurrent requests completed" % len(results))
                return
            if all(s == 200 for s in results):
                pass_("all 8 concurrent requests succeeded")
            else:
                fail("concurrent requests returned %s" % results)
                return
            reqs = mock_servers["p"]["requests"]
            unstripped = _cm_count(reqs)
            if unstripped <= 2:
                pass_("counter integrity held: %d probe request(s) out of %d "
                      "upstream calls" % (unstripped, len(reqs)))
            else:
                fail("too many unstripped calls (%d of %d) — lost counter "
                     "updates" % (unstripped, len(reqs)))
                return
            state = _read_state_file(state_path)
            if state is None:
                fail("state file corrupt after concurrent updates")
            else:
                pass_("state file valid after concurrent updates")
        finally:
            cleanup()
    finally:
        shutil.rmtree(state_dir, ignore_errors=True)


def test_compat_state_key_isolation():
    """Learned state for one (provider, mode, model) key does not strip other
    keys' requests."""
    print("\n--- Test: Compat State Key Isolation ---")
    state_dir, state_path = _bootstrap_learned_state(
        model="claude-sonnet-5")
    try:
        tiers = {
            "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
            "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
            "opus": {"provider": "p", "model": "claude-opus-5"},
        }
        responders = {"p": _reject_unstripped_responder()}
        temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
            _start_compat_proxy(responders, state_path, tiers=tiers)
        if proc is None:
            fail("restart proxy failed to start")
            return
        try:
            # sonnet (learned key) -> stripped, 1 call.
            status, _ = _send(proxy_port, _cm_request(model="sonnet"))
            reqs = mock_servers["p"]["requests"]
            if status == 200 and len(reqs) == 1 and _cm_count(reqs) == 0:
                pass_("learned key strips")
            else:
                fail("learned key did not strip (%s, %d calls)"
                     % (status, len(reqs)))
                return
            # haiku (different model, same provider) -> no entry, fresh
            # discovery: 2 calls.
            before = len(reqs)
            status, _ = _send(proxy_port, _cm_request(model="haiku"))
            reqs = mock_servers["p"]["requests"]
            new = reqs[before:]
            if status == 200 and len(new) == 2 and _cm_count(new) == 1:
                pass_("different model key not affected (fresh discovery)")
            else:
                fail("model isolation broken: %d new calls, %d with cm"
                     % (len(new), _cm_count(new)))
        finally:
            cleanup()
    finally:
        shutil.rmtree(state_dir, ignore_errors=True)


def test_compat_locks_present():
    """The plan-named locks exist and _compat_retry_lock is non-blocking."""
    print("\n--- Test: Compat Locks Present ---")
    import claude_retry_proxy.server as srv
    if not hasattr(srv, "_compat_state_lock"):
        fail("server module has no _compat_state_lock")
        return
    if not hasattr(srv, "_compat_retry_lock"):
        fail("server module has no _compat_retry_lock")
        return
    pass_("both compatibility locks present")
    lock = srv._compat_retry_lock
    if lock.acquire(blocking=False):
        try:
            if lock.acquire(blocking=False):
                lock.release()
                fail("_compat_retry_lock allowed a second non-blocking "
                     "acquire (must be exclusive)")
            else:
                pass_("_compat_retry_lock is exclusive under non-blocking "
                      "acquire")
        finally:
            lock.release()
    else:
        fail("_compat_retry_lock could not be acquired when free")


def test_compat_state_object_shape():
    """compat._state is a _CompatState singleton owning the two lock aliases;
    explicit state injection isolates state operations from the singleton."""
    print("\n--- Test: Compat State Object Shape ---")
    import claude_retry_proxy.server as srv
    import claude_retry_proxy.compat as compat
    if not isinstance(compat._state, compat._CompatState):
        fail("compat._state is not a _CompatState instance")
        return
    if compat._compat_state_lock is not compat._state.lock:
        fail("_compat_state_lock does not alias _state.lock")
        return
    if compat._compat_retry_lock is not compat._state.retry_lock:
        fail("_compat_retry_lock does not alias _state.retry_lock")
        return
    pass_("state singleton and lock aliases hold")

    state_dir, state_path = _make_state_dir()
    saved_path = srv.SETTINGS.feature_compat_file
    stub_key = "stub-provider\x1fanthropic\x1fstub-model\x1fcontext_management"
    stub_entry = {
        "schema_version": 1, "provider": "stub-provider",
        "mode": "anthropic", "actual_model": "stub-model",
        "feature": "context_management", "state": "unsupported",
        "threshold": 32, "strip_counter": 0,
        "probation_successes": 0,
    }
    try:
        # Injection isolation: load fills ONLY the injected state (valid
        # state file pinned via SETTINGS).
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump({"schema_version": 1, "entries": {stub_key: stub_entry}},
                      f)
        srv.SETTINGS.feature_compat_file = state_path
        fresh = compat._CompatState()
        compat._load_compat_state(state=fresh)
        if list(fresh.entries) != \
                [("stub-provider", "anthropic", "stub-model",
                  "context_management")]:
            fail("injected load did not fill fresh.entries: %r"
                 % (list(fresh.entries),))
            return
        if compat._state.entries != {}:
            fail("singleton entries changed by injected load")
            return
        pass_("valid state file loads into the injected object only")

        # Failure branch: a corrupt (non-JSON) file leaves the injected
        # object empty (fail-open) and the singleton untouched.
        garbage_path = state_path + ".garbage"
        with open(garbage_path, "w", encoding="utf-8") as f:
            f.write("this is not json")
        srv.SETTINGS.feature_compat_file = garbage_path
        untouched = dict(compat._state.entries)
        fresh2 = compat._CompatState()
        compat._load_compat_state(state=fresh2)
        if fresh2.entries != {}:
            fail("unreadable path polluted fresh2.entries: %r" % fresh2.entries)
            return
        if compat._state.entries != untouched:
            fail("unreadable path touched the singleton")
            return
        pass_("corrupt state file leaves the injected object empty; "
              "singleton untouched")

        # Injection isolation under _compat_update: a mutate returning
        # persist=False touches only the injected object (never the real
        # SETTINGS.feature_compat_file).
        key = ("stub-provider", "anthropic", "stub-model",
               "context_management")
        result2 = compat._compat_update(
            key, lambda cur: (dict(stub_entry), False), state=fresh2)
        if result2 != stub_entry:
            fail("_compat_update returned unexpected entry")
            return
        if key not in fresh2.entries:
            fail("injected _compat_update did not store into the injected "
                 "state")
            return
        if compat._state.entries != {}:
            fail("_compat_update wrote to the singleton instead of the "
                 "injected state")
            return
        pass_("injected _compat_update isolates state (persist=False)")
    finally:
        srv.SETTINGS.feature_compat_file = saved_path
        shutil.rmtree(state_dir, ignore_errors=True)


def test_compat_normalize_threshold_ladder():
    """Off-ladder thresholds snap onto the doubling ladder: the returned
    value is the largest ladder element <= value, clamped to
    [COMPAT_INITIAL_THRESHOLD, COMPAT_MAX_THRESHOLD]."""
    print("\n--- Test: Compat Normalize Threshold Ladder ---")
    import claude_retry_proxy.server as srv
    cases = [(50, 32), (100, 64), (5000, 4096), (32, 32), (4096, 4096),
             (33, 32)]
    for value, expected in cases:
        got = srv._compat_normalize_threshold(value)
        if got != expected:
            fail("_compat_normalize_threshold(%d) returned %r, expected %d"
                 % (value, got, expected))
            return
    pass_("thresholds snap onto the doubling ladder "
          "[32, 64, ..., 4096]")


def test_compat_temp_file_cleanup():
    """A failed os.replace leaves no temp file behind: the persist failure
    path unlinks the unique-named temp file."""
    print("\n--- Test: Compat Temp File Cleanup ---")
    from unittest import mock
    import claude_retry_proxy.server as srv
    import claude_retry_proxy.compat as compat
    state_dir, state_path = _make_state_dir()
    saved_path = srv.SETTINGS.feature_compat_file
    saved_entries = compat._state.entries
    try:
        srv.SETTINGS.feature_compat_file = state_path
        compat._state.entries = {
            ("p", "anthropic", "m", "context_management"): {
                "schema_version": 1, "provider": "p", "mode": "anthropic",
                "actual_model": "m", "feature": "context_management",
                "state": "unsupported", "threshold": 32,
                "strip_counter": 0, "probation_successes": 0,
            },
        }
        with mock.patch("os.replace", side_effect=OSError("disk full")):
            ok = srv._persist_compat_state_locked()
        if ok:
            fail("persist reported success despite the patched replace "
                 "failure")
            return
        leftovers = [f for f in os.listdir(state_dir) if f.endswith(".tmp")]
        if leftovers:
            fail("temp file leaked after persist failure: %s" % leftovers)
            return
        pass_("no temp file left after failed persist")
    finally:
        srv.SETTINGS.feature_compat_file = saved_path
        compat._state.entries = saved_entries
        shutil.rmtree(state_dir, ignore_errors=True)


def test_compat_field_stripped_trace_accuracy():
    """compatibility_field_stripped fires only for requests whose outbound
    body was actually stripped — the probe-owning request emits
    compatibility_probe_started instead, so the stripped-event count equals
    the real strip count."""
    print("\n--- Test: Compat Field Stripped Trace Accuracy ---")
    state_dir, state_path = _make_state_dir()
    responders = {"p": _reject_unstripped_responder()}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
        _start_compat_proxy(responders, state_path)
    if proc is None:
        shutil.rmtree(state_dir, ignore_errors=True)
        fail("Failed to set up test")
        return
    try:
        # Request 1 learns (400 + stripped 2xx). Requests 2-32: 31 stripped
        # requests (counter 1..31). Request 33 reaches the threshold and IS
        # the probe (unstripped, 400) + its stripped retry (2xx).
        _send(proxy_port, _cm_request())
        if not _walk_strips(proxy_port, mock_servers["p"], 31):
            return
        status, _ = _send(proxy_port, _cm_request())
        if status != 200:
            fail("probe request failed (%s)" % status)
            return
        stripped_events = _compat_trace_events(
            trace_file, "compatibility_field_stripped")
        probe_events = _compat_trace_events(
            trace_file, "compatibility_probe_started")
        rejected_events = _compat_trace_events(
            trace_file, "compatibility_probe_rejected")
        if len(stripped_events) != 31:
            fail("compatibility_field_stripped fired %d times (expected 31 "
                 "= actual strips, excluding the probe owner)"
                 % len(stripped_events))
            return
        if len(probe_events) != 1 or len(rejected_events) != 1:
            fail("probe events wrong (started=%d, rejected=%d, expected "
                 "1/1)" % (len(probe_events), len(rejected_events)))
            return
        pass_("stripped-event count equals actual strips (31); probe owner "
              "emitted probe_started instead")
    finally:
        cleanup()
        shutil.rmtree(state_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# B. Detector
# ---------------------------------------------------------------------------

def _detector_scenario(body, content_type="application/json",
                       include_cm=True, status=400):
    """Run one request against an upstream that always returns the given
    status/body. Returns (status, n_upstream_calls, n_with_cm)."""
    state_dir, state_path = _make_state_dir()

    def responder(info):
        return status, content_type, body

    responders = {"p": responder}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
        _start_compat_proxy(responders, state_path)
    try:
        if proc is None:
            fail("Failed to set up test")
            return 0, -1, -1
        status, _ = _send(proxy_port, _cm_request(include_cm=include_cm))
        reqs = mock_servers["p"]["requests"]
        return status, len(reqs), _cm_count(reqs)
    finally:
        try:
            cleanup()
        except Exception:
            pass
        shutil.rmtree(state_dir, ignore_errors=True)


def test_compat_detector_message_form():
    """The exact observed message-form 400 triggers exactly one stripped
    compatibility retry."""
    print("\n--- Test: Compat Detector Message Form ---")
    status, calls, with_cm = _detector_scenario(OBSERVED_400_BODY)
    if status != 400:
        fail("expected original 400 returned to client, got %s" % status)
    elif calls == 2 and with_cm == 1:
        pass_("message-form 400 triggered one stripped retry (2 upstream "
              "calls, 1 unstripped)")
    else:
        fail("message-form 400: expected 2 calls (1 unstripped), got %d "
             "calls (%d unstripped)" % (calls, calls - with_cm))


def test_compat_detector_structured():
    """A structured extra_forbidden 400 identifying the top-level field
    triggers exactly one stripped compatibility retry."""
    print("\n--- Test: Compat Detector Structured ---")
    status, calls, with_cm = _detector_scenario(STRUCTURED_400_BODY)
    if status != 400:
        fail("expected original 400 returned to client, got %s" % status)
    elif calls == 2 and with_cm == 1:
        pass_("structured extra_forbidden 400 triggered one stripped retry")
    else:
        fail("structured 400: expected 2 calls (1 unstripped), got %d calls "
             "(%d unstripped)" % (calls, calls - with_cm))


def test_compat_detector_nested_path_rejected():
    """A nested-path rejection (tools.0.input.context_management) does not
    trigger a compatibility retry."""
    print("\n--- Test: Compat Detector Nested Path Rejected ---")
    nested = json.dumps({
        "type": "error",
        "error": {
            "type": "invalid_request_error",
            "message": "tools.0.input.context_management: "
                       "Extra inputs are not permitted",
        },
    }).encode()
    status, calls, with_cm = _detector_scenario(nested)
    if status != 400:
        fail("expected 400 passthrough, got %s" % status)
    elif calls == 1:
        pass_("nested-path 400 passed through with no compatibility retry")
    else:
        fail("nested-path 400 triggered %d upstream calls (expected 1)"
             % calls)
        return
    # Structured variant: a nested loc path must not match either.
    structured_nested = json.dumps({
        "type": "error",
        "error": {
            "type": "invalid_request_error",
            "code": "extra_forbidden",
            "loc": ["body", "tools", "0", "context_management"],
        },
    }).encode()
    status, calls, with_cm = _detector_scenario(structured_nested)
    if calls == 1:
        pass_("structured nested loc passed through with no retry")
    else:
        fail("structured nested loc triggered %d upstream calls (expected 1)"
             % calls)


def test_compat_detector_content_type_agnostic():
    """Detection is content-type-agnostic: a JSON body with a text/plain
    Content-Type still matches; a non-JSON body is inconclusive."""
    print("\n--- Test: Compat Detector Content Type Agnostic ---")
    status, calls, with_cm = _detector_scenario(
        OBSERVED_400_BODY, content_type="text/plain")
    if calls == 2 and with_cm == 1:
        pass_("text/plain Content-Type with JSON body still matched")
    else:
        fail("content-type-agnostic detection failed: %d calls (%d "
             "unstripped)" % (calls, calls - with_cm))
        return

    status, calls, with_cm = _detector_scenario(
        b"this is not json at all", content_type="application/json")
    if calls == 1:
        pass_("non-JSON 400 body inconclusive (no retry)")
    else:
        fail("non-JSON body triggered %d upstream calls (expected 1)" % calls)


def test_compat_detector_unrelated_400_rejected():
    """Broad invalid-request, auth, model, quota, and context-limit 400s
    never trigger a compatibility retry or learning, and neither does any
    entry of the shared rejected-body corpus."""
    print("\n--- Test: Compat Detector Unrelated 400 Rejected ---")
    unrelated = [
        ("broad-invalid-request", 400, {
            "type": "error",
            "error": {"type": "invalid_request_error",
                      "message": "Invalid request payload"},
        }),
        ("auth-error", 400, {
            "type": "error",
            "error": {"type": "authentication_error",
                      "message": "invalid x-api-key"},
        }),
        ("model-not-found", 400, {
            "type": "error",
            "error": {"type": "not_found_error",
                      "message": "model not found: claude-sonnet-5"},
        }),
        ("quota", 400, {
            "type": "error",
            "error": {"type": "billing_error",
                      "message": "quota exceeded for this project"},
        }),
        ("context-limit", 400, {
            "type": "error",
            "error": {"type": "invalid_request_error",
                      "message": "prompt is too long: 250000 tokens > "
                                 "200000 maximum"},
        }),
    ]
    corpus = [(label, status, json.dumps(payload).encode())
              for label, status, payload in unrelated]
    corpus += REJECTED_BODY_CORPUS
    for label, resp_status, body in corpus:
        got, calls, with_cm = _detector_scenario(body, status=resp_status)
        if calls != 1:
            fail("%s (status %d) triggered %d upstream calls (expected 1, "
                 "no compatibility retry)" % (label, resp_status, calls))
            return
        if got != resp_status:
            fail("%s: client saw status %d, expected the upstream's %d"
                 % (label, got, resp_status))
            return
    pass_("all unrelated forms and every shared-corpus reject passed "
          "through with no retry")


def test_compat_detector_presence_required():
    """A matching 400 for a request whose body lacks context_management does
    not trigger a compatibility retry."""
    print("\n--- Test: Compat Detector Presence Required ---")
    status, calls, with_cm = _detector_scenario(
        OBSERVED_400_BODY, include_cm=False)
    if calls == 1:
        pass_("no compatibility retry when the field is absent")
    else:
        fail("absent-field request produced %d upstream calls (expected 1)"
             % calls)


# ---------------------------------------------------------------------------
# C. Learn/strip flow (live proxy)
# ---------------------------------------------------------------------------

def test_compat_learn_on_400_stripped_2xx():
    """Initial 400 followed by a 2xx stripped retry learns unsupported
    state; the next matching request is stripped."""
    print("\n--- Test: Compat Learn On 400 Stripped 2xx ---")
    state_dir, state_path = _make_state_dir()
    responders = {"p": _reject_unstripped_responder()}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
        _start_compat_proxy(responders, state_path)
    if proc is None:
        shutil.rmtree(state_dir, ignore_errors=True)
        fail("Failed to set up test")
        return
    try:
        status, body = _send(proxy_port, _cm_request())
        if status != 200:
            fail("learning request returned %s (expected 2xx from stripped "
                 "retry)" % status)
            return
        reqs = mock_servers["p"]["requests"]
        if len(reqs) != 2 or _cm_count(reqs) != 1:
            fail("expected 400 + stripped 2xx (2 calls, 1 unstripped), got "
                 "%d calls (%d unstripped)" % (len(reqs),
                                               len(reqs) - _cm_count(reqs)))
            return
        pass_("discovery: 400 then successful stripped retry")
        if _read_state_file(state_path) is None:
            fail("state file not written after learning")
            return
        learned = _compat_trace_events(trace_file, "compatibility_learned")
        if not learned:
            fail("no compatibility_learned trace event")
            return
        pass_("compatibility_learned trace event emitted")
    finally:
        cleanup()
        shutil.rmtree(state_dir, ignore_errors=True)


def test_compat_no_learn_when_retry_fails():
    """When the stripped retry also fails, the client gets the original 400
    (model-rewritten) and nothing is learned."""
    print("\n--- Test: Compat No Learn When Retry Fails ---")
    state_dir, state_path = _make_state_dir()
    responders = {"p": _always_400_responder()}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
        _start_compat_proxy(responders, state_path)
    if proc is None:
        shutil.rmtree(state_dir, ignore_errors=True)
        fail("Failed to set up test")
        return
    try:
        status, body = _send(proxy_port, _cm_request())
        if status != 400:
            fail("expected original 400, got %s" % status)
            return
        if ERROR_MARKER.encode() not in body:
            fail("client did not receive the original upstream error body")
            return
        reqs = mock_servers["p"]["requests"]
        if len(reqs) != 2 or _cm_count(reqs) != 1:
            fail("expected exactly one compatibility retry (2 calls, 1 "
                 "unstripped), got %d calls" % len(reqs))
            return
        pass_("failed confirmation returns original 400 after one retry")
        state = _read_state_file(state_path)
        if state and _entry_values(_entries(state)):
            fail("state learned despite failed confirmation")
        else:
            pass_("no state learned on failed confirmation")
    finally:
        cleanup()
        shutil.rmtree(state_dir, ignore_errors=True)


def test_compat_failed_confirmation_suppression():
    """After 3 failed confirmations, compatibility retries are suppressed;
    discovery re-arms after a request-count interval (the threshold)."""
    print("\n--- Test: Compat Failed Confirmation Suppression ---")
    state_dir, state_path = _make_state_dir()
    responders = {"p": _always_400_responder()}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
        _start_compat_proxy(responders, state_path)
    if proc is None:
        shutil.rmtree(state_dir, ignore_errors=True)
        fail("Failed to set up test")
        return
    try:
        # Requests 1-3: each attempts one compatibility retry (2 calls each).
        for i in range(3):
            _send(proxy_port, _cm_request())
        reqs = mock_servers["p"]["requests"]
        if len(reqs) != 6:
            fail("expected 3 confirmations x 2 calls = 6, got %d" % len(reqs))
            return
        pass_("first 3 matching requests each attempted one retry")
        # Request 4+: suppressed (1 call each).
        _send(proxy_port, _cm_request())
        _send(proxy_port, _cm_request())
        reqs = mock_servers["p"]["requests"]
        if len(reqs) != 8:
            fail("suppressed requests still retrying: %d calls after 5 "
                 "requests (expected 8)" % len(reqs))
            return
        events = _compat_trace_events(
            trace_file, "compatibility_failed_confirmation_suppressed")
        if not events:
            fail("no compatibility_failed_confirmation_suppressed event")
            return
        pass_("retries suppressed after 3 failed confirmations (event "
              "emitted)")
        # Re-entry: after at most `threshold` (32) further matching requests,
        # discovery retries again (a 2-call request appears). Suppressed
        # requests cost 1 call each; the re-armed request costs 2.
        reentered_at = None
        baseline = len(mock_servers["p"]["requests"])
        for i in range(1, 35):
            _send(proxy_port, _cm_request())
            delta = len(mock_servers["p"]["requests"]) - baseline
            if delta >= i + 1:
                reentered_at = i
                break
        if reentered_at is None:
            fail("discovery never re-armed within threshold + margin")
        elif reentered_at <= 33:
            pass_("discovery re-armed after %d suppressed requests (interval "
                  "= threshold)" % reentered_at)
        else:
            fail("discovery re-armed after %d requests (expected <= 33)"
                 % reentered_at)
    finally:
        cleanup()
        shutil.rmtree(state_dir, ignore_errors=True)


def test_compat_strip_immediate_after_learn():
    """Learned state strips on the very next matching request."""
    print("\n--- Test: Compat Strip Immediate After Learn ---")
    state_dir, state_path = _make_state_dir()
    responders = {"p": _reject_unstripped_responder()}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
        _start_compat_proxy(responders, state_path)
    if proc is None:
        shutil.rmtree(state_dir, ignore_errors=True)
        fail("Failed to set up test")
        return
    try:
        _send(proxy_port, _cm_request())  # learn
        for i in range(3):
            before = len(mock_servers["p"]["requests"])
            status, _ = _send(proxy_port, _cm_request())
            reqs = mock_servers["p"]["requests"][before:]
            if status != 200 or len(reqs) != 1 or _cm_count(reqs) != 0:
                fail("post-learn request %d not stripped (%s, %d calls)"
                     % (i + 1, status, len(reqs)))
                return
        pass_("requests 2-4 stripped immediately after learning")
    finally:
        cleanup()
        shutil.rmtree(state_dir, ignore_errors=True)


def test_compat_key_isolation_live():
    """Learning through the live flow isolates by (provider, mode, model):
    other providers and models are unaffected."""
    print("\n--- Test: Compat Key Isolation Live ---")
    state_dir, state_path = _make_state_dir()
    p_port = find_free_port()
    q_port = find_free_port()
    tiers = {
        "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
        "opus": {"provider": "q", "model": "claude-opus-5"},
    }
    vendors = {
        "p": {"url": "http://127.0.0.1:%d" % p_port, "key": "K-p"},
        "q": {"url": "http://127.0.0.1:%d" % q_port, "key": "K-q"},
    }
    responders = {"p": _reject_unstripped_responder(),
                  "q": _reject_unstripped_responder()}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
        _start_compat_proxy(responders, state_path, tiers=tiers,
                            vendors=vendors)
    if proc is None:
        shutil.rmtree(state_dir, ignore_errors=True)
        fail("Failed to set up test")
        return
    try:
        # Learn on p/claude-sonnet-5 via the sonnet tier.
        _send(proxy_port, _cm_request(model="sonnet"))
        p_reqs = mock_servers["p"]["requests"]
        if len(p_reqs) != 2 or _cm_count(p_reqs) != 1:
            fail("learning on p failed (%d calls)" % len(p_reqs))
            return
        # Same provider, different model: haiku not stripped (fresh
        # discovery, 2 calls).
        before = len(p_reqs)
        _send(proxy_port, _cm_request(model="haiku"))
        new = p_reqs[before:]
        if len(new) != 2 or _cm_count(new) != 1:
            fail("model key not isolated: haiku made %d calls (%d unstripped)"
                 % (len(new), len(new) - _cm_count(new)))
            return
        pass_("different model on same provider unaffected")
        # Different provider: opus on q — not stripped (fresh discovery).
        _send(proxy_port, _cm_request(model="opus"))
        q_reqs = mock_servers["q"]["requests"]
        if len(q_reqs) == 2 and _cm_count(q_reqs) == 1:
            pass_("different provider unaffected (fresh discovery)")
        else:
            fail("provider isolation broken: q saw %d calls (%d unstripped)"
                 % (len(q_reqs), len(q_reqs) - _cm_count(q_reqs)))
    finally:
        cleanup()
        shutil.rmtree(state_dir, ignore_errors=True)


def test_compat_unknown_field_passthrough():
    """Other unknown fields are never stripped or learned — even when the
    upstream 400 names them with an extra-inputs message."""
    print("\n--- Test: Compat Unknown Field Passthrough ---")
    state_dir, state_path = _make_state_dir()
    other_400 = json.dumps({
        "type": "error",
        "error": {"type": "invalid_request_error",
                  "message": "future_beta_field: "
                             "Extra inputs are not permitted"},
    }).encode()

    def responder(info):
        return 400, "application/json", other_400

    responders = {"p": responder}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
        _start_compat_proxy(responders, state_path)
    if proc is None:
        shutil.rmtree(state_dir, ignore_errors=True)
        fail("Failed to set up test")
        return
    try:
        body = _cm_request(include_cm=False)
        body["future_beta_field"] = {"enabled": True}
        for i in range(2):
            status, _ = _send(proxy_port, body)
            if status != 400:
                fail("expected 400 passthrough, got %s" % status)
                return
        reqs = mock_servers["p"]["requests"]
        if len(reqs) != 2:
            fail("unknown-field 400 triggered %d upstream calls for 2 "
                 "requests (expected 2 — no retry)" % len(reqs))
            return
        state = _read_state_file(state_path)
        if state and _entry_values(_entries(state)):
            fail("state learned for a non-context_management field")
            return
        pass_("unknown field: no retry, no learning (constant-anchored)")
    finally:
        cleanup()
        shutil.rmtree(state_dir, ignore_errors=True)


def test_compat_non_matching_400_passthrough():
    """A non-matching 400 on a context_management request passes through
    with no compatibility retry and no state change."""
    print("\n--- Test: Compat Non Matching 400 Passthrough ---")
    state_dir, state_path = _make_state_dir()
    nonmatching = json.dumps({
        "type": "error",
        "error": {"type": "invalid_request_error",
                  "message": "messages.2: Field required"},
    }).encode()

    def responder(info):
        return 400, "application/json", nonmatching

    responders = {"p": responder}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
        _start_compat_proxy(responders, state_path)
    if proc is None:
        shutil.rmtree(state_dir, ignore_errors=True)
        fail("Failed to set up test")
        return
    try:
        status, body = _send(proxy_port, _cm_request())
        if status != 400:
            fail("expected 400, got %s" % status)
            return
        if b"Field required" not in body:
            fail("upstream error body not passed through to client")
            return
        reqs = mock_servers["p"]["requests"]
        if len(reqs) != 1:
            fail("non-matching 400 triggered %d upstream calls (expected 1)"
                 % len(reqs))
            return
        state = _read_state_file(state_path)
        if state and _entry_values(_entries(state)):
            fail("state learned from a non-matching 400")
            return
        pass_("non-matching 400: single call, body preserved, no learning")
    finally:
        cleanup()
        shutil.rmtree(state_dir, ignore_errors=True)


def test_compat_one_retry_cap():
    """At most one compatibility retry per client request
    (COMPAT_MAX_RETRIES_PER_REQUEST = 1)."""
    print("\n--- Test: Compat One Retry Cap ---")
    state_dir, state_path = _make_state_dir()
    responders = {"p": _always_400_responder()}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
        _start_compat_proxy(responders, state_path)
    if proc is None:
        shutil.rmtree(state_dir, ignore_errors=True)
        fail("Failed to set up test")
        return
    try:
        status, _ = _send(proxy_port, _cm_request())
        reqs = mock_servers["p"]["requests"]
        if len(reqs) != 2:
            fail("expected exactly 2 upstream calls (original + 1 retry), "
                 "got %d" % len(reqs))
            return
        pass_("exactly one compatibility retry per client request")
    finally:
        cleanup()
        shutil.rmtree(state_dir, ignore_errors=True)


def test_compat_count_tokens_excluded():
    """count_tokens requests skip compatibility processing entirely."""
    print("\n--- Test: Compat Count Tokens Excluded ---")
    state_dir, state_path = _make_state_dir()
    responders = {"p": _always_400_responder()}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
        _start_compat_proxy(responders, state_path)
    if proc is None:
        shutil.rmtree(state_dir, ignore_errors=True)
        fail("Failed to set up test")
        return
    try:
        status, _ = _send(proxy_port, _cm_request(),
                          path="/v1/messages/count_tokens")
        reqs = mock_servers["p"]["requests"]
        if len(reqs) != 1:
            fail("count_tokens 400 triggered %d upstream calls (expected 1, "
                 "no compatibility retry)" % len(reqs))
            return
        state = _read_state_file(state_path)
        if state and _entry_values(_entries(state)):
            fail("state learned from a count_tokens request")
            return
        pass_("count_tokens excluded from compatibility processing")
    finally:
        cleanup()
        shutil.rmtree(state_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# D. Thresholds / state machine
# ---------------------------------------------------------------------------

def test_compat_initial_threshold_probe():
    """Exactly 32 strips precede the first unstripped probe; the request
    whose strip count reaches the threshold IS the probe (unstripped), and
    its rejected result is retried stripped for its own client."""
    print("\n--- Test: Compat Initial Threshold Probe ---")
    state_dir, state_path = _bootstrap_learned_state()
    try:
        responders = {"p": _reject_unstripped_responder()}
        temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
            _start_compat_proxy(responders, state_path)
        if proc is None:
            fail("restart proxy failed to start")
            return
        try:
            # Fresh learned entry: counter 0, threshold 32. Requests 1-31
            # stripped (1 upstream call each).
            for i in range(31):
                before = len(mock_servers["p"]["requests"])
                status, _ = _send(proxy_port, _cm_request())
                reqs = mock_servers["p"]["requests"][before:]
                if status != 200 or len(reqs) != 1 or _cm_count(reqs) != 0:
                    fail("stripped request %d unexpected (%s, %d calls, %d "
                         "with cm)" % (i + 1, status, len(reqs),
                                       _cm_count(reqs)))
                    return
            pass_("31 requests stripped before any probe")
            # Request 32 reaches the threshold: it IS the unstripped probe
            # (400) followed by its own stripped retry (2xx).
            before = len(mock_servers["p"]["requests"])
            status, _ = _send(proxy_port, _cm_request())
            reqs = mock_servers["p"]["requests"][before:]
            if len(reqs) == 2 and _cm_count(reqs) == 1 and status == 200:
                pass_("request 32 was the unstripped probe (400) followed by "
                      "stripped retry (2xx)")
            else:
                fail("probe pattern wrong: %d calls, %d with cm, status %s"
                     % (len(reqs), _cm_count(reqs), status))
                return
            # Request 33: stripped again (counter reset at probe start).
            before = len(mock_servers["p"]["requests"])
            status, _ = _send(proxy_port, _cm_request())
            reqs = mock_servers["p"]["requests"][before:]
            if len(reqs) == 1 and _cm_count(reqs) == 0 and status == 200:
                pass_("request 33 stripped again after probe")
            else:
                fail("post-probe request not stripped: %d calls" % len(reqs))
        finally:
            cleanup()
    finally:
        shutil.rmtree(state_dir, ignore_errors=True)


def test_compat_rejection_doubles_threshold():
    """A rejected probe doubles the threshold (capped at max) and persists
    the doubled value."""
    print("\n--- Test: Compat Rejection Doubles Threshold ---")
    # Sub-case 1: 32 -> 64. Walk 31 stripped requests, then the 32nd reaches
    # the threshold and IS the probe.
    state_dir, state_path = _bootstrap_learned_state()
    try:
        responders = {"p": _reject_unstripped_responder()}
        temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
            _start_compat_proxy(responders, state_path)
        if proc is None:
            fail("restart proxy failed to start")
            return
        try:
            if not _walk_strips(proxy_port, mock_servers["p"], 31):
                return
            status, _ = _send(proxy_port, _cm_request())  # probe -> retry
            if status != 200:
                fail("probe request failed (%s)" % status)
                return
            state = _read_state_file(state_path)
            entry = next((e for e in _entry_values(_entries(state))
                          if isinstance(e, dict)
                          and e.get("feature") == "context_management"), None)
            if entry is None:
                fail("entry missing after probe rejection")
                return
            if entry.get("threshold") == 64:
                pass_("threshold doubled 32 -> 64 on rejection")
            else:
                fail("threshold after rejection = %r (expected 64)"
                     % entry.get("threshold"))
                return
        finally:
            cleanup()

        # Sub-case 2: cap at max. Thresholds persist across restarts (only
        # counters reset), so seed threshold 4096 directly and reach the
        # probe through a probation cycle (quantum 8): 7 strips, then the
        # 8th is the probe; its rejection doubles into the cap.
        state_dir2, state_path2 = _bootstrap_learned_state()

        def _at_cap(entry):
            entry["state"] = "probation"
            entry["threshold"] = 4096
            entry["probation_successes"] = 1
            entry["strip_counter"] = 0

        try:
            _mutate_entry(state_path2, _at_cap)
            responders = {"p": _reject_unstripped_responder()}
            temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
                _start_compat_proxy(responders, state_path2)
            if proc is None:
                fail("cap proxy failed to start")
                return
            try:
                if not _walk_strips(proxy_port, mock_servers["p"], 7):
                    return
                status, _ = _send(proxy_port, _cm_request())  # probe -> retry
                if status != 200:
                    fail("capped probe request failed (%s)" % status)
                    return
                state = _read_state_file(state_path2)
                entry = next((e for e in _entry_values(_entries(state))
                              if isinstance(e, dict)
                              and e.get("feature") == "context_management"),
                             None)
                if entry is None:
                    fail("entry missing after capped probe")
                    return
                if entry.get("threshold") == 4096:
                    pass_("threshold capped at 4096 (not doubled past max)")
                else:
                    fail("threshold after capped rejection = %r (expected "
                         "4096)" % entry.get("threshold"))
            finally:
                cleanup()
        finally:
            shutil.rmtree(state_dir2, ignore_errors=True)
    finally:
        shutil.rmtree(state_dir, ignore_errors=True)


def test_compat_probation_cycle():
    """After a successful probe, the entry enters probation: 8 strips, then
    the next probe; one success keeps probation."""
    print("\n--- Test: Compat Probation Cycle ---")
    state_dir, state_path = _make_state_dir()

    def ok_responder(info):
        return _ok_response(info)

    # Learn via a rejecting upstream first, then flip to always-2xx (provider
    # recovered) — but seeding is simpler: bootstrap-learn against a
    # rejecting upstream, then restart with the healthy responder.
    responders = {"p": _reject_unstripped_responder()}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
        _start_compat_proxy(responders, state_path)
    if proc is None:
        shutil.rmtree(state_dir, ignore_errors=True)
        fail("Failed to set up test")
        return
    try:
        status, _ = _send(proxy_port, _cm_request())
        if status != 200:
            fail("bootstrap learn failed (%s)" % status)
            return
    finally:
        cleanup()
    # Now the provider has recovered: always 2xx.
    responders = {"p": ok_responder}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
        _start_compat_proxy(responders, state_path)
    if proc is None:
        shutil.rmtree(state_dir, ignore_errors=True)
        fail("restart proxy failed to start")
        return
    try:
        # Requests 1-31 stripped; request 32 reaches the threshold and IS
        # the probe -> 2xx -> one probation success -> probation state.
        for i in range(31):
            before = len(mock_servers["p"]["requests"])
            _send(proxy_port, _cm_request())
            reqs = mock_servers["p"]["requests"][before:]
            if len(reqs) != 1 or _cm_count(reqs) != 0:
                fail("stripped request %d not stripped (%d calls)"
                     % (i + 1, len(reqs)))
                return
        before = len(mock_servers["p"]["requests"])
        status, _ = _send(proxy_port, _cm_request())
        reqs = mock_servers["p"]["requests"][before:]
        if not (len(reqs) == 1 and _cm_count(reqs) == 1 and status == 200):
            fail("request 32 not an unstripped successful probe (%d calls)"
                 % len(reqs))
            return
        state = _read_state_file(state_path)
        entry = next((e for e in _entry_values(_entries(state))
                      if isinstance(e, dict)
                      and e.get("feature") == "context_management"), None)
        if entry is None:
            fail("entry missing after first successful probe")
            return
        if entry.get("state") != "probation" or \
                entry.get("probation_successes") not in (0, 1):
            fail("after 1 success expected probation state, got %r/%r"
                 % (entry.get("state"), entry.get("probation_successes")))
            return
        pass_("first successful probe transitions to probation")
        # Probation quantum 8: 7 strips, then request 40 reaches 8 and IS
        # the probe -> 2xx -> second success -> delisted.
        for i in range(7):
            before = len(mock_servers["p"]["requests"])
            _send(proxy_port, _cm_request())
            reqs = mock_servers["p"]["requests"][before:]
            if len(reqs) != 1 or _cm_count(reqs) != 0:
                fail("probation strip %d not stripped (%d calls)"
                     % (i + 1, len(reqs)))
                return
        before = len(mock_servers["p"]["requests"])
        status, _ = _send(proxy_port, _cm_request())
        reqs = mock_servers["p"]["requests"][before:]
        if not (len(reqs) == 1 and _cm_count(reqs) == 1):
            fail("probation probe not unstripped (%d calls)" % len(reqs))
            return
        state = _read_state_file(state_path)
        entry = next((e for e in _entry_values(_entries(state))
                      if isinstance(e, dict)
                      and e.get("feature") == "context_management"), None)
        if entry is None:
            pass_("second success delisted the entry")
        else:
            fail("entry still present after 2 successes: %r" % entry)
    finally:
        cleanup()
        shutil.rmtree(state_dir, ignore_errors=True)


def test_compat_delist_after_two_successes():
    """A seeded probation entry earns two successful probes and is delisted;
    afterwards requests are no longer stripped.

    probation_successes is in-memory-only (reset on load, per plan), so both
    successes are earned in one session from the seeded probation state.
    """
    print("\n--- Test: Compat Delist After Two Successes ---")
    state_dir, state_path = _bootstrap_learned_state()
    try:
        # Seed the probation STATE (persists across restarts); the provider
        # has recovered: every upstream call returns 2xx, so probes succeed.
        def _probation(entry):
            entry["state"] = "probation"
            entry["threshold"] = 32
            entry["probation_successes"] = 0
            entry["strip_counter"] = 0

        _mutate_entry(state_path, _probation)
        responders = {"p": _ok_response}
        temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
            _start_compat_proxy(responders, state_path)
        if proc is None:
            fail("restart proxy failed to start")
            return
        try:
            # Probation quantum 8: walk 7 stripped requests, the 8th IS the
            # first successful probe.
            if not _walk_strips(proxy_port, mock_servers["p"], 7):
                return
            before = len(mock_servers["p"]["requests"])
            status, _ = _send(proxy_port, _cm_request())
            reqs = mock_servers["p"]["requests"][before:]
            if not (len(reqs) == 1 and _cm_count(reqs) == 1 and status == 200):
                fail("first probe not unstripped 2xx (%d calls, status %s)"
                     % (len(reqs), status))
                return
            state = _read_state_file(state_path)
            entry = next((e for e in _entry_values(_entries(state))
                          if isinstance(e, dict)
                          and e.get("feature") == "context_management"), None)
            if entry is None or entry.get("probation_successes") != 1:
                fail("after first success expected probation_successes=1, "
                     "got %r" % (entry,))
                return
            pass_("first probe success recorded (probation continues)")
            # Second cycle: 7 strips, 8th IS the second successful probe ->
            # delist.
            if not _walk_strips(proxy_port, mock_servers["p"], 7):
                return
            before = len(mock_servers["p"]["requests"])
            status, _ = _send(proxy_port, _cm_request())
            reqs = mock_servers["p"]["requests"][before:]
            if not (len(reqs) == 1 and _cm_count(reqs) == 1 and status == 200):
                fail("second probe not unstripped 2xx (%d calls, status %s)"
                     % (len(reqs), status))
                return
            state = _read_state_file(state_path)
            entry = next((e for e in _entry_values(_entries(state))
                          if isinstance(e, dict)
                          and e.get("feature") == "context_management"), None)
            if entry is not None:
                fail("entry not delisted after second success: %r" % entry)
                return
            pass_("second success delisted the entry")
            # Post-delist: request goes out unstripped (discovery path, 2xx,
            # nothing learned from a 2xx).
            before = len(mock_servers["p"]["requests"])
            status, _ = _send(proxy_port, _cm_request())
            reqs = mock_servers["p"]["requests"][before:]
            if len(reqs) == 1 and _cm_count(reqs) == 1 and status == 200:
                pass_("post-delist request forwarded unstripped")
            else:
                fail("post-delist request unexpected: %d calls (%d with cm)"
                     % (len(reqs), _cm_count(reqs)))
        finally:
            cleanup()
    finally:
        shutil.rmtree(state_dir, ignore_errors=True)


def test_compat_inconclusive_reschedules():
    """An inconclusive probe (non-matching 500) resets the strip counter and
    reschedules at the current threshold without doubling."""
    print("\n--- Test: Compat Inconclusive Reschedules ---")
    state_dir, state_path = _bootstrap_learned_state()
    try:
        def responder(info):
            try:
                has_cm = "context_management" in json.loads(info["body"])
            except Exception:
                has_cm = False
            if has_cm:
                return 500, "application/json", b'{"error":"internal"}'
            return _ok_response(info)

        responders = {"p": responder}
        temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
            _start_compat_proxy(responders, state_path)
        if proc is None:
            fail("restart proxy failed to start")
            return
        try:
            # Walk 31 stripped requests (2xx); request 32 reaches the
            # threshold and IS the probe — an unstripped 500 (inconclusive).
            if not _walk_strips(proxy_port, mock_servers["p"], 31):
                return
            before = len(mock_servers["p"]["requests"])
            status, _ = _send(proxy_port, _cm_request())
            reqs = mock_servers["p"]["requests"][before:]
            if not (len(reqs) == 1 and _cm_count(reqs) == 1 and status == 500):
                fail("probe not unstripped or result not passed through "
                     "(%d calls, status %s)" % (len(reqs), status))
                return
            state = _read_state_file(state_path)
            entry = next((e for e in _entry_values(_entries(state))
                          if isinstance(e, dict)
                          and e.get("feature") == "context_management"), None)
            if entry is None:
                fail("entry missing after inconclusive probe")
                return
            if entry.get("threshold") != 32:
                fail("inconclusive probe changed threshold to %r (expected "
                     "32)" % entry.get("threshold"))
                return
            pass_("inconclusive probe: threshold unchanged (no doubling)")
            # Counter reset to zero: 31 more stripped requests, then the
            # next probe.
            if not _walk_strips(proxy_port, mock_servers["p"], 31):
                return
            before = len(mock_servers["p"]["requests"])
            _send(proxy_port, _cm_request())
            reqs = mock_servers["p"]["requests"][before:]
            if len(reqs) == 1 and _cm_count(reqs) == 1:
                pass_("probe rescheduled after a full threshold of strips")
            else:
                fail("next probe not rescheduled at current threshold (%d "
                     "calls)" % len(reqs))
        finally:
            cleanup()
    finally:
        shutil.rmtree(state_dir, ignore_errors=True)


def test_compat_probe_counter_semantics():
    """Repeated rejection from probation resets probation to zero but keeps
    (and further doubles) the threshold — it never resets to base."""
    print("\n--- Test: Compat Probe Counter Semantics ---")
    state_dir, state_path = _bootstrap_learned_state()
    try:
        def _doubled_probation(entry):
            entry["state"] = "probation"
            entry["threshold"] = 64
            entry["probation_successes"] = 1
            entry["strip_counter"] = 0

        _mutate_entry(state_path, _doubled_probation)
        responders = {"p": _reject_unstripped_responder()}
        temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
            _start_compat_proxy(responders, state_path)
        if proc is None:
            fail("restart proxy failed to start")
            return
        try:
            # 7 probation strips (counter 1..7), then request 8 reaches the
            # probation quantum of 8 and IS the probe -> observed 400.
            for i in range(7):
                before = len(mock_servers["p"]["requests"])
                _send(proxy_port, _cm_request())
                reqs = mock_servers["p"]["requests"][before:]
                if len(reqs) != 1 or _cm_count(reqs) != 0:
                    fail("probation strip %d not stripped (%d calls)"
                         % (i + 1, len(reqs)))
                    return
            before = len(mock_servers["p"]["requests"])
            status, _ = _send(proxy_port, _cm_request())
            reqs = mock_servers["p"]["requests"][before:]
            if not (len(reqs) == 2 and _cm_count(reqs) == 1 and status == 200):
                fail("rejected probe pattern wrong (%d calls, status %s)"
                     % (len(reqs), status))
                return
            state = _read_state_file(state_path)
            entry = next((e for e in _entry_values(_entries(state))
                          if isinstance(e, dict)
                          and e.get("feature") == "context_management"), None)
            if entry is None:
                fail("entry missing after repeated rejection")
                return
            if entry.get("threshold") != 128:
                fail("rejection from probation: threshold %r (expected 128 = "
                     "64 doubled, not reset to base 32)"
                     % entry.get("threshold"))
                return
            if entry.get("state") != "unsupported" or \
                    entry.get("probation_successes") != 0:
                fail("rejection from probation: state=%r successes=%r "
                     "(expected unsupported/0)"
                     % (entry.get("state"), entry.get("probation_successes")))
                return
            pass_("repeated rejection: probation reset, threshold kept and "
                  "doubled (64 -> 128)")
        finally:
            cleanup()
    finally:
        shutil.rmtree(state_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# E. Concurrency / robustness
# ---------------------------------------------------------------------------

def test_compat_single_retry_global():
    """Concurrent first-time requests: exactly one compatibility retry
    occurs globally; losers receive the original 400.

    The same contention harness covers the reasoning feature, whose retry lock
    is its own: a walk denied that lock mutates no counter and writes no state,
    so the three-strike ladder still needs three consecutive complaints from
    the point of contention onward."""
    print("\n--- Test: Compat Single Retry Global ---")
    state_dir, state_path = _make_state_dir()

    def responder(info):
        try:
            has_cm = "context_management" in json.loads(info["body"])
        except Exception:
            has_cm = False
        if has_cm:
            time.sleep(1.0)
            return 400, "application/json", OBSERVED_400_BODY
        time.sleep(1.5)  # hold the retry lock wide open for the losers
        return _ok_response(info)

    def chat_responder(info):
        # Accepts only the advanced candidate, slowly, so the winning walk
        # holds the reasoning feature's own retry lock open while the
        # concurrent losers try to acquire it.
        if _sent_reasoning_field(info) == "reasoning_content":
            time.sleep(1.5)
            return _chat_ok_response(info)
        return 400, "application/json", REASONING_MESSAGE_400

    tiers = {
        "haiku": {"provider": "q", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
        "opus": {"provider": "p", "model": "claude-opus-5"},
    }
    vendors = {
        "p": {"url": "http://127.0.0.1:%d" % find_free_port(), "key": "K"},
        "q": _chat_vendor(find_free_port()),
    }
    responders = {"p": responder, "q": chat_responder}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
        _start_compat_proxy(responders, state_path, tiers=tiers,
                            vendors=vendors)
    if proc is None:
        shutil.rmtree(state_dir, ignore_errors=True)
        fail("Failed to set up test")
        return
    try:
        results = []

        def worker():
            s, _ = _send(proxy_port, _cm_request())
            results.append(s)

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(60)
        if len(results) != 5:
            fail("only %d/5 concurrent requests completed" % len(results))
            return
        reqs = mock_servers["p"]["requests"]
        unstripped = _cm_count(reqs)
        stripped = len(reqs) - unstripped
        n_ok = sum(1 for s in results if s == 200)
        if unstripped == 5 and stripped == 1 and n_ok == 1:
            pass_("global single-flight: 5 unstripped forwards, exactly 1 "
                  "stripped retry, 1 client succeeded")
        else:
            fail("single-flight broken: %d unstripped, %d stripped, %d/5 "
                 "clients 2xx" % (unstripped, stripped, n_ok))
            return
        state = _read_state_file(state_path)
        if state and _entry_values(_entries(state)):
            pass_("leader learned the entry")
        else:
            fail("leader's successful retry did not learn")
            return

        # --- reasoning feature: the same contention harness ----------------
        reasoning_results = []

        def reasoning_worker():
            s, _ = _send(proxy_port, _reasoning_request(model="haiku"))
            reasoning_results.append(s)

        threads = [threading.Thread(target=reasoning_worker)
                   for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(60)
        if len(reasoning_results) != 5:
            fail("only %d/5 concurrent reasoning requests completed"
                 % len(reasoning_results))
            return
        n_ok = sum(1 for s in reasoning_results if s == 200)
        if n_ok != 1:
            fail("reasoning single-flight broken: %d/5 clients 2xx (expected "
                 "exactly the lock holder)" % n_ok)
            return
        if _reasoning_entry(state_path, model="claude-haiku-4-5",
                            provider="q") is not None:
            fail("a contended walk persisted a selection")
            return
        pass_("contended walk: only the lock holder served, no state written")

        # The losers mutated no counter, so the ladder stands at the holder's
        # single complaint: two more consecutive complaints must arrive before
        # the switch can land.
        s, _ = _send(proxy_port, _reasoning_request(model="haiku"))
        if s != 200:
            fail("post-contention request failed (%s)" % s)
            return
        if _reasoning_entry(state_path, model="claude-haiku-4-5",
                            provider="q") is not None:
            fail("switch landed early — a contention loser mutated the "
                 "complaint counter")
            return
        _send(proxy_port, _reasoning_request(model="haiku"))
        if _reasoning_entry(state_path, model="claude-haiku-4-5",
                            provider="q") is None:
            fail("third consecutive complaint did not persist the switch")
            return
        pass_("contention losers mutated no counter: the switch still needed "
              "three consecutive complaints")
    finally:
        cleanup()
        shutil.rmtree(state_dir, ignore_errors=True)


def test_compat_retry_lock_released_on_exception():
    """An upstream failure during the compatibility retry releases the retry
    lock: later requests can still retry and learn."""
    print("\n--- Test: Compat Retry Lock Released On Exception ---")
    state_dir, state_path = _make_state_dir()
    mode = {"fail": True}

    def responder(info):
        try:
            has_cm = "context_management" in json.loads(info["body"])
        except Exception:
            has_cm = False
        if not has_cm:
            if mode["fail"]:
                raise RuntimeError("simulated upstream crash")
            return _ok_response(info)
        return 400, "application/json", OBSERVED_400_BODY

    responders = {"p": responder}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
        _start_compat_proxy(responders, state_path,
                            extra_env={"PROXY_MAX_RETRIES": "1",
                                       "PROXY_INITIAL_DELAY": "1"})
    if proc is None:
        shutil.rmtree(state_dir, ignore_errors=True)
        fail("Failed to set up test")
        return
    try:
        # Request 1: stripped retry crashes mid-flight -> client still gets
        # the original 400, and the lock must be released. PROXY_MAX_RETRIES=1
        # bounds the connection-error loop inside the retry so the test stays
        # fast (the loop itself is tracked in a separate issue).
        status, _ = _send(proxy_port, _cm_request())
        if status != 400:
            fail("expected original 400 after crashed retry, got %s" % status)
            return
        pass_("crashed retry returned the original 400")
        # Single-attempt bound: the compatibility retry must have made exactly
        # ONE upstream call (unstripped + 1 retry = 2 total). More calls mean
        # the compat retry re-entered the connection-error loop — see issue
        # compat-retry-not-single-attempt.
        reqs = mock_servers["p"]["requests"]
        if len(reqs) == 2:
            pass_("compatibility retry made exactly one upstream attempt")
        else:
            fail("compatibility retry made %d upstream calls (expected 2 "
                 "total: unstripped + single retry)" % len(reqs))
            return
        # Request 2: healthy upstream — the retry must be attempted (lock
        # free) and learning must succeed. Delta: unstripped 400 + stripped
        # 2xx = 2 calls, 1 with cm.
        mode["fail"] = False
        before = len(mock_servers["p"]["requests"])
        status, _ = _send(proxy_port, _cm_request())
        reqs = mock_servers["p"]["requests"][before:]
        if status != 200:
            fail("post-crash request failed (%s) — retry lock likely leaked"
                 % status)
            return
        if len(reqs) == 2 and _cm_count(reqs) == 1:
            pass_("lock released: post-crash retry ran and learned")
        else:
            fail("post-crash discovery did not retry correctly (%d calls, %d "
                 "with cm)" % (len(reqs), _cm_count(reqs)))
            return
        state = _read_state_file(state_path)
        if state and _entry_values(_entries(state)):
            pass_("learning recorded after crash recovery")
        else:
            fail("no state learned after recovery")
    finally:
        cleanup()
        shutil.rmtree(state_dir, ignore_errors=True)


def test_compat_config_swap_during_retry():
    """The compatibility retry uses the entry-time config snapshot: the
    in-flight request completes against its original provider, and the admin
    switch (drained afterwards) routes new requests elsewhere."""
    print("\n--- Test: Compat Config Swap During Retry ---")
    state_dir, state_path = _make_state_dir()
    p_port = find_free_port()
    q_port = find_free_port()
    tiers = {
        "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
        "opus": {"provider": "p", "model": "claude-opus-5"},
    }
    vendors = {
        "p": {"url": "http://127.0.0.1:%d" % p_port, "key": "K-p"},
        "q": {"url": "http://127.0.0.1:%d" % q_port, "key": "K-q"},
    }

    def p_responder(info):
        try:
            has_cm = "context_management" in json.loads(info["body"])
        except Exception:
            has_cm = False
        if has_cm:
            time.sleep(0.8)
            return 400, "application/json", OBSERVED_400_BODY
        return _ok_response(info)

    responders = {"p": p_responder, "q": _ok_response}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
        _start_compat_proxy(responders, state_path, tiers=tiers,
                            vendors=vendors)
    if proc is None:
        shutil.rmtree(state_dir, ignore_errors=True)
        fail("Failed to set up test")
        return
    try:
        result = {}

        def worker():
            s, _ = _send(proxy_port, _cm_request())
            result["status"] = s

        t = threading.Thread(target=worker)
        t.start()
        time.sleep(0.2)  # request is inside p's unstripped 400 hold
        switch_body = {
            "tiers": {
                "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
                "sonnet": {"provider": "q", "model": "claude-sonnet-5"},
                "opus": {"provider": "p", "model": "claude-opus-5"},
            }
        }
        switch_status, switch_data = _admin_post(
            proxy_port, "/admin/api/switch", switch_body)
        t.join(30)
        if switch_status != 200:
            fail("admin switch failed during in-flight retry: %s %s"
                 % (switch_status, switch_data))
            return
        if result.get("status") != 200:
            fail("in-flight request did not complete (status %s)"
                 % result.get("status"))
            return
        p_reqs = mock_servers["p"]["requests"]
        q_reqs = mock_servers["q"]["requests"]
        if len(p_reqs) == 2 and _cm_count(p_reqs) == 1 and not q_reqs:
            pass_("in-flight request completed on its original provider "
                  "(p): unstripped 400 + stripped 2xx")
        else:
            fail("retry routing wrong: p=%d calls (%d with cm), q=%d calls"
                 % (len(p_reqs), _cm_count(p_reqs), len(q_reqs)))
            return
        # Post-switch: sonnet goes to q. q has no learned entry, so the body
        # must arrive unstripped.
        status, _ = _send(proxy_port, _cm_request())
        q_reqs = mock_servers["q"]["requests"]
        if status == 200 and len(q_reqs) == 1 and _cm_count(q_reqs) == 1:
            pass_("post-switch requests route to q and are not stripped")
        else:
            fail("post-switch behavior wrong: status %s, q calls %d (%d with "
                 "cm)" % (status, len(q_reqs), _cm_count(q_reqs)))
    finally:
        cleanup()
        shutil.rmtree(state_dir, ignore_errors=True)


def test_compat_retry_stream_interaction():
    """Interaction with streaming and the existing retry loop: learning works
    from streamed 2xx (status-receipt evidence, no rollback on mid-stream
    failure), and the 429/503 loop composes with the compatibility retry."""
    print("\n--- Test: Compat Retry Stream Interaction ---")
    # (a) streamed 2xx stripped retry learns; next request stripped.
    state_dir, state_path = _make_state_dir()

    def sse_responder(info):
        try:
            has_cm = "context_management" in json.loads(info["body"])
        except Exception:
            has_cm = False
        if has_cm:
            return 400, "application/json", OBSERVED_400_BODY
        return _ok_response(info, "sse")

    responders = {"p": sse_responder}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
        _start_compat_proxy(responders, state_path)
    if proc is None:
        shutil.rmtree(state_dir, ignore_errors=True)
        fail("stream proxy failed to start")
        return
    try:
        status, content_type, raw = _send_proxy_request_stream(
            proxy_port, _cm_request())
        if status != 200 or "text/event-stream" not in content_type:
            fail("streamed learning request wrong (%s, %s)"
                 % (status, content_type))
            return
        before = len(mock_servers["p"]["requests"])
        status, _ = _send(proxy_port, _cm_request())
        reqs = mock_servers["p"]["requests"][before:]
        if status == 200 and len(reqs) == 1 and _cm_count(reqs) == 0:
            pass_("streamed 2xx retry learned; next request stripped")
        else:
            fail("streamed 2xx learning broken: status %s, %d calls"
                 % (status, len(reqs)))
            return
    finally:
        cleanup()
        shutil.rmtree(state_dir, ignore_errors=True)

    # (b) mid-stream failure does not roll back learned state.
    state_dir, state_path = _make_state_dir()
    responders = {"p": _reject_unstripped_responder("truncated-sse")}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
        _start_compat_proxy(responders, state_path)
    if proc is None:
        shutil.rmtree(state_dir, ignore_errors=True)
        fail("truncated proxy failed to start")
        return
    try:
        _send_proxy_request_stream(proxy_port, _cm_request())
        before = len(mock_servers["p"]["requests"])
        status, _ = _send(proxy_port, _cm_request())
        reqs = mock_servers["p"]["requests"][before:]
        if status == 200 and len(reqs) == 1 and _cm_count(reqs) == 0:
            pass_("mid-stream truncation did not roll back learning")
        else:
            fail("truncated stream rolled back learning: status %s, %d calls"
                 % (status, len(reqs)))
            return
    finally:
        cleanup()
        shutil.rmtree(state_dir, ignore_errors=True)

    # (c) 429/503 retry loop composes with the compatibility retry.
    state_dir, state_path = _make_state_dir()
    calls = {"n": 0}
    call_lock = threading.Lock()

    def flaky(info):
        with call_lock:
            calls["n"] += 1
            n = calls["n"]
        try:
            has_cm = "context_management" in json.loads(info["body"])
        except Exception:
            has_cm = False
        if n == 1:
            return 503, "application/json", b'{"error":"unavailable"}'
        if has_cm:
            return 400, "application/json", OBSERVED_400_BODY
        return _ok_response(info)

    responders = {"p": flaky}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
        _start_compat_proxy(responders, state_path,
                            extra_env={"PROXY_INITIAL_DELAY": "1",
                                       "PROXY_MAX_DELAY": "2"})
    if proc is None:
        shutil.rmtree(state_dir, ignore_errors=True)
        fail("flaky proxy failed to start")
        return
    try:
        status, _ = _send(proxy_port, _cm_request())
        reqs = mock_servers["p"]["requests"]
        # Calls: 503 (unstripped), 400 (503-retry, still unstripped),
        # 2xx (compat retry, stripped) — 2 with cm.
        if status == 200 and len(reqs) == 3 and _cm_count(reqs) == 2:
            pass_("503 retry -> 400 discovery -> stripped retry composed "
                  "correctly (3 upstream calls, 2 unstripped)")
        else:
            fail("retry composition wrong: status %s, %d calls (%d with cm)"
                 % (status, len(reqs), _cm_count(reqs)))
    finally:
        cleanup()
        shutil.rmtree(state_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# F. Trace privacy
# ---------------------------------------------------------------------------

def test_compat_trace_metadata_only():
    """All compatibility_* trace events are metadata-only: no field values,
    no prompt text, no raw upstream error text."""
    print("\n--- Test: Compat Trace Metadata Only ---")
    state_dir, state_path = _bootstrap_learned_state()
    try:
        responders = {"p": _reject_unstripped_responder()}
        temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
            _start_compat_proxy(responders, state_path)
        if proc is None:
            fail("restart proxy failed to start")
            return
        try:
            # Walk 31 stripped requests, then the 32nd is the rejected probe:
            # stripped/probe/rejected events all fire in one scenario.
            if not _walk_strips(proxy_port, mock_servers["p"], 31):
                return
            status, _ = _send(proxy_port, _cm_request())  # probe -> retry
            if status != 200:
                fail("probe request failed (%s)" % status)
                return
            events = _compat_trace_events(trace_file)
            if not events:
                fail("no compatibility_* trace events recorded")
                return
            blob = json.dumps(events)
            for marker in (CM_MARKER, ERROR_MARKER, UPSTREAM_ERROR_MARKER,
                           "hello"):
                if marker in blob:
                    fail("trace events leak content marker %r" % marker)
                    return
            names = {e.get("event") for e in events}
            expected = {"compatibility_field_stripped",
                        "compatibility_probe_started",
                        "compatibility_probe_rejected"}
            missing = expected - names
            if missing:
                fail("missing expected trace events: %s (observed %s)"
                     % (sorted(missing), sorted(names)))
            else:
                pass_("all expected trace events present and metadata-only "
                      "(%d events, %d types)" % (len(events), len(names)))
        finally:
            cleanup()
    finally:
        shutil.rmtree(state_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# G. reasoning_field (chat mode)
#
# The counter and the latch live in memory inside the spawned proxy, so every
# assertion here is on something observable: the status the client received,
# the bytes the mock upstream actually saw, the trace file, and the persisted
# selection read back from the (per-test isolated) state file.
# ---------------------------------------------------------------------------

def test_reasoning_switch_needs_three_consecutive_complaints():
    """The persisted selection changes only on the third consecutive matched
    complaint against it; an intervening first-attempt success resets the
    count; after a persisted switch the count restarts against the new
    selection; and a thinking-free successful turn never resets at all."""
    print("\n--- Test: Reasoning Switch Needs Three Consecutive "
          "Complaints ---")
    state_dir, state_path = _make_state_dir()
    policy = {"accept": ("reasoning_content",)}
    responders = {"p": _reasoning_upstream(policy)}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
        _start_reasoning_proxy(responders, state_path)
    if proc is None:
        shutil.rmtree(state_dir, ignore_errors=True)
        fail("Failed to set up test")
        return
    try:
        def send(model="sonnet", with_thinking=True):
            return _send(proxy_port, _reasoning_request(
                model=model, with_thinking=with_thinking))[0]

        # (a) Two consecutive complaints are not enough.
        for i in (1, 2):
            if send() != 200:
                fail("complaint %d: the walk did not serve the client" % i)
                return
            if _reasoning_entry(state_path) is not None:
                fail("switch landed after %d complaint(s); it must need %d"
                     % (i, REASONING_SWITCH_THRESHOLD))
                return
        pass_("two consecutive complaints did not switch")

        # (b) A first-attempt success resets the ladder. The upstream is
        # relaxed for exactly one request, modelling a turn it has nothing to
        # complain about.
        policy["accept"] = ("none", "reasoning_content")
        if send() != 200:
            fail("relaxed request did not succeed")
            return
        policy["accept"] = ("reasoning_content",)
        for i in (1, 2):
            if send() != 200:
                fail("post-reset complaint %d not served" % i)
                return
            if _reasoning_entry(state_path) is not None:
                fail("the reset did not take: the switch landed only %d "
                     "complaint(s) after the intervening success" % i)
                return
        pass_("an intervening first-attempt success reset the ladder")

        # (c) The third consecutive complaint persists the switch.
        if send() != 200:
            fail("third post-reset complaint not served")
            return
        entry = _reasoning_entry(state_path)
        if entry is None or entry.get("selection") != "reasoning_content":
            fail("third consecutive complaint did not persist the switch: %r"
                 % (entry,))
            return
        pass_("third consecutive complaint persisted the switch")

        # (d) After the switch the count restarts: two further complaints
        # against the new selection must not advance it again.
        policy["accept"] = ("reasoning",)
        for i in (1, 2):
            if send() != 200:
                fail("post-switch complaint %d not served" % i)
                return
        entry = _reasoning_entry(state_path)
        if entry is None or entry.get("selection") != "reasoning_content":
            fail("two post-switch complaints advanced the selection: %r"
                 % (entry,))
            return
        pass_("after the switch the count restarted at 1")

        # (e) A thinking-free successful turn does NOT reset: on a second pair,
        # complaint / thinking-free 200 / complaint / complaint must still
        # reach the switch.
        policy["accept"] = ("reasoning_content",)
        if send(model="haiku") != 200:
            fail("thinking-free pair: first complaint not served")
            return
        policy["accept"] = ("none", "reasoning_content")
        if send(model="haiku", with_thinking=False) != 200:
            fail("thinking-free turn did not succeed")
            return
        policy["accept"] = ("reasoning_content",)
        for i in (1, 2):
            if send(model="haiku") != 200:
                fail("thinking-free pair complaint %d not served" % i)
                return
        entry = _reasoning_entry(state_path, model="claude-haiku-4-5")
        if entry is None or entry.get("selection") != "reasoning_content":
            fail("a thinking-free success reset the ladder (the switch "
                 "should have landed on the third complaint): %r"
                 % (entry,))
            return
        pass_("a thinking-free successful turn did not reset the ladder")
    finally:
        cleanup()
        shutil.rmtree(state_dir, ignore_errors=True)


def test_reasoning_transient_complaint_does_not_switch():
    """A single matched complaint followed by first-attempt successes leaves
    the persisted selection unchanged — the pin for the default-never-settles
    defect."""
    print("\n--- Test: Reasoning Transient Complaint Does Not Switch ---")
    state_dir, state_path = _make_state_dir()
    policy = {"accept": ("reasoning_content",)}
    responders = {"p": _reasoning_upstream(policy)}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
        _start_reasoning_proxy(responders, state_path)
    if proc is None:
        shutil.rmtree(state_dir, ignore_errors=True)
        fail("Failed to set up test")
        return
    try:
        status, _ = _send(proxy_port, _reasoning_request())
        if status != 200:
            fail("the transient complaint was not absorbed by the walk (%s)"
                 % status)
            return
        if _reasoning_entry(state_path) is not None:
            fail("a single complaint persisted a selection")
            return
        policy["accept"] = ("none", "reasoning_content")
        for i in (1, 2):
            status, _ = _send(proxy_port, _reasoning_request())
            if status != 200:
                fail("follow-up success %d failed (%s)" % (i, status))
                return
        if _reasoning_entry(state_path) is not None:
            fail("the default settled: a lone complaint plus successes "
                 "persisted a selection")
            return
        pass_("a lone transient complaint left the persisted selection "
              "unchanged")
    finally:
        cleanup()
        shutil.rmtree(state_dir, ignore_errors=True)


def test_reasoning_success_serves_client_during_learning():
    """While the count is below the threshold a complaint is absorbed by an
    in-request retry and the client still receives a 200, although the
    persisted selection has not changed.

    The mock upstream is strict about the echoed field, so a walk that re-sent
    the resolved selection instead of the advanced candidate fails here rather
    than passing quietly."""
    print("\n--- Test: Reasoning Success Serves Client During Learning ---")
    state_dir, state_path = _make_state_dir()
    policy = {"accept": ("reasoning_content",)}
    log = []
    responders = {"p": _reasoning_upstream(policy, log=log)}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
        _start_reasoning_proxy(responders, state_path)
    if proc is None:
        shutil.rmtree(state_dir, ignore_errors=True)
        fail("Failed to set up test")
        return
    try:
        status, _ = _send(proxy_port, _reasoning_request())
        if status != 200:
            fail("client did not receive a 200 during learning (%s)" % status)
            return
        if _reasoning_entry(state_path) is not None:
            fail("the persisted selection changed below the threshold")
            return
        sent = [_sent_reasoning_field(i) for i in log]
        if sent != [None, "reasoning_content"]:
            fail("expected the walk to send no field then the advanced "
                 "candidate; upstream saw %r" % (sent,))
            return
        pass_("client served 200 during learning; the walk sent the advanced "
              "candidate, not the resolved selection")
    finally:
        cleanup()
        shutil.rmtree(state_dir, ignore_errors=True)


def test_reasoning_walk_sends_advanced_candidate():
    """A walk step from a persisted `reasoning_content` selection sends exactly
    `reasoning`; from a persisted `reasoning` selection it sends no field at
    all — the literal "none" candidate.

    The wrap step is the pin for the sentinel collision: a resolver keyed on
    the parameter's value rather than on None re-resolves there and re-sends
    the body that just failed."""
    print("\n--- Test: Reasoning Walk Sends Advanced Candidate ---")
    for seeded, accepted, expect_sent, label in (
            ("reasoning_content", "reasoning",
             ["reasoning_content", "reasoning"],
             "reasoning_content -> reasoning"),
            ("reasoning", "none",
             ["reasoning", None],
             "reasoning -> none (no field emitted)")):
        state_dir, state_path = _make_state_dir()
        _seed_reasoning_state(state_path, seeded)
        policy = {"accept": (accepted,)}
        log = []
        responders = {"p": _reasoning_upstream(policy, log=log)}
        temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
            _start_reasoning_proxy(responders, state_path)
        if proc is None:
            shutil.rmtree(state_dir, ignore_errors=True)
            fail("Failed to set up test (%s)" % label)
            return
        try:
            status, _ = _send(proxy_port, _reasoning_request())
            if status != 200:
                fail("%s: walk was not served (%s)" % (label, status))
                return
            sent = [_sent_reasoning_field(i) for i in log]
            if sent != expect_sent:
                fail("%s: expected %r, upstream saw %r — the wrap step "
                     "re-resolved instead of using the advanced candidate"
                     % (label, expect_sent, sent))
                return
            pass_("walk advanced %s" % label)
        finally:
            cleanup()
            shutil.rmtree(state_dir, ignore_errors=True)


def test_reasoning_full_walk_latches():
    """One full walk does not latch a pair; two consecutive ones do. A
    feature-active success in between clears the full-walk counter, so two
    non-consecutive walks never latch. Latching sends no field, issues no
    retry, spares the persisted selection, and does not survive a restart."""
    print("\n--- Test: Reasoning Full Walk Latches ---")
    state_dir, state_path = _make_state_dir()
    _seed_reasoning_state(state_path, "reasoning_content")
    policy = {"accept": ()}       # nothing accepted: every candidate 400s
    responders = {"p": _reasoning_upstream(policy)}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
        _start_reasoning_proxy(responders, state_path)
    if proc is None:
        shutil.rmtree(state_dir, ignore_errors=True)
        fail("Failed to set up test")
        return
    try:
        def send(model="sonnet", with_thinking=True):
            return _send(proxy_port, _reasoning_request(
                model=model, with_thinking=with_thinking))[0]

        def latched_events():
            return _compat_trace_events(trace_file, "compatibility_latched")

        # One request's full walk is one upstream condition examined three
        # times, not three independent observations.
        if send() != 400:
            fail("a fully-complaining walk should return the original 400")
            return
        calls = len(mock_servers["p"]["requests"])
        if calls != 3:
            fail("expected 3 upstream calls for a full walk (initial + 2 "
                 "walk steps), got %d" % calls)
            return
        if latched_events():
            fail("a single full walk latched the pair")
            return
        pass_("one full walk did not latch")

        if send() != 400:
            fail("second full walk should return the original 400")
            return
        if not latched_events():
            fail("two consecutive full walks did not latch")
            return
        pass_("two consecutive full walks latched the pair")

        # Latched: no field, no retry, persisted selection untouched.
        before = len(mock_servers["p"]["requests"])
        if send() != 400:
            fail("latched request should return the original 400")
            return
        if len(mock_servers["p"]["requests"]) - before != 1:
            fail("a latched pair still issued walk retries")
            return
        entry = _reasoning_entry(state_path)
        if entry is None or entry.get("selection") != "reasoning_content":
            fail("the latch rewrote the persisted selection: %r" % (entry,))
            return
        pass_("latched: no field, no retry, persisted selection untouched")

        # Consecutiveness: a success clears the full-walk counter, so two
        # non-consecutive walks must not latch.
        if send(model="haiku") != 400:
            fail("full walk on the second pair should return 400")
            return
        policy["accept"] = ("none",)
        if send(model="haiku") != 200:
            fail("the intervening success did not return 200")
            return
        policy["accept"] = ()
        before = len(latched_events())
        if send(model="haiku") != 400:
            fail("post-success full walk should return 400")
            return
        if len(latched_events()) != before:
            fail("two non-consecutive full walks latched the pair — the "
                 "success in between did not clear the counter")
            return
        if send(model="haiku") != 400:
            fail("second consecutive full walk should return 400")
            return
        if len(latched_events()) == before:
            fail("two consecutive full walks after the reset did not latch")
            return
        pass_("a feature-active success cleared the full-walk counter")
    finally:
        cleanup()

    # The latch is session-scoped: a fresh process starts from the persisted
    # state, so its first full walk does not latch.
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
        _start_reasoning_proxy(responders, state_path)
    if proc is None:
        shutil.rmtree(state_dir, ignore_errors=True)
        fail("restart proxy failed to start")
        return
    try:
        if _send(proxy_port, _reasoning_request())[0] != 400:
            fail("post-restart full walk should return 400")
            return
        calls = len(mock_servers["p"]["requests"])
        if calls != 3:
            fail("post-restart pair started latched: expected a 3-call full "
                 "walk, got %d call(s)" % calls)
            return
        pass_("the latch did not survive a restart")
    finally:
        cleanup()
        shutil.rmtree(state_dir, ignore_errors=True)


def test_reasoning_non_complaint_errors_are_not_counted():
    """A 401/403/500, an unparseable body, and an unrelated 400 naming no
    reasoning field never increment the counter, advance the selection, or
    latch. A non-complaint result inside a walk stops the walk and returns the
    ORIGINAL top-level result to the client."""
    print("\n--- Test: Reasoning Non-Complaint Errors Are Not Counted ---")
    state_dir, state_path = _make_state_dir()
    runner = {"mode": "500", "n": 0}

    def upstream(info):
        runner["n"] += 1
        mode = runner["mode"]
        if mode == "complaint":
            if (_sent_reasoning_field(info) or "none") == "reasoning_content":
                return _chat_ok_response(info)
            return 400, "application/json", REASONING_MESSAGE_400
        if mode == "complaint_then_500":
            if runner["n"] == 1:
                return 400, "application/json", REASONING_MESSAGE_400
            return 500, "application/json", b'{"error":"boom"}'
        if mode == "500":
            return 500, "application/json", b'{"error":"boom"}'
        if mode == "401":
            return 401, "application/json", b'{"error":"unauthorized"}'
        if mode == "403":
            return 403, "application/json", b'{"error":"forbidden"}'
        if mode == "unparseable":
            return 400, "application/json", b"this is not json at all"
        if mode == "unrelated_400":
            return 400, "application/json", json.dumps({
                "type": "error",
                "error": {"type": "invalid_request_error",
                          "message": "Invalid request payload"},
            }).encode()
        raise AssertionError("unknown upstream mode %r" % mode)

    def set_mode(mode):
        runner["mode"] = mode
        runner["n"] = 0

    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
        _start_reasoning_proxy({"p": upstream}, state_path)
    if proc is None:
        shutil.rmtree(state_dir, ignore_errors=True)
        fail("Failed to set up test")
        return
    try:
        def send(model="sonnet"):
            before = len(mock_servers["p"]["requests"])
            status, _ = _send(proxy_port, _reasoning_request(model=model))
            return status, len(mock_servers["p"]["requests"]) - before

        # Every non-complaint shape passes straight through: no walk.
        for mode, model, expect in (("500", "sonnet", 500),
                                    ("401", "sonnet", 401),
                                    ("403", "sonnet", 403),
                                    ("unparseable", "sonnet", 400),
                                    ("unrelated_400", "sonnet", 400)):
            set_mode(mode)
            status, calls = send()
            if status != expect:
                fail("%s: client saw %s, expected %s" % (mode, status, expect))
                return
            if calls != 1:
                fail("%s: expected 1 upstream call (no walk), got %d"
                     % (mode, calls))
                return
        pass_("401/403/500/unparseable/unrelated-400 never started a walk")

        # Two 500s must not count toward the ladder: the switch still needs
        # three complaints from here.
        set_mode("500")
        send()
        send()
        if _reasoning_entry(state_path) is not None:
            fail("a non-complaint error mutated the counter or persisted "
                 "state")
            return
        set_mode("complaint")
        for i in (1, 2):
            status, _ = send()
            if status != 200:
                fail("complaint %d not served (%s)" % (i, status))
                return
        if _reasoning_entry(state_path) is not None:
            fail("the 500s counted toward the ladder: the switch landed "
                 "after only two real complaints")
            return
        status, _ = send()
        if status != 200:
            fail("third complaint not served (%s)" % status)
            return
        if _reasoning_entry(state_path) is None:
            fail("three real complaints did not persist the switch")
            return
        pass_("non-complaint errors did not count toward the ladder")

        # A non-complaint result inside a walk stops it and returns the
        # ORIGINAL top-level result, not the walk's error.
        set_mode("complaint_then_500")
        status, calls = send(model="haiku")
        if status != 400:
            fail("a stopped walk returned %s to the client; it must return "
                 "the original 400 it provoked" % status)
            return
        if calls != 2:
            fail("expected the walk to stop after 1 retry (2 calls), got %d"
                 % calls)
            return
        if _reasoning_entry(state_path, model="claude-haiku-4-5") is not None:
            fail("a stopped walk persisted state")
            return
        if _compat_trace_events(trace_file, "compatibility_latched"):
            fail("a non-complaint error latched the pair")
            return
        pass_("a non-complaint walk step stopped the walk and returned the "
              "original result")
    finally:
        cleanup()
        shutil.rmtree(state_dir, ignore_errors=True)


def test_reasoning_matcher_shapes():
    """The reasoning complaint matcher accepts every shape that names a field
    and rejects everything else — including the echoed-request traversal — and
    a body deep enough to make json.loads raise degrades to False for both
    matchers."""
    print("\n--- Test: Reasoning Matcher Shapes ---")
    import claude_retry_proxy.compat as compat
    match = compat._reasoning_complaint_match

    def envelope(text, **extra):
        err = {"type": "invalid_request_error", "message": text}
        err.update(extra)
        return json.dumps({"type": "error", "error": err}).encode()

    accepted = [
        ("pass-back form",
         envelope("The reasoning_content in the thinking mode must be passed "
                  "back to the API.")),
        ("both-fields form",
         envelope("assistant reasoning and reasoning_content cannot both be "
                  "specified")),
        ("bare field name", envelope("reasoning_content")),
        ("sentence-final form", envelope("unknown field reasoning_content.")),
        ("vllm-style field name", envelope("unknown field reasoning.")),
        ("structured loc form", json.dumps({"type": "error", "error": {
            "type": "invalid_request_error",
            "message": "Extra inputs are not permitted",
            "code": "extra_forbidden",
            "loc": ["messages", 0, "reasoning_content"],
        }}).encode()),
    ]
    for label, body in accepted:
        if not match(400, body):
            fail("matcher rejected the %s: %r" % (label, body))
            return

    rejected = [
        ("dotted nested path as prose", 400,
         envelope("messages.0.reasoning_content")),
        ("field only inside an echoed request payload", 400, json.dumps({
            "type": "error", "error": {
                "type": "invalid_request_error",
                "message": "Invalid request payload",
                "request": {"messages": [
                    {"role": "assistant", "reasoning_content": "x"}]},
            }}).encode()),
        ("structured loc naming another feature's field", 400,
         json.dumps({"type": "error", "error": {
             "code": "extra_forbidden", "loc": ["body", "context_management"],
         }}).encode()),
    ]
    rejected += REJECTED_BODY_CORPUS
    for label, status, body in rejected:
        if match(status, body):
            fail("matcher accepted the %s (status %d): %r"
                 % (label, status, body[:120]))
            return

    deep = b"[" * 100000 + b"]" * 100000
    for name, fn in (("reasoning", match),
                     ("context_management", compat._compat_rejection_match)):
        try:
            got = fn(400, deep)
        except Exception as e:
            fail("%s matcher raised on deeply nested input: %r" % (name, e))
            return
        if got:
            fail("%s matcher matched deeply nested input" % name)
            return

    pass_("matcher shapes: %d accepted, %d rejected, deep nesting degrades "
          "to False for both matchers" % (len(accepted), len(rejected)))


def test_reasoning_delist_on_none_success():
    """A walk whose advanced candidate is the literal "none" and which
    succeeds removes the entry rather than writing selection: "none", so
    absence is what the next load resolves the default from."""
    print("\n--- Test: Reasoning Delist On None Success ---")
    state_dir, state_path = _make_state_dir()
    _seed_reasoning_state(state_path, "reasoning")
    policy = {"accept": ("none",)}
    responders = {"p": _reasoning_upstream(policy)}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
        _start_reasoning_proxy(responders, state_path)
    if proc is None:
        shutil.rmtree(state_dir, ignore_errors=True)
        fail("Failed to set up test")
        return
    try:
        for i in (1, 2):
            status, _ = _send(proxy_port, _reasoning_request())
            if status != 200:
                fail("complaint %d not served (%s)" % (i, status))
                return
            entry = _reasoning_entry(state_path)
            if entry is None or entry.get("selection") != "reasoning":
                fail("the selection changed below the threshold: %r"
                     % (entry,))
                return
        status, _ = _send(proxy_port, _reasoning_request())
        if status != 200:
            fail("third complaint not served (%s)" % status)
            return
        entry = _reasoning_entry(state_path)
        if entry is not None:
            fail("the successful 'none' candidate should have delisted the "
                 "entry, found %r" % (entry,))
            return
        events = [e.get("event") for e in _compat_trace_events(trace_file)]
        if "compatibility_delisted" not in events:
            fail("no compatibility_delisted event: %r" % (events,))
            return
        pass_("the successful 'none' candidate delisted the entry instead of "
              "writing selection: none")
    finally:
        cleanup()
        shutil.rmtree(state_dir, ignore_errors=True)


def test_reasoning_persist_via_second_candidate():
    """A switch whose successful walk candidate is the SECOND step persists
    that candidate, not the first.

    Both other persistence tests reach their switch through walk step 1; this
    pins the step-2 path — step 1 complains, step 2 returns 2xx at or above
    the threshold — where the persisted selection must be the candidate whose
    own attempt was served."""
    print("\n--- Test: Reasoning Persist Via Second Candidate ---")
    state_dir, state_path = _make_state_dir()
    policy = {"accept": ("reasoning",)}   # step 1 rejected, step 2 accepted
    log = []
    responders = {"p": _reasoning_upstream(policy, log=log)}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
        _start_reasoning_proxy(responders, state_path)
    if proc is None:
        shutil.rmtree(state_dir, ignore_errors=True)
        fail("Failed to set up test")
        return
    try:
        # Two complaints are absorbed by the walk (step 2 serves the client)
        # but must not persist: the ladder only climbs to 2.
        for i in (1, 2):
            status, _ = _send(proxy_port, _reasoning_request())
            if status != 200:
                fail("complaint %d not served by the walk (%s)" % (i, status))
                return
            entry = _reasoning_entry(state_path)
            if entry is not None:
                fail("a switch landed below the threshold (%d complaint(s)): "
                     "%r" % (i, entry))
                return
        pass_("two step-2-served complaints did not switch")

        # The third consecutive complaint reaches the threshold: the walk's
        # own 2xx persists the candidate it actually tried and served.
        before = len(log)
        status, _ = _send(proxy_port, _reasoning_request())
        if status != 200:
            fail("third complaint not served by the walk (%s)" % status)
            return
        entry = _reasoning_entry(state_path)
        if entry is None or entry.get("selection") != "reasoning":
            fail("the step-2 candidate did not persist (persisted via step 1 "
                 "instead?): %r" % (entry,))
            return
        sent = [_sent_reasoning_field(i) for i in log[before:]]
        if sent != [None, "reasoning_content", "reasoning"]:
            fail("expected the walk to climb none -> reasoning_content -> "
                 "reasoning; upstream saw %r" % (sent,))
            return
        events = [e.get("event") for e in _compat_trace_events(trace_file)]
        if "compatibility_learned" not in events:
            fail("no compatibility_learned event: %r" % (events,))
            return
        pass_("the step-2 candidate persisted, not the step-1 candidate")
    finally:
        cleanup()
        shutil.rmtree(state_dir, ignore_errors=True)


def test_reasoning_walk_success_clears_full_walks():
    """A walk candidate's own 2xx clears the full-walk counter, so a full walk
    before and one after a walk-served request never latch the pair.

    Nested walk calls run with suppress_compat=True, so their success never
    reaches the request-level reset; absent the walk-level clear, those two
    full walks would sit on two NON-consecutive requests and still latch."""
    print("\n--- Test: Reasoning Walk Success Clears Full Walks ---")
    state_dir, state_path = _make_state_dir()
    policy = {"accept": ()}       # nothing accepted: every candidate 400s
    responders = {"p": _reasoning_upstream(policy)}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
        _start_reasoning_proxy(responders, state_path)
    if proc is None:
        shutil.rmtree(state_dir, ignore_errors=True)
        fail("Failed to set up test")
        return
    try:
        def send():
            before = len(mock_servers["p"]["requests"])
            status, _ = _send(proxy_port, _reasoning_request())
            return status, len(mock_servers["p"]["requests"]) - before

        def latched():
            return _compat_trace_events(trace_file, "compatibility_latched")

        # (a) One full walk: the full-walk counter stands at 1, no latch.
        status, calls = send()
        if (status, calls) != (400, 3):
            fail("full walk (a): status %s, %d call(s) (expected 400, 3)"
                 % (status, calls))
            return
        if latched():
            fail("the first full walk latched the pair")
            return
        pass_("full walk #1 did not latch")

        # (b) A request whose walk candidate succeeds: the client is served and
        # the full-walk counter is cleared by that candidate's own 2xx.
        policy["accept"] = ("reasoning",)
        status, calls = send()
        if (status, calls) != (200, 3):
            fail("walk-served request: status %s, %d call(s) (expected 200, 3)"
                 % (status, calls))
            return
        pass_("a walk candidate's 2xx served the client")

        # (c) A full walk after the walk-served request counts from zero: the
        # two full walks are non-consecutive, so nothing latches.
        policy["accept"] = ()
        status, calls = send()
        if (status, calls) != (400, 3):
            fail("full walk (c): status %s, %d call(s) (expected 400, 3)"
                 % (status, calls))
            return
        if latched():
            fail("two NON-consecutive full walks latched the pair — the walk "
                 "candidate's success did not clear the full-walk counter")
            return
        pass_("the walk success cleared the full-walk counter")

        # (d) The next consecutive full walk latches, proving (c) was a genuine
        # reset rather than a latch that never fires.
        status, calls = send()
        if (status, calls) != (400, 3):
            fail("full walk (d): status %s, %d call(s) (expected 400, 3)"
                 % (status, calls))
            return
        if not latched():
            fail("two consecutive full walks after the walk-served request "
                 "did not latch")
            return
        pass_("the next consecutive full walk latched the pair")

        # Latched: no retry is issued for the pair.
        status, calls = send()
        if (status, calls) != (400, 1):
            fail("latched pair: status %s, %d call(s) (expected 400, 1 — no "
                 "walk)" % (status, calls))
            return
        pass_("the latched pair issued no retry")
    finally:
        cleanup()
        shutil.rmtree(state_dir, ignore_errors=True)


def test_reasoning_threshold_reads_module_binding():
    """The strike-ladder threshold is read from compat's module binding at the
    decision point, so monkeypatching compat.COMPAT_REASONING_SWITCH_THRESHOLD
    — directly, or through the clamp _compat_validate_constants applies —
    changes the persist outcome.

    A by-value copy of the constant anywhere on that path (a def-time default
    argument, or a name imported into the server module) would make the
    monkeypatch inert and fail these assertions."""
    print("\n--- Test: Reasoning Threshold Reads Module Binding ---")
    import claude_retry_proxy.server as srv
    import claude_retry_proxy.compat as compat

    state_dir, state_path = _make_state_dir()
    saved_path = srv.SETTINGS.feature_compat_file
    saved_threshold = compat.COMPAT_REASONING_SWITCH_THRESHOLD
    key = ("threshold-provider", "chat", "threshold-model", "reasoning_field")
    try:
        # No by-value copy of the constant may exist on the server side: the
        # one comparison site must read the module binding the clamp rebinds.
        if hasattr(srv, "COMPAT_REASONING_SWITCH_THRESHOLD"):
            fail("server.py holds a by-value copy of "
                 "COMPAT_REASONING_SWITCH_THRESHOLD; the threshold comparison "
                 "must read compat's (possibly clamped) module binding")
            return
        srv.SETTINGS.feature_compat_file = state_path

        # Shipped threshold (3): a ladder of 2 sits below it — no persist.
        state = compat._CompatState()
        state.reasoning_complaints[key] = ("reasoning_content", 2)
        compat._reasoning_persist_switch(key, "reasoning", "req-w1", "sonnet",
                                         state=state)
        if key in state.entries:
            fail("a ladder of 2 persisted at the shipped threshold 3: %r"
                 % (state.entries.get(key),))
            return

        # Monkeypatch the module binding to 2: the same ladder now persists.
        compat.COMPAT_REASONING_SWITCH_THRESHOLD = 2
        compat._reasoning_persist_switch(key, "reasoning", "req-w1", "sonnet",
                                         state=state)
        entry = state.entries.get(key)
        if entry is None or entry.get("selection") != "reasoning":
            fail("monkeypatching COMPAT_REASONING_SWITCH_THRESHOLD did not "
                 "change the persist outcome — the comparison site does not "
                 "read the module binding: %r" % (entry,))
            return
        if _reasoning_entry(state_path, model="threshold-model",
                            provider="threshold-provider") is None:
            fail("the switched entry was not persisted to the state file")
            return
        pass_("the module binding drives the persist outcome at the shipped "
              "threshold")

        # The clamp path: an invalid threshold is clamped to 2 by
        # _compat_validate_constants, and the outcome follows the clamped value.
        compat.COMPAT_REASONING_SWITCH_THRESHOLD = 1
        compat._compat_validate_constants()
        if compat.COMPAT_REASONING_SWITCH_THRESHOLD != 2:
            fail("_compat_validate_constants did not clamp the reasoning switch "
                 "threshold to 2: %r"
                 % (compat.COMPAT_REASONING_SWITCH_THRESHOLD,))
            return

        state2 = compat._CompatState()
        state2.reasoning_complaints[key] = ("reasoning_content", 1)
        compat._reasoning_persist_switch(key, "reasoning", "req-w1", "sonnet",
                                         state=state2)
        if key in state2.entries:
            fail("a ladder of 1 persisted at the clamped threshold 2")
            return
        state2.reasoning_complaints[key] = ("reasoning_content", 2)
        compat._reasoning_persist_switch(key, "reasoning", "req-w1", "sonnet",
                                         state=state2)
        if state2.entries.get(key, {}).get("selection") != "reasoning":
            fail("a ladder of 2 did not persist at the clamped threshold 2")
            return
        pass_("the clamped module value drives the persist outcome")
    finally:
        compat.COMPAT_REASONING_SWITCH_THRESHOLD = saved_threshold
        srv.SETTINGS.feature_compat_file = saved_path
        shutil.rmtree(state_dir, ignore_errors=True)


def test_reasoning_latched_outcome_issues_no_retry():
    """A latched pair hands the client its original top-level result and
    issues NO upstream call, even when _reasoning_outcome is entered directly
    — bypassing the dispatch-site latch check, which is exactly the
    interleaving this pins.

    A latch re-check is only meaningful after the retry lock is acquired; a
    lock owner can latch the pair and release between the dispatch-site test
    and the acquire, and the re-check is what still stops the walk."""
    print("\n--- Test: Latched Outcome Issues No Retry ---")
    import claude_retry_proxy.server as srv
    import claude_retry_proxy.compat as compat

    key = ("latched-provider", "chat", "latched-model", "reasoning_field")
    feature = compat.COMPAT_FEATURES["reasoning_field"]
    original = (400, {}, b'{"type":"error"}', None, 0.0, 0, "sonnet", "p",
                "claude-sonnet-5")
    calls = []

    def spy(*args, **kwargs):
        calls.append(args)
        # A non-complaint failure: if the latch were bypassed, the walk would
        # stop here and the recorded call is what fails the test.
        return (500, {}, b'{"error":"unreached"}', None, 0.0, 0, "sonnet",
                "p", "claude-sonnet-5")

    # The retry lock must be genuinely free first: a held lock would return
    # early for a different reason and make the test vacuous.
    if not feature.retry_lock.acquire(blocking=False):
        fail("the reasoning retry lock was already held — cannot isolate L1")
        return
    feature.retry_lock.release()

    saved_forward = srv._forward_request_impl
    compat._state.reasoning_latched[key] = True
    srv._forward_request_impl = spy
    try:
        got = srv._reasoning_outcome(
            original, key, "reasoning_content", "req-l1", "sonnet",
            "POST", "/v1/messages", {}, b'{"x": 1}', None, None, None)
        if calls:
            fail("a latched pair forwarded %d upstream call(s) — "
                 "_reasoning_outcome did not re-check the latch after "
                 "acquiring the retry lock" % len(calls))
            return
        if got is not original:
            fail("a latched pair must return the original top-level result "
                 "unchanged, got %r" % (got,))
            return
        pass_("the latched pair returned the original result with no upstream "
              "call")
    finally:
        srv._forward_request_impl = saved_forward
        compat._state.reasoning_latched.pop(key, None)
        compat._state.reasoning_complaints.pop(key, None)
        compat._state.reasoning_full_walks.pop(key, None)


ALL_TESTS = [
    # A. Persistence / state
    ("compat-state-load-missing-file", test_compat_state_load_missing_file),
    ("compat-state-load-corrupt-fails-open", test_compat_state_load_corrupt_fails_open),
    ("compat-state-load-unreadable-fails-open", test_compat_state_load_unreadable_fails_open),
    ("compat-state-roundtrip", test_compat_state_roundtrip),
    ("compat-state-one-bad-entry-keeps-valid", test_compat_state_one_bad_entry_keeps_valid),
    ("compat-state-unknown-feature-ignored", test_compat_state_unknown_feature_ignored),
    ("compat-state-higher-version-fails-open", test_compat_state_higher_version_fails_open),
    ("compat-state-invalid-entries-normalized", test_compat_state_invalid_entries_normalized),
    ("compat-state-atomic-write", test_compat_state_atomic_write),
    ("compat-state-write-metadata-only", test_compat_state_write_metadata_only),
    ("compat-state-persist-failure-retains-memory", test_compat_state_persist_failure_retains_memory),
    ("compat-state-concurrent-updates-no-loss", test_compat_state_concurrent_updates_no_loss),
    ("compat-state-key-isolation", test_compat_state_key_isolation),
    ("compat-locks-present", test_compat_locks_present),
    ("compat-state-object-shape", test_compat_state_object_shape),
    ("compat-normalize-threshold-ladder", test_compat_normalize_threshold_ladder),
    ("compat-temp-file-cleanup", test_compat_temp_file_cleanup),
    ("compat-field-stripped-trace-accuracy", test_compat_field_stripped_trace_accuracy),
    # B. Detector
    ("compat-detector-message-form", test_compat_detector_message_form),
    ("compat-detector-structured", test_compat_detector_structured),
    ("compat-detector-nested-path-rejected", test_compat_detector_nested_path_rejected),
    ("compat-detector-content-type-agnostic", test_compat_detector_content_type_agnostic),
    ("compat-detector-unrelated-400-rejected", test_compat_detector_unrelated_400_rejected),
    ("compat-detector-presence-required", test_compat_detector_presence_required),
    # C. Learn/strip flow
    ("compat-learn-on-400-stripped-2xx", test_compat_learn_on_400_stripped_2xx),
    ("compat-no-learn-when-retry-fails", test_compat_no_learn_when_retry_fails),
    ("compat-failed-confirmation-suppression", test_compat_failed_confirmation_suppression),
    ("compat-strip-immediate-after-learn", test_compat_strip_immediate_after_learn),
    ("compat-key-isolation-live", test_compat_key_isolation_live),
    ("compat-unknown-field-passthrough", test_compat_unknown_field_passthrough),
    ("compat-non-matching-400-passthrough", test_compat_non_matching_400_passthrough),
    ("compat-one-retry-cap", test_compat_one_retry_cap),
    ("compat-count-tokens-excluded", test_compat_count_tokens_excluded),
    # D. Thresholds / state machine
    ("compat-initial-threshold-probe", test_compat_initial_threshold_probe),
    ("compat-rejection-doubles-threshold", test_compat_rejection_doubles_threshold),
    ("compat-probation-cycle", test_compat_probation_cycle),
    ("compat-delist-after-two-successes", test_compat_delist_after_two_successes),
    ("compat-inconclusive-reschedules", test_compat_inconclusive_reschedules),
    ("compat-probe-counter-semantics", test_compat_probe_counter_semantics),
    # E. Concurrency / robustness
    ("compat-single-retry-global", test_compat_single_retry_global),
    ("compat-retry-lock-released-on-exception", test_compat_retry_lock_released_on_exception),
    ("compat-config-swap-during-retry", test_compat_config_swap_during_retry),
    ("compat-retry-stream-interaction", test_compat_retry_stream_interaction),
    # F. Trace privacy
    ("compat-trace-metadata-only", test_compat_trace_metadata_only),
    # G. reasoning_field (chat mode)
    ("reasoning-switch-needs-three-consecutive-complaints", test_reasoning_switch_needs_three_consecutive_complaints),
    ("reasoning-transient-complaint-does-not-switch", test_reasoning_transient_complaint_does_not_switch),
    ("reasoning-success-serves-client-during-learning", test_reasoning_success_serves_client_during_learning),
    ("reasoning-walk-sends-advanced-candidate", test_reasoning_walk_sends_advanced_candidate),
    ("reasoning-full-walk-latches", test_reasoning_full_walk_latches),
    ("reasoning-non-complaint-errors-are-not-counted", test_reasoning_non_complaint_errors_are_not_counted),
    ("reasoning-matcher-shapes", test_reasoning_matcher_shapes),
    ("reasoning-delist-on-none-success", test_reasoning_delist_on_none_success),
    ("reasoning-persist-via-second-candidate", test_reasoning_persist_via_second_candidate),
    ("reasoning-walk-success-clears-full-walks", test_reasoning_walk_success_clears_full_walks),
    ("reasoning-threshold-reads-module-binding", test_reasoning_threshold_reads_module_binding),
    ("reasoning-latched-outcome-issues-no-retry", test_reasoning_latched_outcome_issues_no_retry),
]


if __name__ == "__main__":
    run_cli(ALL_TESTS, "claude-retry-proxy tests: test_compat")
