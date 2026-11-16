# Plan: 2026-11-17-extract-chat-sse

**Plan ID:** 2026-11-17-extract-chat-sse
**Created:** 2026-11-17

## Summary

Extract the **chat-SSE cluster** out of `src/claude_retry_proxy/server.py`
(2,576 wc lines at base `63554b7` — one of two code files over the 1,000-line
threshold) into a new sibling `src/claude_retry_proxy/chat_sse.py`, as a
**pure structural verbatim move**: zero behavioral changes, bodies
byte-identical to their pre-move source, and one relocated shared constant.

The cluster is one concept: **converting an OpenAI chat-completions SSE stream
into Anthropic Messages SSE**. Its members are
`_stream_chat_sse_to_anthropic` (server.py:581–1456, 876 lines),
`_log_response_cap_exceeded` (1509–1518, 10 lines — single caller, inside the
cluster), and the six chat/drain constants
(`SSE_EVENT_DELIMITER`, `MAX_CHAT_TOOL_PENDING_BYTES`,
`MAX_CHAT_TRACKED_TOOL_INDEXES`, `MAX_CHAT_OPEN_TOOL_BLOCKS`,
`MAX_DRAIN_BYTES`, `MAX_DRAIN_SECONDS`; server.py:263–273) — **897 moved
lines**.

**Extraction shape: a handler mixin.** `chat_sse.py` defines
`class ChatSSEHandlerMixin`; `server.py` changes its class statement to
`class ProxyHandler(ChatSSEHandlerMixin, http.server.BaseHTTPRequestHandler):`.
A mixin leaves every moved body byte-identical (`self` is unchanged) and
leaves every call site untouched — `self._stream_chat_sse_to_anthropic(...)`
at server.py:406 resolves through the MRO. Free functions taking the handler
would require rewriting every `self.` in ~900 lines, destroying the
review-by-diff property the guide's move discipline depends on.

**Three names deliberately do not move:**

| Name | Why it stays |
|---|---|
| `_sse_event` (server.py:553–580) | Two staying callers (`_stream_upstream_response`:373, `_stream_response_sse_fallback`:1502) and two test call sites (`test_chat_sse.py:4266`, `test_nesting.py:923` via `object.__new__(srv.ProxyHandler)`) reach it through `ProxyHandler`; it is a shared leaf, not a cluster member. |
| `_DISCONNECT_ERRORS` (server.py:163–169) | Shared leaf with 5 staying readers and 1 moving reader. A sibling cannot import its parent, so it **relocates to `forwarder.py`** (step 1) — the repo's existing shared transport leaf, which already hosts `_error_body`, a shared response-path leaf imported by `server.py`. |
| `_stream_response_sse_fallback`, `_log_client_disconnect` | Distinct concepts (response-mode defensive fallback; disconnect logging, 4 call sites). They are neighbours, not members. |

**Line outcome (measured after implementation, 2026-11-17; post-Step-3):**
`server.py` 2,576 → **1,663**; `chat_sse.py` **936** new lines (897 moved +
header/imports); `forwarder.py` 1,908 → **1,917** (the relocated constant
block). No test file
changes: the chat-SSE tests drive the server end-to-end (the two that build a
bare handler with `object.__new__(srv.ProxyHandler)` reach `_sse_event`, which
does not move), and no test references either moved method.

**Out of scope:** the admin/handler extraction and the `forwarder.py`
owned-state-object conversion (the two other named follow-ups); the
`test_chat_sse.py` (5,051 lines) feature-area partition — a separate plan
(guide §8 test-partition track).

## Repo Mode

**Public.** `detect_repo_mode.py` → `public` (2026-11-17). Plan publishes to
`plans/` with a `Plan:` footer at consolidation.

## Success Criteria

Each is mechanically checkable; the step gates are RED against the pre-change
tree and GREEN after their step.

1. `src/claude_retry_proxy/chat_sse.py` exists, defines
   `class ChatSSEHandlerMixin`, and its two methods are **byte-identical** to
   the `63554b7` segments of `ProxyHandler` (sha256 of the extracted source
   text, compared line-for-line).
2. `server.py` post-move: **zero** module-level defs/assigns of the eight
   moved names; `ProxyHandler`'s base list is exactly
   `(ChatSSEHandlerMixin, http.server.BaseHTTPRequestHandler)`;
   `from .chat_sse import ChatSSEHandlerMixin` is present.
3. `chat_sse.py`'s import block equals the pinned whitelist exactly and
   contains **no** import of `.server` (sibling → parent is illegal).
4. `_DISCONNECT_ERRORS` is defined **only** in `forwarder.py` (verbatim, with
   its six-line comment block); `server.py` imports it from `.forwarder`; the
   runtime attribute is the pinned 3-tuple.
5. Free-variable closure of `chat_sse.py`: every bare `Name` load in both
   methods resolves against method locals ∪ the module's defs/assigns/imports
   ∪ builtins (guide §7.3 scope formula, extended with nested `def`/`class`
   names as local bindings — the probe below showed the formula as written
   reports every nested helper as unresolved).
