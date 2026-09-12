# Plan: Build a `doc/` tree and shrink CLAUDE.md against it
**Project:** D:\proj\claude-retry-proxy
**Plan ID:** 2026-09-12-build-doc-tree
**Created:** 2026-09-12

## Issue Log

| Issue | Status | Found | Resolved | Resolved By |
|-------|--------|-------|----------|-------------|
| [architecture-compat-exception-from-transformed-body](./tmp/reports/2026-09-12-build-doc-tree-architecture-compat-exception-from-transformed-body.json) | Resolved | 2026-09-13 | 2026-09-13 | tester |
| [error-responses-byte-for-byte-overclaim](./tmp/reports/2026-09-12-build-doc-tree-error-responses-byte-for-byte-overclaim.json) | Resolved | 2026-09-13 | 2026-09-13 | tester |
| [cli-reload-origin-claim-wrong](./tmp/reports/2026-09-12-build-doc-tree-cli-reload-origin-claim-wrong.json) | Resolved | 2026-09-13 | 2026-09-13 | tester |
| [test-catalog-lacks-per-test-inventory](./tmp/reports/2026-09-12-build-doc-tree-test-catalog-lacks-per-test-inventory.json) | Resolved | 2026-09-13 | 2026-09-13 | tester |
| [doc-facts-duplicated-across-pages](./tmp/reports/2026-09-12-build-doc-tree-doc-facts-duplicated-across-pages.json) | Resolved | 2026-09-13 | 2026-09-13 | tester |
| [review-claude-md-mode-dispatch-qualifier](./tmp/reports/2026-09-12-build-doc-tree-review-2026-09-12.json) · [verify](./tmp/reports/2026-09-12-build-doc-tree-tester-2026-09-13-2.json) | Resolved | 2026-09-13 | 2026-09-13 | tester |
| [review-admin-switch-preservation-set](./tmp/reports/2026-09-12-build-doc-tree-review-2026-09-12.json) · [verify](./tmp/reports/2026-09-12-build-doc-tree-tester-2026-09-13-2.json) | Resolved | 2026-09-13 | 2026-09-13 | tester |
| [review-trace-log-every-request-claim](./tmp/reports/2026-09-12-build-doc-tree-review-2026-09-12.json) · [verify](./tmp/reports/2026-09-12-build-doc-tree-tester-2026-09-13-2.json) | Resolved | 2026-09-13 | 2026-09-13 | tester |
| [review-content-env-var-count-card](./tmp/reports/2026-09-12-build-doc-tree-review-2026-09-12.json) · [verify](./tmp/reports/2026-09-12-build-doc-tree-tester-2026-09-13-2.json) | Resolved | 2026-09-13 | 2026-09-13 | tester |
| [review-style-css-dead-rules](./tmp/reports/2026-09-12-build-doc-tree-review-2026-09-12.json) · [verify](./tmp/reports/2026-09-12-build-doc-tree-tester-2026-09-13-2.json) | Resolved | 2026-09-13 | 2026-09-13 | tester |
| [review-anchor-resolver-not-committed](./tmp/reports/2026-09-12-build-doc-tree-review-2026-09-12.json) · [deferred](./tmp/reports/defer-issue-review-anchor-resolver-not-committed.json) | Open | 2026-09-13 | — | — |
| [review-content-readme-link-raw-markdown](./tmp/reports/2026-09-12-build-doc-tree-review-2026-09-12.json) · [deferred](./tmp/reports/defer-issue-review-content-readme-link-raw-markdown.json) | Open | 2026-09-13 | — | — |
| [invalid-mode-described-as-startup-rejection](./tmp/reports/2026-09-12-build-doc-tree-invalid-mode-described-as-startup-rejection.json) | Resolved | 2026-09-12 | 2026-09-12 | tester |
| [env-range-described-as-clamp](./tmp/reports/2026-09-12-build-doc-tree-env-range-described-as-clamp.json) | Resolved | 2026-09-12 | 2026-09-12 | tester |
| [probe-lock-described-per-key](./tmp/reports/2026-09-12-build-doc-tree-probe-lock-described-per-key.json) | Resolved | 2026-09-12 | 2026-09-12 | tester |
| [trace-request-entry-field-inventory](./tmp/reports/2026-09-12-build-doc-tree-trace-request-entry-field-inventory.json) | Resolved | 2026-09-12 | 2026-09-12 | tester |
| [compat-stripped-variant-source](./tmp/reports/2026-09-12-build-doc-tree-compat-stripped-variant-source.json) | Resolved | 2026-09-12 | 2026-09-12 | tester |
| [extract-model-raises-on-non-object-json](./tmp/reports/defer-issue-extract-model-raises-on-non-object-json.json) | Open | 2026-09-12 | — | — |
| [compat-entry-failed-confirmations-dead-field](./tmp/reports/defer-issue-compat-entry-failed-confirmations-dead-field.json) | Open | 2026-09-12 | — | — |
| [claude-md-line-refs-rotted](./tmp/reports/defer-issue-claude-md-line-refs-rotted.json) | Resolved | 2026-09-12 | 2026-09-12 | tester |
| [claude-md-sinks-policy-duplicated](./tmp/reports/defer-issue-claude-md-sinks-policy-duplicated.json) | Resolved | 2026-09-12 | 2026-09-12 | tester |
| [planner-reads-nonexistent-test-catalog](./tmp/reports/defer-issue-planner-reads-nonexistent-test-catalog.json) | Resolved | 2026-09-12 | 2026-09-12 | tester |
| [extraction-criteria-link-dead-in-public](./tmp/reports/defer-issue-extraction-criteria-link-dead-in-public.json) | Open | 2026-09-12 | — | — |

## Guidance for Coder

**Files to modify:** none.

This plan has **zero coder steps**. Every target path (`doc/**`, `CLAUDE.md`, `README.md`) is planner-lane per the planner agent definition. There is no source code, no test, and no configuration change. The coder agent should not be launched for this plan.

## Guidance for Tester

**Tests to create:** none. This plan changes no source code and no test file, so there is no new behavior to test.

The tester's role here is **content-accuracy verification** — reading the code and confirming the doc pages describe it correctly. This is the one class of check the planner cannot self-certify, because the planner authored the prose. See `## Proposed Changes` steps for the specific `→ tester verify:` lines.

Two checks in this plan are deliberately **bidirectional** (every documented symbol appears in code, *and* every code-emitted symbol is documented). A one-directional check cannot detect an omitted event or field, because an omission is absent from both sides being compared.

<!-- UPDATED: added 2026-09-12 by /update-plan. Record of the first pass and what the second one must do. -->
**First pass (2026-09-12): FAILURE, and the verdict was correctly reasoned.** The project suite passed cleanly (293 passed, 0 failed, exit 0) and every structural deliverable was verified present — but the tester judged the plan on its own terms, since this plan *redefines the tester's job* as content-accuracy verification, and two of the plan's `→ tester verify:` criteria were unmet. Six issue reports were filed: four newly-authored prose errors (invalid-mode startup claim, env "clamp" claim, per-key probe lock, the `extract_model` "never raises" overclaim), one plan-identified phantom that was only half-fixed (`mode` removed from the page but left in CLAUDE.md), and one inherited inaccuracy (compat stripped-variant source). The bidirectional event check passed cleanly in both directions — all 30 code-emitted event names are documented with no phantom events.

**The lesson for the second pass:** a structural check cannot catch this class of defect. Everything the planner's scripted gates verify — anchors resolve, no secrets, TOC complete, files tracked — was green while five pages asserted behavior the code does not have. That is precisely the Risk this plan named ("Doc asserts behavior the code does not have — worse than the rot it replaces"). The second pass must re-read the six corrected claims against the code, and must also confirm the corrections did not introduce a *new* discrepancy.

**Tests to investigate for retirement:** No test obsolescence identified. Verified by grep: no file under `tests/` references `CLAUDE.md`, `README.md`, any `.md` path, `doc/`, `content.html`, or `doc_structure_check.py`. The aggregator uses a static 13-module import list and `pyproject.toml` uses explicit src-layout, so a new root `doc/` tree cannot affect test collection or packaging.

## Summary

`CLAUDE.md` is 46,540 bytes / 46,318 characters. It is the only documentation artifact in this repo injected into **every** session, and it has grown into a derived description of the code — a 100-line request-path walkthrough, full chat/response transform algorithms, and a duplicate of the sink failure policy. Derived descriptions rot: `server.py:4797` is cited in the file but the module is 4,650 lines, and `server.py:2254` is cited as a retry sleep but is a docstring line.

