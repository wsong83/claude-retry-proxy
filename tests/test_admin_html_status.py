"""The status-stack repaint contract on the served admin page.

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
from test_admin_html import _js_braced_block, _js_function_body
import re


# ===========================================================================
# Status-stack model (plan 2026-11-01-admin-config-500-surface, Step 5)
#
# The page's status area is a STACK, not a single line: failures accumulate
# newest-on-top, a success clears the stack and shows only itself, a keyed
# ticking wait line is moved to the top on every repaint instead of growing the
# stack, an identical unkeyed repaint updates in place, a sticky entry never
# expires, and every keyed entry has an exit (removeStatusKey from a press's
# `finally`).
#
# WHAT THESE PIN, AND WHAT THEY DO NOT: the served page's SOURCE SHAPE,
# extracted per function with the module's brace-balanced walker. This suite is
# pure Python and has no page harness (test_admin_html_pending_status_styled
# records the same boundary). The behaviour those shapes produce was MEASURED
# separately, by running the shipped script under a stub DOM in Node, driving
# showStatus directly, and proving each row below has a reachable failing
# branch by mutating exactly one property at a time.
# ===========================================================================

def _served_admin_page():
    """`(html, cleanup)` for `GET /admin/` on a minimal started proxy.

    `(None, None)` when the proxy could not be started — the caller reports the
    setup failure and returns. Same tier/vendor fixtures as its neighbours.
    """
    port = find_free_port()
    tiers = _mode_tiers("p")
    vendors = {"p": {"url": "http://127.0.0.1:{}".format(port), "key": "K"}}
    proxy_port, proc, mock_servers, temp_dir, cleanup = _start_admin_proxy(
        tiers, vendors)
    if proc is None:
        return None, None
    try:
        status, body, _ = _admin_get(proxy_port, "/admin/")
    except Exception:
        cleanup()
        raise
    if status != 200:
        cleanup()
        return None, None
    return body.decode("utf-8", errors="replace"), cleanup


def _status_fn(html, header):
    """A page function's body with whole-line `//` comments stripped ('' if absent).

    Stripping is load-bearing rather than cosmetic: the stack block's own
    comments name the tokens these checks look for, and the plan's Step 1 gate
    failed for a whole round by matching prose above the code instead of the
    code (issue step1-gate-rendertiers-comment-collision). Line comments only —
    the functions pinned here carry no trailing comments.
    """
    body = _js_function_body(html, header)
    if not body:
        return ""
    return "\n".join(ln for ln in body.splitlines()
                     if not ln.strip().startswith("//"))


def _status_success_block(show):
    """The braced block of showStatus's `type === 'success'` branch ('' if absent)."""
    m = re.search(r"if\s*\(\s*type\s*===\s*'success'\s*\)", show)
    if not m:
        return ""
    return _js_braced_block(show, m.start())


def _finally_block(body):
    """A JS function body's first `finally` block ('' if absent)."""
    m = re.search(r"\bfinally\b", body)
    if not m:
        return ""
    return _js_braced_block(body, m.start())


def _attach_terminal_branch(body):
    """The `else` block of attachToInFlightSwap's `if (refreshed)` ('' if absent).

    That `else` is the watcher's terminal failed-re-read state: the tier row
    could not be re-read (a 500 on `/admin/api/config`, or a fetch throw), the
    page stays locked, and nothing repaints the keyed wait line again — so it is
    the branch that must retire that entry itself.
    """
    m = re.search(r"if\s*\(\s*refreshed\s*\)", body)
    if not m:
        return ""
    if_block = _js_braced_block(body, m.start())
    if not if_block:
        return ""
    after = body.find(if_block, m.start()) + len(if_block)
    em = re.search(r"\belse\b", body[after:])
    if not em:
        return ""
    return _js_braced_block(body, after + em.end() - 1)


