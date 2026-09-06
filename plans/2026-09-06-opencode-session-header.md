# Plan: OpenCode session header — config-driven extra request headers
**Project:** D:\proj\claude-retry-proxy
**Plan ID:** 2026-09-06-opencode-session-header
**Created:** 2026-09-06

## Issue Log

Rows ordered newest-first (latest issues at top). New issues are prepended; resolved issues stay in place with updated status.

| Issue | Status | Found | Resolved | Resolved By |
|-------|--------|-------|----------|-------------|

## Guidance for Coder

**Files to modify:**
- `src/claude_retry_proxy/server.py`
- `src/templates/config.json`

**Step-by-step with verification:** each step below has coder checks tagged `(auto)` or `(scripted)`. The coder self-verifies `(auto)` checks and runs the provided script for `(scripted)` checks. Tester owns the behavioral checks. Line numbers below are anchors as of plan writing (2026-09-06) — locate by symbol name, line numbers may drift.

Architectural constraints:
- The resolver must be a pure helper (no globals except its four arguments); it is called from two places: the outbound header build in `_forward_request_impl` and the request trace entry in `do_POST`. It must be **total**: any unexpected shape (missing top-level key, empty rules, non-dict spec, non-string fields, `request_id=None`, unknown/`None` provider) degrades to skipping the affected rule / returning `{}` — it never raises. Validation in `validate_config` is the strict gate (append-to-errors convention, never throw); the resolver is defense-in-depth, not a second gate.
- Do **not** add `x-opencode-session`, `x-claude-code-session-id`, or any extra-header name to `FORWARD_HEADERS` — extra headers bypass the allowlist entirely. Only `user-agent` joins the allowlist.
- `from` entries are inbound header names matched case-insensitively **over a plain dict** (iterate `headers.items()` comparing `k.lower()` — do NOT rely on container case-insensitivity, because both call sites pass plain dicts); first non-empty (after `.strip()`) value wins. The **emitted value is the stripped value** — this applies to `fallback` literals as well as `from`-derived values (Phase-6 review finding, fixed in round 2). `fallback` is either a literal string or the exact token `"request_id"` (case-sensitive; resolves to the per-request uuid4 passed as `request_id`). The literal string `"request_id"` is not expressible as a fallback — token precedence, documented.
- Application order: resolved extra headers are applied **after** the per-mode provider-key injection in `_forward_request_impl`. Auth cannot be overridden by construction: validation rejects any spec `header` (lowercased) in the reserved-name set (see Step 1), which includes `x-api-key`/`authorization`.
- Do not touch `cli.py` — full config validation lives in `server.py validate_config` (existing layering; the CLI does light tier checks only and detects server-side validation failures via exit code).
- Do not change the `forward_request` return tuple or any existing function signatures except the new helper's. Step 3's trace logging **re-resolves** headers in `do_POST` — never thread resolved headers through the return tuple.
- The step-2 verification script `./tmp/verification/2026-09-06-opencode-session-header-step2.py` is planner-authored as part of this plan and pins the resolver contract. Run it as-is; do **not** regenerate it. If it fails, the resolver implementation is the defect.

## Guidance for Tester

**Tests to create:**
(All Permanent — this is permanent config-driven behavior.)

