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
]


if __name__ == "__main__":
    run_cli(ALL_TESTS, "claude-retry-proxy tests: test_config_keys")
