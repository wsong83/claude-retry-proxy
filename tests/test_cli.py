"""CLI tests: start, stop, status, reload, stdout cleanliness, and
proxy-state cleanup.

Part of the claude-retry-proxy suite; runnable standalone.
"""

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time

from _harness import (
    CLAUDE_PROXY,
    PROXY_DIR,
    PROXY_STATE_FILE,
    _backup_proxy_state,
    _cli_start_with_plain_keys,
    _create_test_config,
    _create_test_keys,
    _create_test_keys_plain,
    _derive_models_from_tiers,
    _restore_proxy_state,
    _send_proxy_request,
    _start_mock_upstream,
    _start_proxy_server_directly,
    cleanup_lock_files,
    fail,
    find_free_port,
    info,
    pass_,
    proxy_status,
    run_cli,
    warn,
)




# ===========================================================================
# Test Case 13: Stop Cleans proxy-state.json
# ===========================================================================

def test_stop_cleans_proxy_state():
    """Start proxy, force-kill server, run stop, verify proxy-state.json deleted."""
    print("\n--- Test 13: Stop Cleans proxy-state.json ---")
    state_backup = _backup_proxy_state()
    cleanup_lock_files()

    try:
        # Ensure cmd_start doesn't refuse with "Proxy already running"
        try:
            os.remove(PROXY_STATE_FILE)
        except OSError:
            pass

        port = find_free_port()
        temp_dir = tempfile.mkdtemp(prefix="proxy_stop_state_")
        try:
            config_path = _create_test_config(temp_dir, {
                "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
                "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
                "opus": {"provider": "p", "model": "claude-opus-5"},
            })
            keys_path = _create_test_keys_plain(temp_dir, {
                "p": {"url": f"http://127.0.0.1:{find_free_port()}", "key": "k"}
            })
            trace_fd, trace_file = tempfile.mkstemp(suffix=".jsonl", dir=temp_dir)
            os.close(trace_fd)

            # Start proxy via CLI (writes proxy-state.json)
            info(f"Starting proxy on port {port}...")
            proc, stdout, stderr, rc = _cli_start_with_plain_keys(
                port, config_path, keys_path, trace_file)
            if rc != 0:
                fail(f"Start failed (exit {rc}): {stdout} {stderr}")
                return

            # Verify proxy-state.json exists (server creates it on startup)
            if not os.path.exists(PROXY_STATE_FILE):
                fail("proxy-state.json not found after start — server may not have created it")
                return
            pass_("proxy-state.json exists after proxy start")

            # Read PID from proxy-state.json
            with open(PROXY_STATE_FILE) as f:
                state = json.load(f)
            pid = state.get("pid")

            # Force-kill the server process (simulating Windows taskkill /F)
            if pid:
                info(f"Force-killing proxy process PID {pid}...")
                if sys.platform == "win32":
                    subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
                else:
                    try:
                        os.kill(pid, signal.SIGKILL)
                    except OSError:
                        pass
                time.sleep(0.5)

            # Verify proxy-state.json still exists (force kill bypasses server finally block)
            if os.path.exists(PROXY_STATE_FILE):
                pass_("proxy-state.json still exists after taskkill /F (server cleanup bypassed)")
            else:
                warn("proxy-state.json already gone — server may have cleaned up; test may be inconclusive")

            # Run stop — should clean up proxy-state.json
            info("Running claude-retry-proxy stop...")
            stop_result = subprocess.run(
                CLAUDE_PROXY + ["stop"],
                capture_output=True, text=True, timeout=10
            )
            stderr = stop_result.stderr

            # Verify proxy-state.json is deleted
            if not os.path.exists(PROXY_STATE_FILE):
                pass_("proxy-state.json deleted by claude-retry-proxy stop")
            else:
                fail("proxy-state.json still exists after stop — not cleaned up by cmd_stop")

            # Assert trace lines (dead-PID flow: force-kill, no graceful shutdown)
            if "cmd_stop: entering" in stderr:
                pass_("stderr trace shows 'cmd_stop: entering'")
            else:
                fail(f"stderr missing 'cmd_stop: entering'. stderr: {stderr[:300]}")
            if "cmd_stop: returning 0" in stderr:
                pass_("stderr trace shows 'cmd_stop: returning 0'")
            else:
                fail(f"stderr missing 'cmd_stop: returning 0'. stderr: {stderr[:300]}")
            if "proxy-state.json removed" in stderr or "proxy-state.json not found" in stderr:
                pass_("stderr trace shows proxy-state.json cleanup")
            else:
                fail(f"stderr missing proxy-state.json cleanup line. stderr: {stderr[:300]}")

            if stop_result.returncode != 0:
                fail(f"stop exited {stop_result.returncode}: {stop_result.stdout} {stderr}")
            else:
                pass_(f"stop exit code 0 ({stop_result.returncode})")

        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    finally:
        cleanup_lock_files()
        subprocess.run(
            CLAUDE_PROXY + ["stop"],
            capture_output=True, text=True, timeout=10
        )
        # Remove the stale state file so the restore reliably puts back the
        # pre-test backup (server wrote state on startup, force-kill bypassed
        # its cleanup, leaving a dead test PID).
        try:
            os.remove(PROXY_STATE_FILE)
        except OSError:
            pass
        _restore_proxy_state(state_backup)




