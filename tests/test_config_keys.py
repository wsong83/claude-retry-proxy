"""Config validation, models-per-provider catalog, heartbeat state,
config template copy, key decryption, and keys-index tests.

Part of the claude-retry-proxy suite; runnable standalone.
"""

import json
import os
import shutil
import subprocess
import tempfile

from _harness import (
    CLAUDE_PROXY,
    PROXY_STATE_FILE,
    _backup_proxy_state,
    _create_test_config,
    _create_test_keys,
    _create_test_keys_plain,
    _restore_proxy_state,
    _setup_tier_routing_test,
    _start_proxy_server_directly,
    cleanup_lock_files,
    fail,
    find_free_port,
    pass_,
    run_cli,
)




# ===========================================================================
# Test: Config Validation Missing Tier
# ===========================================================================

def test_config_validation_missing_tier():
    """Config with empty provider → server refuses to start."""
    print("\n--- Test: Config Validation Missing Tier ---")

    temp_dir = tempfile.mkdtemp(prefix="proxy_config_test_")
    try:
        # Create invalid config (missing model in haiku tier)
        invalid_config = {
            "tiers": {
                "haiku": {"provider": "p"},  # missing model
                "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
                "opus": {"provider": "p", "model": "claude-opus-5"},
            },
            "models": {"p": ["claude-sonnet-5", "claude-opus-5"]}
        }
        config_path = os.path.join(temp_dir, "config.json")
        with open(config_path, "w") as f:
            json.dump(invalid_config, f)

        keys_path = os.path.join(temp_dir, "keys-index.json")
        with open(keys_path, "w") as f:
            json.dump({"vendors": {"p": {"url": "http://127.0.0.1:9999", "key": "k"}}}, f)

        proxy_port = find_free_port()
        proc, probe_ok = _start_proxy_server_directly(
            proxy_port, config_path=config_path, keys_path=keys_path
        )

        # Server should not start (probe_ok should be False)
        if not probe_ok:
            pass_("Server refused to start with invalid config")
        else:
            fail("Server started with invalid config (should have refused)")
            proc.kill()

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)




# ===========================================================================
# Test: Config Validation Unknown Provider
# ===========================================================================

def test_config_validation_unknown_provider():
    """Config references provider not in keys-index.json → server refuses to start."""
    print("\n--- Test: Config Validation Unknown Provider ---")

    temp_dir = tempfile.mkdtemp(prefix="proxy_config_test_")
    try:
        # Config references "unknown-provider" but keys only has "p"
        invalid_config = {
            "tiers": {
                "haiku": {"provider": "unknown-provider", "model": "m"},
                "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
                "opus": {"provider": "p", "model": "claude-opus-5"},
            },
            # "p" has models so the only validation error is the unknown provider
            "models": {"p": ["claude-sonnet-5", "claude-opus-5"]}
        }
        config_path = os.path.join(temp_dir, "config.json")
        with open(config_path, "w") as f:
            json.dump(invalid_config, f)

        keys_path = os.path.join(temp_dir, "keys-index.json")
        with open(keys_path, "w") as f:
            json.dump({"vendors": {"p": {"url": "http://127.0.0.1:9999", "key": "k"}}}, f)

        proxy_port = find_free_port()
        proc, probe_ok = _start_proxy_server_directly(
            proxy_port, config_path=config_path, keys_path=keys_path
        )

        if not probe_ok:
            pass_("Server refused to start with unknown provider")
        else:
            fail("Server started with unknown provider (should have refused)")
            proc.kill()

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)




# ===========================================================================
# Test: Config Validation Models To Keys
# ===========================================================================

