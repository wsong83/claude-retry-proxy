"""The served admin page's JS contract: poll guards, the pending status surface, and the Apply/Load view refusals.

Part of the claude-retry-proxy suite; runnable standalone.
"""
from _harness import (
    _admin_get,
    _mode_tiers,
    _start_admin_proxy,
    fail,
    find_free_port,
    pass_,
    run_cli,
)
import re


def _js_braced_block(text, start):
    """Extract the brace-balanced block beginning at the first '{' at or after
    `start`, braces included ('' when absent or unbalanced).

    The one brace-walker in this module: `_js_function_body` delegates here.
    Correct for the JS it is pointed at — the blocks scanned carry no
    unbalanced brace inside a string literal, and the one template literal in
    reach (`${tier}`) contributes a matched pair, so the depth count lands on
    the right closing brace. An unbalanced brace in a string would defeat it;
    re-check that if one is ever added.
    """
    open_at = text.find("{", start)
    if open_at == -1:
        return ""
    depth = 0
    for i in range(open_at, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[open_at:i + 1]
    return ""


def _js_function_body(text, header):
    """Extract a function's body by brace matching ('' when absent).

    Lets an assertion hold INSIDE a named function rather than somewhere in
    the file — the difference between "the helper does this" and "something
    does". See _js_braced_block for what the depth count can and cannot handle.
    """
    start = text.find(header)
    if start == -1:
        return ""
    return _js_braced_block(text, start)


# The three swap-status poll callbacks, each identified by the function that
# encloses it, with the done-guard it must carry. Asserted BY BLOCK IDENTITY
# rather than by scanning a candidate set: a candidate scan passes a mutant
# where every block guards on one flag, and in that mutant both press paths
# lose their real `swapSettled` re-check (review suggestion 6). The two press
# blocks bail out on `swapSettled`; the attach watcher added by
# 2026-10-15-admin-apply-status compares the generation it captured, so a late
# response from a stale watcher can only bail out.
#
# Identity is POSITIONAL — the enclosing function — because the two press
# callbacks are byte-identical (both repaint `applying — `) and neither
# contains its own function's fetch: the switch/reload POST lives outside the
# interval, in the enclosing handler. A name marker inside the block would
# therefore have to be something the block does not carry.
_POLL_BLOCK_OWNERS = (
    ("async function saveConfig(", "saveConfig press", "if (swapSettled)"),
    ("async function reloadConfig(", "reloadConfig press", "if (swapSettled)"),
    ("function attachToInFlightSwap(", "attach watcher",
     "if (myGeneration !== attachGeneration)"),
)


def test_admin_html_poll_guard_after_await():
    """Every swap-status poll callback re-checks its own done-guard AFTER its
    awaits and before the pending-status repaint (re-review finding
    review-2-stale-poll-overwrites-terminal, fixed in coder round 5; the third
    block and its guard come from 2026-10-15-admin-apply-status).

    A 1 Hz poll response generated while `swapping` was true can resolve after
    the press wrote its terminal status line; without the post-await re-check the
    poll's `showStatus('pending', 'applying — waiting for …')` overwrites that
    line, and the interval is cleared in the same `finally`, so no later poll
    corrects it. The same hazard applies to the attach watcher's terminal line.

    THREE BLOCKS, THREE GUARDS, ASSERTED BY BLOCK IDENTITY: the page carries one
    poll callback per press path (saveConfig, reloadConfig) and one in the attach
    watcher. The press blocks re-check `swapSettled`; the attach block re-checks
    the generation it captured. Each block is first identified by the enclosing
    function, so a mutant that guards every block on one flag — which would
    strip the press paths' real post-await re-check while still satisfying a
    candidate scan — fails here (review suggestion 6).

    WHAT THIS PINS, AND WHAT IT DOES NOT: the page ships no JS test harness and
    the suite is pure Python, so the runtime behaviour (a late poll does not
    repaint) is not exercised here — that is verified by reading the callbacks.
    What this test pins is the ORDERING the fixes introduced, on the page the
    proxy actually serves: in each poll callback the guard must sit between the
    response parse and the repaint, and the top-of-callback guard must still be
    there beside it. Deleting the post-await check fails this test; nothing
    else in the suite would notice.
    """
    print("\n--- Test: Admin HTML Poll Guard Sits After the Awaits ---")
    port = find_free_port()
    tiers = _mode_tiers("p")
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(port), "key": "K"}}
    proxy_port, proc, mock_servers, temp_dir, cleanup = _start_admin_proxy(
        tiers, vendors)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        status, body, _ = _admin_get(proxy_port, "/admin/")
        if status != 200:
            fail("expected 200 for /admin/, got {}".format(status))
            return
        html = body.decode("utf-8", errors="replace")

        blocks = list(re.finditer(
            r"setInterval\(async \(\) => \{(.*?)\},\s*\d+\);", html, re.S))
        if len(blocks) != 3:
            fail("expected 3 poll callbacks (saveConfig, reloadConfig, the "
                 "attach watcher), found {}".format(len(blocks)))
            return

        # Identify each block by the function enclosing it: the guard a block
        # must carry is only meaningful once the block is known.
        regions = []
        for header, kind, _guard in _POLL_BLOCK_OWNERS:
            at = html.find(header)
            if at == -1:
                fail("the {} function is not defined, so its poll callback "
                     "cannot be identified".format(kind))
                return
            regions.append((at, kind))
        regions.sort()

        by_kind = {}
        for match in blocks:
            owners = [kind for at, kind in regions if at <= match.start()]
            if not owners:
                fail("a poll callback at offset {} sits before every known "
                     "poll owner".format(match.start()))
                return
            # The innermost enclosing owner wins: a nested interval would
            # otherwise be attributed to its outer function.
            kind = owners[-1]
            if kind in by_kind:
                fail("two poll callbacks are attributed to the same owner "
                     "({}); expected one each for {}".format(
                         kind, [o[1] for o in _POLL_BLOCK_OWNERS]))
                return
            by_kind[kind] = match.group(1)
        if len(by_kind) != len(_POLL_BLOCK_OWNERS):
            fail("expected one poll callback each for {}, found {}".format(
                [o[1] for o in _POLL_BLOCK_OWNERS], sorted(by_kind)))
            return

        guards = {kind: guard for _h, kind, guard in _POLL_BLOCK_OWNERS}
        for kind, block in sorted(by_kind.items()):
            guard = guards[kind]
            if block.count(guard) < 2:
                fail("{}: expected the {!r} done-guard BOTH at the top of the "
                     "callback and after the awaits; found {} occurrence(s) — a "
                     "press block guarded on anything but swapSettled has lost "
                     "its real post-await re-check".format(
                         kind, guard, block.count(guard)))
                return
            parts = block.split("await resp.json()", 1)
            if len(parts) != 2:
                fail("{}: no 'await resp.json()' response parse".format(kind))
                return
            tail = parts[1]
            guard_pos = tail.find(guard)
            repaint_pos = tail.find("showStatus")
            if guard_pos == -1:
                fail("{}: the {!r} re-check is missing from the post-await "
                     "tail".format(kind, guard))
                return
            if repaint_pos != -1 and guard_pos > repaint_pos:
                fail("{}: the {!r} re-check sits AFTER the repaint — a late "
                     "poll response would overwrite the terminal status "
                     "line".format(kind, guard))
                return
            pass_("{}: top-of-callback guard + post-await {!r} re-check before "
                  "the repaint".format(kind, guard))
    finally:
        cleanup()


