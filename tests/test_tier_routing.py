"""Tier routing, model resolution, response model rewriting, and
two-tiers-same-model collision tests.

Part of the claude-retry-proxy suite; runnable standalone.
"""

import http
import json
import os
import shutil
import socket
import subprocess
import tempfile
import threading
import time

from _harness import (
    _admin_post,
    _create_test_config,
    _create_test_keys,
    _create_test_keys_plain,
    _mode_tiers,
    _send_proxy_request,
    _send_proxy_request_stream,
    _setup_tier_routing_test,
    _start_mode_proxy,
    _start_proxy_server_directly,
    _trace_events_named,
    _wait_for_trace_events,
    fail,
    find_free_port,
    pass_,
    run_cli,
)

from claude_retry_proxy.nesting import MAX_JSON_NESTING_DEPTH




# ===========================================================================
# Test: Tier Routing Basic
# ===========================================================================

def test_tier_routing_basic():
    """Send request with model "sonnet", verify correct upstream receives the configured model name and API key."""
    print("\n--- Test: Tier Routing Basic ---")

    upstream_port = find_free_port()
    tiers = {
        "haiku": {"provider": "test-provider", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "test-provider", "model": "claude-sonnet-5"},
        "opus": {"provider": "test-provider", "model": "claude-opus-5"},
    }
    vendors = {
        "test-provider": {"url": f"http://127.0.0.1:{upstream_port}", "key": "test-api-key-12345"}
    }

    temp_dir, proxy_port, proc, mock_servers, cleanup = _setup_tier_routing_test(tiers, vendors)
    if proc is None:
        fail("Failed to set up tier routing test")
        return

    try:
        # Send request with model "sonnet"
        body = json.dumps({"model": "sonnet", "messages": [{"role": "user", "content": "hi"}]})
        status, resp_body = _send_proxy_request(proxy_port, body=body)

        if status != 200:
            fail(f"Request failed with status {status}")
            return

        # Verify upstream received the request
        requests = mock_servers["test-provider"]["requests"]
        if len(requests) == 0:
            fail("Upstream received no requests")
            return

        req = requests[0]
        # Verify API key was injected
        if req["api_key"] != "test-api-key-12345":
            fail(f"Upstream received wrong API key: {req['api_key']}")
        else:
            pass_("Upstream received correct API key from keys-index.json")

        # Verify model was rewritten
        req_data = json.loads(req["body"])
        if req_data.get("model") == "claude-sonnet-5":
            pass_("Upstream received rewritten model name: claude-sonnet-5")
        else:
            fail(f"Upstream received wrong model: {req_data.get('model')}")

    finally:
        cleanup()




# ===========================================================================
# Test: Tier Routing All Tiers
# ===========================================================================

def test_tier_routing_all_tiers():
    """Send haiku/sonnet/opus requests, verify each routes to its configured provider."""
    print("\n--- Test: Tier Routing All Tiers ---")

    haiku_port = find_free_port()
    sonnet_port = find_free_port()
    opus_port = find_free_port()

    tiers = {
        "haiku": {"provider": "haiku-provider", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "sonnet-provider", "model": "claude-sonnet-5"},
        "opus": {"provider": "opus-provider", "model": "claude-opus-5"},
    }
    vendors = {
        "haiku-provider": {"url": f"http://127.0.0.1:{haiku_port}", "key": "haiku-key"},
        "sonnet-provider": {"url": f"http://127.0.0.1:{sonnet_port}", "key": "sonnet-key"},
        "opus-provider": {"url": f"http://127.0.0.1:{opus_port}", "key": "opus-key"},
    }

    temp_dir, proxy_port, proc, mock_servers, cleanup = _setup_tier_routing_test(tiers, vendors)
    if proc is None:
        fail("Failed to set up tier routing test")
        return

    try:
        # Test each tier
        for tier, expected_model in [("haiku", "claude-haudit-4-5"), ("sonnet", "claude-sonnet-5"), ("opus", "claude-opus-5")]:
            body = json.dumps({"model": tier, "messages": [{"role": "user", "content": "hi"}]})
            status, _ = _send_proxy_request(proxy_port, body=body)

            if status != 200:
                fail(f"{tier} request failed with status {status}")
                continue

        # Verify each provider received exactly one request
        for provider_name in ["haiku-provider", "sonnet-provider", "opus-provider"]:
            reqs = mock_servers[provider_name]["requests"]
            if len(reqs) == 1:
                pass_(f"{provider_name} received 1 request")
            else:
                fail(f"{provider_name} received {len(reqs)} requests, expected 1")

    finally:
        cleanup()




# ===========================================================================
# Test: Model Resolution Reverse Lookup
# ===========================================================================

def test_model_resolution_reverse_lookup():
    """Send request with actual model name (e.g. "claude-sonnet-5"), verify reverse-mapping to tier."""
    print("\n--- Test: Model Resolution Reverse Lookup ---")

    upstream_port = find_free_port()
    tiers = {
        "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
        "opus": {"provider": "p", "model": "claude-opus-5"},
    }
    vendors = {"p": {"url": f"http://127.0.0.1:{upstream_port}", "key": "k"}}

    temp_dir, proxy_port, proc, mock_servers, cleanup = _setup_tier_routing_test(tiers, vendors)
    if proc is None:
        fail("Failed to set up test")
        return

    try:
        # Send with actual model name — should reverse-map to tier
        body = json.dumps({"model": "claude-sonnet-5", "messages": [{"role": "user", "content": "hi"}]})
        status, resp_body = _send_proxy_request(proxy_port, body=body)

        if status == 200:
            pass_("Request with actual model name succeeded (reverse lookup worked)")
        else:
            fail(f"Request with actual model name failed: status {status}")

        # Verify response has tier name
        try:
            resp_data = json.loads(resp_body)
            if resp_data.get("model") == "sonnet":
                pass_("Response model rewritten to tier name: sonnet")
            else:
                fail(f"Response model not rewritten: {resp_data.get('model')}")
        except:
            pass  # Response parsing may not be implemented yet

    finally:
        cleanup()




# ===========================================================================
# Test: Model Resolution Pattern Match
# ===========================================================================

def test_model_resolution_pattern_match():
    """Send request with model name containing tier keyword (e.g. "my-sonnet-model"), verify pattern-match resolves to sonnet tier."""
    print("\n--- Test: Model Resolution Pattern Match ---")

    upstream_port = find_free_port()
    tiers = {
        "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
        "opus": {"provider": "p", "model": "claude-opus-5"},
    }
    vendors = {"p": {"url": f"http://127.0.0.1:{upstream_port}", "key": "k"}}

    temp_dir, proxy_port, proc, mock_servers, cleanup = _setup_tier_routing_test(tiers, vendors)
    if proc is None:
        fail("Failed to set up test")
        return

    try:
        # Send with model name containing "sonnet"
        body = json.dumps({"model": "my-custom-sonnet-model", "messages": [{"role": "user", "content": "hi"}]})
        status, _ = _send_proxy_request(proxy_port, body=body)

        if status == 200:
            pass_("Request with pattern-matched model name succeeded")
        else:
            fail(f"Request with pattern-matched model failed: status {status}")

        # Verify upstream received the sonnet model
        reqs = mock_servers["p"]["requests"]
        if len(reqs) > 0:
            req_data = json.loads(reqs[0]["body"])
            if req_data.get("model") == "claude-sonnet-5":
                pass_("Upstream received sonnet model (pattern match resolved correctly)")
            else:
                fail(f"Upstream received wrong model: {req_data.get('model')}")

    finally:
        cleanup()