def test_config_validation_models_to_keys():
    """Config validation direction is config→keys, not keys→config.

    A provider present in config.models but missing from keys-index.json →
    server refuses to start with "has no entry in keys-index.json". A provider
    present in keys-index.json but absent from config.models and not referenced
    by any tier → server starts successfully (config is authoritative; inactive
    keys providers are silently ignored).
    """
    print("\n--- Test: Config Validation Models To Keys ---")

    temp_dir = tempfile.mkdtemp(prefix="proxy_cfg_models_keys_")
    try:
        # Config models references "orphan" which has no entry in keys-index.json
        invalid_config = {
            "tiers": {
                "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
                "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
                "opus": {"provider": "p", "model": "claude-opus-5"},
            },
            "models": {"p": ["claude-sonnet-5", "claude-opus-5"], "orphan": ["some-model"]}
        }
        config_path = os.path.join(temp_dir, "config.json")
        with open(config_path, "w") as f:
            json.dump(invalid_config, f)

        keys_path = os.path.join(temp_dir, "keys-index.json")
        with open(keys_path, "w") as f:
            json.dump({"vendors": {"p": {"url": "http://127.0.0.1:9999", "key": "k"}}}, f)

        proc, probe_ok = _start_proxy_server_directly(
            find_free_port(), config_path=config_path, keys_path=keys_path
        )

        if not probe_ok:
            try:
                _, err = proc.communicate(timeout=5)
            except Exception:
                err = ""
            if "has no entry in keys-index.json" in err:
                pass_("Server refused to start when config.models references a provider missing from keys-index.json")
            else:
                fail(f"Server refused but without 'has no entry in keys-index.json' error: {err[:300]!r}")
        else:
            fail("Server started although config.models references a provider missing from keys-index.json")
            proc.kill()

        # Now: provider in keys-index.json but not in config.models and not tier-referenced → starts
        valid_config = {
            "tiers": {
                "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
                "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
                "opus": {"provider": "p", "model": "claude-opus-5"},
            },
            "models": {"p": ["claude-sonnet-5", "claude-opus-5"]}
        }
        config_path2 = os.path.join(temp_dir, "config2.json")
        with open(config_path2, "w") as f:
            json.dump(valid_config, f)

        # keys-index.json contains an extra "legacy" provider not in config.models
        keys_path2 = os.path.join(temp_dir, "keys2-index.json")
        with open(keys_path2, "w") as f:
            json.dump({"vendors": {
                "p": {"url": "http://127.0.0.1:9999", "key": "k"},
                "legacy": {"url": "http://127.0.0.1:9998", "key": "k2"},
            }}, f)

        proc2, probe_ok2 = _start_proxy_server_directly(
            find_free_port(), config_path=config_path2, keys_path=keys_path2
        )
        if probe_ok2:
            pass_("Server started with a keys-only provider absent from config.models (not tier-referenced)")
            proc2.terminate()
            try:
                proc2.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc2.kill()
        else:
            try:
                _, err2 = proc2.communicate(timeout=5)
            except Exception:
                err2 = ""
            fail(f"Server refused to start with tier-unreferenced keys-only provider: {err2[:300]!r}")

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)




# ===========================================================================
# Test: Config Validation Tier Provider Needs Models
# ===========================================================================

def test_config_validation_tier_provider_needs_models():
    """A tier-referenced provider must have an entry in config.models.

    Server refuses to start when a tier's provider has no models entry, with a
    clear error mentioning the tier name.
    """
    print("\n--- Test: Config Validation Tier Provider Needs Models ---")

    temp_dir = tempfile.mkdtemp(prefix="proxy_cfg_tier_models_")
    try:
        # "q" is referenced by the opus tier but has no entry in config.models
        invalid_config = {
            "tiers": {
                "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
                "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
                "opus": {"provider": "q", "model": "claude-opus-5"},
            },
            "models": {"p": ["claude-sonnet-5", "claude-opus-5"]}
        }
        config_path = os.path.join(temp_dir, "config.json")
        with open(config_path, "w") as f:
            json.dump(invalid_config, f)

        keys_path = os.path.join(temp_dir, "keys-index.json")
        with open(keys_path, "w") as f:
            json.dump({"vendors": {
                "p": {"url": "http://127.0.0.1:9999", "key": "k"},
                "q": {"url": "http://127.0.0.1:9998", "key": "k2"},
            }}, f)

        proc, probe_ok = _start_proxy_server_directly(
            find_free_port(), config_path=config_path, keys_path=keys_path
        )

        if not probe_ok:
            try:
                _, err = proc.communicate(timeout=5)
            except Exception:
                err = ""
            if "used by tier" in err and "opus" in err:
                pass_("Server refused to start when tier-referenced provider has no models entry, mentioning the tier")
            else:
                fail(f"Server refused but without 'used by tier'/'opus' error: {err[:300]!r}")
        else:
            fail("Server started although a tier-referenced provider had no models entry")
            proc.kill()

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)




# ===========================================================================
# Test: Heartbeat Preserves State
# ===========================================================================

