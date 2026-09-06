"""Mode-dispatch tests: vendor mode resolution, auth/path dispatch by
mode, count_tokens rejection, mode e2e flows, passthrough, and
no-double-transform regressions.

Part of the claude-retry-proxy suite; runnable standalone.
"""

import json
import os

from _harness import (
    _mode_default_responder,
    _mode_tiers,
    _require_server_func,
    _send_proxy_request,
    _start_mode_proxy,
    errors,
    fail,
    find_free_port,
    info,
    pass_,
    run_cli,
)




# --- Step 1: mode read from vendor entry ---

def test_mode_defaults_to_anthropic():
    """Vendor without a mode field is treated as anthropic (x-api-key used)."""
    print("\n--- Test: Mode Defaults To Anthropic ---")
    upstream_port = find_free_port()
    tiers = _mode_tiers()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port), "key": "K-1"}}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(tiers, vendors)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        status, body = _send_proxy_request(proxy_port)
        if status != 200:
            fail("expected 200, got {}".format(status))
            return
        reqs = mock_servers["p"]["requests"]
        if not reqs:
            fail("upstream received no requests")
            return
        if reqs[0]["api_key"] != "K-1":
            fail("expected x-api-key=K-1 (anthropic default), got {!r}".format(reqs[0]["api_key"]))
        else:
            pass_("vendor without mode uses x-api-key (anthropic default)")
    finally:
        cleanup()




def test_mode_null_defaults_to_anthropic():
    """Vendor with mode: null is treated as anthropic."""
    print("\n--- Test: Mode Null Defaults To Anthropic ---")
    upstream_port = find_free_port()
    tiers = _mode_tiers()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port), "key": "K-2", "mode": None}}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(tiers, vendors)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        status, body = _send_proxy_request(proxy_port)
        if status != 200:
            fail("expected 200, got {}".format(status))
            return
        reqs = mock_servers["p"]["requests"]
        if not reqs:
            fail("upstream received no requests")
            return
        if reqs[0]["api_key"] != "K-2":
            fail("expected x-api-key with mode=null (anthropic default), got {!r}".format(reqs[0]["api_key"]))
        else:
            pass_("vendor with mode:null uses x-api-key")
    finally:
        cleanup()




def test_mode_invalid_rejected():
    """Vendor with an unknown mode returns 500 invalid_provider_mode."""
    print("\n--- Test: Mode Invalid Rejected ---")
    upstream_port = find_free_port()
    tiers = _mode_tiers()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port), "key": "K-3", "mode": "watermelon"}}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(tiers, vendors)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        status, body = _send_proxy_request(proxy_port)
        if status != 500:
            fail("expected 500 for invalid mode, got {}".format(status))
        elif b"invalid_provider_mode" not in body:
            fail("expected invalid_provider_mode in error body, got {}".format(body.decode(errors="replace")))
        else:
            pass_("invalid mode returns 500 invalid_provider_mode")
    finally:
        cleanup()




# --- Step 2: auth header dispatch by mode ---

def test_auth_header_anthropic_mode():
    """Anthropic mode forwards with x-api-key, no Authorization header, and
    forwards the anthropic-beta header to upstream."""
    print("\n--- Test: Auth Header Anthropic Mode ---")
    upstream_port = find_free_port()
    tiers = _mode_tiers()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port), "key": "auth-K-ant"}}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(tiers, vendors)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        import http.client as _hc
        conn = _hc.HTTPConnection("127.0.0.1", proxy_port, timeout=10)
        conn.request(
            "POST", "/v1/messages",
            body=json.dumps({"model": "sonnet",
                             "messages": [{"role": "user", "content": "hi"}]}),
            headers={"Content-Type": "application/json",
                     "anthropic-beta": "context-management-2025-06-27"})
        resp = conn.getresponse()
        status = resp.status
        resp.read()
        conn.close()
        if status != 200:
            fail("expected 200, got {}".format(status))
            return
        reqs = mock_servers["p"]["requests"]
        if not reqs:
            fail("upstream received no requests")
            return
        r = reqs[0]
        if r["api_key"] != "auth-K-ant":
            fail("anthropic mode: expected x-api-key=auth-K-ant, got {!r}".format(r["api_key"]))
        if r["authorization"] != "":
            fail("anthropic mode: expected no Authorization header, got {!r}".format(r["authorization"]))
        if r["api_key"] == "auth-K-ant" and r["authorization"] == "":
            pass_("anthropic mode uses x-api-key and drops Authorization")
        if r["anthropic_beta"] != "context-management-2025-06-27":
            fail("anthropic-beta header not forwarded to upstream, got {!r}".format(r["anthropic_beta"]))
        else:
            pass_("anthropic-beta header forwarded to upstream")
    finally:
        cleanup()




def test_auth_header_chat_mode():
    """Chat mode forwards with Authorization: Bearer, no x-api-key."""
    print("\n--- Test: Auth Header Chat Mode ---")
    upstream_port = find_free_port()
    tiers = _mode_tiers()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port), "key": "auth-K-chat", "mode": "chat"}}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(tiers, vendors)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        status, body = _send_proxy_request(proxy_port)
        if status != 200:
            fail("expected 200, got {}".format(status))
            return
        reqs = mock_servers["p"]["requests"]
        if not reqs:
            fail("upstream received no requests")
            return
        r = reqs[0]
        if r["authorization"] != "Bearer auth-K-chat":
            fail("chat mode: expected 'Authorization: Bearer auth-K-chat', got {!r}".format(r["authorization"]))
        if r["api_key"] != "":
            fail("chat mode: expected no x-api-key, got {!r}".format(r["api_key"]))
        if r["authorization"] == "Bearer auth-K-chat" and r["api_key"] == "":
            pass_("chat mode uses Authorization: Bearer")
    finally:
        cleanup()




def test_auth_header_response_mode():
    """Response mode forwards with Authorization: Bearer, no x-api-key."""
    print("\n--- Test: Auth Header Response Mode ---")
    upstream_port = find_free_port()
    tiers = _mode_tiers()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port), "key": "auth-K-resp", "mode": "response"}}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(tiers, vendors)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        status, body = _send_proxy_request(proxy_port)
        if status != 200:
            fail("expected 200, got {}".format(status))
            return
        reqs = mock_servers["p"]["requests"]
        if not reqs:
            fail("upstream received no requests")
            return
        r = reqs[0]
        if r["authorization"] != "Bearer auth-K-resp":
            fail("response mode: expected 'Authorization: Bearer auth-K-resp', got {!r}".format(r["authorization"]))
        if r["api_key"] != "":
            fail("response mode: expected no x-api-key, got {!r}".format(r["api_key"]))
        if r["authorization"] == "Bearer auth-K-resp" and r["api_key"] == "":
            pass_("response mode uses Authorization: Bearer")
    finally:
        cleanup()




