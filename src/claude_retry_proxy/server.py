#!/usr/bin/env python3
"""Multi-provider HTTP retry gateway for Claude API. Listens on localhost, routes
requests by model tier (haiku/sonnet/opus) to different upstream providers, retries
429/503/connection errors with jittered exponential backoff, and logs every request
to a JSONL trace file. Tier routing configured via ~/.claude/proxy/config.json;
provider credentials stored encrypted in ~/.claude/keys-index.json (vim blowfish2)
and decrypted at startup via passphrase prompt. Supports concurrent requests via
ThreadingHTTPServer.

Dependencies: cryptography (for vim blowfish2 decryption), plus Python stdlib
(http.server, http.client, json, threading, uuid, signal, socket, os, sys, time,
re, urllib.parse, argparse).
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

from . import vimcrypt


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
PROXY_MAX_RESPONSE_SIZE = _env_int("PROXY_MAX_RESPONSE_SIZE", 100 * 1024 * 1024, 1024, 1024 * 1024 * 1024)

PROXY_LOG_ALL = _env_str("PROXY_LOG_ALL", "") == "1"

_default_trace = os.path.join(os.path.expanduser("~"), ".claude", "logs", "proxy-trace.jsonl")
PROXY_TRACE_FILE = _env_str("PROXY_TRACE_FILE", _default_trace)

# Config paths
DEFAULT_CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".claude", "proxy", "config.json")
CONFIG_TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "config-template.json")
_default_keys = os.path.join(os.path.expanduser("~"), ".claude", "keys-index.json")
PROXY_KEYS_PATH = _env_str("PROXY_KEYS_PATH", _default_keys)

# Thread-safe config access (read by worker threads, written by admin API)
_config_lock = threading.RLock()
_current_config = None  # Set at startup after validation
_config_path = None  # Path to config.json, set at startup

# Drain-and-swap state for config changes (prevents race with in-flight requests)
_inflight_count = 0  # Number of requests currently in-flight
_config_swapping = False  # True when config swap is in progress
_swap_done = threading.Event()  # Signaled when swap completes

# Startup state dict, kept in memory so the heartbeat can rewrite a
# proxy-state.json deleted externally without losing pid/port fields.
_startup_state = None

# Decrypted vendors table (read-only after init)
# {provider_name: {"url": ..., "key": ..., "mode": "anthropic|chat|response"}}
_vendors = None

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

# Admin page and validation
_admin_html_cache = None
ADMIN_BODY_LIMIT = 64 * 1024  # 64 KB cap for admin POST bodies
_ADMIN_NAME_RE = re.compile(r"^[a-zA-Z0-9_./-]+$")


def _load_admin_html():
    """Load admin.html from package data, cached."""
    global _admin_html_cache
    if _admin_html_cache is None:
        admin_path = os.path.join(os.path.dirname(__file__), "admin.html")
        with open(admin_path, "r", encoding="utf-8") as f:
            _admin_html_cache = f.read()
    return _admin_html_cache


def _validate_admin_name(name):
    """Validate provider/model name contains only safe characters."""
    return bool(_ADMIN_NAME_RE.match(name))


def _validate_csrf_origin(handler, port):
    """Validate Origin header for CSRF protection.

    Returns True if valid, False if invalid.
    Rejects: missing Origin, null Origin, non-localhost origins.
    Accepts: http://localhost:<port>, http://127.0.0.1:<port>, http://[::1]:<port>
    """
    origin = handler.headers.get("Origin")
    if not origin:
        return False
    if origin == "null":
        return False
    valid_origins = [
        "http://localhost:{}".format(port),
        "http://127.0.0.1:{}".format(port),
        "http://[::1]:{}".format(port),
    ]
    return origin in valid_origins


# Whitelisted paths and methods
ALLOWED_PATH_RE = re.compile(r"^/v1/")
ALLOWED_METHODS = {"POST", "OPTIONS"}

# Headers forwarded to upstream
FORWARD_HEADERS = {"authorization", "x-api-key", "content-type",
                   "anthropic-version", "accept"}

# Provider endpoint modes
MODE_VALUES = ("anthropic", "chat", "response")


# ---------------------------------------------------------------------------
# Upstream URL parsing
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Config loading and validation
# ---------------------------------------------------------------------------

def load_config(path):
    """Load config.json from path. Returns dict with 'tiers' and 'models' keys.

    Raises ValueError on invalid JSON or missing required structure.
    Raises FileNotFoundError if path doesn't exist.
    """
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("config must be a JSON object")
    if "tiers" not in data:
        raise ValueError("config missing 'tiers' key")
    if "models" not in data:
        raise ValueError("config missing 'models' key")
    if not isinstance(data["tiers"], dict):
        raise ValueError("'tiers' must be an object")
    if not isinstance(data["models"], dict):
        raise ValueError("'models' must be an object")
    return data


def validate_config(config, providers):
    """Validate config against available providers.

    Args:
        config: dict with 'tiers' and 'models' keys
        providers: set of available provider names (from keys-index.json)

    Returns:
        list of error strings. Empty list means valid.
    """
    errors = []
    tiers = config.get("tiers", {})

    # Check all 3 required tiers present
    required_tiers = {"haiku", "sonnet", "opus"}
    missing = required_tiers - set(tiers.keys())
    if missing:
        errors.append("missing required tiers: {}".format(", ".join(sorted(missing))))

    # Check each tier has non-empty provider and model
    for tier_name in required_tiers:
        if tier_name not in tiers:
            continue
        tier = tiers[tier_name]
        if not isinstance(tier, dict):
            errors.append("tier '{}' must be an object".format(tier_name))
            continue
        provider = tier.get("provider", "")
        model = tier.get("model", "")
        if not provider:
            errors.append("tier '{}' has empty provider".format(tier_name))
        elif provider not in providers:
            errors.append("tier '{}' references unknown provider '{}'".format(tier_name, provider))
        if not model:
            errors.append("tier '{}' has empty model".format(tier_name))

    # Check every provider in config.models has a valid model list and exists
    # in keys-index.json (config is authoritative; keys may contain inactive
    # providers that are silently ignored).
    models = config.get("models", {})
    for provider, entry in models.items():
        if not isinstance(entry, list) or len(entry) == 0 \
                or not all(isinstance(m, str) and m.strip() for m in entry):
            errors.append(
                "provider '{}' has no models in config.models — add at least "
                "one model name for this provider".format(provider))
            continue
        if provider not in providers:
            errors.append(
                "provider '{}' in config.models has no entry in keys-index.json".format(provider))

    # Check every tier-referenced provider has at least one model in the catalog
    for tier_name in required_tiers:
        if tier_name not in tiers:
            continue
        tier = tiers[tier_name]
        if not isinstance(tier, dict):
            continue
        provider = tier.get("provider", "")
        if not provider or provider not in providers:
            continue
        entry = models.get(provider)
        if not isinstance(entry, list) or len(entry) == 0 \
                or not all(isinstance(m, str) and m.strip() for m in entry):
            errors.append(
                "provider '{}' (used by tier '{}') has no entry in "
                "config.models — add at least one model name for this "
                "provider".format(provider, tier_name))

    # Validate disable_retry_claude_count_token is a boolean if present
    if "disable_retry_claude_count_token" in config:
        flag = config["disable_retry_claude_count_token"]
        if not isinstance(flag, bool):
            errors.append(
                "disable_retry_claude_count_token must be a boolean "
                "(true/false), got {}".format(type(flag).__name__))

    return errors


def write_config(path, config):
    """Atomically write config to path (write to .tmp, os.replace)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
        os.replace(tmp, path)
    except OSError:
        # Clean up temp file on failure
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def install_template(dest_path):
    """Copy config-template.json from package data to dest_path."""
    import shutil
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    shutil.copy2(CONFIG_TEMPLATE_PATH, dest_path)


def decrypt_keys(path, passphrase):
    """Decrypt keys-index.json and return vendors table.

    Args:
        path: path to encrypted keys-index.json
        passphrase: decryption passphrase

    Returns:
        dict: {provider_name: {"url": ..., "key": ...}}

    Raises:
        FileNotFoundError: if keys file doesn't exist
        ValueError: if decryption fails or JSON is invalid
    """
    with open(path, "rb") as f:
        data = f.read()
    plaintext = vimcrypt.decrypt(data, passphrase)
    try:
        text = plaintext.decode("utf-8")
    except UnicodeDecodeError as e:
        raise ValueError("decrypted keys file is not valid UTF-8: {}".format(e))
    try:
        keys_data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError("decrypted keys file is not valid JSON: {}".format(e))
    if not isinstance(keys_data, dict):
        raise ValueError("keys file must be a JSON object")
    if "vendors" not in keys_data:
        raise ValueError("keys file missing 'vendors' key")
    vendors = keys_data["vendors"]
    if not isinstance(vendors, dict):
        raise ValueError("'vendors' must be an object")
    # Validate each vendor has url and key
    for name, vendor in vendors.items():
        if not isinstance(vendor, dict):
            raise ValueError("vendor '{}' must be an object".format(name))
        if "url" not in vendor:
            raise ValueError("vendor '{}' missing 'url'".format(name))
        if "key" not in vendor:
            raise ValueError("vendor '{}' missing 'key'".format(name))
    return vendors


def load_keys_file(path, passphrase=None):
    """Load keys-index.json (encrypted or plain) and return vendors table.

    If the file starts with VimCrypt~03!, passphrase is required and the
    file is decrypted. Otherwise, the file is parsed as plain JSON
    (passphrase is ignored).
    """
    with open(path, "rb") as f:
        data = f.read()

    if data.startswith(b"VimCrypt~03!"):
        if not passphrase:
            raise ValueError("passphrase required for encrypted keys file")
        plaintext = vimcrypt.decrypt(data, passphrase)
    else:
        # Reject other VimCrypt~ prefixes (e.g. blowfish1) to avoid confusing
        # "not valid JSON" errors
        if data.startswith(b"VimCrypt~"):
            raise ValueError(
                "unsupported vim encryption method — only blowfish2 "
                "(VimCrypt~03!) is supported"
            )
        plaintext = data

    try:
        text = plaintext.decode("utf-8")
    except UnicodeDecodeError as e:
        raise ValueError("keys file is not valid UTF-8: {}".format(e))
    try:
        keys_data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError("keys file is not valid JSON: {}".format(e))
    if not isinstance(keys_data, dict):
        raise ValueError("keys file must be a JSON object")
    if "vendors" not in keys_data:
        raise ValueError("keys file missing 'vendors' key")
    vendors = keys_data["vendors"]
    if not isinstance(vendors, dict):
        raise ValueError("'vendors' must be an object")
    for name, vendor in vendors.items():
        if not isinstance(vendor, dict):
            raise ValueError("vendor '{}' must be an object".format(name))
        if "url" not in vendor:
            raise ValueError("vendor '{}' missing 'url'".format(name))
        if "key" not in vendor:
            raise ValueError("vendor '{}' missing 'key'".format(name))
        mode = vendor.get("mode")
        if mode is None or mode == "":
            print("[proxy] WARNING: provider '{}' has no 'mode' field — "
                  "defaulting to 'anthropic'".format(name), file=sys.stderr)
        elif not isinstance(mode, str) or mode not in MODE_VALUES:
            print("[proxy] WARNING: provider '{}' has unknown mode '{}' — "
                  "requests will fail with invalid_provider_mode".format(
                      name, mode), file=sys.stderr)
    return vendors