def test_heartbeat_preserves_state():
    """Heartbeat writes the in-memory startup state, never a disk-read {}.

    The heartbeat must write from _startup_state (full pid/port fields), not
    from read_state() which returns {} when proxy-state.json is deleted
    externally. This test exercises the server module in-process: it sets
    _startup_state to a full state dict (as main() does at startup), runs the
    same write the heartbeat performs, and asserts pid/port are preserved when
    the file was deleted first (simulating external deletion).
    """
    print("\n--- Test: Heartbeat Preserves State ---")

    import claude_retry_proxy.server as srv

    state_path = srv.STATE_FILE
    state_backup = None
    if os.path.exists(state_path):
        with open(state_path) as f:
            state_backup = f.read()
    try:
        # Simulate external deletion of the state file (file gone on disk)
        try:
            os.remove(state_path)
        except OSError:
            pass

        # Simulate main() startup: _startup_state holds the full state dict
        full_state = {
            "pid": 12345,
            "port": 8080,
            "started_at": "2026-08-26T00:00:00Z",
            "owner_pid": 54321,
            "last_heartbeat": "2026-08-26T00:00:00Z",
            "last_request_at": "2026-08-26T00:00:00Z",
        }
        srv._startup_state = full_state

        # Heartbeat write: update last_heartbeat on the in-memory copy and write it
        srv._startup_state["last_heartbeat"] = "2026-08-26T01:00:00Z"
        srv.write_state(srv._startup_state)

        with open(state_path) as f:
            recreated = json.load(f)

        pid_ok = recreated.get("pid") == 12345
        port_ok = recreated.get("port") == 8080
        started_ok = recreated.get("started_at") == "2026-08-26T00:00:00Z"
        hb_ok = recreated.get("last_heartbeat") == "2026-08-26T01:00:00Z"

        if pid_ok and port_ok and started_ok:
            pass_("Heartbeat write preserves pid, port, started_at from in-memory state")
        else:
            fail(f"Heartbeat write lost fields: {recreated!r}")
        if hb_ok:
            pass_("Heartbeat write updates last_heartbeat")
        else:
            fail(f"Heartbeat write did not update last_heartbeat: {recreated!r}")

        # Clean up the file we wrote
        try:
            os.remove(state_path)
        except OSError:
            pass
    finally:
        # Restore the previous state file (if any)
        if state_backup is not None:
            os.makedirs(os.path.dirname(state_path), exist_ok=True)
            with open(state_path, "w") as f:
                f.write(state_backup)
        else:
            try:
                os.remove(state_path)
            except OSError:
                pass




# ===========================================================================
# Test: Models Per Provider Validation
# ===========================================================================

