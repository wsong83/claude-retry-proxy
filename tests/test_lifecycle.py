"""Surface tests for the extracted lifecycle module (plan
2026-11-24-extract-server-lifecycle).

WHY THIS EXISTS. `_BestEffortStderr`, `_ProxyHTTPServer` and the startup/serve/
teardown sequence moved out of `server.py` into `claude_retry_proxy.lifecycle`.
`server.py` stays the entry surface: it keeps a no-argument `main()` wrapper
(the console script `claude_retry_proxy.server:main`, the
`python -m claude_retry_proxy.server` invocation) that binds `ProxyHandler` into
`lifecycle.run_server(handler_class)`, and it re-exports the two private classes
so the suite's existing `srv._BestEffortStderr` / `srv._ProxyHTTPServer` reads
keep resolving. These four checks pin exactly that surface, because nothing else
does:

1. `lifecycle.run_server` exists with signature `(handler_class)`, no default,
   and lifecycle.py defines no `main` — a revert to a self-contained `main()`
   fails here.
2. `srv.main` is a callable taking zero required arguments. Scoped as the
   fast-fail complement only: the behavioral pin for the no-arg entry binding is
   the spawned `s.main()` path in test_cli.py, not this assertion.
3. `srv._BestEffortStderr is lifecycle._BestEffortStderr` and
   `srv._ProxyHTTPServer is lifecycle._ProxyHTTPServer` — a re-export, not a
   copy. Re-defining either class in server.py would silently break the
   identity contract the rest of the suite relies on.
4. `python -m claude_retry_proxy.server --help` exits 0. Scoped as the
   help-branch net only: entry wiring is already pinned by the existing
   direct-spawn tests (test_cli.py's `s.main()` spawn and the `PROXY_SERVER`
   spawns in test_trace.py / test_retry_streaming.py), and moved-body execution
   coverage lives in the plan's step-3 gate (READY spawn + SIGTERM +
   `proxy_ready` trace event). Do not read this as either of those.

Direct-import, one subprocess for the help branch. `_harness` is imported first
so the suite's module-level `PROXY_*` path isolation is in place before the
proxy package is imported and before the child inherits the env.

Part of the claude-retry-proxy suite; runnable standalone.
"""

import inspect
import subprocess

from _harness import (
    PROXY_SERVER,
    fail,
    pass_,
    run_cli,
)

import claude_retry_proxy.lifecycle as lifecycle
import claude_retry_proxy.server as srv


# A local import/argparse short-circuit is a subprocess, not a network call; 60 s
# is a fault ceiling (never a slow machine) so a wedge fails loudly by name.
_HELP_TIMEOUT = 60


def _required_params(fn):
    """Names of a callable's parameters that carry no default."""
    return [
        name for name, param in inspect.signature(fn).parameters.items()
        if param.default is inspect.Parameter.empty
        and param.kind not in (inspect.Parameter.VAR_POSITIONAL,
                               inspect.Parameter.VAR_KEYWORD)
    ]


def test_lifecycle_run_server_signature():
    """`lifecycle.run_server` exists as `(handler_class)` with no default, and
    lifecycle.py defines no `main`.

    The moved sequence takes the handler class by parameter injection because
    lifecycle.py may not import its parent (server.py) — `ProxyHandler` stays
    behind. A revert to a self-contained `main()` (or a defaulted/zero-argument
    handler) breaks the one design decision this plan declares, so it fails
    here. The `main` absence is checked in the module namespace, which also
    catches a re-import of a `main` name into lifecycle.
    """
    print("\n--- Test: lifecycle.run_server Signature ---")
    fn = getattr(lifecycle, "run_server", None)
    if fn is None:
        fail("claude_retry_proxy.lifecycle does not define run_server")
        return
    if not inspect.isfunction(fn):
        fail("lifecycle.run_server is not a function: {!r}".format(type(fn)))
        return
    pass_("lifecycle.run_server exists and is a function")

    params = inspect.signature(fn).parameters
    if list(params) == ["handler_class"]:
        pass_("signature parameter list is exactly (handler_class)")
    else:
        fail("signature parameter list is {!r}, expected ['handler_class']"
             .format(list(params)))
    param = params.get("handler_class")
    if param is not None and param.default is inspect.Parameter.empty:
        pass_("handler_class carries no default")
    else:
        fail("handler_class must exist and carry no default (got {!r})"
             .format(None if param is None else param.default))

    if hasattr(lifecycle, "main"):
        fail("lifecycle.py still defines/re-exports a `main` name; the moved "
             "function is run_server")
    else:
        pass_("lifecycle defines no `main`")