def test_admin_html_pending_status_styled():
    """The served admin page paints a VISIBLE pending status, locks the whole
    switch surface while a swap is in play, and detects a swap it did not
    press (plan 2026-10-15-admin-apply-status).

    The defect this plan fixes was invisible from every other test: the
    pending line was emitted as `showStatus('', …)`, so `className` became
    `status ` and no CSS rule ever assigned it `display: block` — every
    pending message rendered with zero height. Nothing in the suite served
    the page and looked at the pending state's style or at the call shape, so
    the page could regress to a silently blank status line with the whole
    suite green.

    WHAT THIS PINS, AND WHAT IT DOES NOT: the served HTML's structure — the
    styled pending rule, the compound disabled-button selector, the absence of
    empty-type calls, the pending call-site count, the attach watcher and its
    load-time counterpart, the button ids, the select-inclusive lockout with
    its single-key restore and its arming on both press paths, the poll-failure
    signal, the completion re-render, the gating of the completion's unlock and
    success line on a successful re-read, the reload path's stale-refusal
    re-read with its gated unlock, the attach watcher's pre-repaint settled
    bail, the load path's own gate (its re-read result captured, its failure
    branch locking and returning over a possibly-pre-swap row, and its
    post-await press-guard re-check), and the operator-guidance strings. It
    does NOT pin runtime behaviour:
    the page ships no JS harness, so that a pending line is actually visible in
    a browser, that a press is actually refused while a swap runs, and that the
    lockout actually restores the operator's controls are read from source
    ordering, not exercised.

    The code-shape patterns are quote-agnostic (`'pending'` / `"pending"`) and
    the lockout's field list is matched loosely, so a cosmetic re-quote fails
    with a truthful message rather than a misleading one (review suggestion 10).
    The `config_reload_stale` discriminator is matched the same way (review
    F4), so a behaviour-identical re-quote cannot blank the (m)-(o) extraction
    and report a branch that could not be read when the branch is there.
    """
    print("\n--- Test: Admin HTML Pending Status Styled ---")
    port = find_free_port()
    tiers = _mode_tiers("p")
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(port), "key": "K"}}
    proxy_port, proc, mock_servers, temp_dir, cleanup = _start_admin_proxy(
        tiers, vendors)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        status, body, _ = _admin_get(proxy_port, "/admin/")
        if status != 200:
            fail("expected 200 for /admin/, got {}".format(status))
            return
        html = body.decode("utf-8", errors="replace")

        # (a) The pending state is styled visible. `.status` alone is
        # display:none; only the state rules re-enable it, and before this
        # plan none of them matched the pending class.
        if re.search(r"\.status\.pending\s*\{[^}]*display\s*:\s*block", html):
            pass_("(a) the .status.pending rule assigns display: block")
        else:
            fail("(a) no `.status.pending` rule with `display: block` — every "
                 "pending message would render invisible (zero height)")

        # (b) The disabled-button rule outranks `button.secondary:hover`.
        # `button.secondary:hover` scores (0,2,1) and beats a bare
        # `button:disabled` (0,1,1) whatever the source order, so the compound
        # selector is required or a disabled Reload button under the pointer
        # keeps painting the enabled hover colour. Scoped to the rule(s) that
        # mention button:disabled — the page has an unrelated select:disabled.
        disabled_sels = [sel.strip() for sel, _b
                         in re.findall(r"([^{}]+)\{([^}]*)\}", html)
                         if "button:disabled" in sel]
        if disabled_sels and any("button.secondary:disabled:hover" in s
                                 for s in disabled_sels):
            pass_("(b) the disabled-button rule lists button:disabled AND "
                  "button.secondary:disabled:hover")
        else:
            fail("(b) the disabled-button rule does not outrank "
                 "button.secondary:hover; selector list(s): {!r}".format(
                     disabled_sels))

        # (c) No pending message uses the empty type. This call shape is the
        # exact defect the plan fixes, and nothing else in the suite would
        # have caught it.
        empty_calls = re.findall(r"showStatus\(\s*(?:''|\"\")", html)
        if not empty_calls:
            pass_("(c) no empty-type showStatus('') call remains")
        else:
            fail("(c) {} empty-type showStatus('') call(s) remain — the call "
                 "shape that rendered the pending line "
                 "invisible".format(len(empty_calls)))

        # (d) Pending lines at their call sites: 2 press entry paints + 2
        # press repaints + 3 attach-watcher paints (entry, repaint, failed
        # re-read) + the poll-failure line. A threshold of 4 is satisfied by
        # the press sites alone, so it would pass with the watcher's paints
        # deleted. Quote-agnostic, so a cosmetic re-quote does not fail this
        # with a message about a missing watcher (review suggestion 10).
        pending_sites = len(re.findall(r"showStatus\(\s*['\"]pending['\"]",
                                       html))
        if pending_sites >= 6:
            pass_("(d) showStatus('pending') at {} call sites (>= 6)".format(
                pending_sites))
        else:
            fail("(d) showStatus('pending') at {} call sites; expected >= 6 "
                 "(2 press entry + 2 press repaint + 2 attach "
                 "watcher)".format(pending_sites))

        # (e) The attach watcher and the load-time detection exist and are
        # wired in: definition + both 409 branches + the load check for the
        # watcher, definition + its loadConfig call for the check.
        attach_def = "function attachToInFlightSwap(" in html
        load_def = "function checkInFlightSwapOnLoad(" in html
        attach_n = html.count("attachToInFlightSwap(")
        load_n = html.count("checkInFlightSwapOnLoad(")
        if attach_def and load_def and attach_n >= 4 and load_n >= 2:
            pass_("(e) attachToInFlightSwap and checkInFlightSwapOnLoad are "
                  "defined and invoked ({} / {} occurrences)".format(
                      attach_n, load_n))
        else:
            fail("(e) attach watcher/load check incomplete: defined "
                 "attach={} load={}, occurrences attach={} load={} "
                 "(expected >= 4 / >= 2)".format(
                     attach_def, load_def, attach_n, load_n))

        # (f) Both control ids the lockout addresses.
        if 'id="apply-btn"' in html and 'id="reload-btn"' in html:
            pass_("(f) both button ids present (apply-btn, reload-btn)")
        else:
            fail("(f) missing button id(s): apply-btn={} reload-btn={}".format(
                'id="apply-btn"' in html, 'id="reload-btn"' in html))

        # (g) The lockout reaches the nine tier selects, not just the buttons.
        # Asserted INSIDE the helper: the provider/model/key loop and
        # `keys.length <= 1` both already exist elsewhere (populateKeys), so a
        # file-wide search would pass on the pre-change tree. The field list is
        # matched loosely rather than as one exact literal, so a re-quote or a
        # re-space of the array does not report a missing lockout (review
        # suggestion 10).
        lock_body = _js_function_body(html, "function setSwapControlsDisabled(")
        if not lock_body:
            fail("(g) the setSwapControlsDisabled helper is not defined")
        else:
            if (re.search(r"for\s*\(\s*const\s+field\s+of\s*\[\s*"
                          r"['\"]provider['\"]\s*,\s*['\"]model['\"]\s*,\s*"
                          r"['\"]key['\"]\s*\]", lock_body)
                    and re.search(r"tier\s*\+\s*['\"]-['\"]\s*\+\s*field",
                                  lock_body)):
                pass_("(g) the lockout iterates the nine tier selects "
                      "(provider/model/key)")
            else:
                fail("(g) the lockout does not reach the tier selects — the "
                     "buttons are locked but the selects stay editable, which "
                     "is what makes the completion re-render unsafe")
            if re.search(r"keys\.length\s*<=\s*1", lock_body):
                pass_("(g) unlocking restores populateKeys' single-key rule "
                      "(keys.length <= 1)")
            else:
                fail("(g) unlocking does not restore the single-key rule — a "
                     "blanket unlock would wrongly enable a single-key "
                     "provider's key select")

        # (h) A persistently failing attach poll is signalled rather than
        # swallowed: on that path a successful `swapping: false` read is the
        # watcher's only exit and nothing else unlocks the controls.
        if ("function noteAttachPollFailure(" in html
                and html.count("noteAttachPollFailure(") >= 3):
            pass_("(h) noteAttachPollFailure is defined and invoked at {} call "
                  "sites".format(html.count("noteAttachPollFailure(")))
        else:
            fail("(h) noteAttachPollFailure incomplete: defined={}, "
                 "occurrences={} (expected >= 3)".format(
                     "function noteAttachPollFailure(" in html,
                     html.count("noteAttachPollFailure(")))
        if re.search(r"attachPollFailures\s*===\s*\d+", html):
            pass_("(h) the attach poll-failure threshold constant is present")
        else:
            fail("(h) no `attachPollFailures === <n>` threshold — the "
                 "poll-failure line would never fire and a locked page would "
                 "narrate progress forever")

        # (i) The attach completion re-renders the tier row from the server,
        # and does so BEFORE the unlock: unlocking first would let
        # renderTiers() re-enable the selects after the unlock, leaving the
        # page unlocked with the stale pre-swap values still on screen. Both
        # positions are read from ONE search of the body — searching the unlock
        # forward from the re-render would make an `unlock is earlier`
        # comparison unreachable (review suggestion 9).
        attach_body = _js_function_body(html, "function attachToInFlightSwap(")
        if not attach_body:
            fail("(i) the attachToInFlightSwap body could not be read")
        else:
            refresh_at = attach_body.find("await refreshTiersFromServer();")
            unlock_at = attach_body.find("setSwapControlsDisabled(false);")
            if refresh_at == -1:
                fail("(i) the attach completion does not re-render the tier "
                     "row from the server — a press from the values it shows "
                     "would write back a pre-swap baseline")
            elif unlock_at == -1:
                fail("(i) the attach completion never unlocks the switch "
                     "surface")
            elif unlock_at < refresh_at:
                fail("(i) the attach completion unlocks BEFORE the re-render "
                     "(refresh_at={} unlock_at={}) — renderTiers() would "
                     "re-enable the selects after the unlock".format(
                         refresh_at, unlock_at))
            else:
                pass_("(i) the attach completion re-renders from the server "
                      "BEFORE unlocking")

        # (j) The two operator-guidance strings. The pending line says a
        # refresh is not needed; the poll-failure line has to say that
        # reloading IS the way out — the one place it is the right advice.
        if "no need to refresh" in html:
            pass_("(j) the pending line tells the operator no refresh is "
                  "needed")
        else:
            fail("(j) the pending line is missing the 'no need to refresh' "
                 "guidance")
        if "reload this page when it is back" in html:
            pass_("(j) the poll-failure line tells the operator reloading is "
                  "the way out")
        else:
            fail("(j) the poll-failure line does not tell the operator that "
                 "reloading is safe")

        # (k) Both press paths ARM the lock before they fetch — asserted per
        # handler body, not by a file-wide count (review suggestion 7):
        # setSwapControlsDisabled also appears in the attach watcher and in
        # both `finally` blocks, so deleting the entry lock from one handler
        # leaves a count-based probe green while leaving the whole switch
        # surface editable for the entire press.
        for fn, path in (("saveConfig", "/admin/api/switch"),
                         ("reloadConfig", "/admin/api/reload")):
            handler = _js_function_body(html, "async function {}(".format(fn))
            lock_at = handler.find("setSwapControlsDisabled(true);")
            fetch_at = handler.find(path)
            if not handler or lock_at == -1 or fetch_at == -1 or lock_at > fetch_at:
                fail("(k) {0}() does not lock the switch surface before its "
                     "{1} fetch (body={2}, lock_at={3}, fetch_at={4}) — the "
                     "controls stay editable for the whole "
                     "press".format(fn, path, bool(handler), lock_at, fetch_at))
            else:
                pass_("(k) {}() locks the switch surface before its "
                      "fetch".format(fn))

        # (l) A FAILED re-read must neither unlock nor claim success (review
        # Warning 1). Both the unlock and the success line are confined to the
        # `if (refreshed)` branch, and the failure branch names the way out
        # instead of leaving the page locked with no explanation.
        if not attach_body:
            fail("(l) the attachToInFlightSwap body could not be read")
        else:
            settle = attach_body[
                attach_body.find("await refreshTiersFromServer();"):]
            guard_at = settle.find("if (refreshed)")
            gated = _js_braced_block(settle, guard_at) if guard_at != -1 else ""
            if guard_at == -1 or not gated:
                fail("(l) the attach completion does not gate its outcome on "
                     "the re-read's result (guard_at={}) — a failed re-read "
                     "would unlock the page and paint success over a tier row "
                     "one swap behind".format(guard_at))
            else:
                unlocked = settle.count("setSwapControlsDisabled(false)")
                unlocked_gated = gated.count("setSwapControlsDisabled(false)")
                painted = len(re.findall(
                    r"showStatus\(\s*['\"]success['\"]", settle))
                painted_gated = len(re.findall(
                    r"showStatus\(\s*['\"]success['\"]", gated))
                failure = _js_braced_block(
                    settle[settle.find(gated) + len(gated):], 0)
                problems = []
                if unlocked_gated < 1 or unlocked != unlocked_gated:
                    problems.append(
                        "the unlock is not confined to the successful re-read "
                        "({} past the re-read, {} inside `if (refreshed)`)"
                        .format(unlocked, unlocked_gated))
                if painted_gated < 1 or painted != painted_gated:
                    problems.append(
                        "the success line is not confined to the successful "
                        "re-read ({} past the re-read, {} inside `if "
                        "(refreshed)`)".format(painted, painted_gated))
                if "reload this page" not in failure:
                    problems.append(
                        "the failure branch does not tell the operator to "
                        "reload")
                if problems:
                    fail("(l) failed re-read handling: " + "; ".join(problems))
                else:
                    pass_("(l) a failed re-read stays locked, skips the "
                          "success line, and tells the operator to reload")

        # The reload path's stale-refusal handling, read ONCE for (m)-(o): the
        # branch, its `if (refreshed)` pair, the failure branch, and the
        # `finally`. server.py emits `config_reload_stale` only when a
        # concurrent switch COMPLETED between this reload's gated tier read and
        # its compare-and-install, so the row on screen is one swap behind BY
        # CONSTRUCTION — the one asymmetric survivor of Step 4(c)'s rule.
        #
        # Brace-balanced extraction, never a `(.*?)…} else` delimiter regex:
        # the branch legitimately CONTAINS a nested `} else` (the
        # `if (refreshed)` pair), and a non-greedy capture stops at that inner
        # delimiter — putting the failure path outside the capture and making
        # the probe unable to fire (issue step4-gate-stale-reload-stale-branch).
        # The discriminator is matched QUOTE-AGNOSTICALLY (review F4). Pinning
        # the exact single-quoted literal meant a behaviour-identical re-quote
        # blanked the extraction below, and the probe then failed with a
        # diagnosis that is not true ("the branch could not be read" when the
        # branch is right there). The module's other code-structure pins are
        # already quote-insensitive — (d), (g), (l) and (n) all match a quote
        # class — so this one matches that idiom.
        reload_body = _js_function_body(html, "async function reloadConfig(")
        stale_match = re.search(r"code\s*===\s*['\"]config_reload_stale['\"]",
                                reload_body)
        stale_branch = (_js_braced_block(reload_body, stale_match.start())
                        if stale_match else "")
        stale_guard_at = stale_branch.find("if (refreshed)")
        stale_gated = (_js_braced_block(stale_branch, stale_guard_at)
                       if stale_guard_at != -1 else "")
        stale_failure = (_js_braced_block(
            stale_branch[stale_branch.find(stale_gated) + len(stale_gated):], 0)
            if stale_gated else "")

        # (m) The stale-refusal branch RE-READS the tier row and gates its
        # outcome on the result. Step 4.5(a)'s first shape called
        # `refreshTiersFromServer()` as a bare statement, discarding the boolean
        # Step 4(a) added precisely so no caller could unlock on a failed
        # re-read — so a failed re-read still unlocked AND still claimed "the
        # tier list has been refreshed" over a row that may predate the swap.
        # This is the reload path's twin of (l).
        if not reload_body or not stale_branch:
            fail("(m) the config_reload_stale branch could not be read "
                 "(reloadConfig={}, branch={}) — the reload path's "
                 "stale-refusal handling is unguarded".format(
                     bool(reload_body), bool(stale_branch)))
        else:
            claimed = stale_branch.count("has been refreshed")
            claimed_gated = stale_gated.count("has been refreshed")
            problems = []
            if not re.search(r"const\s+refreshed\s*=\s*await\s+"
                             r"refreshTiersFromServer\(\)\s*;", stale_branch):
                problems.append(
                    "the re-read result is DISCARDED (no `const refreshed = "
                    "await refreshTiersFromServer();`) — the branch cannot "
                    "tell a successful re-read from a failed one")
            if stale_guard_at == -1 or not stale_gated:
                problems.append(
                    "the branch does not gate its outcome on the re-read (no "
                    "`if (refreshed)` pair)")
            elif claimed < 1 or claimed != claimed_gated:
                problems.append(
                    "the 'has been refreshed' claim is not confined to the "
                    "successful re-read ({} in the branch, {} inside `if "
                    "(refreshed)`)".format(claimed, claimed_gated))
            if problems:
                fail("(m) reload-stale re-read: " + "; ".join(problems))
            else:
                pass_("(m) the reload-stale branch captures the re-read result "
                      "and confines 'has been refreshed' to success")

        # (n) A FAILED re-read leaves the page LOCKED and says so: the failure
        # branch sets `reloadStaleUnresolved` (which the `finally` reads, see
        # (o)) and paints the STICKY "reload this page before applying" line —
        # never the success text — so the operator is not told that a row which
        # may still be one swap behind is truthful. Sticky matters here: a
        # terminal 5 s auto-hide would erase the only message explaining why
        # the switch surface is still locked.
        problems = []
        if not stale_failure:
            problems.append(
                "the failure branch could not be read (the `if (refreshed)` "
                "pair is missing or its else-branch is empty)")
        else:
            if not re.search(r"reloadStaleUnresolved\s*=\s*true\s*;",
                             stale_failure):
                problems.append("the failure branch does not set "
                                "reloadStaleUnresolved, so the finally below "
                                "still unlocks")
            if "reload this page before applying" not in stale_failure:
                problems.append("the failure branch does not tell the operator "
                                "to reload this page before applying")
            if "has been refreshed" in stale_failure:
                problems.append(
                    "the failure branch claims the tier list HAS been refreshed "
                    "— the exact defect Step 4.5(c) closed")
            if not re.search(
                    r"showStatus\(\s*['\"]pending['\"][^;]*?\btrue\s*\)",
                    stale_failure, re.S):
                problems.append("the failure line is not sticky — a terminal "
                                "5 s auto-hide would erase the one message "
                                "that says the page is still locked")
        if problems:
            fail("(n) reload-stale failure path: " + "; ".join(problems))
        else:
            pass_("(n) a failed reload-stale re-read sets the unresolved flag "
                  "and paints the sticky reload-this-page line")

        # (o) The `finally` HOLDS the lock when the re-read failed. The unlock
        # must be unreachable on that path — otherwise the operator is handed
        # an unlocked, stale, unlabelled surface whose next Apply writes the
        # pre-switch mapping back, which is the hazard this plan exists to
        # close. Both the guard's condition and the confinement of the unlock
        # are asserted, so neither an unconditional unlock nor a guard that
        # names the flag without consulting it passes.
        finally_at = reload_body.find("} finally {")
        reload_finally = (_js_braced_block(reload_body, finally_at)
                          if finally_at != -1 else "")
        hold = re.search(r"if\s*\(\s*attachPollHandle\s*===\s*null\s*&&\s*"
                         r"!reloadStaleUnresolved\s*\)", reload_finally)
        gated_unlock = (_js_braced_block(reload_finally, hold.start())
                        if hold else "")
        problems = []
        if not reload_finally:
            problems.append("reloadConfig's finally block could not be read")
        else:
            if not hold:
                problems.append(
                    "the finally's unlock is not gated on "
                    "reloadStaleUnresolved — a failed re-read hands back an "
                    "actionable stale surface")
            unlocked = reload_finally.count("setSwapControlsDisabled(false)")
            unlocked_gated = gated_unlock.count("setSwapControlsDisabled(false)")
            if unlocked < 1:
                problems.append(
                    "the finally never unlocks, so the switch surface would "
                    "stay locked after a successful swap")
            elif unlocked != unlocked_gated:
                problems.append(
                    "setSwapControlsDisabled(false) is reachable outside the "
                    "guarded branch ({} in the finally, {} inside the "
                    "guard)".format(unlocked, unlocked_gated))
        if problems:
            fail("(o) reload-stale unlock: " + "; ".join(problems))
        else:
            pass_("(o) the finally unlocks only when the stale re-read "
                  "succeeded")

        # (p) The attach watcher's `settled` bail gates the REPAINT, not just
        # the terminal path: it must sit between the post-await generation
        # re-check and the `if (!st.swapping)` branch. The generation guard
        # cannot cover this — it rejects only a NEWER attach, and no new attach
        # can arm while `attachPollHandle !== null` — so a tick whose response
        # was generated while the swap still ran but is delivered after a
        # sibling tick settled would otherwise repaint the sticky pending line
        # over the terminal line, with the interval already cleared and nothing
        # left to correct it (Step 4.5(b); the retired inner guard, Step
        # 4.5(d), was unreachable for the same reason).
        bail_at = attach_body.find("if (settled)")
        swap_branch_at = attach_body.find("if (!st.swapping)")
        if not attach_body:
            fail("(p) the attachToInFlightSwap body could not be read")
        elif bail_at == -1:
            fail("(p) the attach callback has no `if (settled)` bail — a tick "
                 "delivered after a sibling tick settled would repaint the "
                 "sticky pending line over the terminal line")
        elif swap_branch_at == -1:
            fail("(p) the attach callback has no `if (!st.swapping)` branch to "
                 "bail before")
        elif bail_at > swap_branch_at:
            fail("(p) the `if (settled)` bail sits AFTER the `!st.swapping` "
                 "branch (bail_at={} branch_at={}), so it cannot gate the "
                 "repaint".format(bail_at, swap_branch_at))
        else:
            pass_("(p) the attach watcher's settled bail precedes the "
                  "!st.swapping branch, gating the repaint")

        # The LOAD path's gate, read ONCE for (q)-(r). Step 4.6 landed the same
        # discipline (l) and (m)-(o) apply to the other two call sites;
        # `checkInFlightSwapOnLoad` was its last asymmetric survivor. Why it
        # matters here and not only there: the switch installs `_current_config`
        # AFTER the drain, so in the branch this code exists for the row on
        # screen is the PRE-swap document, and /admin/api/switch carries no
        # staleness guard — so leaving that row unlocked passes the operator's
        # next Apply straight back over the swap that just completed (review
        # F1, `review-final-load-path-re-read-unguarded`).
        load_body = _js_function_body(
            html, "async function checkInFlightSwapOnLoad(")
        reread_marker = "const refreshed = await refreshTiersFromServer();"
        reread_at = load_body.find(reread_marker)
        failure_at = (load_body.find("if (!refreshed)", reread_at + 1)
                      if reread_at != -1 else -1)
        load_failure = (_js_braced_block(load_body, failure_at)
                        if failure_at != -1 else "")
        # The three-condition press guard, as written at both of this
        # function's sites: the pre-fetch check Step 3 added, and the
        # post-await one Step 4.6 adds. Matched quote-agnostically on the
        # field's VALUE, with the identifier pinned by name.
        guard_pat = (r"if\s*\(\s*swapPollHandle\s*!==\s*null\s*\|\|\s*"
                     r"attachPollHandle\s*!==\s*null\s*\|\|\s*swapSettled\s*\)")
        guard_hits = [m.start() for m in re.finditer(guard_pat, load_body)]
        pre_guard = next((a for a in guard_hits
                          if reread_at != -1 and a < reread_at), -1)
        post_guard = next((a for a in guard_hits
                           if reread_at != -1 and a > reread_at), -1)
        post_guard_body = (_js_braced_block(load_body, post_guard)
                           if post_guard != -1 else "")

        # (q) The no-swap branch CAPTURES its re-read result and, on failure,
        # locks the surface, paints the sticky reload line, and RETURNS — so
        # the post-await guard below cannot run and hand the page back
        # unlocked. Every clause is load-bearing: a branch that paints without
        # locking leaves the row pressable; one that locks without returning
        # can be re-unlocked by the guard block it falls through to; and a
        # failure branch that claims "has been refreshed" tells the operator a
        # possibly-pre-swap row is truthful.
        problems = []
        if not load_body:
            problems.append("the checkInFlightSwapOnLoad body could not be read")
        else:
            if reread_at == -1:
                problems.append(
                    "the no-swap branch DISCARDS its re-read result (no `const "
                    "refreshed = await refreshTiersFromServer();`) — a failed "
                    "re-read leaves a possibly-pre-swap row unlocked and "
                    "pressable, and the next Apply writes that baseline back")
            if not load_failure:
                problems.append(
                    "no `if (!refreshed)` failure branch follows the re-read, "
                    "so a failed re-read falls through to the success path")
            else:
                if "setSwapControlsDisabled(true)" not in load_failure:
                    problems.append(
                        "the failure branch does not lock the switch surface")
                if "setSwapControlsDisabled(false)" in load_failure:
                    problems.append(
                        "the failure branch UNLOCKS the switch surface over a "
                        "row that may still predate the swap")
                if not re.search(
                        r"showStatus\(\s*['\"]pending['\"][^;]*?\btrue\s*\)",
                        load_failure, re.S):
                    problems.append(
                        "the failure line is not a sticky pending line — a "
                        "terminal 5 s auto-hide would erase the only message "
                        "explaining why the page is still locked")
                if "reload this page" not in load_failure:
                    problems.append(
                        "the failure branch does not tell the operator to "
                        "reload this page before applying")
                if "has been refreshed" in load_failure:
                    problems.append(
                        "the failure branch claims the tier list HAS been "
                        "refreshed over a row that may still be one swap behind")
                show_at = load_failure.find("showStatus")
                ret_at = load_failure.find("return")
                if ret_at == -1 or (show_at != -1 and ret_at < show_at):
                    problems.append(
                        "the failure branch does not RETURN after painting — "
                        "it falls through to the post-await guard block, which "
                        "is the re-unlock this gate exists to prevent")
        if problems:
            fail("(q) load-path gated re-read: " + "; ".join(problems))
        else:
            pass_("(q) the load path's failed re-read locks the surface, "
                  "paints the sticky reload line, and returns")

        # (r) The load path re-asserts the press guard AFTER its re-read await.
        # `refreshTiersFromServer()` calls `renderTiers()`, which rebuilds the
        # nine selects as fresh ENABLED nodes; a press that started inside that
        # one fetch window has therefore just had its select lock destroyed and
        # its in-progress edit re-rendered away. Without this re-check the load
        # path is the only re-render site that can unlock a press — every other
        # site either re-checks (the press paths, the attach watcher) or does
        # not re-render (the reload-stale branch). The pre-fetch check is
        # asserted present too, so the re-check cannot be satisfied by moving
        # the original guard past the await.
        problems = []
        if not load_body:
            problems.append("the checkInFlightSwapOnLoad body could not be read")
        else:
            if pre_guard == -1:
                problems.append(
                    "the pre-fetch press guard is gone — the load path no "
                    "longer defers to a press already in flight")
            if post_guard == -1:
                problems.append(
                    "no press-guard re-check AFTER the re-read await — "
                    "renderTiers() rebuilt the selects as fresh enabled nodes, "
                    "so a press that started inside that fetch has just had "
                    "its lock dropped and its edit re-rendered away")
            elif "setSwapControlsDisabled(true)" not in post_guard_body:
                problems.append(
                    "the post-await guard block does not re-lock the surface")
            elif "setSwapControlsDisabled(false)" in post_guard_body:
                problems.append(
                    "the post-await guard block UNLOCKS instead of re-locking")
        if problems:
            fail("(r) load-path post-await press-guard re-check: "
                 + "; ".join(problems))
        else:
            pass_("(r) the load path re-asserts the lock after its re-read "
                  "await while a press or an attach is in play")
    finally:
        cleanup()


