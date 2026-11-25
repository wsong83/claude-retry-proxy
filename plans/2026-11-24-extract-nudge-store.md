# Plan: Extract the chat retry-nudge store into chat_nudge.py (A1 of the forwarder campaign)
**Plan ID:** 2026-11-24-extract-nudge-store
**Created:** 2026-11-24

<!-- ## Immediate Actions: removed 2026-11-24 post-review — zero directives remain; all roles complete, next actions are user-gated (approval + /update-and-commit). -->

## Issue Log

Rows ordered newest-first (latest issues at top). New issues are prepended; resolved issues stay in place with updated status.

| Issue | Status | Found | Resolved | Resolved By |
|-------|--------|-------|----------|-------------|
| 2026-11-25-extract-swap-drain cross-reference — the open scope is now forwarder's swap-drain state + `runtime_state`'s five globals | Resolved | 2026-11-25 | 2026-11-25 | plan 2026-11-25-extract-swap-drain — Partially resolved: the swap-drain half landed here; `runtime_state`'s five globals remain the open remainder of the conversion |
| [step2-cut-range-vs-seam](./tmp/reports/2026-11-24-extract-nudge-store-step2-cut-range-vs-seam.json) | Resolved | 2026-11-24 | 2026-11-24 | [planner](./tmp/reports/2026-11-24-extract-nudge-store-step2-cut-range-vs-seam.json) |
| [step3-frozen-surface-contradiction](./tmp/reports/2026-11-24-extract-nudge-store-step3-frozen-surface-contradiction.json) | Resolved | 2026-11-24 | 2026-11-24 | [planner](./tmp/reports/2026-11-24-extract-nudge-store-step3-frozen-surface-contradiction.json) |

## Guidance for Coder

**Files to modify:**

| File | Change |
|---|---|
| `src/claude_retry_proxy/chat_nudge.py` | NEW — the nudge block moved verbatim, then shaped into the owned-store design (steps 1, 3) |
| `src/claude_retry_proxy/forwarder.py` | delete the nudge block; add the frozen-surface re-export; delete `import hashlib` (step 2); shrink the re-export to the five surviving names (step 3) |

**Step-by-step with verification:** coder steps carry `(auto)`/`(scripted)` checks; the scripted gates live at `./tmp/verification/2026-11-24-extract-nudge-store-step{1,2,3}.py` and must be proven RED against the pre-change tree and GREEN after their step, unedited between runs. The coder never touches `tests/` and never writes docs. Gate scripts that import proxy modules must set the spawn-isolation env (`PROXY_TRACE_FILE`, `PROXY_STATE_FILE`, `PROXY_FEATURE_COMPAT_FILE` under a `tempfile.mkdtemp()` directory) **before** the first proxy import — the canonical block is doc/test-catalog.html#pattern-spawn-isolation.

### Frozen surface (move contract)

`from .chat_nudge import ...` in forwarder.py must carry exactly these seven names — the union of production readers and test-read names, measured 2026-11-24:

| Name | Justification (evidence) |
|---|---|
| `_retry_nudge_arm` | called by `chat_sse.py:20` import; re-exported by `server.py:46` |
| `_retry_nudge_check` | re-exported by `server.py:47`; called in `forwarder.py:1006` |
| `_retry_nudge_entries` | test attribute-form pokes in `tests/test_chat_sse.py` (no test rebinds it — only `.clear()`, item set, membership, read) |
| `_retry_nudge_lock` | test attribute-form pokes in `tests/test_chat_sse.py` |
| `_retry_nudge_messages_bytes` | called by `chat_sse.py:20`; re-exported by `server.py:47` |
| `_retry_nudge_remember` | re-exported by `server.py:48`; called in `forwarder.py:1004` |
| `RETRY_NUDGE_TTL_SECONDS` | re-exported by `server.py:53` |

NOT re-exported (zero external readers measured): `_retry_nudge_sweep` (lock-held-internal, called only within the block at 349/440), `RETRY_NUDGE_MAX_ENTRIES` (read only inside the block), the two eviction/digest internals.

**Step-3 amendment:** the surface legitimately shrinks to **five** names at step 3 — `_retry_nudge_lock` and `_retry_nudge_entries` retire from it because their only readers (the test pokes) repoint to `chat_nudge._store` in the same reviewable unit (step 3 item 4). This amendment is part of the reviewed design, not silent drift; until step 3 lands, the seven-name list above is the contract.

