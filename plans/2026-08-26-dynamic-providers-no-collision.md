# Plan: Dynamic provider loading + remove same-model collision check
**Project:** D:\proj\claude-retry-proxy
**Plan ID:** 2026-08-26-dynamic-providers-no-collision
**Created:** 2026-08-26

## Issue Log

| Issue | Status | Found | Resolved | Resolved By |
|-------|--------|-------|----------|-------------|
| [review-models-truthiness](./tmp/reports/2026-08-26-dynamic-providers-no-collision-review-2026-08-26.json) | Resolved | 2026-08-26 | 2026-08-26 | [tester](./tmp/reports/2026-08-26-dynamic-providers-no-collision-tester-2026-08-26-3.json) |
| [test-helper-models-default-blocked-by-new-validation](./tmp/reports/2026-08-26-dynamic-providers-no-collision-test-helper-models-default-blocked-by-new-validation.json) | Resolved | 2026-08-26 | 2026-08-26 | [tester](./tmp/reports/2026-08-26-dynamic-providers-no-collision-tester-2026-08-26-2.json) |
| [no-models-provider-model-field-unusable](./tmp/reports/2026-08-26-dynamic-providers-no-collision-no-models-provider-model-field-unusable.json) | Resolved | 2026-08-26 | 2026-08-26 | [tester](./tmp/reports/2026-08-26-dynamic-providers-no-collision-tester-2026-08-26.json) |
| [step4-test-removal-misassigned](./tmp/reports/2026-08-26-dynamic-providers-no-collision-step4-test-removal-misassigned.json) | Resolved | 2026-08-26 | 2026-08-26 | [tester](./tmp/reports/2026-08-26-dynamic-providers-no-collision-tester-2026-08-26.json) |
| [inline-verification-cmds-unpassable](./tmp/reports/2026-08-26-dynamic-providers-no-collision-inline-verification-cmds-unpassable.json) | Resolved | 2026-08-26 | 2026-08-26 | [tester](./tmp/reports/2026-08-26-dynamic-providers-no-collision-tester-2026-08-26.json) |

## Guidance for Coder

**Files to modify:**
- `src/claude_retry_proxy/admin.html`
- `src/claude_retry_proxy/server.py`

**Step-by-step with verification:**

1. **Step 1:** Clean up admin.html dropdowns — remove placeholder options and "Custom..." from both provider and model `<select>` elements. <!-- UPDATED: user decided to keep select dropdowns, remove placeholders and custom option instead of datalist approach -->
   - Remove the "Select provider..." placeholder `<option value="">` from the provider `<select>`.
   - Remove the "Select model..." placeholder `<option value="">` from the model `<select>`.
   - Remove the "Custom..." `<option value="__custom__">` from the model `<select>`.
   - Remove the `<input id="${tier}-custom-model">` hidden custom-model input.
   - Remove the `.model-custom` CSS rules (orphaned by custom-input removal).
   - Remove `onModelSelect()` — the function is no longer needed since there's no custom-model toggle.
   - Remove `getModelValue()` — replace call sites with `document.getElementById(\`${tier}-model\`).value` directly.
   - Remove `onProviderChange()` — with no custom-model state to preserve, `populateModels` can be called directly from the provider `<select>`'s `onchange` attribute.
   - `populateModels()` stays but is simplified: no more `preferredModel` parameter, no more custom option insertion. Just populates `<option>` elements from `config.models[provider]` and sets the selected value to the saved tier model.
   - `saveConfig()` validation: the empty-string guard is no longer needed (no blank options exist), but keep the truthiness check for safety.
   → coder verify (auto): `admin.html` contains no `<option value="">` (grep returns empty).
   → coder verify (auto): `admin.html` contains no `__custom__` (grep returns empty).
   → coder verify (auto): `admin.html` contains no `-custom-model` (grep returns empty).
   → coder verify (auto): `admin.html` contains no `onModelSelect` or `getModelValue` (grep returns empty).
   → coder verify (auto): `admin.html` contains no `.model-custom` (grep returns empty).
   → coder verify (scripted): `pip install -e .` succeeds, verify admin.html structure — script at `./tmp/verification/2026-08-26-dynamic-providers-no-collision-step1.py`
   → tester verify: `test_admin_page_served` passes — GET /admin/ returns valid HTML.
   → tester verify: `test_admin_models_provider_keyed` passes (updated) — no placeholder options, no custom option, dropdowns contain only valid values.