# ===========================================================================
# The Apply press refuses on an incomplete view
# (plan 2026-10-25-guard-totality-and-blank-admin, Step 4)
# ===========================================================================

def _save_config_body(html):
    """saveConfig's body extracted by brace matching ('' when absent)."""
    return _js_function_body(html, "async function saveConfig(")


def _save_config_requires_rendered_row_checks(html):
    """Assertion rows for the unrendered-tier-row press guard.

    Returns [(ok, message), ...]. Kept separate from the test function so a
    measurement harness can run these same assertions against a pre-change page
    without starting a proxy — an assertion whose failing branch cannot be
    reached is not a test.
    """
    body = _save_config_body(html)
    if not body:
        return [(False, "saveConfig could not be read from the served page")]
    checks = []

    # The guard's semantic core: a NEGATED existence test on a tier provider
    # select. renderTiers() creates all nine selects or none, so testing any one
    # of them decides the question; the index is left loose rather than pinning
    # TIERS[0].
    row_guard = re.search(
        r"if\s*\(\s*!\s*document\.getElementById\(\s*"
        r"`\$\{TIERS\[\d+\]\}-provider`\s*\)\s*\)", body)
    if not row_guard:
        checks.append((False, (
            "saveConfig has no rendered-tier-row existence guard (a negated "
            "`document.getElementById(`${TIERS[n]}-provider`)` test) — on a "
            "blank page it dereferences a missing element and rejects with an "
            "unhandled TypeError instead of refusing")))
    else:
        checks.append((True, "saveConfig tests that a tier row was rendered"))

    # Before it TOUCHES any tier select. The earliest access in the press body
    # is the key-list guard's provider lookup, so comparing against it also
    # proves the row guard comes first. The matcher deliberately anchors on the
    # `getElementById(...)` CALL and not on a `.value` dereference: the guard
    # loop reads its select through a null-checked handle
    # (`const el = document.getElementById(...); if (!el) {...}; el.value`),
    # and an earlier version of this check matched only the direct-dereference
    # spelling. That version found nothing in the guard loop and anchored on a
    # LATER read — a PASS about a different position (coder-filed
    # `step10-el-handle-breaks-admin-html-row-guard-pin`). The property under
    # test is the ORDERING ("refuse before touching a select"), so both
    # spellings must count; the call is the earliest point either way.
    tier_reads = [m.start() for m in re.finditer(
        r"getElementById\(\s*`\$\{tier\}-(?:provider|model|key)`\s*\)", body)]
    build_at = body.find("newConfig.tiers[tier] = {")
    if not tier_reads:
        checks.append((False, (
            "saveConfig reads no tier select at all — the press body is not "
            "the one this test documents")))
    elif build_at == -1:
        checks.append((False, (
            "saveConfig no longer builds `newConfig.tiers[tier]` — the config "
            "build this ordering check is anchored on is missing")))
    elif row_guard:
        if row_guard.start() < tier_reads[0] < build_at:
            checks.append((True, (
                "the row guard precedes the first tier-select read and the "
                "config build")))
        else:
            checks.append((False, (
                "the row guard is not before the tier selects it protects "
                "(guard at {}, first read at {}, build at {})").format(
                    row_guard.start(), tier_reads[0], build_at)))

    # It must refuse rather than fall through: a return, and a STICKY line.
    # Sticky matters because there is no later repaint on this path — the page
    # never rendered, so nothing else will replace the message.
    if row_guard:
        block = _js_braced_block(body, row_guard.end())
        if not block:
            checks.append((False, "the row guard's block could not be read"))
        else:
            checks.append((bool(re.search(r"\breturn\b", block)), (
                "the row guard returns instead of falling through")))
            checks.append((bool(re.search(r"showStatus\s*\([^;]*,\s*true\s*\)",
                                          block)), (
                "the refusal line is sticky (third argument true)")))
    return checks