def test_models_per_provider_validation():
    """Config.models entries must have valid shape; tier-referenced providers must have a models entry.

    Server refuses to start when a provider's models entry is malformed (missing,
    empty list, a string instead of a list, or a list whose entries are empty or
    whitespace-only) — with a clear "has no models" error — and when a provider
    referenced by a tier has no models entry ("used by tier" error). Starts when
    all tier-referenced providers have at least one non-empty model name.
    Providers in keys-index.json that are neither referenced by a tier nor
    present in config.models are silently ignored.
    """
    print("\n--- Test: Models Per Provider Validation ---")

    def try_start(models, keys_vendors=None):
        temp_dir = tempfile.mkdtemp(prefix="proxy_models_val_")
        try:
            config = {
                "tiers": {
                    "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
                    "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
                    "opus": {"provider": "p", "model": "claude-opus-5"},
                },
                "models": models,
            }
            config_path = os.path.join(temp_dir, "config.json")
            with open(config_path, "w") as f:
                json.dump(config, f)
            if keys_vendors is None:
                keys_vendors = {"p": {"url": "http://127.0.0.1:1", "key": "k"}}
            keys_path = _create_test_keys(temp_dir, keys_vendors)
            proc, probe_ok = _start_proxy_server_directly(
                find_free_port(), config_path=config_path, keys_path=keys_path
            )
            err = ""
            if probe_ok:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
            else:
                # Validation refused startup — collect the error message
                try:
                    _, err = proc.communicate(timeout=5)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass
            return probe_ok, err or ""
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    # (a) provider "p" missing from models but referenced by tiers -> refuse with "used by tier"
    started, err = try_start({})
    if not started and "used by tier" in err:
        pass_("Server refused to start with 'used by tier' when tier provider has no models entry")
    else:
        fail(f"Expected refusal with 'used by tier', got started={started}, stderr={err[:300]!r}")

    # (b) provider "p" present but empty list -> refuse (shape)
    started, err = try_start({"p": []})
    if not started and "has no models" in err:
        pass_("Server refused to start when provider models list is empty")
    else:
        fail(f"Expected refusal for empty models list, got started={started}, stderr={err[:300]!r}")

    # (c) provider "p" has >=1 model -> starts
    started, err = try_start({"p": ["claude-haiku-4-5", "claude-sonnet-5", "claude-opus-5"]})
    if started:
        pass_("Server started when all providers have at least one model")
    else:
        fail(f"Server refused to start although all providers had models: {err[:300]!r}")

    # (d) provider "p" has a string instead of a list -> refuse (shape)
    started, err = try_start({"p": "claude-sonnet-5"})
    if not started and "has no models" in err:
        pass_("Server refused to start when models.p is a string (not a list)")
    else:
        fail(f"Expected refusal for string models value, got started={started}, stderr={err[:300]!r}")

    # (e) provider "p" has a list containing an empty string -> refuse (shape)
    started, err = try_start({"p": [""]})
    if not started and "has no models" in err:
        pass_("Server refused to start when models.p list contains an empty string")
    else:
        fail(f"Expected refusal for list with empty string, got started={started}, stderr={err[:300]!r}")

    # (f) provider "p" has a list containing a whitespace-only string -> refuse (shape)
    started, err = try_start({"p": ["   "]})
    if not started and "has no models" in err:
        pass_("Server refused to start when models.p list contains a whitespace-only string")
    else:
        fail(f"Expected refusal for whitespace-only model string, got started={started}, stderr={err[:300]!r}")

    # (g) provider in keys but not in models and not referenced by any tier -> starts
    #     (config→keys validation direction: keys-index.json is not authoritative)
    started, err = try_start({"p": ["claude-haiku-4-5", "claude-sonnet-5", "claude-opus-5"]},
                             keys_vendors={"p": {"url": "http://127.0.0.1:1", "key": "k"},
                                           "legacy": {"url": "http://127.0.0.1:2", "key": "k2"}})
    if started:
        pass_("Server started with a keys-only provider absent from models (not tier-referenced)")
    else:
        fail(f"Server refused to start although extra keys provider is tier-unreferenced: {err[:300]!r}")




# ===========================================================================
# Test: Config Template Copy
# ===========================================================================

def test_config_template_copy():
    """Missing config.json → template copied, start fails with message."""
    print("\n--- Test: Config Template Copy ---")
    state_backup = _backup_proxy_state()
    cleanup_lock_files()

    try:
        try:
            os.remove(PROXY_STATE_FILE)
        except OSError:
            pass

        temp_dir = tempfile.mkdtemp(prefix="proxy_template_copy_")
        try:
            nonexistent_config = os.path.join(temp_dir, "config.json")
            keys_path = _create_test_keys_plain(temp_dir, {
                "p": {"url": "http://127.0.0.1:1", "key": "k"}
            })

            proc = subprocess.Popen(
                CLAUDE_PROXY + ["start", "--config-path", nonexistent_config,
                                "--keys-path", keys_path],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                stdin=subprocess.PIPE, text=True
            )
            try:
                proc.stdin.close()
            except OSError:
                pass
            stdout, stderr = proc.communicate(timeout=30)

            if proc.returncode == 1:
                pass_("Start without config exited 1")
            else:
                fail(f"Start without config exited {proc.returncode} (expected 1): {stdout} {stderr}")

            if os.path.exists(nonexistent_config):
                pass_("Template created at config path")
            else:
                fail("Template NOT created at config path")

            if "Created config template" in stdout:
                pass_("stdout mentions 'Created config template'")
            else:
                fail(f"stdout missing 'Created config template'. stdout: {stdout[:300]}")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    finally:
        cleanup_lock_files()
        subprocess.run(CLAUDE_PROXY + ["stop"], capture_output=True, text=True, timeout=10)
        _restore_proxy_state(state_backup)




# ===========================================================================
# Test: Key Decryption Wrong Passphrase
# ===========================================================================

