# Plan: Multi-key provider selection (admin page key column + startup/reload resolution)
**Project:** D:\proj\claude-retry-proxy
**Plan ID:** 2026-09-10-multi-key-provider-selection
**Created:** 2026-09-10

<!-- ## Immediate Actions: absent from initial plans. Populated by /update-plan for revised plans, replaced (not accumulated) on each revision. Contains per-role action-only directives (no rationale) telling agents what to do next. Agents read the full plan for context. -->

## Issue Log

Rows ordered newest-first (latest issues at top). New issues are prepended; resolved issues stay in place with updated status.

| Issue | Status | Found | Resolved | Resolved By |
|-------|--------|-------|----------|-------------|
| [review-mkp-trace-key-whitelist-excludes-extra-tiers](./tmp/reports/2026-09-10-multi-key-provider-selection-review-2026-09-10.json) | Resolved | 2026-09-10 | 2026-09-10 | [tester](./tmp/reports/2026-09-10-multi-key-provider-selection-tester-2026-09-10-2.json) |
| [review-mkp-cli-server-rule-drift](./tmp/reports/2026-09-10-multi-key-provider-selection-review-2026-09-10.json) | Resolved | 2026-09-10 | 2026-09-10 | [tester](./tmp/reports/2026-09-10-multi-key-provider-selection-tester-2026-09-10-2.json) |

## Guidance for Coder

**Files to modify:**
- src/claude_retry_proxy/server.py
- src/claude_retry_proxy/cli.py
- src/claude_retry_proxy/admin.html
- src/templates/config.json
- src/templates/keys-index.json

