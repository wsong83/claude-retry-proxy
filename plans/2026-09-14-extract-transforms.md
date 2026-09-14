# Plan: Extract the mode-transform cluster out of server.py

**Project:** D:/proj/claude-retry-proxy
**Plan ID:** 2026-09-14-extract-transforms
**Created:** 2026-09-14

## Issue Log

Rows ordered newest-first (latest issues at top). New issues are prepended; resolved issues stay in place with updated status.

| Issue | Status | Found | Resolved | Resolved By |
|-------|--------|-------|----------|-------------|
| [consolidate-module-split-guidance-docs](./tmp/reports/defer-issue-consolidate-module-split-guidance-docs.json) | Open | 2026-09-14 | — | — |
| [extract-transforms-whitelist-key-mismatch](./tmp/reports/2026-09-14-extract-transforms-coder-import-whitelist-gate-defect.json) | Resolved | 2026-09-14 | 2026-09-15 | [tester](./tmp/reports/2026-09-14-extract-transforms-tester-2026-09-15.json) |

## Guidance for Coder

**Files to modify:**
- `src/claude_retry_proxy/transforms_common.py` (created)
- `src/claude_retry_proxy/transforms_chat.py` (created)
- `src/claude_retry_proxy/transforms_response.py` (created)
- `src/claude_retry_proxy/server.py` (modified)

**Step-by-step with verification:** each step below carries coder checks tagged `(auto)` or `(scripted)`. The coder self-verifies `(auto)` and runs the provided script for `(scripted)`. Tester owns the behavioral checks.

This is a **behavior-preserving extraction**. Everything moves verbatim: same function names, same signatures, same return values, same exceptions, same trace events. Do not "improve" anything you move — no renames, no reordering, no `f`-strings replacing `.format()`, no type annotations, no docstring edits inside moved bodies. The only new text you write is: the module docstring of each new file, the import lines, and `__all__`.

Count the changes precisely — the planner's inventory, measured 2026-09-14 against the pinned tree:

| Kind | Count | What |
|------|------:|------|
| **Behavioral** | **0** | — |
| **Module-surface** | **2** | `_request_transform_timestamp` and `_transform_tool_result_to_chat_tool` stop resolving on the `server` module. All 12 of their call sites move with the bodies (11 inside the moved defs, the 12th being `_transform_tool_result_to_chat_tool`'s sole caller `_transform_anthropic_messages_to_chat`), and no test or external module reads them by name — evidence: `_require_server_func` requests seven distinct names (enumerated in the Summary's frozen-surface bullet), none of which is one of these two, and a repo-wide grep for all 11 moved names in `src/` + `scripts/` (excluding `server.py`) returns zero matches. |
| **Implementation** | **0** | Pure relocation with four import lines added to `server.py`. |

**Pinned region (re-measure at Step 4 start).** On the tree as of 2026-09-14, the transform region is `server.py` lines 2277–3214: the banner block 2277–2279, a blank, the 11 defs (2281–3212), and the two trailing blanks (3213–3214). Before it, `_rewrite_json_response` ends at 2274 with two blanks at 2275–2276; after it, the `# HTTP request handler` banner begins at 3215, followed by one blank and `def _crlf_safe` at 3219. Deleting **2277–3214 inclusive** therefore leaves exactly the repo's two-blank separator between the surviving code and the handler banner. If the file has drifted from these coordinates (blank-line parity, banner text, def head at 2281, last def ending 3212), **stop and report to the planner** — do not improvise ranges.

**Do not move these, even though they sit adjacent to the region:**

| Name | Line | Why it stays |
|------|------|--------------|
| `_rewrite_sse_first_event` | 2178 | The rewrites pair — a model-field patch, not a body-shape transform. Its sole caller is handler streaming machinery (`_stream_upstream_response`, 3339). Rides with the forwarder/handler extraction wave (criteria doc §7; user decision 2026-09-14). |
| `_rewrite_json_response` | 2250 | Same pair; called twice from `_forward_core` (1971, 2062 post-pin). |
| `_crlf_safe` | 3219 | Handler-section header-safety guard; imported directly by `tests/test_unit.py`. |
| `_stream_upstream_response` | 3248 | Handler cluster: owns `self.wfile`, disconnect handling, size caps. Step 5+ material. |
| `_stream_chat_sse_to_anthropic` | 3425 | Handler cluster: the chat SSE stream converter (socket stateful). Not a body transform under the substitution test. |
| `_stream_response_sse_fallback`, `_sse_event` | — | Same: SSE framing/dispatch machinery. |

**Call sites that stay in `server.py` and must keep their text byte-identical.** Only the import block below changes; every existing expression is untouched:
- `_forward_core`: the three `_transform_and_guard(...)` calls, the request-direction dispatch calling `_anthropic_to_chat` / `_anthropic_to_response` in `_forward_request_impl`, and the `transform_fn = _chat_to_anthropic if mode == "chat" else _response_to_anthropic` selection line.
- `ProxyHandler`: the two `_map_chat_finish_reason(...)` calls in the SSE `handle_frame` closure.

