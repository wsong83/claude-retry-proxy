# Plan: Fix the case-sensitive response Content-Type dispatch lookup

**Plan ID:** 2026-11-20-fix-response-content-type-casing
**Created:** 2026-11-20

## Immediate Actions

*(none — Steps 1-4 complete; Phase 6 review in progress)*

## Issue Log

| Issue | Status | Found | Resolved | Resolved By |
|-------|--------|-------|----------|-------------|
| [response-content-type-lookup](./tmp/reports/defer-issue-response-content-type-lookup.json) | Resolved | 2026-11-16 | 2026-11-20 | [tester](./tmp/reports/2026-11-20-fix-response-content-type-casing-tester-2026-11-20.json) |

## Guidance for Coder

**Files to modify:**

- `src/claude_retry_proxy/forwarder.py`
- `src/claude_retry_proxy/server.py`

**Do not:** touch any test file, `CLAUDE.md`, `README.md`, or `doc/**` — those are the
tester's and planner's lanes. Do not change what is forwarded to the client: the
`resp_headers` dict keeps received header casing and last-wins duplicates end to end
(its building comment exists precisely to preserve that). Only the *dispatch* value
becomes case-insensitive.

**Step-by-step with verification:**

1. **Step 1: Case-insensitive dispatch derivation in `forwarder.py`**

   Replace the canonical-spelling lookup at the response-header capture
   (forwarder.py:1487-1497). The comment loses its now-stale clause, and the
   dispatch value is derived with lowercased keys (last-wins preserved — a dict
   comprehension overwrites, so the last matching header of any casing wins).

   Old comment + code (exact):

   ```python
                       # Non-retryable response. Headers are mapped from
                       # Headers.raw — the only carrier of the raw wire pairs:
                       # dict(resp.headers) lowercases keys and comma-joins
                       # duplicate values, which would blank the Content-Type
                       # dispatch below and change every forwarded header's
                       # casing. This comprehension reproduces today's
                       # dict(resp.getheaders()) exactly: received casing,
                       # last-wins duplicates.
                       resp_headers = {k.decode("latin-1"): v.decode("latin-1")
                                       for k, v in resp.headers.raw}
                       content_type = resp_headers.get("Content-Type", "").lower()
   ```

   New comment + code (exact):

   ```python
                       # Non-retryable response. Headers are mapped from
                       # Headers.raw — the only carrier of the raw wire pairs:
                       # dict(resp.headers) lowercases keys and comma-joins
                       # duplicate values, which would change every forwarded
                       # header's casing. This comprehension reproduces today's
                       # dict(resp.getheaders()) exactly: received casing,
                       # last-wins duplicates.
                       resp_headers = {k.decode("latin-1"): v.decode("latin-1")
                                       for k, v in resp.headers.raw}
                       # Dispatch lookup is case-insensitive per RFC 9110
                       # field-name rules: HTTP/2 connections and some gateways
                       # emit lowercased names, which a canonical-spelling
                       # lookup on the received-casing dict above would miss.
                       # Forwarding keeps received casing; only the dispatch
                       # value is normalized (lowercased keys, last-wins).
                       content_type = {k.lower(): v
                                       for k, v in resp_headers.items()}.get(
                                           "content-type", "").lower()
   ```

   The non-2xx rewrite site (forwarder.py:1669, `"application/json" in
   content_type and mode == "anthropic"`) reads this same variable — it is fixed
   by this step with no edit of its own. Every other consumer of
   `resp_headers` (the forwarding loops, `_crlf_safe`) is casing-agnostic.

   → coder verify (auto): `resp_headers.get("Content-Type"` appears **zero** times in
     `forwarder.py` (grep returns empty); the new literal `{k.lower(): v` is present
     in `forwarder.py`; the clause `would blank the Content-Type` is absent.
   → coder verify (scripted): part of the group gate
     `./tmp/verification/2026-11-20-fix-response-content-type-casing-dispatch.py`
     (run after Step 2; assertions `forwarder_no_canonical_lookup`,
     `forwarder_case_insensitive_derivation_present`,
     `behavioral_lowercase_json_rewrite`, `control_canonical_still_rewrites`).

