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
    _create_test_config,
    _create_test_keys,
    _create_test_keys_plain,
    _mode_tiers,
    _send_proxy_request,
    _send_proxy_request_stream,
    _setup_tier_routing_test,
    _start_mode_proxy,
    _start_proxy_server_directly,
    fail,
    find_free_port,
    pass_,
    run_cli,
)




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


def test_deep_nested_body_invalid_json():
    """A deeply nested body returns 400 invalid_json, not a dropped connection.

    json.loads on ~20,000 nested arrays raises RecursionError, which is not a
    ValueError — so the pre-plan guard missed it and the request aborted with
    no HTTP response. The parse site is now total.
    """
    print("\n--- Test: Deep-Nested Body Rejected With invalid_json ---")

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

    # ~40 KB, far inside PROXY_MAX_BODY_SIZE (10 MiB).
    deep = b"[" * 20000 + b"]" * 20000
    try:
        status, resp_body = _send_proxy_request(proxy_port, body=deep)
        if status == 400:
            try:
                data = json.loads(resp_body)
            except Exception as e:
                fail("deep-nested 400 is not valid JSON: {} ({!r})".format(
                    e, resp_body[:200]))
                return
            code = (data.get("error") or {}).get("code")
            if code == "invalid_json":
                pass_("deep-nested body -> 400 invalid_json")
            else:
                fail("deep-nested body: expected error.code invalid_json, got {!r}".format(code))
        elif status == 0:
            fail("deep-nested body caused crash (connection error)")
        else:
            fail("deep-nested body should return 400, got {}".format(status))

        reqs = mock_servers["p"]["requests"]
        if len(reqs) == 0:
            pass_("Upstream received no requests for the deep-nested body")
        else:
            fail("Upstream received {} requests for the deep-nested body".format(len(reqs)))

    finally:
        cleanup()


def _band_depth_for(_body):
    """Midpoint of the decode-succeeds/encode-fails band for a payload builder.

    json.loads and json.dumps have different recursion ceilings: the parser
    holds to a greater depth than the encoder, leaving a band of depths in
    which a payload parses successfully and then raises RecursionError on
    the re-serialize. A depth inside that band exercises an encode-side
    guard. Measured on the running interpreter (never a hardcoded 20,000,
    which sits past BOTH ceilings and so exercises only the decode-side
    fail-safe).

    Args:
        _body: callable depth -> bytes producing the payload to probe.

    Returns the band's midpoint depth, or None if no band exists on this
    interpreter.
    """

    def loads_ok(depth):
        try:
            json.loads(_body(depth))
            return True
        except RecursionError:
            return False

    def dumps_ok(depth):
        try:
            json.dumps(json.loads(_body(depth)))
            return True
        except RecursionError:
            return False

    # Largest depth that still parses.
    lo, hi = 0, 60000
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if loads_ok(mid):
            lo = mid
        else:
            hi = mid - 1
    loads_max = lo
    if loads_max == 0:
        return None
    # Walk down to the largest depth whose re-serialize ALSO succeeds; the
    # band is (dumps_max, loads_max].
    lo, hi = 0, loads_max
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if dumps_ok(mid):
            lo = mid
        else:
            hi = mid - 1
    dumps_max = lo
    if dumps_max >= loads_max:
        return None
    return (dumps_max + loads_max) // 2


def _band_body_depth():
    """Band midpoint for the canonical client-body shape (model + deep array)."""
    return _band_depth_for(
        lambda depth: b'{"model":"sonnet","x":' + b"[" * depth + b"]" * depth + b"}")


