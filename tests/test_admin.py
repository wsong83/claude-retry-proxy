"""Admin page and API tests: config GET, switch, CSRF, providers-detail,
models catalog, reload, and flag preservation.

Part of the claude-retry-proxy suite; runnable standalone.
"""

import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time

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
    _send_proxy_request_stream,
    _setup_tier_routing_test,
    _start_admin_proxy,
    _start_mock_upstream,
    _start_proxy_server_directly,
    _trace_events_named,
    _trace_file_in,
    _wait_admin_swapping,
    _wait_for_trace_events,
    _wait_upstream_request,
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

        # Switch sonnet from p1 to p2. The settle sleep lets the baseline
        # request's worker decrement _inflight_count, so the idle drain sees 0.
        time.sleep(0.3)
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
        except Exception:
            fail(f"Switch response not valid JSON: {data}")
            return
        if resp.get("status") == "ok":
            pass_("Admin API switch returned {'status': 'ok'} (200)")
        else:
            fail(f"Switch response missing 'status': 'ok': {data}")
        # The idle case: nothing was in flight at the press, so the drain
        # exits on count == 0 immediately, nothing is evicted, and the three
        # detail fields are facts (drained True, a small waited_s,
        # inflight_at_swap 0).
        if resp.get("drained") is True:
            pass_("Idle switch reports drained=True")
        else:
            fail(f"Idle switch drained must be True, got {resp.get('drained')!r}")
        waited = resp.get("waited_s")
        if isinstance(waited, (int, float)) and not isinstance(waited, bool) \
                and 0 <= waited < 5:
            pass_(f"Idle switch reports a small numeric waited_s ({waited})")
        else:
            fail(f"Idle switch waited_s must be a small number, got {waited!r}")
        if resp.get("inflight_at_swap") == 0:
            pass_("Idle switch reports inflight_at_swap=0")
        else:
            fail(f"Idle switch inflight_at_swap must be 0, got {resp.get('inflight_at_swap')!r}")

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

        # On-disk config.json is tiers-only after the split-aware switch
        config_path = os.path.join(temp_dir, "config.json")
        with open(config_path) as f:
            disk_config = json.load(f)
        missing = [k for k in ("models", "extra_request_headers",
                               "disable_retry_claude_count_token") if k in disk_config]
        if missing:
            fail(f"Catalog keys re-injected into on-disk config.json by the switch: {missing}")
        else:
            pass_("On-disk config.json is tiers-only after the switch")
        disk_tiers = disk_config.get("tiers", {})
        if all(disk_tiers[t].get("provider") == switch_body["tiers"][t]["provider"]
               and disk_tiers[t].get("model") == switch_body["tiers"][t]["model"]
               for t in switch_body["tiers"]):
            pass_("On-disk tiers updated by the switch")
        else:
            fail(f"On-disk tiers changed unexpectedly: {disk_tiers}")
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
    """Reload re-reads the provider catalog from models.json only.

    A catalog edit (a model added to models.json) becomes visible after a
    reload even while config.json on disk is hand-edited in the meantime —
    tiers do NOT follow the disk edit and routing keeps the in-memory
    mapping. A reload whose catalog drops a model a tier is pinned to is
    refused with 400 and performs no swap: the previous catalog stays in
    effect. A missing or malformed models.json is also a 400.
    """
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

        models_path = os.path.join(temp_dir, "models.json")

        # Catalog edit: model-b added to models.json. Simultaneously hand-edit
        # config.json's tiers on disk (sonnet → model-b) — reload must ignore
        # that edit entirely.
        with open(models_path, "w") as f:
            json.dump({"models": {"p": ["claude-haiku-4-5", "claude-opus-5",
                                        "model-a", "model-b"]}}, f)
        tiers_b = dict(tiers_a)
        tiers_b["sonnet"] = {"provider": "p", "model": "model-b"}
        with open(config_path, "w") as f:
            json.dump({"tiers": tiers_b}, f)

        # POST /admin/api/reload
        status, data = _admin_post(proxy_port, "/admin/api/reload", {})
        if status == 200:
            pass_("Admin API reload with an added catalog model returned 200")
        else:
            fail(f"Admin API reload returned {status}: {data}")
            return
        # The reload 200 carries the same drain detail as switch: nothing was
        # in flight at the press, so drained True / inflight_at_swap 0.
        try:
            reload_resp = json.loads(data)
        except Exception:
            fail(f"Reload response not valid JSON: {data}")
            return
        if reload_resp.get("drained") is True:
            pass_("Reload reports drained=True")
        else:
            fail(f"Reload drained must be True, got {reload_resp.get('drained')!r}")
        r_waited = reload_resp.get("waited_s")
        if isinstance(r_waited, (int, float)) and not isinstance(r_waited, bool) \
                and 0 <= r_waited < 5:
            pass_(f"Reload reports a small numeric waited_s ({r_waited})")
        else:
            fail(f"Reload waited_s must be a small number, got {r_waited!r}")
        if reload_resp.get("inflight_at_swap") == 0:
            pass_("Reload reports inflight_at_swap=0")
        else:
            fail(f"Reload inflight_at_swap must be 0, got {reload_resp.get('inflight_at_swap')!r}")

        # GET /admin/api/config: catalog refreshed, tiers NOT from disk edit
        status, body, _ = _admin_get(proxy_port, "/admin/api/config")
        if status != 200:
            fail(f"GET /admin/api/config after reload returned {status}")
            return
        merged = json.loads(body)
        if isinstance(merged.get("models"), dict) \
                and "model-b" in merged["models"].get("p", []):
            pass_("Reload refreshed the catalog from models.json (model-b present)")
        else:
            fail(f"Reloaded catalog missing model-b: {merged.get('models')}")
        if merged.get("tiers", {}).get("sonnet", {}).get("model") == "model-a":
            pass_("Reload tiers stayed in-memory (disk edit not followed)")
        else:
            fail("Reload adopted disk tiers: sonnet={!r}".format(
                merged.get("tiers", {}).get("sonnet")))

        # Post-reload: sonnet still routes to model-a
        status, resp_body = _send_proxy_request(proxy_port, body=json.dumps({
            "model": "sonnet", "messages": [{"role": "user", "content": "hi"}]}))
        if status != 200:
            fail(f"Post-reload request returned {status}")
            return
        if req_list and b"model-a" in req_list[-1]["body"]:
            pass_("Post-reload sonnet request still routes to model-a")
        else:
            fail(f"Post-reload sonnet routing changed. last: {req_list[-1] if req_list else 'none'}")

        # Catalog what drops the tier-pinned model -> 400, no swap
        with open(models_path, "w") as f:
            json.dump({"models": {"p": ["model-b"]}}, f)
        status, data = _admin_post(proxy_port, "/admin/api/reload", {})
        if status == 400 and "not in the reloaded catalog" in data:
            pass_("Reload refused 400 when a tier's model is absent from the catalog")
        else:
            fail(f"expected 400 for a dropped tier model, got {status}: {data[:300]}")

        # Previous catalog still in effect (no swap)
        status, body, _ = _admin_get(proxy_port, "/admin/api/config")
        if status == 200:
            merged = json.loads(body)
            prev = merged.get("models", {}).get("p", [])
            if "model-a" in prev:
                pass_("Refused reload performed no swap (previous catalog in effect)")
            else:
                fail(f"Refused reload swapped anyway (catalog lost model-a): {prev}")
        else:
            fail(f"GET /admin/api/config after refused reload returned {status}")

        # Missing models.json -> 400
        os.remove(models_path)
        status, data = _admin_post(proxy_port, "/admin/api/reload", {})
        if status == 400 and "models" in data:
            pass_("Reload refused 400 with missing models.json")
        else:
            fail(f"expected 400 for missing models.json, got {status}: {data[:300]}")

        # Malformed models.json -> 400
        with open(models_path, "w") as f:
            f.write("{not json")
        status, data = _admin_post(proxy_port, "/admin/api/reload", {})
        if status == 400 and "models" in data:
            pass_("Reload refused 400 with malformed models.json")
        else:
            fail(f"expected 400 for malformed models.json, got {status}: {data[:300]}")
    finally:
        cleanup()


def test_admin_reload_non_dict_extra_tier():
    """A non-dict extra tier (which startup validation lets through) must
    not crash the reload gate: reload answers 400 naming the tier and never
    drops the connection with no response."""
    print("\n--- Test: Admin Reload Non-Dict Extra Tier ---")

    p_port = find_free_port()
    tiers = {
        "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
        "opus": {"provider": "p", "model": "claude-opus-5"},
        # A hand-edited non-dict tier; validate_config type-checks only the
        # three required tiers, so startup accepts it.
        "preview": "claude-x",
    }
    vendors = {"p": {"url": f"http://127.0.0.1:{p_port}", "key": "k"}}

    proxy_port, proc, mock_servers, temp_dir, cleanup = _start_admin_proxy(
        tiers, vendors)
    if proc is None:
        fail("Failed to set up test")
        return

    try:
        status, data = _admin_post(proxy_port, "/admin/api/reload", {})
        if status == 400 and "tier 'preview' is not an object" in data:
            pass_("Non-dict extra tier refused with its own 400")
        elif status == 400:
            fail("Non-dict tier refused but without the pinned message: {!r}".format(
                data[:300]))
        elif status == 200:
            fail("Non-dict extra tier passed the reload gate (gate is not total): "
                 "{!r}".format(data[:300]))
        else:
            fail("Non-dict tier: expected 400, got {}: {!r}".format(status, data[:300]))
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
    """Admin Apply preserves disable_retry_claude_count_token and
    extra_request_headers (one switch flow, both top-level keys) in the
    returned (in-memory) config. After the split the flag and the header
    rules live in models.json, so the on-disk config.json is tiers-only
    and the in-memory preservation is asserted instead (its replacement
    for the former on-disk flag assertion is the loader-precedence case in
    tests/test_config_split.py)."""
    print("\n--- Test: Admin Switch Preserves Top-Level Keys (flag + extra headers) ---")

    upstream_port = find_free_port()
    proxy_port = find_free_port()

    tiers = {
        "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
        "opus": {"provider": "p", "model": "claude-opus-5"},
    }
    vendors = {"p": {"url": f"http://127.0.0.1:{upstream_port}", "key": "k"}}
    seeded_extra = {"p": [{"header": "x-opencode-session", "fallback": "request_id"}]}

    temp_dir = tempfile.mkdtemp(prefix="proxy_drct_admin_test_")
    try:
        config_path = _create_test_config_with_flag(
            temp_dir, tiers, True, extra_request_headers=seeded_extra)
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

            # extra_request_headers survives the switch in the returned
            # (in-memory) config.
            if config.get("extra_request_headers") == seeded_extra:
                pass_("Returned config preserves extra_request_headers")
            else:
                fail(f"Returned config missing/preserved extra_request_headers: "
                     f"{config.get('extra_request_headers')}")

            # On-disk config.json is tiers-only: the flag and the header
            # rules live in models.json now and the split-aware switch
            # never re-injects them.
            with open(config_path) as f:
                disk_config = json.load(f)
            leftovers = [k for k in ("models", "extra_request_headers",
                                     "disable_retry_claude_count_token")
                         if k in disk_config]
            if leftovers:
                fail(f"Catalog/flag keys remain in on-disk config.json after the switch: {leftovers}")
            else:
                pass_("On-disk config.json is tiers-only after the switch")
            posted = json.loads(switch_body)["tiers"]
            disk_tiers = disk_config.get("tiers", {})
            if all(disk_tiers[t].get("provider") == posted[t]["provider"]
                   and disk_tiers[t].get("model") == posted[t]["model"]
                   for t in posted):
                pass_("On-disk tiers updated by the switch")
            else:
                fail(f"On-disk tiers changed unexpectedly: {disk_tiers}")

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


def test_admin_switch_with_key_name():
    """An admin switch carrying a per-tier key selector persists it and routes
    subsequent traffic under the selected key's payload."""
    print("\n--- Test: Admin Switch With Key Name ---")
    port = find_free_port()
    tiers = _mode_tiers("mkp")
    vendors = {"mkp": {"url": "http://127.0.0.1:{}".format(port), "keys": {"SW": "p1", "CZ": "p2"}}}
    proxy_port, proc, mock_servers, temp_dir, cleanup = _start_admin_proxy(tiers, vendors)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        status, _ = _send_proxy_request(proxy_port, body=json.dumps({
            "model": "claude-sonnet-5", "messages": [{"role": "user", "content": "hi"}]}))
        if status != 200:
            fail("baseline request expected 200, got {}".format(status))
            return
        got = mock_servers["mkp"]["requests"][-1]["api_key"]
        if got == "p1":
            pass_("baseline sonnet request used first key payload p1")
        else:
            fail("baseline auth expected p1, got {!r}".format(got))

        switch_body = {"tiers": {
            "haiku": {"provider": "mkp", "model": "claude-haiku-4-5", "key": "SW"},
            "sonnet": {"provider": "mkp", "model": "claude-sonnet-5", "key": "CZ"},
            "opus": {"provider": "mkp", "model": "claude-opus-5", "key": "SW"},
        }}
        status, data = _admin_post(proxy_port, "/admin/api/switch", switch_body)
        if status != 200:
            fail("switch expected 200, got {}: {}".format(status, data))
            return
        pass_("switch with key selector returned 200")

        status, body, _ = _admin_get(proxy_port, "/admin/api/config")
        if status != 200:
            fail("GET config expected 200, got {}".format(status))
            return
        config = json.loads(body)
        if config.get("tiers", {}).get("sonnet", {}).get("key") == "CZ":
            pass_("switch persisted tier key CZ")
        else:
            fail("expected sonnet key CZ in config, got {!r}".format(config.get("tiers", {}).get("sonnet")))

        pre = len(mock_servers["mkp"]["requests"])
        status, _ = _send_proxy_request(proxy_port, body=json.dumps({
            "model": "claude-sonnet-5", "messages": [{"role": "user", "content": "hi"}]}))
        if status != 200:
            fail("post-switch request expected 200, got {}".format(status))
            return
        reqs = mock_servers["mkp"]["requests"][pre:]
        if reqs and reqs[-1]["api_key"] == "p2":
            pass_("post-switch sonnet request used CZ payload p2")
        else:
            fail("expected post-switch auth p2, got {!r}".format(reqs[-1]["api_key"] if reqs else "none"))
    finally:
        cleanup()


