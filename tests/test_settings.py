"""Unit tests for the settings module (plan 2026-09-16-extract-settings).

Direct-import, no subprocess. Covers the tests-settings surface nothing else
can reach: the _env_int/_env_str fallback branches (previously exercised only
indirectly through spawn-env), the SETTINGS object identity/shape contract,
and the call-time-env trace-path resolver chain.

Env mutations use a fresh namespace (CLAUDE_RETRY_PROXY_TEST_*) and are
saved/restored in finally — a raise between save and restore would leak into
the shared suite (the patch-coherence hazard the SETTINGS object exists to
close). Unset-state simulators also restore the harness-set value of
PROXY_TRACE_FILE.

Part of the claude-retry-proxy suite; runnable standalone.
"""

import os

from _harness import (
    fail,
    pass_,
    run_cli,
)

from claude_retry_proxy import settings
from claude_retry_proxy.server import SETTINGS as SRV_SETTINGS


_TEST_ENV_NAME = "CLAUDE_RETRY_PROXY_TEST_UNSET_VALUE"


def _restore_env(saved, name, absent):
    if absent:
        os.environ.pop(name, None)
    else:
        os.environ[name] = saved


_INT_CASES = [
    ("valid in-range", "42", 42),
    ("unparseable", "abc", 7),
    ("below min", "3", 7),
    ("above max", "999", 7),
    ("empty string", "", 7),
]


def test_env_int_fallback_semantics():
    """The five _env_int branches: valid in-range parses; unparseable,
    below-min, above-max, and empty/unset all fall back to the default (not
    to a bound)."""
    print("\n--- Test: _env_int Fallback Semantics ---")
    absent = _TEST_ENV_NAME not in os.environ
    saved = os.environ.get(_TEST_ENV_NAME)
    try:
        for label, raw, expected in _INT_CASES:
            os.environ[_TEST_ENV_NAME] = raw
            got = settings._env_int(_TEST_ENV_NAME, 7, 10, 100)
            if got == expected:
                pass_("{} -> {}".format(label, got))
            else:
                fail("{}: expected {}, got {}".format(label, expected, got))
        os.environ.pop(_TEST_ENV_NAME, None)
        got = settings._env_int(_TEST_ENV_NAME, 7, 10, 100)
        if got == 7:
            pass_("unset -> default 7")
        else:
            fail("unset: expected default 7, got {}".format(got))
    finally:
        _restore_env(saved, _TEST_ENV_NAME, absent)


def test_env_str_fallback_semantics():
    """_env_str: set returns the value; set-but-empty and unset return the
    default (mapped, not passed through the way the state-file path is)."""
    print("\n--- Test: _env_str Fallback Semantics ---")
    absent = _TEST_ENV_NAME not in os.environ
    saved = os.environ.get(_TEST_ENV_NAME)
    try:
        os.environ[_TEST_ENV_NAME] = "some value"
        got = settings._env_str(_TEST_ENV_NAME, "default-val")
        _check_str("set -> value", got, "some value")
        os.environ[_TEST_ENV_NAME] = ""
        got = settings._env_str(_TEST_ENV_NAME, "default-val")
        _check_str("set-but-empty -> default", got, "default-val")
        os.environ.pop(_TEST_ENV_NAME, None)
        got = settings._env_str(_TEST_ENV_NAME, "default-val")
        _check_str("unset -> default", got, "default-val")
    finally:
        _restore_env(saved, _TEST_ENV_NAME, absent)


def _check_str(name, got, expected):
    if got == expected:
        pass_("{} -> {!r}".format(name, got))
    else:
        fail("{}: expected {!r}, got {!r}".format(name, expected, got))


def test_settings_object_shape():
    """srv.SETTINGS is settings.SETTINGS (one object, one binding — the
    patch-coherence guarantee). All 15 attributes exist with pinned types:
    six ints, the log_all bool, seven strings, and mode_values."""
    print("\n--- Test: SETTINGS Object Identity and Shape ---")
    if SRV_SETTINGS is settings.SETTINGS:
        pass_("srv.SETTINGS is settings.SETTINGS")
    else:
        fail("server and settings resolve different SETTINGS objects")
    if isinstance(settings.SETTINGS, settings.ProxySettings):
        pass_("SETTINGS is a ProxySettings instance")
    else:
        fail("SETTINGS is not a ProxySettings instance: {!r}".format(
            type(settings.SETTINGS)))
    attr_types = {
        "port": int,
        "max_retries": int,
        "initial_delay": int,
        "max_delay": int,
        "max_body_size": int,
        "max_response_size": int,
        "log_all": bool,
        "trace_file": str,
        "keys_path": str,
        "config_path": str,
        "config_template_path": str,
        "state_file": str,
        "feature_compat_file": str,
        "proxy_dir": str,
    }
    for attr, typ in sorted(attr_types.items()):
        if not hasattr(settings.SETTINGS, attr):
            fail("SETTINGS attribute missing: {}".format(attr))
            continue
        got = getattr(settings.SETTINGS, attr)
        if typ is int and isinstance(got, bool):
            fail("SETTINGS.{}: bool leaked where int expected".format(attr))
            continue
        if isinstance(got, typ):
            pass_("SETTINGS.{}: {} present".format(attr, typ.__name__))
        else:
            fail("SETTINGS.{}: expected {}, got {}".format(
                attr, typ.__name__, type(got).__name__))
    got_mode = settings.SETTINGS.mode_values
    if got_mode == ("anthropic", "chat", "response"):
        pass_("SETTINGS.mode_values tuple pinned")
    else:
        fail("mode_values: expected pinned tuple, got {!r}".format(got_mode))


def test_resolve_trace_file_chain():
    """The trace-path chain: absolute --log wins verbatim; relative --log
    joins the cwd; absent --log + env set at call time returns the env value
    (the resolver reads os.environ at call time); absent --log + empty env
    falls through to SETTINGS.trace_file."""
    print("\n--- Test: resolve_trace_file Chain ---")
    resolver = settings.resolve_trace_file
    abs_arg = os.path.join(os.getcwd(), "abs-trace.jsonl")
    if os.path.isabs(abs_arg):
        got = resolver(abs_arg)
        _check_str("absolute --log wins verbatim", got, abs_arg)
    rel_arg = "rel-trace.jsonl"
    got = resolver(rel_arg)
    _check_str("relative --log joins cwd", got,
               os.path.join(os.getcwd(), rel_arg))

    name = "PROXY_TRACE_FILE"
    absent = name not in os.environ
    saved = os.environ.get(name)
    try:
        os.environ[name] = os.path.join(os.getcwd(), "env-trace.jsonl")
        got = resolver(None)
        _check_str("env set at call time wins (log_arg None)", got,
                   os.path.join(os.getcwd(), "env-trace.jsonl"))
        os.environ[name] = ""
        got = resolver(None)
        _check_str("env empty falls through to default", got,
                   settings.SETTINGS.trace_file)
    finally:
        _restore_env(saved, name, absent)


ALL_TESTS = [
    ("env-int-fallback-semantics", test_env_int_fallback_semantics),
    ("env-str-fallback-semantics", test_env_str_fallback_semantics),
    ("settings-object-identity-shape", test_settings_object_shape),
    ("resolve-trace-file-chain", test_resolve_trace_file_chain),
]

if __name__ == "__main__":
    run_cli(ALL_TESTS, "settings module unit tests")