- `tests/_harness.py` — extend the shared mock upstream recorders to capture the full outbound request header set (at minimum: extra headers and `user-agent`, plus per-attempt header capture for the 429-retry mocks; the existing recorders capture only body + x-api-key/authorization/anthropic-beta). Blast-radius note: `_harness.py` underlies all 12 suite modules — run the full suite after this change.
- `tests/test_config_keys.py` — validation matrix for `extra_request_headers`, every malformed variant with its exact error string: non-dict top-level value (string and `null`); unknown provider key (not in `config.models`); spec not a dict (and spec `null`); missing `header`; non-string `header`; `header` not matching `^[A-Za-z0-9][A-Za-z0-9-]*$`; reserved `header` name — `authorization`, `x-api-key`, `host`, `content-length`, `content-type`, `accept`, `anthropic-version`, `anthropic-beta`, `user-agent`, `connection`, `transfer-encoding`, `expect`, `te`, `accept-encoding`, `cookie` — case-insensitive (one row per name); `from` present but not a list; non-string `from` entry; `from` entry not matching the token-charset regex; `from` entry stripped-empty; `from` entry equal to `authorization` or `x-api-key` (case-insensitive — secret-copying rejected); `fallback` present but non-string (int and dict); `fallback` empty; `fallback` stripped-empty; `fallback` containing CR/LF; `fallback` containing a control char; `fallback` not latin-1 encodable; neither `from` (non-empty and non-`[]`) nor `fallback` present — including the variant `from: []` with no fallback (empty list counts as absent); duplicate `header` names within one provider (exact and case-variant). Valid side: a config with rules passes empty-error; a config **without** the `extra_request_headers` key passes (the key is optional and defaults to `{}`); a provider with an **empty spec list** passes as a no-op — resolution yields no rules. <!-- UPDATED 2026-09-06 (/update-plan): empty per-provider spec list is valid, matching implemented behavior (tester documentation_discrepancies). -->
- `tests/test_mode_dispatch.py` — attach matrix via harness upstream-request capture: (a) opencode provider with rule, inbound `X-Claude-Code-Session-Id: <v>` (mixed case) → upstream receives `x-opencode-session: <v>` (case-insensitive inbound name match over a plain dict); (b) inbound `x-opencode-session` present → wins over the native header; (c) inbound value with padding `"  <v>  "` → upstream receives the **stripped** value; (d) neither inbound → value equals the request's `request_id` (obtain the expected value via the trace event's `request_id` with the harness correlation helper); (e) non-opencode provider → `x-opencode-session` absent upstream; (f) inbound `User-Agent: claude-cli/2.1.220 (external, cli)` → forwarded upstream for every mode (anthropic/chat/response), asserting the forwarded UA **value** and that **exactly one** User-Agent header line reaches upstream — do not assert header-name casing (the forwarded name keeps the inbound key's case).
- `tests/test_retry_streaming.py` — retry stability: a 429-retried request to an opencode provider carries the **same** `x-opencode-session` value on every attempt (harness captures per-attempt headers).
- `tests/test_admin.py` — extend the existing `test_admin_switch_preserves_disable_retry_flag` (test_admin.py:753) into a parameterized preservation case rather than adding a parallel near-copy test: one switch flow asserts both `disable_retry_claude_count_token` and `extra_request_headers` survive in the written config and the in-memory config (`GET /admin/api/config`).
- `tests/test_trace.py` — request trace events for a ruled provider include `"extra_request_headers": {"x-opencode-session": "<resolved>"}`; trace events for a non-ruled provider omit the key entirely; the unknown-model 400 error path (provider `None`) also omits the key.

**Tests to investigate for retirement:**
- Planner candidates: none identified — prior greps of `tests/` for `user-agent`, `FORWARD_HEADERS`, `fwd_headers`, `opencode-session`, `session-id` match nothing, so no existing test asserts the exact forwarded-header set. If grep results contradict this, reassess.
- Tester may identify additional candidates during test work.

**Retirement procedure:** For each candidate, verify the test exercises code being removed/changed. If obsolete: delete and note in session report. If still valid: document why in session report.

**Round 2 (Phase-6 review suggestions — quick-fix round):**
- `tests/test_trace.py` — remove the unused `_mode_tiers` import (line ~23).
- `tests/test_mode_dispatch.py` — add one attach-matrix case: a rule whose literal fallback is padded (`"  v  "`) emits the **stripped** value `"v"` upstream, and the trace entry records the stripped value.
- Re-run the full suite (`python tests/test_claude_proxy.py`) — all tests green including the new case.

## Summary

**Problem.** OpenCode emailed: requests to OpenCode Go missing an `x-opencode-session` header may start erroring 2026-09-06, and requests arrive with no user agent ("Unknown client") or `curl`. Root causes, both in the proxy: (1) `FORWARD_HEADERS` (an outbound allowlist) drops the client's `User-Agent` and any session headers — `http.client` adds no default UA (empirically verified: `putrequest()` emits only Host and Accept-Encoding), so upstream sees nothing; (2) nothing sets `x-opencode-session` because there is no config mechanism for per-provider extra headers. The header requirement is not mode-specific — the header build in `_forward_request_impl` is shared by anthropic/chat/response — but live-trace evidence shows the affected traffic is chat-mode (3,486 `mode_dispatch` events for `opencode-go`) plus response-mode `opencode-zen-openai` and anthropic-mode `opencode-zen-claude`; all three need coverage. Live trace also confirms no OpenCode enforcement error has fired yet (all 19 recent 400s are the proxy's own `count_tokens not supported in chat/response mode`).

