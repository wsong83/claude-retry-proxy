#!/usr/bin/env python3
"""CLI for managing the Claude API retry proxy.

Commands:
    start    Start the proxy (load config, decrypt keys, launch proxy server)
    stop     Stop the proxy (kill process)
    status   Show proxy status (running/stopped/stale)
    reload   Reload config from disk
"""

import json
import os
import sys
import time
from datetime import datetime, timezone

from .settings import SETTINGS, resolve_trace_file
from .config import _load_config_for_validation, validate_config
from .keys import load_keys_file, vendor_key_names

HOME = os.path.expanduser("~")
PROXY_DIR = SETTINGS.proxy_dir
PROXY_STATE_FILE = SETTINGS.state_file
CONFIG_FILE = SETTINGS.config_path
KEYS_FILE = SETTINGS.keys_path

PRUNE_RETENTION_DAYS = 5


# ---------------------------------------------------------------------------
# Execution tracing
# ---------------------------------------------------------------------------

def _trace(msg):
    """Print execution trace to stderr for debugging silent failures."""
    try:
        print("[claude-retry-proxy] {}".format(msg), file=sys.stderr)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Process check (cross-platform)
# ---------------------------------------------------------------------------

def is_pid_alive(pid):
    """Check if process is alive (cross-platform).

    On Windows, tries OpenProcess + WaitForSingleObject via ctypes first
    (fast, no subprocess spawn). Falls back to tasklist with timeout if
    OpenProcess fails (permission edge case on some Windows configs).
    On POSIX, uses os.kill(pid, 0).
    """
    _trace("is_pid_alive: pid={}".format(pid))
    if pid is None:
        _trace("is_pid_alive: pid is None -> False")
        return False
    if sys.platform == "win32":
        import ctypes
        try:
            # Try SYNCHRONIZE first — available for any visible process
            SYNCHRONIZE = 0x00100000
            kernel32 = ctypes.windll.kernel32
            kernel32.OpenProcess.restype = ctypes.c_void_p
            kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_bool, ctypes.c_uint32]
            handle = kernel32.OpenProcess(SYNCHRONIZE, False, pid)
            if not handle:
                # SYNCHRONIZE failed — try PROCESS_QUERY_LIMITED_INFORMATION
                PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
                handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if handle:
                # WaitForSingleObject with zero timeout returns immediately:
                #   WAIT_OBJECT_0 (0)     = process exited
                #   WAIT_TIMEOUT  (0x102) = still running
                WAIT_TIMEOUT = 0x00000102
                ret = kernel32.WaitForSingleObject(handle, 0)
                kernel32.CloseHandle(handle)
                alive = ret == WAIT_TIMEOUT
                _trace("is_pid_alive: {} (win32)".format(alive))
                return alive
            # OpenProcess failed with both access masks — fall back to tasklist
            _trace("is_pid_alive: OpenProcess failed, falling back to tasklist")
        except Exception as e:
            _trace("is_pid_alive: ctypes error: {}, falling back to tasklist".format(e))
        # Fallback: use tasklist with timeout
        import subprocess
        try:
            result = subprocess.run(
                ["tasklist", "/FI", "PID eq {}".format(pid)],
                capture_output=True, text=True, timeout=5)
            alive = str(pid) in result.stdout
            _trace("is_pid_alive: {} (win32, tasklist)".format(alive))
            return alive
        except Exception as e:
            _trace("is_pid_alive: tasklist error: {}, assuming alive".format(e))
            return True  # conservative: assume alive so cleanup proceeds
    else:
        try:
            os.kill(pid, 0)
            _trace("is_pid_alive: True (posix)")
            return True
        except OSError:
            _trace("is_pid_alive: False (posix)")
            return False