def test_lifecycle_entry_wrapper():
    """`srv.main` is a callable taking zero required arguments.

    Scoped as a fast-fail complement: the behavioral pin for the no-argument
    entry binding is the spawned `s.main()` path in test_cli.py. This check
    exists so a wrapper that grew a required parameter — which would break the
    console script and `-m` invocation — is caught here first, by name.
    """
    print("\n--- Test: server.main Entry Wrapper ---")
    wrapper = getattr(srv, "main", None)
    if wrapper is None:
        fail("claude_retry_proxy.server does not define main")
        return
    if callable(wrapper):
        pass_("srv.main is callable")
    else:
        fail("srv.main is not callable: {!r}".format(type(wrapper)))
        return
    required = _required_params(wrapper)
    if not required:
        pass_("srv.main takes zero required arguments")
    else:
        fail("srv.main requires argument(s) {}; the console script and "
             "`-m` invocation pass none".format(required))


def test_lifecycle_frozen_surface_identity():
    """The two moved classes are re-exported, not copied.

    tests/test_trace.py, tests/test_retry_streaming.py and tests/test_cli.py
    all read `srv._BestEffortStderr` / `srv._ProxyHTTPServer`. Identity is the
    contract: a second definition in server.py (or a wrapper subclass) would
    pass a mere hasattr check while silently splitting the class the suite and
    the running proxy actually use.
    """
    print("\n--- Test: Lifecycle Frozen-Surface Identity ---")
    for name in ("_BestEffortStderr", "_ProxyHTTPServer"):
        srv_obj = getattr(srv, name, None)
        lc_obj = getattr(lifecycle, name, None)
        if lc_obj is None:
            fail("claude_retry_proxy.lifecycle does not define {}".format(name))
            continue
        if srv_obj is None:
            fail("claude_retry_proxy.server does not re-export {}".format(name))
            continue
        if srv_obj is lc_obj:
            pass_("srv.{} is lifecycle.{}".format(name, name))
        else:
            fail("srv.{} is not lifecycle.{} (a copy, not a re-export)"
                 .format(name, name))


def test_lifecycle_server_help_smoke():
    """`python -m claude_retry_proxy.server --help` exits 0.

    Scoped as the help-branch net only — it proves the module imports and
    argparse still parses its option set end to end in a fresh interpreter.
    Entry wiring is already pinned by the existing direct-spawn tests, and the
    moved body's execution is pinned by the plan's step-3 gate (READY spawn,
    SIGTERM shutdown, `proxy_ready` trace event). The child inherits the
    suite's module-level PROXY_* isolation; `--help` touches neither state nor
    trace.
    """
    print("\n--- Test: Server Module --help Smoke ---")
    try:
        proc = subprocess.run(
            PROXY_SERVER + ["--help"],
            capture_output=True,
            text=True,
            timeout=_HELP_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        fail("`python -m claude_retry_proxy.server --help` timed out after {}s"
             .format(_HELP_TIMEOUT))
        return
    except OSError as e:
        fail("cannot spawn the server module: {}".format(e))
        return
    if proc.returncode == 0:
        pass_("--help exits 0")
    else:
        fail("--help exited {} (stderr={!r})".format(
            proc.returncode, (proc.stderr or "")[:400]))
        return
    # Sanity that argparse actually rendered this module's own option set
    # rather than exiting early for an unrelated reason.
    for token in ("--port", "--config-path", "--keys-path"):
        if token in proc.stdout:
            pass_("usage text carries {}".format(token))
        else:
            fail("usage text is missing {}: {!r}".format(
                token, (proc.stdout or "")[:400]))


ALL_TESTS = [
    ("lifecycle-run-server-signature", test_lifecycle_run_server_signature),
    ("lifecycle-entry-wrapper", test_lifecycle_entry_wrapper),
    ("lifecycle-frozen-surface-identity",
     test_lifecycle_frozen_surface_identity),
    ("lifecycle-server-help-smoke", test_lifecycle_server_help_smoke),
]

if __name__ == "__main__":
    run_cli(ALL_TESTS, "claude-retry-proxy tests: test_lifecycle")