def read_passphrase_from_stdin():
    """Read passphrase from stdin (pipe protocol or interactive).

    For direct server invocation:
    - If stdin is a tty: prompt interactively
    - If stdin is a pipe/file: read one line

    Returns:
        str: the passphrase

    Raises:
        ValueError: on EOF or empty passphrase
        SystemExit: on error
    """
    if sys.stdin.isatty():
        # Interactive prompt
        return vimcrypt.prompt_hidden("Passphrase: ")
    else:
        # Pipe protocol: read one line
        line = sys.stdin.readline()
        if not line:
            print("[proxy] ERROR: EOF on stdin before passphrase", file=sys.stderr)
            sys.exit(1)
        passphrase = line.rstrip("\r\n")
        if not passphrase:
            print("[proxy] ERROR: empty passphrase on stdin", file=sys.stderr)
            sys.exit(1)
        return passphrase


STATE_FILE = os.environ.get("PROXY_STATE_FILE",
                            os.path.join(os.path.expanduser("~"), ".claude", "proxy",
                                         "proxy-state.json"))


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

# Client-disconnect errors: raised when the client closed the connection
# before we finished writing the response (e.g. it timed out during a long
# retry storm). These are expected under load; we log a single line and a
# trace event instead of letting socketserver print a traceback per request.
# ConnectionAbortedError covers Windows WinError 10053; ConnectionResetError
# covers WinError 10054 and POSIX ECONNRESET; BrokenPipeError covers POSIX EPIPE.
_DISCONNECT_ERRORS = (ConnectionResetError, BrokenPipeError, ConnectionAbortedError)


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


