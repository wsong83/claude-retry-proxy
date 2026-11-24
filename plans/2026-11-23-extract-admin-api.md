# Plan: Extract the admin surface from server.py into admin_api.py with a runtime_state.py state leaf

**Plan ID:** 2026-11-23-extract-admin-api
**Created:** 2026-11-23

<!-- ## Immediate Actions: absent from initial plans. Populated by /update-plan for revised plans. -->

## Issue Log

| Issue | Status | Found | Resolved | Resolved By |
|-------|--------|-------|----------|-------------|
| 2026-11-24-extract-server-lifecycle cross-reference — server.py lands ≈1,040 lines — still over threshold (corrected estimate from the ≈990 first quoted). Full retirement needs the server-lifecycle extraction (`main` + `_ProxyHTTPServer`), which this plan names as the follow-up rather than batching (one cluster per plan). | Resolved | 2026-11-24 | 2026-11-24 | plan 2026-11-24-extract-server-lifecycle — performed exactly that extraction: `run_server(handler_class)` + the two classes moved into `lifecycle.py`; server.py dropped below the 1,000-line code threshold (770 lines at round exit), completing the threshold retirement the caveat named. |

## Guidance for Coder

**Files to modify (source only):**

| File | Change |
|---|---|
| `src/claude_retry_proxy/nesting.py` | receives `_nesting_limit_message` (verbatim move) |
| `src/claude_retry_proxy/runtime_state.py` | **new** — five process globals + `heartbeat_loop` |
| `src/claude_retry_proxy/admin_api.py` | **new** — `AdminHandlerMixin`, admin helpers, admin constants |
| `src/claude_retry_proxy/server.py` | cut moved blocks; mixin composition; dispatch stubs; attribute-form state reads; import relocation |
| `src/claude_retry_proxy/safety.py` | one docstring pointer update (L10) |

Never touch `tests/`, `doc/`, `CLAUDE.md`, or `README.md`.

**Base commit for byte-identity:** `8e56a93` (`8e56a9303ed76d5184ac51ec59b54bb81238dfd4`). All "BASE" references below mean `git show 8e56a93:<path>`. The tree was clean at plan creation; line numbers below are BASE line numbers.

### Move inventory (verbatim)

**To `runtime_state.py`** (each block moves with its comment lines exactly as written):

| BASE server.py lines | Content |
|---|---|
| 62–63 | `_current_config = None  # Set at startup after validation` / `_config_path = None  # Path to config.json, set at startup` |
| 76–78 | `_startup_state` + its 2-line comment |
| 80–82 | `_vendors` + its 2-line comment |
| 159–161 | `_shutting_down` + its 2-line comment |
| 190–192, 194–202 | `# Heartbeat thread` banner (3 lines) + `heartbeat_loop` |

**To `admin_api.py`:**

| BASE server.py lines | Content |
|---|---|
| 65–73 | `_CARRIED_MODELS_KEYS` + its 5-line comment (the one definition both admin sites read) |
| 85–87 | `# Admin page and validation` + `_admin_html_cache` + `ADMIN_BODY_LIMIT` |
| 90–97 | `_load_admin_html` |
| 100–117 | `_validate_csrf_origin` |
| 649–772 | do_GET admin branches ×5 (page L650–668, config L671–700, swap-status L706–734, providers L737–748, providers-detail L751–772) |
| 782–1251 | do_POST admin branches ×3 (shutdown L783–813, switch L816–1072, reload L1075–1251) |

**To `nesting.py`:**

| BASE server.py lines | Content |
|---|---|
| 164–187 | `_nesting_limit_message` (docstring + body, self-contained — reads only nesting's own constants) |

**Branch→method conversion (the sanctioned mechanical transformation):** each branch's `if self.path == …:` guard line and any comment lines *above* the guard (e.g. `# Admin page` L649, `# Admin API: get config` L670, the 4-line swap-status preamble L702–705, `# Admin shutdown…` L782, `# Admin API: switch tiers` L815, `# Admin API: reload config from disk` L1074) **stay in server.py as dispatcher comments**; the branch body (everything from the `if` line's suite onward, including internal comments like `# localhost-only check`) moves into a new method on `AdminHandlerMixin`, dedented one level, **byte-identical except the pinned delta table below**. Trailing bare `return` lines stay inside the methods. No method docstrings are added.

**Route → method mapping:** page → `_admin_handle_page`; config → `_admin_handle_config`; swap-status → `_admin_handle_swap_status`; providers → `_admin_handle_providers`; providers-detail → `_admin_handle_providers_detail`; shutdown → `_admin_handle_shutdown`; switch → `_admin_handle_switch`; reload → `_admin_handle_reload`.

### Pinned delta table — moved bodies (21 line edits total: 20 qualifications + 1 deleted global)

Rule: bare quartet names become `runtime_state.<name>` (token-level replacement, no re-punctuation); the `global _shutting_down` line is deleted. Everything else is byte-locked.