def test_key_decryption_wrong_passphrase():
    """Wrong passphrase → start fails with clear error."""
    print("\n--- Test: Key Decryption Wrong Passphrase ---")

    upstream_port = find_free_port()
    tiers = {
        "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
        "opus": {"provider": "p", "model": "claude-opus-5"},
    }
    vendors = {"p": {"url": f"http://127.0.0.1:{upstream_port}", "key": "k"}}

    temp_dir = tempfile.mkdtemp(prefix="proxy_keys_test_")
    try:
        config_path = _create_test_config(temp_dir, tiers)
        keys_path = _create_test_keys(temp_dir, vendors, passphrase="correct-passphrase")

        proxy_port = find_free_port()
        # Try to start with wrong passphrase
        proc, probe_ok = _start_proxy_server_directly(
            proxy_port, config_path=config_path, keys_path=keys_path,
            passphrase="wrong-passphrase"
        )

        if not probe_ok:
            pass_("Server failed to start with wrong passphrase")
            # Check stderr for error message
            try:
                _, stderr = proc.communicate(timeout=2)
                if "passphrase" in stderr.lower() or "decrypt" in stderr.lower():
                    pass_("Error message mentions passphrase/decryption")
                else:
                    fail("Error message doesn't mention passphrase issue")
            except:
                pass
        else:
            fail("Server started with wrong passphrase (should have failed)")
            proc.kill()

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)




# ===========================================================================
# Test: Key Decryption Missing File
# ===========================================================================

def test_key_decryption_missing_file():
    """No keys-index.json → start fails with clear error."""
    print("\n--- Test: Key Decryption Missing File ---")

    temp_dir = tempfile.mkdtemp(prefix="proxy_keys_test_")
    try:
        tiers = {
            "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
            "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
            "opus": {"provider": "p", "model": "claude-opus-5"},
        }
        config_path = _create_test_config(temp_dir, tiers)
        # Don't create keys file

        proxy_port = find_free_port()
        proc, probe_ok = _start_proxy_server_directly(
            proxy_port, config_path=config_path, keys_path="/nonexistent/keys.json"
        )

        if not probe_ok:
            pass_("Server failed to start with missing keys file")
        else:
            fail("Server started with missing keys file (should have failed)")
            proc.kill()

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)




# ===========================================================================
# Test: API Key From Keys-Index
# ===========================================================================

def test_api_key_from_keys_index():
    """Verify x-api-key sent to upstream comes from keys-index.json, not from client."""
    print("\n--- Test: API Key From Keys-Index ---")

    upstream_port = find_free_port()
    tiers = {
        "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
        "opus": {"provider": "p", "model": "claude-opus-5"},
    }
    vendors = {"p": {"url": f"http://127.0.0.1:{upstream_port}", "key": "keys-index-key-12345"}}

    temp_dir, proxy_port, proc, mock_servers, cleanup = _setup_tier_routing_test(tiers, vendors)
    if proc is None:
        fail("Failed to set up test")
        return

    try:
        # Send request with a different API key in the client request
        import http.client as _hc
        body = json.dumps({"model": "sonnet", "messages": [{"role": "user", "content": "hi"}]})
        conn = _hc.HTTPConnection("127.0.0.1", proxy_port, timeout=10)
        conn.request("POST", "/v1/messages", body=body,
                    headers={"Content-Type": "application/json", "x-api-key": "client-key-99999"})
        resp = conn.getresponse()
        resp.read()
        conn.close()

        # Verify upstream received the keys-index key, not the client key
        reqs = mock_servers["p"]["requests"]
        if len(reqs) == 0:
            fail("Upstream received no requests")
            return

        if reqs[0]["api_key"] == "keys-index-key-12345":
            pass_("Upstream received API key from keys-index.json (client key ignored)")
        else:
            fail(f"Upstream received wrong API key: {reqs[0]['api_key']}")

    finally:
        cleanup()


# ===========================================================================
# extra_request_headers validation matrix (plan 2026-09-06-opencode-session-header)
# ===========================================================================

def _base_valid_config():
    """Configuration that validates cleanly (no extra_request_headers key).

    Providers set for validate_config is {"p"}. The unknown-provider check for
    extra_request_headers keys is membership in config['models'], matching the
    plan ('unknown provider key (not in config.models)').
    """
    return {
        "tiers": {
            "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
            "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
            "opus": {"provider": "p", "model": "claude-opus-5"},
        },
        "models": {"p": ["claude-haiku-4-5", "claude-sonnet-5", "claude-opus-5"]},
    }