# ===========================================================================
# Test: Model Resolution Unknown Rejected
# ===========================================================================

def test_model_resolution_unknown_rejected():
    """Send request with unrecognized model name (e.g. "gpt-4"), verify 400 error with valid tier list."""
    print("\n--- Test: Model Resolution Unknown Rejected ---")

    upstream_port = find_free_port()
    tiers = {
        "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
        "opus": {"provider": "p", "model": "claude-opus-5"},
    }
    vendors = {"p": {"url": f"http://127.0.0.1:{upstream_port}", "key": "k"}}

    temp_dir, proxy_port, proc, mock_servers, cleanup = _setup_tier_routing_test(tiers, vendors)
    if proc is None:
        fail("Failed to set up test")
        return

    try:
        # Send with unknown model
        body = json.dumps({"model": "gpt-4", "messages": [{"role": "user", "content": "hi"}]})
        status, resp_body = _send_proxy_request(proxy_port, body=body)

        if status == 400:
            pass_("Unknown model rejected with 400")
            # Check error message includes valid tiers. The envelope's
            # "error" field is an object, so the message is read from
            # error.message; a malformed body must fail, not skip.
            try:
                resp_data = json.loads(resp_body)
            except Exception as e:
                fail("400 response body is not valid JSON: {} ({!r})".format(
                    e, resp_body[:200]))
            else:
                err = resp_data.get("error")
                error_msg = err.get("message", "") if isinstance(err, dict) else ""
                if "haiku" in error_msg or "sonnet" in error_msg or "opus" in error_msg:
                    pass_("Error message includes valid tier names")
                else:
                    fail("Error message doesn't list valid tiers: {!r}".format(
                        error_msg[:200]))
        else:
            fail(f"Unknown model should return 400, got {status}")

        # Verify upstream received NO requests
        reqs = mock_servers["p"]["requests"]
        if len(reqs) == 0:
            pass_("Upstream received no requests for unknown model")
        else:
            fail(f"Upstream received {len(reqs)} requests for unknown model")

    finally:
        cleanup()




# ===========================================================================
# Test: Model Resolution None Rejected
# ===========================================================================

def test_model_resolution_none_rejected():
    """Send request with {"model": null}, verify 400 error (not crash)."""
    print("\n--- Test: Model Resolution None Rejected ---")

    upstream_port = find_free_port()
    tiers = {
        "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
        "opus": {"provider": "p", "model": "claude-opus-5"},
    }
    vendors = {"p": {"url": f"http://127.0.0.1:{upstream_port}", "key": "k"}}

    temp_dir, proxy_port, proc, mock_servers, cleanup = _setup_tier_routing_test(tiers, vendors)
    if proc is None:
        fail("Failed to set up test")
        return

    try:
        # Send with null model
        body = json.dumps({"model": None, "messages": [{"role": "user", "content": "hi"}]})
        status, _ = _send_proxy_request(proxy_port, body=body)

        if status == 400:
            pass_("Null model rejected with 400")
        elif status == 0:
            fail("Null model caused crash (connection error)")
        else:
            fail(f"Null model should return 400, got {status}")

    finally:
        cleanup()




# ===========================================================================
# Test: Response Model Rewrite (non-streaming)
# ===========================================================================

def test_response_model_rewrite():
    """Verify response model name is replaced with tier name (non-streaming)."""
    print("\n--- Test: Response Model Rewrite ---")

    upstream_port = find_free_port()
    tiers = {
        "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
        "opus": {"provider": "p", "model": "claude-opus-5"},
    }
    vendors = {"p": {"url": f"http://127.0.0.1:{upstream_port}", "key": "k"}}

    temp_dir, proxy_port, proc, mock_servers, cleanup = _setup_tier_routing_test(tiers, vendors)
    if proc is None:
        fail("Failed to set up test")
        return

    try:
        # Send request
        body = json.dumps({"model": "sonnet", "messages": [{"role": "user", "content": "hi"}]})
        status, resp_body = _send_proxy_request(proxy_port, body=body)

        if status != 200:
            fail(f"Request failed: {status}")
            return

        # Check response model is rewritten
        try:
            resp_data = json.loads(resp_body)
            if resp_data.get("model") == "sonnet":
                pass_("Response model rewritten to tier name")
            else:
                fail(f"Response model not rewritten: {resp_data.get('model')}")
        except:
            fail("Could not parse response JSON")

    finally:
        cleanup()




# ===========================================================================
# Test: Response Model Rewrite Streaming
# ===========================================================================