def _save_config_requires_key_list_checks(html):
    """Assertion rows for the missing-key-list press guard.

    Returns [(ok, message), ...], separate from the test function for the same
    reason as the row-guard helper.
    """
    body = _save_config_body(html)
    if not body:
        return [(False, "saveConfig could not be read from the served page")]
    checks = []

    # saveConfig carries two `for (const tier of TIERS)` loops (the guard and
    # the post-build validation), so the guard is identified by the lookup it
    # performs, not by being the first loop.
    guard_block = ""
    for match in re.finditer(r"for\s*\(\s*const\s+tier\s+of\s+TIERS\s*\)\s*\{",
                             body):
        block = _js_braced_block(body, match.start())
        if "providerKeys[provider]" in block:
            guard_block = block
            guard_at = match.start()
            break

    if not guard_block:
        checks.append((False, (
            "saveConfig has no per-tier key-list guard looping over TIERS and "
            "consulting `providerKeys[provider]` — when /providers-detail "
            "fails the row still renders with a disabled, empty key select, and "
            "the press sends key=\"\" which the server maps to the provider's "
            "FIRST key")))
        return checks

    checks.append((True, (
        "saveConfig consults providerKeys for every tier before applying")))
    checks.append((bool(re.search(r"\bprovider\s*&&", guard_block)), (
        "the guard skips tiers with no provider selected (an unset provider has "
        "no key list to check)")))
    checks.append((("providerKeys[provider]" in guard_block
                    and ".length" in guard_block), (
        "the guard tests the key list's LENGTH (an absent or empty entry is the "
        "failure condition)")))
    checks.append((bool(re.search(r"showStatus\s*\([^;]*,\s*true\s*\)",
                                  guard_block)), (
        "the refusal line is sticky (third argument true) — Reload Providers "
        "does not re-fetch provider-detail, so only a page reload clears it")))
    checks.append((bool(re.search(r"\breturn\b", guard_block)), (
        "the guard returns without POSTing /admin/api/switch")))

    # It must sit before the config build that reads the nine selects — a guard
    # after the build would refuse a press whose values were already collected.
    build_at = body.find("newConfig.tiers[tier] = {")
    if build_at == -1:
        checks.append((False, (
            "saveConfig no longer builds `newConfig.tiers[tier]` — the config "
            "build this ordering check is anchored on is missing")))
    else:
        checks.append((guard_at < build_at, (
            "the key-list guard precedes the config build")))
    return checks


