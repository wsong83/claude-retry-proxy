"""Request model/tier resolution for the Claude retry gateway.

extract_model(body_bytes) pulls the client-requested model name out of the
request body (total: exactly five outcomes, never raising). resolve_tier(
model_name, config) maps that name onto a serving tier — direct match,
reverse lookup over the configured tiers, then keyword pattern match. Pure
policy leaves consumed by server.py at request entry and by forwarder's
forward path (whose compat/reasoning retries re-enter it). Stdlib-only
(json); this module never imports its parent or any sibling domain module.
"""

import json


# ---------------------------------------------------------------------------
# Model extraction and tier resolution
# ---------------------------------------------------------------------------

def extract_model(body_bytes):
    """Extract model name from request body.

    Returns a 2-tuple (model_name, body_error). The contract is total —
    exactly five outcomes:
      - empty body: ("unknown", None) — early return, never reaches json.loads
        (empty bodies continue to surface as unrecognized_model)
      - object body, usable model: (name, None)
      - object body, model missing/None/non-string: ("unknown", None)
      - parses but is not a dict: (None, "invalid_body_type")
      - does not parse: (None, "invalid_json")
    """
    if not body_bytes:
        return "unknown", None
    try:
        data = json.loads(body_bytes)
    except Exception:  # total per compat._compat_guarded_parse (RecursionError is not a ValueError)
        return None, "invalid_json"
    if not isinstance(data, dict):
        return None, "invalid_body_type"
    model = data.get("model")
    # Guard against None or non-string model values
    if model is None or not isinstance(model, str):
        return "unknown", None
    return model, None


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
