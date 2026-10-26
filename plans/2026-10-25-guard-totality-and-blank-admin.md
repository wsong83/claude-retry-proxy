# Plan: Total JSON parse guards, and an admin surface that refuses on incomplete data
**Plan ID:** 2026-10-25-guard-totality-and-blank-admin
**Created:** 2026-10-25

## Immediate Actions

<!-- REWRITTEN 2026-10-27. This block is the live state; every earlier version was
     stale in exactly the way a coder round then filed an issue about
     (`immediate-actions-stale-after-iteration-3-audit`). -->

**Status: all eleven steps landed and verified. The plan is complete.**

- **Steps 1–11 landed.** Gates `...-step1.py` `PASS 22/22` (its walker is now proven
  identical to the permanent test's by AST comparison), `...-admin-page.py` `PASS 3/3`,
  `...-switch-input.py` `PASS 4/4`, `...-step6.py` `PASS 14/14`, `...-step8.py`
  `PASS 11/11`; full suite **455 slugs, 0 failures** (453+2 gated in the tester's sliced run; 455 passed in the planner's single invocation).
- **The iteration-3 mega-audit ran** (1 High / 19 Medium / 22 Low). Every finding is
  fixed, deferred with a filed report, or recorded as a Known Caveat.
- **Every Issue Log row is `Resolved` except three `Deferred`**, each backed by a
  standalone `./tmp/reports/defer-issue-*.json`.

**Remaining work — planner only:**
1. `## Final Results` is written (2026-10-27); present it for approval.
2. Then `/update-and-commit`.

**No further audit or review round is owed.** The iteration-3 audit returned 1 High,
below the ≥3-High re-audit threshold, and its counters were reset when it ran.

## Issue Log

Rows ordered newest-first (latest issues at top). New issues are prepended; resolved issues stay in place with updated status.

| Issue | Status | Found | Resolved | Resolved By |
|-------|--------|-------|----------|-------------|
| [step10-probe-breaks-step8-check-h](./tmp/reports/2026-10-25-guard-totality-and-blank-admin-step10-probe-breaks-step8-check-h.json) | Resolved | 2026-10-27 | 2026-10-27 | planner |
| [step10-unreadable-count-auto-check](./tmp/reports/2026-10-25-guard-totality-and-blank-admin-step10-unreadable-count-auto-check.json) | Resolved | 2026-10-27 | 2026-10-27 | planner |
| [step10-el-handle-breaks-admin-html-row-guard-pin](./tmp/reports/2026-10-25-guard-totality-and-blank-admin-step10-el-handle-breaks-admin-html-row-guard-pin.json) | Resolved | 2026-10-27 | 2026-10-27 | planner |
| [immediate-actions-stale-after-iteration-3-audit](./tmp/reports/2026-10-25-guard-totality-and-blank-admin-immediate-actions-stale-after-iteration-3-audit.json) | Resolved | 2026-10-27 | 2026-10-27 | planner |

<!-- ADDED 2026-10-27, post-commit. Four issue reports filed by coder round 5 had their
     defects fixed in place but were never given Issue Log rows, so they sat on disk as
     orphaned Open records — and a `tmp/reports/<plan-id>-*.json` sweep would have
     deleted them as transient artifacts with nothing recording that they were resolved.
     Caught while verifying the post-commit sweep glob, which is exactly the check the
     sweep's own content-type guard exists to force. -->
| [mega-audit-3-high-documentation-assigned-to-tester-lane](./tmp/reports/2026-10-25-guard-totality-and-blank-admin-mega-audit-2026-10-26-2.json) | Resolved | 2026-10-26 | 2026-10-26 | planner |
| [mega-audit-3-medium-step1-gate-drifted-from-permanent-test](./tmp/reports/2026-10-25-guard-totality-and-blank-admin-mega-audit-2026-10-26-2.json) | Resolved | 2026-10-26 | 2026-10-26 | planner |
| [mega-audit-3-medium-docs-maintain-an-exact-count](./tmp/reports/2026-10-25-guard-totality-and-blank-admin-mega-audit-2026-10-26-2.json) | Resolved | 2026-10-26 | 2026-10-26 | planner |
| [mega-audit-3-medium-plan-enumeration-drops-steps-8-9](./tmp/reports/2026-10-25-guard-totality-and-blank-admin-mega-audit-2026-10-26-2.json) | Resolved | 2026-10-26 |  2026-10-27  | tester |
| [mega-audit-3-medium-plan-stale-artifacts](./tmp/reports/2026-10-25-guard-totality-and-blank-admin-mega-audit-2026-10-26-2.json) | Resolved | 2026-10-26 |  2026-10-27  | tester |
| [mega-audit-3-medium-admin-page-drops-extra-tiers](./tmp/reports/2026-10-25-guard-totality-and-blank-admin-mega-audit-2026-10-26-2.json) | Resolved | 2026-10-26 |  2026-10-27  | tester |
| [mega-audit-3-medium-saveconfig-partial-render](./tmp/reports/2026-10-25-guard-totality-and-blank-admin-mega-audit-2026-10-26-2.json) | Resolved | 2026-10-26 |  2026-10-27  | tester |
| [mega-audit-3-medium-read-state-widening-collapses-unreadable](./tmp/reports/2026-10-25-guard-totality-and-blank-admin-mega-audit-2026-10-26-2.json) | Resolved | 2026-10-26 |  2026-10-27  | tester |
| [mega-audit-3-medium-reload-serialize-after-drain](./tmp/reports/2026-10-25-guard-totality-and-blank-admin-mega-audit-2026-10-26-2.json) | Resolved | 2026-10-26 |  2026-10-27  | tester |
| [mega-audit-3-medium-doc-coverage-gaps](./tmp/reports/2026-10-25-guard-totality-and-blank-admin-mega-audit-2026-10-26-2.json) | Resolved | 2026-10-26 | 2026-10-27 | planner |
| [mega-audit-3-medium-reviewer-suggestions-dropped-from-log](./tmp/reports/2026-10-25-guard-totality-and-blank-admin-mega-audit-2026-10-26-2.json) | Resolved | 2026-10-26 |  2026-10-27  | tester |
| [reviewer-suggestion-read-state-oserror-misreported-as-absent](./tmp/reports/2026-10-25-guard-totality-and-blank-admin-review-2026-10-26.json) | Resolved | 2026-10-26 | 2026-10-27 | tester |
| [defer-issue-admin-page-loadconfig-ignores-response-ok](./tmp/reports/defer-issue-admin-page-loadconfig-ignores-response-ok.json) | Deferred | 2026-10-26 | — | — |
| [defer-issue-parse-guard-gate-top-level-scope](./tmp/reports/defer-issue-parse-guard-gate-top-level-scope.json) | Deferred | 2026-10-26 | — | — |
| [mega-audit-3-medium-test-subsumed](./tmp/reports/2026-10-25-guard-totality-and-blank-admin-mega-audit-2026-10-26-2.json) | Resolved | 2026-10-26 |  2026-10-27  | tester |
| [step8-gate-check-f-contradicts-supplied-edit](./tmp/reports/2026-10-25-guard-totality-and-blank-admin-step8-gate-check-f-contradicts-supplied-edit.json) | Resolved | 2026-10-26 | 2026-10-26 | tester |
| [step8-grep-auto-check-matches-unrelated-string](./tmp/reports/2026-10-25-guard-totality-and-blank-admin-step8-grep-auto-check-matches-unrelated-string.json) | Resolved | 2026-10-26 | 2026-10-26 | tester |
| [defer-issue-switch-key-name-container-echo](./tmp/reports/defer-issue-switch-key-name-container-echo.json) | Deferred | 2026-10-26 | — | — |
| [reviewer-suggestion-generator-expression-not-enclosing](./tmp/reports/2026-10-25-guard-totality-and-blank-admin-review-2026-10-26-2.json) | Resolved | 2026-10-26 | 2026-10-26 | tester |
| [reviewer-suggestion-catalog-check-unlocked-snapshot](./tmp/reports/2026-10-25-guard-totality-and-blank-admin-review-2026-10-26-2.json) | Resolved | 2026-10-26 | 2026-10-26 | tester |
| [reviewer-warning-reload-success-body-unguarded-serialize](./tmp/reports/2026-10-25-guard-totality-and-blank-admin-review-2026-10-26-2.json) | Resolved | 2026-10-26 | 2026-10-26 | tester |
| [step6-stale-auto-check-unexpected](./tmp/reports/2026-10-25-guard-totality-and-blank-admin-step6-stale-auto-check-unexpected.json) | Resolved | 2026-10-26 | 2026-10-26 | tester |
| [step6-docs-describe-removed-tier-name-prohibition](./tmp/reports/2026-10-25-guard-totality-and-blank-admin-step6-docs-describe-removed-tier-name-prohibition.json) | Resolved | 2026-10-26 | 2026-10-26 | tester |
| [step6-gate-pass-summary-literal](./tmp/reports/2026-10-25-guard-totality-and-blank-admin-step6-gate-pass-summary-literal.json) | Resolved | 2026-10-26 | 2026-10-26 | tester |
| [reviewer-warning-nonstring-tier-provider-model-aborts-do-post](./tmp/reports/2026-10-25-guard-totality-and-blank-admin-review-2026-10-26.json) | Resolved | 2026-10-26 | 2026-10-26 | tester |
| [reviewer-suggestion-unbounded-tier-names-persisted](./tmp/reports/2026-10-25-guard-totality-and-blank-admin-review-2026-10-26.json) | Resolved | 2026-10-26 | 2026-10-26 | tester |
| [reviewer-suggestion-no-committed-coverage-for-step2-step3](./tmp/reports/2026-10-25-guard-totality-and-blank-admin-review-2026-10-26.json) | Resolved | 2026-10-26 | 2026-10-26 | tester |
| [admin-page-gate-sticky-counter-unreachable](./tmp/reports/2026-10-25-guard-totality-and-blank-admin-admin-page-gate-sticky-counter-unreachable.json) | Resolved | 2026-10-26 | 2026-10-26 | tester |
| [defer-issue-admin-unrendered-page-apply-throws](./tmp/reports/defer-issue-admin-unrendered-page-apply-throws.json) | Resolved | 2026-10-17 | 2026-10-26 | tester |
| [defer-issue-recursion-guard-residual-sites](./tmp/reports/defer-issue-recursion-guard-residual-sites.json) | Resolved | 2026-10-16 | 2026-10-26 | tester |

**Resolution (2026-10-26, tester round).** All three resolve on the same
evidence: tester session report
[2026-10-25-guard-totality-and-blank-admin-tester-2026-10-26.json](./tmp/reports/2026-10-25-guard-totality-and-blank-admin-tester-2026-10-26.json)
(`overall_result: SUCCESS`, 448 passed / 0 failed), which ran all three
planner-authored gates **unedited** and measured reachability rather than
asserting it. The planner re-ran all three gates independently after the round
and reproduced every figure before writing these rows.

- `admin-page-gate-sticky-counter-unreachable` — the press-scoped assertion
  re-measures `PASS 3/3 checks passed`, exit 0.
- `defer-issue-admin-unrendered-page-apply-throws` — resolved by Step 4. Gate 2
  check 1 (no `TypeError`, sticky refusal) and check 2 (no POST carrying
  `key: ""`), plus the two permanent `test_admin.py` pins, which the tester
  measured **RED against HEAD's `admin.html` and GREEN against the landed page**.
- `defer-issue-recursion-guard-residual-sites` — resolved as a **superset**: ten
  sites, not the three the deferral named (see the undercount analysis above).
  Gate 1 re-measures `PASS 22/22 parse sites have a total guard`; the tester
  measured HEAD's tree at **10/23 failing** and the landed tree at **0/22**, and
  confirmed the new invariant test fires on a mutant whose
  `cli._parse_trace_entry` guard is re-narrowed to `json.JSONDecodeError`.

Both `defer-issue-*.json` reports stay on disk until `/update-and-commit`
Step 9.6 deletes them in the same act that commits this plan — do not delete
them earlier.

**The three `Open` rows are Phase 6 reviewer findings the operator chose to fix**
(2026-10-26, after the review returned 0 Critical / 1 Warning / 5 Suggestion). All
three link to the same review report because they are findings *inside* it rather
than separate issue reports; the bracketed slug is the finding's identity.

The Warning is the load-bearing one, and it is why this plan was re-opened rather than
finalized: it is **the same defect class Step 3 exists to close, two lines below the
new check**, and it falsifies Step 3's original closure argument (corrected in place at
Step 3). The other two were folded in at the same time — the tier-name hole shares the
identical validation loop, and the coverage gap is the one the reviewer argued from
this plan's own history, since the mega-audit's four-High finding was an artifact that
never ran. Steps 6 and 7 close the first two; the third is only **half** closed — its
Step 3 half became `test_admin_switch_input_rejections`, while its Step 2 half (committed
coverage for `do_GET`'s `500`) is the open deferral
`defer-issue-config-serialize-500-no-committed-coverage`.

`step6-gate-pass-summary-literal` is a **Plan Error in the planner's own gate**, filed
by the coder during the Step 6 round and found independently by the planner in the same
window: `...-step6.py`'s success line was a hardcoded `PASS 8/10` while all ten checks
printed PASS and `failed == 0`. The verdict logic was never wrong — only the summary
literal, which is exactly why it survived calibration (the FAIL branch used the computed
count, so both calibrated runs read correctly). Classified **Plan Error**, fixed by the
planner in the gate's lane, and re-measured rather than assumed: the corrected script
was run against HEAD's tree (`FAIL 3/10`, exit 1) and the working tree (`PASS 10/10`,
exit 0). The coder's own suggested fix was the same edit.

**All six rows above resolve on the 2026-10-26 tester round**
([report](./tmp/reports/2026-10-25-guard-totality-and-blank-admin-tester-2026-10-26-2.json),
`overall_result: SUCCESS`, 450 passed / 0 failed). The evidence, per row:

- `reviewer-warning-nonstring-tier-provider-model-aborts-do-post` — the new
  `test_admin_switch_input_rejections` drives non-string `provider` (dict, list, int)
  and `model` (int, null) and asserts the response **arrives** before asserting 400, so
  the pre-change abort cannot pass it.
- `reviewer-suggestion-unbounded-tier-names-persisted` — tier names are now validated,
  and `test_admin_switch_extra_tier_persisted` pins the positive half on disk.
- `reviewer-suggestion-no-committed-coverage-for-step2-step3` — **its Step 3 half is
  closed** by the same parameterized table. Its Step 2 half (the `/admin/api/config`
  500) is **not**, deliberately: see the deferral below.
- the three `step6-*` rows — the tester ran all four planner gates unedited, including
  `...-step6.py` `PASS 14/14` and the corrected `(auto)` behaviour.

**One deferral was filed rather than left implicit:**
`defer-issue-config-serialize-500-no-committed-coverage.json` — the `/admin/api/config`
500 branch still has no committed coverage. It is deferred, not dropped, and it names a
concrete durable approach (inject an unserializable value into `_current_config` and
drive the handler in-process, as the module already does for the reload-stale gate)
rather than the deep-nesting fixture the plan rejected as host-dependent. A deferral is
a completed disposition and does not block finalization; no adopting row is added here,
so the file stays on disk as an open deferral for a future plan. It is enumerated in
`## Final Results`.

**Three further Suggestions were deliberately NOT taken into this plan** and remain
acknowledged in the review History row's Dismissed cell:
`reviewer-suggestion-read-state-oserror-misreported-as-absent` (the one site where
Step 1's widening changed a caller-visible outcome rather than merely covering a new
parse failure), `reviewer-suggestion-loadconfig-ignores-response-ok` (the page parses
Step 2's new 500 as a config and reports a JS `TypeError` instead of the server's
text), and `reviewer-suggestion-parse-guard-gate-top-level-scan-only` (the gate scans
the package top level only; true as a latent risk today). They are **offered to the
operator for deferral** — see the presentation — rather than silently dropped: each is
recorded here by slug so a future plan can adopt it.

`admin-page-gate-sticky-counter-unreachable` is a **Plan Error** in the planner's
own gate, not an implementation defect: `...-admin-page.py` check 1 asserted an
ABSOLUTE `setTimeoutCalls() === 0` over the page lifetime, but check 1's setup
rejects `/admin/api/config`, so `loadConfig`'s catch necessarily ran the
deliberately NON-sticky failure paint and took the counter to 1 before the press.
Its PASS branch was therefore reachable only by making that line sticky — the
change this plan's Summary records as dropped — so no Step-4-compliant
implementation could pass. Check 2 already used the correct press-scoped delta.

**The fix is applied and measured** (planner's lane — the script is a
planner-authored artifact): the assertion is now press-scoped, matching check 2,
and the script's CALIBRATION docstring records the revision and why the RED
calibration is unaffected (check 1 fails pre-change at the earlier
`rejected !== null` TypeError branch, which precedes the stickiness branch — the
same ordering that let the unreachable PASS branch go unnoticed at calibration
time). Re-run against the implementation: **`PASS 3/3 checks passed`, exit 0.**
<!-- UPDATED 2026-10-26 (post-tester /update-plan): the confirming tester report
     landed the same day, so this row is now Resolved — see the Resolution block
     above. The sentence here previously read "Status stays `Fix Planned` until a
     tester report confirms it, per the resolution rule." -->
Confirmed by the tester session report the same day; the row is now `Resolved`
(the evidence is in the Resolution block above).

This plan **adopts** both deferrals and was revised once, after a mega-audit,
to a scope the operator confirmed across six explicit decisions (2026-10-25):
total guards over per-name enumeration; a total guard at the unguarded
`do_GET` site rather than a gate allowlist; including the two sites the
deferral never scanned; including the four `json.load` twins; closing the
write-path abort over rejecting it; and refusing the Apply press over guessing
a key.

**The recursion deferral undercounts its own surface twice over.** Its AST scan
covered four modules and classified by the exception names of an *enclosing*
`try`, so it could see neither an unguarded site nor the modules it never read.
The gate finds **nine** failing parse sites, not three: the deferral's three, plus
`server.py` `do_GET` (unguarded), plus `cli.py:278`, `compat.py:268`,
`config.py:95`, `config.py:221` (all `json.load(fp)` — the same failure class,
invisible to a `json.loads`-only scan), plus `cli.py:157`. Its recorded fourth
site (`server.py:432`) was retired 2026-10-18 by
plan 2026-10-18-retry-nudge-digest-store and needs no action.

The mega-audit (§ History) additionally found two defects the deferrals never
named, both since reproduced and both fixed here: a client-reachable
no-response abort on the switch handler's **write** path (Step 3), and a silent
credential re-pointing on the admin page (Step 4).

## Guidance for Coder

**Files to modify:**

| File | Sites | Work |
|------|-------|------|
| `src/claude_retry_proxy/server.py` | 3 | `do_POST` parse guard; `do_GET` serialize; switch input bound |
| `src/claude_retry_proxy/transforms_chat.py` | 1 | `_chat_to_anthropic` tool-args parse guard |
| `src/claude_retry_proxy/transforms_response.py` | 1 | `_response_to_anthropic` function_call parse guard |
| `src/claude_retry_proxy/cli.py` | 2 | `_parse_trace_entry` parse guard; `_read_state` load guard |
| `src/claude_retry_proxy/keys.py` | 1 | `load_keys_file` parse guard |
| `src/claude_retry_proxy/config.py` | 2 | `load_models_document`; `_load_config_documents` |
| `src/claude_retry_proxy/compat.py` | 1 | `_load_compat_state` parse guard (Step 1i) |
| `src/claude_retry_proxy/admin.html` | 2 | `saveConfig` press guards |

<!-- CORRECTED 2026-10-26 (Phase 5 mega-audit, rule-enforcer Medium). `compat.py` was
     missing from this table and from the Plan Metadata `coder_files` array, even though
     Step 1i mandates editing it and the working tree shows it modified. The omission
     produced a contradiction the audit also caught: the History row said "Diff is 8
     files" while describing it as "confined to the plan's seven source files". The
     real count is EIGHT source files. -->

**Eight source files**, not seven — `compat.py` was omitted from the first version of
this table. No tests, no docs — those are the tester's and planner's lanes. Line numbers
are 2026-10-25 anchors; match on surrounding text if they have drifted.

**Round completion — read this before you start.** Run any command that can
spawn a proxy or run a test with an explicit `timeout`, and **write your session
report before you end your turn, whatever the result.**

### Step 1 — make all nine parse guards total

