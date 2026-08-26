# Plan: Fix config validation direction + heartbeat state corruption
**Project:** D:\proj\claude-retry-proxy
**Plan ID:** 2026-08-26-fix-validation-direction-heartbeat
**Created:** 2026-08-26

## Issue Log

| Issue | Status | Found | Resolved | Resolved By |
|-------|--------|-------|----------|-------------|
| [stale-pid-stops-stop](./tmp/reports/2026-08-26-fix-validation-direction-heartbeat-stale-pid-stops-stop.json) | Won't-fix | 2026-08-26 | 2026-08-26 | User confirmed: heartbeat fix (in-memory `_startup_state`) guarantees the PID will never be stale going forward — the server always writes `os.getpid()` from its own process, never reads from disk. The `cmd_stop` port-based fallback is unnecessary dead code. |

## Guidance for Coder

**Files to modify:**
- `src/claude_retry_proxy/server.py`

**Step-by-step with verification:**

1. **Step 1:** Fix `validate_config()` in `server.py` — change validation direction from keys→config to config→keys.
   - **Remove** the loop over `providers` (all keys-index.json providers) that checks each has models in `config.models`.
   - **Replace** with a loop over `config["models"].keys()` that checks: (a) valid shape (non-empty list of non-empty strings, existing check), and (b) each provider exists in `providers` set (new check — config→keys direction).
   - **Add** a check: every provider referenced in `tiers` must have an entry in `config.models`. Iterate `required_tiers`, look up each tier's provider, and if the provider is valid and known, verify it exists in `models`.
   - Error messages: shape violations keep the existing `"provider 'X' has no models in config.models"` message. Missing keys: `"provider 'X' in config.models has no entry in keys-index.json"`. Tier references missing models: `"provider 'X' (used by tier 'Y') has no entry in config.models — add at least one model name for this provider"`.
   → coder verify (auto): `validate_config` in `server.py` no longer iterates `for provider in providers:` at the models check (grep confirms old loop is gone).
   → coder verify (auto): `validate_config` contains a loop over `models.items()` (grep confirms `for provider, entry in models.items()`).
   → coder verify (auto): `validate_config` contains `"has no entry in keys-index.json"` (grep confirms config→keys check).
   → coder verify (auto): `validate_config` contains `"used by tier"` in the tier→models check (grep confirms).
   → coder verify (scripted): `pip install -e .` succeeds, then run validation scenarios — script at `./tmp/verification/2026-08-26-fix-validation-direction-heartbeat-step1.py`
   → tester verify: Config with provider in keys but not in models (and not referenced by any tier) starts successfully.
   → tester verify: Config with provider in models but not in keys fails to start with clear error.
   → tester verify: Config with provider referenced in tiers but not in models fails to start with clear error.

2. **Step 2:** Fix heartbeat state corruption in `server.py` — use in-memory startup state.
   - Add module-level variable `_startup_state = None` near the other globals (around line 84, after `_swap_done`).
   - In `main()`: after `write_state(state)` at line 1775, save `_startup_state = state` (the same dict just written). Add `_startup_state` to the `global` declaration at line 1682.
   - In `heartbeat_loop()`: instead of `state = read_state()` (which may return `{}` if the file was deleted externally), use `_startup_state` directly. Update `last_heartbeat` on the in-memory dict and write it. Guard with `if _startup_state is not None:`.
   → coder verify (auto): `_startup_state = None` is defined near the other globals in `server.py` (grep confirms).
   → coder verify (auto): `_startup_state = state` appears in `main()` after `write_state(state)` (grep confirms).
   → coder verify (auto): `heartbeat_loop` uses `_startup_state` instead of `read_state()` (grep confirms `_startup_state` in the function body).
   → coder verify (auto): `heartbeat_loop` no longer calls `read_state()` (grep confirms `read_state` not in `heartbeat_loop`).
   → coder verify (scripted): `pip install -e .` succeeds, verify heartbeat preserves pid/port fields — script at `./tmp/verification/2026-08-26-fix-validation-direction-heartbeat-step2.py`
   → tester verify: Delete proxy-state.json while proxy is running; after 30s, state file is recreated with pid, port, and all expected fields (not just `last_heartbeat`).