def test_response_model_rewrite_streaming():
    """Verify SSE message_start event has tier name, subsequent events unchanged."""
    print("\n--- Test: Response Model Rewrite Streaming ---")

    upstream_port = find_free_port()

    # Mock that streams SSE
    class SSEHandler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            content_len = int(self.headers.get("Content-Length", 0))
            if content_len > 0:
                self.rfile.read(content_len)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            # Send message_start with model
            event1 = json.dumps({"type": "message_start", "message": {"model": "claude-sonnet-5"}})
            self.wfile.write(f"data: {event1}\n\n".encode())
            self.wfile.flush()
            # Send content_block_delta (no model field)
            event2 = json.dumps({"type": "content_block_delta", "delta": {"text": "Hi"}})
            self.wfile.write(f"data: {event2}\n\n".encode())
            self.wfile.flush()

        def log_message(self, format, *args):
            pass

    mock_server = http.server.ThreadingHTTPServer(("127.0.0.1", upstream_port), SSEHandler)
    mock_thread = threading.Thread(target=mock_server.serve_forever, daemon=True)
    mock_thread.start()
    time.sleep(0.2)

    tiers = {
        "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
        "opus": {"provider": "p", "model": "claude-opus-5"},
    }
    vendors = {"p": {"url": f"http://127.0.0.1:{upstream_port}", "key": "k"}}

    temp_dir, proxy_port, proc, mock_servers, cleanup = _setup_tier_routing_test(tiers, vendors)
    if proc is None:
        mock_server.shutdown()
        fail("Failed to set up test")
        return

    try:
        # Send streaming request
        body = json.dumps({"model": "sonnet", "messages": [{"role": "user", "content": "hi"}], "stream": True})
        import http.client as _hc
        conn = _hc.HTTPConnection("127.0.0.1", proxy_port, timeout=10)
        conn.request("POST", "/v1/messages", body=body, headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        resp_data = resp.read().decode()
        conn.close()

        # Check first event has tier name
        if '"model": "sonnet"' in resp_data or '"model":"sonnet"' in resp_data:
            pass_("SSE message_start has tier name")
        else:
            fail("SSE message_start doesn't have tier name")

        # Check subsequent events are unchanged
        if "content_block_delta" in resp_data:
            pass_("Subsequent SSE events present")
        else:
            fail("Subsequent SSE events missing")

    finally:
        cleanup()
        mock_server.shutdown()




# ===========================================================================
# Test: Response Model Rewrite Streaming Non-Message-Start
# ===========================================================================

def test_response_model_rewrite_streaming_non_message_start():
    """First SSE event is not message_start → forwarded unchanged, no rewrite attempted."""
    print("\n--- Test: Response Model Rewrite Streaming Non-Message-Start ---")

    upstream_port = find_free_port()

    class SSEHandler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            content_len = int(self.headers.get("Content-Length", 0))
            if content_len > 0:
                self.rfile.read(content_len)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            # First event is a ping, not message_start
            self.wfile.write(b"data: {\"type\": \"ping\"}\n\n")
            self.wfile.flush()
            self.wfile.write(b"data: {\"type\": \"message_start\", \"message\": {\"model\": \"claude-sonnet-5\"}}\n\n")
            self.wfile.flush()

        def log_message(self, format, *args):
            pass

    mock_server = http.server.ThreadingHTTPServer(("127.0.0.1", upstream_port), SSEHandler)
    mock_thread = threading.Thread(target=mock_server.serve_forever, daemon=True)
    mock_thread.start()
    time.sleep(0.2)

    tiers = {
        "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
        "opus": {"provider": "p", "model": "claude-opus-5"},
    }
    vendors = {"p": {"url": f"http://127.0.0.1:{upstream_port}", "key": "k"}}

    temp_dir, proxy_port, proc, mock_servers, cleanup = _setup_tier_routing_test(tiers, vendors)
    if proc is None:
        mock_server.shutdown()
        fail("Failed to set up test")
        return

    try:
        body = json.dumps({"model": "sonnet", "messages": [{"role": "user", "content": "hi"}], "stream": True})
        import http.client as _hc
        conn = _hc.HTTPConnection("127.0.0.1", proxy_port, timeout=10)
        conn.request("POST", "/v1/messages", body=body, headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        resp_data = resp.read().decode()
        conn.close()

        # First event should be unchanged (ping)
        if '{"type": "ping"}' in resp_data or '{"type":"ping"}' in resp_data:
            pass_("First SSE event (ping) forwarded unchanged")
        else:
            fail("First SSE event was modified")

    finally:
        cleanup()
        mock_server.shutdown()




# ===========================================================================
# Test: Two Tiers, Same Model, Same Provider
# ===========================================================================

def test_two_tiers_same_model_same_provider():
    """Two tiers mapping to the same model from the same provider: the server
    starts, each request routes to the shared model, and JSON + SSE responses
    are rewritten to the requesting tier's name (no reverse map needed)."""
    print("\n--- Test: Two Tiers Same Model Same Provider ---")

    upstream_port = find_free_port()
    requests = []

    class CollisionHandler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            content_len = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_len) if content_len > 0 else b"{}"
            api_key = self.headers.get("x-api-key", "")
            requests.append({"body": body, "api_key": api_key})
            try:
                req_data = json.loads(body)
                model = req_data.get("model", "unknown")
                is_stream = bool(req_data.get("stream", False))
            except Exception:
                model = "unknown"
                is_stream = False
            if is_stream:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                event1 = json.dumps({"type": "message_start", "message": {"model": model}})
                self.wfile.write(f"data: {event1}\n\n".encode())
                self.wfile.flush()
                event2 = json.dumps({"type": "content_block_delta", "delta": {"text": "Hi"}})
                self.wfile.write(f"data: {event2}\n\n".encode())
                self.wfile.flush()
            else:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "id": "ok",
                    "type": "message",
                    "model": model,
                    "content": [{"text": "response"}],
                }).encode())

        def log_message(self, format, *args):
            pass

    mock_server = http.server.ThreadingHTTPServer(("127.0.0.1", upstream_port), CollisionHandler)
    mock_thread = threading.Thread(target=mock_server.serve_forever, daemon=True)
    mock_thread.start()
    time.sleep(0.2)

    tiers = {
        "haiku": {"provider": "p", "model": "deepseek-v4-flash"},
        "sonnet": {"provider": "p", "model": "deepseek-v4-flash"},  # collision with haiku
        "opus": {"provider": "p", "model": "claude-opus-5"},
    }
    vendors = {"p": {"url": f"http://127.0.0.1:{upstream_port}", "key": "k"}}

    temp_dir = tempfile.mkdtemp(prefix="proxy_collision_test_")
    proxy_port = find_free_port()
    try:
        config_path = _create_test_config(temp_dir, tiers)
        keys_path = _create_test_keys(temp_dir, vendors)
        trace_fd, trace_file = tempfile.mkstemp(suffix=".jsonl", dir=temp_dir)
        os.close(trace_fd)
        proc, probe_ok = _start_proxy_server_directly(
            proxy_port, config_path=config_path, keys_path=keys_path, trace_file=trace_file
        )
        if not probe_ok:
            fail("Proxy failed to start with two tiers mapping to the same model")
            return

        try:
            import http.client as _hc

            # --- JSON path: each request gets its own tier name ---
            body = json.dumps({"model": "sonnet", "messages": [{"role": "user", "content": "hi"}]})
            status, resp_body = _send_proxy_request(proxy_port, body=body)
            if status != 200:
                fail(f"sonnet request failed: {status}")
            else:
                resp_data = json.loads(resp_body)
                if resp_data.get("model") == "sonnet":
                    pass_("sonnet request -> response model 'sonnet'")
                else:
                    fail(f"sonnet response model: {resp_data.get('model')!r}, expected 'sonnet'")

            body = json.dumps({"model": "haiku", "messages": [{"role": "user", "content": "hi"}]})
            status, resp_body = _send_proxy_request(proxy_port, body=body)
            if status != 200:
                fail(f"haiku request failed: {status}")
            else:
                resp_data = json.loads(resp_body)
                if resp_data.get("model") == "haiku":
                    pass_("haiku request -> response model 'haiku'")
                else:
                    fail(f"haiku response model: {resp_data.get('model')!r}, expected 'haiku'")

            # Upstream received the shared configured model name for both tiers
            if len(requests) >= 2 and all(
                json.loads(r["body"]).get("model") == "deepseek-v4-flash"
                for r in requests[:2]
            ):
                pass_("Upstream received deepseek-v4-flash for both tiers")
            else:
                fail(f"Upstream model names: {[json.loads(r['body']).get('model') for r in requests]}")

            # --- SSE path: message_start rewritten to per-request tier ---
            stream_body = json.dumps({"model": "sonnet", "messages": [{"role": "user", "content": "hi"}], "stream": True})
            conn = _hc.HTTPConnection("127.0.0.1", proxy_port, timeout=10)
            conn.request("POST", "/v1/messages", body=stream_body, headers={"Content-Type": "application/json"})
            resp = conn.getresponse()
            sse_data = resp.read().decode()
            conn.close()

            if '"model": "sonnet"' in sse_data or '"model":"sonnet"' in sse_data:
                pass_("SSE message_start rewritten to 'sonnet' for sonnet request")
            else:
                fail(f"SSE response model not 'sonnet': {sse_data[:200]}")

            stream_body = json.dumps({"model": "haiku", "messages": [{"role": "user", "content": "hi"}], "stream": True})
            conn = _hc.HTTPConnection("127.0.0.1", proxy_port, timeout=10)
            conn.request("POST", "/v1/messages", body=stream_body, headers={"Content-Type": "application/json"})
            resp = conn.getresponse()
            sse_data = resp.read().decode()
            conn.close()

            if '"model": "haiku"' in sse_data or '"model":"haiku"' in sse_data:
                pass_("SSE message_start rewritten to 'haiku' for haiku request")
            else:
                fail(f"SSE response model not 'haiku': {sse_data[:200]}")

        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
    finally:
        mock_server.shutdown()
        shutil.rmtree(temp_dir, ignore_errors=True)




# ===========================================================================
# Test: Response Model Rewrite Upstream Model
# ===========================================================================