def test_admin_switch_unknown_key_rejected():
    """An unknown key name in a switch payload is rejected with a 400 naming
    tier and provider; config is unchanged and the proxy stays live."""
    print("\n--- Test: Admin Switch Unknown Key Rejected ---")
    port = find_free_port()
    tiers = _mode_tiers("mkp")
    vendors = {"mkp": {"url": "http://127.0.0.1:{}".format(port), "keys": {"SW": "p1", "CZ": "p2"}}}
    proxy_port, proc, mock_servers, temp_dir, cleanup = _start_admin_proxy(tiers, vendors)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        switch_body = {"tiers": {
            "haiku": {"provider": "mkp", "model": "claude-haiku-4-5", "key": "SW"},
            "sonnet": {"provider": "mkp", "model": "claude-sonnet-5", "key": "NOPE"},
            "opus": {"provider": "mkp", "model": "claude-opus-5", "key": "SW"},
        }}
        status, data = _admin_post(proxy_port, "/admin/api/switch", switch_body)
        if status == 400 and "NOPE" in data and "sonnet" in data and "mkp" in data:
            pass_("unknown key rejected with 400 naming tier+provider+key")
        else:
            fail("expected 400 citing sonnet/NOPE/mkp, got {} {!r}".format(status, data[:300]))

        status, body, _ = _admin_get(proxy_port, "/admin/api/config")
        config = json.loads(body)
        if "key" not in config.get("tiers", {}).get("sonnet", {}):
            pass_("rejected switch left config unchanged")
        else:
            fail("config changed despite rejected switch: {!r}".format(config.get("tiers", {}).get("sonnet")))

        status, _ = _send_proxy_request(proxy_port, body=json.dumps({
            "model": "claude-sonnet-5", "messages": [{"role": "user", "content": "hi"}]}))
        if status == 200:
            pass_("proxy still serves requests after rejected switch (no wedge)")
        else:
            fail("proxy unhealthy after rejected switch: {}".format(status))
    finally:
        cleanup()


def test_admin_switch_invalid_key_type_rejected():
    """Non-string key values (false/0/[]) in a switch payload are rejected
    with 400 'invalid key name'; config on disk is unchanged."""
    print("\n--- Test: Admin Switch Invalid Key Type Rejected ---")
    port = find_free_port()
    tiers = _mode_tiers("mkp")
    vendors = {"mkp": {"url": "http://127.0.0.1:{}".format(port), "keys": {"SW": "p1", "CZ": "p2"}}}
    proxy_port, proc, mock_servers, temp_dir, cleanup = _start_admin_proxy(tiers, vendors)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        for bad in (False, 0, []):
            switch_body = {"tiers": {
                "haiku": {"provider": "mkp", "model": "claude-haiku-4-5", "key": "SW"},
                "sonnet": {"provider": "mkp", "model": "claude-sonnet-5", "key": bad},
                "opus": {"provider": "mkp", "model": "claude-opus-5", "key": "SW"},
            }}
            status, data = _admin_post(proxy_port, "/admin/api/switch", switch_body)
            if status == 400:
                pass_("non-string key {!r} rejected (400)".format(bad))
            else:
                fail("expected 400 for key {!r}, got {} {!r}".format(bad, status, data[:200]))

        status, body, _ = _admin_get(proxy_port, "/admin/api/config")
        config = json.loads(body)
        if "key" not in config.get("tiers", {}).get("sonnet", {}):
            pass_("rejected invalid-key switches left config unchanged")
        else:
            fail("config changed despite rejected switches: {!r}".format(config.get("tiers", {}).get("sonnet")))
    finally:
        cleanup()


def test_admin_switch_missing_key_defaults():
    """A switch body without key selectors succeeds and the persisted config
    gains the provider's first key name (canonical config on disk)."""
    print("\n--- Test: Admin Switch Missing Key Defaults ---")
    port = find_free_port()
    tiers = _mode_tiers("mkp")
    vendors = {"mkp": {"url": "http://127.0.0.1:{}".format(port), "keys": {"SW": "p1", "CZ": "p2"}}}
    proxy_port, proc, mock_servers, temp_dir, cleanup = _start_admin_proxy(tiers, vendors)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        switch_body = {"tiers": {
            "haiku": {"provider": "mkp", "model": "claude-haiku-4-5"},
            "sonnet": {"provider": "mkp", "model": "claude-sonnet-5"},
            "opus": {"provider": "mkp", "model": "claude-opus-5"},
        }}
        status, data = _admin_post(proxy_port, "/admin/api/switch", switch_body)
        if status != 200:
            fail("switch without key expected 200, got {}: {}".format(status, data))
            return
        status, body, _ = _admin_get(proxy_port, "/admin/api/config")
        config = json.loads(body)
        tiers_cfg = config.get("tiers", {})
        if all(tiers_cfg.get(t, {}).get("key") == "SW" for t in ("haiku", "sonnet", "opus")):
            pass_("missing key defaults persisted as first key name 'SW'")
        else:
            fail("expected all tiers key=SW after switch, got {!r}".format(tiers_cfg))
        with open(os.path.join(temp_dir, "config.json")) as f:
            disk = json.load(f)
        if all(disk.get("tiers", {}).get(t, {}).get("key") == "SW" for t in ("haiku", "sonnet", "opus")):
            pass_("on-disk config.json carries the defaulted key names")
        else:
            fail("on-disk config missing defaulted keys: {!r}".format(disk.get("tiers")))
    finally:
        cleanup()


def test_admin_switch_validates_key_names():
    """Key-name validation moved to the switch path (reload no longer reads
    tiers from disk, so a bad key on disk is never seen by reload): a switch
    with an unknown key name refuses with 400; a valid key name switches and
    the tier keeps its explicit key."""
    print("\n--- Test: Admin Switch Validates Key Names ---")
    port = find_free_port()
    tiers = {
        "haiku": {"provider": "mkp", "model": "claude-haiku-4-5", "key": "SW"},
        "sonnet": {"provider": "mkp", "model": "claude-sonnet-5", "key": "CZ"},
        "opus": {"provider": "mkp", "model": "claude-opus-5", "key": "SW"},
    }
    vendors = {"mkp": {"url": "http://127.0.0.1:{}".format(port), "keys": {"SW": "p1", "CZ": "p2"}}}

    temp_dir = tempfile.mkdtemp(prefix="proxy_admin_reload_key_")
    proxy_port = find_free_port()
    config_path = _create_test_config(temp_dir, tiers, models=_derive_models_from_tiers(tiers))
    keys_path = _create_test_keys_plain(temp_dir, vendors)

    req_list = []
    mock_servers = {"mkp": {"server": _start_mock_upstream(port, req_list), "requests": req_list}}
    trace_fd, trace_file = tempfile.mkstemp(suffix=".jsonl", dir=temp_dir)
    os.close(trace_fd)
    proc, probe_ok = _start_proxy_server_directly(
        proxy_port, config_path=config_path, keys_path=keys_path,
        passphrase=None, trace_file=trace_file)
    if not probe_ok:
        mock_servers["mkp"]["server"].shutdown()
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
        mock_servers["mkp"]["server"].shutdown()
        shutil.rmtree(temp_dir, ignore_errors=True)

    def switch_tiers(tiers_cfg):
        return _admin_post(proxy_port, "/admin/api/switch", {"tiers": tiers_cfg})

    try:
        bad_tiers = {
            "haiku": {"provider": "mkp", "model": "claude-haiku-4-5", "key": "SW"},
            "sonnet": {"provider": "mkp", "model": "claude-sonnet-5", "key": "NOPE"},
            "opus": {"provider": "mkp", "model": "claude-opus-5", "key": "SW"},
        }
        status, data = switch_tiers(bad_tiers)
        if status == 400 and "NOPE" in data:
            pass_("switch rejects an unknown key name (400)")
        else:
            fail("expected switch 400 for unknown key, got {} {!r}".format(status, data[:300]))

        # After a refused switch the config is untouched
        status, data = _admin_post(proxy_port, "/admin/api/reload", {})
        if status == 200:
            pass_("reload succeeds with an untouched config after the refused switch")
        else:
            fail("expected reload 200 after refused switch, got {} {!r}".format(
                status, data[:300]))

        fixed_tiers = {
            "haiku": {"provider": "mkp", "model": "claude-haiku-4-5", "key": "SW"},
            "sonnet": {"provider": "mkp", "model": "claude-sonnet-5", "key": "CZ"},
            "opus": {"provider": "mkp", "model": "claude-opus-5", "key": "SW"},
        }
        status, data = switch_tiers(fixed_tiers)
        if status == 200:
            pass_("switch succeeds with valid key names")
        else:
            fail("expected switch 200, got {} {!r}".format(status, data[:300]))
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


# ===========================================================================
# Config-swap drain: silence-based drain, retryable eviction, single-flight
# (plan 2026-10-12-swap-silence-drain)
# ===========================================================================

# The swap tests drive a 2 s silence budget; the 30 s default would make every
# one of them silently run at 30 s (and read budget_s 30 from the status
# endpoint). The drain's quiet window is budget + _SWAP_QUIET_GRACE(2 s).
_SWAP_BUDGET_ENV = {"PROXY_SWAP_SILENCE_TIMEOUT": "2"}


def _anthropic_sse(*events):
    """Serialize anthropic-mode SSE frames (`event: <type>` + data + blank line)."""
    out = bytearray()
    for ev in events:
        out += ("event: " + ev["type"] + "\ndata: " + json.dumps(ev) + "\n\n").encode()
    return bytes(out)


def _msg_start(model="claude-sonnet-5"):
    return {"type": "message_start", "message": {
        "id": "msg_swap", "type": "message", "role": "assistant",
        "content": [], "model": model, "stop_reason": None, "stop_sequence": None,
        "usage": {"input_tokens": 1, "output_tokens": 0}}}


def _text_delta(text, index=0):
    return {"type": "content_block_delta", "index": index,
            "delta": {"type": "text_delta", "text": text}}


def _msg_stop():
    return {"type": "message_stop"}


