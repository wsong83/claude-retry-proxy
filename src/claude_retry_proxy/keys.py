"""keys-index.json pipeline: vendor key normalization/shape validation,
decryption, and the passphrase bootstrap.

The keys family lives here extracted verbatim from server.py:
``vendor_key_entries`` / ``vendor_key_names`` (request-path pure helpers),
``_validate_vendor_keys_shape`` (load-time gate) and ``load_keys_file``
(the single decryption+parse entry point used by the server and the CLI), and
``read_passphrase_from_stdin`` — a declared member of the keys bootstrap.
``resolve_api_key`` stays in server.py (request-path resolution, parent
callers in the forwarder/admin); the CLI consumes ``load_keys_file`` /
``vendor_key_names`` via server.py re-exports.
"""

import json
import sys

from . import vimcrypt
from .settings import SETTINGS
from .safety import _validate_admin_name


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
