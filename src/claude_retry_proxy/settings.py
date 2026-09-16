import os


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


class ProxySettings:
    """Env-derived settings value bag, constructed once at import.

    Mutation contract: values are derived from env at import time; `main()`
    in server.py is the only production writer (port / trace_file / log_all,
    at startup); tests may write attributes in place (save/restore).
    """

    def __init__(self):
        self.port = _env_int("PROXY_PORT", 8080, 1024, 65535)
        self.max_retries = _env_int("PROXY_MAX_RETRIES", 10, 1, 100)
        self.initial_delay = _env_int("PROXY_INITIAL_DELAY", 1, 1, 60)
        self.max_delay = _env_int("PROXY_MAX_DELAY", 30, 1, 300)
        self.max_body_size = _env_int("PROXY_MAX_BODY_SIZE", 10 * 1024 * 1024, 1024, 100 * 1024 * 1024)
        self.max_response_size = _env_int("PROXY_MAX_RESPONSE_SIZE", 100 * 1024 * 1024, 1024, 1024 * 1024 * 1024)

        self.log_all = _env_str("PROXY_LOG_ALL", "") == "1"

        _default_trace = os.path.join(os.path.expanduser("~"), ".claude", "logs", "proxy-trace.jsonl")
        self.trace_file = _env_str("PROXY_TRACE_FILE", _default_trace)

        # Config paths
        self.config_path = os.path.join(os.path.expanduser("~"), ".claude", "proxy", "config.json")
        _src_root = os.path.dirname(os.path.dirname(__file__))
        self.config_template_path = os.path.join(_src_root, "templates", "config.json")
        _default_keys = os.path.join(os.path.expanduser("~"), ".claude", "keys-index.json")
        self.keys_path = _env_str("PROXY_KEYS_PATH", _default_keys)

        self.mode_values = ("anthropic", "chat", "response")

        self.proxy_dir = os.path.join(os.path.expanduser("~"), ".claude", "proxy")
        self.state_file = os.environ.get("PROXY_STATE_FILE",
                                         os.path.join(self.proxy_dir,
                                                      "proxy-state.json"))

        self.feature_compat_file = _env_str(
            "PROXY_FEATURE_COMPAT_FILE",
            os.path.join(os.path.expanduser("~"), ".claude", "proxy",
                         "feature-compatibility.json"))


SETTINGS = ProxySettings()


def resolve_trace_file(log_arg):
    """Resolve the trace file path: --log (absolute against cwd) >
    $PROXY_TRACE_FILE (read at call time) > SETTINGS.trace_file as default.
    """
    if log_arg:
        return log_arg if os.path.isabs(log_arg) else os.path.join(os.getcwd(), log_arg)
    env = os.environ.get("PROXY_TRACE_FILE", "")
    return env if env else SETTINGS.trace_file


__all__ = ["SETTINGS", "ProxySettings", "resolve_trace_file"]