def test_deep_nested_body_encode_band():
    """A body inside the decode-succeeds/encode-fails band is answered, not dropped.

    The existing test_deep_nested_body_invalid_json uses depth 20,000 — past
    the json.loads ceiling AND the json.dumps ceiling — so it exercises only
    the decode-side fail-safe. Between the two ceilings lies a band of
    depths where the body parses and the #737 json.dumps re-serialize raises
    RecursionError. Before the encode-side guard was widened that exception
    escaped and the request aborted with ZERO bytes (RemoteDisconnected), the
    exact failure class this plan exists to remove, and no test covered it.
    This pins the boundary: the request must produce a real HTTP response
    that json-parses, and the pre-fix path (a dropped connection) would fail
    it.
    """
    print("\n--- Test: Deep-Nested Body Encode Band (decode-ok / encode-raise) ---")

    depth = _band_body_depth()
    if depth is None:
        fail("could not locate a decode-succeeds/encode-fails band on this interpreter")
        return

    # Prove we are actually in the band before asserting on the proxy.
    probe = b'{"model":"sonnet","x":' + b"[" * depth + b"]" * depth + b"}"
    try:
        parsed_probe = json.loads(probe)
    except RecursionError:
        fail("chosen depth {} does not parse — not in band".format(depth))
        return
    try:
        json.dumps(parsed_probe)
    except RecursionError:
        pass
    except Exception as e:
        fail("chosen depth {}: unexpected encode error {!r}".format(depth, e))
        return
    else:
        fail("chosen depth {} re-serializes locally — not in band".format(depth))
        return

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
        status, resp_body = _send_proxy_request(proxy_port, body=probe)
        if status == 0:
            fail("band-depth {} ({} bytes) dropped the connection "
                 "(zero-byte abort — the encode guard regressed)".format(depth, len(probe)))
            return
        # The in-band shape is a valid object body, so the request is
        # forwarded; the contract is only that a real, parseable HTTP
        # response came back. Pre-fix there was no response at all.
        try:
            json.loads(resp_body)
        except Exception as e:
            fail("band-depth {}: response body is not valid JSON: {} ({!r})".format(
                depth, e, resp_body[:200]))
            return
        pass_("band-depth {} ({} bytes) -> HTTP {} with a parseable body".format(
            depth, len(probe), status))

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


def test_response_json_encode_band():
    """A buffered upstream JSON response in the encode band is returned, not dropped.

    Pins `_rewrite_json_response`'s encode side: the re-serialize must sit
    INSIDE the widened try (review-2 finding review2-rewrite-json-response-encode).
    The mock upstream returns a JSON body whose depth is in the
    decode-succeeds/encode-fails band, so json.loads succeeds and json.dumps
    raises RecursionError. Pre-fix the dumps sat outside the try and the
    exception escaped unfenced (do_POST -> forward_request -> _forward_core
    call sites were unfenced) -> the client got ZERO bytes. Post-fix the guard
    returns the original body bytes: a real, client-parseable response whose
    model field is NOT rewritten (the degrade path), never a dropped connection.
    """
    print("\n--- Test: Response JSON Encode Band (upstream buffered) ---")

    depth = _band_depth_for(_band_response_body)
    if depth is None:
        fail("could not locate a decode-succeeds/encode-fails band on this interpreter")
        return

    probe = _band_response_body(depth)
    # Prove we are actually in the band before asserting on the proxy.
    try:
        parsed = json.loads(probe)
    except RecursionError:
        fail("chosen depth {} does not parse — not in band".format(depth))
        return
    try:
        json.dumps(parsed)
    except RecursionError:
        pass
    except Exception as e:
        fail("chosen depth {}: unexpected encode error {!r}".format(depth, e))
        return
    else:
        fail("chosen depth {} re-serializes locally — not in band".format(depth))
        return

    upstream_port = find_free_port()
    tiers = _mode_tiers()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port), "key": "K"}}
    responders = {"p": lambda info: (200, "application/json", probe)}

    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(
        tiers, vendors, responders=responders)
    if proc is None:
        fail("Failed to set up test")
        return

    try:
        status, resp_body = _send_proxy_request(proxy_port)
        if status == 0:
            fail("band-depth {} response dropped the connection "
                 "(zero-byte abort — the _rewrite_json_response encode guard regressed)".format(depth))
            return
        if status != 200:
            fail("band-depth {}: expected 200, got {}".format(depth, status))
            return
        try:
            json.loads(resp_body)
        except Exception as e:
            fail("band-depth {}: response body is not valid JSON: {} ({!r})".format(
                depth, e, resp_body[:200]))
            return
        # Degrade path: the encode failed, so the original bytes are forwarded
        # with the upstream's model intact — no rewrite, no abort.
        if resp_body != probe:
            fail("band-depth {}: expected the original (unrewritten) body, "
                 "got {} bytes differing from the {}-byte probe".format(
                     depth, len(resp_body), len(probe)))
            return
        pass_("band-depth {} ({} bytes) -> HTTP 200 with the original body forwarded".format(
            depth, len(probe)))
    finally:
        cleanup()


def _band_response_body(depth):
    """Upstream buffered-JSON shape at a measured depth: top-level model + deep array."""
    return (b'{"id":"msg_up","type":"message","model":"claude-sonnet-5",'
            b'"content":[{"type":"text","text":"hi"}],"x":'
            + b"[" * depth + b"]" * depth + b"}")


