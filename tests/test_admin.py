"""Admin page and API tests: config GET, switch, CSRF, providers-detail,
models catalog, reload, and flag preservation.

Part of the claude-retry-proxy suite; runnable standalone.
"""

import json
import os
import shutil
import subprocess
import tempfile

from _harness import (
    _admin_get,
    _admin_post,
    _create_test_config,
    _create_test_config_with_flag,
    _create_test_keys,
    _create_test_keys_plain,
    _derive_models_from_tiers,
    _mode_tiers,
    _send_proxy_request,
    _setup_tier_routing_test,
    _start_admin_proxy,
    _start_mock_upstream,
    _start_proxy_server_directly,
    errors,
    fail,
    find_free_port,
    pass_,
    run_cli,
    warn,
)




# ===========================================================================
# Test: Admin Page Served
# ===========================================================================

def test_admin_page_served():
    """GET /admin/ returns HTML."""
    print("\n--- Test: Admin Page Served ---")

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
        import http.client as _hc
        conn = _hc.HTTPConnection("127.0.0.1", proxy_port, timeout=10)
        conn.request("GET", "/admin/")
        resp = conn.getresponse()
        status = resp.status
        content_type = resp.getheader("Content-Type", "")
        body = resp.read().decode()
        conn.close()

        if status == 200:
            pass_("GET /admin/ returned 200")
        else:
            fail(f"GET /admin/ returned {status}, expected 200")

        if "text/html" in content_type:
            pass_("Content-Type is text/html")
        else:
            fail(f"Content-Type is {content_type}, expected text/html")

        if "<html" in body.lower() or "<!doctype" in body.lower():
            pass_("Response contains HTML")
        else:
            fail("Response doesn't contain HTML")

    finally:
        cleanup()




# ===========================================================================
# Test: Admin API Config
# ===========================================================================

def test_admin_api_config():
    """GET /admin/api/config returns current tiers + models."""
    print("\n--- Test: Admin API Config ---")

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
        import http.client as _hc
        conn = _hc.HTTPConnection("127.0.0.1", proxy_port, timeout=10)
        conn.request("GET", "/admin/api/config")
        resp = conn.getresponse()
        status = resp.status
        body = resp.read().decode()
        conn.close()

        if status != 200:
            fail(f"GET /admin/api/config returned {status}")
            return

        try:
            config = json.loads(body)
            if "tiers" in config and "models" in config:
                pass_("Config API returns tiers and models")
            else:
                fail("Config API missing tiers or models")
        except:
            fail("Config API response not valid JSON")

    finally:
        cleanup()




# ===========================================================================
# Test: Admin API Switch
# ===========================================================================

