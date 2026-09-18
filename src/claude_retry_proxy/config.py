"""config.json pipeline: loading, validation, header-rule safety constants,
and template installation.

The config family lives here extracted verbatim from server.py:
``load_config`` / ``validate_config`` / ``write_config`` / ``install_template``,
plus the extra_request_headers safety constants that move with them.
``parse_upstream`` and ``resolve_api_key`` stay in server.py (request-path
resolution); the CLI consumes these functions via the re-exports on server.py
or by importing ``install_template`` /``_load_config_for_validation`` directly.
"""

import json
import os
import re

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


def _load_config_for_validation(path=None):
    """Load and validate config.json. Returns (config, error_msg)."""
    if path is None:
        path = SETTINGS.config_path
    if not os.path.exists(path):
        return None, "config file not found: {}".format(path)
    try:
        with open(path, "r", encoding="utf-8") as f:
            config = json.load(f)
    except json.JSONDecodeError as e:
        return None, "invalid JSON in config: {}".format(e)
    if not isinstance(config, dict):
        return None, "config must be a JSON object"
    if "tiers" not in config:
        return None, "config missing 'tiers' key"
    # Validate each tier has non-empty provider and model
    tiers = config.get("tiers", {})
    for tier_name in ("haiku", "sonnet", "opus"):
        if tier_name not in tiers:
            return None, "missing required tier: {}".format(tier_name)
        tier = tiers[tier_name]
        if not isinstance(tier, dict):
            return None, "tier '{}' must be an object".format(tier_name)
        if not tier.get("provider"):
            return None, "tier '{}' has empty provider".format(tier_name)
        if not tier.get("model"):
            return None, "tier '{}' has empty model".format(tier_name)
    return config, None