def _switch_body(sonnet_provider):
    """A complete three-tier switch body moving sonnet to `sonnet_provider`."""
    return {"tiers": {
        "haiku": {"provider": "p1", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": sonnet_provider, "model": "claude-sonnet-5"},
        "opus": {"provider": "p1", "model": "claude-opus-5"},
    }}


def _swap_proxy(streamers=None, responders=None, extra_env=None,
                provider_names=("p1", "p2"), models=None):
    """Start an admin proxy for the swap tests: sonnet -> p1, p2 (and extras) available.

    `streamers` maps vendor -> handler_fn(handler, info) for a fixture-driven
    streaming upstream; `responders` maps vendor -> responder(info). extra_env
    defaults to a 2 s swap silence budget. `models` overrides the provider
    catalog written to models.json (the concurrent-press test sizes it to widen
    the reload handler's pre-press window deterministically).

    Returns (proxy_port, proc, mock_servers, temp_dir, trace_file, cleanup).
    """
    tiers = {
        "haiku": {"provider": "p1", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "p1", "model": "claude-sonnet-5"},
        "opus": {"provider": "p1", "model": "claude-opus-5"},
    }
    vendors = {}
    for name in provider_names:
        vendors[name] = {"url": "http://127.0.0.1:{}".format(find_free_port()),
                         "key": "k-" + name}
    env = dict(_SWAP_BUDGET_ENV)
    if extra_env:
        env.update(extra_env)
    proxy_port, proc, mock_servers, temp_dir, cleanup = _start_admin_proxy(
        tiers, vendors, models=models, extra_env=env, responders=responders,
        streamers=streamers)
    return (proxy_port, proc, mock_servers, temp_dir,
            _trace_file_in(temp_dir), cleanup)


def _stream_request_in_thread(port, out, body=None):
    """POST a request on a background thread; the result lands in out['result']."""
    if body is None:
        body = {"model": "sonnet", "stream": True,
                "messages": [{"role": "user", "content": "hi"}]}

    def worker():
        try:
            out["result"] = _send_proxy_request_stream(port, body)
        except Exception as e:
            out["result"] = (0, "", str(e).encode())

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    return t


def _admin_get_json(proxy_port, path):
    """GET an admin endpoint and decode JSON; returns (status, payload|None)."""
    status, body, _ = _admin_get(proxy_port, path)
    try:
        return status, json.loads(body)
    except Exception:
        return status, None


def test_switch_succeeds_during_long_live_stream():
    """A continuously-streaming request in flight at the press is waited to
    completion, not killed — the plan's "live work is waited to completion,
    unbounded by wall-clock".

    The stream runs 6.0 s (10 chunks at 0.6 s), deliberately LONGER than the
    drain's quiet window (budget + _SWAP_QUIET_GRACE = 4 s): chunks arrive
    every 0.6 s against a 2 s budget, so the shared activity clock never reads
    quiet and the drain must exit on count == 0 when the stream ends. Asserts
    the switch 200 carries drained True / inflight_at_swap 1, the client
    received the COMPLETE stream, and a post-switch request routes to the new
    provider."""
    print("\n--- Test: Switch Waits Out a Long Live Stream ---")
    n_chunks = 10
    gap = 0.6
    first_chunk = threading.Event()

    def streamer(handler, info):
        handler.send_response(200)
        handler.send_header("Content-Type", "text/event-stream")
        handler.end_headers()
        handler.wfile.write(_anthropic_sse(_msg_start()))
        handler.wfile.flush()
        first_chunk.set()
        for i in range(n_chunks):
            time.sleep(gap)
            handler.wfile.write(_anthropic_sse(_text_delta("chunk-{}".format(i))))
            handler.wfile.flush()
        handler.wfile.write(_anthropic_sse(_msg_stop()))
        handler.wfile.flush()

    proxy_port, proc, mock_servers, temp_dir, trace_file, cleanup = _swap_proxy(
        streamers={"p1": streamer})
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        out = {}
        client = _stream_request_in_thread(proxy_port, out)
        if not first_chunk.wait(5):
            fail("upstream never streamed its first chunk")
            return
        status, data = _admin_post(
            proxy_port, "/admin/api/switch", _switch_body("p2"), timeout=30)
        client.join(20)
        if status != 200:
            fail("switch during a live stream returned {}: {}".format(status, data))
            return
        resp = json.loads(data)
        if resp.get("drained") is not True:
            fail("a waited-out live stream must report drained True, got {!r}".format(
                resp.get("drained")))
            return
        if not isinstance(resp.get("waited_s"), (int, float)) or resp["waited_s"] > 20:
            fail("waited_s must be a small number, got {!r}".format(resp.get("waited_s")))
            return
        if resp.get("inflight_at_swap") != 1:
            fail("inflight_at_swap must be 1, got {!r}".format(resp.get("inflight_at_swap")))
            return
        cstatus, _ctype, raw = out.get("result", (0, "", b""))
        if cstatus != 200:
            fail("client stream status {}, expected 200".format(cstatus))
            return
        missing = [i for i in range(n_chunks)
                   if ("chunk-{}".format(i)).encode() not in raw]
        if missing:
            fail("client stream is incomplete; missing chunks {}".format(missing))
            return
        if b"message_stop" not in raw:
            fail("client stream lacks message_stop")
            return
        if _trace_events_named(trace_file, "swap_abort"):
            fail("a waited-out live stream must not be evicted")
            return
        st, _ = _send_proxy_request(proxy_port, body=json.dumps(
            {"model": "sonnet", "messages": [{"role": "user", "content": "hi"}]}))
        if st == 200 and len(mock_servers["p2"]["requests"]) == 1:
            pass_("switch waited the live stream to completion; client got all {} "
                  "chunks; post-switch routes to p2".format(n_chunks))
        else:
            fail("post-switch routing wrong: status {}, p2 calls {}".format(
                st, len(mock_servers["p2"]["requests"])))
    finally:
        cleanup()


def test_switch_evicts_silent_stream():
    """A stream that emits a byte AFTER the press and then goes silent is
    evicted at the armed budget. drained False is deterministic because the
    drain's quiet window is budget + _SWAP_QUIET_GRACE while the armed wake is
    budget — if this flakes, that ordering is broken."""
    print("\n--- Test: Switch Evicts a Silent Stream ---")
    budget = 2
    grace = 2
    post_press_byte = threading.Event()

    def streamer(handler, info):
        handler.send_response(200)
        handler.send_header("Content-Type", "text/event-stream")
        handler.end_headers()
        handler.wfile.write(_anthropic_sse(_msg_start()))
        handler.wfile.flush()
        # The fixture shape matters: a straggler that was already silent before
        # the press is a LATE exit (see the dedicated test). This one emits a
        # byte after the press, so the loop's next read is armed at the budget
        # while _config_swapping is True — its wake is deterministic.
        post_press_byte.wait(15)
        handler.wfile.write(_anthropic_sse(_text_delta("post-press")))
        handler.wfile.flush()
        time.sleep(30)  # hold silently

    proxy_port, proc, mock_servers, temp_dir, trace_file, cleanup = _swap_proxy(
        streamers={"p1": streamer})
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        out = {}
        client = _stream_request_in_thread(proxy_port, out)
        if not _wait_upstream_request(mock_servers, "p1"):
            fail("upstream never received the stream request")
            return
        switch_out = {}
        sw = threading.Thread(
            target=lambda: switch_out.update(
                zip(("status", "data"), _admin_post(
                    proxy_port, "/admin/api/switch", _switch_body("p2")))),
            daemon=True)
        sw.start()
        if _wait_admin_swapping(proxy_port) is None:
            fail("swap never became visible on /admin/api/swap-status")
            return
        post_press_byte.set()
        t0 = time.time()
        sw.join(20)
        elapsed = time.time() - t0
        client.join(20)
        status = switch_out.get("status")
        data = switch_out.get("data")
        if status != 200:
            fail("switch of a silent stream returned {}: {}".format(status, data))
            return
        if not (budget <= elapsed <= budget + grace + 8):
            fail("switch returned after {:.1f}s, outside [{}s, {}s]".format(
                elapsed, budget, budget + grace + 8))
            return
        resp = json.loads(data)
        if resp.get("drained") is not False:
            fail("an eviction must report drained False, got {!r}".format(resp.get("drained")))
            return
        if resp.get("inflight_at_swap") != 1:
            fail("inflight_at_swap must be 1, got {!r}".format(resp.get("inflight_at_swap")))
            return
        cstatus, _ctype, raw = out.get("result", (0, "", b""))
        if cstatus != 200:
            fail("client stream status {}, expected 200".format(cstatus))
            return
        if b"post-press" not in raw:
            fail("the post-press chunk must reach the client before eviction")
            return
        if b"config swap in progress" not in raw:
            fail("evicted stream must end with the retryable config_swap_restart error")
            return
        if b"message_stop" in raw:
            fail("an evicted stream must not carry a normal terminal")
            return
        aborts = _wait_for_trace_events(trace_file, "swap_abort")
        stream_aborts = [e for e in aborts if e.get("phase") == "stream"]
        if not stream_aborts:
            fail("no swap_abort event with phase 'stream'; got {}".format(aborts))
            return
        st, _ = _send_proxy_request(proxy_port, body=json.dumps(
            {"model": "sonnet", "messages": [{"role": "user", "content": "hi"}]}))
        if st == 200 and len(mock_servers["p2"]["requests"]) == 1:
            pass_("silent post-press stream evicted in {:.1f}s; drained False; "
                  "client got the retryable error; post-switch routes to p2".format(elapsed))
        else:
            fail("post-switch routing wrong: status {}, p2 calls {}".format(
                st, len(mock_servers["p2"]["requests"])))
    finally:
        cleanup()


def test_switch_silent_before_press_is_late_exit():
    """The accepted late-exit boundary, pinned so it is not mistaken for a bug —
    plus the shared-clock discrimination that stops it passing for the wrong
    reason.

    Boundary: the straggler's upstream sends two chunks then holds the socket
    open silently; the press lands while its loop is ALREADY blocked in its
    read (armed at the connection's 300 s timeout, not the budget), so the
    drain cannot evict it. The client-side error lands at the straggler's own
    wake, so this test does not assert its timing — it asserts only that the
    old-routing bytes delivered at that wake are not forwarded (the epoch check
    fires before the forward).

    Clock discrimination: a SECOND request is in flight and keeps emitting a
    sub-budget cadence past the press, for longer than the drain's quiet window
    (budget + _SWAP_QUIET_GRACE). The quiet window is measured from the last
    upstream byte across ALL in-flight requests, so the drain cannot exit while
    that cadence runs: waited_s must exceed the quiet window (a drain reading a
    press-stamped local exits at exactly budget + grace), and the concurrently
    live request must be waited to completion rather than evicted."""
    print("\n--- Test: Silent-Before-Press Stream Is a Late Exit ---")
    quiet_window = 2 + 2      # SETTINGS.swap_silence_timeout + _SWAP_QUIET_GRACE
    live_gap = 0.4
    live_chunks = 13          # 5.2 s — deliberately longer than quiet_window
    late_wake = threading.Event()
    live_first = threading.Event()

    def streamer(handler, info):
        handler.send_response(200)
        handler.send_header("Content-Type", "text/event-stream")
        handler.end_headers()
        if b"STRAGGLER" in info.get("body", b""):
            # Both pre-press chunks land immediately, so the proxy's next read
            # blocks BEFORE the press and is armed at the connection's 300 s
            # timeout — the un-wakeable read this boundary is about.
            handler.wfile.write(_anthropic_sse(_msg_start(), _text_delta("pre-press")))
            handler.wfile.flush()
            late_wake.wait(30)
            handler.wfile.write(_anthropic_sse(_text_delta("OLD-ROUTING-MARKER")))
            handler.wfile.flush()
            return
        # The concurrently-live request: a sub-budget cadence keeps refreshing
        # the shared activity clock well past the press.
        handler.wfile.write(_anthropic_sse(_msg_start()))
        handler.wfile.flush()
        live_first.set()
        for i in range(live_chunks):
            time.sleep(live_gap)
            handler.wfile.write(_anthropic_sse(_text_delta("live-{}".format(i))))
            handler.wfile.flush()
        handler.wfile.write(_anthropic_sse(_msg_stop()))
        handler.wfile.flush()

    proxy_port, proc, mock_servers, temp_dir, trace_file, cleanup = _swap_proxy(
        streamers={"p1": streamer})
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        live_out = {}
        live = _stream_request_in_thread(proxy_port, live_out, body={
            "model": "sonnet", "stream": True,
            "messages": [{"role": "user", "content": "LIVE"}]})
        if not live_first.wait(5):
            fail("the concurrently-live request never streamed")
            return
        out = {}
        client = _stream_request_in_thread(proxy_port, out, body={
            "model": "sonnet", "stream": True,
            "messages": [{"role": "user", "content": "STRAGGLER"}]})
        deadline = time.time() + 5
        while len(mock_servers["p1"]["requests"]) < 2 and time.time() < deadline:
            time.sleep(0.05)
        if len(mock_servers["p1"]["requests"]) < 2:
            fail("upstream never received both requests")
            return
        time.sleep(0.4)  # let the proxy forward the chunks and block in read
        t0 = time.time()
        status, data = _admin_post(
            proxy_port, "/admin/api/switch", _switch_body("p2"), timeout=30)
        elapsed = time.time() - t0
        if status != 200:
            fail("switch of a late-exit straggler returned {}: {}".format(status, data))
            return
        if elapsed > 20:
            fail("the quiet path must terminate, took {:.1f}s".format(elapsed))
            return
        resp = json.loads(data)
        if resp.get("drained") is not True:
            fail("nothing is evicted during the drain, so drained must be True, got {!r}".format(
                resp.get("drained")))
            return
        if resp.get("inflight_at_swap") != 2:
            fail("both requests are in flight at the press, so inflight_at_swap "
                 "must be 2, got {!r}".format(resp.get("inflight_at_swap")))
            return
        waited = resp.get("waited_s")
        if not isinstance(waited, (int, float)) or waited < quiet_window + 1.5:
            fail("the drain must be measured from the last upstream byte, not "
                 "from the press: waited_s {!r} is inside the {}s quiet window "
                 "while upstream bytes were still arriving".format(
                     waited, quiet_window))
            return
        live.join(20)
        lstatus, _ltype, lraw = live_out.get("result", (0, "", b""))
        if lstatus != 200 or b"message_stop" not in lraw:
            fail("the concurrently-live request must be waited to completion "
                 "(status {}, {} bytes, tail {!r})".format(lstatus, len(lraw), lraw[-160:]))
            return
        if b"config_swap_restart" in lraw:
            fail("the concurrently-live request was evicted by the drain")
            return
        # Drive the straggler's own wake cheaply: the swap is complete, so the
        # marker chunk must be rejected by the epoch check, not forwarded.
        late_wake.set()
        client.join(20)
        cstatus, _ctype, raw = out.get("result", (0, "", b""))
        if cstatus != 200:
            fail("client stream status {}, expected 200".format(cstatus))
            return
        if b"pre-press" not in raw:
            fail("the pre-press chunk must reach the client")
            return
        if b"OLD-ROUTING-MARKER" in raw:
            fail("old-routing bytes were forwarded after the swap")
            return
        if b"config swap in progress" not in raw:
            fail("the straggler must close with the retryable config_swap_restart error")
            return
        st, _ = _send_proxy_request(proxy_port, body=json.dumps(
            {"model": "sonnet", "messages": [{"role": "user", "content": "hi"}]}))
        if st == 200 and len(mock_servers["p2"]["requests"]) == 1:
            pass_("late-exit boundary pinned under the shared clock: switch 200 in "
                  "{:.1f}s, drained True, live stream completed, no old-routing "
                  "bytes after the wake, post-switch routes to p2".format(elapsed))
        else:
            fail("post-switch routing wrong: status {}, p2 calls {}".format(
                st, len(mock_servers["p2"]["requests"])))
    finally:
        late_wake.set()
        cleanup()


def test_switch_abandons_retry_chain():
    """A request sleeping in 429 backoff (PROXY_MAX_DELAY high) abandons at the
    press: it returns 503 config_swap_restart within a sleep slice, well under
    the backoff, the switch returns 200 quickly, a swap_abort event with phase
    'retry_chain' lands, and no 'retry' event is logged for the sleep the chain
    never took (the accounting follows the completed sleep)."""
    print("\n--- Test: Switch Abandons a Retry Chain ---")

    def p1_429(info):
        return (429, "application/json",
                b'{"type":"error","error":{"type":"rate_limit_error","message":"slow down"}}')

    proxy_port, proc, mock_servers, temp_dir, trace_file, cleanup = _swap_proxy(
        responders={"p1": p1_429},
        extra_env={"PROXY_MAX_DELAY": "30", "PROXY_MAX_RETRIES": "5"})
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        out = {}
        client = _stream_request_in_thread(proxy_port, out, body={
            "model": "sonnet", "messages": [{"role": "user", "content": "hi"}]})
        if not _wait_upstream_request(mock_servers, "p1"):
            fail("upstream never received the request")
            return
        time.sleep(0.4)  # the chain is now inside _interruptible_sleep
        t0 = time.time()
        status, data = _admin_post(proxy_port, "/admin/api/switch", _switch_body("p2"))
        switch_elapsed = time.time() - t0
        client.join(15)
        if status != 200:
            fail("switch during a backoff chain returned {}: {}".format(status, data))
            return
        if switch_elapsed > 5:
            fail("switch must return promptly once the chain abandons, took {:.1f}s".format(
                switch_elapsed))
            return
        cstatus, _ctype, raw = out.get("result", (0, "", b""))
        if cstatus != 503:
            fail("abandoned chain must return 503, got {}".format(cstatus))
            return
        if b"config_swap_restart" not in raw:
            fail("abandoned chain body must carry config_swap_restart: {!r}".format(raw[:300]))
            return
        if not _wait_for_trace_events(trace_file, "swap_abort"):
            fail("no swap_abort event for the abandoned chain")
            return
        phases = {e.get("phase") for e in _trace_events_named(trace_file, "swap_abort")}
        if "retry_chain" not in phases:
            fail("swap_abort phases {} must include retry_chain".format(phases))
            return
        retry_events = _trace_events_named(trace_file, "retry")
        if retry_events:
            fail("an abandoned chain must not log a retry it never took: {}".format(retry_events))
            return
        st, _ = _send_proxy_request(proxy_port, body=json.dumps(
            {"model": "sonnet", "messages": [{"role": "user", "content": "hi"}]}))
        if st == 200 and len(mock_servers["p2"]["requests"]) == 1:
            pass_("chain abandoned at the press (503 config_swap_restart in {:.1f}s, "
                  "no phantom retry); re-issue routes to p2".format(switch_elapsed))
        else:
            fail("re-issue routing wrong: status {}, p2 calls {}".format(
                st, len(mock_servers["p2"]["requests"])))
    finally:
        cleanup()


def test_switch_straggler_pre_first_byte_fails_retryably():
    """An upstream that answers long after the quiet-drain swap fails the
    straggler retryably: the switch returns 200 (drained True) on the quiet
    window, and when the upstream finally answers the client gets 503
    config_swap_restart and NEVER the marker body (no old-routing content
    after the swap)."""
    print("\n--- Test: Pre-First-Byte Straggler Fails Retryably ---")
    # Hold past the quiet window (budget + grace = 4 s) so the answer lands
    # after the epoch bump — the pre_first_byte checkpoint.
    hold = 6.0

    def streamer(handler, info):
        time.sleep(hold)
        body = json.dumps({
            "id": "ok", "type": "message", "role": "assistant",
            "model": "claude-sonnet-5",
            "content": [{"type": "text", "text": "MARKER-OLD-ROUTING"}],
            "stop_reason": "end_turn", "stop_sequence": None,
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }).encode()
        handler.send_response(200)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)

    proxy_port, proc, mock_servers, temp_dir, trace_file, cleanup = _swap_proxy(
        streamers={"p1": streamer})
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        out = {}
        client = _stream_request_in_thread(proxy_port, out, body={
            "model": "sonnet", "messages": [{"role": "user", "content": "hi"}]})
        if not _wait_upstream_request(mock_servers, "p1"):
            fail("upstream never received the request")
            return
        time.sleep(0.3)  # the request is blocked in getresponse()
        status, data = _admin_post(proxy_port, "/admin/api/switch", _switch_body("p2"))
        if status != 200:
            fail("switch returned {}: {}".format(status, data))
            return
        resp = json.loads(data)
        if resp.get("drained") is not True:
            fail("nothing is evicted during the drain, so drained must be True, got {!r}".format(
                resp.get("drained")))
            return
        if resp.get("inflight_at_swap") != 1:
            fail("inflight_at_swap must be 1, got {!r}".format(resp.get("inflight_at_swap")))
            return
        client.join(20)
        cstatus, _ctype, raw = out.get("result", (0, "", b""))
        if cstatus != 503:
            fail("straggler must return 503, got {}: {!r}".format(cstatus, raw[:300]))
            return
        if b"config_swap_restart" not in raw:
            fail("straggler body must carry config_swap_restart: {!r}".format(raw[:300]))
            return
        if b"MARKER-OLD-ROUTING" in raw:
            fail("the old-routing marker body reached the client after the swap")
            return
        phases = {e.get("phase") for e in _wait_for_trace_events(trace_file, "swap_abort")}
        if "pre_first_byte" not in phases:
            fail("swap_abort phases {} must include pre_first_byte".format(phases))
            return
        pass_("post-quiet-window answer failed retryably (503 config_swap_restart); "
              "no old-routing body delivered")
    finally:
        cleanup()