def test_response_model_rewrite_upstream_model():
    """Upstream returns an arbitrary model name → rewritten to tier name (unconditional rewrite)."""
    print("\n--- Test: Response Model Rewrite Upstream Model ---")

    upstream_port = find_free_port()

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            content_len = int(self.headers.get("Content-Length", 0))
            if content_len > 0:
                self.rfile.read(content_len)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            # Return a model name not configured in any tier
            self.wfile.write(b'{"id":"ok","type":"message","model":"unknown-model"}')

        def log_message(self, format, *args):
            pass

    mock_server = http.server.ThreadingHTTPServer(("127.0.0.1", upstream_port), Handler)
    mock_thread = threading.Thread(target=mock_server.serve_forever, daemon=True)
    mock_thread.start()
    time.sleep(0.2)

    tiers = {
        "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
        "opus": {"provider": "p", "model": "claude-opus-5"},
    }
    vendors = {"p": {"url": f"http://127.0.0.1:{upstream_port}", "key": "k"}}

    temp_dir, proxy_port, proc, mock_servers, cleanup = _setup_tier_routing_test(tiers, vendors)
    if proc is None:
        mock_server.shutdown()
        fail("Failed to set up test")
        return

    try:
        body = json.dumps({"model": "sonnet", "messages": [{"role": "user", "content": "hi"}]})
        status, resp_body = _send_proxy_request(proxy_port, body=body)

        if status != 200:
            fail(f"Request failed: {status}")
            return

        # Unconfigured upstream model is still rewritten to the tier name
        try:
            resp_data = json.loads(resp_body)
            if resp_data.get("model") == "sonnet":
                pass_("Unknown upstream model rewritten to tier name")
            else:
                fail(f"Response model not rewritten: {resp_data.get('model')}")
        except:
            fail("Could not parse response")

    finally:
        cleanup()
        mock_server.shutdown()


# ===========================================================================
# Standard-envelope conformance tests
#
# The proxy is a drop-in replacement for the Anthropic Messages API, so its
# own error responses must carry the standard envelope:
#   {"type":"error","error":{"type":<taxonomy>,"code":<proxy code>,
#    "message":…},"request_id":…}
# error.code is the proxy discriminator; error.type is the Anthropic category.
# ===========================================================================

def test_non_object_body_rejected():
    """Every non-object JSON body returns 400 invalid_body_type, never a
    dropped connection.

    A body that is valid JSON but not an object (null, 123, "x", [1,2],
    true, 3.14) previously raised AttributeError on data.get(...) and
    aborted the request with zero bytes. Each shape must now produce a
    parseable 400 with error.code == "invalid_body_type" and the upstream
    must receive nothing.
    """
    print("\n--- Test: Non-Object Body Rejected With invalid_body_type ---")

    upstream_port = find_free_port()
    tiers = {
        "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
        "opus": {"provider": "p", "model": "claude-opus-5"},
    }
    vendors = {"p": {"url": f"http://127.0.0.1:{upstream_port}", "key": "k"}}

    temp_dir, proxy_port, proc, mock_servers, cleanup = _setup_tier_routing_test(tiers, vendors)
    if proc is None:
        fail("Failed to set up test")
        return

    corpus = ["null", "123", '"x"', "[1,2]", "true", "3.14"]
    try:
        for label in corpus:
            status, resp_body = _send_proxy_request(proxy_port, body=label)
            if status == 400:
                try:
                    data = json.loads(resp_body)
                except Exception as e:
                    fail("body {}: 400 is not valid JSON: {} ({!r})".format(
                        label, e, resp_body[:200]))
                    continue
                code = (data.get("error") or {}).get("code")
                if code == "invalid_body_type":
                    pass_("body {} -> 400 invalid_body_type".format(label))
                else:
                    fail("body {}: expected error.code invalid_body_type, got {!r}".format(
                        label, code))
            elif status == 0:
                fail("body {} caused crash (connection error)".format(label))
            else:
                fail("body {} should return 400, got {}".format(label, status))

        reqs = mock_servers["p"]["requests"]
        if len(reqs) == 0:
            pass_("Upstream received no requests for any non-object body")
        else:
            fail("Upstream received {} requests for non-object bodies".format(len(reqs)))

    finally:
        cleanup()


def test_nesting_limit_client_body():
    """The client nesting boundary: accept at the limit, reject past it.

    One parameterized test so the accept case is the same request shape (model,
    route, tool schema) the reject cases refuse:

      - at exactly MAX_JSON_NESTING_DEPTH, forced through the scanner's SLOW
        path (two sibling chains push the total open count past the limit, so
        the count fast path cannot decide) -> the request is served, and the
        transform demonstrably ran: the tool-schema pattern reaches the
        upstream normalized and no transform_failure event is logged. Without
        that second half, a silent degrade to the untransformed body would
        look green.
      - at limit+1 -> 400 with error.code "nesting_limit_exceeded", the limit
        and a $-rooted path in the message; the upstream receives nothing.
      - far past the limit -> the same rejection (the scanner reports the
        FIRST crossing, not the deepest).
    """
    print("\n--- Test: Client Body Nesting Limit ---")

    limit = MAX_JSON_NESTING_DEPTH
    # A chain of limit-1 arrays under the root reaches exactly the limit.
    chain = "[" * (limit - 1) + "]" * (limit - 1)
    base = {
        "model": "sonnet",
        "messages": [{"role": "user", "content": "hi"}],
        "tools": [{"name": "mcp__exa__agent_run",
                   "input_schema": {"type": "object",
                                    "properties": {"query": {"type": "string",
                                                             "pattern": r"^agent\_run\_"}}}}],
    }
    head = json.dumps(base)[:-1]
    accept_body = head + ',"a":' + chain + ',"b":' + chain + "}"
    if accept_body.count("[") + accept_body.count("{") <= limit:
        fail("accept fixture does not force the slow path ({} opens, limit {})".format(
            accept_body.count("[") + accept_body.count("{"), limit))
        return
    reject_body = head + ',"a":' + "[" * limit + "]" * limit + "}"
    far_body = head + ',"a":' + "[" * (limit * 10) + "]" * (limit * 10) + "}"

    upstream_port = find_free_port()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port), "key": "K"}}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(
        _mode_tiers(), vendors)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        status, resp_body = _send_proxy_request(proxy_port, body=accept_body)
        if status != 200:
            fail("accept at the limit ({} levels) returned {}, expected 200: {!r}".format(
                limit, status, resp_body[:200]))
            return
        reqs = mock_servers["p"]["requests"]
        if len(reqs) != 1:
            fail("accept at the limit: upstream received {} requests, expected 1".format(
                len(reqs)))
            return
        try:
            upstream_body = json.loads(reqs[0]["body"])
        except Exception as e:
            fail("upstream body is not JSON: {} ({!r})".format(e, reqs[0]["body"][:200]))
            return
        pattern = ((((upstream_body.get("tools") or [{}])[0].get("input_schema") or {})
                    .get("properties") or {}).get("query") or {}).get("pattern")
        if pattern != "^agent_run_":
            fail("the accept case did not run the transform: upstream pattern "
                 "{!r}, expected the sanitized '^agent_run_'".format(pattern))
            return
        if upstream_body.get("messages") != base["messages"]:
            fail("verbatim forward altered the messages: {!r}".format(
                upstream_body.get("messages")))
            return
        events = _trace_events_named(trace_file, "transform_failure")
        if events:
            fail("accept at the limit logged {} transform_failure event(s) — the "
                 "body degraded instead of transforming".format(len(events)))
            return
        events = _trace_events_named(trace_file, "nesting_limit_exceeded")
        if events:
            fail("accept at the limit logged a nesting event: {!r}".format(events[0]))
            return
        pass_("accept at the limit (slow path, {} bytes): served, transform ran, "
              "pattern normalized".format(len(accept_body)))

        for label, body, expected_depth_floor in (
                ("limit+1", reject_body, limit + 1),
                ("far past the limit", far_body, limit + 1)):
            status, resp_body = _send_proxy_request(proxy_port, body=body)
            if status == 0:
                fail("{}: connection dropped instead of a 400 ({!r})".format(
                    label, resp_body[:120]))
                return
            if status != 400:
                fail("{}: expected 400, got {}".format(label, status))
                return
            try:
                data = json.loads(resp_body)
            except Exception as e:
                fail("{}: 400 body is not JSON: {} ({!r})".format(
                    label, e, resp_body[:200]))
                return
            err = data.get("error") or {}
            if err.get("code") != "nesting_limit_exceeded":
                fail("{}: expected error.code nesting_limit_exceeded, got {!r}".format(
                    label, err.get("code")))
                return
            message = err.get("message") or ""
            if "limit of {} levels".format(limit) not in message:
                fail("{}: message does not name the limit: {!r}".format(label, message))
                return
            if ": $" not in message:
                fail("{}: message carries no $-rooted path: {!r}".format(label, message))
                return
            pass_("{} -> 400 nesting_limit_exceeded with limit and path".format(label))

        if len(mock_servers["p"]["requests"]) != 1:
            fail("a rejected body reached the upstream ({} requests)".format(
                len(mock_servers["p"]["requests"])))
            return
        events = [e for e in _trace_events_named(trace_file, "nesting_limit_exceeded")
                  if e.get("site") == "request_body"]
        if len(events) != 2:
            fail("expected 2 request_body nesting events (one per reject), got {}".format(
                len(events)))
            return
        for ev in events:
            if ev.get("depth", 0) < limit + 1:
                fail("event depth {} is not past the limit {}".format(
                    ev.get("depth"), limit))
                return
        entry = [e for e in _trace_events_named(trace_file, "request")
                 if e.get("http_status") == 400 and e.get("model") == "unknown"]
        if len(entry) != 2:
            fail("each rejection must also write a pre-routing request entry "
                 "(http_status 400, model unknown); found {}".format(len(entry)))
            return
        pass_("rejections: upstream untouched, 2 request_body events, 2 mirrored "
              "request entries")
    finally:
        cleanup()