# --- Step 3: path construction by mode ---

def test_path_anthropic_mode():
    """Anthropic mode appends the original request path to the upstream URL."""
    print("\n--- Test: Path Anthropic Mode ---")
    upstream_port = find_free_port()
    tiers = _mode_tiers()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port), "key": "K"}}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(tiers, vendors)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        status, body = _send_proxy_request(proxy_port)
        if status != 200:
            fail("expected 200, got {}".format(status))
            return
        reqs = mock_servers["p"]["requests"]
        if not reqs:
            fail("upstream received no requests")
            return
        if reqs[0]["path"] != "/v1/messages":
            fail("anthropic mode: expected upstream path /v1/messages, got {!r}".format(reqs[0]["path"]))
        else:
            pass_("anthropic mode forwards the original request path")
    finally:
        cleanup()




def test_path_chat_mode():
    """Chat mode upstream path is path_prefix + /v1/chat/completions."""
    print("\n--- Test: Path Chat Mode ---")
    upstream_port = find_free_port()
    tiers = _mode_tiers()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port), "key": "K", "mode": "chat"}}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(tiers, vendors)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        status, body = _send_proxy_request(proxy_port)
        if status != 200:
            fail("expected 200, got {}".format(status))
            return
        reqs = mock_servers["p"]["requests"]
        if not reqs:
            fail("upstream received no requests")
            return
        if reqs[0]["path"] != "/v1/chat/completions":
            fail("chat mode: expected upstream path /v1/chat/completions, got {!r}".format(reqs[0]["path"]))
        else:
            pass_("chat mode upstream path ends in /v1/chat/completions")
    finally:
        cleanup()




def test_path_response_mode():
    """Response mode upstream path is path_prefix + /v1/responses."""
    print("\n--- Test: Path Response Mode ---")
    upstream_port = find_free_port()
    tiers = _mode_tiers()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port), "key": "K", "mode": "response"}}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(tiers, vendors)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        status, body = _send_proxy_request(proxy_port)
        if status != 200:
            fail("expected 200, got {}".format(status))
            return
        reqs = mock_servers["p"]["requests"]
        if not reqs:
            fail("upstream received no requests")
            return
        if reqs[0]["path"] != "/v1/responses":
            fail("response mode: expected upstream path /v1/responses, got {!r}".format(reqs[0]["path"]))
        else:
            pass_("response mode upstream path ends in /v1/responses")
    finally:
        cleanup()




def test_path_double_v1_prevention():
    """A vendor URL ending in /v1 must not produce a /v1/v1/ upstream path."""
    print("\n--- Test: Path Double V1 Prevention ---")
    upstream_port = find_free_port()
    tiers = _mode_tiers()
    vendors = {"p": {"url": "http://127.0.0.1:{}/v1".format(upstream_port), "key": "K", "mode": "chat"}}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(tiers, vendors)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        status, body = _send_proxy_request(proxy_port)
        if status != 200:
            fail("expected 200, got {}".format(status))
            return
        reqs = mock_servers["p"]["requests"]
        if not reqs:
            fail("upstream received no requests")
            return
        p = reqs[0]["path"]
        if p == "/v1/v1/chat/completions":
            fail("chat mode produced double /v1/v1 upstream path: {!r}".format(p))
        elif p != "/v1/chat/completions":
            fail("expected /v1/chat/completions, got {!r}".format(p))
        else:
            pass_("trailing /v1 in vendor URL is not duplicated: {}".format(p))
    finally:
        cleanup()




def test_count_tokens_rejected_chat_mode():
    """count_tokens returns 400 in chat mode."""
    print("\n--- Test: Count Tokens Rejected Chat Mode ---")
    upstream_port = find_free_port()
    tiers = _mode_tiers()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port), "key": "K", "mode": "chat"}}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(tiers, vendors)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        status, body = _send_proxy_request(
            proxy_port, path="/v1/messages/count_tokens",
            body=json.dumps({"model": "sonnet"}))
        if status != 400:
            fail("chat mode count_tokens: expected 400, got {}".format(status))
        elif b"count_tokens" not in body:
            fail("expected count_tokens rejection message, got {}".format(body.decode(errors="replace")))
        else:
            pass_("chat mode rejects count_tokens with 400")
    finally:
        cleanup()




def test_count_tokens_rejected_response_mode():
    """count_tokens returns 400 in response mode."""
    print("\n--- Test: Count Tokens Rejected Response Mode ---")
    upstream_port = find_free_port()
    tiers = _mode_tiers()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port), "key": "K", "mode": "response"}}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(tiers, vendors)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        status, body = _send_proxy_request(
            proxy_port, path="/v1/messages/count_tokens",
            body=json.dumps({"model": "sonnet"}))
        if status != 400:
            fail("response mode count_tokens: expected 400, got {}".format(status))
        elif b"count_tokens" not in body:
            fail("expected count_tokens rejection message, got {}".format(body.decode(errors="replace")))
        else:
            pass_("response mode rejects count_tokens with 400")
    finally:
        cleanup()




# --- Step 4: _anthropic_to_chat ---

def test_anthropic_to_chat_basic():
    """messages, model, max_tokens, temperature map through."""
    print("\n--- Test: Anthropic To Chat Basic ---")
    fn = _require_server_func("_anthropic_to_chat")
    if fn is None:
        return
    inp = {"model": "sonnet",
           "messages": [{"role": "user", "content": "hi"}],
           "max_tokens": 100,
           "temperature": 0.5}
    out = fn(dict(inp))
    if not isinstance(out, dict):
        fail("_anthropic_to_chat must return a dict, got {!r}".format(type(out)))
        return
    checks = [
        (out.get("model") == "sonnet", "model pass-through"),
        (out.get("messages") == [{"role": "user", "content": "hi"}], "messages pass-through"),
        (out.get("max_tokens") == 100, "max_tokens pass-through"),
        (out.get("temperature") == 0.5, "temperature pass-through"),
    ]
    for ok, label in checks:
        if not ok:
            fail("basic mapping failed: {}".format(label))
    if all(ok for ok, _ in checks):
        pass_("anthropic->chat basic mapping correct")