def _read_capped(resp, max_bytes):
    """Read up to max_bytes from resp. Truncate past the cap with a marker.

    Drains the response body so the connection can be closed cleanly, but
    bounds memory: if the body exceeds max_bytes, stop reading and return a
    standalone truncation marker. Returns the full body unchanged if it fits
    within max_bytes.
    """
    if max_bytes <= 0:
        return b''
    chunks = []
    total = 0
    try:
        while total < max_bytes:
            chunk = resp.read(min(8192, max_bytes - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
    except OSError:
        pass
    # Drain-and-discard the rest so the connection can be closed without a
    # pending RST. Track whether we actually read tail data to distinguish
    # "exactly at cap" from "truncated".
    truncated = False
    try:
        while True:
            tail = resp.read(8192)
            if not tail:
                break
            truncated = True
    except OSError:
        pass
    if truncated:
        return b'{"error":"[proxy: response body truncated]"}'
    return b"".join(chunks)


# ---------------------------------------------------------------------------
# Heartbeat thread
# ---------------------------------------------------------------------------

def heartbeat_loop():
    while not _shutting_down:
        time.sleep(30)
        if _shutting_down:
            break
        if _startup_state is not None:
            _startup_state["last_heartbeat"] = time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            write_state(_startup_state)


# ---------------------------------------------------------------------------
# HTTP request forwarding
# ---------------------------------------------------------------------------

def forward_request(method, path, headers, body, handler=None, request_id=None):
    """Forward a request to the upstream API with tier-based routing.

    Args:
        method, path, headers, body: request components
        handler: ProxyHandler instance for streaming responses
        request_id: unique request identifier for tracing

    Returns (status, response_headers, body_bytes, first_byte_ms, total_sec, retries, tier, provider).
    total_sec covers the entire request including all retry waits.
    On 429 and 503, retries with jittered exponential backoff. 429 uses the
    maximal delay (PROXY_MAX_DELAY); 503 uses the exponential.
    When handler is provided and the upstream responds 2xx, the body is
    streamed to the client in real time via the handler (body_bytes is then
    b""); otherwise the body is buffered and returned.
    """
    global _inflight_count

    # Drain-and-swap: snapshot config state at request start
    # If a config swap is in progress, wait for it to complete before proceeding
    # Snapshot config and vendors together under the same lock
    # to prevent race where config is read before lock but vendors is
    # snapshotted inside lock (reviewer-drain-swap-race fix).
    while True:
        with _config_lock:
            if not _config_swapping:
                # No swap in progress - increment counter and snapshot all state together
                _inflight_count += 1
                config_snapshot = _current_config
                vendors_snapshot = _vendors
                break
        # Swap in progress - wait for it to complete
        _swap_done.wait()

    try:
        return _forward_request_impl(method, path, headers, body, handler, request_id,
                                     config_snapshot, vendors_snapshot)
    finally:
        # Decrement counter when request completes (success or failure)
        with _config_lock:
            _inflight_count -= 1


def _forward_request_impl(method, path, headers, body, handler, request_id,
                          config, vendors):
    """Internal implementation of forward_request with snapshot config."""
    if method not in ALLOWED_METHODS:
        return 400, {}, b'{"error":"Method not allowed"}', 0, 0, 0, "unknown", None, None

    if not ALLOWED_PATH_RE.match(path):
        return 400, {}, b'{"error":"Path not allowed"}', 0, 0, 0, "unknown", None, None

    if body and len(body) > PROXY_MAX_BODY_SIZE:
        return 413, {}, b'{"error":"Payload too large"}', 0, 0, 0, "unknown", None, None

    # Resolve tier from model name
    model_name = extract_model(body)
    tier = resolve_tier(model_name, config)

    if tier == "unknown":
        # Unknown model - reject with 400 listing valid tiers
        # List in plan-specified order: haiku, sonnet, opus
        valid_tiers = [t for t in ("haiku", "sonnet", "opus") if t in config.get("tiers", {})]
        err_msg = json.dumps({
            "error": "Unrecognized model: {}. Valid tiers: {}".format(
                model_name, ", ".join(valid_tiers))
        })
        return 400, {}, err_msg.encode("utf-8"), 0, 0, 0, "unknown", None, None

    # Look up provider and upstream info
    tier_config = config["tiers"][tier]
    provider_name = tier_config["provider"]
    actual_model = tier_config["model"]
    vendor = vendors[provider_name]
    upstream_url = vendor["url"]
    api_key = vendor["key"]

    # Read endpoint mode (None/''/missing normalize to "anthropic")
    mode = vendor.get("mode") or "anthropic"
    if mode not in MODE_VALUES:
        err_msg = json.dumps({
            "error": {
                "type": "invalid_provider_mode",
                "message": "Provider '{}' has invalid mode '{}'. Valid modes: {}".format(
                    provider_name, mode, ", ".join(MODE_VALUES))
            }
        })
        return 500, {}, err_msg.encode("utf-8"), 0, 0, 0, tier, provider_name, actual_model

    if mode != "anthropic":
        log_trace({
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "event": "mode_dispatch",
            "request_id": request_id,
            "tier": tier,
            "provider": provider_name,
            "mode": mode,
        })

    # Parse upstream URL
    parsed = parse_upstream(upstream_url)
    if parsed is None:
        err_msg = json.dumps({
            "error": {
                "type": "invalid_provider_url",
                "message": "Provider '{}' has invalid URL: {}".format(provider_name, upstream_url)
            }
        })
        return 500, {}, err_msg.encode("utf-8"), 0, 0, 0, tier, provider_name, actual_model

    host, port, use_ssl, path_prefix = parsed

    # count_tokens has no equivalent on the OpenAI endpoints — reject it for
    # chat/response modes gated on the same tolerant path check used below.
    _is_count_tokens = path.split("?", 1)[0].rstrip("/").endswith(
        "/messages/count_tokens")
    if mode != "anthropic" and _is_count_tokens:
        err_msg = json.dumps({
            "error": "count_tokens not supported in chat/response mode"
        })
        return 400, {}, err_msg.encode("utf-8"), 0, 0, 0, tier, provider_name, actual_model

    # Build request body once before the retry loop (never re-transformed per
    # attempt). Anthropic mode does a model-only rewrite; chat/response modes
    # run the full body transform. On any failure fall back to the original
    # body and log a transform_failure trace event.
    rewritten_body = body
    if body:
        try:
            body_json = json.loads(body)
            body_json["model"] = actual_model
            if mode == "chat":
                rewritten_body = json.dumps(_anthropic_to_chat(
                    body_json, request_id=request_id, mode=mode,
                    provider=provider_name, tier=tier)).encode("utf-8")
            elif mode == "response":
                rewritten_body = json.dumps(_anthropic_to_response(body_json)).encode("utf-8")
            else:
                rewritten_body = json.dumps(body_json).encode("utf-8")
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError,
                KeyError, IndexError, AttributeError, ValueError):
            if mode != "anthropic":
                log_trace({
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "event": "transform_failure",
                    "request_id": request_id,
                    "provider": provider_name,
                    "tier": tier,
                    "mode": mode,
                })
            rewritten_body = body  # Keep original body if transform/parse fails

    # Build headers for forwarding
    fwd_headers = {}
    for k, v in headers.items():
        if k.lower() in FORWARD_HEADERS:
            # Skip authorization and x-api-key (we inject provider's key)
            if k.lower() in ("authorization", "x-api-key"):
                continue
            fwd_headers[k] = v
    # Inject provider's API key per mode
    if mode == "anthropic":
        fwd_headers["x-api-key"] = api_key
    else:
        fwd_headers["Authorization"] = "Bearer {}".format(api_key)

    # Dispatch upstream path per mode. chat/response modes strip a trailing
    # /v1 from the configured base URL so an OpenAI-style base does not
    # produce a doubled /v1/v1/ prefix.
    if mode == "anthropic":
        upstream_path = path_prefix + path if path_prefix else path
    else:
        if path_prefix.endswith("/v1"):
            path_prefix = path_prefix[:-3]
        endpoint = "/v1/chat/completions" if mode == "chat" else "/v1/responses"
        upstream_path = path_prefix + endpoint

    total_start = time.time()
    last_status = None
    retries = 0

    # Skip retry for count_tokens when disabled (avoids wasting bandwidth
    # on providers that don't support this Anthropic-specific endpoint)
    disable_retry = config.get("disable_retry_claude_count_token", False)
    max_attempts = 1 if (disable_retry and _is_count_tokens) \
                   else PROXY_MAX_RETRIES + 1

    for attempt in range(max_attempts):
        try:
            if use_ssl:
                conn = http.client.HTTPSConnection(host, port, timeout=300)
            else:
                conn = http.client.HTTPConnection(host, port, timeout=300)
            conn.request(method, upstream_path, body=rewritten_body, headers=fwd_headers)
            resp = conn.getresponse()

            if resp.status in (429, 503):
                last_status = resp.status
                if attempt < max_attempts - 1:
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
                    print("[proxy] {} on attempt {}/{}, model={}, provider={}, rid={}, retrying in {}s".format(
                        reason, attempt + 1, max_attempts, actual_model,
                        provider_name, request_id, delay), file=sys.stderr)
                    log_trace({
                        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        "event": "retry",
                        "attempt": attempt + 1,
                        "delay_s": delay,
                        "reason": reason,
                        "model": actual_model,
                        "provider": provider_name,
                        "request_id": request_id,
                        "path": path,
                    })
                    time.sleep(delay)
                    conn.close()
                    continue
                else:
                    err_body = _read_capped(resp, PROXY_MAX_BODY_SIZE)
                    try:
                        conn.close()
                    except OSError:
                        pass
                    return resp.status, {}, err_body, None, time.time() - total_start, retries, tier, provider_name, actual_model

            # Non-retryable response
            resp_headers = dict(resp.getheaders())
            content_type = resp_headers.get("Content-Type", "").lower()

            # Determine response handling strategy based on status and Content-Type
            if handler is not None and 200 <= resp.status < 300:
                # 2xx response - check Content-Type to decide streaming vs buffering
                if "text/event-stream" in content_type:
                    # SSE: stream with mode-appropriate rewriting/transform
                    first_byte_ms = handler._stream_upstream_response(
                        resp, resp.status, resp_headers, request_id, retries,
                        tier=tier, mode=mode)
                    conn.close()
                    return (resp.status, resp_headers, b"",
                            first_byte_ms, time.time() - total_start, retries, tier, provider_name, actual_model)
                elif "application/json" in content_type:
                    # JSON: buffer, then dispatch mode-appropriate transform
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
                    resp_body = b"".join(chunks)
                    conn.close()

                    if mode == "chat":
                        resp_body = _transform_and_guard(
                            resp_body, tier, _chat_to_anthropic, request_id, mode, provider_name)
                    elif mode == "response":
                        resp_body = _transform_and_guard(
                            resp_body, tier, _response_to_anthropic, request_id, mode, provider_name)
                    else:
                        resp_body = _rewrite_json_response(
                            resp_body, tier, request_id)
                    resp_headers["Content-Length"] = str(len(resp_body))

                    return (resp.status, resp_headers, resp_body,
                            first_byte_elapsed, total_elapsed, retries, tier, provider_name, actual_model)
                else:
                    # Other content types: chat/response modes buffer and
                    # transform as JSON (OpenAI APIs return JSON or SSE);
                    # anthropic mode streams unchanged (existing behavior).
                    if mode in ("chat", "response"):
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
                        resp_body = b"".join(chunks)
                        conn.close()
                        transform_fn = _chat_to_anthropic if mode == "chat" else _response_to_anthropic
                        resp_body = _transform_and_guard(
                            resp_body, tier, transform_fn, request_id, mode, provider_name)
                        resp_headers["Content-Length"] = str(len(resp_body))
                        return (resp.status, resp_headers, resp_body,
                                first_byte_elapsed, total_elapsed, retries, tier, provider_name, actual_model)
                    else:
                        first_byte_ms = handler._stream_upstream_response(
                            resp, resp.status, resp_headers, request_id, retries,
                            tier=tier, mode=mode)
                        conn.close()
                        return (resp.status, resp_headers, b"",
                                first_byte_ms, time.time() - total_start, retries, tier, provider_name, actual_model)

            # Non-2xx or no handler — buffer the body so upstream error content
            # stays in the trace log.
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

            resp_body = b"".join(chunks)
            conn.close()

            # Non-2xx error path: anthropic mode keeps the model rewrite it had before;
            # chat/response modes pass upstream error bodies through
            # byte-for-byte untransformed.
            if "application/json" in content_type and mode == "anthropic":
                resp_body = _rewrite_json_response(
                    resp_body, tier, request_id)
                resp_headers["Content-Length"] = str(len(resp_body))

            return (resp.status, resp_headers, resp_body,
                    first_byte_elapsed, total_elapsed, retries, tier, provider_name, actual_model)

        except (socket.error, ConnectionError, OSError) as e:
            last_status = 0
            if attempt < max_attempts - 1:
                delay = compute_jittered_delay(compute_delay(attempt))
                retries += 1
                increment_retried()
                print("[proxy] Connection error on attempt {}/{}, model={}, provider={}, rid={}: {}, retrying in {}s".format(
                    attempt + 1, max_attempts, actual_model, provider_name,
                    request_id, e, delay), file=sys.stderr)
                log_trace({
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "event": "retry",
                    "attempt": attempt + 1,
                    "delay_s": delay,
                    "reason": "connection_error",
                    "model": actual_model,
                    "provider": provider_name,
                    "request_id": request_id,
                    "error": sanitize_error(str(e)),
                    "path": path,
                })
                time.sleep(delay)
                continue
            else:
                total_elapsed = time.time() - total_start
                err_body = json.dumps({
                    "error": {
                        "type": "upstream_unreachable",
                        "message": "upstream: {} after {} retries".format(
                            sanitize_error(str(e)) or "connection failed", retries),
                    }
                }).encode("utf-8")
                return 0, {}, err_body, None, total_elapsed, retries, tier, provider_name, actual_model

    total_elapsed = time.time() - total_start
    return last_status or 0, {}, b'', None, total_elapsed, retries, tier, provider_name, actual_model


# ---------------------------------------------------------------------------
# Model extraction and tier resolution
# ---------------------------------------------------------------------------

def extract_model(body_bytes):
    """Extract model name from request body.

    Returns "unknown" if body is empty, not valid JSON, or model is missing/None/non-string.
    """
    if not body_bytes:
        return "unknown"
    try:
        data = json.loads(body_bytes)
        model = data.get("model")
        # Guard against None or non-string model values
        if model is None or not isinstance(model, str):
            return "unknown"
        return model
    except (json.JSONDecodeError, UnicodeDecodeError):
        return "unknown"


def resolve_tier(model_name, config):
    """Resolve a model name to a tier name.

    Resolution order:
    1. None guard: if model_name is None or not a string, return "unknown"
    2. Direct match: if model_name is "haiku"/"sonnet"/"opus"
    3. Reverse lookup: scan config tiers for matching model
    4. Pattern match: check if tier keyword is in model_name (opus, sonnet, haiku order)

    Returns:
        str: tier name ("haiku", "sonnet", "opus") or "unknown" if unresolvable
    """
    # 1. None guard
    if model_name is None or not isinstance(model_name, str):
        return "unknown"

    # 2. Direct match
    if model_name in ("haiku", "sonnet", "opus"):
        return model_name

    # 3. Reverse lookup: find tier whose configured model matches
    tiers = config.get("tiers", {})
    for tier_name, tier_config in tiers.items():
        if isinstance(tier_config, dict):
            configured_model = tier_config.get("model")
            if configured_model and configured_model == model_name:
                return tier_name

    # 4. Pattern match: check in order opus, sonnet, haiku (most-specific first)
    model_lower = model_name.lower()
    for tier in ("opus", "sonnet", "haiku"):
        if tier in model_lower:
            return tier

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
# Response model rewriting helpers
# ---------------------------------------------------------------------------

SSE_EVENT_DELIMITER = b"\n\n"

# Chat-mode SSE tool-call conversion bounds (mirror the per-frame event buffer).
MAX_CHAT_TOOL_PENDING_BYTES = 64 * 1024
MAX_CHAT_TRACKED_TOOL_INDEXES = 32
MAX_CHAT_OPEN_TOOL_BLOCKS = 32


def _rewrite_sse_first_event(event_bytes, tier, request_id):
    """Rewrite model in first SSE event if it's a message_start event.

    Args:
        event_bytes: raw bytes of first SSE event
        tier: tier name to rewrite model to
        request_id: for logging

    Returns:
        bytes: possibly rewritten event
    """
    # Parse SSE event - look for event: and data: lines
    event_text = event_bytes.decode("utf-8", errors="replace")
    lines = event_text.split("\n")
    event_type = None
    data_lines = []

    for line in lines:
        if line.startswith("event:"):
            event_type = line[6:].strip()
        elif line.startswith("data:"):
            data_lines.append(line[5:].strip())

    # Parse JSON from data lines
    if not data_lines:
        return event_bytes

    json_text = "\n".join(data_lines)
    try:
        data = json.loads(json_text)
    except json.JSONDecodeError:
        # Malformed JSON - forward unchanged with warning
        log_trace({
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "event": "sse_rewrite_malformed_json",
            "request_id": request_id,
        })
        return event_bytes

    # Check if this is a message_start event
    # Check both SSE event type and JSON type field (SSE events can omit event: line)
    json_type = data.get("type") if isinstance(data, dict) else None
    is_message_start = (event_type == "message_start") or (json_type == "message_start")

    if not is_message_start:
        # Not a message_start event - forward unchanged
        return event_bytes

    # Check for model field and rewrite
    message = data.get("message", {})
    if not isinstance(message, dict):
        return event_bytes

    upstream_model = message.get("model")
    if not upstream_model:
        return event_bytes

    # Rewrite model to tier name
    message["model"] = tier
    data["message"] = message

    # Rebuild SSE event - preserve original format
    new_json = json.dumps(data)
    if event_type:
        # Had explicit event: line
        new_event = "event: {}\ndata: {}\n\n".format(event_type, new_json)
    else:
        # Data-only format
        new_event = "data: {}\n\n".format(new_json)
    return new_event.encode("utf-8")


def _rewrite_json_response(body_bytes, tier, request_id):
    """Rewrite model field in JSON response body.

    Args:
        body_bytes: raw response body
        tier: tier name to rewrite model to
        request_id: for logging

    Returns:
        bytes: possibly rewritten body
    """
    try:
        data = json.loads(body_bytes)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return body_bytes

    if not isinstance(data, dict):
        return body_bytes

    upstream_model = data.get("model")
    if not upstream_model or not isinstance(upstream_model, str):
        return body_bytes

    data["model"] = tier
    return json.dumps(data).encode("utf-8")


# ---------------------------------------------------------------------------
# Endpoint-mode request/response transformations
# ---------------------------------------------------------------------------

def _transform_and_guard(raw_body, tier, transform_fn, request_id, mode, provider):
    """Run a response transform on raw JSON bytes with passthrough-on-failure.

    json.loads runs INSIDE the guard: any parse or shape failure logs a
    transform_failure trace event (metadata only — never body content) and
    returns the original raw bytes unchanged.
    """
    try:
        parsed = json.loads(raw_body)
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError):
        log_trace({
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "event": "transform_failure",
            "request_id": request_id,
            "mode": mode,
            "provider": provider,
            "tier": tier,
        })
        return raw_body
    try:
        return json.dumps(transform_fn(parsed, tier, request_id=request_id, mode=mode, provider=provider)).encode("utf-8")
    except (json.JSONDecodeError, KeyError, TypeError, IndexError,
            AttributeError, ValueError):
        log_trace({
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "event": "transform_failure",
            "request_id": request_id,
            "mode": mode,
            "provider": provider,
            "tier": tier,
        })
        return raw_body


def _anthropic_to_chat(body_json, request_id=None, mode=None, provider=None,
                       tier=None):
    """Transform an Anthropic Messages request into OpenAI Chat Completions.

    Builds `out` without mutating `body_json`. messages / tools / tool_choice
    are transformed via the _transform_anthropic_*_to_chat helpers; thinking /
    metadata / top_k are Anthropic-specific request config and are dropped.
    """
    out = {}
    if "model" in body_json:
        out["model"] = body_json["model"]
    cache_locations = []
    if "messages" in body_json:
        out["messages"] = _transform_anthropic_messages_to_chat(
            body_json.get("messages", []), request_id=request_id, mode=mode,
            provider=provider, tier=tier, cache_stripped_out=cache_locations)

    system = body_json.get("system")
    system_text = None
    if isinstance(system, str):
        system_text = system
    elif isinstance(system, list):
        parts = [b.get("text") for b in system
                 if isinstance(b, dict) and isinstance(b.get("text"), str)]
        system_text = "\n".join(parts)
    if system_text:
        messages = out.get("messages")
        if not isinstance(messages, list):
            messages = []
        messages.insert(0, {"role": "system", "content": system_text})
        out["messages"] = messages

    if "tools" in body_json and isinstance(body_json.get("tools"), list):
        transformed_tools = _transform_anthropic_tools_to_chat(
            body_json["tools"], request_id=request_id, mode=mode,
            provider=provider, tier=tier, cache_stripped_out=cache_locations)
        out["tools"] = transformed_tools
        if transformed_tools and "tool_choice" in body_json:
            tc = _transform_anthropic_tool_choice_to_chat(
                body_json.get("tool_choice"))
            if tc is not None:
                out["tool_choice"] = tc

    if cache_locations:
        log_trace({
            "timestamp": _request_transform_timestamp(),
            "event": "cache_control_stripped",
            "request_id": request_id,
            "locations": cache_locations,
            "mode": mode,
            "provider": provider,
            "tier": tier,
        })

    for field in ("max_tokens", "temperature", "stream", "top_p"):
        if field in body_json:
            out[field] = body_json[field]
    if "stop_sequences" in body_json:
        out["stop"] = body_json["stop_sequences"]
    return out


