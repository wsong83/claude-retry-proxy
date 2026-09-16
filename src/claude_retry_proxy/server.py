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

from . import sinks
from . import vimcrypt
from .sanitize import sanitize_error
from .sinks import (log_trace, write_state, increment_total, increment_retried,
                    write_start_marker, write_stop_marker)
from .transforms_chat import (_anthropic_to_chat, _chat_to_anthropic,
                              _map_chat_finish_reason,
                              _transform_anthropic_messages_to_chat,
                              _transform_anthropic_tool_choice_to_chat,
                              _transform_anthropic_tools_to_chat)
from .transforms_common import _transform_and_guard
from .transforms_response import (_anthropic_to_response, _response_to_anthropic)
from .settings import SETTINGS, resolve_trace_file


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
                   "anthropic-version", "accept", "anthropic-beta",
                   "user-agent"}

# Header names an extra_request_headers rule may not set: proxy-managed
# (auth injection, Host, body semantics, forwarded allowlist) plus
# hop-by-hop/protocol framing headers. Match case-insensitively.
RESERVED_EXTRA_HEADER_NAMES = {
    "authorization", "x-api-key", "host", "content-length",
    "content-type", "accept", "anthropic-version", "anthropic-beta",
    "user-agent", "connection", "transfer-encoding", "expect", "te",
    "accept-encoding", "cookie",
}

# 'header' names and 'from' entries must be token-shaped RFC 9110 field names
EXTRA_HEADER_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]*$")

# 'from' entries may not name the client auth headers — copying the client's
# key into an arbitrary outbound header (or the trace) is not permissible.
EXTRA_FROM_FORBIDDEN = {"authorization", "x-api-key"}


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


def _validate_extra_header_spec(provider, spec, errors, seen_headers):
    """Append validation errors for one extra_request_headers rule spec.

    Appends to errors only — never raises. Type-guards every string field
    before any regex/truthiness check so non-string values yield validation
    errors, not exceptions. `seen_headers` tracks lowercased 'header' names
    already accepted for this provider (case-insensitive uniqueness).
    """
    header = spec.get("header")
    if not isinstance(header, str):
        errors.append(
            "extra_request_headers['{}'] rule 'header' must be a string, "
            "got {}".format(provider, type(header).__name__))
        return
    if not header:
        errors.append(
            "extra_request_headers['{}'] rule 'header' cannot be "
            "empty".format(provider))
        return
    if not EXTRA_HEADER_NAME_RE.match(header):
        errors.append(
            "extra_request_headers['{}'] rule 'header' '{}' does not match "
            "^[A-Za-z0-9][A-Za-z0-9-]*$".format(provider, header))
        return
    header_lower = header.lower()
    if header_lower in RESERVED_EXTRA_HEADER_NAMES:
        errors.append(
            "extra_request_headers['{}'] rule 'header' '{}' is reserved "
            "and cannot be set".format(provider, header))
        return
    if header_lower in seen_headers:
        errors.append(
            "extra_request_headers['{}'] duplicate rule 'header' '{}' "
            "(case-insensitive)".format(provider, header))
        return
    seen_headers.add(header_lower)

    from_list = spec.get("from")
    has_from = False
    if from_list is not None:
        if not isinstance(from_list, list):
            errors.append(
                "extra_request_headers['{}'] rule 'from' must be a list of "
                "header names, got {}".format(
                    provider, type(from_list).__name__))
        else:
            for entry in from_list:
                if not isinstance(entry, str):
                    errors.append(
                        "extra_request_headers['{}'] rule 'from' entry must "
                        "be a string, got {}".format(
                            provider, type(entry).__name__))
                    continue
                if not entry.strip():
                    errors.append(
                        "extra_request_headers['{}'] rule 'from' entry "
                        "cannot be empty".format(provider))
                    continue
                if not EXTRA_HEADER_NAME_RE.match(entry):
                    errors.append(
                        "extra_request_headers['{}'] rule 'from' entry '{}' "
                        "does not match ^[A-Za-z0-9][A-Za-z0-9-]*$".format(
                            provider, entry))
                    continue
                if entry.lower() in EXTRA_FROM_FORBIDDEN:
                    errors.append(
                        "extra_request_headers['{}'] rule 'from' entry '{}' "
                        "is reserved (client auth headers cannot be "
                        "copied)".format(provider, entry))
                    continue
                has_from = True

    fallback = spec.get("fallback")
    if fallback is not None:
        if not isinstance(fallback, str):
            errors.append(
                "extra_request_headers['{}'] rule 'fallback' must be a "
                "string, got {}".format(
                    provider, type(fallback).__name__))
        elif not fallback.strip():
            errors.append(
                "extra_request_headers['{}'] rule 'fallback' cannot be "
                "empty".format(provider))
        else:
            try:
                fallback.encode("latin-1")
            except UnicodeEncodeError:
                errors.append(
                    "extra_request_headers['{}'] rule 'fallback' must be "
                    "latin-1 encodable".format(provider))
            else:
                if any(ord(_c) < 32 or ord(_c) == 127 for _c in fallback):
                    errors.append(
                        "extra_request_headers['{}'] rule 'fallback' "
                        "contains control characters".format(provider))

    if not has_from and fallback is None:
        errors.append(
            "extra_request_headers['{}'] rule needs a non-empty 'from' list "
            "or a 'fallback'".format(provider))