def test_anthropic_to_chat_system_string():
    """system string becomes the first system message."""
    print("\n--- Test: Anthropic To Chat System String ---")
    fn = _require_server_func("_anthropic_to_chat")
    if fn is None:
        return
    inp = {"model": "sonnet", "system": "You are helpful",
           "messages": [{"role": "user", "content": "hi"}]}
    out = fn(inp)
    msgs = out.get("messages")
    if not isinstance(msgs, list) or len(msgs) < 2:
        fail("expected system message prepended to messages")
    elif not isinstance(msgs[0], dict) or msgs[0].get("role") != "system" or msgs[0].get("content") != "You are helpful":
        fail("expected first message to be the system message, got {!r}".format(msgs[0]))
    else:
        pass_("system string prepended as system message")




def test_anthropic_to_chat_system_list():
    """system content blocks are concatenated with newlines; non-text dropped."""
    print("\n--- Test: Anthropic To Chat System List ---")
    fn = _require_server_func("_anthropic_to_chat")
    if fn is None:
        return
    inp = {"model": "sonnet",
           "system": [{"type": "text", "text": "First"},
                      {"type": "text", "text": "Second"},
                      {"type": "image", "source": {"type": "base64", "data": "x"}}],
           "messages": [{"role": "user", "content": "hi"}]}
    out = fn(inp)
    msgs = out.get("messages")
    if not isinstance(msgs, list) or not msgs:
        fail("messages missing from output")
        return
    if msgs[0].get("role") != "system" or msgs[0].get("content") != "First\nSecond":
        fail("expected system message content 'First\\nSecond', got {!r}".format(msgs[0]))
    if len(msgs) != 2:
        fail("expected exactly user message after system (image block dropped), got {} messages".format(len(msgs)))
    if msgs[0].get("role") == "system" and msgs[0].get("content") == "First\nSecond" and len(msgs) == 2:
        pass_("system list concatenated; non-text blocks dropped")




def test_anthropic_to_chat_dropped_fields():
    """thinking, metadata, top_k absent; tools and tool_choice now transformed (plan 2026-08-29)."""
    print("\n--- Test: Anthropic To Chat Dropped Fields ---")
    fn = _require_server_func("_anthropic_to_chat")
    if fn is None:
        return
    inp = {"model": "sonnet",
           "messages": [{"role": "user", "content": "hi"}],
           "thinking": {"type": "enabled", "budget_tokens": 100},
           "tools": [{"name": "t", "input_schema": {}}],
           "tool_choice": {"type": "auto"},
           "metadata": {"user_id": "x"},
           "top_k": 5}
    out = fn(inp)
    for key in ("thinking", "metadata", "top_k"):
        if key in out:
            fail("expected {!r} dropped from output, present: {}".format(key, sorted(out.keys())))
    if "messages" not in out:
        fail("messages missing from output")
    if out.get("tools") != [{"type": "function", "function": {"name": "t", "parameters": {}}}]:
        fail("expected transformed tools, got {!r}".format(out.get("tools")))
    if out.get("tool_choice") != "auto":
        fail("expected tool_choice 'auto' (transformed), got {!r}".format(out.get("tool_choice")))
    if (all(key not in out for key in ("thinking", "metadata", "top_k"))
            and "messages" in out
            and out.get("tools") == [{"type": "function", "function": {"name": "t", "parameters": {}}}]
            and out.get("tool_choice") == "auto"):
        pass_("thinking/metadata/top_k dropped; tools/tool_choice transformed")




def test_anthropic_to_chat_stop_sequences():
    """stop_sequences is renamed to stop."""
    print("\n--- Test: Anthropic To Chat Stop Sequences ---")
    fn = _require_server_func("_anthropic_to_chat")
    if fn is None:
        return
    inp = {"model": "sonnet",
           "messages": [{"role": "user", "content": "hi"}],
           "stop_sequences": ["END", "</s>"]}
    out = fn(inp)
    if "stop_sequences" in out:
        fail("stop_sequences should be renamed, still present")
    if out.get("stop") != ["END", "</s>"]:
        fail("expected stop=['END', '</s>'], got {!r}".format(out.get("stop")))
    if "stop_sequences" not in out and out.get("stop") == ["END", "</s>"]:
        pass_("stop_sequences renamed to stop")




# --- Step 9: wiring / e2e ---

def test_chat_mode_e2e_json():
    """End-to-end chat mode request/response through the live proxy."""
    print("\n--- Test: Chat Mode E2E JSON ---")
    upstream_port = find_free_port()
    tiers = _mode_tiers()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port), "key": "K", "mode": "chat"}}
    chat_ok = json.dumps({
        "id": "chatcmpl-1", "object": "chat.completion", "created": 1, "model": "gpt-4o",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "Hello"},
                     "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
    }).encode()
    responders = {"p": lambda info: (200, "application/json", chat_ok)}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(tiers, vendors, responders=responders)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        status, body = _send_proxy_request(proxy_port)
        if status != 200:
            fail("expected 200, got {}".format(status))
            return
        try:
            data = json.loads(body)
        except Exception:
            fail("response is not valid JSON: {!r}".format(body[:200]))
            return
        if data.get("type") != "message" or data.get("role") != "assistant":
            fail("response not anthropic-shaped: {!r}".format(data))
        if data.get("model") != "sonnet":
            fail("expected model tier 'sonnet', got {!r}".format(data.get("model")))
        if data.get("content") != [{"type": "text", "text": "Hello"}]:
            fail("expected content [text Hello], got {!r}".format(data.get("content")))
        if data.get("stop_reason") != "end_turn":
            fail("expected stop_reason end_turn, got {!r}".format(data.get("stop_reason")))
        reqs = mock_servers["p"]["requests"]
        if not reqs:
            fail("upstream received no requests")
            return
        try:
            upstream_body = json.loads(reqs[0]["body"])
        except Exception:
            fail("upstream request body is not JSON: {!r}".format(reqs[0]["body"][:200]))
            return
        if upstream_body.get("model") != "claude-sonnet-5":
            fail("upstream should receive the actual model name, got {!r}".format(upstream_body.get("model")))
        if not isinstance(upstream_body.get("messages"), list):
            fail("upstream should receive messages array, got {!r}".format(upstream_body.get("messages")))
        if data.get("type") == "message" and data.get("content") == [{"type": "text", "text": "Hello"}] and isinstance(upstream_body.get("messages"), list):
            pass_("chat mode e2e transform round-trips")
    finally:
        cleanup()