The rule: **every `json.loads` / `json.load` sits in a `try` with a total
handler (`except Exception`)**, and the `try` body holds the parse and nothing
else unrelated, so the broader handler cannot mask anything but the parse.
`except Exception` is required, not optional: `RecursionError` is a
`RuntimeError` and `UnicodeDecodeError` is a *sibling* of
`json.JSONDecodeError` under `ValueError`, so neither is caught by a
`JSONDecodeError` clause.

<!-- UPDATED 2026-10-26 (coder-reported): the rule originally read "the `try`
body stays a single call", which is not literal at the four `json.load(fp)`
sites (1e, 1g, 1h, 1i): their try bodies enclose `with open(...)` as well as the
parse, because the blocks this plan supplies preserve that pre-existing shape.
Read as "one parse call, no unrelated logic" the rule holds everywhere; the four
`json.loads` sites (1a, 1b, 1c, 1f) are literally one call. -->

Note for 1g and 1h: the total clause is appended AFTER the existing specific
clauses, which keep their messages and win by ordering. Do not reorder them.

**1a. `server.py`, `do_POST` (admin switch, ~3535).** Handler body unchanged.

```python
            body = self.rfile.read(content_length) if content_length > 0 else b""
            try:
                data = json.loads(body)
            except Exception:
                # Total by design. json.loads can fail on this bytes body as
                # JSONDecodeError (syntax), UnicodeDecodeError (bytes that are
                # not valid utf-8) or RecursionError (nesting deeper than the
                # interpreter will recurse). RecursionError is a RuntimeError
                # and UnicodeDecodeError is a SIBLING of JSONDecodeError rather
                # than a subclass, so naming only JSONDecodeError let both
                # escape and abort do_POST with no HTTP response at all.
                self._send_response(400, b'{"error":"invalid JSON"}')
                return
```

**1b. `transforms_chat.py`, `_chat_to_anthropic` (~584).**

```python
                elif isinstance(args, str):
                    try:
                        parsed_args = json.loads(args)
                    except Exception:
                        # Total by design: RecursionError is a RuntimeError, so
                        # a JSONDecodeError-only guard let a deeply nested
                        # upstream arguments string escape and lose the
                        # placeholder-block degradation that follows.
                        parsed_args = None
```

**1c. `transforms_response.py`, `_response_to_anthropic` (~372).** Same shape
and reason as 1b — upstream `arguments` on a `function_call` item.

```python
                elif isinstance(args, str):
                    try:
                        parsed_args = json.loads(args)
                    except Exception:
                        # Total by design: RecursionError is a RuntimeError, so
                        # a JSONDecodeError-only guard let a deeply nested
                        # upstream arguments string escape and lose the
                        # placeholder-block degradation that follows.
                        parsed_args = None
```

**1d. `cli.py`, `_parse_trace_entry` (~157).** The existing tuple is redundant
(`JSONDecodeError` already subclasses `ValueError`) and still misses
`RecursionError`.

```python
    try:
        obj = json.loads(line)
    except Exception:
        # Total by design: RecursionError is a RuntimeError, not a ValueError,
        # so the previous (JSONDecodeError, ValueError) tuple let a deeply
        # nested line escape and abort the whole prune pass. This guard's
        # contract is "unparseable line -> None -> preserved as-is", which
        # covers that case exactly.
        return None
```

**1e. `cli.py`, `_read_state` (~278).** `json.load(fp)` raises the same classes.

```python
    try:
        with open(PROXY_STATE_FILE) as f:
            return json.load(f)
    except Exception:
        # Total by design: a (FileNotFoundError, JSONDecodeError) tuple misses
        # both RecursionError (a RuntimeError) and UnicodeDecodeError (a
        # sibling of JSONDecodeError). This function's contract is "unreadable
        # state -> None", which covers both.
        return None
```

**1f. `keys.py`, `load_keys_file` (~141).** UTF-8 is already converted to
`ValueError` above; only the JSON clause changes, and its message stays as-is.

```python
    try:
        keys_data = json.loads(text)
    except Exception as e:
        # Total by design: RecursionError is not a JSONDecodeError, so a
        # gravely over-nested keys file escaped as a raw traceback instead of
        # the clean message this guard exists to produce.
        raise ValueError("keys file is not valid JSON: {}".format(e))
```

**1g. `config.py`, `load_models_document` (~95).** Append one clause AFTER the
existing `except OSError` clause. The four specific clauses keep their messages
and win by ordering; the total clause catches the residual. Do not reorder them.

```python
    except OSError as e:
        raise ValueError(
            "models.json cannot be read: {} ({})".format(models_path, e)) from e
    except Exception as e:
        # Total by design: this function's contract (see the docstring) is that
        # ANY unreadable or unparseable models.json becomes a clean ValueError,
        # because the server's startup handler catches only
        # (FileNotFoundError, json.JSONDecodeError, ValueError). A document
        # nested deeper than the interpreter recurses raises RecursionError,
        # which is none of those and escaped as a raw traceback.
        raise ValueError(
            "models.json cannot be parsed: {} ({})".format(models_path, e)) from e
```

**1h. `config.py`, `_load_config_documents` (~221).** Same treatment.

```python
    except OSError as e:
        raise ValueError(
            "config cannot be read: {} ({})".format(config_path, e)) from e
    except Exception as e:
        # Total by design: see load_models_document. RecursionError is neither
        # a JSONDecodeError nor an OSError, so a gravely over-nested config.json
        # escaped the clauses above as a raw traceback.
        raise ValueError(
            "config cannot be parsed: {} ({})".format(config_path, e)) from e
```

**1i. `compat.py`, `_load_compat_state` (~268).** All four names in this tuple
already share ONE message, so widening the tuple to `Exception` is
message-preserving — change the exception list only.

```python
    except Exception as e:
        print("[proxy] WARNING: compatibility state file unreadable "
              "({}) — failing open with empty state".format(
                  sanitize_error(str(e))), file=sys.stderr)
        return
```

→ coder verify (scripted): `python ./tmp/verification/2026-10-25-guard-totality-and-blank-admin-step1.py`
exits 0 with `PASS 22/22 parse sites have a total guard`. Against the pre-change
tree the same script prints `FAIL 13/23 ... (10 narrow, unguarded or aliased)`
and exits 1. (23 pre-change sites → 22 after, because Step 2 removes the
`do_GET` `json.loads` entirely.)

→ coder verify (auto): each `try` you touched holds the parse and no unrelated
logic — literally one call at 1a/1b/1c/1f, and the parse plus its `with
open(...)` at 1e/1g/1h/1i.

### Step 2 — guard the `do_GET` serialize instead of the round-trip

`server.py` `do_GET` (`/admin/api/config`, ~3391). Replace the round-trip AND
the unguarded outer encode with a single lock-held `json.dumps`:

```python
            # Serialize INSIDE the lock and send those bytes. The previous
            # json.loads(json.dumps(...)) round-trip existed to copy the config
            # so the outer dumps could run outside the lock — but it left the
            # ENCODE unguarded one line later, and a config that DECODES fine can
            # still fail to ENCODE (the encoder's ceiling sits below the
            # decoder's). Such a config aborted do_GET with no HTTP response.
            # json.dumps(json.loads(json.dumps(x))) is byte-identical to
            # json.dumps(x), so the round-trip bought nothing.
            try:
                with _config_lock:
                    payload = json.dumps(_current_config).encode("utf-8")
            except Exception:
                # Reachable: a hand-edited config.json can hold a document that
                # parses (decode ceiling ~16915) yet exceeds the encoder's
                # (~15505). Step 3 keeps client-supplied values out of this path.
                self._send_response(500, json.dumps({
                    "error": "the configuration could not be serialized"
                }).encode("utf-8"))
                return
            self._send_response(200, payload)
            return
```

Note: a plain `{"error": ...}` body is correct here — the admin surface is
deliberately outside the Anthropic error envelope.

→ coder verify (scripted): `...-step1.py` no longer lists any `do_GET` site, and
still exits 0.
→ coder verify (auto): `json.loads` no longer appears in `do_GET`; the new
`except Exception` encloses only the `json.dumps` call.

### Step 3 — reject unknown per-tier keys in the switch validation

`server.py`, the per-tier validation loop in `do_POST` (~3565), immediately
after the `isinstance(tier_config, dict)` check:

```python
                extra = set(tier_config.keys()) - {"provider", "model", "key"}
                if extra:
                    self._send_response(400, json.dumps({
                        "error": "tier '{}' has unsupported key(s): {}".format(
                            tier_name, ", ".join(sorted(extra)))
                    }).encode("utf-8"))
                    return
```

**Why this closes a no-response abort, not just tidies input.** `disk_config`
is built as `{"tiers": new_tiers}` and handed to `write_config`, whose
`json.dump(config, f, indent=2)` catches only `OSError`. Unknown keys were
neither rejected nor stripped, so a tier dict could carry an extra key holding
a deeply nested value straight into that serializer. Measured ceilings on this
interpreter: `json.loads` survives depth ~16915, `json.dumps(obj)` ~15505, but
`json.dump(obj, f, indent=2)` only **994** — `indent` moves the encoder onto the
pure-Python path, which recurses once per level in Python. So a ~2 KB body
carrying one unknown key at depth 995 passed every check and then raised
`RecursionError` out of `write_config`, out of the handler's `except OSError`,
and out of `do_POST` — no HTTP response, and a `config.json.tmp` left behind.

After this check every surviving *key name* is one of `provider`/`model`/`key`, so
no unknown key can carry a nested value into the serializer — the hole this step was
written for is closed by construction rather than by catching the exception
afterwards.

<!-- CORRECTED 2026-10-26 (Phase 6 reviewer Warning, independently confirmed).
     This paragraph previously read: "After this check every surviving value is
     provider/model/key, all of which _validate_admin_name bounds to a short
     safe-charset string, so nothing on the write path can nest."
     That OVERCLAIMED, and the correction matters because the plan was relying on it
     as the closure argument. `_validate_admin_name` bounds *strings*; it does not
     bound *values*, and for a non-string it RAISES rather than returning False —
     `_ADMIN_NAME_RE.match(name)` with a dict/list/int raises `TypeError: expected
     string or bytes-like object`, there is no outer try, and `do_POST` aborts with
     NO HTTP RESPONSE. That is the same defect class this step exists to close,
     two lines below the new check.
     MEASURED by the planner against a really spawned server (a review finding is
     not accepted on report):
       {"provider": {}}   -> RemoteDisconnected (no HTTP response)
       {"provider": ["x"]}-> RemoteDisconnected
       {"provider": 5}    -> no response within 15 s (socket stays open)
       {"model": 5}       -> no response within 15 s
       {"model": null}    -> no response within 15 s
       legitimate body    -> 200; unknown per-tier key -> 400; server survives the
                             whole series; no orphaned temp file.
     Evidence: ./tmp/verification/2026-10-25-guard-totality-and-blank-admin-reviewer-warning-probe.py
     (child stderr carries `TypeError: expected string or bytes-like object, got 'dict'`).
     So the unknown-KEY hole is closed and the non-string-VALUE hole is NOT.
     Disposition is the operator's — see ## Issue Log and ## Final Results. -->

→ coder verify (scripted): `python ./tmp/verification/2026-10-25-guard-totality-and-blank-admin-switch-input.py`
— exits 0 with `PASS 4/4 checks passed`. Against the pre-change tree the same
script prints `FAIL 1/4 checks passed` and exits 1, with check C reporting
`NO HTTP RESPONSE (RemoteDisconnected)` from a real spawned server.
→ coder verify (auto): the check sits after the dict check and before the
provider validation; it returns 400 and does not mutate `tier_config`.

### Step 4 — refuse the Apply press on an incomplete view