def _status_stack_failure_checks(html):
    """Rows for (a): a second failure stacks, and BOTH lines are rendered.

    The warning scenario this models: `/admin/api/config` answers 500, the guard
    paints the server's diagnostic, and the load-time swap probe's re-read fails
    too and paints its own line — with a single-line status the operator never
    sees the first message at all.
    """
    show = _status_fn(html, "function showStatus(")
    if not show:
        return [(False, "showStatus could not be read from the served page")]
    checks = []
    checks.append((bool(re.search(r"statusEntries\.unshift\(", show)), (
        "a failure is INSERTED at the top of the stack (`statusEntries.unshift(`) "
        "rather than assigned as the only entry — assignment is the single-line, "
        "last-write-wins behaviour the stack replaces, so the earlier diagnostic "
        "would vanish")))
    success = _status_success_block(show)
    checks.append((bool(success) and "statusEntries = []" in success, (
        "the success branch is where the stack is emptied (`statusEntries = []` "
        "inside `type === 'success'`)")))
    outside = show.replace(success, "") if success else show
    checks.append((not re.search(r"statusEntries\s*=(?!=)", outside), (
        "the failure arm never REASSIGNS `statusEntries` — a reassignment "
        "outside the success branch is a last-write-wins regression wearing the "
        "stack's variable name")))
    render = _status_fn(html, "function renderStatus(")
    checks.append((bool(render) and "statusEntries.forEach(" in render, (
        "the renderer paints EVERY stacked entry (`statusEntries.forEach(`) — "
        "painting one entry is the single-line behaviour this model replaces")))
    checks.append((bool(render) and "appendChild(" in render
                   and "createElement(" in render
                   and not re.search(r"\b(?:reverse|sort)\(", render), (
        "each entry becomes its own element, appended in stack order, so the "
        "newest (index 0) renders first, at the top — with no re-sort and no "
        "reverse that would put the oldest message on top")))
    return checks


def _status_stack_success_checks(html):
    """Rows for (b): a success call clears the stack and shows only itself."""
    show = _status_fn(html, "function showStatus(")
    if not show:
        return [(False, "showStatus could not be read from the served page")]
    success = _status_success_block(show)
    checks = []
    checks.append((bool(success) and "statusEntries = []" in success, (
        "a success call EMPTIES the stack (`statusEntries = []` in the success "
        "branch) — without it stale failures stay on screen under a line that "
        "says everything worked")))
    reset_at = show.find("statusEntries = []")
    insert_at = show.find("statusEntries.unshift(")
    checks.append((reset_at != -1 and insert_at != -1 and reset_at < insert_at, (
        "the emptying happens BEFORE the success entry is inserted — a reset "
        "after the insert would discard the success line itself")))
    checks.append((bool(success) and "clearTimeout(" in success, (
        "the cleared entries' pending expiries are cancelled before the stack is "
        "emptied — a timer must not outlive the entry it would remove")))
    return checks


def _status_stack_keyed_repaint_checks(html):
    """Rows for (c): a keyed tick repaint pins to the top and does not grow."""
    show = _status_fn(html, "function showStatus(")
    if not show:
        return [(False, "showStatus could not be read from the served page")]
    checks = []
    checks.append(("e.key === key" in show, (
        "a repaint looks an existing entry up BY KEY (`e.key === key`) — the "
        "1 Hz wait line must update in place, not add one line per second")))
    checks.append(("key !== null && e.key === key" in show, (
        "the keyed lookup is scoped to keyed paints (`key !== null &&` first) — "
        "unscoped, every unkeyed paint matches unkeyed entries by `null === null` "
        "whatever their text, and unrelated failures collapse into one")))
    reuse_at = show.find("if (reuseAt !== -1)")
    splice_at = show.find("statusEntries.splice(reuseAt, 1)")
    insert_at = show.find("statusEntries.unshift(")
    checks.append((reuse_at != -1 and splice_at != -1 and insert_at != -1
                   and reuse_at < splice_at < insert_at, (
        "on a hit the OLD entry is spliced out before the new one is inserted "
        "(`if (reuseAt !== -1)` then `splice(reuseAt, 1)` then `unshift`) — "
        "without the splice the moved entry leaves a duplicate behind and the "
        "stack grows on every tick")))
    total = len(re.findall(r"showStatus\(\s*'pending',\s*swapWaitText\(", html))
    keyed = len(re.findall(
        r"showStatus\(\s*'pending',\s*swapWaitText\([^()]*\),\s*true,\s*"
        r"'(?:swap-wait|attach-wait)'\)", html))
    checks.append((total > 0 and keyed == total, (
        "every ticking wait paint carries its key as the fourth argument "
        "({} of {} do) — an unkeyed tick takes the unkeyed arm and stacks a new "
        "line every second".format(keyed, total))))
    return checks