## Guidance for Tester

**Tests to create:**
- **Permanent:** `test_config_validation_models_to_keys` — provider in `config.models` but not in `keys-index.json` → server refuses to start. Provider in `keys-index.json` but not in `config.models` (and not referenced by any tier) → server starts successfully.
- **Permanent:** `test_config_validation_tier_provider_needs_models` — tier references a provider that has no entry in `config.models` → server refuses to start with clear error message mentioning the tier name.
- **Permanent:** `test_heartbeat_preserves_state` — start proxy, verify state file has `pid` and `port`, delete state file, wait 35s, verify state file is recreated with `pid` and `port` fields intact.

**Tests to update:**
- `test_models_per_provider_validation` — case (a) currently expects refusal when a provider in keys has no models entry. Update: provider NOT referenced by any tier and NOT in models → should START successfully (not refused). Add a new case where the provider IS referenced by a tier but has no models → should be REFUSED.
- `test_config_validation_unknown_provider` — no change needed (tier references unknown provider still refuses).

**Tests to investigate for retirement:**
- Planner candidates: none. All existing tests remain valid; only expectations change.
- Tester may identify additional candidates during test work.

**Retirement procedure:** For each candidate, verify the test exercises code being removed/changed. If obsolete: delete and note in session report. If still valid: document why in session report.

## Summary

**Problem:** Two bugs from the recent `2026-08-26-dynamic-providers-no-collision` plan:

1. **Config validation direction is wrong.** The new `validate_config()` check iterates all providers in `keys-index.json` and requires each to have models in `config.models`. But `keys-index.json` is a credential store that may contain inactive/broken/legacy providers. The user's intent is that `config.json` is authoritative — it defines which providers are active (`models` keys) and which are routed to (`tiers`). Validation should flow config→keys, not keys→config.

2. **Heartbeat corrupts state file.** The `heartbeat_loop()` reads state from disk, modifies `last_heartbeat`, and writes back. If the CLI's `cleanup()` deletes the file (during a failed start attempt), `read_state()` returns `{}`, and the heartbeat writes a state file with only `last_heartbeat` — losing `pid`/`port` permanently. The CLI then can't detect the running proxy.

**Approach:**

**Fix 1 — Validation direction (config→keys):**
```
Before:  for provider in keys_providers:   check models.get(provider)
After:   for provider in config.models:    check shape + check provider in keys
         for tier in required_tiers:       check tier.provider in config.models
```

Three checks:
- Every entry in `config.models` has valid shape (non-empty list of non-empty strings)
- Every provider in `config.models` exists in `keys-index.json` (config→keys)
- Every provider referenced in `tiers` has an entry in `config.models` (tiers→models)

Providers in `keys-index.json` that aren't in `config.models` and aren't referenced by any tier are silently ignored.

**Fix 2 — Heartbeat in-memory state:**
```
Before:  heartbeat reads state from disk → may get {} → writes degraded state
After:   heartbeat uses in-memory _startup_state (set at server init) → always has full fields
```

The server saves its initial state dict in a module-level `_startup_state` variable. The heartbeat updates `last_heartbeat` on this in-memory copy and writes it, never reading from disk. If the file is deleted externally, the next heartbeat recreates it with all fields intact.

**What is explicitly out of scope:**
- No changes to `cli.py` (the `cleanup()` function, `proxy-stderr.log` truncation, etc.)
- No changes to `admin.html`
- No changes to `config-template.json`
- No changes to the admin API endpoints

## Repo Mode

Public

## Document Overrides

| Document | Rule Overridden | Reason |
|----------|----------------|--------|
| CLAUDE.md line 126 | "Every provider in keys-index.json must have at least one model name in config.models" | Validation direction is reversed: config.models is authoritative, not keys-index.json |
| README.md ~line 84 | Config validation description referencing keys→config direction | Validation now flows config→keys: every provider in config.models must have keys, every tier-referenced provider must have a models entry |