**Import whitelists are pinned and gate-enforced** (see "How the scripts were validated"). Each new module's imports are exactly:

- `transforms_common.py`: `import json`, `import time`, `from .sinks import log_trace`
- `transforms_chat.py`: `import json`, `import time`, **`import uuid`**, `from .sinks import log_trace`, `from .transforms_common import _request_transform_timestamp`
- `transforms_response.py`: `import json`, `import time`, `from .sinks import log_trace`, `from .transforms_common import _request_transform_timestamp`

(`uuid` serves tool-call id synthesis inside `_chat_to_anthropic`; it was caught by the calibration dry-run of the Rule-3 gate, not by the initial inventory. If the gate ever fails for a name not in these lists, do not add the import silently — the plan must be revised.)

**How the scripts were validated (calibration record).** Step 4's script was negative-tested against the pre-change tree: it fails on **exactly the 20 not-yet-done conditions** (11 defs still present, banner present, 2 orphans still resolving, `_map_chat_finish_reason` count 4≠2, 2 orphan reference groups, 3 modules missing) and on **none** of the counts that should already hold (guard calls 3, request-dispatch calls 1+1, bare refs 2+2, seam parity, import smoke, `--help`). Steps 1–3 exit early pre-change ("not created yet"); their predicates were validated as follows — the Rule-3 undefined-name gate was dry-run against synthetic future modules (whitelisted imports + the exact HEAD def bodies) with **ALL CLEAN** for all three modules, and that run caught two first-draft defects (the chat whitelist gained `uuid`; comprehension targets must be collected before the element body, per word-grinder Rule 3). The import audit was **not** exercised in that draft, and its first real run (coder Step 1 round) exposed a third defect — the `ImportFrom` level/key mismatch (issue `extract-transforms-whitelist-key-mismatch`) — now fixed and negative-tested: whitelisted relative imports pass, while `import os`, `from .server import …`, wrong names from whitelisted modules, and `from json import dumps` are each rejected. With the fix, steps 1–3 run exit-0 against the coder's on-disk modules (byte-identity, whitelist, closure, acyclicity all pass). A gate that cannot fail is not a gate.

**Rollback.** The whole plan is one reviewable unit and one commit (user decision 2026-09-14 — see Document Overrides): `git revert <sha>` of the single refactor commit removes all four steps together, and the live proxy picks the revert up on its next restart. No artifacts are migrated. Between module creation and the commit, the three new files are **staged** (`git add`) rather than untracked, so they are index-protected from `git clean`, carried by `git stash`, and visible in diffs while the tree is red between steps. The verification scripts are step-boundary gates: once the single commit lands, steps 1–4 stop being re-runnable against HEAD (it loses the defs they compare against). Step T1 therefore bases its diff on the pre-plan HEAD (see below), not on HEAD.

## Guidance for Tester

**Tests to create:** none. This is a zero-test-change extraction: the suite reaches the moved functions through `_require_server_func` → `getattr(server, name)` in `tests/test_chat_transform.py`, `tests/test_response_transform.py`, and `tests/test_mode_dispatch.py`, and the 9 imported names keep resolving on `claude_retry_proxy.server`; the 2 orphans stop resolving by omission from the import list (see the module-surface table). No test file is modified.

**Tests to investigate for retirement:**
- Planner candidates: none. "No test obsolescence identified." `tests/test_unit.py` imports `_crlf_safe` directly, but that function does not move. Every transform test changes nothing about *how* it reaches the code or *what* it asserts.
- Tester may identify additional candidates during test work.

**Retirement procedure:** For each candidate, verify the test exercises code being removed/changed. If obsolete: delete and note in session report. If still valid: document why in session report.

## Proposed Changes

Each step includes verification checks tagged with confidence (see Prime Directive 4).
`(auto)` = mechanical, coder self-verifies. `(scripted)` = deterministic multi-step, coder runs provided script.
Every step must have at least one verification check executable by its owner (coder steps: coder checks; tester steps: tester verify; planner steps: Evidence).

