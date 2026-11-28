"""Upstream transport tests: proxy entry without an auth header,
Accept-Encoding identity, cookie isolation, and IPv6 provider URLs."""

import http
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from _harness import PROXY_SERVER, _create_test_config, _create_test_keys, _create_test_keys_plain, _drain_child_stderr, _mode_tiers, _send_proxy_request, _spawn_proxy_with_bind_retry, _start_mode_proxy, fail, find_free_port, pass_, run_cli


# ===========================================================================
# Test Case 23: Start No Auth Header Required
# ===========================================================================

def test_start_no_auth_header_required():
    """Start proxy, send POST without X-Proxy-Auth header; assert 200 (forwarded)."""
    print("\n--- Test 23: Start No Auth Header Required ---")

    import http.client as http_client

    upstream_port = find_free_port()
    proxy_port = find_free_port()

    class NoAuthHandler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"id":"ok","type":"message"}')

        def log_message(self, format, *args):
            pass

    mock_server = http.server.ThreadingHTTPServer(("127.0.0.1", upstream_port), NoAuthHandler)
    mock_thread = threading.Thread(target=mock_server.serve_forever, daemon=True)
    mock_thread.start()
    time.sleep(0.3)

    # Create temp config and keys
    temp_dir = tempfile.mkdtemp(prefix="proxy_noauth_test_")
    tiers = {
        "haiku": {"provider": "test-provider", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "test-provider", "model": "claude-sonnet-5"},
        "opus": {"provider": "test-provider", "model": "claude-opus-5"},
    }
    vendors = {
        "test-provider": {"url": f"http://127.0.0.1:{upstream_port}", "key": "test-api-key"}
    }
    config_path = _create_test_config(temp_dir, tiers)
    keys_path = _create_test_keys(temp_dir, vendors)

    env = os.environ.copy()
    env["PROXY_PORT"] = str(proxy_port)

    proc = subprocess.Popen(
        PROXY_SERVER + ["--port", str(proxy_port), "--config-path", config_path, "--keys-path", keys_path],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, text=True
    )
    _drain_child_stderr(proc)

    # Pipe passphrase to server
    if proc.stdin:
        try:
            proc.stdin.write("test-passphrase\n")
            proc.stdin.flush()
        except BrokenPipeError:
            pass
        finally:
            try:
                proc.stdin.close()
            except:
                pass

    # TCP probe for readiness (server no longer prints auth token)
    ready = False
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            sock.connect(("127.0.0.1", proxy_port))
            sock.close()
            ready = True
            break
        except (socket.error, ConnectionRefusedError):
            time.sleep(0.1)

    if not ready:
        proc.kill()
        mock_server.shutdown()
        shutil.rmtree(temp_dir, ignore_errors=True)
        fail("Proxy server failed to start (TCP probe timeout)")
        return

    try:
        # Send request WITHOUT X-Proxy-Auth header — must succeed (200)
        body = json.dumps({"model": "sonnet", "messages": [{"role": "user", "content": "hi"}]})
        conn = http_client.HTTPConnection("127.0.0.1", proxy_port, timeout=10)
        conn.request("POST", "/v1/messages", body=body,
                    headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        status = resp.status
        resp.read()
        conn.close()

        if status == 200:
            pass_("POST without X-Proxy-Auth returned 200 — no auth required")
        else:
            fail(f"POST without X-Proxy-Auth returned {status}, expected 200")

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        mock_server.shutdown()
        shutil.rmtree(temp_dir, ignore_errors=True)


# ===========================================================================
# httpx2 transport migration (plan 2026-11-15-httpx2-transport-sse)
# ===========================================================================

def test_upstream_accept_encoding_identity():
    """The forwarded request carries exactly one `Accept-Encoding: identity`.

    Defence-in-depth only: correctness of the read paths rests on iter_raw,
    which is byte-faithful regardless of the response's Content-Encoding. The
    pin preserves the wire state the stdlib transport already produced (the
    name is not in FORWARD_HEADERS, so http.client's own `identity` default
    was what reached upstream) and cannot be overridden from config —
    RESERVED_EXTRA_HEADER_NAMES reserves the name.
    """
    print("\n--- Test: Upstream Accept-Encoding Identity Pin ---")
    tiers = _mode_tiers()
    upstream_port = find_free_port()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port), "key": "K"}}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(
        tiers, vendors)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        status, _body = _send_proxy_request(proxy_port)
        if status != 200:
            fail("expected 200 from the default responder, got {}".format(status))
            return
        reqs = mock_servers["p"]["requests"]
        if not reqs:
            fail("mock upstream recorded no request")
            return
        got = (reqs[0].get("headers") or {}).get("accept-encoding")
        if got == ["identity"]:
            pass_("upstream request carries exactly one Accept-Encoding: identity")
        else:
            fail("expected accept-encoding ['identity'], got {!r}".format(got))
    finally:
        cleanup()