def test_response_mode_e2e_json():
    """End-to-end response mode request/response through the live proxy."""
    print("\n--- Test: Response Mode E2E JSON ---")
    upstream_port = find_free_port()
    tiers = _mode_tiers()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port), "key": "K", "mode": "response"}}
    resp_ok = json.dumps({
        "id": "resp_1", "object": "response", "created_at": 1, "model": "gpt-4o",
        "status": "completed",
        "output": [{"type": "message", "role": "assistant",
                    "content": [{"type": "output_text", "text": "Hello", "annotations": []}]}],
        "usage": {"input_tokens": 4, "output_tokens": 2, "total_tokens": 6},
    }).encode()
    responders = {"p": lambda info: (200, "application/json", resp_ok)}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(tiers, vendors, responders=responders)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        body = json.dumps({"model": "sonnet",
                           "system": "Be concise",
                           "messages": [{"role": "user", "content": "one"},
                                        {"role": "assistant", "content": "two"},
                                        {"role": "user", "content": "three"}],
                           "stream": True})
        status, resp_body = _send_proxy_request(proxy_port, body=body)
        if status != 200:
            fail("expected 200, got {}".format(status))
            return
        try:
            data = json.loads(resp_body)
        except Exception:
            fail("response is not valid JSON: {!r}".format(resp_body[:200]))
            return
        if data.get("model") != "sonnet":
            fail("expected model tier 'sonnet', got {!r}".format(data.get("model")))
        if data.get("content") != [{"type": "text", "text": "Hello"}]:
            fail("expected content [text Hello], got {!r}".format(data.get("content")))
        reqs = mock_servers["p"]["requests"]
        if not reqs:
            fail("upstream received no requests")
            return
        try:
            ubody = json.loads(reqs[0]["body"])
        except Exception:
            fail("upstream request body not JSON: {!r}".format(reqs[0]["body"][:200]))
            return
        if ubody.get("stream") is not False:
            fail("upstream should receive stream=false, got {!r}".format(ubody.get("stream")))
        expected_input = [
            {"type": "message", "role": "user",
             "content": [{"type": "input_text", "text": "one"}]},
            {"type": "message", "role": "assistant",
             "content": [{"type": "output_text", "text": "two"}]},
            {"type": "message", "role": "user",
             "content": [{"type": "input_text", "text": "three"}]},
        ]
        if ubody.get("input") != expected_input:
            fail("upstream input should be full history items, got {!r}".format(ubody.get("input")))
        if ubody.get("instructions") != "Be concise":
            fail("upstream instructions mismatch: {!r}".format(ubody.get("instructions")))
        if "messages" in ubody:
            fail("upstream body should drop messages, got {!r}".format(sorted(ubody.keys())))
        if (data.get("model") == "sonnet"
                and data.get("content") == [{"type": "text", "text": "Hello"}]
                and "messages" not in ubody
                and ubody.get("input") == expected_input):
            pass_("response mode e2e transform round-trips")
    finally:
        cleanup()




def test_response_mode_assistant_output_text_e2e():
    """E2E: schema-validating mock upstream enforces role-appropriate content types.

    The mock rejects any Responses input item whose content type does not match
    its role (assistant must use output_text, non-assistant input_text) with a
    400; the proxy's transformed request must pass validation.
    """
    print("\n--- Test: Response Mode Assistant Output Text E2E ---")
    upstream_port = find_free_port()
    tiers = _mode_tiers()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port), "key": "K",
                     "mode": "response"}}
    state = {"parse_ok": False, "validated_items": 0, "violations": []}
    resp_ok = json.dumps({
        "id": "resp_1", "object": "response", "created_at": 1, "model": "gpt-4o",
        "status": "completed",
        "output": [{"type": "message", "role": "assistant",
                    "content": [{"type": "output_text", "text": "ok",
                                 "annotations": []}]}],
        "usage": {"input_tokens": 4, "output_tokens": 2, "total_tokens": 6},
    }).encode()

    def responder(info):
        try:
            ubody = json.loads(info["body"])
        except Exception:
            state["parse_ok"] = False
            err = json.dumps({"error": {"message": "schema validation failed: "
                                                  "body not JSON"}}).encode()
            return 400, "application/json", err
        state["parse_ok"] = True
        for item in ubody.get("input", []):
            if not isinstance(item, dict) or item.get("type") != "message":
                continue
            role = item.get("role")
            expected_ct = "output_text" if role == "assistant" else "input_text"
            state["validated_items"] += 1
            for block in item.get("content", []):
                if isinstance(block, dict) and block.get("type") != expected_ct:
                    state["violations"].append(
                        "role {!r} has block type {!r}, expected {!r}".format(
                            role, block.get("type"), expected_ct))
        if state["violations"]:
            err = json.dumps({"error": {"message": "schema validation failed: "
                                                   + "; ".join(state["violations"])}}).encode()
            return 400, "application/json", err
        return 200, "application/json", resp_ok

    responders = {"p": responder}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(
        tiers, vendors, responders=responders)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        body = json.dumps({"model": "sonnet",
                           "messages": [{"role": "user", "content": "q1"},
                                        {"role": "assistant", "content": "a1"},
                                        {"role": "user", "content": "q2"}],
                           "stream": False})
        status, resp_body = _send_proxy_request(proxy_port, body=body)
        if status != 200:
            fail("expected 200, got {} body={!r}".format(status, resp_body[:200]))
            return
        reqs = mock_servers["p"]["requests"]
        if len(reqs) != 1:
            fail("expected exactly 1 upstream request, got {}".format(len(reqs)))
            return
        if not state["parse_ok"] or state["validated_items"] != 3 or state["violations"]:
            fail("mock validation did not pass cleanly: parse_ok={!r} "
                 "validated={!r} violations={!r}".format(
                     state["parse_ok"], state["validated_items"], state["violations"]))
            return
        try:
            data = json.loads(resp_body)
        except Exception:
            fail("proxy response is not valid JSON: {!r}".format(resp_body[:200]))
            return
        if data.get("type") != "message":
            fail("expected Anthropic message response, got type {!r}".format(data.get("type")))
        if data.get("role") != "assistant":
            fail("expected role assistant, got {!r}".format(data.get("role")))
        if data.get("stop_reason") != "end_turn":
            fail("expected stop_reason end_turn, got {!r}".format(data.get("stop_reason")))
        if data.get("content") != [{"type": "text", "text": "ok"}]:
            fail("expected content [text ok], got {!r}".format(data.get("content")))
        else:
            pass_("schema-validating upstream accepted role-appropriate "
                   "content types; round-trip ok")
    finally:
        cleanup()