2. **Step 2:** Add startup validation: every provider in `_vendors` must have at least one model in `config.models`. <!-- NEW: replaces the datalist approach — models are strictly from config.json -->
   - In `validate_config()` (server.py ~line 202): add a check that for every provider name in the `providers` set, `config["models"].get(provider, [])` is a non-empty list.
   - Error message: `"provider 'X' has no models in config.models — add at least one model name for this provider"`.
   - This runs at server startup (in `main()` via `validate_config`) and at admin reload (via `/admin/api/reload`).
   - The admin switch endpoint (`/admin/api/switch`) does NOT need this check — it preserves the existing `models` section, and the provider was already validated at startup.
   → coder verify (auto): `validate_config` contains a check that iterates `providers` and verifies `config["models"].get(p, [])` is non-empty (grep confirms the loop and error message).
   → coder verify (scripted): `pip install -e .` succeeds, then `python -c "from claude_retry_proxy.server import validate_config; errs = validate_config({'tiers':{'haiku':{'provider':'p','model':'m'},'sonnet':{'provider':'p','model':'m'},'opus':{'provider':'p','model':'m'}},'models':{}}, {'p'}); assert any('no models' in e for e in errs), f'Expected models-per-provider error, got: {errs}'; print('PASS: validate_config rejects provider with no models')"` — script at `./tmp/verification/2026-08-26-dynamic-providers-no-collision-step2.py`
   → tester verify: Server refuses to start when a provider in `keys-index.json` has no entry in `config.models`.
   → tester verify: Server starts successfully when all providers have at least one model in `config.models`.

3. **Step 3:** Remove `build_reverse_map()` and `_reverse_model_map` global from `server.py`. Remove all `reverse_map` plumbing. <!-- UNCHANGED from original plan -->
   - Remove `build_reverse_map()` function (lines 249-270).
   - Remove `_reverse_model_map` global (line 79).
   - `forward_request()`: remove `reverse_map_snapshot` from the snapshot block (lines 613-625), stop threading it into `_forward_request_impl` (line 631).
   - `_forward_request_impl()`: remove `reverse_map` from the signature (line 639), remove the `reverse_map` conditional guard from the JSON buffering branches (lines 789, 847).
   - `_stream_upstream_response()`: remove `reverse_map=None` from the signature (line 1130), remove `reverse_map` from the `is_sse and tier and reverse_map` guard (line 1162), pass only `tier` to `_rewrite_sse_first_event` (line 1209).
   - `do_POST()`: remove `global _reverse_model_map` (line 1363), remove `new_reverse_map` construction and `_reverse_model_map` assignment from `/admin/api/switch` (lines 1508, 1519) and `/admin/api/reload` (lines 1572, 1603).
   - `main()`: remove `global _reverse_model_map` (line 1737), remove `build_reverse_map` call and error handling (lines 1811-1814).
   → coder verify (auto): `build_reverse_map` is not defined anywhere in `server.py` (grep returns empty).
   → coder verify (auto): `_reverse_model_map` is not referenced anywhere in `server.py` (grep returns empty).
   → coder verify (auto): `reverse_map` is not referenced anywhere in `server.py` (grep returns empty).
   → coder verify (scripted): `pip install -e .` succeeds, verify no reverse_map references — script at `./tmp/verification/2026-08-26-dynamic-providers-no-collision-step3.py`
   → tester verify: All existing tier-routing tests pass.
   → tester verify: Config with two tiers mapping to same model starts successfully and routes correctly.