def test_admin_api_switch():
    """POST /admin/api/switch updates tier, subsequent request routes to new provider."""
    print("\n--- Test: Admin API Switch ---")

    p1_port = find_free_port()
    p2_port = find_free_port()
    tiers = {
        "haiku": {"provider": "p1", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "p1", "model": "claude-sonnet-5"},
        "opus": {"provider": "p1", "model": "claude-opus-5"},
    }
    vendors = {
        "p1": {"url": f"http://127.0.0.1:{p1_port}", "key": "k1"},
        "p2": {"url": f"http://127.0.0.1:{p2_port}", "key": "k2"},
    }

    proxy_port, proc, mock_servers, temp_dir, cleanup = _start_admin_proxy(tiers, vendors)
    if proc is None:
        fail("Failed to set up test")
        return

    try:
        # Baseline: sonnet routes to p1
        status, resp_body = _send_proxy_request(proxy_port, body=json.dumps({
            "model": "sonnet", "messages": [{"role": "user", "content": "hi"}]}))
        if status != 200:
            fail(f"Baseline request returned {status}")
            return
        p1_count_before = len(mock_servers["p1"]["requests"])
        pass_(f"Baseline sonnet request routed to p1 ({p1_count_before} requests)")

        # Switch sonnet from p1 to p2
        switch_body = {
            "tiers": {
                "haiku": {"provider": "p1", "model": "claude-haiku-4-5"},
                "sonnet": {"provider": "p2", "model": "claude-sonnet-5"},
                "opus": {"provider": "p1", "model": "claude-opus-5"},
            }
        }
        status, data = _admin_post(proxy_port, "/admin/api/switch", switch_body)
        if status != 200:
            fail(f"Switch returned {status}: {data}")
            return
        try:
            resp = json.loads(data)
            if resp.get("status") == "ok":
                pass_("Admin API switch returned {'status': 'ok'} (200)")
            else:
                fail(f"Switch response missing 'status': 'ok': {data}")
        except Exception:
            fail(f"Switch response not valid JSON: {data}")

        # Post-switch: sonnet routes to p2
        status, resp_body = _send_proxy_request(proxy_port, body=json.dumps({
            "model": "sonnet", "messages": [{"role": "user", "content": "hi"}]}))
        if status != 200:
            fail(f"Post-switch request returned {status}")
            return

        p2_count = len(mock_servers["p2"]["requests"])
        if p2_count >= 1:
            pass_(f"Post-switch sonnet request routed to p2 ({p2_count} requests)")
        else:
            fail("Post-switch sonnet request did NOT route to p2")

        p1_count_after = len(mock_servers["p1"]["requests"])
        if p1_count_after == p1_count_before:
            pass_("p1 received zero further sonnet requests")
        else:
            fail(f"p1 received further requests after switch: before={p1_count_before} after={p1_count_after}")

    finally:
        cleanup()




# ===========================================================================
# Test: Admin API Switch Invalid Provider
# ===========================================================================

def test_admin_api_switch_invalid_provider():
    """POST with unknown provider → error response."""
    print("\n--- Test: Admin API Switch Invalid Provider ---")

    p_port = find_free_port()
    tiers = {
        "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
        "opus": {"provider": "p", "model": "claude-opus-5"},
    }
    vendors = {"p": {"url": f"http://127.0.0.1:{p_port}", "key": "k"}}

    proxy_port, proc, mock_servers, temp_dir, cleanup = _start_admin_proxy(tiers, vendors)
    if proc is None:
        fail("Failed to set up test")
        return

    try:
        switch_body = {
            "tiers": {
                "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
                "sonnet": {"provider": "nonexistent", "model": "claude-sonnet-5"},
                "opus": {"provider": "p", "model": "claude-opus-5"},
            }
        }
        status, data = _admin_post(proxy_port, "/admin/api/switch", switch_body)
        if status == 400:
            pass_(f"Switch with invalid provider returned 400")
        else:
            fail(f"Switch with invalid provider returned {status}: {data}")
        if "unknown provider" in data:
            pass_(f"Error mentions 'unknown provider': {data}")
        else:
            fail(f"Error missing 'unknown provider': {data}")
    finally:
        cleanup()




# ===========================================================================
# Test: Admin API Switch Preserves Models
# ===========================================================================