def test_response_mode_tool_loop_e2e():
    """Two-turn tool loop through response mode: tool_use then final text.

    Turn 1's upstream request must carry flat tools and full Responses input;
    the mock returns a function_call and the client must receive tool_use with
    stop_reason "tool_use". Turn 2's request must carry the matching
    function_call and function_call_output; the mock returns final text and
    the client must receive stop_reason "end_turn".
    """
    print("\n--- Test: Response Mode Tool Loop E2E ---")
    upstream_port = find_free_port()
    tiers = _mode_tiers()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port), "key": "K",
                     "mode": "response"}}
    fc_body = json.dumps({
        "id": "resp_1", "object": "response", "created_at": 1, "model": "gpt-4o",
        "status": "completed",
        "output": [{"type": "function_call", "call_id": "call_1",
                    "name": "get_weather", "arguments": '{"city": "SF"}'}],
        "usage": {"input_tokens": 4, "output_tokens": 2, "total_tokens": 6},
    }).encode()
    text_body = json.dumps({
        "id": "resp_2", "object": "response", "created_at": 2, "model": "gpt-4o",
        "status": "completed",
        "output": [{"type": "message", "role": "assistant",
                    "content": [{"type": "output_text", "text": "Sunny in SF"}]}],
        "usage": {"input_tokens": 9, "output_tokens": 3, "total_tokens": 12},
    }).encode()
    attempts = {"n": 0}

    def responder(info):
        attempts["n"] += 1
        if attempts["n"] == 1:
            return 200, "application/json", fc_body
        return 200, "application/json", text_body

    responders = {"p": responder}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(
        tiers, vendors, responders=responders)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        schema = {"type": "object",
                  "properties": {"city": {"type": "string"}},
                  "required": ["city"]}
        tools = [{"name": "get_weather", "description": "Get weather",
                  "input_schema": schema}]
        body1 = json.dumps({"model": "sonnet", "max_tokens": 64, "stream": False,
                            "tools": tools,
                            "messages": [{"role": "user", "content": "weather in SF?"}]})
        status1, resp1 = _send_proxy_request(proxy_port, body=body1)
        if status1 != 200:
            fail("turn 1 expected 200, got {}".format(status1))
            return
        try:
            data1 = json.loads(resp1)
        except Exception:
            fail("turn 1 response not JSON: {!r}".format(resp1[:200]))
            return
        content1 = data1.get("content") if isinstance(data1.get("content"), list) else []
        tool_blocks = [b for b in content1
                       if isinstance(b, dict) and b.get("type") == "tool_use"]
        if not tool_blocks:
            fail("turn 1 must return a tool_use block, got {!r}".format(content1))
            return
        tb = tool_blocks[0]
        if tb.get("id") != "call_1" or tb.get("name") != "get_weather" \
                or tb.get("input") != {"city": "SF"}:
            fail("turn 1 tool_use mismatch: {!r}".format(tb))
            return
        if data1.get("stop_reason") != "tool_use":
            fail("turn 1 stop_reason must be 'tool_use', got {!r}".format(
                data1.get("stop_reason")))
            return

        reqs = mock_servers["p"]["requests"]
        if not reqs:
            fail("upstream received no requests")
            return
        if reqs[0]["path"] != "/v1/responses":
            fail("upstream path should be /v1/responses, got {!r}".format(reqs[0]["path"]))
        if reqs[0]["authorization"] != "Bearer K":
            fail("response mode should use Authorization Bearer, got {!r}".format(
                reqs[0]["authorization"]))
        ubody1 = json.loads(reqs[0]["body"])
        if ubody1.get("stream") is not False:
            fail("upstream stream must be false, got {!r}".format(ubody1.get("stream")))
        if ubody1.get("tools") != [{"type": "function", "name": "get_weather",
                                    "description": "Get weather", "parameters": schema}]:
            fail("upstream tools must be flat Responses function tools, got {!r}".format(
                ubody1.get("tools")))
        if ubody1.get("input") != [{"type": "message", "role": "user",
                                    "content": [{"type": "input_text",
                                                 "text": "weather in SF?"}]}]:
            fail("turn 1 upstream input must be full message items, got {!r}".format(
                ubody1.get("input")))

        body2 = json.dumps({"model": "sonnet", "max_tokens": 64, "stream": False,
                            "tools": tools,
                            "messages": [
                                {"role": "user", "content": "weather in SF?"},
                                {"role": "assistant", "content": [
                                    {"type": "tool_use", "id": "call_1",
                                     "name": "get_weather", "input": {"city": "SF"}}]},
                                {"role": "user", "content": [
                                    {"type": "tool_result", "tool_use_id": "call_1",
                                     "content": "Sunny 21C"}]},
                            ]})
        status2, resp2 = _send_proxy_request(proxy_port, body=body2)
        if status2 != 200:
            fail("turn 2 expected 200, got {}".format(status2))
            return
        try:
            data2 = json.loads(resp2)
        except Exception:
            fail("turn 2 response not JSON: {!r}".format(resp2[:200]))
            return
        texts = [b.get("text") for b in (data2.get("content") or [])
                 if isinstance(b, dict) and b.get("type") == "text"]
        if not any(t for t in texts if t):
            fail("turn 2 must return final text, got {!r}".format(data2.get("content")))
            return
        if data2.get("stop_reason") != "end_turn":
            fail("turn 2 stop_reason must be 'end_turn', got {!r}".format(
                data2.get("stop_reason")))
            return
        if len(reqs) < 2:
            fail("upstream received <2 requests, got {}".format(len(reqs)))
            return
        ubody2 = json.loads(reqs[1]["body"])
        items = ubody2.get("input") if isinstance(ubody2.get("input"), list) else []
        kinds = [it.get("type") for it in items if isinstance(it, dict)]
        if kinds != ["message", "function_call", "function_call_output"]:
            fail("turn 2 upstream input kinds wrong: {!r}".format(kinds))
            return
        fc = [it for it in items if it.get("type") == "function_call"][0]
        fco = [it for it in items if it.get("type") == "function_call_output"][0]
        if fc.get("call_id") != "call_1" or fc.get("name") != "get_weather" \
                or json.loads(fc.get("arguments", "null")) != {"city": "SF"}:
            fail("turn 2 function_call item mismatch: {!r}".format(fc))
            return
        if fco.get("call_id") != "call_1" or fco.get("output") != "Sunny 21C":
            fail("turn 2 function_call_output mismatch: {!r}".format(fco))
            return
        pass_("two-turn response-mode tool loop round-trips")
    finally:
        cleanup()