`admin.html`, `saveConfig` (~219). Two guards as the function's first
statements, before the `TIERS.forEach` that reads the nine selects. Do not
touch `reloadConfig` — it is a working recovery path (Step 5's check 3 pins it).

```js
        async function saveConfig() {
            // The tier selects exist only after renderTiers() has run, and the
            // failing initial-load path never reaches it. Reading one would
            // throw above this function's try, surfacing as an unhandled
            // rejection with no status line at all.
            if (!document.getElementById(`${TIERS[0]}-provider`)) {
                showStatus('error', 'Failed to load config — reload the page', true);
                return;
            }
            // /providers-detail supplies the key NAMES. When that fetch fails the
            // row still renders, so the page looks normal — but populateKeys
            // builds no options and disables the select, and a disabled select
            // still reads "". The server maps "" to names[0] (the provider's
            // FIRST key), not to "unchanged", so pressing Apply would silently
            // re-point every multi-key tier and persist it. Reload Providers
            // does not re-fetch provider-detail, so only a full page reload
            // clears this state.
            for (const tier of TIERS) {
                const provider = document.getElementById(`${tier}-provider`).value;
                if (provider && !(providerKeys[provider] || []).length) {
                    showStatus('error', 'The key list could not be loaded — '
                        + 'reload the page before applying', true);
                    return;
                }
            }
            const newConfig = {
                tiers: {}
            };
```

Both messages are sticky (third argument suppresses the 5-second auto-hide).
`providerKeys` is populated only by `loadProviderModes()`; every provider in the
live catalog carries at least one key name, so an empty entry means the fetch
did not succeed.

→ coder verify (scripted): `python ./tmp/verification/2026-10-25-guard-totality-and-blank-admin-admin-page.py`
— checks 1, 2 and 3 all PASS, exit 0. Pre-change: `FAIL 1/3` with checks 1 and
2 red (check 1 `TypeError: Cannot read properties of null (reading 'value')`;
check 2 POSTs with `sonnet key=""`) and check 3 green.
→ coder verify (auto): both guards precede the `TIERS.forEach`; `reloadConfig`
is byte-identical to its pre-change text; no `disabled` attribute or
`setSwapControlsDisabled` call was added to the load path.

### Step 6 — bound tier names, and type-check the values handed to the name validator

<!-- ADDED 2026-10-26 (Phase 6, iteration 2). Steps 1–5 are complete and verified;
     this is the next step number, not a renumbering. It closes the Phase 6
     reviewer's one Warning plus the Suggestion that shares its validation loop,
     after the operator chose "add a Step 6, fix now" over deferring them. -->

**Why this exists — two holes in the same loop, both measured.**
`do_POST`'s switch validation has two remaining unchecked inputs, and both are the
*class* Step 3 was written to close (a client-reachable abort with no HTTP response)
rather than a stylistic gap.

**Hole A — a non-string `provider`/`model` aborts the handler.** `provider` and
`model` are read with `.get(..., "")` and passed straight to `_validate_admin_name`,
which is `_ADMIN_NAME_RE.match(name)`. A regex `match` on a dict/list/int **raises**
`TypeError: expected string or bytes-like object` — it does not return `False`. There
is no outer `try` in `do_POST`, so the handler aborts and the socket closes with no
response. Measured by the planner against a really spawned server
(`./tmp/verification/2026-10-25-guard-totality-and-blank-admin-reviewer-warning-probe.py`):

```
{"provider": {}}     -> RemoteDisconnected (no HTTP response)
{"provider": ["x"]}  -> RemoteDisconnected
{"provider": 5}      -> no response within 15 s (socket stays open)
{"model": 5}         -> no response within 15 s
{"model": null}      -> no response within 15 s
```

Note the asymmetry that proves the point: `{"key": {}}` correctly answers **400**,
because the key check at `server.py:3611-3612` already tests `isinstance(key, str)`
*first*. The fix is to give `provider` and `model` the same treatment the key already
has — not a new mechanism, the existing one applied consistently.

**Hole B — tier *names* are unvalidated.** Only *missing* tiers are checked
(`required_tiers - set(new_tiers.keys())`), and nothing bounds the names that ARE
present, so arbitrary client text reaches `disk_config = {"tiers": new_tiers}` and is
persisted into `config.json`.

<!-- CORRECTED 2026-10-26 (Phase 5 mega-audit, finding `defect-tracer` Medium).
     The first version of this step closed Hole B by FORBIDDING extra tier names
     (`required_tiers.symmetric_difference(...)` -> 400). That was WRONG: extra tiers
     are a documented, supported shape, and the audit caught the step removing a
     capability instead of validating input.
       - doc/configuration.html: "Extra tiers beyond the required three are permitted,
         and are reachable through reverse lookup."
       - config.py validate_config iterates ALL tiers, commented: "not just the three
         required ones, because resolve_tier's reverse lookup can route to extra tiers".
       - resolve_tier (server.py:1877-1882) scans every tier.
       - the reload gate judges every tier of the candidate (server.py:3775).
     Before this step the switch was the only runtime path that could install a
     documented shape; the wrong version made hand-editing config.json the only one.
     The repair validates the name with the same `_validate_admin_name` rule the
     provider/model/key checks two lines below already use, which closes arbitrary
     text at rest while keeping extra tiers reachable. Gate checks C and C2 are the
     regression pin: a well-formed fourth tier must still be APPLIED and persisted. -->

**Coder edit 1 — validate tier names (do NOT restrict them).** In `do_POST`, immediately
**after** the existing `missing` check and **before** the
`# Validate provider names and model names` comment (i.e. after `server.py:3582`, before
`:3584`), insert exactly:

```python
            # Tier names are validated, NOT restricted: extra tiers beyond the
            # required three are a documented, supported shape (they are
            # reachable through resolve_tier's reverse lookup, and
            # validate_config iterates every tier for exactly that reason).
            # What must not survive is arbitrary client text landing in
            # config.json, so the name is bound by the same charset rule used
            # for provider/model/key below.
            for tier_name in new_tiers:
                if not isinstance(tier_name, str) or not _validate_admin_name(tier_name):
                    self._send_response(400, json.dumps({
                        "error": "invalid tier name: {}".format(tier_name)
                    }).encode("utf-8"))
                    return
```

**Do not reject a name merely for not being one of `haiku`/`sonnet`/`opus`.** Missing
required tiers are already handled above; extra tiers must pass through. The
`isinstance` test is trivially true for JSON object keys, but it mirrors the provider /
model / key checks and keeps the rule uniform if this loop is ever reached with a
non-string key.

**Coder edit 2 — type-check before the name validator.** In the same loop, replace the
two validator calls (`server.py:3600-3609`) with these four lines, keeping every
surrounding line untouched:

```python
                if not isinstance(provider, str) or not _validate_admin_name(provider):
                    self._send_response(400, json.dumps({
                        "error": "invalid provider name: {}".format(provider)
                    }).encode("utf-8"))
                    return
                if not isinstance(model, str) or not _validate_admin_name(model):
                    self._send_response(400, json.dumps({
                        "error": "invalid model name: {}".format(model)
                    }).encode("utf-8"))
                    return
```

**On echoing the offending value.** The `"{}".format(provider)` interpolation is safe
at every depth this endpoint can receive, and that was **measured rather than assumed**:
`str()` of a nested container is a second potential recursion site, and re-introducing
the abort while fixing the abort would be the worst outcome. At the 64 KB
`ADMIN_BODY_LIMIT`, `format()` succeeds for dicts to depth 10 000 and lists to depth
16 000 — every depth that fits. It also matches the existing surface's convention
(`"invalid key name: {}"`, `"unknown provider: {}"`) and passes through `json.dumps`.
Do not "improve" this to a bare type name; the echoed value is what makes the 400
actionable.

**Coder edit 3 — apply the catalog rule the reload gate already applies.**

<!-- ADDED 2026-10-26 (Phase 5 mega-audit, finding `oversight-catcher` Medium #28,
     measured). The switch loop never checks `model` against the live catalog, while
     the reload gate refuses a tier whose model is not in it
     (server.py:3786-3793). So Apply could install a configuration that Reload then
     rejects: a POST with `{"model": "model-not-in-catalog"}` returned 200 and was
     persisted, after which POST /admin/api/reload answered 400 naming that tier.
     Neither side was wrong — the DISAGREEMENT was, and the operator chose to make
     Apply validate. -->

In `do_POST`'s `# Validate providers exist` loop, immediately after the
`if provider not in provider_names:` block (after `server.py:3633`, before
`names = vendor_key_names(...)`), insert exactly:

```python
                # The reload gate already refuses a tier whose model is not in
                # the catalog; without this the switch accepts a configuration
                # that reload then rejects, so Apply and Reload would disagree
                # about the same rule. `model` is a validated string here.
                model = tier_config.get("model", "")
                catalog = (_current_config.get("models") or {}).get(provider)
                if not isinstance(catalog, list) or model not in catalog:
                    self._send_response(400, json.dumps({
                        "error": "tier '{}': unknown model '{}' for provider '{}'"
                                 .format(tier_name, model, provider)
                    }).encode("utf-8"))
                    return
```

This loop runs **after** the name-validation loop, so `provider` is already known to be
a string and `model` is already known to be a string — the `isinstance(catalog, list)`
half therefore guards only the catalog's own shape (a malformed `models` document), not
client input.

→ coder verify (scripted): `python ./tmp/verification/2026-10-25-guard-totality-and-blank-admin-step6.py`
— exits 0 with `PASS 14/14 checks passed` (ten request cases A, B, D, E1–E5, F, C, the
provenance precondition P, the persistence check C2, the debris check G and the survival
check H, all driven against a really spawned server). **Calibrated by
measurement, not predicted — three points:**

Fourteen checks: ten request cases (A, B, D, E1–E5, F, C), the provenance precondition P,
the persistence check C2, the debris check G and the survival check H.

| Tree | Result |
|------|--------|
| `HEAD` (no steps landed) | `FAIL 6/14`, exit 1 |
| working tree, Step 6 **as first landed** | `FAIL 11/14`, exit 1 |
| working tree, **corrected** Step 6 | `PASS 14/14`, exit 0 |

All three figures were re-measured with the gate's **final** text after its docstring was
edited to record them — a gate edited after calibration has an invalid calibration, so
the HEAD point (`git archive` temp tree) and the working-tree point were both re-run
against the final artifact rather than carried over.

The middle row is the important one and it is a *design* calibration, not just a code
one: against the first version of this step, exactly **F** and **C/C2** fail — F because
the switch still accepts an off-catalog model (`200` where `400` is required), and C/C2
because tier-name rejection turns a documented shape into a `400` and nothing reaches
disk. Every other check is already green there, which is what proves the two corrections
target the two wrong decisions rather than re-rolling the whole gate.

<!-- The HEAD and corrected-tree figures are filled in by measurement, not prediction;
     see the History row for this revision. -->

**The HEAD point was measured after the fact, and that matters.** The script's summary
literals were wrong on first write — the success line was a hardcoded `PASS 8/10`
against ten PASS lines — and were fixed *after* the first calibration. A gate edited
after calibration has an invalid calibration, so rather than assume the edit was
verdict-neutral it was re-measured: `src/claude_retry_proxy` was read out of HEAD with
`git archive` into a temp tree and the final script run there. The repo's own `src/` was
never edited, and the shadowing was verified before the result was trusted (importing
`claude_retry_proxy.server` from the temp tree resolved to the temp path and contained
no `symmetric_difference`). The fixing edit itself is defect `step6-gate-pass-summary-literal`
in the Issue Log, filed independently by the coder in the same round.
→ coder verify (auto): `server.py`'s switch handler contains
`isinstance(provider, str)` and `isinstance(model, str)`, both **before** their
`_validate_admin_name` call on the same line; the tier-name loop tests
`isinstance(tier_name, str) or not _validate_admin_name(tier_name)` and **does not**
reference `required_tiers` (no rejection of names merely for being non-standard); and
the model-catalog block tests `model not in catalog` inside the
`# Validate providers exist` loop.

<!-- CORRECTED 2026-10-26 (Step 8). This auto-check pinned the catalog read as a live
     `_current_config.get("models")` call inside the loop; Step 8 replaces that read
     with a lock-taken snapshot (`validated_models.get(provider)`), so the old wording
     would fail a correct implementation. It now pins the *predicate*, which is what
     Step 6 established and Step 8 preserves. Same defect class as
     `step6-stale-auto-check-unexpected` above: an auto-check that names an artifact a
     later step supersedes. -->

<!-- CORRECTED 2026-10-26 (coder-filed `step6-stale-auto-check-unexpected`). This
     auto-check previously read "`unexpected` is computed from `required_tiers` before
     the provider-validation loop" — a reference to the superseded
     `symmetric_difference` rejection, which the Phase 5 audit had this step remove.
     A `(auto)` check that names a symbol the step no longer creates is worse than no
     check: it either fails a correct implementation or trains the reader to skip it. -->
→ coder verify (auto): the rest of `do_POST` is unchanged — this step adds no `try`,
so it must not alter any other status code. Re-run the Step 3 gate
(`...-switch-input.py`, expect `PASS 4/4`) and the Step 2 gate
(`...-admin-page.py`, expect `PASS 3/3`) to prove no regression.

### Step 8 — close the reload's unguarded success body, and re-check the catalog when the epoch moves

<!-- ADDED 2026-10-26 (Phase 6, iteration 3). Steps 1–7 are complete and verified;
     this is the next step number, not a renumbering. It closes the second Phase 6
     review's one Warning and two of its four Suggestions, after the operator chose
     "fix the three real ones". -->

**Why this exists — three findings, all three measured by the reviewer.** The second
review (`...-review-2026-10-26-2.json`) returned **0 Critical / 1 Warning / 4
Suggestions**. Three are fixed here; the fourth is deferred (see the Issue Log).

**Finding 1 (Warning, `server.py:3865`) — the reload's success body is the last
unguarded serialization on the admin surface.** `response_body = json.dumps({...,
"config": candidate, ...})` sits inside a `try:` (3846) that has **only** a
`finally:` (3872) and no `except`, and `do_POST` has no outer `try`. `candidate`
carries the tier document loaded from disk, so a hand-edited `config.json` holding
one deep unknown-key value makes `POST /admin/api/reload` abort with **no HTTP
response** — after the install and epoch bump have already happened. It is the same
reachability Step 2 fixed at the `GET` site, one sibling over.

**Finding 2 (Suggestion, `server.py:3646`) — the catalog check validates against a
snapshot read outside `_config_lock`.** Phase 3 carries the **live** catalog forward
(`new_config["models"] = _current_config.get("models", {})` at 3699), so a reload that
finishes between the two can leave the switch persisting a tier whose model the reload
path rejects — the exact Apply/Reload disagreement Step 6 edit 3 exists to remove.
Single-flight does not cover the window: it begins at `_drain_for_swap()` (3673),
*after* the validation read.

**Finding 3 (Suggestion, `server.py:3628`) — deferred, not fixed.** The
`"invalid key name: {}".format(key)` container echo was measured safe on this
interpreter and is filed as `defer-issue-switch-key-name-container-echo`; see the
Issue Log and `## Final Results`.

**Coder edit 1 — snapshot the epoch and the catalog together.** In `do_POST`, replace
the head of the `# Validate providers exist` block, i.e. `server.py:3632-3633`, so the
loop body reads the snapshot rather than `_current_config`:

```python
            # Validate providers exist
            provider_names = set(_vendors.keys())
            # Snapshot the epoch and the catalog together, under the lock: the
            # check below validates against this snapshot, and Phase 3 re-checks
            # it when the epoch has moved by then (see there). Reading the two
            # separately would let a reload land between them.
            with _config_lock:
                validated_epoch = _config_epoch
                validated_models = _current_config.get("models") or {}
            for tier_name, tier_config in new_tiers.items():
```

and, in the same loop, replace `server.py:3646`'s

```python
                catalog = (_current_config.get("models") or {}).get(provider)
```

with

```python
                catalog = validated_models.get(provider)
```

Leave the comment above it (3641-3644) and the predicate (3647) untouched.

**Coder edit 2 — re-check the catalog in Phase 3 when the epoch moved.** Insert
**immediately after** `with _config_lock:` in Phase 3, i.e. after `server.py:3689` and
**before** the `# The provider catalog lives in models.json` comment at `:3690`:

```python
                    # The snapshot validated above was taken before this press
                    # owned the swap, so a reload that finished in between can
                    # have replaced the catalog it was checked against -- and
                    # Phase 3 carries the LIVE catalog forward. Re-check against
                    # that one when the epoch moved; otherwise the switch
                    # persists a tier that Reload then refuses, which is the
                    # Apply/Reload disagreement the check above exists to
                    # remove. Answering the same 400 keeps the operator's
                    # diagnostic identical to a fresh press.
                    if (response_status is None
                            and _config_epoch != validated_epoch):
                        live_models = _current_config.get("models") or {}
                        for _name, _cfg in new_tiers.items():
                            _catalog = live_models.get(_cfg.get("provider", ""))
                            if (not isinstance(_catalog, list)
                                    or _cfg.get("model", "") not in _catalog):
                                response_status = 400
                                response_body = json.dumps({
                                    "error": "tier '{}': unknown model '{}' for "
                                             "provider '{}'".format(
                                                 _name, _cfg.get("model", ""),
                                                 _cfg.get("provider", ""))
                                }).encode("utf-8")
                                break
```

The existing `if response_status is None:` at `:3704` already suppresses the write
when this sets a status, so no other line changes. **Do not** answer a 409 here and
**do not** introduce a `config_switch_stale` code: the operator's correct next action
is the same either way, and a re-check against the live catalog yields the *accurate*
diagnostic ("unknown model X for provider Y") rather than a generic staleness code
that would also need a page branch and a doc row. This differs deliberately from the
reload path's `config_reload_stale`, which must refuse wholesale because its
`candidate` is a whole document whose tiers it cannot re-validate.

**Coder edit 3 — serialize the reload's success body before installing it.** Replace
`server.py:3861-3871` (the `else:` branch of the reload's Phase 3) with:

```python
                    else:
                        # Serialize BEFORE installing. The success body embeds
                        # `candidate` -- the document loaded from disk -- and a
                        # config can decode yet fail to re-encode (the encoder's
                        # stack ceiling sits below the decoder's, and `indent=`
                        # collapses it again). Built after the install, such a
                        # failure would leave the swap applied and the epoch
                        # bumped while the client received NO HTTP response at
                        # all (this try has no `except`, and `do_POST` has no
                        # outer one). Built first, nothing has been installed
                        # yet, so the 500 is truthful: the previous mapping is
                        # still in force.
                        try:
                            success_body = json.dumps({
                                "status": "ok",
                                "config": candidate,
                                "drained": drained,
                                "waited_s": round(waited_s, 3),
                                "inflight_at_swap": inflight_at_press,
                            }).encode("utf-8")
                        except Exception:
                            response_status = 500
                            response_body = json.dumps({
                                "error": "the configuration could not be serialized"
                            }).encode("utf-8")
                        else:
                            _current_config = candidate
                            _config_epoch += 1
                            response_status = 200
                            response_body = success_body
```

`except Exception` is deliberate and matches Step 2's `do_GET` guard: the raising
classes here are `RecursionError` (a `RuntimeError`) and `TypeError`, and naming only
`ValueError` would let `RecursionError` through — the same class-split mistake
[`doc/architecture.html#json-ceilings`](../../doc/architecture.html) records.

**Planner doc edit (already applied, do not re-apply).** `doc/operations.html:178-182`
now records the reload's `500` in the `<code>/admin/api/reload</code>` row.

→ coder verify (auto): `server.py` contains exactly one `with _config_lock:` between
`# Validate providers exist` and the `for tier_name, tier_config in new_tiers.items():`
that follows it, and in that block `validated_epoch = _config_epoch` precedes
`validated_models = ...`; **the only occurrence of `_current_config.get("models")` in
that region is INSIDE that lock block** (it is the snapshot itself — see the correction
note below), and the loop body reads `catalog = validated_models.get(provider)`;
Phase 3's lock block opens with `if (response_status is None` /
`and _config_epoch != validated_epoch):`; and the reload's success `json.dumps` is inside
a `try:` whose `except Exception:` sets `response_status = 500` and whose `else:`
performs the `_current_config = candidate` assignment — verified by **enclosure**
(`try`-block membership), never by grepping for `except`.
→ coder verify (auto): `grep -c '"the configuration could not be serialized"' src/claude_retry_proxy/server.py`
— the **quoted literal** — returns **3**: the `do_GET` site Step 2 added, the reload's
pre-drain probe (Step 10 edit B), and the reload's post-drain guard added here.

<!-- CORRECTED 2026-10-27 (coder-filed `step10-probe-breaks-step8-check-h`). This check
     and the gate's check H were pinned at 2 until Step 10 added a third legitimate site;
     a faithful implementation of Step 10 therefore turned the Step 8 gate RED and made
     Step 10's own "expect no change" verification unsatisfiable. Both now read 3 and name
     all three sites. The lesson is the same one this plan has now recorded four times: a
     count pinned to a literal must name every producer of that literal. -->

<!-- CORRECTED 2026-10-26 (coder-filed `step8-gate-check-f-contradicts-supplied-edit` and
     `step8-grep-auto-check-matches-unrelated-string`). Two defects in this block, both
     of the class the plan exists to remove — a verification that does not measure what
     it claims:
       1. It required `_current_config.get("models")` to be ABSENT from the validation
          region, while edit 1 above supplies that exact expression INSIDE the lock as
          the snapshot. No implementation could satisfy both, and the coder measured the
          consequence: `FAIL 8/9`, F the sole failure, against a correct implementation.
          The check now tests intent (the only read is the lock-taken snapshot) and the
          gate proves the predicate still discriminates via pinned literals F1/F2.
       2. The grep used the unquoted substring `could not be serialized`, which also
          matches the pre-existing, unrelated SSE message `"response frame could not be
          serialized"` at `server.py:2357` — so the check demanded 2 while the honest
          answer was 3, and would have passed only for the wrong reason. Now the quoted
          literal. The gate's own check H already counted the quoted literal; the plan
          did not, which is the same drift one level up. -->
→ coder verify (auto): re-run all four existing gates and expect no regression —
`...-step6.py` (`PASS 14/14`), `...-switch-input.py` (`PASS 4/4`), `...-admin-page.py`
(`PASS 3/3`), and the suite (`450 passed`).
→ coder verify (scripted): run the extended gate
`./tmp/verification/2026-10-25-guard-totality-and-blank-admin-step8.py` and paste its
summary line. It is calibrated at **two** points — pre-Step-8 working tree (MEASURED
`FAIL 4/9`, exit 1, against the pre-F-split gate) and post-Step-8 working tree
(MEASURED `PASS 11/11`, exit 0) — and its header records both, including why the RED
figure is not re-run (the tree it measured no longer exists; the pre-fix text is pinned
as a literal and re-proved by F1 on every invocation). There is no HEAD point: every
check it turns RED is created by Step 8, so a HEAD run would move nothing. Its RED run
is the reviewer's Warning reproduced end-to-end:
`FAIL B  reload of a config that cannot be re-encoded -> NO HTTP RESPONSE
(TimeoutError)`. **Expect `PASS 11/11`.**

### Step 10 — the three code Mediums the iteration-3 audit found

<!-- ADDED 2026-10-26 (Phase 5 mega-audit iteration 3). The audit's 19 Mediums were
     triaged; three need code and are fixed here, the rest are plan text or doc work in
     the planner's lane. All three are pre-existing behaviours that this plan made
     load-bearing, except edit B, which repairs a hazard Step 8 introduced. -->

**Coder edit A — `_read_state` must not collapse "unreadable" into "absent"**
(`cli.py:279-287`; callers at 443, 649, 746, 788). Step 1 widened the guard to
`except Exception`, which is right for the parse classes — but the function's contract
("unreadable → None") then makes `cmd_stop` print **"Proxy: not running (no state
file)" and exit 0** over a state file that is present and whose proxy is alive,
contradicting the documented stop contract (CLAUDE.md Gotchas / `#stop-contract`).
Reachable on Windows without a corrupt file: the heartbeat rewrites the file every 30 s,
so a transient sharing violation lands in this clause.

Insert immediately above `def _read_state():`:

```python
_UNREADABLE = object()
```

and replace the function body with:

```python
def _read_state():
    """Read proxy-state.json.

    Returns the parsed dict; `None` when the file genuinely does not exist; or
    `_UNREADABLE` when it exists but could not be read. The three outcomes are
    deliberately distinct: collapsing "unreadable" into "absent" makes `cmd_stop`
    report "not running" — exiting 0 — over a state file whose proxy is still
    alive, which contradicts the documented stop contract. Totality is kept: a
    `(ValueError, JSONDecodeError)` tuple would miss `RecursionError` (a
    `RuntimeError`) and `UnicodeDecodeError` is a sibling of `JSONDecodeError`,
    not a subclass.
    """
    try:
        with open(PROXY_STATE_FILE) as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except Exception:
        return _UNREADABLE
```

Then, **at each of the four call sites**, branch on the sentinel before the existing
`if not state:` / `if state:` test. Use this exact shape (wording per command,
`return 1` in all four):

```python
    if state is _UNREADABLE:
        print("ERROR: the state file {} exists but could not be read; the proxy "
              "may still be running".format(PROXY_STATE_FILE))
        return 1
```

`cmd_status` is the one command that currently returns 1 when not running, so its
unreadable branch returning 1 as well is consistent. Do **not** delete the file on this
path — an unreadable-but-present state file is the orphan's only handle.

**Coder edit B — decide the reload's serializability BEFORE the press**
(`server.py:3861-3863`). Step 8 edit 3 moved the success-body serialize ahead of the
*install*, but still after `_drain_for_swap()` — and the drain pauses all admissions,
waits with no wall-clock cap, and abandons retry chains. So a press that can never
succeed still performs a disruptive press, contradicting the reload's own ordering rule
stated ~60 lines above ("the catalog is loaded, and the gate run, BEFORE the press …
rather than after an unbounded drain"). The auditor measured it: 500 returned, drain
invocations = 1.

Insert **immediately before** the `# Drain-and-swap: pause admissions` comment that
precedes `drain = _drain_for_swap()` in the reload handler:

```python
            # Whether the success body can be serialized is decidable BEFORE the
            # press: its only raising component is `candidate`, and the three
            # drain scalars are JSON-safe. Probe it here so a press that can
            # never succeed does not drain — the same ordering rule the gate
            # above follows, for the same reason (a refused reload abandons no
            # retry chains). The post-drain build stays as it is; this is the
            # early refusal, not a replacement for the total guard there.
            try:
                json.dumps(candidate)
            except Exception:
                self._send_response(500, json.dumps({
                    "error": "the configuration could not be serialized"
                }).encode("utf-8"))
                return
```

**The post-drain guard stays.** It is not redundant: it still catches a failure that
the probe's shallower shape somehow misses, and it is what the committed test drives.

**Coder edit C — the press guard must be self-sufficient** (`admin.html:236-243`).
Guard 1 tests only the `haiku` provider select; guard 2 then dereferences all nine with
no null check. Both sit **above** `saveConfig`'s own `try`, so a missing select raises
`TypeError: Cannot read properties of null (reading 'value')` as an unhandled rejection
with no status line — the exact failure guard 1 was added to remove, one row later.

Replace guard 2's loop head:

```js
            for (const tier of TIERS) {
                const provider = document.getElementById(`${tier}-provider`).value;
```

with:

```js
            for (const tier of TIERS) {
                // The element may be missing even when guard 1 passed: both
                // guards sit ABOVE saveConfig's try, so a null dereference here
                // rejects unhandled with no status line — the failure guard 1
                // removed, one row later. Checking the handle makes this guard
                // self-sufficient instead of relying on the haiku row standing
                // in for all nine selects; once this loop completes, the two
                // later loops' dereferences are safe by construction.
                const el = document.getElementById(`${tier}-provider`);
                if (!el) {
                    showStatus('error', 'Failed to load config — reload the page', true);
                    return;
                }
                const provider = el.value;
```

**Coder edit D — record the extra-tier contract on the page.** The Apply press rewrites
the tier map to the three standard tiers, so a documented extra tier is deleted
(`admin.html:244-253` × `server.py:3724`). MEASURED by the auditor: after a
page-identical press against a config holding `ghost-tier`, the on-disk and in-memory
maps are exactly `['haiku','opus','sonnet']`. The audit offered two resolutions; **this
plan takes (a), document it**, because (b) — seeding `newConfig.tiers` from
`config.tiers` — makes every Apply press 400 whenever a preserved extra names a model
absent from the live catalog, i.e. it converts an invisible edit into a blocked UI on
exactly the configs that have extras. Do **not** change `saveConfig`'s tier list. The
doc line is the planner's and is already applied (`doc/operations.html` admin section).

→ coder verify (auto): `grep -c "_UNREADABLE" src/claude_retry_proxy/cli.py` returns
**7** (the sentinel definition, the docstring reference, the `except` return, and one
branch at each of the four call sites) — and `grep -n "if state is _UNREADABLE"` lists
**four** lines.

<!-- CORRECTED 2026-10-27 (coder-filed `step10-unreadable-count-auto-check`). The check
     pinned 6 while its own parenthetical enumerated seven distinct lines; `grep -c`
     counts lines, so a faithful implementation measured 7 and the only way to reach 6
     was to delete the docstring line the plan itself supplies. Planner arithmetic
     error, fixed to the measured value. -->
→ coder verify (auto): the reload handler contains `json.dumps(candidate)` **before**
`drain = _drain_for_swap()`, and the existing post-drain `success_body = json.dumps({`
block is unchanged — both by position in the source, not by count.
→ coder verify (auto): `admin.html`'s `saveConfig` contains `const el =
document.getElementById(`${tier}-provider`);` inside the `for (const tier of TIERS)`
guard loop, and no remaining bare `.value` dereference in that loop.
→ coder verify (scripted): re-run all five gates (`22/22`, `3/3`, `4/4`, `14/14`,
`11/11`) and the full suite; report the measured totals. **Expect no change** to the
gate numbers: none of these edits touches a parse guard, the switch validation, the
page's press guards, or the reload's serialize path's shape.

## Guidance for Tester

### Step 11 — committed coverage for Step 10's three behaviours (added 2026-10-26)

**Part A — an unreadable state file is not an absent one.** Call `cli._read_state()` with
`cli.PROXY_STATE_FILE` pointing at a directory (so `open` raises `IsADirectoryError`, an
`OSError`, without needing permissions this platform may not enforce) and assert the
return **is** `cli._UNREADABLE` — identity, not truthiness, because the whole defect was
that a falsy sentinel could not be told from `None`. Then point it at a nonexistent path
and assert the return **is** `None`. Finally assert the four call sites branch: call
`cli.cmd_stop` / `cmd_status` with an unreadable state file (patch `sys.argv` and capture
stdout) and assert **exit status 1** and that the output does **not** contain "not
running (no state file)". Restore `cli.PROXY_STATE_FILE` and `sys.argv` in a `finally:`.

**Part B — the reload refuses before draining.** In-process reload
(`object.__new__(srv.ProxyHandler)`) with `srv._current_config` poisoned exactly as in
`test_admin_reload_serialize_failure_500`'s fixture (a `set` under an unknown per-tier
key), and `srv._drain_for_swap` rebound to a stand-in that **counts its invocations and
then calls the real one**. Assert the status is **500**, the message is the documented
one, and the count is **0** — the press never happened. Restore both in a `finally:`.
The existing `test_admin_reload_serialize_failure_500` must keep passing unchanged: the
post-drain guard is still there, and this new test pins the *ordering*, not the guard.

**Part C — Apply rewrites the tier map, and that is now the documented contract.** In
process, drive `/admin/api/switch` with a page-identical three-tier body against a
`_current_config` carrying a fourth, well-formed `ghost-tier` whose model **is** in the
catalog, and assert the response is **200** and that the persisted and in-memory tier
maps are exactly `{haiku, opus, sonnet}` — i.e. the extra tier is gone. This pins a
deliberate, documented behaviour, not a bug: if a later change ever round-trips extras,
this test fails and whoever made it must update
`doc/operations.html`'s "Apply rewrites the tier map" paragraph in the same change. Say
that in the test docstring, so the failure message explains itself.

Note the contrast deliberately: `test_admin_switch_extra_tier_persisted` (Step 7) pins
that the **API** accepts and persists a fourth tier when the client sends one. Both are
true and neither contradicts the other — the API honours what it is given; the page
sends only three. Do not "reconcile" them by changing either.

**Part D — repair the ordering pin Step 10 edit C invalidated** (coder-filed
`step10-el-handle-breaks-admin-html-row-guard-pin`).
`tests/test_admin.py::test_admin_html_apply_requires_rendered_row` (via
`_save_config_requires_rendered_row_checks`) locates the first tier-select read with a
regex that only matches the **direct dereference** form,
`document.getElementById(`${tier}-provider`).value`. Edit C replaced that with a
null-checked handle (`const el = document.getElementById(...); if (!el) {...};
const provider = el.value;`), so the regex now finds nothing in the guard loop and the
ordering assertion silently anchors on a later read — **the test reports a PASS about a
different position**. That is the `assertion-swaps-need-reachability-measurement` failure
mode, and it is why this must be fixed rather than merely made green.

Widen the matcher to accept **both** spellings, or anchor the ordering assertion on the
guard loop's first `getElementById` call instead of on a `.value` dereference. The
assertion must keep testing the **property** — that the press refuses before it reads or
sends anything — not one spelling of the read. Prove the repaired assertion still has a
reachable failing branch: with the guard removed from a copy of `admin.html`, the test
must fail; say which mutant you ran and what it reported.

**Run and report:** the three new slugs via `-t` with their `>> <slug>: PASSED` lines,
the full suite (record the new total; expect **452 + 3**), and all five planner gates
unedited (`22/22`, `3/3`, `4/4`, `14/14`, `11/11`). Also confirm
`test_admin_reload_serialize_failure_500` still passes unchanged. Report measured
counts, not claims.


**Tests to create:**

- **Permanent — `tests/test_parse_guards.py` (new module): the parse-guard
  totality invariant.** Walk every `*.py` under `src/claude_retry_proxy/` with
  `ast`; for every `json.loads(...)` and `json.load(...)` call and every bare
  `loads(...)`/`load(...)` name call, assert an enclosing `try` whose handlers
  are total. Report one line per site plus a summary, in the suite's style.
  Assert the site count is non-zero so a path or parse failure cannot pass
  vacuously. Baseline pre-change: 10 of 23 sites fail; post-change 0 of 22.
  **Do not use `ast.unparse`** — the package declares `requires-python = ">=3.8"`
  and `ast.unparse` needs 3.9; read exception names off the nodes directly, as
  the step-1 script does.
- **Permanent — `tests/test_admin.py`: two structural pins on `admin.html`.**
  (a) `saveConfig` tests for a rendered tier row before it reads any tier
  select; (b) `saveConfig` refuses when a tier's provider has no entry in
  `providerKeys`. Shape them like the module's existing `admin.html` assertions
  — those serve the page from a live proxy (`_admin_get(proxy_port, "/admin/")`),
  not by reading the file; a cwd-relative `open()` would break the documented
  invocation from a different directory unless you anchor it the way
  `tests/test_docs.py:24` does. Make each failing branch genuinely reachable.
- **Temporary:** none required.

**Register the module — this is required and easy to miss.**
`tests/test_claude_proxy.py` is a hand-maintained aggregator: it imports each
area module's `ALL_TESTS` explicitly (17 imports) and concatenates them, and
`run_cli` does no discovery. There is no `conftest.py` and no pytest config, so
`python tests/test_claude_proxy.py` is the only runner, and **an unregistered
module never executes**. Add:

```python
from test_parse_guards import ALL_TESTS as PARSE_GUARDS_TESTS
```

and append `PARSE_GUARDS_TESTS` to the `ALL_TESTS` tuple.

**On the admin page's behavioural coverage.** The page's JavaScript is never
executed by the Python suite, and this repo has deliberately **not** committed a
Node-driven `admin.html` test: the precedent
(`tmp/verification/2026-10-12-swap-silence-drain-409-rendering.py`) records
outright that its Node execution "is NOT a committed regression test". Follow
that precedent — do **not** introduce a Node dependency into the suite. The
behavioural contract for this plan is pinned by
`./tmp/verification/2026-10-25-guard-totality-and-blank-admin-admin-page.py`;
run it and report its result. If you believe the Node gap is now worth closing
permanently, say so in your report as a recommendation rather than adding it
unilaterally — that is an architecture decision, not a test decision.

**Verification scripts to create:** none. All three scripts named in this plan
are planner-authored and already calibrated; run them, do not edit them.

**Tests to investigate for retirement:**
- Planner candidates: **none.** `tests/test_tier_routing.py::test_deep_nested_body_invalid_json`
  covers the client-body path end-to-end (a real proxy returning `400
  invalid_json`) and stays valid and load-bearing — the new totality gate checks
  guard *shape* statically and does not subsume it. No other test exercises the
  sites being widened.
- Tester may identify additional candidates during test work.

**Retirement procedure:** For each candidate, verify the test exercises code
being removed/changed. If obsolete: delete and note in session report. If still
valid: document why in session report.

**Round gates to report:** the full suite, the new module alone, the new module
listed by `python tests/test_claude_proxy.py --list` (slug match — a green exit
alone does not prove it ran), and all three verification scripts. Report measured
counts, not claims.

### Step 7 — committed coverage for the switch validation (added 2026-10-26)

<!-- ADDED 2026-10-26 (Phase 6, iteration 2). Closes the reviewer's Suggestion
     `reviewer-suggestion-no-committed-coverage-for-step2-step3`, which observed that
     Steps 2 and 3 have no committed coverage at all — only the tmp/verification/
     scripts that the post-commit sweep retires. The reviewer's argument is this
     plan's own history: the mega-audit's four-High finding was an artifact that
     never ran, and the plan's response to that was to demand a permanent test.
     Leaving its own two server behaviours covered by transient scripts only would
     be the same shape one level down. -->

<!-- REVISED 2026-10-26 (Phase 5 mega-audit, `test-impact` + `conflict-resolver`
     Mediums). The first version specified FOUR tests. The audit showed one was an
     outright duplicate and the other three repeated a rejection harness that already
     exists three times in the module, which is why this is now ONE parameterized test
     plus a fix to an existing test. -->

**Part 1 — fix a false-GREEN branch in the Step 5 module.** `tests/test_parse_guards.py`
`_guard_for` walks the whole ancestor chain for `try` nodes and does not stop at a scope
boundary, so a parse inside a `def`/`async def`/`class`/`lambda` that is merely *defined
in* a try body is reported as guarded — even though that try cannot catch the call when
the nested scope is later invoked. Measured by the audit with the module's own
`_scan_source`: `try:\n    def f():\n        return json.loads(s)\nexcept Exception:\n
pass` yields **sites 1 / failures 0**. No live site has this shape today (all 22 were
re-scanned, 0 failures), so this is latent — but the gate exists precisely to replace
per-site review for code written later, and `test_parse_guard_scanner_semantics` claims
to pin every accept/reject branch with no case for this one.

Change `_guard_for` so a `try` whose direct-child statement on the path is
`ast.FunctionDef`, `ast.AsyncFunctionDef`, `ast.ClassDef` or `ast.Lambda` is **not**
treated as enclosing (keep walking outward), and add those three synthetic shapes to
`_SCANNER_CASES` with `expected_site_failures = 1` so the new branch is reachable and
pinned. Report the case count before and after.

**Part 2 — one parameterized rejection test in `tests/test_admin.py`.** Replace the four
separate tests with a single `test_admin_switch_input_rejections` driving one started
proxy over a `(label, body, expected_message_fragment)` table, asserting for every row:
the response **arrives**, its status is `400`, the message names what was rejected, and
`GET /admin/api/config` shows the persisted mapping untouched.

| Row | Body | Pins |
|-----|------|------|
| unsupported per-tier key | a tier carrying `{"x": []}` | Step 3's `extra` check — the only coverage of it |
| unknown tier name | a two-tier body | the existing `missing` half (complements `test_admin_api_switch_missing_tier_rejected`) |
| invalid tier name | a fourth tier named `bad tier!` | Step 6's name validation |
| non-string provider | `provider` as dict, list and int | Step 6's Hole A — **assert the response arrives**, since the pre-change failure mode was no response at all and a "not 200" assertion would pass on a hung socket |
| non-string model | `model` as int and null | Step 6's Hole A |
| model not in catalog | `{"model": "model-not-in-catalog"}` | Step 6's edit 3 — the rule Reload already enforces |

Reuse the module's existing rejection-harness idiom rather than hand-rolling a fourth
copy; if a shared helper is the natural fit, extract one and note it in your report.

**Also add — the positive half of the tier-name rule**, which no existing test covers
and which the plan has already got wrong once: a switch carrying a **well-formed extra
tier** (`ghost-tier`) must return **200** and the extra tier must be present in the
persisted `config.json`. Extra tiers are documented and supported
(`doc/configuration.html`), so this pins that the validation did not become a
prohibition. Give it its own slug — a regression pin that asserts a *success* should not
be buried in the rejection table.

**Not specified, and the reason changed.** The first version proposed
`test_admin_api_config_ok`; the audit showed `test_admin_api_config`
(`tests/test_admin.py:104`) already GETs that endpoint and fails on any non-200, and the
endpoint's happy path is asserted 200 in six further places. **Drop it** — adding it
would be a duplicate. Step 2's new `500` branch also stays uncommitted: it is reachable
only via a ~16 000-deep fixture that measures the interpreter's stack rather than this
code, and would go flaky across machines. If you can propose a durable form (e.g.
monkeypatching `json.dumps` in the handler's namespace to raise), say so in your report
as a recommendation.

**Register nothing new.** These go in the existing `tests/test_admin.py` and
`tests/test_parse_guards.py`, both already imported by the aggregator.

**Run and report:** every changed or added slug via `-t` with its `>> <slug>: PASSED`
line (a green exit alone does not prove it ran), the full suite, and all four
planner-authored verification scripts (`...-step1.py` `PASS 22/22`,
`...-admin-page.py` `PASS 3/3`, `...-switch-input.py` `PASS 4/4`,
`...-step6.py` `PASS 14/14`). Report measured counts, not claims.

### Step 9 — the generator-expression shape, and committed coverage for the two Step 8 branches (added 2026-10-26)

<!-- ADDED 2026-10-26 (Phase 6, iteration 3). Step 7's scanner fix and Step 8's two
     new answer paths; the operator chose "fix the three real ones". -->

**Part A — a generator expression does not enclose its body (review
`...-review-2026-10-26-2.json`, Suggestion at `tests/test_parse_guards.py:166`).**
Step 7 made `_scan_source` reject a parse inside a `def`/`async def`/`class`/`lambda`
defined in a `try` body, but a **generator expression** is still treated as enclosing.
It is not: `gen = (json.loads(s) for s in xs)` performs no call at binding time — the
call runs when the generator is consumed, outside the `try`. A **list** comprehension
is correctly treated as enclosing precisely because it *is* eager, so the distinction
is real rather than pedantic. The reviewer measured the false GREEN with the module's
own `_scan_source`: 1 site / **0** failing for the generator form. No live site has the
shape (the live scan is 22 sites / 0 failing), so this is latent — but the scanner
exists to replace per-site review for code written later, which is the argument Step 7
itself used.

Change: add `ast.GeneratorExp` to `SCOPE_BOUNDARIES`, and add **one** row to
`_SCANNER_CASES` — a body consisting of `gen = (json.loads(s) for s in xs)` inside a
`try`, expecting **1 site / 1 failing**. `_SCANNER_CASES` therefore goes from **21
rows to 22**. Set comprehensions and dict comprehensions are eager like list
comprehensions and stay *out* of `SCOPE_BOUNDARIES`; do not add them, and add no case
for them.

The **case-count doc line in `doc/test-catalog.html` is NOT yours to edit** — it is the
planner's lane, and this step originally told the tester to change it, which the Phase 5
mega-audit (iteration 3) filed as the plan's one **High**. Report the final
`_SCANNER_CASES` count and its before/after in your session report; the planner moves
the line.

<!-- CORRECTED 2026-10-26 (Phase 5 mega-audit iteration-3, boundary-checker High
     `documentation-assigned-to-tester-lane`). This paragraph previously read "The
     case-count doc line in `doc/test-catalog.html` that names the row count must move in
     the same change" — a direct instruction to edit a `doc/` file from the tester's
     lane, and a cross-agent assignment conflict with `## Guidance for Planner`, which
     lists the same file under What-to-sync. The tester complied and the edit is correct,
     but the instruction was the defect: this plan's own Step 8 note states the doctrine
     it violated ("the planner wrote it in the revision rather than leaving it to the
     coder, who does not write documentation"). `doc/test-catalog.html` now appears in
     exactly one lane's list. See Issue Log row
     `mega-audit-3-high-documentation-assigned-to-tester-lane`. -->

**Part B — the reload answers 500, and installs nothing, when the candidate cannot be
serialized (Step 8, coder edit 3).** `candidate["tiers"]` is
`_current_config.get("tiers", {})` (`server.py:3780`) — the **in-memory** document, not a
disk re-read — so the seam is module state, and no patching is needed. The planner
measured this fixture: `validate_config` returns `[]` for a tier carrying an unknown
per-tier key whose value is a `set`, and `json.dumps` of that document raises
`TypeError`. Use it:

```python
poisoned = {
    "tiers": {t: {"provider": P, "model": M, "key": "", "poison": {1, 2}}
              for t in ("haiku", "sonnet", "opus")},
    "models": {P: [M]},
}
```

with `srv._current_config` swapped to it and restored in a `finally:`. Drive the reload
handler in-process (`object.__new__(srv.ProxyHandler)`, the pattern the module already
uses for the reload-stale gate) and assert three things: the status is **500**, the body
carries `"the configuration could not be serialized"`, and **`srv._current_config` is
still the poisoned document** (the 500 branch performs no install and no epoch bump —
`is`, not `==`, so a rebuild cannot pass it).

Do **not** build a deep-nesting fixture: it measures the interpreter's stack, not this
code. `TypeError` and `RecursionError` both arrive at the same `except Exception:`, which
is the property the guard is supposed to have; the deep fixture proves less and goes
flaky across machines.

**Part C — the switch re-checks the catalog when the epoch moves (Step 8, coder edit
2).** In-process again. `do_POST` calls `_drain_for_swap()` by global lookup
(`server.py:3673`), which sits **between** the validation snapshot and Phase 3 — so
rebinding `srv._drain_for_swap` puts the test exactly inside the window:

```python
real_drain = srv._drain_for_swap

def moved_drain():
    srv._config_epoch += 1                        # a reload completed here
    srv._current_config["models"] = {P: []}       # ...and its catalog dropped M
    return real_drain()
```

Restore `srv._drain_for_swap` and `srv._config_epoch` / `srv._current_config` in a
`finally:`. Assert the switch answers **400** naming the tier, provider, and model, and
that the persisted `config.json` is untouched. Then the converse, in a second case: bump
the epoch but leave the catalog listing `M` — the switch must answer **200** and persist
the tier, proving the re-check gates on the catalog and not merely on the epoch having
moved. A gate that refuses whenever the epoch moved would fail the converse, and would
be wrong: nothing about a catalog that still lists the model is stale.

If your reading of `server.py` shows `_drain_for_swap` is not reached by global lookup,
say so in your report rather than working around it.

**The `do_GET` `/admin/api/config` 500 branch stays covered by its own filed
deferral** (`defer-issue-config-serialize-500-no-committed-coverage`) — it is not in
this step. Do not extend Step 9 to it without a plan revision.

**Register nothing new.** Parts A–C go in the existing `tests/test_parse_guards.py`
(A) and `tests/test_admin.py` (B, C), both already imported by the aggregator.

**Run and report:** every changed or added slug via `-t` with its `>> <slug>: PASSED`
line, the full suite (record the new total — it must be **450 + the number of tests
B and C add**), and all five planner-authored verification scripts
(`...-step1.py` `PASS 22/22`, `...-admin-page.py` `PASS 3/3`,
`...-switch-input.py` `PASS 4/4`, `...-step6.py` `PASS 14/14`, `...-step8.py`
`PASS 11/11`). Report measured counts, not claims.

## Summary

**Problem A — nine parse guards name too few exceptions, and one names none.**
`json.loads` and `json.load(fp)` fail in unrelated ways: `JSONDecodeError` on
syntax, `UnicodeDecodeError` on bytes that are not valid UTF-8, `RecursionError`
when a document nests deeper than the interpreter recurses. Only the first is
named at these sites, and the other two are not its subclasses — `RecursionError`
is a `RuntimeError`; `UnicodeDecodeError` is a *sibling* of `JSONDecodeError`
under `ValueError`.

The input need not be malformed: `'[' * 20000 + ']' * 20000` is balanced, valid
JSON, and still raises `RecursionError`. The repo already recognises this class —
`test_deep_nested_body_invalid_json` records the identical defect being found and
fixed on the client-body path — and this plan closes the residuals that fix left.
Enumerating names one at a time produced both rounds, so the fix is totality plus
a gate that checks it.

Measured consequences (all reproduced before this plan was written):

| Site | Control | Consequence of an escape |
|------|---------|--------------------------|
| `server.py` `do_POST` parse | local client; localhost + CSRF-gated | **No HTTP response at all** — `socketserver` logs a traceback and closes the socket; the traceback reaches `proxy-stderr.log` raw, bypassing `sanitize_error` |
| `transforms_chat.py` | **upstream provider** | the placeholder-block degradation and its `tool_args_parse_failure` event are lost |
| `transforms_response.py` | **upstream provider** | same |
| `config.py` ×2 | hand-edited `config.json`/`models.json` | a raw traceback instead of the clean `ValueError` the function exists to produce — and `server.main()` catches only `(FileNotFoundError, JSONDecodeError, ValueError)` |
| `cli.py` ×2 | proxy-written state/trace files | `_read_state` returns a traceback instead of `None`; `_parse_trace_entry` aborts the whole prune pass (its call site is wrapped, so `start` survives with a warning) |

**Problem B — the admin switch's write path aborts with a ~2 KB body.**
`disk_config = {"tiers": new_tiers}` is handed to `write_config`, whose
`json.dump(..., indent=2)` catches only `OSError`. Unknown per-tier keys were
neither rejected nor stripped, so one extra key holding a deeply nested value
reached that serializer. Because `indent` moves the encoder onto the pure-Python
path, its ceiling is **994** — while the parser accepts ~16915 — so a ~2 KB body
aborted the request with no response and orphaned `config.json.tmp`. No
persistence and no corruption (the write is atomic and `_current_config` is
updated only after it returns), and it needs a deliberately crafted body: the
legitimate body is depth 4 and the page builds a fixed three-field structure.
Step 3 closes it by construction.

**Problem C — an incomplete admin page acts on the wrong data.** Two distinct
states reach Apply with the page's view incomplete, and in both the press does
the wrong thing:

- *Blank page.* The initial load fails, `renderTiers()` never runs, the selects
  do not exist — but both buttons stay pressable, and the press throws above
  `saveConfig`'s own `try` as an unhandled rejection with no feedback.
- *Missing key list.* `/providers-detail` fails; `loadProviderModes()` swallows
  it by design and leaves `providerKeys = {}`, but the row still renders, so the
  page looks normal. The key selects end up empty and **disabled**, and a
  disabled select still reads `""` — which the server maps to `names[0]`, the
  provider's **first** key, not "unchanged". Every multi-key tier is silently
  re-pointed and persisted while the status line reports success. Seven
  providers on this install carry multiple keys and two are in active routing.
  Neither `reloadConfig` nor `refreshTiersFromServer` re-fetches
  provider-detail, so only a full page reload clears it.

Both are fixed by refusing the press and saying why, which is the discipline the
page already uses on its failed-re-read path.

Note the correction this plan carries: an earlier draft made the *load-failure*
line sticky. That was measured to be harmful — `checkInFlightSwapOnLoad()` runs
after the catch and its no-swap branch calls `refreshTiersFromServer()`, which
sets `config` and re-renders **without painting a status line**, so a transient
failure self-heals and a sticky message would have persisted as a permanent
false error over a recovered page. That change is dropped.

**Alternatives considered and rejected.** (1) A shared total-parse helper module
instead of per-site guards — the client-body sites fixed earlier all use bare
`Exception` in place, and the *gate* supplies the "unrepresentable" property a
helper would have been introduced for. (2) Appending `RecursionError` to each
tuple — leaves the UTF-8 hole open and repeats the enumeration that caused the
defect twice. (3) Allowlisting the unguarded `do_GET` site in the gate —
rejected by the operator; the exemption would rest on an interpreter property
rather than on the code. (4) Disabling both admin buttons — removes the working
Reload recovery path (measured). (5) Having `saveConfig` fall back to the saved
key when the select is unpopulated — papers over the missing key list, leaving
the operator unable to see or change keys while believing their selection is
intact. (6) Rejecting the write-path abort as wont-fix — rejected by the
operator; it is three lines on an endpoint this plan already touches.

**Out of scope.** The `do_POST` broad-outer-try structural question (a request
path that can write no response on an unexpected exception is a design change
wider than one parse). Changing the server's `""`-means-first-key wire semantics
— Step 4 stops the reachable path, but a future client could still send `""`.
Any change to the swap-lockout state machine. Committing a Node-driven
`admin.html` test to the suite. The two remaining open deferrals
(`httpx2-native-sse-transport`, `orphaned-test-state-files`).

## Repo Mode

Public

## Document Overrides

None

## Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| A widened `except Exception` masks an unrelated failure at one of the nine parse sites | A genuine defect becomes invisible there | Every `try` body was read and verified to hold **the parse and nothing else unrelated** — not literally one call, since the four `json.load(fp)` sites enclose their `with open(...)` too. Where a function has several specific clauses (1g, 1h), the total clause is appended LAST so the specific messages still win by ordering. Step 1's `(auto)` check requires the coder to re-confirm per site. |
| The totality gate passes vacuously — a path change, import failure or parse error leaves it scanning nothing | The invariant is unenforced while appearing enforced | The gate asserts a non-zero site count and prints `FAIL n/m` with the observed `m`. Baseline 23 sites. The tester's module carries the same assertion. |
| The gate misses a site reached through `from json import loads` or `import json as j` | A narrow site passes unnoticed | The scan flags bare `loads(...)`/`load(...)` name calls, so an alias import cannot hide a site. `import json as j; j.loads(...)` remains invisible; the gate's docstring states that limit rather than claiming the alias case is the only blind spot. |
| Step 3 rejects a key a legitimate client already sends | The admin page's Apply starts failing with 400 | The page builds exactly `provider`/`model`/`key` per tier (`admin.html:223-229`); no shipped client sends anything else. Step 5's check 3 pins that the page still applies successfully. |
| Step 2 changes a working endpoint's response path (round-trip removed, lock held during the encode) | A regression in `/admin/api/config` | `json.dumps(json.loads(json.dumps(x)))` is byte-identical to `json.dumps(x)`, and the lock was already held for the inner encode, so the hold grows by one call. The new `except` is unreachable for any config this process wrote; Step 4's tests and the full suite cover the endpoint. |

## Proposed Changes

Each step includes verification checks tagged with confidence.
`(auto)` = mechanical, coder self-verifies. `(scripted)` = deterministic
multi-step, coder runs provided script.

1. **Step 1:** Make all nine parse guards total — `server.py` `do_POST` (1a),
   `transforms_chat.py` (1b), `transforms_response.py` (1c), `cli.py`
   `_parse_trace_entry` (1d) and `_read_state` (1e), `keys.py` (1f),
   `config.py` `load_models_document` (1g) and `_load_config_documents` (1h),
   `compat.py` (1i) — each preserving its existing handler, verbatim blocks above
   → coder verify (scripted): `...-step1.py` exits 0 with
   `PASS 22/22 parse sites have a total guard` (pre-change:
   `FAIL 13/23 ... (10 narrow, unguarded or aliased)`, exit 1)
   → coder verify (auto): each touched `try` body holds the parse and nothing else
   unrelated (`with open(...)` at the four `json.load(fp)` sites is the documented
   exception), and re-confirm per site
   → tester verify: `tests/test_parse_guards.py` passes, is listed by
   `--list`, and fails on a deliberately re-narrowed guard

2. **Step 2:** Replace `do_GET`'s `json.loads(json.dumps(...))` round-trip with
   a lock-held single `json.dumps` inside a total guard, sending a plain
   `{"error": ...}` 500 on failure
   → coder verify (scripted): `...-step1.py` no longer lists any `do_GET` site
   and still exits 0
   → coder verify (auto): no `json.loads` remains in `do_GET`; the new handler
   encloses only the `json.dumps` call

3. **Step 3:** Reject per-tier keys other than `provider`/`model`/`key` in the
   switch validation loop
   → coder verify (scripted): `...-switch-input.py` exits 0 (pre-change: exit 1,
   abort reproduced)
   → coder verify (auto): the check follows the dict check and precedes provider
   validation; it returns 400 without mutating `tier_config`
   → tester verify: the full suite's admin tests stay green (a rejected key is
   the only new 400)

4. **Step 4:** Add the two press guards to `saveConfig` — unrendered tier row,
   and a tier whose provider has no key list — both sticky, both before the
   nine-select read
   → coder verify (scripted): `...-admin-page.py` passes checks 1, 2 and 3,
   exit 0 (pre-change: `FAIL 1/3`)
   → coder verify (auto): `reloadConfig` unchanged; no `disabled` /
   `setSwapControlsDisabled` added to the load path
   → tester verify: `tests/test_admin.py` structural pins (a) and (b) pass

5. **Step 5:** Add `tests/test_parse_guards.py` (totality invariant, including
   the bare-alias check, the non-zero site count, and no `ast.unparse`), the two
   `admin.html` structural pins in `tests/test_admin.py`, **and register the new
   module in `tests/test_claude_proxy.py`** (tester-owned)
   → tester verify: the new module passes post-Step-1 and fails on a deliberately
   re-narrowed guard (measure both); `python tests/test_claude_proxy.py --list`
   lists its slugs; the full-suite output carries `>> <slug>: PASSED` for each;
   `tests/test_admin.py` fully green; measured counts reported
6. **Step 6:** Bound the switch's tier **names** by validation (NOT by forbidding
   extra tiers — they are a documented, supported shape) and apply the reload gate's
   catalog rule to `model`, so Apply and Reload stop disagreeing (coder-owned)
   → coder verify: `...-step6.py` `PASS 14/14`; the two companion gates still
   `PASS 4/4` and `PASS 3/3`; `...-step1.py` still `PASS 22/22`
7. **Step 7:** Fix the false-GREEN scope-boundary branch in the Step 5 module's
   `_guard_for`, and add one parameterized switch-input rejection test plus a
   positive extra-tier regression pin in `tests/test_admin.py` — replacing the four
   separate tests an earlier draft specified, one of which duplicated an existing
   test (tester-owned)
   → tester verify: every changed/added slug shown as `>> <slug>: PASSED`;
   the `_guard_for` branch proven reachable by its new synthetic cases; measured
   counts reported
8. **Step 8:** Serialize the reload's success body **before** installing it (answer
   `500` on failure), snapshot the epoch and the catalog together under
   `_config_lock`, and re-check the catalog in Phase 3 when the epoch moved
   (coder-owned)
   → coder verify: `...-step8.py` `PASS 11/11`; the four companion gates unchanged;
   the `(auto)` checks by `try`-enclosure, never by grepping `except`
