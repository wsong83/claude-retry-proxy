# Plan: Sweep the terminal deferral corpus and make the index honest
**Project:** D:\proj\claude-retry-proxy
**Plan ID:** 2026-10-15-deferred-corpus-sweep
**Created:** 2026-10-15

> **Planner-only plan.** No coder or tester steps; no implementation rounds.
> Phases 5 and 6 tolerate the absent coder/tester reports for this plan.
>
> **Precondition — execute this plan LAST in the cycle.** Its third step
> rewrites `CLAUDE.md`'s deferred-issue index to the cycle's end state, and
> Plans A/B/C each close issues of their own. Run this only after
> `2026-10-15-posix-shutdown-and-stop-reporting`,
> `2026-10-15-chat-sse-stream-tail` and `2026-10-15-test-harness-robustness`
> have completed their `/update-plan` cycles. The step-1 gate asserts the end
> state, so it is expected to be red until then.

## Issue Log

Rows ordered newest-first. The 24 swept rows are recorded here because the
plan's Issue Log is the record that outlives the report files; `/update-and-commit`
Step 9.6 retires a report whose row is `Resolved`, and this plan is the row's
author for every entry below.

| Issue | Status | Found | Resolved | Resolved By |
|-------|--------|-------|----------|-------------|
| [planner-doctrine-gaps](./tmp/reports/defer-issue-planner-doctrine-gaps.json) | Open (deferred, **cross-repo → `claude-config`**) | 2026-10-16 | — | deferred — filed after this plan's execution, when the user asked whether the two lessons the plan had just produced were really planner-doctrine gaps rather than project memories. They are: **gate calibration is undocumented** (`calibrat` appears **0** times in the 751-line `root/agents/planner.md` — claude-config's **source**, not the deployed copy, which is a *different* file at the same line count — `ownership` **0**, `negative assert` **0** — re-derivable in one command, quoted in the report), **ownership changes carry no reader-enumeration rule**, and **the round-triage freshness notion stops at session reports** rather than covering any artifact read off disk. All three cost this cycle real rounds: a false-GREEN calibration, a drain that stole a pipe two tests read directly (423/1, with four neighbouring assertions passing *vacuously* because they were phrased as absences), and a killed round's suite log read as a live flake when its own progress log showed the fix landing *after* the failing run. The `target_repo` is `claude-config` — the repo that owns `~/.claude/agents/planner.md` and `~/bin/claude_*`, which are **deployed copies** `deploy.py` overwrites, so the edit belongs in the source. At the user's 2026-10-16 instruction the report is **mirrored** into `claude-config/tmp/reports/` under the same `issue_id` (`target_repo` null there, since that is the repo that fixes it), because a report living only here is invisible to that repo's own sessions — the corpus is machine-local and presence is the state. The two copies are one issue, cross-referenced in both directions, and their retirement is paired. Recorded as one issue rather than five so the deferral corpus does not double-count the same lesson |
| [extract-model-raises-on-non-object-json](./tmp/reports/defer-issue-extract-model-raises-on-non-object-json.json) | Resolved | 2026-09-12 | 2026-10-15 | Verified fixed in source — `server.py:1714` guards `isinstance(data, dict)` and the docstring carries the total 5-outcome contract |
| [unfinished-turn-detector-ignores-degraded-tool](./tmp/reports/defer-issue-unfinished-turn-detector-ignores-degraded-tool.json) | Resolved | 2026-10-04 | 2026-10-15 | Verified fixed in source — `server.py:2999` carries the `and not tool_calls_seen` clause |
| [widened-guard-silent-in-anthropic-mode](./tmp/reports/defer-issue-widened-guard-silent-in-anthropic-mode.json) | Resolved | 2026-10-05 | 2026-10-15 | Verified fixed in source — `server.py:1166` logs `transform_failure` unconditionally; the `mode != "anthropic"` gate is gone |
| [client-body-recursionerror-no-response](./tmp/reports/defer-issue-client-body-recursionerror-no-response.json) | Resolved | 2026-09-30 | 2026-10-15 | Verified fixed in source at all four named sites (`server.py:1031`, `server.py:1712`, `compat.py:795`, response helper); the remaining narrow guards are a different surface, re-filed as [recursion-guard-residual-sites](./tmp/reports/defer-issue-recursion-guard-residual-sites.json) |
| [admin-readiness-probe-flake-under-suite-load](./tmp/reports/defer-issue-admin-readiness-probe-flake-under-suite-load.json) | Resolved | — | 2026-10-15 | Withdrawn deferral — superseded by the tester's own issue report and fixed; the file is a terminal artifact |
| [preexisting-cli-state-file-leak](./tmp/reports/defer-issue-preexisting-cli-state-file-leak.json) | Resolved | 2026-10-05 | 2026-10-05 | Resolved by tester |
| [stale-test-state-file-pid-reuse](./tmp/reports/defer-issue-stale-test-state-file-pid-reuse.json) | Resolved | 2026-10-03 | 2026-10-03 | 2026-10-03-stale-test-state-file-pid-reuse |
| [trailing-usage-chunk-never-read](./tmp/reports/defer-issue-trailing-usage-chunk-never-read.json) | Resolved | 2026-10-02 | 2026-10-02 | 2026-10-02-drain-after-finish-reason |
| [finish-before-tool-calls-dropped](./tmp/reports/defer-issue-finish-before-tool-calls-dropped.json) | Resolved | 2026-10-02 | 2026-10-02 | 2026-10-02-drain-after-finish-reason |
| [consolidate-module-split-guidance-docs](./tmp/reports/defer-issue-consolidate-module-split-guidance-docs.json) | Resolved | 2026-09-14 | 2026-09-16 | 2026-09-16-refactor-split-skill |
| [review-content-readme-link-raw-markdown](./tmp/reports/defer-issue-review-content-readme-link-raw-markdown.json) | Resolved | 2026-09-13 | 2026-09-14 | 2026-09-14-commit-doc-anchor-check |
| [review-anchor-resolver-not-committed](./tmp/reports/defer-issue-review-anchor-resolver-not-committed.json) | Resolved | 2026-09-13 | 2026-09-14 | 2026-09-14-commit-doc-anchor-check |
| [state-sink-empty-path-stray-tmp](./tmp/reports/defer-issue-state-sink-empty-path-stray-tmp.json) | Resolved | 2026-09-12 | 2026-09-15 | 2026-09-15-sanitize-sinks-deferred |
| [sink-chmod-branch-untested-outside-posix](./tmp/reports/defer-issue-sink-chmod-branch-untested-outside-posix.json) | Resolved | 2026-09-12 | 2026-09-15 | 2026-09-15-sanitize-sinks-deferred |
| [sanitize-error-regex-catastrophic-backtracking](./tmp/reports/defer-issue-sanitize-error-regex-catastrophic-backtracking.json) | Resolved | 2026-09-12 | 2026-09-15 | 2026-09-15-sanitize-sinks-deferred |
| [sanitize-error-path-redaction-inert-on-windows](./tmp/reports/defer-issue-sanitize-error-path-redaction-inert-on-windows.json) | Resolved | 2026-09-12 | 2026-09-15 | 2026-09-15-sanitize-sinks-deferred |
| [planner-reads-nonexistent-test-catalog](./tmp/reports/defer-issue-planner-reads-nonexistent-test-catalog.json) | Resolved | 2026-09-12 | 2026-09-12 | 2026-09-12-build-doc-tree |
| [extraction-criteria-link-dead-in-public](./tmp/reports/defer-issue-extraction-criteria-link-dead-in-public.json) | Resolved | 2026-09-12 | 2026-09-16 | 2026-09-16-refactor-split-skill |
| [compat-entry-failed-confirmations-dead-field](./tmp/reports/defer-issue-compat-entry-failed-confirmations-dead-field.json) | Resolved | 2026-09-12 | 2026-09-23 | 2026-09-23-drop-dead-failed-confirmations-field |
| [claude-md-sinks-policy-duplicated](./tmp/reports/defer-issue-claude-md-sinks-policy-duplicated.json) | Resolved | 2026-09-12 | 2026-09-12 | 2026-09-12-build-doc-tree |
| [claude-md-line-refs-rotted](./tmp/reports/defer-issue-claude-md-line-refs-rotted.json) | Resolved | 2026-09-12 | 2026-09-12 | 2026-09-12-build-doc-tree |
| [write-state-no-lock-concurrent-replace](./tmp/reports/defer-issue-write-state-no-lock-concurrent-replace.json) | Resolved | 2026-09-11 | 2026-09-15 | 2026-09-15-sanitize-sinks-deferred |
| [unguarded-write-state-log-trace-oserror](./tmp/reports/defer-issue-unguarded-write-state-log-trace-oserror.json) | Resolved | 2026-09-07 | 2026-09-10 | 2026-09-10-guard-trace-state-sinks |
| [break-up-large-source-and-test-files](./tmp/reports/defer-issue-break-up-large-source-and-test-files.json) | Resolved | 2026-09-01 | 2026-09-16 | 2026-09-16-refactor-split-skill |