def test_swap_status_endpoint():
    """GET /admin/api/swap-status: during a held-stream drain it reports
    swapping True, inflight >= 1, numeric waited_s/silence_s and the configured
    budget_s; when idle it reports swapping False with both nullable fields
    null (asserted as null, not a TypeError-shaped 500 — the per-field guard
    is what buys that).

    Clock discrimination: the fixture keeps a sub-budget upstream cadence alive
    for LONGER than the drain's quiet window (budget + _SWAP_QUIET_GRACE) and
    the status is polled again after that window has elapsed. A drain reading a
    press-stamped local has exited by then — swapping False, and the live
    stream cut with the retryable error; a drain reading the shared activity
    clock (which any upstream byte refreshes) is still waiting, so swapping
    must still be True with silence_s reading fresh. Asserted against the
    plan's semantics, never against the current behaviour."""
    print("\n--- Test: Swap Status Endpoint ---")
    budget = 2
    quiet_window = budget + 2      # budget + _SWAP_QUIET_GRACE
    first_chunk = threading.Event()
    stop_streaming = threading.Event()

    def streamer(handler, info):
        handler.send_response(200)
        handler.send_header("Content-Type", "text/event-stream")
        handler.end_headers()
        handler.wfile.write(_anthropic_sse(_msg_start()))
        handler.wfile.flush()
        first_chunk.set()
        i = 0
        # A sub-budget cadence: every read returns a byte well inside the armed
        # budget, and every byte refreshes the shared activity clock.
        while not stop_streaming.is_set():
            time.sleep(0.4)
            handler.wfile.write(_anthropic_sse(_text_delta("live-{}".format(i))))
            handler.wfile.flush()
            i += 1
        handler.wfile.write(_anthropic_sse(_msg_stop()))
        handler.wfile.flush()

    proxy_port, proc, mock_servers, temp_dir, trace_file, cleanup = _swap_proxy(
        streamers={"p1": streamer})
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        out = {}
        client = _stream_request_in_thread(proxy_port, out)
        if not first_chunk.wait(5):
            fail("upstream never streamed")
            return
        switch_out = {}
        sw = threading.Thread(
            target=lambda: switch_out.update(
                zip(("status", "data"), _admin_post(
                    proxy_port, "/admin/api/switch", _switch_body("p2"),
                    timeout=30))),
            daemon=True)
        sw.start()
        during = _wait_admin_swapping(proxy_port)
        if during is None:
            fail("swap never became visible on /admin/api/swap-status")
            return
        if during.get("inflight", 0) < 1:
            fail("during a held drain inflight must be >= 1, got {!r}".format(during.get("inflight")))
            return
        for field in ("waited_s", "silence_s"):
            val = during.get(field)
            if isinstance(val, (int, float)) and not isinstance(val, bool) and val >= 0:
                pass_("during drain: {} is numeric ({:.2f})".format(field, val))
            else:
                fail("during drain: {} must be numeric, got {!r}".format(field, val))
                return
        if during.get("budget_s") != budget:
            fail("budget_s must read the configured {}s, got {!r}".format(
                budget, during.get("budget_s")))
            return
        # Poll again once a press-stamped drain would have exited, with the
        # cadence still running: the shared clock must read fresh.
        time.sleep(quiet_window + 1.0)
        after = _admin_get_json(proxy_port, "/admin/api/swap-status")[1] or {}
        if after.get("swapping") is not True:
            fail("swapping must still be True once the quiet window has elapsed "
                 "while upstream bytes keep arriving (a press-stamped drain "
                 "reads itself quiet by then); got {!r}".format(after))
            return
        silence = after.get("silence_s")
        if not isinstance(silence, (int, float)) or isinstance(silence, bool) or silence >= budget:
            fail("silence_s must read the shared clock as fresh while bytes "
                 "arrive, got {!r}".format(silence))
            return
        pass_("clock discrimination: swapping still True and silence_s {:.2f}s "
              "after {:.1f}s of continuous upstream bytes".format(
                  silence, quiet_window + 1.0))
        stop_streaming.set()
        sw.join(30)
        if switch_out.get("status") != 200:
            fail("switch returned {}: {}".format(
                switch_out.get("status"), switch_out.get("data")))
            return
        resp = json.loads(switch_out.get("data"))
        if resp.get("drained") is not True or resp.get("inflight_at_swap") != 1:
            fail("a waited-out live stream must report drained True and "
                 "inflight_at_swap 1, got {!r}".format(resp))
            return
        client.join(20)
        cstatus, _ctype, raw = out.get("result", (0, "", b""))
        if cstatus != 200 or b"message_stop" not in raw:
            fail("the live stream must be waited to completion (status {}, "
                 "{} bytes, tail {!r})".format(cstatus, len(raw), raw[-160:]))
            return
        if b"config_swap_restart" in raw:
            fail("a waited-out live stream must never be evicted")
            return
        status, idle = _admin_get_json(proxy_port, "/admin/api/swap-status")
        if status != 200:
            fail("idle swap-status returned {} (a per-field guard failure 500s it)".format(status))
            return
        if idle.get("swapping") is not False:
            fail("idle swapping must be False, got {!r}".format(idle.get("swapping")))
            return
        if idle.get("waited_s") is not None or idle.get("silence_s") is not None:
            fail("idle nullable fields must be null, got waited_s={!r} silence_s={!r}".format(
                idle.get("waited_s"), idle.get("silence_s")))
            return
        pass_("swap-status reports live drain detail, null idle fields, and a "
              "waited-out live stream")
    finally:
        stop_streaming.set()
        cleanup()


def test_second_press_refused_409():
    """Swaps are single-flight: while a drain runs a second press (switch or
    reload) is refused 409 config_swap_in_progress and enters no drain. The
    first press's effect is the only one that lands — asserted through its
    observable trace, since the epoch itself is not exposed: the refused press
    changes no routing (two successive post-swap checks both route to p2) and
    p3 receives nothing.

    The in-flight stream deliberately outlives the drain's quiet window, so
    "the in-flight stream must be unaffected" is asserted against a drain that
    would otherwise have evicted it."""
    print("\n--- Test: Second Press Refused 409 ---")
    first_chunk = threading.Event()

    def streamer(handler, info):
        handler.send_response(200)
        handler.send_header("Content-Type", "text/event-stream")
        handler.end_headers()
        handler.wfile.write(_anthropic_sse(_msg_start()))
        handler.wfile.flush()
        first_chunk.set()
        # ~5 s of live work, deliberately LONGER than the drain's quiet window
        # (budget + _SWAP_QUIET_GRACE = 4 s), so "the in-flight stream must be
        # unaffected" is a real assertion rather than a timing accident: a drain
        # reading a press-stamped clock exits at the quiet window and evicts it.
        for i in range(13):  # 13 x 0.4 s = 5.2 s
            time.sleep(0.4)
            handler.wfile.write(_anthropic_sse(_text_delta("live-{}".format(i))))
            handler.wfile.flush()
        handler.wfile.write(_anthropic_sse(_msg_stop()))
        handler.wfile.flush()

    proxy_port, proc, mock_servers, temp_dir, trace_file, cleanup = _swap_proxy(
        streamers={"p1": streamer}, provider_names=("p1", "p2", "p3"))
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        out = {}
        client = _stream_request_in_thread(proxy_port, out)
        if not first_chunk.wait(5):
            fail("upstream never streamed its first chunk")
            return
        first = {}
        t1 = threading.Thread(
            target=lambda: first.update(
                zip(("status", "data"), _admin_post(
                    proxy_port, "/admin/api/switch", _switch_body("p2")))),
            daemon=True)
        t1.start()
        if _wait_admin_swapping(proxy_port) is None:
            fail("first swap never became visible")
            return
        s2, d2 = _admin_post(proxy_port, "/admin/api/switch", _switch_body("p3"))
        if s2 == 409 and b"config_swap_in_progress" in d2.encode():
            pass_("second switch refused 409 config_swap_in_progress")
        else:
            fail("second switch must be refused 409, got {}: {}".format(s2, d2))
        s3, d3 = _admin_post(proxy_port, "/admin/api/reload", {})
        if s3 == 409 and b"config_swap_in_progress" in d3.encode():
            pass_("concurrent reload refused 409 (shared single-flight)")
        else:
            fail("reload must share the single-flight guard, got {}: {}".format(s3, d3))
        t1.join(20)
        client.join(20)
        if first.get("status") != 200:
            fail("first switch returned {}: {}".format(first.get("status"), first.get("data")))
            return
        cstatus, _ctype, raw = out.get("result", (0, "", b""))
        if cstatus != 200 or b"message_stop" not in raw:
            fail("the in-flight stream must be unaffected (status {}, {} bytes, tail {!r})".format(
                cstatus, len(raw), raw[-160:]))
            return
        checks = []
        for _ in range(2):
            st, _ = _send_proxy_request(proxy_port, body=json.dumps(
                {"model": "sonnet", "messages": [{"role": "user", "content": "hi"}]}))
            checks.append((st, len(mock_servers["p2"]["requests"]),
                           len(mock_servers["p3"]["requests"])))
        if all(st == 200 and p2 >= 1 and p3 == 0 for st, p2, p3 in checks):
            pass_("only the first press landed: two successive checks route to p2, p3 untouched")
        else:
            fail("routing wrong across the two checks: {}".format(checks))
    finally:
        cleanup()