4. **Step 4:** Use `tier` parameter directly in `_rewrite_sse_first_event()` and `_rewrite_json_response()` instead of reverse map lookup. <!-- UNCHANGED from original plan -->
   - `_rewrite_sse_first_event()`: replace `if upstream_model in reverse_map:` / `message["model"] = reverse_map[upstream_model]` with `message["model"] = tier`. Remove the `reverse_map` parameter.
   - `_rewrite_json_response()`: same replacement. Remove the `reverse_map` parameter.
   - Both functions always rewrite the model to the tier name when a `model` field is present — no conditional lookup.
   - Remove the unmapped-model warning trace events (`sse_unmapped_model`, `json_unmapped_model`) — they are no longer reachable.
   - Update docstrings to remove `reverse_map` references.
   → coder verify (auto): `_rewrite_sse_first_event` signature is `(event_bytes, tier, request_id)` (grep confirms).
   → coder verify (auto): `_rewrite_json_response` signature is `(body_bytes, tier, request_id)` (grep confirms).
   → coder verify (auto): `message["model"] = tier` in `_rewrite_sse_first_event` and `data["model"] = tier` in `_rewrite_json_response` (grep confirms both).
   → coder verify (auto): No reference to `reverse_map` in either function (grep returns empty).
   → coder verify (auto): No `sse_unmapped_model` or `json_unmapped_model` trace events in `server.py` (grep returns empty).
   → tester verify: SSE and JSON response model rewriting still work — tier name appears in responses.
   → tester verify: Two tiers sharing the same model each get their correct tier name.

5. **Step 5:** Tighten the models-per-provider check in `validate_config()` to validate shape, not just truthiness. <!-- UPDATED: review Warning — bare truthiness passes string values and lists containing empty strings -->
   - Replace the bare `if not models.get(provider)` check with explicit shape validation.
   - The entry must be a `list`, non-empty, and every element must be a non-empty `str` after stripping whitespace.
   - Code change in `validate_config()` (server.py ~line 240):
     ```python
     # Before:
     if not models.get(provider):
     # After:
     entry = models.get(provider)
     if not isinstance(entry, list) or len(entry) == 0 \
             or not all(isinstance(m, str) and m.strip() for m in entry):
     ```
   - Also remove the dead `input` from the CSS selector `select, input { ... }` in admin.html (line ~19) — one-word fix, same file.
   → coder verify (auto): `validate_config` in `server.py` contains `isinstance(entry, list)` in the models-per-provider check (grep confirms).
   → coder verify (auto): `validate_config` in `server.py` contains `all(isinstance(m, str) and m.strip() for m in entry)` (grep confirms).
   → coder verify (auto): `admin.html` CSS no longer contains `select, input` with `input` (grep returns empty for `select, input`).
   → coder verify (scripted): `pip install -e .` succeeds, verify shape validation rejects string and empty-string-list entries — script at `./tmp/verification/2026-08-26-dynamic-providers-no-collision-step5.py`
   → tester verify: `test_models_per_provider_validation` passes (existing — missing/empty catalog still rejected).
   → tester verify: New test cases for malformed entries: `"models": {"p": "claude-sonnet-5"}` (string) and `"models": {"p": [""]}` (list with empty string) are rejected at startup.

## Guidance for Tester

**Tests to create:**
- **Permanent:** `test_models_per_provider_validation` — config with a provider `p` in keys-index.json but no entry for `p` in `config.models` (or empty list). Server must refuse to start. Config with all providers having ≥1 model in `config.models` must start successfully. **UPDATED:** also test that `"models": {"p": "claude-sonnet-5"}` (string, not list) and `"models": {"p": [""]}` (list with empty string) are rejected at startup.
- **Permanent:** `test_two_tiers_same_model_same_provider` — config with haiku and sonnet both mapping to `deepseek-v4-flash` from provider `p`. Send a request with `"model": "sonnet"` and verify the response body contains `"model": "sonnet"`. Send a second request with `"model": "haiku"` and verify the response body contains `"model": "haiku"`. Also verify SSE responses are rewritten correctly for both tiers.

**Tests to investigate for retirement:**
- Planner candidates:
  - `tests/test_claude_proxy.py::test_config_validation_reverse_map_collision` — tests behavior that is intentionally removed (reverse map collision rejection). Delete the test function and its registry entry.
  - `tests/test_claude_proxy.py::test_admin_models_provider_keyed` — the assertions about `populateModels` and `config.models?.[tier]` absence need updating. The new admin.html has no placeholder options, no custom option, and stricter model-population logic. Update the test to verify: no `<option value="">`, no `__custom__`, dropdowns populate from `config.models[provider]`.
- Tester may identify additional candidates during test work.