6. `python tests/test_claude_proxy.py` passes with the full-suite count
   preserved at **531** (measured at plan authoring), no test file edited, and
   `python scripts/check_spawn_isolation.py` exits 0 — every verification
   script in the plan's corpus carries the canonical isolation block before
   its first proxy import and first spawn.
7. `server.py` line count measured and recorded after the move (post-Step-3:
   **1,663**; `chat_sse.py` 936, `forwarder.py` 1,917); `wc -l` re-measured,
   never estimated.

## Document Overrides

| Document | Rule Overridden | Reason |
|----------|----------------|--------|
| refactor-split guide §4 ("a class is warranted iff the cluster owns state with a lifecycle and invariants") | The extraction target is a **mixin class**, not an instantiated state-owning class. | The class here is a method grouping inherited by the framework's `BaseHTTPRequestHandler` subclass; it owns no state and is never instantiated on its own. The byte-lock of a verbatim move requires it: free functions taking the handler would rewrite every `self.` reference inside 900 lines. |
| refactor-split guide §2 (deletion test: a member with an outside home is a squatter) | `_DISCONNECT_ERRORS` moves **with the plan** although it is not a cluster member. | The moving body reads it by bare name and the new sibling may not import its parent. The guide's own §2 external-dependency rule resolves this: a stay-behind dependency of a moved body is a shared leaf and gets a leaf module home — here `forwarder.py`, which imports no sibling back (so §7.2's two-direction closure holds), and already hosts `_error_body`, the same pattern. |
| refactor-split guide §7.3 (the AST-gate scope formula) | The step-2 gate adds **nested `def`/`class` names** to a function's local scope. | The formula as written reports every nested helper (`write`, `terminal`, `handle_frame`, … 18 names in the moved body) as unresolved, so a byte-identical move could never pass. Measured by the satisfiability probe recorded in the Calibration record. |

## Membership and Blast Radius (guide §2/§6 record)

- **Concept test:** one concept — *converting a chat-completions SSE stream
  into Anthropic Messages SSE*, including its stream bounds. The two methods
  and six constants are instances/aspects of it.
- **Substitution test:** callers treat it through one API —
  `self._stream_chat_sse_to_anthropic(...)` (server.py:406) and
  `self._log_response_cap_exceeded(...)` (server.py:1319). Both resolve
  unchanged after the move.
- **Deletion test:** delete the cluster and `_stream_chat_sse_to_anthropic`
  has no home. `_log_response_cap_exceeded` has exactly one caller, inside the
  cluster → member. `_sse_event` would survive (three callers, two staying) →
  squatter, stays behind. `_DISCONNECT_ERRORS` survives (five staying readers)
  → shared leaf, relocated to `forwarder.py`.
- **Blast radius:** the moved bodies make **zero writes** to staying module
  state (no `global` statements anywhere in the region) and touch exactly
  **one** staying call site (server.py:406, unchanged by inheritance). The
  moved module reads `forwarder.py`/`sinks.py`/`settings.py`/`nesting.py`/
  `transforms_chat.py` leaves and nothing else. This is the lowest-blast-radius
  remaining cluster; the admin/handler cluster is the opposite (it rebinds
  `_current_config`, `_vendors`, `_shutdown_state` through `global`).
- **Ordering:** step 1 (`_DISCONNECT_ERRORS` → `forwarder.py`) must land
  before step 2, because `chat_sse.py` imports the constant from
  `forwarder.py`; each boundary is green on its own.

## Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| Range drift between plan authoring and implementation | A literal line range deletes the wrong text | Step 2 gives ranges as **AST boundaries** (`FunctionDef.lineno`/`end_lineno`), re-derived immediately before cutting; the small ranges (constants, comment, one-line edits) are given as exact text blocks with an occurrence-count precheck. |
| MRO regression: a moved name is not found because the base list was edited wrongly | `AttributeError` on every chat-mode stream | Gate asserts `__bases__`, `__dict__` membership, and method identity (`server.ProxyHandler.X is chat_sse.ChatSSEHandlerMixin.X`). |
| Hidden test coupling to the moved methods | Red suite the coder may not fix (test edits are the tester's lane) | Census already run: `grep` over `tests/` shows zero references to `_stream_chat_sse_to_anthropic` / `_log_response_cap_exceeded`; `_sse_event` (the only test-reached name) stays. Tester re-confirms in Step 3. |
| Import-whitelist omission in the new module | `NameError` at the first chat stream | Closure gate (guide §7.3 formula) + exact whitelist assertion; the gate is RED before the move. |
| `_DISCONNECT_ERRORS` left defined in both places | Two divergent copies (silent) | Gate asserts the constant is absent from `server.py`'s own assigns and present in `forwarder.py`. |

## Rollback

One cluster, one plan, one commit. Interim per-step commits are staging and
are folded at `/update-and-commit` Step 10 consolidation; reverting the plan's
commit restores `server.py`, `forwarder.py`, and removes `chat_sse.py` in one
`git revert`.

## Issue Log

Rows ordered newest-first (latest issues at top). New issues are prepended; resolved issues stay in place with updated status.

| Issue | Status | Found | Resolved | Resolved By |
|-------|--------|-------|----------|-------------|

## Proposed Changes

1. **Step 1:** Move `_DISCONNECT_ERRORS` (comment block + constant, server.py:163–169) verbatim into `forwarder.py`, and import it into `server.py` from `.forwarder`.
   - **Delete from `server.py`** — this exact block, which must match exactly once (precheck `src.count(block) == 1`), together with the single blank line that follows it:
     ```
     # Client-disconnect errors: raised when the client closed the connection
     # before we finished writing the response (e.g. it timed out during a long
     # retry storm). These are expected under load; we log a single line and a
     # trace event instead of letting socketserver print a traceback per request.
     # ConnectionAbortedError covers Windows WinError 10053; ConnectionResetError
     # covers WinError 10054 and POSIX ECONNRESET; BrokenPipeError covers POSIX EPIPE.
     _DISCONNECT_ERRORS = (ConnectionResetError, BrokenPipeError, ConnectionAbortedError)
     ```
     It sits between the `_shutting_down = False` line and `def _nesting_limit_message`; leave exactly two blank lines between them afterwards.
   - **Insert into `forwarder.py`** at the top of the module-constant area — immediately before the comment line `# Thread-safe config access (read by worker threads, written by admin API)` — this block followed by two blank lines:
     ```
     # Client-disconnect errors: raised when the client closed the connection
     # before we finished writing the response (e.g. it timed out during a long
     # retry storm). These are expected under load; we log a single line and a
     # trace event instead of letting socketserver print a traceback per request.
     # ConnectionAbortedError covers Windows WinError 10053; ConnectionResetError
     # covers WinError 10054 and POSIX ECONNRESET; BrokenPipeError covers POSIX EPIPE.
     _DISCONNECT_ERRORS = (ConnectionResetError, BrokenPipeError, ConnectionAbortedError)
     ```
   - **Rewrite the first two lines of `server.py`'s `from .forwarder import (` block** (currently lines 49–50) to add the name, keeping the line count:
     ```
     from .forwarder import (_DISCONNECT_ERRORS, _client_user_agent, _drain_for_swap,
                             _error_body, _forward_request_impl, _note_swap_eviction,
     ```
     Lines 51 onward of the block are unchanged.
   → coder verify (auto): `_DISCONNECT_ERRORS` appears in `forwarder.py` and not as a module-level assignment in `server.py`; `server.py`'s `from .forwarder import` list contains the name.
   → coder verify (scripted): `python ./tmp/verification/2026-11-17-extract-chat-sse-step1.py` exits 0.
   → tester verify: the target paths of affected tests still pass (Step 4 runs the full suite).

2. **Step 2:** Create `chat_sse.py` with the constants and a `ChatSSEHandlerMixin` holding the two methods byte-identically; rewire `server.py`.
   - **Create `src/claude_retry_proxy/chat_sse.py`** with exactly this header, then the two method bodies inserted verbatim (see the extraction recipe below), indented as class members (4 spaces):
     ```python
     """Chat-mode SSE conversion for the proxy HTTP handler.

     Extracted verbatim from `server.py` (plan 2026-11-17-extract-chat-sse) as the
     `ChatSSEHandlerMixin` the handler inherits. The module converts an OpenAI
     chat-completions SSE stream into Anthropic Messages SSE events and owns the
     chat-mode frame/drain bounds. Bodies are byte-identical to their pre-move
     source; `_sse_event` stays on the handler in `server.py` and resolves through
     the class MRO.
     """

     import json
     import sys
     import time
     import uuid

     import httpx2

     from . import forwarder
     from .forwarder import (_DISCONNECT_ERRORS, _error_body, _note_swap_eviction,
                             _retry_nudge_arm, _retry_nudge_messages_bytes,
                             _swap_epoch_changed, _touch_upstream_activity)
     from .nesting import check_payload_nesting, nesting_event
     from .settings import SETTINGS
     from .sinks import log_trace
     from .transforms_chat import _map_chat_finish_reason


     SSE_EVENT_DELIMITER = b"\n\n"

     # Chat-mode SSE tool-call conversion bounds (mirror the per-frame event buffer).
     MAX_CHAT_TOOL_PENDING_BYTES = 64 * 1024
     MAX_CHAT_TRACKED_TOOL_INDEXES = 32
     MAX_CHAT_OPEN_TOOL_BLOCKS = 32

     # Post-finish drain bounds: after a finish_reason chunk the read loop keeps
     # reading briefly to capture trailing usage / tool_call frames.
     MAX_DRAIN_BYTES = 64 * 1024
     MAX_DRAIN_SECONDS = 5


     class ChatSSEHandlerMixin:
         """Chat-mode SSE conversion methods for ProxyHandler.

         Mixed into `server.ProxyHandler` ahead of `BaseHTTPRequestHandler`; the
         methods of this class resolve `_sse_event` and `wfile` through the MRO.
         """
     ```
     Then paste `_stream_chat_sse_to_anthropic` and `_log_response_cap_exceeded`
     verbatim from `server.py` (same indentation, same docstrings, same
     comments), separated by one blank line. Extract them with this recipe,
     run from the repo root **before** deleting them:
     ```
     python - <<'PY'
     import ast, pathlib
     p = pathlib.Path("src/claude_retry_proxy/server.py")
     src = p.read_text(encoding="utf-8")
     lines = src.splitlines(keepends=True)
     tree = ast.parse(src)
     cls = next(n for n in tree.body
                if isinstance(n, ast.ClassDef) and n.name == "ProxyHandler")
     for name in ("_stream_chat_sse_to_anthropic", "_log_response_cap_exceeded"):
         fn = next(n for n in cls.body
                   if isinstance(n, ast.FunctionDef) and n.name == name)
         print("### " + name + " " + str(fn.lineno) + "-" + str(fn.end_lineno))
         print("".join(lines[fn.lineno-1:fn.end_lineno]), end="")
     PY
     ```
   - **Add to `server.py`'s import block** immediately after the `from . import sinks` line:
     ```
     from .chat_sse import ChatSSEHandlerMixin
     ```
   - **Change the class statement** (line 271 in the tree as step 1 leaves it; line 295 at base `63554b7`):
     - old: `class ProxyHandler(http.server.BaseHTTPRequestHandler):`
     - new: `class ProxyHandler(ChatSSEHandlerMixin, http.server.BaseHTTPRequestHandler):`
   - **Delete from `server.py`** the six-constant block plus its now-empty banner. Precheck each block matches exactly once.
     ```
     # ---------------------------------------------------------------------------
     # Response model rewriting helpers
     # ---------------------------------------------------------------------------

     SSE_EVENT_DELIMITER = b"\n\n"

     # Chat-mode SSE tool-call conversion bounds (mirror the per-frame event buffer).
     MAX_CHAT_TOOL_PENDING_BYTES = 64 * 1024
     MAX_CHAT_TRACKED_TOOL_INDEXES = 32
     MAX_CHAT_OPEN_TOOL_BLOCKS = 32

     # Post-finish drain bounds: after a finish_reason chunk the read loop keeps
     # reading briefly to capture trailing usage / tool_call frames.
     MAX_DRAIN_BYTES = 64 * 1024
     MAX_DRAIN_SECONDS = 5

     ```
     Delete the fenced block **through both trailing blank lines** — the blank line shown inside the fence and the one after it — leaving exactly two blank lines before the `# HTTP request handler` banner (audit finding `audit-l5-step2-deletion-text`).
   - **Delete the two method ranges** from `ProxyHandler`, using the AST recipe's `lineno`–`end_lineno` re-derived on the tree as it stands (at base `63554b7` they are 581–1456 and 1509–1518; **never compute the shift by hand**). Delete each method's lines plus exactly the single blank line that follows it. After both deletions every remaining method is separated by exactly one blank line, and the class is still terminated by two blank lines before `class _ProxyHTTPServer`.
   → coder verify (auto): `chat_sse.py` exists; `server.py` has no class-body `def` named `_stream_chat_sse_to_anthropic` or `_log_response_cap_exceeded` and no module-level assign of the six constants; `python -m compileall -q src/claude_retry_proxy` succeeds (no import-bearing one-liner — the isolated gate script below is the import check).
   → coder verify (scripted): `python ./tmp/verification/2026-11-17-extract-chat-sse-step2.py` exits 0.
   → tester verify: Step 4.

3. **Step 3 (revision, coder):** Remove the now-unused `_map_chat_finish_reason` name from `server.py`'s `transforms_chat` import block — its only two readers moved with the cluster and no test reads it through the server surface (audit finding `audit-l24-unused-import`). `chat_sse.py` keeps its own import.
   - Replace the block so it reads exactly:
     ```
     from .transforms_chat import (_anthropic_to_chat, _chat_to_anthropic,
                                   _transform_anthropic_messages_to_chat,
                                   _transform_anthropic_tool_choice_to_chat,
                                   _transform_anthropic_tools_to_chat)
     ```
     Delete the `_map_chat_finish_reason,` name and re-wrap; the other five names stay — they have test-code readers (`_require_server_func`).
   - Also correct the mixin docstring's contract sentence in `chat_sse.py`: `wfile` is an instance attribute installed by `BaseHTTPRequestHandler.__init__`, not an MRO lookup — the docstring must say the methods resolve `_sse_event` through the MRO and use the handler's `wfile`.
   → coder verify (auto): `grep -c "_map_chat_finish_reason" src/claude_retry_proxy/server.py` returns 0; `python -m compileall -q src/claude_retry_proxy` succeeds.
   → coder verify (scripted): `python ./tmp/verification/2026-11-17-extract-chat-sse-step2.py` still exits 0 (it imports the package under the isolation block).
   → tester verify: Step 4's full-suite run covers it.

4. **Step 4:** Full-suite and structural verification of the move; no test changes.
   → tester verify: `python tests/test_claude_proxy.py` reports **531 passed / 0 failed** (the plan-authoring baseline is 531 registered tests; the count must be unchanged).
   → tester verify: `python ./tmp/verification/2026-11-17-extract-chat-sse-step2.py` exits 0 — it carries the canonical isolation block, and its MRO/identity assertions are the structural check.
   → tester verify: `python scripts/check_spawn_isolation.py` exits 0 (0 fail) — the corpus rule every verification script owes.
   → tester verify: consumer census for the six relocated constants — no test reads them as `server.<NAME>` (verified by the planner on 2026-11-17: only prose/comment mentions in `tests/test_chat_sse.py`), and no test references either moved method by attribute; report both findings.

5. **Step 5:** Planner doc sync, closure, and final measurement.
   → Evidence: `git status --porcelain` shows only plan-owned files when the doc step runs; `wc -l src/claude_retry_proxy/server.py src/claude_retry_proxy/chat_sse.py src/claude_retry_proxy/forwarder.py` output recorded in `## Final Results`; `python scripts/check_doc_anchors.py` exits 0; `python scripts/check_spawn_isolation.py` exits 0; `retire_inventory` recorded in Plan Metadata and `## Final Results` written before the plan is presented for approval.

## Guidance for Coder

**Files to modify:** `src/claude_retry_proxy/forwarder.py`, `src/claude_retry_proxy/server.py`, `src/claude_retry_proxy/chat_sse.py` (new).

**Step-by-step with verification:** each step above has coder checks tagged
`(auto)` or `(scripted)`. The coder self-verifies `(auto)` checks and runs the
provided script for `(scripted)` checks. Tester owns the behavioral checks.

**Module-surface count table**

| Class | Count | Detail |
|---|---|---|
| Behavioral changes | **0** | Pure verbatim move; no logic, string, or signature edits. |
| Module-surface changes | **20** | Step 1: +1 name to `forwarder.py`'s surface (`_DISCONNECT_ERRORS`), −1 own def in `server.py` (kept as an import binding). Step 2: −8 names from `server.py`'s own definitions (2 methods + 6 constants), +9 names into `chat_sse.py` (1 class + 2 methods + 6 constants). Step 3: −1 imported name from `server.py` (`_map_chat_finish_reason`). Sum: 1 + 1 + 8 + 9 + 1 = 20. |
| Implementation changes | **10** | Step 1: 1 deletion block, 1 insertion block, 1 import-block rewrite (3). Step 2: 1 new file, 1 import line added, 1 class statement edited, 2 method deletions, 1 constant-block deletion (6). Step 3: 1 import-line edit (1). |

**Constraints**

- Verbatim only: no renaming, reordering, reformatting, annotation or f-string
  edits, no bug fixes inside the moved text (guide §8). A defect noticed
  mid-move is filed, not fixed.
- Do not move `_sse_event`, `_stream_response_sse_fallback`,
  `_log_client_disconnect`, or `_crlf_safe`.
- Do not add any import to `chat_sse.py` beyond the whitelist in Step 2.
- `git add src/claude_retry_proxy/chat_sse.py` the moment it exists.
- The step gates are step-local: re-run step 1's gate only before/after step 1.

## Guidance for Tester

**Tests to create:**
- No tests to create. The move is behavior-neutral and the existing suite is
  the regression net; the chat-SSE coverage (77 tests in `tests/test_chat_sse.py`)
  drives the code end-to-end through the server.

**Tests to investigate for retirement:**
- No test obsolescence identified. No function, endpoint, or behavior is
  removed or changed; only the module a method is defined in moves, and no
  test imports either moved method (census: only `_sse_event`, which stays,
  is reached by tests through `obj.__new__(srv.ProxyHandler)`).
- Tester may identify additional candidates during test work; none are
  expected.

**Verification to run (Step 4):**
- Full suite: 531 passed / 0 failed / 0 skipped, count unchanged.
- Structural identity and MRO checks listed in Step 4.
- Confirm no test edits were needed; report the `grep` result for the moved
  names.

## Guidance for Planner

Documentation tasks you will execute yourself (not the coder):

- **Files to modify:**
  - `./CLAUDE.md` — the `Structure` block's `server.py` bullet (note the
    mixin base; it still holds the handler, admin, CLI, and mode-dispatch
    clusters) and a new `chat_sse.py` bullet after `forwarder.py` describing
    the `ChatSSEHandlerMixin` and the byte-identical move; also correct the
    `forwarder.py` bullet to note it now defines `_DISCONNECT_ERRORS`.
  - `doc/architecture.html` — the request-path paragraph (lines 50–54) names
    `ProxyHandler.do_POST` and `forward_request` in `server.py`; add that the
    chat-mode SSE conversion lives in `chat_sse.py` (`ChatSSEHandlerMixin`).
  - `./CLAUDE.md` doc-accuracy correction found by the coder round: the
    "23-name frozen surface" numeral (lines 30 and 438) now undercounts — the
    `from .forwarder import` block binds 24 names with `_DISCONNECT_ERRORS`.
    No test pins the figure. Per the global CLAUDE.md rule that documentation
    must not maintain exact counts, **drop the numeral** ("the frozen surface
    re-exported by `server.py`") instead of incrementing it.
  - `./CLAUDE.md` "Future Work — TODO": the remaining-clusters sentence (line
    444) must drop "chat-SSE drain", leaving "the admin/handler extraction and
    the forwarder owned-state conversion"; and the staged-decomposition
    narrative gains a step-7 entry for this plan ("the chat-SSE extraction
    moved the chat-mode SSE conversion into `chat_sse.py` as a
    `ChatSSEHandlerMixin` behind a byte-identical verbatim move"), with the
    "Five more followed" count phrase adjusted so the series stays consistent.
  - `doc/architecture.html` "Client disconnects" (line 666): the sentence
    "is not caught by the handler's `_DISCONNECT_ERRORS` set" must name the
    constant's new home (`forwarder.py`), since step 1 left only an import
    binding in `server.py`.
  - `doc/architecture.html` date stamps: bump **both** "Last updated" stamps
    (masthead line 13 and footer line 904) to 2026-11-17 — the page masthead
    date is part of the page contract.
  - `doc/test-catalog.html` lines 103–107: the isolation prose names the
    modules that import `settings.py` at import; add `chat_sse.py` as the
    fourth (flagged by the tester round), and bump the footer date stamp.
  - `doc/provider-modes.html` line 597: `MAX_CHAT_OPEN_TOOL_BLOCKS` is described
    as a *concurrency* cap ("tool blocks left open simultaneously"), but
    `tools_started` is never decremented on `content_block_stop` — it is a
    per-stream total cap. Correct the sentence (pre-existing drift found by the
    audit; the constant moved in this plan, so the page is in scope).
- **`.claude/mega-audit-files.json`:** no change (no new declared audit
  location).
- **When:** after coder Step 3, before Step 5's measurement.
- **What to sync:** the module-layout claims only — behavior prose in
  `doc/provider-modes.html` is unchanged by this plan. Measure every quoted
  line count after the move; never estimate.

## Verification Scripts

- `./tmp/verification/2026-11-17-extract-chat-sse-step1.py` — step 1 gate:
  `_DISCONNECT_ERRORS` present in `forwarder.py` verbatim, absent from
  `server.py`'s own definitions, imported into `server.py`, and the runtime
  tuple.
- `./tmp/verification/2026-11-17-extract-chat-sse-step2.py` — step 2 gate:
  new module present, both methods byte-identical to the `63554b7` source,
  the six constants moved, the import whitelist exact, no parent import,
  the MRO/base-list/identity assertions, and the free-variable closure.
- Both are **RED against the pre-change tree** (recorded in History) and GREEN
  after their step.
- Coder-authored move helpers (plan-transient; retired with the plan's
  `retire_inventory`): `./tmp/verification/2026-11-17-extract-chat-sse-move.py`
  (composes `chat_sse.py` from AST segments) and
  `./tmp/verification/2026-11-17-extract-chat-sse-cut.py` (verifies byte
  identity before deleting; writes atomically via temp file + `os.replace`).
- **Isolation requirement.** Every script here that imports `claude_retry_proxy`
  or spawns a process carries the canonical block from
  `doc/test-catalog.html#pattern-spawn-isolation` (the `_ISOLATION_DIR =
  tempfile.mkdtemp(...)` derivation plus the three `PROXY_*` assignments)
  **before** its first proxy import and first spawn. `step1.py` is import-only
  and `step2.py` spawns `git`, so both carry it; `python
  scripts/check_spawn_isolation.py` must exit 0. The same rule applies to any
  import-bearing one-liner: use the isolated gate script rather than a bare
  `python -c "import claude_retry_proxy…"`.

**Calibration record (2026-11-17, pre-change tree `63554b7`):**
- step1 gate → exit 1, 6 FAIL (only the runtime-tuple assertion passes, as it
  must — that count already holds).
- step2 gate → exit 1, `chat_sse.py` absent.
- Satisfiability probe of the closure predicate against the real moved bodies
  found the guide §7.3 formula reports 18 nested helper defs (`write`,
  `terminal`, `handle_frame`, …) as unresolved; the gate now adds nested
  `def`/`class` names to the local scope, and the probe is clean (`{}`).
- Teeth probe: a one-character mutation of the moved segment is rejected by
  the byte-identity predicate; an extra import is rejected by the whitelist
  predicate.

## History

| Date | Event | Conclusion | Dismissed |
|------|-------|------------|-----------|
| 2026-11-17 | Initial plan | Extract the chat-SSE cluster (897 lines) from `server.py` into `chat_sse.py` as a `ChatSSEHandlerMixin`, relocating `_DISCONNECT_ERRORS` to `forwarder.py`; decision confirmed with the user (mixin shape; forwarder leaf). Both step gates calibrated RED; the closure-gate satisfiability probe fixed the nested-def scope gap before hand-off. | — |
| 2026-11-17 | Mega-audit (post-implementation, user-directed) | Verdict "Issues found — plan needs revision": 32 findings (4 High / 9 Medium / 19 Low). All four Highs were **one root cause** — the plan's own gate scripts imported/spawned the proxy without the canonical isolation block, so `check_spawn_isolation.py` failed and the suite was 529/2; fixed in both scripts (checker `0 fail`), `cut.py` now writes atomically and trims one blank line, the doc sync was executed, a new Step 3 removes the unused `_map_chat_finish_reason` import, Step 5 owns closure, and four pre-existing code defects were filed as deferrals. Suite re-run after the fixes: **531 passed / 0 failed**. Report: [mega-audit](./tmp/reports/2026-11-17-extract-chat-sse-mega-audit-2026-11-17.json). | [audit-l20-prior-plan-ordering](./tmp/reports/2026-11-17-extract-chat-sse-mega-audit-2026-11-17.json), [audit-l25-mixin-contract-transient](./tmp/reports/2026-11-17-extract-chat-sse-mega-audit-2026-11-17.json) |
| 2026-11-17 | Review (Phase 6, Sonnet) | Verdict "Issues found — non-blocking": 0 Critical / 0 Warning / 3 Suggestion. Inherited obligations measured: the `iter_raw`-outside-`try` hunch is **refuted** (httpx2's `iter_raw` is a generator; its body runs on first `next()`, inside the try), `_DISCONNECT_ERRORS` is never rebound, no import cycle, byte identity independently reproduced (both methods byte-equal, sha256 `fb2069d3…` / `e890e76a…`), and the suite result is corroborated from the tester's log (714.2 s exceeds the 600 s foreground cap). One Suggestion fixed in-lane (`architecture.html`'s stale 300 s socket claim → `PROXY_READ_TIMEOUT`), one filed as a deferral (`chat-sse-test-comment-stale-cap-location`), two recorded below. Report: [review](./tmp/reports/2026-11-17-extract-chat-sse-review-2026-11-17.json). | [review-mixin-mro-collision-risk](./tmp/reports/2026-11-17-extract-chat-sse-review-2026-11-17.json), [review-readme-python-version-stale](./tmp/reports/2026-11-17-extract-chat-sse-review-2026-11-17.json) |
| 2026-11-17 | Implementation round (tester) — round 3 | **SUCCESS**: full suite 531 passed / 0 failed (714.2 s), step-2 structural gate 38/38, step-1 gate 7/7, spawn-isolation corpus PASS (standalone and via the suite hook), both consumer censuses clean, no test edits, measured counts match the plan exactly (1,663 / 936 / 1,917). One doc gap flagged — `doc/test-catalog.html`'s `settings.py` importer list omitted `chat_sse.py` — fixed in the planner lane. | — |
| 2026-11-17 | Implementation round (coder) — round 2 | Step 3 only: `_map_chat_finish_reason` removed from `server.py` (0 occurrences), mixin docstring's `wfile` claim corrected; build pass, zero issues; step-2 gate 38/38 and `check_spawn_isolation.py` PASS. Post-Step-3 measurements: `server.py` 1,663, `chat_sse.py` 936, `forwarder.py` 1,917. | — |
| 2026-11-17 | Implementation round (coder) — round 1 | Both gates GREEN verbatim (step1 7/7, step2 38/38); build pass; zero issues filed; no test edits. Measured: `server.py` 2,576 → 1,664, `chat_sse.py` 934, `forwarder.py` 1,908 → 1,917 — the plan's estimates were 12/16 lines low on header/import bulk; the 897 moved-line figure held exactly. Coder flagged the stale "23-name frozen surface" doc numeral, queued as a planner doc task. | — |

## Final Results

- **Status: COMPLETED** (2026-11-17).
- **What landed:** the chat-SSE conversion cluster extracted from
  `server.py` into `src/claude_retry_proxy/chat_sse.py` as a
  `ChatSSEHandlerMixin` that `ProxyHandler` inherits ahead of
  `BaseHTTPRequestHandler` — a byte-identical verbatim move of
  `_stream_chat_sse_to_anthropic` and `_log_response_cap_exceeded` plus the
  six chat/drain constants; `_DISCONNECT_ERRORS` relocated to `forwarder.py`
  as a shared leaf; the now-unused `_map_chat_finish_reason` import removed
  from `server.py`; the mixin docstring corrected (`wfile` is an instance
  attribute, not an MRO lookup).
- **Files changed:** `src/claude_retry_proxy/{chat_sse.py (A), server.py (M),
  forwarder.py (M)}`; `CLAUDE.md`, `doc/{architecture,provider-modes,test-catalog}.html`.
- **Test results:** **531 passed / 0 failed / 0 skipped** (tester round 3;
  suite log `tmp/logs/2026-11-17-extract-chat-sse-tester-suite.log`, 714.2 s).
  Structural gates: step-1 7/7, step-2 38/38 (byte-identity sha256, exact
  import whitelist, no parent import, base list, MRO identity, empty closure).
  `scripts/check_spawn_isolation.py` PASS (2 spawners, 0 fail) standalone and
  through the suite's live-corpus hook. No test file edited.
- **Measurements (post-Step-3, `wc -l`):** `server.py` 2,576 → **1,663**;
  `chat_sse.py` **936**; `forwarder.py` 1,908 → **1,917**.
- **Audit:** post-implementation mega-audit (user-directed) — 32 findings
  (4 High / 9 Medium / 19 Low); all High + Medium fixed, the four Highs being
  one root cause (the plan's own gate scripts lacked the spawn-isolation
  block). Report:
  [mega-audit](./tmp/reports/2026-11-17-extract-chat-sse-mega-audit-2026-11-17.json).
- **Review:** 0 Critical / 0 Warning / 3 Suggestion — ready to commit. One
  suggestion fixed in-lane, one deferred, two recorded in the History
  `Dismissed` cell. Report:
  [review](./tmp/reports/2026-11-17-extract-chat-sse-review-2026-11-17.json).
- **Issues:** 0 open, 0 in-row deferred. Standalone deferrals filed from this
  plan (all on disk, presence = open):
  `chat-tool-degradation-counter-disposition`,
  `chat-sse-coalesced-late-frames`, `chat-sse-choices-shape-guard`,
  `response-cap-stderr-print-raises` (pre-existing, frozen by the verbatim
  move), and `chat-sse-test-comment-stale-cap-location` (caused by the move).
- **Known caveats:** `ChatSSEHandlerMixin` is first in the MRO with no
  committed namespace-collision guard; a future `handle`/`setup`/`finish`-
  style member in the mixin would silently shadow `BaseHTTPRequestHandler`.
  `server.py` remains over the 1,000-line threshold; the named follow-ups are
  the admin/handler extraction and the `forwarder.py` owned-state conversion.
  `README.md:44` still advertises Python 3.8 while the package requires 3.10+
  (pre-existing, out of scope).
- **Residue outside the retire contract** (not under `tmp/reports/` or
  `tmp/verification/`, so `retire_inventory` cannot sweep them): the tester's
  suite wrapper `tmp/2026-11-17-extract-chat-sse-suite-run.py`, and the
  planner's scratch extracts `tmp/hunches.txt` and `tmp/areas.txt`. The
  post-commit retire hand-off must name them explicitly.

## Cross-References to Prior Plans

| Prior Plan | Deferred Issue | Resolution |
|------------|---------------|------------|
| 2026-11-16-extract-forwarder | the remaining clusters (admin/handler, chat-SSE drain) are tracked by the /refactor-split survey | This plan extracted the chat-SSE drain cluster into `chat_sse.py` as `ChatSSEHandlerMixin`; only the admin/handler extraction remains |

## Plan Metadata

```json
{
  "plan_id": "2026-11-17-extract-chat-sse",
  "steps": [
    "Step 1: move _DISCONNECT_ERRORS to forwarder.py",
    "Step 2: chat-SSE cluster to chat_sse.py as ChatSSEHandlerMixin",
    "Step 3: remove the unused _map_chat_finish_reason import",
    "Step 4: full-suite and structural verification",
    "Step 5: planner doc sync, closure, and final measurement"
  ],
  "coder_files": [
    "src/claude_retry_proxy/forwarder.py",
    "src/claude_retry_proxy/server.py",
    "src/claude_retry_proxy/chat_sse.py"
  ],
  "tester_files": [],
  "doc_files": ["./CLAUDE.md", "doc/architecture.html", "doc/provider-modes.html", "doc/test-catalog.html"],
  "verification_scripts": [
    "./tmp/verification/2026-11-17-extract-chat-sse-step1.py",
    "./tmp/verification/2026-11-17-extract-chat-sse-step2.py",
    "./tmp/verification/2026-11-17-extract-chat-sse-move.py",
    "./tmp/verification/2026-11-17-extract-chat-sse-cut.py"
  ],
  "retire_inventory": [
    "./tmp/verification/2026-11-17-extract-chat-sse-step1.py",
    "./tmp/verification/2026-11-17-extract-chat-sse-step2.py",
    "./tmp/verification/2026-11-17-extract-chat-sse-move.py",
    "./tmp/verification/2026-11-17-extract-chat-sse-cut.py",
    "./tmp/reports/2026-11-17-extract-chat-sse-coder-2026-11-17.json",
    "./tmp/reports/2026-11-17-extract-chat-sse-coder-2026-11-17-2.json",
    "./tmp/reports/2026-11-17-extract-chat-sse-tester-2026-11-17.json",
    "./tmp/reports/2026-11-17-extract-chat-sse-mega-audit-2026-11-17.json",
    "./tmp/reports/2026-11-17-extract-chat-sse-review-2026-11-17.json"
  ],
  "repo_mode": "Public",
  "document_overrides": [
    "refactor-split guide §4: mixin class instead of a state-owning class (Reason: method grouping inherited by the framework handler; byte-lock of the verbatim move)",
    "refactor-split guide §2 deletion test: _DISCONNECT_ERRORS relocates with the plan (Reason: moved body reads it by bare name; sibling may not import the parent; forwarder.py is the shared leaf home and imports no sibling back)",
    "refactor-split guide §7.3: the AST undefined-name gate adds nested def/class names to the local scope (Reason: the formula as written reports every nested helper as unresolved, making a byte-identical move unpassable)"
  ]
}
```

## Audit Accumulation

*Counters reset when mega-audit runs. Used by Phase 5 entry trigger.*

| Counter | Value | Last Updated |
|---------|-------|--------------|
| issues_resolved_since_audit | 0 | 2026-11-17 |
| steps_changed_since_audit | 4 | 2026-11-17 |
| files_changed_since_audit | 1 | 2026-11-17 |