def test_concurrent_presses_single_flight():
    """Single-flight in the CONCURRENT window — the race
    `test_second_press_refused_409` cannot see, because that test issues its
    second press only after the first press has landed.

    A reload is issued first and a switch ~20 ms later, while a silent stream
    holds the in-flight count. The reload handler performs models.json file I/O
    plus the membership/validate gate BEFORE it presses, so any guard that is a
    separate step from the press is passed by BOTH presses inside that gap —
    the reviewer's probe opened it at 3 ms. Only an atomic check-and-set refuses
    one. The reload's catalog is sized so its pre-press work measures ~90 ms
    rather than a coin-flip few ms, while the switch — pressing early, inside
    that gap — holds the single-flight flag for the drain's whole quiet window
    (budget + _SWAP_QUIET_GRACE, i.e. 4 s at the 2 s test budget). The switch
    therefore still holds the flag when the reload reaches its press, which is
    the ordering the filler below drives.

    Asserts (the two branch comments carry the per-outcome detail):
      - the outcome is one 200 + one 409, or — if a scheduling flip put the
        switch's ENTIRE cycle before the reload's gated tier read, so the two
        swaps were sequential rather than concurrent — two sequential 200s;
      - every 409 carries the Anthropic error envelope (type=error,
        error.type=api_error, a non-empty error.code and a request_id) and its
        code is one of the two legitimate refusals: the single-flight
        `config_swap_in_progress`, or `config_reload_stale` (the reload's
        Phase-3 epoch guard refusing a candidate that predates a switch that
        completed in its gate-to-install window);
      - in the one-200 outcome the epoch bumped exactly once. It is not exposed
        on the admin surface, so it is pinned by its two observable
        consequences: exactly one 200 is exactly one bump (the increment lives
        only in the 200 swap body — the 409 and 400 refusals return before
        Phase 3, and the 500 disk-failure path performs no swap and no bump),
        and the survivor's mapping is in force;
      - the surviving press's mapping is the one in force afterwards, checked
        twice over: a leaked second press applies its own (stale) mapping after
        the first — the silent revert the reviewer measured — which moves the
        routing off the survivor's provider. That mapping check is what catches
        the revert in both outcomes.
    """
    print("\n--- Test: Concurrent Presses Are Single-Flight ---")
    quiet_window = 2 + 2      # SETTINGS.swap_silence_timeout + _SWAP_QUIET_GRACE
    # A catalog big enough that the reload handler's load + membership gate
    # reliably outlasts the second press's arrival (measured ~90 ms here against
    # a press gap whose jitter is tens of ms).
    filler = ["m%06d" % i for i in range(400000)]
    tier_models = ["claude-haiku-4-5", "claude-sonnet-5", "claude-opus-5"]
    models = {"p1": tier_models + filler, "p2": list(tier_models)}

    def streamer(handler, info):
        if b"SILENT" not in info.get("body", b""):
            # A route-check probe: answer promptly so EITHER survivor's
            # provider can be probed after the swap.
            body = json.dumps({
                "id": "ok", "type": "message", "role": "assistant",
                "model": "claude-sonnet-5",
                "content": [{"type": "text", "text": "ok"}],
                "stop_reason": "end_turn", "stop_sequence": None,
                "usage": {"input_tokens": 1, "output_tokens": 1},
            }).encode()
            handler.send_response(200)
            handler.send_header("Content-Type", "application/json")
            handler.send_header("Content-Length", str(len(body)))
            handler.end_headers()
            handler.wfile.write(body)
            return
        handler.send_response(200)
        handler.send_header("Content-Type", "text/event-stream")
        handler.end_headers()
        handler.wfile.write(_anthropic_sse(_msg_start()))
        handler.wfile.flush()
        time.sleep(30)  # hold silently: the drain exits on the quiet window

    proxy_port, proc, mock_servers, temp_dir, trace_file, cleanup = _swap_proxy(
        streamers={"p1": streamer, "p2": streamer}, models=models)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        out = {}
        client = _stream_request_in_thread(proxy_port, out, body={
            "model": "sonnet", "stream": True,
            "messages": [{"role": "user", "content": "SILENT"}]})
        if not _wait_upstream_request(mock_servers, "p1"):
            fail("upstream never received the stream request")
            return

        reload_out = {}
        switch_out = {}

        def do_reload():
            try:
                reload_out.update(zip(("status", "data"), _admin_post(
                    proxy_port, "/admin/api/reload", {}, timeout=30)))
            except Exception as e:
                reload_out["error"] = str(e)

        def do_switch():
            try:
                switch_out.update(zip(("status", "data"), _admin_post(
                    proxy_port, "/admin/api/switch", _switch_body("p2"),
                    timeout=30)))
            except Exception as e:
                switch_out["error"] = str(e)

        tr = threading.Thread(target=do_reload, daemon=True)
        tr.start()
        # A head start sized well inside the reload's measured pre-press gap
        # (~90 ms) but comfortably past the inter-thread scheduling jitter, so
        # the guard ORDER is deterministic and the race — not the jitter — is
        # what the assertions exercise.
        time.sleep(0.02)
        ts = threading.Thread(target=do_switch, daemon=True)
        ts.start()
        tr.join(40)
        ts.join(40)

        reload_status = reload_out.get("status")
        switch_status = switch_out.get("status")
        statuses = sorted(c for c in (reload_status, switch_status) if c is not None)
        # Two outcomes are consistent with an atomic single-flight guard:
        #   [200, 409] — the switch pressed inside the reload's pre-press window
        #                and the reload was refused. This is the ordering the
        #                filler below drives.
        #   [200, 200] — a scheduling flip put the switch's ENTIRE cycle before
        #                the reload's gated tier read, so the two swaps were
        #                sequential rather than concurrent and both landed
        #                legitimately. Rejecting this would misattribute a
        #                scheduling change on a correct tree to the
        #                single-flight defect (the re-review's finding 2).
        # Anything else — a 500, a hung press, a missing status — is a real
        # failure.
        if statuses not in ([200, 409], [200, 200]):
            fail("concurrent presses must be one 200 + one 409 (a refusal) or two "
                 "sequential 200s (the switch completed before the reload pressed); "
                 "anything else means a drain failed or two drains ran concurrently "
                 "for one logical change; got reload={} switch={}".format(
                     reload_status, switch_status))
            return
        if 409 in statuses:
            refused = reload_out if reload_status == 409 else switch_out
            # Either 409 code is a correct refusal: the single-flight
            # config_swap_in_progress, or the stale-candidate
            # config_reload_stale the reload's Phase-3 epoch guard emits when a
            # switch completed between its gated tier read and its install
            # (server.py:3567 capture, :3638 compare). Asserting the envelope
            # SHAPE rather than one code by name keeps a correct refusal from
            # being misdiagnosed as the single-flight defect.
            try:
                env = json.loads(refused.get("data", ""))
            except Exception:
                env = None
            err = env.get("error") if isinstance(env, dict) else None
            if not isinstance(err, dict) or env.get("type") != "error" \
                    or err.get("type") != "api_error" or not err.get("code") \
                    or not env.get("request_id"):
                fail("the refused press must carry the Anthropic error envelope "
                     "(type=error, error.type=api_error, a non-empty error.code and a "
                     "request_id): {!r}".format(refused.get("data", "")))
                return
            if err["code"] not in ("config_swap_in_progress", "config_reload_stale"):
                fail("the refused press carries 409 code {!r}; expected "
                     "config_swap_in_progress (single-flight) or config_reload_stale "
                     "(stale candidate)".format(err["code"]))
                return
            winner = switch_out if switch_status == 200 else reload_out
            survivor_provider = "p2" if switch_status == 200 else "p1"
            resp = json.loads(winner.get("data", "{}"))
            if resp.get("inflight_at_swap") != 1:
                fail("the in-flight stream must be counted at the press, got {!r}".format(
                    resp.get("inflight_at_swap")))
                return
            if not isinstance(resp.get("waited_s"), (int, float)) or resp["waited_s"] < 3:
                fail("the winning drain must have waited out the quiet window while "
                     "the silent stream held the count, got waited_s {!r}".format(
                         resp.get("waited_s")))
                return
            outcome = "exactly one 200 + one 409 ({})".format(err["code"])
        else:
            # Both swaps landed, sequentially: the switch installed sonnet -> p2,
            # and the reload's candidate — read from _current_config after that
            # install, or the reload's own Phase-3 guard would have refused it
            # config_reload_stale — carries the SAME mapping. The mapping in
            # force must therefore still be p2.
            survivor_provider = "p2"
            outcome = ("two sequential 200s (the switch completed before the reload "
                       "pressed)")

        # The epoch is not exposed; its consequences are. In the one-200 outcome
        # that is one bump plus the survivor's mapping in force; in the two-200
        # outcome it is two bumps — one per landed press, both legitimate because
        # the presses were sequential — and again the surviving mapping in force.
        # Checked twice over: a leaked second press applies its own (stale)
        # mapping after the first, the silent revert the reviewer measured, which
        # shows as routing moving off the survivor's provider.
        p1_before = len(mock_servers["p1"]["requests"])
        p2_before = len(mock_servers["p2"]["requests"])
        for _ in range(2):
            st, _b = _send_proxy_request(proxy_port, body=json.dumps(
                {"model": "sonnet", "messages": [{"role": "user", "content": "hi"}]}))
            if st != 200:
                fail("post-swap route check returned {}".format(st))
                return
            time.sleep(0.1)
        p1_after = len(mock_servers["p1"]["requests"]) - p1_before
        p2_after = len(mock_servers["p2"]["requests"]) - p2_before
        if survivor_provider == "p2":
            ok = (p2_after == 2 and p1_after == 0)
            detail = "the switch's mapping is in force, so both checks must reach p2"
        else:
            ok = (p1_after == 2 and p2_after == 0)
            detail = "the reload survived (tiers unchanged), so both checks must stay on p1"
        if not ok:
            fail("{}; got p1={} p2={} — routing moved off the surviving press's "
                 "mapping (a leaked second press reverting it)".format(
                     detail, p1_after, p2_after))
            return
        # The straggler pieces are parked; cleanup kills the proxy.
        client.join(0.1)
        pass_("concurrent presses: {}; both route checks stayed on {} (mapping "
              "not reverted)".format(outcome, survivor_provider))
    finally:
        cleanup()