**Retirement procedure:** For each candidate, verify the test exercises code being removed/changed. If obsolete: delete and note in session report. If still valid: document why in session report.

## Summary

**Problem:** Two issues:

1. When a new provider is added to `keys-index.json`, the admin page has no model suggestions for it because `config.json`'s `models` section has no entry. The model dropdown had "Custom..." as a workaround, but the user wants models strictly from `config.json`.

2. The proxy refuses to start if two tiers map to the same model name (`build_reverse_map` collision). This prevents legitimate configurations.

**Approach:**

**Issue 1 — Dynamic providers with strict model catalog:** Providers are only from `keys-index.json` (already dynamic via `/admin/api/providers`). Models are only from `config.json`'s `models` section. The admin page dropdowns are cleaned up: no placeholder options, no "Custom..." — only valid values appear. Startup validation ensures every provider in `keys-index.json` has at least one model in `config.models`; the proxy refuses to start otherwise. This catches the "apinebula" case at startup with a clear error message telling the user to populate `config.models`.

**Issue 2 — Remove reverse map collision:** The `build_reverse_map()` function and `_reverse_model_map` global are removed entirely. The `tier` variable is already resolved per-request and threaded through the call chain. Each request runs in its own thread with its own `tier` local variable. The rewrite functions use `tier` directly instead of a reverse map lookup.

```
Before:  upstream_model → reverse_map lookup → tier_name (collision if two tiers share model)
After:   tier (already known from request resolution) → tier_name (always correct, no map needed)
```

The reverse lookup in `resolve_tier()` step 3 scans `config["tiers"]` directly — it does not use `build_reverse_map()`'s output. When two tiers map to the same model, the first match wins (deterministic with Python 3.7+ insertion-ordered dicts).

**What is explicitly out of scope:**
- No changes to the `models` section structure in `config.json` — it remains a provider-keyed catalog of model names.
- No changes to the `config-template.json`.
- No changes to `analyze_proxy_trace.py`.
- No changes to the CLI (`cli.py`).
- No free-text model input, no datalist — models are strictly from the `models` catalog.

## Repo Mode

Public

## Document Overrides

| Document | Rule Overridden | Reason |
|----------|----------------|--------|
| CLAUDE.md line 175 | "Reverse map collisions (two tiers mapping to the same model name) are also rejected" | Reverse map is eliminated entirely |

## Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| Reverse lookup ambiguity in `resolve_tier()` (step 3) when two tiers share a model | Client sends `"model": "deepseek-v4-flash"` and the first tier in config dict wins | Step 2 (direct tier-name match) catches requests that use tier names. Step 3 reverse lookup is only for clients sending the actual upstream model name. |
| Adding a new provider to `keys-index.json` requires a corresponding `config.models` entry | Server refuses to start until user adds models | Error message is explicit: "provider 'X' has no models in config.models — add at least one model name for this provider" |

## Proposed Changes

1. **Step 1:** Clean up `admin.html` dropdowns — remove placeholder options, "Custom...", hidden custom input, and dead CSS.
   → coder verify (auto): `admin.html` contains no `<option value="">` (grep returns empty).
   → coder verify (auto): `admin.html` contains no `__custom__` (grep returns empty).
   → coder verify (auto): `admin.html` contains no `-custom-model` (grep returns empty).
   → coder verify (auto): `admin.html` contains no `onModelSelect` or `getModelValue` (grep returns empty).
   → coder verify (auto): `admin.html` contains no `.model-custom` (grep returns empty).
   → coder verify (scripted): Verify admin.html structure — script at `./tmp/verification/2026-08-26-dynamic-providers-no-collision-step1.py`
   → tester verify: `test_admin_page_served` passes.
   → tester verify: `test_admin_models_provider_keyed` passes (updated) — no placeholders, no custom option.

2. **Step 2:** Add startup validation: every provider in `_vendors` must have ≥1 model in `config.models`. Refuse to start otherwise.
   → coder verify (auto): `validate_config` contains a loop over `providers` checking `config["models"].get(p, [])` is non-empty.
   → coder verify (scripted): Verify validate_config rejects provider with no models — script at `./tmp/verification/2026-08-26-dynamic-providers-no-collision-step2.py`
   → tester verify: Server refuses to start when a provider lacks models in `config.models`.
   → tester verify: Server starts successfully when all providers have models.