## Guidance for Coder

**Files to modify:** none. This plan is planner-only.

## Guidance for Tester

**Tests to create:** none.

**Tests to investigate for retirement:**
- No test obsolescence identified — this plan changes no source and no test.

## Summary

`./tmp/reports/` holds 30 `defer-issue-*.json` files. They are **not** 30 open
issues. `defer-issue.md:70` is explicit that status is transitional — *"the
file's presence IS the open state; `status` is always `"Open"` for a file on
disk (terminal dispositions delete the file)"* — so the directory has
accumulated 24 files that should already be gone:

| Bucket | Count | Evidence |
|--------|-------|----------|
| Carrying `status: "Resolved"` | 19 | Each names its resolving plan in `resolved_by` |
| Carrying `status: "Withdrawn"` | 1 | `admin-readiness-probe-flake-under-suite-load` — superseded and fixed |
| Verified fixed in source, never closed | 4 | Verified 2026-10-15 by reading the current tree |

The fourth bucket is the one that matters: all four are still labelled `Open`,
so anything reading the corpus at face value believes the proxy still has a
non-object-JSON crash in `extract_model`, a mis-attributing unfinished-turn
detector, a silent anthropic-mode transform failure, and an unguarded
client-body parse. All four are fixed in the shipped source. Left alone, they
distort every future triage — this session's clustering initially counted them
as live defects.