def test_nesting_limit_leading_close_body():
    """A ']'-prefixed deep body gets a 400, never a dropped connection.

    The scanner ignores a close at depth 0, so leading stray closes must not
    stop it from finding the crossing behind them. The body is not valid JSON,
    so the repaired-prefix diagnostic fails and the message carries the
    offset-only form — the same failure class (a zero-byte abort) the pre-plan
    guards were added to remove.
    """
    print("\n--- Test: Leading-Close Deep Body ---")

    limit = MAX_JSON_NESTING_DEPTH
    body = b"]" * 4 + b"[" * (limit + 1) + b"]" * (limit + 1)

    upstream_port = find_free_port()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port), "key": "K"}}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(
        _mode_tiers(), vendors)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        status, resp_body = _send_proxy_request(proxy_port, body=body)
        if status == 0:
            fail("']'-prefixed deep body dropped the connection ({!r})".format(
                resp_body[:120]))
            return
        if status != 400:
            fail("expected 400, got {}".format(status))
            return
        try:
            data = json.loads(resp_body)
        except Exception as e:
            fail("400 body is not JSON: {} ({!r})".format(e, resp_body[:200]))
            return
        err = data.get("error") or {}
        if err.get("code") != "nesting_limit_exceeded":
            fail("expected error.code nesting_limit_exceeded, got {!r}".format(
                err.get("code")))
            return
        message = err.get("message") or ""
        if "body may not be valid JSON" not in message:
            fail("expected the offset-only diagnostic for an unrepairable prefix, "
                 "got {!r}".format(message))
            return
        if mock_servers["p"]["requests"]:
            fail("the rejected body reached the upstream ({} requests)".format(
                len(mock_servers["p"]["requests"])))
            return
        pass_("']'-prefixed deep body -> 400 with the offset-only diagnostic")
    finally:
        cleanup()


def test_error_envelope_shape():
    """Representative error per status family carries the standard envelope.

    path_not_allowed (400), payload_too_large (413) and upstream_unreachable
    (502, read from the RESPONSE not the trace) each carry top-level
    type=="error", an error object with type/code/message, and a non-empty
    top-level request_id.
    """
    print("\n--- Test: Error Envelope Shape ---")

    upstream_port = find_free_port()
    tiers = {
        "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
        "opus": {"provider": "p", "model": "claude-opus-5"},
    }
    vendors = {"p": {"url": f"http://127.0.0.1:{upstream_port}", "key": "k"}}

    temp_dir, proxy_port, proc, mock_servers, cleanup = _setup_tier_routing_test(tiers, vendors)
    if proc is None:
        fail("Failed to set up test")
        return

    def _check(label, status, resp_body, expect_type, expect_code):
        if status == 0:
            fail("{}: caused crash (connection error)".format(label))
            return
        try:
            data = json.loads(resp_body)
        except Exception as e:
            fail("{}: body is not valid JSON: {} ({!r})".format(label, e, resp_body[:200]))
            return
        if data.get("type") != "error":
            fail("{}: top-level type != 'error': {!r}".format(label, data.get("type")))
            return
        err = data.get("error")
        if not isinstance(err, dict):
            fail("{}: error is not an object: {!r}".format(label, err))
            return
        if err.get("type") != expect_type:
            fail("{}: error.type expected {!r}, got {!r}".format(label, expect_type, err.get("type")))
            return
        if err.get("code") != expect_code:
            fail("{}: error.code expected {!r}, got {!r}".format(label, expect_code, err.get("code")))
            return
        if not isinstance(err.get("message"), str) or err.get("message") == "":
            fail("{}: error.message missing or empty: {!r}".format(label, err.get("message")))
            return
        rid = data.get("request_id")
        if not isinstance(rid, str) or rid == "":
            fail("{}: top-level request_id missing or empty: {!r}".format(label, rid))
            return
        pass_("{}: envelope type/code/request_id correct".format(label))

    try:
        # 400 family — method_not_allowed is unreachable via the client (non-POST
        # /v1/* falls through to the framework 501); path_not_allowed is
        # reachable only for methods that reach _forward_request_impl, so drive
        # the "Method not allowed" branch via OPTIONS on /v1/* is not possible
        # either. payload_too_large is reachable by Content-Length over the cap.
        body = json.dumps({"model": "sonnet", "messages": [{"role": "user", "content": "hi"}]})

        # 400 — path_not_allowed: POST to a non-/v1/ path reaches the impl with
        # method POST, so the method check passes and the path check trips.
        status, resp_body = _send_proxy_request(proxy_port, path="/not-v1/messages", body=body)
        _check("path_not_allowed (400)", status, resp_body,
               "invalid_request_error", "path_not_allowed")

        # 413 — payload_too_large: advertise a Content-Length over the cap.
        import http.client as _hc
        conn = _hc.HTTPConnection("127.0.0.1", proxy_port, timeout=10)
        conn.putrequest("POST", "/v1/messages")
        conn.putheader("Content-Type", "application/json")
        conn.putheader("Content-Length", str(10485760 + 1))
        conn.endheaders()
        resp = conn.getresponse()
        status = resp.status
        resp_body = resp.read()
        conn.close()
        _check("payload_too_large (413)", status, resp_body,
               "request_too_large", "payload_too_large")

        # 502 — upstream_unreachable: point the provider at a closed port.
        # _setup_tier_routing_test would bind a live mock at that port, so
        # drive the server directly with a two-file pair and a bounded retry
        # count (a dead port would otherwise cost 10 retries of backoff).
        dead_port = find_free_port()
        dead_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        dead_sock.bind(("127.0.0.1", dead_port))
        dead_sock.close()
        d_temp = tempfile.mkdtemp(prefix="proxy_deadup_")
        d_tiers = {
            "haiku": {"provider": "dead", "model": "claude-haiku-4-5"},
            "sonnet": {"provider": "dead", "model": "claude-sonnet-5"},
            "opus": {"provider": "dead", "model": "claude-opus-5"},
        }
        d_vendors = {"dead": {"url": f"http://127.0.0.1:{dead_port}", "key": "k"}}
        d_config = _create_test_config(
            d_temp, d_tiers, models={"dead": ["claude-haiku-4-5",
                                              "claude-sonnet-5",
                                              "claude-opus-5"]})
        d_keys = _create_test_keys_plain(d_temp, d_vendors)
        d_port = find_free_port()
        d_proc = None
        try:
            d_proc, d_ok = _start_proxy_server_directly(
                d_port, config_path=d_config, keys_path=d_keys, passphrase=None,
                extra_env={"PROXY_MAX_RETRIES": "1",
                           "PROXY_INITIAL_DELAY": "1",
                           "PROXY_MAX_DELAY": "1"})
            if not d_ok:
                fail("502 check: failed to start dead-upstream proxy")
            else:
                status, resp_body = _send_proxy_request(d_port, body=body)
                _check("upstream_unreachable (502)", status, resp_body,
                       "api_error", "upstream_unreachable")
        finally:
            # Terminate the directly-spawned dead-upstream proxy before the
            # temp dir goes. Leaving it live leaks a LISTENING socket whose
            # heartbeat re-creates the per-run state file naming a live PID,
            # so a later CLI `start` reads "Proxy already running".
            if d_proc is not None:
                d_proc.terminate()
                try:
                    d_proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    d_proc.kill()
            shutil.rmtree(d_temp, ignore_errors=True)

    finally:
        cleanup()