9. **Step 9:** Add `ast.GeneratorExp` to the scanner's scope boundaries (one case,
   21 → 22 rows), and commit two in-process tests pinning the reload's `500` and the
   epoch-move catalog re-check (tester-owned)
   → tester verify: the generator row proven RED against the pre-Step-9 walker and
   GREEN against the landed one; both new slugs shown as `>> <slug>: PASSED`
10. **Step 10:** The three code Mediums the iteration-3 audit found — `_read_state`
    must not collapse an unreadable state file into an absent one, the reload must
    decide serializability **before** the drain, and the page's press guard must be
    self-sufficient per tier (coder-owned)
    → coder verify: `_UNREADABLE` at one definition and four call sites; the probe
    positioned before `_drain_for_swap()` by source position; no bare `.value`
    dereference left in the guard loop; all five gates and the suite unchanged
11. **Step 11:** Committed coverage for Step 10's three behaviours, including the pin
    that makes the documented "Apply rewrites the tier map" contract fail loudly if it
    is ever changed (tester-owned)
    → tester verify: three new slugs `>> <slug>: PASSED`; suite 452 + 3;
    `test_admin_reload_serialize_failure_500` still green unchanged

<!-- Steps 6 and 7 were appended 2026-10-26. The first version of this plan carried
     them only as headings under Guidance for Coder / Guidance for Tester, so the
     machine-extracted `steps` field (7) disagreed with this list (5) — a
     rule-enforcer Medium in the Phase 5 audit. This list is the canonical one.
     Steps 8–11 were appended in iterations 3 and 4; the iteration-3 mega-audit
     re-filed the SAME Medium because this list had again fallen behind the
     metadata field (9 vs 7). The two are now equal at 11 — if a future revision
     adds a step, it goes here and in `## Plan Metadata.steps` in the same edit.
     That is the whole rule; there is no gate for it. -->