def test_admin_html_apply_requires_rendered_row():
    """On a blank page the Apply press REFUSES instead of throwing.

    The initial load can fail before `renderTiers()` runs, so the nine tier
    `<select>`s do not exist. Both buttons stay pressable (deliberately: Reload
    Providers is the working recovery path). Before this plan, `saveConfig`
    dereferenced a missing element as its first statement — above its own `try`
    — so the `async` function rejected with an unhandled `TypeError` and painted
    no status line at all. Nothing else in the suite served the page and looked
    at this ordering, so a regression would have been silent.

    WHAT THIS PINS, AND WHAT IT DOES NOT: the served page's SOURCE ORDER — a
    negated tier-row existence test, before any tier-select read, whose block
    returns with a sticky error line. It does not execute the JavaScript; the
    behavioural contract was measured under Node (check 1 of the page-behaviour
    probe), which this repo deliberately does not make a suite dependency.
    """
    print("\n--- Test: Apply Requires a Rendered Row ---")
    port = find_free_port()
    tiers = _mode_tiers("p")
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(port), "key": "K"}}
    proxy_port, proc, mock_servers, temp_dir, cleanup = _start_admin_proxy(
        tiers, vendors)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        status, body, _ = _admin_get(proxy_port, "/admin/")
        if status != 200:
            fail("expected 200 for /admin/, got {}".format(status))
            return
        html = body.decode("utf-8", errors="replace")
        for ok, msg in _save_config_requires_rendered_row_checks(html):
            if ok:
                pass_(msg)
            else:
                fail(msg)
    finally:
        cleanup()