def validate_config(config, providers, provider_keys=None):
    """Validate config against available providers.

    Args:
        config: dict with 'tiers' and 'models' keys
        providers: set of available provider names (from keys-index.json)
        provider_keys: optional map of provider -> key names (built with
            vendor_key_names). When provided, each tier's optional "key"
            selector is validated against that list: absent/None/"" select
            the first key, non-string values are errors, and unknown names
            are errors. Legacy two-arg callers (provider_keys=None) skip key
            checks entirely.

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

    # Validate per-tier key selectors against the providers' key lists
    # (provider_keys is additive — legacy two-arg callers skip key checks).
    # Iterates ALL config tiers, not just the three required ones, because
    # resolve_tier's reverse lookup can route to extra tiers. Non-dict tiers
    # are skipped here — a required non-dict tier already got the existing
    # "must be an object" error from the loop above, and this loop must not
    # raise (never-raise property preserved).
    if provider_keys is not None:
        for tier_name, tier in tiers.items():
            if not isinstance(tier, dict):
                continue
            provider = tier.get("provider", "")
            selected = tier.get("key")
            if selected is None or selected == "":
                continue
            if not isinstance(selected, str):
                errors.append(
                    "tier '{}' key must be a string, got {}".format(
                        tier_name, type(selected).__name__))
                continue
            if not provider or provider not in providers:
                continue
            names = provider_keys.get(provider)
            if not names:
                continue
            if selected not in names:
                errors.append(
                    "tier '{}' references unknown key '{}' for provider "
                    "'{}' (available: {})".format(
                        tier_name, selected, provider, ", ".join(names)))

    # Validate disable_retry_claude_count_token is a boolean if present
    if "disable_retry_claude_count_token" in config:
        flag = config["disable_retry_claude_count_token"]
        if not isinstance(flag, bool):
            errors.append(
                "disable_retry_claude_count_token must be a boolean "
                "(true/false), got {}".format(type(flag).__name__))

    # Validate optional extra_request_headers (provider-keyed map of header
    # rules). Absent key is valid (defaults to {} on resolution). Every check
    # appends to errors — never raises — and type-guards string fields before
    # any regex/truthiness test so non-string values yield a validation error,
    # not an exception.
    if "extra_request_headers" in config:
        extra = config.get("extra_request_headers")
        if not isinstance(extra, dict):
            errors.append(
                "extra_request_headers must be an object, got {}".format(
                    type(extra).__name__))
        else:
            for provider, spec_list in extra.items():
                if provider not in models:
                    errors.append(
                        "extra_request_headers references unknown provider "
                        "'{}'".format(provider))
                    continue
                if not isinstance(spec_list, list):
                    errors.append(
                        "extra_request_headers['{}'] must be a list of rule "
                        "objects, got {}".format(
                            provider, type(spec_list).__name__))
                    continue
                seen_headers = set()
                for spec in spec_list:
                    if not isinstance(spec, dict):
                        errors.append(
                            "extra_request_headers['{}'] rule must be an "
                            "object, got {}".format(
                                provider, type(spec).__name__))
                        continue
                    _validate_extra_header_spec(provider, spec, errors,
                                                seen_headers)

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
    """Copy config.json template from src/templates/ to dest_path."""
    import shutil
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    shutil.copy2(SETTINGS.config_template_path, dest_path)


def vendor_key_entries(vendor):
    """Normalize a vendor's key material to [(name, payload), ...].

    Total (never raises) and pure. A non-dict vendor, a vendor with no usable
    key entries, or a malformed shape degrades to [("default", "")]. The
    multi-key "keys" object (insertion order, survivor rule: non-empty-string
    name and non-empty-string payload) takes precedence over the legacy
    "key" string; when a present "keys" object yields zero surviving entries
    the result degrades rather than falling through to "key".
    """
    if not isinstance(vendor, dict):
        return [("default", "")]
    keys_field = vendor.get("keys")
    if isinstance(keys_field, dict):
        entries = [
            (n, p) for n, p in keys_field.items()
            if isinstance(n, str) and n
            and isinstance(p, str) and p
        ]
        if entries:
            return entries
        return [("default", "")]
    key_field = vendor.get("key")
    if isinstance(key_field, str):
        return [("default", key_field)]
    return [("default", "")]


def vendor_key_names(vendor):
    """Key names for a vendor in insertion order (via vendor_key_entries)."""
    return [name for name, _ in vendor_key_entries(vendor)]


def resolve_api_key(vendor, tier_config):
    """Resolve the (payload, name) for a request against a tier config.

    Exact-name match on a non-empty string tier_config["key"]; any other
    selection (absent/None/""/non-string, or a non-dict tier_config) falls
    back to the first entry. Total and pure.
    """
    entries = vendor_key_entries(vendor)
    if isinstance(tier_config, dict):
        selected = tier_config.get("key")
        if isinstance(selected, str) and selected:
            for name, payload in entries:
                if name == selected:
                    return (payload, name)
    return (entries[0][1], entries[0][0])


def _validate_vendor_keys_shape(vendors):
    """Validate the per-vendor key/keys shape of a keys table (load-time gate).

    Raises ValueError on the first violation. Every vendor must carry exactly
    one of the two forms: "key" (legacy single-key string; an empty string is
    accepted with a stderr warning) or "keys" (a non-empty object mapping a
    non-empty charset-safe name to a non-empty string payload free of CR/LF
    and C0 control characters — payloads are emitted verbatim into outbound
    auth headers). Used by both decryption paths so they enforce one shared
    rule, never a divergent one.
    """
    for name, vendor in vendors.items():
        if not isinstance(vendor, dict):
            raise ValueError("vendor '{}' must be an object".format(name))
        if "url" not in vendor:
            raise ValueError("vendor '{}' missing 'url'".format(name))
        has_key = "key" in vendor
        has_keys = "keys" in vendor
        if has_key and has_keys:
            raise ValueError(
                "vendor '{}' has both 'key' and 'keys' — use one form".format(name))
        if not has_key and not has_keys:
            raise ValueError(
                "vendor '{}' missing 'key' or 'keys'".format(name))
        if has_keys:
            keys_field = vendor["keys"]
            if not isinstance(keys_field, dict) or not keys_field:
                raise ValueError(
                    "vendor '{}' 'keys' must be a non-empty object".format(name))
            for kname, payload in keys_field.items():
                if not isinstance(kname, str) or not kname:
                    raise ValueError(
                        "vendor '{}' has an empty key name".format(name))
                if not _validate_admin_name(kname):
                    raise ValueError(
                        "vendor '{}' key name '{}' has invalid characters".format(
                            name, kname))
                if not isinstance(payload, str) or not payload:
                    raise ValueError(
                        "vendor '{}' key '{}' must have a non-empty string "
                        "payload".format(name, kname))
                if any(ord(_c) < 32 or ord(_c) == 127 for _c in payload):
                    raise ValueError(
                        "vendor '{}' key '{}' payload contains control "
                        "characters".format(name, kname))
        else:
            key_value = vendor["key"]
            if not isinstance(key_value, str):
                raise ValueError(
                    "vendor '{}' 'key' must be a string, got {}".format(
                        name, type(key_value).__name__))
            if key_value == "":
                print("[proxy] WARNING: provider '{}' has an empty 'key' — "
                      "requests through it will fail with "
                      "invalid_provider_key".format(name), file=sys.stderr)


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
    _validate_vendor_keys_shape(vendors)
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
    _validate_vendor_keys_shape(vendors)
    for name, vendor in vendors.items():
        mode = vendor.get("mode")
        if mode is None or mode == "":
            print("[proxy] WARNING: provider '{}' has no 'mode' field — "
                  "defaulting to 'anthropic'".format(name), file=sys.stderr)
        elif not isinstance(mode, str) or mode not in SETTINGS.mode_values:
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


# Bind the process-wide sinks to the resolved paths, exactly as the module-level
# path constants did before the extraction.
sinks.configure(trace_path=SETTINGS.trace_file, state_path=SETTINGS.state_file)


class _BestEffortStderr:
    """Wraps a stderr stream so diagnostic prints cannot raise into callers.

    server.py holds ~40 runtime stderr prints, several inside the retry loop's
    try block. A stderr write failure there (full disk — proxy-stderr.log sits
    on the same volume as the sinks) would be read by the loop's
    `except (socket.error, ConnectionError, OSError)` clause as a connection
    error, re-issuing the upstream POST or dropping an already-answered
    response. Guarding the stream covers every present and future print site.
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