1. **Step 1:** Create `src/claude_retry_proxy/transforms_common.py`. Move `_transform_and_guard` (`server.py:2281-2312`) and `_request_transform_timestamp` (`server.py:2377-2378`) into it **verbatim** — byte-identical bodies, two blank lines between defs, original order. Module docstring: one line stating this is the shared mechanism for endpoint-mode response transforms (the passthrough-on-failure guard and the shared trace-timestamp helper). Imports exactly: `import json`, `import time`, `from .sinks import log_trace`. `__all__ = ["_transform_and_guard", "_request_transform_timestamp"]`. **Do not touch `server.py` in this step.**
   → coder verify (auto): file exists with the two defs; `import claude_retry_proxy.transforms_common` succeeds
   → coder verify (scripted): `./tmp/verification/2026-09-14-extract-transforms-step1.py` — asserts the exact two-def surface, byte-identity vs `git show HEAD` (AST source segments, line-ending normalized), the import whitelist, the Rule-3 undefined-name gate (params ∪ Store names ∪ lambda args ∪ except aliases ∪ function-local imports ∪ comprehension targets, closures resolved through enclosing scopes), `__all__`, and standalone import without pulling `claude_retry_proxy.server`
   → tester verify: none (additive module, unreachable until Step 4 — no behavioral change to verify)

2. **Step 2:** Create `src/claude_retry_proxy/transforms_chat.py`. Move the seven chat-family defs **verbatim, in original order**: `_anthropic_to_chat` (2315-2374), `_transform_anthropic_messages_to_chat` (2381-2576, including its nested `def _assistant_msg` — byte-locked), `_transform_tool_result_to_chat_tool` (2579-2598), `_transform_anthropic_tools_to_chat` (2601-2644), `_transform_anthropic_tool_choice_to_chat` (2647-2663), `_map_chat_finish_reason` (2666-2671), `_chat_to_anthropic` (2674-2801). Imports exactly: `import json`, `import time`, `import uuid`, `from .sinks import log_trace`, `from .transforms_common import _request_transform_timestamp` (the "import follows its reader" relocation — the six chat-side call sites keep calling it bare). `__all__` = the seven names. **Do not touch `server.py`.**
   → coder verify (auto): file exists with the seven defs in order; `import claude_retry_proxy.transforms_chat` succeeds
   → coder verify (scripted): `./tmp/verification/2026-09-14-extract-transforms-step2.py` — same assertion battery (whitelist includes `uuid`; `_request_transform_timestamp` allowed from `.transforms_common`)
   → tester verify: none (additive module)

3. **Step 3:** Create `src/claude_retry_proxy/transforms_response.py`. Move the two response-family defs **verbatim, in original order**: `_anthropic_to_response` (2804-3110), `_response_to_anthropic` (3113-3212). Imports exactly: `import json`, `import time`, `from .sinks import log_trace`, `from .transforms_common import _request_transform_timestamp` (the five response-side call sites keep calling it bare). `__all__` = the two names. **Do not touch `server.py`.**
   → coder verify (auto): file exists with the two defs in order; `import claude_retry_proxy.transforms_response` succeeds
   → coder verify (scripted): `./tmp/verification/2026-09-14-extract-transforms-step3.py` — same assertion battery
   → tester verify: none (additive module)

