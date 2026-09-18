# Plan: Extract the config/keys family into siblings and single-source CLI validation
**Project:** D:\proj\claude-retry-proxy
**Plan ID:** 2026-09-17-extract-config-keys
**Created:** 2026-09-17

## Immediate Actions

**Coder:** Add `tiers = config.get("tiers", {})` as the first line of the step-6(c) replacement block in `cmd_start` (its reader — the post-spawn tier-print loop — survives outside the cut; see Guidance for Coder step 6(c)). Re-run the step-6 gate. Do not touch tests. Do not re-run step-5's gate — its boundary has passed.

**Tester:** After the coder lands the one-line fix, resume the red-unit round: full suite, updated pins, the two planned permanent tests, the template-flow fold candidates (`test_cli_start_template_created` / `test_config_template_copy`), and the retirement investigation per Guidance for Tester.

## Issue Log

Rows ordered newest-first (latest issues at top). New issues are prepended; resolved issues stay in place with updated status.

| Issue | Status | Found | Resolved | Resolved By |
|-------|--------|-------|----------|-------------|
| [cli-start-tiers-nameerror](./tmp/reports/2026-09-17-extract-config-keys-cli-start-tiers-nameerror.json) | Resolved | 2026-09-18 | 2026-09-18 | [tester](./tmp/reports/2026-09-17-extract-config-keys-tester-2026-09-18.json) |
| [step5-boundary-gate-vs-step7](./tmp/reports/2026-09-17-extract-config-keys-step5-boundary-gate-vs-step7.json) | Resolved | 2026-09-17 | 2026-09-18 | [tester](./tmp/reports/2026-09-17-extract-config-keys-tester-2026-09-18.json) |
| [step6-gate-defaults-attribute-crash](./tmp/reports/2026-09-17-extract-config-keys-step6-gate-defaults-attribute-crash.json) | Resolved | 2026-09-17 | 2026-09-18 | [tester](./tmp/reports/2026-09-17-extract-config-keys-tester-2026-09-18.json) |
| [step2-gate-reexport-name-collision](./tmp/reports/2026-09-17-extract-config-keys-step2-gate-reexport-name-collision.json) | Resolved | 2026-09-17 | 2026-09-18 | [tester](./tmp/reports/2026-09-17-extract-config-keys-tester-2026-09-18.json) |
| [step1-gate-attribute-bug](./tmp/reports/2026-09-17-extract-config-keys-step1-gate-attribute-bug.json) | Resolved | 2026-09-17 | 2026-09-18 | [tester](./tmp/reports/2026-09-17-extract-config-keys-tester-2026-09-18.json) |
| [refactor-split-utility-cluster-doctrine](./tmp/reports/defer-issue-refactor-split-utility-cluster-doctrine.json) | Open | 2026-09-17 | — | — |

## Guidance for Coder

**Files to modify:** `src/claude_retry_proxy/server.py`, `src/claude_retry_proxy/cli.py`, plus three NEW files: `src/claude_retry_proxy/safety.py`, `src/claude_retry_proxy/config.py`, `src/claude_retry_proxy/keys.py`.

**Step-by-step with verification:** each step carries `(auto)` checks the coder self-verifies and `(scripted)` checks run with `python tmp/verification/2026-09-17-extract-config-keys-step<N>.py` from the project root (exit 0 = pass). Tester owns behavioral checks. All line numbers below are the **pre-change tree** (they shift between steps); every range is content-anchored — re-verify the landmark lines before cutting, and stop-and-report if a landmark is missing (guide §5). Steps 1–4 must leave the tree green; steps 5–6 form one red unit with the tester (see bottom). `git add` each new module the moment it exists.

**Move discipline (§5, §7.2):** moved bodies are byte-identical — no renames, formatting, or comment edits inside a moved range except where a step explicitly declares a design change. New files get a module docstring (new text is fine outside moved ranges). Imports follow their readers: an import line whose every reader moved is deleted from the parent; the whitelist below is exhaustive — an import not on it means a plan revision, not a silent addition.

**Gate lifecycle:** each step's scripted gate is a step-local snapshot — run it at its own step boundary only (§7.2). Rerunning an earlier step's gate after later steps have legitimately changed the tree produces stale failures, not regressions (recorded: the step-5 module-top-import check after step 6).

### Module-surface count table

| Step | Behavioral changes | Module-surface changes | Implementation |
|------|--------------------|------------------------|----------------|
| 1 | 0 | server re-exports +2 (`_ADMIN_NAME_RE`, `_validate_admin_name`), −2 defs | +safety.py |
| 2 | 0 | server re-exports +3 (`load_config`, `validate_config`, `write_config`), −8 defs/constants | +config.py |
| 3 | 0 | server re-exports +4 (`load_keys_file`, `read_passphrase_from_stdin`, `vendor_key_entries`, `vendor_key_names`), −6 defs (carve-out: `resolve_api_key` stays) | +keys.py |
| 4 | 0 | −1 import line (`from . import vimcrypt`) | 0 |
| 5 | 1: create-failure path (makedirs/copy error) now prints `ERROR: Cannot create config at …` instead of an uncaught traceback; missing-template branch prints the path `install_template` reads (`SETTINGS.config_template_path`) instead of the cli-side copy | cli +1 function-local import name (`install_template`), −1 function-local `import shutil`, −1 module constant `CONFIG_TEMPLATE_PATH` | cli block replaced |
| 6 | 4: (a) keys errors label `Decryption failed:`/`Invalid keys file:` → the loader's own messages under `ERROR: …`; (b) keys SHAPE validation + mode warnings now run at `start`; (c) `start` validation now the canonical set (key selectors, extra headers, models-catalog, count-token flag) — stricter; (d) `_load_config_for_validation` default param changed `CONFIG_FILE` → `SETTINGS.config_path` (runtime no-op: both callers pass paths explicitly) | cli +4 module-top import names (`_load_config_for_validation`, `validate_config`, `load_keys_file`, `vendor_key_names`), −1 def moved to config.py (`_load_config_for_validation`), cli −1 `vimcrypt.decrypt` usage | cli blocks replaced |
| 7 | 1: dead `decrypt_keys` removed (zero callers, verified pre-plan: repo-wide grep finds only its def) | keys.py −1 def | def removed |