3. **Step 3:** Remove `build_reverse_map()` and `_reverse_model_map` global from `server.py`. Remove all `reverse_map` plumbing.
   → coder verify (auto): `build_reverse_map` not defined in `server.py` (grep returns empty).
   → coder verify (auto): `_reverse_model_map` not referenced in `server.py` (grep returns empty).
   → coder verify (auto): `reverse_map` not referenced in `server.py` (grep returns empty).
   → coder verify (scripted): Verify no reverse_map references — script at `./tmp/verification/2026-08-26-dynamic-providers-no-collision-step3.py`
   → tester verify: All existing tier-routing tests pass.
   → tester verify: Config with two tiers mapping to same model starts successfully.

4. **Step 4:** Use `tier` parameter directly in `_rewrite_sse_first_event()` and `_rewrite_json_response()`. Remove `reverse_map` parameter from both signatures.
   → coder verify (auto): Both signatures are `(event_bytes, tier, request_id)` and `(body_bytes, tier, request_id)` respectively.
   → coder verify (auto): `message["model"] = tier` and `data["model"] = tier` in the respective functions.
   → coder verify (auto): No `reverse_map`, `sse_unmapped_model`, or `json_unmapped_model` in `server.py` (grep returns empty).
   → tester verify: SSE and JSON response model rewriting still work.
   → tester verify: Two tiers sharing the same model each get their correct tier name.

5. **Step 5:** Tighten models-per-provider check in `validate_config()` to validate shape, not just truthiness.
   → coder verify (auto): `validate_config` contains `isinstance(entry, list)` and `all(isinstance(m, str) and m.strip() for m in entry)` (grep confirms both).
   → coder verify (auto): `admin.html` CSS no longer contains `select, input` (grep returns empty).
   → coder verify (scripted): Verify shape validation — script at `./tmp/verification/2026-08-26-dynamic-providers-no-collision-step5.py`
   → tester verify: `test_models_per_provider_validation` passes (updated — malformed entries rejected).

## Guidance for Planner

- **Doc files to update:** `CLAUDE.md`, `README.md`
- **When:** after coder + tester finish
- **What to sync:**
  - `CLAUDE.md` line 87: Remove "build reverse map `{actual_model: tier}`" — replace with "resolve tier from request body, thread through call chain for response rewriting"
  - `CLAUDE.md` line 114: Remove "config + reverse_map" — change to "config state"
  - `CLAUDE.md` line 175: Remove "Reverse map collisions (two tiers mapping to the same model name) are also rejected" — replace with "Two tiers may map to the same model name; response rewriting uses the per-request tier"
  - `CLAUDE.md`: Add gotcha about the models-per-provider startup validation (every provider in keys-index.json must have ≥1 model in config.models)
  - `README.md` line 84: Remove "no reverse map collisions" from the validation description — replace with "every provider has at least one model in config.models"

## History

| Date | Event | Conclusion | Dismissed |
|------|-------|------------|-----------|
| 2026-08-26 | Spec revision (/update-plan) | Added Step 5: tighten validate_config shape validation (string, empty-string-list), fix dead CSS selector | — |
| 2026-08-26 | Review | Verdict: Issues found — non-blocking (0 Critical, 1 Warning, 1 Suggestion). | [review-models-truthiness](./tmp/reports/2026-08-26-dynamic-providers-no-collision-review-2026-08-26.json): Warning (Correctness); [review-dead-css-selector](./tmp/reports/2026-08-26-dynamic-providers-no-collision-review-2026-08-26.json): Suggestion (Readability) |
| 2026-08-26 | Spec revision (/update-plan) | Replaced datalist approach with strict dropdowns + models-per-provider startup validation; fixed Step 1/2 inline verification bugs and Step 4 test-removal misassignment | — |
| 2026-08-26 | Finalized (/update-plan) | All 5 issues resolved; 65/65 tests pass; plan complete | — |
| 2026-08-26 | Initial plan | Two-part plan: datalist-based model input + reverse map elimination | — |

## Plan Metadata