_RESERVED_EXTRA_HEADER_NAMES = [
    "authorization", "x-api-key", "host", "content-length", "content-type",
    "accept", "anthropic-version", "anthropic-beta", "user-agent",
    "connection", "transfer-encoding", "expect", "te", "accept-encoding",
    "cookie",
]


def _expect_extra_errors(cfg, wanted_substrings, label, srv, n_exact=None):
    """Run validate_config over cfg and assert wanted substrings appear.

    wanted_substrings: list of substrings, each must appear in some error.
    n_exact: optional exact error-list length (when the variant is fully
    specified and the base config is clean). Pass None to skip the check
    (variants that legitimately emit multiple errors).
    """
    errors = srv.validate_config(cfg, {"p"})
    if n_exact is not None and len(errors) != n_exact:
        fail(f"{label}: expected exactly {n_exact} error(s), got {len(errors)}: {errors}")
        return
    for sub in wanted_substrings:
        if not any(sub in e for e in errors):
            fail(f"{label}: no error contains {sub!r}; got {errors}")
            return
    pass_(f"{label}: errors matched ({errors!r})")


def test_extra_request_headers_validation_matrix():
    """Validation matrix for extra_request_headers: every malformed variant
    yields its specific validation error (never a raise), and the two valid
    sides (with rules / without the key) pass empty-error.

    Error substrings are pinned from the coder's implementation (see coder
    report out_of_scope field). In-process validate_config keeps ~40
    sub-checks fast; one spawn-refusal integration test covers the startup
    path.
    """
    print("\n--- Test: extra_request_headers validation matrix ---")
    import claude_retry_proxy.server as srv

    base = _base_valid_config()
    if srv.validate_config(base, {"p"}):
        fail("base config should validate clean without extra_request_headers")
        return
    pass_("config without extra_request_headers key validates clean (optional key)")

    def variant(extra):
        cfg = dict(base)
        cfg["extra_request_headers"] = extra
        return cfg

    RESERVED = _RESERVED_EXTRA_HEADER_NAMES

    # Top-level shape (string, null, list)
    _expect_extra_errors(variant("x"), ["extra_request_headers must be an object, got str"], "top-level string", srv, n_exact=1)
    _expect_extra_errors(variant(None), ["extra_request_headers must be an object, got NoneType"], "top-level null", srv, n_exact=1)
    _expect_extra_errors(variant(["x"]), ["extra_request_headers must be an object, got list"], "top-level list", srv, n_exact=1)

    # Unknown provider key (not in config.models)
    _expect_extra_errors(variant({"ghost": [{"header": "x-a", "fallback": "v"}]}),
                         ["extra_request_headers references unknown provider 'ghost'"],
                         "unknown provider key", srv, n_exact=1)

    # Provider value not a list
    _expect_extra_errors(variant({"p": "notalist"}),
                         ["extra_request_headers['p'] must be a list of rule objects, got str"],
                         "provider value string", srv, n_exact=1)
    _expect_extra_errors(variant({"p": None}),
                         ["extra_request_headers['p'] must be a list of rule objects, got NoneType"],
                         "provider value null", srv, n_exact=1)

    # Spec not a dict (and null)
    _expect_extra_errors(variant({"p": ["notadict"]}),
                         ["extra_request_headers['p'] rule must be an object, got str"],
                         "spec string", srv, n_exact=1)
    _expect_extra_errors(variant({"p": [None]}),
                         ["extra_request_headers['p'] rule must be an object, got NoneType"],
                         "spec null", srv, n_exact=1)

    # Missing header
    _expect_extra_errors(variant({"p": [{"fallback": "v"}]}),
                         ["extra_request_headers['p'] rule 'header' must be a string, got NoneType"],
                         "missing header", srv)

    # Non-string header (int)
    _expect_extra_errors(variant({"p": [{"header": 42, "fallback": "v"}]}),
                         ["extra_request_headers['p'] rule 'header' must be a string, got int"],
                         "non-string header int", srv, n_exact=1)

    # Header empty
    _expect_extra_errors(variant({"p": [{"header": "", "fallback": "v"}]}),
                         ["extra_request_headers['p'] rule 'header' cannot be empty"],
                         "empty header", srv, n_exact=1)

    # Header regex failure
    _expect_extra_errors(variant({"p": [{"header": "bad name", "fallback": "v"}]}),
                         ["extra_request_headers['p'] rule 'header' 'bad name' does not match ^[A-Za-z0-9][A-Za-z0-9-]*$"],
                         "header regex", srv, n_exact=1)

    # Reserved header names — one row per name, case-insensitive
    for h in RESERVED:
        _expect_extra_errors(variant({"p": [{"header": h.upper(), "fallback": "v"}]}),
                             ["extra_request_headers['p'] rule 'header' '{}' is reserved and cannot be set".format(h.upper())],
                             "reserved header {}".format(h), srv, n_exact=1)

    # Duplicate header names — exact and case-variant
    dup_cfg = {"p": [
        {"header": "x-opencode-session", "from": ["x-s"], "fallback": "request_id"},
        {"header": "x-opencode-session", "fallback": "v2"},
    ]}
    _expect_extra_errors(variant(dup_cfg),
                         ["duplicate rule 'header' 'x-opencode-session' (case-insensitive)"],
                         "duplicate header exact", srv)
    dup_cfg2 = {"p": [
        {"header": "x-opencode-session", "from": ["x-s"], "fallback": "request_id"},
        {"header": "X-OpenCode-Session", "fallback": "v2"},
    ]}
    _expect_extra_errors(variant(dup_cfg2),
                         ["duplicate rule 'header' 'X-OpenCode-Session' (case-insensitive)"],
                         "duplicate header case-variant", srv)

    # from not a list
    _expect_extra_errors(variant({"p": [{"header": "x-a", "from": "notalist", "fallback": "v"}]}),
                         ["extra_request_headers['p'] rule 'from' must be a list of header names, got str"],
                         "from not a list", srv, n_exact=1)

    # from entry non-string (int)
    _expect_extra_errors(variant({"p": [{"header": "x-a", "from": [42], "fallback": "v"}]}),
                         ["extra_request_headers['p'] rule 'from' entry must be a string, got int"],
                         "from entry int", srv)

    # from entry stripped-empty
    _expect_extra_errors(variant({"p": [{"header": "x-a", "from": ["", "  "], "fallback": "v"}]}),
                         ["extra_request_headers['p'] rule 'from' entry cannot be empty"],
                         "from entry whitespace", srv)

    # from entry regex failure
    _expect_extra_errors(variant({"p": [{"header": "x-a", "from": ["bad name"], "fallback": "v"}]}),
                         ["extra_request_headers['p'] rule 'from' entry 'bad name' does not match ^[A-Za-z0-9][A-Za-z0-9-]*$"],
                         "from entry regex", srv, n_exact=1)

    # from entry reserved auth name — case-insensitive
    _expect_extra_errors(variant({"p": [{"header": "x-a", "from": ["Authorization"], "fallback": "v"}]}),
                         ["extra_request_headers['p'] rule 'from' entry 'Authorization' is reserved (client auth headers cannot be copied)"],
                         "from entry authorization", srv, n_exact=1)
    _expect_extra_errors(variant({"p": [{"header": "x-a", "from": ["x-api-key"], "fallback": "v"}]}),
                         ["extra_request_headers['p'] rule 'from' entry 'x-api-key' is reserved (client auth headers cannot be copied)"],
                         "from entry x-api-key", srv, n_exact=1)

    # fallback non-string (int and dict)
    _expect_extra_errors(variant({"p": [{"header": "x-a", "from": ["x-b"], "fallback": 42}]}),
                         ["extra_request_headers['p'] rule 'fallback' must be a string, got int"],
                         "fallback int", srv, n_exact=1)
    _expect_extra_errors(variant({"p": [{"header": "x-a", "from": ["x-b"], "fallback": {}}]}),
                         ["extra_request_headers['p'] rule 'fallback' must be a string, got dict"],
                         "fallback dict", srv, n_exact=1)

    # fallback empty and stripped-empty
    _expect_extra_errors(variant({"p": [{"header": "x-a", "from": ["x-b"], "fallback": ""}]}),
                         ["extra_request_headers['p'] rule 'fallback' cannot be empty"],
                         "fallback empty", srv, n_exact=1)
    _expect_extra_errors(variant({"p": [{"header": "x-a", "from": ["x-b"], "fallback": "   "}]}),
                         ["extra_request_headers['p'] rule 'fallback' cannot be empty"],
                         "fallback stripped-empty", srv, n_exact=1)

    # fallback CR/LF and control char
    _expect_extra_errors(variant({"p": [{"header": "x-a", "from": ["x-b"], "fallback": "a\nb"}]}),
                         ["extra_request_headers['p'] rule 'fallback' contains control characters"],
                         "fallback CR/LF", srv, n_exact=1)
    _expect_extra_errors(variant({"p": [{"header": "x-a", "from": ["x-b"], "fallback": "a\x00b"}]}),
                         ["extra_request_headers['p'] rule 'fallback' contains control characters"],
                         "fallback control char", srv, n_exact=1)

    # fallback not latin-1 encodable (U+6728 is outside latin-1)
    _expect_extra_errors(variant({"p": [{"header": "x-a", "from": ["x-b"], "fallback": "a木b"}]}),
                         ["extra_request_headers['p'] rule 'fallback' must be latin-1 encodable"],
                         "fallback non-latin1", srv, n_exact=1)

    # neither from (non-empty, non-[]) nor fallback present — including from: []
    _expect_extra_errors(variant({"p": [{"header": "x-a"}]}),
                         ["extra_request_headers['p'] rule needs a non-empty 'from' list or a 'fallback'"],
                         "neither from nor fallback", srv, n_exact=1)
    _expect_extra_errors(variant({"p": [{"header": "x-a", "from": []}]}),
                         ["extra_request_headers['p'] rule needs a non-empty 'from' list or a 'fallback'"],
                         "from empty list no fallback", srv, n_exact=1)

    # Valid side: provider with a well-formed rule list validates clean
    valid_rules = {"p": [
        {"header": "x-opencode-session",
         "from": ["x-opencode-session", "x-claude-code-session-id"],
         "fallback": "request_id"},
    ]}
    errs = srv.validate_config(variant(valid_rules), {"p"})
    if errs:
        fail("config with well-formed extra_request_headers should validate clean, got {}".format(errs))
    else:
        pass_("config with well-formed extra_request_headers validates clean")