The repo has no `doc/` directory. The sibling project `../word-grinder` establishes the convention this plan adopts: a flat `doc/` of HTML pages sharing one `style.css`, indexed by `content.html`, gated by the committed `~/.claude/scripts/doc_structure_check.py`, with `CLAUDE.md` retaining a terse operational summary plus anchored pointers (`doc/architecture.html#retry`) into the deep reference.

**Three-way audience split** (the organizing principle):

| Audience | Artifact | Register |
|---|---|---|
| Claude | `CLAUDE.md` | Terse, imperative, operational + anchored pointers |
| Human, getting started | `README.md` | Setup, usage, config — self-contained |
| Human, going deep | `doc/*.html` | Explanatory prose, rationale, internals |

**This is a rewrite, not a move.** HTML prose for humans reads differently from CLAUDE.md's instruction register, so the migrated content is re-authored rather than relocated. CLAUDE.md keeps the terse operational version of the same facts. That duplication is explicitly sanctioned by the global rule (*"Duplication is fine — anything both audiences need can appear in both files"*).

**The gate.** `doc_structure_check.py` enforces 10 rules and a global `PostToolUse` hook runs it on every `Write|Edit` resolving inside `<cwd>/doc/`. It currently no-ops here (it exits 0 with "No docs to audit"). Constraints that shape the design:

