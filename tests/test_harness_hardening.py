"""Harness-behavior tests: port-ownership fallback, proxy-port bind
retry, failure artifact preservation (plan
2026-11-12-test-harness-port-hardening)."""
import http.server
import json
import os
import shutil
import tempfile
import threading

import _harness
from _harness import (
    _MockHTTPServer,
    _create_test_config,
    _create_test_keys_plain,
    _send_proxy_request,
    _spawn_proxy_with_bind_retry,
    _start_mode_proxy,
    fail,
    find_free_port,
    pass_,
    run_cli,
)

# Startup validation requires all three tiers (config.py), so every
# fixture uses the same three-tier shape the admin tests use.
_TIERS = {
    "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
    "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
    "opus": {"provider": "p", "model": "claude-opus-5"},
}


def _hold_a_port():
    """Occupy a TCP port with a silent listener; returns (server, port)."""
    class Silent(http.server.BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass
    server = _MockHTTPServer(("127.0.0.1", 0), Silent)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, server.server_address[1]


def test_bind_fallback_rebinds_and_url_follows():
    """A vendor port held by a foreign listener: the mock rebinds
    ephemeral, the vendor URL follows the bound port, and the request
    path still works end to end."""
    print("\n--- Test: Harness Bind Fallback Rebinds, URL Follows ---")
    holder, held_port = _hold_a_port()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(held_port),
                     "key": "k"}}
    before_url = vendors["p"]["url"]
    td, proxy_port, proc, mock_servers, trace_file, cleanup = \
        _start_mode_proxy(_TIERS, vendors)
    if proc is None:
        fail("setup failed entirely (probe never succeeded)")
        holder.shutdown()
        holder.server_close()
        return
    try:
        after_url = vendors["p"]["url"]
        if after_url == before_url:
            fail("vendor URL was not repointed off the held port: "
                 "{!r}".format(after_url))
            return
        bound_port = mock_servers["p"]["server"].server_address[1]
        if str(bound_port) not in after_url:
            fail("URL {!r} does not carry the bound port {}".format(
                after_url, bound_port))
            return
        body = json.dumps({"model": "sonnet",
                           "messages": [{"role": "user", "content": "hi"}]})
        status, resp = _send_proxy_request(proxy_port, body=body)
        if status != 200:
            fail("end-to-end request failed: {} {!r}".format(status, resp[:200]))
            return
        pass_("mock rebound off the held port, URL followed, request OK")
    finally:
        cleanup()
        holder.shutdown()
        holder.server_close()


def test_proxy_port_busy_retries_once():
    """A proxy spawn onto a held port: the connect-only probe success is
    rejected by marker-vs-liveness discrimination, the dead child's
    stderr names the busy port, and one retry on a fresh port comes up
    ready."""
    print("\n--- Test: Harness Proxy Port Busy Retries Once ---")
    holder, held_port = _hold_a_port()
    temp_dir = tempfile.mkdtemp(prefix="harness_hard_")
    trace_fd, trace_file = tempfile.mkstemp(suffix=".jsonl", dir=temp_dir)
    os.close(trace_fd)
    port = held_port
    proc = None
    try:
        config_path = _create_test_config(temp_dir, _TIERS)
        keys_path = _create_test_keys_plain(
            temp_dir, {"p": {"url": "http://127.0.0.1:1", "key": "k"}})
        port, proc, probe_ok = _spawn_proxy_with_bind_retry(
            held_port, config_path=config_path, keys_path=keys_path,
            passphrase=None, trace_file=trace_file)
        if not probe_ok:
            fail("retry did not bring the proxy up on a fresh port")
            return
        if port == held_port:
            fail("returned port {} is the held port".format(port))
            return
        if proc.poll() is not None:
            fail("returned proc is not alive")
            return
        pass_("proxy respawned on fresh port {} after bind collision".format(port))
    finally:
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()
        holder.shutdown()
        holder.server_close()
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_cleanup_preserves_artifacts_on_failure():
    """With the failure flag set, cleanup() keeps temp_dir, the trace
    file, and a stderr dump, and prints their paths. (The removal branch
    is pinned by the Step 10 suite-level no-residue check, not here.)"""
    print("\n--- Test: Harness Cleanup Preserves Artifacts on Failure ---")
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(find_free_port()),
                     "key": "k"}}
    td, proxy_port, proc, mock_servers, trace_file, cleanup = \
        _start_mode_proxy(_TIERS, vendors)
    if proc is None:
        fail("setup failed")
        return
    _harness._TEST_FAILED = True
    cleanup()
    try:
        if not os.path.isdir(td):
            fail("cleanup() deleted temp_dir despite the failure flag")
            return
        if not os.path.exists(trace_file):
            fail("cleanup() deleted the trace file despite the failure flag")
            return
        if not os.path.exists(os.path.join(td, "proxy-stderr.log")):
            fail("cleanup() wrote no proxy-stderr.log despite the failure flag")
            return
        pass_("failure flag preserves temp_dir, trace file, stderr dump")
    finally:
        _harness._TEST_FAILED = False
        shutil.rmtree(td, ignore_errors=True)


ALL_TESTS = [
    ("harness-bind-fallback-rebinds-and-url-follows",
     test_bind_fallback_rebinds_and_url_follows),
    ("harness-proxy-port-busy-retries-once",
     test_proxy_port_busy_retries_once),
    ("harness-cleanup-preserves-artifacts-on-failure",
     test_cleanup_preserves_artifacts_on_failure),
]


if __name__ == "__main__":
    run_cli(ALL_TESTS, "claude-retry-proxy tests: test_harness_hardening")
