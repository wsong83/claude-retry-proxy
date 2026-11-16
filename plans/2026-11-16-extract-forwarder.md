# Plan: 2026-11-16-extract-forwarder

## Summary

Extract the **forwarder cluster** out of `src/claude_retry_proxy/server.py`
(≈4,445 lines at base 529e327; 4,444 newline-terminated — the only code file over the
1,000-line threshold) into a new sibling
`src/claude_retry_proxy/forwarder.py`. The cluster is one concept: the
upstream forward path — everything between "the client body has arrived" and
"the upstream response is returned", together with the two stateful
mechanisms it owns (the drain-and-swap protocol state and the chat retry-nudge
marker store) and its transport helpers. It is a **pure structural verbatim
move**: zero behavioral changes, byte-identity enforced per moved def by
sha256 manifest, frozen-surface re-exports through the parent, mutable state
accessed attribute-form (`forwarder.<name>`), and a gate-enforced import
whitelist for the new module.

**52 moved names (31 defs + 21 module-level assigns)**, staged as
**step 1 = 19** (swap-drain cluster + `_error_body`), **step 2 = 9**
(retry-nudge cluster), **step 3 = 24** (transport helpers, forward path,
tier/rewrite, remaining request-policy constants) — an order derived from the
**free-variable closure of the moved set** (mega-audit iteration 1 found two
step-boundary NameErrors in the original 18/25/9 order; every intra-set
cross-step edge is now verified by a per-step AST closure gate, not by
inspection). **39 staying-code edit sites** (37 attribute re-forms + 2
`global`-declaration edits). **Tester scope: 60 AST attribute sites + 6
string-form save/restore blocks** (27 moved-name strings) in tests; comment
mentions are explicitly out of scope. The owned-state-object conversion
demanded by refactor-split §5 (guide) is deliberately **recorded as a named
follow-up**, not done here (Document Overrides).

## Repo Mode

Public (detect_repo_mode.py: "public"). Plan publishes to `plans/` with a
`Plan:` footer at consolidation time.

## Success Criteria

Each is mechanically checkable; gates are RED against the pre-change tree and
GREEN after their step (the RED runs are recorded in History).

1. `forwarder.py` exists; **all 52 moved names are byte-identical** to their
   pre-move source segments (sha256 manifest
   `tmp/verification/2026-11-16-extract-forwarder-hashes.json`, embedded in
   the step gates; regenerated for the 19/9/24 partition at revision 2).
2. `server.py` post-move: **zero** module-level defs/assigns of the 52 moved
   names; **zero** bare `Name` loads/stores of the mutable-state names
   (step-scoped: `STATE10` at the step-1 boundary — the 8 swap-state
   assigns + `_SWAP_QUIET_GRACE` + `_rng_local`; from the step-2 boundary
   on `STATE13` — the same 12 names + `RETRY_NUDGE_MAX_ENTRIES`, the nudge
   state having moved at step 2 —
   the nudge state moves at step 2, not step 3; every access is
   `forwarder.<name>`); its `forwarder`
   import is exactly the **23-name frozen surface** (measured:
   14 production caller-reads ∪ 9 test-code reads; mega-audit found 5 of the
   originally proposed 28 had comment-only "test hits" and were pruned).
3. Import relocations complete per step (step 1: `random`; step 2:
   `hashlib`; step 3: `math`, `re`, `urlparse` + sole-reader leaf names incl.
   the whole `transforms_common` line) with **zero** remaining imports/reads
   in `server.py`; `server.py` keeps its dual-reader imports — measured with
   staying production readers (`time`, `json`, `sys`, `threading`, `httpx2`
   ×9 staying catch sites, `uuid` ×9, `SETTINGS`, `log_trace`,
   `sanitize_error`, `check_payload_nesting`, `nesting_event`,
   `_map_chat_finish_reason` ×2 production call sites) **and** test-code readers (the
   `transforms_chat` line ×5 `_require_server_func` consumers + production
   reader, the `transforms_response` line ×45, `_compat_retry_lock`
   test_compat.py:1201/1205) — the last group is a declared override, see
   Document Overrides #4. `_ADMIN_NAME_RE` stays as an explicitly-unused
   import (removing it is not this plan's business).
4. `forwarder.py` import block equals the pinned whitelist exactly at every
   step boundary — the whitelist lives in
   `tmp/verification/_forwarder_gate_common.py` (`FWD_STDLIB_*` /
   `FWD_FROM_*`) and is restated per step in Proposed Changes.
5. **Free-variable closure at every step boundary**: for every def moved so
   far, each bare Name load resolves inside forwarder's post-step namespace
   (its own defs + imports ∪ builtins) — asserted by the per-step closure
   gate (mega-audit iteration 1: this check would have caught both boundary
   NameErrors).
6. `python tests/test_claude_proxy.py` passes after the tester re-point, with
   the full-suite test count preserved (no test deleted; only access-form
   edits). Precondition for every gate and suite run: `python -c "import
   claude_retry_proxy.server as s; print(s.__file__)"` prints this repo's
   `src/claude_retry_proxy/server.py` (editable install — project CLAUDE.md).
7. Every step gate exits 0 in `post` phase after its step and non-zero
   before it; each gate's `pre` phase verifies the tree is in the expected
   pre-step state (staged-index progression per Document Overrides #5:
   plan-files-only staged changes, nothing unstaged; forwarder.py absent
   or at the previous step's exact state; step-1 additionally pins
   HEAD == 529e327).

## Document Overrides

1. **§5 State doctrine (owned object with lock) — deferred as a named
   follow-up.** The §5-hot state is ten names: the 8 swap-state assigns
   (`_config_lock`, `_inflight_count`, `_config_swapping`, `_swap_done`,
   `_config_epoch`, `_last_upstream_activity`, `_swap_started_at`,
   `_swap_evictions`) plus the nudge pair (`_retry_nudge_lock`,
   `_retry_nudge_entries`); two state-adjacent holders move with their
   cluster (`_SWAP_QUIET_GRACE` float constant, `_rng_local`
   threading.local) — 12 names relocate **verbatim** as
   bare module globals because move-then-shape (guide §6) and
   never-fix-in-a-move outrank the state doctrine at plan time: converting
   12 names across 39 production sites + tester sites would bury a design
   change inside a verbatim move and destroy reviewability. The conversion is
   recorded in `CLAUDE.md` → Future Work as "forwarder owned-state-object
   conversion" and must be its own plan.
2. **State names are never re-exported.** The parent's re-export is a plain
   `from .forwarder import (...)` binding in server's own module dict — a
   name the parent re-exported cannot be *written through* to forwarder
   (and a PEP 562 `__getattr__` would not help either: it forwards reads
   only). Since tests patch state, the only faithful form is attribute
   access: `forwarder.<name>`. Function/constant re-exports work because
   their bindings are stable.
3. **API exposure (user requirement): the frozen surface is exactly 23
   names** — 14 production caller-reads (survey sections 3–4, enumerated)
   ∪ 9 test-code reads (AST census: from-imports in test_unit; `srv.`-attr
   reads in test_chat_sse/test_nesting/test_trace). Five names proposed in
   the first draft were pruned at mega-audit iteration 1 — their only "test
   hits" were docstrings/comments (`resolve_tier`, `parse_upstream`,
   `_read_capped`, `FORWARD_HEADERS`, `_interruptible_sleep` — the last
   still re-exported at steps 1–2 while staying core reads it) — plus
   `CLIENT_USER_AGENT_*` re-measured as attr-reads and `RETRY_NUDGE_TTL_SECONDS`
   as attr-reads (both stay). Mutable state is *never* re-exported;
   interim step-1 re-exports of cluster-internal helpers
   (`_swap_abort_tuple`, `_swap_chain_abort`) are pruned at step 3 when
   their readers move.
