#!/usr/bin/env python3
"""HTTP retry proxy for Claude API. Listens on localhost and forwards requests
to the upstream endpoint, retrying on 429 (Too Many Requests) and 503 (Service
Unavailable) with jittered exponential backoff. Logs all requests to a JSONL
trace file.

Provider-agnostic — reads upstream URL from settings.json at startup. Supports
concurrent requests via ThreadingHTTPServer.

Dependencies: Python stdlib only (http.server, http.client, json, threading,
uuid, signal, socket, os, sys, time, re, urllib.parse, argparse).
"""

import argparse
import http.client
import http.server
import json
import math
import os
import random
import re
import signal
import socket
import sys
import threading
import time
import uuid
from urllib.parse import urlparse


# ---------------------------------------------------------------------------
# Configuration (environment variables with validation and defaults)
# ---------------------------------------------------------------------------

def _env_int(name, default, min_val=None, max_val=None):
    val = os.environ.get(name, "")
    if val == "":
        return default
    try:
        v = int(val)
        if min_val is not None and v < min_val:
            return default
        if max_val is not None and v > max_val:
            return default
        return v
    except ValueError:
        return default


def _env_str(name, default):
    val = os.environ.get(name, "")
    return val if val else default


PROXY_PORT = _env_int("PROXY_PORT", 8080, 1024, 65535)
PROXY_MAX_RETRIES = _env_int("PROXY_MAX_RETRIES", 10, 1, 100)
PROXY_INITIAL_DELAY = _env_int("PROXY_INITIAL_DELAY", 1, 1, 60)
PROXY_MAX_DELAY = _env_int("PROXY_MAX_DELAY", 30, 1, 300)
PROXY_MAX_BODY_SIZE = _env_int("PROXY_MAX_BODY_SIZE", 10 * 1024 * 1024, 1024, 100 * 1024 * 1024)

PROXY_LOG_ALL = _env_str("PROXY_LOG_ALL", "") == "1"

_default_trace = os.path.join(os.path.expanduser("~"), ".claude", "logs", "proxy-trace.jsonl")
PROXY_TRACE_FILE = _env_str("PROXY_TRACE_FILE", _default_trace)

# Thread-local RNG — the module-global random is not thread-safe under
# ThreadingHTTPServer worker threads (Mersenne Twister state is shared).
_rng_local = threading.local()

def _rng():
    """Per-thread random.Random instance, lazily created."""
    r = getattr(_rng_local, "rng", None)
    if r is None:
        r = random.Random()
        _rng_local.rng = r
    return r

# Whitelisted paths and methods
ALLOWED_PATH_RE = re.compile(r"^/v1/")
ALLOWED_METHODS = {"POST", "OPTIONS"}

# Headers forwarded to upstream
FORWARD_HEADERS = {"authorization", "x-api-key", "content-type",
                   "anthropic-version", "accept"}


# ---------------------------------------------------------------------------
# Upstream URL — read from settings.json at startup (provider-agnostic)
# ---------------------------------------------------------------------------

def read_upstream_url():
    """Read ANTHROPIC_BASE_URL from settings.json."""
    settings_path = os.path.join(os.path.expanduser("~"), ".claude", "settings.json")
    try:
        with open(settings_path) as f:
            data = json.load(f)
        url = data.get("env", {}).get("ANTHROPIC_BASE_URL", "")
        return url
    except (FileNotFoundError, json.JSONDecodeError):
        return ""


def parse_upstream(url):
    """Parse upstream URL into (host, port, use_ssl, path_prefix). Returns None on failure."""
    if not url:
        return None
    parsed = urlparse(url)
    host = parsed.hostname
    if not host:
        return None
    if parsed.scheme == "https":
        port = parsed.port or 443
        use_ssl = True
    elif parsed.scheme == "http":
        port = parsed.port or 80
        use_ssl = False
    else:
        return None
    path_prefix = parsed.path.rstrip("/") if parsed.path else ""
    return (host, port, use_ssl, path_prefix)