| Route | BASE line | BASE text (dedented) → NEW text |
|---|---|---|
| config | 690 | `payload = json.dumps(_current_config).encode("utf-8")` → `payload = json.dumps(runtime_state._current_config).encode("utf-8")` |
| providers | 746 | `providers = list(_vendors.keys()) if _vendors else []` → `providers = list(runtime_state._vendors.keys()) if runtime_state._vendors else []` |
| providers-detail | 761 | `for name, vendor in (_vendors or {}).items():` → `for name, vendor in (runtime_state._vendors or {}).items():` |
| shutdown | 797 | **DELETE** the line `global _shutting_down` |
| shutdown | 798 | `if _shutting_down:` → `if runtime_state._shutting_down:` |
| shutdown | 801 | `_shutting_down = True` → `runtime_state._shutting_down = True` |
| switch | 937 | `provider_names = set(_vendors.keys())` → qualified |
| switch | 944 | `validated_models = _current_config.get("models") or {}` → qualified |
| switch | 964 | `names = vendor_key_names(_vendors[provider])` → qualified |
| switch | 1012 | `live_models = _current_config.get("models") or {}` → qualified |
| switch | 1034 | `"models": _current_config.get("models", {}),` → qualified |
| switch | 1037 | `if _key in _current_config:` → qualified |
| switch | 1038 | `new_config[_key] = _current_config[_key]` → qualified |
| switch | 1042 | `write_config(_config_path, disk_config)` → qualified |
| switch | 1044 | `_current_config = new_config` → `runtime_state._current_config = new_config` |
| reload | 1094 | `models_doc = load_models_document(models_path_for(_config_path))` → qualified |
| reload | 1115 | `"tiers": _current_config.get("tiers", {}),` → qualified |
| reload | 1128 | `models_path = models_path_for(_config_path)` → qualified |
| reload | 1149 | `provider_names = set(_vendors.keys())` → `provider_names = set(runtime_state._vendors.keys())` |
| reload | 1151 | `for name, v in _vendors.items()}` (the `provider_keys` comprehension) → `for name, v in runtime_state._vendors.items()}` |
| reload | 1237 | `_current_config = candidate` → `runtime_state._current_config = candidate` |

### Stay-behind table (do NOT move)

| BASE lines | Name | Why it stays |
|---|---|---|
| 774–777 | do_GET default 404 | the handler's Anthropic-surface fallback for every non-admin GET — fails the deletion test for the admin cluster |
| 1253–1460 | do_POST client path | the request path |
| 272–646, 1462–1464 | handler core methods | `send_response`, `_send_response`, `_stream_upstream_response`, `_sse_event`, `_stream_response_sse_fallback`, `_log_client_disconnect`, `do_OPTIONS`, `log_message` |
| 125–156 | `_BestEffortStderr` | stderr guard installed by `main` |
| 120–122 | `sinks.configure(...)` | sinks bootstrap (module import + main) |
| 255–267 | `_crlf_safe` | response-path guard used by staying methods |
| 209–248 | `forward_request` | forward entry (re-reads state attribute-form, 2 pinned sites) |
| 1471–1494, 1497–1686 | `_ProxyHTTPServer`, `main` | server lifecycle — the named follow-up extraction |
| 49–59 | forwarder imports except `_drain_for_swap` | frozen surface + staying readers (see Frozen-surface evidence) |

**Frozen-surface evidence lines (do not "clean up" these imports):**
- `_retry_nudge_arm` / `_retry_nudge_check` / `_retry_nudge_messages_bytes` / `_retry_nudge_remember`, `compute_delay`, `compute_jittered_delay`, `_rng`, `_rewrite_json_response`: each occurs in BASE server.py only on the import line — zero production readers — but tests import them **from server** (`tests/test_unit.py` L26 `from claude_retry_proxy.server import compute_jittered_delay, compute_delay, _rng, SETTINGS`; `srv._retry_nudge_remember` ×7 across the suite). They stay imported in server.py.
- `MAX_JSON_NESTING_DEPTH`: its only production reader was `_nesting_limit_message` (moved in Step 1), but `srv.MAX_JSON_NESTING_DEPTH` has 1 test reader (tests/test_admin.py). Retained in server.py's nesting import with this evidence.
- `write_state`: heartbeat moves out, but `main()` (BASE L1618) remains a production reader and `srv.write_state` has 3 test readers (tests/test_trace.py ×2, tests/test_config_keys.py ×1). Stays — no action.
- `_ADMIN_NAME_RE` (safety import): zero production readers in BASE server.py even before this plan (pre-existing dead import). Left untouched by this plan — removing it is unrelated cleanup; a future hygiene plan may retire it.
- `_drain_for_swap` is the exception: its only production readers were the admin branches (now in admin_api). It is **removed from server.py's forwarder import** and imported by admin_api.py; tests repoint their stubs to `admin_api._drain_for_swap` (Step 5).

**Import relocations (import follows its readers — sole reader moved):**
- server.py's config import shrinks to `load_config, validate_config` (both still read by `main`); `write_config` (switch L1042), `load_models_document` (reload L1094), `models_path_for` (reload L1094/L1128) relocate — zero test readers (`srv.write_config` etc.: grep-verified zero).
- server.py's safety import drops `_validate_admin_name` (switch branches only; zero test readers) and keeps `_ADMIN_NAME_RE` (see evidence above).
- server.py's nesting import drops `_REPAIR_MAX_NODES` / `_REPAIR_MAX_OFFSET` (sole reader moved in Step 1; zero test readers) and adds `_nesting_limit_message`.
- admin_api.py and runtime_state.py import what their bodies read (whitelists pinned above / in Step 2).

### Import whitelists (pinned exactly; enforced by the gates)

`runtime_state.py` (complete file header):
```python
import time

from .sinks import write_state
```

`admin_api.py` (complete import block; module name sorted, then `from .` sorted):
```python
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
```

`server.py` import deltas: add `from . import admin_api`, `from . import runtime_state`, `from .admin_api import AdminHandlerMixin`; extend `from .nesting import (...)` (add `_nesting_limit_message`, drop `_REPAIR_MAX_NODES`/`_REPAIR_MAX_OFFSET`); shrink `from .config import (...)` to `load_config, validate_config`; shrink `from .safety import ...` to `_ADMIN_NAME_RE`; remove `_drain_for_swap` from `from .forwarder import (...)`. No other import changes.

**`git add src/claude_retry_proxy/runtime_state.py` and `src/claude_retry_proxy/admin_api.py` the moment each file exists** (untracked files do not survive resets/cleans).

### Module-surface count table

