# Plan: Strip ECMA identity escapes from tool-schema `pattern` regexes so strict backends accept them

**Project:** D:\proj\claude-retry-proxy
**Plan ID:** 2026-10-06-re2-portable-tool-schema-patterns
**Created:** 2026-10-06

## Immediate Actions

**Phase 6 review is done (0 Critical / 2 Warning / 3 Suggestion, non-blocking). One bounded remediation round fixes finding 1 and two docstrings; then doc sync and commit.**

Verified state on the current tree — full declared suite **401 passed / 0 failed / 401 total**; mutation script **MUTATION DISCIPLINE PASSED** (8 tests × 5 mutations, including mutation E which reverts `server.py`'s else branch and fails exactly the new anthropic-mode e2e test; planner re-ran it independently); and a **live end-to-end probe**: a `model: "opus"` request (opus → deepseek, anthropic mode) carrying `pattern: "^agent\_run\_"` returned **200** from deepseek-flash — the exact request that previously 400'd.

**Review report:** [review-2026-10-06.json](./tmp/reports/2026-10-06-re2-portable-tool-schema-patterns-review-2026-10-06.json) — 0 Critical / 2 Warning / 3 Suggestion, non-blocking. Verified: the keep/drop rule passes the plan's table and ~25 adversarial inputs, the metachar set is exactly the 13 ECMA SyntaxCharacters, `-` is in-class-kept/out-of-class-dropped, all three helpers are total and non-mutating, and **mutation E genuinely pins the `server.py:980` wiring** (reverting it fails only the new e2e test).

**Round 5 (coder) landed** the finding-1 tracker fix and the docstrings (report: [coder-2026-10-06-3.json](./tmp/reports/2026-10-06-re2-portable-tool-schema-patterns-coder-2026-10-06-3.json)); the planner spot-checked the tracker across 11 class shapes — all correct.

**Correction to finding 1's rationale (planner, 2026-10-06).** The reviewer's premise — "ECMA treats `]` immediately after `[` as a literal" — is **false for ECMA-262**: verified in Node, `[]\-a]` and `[]-a]` match identically (ECMA forbids `]` as a class member, so `[]` is an empty class); the divergence the reviewer measured is **PCRE-only** (Python `re`). The fix is nevertheless **kept**, on a better ground: it is the *conservative* choice — it declines to strip when the character-class parse is ambiguous across dialects, so it can never change meaning under any engine, at the cost of not sanitizing a pattern shape no real schema emits. The backend rejects `\_` (valid in ECMA), so it is not ECMA either; RE2/Rust-family engines do treat `]`-first as literal, which is why the conservative side is the right one.

**Coder — implement Step 4 (user-directed 2026-10-06, "fix all valid"): findings 2, 3 and 5.** Do not change the tracker or the three existing call sites.

**Step 4 landed** (coder report: [coder-2026-10-06-4.json](./tmp/reports/2026-10-06-re2-portable-tool-schema-patterns-coder-2026-10-06-4.json)). The tester added `sanitize-schema-patterns-value-positions` and `sanitize-schema-patterns-collision-merge` (chat 49→51), extended the mutation script to **8 mutations × 10 tests**, and ran it — **MUTATION DISCIPLINE PASSED** (mutations F/G newly cover finding 2's two directions, H covers finding 3, E covers the server wiring). It then **exited without running the full suite or writing a report** — the recurring `operate-round-ends-turn-before-waiting` failure. Planner-verified independently: the two new tests pass; the extended mutation script passes; a 12-case functional check of every Step 4 behaviour passes; the three touched modules are 51/38/29 with no regressions.

**Tester — write the closing report only.** Everything is on disk and verified; do **not** re-author tests. Run the full declared suite **foreground** (`python tests/test_claude_proxy.py`), re-run `tmp/verification/2026-10-06-re2-portable-tool-schema-patterns-mutation.py`, and write `tmp/reports/2026-10-06-re2-portable-tool-schema-patterns-tester-2026-10-06-3.json` with `overall_result: "SUCCESS"` and those two results. Do not yield the turn until the report file exists.

**Planner — after the report:** the doc sync (`doc/provider-modes.html` anthropic-mode note, `CLAUDE.md`, `doc/test-catalog.html`) and `/update-and-commit`.

<!-- HISTORICAL — superseded: this block directed the Step 3 coder + tester rounds, now landed. -->
**Corrected diagnosis (2026-10-06): the failing provider is in anthropic mode, so the Step 1–2 sanitizer never ran for it. That path is Step 3 now.**

The live trace shows every 400 is `tier: opus, provider: deepseek`, and the admin API reports `deepseek`'s mode as **`anthropic`**. In anthropic mode (`server.py:980`) the proxy forwards the parsed body **verbatim** — it never calls the chat/response transforms, so the sanitizer placed inside `_transform_anthropic_tools_to_chat` / `_anthropic_to_response` is bypassed. The earlier attribution to `transforms_chat.py:335` (chat mode) was wrong for this request; the chat/response work still stands and is correct for those modes, but the failing request never reaches it. Restart and reinstall were never the issue — the editable install (resolves to `src/`) and the 18:16 restart are both confirmed good.

**What is already landed and verified (do not re-derive):** Steps 1–2 source (+88 in `transforms_common.py`, both call sites), five new tests (four chat, one response), and the mutation script. Targeted runs **47/47** and **38/38**; mutation script **MUTATION DISCIPLINE PASSED**; full declared suite **398 passed / 0 failed** on the Step 1–2 tree. The tester round that produced the tests then backgrounded the suite and exited without a report — but its tests are on disk and load-bearing.

**Coder — implement Step 3**, the only remaining source change: sanitize tool `input_schema` patterns on the **anthropic-mode** verbatim forward (helper `_sanitize_body_tools` in `transforms_common.py` + one call in the `else` branch at `server.py:980`). Do not touch `tests/**`.

**Tester — after the coder:** add the Step 3 tests (unit on `_sanitize_body_tools`, one anthropic-mode end-to-end through the mock-upstream harness), mutation-check the new branch, run the full suite **foreground** (`python tests/test_claude_proxy.py` — do not background it), re-run the existing mutation script, and write the session report with `overall_result: "SUCCESS"`. Do not yield the turn until the report exists.

**Planner — after the tester report:** finish Phase 6 — the code review, the doc sync (`doc/provider-modes.html` now also noting the anthropic-mode normalization, `CLAUDE.md`, `doc/test-catalog.html`) and `/update-and-commit`.

## Summary

**Problem.** A tool call through the chat-mode path 400s with
`Invalid schema for function 'mcp__exa__agent_run': "^agent\_run\_" is not a "regex"`
when routed to the deepseek-flash provider. The Exa MCP server builds its
`input_schema` with Zod v4, whose JSON-Schema converter turns `string().startsWith("agent_run_")`
into `{"pattern": "^agent\\_run\\_"}` — a regex carrying an ECMA **identity escape**
(a backslash before a punctuation character that is not a metacharacter). Identity
escapes are valid in ECMA-262 and, per Go's own `regexp/syntax` source (`parseEscape`'s
`default` branch accepts `\` before any non-alphanumeric ASCII character), in Go's RE2 —
but the DeepSeek backend's schema validator is stricter and rejects them, so the invalid
`pattern` reaches it and the request 400s before any completion is produced.

The proxy forwards `input_schema` **verbatim** into the outgoing tool schema at two sites —
chat mode (`transforms_chat.py:335`, into `function.parameters`) and response mode
(`transforms_response.py:258`, into `parameters`). Both backends receive the untouched
bytes, so the fix is in the proxy, not the MCP server.

**Approach.** Add one shared, pure, total, non-mutating sanitizer to
`transforms_common.py` and call it from both tool transforms. It walks a tool
`input_schema` and rewrites every JSON-Schema regex — both `"pattern"` values and
`"patternProperties"` object keys — by stripping backslashes that are ECMA identity
escapes, leaving meaningful escapes alone. A pattern carrying only identity escapes is
accepted by every engine; the rewrite is semantics-preserving because, by the very
definition of an identity escape, `\c` *is* `c`.

**Key design decisions:**

- **Placement: `transforms_common.py`, not `transforms_chat.py`.** The identical
  `input_schema → parameters` forward exists in both the chat and response transforms
  (`transforms_chat.py:335`, `transforms_response.py:258`); both already import from
  `transforms_common`. One function, two call sites, no duplication.
- **The strip rule is grounded in the ECMA definition of IdentityEscape, not in any one
  backend.** `pattern` is an ECMA-262 regex per the JSON Schema spec, so a `\c` that is
  not a recognized escape is definitionally the character `c`. Stripping it is valid and
  meaning-preserving for any engine, strict or lax. This sidesteps the fact that the
  failing backend is *stricter than Go RE2* (Go accepts `\_`; this backend does not) —
  we do not need to know which engine it is.
- **Hard invariant: never strip a backslash before an ASCII letter or digit.** Every
  meaningful escape in every major engine is introduced by a letter or digit
  (`\d \w \s \n \t \x \u \p{L} \b \Q…\E`, octal). Dropping such a backslash would change
  meaning (`\d` → `d`), so the sanitizer refuses to touch them even when, as with `\u0041`,
  the escape is itself non-portable. The stripper only ever targets the unambiguous
  identity-escape class.
- **Metacharacter escapes are kept.** `\^ \$ \\ \. \* \+ \? \( \) \[ \] \{ \} \|` mean
  "literal metacharacter" in every engine; stripping them would change meaning on all of
  them.
- **`-` is context-sensitive.** Inside a character class `\-` is a meaningful escape
  (literal hyphen, where a bare `-` may be a range operator); outside one `\-` is an
  identity escape. The stripper tracks class state for `-` alone and keeps `\-` inside a
  class, drops it outside.
- **No new trace event.** The rewrite is a correctness-preserving normalization, not a
  data-loss or feature-loss transformation; unlike `content_block_dropped` or
  `cache_control_stripped` there is nothing an operator should act on, and a per-request
  event would fire on every tool-bearing DeepSeek request. The behavior is observable in
  that the 400s stop occurring. (Presented as a considered-and-rejected alternative
  below, so it is deliberate rather than an omission.)

**Alternatives considered and rejected:**

- *Mitigate at the MCP layer* (drop `agent_run` from `TOOLS`) — fixes one tool for one
  server; does nothing for any other MCP server or schema that emits an identity escape.
- *Sanitize only for the DeepSeek provider* — the escape is definitionally redundant, so
  universal stripping is safe for every engine; keying it off provider adds config and
  test surface for no benefit.
- *Context-free stripping that also drops `\-` everywhere* — smaller, but would silently
  change `[a\-z]` (literal hyphen) into `[a-z]` (a range). Rejected: the class tracker is
  ~ten lines and is the difference between a correct rewrite and a wrong one.
- *A per-request `schema_pattern_sanitized` trace event* — rejected for the reason above;
  trivially re-addable if the operator later wants lead-observability.
- *Translate non-portable regex features too* (lookarounds, backreferences, `\uXXXX`) —
  out of scope: those are inexpressible in RE2-style engines and cannot be fixed by
  stripping; a translator is a separate project.

**Explicitly out of scope:**

- Translating lookarounds, backreferences, `\u`, `\cX`, or any letter-introduced escape
  that a strict engine does not support. Such patterns still fail exactly as they do
  today; the sanitizer makes no claim to fix them.
- ~~Anthropic mode~~ — **in scope (Step 3, added after the live trace proved the
  `deepseek` provider is `mode: "anthropic"` and rejects the unsanitized `\_`).**
  The earlier assumption that anthropic-mode validators accept identity escapes was
  false for this backend, so the verbatim forward now sanitizes tool schemas too.
- Touching `_transform_and_guard` or any guard; the request-direction transforms already
  run inside an `except Exception` fence at `server.py:981`, so a failure could not abort
  a request — the sanitizer is internal-total regardless.
- `format`, `propertyNames`, `dependencies`, or any other schema keyword. Generic
  recursion already descends into subschema-bearing keywords; only the two
  regex-typed locations (`pattern` values, `patternProperties` keys) need direct
  handling.

## Repo Mode

Public

*Detected at plan creation. Determines: plan archival path, commit-message content, staged files.*

## Document Overrides

| Document | Rule Overridden | Reason |
|----------|----------------|--------|

## Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| The class tracker misparsed a `]`-first literal member (ECMA treats `]` immediately after `[` or `[^` as a literal) | Confirmed by review: `[]\-a]` → `[]-a]` changes what the pattern matches (`-` becomes a range operator) — a meaning change, not merely a portability gap | **Fixed in the remediation round** — a leading `]`/`^]` is now treated as a class member. The plan's original example (`[]\-]`) was in fact safe; the dangerous shape needs a member after the stripped `\-` |
| The walk rewrote a `pattern`-keyed string inside value keywords (`const`/`enum`/`default`/`examples`) | Silent corruption of asserted/example data carrying a `pattern` key | **Fixed in Step 4 (review finding 2, user-directed).** The walk is now position-aware: value keywords are copied verbatim, while `properties`/`$defs`/`definitions`/`dependentSchemas` are treated as name→schema maps — so a property legitimately named `default` is still sanitized |
| Two `patternProperties` keys differing only by identity escapes collided after stripping (last won) | One schema entry silently dropped | **Fixed in Step 4 (review finding 3, user-directed).** On collision the two subschemas merge as `{"allOf": [...]}` — semantically correct (both equivalent patterns apply) and lossless |
| The pre-dispatch `try` block's fallback (`server.py:991`) forwards the raw client bytes un-sanitized with no trace event | A sanitize failure was invisible for anthropic mode | **Fixed in Step 4 (review finding 5, user-directed).** The anthropic-mode transform failure now logs `transform_failure`. The fallback itself (raw bytes for a body that could not be transformed) is unchanged and unavoidable |
| Stripping `\/` or `\-` (outside class) changes a valid ECMA pattern's meaning for a lax engine (Qwen) | None — semantic identity, not merely acceptance | Identity escapes are definitionally the bare character; Qwen's parse of `^agent_run_` and `^agent\_run\_` is identical input to matching. The rewrite is not "made RE2-valid", it is "made redundant-escape-free" |
| A letter-introduced escape that a strict engine rejects (`\u0041`) survives untouched | The request still 400s exactly as it does today | Not a regression; fixing it requires translation, which is out of scope and named as such. The invariant (never strip before a letter/digit) is the safe side: stripping would be a *meaning change*, not a portability fix |
| The sanitizer raises on a hostile/oversized schema | Request abort | It is total (non-dict/list returns as-is, non-string `pattern`/keys untouched), the input schemas are shallow by construction, and the existing `except Exception` fence at `server.py:981` is a second line of defense. No new crash class is introduced |
| Deep-copying every schema perturbs identity assumptions elsewhere | A future test asserting `out["function"]["parameters"] is input_schema` | No current test asserts that identity (verified — `test_anthropic_to_chat_no_input_mutation` checks only that the *input* is unmutated, and dict equality, not identity, is asserted on output). The sanitizer always returns a new structure, matching the transforms' existing "does not mutate" contract |
| The rewrite masks the real problem upstream (the MCP server emitting bad schema) | Operators stop noticing the underlying defect | The underlying schema is not wrong — it is valid ECMA, and DeepSeek is within its rights rejecting the non-portable form only because the form is redundant, not because the schema is malformed. There is nothing upstream to fix |

## Rollback

The change is confined to `src/claude_retry_proxy/transforms_common.py` (two new
functions) and two one-line call sites in `transforms_chat.py` and
`transforms_response.py`, plus tests. There is **no data migration, no persisted-state
change, no configuration change, and no trace-format change**: `feature-compatibility.json`,
`config.json`, `models.json`, the keys file and the trace schema are untouched. Reverting
is a pure code revert — deleting the two call-site edits and the two functions, and
removing the added tests. The only externally visible behavior is that tool-bearing
requests whose `pattern` carried identity escapes reach strict backends instead of
400-ing; reverting restores the current 400. No flag or staged rollout is needed because
the sanitized schema is accepted by every backend that accepted the unsanitized one.

## Proposed Changes

`(auto)` = mechanical, coder self-verifies. `(scripted)` = deterministic multi-step, coder runs provided script. This plan has no standalone verification scripts; the escape table and both modes' integration are pinned by the tester's unit tests, which are the load-bearing evidence for a change this small.

1. **Step 1: Add `_strip_regex_identity_escapes` and `_sanitize_schema_patterns` to `transforms_common.py`; export both via `__all__`.**

   `_strip_regex_identity_escapes(pattern)` — a pure string→string rewriter implementing this rule, character-by-character over the pattern:

   - If the current char is not `\`, copy it. Track `in_class` (initial `False`) solely to decide `-`; on an unescaped `[` when `in_class` is `False`, set `in_class = True` (an unescaped `[` while already in-class is a literal member and leaves state unchanged); on an unescaped `]` when `in_class` is `True`, set `in_class = False`.
   - If the current char is `\` and is the **last** character, copy it and stop (a trailing escape is already malformed; do not invent behavior).
   - If the current char is `\` followed by `c`, then **keep the backslash** iff `c` is ASCII `[0-9A-Za-z]`, or `c` is one of `^ $ \ . * + ? ( ) [ ] { } |`, or `c` is `-` while `in_class` is `True`. Otherwise **drop the backslash** (emit `c` alone). Always consume both characters together.

   This encodes the invariant and the two keep-classes, and drops `\` before every remaining symbol (`_ / : ! # % & ' " , ; < > = @ ~` backtick, and whitespace), which by ECMA are identity escapes and by every strict engine are invalid escapes.

   Reference table (input → output) that the docstring should reproduce compactly:

   | Input (raw) | Output | Why |
   |---|---|---|
   | `^agent\_run\_` | `^agent_run_` | the reported bug |
   | `foo\-bar` | `foo-bar` | `-` outside class is identity |
   | `[a\-z]` | `[a\-z]` (unchanged) | `-` inside class is a literal-hyphen escape |
   | `[a\-z]\-x` | `[a\-z]-x` | mixed: in-class kept, out-of-class dropped |
   | `\d{1,3}\.\d+` | unchanged | `\d` (letter), `\.` (metachar) are meaningful |
   | `\.\^\[\]\{\}\\\*\+\?\$\|` | unchanged | all metacharacter escapes |
   | `\s\w\n\t\x41\u0041\p{L}\Qx\E\0` | unchanged | every escape is letter/digit-introduced |
   | `a\/b\:c\@d\!\#e` | `a/b:c@d!#e` | `/` and punctuation are identity |
   | `\ ` | ` ` (space) | whitespace is identity |
   | `ab\` | `ab\` (unchanged) | trailing escape |
   | `` (empty) | unchanged | empty passthrough |

   `_sanitize_schema_patterns(node)` — a recursive, non-mutating, total walk returning a new structure:
   - dict → for each `k, v`: when `k == "pattern"` and `v` is a `str`, set `v` to `_strip_regex_identity_escapes(v)`; when `k == "patternProperties"` and `v` is a dict, rebuild it with each *string* key passed through `_strip_regex_identity_escapes` (non-string keys left as-is) and each value recursed; otherwise recurse into `v`. Non-dict path: if it does not match either special key, assign `_sanitize_schema_patterns(v)`.
   - list → `[_sanitize_schema_patterns(x) for x in node]`.
   - anything else → return unchanged.

   The docstring must state: (1) it never mutates the input; (2) it is total — a non-string `pattern` value, a non-string `patternProperties` key, and non-dict/list nodes all pass through unchanged; (3) generic recursion descends into every subschema-bearing keyword, so `properties`, `items`, `anyOf`, `oneOf`, `allOf`, `not`, `propertyNames`, `$defs`, `dependentSchemas`, etc. are covered without special cases.

   → coder verify (auto): both functions defined at module level in `transforms_common.py`; both names present in `__all__`; `_strip_regex_identity_escapes` contains no `[0-9A-Za-z]` strip branch (letters/digits are never dropped); `_sanitize_schema_patterns` contains the `== "pattern"` and `== "patternProperties"` branches and never mutates `node` in place.
   → tester verify: the full input→output table above as direct-call unit tests, plus the walk tests in Guidance for Tester.

2. **Step 2: Apply the sanitizer at both tool-transforms' `input_schema → parameters` forwards.**

   - `transforms_chat.py:335` — change `fn = {"name": name, "parameters": input_schema}` to `fn = {"name": name, "parameters": _sanitize_schema_patterns(input_schema)}`; extend the existing `from .transforms_common import _request_transform_timestamp` at `:9` with `_sanitize_schema_patterns`.
   - `transforms_response.py:258` — change `fn = {"type": "function", "name": name, "parameters": input_schema}` to `fn = {"type": "function", "name": name, "parameters": _sanitize_schema_patterns(input_schema)}`; extend the existing import at `:8` the same way.

   Both transforms already declare "does not mutate `body_json`"; the sanitizer's copy preserves that, and `cache_control` lives on the tool dict (outside `input_schema`), so the `cache_control_stripped`/`cache_stripped_out` bookkeeping is untouched.

   → coder verify (auto): `grep -rn "parameters.*input_schema" src/` shows exactly the two call sites and both pass `_sanitize_schema_patterns(input_schema)`; `grep -rn "input_schema" src/claude_retry_proxy/transforms_*.py` shows no remaining `"parameters": input_schema` or `"parameters": tool["input_schema"]`-style verbatim forward; both imports carry the new name. No other source file changes.
   → tester verify: chat- and response-mode integration tests below.

   3. **Step 3: Sanitize tool `input_schema` patterns on the anthropic-mode verbatim forward.**

   **(a)** Add `_sanitize_body_tools(body_json)` to `transforms_common.py` and export it via `__all__`. It returns a shallow copy of `body_json` in which every `tools[i]["input_schema"]` that is a dict is replaced by `_sanitize_schema_patterns(...)`; a non-dict `body_json`, a missing/non-list `tools`, and non-dict tool entries pass through unchanged; no input is mutated.
   **(b)** In `server.py`, import `_sanitize_body_tools` (beside the existing `_transform_and_guard` import from `transforms_common`) and change the anthropic-mode branch — the `else` of the chat/response `elif` chain at `server.py:980` — from `rewritten_body = json.dumps(body_json).encode("utf-8")` to `rewritten_body = json.dumps(_sanitize_body_tools(body_json)).encode("utf-8")`. The chat and response branches are unchanged; the raw client `body` bytes are never touched.

   → coder verify (auto): `_sanitize_body_tools` is in `transforms_common.__all__`; the `else` branch is the only line that gained the call; `_sanitize_body_tools` constructs fresh dicts/lists and never mutates its argument; grep shows no other mode-unconditional `json.dumps(body_json)` forward remains.
   → tester verify: unit tests on `_sanitize_body_tools` (sanitized copy, non-mutation, passthrough for non-dict tools / absent `tools`); one anthropic-mode end-to-end through the existing mock-upstream harness asserting the upstream body carries `tools[0].input_schema…pattern == "^agent_run_"`; mutation check that reverting the `else` branch to `json.dumps(body_json)` fails that test.

4. **Step 4: Remediate review findings 2, 3 and 5 (position-aware walk, collision-safe keys, de-silenced fallback).**

   **(a) Finding 2 — make `_sanitize_schema_patterns` position-aware.** Today the walk rewrites any `pattern`-keyed string in any nested dict, including inside *value* keywords (`const`/`enum`/`default`/`examples`) where it is asserted DATA, not a schema. Distinguish three node roles:
   - **schema** (keys are keywords): handle `pattern` (value) and `patternProperties` (regex keys); **skip** `const`/`enum`/`default`/`examples`, copying them verbatim; treat `properties`, `$defs`, `definitions` and `dependentSchemas` as **name→schema maps** (their keys are names — never sanitized, never read as keywords — and each value is recursed as a schema); recurse every other value as a schema (covers `items`, `prefixItems`, `allOf`/`anyOf`/`oneOf`, `not`, `if`/`then`/`else`, `contains`, `propertyNames`, `additionalProperties`, …).
   - The name-map handling is what keeps a property legitimately named `default` or `const` sanitized, so this fix does **not** trade a rare corruption for a common miss — verify both directions in the tests.
   **(b) Finding 3 — make `patternProperties` key stripping collision-safe.** Two keys differing only by identity escapes collapse to one; today the later silently overwrites the earlier. On collision, merge the two subschemas as `{"allOf": [existing, new]}` — the two equivalent patterns both apply to a matching property, so this is semantically correct and drops no entry.
   **(c) Finding 5 — de-silence the anthropic-mode transform fallback.** `server.py:981-991` suppresses the `transform_failure` trace event when `mode == "anthropic"`. Now that anthropic mode performs a real sanitize, a failure there must be visible: log the event for anthropic mode too (drop the `mode != "anthropic"` gate on that log).
   Update the `_sanitize_schema_patterns` docstring for the new contracts — with value keywords excluded, the "only two regex-typed locations" wording is removed entirely.

   → coder verify (auto): `const`/`enum`/`default`/`examples` values are returned unchanged; `properties.default.pattern` **is** sanitized; a `patternProperties` key collision yields an `allOf` merge, not a drop; the anthropic-mode `except` logs `transform_failure`.
   → tester verify: unit cases for both directions of the value-keyword/name-map split, the collision merge, and a preserved `patternProperties` key that does not collide; re-run the mutation script (extend it with a value-keyword mutation) and the full suite **foreground**.

## Guidance for Coder

**Files to modify:** `src/claude_retry_proxy/transforms_common.py`, `src/claude_retry_proxy/transforms_chat.py`, `src/claude_retry_proxy/transforms_response.py`, `src/claude_retry_proxy/server.py`. No other source files. Do not touch `tests/**` (tester lane) or any `.md`/`.html` (planner lane).

**Hard constraints:**

- **Never strip a backslash before an ASCII letter or digit.** This is the single invariant that keeps the rewrite meaning-preserving. Reviewers should check this by confirming the only branches that drop a backslash are gated on a non-alphanumeric, non-metacharacter condition (and the out-of-class `-` case).
- **Keep the metacharacter set** `^ $ \ . * + ? ( ) [ ] { } |` intact — their escapes are meaningful in every engine.
- **`-` is kept inside a character class, dropped outside.** The class tracker exists for this one character; do not generalize it or "simplify" it into an unconditional drop.
- **`_sanitize_schema_patterns` must never mutate its argument.** It builds a fresh structure at every dict/list level (immutable leaves may be shared — that is fine and still satisfies the no-mutation contract).
- **Both functions must be total.** No raising: a non-dict/list node, a non-string `pattern` value, a non-string `patternProperties` key, and all other keyword values pass through or recurse without assumption.
- **No new modules, no new dependencies, no trace events, no status-code changes.** The only observable change is that sanitized patterns reach the backend.
- **Match the repo's docstring depth** — a docstring that names the bug it fixes, the invariant, and the totality contract, in the style of the neighboring transforms.

## Guidance for Tester

**Tests to create — `tests/test_chat_transform.py` (add to `ALL_TESTS`):**

- **Direct string table (`_strip_regex_identity_escapes`)** — one test looping the full input→output table in Step 1, so a regression in any single rule fails loudly. Cover at minimum: the `^agent\_run\_` case, `-` both in-class and out, mixed in/out class, a no-op metacharacter string, a no-op class/control/hex/unicode/octal string, the `/ : @ !` punctuation strip, a trailing backslash, and the empty string.
- **Schema walk (`_sanitize_schema_patterns`)** — a nested schema with `pattern` at multiple depths (`properties`, `items`, `anyOf[0]`), a `patternProperties` object whose string keys carry escapes and whose values recurse to their own `pattern`, and assertions that non-string `pattern` values and non-dict nodes pass through unchanged.
- **No-mutation** — assert the input schema dict (deep-equal to its pre-call snapshot) is unchanged after the walk, and that the returned value is a *different* object.
- **Chat integration** — drive `_transform_anthropic_tools_to_chat` with a tool whose `input_schema` has `pattern: "^agent\\_run\\_"`; assert `out[0]["function"]["parameters"]` carries `^agent_run_` and the input `tools` list is unmutated.

**Tests to create — `tests/test_response_transform.py`:**

- **Response integration** — drive `_anthropic_to_response` with a tool whose `input_schema` has an escaped `pattern`; assert `out["tools"][0]["parameters"]` is sanitized and the input body is unmutated.

**Mutation discipline (non-negotiable for this plan's evidence).** The suite currently passes with the sanitizer absent, so a test that is merely green on the landed tree proves nothing. Revert each rule in a temp copy of `transforms_common.py` and confirm the matching test fails:
- Reverting the `_`/punctuation strip → the table test and the chat integration fail.
- Reverting the out-of-class `-` drop → the `foo\-bar` case fails.
- Reverting the in-class `-` keep → the `[a\-z]` case fails.
- Reverting the "never strip before a letter/digit" gate → the `\d`/`\s`/`\x`/`\u` no-op cases fail (they would be mangled to `d`/`s`/…).

**Existing tests to re-verify, not modify:**

- **`test_anthropic_to_chat_no_input_mutation` and `test_anthropic_to_chat_tools_transform`** — both must still pass unmodified (copy preserves no-mutation; dict equality is by value). Do **not** weaken either.
- **The full declared suite** (`python tests/test_claude_proxy.py`) must stay green; the response-mode transform tests in `tests/test_response_transform.py` already exist and the new integration test extends that file.

**Test isolation:** inherit the existing `_harness` isolation (`PROXY_TRACE_FILE`, `PROXY_STATE_FILE`, `PROXY_FEATURE_COMPAT_FILE` are session-temp paths already). New tests are pure function-level transforms and do not spawn a proxy; do not hand-build proxy paths.

## Guidance for Planner

Documentation the planner will sync after the tester confirms (not the coder):

- **`doc/provider-modes.html`** — in the chat and response tool-transform prose, add one line that `input_schema.pattern` strings (and `patternProperties` keys) are normalized by stripping ECMA identity-escape backslashes before forwarding, so strict-backend 400s on MCP-tool schemas do not occur. Frame it as a portability normalization, not a Go-specific fix — do not repeat the incorrect "Go RE2 rejects `\_`" claim.
- **`CLAUDE.md`** — a one-line Gotchas entry (or an Architecture bullet beside the mode-dispatch step) recording that tool-schema regexes are sanitized of identity escapes in chat and response modes before forwarding.
- **`doc/test-catalog.html`** — regenerate for the new test names in `tests/test_chat_transform.py`.
- No `.claude/mega-audit-files.json` change, no deferred-issue index change (this plan resolves none of the listed deferrals), no env-var or configuration doc change.

## History

One row per event (spec revision / mega-audit / review / implementation round). Conclusion = one-sentence outcome or what changed.

| Date | Event | Conclusion | Dismissed |
|------|-------|------------|-----------|
| 2026-10-06 | Initial plan | Normalize tool-schema `pattern` regexes by stripping ECMA identity escapes (the escape class that 400s on strict backends but is semantically redundant), applied in both chat and response transforms via one shared, total, non-mutating helper. Recorded and corrected the supplied root-cause: the failing backend is not Go RE2 (Go's `regexp/syntax` accepts `\` before any non-alphanumeric ASCII char), so the fix is justified on portability rather than on a false Go-compatibility claim. | — |
| 2026-10-06 | Round 1 (coder) — Steps 1–2 landed, no issues filed; report: [coder-2026-10-06.json](./tmp/reports/2026-10-06-re2-portable-tool-schema-patterns-coder-2026-10-06.json) | Both steps implemented: `_strip_regex_identity_escapes` + `_sanitize_schema_patterns` added to `transforms_common.py` (+88) and called from both tool transforms (`transforms_chat.py:335`, `transforms_response.py:258`); `__all__` extended; both imports updated. `build_result: pass`. **Planner-verified against every hard constraint** — the `keep` gate leads with the ASCII letter/digit range, the metacharacter set is exactly `^$\\.*+?()[]{}|`, `-` is kept only inside a class, the walk builds fresh dicts/lists, and neither call site retains a verbatim `"parameters": input_schema`. The landed helper was run against the plan's 11-row reference table: **11/11 PASS**, plus nested `pattern`, `patternProperties` keys *and* values, `items`, no-mutation (`input == snapshot`) and a fresh output object. The one long line (`transforms_response.py:258`, 106 cols) matches the file's existing 107–118 column style; the repo has no lint config or style test. | — |
| 2026-10-06 | Round 2 (tester) — six tests landed and mutation-proven, but **no report written** (round ended its turn with the suite backgrounded) | Added five tests to `tests/test_chat_transform.py` (reference table, schema walk, no-mutation, chat integration) and one to `tests/test_response_transform.py` (response integration), all registered in `ALL_TESTS`; plus `tmp/verification/…-mutation.py`. Targeted runs **47/47** and **38/38**; the mutation script prints **MUTATION DISCIPLINE PASSED** — reverting each of the four rules fails exactly its required tests, with baseline and restored copies green, so the tests are load-bearing rather than merely green. The diff is purely additive. **The round then backgrounded the full suite and exited at end-of-turn**, killing that run and leaving no session report — the deferred `operate-round-ends-turn-before-waiting`. Nothing else was lost: no `PROXY_*` process leaked. A report-only re-run is directed in Immediate Actions. | — |
| 2026-10-06 | Diagnosis correction — the plan's `anthropic mode` exclusion was wrong | **The live trace and admin `/providers-detail` show the failing provider `deepseek` runs `mode: "anthropic"`**, and that mode (`server.py:980`) forwards the parsed body verbatim — never calling the chat/response transforms. So the Step 1–2 sanitizer, correctly placed for chat/response, is bypassed on the exact request that 400s. Full suite on the Step 1–2 tree: **398 passed / 0 failed**. The plan now adds Step 3 to sanitize tool schemas on the anthropic-mode forward. No prior work is invalidated — chat/response coverage stands. | — |
| 2026-10-06 | Round 3 (coder) — Step 3 landed; report: [coder-2026-10-06-2.json](./tmp/reports/2026-10-06-re2-portable-tool-schema-patterns-coder-2026-10-06-2.json) | Added `_sanitize_body_tools` to `transforms_common.py` (exported via `__all__`) and wired it into the anthropic-mode `else` branch: `server.py:980` now does `json.dumps(_sanitize_body_tools(body_json))`; the `transforms_common` import gained the name. Planner-verified by direct call — sanitized copy, non-mutation, and passthrough for a non-dict body / missing tools / non-dict tools all correct. **Live-confirmed by the planner:** a real `model: "opus"` request (opus → deepseek, anthropic mode) carrying `pattern: "^agent\_run\_"` returned **200** from deepseek-flash — the exact request that previously 400'd. | — |
| 2026-10-06 | Round 4 (tester) — Step 3 tested; report: [tester-2026-10-06.json](./tmp/reports/2026-10-06-re2-portable-tool-schema-patterns-tester-2026-10-06.json) | `overall_result: SUCCESS`. Added two unit tests for `_sanitize_body_tools` (`tests/test_chat_transform.py`) and one anthropic-mode end-to-end test through the mock-upstream harness (`tests/test_mode_dispatch.py`) asserting the upstream-received body carries `tools[0].input_schema…pattern == "^agent_run_"` with the tool name and messages untouched. Full declared suite ran **foreground**: **401 passed / 0 failed / 401 total**. The mutation script was extended to 8 tests × 5 mutations and prints **MUTATION DISCIPLINE PASSED** — mutation E reverts `server.py`'s else branch and fails exactly the new e2e test (planner re-ran it independently: PASS). No issues filed; no skips; no pre-existing failures. | — |
| 2026-10-06 | Review (`reviewer`, Phase 6) — 0 Critical / 2 Warning / 3 Suggestion; report: [review-2026-10-06.json](./tmp/reports/2026-10-06-re2-portable-tool-schema-patterns-review-2026-10-06.json) | **Verdict: non-blocking, ready to commit.** Core rule, metachar set, `-` rule, totality and non-mutation all verified by direct execution; mutation E confirmed as genuine wiring proof. **Two Warnings:** (1) the `]`-first-in-class residual is a *confirmed* meaning change (`[]\-a]` → `[]-a]`), broader than the plan's own example — the plan's `[]\-]` example was in fact safe; (2) the walk rewrites a `pattern` key inside value keywords (`const`/`enum`/`default`/`examples`), silently corrupting asserted data. **User-directed disposition (2026-10-06):** fix finding 1 and the finding-2/4 docstrings in one bounded round; accept finding 2's corruption, finding 3 and finding 5 as documented residuals (Risks). | none Critical; findings 3 and 5 and the finding-2 corruption carried as accepted residuals rather than dismissed findings |
| 2026-10-06 | Round 6 (coder) — Step 4 landed (findings 2, 3, 5); report: [coder-2026-10-06-4.json](./tmp/reports/2026-10-06-re2-portable-tool-schema-patterns-coder-2026-10-06-4.json) | The walk is now position-aware (`_verbatim_copy` for `const`/`enum`/`default`/`examples`; `properties`/`$defs`/`definitions`/`dependentSchemas` walked as name→schema maps), `patternProperties` key collisions merge as `allOf`, and the anthropic-mode `except` now logs `transform_failure` (the `mode != "anthropic"` gate dropped). Planner-verified: 12/12 functional checks pass; 51/38/29 on the touched modules with no regressions. | — |
| 2026-10-06 | Round 7 + 8 (tester) — Step 4 tests landed, then a report-only re-run; report: [tester-2026-10-06-3.json](./tmp/reports/2026-10-06-re2-portable-tool-schema-patterns-tester-2026-10-06-3.json) | Round 7 added `sanitize-schema-patterns-value-positions` and `sanitize-schema-patterns-collision-merge` and extended the mutation script to 8 mutations × 10 tests, then exited without a report (the recurring early-exit). Round 8 was directed report-only and completed: `overall_result: SUCCESS`, full suite **403 passed / 0 failed / 403 total** (foreground), mutation script **MUTATION DISCIPLINE PASSED** (mutations F/G cover finding 2's two directions, H covers finding 3, E the server wiring, plus a finding-5 static check). All five review findings are now fixed. | — |

## Issue Log

No issues yet. Rows open here if the coder, tester, or a review finds defects.

| Issue | Status | Found | Resolved | Resolved By |
|-------|--------|-------|----------|-------------|

## Plan Metadata

```json
{
  "plan_id": "2026-10-06-re2-portable-tool-schema-patterns",
  "steps": [
    "Step 1: Add _strip_regex_identity_escapes and _sanitize_schema_patterns to transforms_common.py",
    "Step 2: Apply the sanitizer at both tool-transforms' input_schema -> parameters forwards",
    "Step 3: Sanitize tool input_schema patterns on the anthropic-mode verbatim forward (_sanitize_body_tools + server.py:980)",
    "Step 4: Remediate review findings 2, 3, 5 — position-aware schema walk, collision-safe patternProperties keys, de-silenced anthropic-mode transform fallback"
  ],
  "coder_files": ["src/claude_retry_proxy/transforms_common.py", "src/claude_retry_proxy/transforms_chat.py", "src/claude_retry_proxy/transforms_response.py", "src/claude_retry_proxy/server.py"],
  "tester_files": ["tests/test_chat_transform.py", "tests/test_response_transform.py", "tests/test_mode_dispatch.py"],
  "doc_files": ["doc/provider-modes.html", "CLAUDE.md", "doc/test-catalog.html"],
  "verification_scripts": ["./tmp/verification/2026-10-06-re2-portable-tool-schema-patterns-mutation.py"],
  "repo_mode": "Public",
  "document_overrides": []
}
```

## Audit Accumulation

*Counters reset when mega-audit runs. Used by Phase 5 entry trigger.*

| Counter | Value | Last Updated |
|---------|-------|--------------|
| issues_resolved_since_audit | 0 | 2026-10-06 |
| steps_changed_since_audit | 0 | 2026-10-06 |
| files_changed_since_audit | 5 | 2026-10-06 |

## Documentation

- `doc/provider-modes.html` — new "Tool-schema pattern normalization" section (`#pattern-normalization`): the stripper, the all-three-modes coverage, and the value-keyword exclusion.
- `CLAUDE.md` — a Gotchas-table row recording the all-modes normalization.
- `doc/test-catalog.html` — module counts updated to 51 / 38 / 29 and the 10 new test entries added.

## Final Results

**Completion date:** 2026-10-06
**Status:** COMPLETED

### What landed

Tool-schema regex portability. The proxy now strips **ECMA identity escapes** — a redundant backslash before a non-metacharacter, e.g. the `\_` Zod's `startsWith` emits for `"agent_run_"` — from every forwarded tool schema, in **all three endpoint modes**, so strict backends stop rejecting MCP-built schemas with `Invalid schema for function …`.

| File | Change |
|---|---|
| `transforms_common.py` | `_strip_regex_identity_escapes` (the stripper + class tracker), `_sanitize_schema_patterns` (position-aware walk), `_sanitize_body_tools` (anthropic-forward wrapper) |
| `transforms_chat.py:335`, `transforms_response.py:258` | call sites |
| `server.py:980` | anthropic-mode `else` branch sanitizes (`json.dumps(_sanitize_body_tools(body_json))`) |
| `server.py:981-991` | anthropic-mode transform failure now logged (finding 5) |

### Test results

- **403 passed / 0 failed / 403 total**, exit 0 — `python tests/test_claude_proxy.py` on the final tree; one known deferred warning (`no_proxy_stop event in trace`).
- **10 new permanent tests** — 8 in `test_chat_transform.py`, 1 in `test_response_transform.py`, 1 anthropic-mode e2e in `test_mode_dispatch.py`.
- **Mutation discipline PASSED** — `tmp/verification/2026-10-06-re2-portable-tool-schema-patterns-mutation.py`: 10 tests × 8 mutations (A–H) plus a finding-5 static check; every rule revert fails exactly its required test, baseline and restored copies stay green.
- **Live-confirmed** — a `model: "opus"` request routed to the `deepseek` provider (anthropic mode) carrying `pattern: "^agent\_run\_"` returned **200**, the exact request that previously 400'd.

### Review

Phase 6 review returned 0 Critical / 2 Warning / 3 Suggestion, non-blocking. **All five findings were fixed** (user-directed). Finding 1's stated rationale was corrected by the planner after measurement: the `]`-first-in-class divergence is PCRE-only, not ECMA (verified in Node); the fix is retained as the conservative, never-change-meaning side.

### Plan-completion note

Three of the four tester rounds exited their turn before writing a report — the deferred `operate-round-ends-turn-before-waiting`. No evidence was lost: each round's work was verified independently by the planner (targeted runs + the mutation script + direct functional checks), and a final report-only round produced the closing report against the finished tree.