# Module-level globals — assigned at runtime in main() (not at import time).
# This avoids sys.exit(1) on import when settings.json is absent, so tests
# and --help work without a valid upstream URL configured.
UPSTREAM_URL = ""
UPSTREAM_HOST = UPSTREAM_PORT = UPSTREAM_USE_SSL = UPSTREAM_PATH_PREFIX = None


STATE_FILE = os.path.join(os.path.expanduser("~"), ".claude", "proxy",
                          "proxy-state.json")


def read_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def write_state(state):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f)
    os.replace(tmp, STATE_FILE)
    # Restrict permissions on POSIX (best-effort; Windows chmod is a near-no-op).
    if os.name == "posix":
        try:
            os.chmod(STATE_FILE, 0o600)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Trace logging (thread-safe)
# ---------------------------------------------------------------------------

_trace_lock = threading.Lock()

# Request counters for stop marker
_request_counter_lock = threading.Lock()
_requests_total = 0
_requests_retried = 0


# Shutdown flag — checked by background threads to avoid interfering with
# graceful shutdown. Set True by the /admin/shutdown handler.
_shutting_down = False


def increment_total():
    global _requests_total
    with _request_counter_lock:
        _requests_total += 1


def increment_retried():
    global _requests_retried
    with _request_counter_lock:
        _requests_retried += 1


def log_trace(entry):
    d = os.path.dirname(PROXY_TRACE_FILE)
    if d:
        os.makedirs(d, exist_ok=True)
    with _trace_lock:
        with open(PROXY_TRACE_FILE, "a") as f:
            f.write(json.dumps(entry) + "\n")
    # Restrict permissions on POSIX (best-effort; Windows chmod is a near-no-op).
    if os.name == "posix":
        try:
            os.chmod(PROXY_TRACE_FILE, 0o600)
        except OSError:
            pass


def write_start_marker():
    log_trace({
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
        "event": "proxy_start",
        "port": PROXY_PORT,
        "original_url": UPSTREAM_URL,
        "pid": os.getpid()
    })


def write_stop_marker():
    with _request_counter_lock:
        total = _requests_total
        retried = _requests_retried
    log_trace({
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
        "event": "proxy_stop",
        "pid": os.getpid(),
        "requests_total": total,
        "requests_retried": retried
    })


def compute_delay(attempt):
    """Exponential backoff: 2^attempt seconds, capped at PROXY_MAX_DELAY."""
    delay = PROXY_INITIAL_DELAY * (2 ** attempt)
    return min(delay, PROXY_MAX_DELAY)


def compute_jittered_delay(base):
    """±25% uniform jitter on base, unbiased half-up rounded to an integer second, floored at 0.

    Uses floor(x + 0.5), NOT round(): Python 3 round() is banker's rounding,
    which collapses small even base values to a constant.
    """
    if base <= 0:
        return 0
    jitter = _rng().uniform(-0.25, 0.25) * base
    return max(0, math.floor(base + jitter + 0.5))


# ---------------------------------------------------------------------------
# Heartbeat thread
# ---------------------------------------------------------------------------

def heartbeat_loop():
    while not _shutting_down:
        time.sleep(30)
        if _shutting_down:
            break
        state = read_state()
        state["last_heartbeat"] = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        write_state(state)


# ---------------------------------------------------------------------------
# HTTP request forwarding
# ---------------------------------------------------------------------------