**The index is wrong in both directions.** `CLAUDE.md`'s "Unresolved Deferred
Issues" block lists 13 entries, and **six of them no longer have a report on
disk** — `no-proxy-stop-trace-warning`, `cli-pre-existing-remove-idiom-copies`
and `suite-load-admin-connection-abort` (closed by
`2026-10-15-test-harness-robustness`), `posix-sigterm-shutdown-deadlock`
(`2026-10-15-posix-shutdown-and-stop-reporting`), and
`chat-sse-done-framing-assumption` plus `chat-sse-late-frame-offsets-unasserted`
(`2026-10-15-chat-sse-stream-tail`). The block was never a reliable index: four
deferrals that existed on disk were **never added to it at all** —
`cli-stop-always-returns-zero` (fixed by Plan A, and the most consequential CLI
defect in the corpus, invisible to the project's own tracking),
`harness-ready-marker-comment-windows` (closed by Plan C's Step 4),
and `unfinished-turn-detector-ignores-degraded-tool` and
`widened-guard-silent-in-anthropic-mode` (both this plan's fourth bucket).

**Approach.** Record every disposition in this plan's Issue Log (the record that
outlives the files), file one new deferral for the residual the fourth bucket
genuinely leaves behind, then retire the 24 files and rewrite the index to the
cycle's end state.

**The residual is re-filed, not dropped.** `client-body-recursionerror-no-response`
named four sites; all four are now total. Three narrower guards remain that share
the failure class — `server.py:3381` (the admin switch body), and
`transforms_chat.py:462` / `transforms_response.py:373` (upstream SSE per-frame
payloads, i.e. *upstream-controlled* input). Those are a different surface from
the client-body path the report was about, so they are filed fresh as
`recursion-guard-residual-sites` rather than silently absorbed into a `Resolved`
row.

```
  before:  30 files on disk ──► 10 nominally open, 4 of them already fixed
                                index block lists 13 (6 with no report left, 4
                                never indexed at all)
  after:    7 files on disk ──►  6 genuinely open + 1 newly filed residual
                                index block lists exactly those 7
```

**Alternatives considered.** (a) *Delete only the 20 terminal files and leave the
4 stale-open ones* — rejected: they are the actively misleading ones.
(b) *Leave the files and fix only the index* — rejected: presence means open, so
the corpus keeps lying to the next reader. (c) *Re-open the 4 as fresh issues to
"close them properly"* — rejected as pure ceremony; the source already proves
them fixed.

**Out of scope.** The five genuinely open issues that this cycle deliberately
leaves deferred — `port-default-collision-hazard`,
`proxy-stderr-append-stale-tail`, `image-content-blocks-chat-mode`,
`httpx2-native-sse-transport`, and the cross-repo
`operate-round-ends-turn-before-waiting`. The five Plan-A/B/C issues: their own
plans own those rows, and this plan's index rewrite happens after theirs.

## Repo Mode

Public

## Document Overrides

| Document | Rule Overridden | Reason |
|----------|----------------|--------|

## Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| Deleting a report that is not actually terminal | Loss of a live issue's only record | Each of the 24 was verified individually: 20 carry `status: "Resolved"`/`"Withdrawn"` in the file itself, and the 4 stale-open ones were verified fixed by reading the current source (line-cited in the Issue Log). Every disposition is recorded in the Issue Log before any deletion |
| The index rewrite lands before Plans A/B/C finish | The block would list issues as closed that are still open | Stated as a precondition at the top of this plan; the step-1 gate asserts the end state and is red until the cycle completes |
| `CLAUDE.md`'s block is regenerated while a `/update-and-commit` retirement is mid-flight | Two writers disagree about which rows exist | This plan is the single writer for the block this cycle; Plans A/B/C are instructed in their own "Guidance for Planner" sections not to touch it |

## Proposed Changes

1. **Step 1:** Retire the 24 terminal deferral reports from `./tmp/reports/`, with every disposition recorded in this plan's Issue Log first
   → Evidence: `ls tmp/reports/defer-issue-*.json | wc -l` shows the end-state count, and a scripted check confirms none of the 24 named basenames survives — `python ./tmp/verification/2026-10-15-deferred-corpus-sweep-step1.py`
   → Evidence: each deletion names the file's own `status` field (for the 20) or the line-cited source verification (for the 4) in the Issue Log row above
2. **Step 2:** File the residual recursion-guard deferral as `recursion-guard-residual-sites`, naming the three remaining **reachable** narrow guards and their differing input trust levels
   → Evidence: `tmp/reports/defer-issue-recursion-guard-residual-sites.json` exists and its `problem` field names the three reachable sites as `server.py:3400` (in `do_POST`, the admin switch body), `transforms_chat.py:461` (in `_chat_to_anthropic`) and `transforms_response.py:372` (in `_response_to_anthropic`), and records a fourth, `server.py:432`, which shares the shape but was **measured unreachable**
   → **Line refs re-derived 2026-10-16.** The three written into this step when the plan was authored had rotted: `server.py:3381` is now a localhost-only `return`, not a parse guard, and the other two had drifted by one line each. The set was re-derived by AST-scanning every `json.loads` call in the four files and classifying each by the exception names of its own enclosing `try` — 16 sites, 12 already total, 4 narrow. Function names are the durable anchor, as this cycle's other plans learned the same way.
   → **The fourth site, and why it is filed as a note rather than a defect.** `server.py:432` re-parses `entry["messages_json"]` under `(TypeError, ValueError)`, while the store site one function over (`server.py:336`) guards `(TypeError, ValueError, RecursionError)`. Measured 2026-10-16: `json.dumps` encodes nested lists to depth **15510** and `json.loads` decodes a bracketed string to **16921** on this interpreter — the encode ceiling is the stricter one, so anything the store path managed to write re-parses, and the read-back guard cannot fire. Recorded because the invariant that makes it unreachable is an interpreter property, not a property of the code.
3. **Step 3:** Rewrite `CLAUDE.md`'s "Unresolved Deferred Issues" JSON block and its "Future Work — TODO" prose to the cycle's end state (seven entries: the six deliberately-left-deferred issues plus the new residual deferral)
   → Evidence: `python ./tmp/verification/2026-10-15-deferred-corpus-sweep-step1.py` exits 0 — it asserts the 24 are gone, that every issue_id in the block has a report on disk, that none of the 24 is indexed, and that `recursion-guard-residual-sites` is both indexed and filed
   → Evidence: `git diff CLAUDE.md` shows the block and the "Future Work — TODO" paragraph changed, with the per-issue resolution prose reduced to the five remaining open items

## Guidance for Planner

Documentation tasks you will execute yourself (not the coder):

- **Files to modify:**
  - `./CLAUDE.md`
- **When:** after Plans A/B/C have completed, as this plan's steps 1-3
- **What to sync:**
  - `CLAUDE.md` — the `## Unresolved Deferred Issues` fenced JSON block: replace
    all 13 entries with the cycle's end state (7 entries). Keep the existing
    field shape (`issue_id`, `title`, `target_repo`, `report`, `deferred`,
    `date_source`).
  - `CLAUDE.md` — the `## Future Work — TODO` prose paragraph: it currently opens
    "Thirteen deferred issues remain" and narrates several already-resolved
    plans. Rewrite it to describe the six remaining open issues and the one new
    residual deferral, and drop the resolution narration that duplicates the plan
    archives.
  - **Retirement mechanics:** use the guarded form from `/update-and-commit`
    Step 9.6 — validate each basename against the `defer-issue-*.json` regex,
    resolve the canonical path under `./tmp/reports/`, delete, and check the exit
    status. Do not glob-delete.

## History

| Date | Event | Conclusion | Dismissed |
|------|-------|------------|-----------|
| 2026-10-15 | Initial plan | Planner-only sweep: 24 terminal deferral reports (19 `Resolved`, 1 withdrawn, 4 verified-fixed-but-unclosed) retired, the residual recursion-guard surface re-filed, and CLAUDE.md's index block rewritten to the cycle's 7-entry end state. | — |
| 2026-10-16 | Pre-run count refresh (planner) | **Every before-count in this plan was re-derived against the corpus as the cycle actually left it.** The terminal set is unchanged at **24** (19 `Resolved` + 1 `Withdrawn` + 4 verified-fixed), and the after-state is unchanged at **6** — but the starting figures had drifted: the directory holds **29** files, not 36, and **9** nominally open, not 16, because Plan A's closeout retired `cli-stop-always-returns-zero` and `posix-sigterm-shutdown-deadlock` (the user removed both files), Plan B's retired its two chat-SSE deferrals, and Plan C's retired four more (`no-proxy-stop-trace-warning`, `cli-pre-existing-remove-idiom-copies`, `suite-load-admin-connection-abort`, `harness-ready-marker-comment-windows`). The index-drift finding was also **stronger than first recorded**: six of the block's 13 entries now have no report on disk, and **four** deferrals that existed on disk were never indexed at all — not the one this plan originally named. Re-derived by reading the corpus and the block directly (`git status`, per-file `status`, and a block-to-corpus diff), not by arithmetic on the old numbers. | — |
| 2026-10-16 | Count refresh, second pass (planner) — **Plan C's Step 9.9 filed one new deferral** | The counts above are stale by one file, and this is the *last* plan in the cycle so it must not run on arithmetic that predates the cycle's final act. Plan C's Step 9.9 disposition gate surfaced a round-4 out-of-scope observation — 36 orphaned per-run state files in `~/.claude/proxy/`, with that plan's own verification scripts a systematic source — and the **user chose defer** over fix or won't-fix, so `defer-issue-orphaned-test-state-files.json` now sits in `./tmp/reports/`. Directory **30** files (was 29), **10** nominally open (was 9), and the end state **7** (was 6): the six deliberately-left-deferred issues plus the newly filed residual. The terminal set stays **24** — the new report is `Open`, not terminal — so **Step 1's retirement list is unchanged**; only the arithmetic around it moved. Nothing else in the plan shifts: the block still holds 13 entries, the six-entries-with-no-report and four-never-indexed findings are unaffected, and Step 2 still files `recursion-guard-residual-sites`. | — |
| 2026-10-16 | **Execution (planner)** — all three steps, gate RED → GREEN in one session | Step 1 retired 24 reports with per-file evidence (`…-deferred-corpus-sweep-retire.py`, 24 RETIRED, 0 failures; corpus 30 → 7). Step 2 filed the residual deferral. Step 3 rewrote `CLAUDE.md`'s block (13 → 7 entries) and its TODO prose. The step-1 gate went from **11 failures** to **exit 0**, unedited, in the same run — the plan's end-state claim made true. Two corrections were made while executing: **Step 2's line refs had rotted** (`server.py:3381` is a localhost-only `return`), so the sites were re-derived by AST scan and are anchored on enclosing function names — which also surfaced a **fourth** narrow guard, measured unreachable because the encode ceiling sits below the decode ceiling; and **the Step 9.9 deferral's report was renamed underneath the session** (no hook does that), so the rename was completed rather than reverted — `issue_id` now matches the basename, and all 7 reports satisfy `basename == defer-issue-<issue_id>.json`. One stale paragraph in `CLAUDE.md` — the staged-decomposition line counts — was flagged to the user rather than edited, being outside this step's declared scope. | — |
| 2026-10-16 | Post-execution deferral (user decision) — **`planner-doctrine-gaps` filed cross-repo; corpus 7 → 8** | After the sweep committed, the user asked whether the two lessons the execution had just produced were really **planner-doctrine gaps** rather than project memories, and whether to defer them to the planner's own repo instead. Measured and answered: they are. `root/agents/planner.md` (claude-config's **source**, 751 lines — the deployed copy is a *different* file at the same line count, so the copy measured has to be named) contains the string `calibrat` **zero** times, `ownership` **zero**, `negative assert` **zero** — so gate calibration, ownership enumeration and the extension of the fresh-report notion to arbitrary artifacts are all undocumented, while the three incidents behind them cost this cycle real rounds. Filed as **one** cross-repo deferral against `target_repo: claude-config` (the repo that owns `~/.claude/agents/planner.md` and `~/bin/claude_*`, which `deploy.py` overwrites — the edit belongs in the source) rather than five, so the corpus does not double-count one lesson. The **five project memories stay until the doctrine lands**, then are retired; deleting them now would lose the lesson in the interim. At the user's follow-up instruction the same day the report was **mirrored** into `claude-config/tmp/reports/` under the same `issue_id`, with `target_repo` null there because that is the repo that fixes it: `/defer-issue`'s documented behaviour keeps a cross-repo report in the **filing** repo only, and the corpus is machine-local, so a report living only here is invisible to that repo's own sessions. The two copies are one issue, not two, and because each repo retires reports by deleting the file, their retirement is paired. Consequence for this plan's arithmetic, stated against the **post-sweep** series rather than the pre-sweep one: the sweep left **7** files on disk (6 non-terminal survivors + `recursion-guard-residual-sites`) and this deferral makes it **8**, all of them nominally open and all genuinely so. The block goes 13 entries → **8**. The terminal set is still **24**, so Step 1's retirement list is untouched, and the step-1 gate asserts *agreement* rather than a count — which is why it stayed green across this change. | — |

## Plan Metadata

```json
{
  "plan_id": "2026-10-15-deferred-corpus-sweep",
  "steps": [
    "Step 1: Retire the 24 terminal deferral reports from ./tmp/reports/",
    "Step 2: File the residual recursion-guard deferral as recursion-guard-residual-sites",
    "Step 3: Rewrite CLAUDE.md's Unresolved Deferred Issues block and Future Work prose"
  ],
  "coder_files": [],
  "tester_files": [],
  "doc_files": ["./CLAUDE.md"],
  "verification_scripts": [
    "./tmp/verification/2026-10-15-deferred-corpus-sweep-step1.py"
  ],
  "repo_mode": "Public",
  "document_overrides": []
}
```

## Audit Accumulation

| Counter | Value | Last Updated |
|---------|-------|--------------|
| issues_resolved_since_audit | 24 | 2026-10-16 |
| steps_changed_since_audit | 0 | 2026-10-16 |
| files_changed_since_audit | 1 | 2026-10-16 |

No audit has been run against this plan — it is planner-only, changes no source
and no test, and its whole output is a corpus sweep plus one documentation
rewrite. The 24 is the Issue Log's own count of terminal dispositions, and the 1
is `CLAUDE.md`.

## Documentation

- `CLAUDE.md` — the deferred-issue index block and the "Future Work — TODO"
  prose, rewritten to the cycle's end state.

## Final Results

**Completed:** 2026-10-16
**Status:** COMPLETED
**Plan ID:** 2026-10-15-deferred-corpus-sweep
**Rounds:** none. Planner-only plan — no coder and no tester lane, executed
directly by the planner as its three steps prescribe.

### What shipped

| Step | Change | Evidence |
|------|--------|----------|
| 1 | The **24 terminal deferral reports** retired from `tmp/reports/`, each with its disposition class printed beside the file's own `status` field, its `issue_id` re-checked against the name it was retired under, and its absence confirmed by re-stat | `tmp/verification/2026-10-15-deferred-corpus-sweep-retire.py` — 24 RETIRED lines, 0 failures; corpus 30 → 7 at that point, → **8** after the post-execution deferral below |
| 2 | The residual filed as `recursion-guard-residual-sites`, naming three **reachable** narrow guards with their differing input trust levels and a fourth measured unreachable | `tmp/reports/defer-issue-recursion-guard-residual-sites.json` |
| 3 | `CLAUDE.md`'s "Unresolved Deferred Issues" block (**13 entries → 8**) and its "Future Work — TODO" prose rewritten to the cycle's end state | step-1 gate GREEN |

**Files changed:** `CLAUDE.md`. Everything else the plan produced is machine-local
(`tmp/reports/`, `tmp/verification/`).

### Verification

**`python tmp/verification/2026-10-15-deferred-corpus-sweep-step1.py` exits 0** —
*"24 terminal reports swept; CLAUDE.md indexes 8 issues, all with a report on
disk"* (it read **7** between this plan's execution and the post-execution
deferral recorded below; the gate asserts agreement, not a count, so both
readings are green). Before execution the same gate was **RED with 11 failures**, which is the
calibration: it named all 24 survivors, all six block entries with no report left,
both swept issues still indexed, and the absent residual. The gate was therefore
red against the pre-state and green against the post-state, in the same run
session, with no edit to the gate.