def test_admin_api_switch_preserves_models():
    """Switch tiers, verify models section unchanged in config.json."""
    print("\n--- Test: Admin API Switch Preserves Models ---")

    p_port = find_free_port()
    tiers = {
        "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
        "opus": {"provider": "p", "model": "claude-opus-5"},
    }
    models = {"p": ["claude-sonnet-5", "claude-haiku-4-5", "claude-opus-5"]}
    vendors = {"p": {"url": f"http://127.0.0.1:{p_port}", "key": "k"}}

    proxy_port, proc, mock_servers, temp_dir, cleanup = _start_admin_proxy(
        tiers, vendors, models=models)
    if proc is None:
        fail("Failed to set up test")
        return

    try:
        # POST switch with tiers only (no models field)
        switch_body = {
            "tiers": {
                "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
                "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
                "opus": {"provider": "p", "model": "claude-opus-5"},
            }
        }
        status, data = _admin_post(proxy_port, "/admin/api/switch", switch_body)
        if status != 200:
            fail(f"Switch returned {status}: {data}")
            return

        # GET /admin/api/config → models section unchanged
        import http.client as _hc
        conn = _hc.HTTPConnection("127.0.0.1", proxy_port, timeout=10)
        conn.request("GET", "/admin/api/config")
        resp = conn.getresponse()
        body = resp.read().decode()
        conn.close()
        if resp.status != 200:
            fail(f"GET /admin/api/config returned {resp.status}")
            return
        config = json.loads(body)
        if config.get("models") == models:
            pass_("Models section unchanged in /admin/api/config response")
        else:
            fail(f"Models section changed: {config.get('models')}")

        # On-disk config.json still has models section
        config_path = os.path.join(temp_dir, "config.json")
        with open(config_path) as f:
            disk_config = json.load(f)
        if disk_config.get("models") == models:
            pass_("Models section still present in on-disk config.json")
        else:
            fail(f"Models section missing from on-disk config.json: {disk_config.get('models')}")
    finally:
        cleanup()




# ===========================================================================
# Test: Admin API CSRF Rejected
# ===========================================================================

def test_admin_api_csrf_rejected():
    """POST with foreign Origin header → rejected."""
    print("\n--- Test: Admin API CSRF Rejected ---")

    p_port = find_free_port()
    tiers = {
        "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
        "opus": {"provider": "p", "model": "claude-opus-5"},
    }
    vendors = {"p": {"url": f"http://127.0.0.1:{p_port}", "key": "k"}}

    proxy_port, proc, mock_servers, temp_dir, cleanup = _start_admin_proxy(tiers, vendors)
    if proc is None:
        fail("Failed to set up test")
        return

    try:
        switch_body = {
            "tiers": {
                "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
                "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
                "opus": {"provider": "p", "model": "claude-opus-5"},
            }
        }
        status, data = _admin_post(proxy_port, "/admin/api/switch", switch_body,
                                   origin="http://evil.com:9999")
        if status == 403:
            pass_("Foreign Origin rejected with 403")
        else:
            fail(f"Foreign Origin returned {status} (expected 403): {data}")
    finally:
        cleanup()




# ===========================================================================
# Test: Admin API CSRF Null Origin Rejected
# ===========================================================================

def test_admin_api_csrf_null_origin_rejected():
    """POST with Origin: null → rejected."""
    print("\n--- Test: Admin API CSRF Null Origin Rejected ---")

    p_port = find_free_port()
    tiers = {
        "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
        "opus": {"provider": "p", "model": "claude-opus-5"},
    }
    vendors = {"p": {"url": f"http://127.0.0.1:{p_port}", "key": "k"}}

    proxy_port, proc, mock_servers, temp_dir, cleanup = _start_admin_proxy(tiers, vendors)
    if proc is None:
        fail("Failed to set up test")
        return

    try:
        switch_body = {
            "tiers": {
                "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
                "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
                "opus": {"provider": "p", "model": "claude-opus-5"},
            }
        }
        status, data = _admin_post(proxy_port, "/admin/api/switch", switch_body,
                                   origin="null")
        if status == 403:
            pass_("Origin: null rejected with 403")
        else:
            fail(f"Origin: null returned {status} (expected 403): {data}")
    finally:
        cleanup()




# ===========================================================================
# Test: Admin API CSRF Missing Origin Rejected
# ===========================================================================