def _request_transform_timestamp():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _transform_anthropic_messages_to_chat(messages, request_id=None, mode=None,
                                          provider=None, tier=None,
                                          cache_stripped_out=None):
    """Convert an Anthropic messages array into OpenAI Chat messages.

    Always returns a new list (never mutates the input). thinking blocks are
    converted to reasoning_content on the assistant message; redacted_thinking
    blocks with non-empty data are converted to a placeholder; image / unknown
    blocks are stripped; tool_use and tool_result are converted to OpenAI
    tool_calls / role:tool messages; cache_control is stripped from kept
    blocks. cache_control_stripped is reported to the caller via the optional
    cache_stripped_out list rather than logged here, so _anthropic_to_chat can
    coalesce one event per request.
    """
    if not isinstance(messages, list):
        return []
    dropped = {"thinking": 0, "redacted_thinking": 0, "image": 0,
               "tool_result": 0, "unknown": 0}
    passthrough = {"redacted_thinking": 0}
    cache_stripped = False
    tool_use_ids = set()
    out = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        role = msg.get("role")
        content = msg.get("content")
        if isinstance(content, str):
            out.append({"role": role, "content": content})
            continue
        if role == "user" and (content is None or content == []):
            out.append({"role": "user", "content": ""})
            continue
        if not isinstance(content, list):
            continue
        if role == "assistant":
            text_parts = []
            tool_calls = []
            reasoning_text = None
            for block in content:
                if not isinstance(block, dict):
                    dropped["unknown"] += 1
                    continue
                if "cache_control" in block:
                    cache_stripped = True
                btype = block.get("type")
                if btype == "thinking":
                    thinking = block.get("thinking")
                    if isinstance(thinking, str) and thinking:
                        reasoning_text = thinking
                    else:
                        dropped["thinking"] += 1
                    continue
                if btype == "redacted_thinking":
                    data = block.get("data")
                    if isinstance(data, str) and data and reasoning_text is None:
                        reasoning_text = "[redacted_thinking: data not available]"
                        passthrough["redacted_thinking"] += 1
                        log_trace({
                            "timestamp": _request_transform_timestamp(),
                            "event": "redacted_thinking_passthrough",
                            "request_id": request_id,
                            "mode": mode,
                            "provider": provider,
                            "tier": tier,
                            "data_length": len(data) if isinstance(data, str) else -1,
                        })
                    else:
                        dropped["redacted_thinking"] += 1
                    continue
                if btype == "tool_use":
                    tool_name = block.get("name")
                    tool_id = block.get("id")
                    input_val = block.get("input")
                    if not isinstance(input_val, dict):
                        text_parts.append(
                            "[Tool call failed: arguments for '{}' (call {}) "
                            "could not be serialized as JSON]".format(
                                tool_name or "<unknown>", tool_id or "<unknown>"))
                        log_trace({
                            "timestamp": _request_transform_timestamp(),
                            "event": "tool_args_parse_failure",
                            "request_id": request_id,
                            "mode": mode,
                            "provider": provider,
                            "tier": tier,
                            "tool_name": tool_name,
                            "tool_id": tool_id,
                            "error": "tool_use.input must be a JSON object",
                        })
                        continue
                    try:
                        arguments = json.dumps(input_val, allow_nan=False)
                    except (ValueError, TypeError) as exc:
                        text_parts.append(
                            "[Tool call failed: arguments for '{}' (call {}) "
                            "could not be serialized as JSON]".format(
                                tool_name or "<unknown>", tool_id or "<unknown>"))
                        log_trace({
                            "timestamp": _request_transform_timestamp(),
                            "event": "tool_args_parse_failure",
                            "request_id": request_id,
                            "mode": mode,
                            "provider": provider,
                            "tier": tier,
                            "tool_name": tool_name,
                            "tool_id": tool_id,
                            "error": str(exc),
                        })
                        continue
                    if not isinstance(tool_id, str) or not tool_id:
                        dropped["unknown"] += 1
                        continue
                    tool_use_ids.add(tool_id)
                    if not isinstance(tool_name, str):
                        tool_name = ""
                    tool_calls.append({
                        "id": tool_id,
                        "type": "function",
                        "function": {
                            "name": tool_name,
                            "arguments": arguments,
                        },
                    })
                    continue
                if btype == "text":
                    text_parts.append(block.get("text"))
                    continue
                dropped["unknown"] += 1
            def _assistant_msg(content):
                m = {"role": "assistant", "content": content}
                if reasoning_text is not None:
                    m["reasoning_content"] = reasoning_text
                    m["reasoning"] = reasoning_text
                return m

            if tool_calls and text_parts:
                # Split structure: reasoning_content rides on the text message;
                # the content:null tool_calls message stays clean.
                out.append(_assistant_msg("\n".join(
                    t for t in text_parts if isinstance(t, str))))
                out.append({"role": "assistant", "content": None,
                            "tool_calls": tool_calls})
            elif tool_calls:
                m = _assistant_msg(None)
                m["tool_calls"] = tool_calls
                out.append(m)
            elif text_parts:
                out.append(_assistant_msg("\n".join(
                    t for t in text_parts if isinstance(t, str))))
            else:
                out.append(_assistant_msg(""))
        elif role == "user":
            tool_messages = []
            text_parts = []
            for block in content:
                if not isinstance(block, dict):
                    dropped["unknown"] += 1
                    continue
                if "cache_control" in block:
                    cache_stripped = True
                btype = block.get("type")
                if btype == "tool_result":
                    t = _transform_tool_result_to_chat_tool(block, tool_use_ids)
                    if t is None:
                        dropped["tool_result"] += 1
                        continue
                    tool_messages.append(t)
                    continue
                if btype == "text":
                    text_parts.append(block.get("text"))
                    continue
                if btype == "image":
                    dropped["image"] += 1
                    continue
                dropped["unknown"] += 1
            out.extend(tool_messages)
            if text_parts:
                text = "\n".join(t for t in text_parts if isinstance(t, str))
                out.append({"role": role, "content": text})
        else:
            out.append({"role": role, "content": content})
    if cache_stripped and cache_stripped_out is not None:
        cache_stripped_out.append("messages")
    if sum(dropped.values()) > 0:
        log_trace({
            "timestamp": _request_transform_timestamp(),
            "event": "content_block_dropped",
            "request_id": request_id,
            "dropped_counts": dropped,
            "location": "message",
            "mode": mode,
            "provider": provider,
            "tier": tier,
        })
    return out


def _transform_tool_result_to_chat_tool(block, known_ids):
    """Convert one Anthropic tool_result block into an OpenAI role:tool message.

    Returns None if the block's tool_use_id is missing/not a string, or does
    not match a tool_use.id from a preceding assistant message (the block is
    dropped). tool_result.content may be a string or a list of text blocks;
    text is extracted and joined with newlines.
    """
    tid = block.get("tool_use_id")
    if not isinstance(tid, str) or not tid or tid not in known_ids:
        return None
    content = block.get("content")
    if isinstance(content, list):
        parts = [c.get("text") for c in content
                 if isinstance(c, dict) and c.get("type") == "text"
                 and isinstance(c.get("text"), str)]
        content = "\n".join(parts)
    if not isinstance(content, str):
        content = ""
    return {"role": "tool", "tool_call_id": tid, "content": content}


def _transform_anthropic_tools_to_chat(tools, request_id=None, mode=None,
                                       provider=None, tier=None,
                                       cache_stripped_out=None):
    """Convert Anthropic tool definitions to OpenAI Chat function tools.

    Returns a new list; tools:null and non-list inputs become []. Entries
    missing name or input_schema are skipped. cache_control_stripped is
    reported to the caller via the optional cache_stripped_out list rather
    than logged here, so _anthropic_to_chat can coalesce one event per request.
    """
    if not isinstance(tools, list):
        return []
    out = []
    cache_stripped = False
    dropped = 0
    for tool in tools:
        if not isinstance(tool, dict):
            dropped += 1
            continue
        name = tool.get("name")
        input_schema = tool.get("input_schema")
        if not isinstance(name, str) or not name or not isinstance(input_schema, dict):
            dropped += 1
            continue
        fn = {"name": name, "parameters": input_schema}
        if isinstance(tool.get("description"), str):
            fn["description"] = tool["description"]
        if "cache_control" in tool:
            cache_stripped = True
        out.append({"type": "function", "function": fn})
    if dropped > 0:
        log_trace({
            "timestamp": _request_transform_timestamp(),
            "event": "content_block_dropped",
            "request_id": request_id,
            "dropped_counts": {"unknown": dropped},
            "location": "tool_definition",
            "mode": mode,
            "provider": provider,
            "tier": tier,
        })
    if cache_stripped and cache_stripped_out is not None:
        cache_stripped_out.append("tools")
    return out


def _transform_anthropic_tool_choice_to_chat(tool_choice):
    """Convert an Anthropic tool_choice to OpenAI tool_choice (None to omit)."""
    if not isinstance(tool_choice, dict):
        return None
    tc_type = tool_choice.get("type")
    if tc_type == "none":
        return "none"
    if tc_type == "auto":
        return "auto"
    if tc_type == "any":
        return "required"
    if tc_type == "tool":
        name = tool_choice.get("name")
        if isinstance(name, str) and name:
            return {"type": "function", "function": {"name": name}}
        return None
    return None


def _map_chat_finish_reason(finish_reason):
    """Map an OpenAI finish_reason to an Anthropic stop_reason (null for no map)."""
    mapping = {"stop": "end_turn", "length": "max_tokens", "tool_calls": "tool_use"}
    if isinstance(finish_reason, str) and finish_reason in mapping:
        return mapping[finish_reason]
    return None