### Steps

1. **Step 1: create `safety.py` (the task-shaped utility leaf).**
   New file `src/claude_retry_proxy/safety.py`: module docstring stating the task contract (string-emission-safety predicates: pure, stdlib-only, no package imports, no module state) and indexing the stay-behind idioms of the same task (the inline control-char scans that move with the validators in steps 2–3; `_crlf_safe` server.py:2234, `_validate_csrf_origin` server.py:97, `ALLOWED_PATH_RE` server.py:118, `RESERVED_EXTRA_HEADER_NAMES`/`EXTRA_FROM_FORBIDDEN` in config.py after step 2). Then `import re` and the **verbatim** bodies from server.py:79 (`_ADMIN_NAME_RE = re.compile(r"^[a-zA-Z0-9_./-]+$")`) and server.py:92–94 (`_validate_admin_name`).
   In server.py: add the import `from .safety import _ADMIN_NAME_RE, _validate_admin_name` (place alphabetically near the other relative imports, lines 31–43 block); delete exactly line 79, and delete lines 92–95 (the def through its following blank line — this preserves the double-blank separation at 91/96 before `_validate_csrf_origin`). Leave the `# Admin page and validation` banner (76) in place — it heads `_load_admin_html` and `_validate_csrf_origin`, which stay.
   → coder verify (auto): `git diff` on server.py shows only the import addition and the two deletions; safety.py bodies are byte-identical to the pre-change server.py:79 and 92–94.
   → coder verify (scripted): `python tmp/verification/2026-09-17-extract-config-keys-step1.py` (note: the 4-call-site count is a step-local snapshot valid only while the keys functions still sit in server.py).
   → tester verify: suite green (322 tests), `test_unit.py` unaffected (it imports `compute_*`, `_crlf_safe`, `SETTINGS` — nothing from this step).

2. **Step 2: create `config.py` (config.json pipeline).**
   New file `src/claude_retry_proxy/config.py`: module docstring; imports exactly `json`, `os`, `re`, `from .settings import SETTINGS` (whitelist — no `urllib.parse`: it follows `parse_upstream`, which stays). Then two **verbatim** ranges, content-anchored:
   - server.py:126–142: the banner comment `# Header names an extra_request_headers rule may not set: …` through `EXTRA_FROM_FORBIDDEN = {"authorization", "x-api-key"}` plus the one following blank line (129–134 is a multi-line set — take it whole).
   - server.py:168–470: the banner `# ---------------------------------------------------------------------------\n# Config loading and validation\n# ---------------------------------------------------------------------------` through `install_template`'s body end (468) plus the single blank line 469/470 that precedes `def vendor_key_entries` — i.e. end the cut exactly at the blank before `def vendor_key_entries`.
   In server.py: add `from .config import load_config, validate_config, write_config`; delete the two ranges. `load_config`, `validate_config`, `write_config` are re-exported because the parent reads them (main + `do_GET`/`do_POST` admin paths) and because `tests/test_retry_streaming.py:2410` imports `validate_config` directly (frozen surface — never clean the test import). `install_template`, `_validate_extra_header_spec`, and the three EXTRA constants are NOT re-exported: no parent caller and no test imports them (step 5 imports `install_template` straight from `.config` in cli.py, a package sibling).
   → coder verify (auto): verify the two landmarks before cutting; the cut leaves exactly two blank lines after `FORWARD_HEADERS`' end (124/125/143/144 shape) and exactly two blank lines after `parse_upstream` (166/167 then `def vendor_key_entries`).
   → coder verify (scripted): `python tmp/verification/2026-09-17-extract-config-keys-step2.py`.
   → tester verify: suite green; `test_config_keys.py` and `test_retry_streaming.py` config-validation tests unchanged (same function objects via re-export).

