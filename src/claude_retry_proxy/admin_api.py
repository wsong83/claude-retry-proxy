"""The admin control plane: the /admin/ page, its API endpoints, and their guard.

``AdminHandlerMixin`` carries the eight admin request handlers -- five GET
endpoints (the page, the config document, the live swap status, the provider
list, and the per-provider mode detail) and three POST endpoints (shutdown,
tier switch, catalog reload). ``ProxyHandler`` inherits it ahead of
``ChatSSEHandlerMixin`` and ``BaseHTTPRequestHandler``; ``do_GET``/``do_POST``
keep the route guards and delegate each admin branch here.

Process state is read attribute-form from ``runtime_state``: the moved branches'
state cannot live in this module (``server.py`` is this module's parent and is
never imported), and a bare global would bind to the defining module and
silently fork the live config on the first switch press.
"""

import json
import os
import sys
import threading
import time
import uuid

from . import forwarder
from . import runtime_state
from .config import (load_models_document, models_path_for, validate_config,
                     write_config)
from .forwarder import _drain_for_swap, _error_body
from .keys import vendor_key_names
from .nesting import (_nesting_limit_message, check_payload_nesting,
                      nesting_event)
from .safety import _validate_admin_name
from .settings import SETTINGS
from .sinks import log_trace


# models.json catalog keys the admin paths carry over: /admin/api/switch takes
# them from the current in-memory config and /admin/api/reload from the
# reloaded document. Neither path writes them, so a key missing here is
# silently dropped from the in-memory document on every admin press — the one
# definition both sites read.
_CARRIED_MODELS_KEYS = ("extra_request_headers",
                        "disable_retry_claude_count_token",
                        "reasoning_field_switch",
                        "reasoning_roundtrip")


# Admin page and validation
_admin_html_cache = None
ADMIN_BODY_LIMIT = 64 * 1024  # 64 KB cap for admin POST bodies


def _load_admin_html():
    """Load admin.html from package data, cached."""
    global _admin_html_cache
    if _admin_html_cache is None:
        admin_path = os.path.join(os.path.dirname(__file__), "admin.html")
        with open(admin_path, "r", encoding="utf-8") as f:
            _admin_html_cache = f.read()
    return _admin_html_cache


def _validate_csrf_origin(handler, port):
    """Validate Origin header for CSRF protection.

    Returns True if valid, False if invalid.
    Rejects: missing Origin, null Origin, non-localhost origins.
    Accepts: http://localhost:<port>, http://127.0.0.1:<port>, http://[::1]:<port>
    """
    origin = handler.headers.get("Origin")
    if not origin:
        return False
    if origin == "null":
        return False
    valid_origins = [
        "http://localhost:{}".format(port),
        "http://127.0.0.1:{}".format(port),
        "http://[::1]:{}".format(port),
    ]
    return origin in valid_origins