def _chat_to_anthropic(chat_body, tier, request_id=None, mode=None, provider=None):
    """Transform an OpenAI Chat Completions JSON response into Anthropic Messages.

    All field access is guarded with .get()/truthiness defaults; the whole
    body is wrapped so any shape failure passes through unchanged.
    """
    try:
        _id = chat_body.get("id") or str(uuid.uuid4())
        choices = chat_body.get("choices") or []
        usage = chat_body.get("usage") or {}
        result = {
            "id": "msg_" + _id,
            "model": tier,
            "type": "message",
            "role": "assistant",
            "content": [],
            "stop_reason": None,
            "stop_sequence": None,
            "usage": {
                "input_tokens": usage.get("prompt_tokens") or 0,
                "output_tokens": usage.get("completion_tokens") or 0,
            },
        }
        if not choices:
            return result

        choice = choices[0] or {}
        message = choice.get("message") or {}
        content = message.get("content")
        if isinstance(content, str) and content:
            result["content"] = [{"type": "text", "text": content}]
        elif isinstance(content, list):
            result["content"] = [
                {"type": "text", "text": part.get("text")}
                for part in content
                if isinstance(part, dict) and part.get("type") == "text"
                and isinstance(part.get("text"), str)
            ]
        else:
            result["content"] = []

        reasoning = message.get("reasoning_content")
        if not (isinstance(reasoning, str) and reasoning):
            reasoning = message.get("reasoning")
        if isinstance(reasoning, str) and reasoning:
            result["content"].insert(0, {
                "type": "thinking",
                "thinking": reasoning,
                "signature": "",
            })

        tool_calls = message.get("tool_calls")
        if isinstance(tool_calls, list):
            emitted_tool_use = False
            for tc in tool_calls:
                if not isinstance(tc, dict):
                    log_trace({
                        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        "event": "tool_args_parse_failure",
                        "request_id": request_id,
                        "mode": mode,
                        "provider": provider,
                        "tier": tier,
                    })
                    result["content"].append({
                        "type": "text",
                        "text": "[Tool call failed: tool call entry is not a dict (call {})]".format(
                            tc.get("id") if isinstance(tc, dict) else "<unknown>"),
                    })
                    continue
                fn = tc.get("function")
                fn = fn if isinstance(fn, dict) else {}
                args = fn.get("arguments")
                if isinstance(args, dict):
                    parsed_args = args
                elif isinstance(args, str):
                    try:
                        parsed_args = json.loads(args)
                    except json.JSONDecodeError:
                        parsed_args = None
                    if not isinstance(parsed_args, dict):
                        parsed_args = None
                else:
                    parsed_args = None
                if parsed_args is None or parsed_args == {}:
                    log_trace({
                        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        "event": "tool_args_parse_failure",
                        "request_id": request_id,
                        "mode": mode,
                        "provider": provider,
                        "tier": tier,
                    })
                    result["content"].append({
                        "type": "text",
                        "text": "[Tool call failed: arguments for '{}' (call {}) could not be parsed as JSON]".format(
                            fn.get("name") or "<unknown>", tc.get("id") or "<unknown>"),
                    })
                    continue
                result["content"].append({
                    "type": "tool_use",
                    "id": tc.get("id") or str(uuid.uuid4()),
                    "name": fn.get("name") or None,
                    "input": parsed_args,
                })
                emitted_tool_use = True

            if not emitted_tool_use:
                result["stop_reason"] = None
            else:
                result["stop_reason"] = _map_chat_finish_reason(choice.get("finish_reason"))

        if not isinstance(tool_calls, list):
            sr = _map_chat_finish_reason(choice.get("finish_reason"))
            if sr == "tool_use":
                sr = None  # tool_calls null/absent — don't claim tool_use
            result["stop_reason"] = sr
        return result
    except (json.JSONDecodeError, KeyError, TypeError, IndexError, AttributeError):
        log_trace({
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "event": "transform_failure",
            "request_id": request_id,
            "mode": mode,
            "provider": provider,
            "tier": tier,
        })
        return chat_body


def _anthropic_to_response(body_json):
    """Transform an Anthropic Messages request into OpenAI Responses.

    Single-turn only: `input` is the text of the last user message. `stream`
    is forced false — response-mode SSE is not implemented, so the upstream
    must return buffered JSON.
    """
    out = {}
    if "model" in body_json:
        out["model"] = body_json["model"]
    out["stream"] = False

    user_text = ""
    messages = body_json.get("messages")
    if isinstance(messages, list):
        user_msgs = [m for m in messages
                     if isinstance(m, dict) and m.get("role") == "user"]
        if user_msgs:
            content = user_msgs[-1].get("content")
            if isinstance(content, str):
                user_text = content
            elif isinstance(content, list):
                parts = [c.get("text") for c in content
                         if isinstance(c, dict) and c.get("type") == "text"
                         and isinstance(c.get("text"), str)]
                user_text = "\n".join(parts)
    out["input"] = user_text

    system = body_json.get("system")
    system_text = None
    if isinstance(system, str):
        system_text = system
    elif isinstance(system, list):
        parts = [b.get("text") for b in system
                 if isinstance(b, dict) and isinstance(b.get("text"), str)]
        system_text = "\n".join(parts)
    if system_text:
        out["instructions"] = system_text

    if "max_tokens" in body_json:
        out["max_output_tokens"] = body_json["max_tokens"]
    if "temperature" in body_json:
        out["temperature"] = body_json["temperature"]
    if "top_p" in body_json:
        out["top_p"] = body_json["top_p"]
    return out


def _response_to_anthropic(resp_body, tier, request_id=None, mode=None, provider=None):
    """Transform an OpenAI Responses JSON response into Anthropic Messages.

    Same defensive conventions as _chat_to_anthropic: guarded .get() access
    and an outer try/except falling back to the original body.
    """
    try:
        output = resp_body.get("output") or []
        usage = resp_body.get("usage") or {}
        result = {
            "id": resp_body.get("id"),
            "model": tier,
            "type": "message",
            "role": "assistant",
            "content": [],
            "stop_reason": None,
            "stop_sequence": None,
            "usage": {
                "input_tokens": usage.get("input_tokens") or 0,
                "output_tokens": usage.get("output_tokens") or 0,
            },
        }
        if not output:
            return result

        # First message-type output provides the content (the Responses API
        # normally returns a single message output per request).
        for item in output:
            if not isinstance(item, dict) or item.get("type") != "message":
                continue
            for cb in (item.get("content") or []):
                if not isinstance(cb, dict) or cb.get("type") != "output_text":
                    continue
                text = cb.get("text")
                if isinstance(text, str):
                    result["content"].append({"type": "text", "text": text})
            break

        result["stop_reason"] = "end_turn" if resp_body.get("status") == "completed" else None
        return result
    except (json.JSONDecodeError, KeyError, TypeError, IndexError, AttributeError):
        log_trace({
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "event": "transform_failure",
            "request_id": request_id,
            "mode": mode,
            "provider": provider,
            "tier": tier,
        })
        return resp_body


# ---------------------------------------------------------------------------
# HTTP request handler
# ---------------------------------------------------------------------------

def _crlf_safe(headers):
    """Drop headers whose name or value contains CR/LF (response-splitting guard).

    A header name or value carrying a raw newline would let an upstream-injected
    value reach the client's parser as a different header set than the proxy
    parsed (parser-differential attack; cf. CVE-2019-9740/CVE-2019-9947). Omit
    such entries rather than forwarding them.
    """
    if not headers:
        return {}
    return {k: v for k, v in headers.items()
            if "\r" not in k and "\n" not in k
            and "\r" not in str(v) and "\n" not in str(v)}


