"""config.json + models.json pipeline: two-document loading, validation,
header-rule safety constants, and template installation.

The config family lives here extracted verbatim from server.py:
``load_config`` / ``validate_config`` / ``write_config`` / ``install_template``,
plus the extra_request_headers safety constants that move with them.
The load is two-document: config.json carries the tier mapping (``tiers`` and
nothing else), the sibling models.json — resolved beside the resolved config
path — carries ``models``, ``extra_request_headers``, and
``disable_retry_claude_count_token``, and the two are merged at load
(``models_path_for`` / ``load_models_document`` / ``_load_config_documents``).
A leftover catalog key still in config.json warns on stderr and is ignored.
``parse_upstream`` and ``resolve_api_key`` stay in server.py (request-path
resolution); the CLI consumes these functions via the re-exports on server.py
or by importing ``install_template`` /``_load_config_for_validation`` directly.
"""

import json
import os
import re
import sys

from .settings import SETTINGS


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
# Config loading and validation
# ---------------------------------------------------------------------------

MODELS_FILENAME = "models.json"

# Top-level keys a config.json document may still carry besides "tiers" —
# all three are catalog-era leftovers ignored with a warning; their home is
# the sibling models.json document.
_LEFTOVER_KEYS = ("models", "extra_request_headers", "disable_retry_claude_count_token")


def models_path_for(config_path):
    """Return the sibling models.json path for a config.json path.

    The abspath is load-bearing: a bare ``config.json`` argument would
    otherwise yield an empty dirname and silently resolve the sibling
    against the cwd.
    """
    return os.path.join(os.path.dirname(os.path.abspath(config_path)),
                        MODELS_FILENAME)


def load_models_document(models_path):
    """Read and structurally check the models.json catalog document alone.

    Returns a dict with ``models``, plus ``extra_request_headers`` and
    ``disable_retry_claude_count_token`` when the document carries them.

    Every read or structure failure becomes a ValueError naming models.json
    and its resolved path — FileNotFoundError, IsADirectoryError,
    PermissionError, UnicodeDecodeError and json.JSONDecodeError must all be
    converted, because the server's startup handler catches only
    (FileNotFoundError, json.JSONDecodeError, ValueError) and anything else
    escapes as a raw traceback.
    """
    try:
        with open(models_path, "r", encoding="utf-8") as f:
            doc = json.load(f)
    except FileNotFoundError as e:
        raise ValueError("models.json not found: {}".format(models_path)) from e
    except json.JSONDecodeError as e:
        raise ValueError(
            "models.json is not valid JSON: {} ({})".format(models_path, e)) from e
    except UnicodeDecodeError as e:
        raise ValueError(
            "models.json is not valid UTF-8: {} ({})".format(models_path, e)) from e
    except OSError as e:
        raise ValueError(
            "models.json cannot be read: {} ({})".format(models_path, e)) from e
    if not isinstance(doc, dict):
        raise ValueError("models.json must be a JSON object: {}".format(models_path))
    if "models" not in doc:
        raise ValueError("models.json missing 'models' key: {}".format(models_path))
    if not isinstance(doc["models"], dict):
        raise ValueError(
            "models.json 'models' must be an object: {}".format(models_path))
    if "extra_request_headers" in doc \
            and not isinstance(doc["extra_request_headers"], dict):
        raise ValueError(
            "models.json 'extra_request_headers' must be an object: {}".format(
                models_path))
    if "disable_retry_claude_count_token" in doc \
            and not isinstance(doc["disable_retry_claude_count_token"], bool):
        raise ValueError(
            "models.json 'disable_retry_claude_count_token' must be a boolean: "
            "{}".format(models_path))
    out = {"models": doc["models"]}
    if "extra_request_headers" in doc:
        out["extra_request_headers"] = doc["extra_request_headers"]
    if "disable_retry_claude_count_token" in doc:
        out["disable_retry_claude_count_token"] = \
            doc["disable_retry_claude_count_token"]
    return out