### Step 1: Create `src/claude_retry_proxy/chat_nudge.py` — the block moved byte-verbatim

Module skeleton (new text, this is the only new prose):

```python
"""Chat retry-nudge marker store (extracted from forwarder.py 2026-11-24).

Owns the single-use, in-memory recovery markers for the chat-mode
unfinished-turn retry (see the banner comment below). The parent module
(forwarder.py) imports this one; this module never imports its parent.
"""

import hashlib
import json
import threading
import time
```

followed by forwarder.py lines **275–472 inclusive** (198 lines: the `# ----` banner top at 275 through `return None` at 472; chat_nudge.py ends at the `return None` line), byte-identical — no renames, no reordering, no rewrapping, no annotation or f-string edits, no bug fixes. The blank pair at 273–274 stays in forwarder; the block's trailing blank pair 473–474 is deleted with the block at step 2 (its seam post-condition requires it). **`git add src/claude_retry_proxy/chat_nudge.py` immediately after creation.**

Import whitelist (pinned; exactly these four lines, nothing else): `hashlib`, `json`, `threading`, `time`. `hashlib`'s sole reader in all of forwarder.py is this block (measured: the import at line 11 and uses at 332/334/417/426 only); `json`/`time`/`threading` have readers elsewhere in forwarder and stay.

→ coder verify (auto): `chat_nudge.py` exists; `python3 -m py_compile src/claude_retry_proxy/chat_nudge.py` succeeds; it defines `_retry_nudge_sweep`, `_retry_nudge_remember`, `_retry_nudge_arm`, `_retry_nudge_messages_bytes`, `_retry_nudge_check`, `RETRY_NUDGE_TTL_SECONDS`, `RETRY_NUDGE_MAX_ENTRIES`, `_retry_nudge_lock`, `_retry_nudge_entries`.

→ coder verify (scripted): gate `./tmp/verification/2026-11-24-extract-nudge-store-step1.py` — byte-identity gate against the pinned pre-change literal (extracted mechanically from forwarder.py lines 275–472 at gate-authoring time with landmark assertions), located in `chat_nudge.py` by its banner pair through `return None` as the module tail, byte-for-byte; assert the module's import block is exactly the four whitelisted names (AST `Import` nodes, not text grep). RED on the pre-change tree (`chat_nudge.py` absent ⇒ FAIL), GREEN after step 1.

### Step 2: Rewire forwarder.py — delete the block, add the re-export, relocate `hashlib`

1. Delete forwarder.py lines **275–474** — the 198-line block step 1 moved **plus its trailing blank pair 473–474** (the step-2 seam post-condition requires exactly two blanks after the cut, which the surviving 273–274 pair provides; keeping 473–474 would leave four and fail gate-2 check (d)). Landmarks before cutting: lines 273–274 are two blanks, line 272 is `    return json.dumps(envelope).encode("utf-8")` (end of `_error_body`), line 275 is the `# ----` banner top, line 276 is `# Retry-nudge marker store (chat-mode unfinished-turn recovery)`, line 472 is `    return None`, lines 473–474 are two blanks, line 475 is `# Whitelisted paths and methods`. Post-cut seam must show `_error_body`'s return, then **exactly two** blank lines (the surviving 273–274), then `# Whitelisted paths and methods`. **A zero-length or shifted range on re-verification is a stop-and-report, not an improvisation.**
2. Delete `import hashlib` from forwarder.py (sole reader moved).
3. Add the re-export in forwarder.py's relative-import block, after the existing `from .settings import SETTINGS` line (forwarder.py imports no lifecycle module — that anchor was an error in the original draft), wrapped in the file's existing parenthesized from-import style; exact names per the frozen-surface table above:
   `from .chat_nudge import (_retry_nudge_arm, _retry_nudge_check, _retry_nudge_entries, _retry_nudge_lock, _retry_nudge_messages_bytes, _retry_nudge_remember, RETRY_NUDGE_TTL_SECONDS)`

→ coder verify (auto): `grep -c hashlib src/claude_retry_proxy/forwarder.py` returns 0; `python3 -c "import claude_retry_proxy.server"` succeeds; forwarder.py line count is 1,944 − 200 + (re-export lines) − 1 (the 200 = the 198-line block plus its trailing blank pair 473–474, both removed at this step).