def test_admin_api_csrf_missing_origin_rejected():
    """POST without Origin header → rejected."""
    print("\n--- Test: Admin API CSRF Missing Origin Rejected ---")

    p_port = find_free_port()
    tiers = {
        "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
        "opus": {"provider": "p", "model": "claude-opus-5"},
    }
    vendors = {"p": {"url": f"http://127.0.0.1:{p_port}", "key": "k"}}

    proxy_port, proc, mock_servers, temp_dir, cleanup = _start_admin_proxy(tiers, vendors)
    if proc is None:
        fail("Failed to set up test")
        return

    try:
        import http.client as _hc
        switch_body = {
            "tiers": {
                "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
                "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
                "opus": {"provider": "p", "model": "claude-opus-5"},
            }
        }
        conn = _hc.HTTPConnection("127.0.0.1", proxy_port, timeout=10)
        conn.request("POST", "/admin/api/switch",
                     body=json.dumps(switch_body),
                     headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        data = resp.read().decode()
        conn.close()
        if resp.status == 403:
            pass_("Missing Origin rejected with 403")
        else:
            fail(f"Missing Origin returned {resp.status} (expected 403): {data}")
    finally:
        cleanup()




# ===========================================================================
# Test: Admin API CSRF IPv6 Loopback Accepted
# ===========================================================================

def test_admin_api_csrf_ipv6_loopback_accepted():
    """POST with Origin: http://[::1]:<port> → accepted."""
    print("\n--- Test: Admin API CSRF IPv6 Loopback Accepted ---")

    p_port = find_free_port()
    tiers = {
        "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
        "opus": {"provider": "p", "model": "claude-opus-5"},
    }
    vendors = {"p": {"url": f"http://127.0.0.1:{p_port}", "key": "k"}}

    proxy_port, proc, mock_servers, temp_dir, cleanup = _start_admin_proxy(tiers, vendors)
    if proc is None:
        fail("Failed to set up test")
        return

    try:
        switch_body = {
            "tiers": {
                "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
                "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
                "opus": {"provider": "p", "model": "claude-opus-5"},
            }
        }
        origin = "http://[::1]:{}".format(proxy_port)
        status, data = _admin_post(proxy_port, "/admin/api/switch", switch_body,
                                   origin=origin)
        if status == 200:
            pass_("IPv6 loopback Origin accepted (200) — validates Origin allowlist")
        else:
            fail(f"IPv6 loopback Origin returned {status} (expected 200): {data}")
    finally:
        cleanup()




# ===========================================================================
# Test: Admin API Switch Missing Tier Rejected
# ===========================================================================

def test_admin_api_switch_missing_tier_rejected():
    """POST with only 2 tiers → 400 error listing missing tier."""
    print("\n--- Test: Admin API Switch Missing Tier Rejected ---")

    p_port = find_free_port()
    tiers = {
        "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
        "opus": {"provider": "p", "model": "claude-opus-5"},
    }
    vendors = {"p": {"url": f"http://127.0.0.1:{p_port}", "key": "k"}}

    proxy_port, proc, mock_servers, temp_dir, cleanup = _start_admin_proxy(tiers, vendors)
    if proc is None:
        fail("Failed to set up test")
        return

    try:
        switch_body = {
            "tiers": {
                "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
                "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
            }
        }
        status, data = _admin_post(proxy_port, "/admin/api/switch", switch_body)
        if status == 400:
            pass_(f"Switch with 2 tiers returned 400")
        else:
            fail(f"Switch with 2 tiers returned {status} (expected 400): {data}")
        if "missing tiers" in data:
            pass_(f"Error mentions 'missing tiers': {data}")
        else:
            fail(f"Error missing 'missing tiers': {data}")
    finally:
        cleanup()




# ===========================================================================
# Test: Admin API Reload
# ===========================================================================

def test_admin_api_reload():
    """Modify config.json on disk, POST /admin/api/reload, verify new mapping active."""
    print("\n--- Test: Admin API Reload ---")

    p_port = find_free_port()
    tiers_a = {
        "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "p", "model": "model-a"},
        "opus": {"provider": "p", "model": "claude-opus-5"},
    }
    vendors = {"p": {"url": f"http://127.0.0.1:{p_port}", "key": "k"}}

    temp_dir = tempfile.mkdtemp(prefix="proxy_admin_reload_")
    proxy_port = find_free_port()
    config_path = _create_test_config(temp_dir, tiers_a)
    keys_path = _create_test_keys_plain(temp_dir, vendors)

    req_list = []
    mock_servers = {"p": {
        "server": _start_mock_upstream(p_port, req_list),
        "requests": req_list,
    }}

    trace_fd, trace_file = tempfile.mkstemp(suffix=".jsonl", dir=temp_dir)
    os.close(trace_fd)

    proc, probe_ok = _start_proxy_server_directly(
        proxy_port, config_path=config_path, keys_path=keys_path,
        passphrase=None, trace_file=trace_file
    )

    if not probe_ok:
        mock_servers["p"]["server"].shutdown()
        proc.kill()
        shutil.rmtree(temp_dir, ignore_errors=True)
        fail("Failed to set up test")
        return

    def cleanup():
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        mock_servers["p"]["server"].shutdown()
        shutil.rmtree(temp_dir, ignore_errors=True)

    try:
        # Baseline: sonnet routes to model-a
        status, resp_body = _send_proxy_request(proxy_port, body=json.dumps({
            "model": "sonnet", "messages": [{"role": "user", "content": "hi"}]}))
        if status != 200:
            fail(f"Baseline request returned {status}")
            return
        if req_list and b"model-a" in req_list[-1]["body"]:
            pass_("Baseline sonnet request routed to model-a")
        else:
            fail(f"Baseline sonnet request did not route to model-a. last: {req_list[-1] if req_list else 'none'}")

        # Modify config.json on disk: sonnet → model-b
        tiers_b = dict(tiers_a)
        tiers_b["sonnet"] = {"provider": "p", "model": "model-b"}
        with open(config_path, "w") as f:
            # Reload re-validates: provider "p" needs >=1 model in config.models
            json.dump({"tiers": tiers_b, "models": _derive_models_from_tiers(tiers_b)}, f)

        # POST /admin/api/reload
        status, data = _admin_post(proxy_port, "/admin/api/reload", {})
        if status == 200:
            pass_("Admin API reload returned 200")
        else:
            fail(f"Admin API reload returned {status}: {data}")
            return

        # Post-reload: sonnet routes to model-b
        status, resp_body = _send_proxy_request(proxy_port, body=json.dumps({
            "model": "sonnet", "messages": [{"role": "user", "content": "hi"}]}))
        if status != 200:
            fail(f"Post-reload request returned {status}")
            return
        if req_list and b"model-b" in req_list[-1]["body"]:
            pass_("Post-reload sonnet request routed to model-b")
        else:
            fail(f"Post-reload sonnet request did not route to model-b. last: {req_list[-1] if req_list else 'none'}")
    finally:
        cleanup()




# ===========================================================================
# Test: Admin API Serves Provider-Keyed Models (plan Step 3)
# ===========================================================================

def test_admin_models_provider_keyed():
    """Admin API serves models keyed by provider; admin.html model <select> is
    populated from config.models[provider] — no placeholder or custom options."""
    print("\n--- Test: Admin Models Provider-Keyed ---")

    upstream_port = find_free_port()
    tiers = {
        "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
        "opus": {"provider": "p", "model": "claude-opus-5"},
    }
    vendors = {"p": {"url": f"http://127.0.0.1:{upstream_port}", "key": "k"}}
    # Models keyed by PROVIDER name (matching config.json layout), not by tier
    models = {
        "p": ["claude-haiku-4-5", "claude-sonnet-5", "claude-opus-5", "qwen3.7-plus"]
    }

    temp_dir = tempfile.mkdtemp(prefix="proxy_admin_models_test_")
    try:
        config_path = _create_test_config(temp_dir, tiers, models=models)
        keys_path = _create_test_keys(temp_dir, vendors)

        proxy_port = find_free_port()
        proc, probe_ok = _start_proxy_server_directly(
            proxy_port, config_path=config_path, keys_path=keys_path
        )
        if not probe_ok:
            fail("Proxy server failed to start")
            return

        try:
            import http.client as _hc

            # 1. Admin API serves provider-keyed models
            conn = _hc.HTTPConnection("127.0.0.1", proxy_port, timeout=10)
            conn.request("GET", "/admin/api/config")
            resp = conn.getresponse()
            status = resp.status
            body = resp.read().decode()
            conn.close()

            if status != 200:
                fail(f"GET /admin/api/config returned {status}")
                return

            config = json.loads(body)
            if "models" not in config:
                fail("Admin config missing 'models' key")
                return

            if "p" in config["models"] and isinstance(config["models"]["p"], list):
                pass_("config.models is keyed by provider name (models.p present)")
            else:
                fail(f"config.models not provider-keyed: {list(config['models'].keys())}")

            if "qwen3.7-plus" in config["models"]["p"]:
                pass_("Provider model list contains expected model")
            else:
                fail(f"Provider model list missing qwen3.7-plus: {config['models']['p']}")

            # 2. Admin page HTML: model <select> populated from the provider's model
            #    catalog — no placeholders, no "Custom...", no hidden input
            conn = _hc.HTTPConnection("127.0.0.1", proxy_port, timeout=10)
            conn.request("GET", "/admin/")
            html_resp = conn.getresponse()
            html = html_resp.read().decode()
            conn.close()

            if '<select id="${tier}-model"' in html:
                pass_("admin.html model field is a <select> per tier")
            else:
                fail("admin.html model field is not a <select>")

            if "config.models" in html:
                pass_("admin.html references config.models for model population")
            else:
                fail("admin.html missing config.models reference")

            if '<option value="">' in html:
                fail("admin.html still contains an empty placeholder <option>")
            else:
                pass_("admin.html has no placeholder <option value=\"\">")

            if "__custom__" in html:
                fail("admin.html still contains the 'Custom...' option")
            else:
                pass_("admin.html has no 'Custom...' option")

            if "-custom-model" in html:
                fail("admin.html still contains a -custom-model input")
            else:
                pass_("admin.html has no hidden custom-model input")

            if ".model-custom" in html:
                fail("admin.html still contains .model-custom CSS")
            else:
                pass_("admin.html has no .model-custom CSS")

        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)