def forward_request(method, path, headers, body):
    """Forward a request to the upstream API.
    Returns (status, response_headers, body_bytes, first_byte_ms, total_sec, retries).
    total_sec covers the entire request including all retry waits.
    On 429 and 503, retries with jittered exponential backoff. 429 uses the
    maximal delay (PROXY_MAX_DELAY); 503 uses the exponential.
    """
    if method not in ALLOWED_METHODS:
        return 400, {}, b'{"error":"Method not allowed"}', 0, 0, 0

    if not ALLOWED_PATH_RE.match(path):
        return 400, {}, b'{"error":"Path not allowed"}', 0, 0, 0

    if body and len(body) > PROXY_MAX_BODY_SIZE:
        return 413, {}, b'{"error":"Payload too large"}', 0, 0, 0

    # Filter headers for forwarding
    fwd_headers = {}
    for k, v in headers.items():
        if k.lower() in FORWARD_HEADERS:
            fwd_headers[k] = v

    total_start = time.time()
    last_status = None
    retries = 0

    for attempt in range(PROXY_MAX_RETRIES + 1):
        try:
            if UPSTREAM_USE_SSL:
                conn = http.client.HTTPSConnection(UPSTREAM_HOST, UPSTREAM_PORT,
                                                   timeout=300)
            else:
                conn = http.client.HTTPConnection(UPSTREAM_HOST, UPSTREAM_PORT,
                                                  timeout=300)
            upstream_path = UPSTREAM_PATH_PREFIX + path if UPSTREAM_PATH_PREFIX else path
            conn.request(method, upstream_path, body=body, headers=fwd_headers)
            resp = conn.getresponse()

            if resp.status in (429, 503):
                last_status = resp.status
                if attempt < PROXY_MAX_RETRIES:
                    if resp.status == 429:
                        delay = compute_jittered_delay(PROXY_MAX_DELAY)
                        reason = "429"
                    elif resp.status == 503:
                        delay = compute_jittered_delay(compute_delay(attempt))
                        reason = "503"
                    else:  # defensive — future expansion must add a branch here
                        delay = compute_jittered_delay(compute_delay(attempt))
                        reason = str(resp.status)
                    try:
                        resp.read()  # drain response body before close
                    except (socket.error, OSError):
                        pass
                    retries += 1
                    increment_retried()
                    print("[proxy] {} on attempt {}/{}, retrying in {}s".format(
                        reason, attempt + 1, PROXY_MAX_RETRIES + 1, delay), file=sys.stderr)
                    log_trace({
                        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        "event": "retry",
                        "attempt": attempt + 1,
                        "delay_s": delay,
                        "reason": reason,
                        "path": path,
                    })
                    time.sleep(delay)
                    conn.close()
                    continue
                else:
                    return resp.status, {}, b'', None, time.time() - total_start, retries

            # Non-retryable response — stream it back
            first_byte_start = time.time()
            chunks = []
            first_byte = True
            first_byte_elapsed = None

            while True:
                chunk = resp.read(8192)
                if not chunk:
                    break
                if first_byte:
                    first_byte_elapsed = (time.time() - first_byte_start) * 1000
                    first_byte = False
                chunks.append(chunk)

            total_elapsed = time.time() - total_start

            resp_headers = dict(resp.getheaders())
            conn.close()

            return (resp.status, resp_headers, b"".join(chunks),
                    first_byte_elapsed, total_elapsed, retries)

        except (socket.error, ConnectionError, OSError) as e:
            last_status = 0
            if attempt < PROXY_MAX_RETRIES:
                delay = compute_delay(attempt)
                retries += 1
                increment_retried()
                print("[proxy] Connection error on attempt {}: {}, retrying in {}s".format(
                    attempt + 1, e, delay), file=sys.stderr)
                log_trace({
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "event": "retry",
                    "attempt": attempt + 1,
                    "delay_s": delay,
                    "reason": "connection_error",
                    "error": sanitize_error(str(e)),
                    "path": path,
                })
                time.sleep(delay)
                continue
            else:
                total_elapsed = time.time() - total_start
                return 0, {}, b'', None, total_elapsed, retries

    total_elapsed = time.time() - total_start
    return last_status or 0, {}, b'', None, total_elapsed, retries


# ---------------------------------------------------------------------------
# Model extraction
# ---------------------------------------------------------------------------

def extract_model(body_bytes):
    if not body_bytes:
        return "unknown"
    try:
        data = json.loads(body_bytes)
        return data.get("model", "unknown")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return "unknown"