| Kind | Exact count |
|---|---|
| Behavioral changes | **0** (byte-equivalent relocation; suite behavior identical) |
| Module-surface — new module `admin_api.py` | 1 class (`AdminHandlerMixin`) with 8 methods + 2 functions (`_load_admin_html`, `_validate_csrf_origin`) + 3 module constants (`_admin_html_cache`, `ADMIN_BODY_LIMIT`, `_CARRIED_MODELS_KEYS`) = 14 names |
| Module-surface — new module `runtime_state.py` | 5 globals + 1 function (`heartbeat_loop`) = 6 names |
| Module-surface — `nesting.py` | +1 name (`_nesting_limit_message`) |
| Module-surface — `server.py` | −3 module functions (`_load_admin_html`, `_validate_csrf_origin`, `heartbeat_loop`); −8 module constants (`_current_config`, `_config_path`, `_vendors`, `_shutting_down`, `_startup_state`, `_admin_html_cache`, `ADMIN_BODY_LIMIT`, `_CARRIED_MODELS_KEYS`); −1 forwarder import name (`_drain_for_swap`); +3 imports (`admin_api`, `runtime_state`, `AdminHandlerMixin`); +1 MRO base; +8 dispatch calls; `_nesting_limit_message` remains resolvable via the nesting import |
| Implementation changes | 21 pinned line edits in moved bodies (20 qualifications + 1 deleted `global`, table above); 17 pinned line edits in staying server.py code (14 qualifications + 2 deleted `global` lines + 1 thread-target, table in Step 4); 4 import-set relocations (config −3 names, safety −1, nesting −2+1, forwarder −1); 1 docstring pointer in safety.py L10; 2 new module docstrings |

### Red window

Steps 1–3 are green at every boundary (each new module is created unused; the suite stays green; commit per step). **Step 4 opens the red window**: the moment server.py cuts the quartet, tests patching `srv._current_config` / `srv._vendors` / `srv._config_path` / `srv._shutting_down` / `srv._startup_state` / `srv._drain_for_swap` / `srv.heartbeat_loop` / `srv.time` (heartbeat tests) fail loudly. **Steps 4 and 5 are one reviewable unit: do not commit inside the red window.** Commit after Step 5 closes it with the suite green.

### Step-by-step

1. **Step 1:** Move `_nesting_limit_message` (BASE server.py L164–187) verbatim into `nesting.py`; extend server.py's `from .nesting import (...)` with `_nesting_limit_message`. No other change. Tree stays green (`test_nesting.py` imports it from `claude_retry_proxy.server`, which still resolves via the import).
   → coder verify (auto): `nesting.py` defines `_nesting_limit_message`; server.py has no module-level def of it but imports it from `.nesting`.
   → coder verify (scripted): `python ./tmp/verification/2026-11-23-extract-admin-api-step1.py` exits 0 (carries the canonical isolation block — all four gate scripts do).
   → tester verify: suite green; `test_nesting.py` passes unmodified.

2. **Step 2:** Create `src/claude_retry_proxy/runtime_state.py`: module docstring (new text: the §5 runtime-mutable state home, sibling to settings.py), the pinned import block, the five global blocks and `heartbeat_loop` moved verbatim per the move inventory (comment lines included, order preserved as listed). **`git add` it immediately.** Nothing imports it yet — tree stays green.
   → coder verify (auto): the five assigns and `heartbeat_loop` present; import block matches the whitelist.
   → coder verify (scripted): `python ./tmp/verification/2026-11-23-extract-admin-api-step2.py` exits 0.
   → tester verify: step 2 gate exits 0 (carries the canonical isolation block).

3. **Step 3:** Create `src/claude_retry_proxy/admin_api.py`: module docstring (new text), the pinned import block, the moved helpers/constants verbatim, and `AdminHandlerMixin` holding the eight route methods — bodies byte-identical to the BASE branch suites except the pinned 21-line delta table (20 qualifications + 1 deleted `global`). **`git add` it immediately.** Nothing imports it yet — tree stays green.
   → coder verify (auto): the 8 methods exist on the class; the three constants and two helpers exist at module level.
   → coder verify (scripted): `python ./tmp/verification/2026-11-23-extract-admin-api-step3.py` exits 0.
   → tester verify: step 3 gate exits 0.