def test_anthropic_mode_unchanged():
    """Existing anthropic behavior is preserved (no mode field)."""
    print("\n--- Test: Anthropic Mode Unchanged ---")
    upstream_port = find_free_port()
    tiers = _mode_tiers()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port), "key": "K"}}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(tiers, vendors)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        status, body = _send_proxy_request(proxy_port)
        if status != 200:
            fail("expected 200, got {}".format(status))
            return
        try:
            data = json.loads(body)
        except Exception:
            fail("response not JSON: {!r}".format(body[:200]))
            return
        # x-api-key used (anthropic default)
        reqs = mock_servers["p"]["requests"]
        if not reqs or reqs[0]["api_key"] != "K":
            fail("anthropic mode should use x-api-key=K")
        # model rewritten to tier name
        if data.get("model") != "sonnet":
            fail("expected model rewritten to 'sonnet', got {!r}".format(data.get("model")))
        if data.get("content") == [{"type": "text", "text": "hello"}] and reqs and reqs[0]["api_key"] == "K":
            pass_("anthropic mode preserves existing behavior")
    finally:
        cleanup()




def test_chat_mode_non_2xx_passthrough():
    """Chat-mode non-2xx error body passes through untransformed."""
    print("\n--- Test: Chat Mode Non 2xx Passthrough ---")
    upstream_port = find_free_port()
    tiers = _mode_tiers()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port), "key": "K", "mode": "chat"}}
    err_body = json.dumps({"error": {"message": "Nothing here", "type": "invalid_request_error"}}).encode()
    responders = {"p": lambda info: (404, "application/json", err_body)}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(tiers, vendors, responders=responders)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        status, body = _send_proxy_request(proxy_port)
        if status != 404:
            fail("expected 404, got {}".format(status))
            return
        if body != err_body:
            fail("non-2xx body should pass through byte-for-byte, got {!r}".format(body[:200]))
        else:
            pass_("chat-mode non-2xx body passes through untransformed")
    finally:
        cleanup()




def test_transform_failure_passthrough():
    """Malformed JSON response body passes through with a transform_failure trace event."""
    print("\n--- Test: Transform Failure Passthrough ---")
    upstream_port = find_free_port()
    tiers = _mode_tiers()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port), "key": "K", "mode": "chat"}}
    bad_body = b"this is not json at all"
    responders = {"p": lambda info: (200, "application/json", bad_body)}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(tiers, vendors, responders=responders)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        status, body = _send_proxy_request(proxy_port)
        if status != 200:
            fail("expected 200, got {}".format(status))
            return
        if body != bad_body:
            fail("malformed JSON body should pass through unchanged, got {!r}".format(body[:200]))
            return
        found = False
        fields_ok = False
        with open(trace_file) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except Exception:
                    continue
                if ev.get("event") == "transform_failure":
                    found = True
                    if (ev.get("provider") == "p" and ev.get("tier") == "sonnet"
                            and ev.get("request_id") and ev.get("mode") == "chat"):
                        fields_ok = True
        if not found:
            fail("expected a transform_failure trace event, none found")
        elif not fields_ok:
            fail("transform_failure event missing provider/tier/request_id/mode, got {!r}".format(ev))
        else:
            pass_("malformed JSON passes through with transform_failure trace event carrying provider/tier")
    finally:
        cleanup()




def test_tool_args_parse_failure_trace_has_request_id():
    """End-to-end: tool_args_parse_failure trace event carries request_id/mode/provider/tier.

    Chat-mode proxy with a mock upstream returning malformed tool-call
    arguments. The proxy's response transform degrades the malformed call to
    a text block and logs tool_args_parse_failure with the full correlation
    context threaded through _transform_and_guard.
    """
    print("\n--- Test: Tool Args Parse Failure Trace Has Request ID ---")
    upstream_port = find_free_port()
    tiers = _mode_tiers()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port), "key": "K", "mode": "chat"}}
    chat_malformed = json.dumps({
        "id": "chatcmpl-1", "object": "chat.completion", "created": 1, "model": "gpt-4o",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "",
                                             "tool_calls": [
                                                 {"id": "call_1", "type": "function",
                                                  "function": {"name": "f", "arguments": "{not json"}}]},
                     "finish_reason": "tool_calls"}],
        "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
    }).encode()
    responders = {"p": lambda info: (200, "application/json", chat_malformed)}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(
        tiers, vendors, responders=responders)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        status, body = _send_proxy_request(proxy_port)
        if status != 200:
            fail("expected 200, got {}".format(status))
            return
        try:
            data = json.loads(body)
        except Exception:
            fail("response is not valid JSON: {!r}".format(body[:200]))
            return
        content = data.get("content") if isinstance(data.get("content"), list) else []
        if any(b.get("type") == "tool_use" for b in content):
            fail("malformed tool args must not produce a tool_use block, content={!r}".format(content))
            return
        if data.get("stop_reason") is not None:
            fail("all-malformed tool calls should force stop_reason None, got {!r}".format(data.get("stop_reason")))
            return
        found = False
        fields_ok = False
        matched_ev = None
        with open(trace_file) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except Exception:
                    continue
                if ev.get("event") == "tool_args_parse_failure":
                    found = True
                    matched_ev = ev
                    if (ev.get("request_id") and ev.get("mode") == "chat"
                            and ev.get("provider") == "p" and ev.get("tier") == "sonnet"):
                        fields_ok = True
        if not found:
            fail("expected a tool_args_parse_failure trace event, none found")
        elif not fields_ok:
            fail("tool_args_parse_failure event missing request_id/mode/provider/tier, got {!r}".format(matched_ev))
        else:
            pass_("tool_args_parse_failure trace event carries request_id/mode/provider/tier")
    finally:
        cleanup()




