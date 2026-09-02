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

ALLOWED_STATE_KEYS = {
    "schema_version", "provider", "mode", "actual_model", "feature",
    "state", "threshold", "strip_counter", "probation_successes",
    "failed_confirmations",
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


def test_compat_state_roundtrip():
    """A learned entry persists with plan-pinned schema fields and survives a
    proxy restart (stripping resumes immediately)."""
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
            "failed_confirmations": 0,
        }
        _write_state_file(state_path, state)

        # The foreign entry must not be loaded into state at all (plan load
        # contract: "unknown feature keys -> ignore (forward-compat)").
        import claude_retry_proxy.server as srv
        saved_path = srv.PROXY_FEATURE_COMPAT_FILE
        saved_state = srv._compat_state
        try:
            srv.PROXY_FEATURE_COMPAT_FILE = state_path
            srv._load_compat_state()
            loaded_features = [e.get("feature")
                               for e in srv._compat_state.values()]
            if "some_future_beta_field" in loaded_features:
                fail("foreign-feature entry was loaded into state")
                return
            if "context_management" not in loaded_features:
                fail("learned context_management entry not loaded")
                return
            pass_("foreign-feature entry not loaded; learned entry loaded")
        finally:
            srv.PROXY_FEATURE_COMPAT_FILE = saved_path
            srv._compat_state = saved_state

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
            extra = set(entry) - ALLOWED_STATE_KEYS
            if extra:
                fail("persisted entry has unexpected keys: %s" % sorted(extra))
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
    state_dir, state_path = _make_state_dir()
    saved_path = srv.PROXY_FEATURE_COMPAT_FILE
    saved_state = srv._compat_state
    try:
        srv.PROXY_FEATURE_COMPAT_FILE = state_path
        srv._compat_state = {
            ("p", "anthropic", "m", "context_management"): {
                "schema_version": 1, "provider": "p", "mode": "anthropic",
                "actual_model": "m", "feature": "context_management",
                "state": "unsupported", "threshold": 32,
                "strip_counter": 0, "probation_successes": 0,
                "failed_confirmations": 0,
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
        srv.PROXY_FEATURE_COMPAT_FILE = saved_path
        srv._compat_state = saved_state
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
                       include_cm=True):
    """Run one request against an upstream that always returns the given
    400. Returns (status, n_upstream_calls, n_with_cm)."""
    state_dir, state_path = _make_state_dir()

    def responder(info):
        return 400, content_type, body

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
    never trigger a compatibility retry or learning."""
    print("\n--- Test: Compat Detector Unrelated 400 Rejected ---")
    unrelated = [
        ("broad-invalid-request", {
            "type": "error",
            "error": {"type": "invalid_request_error",
                      "message": "Invalid request payload"},
        }),
        ("auth-error", {
            "type": "error",
            "error": {"type": "authentication_error",
                      "message": "invalid x-api-key"},
        }),
        ("model-not-found", {
            "type": "error",
            "error": {"type": "not_found_error",
                      "message": "model not found: claude-sonnet-5"},
        }),
        ("quota", {
            "type": "error",
            "error": {"type": "billing_error",
                      "message": "quota exceeded for this project"},
        }),
        ("context-limit", {
            "type": "error",
            "error": {"type": "invalid_request_error",
                      "message": "prompt is too long: 250000 tokens > "
                                 "200000 maximum"},
        }),
    ]
    for label, payload in unrelated:
        status, calls, with_cm = _detector_scenario(
            json.dumps(payload).encode())
        if calls != 1:
            fail("%s 400 triggered %d upstream calls (expected 1, no "
                 "compatibility retry)" % (label, calls))
            return
    pass_("all unrelated 400 forms passed through with no retry")


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
    occurs globally; losers receive the original 400."""
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

    responders = {"p": responder}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
        _start_compat_proxy(responders, state_path)
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
]


if __name__ == "__main__":
    run_cli(ALL_TESTS, "claude-retry-proxy tests: test_compat")