Its conditions are the plan's own end-state claim, so passing them is the plan
being made true rather than a check bolted on: (A) none of the 24 survives,
(B) every indexed `issue_id` has a report on disk, (C) none of the 24 is indexed,
(D) the new residual is both indexed and filed. Condition B is a **bidirectional**
honesty check — the old block failed it in both directions at once, with six
entries pointing at reports that no longer existed and four reports that had
never been indexed.

Independent of the gate: every report on disk was checked for
`basename == issue_id` (**8/8 OK**), and a recursive scan confirms no reference to
the retired corpus survives in `CLAUDE.md`, `plans/` or `tmp/plans/`.

### Two corrections made while executing

1. **Step 2's line references had rotted**, which the plan had guarded against
   everywhere except here. `server.py:3381` is a localhost-only `return`
   statement, not a parse guard. The sites were re-derived by AST-scanning every
   `json.loads` call in the four files and classifying each by the exception
   names of its own enclosing `try` — 16 sites, 12 already total, 4 narrow — and
   the report anchors them on enclosing function names, which do not rot. The
   same scan found a **fourth** narrow guard the plan had not named
   (`server.py:432`), and measuring it showed it **cannot fire**: `json.dumps`
   encodes nested lists to depth 15,510 where `json.loads` decodes to 16,921, so
   anything the store path wrote re-parses. Filed as a consistency note rather
   than inflated into a defect.