def test_upstream_cookie_isolation():
    """A `Set-Cookie` on one proxied request never replays on the next.

    The upstream client is created per retry chain and dies with it, so
    connection state — cookies included — cannot accumulate across proxied
    requests. This is the mirror of the stateless forwarding the stdlib
    transport provided; a pooled cross-request client would silently start
    replaying provider cookies.
    """
    print("\n--- Test: Upstream Cookie Isolation ---")
    upstream_port = find_free_port()
    tiers = _mode_tiers()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port),
                     "key": "K"}}
    body_bytes = json.dumps({
        "id": "msg_ok", "type": "message", "role": "assistant",
        "model": "claude-sonnet-5",
        "content": [{"type": "text", "text": "hello"}],
        "stop_reason": "end_turn", "stop_sequence": None,
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }).encode()

    def streamer(handler, info):
        # A custom handler is the only shape that can carry an extra response
        # header (the canned responder owns Content-Type/Length only).
        handler.send_response(200)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(body_bytes)))
        handler.send_header("Set-Cookie", "provider_session=abc123")
        handler.end_headers()
        handler.wfile.write(body_bytes)
        handler.wfile.flush()

    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(
        tiers, vendors, streamers={"p": streamer})
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        first_status, _first = _send_proxy_request(proxy_port)
        second_status, _second = _send_proxy_request(proxy_port)
        if first_status != 200 or second_status != 200:
            fail("expected 200 on both requests, got {} / {}".format(
                first_status, second_status))
            return
        reqs = mock_servers["p"]["requests"]
        if len(reqs) != 2:
            fail("expected exactly two upstream requests, got {}".format(len(reqs)))
            return
        second_cookie = (reqs[1].get("headers") or {}).get("cookie")
        if second_cookie is None:
            pass_("request 2 carries no Cookie header after request 1's Set-Cookie")
        else:
            fail("request 2 replayed the upstream cookie: {!r}".format(second_cookie))
    finally:
        cleanup()


def test_ipv6_provider_url_routes():
    """A provider URL with an IPv6-literal authority routes to the upstream.

    urlparse returns `parsed.hostname`, which strips the brackets from
    '[::1]', so the client's base_url has to put them back: an unbracketed
    'http://::1:<port>' makes httpx2 raise InvalidURL at Client construction,
    which sits OUTSIDE the retry loop — every request to such a provider
    answered 502 with zero upstream attempts (the stdlib transport accepted
    the bare host, so the transport swap introduced this). The assertion is
    wire-level on purpose: the ::1 stub must actually receive the POST.
    """
    print("\n--- Test: IPv6-Literal Provider URL Routes ---")

    class Ipv6StubServer(http.server.ThreadingHTTPServer):
        # Windows: SO_REUSEADDR would let a second listener take a held port —
        # the same POSIX-only reuse choice the proxy and the suite's mocks make.
        address_family = socket.AF_INET6
        allow_reuse_address = (sys.platform != "win32")

    hits = []

    class StubHandler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            if length > 0:
                self.rfile.read(length)
            hits.append(self.path)
            payload = json.dumps({
                "id": "msg_v6", "type": "message", "role": "assistant",
                "model": "claude-sonnet-5",
                "content": [{"type": "text", "text": "ok"}],
                "stop_reason": "end_turn", "stop_sequence": None,
                "usage": {"input_tokens": 1, "output_tokens": 1},
            }).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, fmt, *args):
            pass

    try:
        # Bind port 0 directly: no find-free-port TOCTOU, and the stub owns
        # whatever port it reports.
        stub = Ipv6StubServer(("::1", 0), StubHandler)
    except OSError as exc:
        fail("this host cannot bind an IPv6 loopback stub ({}), so the "
             "IPv6-literal routing path cannot be exercised".format(exc))
        return
    threading.Thread(target=stub.serve_forever, daemon=True).start()
    temp_dir = tempfile.mkdtemp(prefix="proxy_ipv6_")
    proc = None
    try:
        upstream_port = stub.server_address[1]
        tiers = _mode_tiers()
        vendors = {"p": {"url": "http://[::1]:{}/v1".format(upstream_port),
                         "key": "K"}}
        config_path = _create_test_config(temp_dir, tiers)
        keys_path = _create_test_keys_plain(temp_dir, vendors)
        trace_fd, trace_file = tempfile.mkstemp(suffix=".jsonl", dir=temp_dir)
        os.close(trace_fd)
        proxy_port, proc, ready = _spawn_proxy_with_bind_retry(
            find_free_port(), config_path=config_path, keys_path=keys_path,
            passphrase=None, trace_file=trace_file)
        if not ready:
            fail("proxy did not become ready with an IPv6-literal provider URL")
            return
        status, body = _send_proxy_request(proxy_port)
        if status != 200:
            fail("expected 200 from the IPv6 provider route, got {}: {!r}"
                 .format(status, body[:300]))
            return
        if len(hits) != 1:
            fail("expected exactly one upstream POST, got {} — zero attempts "
                 "with a 502 is the client-construction failure this test "
                 "guards".format(len(hits)))
            return
        if not hits[0].endswith("/messages"):
            fail("unexpected upstream path {!r} — the plan's '{}' vendor URL is "
                 "expected to carry the appended client path".format(
                     hits[0], "/v1"))
            return
        pass_("IPv6-literal provider URL reached the ::1 stub exactly once "
              "({})".format(hits[0]))
    finally:
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        stub.shutdown()
        stub.server_close()
        shutil.rmtree(temp_dir, ignore_errors=True)


ALL_TESTS = [
    ("start-no-auth-header-required", test_start_no_auth_header_required),
    # httpx2 transport migration (plan 2026-11-15-httpx2-transport-sse)
    ("upstream-accept-encoding-identity", test_upstream_accept_encoding_identity),
    ("upstream-cookie-isolation", test_upstream_cookie_isolation),
    # Step 8 review-Warning fixes (same plan, revision 6)
    ("ipv6-provider-url-routes", test_ipv6_provider_url_routes),
]


if __name__ == "__main__":
    run_cli(ALL_TESTS, "claude-retry-proxy tests: test_retry_streaming_transport")