def test_admin_switch_preserves_disable_retry_flag():
    """Admin Apply preserves disable_retry_claude_count_token in returned + on-disk config."""
    print("\n--- Test: Admin Switch Preserves Disable Retry Flag ---")

    upstream_port = find_free_port()
    proxy_port = find_free_port()

    tiers = {
        "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
        "opus": {"provider": "p", "model": "claude-opus-5"},
    }
    vendors = {"p": {"url": f"http://127.0.0.1:{upstream_port}", "key": "k"}}

    temp_dir = tempfile.mkdtemp(prefix="proxy_drct_admin_test_")
    try:
        config_path = _create_test_config_with_flag(temp_dir, tiers, True)
        keys_path = _create_test_keys(temp_dir, vendors)

        proc, probe_ok = _start_proxy_server_directly(
            proxy_port, config_path=config_path, keys_path=keys_path
        )
        if not probe_ok:
            fail("Proxy server failed to start")
            return

        try:
            import http.client as _hc
            # Apply a tier switch (swap sonnet to a new model on same provider)
            switch_body = json.dumps({
                "tiers": {
                    "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
                    "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
                    "opus": {"provider": "p", "model": "claude-opus-5"},
                }
            })
            conn = _hc.HTTPConnection("127.0.0.1", proxy_port, timeout=10)
            conn.request("POST", "/admin/api/switch", body=switch_body,
                         headers={"Content-Type": "application/json", "Origin": f"http://localhost:{proxy_port}"})
            resp = conn.getresponse()
            switch_status = resp.status
            resp.read()
            conn.close()

            if switch_status != 200:
                fail(f"Admin switch returned {switch_status}, expected 200")
                return

            # Check returned config
            conn = _hc.HTTPConnection("127.0.0.1", proxy_port, timeout=10)
            conn.request("GET", "/admin/api/config")
            resp = conn.getresponse()
            config = json.loads(resp.read().decode())
            conn.close()

            if config.get("disable_retry_claude_count_token") is True:
                pass_("Returned config preserves disable_retry_claude_count_token=true")
            else:
                fail(f"Returned config missing/preserved flag: {config.get('disable_retry_claude_count_token')}")

            # Check on-disk config.json
            with open(config_path) as f:
                disk_config = json.load(f)
            if disk_config.get("disable_retry_claude_count_token") is True:
                pass_("On-disk config preserves disable_retry_claude_count_token=true")
            else:
                fail(f"On-disk config missing/preserved flag: {disk_config.get('disable_retry_claude_count_token')}")

        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)