4. **Step 4:** Rewire and cut `server.py` — **the red window opens here; do not commit until Step 5 closes it.**
   a. Import deltas (whitelist above).
   b. `class ProxyHandler(AdminHandlerMixin, ChatSSEHandlerMixin, http.server.BaseHTTPRequestHandler):`
   c. Replace each admin branch with its dispatcher comment + guard + delegation:
      `if self.path == "<route>":` → `return self._admin_handle_<route>()` (8 sites).
   d. Delete the moved module-level blocks and the moved branch ranges. Re-derive every range boundary by AST (`lineno`/`end_lineno` re-derived on the tree as it stands immediately before cutting — never compute shifts by hand; a zero-length range or a drifted landmark is a stop-and-report). **Blank-line mechanic:** delete each moved block together with its entire adjacent blank run, then ensure exactly two blank lines between surviving top-level statements (the normal module spacing) — the gate's "no 3+ consecutive blank lines" check is the POST-CONDITION the mechanic must satisfy, not a warning.
   e. Attribute-form qualifications in staying code (17 pinned edits: 14 qualifications + 2 deletions + 1 thread-target):
      - L235 `_current_config` → `runtime_state._current_config`; L236 `_vendors` → `runtime_state._vendors` (in `forward_request`'s snapshot block)
      - L1387 `_current_config` (the `_resolve_extra_request_headers(...)` argument); L1416 `_current_config`; L1419 `_vendors.get(provider)`; L1421 `_vendors[provider]` (client-path trace reads — L1421 sits inside `try: … except Exception: pass`, where an unqualified NameError would be swallowed and every request's trace entry would silently lose its `key` field; this is why it is pinned individually)
      - L1515 **DELETE** `global _current_config, _vendors, _config_path, _startup_state` (main has no `global` left)
      - L1560 `_vendors = load_keys_file(...)` → `runtime_state._vendors = ...`; L1567 `_current_config = load_config(...)` → qualified; L1568 `_config_path = config_path` → qualified; L1625 `_startup_state = state` → qualified
      - L1577 `provider_names = set(_vendors.keys())` → qualified; L1578 `provider_keys = {name: vendor_key_names(v) for name, v in _vendors.items()}` → qualified; L1579 `errors = validate_config(_current_config, ...)` → qualified (unqualified, these are NameError during startup — the proxy cannot boot)
      - L1646 `", ".join(_vendors.keys())` in the startup `Providers:` banner → qualified
      - L1641 `threading.Thread(target=heartbeat_loop, ...)` → `target=runtime_state.heartbeat_loop`
      - L780 **DELETE** `global _current_config` (do_POST's first line)
   f. safety.py L10: `` ``_validate_csrf_origin`` (server.py) `` → `` ``_validate_csrf_origin`` (admin_api.py) `` (the `_crlf_safe` pointer stays).
   → coder verify (auto): `python -m compileall -q src/claude_retry_proxy` succeeds.
   → coder verify (scripted): `python ./tmp/verification/2026-11-23-extract-admin-api-step4.py` exits 0 (import whitelists incl. the relocated config/nesting/safety sets, MRO, dispatch stubs, zero bare quartet names, zero `global` statements in `main`/`do_POST`, undefined-name closure, qualification sites — client path asserts 2 config + 2 vendors reads —, safety.py pointer, runtime MRO/identity assertions under the isolation block).
   → tester verify: deferred to Step 5 (red window).

5. **Step 5:** Repoint test bindings to the new homes (tester-owned; closes the red window). Only these names move — every other `srv.*` binding is untouched. **Completeness method: grep the six names across all of `tests/` — do NOT trust the per-file list or AttributeError** (assignment-form patches like `srv._startup_state = X` never raise; they silently create a dead module attribute, so a missed write-form patch keeps the test passing against a binding the production code never reads). Per-name totals (grep-verified at BASE): `srv._current_config` 30, `srv._vendors` 14, `srv._config_path` 11, `srv._shutting_down` 10, `srv._startup_state` 9, `srv._drain_for_swap` 10, `srv.heartbeat_loop` 2, plus the heartbeat clock `srv.time` 6 sites (three save/restore tuples + two assignments, tests/test_trace.py L1483–1643). Per-file concentration: `tests/test_admin.py` (49 five-name sites + 10 `_drain_for_swap`), `tests/test_trace.py` (16 five-name sites + 2 `heartbeat_loop` + 6 `time`), `tests/test_retry_streaming.py` (6), `tests/test_config_keys.py` (3 — `test_heartbeat_preserves_state`, L338/341/342). **Dynamic-lookup sites:** six save/restore blocks use string-keyed `getattr(srv, name)` / `saved_srv[...]` dict patterns (test_admin.py ~L2866, 3200, 3325, 3433, 3568, 3665) — invisible to literal substitution; grep `getattr(srv` and `saved_srv\[` and repoint to `getattr(runtime_state, name)` / a runtime_state-keyed dict.
   → tester verify: full suite green (`python tests/test_claude_proxy.py`), zero collection errors, suite count identical to the pre-round run; a `git grep -n 'srv\.\(_current_config\|_vendors\|_config_path\|_shutting_down\|_startup_state\|_drain_for_swap\|heartbeat_loop\)' tests/` returns zero matches; `python scripts/check_spawn_isolation.py` still reports the corpus clean. The suite run is necessary but NOT sufficient (silent write-form patches) — the grep is the completeness check.

6. **Step 6:** Behavioral verification sweep.
   → tester verify: re-run all four gate scripts (all exit 0); run the full suite once more end-to-end; confirm the admin-surface behaviors are covered by the existing green tests (switch/reload/swap-status/providers/CSRF/403/404 paths — no behavior was removed, so no new tests are required; any failure is a repoint miss or a move defect, not missing coverage).

7. **Step 7:** Documentation sync (planner-owned — see Guidance for Planner).
   → planner Evidence: `git grep` across `doc/`, `CLAUDE.md` for the changed identifiers (`_current_config`, `_vendors`, `_drain_for_swap`, `heartbeat_loop`, `AdminHandlerMixin`, MRO text) returns only post-sync references; each updated doc page carries the structure entries.

### Gate calibration (final — pre-change tree at 8e56a93, measured 2026-11-23, post mega-audit revision)

- **RED (all four, untouched tree):** step1 exit 1 (4 FAIL: nesting def absent, server def present, import missing, runtime identity; 2 PASS must-hold) · step2 exit 1 (1 FAIL: module missing) · step3 exit 1 (1 FAIL: module missing) · step4 exit 1 (FAILs exactly on not-yet-met conditions; the full-scope closure is GREEN pre-change — satisfiability on the real tree — and PASSes compileall, dispatcher comments, no-value-import, blank parity).
- **Satisfiability probe ×8 (round-trip):** every route's BASE suite → pinned transforms → synthetic method → re-extraction via the gate's own logic round-trips exactly (page 18, config 29, swap-status 28, providers 11, providers-detail 21, shutdown 30→29 — the deleted `global` line —, switch 256, reload 176).
- **Synthetic-GREEN probe (post-audit):** a full post-change tree was constructed from BASE (runtime_state.py from the pinned slices; admin_api.py via the gate's own apply_pinned machinery; post-cut server.py with stubs, deletions, and all 17 staying edits; nesting.py + safety.py updated), and each gate was run against it. Result: every STATIC check passes; the only FAIL per gate is the runtime-import check that requires the real package to carry the new modules (impossible pre-change by construction). This probe exercised the bare-name, qualification-count, import-set, closure, and MRO checks against a built tree — not just the round-trip. The probe run also proved the closure gate's teeth: a probe-construction bug that dropped server.py's keys import was flagged immediately (`unresolved: load_keys_file, read_passphrase_from_stdin, vendor_key_names`).
- **Calibration fixes landed during authoring/audit** (each caught by a probe or RED run, not by inspection): ancestor-scope + dunder resolution in the closures (guide §7.3 trap: `evict_stream`/`_delayed_shutdown` free variables, `__file__`); class-method lookup for `do_GET`/`do_POST` and module-level lookup for `forward_request`/`main`; step2 closure's module-import resolution (`time`/`write_state`); the two reload `_vendors` rows + `_vendors` count 5→7; do_POST vendors read count 1→2; labeled result tuples for the evidence lines.
- Gates are step-local: step N's gate proves step N; earlier gates stay green after later steps (all four are GREEN at the Step 6 sweep).

## Guidance for Tester

**Tests to create:**
- **Permanent:** none. This plan relocates code byte-equivalently; the existing admin/heartbeat/trace/retry tests are the behavioral gate. Creating new tests for relocated behavior would duplicate the suite's existing coverage.
- **Temporary:** none.

**Tests to investigate for retirement:**
- Planner candidates: none — no test exercises removed code; every existing test keeps its behavior (only its patch targets move).
- Tester may identify additional candidates during the repoint; apply the per-test coverage proof rule before claiming any.

**Repoint inventory:** see Step 5 — six moving names, four files, ~92 sites including six string-keyed `getattr(srv, …)` blocks. **Loudness is not guaranteed:** read-form misses raise `AttributeError`, but write-form patches (`srv.<name> = …`) silently create a dead attribute and keep passing. The grep-for-zero-matches check in Step 5 is the completeness proof; the suite run is necessary but not sufficient.

**Verification scripts to create:** none. (Existing test files modified by the repoint — not creations: `tests/test_admin.py`, `tests/test_retry_streaming.py`, `tests/test_trace.py`, `tests/test_config_keys.py`.)

**Red window:** Step 4's cut will leave the tree red against the current tests. That is expected and documented; do not weaken any test to pass it — repoint bindings only.

**Deferred-issue candidate (planner-identified, from the mega-audit):** the admin POST body read (`self.rfile.read(content_length)` after only the `ADMIN_BODY_LIMIT` upper-bound check, BASE L840) has no inbound read timeout — a client that declares ≤64 KB and then stalls holds a worker thread indefinitely. Pre-existing boundary behavior inside a moved branch: per §8 it must NOT be fixed in the move; file it via `/defer-issue` (pre_existing, evidence: BASE server.py L831–840) during the round.

## Summary

**Problem.** `server.py` (1,686 lines) is over the repo's 1,000-line code threshold and holds two distinct concepts: the HTTP forward path (mode dispatch, streaming, SSE) and the admin control plane (the `/admin/` page, five GET API endpoints, three POST endpoints). The admin/handler extraction is the repo's tracked follow-up (CLAUDE.md Future Work; the /refactor-split survey).

**Approach.** Extract the admin surface (≈600 lines of branch bodies + helpers) into `admin_api.py` as an `AdminHandlerMixin` composed into `ProxyHandler` — the exact shape of the ratified chat_sse extraction (plan 2026-11-17-extract-chat-sse, step 7 of the staged decomposition). The moved branches' state cannot stay in server.py (the new module may never import its parent, and `global` binds to the defining module — leaving the globals in server.py would silently fork the live config on the first switch press). A survey of every module-level binding in the package (12 modules) classified all candidates: exactly five process globals (`_current_config`, `_config_path`, `_vendors`, `_shutting_down`, `_startup_state`) plus their maintainer (`heartbeat_loop`) move to a new leaf `runtime_state.py` — the §5 "mutated at runtime" category's module home, sibling to `settings.py` (the resolved-once home); forwarder's swap/nudge state stays protocol-owned; compat already owns its state object; sinks own their pair; SETTINGS must not absorb runtime state. `_nesting_limit_message` (the one shared helper whose callers straddle the cut) relocates to its domain leaf `nesting.py`, keeping the extraction a full two-direction closure.

**Key design decisions.**
- State home chosen by the user over the alternatives (state-in-admin_api vs a thinner bare quartet leaf): the five-global leaf with `heartbeat_loop` is heavier and healthier — a nameable concept (process runtime state + its heartbeat) that later hosts the tracked owned-state conversion, and it keeps the hot forward path depending on a neutral state leaf instead of the admin module.
- Bare-globals relocation (not the §5 owned-object shape) matches the ratified forwarder precedent; owned-object conversion remains the separate named follow-up. Declared in Document Overrides.
- Verbatim-move discipline with two pinned delta classes: 20 `runtime_state.` qualifications + 1 deleted `global` line in moved bodies (21 edits); 14 qualifications + 2 deleted `global` lines + 1 thread-target edit in staying server.py code (17 edits). Everything else byte-identical to BASE `8e56a93`, gate-enforced.
- server.py lands ≈1,040 lines — still over threshold (corrected estimate from the ≈990 first quoted). Full retirement needs the server-lifecycle extraction (`main` + `_ProxyHTTPServer`), which this plan names as the follow-up rather than batching (one cluster per plan).

**Alternatives rejected.**
- *State stays in server.py* — impossible without circular imports; `global` would silently fork the config (the worst failure class this repo guards against).
- *Re-export state through server for test compatibility* — re-exports copy bindings; test writes would diverge from the live binding (the frozen rule from the forwarder extraction: state is never re-exported, attribute-form mandatory).
- *State rides inside admin_api.py* — the hot path would depend on the admin module for its entry snapshot; rejected in favor of the neutral leaf (user decision).
- *`_nesting_limit_message` stays in server.py* — admin_api could not import it (parent direction); nesting.py is its domain leaf (owns every constant it reads), and server's import-back keeps `test_nesting.py` untouched.

**Out of scope.** The server-lifecycle extraction (`main` + `_ProxyHTTPServer`); the owned-state conversion (forwarder swap/nudge + runtime_state's five globals); the ten over-threshold test files (each split is its own plan); any behavior change whatsoever (§8 byte-lock — a defect found in the moved branches becomes a `/defer-issue`, never an in-move fix).

## Repo Mode

Public

*Detected at plan creation (detect_repo_mode.py, 2026-11-23). Determines: plan archival path, commit-message content, staged files.*

## Document Overrides

| Document | Rule Overridden | Reason |
|----------|----------------|--------|
| `~/.claude/guides/refactor-split-guidance.md` §5 | Runtime-mutated state's home is "an owned object with a lock… never a bare module global" | Staged relocation: the five globals move as bare globals into `runtime_state.py` with attribute-form access, exactly the ratified forwarder-extraction pattern (plan 2026-11-16-extract-forwarder); the tracked owned-state conversion follow-up is the sanctioned design change and lands in this module. Mixing the conversion into this verbatim move would violate move-then-shape. |

## Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Red window spans the coder→tester boundary (steps 4–5) | Tree red between rounds; a stall inside the window leaves tests failing | One reviewable unit; no commit inside; the retry rule and assess-and-brief apply if the round dies inside it |
| A missed bare quartet read silently reads a stale/absent binding | `NameError` at request time (loud) or, worst case, reading a qualified binding inconsistently | Step 4 gate: AST walk asserting **zero** bare `Name` nodes of the five names in server.py, plus full-scope undefined-name closure; the same assertion over admin_api.py in Step 3 |
| Qualification drift inside moved bodies (the 21 pinned edits) | A paraphrased qualification diverges from the reviewed delta table | Step 3 gate compares each method body to the BASE suite with only the pinned line diffs allowed; any other diff is a gate failure; the synthetic-GREEN probe exercised the bare-name and count checks against a built post-move admin_api, not only the round-trip |
| Test-repoint misses (~92 sites) | Read-form misses fail loudly (`AttributeError`); **write-form misses are silent** (assignment to a module attribute never raises — the fake installs on a dead binding) | Step 5's grep-for-zero-matches is the completeness check; the suite run is necessary but not sufficient; the six `getattr(srv, name)` blocks are enumerated separately |
| `_drain_for_swap` import removal from server breaks a test-import assumption | Test patches install on a dead binding | Frozen-surface evidence line documents the deliberate relocation; tests repoint in Step 5; the step 4 gate asserts the name's absence from server's import |
| Red-window abort mid-round | Partially rewired tree | The Step 3 commit is the anchor: `git checkout -- src/claude_retry_proxy/server.py` restores it (both new modules are already committed and unused at that point) |

## Proposed Changes

See "Step-by-step" in Guidance for Coder (Steps 1–4, each with `(auto)` + `(scripted)` checks), Guidance for Tester (Steps 5–6), and Guidance for Planner (Step 7). Every step carries at least one verification check executable by its owner.

## Guidance for Planner

Documentation tasks executed by the planner (after the tester round closes green):

- **Files to modify:**
  - `./CLAUDE.md`
  - `./doc/architecture.html`
  - `./doc/operations.html`
  - `./doc/test-catalog.html`
- **`.claude/mega-audit-files.json`:** no declared audit-locations file exists in this repo; nothing to update.
- **When:** after the tester round confirms green (Step 7), before `## Final Results`.
- **What to sync:**
  - `CLAUDE.md`: structure list — add `admin_api.py` and `runtime_state.py` entries; update `server.py` (delegates the admin surface to `AdminHandlerMixin`; reads process state attribute-form from `runtime_state`), `nesting.py` (carries `_nesting_limit_message`), and the chat_sse/server MRO description (`AdminHandlerMixin` → `ChatSSEHandlerMixin` → `BaseHTTPRequestHandler`); Future Work — the admin/handler extraction is done (this plan), name the server-lifecycle extraction (`main` + `_ProxyHTTPServer`) as the follow-up that finishes server.py's threshold retirement, and extend the owned-state conversion's scope note to cover runtime_state's five globals.
  - `doc/architecture.html`: the handler-inheritance line (L56 area) gains the new mixin; the config-swap/heartbeat sections checked for module-home references (the heartbeat section's in-memory-state facts remain true; verify and only touch what names server.py as the state's home).
  - `doc/operations.html`: L348's `_current_config` reference — the name survives (in runtime_state); verify the sentence stays true without edit, adjust only if it names the module.
  - `doc/test-catalog.html`: entries naming moved patch targets — `test_reload_does_not_revert_concurrent_switch` (`_drain_for_swap` monkeypatch → on `admin_api`), `test_admin_switch_rechecks_catalog_after_epoch_move` (same rebind, L715), `test_admin_reload_serialize_failure_500` and `test_admin_config_serialize_failure_500` (`_current_config` → `runtime_state._current_config`), and L709's `test_admin_html_pending_status_styled` sentence "`server.py` emits `config_reload_stale`" → the emitter now lives in `admin_api.py` (or drop the file attribution); heartbeat entries verified for continued truth. The enumeration is not exhaustive by itself — the identifier sweep below is the completeness check.
  - Doc-sync is a sweep: `git grep` every changed identifier (`_current_config`, `_vendors`, `_config_path`, `_shutting_down`, `_startup_state`, `_drain_for_swap`, `heartbeat_loop`, `_nesting_limit_message`, `AdminHandlerMixin`, `_validate_csrf_origin`, `_load_admin_html`, `config_reload_stale` emitter attribution) across `doc/`, `CLAUDE.md`, and docstrings; re-measure any quoted line count before writing.

## History

| Date | Event | Conclusion | Dismissed |
|------|-------|------------|-----------|
| 2026-11-23 | Initial plan | Admin-surface extraction designed with a five-global runtime_state leaf; state home confirmed by user (Option B-plus) after a full package state survey | — |
| 2026-11-23 | Mega-audit (run wf_d9066bbc-3f6, 9 lenses; [report](./tmp/reports/2026-11-23-extract-admin-api-mega-audit-2026-11-23.json)) | 17 High + 14 Medium all fixed in-plan: 7 missed bare-quartet sites pinned (reload L1149/L1151; staying L1421 [silent — swallowed in the trace-key try], L1577–1579, L1646); two unsatisfiable gate checks corrected (step2 closure now resolves imports; step3 `_vendors` 5→7, step4 do_POST vendors 1→2); blank-line deletion mechanic restated (whole-run removal, ≤2-blank post-condition); repoint inventory corrected (4 files, ~92 sites, write-form silence documented, `getattr(srv, …)` blocks enumerated); import relocations pinned with frozen-surface evidence (`write_state`/`MAX_JSON_NESTING_DEPTH` retained, `write_config`/`load_models_document`/`models_path_for`/`_validate_admin_name`/`_REPAIR_*` relocated); doc-sync set grew by two entries (test-catalog L715, L709); synthetic-GREEN probe proves all four gates satisfiable against a built post-change tree. 0 High remain → no re-audit iteration. | [oversight-catcher #11](./tmp/reports/2026-11-23-extract-admin-api-mega-audit-2026-11-23.json) full Rollback section (one-line anchor added to Risks instead); [rule-enforcer #16](./tmp/reports/2026-11-23-extract-admin-api-mega-audit-2026-11-23.json) / [conflict-resolver #22](./tmp/reports/2026-11-23-extract-admin-api-mega-audit-2026-11-23.json) / [edge-case-explorer #30](./tmp/reports/2026-11-23-extract-admin-api-mega-audit-2026-11-23.json) three-entry undercount (superseded — the Medium doc-sync fix enumerates the fourth entry and names the sweep as completeness) |
| 2026-11-23 | Implementation round (coder) — exit 0, [report](./tmp/reports/2026-11-23-extract-admin-api-coder-2026-11-23.json) | Steps 1–4 complete per plan; planner independently re-ran all four gates GREEN (exit 0 ×4); no commit inside the red window — note: no interim commits at all (coder declined per-plan commit-per-step; new modules are `git add`-staged, so the rollback anchor is staging-level, not a commit — accepted, `/update-and-commit` owns commits); `defer-issue-admin-body-read-timeout.json` filed standalone per §8 (no plan row at filing); two plan-prefixed scratch scripts under `./tmp/verification/` (`-gen-admin-api.py`, `-rewrite-branches.py`) are outside `retire_inventory` — to be added at Final Results | — |
| 2026-11-23 | Verification round (tester) — exit 0, [report](./tmp/reports/2026-11-23-extract-admin-api-tester-2026-11-23.json) | SUCCESS: red window closed; Step 5 repoint proven complete by the zero-match grep (`srv.<six names>` → 0 in tests/; the only `getattr(srv` hit is the harness's generic helper); Step 6 suite 546/546 with collection count identical pre/post; four gates re-run GREEN (8/14/39/37 assertions); spawn-isolation corpus initially red on the coder's scratch script — tester added the canonical block in-round, checker now clean; no tests created/weakened/removed; the three documentation discrepancies it listed are exactly the plan's Step 7 doc-sync items | — |
| 2026-11-23 | Review — verdict "Issues found — non-blocking"; [report](./tmp/reports/2026-11-23-extract-admin-api-review-2026-11-23.json) | No Critical, no Warning; all eight measurement obligations CONFIRMED (byte-identity via an independent extractor against BASE 8e56a93; the formerly-missed L1149/L1151/L1421 sites qualified; zero bare state names; import sets exact; test repoint complete beyond the plan's six names; gates 8/14/39/37; suite substituted with targeted 155-test run across six modules + mtime-ordering argument — the reviewer did not re-run the full suite); Step 7 doc sync named as the remaining pre-commit act | [Suggestion #1](./tmp/reports/2026-11-23-extract-admin-api-review-2026-11-23.json) dead `from . import admin_api` import in server.py (pinned by the step4 gate; a future hygiene plan may remove it — removing post-review would invalidate the byte-identity evidence); [Suggestion #2](./tmp/reports/2026-11-23-extract-admin-api-review-2026-11-23.json) `_BestEffortStderr` docstring's print-owner enumeration omits admin_api.py; [Suggestion #3](./tmp/reports/2026-11-23-extract-admin-api-review-2026-11-23.json) runtime_state.py docstring overclaims ("values an admin press swaps" — only `_current_config` is swapped); [Suggestion #4](./tmp/reports/2026-11-23-extract-admin-api-review-2026-11-23.json) `saved_srv` snapshot naming in test_admin.py; [Suggestion #5](./tmp/reports/2026-11-23-extract-admin-api-review-2026-11-23.json) the no-bare-state guarantee lives only in the transient gate — a permanent suite guard is a deferred-improvement candidate for the next plan touching this area |

## Plan Metadata

```json
{
  "plan_id": "2026-11-23-extract-admin-api",
  "steps": [
    "Step 1: Move _nesting_limit_message into nesting.py",
    "Step 2: Create runtime_state.py with the five process globals and heartbeat_loop",
    "Step 3: Create admin_api.py with AdminHandlerMixin and the admin helpers",
    "Step 4: Rewire server.py - mixin composition, dispatch stubs, attribute-form state, import relocation",
    "Step 5: Repoint test bindings to the new module homes",
    "Step 6: Behavioral verification - full suite green with count preserved",
    "Step 7: Documentation sync (planner)"
  ],
  "coder_files": [
    "src/claude_retry_proxy/server.py",
    "src/claude_retry_proxy/nesting.py",
    "src/claude_retry_proxy/admin_api.py",
    "src/claude_retry_proxy/runtime_state.py",
    "src/claude_retry_proxy/safety.py"
  ],
  "tester_files": [
    "tests/test_admin.py",
    "tests/test_retry_streaming.py",
    "tests/test_trace.py",
    "tests/test_config_keys.py"
  ],
  "doc_files": [
    "./CLAUDE.md",
    "./doc/architecture.html",
    "./doc/operations.html",
    "./doc/test-catalog.html"
  ],
  "verification_scripts": [
    "./tmp/verification/2026-11-23-extract-admin-api-step1.py",
    "./tmp/verification/2026-11-23-extract-admin-api-step2.py",
    "./tmp/verification/2026-11-23-extract-admin-api-step3.py",
    "./tmp/verification/2026-11-23-extract-admin-api-step4.py"
  ],
  "retire_inventory": [
    "./tmp/reports/2026-11-23-extract-admin-api-coder-2026-11-23.json",
    "./tmp/reports/2026-11-23-extract-admin-api-tester-2026-11-23.json",
    "./tmp/reports/2026-11-23-extract-admin-api-mega-audit-2026-11-23.json",
    "./tmp/reports/2026-11-23-extract-admin-api-review-2026-11-23.json",
    "./tmp/verification/2026-11-23-extract-admin-api-step1.py",
    "./tmp/verification/2026-11-23-extract-admin-api-step2.py",
    "./tmp/verification/2026-11-23-extract-admin-api-step3.py",
    "./tmp/verification/2026-11-23-extract-admin-api-step4.py",
    "./tmp/verification/2026-11-23-extract-admin-api-gen-admin-api.py",
    "./tmp/verification/2026-11-23-extract-admin-api-rewrite-branches.py"
  ],
  "repo_mode": "Public",
  "document_overrides": [
    "~/.claude/guides/refactor-split-guidance.md §5: runtime-mutated state home is an owned object with a lock, never a bare module global (Reason: staged relocation per the ratified forwarder-extraction precedent; runtime_state.py hosts the tracked owned-state conversion follow-up)"
  ]
}
```

## Audit Accumulation

| Counter | Value | Last Updated |
|---------|-------|--------------|
| issues_resolved_since_audit | 0 | 2026-11-23 |
| steps_changed_since_audit | 0 | 2026-11-23 |
| files_changed_since_audit | 0 | 2026-11-23 |

## Documentation

Operational summary lives in `CLAUDE.md`; the deep reference in `doc/` (indexed by `doc/content.html`). Step 7 reconciles all four synced surfaces after implementation. No supplementary docs are created by this plan.

## Final Results

**Status: COMPLETED** — 2026-11-23

**What was built.** The admin surface moved out of `server.py` into `admin_api.py` (`AdminHandlerMixin`, eight `/admin` route handlers + two helpers + three admin constants, bodies byte-verbatim from BASE `8e56a93` except the 21 pinned moved-body edits); the five process globals + `heartbeat_loop` moved to the new `runtime_state.py` leaf (attribute-form access everywhere, state never re-exported); `_nesting_limit_message` moved to its domain leaf `nesting.py`; sole-reader imports relocated out of server.py (forwarder −1, config −3, safety −1, nesting −2+1) with frozen-surface evidence lines for the retained names; `safety.py`'s docstring pointer updated. `server.py` carries 17 pinned staying-code edits and lands ≈1,040 lines (still marginally over the 1,000 threshold — the named server-lifecycle follow-up retires the remainder). 5 files changed, 2 created; 4 test files repointed (~92 sites), no test created, weakened, or removed; suite collection count identical pre/post.

**Steps:** all 7 complete (coder 1–4; tester 5–6; planner doc-sync 7 — CLAUDE.md structure/MRO/Future-Work, doc/test-catalog.html six patch-target entries, doc/architecture.html handler-composition paragraph; identifier sweep verified; `test_docs.py` 11/11; `check_doc_anchors.py` 272 anchors resolved, no secret shapes).

**Verification:** four step gates GREEN (coder round, re-run by tester, re-run by reviewer: 8/14/39/37 assertions) — each calibrated RED against the pre-change tree and proven satisfiable by a synthetic-GREEN probe; full suite **546 passed / 0 failed** (tester, exit 0), collection count preserved; reviewer independently ran the six touched modules (155/155) and `check_spawn_isolation.py` (clean); repoint completeness proven by zero-match grep including the write-form-silence class.

**Review:** verdict "Issues found — non-blocking" — no Critical, no Warning; 5 Suggestions dismissed (see History); the reviewer's byte-identity confirmation used an independent extractor against BASE.

**Deferred issues** (standalone `defer-issue-*.json`, open on disk — presence means open; no adopting-plan row):
- `defer-issue-admin-body-read-timeout.json` — the admin POST body read (`self.rfile.read(content_length)` after only the `ADMIN_BODY_LIMIT` upper bound) has no inbound read timeout; a client declaring ≤64 KB and stalling holds a worker thread indefinitely. Pre-existing at BASE, §8-excluded from the verbatim move, filed by the coder with reproduction.
- (`defer-issue-sink-warning-in-process-unit-tests.json` is the pre-existing deferral from plan 2026-11-22-sse-scan-ping-first — unrelated to this plan, untouched, still open.)

**Known caveats:** the reviewer's five Suggestions (dead `from . import admin_api` import; `_BestEffortStderr` docstring enumeration; `runtime_state.py` docstring overclaim; `saved_srv` test naming; the no-bare-state guarantee living only in the transient gate) are recorded in the History Dismissed cell as deferred improvements for a future hygiene plan. The reviewer substituted targeted module runs for a full-suite re-run (mtime-ordering argument + the tester's 546/546); the gates' RED profile was measured pre-change and cannot be re-derived without reverting.

**Retirement:** `retire_inventory` (Plan Metadata) lists this plan's ten transient tmp artifacts — four session/mega-audit/review reports and six verification scripts (four gates + the coder's two scratch generators) — for the post-commit sweep. The deferral report above is live and never swept.