def kill_process_windows(pid):
    """Terminate a process by PID using Windows API.

    Uses OpenProcess + TerminateProcess directly instead of taskkill /F,
    which can interfere with the calling process on some Windows versions.
    """
    _trace("kill_process_windows: pid={}".format(pid))
    import ctypes
    PROCESS_TERMINATE = 0x0001
    try:
        kernel32 = ctypes.windll.kernel32
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_bool, ctypes.c_uint32]
        handle = kernel32.OpenProcess(PROCESS_TERMINATE, False, pid)
        if handle:
            _trace("kill_process_windows: OpenProcess succeeded, terminating")
            kernel32.TerminateProcess(handle, 0)
            kernel32.CloseHandle(handle)
            _trace("kill_process_windows: terminated and closed handle")
            return True
        else:
            _trace("kill_process_windows: OpenProcess returned null handle")
    except Exception as e:
        _trace("kill_process_windows: exception: {}".format(e))
    return False


# ---------------------------------------------------------------------------
# Trace log pruning (best-effort maintenance)
# ---------------------------------------------------------------------------

_TS_FORMATS = ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.000Z")


def _parse_trace_entry(line):
    """Parse one JSONL trace line into {ts, event, status} (subset).

    Returns None if the line is not valid JSON. `ts` may be None within a
    valid entry if the timestamp field is missing or unparseable (the entry
    is kept but not age-checked). Callers MUST use `is not None` checks on
    the returned `ts` field.
    """
    try:
        obj = json.loads(line)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(obj, dict):
        return None
    ts_str = obj.get("timestamp")
    ts = None
    if isinstance(ts_str, str):
        for fmt in _TS_FORMATS:
            try:
                ts = datetime.strptime(ts_str, fmt).replace(
                    tzinfo=timezone.utc).timestamp()
                break
            except ValueError:
                continue
    return {"ts": ts, "event": obj.get("event"), "status": obj.get("status")}


def _fmt_ts(epoch):
    return time.strftime("%Y-%m-%d", time.gmtime(epoch))