# --- Step 10: admin providers-detail endpoint ---

def test_admin_providers_detail():
    """providers-detail returns mode per provider without keys."""
    print("\n--- Test: Admin Providers Detail ---")
    p1, p2, p3 = find_free_port(), find_free_port(), find_free_port()
    tiers = _mode_tiers("anthro")
    vendors = {
        "anthro": {"url": "http://127.0.0.1:{}".format(p1), "key": "KEY-AAA"},
        "chat_p": {"url": "http://127.0.0.1:{}".format(p2), "key": "KEY-BBB", "mode": "chat"},
        "resp_p": {"url": "http://127.0.0.1:{}".format(p3), "key": "KEY-CCC", "mode": "response"},
    }
    proxy_port, proc, mock_servers, temp_dir, cleanup = _start_admin_proxy(tiers, vendors)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        status, body, _ = _admin_get(proxy_port, "/admin/api/providers-detail")
        if status != 200:
            fail("expected 200, got {}".format(status))
            return
        try:
            data = json.loads(body)
        except Exception:
            fail("providers-detail not JSON: {!r}".format(body[:200]))
            return
        providers = data.get("providers", {})
        if providers.get("anthro", {}).get("mode") != "anthropic":
            fail("expected anthro mode anthropic, got {!r}".format(providers))
        if providers.get("chat_p", {}).get("mode") != "chat":
            fail("expected chat_p mode chat, got {!r}".format(providers))
        if providers.get("resp_p", {}).get("mode") != "response":
            fail("expected resp_p mode response, got {!r}".format(providers))
        text = body.decode("utf-8", errors="replace")
        for key in ("KEY-AAA", "KEY-BBB", "KEY-CCC"):
            if key in text:
                fail("providers-detail leaked key material: {}".format(key))
        if providers.get("chat_p", {}).get("mode") == "chat" and "KEY-BBB" not in text:
            pass_("providers-detail returns modes without keys")
    finally:
        cleanup()




