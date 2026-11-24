"""Process lifecycle for the retry proxy.

Holds the process startup/serve/teardown sequence and its two private
mechanisms: the listening server class (`_ProxyHTTPServer`) and the
best-effort stderr wrapper (`_BestEffortStderr`). server.py binds the
handler class into the sequence and remains the entry surface (the
console script `claude_retry_proxy.server:main` and the
`python -m claude_retry_proxy.server` invocation).
"""

import argparse
import http.server
import json
import os
import signal
import socket
import sys
import threading
import time

from . import runtime_state
from . import sinks
from .compat import _compat_validate_constants, _load_compat_state
from .config import load_config, validate_config
from .keys import load_keys_file, read_passphrase_from_stdin, vendor_key_names
from .settings import SETTINGS, resolve_trace_file
from .sinks import log_trace, write_state, write_start_marker, write_stop_marker


class _BestEffortStderr:
    """Wraps a stderr stream so diagnostic prints cannot raise into callers.

    Runtime stderr prints — server.py's own and, on the forward path,
    forwarder.py's — include several inside the retry loop's try block. A
    stderr write failure there (full disk — proxy-stderr.log sits on the same
    volume as the sinks) would be read by the loop's
    `except (httpx2.RequestError, httpx2.StreamError, OSError)` clause as a
    connection error, re-issuing the upstream POST or dropping an
    already-answered response. Guarding the stream covers every present and
    future print site.
    """

    def __init__(self, stream):
        self._stream = stream

    def write(self, data):
        try:
            return self._stream.write(data)
        except Exception:
            # Generic form: a payload with no __len__ must not turn the
            # swallowed write failure into a TypeError out of this wrapper.
            return len(data) if hasattr(data, "__len__") else 0

    def flush(self):
        try:
            self._stream.flush()
        except Exception:
            pass

    def __getattr__(self, name):
        return getattr(self._stream, name)


class _ProxyHTTPServer(http.server.ThreadingHTTPServer):
    """The proxy's listening server.

    allow_reuse_address is platform-dependent because SO_REUSEADDR does not
    mean the same thing on Windows. On POSIX it tolerates binding a port left
    in TIME_WAIT while still refusing a second LISTEN. On Windows it permits
    binding a port that already has a live listener, so the sole-owner
    guarantee needs a plain bind there; a plain bind still tolerates
    TIME_WAIT on Windows. On POSIX a plain bind would refuse the TIME_WAIT
    residue a just-stopped proxy leaves behind, so that branch keeps the
    reuse flag.
    """
    allow_reuse_address = sys.platform != "win32"
    # socketserver's default accept backlog is 5; a burst of
    # simultaneous connections (parallel tool fan-outs, test
    # concurrency) overflows it and the kernel drops SYNs — measured
    # 2026-11-19 via TcpExtListenDrops/ListenOverflows deltas (+71)
    # during six 20-request bursts (evidence: plan
    # 2026-11-19-drop-redacted-thinking-chat-placeholder, issue
    # ingress-listen-backlog). A dropped connection never reaches the
    # handler: the client sees a ~1 s SYN-retransmit stall or a
    # ConnectionResetError, and leaves no trace entry. 128 gives
    # realistic fan-outs 25x headroom; somaxconn clamps beyond that.
    request_queue_size = 128