def test_stop_trace_with_proxy():
    """Start proxy, run claude-retry-proxy stop; verify stderr shows graceful-stop sequence."""
    print("\n--- Test 20: Stop Trace with Proxy Running ---")
    state_backup = _backup_proxy_state()
    cleanup_lock_files()

    try:
        # Ensure cmd_start doesn't refuse with "Proxy already running"
        try:
            os.remove(PROXY_STATE_FILE)
        except OSError:
            pass

        port = find_free_port()
        temp_dir = tempfile.mkdtemp(prefix="proxy_stop_trace_")
        try:
            config_path = _create_test_config(temp_dir, {
                "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
                "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
                "opus": {"provider": "p", "model": "claude-opus-5"},
            })
            keys_path = _create_test_keys_plain(temp_dir, {
                "p": {"url": f"http://127.0.0.1:{find_free_port()}", "key": "k"}
            })
            trace_fd, trace_file = tempfile.mkstemp(suffix=".jsonl", dir=temp_dir)
            os.close(trace_fd)

            # Start proxy via CLI
            info(f"Starting proxy on port {port}...")
            proc, stdout, stderr_start, rc = _cli_start_with_plain_keys(
                port, config_path, keys_path, trace_file)
            if rc != 0:
                fail(f"Start failed (exit {rc}): {stdout} {stderr_start}")
                return

            # Verify proxy is running (state file has live PID)
            if not os.path.exists(PROXY_STATE_FILE):
                fail("proxy-state.json not created after start")
                return

            # Run stop, capturing stderr separately
            info("Running claude-retry-proxy stop...")
            stop_result = subprocess.run(
                CLAUDE_PROXY + ["stop"],
                capture_output=True, text=True, timeout=30
            )
            stderr = stop_result.stderr

            if stop_result.returncode != 0:
                fail(f"stop exited {stop_result.returncode}: {stop_result.stdout} {stderr}")

            # Assert: deterministic graceful-shutdown trace lines (live proxy,
            # /admin/shutdown succeeds). Do NOT assert "force-killing" or
            # "proxy-state.json removed" — in the graceful path the server's
            # finally block removes proxy-state.json first, and the PID is dead.
            if "cmd_stop: entering" in stderr:
                pass_("stderr contains 'cmd_stop: entering'")
            else:
                fail(f"stderr missing 'cmd_stop: entering'. stderr: {stderr[:300]}")

            if "cmd_stop: shutdown request accepted" in stderr:
                pass_("stderr contains 'cmd_stop: shutdown request accepted'")
            else:
                fail(f"stderr missing 'cmd_stop: shutdown request accepted'. stderr: {stderr[:300]}")

            if "cmd_stop: proxy exited gracefully" in stderr:
                pass_("stderr contains 'cmd_stop: proxy exited gracefully'")
            else:
                fail(f"stderr missing 'cmd_stop: proxy exited gracefully'. stderr: {stderr[:300]}")

            if "cmd_stop: returning 0" in stderr:
                pass_("stderr contains 'cmd_stop: returning 0'")
            else:
                fail(f"stderr missing 'cmd_stop: returning 0'. stderr: {stderr[:300]}")

            # Assert: trace format uses [claude-retry-proxy] prefix
            if "[claude-retry-proxy]" in stderr:
                pass_("stderr trace lines use [claude-retry-proxy] prefix")
            else:
                fail(f"stderr missing [claude-retry-proxy] prefix. stderr: {stderr[:300]}")

            # Assert: stdout reports stopped
            if "Proxy: stopped" in stop_result.stdout:
                pass_("stdout contains 'Proxy: stopped'")
            else:
                fail(f"stdout missing 'Proxy: stopped'. stdout: {stop_result.stdout[:300]}")

        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    finally:
        cleanup_lock_files()
        subprocess.run(
            CLAUDE_PROXY + ["stop"],
            capture_output=True, text=True, timeout=10
        )
        _restore_proxy_state(state_backup)




# ===========================================================================
# Test Case 21: Stop Cleans proxy-state.json (dead PID)
# ===========================================================================