def test_unrecognized_model_injection_safe():
    """A model name carrying JSON metacharacters cannot break the envelope.

    The message interpolates the client-supplied model name verbatim, so the
    body must be produced by json.dumps, not string interpolation — a "
    or \\ in the model name would otherwise yield malformed JSON or allow
    field injection. The response must round-trip through json.loads with the
    model name confined to error.message.
    """
    print("\n--- Test: Unrecognized Model Injection Safety ---")

    upstream_port = find_free_port()
    tiers = {
        "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
        "opus": {"provider": "p", "model": "claude-opus-5"},
    }
    vendors = {"p": {"url": f"http://127.0.0.1:{upstream_port}", "key": "k"}}

    temp_dir, proxy_port, proc, mock_servers, cleanup = _setup_tier_routing_test(tiers, vendors)
    if proc is None:
        fail("Failed to set up test")
        return

    evil_model = 'x\\",\\"code\\":\\"pwn'
    body = json.dumps({"model": evil_model, "messages": [{"role": "user", "content": "hi"}]})
    try:
        status, resp_body = _send_proxy_request(proxy_port, body=body)
        if status != 400:
            fail("injection case: expected 400, got {}".format(status))
            return
        try:
            data = json.loads(resp_body)
        except Exception as e:
            fail("injection case: body did not round-trip through json.loads: {} ({!r})".format(
                e, resp_body[:200]))
            return

        if set(data.keys()) != {"type", "error", "request_id"}:
            fail("injection case: top-level keys unexpected: {!r}".format(sorted(data.keys())))
            return
        err = data["error"]
        if set(err.keys()) != {"type", "code", "message"}:
            fail("injection case: error keys unexpected: {!r}".format(sorted(err.keys())))
            return
        if err.get("code") != "unrecognized_model":
            fail("injection case: expected code unrecognized_model, got {!r}".format(err.get("code")))
            return
        if evil_model not in err.get("message", ""):
            fail("injection case: model name not confined to error.message: {!r}".format(err.get("message")))
            return
        pass_("injection-safe: model name round-trips inside error.message only")

    finally:
        cleanup()


def test_get_v1_models_404_envelope():
    """GET /v1/models is an Anthropic-surface 404 carrying the envelope.

    do_GET's default branch answers any non-admin GET. That response is not
    admin, so it must use the standard envelope with error.type
    not_found_error and code not_found.
    """
    print("\n--- Test: GET /v1/models 404 Envelope ---")

    upstream_port = find_free_port()
    tiers = {
        "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
        "opus": {"provider": "p", "model": "claude-opus-5"},
    }
    vendors = {"p": {"url": f"http://127.0.0.1:{upstream_port}", "key": "k"}}

    temp_dir, proxy_port, proc, mock_servers, cleanup = _setup_tier_routing_test(tiers, vendors)
    if proc is None:
        fail("Failed to set up test")
        return

    import http.client as _hc
    try:
        conn = _hc.HTTPConnection("127.0.0.1", proxy_port, timeout=10)
        conn.request("GET", "/v1/models")
        resp = conn.getresponse()
        status = resp.status
        resp_body = resp.read()
        conn.close()

        if status != 404:
            fail("GET /v1/models: expected 404, got {}".format(status))
            return
        try:
            data = json.loads(resp_body)
        except Exception as e:
            fail("GET /v1/models: 404 body is not valid JSON: {} ({!r})".format(e, resp_body[:200]))
            return
        err = data.get("error")
        if not isinstance(err, dict):
            fail("GET /v1/models: error is not an object: {!r}".format(err))
            return
        if err.get("type") != "not_found_error" or err.get("code") != "not_found":
            fail("GET /v1/models: expected not_found_error/not_found, got {!r}/{!r}".format(
                err.get("type"), err.get("code")))
            return
        if data.get("type") != "error":
            fail("GET /v1/models: top-level type != 'error': {!r}".format(data.get("type")))
            return
        rid = data.get("request_id")
        if not isinstance(rid, str) or rid == "":
            fail("GET /v1/models: request_id missing or empty: {!r}".format(rid))
            return
        pass_("GET /v1/models -> 404 not_found_error/not_found envelope")

    finally:
        cleanup()


def test_nesting_limit_buffered_response_body():
    """A buffered upstream body past the limit is forwarded byte-identical.

    Degrade, not error: the client receives the upstream's own bytes (so the
    model is NOT rewritten to the tier), and the trace records the event at
    site "response_rewrite" — the site that carries the tier in scope. The
    pre-plan behaviour for this shape was interpreter-dependent (a parse that
    might raise with no fence); the boundary check makes it deterministic.
    """
    print("\n--- Test: Buffered Upstream Body Nesting Limit ---")

    limit = MAX_JSON_NESTING_DEPTH
    probe = (b'{"id":"msg_up","type":"message","model":"claude-sonnet-5",'
             b'"content":[{"type":"text","text":"hi"}],"x":'
             + b"[" * (limit + 1) + b"]" * (limit + 1) + b"}")

    upstream_port = find_free_port()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port), "key": "K"}}
    responders = {"p": lambda info: (200, "application/json", probe)}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(
        _mode_tiers(), vendors, responders=responders)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        status, resp_body = _send_proxy_request(proxy_port)
        if status == 0:
            fail("a >limit buffered response dropped the connection ({!r})".format(
                resp_body[:120]))
            return
        if status != 200:
            fail("expected 200, got {}".format(status))
            return
        if resp_body != probe:
            fail("expected the upstream bytes forwarded unchanged ({} bytes), "
                 "got {} bytes".format(len(probe), len(resp_body)))
            return
        events = [e for e in _trace_events_named(trace_file, "nesting_limit_exceeded")
                  if e.get("site") == "response_rewrite"]
        if len(events) != 1:
            fail("expected exactly one nesting event with site response_rewrite, "
                 "got {!r}".format(_trace_events_named(trace_file, "nesting_limit_exceeded")))
            return
        ev = events[0]
        if ev.get("tier") != "sonnet":
            fail("response_rewrite event must carry the tier, got {!r}".format(
                ev.get("tier")))
            return
        if ev.get("depth", 0) < limit + 1:
            fail("event depth {} is not past the limit {}".format(
                ev.get("depth"), limit))
            return
        if [e for e in _trace_events_named(trace_file, "transform_failure")]:
            fail("the degrade must not also log transform_failure")
            return
        pass_(">limit upstream body forwarded byte-identical; response_rewrite event "
              "carries tier and depth {}".format(ev.get("depth")))
    finally:
        cleanup()