def test_admin_providers_detail_no_mode():
    """Providers without a mode return anthropic."""
    print("\n--- Test: Admin Providers Detail No Mode ---")
    p1 = find_free_port()
    tiers = _mode_tiers("anthro")
    vendors = {"anthro": {"url": "http://127.0.0.1:{}".format(p1), "key": "K"}}
    proxy_port, proc, mock_servers, temp_dir, cleanup = _start_admin_proxy(tiers, vendors)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        status, body, _ = _admin_get(proxy_port, "/admin/api/providers-detail")
        if status != 200:
            fail("expected 200, got {}".format(status))
            return
        try:
            data = json.loads(body)
        except Exception:
            fail("providers-detail not JSON: {!r}".format(body[:200]))
            return
        mode = data.get("providers", {}).get("anthro", {}).get("mode")
        if mode != "anthropic":
            fail("expected mode anthropic for mode-less provider, got {!r}".format(mode))
        else:
            pass_("mode-less provider reports anthropic")
    finally:
        cleanup()




def test_admin_providers_detail_forbidden():
    """providers-detail is rejected for non-localhost clients."""
    print("\n--- Test: Admin Providers Detail Forbidden ---")
    p1 = find_free_port()
    tiers = _mode_tiers("anthro")
    vendors = {"anthro": {"url": "http://127.0.0.1:{}".format(p1), "key": "K"}}
    proxy_port, proc, mock_servers, temp_dir, cleanup = _start_admin_proxy(tiers, vendors)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        try:
            status, body, _ = _admin_get(proxy_port, "/admin/api/providers-detail", source_ip="127.0.0.2")
        except OSError as e:
            fail("cannot bind alternate loopback source: {} — environment limited".format(e))
            return
        if status != 403:
            fail("expected 403 for non-localhost client, got {} ({})".format(status, body[:100]))
        else:
            pass_("non-localhost providers-detail request rejected")
    finally:
        cleanup()