→ coder verify (scripted): gate `./tmp/verification/2026-11-24-extract-nudge-store-step2.py` — (a) AST undefined-name check over the whole of forwarder.py with the full local-scope formula (params ∪ Store-context Names ∪ Lambda args ∪ ExceptHandler.name collected conditionally ∪ function-local imports; resolve Load names against locals ∪ module defs/assignments/imports ∪ builtins); (b) frozen-surface resolution: import forwarder under spawn-isolation env and `getattr` each of the seven names, FAIL naming any miss; (c) assert exactly one `from .chat_nudge import` in forwarder.py; (d) seam check: the two-blank gap before `# Whitelisted paths and methods`. RED on the pre-step-2 tree (block still present ⇒ the from-import is absent ⇒ FAIL), GREEN after step 2.

→ tester verify: full suite passes; total test count unchanged from the pre-change baseline; all nine nudge-behavior tests in `test_chat_sse.py` pass unmodified (they reach the store through the re-exported same objects — attribute-form `.clear()`/item-set/lock use need no edits in this step).

### Step 3: Owned-state conversion — `_NudgeStore` (design change; RED window with tester)

Shape step, NOT byte-locked. In `chat_nudge.py`:

1. Add class `_NudgeStore` owning the state: `__init__(self)` creates `self._lock = threading.Lock()` and `self._entries = {}`; methods `_sweep(self)`, `remember(self, request_id, body, body_json)`, `arm(self, request_id)`, `messages_bytes(self, request_id)`, `check(self, body, body_json)` — bodies carried over from the functions with exactly three rewrites: the two state bindings (`_retry_nudge_lock` → `self._lock`, `_retry_nudge_entries` → `self._entries`) and the two internal `_retry_nudge_sweep()` calls → `self._sweep()` (in `remember` and `check`); every other line byte-identical to step 1's text.
2. Replace the module-level `_retry_nudge_lock = ...` / `_retry_nudge_entries = ...` assignments with a single `_store = _NudgeStore()`. The module-level `_retry_nudge_sweep` function is **deleted** in this step (zero external readers measured — it was never in the frozen surface); it lives on as `_NudgeStore._sweep`.
3. Keep **four** module-level wrapper functions carrying the **frozen names** — `_retry_nudge_remember`, `_retry_nudge_arm`, `_retry_nudge_messages_bytes`, `_retry_nudge_check` — with unchanged signatures; each body is a single `return _store.<method>(...)` delegation (`remember`, `arm`, `messages_bytes`, `check` are the method names). `chat_sse.py` and `server.py` keep working byte-untouched through forwarder's re-export. `_store` itself is NOT re-exported — zero production readers; the tests reach `chat_nudge._store` directly.
4. Shrink forwarder's re-export to the **five surviving names** (`_retry_nudge_arm`, `_retry_nudge_check`, `_retry_nudge_messages_bytes`, `_retry_nudge_remember`, `RETRY_NUDGE_TTL_SECONDS`): `_retry_nudge_lock` and `_retry_nudge_entries` leave the frozen surface at this step — their only readers are the test pokes, which repoint to `chat_nudge._store` in the same reviewable unit (Guidance for Tester); production readers measured zero. The re-export edit belongs to the coder's half of the red window.

**Red interval:** this step breaks the attribute-form state pokes in `tests/test_chat_sse.py` (`forwarder._retry_nudge_lock` / `forwarder._retry_nudge_entries`, ≈10 sites in 6 tests). The coder edit and the tester repoint (see Guidance for Tester) are **one reviewable unit**; no commit inside the window.

→ coder verify (scripted): gate `./tmp/verification/2026-11-24-extract-nudge-store-step3.py` — (a) AST: `_NudgeStore` defined with the five methods; (b) assert-the-assembly: exactly ONE `threading.Lock()` call and ONE empty-dict construction in chat_nudge.py, both inside `_NudgeStore.__init__` — the module must hold exactly one store instance, `_store = _NudgeStore()`; (c) no module-level `_retry_nudge_lock`/`_retry_nudge_entries` assignments remain and no module-level `_retry_nudge_sweep` function remains; (d) each of the four wrappers — keyed by their frozen names (`_retry_nudge_remember` → `remember`, `_retry_nudge_arm` → `arm`, `_retry_nudge_messages_bytes` → `messages_bytes`, `_retry_nudge_check` → `check`) — has a single-statement body: a delegation Call to `_store.<method>` with mirrored arguments (AST, not text); (e) no bare-name use of `_retry_nudge_lock`/`_retry_nudge_entries`/`_retry_nudge_sweep` anywhere inside `_NudgeStore` (all reads/writes go through `self._lock`/`self._entries`/`self._sweep`); (f) forwarder's re-export carries exactly the **five** surviving names — no `_retry_nudge_lock`, no `_retry_nudge_entries`, no `_store`, no aliases; (g) runtime assembly: under spawn-isolation env, `import claude_retry_proxy.server` succeeds and forwarder resolves each of the five names (the green-side import proof, mirroring gate-2 check (b)). RED on the pre-step-3 tree, GREEN after the coder's half.