def test_stop_cleans_proxy_state_lock():
    """Create proxy-state.json with a dead PID; run stop; verify state file deleted."""
    print("\n--- Test 21: Stop Cleans proxy-state.json (dead PID) ---")
    state_backup = _backup_proxy_state()
    cleanup_lock_files()

    try:
        # Create proxy directory if needed
        os.makedirs(PROXY_DIR, exist_ok=True)

        # Create proxy-state.json with a dead PID so cmd_stop enters the
        # kill/cleanup block and removes the state file.
        dead_pid = 99999  # Almost certainly not a real PID
        fake_state = {
            "pid": dead_pid,
            "port": 19999,
            "start_time": "2020-01-01T00:00:00Z",
            "config_path": "/nonexistent",
            "keys_path": "/nonexistent"
        }
        with open(PROXY_STATE_FILE, "w") as f:
            json.dump(fake_state, f)
        pass_("Created proxy-state.json with dead PID")

        # Run stop — dead PID = no-op kill, then state file removed
        info("Running claude-retry-proxy stop...")
        result = subprocess.run(
            CLAUDE_PROXY + ["stop"],
            capture_output=True, text=True, timeout=10
        )
        stderr = result.stderr

        # Assert: proxy-state.json is deleted
        if not os.path.exists(PROXY_STATE_FILE):
            pass_("proxy-state.json deleted by claude-retry-proxy stop")
        else:
            fail("proxy-state.json still exists after stop — not cleaned up by cmd_stop")

        # Assert: trace lines — dead-PID flow skips graceful shutdown, so the
        # server's finally block never runs and cmd_stop's own os.remove
        # succeeds ("proxy-state.json removed" is deterministic here).
        if "cmd_stop: entering" in stderr:
            pass_("stderr trace shows 'cmd_stop: entering'")
        else:
            fail(f"stderr missing 'cmd_stop: entering'. stderr: {stderr[:300]}")
        if "cmd_stop: proxy-state.json removed" in stderr:
            pass_("stderr trace shows 'cmd_stop: proxy-state.json removed'")
        else:
            fail(f"stderr missing 'cmd_stop: proxy-state.json removed'. stderr: {stderr[:300]}")
        if "cmd_stop: returning 0" in stderr:
            pass_("stderr trace shows 'cmd_stop: returning 0'")
        else:
            fail(f"stderr missing 'cmd_stop: returning 0'. stderr: {stderr[:300]}")

        # Assert: stdout reports stopped
        if "Proxy: stopped" in result.stdout:
            pass_("stdout contains 'Proxy: stopped'")
        else:
            fail(f"stdout missing 'Proxy: stopped'. stdout: {result.stdout[:300]}")

        if result.returncode != 0:
            fail(f"stop exited {result.returncode}: {result.stdout} {stderr}")
        else:
            pass_(f"stop exit code 0 ({result.returncode})")

    finally:
        cleanup_lock_files()
        subprocess.run(
            CLAUDE_PROXY + ["stop"],
            capture_output=True, text=True, timeout=10
        )
        _restore_proxy_state(state_backup)




# ===========================================================================
# Test Case 22: Start Stdout Not Contaminated by Trace
# ===========================================================================

def test_start_stdout_not_contaminated():
    """Start proxy with plain keys; assert stdout clean (no trace, no key material)."""
    print("\n--- Test 22: Start Stdout Not Contaminated ---")
    state_backup = _backup_proxy_state()
    cleanup_lock_files()

    try:
        # Ensure cmd_start doesn't refuse with "Proxy already running"
        try:
            os.remove(PROXY_STATE_FILE)
        except OSError:
            pass

        port = find_free_port()
        temp_dir = tempfile.mkdtemp(prefix="proxy_stdout_")
        try:
            config_path = _create_test_config(temp_dir, {
                "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
                "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
                "opus": {"provider": "p", "model": "claude-opus-5"},
            })
            keys_path = _create_test_keys_plain(temp_dir, {
                "p": {"url": f"http://127.0.0.1:{find_free_port()}", "key": "test-api-key"}
            })
            trace_fd, trace_file = tempfile.mkstemp(suffix=".jsonl", dir=temp_dir)
            os.close(trace_fd)

            # Start proxy via CLI with plain keys
            info(f"Starting proxy on port {port}...")
            proc, stdout, stderr, rc = _cli_start_with_plain_keys(
                port, config_path, keys_path, trace_file)

            if rc != 0:
                fail(f"Start failed (exit {rc}): {stdout} {stderr}")
                return

            # Assert: stdout contains startup messages
            if "Proxy started" in stdout:
                pass_("stdout contains 'Proxy started'")
            else:
                fail(f"stdout missing 'Proxy started'. stdout: {stdout[:300]}")

            if "Tiers:" in stdout:
                pass_("stdout contains 'Tiers:'")
            else:
                fail(f"stdout missing 'Tiers:'. stdout: {stdout[:300]}")

            # Assert: NO "Auth token:" on stdout (auth removed)
            if "Auth token:" in stdout:
                fail("stdout contains 'Auth token:' — auth should be removed")
            else:
                pass_("stdout does NOT contain 'Auth token:'")

            # Assert: NO key material on stdout
            if "test-api-key" in stdout:
                fail("stdout contains API key material — key leaked to stdout")
            else:
                pass_("stdout does NOT contain API key material")

            # Assert: NO trace lines on stdout (trace goes to stderr)
            if "[claude-retry-proxy]" in stdout:
                fail("stdout contains [claude-retry-proxy] trace lines — trace leaked to stdout")
            else:
                pass_("stdout does NOT contain [claude-retry-proxy] trace prefix")

            # Assert: trace IS on stderr (proves trace is working, just on the right stream)
            if "[claude-retry-proxy]" in stderr:
                pass_("stderr contains [claude-retry-proxy] trace lines (trace on correct stream)")
            else:
                warn("stderr missing [claude-retry-proxy] trace — tracing may not be active")

            # Clean up the running proxy
            stop_result = subprocess.run(
                CLAUDE_PROXY + ["stop"],
                capture_output=True, text=True, timeout=10
            )
            if stop_result.returncode != 0:
                fail(f"stop after start failed: {stop_result.stdout} {stop_result.stderr}")

        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    finally:
        cleanup_lock_files()
        subprocess.run(
            CLAUDE_PROXY + ["stop"],
            capture_output=True, text=True, timeout=10
        )
        _restore_proxy_state(state_backup)