def test_admin_providers_detail_invalid_mode_normalized():
    """Unknown mode in keys is normalized to anthropic in the admin endpoint."""
    print("\n--- Test: Admin Providers Detail Invalid Mode Normalized ---")
    p1 = find_free_port()
    tiers = _mode_tiers("anthro")
    vendors = {"anthro": {"url": "http://127.0.0.1:{}".format(p1), "key": "K", "mode": "watermelon"}}
    proxy_port, proc, mock_servers, temp_dir, cleanup = _start_admin_proxy(tiers, vendors)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        # Server must still start (mode validation is warn-only) and normalize display
        status, body, _ = _admin_get(proxy_port, "/admin/api/providers-detail")
        if status != 200:
            fail("expected 200, got {}".format(status))
            return
        try:
            data = json.loads(body)
        except Exception:
            fail("providers-detail not JSON: {!r}".format(body[:200]))
            return
        mode = data.get("providers", {}).get("anthro", {}).get("mode")
        if mode != "anthropic":
            fail("expected unknown mode normalized to anthropic, got {!r}".format(mode))
        else:
            pass_("unknown mode displayed as anthropic")
    finally:
        cleanup()


ALL_TESTS = [
    ("admin-page-served", test_admin_page_served),
    ("admin-api-config", test_admin_api_config),
    ("admin-api-switch", test_admin_api_switch),
    ("admin-api-switch-invalid-provider", test_admin_api_switch_invalid_provider),
    ("admin-api-switch-preserves-models", test_admin_api_switch_preserves_models),
    ("admin-api-csrf-rejected", test_admin_api_csrf_rejected),
    ("admin-api-csrf-null-origin-rejected", test_admin_api_csrf_null_origin_rejected),
    ("admin-api-csrf-missing-origin-rejected", test_admin_api_csrf_missing_origin_rejected),
    ("admin-api-csrf-ipv6-loopback-accepted", test_admin_api_csrf_ipv6_loopback_accepted),
    ("admin-api-switch-missing-tier-rejected", test_admin_api_switch_missing_tier_rejected),
    ("admin-api-reload", test_admin_api_reload),
    ("admin-models-provider-keyed", test_admin_models_provider_keyed),
    ("admin-providers-detail", test_admin_providers_detail),
    ("admin-providers-detail-no-mode", test_admin_providers_detail_no_mode),
    ("admin-providers-detail-forbidden", test_admin_providers_detail_forbidden),
    ("admin-providers-detail-invalid-mode-normalized", test_admin_providers_detail_invalid_mode_normalized),
    ("admin-switch-preserves-disable-retry-flag", test_admin_switch_preserves_disable_retry_flag),
]


if __name__ == "__main__":
    run_cli(ALL_TESTS, "claude-retry-proxy tests: test_admin")