## Guidance for Planner

Documentation tasks you will execute yourself (not the coder):

- **Files to modify:**
  - `./CLAUDE.md`
  - `./README.md`
  - `./doc/architecture.html`
  - `./doc/operations.html`
  - `./doc/provider-modes.html`
  - `./doc/test-catalog.html`
- **`.claude/mega-audit-files.json`:** absent in this repo and this plan adds no
  audit locations — no change.
- **When:** after the coder and tester rounds complete, before `## Final Results`.
- **What to sync:**
  - `./CLAUDE.md` — the Gotchas row ending "guards are verified by
    `try`-**enclosure**, never by grepping `except`". Extend it: guards must be
    **total** (`except Exception`), because `RecursionError` is a `RuntimeError`
    and `UnicodeDecodeError` is a sibling of `JSONDecodeError` rather than a
    subclass; the rule covers `json.load` as well as `json.loads`; and it is now
    enforced by a permanent test. One line, not a new row. **This row currently
    links to `doc/architecture.html#error-envelope`, which contains neither the
    ceiling split nor the enclosure discipline** — see the architecture.html item
    below, which makes that anchor honest rather than retargeting it. The new
    sentence should also cross-reference `doc/provider-modes.html#malformed-args`,
    since the totality rule is what makes that page's placeholder-block
    degradation unconditional.
  - `./doc/architecture.html` — the `error-envelope` section (from line 257)
    must be **given** the content the CLAUDE.md link already promises: the
    decode/encode ceiling split (`json.loads` ≈16915 vs `json.dumps` ≈15505, and
    `indent` collapsing the encoder to ~994), the try-enclosure discipline, and
    the totality requirement naming the two escaping classes. It currently has
    none of these.
  - `./doc/provider-modes.html` — owns two facts this plan touches and is
    currently outside the doc set: `#malformed-args` documents the
    placeholder-block degradation and `tool_args_parse_failure` event that Steps
    1b/1c widen the guard around (its prose describes the degradation as
    unconditional — that is what this plan makes true), and line ~460 is the
    current home of the ceiling split. State which page owns the ceiling fact and
    cross-link from the other.
  - `./doc/operations.html` (admin section) and `./README.md` (admin page
    section) — record the page's behaviour when its fetches fail: the tier area
    stays empty and Apply refuses; a missing key list also makes Apply refuse
    rather than re-point credentials; Reload Providers remains the recovery path
    for a blank page but does **not** re-fetch provider-detail, so an unloaded key
    list needs a full page reload. **Two new response codes this plan introduces
    also belong there** (flagged by the coder, 2026-10-26): `/admin/api/config`
    can now answer `500 {"error": "the configuration could not be serialized"}`
    when a config that decodes cannot be encoded, and `/admin/api/switch` can now
    answer `400` for a tier carrying an unsupported key. The admin section's
    endpoint table carries no status column, so both belong in its prose.
  - `./doc/test-catalog.html` — three things, not one: the catalog **table** row
    for `tests/test_parse_guards.py`; the **per-test inventory** entries (one
    `<li>` per test in the new module, plus one per new `test_admin.py` pin under
    its category), since the page states outright that "a test added without an
    entry here is missing silently"; and a category heading for the new
    static-invariant area, which none of the existing behaviour categories
    describes.
  - `./README.md` Testing section — its enumeration of what the suite covers
    omits the new static-invariant capability.
  - Doc gates after editing: `python scripts/check_doc_anchors.py` and
    `python ~/.claude/scripts/doc_structure_check.py`.
- **Deferral bookkeeping:** when all steps are verified, `/update-plan` takes both
  Issue Log rows to `Resolved`; `/update-and-commit` Step 9.6 deletes the two
  `defer-issue-*.json` reports in the same act that commits this plan — do not
  delete them earlier. Note in the recursion row that it was resolved as a
  **superset** (ten sites, not the three it named).

## History