Do not:
- Do not touch any file under tests/ (test work is exclusively the tester's lane).
- Do not touch CLAUDE.md, README.md, or any .md/.html documentation (planner's lane).
- Do not change `forward_request`'s or `_forward_request_impl`'s return-tuple shape (signature discipline — see Step 3).
- Do not change the `_validate_admin_name` charset regex.
- Do not add memoization/caching to the new key helpers — they must be pure (stateless, no mutation of inputs); concurrency safety rests on that.
- Do not introduce an `api_key` field name anywhere — the decrypted-JSON field is `key` (some doc prose says `api_key`; the planner fixes the prose, the code keeps `key`).

**Step-by-step with verification:** each step above has coder checks tagged `(auto)` or `(scripted)`. The coder self-verifies `(auto)` checks and runs the provided script for `(scripted)` checks. Tester owns the behavioral checks. See coder Prime Directive 4.

## Guidance for Tester

**Tests to create:**
- **Permanent:** tests/test_config_keys.py
  - `test_multikey_keys_load_and_route` — plain keys file with an object-form vendor (`"keys": {"SW":"p1","CZ":"p2"}`) starts successfully; request through a tier whose config names `"CZ"` reaches the upstream with `p2` as auth; tier naming `"SW"` reaches with `p1`; `"SW"` is the first key for defaulting (insertion order).
  - `test_tier_key_absent_defaults_first` — tier has no `key` field (legacy config) → first payload (first insertion-order entry) used.
  - `test_tier_key_empty_string_defaults_first` — tier `"key": ""` → first payload used.
  - `test_validate_config_key_name_checks` — reusing the `_expect_extra_errors`-style helper: unknown name → error containing tier + provider + available names; non-string `key` (e.g. `123`, `false`, `[]`) → "must be a string" error; absent/`""`/None → no error; a non-dict tier (e.g. a list) must produce the existing "must be an object" error and NOT raise; an extra (non-required) tier present in config with an unknown key name → error. Also assert `validate_config(cfg, {"p"})` (two-arg, legacy call) still works and skips key checks; the same for the existing `test_retry_streaming.py` two-arg call sites.
  - `test_keys_file_invalid_multikey_shapes_rejected` — each malformed variant fails server startup (spawn via `_start_proxy_server_directly`, expect failure, mirroring `test_key_decryption_missing_file` style): vendor with BOTH `key` and `keys`; vendor with NEITHER; `keys` not a dict (e.g. a string or `123`); `keys` an empty object; empty name; name failing the admin charset regex; non-string payload; empty payload; payload containing CR/LF or other C0 control characters; non-string `key` value (e.g. `123`).
  - `test_string_form_empty_key_warns_not_rejects` — a vendor with `"key": ""` (string form) still loads: server starts (other vendors valid) with the empty-key warning on stderr; a request through that vendor returns the new `invalid_provider_key` 500 JSON (see Step 3) rather than sending an empty auth header upstream.
- **Permanent:** tests/test_admin.py
  - `test_admin_providers_detail_returns_key_names` — object-form vendor → `providers.<name>.keys == ["SW", "CZ"]` in insertion order; string-form vendor → `keys == ["default"]`; neither payload strings nor any `url` value ever appear in the response body (extend the existing leak-assertion pattern at `test_admin_providers_detail`).
  - `test_admin_switch_with_key_name` — POST `/admin/api/switch` with `key: "CZ"` → 200; GET `/admin/api/config` shows the tier's `key` persisted; a subsequent proxy request uses the CZ payload.
  - `test_admin_switch_unknown_key_rejected` — POST with `key: "NOPE"` → 400 with tier/provider in the error; config on disk unchanged.
  - `test_admin_switch_invalid_key_type_rejected` — POST with `key: false` (or `0`, `[]`) → 400 "invalid key name"; config on disk unchanged. (Unified unset rule — non-string setters are errors at every gate.)
  - `test_admin_switch_missing_key_defaults` — POST tiers without `key` (existing test style) → 200 and the persisted tier gains `"key": "<first name>"` (canonical config on disk).
  - `test_admin_reload_validates_key_names` — write a config with an unknown tier key to disk, POST `/admin/api/reload` → 400; fix the name, reload → 200.
  - `test_admin_html_key_column` — extend the existing admin.html assertion style (`test_admin_models_provider_keyed`): `<select id="${tier}-key"` present after the model select; `select:disabled` CSS rule present; the `keys` list from the providers-detail fetch is consumed; `populateKeys` is INVOKED in two places — inside `renderTiers` (initial load, next to `populateModels`) and on the provider select's onchange — so the key select cannot render empty on page load; a static column header row exists before `#tiers-container` with the exact titles "Provider", "Model", "Key" (spans, not re-rendered by `renderTiers`).
- **Permanent:** tests/test_cli.py
  - `test_start_unknown_tier_key_fails_via_server_gate` — `claude-retry-proxy start` with a config whose tier names an unknown key exits non-zero post-spawn (server startup validation is the single authoritative rule); the surfaced error names the key. Also cover a non-string selector (`"key": false`) the same way. Mirrors the existing `test_key_decryption_missing_file` pattern.
  - `test_start_status_reload_tier_lines_show_key` — after a config with a set tier `key`, the tier display lines of `start`, `status`, AND `reload` all carry the `[key=NAME]` suffix (assert CLI stdout of each subcommand; the three sites must stay in lockstep).
- **Permanent:** tests/test_trace.py — trace test lives HERE (not test_config_keys.py): it targets the same do_POST completion-entry site as the existing `test_extra_request_headers_in_trace`, so extend/reuse that fixture:
  - `test_trace_includes_key_name_not_payload` — trace request event for a multi-key tier carries `"key": "<resolved name>"`; the JSONL line does not contain any payload string; an unknown-model 400 request still delivers the 400 response to the client AND its trace entry has no `key` field (do_POST re-resolution must not crash pre-send); an EXTRA (non-standard) tier present in config and routed via reverse model lookup ALSO carries its `key` in the trace entry (generic resolution).
- **Harness:** extend tests/_harness.py (`_create_test_keys_plain` accepts an object-form `"keys": {name: payload}` vendor, or add a `_create_test_keys_multi` helper) so multi-key vendors are testable with existing helpers. Any changes to existing shared helpers must keep the 259-test baseline green.

**Tests to investigate for retirement:**
- Planner candidates: none identified with confidence. **No test obsolescence identified** — no existing test asserts that `vendor["key"]` is a scalar string; the auth-injection tests use string keys (still valid single-key form).
- Tester must re-run and confirm (expected green, no edits): `test_admin_providers_detail` (string vendors produce name `"default"`, payloads still absent), all `test_admin_api_switch*` variants (bodies without `key` now default server-side), `test_admin_switch_preserves_disable_retry_flag` (tier dicts on disk now include `"key"` — check it compares the fields it cares about, not exact dict equality), `test_config_keys.py` `validate_config` call sites (signature is additive), `test_retry_streaming.py` validate_config calls at ~line 2420/2428 (unchanged two-arg form), and any test asserting the exact content of `src/templates/config.json` (tier entries gain `"key": ""`).

**Retirement procedure:** For each candidate, verify the test exercises code being removed/changed. If obsolete: delete and note in session report. If still valid: document why in session report (e.g., "tests error handling path still present").

## Summary

**Problem:** keys-index.json vendors can now hold multiple API keys per provider. Nothing in the proxy can distinguish them: `vendor["key"]` is read as a single string, the admin page has no key control, and per-tier key choice cannot survive a restart.

**Design (all four decisions confirmed by the user on 2026-09-10):**

- **Keys schema (keys-index.json, decrypted JSON):** a vendor carries exactly one of two fields — `key`: a plain string (legacy, one key, its name is `"default"`) or `keys`: an object mapping name → payload (multi-key; names = object keys like `"SW"`/`"CZ"` of the user's `opencode-go` entry, payload = plaintext API key string). Key order = the object's insertion order, so "first key" is deterministic. Payloads are plaintext after whole-file vimcrypt decryption — no per-key decryption is added.
- **Selection persistence:** each tier in config.json may carry `"key": "<name>"`; absent/`""`/null means the provider's first key. Admin Apply writes the tier keys via the existing `write_config` path, so the choice survives restarts. Two tiers may map to the same provider with different keys.
- **Strict validation** (server-authoritative): a tier key name that doesn't exist in its provider's key list, or a non-string set value (false/0/[]), is an error at every gate — server `validate_config` (startup + admin reload) and admin switch. <!-- UPDATED: review-mkp-cli-server-rule-drift — the CLI deliberately performs NO key-name validation of its own (one rule, one copy); a bad config fails at server startup and the CLI surfaces the same error via its "Proxy exited during startup" + stderr-tail path, the same mechanism used for models-catalog and keys-shape errors. --> Runtime resolution falls back to the first key as defense-in-depth behind the load/validation gates.
- **Reload scope:** reload re-reads config.json only and compares key names against the in-memory vendors snapshot (keys are loaded once at startup; the passphrase is never retained).
- **Trace:** the resolved key *name* (never the payload) is added to the per-request trace entry and the `mode_dispatch` event. <!-- UPDATED: review-mkp-trace-key-whitelist-excludes-extra-tiers — trace-time resolution is generic: ANY tier present in config (standard or extra) gets its `key` traced when the provider-ownership guard holds; the field is omitted when resolution is impossible (guard failure, unowned tier, early non-routed paths). -->

```
                          config.json                    keys-index.json
            tier ---- "key":"CZ" ----+---- providers: [url, mode,
                                     |                keys: {"SW": p1, "CZ": p2}]  (or legacy "key": p0)
admin page: [provider][model][key▾]  |                     |
  single-key vendor -> options["default"], disabled+grey |  |
  save writes tier.key          startup/reload: strict    |  |
                                compare name vs keys      V  V
                     _forward_request_impl ---- resolve_api_key(vendor, tier) -> (payload, name)
                                                auth injection unchanged; trace gains name
```

**Resolution algorithm (per request):** `resolve_api_key(vendor, tier_config)` normalizes the vendor's key field to `[(name, payload)]` (`vendor_key_entries`), matches `tier_config["key"]` against names (exact), falls back to the first entry. The wire auth header continues to use the payload exactly as today.

**Unified "unset key" semantics (all three gates — server validate_config at startup, admin switch, admin reload-via-validate_config; the CLI does not re-validate):** absent, null, or `""` = unset → first key. Any other non-string (false, 0, [], 123, obj) = validation error. A string setter must name an existing key of the tier's provider — unknown name = validation error. This rule applies to ALL tier entries present in config, not only the three required tiers (resolve_tier's reverse lookup can route to extra tiers).

**Key naming rules:** names are the object keys of the `keys` map — non-empty strings matching the existing `_ADMIN_NAME_RE` charset (uniqueness is guaranteed by object semantics; a duplicated name in a hand-edited file collapses to its last occurrence at JSON parse time — accepted, not detected). `"default"` is the name of the single key of a string-form vendor. Payloads must be non-empty strings free of CR/LF and C0 control characters (they are emitted verbatim into outbound auth headers).

**Backward compatibility / migration:** the legacy single-key string form remains valid and is normalized to name `"default"` — no schema migration of existing files is ever needed. Configs without a tier `key` field keep first-key behavior. The only new startup strictness is on shape errors of the new `keys` field (a field that cannot exist in pre-change files), on vendors carrying both `key` and `keys`, and on non-string `key` values; a string-form `"key": ""` continues to load, now with a stderr warning (matching the missing-mode warning precedent), and requests through it fail with a clear `invalid_provider_key` 500 instead of an empty auth header. **Rollback:** no data migration state exists — git-reverting the server/cli/templates changes fully restores single-key behavior; config.json and keys-index.json are plain JSON and untouched by any conversion.

**Alternatives considered and rejected:**
- Per-key vim blowfish2 blobs — user confirmed payloads are plaintext strings (matches the pasted config and this repo's post-decryption schema).
- Separate selection file — config.json tier field is the single source of truth and rides the existing switch/reload plumbing.
- Silent fallback to first key on unknown names — repo policy is strict config validation; a typo should not silently route traffic through the wrong key.
- Re-reading keys-index.json on reload — would require retaining the passphrase in server memory for process lifetime.
- Threading the key name through `forward_request`'s return tuple — rejected; the completion trace re-resolves the name in `do_POST` following the established `extra_request_headers` precedent (with an added provider-match guard, see Step 3).

**Out of scope:** per-key encrypted payloads; reload re-reading the keys file; key-usage metering/rotation; weighting the compatibility learner's state by key name (compat state keys on provider/mode/model — key choice is credential rotation, not API behavior); masking/filtering key names in admin responses (names are charset-restricted and localhost-only, same trust level as provider names); validating extra tiers' provider existence (pre-existing gap: validate_config checks only the three required tiers for provider, unchanged by this plan).

## Repo Mode

Public

## Document Overrides

| Document | Rule Overridden | Reason |
|----------|----------------|--------|
| CLAUDE.md (Config validation strictness gotcha) | "Providers in keys-index.json that aren't in config.models ... are silently ignored" | Key SHAPE is now load-validated for ALL vendors including inactive ones: a malformed `keys` object (or a vendor with both `key` and `keys` / neither) on an inactive provider refuses startup. "Silently ignored" now applies to structurally valid vendors only; the string form (`"key": ""` included) is exempt and keeps loading with a warning. |

## Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| Strict load validation rejects the user's hand-edited keys file (malformed `keys` entries, both `key` and `keys` present, neither present, non-string key values) and the proxy refuses to start | Downtime until the file is fixed | Precise per-vendor ValueError naming the defect; docs show the exact accepted shapes; the `keys` field has zero legacy-file exposure (it cannot exist before this change) |
| Key payloads leak into admin responses or traces | Credential exposure on localhost/trace file | Payloads never enter providers-detail or trace (names only); tester locks this with dedicated leak assertions (payloads AND url) |
| Existing configs/curl scripts without the `key` field | Behavior change on upgrade | Absent/empty `key` defaults server-side to the first key, and the switch handler normalizes it into the persisted config |
| String-form `"key": ""` vendors now warn at startup and 500 at request time (previously: started silently, failed upstream with empty auth) | Slightly different failure mode for already-broken entries | Warning text explained in docs; the 500 names the provider, making the misconfiguration diagnosable |
| Trace file grows one field per request | Negligible storage cost | Name only (no payload), consistent with existing tier/provider fields |

## Proposed Changes

Each step includes verification checks tagged with confidence (see Prime Directive 4).
`(auto)` = mechanical, coder self-verifies. `(scripted)` = deterministic multi-step, coder runs provided script.
Every step must have at least one verification check executable by its owner (coder steps: coder checks; tester steps: tester verify; planner steps: Evidence).
Steps MUST use this numbered-list format exactly. The `### Step N:` heading format is deprecated and must not be used.

1. **Step 1: Multi-key keys schema, shared load validation, and runtime helpers (server.py)**
   Add three pure, total (never-raising, no mutation/caching) helpers near `load_keys_file`. Totality covers the vendor argument itself: it is read with `.get` and may be any JSON value (non-dict vendor → degenerate result, never a raise).
   - `vendor_key_entries(vendor)` → `[(name, payload), ...]` — `vendor` a non-dict → `[("default", "")]`. When `vendor["keys"]` is a dict, that field takes precedence: entries `(name, value)` for each item with a non-empty-string name and non-empty-string payload, in insertion order (empty-payload or bad-name items skipped — same condition as the load gate). Otherwise fall back to `vendor["key"]`: absent/None → `[("default", "")]`; a string (empty included) → `[("default", s)]`; any other type or zero surviving entries → `[("default", "")]`.
   - `vendor_key_names(vendor)` → `[name for name, _ in vendor_key_entries(vendor)]` (insertion order preserved).
   - `resolve_api_key(vendor, tier_config)` → `(payload, name)` — entries per above; `selected = tier_config.get("key")` when tier_config is a dict with a non-empty-string value; exact name match wins; otherwise entries[0].
   Add a shared validator `_validate_vendor_keys_shape(vendors)` (raises `ValueError` per vendor, never used outside loading) and call it from BOTH `load_keys_file` and `decrypt_keys` (update in lockstep — one shared rule, no divergence). Rules, per vendor: exactly one of `key` / `keys` may be present — both present → error `"vendor 'X' has both 'key' and 'keys' — use one form"`; neither → error `"vendor 'X' missing 'key' or 'keys'"` (replaces today's missing-`key` message). `key`: a string → accept, and emit an stderr warning mirroring the existing missing-mode warning when it is empty (do NOT reject); non-string → reject. `keys`: must be a non-empty dict; every name non-empty and matching `_ADMIN_NAME_RE`; every payload a non-empty string free of CR/LF and C0 control chars; any violation → reject.
   → coder verify (auto): `vendor_key_entries`, `vendor_key_names`, `resolve_api_key`, `_validate_vendor_keys_shape` defined in server.py (grep each name); both `load_keys_file` and `decrypt_keys` call the shared validator (read both call sites).
   → coder verify (auto): logic trace — for a string key `vendor_key_entries` returns exactly `[("default", <string>)]`; for `{"keys": {"SW": "a", "CZ": "b"}}` it returns `[("SW", "a"), ("CZ", "b")]` in insertion order; for a vendor with both fields the validator raises ValueError mentioning "both"; a string-form `"key": ""` reaches the warning branch, not a raise.
   → coder verify (scripted): run `python ./tmp/verification/2026-09-10-multi-key-provider-selection-step1.py` — helper behavior matrix (string/object/malformed shapes, non-dict vendors, `keys`-precedence, empty-payload skipping, selection match, absent/unknown/non-string selection → first); exit 0 on pass.
   → tester verify: `test_multikey_keys_load_and_route`, `test_keys_file_invalid_multikey_shapes_rejected`, `test_string_form_empty_key_warns_not_rejects`, `test_tier_key_absent_defaults_first`, `test_tier_key_empty_string_defaults_first` (Guidance for Tester).

2. **Step 2: Per-tier key-name validation in `validate_config` + startup/reload comparison (server.py)**
   Extend the signature to `validate_config(config, providers, provider_keys=None)`. When `provider_keys` is provided (map provider → list of names, built with `vendor_key_names`), add a check loop over ALL entries of `config.get("tiers", {})` (not just the three required tiers — resolve_tier's reverse lookup can route to extra tiers), nested INSIDE the existing `isinstance(tier, dict)` guard so non-dict tiers keep producing the existing "must be an object" error and the function keeps its never-raise property. Per tier dict: `selected = tier.get("key")`; absent/None/`""` → skip (first-key semantics); non-string → error `"tier 'X' key must be a string, got <type>"`; provider empty or not in `providers` → skip (existing checks already report provider problems); provider not in `provider_keys` → skip (no key info for it); name not in `provider_keys[provider]` → error `"tier 'X' references unknown key 'Y' for provider 'Z' (available: A, B)"`. When `provider_keys` is None (legacy two-arg callers — the existing tests and `test_retry_streaming.py`), skip key checks entirely.
   Update both server call sites to pass the map: `main()` (currently `validate_config(_current_config, provider_names)`) and the admin reload handler (`errors = validate_config(new_config, provider_names)`), each building `{name: vendor_key_names(v) for name, v in _vendors.items()}`.
   → coder verify (auto): signature grep shows the third parameter defaults to None.
   → coder verify (auto): read both call sites — each passes a provider→names map built from `_vendors` via `vendor_key_names`; no other server-side `validate_config(` call remains two-arg.
   → coder verify (auto): logic trace — the new key-check loop starts with `if not isinstance(tier, dict): continue`-equivalent guard and iterates `tiers.items()`, not the required-tiers tuple.
   → tester verify: `test_validate_config_key_name_checks`, `test_admin_reload_validates_key_names`, `test_start_unknown_tier_key_fails_via_server_gate`.

3. **Step 3: Key resolution at request time + defensive guard + trace key name (server.py)**
   In `_forward_request_impl` where `api_key = vendor["key"]` is assigned: replace with `api_key, key_name = resolve_api_key(vendor, tier_config)`. Immediately after, add a defensive guard: if `api_key` is falsy (degenerate resolution — empty-string string-form key, or anything that slipped past the load gate), return a 500 with `{"error": {"type": "invalid_provider_key", "message": "Provider '<name>' has no usable API key configured"}}` (mirroring the existing `invalid_provider_mode` 500 shape) before any header injection. The per-mode auth injection below (x-api-key / Authorization Bearer) is otherwise unchanged. Add `"key": key_name` to the `mode_dispatch` trace event.
   In `do_POST`'s request-completion trace entry: add `"key"` after `"provider"`, re-resolved at trace time. The re-resolution MUST be wrapped in an explicit try/except (omit the `key` field on any failure) because — unlike the guard-free `extra_request_headers` re-resolution whose resolver is total on its inputs — this one dereferences `_current_config["tiers"][tier]` and `_vendors[provider]`, and four routine request paths return `tier == "unknown"` and `provider is None` (method-not-allowed 400, path-not-allowed 400, payload-too-large 413, unknown-model 400); without the guard, building the trace entry would crash `do_POST` before the error response is sent. <!-- UPDATED: review-mkp-trace-key-whitelist-excludes-extra-tiers — do NOT whitelist the three standard tier names; resolve for ANY tier present in _current_config['tiers'] so extra tiers routed via reverse lookup get their key traced. --> Inside the guard: skip (omit the field) when `provider` is falsy; then read `tier_cfg = _current_config.get("tiers", {}).get(tier)` (`.get`-based, never indexing) and resolve only when `tier_cfg` is a dict AND `tier_cfg.get("provider") == provider` (entry-snapshot provider still owns the tier; a mid-request admin switch otherwise mixes the old provider's vendor with the new tier's key selector, and an unowned tier simply omits the field). `tier == "unknown"` is already excluded by the falsy-provider skip; the three standard tiers are always present in a valid config, so this membership check is strictly more general than a name whitelist. Keep the signature-discipline comment at the site: the key name is never threaded through `forward_request`'s return tuple; the wire auth used the entry snapshot; trace-only divergence is guarded out where possible and explicitly accepted otherwise.
   Do not change `forward_request` / `_forward_request_impl` return-tuple shapes or `forward_request`'s docstring.
   → coder verify (auto): grep shows `api_key, key_name = resolve_api_key(vendor, tier_config)` and no remaining direct `vendor["key"]` indexing in `_forward_request_impl`; the falsy-key 500 return precedes the fwd_headers build.
   → coder verify (auto): do_POST's `forward_request(` unpack still names 9 variables; the trace-entry dict includes a `"key"` key between `provider` and `status`.
   → coder verify (auto): logic trace — the do_POST re-resolution sits inside try/except, skips on falsy provider, reads the tier config via `.get` (no bare indexing), and checks `tier_cfg.get("provider") == provider` before resolving; NO fixed tier-name whitelist remains in the re-resolution.
   → tester verify: `test_multikey_keys_load_and_route` (wire auth), `test_trace_includes_key_name_not_payload` (including the unknown-model 400 case: response delivered AND trace entry without `key`, and the extra-tier reverse-lookup case: trace entry WITH `key`), `test_string_form_empty_key_warns_not_rejects` (the 500).

4. **Step 4: Admin API — providers-detail key names + switch key handling (server.py)**
   In the `providers-detail` handler: `providers_detail[name] = {"mode": mode, "keys": vendor_key_names(vendor)}` — names only, never payloads or url; the total helper guarantees absent/malformed key fields cannot raise here.
   In the `/admin/api/switch` handler — which validates inline by design and never calls `validate_config` (that is the reload path's job; preserve the split) — add to the first per-tier validation loop (provider/model name checks): when `tier_config.get("key")` is not None/`""` and (not a str or not `_validate_admin_name(key)`), respond 400 `"invalid key name: ..."` (this makes false/0/[] rejected here exactly like the other gates). In the provider-existence loop (after `_vendors[provider]` is known): `names = vendor_key_names(_vendors[provider])`; if the tier's key is missing/`""`/None set `tier_config["key"] = names[0]` (mutate the incoming dict so the persisted config.json is canonical); elif the name is not in `names`, respond 400 `"tier 'X': unknown key 'Y' for provider 'Z' (available: ...)"`. Both 400s must fire before the drain-and-swap Phase 1 (`_config_swapping = True`).
   The reload handler needs no further change (Step 2 supplies the validation via `validate_config`).
   → coder verify (auto): providers-detail handler grep shows `"keys": vendor_key_names(` and no `vendor["key"]` in the response path.
   → coder verify (auto): logic trace — defaulted `tier_config["key"] = names[0]` happens in the provider-existence loop before `write_config`; the unknown-key 400 branch and the invalid-type 400 branch both precede `_config_swapping = True`.
   → tester verify: `test_admin_providers_detail_returns_key_names`, `test_admin_switch_with_key_name`, `test_admin_switch_unknown_key_rejected`, `test_admin_switch_invalid_key_type_rejected`, `test_admin_switch_missing_key_defaults`.

5. **Step 5: CLI — tier display with key suffix (cli.py)**
   <!-- UPDATED: review-mkp-cli-server-rule-drift — the CLI no longer validates key names at all; the server's authoritative startup gate is the single rule. Remove the `_vendor_key_names` helper and the cmd_start key-name validation loop entirely: the CLI reads key NAMES from the keys file nowhere, which also removes the duplicated charset regex and any drift risk by construction. A config whose tier names an unknown key (or has a non-string selector) fails at server startup via `validate_config`; the CLI surfaces that error post-spawn through the existing "Proxy exited during startup" + stderr-tail path — the same mechanism already used for models-catalog and keys-shape errors. -->
   Tier display lines — all THREE sites (cmd_start, cmd_status, cmd_reload): when `tier.get("key")` is truthy, append ` [key=<name>]` to the printed line (e.g. `"  {} -> {} ({}) [key={}]"`); when absent print the existing 3-argument form. All three sites must change together (a shared local formatting snippet is acceptable to keep them in lockstep). The display reads the tier dict from config only.
   → coder verify (auto): `_vendor_key_names` does NOT exist in cli.py (grep returns empty); the three print sites are greppable for `[key=`; no key-name validation loop remains in `cmd_start` (the pre-spawn checks still cover missing tiers and provider existence).
   → tester verify: `test_start_unknown_tier_key_fails_via_server_gate`, `test_start_status_reload_tier_lines_show_key`.

6. **Step 6: Admin page key column (admin.html)**
   CSS: add a disabled-select rule (grey background ~`#3a3a4a`, muted text ~`#9a9a9a`, grey border `#555`, `cursor: not-allowed`).
   Column headers (user-requested): add a header row above the tier rows inside the Tier Configuration card, before `#tiers-container` — an 80px spacer (aligning with the `.tier-label` column) followed by three equal-width (flex:1) `<span>` titles "Provider", "Model", "Key" styled small/uppercase/muted (`color:#9a9a9a`, `text-transform:uppercase`, ~0.8rem, letter-spacing ~0.05em) with a subtle bottom border separating it from the rows. The header is static markup (not re-rendered by `renderTiers`).
   JS: store the providers-detail `keys` array alongside the existing mode data (e.g. `providerKeys[p] = {mode, keys}` — keep `providerModes` working as today).
   `renderTiers()`: add a third `<select id="${tier}-key"></select>` after the model select. IMPORTANT — `renderTiers` must also CALL `populateKeys(tier)` for each tier during initial render, right next to the existing `populateModels(tier)` call; wiring only the onchange would leave the key select empty on page load and break the first Apply (it would POST `key: ""` and get 400).
   New `populateKeys(tier)`: rebuild options from the selected provider's `keys` (option creation via textContent only — same XSS guard as providers/models), set `keySelect.disabled = (options.length <= 1)`, restore the saved `config.tiers[tier].key` when present in the list, else leave the first option selected. The provider select's onchange (currently `populateModels('${tier}')`) must also repopulate the key select.
   `saveConfig()`: include `key: document.getElementById(`${tier}-key`).value` in each `newConfig.tiers[tier]`; provider/model validation unchanged. `reloadConfig()` unchanged (renderTiers re-renders).
   → coder verify (auto): grep admin.html for `<select id="${tier}-key"`, `select:disabled`, `populateKeys`, a `keys` array from the providers-detail fetch, the `disabled =` assignment, and a static header row containing "Provider", "Model", and "Key" titles outside `renderTiers`.
   → coder verify (auto): logic trace — `populateKeys` reads options by provider from the fetched key names, never from `config.models`; `renderTiers` contains a `populateKeys(...)` call (initial wiring) AND the `${tier}-provider` onchange also calls it; `saveConfig` sends `key` but does not block a disabled single-key select (reads `.value` directly).
   → tester verify: `test_admin_html_key_column` (including the two-invocation assertion), `test_admin_switch_with_key_name` (end-to-end through the persisted tier).

7. **Step 7: Templates (src/templates/config.json + src/templates/keys-index.json)**
   `config.json` template: each tier object gains `"key": ""` (empty string = provider's first key; both the CLI validator and `validate_config` treat it as unset, so the template's existing fail-with-instructions startup behavior is unchanged).
   `keys-index.json` template: this is the user-facing "how to use multi-key" reference — it must show BOTH accepted forms side by side: keep the existing single-key `"key": "sk-ant-api03-your-key-here"` examples AND add a multi-key example provider demonstrating the name→payload object, e.g.
   ```json
   "example-multikey-provider": {
     "url": "https://opencode.ai/zen/go",
     "mode": "chat",
     "keys": {
       "SW": "sk-first-example-key",
       "CZ": "sk-second-example-key"
     }
   }
   ```
   Keep the field names exactly `key` / `keys` (never `api_key`). Realistic placeholder payloads only.
   → coder verify (auto): `python -m json.tool` succeeds on both files; grep shows `"key": ""` in all three config tier objects; the keys template contains BOTH a single-key `"key":` string example and a `"keys": {` object example.
   → tester verify: any existing template-copy/startup tests still pass (see Guidance for Tester re-verify list).

## Guidance for Planner

Documentation tasks you will execute yourself (not the coder):

- **Doc files to create/update:** CLAUDE.md, README.md
- **When:** after coder and tester complete (docs describe final behavior).
- **What to sync:**
  - CLAUDE.md — Structure section: note both templates under `src/templates/` (keys-index.json template already exists but is not listed; describe the multi-key `keys` object form). Architecture Step 3 (keys lookup): document the `keys` name→payload object form (vs legacy `key` string), `"default"` name for string-form keys, per-tier `"key"` selection, the strict key-name comparison at startup/reload, and the `invalid_provider_key` 500; while there, correct the stale prose that describes the vendor field as `api_key` — the field is `key` (and the multi-key field is `keys`). Architecture Step 8 (trace): the field enumeration gains `key` (resolved key name). Admin API bullets: providers-detail gains `keys` (names only), switch accepts/defaults/validates the per-tier `key` field. Gotchas: multi-key schema + strict validation (malformed `keys` objects, vendors with both/neither `key`/`keys`, and non-string `key` values refuse startup with per-vendor ValueError; string-form `"key": ""` warns instead and 500s at request time); empty-string `"key"` = first key; selection defaulted to the first key when absent (backward compatible with legacy configs); the trace `key` field carries the key *name* only, on every request, is NOT gated by `--all`, and is omitted when resolution is impossible; payload validation bars CR/LF/control chars. Update the pinned test-suite count in the "Test suite is safe alongside a live proxy" gotcha to the post-implementation total (or reword to avoid a pinned count).
  - README.md — "Keys file format" section (~line 229): the two accepted forms with examples (`key` string vs `keys` name→payload object); exactly-one-of the two fields; name charset rules; `"default"` semantics; payload rules (non-empty, no CR/LF/control chars); payloads are plaintext within the file-level encryption; the string-form-empty-key warning. Configuration section: optional per-tier `"key"` field, first-key default, error behavior for unknown/non-string selectors. Admin page usage: the new Key column, single-key providers show `default` with a disabled grey select. Trace log section: `key` = resolved key name per request.
  - Use placeholder values in any example; never paste real key material.

## History

One row per event (spec revision / mega-audit / review / implementation round). Conclusion = one-sentence outcome or what changed. Dismissed = compact dismissed-findings list for the reviewer — verbatim issue slugs linked as `[<slug>](<report-path>)`, no prose-only entries (the update-and-commit cross-ref and the reviewer both match these cells verbatim). Link to report files; never restate findings inline.

| Date | Event | Conclusion | Dismissed |
|------|-------|------------|-----------|
| 2026-09-10 | Initial plan | Multi-key schema (list-of-pairs), per-tier `"key"` in config.json, strict startup/reload comparison, admin key column with disabled grey single-key select, name-only tracing; all four user decisions recorded in Summary. | — |
| 2026-09-10 | Mega-audit (pre-implementation) | 37 findings (1 High, 14 Medium, 22 Low) processed — the High (guard-less trace re-resolution crashing routine 400s) and all 14 Mediums fixed: unified unset-key semantics across all four gates, key check extended to all config tiers, shared keys-shape validator for both loaders, CLI helper parity + charset, warning (not reject) for empty string-form keys, payload CR/LF rejection, switch inline-validation wording, migration/rollback notes, trace tests relocated beside the existing fixture, decrypt_keys lockstep, doc-drift syncs; 21 of 22 Lows also folded into the same fixes; audit report: [mega-audit](./tmp/reports/2026-09-10-multi-key-provider-selection-mega-audit-2026-09-10.json). | [mkp-rc-script-as-spec](./tmp/reports/2026-09-10-multi-key-provider-selection-mega-audit-2026-09-10.json) |
| 2026-09-10 | Spec revision (user) | Actual keys-index.json format supplied by the user: multi-key vendors use a `"keys": {name: payload}` OBJECT (not the plan's earlier list-of-pairs reading), single-key vendors keep the `key` string; exactly-one-of-`key`/`keys` load rule, `keys`-first helper precedence, insertion order = first key; keys-index.json template updated to demonstrate both forms. | — |
| 2026-09-10 | Review (Phase 6) | Verdict "Approve with warnings" — 0 Critical, 2 Warning, 2 Suggestion; all four hard guarantees verified (payloads never reach admin/traces; step-1 script passes against shipped helpers; unified unset-key semantics across all four gates; guard-safe do_POST trace re-resolution); report: [review](./tmp/reports/2026-09-10-multi-key-provider-selection-review-2026-09-10.json). The two Warnings were subsequently re-opened as Issue Log entries and are being fixed (see next row). | [review-mkp-start-keys-shape-fails-post-spawn](./tmp/reports/2026-09-10-multi-key-provider-selection-review-2026-09-10.json), [review-mkp-admin-stale-key-restore-on-provider-change](./tmp/reports/2026-09-10-multi-key-provider-selection-review-2026-09-10.json) |
| 2026-09-10 | Spec revision (/update-plan) | Two reviewer warnings re-opened per user direction as Fix Planned: CLI key-name validation removed entirely (server-authoritative single rule, duplicated helper/regex deleted) and trace `key` re-resolution made generic over any config tier; Steps 3+5 revised with UPDATED markers, tester guidance updated, Immediate Actions generated, Final Results marked superseded. | — |
| 2026-09-10 | Implementation round 2 (fix round) | Both Fix Planned reviewer Warnings implemented (coder build pass, no issues filed) and verified (tester SUCCESS 275/275): generic trace `key` resolution + CLI validation removal with display sites unified; session reports: [coder](./tmp/reports/2026-09-10-multi-key-provider-selection-coder-2026-09-10-2.json), [tester](./tmp/reports/2026-09-10-multi-key-provider-selection-tester-2026-09-10-2.json). | — |
| 2026-09-10 | Review (Phase 6, round 2) | Verdict "No issues found" on the revision delta — both resolved Warnings confirmed faithful and minimal, reverted tests re-executed with PASS (test_trace 8/8 incl. extra-tier case, test_cli 10/10 incl. post-spawn gate rejection); report: [review 2](./tmp/reports/2026-09-10-multi-key-provider-selection-review-2026-09-10-2.json). | — |

## Plan Metadata

Fenced ```json block — the machine contract read by `parsePlanContext` (JSON-first, regex fallback). **Update it on every revision** — the rule-enforcer lens files a Medium finding when it is missing, invalid, or out of sync with the prose sections. Field semantics: `steps` = one title per `## Proposed Changes` step (numbering + first phrase; extra prose detail on either side is not a mismatch); `tester_files` = Tests to create + Verification scripts to create + Tests to investigate for retirement (mirrors the fallback's three-marker union); `doc_files` = the planner's `**Files to modify:**` list; `verification_scripts` entries shaped `./tmp/verification/<name>.py`; `repo_mode` = `Private` or `Public`; `document_overrides` = the `## Document Overrides` rows as formatted strings.

```json
{
  "plan_id": "2026-09-10-multi-key-provider-selection",
  "steps": [
    "Step 1: Multi-key keys schema, shared load validation, and runtime helpers (server.py)",
    "Step 2: Per-tier key-name validation in validate_config + startup/reload comparison (server.py)",
    "Step 3: Key resolution at request time + defensive guard + trace key name (server.py)",
    "Step 4: Admin API — providers-detail key names + switch key handling (server.py)",
    "Step 5: CLI — tier display with key suffix (cli.py)",
    "Step 6: Admin page key column (admin.html)",
    "Step 7: Templates (src/templates/config.json + src/templates/keys-index.json)"
  ],
  "coder_files": [
    "src/claude_retry_proxy/server.py",
    "src/claude_retry_proxy/cli.py",
    "src/claude_retry_proxy/admin.html",
    "src/templates/config.json",
    "src/templates/keys-index.json"
  ],
  "tester_files": [
    "tests/test_config_keys.py",
    "tests/test_admin.py",
    "tests/test_cli.py",
    "tests/test_trace.py",
    "tests/_harness.py",
    "./tmp/verification/2026-09-10-multi-key-provider-selection-step1.py"
  ],
  "doc_files": [
    "CLAUDE.md",
    "README.md"
  ],
  "verification_scripts": ["./tmp/verification/2026-09-10-multi-key-provider-selection-step1.py"],
  "repo_mode": "Public",
  "document_overrides": [
    "CLAUDE.md: 'inactive providers are silently ignored' (Reason: the keys field shape is now load-validated for all vendors)"
  ]
}
```

## Audit Accumulation

*Counters reset when mega-audit runs. Used by Phase 5 entry trigger.*

| Counter | Value | Last Updated |
|---------|-------|--------------|
| issues_resolved_since_audit | 2 | 2026-09-10 |
| steps_changed_since_audit | 2 | 2026-09-10 |
| files_changed_since_audit | 0 | 2026-09-10 |

## Documentation
- [README.md](README.md) — "Keys file format", "Configuration", admin page, trace log sections.
- [CLAUDE.md](CLAUDE.md) — Structure, Architecture, Gotchas sections.

## Final Results

- **Status:** COMPLETED (2026-09-10 — includes the post-review fix round)
- **Implementation:** all 7 coder steps complete (round 1), plus the two review fixes (round 2): generic trace `key` re-resolution over any config tier, and CLI key-name validation removed in favor of the server-authoritative rule (three CLI display sites unified on one helper). Coder build pass both rounds; zero issues filed. Final diff: 11 files, +1327/−51 — round 1: server.py (+232), cli.py (+72), admin.html (+49), both templates, 4 test files; round 2: server.py + cli.py + tests/test_cli.py + tests/test_trace.py.
- **Tests:** round-1 tester SUCCESS — **275/275** (259 baseline + 16 new permanent tests); round-2 tester SUCCESS — **275/275** re-confirmed with the repurposed `test_start_unknown_tier_key_fails_via_server_gate` (post-spawn server-gate rejection: unknown key AND non-string selector) and the extended `test_trace_includes_key_name_not_payload` (extra-tier reverse-lookup carries `key`). Step-1 verification script passes. No tests skipped or retired; one pre-existing benign harness warning ("No proxy_stop event in trace").
- **Reviews:** round 1 "Approve with warnings" (0 Critical) — the two Warnings were re-opened per user direction and are now **Resolved** (tester, 2026-09-10); round 2 verdict "No issues found" — generic resolver un-crashable with all guards intact (membership over the real config, no whitelist remnants), CLI deletion clean with no orphaned references, reverted tests re-executed with PASS. All four hard guarantees verified end-to-end.
- **Known caveats (non-blocking reviewer Suggestions, dismissed in History):**
  - `review-mkp-start-keys-shape-fails-post-spawn` — keys-file shape defects surface post-spawn via the server stderr tail (diagnosable); pre-spawn CLI reporting would be nicer but is not implemented.
  - `review-mkp-admin-stale-key-restore-on-provider-change` — populateKeys restores a same-named key tag after a provider change instead of resetting to the first key.
  - Reviewer hunches (both reports) remain in the review reports; the `analyze_proxy_trace.py` hunch is closed — the analyzer reads specific fields and ignores unknown ones, so the new trace `key` field has no impact.
- **Cross-reference check:** no prior-plan deferred issue is resolved by this implementation (open deferred issues `break-up-large-source-and-test-files`, `image-content-blocks-chat-mode`, `unguarded-write-state-log-trace-oserror` are unrelated) — no `## Cross-References to Prior Plans` section.
- **Documentation:** CLAUDE.md and README.md synced by the planner (multi-key `keys` schema, per-tier `key` selector, admin Key column, trace `key` field, strict-validation gotchas, suite count 275).