def test_admin_html_apply_requires_key_list():
    """Apply refuses when a tier's provider has no entry in `providerKeys`.

    `/providers-detail` supplies the key NAMES, and `loadProviderModes()`
    swallows a failed fetch by design — but `renderTiers()` still runs, so the
    row renders and the page looks normal. `populateKeys` then builds no options
    and disables the key select, and a disabled select still reads `""`. The
    server maps `""` to `names[0]` — the provider's FIRST key, not "unchanged" —
    so before this plan the press silently re-pointed every multi-key tier and
    persisted it while reporting success. Neither Reload Providers nor
    `refreshTiersFromServer` re-fetches provider-detail, so only a full page
    reload clears the state.

    WHAT THIS PINS, AND WHAT IT DOES NOT: the served page's source ordering and
    shape — a per-tier `providerKeys[provider]` length test, before the config
    build, that returns with a sticky error line. Runtime behaviour is pinned by
    the Node-driven verification script's check 2, not here.
    """
    print("\n--- Test: Apply Requires the Key List ---")
    port = find_free_port()
    tiers = _mode_tiers("p")
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(port), "key": "K"}}
    proxy_port, proc, mock_servers, temp_dir, cleanup = _start_admin_proxy(
        tiers, vendors)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        status, body, _ = _admin_get(proxy_port, "/admin/")
        if status != 200:
            fail("expected 200 for /admin/, got {}".format(status))
            return
        html = body.decode("utf-8", errors="replace")
        for ok, msg in _save_config_requires_key_list_checks(html):
            if ok:
                pass_(msg)
            else:
                fail(msg)
    finally:
        cleanup()