2. **The Step 9.9 deferral's report was renamed underneath this session.** The
   file was created as `defer-issue-orphaned-test-state-files-from-verification-scripts.json`
   and was found on disk as `defer-issue-orphaned-test-state-files.json`, with the
   markdown link targets in the archived plan already rewritten to match but the
   inner `issue_id` and the visible labels not. No configured hook renames files
   (checked: the only `Write|Edit` hook is the advisory doc-structure check), so
   the rename came from outside the session. Rather than revert it, the rename was
   **completed**: the report's `issue_id` now matches its basename, and the labels
   in the plan, its archive and this plan's History follow. The corpus invariant
   `basename == defer-issue-<issue_id>.json` holds for all 8 files.

### Issues resolved

The plan's Issue Log carries **25 rows** — **24 `Resolved`** (19 whose files said
so, 1 withdrawn, and 4 verified fixed in source that were never closed) plus **1
`Open (deferred)`**: the cross-repo `planner-doctrine-gaps`, filed after execution
at the user's direction. The 24 terminal reports are gone; the Issue Log is the
surviving record, which is the whole point of the sweep.

### Deferred

**Two**, both filed on 2026-10-16.

- `recursion-guard-residual-sites`, filed by this plan — see above.
- `planner-doctrine-gaps` ([report](./tmp/reports/defer-issue-planner-doctrine-gaps.json)),
  filed **after** this plan executed, at the user's direction: the two lessons the
  execution produced turned out to be planner-doctrine gaps rather than project
  memories, so they are deferred to `claude-config` rather than living in one
  project's agent memory, where only that project would ever load them. Cross-repo
  and direction-level — the report carries the measured evidence and the three
  insertion points in `planner.md`.

### Observed, not changed

**`CLAUDE.md`'s staged-decomposition paragraph is stale and was deliberately left
alone.** It records `server.py` at 2,613 wc lines after the compat extraction,
against 4,027 today, and Plan C's own line-count survey shows the same drift
across the tree. It is load-bearing context for the /refactor-split survey rather
than deferral narration, so rewriting it here would exceed the plan's declared
scope (one index block, one TODO paragraph) — and the global CLAUDE.md rule is to
flag redundant or outdated content and wait for explicit approval rather than
delete it. **Flagged to the user.**