2. **Step 2: Thread `content_type` into `_stream_upstream_response`**

   The second lookup lives in `server.py:363-365`
   (`_stream_upstream_response` re-derives `is_sse` from the raw-casing dict).
   The forwarder already resolved the dispatch value once — thread it instead of
   re-deriving, so both dispatch decisions share one source. The parameter is
   keyword-only with **no default**, mirroring the `epoch` doctrine: a missed
   call site fails loudly at run time, never silently mis-dispatches.

   `server.py` signature — old (exact):

   ```python
       def _stream_upstream_response(self, resp, status, resp_headers, request_id, retries,
                                      epoch, tier=None, mode=None, tools_declared=False,
                                      provider=None, key=None, retry_original_id=None):
   ```

   New (exact):

   ```python
       def _stream_upstream_response(self, resp, status, resp_headers, request_id, retries,
                                      epoch, tier=None, mode=None, tools_declared=False,
                                      provider=None, key=None, retry_original_id=None, *,
                                      content_type):
   ```

   `server.py` body — old (exact):

   ```python
           # Check Content-Type to determine rewriting strategy
           content_type = resp_headers.get("Content-Type", "").lower()
           is_sse = "text/event-stream" in content_type
   ```

   New (exact):

   ```python
           # content_type is resolved once by the forwarder's case-insensitive
           # dispatch and threaded here: this method must agree with that
           # dispatch, and re-deriving from the received-casing resp_headers
           # dict would repeat the canonical-spelling lookup defect.
           is_sse = "text/event-stream" in content_type
   ```

   Both call sites in `forwarder.py` (the SSE branch at ~1504 and the
   anthropic-mode other-content branch at ~1617) add
   `content_type=content_type,` to the keyword arguments (after
   `epoch=epoch,`).

   → coder verify (auto): `_stream_upstream_response`'s signature in `server.py`
     ends with `*, content_type`; `resp_headers.get("Content-Type"` appears zero
     times in `server.py`; both `handler._stream_upstream_response(` call sites in
     `forwarder.py` pass `content_type=content_type`.
   → coder verify (scripted): the group gate
     `./tmp/verification/2026-11-20-fix-response-content-type-casing-dispatch.py`
     exits 0 — assertions `server_no_canonical_lookup`,
     `server_signature_has_required_content_type`, `both_call_sites_thread_content_type`,
     `behavioral_lowercase_json_rewrite`, `control_canonical_still_rewrites` all PASS.
     Calibration: proven RED against the pre-change tree on 2026-11-20 (baseline
     recorded in History; assertions 1-6 FAIL, control PASS), script unedited.

## Guidance for Tester

**Tests to create:**