→ tester verify: full suite passes after the repoint; test count preserved (no tests deleted); the six repointed tests keep their original assertions (only the access path changed).

## Guidance for Tester

**Tests to create:**
- **Permanent:** none required — the nine existing nudge-behavior tests (`test_chat_sse.py:2833`–`3784`: unfinished-turn nudge, no-nudge-without-marker, disabled-by-empty-env, stall passthrough, armed-only TTL sweep, ineligible-not-consume, large-conversation canonicalization, prefix-digest strict extension, 64-entry eviction) already cover the store's behavior through its public surface. The conversion is internal shape; new tests would duplicate measured coverage.
- **Temporary:** none.

**Tests to revise (step 3 red window):**
- Repoint every `forwarder._retry_nudge_lock` / `forwarder._retry_nudge_entries` poke in `tests/test_chat_sse.py` to the canonical post-conversion form: `from claude_retry_proxy import chat_nudge`, then `with chat_nudge._store._lock:` guarding `chat_nudge._store._entries` access (enumerate sites: `grep -n 'forwarder\._retry_nudge_lock\|forwarder\._retry_nudge_entries' tests/test_chat_sse.py` — ≈10 sites in 6 tests at last measure; re-measure at execution). Assertions stay byte-identical; only the access path changes. Do NOT rebind `_store` or swap in fresh dicts — mutate the store's own objects exactly as the old pokes did.

**Tests to investigate for retirement:**
- No test obsolescence identified — the move re-exports the same objects and the conversion preserves every behavior the nine tests assert.

**Retirement procedure:** not applicable this plan.

## Summary

**Problem.** `forwarder.py` (1,944 lines) is the repo's only code file over the 1,000-line threshold (refactor-split survey, 2026-11-24). The nudge block (lines 275–472) is a self-contained cluster: the chat-mode unfinished-turn recovery marker store — five functions, two policy constants, a lock and a bounded dict. It passes the utility-cluster tests (task identity: "chat-mode unfinished-turn recovery"; leaf purity: stdlib-only reads — `time`/`json`/`hashlib`; cross-cutting: consumed by `forwarder.py` and `chat_sse.py`; bounded size) and it owns runtime-mutated state, which per state doctrine (guide §5) belongs in an owned object, never bare globals.

**Approach.** Move-then-shape, two separate units: (1) byte-verbatim move of the block into `chat_nudge.py` with the frozen surface re-exported through `forwarder.py` — the parent→sibling import direction, `hashlib`'s import line relocating with its sole reader; (2) the owned-state conversion (`_NudgeStore`), with module-level wrapper functions preserving the production call surface so `chat_sse.py`/`server.py` stay byte-untouched. This is plan A1 of the forwarder campaign (user-confirmed sequencing 2026-11-24): A2 response rewriting, A3 tier resolution, A4 the swap-drain owned-state conversion + extraction follow; A5 (monolith decomposition) is explicitly not planned — forwarder.py plateaus ~1,750 after this plan and the residual is tracked by the refactor-split survey.

**Key decisions.**
- Wrapper-preserving conversion: the four frozen function names (`_retry_nudge_remember`, `_retry_nudge_arm`, `_retry_nudge_messages_bytes`, `_retry_nudge_check`) survive as delegation wrappers over the store methods, so the production callers (`chat_sse.py` ×2 names, `server.py` ×4 + TTL) never change; the only surface edit in the whole plan is step 3's re-export shrink to five names (the two state names' only readers are the tests repointing in the same unit).
- Test-state pokes travel through `forwarder._store` → `chat_nudge._store._entries/_lock` — private-attribute reach-in, the repo's established test style (cf. `forwarder._config_lock` pokes in `test_admin.py`).
- `RETRY_NUDGE_MAX_ENTRIES` and `_retry_nudge_sweep` stay private to the new module (zero external readers measured).