3. **Step 3: create `keys.py` (keys-index pipeline) — TWO cuts with an explicit carve-out.**
   New file `src/claude_retry_proxy/keys.py`: module docstring; imports exactly `json`, `sys`, `from . import vimcrypt`, `from .settings import SETTINGS`, `from .safety import _validate_admin_name` (whitelist — no `os`, no `re`: the two `re.`-shaped matches in the region are docstring text, calibrated). Then two **verbatim** ranges, content-anchored:
   - server.py:471–503: from `def vendor_key_entries(vendor):` through `vendor_key_names`' content and the two blank lines that follow it (ends immediately before `def resolve_api_key(`).
   - server.py:521–695: from `def _validate_vendor_keys_shape(vendors):` through the blank line immediately before the comment `# Bind the process-wide sinks to the resolved paths, exactly as the module-level`.
   **`resolve_api_key` (server.py:504–518) plus its two blank separators STAYS IN PLACE** — request-path resolution with parent callers (forwarder 1524, do_POST 3449); a contiguous cut would delete it. The shipped `keys.py` also explicitly includes `read_passphrase_from_stdin` (666–693, inside the second range) — it moves as a declared member of the keys bootstrap (it exists only to feed the keys decrypt; its `vimcrypt.prompt_hidden` call at server.py:682 is the reader that later justifies dropping the parent's vimcrypt import).
   In server.py: add `from .keys import load_keys_file, read_passphrase_from_stdin, vendor_key_entries, vendor_key_names`; delete the two ranges. Seam parity: after both cuts, exactly two blank lines sit between `install_template`'s end and `def resolve_api_key`, and exactly two blank lines sit between `resolve_api_key`'s end and the `# Bind the process-wide sinks` comment. Re-export evidence: `read_passphrase_from_stdin` and `load_keys_file` (main), `vendor_key_names` (admin paths 3081/3205/3304 + main 3572), `vendor_key_entries` (the parent-staying `resolve_api_key` reads it bare at server.py:511). `decrypt_keys` (dead — removal resolves in step 7) and `_validate_vendor_keys_shape` are NOT re-exported (no parent/test readers).
   → coder verify (auto): landmarks re-verified before cutting, both seams pinned as specified; `sinks.configure(...)` block untouched; `resolve_api_key` still defined in server.py and byte-identical.
   → coder verify (scripted): `python tmp/verification/2026-09-17-extract-config-keys-step3.py`.
   → tester verify: suite green; `test_config_keys.py` keys-path tests unchanged (loaders callable via re-export).

4. **Step 4: server.py assembly + import cleanup.**
   Delete `from . import vimcrypt` (server.py:32) — its every reader moved: `decrypt_keys` (594) and `load_keys_file` (627) live in keys.py after step 3, and `read_passphrase_from_stdin` (682, `prompt_hidden`) moved with them per step 3's declared member list. Zero reads remain in server.py (calibrated by grep: only 32/594/627/682 matched pre-change). Nothing else: every remaining server.py import still has a reader.
   → coder verify (scripted): `python tmp/verification/2026-09-17-extract-config-keys-step4.py` — the whole-file undefined-name assembly gate plus the three re-export checks and the no-vimcrypt check.
   → tester verify: suite green at this boundary — this is the commit point for the structural half (steps 1–4 must land green and be committed before step 5).

5. **Step 5: retarget cli.py template-copy onto `install_template`.**
   In `cmd_start`, replace the inline block (cli.py:363–372) with:
   ```python
   if not os.path.exists(config_path):
       if os.path.exists(SETTINGS.config_template_path):
           try:
               install_template(config_path)
           except OSError as e:
               print("ERROR: Cannot create config at {}: {}".format(config_path, e))
               return 1
       else:
           print("ERROR: Config file not found: {}".format(config_path))
           print("Template not available at: {}".format(SETTINGS.config_template_path))
           return 1
       print("Created config template at: {}".format(config_path))
       print("Please populate the config and run 'claude-retry-proxy start' again.")
       return 1
   ```
   The copy policy itself is `install_template` (config.py) — cli.py keeps only the branch logic and the UX strings. Two truthfulness fixes over the original draft: the missing-template branch prints the same path `install_template` would read (`SETTINGS.config_template_path`, from settings — same value as the cli binding), and a create failure (makedirs/copy error) prints a distinct `Cannot create config` message instead of falsely claiming the template is missing (see Risks #2). Remove the function-local `import shutil` (cli.py:335) and delete the `CONFIG_TEMPLATE_PATH = SETTINGS.config_template_path` binding (cli.py:24 — the error print above is its last reader; the pre-change `exists()` check at cli.py:366 is replaced). Add NO module-top imports in this step — inside `cmd_start`, next to its existing function-local imports (cli.py:334–340), add `from .config import install_template`. The other new cli imports land in step 6, when the functions they name exist in their new homes (landing them now would break `import claude_retry_proxy.cli` with ImportError — a hard dead state, not the declared red).
   → coder verify (scripted): `python tmp/verification/2026-09-17-extract-config-keys-step5.py`.
   → tester verify (same unit): `test_cli.py` template-flow tests pass; new permanent test for the missing-template path (see Guidance for Tester).

6. **Step 6: single-source cli.py keys-path and validation.**
   In cli.py module top add: `from .config import _load_config_for_validation, validate_config` and `from .keys import load_keys_file, vendor_key_names` (they all exist in their new homes by now).
   (a) Move `_load_config_for_validation` (cli.py:302–331) into config.py, **verbatim except the declared design change**: its `path = CONFIG_FILE` default becomes `path = SETTINGS.config_path`. Delete cli.py:302–331 (def through its two trailing blanks, preserving the double-blank separation before `cmd_start`). `cmd_start` and `cmd_status` call sites are untouched.
   (b) Replace the keys-read/decrypt block (cli.py:381–384 read + 389–430 decrypt/parse + vendors check) with: the same 14-byte prefix peek (`with open(keys_path, "rb") as f: head = f.read(14)` — `f.read` may return fewer bytes for a short file; `startswith` handles it), the same FileNotFoundError guard, `_keys_encrypted = head.startswith(b"VimCrypt~03!")`, the **existing passphrase-prompt block carried forward verbatim** (cli.py:391–407, incl. `--passphrase-file` handling), then:
   ```python
   try:
       vendors = load_keys_file(keys_path, passphrase if _keys_encrypted else None)
   except (ValueError, OSError) as e:
       print("ERROR: {}".format(e))
       return 1
   _trace("cmd_start: loaded {} vendors".format(len(vendors)))
   ```
   The old `Decryption failed:`/`Invalid keys file:` labels go away; `load_keys_file`'s own messages are self-describing. The old "vendors" presence check is absorbed (loader raises it). `_keys_encrypted` still drives the later `--passphrase-file` forwarding — keep it.
   (c) Replace the hand-rolled validation (cli.py:432–454) with:
   <!-- UPDATED 2026-09-18: the pre-change block's first line `tiers = config.get("tiers", {})` was a definition whose reader survives outside this cut — the post-spawn tier-print loop (cli.py ~590). Restore it as the block's first line (issue cli-start-tiers-nameerror). -->
   ```python
   tiers = config.get("tiers", {})
   provider_keys = {name: vendor_key_names(v) for name, v in vendors.items()}
   errors = validate_config(config, set(vendors.keys()), provider_keys)
   if errors:
       print("ERROR: Config validation failed:")
       for e in errors:
           print("  - {}".format(e))
       return 1
   ```
   Keep the footer print loop verbatim. Declared deltas, corrected against `validate_config`'s actual body (server.py:295–444 — it does NOT validate that a tier's model appears in `models[provider]`, nor does it parse vendor upstream URLs — `parse_upstream` is request-path only, server.py:1563): the canonical checks that newly run at `start` are **key selectors** (provider_keys arg), **extra_request_headers specs**, **models-catalog checks** (models entries shape, tier-referenced provider has a catalog entry), and the **`disable_retry_claude_count_token` boolean check**, plus the string delta `missing tiers:` → `missing required tiers:`. Unknown-model typos fail per-request at `resolve_tier` (400) in both the old and the new build — that gap is unchanged and out of scope.
   → coder verify (auto): the passphrase-prompt block is byte-identical to the pre-change cli.py:391–407; `from . import vimcrypt` still present in `cmd_start` (prompt_hidden is its reader).
   → coder verify (scripted): `python tmp/verification/2026-09-17-extract-config-keys-step6.py`.
   → tester verify (same unit): updated `test_cli.py` pins; new permanent strictness test (see below).

7. **Step 7: remove dead `decrypt_keys` from keys.py.**
   Delete the `decrypt_keys` def only. `load_keys_file` is the single decryption entry point; `vimcrypt` stays imported (its readers remain). No re-export existed.
   → coder verify (scripted): `python tmp/verification/2026-09-17-extract-config-keys-step7.py`.
   → tester verify: suite green; update the docstring mention at `tests/test_config_keys.py:931` (the only textual reference outside src/).

**Red interval:** steps 5–6 necessarily go red between coder edits and tester updates (pinned CLI strings). They form ONE reviewable unit with the tester's update round — no commit inside the window; the coder does not touch tests, the tester does not edit source. There is no green commit inside the 5–6 window, so the rollback below treats 5–6 as one unit.

**Rollback:** steps 1–4 are additive and commit green — each reverts independently with `git revert <sha>`, or in reverse order if uncommitted (`git checkout` the parent for the deleted ranges: re-instate server.py:79, 92–95, 126–142, 168–470, 471–503, 521–695 and remove the three sibling imports; delete the three new modules). Steps 5–7 form the behavioral unit and revert as one: restore cli.py's hand-rolled template/keys/validation blocks and its `_load_config_for_validation` def (including the `CONFIG_FILE` default and the `CONFIG_TEMPLATE_PATH` binding), drop the step-6 module-top imports and the step-5 function-local one, and re-instate `decrypt_keys` in keys.py. If intervening commits landed since the structural commit, re-apply or rebase the revert onto the current tree rather than ordering a blind revert that may conflict (guide §5).

## Guidance for Tester

**Tests to create:**
- **Permanent:** `test_start_rejects_uncatalogued_model_selector_at_cli` (or equivalent, in `tests/test_cli.py`) — a config that the old CLI copy accepted but the canonical `validate_config` refuses (e.g. a tier `key` selector naming no key of the provider, or a tier referencing a provider that has no `models` catalog entry) must fail `cmd_start` with the aggregated `Config validation failed:` list. Structure it with the existing spawn-refusal tests in `test_config_keys.py` (~44–128) as a dual-enforcement-point assertion: the same config is refused by the CLI's pre-spawn check AND by the spawned server, with the same error list. Do NOT key it on a tier-model-name typo — `validate_config` deliberately does not check model names against the catalog (failling per-request at `resolve_tier` is unchanged behavior, per Summary).
- **Permanent:** one parameterized template-flow test in `tests/test_cli.py` covering both branches — template present → copied + `Created config template at:` printed; template absent → both `ERROR: Config file not found:` + `Template not available at:` + return 1 (simulate by patching `settings.SETTINGS.config_template_path`, which is the path `install_template` reads — patching a cli-side constant no longer works).
- **Temporary:** none expected; a scratch reproduction of step 6's error-label flow may be used and deleted.

**Tests to update (same unit as steps 5–6):**
- `tests/test_cli.py` pins for: `Decryption failed:` / `Invalid keys file:` labels (now the loader's messages under `ERROR: …` — e.g. keys-file invalid JSON message changes); `missing tiers:` (now `missing required tiers:`); any start-flow invocation whose keys file violates the load-time shape gate or emits mode `[proxy] WARNING` lines during start (new at CLI); every newly-reachable `validate_config` error string (models-catalog shape/presence, count-token flag type, key selectors, extra-header specs) — pin them against `validate_config`'s actual strings, not paraphrases; any test that patched `cli.CONFIG_TEMPLATE_PATH` (the binding is removed — patch `SETTINGS.config_template_path`).
- `tests/test_config_keys.py:931` docstring mention of `decrypt_keys` (step 7).

**Round-1 outcome (2026-09-18):** the red-unit round caught a real regression (issue `cli-start-tiers-nameerror`) — the dropped `tiers` definition broke every CLI start path; `test_cli_reload` is the permanent regression catch that surfaced it and now pins the fixed behavior. The round resumes after the coder lands the one-line fix in step 6(c): full suite, the updated pins, the two planned permanent tests, and the template-fold candidates above remain in force.

**Tests to investigate for retirement:**
- Planner candidates: `test_cli_start_template_created` (tests/test_cli.py ~553–598) and `test_config_template_copy` (tests/test_config_keys.py ~474–518) — near-duplicates of each other on the template-present branch, superseded by the new parameterized template-flow test if it absorbs both branches. Per-test coverage proof before deleting either; if a candidate holds unique coverage, fold instead and document why in the session report.

## Summary

Server startup and the admin API read `config.json` and `keys-index.json` through one function family in `server.py`, while `cli.py` `start` hand-rolls a second, shallower copy of the same policy: its own decrypt (cli.py:408–424), its own validate-against-vendors (cli.py:432–453), its own template-copy (cli.py:363–372), and a loader (`_load_config_for_validation`). Two copies of a load-bearing policy (§7) — the CLI copy is a subset: a config that the spawned server would refuse at startup for key-selector, extra-header, models-catalog, or count-token-flag reasons passes `start` and dies after spawn. (A tier model *name* typo fails per-request at `resolve_tier` in both builds — that gap is unchanged and out of scope.)

Approach: extract the family into `config.py` / `keys.py` siblings, plus a `safety.py` utility leaf for the shared input-safety predicate, in verbatim moves (steps 1–4, zero behavior change, reviewable by diff); then single-source the CLI consumers onto the family and delete the CLI's four hand-rolled copies (steps 5–7, move-then-shape per §6/§7.2).

```
server.py ──► safety.py  (re only)            cli.py ──► config.py ──► settings.py
   ├────────► config.py (json, os, re, SETTINGS)   ├──► keys.py ──► settings.py, vimcrypt.py, safety.py
   └────────► keys.py  (json, sys, vimcrypt, SETTINGS, _validate_admin_name)
```

Every arrow is parent→sibling or sibling→leaf; no module imports the parent; no cycles.

- What stays in server.py: `parse_upstream` + `resolve_api_key` (request-path resolution with all callers in the forwarder/admin — forwarder collaborators riding a later plan; step 3's cut carves `resolve_api_key` out of the keys range), CSRF/list/headers constants, `sinks.configure(...)`.
- Dead code handled: `decrypt_keys` removed (superseded by `load_keys_file`); `install_template` resurrected as the shared template policy (its twin was the CLI inline copy).
- Alternatives rejected: one combined `config_keys.py` module (two honest categories, each independently closed — one file would bury the config→keys import shape); a validation grab-bag file (fails the utility-cluster tests — no shared task); deferring the CLI consolidation (`cli.py` duplication was declared unacceptable — sequencing B chosen by the user over two plans).
- Out of scope: the doctrine amendment itself (cross-repo, see Issue Log — this plan declares the override locally); compat/forwarder/admin extractions; any `cli.py` behavior not touched by the four single-sourcing points; `parse_upstream`/`resolve_api_key` relocation; unknown-model-at-start validation (audit-verified: `validate_config` never checked it, the plan does not add it); the `write_config` fixed `.tmp` name (pre-existing wart, carried verbatim per §8 — single-writer-safe today under `_config_lock`, unique-suffix follow-up tracked in Risks).

Baseline (pre-change tree, 2026-09-17): 322 passed / 0 failed; one trace warning, the tracked deferred issue `no-proxy-stop-trace-warning`.

## Repo Mode

Public

## Document Overrides

| Document | Rule Overridden | Reason |
|----------|-----------------|--------|
| refactor-split guide §2 Test 2 / §3 (role-grouping) | `safety.py` groups small pure predicates by task identity (string-emission safety), not by a shared API | User-directed ownership rule for task-shaped utility leaves (pure, stdlib-only, cross-cutting, bounded) — tracked by defer-issue `refactor-split-utility-cluster-doctrine` in claude-config |
| refactor-split guide §6 (one cluster per plan) | This plan wraps the config/keys family extraction AND its cli.py consumer consolidation in one plan | User chose sequencing B (move-then-shape in one plan) — steps 1–4 are purely structural and commit green before step 5; the red unit is documented |

## Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| Stricter start-time validation rejects configs that previously passed `start` (key selectors, extra headers, models-catalog, count-token flag) | Users with latent config errors fail at start instead of after spawn | Intended: single policy. Aggregated list format unchanged. Tester adds a permanent dual-enforcement-point test and updates old message pins |
| New `Cannot create config at …` message path (create failures previously raised an uncaught traceback) | Minor UX addition — truthful, but new text could be worth revisiting | Guarded branch, distinct from the missing-template arm; tester pins both branches in the parameterized template test |
| `write_config`'s fixed `.tmp` name carried verbatim into config.py (pre-existing wart: two unlocked writers could interleave) | Nil today (sole live writer is the admin switch, serialized under `_config_lock`) | Carried verbatim per §8 with the wart documented in Summary out-of-scope; a unique-suffix fix is a cheap follow-up plan, not this one |
| Red interval between coder steps 5–6 and tester updates | Suite red if committed inside the window | Steps 5–6 + tester updates are one reviewable unit; no commits inside it; steps 1–4 commit green first; rollback path documented in Guidance for Coder |

## Proposed Changes

Each step includes verification checks tagged with confidence (see Prime Directive 4).
`(auto)` = mechanical, coder self-verifies. `(scripted)` = deterministic multi-step, coder runs provided script.
Every step must have at least one verification check executable by its owner (coder steps: coder checks; tester steps: tester verify; planner steps: Evidence).
Steps MUST use this numbered-list format exactly. The `### Step N:` heading format is deprecated and must not be used.

1. **Step 1:** create `safety.py`, move `_ADMIN_NAME_RE` + `_validate_admin_name` verbatim, re-export through server.py
   → coder verify (auto): diff shows only import addition + the two deletions; bodies byte-identical to server.py:79 and 92–94
   → coder verify (scripted): ./tmp/verification/2026-09-17-extract-config-keys-step1.py (4-call-site count is a step-local snapshot)
   → tester verify: suite green, `test_unit.py` unaffected

2. **Step 2:** create `config.py`, move ranges 126–142 + 168–470 verbatim (content-anchored), re-export load_config/validate_config/write_config
   → coder verify (auto): landmarks re-verified before cutting; seam blank parity as specified
   → coder verify (scripted): ./tmp/verification/2026-09-17-extract-config-keys-step2.py
   → tester verify: suite green; config-validation tests unchanged via re-export

3. **Step 3:** create `keys.py`, move ranges 471–503 + 521–695 verbatim (content-anchored, `resolve_api_key` carved out), re-export the four parent-read names
   → coder verify (auto): `sinks.configure(...)` block untouched; `resolve_api_key` still defined in server.py
   → coder verify (scripted): ./tmp/verification/2026-09-17-extract-config-keys-step3.py
   → tester verify: suite green; keys-path tests unchanged via re-export

4. **Step 4:** drop `from . import vimcrypt` from server.py (readers all moved); commit the structural half green
   → coder verify (scripted): ./tmp/verification/2026-09-17-extract-config-keys-step4.py (whole-file assembly gate)
   → tester verify: suite green at this boundary

5. **Step 5:** retarget cli.py template-copy onto `install_template` (function-local import, truthful error split); drop the local `import shutil` and the `CONFIG_TEMPLATE_PATH` binding
   → coder verify (scripted): ./tmp/verification/2026-09-17-extract-config-keys-step5.py
   → tester verify (same unit): template-flow tests pass; new parameterized template-flow test (present + absent branches)

6. **Step 6:** single-source cli.py: move `_load_config_for_validation` into config.py (declared default change), retarget keys-path onto `load_keys_file`, validation onto `validate_config`
   → coder verify (auto): passphrase-prompt block byte-identical to pre-change cli.py:391–407; `from . import vimcrypt` retained in cmd_start
   → coder verify (scripted): ./tmp/verification/2026-09-17-extract-config-keys-step6.py
   → tester verify (same unit): updated test_cli.py pins; new permanent dual-enforcement-point canonical-set test

7. **Step 7:** remove dead `decrypt_keys` from keys.py
   → coder verify (scripted): ./tmp/verification/2026-09-17-extract-config-keys-step7.py
   → tester verify: suite green; update the test_config_keys.py:931 docstring mention

## Guidance for Planner

Documentation tasks you will execute yourself (not the coder):

- **Doc files to create/update:** `CLAUDE.md`, `README.md`, `doc/configuration.html`, `doc/operations.html`, `doc/content.html`, `doc/test-catalog.html`.
- **`.claude/mega-audit-files.json`:** no change (file absent in this repo).
- **When:** after coder and tester finish (steps 1–7 verified); CLAUDE.md structure-list line-counts re-measured (never estimated) at that point.
- **What to sync:**
  - `CLAUDE.md`: (1) Structure list — add `safety.py`/`config.py`/`keys.py` lines, trim `server.py`'s line, adjust `cli.py`'s line (validation is now the shared family); (2) the Architecture "CLI `start`" bullet — template copy runs via `install_template`, keys errors are loader-sourced, validation is the canonical `validate_config` set with the aggregated list; (3) the Gotchas "moved-out" table row "Validation flows config→keys, not the reverse, and is strict" — point it at config.py/keys.py as the policy home; (4) Future Work paragraph — note the config/keys + safety stages landed and `decrypt_keys` was removed.
  - `README.md`: "How it works" step 3's start-time validation enumeration — update it to the single-sourced canonical set (or replace the enumeration with a one-line pointer to `doc/configuration.html#validation`).
  - `doc/configuration.html`: `#validation` (line 310) — canonical policy home is config.py/keys.py; the CLI start path enforces the same rules and same error strings.
  - `doc/operations.html`: the start-flow table row and text (~lines 24–65) — loader-sourced keys messages replace `Decryption failed:`/`Invalid keys file:`, aggregated canonical validation at start, template-create failure message; the `#passphrase` section (85–108) stays accurate (CLI still decrypts first) — verify wording only.
  - `doc/content.html`: verify the configuration/operations page blurbs still match after the above edits — no structural change expected; record a no-change note if none.
  - `doc/test-catalog.html`: cli/config-keys area map after the tester lands the step 5–6 test updates.

## History

One row per event (spec revision / mega-audit / review / implementation round). Conclusion = one-sentence outcome or what changed. Dismissed = compact dismissed-findings list for the reviewer — verbatim issue slugs linked as `[<slug>](<report-path>)`, no prose-only entries (the update-and-commit cross-ref and the reviewer both match these cells verbatim). Link to report files; never restate findings inline.

| Date | Event | Conclusion | Dismissed |
|------|-------|------------|-----------|
| 2026-09-18 | Review (Phase 6) | Verdict: issues found — non-blocking; byte-identity of all moved bodies machine-verified, re-export surface matches the count table, the three test removals are absorbed — report: [2026-09-17-extract-config-keys-review-2026-09-18](./tmp/reports/2026-09-17-extract-config-keys-review-2026-09-18.json) | [review-20260918-s1](./tmp/reports/2026-09-17-extract-config-keys-review-2026-09-18.json), [review-20260918-s2](./tmp/reports/2026-09-17-extract-config-keys-review-2026-09-18.json), [review-20260918-s3](./tmp/reports/2026-09-17-extract-config-keys-review-2026-09-18.json), [review-20260918-s4](./tmp/reports/2026-09-17-extract-config-keys-review-2026-09-18.json), [review-20260918-s5](./tmp/reports/2026-09-17-extract-config-keys-review-2026-09-18.json) |
| 2026-09-18 | Spec revision (/update-plan) | Restored the `tiers` definition in the step-6(c) replacement block — its surviving reader (the post-spawn tier-print loop) was missed ([2026-09-17-extract-config-keys-cli-start-tiers-nameerror](./tmp/reports/2026-09-17-extract-config-keys-cli-start-tiers-nameerror.json)); made the step-5 gate idempotent across the 5/6 boundary ([2026-09-17-extract-config-keys-step5-boundary-gate-vs-step7](./tmp/reports/2026-09-17-extract-config-keys-step5-boundary-gate-vs-step7.json)) | — |
| 2026-09-17 | Spec revision (/update-plan) | Fixed the step-6 gate's `ast.expr` defaults crash (ast.Dump-based check) plus a latent module-top `install_template` requirement dropped per the step-5 revision, and pre-emptively fixed the step-7 checker's missing except-alias/nested-scope locals ([2026-09-17-extract-config-keys-step6-gate-defaults-attribute-crash](./tmp/reports/2026-09-17-extract-config-keys-step6-gate-defaults-attribute-crash.json)); step-6 gate now passes on the applied tree, no plan-prose changes | — |
| 2026-09-17 | Spec revision (/update-plan) | Fixed two coder-filed gate defects: step-1 gate now accepts the Attribute form of `re.compile` ([2026-09-17-extract-config-keys-step1-gate-attribute-bug](./tmp/reports/2026-09-17-extract-config-keys-step1-gate-attribute-bug.json)) and the step-2/3 "still defines" checks now exclude names supplied by the mandated re-export imports ([2026-09-17-extract-config-keys-step2-gate-reexport-name-collision](./tmp/reports/2026-09-17-extract-config-keys-step2-gate-reexport-name-collision.json)); gates 1–2 pass on the applied tree, no plan-prose changes | — |
| 2026-09-17 | Mega-audit (pre-implementation, iteration 1) | 5 High + 14 Medium findings fixed in place: step-3 resolve_api_key carve-out, validate_config strictness-claim correction (unknown-model/upstream dropped), step-5/6 import ordering, template truthfulness split + SETTINGS-sourced path, rollback block, doc-gap syncs — 0 High remain, no re-iteration; report: [2026-09-17-extract-config-keys-mega-audit-2026-09-17](./tmp/reports/2026-09-17-extract-config-keys-mega-audit-2026-09-17.json) | [2026-09-17-extract-config-keys-audit-L3](./tmp/reports/2026-09-17-extract-config-keys-mega-audit-2026-09-17.json), [2026-09-17-extract-config-keys-audit-L7](./tmp/reports/2026-09-17-extract-config-keys-mega-audit-2026-09-17.json), [2026-09-17-extract-config-keys-audit-L8](./tmp/reports/2026-09-17-extract-config-keys-mega-audit-2026-09-17.json), [2026-09-17-extract-config-keys-audit-L11](./tmp/reports/2026-09-17-extract-config-keys-mega-audit-2026-09-17.json), [2026-09-17-extract-config-keys-audit-L12](./tmp/reports/2026-09-17-extract-config-keys-mega-audit-2026-09-17.json), [2026-09-17-extract-config-keys-audit-L13](./tmp/reports/2026-09-17-extract-config-keys-mega-audit-2026-09-17.json), [2026-09-17-extract-config-keys-audit-L17](./tmp/reports/2026-09-17-extract-config-keys-mega-audit-2026-09-17.json), [2026-09-17-extract-config-keys-audit-L18](./tmp/reports/2026-09-17-extract-config-keys-mega-audit-2026-09-17.json), [2026-09-17-extract-config-keys-audit-L20](./tmp/reports/2026-09-17-extract-config-keys-mega-audit-2026-09-17.json), [2026-09-17-extract-config-keys-audit-L21](./tmp/reports/2026-09-17-extract-config-keys-mega-audit-2026-09-17.json), [2026-09-17-extract-config-keys-audit-L22](./tmp/reports/2026-09-17-extract-config-keys-mega-audit-2026-09-17.json), [2026-09-17-extract-config-keys-audit-L23](./tmp/reports/2026-09-17-extract-config-keys-mega-audit-2026-09-17.json), [2026-09-17-extract-config-keys-audit-L24](./tmp/reports/2026-09-17-extract-config-keys-mega-audit-2026-09-17.json), [2026-09-17-extract-config-keys-audit-L27](./tmp/reports/2026-09-17-extract-config-keys-mega-audit-2026-09-17.json), [2026-09-17-extract-config-keys-audit-L29](./tmp/reports/2026-09-17-extract-config-keys-mega-audit-2026-09-17.json), [2026-09-17-extract-config-keys-audit-L30](./tmp/reports/2026-09-17-extract-config-keys-mega-audit-2026-09-17.json), [2026-09-17-extract-config-keys-audit-L31](./tmp/reports/2026-09-17-extract-config-keys-mega-audit-2026-09-17.json), [2026-09-17-extract-config-keys-audit-L32](./tmp/reports/2026-09-17-extract-config-keys-mega-audit-2026-09-17.json), [2026-09-17-extract-config-keys-audit-L33](./tmp/reports/2026-09-17-extract-config-keys-mega-audit-2026-09-17.json) |
| 2026-09-17 | Initial plan | Phase 3 design closed after iterative discussion — extract config/keys + safety.py, user chose sequencing B | — |

## Plan Metadata

Fenced ```json block — the machine contract read by `parsePlanContext` (JSON-first, regex fallback). **Update it on every revision** — the rule-enforcer lens files a Medium finding when it is missing, invalid, or out of sync with the prose sections. Field semantics: `steps` = one title per `## Proposed Changes` step (numbering + first phrase; extra prose detail on either side is not a mismatch); `tester_files` = Tests to create + Verification scripts to create + Tests to investigate for retirement (mirrors the fallback's three-marker union); `doc_files` = the planner's `**Files to modify:**` list; `verification_scripts` entries shaped `./tmp/verification/<name>.py`; `repo_mode` = `Private` or `Public`; `document_overrides` = the `## Document Overrides` rows as formatted strings.

```json
{
  "plan_id": "2026-09-17-extract-config-keys",
  "steps": [
    "Step 1: create safety.py, move _ADMIN_NAME_RE + _validate_admin_name verbatim, re-export through server.py",
    "Step 2: create config.py, move ranges 126-142 + 168-470 verbatim (content-anchored), re-export load_config/validate_config/write_config",
    "Step 3: create keys.py, move ranges 471-503 + 521-695 verbatim (content-anchored, resolve_api_key carved out), re-export the four parent-read names",
    "Step 4: drop `from . import vimcrypt` from server.py (readers all moved); commit the structural half green",
    "Step 5: retarget cli.py template-copy onto install_template (function-local import, truthful error split); drop the local import shutil and the CONFIG_TEMPLATE_PATH binding",
    "Step 6: single-source cli.py: move _load_config_for_validation into config.py (declared default change), retarget keys-path onto load_keys_file, validation onto validate_config",
    "Step 7: remove dead decrypt_keys from keys.py"
  ],
  "coder_files": [
    "src/claude_retry_proxy/server.py",
    "src/claude_retry_proxy/cli.py",
    "src/claude_retry_proxy/safety.py",
    "src/claude_retry_proxy/config.py",
    "src/claude_retry_proxy/keys.py"
  ],
  "tester_files": [
    "tests/test_cli.py",
    "tests/test_config_keys.py"
  ],
  "doc_files": [
    "CLAUDE.md",
    "doc/configuration.html",
    "doc/operations.html",
    "doc/test-catalog.html"
  ],
  "verification_scripts": [
    "./tmp/verification/2026-09-17-extract-config-keys-step1.py",
    "./tmp/verification/2026-09-17-extract-config-keys-step2.py",
    "./tmp/verification/2026-09-17-extract-config-keys-step3.py",
    "./tmp/verification/2026-09-17-extract-config-keys-step4.py",
    "./tmp/verification/2026-09-17-extract-config-keys-step5.py",
    "./tmp/verification/2026-09-17-extract-config-keys-step6.py",
    "./tmp/verification/2026-09-17-extract-config-keys-step7.py"
  ],
  "repo_mode": "Public",
  "document_overrides": [
    "refactor-split guide §2 Test 2 / §3 (role-grouping): safety.py groups small pure predicates by task identity (string-emission safety), not by a shared API (Reason: user-directed ownership rule for task-shaped utility leaves — tracked by defer-issue refactor-split-utility-cluster-doctrine in claude-config)",
    "refactor-split guide §6 (one cluster per plan): this plan wraps the config/keys family extraction AND its cli.py consumer consolidation in one plan (Reason: user chose sequencing B (move-then-shape in one plan) — steps 1-4 are purely structural and commit green before step 5; the red unit is documented)"
  ]
}
```

## Audit Accumulation

*Counters reset when mega-audit runs. Used by Phase 5 entry trigger.*

| Counter | Value | Last Updated |
|---------|-------|--------------|
| issues_resolved_since_audit | 0 | 2026-09-18 |
| steps_changed_since_audit | 1 | 2026-09-18 |
| files_changed_since_audit | 0 | 2026-09-18 |

## Documentation

`doc/configuration.html`, `doc/operations.html`, `doc/test-catalog.html`, `doc/content.html` (index) — the tree is indexed by `doc/content.html`; CLAUDE.md carries the operational summary. Changes land after implementation (see Guidance for Planner).

## Final Results

**Status:** COMPLETED — commit pending (owned by `/update-and-commit`).

- **Implementation:** coder round 2026-09-17 (`build_result: pass`). Steps 1–4 (structural): `safety.py` (24 lines), `config.py` (367), `keys.py` (191) extracted from `server.py` (3,661 → 3,130 wc lines post-trim), verbatim-move discipline verified byte-for-byte by the reviewer against `HEAD`. Steps 5–7 (consolidation): cli.py template-copy/keys-load/validation single-sourced onto the family; dead `decrypt_keys` removed; the round-1 `tiers` NameError regression fixed under `/update-plan`.
- **Tests:** tester round 2026-09-18 `SUCCESS` — aggregator 321/321 (0 failed, 0 skipped; 1 pre-existing trace warning). Added: `test_start_rejects_uncatalogued_model_selector_at_cli` (dual enforcement point) and `test_cli_start_template_flow` (3-branch parameterized). Removed per user approval: `test_cli_start_no_config`, `test_config_template_copy`, `test_start_unknown_tier_key_fails_via_server_gate` (absorption verified by the reviewer).
- **Issues:** 6 rows — 5 Resolved (four verification-gate defects + the tiers NameError), 1 carried Open cross-repo (`refactor-split-utility-cluster-doctrine`, targets claude-config).
- **Review:** 2026-09-18 — verdict "issues found — non-blocking"; 0 Critical, 0 Warning, 5 Suggestions (History Dismissed cell).
- **Docs:** CLAUDE.md (structure + CLI-start bullet + moved-out table + Future Work + deferred index), README.md, doc/configuration.html, doc/operations.html, doc/test-catalog.html synced; doc/content.html verified no-change; doc-structure gate PASS.
- **Known caveats (reviewer Suggestions):** dead `_ADMIN_NAME_RE` re-export on server.py; config.py docstring spacing glitch; duplicate test banners + dead `combined` local in test_cli.py; `load_keys_file` docstring lacks its raise contract; the non-string key-selector sub-case is now covered at validate_config level only (not end-to-end).