def _status_stack_dedupe_checks(html):
    """Rows for (d): an identical unkeyed repaint updates in place."""
    show = _status_fn(html, "function showStatus(")
    if not show:
        return [(False, "showStatus could not be read from the served page")]
    checks = []
    norm_at = show.find("if (key === undefined) { key = null; }")
    success_at = show.find("type === 'success'")
    checks.append((norm_at != -1 and success_at != -1 and norm_at < success_at, (
        "the omitted key is normalised to `null` before any branch "
        "(`if (key === undefined) { key = null; }`) — an `undefined` key is "
        "stored as-is and silently defeats the unkeyed comparisons below, so the "
        "model degrades to last-write-wins in the one arm that matters here "
        "(issue step4-showstatus-undefined-key-collision)")))
    checks.append(("e.key === null && e.text === message" in show, (
        "the unkeyed match requires BOTH `e.key === null` and "
        "`e.text === message` — without the text clause every unkeyed paint "
        "reuses the topmost unkeyed slot and distinct failures stop stacking; "
        "without the key clause an unkeyed paint splices out a KEYED entry that "
        "happens to carry the same text")))
    return checks


def _status_stack_sticky_checks(html):
    """Rows for (e): the load-failure lines are sticky, and sticky is honoured."""
    show = _status_fn(html, "function showStatus(")
    load = _status_fn(html, "async function loadConfig(")
    checks = []
    checks.append((bool(re.search(
        r"showStatus\(\s*'error',\s*'Failed to load config: '\s*\+\s*"
        r"errorText\(configResult\),\s*true\)", load)), (
        "the load-failure guard line is STICKY (its third argument is `true`) — "
        "it must persist until a success clears the stack or the page reloads; a "
        "5 s expiry drops the server's diagnostic while the operator is still "
        "reading it")))
    checks.append((bool(re.search(
        r"showStatus\(\s*'error',\s*'Failed to load config: '\s*\+\s*"
        r"e\.message,\s*true\)", load)), (
        "the failing-load catch paint is sticky too — a thrown load is the same "
        "`this page cannot be configured` terminal state")))
    checks.append((bool(show) and bool(re.search(r"if\s*\(\s*!sticky\s*\)", show)), (
        "showStatus arms an expiry ONLY for non-sticky entries (`if (!sticky)`) — "
        "without it the sticky flag is inert and every line, including the "
        "guard's, fades after 5 s")))
    return checks