## Proposed Changes

1. **Step 1:** Fix `validate_config()` — change validation direction from keys→config to config→keys.
   → coder verify (auto): `validate_config` no longer iterates `for provider in providers:` at the models check (grep confirms old loop is gone).
   → coder verify (auto): `validate_config` contains a loop over `models.items()` (grep confirms `for provider, entry in models.items()`).
   → coder verify (auto): `validate_config` contains `"has no entry in keys-index.json"` (grep confirms config→keys check).
   → coder verify (auto): `validate_config` contains `"used by tier"` in the tier→models check (grep confirms).
   → coder verify (scripted): Verify validation scenarios — script at `./tmp/verification/2026-08-26-fix-validation-direction-heartbeat-step1.py`
   → tester verify: Config with provider in keys but not in models (and not referenced by any tier) starts successfully.
   → tester verify: Config with provider in models but not in keys fails to start with clear error.
   → tester verify: Config with provider referenced in tiers but not in models fails to start with clear error.

2. **Step 2:** Fix heartbeat state corruption — use in-memory `_startup_state` instead of `read_state()`.
   → coder verify (auto): `_startup_state = None` defined near other globals in `server.py` (grep confirms).
   → coder verify (auto): `_startup_state = state` appears in `main()` after `write_state(state)` (grep confirms).
   → coder verify (auto): `heartbeat_loop` uses `_startup_state` instead of `read_state()` (grep confirms `_startup_state` in function body).
   → coder verify (auto): `heartbeat_loop` no longer calls `read_state()` (grep confirms `read_state` not in `heartbeat_loop`).
   → coder verify (scripted): Verify heartbeat preserves pid/port — script at `./tmp/verification/2026-08-26-fix-validation-direction-heartbeat-step2.py`
   → tester verify: Delete proxy-state.json while proxy is running; after 30s, state file is recreated with pid, port, and all expected fields.

## Guidance for Planner

- **Doc files to update:** `CLAUDE.md`, `README.md`
- **When:** after coder + tester finish
- **What to sync:**
  - `CLAUDE.md` line 126: Replace "Every provider in keys-index.json must have at least one model name in config.models — the proxy refuses to start otherwise" with the new validation rules: every provider in `config.models` must have valid shape, every provider in `config.models` must have keys, every tier-referenced provider must have a models entry. Add gotcha about the heartbeat in-memory state — the server keeps its startup state in memory and the heartbeat writes from that copy, so deleting `proxy-state.json` while the proxy is running will be repaired within 30s.
  - `README.md` ~line 84: Replace the config validation description referencing the old keys→config direction with the new rules: every provider in `config.models` must have a corresponding entry in `keys-index.json`, every provider in `config.models` must have at least one valid model name, and every provider referenced by a tier must have a models entry.

## History

| Date | Event | Conclusion | Dismissed |
|------|-------|------------|-----------|
| 2026-08-26 | Review | Verdict: Issues found — non-blocking (0 Critical, 1 Warning, 3 Suggestions). Ready to commit. | [review-models-isinstance-guard](./tmp/reports/2026-08-26-fix-validation-direction-heartbeat-review-2026-08-26.json): Warning (Correctness); [review-startup-state-stale](./tmp/reports/2026-08-26-fix-validation-direction-heartbeat-review-2026-08-26.json): Suggestion (Correctness); [review-test-mutates-real-state](./tmp/reports/2026-08-26-fix-validation-direction-heartbeat-review-2026-08-26.json): Suggestion (Design); [review-doc-drift-readme](./tmp/reports/2026-08-26-fix-validation-direction-heartbeat-review-2026-08-26.json): Suggestion (Readability) |
| 2026-08-26 | Spec revision (/update-plan) | Coder completed both steps (build pass); tester found 1 pre-existing issue (stale-pid-stops-stop) — won't-fix per user: heartbeat fix guarantees PID never stale | [stale-pid-stops-stop](./tmp/reports/2026-08-26-fix-validation-direction-heartbeat-stale-pid-stops-stop.json) |
| 2026-08-26 | Initial plan | Two fixes: validation direction keys→config reversed to config→keys, heartbeat state corruption fixed via in-memory startup state | — |