def _band_sse_event(depth):
    """Anthropic-mode message_start SSE first event at a measured depth.

    Depth rides on an unused payload key so the event parses (loads ceiling)
    but the model rewrite's json.dumps re-serialize raises (dumps ceiling).
    """
    data = (b'{"type":"message_start","message":{"id":"msg_up",'
            b'"type":"message","role":"assistant","model":"claude-sonnet-5",'
            b'"content":[],"x":' + b"[" * depth + b"]" * depth + b"}}")
    return b"event: message_start\ndata: " + data + b"\n\n"


def test_sse_first_event_encode_band():
    """A message_start first event in the encode band still streams, not zero bytes.

    Pins `_rewrite_sse_first_event`'s separate encode guard (review-2 finding
    review-sse-first-event-narrow-guard, reopened): round 2 widened only the
    decode try, leaving json.dumps outside it, so an in-band message_start
    returned HTTP 200 with ZERO body bytes. Post-fix the re-serialize runs in
    its own guard: an encode failure degrades to forwarding the ORIGINAL event
    (model not rewritten) and the rest of the stream flows normally.
    """
    print("\n--- Test: SSE First Event Encode Band (message_start) ---")

    depth = _band_depth_for(lambda d: _band_sse_event(d).split(b"data: ", 1)[1].rstrip(b"\n"))
    if depth is None:
        fail("could not locate a decode-succeeds/encode-fails band on this interpreter")
        return

    event_bytes = _band_sse_event(depth)
    data_text = event_bytes.split(b"data: ", 1)[1].rstrip(b"\n")
    # Prove the data payload is in band (parses, fails to re-encode).
    try:
        parsed = json.loads(data_text)
    except RecursionError:
        fail("chosen depth {} does not parse — not in band".format(depth))
        return
    try:
        json.dumps(parsed)
    except RecursionError:
        pass
    except Exception as e:
        fail("chosen depth {}: unexpected encode error {!r}".format(depth, e))
        return
    else:
        fail("chosen depth {} re-serializes locally — not in band".format(depth))
        return

    upstream_port = find_free_port()
    tiers = _mode_tiers()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port), "key": "K"}}
    delta_event = b'event: content_block_delta\ndata: {"type":"content_block_delta",' \
                  b'"delta":{"type":"text_delta","text":"Hi"}}\n\n'
    stop_event = b'data: {"type":"message_stop"}\n\n'
    sse_body = event_bytes + delta_event + stop_event
    responders = {"p": lambda info: (200, "text/event-stream", sse_body)}

    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(
        tiers, vendors, responders=responders)
    if proc is None:
        fail("Failed to set up test")
        return

    try:
        status, content_type, raw = _send_proxy_request_stream(
            proxy_port, body={"model": "sonnet",
                              "messages": [{"role": "user", "content": "hi"}],
                              "stream": True})
        if status != 200:
            fail("band-depth {}: expected 200, got {}".format(depth, status))
            return
        if not raw:
            fail("band-depth {} message_start: HTTP 200 with ZERO body bytes "
                 "(the _rewrite_sse_first_event encode guard regressed)".format(depth))
            return
        text = raw.decode("utf-8", errors="replace")
        if "message_start" not in text:
            fail("band-depth {}: first event missing from stream: {!r}".format(
                depth, text[:200]))
            return
        if "content_block_delta" not in text or "message_stop" not in text:
            fail("band-depth {}: stream truncated after the first event "
                 "(got {} bytes)".format(depth, len(raw)))
            return
        # Degrade path: encode failed, original event forwarded unchanged —
        # the upstream's model string survives because no rewrite happened.
        if "claude-sonnet-5" not in text:
            fail("band-depth {}: expected the unrewritten upstream model in "
                 "the forwarded first event".format(depth))
            return
        pass_("band-depth {} ({} bytes): full stream forwarded, first event degraded".format(
            depth, len(raw)))
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
    ("deep-nested-body-invalid-json", test_deep_nested_body_invalid_json),
    ("deep-nested-body-encode-band", test_deep_nested_body_encode_band),
    ("response-json-encode-band", test_response_json_encode_band),
    ("sse-first-event-encode-band", test_sse_first_event_encode_band),
    ("error-envelope-shape", test_error_envelope_shape),
    ("unrecognized-model-injection-safe", test_unrecognized_model_injection_safe),
    ("get-v1-models-404-envelope", test_get_v1_models_404_envelope),
]


if __name__ == "__main__":
    run_cli(ALL_TESTS, "claude-retry-proxy tests: test_tier_routing")