def _status_stack_keyed_removal_checks(html):
    """Rows for (f): the keyed-entry dead-end regression.

    The failure this pins, measured under Node by the round that specified the
    stack: a press paints the sticky keyed `applying — …` line, the press then
    fails terminally, and nothing repaints the keyed entry or clears it — no
    repaint, no success, no timer. It survives every other line's expiry and
    becomes the page's only, permanently false status. The exit is a keyed
    removal in each press handler's `finally`.

    The same dead-end on the attach family (review round 2, measured): a 409
    hand-off starts the watcher, the swap ends, and the tier re-read fails — the
    watcher paints its terminal line and returns, leaving the frozen keyed
    `… waiting for N in-flight request(s) … (no need to refresh …)` line above
    it for the life of the page. The watcher's terminal branch must therefore
    remove its own keyed entry before it paints.
    """
    rm = _status_fn(html, "function removeStatusKey(")
    checks = []
    checks.append((bool(rm) and "findIndex" in rm and "e.key === key" in rm, (
        "removeStatusKey looks the entry up BY KEY (`findIndex(... e.key === "
        "key)`) — removal must not touch the attach family's lines")))
    checks.append((bool(rm) and "statusEntries.splice(" in rm
                   and "renderStatus()" in rm, (
        "removeStatusKey splices the entry out AND repaints — a removal that "
        "leaves the DOM alone keeps showing the frozen line")))
    checks.append((bool(rm) and "clearTimeout(" in rm, (
        "removeStatusKey cancels the entry's pending expiry before splicing it "
        "out, so no timer fires against the removed entry")))
    for header, name, catch_literal in (
            ("async function saveConfig(", "saveConfig",
             "showStatus('error', 'Failed to save: ' + e.message);"),
            ("async function reloadConfig(", "reloadConfig",
             "showStatus('error', 'Failed to reload providers: ' + e.message);")):
        body = _status_fn(html, header)
        if not body:
            checks.append((False, "{} could not be read from the served "
                                  "page".format(name)))
            continue
        fin = _finally_block(body)
        checks.append((bool(fin) and "removeStatusKey('swap-wait')" in fin, (
            "{}'s `finally` removes the keyed 'swap-wait' entry "
            "unconditionally — the only exit for a press that reaches a terminal "
            "state without a repaint or a success".format(name))))
        checks.append((
            "showStatus('error', 'Error: ' + errorText(result));" in body, (
                "{}'s terminal failure line is unkeyed and NON-sticky, so it "
                "expires on its own — with the keyed wait line already removed "
                "the status area ends EMPTY rather than frozen on either "
                "line".format(name))))
        checks.append((catch_literal in body, (
            "{}'s network-failure catch line is unkeyed and non-sticky for the "
            "same reason".format(name))))

    attach = _status_fn(html, "function attachToInFlightSwap(")
    if not attach:
        checks.append((False, "attachToInFlightSwap could not be read from the "
                              "served page"))
        return checks
    removal = "removeStatusKey('attach-wait')"
    branch = _attach_terminal_branch(attach)
    checks.append((attach.count(removal) == 1, (
        "the attach watcher removes its keyed 'attach-wait' entry exactly once "
        "(`{}`) — without an exit the frozen '… waiting for N in-flight "
        "request(s) … (no need to refresh …)' line outlives the terminal line "
        "it sits above".format(removal))))
    checks.append((bool(branch) and removal in branch, (
        "that removal lives in the watcher's terminal failed-re-read `else` "
        "branch (the `refreshed` false arm) — the one exit path that neither "
        "repaints nor succeeds")))
    first = branch.lstrip()
    first = first[1:].lstrip() if first.startswith("{") else first
    checks.append((first.startswith(removal), (
        "the removal is that branch's FIRST statement — the keyed line must be "
        "gone before the terminal line lands, not after it")))
    checks.append((bool(branch) and removal in branch
                   and branch.find(removal) < branch.find("showStatus("), (
        "the removal precedes the branch's terminal paint ("
        "`showStatus('pending', prefix + 'the config could not be re-read …')`) "
        "— a removal after the paint would leave the frozen line beneath a "
        "message that says the page is waiting on nothing")))
    return checks


def _run_status_stack_checks(checks, label):
    for ok, msg in checks:
        if ok:
            pass_(msg)
        else:
            fail("[{}] {}".format(label, msg))