class ProxyHandler(http.server.BaseHTTPRequestHandler):

    def _send_response(self, status, body_bytes, headers=None):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        if headers:
            for k, v in _crlf_safe(headers).items():
                if k.lower() not in {"content-type", "transfer-encoding",
                                     "content-length", "connection"}:
                    self.send_header(k, v)
        self.send_header("Content-Length", str(len(body_bytes)))
        self.end_headers()
        self.wfile.write(body_bytes)

    def _stream_upstream_response(self, resp, status, resp_headers, request_id, retries,
                                   tier=None, mode=None):
        """Stream an upstream 2xx response body to the client as it arrives.

        For SSE (text/event-stream):
          - anthropic mode: buffers first event (64KB cap), rewrites model in
            message_start event to tier name. Subsequent events forwarded
            unchanged.
          - chat mode: transforms the OpenAI chat-completions SSE stream into
            synthetic Anthropic Messages SSE events.
          - response mode: upstream SSE is unexpected (the request transform
            forces stream:false); handled by a defensive terminal-only fallback.

        For other content types: streams unchanged.

        Returns the first-byte latency in ms, or None if aborted.
        """
        first_byte_start = time.time()
        first_byte_ms = None
        first_chunk = True
        bytes_streamed = 0

        # Check Content-Type to determine rewriting strategy
        content_type = resp_headers.get("Content-Type", "").lower()
        is_sse = "text/event-stream" in content_type

        try:
            self.send_response(status)
            # Forward all other headers verbatim, including content-type
            # (required for text/event-stream SSE responses). Drop hop-by-hop
            # headers — http.client already de-chunked the upstream body, and
            # the response is close-delimited via HTTP/1.0.
            for k, v in _crlf_safe(resp_headers).items():
                if k.lower() not in {"transfer-encoding", "content-length",
                                     "connection"}:
                    self.send_header(k, v)
            self.end_headers()

            if is_sse and tier:
                if mode == "chat":
                    return self._stream_chat_sse_to_anthropic(
                        resp, request_id, tier, first_byte_start)
                if mode == "response":
                    return self._stream_response_sse_fallback(
                        resp, request_id, tier, first_byte_start)
                # SSE path (anthropic mode): buffer first event for model
                # rewriting. Buffer chunks until \n\n delimiter is found or
                # 64KB cap is exceeded.
                first_event_buffer = bytearray()
                MAX_FIRST_EVENT_BUFFER = 64 * 1024  # 64 KB cap
                first_event_found = False
                rewrite_skipped = False

                while not first_event_found:
                    try:
                        chunk = resp.read1(8192)
                    except (http.client.IncompleteRead, http.client.RemoteDisconnected,
                            socket.error, OSError):
                        break
                    if not chunk:
                        break
                    first_event_buffer.extend(chunk)

                    # Check for event delimiter
                    if b"\n\n" in first_event_buffer:
                        first_event_found = True
                    elif len(first_event_buffer) > MAX_FIRST_EVENT_BUFFER:
                        # Buffer exceeded cap - forward as-is without rewriting
                        rewrite_skipped = True
                        first_event_found = True
                        log_trace({
                            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                            "event": "sse_buffer_cap_exceeded",
                            "request_id": request_id,
                        })

                if first_event_buffer:
                    # Split buffer at first \n\n to isolate first event
                    delimiter_idx = first_event_buffer.find(b"\n\n")
                    if delimiter_idx >= 0:
                        # Extract first event (including \n\n)
                        first_event_bytes = bytes(first_event_buffer[:delimiter_idx + 2])
                        # Remainder is everything after the first \n\n
                        remainder = bytes(first_event_buffer[delimiter_idx + 2:])
                    else:
                        # No delimiter found (buffer exceeded cap)
                        first_event_bytes = bytes(first_event_buffer)
                        remainder = b""

                    if not rewrite_skipped:
                        # Try to rewrite model in first event only
                        first_event_bytes = _rewrite_sse_first_event(
                            first_event_bytes, tier, request_id)

                    # Write rewritten first event
                    self.wfile.write(first_event_bytes)
                    self.wfile.flush()
                    bytes_streamed += len(first_event_bytes)
                    # Write remainder (may contain additional events from the same chunk)
                    if remainder:
                        self.wfile.write(remainder)
                        self.wfile.flush()
                        bytes_streamed += len(remainder)
                    first_byte_ms = (time.time() - first_byte_start) * 1000
                    first_chunk = False

                # Stream remaining events unchanged
                while True:
                    try:
                        chunk = resp.read1(8192)
                    except (http.client.IncompleteRead, http.client.RemoteDisconnected,
                            socket.error, OSError):
                        break
                    if not chunk:
                        break
                    bytes_streamed += len(chunk)
                    if bytes_streamed > PROXY_MAX_RESPONSE_SIZE:
                        log_trace({
                            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                            "event": "response_size_cap_exceeded",
                            "request_id": request_id,
                            "bytes_streamed": bytes_streamed,
                            "limit": PROXY_MAX_RESPONSE_SIZE,
                        })
                        print("[proxy] Response size limit exceeded ({} bytes)".format(
                            bytes_streamed), file=sys.stderr)
                        break
                    self.wfile.write(chunk)
                    self.wfile.flush()
            else:
                # Non-SSE path: stream unchanged
                while True:
                    try:
                        chunk = resp.read1(8192)
                    except (http.client.IncompleteRead, http.client.RemoteDisconnected,
                            socket.error, OSError):
                        break
                    if not chunk:
                        break
                    bytes_streamed += len(chunk)
                    if bytes_streamed > PROXY_MAX_RESPONSE_SIZE:
                        log_trace({
                            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                            "event": "response_size_cap_exceeded",
                            "request_id": request_id,
                            "bytes_streamed": bytes_streamed,
                            "limit": PROXY_MAX_RESPONSE_SIZE,
                        })
                        print("[proxy] Response size limit exceeded ({} bytes)".format(
                            bytes_streamed), file=sys.stderr)
                        break
                    self.wfile.write(chunk)
                    self.wfile.flush()
                    if first_chunk:
                        first_byte_ms = (time.time() - first_byte_start) * 1000
                        first_chunk = False

        except _DISCONNECT_ERRORS:
            self._log_client_disconnect(request_id, status, retries)
            return None
        return first_byte_ms

    def _sse_event(self, payload):
        """Serialize one SSE frame — `event: <type>` + `data: <json>` lines.

        The Anthropic SDKs dispatch streaming events on the SSE `event:` field
        against a hardcoded whitelist; a data-only frame arrives with
        event=None and is silently dropped. The type is taken from
        payload["type"], and provider-controlled bytes only ever flow through
        json.dumps (SSE injection guard).
        """
        etype = payload.get("type")
        if not isinstance(etype, str) or not etype:
            etype = "message"
        return ("event: " + etype + "\n"
                "data: " + json.dumps(payload) + "\n\n").encode("utf-8")

    def _stream_chat_sse_to_anthropic(self, resp, request_id, tier, first_byte_start):
        """Transform an OpenAI chat-completions SSE stream into Anthropic Messages SSE.

        Frames are assembled on the \\n\\n delimiter (CRLF-normalized) — never
        split mid-frame. A synthetic message_start opens the stream; the first
        content_block_start is deferred until the first delta's type is known
        (reasoning_content/reasoning deltas open a thinking block at index 0,
        content deltas a text block). Deltas become content_block_delta, and
        terminal events (content_block_stop, message_delta, message_stop) are
        emitted exactly once — on the finish_reason chunk, or synthesized at
        EOF/truncation so the Anthropic client never hangs. [DONE] and
        non-data frames are skipped.

        OpenAI delta.tool_calls are converted into Anthropic tool_use content
        blocks: per-upstream-index state buffers argument fragments until valid
        id+name metadata exists, and all Anthropic block indices come from the
        shared monotonic allocator (incremented only on content_block_start,
        never on close, so indices stay contiguous). A normal "tool_calls"
        finish closes open tool blocks in ascending index order and claims
        stop_reason "tool_use" only when a parseable tool block was emitted; all
        malformed/dropped variants degrade to a null stop reason that are
        reported via one bounded metadata-only trace event per stream.
        """
        MAX_EVENT_BUFFER = 64 * 1024
        buf = bytearray()
        usage = {}
        chat_id = None
        message_started = False
        first_frame = True
        tool_calls_seen = False
        emitted_tool_use = False
        bytes_streamed = 0
        first_byte_ms = None
        block_index = 0
        current_block_type = None
        current_block_index = None
        open_blocks = []
        tool_states = {}
        tools_started = 0
        malformed_tool_count = 0
        overflow_tool_count = 0
        dropped_fragment_count = 0
        unparseable_arg_count = 0
        scalar_after_tools_dropped = 0
        frame_dropped = False
        degradation_logged = False

        def write(payload):
            nonlocal bytes_streamed, first_byte_ms
            data = self._sse_event(payload)
            self.wfile.write(data)
            self.wfile.flush()
            bytes_streamed += len(data)
            if first_byte_ms is None:
                first_byte_ms = (time.time() - first_byte_start) * 1000

        def start_message():
            nonlocal message_started
            if message_started:
                return
            mid = ("msg_" + chat_id) if chat_id else ("msg_" + str(uuid.uuid4()))
            write({
                "type": "message_start",
                "message": {
                    "id": mid,
                    "type": "message",
                    "role": "assistant",
                    "content": [],
                    "model": tier,
                    "stop_reason": None,
                    "stop_sequence": None,
                    "usage": {"input_tokens": 0, "output_tokens": 0},
                },
            })
            message_started = True

        def alloc_index():
            nonlocal block_index
            idx = block_index
            block_index += 1
            return idx

        def close_scalar_block():
            nonlocal current_block_type, current_block_index
            if current_block_type is not None:
                write({"type": "content_block_stop", "index": open_blocks[-1]})
                open_blocks.pop()
                current_block_type = None
                current_block_index = None

        def open_text_block():
            nonlocal current_block_type, current_block_index
            if current_block_type == "text":
                return
            close_scalar_block()
            idx = alloc_index()
            write({
                "type": "content_block_start",
                "index": idx,
                "content_block": {"type": "text", "text": ""},
            })
            open_blocks.append(idx)
            current_block_type = "text"
            current_block_index = idx

        def open_thinking_block():
            nonlocal current_block_type, current_block_index
            if current_block_type == "thinking":
                return
            close_scalar_block()
            idx = alloc_index()
            write({
                "type": "content_block_start",
                "index": idx,
                "content_block": {"type": "thinking", "thinking": "",
                                  "signature": ""},
            })
            open_blocks.append(idx)
            current_block_type = "thinking"
            current_block_index = idx

        def new_tool_state():
            return {
                "id": None,
                "name": None,
                "index": None,
                "started": False,
                "closed": False,
                "dropped": False,
                "pending": [],
                "pending_bytes": 0,
                "arg_parts": [],
            }

        def start_tool_block(state):
            nonlocal tools_started, emitted_tool_use
            if tools_started >= MAX_CHAT_OPEN_TOOL_BLOCKS:
                return False
            close_scalar_block()
            idx = alloc_index()
            write({
                "type": "content_block_start",
                "index": idx,
                "content_block": {"type": "tool_use",
                                  "id": state["id"],
                                  "name": state["name"],
                                  "input": {}},
            })
            state["index"] = idx
            state["started"] = True
            tools_started += 1
            emitted_tool_use = True
            for frag in state["pending"]:
                write({"type": "content_block_delta", "index": idx,
                       "delta": {"type": "input_json_delta",
                                 "partial_json": frag}})
                state["arg_parts"].append(frag)
            state["pending"] = []
            state["pending_bytes"] = 0
            return True

        def close_open_tool_blocks(validate):
            nonlocal unparseable_arg_count
            candidates = [st for st in tool_states.values()
                          if st["started"] and not st["closed"]]
            valid = 0
            for st in sorted(candidates, key=lambda s: s["index"]):
                write({"type": "content_block_stop", "index": st["index"]})
                st["closed"] = True
                if validate and not st["dropped"]:
                    try:
                        parsed = json.loads("".join(st["arg_parts"]))
                    except ValueError:
                        unparseable_arg_count += 1
                        continue
                    if not isinstance(parsed, dict):
                        unparseable_arg_count += 1
                        continue
                    valid += 1
            return valid

        def log_tool_degradation_summary():
            nonlocal degradation_logged
            if degradation_logged:
                return
            degradation_logged = True
            log_trace({
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "event": "chat_sse_tool_degradation",
                "request_id": request_id,
                "malformed_tool_count": malformed_tool_count,
                "overflow_tool_count": overflow_tool_count,
                "dropped_fragment_count": dropped_fragment_count,
                "unparseable_arg_count": unparseable_arg_count,
                "scalar_after_tools_dropped": scalar_after_tools_dropped,
                "frame_dropped": 1 if frame_dropped else 0,
            })

        def process_tool_calls(tool_calls):
            nonlocal malformed_tool_count, overflow_tool_count, dropped_fragment_count
            if not isinstance(tool_calls, list):
                malformed_tool_count += 1
                return
            for tc in tool_calls:
                if not isinstance(tc, dict):
                    malformed_tool_count += 1
                    continue
                index = tc.get("index")
                if not isinstance(index, int) or isinstance(index, bool):
                    # Missing index: a non-empty argument fragment cannot be
                    # associated with any tool — counted as a dropped fragment so
                    # the stream never claims tool_use; other entries are malformed.
                    fn0 = tc.get("function")
                    args0 = fn0.get("arguments") if isinstance(fn0, dict) else None
                    if isinstance(args0, str) and args0:
                        dropped_fragment_count += 1
                    else:
                        malformed_tool_count += 1
                    continue
                fn = tc.get("function")
                if fn is not None and not isinstance(fn, dict):
                    malformed_tool_count += 1
                    continue
                fn = fn if isinstance(fn, dict) else {}
                state = tool_states.get(index)
                if state is None:
                    if len(tool_states) >= MAX_CHAT_TRACKED_TOOL_INDEXES:
                        overflow_tool_count += 1
                        continue
                    state = new_tool_state()
                    tool_states[index] = state
                if state["dropped"]:
                    continue
                id_ = tc.get("id")
                name_ = fn.get("name")
                if isinstance(id_, str) and id_:
                    if state["id"] is not None and state["id"] != id_:
                        malformed_tool_count += 1
                        state["dropped"] = True
                        state["pending"] = []
                        state["pending_bytes"] = 0
                        continue
                    state["id"] = id_
                if isinstance(name_, str) and name_:
                    if state["name"] is not None and state["name"] != name_:
                        malformed_tool_count += 1
                        state["dropped"] = True
                        state["pending"] = []
                        state["pending_bytes"] = 0
                        continue
                    state["name"] = name_
                args = fn.get("arguments")
                if args is not None and not isinstance(args, str):
                    malformed_tool_count += 1
                    state["dropped"] = True
                    state["pending"] = []
                    state["pending_bytes"] = 0
                    continue
                if not state["started"] and state["id"] and state["name"] \
                        and not state["dropped"]:
                    if not start_tool_block(state):
                        overflow_tool_count += 1
                        state["dropped"] = True
                        state["pending"] = []
                        state["pending_bytes"] = 0
                        continue
                if isinstance(args, str) and args:
                    if state["started"]:
                        state["arg_parts"].append(args)
                        write({
                            "type": "content_block_delta",
                            "index": state["index"],
                            "delta": {"type": "input_json_delta",
                                      "partial_json": args},
                        })
                    else:
                        if state["pending_bytes"] + len(args.encode("utf-8")) \
                                > MAX_CHAT_TOOL_PENDING_BYTES:
                            malformed_tool_count += 1
                            state["dropped"] = True
                            state["pending"] = []
                            state["pending_bytes"] = 0
                            continue
                        state["pending"].append(args)
                        state["pending_bytes"] += len(args.encode("utf-8"))

        def terminal(stop_reason, force_log=False):
            nonlocal malformed_tool_count
            while open_blocks:
                idx = open_blocks.pop()
                write({"type": "content_block_stop", "index": idx})
            close_open_tool_blocks(validate=False)
            # Any tracked tool whose metadata never produced a start is
            # incomplete — count it so the coalesced diagnostic fires.
            for st in tool_states.values():
                if not st["started"] and not st["dropped"]:
                    malformed_tool_count += 1
                    st["dropped"] = True
            delta_usage = {"input_tokens": 0, "output_tokens": 0}
            if usage.get("prompt_tokens") is not None:
                delta_usage["input_tokens"] = usage.get("prompt_tokens")
            if usage.get("completion_tokens") is not None:
                delta_usage["output_tokens"] = usage.get("completion_tokens")
            write({
                "type": "message_delta",
                "delta": {"stop_reason": stop_reason, "stop_sequence": None},
                "usage": delta_usage,
            })
            write({"type": "message_stop"})
            if force_log or malformed_tool_count or overflow_tool_count \
                    or dropped_fragment_count or unparseable_arg_count \
                    or scalar_after_tools_dropped or frame_dropped:
                log_tool_degradation_summary()

        def handle_frame(frame):
            nonlocal chat_id, usage, first_frame, tool_calls_seen, scalar_after_tools_dropped, malformed_tool_count
            text = frame.decode("utf-8", errors="replace")
            data_lines = [ln[5:].strip() for ln in text.splitlines()
                          if ln.startswith("data:")]
            if not data_lines:
                return None  # comment/event-only frame — skip silently
            raw = "\n".join(data_lines).strip()
            if raw == "[DONE]":
                return "done"
            try:
                chunk = json.loads(raw)
            except json.JSONDecodeError:
                log_trace({
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "event": "chat_sse_malformed_json",
                    "request_id": request_id,
                })
                return None
            if not isinstance(chunk, dict):
                return None
            u = chunk.get("usage")
            if isinstance(u, dict):
                usage = u
            choices = chunk.get("choices") or []
            if not choices:
                return None
            choice = choices[0] or {}
            delta = choice.get("delta") or {}
            if first_frame:
                first_frame = False
                cid = chunk.get("id")
                if isinstance(cid, str) and cid:
                    chat_id = cid
                start_message()
            if isinstance(delta, dict):
                if delta.get("tool_calls"):
                    tool_calls_seen = True
                reasoning = delta.get("reasoning_content")
                if not (isinstance(reasoning, str) and reasoning):
                    reasoning = delta.get("reasoning")
                if isinstance(reasoning, str) and reasoning:
                    if emitted_tool_use:
                        scalar_after_tools_dropped += 1
                    else:
                        if current_block_type != "thinking":
                            open_thinking_block()
                        write({
                            "type": "content_block_delta",
                            "index": current_block_index,
                            "delta": {"type": "thinking_delta", "thinking": reasoning},
                        })
                content = delta.get("content")
                if isinstance(content, str) and content:
                    if emitted_tool_use:
                        scalar_after_tools_dropped += 1
                    else:
                        if current_block_type != "text":
                            open_text_block()
                        write({
                            "type": "content_block_delta",
                            "index": current_block_index,
                            "delta": {"type": "text_delta", "text": content},
                        })
                tool_calls = delta.get("tool_calls")
                if tool_calls is not None:
                    process_tool_calls(tool_calls)
            elif delta:
                # Non-dict delta shape (e.g. a string or list): cannot be a
                # valid tool-call frame — the frame is skipped and counted in
                # the degradation diagnostics rather than raising mid-stream.
                malformed_tool_count += 1
            finish_reason = choice.get("finish_reason")
            if finish_reason is not None:
                return ("finish", finish_reason)
            return None

        try:
            while True:
                try:
                    chunk = resp.read1(8192)
                except (http.client.IncompleteRead, http.client.RemoteDisconnected,
                        socket.error, OSError):
                    break
                if not chunk:
                    break
                if first_byte_ms is None:
                    first_byte_ms = (time.time() - first_byte_start) * 1000
                # Degraded mode (first-frame cap exceeded): forward raw bytes
                if buf is None:
                    bytes_streamed += len(chunk)
                    if bytes_streamed > PROXY_MAX_RESPONSE_SIZE:
                        self._log_response_cap_exceeded(request_id, bytes_streamed)
                        break
                    self.wfile.write(chunk)
                    self.wfile.flush()
                    continue
                chunk = chunk.replace(b"\r\n", b"\n")
                buf.extend(chunk)
                while True:
                    idx = buf.find(SSE_EVENT_DELIMITER)
                    if idx < 0:
                        break
                    frame = bytes(buf[:idx])
                    del buf[:idx + 2]
                    result = handle_frame(frame)
                    if result == "done":
                        continue
                    if isinstance(result, tuple) and result[0] == "finish":
                        finish_reason = result[1]
                        if finish_reason == "tool_calls":
                            valid = close_open_tool_blocks(validate=True)
                            if (valid > 0 and dropped_fragment_count == 0
                                    and overflow_tool_count == 0
                                    and unparseable_arg_count == 0
                                    and not (frame_dropped and emitted_tool_use)):
                                sr = "tool_use"
                            else:
                                sr = None
                            terminal(sr)
                        elif emitted_tool_use:
                            close_open_tool_blocks(validate=False)
                            terminal(_map_chat_finish_reason(finish_reason),
                                     force_log=True)
                        else:
                            terminal(_map_chat_finish_reason(finish_reason))
                        return first_byte_ms
                # Memory guards for frames without a delimiter
                if len(buf) > MAX_EVENT_BUFFER:
                    if not message_started:
                        # First event exceeded cap before \\n\\n: degrade to
                        # raw passthrough with a synthetic start (accepted
                        # residual for the chat-mode 64KB-cap edge case).
                        log_trace({
                            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                            "event": "chat_sse_buffer_cap_exceeded",
                            "request_id": request_id,
                        })
                        start_message()
                        raw_splice = bytes(buf)
                        buf.clear()
                        bytes_streamed += len(raw_splice)
                        self.wfile.write(raw_splice)
                        self.wfile.flush()
                        first_byte_ms = (time.time() - first_byte_start) * 1000
                        buf = None  # switch to raw forwarding
                    else:
                        log_trace({
                            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                            "event": "chat_sse_frame_cap_exceeded",
                            "request_id": request_id,
                            "bytes": len(buf),
                        })
                        frame_dropped = True
                        buf.clear()
                if bytes_streamed > PROXY_MAX_RESPONSE_SIZE:
                    self._log_response_cap_exceeded(request_id, bytes_streamed)
                    break
        except _DISCONNECT_ERRORS:
            raise
        # EOF reached without a finish_reason chunk: synthesize a clean
        # terminal sequence so the client stream never hangs.
        if not message_started:
            start_message()
        log_trace({
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "event": "chat_sse_truncated",
            "request_id": request_id,
            "pending_bytes": len(buf) if isinstance(buf, bytearray) else 0,
        })
        sr = "end_turn"
        if tool_calls_seen:
            sr = None
        terminal(sr)
        return first_byte_ms

    def _stream_response_sse_fallback(self, resp, request_id, tier, first_byte_start):
        """Handle unexpected Responses-mode upstream SSE defensively.

        The request transform forces stream:false, so SSE here means a provider
        ignored the flag. Drain the unexpected stream and synthesize a clean,
        empty Anthropic terminal sequence instead of leaking raw OpenAI SSE.
        """
        first_byte_ms = None
        try:
            log_trace({
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "event": "response_sse_unexpected",
                "request_id": request_id,
            })
            try:
                while resp.read1(8192):
                    pass
            except (http.client.IncompleteRead, http.client.RemoteDisconnected,
                    socket.error, OSError):
                pass
            mid = "msg_" + str(uuid.uuid4())
            events = [
                {"type": "message_start",
                 "message": {"id": mid, "type": "message", "role": "assistant",
                             "content": [], "model": tier, "stop_reason": None,
                             "stop_sequence": None,
                             "usage": {"input_tokens": 0, "output_tokens": 0}}},
                {"type": "content_block_start", "index": 0,
                 "content_block": {"type": "text", "text": ""}},
                {"type": "content_block_stop", "index": 0},
                {"type": "message_delta",
                 "delta": {"stop_reason": None, "stop_sequence": None},
                 "usage": {"input_tokens": 0, "output_tokens": 0}},
                {"type": "message_stop"},
            ]
            for ev in events:
                self.wfile.write(self._sse_event(ev))
            self.wfile.flush()
            first_byte_ms = (time.time() - first_byte_start) * 1000
        except _DISCONNECT_ERRORS:
            return None
        return first_byte_ms

    def _log_response_cap_exceeded(self, request_id, bytes_streamed):
        log_trace({
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "event": "response_size_cap_exceeded",
            "request_id": request_id,
            "bytes_streamed": bytes_streamed,
            "limit": PROXY_MAX_RESPONSE_SIZE,
        })
        print("[proxy] Response size limit exceeded ({} bytes)".format(
            bytes_streamed), file=sys.stderr)

    def _log_client_disconnect(self, request_id, status, retries):
        """Record a client_disconnect event; suppress the traceback.

        Must never raise: it runs from an except handler, so a secondary
        failure here would re-raise and defeat the fix. stderr print is
        primary; trace event is best-effort.
        """
        try:
            print("[proxy] client disconnected mid-response "
                  "(request_id={}, status={}, retries={})".format(
                      request_id, status, retries), file=sys.stderr)
        except Exception:
            pass
        try:
            log_trace({
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "event": "client_disconnect",
                "request_id": request_id,
                "http_status": status,
                "retries": retries,
            })
        except Exception:
            pass

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Allow", "POST, OPTIONS")
        self.end_headers()

    def do_GET(self):
        # Admin page
        if self.path == "/admin/" or self.path == "/admin":
            # localhost-only check
            if self.client_address[0] not in ("127.0.0.1", "::1"):
                self.send_response(403)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"error":"forbidden"}')
                return

            try:
                html = _load_admin_html()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(html.encode("utf-8"))))
                self.end_headers()
                self.wfile.write(html.encode("utf-8"))
            except Exception as e:
                self._send_response(500, json.dumps({"error": str(e)}).encode("utf-8"))
            return

        # Admin API: get config
        if self.path == "/admin/api/config":
            # localhost-only check
            if self.client_address[0] not in ("127.0.0.1", "::1"):
                self.send_response(403)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"error":"forbidden"}')
                return

            with _config_lock:
                config_copy = json.loads(json.dumps(_current_config))
            self._send_response(200, json.dumps(config_copy).encode("utf-8"))
            return

        # Admin API: get providers list
        if self.path == "/admin/api/providers":
            # localhost-only check
            if self.client_address[0] not in ("127.0.0.1", "::1"):
                self.send_response(403)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"error":"forbidden"}')
                return

            providers = list(_vendors.keys()) if _vendors else []
            self._send_response(200, json.dumps({"providers": providers}).encode("utf-8"))
            return

        # Admin API: get per-provider mode detail (mode only — never url/key)
        if self.path == "/admin/api/providers-detail":
            # localhost-only check
            if self.client_address[0] not in ("127.0.0.1", "::1"):
                self.send_response(403)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"error":"forbidden"}')
                return

            providers_detail = {}
            for name, vendor in (_vendors or {}).items():
                mode = vendor.get("mode")
                if mode not in MODE_VALUES:
                    mode = "anthropic"
                providers_detail[name] = {"mode": mode}
            self._send_response(200, json.dumps({
                "providers": providers_detail
            }).encode("utf-8"))
            return

        # Default: 404
        self._send_response(404, b'{"error":"not found"}')

    def do_POST(self):
        global _current_config

        # Admin shutdown — localhost-only, graceful shutdown via server.shutdown()
        if self.path == "/admin/shutdown":
            # localhost-only check
            if self.client_address[0] not in ("127.0.0.1", "::1"):
                self.send_response(403)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"error":"forbidden"}')
                return

            # CSRF check
            if not _validate_csrf_origin(self, PROXY_PORT):
                self._send_response(403, b'{"error":"forbidden: invalid Origin"}')
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

        # Admin API: switch tiers
        if self.path == "/admin/api/switch":
            # localhost-only check
            if self.client_address[0] not in ("127.0.0.1", "::1"):
                self.send_response(403)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"error":"forbidden"}')
                return

            # CSRF check
            if not _validate_csrf_origin(self, PROXY_PORT):
                self._send_response(403, b'{"error":"forbidden: invalid Origin"}')
                return

            # Read and validate body size
            try:
                content_length = int(self.headers.get("Content-Length", 0))
            except (ValueError, TypeError):
                self._send_response(400, b'{"error":"invalid Content-Length"}')
                return
            if content_length > ADMIN_BODY_LIMIT:
                self._send_response(413, b'{"error":"request body too large"}')
                return

            body = self.rfile.read(content_length) if content_length > 0 else b""
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                self._send_response(400, b'{"error":"invalid JSON"}')
                return

            # Validate all 3 tiers present
            new_tiers = data.get("tiers", {})
            required_tiers = {"haiku", "sonnet", "opus"}
            missing = required_tiers - set(new_tiers.keys())
            if missing:
                self._send_response(400, json.dumps({
                    "error": "missing tiers: {}".format(", ".join(sorted(missing)))
                }).encode("utf-8"))
                return

            # Validate provider names and model names
            for tier_name, tier_config in new_tiers.items():
                if not isinstance(tier_config, dict):
                    self._send_response(400, json.dumps({
                        "error": "tier '{}' must be an object".format(tier_name)
                    }).encode("utf-8"))
                    return
                provider = tier_config.get("provider", "")
                model = tier_config.get("model", "")
                if not _validate_admin_name(provider):
                    self._send_response(400, json.dumps({
                        "error": "invalid provider name: {}".format(provider)
                    }).encode("utf-8"))
                    return
                if not _validate_admin_name(model):
                    self._send_response(400, json.dumps({
                        "error": "invalid model name: {}".format(model)
                    }).encode("utf-8"))
                    return

            # Validate providers exist
            provider_names = set(_vendors.keys())
            for tier_name, tier_config in new_tiers.items():
                provider = tier_config.get("provider", "")
                if provider not in provider_names:
                    self._send_response(400, json.dumps({
                        "error": "unknown provider: {}".format(provider)
                    }).encode("utf-8"))
                    return

            # Drain-and-swap: wait for in-flight requests to complete before swapping
            response_status = None
            response_body = None

            # Phase 1: Set swap flag and wait for drain
            with _config_lock:
                _config_swapping = True
                _swap_done.clear()

            # Phase 2: Wait for in-flight requests to drain (with timeout)
            drain_timeout = 30.0  # seconds
            drain_start = time.time()
            while True:
                with _config_lock:
                    if _inflight_count == 0:
                        break
                if time.time() - drain_start > drain_timeout:
                    # Timeout - abort swap
                    with _config_lock:
                        _config_swapping = False
                        _swap_done.set()
                    self._send_response(503, b'{"error":"config swap timeout: requests still in-flight"}')
                    return
                time.sleep(0.1)

            # Phase 3: Perform the swap
            try:
                with _config_lock:
                    # Preserve models section, replace tiers
                    new_config = {
                        "tiers": new_tiers,
                        "models": _current_config.get("models", {})
                    }
                    # Preserve known top-level config keys across hot-switches
                    for _key in ("disable_retry_claude_count_token",):
                        if _key in _current_config:
                            new_config[_key] = _current_config[_key]
                    if response_status is None:
                        # Write to disk FIRST, then update in-memory
                        try:
                            write_config(_config_path, new_config)
                            # Only update in-memory after successful disk write
                            _current_config = new_config
                            response_status = 200
                            response_body = json.dumps({"status": "ok"}).encode("utf-8")
                        except OSError as e:
                            response_status = 500
                            response_body = json.dumps({
                                "error": "failed to write config: {}".format(e)
                            }).encode("utf-8")
            finally:
                # Phase 4: Clear swap flag and signal completion
                with _config_lock:
                    _config_swapping = False
                    _swap_done.set()

            # Send response after releasing lock
            self._send_response(response_status, response_body)
            return

        # Admin API: reload config from disk
        if self.path == "/admin/api/reload":
            # localhost-only check
            if self.client_address[0] not in ("127.0.0.1", "::1"):
                self.send_response(403)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"error":"forbidden"}')
                return

            # CSRF check
            if not _validate_csrf_origin(self, PROXY_PORT):
                self._send_response(403, b'{"error":"forbidden: invalid Origin"}')
                return

            # Reload config from disk
            try:
                new_config = load_config(_config_path)
            except (FileNotFoundError, json.JSONDecodeError, ValueError) as e:
                self._send_response(400, json.dumps({
                    "error": "failed to load config: {}".format(e)
                }).encode("utf-8"))
                return

            # Validate against providers
            provider_names = set(_vendors.keys())
            errors = validate_config(new_config, provider_names)
            if errors:
                self._send_response(400, json.dumps({
                    "error": "config validation failed: {}".format("; ".join(errors))
                }).encode("utf-8"))
                return

            # Drain-and-swap: wait for in-flight requests to complete before swapping
            # Phase 1: Set swap flag and wait for drain
            with _config_lock:
                _config_swapping = True
                _swap_done.clear()

            # Phase 2: Wait for in-flight requests to drain (with timeout)
            drain_timeout = 30.0  # seconds
            drain_start = time.time()
            while True:
                with _config_lock:
                    if _inflight_count == 0:
                        break
                if time.time() - drain_start > drain_timeout:
                    # Timeout - abort swap
                    with _config_lock:
                        _config_swapping = False
                        _swap_done.set()
                    self._send_response(503, b'{"error":"config swap timeout: requests still in-flight"}')
                    return
                time.sleep(0.1)

            # Phase 3: Perform the swap
            try:
                with _config_lock:
                    _current_config = new_config
            finally:
                # Phase 4: Clear swap flag and signal completion
                with _config_lock:
                    _config_swapping = False
                    _swap_done.set()

            self._send_response(200, json.dumps({
                "status": "ok",
                "config": new_config
            }).encode("utf-8"))
            return

        request_id = str(uuid.uuid4())

        # Read request body
        try:
            content_length = int(self.headers.get("Content-Length", 0))
        except (ValueError, TypeError):
            self._send_response(400, b'{"error":"invalid Content-Length"}')
            return
        if content_length > PROXY_MAX_BODY_SIZE:
            try:
                self._send_response(413,
                    b'{"error":"Payload too large"}')
            except _DISCONNECT_ERRORS:
                self._log_client_disconnect(request_id, 413, 0)
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

        status, resp_headers, resp_body, first_byte_ms, total_sec, retries, tier, provider, actual_model = \
            forward_request(self.command, self.path,
                            {k: v for k, v in self.headers.items()},
                            body, handler=self, request_id=request_id)

        # Mirrors forward_request's streaming branch: streaming paths return
        # resp_body=b"" (already sent to client), buffering paths return the
        # actual body (needs _send_response). Check both status and body.
        streamed = (200 <= status < 300) and (resp_body == b"")

        # Build trace entry
        success = 200 <= status < 300
        trace_entry = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "event": "request",
            "request_id": request_id,
            "method": self.command,
            "path": self.path,
            "model": actual_model or model,
            "tier": tier,
            "provider": provider,
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
            if not streamed:
                # Streamed 2xx bodies were consumed by the client in real time
                # and are not captured — a deliberate reduction in data-at-rest
                # exposure under --all.
                try:
                    trace_entry["response_body"] = json.loads(resp_body.decode("utf-8"))
                except Exception:
                    trace_entry["response_body"] = resp_body.decode("utf-8", errors="replace") if resp_body else None

        log_trace(trace_entry)

        if not streamed:
            try:
                self._send_response(status, resp_body, resp_headers)
            except _DISCONNECT_ERRORS:
                # Client disconnected mid-response (timed out, cancelled, etc.).
                # The request already completed upstream and is traced above;
                # record a delivery-failure event and avoid a traceback.
                self._log_client_disconnect(request_id, status, retries)

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
    parser.add_argument("--config-path", type=str, default=None,
                        help="Path to config.json (default: ~/.claude/proxy/config.json)")
    parser.add_argument("--keys-path", type=str, default=None,
                        help="Path to encrypted keys-index.json (default: ~/.claude/keys-index.json)")
    parser.add_argument("--passphrase-file", type=str, default=None,
                        help="Read passphrase from file instead of stdin")
    args = parser.parse_args()

    global PROXY_PORT, PROXY_TRACE_FILE, PROXY_LOG_ALL
    global _current_config, _vendors, _config_path, _startup_state

    if args.port is not None:
        PROXY_PORT = args.port
    if args.log is not None:
        if not os.path.isabs(args.log):
            args.log = os.path.join(os.getcwd(), args.log)
        PROXY_TRACE_FILE = args.log
    if getattr(args, "all"):
        PROXY_LOG_ALL = True

    # Resolve paths
    config_path = args.config_path or DEFAULT_CONFIG_PATH
    keys_path = args.keys_path or PROXY_KEYS_PATH

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
        _vendors = load_keys_file(keys_path, passphrase)
    except ValueError as e:
        print("[proxy] ERROR: Key decryption failed: {}".format(e), file=sys.stderr)
        sys.exit(1)

    # Load and validate config
    try:
        _current_config = load_config(config_path)
        _config_path = config_path
    except FileNotFoundError:
        print("[proxy] ERROR: Config file not found: {}".format(config_path), file=sys.stderr)
        print("[proxy] Run 'claude-retry-proxy start' to create from template", file=sys.stderr)
        sys.exit(1)
    except (json.JSONDecodeError, ValueError) as e:
        print("[proxy] ERROR: Invalid config: {}".format(e), file=sys.stderr)
        sys.exit(1)

    provider_names = set(_vendors.keys())
    errors = validate_config(_current_config, provider_names)
    if errors:
        print("[proxy] ERROR: Config validation failed:", file=sys.stderr)
        for err in errors:
            print("[proxy]   - {}".format(err), file=sys.stderr)
        sys.exit(1)

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
        "last_heartbeat": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "last_request_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    write_state(state)
    _startup_state = state

    # Write start marker to trace
    write_start_marker()

    # Start background threads
    threading.Thread(target=heartbeat_loop, daemon=True).start()

    # Start server with ThreadingHTTPServer for concurrent requests
    server = http.server.ThreadingHTTPServer(("127.0.0.1", PROXY_PORT), ProxyHandler)
    print("[proxy] Listening on 127.0.0.1:{}".format(PROXY_PORT), file=sys.stderr)
    print("[proxy] Providers: {}".format(", ".join(_vendors.keys())), file=sys.stderr)
    # Print readiness marker to stdout for CLI to detect (separate from stderr logs)
    print("READY", flush=True)
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