def prune_trace_file(path):
    """Print a summary of the trace log and prune entries older than 5 days.

    Returns (kept_count, removed_count). Streams the file line-by-line to a
    temp file (no full read into memory), then atomically replaces. Malformed
    lines (partial crash writes, unparseable JSON) are preserved as-is — we
    can't date them, and dropping history silently is worse than keeping it;
    they count toward kept_count. If the file doesn't exist or can't be
    opened, prints a message and returns (0, 0) without error.
    """
    cutoff = time.time() - PRUNE_RETENTION_DAYS * 86400
    kept = 0
    removed = 0
    oldest_ts = None
    newest_ts = None
    failure_count = 0
    total_bytes = 0
    tmp = path + ".tmp"

    try:
        total_bytes = os.path.getsize(path)
    except OSError:
        total_bytes = 0

    try:
        f_in = open(path, "r", encoding="utf-8", errors="replace")
    except FileNotFoundError:
        print("Trace: no trace file yet ({})".format(path))
        return 0, 0
    except OSError as e:
        print("Trace: cannot read {} ({})".format(path, e), file=sys.stderr)
        return 0, 0

    try:
        f_out = open(tmp, "w", encoding="utf-8", errors="replace")
    except OSError as e:
        f_in.close()
        print("Trace: cannot write temp file {} ({})".format(tmp, e),
              file=sys.stderr)
        return 0, 0

    try:
        with f_in, f_out:
            for line in f_in:
                if not line.strip():
                    # Preserve blank lines (don't silently drop them).
                    f_out.write(line)
                    kept += 1
                    continue
                entry = _parse_trace_entry(line)
                if entry is None:
                    # Malformed JSON — keep as-is, can't age-check.
                    f_out.write(line)
                    kept += 1
                    continue
                ts = entry.get("ts")
                if ts is not None:
                    if oldest_ts is None or ts < oldest_ts:
                        oldest_ts = ts
                    if newest_ts is None or ts > newest_ts:
                        newest_ts = ts
                if (entry.get("event") == "request"
                        and entry.get("status") == "failure"):
                    failure_count += 1
                if ts is not None and ts < cutoff:
                    removed += 1
                else:
                    f_out.write(line)
                    kept += 1
        # Atomic replace (same directory → same volume → atomic on Windows too).
        os.replace(tmp, path)
    except OSError as e:
        # Best-effort temp cleanup on any failure; the original file is intact.
        try:
            os.remove(tmp)
        except OSError:
            pass
        print("Trace: prune failed for {} ({})".format(path, e),
              file=sys.stderr)
        return 0, 0

    print("Trace: {} entries ({} kept, {} pruned >{}d); {}B; range {}..{}; {} failures".format(
        kept + removed, kept, removed, PRUNE_RETENTION_DAYS,
        total_bytes,
        _fmt_ts(oldest_ts) if oldest_ts is not None else "n/a",
        _fmt_ts(newest_ts) if newest_ts is not None else "n/a",
        failure_count,
    ))
    return kept, removed


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def _read_state():
    """Read proxy-state.json. Returns dict or None."""
    try:
        with open(PROXY_STATE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _write_state(state):
    """Write proxy-state.json atomically."""
    import tempfile
    os.makedirs(PROXY_DIR, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=PROXY_DIR, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(state, f)
        os.replace(tmp, PROXY_STATE_FILE)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def _format_tier_line(tier_name, tier, indent="  "):
    """One tier display line, with the [key=NAME] suffix when one is set."""
    label = "{}{} -> {} ({})".format(
        indent, tier_name, tier.get("model"), tier.get("provider"))
    key = tier.get("key")
    if key:
        label += " [key={}]".format(key)
    return label


def cmd_start(args):
    """Start the proxy."""
    import argparse
    import socket
    import subprocess
    import threading

    from . import vimcrypt
    from .config import install_template

    parser = argparse.ArgumentParser(prog="claude-retry-proxy start")
    parser.add_argument("--port", "-p", type=int, default=SETTINGS.port,
                        help="Port to listen on (default: $PROXY_PORT or 8080)")
    parser.add_argument("--log", "-l", type=str, default=None,
                        help="Trace log file path")
    parser.add_argument("--all", "-a", action="store_true",
                        help="Log full request/response bodies")
    parser.add_argument("--config-path", type=str, default=None,
                        help="Path to config.json")
    parser.add_argument("--keys-path", type=str, default=None,
                        help="Path to keys-index.json")
    parser.add_argument("--passphrase-file", type=str, default=None,
                        help="Read passphrase from file (for non-interactive use)")
    parsed = parser.parse_args(args)
    port = parsed.port
    config_path = parsed.config_path or CONFIG_FILE
    keys_path = parsed.keys_path or KEYS_FILE

    _trace("cmd_start: entering (port={})".format(port))

    # 1. Check config.json exists
    if not os.path.exists(config_path):
        if os.path.exists(SETTINGS.config_template_path):
            try:
                install_template(config_path)
            except OSError as e:
                print("ERROR: Cannot create config at {}: {}".format(config_path, e))
                return 1
        else:
            print("ERROR: Config file not found: {}".format(config_path))
            print("Template not available at: {}".format(SETTINGS.config_template_path))
            return 1
        print("Created config template at: {}".format(config_path))
        print("Please populate the config and run 'claude-retry-proxy start' again.")
        return 1

    # 2. Load and validate config
    config, err = _load_config_for_validation(config_path)
    if err:
        print("ERROR: {}".format(err))
        return 1

    # 3. Load keys file (plain JSON or encrypted)
    try:
        with open(keys_path, "rb") as f:
            head = f.read(14)
    except FileNotFoundError:
        print("ERROR: Keys file not found: {}".format(keys_path))
        return 1

    _keys_encrypted = head.startswith(b"VimCrypt~03!")

    if _keys_encrypted:
        # Encrypted: prompt for passphrase and decrypt
        try:
            if parsed.passphrase_file:
                with open(parsed.passphrase_file, "r", encoding="utf-8") as f:
                    passphrase = f.read().rstrip("\r\n")
                if not passphrase:
                    print("ERROR: Empty passphrase in file")
                    return 1
            else:
                passphrase = vimcrypt.prompt_hidden("Passphrase: ")
        except OSError as e:
            print("ERROR: Cannot read passphrase file: {}".format(e))
            return 1
        except (ValueError, KeyboardInterrupt) as e:
            print("\nERROR: {}".format(e))
            return 1
    else:
        # Plain JSON: no passphrase needed
        passphrase = None  # signal to skip stdin piping below

    try:
        vendors = load_keys_file(keys_path, passphrase if _keys_encrypted else None)
    except (ValueError, OSError) as e:
        print("ERROR: {}".format(e))
        return 1
    _trace("cmd_start: loaded {} vendors".format(len(vendors)))

    # 5. Validate config against vendors
    tiers = config.get("tiers", {})
    provider_keys = {name: vendor_key_names(v) for name, v in vendors.items()}
    errors = validate_config(config, set(vendors.keys()), provider_keys)
    if errors:
        print("ERROR: Config validation failed:")
        for e in errors:
            print("  - {}".format(e))
        return 1

    # 6. Check if proxy already running
    state = _read_state()
    if state:
        pid = state.get("pid")
        if pid and is_pid_alive(pid):
            print("ERROR: Proxy already running (PID {})".format(pid))
            return 1
        # Stale state - clean up
        _trace("cmd_start: cleaning up stale state")
        try:
            os.remove(PROXY_STATE_FILE)
        except OSError:
            pass

    # 7. Prune trace log (best-effort)
    try:
        prune_trace_file(resolve_trace_file(parsed.log))
    except Exception as e:
        print("WARNING: trace log check failed ({}); continuing".format(e),
              file=sys.stderr)

    # 8. Build server command
    proxy_cmd = [sys.executable, "-m", "claude_retry_proxy.server",
                 "--port", str(port),
                 "--config-path", config_path,
                 "--keys-path", keys_path]
    if _keys_encrypted and parsed.passphrase_file:
        proxy_cmd.extend(["--passphrase-file", parsed.passphrase_file])
    if parsed.log:
        proxy_cmd.extend(["--log", parsed.log])
    if getattr(parsed, "all"):
        proxy_cmd.append("--all")

    # 9. Start proxy with passphrase piped via stdin
    creationflags = 0
    if sys.platform == "win32":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP

    os.makedirs(PROXY_DIR, exist_ok=True)
    stderr_fh = open(os.path.join(PROXY_DIR, "proxy-stderr.log"), "ab")
    proc = subprocess.Popen(
        proxy_cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=stderr_fh,
        creationflags=creationflags
    )
    _trace("cmd_start: proxy spawned (pid={})".format(proc.pid))

    # Pipe passphrase to server (only when keys are encrypted and no
    # --passphrase-file was passed through)
    if _keys_encrypted and not parsed.passphrase_file:
        try:
            proc.stdin.write((passphrase + "\n").encode("utf-8"))
            proc.stdin.close()
        except (BrokenPipeError, OSError) as e:
            _trace("cmd_start: stdin write failed: {}".format(e))
            # Read stderr for error message
            stderr_fh.flush()
            try:
                with open(stderr_fh.name, "rb") as f:
                    tail = f.read(2048).decode("utf-8", errors="replace")
            except OSError:
                tail = ""
            print("ERROR: Server failed to start: {}".format(tail))
            # Cleanup
            if proc.poll() is None:
                proc.terminate()
            try:
                os.remove(PROXY_STATE_FILE)
            except OSError:
                pass
            return 1
    else:
        # Plain keys or --passphrase-file: close stdin so server doesn't block
        try:
            proc.stdin.close()
        except OSError:
            pass

    def read_tail(fh, n):
        try:
            fh.flush()
            size = os.fstat(fh.fileno()).st_size
            with open(fh.name, "rb") as f:
                if size > n:
                    f.seek(-n, os.SEEK_END)
                return f.read().decode("utf-8", errors="replace")
        except OSError:
            return ""

    def cleanup(kill_proc=False):
        """Clean up after a failed start."""
        _trace("cmd_start: cleanup (kill_proc={})".format(kill_proc))
        if kill_proc and proc is not None and proc.poll() is None:
            try:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
            except OSError:
                pass
        try:
            os.remove(PROXY_STATE_FILE)
        except OSError:
            pass

    # 9.5. Wait for readiness marker from server (with timeout)
    readiness_timeout = 5.0  # seconds
    readiness_start = time.time()
    ready_event = threading.Event()

    def _read_stdout():
        try:
            for raw_line in proc.stdout:
                line_str = raw_line.decode("utf-8", errors="replace").strip()
                _trace("cmd_start: stdout: {}".format(line_str))
                if line_str == "READY":
                    ready_event.set()
                    return
        except (OSError, ValueError):
            pass

    _stdout_thread = threading.Thread(target=_read_stdout, daemon=True)
    _stdout_thread.start()

    ready_received = ready_event.wait(timeout=readiness_timeout)
    if ready_received:
        _trace("cmd_start: READY received")

    if not ready_received:
        if proc.poll() is not None:
            _trace("cmd_start: proxy exited before READY")
            cleanup(kill_proc=False)
            tail = read_tail(stderr_fh, 2048)
            print("ERROR: Proxy exited during startup")
            print(tail)
            return 1
        _trace("cmd_start: READY timeout after {:.1f}s".format(
            time.time() - readiness_start))
        cleanup(kill_proc=True)
        tail = read_tail(stderr_fh, 2048)
        print("ERROR: Proxy did not become ready within {:.0f}s".format(
            readiness_timeout))
        print(tail)
        return 1

    # 10. TCP readiness probe (2s timeout)
    deadline = time.time() + 2
    probe_ok = False
    attempt = 0
    while time.time() < deadline:
        try:
            s = socket.create_connection(("127.0.0.1", port), 0.5)
            s.close()
            probe_ok = True
            _trace("cmd_start: TCP probe OK on attempt {}".format(attempt + 1))
            break
        except OSError:
            attempt += 1
            if proc.poll() is not None:
                _trace("cmd_start: proxy exited during TCP probe")
                cleanup(kill_proc=False)
                tail = read_tail(stderr_fh, 2048)
                print("ERROR: Proxy exited during startup")
                print(tail)
                return 1
            time.sleep(0.1)

    if not probe_ok:
        _trace("cmd_start: TCP probe timeout after {} attempts".format(attempt))
        cleanup(kill_proc=True)
        tail = read_tail(stderr_fh, 2048)
        print("ERROR: Proxy did not become ready on port {} within 2s".format(port))
        print(tail)
        return 1

    # 11. Write proxy-state.json (PID, port, start_time, config_path)
    _write_state({
        "pid": proc.pid,
        "port": port,
        "start_time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "config_path": config_path
    })

    print("Proxy started on port {}".format(port))
    print("Tiers:")
    for tier_name in sorted(tiers.keys()):
        tier = tiers[tier_name]
        if isinstance(tier, dict):
            print(_format_tier_line(tier_name, tier))
    _trace("cmd_start: success, returning 0")
    return 0


def cmd_stop(args):
    """Stop the proxy."""
    _trace("cmd_stop: entering")

    state = _read_state()
    if not state:
        print("Proxy: not running (no state file)")
        return 0

    pid = state.get("pid")
    port = state.get("port")

    # 1. Signal graceful shutdown via HTTP
    shutdown_ok = False
    if port and pid and is_pid_alive(pid):
        _trace("cmd_stop: sending shutdown to pid={} port={}".format(pid, port))
        try:
            import urllib.request
            req = urllib.request.Request(
                "http://127.0.0.1:{}/admin/shutdown".format(port),
                method="POST")
            # Add Origin header for CSRF validation (reviewer-cmd-stop-csrf fix)
            req.add_header("Origin", "http://127.0.0.1:{}".format(port))
            with urllib.request.urlopen(req, timeout=2) as resp:
                resp.read()
            shutdown_ok = True
            _trace("cmd_stop: shutdown request accepted")
        except Exception as e:
            _trace("cmd_stop: shutdown request failed: {}".format(e))

    # 2. Wait for graceful exit (5s timeout)
    if shutdown_ok:
        _trace("cmd_stop: waiting for proxy to exit...")
        deadline = time.time() + 5
        try:
            while time.time() < deadline:
                if not os.path.exists(PROXY_STATE_FILE):
                    _trace("cmd_stop: proxy exited gracefully")
                    break
                time.sleep(0.3)
            else:
                _trace("cmd_stop: timeout waiting for graceful exit")
        except KeyboardInterrupt:
            _trace("cmd_stop: interrupted, proceeding to cleanup")

    # 3. Clean up state file
    try:
        os.remove(PROXY_STATE_FILE)
        _trace("cmd_stop: proxy-state.json removed")
    except OSError:
        _trace("cmd_stop: proxy-state.json not found")

    print("Proxy: stopped")

    # 4. Force kill if still running
    if pid and is_pid_alive(pid):
        _trace("cmd_stop: force-killing pid={}".format(pid))
        if sys.platform == "win32":
            kill_process_windows(pid)
            time.sleep(0.3)
            if is_pid_alive(pid):
                print("WARNING: Proxy PID {} may still be running".format(pid),
                      file=sys.stderr)
        else:
            import signal
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass

    _trace("cmd_stop: returning 0")
    return 0


def cmd_status(args):
    """Show proxy status."""
    _trace("cmd_status: entering")

    state = _read_state()
    if not state:
        _trace("cmd_status: no state file -> returning 1")
        print("Proxy: not running (no state file)")
        return 1

    pid = state.get("pid")
    port = state.get("port", 8080)
    start_time = state.get("start_time", "unknown")
    config_path = state.get("config_path")

    if pid and is_pid_alive(pid):
        _trace("cmd_status: pid={} alive -> returning 0".format(pid))
        print("Proxy: running")
        print("  PID: {}".format(pid))
        print("  Port: {}".format(port))
        print("  Started: {}".format(start_time))

        # Show tier mapping from config
        config, err = _load_config_for_validation(config_path)
        if not err and config:
            tiers = config.get("tiers", {})
            if tiers:
                print("  Tiers:")
                for tier_name in sorted(tiers.keys()):
                    tier = tiers[tier_name]
                    if isinstance(tier, dict):
                        print(_format_tier_line(tier_name, tier, "    "))
        return 0
    else:
        _trace("cmd_status: pid={} dead (stale state) -> returning 1".format(pid))
        print("Proxy: not running (stale state, PID {} dead)".format(pid))
        print("  Run 'claude-retry-proxy stop' to clean up")
        return 1


def cmd_reload(args):
    """Reload config from disk."""
    _trace("cmd_reload: entering")

    state = _read_state()
    if not state:
        print("ERROR: Proxy not running")
        return 1

    port = state.get("port")
    pid = state.get("pid")

    if not port or not pid or not is_pid_alive(pid):
        print("ERROR: Proxy not running (stale state)")
        return 1

    try:
        import urllib.request
        req = urllib.request.Request(
            "http://127.0.0.1:{}/admin/api/reload".format(port),
            method="POST",
            headers={"Origin": "http://127.0.0.1:{}".format(port)})
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = resp.read().decode("utf-8")
            data = json.loads(body)
            if data.get("status") == "ok":
                print("Config reloaded successfully")
                config = data.get("config", {})
                tiers = config.get("tiers", {})
                if tiers:
                    print("Tiers:")
                    for tier_name in sorted(tiers.keys()):
                        tier = tiers[tier_name]
                        if isinstance(tier, dict):
                            print(_format_tier_line(tier_name, tier))
                return 0
            else:
                print("ERROR: {}".format(data.get("error", "unknown error")))
                return 1
    except Exception as e:
        print("ERROR: Reload failed: {}".format(e))
        return 1


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def print_usage():
    print("Usage: claude-retry-proxy <command> [options]")
    print()
    print("Commands:")
    print("  start   Start the proxy (load config, decrypt keys, launch server)")
    print("  stop    Stop the proxy")
    print("  status  Show proxy status")
    print("  reload  Reload config from disk")


def main():
    _trace("main: argv={!r}".format(sys.argv))

    if len(sys.argv) < 2 or sys.argv[1] in ("--help", "-h"):
        print_usage()
        sys.exit(0 if len(sys.argv) < 2 else 0)

    cmd = sys.argv[1]
    args = sys.argv[2:]

    _trace("main: dispatching to cmd_{}".format(cmd))

    if cmd == "start":
        exit_code = cmd_start(args)
    elif cmd == "stop":
        exit_code = cmd_stop(args)
    elif cmd == "status":
        exit_code = cmd_status(args)
    elif cmd == "reload":
        exit_code = cmd_reload(args)
    else:
        print("Unknown command: {}".format(cmd))
        print("Usage: claude-retry-proxy <command> [options]")
        sys.exit(1)

    _trace("main: exit_code={}".format(exit_code))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()