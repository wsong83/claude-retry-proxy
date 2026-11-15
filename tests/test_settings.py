"""Unit tests for the settings module (plan 2026-09-16-extract-settings).

Direct-import, no subprocess. Covers the tests-settings surface nothing else
can reach: the _env_int/_env_str fallback branches (previously exercised only
indirectly through spawn-env), the SETTINGS object identity/shape contract,
the call-time-env trace-path resolver chain, and the package's two version
declarations (__version__ vs pyproject.toml).

Env mutations use a fresh namespace (CLAUDE_RETRY_PROXY_TEST_*) and are
saved/restored in finally — a raise between save and restore would leak into
the shared suite (the patch-coherence hazard the SETTINGS object exists to
close). Unset-state simulators also restore the harness-set value of
PROXY_TRACE_FILE.

Part of the claude-retry-proxy suite; runnable standalone.
"""

import os
import re

from _harness import (
    fail,
    pass_,
    run_cli,
)

import claude_retry_proxy
from claude_retry_proxy import settings
from claude_retry_proxy.server import SETTINGS as SRV_SETTINGS


_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

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


# The real binding's parse/clamp surface (plan 2026-10-12-swap-silence-drain):
# unset -> 30; in-range parses; below-min, above-max, unparseable and empty
# all fall back to the default rather than to a bound.
_SWAP_SILENCE_ENV = "PROXY_SWAP_SILENCE_TIMEOUT"
_SWAP_SILENCE_CASES = [
    ("valid in-range", "7", 7),
    ("min boundary", "1", 1),
    ("below min", "0", 30),
    ("above max", "400", 30),
    ("unparseable", "abc", 30),
    ("empty string", "", 30),
]


# The read-timeout binding (plan 2026-11-15-httpx2-transport-sse, Step 1):
# default 120, floor 10, ceiling 600. The floor is load-bearing — the tester's
# stall tests pin exactly 10 because anything smaller is refused by design and
# silently defaults back to 120.
_READ_TIMEOUT_ENV = "PROXY_READ_TIMEOUT"
_READ_TIMEOUT_CASES = [
    ("valid in-range", "30", 30),
    ("min boundary", "10", 10),
    ("max boundary", "600", 600),
    ("below min", "5", 120),
    ("above max", "900", 120),
    ("unparseable", "abc", 120),
    ("empty string", "", 120),
]