# ===========================================================================
# Test: CLI Reload
# ===========================================================================

def test_cli_reload():
    """claude-retry-proxy reload sends reload request to running proxy."""
    print("\n--- Test: CLI Reload ---")
    state_backup = _backup_proxy_state()
    cleanup_lock_files()

    try:
        try:
            os.remove(PROXY_STATE_FILE)
        except OSError:
            pass

        port = find_free_port()
        p_port = find_free_port()
        temp_dir = tempfile.mkdtemp(prefix="proxy_cli_reload_")
        try:
            tiers_a = {
                "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
                "sonnet": {"provider": "p", "model": "model-a"},
                "opus": {"provider": "p", "model": "claude-opus-5"},
            }
            config_path = _create_test_config(temp_dir, tiers_a)
            keys_path = _create_test_keys_plain(temp_dir, {
                "p": {"url": f"http://127.0.0.1:{p_port}", "key": "k"}
            })
            trace_fd, trace_file = tempfile.mkstemp(suffix=".jsonl", dir=temp_dir)
            os.close(trace_fd)

            req_list = []
            mock_server = _start_mock_upstream(p_port, req_list)
            mock_started = True

            proc, stdout, stderr, rc = _cli_start_with_plain_keys(
                port, config_path, keys_path, trace_file)
            if rc != 0:
                fail(f"Start failed (exit {rc}): {stdout} {stderr}")
                return

            # Probe the port to confirm proxy is ready
            probe_ok = False
            deadline = time.time() + 5
            while time.time() < deadline:
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(1)
                    sock.connect(("127.0.0.1", port))
                    sock.close()
                    probe_ok = True
                    break
                except (socket.error, ConnectionRefusedError):
                    time.sleep(0.1)
            if not probe_ok:
                fail("Proxy did not become ready on port")
                return

            # Modify config.json on disk: sonnet → model-b
            tiers_b = dict(tiers_a)
            tiers_b["sonnet"] = {"provider": "p", "model": "model-b"}
            with open(config_path, "w") as f:
                # Reload re-validates: provider "p" needs >=1 model in config.models
                json.dump({"tiers": tiers_b, "models": _derive_models_from_tiers(tiers_b)}, f)

            # Run claude-retry-proxy reload (no --port; reads from proxy-state.json)
            result = subprocess.run(CLAUDE_PROXY + ["reload"],
                                    capture_output=True, text=True, timeout=10)
            if result.returncode != 0:
                fail(f"reload exited {result.returncode}: {result.stdout} {result.stderr}")
                return
            pass_("claude-retry-proxy reload exited 0")

            # Verify reload took effect: sonnet routes to model-b
            status, resp_body = _send_proxy_request(port, body=json.dumps({
                "model": "sonnet", "messages": [{"role": "user", "content": "hi"}]}))
            if status != 200:
                fail(f"Post-reload request returned {status}")
                return
            if req_list and b"model-b" in req_list[-1]["body"]:
                pass_("Post-reload sonnet request routed to model-b")
            else:
                fail(f"Post-reload sonnet request did not route to model-b. last: {req_list[-1] if req_list else 'none'}")

            # Clean up the proxy
            stop_result = subprocess.run(CLAUDE_PROXY + ["stop"],
                                         capture_output=True, text=True, timeout=10)
            if stop_result.returncode != 0:
                fail(f"stop failed: {stop_result.stdout} {stop_result.stderr}")

        finally:
            if 'mock_started' in dir():
                mock_server.shutdown()
            shutil.rmtree(temp_dir, ignore_errors=True)

    finally:
        cleanup_lock_files()
        subprocess.run(CLAUDE_PROXY + ["stop"], capture_output=True, text=True, timeout=10)
        _restore_proxy_state(state_backup)




# ===========================================================================
# Test: CLI Start No Config
# ===========================================================================

def test_cli_start_no_config():
    """Start without config.json → template created, exit 1, message printed."""
    print("\n--- Test: CLI Start No Config ---")
    state_backup = _backup_proxy_state()
    cleanup_lock_files()

    try:
        try:
            os.remove(PROXY_STATE_FILE)
        except OSError:
            pass

        temp_dir = tempfile.mkdtemp(prefix="proxy_cli_noconfig_")
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
# Test: CLI Start Invalid Config
# ===========================================================================