def run_server(handler_class):
    # Parse CLI args
    parser = argparse.ArgumentParser(
        description="HTTP retry proxy for Claude API")
    parser.add_argument("--port", type=int, default=None,
                        help="Port to listen on (default: $PROXY_PORT or 8080)")
    parser.add_argument("--log", "-l", type=str, default=None,
                        help="Trace log file path")
    parser.add_argument("--all", "-a", action="store_true",
                        help="Log full request/response bodies")
    parser.add_argument("--config-path", type=str, default=None,
                        help="Path to config.json (default: ~/.claude/proxy/config.json)")
    parser.add_argument("--keys-path", type=str, default=None,
                        help="Path to encrypted keys-index.json (default: ~/.claude/keys-index.json)")
    parser.add_argument("--passphrase-file", type=str, default=None,
                        help="Read passphrase from file instead of stdin")
    args = parser.parse_args()

    if args.port is not None:
        SETTINGS.port = args.port
    SETTINGS.trace_file = resolve_trace_file(args.log)
    if getattr(args, "all"):
        SETTINGS.log_all = True
    sinks.configure(trace_path=SETTINGS.trace_file, state_path=SETTINGS.state_file)

    # Resolve paths
    config_path = args.config_path or SETTINGS.config_path
    keys_path = args.keys_path or SETTINGS.keys_path

    # Read keys file and detect format
    try:
        with open(keys_path, "rb") as _kf:
            _keys_data = _kf.read()
    except FileNotFoundError:
        print("[proxy] ERROR: Keys file not found: {}".format(keys_path), file=sys.stderr)
        sys.exit(1)

    _needs_passphrase = _keys_data.startswith(b"VimCrypt~03!")

    if _needs_passphrase:
        # Read passphrase (same logic as before)
        if args.passphrase_file:
            try:
                with open(args.passphrase_file, "r", encoding="utf-8") as f:
                    passphrase = f.read().rstrip("\r\n")
            except OSError as e:
                print("[proxy] ERROR: Cannot read passphrase file: {}".format(e), file=sys.stderr)
                sys.exit(1)
            if not passphrase:
                print("[proxy] ERROR: Empty passphrase in file", file=sys.stderr)
                sys.exit(1)
        else:
            passphrase = read_passphrase_from_stdin()
    else:
        passphrase = None
        # Warn about plain keys at-rest exposure (mirrors --all warning)
        print("[proxy] WARNING: keys file is plain JSON — API keys are stored "
              "unencrypted on disk", file=sys.stderr)

    # Load keys (decrypts if encrypted, parses plain JSON otherwise)
    try:
        runtime_state._vendors = load_keys_file(keys_path, passphrase)
    except ValueError as e:
        print("[proxy] ERROR: Key decryption failed: {}".format(e), file=sys.stderr)
        sys.exit(1)

    # Load and validate config
    try:
        runtime_state._current_config = load_config(config_path)
        runtime_state._config_path = config_path
    except FileNotFoundError:
        print("[proxy] ERROR: Config file not found: {}".format(config_path), file=sys.stderr)
        print("[proxy] Run 'claude-retry-proxy start' to create from template", file=sys.stderr)
        sys.exit(1)
    except (json.JSONDecodeError, ValueError) as e:
        print("[proxy] ERROR: Invalid config: {}".format(e), file=sys.stderr)
        sys.exit(1)

    provider_names = set(runtime_state._vendors.keys())
    provider_keys = {name: vendor_key_names(v) for name, v in runtime_state._vendors.items()}
    errors = validate_config(runtime_state._current_config, provider_names, provider_keys)
    if errors:
        print("[proxy] ERROR: Config validation failed:", file=sys.stderr)
        for err in errors:
            print("[proxy]   - {}".format(err), file=sys.stderr)
        sys.exit(1)

    # Compatibility subsystem: validate tuning constants and load learned state
    _compat_validate_constants()
    _load_compat_state()

    # Check if another proxy is already running on this port.
    # The probe mirrors the bind it guards, so it can never be stricter than
    # the real listener. On POSIX SO_REUSEADDR tolerates a port left in
    # TIME_WAIT while still refusing a second LISTEN. On Windows the flag
    # means something different: it permits binding a port that already has
    # a live listener, so the probe — and the listener — must use a plain
    # bind there. A plain bind on Windows still tolerates TIME_WAIT.
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if sys.platform != "win32":
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("127.0.0.1", SETTINGS.port))
    except OSError:
        print("[proxy] Port {} is already in use. Proxy may already be running.".format(
            SETTINGS.port), file=sys.stderr)
        sys.exit(1)
    finally:
        sock.close()

    # Write initial state
    state = {
        "pid": os.getpid(),
        "port": SETTINGS.port,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "owner_pid": os.getppid(),
        "last_heartbeat": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "last_request_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    if not write_state(state):
        try:
            print("[proxy] ERROR: state file {} is not writable — aborting startup".format(
                SETTINGS.state_file), file=sys.stderr)
        except Exception:
            pass
        sys.exit(1)
    runtime_state._startup_state = state

    # Write start marker to trace
    if not write_start_marker(SETTINGS.port):
        try:
            print("[proxy] ERROR: trace file {} is not writable — aborting startup".format(
                SETTINGS.trace_file), file=sys.stderr)
        except Exception:
            pass
        sys.exit(1)

    # Runtime diagnostics become best-effort from here on (see _BestEffortStderr).
    # Installed after both fail-fast checks so their ERROR lines stay loud.
    sys.stderr = _BestEffortStderr(sys.stderr)

    # Start background threads
    threading.Thread(target=runtime_state.heartbeat_loop, daemon=True).start()

    # Start server with ThreadingHTTPServer for concurrent requests
    server = _ProxyHTTPServer(("127.0.0.1", SETTINGS.port), handler_class)
    print("[proxy] Listening on 127.0.0.1:{}".format(SETTINGS.port), file=sys.stderr)
    print("[proxy] Providers: {}".format(", ".join(runtime_state._vendors.keys())), file=sys.stderr)
    # Register graceful shutdown signal handlers so write_stop_marker()
    # runs on normal shutdown (claude-retry-proxy stop sends SIGTERM/taskkill).
    def _shutdown_handler(signum, frame):
        # socketserver.BaseServer.shutdown() blocks until serve_forever()
        # returns, and a Python signal handler runs ON the serve_forever
        # thread — calling it inline is the documented deadlock. Dispatch it,
        # mirroring the admin path's _delayed_shutdown.
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, _shutdown_handler)
    if sys.platform != "win32":
        signal.signal(signal.SIGINT, _shutdown_handler)
    # On Windows, Ctrl+C raises KeyboardInterrupt which the try/except already handles

    # Readiness now post-dates handler registration: READY (stdout marker for
    # the CLI) and the pollable proxy_ready trace event both mean "fully
    # initialised" — a consumer acting on either can safely deliver SIGTERM.
    print("READY", flush=True)
    log_trace({
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
        "event": "proxy_ready",
        "port": SETTINGS.port,
        "pid": os.getpid(),
    })

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        write_stop_marker()
        # Clean up state file
        try:
            os.remove(SETTINGS.state_file)
        except OSError:
            pass