class AdminHandlerMixin:
    def _admin_handle_page(self):
        # localhost-only check
        if self.client_address[0] not in ("127.0.0.1", "::1"):
            self.send_response(403)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error":"forbidden"}')
            return

        try:
            html = _load_admin_html()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html.encode("utf-8"))))
            self.end_headers()
            self.wfile.write(html.encode("utf-8"))
        except Exception as e:
            self._send_response(500, json.dumps({"error": str(e)}).encode("utf-8"))
        return

    def _admin_handle_config(self):
        # localhost-only check
        if self.client_address[0] not in ("127.0.0.1", "::1"):
            self.send_response(403)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error":"forbidden"}')
            return

        # Serialize INSIDE the lock and send those bytes. The previous
        # json.loads(json.dumps(...)) round-trip existed to copy the config
        # so the outer dumps could run outside the lock — but it left the
        # ENCODE unguarded one line later, and a config that DECODES fine can
        # still fail to ENCODE (the encoder's ceiling sits below the
        # decoder's). Such a config aborted do_GET with no HTTP response.
        # json.dumps(json.loads(json.dumps(x))) is byte-identical to
        # json.dumps(x), so the round-trip bought nothing.
        try:
            with forwarder._config_lock:
                payload = json.dumps(runtime_state._current_config).encode("utf-8")
        except Exception:
            # Reachable: a hand-edited config.json can hold a document that
            # parses (decode ceiling ~16915) yet exceeds the encoder's
            # (~15505). Step 3 keeps client-supplied values out of this path.
            self._send_response(500, json.dumps({
                "error": "the configuration could not be serialized"
            }).encode("utf-8"))
            return
        self._send_response(200, payload)
        return

    def _admin_handle_swap_status(self):
        # localhost-only check
        if self.client_address[0] not in ("127.0.0.1", "::1"):
            self.send_response(403)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error":"forbidden"}')
            return

        # Each nullable field is guarded on its own source, not on
        # `swapping`: a `time.time() - None` TypeError would 500 the
        # endpoint, and the admin page swallows poll failures — the bug
        # would degrade silently into a dead status line.
        with forwarder._config_lock:
            swapping = forwarder._config_swapping
            now = time.time()
            waited_s = (now - forwarder._swap_started_at) \
                if (swapping and forwarder._swap_started_at is not None) else None
            silence_s = (now - forwarder._last_upstream_activity) \
                if (swapping and forwarder._last_upstream_activity) else None
            inflight = forwarder._inflight_count
        self._send_response(200, json.dumps({
            "swapping": swapping,
            "waited_s": waited_s,
            "inflight": inflight,
            "silence_s": silence_s,
            "budget_s": SETTINGS.swap_silence_timeout,
        }).encode("utf-8"))
        return

    def _admin_handle_providers(self):
        # localhost-only check
        if self.client_address[0] not in ("127.0.0.1", "::1"):
            self.send_response(403)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error":"forbidden"}')
            return

        providers = list(runtime_state._vendors.keys()) if runtime_state._vendors else []
        self._send_response(200, json.dumps({"providers": providers}).encode("utf-8"))
        return

    def _admin_handle_providers_detail(self):
        # localhost-only check
        if self.client_address[0] not in ("127.0.0.1", "::1"):
            self.send_response(403)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error":"forbidden"}')
            return

        providers_detail = {}
        for name, vendor in (runtime_state._vendors or {}).items():
            mode = vendor.get("mode")
            if mode not in SETTINGS.mode_values:
                mode = "anthropic"
            providers_detail[name] = {
                "mode": mode,
                "keys": vendor_key_names(vendor),
            }
        self._send_response(200, json.dumps({
            "providers": providers_detail
        }).encode("utf-8"))
        return

    def _admin_handle_shutdown(self):
        # localhost-only check
        if self.client_address[0] not in ("127.0.0.1", "::1"):
            self.send_response(403)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error":"forbidden"}')
            return

        # CSRF check
        if not _validate_csrf_origin(self, SETTINGS.port):
            self._send_response(403, b'{"error":"forbidden: invalid Origin"}')
            return

        if runtime_state._shutting_down:
            self._send_response(200, b'{"status":"already_shutting_down"}')
            return
        runtime_state._shutting_down = True

        self._send_response(200, b'{"status":"shutting_down"}')

        def _delayed_shutdown():
            time.sleep(0.1)
            try:
                self.server.shutdown()
            except Exception as e:
                print("[proxy] ERROR during shutdown: {}".format(e),
                      file=sys.stderr)
        threading.Thread(target=_delayed_shutdown, daemon=True).start()
        return

    def _admin_handle_switch(self):
        # localhost-only check
        if self.client_address[0] not in ("127.0.0.1", "::1"):
            self.send_response(403)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error":"forbidden"}')
            return

        # CSRF check
        if not _validate_csrf_origin(self, SETTINGS.port):
            self._send_response(403, b'{"error":"forbidden: invalid Origin"}')
            return

        # Read and validate body size
        try:
            content_length = int(self.headers.get("Content-Length", 0))
        except (ValueError, TypeError):
            self._send_response(400, b'{"error":"invalid Content-Length"}')
            return
        if content_length > ADMIN_BODY_LIMIT:
            self._send_response(413, b'{"error":"request body too large"}')
            return

        body = self.rfile.read(content_length) if content_length > 0 else b""
        # The admin surface keeps its documented exclusion from the
        # Anthropic envelope, so this branch owns its own request_id (the
        # shared one is only assigned further down, on the client path).
        request_id = str(uuid.uuid4())
        _nesting = check_payload_nesting(body)
        if _nesting is not None:
            message = _nesting_limit_message(_nesting)
            log_trace(nesting_event("admin_body", _nesting,
                                    request_id=request_id))
            self._send_response(400, json.dumps({
                "error": message,
                "code": "nesting_limit_exceeded",
            }).encode("utf-8"))
            return
        try:
            data = json.loads(body)
        except Exception:
            # Total by design. json.loads can fail on this bytes body as
            # JSONDecodeError (syntax), UnicodeDecodeError (bytes that are
            # not valid utf-8) or RecursionError (nesting deeper than the
            # interpreter will recurse). RecursionError is a RuntimeError
            # and UnicodeDecodeError is a SIBLING of JSONDecodeError rather
            # than a subclass, so naming only JSONDecodeError let both
            # escape and abort do_POST with no HTTP response at all.
            self._send_response(400, b'{"error":"invalid JSON"}')
            return

        # A body that is valid JSON but not an object (null, a list, a
        # string) would otherwise raise AttributeError at
        # data.get(...) and abort do_POST with no HTTP response at all.
        if not isinstance(data, dict):
            self._send_response(400, b'{"error":"invalid JSON body"}')
            return

        # Validate all 3 tiers present
        new_tiers = data.get("tiers", {})
        if not isinstance(new_tiers, dict):
            self._send_response(400, b'{"error":"\'tiers\' must be an object"}')
            return
        required_tiers = {"haiku", "sonnet", "opus"}
        missing = required_tiers - set(new_tiers.keys())
        if missing:
            self._send_response(400, json.dumps({
                "error": "missing tiers: {}".format(", ".join(sorted(missing)))
            }).encode("utf-8"))
            return

        # Tier names are validated, NOT restricted: extra tiers beyond the
        # required three are a documented, supported shape (they are
        # reachable through resolve_tier's reverse lookup, and
        # validate_config iterates every tier for exactly that reason).
        # What must not survive is arbitrary client text landing in
        # config.json, so the name is bound by the same charset rule used
        # for provider/model/key below.
        for tier_name in new_tiers:
            if not isinstance(tier_name, str) or not _validate_admin_name(tier_name):
                self._send_response(400, json.dumps({
                    "error": "invalid tier name: {}".format(tier_name)
                }).encode("utf-8"))
                return

        # Validate provider names and model names
        for tier_name, tier_config in new_tiers.items():
            if not isinstance(tier_config, dict):
                self._send_response(400, json.dumps({
                    "error": "tier '{}' must be an object".format(tier_name)
                }).encode("utf-8"))
                return
            extra = set(tier_config.keys()) - {"provider", "model", "key"}
            if extra:
                self._send_response(400, json.dumps({
                    "error": "tier '{}' has unsupported key(s): {}".format(
                        tier_name, ", ".join(sorted(extra)))
                }).encode("utf-8"))
                return
            provider = tier_config.get("provider", "")
            model = tier_config.get("model", "")
            if not isinstance(provider, str) or not _validate_admin_name(provider):
                self._send_response(400, json.dumps({
                    "error": "invalid provider name: {}".format(provider)
                }).encode("utf-8"))
                return
            if not isinstance(model, str) or not _validate_admin_name(model):
                self._send_response(400, json.dumps({
                    "error": "invalid model name: {}".format(model)
                }).encode("utf-8"))
                return
            key = tier_config.get("key")
            if key is not None and key != "" and (
                    not isinstance(key, str) or not _validate_admin_name(key)):
                self._send_response(400, json.dumps({
                    "error": "invalid key name: {}".format(key)
                }).encode("utf-8"))
                return

        # Validate providers exist
        provider_names = set(runtime_state._vendors.keys())
        # Snapshot the epoch and the catalog together, under the lock: the
        # check below validates against this snapshot, and Phase 3 re-checks
        # it when the epoch has moved by then (see there). Reading the two
        # separately would let a reload land between them.
        with forwarder._config_lock:
            validated_epoch = forwarder._config_epoch
            validated_models = runtime_state._current_config.get("models") or {}
        for tier_name, tier_config in new_tiers.items():
            provider = tier_config.get("provider", "")
            if provider not in provider_names:
                self._send_response(400, json.dumps({
                    "error": "unknown provider: {}".format(provider)
                }).encode("utf-8"))
                return
            # The reload gate already refuses a tier whose model is not in
            # the catalog; without this the switch accepts a configuration
            # that reload then rejects, so Apply and Reload would disagree
            # about the same rule. `model` is a validated string here.
            model = tier_config.get("model", "")
            catalog = validated_models.get(provider)
            if not isinstance(catalog, list) or model not in catalog:
                self._send_response(400, json.dumps({
                    "error": "tier '{}': unknown model '{}' for provider '{}'"
                             .format(tier_name, model, provider)
                }).encode("utf-8"))
                return
            names = vendor_key_names(runtime_state._vendors[provider])
            key = tier_config.get("key")
            if key is None or key == "":
                tier_config["key"] = names[0]
            elif key not in names:
                self._send_response(400, json.dumps({
                    "error": "tier '{}': unknown key '{}' for provider "
                    "'{}' (available: {})".format(
                        tier_name, key, provider, ", ".join(names))
                }).encode("utf-8"))
                return

        # Drain-and-swap: pause admissions and wait for in-flight work.
        # Never fails and never aborts: it always reaches a decision, and
        # the handler returns 200 with the drain detail. Only a disk-write
        # failure below (which follows a completed drain) returns 500, and
        # that path performs no swap and no epoch bump — survivors
        # legitimately continue on the old mapping.
        response_status = None
        response_body = None
        drain = _drain_for_swap()
        if drain is None:
            # Single-flight: a swap is already in progress. The guard and
            # the press share one lock acquisition inside _drain_for_swap,
            # so two concurrent presses cannot both enter a drain — the
            # second is refused here without disturbing the first swap's
            # mapping, epoch, or drain counters.
            self._send_response(409, _error_body(
                "api_error", "config_swap_in_progress",
                "a config swap is already in progress; retry when it completes",
                str(uuid.uuid4())))
            return
        drained, inflight_at_press, waited_s = drain

        # Phase 3: Perform the swap
        try:
            with forwarder._config_lock:
                # The snapshot validated above was taken before this press
                # owned the swap, so a reload that finished in between can
                # have replaced the catalog it was checked against -- and
                # Phase 3 carries the LIVE catalog forward. Re-check against
                # that one when the epoch moved; otherwise the switch
                # persists a tier that Reload then refuses, which is the
                # Apply/Reload disagreement the check above exists to
                # remove. Answering the same 400 keeps the operator's
                # diagnostic identical to a fresh press.
                if (response_status is None
                        and forwarder._config_epoch != validated_epoch):
                    live_models = runtime_state._current_config.get("models") or {}
                    for _name, _cfg in new_tiers.items():
                        _catalog = live_models.get(_cfg.get("provider", ""))
                        if (not isinstance(_catalog, list)
                                or _cfg.get("model", "") not in _catalog):
                            response_status = 400
                            response_body = json.dumps({
                                "error": "tier '{}': unknown model '{}' for "
                                         "provider '{}'".format(
                                             _name, _cfg.get("model", ""),
                                             _cfg.get("provider", ""))
                            }).encode("utf-8")
                            break
                # The provider catalog lives in models.json and this
                # process never writes it: the disk document carries the
                # tier mapping and nothing else.
                disk_config = {"tiers": new_tiers}
                # The in-memory document keeps today's merged shape:
                # catalog, header rules, and flag carried over from the
                # current config.
                new_config = {
                    "tiers": disk_config["tiers"],
                    "models": runtime_state._current_config.get("models", {}),
                }
                for _key in _CARRIED_MODELS_KEYS:
                    if _key in runtime_state._current_config:
                        new_config[_key] = runtime_state._current_config[_key]
                if response_status is None:
                    # Write to disk FIRST, then update in-memory
                    try:
                        write_config(runtime_state._config_path, disk_config)
                        # Only update in-memory after successful disk write
                        runtime_state._current_config = new_config
                        # The epoch bump is the eviction signal for any
                        # straggler still holding an old snapshot.
                        forwarder._config_epoch += 1
                        response_status = 200
                        response_body = json.dumps({
                            "status": "ok",
                            "drained": drained,
                            "waited_s": round(waited_s, 3),
                            "inflight_at_swap": inflight_at_press,
                        }).encode("utf-8")
                    except OSError as e:
                        response_status = 500
                        response_body = json.dumps({
                            "error": "failed to write config: {}".format(e)
                        }).encode("utf-8")
        finally:
            # Phase 4: Clear swap flag and signal completion. The
            # timestamp clears in the SAME acquisition: the status
            # endpoint must never observe swapping True with a None
            # started_at.
            with forwarder._config_lock:
                forwarder._config_swapping = False
                forwarder._swap_started_at = None
                forwarder._swap_done.set()

        # Send response after releasing lock
        self._send_response(response_status, response_body)
        return

    def _admin_handle_reload(self):
        # localhost-only check
        if self.client_address[0] not in ("127.0.0.1", "::1"):
            self.send_response(403)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error":"forbidden"}')
            return

        # CSRF check
        if not _validate_csrf_origin(self, SETTINGS.port):
            self._send_response(403, b'{"error":"forbidden: invalid Origin"}')
            return

        # Reload the provider catalog from models.json. Tiers are not
        # re-read from disk. This happens at handler entry, before the
        # drain, so a missing or malformed catalog fails fast with an
        # immediate 400 rather than after an unbounded drain.
        try:
            models_doc = load_models_document(models_path_for(runtime_state._config_path))
        except ValueError as e:
            self._send_response(400, json.dumps({
                "error": "failed to load models: {}".format(e)
            }).encode("utf-8"))
            return

        # Assemble the candidate and run the membership/validate gate
        # BEFORE the press, so a refused reload abandons no retry chains.
        # Safe now that single-flight keeps a concurrent switch from
        # completing — and being silently reverted in memory — mid-drain,
        # which is what the original after-drain ordering guarded against.
        with forwarder._config_lock:
            # The epoch these tiers are read at, captured in the SAME
            # acquisition. A /admin/api/switch that completes its whole
            # press -> drain -> swap -> release cycle after this gate and
            # before Phase 3 leaves this candidate stale; Phase 3 compares
            # the epoch before installing, so it can never revert the
            # switch's mapping.
            gated_epoch = forwarder._config_epoch
            candidate = {
                "tiers": runtime_state._current_config.get("tiers", {}),
                "models": models_doc.get("models", {}),
            }
            for _key in _CARRIED_MODELS_KEYS:
                if _key in models_doc:
                    candidate[_key] = models_doc[_key]

            # Membership gate: every tier must name a provider whose
            # reloaded catalog lists its model. The gate is total —
            # a tier it cannot judge is refused with its own 400,
            # never skipped, and it must run before validate_config
            # so the specific error is not pre-empted.
            gate_error = None
            models_path = models_path_for(runtime_state._config_path)
            for tier_name, tier in candidate["tiers"].items():
                if not isinstance(tier, dict):
                    gate_error = "tier '{}' is not an object".format(tier_name)
                    break
                provider = tier.get("provider")
                model = tier.get("model")
                if not provider or not model \
                        or not isinstance(provider, str) \
                        or not isinstance(model, str):
                    gate_error = "tier '{}' does not name a provider and a model".format(tier_name)
                    break
                catalog_entry = candidate["models"].get(provider)
                if not isinstance(catalog_entry, list) \
                        or model not in catalog_entry:
                    gate_error = (
                        "reload refused: tier '{}' uses model '{}', which is "
                        "not in the reloaded catalog for provider '{}' "
                        "({})".format(tier_name, model, provider, models_path))
                    break
            if gate_error is None:
                provider_names = set(runtime_state._vendors.keys())
                provider_keys = {name: vendor_key_names(v)
                                 for name, v in runtime_state._vendors.items()}
                errors = validate_config(candidate, provider_names,
                                         provider_keys)
                if errors:
                    gate_error = "config validation failed: {}".format(
                        "; ".join(errors))
        if gate_error is not None:
            # Refusal: no press, no drain, no swap — the previous
            # catalog stays in effect and no retry chain was disturbed.
            self._send_response(400, json.dumps({
                "error": gate_error
            }).encode("utf-8"))
            return

        # Whether the success body can be serialized is decidable BEFORE the
        # press: its only raising component is `candidate`, and the three
        # drain scalars are JSON-safe. Probe it here so a press that can
        # never succeed does not drain — the same ordering rule the gate
        # above follows, for the same reason (a refused reload abandons no
        # retry chains). The post-drain build stays as it is; this is the
        # early refusal, not a replacement for the total guard there.
        try:
            json.dumps(candidate)
        except Exception:
            self._send_response(500, json.dumps({
                "error": "the configuration could not be serialized"
            }).encode("utf-8"))
            return

        # Drain-and-swap: pause admissions and wait for in-flight work
        # (see /admin/api/switch).
        drain = _drain_for_swap()
        if drain is None:
            # Single-flight, shared with /admin/api/switch: the guard and
            # the press share one lock acquisition inside _drain_for_swap,
            # so a reload racing a switch is refused here and leaves the
            # in-progress swap's mapping intact (see there).
            self._send_response(409, _error_body(
                "api_error", "config_swap_in_progress",
                "a config swap is already in progress; retry when it completes",
                str(uuid.uuid4())))
            return
        drained, inflight_at_press, waited_s = drain

        # Phase 3: swap in the gated candidate and bump the epoch.
        try:
            with forwarder._config_lock:
                if forwarder._config_epoch != gated_epoch:
                    # A concurrent /admin/api/switch completed a swap
                    # between the gate above and this install, so
                    # `candidate`'s tiers predate it: installing them would
                    # silently revert that switch's mapping. No swap is in
                    # progress at this point, so this is NOT the
                    # single-flight refusal — it is a stale candidate.
                    response_status = 409
                    response_body = _error_body(
                        "api_error", "config_reload_stale",
                        "the configuration changed while the reload was "
                        "being prepared; retry",
                        str(uuid.uuid4()))
                else:
                    # Serialize BEFORE installing. The success body embeds
                    # `candidate` -- the document loaded from disk -- and a
                    # config can decode yet fail to re-encode (the encoder's
                    # stack ceiling sits below the decoder's, and `indent=`
                    # collapses it again). Built after the install, such a
                    # failure would leave the swap applied and the epoch
                    # bumped while the client received NO HTTP response at
                    # all (this try has no `except`, and `do_POST` has no
                    # outer one). Built first, nothing has been installed
                    # yet, so the 500 is truthful: the previous mapping is
                    # still in force.
                    try:
                        success_body = json.dumps({
                            "status": "ok",
                            "config": candidate,
                            "drained": drained,
                            "waited_s": round(waited_s, 3),
                            "inflight_at_swap": inflight_at_press,
                        }).encode("utf-8")
                    except Exception:
                        response_status = 500
                        response_body = json.dumps({
                            "error": "the configuration could not be serialized"
                        }).encode("utf-8")
                    else:
                        runtime_state._current_config = candidate
                        forwarder._config_epoch += 1
                        response_status = 200
                        response_body = success_body
        finally:
            # Phase 4: Clear swap flag and signal completion (the
            # timestamp clears in the same acquisition — see there).
            with forwarder._config_lock:
                forwarder._config_swapping = False
                forwarder._swap_started_at = None
                forwarder._swap_done.set()

        # Send response after releasing lock
        self._send_response(response_status, response_body)
        return
