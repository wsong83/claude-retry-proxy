"""Compatibility-learning tests for claude-retry-proxy: the _CompatState
persistence layer — fail-open loading, schema normalization, atomic writes,
concurrency, key isolation, locks, and metadata-only trace accuracy.

The live-loop clusters live in their own modules (test_compat_cm,
test_compat_policy, test_compat_retry, test_compat_reasoning) with shared
fixtures in _compat_support (plan 2026-11-26-partition-test-compat).

Part of the claude-retry-proxy suite; runnable standalone."""

import json
import os
import shutil
import tempfile
import threading

from _harness import (
    fail,
    pass_,
    run_cli,
    warn,
)

from _compat_support import (
    CM_MARKER,
    ERROR_MARKER,
    UPSTREAM_ERROR_MARKER,
    _bootstrap_learned_state,
    _cm_count,
    _cm_request,
    _compat_trace_events,
    _entries,
    _entry_values,
    _make_state_dir,
    _mutate_entry,
    _read_state_file,
    _reject_unstripped_responder,
    _send,
    _start_compat_proxy,
    _walk_strips,
    _write_state_file,
)

from test_compat_cm import ALL_TESTS as CM_TESTS

from test_compat_policy import ALL_TESTS as POLICY_TESTS

from test_compat_retry import ALL_TESTS as RETRY_TESTS

from test_compat_reasoning import ALL_TESTS as REASONING_TESTS


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
        selection = compat._reasoning_entry_selection(
            ("absent-provider", "chat", "absent-model", "reasoning_field"))
        if selection != "none":
            fail("absent reasoning entry must resolve to the 'none' default, "
                 "got %r" % (selection,))
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
] + CM_TESTS + POLICY_TESTS + RETRY_TESTS + REASONING_TESTS


if __name__ == "__main__":
    run_cli(ALL_TESTS, "claude-retry-proxy tests: test_compat")