def test_reload_does_not_revert_concurrent_switch():
    """The reload's stale-candidate epoch guard (re-review finding
    review-2-reload-stale-candidate), driven DETERMINISTICALLY in-process.

    The guard closes the window between the reload's gated tier read
    (`gated_epoch = _config_epoch`, captured in the SAME `_config_lock`
    acquisition that reads the candidate's tiers — server.py:3567) and Phase 3's
    compare-and-install (`if _config_epoch != gated_epoch:` — server.py:3638).
    A /admin/api/switch that completes its whole press -> drain -> swap ->
    release cycle inside that window must not have its mapping silently
    reverted by the reload installing its stale candidate.

    That interleaving cannot be driven from outside the process: the window
    between the gate's lock release and the reload's press is a few bytecodes
    wide, and a test that depended on winning that scheduling race would flake
    on a CORRECT tree — the reviewer could not reproduce it in 15 attempts.
    This test therefore drives the guard's PRECONDITION deterministically
    instead: it monkeypatches `_drain_for_swap` — the one call the reload
    handler makes between its gate and Phase 3 — to simulate a switch that
    completed inside the window (clearing the flag, installing the switch's
    tiers, bumping the epoch), then invokes the reload handler in-process via
    the `object.__new__(srv.ProxyHandler)` pattern used elsewhere in the suite.
    Phase 3 must refuse 409 `config_reload_stale`, install nothing and bump
    nothing.

    Deleting the guard (or a defaulted `epoch`) fails this test twice over: the
    status becomes 200, and `_current_config` is reverted to the pre-switch
    tiers. The module globals the handler reads are saved and restored in a
    `finally` so the in-process state cannot leak into a later test.
    """
    print("\n--- Test: Reload Does Not Revert a Concurrent Switch ---")
    import claude_retry_proxy.server as srv

    temp_dir = tempfile.mkdtemp()
    try:
        original_tiers = _switch_body("p1")["tiers"]
        switch_tiers = _switch_body("p2")["tiers"]
        with open(os.path.join(temp_dir, "models.json"), "w", encoding="utf-8") as f:
            json.dump({"models": {
                "p1": ["claude-haiku-4-5", "claude-sonnet-5", "claude-opus-5"],
                "p2": ["claude-sonnet-5"],
            }}, f)
        config_path = os.path.join(temp_dir, "config.json")
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump({"tiers": original_tiers}, f)

        saved = {name: getattr(srv, name) for name in (
            "_config_path", "_current_config", "_config_epoch", "_vendors",
            "_config_swapping", "_inflight_count", "_swap_evictions")}
        saved_drain = srv._drain_for_swap
        try:
            srv._config_path = config_path
            srv._current_config = {"tiers": original_tiers}
            srv._config_epoch = 5
            srv._vendors = {
                "p1": {"url": "http://127.0.0.1:1", "key": "k-p1"},
                "p2": {"url": "http://127.0.0.1:2", "key": "k-p2"},
            }
            srv._config_swapping = False
            srv._inflight_count = 0
            srv._swap_evictions = 0

            def concurrent_switch_completes():
                # The interleaving the guard exists for: a switch presses, swaps
                # and releases entirely between the reload's gated tier read and
                # its Phase-3 install. `candidate` still holds `original_tiers`.
                srv._config_swapping = True
                srv._current_config = {"tiers": switch_tiers}
                srv._config_epoch = 6
                srv._config_swapping = False
                return (True, 0, 0.0)

            srv._drain_for_swap = concurrent_switch_completes

            captured = []
            handler = object.__new__(srv.ProxyHandler)
            handler.path = "/admin/api/reload"
            handler.client_address = ("127.0.0.1", 55555)
            handler.headers = {
                "Content-Length": "0",
                "Origin": "http://127.0.0.1:{}".format(srv.SETTINGS.port),
            }
            handler.rfile = io.BytesIO(b"")
            handler.wfile = io.BytesIO()
            handler._send_response = (
                lambda status, body, headers=None: captured.append((status, body)))
            handler.do_POST()

            if not captured:
                fail("the reload handler sent no response")
                return
            status, body = captured[-1]
            if status != 409:
                fail("installing a candidate that predates a completed switch must "
                     "be refused 409; got {} (body {!r}) — the epoch guard did not "
                     "fire".format(status, body[:200].decode("utf-8", "replace")))
                return
            try:
                parsed = json.loads(body)
            except Exception as e:
                fail("the refusal body is not JSON: {} ({!r})".format(e, body[:200]))
                return
            err = parsed.get("error") if isinstance(parsed, dict) else None
            if not isinstance(err, dict) or err.get("code") != "config_reload_stale":
                fail("expected the stale-candidate refusal error.code "
                     "config_reload_stale, got {!r}".format(parsed))
                return
            if parsed.get("type") != "error" or err.get("type") != "api_error" \
                    or not parsed.get("request_id"):
                fail("the refusal must carry the Anthropic envelope (type=error, "
                     "error.type=api_error, a request_id): {!r}".format(parsed))
                return
            if srv._current_config != {"tiers": switch_tiers}:
                fail("the reload REVERTED the switch's mapping: _current_config is "
                     "{!r}, expected the switch's tiers {!r}".format(
                         srv._current_config, {"tiers": switch_tiers}))
                return
            if srv._config_epoch != 6:
                fail("a refused reload must not bump the epoch; got {}".format(
                    srv._config_epoch))
                return
            pass_("reload refused 409 config_reload_stale; the switch's mapping "
                  "survived and no epoch bump was taken")
        finally:
            srv._drain_for_swap = saved_drain
            for name, value in saved.items():
                setattr(srv, name, value)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _js_braced_block(text, start):
    """Extract the brace-balanced block beginning at the first '{' at or after
    `start`, braces included ('' when absent or unbalanced).

    The one brace-walker in this module: `_js_function_body` delegates here.
    Correct for the JS it is pointed at — the blocks scanned carry no
    unbalanced brace inside a string literal, and the one template literal in
    reach (`${tier}`) contributes a matched pair, so the depth count lands on
    the right closing brace. An unbalanced brace in a string would defeat it;
    re-check that if one is ever added.
    """
    open_at = text.find("{", start)
    if open_at == -1:
        return ""
    depth = 0
    for i in range(open_at, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[open_at:i + 1]
    return ""


def _js_function_body(text, header):
    """Extract a function's body by brace matching ('' when absent).

    Lets an assertion hold INSIDE a named function rather than somewhere in
    the file — the difference between "the helper does this" and "something
    does". See _js_braced_block for what the depth count can and cannot handle.
    """
    start = text.find(header)
    if start == -1:
        return ""
    return _js_braced_block(text, start)


# The three swap-status poll callbacks, each identified by the function that
# encloses it, with the done-guard it must carry. Asserted BY BLOCK IDENTITY
# rather than by scanning a candidate set: a candidate scan passes a mutant
# where every block guards on one flag, and in that mutant both press paths
# lose their real `swapSettled` re-check (review suggestion 6). The two press
# blocks bail out on `swapSettled`; the attach watcher added by
# 2026-10-15-admin-apply-status compares the generation it captured, so a late
# response from a stale watcher can only bail out.
#
# Identity is POSITIONAL — the enclosing function — because the two press
# callbacks are byte-identical (both repaint `applying — `) and neither
# contains its own function's fetch: the switch/reload POST lives outside the
# interval, in the enclosing handler. A name marker inside the block would
# therefore have to be something the block does not carry.
_POLL_BLOCK_OWNERS = (
    ("async function saveConfig(", "saveConfig press", "if (swapSettled)"),
    ("async function reloadConfig(", "reloadConfig press", "if (swapSettled)"),
    ("function attachToInFlightSwap(", "attach watcher",
     "if (myGeneration !== attachGeneration)"),
)


def test_admin_html_poll_guard_after_await():
    """Every swap-status poll callback re-checks its own done-guard AFTER its
    awaits and before the pending-status repaint (re-review finding
    review-2-stale-poll-overwrites-terminal, fixed in coder round 5; the third
    block and its guard come from 2026-10-15-admin-apply-status).

    A 1 Hz poll response generated while `swapping` was true can resolve after
    the press wrote its terminal status line; without the post-await re-check the
    poll's `showStatus('pending', 'applying — waiting for …')` overwrites that
    line, and the interval is cleared in the same `finally`, so no later poll
    corrects it. The same hazard applies to the attach watcher's terminal line.

    THREE BLOCKS, THREE GUARDS, ASSERTED BY BLOCK IDENTITY: the page carries one
    poll callback per press path (saveConfig, reloadConfig) and one in the attach
    watcher. The press blocks re-check `swapSettled`; the attach block re-checks
    the generation it captured. Each block is first identified by the enclosing
    function, so a mutant that guards every block on one flag — which would
    strip the press paths' real post-await re-check while still satisfying a
    candidate scan — fails here (review suggestion 6).

    WHAT THIS PINS, AND WHAT IT DOES NOT: the page ships no JS test harness and
    the suite is pure Python, so the runtime behaviour (a late poll does not
    repaint) is not exercised here — that is verified by reading the callbacks.
    What this test pins is the ORDERING the fixes introduced, on the page the
    proxy actually serves: in each poll callback the guard must sit between the
    response parse and the repaint, and the top-of-callback guard must still be
    there beside it. Deleting the post-await check fails this test; nothing
    else in the suite would notice.
    """
    print("\n--- Test: Admin HTML Poll Guard Sits After the Awaits ---")
    port = find_free_port()
    tiers = _mode_tiers("p")
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(port), "key": "K"}}
    proxy_port, proc, mock_servers, temp_dir, cleanup = _start_admin_proxy(
        tiers, vendors)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        status, body, _ = _admin_get(proxy_port, "/admin/")
        if status != 200:
            fail("expected 200 for /admin/, got {}".format(status))
            return
        html = body.decode("utf-8", errors="replace")

        blocks = list(re.finditer(
            r"setInterval\(async \(\) => \{(.*?)\},\s*\d+\);", html, re.S))
        if len(blocks) != 3:
            fail("expected 3 poll callbacks (saveConfig, reloadConfig, the "
                 "attach watcher), found {}".format(len(blocks)))
            return

        # Identify each block by the function enclosing it: the guard a block
        # must carry is only meaningful once the block is known.
        regions = []
        for header, kind, _guard in _POLL_BLOCK_OWNERS:
            at = html.find(header)
            if at == -1:
                fail("the {} function is not defined, so its poll callback "
                     "cannot be identified".format(kind))
                return
            regions.append((at, kind))
        regions.sort()

        by_kind = {}
        for match in blocks:
            owners = [kind for at, kind in regions if at <= match.start()]
            if not owners:
                fail("a poll callback at offset {} sits before every known "
                     "poll owner".format(match.start()))
                return
            # The innermost enclosing owner wins: a nested interval would
            # otherwise be attributed to its outer function.
            kind = owners[-1]
            if kind in by_kind:
                fail("two poll callbacks are attributed to the same owner "
                     "({}); expected one each for {}".format(
                         kind, [o[1] for o in _POLL_BLOCK_OWNERS]))
                return
            by_kind[kind] = match.group(1)
        if len(by_kind) != len(_POLL_BLOCK_OWNERS):
            fail("expected one poll callback each for {}, found {}".format(
                [o[1] for o in _POLL_BLOCK_OWNERS], sorted(by_kind)))
            return

        guards = {kind: guard for _h, kind, guard in _POLL_BLOCK_OWNERS}
        for kind, block in sorted(by_kind.items()):
            guard = guards[kind]
            if block.count(guard) < 2:
                fail("{}: expected the {!r} done-guard BOTH at the top of the "
                     "callback and after the awaits; found {} occurrence(s) — a "
                     "press block guarded on anything but swapSettled has lost "
                     "its real post-await re-check".format(
                         kind, guard, block.count(guard)))
                return
            parts = block.split("await resp.json()", 1)
            if len(parts) != 2:
                fail("{}: no 'await resp.json()' response parse".format(kind))
                return
            tail = parts[1]
            guard_pos = tail.find(guard)
            repaint_pos = tail.find("showStatus")
            if guard_pos == -1:
                fail("{}: the {!r} re-check is missing from the post-await "
                     "tail".format(kind, guard))
                return
            if repaint_pos != -1 and guard_pos > repaint_pos:
                fail("{}: the {!r} re-check sits AFTER the repaint — a late "
                     "poll response would overwrite the terminal status "
                     "line".format(kind, guard))
                return
            pass_("{}: top-of-callback guard + post-await {!r} re-check before "
                  "the repaint".format(kind, guard))
    finally:
        cleanup()