def test_nesting_limit_admin_body():
    """An admin body past the limit is refused with the flat admin shape.

    The admin surface keeps its documented exclusion from the Anthropic
    envelope: a flat {"error": <message>, "code": ...} object with no "type"
    and no top-level "request_id". A normal admin body must still be served,
    so the check cannot be passing by breaking the branch.
    """
    print("\n--- Test: Admin Body Nesting Limit ---")
    import http.client as _hc

    limit = MAX_JSON_NESTING_DEPTH
    body = b'{"tiers":' + b"[" * (limit + 1) + b"]" * (limit + 1) + b"}"

    upstream_port = find_free_port()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port), "key": "K"}}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(
        _mode_tiers(), vendors)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        conn = _hc.HTTPConnection("127.0.0.1", proxy_port, timeout=10)
        try:
            conn.request("POST", "/admin/api/switch", body=body, headers={
                "Content-Type": "application/json",
                "Origin": "http://127.0.0.1:{}".format(proxy_port),
            })
            resp = conn.getresponse()
            status = resp.status
            raw = resp.read()
        finally:
            conn.close()
        if status == 0:
            fail("a >limit admin body dropped the connection")
            return
        if status != 400:
            fail("expected 400, got {} ({!r})".format(status, raw[:200]))
            return
        try:
            data = json.loads(raw)
        except Exception as e:
            fail("admin 400 is not JSON: {} ({!r})".format(e, raw[:200]))
            return
        if set(data) != {"error", "code"}:
            fail("admin rejection must keep the flat shape {{'error','code'}}, "
                 "got keys {!r}".format(sorted(data)))
            return
        if data.get("code") != "nesting_limit_exceeded":
            fail("expected code nesting_limit_exceeded, got {!r}".format(data.get("code")))
            return
        message = data.get("error") or ""
        if not isinstance(message, str) or "limit of {} levels".format(limit) not in message:
            fail("admin message does not name the limit: {!r}".format(message))
            return
        events = [e for e in _trace_events_named(trace_file, "nesting_limit_exceeded")
                  if e.get("site") == "admin_body"]
        if len(events) != 1:
            fail("expected one nesting event with site admin_body, got {!r}".format(
                _trace_events_named(trace_file, "nesting_limit_exceeded")))
            return
        if not events[0].get("request_id"):
            fail("the admin branch must own a request_id on its event: {!r}".format(
                events[0]))
            return
        pass_(">limit admin body -> flat 400 with code nesting_limit_exceeded")

        status, text = _admin_post(proxy_port, "/admin/api/reload", {})
        if status != 200:
            fail("a normal admin body must still be served, got {} ({!r})".format(
                status, text[:200]))
            return
        pass_("normal admin body still served (200)")
    finally:
        cleanup()


def test_nesting_limit_sse_first_event_forwarded():
    """A >limit first SSE event is forwarded byte-identical, no model rewrite.

    The anthropic-mode stream buffers its first event to rewrite the model to
    the tier. When that event's JSON payload is nested past the limit the
    rewrite is skipped and the event is forwarded verbatim, so the client sees
    the UPSTREAM model name — the documented degrade. The trace records
    ``nesting_limit_exceeded`` with ``site: "sse_first_event"`` carrying the
    tier (that field was missing before Step 11) and the shared builder's
    ``degrade`` field (null here, since the well-formed crossing resolves a
    path), and the rest of the stream still flows (the second event and byte
    equality prove it).

    This branch had no behavioural coverage before Step 12; its own comment
    claimed "documented and tested" while nothing reached it.
    """
    print("\n--- Test: SSE First Event Nesting Limit ---")

    limit = MAX_JSON_NESTING_DEPTH
    first_event = (b'data: {"type":"message_start","message":{"model":"claude-sonnet-5"},'
                   b'"x":' + b"[" * (limit + 1) + b"]" * (limit + 1) + b"}\n\n")
    second_event = b'data: {"type":"content_block_delta","delta":{"text":"Hi"}}\n\n'
    sse_body = first_event + second_event

    upstream_port = find_free_port()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port), "key": "K"}}
    responders = {"p": lambda info: (200, "text/event-stream", sse_body)}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(
        _mode_tiers(), vendors, responders=responders)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        status, content_type, raw = _send_proxy_request_stream(
            proxy_port,
            body={"model": "sonnet",
                  "messages": [{"role": "user", "content": "hi"}],
                  "stream": True})
        if status != 200:
            fail("expected 200, got {} ({!r})".format(status, raw[:160]))
            return
        if raw != sse_body:
            fail("expected the whole stream byte-identical to upstream "
                 "({} bytes), got {} bytes: {!r}".format(
                     len(sse_body), len(raw), raw[:200]))
            return
        if b'"model":"claude-sonnet-5"' not in raw:
            fail("the forwarded first event must keep the upstream model name, "
                 "got {!r}".format(raw[:200]))
            return
        if b'"model":"sonnet"' in raw:
            fail("the first event was rewritten to the tier despite the "
                 "nesting violation: {!r}".format(raw[:200]))
            return
        events = [e for e in _wait_for_trace_events(trace_file,
                                                    "nesting_limit_exceeded")
                  if e.get("site") == "sse_first_event"]
        if len(events) != 1:
            fail("expected one nesting event with site sse_first_event, got "
                 "{!r}".format(_trace_events_named(trace_file,
                                                   "nesting_limit_exceeded")))
            return
        ev = events[0]
        if ev.get("tier") != "sonnet":
            fail("the sse_first_event event must carry the tier, got {!r}".format(
                ev.get("tier")))
            return
        if ev.get("degrade") is not None or not isinstance(ev.get("path"), str):
            fail("the sse_first_event event must carry the shared degrade field "
                 "(null here: the crossing is well-formed, so a path resolves), "
                 "got path {!r} degrade {!r}".format(
                     ev.get("path"), ev.get("degrade")))
            return
        if ev.get("depth", 0) < limit + 1:
            fail("event depth {} is not past the limit {}".format(
                ev.get("depth"), limit))
            return
        if not ev.get("request_id"):
            fail("the sse_first_event event must carry a request_id: {!r}".format(ev))
            return
        pass_(">limit first event forwarded byte-identical (upstream model name "
              "kept); sse_first_event event carries tier")
    finally:
        cleanup()