def test_retry_does_not_double_transform():
    """A 429 retry sends the same single-transformed body, not double-encoded."""
    print("\n--- Test: Retry Does Not Double Transform ---")
    upstream_port = find_free_port()
    tiers = _mode_tiers()
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port), "key": "K", "mode": "chat"}}
    chat_ok = json.dumps({
        "id": "chatcmpl-1", "object": "chat.completion", "created": 1, "model": "gpt-4o",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "Hello"},
                     "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
    }).encode()
    err_body = json.dumps({"error": {"message": "too many", "type": "rate_limit"}}).encode()
    attempts = {"n": 0}

    def responder(info):
        attempts["n"] += 1
        if attempts["n"] == 1:
            return 429, "application/json", err_body
        return 200, "application/json", chat_ok

    responders = {"p": responder}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(
        tiers, vendors, responders=responders,
        extra_env={"PROXY_MAX_RETRIES": "2", "PROXY_MAX_DELAY": "2", "PROXY_INITIAL_DELAY": "1"})
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        status, body = _send_proxy_request(proxy_port)
        if status != 200:
            fail("expected 200 after retry, got {}".format(status))
            return
        reqs = mock_servers["p"]["requests"]
        if len(reqs) < 2:
            fail("expected upstream to receive at least 2 requests (429 then 200), got {}".format(len(reqs)))
            return
        bodies = [json.loads(r["body"]) for r in reqs]
        for rb in bodies:
            if not isinstance(rb, dict) or not isinstance(rb.get("messages"), list):
                fail("transformed body should be single-pass JSON with messages list, got {!r}".format(rb))
                return
        if reqs[0]["body"] != reqs[1]["body"]:
            fail("retry should reuse the same pre-built transformed body")
        else:
            pass_("retry sends the single-transformed body, unchanged across attempts")
    finally:
        cleanup()


# --- extra_request_headers attach matrix + user-agent forwarding ---
# (plan 2026-09-06-opencode-session-header)

def _last_request_event(trace_file, provider):
    """Return the newest 'request' trace event dict for provider, or None."""
    ev = None
    if not trace_file or not os.path.exists(trace_file):
        return None
    with open(trace_file) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                parsed = json.loads(line)
            except Exception:
                continue
            if parsed.get("event") == "request" and parsed.get("provider") == provider:
                ev = parsed
    return ev


def _last_request_event_request_id(trace_file, provider):
    """Return the request_id of the newest 'request' trace event for provider."""
    ev = _last_request_event(trace_file, provider)
    return ev.get("request_id") if ev else None


def test_extra_request_headers_attach_matrix():
    """Resolved extra header emission for a ruled vs unruled provider.

    (a) mixed-case inbound X-Claude-Code-Session-Id -> x-opencode-session
    (b) inbound x-opencode-session wins over the alias header
    (c) padded inbound value -> stripped emitted value
    (d) neither inbound -> value equals the request's request_id (trace-correlated)
    (e) provider without an x-opencode-session rule -> x-opencode-session absent upstream
    (f) padded literal fallback -> stripped value upstream AND in the trace
    """
    print("\n--- Test: extra_request_headers attach matrix ---")
    upstream1 = find_free_port()
    upstream2 = find_free_port()
    tiers = {
        "haiku": {"provider": "opencode-go", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "opencode-go", "model": "sonnet"},
        "opus": {"provider": "other", "model": "opaque-model-other"},
    }
    vendors = {
        "opencode-go": {"url": "http://127.0.0.1:{}".format(upstream1), "key": "K-OG"},
        "other": {"url": "http://127.0.0.1:{}".format(upstream2), "key": "K-OTHER"},
    }
    extra = {
        "opencode-go": [
            {"header": "x-opencode-session",
             "from": ["x-opencode-session", "x-claude-code-session-id"],
             "fallback": "request_id"},
        ],
        "other": [
            {"header": "x-strip-fallback", "fallback": "  v  "},
        ],
    }
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(
        tiers, vendors, extra_headers=extra)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        og_reqs = mock_servers["opencode-go"]["requests"]
        other_reqs = mock_servers["other"]["requests"]

        def send(model, headers=None, check_other=False):
            status, _ = _send_proxy_request(
                proxy_port,
                body=json.dumps({"model": model, "messages": [{"role": "user", "content": "hi"}]}),
                headers=headers)
            if status != 200:
                fail("expected 200, got {}".format(status))
                return None
            if check_other:
                return other_reqs[-1]["headers"]
            return og_reqs[-1]["headers"]

        # (a) mixed-case inbound alias name -> x-opencode-session emitted
        h = send("sonnet", {"X-Claude-Code-Session-Id": "session-a1"})
        if h is None:
            return
        if h.get("x-opencode-session") == ["session-a1"]:
            pass_("(a) mixed-case X-Claude-Code-Session-Id -> x-opencode-session: session-a1")
        else:
            fail("(a) expected x-opencode-session=session-a1, got {!r}".format(h.get("x-opencode-session")))

        # (b) native x-opencode-session inbound wins over the alias
        h = send("sonnet", {"x-opencode-session": "native-v", "X-Claude-Code-Session-Id": "alias-v"})
        if h is None:
            return
        if h.get("x-opencode-session") == ["native-v"]:
            pass_("(b) inbound x-opencode-session wins over alias")
        else:
            fail("(b) expected x-opencode-session=native-v, got {!r}".format(h.get("x-opencode-session")))

        # (c) padded inbound value -> stripped emitted value
        h = send("sonnet", {"X-Claude-Code-Session-Id": "  padded  "})
        if h is None:
            return
        if h.get("x-opencode-session") == ["padded"]:
            pass_("(c) padded inbound value emitted stripped: 'padded'")
        else:
            fail("(c) expected x-opencode-session='padded', got {!r}".format(h.get("x-opencode-session")))

        # (d) neither inbound -> value equals the request's request_id
        h = send("sonnet")
        if h is None:
            return
        expected = _last_request_event_request_id(trace_file, "opencode-go")
        if h.get("x-opencode-session") == [expected]:
            pass_("(d) absent inbound -> resolved to request_id {}".format(expected))
        else:
            fail("(d) expected x-opencode-session={!r} (trace request_id), got {!r}".format(
                expected, h.get("x-opencode-session")))

        # (e) provider without an x-opencode-session rule -> header absent upstream
        h = send("opaque-model-other", check_other=True)
        if h is None:
            return
        if "x-opencode-session" not in h:
            pass_("(e) provider without an x-opencode-session rule emits no x-opencode-session upstream")
        else:
            fail("(e) expected no x-opencode-session for non-opencode provider, got {!r}".format(
                h.get("x-opencode-session")))

        # (f) padded literal fallback -> stripped value upstream AND in the trace
        #     (Phase-6 review round-2: fallback literals are emitted stripped,
        #      matching from-derived values)
        h = send("opaque-model-other", check_other=True)
        if h is None:
            return
        if h.get("x-strip-fallback") == ["v"]:
            pass_("(f) padded fallback literal emitted stripped upstream: 'v'")
        else:
            fail("(f) expected x-strip-fallback='v', got {!r}".format(h.get("x-strip-fallback")))
        ev = _last_request_event(trace_file, "other")
        if ev is not None and ev.get("extra_request_headers") == {"x-strip-fallback": "v"}:
            pass_("(f) trace records the stripped fallback value: {{'x-strip-fallback': 'v'}}")
        else:
            fail("(f) expected trace extra_request_headers={{'x-strip-fallback': 'v'}}, got {!r}".format(
                ev.get("extra_request_headers") if ev else None))
    finally:
        cleanup()


