"""Admin switch/reload validation: the press payloads, key selection, and reload's candidate gates.

Part of the claude-retry-proxy suite; runnable standalone.
"""
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
    _start_admin_proxy,
    _start_mock_upstream,
    _start_proxy_server_directly,
    fail,
    find_free_port,
    pass_,
    run_cli,
)
import json
import os
import shutil
import subprocess
import tempfile
import time


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

    req_list = []
    p_server = _start_mock_upstream(p_port, req_list)
    # The mock owns the port it actually bound (an EADDRINUSE fallback
    # rebinds ephemeral) — the URL must carry that port, so bind first.
    p_port = p_server.server_address[1]
    vendors["p"]["url"] = "http://127.0.0.1:{}".format(p_port)
    keys_path = _create_test_keys_plain(temp_dir, vendors)
    mock_servers = {"p": {
        "server": p_server,
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
        mock_servers["p"]["server"].server_close()
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


def test_admin_switch_preserves_disable_retry_flag():
    """Admin Apply preserves disable_retry_claude_count_token,
    extra_request_headers, and the reasoning_roundtrip policy (one switch
    flow, all top-level models.json keys) in the returned (in-memory) config,
    and a following /admin/api/reload installs a CHANGED reasoning_roundtrip
    value rather than keeping the stale one. After the split the flag and the
    header rules live in models.json, so the on-disk config.json is tiers-only
    and the in-memory preservation is asserted instead (its replacement for
    the former on-disk flag assertion is the loader-precedence case in
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
    seeded_roundtrip = {"p/claude-sonnet-5": "always"}

    temp_dir = tempfile.mkdtemp(prefix="proxy_drct_admin_test_")
    try:
        config_path = _create_test_config_with_flag(
            temp_dir, tiers, True, extra_request_headers=seeded_extra,
            reasoning_roundtrip=seeded_roundtrip)
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

            # The reasoning_roundtrip policy survives the switch. This is the
            # regression test for the carried-key tuple: a switch that hardcodes
            # only its three older siblings silently drops the policy.
            if config.get("reasoning_roundtrip") == seeded_roundtrip:
                pass_("Returned config preserves reasoning_roundtrip")
            else:
                fail(f"Returned config missing/preserved reasoning_roundtrip: "
                     f"{config.get('reasoning_roundtrip')}")

            # /admin/api/reload installs the candidate's CHANGED policy value,
            # not the in-memory one it replaces.
            models_path = os.path.join(temp_dir, "models.json")
            with open(models_path) as f:
                models_doc = json.load(f)
            changed_roundtrip = {"p/claude-opus-5": "always"}
            models_doc["reasoning_roundtrip"] = changed_roundtrip
            with open(models_path, "w") as f:
                json.dump(models_doc, f)
            conn = _hc.HTTPConnection("127.0.0.1", proxy_port, timeout=10)
            conn.request("POST", "/admin/api/reload", body="{}",
                         headers={"Content-Type": "application/json",
                                  "Origin": f"http://localhost:{proxy_port}"})
            resp = conn.getresponse()
            reload_status = resp.status
            resp.read()
            conn.close()
            if reload_status != 200:
                fail(f"Admin reload returned {reload_status}, expected 200")
                return
            conn = _hc.HTTPConnection("127.0.0.1", proxy_port, timeout=10)
            conn.request("GET", "/admin/api/config")
            resp = conn.getresponse()
            config = json.loads(resp.read().decode())
            conn.close()
            if config.get("reasoning_roundtrip") == changed_roundtrip:
                pass_("Reload installed the changed reasoning_roundtrip value")
            else:
                fail(f"Reload did not install the changed reasoning_roundtrip: "
                     f"{config.get('reasoning_roundtrip')}")
            if config.get("extra_request_headers") == seeded_extra:
                pass_("Reload preserved extra_request_headers")
            else:
                fail(f"Reload dropped extra_request_headers: "
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

    req_list = []
    mkp_server = _start_mock_upstream(port, req_list)
    # Same as the reload test above: the URL follows the bound port.
    port = mkp_server.server_address[1]
    vendors["mkp"]["url"] = "http://127.0.0.1:{}".format(port)
    keys_path = _create_test_keys_plain(temp_dir, vendors)
    mock_servers = {"mkp": {"server": mkp_server, "requests": req_list}}
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
        mock_servers["mkp"]["server"].server_close()
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


# ===========================================================================
# Switch input validation: every rejection in one table, plus the positive half
# (plan 2026-10-25-guard-totality-and-blank-admin, Step 7)
# ===========================================================================

def _switch_tier_mapping(tiers):
    """{tier: (provider, model)} — the mapping a refusal must leave untouched."""
    return {name: (cfg.get("provider"), cfg.get("model"))
            for name, cfg in tiers.items()}


def _switch_rejection_rows():
    """(label, bodies, expected_message_fragment) — the switch rejection table.

    One row per validation rule; `bodies` is a tuple where one rule rejects
    several VALUES of the same field (a non-string provider as dict/list/int, a
    non-string model as int/null) — those are one rule, not three. Each fragment
    is a substring of the server's real message, so a row fails if the message
    stops naming what was rejected.
    """
    base = _mode_tiers("p")

    def body(sonnet=None, extra=None):
        tiers = {name: dict(cfg) for name, cfg in base.items()}
        if sonnet is not None:
            tiers["sonnet"] = sonnet
        if extra:
            tiers.update(extra)
        return {"tiers": tiers}

    return [
        ("a tier carrying an unsupported per-tier key",
         (body(sonnet=dict(base["sonnet"], x=[])),),
         "has unsupported key(s): x"),
        ("a two-tier body (a required tier absent)",
         ({"tiers": {"haiku": dict(base["haiku"]),
                     "sonnet": dict(base["sonnet"])}},),
         "missing tiers: opus"),
        ("a fourth tier with an invalid name",
         (body(extra={"bad tier!": dict(base["opus"])}),),
         "invalid tier name: bad tier!"),
        ("a non-string provider (dict, list, int)",
         tuple(body(sonnet=dict(base["sonnet"], provider=value))
               for value in ({}, ["x"], 5)),
         "invalid provider name"),
        ("a non-string model (int, null)",
         tuple(body(sonnet=dict(base["sonnet"], model=value))
               for value in (5, None)),
         "invalid model name"),
        ("a model absent from the provider's catalog",
         (body(sonnet=dict(base["sonnet"], model="model-not-in-catalog")),),
         "unknown model 'model-not-in-catalog'"),
    ]


def _assert_switch_rejected(proxy_port, baseline, label, switch_body, fragment):
    """POST one switch body; assert the refusal, its message, and no change.

    THREE assertions, and the first one is load-bearing rather than decorative:
    the response must ARRIVE. A non-string `provider`/`model` used to raise
    inside the name validator and abort the handler, and `_admin_post` reports a
    transport failure as status 0 — so a "not 200" assertion would pass on a
    hung socket. A status-0 failure here names that pre-change failure mode.
    """
    status, data = _admin_post(proxy_port, "/admin/api/switch", switch_body)
    if status == 0:
        fail("{}: no HTTP response at all ({}) — the handler aborted".format(
            label, data[:200]))
        return
    if status != 400:
        fail("{}: expected 400, got {}: {}".format(label, status, data[:300]))
        return
    if fragment not in data:
        fail("{}: 400 does not name the rejection (expected {!r}): {}".format(
            label, fragment, data[:300]))
        return
    pass_("{}: refused with 400 naming {!r}".format(label, fragment))

    status, body_bytes, _ = _admin_get(proxy_port, "/admin/api/config")
    if status != 200:
        fail("{}: GET /admin/api/config returned {} after the refusal".format(
            label, status))
        return
    persisted = _switch_tier_mapping(json.loads(body_bytes).get("tiers", {}))
    if persisted == baseline:
        pass_("{}: persisted mapping untouched".format(label))
    else:
        fail("{}: persisted mapping CHANGED: {!r} (baseline {!r})".format(
            label, persisted, baseline))


def test_admin_switch_input_rejections():
    """Every way `/admin/api/switch` refuses a body, over one started proxy.

    The endpoint gained three rejection classes in this plan's Step 6 (a tier
    name that is not a safe-charset string, a non-string provider/model, and a
    model the provider's catalog does not list) in addition to the ones it
    already had (an unsupported per-tier key from Step 3, and the required-tier
    check). Each was, before it was checked, a body that made the endpoint
    **answer nothing at all** — except the catalog rule, which was a
    disagreement with Reload rather than an abort. One proxy and one table keeps
    that whole surface in one place instead of four near-identical test bodies.

    Driving one proxy is also what makes the last assertion per row meaningful:
    the baseline is the mapping the page loaded, so a row that silently landed
    would be caught by the NEXT row's comparison as well as its own.
    """
    print("\n--- Test: Admin Switch Input Rejections ---")
    upstream = find_free_port()
    tiers = _mode_tiers("p")
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream), "key": "K"}}
    proxy_port, proc, mock_servers, temp_dir, cleanup = _start_admin_proxy(
        tiers, vendors)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        status, body_bytes, _ = _admin_get(proxy_port, "/admin/api/config")
        if status != 200:
            fail("GET /admin/api/config expected 200, got {}".format(status))
            return
        baseline = _switch_tier_mapping(
            json.loads(body_bytes).get("tiers", {}))
        if baseline == _switch_tier_mapping(tiers):
            pass_("baseline mapping loaded ({} tiers)".format(len(baseline)))
        else:
            fail("baseline tiers differ from the fixture: {!r}".format(baseline))
            return

        rows = _switch_rejection_rows()
        cases = sum(len(bodies) for _label, bodies, _fragment in rows)
        print("  ({} rejection rule(s) over {} request body/bodies)".format(
            len(rows), cases))
        for label, bodies, fragment in rows:
            for switch_body in bodies:
                _assert_switch_rejected(proxy_port, baseline, label,
                                        switch_body, fragment)
    finally:
        cleanup()


def test_admin_switch_extra_tier_persisted():
    """A well-formed EXTRA tier is APPLIED and persisted — validation, not
    prohibition.

    Extra tier names are a documented, supported shape: `doc/configuration.html`
    says so, `validate_config` iterates every tier "because resolve_tier's
    reverse lookup can route to extra tiers", and the reload gate judges every
    tier of its candidate. Step 6's first version forbade them, which the
    Phase 5 audit caught as removing a capability rather than validating input;
    this is the positive half of the rule that replaced it, and it has its own
    slug because a regression pin that asserts a SUCCESS does not belong inside
    a rejection table.

    The counterpart is `test_admin_switch_input_rejections`' fourth-tier row: an
    ill-formed NAME is refused, while a well-formed extra tier passes through.
    """
    print("\n--- Test: Admin Switch Extra Tier Persisted ---")
    upstream = find_free_port()
    tiers = _mode_tiers("p")
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(upstream), "key": "K"}}
    proxy_port, proc, mock_servers, temp_dir, cleanup = _start_admin_proxy(
        tiers, vendors)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        ghost = {"provider": "p", "model": "claude-opus-5"}
        switch_tiers = {name: dict(cfg) for name, cfg in tiers.items()}
        switch_tiers["ghost-tier"] = dict(ghost)
        status, data = _admin_post(proxy_port, "/admin/api/switch",
                                   {"tiers": switch_tiers})
        if status != 200:
            fail("switch carrying a well-formed extra tier expected 200, got "
                 "{}: {}".format(status, data[:300]))
            return
        pass_("switch carrying a well-formed extra tier returned 200")

        # The in-memory view the page reads.
        status, body_bytes, _ = _admin_get(proxy_port, "/admin/api/config")
        if status != 200:
            fail("GET /admin/api/config expected 200, got {}".format(status))
            return
        served = json.loads(body_bytes).get("tiers", {}).get("ghost-tier")
        if isinstance(served, dict) and (
                served.get("provider") == ghost["provider"]
                and served.get("model") == ghost["model"]):
            pass_("/admin/api/config serves the extra tier")
        else:
            fail("extra tier missing from /admin/api/config: {!r}".format(served))

        # The on-disk document a restart would read.
        config_path = os.path.join(temp_dir, "config.json")
        with open(config_path) as fh:
            disk = json.load(fh)
        disk_ghost = disk.get("tiers", {}).get("ghost-tier")
        if isinstance(disk_ghost, dict) and (
                disk_ghost.get("provider") == ghost["provider"]
                and disk_ghost.get("model") == ghost["model"]):
            pass_("extra tier reached the persisted config.json")
        else:
            fail("extra tier missing from the persisted config.json: {!r}".format(
                disk_ghost))
        missing = [t for t in ("haiku", "sonnet", "opus")
                   if t not in disk.get("tiers", {})]
        if missing:
            fail("the switch dropped required tier(s): {}".format(missing))
        else:
            pass_("the three required tiers are still persisted")
    finally:
        cleanup()


ALL_TESTS = [
    ("admin-api-switch", test_admin_api_switch),
    ("admin-api-switch-invalid-provider",
     test_admin_api_switch_invalid_provider),
    ("admin-api-switch-preserves-models",
     test_admin_api_switch_preserves_models),
    ("admin-api-switch-missing-tier-rejected",
     test_admin_api_switch_missing_tier_rejected),
    ("admin-switch-input-rejections", test_admin_switch_input_rejections),
    ("admin-switch-extra-tier-persisted",
     test_admin_switch_extra_tier_persisted),
    ("admin-api-reload", test_admin_api_reload),
    ("admin-reload-non-dict-extra-tier",
     test_admin_reload_non_dict_extra_tier),
    ("admin-switch-preserves-disable-retry-flag",
     test_admin_switch_preserves_disable_retry_flag),
    ("admin-switch-with-key-name", test_admin_switch_with_key_name),
    ("admin-switch-unknown-key-rejected",
     test_admin_switch_unknown_key_rejected),
    ("admin-switch-invalid-key-type-rejected",
     test_admin_switch_invalid_key_type_rejected),
    ("admin-switch-missing-key-defaults",
     test_admin_switch_missing_key_defaults),
    ("admin-switch-validates-key-names",
     test_admin_switch_validates_key_names),
]


if __name__ == "__main__":
    run_cli(ALL_TESTS, "claude-retry-proxy tests: test_admin_switch")