| Date | Event | Conclusion | Dismissed |
|------|-------|------------|-----------|
| 2026-10-25 | Initial plan | Adopts both deferrals at the operator's choice of scope from the four open ones. 4 steps / 6 source files; mega-audit triggered on the file count. | — |
| 2026-10-25 | Gate calibration (pre-change) | All three scripts run against the pre-change tree, unedited afterwards. `...-step1.py`: exit 1, `FAIL 13/23 parse sites have a total guard (10 narrow, unguarded or aliased)` — the ten named in Issue Log. `...-admin-page.py`: exit 1, `FAIL 1/3` — check 1 red (`TypeError: Cannot read properties of null (reading 'value')`), check 2 red (POSTs `/admin/api/switch` with `sonnet key=""` while the key list was never loaded), check 3 green as the regression pin. `...-switch-input.py`: exit 1, `FAIL 1/4` driven against a REAL spawned server — check A green (a legitimate body still returns 200), check B red (a shallow unknown per-tier key returns 200 and is persisted), check C red (**no HTTP response at all**: `RemoteDisconnected`, `RecursionError` out of `write_config`), check D red (orphaned `config.json.tmp`). | — |
| 2026-10-25 | Mega-audit (iteration 1) | Verdict **Issues found — plan needs revision**: 4 High, 14 Medium, 25 Low across 9 lenses. Report [2026-10-25-guard-totality-and-blank-admin-mega-audit-2026-10-25.json](./tmp/reports/2026-10-25-guard-totality-and-blank-admin-mega-audit-2026-10-25.json). All 4 Highs are ONE issue found independently by four lenses: the new test module was never registered in the hand-maintained aggregator, so the plan's central artifact would never have run. All 14 Mediums verified independently and fixed. Two findings are defects the deferrals never named and were confirmed with the operator as in-scope: the switch write-path abort (now Step 3) and the admin key-data silent re-pointing (now Step 4). The audit also inverted one of the plan's own premises: Step 1b's unreachability claim covered the wrong half of the round-trip (measured — a structure decodes at 16000 depth and then fails to encode), so it was replaced by Step 2. | Low findings, acknowledged and not fixed: `alias-module-form` (matcher misses `import json as j`; now stated as a known limit rather than claimed as the only blind spot); `single-statement-two-calls` (1b's try held two calls; Step 2 removes it); `docstring-vs-idiom` (`test_admin.py`'s admin.html pins serve a live proxy, not the file); `python38-unparse` (script portability — **fixed** in the revised step-1 script); `node-stub-stale-elements` (the DOM stub cannot represent a cleared container; stated as a limit); `rollback-section` (no Rollback section; the deferral deletion is untracked and not `git revert`-able); `deferral-count-arithmetic` (**fixed** in this revision); `nested-try-placement`, `partial-render-exclusion`, `adjacent-narrow-outer-handlers` (transform bodies keep narrow outer handlers), `keys-vimcrypt-unguarded`, `readme-testing-enumeration` (**fixed** via Guidance for Planner), `out-of-scope-do-post-outer-try` (recorded in Out of scope) |
| 2026-10-25 | Revision (audit-driven) | The plan was rewritten to 5 steps / 7 source files to address all 4 Highs and all 14 Mediums: aggregator registration added to Step 5 and `tester_files`; the parse rule widened to `json.load` (four more sites, so the gate covers the failure class rather than one function); Step 1b replaced by Step 2; the sticky load-failure message **dropped** (measured to create a permanent false error over a self-healed page); the `renderTiers` "sole caller" claim corrected; Steps 3 and 4 added for the two operator-confirmed defects; doc targets rewritten against measured reality. Both gates re-calibrated RED after the revision (`FAIL 13/23`; `FAIL 1/3`), and a third gate added for Step 3. No re-audit: 0 High findings remain, below the ≥3 threshold. | — |
| 2026-10-26 | Implementation round (coder) — exit 0, report `build_result: pass` | Report [2026-10-25-guard-totality-and-blank-admin-coder-2026-10-26.json](./tmp/reports/2026-10-25-guard-totality-and-blank-admin-coder-2026-10-26.json). Launched 08:32:37, terminal `[2026-10-26 08:39:22] exit 0`, lock released, fresh report written (08:39:02). Steps 1–3 complete with gates green (`PASS 22/22`, `PASS 4/4`); Step 4 implemented verbatim with its `(auto)` checks passing; Step 5 is tester-owned and not in this round. Diff is **8 files / 100 insertions / 10 deletions**, confined to the plan's seven source files — the planner read every hunk and confirmed each is the plan's supplied block verbatim. | — |
| 2026-10-26 | Spec revision (/update-plan) | Post-coder revision. **Plan Error fixed in the planner's own gate**: `...-admin-page.py` check 1's absolute `setTimeoutCalls() === 0` was unreachable for any compliant implementation (see the Issue Log row) — now press-scoped, re-measured `PASS 3/3` against the implementation, status `Fix Planned` pending a tester report. Step 1's rule reworded: the `try` body holds "the parse and nothing else unrelated" rather than "a single call", since 1e/1g/1h/1i enclose `with open(...)` too (coder-reported). Guidance for Planner gained the two new admin response codes (500 on `/admin/api/config`, 400 on `/admin/api/switch`) and a `#malformed-args` cross-reference. Counters: steps_changed +1. | Coder `out_of_scope` items analyzed and disposed, none left as an issue: (1) **`from e` absent in `keys.load_keys_file`'s ValueError** — analyzed as NOT a defect: the chained exception is still printed (as "During handling of the above exception"), so this is a traceback-style nuance rather than a loss of information, and it is pre-existing at a site this plan only widens. Recorded here rather than filed. (2) **Step 3's 400 echoes client-controlled tier key names** — consistent with the admin surface's existing error text (`"unknown provider: X"`, `"tier 'X': unknown key 'Y'"`), bounded by `ADMIN_BODY_LIMIT`, and passed through `json.dumps`; no change. (3) **The `(auto)` single-call wording** — accepted and fixed in Step 1. (4) **Diff confined to plan files** — confirmed, not an issue. |
| 2026-10-26 | Tester round — exit 0, `overall_result: SUCCESS` | Report [2026-10-25-guard-totality-and-blank-admin-tester-2026-10-26.json](./tmp/reports/2026-10-25-guard-totality-and-blank-admin-tester-2026-10-26.json). Launched 08:43, terminal `[2026-10-26 09:11:13] exit 0`, lock released, report validated (`report_check`: 2 passed, 0 failed). **Step 5 complete**: `tests/test_parse_guards.py` is a new 409-line permanent module with three tests (`parse-guards-totality` — 22 sites, with a non-zero site count asserted so a path change cannot pass vacuously; `parse-guard-scanner-semantics` — 16 synthetic cases pinning every accept/reject branch of the scanner; `parse-guard-gate-python38-portable` — no `ast.unparse`, since `pyproject.toml` declares `>=3.8`), registered in the hand-maintained aggregator, which **closes the mega-audit's four-High finding** (an unregistered module never runs). Two structural pins added to `tests/test_admin.py` in that module's live-proxy style. Suite 443 → **448**, baseline measured before any test edit (443/0/443) so no pre-existing failure existed. **No issues filed.** | — |
| 2026-10-26 | Spec revision (/update-plan) | Post-tester revision. All three Issue Log rows → `Resolved` (`admin-page-gate-sticky-counter-unreachable` on the tester's confirmation, both adopted deferrals on their gates measured green); the recursion row records resolution as a **superset** — ten sites, not the three it named. Resolution block added with the shared evidence and the explicit instruction that the two `defer-issue-*.json` reports stay on disk until `/update-and-commit` Step 9.6 deletes them. `## Immediate Actions` rewritten from tester directives to the remaining planner sequence (reviewer → doc tasks → `## Final Results`). **The planner re-ran all three gates independently before writing these rows** — `PASS 22/22`, `PASS 3/3`, `PASS 4/4`; confirmed 448 slugs registered, all five new slugs present, and `>> <slug>: PASSED` for each. No `Open`/`Fix Planned` remain, so Phase 6 is entered; the loop cap was not approached (1 iteration of steps 6–10). | — |
| 2026-10-26 | Review (Phase 6, reviewer subagent) | Verdict **Issues found — non-blocking**: 0 Critical, 1 Warning, 5 Suggestion. Report [2026-10-25-guard-totality-and-blank-admin-review-2026-10-26.json](./tmp/reports/2026-10-25-guard-totality-and-blank-admin-review-2026-10-26.json) (validated `report_check: 1 passed, 0 failed`). **The review gate passes — no Critical, nothing blocks the commit.** The reviewer re-ran all three gates and the tester's reachability script and reproduced every figure exactly (22/22, 3/3, 4/4; before=10/23, after=0/22, mutant=1/22), then went further and put the previously unmeasured branches RED itself: three Node mutants (non-sticky both guards, deleted row guard, deleted key guard — proving the mid-round check-1 fix is sound rather than relocated), every assertion row of both `test_admin.py` pins, and the python38 portability test. It read all nine widened `try` bodies individually and confirmed each holds only the parse (plus `with open(...)` at the four `json.load(fp)` sites), so no newly-swallowed exception masks unrelated logic. It also proved two otherwise-unverified branches reachable end-to-end: `do_GET`'s new 500 and Step 3's 400 at depth 1000. All 71 mega-audit obligations (33 hunches + 38 areas) were dispositioned as CLOSED / STILL LIVE / OUT OF SCOPE, with nothing closed re-filed and the deck cleared. | **Acknowledged, non-blocking** — carried into `## Final Results` as Known Caveats and presented to the operator for disposition. Warnings/Suggestions, by slug: `reviewer-warning-nonstring-tier-provider-model-aborts-do-post` (**the one Warning — the planner independently reproduced it, and it falsifies this plan's own Step 3 closure claim; see the corrected paragraph at Step 3 and the Issue Log**); `reviewer-suggestion-unbounded-tier-names-persisted` (an extra tier name returns 200 and is persisted verbatim; measured); `reviewer-suggestion-read-state-oserror-misreported-as-absent` (widening `_read_state`'s guard is the one site where a caller-visible outcome changed — an unreadable state file now reads as absent and `stop` exits 0); `reviewer-suggestion-loadconfig-ignores-response-ok` (Step 2's new 500 reaches the page as a JS `TypeError` message rather than the server's text); `reviewer-suggestion-no-committed-coverage-for-step2-step3` (both new server behaviours are covered only by transient `tmp/verification/` scripts — the sharpest of the five, since this plan's own four-High finding was an artifact that never ran); `reviewer-suggestion-parse-guard-gate-top-level-scan-only` (`os.listdir` scans the package top level only, so a future subpackage's parse sites would be silently unscanned — true today by measurement, latent tomorrow). |
| 2026-10-26 | Spec revision — iteration 2 (/update-plan) | **The plan was re-opened rather than finalized**, on the operator's decision after the review. Three reviewer findings became `Open` Issue Log rows and two steps were added to close them. **The planner independently reproduced the Warning before writing anything**: a new gate (`...-reviewer-warning-probe.py`) drove a really spawned server and confirmed `{"provider": {}}` / `{"provider": ["x"]}` → `RemoteDisconnected` and `{"provider": 5}` / `{"model": 5}` / `{"model": null}` → no response within 15 s, with the child's stderr carrying `TypeError: expected string or bytes-like object, got 'dict'`. **Step 6** added (two verbatim blocks in `do_POST`: reject unknown tier names, and `isinstance`-guard `provider`/`model` before `_validate_admin_name`), with its own gate **calibrated RED by measurement** — `FAIL 4/10`, exit 1, and the gate's own pre-H note proves the tier-name hole is a *persistence* defect (`['ghost-tier']` reached `config.json` on disk). **Step 7** added: four permanent tests in `tests/test_admin.py`, closing the coverage gap. Counters: `steps_changed_since_audit` 2 → **4**, which **crosses the Phase 5 entry trigger** — a mega-audit is now due (recorded in `## Audit Accumulation`; not yet run). `## Final Results` marked SUPERSEDED rather than deleted, so its measured iteration-1 evidence stays readable. | **Two deliberate deviations, both flagged rather than silent:** (1) Step 7 specifies **four** permanent tests where the approved scope said "+2", because Step 6 added two behaviours of its own and pinning only Steps 2–3 would leave the newest code uncovered — the precise gap Step 7 exists to close. (2) A committed test for Step 2's `500` branch is **not** specified: it is reachable, but only via a ~16 000-deep fixture that measures the interpreter's stack rather than this code, and would go flaky across machines. **Three Suggestions deliberately left out of scope** and offered to the operator for deferral rather than silently dropped: `reviewer-suggestion-read-state-oserror-misreported-as-absent`, `reviewer-suggestion-loadconfig-ignores-response-ok`, `reviewer-suggestion-parse-guard-gate-top-level-scan-only`. |
| 2026-10-26 | Implementation round 2 (coder) — exit 0, `build_result: pass` | Report [2026-10-25-guard-totality-and-blank-admin-coder-2026-10-26-2.json](./tmp/reports/2026-10-25-guard-totality-and-blank-admin-coder-2026-10-26-2.json). Terminal `[exit 0]`, lock released. **Step 6 landed verbatim** — diff confined to `src/claude_retry_proxy/server.py`, and Steps 1–4 left byte-untouched. The planner read every hunk and confirmed both blocks match the plan's supplied text exactly (`symmetric_difference` on the tier names; `isinstance(provider, str) or not _validate_admin_name(provider)`, and the same for `model`). **All four gates green after the change**: `...-step1.py` `PASS 22/22`; `...-admin-page.py` `PASS 3/3`; `...-switch-input.py` `PASS 4/4`; `...-step6.py` `PASS 10/10` (was `FAIL 4/10` immediately before). Full suite **448 passed, 0 failed**, unchanged — Step 6 adds no tests; Step 7 is the tester's. The coder re-ran the companion gates unedited as instructed and reported measured counts. | **One issue filed** — `step6-gate-pass-summary-literal`, a **Plan Error in the planner's own gate** (not the implementation): the success line was a hardcoded `PASS 8/10` against ten PASS lines. The coder judged it non-blocking and said so explicitly (exit code and verdict correct), which was the right call; the planner had found and fixed it in the same window. **Coder `out_of_scope` items dispositioned, none left open:** (1) the summary literal — accepted, it *is* the filed issue; (2) **two client-visible behaviours this step adds beyond Guidance for Planner's list** — a new `400 {"error": "unknown tier(s): ..."}` and the semantic widening of `invalid provider name`/`invalid model name` to cover non-string values — accepted and actioned: both were written into `doc/operations.html`, `README.md` and this plan's doc ledger, and the coder's point that the endpoint now *answers* rather than aborts is stated there, since "no response at all" was what an API client previously had to handle. Its related suggestion (b), that the admin endpoint table rather than prose should carry the new statuses so the table stays the single inventory, was also adopted. |
| 2026-10-26 | Mega-audit (iteration 2, Phase 5 — post-revision audit) | Trigger met for the first time (`issues_resolved_since_audit` 3, `steps_changed_since_audit` 4 → adding Steps 6–7 crossed it). Run post-implementation over the 74,297-char plan, 7-range chunked pre-read, 12 agents, 0 agent errors. Verdict **Issues found — non-blocking**: **0 High, 17 Medium, 21 Low**. **No High means no re-audit and no escalation** — the plan proceeds. The two most important findings are both against work this plan authored: (1) **Step 6 was wrong** — it forbade extra tier names, which are documented and supported (`doc/configuration.html`; `validate_config` iterates every tier "because resolve_tier's reverse lookup can route to extra tiers"), so it removed a capability instead of validating input, and the correct shape was demonstrated two lines below it; (2) **the `_guard_for` enclosure walker has a false-GREEN branch** — a parse inside a `def` merely *defined in* a try body is reported guarded, measured with the module's own scanner (sites 1 / failures 0), latent today but the gate exists to replace per-site review. Also found: my Step 6 gate never verified *which* package the child imported (vacuous PASS on a snapshot install), and the landed doc text claims Reload Providers "cannot clear either" incomplete state, contradicting the plan's own gate check 3. | 21 Low findings acknowledged, not fixed: `error-hunter` on the four Step-7 slugs not yet existing (correctly self-limited to Low rather than a false High); a plan Rollback/Migration gap; several plan-internal inconsistencies the revision then fixed anyway (`## Plan Metadata` steps 7-vs-5; `compat.py` missing from `coder_files` — so "seven source files" was wrong, it is eight; stale `## Immediate Actions`; the "all done" doc claim vs pending Step 7); an `admin.html` populateKeys/guard-ordering observation; a `_step6` gate spawn/cleanup observation; two `cli._read_state` observations duplicating the earlier Suggestion. |
| 2026-10-26 | Revision (audit-driven) — iteration 3 | All 17 Mediums addressed or formally dispositioned; no Low fixed beyond those that were already in scope. **Step 6 corrected, not extended**: `symmetric_difference` rejection → tier-name validation via `_validate_admin_name` (extra tiers stay reachable), plus a new **edit 3** applying the reload gate's catalog rule to `model` so Apply and Reload stop disagreeing (operator's choice: make Apply validate). **Step 7 rewritten**: it now fixes `_guard_for`'s scope boundary with three synthetic cases, replaces four hand-rolled tests with **one parameterized rejection table** plus a **positive extra-tier regression pin**, and **drops `test_admin_api_config_ok`** as a duplicate of the existing `test_admin_api_config`. `...-step6.py` rebuilt: 14 checks including a **provenance precondition P** (fails if the child imports outside this tree) and a persistence check C2. Bookkeeping fixed: Steps 6–7 added to `## Proposed Changes`; `compat.py` added to the file table and `coder_files`; `## Immediate Actions` rewritten to the live state; the doc ledger's "all done" scoped to Steps 1–6 with Step 7's entries listed as outstanding; the RELOAD-cannot-clear claim corrected in both `doc/operations.html` and `README.md`. Counters reset by the audit run, then `steps_changed` 0 → 2 (Step 6 rewritten, Step 7 rewritten). | **`reviewer-suggestion-read-state-oserror-misreported-as-absent`, `reviewer-suggestion-loadconfig-ignores-response-ok`, `reviewer-suggestion-parse-guard-gate-top-level-scan-only`** — still deferred, now also present as Low audit findings; unchanged from the previous row's disposition. The Low audit findings were not actioned individually: they are acknowledged here in aggregate, and the ones that described real plan defects were fixed anyway (see Conclusion). |
| 2026-10-26 | Implementation round 3 (coder) — exit 0, `build_result: pass` | Report [2026-10-25-guard-totality-and-blank-admin-coder-2026-10-26-3.json](./tmp/reports/2026-10-25-guard-totality-and-blank-admin-coder-2026-10-26-3.json). Terminal `[exit 0]`, lock released. **The correction landed verbatim and nothing else moved**: the 6-line `symmetric_difference` rejection is gone, replaced by the 13-line tier-name validation loop; the 12-line model-catalog block was inserted in the `# Validate providers exist` loop; edit 2 was already present and identical so it was left alone. Diff confined to `src/claude_retry_proxy/server.py`. **All four gates green**: `...-step6.py` **`PASS 14/14`** — including the two that were failing, `F` (off-catalog model → 400) and `C`/`C2` (well-formed extra tier → 200 **and present in `config.json`**) — plus `...-step1.py` `PASS 22/22`, `...-admin-page.py` `PASS 3/3`, `...-switch-input.py` `PASS 4/4`, and the full suite **448 passed, 0 failed**. The gate's final artifact was re-calibrated after its docstring edit: `HEAD` `FAIL 6/14`, working tree `PASS 14/14`. | **Two issues filed, both real and both against the planner's artifacts** — `step6-stale-auto-check-unexpected` (the `(auto)` check still named `unexpected`, a symbol the corrected step no longer creates, so a correct implementation would have failed it) and `step6-docs-describe-removed-tier-name-prohibition` (both committed docs still described the superseded rule that a non-standard tier name is refused — the exact behaviour the audit had this plan reverse). Both fixed in the planner's lane and marked `Fix Planned`. **`out_of_scope` item 2 accepted, and it is a fair criticism:** the coder declined to reproduce the `FAIL 11/14` pre-change figure because the Immediate Actions ordering told it to apply the correction first. That is a plan defect, not a coder shortcut — a step that asks for a before/after comparison must say which order produces which number. The figure is the planner's own measurement, taken before the edit; the gate's docstring and the Step 6 calibration table say so explicitly rather than implying the coder corroborated it. |
| 2026-10-26 | Review (Phase 6, iteration 2 — reviewer subagent) | Verdict **Issues found — non-blocking**: **0 Critical, 1 Warning, 4 Suggestion**. Report [2026-10-25-guard-totality-and-blank-admin-review-2026-10-26-2.json](./tmp/reports/2026-10-25-guard-totality-and-blank-admin-review-2026-10-26-2.json) (validated `report_check: 1 passed, 0 failed`). **The review gate passes — no Critical, nothing blocks the commit**, and the commit gate itself passes. The reviewer re-verified the four gates and the 450-test suite, then **measured every finding rather than asserting it**: `validate_config` accepts a 16000-deep unknown per-tier value, `json.dumps` of the exact reload response shape raises `RecursionError`, the ceilings are ~16915 / ~15505, `str()` survives a 16900-deep list but only a 10900-deep dict, and a really spawned proxy aborts the reload with no response. | **All five findings dispositioned by slug, none dropped silently:** `reviewer-warning-reload-success-body-unguarded-serialize` (**the one Warning — the planner's own gate reproduced it end-to-end before writing Step 8**; now `Fix Planned`); `reviewer-suggestion-catalog-check-unlocked-snapshot` (`Fix Planned`, Step 8); `reviewer-suggestion-generator-expression-not-enclosing` (`Fix Planned`, Step 9); `reviewer-suggestion-switch-key-name-container-echo` (the `format(key)` container echo — measured safe on this interpreter, now filed as `defer-issue-switch-key-name-container-echo`); and the doc paragraph whose "the reason is the same for all four" contradicted "The catalog rule is the exception" three sentences later — **fixed directly in `doc/operations.html`** (a planner-lane doc edit, not a step). |
| 2026-10-26 | Spec revision — iteration 3 (/update-plan) | **Re-opened a second time**, on the operator's decision ("fix the three real ones") after the iteration-2 review. Two steps added. **Step 8** carries three coder edits: serialize the reload's success body **before** installing it and answer 500 on failure (the Warning); snapshot the epoch and the catalog together under `_config_lock`; and re-check the catalog in Phase 3 **when the epoch moved**, answering the same 400 — *not* the reviewer's literal "carry that same snapshot into Phase 3", which would silently revert a reload that completed in the window, and *not* a new `config_switch_stale` 409, which would need a page branch and a doc row for no diagnostic gain. **Step 9** carries three tester parts: `ast.GeneratorExp` + one `_SCANNER_CASES` row (21 → 22); a committed reload-500 test keyed on an injected unserializable candidate rather than a deep fixture; and a committed epoch-move test using `_drain_for_swap` as the seam. A new gate, `...-step8.py` (9 checks), was written and **calibrated RED by measurement**: `FAIL 4/9`, exit 1, with `FAIL B ... NO HTTP RESPONSE (TimeoutError)` — the Warning reproduced against a document measured at 15508 levels deep on CPython 3.14.3. The Step 6 `(auto)` check that pinned the now-replaced `_current_config.get("models")` read was reworded in the same revision. Counters: `steps_changed_since_audit` 4 → **6**; `issues_resolved_since_audit` unchanged at 6 — **the Phase 5 trigger is not re-met** (it needs `issues_resolved ≥ 3` **and** a second counter ≥ 3; the second is met, the first is not since the previous audit). | **The `format(key)` container echo is deferred**, not fixed: the reviewer measured it safe within real margins and no input was found that reproduces an abort on CPython 3.14.3. Filed as `defer-issue-switch-key-name-container-echo` rather than left as prose. **One deliberate asymmetry, stated rather than hidden:** Step 9 commits a test for the reload's new 500 branch but **not** for `do_GET`'s, which stays on its own filed deferral — closing that one would mean deleting a `defer-issue-*.json` from the corpus, which the planner cannot do in this lane, and doing half of it would leave the corpus inconsistent. |
| 2026-10-26 | Implementation round 4 (coder) — exit 0, `build_result: pass` | Report [2026-10-25-guard-totality-and-blank-admin-coder-2026-10-26-4.json](./tmp/reports/2026-10-25-guard-totality-and-blank-admin-coder-2026-10-26-4.json). Terminal `[2026-10-26 20:23:23] exit 0`, lock released. **All three Step 8 edits landed verbatim**: the lock-taken epoch+catalog snapshot at 3632-3641, `catalog = validated_models.get(provider)` at 3653, the Phase 3 epoch-guarded re-check at 3696-3720, and the serialize-before-install reload body at 3892-3921. Diff confined to `src/claude_retry_proxy/server.py`; Steps 1–7 byte-untouched (the planner read every hunk). Regression gates clean: `...-step6.py` `PASS 14/14`, `...-switch-input.py` `PASS 4/4`, `...-admin-page.py` `PASS 3/3`, suite 450 passed / 0 failed. The step self-reported `blocked` rather than `complete` — correctly, and the reason was the planner's, not theirs (see Dismissed). | **Two issues filed against the planner's artifacts, both real, both correct, both fixed by the planner in this revision** — `step8-gate-check-f-contradicts-supplied-edit` (check F tested `_current_config.get("models")` as a substring over the whole validation region, but Step 8 edit 1 puts that exact expression *inside the lock* as the snapshot, so the gate forbade the fix it existed to verify and `FAIL 8/9` was reached by a correct implementation) and `step8-grep-auto-check-matches-unrelated-string` (the plan's `grep -c 'could not be serialized'` = 2 requirement also matches the pre-existing SSE message at 2357; the quoted literal is the honest form). A third observation was accepted too: the step tagged a gate run `(measure)`, which is not one of the coder's two verification tiers, so it is now `(scripted)`. **The `blocked` status is the right call and is recorded as such** — the coder declined to certify a step whose own gate could not pass, instead of quietly editing the gate or reporting success. |
| 2026-10-26 | Mega-audit (iteration 3, Phase 5 — re-audit) | Trigger met (11 resolved / 6 steps changed). Report [2026-10-25-guard-totality-and-blank-admin-mega-audit-2026-10-26-2.json](./tmp/reports/2026-10-25-guard-totality-and-blank-admin-mega-audit-2026-10-26-2.json) (validated `report_check: 18 passed, 0 failed`). Chunked pre-read, 10 ranges, 10 lenses, 21 agents, 0 agent errors, 1.57 M subagent tokens, 433 tool calls. Verdict **Issues found — plan needs revision**: **1 High, 19 Medium, 22 Low**. One High is below the ≥3-High re-audit threshold, so no further audit. **The first attempt failed at the pre-read** — `PLAN_READ_FAILED / LENGTH_MISMATCH` — because the planner measured the plan, launched the audit, and *then* edited the plan; the workflow's exact-count gate caught it (range 1401-1600 returned 37843 against an expected 37635 on all three attempts, every other range matching) instead of auditing a half-stale document. Re-measured on the settled file (117,627) and re-run. That failure is recorded rather than retried silently: it is this plan's own defect class, committed by the planner against the planner. | **Two Mediums fixed before this row was written** (planner lane, measured): `mega-audit-3-medium-step1-gate-drifted-from-permanent-test` — the Step 1 gate's `_guard_for` was a strictly weaker algorithm than `tests/test_parse_guards.py`'s, returning OPPOSITE verdicts on four shapes the auditor built, so the plan's central invariant had two implementations that disagreed; the gate's walk was replaced with the test's, and the two are now proven identical by comparing their **dumped ASTs** (`_guard_for` bodies equal: True; `SCOPE_BOUNDARIES` equal: True), with the live tree still `PASS 22/22`. And `mega-audit-3-medium-docs-maintain-an-exact-count` — `doc/test-catalog.html` restated the `_SCANNER_CASES` row count, which this repo's own doctrine forbids (documentation must not maintain exact counts); the sentence now names the rule and the measure-on-demand command instead. The **High** is fixed as plan text: Step 9 Part A no longer tells the tester to edit `doc/`, a lane it does not own. **Sixteen Mediums and all 22 Lows remain open** and are itemized in the Issue Log; several need a coder round (the `saveConfig` extra-tier deletion, the partial-render guard, the `_read_state` widening) and are therefore not planner-fixable. |
| 2026-10-26 | Tester round 3 — exit 0, `overall_result: SUCCESS` | Report [2026-10-25-guard-totality-and-blank-admin-tester-2026-10-26-3.json](./tmp/reports/2026-10-25-guard-totality-and-blank-admin-tester-2026-10-26-3.json) (validated `report_check`). Lock released, terminal `[2026-10-26 20:59:20] exit 0`. **Step 9 complete, all three parts.** A — `ast.GeneratorExp` joined `SCOPE_BOUNDARIES` and `_SCANNER_CASES` grew 21 → 22; the live scan is unchanged at 22 sites / 0 failing, so the widening alters no verdict on the tree. B — `test_admin_reload_serialize_failure_500` (4 assertions: status, message, `_current_config **is**` the poisoned document, no epoch bump). C — `test_admin_switch_rechecks_catalog_after_epoch_move` (7 assertions across both directions, including that case 2 persists the extra tier and carries the live catalog forward). Suite **450 → 452 passed, 0 failed**, baseline measured before any edit. **All five planner gates green unedited**: `22/22`, `3/3`, `4/4`, `14/14`, `11/11`. Both doc gates pass after the round's `doc/test-catalog.html` edit (237 anchors; 9 files). **No issues filed — nothing failed.** | **Reachability measured, not asserted** — the round built three mutants and showed each new assertion's failing branch can actually fire: the module's own `_scan_source` with the pre-Step-9 four kinds reports the generator row GUARDED (1/0); a shadowed package that serializes AFTER installing turns test B RED (`Test crashed: Object of type set is not JSON serializable` — the pre-Step-8 no-response escape); deleting the Phase-3 re-check turns case 1 RED (200 instead of 400); replacing the catalog predicate with `if True:` turns case 2 RED (400 instead of 200), which is what proves the check gates on the catalog and not on the epoch alone. **One method deviation, reported rather than silent and accepted:** the full suite was run as three contiguous slices of the declared runner because a single invocation exceeds the 10-minute foreground cap; the union is every slug the runner lists (151/151/150) with none filtered or substituted. **The planner re-ran the whole suite afterwards as ONE invocation** — `Results: 452 passed, 0 failed, 452 total`, exit 0 — which reproduces the sliced union exactly and so validates the workaround as verdict-neutral rather than merely plausible. **Three `out_of_scope` items carried forward, none dismissed:** `tests/test_admin.py` is now past 4,000 lines against the refactor-split test threshold of 1,500 — a standing split candidate and an architecture decision, not a test decision; `ast.ClassDef` stays in `SCOPE_BOUNDARIES` although a class body executes eagerly (conservative, pinned, and changing it would delete a pinned case); and the PID-12504 orphan proxy is a **running process** heartbeating into a 2026-10-15 test-state file, which is worth knowing when `defer-issue-orphaned-test-state-files` is triaged. |
| 2026-10-26 | Tester round 2 — exit 0, `overall_result: SUCCESS` | Report [2026-10-25-guard-totality-and-blank-admin-tester-2026-10-26-2.json](./tmp/reports/2026-10-25-guard-totality-and-blank-admin-tester-2026-10-26-2.json). **A first attempt died at startup** — the launcher was killed by the harness's 30-minute background cap before the round got going (log stalled at 12:39, no report); it was **not** a work failure. The lock was left stale and was **not** deleted (the planner never deletes a lock); the launcher reclaimed it on restart, and the round was re-launched with a 90-minute budget. **Step 7 complete, both parts.** Part 1: `_guard_for` stops at a scope boundary and `_SCANNER_CASES` grew 16 → **21**. Part 2: `test_admin_switch_input_rejections` (6 rejection rules over 9 bodies, asserting per body that the response **arrives**, names the rejection, and leaves the persisted mapping untouched) plus `test_admin_switch_extra_tier_persisted` (the positive half — a well-formed extra tier returns 200 and reaches `config.json`). Suite **448 → 450**, baseline measured before any edit. All four planner gates ran **unedited** and green (`22/22`, `3/3`, `4/4`, `14/14`). Reachability **measured, not claimed**: a pre-fix `_guard_for` embedded as a literal reports all five boundary shapes as GUARDED, the landed walker reports them failing, and a PYTHONPATH-shadowed mutant with Step 6's checks reverted answers `0/200/200` where the tree answers `400/400/400`. | **Two deliberate deviations, both reported rather than silent, both accepted:** (a) `_SCANNER_CASES` has **21** rows, not the 19 the plan's "three synthetic shapes" implies, and `_guard_for` tests the whole try-to-call path rather than only the try body's direct child — because **the literal direct-child rule cannot reach `ast.Lambda` at all** (a lambda is never a try body's direct child) and leaves the identical false-GREEN for a `def` behind an `if`. That is a strict superset of the prescribed rule, measured to change no verdict on the live tree (22 sites / 0 failing before and after). The planner's prescription was incomplete; the tester's is the correct one. (b) two admin slugs added to `test_admin.py`'s `ALL_TESTS` — expected, and the module is already aggregator-registered. Nothing removed, skipped or promoted. |
| 2026-10-27 | Implementation round 5 (coder) — exit 0, `build_result: pass` | Report [2026-10-25-guard-totality-and-blank-admin-coder-2026-10-26-5.json](./tmp/reports/2026-10-25-guard-totality-and-blank-admin-coder-2026-10-26-5.json). Terminal `[2026-10-27 00:11:53] exit 0`, lock released. **All of Step 10 landed verbatim**: `_UNREADABLE` with four call-site branches in `cli.py`, the pre-drain serialize probe at `server.py:3869` ahead of `drain = _drain_for_swap()` at 3878 (post-drain guard unchanged at 3920), the null-checked select handle in `admin.html`, and edit D confirmed as doc-only with `saveConfig`'s tier list untouched. Diff confined to `src/` plus one suite-wrapper script. The round self-reported **blocked**, not complete — again correctly, and again because of this plan's own text (see Dismissed). | **Four issues filed, all four against the planner's artifacts, all four real, all four fixed.** `step10-probe-breaks-step8-check-h` — edit B legitimately creates a THIRD `"could not be serialized"` site while Step 8's check H pinned exactly 2, so a faithful implementation turned an earlier gate RED and made Step 10's own "expect no change" unsatisfiable; check H and the plan now read 3 and name all three sites. `step10-unreadable-count-auto-check` — the `grep -c "_UNREADABLE"` pin said 6 while its own parenthetical enumerated seven distinct lines; corrected to the measured 7. `immediate-actions-stale-after-iteration-3-audit` — the documented entry point still described the pre-audit sequence and named no coder work; rewritten. `step10-el-handle-breaks-admin-html-row-guard-pin` — edit C's null-checked handle broke a tester-owned regex that matched only the direct `.value` form, so the ordering test went **green while anchoring on a different position**; deferred to Step 11 Part D with a required mutant proof. |
| 2026-10-27 | Tester round 6 — exit 0, `overall_result: SUCCESS` | Report [2026-10-25-guard-totality-and-blank-admin-tester-2026-10-27.json](./tmp/reports/2026-10-25-guard-totality-and-blank-admin-tester-2026-10-27.json). Terminal exit 0, lock released. **Step 11 complete, all four parts.** A — `_read_state`'s three-way outcome pinned **by identity** (`is`, not truthiness — the defect was precisely that a falsy sentinel could not be told from `None`), and all **four** call sites driven through `main()`, two more than the plan named, each exiting 1 with the distinct diagnostic. B — the reload's **ordering** pinned, not just its 500: a counting `_drain_for_swap` stand-in observes **zero** invocations, with a positive control in the same test showing it observes exactly one press when the candidate serializes, so the zero is a measurement rather than an artifact of a binding that never fires. C — the documented Apply-rewrites-the-tier-map contract pinned, with a docstring that tells any future changer to move `doc/operations.html` rather than the assertion. D — the ordering matcher repaired to anchor on the `getElementById` call rather than one `.value` spelling, with the failing branch proven reachable (guard deleted → RED; guard moved late → the ordering row RED). Suite **452 → 455** (453 passed, 2 Windows-gated). | **The round exceeded the instruction in two places, both better than what was asked:** it drove all four `_read_state` call sites where the plan named two, and it added the positive control that turns Part B's zero into a measurement. No issues filed. No test removed, skipped or promoted. |

## Plan Metadata

```json
{
  "plan_id": "2026-10-25-guard-totality-and-blank-admin",
  "steps": [
    "Step 1: Make all nine parse guards total",
    "Step 2: Replace do_GET's round-trip with a lock-held total-guarded serialize",
    "Step 3: Reject per-tier keys other than provider/model/key in the switch validation",
    "Step 4: Add the two press guards to saveConfig",
    "Step 5: Add tests/test_parse_guards.py, the admin.html pins, and register the module",
    "Step 6: Bound the switch's tier names by validation (NOT by forbidding extra tiers — they are a documented, supported shape) and apply the reload gate's catalog rule to model, so Apply and Reload stop disagreeing",
    "Step 7: Fix the false-GREEN scope-boundary branch in the Step 5 module's _guard_for, and add one parameterized switch-input rejection test plus a positive extra-tier regression pin in tests/test_admin.py",
    "Step 8: Serialize the reload's success body before installing it (answer 500 on failure), snapshot the epoch and the catalog together under _config_lock, and re-check the catalog in Phase 3 when the epoch moved",
    "Step 9: Add ast.GeneratorExp to the scanner's scope boundaries (one case, 21 -> 22 rows), and commit two in-process tests pinning the reload 500 and the epoch-move catalog re-check",
    "Step 10: The three code Mediums from the iteration-3 mega-audit — _read_state must distinguish unreadable from absent, the reload must decide serializability before the drain, and the page's press guard must be self-sufficient per tier",
    "Step 11: Committed coverage for Step 10's three behaviours, including the pin that makes the documented Apply-rewrites-the-tier-map contract fail loudly if it changes"
  ],
  "coder_files": [
    "src/claude_retry_proxy/server.py",
    "src/claude_retry_proxy/transforms_chat.py",
    "src/claude_retry_proxy/transforms_response.py",
    "src/claude_retry_proxy/cli.py",
    "src/claude_retry_proxy/keys.py",
    "src/claude_retry_proxy/config.py",
    "src/claude_retry_proxy/compat.py",
    "src/claude_retry_proxy/admin.html"
  ],
  "tester_files": [
    "tests/test_parse_guards.py",
    "tests/test_admin.py",
    "tests/test_claude_proxy.py"
  ],
  "doc_files": [
    "./CLAUDE.md",
    "./README.md",
    "./doc/architecture.html",
    "./doc/operations.html",
    "./doc/provider-modes.html",
    "./doc/test-catalog.html"
  ],
  "verification_scripts": [
    "./tmp/verification/2026-10-25-guard-totality-and-blank-admin-step1.py",
    "./tmp/verification/2026-10-25-guard-totality-and-blank-admin-admin-page.py",
    "./tmp/verification/2026-10-25-guard-totality-and-blank-admin-switch-input.py",
    "./tmp/verification/2026-10-25-guard-totality-and-blank-admin-step6.py",
    "./tmp/verification/2026-10-25-guard-totality-and-blank-admin-step8.py",
    "./tmp/verification/2026-10-25-guard-totality-and-blank-admin-reviewer-warning-probe.py"
  ],
  "repo_mode": "Public",
  "document_overrides": []
}
```

## Audit Accumulation

*Counters reset when mega-audit runs. Used by Phase 5 entry trigger.*

| Counter | Value | Last Updated |
|---------|-------|--------------|
| issues_resolved_since_audit | 0 | 2026-10-26 |
| steps_changed_since_audit | 0 | 2026-10-26 |
| files_changed_since_audit | 0 | 2026-10-26 |

**Reset 2026-10-26: the Phase 5 mega-audit RAN (iteration 3).** The counters were
11 / 6 / 0 and were cleared immediately after the report was read, per the rule. The
verdict was "plan needs revision" on **1 High** — below the ≥3-High re-audit threshold,
so no further audit is owed. Counters will accumulate again from any revision that
follows this one.

**Phase 5 entry trigger re-evaluated 2026-10-26 after the tester round: NOT met.**
*Snapshot of the counters at that moment, superseded by the re-evaluation above —
`steps_changed_since_audit` has since moved from 2 to 6; the verdict did not change.*
`issues_resolved_since_audit` was 6 (≥ 3 ✓), but the second conjunct requires
`steps_changed_since_audit ≥ 3` **or** `files_changed_since_audit ≥ 3`, and it read
2 and 0 — Step 6 and Step 7 both have corrected text, and no source file was added to
or removed from the coder table. So the conjunction was false and **no re-audit ran**
before that Phase 6 review. The 6 resolved issues are the six rows in the Issue Log
above; all resolved after the audit ran, so none of them is a counter the audit already
discharged.

**Reset 2026-10-26: the Phase 5 mega-audit RAN.** The counters were 3 / 4 / 0 and were
cleared immediately after the report was read, before fixes were applied, per the rule.
They had accumulated 2 by the end of iteration 2 (Step 6 rewritten, Step 7 rewritten)
and 6 by the end of iteration 3 (Steps 6, 7, 8 and 9 — two of them new steps, two of
them rewritten).
`files_changed_since_audit` stays 0 — no source file was added to or removed from the
coder table (`compat.py` was *added to the table*, correcting an omission; it was always
in the diff).

**Phase 5 entry trigger: MET and discharged 2026-10-26.** The trigger is
`issues_resolved_since_audit ≥ 3` **AND** (`steps_changed_since_audit ≥ 3` **OR**
`files_changed_since_audit ≥ 3`). It read 3 / 4 / 0 and the audit ran. It did not hold
afterwards (0 / 2 / 0), and after the iteration-3 revision it reads 0 / 6 / 0 — still
false, because no issue has been resolved since the audit.

## Audit: Phase 5 disposition

**Run 2026-10-26.** Report
[2026-10-25-guard-totality-and-blank-admin-mega-audit-2026-10-26.json](./tmp/reports/2026-10-25-guard-totality-and-blank-admin-mega-audit-2026-10-26.json)
(validated `report_check: 1 passed, 0 failed`). Post-implementation, 12 agents,
1.33 M subagent tokens, 313 tool calls, 0 agent errors.

| | |
|---|---|
| Verdict | **Issues found — non-blocking** |
| Findings | **0 High**, 17 Medium, 21 Low (38 unique after dedupe across 10 lenses) |
| Re-audit | **Not triggered** — the re-iteration threshold is ≥3 High; there are none |
| Escalation | **Not required** — that trigger is also ≥3 High |
| Fix requirement | All 17 Mediums addressed in this revision (see the History row) |

**The audit's value here was concentrated in two findings against the plan's own newest
work**, which is the reason the Phase 5 lens exists: it caught Step 6 removing a
documented feature rather than validating input, and it caught a false-GREEN branch in
the enclosure walker that the plan's central permanent test is built on. Both were
measured by the lens, not asserted, and both are corrected above.

## Documentation

Reconciled in Phase 6 step 5 (2026-10-26). Both doc gates pass:
`python scripts/check_doc_anchors.py` → `PASS`, 233 anchors resolved, no secret shapes;
`python ~/.claude/scripts/doc_structure_check.py` → `PASS`, 9 files, no violations.

Declared surface **for Steps 1–6** — all done. (Step 7's entries are still outstanding;
see the end of this section.)

<!-- UPDATED 2026-10-26: this heading read "Declared surface, all done" unqualified,
     which the Phase 5 audit correctly read as claiming the whole doc surface was
     complete while Step 7 — still pending — adds tests that doc/test-catalog.html
     requires an entry for. -->

| File | What changed |
|------|--------------|
| `./CLAUDE.md` | The guard-enclosure Gotchas row extended **in place, one row** (not a new row) with totality, the `RecursionError` /`UnicodeDecodeError` relationship, the `json.load` scope, and the permanent test. Its link was **refined** from `#error-envelope` to the new `#json-ceilings` subsection *inside the same section*, so the promised content now exists where the link points — the plan asked for the anchor to be made honest rather than retargeted, and a subsection of the same section satisfies that while landing the reader on the right paragraph. |
| `./doc/architecture.html` | New `<h3 id="json-ceilings">` inside the `error-envelope` section — **the content that section was linked for and did not have**: the three-way ceiling table, the measure-on-demand command, the three unrelated failure classes, the totality rule, the `try`-enclosure discipline, and an explicit statement that totality is a shape check whose narrowness half stays a review obligation. |
| `./doc/provider-modes.html` | **Ceiling ownership made explicit**: the page no longer restates the numbers and instead cross-links `architecture.html#json-ceilings` as the owner, keeping only its local consequence (the SSE `response_frame_encode_failure` frame). `#malformed-args` gained the paragraph that totality is what makes its placeholder degradation unconditional — verified against `transforms_chat.py:583-587` before writing, not assumed. |
| `./doc/operations.html` | Admin section: the unknown-per-tier-key `400` with its real rationale; a new `<h3 id="admin-incomplete-view">` covering both incomplete-data states, what the operator sees, what Apply does, and why the refusal is sticky; the `/admin/api/config` `500` added to the endpoint table. |
| `./README.md` | Admin section: the two incomplete-data refusals and the two new response codes for API users. Testing section: the static-invariant capability. |
| `./doc/test-catalog.html` | Catalog table row for `tests/test_parse_guards.py`; the `test_admin.py` row extended; **Category 12 — Static Source Invariants** (new heading, placed after Category 11 so the numbering stays ordered) with one `<li>` per new test and a "what this category does not cover" note; two `<li>` entries for the `test_admin.py` pins under Category 8; inventory marker dated. |

**Two additions beyond the declared surface, both closing gaps the round exposed:**

1. **`doc/test-catalog.html` "Adding a test" was actively misleading.** It said a new
   test is picked up by "that module's `ALL_TESTS` list — the aggregator picks it up
   from there", which is true only for an *already-registered* module. That is precisely
   the trap the mega-audit's four-High finding fell into (a module that is never
   imported never runs, and the suite stays green). Step 3 of that list now states the
   registration requirement and the two-command proof (`--list` for the slug,
   `-t <slug>` for `>> <slug>: PASSED`), including that a green exit code is exactly
   what an unregistered module produces.
2. **Last-updated stamps** on all four edited pages (header + footer) moved to
   2026-10-26. `doc/test-catalog.html`'s header and footer had already disagreed
   (2026-10-22 vs 2026-10-21) before this plan touched it.

**Added 2026-10-26 in iteration 2, for Step 6** (from the coder's `doc_suggestions`,
both actioned):

- `./doc/operations.html` and `./README.md` — the switch endpoint's rejections read as
  one group of **four**: a tier name that is not a safe-charset string, an unsupported
  per-tier key, a non-string provider/model, and a model not in the provider's catalog.
  The first three are stated with the property that unites them — each was, before it
  was checked, a body that made the endpoint **answer nothing at all**, so a client had
  to treat a dead connection as a validation error — and the fourth is called out as the
  different kind of fix (a disagreement with Reload, not an abort). The `invalid
  provider name` / `invalid model name` messages are documented as now covering
  non-string values.

  <!-- CORRECTED 2026-10-26 (coder-filed
       `step6-docs-describe-removed-tier-name-prohibition`). This entry, and the docs
       themselves, still described the SUPERSEDED rule — "a tier name other than the
       three standard ones is refused" — which the Phase 5 audit's correction reversed.
       Both files now state the opposite property explicitly: the check validates the
       NAME and does not restrict WHICH tiers exist, with a cross-reference to
       doc/configuration.html, which was already correct and is the reference the other
       two are reconciled against. Leaving committed docs describing a prohibition the
       code does not implement would have been the worst outcome of this correction. -->
- `./doc/operations.html`'s admin endpoint table — the coder's suggestion (b) was
  adopted: the `/admin/api/switch` row now carries its `400` conditions, so the table
  remains the single inventory of what the admin API can answer rather than leaving the
  Step 2 `500` and the Step 6 `400`s in prose only.
- **A stale overclaim was found and fixed in the docs while doing this**, not just in
  the plan: `doc/operations.html` still carried the *same* false "every surviving value
  is a short string bound by the name validation" sentence that Step 3's paragraph was
  corrected for. It happens to be **true after Step 6** and was false before, so it was
  rewritten to say what actually made it true rather than left to be right by accident.

**Deliberate removal — OPERATOR-APPROVED 2026-10-26.** The `CLAUDE.md` row's literal
`≈16,920` / `≈15,501` figures were replaced by a persistent description plus the
measure-on-demand command, because the global doc rule forbids maintaining exact figures
as fact. Both were interpreter-dependent snapshots; this run measured ≈16,915 / ≈15,505
on the same interpreter, which is the point — they drift. The mechanism is unchanged and
the numbers remain reproducible on demand.

<!-- APPROVAL RECORD. ~/.claude/CLAUDE.md's CLAUDE.md-Maintenance rule requires that
     redundant or outdated content be flagged AND that the update "Wait for explicit
     approval before removing it". The Phase 5 mega-audit filed a rule-enforcer Medium
     because the plan recorded only its own rationale, not an approval — flagging in a
     plan is not the approval the rule requires. The operator was asked directly and
     chose "Approve the removal" on 2026-10-26. That is the approval; this comment is
     its record. No further sign-off is outstanding for this removal. -->

**Step 7's doc work: DONE 2026-10-26.** The declared-surface table above covers Steps
1–6; Step 7 added the following, since `doc/test-catalog.html` states outright that "a
test added without an entry here is missing silently":

- Category 8 — one `<li>` for `test_admin_switch_input_rejections` (the parameterized
  six-rule / nine-body table, and *why* it asserts the response arrives) and one for
  `test_admin_switch_extra_tier_persisted` (the positive half, including why it has its
  own slug);
- Category 12 — `test_parse_guard_scanner_semantics`'s entry corrected from "16
  synthetic cases" to **21**, with the five scope-boundary shapes named and the
  false-GREEN they exist to catch explained;
- the `tests/test_admin.py` catalog-table row extended to name the switch-input
  rejection coverage.

Doc gates re-run after these edits: `check_doc_anchors.py` **PASS** (235 anchors),
`doc_structure_check.py` **PASS** (9 files). Note the counts are a point-in-time
measurement, not a maintained figure.

**Iteration 3's doc work (planner lane, applied with the revision).**

- `./doc/operations.html` — the `/admin/api/reload` endpoint-table row now carries the
  `500` for a configuration that cannot be serialized, states that the previous catalog
  stays in effect, and cross-links `architecture.html#json-ceilings`. This is Step 8
  coder edit 3's user-visible contract; the planner wrote it in the revision rather than
  leaving it to the coder, who does not write documentation.
- `./doc/operations.html` — the admin paragraph's "the reason is the same for all
  **four**" was corrected to name the first three, resolving the self-contradiction the
  second review found three sentences before "The catalog rule is the exception to that
  history".

**Step 9's doc work: DONE 2026-10-26 (tester round).** `doc/test-catalog.html`'s
Category 12 entry for `test_parse_guard_scanner_semantics` moved from "21 synthetic
cases" to **22** and now names the generator-expression boundary together with the
eager/lazy distinction that decides membership; Category 8 gained one `<li>` each for
`test_admin_reload_serialize_failure_500` and
`test_admin_switch_rechecks_catalog_after_epoch_move`; and the `tests/test_admin.py`
inventory row names both new behaviours, per the page's own rule that a test added
without an entry here is missing silently. The round verified
`doc/operations.html`'s reload-500 row against the code rather than assuming it.

Doc gates re-run after the iteration-3 edits, measured rather than assumed:
`check_doc_anchors.py` **PASS** (237 anchors — two more than the Step 7 figure above,
from the new `#json-ceilings` cross-reference and the reload row), no secret shapes;
`doc_structure_check.py` **PASS** (9 files, no violations).

## Final Results

**Completion date:** 2026-10-27
**Status:** COMPLETE — 11 steps, three Phase 6 reviews, two Phase 5 mega-audits.

<!-- REWRITTEN 2026-10-27. The iteration-1 record it replaces is preserved verbatim
     under "Superseded iteration-1 record" at the end of this section, because every
     figure in it was measured and it documents the plan's first five steps. -->

### What was built

A multi-provider retry gateway gained **total JSON guards** and an **admin surface that
answers**. Concretely:

1. **Nine parse sites made total.** Every `json.loads` / `json.load` in the package now
   sits in a `try` whose handler catches `Exception`, because the three failure classes
   are not related by inheritance — `RecursionError` is a `RuntimeError`, and
   `UnicodeDecodeError` is a *sibling* of `JSONDecodeError`, not a subclass — so naming
   types one at a time lets two of the three escape and abort the handler with no HTTP
   response. Enforced permanently by `tests/test_parse_guards.py`, which scans the
   package and reports per-site evidence.
2. **`do_GET`'s `/admin/api/config` serializes inside the lock** and answers `500`
   instead of aborting; the old `json.loads(json.dumps(...))` round-trip is gone.
3. **The switch validation rejects what it cannot judge**: unknown per-tier keys, tier
   names outside the safe charset (**validated, not restricted** — extra tiers stay a
   supported shape), non-string `provider`/`model`, and models absent from the catalog,
   which is the same rule Reload already applied.
4. **The admin page refuses on an incomplete view** rather than silently re-pointing
   every multi-key tier to its first credential, and its press guards are per-tier
   self-sufficient.
5. **The reload's success body is serialized before it is installed** — and, after the
   second review, **before the drain** — so a press that can never succeed disturbs
   nothing and answers `500` truthfully with the previous mapping still in force.
6. **The switch re-checks the live catalog when the epoch moved** between its validation
   snapshot and Phase 3, closing the Apply/Reload disagreement rather than narrowing it.
7. **`_read_state` distinguishes unreadable from absent**, so `stop` can no longer print
   "not running" and exit 0 over a state file whose proxy is alive.

### Verification (all measured, none asserted)

| Gate | Result |
|---|---|
| Full suite | **455 slugs, 0 failures.** Tester round: `453 passed, 0 failed, 2 skipped` (the two platform-gated tests). Planner's independent single invocation: `455 passed, 0 failed, 455 total`. Both measurements are recorded as reported; the difference is in how the two invocations classify the gated pair, not in the outcome. |
| `...-step1.py` | `PASS 22/22` parse sites have a total guard |
| `...-admin-page.py` | `PASS 3/3` |
| `...-switch-input.py` | `PASS 4/4` |
| `...-step6.py` | `PASS 14/14` |
| `...-step8.py` | `PASS 11/11` |
| `scripts/check_doc_anchors.py` | `PASS`, 237 anchors, no secret shapes |
| `~/.claude/scripts/doc_structure_check.py` | `PASS`, 9 files, no violations |

Reachability was measured rather than claimed at every step: mutant runs turned each new
assertion RED (the generator row against the pre-Step-9 walker; a post-install serialize
turning the reload test into a crash; the Phase-3 re-check deleted → 200 instead of 400;
a catalog-blind epoch refusal → 400 instead of 200; a deleted or late-moved page guard).

### Issues resolved

Every Issue Log row is `Resolved` except three `Deferred` (below). The plan closed
findings from **three Phase 6 reviews** and **two Phase 5 mega-audits**, including:

- the first review's Warning (non-string `provider`/`model` aborted `do_POST`) and its
  sharpest Suggestion (the plan's own new behaviours had no committed coverage);
- the second review's Warning (the reload's success body was the last unguarded
  serialize on the admin surface) and its catalog-lock Suggestion;
- the third mega-audit's **High** — a doc edit assigned to the tester's lane — and its
  three code Mediums (extra-tier deletion, partial-render guard, `_read_state`);
- and, repeatedly, **the plan's own verification artifacts**: four coder-filed defects
  against gates and plan text, each of which would have made a correct implementation
  fail or a broken one pass.

### Known caveats

- Two of 455 tests are Windows-gated by design and were not exercised here.
- The admin page's JavaScript is never executed by the committed suite; its behavioural
  contract lives in the calibrated `tmp/verification/` scripts, which the post-commit
  sweep retires. There is deliberately no Node dependency.
- `tests/test_admin.py` is past 4,000 lines against the refactor-split test threshold of
  1,500 — a standing split candidate, deliberately not taken mid-plan.

### Deferred issues

Enumerated here so no deferral is merely absent. Each is a standalone
`./tmp/reports/defer-issue-*.json` and carries no plan row.

1. **`defer-issue-config-serialize-500-no-committed-coverage`** — the `do_GET`
   `/admin/api/config` 500 branch is covered only by transient verification scripts. Its
   sibling (the reload's 500) **is** committed, via
   `test_admin_reload_serialize_failure_500`. The asymmetry is deliberate: the reload's
   refusal was introduced by this plan and shipped with a test in the same round, while
   converting the `do_GET` gap would have meant deleting an already-filed deferral — a
   corpus action outside the planner's lane in this session.
2. **`defer-issue-switch-key-name-container-echo`** — `"invalid key name: {}".format(key)`
   stringifies a client-supplied container into a response. Measured safe on CPython
   3.14.3 within real decode limits (a 16000-deep list answers `400`, then a legitimate
   switch `200`), but the safety is an interpreter property, not a code property.
3. **`defer-issue-admin-page-loadconfig-ignores-response-ok`** — the page's `loadConfig`
   ignores `resp.ok`, so the `GET /admin/api/config` 500 reaches the operator as a JS
   `TypeError` rather than the server's message.
4. **`defer-issue-parse-guard-gate-top-level-scope`** — the totality gate enumerates
   sites with a non-recursive `os.listdir`; complete today because the package is flat,
   silently incomplete the day a subpackage appears.

### Files changed

Source: `server.py`, `cli.py`, `config.py`, `keys.py`, `compat.py`, `admin.html`,
`transforms_chat.py`, `transforms_response.py`.
Tests: `tests/test_parse_guards.py` (new), `tests/test_admin.py`, `tests/test_claude_proxy.py`.
Docs: `CLAUDE.md`, `README.md`, `doc/architecture.html`, `doc/operations.html`,
`doc/provider-modes.html`, `doc/test-catalog.html`.

**Superseded iteration-1 record**

The original `## Final Results` is preserved below verbatim: its figures were measured
and remain accurate for Steps 1–5.

### Superseded iteration-1 record (verbatim)

> **SUPERSEDED 2026-10-26 — the plan was re-opened for iteration 2.** This section
> records the state at the end of iteration 1 (Steps 1–5 landed, verified, docs
> reconciled, review passed with 0 Critical). The operator then chose to address the
> reviewer's one Warning plus two adjacent findings **inside this plan** rather than
> deferring them, so Steps 6 and 7 were added and the plan returned to Phase 5. The
> evidence below remains accurate for Steps 1–5 and every figure in it was measured;
> **it is not yet the final record.** It will be rewritten once Steps 6–7 land, the
> Phase 5 audit runs, and the Phase 6 reviewer has seen the whole diff.

**Status at end of iteration 1: COMPLETED (2026-10-26) — re-opened the same day.**

### What was built

Five steps across 7 source files, 3 test files and 6 documentation files.

- **Step 1** — all nine JSON parse guards made **total** (`except Exception`), replacing
  per-name enumeration that had already failed twice on this same defect class.
- **Step 2** — `do_GET`'s config round-trip (which could raise on the *encode* half)
  replaced with a lock-held, totally-guarded `json.dumps`, answering `500` on failure.
- **Step 3** — `POST /admin/api/switch` rejects per-tier keys other than
  `provider`/`model`/`key`, closing the client-reachable no-response abort on the
  write path.
- **Step 4** — two guards at the top of `admin.html`'s `saveConfig`, refusing the press
  on an unrendered tier row and on an unloaded key list (the latter being the silent
  credential re-pointing).
- **Step 5** (tester) — `tests/test_parse_guards.py`, a new permanent module with three
  tests, registered in the hand-maintained aggregator, plus two structural pins in
  `tests/test_admin.py`.

### Verification evidence

| Check | Result |
|-------|--------|
| Full suite (declared runner), post-change | **448 passed, 0 failed, 448 total**, exit 0 |
| Pre-change baseline, measured before any test edit | 443 passed, 0 failed, 443 total, exit 0 |
| Delta | exactly the 5 new tests; no pre-existing failure existed to investigate |
| Gate 1 — parse-guard totality (AST) | `PASS 22/22` (pre-change: `FAIL 13/23`, 10 failing) |
| Gate 2 — admin page incomplete view (Node) | `PASS 3/3` (pre-change: `FAIL 1/3`) |
| Gate 3 — switch input (real spawned server) | `PASS 4/4` (pre-change: `FAIL 1/4`) |
| Reachability, measured not claimed | HEAD **10/23** failing → landed **0/22**; mutant with `cli._parse_trace_entry` re-narrowed to `JSONDecodeError` → **1/22** fires |
| `test_admin.py` pins reachability | measured RED against HEAD's `admin.html`, GREEN against the landed page |
| Doc gates | `check_doc_anchors.py` PASS (233 anchors); `doc_structure_check.py` PASS (9 files) |
| Reviewer | **0 Critical, 1 Warning, 5 Suggestion** — gate passes |

The planner re-ran all three gates, the suite, and both doc gates independently after the
rounds; the reviewer reproduced the same figures and additionally put every previously
unmeasured branch RED by mutation.

### Issues resolved

All three Issue Log rows are `Resolved`, dated 2026-10-26, `Resolved By: tester`:

- `admin-page-gate-sticky-counter-unreachable` — **Plan Error** in the planner's own gate.
  Its check 1 asserted a page-lifetime `setTimeoutCalls() === 0`, which no compliant
  implementation could reach; fixed press-scoped and re-measured, and the reviewer
  confirmed the fix is sound rather than relocated.
- `defer-issue-admin-unrendered-page-apply-throws` — resolved by Step 4.
- `defer-issue-recursion-guard-residual-sites` — resolved as a **superset**: ten sites,
  not the three the deferral named.

### Deferred issues adopted and closed

Both deferrals this plan adopted are resolved above. The recursion deferral's own
undercount is the plan's central finding: its AST scan covered four modules and
classified by enclosing-`try` exception names, so it could see neither an unguarded site
nor the modules it never read. Both `defer-issue-*.json` reports remain on disk until
`/update-and-commit` Step 9.6 deletes them in the same act that commits this plan.

### Known caveats — reviewer findings, none blocking

The review gate passed with **no Critical** findings. One Warning and five Suggestions
are acknowledged and **await the operator's disposition** (presented with this plan; the
plan is not re-opened unilaterally). The Warning is recorded here in full because it
falsifies a claim this plan made:

1. **[Warning] `reviewer-warning-nonstring-tier-provider-model-aborts-do-post`** — a
   non-string `provider`/`model` in a switch body aborts `do_POST` with **no HTTP
   response**. `_validate_admin_name` bounds *strings*; for a dict/list/int it **raises**
   `TypeError: expected string or bytes-like object` rather than returning `False`, and
   there is no outer `try`. Independently reproduced by the planner against a really
   spawned server: `{"provider": {}}` and `{"provider": ["x"]}` → `RemoteDisconnected`;
   `{"provider": 5}`, `{"model": 5}`, `{"model": null}` → no response within 15 s (the
   socket stays open). The server survives and leaves no temp file. **This is the same
   defect class Step 3 exists to close, two lines below the new check**, and it means
   Step 3's original closure argument overclaimed — the unknown-**key** hole is closed,
   the non-string-**value** hole is not. The paragraph at Step 3 is corrected in place
   with the measurement.
2. **[Suggestion] `reviewer-suggestion-unbounded-tier-names-persisted`** — tier *names*
   are unvalidated: an extra tier `ghost-tier` returns 200 and is persisted verbatim into
   `config.json` (measured). Unrelated to the parse-guard invariant, but the same
   validation loop.
3. **[Suggestion] `reviewer-suggestion-read-state-oserror-misreported-as-absent`** — the
   one site where widening a guard changed a caller-visible outcome: `_read_state` now
   also absorbs `PermissionError`/`IsADirectoryError`, and every caller reports a falsy
   result as "no state file", so `stop` can exit 0 against an unreadable state file.
4. **[Suggestion] `reviewer-suggestion-loadconfig-ignores-response-ok`** — Step 2's new
   `500` is parsed by the page as a config, surfacing as a JS `TypeError` message rather
   than the server's own text. (Interestingly, this means the page's *new* failure path
   behaves like the old blank-page one.)
5. **[Suggestion] `reviewer-suggestion-no-committed-coverage-for-step2-step3`** — Steps 2
   and 3's server behaviours have **no committed coverage**; only the transient
   `tmp/verification/` gates, which the post-commit sweep retires.
6. **[Suggestion] `reviewer-suggestion-parse-guard-gate-top-level-scan-only`** — the
   permanent gate uses `os.listdir` (package top level only), so a future subpackage's
   parse sites would be silently unscanned while the gate stayed green. True today only
   as a latent risk (measured: the package has no subpackages).

Reviewer self-assessment: confidence **high**, coverage complete over all 10 tracked
files plus the untracked test module and all four verification scripts; limitations are
no browser-level execution and no live upstream emitting deeply nested tool arguments.

### Outcome

The plan's operative goal is met and verified: **every JSON parse site in the package has
a total guard, enforced by a permanent test that has been proven to go RED**, and the
admin surface refuses rather than acting on data it does not have. The caveats above are
adjacent hardening — one of them, the Warning, completes a claim Step 3 made and did not
fully deliver.

(Populated after implementation completes.)