- Content files must be `.html` — `doc/` is pure HTML, no `.md`.
- `content.html` and `style.css` are mandatory.
- **Every `<a href>` must be relative.** `http://`, `https://`, `//`, and root-relative `/` are violations. External URLs may appear as *text* only, never as links. This is the sharpest constraint: a proxy doc that wants to cite the Anthropic Messages API or the OpenAI Chat Completions spec must show the URL in a `<code>` block.
- Every `.html` needs a non-empty `<title>` and a last-updated indicator.
- The gate does **not** check that relative TOC targets exist, and does **not** scan for secret-shaped strings. Both gaps are covered by `./tmp/verification/2026-09-12-build-doc-tree-step9.py` (Step 9) and the Step 11 TOC check.
- AI-tooling-term scanning is **skipped** — this repo is public (verified: `detect_repo_mode.py` → "public").
- Scripts-coverage is **N/A** — it triggers only on a literal `<cwd>/root/scripts`, which does not exist here (this repo's scripts live at `<cwd>/scripts/`).

**Projected result.** The disposition below moves 15,893 of the Gotchas section's 18,718 characters out and keeps 2,792, leaving roughly 2,000–2,500 characters of replacement summaries and pointers. That is a larger reduction than "shrink the biggest bullets" would suggest:

| Artifact | Now | After |
|---|---:|---:|
| `CLAUDE.md` | 46,318 chars | **~21,000** |
| `README.md` | 23,488 bytes | ~24,000 (gains doc links) |
| `doc/` | 0 | ~95,000 (7 content pages + `content.html` + `style.css` = 9 files) |

**The `## Unresolved Deferred Issues` block is NOT restructured.** An earlier draft of this plan proposed dropping the `report` and `target_repo` fields on the grounds that they point into gitignored `tmp/`. The mega-audit showed this cannot hold: `~/.claude/agents/report-schemas.md` marks both fields **Required: Yes**, and `/update-and-commit` Step 9.9 is the block's **sole writer**, rebuilding it from that schema on every commit. The restructure would be reverted by the very commit that lands this plan. The block is therefore preserved byte-stable, and unchanged content accounts for 2,324 of the ~21,000 target.

**Out of scope — explicitly:**

- **The 826 KB `plans/` corpus** (20 files). Not touched. It is read-on-demand and costs no context budget.
- **`.claude/cluster-extraction-criteria.md`** — stays untracked, as the user directed. Because that leaves `CLAUDE.md:529` as a dead link in a published repo, the deliberate non-fix is recorded as a deferred issue (see Issue Log) rather than left unrecorded.
- **`report-schemas.md` and `/update-and-commit` Step 9.9** — user-global tooling outside this repo, not modified.
- **No source, test, or config changes.** The proxy's behavior is untouched.

## Repo Mode

Public

*Detected via `~/.claude/scripts/detect_repo_mode.py` — output "public". Confirms the AI-term scan is skipped by the gate.*

## Document Overrides

| Document | Rule Overridden | Reason |
|----------|----------------|--------|
| `~/.claude/CLAUDE.md` — "CLAUDE.md Maintenance" | "Keep CLAUDE.md files compact, but never silently delete... flag any redundant or outdated content for the user... wait for explicit approval before removing it" | Deletions are enumerated per-bullet in the disposition table, and Step 9 executes in two phases with an explicit user-approval checkpoint between them. Nothing is removed without a recorded disposition and an approval. |

## Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| Step 9 deletes content from a git-tracked guidance file with no restore point | Unrecoverable loss of hand-written operational guidance | **Restore point:** commit the pre-shrink state (or create a `pre-doc-shrink` tag) before Step 9. Revert with `git checkout <commit> -- CLAUDE.md`. Step 9 also writes atomically (tmp file + `os.replace`, mirroring `StateSink`) so an exception mid-write cannot truncate the file. |
| Rewritten prose drifts from actual behavior during re-authoring | Doc asserts behavior the code does not have — worse than the rot it replaces | Each page carries a `→ tester verify:` line requiring the tester to read the corresponding code and falsify specific claims. Two of them are bidirectional. |
| **Real secrets copied into new prose from local artifacts** | A public repo publishes live provider URLs, key payloads, or session ids | Steps 4/5/7 carry an explicit "placeholder values only" instruction with a matching planner verify line. `~/.claude/proxy/config.json`, `~/.claude/keys-index.json`, `~/.claude/logs/proxy-trace.jsonl`, and `~/.claude/proxy/proxy-state.json` are **prohibited sources** for any example. The Step 9 script includes a secret-shape scan. See Step 11. |
| A security advisory is dropped while its source bullet is rewritten | Windows users left unaware that keys/trace files are world-readable without manual `icacls` | Step 11 enumerates the advisories that must survive re-authoring and has the **tester** check for their presence — a code-agreement check structurally cannot detect a missing advisory, because the advisory is not in the code. |
| Anchor targets in CLAUDE.md break when a heading is renamed | Silent dead pointers, the exact defect this plan removes | `doc/<page>.html` section `id` attributes are a **global convention** (Guidance for Planner), and the Step 9 script resolves every `doc/*.html#anchor` reference against real files and real `id` attributes, failing loudly on any miss. |
| Gate activates mid-construction | `doc/` writes trigger the hook before all pages exist | The hook is advisory by construction — `PostToolUse` cannot block a write; violations surface as `additionalContext` only. |
| A `.md` file accidentally lands inside `doc/` | Hard gate violation (content-ext rule) | Step 1 verification asserts `doc/` contains only `.html` and `.css`. |
| `doc/` is created but never `git add`ed while README links into it | Published README links dangle — the same defect class this plan removes | Step 11 includes an explicit `git status` check that all 9 `doc/` files are tracked. |

## Proposed Changes

Every step is planner-owned (`doc/**`, `CLAUDE.md`, and `README.md` are all planner-lane). Verification is by the planner, with content-accuracy checks assigned to the tester.

1. **Step 1:** Scaffold `doc/` — create `doc/style.css` (adapted from `../word-grinder/doc/style.css`: re-title the header comment for this project, drop the word-grinder-specific badge classes `.badge-exam`, `.badge-domain`, `.pipeline-step`, `.escalation`, keep reset/layout/headings/code/pre/table and the generic `.note`/`.ok`/`.error`/`.required`/`.optional`/`.badge`/`.overview-grid`) and `doc/content.html` (the TOC landing page linking all **7** content pages, with a `Last updated` line).
   → planner verify (scripted): run `python ~/.claude/scripts/doc_structure_check.py` from the repo root (no `--mode` pin — let the checker auto-detect); it must exit 0 and print `## Doc-Structure: PASS`.
   → planner verify (auto): `doc/` contains no `.md` files; `content.html` has `<link rel="stylesheet" href="style.css">`, a non-empty `<title>`, and a `YYYY-MM-DD` date in visible text; every `<a href>` in it is relative.

2. **Step 2:** Author `doc/architecture.html` — human-readable architecture reference. Sources: CLAUDE.md `## Architecture` bullets (the `**Server**` request-path walkthrough 7,041 chars, drain-and-swap, client-disconnect, give-up body, response size caps), the sink failure policy (4,009 chars), retry/backoff (`PROXY_INITIAL_DELAY * 2**attempt`, 429-uses-`PROXY_MAX_DELAY`, ±25% integer-second jitter, give-up paths), and the `**Heartbeat state is in-memory**` bullet.
   → planner verify (auto): every `<h2>` carries a unique non-empty `id`; no absolute `<a href>`; the page states the retry formula, the 429-vs-503 delay distinction, and give-up behavior for both exhaustion paths.
   → tester verify: read `src/claude_retry_proxy/server.py` retry loop and `forward_request`; confirm the documented backoff formula, the 429/503 delay split, the give-up body-preservation behavior, and the `PROXY_MAX_BODY_SIZE` drain cap match the code. Report any claim the code contradicts.
   → tester verify (**second pass — added 2026-09-12 during Step 9 Phase A**): `doc/architecture.html#size-caps` and `#disconnects` did not exist when the Step 9 disposition was written. Two Gotchas bullets (`**Response size caps**`, `**Streaming disconnect catch is scoped to _DISCONNECT_ERRORS**`) had been assigned to `architecture.html` as their destination, but no section there actually covered them — shrinking on the unverified disposition would have deleted both facts silently. Both sections were authored immediately before the shrink, which is why they carry no tester line from the original audit. Confirm:
       (a) the response cap is enforced at exactly the **7** read loops the page names — 3 buffered in `_forward_core` (2xx `application/json`, 2xx of another content type under a non-anthropic mode, non-2xx) and 4 streaming (silent forward, client-disconnect-aware, two audit paths) — and that each site emits `response_size_cap_exceeded`;
       (b) `PROXY_MAX_BODY_SIZE` yields `413` on the client request path, and caps the give-up drain;
       (c) the disconnect catch tuple is exactly `ConnectionResetError`, `BrokenPipeError`, `ConnectionAbortedError`.
       For `#disconnects`, the residual is an **accepted, review-signed-off** residual, not an open defect — verify the prose describes it accurately and fairly, and report only if it overstates or understates the impact. Do not file it as a new issue.

3. **Step 3:** Author `doc/provider-modes.html` — the three endpoint modes. Sources: CLAUDE.md `**Provider mode dispatch**` (4,283 chars) and `**Malformed tool arguments in chat mode**` (1,280 chars), plus the per-mode auth header, path rewrite, request transform, response transform, and SSE behavior.
   → planner verify (auto): documents all three modes (`anthropic`, `chat`, `response`), the auth-header difference, the path rewrite per mode, the `count_tokens` 400, and the `tool_args_parse_failure` degradation; every `<h2>` has a unique non-empty `id`; no absolute `<a href>`.
   → tester verify: read `server.py` mode-dispatch and transform functions; confirm the documented auth headers, paths, and the malformed-tool-argument placeholder text match the code exactly.

4. **Step 4:** Author `doc/configuration.html` — `config.json` schema (tiers, models, `disable_retry_claude_count_token`, `extra_request_headers`), `keys-index.json` (plain-JSON vs `VimCrypt~03!`, `key` vs `keys`, per-tier key selector, the `"default"` name), the full 11-row environment-variable table, and config-validation rules. Sources: CLAUDE.md `## Environment Variables (server)`, `**Multi-key provider keys**` (1,766), `**Keys file can be plain JSON**` (824), `**Config validation is strict**` (768).
   **All example values use placeholders only** — `https://api.example-provider.invalid`, `sk-EXAMPLE-NOT-A-REAL-KEY`. Never source an example from `~/.claude/proxy/config.json`, `~/.claude/keys-index.json`, or any trace log.
   → planner verify (auto): all **11** environment variables appear with identical names and defaults; the `{header, from, fallback}` spec shape and the `"request_id"` token are documented; every `<h2>` has a unique non-empty `id`; no absolute `<a href>`; no example value matches a real-secret shape.
   → tester verify: read `server.py` env-var reads and config validation; confirm every documented default and every documented validation refusal matches the code.

5. **Step 5:** Author `doc/operations.html` — CLI lifecycle (`start`/`stop`/`status`/`reload`), the passphrase pipe protocol, the two-phase readiness protocol, the admin page and API endpoints with CSRF rules, the drain-and-swap pattern and its 30s timeout, shutdown semantics, and runtime artifact paths. Sources: CLAUDE.md `**CLI start**`, `**Passphrase pipe protocol**`, `**Two-phase readiness protocol**` (645), `**Shutdown does not drain in-flight requests**` (1,222), `**Drain-and-swap timeout during retry sleep**` (578), admin-API bullets.
   **Placeholder values only**, as in Step 4. State that `--passphrase-file` puts the passphrase in the process command line, visible to same-host process listings.
   → planner verify (auto): all four CLI subcommands documented; every admin endpoint path listed; the CSRF accept/reject sets stated; every `<h2>` has a unique non-empty `id`; no absolute `<a href>`.
   → tester verify: read `src/claude_retry_proxy/cli.py` and the admin handlers in `server.py`; confirm the documented subcommands, endpoints, and Origin rules match the code.

6. **Step 6:** Author `doc/compatibility.html` — the per-upstream `context_management` compatibility learner. **Authored from `server.py:846-1290` and `:1659-1681`, `:1788-1840`, not from CLAUDE.md.** CLAUDE.md's prose covers only "detection, stripping, request-count revalidation, and two-success delisting" and omits an entire branch of the machine (suppression), the probation threshold, and the doubling ladder. Page must document, as verified from code:

   *Policy constants* (`server.py:849-855`, maintainer-tunable, no user-facing config surface): `COMPAT_INITIAL_THRESHOLD` 32, `COMPAT_PROBATION_THRESHOLD` 8, `COMPAT_BACKOFF_MULTIPLIER` 2, `COMPAT_MAX_THRESHOLD` 4096, `COMPAT_DELISTING_SUCCESSES` 2, `COMPAT_MAX_RETRIES_PER_REQUEST` 1, `COMPAT_FAILED_CONFIRMATION_SUPPRESSION` 3. Include the startup clamp rules (`_compat_validate_constants`, `:891`): multiplier ≥2, delisting ≥2, initial ≤ max — each warns and clamps on stderr rather than failing.

   *State key and states*: key is `(provider, mode, actual_model, feature)` (`:909`), persisted `\x1f`-joined (`:914`). Exactly **two** states — `unsupported` and `probation` (`:869-870`). "Delisted" is an *event*, not a state: it means the entry is **removed** from `_compat_state`.

   *Transitions*: learn → entry created `unsupported`/threshold 32 (`_compat_learn`, `:1144`). Strip counting (`_compat_record_strip`, `:1178`) — effective threshold is 8 in probation, else the entry's threshold. Probe fired when the threshold is reached and `_compat_retry_lock` is acquired non-blocking; the probe sends the request **un**stripped. Outcome (`_compat_probe_outcome`, `:1438`): 2xx → `_compat_probe_success` (`:1201`) increments `probation_successes`, resets `strip_counter`, delists at ≥2 else sets `probation`; matching 400 → `_compat_probe_rejected` (`:1245`) resets successes, sets `unsupported`, **doubles** the threshold capped at 4096, then returns the stripped retry result; anything else → `_compat_probe_inconclusive` (`:1272`) leaves state and successes unchanged and only zeroes `strip_counter`.

   *Suppression branch* (no CLAUDE.md coverage): 3 failed confirmations (`_compat_record_failed_confirmation`, `:1110`) suppress the learner for that key; a suppressed request is counted and skipped (`_compat_note_suppressed_request`, `:1129`) and after 32 suppressed requests the counter clears, re-entering discovery.

   *Persistence*: `PROXY_FEATURE_COMPAT_FILE` (default `~/.claude/proxy/feature-compatibility.json`), atomic tmp+`os.replace` (`:1043`), schema_version 1, entry validation (`_compat_validate_entry`, `:935`) drops invalid entries with a redacted warning, load failure fails **open** with empty state. Note counters are reset to zero on load — deliberately fail-safe toward over-stripping.

   *The ten `compatibility_*` events* live on this page (Step 7's inventory assigns them here): `compatibility_learned`, `compatibility_field_stripped`, `compatibility_probe_started`, `compatibility_probe_succeeded`, `compatibility_delisted`, `compatibility_probe_rejected`, `compatibility_probe_inconclusive`, `compatibility_rejection_detected`, `compatibility_failed_confirmation_suppressed`, `compatibility_persist_failed`.
   → planner verify (auto): the page states all seven constants with their values; names both states and makes clear delisting is removal, not a third state; documents the suppression branch; every `<h2>` has a unique non-empty `id`; no absolute `<a href>`.
   → tester verify: read the *transition functions* in `server.py` (`_compat_probe_outcome`, `_compat_probe_success`, `_compat_probe_rejected`, `_compat_probe_inconclusive`, `_compat_record_strip`, `_compat_note_suppressed_request`), not just the `COMPAT_*` constants. Confirm the documented thresholds, the doubling ladder and its 4096 cap, the 8-vs-entry-threshold split, the delisting condition, and the 32-request suppression reset match the implementation. Report any mismatch. Also confirm the page does **not** present the entry's `failed_confirmations` field as a live counter — it is permanently 0 (see Issue Log: `compat-entry-failed-confirmations-dead-field`).

7. **Step 7:** Author `doc/trace-log.html` — the JSONL trace entry shape, the 5-day prune, `scripts/analyze_proxy_trace.py`, and the `--all` data-exposure warning including the deliberate non-capture of streamed 2xx bodies and the Windows `icacls` caveat.
   **The field list and event inventory are enumerated from `server.py`/`sinks.py`, not from CLAUDE.md** — CLAUDE.md carries no field list and only ~6 event names, so deriving from it would drop real fields and canonize a phantom one. The `request` entry does **not** carry a `mode` field.
   → planner verify (auto): every `<h2>` has a unique non-empty `id`; no absolute `<a href>`; the `--all` non-capture caveat and the Windows ACL caveat are both stated.
   → tester verify (**bidirectional**): read the trace-emitting code. Confirm (a) every field and event name documented on the page is actually emitted, and (b) **every event name emitted in code appears on some page** — `compatibility_*` events on `compatibility.html`, the rest here. Report any omission in either direction.

8. **Step 8:** Author `doc/test-catalog.html` — the test suite map: file→module mapping, the `tests/_harness.py` isolation mechanism (`PROXY_STATE_FILE`, `PROXY_FEATURE_COMPAT_FILE`, `PROXY_TRACE_FILE` set at module load), the aggregator entry point, and testing patterns. **This page closes a silent no-op**: the planner agent is instructed to read `doc/test-catalog.html` before designing tester guidance, and this repo has no such file, so that instruction currently does nothing.
   **Re-count at authoring time — do not copy a frozen total.** Run `python tests/test_claude_proxy.py` (or re-count `def test_` over `tests/*.py`) and record what it actually reports. Carry the caveat that the count is a snapshot, not a fixed figure. There is no template to copy — `../word-grinder/doc/` has no `test-catalog.html`.

<!-- CORRECTED 2026-09-13: that last sentence is false. `../word-grinder/doc/test-catalog.html`
     exists — tracked since fc77664 (2026-08-14), 871 lines / 71 KB in the working tree, with a
     10-category "Per-Test Descriptions" section. Step 8 shipped a module table only, so the page
     did not serve the planner/tester read instructions it exists for. Step 13 item 4 adds it. -->
   → planner verify (scripted): the page's file list and per-file counts match a live `def test_` count over `tests/*.py` taken at authoring time; every `<h2>` has a unique non-empty `id`; no absolute `<a href>`.
   → tester verify: confirm the documented harness isolation claims are what `tests/_harness.py` actually does, that the documented entry point is correct, and that the page satisfies the planner/tester read instructions (category groupings, coverage descriptions, cross-references) — the read instructions, not just the file list.

9. **Step 9 — PHASE A (stage every edit in the same session):** Produce the complete shrink diff for user approval. Write a temp copy, generate the full before/after for `CLAUDE.md` using the disposition table below, and present it.
   **⛔ CHECKPOINT — do not write `CLAUDE.md` until the user explicitly approves the diff.** Per the user's global CLAUDE.md rule, redundant or outdated content must be flagged and explicitly approved before removal.

10. **Step 9 — PHASE B (after explicit approval):** Write the shrunk `CLAUDE.md` to ~21,000 chars via the approved diff. Every removal is replaced by a one-to-two-line summary plus a pointer to the owning page with a fragment anchor. Write **atomically** (temp file + `os.replace`).
    → planner verify (auto): the file contains no `server.py:<line>` citation; no section was deleted without a row in the disposition table; each moved topic has a `doc/<page>.html#<anchor>` pointer; the `## Unresolved Deferred Issues` JSON block still parses and lists the same 7 `issue_id` values.
    → planner verify (scripted): `./tmp/verification/2026-09-12-build-doc-tree-step9.py` — resolves every `doc/*.html#anchor` reference in `CLAUDE.md` and `README.md` against real files and real `id` attributes; scans new prose for secret shapes; exits non-zero listing every failure. It must **fail loudly if an expected marker/heading is not found** rather than silently no-op'ing (the file uses CRLF-capable line endings on this Windows box).
    → tester verify: spot-read pointers and confirm each lands on prose that actually covers the summarized claim (an anchor can resolve yet point at the wrong section). Cover at least one pointer per destination page, not 5 arbitrary ones.

11. **Step 11:** Final gate and reconciliation.
    → planner verify (scripted): `python ~/.claude/scripts/doc_structure_check.py` from the repo root exits 0 with `## Doc-Structure: PASS` reporting **`- 9 files checked`** (7 content pages + `content.html` + `style.css`). *(Verified against the checker source: it prints `len(files)` over `doc/` recursively.)*
    → planner verify (auto): (a) every page in `content.html`'s TOC exists on disk and every page on disk appears in the TOC; (b) `git status` shows all 9 `doc/` files tracked; (c) the security advisories from the disposition table are present on their owning pages — keys-file encryption recommendation + Windows `icacls` ACL restriction (`configuration.html`), `--all` plaintext-prompt exposure + non-capture of streamed 2xx bodies + Windows chmod/ACL caveat (`trace-log.html`), admin-API localhost-only + Origin/CSRF requirement (`operations.html`).
    → tester verify: confirm the advisories are substantively intact, not merely present as strings.

<!-- UPDATED: added 2026-09-12 by /update-plan after the first tester pass returned FAILURE with six content-accuracy findings. -->

12. **Step 12:** Content-accuracy correction pass — fix the six documentation-vs-code discrepancies found by the tester's first pass. All planner-lane; **no source, test, or config change** (the one code defect found is deferred, see the Issue Log).
    1. `doc/architecture.html#request-path` — delete the sentence "It never raises." from Step 1. Per user decision 2026-09-12: the page keeps its enumeration of the three handled cases, which is true now and remains true after the deferred fix lands, so this creates no follow-up doc edit. Deliberately *not* describing the defect inline, because a defect description would become false the moment the fix lands.
    2. `doc/architecture.html#disconnects` — the residual's parenthetical says "per-key probe lock"; the lock is a single process-wide `threading.Lock` (`server.py:888`). Reword to the global throttle.
    3. `doc/provider-modes.html` — an invalid provider `mode` is described as rejected at startup. `_validate_vendors` (`server.py:692-701`) prints a WARNING and returns the table unchanged; enforcement is the request-time 500 `invalid_provider_mode` (`server.py:1587-1596`). Reword to "warned about at startup (the proxy still starts), rejected at request time".
    4. `doc/provider-modes.html#compat-retry` — "a lock that allows at most one probe per key at a time" → one probe at a time across the whole proxy.
    5. `doc/provider-modes.html#compat-retry` — the stripped variant is described as derived from the already-transformed body with no re-transform. `_compat_stripped_body` (`server.py:1425-1435`, docstring "the stripped client body") is called with the **client** body at `:1761` and `:1813`, and the result re-enters `_forward_request_impl`, which runs the transform pipeline again (`:1692-1701`). Reword to "derived from the original client body with the feature field removed, re-sent through the normal forward path — one upstream attempt, but a fresh transform pass".
    6. `doc/configuration.html#validation` — drop the "A vendor's mode is not one of the three valid values" row from the refuses-to-start table (see item 3).
    7. `doc/configuration.html#env-vars` — the table's closing sentence claims an out-of-range value is "clamped" and "reported on stderr". `_env_int` (`server.py:42-54`) returns the variable's **default** and prints nothing; measured: `PROXY_MAX_RETRIES=999` → 10 (not 100), `PROXY_PORT=80` → 8080 (not 1024), `PROXY_MAX_DELAY=abc` → 30, stderr bytes 0. Replace with the silent-default wording. (The warn-and-clamp mechanism that this sentence conflated with is `_compat_validate_constants`, `server.py:891-906`, which governs the `COMPAT_*` constants and is documented correctly on the compatibility page.)
    8. `doc/compatibility.html#probe` — "Only one probe per key may be in flight" → one probe in flight proxy-wide.
    9. `doc/trace-log.html#entry-schema` — the table's "every field below is present on every `request` entry unless noted" invariant is violated by the oversized-body early return (`server.py:4349-4362`), whose entry omits `tier` and `provider`; and `provider` is `null` on the pre-routing 400 paths. Add both exception notes.
    10. `CLAUDE.md` — drop `mode` from the Architecture step-8 trace list (the `request` entry has no `mode` key: zero `trace_entry["mode"]` assignments in `server.py`; the plan's own mega-audit found this and Step 7 fixed only the page), and reword the step-5 stripped-variant claim per item 5.
    → planner verify (auto): every one of the ten edits is applied; `doc/architecture.html` no longer contains "never raises"; the strings "per key" and "per-key" no longer appear in any probe-lock sentence on the three affected pages; `CLAUDE.md` no longer lists `mode` among the trace-entry fields.
    → planner verify (scripted): re-run `python ~/.claude/scripts/doc_structure_check.py` (must exit 0 with `- 9 files checked`) and `./tmp/verification/2026-09-12-build-doc-tree-step9.py` (anchors still resolve, no secret shapes).
    → tester verify (**second pass — this is the re-run that closes the FAILURE verdict**): re-read the six corrected claims against `server.py` and confirm each now matches the code. Specifically: `extract_model`'s documented contract no longer asserts totality; the three probe-lock sentences describe a process-wide throttle; the mode claim distinguishes the startup warning from the request-time 500; the env-var sentence says silently-ignored-and-defaulted; the compat stripped variant is described as coming from the client body with a re-run transform; and `trace-log.html` notes the reduced 413 entry. Report any remaining mismatch, and confirm no *new* discrepancy was introduced by the corrections.

<!-- UPDATED: added 2026-09-13 by /update-plan from the Phase 6 review. -->

13. **Step 13:** Review correction pass — fix the Phase 6 reviewer's findings. All planner-lane; still **no source, test, or config change**.
    **Must fix (factual, code-contradicted):**
    1. `doc/architecture.html:106-107` — **the Critical.** The "Request bodies are transformed once" note says the compatibility retry "derives a stripped variant from the already-transformed body". `_compat_stripped_body` (`server.py:1425-1435`) takes the **client** body (`:1759-1761`, `:1813`) and its result re-enters `_forward_request_impl` (`:1457`, `:1816`), re-running the transform (`:1692-1701`). Step 12 item 5 fixed this on `provider-modes.html` and in `CLAUDE.md` but missed this third instance — so the page now contradicts both the file that links to it and the page it links to. Reword to match.
    2. `doc/provider-modes.html:213` — "a non-2xx response passes through byte-for-byte untransformed in every mode" is false for anthropic mode: `server.py:2061-2064` applies `_rewrite_json_response` to any non-2xx JSON body, and that helper (`:2250-2274`) replaces a top-level string `model` and re-serialises. Chat/response modes and the give-up path genuinely are untouched. Scope the sentence.
    3. `doc/operations.html:166` — the CSRF warning says "the CLI's own reload path do[es] not add [an Origin] by default". `cli.py:689` and `:802` both send `Origin: http://127.0.0.1:<port>`. Drop the CLI from the clause; keep `curl`.
    **Should fix (convention, maintainability):**
    4. `doc/test-catalog.html` — add the per-test inventory the page exists to provide (`planner.md:155`, `tester.md:67` both instruct a read for duplicate-avoidance, which a module table cannot serve). **Step 8's premise was false:** `../word-grinder/doc/test-catalog.html` exists, tracked since `fc77664` (2026-08-14), 859 lines at HEAD, with a 10-category "Per-Test Descriptions" section listing test names with one-line descriptions — regenerated, not hand-maintained, which is what keeps it from rotting. Match that shape, not an exhaustive hand-written list.

<!-- APPLIED 2026-09-13: 293 entries in 10 categories, built from each test's own docstring by
     tmp/verification/2026-09-13-gen-test-catalog.py (one-off, gitignored).

     **Second correction to this item:** "regenerated, not hand-maintained" is not what the
     sibling does. It has no generator — nothing under `scripts/`, no user-level command, and its
     page is reconciled by hand in the same commit as the feature work (1500d17: "reconcile
     CLAUDE.md and test catalog"). Ours states that rule on the page rather than implying a tool.

     Residual gap, not fixed here: nothing verifies the inventory against `tests/`, so it can
     drift the way the module counts can. A suite-level check would be a test change, outside this
     plan's scope. -->
    5. Duplication ownership — four facts are stated in full on two pages each with no owner: trace pruning (`operations.html:229` / `trace-log.html:169`), heartbeat state (`architecture.html:357` / `operations.html:218`), shutdown semantics (`architecture.html:450` / `operations.html:171`), sink failure (`architecture.html#sinks` / `trace-log.html:203`). Give each one owner and reduce the other site to a summary plus an anchor, the pattern `architecture.html#sinks` already models.
    6. `CLAUDE.md:137` — "it rides on the separate `mode_dispatch` event" needs the qualifier: `server.py:1598` emits it only when `mode != "anthropic"`, so grepping for it after an ordinary request finds nothing. Both owning pages state this correctly.
    7. `doc/configuration.html:103` / `operations.html#admin` — a hot switch preserves the models catalog, `disable_retry_claude_count_token`, **and** `extra_request_headers` (`server.py:4230-4240`). The rewrite kept only the flag; the pre-shrink CLAUDE.md stated both. An operator can no longer tell whether switching tiers discards their header rules.
    8. `doc/content.html:28` — the hand-counted "11 server env vars" card is rot-prone (the count moved twice in the fortnight before this plan) and nothing verifies it. Annotate it the way `test-catalog.html` annotates its test count, or drop it.
    9. `doc/trace-log.html:17` — "every request appends one `request` entry" has two further exceptions beyond shutdown: an unparsable `Content-Length` returns before any `log_trace` (`server.py:4338-4341`), and admin POSTs return without one (`:4076-4315`). Qualify to "every request the proxy forwards" or extend the exception list.
    10. `doc/style.css` — 36 selector lines define classes no page uses (`.ok`, `.code-block` and children, `.rule-box` and children, `.badge-ok/.badge-bad`, `.tag*`, `.flow-arrow`, `.field-grid`, `.two-col`, `.file-ref`, `.desc`, `.section`, `.note-callout`, `.ref-link`), and the header comment claims the sibling's "step cards" and "LLM rule boxes" were removed when `.step-box` is used by 12 elements and `.rule-box` is still defined. Delete the dead rules and correct the comment.
    **Left Open (recorded, not fixed here):**
    - `review-anchor-resolver-not-committed` — nothing committed re-checks the 30 `doc/*.html#anchor` references cited from `CLAUDE.md`; the plan's resolver is one-shot and lives under gitignored `tmp/`. Committing it (or wiring it into the suite) is a tooling change beyond this plan's doc-only scope.
    - `review-content-readme-link-raw-markdown` — `doc/content.html` links to `../README.md`, which opens as raw Markdown from a browser; the sibling convention links `.html` only. The fix (point at the rendered repo page) needs a decision about what URL to use, which the doc-structure gate's relative-href rule constrains.
    → planner verify (scripted): `doc_structure_check.py` exits 0 with `- 9 files checked`; the anchor resolver exits 0; `grep -rn 'already-transformed' doc/ CLAUDE.md README.md` returns nothing.
    → tester verify (**third pass**): re-read each corrected claim against `server.py`/`cli.py`, and — this is the part both prior passes missed — **search for further instances of every claim being corrected**, rather than verifying only the sites named here. Report any surviving instance on any other page.

<!-- UPDATED: 2026-09-13 by /update-plan from the tester's third pass. -->

**Third-pass result (2026-09-13).** The tester verified **items 1–5** — the five findings that had
their own report files — and each is now `Resolved`, with its evidence recorded in that file rather
than here. The pass also did exactly what the verify line above asked and swept for further
instances of each corrected claim: it found **two survivors** of the byte-for-byte error-path claim
that Steps 12 and 13 had both missed (`doc/architecture.html#retry`, `README.md`). Those were fixed
the same day at the user's direction — Step 14 below — and the sweep was re-run afterwards to
confirm the two unqualified instances are gone.

<!-- CORRECTED 2026-09-13 by /update-plan. The paragraph that stood here asserted that no report
     mentioned items 6–10's claim families. That assertion was false, and the correction is
     recorded rather than quietly deleted — it is the same failure mode the plan keeps surfacing:
     a claim written from a partial probe and stated as a generalisation. -->

**Items 6–10: mis-recorded, then verified.** The paragraph that stood here said no report mentioned
the `mode_dispatch` qualifier, the switch-preservation set, the trace-log forwarding claim, the
env-var card, or the dead CSS rules. It was written from a probe of the five *finding* reports, and
as a generalisation it was wrong: the third pass's session report
([tester-2026-09-13.json](./tmp/reports/2026-09-12-build-doc-tree-tester-2026-09-13.json)) does
mention all five families — but only in the running prose of its verdict, with no per-item
verification attributed to any of them, so the `/update-plan` mechanism, which looks for a report
that confirms a *named* issue, could not consume it. The gap was therefore one of **report
attribution, not of verification**. The focused pass
([tester-2026-09-13-2.json](./tmp/reports/2026-09-12-build-doc-tree-tester-2026-09-13-2.json))
closed it: each of the five issues now carries a named entry recording the claim, the exact code
read, and the result, and all five PASS with no defect found — `server.py:1598-1607` (the
`mode != "anthropic"` guard), `:4231-4240` (the preserved key tuple), `:4337-4341` plus the three
admin handlers (the missing trace entries), the `PROXY_*` count agreeing at 11 across four sources,
and the stylesheet measuring 22 defined / 22 used / none dead. All five rows are `Resolved`.

14. **Step 14:** Third-pass sweep follow-up — the two surviving instances of the corrected byte-for-byte claim, fixed 2026-09-13 at the user's direction, after Step 13 had closed. `doc/architecture.html#retry` claimed the error path was returned "untransformed"; it now states the retry fact and defers the rewrite semantics to the owning page (`Whether its body is rewritten on the way out is mode-dependent — see provider-modes.html`). `README.md:350-351` scoped its "pass through untransformed" sentence to chat and response modes, which is what `server.py:2061` implements. Both edits are recorded in full in the finding's report.
    → planner verify (scripted, run 2026-09-13): the claim-family sweep `grep -rn 'untransformed\|byte-for-byte\|untranslated' doc/ CLAUDE.md README.md` returns four hits, each correct in context — `provider-modes.html:214` (already scoped by Step 13 item 2), `provider-modes.html:392` (the give-up path, genuinely untouched), `test-catalog.html:235` (a chat-mode test description), and the corrected `README.md:351`.
    → tester verify (done, in the same pass): the post-fix sweep re-run, recorded in the `error-responses-byte-for-byte-overclaim` report.
    → focused verification pass (done 2026-09-13): `tester-2026-09-13-2.json` — the per-item pass over Step 13 items 6–10 that this step called for. All five PASS, each with its code read recorded. This also corrected a false premise this step carried about what the third pass had covered.

### CLAUDE.md per-section disposition

Target: 46,318 → ~21,000 characters.

| Section | Now | Disposition | Target |
|---|---:|---|---:|
| Purpose | 777 | Keep | 777 |
| Structure | 2,706 | Keep; add `doc/` rows | ~2,900 |
| Build / Test / Run | 1,600 | Keep | 1,600 |
| Architecture | 12,742 | Reduce to summary + anchored pointers → `architecture.html`, `provider-modes.html`, `operations.html` | ~3,500 |
| Environment Variables | 1,935 | Keep as quick-reference table (`configuration.html` is authoritative) | 1,935 |
| Gotchas | 18,718 | **Split** — 15,893 move out, 2,792 stay (below) | ~5,000 |
| Refactoring | 495 | Keep (dead link recorded as a deferred issue, not fixed) | 495 |
| Documentation | 3,717 | Replace with `doc/` index + `plans/` + `scripts/` pointers | ~1,500 |
| Unresolved Deferred Issues | 2,324 | **Unchanged** — schema-required fields, single-writer block | 2,324 |
| Future Work — TODO | 1,178 | Trim the plan-history narration | ~400 |
| | | **Total** | **~21,200** |

**Gotchas split — all 15 bullets that move** (the section has 21 bullets; these 15 plus the 6 below account for every one):

| Bullet | Chars | Destination |
|---|---:|---|
| `**Provider mode dispatch**` | 4,283 | `provider-modes.html` |
| `**Multi-key provider keys**` | 1,766 | `configuration.html` |
| `**Trace/state I/O failures degrade the proxy**` | 1,377 | `architecture.html` (dedupe — already stated in Architecture) |
| `**Malformed tool arguments in chat mode**` | 1,280 | `provider-modes.html` |
| `**Shutdown does not drain in-flight requests**` | 1,222 | `operations.html` (keep ~3-line summary + pointer) |
| `**Streaming disconnect catch is scoped to _DISCONNECT_ERRORS**` | 844 | `architecture.html` |
| `**Keys file can be plain JSON**` | 824 | `configuration.html` |
| `**Config validation is strict**` | 768 | `configuration.html` |
| `**Two-phase readiness protocol**` | 645 | `operations.html` |
| `**disable_retry_claude_count_token**` | 585 | `configuration.html` |
| `**Drain-and-swap timeout during retry sleep**` | 578 | `operations.html` |
| `**Response size caps**` | 466 | `architecture.html` |
| `**Integer-second jitter is degenerate**` | 448 | `architecture.html` |
| `**Give-up error body preservation**` | 435 | `architecture.html` |
| `**Heartbeat state is in-memory**` | 372 | `architecture.html` |
| | **15,893** | |

**Gotchas split — the 6 that stay in CLAUDE.md** (operational, bite-you-now; 2,792 chars): `**~/.claude/settings.json` is static** (189), **`--all` / `PROXY_LOG_ALL` data exposure** (771), **Admin API CSRF protection** (294), **`PROXY_IDLE_TIMEOUT` is a dead env var** (133), **worst-case retry hold** (367), **test-suite state isolation** (1,038, trimmed — drop the self-defeating count narrative, keep the isolation fact).

**Resolved by this plan:**

- All `server.py:<line>` citations removed (all three imprecise; one out of range).
- The sinks failure policy stops being stated twice.
- `doc/test-catalog.html` starts existing, so the planner's read instruction stops silently no-opping.
- 15,893 chars of rot-prone derived description leave the always-injected file.

**Deliberately NOT resolved** (recorded, not silently skipped):

- The `## Unresolved Deferred Issues` gitignored-path issue — cannot be fixed without changing user-global tooling. No longer claimed as a deliverable.
- `CLAUDE.md:529`'s dead link to `.claude/cluster-extraction-criteria.md` — user directed it stays. Filed as `extraction-criteria-link-dead-in-public`.

**Known follow-ups this plan creates (not fixed here):**

- `src/claude_retry_proxy/server.py:1751` carries an in-code comment "Documented in CLAUDE.md Gotchas" for the `_DISCONNECT_ERRORS` residual. After Step 9 that referent moves to `doc/architecture.html`; the comment is not updated (source changes are out of scope).
- `README.md`'s env-var table has 10 rows vs CLAUDE.md's 11 (omits `PROXY_FEATURE_COMPAT_FILE`). Step 10 adds links only, so the divergence persists.
- `pyproject.toml` sets `readme = "README.md"` and `doc/` is not shipped as package data, so Step 10's new README→doc links will be dead on PyPI's rendered long-description.

## Guidance for Planner

All steps are executed by the planner. No doc work is delegated to the coder.

<!-- UPDATED: added 2026-09-12 by /update-plan. This is the root-cause fix for the first tester pass's FAILURE. -->
- **Source discipline — the rule this revision exists to add.** Every factual claim in a
  re-authored page must be **re-derived from the code**. CLAUDE.md prose may supply the *list of
  topics* to cover; it may never supply a *fact* to assert. The original plan applied this
  discipline only to Steps 6 and 7 — the two steps the mega-audit happened to scrutinize — and let
  Steps 2–5 source prose straight from CLAUDE.md. Four of the six findings in the first tester pass
  came through that gap. Two of them (`invalid-mode-described-as-startup-rejection`,
  `env-range-described-as-clamp`) were claims CLAUDE.md never made in the first place: they were
  invented during re-authoring, which is worse than inheriting an error. Apply this rule to **every**
  page, including pages an audit has not flagged, and treat "the old doc said so" as a reason to
  check the code, not a reason to skip checking it.

- **Doc files to create:** `doc/content.html`, `doc/style.css`, `doc/architecture.html`, `doc/provider-modes.html`, `doc/configuration.html`, `doc/operations.html`, `doc/compatibility.html`, `doc/trace-log.html`, `doc/test-catalog.html` (**9 files**).
- **Doc files to update:** `CLAUDE.md` (Step 9), `README.md` (Step 10).
- **Global doc convention:** every `<h2>` in every `doc/*.html` page carries a unique non-empty `id`. This is a precondition for Step 9's anchor pointers and must be applied as each page is authored, not retrofitted.
- **When:** Steps 1–8 in order; Steps 9–10 after 2–8 complete (pointers must land on existing pages); Step 11 last.
- **Restore point:** commit or tag the pre-shrink state before Step 9.
- **Verification script to write:** `./tmp/verification/2026-09-12-build-doc-tree-step9.py` — anchor resolution + secret-shape scan. Do **not** re-implement the doc-structure rules; `~/.claude/scripts/doc_structure_check.py` is the sanctioned mechanism for those, and re-implementing them violates the global Verification and Audits rule. This script is new capability (anchor resolution and secret scanning are not among the checker's 10 rules), not a duplicate.
- **Approval gate:** Step 9 Phase A produces a diff; Phase B is not executed without explicit user approval.

## History

| Date | Event | Conclusion | Dismissed |
|------|-------|------------|-----------|
| 2026-09-12 | Initial plan | Adopts the `../word-grinder` doc convention (HTML + `style.css` + `content.html`, gated by `doc_structure_check.py`); moves derived architecture/transform reference out of CLAUDE.md into 8 HTML pages, cutting it 46,318 → ~21,000. | — |
| 2026-09-12 | Mega-audit (pre-implementation) | 11/11 lenses, 56 findings, **0 High** / 24 Medium / 32 Low. 15 distinct Mediums addressed: page-count arithmetic corrected (7 content pages / 9 files); Step 4 env-var count 9→11; two unassigned Gotchas bullets assigned; 4 phantom Issue Log report links resolved; **the deferred-issues restructure withdrawn** (schema + single-writer conflict); Step 9 approval checkpoint added; rollback + atomic write added; Step 8 de-frozen to a live count; `<h2 id>` hoisted to a global convention; Step 7 field/event inventory re-sourced from code and made bidirectional; placeholder-only security control + advisory-survival check added. | [review-dir-as-file](~/.claude/scripts/doc_structure_check.py), [review-rel-media-case](~/.claude/scripts/doc_structure_check.py), [review-claude-sentence-final](~/.claude/scripts/doc_structure_check.py) — all pre-existing checker hardening, noted as historical context only; 32 Low findings acknowledged, none actioned. |
| 2026-09-12 | Compatibility code read (user-requested) | Step 6 re-sourced from `server.py:846-1290` after the user asked for the compatibility code to be checked — the page's original source line ("the state-machine detail currently implied across the Gotchas") was papering over a real gap and the mega-audit had flagged the transition logic as unverified. Found CLAUDE.md's prose omits an entire machine branch (**suppression**: 3 failed confirmations suppress a key, cleared after 32 suppressed requests) plus the probation threshold of 8 and the 32→4096 doubling ladder. Also confirmed exactly 10 `compatibility_*` events and 30 distinct event names repo-wide. Filed `compat-entry-failed-confirmations-dead-field` (a persisted entry field that is never incremented). | — |
| 2026-09-12 | Step 9 Phase A — diff staged and approved | Shrink executed: `CLAUDE.md` **46,318 → 22,930 chars** (−50.5%), 187 insertions / 477 deletions. Deferred-issues block verified byte-identical (7 `issue_id`s), zero `server.py:<line>` citations remain. **Two missing destinations found before the shrink ran:** the disposition assigned `**Response size caps**` and `**Streaming disconnect catch is scoped to _DISCONNECT_ERRORS**` to `architecture.html`, but no section there covered either — the `_DISCONNECT_ERRORS` string appeared in no doc page at all. Authored `doc/architecture.html#size-caps` and `#disconnects` first, then shrank; both carry a second-pass tester line. Deviations from the projection, both deliberate: `## Structure` trimmed −950 (the 13-file `tests/` listing replaced by a pointer to `doc/test-catalog.html#catalog`, which carries it with live counts), and the final size landed at 22,930 vs the ~21,200 projection, the overage concentrated in `## Architecture` (6,202 vs 3,500 projected) where all eight request-path steps were kept for operational value. | — |
| 2026-09-12 | Spec revision (/update-plan) | Tester's first pass returned FAILURE with six content-accuracy findings — the suite itself passed 293/293, so the failure was against this plan's own content-accuracy criteria. Added Step 12 (10 doc corrections across 6 files), a universal source-discipline rule to Guidance for Planner, and a second-pass tester line. Root cause: "derive from code, not from CLAUDE.md" was applied to Steps 6–7 only; four of six findings came through that gap, and two of them were claims CLAUDE.md never made at all. The `extract_model` code defect is deferred by user decision (this plan changes no code); its page wording is corrected by deleting the overclaim rather than describing the defect. Three earlier Fix Planned issues moved to Resolved. | [extract-model-raises-on-non-object-json](./tmp/reports/defer-issue-extract-model-raises-on-non-object-json.json) |
| 2026-09-13 | Spec revision (/update-plan) — Phase 6 review | Reviewer returned **"Issues found — must fix before commit"**: 1 Critical / 4 Warning / 7 Suggestion, 14 dismissed, 3 hunches. The Critical is the *third* instance of the compat stripped-variant claim Step 12 corrected on two other surfaces, leaving `architecture.html` and `provider-modes.html` contradicting each other; both tester passes verified the fix list they were handed rather than searching for further instances of the same claim. Corrected a false plan premise too: `../word-grinder/doc/test-catalog.html` has existed since 2026-08-14, so Step 8's "there is no template to copy" was wrong. Added Step 13 (10 corrections; 2 items left Open), reopened the plan. Security, performance and register dimensions passed clean. | [review report](./tmp/reports/2026-09-12-build-doc-tree-review-2026-09-12.json) |
| 2026-09-13 | Spec revision (/update-plan) — tester's third pass | Five review findings verified and moved to Resolved. The same pass's cross-page sweep found two survivors of the byte-for-byte claim that Steps 12–13 missed, fixed the same day as Step 14. Step 13 items 6–10 were covered by no report and stay Fix Planned. | [byte-for-byte report](./tmp/reports/2026-09-12-build-doc-tree-error-responses-byte-for-byte-overclaim.json) |
| 2026-09-13 | Spec revision (/update-plan) — focused verification pass | Step 13 items 6–10 verified per-item and moved to Resolved, emptying the `Fix Planned` column: the mode_dispatch guard, the hot-switch preservation tuple, the two missing trace entries, the env-var count, and the stylesheet measurement, each against the code. Corrected this plan's own false premise that no report mentioned those claim families — the third pass did mention them, in unattributed verdict prose, so the gap was bookkeeping rather than verification. | [focused pass](./tmp/reports/2026-09-12-build-doc-tree-tester-2026-09-13-2.json) |

## Plan Metadata

```json
{
  "plan_id": "2026-09-12-build-doc-tree",
  "steps": [
    "Step 1: Scaffold doc/",
    "Step 2: Author doc/architecture.html",
    "Step 3: Author doc/provider-modes.html",
    "Step 4: Author doc/configuration.html",
    "Step 5: Author doc/operations.html",
    "Step 6: Author doc/compatibility.html",
    "Step 7: Author doc/trace-log.html",
    "Step 8: Author doc/test-catalog.html",
    "Step 9: Shrink CLAUDE.md",
    "Step 10: Update README.md",
    "Step 11: Final gate and reconciliation",
    "Step 12: Content-accuracy correction pass",
    "Step 13: Review correction pass",
    "Step 14: Third-pass sweep follow-up"
  ],
  "coder_files": [],
  "tester_files": [],
  "doc_files": [
    "doc/content.html",
    "doc/style.css",
    "doc/architecture.html",
    "doc/provider-modes.html",
    "doc/configuration.html",
    "doc/operations.html",
    "doc/compatibility.html",
    "doc/trace-log.html",
    "doc/test-catalog.html",
    "CLAUDE.md",
    "README.md"
  ],
  "verification_scripts": ["./tmp/verification/2026-09-12-build-doc-tree-step9.py", "./tmp/verification/2026-09-13-gen-test-catalog.py"],
  "repo_mode": "Public",
  "document_overrides": ["~/.claude/CLAUDE.md — CLAUDE.md Maintenance: keep CLAUDE.md compact, but never silently delete (Reason: deletions are enumerated per-bullet in the disposition table, and Step 9 executes in two phases with an explicit user-approval checkpoint between them)"]
}
```

## Audit Accumulation

| Counter | Value | Last Updated |
|---------|-------|--------------|
| issues_resolved_since_audit | 0 | 2026-09-12 |
| steps_changed_since_audit | 0 | 2026-09-12 |
| files_changed_since_audit | 0 | 2026-09-12 |

*Counters reset by the mega-audit run of 2026-09-12.*

## Documentation

- `doc/content.html` — root landing page / table of contents for all documentation.
- `doc/architecture.html` — architecture reference: request path, retry/backoff, sink failure policy, drain-and-swap, heartbeat. Keep in sync with code changes.
- `doc/provider-modes.html` — anthropic / chat / response mode dispatch, request and response transforms, SSE synthesis, tool-call handling. Keep in sync with code changes.
- `doc/configuration.html` — `config.json` and `keys-index.json` schemas, multi-key selection, `extra_request_headers`, environment variables, validation rules, keys-file security advisory. Keep in sync with code changes.
- `doc/operations.html` — CLI lifecycle, passphrase protocol, readiness, admin page and API, runtime artifacts. Keep in sync with code changes.
- `doc/compatibility.html` — the `context_management` compatibility learner state machine and its `compatibility_*` trace events. Keep in sync with code changes.
- `doc/trace-log.html` — trace entry schema, event names, prune policy, analysis tool, data exposure. Keep in sync with code changes.
- `doc/test-catalog.html` — test suite map and harness isolation. Keep in sync with test file reorganization.
- `doc/style.css` — shared stylesheet for all `doc/` pages.
- `plans/` — completed implementation plans (20 files). One per feature, with design rationale, issue log, and test results.

## Final Results

**Completion date:** 2026-09-13
**Status:** COMPLETED — 18 of 23 Issue Log rows `Resolved`, the `Fix Planned` column empty, and the 5 remaining rows all dispositioned (2 deferred at commit time, 3 carried deferred issues).

<!-- UPDATED: 2026-09-13 (completion). This status was written as COMPLETED once before, on
     2026-09-12, and it was premature: it was set before the Phase 6 reviewer ran, and the reviewer
     then returned a Critical on a page two tester passes had already cleared. The plan was
     reopened, Steps 13 and 14 ran, and three verification passes closed every finding. The
     narrative below is kept in full — a status that had to be earned rather than assumed is this
     plan's most transferable output. -->

> **Reopen history (2026-09-13), kept because it is the plan's most useful record.** The review returned **1 Critical / 4 Warning / 7 Suggestion**
> ([review report](./tmp/reports/2026-09-12-build-doc-tree-review-2026-09-12.json)). The Critical
> is the *third* instance of a claim Step 12 corrected on two other surfaces — `architecture.html`
> and `provider-modes.html` now contradict each other, and `architecture.html` links to the page
> that contradicts it. Both tester passes verified the fix list they were handed rather than
> searching for further instances of the same claim; the reviewer found the one nobody had been
> pointed at. The results below stand as the round-2 state; Step 13 supersedes them.

### What landed

A `doc/` tree of 9 files (7 content pages + `content.html` + `style.css`, 122 KB) plus a `CLAUDE.md` rewritten against it and a `README.md` that links into it.

| Artifact | Before | After |
|---|---:|---:|
| `CLAUDE.md` | 46,318 chars | **23,128** (−50.1%) |
| `README.md` | 23,488 bytes | ~24,600 (gained a `Going deeper` index + 2 inline pointers) |
| `doc/` | — | 9 files, 122 KB |

### Files changed

`CLAUDE.md`, `README.md`, 9 new files under `doc/`, and the archived plan + content index under `plans/` — **13 files, +3,542 / −479 lines**. **No source, test, or configuration file was modified**, verified by `git diff --cached --name-only` filtered to `src/ tests/ scripts/ pyproject.toml` (empty).

### Test results

| Round | Report | Result |
|---|---|---|
| 1 | [tester-2026-09-12](./tmp/reports/2026-09-12-build-doc-tree-tester-2026-09-12.json) | 293/293 passed, exit 0 — **verdict FAILURE** (content-accuracy criteria unmet, 6 findings) |
| 2 | [tester-2026-09-12-2](./tmp/reports/2026-09-12-build-doc-tree-tester-2026-09-12-2.json) | 293/293 passed, exit 0 — **verdict SUCCESS** (all 6 corrected and re-verified) |
| 3 | [tester-2026-09-13](./tmp/reports/2026-09-12-build-doc-tree-tester-2026-09-13.json) | 293/293 passed, exit 0 — **verdict SUCCESS** (Step 13 items 1–5 re-read against code; the cross-page sweep found **2 surviving instances** of a corrected claim, fixed as Step 14) |
| 4 | [tester-2026-09-13-2](./tmp/reports/2026-09-12-build-doc-tree-tester-2026-09-13-2.json) | 293/293 passed, exit 0 — **verdict SUCCESS** (focused pass: Step 13 items 6–10 each verified per-item against code, all PASS) |

Scripted gates at close: `doc_structure_check.py` exits 0 with `## Doc-Structure: PASS` / `- 9 files checked`; the plan's anchor+secret script exits 0 with 228 references resolved and no secret shapes. TOC symmetric with disk (7 ↔ 7). All 9 `doc/` files tracked. The suite result never moved across the four rounds — 293/293 every time — because nothing under `src/` or `tests/` was ever touched.

### Issues resolved

Eighteen of twenty-three Issue Log rows are `Resolved`, the `Fix Planned` column is empty, and every one of those was closed by a tester pass that read the code rather than the plan's description of the fix. The five that remain `Open` are deferred work, not failures of this plan — each carries a `defer-issue-*.json` report and is indexed in CLAUDE.md's unresolved-issue block:

- [review-anchor-resolver-not-committed](./tmp/reports/defer-issue-review-anchor-resolver-not-committed.json) — nothing committed re-checks the anchors CLAUDE.md cites into `doc/`; the resolver is a one-off under gitignored `tmp/`. Deferred at commit time.
- [review-content-readme-link-raw-markdown](./tmp/reports/defer-issue-review-content-readme-link-raw-markdown.json) — `content.html` links `../README.md`, which opens as raw Markdown in a browser; the fix needs a URL decision the gate's relative-href rule constrains. Deferred at commit time.
- [extract-model-raises-on-non-object-json](./tmp/reports/defer-issue-extract-model-raises-on-non-object-json.json) — a **live, user-visible code bug** confirmed still present on the final tree: `extract_model` raises `AttributeError` on any valid JSON body that is not an object, and the unguarded call at `do_POST` pre-empts the whole downstream guard chain, so the client gets no HTTP response at all. Deferred by user decision because this plan changes no code. Its page overclaim was removed.
- [compat-entry-failed-confirmations-dead-field](./tmp/reports/defer-issue-compat-entry-failed-confirmations-dead-field.json) — pre-existing, documented on `compatibility.html`.
- [extraction-criteria-link-dead-in-public](./tmp/reports/defer-issue-extraction-criteria-link-dead-in-public.json) — the deliberate non-fix the user directed.

### The round-1 failure, and why it is the plan's most useful output

The first tester pass returned FAILURE against a **green test suite and green scripted gates**. Anchors resolved, no secrets, TOC complete, files tracked, 293/293 passing — while five pages asserted behaviour the code does not have. Four of the six findings were prose authored during Steps 2–4 that had never been checked against code; two of those were claims `CLAUDE.md` never made at all, invented during re-authoring.

Root cause: the plan applied *"derive from code, not from CLAUDE.md"* to Steps 6 and 7 only — the two steps the mega-audit happened to scrutinize — and let Steps 2–5 source prose from the old file. That gap is now closed by a universal source-discipline rule in `## Guidance for Planner`, and it is the single most transferable lesson from this plan: **a structural check cannot detect a plausible falsehood.** Every gate this plan defined was the wrong shape to catch the failure it actually had.

### Known follow-ups this plan creates (recorded, not fixed)

- `src/claude_retry_proxy/server.py:1751` carries an in-code comment "Documented in CLAUDE.md Gotchas" for the `_DISCONNECT_ERRORS` residual. After the shrink that referent is `doc/architecture.html#disconnects`; the comment is stale.
- `README.md`'s env-var table has 10 rows vs `CLAUDE.md`'s 11 — it omits `PROXY_FEATURE_COMPAT_FILE`.
- `pyproject.toml` sets `readme = "README.md"` and `doc/` is not shipped as package data, so the new README→`doc/` links are dead on PyPI's rendered long-description.