# ---------------------------------------------------------------------------
# Error message sanitization
# ---------------------------------------------------------------------------

def sanitize_error(msg):
    if not msg:
        return None
    msg = str(msg)
    msg = re.sub(r'(?:/[^\s"]*)+([/\\]\.(?:claude|ssh|gnupg|aws|azure|config|local))[^\s"]*',
                 r'[redacted-path]', msg)
    msg = re.sub(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b',
                 '[redacted-ip]', msg)
    return msg[:200]


# ---------------------------------------------------------------------------
# HTTP request handler
# ---------------------------------------------------------------------------

class ProxyHandler(http.server.BaseHTTPRequestHandler):

    def _send_response(self, status, body_bytes, headers=None):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        if headers:
            for k, v in headers.items():
                if k.lower() not in {"content-type", "transfer-encoding",
                                     "content-length", "connection"}:
                    self.send_header(k, v)
        self.send_header("Content-Length", str(len(body_bytes)))
        self.end_headers()
        self.wfile.write(body_bytes)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Allow", "POST, OPTIONS")
        self.end_headers()

    def do_POST(self):
        # Admin shutdown — localhost-only, graceful shutdown via server.shutdown()
        if self.path == "/admin/shutdown":
            if self.client_address[0] not in ("127.0.0.1", "::1"):
                self.send_response(403)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"error":"forbidden"}')
                return

            global _shutting_down
            if _shutting_down:
                self._send_response(200, b'{"status":"already_shutting_down"}')
                return
            _shutting_down = True

            self._send_response(200, b'{"status":"shutting_down"}')

            def _delayed_shutdown():
                time.sleep(0.1)
                try:
                    self.server.shutdown()
                except Exception as e:
                    print("[proxy] ERROR during shutdown: {}".format(e),
                          file=sys.stderr)
            threading.Thread(target=_delayed_shutdown, daemon=True).start()
            return

        request_id = str(uuid.uuid4())

        # Read request body
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length > PROXY_MAX_BODY_SIZE:
            self._send_response(413,
                b'{"error":"Payload too large"}')
            log_trace({
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "event": "request",
                "request_id": request_id,
                "method": self.command,
                "path": self.path,
                "model": "unknown",
                "status": "failure",
                "http_status": 413,
                "retries": 0,
                "total_latency_sec": 0,
                "first_byte_latency_ms": None,
                "error": "Payload too large"
            })
            return
        body = self.rfile.read(content_length) if content_length > 0 else b""

        # request_id already generated above
        model = extract_model(body)

        increment_total()

        status, resp_headers, resp_body, first_byte_ms, total_sec, retries = \
            forward_request(self.command, self.path,
                            {k: v for k, v in self.headers.items()},
                            body)

        # Build trace entry
        success = 200 <= status < 300
        trace_entry = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "event": "request",
            "request_id": request_id,
            "method": self.command,
            "path": self.path,
            "model": model,
            "status": "success" if success else "failure",
            "http_status": status,
            "retries": retries,
            "total_latency_sec": round(total_sec, 3) if total_sec else 0,
            "first_byte_latency_ms": int(first_byte_ms) if first_byte_ms else None,
            "error": None if success else sanitize_error(
                resp_body.decode("utf-8", errors="replace") if resp_body else
                "HTTP {}".format(status))
        }

        if PROXY_LOG_ALL:
            # Include full request/response bodies
            try:
                trace_entry["request_body"] = json.loads(body.decode("utf-8"))
            except Exception:
                trace_entry["request_body"] = body.decode("utf-8", errors="replace") if body else None
            try:
                trace_entry["response_body"] = json.loads(resp_body.decode("utf-8"))
            except Exception:
                trace_entry["response_body"] = resp_body.decode("utf-8", errors="replace") if resp_body else None

        log_trace(trace_entry)

        self._send_response(status, resp_body, resp_headers)

    def log_message(self, format, *args):
        # Suppress default http.server logging (we use our own trace log)
        pass


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    # Parse CLI args
    parser = argparse.ArgumentParser(
        description="HTTP retry proxy for Claude API")
    parser.add_argument("--port", type=int, default=None,
                        help="Port to listen on (default: $PROXY_PORT or 8080)")
    parser.add_argument("--log", "-l", type=str, default=None,
                        help="Trace log file path")
    parser.add_argument("--all", "-a", action="store_true",
                        help="Log full request/response bodies")
    parser.add_argument("--upstream-url", type=str, default=None,
                        help="Upstream API base URL (passed by CLI; overrides settings.json)")
    args = parser.parse_args()

    global PROXY_PORT, PROXY_TRACE_FILE, PROXY_LOG_ALL
    global UPSTREAM_URL, UPSTREAM_HOST, UPSTREAM_PORT, UPSTREAM_USE_SSL, UPSTREAM_PATH_PREFIX

    if args.port is not None:
        PROXY_PORT = args.port
    if args.log is not None:
        if not os.path.isabs(args.log):
            args.log = os.path.join(os.getcwd(), args.log)
        PROXY_TRACE_FILE = args.log
    if getattr(args, "all"):
        PROXY_LOG_ALL = True

    # Resolve upstream URL at runtime (not import time).
    # CLI always passes --upstream-url; direct invocation reads settings.json.
    if args.upstream_url is not None:
        UPSTREAM_URL = args.upstream_url
    else:
        UPSTREAM_URL = read_upstream_url()
    parsed = parse_upstream(UPSTREAM_URL)
    if parsed is None:
        if args.upstream_url is not None:
            print("[proxy] ERROR: Invalid --upstream-url: {}".format(UPSTREAM_URL),
                  file=sys.stderr)
        else:
            print("[proxy] ERROR: Could not parse ANTHROPIC_BASE_URL from settings.json: {!r}".format(UPSTREAM_URL),
                  file=sys.stderr)
        sys.exit(1)
    UPSTREAM_HOST, UPSTREAM_PORT, UPSTREAM_USE_SSL, UPSTREAM_PATH_PREFIX = parsed

    # Check if another proxy is already running on this port
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", PROXY_PORT))
    except OSError:
        print("[proxy] Port {} is already in use. Proxy may already be running.".format(
            PROXY_PORT), file=sys.stderr)
        sys.exit(1)
    finally:
        sock.close()

    # Write initial state
    state = {
        "pid": os.getpid(),
        "port": PROXY_PORT,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "owner_pid": os.getppid(),
        "original_url": UPSTREAM_URL,
        "last_heartbeat": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "last_request_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    write_state(state)

    # Write start marker to trace
    write_start_marker()

    # Start background threads
    threading.Thread(target=heartbeat_loop, daemon=True).start()

    # Start server with ThreadingHTTPServer for concurrent requests
    server = http.server.ThreadingHTTPServer(("127.0.0.1", PROXY_PORT), ProxyHandler)
    print("[proxy] Listening on 127.0.0.1:{}".format(PROXY_PORT), file=sys.stderr)
    print("[proxy] Upstream: {}:{}".format(UPSTREAM_HOST, UPSTREAM_PORT), file=sys.stderr)
    # Register graceful shutdown signal handlers so write_stop_marker()
    # runs on normal shutdown (claude-retry-proxy stop sends SIGTERM/taskkill).
    # server.shutdown() causes serve_forever() to return normally into
    # the finally block, which writes the proxy_stop trace marker.
    def _shutdown_handler(signum, frame):
        server.shutdown()

    signal.signal(signal.SIGTERM, _shutdown_handler)
    if sys.platform != "win32":
        signal.signal(signal.SIGINT, _shutdown_handler)
    # On Windows, Ctrl+C raises KeyboardInterrupt which the try/except already handles

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        write_stop_marker()
        # Clean up state file
        try:
            os.remove(STATE_FILE)
        except OSError:
            pass


if __name__ == "__main__":
    main()