def compute_delay(attempt):
    """Exponential backoff: 2^attempt seconds, capped at SETTINGS.max_delay."""
    delay = SETTINGS.initial_delay * (2 ** attempt)
    return min(delay, SETTINGS.max_delay)


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
# Feature compatibility learning (Anthropic mode, single feature)
# ---------------------------------------------------------------------------

# Maintainer-tunable policy constants (no user-facing configuration surface).
COMPAT_INITIAL_THRESHOLD = 32      # strips before first revalidation probe
COMPAT_PROBATION_THRESHOLD = 8     # strips between probation probes
COMPAT_BACKOFF_MULTIPLIER = 2      # threshold multiplier on repeated rejection
COMPAT_MAX_THRESHOLD = 4096        # maximum strip threshold
COMPAT_DELISTING_SUCCESSES = 2     # successful probes to delist
COMPAT_MAX_RETRIES_PER_REQUEST = 1 # maximum compatibility retries per client request
COMPAT_FAILED_CONFIRMATION_SUPPRESSION = 3  # failed confirmations before suppression

# The single learnable feature. Field names from upstream error bodies are
# compared against this constant and never copied into state keys, strip
# logic, or trace events.
COMPAT_FEATURE = "context_management"
COMPAT_FEATURE_MODE = "anthropic"
COMPAT_SCHEMA_VERSION = 1

COMPAT_STATE_UNSUPPORTED = "unsupported"
COMPAT_STATE_PROBATION = "probation"

# In-memory learned state: {key_string: entry_dict}
_compat_state = {}
# Per-key in-memory failed-confirmation counters: {key_string: int}
_compat_failed_confirmations = {}
# Per-key counters of matching requests seen while suppression is active:
# re-enters discovery after COMPAT_INITIAL_THRESHOLD matching requests.
_compat_suppressed_seen = {}
# Rate limiter for compatibility_persist_failed trace events: {key_string: ts}
_compat_persist_warned = {}

# Fast lock: protects _compat_state / _compat_failed_confirmations and
# serializes persistence I/O (built under the lock).
_compat_state_lock = threading.Lock()
# Slow-path lock: at most one in-flight compatibility retry/probe globally.
# Acquired with blocking=False; held for the duration of the upstream HTTP
# call; released in finally on every outcome.
_compat_retry_lock = threading.Lock()


def _compat_validate_constants():
    """Validate tuning-constant relationships at startup; warn and clamp."""
    global COMPAT_INITIAL_THRESHOLD, COMPAT_BACKOFF_MULTIPLIER, \
        COMPAT_DELISTING_SUCCESSES
    if COMPAT_BACKOFF_MULTIPLIER < 2:
        print("[proxy] WARNING: COMPAT_BACKOFF_MULTIPLIER must be >= 2 — "
              "clamped to 2", file=sys.stderr)
        COMPAT_BACKOFF_MULTIPLIER = 2
    if COMPAT_DELISTING_SUCCESSES < 2:
        print("[proxy] WARNING: COMPAT_DELISTING_SUCCESSES must be >= 2 — "
              "clamped to 2", file=sys.stderr)
        COMPAT_DELISTING_SUCCESSES = 2
    if COMPAT_INITIAL_THRESHOLD > COMPAT_MAX_THRESHOLD:
        print("[proxy] WARNING: COMPAT_INITIAL_THRESHOLD exceeds "
              "COMPAT_MAX_THRESHOLD — clamped", file=sys.stderr)
        COMPAT_INITIAL_THRESHOLD = COMPAT_MAX_THRESHOLD


def _compat_key(provider, mode, actual_model):
    """Build the in-memory state key for a learned entry."""
    return (provider, mode, actual_model, COMPAT_FEATURE)


def _compat_file_key(key):
    """Serialize a state key tuple for the persisted dict (unambiguous separator)."""
    return "\x1f".join(key)


def _compat_parse_file_key(key_str):
    return tuple(key_str.split("\x1f"))


def _compat_normalize_threshold(threshold):
    """Snap an arbitrary threshold onto the doubling ladder [initial, max].

    Returns the largest ladder element (initial * multiplier^k) that does not
    exceed min(threshold, max), floored at COMPAT_INITIAL_THRESHOLD.
    """
    t = COMPAT_INITIAL_THRESHOLD
    while t * COMPAT_BACKOFF_MULTIPLIER <= min(threshold, COMPAT_MAX_THRESHOLD):
        t *= COMPAT_BACKOFF_MULTIPLIER
    return t


def _compat_validate_entry(entry):
    """Validate one loaded state entry. Returns normalized entry or None."""
    if not isinstance(entry, dict):
        return None
    provider = entry.get("provider")
    mode = entry.get("mode")
    actual_model = entry.get("actual_model")
    feature = entry.get("feature")
    state = entry.get("state")
    threshold = entry.get("threshold")
    if not isinstance(provider, str) or not provider:
        return None
    if not isinstance(mode, str) or not mode:
        return None
    if not isinstance(actual_model, str) or not actual_model:
        return None
    if not isinstance(feature, str) or not feature:
        return None
    if feature != COMPAT_FEATURE:
        return None
    if state not in (COMPAT_STATE_UNSUPPORTED, COMPAT_STATE_PROBATION):
        return None
    if not isinstance(threshold, int) or isinstance(threshold, bool):
        return None
    strip_counter = entry.get("strip_counter", 0)
    probation_successes = entry.get("probation_successes", 0)
    failed_confirmations = entry.get("failed_confirmations", 0)
    for v in (strip_counter, probation_successes, failed_confirmations):
        if not isinstance(v, int) or isinstance(v, bool):
            return None
    return {
        "schema_version": COMPAT_SCHEMA_VERSION,
        "provider": provider,
        "mode": mode,
        "actual_model": actual_model,
        "feature": feature,
        "state": state,
        "threshold": _compat_normalize_threshold(threshold),
        # Counters are in-memory-only: restart resets them to zero
        # (fail-safe direction — over-stripping, never under-stripping).
        "strip_counter": 0,
        "probation_successes": 0,
        "failed_confirmations": 0,
    }


