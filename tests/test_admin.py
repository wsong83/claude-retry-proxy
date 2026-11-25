"""Admin read surface: the served page, the config GET, the CSRF origin rules, providers-detail, and the models catalog.

Part of the claude-retry-proxy suite; runnable standalone.
"""
from _harness import (
    _admin_get,
    _admin_post,
    _create_test_config,
    _create_test_keys,
    _mode_tiers,
    _setup_tier_routing_test,
    _start_admin_proxy,
    _start_proxy_server_directly,
    fail,
    find_free_port,
    pass_,
    run_cli,
)
import json
import shutil
import subprocess
import tempfile


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


# ===========================================================================
# Multi-key provider selection (plan 2026-09-10-multi-key-provider-selection)
# ===========================================================================

def test_admin_providers_detail_returns_key_names():
    """providers-detail returns key NAMES per provider (insertion order for
    object form, ['default'] for string form) and never payloads or url."""
    print("\n--- Test: Admin Providers Detail Key Names ---")
    p1 = find_free_port()
    tiers = _mode_tiers("mkp")
    vendors = {
        "mkp": {"url": "http://127.0.0.1:{}".format(p1), "keys": {"SW": "p1", "CZ": "p2"}},
        "strp": {"url": "http://127.0.0.1:{}".format(find_free_port()), "key": "K-STR"},
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
        if providers.get("mkp", {}).get("keys") == ["SW", "CZ"]:
            pass_("object-form vendor key names == [SW, CZ] in insertion order")
        else:
            fail("expected mkp keys [SW, CZ], got {!r}".format(providers.get("mkp")))
        if providers.get("strp", {}).get("keys") == ["default"]:
            pass_("string-form vendor key names == [default]")
        else:
            fail("expected strp keys [default], got {!r}".format(providers.get("strp")))
        text = body.decode("utf-8", errors="replace")
        leaked = None
        for needle in ("p1", "p2", "K-STR", '"url"', "http://"):
            if needle in text:
                leaked = needle
                break
        if leaked is None:
            pass_("providers-detail leaks no payload or url material")
        else:
            fail("providers-detail leaked {!r}".format(leaked))
    finally:
        cleanup()


def test_admin_html_key_column():
    """admin.html gains a per-tier key <select>, a disabled-select style, a
    static column header row (Provider/Model/Key) above #tiers-container, and
    a populateKeys wired in renderTiers AND the provider onchange."""
    print("\n--- Test: Admin HTML Key Column ---")
    port = find_free_port()
    tiers = _mode_tiers("p")
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(port), "keys": {"SW": "p1", "CZ": "p2"}}}
    proxy_port, proc, mock_servers, temp_dir, cleanup = _start_admin_proxy(tiers, vendors)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        status, body, _ = _admin_get(proxy_port, "/admin/")
        if status != 200:
            fail("expected 200 for /admin/, got {}".format(status))
            return
        html = body.decode("utf-8", errors="replace")

        if '<select id="${tier}-key"' in html:
            pass_("admin.html has a per-tier key <select>")
        else:
            fail("admin.html missing '<select id=\"${tier}-key\"'")

        if "select:disabled" in html:
            pass_("admin.html has the disabled-select CSS rule")
        else:
            fail("admin.html missing 'select:disabled' CSS rule")

        if "providerKeys" in html:
            pass_("admin.html consumes the providers-detail keys list (providerKeys)")
        else:
            fail("admin.html missing providerKeys")

        n_invoke = html.count("populateKeys(")
        if n_invoke >= 2:
            pass_("populateKeys() invoked in {} places (renderTiers + onchange)".format(n_invoke))
        else:
            fail("populateKeys() invoked {} times; expected >= 2 (renderTiers + provider onchange)".format(n_invoke))

        idx_provider = html.find(">Provider<")
        idx_container = html.find("tiers-container")
        if idx_provider != -1 and idx_container != -1 and idx_provider < idx_container \
                and ">Model<" in html and ">Key<" in html:
            pass_("static column header row (Provider/Model/Key) sits above #tiers-container")
        else:
            fail("static header row missing/out of place: >Provider< at {}, tiers-container at {}, "
                 ">Model< present {}, >Key< at {}".format(
                     idx_provider, idx_container, ">Model<" in html, html.find(">Key<")))
    finally:
        cleanup()


ALL_TESTS = [
    ("admin-page-served", test_admin_page_served),
    ("admin-api-config", test_admin_api_config),
    ("admin-api-csrf-rejected", test_admin_api_csrf_rejected),
    ("admin-api-csrf-null-origin-rejected",
     test_admin_api_csrf_null_origin_rejected),
    ("admin-api-csrf-missing-origin-rejected",
     test_admin_api_csrf_missing_origin_rejected),
    ("admin-api-csrf-ipv6-loopback-accepted",
     test_admin_api_csrf_ipv6_loopback_accepted),
    ("admin-models-provider-keyed", test_admin_models_provider_keyed),
    ("admin-providers-detail", test_admin_providers_detail),
    ("admin-providers-detail-no-mode", test_admin_providers_detail_no_mode),
    ("admin-providers-detail-forbidden",
     test_admin_providers_detail_forbidden),
    ("admin-providers-detail-invalid-mode-normalized",
     test_admin_providers_detail_invalid_mode_normalized),
    ("admin-providers-detail-returns-key-names",
     test_admin_providers_detail_returns_key_names),
    ("admin-html-key-column", test_admin_html_key_column),
]


if __name__ == "__main__":
    run_cli(ALL_TESTS, "claude-retry-proxy tests: test_admin")
