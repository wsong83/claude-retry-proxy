#!/usr/bin/env python3
"""CLI for managing the Claude API retry proxy.

Commands:
    start    Start the proxy (URL swap, then launch proxy server)
    stop     Stop the proxy (kill process, restore original URL)
    status   Show proxy status (running/stopped/stale)
"""

import json
import os
import sys
import time


HOME = os.path.expanduser("~")
PROXY_DIR = os.path.join(HOME, ".claude", "proxy")
PROXY_STATE_FILE = os.path.join(PROXY_DIR, "proxy-state.json")
URL_LOCK_FILE = os.path.join(PROXY_DIR, "base-url.lock")
URL_SWAP_LOCK_FILE = os.path.join(PROXY_DIR, "url-swap.lock")
SETTINGS_FILE = os.path.join(HOME, ".claude", "settings.json")


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
# URL swap locking (cross-platform O_EXCL)
# ---------------------------------------------------------------------------

def acquire_swap_lock(timeout=10):
    """Acquire URL swap lock with timeout using O_EXCL."""
    _trace("acquire_swap_lock: entering (timeout={})".format(timeout))
    os.makedirs(PROXY_DIR, exist_ok=True)
    deadline = time.time() + timeout
    attempt = 0
    while time.time() < deadline:
        try:
            fd = os.open(URL_SWAP_LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            _trace("acquire_swap_lock: success on attempt {}".format(attempt + 1))
            return True
        except OSError:
            # Stale lock detection: if the lock file is older than 30s,
            # the previous holder crashed. Remove it and retry.
            try:
                mtime = os.path.getmtime(URL_SWAP_LOCK_FILE)
                if time.time() - mtime > 30:
                    _trace("acquire_swap_lock: stale lock detected, removing")
                    try:
                        os.remove(URL_SWAP_LOCK_FILE)
                    except OSError:
                        pass
                    continue
            except OSError:
                pass
            attempt += 1
            _trace("acquire_swap_lock: attempt {} failed (OSError), retrying".format(attempt))
            time.sleep(0.1)
    _trace("acquire_swap_lock: timeout after {} attempts".format(attempt))
    return False


def release_swap_lock():
    """Release URL swap lock with retry on transient failures.

    On Windows, os.remove can fail transiently (indexer, virus scanner).
    Retries up to 5 times with exponential backoff. Silently returns if the
    lock file is already gone (ENOENT). On final failure after all retries,
    prints a warning to stderr.
    """
    import errno
    try:
        _trace("release_swap_lock: entering")
    except Exception:
        pass
    for attempt in range(5):
        try:
            os.remove(URL_SWAP_LOCK_FILE)
            _trace("release_swap_lock: removed on attempt {}".format(attempt + 1))
            return
        except OSError as e:
            if getattr(e, 'errno', None) == errno.ENOENT:
                _trace("release_swap_lock: already removed")
                return
            if attempt < 4:
                _trace("release_swap_lock: attempt {} failed, retrying".format(attempt + 1))
                time.sleep(0.1 * (2 ** attempt))
    # Final failure after all retries exhausted
    _trace("release_swap_lock: FAILED after 5 attempts")
    print("WARNING: Failed to remove URL swap lock after 5 attempts: {}".format(
        URL_SWAP_LOCK_FILE), file=sys.stderr)


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
# URL lock file I/O
# ---------------------------------------------------------------------------

def read_url_lock():
    """Read base-url.lock. Returns dict or None."""
    _trace("read_url_lock: entering")
    try:
        with open(URL_LOCK_FILE) as f:
            data = json.load(f)
            _trace("read_url_lock: found, pid={}".format(data.get("pid")))
            return data
    except (FileNotFoundError, json.JSONDecodeError):
        _trace("read_url_lock: not found")
        return None


def write_url_lock(original_url, port, pid):
    """Write base-url.lock atomically."""
    _trace("write_url_lock: entering (url={!r}, port={}, pid={})".format(
        original_url, port, pid))
    import tempfile
    data = {
        "original_url": original_url,
        "proxy_port": port,
        "locked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "locked_at_epoch": time.time(),
        "pid": pid
    }
    os.makedirs(PROXY_DIR, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=PROXY_DIR, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f)
        os.replace(tmp, URL_LOCK_FILE)
        _trace("write_url_lock: success")
    except Exception:
        _trace("write_url_lock: FAILED, cleaning up temp file")
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Settings file I/O
# ---------------------------------------------------------------------------

def read_settings_url():
    """Read ANTHROPIC_BASE_URL from settings.json."""
    _trace("read_settings_url: entering")
    try:
        with open(SETTINGS_FILE) as f:
            data = json.load(f)
        url = data.get("env", {}).get("ANTHROPIC_BASE_URL", "")
        _trace("read_settings_url: url={!r}".format(url))
        return url
    except (FileNotFoundError, json.JSONDecodeError):
        _trace("read_settings_url: file not found or invalid JSON -> ''")
        return ""


def write_settings_url(url):
    """Write ANTHROPIC_BASE_URL to settings.json atomically."""
    _trace("write_settings_url: entering")
    import tempfile
    try:
        with open(SETTINGS_FILE) as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        data = {}
    if "env" not in data:
        data["env"] = {}
    data["env"]["ANTHROPIC_BASE_URL"] = url
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(SETTINGS_FILE), suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        os.replace(tmp, SETTINGS_FILE)
        _trace("write_settings_url: success")
    except Exception:
        _trace("write_settings_url: FAILED, cleaning up temp file")
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# URL validation
# ---------------------------------------------------------------------------

def validate_url(url):
    """Validate URL is not localhost and has valid hostname.
    Returns (is_valid, error_message).
    """
    from urllib.parse import urlparse
    if not url:
        return False, "URL is empty"
    parsed = urlparse(url)
    if not parsed.hostname:
        return False, "URL has no hostname"
    if parsed.hostname in ("localhost", "127.0.0.1", "::1"):
        return False, "URL is localhost - cannot proxy to self"
    if parsed.scheme not in ("http", "https"):
        return False, "URL scheme must be http or https"
    return True, None


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_start(args):
    """Start the proxy."""
    import argparse
    import socket
    import subprocess

    parser = argparse.ArgumentParser(prog="claude-retry-proxy start")
    parser.add_argument("--port", "-p", type=int, default=8080,
                        help="Port to listen on (default: 8080)")
    parser.add_argument("--log", "-l", type=str, default=None,
                        help="Trace log file path")
    parser.add_argument("--all", "-a", action="store_true",
                        help="Log full request/response bodies")
    parsed = parser.parse_args(args)
    port = parsed.port

    _trace("cmd_start: entering (port={})".format(port))

    # Acquire swap lock
    if not acquire_swap_lock(timeout=10):
        _trace("cmd_start: acquire_swap_lock -> False, returning 1")
        print("ERROR: Could not acquire URL swap lock. Another start/stop in progress?")
        return 1
    try:
        # Check for existing base-url.lock
        lock = read_url_lock()
        if lock:
            _trace("cmd_start: existing lock found, pid={}".format(lock.get("pid")))
            pid = lock.get("pid")
            if pid and is_pid_alive(pid):
                print("ERROR: Proxy already running (PID {})".format(pid))
                _trace("cmd_start: proxy already running, returning 1")
                return 1
            # Crash recovery — restore original URL from lock first
            _trace("cmd_start: crash recovery — restoring original URL")
            print("INFO: Crash recovery — restoring original URL from stale lock")
            original = lock.get("original_url")
            if original:
                write_settings_url(original)
            # Remove stale lock
            try:
                os.remove(URL_LOCK_FILE)
            except OSError:
                pass

        # Read and validate current URL
        current_url = read_settings_url()
        valid, err = validate_url(current_url)
        if not valid:
            _trace("cmd_start: invalid URL: {}".format(err))
            print("ERROR: Invalid ANTHROPIC_BASE_URL: {}".format(err))
            return 1

        # Swap URL in settings BEFORE spawning proxy
        write_settings_url("http://localhost:{}".format(port))
        _trace("cmd_start: URL swapped to localhost:{}".format(port))

        # Build proxy server command — pass original URL so proxy doesn't read
        # localhost from settings.json (already swapped above)
        proxy_cmd = [sys.executable, "-m", "claude_retry_proxy.server",
                     "--port", str(port), "--upstream-url", current_url]
        if parsed.log:
            proxy_cmd.extend(["--log", parsed.log])
        if getattr(parsed, "all"):
            proxy_cmd.append("--all")

        # Start proxy in background
        creationflags = 0
        if sys.platform == "win32":
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP

        stderr_fh = open(os.path.join(PROXY_DIR, "proxy-stderr.log"), "ab")
        proc = subprocess.Popen(
            proxy_cmd,
            stdout=subprocess.DEVNULL,
            stderr=stderr_fh,
            creationflags=creationflags
        )
        _trace("cmd_start: proxy spawned (pid={})".format(proc.pid))

        # Write URL lock with PROXY SERVER PID (not CLI PID)
        # MUST be after Popen so proc.pid is the server PID for liveness checking
        write_url_lock(current_url, port, proc.pid)

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

        def rollback(kill_proc=False):
            """Restore the original URL and remove the lock after a failed start.

            Two independent try/except blocks: a failure restoring settings must
            not prevent lock removal (and vice versa). If kill_proc, also stop the
            still-running server so no detached zombie is left listening.
            """
            _trace("cmd_start: rollback (kill_proc={})".format(kill_proc))
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
                write_settings_url(current_url)
            except Exception:
                pass
            try:
                os.remove(URL_LOCK_FILE)
            except OSError:
                pass

        # TCP probe: the server binds the port and is ready when a
        # TCP connection succeeds. The probe also detects a server that
        # started then crashed (proc.poll() check on each iteration).
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
                    _trace("cmd_start: proxy exited during TCP probe, rolling back")
                    rollback(kill_proc=False)
                    tail = read_tail(stderr_fh, 2048)
                    print("ERROR: Proxy exited during startup")
                    print(tail)
                    return 1
                time.sleep(0.1)
        if not probe_ok:
            _trace("cmd_start: TCP probe timeout after {} attempts, rolling back".format(attempt))
            rollback(kill_proc=True)
            tail = read_tail(stderr_fh, 2048)
            print("ERROR: Proxy did not become ready on port {} "
                  "within 2s".format(port))
            print(tail)
            return 1

        print("Proxy started on port {}".format(port))
        print("Original URL: {}".format(current_url))
        _trace("cmd_start: success, returning 0")
        return 0
    finally:
        release_swap_lock()


def cmd_stop(args):
    """Stop the proxy and restore original URL."""

    _trace("cmd_stop: entering")

    ok = acquire_swap_lock(timeout=10)
    _trace("cmd_stop: acquire_swap_lock -> {}".format(ok))
    if not ok:
        print("ERROR: Could not acquire URL swap lock. Another start/stop in progress?")
        _trace("cmd_stop: returning 1")
        return 1
    try:
        lock = read_url_lock()
        _trace("cmd_stop: read_url_lock -> {}".format(
            "found" if lock else "not found"))
        if not lock:
            print("Proxy: not running (no lock file)")
            _trace("cmd_stop: returning 0")
            release_swap_lock()
            return 0

        pid = lock.get("pid")
        current_url = read_settings_url()
        original = lock.get("original_url")

        # 1. Signal graceful shutdown via HTTP (if port known)
        port = lock.get("proxy_port")
        shutdown_ok = False
        if port and pid and is_pid_alive(pid):
            _trace("cmd_stop: sending shutdown to pid={} port={}".format(pid, port))
            try:
                import urllib.request
                req = urllib.request.Request(
                    "http://127.0.0.1:{}/admin/shutdown".format(port),
                    method="POST")
                with urllib.request.urlopen(req, timeout=2) as resp:
                    resp.read()
                shutdown_ok = True
                _trace("cmd_stop: shutdown request accepted")
            except Exception as e:
                _trace("cmd_stop: shutdown request failed: {}".format(e))

        # 2. Wait for graceful exit (5s timeout) — poll for proxy-state.json
        #    removal. The server removes this file in its finally block right
        #    after server_close(). os.path.exists is a pure filesystem check —
        #    no PID interaction, no antivirus risk.
        #    Port-polling via socket.create_connection is unreliable on Windows:
        #    the OS may accept connections briefly after server_close().
        if shutdown_ok:
            _trace("cmd_stop: waiting for proxy to exit...")
            deadline = time.time() + 5
            try:
                while time.time() < deadline:
                    if not os.path.exists(PROXY_STATE_FILE):
                        _trace("cmd_stop: proxy exited gracefully (state file removed)")
                        break
                    time.sleep(0.3)
                else:
                    _trace("cmd_stop: timeout waiting for graceful exit")
            except KeyboardInterrupt:
                _trace("cmd_stop: interrupted, proceeding to cleanup")
                # Fall through to cleanup — don't leave locks/URL in bad state

        # 3. Clean up lock files and restore URL BEFORE any force-kill.
        #    If force-kill triggers the antivirus crash, cleanup is already done
        #    and the URL is restored. The proxy process may survive (orphaned)
        #    but the user's settings are correct and locks are cleared.
        try:
            os.remove(URL_LOCK_FILE)
            _trace("cmd_stop: base-url.lock removed")
        except OSError:
            _trace("cmd_stop: base-url.lock not found")

        release_swap_lock()

        try:
            os.remove(PROXY_STATE_FILE)
            _trace("cmd_stop: proxy-state.json removed")
        except OSError:
            _trace("cmd_stop: proxy-state.json not found")
        try:
            os.remove(os.path.join(PROXY_DIR, "proxy-state.lock"))
            _trace("cmd_stop: proxy-state.lock removed")
        except OSError:
            _trace("cmd_stop: proxy-state.lock not found")

        # Check if settings already has a non-localhost URL (manual edit).
        # Warn but still restore — the original URL from the lock is authoritative.
        current_url = read_settings_url()
        if current_url and "localhost" not in current_url and "127.0.0.1" not in current_url:
            if current_url != original:
                print("WARNING: settings.json has non-localhost URL (manual edit?)")
                print("  Current: {}".format(current_url))
                print("  Restoring original: {}".format(original))

        if original:
            _trace("cmd_stop: restoring original={!r}".format(original))
            try:
                write_settings_url(original)
                print("Restored URL: {}".format(original))
            except Exception as e:
                print("ERROR: Failed to restore original URL: {}".format(e))
                print("  Please restore manually: ANTHROPIC_BASE_URL={}".format(original))
        else:
            _trace("cmd_stop: no original_url in lock, skipping URL restore")

        print("Proxy: stopped")

        # 4. Force kill only as last resort — AFTER all cleanup is complete.
        #    If this crashes the CLI (antivirus), the damage is contained.
        if pid and is_pid_alive(pid):
            _trace("cmd_stop: force-killing pid={} (cleanup already done)".format(pid))
            if sys.platform == "win32":
                kill_process_windows(pid)
                # Brief check: did the kill work?
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
    finally:
        # Release swap lock as a final safety net (already released above,
        # but calling again is harmless — release_swap_lock handles ENOENT).
        release_swap_lock()


def cmd_status(args):
    """Show proxy status."""
    _trace("cmd_status: entering")
    lock = read_url_lock()
    if not lock:
        _trace("cmd_status: no lock file -> returning 1")
        print("Proxy: not running (no lock file)")
        return 1

    pid = lock.get("pid")
    port = lock.get("proxy_port", 8080)
    original = lock.get("original_url", "unknown")

    if pid and is_pid_alive(pid):
        _trace("cmd_status: pid={} alive -> returning 0".format(pid))
        print("Proxy: running")
        print("  PID: {}".format(pid))
        print("  Port: {}".format(port))
        print("  Original URL: {}".format(original))
        return 0
    else:
        _trace("cmd_status: pid={} dead (stale lock) -> returning 1".format(pid))
        print("Proxy: not running (stale lock, PID {} dead)".format(pid))
        print("  Run 'claude-retry-proxy stop' to clean up")
        return 1


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def print_usage():
    print("Usage: claude-retry-proxy <command> [options]")
    print()
    print("Commands:")
    print("  start   Start the proxy (URL swap + launch proxy server)")
    print("  stop    Stop the proxy and restore original URL")
    print("  status  Show proxy status")


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
    else:
        print("Unknown command: {}".format(cmd))
        print("Usage: claude-retry-proxy <command> [options]")
        sys.exit(1)

    _trace("main: exit_code={}".format(exit_code))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()