def test_admin_html_status_stack_failures():
    """(a) Two failures leave BOTH lines rendered, newest first.

    Plan 2026-11-01-admin-config-500-surface, Step 5. Pins the source shape that
    produces the stack: newest-on-top insert, no reassignment outside the
    success branch, and a renderer that paints every entry in stack order. The
    runtime behaviour is measured by the Step 5 verification script under Node.
    """
    print("\n--- Test: Admin HTML Status Stack - Failures Stack ---")
    html, cleanup = _served_admin_page()
    if html is None:
        fail("Failed to set up test")
        return
    try:
        _run_status_stack_checks(_status_stack_failure_checks(html), "a")
    finally:
        cleanup()


def test_admin_html_status_stack_success_clears():
    """(b) A success call clears the stack and shows only the success line."""
    print("\n--- Test: Admin HTML Status Stack - Success Clears ---")
    html, cleanup = _served_admin_page()
    if html is None:
        fail("Failed to set up test")
        return
    try:
        _run_status_stack_checks(_status_stack_success_checks(html), "b")
    finally:
        cleanup()


def test_admin_html_status_stack_keyed_repaint():
    """(c) A keyed tick repaint pins to the top and does not grow the stack."""
    print("\n--- Test: Admin HTML Status Stack - Keyed Repaint ---")
    html, cleanup = _served_admin_page()
    if html is None:
        fail("Failed to set up test")
        return
    try:
        _run_status_stack_checks(_status_stack_keyed_repaint_checks(html), "c")
    finally:
        cleanup()


def test_admin_html_status_stack_unkeyed_dedupe():
    """(d) Re-painting an identical unkeyed message does not duplicate it."""
    print("\n--- Test: Admin HTML Status Stack - Unkeyed Dedupe ---")
    html, cleanup = _served_admin_page()
    if html is None:
        fail("Failed to set up test")
        return
    try:
        _run_status_stack_checks(_status_stack_dedupe_checks(html), "d")
    finally:
        cleanup()


def test_admin_html_status_stack_sticky():
    """(e) The sticky guard line carries `true`, and sticky suppresses expiry."""
    print("\n--- Test: Admin HTML Status Stack - Sticky Guard Line ---")
    html, cleanup = _served_admin_page()
    if html is None:
        fail("Failed to set up test")
        return
    try:
        _run_status_stack_checks(_status_stack_sticky_checks(html), "e")
    finally:
        cleanup()


def test_admin_html_status_stack_keyed_removal():
    """(f) The keyed-entry dead-end: every keyed wait paint has an exit.

    Pins that both press handlers remove the keyed 'swap-wait' entry
    unconditionally in `finally`, that the attach watcher's terminal
    failed-re-read branch removes its own 'attach-wait' entry before painting
    its terminal line, that the removal is keyed and repaints, and that the
    terminal failure lines are unkeyed and non-sticky — so a failed Apply ends
    with an EMPTY status area, never the frozen `applying — …` line, and a
    failed attach re-read ends with the terminal line alone, never the frozen
    `… waiting for N in-flight request(s) …` line above it.
    """
    print("\n--- Test: Admin HTML Status Stack - Keyed Removal ---")
    html, cleanup = _served_admin_page()
    if html is None:
        fail("Failed to set up test")
        return
    try:
        _run_status_stack_checks(_status_stack_keyed_removal_checks(html), "f")
    finally:
        cleanup()


ALL_TESTS = [
    ("admin-html-status-stack-failures",
     test_admin_html_status_stack_failures),
    ("admin-html-status-stack-success-clears",
     test_admin_html_status_stack_success_clears),
    ("admin-html-status-stack-keyed-repaint",
     test_admin_html_status_stack_keyed_repaint),
    ("admin-html-status-stack-unkeyed-dedupe",
     test_admin_html_status_stack_unkeyed_dedupe),
    ("admin-html-status-stack-sticky", test_admin_html_status_stack_sticky),
    ("admin-html-status-stack-keyed-removal",
     test_admin_html_status_stack_keyed_removal),
]


if __name__ == "__main__":
    run_cli(ALL_TESTS, "claude-retry-proxy tests: test_admin_html_status")