def _load_config_documents(config_path):
    """Load the config.json + sibling models.json pair. Returns (merged, warnings).

    Raises FileNotFoundError when config.json is absent — the load_config
    contract server.py's startup handler keys on. Every other read or
    structure failure on either document becomes a ValueError naming the
    file and its path. Reads config.json's ``tiers`` and nothing else: every
    other key in that document is a catalog-era leftover, collected into
    ``warnings`` (one line per key, in _LEFTOVER_KEYS order) and excluded
    from the merged result.
    """
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            doc = json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(
            "config is not valid JSON: {} ({})".format(config_path, e)) from e
    except UnicodeDecodeError as e:
        raise ValueError(
            "config is not valid UTF-8: {} ({})".format(config_path, e)) from e
    except FileNotFoundError:
        raise
    except OSError as e:
        raise ValueError(
            "config cannot be read: {} ({})".format(config_path, e)) from e
    if not isinstance(doc, dict):
        raise ValueError("config must be a JSON object")
    if "tiers" not in doc:
        raise ValueError("config missing 'tiers' key")
    if not isinstance(doc["tiers"], dict):
        raise ValueError("'tiers' must be an object")

    models_path = models_path_for(config_path)
    models_doc = load_models_document(models_path)
    warnings = []
    for key in _LEFTOVER_KEYS:
        if key not in doc:
            continue
        if key in models_doc:
            warnings.append(
                "[proxy] WARNING: {} carries a '{}' key; it is ignored — "
                "config.json holds the tier mapping, and the value is read "
                "from {}.".format(config_path, key, models_path))
        else:
            warnings.append(
                "[proxy] WARNING: {} carries a '{}' key; it is ignored and "
                "its value is dropped — {} does not carry '{}'.".format(
                    config_path, key, models_path, key))
    merged = {"tiers": doc["tiers"]}
    merged.update(models_doc)
    return merged, warnings


def load_config(path):
    """Load the config.json + sibling models.json pair, merged.

    Reads 'tiers' from config.json and the catalog ('models',
    'extra_request_headers', 'disable_retry_claude_count_token') from the
    sibling models.json resolved beside it. Leftover catalog keys still in
    config.json warn on stderr and are ignored.

    Raises ValueError on invalid JSON or missing required structure in
    either document (naming the file and path).
    Raises FileNotFoundError only when config.json doesn't exist.
    """
    merged, warnings = _load_config_documents(path)
    for line in warnings:
        print(line, file=sys.stderr)
    return merged


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
    """Provision both config.json and its sibling models.json from the
    package's templates/ directory.

    dest_path is resolved through os.path.abspath first — a bare
    --config-path config.json otherwise hands os.path.dirname an empty
    string, and makedirs("") raises FileNotFoundError, which cmd_start's
    except OSError reports as a config-creation failure.

    Existence-gated on both sides: any destination that already exists is
    skipped with a printed 'Preserved existing ...' line — shutil.copy2
    overwrites unconditionally, and cmd_start triggers this function on
    either file's absence, so a populated config.json (or a hand-authored
    catalog) reaches it and an unconditional copy would replace it with the
    empty template.

    models.json is written first and config.json last: cmd_start re-enters
    the install branch whenever either file is absent, so config.json's
    continued absence is the signal that provisioning is unfinished — a
    failed install leaves that signal in place and the next start retries.

    Returns None. Raises OSError naming the failing destination when a
    copy fails.
    """
    import shutil
    dest_path = os.path.abspath(dest_path)
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    destinations = (
        ("models", SETTINGS.models_template_path, models_path_for(dest_path)),
        ("config", SETTINGS.config_template_path, dest_path),
    )
    for label, template_path, dest in destinations:
        if os.path.exists(dest):
            print("Preserved existing {} at: {}".format(
                os.path.basename(dest), dest))
            continue
        try:
            shutil.copy2(template_path, dest)
        except OSError as e:
            raise OSError(
                "cannot install the {} template at {}: {}".format(
                    label, dest, e)) from e
        print("Created {} template at: {}".format(label, dest))


def _load_config_for_validation(path=None):
    """Load the config/models document pair for CLI validation.

    Returns (config, error_msg). Retains the path=None fallback to
    SETTINGS.config_path before any sibling resolution: cmd_status passes
    state.get("config_path"), which is None for state files written before
    that field existed, and os.path.abspath(None) would raise TypeError.
    """
    if path is None:
        path = SETTINGS.config_path
    try:
        config, warnings = _load_config_documents(path)
    except (FileNotFoundError, json.JSONDecodeError, ValueError) as e:
        return None, str(e)
    for line in warnings:
        print(line, file=sys.stderr)
    return config, None