## Plan Metadata

```json
{
  "plan_id": "2026-08-26-fix-validation-direction-heartbeat",
  "steps": [
    "Step 1: Fix validate_config() — change validation direction from keys→config to config→keys",
    "Step 2: Fix heartbeat state corruption — use in-memory _startup_state instead of read_state()"
  ],
  "coder_files": [
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
    "./tmp/verification/2026-08-26-fix-validation-direction-heartbeat-step1.py",
    "./tmp/verification/2026-08-26-fix-validation-direction-heartbeat-step2.py"
  ],
  "repo_mode": "Public",
  "document_overrides": [
    "CLAUDE.md: \"Every provider in keys-index.json must have at least one model name in config.models\" (Reason: validation direction is reversed — config.models is authoritative, not keys-index.json)",
    "README.md: Config validation description referencing keys→config direction (Reason: validation now flows config→keys)"
  ]
}
```

## Final Results

**Completion date:** 2026-08-27
**Status:** COMPLETED

### What was implemented

1. **Validation direction reversed** (Step 1) — `validate_config()` in `server.py` changed from iterating all keys-index.json providers to iterating `config.models` entries. Three checks: (a) shape validation on every models entry, (b) every models provider must exist in keys-index.json (config→keys), (c) every tier-referenced provider must have a models entry (tiers→models). Providers in keys-index.json that aren't in config.models and aren't referenced by any tier are silently ignored.

2. **Heartbeat state corruption fixed** (Step 2) — `heartbeat_loop()` now uses in-memory `_startup_state` (set at server init from `os.getpid()`) instead of `read_state()` from disk. The PID is always the server's own process ID, never a stale value read from a corrupted file. If the state file is deleted externally, the next heartbeat recreates it with all fields intact within 30s.

### Files changed

| File | Change |
|------|--------|
| `src/claude_retry_proxy/server.py` | `validate_config()`: replaced keys→config loop with config→keys + tiers→models checks; `heartbeat_loop()`: uses in-memory `_startup_state` instead of `read_state()`; `main()`: saves `_startup_state` after `write_state()` |
| `tests/test_claude_proxy.py` | Added `test_config_validation_models_to_keys`, `test_config_validation_tier_provider_needs_models`, `test_heartbeat_preserves_state`; updated `test_models_per_provider_validation` (keys-only provider now starts successfully) |

### Test results

**68/68 tests pass, 0 failed, 0 skipped** ([tester report](./tmp/reports/2026-08-26-fix-validation-direction-heartbeat-tester-2026-08-26.json))

### Review verdict

**Issues found — non-blocking** (0 Critical, 1 Warning, 3 Suggestions) ([review report](./tmp/reports/2026-08-26-fix-validation-direction-heartbeat-review-2026-08-26.json))

### Issues resolved

| Issue | Resolution |
|-------|------------|
| stale-pid-stops-stop | Won't-fix — heartbeat fix guarantees PID will never be stale; `cmd_stop` port-based fallback would be dead code |

### Known caveats

- **Review Warning (Correctness):** `validate_config` iterates `models.items()` without an `isinstance(models, dict)` guard. All production entry points are protected by `load_config`'s dict validation; a direct call with a non-dict `models` would raise `AttributeError` instead of returning a validation error. Low risk. Future hardening could add a defensive guard.
- **Review Suggestion (Correctness):** The heartbeat's `_startup_state` snapshot is never refreshed if the state file is regenerated by the CLI's `_write_state` (two-writer scheme). The plan's 30s-repair guarantee holds because the heartbeat always writes the server's own PID. Pre-existing design property.
- **Review Suggestion (Design):** `test_heartbeat_preserves_state` mutates the real `~/.claude/proxy/proxy-state.json` in-process with a restore-in-finally. A mid-test interruption could leave the state file corrupted. Implemented as unit-style with user approval to avoid clobbering a live proxy.