```json
{
  "plan_id": "2026-08-26-dynamic-providers-no-collision",
  "steps": [
    "Step 1: Clean up admin.html dropdowns — remove placeholders, custom option, dead CSS",
    "Step 2: Add startup validation — every provider must have >=1 model in config.models",
    "Step 3: Remove build_reverse_map() and _reverse_model_map from server.py",
    "Step 4: Use tier parameter directly in _rewrite_sse_first_event and _rewrite_json_response",
    "Step 5: Tighten validate_config models-per-provider check to validate shape, not just truthiness"
  ],
  "coder_files": [
    "src/claude_retry_proxy/admin.html",
    "src/claude_retry_proxy/server.py"
  ],
  "tester_files": [
    "tests/test_claude_proxy.py"
  ],
  "doc_files": [
    "CLAUDE.md",
    "README.md"
  ],
  "verification_scripts": [
    "./tmp/verification/2026-08-26-dynamic-providers-no-collision-step1.py",
    "./tmp/verification/2026-08-26-dynamic-providers-no-collision-step2.py",
    "./tmp/verification/2026-08-26-dynamic-providers-no-collision-step3.py",
    "./tmp/verification/2026-08-26-dynamic-providers-no-collision-step5.py"
  ],
  "repo_mode": "Public",
  "document_overrides": [
    "CLAUDE.md: \"Reverse map collisions (two tiers mapping to the same model name) are also rejected\" (Reason: reverse map is eliminated entirely)"
  ]
}
```

## Final Results

**Completion date:** 2026-08-26
**Status:** COMPLETED

### What was implemented

1. **Admin.html dropdowns cleaned up** (Step 1) — removed placeholder options, "Custom..." option, hidden custom-model input, dead CSS, and three associated JS functions (`onModelSelect`, `getModelValue`, `onProviderChange`). Model dropdowns now populate strictly from `config.models[provider]`.

2. **Models-per-provider startup validation** (Step 2) — `validate_config()` now checks that every provider in `keys-index.json` has at least one model in `config.models`. The proxy refuses to start with a clear error message otherwise.

3. **Reverse map eliminated** (Step 3) — `build_reverse_map()` function and `_reverse_model_map` global removed from `server.py`. All `reverse_map` plumbing stripped from `forward_request`, `_forward_request_impl`, `_stream_upstream_response`, `do_POST`, and `main()`.

4. **Tier-based response rewriting** (Step 4) — `_rewrite_sse_first_event()` and `_rewrite_json_response()` now use the per-request `tier` variable directly instead of a reverse map lookup. Two tiers can now map to the same model from the same provider.

5. **Shape validation tightened** (Step 5) — models-per-provider check upgraded from bare truthiness to explicit `isinstance(entry, list)` + `len(entry) == 0` + `all(isinstance(m, str) and m.strip() for m in entry)`. Dead `input` removed from `select, input` CSS selector.

### Files changed

| File | Change |
|------|--------|
| `src/claude_retry_proxy/admin.html` | Cleaned dropdowns, removed dead CSS/JS |
| `src/claude_retry_proxy/server.py` | Removed reverse_map, added models-per-provider validation, tightened shape check |
| `tests/test_claude_proxy.py` | Added `test_models_per_provider_validation`, `test_two_tiers_same_model_same_provider`; updated `test_admin_models_provider_keyed`; removed `test_config_validation_reverse_map_collision` |
| `CLAUDE.md` | Updated gotchas: reverse map → per-request tier, models-per-provider validation with shape detail |
| `README.md` | Updated config validation description |

### Test results

**65/65 tests pass, 0 failed, 0 skipped** (tester round 3, [report](./tmp/reports/2026-08-26-dynamic-providers-no-collision-tester-2026-08-26-3.json))

### Issues resolved

| Issue | Resolution |
|-------|------------|
| review-models-truthiness | Step 5: `isinstance` + all-elements-non-empty check |
| test-helper-models-default-blocked-by-new-validation | Test helpers updated to derive models from tiers/vendors |
| no-models-provider-model-field-unusable | Datalist reverted, strict `<select>` with startup validation |
| step4-test-removal-misassigned | Test removal moved to tester guidance |
| inline-verification-cmds-unpassable | Inline commands removed; canonical `.py` scripts are authority |