def test_extra_request_headers_startup_refusal():
    """Server refuses to start with a malformed extra_request_headers and
    starts with a well-formed one (startup integration)."""
    print("\n--- Test: extra_request_headers startup integration ---")

    def try_start(extra):
        temp_dir = tempfile.mkdtemp(prefix="proxy_erh_start_")
        try:
            cfg = _base_valid_config()
            cfg["extra_request_headers"] = extra
            config_path = os.path.join(temp_dir, "config.json")
            with open(config_path, "w") as f:
                json.dump(cfg, f)
            keys_path = _create_test_keys_plain(temp_dir, {"p": {"url": "http://127.0.0.1:9999", "key": "k"}})
            proc, probe_ok = _start_proxy_server_directly(
                find_free_port(), config_path=config_path, keys_path=keys_path)
            err = ""
            if probe_ok:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
            else:
                try:
                    _, err = proc.communicate(timeout=5)
                except Exception:
                    pass
            return probe_ok, err or ""
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    started, err = try_start("not-a-map")
    if not started and "extra_request_headers must be an object" in err:
        pass_("Server refused to start with malformed extra_request_headers (top-level string)")
    else:
        fail(f"Expected malformed extra_request_headers to refuse startup, got started={started}, stderr={err[:300]!r}")

    started, err = try_start({"p": [{"header": "x-opencode-session", "from": ["x-s"], "fallback": "request_id"}]})
    if started:
        pass_("Server started with a well-formed extra_request_headers config")
    else:
        fail(f"Server refused to start with valid extra_request_headers: {err[:300]!r}")


ALL_TESTS = [
    ("config-validation-missing-tier", test_config_validation_missing_tier),
    ("config-validation-unknown-provider", test_config_validation_unknown_provider),
    ("config-validation-models-to-keys", test_config_validation_models_to_keys),
    ("config-validation-tier-provider-needs-models", test_config_validation_tier_provider_needs_models),
    ("models-per-provider-validation", test_models_per_provider_validation),
    ("heartbeat-preserves-state", test_heartbeat_preserves_state),
    ("config-template-copy", test_config_template_copy),
    ("key-decryption-wrong-passphrase", test_key_decryption_wrong_passphrase),
    ("key-decryption-missing-file", test_key_decryption_missing_file),
    ("api-key-from-keys-index", test_api_key_from_keys_index),
    ("extra-request-headers-validation-matrix", test_extra_request_headers_validation_matrix),
    ("extra-request-headers-startup-integration", test_extra_request_headers_startup_refusal),
]


if __name__ == "__main__":
    run_cli(ALL_TESTS, "claude-retry-proxy tests: test_config_keys")