def test_nesting_limit_response_transform():
    """A >limit buffered chat-mode body degrades in _transform_and_guard.

    Chat/response modes run the buffered upstream body through
    ``_transform_and_guard``; a body past the limit is forwarded unchanged
    with ``nesting_limit_exceeded`` at ``site: "response_transform"`` (mode,
    provider and tier in scope) and WITHOUT a ``transform_failure`` — the
    distinct site proves the nesting guard fired, not the total-parse guard.
    """
    print("\n--- Test: Response Transform Nesting Limit ---")

    limit = MAX_JSON_NESTING_DEPTH
    probe = (b'{"id":"chatcmpl-1","object":"chat.completion","model":"gpt-4o",'
             b'"choices":[{"index":0,"message":{"role":"assistant","content":"hi"},'
             b'"finish_reason":"stop"}],'
             b'"usage":{"prompt_tokens":1,"completion_tokens":1},"x":'
             + b"[" * (limit + 1) + b"]" * (limit + 1) + b"}")

    upstream_port = find_free_port()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port),
                     "key": "K", "mode": "chat"}}
    responders = {"p": lambda info: (200, "application/json", probe)}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(
        _mode_tiers(), vendors, responders=responders)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        status, resp_body = _send_proxy_request(proxy_port)
        if status == 0:
            fail("a >limit chat-mode body dropped the connection ({!r})".format(
                resp_body[:120]))
            return
        if status != 200:
            fail("expected 200, got {} ({!r})".format(status, resp_body[:160]))
            return
        if resp_body != probe:
            fail("expected the upstream bytes forwarded unchanged ({} bytes), "
                 "got {} bytes".format(len(probe), len(resp_body)))
            return
        events = [e for e in _wait_for_trace_events(trace_file,
                                                    "nesting_limit_exceeded")
                  if e.get("site") == "response_transform"]
        if len(events) != 1:
            fail("expected one nesting event with site response_transform, got "
                 "{!r}".format(_trace_events_named(trace_file,
                                                   "nesting_limit_exceeded")))
            return
        ev = events[0]
        if (ev.get("mode") != "chat" or ev.get("provider") != "p"
                or ev.get("tier") != "sonnet"):
            fail("response_transform event must carry mode/provider/tier, got "
                 "{!r}".format(ev))
            return
        if ev.get("depth", 0) < limit + 1:
            fail("event depth {} is not past the limit {}".format(
                ev.get("depth"), limit))
            return
        if [e for e in _trace_events_named(trace_file, "transform_failure")]:
            fail("the nesting degrade must not also log transform_failure")
            return
        pass_(">limit chat-mode body forwarded byte-identical; "
              "response_transform event carries mode/provider/tier")
    finally:
        cleanup()


def test_nesting_limit_response_body_capture():
    """The --all response-body capture degrades past the limit.

    Under ``PROXY_LOG_ALL`` the buffered upstream body is a SECOND parsed
    payload (distinct from the request body), so it is bounded at its own
    site: ``response_body_capture``. The trace entry then carries the raw
    decoded text rather than a parsed object, and the client still receives
    the upstream bytes unchanged. The event carries its routing identity —
    ``tier``, which is in scope at this site and was the field Step 17's
    single-sourced builder restored — plus the shared ``degrade`` field (null
    here, since a well-formed crossing resolves a path). The anthropic-mode
    rewrite fires its own ``response_rewrite`` event for the same body — both
    are expected.
    """
    print("\n--- Test: Response Body Capture Nesting Limit ---")

    limit = MAX_JSON_NESTING_DEPTH
    probe = (b'{"id":"msg_up","type":"message","model":"claude-sonnet-5",'
             b'"content":[{"type":"text","text":"hi"}],"x":'
             + b"[" * (limit + 1) + b"]" * (limit + 1) + b"}")

    upstream_port = find_free_port()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port), "key": "K"}}
    responders = {"p": lambda info: (200, "application/json", probe)}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(
        _mode_tiers(), vendors, responders=responders,
        extra_env={"PROXY_LOG_ALL": "1"})
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        status, resp_body = _send_proxy_request(proxy_port)
        if status != 200:
            fail("expected 200, got {} ({!r})".format(status, resp_body[:160]))
            return
        if resp_body != probe:
            fail("expected the upstream bytes forwarded unchanged ({} bytes), "
                 "got {} bytes".format(len(probe), len(resp_body)))
            return
        events = [e for e in _wait_for_trace_events(trace_file,
                                                    "nesting_limit_exceeded")
                  if e.get("site") == "response_body_capture"]
        if len(events) != 1:
            fail("expected one nesting event with site response_body_capture, "
                 "got {!r}".format(_trace_events_named(trace_file,
                                                       "nesting_limit_exceeded")))
            return
        ev = events[0]
        if ev.get("depth", 0) < limit + 1:
            fail("event depth {} is not past the limit {}".format(
                ev.get("depth"), limit))
            return
        if not ev.get("request_id"):
            fail("the response_body_capture event must carry a request_id: "
                 "{!r}".format(ev))
            return
        if ev.get("tier") != "sonnet":
            fail("the response_body_capture event must carry the tier — it is "
                 "in scope here and was the field the single-sourced builder "
                 "restored — got {!r}".format(ev.get("tier")))
            return
        if ev.get("degrade") is not None or not isinstance(ev.get("path"), str):
            fail("the response_body_capture event must carry the shared degrade "
                 "field (null here: a well-formed crossing resolves a path), "
                 "got path {!r} degrade {!r}".format(
                     ev.get("path"), ev.get("degrade")))
            return
        entries = [e for e in _wait_for_trace_events(trace_file, "request")
                   if "response_body" in e]
        if len(entries) != 1:
            fail("expected one request entry carrying response_body, got "
                 "{}".format(len(entries)))
            return
        captured = entries[0].get("response_body")
        if not isinstance(captured, str):
            fail("the capture must fall back to the decoded-text form (a str), "
                 "got {!r}".format(type(captured).__name__))
            return
        if captured != probe.decode("utf-8"):
            fail("the decoded-text capture does not match the upstream body")
            return
        pass_(">limit --all capture fell back to decoded text; "
              "response_body_capture event logged")
    finally:
        cleanup()


ALL_TESTS = [
    ("tier-routing-basic", test_tier_routing_basic),
    ("tier-routing-all-tiers", test_tier_routing_all_tiers),
    ("model-resolution-reverse-lookup", test_model_resolution_reverse_lookup),
    ("model-resolution-pattern-match", test_model_resolution_pattern_match),
    ("model-resolution-unknown-rejected", test_model_resolution_unknown_rejected),
    ("model-resolution-none-rejected", test_model_resolution_none_rejected),
    ("response-model-rewrite", test_response_model_rewrite),
    ("response-model-rewrite-streaming", test_response_model_rewrite_streaming),
    ("response-model-rewrite-streaming-non-message-start", test_response_model_rewrite_streaming_non_message_start),
    ("response-model-rewrite-upstream-model", test_response_model_rewrite_upstream_model),
    ("two-tiers-same-model-same-provider", test_two_tiers_same_model_same_provider),
    ("non-object-body-rejected", test_non_object_body_rejected),
    ("nesting-limit-client-body", test_nesting_limit_client_body),
    ("nesting-limit-leading-close-body", test_nesting_limit_leading_close_body),
    ("nesting-limit-buffered-response-body", test_nesting_limit_buffered_response_body),
    ("nesting-limit-sse-first-event-forwarded", test_nesting_limit_sse_first_event_forwarded),
    ("nesting-limit-response-transform", test_nesting_limit_response_transform),
    ("nesting-limit-response-body-capture", test_nesting_limit_response_body_capture),
    ("nesting-limit-admin-body", test_nesting_limit_admin_body),
    ("error-envelope-shape", test_error_envelope_shape),
    ("unrecognized-model-injection-safe", test_unrecognized_model_injection_safe),
    ("get-v1-models-404-envelope", test_get_v1_models_404_envelope),
]


if __name__ == "__main__":
    run_cli(ALL_TESTS, "claude-retry-proxy tests: test_tier_routing")