4. **Step 4:** Rewire `src/claude_retry_proxy/server.py`. Order of operations: (a) re-verify the pinned region (banner at 2277–2279, `def _transform_and_guard(` at 2281, last def ends at 3212, handler banner at 3215; also `git diff -- src/claude_retry_proxy/server.py` must be empty before you start — do not delete ranges from a drifted file; and confirm the range held nothing but the banner, the 11 defs, and blank lines — the step-4 script's region-shape check asserts against HEAD that the span contains exactly those 11 `FunctionDef` nodes and no module-level Assign/Import/ClassDef, so nothing can ride along in the deletion); (b) delete lines **2277–3214 inclusive**; (c) add to the package-import group, immediately after the existing `from .sinks import (...)` line (server.py:34-35), these three lines:
   ```python
   from .transforms_chat import (_anthropic_to_chat, _chat_to_anthropic,
                                 _map_chat_finish_reason,
                                 _transform_anthropic_messages_to_chat,
                                 _transform_anthropic_tool_choice_to_chat,
                                 _transform_anthropic_tools_to_chat)
   from .transforms_common import _transform_and_guard
   from .transforms_response import (_anthropic_to_response, _response_to_anthropic)
   ```
   Do **not** import `_request_transform_timestamp` or `_transform_tool_result_to_chat_tool` (see the module-surface table). Do **not** remove `import json` / `import time` / any other import from `server.py` — the file retains many other readers. Do not touch any other line: every remaining call site and the two bare transform_fn references stay byte-identical.
   → coder verify (auto): none of the 11 defs remain in `server.py` (grep); the three import lines are present; `import claude_retry_proxy.server` succeeds
   → coder verify (scripted): `./tmp/verification/2026-09-14-extract-transforms-step4.py` — asserts: 11 defs gone; banner gone; the 9 re-exported names resolve on the imported `server` module and the 2 orphans do not; call-site token counts (`_transform_and_guard` calls 3, request-dispatch calls 1+1, `_map_chat_finish_reason` calls 2 — down from 4, the pair that moved with `_chat_to_anthropic`; bare refs `_chat_to_anthropic` 2 / `_response_to_anthropic` 2, zero direct calls; zero orphan references); seam blank-line parity (exactly two blanks between `_rewrite_json_response` and the handler banner, one blank before `def _crlf_safe`); whole-move byte-identity of all 11 defs vs HEAD; a HEAD region-shape check (the deleted range held exactly the 11 defs and nothing else — nothing rides along in the deletion); the export probe additionally asserts the resolved `server` module file lives under this repo's `src/` (the editable-install check CLAUDE.md mandates); import-chain acyclicity for all three modules; `python -m claude_retry_proxy.server --help` exits 0. Baseline calibration: fails pre-change on exactly 20 not-yet-done conditions and on none of the already-holding counts.
   → tester verify: full suite green after Step T2 (Step 4 and the tester steps are one reviewable unit — see Guidance for Tester (steps))

## Guidance for Tester (steps)

1. **Step T1:** Behavioral gate. Run `python tests/test_claude_proxy.py`. Then independently audit the move: pin the pre-plan commit's SHA first (`git rev-parse --short HEAD` before the single refactor commit, or `git log --oneline -2` after it — HEAD loses the defs at that commit, so the comparison base is the pre-plan tree), then diff each of the 11 defs' bodies in the three new modules against `git show <pre-plan-sha>:src/claude_retry_proxy/server.py` (AST-normalized comparison, not eyeball — the step scripts already do byte-identity; the tester's job is an *independent* second measurement), and confirm the only server.py differences are the region deletion and the three import lines (`git diff -- src/claude_retry_proxy/server.py` review). Confirm the two module-surface changes are exactly the two orphans and nothing else (`import claude_retry_proxy.server as s; [n for n in dir(s) ...]`-style probe against a HEAD checkout's dir() is overkill; assert the 9 resolve and the 2 do not via the step4 probe).
   → tester verify: suite green; byte-identity auditor confirms zero body drift; module-surface delta = exactly the 2 orphans

2. **Step T2:** Full-suite gate, twice to shake flake. Baseline measured by the planner 2026-09-14: **304 passed, 0 failed** (one known warning: "No proxy_stop event in trace" — deferred issue `no-proxy-stop-trace-warning`, expected for abrupt teardown, not a failure). **No test file changes in this plan, so the per-module counts and the aggregate must be unchanged at 304** — any delta is a regression or a test the suite newly reaches, and both are findings. <!-- UPDATED 2026-09-15: the aggregator prints per-test slug lines, never module filenames — the literal check was not executable as written; the slug-based verification below is what the tester ran and is the executable form --> Spot-check that the transform tests ran: import `ALL_TESTS` from each of `tests/test_chat_transform.py`, `tests/test_response_transform.py`, and `tests/test_mode_dispatch.py`, match every slug against `>> <slug>: PASSED` lines in the suite output, and confirm zero missing. Measured 2026-09-15: 41/41 + 37/37 + 28/28 (106 of 304).
   → tester verify: 304/304 twice; per-module counts unchanged; session report with `overall_result: "SUCCESS"`

## Summary

**Problem.** `src/claude_retry_proxy/server.py` is 4,650 lines (wc -l, 2026-09-14) and holds seven unrelated concerns. This plan extracts exactly one of them — the endpoint-mode body-transform cluster (chat + response) — as the next step of the staged decomposition in `.claude/cluster-extraction-criteria.md` §7 (sinks and sanitize are already out). It is the natural successor: the moved bodies read **no** module-level state at all, reaching outside themselves only for `log_trace` (already a leaf in `sinks.py`), `json`, `time`, and `uuid` — so the blast radius is the smallest of the remaining clusters.

**Cluster shape (user-approved 2026-09-14 after detailed discussion):**

```
transforms_common.py    __all__ = [_transform_and_guard,           (34 lines)
                                   _request_transform_timestamp]
                        the guard: passthrough-on-failure wrapper every
                        response transform runs through; the timestamp
                        helper both families import (6 chat + 5 response sites)

transforms_chat.py      __all__ = [_anthropic_to_chat,             (471 lines)
                                   _transform_anthropic_messages_to_chat,
                                   _transform_tool_result_to_chat_tool,
                                   _transform_anthropic_tools_to_chat,
                                   _transform_anthropic_tool_choice_to_chat,
                                   _map_chat_finish_reason,
                                   _chat_to_anthropic]

transforms_response.py  __all__ = [_anthropic_to_response,         (407 lines)
                                   _response_to_anthropic]
```

Import DAG, strictly downward — no cycle is possible: `server` → {common, chat, response}; {chat, response} → common; common → sinks → sanitize. Nothing in the cluster imports `server`.

**Membership (criteria doc tests 1–3).** All 11 defs are instances of one thing — body-shape conversion between the Anthropic format and a vendor mode, in both directions (request: anthropic→mode; response: mode→anthropic), plus the two mechanisms that conversion requires (the guard, the timestamp; "collaborators, not siblings"). Substitution holds where it matters: `_forward_core` already treats the two mode converters interchangeably (`transform_fn = _chat_to_anthropic if mode == "chat" else _response_to_anthropic`), threaded through the same guard. Deletion: the guard has no caller outside the concept; the timestamp's 11 readers are all inside it; the four converters *are* the body; `_map_chat_finish_reason`'s two handler-side readers stay valid via re-import.

**Key design decisions.**

- **Three files, not one.** The user chose the shared-core layout over a single `transforms.py` (2026-09-14). The sharing is exactly what the core holds: one 2-line helper imported by both families, one 32-line guard that both modes' responses run through at runtime (its callers sit in `_forward_core`, so the guard is imported by `server` alone — an honest asymmetry, not a padded core).
- **The rewrites pair stays.** `_rewrite_sse_first_event`/`_rewrite_json_response` patch one field (`model`) for the client-facing tier name; they are not shape transforms, and their readers live in the forward/handler code that later extraction steps move (criteria §7). Extracting them now would strand a handler-internal dependency in a module owned by the wrong wave. User-approved after the evidence (2026-09-14).
- **The SSE machinery stays.** `_stream_upstream_response`, `_stream_chat_sse_to_anthropic`, `_stream_response_sse_fallback`, `_sse_event` are handler-cluster code (socket I/O, disconnect handling, framing); they split with the handler extraction (step 5+). Recorded in the criteria doc so that plan need not re-derive it. Note for that future plan: response-mode streaming is deliberately absent today (request transform forces `stream:false`; only a defensive fallback exists) — enabling it is a feature plan, not structural work.
- **Two names become unbound on `server`.** `_request_transform_timestamp` and `_transform_tool_result_to_chat_tool` have zero remaining readers after the move (all 12 call sites relocate) and zero test lookups — the frozen surface (caller-read names ∪ test-imported names) does not include them, so `server.py` imports only the 11 − 2 names. Mirrors the sinks plan's `SINK_WARN_INTERVAL` precedent: the parent's surface is what it actually uses.
- **Frozen surface is preserved.** Tests reach 7 of the names only through `_require_server_func` → `getattr(server, name)` — the `_transform_anthropic_*` trio plus `_anthropic_to_chat`, `_chat_to_anthropic`, `_anthropic_to_response`, `_response_to_anthropic`. Four of those also have production call sites that stay in `server.py`; the other 3 are imported solely to preserve the test surface. All 7 are among the 9 imported. Zero test changes, zero retargeting — unlike the sinks plan, there is no red interval anywhere in this plan.
- **Verification is byte-identity + closure, per the word-grinder module-split guidance (Rule 2 byte-lock, Rule 3 full-scope AST gate) and the criteria doc §6 (token-based checks, calibration).** The Rule-3 gate needed comprehension-target ordering (see History/calibration) and the chat whitelist needed `uuid` — both caught by negative-testing before the plan shipped.

**Alternatives considered and rejected.**

- *Single `transforms.py`* — under the 1,000-line target and simplest, but the user prefers the mode-family layout with a shared core; the measured sharing (34 lines) makes the core small but honest.
- *An anthropic-mode file holding the rewrites* — 97 lines, response-only, wrong concept (field patch ≠ shape conversion), wrong staging (rides the forwarder/handler wave). User-approved rejection.
- *Keep `_transform_and_guard` in `server.py`* — it is a deletion-test member of the cluster; keeping it would split one mechanism from its charge while the call sites stay byte-identical either way.
- *Re-export the two orphans* — a surfaced-but-unused name is speculative API. (`read_state` was deleted rather than relocated for the same reason — see the sinks plan's Issue Log, `tmp/plans/2026-09-11-extract-sinks.md`.)
- *`__init__.py` re-exports* (the defer report's suggestion) — no consumer imports the package top-level for functions; the `server` module is the named surface.

**Out of scope.** Everything else in `server.py` (rewrites, SSE trio, handler, forwarder, settings, compat, admin, retry/backoff); the deferred issues in CLAUDE.md's `## Unresolved Deferred Issues` (including `break-up-large-source-and-test-files`, which stays Open — this is one cluster of its staged decomposition, and the criteria doc has the rest); response-mode streaming as a feature; anything behavioral.

## Repo Mode

Public

*Detected at plan creation. Determines: plan archival path, commit-message content, staged files.*

## Document Overrides

| Document | Rule Overridden | Reason |
|----------|---------------|--------|
| `.claude/cluster-extraction-criteria.md` §6 | "Green at every boundary; commit at every boundary" | User decision 2026-09-14: this plan is one coherent single-cluster refactor and ships as ONE commit. The boundary-commit rule exists for large multi-step refactors where working-tree loss and partial revert are material risks; here the whole plan is the revert unit. Staging-on-creation covers the untracked-file risk (see Risks). |

## Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| **Pinned line ranges drift before Step 4** (another plan may edit `server.py` between plan time and implementation) | Deletion cuts into the wrong lines — silent corruption that green tests would not catch until review | Step 4 (a): re-verify the pinned coordinates (banner, def head, last-def end, handler banner) and confirm `git diff -- src/claude_retry_proxy/server.py` is empty before deleting. Any drift → stop and report to the planner. |
| A moved body reads a name nobody inventoried (hidden dependency beyond `log_trace`/`json`/`time`/`uuid`) | `NameError` at request time on the rewritten tree | The Rule-3 gate fails loudly (name + line) at the coder's step boundary. Calibration already dry-ran all three synthetic modules against the pinned whitelists — ALL CLEAN — and added `uuid` to chat. Any gate failure for a name outside the whitelists must come back to the planner, not a silent import. |
| Coder "improves" moved bodies (renames, f-string rewrites, docstring edits) | Silent behavior drift; destroys the plan's only reviewable property | Byte-identity gates reject any body drift at every step; Guidance for Coder's do-not list; the tester independently re-diffs against `git show HEAD`. |
| Test surface broken by a missed re-export | `getattr(server, name)` failures inside `_require_server_func` — tests fail (visible), not silently | Step 4's export/absence probe pins exactly the 9-resolve/2-unbound surface. |
| New modules unprotected while in flight (single-commit mode) | Working-tree loss — `git clean -fd` would delete the untracked creations (criteria §6) | Coder stages (`git add`) each new module immediately on creation: index-protected from `git clean`, carried by `git stash`, diffable while the tree is red between steps. The single commit lands when the suite is green. |

## Guidance for Planner

Documentation tasks you will execute yourself (not the coder):

- **Doc files to update:** `CLAUDE.md`, `.claude/cluster-extraction-criteria.md`.
- **When:** after the coder finishes and the tester reports `overall_result: "SUCCESS"`.
- **What to sync:**
  - **Structure section, `src/claude_retry_proxy/` listing** — add three entries matching the existing style: `transforms_common.py` (shared endpoint-mode transform mechanism: `_transform_and_guard` guard + `_request_transform_timestamp` helper), `transforms_chat.py` (Anthropic↔Chat body transforms), `transforms_response.py` (Anthropic↔Responses body transforms). The `server.py` entry's parenthetical is unchanged ("model rewriting" already refers to the rewrites pair, which stays).
  - **Future Work → TODO prose** — add one sentence that the transforms cluster landed (partial progress on `break-up-large-source-and-test-files`); do NOT touch the `## Unresolved Deferred Issues` JSON block (`/update-and-commit` is its sole writer) and do NOT claim the file-size issue is resolved.
  - **`.claude/cluster-extraction-criteria.md` §7** — re-measure and record: `server.py` 4,651 → 3,720 lines (coder-measured on the staged tree: 938 deleted, +7 for the seven wrapped import lines); the `Mode transforms (chat + response)` row marked extracted 2026-09-14 with the three-module layout and per-module sizes (code-body spans 34/471/407; whole files 46/499/421 including docstrings/imports/`__all__`); the extraction-order table's step 2 marked done. The three verdict records for future plans (SSE machinery belongs to the handler cluster; the rewrites pair rides the forwarder/handler wave; response-mode streaming is a future feature plan) were written into §7 at plan-approval time — nothing further to record there. One line-reference re-point remains: the §7 state table's `server.py:113` note (`_admin_html_cache`) shifts by the import block's line count — measure the post-rewire value on the final tree during the same sync (estimation proved unreliable: the block landed as 7 wrapped lines, not 3).
  - **`doc/*.html`** — verified 2026-09-14: zero `server.py:` line references anywhere in the doc tree, and no function is renamed or removed, so no doc content changes. Re-verify with the commit's diff to be sure nothing references the region.
  - **Non-doc task:** keep `tmp/reports/defer-issue-break-up-large-source-and-test-files.json` at `status: "Open"` with `target_repo: null`.

## History

| Date | Event | Conclusion | Dismissed |
|------|-------|------------|-----------|
| 2026-09-14 | Initial plan | Extract the endpoint-mode transform cluster from `server.py` (4,650 lines) into `transforms_common.py` + `transforms_chat.py` + `transforms_response.py` (912 code lines, 11 defs, byte-identical; 938 lines out of `server.py`); zero test changes, zero behavioral changes, module-surface change = 2 orphan names unbound. Phase 4.5 mega-audit not triggered by threshold, then user-invoked the same day (see below). Calibration: all four verification scripts negative-tested against the pre-change tree; the Rule-3 gate dry-run on synthetic future modules caught and fixed two first-draft defects (chat needs `import uuid`; comprehension-target ordering). | — |
| 2026-09-14 | Mega-audit (pre-implementation, iteration 1 of 3 — user-invoked outside the Phase 4.5 trigger) | 16 findings — **0 High / 3 Medium / 13 Low** — verdict "Issues found — non-blocking"; 0 High is the planner's exit-test (<3), so no second iteration. All 16 fixed this round, Mediums first: tester-prose contradiction (9 names resolve / 2 unbound, not "all 11"); the T1 byte-diff base pinned to the Step 3 commit (HEAD loses the defs at Step 4); the criteria-doc `server.py:113` line-reference drift added to the doc sync. Lows also fixed rather than dismissed — all were plan-internal arithmetic or gate hardening: response family 411→407 / total 916→912; seven test-reached names split 4 production-covered / 3 test-only; citation corrected to the sinks-plan `read_state` precedent; verdict records actually written into criteria §7 (the plan had cited them as already present); scripts now decode `git show` output as utf-8 (locale-default cp1252 would mangle em-dashes), gained a HEAD region-shape check (no statement but the 11 defs may ride in the deletion range) and an editable-install `src/` assertion on the export probe; steps 1–3 script expiry documented. Calibration re-verified: step 4 still fails pre-change on exactly the same 20 not-yet-done conditions. Report: `./tmp/reports/2026-09-14-extract-transforms-mega-audit-2026-09-14.json`. | — (all 16 closed; none dismissed) |
| 2026-09-14 | Spec revision (/update-plan) | User decision: the plan ships as ONE commit — a coherent single-cluster refactor, not a multi-step one. Per-step boundary commits removed from Immediate Actions and Rollback; staging-on-creation added as the in-flight protection; Step T1's diff base re-pinned to the pre-plan HEAD; the criteria-doc §6 deviation recorded in Document Overrides (and in Plan Metadata). | — |
| 2026-09-15 | Implementation round (coder Steps 1–4, tester T1–T2) | Coder: all four steps complete, `build_result: pass`, all four step gates exit 0 after the whitelist-fix revision; files staged in single-commit mode, **the single commit not yet landed** (coder's commit attempts denied — pending user approval). Module files 46/499/421 lines incl. header text; `server.py` 4,651 → 3,720. Tester: `overall_result: SUCCESS`, 304/304 on four genuine full-suite runs (aggregate unchanged from baseline; only the known-and-expected `no-proxy-stop-trace-warning`), transform module groups verified via slugs (41/41 + 37/37 + 28/28 = 106/304), independent byte-identity audit clean (all 11 defs identical to the pre-rewire tree `c7f93c7`; server.py diff = 7 insertions / 938 deletions = exactly the import block), step4 gate re-run PASS. Reports: `./tmp/reports/2026-09-14-extract-transforms-coder-2026-09-14.json`, `./tmp/reports/2026-09-14-extract-transforms-tester-2026-09-15.json`. | — |
| 2026-09-15 | Spec revision (/update-plan) | T2's spot-check wording corrected to the executable slug-based check (the aggregator never prints module filenames — tester-reported discrepancy); issue `extract-transforms-whitelist-key-mismatch` → Resolved; Guidance-for-Planner numbers updated to the coder's measurements (4,651 → 3,720, measured re-point, whole-file vs code-body sizes); Immediate Actions removed (zero open directives). | — |
| 2026-09-15 | Phase 6 review (implementation, adversarial) | 1 finding — **0 Critical / 0 Warning / 1 Suggestion** — verdict "Issues found — non-blocking"; ready to commit. Report: `./tmp/reports/2026-09-14-extract-transforms-review-2026-09-15.json`. The reviewer independently re-verified: all 11 moved defs byte-identical to `HEAD:server.py` (raw compare, no normalization), def order matching the plan pins, all four gates re-run PASS (the whitelist level-folding fix present and commented), module surface 9-resolve/2-unbound with `__file__` under this repo's `src/`, diff accounting 7 insertions / 938 deletions with nothing else in the deletion range, seam parity, call-site token counts, whitelist usage, and acyclicity. | `[review-t1-audit-dead-code](./tmp/reports/2026-09-14-extract-transforms-review-2026-09-15.json)` — acknowledged, not fixed: dead code in the gitignored tester audit script (`defs_of()` uncalled with a no-op `pytest_skip` assignment; unused `import_added`; dead `expected_import_lines = 5` contradicting the live check that correctly requires 3). Non-blocking; the file never ships outside `tmp/`. |

## Plan Metadata

```json
{
  "plan_id": "2026-09-14-extract-transforms",
  "steps": ["Step 1: Create transforms_common.py", "Step 2: Create transforms_chat.py", "Step 3: Create transforms_response.py", "Step 4: Rewire server.py"],
  "coder_files": ["src/claude_retry_proxy/transforms_common.py", "src/claude_retry_proxy/transforms_chat.py", "src/claude_retry_proxy/transforms_response.py", "src/claude_retry_proxy/server.py"],
  "tester_files": [],
  "doc_files": ["CLAUDE.md", ".claude/cluster-extraction-criteria.md"],
  "verification_scripts": ["./tmp/verification/2026-09-14-extract-transforms-step1.py", "./tmp/verification/2026-09-14-extract-transforms-step2.py", "./tmp/verification/2026-09-14-extract-transforms-step3.py", "./tmp/verification/2026-09-14-extract-transforms-step4.py"],
  "repo_mode": "Public",
  "document_overrides": [".claude/cluster-extraction-criteria.md §6: commit at every step boundary (Reason: user decision 2026-09-14 — one commit for the whole coherent single-cluster refactor)"]
}
```

## Audit Accumulation

*Counters reset when mega-audit runs. Used by Phase 5 entry trigger.*

| Counter | Value | Last Updated |
|---------|-------|--------------|
| issues_resolved_since_audit | 0 | 2026-09-14 |
| steps_changed_since_audit | 0 | 2026-09-14 |
| files_changed_since_audit | 0 | 2026-09-14 |

## Documentation

- [CLAUDE.md](CLAUDE.md) — Structure gains the three `transforms_*` entries; Future Work notes partial progress on the file-split issue.
- `.claude/cluster-extraction-criteria.md` — §7 re-measured (server.py 3,719 wc post-extraction); transforms row marked extracted; extraction-order step 2 marked done; the `server.py:113` note re-pointed to the measured 124; SSE/rewrites/response-streaming verdicts recorded for the step 5+ plans.

## Final Results

**Status:** COMPLETED — commit pending (owned by `/update-and-commit`; single-commit mode per the user's 2026-09-14 decision, Document Overrides).
**Completed:** 2026-09-15 (coder 2026-09-14; tester 2026-09-15; Phase 6 review 2026-09-15).

**Files changed**

| File | Change |
|------|--------|
| `src/claude_retry_proxy/transforms_common.py` | **created** — `_transform_and_guard` + `_request_transform_timestamp`, byte-identical (46 lines incl. header) |
| `src/claude_retry_proxy/transforms_chat.py` | **created** — the seven chat-family defs, byte-identical (499 lines incl. header) |
| `src/claude_retry_proxy/transforms_response.py` | **created** — `_anthropic_to_response` + `_response_to_anthropic`, byte-identical (421 lines incl. header) |
| `src/claude_retry_proxy/server.py` | modified — 938-line region deleted, 7-line import block added: **4,650 → 3,720 lines** (`wc -l` reports 3,719 — the file has no trailing newline) |

**Test results.** 304 passed / 0 failed on four genuine full-suite runs (T1 ×2 incl. the captured run, T2 ×2), aggregate and per-run counts unchanged from the 2026-09-14 planner baseline; only the known-and-expected `No proxy_stop event in trace` warning (deferred `no-proxy-stop-trace-warning`). The three transform module groups slug-verified via `ALL_TESTS` import and `>> <slug>: PASSED` matching: 41/41 + 37/37 + 28/28 = 106 of 304, zero missing. No test file changed.

**Verification.** All four plan gates exit 0 at every boundary, re-run PASS three times independently (coder round, tester round, Phase 6 reviewer). Byte-identity of all 11 moved defs against the pre-rewire tree (`c7f93c7`) confirmed by three independent measurements (the plan's AST-segment gates, the tester's T1 audit script, the reviewer's raw compare). Module surface: 9 names imported on `server`, the 2 orphans unbound as specified; `server.__file__` resolves to this repo's `src/` (editable install). Diff accounting: server.py = exactly the 7 import lines added and the 938-line region deleted — the region-shape check proves nothing else rode along.

**Module-surface changes (2).** `_request_transform_timestamp` and `_transform_tool_result_to_chat_tool` no longer resolve on the `server` module; zero in-repo consumers. Zero behavioral changes, zero implementation changes beyond the import block.

**Issues.** The coder-filed `extract-transforms-whitelist-key-mismatch` (planner script defect) is Resolved (tester-verified). The log's `consolidate-module-split-guidance-docs` deferral stays Open — a global docs task unrelated to this implementation and non-blocking (deferral precedent: the sinks plan finalized with its Open deferrals). The repo-level deferred issue `break-up-large-source-and-test-files` remains Open: this plan is the transforms step of its staged decomposition, not the whole issue.

**Known caveats.** One reviewer Suggestion, acknowledged not fixed: dead code in the gitignored tester audit script `tmp/verification/2026-09-14-extract-transforms-t1-audit.py` (`defs_of()` uncalled with a no-op `pytest_skip` assignment; unused `import_added`; dead `expected_import_lines = 5` contradicting the live check that correctly requires 3). Non-blocking; the file never ships outside `tmp/`.

**Cross-references to prior plans.** None — no deferred item from a prior plan was resolved by this work (checked against the sinks plan's and doc-tree plan's deferred lists; `sinks`/`sanitize` deferrals and the doc-tree deferrals all stand unchanged).