def _load_config_guard_checks(html):
    """Assertion rows for `loadConfig`'s /admin/api/config status guard.

    Returns [(ok, message), ...]. Separate from the test function for the same
    reason as the row-guard helper: a measurement harness can run these same
    assertions against a pre-change page without starting a proxy — an
    assertion whose failing branch cannot be reached is not a test.

    JS line comments are stripped before every needle. The mandated guard
    comment names both `renderTiers()` and `errorText(` ABOVE the status check,
    so a raw-text find matches prose and reports the ordering backwards — the
    exact collision that made the plan's own Step 1 gate unpassable
    (issue step1-gate-rendertiers-comment-collision).
    """
    body = _js_function_body(html, "async function loadConfig(")
    if not body:
        return [(False, "loadConfig could not be read from the served page")]
    code = "\n".join(ln for ln in body.splitlines()
                     if not ln.strip().startswith("//"))
    checks = []

    ok_at = code.find("configResp.ok")
    checks.append((ok_at != -1, (
        "loadConfig tests the /admin/api/config response status "
        "(`configResp.ok`) before using the body — a non-OK body is still "
        "valid JSON, so without the guard `config` becomes {error: ...}, "
        "renderTiers() throws a TypeError on the missing tiers, and the "
        "operator sees the page's generic message instead of the server's "
        "diagnostic")))
    if ok_at == -1:
        return checks

    # The assignment, not any mention: `const configResult =` and
    # `const [configResp, ...]` must not satisfy this anchor.
    assign = re.search(r"(?m)^\s*config\s*=", code)
    checks.append((assign is not None and ok_at < assign.start(), (
        "the status guard precedes the `config =` assignment — the error "
        "document must never become the page's config")))
    render_at = code.find("renderTiers()")
    checks.append((-1 not in (ok_at, render_at) and ok_at < render_at, (
        "the status guard precedes renderTiers() — the tiers-less error body "
        "must never reach the renderer")))

    block = _js_braced_block(code, ok_at)
    if not block:
        checks.append((False, "the non-OK branch's block could not be read"))
        return checks
    checks.append(("errorText(" in block, (
        "the non-OK branch surfaces the server's message via errorText( — the "
        "same contract as the page's save and reload paths")))
    checks.append(("showStatus('error'" in block, (
        "the non-OK branch paints an error status line")))
    checks.append((bool(re.search(r"\breturn\b", block)), (
        "the non-OK branch returns rather than falling through into the "
        "success path")))
    # Source-shape pin only (reachability of the load-time swap lock is a
    # runtime property the page has no harness for): the guard must preserve
    # the call AND its `return` must keep the tail call from firing a second
    # time on this path.
    checks.append((block.count("checkInFlightSwapOnLoad(") == 1, (
        "the non-OK branch preserves exactly one checkInFlightSwapOnLoad() "
        "call (found {}) — dropping it unarms the in-flight-swap lock on a "
        "failed load".format(block.count("checkInFlightSwapOnLoad(")))))
    return checks