def _load_compat_state():
    """Load learned compatibility state from SETTINGS.feature_compat_file.

    Missing file → empty state (no warning). Malformed/unreadable file →
    warn to stderr and fail open with empty state. Known schema version with
    invalid individual entries → drop bad entries, keep valid ones, warn per
    entry. Unknown feature keys → ignored (forward-compat).
    """
    global _compat_state
    loaded = {}
    try:
        with open(SETTINGS.feature_compat_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return
    except (OSError, json.JSONDecodeError, UnicodeDecodeError, ValueError) as e:
        print("[proxy] WARNING: compatibility state file unreadable "
              "({}) — failing open with empty state".format(
                  sanitize_error(str(e))), file=sys.stderr)
        return
    if not isinstance(data, dict):
        print("[proxy] WARNING: compatibility state file is not a JSON "
              "object — failing open with empty state", file=sys.stderr)
        return
    version = data.get("schema_version")
    if version != COMPAT_SCHEMA_VERSION:
        print("[proxy] WARNING: compatibility state file has unknown "
              "schema_version {!r} (expected {}) — failing open with "
              "empty state".format(version, COMPAT_SCHEMA_VERSION),
              file=sys.stderr)
        return
    entries = data.get("entries")
    if not isinstance(entries, dict):
        print("[proxy] WARNING: compatibility state file has invalid "
              "'entries' — failing open with empty state", file=sys.stderr)
        return
    for key_str, entry in entries.items():
        if not isinstance(key_str, str):
            continue
        parsed = _compat_validate_entry(entry)
        if parsed is None:
            feature_name = entry.get("feature") if isinstance(entry, dict) else None
            if feature_name != COMPAT_FEATURE:
                # Unknown feature keys: ignore silently (forward-compat).
                continue
            print("[proxy] WARNING: dropping invalid compatibility state "
                  "entry (key redacted)", file=sys.stderr)
            continue
        loaded[_compat_parse_file_key(key_str)] = parsed
    _compat_state = loaded


def _persist_compat_state_locked():
    """Atomically persist the learned state. Caller must hold _compat_state_lock.

    Keeps successful in-memory updates on failure and emits a rate-limited
    metadata-only compatibility_persist_failed trace event (once per 60s per key).
    """
    payload = {
        "schema_version": COMPAT_SCHEMA_VERSION,
        "entries": {_compat_file_key(k): v for k, v in _compat_state.items()},
    }
    d = os.path.dirname(SETTINGS.feature_compat_file)
    tmp = "{}.{}.tmp".format(SETTINGS.feature_compat_file,
                             "{}-{}".format(os.getpid(),
                                            uuid.uuid4().hex[:8]))
    try:
        if d:
            os.makedirs(d, exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        os.replace(tmp, SETTINGS.feature_compat_file)
        if os.name == "posix":
            try:
                os.chmod(SETTINGS.feature_compat_file, 0o600)
            except OSError:
                pass
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        return False
    return True


def _compat_persist_failure_trace(key):
    """Rate-limited metadata-only trace for persistence failure (60s per key)."""
    key_str = _compat_file_key(key)
    now = time.time()
    last = _compat_persist_warned.get(key_str, 0)
    if now - last < 60:
        return
    _compat_persist_warned[key_str] = now
    log_trace({
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "event": "compatibility_persist_failed",
        "provider": key[0],
        "mode": key[1],
        "actual_model": key[2],
        "feature": key[3],
    })


def _compat_update(key, mutate):
    """Apply mutate(entry_dict) under the state lock and persist on transition.

    mutate receives the current entry dict (or None) and returns
    (new_entry_or_None, persist_flag). new_entry None means delist. Returns
    the resulting entry (or None).
    """
    with _compat_state_lock:
        entry = _compat_state.get(key)
        new_entry, persist = mutate(entry)
        if new_entry is None:
            _compat_state.pop(key, None)
        else:
            _compat_state[key] = new_entry
        if persist:
            if not _persist_compat_state_locked():
                _compat_persist_failure_trace(key)
        return new_entry


def _compat_get(key):
    with _compat_state_lock:
        return _compat_state.get(key)


def _compat_record_failed_confirmation(key):
    """Increment the in-memory failed-confirmation counter. Returns the count."""
    with _compat_state_lock:
        n = _compat_failed_confirmations.get(key, 0) + 1
        _compat_failed_confirmations[key] = n
        return n


def _compat_reset_failed_confirmations(key):
    with _compat_state_lock:
        _compat_failed_confirmations.pop(key, None)


def _compat_suppressed(key):
    with _compat_state_lock:
        return _compat_failed_confirmations.get(key, 0) \
            >= COMPAT_FAILED_CONFIRMATION_SUPPRESSION


def _compat_note_suppressed_request(key):
    """Count a matching request seen while suppression is active.

    After COMPAT_INITIAL_THRESHOLD matching requests, re-enter discovery by
    clearing the failed-confirmation counter for the key.
    """
    with _compat_state_lock:
        n = _compat_suppressed_seen.get(key, 0) + 1
        if n >= COMPAT_INITIAL_THRESHOLD:
            _compat_suppressed_seen.pop(key, None)
            _compat_failed_confirmations.pop(key, None)
        else:
            _compat_suppressed_seen[key] = n


def _compat_learn(key, request_id, tier):
    """Record unsupported state for key after a successful stripped retry."""
    def mutate(entry):
        if entry is not None:
            return entry, False  # already learned
        return ({
            "schema_version": COMPAT_SCHEMA_VERSION,
            "provider": key[0],
            "mode": key[1],
            "actual_model": key[2],
            "feature": key[3],
            "state": COMPAT_STATE_UNSUPPORTED,
            "threshold": COMPAT_INITIAL_THRESHOLD,
            "strip_counter": 0,
            "probation_successes": 0,
            "failed_confirmations": 0,
        }, True)

    _compat_update(key, mutate)
    _compat_reset_failed_confirmations(key)
    log_trace({
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "event": "compatibility_learned",
        "request_id": request_id,
        "provider": key[0],
        "mode": key[1],
        "actual_model": key[2],
        "feature": key[3],
        "tier": tier,
        "state": COMPAT_STATE_UNSUPPORTED,
        "threshold": COMPAT_INITIAL_THRESHOLD,
    })


def _compat_record_strip(key):
    """Increment the strip counter. Returns True when the threshold is reached.

    Effective threshold: COMPAT_PROBATION_THRESHOLD (8) in probation state,
    otherwise the entry's (possibly doubled) threshold.
    """
    with _compat_state_lock:
        entry = _compat_state.get(key)
        if entry is None:
            return False
        entry["strip_counter"] += 1
        if entry["state"] == COMPAT_STATE_PROBATION:
            return entry["strip_counter"] >= COMPAT_PROBATION_THRESHOLD
        return entry["strip_counter"] >= entry["threshold"]


def _compat_reset_strip_counter(key):
    with _compat_state_lock:
        entry = _compat_state.get(key)
        if entry is not None:
            entry["strip_counter"] = 0


def _compat_probe_success(key, request_id, tier):
    """Record one probe success; delist at delisting_successes, else probation."""
    existed = True

    def mutate(entry):
        nonlocal existed
        if entry is None:
            existed = False
            return None, False
        entry["probation_successes"] += 1
        entry["strip_counter"] = 0
        if entry["probation_successes"] >= COMPAT_DELISTING_SUCCESSES:
            return None, True
        entry["state"] = COMPAT_STATE_PROBATION
        return entry, True

    result = _compat_update(key, mutate)
    if not existed:
        return  # entry vanished concurrently — no state change to report
    if result is not None:
        log_trace({
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "event": "compatibility_probe_succeeded",
            "request_id": request_id,
            "provider": key[0],
            "mode": key[1],
            "actual_model": key[2],
            "feature": key[3],
            "tier": tier,
            "probation_successes": result["probation_successes"],
        })
    else:
        log_trace({
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "event": "compatibility_delisted",
            "request_id": request_id,
            "provider": key[0],
            "mode": key[1],
            "actual_model": key[2],
            "feature": key[3],
            "tier": tier,
        })


def _compat_probe_rejected(key, request_id, tier):
    """Repeated rejection: reset probation, double the threshold (capped), persist."""
    def mutate(entry):
        if entry is None:
            return None, False
        entry["probation_successes"] = 0
        entry["state"] = COMPAT_STATE_UNSUPPORTED
        entry["strip_counter"] = 0
        entry["threshold"] = min(entry["threshold"] * COMPAT_BACKOFF_MULTIPLIER,
                                 COMPAT_MAX_THRESHOLD)
        return entry, True

    result = _compat_update(key, mutate)
    if result is not None:
        log_trace({
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "event": "compatibility_probe_rejected",
            "request_id": request_id,
            "provider": key[0],
            "mode": key[1],
            "actual_model": key[2],
            "feature": key[3],
            "tier": tier,
            "threshold": result["threshold"],
        })


def _compat_probe_inconclusive(key, request_id, tier):
    """Inconclusive probe: leave state/successes unchanged, reschedule at current."""
    with _compat_state_lock:
        entry = _compat_state.get(key)
        threshold = entry["threshold"] if entry else COMPAT_INITIAL_THRESHOLD
        if entry is not None:
            entry["strip_counter"] = 0
    log_trace({
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "event": "compatibility_probe_inconclusive",
        "request_id": request_id,
        "provider": key[0],
        "mode": key[1],
        "actual_model": key[2],
        "feature": key[3],
        "tier": tier,
        "threshold": threshold,
    })


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
    maximal delay (SETTINGS.max_delay); 503 uses the exponential.
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


# Anchored message-form detector for the observed unsupported-feature 400.
# The feature token must appear at message start or be preceded by ': ' or
# '] ' — dotted nested-path matches (e.g. tools.0.context_management) never
# match. Built from the policy constant; upstream text is only ever matched
# against it, never copied.
_COMPAT_MESSAGE_RE = re.compile(
    r"(?:^|(?<=: )|(?<=\] ))" + re.escape(COMPAT_FEATURE) +
    r": Extra inputs are not permitted$")


def _compat_message_match(data):
    """True if any error message matches the anchored message-form 400 shape."""
    stack = [data]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            msg = node.get("message")
            if isinstance(msg, str) and _COMPAT_MESSAGE_RE.search(msg):
                return True
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return False


def _compat_structured_match(data):
    """True if structured `extra_forbidden` validation data locates the
    feature constant at top level (loc ends with it and is not a nested path)."""
    stack = [data]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            if any(node.get(k) == "extra_forbidden" for k in ("type", "code")):
                loc = node.get("loc", node.get("location"))
                if isinstance(loc, list) and loc:
                    if (loc[-1] == COMPAT_FEATURE and len(loc) <= 2
                            and (len(loc) == 1 or loc[0] in ("body", "request"))):
                        return True
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return False


def _compat_rejection_match(status, resp_body):
    """Recognize the two enumerated unsupported-feature 400 shapes.

    Content-type agnostic: the drained body is parsed as JSON regardless of
    the upstream Content-Type header. Bodies exceeding SETTINGS.max_body_size
    or failing to parse are inconclusive (False — never learn).
    """
    if status != 400 or not resp_body:
        return False
    if len(resp_body) > SETTINGS.max_body_size:
        return False
    try:
        data = json.loads(resp_body)
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
        return False
    if not isinstance(data, dict):
        return False
    return _compat_message_match(data) or _compat_structured_match(data)


def _compat_merge_retries(original_result, retry_result):
    """Sum the original forwarding loop's retries with the retry's own."""
    merged = list(retry_result)
    merged[5] = (retry_result[5] or 0) + (original_result[5] or 0)
    return tuple(merged)


def _compat_stripped_body(body):
    """Derive the stripped client body (original minus the feature). None if
    the original body does not parse as a JSON object."""
    try:
        stripped = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
        return None
    if not isinstance(stripped, dict):
        return None
    stripped.pop(COMPAT_FEATURE, None)
    return json.dumps(stripped).encode("utf-8")


def _compat_probe_outcome(result, key, request_id, tier, method, path,
                          headers, body, handler, config, vendors):
    """Process an unstripped probe response under the state machine.

    2xx records a probation success (evidence recorded at status receipt;
    mid-stream failures do not roll back). The same exact 400 doubles the
    threshold and returns the stripped retry result. Anything else is
    inconclusive. The caller owns _compat_retry_lock.
    """
    status = result[0]
    if 200 <= status < 300:
        _compat_probe_success(key, request_id, tier)
        return result
    if status == 400 and _compat_rejection_match(status, result[2]):
        _compat_probe_rejected(key, request_id, tier)
        stripped_body = _compat_stripped_body(body)
        if stripped_body is None:
            return result
        for _attempt in range(COMPAT_MAX_RETRIES_PER_REQUEST):
            retry_result = _forward_request_impl(
                method, path, headers, stripped_body, handler, request_id,
                config, vendors, suppress_compat=True)
            return _compat_merge_retries(result, retry_result)
        return result
    _compat_probe_inconclusive(key, request_id, tier)
    return result


def _resolve_extra_request_headers(headers, provider_name, config, request_id):
    """Resolve outbound extra request headers for a provider from config rules.

    Pure helper — no globals. Total: unexpected shapes (missing top-level key,
    unknown/None provider, malformed rules, non-string fields, request_id None
    with the token fallback) degrade to a skipped rule / {}; never raises.
    Config validation is the strict gate; this is defense-in-depth, not a
    second gate.

    Inbound `from` names are matched case-insensitively over a plain dict
    (both call sites pass plain dicts, so we compare k.lower() ourselves);
    the first non-empty stripped value wins and the emitted value is the
    stripped value. `fallback` is a literal string or the exact case-sensitive
    token "request_id", which resolves to the `request_id` argument (None
    yields nothing for that rule). Rules whose resolved value contains CR/LF
    are skipped.
    """
    if not provider_name or not isinstance(config, dict):
        return {}
    extra = config.get("extra_request_headers")
    if not isinstance(extra, dict):
        return {}
    rules = extra.get(provider_name)
    if not isinstance(rules, list):
        return {}
    inbound = {}
    for k, v in headers.items():
        if isinstance(k, str):
            lk = k.lower()
            if lk not in inbound:
                inbound[lk] = v
    resolved = {}
    for spec in rules:
        if not isinstance(spec, dict):
            continue
        header = spec.get("header")
        if not isinstance(header, str) or not header:
            continue
        value = None
        from_list = spec.get("from")
        if isinstance(from_list, list):
            for name in from_list:
                if not isinstance(name, str):
                    continue
                candidate = inbound.get(name.lower())
                if candidate is None:
                    continue
                stripped = candidate.strip() if isinstance(candidate, str) else None
                if stripped:
                    value = stripped
                    break
        if value is None:
            fallback = spec.get("fallback")
            if isinstance(fallback, str):
                if fallback == "request_id":
                    if request_id is not None:
                        value = request_id
                elif fallback.strip():
                    value = fallback.strip()
        if value is None:
            continue
        if "\r" in value or "\n" in value:
            continue
        resolved[header] = value
    return resolved


def _forward_request_impl(method, path, headers, body, handler, request_id,
                          config, vendors, suppress_compat=False):
    """Internal implementation of forward_request with snapshot config.

    suppress_compat=True bypasses the feature-compatibility subsystem
    entirely — compatibility retries call this function with the flag set,
    so recursion is structurally impossible and the retry is a single
    upstream attempt (never re-enters the 429/503 retry loop).
    """
    if method not in ALLOWED_METHODS:
        return 400, {}, b'{"error":"Method not allowed"}', 0, 0, 0, "unknown", None, None

    if not ALLOWED_PATH_RE.match(path):
        return 400, {}, b'{"error":"Path not allowed"}', 0, 0, 0, "unknown", None, None

    if body and len(body) > SETTINGS.max_body_size:
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
    api_key, key_name = resolve_api_key(vendor, tier_config)

    if not api_key:
        # Degenerate resolution (defense-in-depth behind the load gate — e.g.
        # a string-form "key": "" vendor): fail clearly rather than emitting
        # an empty/x-api-key: None header upstream.
        err_msg = json.dumps({
            "error": {
                "type": "invalid_provider_key",
                "message": "Provider '{}' has no usable API key configured".format(
                    provider_name)
            }
        })
        return 500, {}, err_msg.encode("utf-8"), 0, 0, 0, tier, provider_name, actual_model

    # Read endpoint mode (None/''/missing normalize to "anthropic")
    mode = vendor.get("mode") or "anthropic"
    if mode not in SETTINGS.mode_values:
        err_msg = json.dumps({
            "error": {
                "type": "invalid_provider_mode",
                "message": "Provider '{}' has invalid mode '{}'. Valid modes: {}".format(
                    provider_name, mode, ", ".join(SETTINGS.mode_values))
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
            "key": key_name,
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

    # Parse the request body once. Unparseable bodies skip compatibility
    # logic entirely (the transform below falls back to the original body).
    body_json = None
    if body:
        try:
            body_json = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            body_json = None

    # Build request body once before the retry loop (never re-transformed per
    # attempt). Anthropic mode does a model-only rewrite (plus learned
    # conditional stripping of the compatibility feature); chat/response modes
    # run the full body transform. On any failure fall back to the original
    # body and log a transform_failure trace event.
    rewritten_body = body
    compat_decision = None  # None | ("strip", key) | ("probe", key)
    compat_outbound_present = False
    if body:
        try:
            body_json["model"] = actual_model
            # Compatibility gate: Anthropic mode only, single learnable
            # feature present at top level in the parsed body, never on
            # compatibility retries, count_tokens excluded.
            if (mode == "anthropic" and not _is_count_tokens
                    and not suppress_compat and isinstance(body_json, dict)
                    and COMPAT_FEATURE in body_json):
                _ck = _compat_key(provider_name, mode, actual_model)
                if _compat_get(_ck) is not None:
                    reached = _compat_record_strip(_ck)
                    if reached and _compat_retry_lock.acquire(blocking=False):
                        # Probe owner: send the unstripped body. Counter
                        # resets to 0 at probe start; strips concurrent with
                        # an in-progress probe count toward the next threshold.
                        _compat_reset_strip_counter(_ck)
                        log_trace({
                            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                            "event": "compatibility_probe_started",
                            "request_id": request_id,
                            "provider": provider_name,
                            "mode": mode,
                            "tier": tier,
                            "actual_model": actual_model,
                            "feature": COMPAT_FEATURE,
                        })
                        compat_decision = ("probe", _ck)
                    else:
                        body_json.pop(COMPAT_FEATURE, None)
                        log_trace({
                            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                            "event": "compatibility_field_stripped",
                            "request_id": request_id,
                            "provider": provider_name,
                            "mode": mode,
                            "tier": tier,
                            "actual_model": actual_model,
                            "feature": COMPAT_FEATURE,
                        })
                        compat_decision = ("strip", _ck)
            if isinstance(body_json, dict):
                compat_outbound_present = COMPAT_FEATURE in body_json
            if mode == "chat":
                rewritten_body = json.dumps(_anthropic_to_chat(
                    body_json, request_id=request_id, mode=mode,
                    provider=provider_name, tier=tier)).encode("utf-8")
            elif mode == "response":
                rewritten_body = json.dumps(_anthropic_to_response(
                    body_json, request_id=request_id, mode=mode,
                    provider=provider_name, tier=tier)).encode("utf-8")
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

    # Apply config-driven extra request headers. Runs here, after the
    # per-mode key injection and outside the retry loop, so injected auth
    # wins by construction (validate_config rejects reserved names) and the
    # resolved value is stable across 429/503 retries.
    for _header_name, _header_value in _resolve_extra_request_headers(
            headers, provider_name, config, request_id).items():
        fwd_headers[_header_name] = _header_value

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

    # Accepted residual (review finding 6): an exotic non-_DISCONNECT
    # client-write OSError during a streamed 2xx probe can re-issue the probe
    # POST after headers were sent; bounded to one spurious threshold doubling,
    # self-heals on the next probe cycle. Documented in CLAUDE.md Gotchas.
    compat_owned = compat_decision is not None and compat_decision[0] == "probe"
    if compat_owned:
        try:
            result = _forward_core(
                method, path, handler, request_id, config, rewritten_body,
                fwd_headers, upstream_path, host, port, use_ssl, tier,
                provider_name, actual_model, mode, _is_count_tokens)
            return _compat_probe_outcome(
                result, compat_decision[1], request_id, tier, method, path,
                headers, body, handler, config, vendors)
        finally:
            _compat_retry_lock.release()

    result = _forward_core(
        method, path, handler, request_id, config, rewritten_body,
        fwd_headers, upstream_path, host, port, use_ssl, tier,
        provider_name, actual_model, mode, _is_count_tokens,
        max_attempts=1 if suppress_compat else None)

    # Stripped request: upstream already saw the stripped body — return as-is.
    if compat_decision is not None:
        return result

    # Discovery: the request carried the feature with no learned entry at
    # send time. On a recognized exact 400, confirm with one stripped retry
    # (single upstream attempt, same snapshot, suppress_compat=True).
    if suppress_compat or mode != "anthropic" or _is_count_tokens \
            or not compat_outbound_present:
        return result
    if result[0] != 400:
        return result
    if not _compat_rejection_match(result[0], result[2]):
        return result
    key = _compat_key(provider_name, mode, actual_model)
    log_trace({
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "event": "compatibility_rejection_detected",
        "request_id": request_id,
        "provider": provider_name,
        "mode": mode,
        "tier": tier,
        "actual_model": actual_model,
        "feature": COMPAT_FEATURE,
    })
    if _compat_suppressed(key):
        _compat_note_suppressed_request(key)
        log_trace({
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "event": "compatibility_failed_confirmation_suppressed",
            "request_id": request_id,
            "provider": provider_name,
            "mode": mode,
            "tier": tier,
            "actual_model": actual_model,
            "feature": COMPAT_FEATURE,
        })
        return result
    if not _compat_retry_lock.acquire(blocking=False):
        return result
    try:
        retry_result = None
        stripped_body = _compat_stripped_body(body)
        if stripped_body is not None:
            for _attempt in range(COMPAT_MAX_RETRIES_PER_REQUEST):
                retry_result = _forward_request_impl(
                    method, path, headers, stripped_body, handler,
                    request_id, config, vendors, suppress_compat=True)
                break
        if retry_result is None:
            return result
        retry_result = _compat_merge_retries(result, retry_result)
        if 200 <= retry_result[0] < 300:
            _compat_learn(key, request_id, tier)
            return retry_result
        _compat_record_failed_confirmation(key)
        if _compat_suppressed(key):
            log_trace({
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "event": "compatibility_failed_confirmation_suppressed",
                "request_id": request_id,
                "provider": provider_name,
                "mode": mode,
                "tier": tier,
                "actual_model": actual_model,
                "feature": COMPAT_FEATURE,
            })
        return result
    finally:
        _compat_retry_lock.release()


def _forward_core(method, path, handler, request_id, config,
                  rewritten_body, fwd_headers, upstream_path,
                  host, port, use_ssl, tier, provider_name, actual_model,
                  mode, is_count_tokens, max_attempts=None):
    """Forwarding pass: 429/503/connection retry loop and response handling.

    max_attempts=None derives the attempt count from config (SETTINGS.max_retries,
    count_tokens exclusion); an explicit value overrides both — compatibility
    retries pass 1 so a compat retry is a single upstream attempt.
    """
    total_start = time.time()
    last_status = None
    retries = 0

    # Skip retry for count_tokens when disabled (avoids wasting bandwidth
    # on providers that don't support this Anthropic-specific endpoint)
    if max_attempts is None:
        disable_retry = config.get("disable_retry_claude_count_token", False)
        max_attempts = 1 if (disable_retry and is_count_tokens) \
                       else SETTINGS.max_retries + 1

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
                        delay = compute_jittered_delay(SETTINGS.max_delay)
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
                    err_body = _read_capped(resp, SETTINGS.max_body_size)
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
                    total_bytes = 0

                    while True:
                        chunk = resp.read(8192)
                        if not chunk:
                            break
                        if first_byte:
                            first_byte_elapsed = (time.time() - first_byte_start) * 1000
                            first_byte = False
                        chunks.append(chunk)
                        total_bytes += len(chunk)
                        if total_bytes > SETTINGS.max_response_size:
                            log_trace({
                                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                "event": "response_size_cap_exceeded",
                                "request_id": request_id,
                                "bytes_read": total_bytes,
                                "limit": SETTINGS.max_response_size,
                            })
                            print("[proxy] Response size limit exceeded ({} bytes), rid={}".format(
                                total_bytes, request_id), file=sys.stderr)
                            break

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
                        total_bytes = 0
                        while True:
                            chunk = resp.read(8192)
                            if not chunk:
                                break
                            if first_byte:
                                first_byte_elapsed = (time.time() - first_byte_start) * 1000
                                first_byte = False
                            chunks.append(chunk)
                            total_bytes += len(chunk)
                            if total_bytes > SETTINGS.max_response_size:
                                log_trace({
                                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                    "event": "response_size_cap_exceeded",
                                    "request_id": request_id,
                                    "bytes_read": total_bytes,
                                    "limit": SETTINGS.max_response_size,
                                })
                                print("[proxy] Response size limit exceeded ({} bytes), rid={}".format(
                                    total_bytes, request_id), file=sys.stderr)
                                break
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
            total_bytes = 0

            while True:
                chunk = resp.read(8192)
                if not chunk:
                    break
                if first_byte:
                    first_byte_elapsed = (time.time() - first_byte_start) * 1000
                    first_byte = False
                chunks.append(chunk)
                total_bytes += len(chunk)
                if total_bytes > SETTINGS.max_response_size:
                    log_trace({
                        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        "event": "response_size_cap_exceeded",
                        "request_id": request_id,
                        "bytes_read": total_bytes,
                        "limit": SETTINGS.max_response_size,
                    })
                    print("[proxy] Response size limit exceeded ({} bytes), rid={}".format(
                        total_bytes, request_id), file=sys.stderr)
                    break

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
                    if bytes_streamed > SETTINGS.max_response_size:
                        log_trace({
                            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                            "event": "response_size_cap_exceeded",
                            "request_id": request_id,
                            "bytes_streamed": bytes_streamed,
                            "limit": SETTINGS.max_response_size,
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
                    if bytes_streamed > SETTINGS.max_response_size:
                        log_trace({
                            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                            "event": "response_size_cap_exceeded",
                            "request_id": request_id,
                            "bytes_streamed": bytes_streamed,
                            "limit": SETTINGS.max_response_size,
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
                    if bytes_streamed > SETTINGS.max_response_size:
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
                if bytes_streamed > SETTINGS.max_response_size:
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
            "limit": SETTINGS.max_response_size,
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
                if mode not in SETTINGS.mode_values:
                    mode = "anthropic"
                providers_detail[name] = {
                    "mode": mode,
                    "keys": vendor_key_names(vendor),
                }
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
            if not _validate_csrf_origin(self, SETTINGS.port):
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
            if not _validate_csrf_origin(self, SETTINGS.port):
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
                key = tier_config.get("key")
                if key is not None and key != "" and (
                        not isinstance(key, str) or not _validate_admin_name(key)):
                    self._send_response(400, json.dumps({
                        "error": "invalid key name: {}".format(key)
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
                names = vendor_key_names(_vendors[provider])
                key = tier_config.get("key")
                if key is None or key == "":
                    tier_config["key"] = names[0]
                elif key not in names:
                    self._send_response(400, json.dumps({
                        "error": "tier '{}': unknown key '{}' for provider "
                        "'{}' (available: {})".format(
                            tier_name, key, provider, ", ".join(names))
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
                    for _key in ("disable_retry_claude_count_token",
                                 "extra_request_headers",):
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
            if not _validate_csrf_origin(self, SETTINGS.port):
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
            provider_keys = {name: vendor_key_names(v) for name, v in _vendors.items()}
            errors = validate_config(new_config, provider_names, provider_keys)
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
        if content_length > SETTINGS.max_body_size:
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
            "key": None,  # resolved below; omitted when resolution fails
            "status": "success" if success else "failure",
            "http_status": status,
            "retries": retries,
            "total_latency_sec": round(total_sec, 3) if total_sec else 0,
            "first_byte_latency_ms": int(first_byte_ms) if first_byte_ms else None,
            "error": None if success else sanitize_error(
                resp_body.decode("utf-8", errors="replace") if resp_body else
                "HTTP {}".format(status))
        }

        # Re-resolve extra request headers for the trace (never threaded
        # through forward_request's return tuple — signature discipline).
        # This uses _current_config at event time, so a mid-request admin
        # swap could log the post-swap mapping; the wire header used the
        # entry snapshot. Trace-only cosmetic divergence, accepted.
        resolved_extra = _resolve_extra_request_headers(
            {k: v for k, v in self.headers.items()},
            provider, _current_config, request_id)
        if resolved_extra:
            trace_entry["extra_request_headers"] = resolved_extra

        # Re-resolve the provider key name for the trace (never threaded
        # through forward_request's return tuple — signature discipline; the
        # wire auth used the entry snapshot). Resolution is generic over ANY
        # tier present in config, so an extra tier reached via reverse model
        # lookup gets its key traced too. Unlike _resolve_extra_request_headers
        # above (total on its inputs), this dereferences _current_config["tiers"]
        # and _vendors, which can KeyError on the unknown-tier / None-provider
        # early-return paths (method/path/model 400s and the 413) and after a
        # mid-request admin swap; the guard keeps do_POST from crashing before
        # the error response and the trace entry are written, and the key field
        # is omitted when resolution is impossible. The provider-ownership
        # check (entry-snapshot provider still owns the tier) prevents a
        # post-swap tier from mixing the old provider's vendor with the new
        # tier's key selector; an unowned tier simply omits the field.
        try:
            if provider:
                _tier_cfg = (_current_config.get("tiers") or {}).get(tier)
                if (isinstance(_tier_cfg, dict)
                        and _tier_cfg.get("provider") == provider
                        and isinstance(_vendors.get(provider), dict)):
                    trace_entry["key"] = resolve_api_key(
                        _vendors[provider], _tier_cfg)[1]
        except Exception:
            pass
        if trace_entry.get("key") is None:
            trace_entry.pop("key", None)

        if SETTINGS.log_all:
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

    global _current_config, _vendors, _config_path, _startup_state

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
    provider_keys = {name: vendor_key_names(v) for name, v in _vendors.items()}
    errors = validate_config(_current_config, provider_names, provider_keys)
    if errors:
        print("[proxy] ERROR: Config validation failed:", file=sys.stderr)
        for err in errors:
            print("[proxy]   - {}".format(err), file=sys.stderr)
        sys.exit(1)

    # Compatibility subsystem: validate tuning constants and load learned state
    _compat_validate_constants()
    _load_compat_state()

    # Check if another proxy is already running on this port
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
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
    _startup_state = state

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
    threading.Thread(target=heartbeat_loop, daemon=True).start()

    # Start server with ThreadingHTTPServer for concurrent requests
    server = http.server.ThreadingHTTPServer(("127.0.0.1", SETTINGS.port), ProxyHandler)
    print("[proxy] Listening on 127.0.0.1:{}".format(SETTINGS.port), file=sys.stderr)
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
            os.remove(SETTINGS.state_file)
        except OSError:
            pass


if __name__ == "__main__":
    main()