5. **Staged-index progression (the coder lane denies `git commit`).** The
   original design used per-step staging commits; coder round 1 proved
   the lane cannot make them (`git commit` harness-denied — issue
   coder-lane-cannot-make-staging-commits). The plan therefore progresses
   through the INDEX: each step ends with `git add` of its files only,
   and the gates' `pre` phases verify the tree state instead of commit
   cleanliness — staged changes limited to the plan's file set, nothing
   unstaged anywhere, no untracked non-plan paths (helper
   `tree_state_ok()`). Landmark-verification safety is preserved (an
   outside edit would surface as an unstaged or non-plan entry),
   abandonability via Rollback branch (a) (`git restore --staged` +
   user-executed hand-off), and the single plan commit lands at
   `/update-and-commit`. The red interval (Risks #1) is unchanged and no
   green is claimed inside it.
4. **Dual-reader leaf imports stay in server.py when tests read them there.**
   Import relocation (guide: relocate an import whose sole reader moved)
   applies to *sole* readers. Three leaf lines have test-code readers on the
   server surface and are therefore kept unchanged in server.py while
   forwarder imports its own copy: the `transforms_chat` line (all 6 names —
   5 via `_require_server_func` in test_chat_transform.py/test_mode_dispatch.py
   + `_map_chat_finish_reason` ×2 production call sites), the `transforms_response`
   line (both names — 45 `_require_server_func` sites in
   test_response_transform.py), and `_compat_retry_lock` in the compat line
   (test_compat.py:1201 `hasattr` + :1205 attr read). The `transforms_common`
   line has zero test-code reads and deletes whole.

## Membership and Blast Radius (guide §2/§6 record)

- **Concept test**: one concept — the upstream forward path (admission →
  transform → transport → retry → compat → response rewrite) plus the two
  mechanisms it owns. The drain protocol and the nudge store ride as
  collaborators; this enrollment is an explicit judgment call, not a
  deletion-test output: both have staying callers today (do_POST's admin
  press paths L3753/3951; the chat-SSE drain L3211–3229), and they move
  because their state and their only callers live inside the cluster the
  handler plan will consume. The later handler plan reaches forwarder.py by
  direct sibling→sibling import (handler imports forwarder; neither is the
  other's parent — the parent stays server.py).
- **Substitution test**: callers treat the cluster through one API —
  `forward_request` (wrapper, stays) and the admin/drain call sites.
  Internals never leak upward except through the frozen surface.
- **Blast radius ordering**: dependency shape forces drain-cluster-first:
  `_forward_request_impl`/`_forward_core` (step 3) call the drain helpers
  (step 1) and the nudge helpers (step 2), and sibling → parent imports are
  illegal. Step 1 therefore edits 39 staying sites (the risky region), steps
  2–3 edit zero staying lines beyond re-exports. This is the minimum-read
  ordering given the dependency graph; a zero-risk first step does not exist
  here (measured, not assumed).
- **One cluster per plan**: the handler/admin extraction is a *separate*
  later plan (it becomes possible only after this one). The chat-SSE drain
  extraction is a third plan.

## Risks

1. **Red window, steps 1–4 as one reviewable unit — and asymmetric.** Step 1
   breaks test-side `srv.<swap-state>` reads (AttributeError) and silently
   *shadows* their writes (assignment to a non-re-exported name creates a
   dead attribute on the server module; the moved code never sees it).
   Reads are loud, writes are silent — **the authoritative detector is the
   tester gate's AST + string-form scan, not runtime failure**, and a test
   that only writes state can stay green while testing nothing. Hence the
   exhaustive re-point of all 60 attribute sites and all 6 string-form
   blocks, not just the failing ones. Production code is green at every step
   boundary (re-exports + attribute edits + the closure gate), the test
   suite is red from step 1 until the tester's step 4. No commit may be
   presented as green inside the window; interim per-step commits are
   staging (guide §6: one plan, one commit).
2. **Half-patched-function trap, both directions.** After the split,
   `srv.<moved-fn> = fake` patches affect only staying callers (server's
   module dict); moved callers resolve forwarder's own binding. Measured
   census: the only test patches of moved functions are
   `srv._drain_for_swap =` ×7 (test_admin.py L2890/2942/3420/3476/3648/3690/
   3717), whose only production callers are do_POST L3753/3951 — staying.
   **They keep working; the tester must not "fix" them.** No test patches any
   other moved function (setattr/string-form scan: zero). Inverse census
   (patches of *staying* names whose consumers moved): the only staying-leaf
   patches in the suite are `srv.time = ...` ×2 (test_trace.py:1494/1628,
   driving the staying heartbeat loop) — no moved-code consumer, unaffected.
3. **Hidden write sites under `global` decls.** The survey's section 3/4
   cannot see `_config_epoch += 1` etc. inside do_POST (the `global`
   statement puts them in local scope). The 6 epoch sites, 4
   swapping/started_at sites, and 2 `_swap_done` sites in do_POST are pinned
   in the step-1 table and re-verified at edit time by landmark text.
   Deleting/shrinking the `global` lines (780, 3549) is part of the edit; a
   missed hidden store fails at runtime with `NameError` on first admin
   press — the gates' zero-bare-name walk makes this GREEN-checkable.
4. **Byte-identity mechanics.** No moved def has decorators (measured), so
   `ast.get_source_segment` slices (def-line → end) are the whole unit.
   Adjacent comment bands move by pinned deletion range, not by hash.
5. **Threshold drift.** All line numbers are as-of-plan-writing
   (server.py @ 529e327). The coder re-verifies each
   deletion range by landmark before cutting; a drifted or zero-length range
   is a stop-and-report, never an improvisation.
6. **Compile-green is not resolve-green.** A byte-identical move compiles
   fine and still NameErrors at runtime on the first eligible request if a
   moved body reads a name the forwarder namespace lacks (iteration 1 found
   two). The per-step free-variable closure gate (SC5) is the systemic
   defense; a gate that only parsed/imported would repeat the failure.

## Rollback

- **Base**: 529e327 (master, clean tree at plan time). The plan's first gate
  pins HEAD == 529e327 in its `pre` phase.
- **Partial-step abandonment** — select the branch by what has landed:
  (a) *No interim commit yet* (work exists only in the tree/index):
  `git checkout -- src/claude_retry_proxy/server.py tests/`, then
  `git restore --staged src/claude_retry_proxy/forwarder.py` (the coder
  stages the file the moment it exists, so "untracked" is the wrong
  assumption) and hand the working-tree file's deletion to the user via
  the repo's guarded hand-off script — agents never `rm` workflow
  artifacts. Verify recovery: `python -c "import
  claude_retry_proxy.server"` succeeds and `git status --porcelain --
  src/ tests/` is empty.
  (b) *Interim staging commits exist*: `git revert` those commits only —
  never `reset` (no history rewriting, so the git-history-rewriting
  guide is not in play); re-apply a needed revert onto the current tree
  if intervening commits exist rather than ordering a blind revert.
  **Mid-step interruption** (a run dies between the deletion ranges of
  one step): never resume mid-step — restore the previous boundary per
  branch (a)/(b), re-run that step's `pre` phase, and start the step
  from its beginning. A half-cut tree fails its own gate's
  residual-name check; the gate detects, the rollback recovers.
- **Post-consolidation**: the plan lands as one commit; rollback is
  `git revert` of that single commit plus a proxy restart. No env var
  restores any part of this move (the drain mechanism is untouched — this
  is a structural move only).

## Issue Log

| # | Status | Severity | Summary | Resolution |
|---|--------|----------|---------|------------|
| 1 | Resolved | Medium | Gate: do_POST global-decl equality demanded `{'_current_config'}` but the tree legitimately keeps `global _shutting_down` (coder round 1, [gate-do-post-global-assertion-unsatisfiable](./tmp/reports/2026-11-16-extract-forwarder-gate-do-post-global-assertion-unsatisfiable.json)) | assert widened to `{'_current_config', '_shutting_down'}` in all three step gates; step-1 post GREEN 18/18 |
| 2 | Resolved | Medium | Gate: server-side closure namespace lacked ClassDef names and module dunders — 4 false positives ([gate-server-closure-namespace-incomplete](./tmp/reports/2026-11-16-extract-forwarder-gate-server-closure-namespace-incomplete.json)) | `closure_violations` namespace gains ClassDef names + module dunders; zero violations on the staged tree |
| 3 | Resolved | High | The coder lane cannot run `git commit`; per-step staging commits impossible and steps 2–3 pre phases unsatisfiable ([coder-lane-cannot-make-staging-commits](./tmp/reports/2026-11-16-extract-forwarder-coder-lane-cannot-make-staging-commits.json)) | Document Overrides #5 rewritten: staged-index progression; gates use `tree_state_ok()` (plan-files-only staged, nothing unstaged); step-2 pre GREEN 7/7 on the round-1 staged tree |
| 4 | Resolved | Medium | Gate: step-3 pre demanded `urlparse` among PLAIN imports, but it arrives via `from urllib.parse import urlparse` — pre unsatisfiable (coder round 2, [gate-step3-pre-urlparse-unsatisfiable](./tmp/reports/2026-11-16-extract-forwarder-gate-step3-pre-urlparse-unsatisfiable.json)) | pre check split: math/re via plain, urlparse via the from-import; step-3 pre GREEN 7/7 on the post-step-2 tree |
| 5 | Resolved | Low | `compat.py:52` comment says "server.py imports it" of COMPAT_FEATURE — falsified by step 3; compat.py was outside the round-3 edit list ([compat-comment-stale-server-import](./tmp/reports/2026-11-16-extract-forwarder-compat-comment-stale-server-import.json)) | compat.py added to coder scope; coder round 4 fixes the comment line (planner lane cannot edit src) |
| 6 | Resolved | Low | Step 5 ordered "re-run all four gates post" — step-1/step-2 post assert intermediate boundary states, unsatisfiable on the final tree ([step5-four-gate-rerun-unsatisfiable](./tmp/reports/2026-11-16-extract-forwarder-step5-four-gate-rerun-unsatisfiable.json)) | Step 5 item 3 rewritten: re-run the two cumulative gates (step-3 post + tests-repost post); intermediate gate evidence stands as recorded |
| 7 | Resolved | High | Phase-6 review H1: the tester's three test-file edits were unstaged (` M`) — the index held src-only, and a commit from it would ship a tree failing ~60 attribute sites (review-index-missing-test-edits) | planner staged the three files (`git add tests/test_admin.py tests/test_chat_sse.py tests/test_retry_streaming.py`); index now matches the green 531/531 tree |
| 8 | Resolved | Medium | Phase-6 review M2: gate helper `PLAN_FILES` omits `src/claude_retry_proxy/compat.py` — `tree_state_ok()` RED on the final tree ("staged path outside the plan's files") (review-plan-files-omits-compat) | PLAN_FILES extended to the plan's full inventory (compat.py + the tester's three files, with a comment recording why); the coder-boundary pre phases that relied on the old set are complete and not re-run; lane separation stays harness-enforced |
| 9 | Resolved | Low | Phase-6 review L4+L3(src): two server.py comments falsified by the move — the module docstring's dependency list (L10-12) still names `re`/`urllib.parse` (both relocated to forwarder.py), and `_BestEffortStderr`'s rationale (L125-135) says "server.py holds ~40 runtime stderr prints, several inside the retry loop's try block" though the retry loop moved (review-server-comments-stale) | coder round 5 (exit 0): both texts fixed comment-only — the dependency list drops the relocated names, the rationale names server.py's own prints plus forwarder.py's forward path; step-3 post re-run GREEN at close-out |
| 10 | Resolved | Low | Phase-6 review L3(tests)+residual: four test-side comments stale — test_trace.py:1652 repeats the `_BestEffortStderr` rationale with the moved retry loop; tests/_harness.py:31-35 and 41-46 and test_spawn_isolation.py:5-6 name cli.py/server.py as the settings-reading modules without forwarder.py, the third since the split (review-test-comments-stale) | tester round 2: the four texts fixed, plus a second staleness the tester caught — test_trace's quoted clause predated the httpx2 transport, both fixed in the one docstring; tests-repoint post GREEN 7/7 before AND after (87 sites unchanged), corpus 0 fail, suite 531/531; _harness.py:95-96 deliberately left (state-file read path — forwarder.py does not read it) |
| 11 | Resolved | Low | Phase-6 review L5: three save/restore `finally` blocks (test_admin.py, empty-dict inits at 3307/3411/3547) KeyError-mask the real failure when setup raises before the snapshot dicts populate (review-finally-keyerror-mask) | tester round 2: all three blocks guarded (reload-serialize, probe-precedes-drain, switch-apply); stand-in restore + `shutil.rmtree` unconditional; suite 531/531 |
| 12 | Resolved | Low | Phase-6 review L6: retire_inventory missed five transient artifacts — the coder's step-2/step-3 slice scripts and the tester's census/repoint/poll-suite scripts (review-retire-inventory-incomplete) | all five verified present and added to retire_inventory in revision 6, together with the rev6/rev7 patch scripts |
| 13 | Resolved | Low | Tester-found gate defect: the tests-repoint binding check does not see enclosing-function `forwarder` imports, so four nested functions in test_admin.py carry redundant function-local imports to satisfy it ([gate-forwarder-binding-scope-closures](./tmp/reports/2026-11-16-extract-forwarder-gate-forwarder-binding-scope-closures.json)) | accepted residual: the workaround is in place, gate-visible and green; fixing the check buys only the removal of four harmless imports and the gate retires with the plan — this row is the record that retires the report at close-out |

## Proposed Changes

All steps `(scripted)` unless marked `(auto)`. Gate scripts live in
`tmp/verification/` and are run from the repo root WITHOUT `-I`
(isolated mode drops the script directory from `sys.path`).

### Step 1 — swap-drain cluster + `_error_body` → forwarder.py `(scripted: gate step1)`

**Moves (19 names, sha256-pinned)**: state assigns `_config_lock` (L71),
`_inflight_count` (86), `_config_swapping` (87), `_swap_done` (88),
`_config_epoch` (89), `_last_upstream_activity` (90), `_swap_started_at` (91),
`_swap_evictions` (92), `_SWAP_QUIET_GRACE` (97), `_rng_local` (109); defs
`_rng` (111–117), `_touch_upstream_activity` (141–149), `_drain_for_swap`
(152–210), `_note_swap_eviction` (213–230), `_swap_epoch_changed` (233–240),
`_swap_chain_abort` (243–250), `_interruptible_sleep` (253–266),
`_swap_abort_tuple` (269–281), **`_error_body` (646–666)** — pulled forward
from the transport band because `_swap_abort_tuple` (L277) calls it; leaving
it in server.py would NameError every swap-press eviction at this boundary
(mega-audit iteration 1, finding 2; its only free variable is `json`).

**Deletion ranges (landmark-verify, then cut)**:
- L70–71 (the `_config_lock` comment + assign move together — an
  orphaned comment is a defect the coder must not leave); L72–83 stay
  (`_current_config`, `_config_path`, `_CARRIED_MODELS_KEYS` + comments).
- L85–97 (swap-state comment 85 + assigns 86–92 + grace comment 94–96 +
  assign 97). L99–105 stay (`_startup_state`, `_vendors`).
- L107–117 (`_rng_local` comment 107–108 + assign 109 + `_rng` 111–117).
- L120–139 ("Config-swap drain helpers" banner + design comment — moves with
  the cluster; blanks 118–119 and 140 are seam, blank parity pinned).
- L141–281 (the seven drain defs, comment separators included; the
  eighth cluster def, `_rng`, was cut at L111–117 above).
- L646–666 (`_error_body`), seam blanks verified around it; L628–643
  (`compute_delay`, `compute_jittered_delay`) STAY until step 3.

**Create `forwarder.py`**: module docstring (new text — the only non-verbatim
lines in the file), then exactly this import block (step-1 whitelist):

```python
import json
import random
import threading
import time

from .settings import SETTINGS
from .sinks import log_trace
```

then the moved defs in server.py order (comment bands included).

**server.py additions** (after the leaf-import block):

```python
from . import forwarder
from .forwarder import (_drain_for_swap, _error_body, _interruptible_sleep,
                        _note_swap_eviction, _rng, _swap_abort_tuple,
                        _swap_chain_abort, _swap_epoch_changed,
                        _touch_upstream_activity)
```

(9 interim re-exports: staying forward-path code (L808–1932) bare-reads
`_interruptible_sleep`/`_swap_abort_tuple`/`_swap_chain_abort` until all
three move at step 3, and staying do_GET/do_POST/streaming read
`_error_body` from day one. All three function names are pruned from the
re-export line at step 3 (`_interruptible_sleep` because its test hits
were docstrings only — measured; the other two because their readers
moved). `_rng`, `_touch_upstream_activity`, `_error_body` are in the
final 23-name surface.)

**server.py staying-code edits — 39 sites total this step** (37 attribute
re-forms + 2 `global`-declaration edits; every moved *state* name becomes
`forwarder.<name>`; moved *function* names stay bare, resolving through the
re-export — including `_swap_epoch_changed` in the four streaming lines,
where only the state name `_config_swapping` is qualified):

| Site | Current | After |
|---|---|---|
| 780 | `    global _inflight_count` | (delete line) |
| 788 | `        with _config_lock:` | `        with forwarder._config_lock:` |
| 789 | `            if not _config_swapping:` | `            if not forwarder._config_swapping:` |
| ~792 | `            _inflight_count += 1` | `            forwarder._inflight_count += 1` |
| 794 | `            epoch_snapshot = _config_epoch` | `            epoch_snapshot = forwarder._config_epoch` |
| 797 | `        _swap_done.wait()` | `        forwarder._swap_done.wait()` |
| 804 | `        with _config_lock:` | `        with forwarder._config_lock:` |
| ~805 | `            _inflight_count -= 1` | `            forwarder._inflight_count -= 1` |
| 2319 | `if _config_swapping or _swap_epoch_changed(epoch):` | `if forwarder._config_swapping or _swap_epoch_changed(epoch):` |
| 2378 | (same expression) | (qualify `_config_swapping` only) |
| 2410 | (same expression) | (qualify `_config_swapping` only) |
| 3066 | (same expression, `_stream_chat_sse_to_anthropic`) | (qualify `_config_swapping` only) |
| 3458 | `        with _config_lock:` | `        with forwarder._config_lock:` |
| 3488 | `        with _config_lock:` | `        with forwarder._config_lock:` |
| 3489 | `            swapping = _config_swapping` | `            swapping = forwarder._config_swapping` |
| 3491 | `                    _swap_started_at` (read) | `                    forwarder._swap_started_at` |
| 3492 | (second read) | (re-form) |
| 3493 | `                    _last_upstream_activity` (read) | `                    forwarder._last_upstream_activity` |
| 3494 | (second read) | (re-form) |
| 3495 | `                inflight = _inflight_count` | `                inflight = forwarder._inflight_count` |
| 3549 | `    global _current_config, _config_epoch, _config_swapping, _swap_started_at` | `    global _current_config` |
| 3711 | `        with _config_lock:` | `        with forwarder._config_lock:` |
| 3712 | `            validated_epoch = _config_epoch` | `            validated_epoch = forwarder._config_epoch` |
| 3769 | `        with _config_lock:` | `        with forwarder._config_lock:` |
| 3780 | `            and _config_epoch != validated_epoch)` | `            and forwarder._config_epoch != validated_epoch)` |
| 3816 | `        _config_epoch += 1` | `        forwarder._config_epoch += 1` |
| 3834 | `        with _config_lock:` | `        with forwarder._config_lock:` |
| 3835 | `            _config_swapping = False` | `            forwarder._config_swapping = False` |
| 3836 | `            _swap_started_at = None` | `            forwarder._swap_started_at = None` |
| 3837 | `            _swap_done.set()` | `            forwarder._swap_done.set()` |
| 3875 | `        with _config_lock:` | `        with forwarder._config_lock:` |
| 3882 | `            gated_epoch = _config_epoch` | `            gated_epoch = forwarder._config_epoch` |
| 3966 | `        with _config_lock:` | `        with forwarder._config_lock:` |
| 3967 | `            if _config_epoch != gated_epoch:` | `            if forwarder._config_epoch != gated_epoch:` |
| 4007 | `        _config_epoch += 1` | `        forwarder._config_epoch += 1` |
| 4013 | `        with _config_lock:` | `        with forwarder._config_lock:` |
| 4014 | `            _config_swapping = False` | `            forwarder._config_swapping = False` |
| 4015 | `            _swap_started_at = None` | `            forwarder._swap_started_at = None` |
| 4016 | `            _swap_done.set()` | `            forwarder._swap_done.set()` |

(Landmark-verify each at edit time; `forward_request` L764–805 and do_POST's
admin tail blocks 3828–3845 / 4005–4020 were read whole at plan time.)

**Byte-hash note**: `ast.get_source_segment` ends at the statement's
value, so the seven state assigns' trailing inline comments sit outside
the hashed segment — the pinned deletion ranges carry them verbatim, and
the step gate asserts each comment text in forwarder.py's source.

**Import relocation (step 1)**: delete `import random` (L22) from server.py
— sole reader `_rng` moved. (`json`, `threading`, `time` are dual-reader:
server keeps all three, forwarder imports its own.)

**Gate**: `python tmp/verification/2026-11-16-extract-forwarder-step1.py pre`
/ `... step1.py post`. Post asserts: manifest (19), forwarder module body ==
exactly the 19 names, whitelist exact, zero bare uses of the 10 swap-state
names in server.py (`STATE10` — the nudge state is still legitimately
server's until step 2), re-export == the 9-name set, `random` relocated, the
**free-variable closure** of the 19 moved defs against forwarder's namespace,
clean-tree preconditions.

### Step 2 — retry-nudge cluster → forwarder.py `(scripted: gate step2)`

**Moves (9 names, sha256-pinned)**: `RETRY_NUDGE_TTL_SECONDS` (300),
`RETRY_NUDGE_MAX_ENTRIES` (301), `_retry_nudge_lock` (307),
`_retry_nudge_entries` (308), `_retry_nudge_sweep` (311–327),
`_retry_nudge_remember` (330–382), `_retry_nudge_arm` (385–404),
`_retry_nudge_messages_bytes` (407–422), `_retry_nudge_check` (425–481).

**Order note (mega-audit iteration 1, finding 1)**: the nudge cluster moves
BEFORE the forward path because `_forward_request_impl` (L1211/1213)
bare-reads `_retry_nudge_remember`/`_retry_nudge_check`; moving the forward
path first would NameError every eligible chat request at this boundary.
The nudge defs' free variables are only `time`/`json`/`hashlib`/`threading`
+ their own names (verified by the step-2 closure gate) — nothing from step
3.

**Deletion range**: L284–308 (nudge banner 284–286 + "#" 287 + explanatory
block 288–299 + the four assigns) and L311–481 (five defs + separators).
Blanks 282–283 and 309–310 are seam.

**forwarder.py additions**: the 9 moved names (4 assigns + 5 defs) +
`import hashlib` appended to the stdlib block (sole readers are the nudge defs; **delete `import hashlib`
(L16) from server.py** at this step).

**server.py re-export line after step 2** — nothing is pruned yet: the
staying forward-path code still bare-reads `_swap_abort_tuple`/
`_swap_chain_abort` (they move at step 3), so the set grows from 9 to
**14 names** (step-1 set + the 4 nudge functions + `RETRY_NUDGE_TTL_SECONDS`;
the pruning of `_swap_abort_tuple`, `_swap_chain_abort`, and
`_interruptible_sleep` all happens at step 3):

```python
from .forwarder import (_drain_for_swap, _error_body, _interruptible_sleep,
                        _note_swap_eviction, _retry_nudge_arm,
                        _retry_nudge_check, _retry_nudge_messages_bytes,
                        _retry_nudge_remember, _rng, _swap_abort_tuple,
                        _swap_chain_abort, _swap_epoch_changed,
                        _touch_upstream_activity, RETRY_NUDGE_TTL_SECONDS)
```

**Staying-code edits this step: ZERO** (no production staying reads of nudge
state — measured; the chat path calls the functions via re-export).

**Red note**: this step widens the red window (test_chat_sse's 26 nudge
attribute sites + string forms start failing/shadowing) — expected; step 4
is the same reviewable unit.

**Gate**: `... step2.py pre` / `... step2.py post` (post: cumulative 28-name
manifest, whitelist with hashlib, re-export == 14 names, zero bare uses
of the 12 state names + `RETRY_NUDGE_MAX_ENTRIES` (`STATE13` — the nudge
state moves at this step), closure of all 28 moved defs, `hashlib`
relocated).

### Step 3 — transport helpers, forward path, tier/rewrite → forwarder.py `(scripted: gate step3)`

**Moves (24 names, sha256-pinned)**: `ALLOWED_PATH_RE` (520),
`ALLOWED_METHODS` (521), `FORWARD_HEADERS` (524–526), `parse_upstream`
(533–557), `resolve_api_key` (560–574), `compute_delay` (628–631),
`compute_jittered_delay` (634–643), `_read_capped` (695–742),
`CLIENT_USER_AGENT_MAX_CHARS` (992), `CLIENT_USER_AGENT_TRUNCATION_MARKER`
(993), `TRACE_MODEL_MAX_CHARS` (995), `TRACE_MODEL_TRUNCATION_MARKER` (996),
`_client_user_agent` (999–1038), `_trace_model` (1041–1055),
`_compat_probe_outcome` (808–839), `_reasoning_rescue` (842–915),
`_resolve_extra_request_headers` (918–982), `_forward_request_impl`
(1058–1529), `_upstream_header_value` (1532–1544), `_forward_core`
(1547–1932), `extract_model` (1939–1963), `resolve_tier` (1966–2000),
`_rewrite_sse_first_event` (2020–2106), `_rewrite_json_response`
(2109–2141).

**Deletion ranges** (stay-behind splits pinned):
- L519–526 ("Whitelisted paths and methods" comment + three constants).
- L529–531 banner ("Upstream URL parsing") + L533–557 + L560–574. L575–612
  STAY (Expr L579, `_BestEffortStderr` L582–612 — used by `main`).
- L628–643 (`compute_delay`, `compute_jittered_delay`). L669–692 STAYS
  (`_nesting_limit_message` — handler + test_nesting reader).
- L695–742 (`_read_capped`). L749–757 STAYS (`heartbeat_loop`).
- L808–982 (`_compat_probe_outcome`, `_reasoning_rescue`,
  `_resolve_extra_request_headers`; L983–991 comment band moves with the UA
  constants).
- L992–1055 (four constants + `_client_user_agent` + `_trace_model`).
- L1058–1544 (`_forward_request_impl`, `_upstream_header_value`),
  L1547–1932 (`_forward_core`).
- L1935–1963 (banner "Model extraction and tier resolution" +
  `extract_model`), L1966–2000 (`resolve_tier`).
- L2020–2141 (`_rewrite_sse_first_event`, `_rewrite_json_response`).
  L2007–2017 STAY (SSE/drain constants — handler readers).

**forwarder.py additions**: the 24 moved names (7 assigns + 17 defs) +
these whitelist lines
(stdlib): `httpx2`, `math`, `re`, `sys`, `from urllib.parse import urlparse`;
(leaves): the **25-name compat set** (the 30-name server import block
minus the six kept names — forwarder imports `_compat_retry_lock` as a
**dual reader**: the moved impl bare-reads it at L1245/1412/1497/1529,
while server keeps its own copy for the test readers; Document Overrides
#4), `from .config import reasoning_roundtrip_models,
reasoning_switch_params`, `from .keys import
vendor_key_entries`, `from .nesting import check_payload_nesting,
nesting_event`, `from .sanitize import sanitize_error`, `increment_retried`
(joins the sinks line), `from .transforms_common import _sanitize_body_tools,
_transform_and_guard`, `from .transforms_response import
_anthropic_to_response, _response_to_anthropic` (dual with server's kept
line), `_anthropic_to_chat`/`_chat_to_anthropic` join the transforms_chat
line (dual with server's kept line). The full final block is pinned as
`FWD_STDLIB_3`/`FWD_FROM_3` in `_forwarder_gate_common.py` — that file is
the authoritative whitelist; this prose restates it.

**server.py re-export line after step 3** — prunes `_swap_abort_tuple`,
`_swap_chain_abort` (readers moved), prunes `_interruptible_sleep` (zero
remaining production readers; test hits were docstrings only — measured),
adds 12 step-3 names → final **23-name frozen surface**:

```python
from .forwarder import (_client_user_agent, _drain_for_swap, _error_body,
                        _forward_request_impl, _note_swap_eviction,
                        _resolve_extra_request_headers, _retry_nudge_arm,
                        _retry_nudge_check, _retry_nudge_messages_bytes,
                        _retry_nudge_remember, _rewrite_json_response,
                        _rewrite_sse_first_event, _rng, _swap_epoch_changed,
                        _touch_upstream_activity, _trace_model,
                        CLIENT_USER_AGENT_MAX_CHARS,
                        CLIENT_USER_AGENT_TRUNCATION_MARKER,
                        RETRY_NUDGE_TTL_SECONDS, compute_delay,
                        compute_jittered_delay, extract_model, resolve_api_key)
```

**Import relocations (step 3)** — delete from server.py (sole readers
moved): `import math` (L20), `import re` (L23), `from urllib.parse import
urlparse` (L30); from L35 config line drop `reasoning_roundtrip_models,
reasoning_switch_params` (tests read these on the `config` module directly —
measured, test_config_split.py); from L36 keys line drop
`vendor_key_entries`; from the compat block drop the 24 relocating names —
it keeps exactly `_compat_state_lock, _compat_validate_constants,
_load_compat_state, _compat_normalize_threshold, _persist_compat_state_locked,
_compat_retry_lock` — of which two have `main()` readers
(`_compat_validate_constants` L4345, `_load_compat_state` L4346), three
are reader-less imports kept as untouched (not this plan's business to
remove), and `_compat_retry_lock` is the test-read override whose moved
reader forwarder re-imports (dual); from L57 sinks line drop `increment_retried` (tests
read the sinks module directly — measured, test_sinks.py:358); **the L59–63
transforms_chat line and L65 transforms_response line stay UNCHANGED**
(test-code readers; Document Overrides #4); **L64 transforms_common line
deletes whole** (zero staying production readers, zero test-code reads —
all test hits are docstrings/labels, measured). Server KEEPS: `httpx2` (9
staying catch sites), `uuid` (9 staying sites), `time`, `json`, `sys`,
`threading`, `SETTINGS`, `log_trace`, `write_state`, `increment_total`,
`write_start_marker`, `write_stop_marker`, `sanitize_error`,
`check_payload_nesting`, `nesting_event`, `resolve_trace_file`,
`_validate_admin_name` (all measured with staying readers).

**Staying-code edits this step: ZERO** beyond the three leaf-docstring
attribution fixes this step falsifies: `config.py:14–15`
("`parse_upstream` and `resolve_api_key` stay in server.py" → "live in
forwarder.py"), `keys.py:9` ("`resolve_api_key` stays in server.py" →
"lives in forwarder.py"), and `safety.py:10–11` (the moved-name list
drops `ALLOWED_PATH_RE`, which now lives in forwarder.py; `_crlf_safe`
and `_validate_csrf_origin` remain server.py's). Comment-only edits —
no behavior.

**Gate**: `... step3.py pre` / `... step3.py post` (post: cumulative 52-name
manifest — the strongest final identity check — whitelist final, re-export
== 23, zero bare uses of the 12 state names + `RETRY_NUDGE_MAX_ENTRIES`,
closure of all 52 defs, banner moves, `hashlib`/`math`/`re`/`urlparse`
relocated).

### Step 4 — tester: re-point the state sites `(scripted: gate tests-repoint)`

**The real census is AST-based, not text-based** (mega-audit iteration 1:
the first draft's 105 was a raw-text count; comments/docstrings inflated
it). Re-point every code-form access of the ten state names:
`_config_lock`, `_inflight_count`, `_config_swapping`, `_swap_done`,
`_config_epoch`, `_last_upstream_activity`, `_swap_started_at`,
`_swap_evictions`, `_SWAP_QUIET_GRACE`, `_rng_local`, plus the nudge pair
`_retry_nudge_lock`, `_retry_nudge_entries`:

1. **60 attribute sites** (`alias.<name>` reads, patches, dict mutations,
   with-forms — post-move the parent holds none of these names; reads raise
   AttributeError, writes silently shadow):

| Test file | Attribute sites |
|---|---|
| tests/test_admin.py | `_config_epoch` 17, `_config_swapping` 7, `_inflight_count` 5, `_swap_evictions` 5 = **34** |
| tests/test_chat_sse.py | `_retry_nudge_entries` 14, `_retry_nudge_lock` 12 = **26** |

2. **6 string-form save/restore blocks** in test_admin.py —
   `saved = {name: getattr(srv, name) for name in (...)}` + the matching
   `finally` restore loop. The tuples mix staying and moved names and
   **cannot be re-pointed wholesale**: split each into a staying list
   (`_config_path`, `_current_config`, `_vendors` — still getattr/sattr on
   `srv`) and a moved list (`_config_epoch`, `_config_swapping`,
   `_inflight_count`, `_swap_evictions`, `_swap_started_at` — getattr/sattr
   on `forwarder`), updating both the save comprehension and the restore
   loop — **and re-forming each restore loop as explicit per-name
   attribute statements** (`forwarder._config_epoch = saved_fwd["_config_epoch"]`
   etc.), using two containers (`saved_srv` for staying names, `saved_fwd`
   for moved names). Loop-form restores are invisible to the gate's other
   detectors (mega-audit iteration 3, High): only attribute-form restores
   are gate-checked on both bases, so a missed restore cannot slip through
   silently. Blocks: L2864–2866 (+finally 2941–2944), L3189–3191 (+3260),
   L3307–3310 (+3348), L3401–3404 (+3478), L3521–3524 (+3579), L3605–3608
   (+ finally L3718–3719). 27 moved-name strings total across the six tuples
   (measured; per-block 4/3/5/5/5/5 — block 2 at L3189 has 3 moved
   names, no `_swap_evictions`).
3. **Leave alone**: the 18 comment/docstring mentions of state names (no
   runtime effect), the 7 `srv._drain_for_swap =` patches
   (L2890/2942/3420/3476/3648/3690/3717 — their only production callers are
   staying do_POST L3753/3951; re-pointing would BREAK them), and all
   reads/patches of functions/constants (covered by the frozen surface).
4. **Import style**: `import claude_retry_proxy.forwarder as forwarder`,
   function-locally, mirroring each file's existing
   `import claude_retry_proxy.server as srv` placement — never
   module-level above the harness import (forwarder imports settings,
   whose env-derived paths must bind after the harness sets them). The
   attribute base must be exactly `forwarder` — the gate classifies
   sites by that literal name.
5. **Comment citation sweep**: rewrite or remove `server.py:<line>`
   citations in test comments/docstrings (comment-only edits; ~1,500 lines
   move out of server.py, so the citations go stale). No assertion changes.
6. Run `... tests-repoint.py post` BEFORE the suite: a missed re-point
   in a save/restore block is not a clean failure but a potential
   unbounded hang (a save re-pointed to `forwarder` with a `finally`
   loop restoring into `srv` deadlocks the next admin-press test), so
   the hard zero-bare checks must pass first. Then run the full suite:
   `python tests/test_claude_proxy.py` — full count preserved, all
   green. A suite run inside the red window is aborted, not debugged.

**Gate**: `... tests-repoint.py pre` / `... tests-repoint.py post`. Post
asserts: zero state-name Attribute sites on any non-forwarder base (hard),
zero srv-based state-name tuple blocks (hard — each block is either
forwarder-routed or split into a staying srv block + a moved forwarder
block), zero state-name accessor calls with a non-forwarder base, ≥ 55
forwarder-form attribute sites (calibration floor, measured 60), no
state-name from-imports of the server module, zero loop-form `setattr`
restores (the re-form mandate above), and every function using
`forwarder.<state>` carrying a `forwarder` binding (module-level or
function-local).

### Step 5 — planner: doc sync + final verification `(auto)`

1. `CLAUDE.md` (maintenance discipline: before revising any section, find
   the command/gate that owns or reads it; baseline the MUST/NEVER/ALWAYS
   keyword count before the edit and re-count after; flag any redundant or
   outdated content for the user — never silently delete):
   - Structure: add the `forwarder.py` entry (one behavioral sentence, no
     line counts); adjust the `server.py` entry; **rewrite the `compat.py`
     entry's parenthetical** — "(extracted from server.py; the probe-outcome
     + retry orchestration slice stays in server.py)" becomes "...now lives
     in forwarder.py" (the whole forward path moves, including the
     probe-outcome slice `L808–982` and the retry-orchestration slice
     `_forward_request_impl` L1058–1529).
   - Future Work: add the named follow-up "forwarder owned-state-object
     conversion (§5: swap-drain + nudge state as owned objects; supersedes
     the bare-globals relocation of 2026-11-16-extract-forwarder)"; update
     the remaining-clusters sentence ("router/forwarder, admin/handler" →
     admin/handler + chat-SSE drain remain; forwarder completed by this
     plan).
   - `CLAUDE.md` Gotchas (the "Test suite is safe alongside a live
     proxy" bullet): the isolation invariant "before importing `cli.py`
     or `server.py`" gains `forwarder.py` as the third settings-importing
     module.
   - `doc/test-catalog.html` (§Isolation lead, L55–57): the same
     "before any server or CLI module is imported" sentence gains
     `forwarder.py`.
   - Gotchas/architecture elsewhere: fix only file-attribution claims,
     not mechanism prose.
2. `doc/` sweep — enumerated What-to-sync (re-verify each at doc-sync time;
   line numbers drift):
   - `doc/compatibility.html` (the `_CompatState` section, retry-lock
     paragraph): "the forward path in `server.py` reaches it through the
     module-level aliases `_compat_state_lock` / `_compat_retry_lock`" →
     forward path is in `forwarder.py`; `_compat_state_lock` remains
     importable from server.py; `_compat_retry_lock` remains importable from
     both (server keeps it for tests; forwarder imports it).
   - `doc/architecture.html` (request path / config-swap attributions):
     sweep "server.py" file attributions that must read forwarder.py;
     mechanism prose stays.
   - `doc/test-catalog.html:104` ("both `cli.py` and `server.py`") and
     `doc/content.html:101`: update the module attributions.
   - `doc/operations.html` and `README.md`: verified at plan time to
     contain zero "server.py" attributions — explicit no-ops, listed so
     the sweep is checked against a measured set, not an open grep.
   - Bump the `Last updated:` header (L13) and footer stamps on every
     doc page that receives a content edit (repo convention: same
     commit).
   - Re-measure any quoted line count before touching it — prefer removing
     counts (no exact counts maintained).
3. Re-run the two **cumulative** gates in `post` phase — step-3 post and
   tests-repoint post — plus `python scripts/check_doc_anchors.py` via the
   test suite. The intermediate step-1/step-2 post phases assert their
   boundary states and are NOT re-runnable on the final tree (issue 6);
   their GREEN evidence stands as recorded (round reports + calibration
   files). Report final line
   counts (server.py, forwarder.py) in History only.
4. `/update-and-commit` at the end of the round sequence consolidates into
   the plan's single commit (Plan: footer; plans/<id>.md + content.json
   publish step; public mode).

## Work Items

**Files to modify (coder)**: `src/claude_retry_proxy/server.py`; `src/claude_retry_proxy/forwarder.py` (new); `src/claude_retry_proxy/config.py`; `src/claude_retry_proxy/keys.py`; `src/claude_retry_proxy/safety.py`; `src/claude_retry_proxy/compat.py` (one comment line, issue 5).
**Tests to create (tester)**: none — the tester only re-points existing tests in `tests/test_admin.py` and `tests/test_chat_sse.py`, plus the comment-citation sweep — 5 `server.py:<line>` sites
(test_admin.py:2738/2824/2825/3591, test_retry_streaming.py:2804). Tester round 2 (Phase-6 review follow-ups, issues 10-11) additionally touches `tests/test_admin.py` (L5 guards) and, comment-only, `tests/_harness.py`, `tests/test_spawn_isolation.py`, `tests/test_trace.py`.
**Verification scripts to create**: `./tmp/verification/2026-11-16-extract-forwarder-step1.py`, `./tmp/verification/2026-11-16-extract-forwarder-step2.py`, `./tmp/verification/2026-11-16-extract-forwarder-step3.py`, `./tmp/verification/2026-11-16-extract-forwarder-tests-repoint.py`, `./tmp/verification/2026-11-16-extract-forwarder-closure-survey.py`, `./tmp/verification/_forwarder_gate_common.py`.
**Tests to investigate for retirement**: none — `tests/test_compat.py::test_compat_locks_present` keeps verifying the server-surface aliases (server keeps both names), recorded here so the post-move review does not re-litigate it.
**Docs to modify (planner)**: `CLAUDE.md`, `doc/compatibility.html`, `doc/architecture.html`, `doc/test-catalog.html`, `doc/content.html`.

## Guidance for Coder

Lane: you own `src/**` only. You do NOT touch `tests/` (lane separation is
harness-enforced) and you do NOT touch `doc/**`/`CLAUDE.md` (planner owns
docs). The red window is expected (Risks #1) — production code must import
and compile green at every step boundary (`python -c "import
claude_retry_proxy.server"` after each step), the suite need not pass until
the tester's step 4. Do not "fix" failing tests; do not edit moved bodies
(never-fix-in-a-move); do not add imports beyond the whitelist (an unlisted
import is a plan revision — stop and report). `git add src/claude_retry_proxy/forwarder.py` the moment it exists. **Do not run `git commit`** — the lane denies it (round-1 evidence). Each step ends with `git add` of exactly that step's files; the gates' `pre` phases verify the staged-index tree state (plan files only, nothing unstaged) instead of commit cleanliness. Expected RED tests through the window (Risks #1) — do not wait for green, and do not present any state as green inside the red interval. **Coder addendum (round 4, issue 5)**: fix the one falsified comment in `src/claude_retry_proxy/compat.py:52` — "server.py imports it" of COMPAT_FEATURE now reads "forwarder.py imports it" (comment-only; the import lines themselves are correct as landed). **Coder addendum (round 5, issue 9)**: fix the two falsified comments in `src/claude_retry_proxy/server.py` — the module docstring's dependency line (L10-12) drops the stale `re`/`urllib.parse` names (both relocated; keep the list to what server.py actually imports), and `_BestEffortStderr`'s docstring rationale (L125-135) re-words the retry-loop sentence to name forwarder.py (the loop moved; the wrapper's reason — a stderr write failure misread by the retry clause as a connection error — is unchanged). Comment-only: no manifest, whitelist, or import line may change. Verify with the step-3 post gate (must stay GREEN 28/28) after `git add src/claude_retry_proxy/server.py`. Landmark-verify
every deletion range before cutting; a drifted range is a stop-and-report.
Editable-install precondition (SC6) holds for every smoke check.

## Guidance for Tester

Lane: you own `tests/**` only. Your step runs after the coder's three steps.
Work the Step-4 lists — the 60 attribute sites (mechanical re-form) and
the 6 save/restore blocks (tuple-split mechanics) — as a **census, not a
closed set**: the gate hard-fails on ANY state-name code site it sees
outside the tables, and a gate-red site is in scope. Leave the 7 drain
patches, the comment mentions, and all function/constant reads alone. Remember the asymmetry (Risks #1): a green suite does not prove the
re-point is complete — the gate's zero-bare-attribute AND zero-srv-string
checks are the completion proof. Do not weaken, delete, or rename any test.
Run the full suite and report the count and any failure verbatim — a failure
is a plan defect to surface, never something to work around. **Tester addendum (round 2, issues 10-11)**: (a) guard the three save/restore `finally` blocks whose `saved_srv`/`saved_fwd` snapshots initialize empty before the `try` (test_admin.py, inits at 3307/3411/3547) — wrap each block's dict-keyed restore lines in `if saved_srv:` / `if saved_fwd:`; the drain stand-in restore and `shutil.rmtree` stay unconditional; (b) fix four stale comments — test_trace.py:1652's docstring rationale (the retry loop lives in forwarder.py now), tests/_harness.py:31-35 and 41-46 (forwarder.py is a third settings-importing module alongside cli.py/server.py), test_spawn_isolation.py:5-6 (same). Comment/guard-only: the re-point surface (87 forwarder-form sites) must not change. In comment text name modules bare (`forwarder.py`, `cli.py`, `server.py`) — never add package-path strings that could re-classify a file under the spawn-isolation corpus checker. Verify: full suite 531/531, `python scripts/check_spawn_isolation.py` 0 fail, and the tests-repoint gate's `post` phase GREEN 7/7. Do NOT run `git add` (the planner stages at close-out); do not run the gate's `pre` phase (it asserts the pre-repoint state, long gone).

## Guidance for Planner

Step 5 is yours: doc sync per the enumerated checklist, gate re-runs,
History numbers, then the round close-out per Phase 6 (reviewer, issue
resolution, /update-plan, /update-and-commit consolidation). The transient
verification artifacts retire per the repo's file-deletion doctrine
(retire_inventory below).

## Verification Scripts

| Script | Phases | Asserts |
|---|---|---|
| `tmp/verification/2026-11-16-extract-forwarder-step1.py` | pre/post | clean-tree + HEAD pin; step-1 manifest (19); forwarder == exactly 19 names; step-1 whitelist; STATE10 zero-bare in server.py; re-export == 9; `random` relocated; **free-variable closure (both directions)**;
module import probe; banner move |
| `tmp/verification/2026-11-16-extract-forwarder-step2.py` | pre/post | cumulative manifest (28); whitelist + hashlib; STATE13 zero-bare (12
state names + MAX_ENTRIES); re-export == 14; hashlib relocated; closure
(both directions); import probe; nudge banner |
| `tmp/verification/2026-11-16-extract-forwarder-step3.py` | pre/post | cumulative manifest (52 — full re-verify); final whitelist; STATE12+MAX_ENTRIES zero-bare; re-export == final 23; math/re/urlparse relocated; import-line asserts (transforms kept lines, compat 6-name kept set, transforms_common deleted); closure; banners |
| `tmp/verification/2026-11-16-extract-forwarder-tests-repoint.py` | pre/post | tests/ AST scan: zero non-forwarder state-name Attribute sites; zero state-name strings in getattr/setattr/hasattr with non-forwarder base; ≥55 forwarder-form sites; no state-name from-imports of server |
| `tmp/verification/2026-11-16-extract-forwarder-closure-survey.py` | (survey) | plan-time evidence generator (sections 1–5); re-runnable |
| `tmp/verification/2026-11-16-extract-forwarder-hashes.json` | (data) | sha256 manifest per step (19/9/24), regenerated at revision 2 from 529e327 |

**Runtime isolation**: the shared helper carries a launch token (the
editable-install probe's `import claude_retry_proxy.server` string) and
a spawn token (`subprocess.run` for the git probes and the probe), so
`scripts/check_spawn_isolation.py` classifies it as a **spawner** and
the suite's corpus hook enforces compliance. The helper therefore opens
with the canonical block verbatim (`tempfile.mkdtemp(prefix="proxy-probe-")`
+ the three `os.environ["PROXY_*_FILE"]` assignments + `atexit` cleanup),
textually before its first proxy-reference line and its first spawn —
the probe child inherits the isolated environment (no per-call `env=`
plumbing). The git probes never touch the proxy; only the editable-install
probe imports it, in a child. `python scripts/check_spawn_isolation.py`
must report the corpus clean (0 fail) — re-run it after any gate edit.
The suite run itself is isolated by the suite's own module-load binding.
The helper also asserts no stdlib-shadowing filename exists in its own
directory before doing work (`-I` is not used, so `sys.path[0]` is the
script directory).

**retire_inventory** (transient artifacts; quarantine to
`./tmp/retired-artifacts/<plan-id>-<date>/` then user-executed hand-off
deletion at plan close-out): the four gate scripts, the shared helper
`_forwarder_gate_common.py` (retire with the gates — they import it),
the closure survey, the hashes manifest (retire with the gates — the
gates embed its hashes), the calibration `calib-*.txt` / `calib2-*.txt`
outputs, the revision patch scripts (`tmp/plans/patch_plan_rev3*.py`,
`tmp/plans/patch_plan_rev4.py`, `tmp/plans/patch_plan_rev5.py`,
`tmp/plans/patch_plan_rev6*.py`), the coder round's transients
(`tmp/extract-forwarder-step1-slice.py`, `tmp/extract-forwarder-step2-slice.py`,
`tmp/extract-forwarder-step3-slice.py`, `tmp/diag-gate-checks.py` — the
first and last declared by the round's out_of_scope note), the tester's
three transients (`tmp/tester-census-forwarder.py`,
`tmp/tester-repoint-forwarder.py`, `tmp/tester-poll-suite.py` (revised in
place by round 2 — now argument-driven), `tmp/tester-round2-suite.py`), and
`tmp/reports/2026-11-16-extract-forwarder-mega-audit-*.json`.

## History

- 2026-11-16: survey (code >1,000 threshold: server.py only; 10 test files
  >1,500 tracked for a later test-partition plan); user chose
  "Handler/admin split" direction; dependency analysis re-ordered it to
  forwarder-first; user conditioned approval on guideline adherence, cluster
  explanation, dependency report, clean cross-file separation, and reduced
  API exposure — satisfied in this plan; user confirmed "ok".
- 2026-11-16 (session, revision 1): closure survey written + run; urlparse
  reader census (sole reader L538 parse_upstream — relocates);
  staying-leaf-reader census; first test census (raw-text, later corrected);
  leaf whitelist dedupe; sha256 manifests (18/25/9); plan written; gates
  RED-calibrated (step1-pre GREEN, all other phases RED, expected reason:
  forwarder.py absent). Gates run WITHOUT `-I` (isolated mode drops the
  script directory from sys.path).
- 2026-11-16 (session, revision 2 — mega-audit iteration 1): workflow
  `wf_248230fc-ec3` (single-read mode, 9 lenses, 60 findings: 19 High /
  22 Medium / 19 Low; report at `tmp/reports/2026-11-16-extract-forwarder-
  mega-audit-2026-11-16.json`). All High+Medium fixed in this revision:
  two step-boundary NameErrors (nudge-after-forward-path;
  `_swap_abort_tuple`→`_error_body`) fixed by re-partitioning 19/9/24 with
  a per-step free-variable closure gate; STATE12 mis-scoping in step-1/2
  gates fixed with step-scoped sets; the 105-site census re-pinned to 60
  attribute sites + 6 string-form blocks (comments excluded); frozen
  surface re-derived 28→23 (docstring-only "test imports" pruned; TTL and
  CLIENT_USER_AGENT_* re-measured as real attr reads); transforms_chat/
  transforms_response/`_compat_retry_lock` kept in server (test-code
  readers — Document Overrides #4); Plan Metadata JSON block added;
  Rollback section added; isolation + retire_inventory declared; CLAUDE.md
  compat.py/Future Work sync added; guide citations corrected to §6/§7.
  Low findings fixed in the same pass (arithmetic, counts, section cites,
  hashlib deletion instruction, step-2 moves-list completion, hashlib
  keeps, `_ADMIN_NAME_RE` annotation). Gate design consulted
  `~/.claude/guides/engineering-doctrine.md` (applied: gate
  satisfiability/teeth — RED calibration; namespace-patch semantics and
  patched-callee blind spots — the re-export/patch census; evidence on disk
  is a snapshot — hashes.json).
- 2026-11-16 (session, revision 3 — mega-audit iteration 2): workflow `wf_a56cdac1-45e` (single-read, 9 lenses, 51 findings: 7 High / 22 Medium / 22 Low). Two High root causes fixed: `_compat_retry_lock` was missing from FORWARDER's step-3 whitelist (the moved impl bare-reads it at L1245/1412/1497/1529 — dual reader, not sole reader; forwarder's compat set is 25, server keeps 6) and the gate helper failed the repo's spawn-isolation corpus checker (no canonical block textually before the first launch/spawn token) — the canonical block now opens `_forwarder_gate_common.py` and the probe child inherits the isolated env (the dead per-call `env=` plumbing removed). Medium fixes: Rollback re-written (branch by landed state; staged-forwarder recovery via `git restore --staged`; revert-only, never reset; mid-step interruption rule), Global-name closure added to the gate, repo_mode "Public", verification_scripts shaped `./tmp/verification/*.py`, marker sections added, step-2 gate set renamed STATE13, compat kept-set parenthetical corrected (2 main()-read + 3 reader-less + 1 test-read), staging-commit instruction added, gate-before-suite ordering, 27-string count, seven-def count, doc sweep re-scoped (test-catalog.html:104 + content.html:101 added; operations.html/README.md verified no-ops; Last-updated stamps), tester import form pinned, retire_inventory completed, test_retry_streaming.py added to tester_files. Dismissed with evidence: `_rewrite_json_response` surfacing (finding: "no test reads it" — test_nesting.py:849/856 reads `srv._rewrite_json_response`, AST-verified; the name stays in the 23-name surface). `Global`-name and store-side closure notes: moved defs' `global` declarations all name moved state (verified by the new gate check).
- 2026-11-16 (session, revision 4 — mega-audit iteration 3): workflow `wf_419d4ddc-625` (36 findings — 2 High / 13 Medium / 21 Low; below the ≥3-High threshold and at the 3-iteration cap → exit condition met). High fixed: the tests-repoint gate could not see the restore-loop half of the six save/restore blocks (`setattr(srv, name, value)` loops carry no constant/attribute/tuple signal) — the plan now mandates explicit attribute-form restores (two containers, per-name statements) AND the gate gained a loop-form-setattr detector plus a forwarder-binding scope check. Mediums fixed: manifest guard, module import probe in every post phase, `global`-decl post asserts, server-side closure mirror (SC5 both directions), trailing-comment text assertions (byte-hash blind spot), doc_files/coder_files/tester_files sync (content.html in; operations/README out as verified no-ops; leaf docstring files added as coder files — config.py/keys.py/safety.py attribution lines), step-2 row STATE13, staging-commits Document Override #5, CLAUDE.md/test-catalog isolation-invariant sync, citation-scope reconciliation, sixth finally pinned (3718–3719), L70 comment moves with its assign, defs/assigns wording, 5-pruned-names reconciliation, move-then-shape citation §6. Accepted residual (documented, not fixed): the stdlib-shadow guard runs after the imports it protects — the import-time window is unprotectable in-process; tmp/verification is planner-owned and the corpus checker plus quarantine cover the rest. Remaining Low findings are recorded in tmp/reports/2026-11-16-extract-forwarder-mega-audit-2026-11-16-iter3.json and intentionally not individually fixed (cap reached; gate-verified surfaces unaffected).
- 2026-11-16 (session, coder round 1): launcher `bldy6wxed`-detached (PID 60256), finished 15:24, exit 0. **Step 1 complete**: swap-drain cluster + `_error_body` moved byte-identical (19/19 manifest), 37 attribute re-forms + 2 global-decl edits, re-export 9 names, `random` relocated — tree STAGED, not committed (issue 3). Gate post 20/22 GREEN; the 2 RED were gate defects (issues 1–2), fixed in planner revision 5; step-1 post now 18/18 GREEN, step-2 pre 7/7 GREEN on the staged tree. Lines: server.py 4,233; forwarder.py 236. Move mechanics: landmark-verified slice script; 3-blank seams collapsed to 2 (deliberate, declared). Round-2 launcher: fresh (never resume), resumes at step 2. **Round 2** (launcher attempt -2, 15:28): **step 2 complete** — 9/9 manifest byte-identical, hashlib relocated, 14-name re-export, step-2 post GREEN 17/17, staged. Blocked at step 3 by the gate's urlparse plain-import bug (issue 4, fixed in revision 6; step-3 pre now GREEN 7/7). Round-3 launcher: fresh, resumes at step 3. **Round 3** (attempt -3): **step 3 complete** — 24/24 manifest byte-identical, cumulative 52/52 re-verified, step-3 post GREEN 28/28, math/re/urlparse + sole-reader leaf relocations, transforms_common line deleted, the three leaf docstrings fixed, tree staged. All three coder steps done; two non-blocking observations filed (issues 5–6, resolved in revision 6; coder round 4 carries the one compat.py comment line). Tester round: next. **Tester round** (2026-11-16, SUCCESS): gate-first ordering held — tests-repoint pre GREEN (60 bare attribute sites, 6 srv tuple blocks, 6 loop restores — the census matched measurement exactly), then the re-point: 34+26 attribute sites re-pointed, the 6 save/restore blocks split (saved_srv + saved_fwd, explicit per-name attribute-form restores), 5 nested-scope forwarder bindings, 5 citation rewrites; post GREEN on all 7 hard checks (87 forwarder-form sites). Full suite: **531/531 passed, 0 failed, 0 skipped** — red window closed. Spawn-isolation corpus 0 fail. Reviewer: next.
- 2026-11-16 (session, Phase 6 review): adversarial reviewer subagent, verdict **FIX-FIRST** — the move itself clean: 52/52 byte-identity independently re-derived against 529e327; runtime seam verified (`srv.forwarder is forwarder`, all 23 re-exports identical objects, zero state names leaked onto server, `srv._compat_retry_lock is forwarder._compat_retry_lock is compat._compat_retry_lock`); only the 7 documented `srv._drain_for_swap` patches exist and still work. Must-fix applied immediately: H1 (issue 7) and M2 (issue 8). Lows routed: L3/L4 stale comments (issues 9-10, coder round 5 + tester round 2), L5 finally guards (issue 11, tester round 2), L6 retire_inventory (issue 12, fixed in revision 6). The reviewer re-ran both cumulative gates GREEN before the fix rounds (step-3 post 28/28, tests-repoint post 7/7). Revision 6 records the findings, adds the two fix rounds' guidance, and completes retire_inventory.
- 2026-11-16 (session, revision 8b): row 3's report linked too — the close-out orphan scan surfaced it (the interim filename filter had excluded the basename containing 'coder'); identity verified (issue_id matches, type issue), row Resolved, resolution (staged-index progression) verified by the gate record.
- 2026-11-16 (session, revision 8): the six on-disk issue reports linked
  from their Resolved Issue Log rows as markdown links (Route A's
  retirement derivation is link-based; bare parenthetical slugs collect
  zero candidates and leave presence-means-open files behind at
  close-out). No row text otherwise changed.
- 2026-11-16 (session, Phase-6 fix rounds + Step 5 close-out): coder round 5 (issue 9) and tester round 2 (issues 10-11) both exit 0. Launcher note: rounds are sequential per plan — the tester launch was refused exit 2 while the coder round was live (the error names the coder lock); memory updated. Fix rounds verified: tests-repoint post GREEN 7/7 before and after (87 forwarder-form sites unchanged), spawn-isolation corpus 0 fail, suite 531/531 after round 2. Issue 13 filed (gate binding-scope blind spot — accepted residual, row is the record). Step-5 doc sync (planner lane): CLAUDE.md — Structure gains the forwarder.py entry, server.py entry rewritten, compat.py parenthetical now names forwarder.py as the orchestration home, isolation invariant lists all three settings-importing modules, Future Work "Five more followed" + step-6 forwarder paragraph + named owned-state-object follow-up + remaining clusters (admin/handler, chat-SSE drain); doc/architecture.html — request path names the `_forward_core` hand-off, retry-loop attribution; doc/compatibility.html — retry-lock paragraph (forwarder imports `_compat_retry_lock`, server keeps the test-facing aliases); doc/test-catalog.html — both settings-import sentences; doc/content.html:101 verified no-op (generic path convention); operations.html/README.md re-verified no-ops; stamps bumped on the three edited pages; rule-keyword count 0/0/0 before == after (nothing deleted). Both cumulative gates re-run GREEN on the fully staged tree (step-3 post; tests-repoint post 7/7). Full suite re-run after the doc sync: 531/531. Final line counts: server.py 2,576; forwarder.py 1,908 (from 4,445 pre-plan).

## Final Results

- **Completed:** 2026-11-16 — **COMPLETED**.
- **What landed:** the upstream forward path extracted from `server.py` (4,445
  lines pre-plan) into `forwarder.py` (1,908) as three byte-identical verbatim
  steps (sha256 manifests 19/9/24, cumulatively re-verified 52/52 against HEAD
  `529e327`), leaving `server.py` at 2,576 lines with the handler / admin /
  CLI / mode-dispatch clusters. Frozen surface: exactly 23 names re-exported by
  `server.py` (read-only; state names deliberately never re-exported —
  attribute form mandatory). Import direction parent→sibling only
  (`forwarder.py` never imports `server.py`).
- **Files changed:** `src/claude_retry_proxy/{server.py (M), forwarder.py (A),
  compat.py, config.py, keys.py, safety.py}`; `tests/{test_admin.py,
  test_chat_sse.py, test_retry_streaming.py, test_trace.py, _harness.py,
  test_spawn_isolation.py}`; `CLAUDE.md`,
  `doc/{architecture,compatibility,test-catalog}.html`.
- **Test results:** 531 passed / 0 failed / 0 skipped (tester rounds 1 and 2;
  re-run green after the doc sync). Both cumulative gates GREEN on the fully
  staged tree (step-3 post; tests-repoint post 7/7 at 87 forwarder-form
  sites). Spawn-isolation corpus 0 fail.
- **Issues:** 13 Resolved, 0 Open, 0 deferred; accepted residuals recorded
  in-row (issue 13, gate binding-scope blind spot) and in History (iter-3 cap).
- **Named follow-ups:** forwarder owned-state-object conversion (guide §5 —
  swap-drain + nudge state as owned objects); the remaining clusters
  (admin/handler, chat-SSE drain) are tracked by the /refactor-split survey.

## Plan Metadata

```json
{
  "plan_id": "2026-11-16-extract-forwarder",
  "steps": [
    "Step 1: swap-drain cluster + _error_body -> forwarder.py (19 names)",
    "Step 2: retry-nudge cluster -> forwarder.py (9 names)",
    "Step 3: transport helpers, forward path, tier/rewrite -> forwarder.py (24 names)",
    "Step 4: tester re-points 60 attribute sites + 6 string-form blocks",
    "Step 5: planner doc sync + final verification"
  ],
  "coder_files": ["src/claude_retry_proxy/server.py", "src/claude_retry_proxy/forwarder.py", "src/claude_retry_proxy/config.py", "src/claude_retry_proxy/keys.py", "src/claude_retry_proxy/safety.py", "src/claude_retry_proxy/compat.py"],
  "tester_files": ["tests/test_admin.py", "tests/test_chat_sse.py", "tests/test_retry_streaming.py", "tests/_harness.py", "tests/test_spawn_isolation.py", "tests/test_trace.py"],
  "doc_files": ["CLAUDE.md", "doc/compatibility.html", "doc/architecture.html", "doc/test-catalog.html", "doc/content.html"],
  "verification_scripts": [
    "./tmp/verification/2026-11-16-extract-forwarder-step1.py",
    "./tmp/verification/2026-11-16-extract-forwarder-step2.py",
    "./tmp/verification/2026-11-16-extract-forwarder-step3.py",
    "./tmp/verification/2026-11-16-extract-forwarder-tests-repoint.py",
    "./tmp/verification/2026-11-16-extract-forwarder-closure-survey.py",
    "./tmp/verification/_forwarder_gate_common.py"
  ],
  "document_overrides": [
    "§5 state doctrine deferred as named follow-up (bare-globals verbatim relocation)",
    "state names never re-exported (attribute form mandatory)",
    "frozen surface exactly 23 names (measured caller-read ∪ test-code reads)",
    "dual-reader leaf imports stay in server.py when tests read them there (transforms_chat, transforms_response, _compat_retry_lock)"
  ],
  "repo_mode": "Public"
}
```

## Audit Accumulation

- `issues_resolved_since_audit`: 0
- `steps_changed_since_audit`: 0
- `files_changed_since_audit`: 0
- Last Updated: 2026-11-16 (mega-audit iteration 3 completed: 36 findings — 2 High / 13 Medium / 21 Low; all High+Medium fixed; cap reached, exit condition met. History: iteration 1 — 60 findings 19H/22M/19L; iteration 2 — 51 findings 7H/22M/22L; counters reset each run)
