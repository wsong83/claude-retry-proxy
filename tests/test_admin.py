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


def test_admin_html_poll_guard_after_await():
    """Both swap-status poll callbacks re-check `swapSettled` AFTER their awaits
    and before the pending-status repaint (re-review finding
    review-2-stale-poll-overwrites-terminal, fixed in coder round 5).

    A 1 Hz poll response generated while `swapping` was true can resolve after
    the press wrote its terminal status line; without the post-await re-check the
    poll's `showStatus('', 'applying — waiting for …')` overwrites that line, and
    the interval is cleared in the same `finally`, so no later poll corrects it.

    WHAT THIS PINS, AND WHAT IT DOES NOT: the page ships no JS test harness and
    the suite is pure Python, so the runtime behaviour (a late poll does not
    repaint) is not exercised here — that is verified by reading the two
    callbacks. What this test pins is the ORDERING the fix introduced, on the
    page the proxy actually serves: in each poll callback the guard must sit
    between the response parse and the repaint, and the top-of-callback guard
    must still be there beside it. Deleting the post-await check fails this
    test; nothing else in the suite would notice.
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

        blocks = re.findall(r"setInterval\(async \(\) => \{(.*?)\},\s*\d+\);",
                            html, re.S)
        if len(blocks) != 2:
            fail("expected 2 poll callbacks (saveConfig, reloadConfig), found "
                 "{}".format(len(blocks)))
            return

        for i, block in enumerate(blocks):
            label = "poll callback {}".format(i + 1)
            if block.count("if (swapSettled)") < 2:
                fail("{}: expected BOTH the top-of-callback guard and the "
                     "post-await re-check; found {} occurrence(s) of "
                     "'if (swapSettled)'".format(
                         label, block.count("if (swapSettled)")))
                return
            parts = block.split("await resp.json()", 1)
            if len(parts) != 2:
                fail("{}: no 'await resp.json()' response parse".format(label))
                return
            tail = parts[1]
            guard_pos = tail.find("if (swapSettled)")
            repaint_pos = tail.find("showStatus")
            if guard_pos == -1:
                fail("{}: the swapSettled re-check is missing from the "
                     "post-await tail".format(label))
                return
            if repaint_pos != -1 and guard_pos > repaint_pos:
                fail("{}: the swapSettled re-check sits AFTER the repaint — a "
                     "late poll response would overwrite the terminal status "
                     "line".format(label))
                return
            pass_("{}: top-of-callback guard + post-await re-check before the "
                  "repaint".format(label))
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
    ("admin-admission-blocked-not-evicted", test_request_blocked_at_admission_not_evicted),
]


if __name__ == "__main__":
    run_cli(ALL_TESTS, "claude-retry-proxy tests: test_admin")