def test_admin_html_pending_status_styled():
    """The served admin page paints a VISIBLE pending status, locks the whole
    switch surface while a swap is in play, and detects a swap it did not
    press (plan 2026-10-15-admin-apply-status).

    The defect this plan fixes was invisible from every other test: the
    pending line was emitted as `showStatus('', …)`, so `className` became
    `status ` and no CSS rule ever assigned it `display: block` — every
    pending message rendered with zero height. Nothing in the suite served
    the page and looked at the pending state's style or at the call shape, so
    the page could regress to a silently blank status line with the whole
    suite green.

    WHAT THIS PINS, AND WHAT IT DOES NOT: the served HTML's structure — the
    styled pending rule, the compound disabled-button selector, the absence of
    empty-type calls, the pending call-site count, the attach watcher and its
    load-time counterpart, the button ids, the select-inclusive lockout with
    its single-key restore and its arming on both press paths, the poll-failure
    signal, the completion re-render, the gating of the completion's unlock and
    success line on a successful re-read, the reload path's stale-refusal
    re-read with its gated unlock, the attach watcher's pre-repaint settled
    bail, the load path's own gate (its re-read result captured, its failure
    branch locking and returning over a possibly-pre-swap row, and its
    post-await press-guard re-check), and the operator-guidance strings. It
    does NOT pin runtime behaviour:
    the page ships no JS harness, so that a pending line is actually visible in
    a browser, that a press is actually refused while a swap runs, and that the
    lockout actually restores the operator's controls are read from source
    ordering, not exercised.

    The code-shape patterns are quote-agnostic (`'pending'` / `"pending"`) and
    the lockout's field list is matched loosely, so a cosmetic re-quote fails
    with a truthful message rather than a misleading one (review suggestion 10).
    The `config_reload_stale` discriminator is matched the same way (review
    F4), so a behaviour-identical re-quote cannot blank the (m)-(o) extraction
    and report a branch that could not be read when the branch is there.
    """
    print("\n--- Test: Admin HTML Pending Status Styled ---")
    port = find_free_port()
    tiers = _mode_tiers("p")
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(port), "key": "K"}}
    proxy_port, proc, mock_servers, temp_dir, cleanup = _start_admin_proxy(
        tiers, vendors)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        status, body, _ = _admin_get(proxy_port, "/admin/")
        if status != 200:
            fail("expected 200 for /admin/, got {}".format(status))
            return
        html = body.decode("utf-8", errors="replace")

        # (a) The pending state is styled visible. `.status` alone is
        # display:none; only the state rules re-enable it, and before this
        # plan none of them matched the pending class.
        if re.search(r"\.status\.pending\s*\{[^}]*display\s*:\s*block", html):
            pass_("(a) the .status.pending rule assigns display: block")
        else:
            fail("(a) no `.status.pending` rule with `display: block` — every "
                 "pending message would render invisible (zero height)")

        # (b) The disabled-button rule outranks `button.secondary:hover`.
        # `button.secondary:hover` scores (0,2,1) and beats a bare
        # `button:disabled` (0,1,1) whatever the source order, so the compound
        # selector is required or a disabled Reload button under the pointer
        # keeps painting the enabled hover colour. Scoped to the rule(s) that
        # mention button:disabled — the page has an unrelated select:disabled.
        disabled_sels = [sel.strip() for sel, _b
                         in re.findall(r"([^{}]+)\{([^}]*)\}", html)
                         if "button:disabled" in sel]
        if disabled_sels and any("button.secondary:disabled:hover" in s
                                 for s in disabled_sels):
            pass_("(b) the disabled-button rule lists button:disabled AND "
                  "button.secondary:disabled:hover")
        else:
            fail("(b) the disabled-button rule does not outrank "
                 "button.secondary:hover; selector list(s): {!r}".format(
                     disabled_sels))

        # (c) No pending message uses the empty type. This call shape is the
        # exact defect the plan fixes, and nothing else in the suite would
        # have caught it.
        empty_calls = re.findall(r"showStatus\(\s*(?:''|\"\")", html)
        if not empty_calls:
            pass_("(c) no empty-type showStatus('') call remains")
        else:
            fail("(c) {} empty-type showStatus('') call(s) remain — the call "
                 "shape that rendered the pending line "
                 "invisible".format(len(empty_calls)))

        # (d) Pending lines at their call sites: 2 press entry paints + 2
        # press repaints + 3 attach-watcher paints (entry, repaint, failed
        # re-read) + the poll-failure line. A threshold of 4 is satisfied by
        # the press sites alone, so it would pass with the watcher's paints
        # deleted. Quote-agnostic, so a cosmetic re-quote does not fail this
        # with a message about a missing watcher (review suggestion 10).
        pending_sites = len(re.findall(r"showStatus\(\s*['\"]pending['\"]",
                                       html))
        if pending_sites >= 6:
            pass_("(d) showStatus('pending') at {} call sites (>= 6)".format(
                pending_sites))
        else:
            fail("(d) showStatus('pending') at {} call sites; expected >= 6 "
                 "(2 press entry + 2 press repaint + 2 attach "
                 "watcher)".format(pending_sites))

        # (e) The attach watcher and the load-time detection exist and are
        # wired in: definition + both 409 branches + the load check for the
        # watcher, definition + its loadConfig call for the check.
        attach_def = "function attachToInFlightSwap(" in html
        load_def = "function checkInFlightSwapOnLoad(" in html
        attach_n = html.count("attachToInFlightSwap(")
        load_n = html.count("checkInFlightSwapOnLoad(")
        if attach_def and load_def and attach_n >= 4 and load_n >= 2:
            pass_("(e) attachToInFlightSwap and checkInFlightSwapOnLoad are "
                  "defined and invoked ({} / {} occurrences)".format(
                      attach_n, load_n))
        else:
            fail("(e) attach watcher/load check incomplete: defined "
                 "attach={} load={}, occurrences attach={} load={} "
                 "(expected >= 4 / >= 2)".format(
                     attach_def, load_def, attach_n, load_n))

        # (f) Both control ids the lockout addresses.
        if 'id="apply-btn"' in html and 'id="reload-btn"' in html:
            pass_("(f) both button ids present (apply-btn, reload-btn)")
        else:
            fail("(f) missing button id(s): apply-btn={} reload-btn={}".format(
                'id="apply-btn"' in html, 'id="reload-btn"' in html))

        # (g) The lockout reaches the nine tier selects, not just the buttons.
        # Asserted INSIDE the helper: the provider/model/key loop and
        # `keys.length <= 1` both already exist elsewhere (populateKeys), so a
        # file-wide search would pass on the pre-change tree. The field list is
        # matched loosely rather than as one exact literal, so a re-quote or a
        # re-space of the array does not report a missing lockout (review
        # suggestion 10).
        lock_body = _js_function_body(html, "function setSwapControlsDisabled(")
        if not lock_body:
            fail("(g) the setSwapControlsDisabled helper is not defined")
        else:
            if (re.search(r"for\s*\(\s*const\s+field\s+of\s*\[\s*"
                          r"['\"]provider['\"]\s*,\s*['\"]model['\"]\s*,\s*"
                          r"['\"]key['\"]\s*\]", lock_body)
                    and re.search(r"tier\s*\+\s*['\"]-['\"]\s*\+\s*field",
                                  lock_body)):
                pass_("(g) the lockout iterates the nine tier selects "
                      "(provider/model/key)")
            else:
                fail("(g) the lockout does not reach the tier selects — the "
                     "buttons are locked but the selects stay editable, which "
                     "is what makes the completion re-render unsafe")
            if re.search(r"keys\.length\s*<=\s*1", lock_body):
                pass_("(g) unlocking restores populateKeys' single-key rule "
                      "(keys.length <= 1)")
            else:
                fail("(g) unlocking does not restore the single-key rule — a "
                     "blanket unlock would wrongly enable a single-key "
                     "provider's key select")

        # (h) A persistently failing attach poll is signalled rather than
        # swallowed: on that path a successful `swapping: false` read is the
        # watcher's only exit and nothing else unlocks the controls.
        if ("function noteAttachPollFailure(" in html
                and html.count("noteAttachPollFailure(") >= 3):
            pass_("(h) noteAttachPollFailure is defined and invoked at {} call "
                  "sites".format(html.count("noteAttachPollFailure(")))
        else:
            fail("(h) noteAttachPollFailure incomplete: defined={}, "
                 "occurrences={} (expected >= 3)".format(
                     "function noteAttachPollFailure(" in html,
                     html.count("noteAttachPollFailure(")))
        if re.search(r"attachPollFailures\s*===\s*\d+", html):
            pass_("(h) the attach poll-failure threshold constant is present")
        else:
            fail("(h) no `attachPollFailures === <n>` threshold — the "
                 "poll-failure line would never fire and a locked page would "
                 "narrate progress forever")

        # (i) The attach completion re-renders the tier row from the server,
        # and does so BEFORE the unlock: unlocking first would let
        # renderTiers() re-enable the selects after the unlock, leaving the
        # page unlocked with the stale pre-swap values still on screen. Both
        # positions are read from ONE search of the body — searching the unlock
        # forward from the re-render would make an `unlock is earlier`
        # comparison unreachable (review suggestion 9).
        attach_body = _js_function_body(html, "function attachToInFlightSwap(")
        if not attach_body:
            fail("(i) the attachToInFlightSwap body could not be read")
        else:
            refresh_at = attach_body.find("await refreshTiersFromServer();")
            unlock_at = attach_body.find("setSwapControlsDisabled(false);")
            if refresh_at == -1:
                fail("(i) the attach completion does not re-render the tier "
                     "row from the server — a press from the values it shows "
                     "would write back a pre-swap baseline")
            elif unlock_at == -1:
                fail("(i) the attach completion never unlocks the switch "
                     "surface")
            elif unlock_at < refresh_at:
                fail("(i) the attach completion unlocks BEFORE the re-render "
                     "(refresh_at={} unlock_at={}) — renderTiers() would "
                     "re-enable the selects after the unlock".format(
                         refresh_at, unlock_at))
            else:
                pass_("(i) the attach completion re-renders from the server "
                      "BEFORE unlocking")

        # (j) The two operator-guidance strings. The pending line says a
        # refresh is not needed; the poll-failure line has to say that
        # reloading IS the way out — the one place it is the right advice.
        if "no need to refresh" in html:
            pass_("(j) the pending line tells the operator no refresh is "
                  "needed")
        else:
            fail("(j) the pending line is missing the 'no need to refresh' "
                 "guidance")
        if "reload this page when it is back" in html:
            pass_("(j) the poll-failure line tells the operator reloading is "
                  "the way out")
        else:
            fail("(j) the poll-failure line does not tell the operator that "
                 "reloading is safe")

        # (k) Both press paths ARM the lock before they fetch — asserted per
        # handler body, not by a file-wide count (review suggestion 7):
        # setSwapControlsDisabled also appears in the attach watcher and in
        # both `finally` blocks, so deleting the entry lock from one handler
        # leaves a count-based probe green while leaving the whole switch
        # surface editable for the entire press.
        for fn, path in (("saveConfig", "/admin/api/switch"),
                         ("reloadConfig", "/admin/api/reload")):
            handler = _js_function_body(html, "async function {}(".format(fn))
            lock_at = handler.find("setSwapControlsDisabled(true);")
            fetch_at = handler.find(path)
            if not handler or lock_at == -1 or fetch_at == -1 or lock_at > fetch_at:
                fail("(k) {0}() does not lock the switch surface before its "
                     "{1} fetch (body={2}, lock_at={3}, fetch_at={4}) — the "
                     "controls stay editable for the whole "
                     "press".format(fn, path, bool(handler), lock_at, fetch_at))
            else:
                pass_("(k) {}() locks the switch surface before its "
                      "fetch".format(fn))

        # (l) A FAILED re-read must neither unlock nor claim success (review
        # Warning 1). Both the unlock and the success line are confined to the
        # `if (refreshed)` branch, and the failure branch names the way out
        # instead of leaving the page locked with no explanation.
        if not attach_body:
            fail("(l) the attachToInFlightSwap body could not be read")
        else:
            settle = attach_body[
                attach_body.find("await refreshTiersFromServer();"):]
            guard_at = settle.find("if (refreshed)")
            gated = _js_braced_block(settle, guard_at) if guard_at != -1 else ""
            if guard_at == -1 or not gated:
                fail("(l) the attach completion does not gate its outcome on "
                     "the re-read's result (guard_at={}) — a failed re-read "
                     "would unlock the page and paint success over a tier row "
                     "one swap behind".format(guard_at))
            else:
                unlocked = settle.count("setSwapControlsDisabled(false)")
                unlocked_gated = gated.count("setSwapControlsDisabled(false)")
                painted = len(re.findall(
                    r"showStatus\(\s*['\"]success['\"]", settle))
                painted_gated = len(re.findall(
                    r"showStatus\(\s*['\"]success['\"]", gated))
                failure = _js_braced_block(
                    settle[settle.find(gated) + len(gated):], 0)
                problems = []
                if unlocked_gated < 1 or unlocked != unlocked_gated:
                    problems.append(
                        "the unlock is not confined to the successful re-read "
                        "({} past the re-read, {} inside `if (refreshed)`)"
                        .format(unlocked, unlocked_gated))
                if painted_gated < 1 or painted != painted_gated:
                    problems.append(
                        "the success line is not confined to the successful "
                        "re-read ({} past the re-read, {} inside `if "
                        "(refreshed)`)".format(painted, painted_gated))
                if "reload this page" not in failure:
                    problems.append(
                        "the failure branch does not tell the operator to "
                        "reload")
                if problems:
                    fail("(l) failed re-read handling: " + "; ".join(problems))
                else:
                    pass_("(l) a failed re-read stays locked, skips the "
                          "success line, and tells the operator to reload")

        # The reload path's stale-refusal handling, read ONCE for (m)-(o): the
        # branch, its `if (refreshed)` pair, the failure branch, and the
        # `finally`. server.py emits `config_reload_stale` only when a
        # concurrent switch COMPLETED between this reload's gated tier read and
        # its compare-and-install, so the row on screen is one swap behind BY
        # CONSTRUCTION — the one asymmetric survivor of Step 4(c)'s rule.
        #
        # Brace-balanced extraction, never a `(.*?)…} else` delimiter regex:
        # the branch legitimately CONTAINS a nested `} else` (the
        # `if (refreshed)` pair), and a non-greedy capture stops at that inner
        # delimiter — putting the failure path outside the capture and making
        # the probe unable to fire (issue step4-gate-stale-reload-stale-branch).
        # The discriminator is matched QUOTE-AGNOSTICALLY (review F4). Pinning
        # the exact single-quoted literal meant a behaviour-identical re-quote
        # blanked the extraction below, and the probe then failed with a
        # diagnosis that is not true ("the branch could not be read" when the
        # branch is right there). The module's other code-structure pins are
        # already quote-insensitive — (d), (g), (l) and (n) all match a quote
        # class — so this one matches that idiom.
        reload_body = _js_function_body(html, "async function reloadConfig(")
        stale_match = re.search(r"code\s*===\s*['\"]config_reload_stale['\"]",
                                reload_body)
        stale_branch = (_js_braced_block(reload_body, stale_match.start())
                        if stale_match else "")
        stale_guard_at = stale_branch.find("if (refreshed)")
        stale_gated = (_js_braced_block(stale_branch, stale_guard_at)
                       if stale_guard_at != -1 else "")
        stale_failure = (_js_braced_block(
            stale_branch[stale_branch.find(stale_gated) + len(stale_gated):], 0)
            if stale_gated else "")

        # (m) The stale-refusal branch RE-READS the tier row and gates its
        # outcome on the result. Step 4.5(a)'s first shape called
        # `refreshTiersFromServer()` as a bare statement, discarding the boolean
        # Step 4(a) added precisely so no caller could unlock on a failed
        # re-read — so a failed re-read still unlocked AND still claimed "the
        # tier list has been refreshed" over a row that may predate the swap.
        # This is the reload path's twin of (l).
        if not reload_body or not stale_branch:
            fail("(m) the config_reload_stale branch could not be read "
                 "(reloadConfig={}, branch={}) — the reload path's "
                 "stale-refusal handling is unguarded".format(
                     bool(reload_body), bool(stale_branch)))
        else:
            claimed = stale_branch.count("has been refreshed")
            claimed_gated = stale_gated.count("has been refreshed")
            problems = []
            if not re.search(r"const\s+refreshed\s*=\s*await\s+"
                             r"refreshTiersFromServer\(\)\s*;", stale_branch):
                problems.append(
                    "the re-read result is DISCARDED (no `const refreshed = "
                    "await refreshTiersFromServer();`) — the branch cannot "
                    "tell a successful re-read from a failed one")
            if stale_guard_at == -1 or not stale_gated:
                problems.append(
                    "the branch does not gate its outcome on the re-read (no "
                    "`if (refreshed)` pair)")
            elif claimed < 1 or claimed != claimed_gated:
                problems.append(
                    "the 'has been refreshed' claim is not confined to the "
                    "successful re-read ({} in the branch, {} inside `if "
                    "(refreshed)`)".format(claimed, claimed_gated))
            if problems:
                fail("(m) reload-stale re-read: " + "; ".join(problems))
            else:
                pass_("(m) the reload-stale branch captures the re-read result "
                      "and confines 'has been refreshed' to success")

        # (n) A FAILED re-read leaves the page LOCKED and says so: the failure
        # branch sets `reloadStaleUnresolved` (which the `finally` reads, see
        # (o)) and paints the STICKY "reload this page before applying" line —
        # never the success text — so the operator is not told that a row which
        # may still be one swap behind is truthful. Sticky matters here: a
        # terminal 5 s auto-hide would erase the only message explaining why
        # the switch surface is still locked.
        problems = []
        if not stale_failure:
            problems.append(
                "the failure branch could not be read (the `if (refreshed)` "
                "pair is missing or its else-branch is empty)")
        else:
            if not re.search(r"reloadStaleUnresolved\s*=\s*true\s*;",
                             stale_failure):
                problems.append("the failure branch does not set "
                                "reloadStaleUnresolved, so the finally below "
                                "still unlocks")
            if "reload this page before applying" not in stale_failure:
                problems.append("the failure branch does not tell the operator "
                                "to reload this page before applying")
            if "has been refreshed" in stale_failure:
                problems.append(
                    "the failure branch claims the tier list HAS been refreshed "
                    "— the exact defect Step 4.5(c) closed")
            if not re.search(
                    r"showStatus\(\s*['\"]pending['\"][^;]*?\btrue\s*\)",
                    stale_failure, re.S):
                problems.append("the failure line is not sticky — a terminal "
                                "5 s auto-hide would erase the one message "
                                "that says the page is still locked")
        if problems:
            fail("(n) reload-stale failure path: " + "; ".join(problems))
        else:
            pass_("(n) a failed reload-stale re-read sets the unresolved flag "
                  "and paints the sticky reload-this-page line")

        # (o) The `finally` HOLDS the lock when the re-read failed. The unlock
        # must be unreachable on that path — otherwise the operator is handed
        # an unlocked, stale, unlabelled surface whose next Apply writes the
        # pre-switch mapping back, which is the hazard this plan exists to
        # close. Both the guard's condition and the confinement of the unlock
        # are asserted, so neither an unconditional unlock nor a guard that
        # names the flag without consulting it passes.
        finally_at = reload_body.find("} finally {")
        reload_finally = (_js_braced_block(reload_body, finally_at)
                          if finally_at != -1 else "")
        hold = re.search(r"if\s*\(\s*attachPollHandle\s*===\s*null\s*&&\s*"
                         r"!reloadStaleUnresolved\s*\)", reload_finally)
        gated_unlock = (_js_braced_block(reload_finally, hold.start())
                        if hold else "")
        problems = []
        if not reload_finally:
            problems.append("reloadConfig's finally block could not be read")
        else:
            if not hold:
                problems.append(
                    "the finally's unlock is not gated on "
                    "reloadStaleUnresolved — a failed re-read hands back an "
                    "actionable stale surface")
            unlocked = reload_finally.count("setSwapControlsDisabled(false)")
            unlocked_gated = gated_unlock.count("setSwapControlsDisabled(false)")
            if unlocked < 1:
                problems.append(
                    "the finally never unlocks, so the switch surface would "
                    "stay locked after a successful swap")
            elif unlocked != unlocked_gated:
                problems.append(
                    "setSwapControlsDisabled(false) is reachable outside the "
                    "guarded branch ({} in the finally, {} inside the "
                    "guard)".format(unlocked, unlocked_gated))
        if problems:
            fail("(o) reload-stale unlock: " + "; ".join(problems))
        else:
            pass_("(o) the finally unlocks only when the stale re-read "
                  "succeeded")

        # (p) The attach watcher's `settled` bail gates the REPAINT, not just
        # the terminal path: it must sit between the post-await generation
        # re-check and the `if (!st.swapping)` branch. The generation guard
        # cannot cover this — it rejects only a NEWER attach, and no new attach
        # can arm while `attachPollHandle !== null` — so a tick whose response
        # was generated while the swap still ran but is delivered after a
        # sibling tick settled would otherwise repaint the sticky pending line
        # over the terminal line, with the interval already cleared and nothing
        # left to correct it (Step 4.5(b); the retired inner guard, Step
        # 4.5(d), was unreachable for the same reason).
        bail_at = attach_body.find("if (settled)")
        swap_branch_at = attach_body.find("if (!st.swapping)")
        if not attach_body:
            fail("(p) the attachToInFlightSwap body could not be read")
        elif bail_at == -1:
            fail("(p) the attach callback has no `if (settled)` bail — a tick "
                 "delivered after a sibling tick settled would repaint the "
                 "sticky pending line over the terminal line")
        elif swap_branch_at == -1:
            fail("(p) the attach callback has no `if (!st.swapping)` branch to "
                 "bail before")
        elif bail_at > swap_branch_at:
            fail("(p) the `if (settled)` bail sits AFTER the `!st.swapping` "
                 "branch (bail_at={} branch_at={}), so it cannot gate the "
                 "repaint".format(bail_at, swap_branch_at))
        else:
            pass_("(p) the attach watcher's settled bail precedes the "
                  "!st.swapping branch, gating the repaint")

        # The LOAD path's gate, read ONCE for (q)-(r). Step 4.6 landed the same
        # discipline (l) and (m)-(o) apply to the other two call sites;
        # `checkInFlightSwapOnLoad` was its last asymmetric survivor. Why it
        # matters here and not only there: server.py installs `_current_config`
        # AFTER the drain, so in the branch this code exists for the row on
        # screen is the PRE-swap document, and /admin/api/switch carries no
        # staleness guard — so leaving that row unlocked passes the operator's
        # next Apply straight back over the swap that just completed (review
        # F1, `review-final-load-path-re-read-unguarded`).
        load_body = _js_function_body(
            html, "async function checkInFlightSwapOnLoad(")
        reread_marker = "const refreshed = await refreshTiersFromServer();"
        reread_at = load_body.find(reread_marker)
        failure_at = (load_body.find("if (!refreshed)", reread_at + 1)
                      if reread_at != -1 else -1)
        load_failure = (_js_braced_block(load_body, failure_at)
                        if failure_at != -1 else "")
        # The three-condition press guard, as written at both of this
        # function's sites: the pre-fetch check Step 3 added, and the
        # post-await one Step 4.6 adds. Matched quote-agnostically on the
        # field's VALUE, with the identifier pinned by name.
        guard_pat = (r"if\s*\(\s*swapPollHandle\s*!==\s*null\s*\|\|\s*"
                     r"attachPollHandle\s*!==\s*null\s*\|\|\s*swapSettled\s*\)")
        guard_hits = [m.start() for m in re.finditer(guard_pat, load_body)]
        pre_guard = next((a for a in guard_hits
                          if reread_at != -1 and a < reread_at), -1)
        post_guard = next((a for a in guard_hits
                           if reread_at != -1 and a > reread_at), -1)
        post_guard_body = (_js_braced_block(load_body, post_guard)
                           if post_guard != -1 else "")

        # (q) The no-swap branch CAPTURES its re-read result and, on failure,
        # locks the surface, paints the sticky reload line, and RETURNS — so
        # the post-await guard below cannot run and hand the page back
        # unlocked. Every clause is load-bearing: a branch that paints without
        # locking leaves the row pressable; one that locks without returning
        # can be re-unlocked by the guard block it falls through to; and a
        # failure branch that claims "has been refreshed" tells the operator a
        # possibly-pre-swap row is truthful.
        problems = []
        if not load_body:
            problems.append("the checkInFlightSwapOnLoad body could not be read")
        else:
            if reread_at == -1:
                problems.append(
                    "the no-swap branch DISCARDS its re-read result (no `const "
                    "refreshed = await refreshTiersFromServer();`) — a failed "
                    "re-read leaves a possibly-pre-swap row unlocked and "
                    "pressable, and the next Apply writes that baseline back")
            if not load_failure:
                problems.append(
                    "no `if (!refreshed)` failure branch follows the re-read, "
                    "so a failed re-read falls through to the success path")
            else:
                if "setSwapControlsDisabled(true)" not in load_failure:
                    problems.append(
                        "the failure branch does not lock the switch surface")
                if "setSwapControlsDisabled(false)" in load_failure:
                    problems.append(
                        "the failure branch UNLOCKS the switch surface over a "
                        "row that may still predate the swap")
                if not re.search(
                        r"showStatus\(\s*['\"]pending['\"][^;]*?\btrue\s*\)",
                        load_failure, re.S):
                    problems.append(
                        "the failure line is not a sticky pending line — a "
                        "terminal 5 s auto-hide would erase the only message "
                        "explaining why the page is still locked")
                if "reload this page" not in load_failure:
                    problems.append(
                        "the failure branch does not tell the operator to "
                        "reload this page before applying")
                if "has been refreshed" in load_failure:
                    problems.append(
                        "the failure branch claims the tier list HAS been "
                        "refreshed over a row that may still be one swap behind")
                show_at = load_failure.find("showStatus")
                ret_at = load_failure.find("return")
                if ret_at == -1 or (show_at != -1 and ret_at < show_at):
                    problems.append(
                        "the failure branch does not RETURN after painting — "
                        "it falls through to the post-await guard block, which "
                        "is the re-unlock this gate exists to prevent")
        if problems:
            fail("(q) load-path gated re-read: " + "; ".join(problems))
        else:
            pass_("(q) the load path's failed re-read locks the surface, "
                  "paints the sticky reload line, and returns")

        # (r) The load path re-asserts the press guard AFTER its re-read await.
        # `refreshTiersFromServer()` calls `renderTiers()`, which rebuilds the
        # nine selects as fresh ENABLED nodes; a press that started inside that
        # one fetch window has therefore just had its select lock destroyed and
        # its in-progress edit re-rendered away. Without this re-check the load
        # path is the only re-render site that can unlock a press — every other
        # site either re-checks (the press paths, the attach watcher) or does
        # not re-render (the reload-stale branch). The pre-fetch check is
        # asserted present too, so the re-check cannot be satisfied by moving
        # the original guard past the await.
        problems = []
        if not load_body:
            problems.append("the checkInFlightSwapOnLoad body could not be read")
        else:
            if pre_guard == -1:
                problems.append(
                    "the pre-fetch press guard is gone — the load path no "
                    "longer defers to a press already in flight")
            if post_guard == -1:
                problems.append(
                    "no press-guard re-check AFTER the re-read await — "
                    "renderTiers() rebuilt the selects as fresh enabled nodes, "
                    "so a press that started inside that fetch has just had "
                    "its lock dropped and its edit re-rendered away")
            elif "setSwapControlsDisabled(true)" not in post_guard_body:
                problems.append(
                    "the post-await guard block does not re-lock the surface")
            elif "setSwapControlsDisabled(false)" in post_guard_body:
                problems.append(
                    "the post-await guard block UNLOCKS instead of re-locking")
        if problems:
            fail("(r) load-path post-await press-guard re-check: "
                 + "; ".join(problems))
        else:
            pass_("(r) the load path re-asserts the lock after its re-read "
                  "await while a press or an attach is in play")
    finally:
        cleanup()