**Approach.** Two pieces:

1. **New normalized config mechanism** — an optional top-level `extra_request_headers` map in `config.json`, keyed by provider name (matching the repo's provider-keyed `models` style). Each provider maps to a list of header specs; every spec attaches one outbound header to all upstream requests for that provider, any mode:

```json
"extra_request_headers": {
  "opencode-go": [
    {
      "header": "x-opencode-session",
      "from": ["x-opencode-session", "x-claude-code-session-id"],
      "fallback": "request_id"
    }
  ]
}
```

Resolution per request (pure helper `_resolve_extra_request_headers(headers, provider_name, config, request_id)` → `dict`): first non-empty inbound header among `from` (case-insensitive over a plain dict, stripped; the emitted value is the stripped value) wins; otherwise `fallback` — a literal string, or the case-sensitive token `"request_id"` resolving to the per-request uuid4 (the literal string `"request_id"` is not expressible; token precedence, documented). The resolver is total: missing top-level key, unknown/`None` provider, malformed rule shapes, or `request_id=None` with token fallback all degrade to a skipped rule / `{}` — the resolver never raises; validation is the strict gate. Built once before the retry loop, so the value is stable across 429/503 retries, and stable across the compat-retry re-invocation (same inputs: inbound headers + `request_id`). Claude Code natively sends `X-Claude-Code-Session-Id` on API requests since v2.1.86 (user runs 2.1.220) — "one stable ID per conversation" — so the proxy translates it, no client-side change needed. Validation joins `validate_config` (strict, startup + admin reload, append-to-errors — new checks never throw): the top-level key is **optional** (absent → `{}`, existing live configs keep starting); provider keys must be known; all string fields are type-guarded before any regex/truthiness check (a non-string `header` or `fallback` must produce a validation error, never a raise); `header` names must match `^[A-Za-z0-9][A-Za-z0-9-]*$` and not be reserved — the reserved set is the proxy-managed names {`authorization`, `x-api-key`, `host`, `content-length`, `content-type`, `accept`, `anthropic-version`, `anthropic-beta`, `user-agent`} plus hop-by-hop/protocol names {`connection`, `transfer-encoding`, `expect`, `te`, `accept-encoding`, `cookie`} — all case-insensitive; `from` entries share the token-charset shape rule and additionally reject `authorization`/`x-api-key` (copying the client's auth value into an arbitrary outbound header and the trace is not permissible); `fallback` must be a string whose stripped form is non-empty, latin-1 encodable, and free of CR/LF and control characters; each spec needs `from` (non-empty and non-`[]`; whitespace-only entries rejected like empty) and/or `fallback`; `header` names must be unique case-insensitively within a provider. Documented non-goal: no length caps on header names/values beyond the charset/latin-1 rules — the proxy's client is localhost and `http.client` bounds what reaches the wire.

2. **UA pass-through** — `user-agent` joins `FORWARD_HEADERS`, fixing "Unknown client"; OpenCode will then see `claude-cli/<version> (external, cli)`. Since `http.client` auto-adds no UA, the forwarded UA is the only one upstream — the tester attach-matrix asserts exactly one User-Agent line reaches upstream.

**Key plumbing gotcha:** the admin hot-switch handler rebuilds config from scratch and preserves only an explicit top-level key tuple (`server.py:3897`, currently `("disable_retry_claude_count_token",)`) — `extra_request_headers` must join it or tier switching would silently drop rules.

**Trace:** request trace events gain `"extra_request_headers": {<resolved map>}` when the provider has rules; key omitted otherwise. Mechanism: **re-resolution in `do_POST`** from `self.headers` + returned `provider` + `request_id` + `_current_config` — never threaded through the `forward_request` return tuple (signature/snapshot discipline preserved). `provider` `None` on early-error paths → `{}` → key omitted. The trace value uses `_current_config` at event time, so a mid-request config swap could log the post-swap mapping — trace-only cosmetic, accepted; a code comment at the trace site documents this. Privacy: the trace persists the resolved header **values** — for the opencode rule, the client's stable per-conversation session id. This was an explicit user decision ("log it"); the exposure is disclosed in README/CLAUDE.md (trace file is 0o600 on POSIX, world-readable on Windows unless ACL-restricted — existing gotcha).

**Deployment (user action, after this plan completes):** add the opencode rule to the live `~/.claude/proxy/config.json` and run `claude-retry-proxy reload` (or admin Reload). The shipped template ships `"extra_request_headers": {}` — empty and generic; the user's live config is theirs to fill. Existing live configs without the key are unaffected at upgrade (key optional). **Rollback:** recovery from a malformed value is deleting the `extra_request_headers` key from `~/.claude/proxy/config.json` and restarting — validation fails closed with the exact error string, so startup/reload refuse rather than run degraded.

**Alternatives considered:**
- Client-side hook injecting `additionalHeaders` with the hook `session_id` (Claude Code hooks support this): rejected — Claude Code already ships the native `X-Claude-Code-Session-Id` header, so a per-tool-call process-spawning hook is pure overhead (50–150 ms/tool call on Windows).
- `ANTHROPIC_CUSTOM_HEADERS` env var: rejected — static, cannot embed a per-conversation ID.
- Hardcoded `if provider_name.startswith("opencode")` in server.py: rejected by the user in favor of the normalized config map, which covers any future provider-specific header requirement.
- Rule-list config shape (`providers` array per rule): rejected — provider-keyed map matches the repo's existing config style and keeps validation simple.

**Out of scope:** direct-to-OpenCode curl traffic (bypasses the proxy; user adds headers manually if needed), client-side config changes, any count_tokens behavior.

## Repo Mode

Public

## Document Overrides

None — no documented rule is contradicted.

## Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| Live config lacks the rule after deploy → OpenCode enforcement errors continue | Broken requests on opencode tiers | Explicit deployment step (edit live config + reload); summary above names it |
| Admin hot-switch drops rules (preservation tuple missed) | Rules silently vanish on tier switch | Careful in Step 1; dedicated tester admin test (parameterized preservation) |
| Extra header name collides with proxy-managed headers or injected auth | Auth/body parsing broken upstream | Validation rejects the reserved-name set (proxy-managed + hop-by-hop, case-insensitive); tester malformed-variant rows |
| Resolved value invalid at send time (CR/LF, control chars, non-latin-1) | Untraced connection drop on every request for that provider | Fallback value validation at config time; resolver defense-in-depth skips bad rules; tester matrix rows |
| Value instability across retries | OpenCode sees multiple session IDs for one request | Resolver runs once before retry loop; tester retry-stability test |
| Malformed live config after hand-editing | Proxy refuses startup/reload | Strict validation fails closed with exact error; rollback = remove the key + restart |

## Proposed Changes

Each step includes verification checks tagged with confidence. `(auto)` = mechanical, coder self-verifies. `(scripted)` = deterministic multi-step, coder runs provided script.

1. **Step 1:** Add `extra_request_headers` schema support: validation in `validate_config` (whole-map checks per the Guidance-for-Tester matrix: optional top-level key defaulting to `{}` when absent; dict shape; known provider keys; spec shapes; type guards on every string field before any regex/truthiness check so non-string values produce validation errors, never a raise inside validation; header-name regex `^[A-Za-z0-9][A-Za-z0-9-]*$`; reserved-name rejection for the proxy-managed set `{"authorization", "x-api-key", "host", "content-length", "content-type", "accept", "anthropic-version", "anthropic-beta", "user-agent"}` plus hop-by-hop set `{"connection", "transfer-encoding", "expect", "te", "accept-encoding", "cookie"}` — all case-insensitive; `from` list shape with token-charset entries, stripped-empty rejection, and `authorization`/`x-api-key` rejection; `fallback` value validation: string, stripped-non-empty, latin-1 encodable, no CR/LF or control chars; at-least-one-of rule with `from: []` and whitespace-only entries counting as absent; case-insensitive duplicate `header` names within a provider rejected; all new checks append to the errors list — never raise), add `"extra_request_headers"` to the admin-switch preservation tuple (near server.py:3897), add `"extra_request_headers": {}` to `src/templates/config.json`.
   → coder verify (auto): `validate_config` contains the new checks (grep `extra_request_headers` in the function; read each check branch and confirm append-to-errors style); the preservation tuple at the admin-switch site lists the key; template file contains `"extra_request_headers": {}` as a top-level key.
   → tester verify: the permanent `tests/test_config_keys.py` validation matrix passes — every malformed variant returns its exact error string, valid configs with and without the key pass empty-error.

2. **Step 2:** Add the pure total resolver `_resolve_extra_request_headers(headers, provider_name, config, request_id)` (place near the HTTP forwarding section, before `_forward_request_impl`) and apply it in `_forward_request_impl`'s header build immediately after the per-mode provider-key injection (after server.py:1402): for each resolved `(name, value)` set `fwd_headers[name] = value`. The apply-loop sits in the header build only — never inside the retry loop — so the value is stable across attempts. Also add `"user-agent"` to `FORWARD_HEADERS` (server.py:153). Resolution order: `from` entries left-to-right, case-insensitive lookup over a plain dict (compare `k.lower()`), stripped-empty values treated as absent, **emitted value = stripped value**; then `fallback` (the case-sensitive token `"request_id"` → `request_id` argument — but if `request_id` is `None`, the rule yields nothing; anything else → literal). Defense-in-depth: skip any rule whose resolved value contains CR/LF (validation is the gate; this keeps the resolver total). Returns `{}` when the provider has no rules, is unknown, or is `None`; a missing `extra_request_headers` key yields `{}` (use `config.get("extra_request_headers", {})`).
   → coder verify (auto): helper exists with the exact 4-arg signature returning a dict; the apply-loop sits after the key-injection block and before `upstream_path` dispatch, and outside the retry loop; `FORWARD_HEADERS` set contains `"user-agent"`; no extra-header name appears in `FORWARD_HEADERS`.
   → coder verify (scripted): branch matrix — script at `./tmp/verification/2026-09-06-opencode-session-header-step2.py` (planner-authored, run as-is; 15 resolver cases — round-2 extension added a padded-fallback-literal case — including missing-key, provider-`None`, `request_id`-`None`, stripped-emit, fallback-literal strip emission, token case-sensitivity, CR/LF defense; exit 0 on pass).
   → tester verify: the permanent `tests/test_mode_dispatch.py` attach matrix and `tests/test_retry_streaming.py` retry-stability test pass — upstream captures, priority, stripped emit, request_id fallback, absent-for-other-providers, UA forwarding across all modes with exactly one UA line, same value on every 429 retry attempt.

3. **Step 3:** Log resolved extra headers in request trace events: in `do_POST`, when building the trace entry (server.py ~4044, after the `"provider"` field), compute `resolved = _resolve_extra_request_headers({k: v for k, v in self.headers.items()}, provider, _current_config, request_id)` and set `trace_entry["extra_request_headers"] = resolved` only when non-empty. **Re-resolution** is the mechanism — do NOT thread resolved headers through the `forward_request` return tuple (signature contract). `provider` may be `None` on early-error paths — the resolver returns `{}`, so the key is omitted. Add a code comment at the trace site documenting the accepted snapshot-vs-`_current_config` divergence (cosmetic-only).
   → coder verify (auto): trace-entry construction contains the call and the conditional assignment (read the site, trace the branch); no change to the `forward_request` return tuple or any unpack site; the divergence comment is present.
   → tester verify: the permanent `tests/test_trace.py` cases pass — ruled provider → key present with resolved map; non-ruled provider → key absent; unknown-model 400 error path → key absent.

4. **Step 4 (round 2 — Phase-6 review suggestions):** Fix the three findings from `tmp/reports/2026-09-06-opencode-session-header-review-2026-09-06.json` (verdict non-blocking, 3 suggestions): (a) remove the dead `fallback_valid` variable in `_validate_extra_header_spec` (server.py ~299/~324) — the neither-check reads `fallback is None`, so the variable is assigned but never read; (b) harmonize emission: fallback literals are emitted **stripped** like `from`-derived values (server.py ~1437) — apply `.strip()` on the literal-resolution path. No other behavior changes (do not touch tests; no signature, reserved-set, or trace-logic changes).
   → coder verify (auto): grep `fallback_valid` finds nothing; the fallback-literal path strips before emit; the round's diff touches only the two server.py sites.
   → coder verify (scripted): re-run `./tmp/verification/2026-09-06-opencode-session-header-step2.py` (now 15 cases incl. the padded-fallback-literal case) — exit 0.
   → tester verify: round-2 tester instructions below; full suite green.

<!-- UPDATED 2026-09-06 (/update-plan, review round): Step 4 added — user-directed quick-fix round for the 3 Phase-6 review suggestions. -->

## Guidance for Planner

Documentation tasks I execute myself (not the coder):

**Files to modify:**
- `CLAUDE.md`
- `README.md`

- **When:** after coder + tester complete (Final Results phase)
- **What to sync:**
  - `CLAUDE.md` — Architecture step 4 (mode dispatch) gains one bullet describing `extra_request_headers` (provider-keyed map, from/fallback resolution, `"request_id"` token and its precedence, reserved-name rejection, optional-key default) and the `user-agent` allowlist addition; Gotchas gains a note that the admin hot-switch preservation tuple now includes `extra_request_headers`, plus a note that the trace's new `extra_request_headers` field persists resolved header values (including the per-conversation session id) — the existing Windows world-readable-trace caveat applies; Gotchas "Test suite is safe alongside a live proxy" recount — update the "253 tests" figure to the new suite total after the tester completes (module count stays 12; all new tests land in existing modules); Documentation section — at Final Results, move this plan from `tmp/plans/` to `plans/` and add its `plans/2026-09-06-opencode-session-header.md` bullet per repository convention.
  - `README.md` — user-facing `config.json` section documents the `extra_request_headers` schema (provider-keyed map, `header`/`from`/`fallback` fields, `"request_id"` token and its precedence, reserved names, optional key) with the opencode-go example; UA forwarding mention included; the trace-log section notes the new `extra_request_headers` field and the session-id persistence disclosure.

## History

One row per event (spec revision / mega-audit / review / implementation round). Conclusion = one-sentence outcome or what changed.

| Date | Event | Conclusion | Dismissed |
|------|-------|------------|-----------|
| 2026-09-07 | Round 2 complete (/update-plan) | Coder round 2 (Step 4) and tester round 2 report back — both SUCCESS: full suite 259/259, step-2 scripted matrix 15/15, all three Phase-6 review suggestions closed. Final Results finalized (COMPLETED, ready for `/update-and-commit`). | — |
| 2026-09-06 | Spec revision (/update-plan, review round) | Phase-6 review verdict non-blocking (0 critical / 0 warning / 3 suggestions). User directed a quick-fix round: Step 4 (coder — dead `fallback_valid` removal, fallback-literal strip emission) + round-2 tester items (unused-import removal, padded-literal attach case). Step-2 script extended to 15 cases. | — |
| 2026-09-06 | Spec revision (/update-plan) | Coder and tester report back — both SUCCESS (259/259 tests, 0 failed, 0 skipped, no open issues; step-2 scripted matrix 14/14). Plan corrected: an empty per-provider spec list is a valid no-op (moved from the malformed-variant matrix to the valid side). Final Results written; Phase 6 reviewer launched. | — |
| 2026-09-06 | Mega-audit (pre-implementation, 11 lenses) | Verdict "Issues found — non-blocking" (39 findings, 0 High). Rev2 fixed all Medium findings: string type guards, extended reserved-name set (proxy-managed ∪ hop-by-hop), fallback value validation (latin-1, no CR/LF/control), strip-pinned resolution, optional-key default for existing configs, total resolver, harness capture scope, admin-test parameterization, explicit trace re-resolution, verification-script ownership, CLAUDE.md test-count + plans/-migration sync items. Exit condition met (0 High) — no re-audit. | 17 Low findings acknowledged: the http.client "double UA" Medium's premise plus its Low cousins refuted empirically (putrequest emits no default UA); literal-"request_id" collision → documented token precedence; duplicate-name and from-name auth-copy Lows closed in validation anyway; size-bounds Low → documented non-goal; trace-value privacy Lows → user-approved value logging, docs now disclose; pre-existing step-2 script Low → planner-authored by design, run-as-is constraint added; cosmetic concurrency/divergence Lows → code comment in Step 3; migration/rollback Lows closed by the Deploy/Rollback paragraph. |
| 2026-09-06 | Initial plan | Scope set with user: config-driven provider-keyed map (rejected hardcode + rule-list), curl direct traffic out of scope, trace logging included. | — |

## Plan Metadata

Fenced ```json block — the machine contract read by `parsePlanContext`. **Update it on every revision.**

```json
{
  "plan_id": "2026-09-06-opencode-session-header",
  "steps": ["Step 1: Add extra_request_headers schema, validation, admin-switch preservation, template key", "Step 2: Add resolver, apply in header build, forward user-agent", "Step 3: Log resolved extra headers in request trace events", "Step 4: Fix Phase-6 review suggestions in server.py (dead variable, fallback-literal strip emission)"],
  "coder_files": ["src/claude_retry_proxy/server.py", "src/templates/config.json"],
  "tester_files": ["tests/_harness.py", "tests/test_config_keys.py", "tests/test_mode_dispatch.py", "tests/test_retry_streaming.py", "tests/test_admin.py", "tests/test_trace.py"],
  "doc_files": ["CLAUDE.md", "README.md"],
  "verification_scripts": ["./tmp/verification/2026-09-06-opencode-session-header-step2.py"],
  "repo_mode": "Public",
  "document_overrides": []
}
```

## Audit Accumulation

*Counters reset when mega-audit runs. Used by Phase 5 entry trigger.*

| Counter | Value | Last Updated |
|---------|-------|--------------|
| issues_resolved_since_audit | 0 | 2026-09-06 |
| steps_changed_since_audit | 0 | 2026-09-06 |
| files_changed_since_audit | 0 | 2026-09-06 |

## Documentation

- `./tmp/plans/2026-09-06-opencode-session-header.md` (this plan)
- `./tmp/reports/2026-09-06-opencode-session-header-mega-audit-2026-09-06.json` (mega-audit report)
- `./tmp/reports/2026-09-06-opencode-session-header-review-2026-09-06.json` (Phase 6 review report)
- `./tmp/verification/2026-09-06-opencode-session-header-step2.py` (step-2 coder verification script)

## Final Results

- **Completion date:** 2026-09-07 (finalized; rounds 1–2 executed 2026-09-06)
- **Status:** COMPLETED — round 2 closed all three Phase-6 review suggestions

**Files changed** (working tree; commit pending `/update-and-commit`):
- Implementation — `src/claude_retry_proxy/server.py`: `_validate_extra_header_spec` + `validate_config` integration (type guards, 15-name reserved set, fallback value validation, exact error strings), total resolver `_resolve_extra_request_headers`, header-build application after provider-key injection and outside the retry loop, `user-agent` in `FORWARD_HEADERS`, `extra_request_headers` trace field (re-resolution, provider-`None` handling, divergence comment), admin-switch preservation tuple; round 2: dead `fallback_valid` variable removed from `_validate_extra_header_spec`, fallback literals emitted stripped (token precedence preserved). `src/templates/config.json`: `"extra_request_headers": {}`.
- Tests — `tests/_harness.py` (full outbound-header capture + fixtures), `tests/test_config_keys.py` (45-check validation matrix + startup integration), `tests/test_mode_dispatch.py` (attach matrix + UA all modes/exactly-one-UA), `tests/test_retry_streaming.py` (per-attempt retry stability), `tests/test_admin.py` (parameterized preservation of both top-level keys), `tests/test_trace.py` (field present/absent + provider-`None` 400 path); round 2: attach-matrix case (f) (padded literal fallback → stripped value upstream and in the trace), unused `_mode_tiers` import removed from `tests/test_trace.py`.

**Test results:** full suite 259/259 green in both rounds (0 failed, 0 skipped; 253 → 259 from the new permanent tests); coder step-2 scripted matrix 14/14 in round 1 → 15/15 in round 2.

**Issues resolved:** none were opened in either round (coder 0, tester 0). One plan-text divergence accepted: an empty per-provider spec list validates as a no-op (Guidance-for-Tester matrix updated to match). All three Phase-6 review suggestions closed in round 2: #1 dead `fallback_valid` (coder), #2 unused `_mode_tiers` import (tester), #3 fallback-literal strip asymmetry (coder + tester case (f)).

**Reports:** coder `tmp/reports/2026-09-06-opencode-session-header-coder-2026-09-06.json` · tester `tmp/reports/2026-09-06-opencode-session-header-tester-2026-09-06.json` · mega-audit `tmp/reports/2026-09-06-opencode-session-header-mega-audit-2026-09-06.json` · Phase 6 review `tmp/reports/2026-09-06-opencode-session-header-review-2026-09-06.json` — verdict "Issues found — non-blocking" (0 critical, 0 warning, 3 suggestions), all three fixed in round 2 · coder round 2 `tmp/reports/2026-09-06-opencode-session-header-coder-2026-09-06-2.json` · tester round 2 `tmp/reports/2026-09-06-opencode-session-header-tester-2026-09-06-2.json`

**Documentation:** planner-owned CLAUDE.md/README sync per Guidance for Planner (Architecture bullet, Gotchas notes, 253 → 259 recount, trace-field disclosure, README schema section, plans/ move) executes at `/update-and-commit`.

**User deployment reminder (unchanged):** add the opencode rule to the live `~/.claude/proxy/config.json` and run `claude-retry-proxy reload` — OpenCode enforcement for missing `x-opencode-session` went live 2026-09-06.