def test_admin_html_load_config_status_guard():
    """The served page's `loadConfig` refuses a non-OK /admin/api/config body.

    Since the endpoint can legitimately answer `500 {"error": "the
    configuration could not be serialized"}`, the page parsed it and set the
    global `config` to that tiers-less document, so `renderTiers()` threw a
    `TypeError` and the failing-load path showed its own generic message
    (plan 2026-11-01-admin-config-500-surface; adopting
    defer-issue-admin-page-loadconfig-ignores-response-ok).

    WHAT THIS PINS, AND WHAT IT DOES NOT: the served page's SOURCE shape —
    a `configResp.ok` test inside `loadConfig`, ordered before the `config =`
    assignment and before `renderTiers()`, whose non-OK branch paints an error
    line carrying `errorText(`, keeps its single `checkInFlightSwapOnLoad()`
    call, and returns. It does not execute the JavaScript; the suite is pure
    Python and has no page harness. Deleting the guard fails this test; nothing
    else in the suite would notice.
    """
    print("\n--- Test: Admin HTML Config Load Status Guard ---")
    port = find_free_port()
    tiers = _mode_tiers("p")
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(port), "key": "K"}}
    proxy_port, proc, mock_servers, temp_dir, cleanup = _start_admin_proxy(
        tiers, vendors)
    if proc is None:
        fail("Failed to set up test")
        return
    try:
        status, body, _ = _admin_get(proxy_port, "/admin/")
        if status != 200:
            fail("expected 200 for /admin/, got {}".format(status))
            return
        html = body.decode("utf-8", errors="replace")
        for ok, msg in _load_config_guard_checks(html):
            if ok:
                pass_(msg)
            else:
                fail(msg)
    finally:
        cleanup()


ALL_TESTS = [
    ("admin-html-poll-guard-after-await",
     test_admin_html_poll_guard_after_await),
    ("admin-html-pending-status-styled",
     test_admin_html_pending_status_styled),
    ("admin-html-apply-requires-rendered-row",
     test_admin_html_apply_requires_rendered_row),
    ("admin-html-apply-requires-key-list",
     test_admin_html_apply_requires_key_list),
    ("admin-html-load-config-status-guard",
     test_admin_html_load_config_status_guard),
]


if __name__ == "__main__":
    run_cli(ALL_TESTS, "claude-retry-proxy tests: test_admin_html")