def test_request_blocked_at_admission_not_evicted():
    """A request blocked in _swap_done.wait() while a swap runs must NOT be
    evicted by the swap it waited on: after the release it is admitted with the
    POST-swap epoch and completes against the new provider, never
    config_swap_restart."""
    print("\n--- Test: Admission-Blocked Request Is Not Evicted ---")
    held = threading.Event()

    def streamer(handler, info):
        handler.send_response(200)
        handler.send_header("Content-Type", "text/event-stream")
        handler.end_headers()
        handler.wfile.write(_anthropic_sse(_msg_start(), _text_delta("straggler")))
        handler.wfile.flush()
        held.set()
        time.sleep(30)  # hold the drain open on the quiet path

    proxy_port, proc, mock_servers, temp_dir, trace_file, cleanup = _swap_proxy(
        streamers={"p1": streamer})
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        out = {}
        straggler = _stream_request_in_thread(proxy_port, out)
        if not held.wait(5):
            fail("upstream never streamed")
            return
        switch_out = {}
        sw = threading.Thread(
            target=lambda: switch_out.update(
                zip(("status", "data"), _admin_post(
                    proxy_port, "/admin/api/switch", _switch_body("p2")))),
            daemon=True)
        sw.start()
        if _wait_admin_swapping(proxy_port) is None:
            fail("swap never became visible")
            return
        # Issued while the swap is in progress: this one blocks at admission.
        blocked = {}
        blk = _stream_request_in_thread(proxy_port, blocked, body={
            "model": "sonnet", "messages": [{"role": "user", "content": "hi"}]})
        sw.join(20)
        if switch_out.get("status") != 200:
            fail("switch returned {}: {}".format(
                switch_out.get("status"), switch_out.get("data")))
            return
        blk.join(20)
        bstatus, _btype, braw = blocked.get("result", (0, "", b""))
        if bstatus != 200:
            fail("admission-blocked request must complete 200 after release, got {}: {!r}".format(
                bstatus, braw[:300]))
            return
        if b"config_swap_restart" in braw:
            fail("the request blocked at admission was evicted by the swap it waited on")
            return
        if len(mock_servers["p2"]["requests"]) == 1 and not mock_servers["p1"]["requests"][1:]:
            pass_("admission-blocked request admitted post-swap on the new provider (p2), "
                  "never evicted")
        else:
            fail("routing wrong: p1 calls {}, p2 calls {}".format(
                len(mock_servers["p1"]["requests"]), len(mock_servers["p2"]["requests"])))
        # The straggler is still parked; cleanup kills the proxy.
        straggler.join(0.1)
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
    ("admin-reload-non-dict-extra-tier", test_admin_reload_non_dict_extra_tier),
    ("admin-models-provider-keyed", test_admin_models_provider_keyed),
    ("admin-providers-detail", test_admin_providers_detail),
    ("admin-providers-detail-no-mode", test_admin_providers_detail_no_mode),
    ("admin-providers-detail-forbidden", test_admin_providers_detail_forbidden),
    ("admin-providers-detail-invalid-mode-normalized", test_admin_providers_detail_invalid_mode_normalized),
    ("admin-switch-preserves-disable-retry-flag", test_admin_switch_preserves_disable_retry_flag),
    ("admin-providers-detail-returns-key-names", test_admin_providers_detail_returns_key_names),
    ("admin-switch-with-key-name", test_admin_switch_with_key_name),
    ("admin-switch-unknown-key-rejected", test_admin_switch_unknown_key_rejected),
    ("admin-switch-invalid-key-type-rejected", test_admin_switch_invalid_key_type_rejected),
    ("admin-switch-missing-key-defaults", test_admin_switch_missing_key_defaults),
    ("admin-switch-validates-key-names", test_admin_switch_validates_key_names),
    ("admin-html-key-column", test_admin_html_key_column),
    # Config-swap drain (plan 2026-10-12-swap-silence-drain)
    ("admin-switch-waits-long-live-stream", test_switch_succeeds_during_long_live_stream),
    ("admin-switch-evicts-silent-stream", test_switch_evicts_silent_stream),
    ("admin-switch-silent-before-press-late-exit", test_switch_silent_before_press_is_late_exit),
    ("admin-switch-abandons-retry-chain", test_switch_abandons_retry_chain),
    ("admin-switch-pre-first-byte-straggler", test_switch_straggler_pre_first_byte_fails_retryably),
    ("admin-swap-status-endpoint", test_swap_status_endpoint),
    ("admin-second-press-refused-409", test_second_press_refused_409),
    ("admin-concurrent-presses-single-flight", test_concurrent_presses_single_flight),
    ("admin-reload-stale-candidate-guard", test_reload_does_not_revert_concurrent_switch),
    ("admin-html-poll-guard-after-await", test_admin_html_poll_guard_after_await),
    ("admin-html-pending-status-styled", test_admin_html_pending_status_styled),
    ("admin-admission-blocked-not-evicted", test_request_blocked_at_admission_not_evicted),
]


if __name__ == "__main__":
    run_cli(ALL_TESTS, "claude-retry-proxy tests: test_admin")