def test_env_int_fallback_semantics():
    """The five _env_int branches: valid in-range parses; unparseable,
    below-min, above-max, and empty/unset all fall back to the default (not
    to a bound). The same surface is pinned for the real
    PROXY_SWAP_SILENCE_TIMEOUT binding (default 30, min 1, max 300) and for
    PROXY_READ_TIMEOUT (default 120, min 10, max 600)."""
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

    absent_swap = _SWAP_SILENCE_ENV not in os.environ
    saved_swap = os.environ.get(_SWAP_SILENCE_ENV)
    try:
        for label, raw, expected in _SWAP_SILENCE_CASES:
            os.environ[_SWAP_SILENCE_ENV] = raw
            got = settings._env_int(_SWAP_SILENCE_ENV, 30, 1, 300)
            if got == expected:
                pass_("swap silence {} -> {}".format(label, got))
            else:
                fail("swap silence {}: expected {}, got {}".format(label, expected, got))
        os.environ.pop(_SWAP_SILENCE_ENV, None)
        got = settings._env_int(_SWAP_SILENCE_ENV, 30, 1, 300)
        if got == 30:
            pass_("swap silence unset -> default 30")
        else:
            fail("swap silence unset: expected default 30, got {}".format(got))
        # The live binding on the SETTINGS singleton — built at import from an
        # environment the harness never sets this var in, so it reads the
        # default 30.
        if settings.SETTINGS.swap_silence_timeout == 30:
            pass_("SETTINGS.swap_silence_timeout is 30 (env unset)")
        else:
            fail("SETTINGS.swap_silence_timeout: expected 30, got {!r}".format(
                settings.SETTINGS.swap_silence_timeout))
    finally:
        _restore_env(saved_swap, _SWAP_SILENCE_ENV, absent_swap)

    absent_read = _READ_TIMEOUT_ENV not in os.environ
    saved_read = os.environ.get(_READ_TIMEOUT_ENV)
    try:
        for label, raw, expected in _READ_TIMEOUT_CASES:
            os.environ[_READ_TIMEOUT_ENV] = raw
            got = settings._env_int(_READ_TIMEOUT_ENV, 120, 10, 600)
            if got == expected:
                pass_("read timeout {} -> {}".format(label, got))
            else:
                fail("read timeout {}: expected {}, got {}".format(
                    label, expected, got))
        os.environ.pop(_READ_TIMEOUT_ENV, None)
        got = settings._env_int(_READ_TIMEOUT_ENV, 120, 10, 600)
        if got == 120:
            pass_("read timeout unset -> default 120")
        else:
            fail("read timeout unset: expected default 120, got {}".format(got))
        # The live binding on the SETTINGS singleton — built at import from an
        # environment the harness never sets this var in, so it reads the
        # default 120. This is the value every spawned proxy inherits unless a
        # test pins PROXY_READ_TIMEOUT itself.
        if settings.SETTINGS.read_timeout == 120:
            pass_("SETTINGS.read_timeout is 120 (env unset)")
        else:
            fail("SETTINGS.read_timeout: expected 120, got {!r}".format(
                settings.SETTINGS.read_timeout))
    finally:
        _restore_env(saved_read, _READ_TIMEOUT_ENV, absent_read)


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
    patch-coherence guarantee). All 18 attributes in the attr_types table
    exist with pinned types: eight ints, one bool (log_all), and nine
    strings; mode_values is pinned separately below, not in the table."""
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
        "swap_silence_timeout": int,
        "read_timeout": int,
        "log_all": bool,
        "trace_file": str,
        "keys_path": str,
        "config_path": str,
        "config_template_path": str,
        "models_template_path": str,
        "state_file": str,
        "feature_compat_file": str,
        "proxy_dir": str,
        "chat_retry_nudge": str,
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
    if settings.SETTINGS.models_template_path != \
            settings.SETTINGS.config_template_path:
        pass_("models_template_path differs from config_template_path")
    else:
        fail("SETTINGS.models_template_path equals config_template_path; "
             "the split templates must be distinct files")
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


def test_version_consistency():
    """`__version__` equals the version declared in pyproject.toml.

    The release carries two independent declarations of one number —
    `claude_retry_proxy.__version__` (what installed packages report) and
    `pyproject.toml`'s `project.version` (what the wheel is built with). The
    plan's Step 2 bump (0.2.0 -> 0.3.0) marked a breaking release (Python
    floor 3.10 + a mandatory httpx2 dependency) and left the second
    declaration stale, so both halves are pinned: the pairing this release
    ships, and their equality in general. Editing one without the other fails
    here instead of shipping a package that misreports its own version.
    """
    print("\n--- Test: Version Consistency ---")
    pyproject_path = os.path.join(_REPO_ROOT, "pyproject.toml")
    try:
        with open(pyproject_path, encoding="utf-8") as fh:
            pyproject = fh.read()
    except OSError as exc:
        fail("cannot read pyproject.toml: {}".format(exc))
        return
    match = re.search(r'(?m)^version\s*=\s*"([^"]+)"', pyproject)
    if match is None:
        fail("pyproject.toml carries no project version line")
        return
    declared = match.group(1)
    runtime = claude_retry_proxy.__version__
    if runtime == declared:
        pass_("__version__ matches pyproject.toml ({!r})".format(runtime))
    else:
        fail("__version__ {!r} != pyproject version {!r} — the two "
             "declarations have drifted".format(runtime, declared))
    if runtime == "0.3.0" and declared == "0.3.0":
        pass_("the 0.3.0 pairing this release ships is pinned")
    else:
        fail("expected the 0.3.0 pairing, got __version__ {!r} / pyproject "
             "{!r}".format(runtime, declared))


ALL_TESTS = [
    ("env-int-fallback-semantics", test_env_int_fallback_semantics),
    ("env-str-fallback-semantics", test_env_str_fallback_semantics),
    ("settings-object-identity-shape", test_settings_object_shape),
    ("resolve-trace-file-chain", test_resolve_trace_file_chain),
    ("version-consistency", test_version_consistency),
]

if __name__ == "__main__":
    run_cli(ALL_TESTS, "settings module unit tests")