- **Permanent** (suggest `tests/test_response_headers.py`, which already stubs
  upstreams and drives the live proxy via `_harness`; reuse its stub/env pattern —
  the stub emits `send_header("content-type", ...)` with a lowercase name, which
  Python's `send_header` writes verbatim to the wire):
  1. `test_lowercase_resp_content_type_anthropic_json_rewrites_model` — stub 200
     `application/json` (lowercased name), anthropic-mode tier: response body's
     `model` equals the tier alias (pre-fix: the upstream model passed through raw).
  2. `test_lowercase_resp_content_type_anthropic_sse_rewrites_message_start` — stub
     200 `text/event-stream` (lowercased name), anthropic mode: the first event's
     `message_start.message.model` equals the tier alias (proves the SSE branch was
     taken — the raw passthrough would not rewrite).
  3. `test_lowercase_resp_content_type_chat_sse_streamed_as_anthropic` — chat-mode
     tier, stub SSE (lowercased name) carrying chat frames with `finish_reason`:
     the client receives Anthropic-shaped SSE events (`message_start` …
     `message_stop`), not the raw chat body; the trace records no
     `transform_failure` for the request (pre-fix: buffered whole → chat transform
     fails → raw passthrough).
  4. `test_lowercase_resp_content_type_non2xx_anthropic_json_rewrite` — stub 400
     `application/json` (lowercased name) with a top-level `model` field,
     anthropic mode: the error body's `model` is rewritten to the tier alias.
- Canonical-casing behavior is already covered by the existing suite (control);
  do not duplicate it.

**Tests to investigate for retirement:**

- Planner candidates: none — no test obsolescence identified. The change is
  additive (more upstream casings dispatch correctly); every existing canonical-path
  test remains valid.

**Retirement procedure:** n/a (no candidates).

→ tester verify: the four new tests pass; the full suite
  (`python tests/test_claude_proxy.py`) is green.

## Summary

**Problem.** The response-header capture builds `resp_headers` keyed by the
*received* header-name casing (deliberately — forwarding must preserve wire
casing), then looks the dispatch value up with the canonical spelling
`resp_headers.get("Content-Type", "")`. Any upstream emitting lowercased
response header names — every HTTP/2 connection, some HTTP/1.1 gateways —
yields `""`, and every decision keyed on it is silently skipped: the 2xx
`application/json` branch (anthropic-mode `model` never rewritten to the tier
alias), the 2xx `text/event-stream` branch (chat-mode SSE buffered whole → chat
transform fails → `transform_failure` → raw passthrough, no progressive
streaming), and the non-2xx anthropic JSON rewrite. There are exactly two
case-sensitive lookup sites (grep-verified): `forwarder.py:1497` (dispatches
SSE vs JSON vs other, and feeds the non-2xx rewrite) and `server.py:364`
(`_stream_upstream_response`'s `is_sse`).

```
upstream (lowercased headers) → forwarder capture (raw casing, kept)
                                    ├─ dispatch lookup  ← FIX 1 (case-insensitive)
                                    └─ forward to client (received casing, unchanged)
_filter/_stream_upstream_response ── is_sse lookup ← FIX 2 (threaded from FIX 1)
```

**Approach.** Derive the dispatch value with lowercased keys (last-wins kept);
forwarding untouched. Thread the resolved value into
`_stream_upstream_response` as a required keyword-only parameter rather than
re-deriving — one derivation site, and the two dispatch decisions cannot drift.
Verified experimentally on 2026-11-20: a local stub emitting `content-type:
application/json` makes the old expression return `''` while
`resp.headers.get` returns the value; the qwen vendor probe
(`token-plan.cn-beijing.maas.aliyuncs.com`, 404) returned all-lowercased wire
header names, confirming the affected vendor class first-hand.

**Design decisions (planner-owned, with rationale):**
- *Comprehension over `resp.headers.get`*: `Headers.get` comma-joins duplicate
  headers; the lowercased-key comprehension preserves the old dict's exact
  last-wins semantics for the dispatch value.
- *Keyword-only required param*: mirrors the `epoch` doctrine — a missed call
  site fails loudly instead of silently mis-dispatching (`content_type=""`
  would disable SSE detection silently).
- *Threaded, not re-derived*: the forwarder's branch and the stream method's
  branch are the same decision; two derivations invite drift.

**Alternatives rejected:** normalizing `resp_headers` keys to lowercase
(changes forwarded header casing, contradicting the verbatim-forward contract
and the capture comment's stated purpose); consulting `resp.headers.get` at
both sites (comma-join duplicates semantics; duplicates the policy in two
modules).

**Out of scope:** the ping-before-message_start SSE rewrite gap
(qwen opens its stream with `event:ping`, so the first-event-only rewrite
misses `message_start` even after this fix) — filed as
`./tmp/reports/defer-issue-sse-rewrite-ping-first.json`, own plan later.

## Repo Mode

Public

*Detected at plan creation (detect_repo_mode.py, 2026-11-20). Determines: plan archival path, commit-message content, staged files.*

## Document Overrides

*(empty — zero tolerance; every documented rule is in force)*

| Document | Rule Overridden | Reason |
|----------|----------------|--------|

## Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| `_stream_upstream_response` signature change | A missed call site would TypeError loudly at request time | Required keyword-only param (loud by design); exactly two call sites, both in `forwarder.py`, both edited in Step 2; no test calls the method directly (grep-verified) |
| Duplicate `Content-Type` headers with mixed casings | Last-wins now spans casings (old code only saw canonical-cased duplicates) | Degenerate upstream behavior; both consumers are substring tests, tolerant of any single value choice |
| Lowercased-header vendors now enter the JSON/SSE branches | The fix's intended behavior change — anthropic JSON/SSE and chat SSE take previously-dead paths | Step 3's four-path regression matrix exercises exactly these branches end-to-end |

## Proposed Changes

1. **Step 1:** Case-insensitive dispatch derivation in `forwarder.py` (exact old→new in Guidance for Coder)
   → coder verify (auto): `resp_headers.get("Content-Type"` zero matches in `forwarder.py`; `{k.lower(): v` present; `would blank the Content-Type` absent
   → coder verify (scripted): group gate `./tmp/verification/2026-11-20-fix-response-content-type-casing-dispatch.py` — forwarder assertions (run in full after Step 2)
2. **Step 2:** Thread `content_type` into `_stream_upstream_response` (required keyword-only; both call sites updated)
   → coder verify (auto): signature ends `*, content_type`; zero `resp_headers.get("Content-Type"` matches in `server.py`; both call sites pass `content_type=content_type`
   → coder verify (scripted): group gate exits 0 (all seven assertions PASS; RED baseline recorded in History)
3. **Step 3:** Regression tests for lowercased response header casing (four permanent tests in `tests/test_response_headers.py`)
   → tester verify: the four new tests pass; `python tests/test_claude_proxy.py` green
4. **Step 4:** Doc sync (`provider-modes.html` checked-first paragraph + first-event-only rewrite note), `CLAUDE.md` step-6 note, identifier sweep; ping-first deferral filed at drafting time
   → Evidence: `git grep -in 'Content-Type' doc/ CLAUDE.md` output reviewed and synced surfaces listed; `git grep -n 'resp_headers.get("Content-Type"'` returns empty; `./tmp/reports/defer-issue-sse-rewrite-ping-first.json` exists and parses

## Guidance for Planner

Documentation tasks you will execute yourself (not the coder):

- **Files to modify:**
  - `doc/provider-modes.html`
  - `doc/test-catalog.html`
  - `./CLAUDE.md`
- **`.claude/mega-audit-files.json`:** no changes (no declared audit locations added/renamed/retired).
- **When:** after the coder finishes (Steps 1-2), in parallel with / after the tester round.
- **What to sync:**
  - `doc/provider-modes.html` (~line 257): extend the checked-first paragraph — the
    field-name match is case-insensitive (RFC 9110); an upstream emitting lowercased
    header names — every HTTP/2 connection — dispatches identically, while forwarding
    keeps the received casing.
  - `doc/provider-modes.html` (SSE rewrite section): state that the anthropic-mode
    rewrite covers the **first event only**; vendors opening with a non-`message_start`
    event (e.g. a leading `ping`) are not rewritten — tracked as
    `defer-issue-sse-rewrite-ping-first`.
  - `CLAUDE.md` (Architecture step 6, ~line 153): add the case-insensitive
    field-name note to the "Content-Type is checked FIRST" sentence; note forwarding
    keeps received casing.
  - `doc/test-catalog.html`: add four per-test rows to the `test_response_headers.py`
    section (one per new test — RFC 9110 case-insensitive dispatch, the four branches,
    the received-casing-forwarded pin) and extend the module's catalog-table row to
    mention the lowercased-content-type dispatch matrix (per the tester's
    doc_suggestions).
  - Sweep: `git grep -in 'Content-Type' doc/ CLAUDE.md` and
    `git grep -n 'resp_headers.get("Content-Type"'` — sync every surface naming the
    dispatch; collect counts from the working tree (no exact-count maintenance).

## History

| Date | Event | Conclusion | Dismissed |
|------|-------|------------|-----------|
| 2026-11-20 | Review | [Report](./tmp/reports/2026-11-20-fix-response-content-type-casing-review-2026-11-20.json): verdict "Issues found — non-blocking"; zero Critical, zero Warning, 3 Suggestions. Both focus call sites verified thread-safe-by-construction (a missed site surfaces as 502 `forward_failed`, never a silent mis-dispatch); no case-sensitive response-header reads remain; forwarded header set genuinely untouched (received casing pinned by the SSE test). Suggestion `forwarded-casing-doc-scope` (my doc sentence overstated verbatim forwarding) fixed immediately in `CLAUDE.md` + `provider-modes.html` after the review returned. | [dup-header-last-wins-comment](./tmp/reports/2026-11-20-fix-response-content-type-casing-review-2026-11-20.json), [forwarded-casing-doc-scope](./tmp/reports/2026-11-20-fix-response-content-type-casing-review-2026-11-20.json) (fixed), [passthrough-site-uncovered](./tmp/reports/2026-11-20-fix-response-content-type-casing-review-2026-11-20.json) |
| 2026-11-20 | Planner Step 4 executed | Doc sync complete: `provider-modes.html` (checked-first paragraph — RFC 9110 case-insensitive field-name match, forwarding keeps received casing; first-event-only rewrite note naming `defer-issue-sse-rewrite-ping-first`), `CLAUDE.md` step-6 note, `test-catalog.html` (module row extended + four per-test rows per the tester's doc_suggestions). Sweeps clean: `resp_headers.get("Content-Type"` zero matches in src/ and doc/ (one archived-plan hit, historical record); all four surfaces verified. | — |
| 2026-11-20 | Spec revision (/update-plan) | Tester round succeeded (exit 0, fresh report [2026-11-20-tester](./tmp/reports/2026-11-20-fix-response-content-type-casing-tester-2026-11-20.json)): overall SUCCESS — all four permanent regression tests pass standalone, in-module, and in the full suite, each proven RED against the pre-fix tree; no issues filed; the SSE test additionally pins the forwarded-verbatim lowercased header name. Issue Log row Resolved. Planner Step 4 (doc sync) remains. | — |
| 2026-11-20 | Spec revision (/update-plan) | Coder round succeeded (exit 0, fresh report [2026-11-20-coder](./tmp/reports/2026-11-20-fix-response-content-type-casing-coder-2026-11-20.json)): Steps 1-2 complete, build pass, no issues filed, dispatch gate 7/7 GREEN (behavioral assertion now rewrites the tier alias through the real forward path). Proceed to tester round. | — |
| 2026-11-20 | Initial plan | Adopting defer-issue-response-content-type-lookup after independent verification (stub-upstream execution + qwen vendor probe); two-site fix confirmed by grep; ping-first gap filed as defer-issue-sse-rewrite-ping-first; mega-audit not triggered (4 steps, 2 source files). RED baseline of the dispatch gate on the pre-change tree: assertions 1-6 FAIL / control PASS (script unedited). | — |

## Plan Metadata

```json
{
  "plan_id": "2026-11-20-fix-response-content-type-casing",
  "steps": [
    "Step 1: Case-insensitive dispatch derivation in forwarder.py",
    "Step 2: Thread content_type into _stream_upstream_response",
    "Step 3: Regression tests for lowercased response header casing",
    "Step 4: Doc sync + ping-first deferral record + identifier sweep"
  ],
  "coder_files": ["src/claude_retry_proxy/forwarder.py", "src/claude_retry_proxy/server.py"],
  "tester_files": ["tests/test_response_headers.py"],
  "doc_files": ["doc/provider-modes.html", "doc/test-catalog.html", "./CLAUDE.md"],
  "verification_scripts": ["./tmp/verification/2026-11-20-fix-response-content-type-casing-dispatch.py"],
  "retire_inventory": [
    "./tmp/reports/2026-11-20-fix-response-content-type-casing-coder-2026-11-20.json",
    "./tmp/reports/2026-11-20-fix-response-content-type-casing-tester-2026-11-20.json",
    "./tmp/reports/2026-11-20-fix-response-content-type-casing-review-2026-11-20.json",
    "./tmp/verification/2026-11-20-fix-response-content-type-casing-dispatch.py"
  ],
  "repo_mode": "Public",
  "document_overrides": []
}
```

## Audit Accumulation

*Counters reset when mega-audit runs. Used by Phase 5 entry trigger.*

| Counter | Value | Last Updated |
|---------|-------|--------------|
| issues_resolved_since_audit | 1 | 2026-11-20 |
| steps_changed_since_audit | 0 | 2026-11-20 |
| files_changed_since_audit | 1 | 2026-11-20 |

## Documentation

Deep reference lives in `doc/` (indexed by `doc/content.html`); the dispatch
surface is `doc/provider-modes.html`. This plan's doc edits sync that file and
`CLAUDE.md`'s operational summary.

## Final Results

**Status: COMPLETED — 2026-11-20** (pending user approval to commit)

**What was implemented.** The response Content-Type dispatch is now
case-insensitive (RFC 9110 field-name rules) at both lookup sites: the
forwarder's dispatch derivation (which also feeds the non-2xx anthropic JSON
rewrite) and `_stream_upstream_response`'s `is_sse` decision — the latter via
a required keyword-only `content_type` parameter threaded from the forwarder,
so the two dispatch decisions share one source and a missed site fails loudly.
Forwarding keeps received header casing verbatim (streamed path includes
Content-Type; buffered paths synthesize their own canonical Content-Type).
An upstream emitting lowercased response header names — every HTTP/2 vendor —
now dispatches identically to canonical casing; the live-observed qwen
symptom (tier alias rewrite silently skipped) is fixed on all four branches.

**Verification.**
- Dispatch gate `./tmp/verification/2026-11-20-fix-response-content-type-casing-dispatch.py`:
  RED 1/7 pre-change → GREEN 7/7 post-change (script unedited); the behavioral
  assertion drives the real forward path against a lowercased-header stub.
- Tester: overall SUCCESS — the four permanent regression tests pass
  standalone, in-module, and in the full suite (537 passed / 0 failed), each
  proven RED against the pre-fix tree; the SSE test additionally pins the
  forwarded-verbatim lowercased header name.
- Reviewer: non-blocking verdict, zero Critical/Warning, 3 Suggestions
  (one fixed immediately — the doc forwarding-scope sentence; two noted in
  History Dismissed).

**Issues resolved:** [response-content-type-lookup](./tmp/reports/defer-issue-response-content-type-lookup.json) — Resolved 2026-11-20 (tester-confirmed).

**Deferred issues enumerated (open, by design):**
- [sse-rewrite-ping-first](./tmp/reports/defer-issue-sse-rewrite-ping-first.json) —
  the anthropic SSE rewrite covers the first event only; ping-first vendors
  (qwen) still miss the streamed `message_start` rewrite even after this fix.
  Filed 2026-11-20; own plan later. Documented in `provider-modes.html`.

**Out-of-scope observations recorded by the reviewer (non-blocking):**
the last-wins comment nuance for mixed-casing duplicate Content-Type headers
(no behavioral impact — both consumers are substring tests), and static-only
coverage of the anthropic 2xx non-JSON/non-SSE passthrough call site's
`content_type` threading.

**Cross-references to prior plans:** none — the adopted deferral was
standalone (filed 2026-11-16 by the user, no prior-plan row), and no
prior-plan deferred item is resolved by this implementation.