def test_user_agent_forwarded_all_modes():
    """Inbound User-Agent forwarded upstream for anthropic/chat/response modes,
    exactly one User-Agent line reaching upstream."""
    print("\n--- Test: User-Agent forwarded across all modes ---")
    chat_ok = json.dumps({
        "id": "chatcmpl-1", "object": "chat.completion", "created": 1, "model": "gpt-4o",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "Hello"},
                     "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
    }).encode()
    resp_ok = json.dumps({
        "id": "resp_1", "object": "response", "created_at": 1, "model": "gpt-4o",
        "status": "completed",
        "output": [{"type": "message", "role": "assistant",
                    "content": [{"type": "output_text", "text": "Hello", "annotations": []}]}],
        "usage": {"input_tokens": 4, "output_tokens": 2, "total_tokens": 6},
    }).encode()

    for mode, responder in (
        ("anthropic", _mode_default_responder),
        ("chat", lambda info: (200, "application/json", chat_ok)),
        ("response", lambda info: (200, "application/json", resp_ok)),
    ):
        upstream_port = find_free_port()
        vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream_port), "key": "K",
                         "mode": mode} if mode != "anthropic" else
                   {"url": "http://127.0.0.1:{}".format(upstream_port), "key": "K"}}
        temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = _start_mode_proxy(
            _mode_tiers(), vendors, responders={"p": responder})
        if proc is None:
            fail("Failed to set up {} mode proxy".format(mode))
            continue
        try:
            status, _ = _send_proxy_request(
                proxy_port, headers={"User-Agent": "claude-cli/2.1.220 (external, cli)"})
            if status != 200:
                fail("{} mode: expected 200, got {}".format(mode, status))
                continue
            reqs = mock_servers["p"]["requests"]
            if not reqs:
                fail("{} mode: upstream received no requests".format(mode))
                continue
            ua_lines = (reqs[0].get("headers") or {}).get("user-agent")
            if ua_lines == ["claude-cli/2.1.220 (external, cli)"]:
                pass_("{} mode: User-Agent forwarded exactly once with value".format(mode))
            else:
                fail("{} mode: expected exactly one 'claude-cli/2.1.220 (external, cli)' "
                     "user-agent line, got {!r}".format(mode, ua_lines))
        finally:
            cleanup()


ALL_TESTS = [
    ("mode-defaults-to-anthropic", test_mode_defaults_to_anthropic),
    ("mode-null-defaults-to-anthropic", test_mode_null_defaults_to_anthropic),
    ("mode-invalid-rejected", test_mode_invalid_rejected),
    ("auth-header-anthropic-mode", test_auth_header_anthropic_mode),
    ("auth-header-chat-mode", test_auth_header_chat_mode),
    ("auth-header-response-mode", test_auth_header_response_mode),
    ("path-anthropic-mode", test_path_anthropic_mode),
    ("path-chat-mode", test_path_chat_mode),
    ("path-response-mode", test_path_response_mode),
    ("path-double-v1-prevention", test_path_double_v1_prevention),
    ("count-tokens-rejected-chat-mode", test_count_tokens_rejected_chat_mode),
    ("count-tokens-rejected-response-mode", test_count_tokens_rejected_response_mode),
    ("anthropic-to-chat-basic", test_anthropic_to_chat_basic),
    ("anthropic-to-chat-system-string", test_anthropic_to_chat_system_string),
    ("anthropic-to-chat-system-list", test_anthropic_to_chat_system_list),
    ("anthropic-to-chat-dropped-fields", test_anthropic_to_chat_dropped_fields),
    ("anthropic-to-chat-stop-sequences", test_anthropic_to_chat_stop_sequences),
    ("chat-mode-e2e-json", test_chat_mode_e2e_json),
    ("response-mode-e2e-json", test_response_mode_e2e_json),
    ("response-mode-assistant-output-text-e2e", test_response_mode_assistant_output_text_e2e),
    ("response-mode-tool-loop-e2e", test_response_mode_tool_loop_e2e),
    ("anthropic-mode-unchanged", test_anthropic_mode_unchanged),
    ("chat-mode-non-2xx-passthrough", test_chat_mode_non_2xx_passthrough),
    ("transform-failure-passthrough", test_transform_failure_passthrough),
    ("tool-args-parse-failure-trace-has-request-id", test_tool_args_parse_failure_trace_has_request_id),
    ("retry-does-not-double-transform", test_retry_does_not_double_transform),
    ("extra-request-headers-attach-matrix", test_extra_request_headers_attach_matrix),
    ("user-agent-forwarded-all-modes", test_user_agent_forwarded_all_modes),
]


if __name__ == "__main__":
    run_cli(ALL_TESTS, "claude-retry-proxy tests: test_mode_dispatch")