def test_cli_start_invalid_config():
    """Start with broken config → exit 1, specific error."""
    print("\n--- Test: CLI Start Invalid Config ---")
    state_backup = _backup_proxy_state()
    cleanup_lock_files()

    try:
        try:
            os.remove(PROXY_STATE_FILE)
        except OSError:
            pass

        temp_dir = tempfile.mkdtemp(prefix="proxy_cli_invalidcfg_")
        try:
            invalid_config_path = os.path.join(temp_dir, "config.json")
            with open(invalid_config_path, "w") as f:
                f.write("not valid json {{{")
            keys_path = _create_test_keys_plain(temp_dir, {
                "p": {"url": "http://127.0.0.1:1", "key": "k"}
            })

            proc = subprocess.Popen(
                CLAUDE_PROXY + ["start", "--config-path", invalid_config_path,
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
                pass_("Start with invalid config exited 1")
            else:
                fail(f"Start with invalid config exited {proc.returncode} (expected 1): {stdout} {stderr}")

            combined = stdout + stderr
            if "Invalid config" in combined or "ERROR" in combined:
                pass_("Error message mentions 'Invalid config' or 'ERROR'")
            else:
                fail(f"Error message missing 'Invalid config'/'ERROR'. stdout={stdout[:200]} stderr={stderr[:200]}")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    finally:
        cleanup_lock_files()
        subprocess.run(CLAUDE_PROXY + ["stop"], capture_output=True, text=True, timeout=10)
        _restore_proxy_state(state_backup)




# ===========================================================================
# Test: CLI Status Shows Tiers
# ===========================================================================

def test_cli_status_shows_tiers():
    """Status output includes tier → provider → model mapping."""
    print("\n--- Test: CLI Status Shows Tiers ---")
    state_backup = _backup_proxy_state()
    cleanup_lock_files()

    try:
        try:
            os.remove(PROXY_STATE_FILE)
        except OSError:
            pass

        port = find_free_port()
        p_port = find_free_port()
        temp_dir = tempfile.mkdtemp(prefix="proxy_cli_status_")
        try:
            tiers = {
                "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
                "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
                "opus": {"provider": "p", "model": "claude-opus-5"},
            }
            config_path = _create_test_config(temp_dir, tiers)
            keys_path = _create_test_keys_plain(temp_dir, {
                "p": {"url": f"http://127.0.0.1:{p_port}", "key": "k"}
            })
            trace_fd, trace_file = tempfile.mkstemp(suffix=".jsonl", dir=temp_dir)
            os.close(trace_fd)

            mock_server = _start_mock_upstream(p_port, [])

            proc, stdout, stderr, rc = _cli_start_with_plain_keys(
                port, config_path, keys_path, trace_file)
            if rc != 0:
                fail(f"Start failed (exit {rc}): {stdout} {stderr}")
                return

            # Run claude-retry-proxy status
            stdout, stderr, status_rc = proxy_status()
            if status_rc == 0:
                pass_("claude-retry-proxy status exited 0")
            else:
                fail(f"status exited {status_rc}: {stdout} {stderr}")
                return

            for tier in ("haiku", "sonnet", "opus"):
                if tier in stdout:
                    pass_(f"status shows tier '{tier}'")
                else:
                    fail(f"status missing tier '{tier}'. stdout: {stdout[:300]}")

            # Provider/model info shown (e.g. "sonnet -> claude-sonnet-5 (p)")
            for needle in ("claude-haiku-4-5", "claude-sonnet-5", "claude-opus-5", "(p)"):
                if needle in stdout:
                    pass_(f"status shows provider/model info '{needle}'")
                else:
                    fail(f"status missing '{needle}'. stdout: {stdout[:300]}")

            # Clean up the proxy
            stop_result = subprocess.run(CLAUDE_PROXY + ["stop"],
                                         capture_output=True, text=True, timeout=10)
            if stop_result.returncode != 0:
                fail(f"stop failed: {stop_result.stdout} {stop_result.stderr}")
            mock_server.shutdown()

        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    finally:
        cleanup_lock_files()
        subprocess.run(CLAUDE_PROXY + ["stop"], capture_output=True, text=True, timeout=10)
        _restore_proxy_state(state_backup)


# ===========================================================================
# Multi-key provider selection (plan 2026-09-10-multi-key-provider-selection)
# ===========================================================================

def test_start_unknown_tier_key_fails_via_server_gate():
    """claude-retry-proxy start with an unknown or non-string tier key exits
    non-zero POST-spawn — the server's validate_config is the single
    authoritative gate — and the surfaced error names the key."""
    print("\n--- Test: Start Unknown Tier Key Fails Via Server Gate ---")
    state_backup = _backup_proxy_state()
    cleanup_lock_files()

    try:
        try:
            os.remove(PROXY_STATE_FILE)
        except OSError:
            pass

        p_port = find_free_port()
        temp_dir = tempfile.mkdtemp(prefix="proxy_cli_key_")
        try:
            vendors = {"p": {"url": "http://127.0.0.1:{}".format(p_port),
                             "keys": {"SW": "p1", "CZ": "p2"}}}

            def try_start(tiers):
                config_path = _create_test_config(temp_dir, tiers, models={
                    "p": ["claude-haiku-4-5", "claude-sonnet-5", "claude-opus-5"]})
                keys_path = _create_test_keys_plain(temp_dir, vendors)
                proc = subprocess.Popen(
                    CLAUDE_PROXY + ["start", "--config-path", config_path,
                                    "--keys-path", keys_path],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    stdin=subprocess.PIPE, text=True
                )
                try:
                    proc.stdin.close()
                except OSError:
                    pass
                try:
                    stdout, stderr = proc.communicate(timeout=60)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
                    return -1, "", "timeout"
                return proc.returncode, stdout, stderr

            # Unknown key name on the sonnet tier -> the server gate rejects
            # post-spawn and the CLI surfaces the server's error
            rc, stdout, stderr = try_start({
                "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
                "sonnet": {"provider": "p", "model": "claude-sonnet-5", "key": "NOPE"},
                "opus": {"provider": "p", "model": "claude-opus-5"},
            })
            combined = stdout + stderr
            if (rc == 1 and "Proxy exited during startup" in combined
                    and "unknown key" in combined and "NOPE" in combined and "sonnet" in combined):
                pass_("start with unknown tier key fails post-spawn via the server gate (error names key/tier)")
            else:
                fail("expected post-spawn server-gate rejection naming sonnet/NOPE, got rc={} "
                     "stdout={!r} stderr={!r}".format(rc, stdout[:400], stderr[:400]))

            # Non-string truthy key (false) -> 'must be a string' from the server gate
            rc, stdout, stderr = try_start({
                "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
                "sonnet": {"provider": "p", "model": "claude-sonnet-5", "key": False},
                "opus": {"provider": "p", "model": "claude-opus-5"},
            })
            combined = stdout + stderr
            if rc == 1 and "must be a string" in combined:
                pass_("start with non-string selector 'false' fails post-spawn (must be a string)")
            else:
                fail("expected 'must be a string' via the server gate, got rc={} stdout={!r}".format(
                    rc, stdout[:400]))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
    finally:
        cleanup_lock_files()
        subprocess.run(CLAUDE_PROXY + ["stop"], capture_output=True, text=True, timeout=10)
        _restore_proxy_state(state_backup)


def test_start_status_reload_tier_lines_show_key():
    """Tier display lines in start, status, and reload all carry the
    [key=NAME] suffix when a tier has a key selector set."""
    print("\n--- Test: Start/Status/Reload Tier Lines Show Key ---")
    state_backup = _backup_proxy_state()
    cleanup_lock_files()

    try:
        try:
            os.remove(PROXY_STATE_FILE)
        except OSError:
            pass

        port = find_free_port()
        p_port = find_free_port()
        temp_dir = tempfile.mkdtemp(prefix="proxy_cli_key_col_")
        try:
            tiers = {
                "haiku": {"provider": "p", "model": "claude-haiku-4-5", "key": "SW"},
                "sonnet": {"provider": "p", "model": "claude-sonnet-5", "key": "CZ"},
                "opus": {"provider": "p", "model": "claude-opus-5", "key": "SW"},
            }
            config_path = _create_test_config(temp_dir, tiers, models={
                "p": ["claude-haiku-4-5", "claude-sonnet-5", "claude-opus-5"]})
            keys_path = _create_test_keys_plain(temp_dir, {
                "p": {"url": "http://127.0.0.1:{}".format(p_port), "keys": {"SW": "p1", "CZ": "p2"}}
            })
            trace_fd, trace_file = tempfile.mkstemp(suffix=".jsonl", dir=temp_dir)
            os.close(trace_fd)

            mock_server = _start_mock_upstream(p_port, [])

            proc, stdout, stderr, rc = _cli_start_with_plain_keys(
                port, config_path, keys_path, trace_file)
            if rc != 0:
                fail("Start failed (exit {}): {} {}".format(rc, stdout, stderr))
                return
            try:
                if "[key=CZ]" in stdout:
                    pass_("start tier lines show [key=CZ]")
                else:
                    fail("start stdout missing [key=CZ]. stdout: {!r}".format(stdout[:400]))

                out, err, status_rc = proxy_status()
                if status_rc == 0 and "[key=CZ]" in out:
                    pass_("status tier lines show [key=CZ]")
                else:
                    fail("status missing [key=CZ] (rc={}): {!r}".format(status_rc, out[:400]))

                reload_result = subprocess.run(
                    CLAUDE_PROXY + ["reload"], capture_output=True, text=True, timeout=30
                )
                if reload_result.returncode == 0 and "[key=CZ]" in reload_result.stdout:
                    pass_("reload tier lines show [key=CZ]")
                else:
                    fail("reload missing [key=CZ] (rc={}): {!r}".format(
                        reload_result.returncode, reload_result.stdout[:400]))
            finally:
                stop_result = subprocess.run(
                    CLAUDE_PROXY + ["stop"], capture_output=True, text=True, timeout=10)
                if stop_result.returncode != 0:
                    fail("stop after start failed: {} {}".format(
                        stop_result.stdout, stop_result.stderr))
                mock_server.shutdown()
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
    finally:
        cleanup_lock_files()
        subprocess.run(CLAUDE_PROXY + ["stop"], capture_output=True, text=True, timeout=10)
        _restore_proxy_state(state_backup)


# --- Sink startup fail-fast (plan 2026-09-10-guard-trace-state-sinks) ---
#
# The sinks return True/False; main() acts on the two startup writes and exits
# non-zero before printing READY. No separate preflight check exists — the real
# write is the check.

def _drain_after_exit(proc, timeout=20):
    """Wait for a server process to exit; return (stdout, stderr)."""
    try:
        return proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        return proc.communicate()


def _assert_startup_aborted(proc, blocked, label):
    """Assert a direct server invocation exited before READY, naming `blocked`."""
    stdout, stderr = _drain_after_exit(proc)
    if proc.returncode not in (0, None):
        pass_("{}: server exited non-zero ({})".format(label, proc.returncode))
    else:
        fail("{}: expected non-zero exit, got {}".format(label, proc.returncode))
    if "READY" not in (stdout or ""):
        pass_("{}: no READY marker on stdout".format(label))
    else:
        fail("{}: READY printed despite the unwritable path".format(label))
    if "is not writable" in (stderr or "") and blocked in (stderr or ""):
        pass_("{}: stderr ERROR names the unwritable path".format(label))
    else:
        fail("{}: expected an ERROR naming {!r}, got: {!r}".format(
            label, blocked, (stderr or "")[-400:]))


def test_startup_aborts_on_unwritable_trace_path():
    """An unwritable trace path aborts startup before READY.

    write_start_marker() returns False, so main() prints an ERROR naming the
    path and exits non-zero — the CLI surfaces this as "Proxy exited during
    startup" with the stderr tail.
    """
    print("\n--- Test: Startup Aborts On Unwritable Trace Path ---")

    temp_dir = tempfile.mkdtemp(prefix="proxy_start_trace_")
    port = find_free_port()
    upstream_port = find_free_port()
    tiers = {
        "haiku": {"provider": "test-provider", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "test-provider", "model": "claude-sonnet-5"},
        "opus": {"provider": "test-provider", "model": "claude-opus-5"},
    }
    vendors = {
        "test-provider": {"url": "http://127.0.0.1:{}".format(upstream_port),
                          "key": "test-api-key"}
    }
    config_path = _create_test_config(temp_dir, tiers)
    keys_path = _create_test_keys_plain(temp_dir, vendors)

    blocked = os.path.join(temp_dir, "trace-is-a-directory")
    os.mkdir(blocked)

    proc, _probe = _start_proxy_server_directly(
        port, config_path=config_path, keys_path=keys_path,
        passphrase=None, trace_file=blocked)
    try:
        _assert_startup_aborted(proc, blocked, "unwritable trace path")
    finally:
        if proc.poll() is None:
            proc.kill()
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_startup_aborts_on_unwritable_state_path():
    """An unwritable state path aborts startup before READY.

    write_state() returns False on the initial state write, so main() prints an
    ERROR naming the path and exits non-zero.
    """
    print("\n--- Test: Startup Aborts On Unwritable State Path ---")

    temp_dir = tempfile.mkdtemp(prefix="proxy_start_state_")
    port = find_free_port()
    upstream_port = find_free_port()
    tiers = {
        "haiku": {"provider": "test-provider", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "test-provider", "model": "claude-sonnet-5"},
        "opus": {"provider": "test-provider", "model": "claude-opus-5"},
    }
    vendors = {
        "test-provider": {"url": "http://127.0.0.1:{}".format(upstream_port),
                          "key": "test-api-key"}
    }
    config_path = _create_test_config(temp_dir, tiers)
    keys_path = _create_test_keys_plain(temp_dir, vendors)

    # The trace path stays writable so only the state sink is under test.
    trace_file = os.path.join(temp_dir, "trace.jsonl")
    blocked = os.path.join(temp_dir, "state-is-a-directory")
    os.mkdir(blocked)

    proc, _probe = _start_proxy_server_directly(
        port, config_path=config_path, keys_path=keys_path, passphrase=None,
        trace_file=trace_file, extra_env={"PROXY_STATE_FILE": blocked})
    try:
        _assert_startup_aborted(proc, blocked, "unwritable state path")
    finally:
        if proc.poll() is None:
            proc.kill()
        shutil.rmtree(temp_dir, ignore_errors=True)


def _sink_tiers_and_vendors(upstream_port, mode="anthropic"):
    """Standard three-tier config whose single vendor declares its mode.

    The explicit mode matters for the failing-stderr test below: a vendor
    without one makes startup emit an unguarded mode warning, which would raise
    out of a failing stderr before the fail-fast is reached.
    """
    tiers = {
        "haiku": {"provider": "test-provider", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "test-provider", "model": "claude-sonnet-5"},
        "opus": {"provider": "test-provider", "model": "claude-opus-5"},
    }
    vendors = {
        "test-provider": {"url": "http://127.0.0.1:{}".format(upstream_port),
                          "key": "test-api-key", "mode": mode}
    }
    return tiers, vendors


def test_relative_state_path_starts_and_writes():
    """A bare relative PROXY_STATE_FILE must not abort startup.

    write_state called os.makedirs(os.path.dirname(STATE_FILE)) with no
    empty-dirname guard, so a directoryless value like "proxy-state.json" made
    os.makedirs("") raise FileNotFoundError — which the fail-fast then reported
    as "state file ... is not writable", naming the wrong cause.
    """
    print("\n--- Test: Relative State Path Starts And Writes ---")

    temp_dir = tempfile.mkdtemp(prefix="proxy_rel_state_")
    port = find_free_port()
    tiers, vendors = _sink_tiers_and_vendors(find_free_port())
    config_path = _create_test_config(temp_dir, tiers)
    keys_path = _create_test_keys_plain(temp_dir, vendors)
    trace_file = os.path.join(temp_dir, "trace.jsonl")

    proc, probe_ok = _start_proxy_server_directly(
        port, config_path=config_path, keys_path=keys_path, passphrase=None,
        trace_file=trace_file, cwd=temp_dir,
        extra_env={"PROXY_STATE_FILE": "proxy-state.json"})
    try:
        if probe_ok:
            pass_("server started with a bare relative PROXY_STATE_FILE")
        else:
            fail("server aborted with a relative PROXY_STATE_FILE "
                 "(os.makedirs('') guarded?)")

        written = os.path.join(temp_dir, "proxy-state.json")
        if os.path.exists(written):
            pass_("state file written relative to the server's cwd")
            with open(written) as f:
                state = json.load(f)
            if state.get("pid") and state.get("port") == port:
                pass_("state file carries this process's pid and port")
            else:
                fail("unexpected state contents: {!r}".format(state))
        else:
            fail("state file not written at {!r}".format(written))
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_startup_abort_exits_one_with_failing_stderr():
    """An unwritable trace path still aborts with exit 1 when stderr is broken.

    The two fail-fast ERROR prints are wrapped so sys.exit(1) is reached
    deterministically instead of the abort depending on an unhandled traceback.
    The raising sys.stderr is installed inside the child driver: a subprocess's
    real stderr cannot be made to fail portably (a broken pipe aborts the child
    at the CRT level rather than raising a catchable OSError).

    Encrypted keys and an explicit vendor mode keep every other startup print
    out of the way, so the only print that can fail here is the guarded
    fail-fast ERROR line.
    """
    print("\n--- Test: Startup Abort Exits 1 With Failing stderr ---")

    temp_dir = tempfile.mkdtemp(prefix="proxy_abort_stderr_")
    port = find_free_port()
    tiers, vendors = _sink_tiers_and_vendors(find_free_port())
    config_path = _create_test_config(temp_dir, tiers)
    keys_path = _create_test_keys(temp_dir, vendors, "test-passphrase")
    state_file = os.path.join(temp_dir, "state.json")
    blocked_trace = os.path.join(temp_dir, "trace-is-a-directory")
    os.mkdir(blocked_trace)

    driver = (
        "import sys\n"
        "class _Raising(object):\n"
        "    encoding = 'utf-8'\n"
        "    def write(self, d):\n"
        "        raise OSError(28, 'No space left on device')\n"
        "    def flush(self): pass\n"
        "    def isatty(self): return False\n"
        "sys.stderr = _Raising()\n"
        "import claude_retry_proxy.server as s\n"
        "sys.argv = ['server', '--port', {port}, '--config-path', {cfg}, "
        "'--keys-path', {keys}, '-l', {trace}]\n"
        "s.main()\n"
    ).format(port=repr(str(port)), cfg=repr(config_path),
             keys=repr(keys_path), trace=repr(blocked_trace))

    env = os.environ.copy()
    env["PROXY_STATE_FILE"] = state_file
    proc = subprocess.Popen(
        [sys.executable, "-c", driver],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env=env, text=True)
    try:
        try:
            stdout, stderr = proc.communicate(
                input="test-passphrase\n", timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, stderr = proc.communicate()

        if proc.returncode == 1:
            pass_("server exited 1 with a failing stderr")
        else:
            fail("expected exit code 1, got {}".format(proc.returncode))

        if "READY" not in (stdout or ""):
            pass_("no READY marker on stdout")
        else:
            fail("READY printed despite the unwritable trace path")

        # Guarded, the abort reaches sys.exit(1) and CPython's excepthook never
        # runs. Unguarded, the print's OSError propagates, the excepthook then
        # fails against the same raising stderr, and CPython dumps the object
        # repr plus "lost sys.stderr" to the real fd 2. Note it emits NO
        # "Traceback" line, so a traceback check alone passes either way.
        dump_markers = [m for m in ("lost sys.stderr", "object repr")
                        if m in (stderr or "")]
        if not dump_markers:
            pass_("no CPython excepthook failure dump on the real stderr")
        else:
            fail("fail-fast print raised unguarded — CPython dumped {!r} to "
                 "fd 2: {!r}".format(dump_markers, (stderr or "")[-300:]))
    finally:
        if proc.poll() is None:
            proc.kill()
        shutil.rmtree(temp_dir, ignore_errors=True)


ALL_TESTS = [
    ("cli-reload", test_cli_reload),
    ("cli-start-no-config", test_cli_start_no_config),
    ("cli-start-invalid-config", test_cli_start_invalid_config),
    ("cli-status-shows-tiers", test_cli_status_shows_tiers),
    ("start-unknown-tier-key-fails-via-server-gate", test_start_unknown_tier_key_fails_via_server_gate),
    ("start-status-reload-tier-lines-show-key", test_start_status_reload_tier_lines_show_key),
    ("cli-stop-cleans-proxy-state-lock", test_stop_cleans_proxy_state_lock),
    ("cli-stop-cleans-proxy-state", test_stop_cleans_proxy_state),
    ("cli-stop-trace-with-proxy", test_stop_trace_with_proxy),
    ("cli-start-stdout-not-contaminated", test_start_stdout_not_contaminated),
    ("startup-aborts-on-unwritable-trace-path", test_startup_aborts_on_unwritable_trace_path),
    ("startup-aborts-on-unwritable-state-path", test_startup_aborts_on_unwritable_state_path),
    ("relative-state-path-starts-and-writes", test_relative_state_path_starts_and_writes),
    ("startup-abort-exits-one-with-failing-stderr", test_startup_abort_exits_one_with_failing_stderr),
]


if __name__ == "__main__":
    run_cli(ALL_TESTS, "claude-retry-proxy tests: test_cli")