**Alternatives rejected.** Converting state and moving in one step — destroys reviewability (a move that is "except here" cannot be diff-reviewed). Importing `chat_nudge` directly from `chat_sse.py` — a second call-site rewrite with zero benefit while the re-export is free. Splitting A2/A3 into this plan — one cluster per plan.

**Out of scope.** A2–A4 of the campaign; monolith decomposition (A5, declined by user decision 2026-11-24); the runtime_state.py five-globals conversion (A4's successor); any behavior change in nudge semantics (TTL, eviction, digest matching).

## Repo Mode

Public

*Detected at plan creation (2026-11-24, `detect_repo_mode.py`). Determines: plan archival path, commit-message content, staged files.*

## Document Overrides

| Document | Rule Overridden | Reason |
|----------|----------------|--------|

## Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Step 3 red window (coder edit breaks tests the coder may not edit) | suite red between coder and tester halves | documented red interval; one reviewable unit; no commit inside the window |
| Attribute-form re-export divergence (a future rebind of `forwarder._retry_nudge_entries` would desync from the store) | silent state fork | no test or production site rebinds today (measured); step 3 removes the hazard entirely by deleting the module-level names |
| Gate scripts importing proxy modules without isolation | gates could touch the live proxy's trace/state files | every gate sets the spawn-isolation env block before its first proxy import |

## Proposed Changes

Each step includes verification checks tagged with confidence (see Prime Directive 4).
`(auto)` = mechanical, coder self-verifies. `(scripted)` = deterministic multi-step, coder runs provided script.
Every step must have at least one verification check executable by its owner (coder steps: coder checks; tester steps: tester verify; planner steps: Evidence).
Steps MUST use this numbered-list format exactly. The `### Step N:` heading format is deprecated and must not be used.

1. **Step 1:** Create `src/claude_retry_proxy/chat_nudge.py` — module skeleton (docstring + the four whitelisted imports: `hashlib`, `json`, `threading`, `time`) plus forwarder.py lines 275–472 byte-verbatim; `git add` the new file immediately
   → coder verify (auto): file exists, compiles, defines the five functions + two constants + lock + entries
   → coder verify (scripted): `./tmp/verification/2026-11-24-extract-nudge-store-step1.py` — byte-identity against the pinned pre-change literal (forwarder.py lines 275–472) + import-whitelist AST check (RED pre-change / GREEN post-step-1)
2. **Step 2:** Rewire `forwarder.py` — delete lines 275–474 (the moved 198-line block plus its trailing blank pair; landmarks and seam pinned in Guidance for Coder), delete `import hashlib`, add the seven-name re-export from `.chat_nudge`
   → coder verify (auto): zero `hashlib` in forwarder.py; `python3 -c "import claude_retry_proxy.server"` succeeds
   → coder verify (scripted): `./tmp/verification/2026-11-24-extract-nudge-store-step2.py` — AST undefined-name sweep (full local scope) + seven-name frozen-surface resolution + single-from-import + seam check (RED pre-step-2 / GREEN post-step-2)
   → tester verify: full suite passes, count unchanged, nine nudge tests green (unmodified at this step — the step-3 red window repoints 4 of them afterward, by design)
3. **Step 3:** Owned-state conversion in `chat_nudge.py` — `_NudgeStore` (owns `_lock`/`_entries`; methods carry the bodies with only the state bindings and internal sweep calls rewritten), single `_store = _NudgeStore()`, four frozen-name delegation wrappers; forwarder's re-export shrinks to the five surviving names. Red window with the tester repoint — one reviewable unit, no commit inside
   → coder verify (scripted): `./tmp/verification/2026-11-24-extract-nudge-store-step3.py` — class+methods AST, one-store/one-lock/one-dict assembly assertion, no bare state assignments, wrapper delegation shape, `_store` in re-export (RED pre-step-3 / GREEN post-coder-half)
   → tester verify: suite green after repointing the state pokes to `chat_nudge._store._lock`/`._entries` (re-measured at execution: 26 sites in 4 tests); count preserved; assertions unchanged
4. **Step 4:** Doc sync (planner) — CLAUDE.md structure list gains `chat_nudge.py` and drops the nudge inventory from `forwarder.py`'s entry; `git grep -in nudge` across `doc/*.html`, `README.md`, `CLAUDE.md` and update every module pointer the move invalidates; re-quote no line counts
   → Evidence: executed 2026-11-24 — sweep found zero module pointers outside CLAUDE.md (provider-modes/trace-log/test-catalog/configuration/README hits are all behavioral; the "nudge ∧ forwarder" stale-pointer test returned empty); CLAUDE.md edited in three places (structure list: forwarder.py entry drops the store and gains the re-export clause; new chat_nudge.py entry; Refactoring follow-up scope narrows to swap-drain + runtime_state with the nudge half marked landed); post-edit full-suite rerun launched as the final pre-review gate

## Guidance for Planner

Documentation tasks you will execute yourself (not the coder):

- **Files to modify:**
  - `./CLAUDE.md`
  - `./doc/provider-modes.html`
  - `./doc/architecture.html` (only if the grep sweep names it)
  - `./doc/test-catalog.html` (only if tester-side test metadata changes)
- **`.claude/mega-audit-files.json`:** no change — the file does not exist in this repo and this plan declares no audit locations.
- **When:** after the tester round passes (steps land complete), before `## Final Results`.
- **What to sync:** CLAUDE.md `Structure` — new `chat_nudge.py` entry (owned-state store; wrapper surface; never imports its parent), `forwarder.py` entry loses "the chat retry-nudge store" from its inventory; `doc/provider-modes.html` — module pointers in the unfinished-turn/nudge sections; the doc-sync sweep is `git grep -in nudge -- '*.md' '*.html' 'doc/**'` plus identifier sweep for `RETRY_NUDGE_|_retry_nudge_` — every hit either keeps pointing at a still-true statement or is edited; no exact counts quoted anywhere (test counts, line counts).

## History

One row per event (spec revision / mega-audit / review / implementation round). Conclusion = one-sentence outcome or what changed. Dismissed = compact dismissed-findings list for the reviewer — verbatim issue slugs linked as `[<slug>](<report-path>)`, no prose-only entries (the update-and-commit cross-ref and the reviewer both match these cells verbatim). Link to report files; never restate findings inline.

| Date | Event | Conclusion | Dismissed |
|------|-------|------------|-----------|
| 2026-11-24 | Review (Phase 6) | Verdict: **Issues found — non-blocking** — zero Critical, zero Warning, 3 Readability Suggestions; all plan-nominated checks verified positive (callers byte-untouched, one lock/one table, five-name surface, move contract re-proven against HEAD, test diff access-path-only); ready to commit from a code-quality standpoint ([review report](./tmp/reports/2026-11-24-extract-nudge-store-review-2026-11-24.json)) | [review-import-order](./tmp/reports/2026-11-24-extract-nudge-store-review-2026-11-24.json), [review-wrapper-docstrings](./tmp/reports/2026-11-24-extract-nudge-store-review-2026-11-24.json), [review-docstring-store-phrasing](./tmp/reports/2026-11-24-extract-nudge-store-review-2026-11-24.json) |
| 2026-11-24 | Implementation round (tester) 1 — red window closed | SUCCESS: 26 poke sites in 4 tests repointed to `chat_nudge._store._lock/_entries` (assertions byte-identical, only access paths changed); step-3 gate 17/17; move contract independently corroborated against HEAD; suite **550/550 green**, count preserved, all nine nudge tests passing; two interim spawn-isolation failures were this plan's own tmp/verification helper scripts tripping the corpus checker — fixed in the tester's lane by prepending the canonical isolation block (checker/security test untouched); tester's two stale-advisory findings on the plan's verify lines fixed in this revision ([tester report](./tmp/reports/2026-11-24-extract-nudge-store-tester-2026-11-24.json)) | — |
| 2026-11-24 | Implementation round (coder) 2 — steps 1–3 completed, red window open | All three coder steps landed; gates green at their steps, unedited (gate 1 6/6 incl. byte-identity, gate 2 9/9, gate 3 15/15); red window open — 26 attribute-form poke sites in 4 tests (plan's ~10-in-6 was stale; plan mandated re-measurement); no commit made, per the red-interval doctrine; coder filed a non-blocking plan-text issue (cut range vs seam off-by-two + lifecycle anchor error), repaired in this revision; forwarder.py now 1,746 lines ([coder report](./tmp/reports/2026-11-24-extract-nudge-store-coder-2026-11-24.json)) | — |
| 2026-11-24 | Implementation round (coder) 1 — blocked pre-edit; plan revised | Round exited 0 with **zero source edits**: the coder's pre-implementation gate-satisfiability probe found step 3's shape incompatible with the step-2 re-export (un-prefixed wrapper names + deleted state names ⇒ package ImportError; gate 3 had no runtime check and would report GREEN on the broken package); revision: frozen-name wrappers, re-export shrinks to five names at step 3, gate 3 gains five-name (f) + runtime-assembly (g) checks; gate 3 re-calibrated RED, gate 2 regression-checked RED ([issue report](./tmp/reports/2026-11-24-extract-nudge-store-step3-frozen-surface-contradiction.json)) | — |
| 2026-11-24 | Baseline | First suite run 549/550 (1 failure, name lost to a truncating pipe that also masked the exit code); full-log rerun **550/550 green, exit 0** — operative baseline; transient unexplained, dispositioned if it recurs with a name | — |
| 2026-11-24 | Gate authoring + calibration | Three step gates written to `./tmp/verification/` and proven RED on the pre-change tree; gate-2's AST sweep teeth+satisfiability probes pass (7 undefined-name patterns caught incl. module-level lambdas and nested defs; clean module passes); calibration found and fixed one lambda-visitor gap plus two probe-data bugs — the sweep itself needed the lambda fix, the probes were wrong twice | — |
| 2026-11-24 | Initial plan | Surveyed 51,708 lines across src/scripts/tests; forwarder.py is the sole code file over threshold; A1 nudge-store extraction drafted per the refactor-split doctrine (move-then-shape, frozen surface measured) | — |

## Plan Metadata

Fenced ```json block — the machine contract read by `parsePlanContext` (JSON-first, regex fallback). **Update it on every revision.**

```json
{
  "plan_id": "2026-11-24-extract-nudge-store",
  "steps": ["Step 1: Create chat_nudge.py — block moved byte-verbatim", "Step 2: Rewire forwarder.py — delete block, re-export frozen surface, relocate hashlib", "Step 3: Owned-state conversion — _NudgeStore with delegation wrappers", "Step 4: Doc sync (planner)"],
  "coder_files": ["src/claude_retry_proxy/chat_nudge.py", "src/claude_retry_proxy/forwarder.py"],
  "tester_files": ["tests/test_chat_sse.py"],
  "doc_files": ["CLAUDE.md", "doc/provider-modes.html"],
  "verification_scripts": ["./tmp/verification/2026-11-24-extract-nudge-store-step1.py", "./tmp/verification/2026-11-24-extract-nudge-store-step2.py", "./tmp/verification/2026-11-24-extract-nudge-store-step3.py"],
  "retire_inventory": ["./tmp/reports/2026-11-24-extract-nudge-store-coder-2026-11-24.json", "./tmp/reports/2026-11-24-extract-nudge-store-tester-2026-11-24.json", "./tmp/reports/2026-11-24-extract-nudge-store-review-2026-11-24.json", "./tmp/verification/2026-11-24-extract-nudge-store-step1.py", "./tmp/verification/2026-11-24-extract-nudge-store-step2.py", "./tmp/verification/2026-11-24-extract-nudge-store-step3.py", "./tmp/verification/2026-11-24-extract-nudge-store-apply1.py", "./tmp/verification/2026-11-24-extract-nudge-store-apply2-cut.py", "./tmp/verification/2026-11-24-extract-nudge-store-apply3-check.py", "./tmp/verification/2026-11-24-extract-nudge-store-tester-head-identity.py", "./tmp/verification/__pycache__"],
  "repo_mode": "Public",
  "document_overrides": []
}
```

## Audit Accumulation

*Counters reset when mega-audit runs. Used by Phase 5 entry trigger.*

| Counter | Value | Last Updated |
|---------|-------|--------------|
| issues_resolved_since_audit | 2 | 2026-11-24 |
| steps_changed_since_audit | 4 | 2026-11-24 |
| files_changed_since_audit | 0 | 2026-11-24 |

## Documentation

- Design doctrine: `/refactor-split` command + `~/.claude/guides/refactor-split-guidance.md` (utility-cluster admission, state doctrine §5, move mechanics §7, gate disciplines §6).
- Campaign context: project CLAUDE.md `## Refactoring` (steps 1–8 landed; the owned-state follow-up this plan advances for the nudge half).
- The suite baseline is recorded in the first implementation round's History row.

## Final Results

**Status: COMPLETED** (2026-11-24)

### What was built

The chat retry-nudge marker store moved out of `forwarder.py` (1,944 → 1,746 lines) into the new leaf module `src/claude_retry_proxy/chat_nudge.py`, in two reviewable units: (1) the 198-line block (forwarder.py lines 275–472) moved byte-verbatim behind a frozen-surface re-export, `import hashlib` relocating with its sole reader; (2) the owned-state conversion — `_NudgeStore` owning the lock and the bounded single-use entry table as a `_store` singleton, with the four frozen-name delegation wrappers (`_retry_nudge_remember`/`_retry_nudge_arm`/`_retry_nudge_messages_bytes`/`_retry_nudge_check`) keeping `chat_sse.py` and `server.py` byte-untouched, and forwarder's re-export shrunk to the five surviving names (`_retry_nudge_lock`/`_retry_nudge_entries` retired from the surface; their only readers, 26 test poke sites, repointed to `chat_nudge._store` in the same reviewable unit). This lands the nudge half of the CLAUDE.md-named owned-state-object follow-up; the open scope is now forwarder's swap-drain state + `runtime_state`'s five globals. Plan A1 of the user-confirmed forwarder campaign (A2 response rewriting, A3 tier resolution, A4 swap-drain conversion follow; A5 monolith decomposition declined).

### Steps completed

All four. Step evidence: gate 1 GREEN 6/6 after step 1 (byte-identity vs the pinned 198-line literal); gate 2 GREEN 9/9 after step 2; gate 3 GREEN 15/15 after the coder's half and 17/17 at the tester's close; step 4 executed by the planner (sweep evidence in the step's Evidence line). Gates were never edited between RED calibration and GREEN runs. Gates 1 and 2 are step-scoped and FAIL against the final tree only on what step 3 deliberately reshaped — by design, not regressions.

### Test results

- Tester round: suite **550/550 green** (exit 0), count preserved, all nine nudge-behavior tests passing; repoint diff = 30 lines (26 pokes + 4 import lines), zero assertion lines touched, no store rebinding.
- Planner post-doc-sync rerun: **550/550 green** (exit 0) — validates the CLAUDE.md edits against the suite's doc tests.
- Baseline: 550/550 (a first run's single failure was an unobserved transient; see History, Baseline row).

### Review verdict

**Issues found — non-blocking** (Sonnet reviewer, 2026-11-24): zero Critical, zero Warning, 3 Readability Suggestions (recorded in the Review History row's Dismissed cell). All plan-nominated checks verified positive: production callers byte-untouched with runtime identity confirmed; exactly one lock and one entry table; `_store` absent from the re-export; the move contract mechanically re-proven against `git show HEAD:` lines 275–472; the test diff access-path-only. Reviewer self-assessment: high confidence, converged.

### Documentation updated

`CLAUDE.md` (three places: structure list — forwarder.py entry + new chat_nudge.py entry; Refactoring follow-up scope narrowed to the swap-drain + runtime_state halves). The sweep found zero module pointers to update in `doc/*.html` or `README.md` — all nudge references there are behavioral.

### Known caveats

1. **Commit staging (reviewer hunch, load-bearing for the commit act):** the git index holds the STEP-1 revision of `chat_nudge.py` (211 lines, no `_NudgeStore`/`_store`); the step-3 conversion sits unstaged. `/update-and-commit` MUST re-add the working-tree file before committing — an index-only commit lands a tree whose repointed tests fail with AttributeError.
2. Reviewer Suggestions (3, non-blocking): the `.chat_nudge` import breaks the relative-import block's alphabetical order; the four wrappers carry no docstrings (semantics live on the methods; `help()` on the cross-module surface is empty); forwarder's module docstring phrasing could suggest `forwarder._store` exists. Deferred as improvements — foldable into a later campaign round.
3. `tmp/verification/__pycache__/` is compiled residue from the helper scripts; recorded in `retire_inventory` for the terminal sweep.
4. Two standing deferrals (`admin-body-read-timeout`, `sink-warning-in-process-unit-tests`) predate this plan, are unrelated to it, and remain open on disk.

### Issue Log final state

Both plan-scoped issues Resolved (planner, plan-text repairs): `step3-frozen-surface-contradiction` (round 1, caught by the coder's pre-implementation gate-satisfiability probe) and `step2-cut-range-vs-seam` (round 2, non-blocking). Their report files retire via `/update-and-commit` Step 9.6 routing, not the terminal sweep.
