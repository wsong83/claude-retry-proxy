"""Spawn-isolation corpus checker tests: scripts/check_spawn_isolation.py.

WHY THIS EXISTS. Standalone verification scripts (``tmp/verification/*.py``)
spawn throwaway proxy children outside the test suite. The suite isolates its
children because ``_harness`` sets ``PROXY_STATE_FILE``, ``PROXY_TRACE_FILE``
and ``PROXY_FEATURE_COMPAT_FILE`` at import, before ``cli.py``/``server.py``
are imported; a standalone script does not, so the child it spawns inherits
the live paths and can write to — or delete — the live ``~/.claude/proxy``
state document. The committed checker enforces the authoring-time rule (the
canonical block, documented in ``doc/test-catalog.html#pattern-spawn-isolation``)
and this module is its regression net.

WHAT THE CASES PIN.

* Teeth (case 1) is RED calibration: seven non-compliant spawners, each
  violated check reached by exactly one fixture, so a checker that stops
  checking anything cannot stay green here.
* Satisfiability (case 2) is the other half of teeth: the canonical block —
  copied verbatim from the plan — must PASS, or the gate is unsatisfiable and
  every author is forced into the exemption marker. Its fixture carries a real
  top-level proxy import after the block, so the import comparator is actually
  exercised rather than vacuous.
* Cases 3 and 12 pin the two SKIP classification branches (import-only,
  spawn-only) so the false-positive surface is visible rather than enforced.
* Cases 4-6 pin the exemption marker (state-anchored: it never waives the
  mkdtemp derivation, the ``PROXY_STATE_FILE`` assignment or the ordering
  rule — each with its own exempt-teeth fixture), the deliberate raw-text
  overflag, and the encoding-defect path.
* Cases 7-11 pin the root/bad-path lattice, the live-corpus hook, self-scan
  identity, the unreadable-directory fault, and the quarantine prune.

NON-HERMETIC BY DESIGN (case 8). The corpus hook scans the live gitignored
``tmp/verification`` workspace, so a non-compliant script authored by any
round fails this plan's tester round — that is the enforcement mechanism, not
an accident. The checker's single delayed re-read mitigates the torn-read
race; a vanished file is a benign SKIP.

Every fixture is synthetic, built in this test's own temp space — never inside
``tmp/`` — and every checker invocation carries ``errors=\"replace\"`` and an
explicit ``timeout``, so a hang is a loud FAIL naming the case rather than a
stuck suite.

Part of the claude-retry-proxy suite; runnable standalone.
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile

from _harness import (
    fail,
    info,
    pass_,
    run_cli,
)


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHECKER_PATH = os.path.join(REPO_ROOT, "scripts", "check_spawn_isolation.py")
CORPUS_DIR = os.path.join(REPO_ROOT, "tmp", "verification")

# A checker invocation is a local text scan; 120 s is a ceiling that can only
# be reached by a fault (never by a slow machine), and it turns that fault into
# a named FAIL instead of a wedged suite.
CAPTURE_TIMEOUT = 120

# The canonical compliant block, verbatim from the plan's single source of
# truth. Case 2 builds its GREEN fixture from it; taste for the checker's
# satisfiability depends on this staying byte-identical, so edits here must be
# matched in doc/test-catalog.html#pattern-spawn-isolation.
CANON_BLOCK = '''import atexit
import os
import shutil
import tempfile

# Spawned or imported proxy code must never touch live runtime state. These
# three overrides must execute BEFORE the first `import claude_retry_proxy`
# line AND before the first process spawn: settings.py binds ALL THREE paths
# from the environment at import (state, trace, and compat — the sinks are
# configured from SETTINGS at import), and a spawned child inherits the env
# it is forked with.
_ISOLATION_DIR = tempfile.mkdtemp(prefix="proxy-probe-")
os.environ["PROXY_STATE_FILE"] = os.path.join(_ISOLATION_DIR, "state.json")
os.environ["PROXY_TRACE_FILE"] = os.path.join(_ISOLATION_DIR, "trace.jsonl")
os.environ["PROXY_FEATURE_COMPAT_FILE"] = os.path.join(_ISOLATION_DIR, "feature-compat.json")
# Best-effort cleanup once this script exits (children are waited on first):
atexit.register(shutil.rmtree, _ISOLATION_DIR, True)
'''

# A spawn call carrying a launch token, so a fixture that also carries a spawn
# API token classifies as a spawner and reaches the compliance checks instead
# of a SKIP branch.
SPAWN_LINE = (
    'subprocess.run([sys.executable, "-m", "claude_retry_proxy.server",\n'
    '                "--port", "0"], check=False)\n'
)

SUMMARY_RE = re.compile(r"^check_spawn_isolation: root=(.*?) \|")


# ---------------------------------------------------------------------------
# Fixture and invocation helpers
# ---------------------------------------------------------------------------

def _write(path, text):
    """Write fixture text as UTF-8/LF — the checker reads utf-8-sig."""
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def _write_bytes(path, data):
    """Write raw fixture bytes (encoding cases)."""
    with open(path, "wb") as fh:
        fh.write(data)


def _run(case, args, cwd=None):
    """Run the checker; a timeout is a loud FAIL naming the case, never a hang."""
    try:
        return subprocess.run(
            [sys.executable, CHECKER_PATH] + list(args),
            cwd=cwd,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=CAPTURE_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        fail("%s: checker timed out after %ds" % (case, CAPTURE_TIMEOUT))
        return None


def _lines(stdout, prefix):
    return [ln for ln in stdout.splitlines() if ln.startswith(prefix)]


def _summary_line(stdout):
    for line in stdout.splitlines():
        if line.startswith("check_spawn_isolation: "):
            return line
    return None


def _fixture_dir(base, name):
    path = os.path.join(base, name)
    os.makedirs(path, exist_ok=True)
    return path


# ---------------------------------------------------------------------------
# Case 1: teeth (RED calibration, seven fixtures)
# ---------------------------------------------------------------------------

def _teeth_fixtures():
    """(label, filename, text, required substrings, forbidden substrings).

    Each of the seven fixtures reaches a DIFFERENT compliance violation, so a
    checker that silently stops evaluating one of them goes red here.
    """
    header = "".join("# comment filler line %02d\n" % n for n in range(1, 26))
    return [
        # (a) none of the three env assignments: the presence checks.
        ("a-no-block", "no_block.py",
         'import subprocess\nimport sys\n\n' + SPAWN_LINE,
         ("_ISOLATION_DIR", "PROXY_STATE_FILE", "PROXY_TRACE_FILE",
          "PROXY_FEATURE_COMPAT_FILE"),
         ()),
        # (b) state hardcoded to the LIVE path, unrelated mkdtemp: shape check.
        ("b-live-state", "live_state.py",
         'import os\nimport subprocess\nimport sys\nimport tempfile\n\n'
         '_SCRATCH = tempfile.mkdtemp(prefix="scratch-")\n'
         'os.environ["PROXY_STATE_FILE"] = os.path.expanduser(\n'
         '    "~/.claude/proxy/proxy-state.json")\n' + SPAWN_LINE,
         ("PROXY_STATE_FILE is not assigned",),
         ()),
        # (c) ordering, import side: the complete block sits after the import.
        ("c-order-import", "order_import.py",
         'import claude_retry_proxy.server as proxy_server\n\n'
         + CANON_BLOCK + "\n" + SPAWN_LINE,
         ("ordering", "must precede the first", "claude_retry_proxy import"),
         ("spawn-API token",)),
        # (d) ordering, split shape: state before the import, trace + compat
        # after it. An earliest-offset comparator would wrongly pass this.
        ("d-order-split", "order_split.py",
         'import os\nimport sys\nimport tempfile\n\n'
         '_ISOLATION_DIR = tempfile.mkdtemp(prefix="proxy-probe-")\n'
         'os.environ["PROXY_STATE_FILE"] = os.path.join(_ISOLATION_DIR, "state.json")\n'
         'import claude_retry_proxy.server as proxy_server\n'
         'os.environ["PROXY_TRACE_FILE"] = os.path.join(_ISOLATION_DIR, "trace.jsonl")\n'
         'os.environ["PROXY_FEATURE_COMPAT_FILE"] = os.path.join(\n'
         '    _ISOLATION_DIR, "feature-compat.json")\n' + SPAWN_LINE,
         ("ordering", "claude_retry_proxy import"),
         ("spawn-API token",)),
        # (e) ordering, spawn side: the block is complete but sits after the
        # spawn; no in-process import, so only the spawn comparator can fire.
        # The message names the boundary token it actually matched.
        ("e-order-spawn", "order_spawn.py",
         'import subprocess\nimport sys\n\n' + SPAWN_LINE + "\n" + CANON_BLOCK,
         ("ordering", "spawn-API token (subprocess.run)"),
         ("claude_retry_proxy import",)),
        # (f) ordering, comment-skew shape: a large `#` header plus interleaved
        # comments sit between the spawn and the block, so raw-text offsets and
        # blanked-text offsets diverge. A mixed-basis implementation compares
        # them and sees no violation — this fixture is its discriminator.
        ("f-order-skew", "order_skew.py",
         'import subprocess\nimport sys\n\n' + header + SPAWN_LINE
         + header + CANON_BLOCK,
         ("ordering", "spawn-API token (subprocess.run)"),
         ("claude_retry_proxy import",)),
        # (g) exactly-once: the canonical block plus a later live-path
        # reassignment before the spawn. Last-match-offset logic passes this.
        ("g-exactly-once", "exactly_once.py",
         CANON_BLOCK
         + 'os.environ["PROXY_STATE_FILE"] = os.path.expanduser(\n'
           '    "~/.claude/proxy/proxy-state.json")\n' + SPAWN_LINE,
         ("PROXY_STATE_FILE", "expected exactly one"),
         ()),
    ]


def test_spawn_isolation_teeth():
    """Seven non-compliant spawners, one violated check each — all must FAIL.

    RED calibration: with a vacuous checker (always PASS) or a checker that
    lost one comparator, at least one of these fixtures turns green and this
    test fails. The FAIL line text is printed for each fixture so the round's
    transcript carries the evidence.
    """
    print("\n--- Test: Spawn-Isolation Checker Teeth (RED calibration) ---")
    base = tempfile.mkdtemp(prefix="spawn_teeth_")
    try:
        for label, filename, text, required, forbidden in _teeth_fixtures():
            sub = _fixture_dir(base, label)
            _write(os.path.join(sub, filename), text)
            proc = _run(label, ["--path", sub])
            if proc is None:
                return
            fails = _lines(proc.stdout, "FAIL ")
            if proc.returncode != 1:
                fail("%s: exit=%d, expected 1 (stdout=%r stderr=%r)"
                     % (label, proc.returncode, proc.stdout[:400],
                        proc.stderr[:300]))
                continue
            if len(fails) != 1:
                fail("%s: expected exactly 1 FAIL line, got %d: %r"
                     % (label, len(fails), fails))
                continue
            line = fails[0]
            if not line.startswith("FAIL %s: " % filename):
                fail("%s: FAIL line does not name %s: %r"
                     % (label, filename, line))
                continue
            missing = [needle for needle in required if needle not in line]
            if missing:
                fail("%s: FAIL line is missing %r: %r"
                     % (label, missing, line))
                continue
            leaked = [needle for needle in forbidden if needle in line]
            if leaked:
                fail("%s: FAIL line carries foreign comparator text %r: %r"
                     % (label, leaked, line))
                continue
            pass_("%s: %s" % (label, line))
    finally:
        shutil.rmtree(base, ignore_errors=True)


# ---------------------------------------------------------------------------
# Case 2: satisfiability (GREEN)
# ---------------------------------------------------------------------------

def test_spawn_isolation_satisfiable():
    """The canonical block PASSes — the gate is satisfiable.

    Without this case a checker could be made "green" by making compliance
    impossible, which would drive every author to the exemption marker and
    silently retire the rule. The fixture is the plan's block verbatim followed
    by a real top-level ``import claude_retry_proxy.server`` line and then a
    spawn line, so the import comparator is genuinely exercised (a compliant
    block legitimately precedes it) rather than left vacuous. The phrase also
    appears mid-line inside the block's own comment, where only a raw-text,
    non-line-anchored search can hit it — and such a search would place the
    import hit inside the block, ahead of the assignments, and fail here.
    """
    print("\n--- Test: Spawn-Isolation Checker Is Satisfiable ---")
    base = tempfile.mkdtemp(prefix="spawn_green_")
    try:
        sub = _fixture_dir(base, "clean")
        _write(os.path.join(sub, "clean_spawner.py"),
               'import subprocess\nimport sys\n\n' + CANON_BLOCK + "\n"
               'import claude_retry_proxy.server as proxy_server\n\n'
               + SPAWN_LINE)
        proc = _run("satisfiable", ["--path", sub])
        if proc is None:
            return
        if proc.returncode != 0:
            fail("satisfiable: exit=%d, expected 0 (stdout=%r stderr=%r)"
                 % (proc.returncode, proc.stdout[:400], proc.stderr[:300]))
            return
        passes = _lines(proc.stdout, "PASS ")
        if passes != ["PASS clean_spawner.py"]:
            fail("satisfiable: expected exactly ['PASS clean_spawner.py'], "
                 "got %r (stdout=%r)" % (passes, proc.stdout[:400]))
            return
        pass_("canonical block passes: %s" % passes[0])
    finally:
        shutil.rmtree(base, ignore_errors=True)


# ---------------------------------------------------------------------------
# Case 3: false-positive guard (import-only)
# ---------------------------------------------------------------------------

def test_spawn_isolation_import_only_skip():
    """A proxy import with no spawn API is a visible SKIP, never a failure.

    In-process importers are a documented residual gap: they cannot leak a
    child, but they do read the env at import. The disposition is visibility,
    not enforcement — an author who later adds a spawn call becomes a spawner
    and the compliance checks engage.
    """
    print("\n--- Test: Spawn-Isolation Import-Only Is a SKIP ---")
    base = tempfile.mkdtemp(prefix="spawn_importonly_")
    try:
        sub = _fixture_dir(base, "importer")
        _write(os.path.join(sub, "importer.py"),
               'from claude_retry_proxy.transforms_chat import '
               'anthropic_to_chat_body\n\n'
               'def convert(body):\n'
               '    return anthropic_to_chat_body(body)\n')
        proc = _run("import-only", ["--path", sub])
        if proc is None:
            return
        if proc.returncode != 0:
            fail("import-only: exit=%d, expected 0 (stdout=%r stderr=%r)"
                 % (proc.returncode, proc.stdout[:400], proc.stderr[:300]))
            return
        skips = _lines(proc.stdout, "SKIP ")
        if skips != ["SKIP importer.py: launch tokens without a spawn API"]:
            fail("import-only: expected the launch-without-spawn SKIP, got %r"
                 % (skips,))
            return
        pass_("import-only classified as a SKIP, not a failure")
    finally:
        shutil.rmtree(base, ignore_errors=True)


# ---------------------------------------------------------------------------
# Case 4: the exemption marker
# ---------------------------------------------------------------------------

def test_spawn_isolation_exemption():
    """The marker is honored, and its limits (checks 1, 2 and 5) cannot be waived.

    Eight shapes: a genuine trace-only exemption (EXEMPT, exit 0); an empty
    reason (FAIL); a marker with no state assignment (FAIL — the marker can
    never green-light a script whose child could write or delete the live
    state document); a reason carrying a second colon, which must survive the
    FULL-PREFIX cut rather than being truncated at the first colon; then three
    exempt teeth — a live-path ``_ISOLATION_DIR``, an empty ``_ISOLATION_DIR``,
    and a canonical pair placed after the first spawn-API token must each FAIL
    under the marker — plus a reason carrying control characters, which must be
    emitted sanitized so an evidence line cannot be forged.
    """
    print("\n--- Test: Spawn-Isolation Exemption Marker ---")
    base = tempfile.mkdtemp(prefix="spawn_exempt_")
    try:
        # (a) trace genuinely redirected via --log; state assignment present.
        sub = _fixture_dir(base, "a-exempt")
        _write(os.path.join(sub, "exempted_trace.py"),
               "# spawn-isolation: exempt: trace redirected via --log to the "
               "script's own temp dir\n"
               'import os\nimport sys\nimport tempfile\n\n'
               '_ISOLATION_DIR = tempfile.mkdtemp(prefix="proxy-probe-")\n'
               'os.environ["PROXY_STATE_FILE"] = os.path.join(\n'
               '    _ISOLATION_DIR, "state.json")\n' + SPAWN_LINE)
        proc = _run("exemption-a", ["--path", sub])
        if proc is None:
            return
        exempts = _lines(proc.stdout, "EXEMPT ")
        if proc.returncode != 0 or exempts != [
                "EXEMPT exempted_trace.py: trace redirected via --log to the "
                "script's own temp dir"]:
            fail("(a) expected a single EXEMPT line and exit 0, got exit=%d "
                 "lines=%r stderr=%r"
                 % (proc.returncode, exempts, proc.stderr[:300]))
        else:
            pass_("(a) marker honored: %s" % exempts[0])

        # (b) whitespace-only reason.
        sub = _fixture_dir(base, "b-empty-reason")
        _write(os.path.join(sub, "empty_reason.py"),
               "# spawn-isolation: exempt:   \n"
               'import subprocess\nimport sys\n\n' + SPAWN_LINE)
        proc = _run("exemption-b", ["--path", sub])
        if proc is not None:
            fails = _lines(proc.stdout, "FAIL ")
            if proc.returncode != 1 or len(fails) != 1 or not fails[0].endswith(
                    "exempt marker without reason"):
                fail("(b) expected one FAIL 'exempt marker without reason', "
                     "got exit=%d %r" % (proc.returncode, proc.stdout[:400]))
            else:
                pass_("(b) %s" % fails[0])

        # (c) marker with a reason but no state assignment.
        sub = _fixture_dir(base, "c-no-state")
        _write(os.path.join(sub, "no_state.py"),
               "# spawn-isolation: exempt: trace-only\n"
               'import subprocess\nimport sys\n\n' + SPAWN_LINE)
        proc = _run("exemption-c", ["--path", sub])
        if proc is not None:
            fails = _lines(proc.stdout, "FAIL ")
            if proc.returncode != 1 or len(fails) != 1 or not fails[0].endswith(
                    "exempt-without-state-isolation"):
                fail("(c) expected one FAIL 'exempt-without-state-isolation', "
                     "got exit=%d %r" % (proc.returncode, proc.stdout[:400]))
            else:
                pass_("(c) %s" % fails[0])

        # (d) a reason containing a second colon survives the prefix cut.
        sub = _fixture_dir(base, "d-colon-reason")
        _write(os.path.join(sub, "colon_reason.py"),
               "# spawn-isolation: exempt: see docs: note\n"
               'import os\nimport sys\nimport tempfile\n\n'
               '_ISOLATION_DIR = tempfile.mkdtemp(prefix="proxy-probe-")\n'
               'os.environ["PROXY_STATE_FILE"] = os.path.join(\n'
               '    _ISOLATION_DIR, "state.json")\n' + SPAWN_LINE)
        proc = _run("exemption-d", ["--path", sub])
        if proc is not None:
            exempts = _lines(proc.stdout, "EXEMPT ")
            if proc.returncode != 0 or exempts != [
                    "EXEMPT colon_reason.py: see docs: note"]:
                fail("(d) expected the post-prefix reason 'see docs: note', "
                     "got exit=%d %r" % (proc.returncode, exempts))
            else:
                pass_("(d) reason cut at the full prefix: %s" % exempts[0])

        # (e) exempt teeth, check 1: the derivation is live-path, and the join
        # shape (the only thing the old state anchor proved) is intact. The
        # marker never waives the mkdtemp derivation.
        sub = _fixture_dir(base, "e-live-iso")
        _write(os.path.join(sub, "live_iso_exempt.py"),
               "# spawn-isolation: exempt: trace redirected via --log\n"
               'import os\nimport sys\n\n'
               '_ISOLATION_DIR = os.path.expanduser("~/.claude/proxy")\n'
               'os.environ["PROXY_STATE_FILE"] = os.path.join(\n'
               '    _ISOLATION_DIR, "state.json")\n' + SPAWN_LINE)
        proc = _run("exemption-e", ["--path", sub])
        if proc is not None:
            fails = _lines(proc.stdout, "FAIL ")
            if proc.returncode != 1 or len(fails) != 1 or \
                    "_ISOLATION_DIR is not derived from tempfile.mkdtemp" \
                    not in fails[0]:
                fail("(e) a live-path _ISOLATION_DIR under the marker must "
                     "FAIL the derivation check; exit=%d %r"
                     % (proc.returncode, proc.stdout[:400]))
            else:
                pass_("(e) %s" % fails[0])

        # (f) exempt teeth, check 1 variant: an explicitly empty derivation —
        # the state file would land in the cwd, which is still live state.
        sub = _fixture_dir(base, "f-empty-iso")
        _write(os.path.join(sub, "empty_iso_exempt.py"),
               "# spawn-isolation: exempt: trace redirected via --log\n"
               'import os\nimport sys\n\n'
               '_ISOLATION_DIR = ""\n'
               'os.environ["PROXY_STATE_FILE"] = os.path.join(\n'
               '    _ISOLATION_DIR, "state.json")\n' + SPAWN_LINE)
        proc = _run("exemption-f", ["--path", sub])
        if proc is not None:
            fails = _lines(proc.stdout, "FAIL ")
            if proc.returncode != 1 or len(fails) != 1 or \
                    "_ISOLATION_DIR is not derived from tempfile.mkdtemp" \
                    not in fails[0]:
                fail("(f) an empty _ISOLATION_DIR under the marker must FAIL "
                     "the derivation check; exit=%d %r"
                     % (proc.returncode, proc.stdout[:400]))
            else:
                pass_("(f) %s" % fails[0])

        # (g) exempt teeth, check 5: the canonical state pair is complete and
        # correctly shaped, but placed after the first spawn-API token — the
        # spawned child would inherit the live paths.
        sub = _fixture_dir(base, "g-post-spawn")
        _write(os.path.join(sub, "post_spawn_exempt.py"),
               "# spawn-isolation: exempt: trace redirected via --log\n"
               'import subprocess\nimport sys\n\n'
               + SPAWN_LINE + "\n"
               '_ISOLATION_DIR = tempfile.mkdtemp(prefix="proxy-probe-")\n'
               'os.environ["PROXY_STATE_FILE"] = os.path.join(\n'
               '    _ISOLATION_DIR, "state.json")\n')
        proc = _run("exemption-g", ["--path", sub])
        if proc is not None:
            fails = _lines(proc.stdout, "FAIL ")
            if proc.returncode != 1 or len(fails) != 1 or \
                    "must precede the first spawn-API token (subprocess.run)" \
                    not in fails[0]:
                fail("(g) a post-spawn canonical pair under the marker must "
                     "FAIL the ordering check; exit=%d %r"
                     % (proc.returncode, proc.stdout[:400]))
            else:
                pass_("(g) %s" % fails[0])

        # (h) the reason is emitted through the sanitizer: C0 controls and DEL
        # are stripped, so the evidence line stays one line and cannot be
        # forged by the reason's own content.
        sub = _fixture_dir(base, "h-control-reason")
        _write(os.path.join(sub, "ctrl_reason.py"),
               "# spawn-isolation: exempt: trace\x07 redirected\x1b "
               "via --log\x7f\n"
               'import os\nimport sys\nimport tempfile\n\n'
               '_ISOLATION_DIR = tempfile.mkdtemp(prefix="proxy-probe-")\n'
               'os.environ["PROXY_STATE_FILE"] = os.path.join(\n'
               '    _ISOLATION_DIR, "state.json")\n' + SPAWN_LINE)
        proc = _run("exemption-h", ["--path", sub])
        if proc is not None:
            exempts = _lines(proc.stdout, "EXEMPT ")
            if proc.returncode != 0 or exempts != [
                    "EXEMPT ctrl_reason.py: trace redirected via --log"]:
                fail("(h) the exemption reason must be emitted sanitized, got "
                     "exit=%d %r" % (proc.returncode, exempts))
            elif any(ch in proc.stdout for ch in "\x07\x1b\x7f"):
                fail("(h) a control character escaped into stdout: %r"
                     % proc.stdout[:400])
            elif len(proc.stdout.splitlines()) != 2:
                fail("(h) expected exactly one EXEMPT line plus the summary, "
                     "got %d physical line(s): %r"
                     % (len(proc.stdout.splitlines()), proc.stdout[:400]))
            else:
                pass_("(h) control characters stripped from the reason: %s"
                      % exempts[0])
    finally:
        shutil.rmtree(base, ignore_errors=True)


# ---------------------------------------------------------------------------
# Case 5: prose overflag (raw-text detection, documented safe side)
# ---------------------------------------------------------------------------

def test_spawn_isolation_prose_overflag():
    """Docstring- and comment-only tokens still classify a file as a spawner.

    Detection runs on RAW text deliberately: overflag is the safe side, and
    the exemption marker is the remedy. Both variants here must FAIL the
    presence checks rather than pass as clean non-spawners.
    """
    print("\n--- Test: Spawn-Isolation Prose Overflag ---")
    base = tempfile.mkdtemp(prefix="spawn_prose_")
    try:
        sub = _fixture_dir(base, "a-docstring")
        _write(os.path.join(sub, "docstring_only.py"),
               'import subprocess\n\n'
               'DOC = """\nThis helper documents the claude-retry-proxy gateway.\n"""\n\n'
               'subprocess.run(["echo", "hello"])\n')
        proc = _run("prose-a", ["--path", sub])
        if proc is not None:
            fails = _lines(proc.stdout, "FAIL ")
            if proc.returncode != 1 or len(fails) != 1 or \
                    "_ISOLATION_DIR" not in fails[0]:
                fail("(a) docstring-only launch token must still be flagged "
                     "and fail the presence checks; exit=%d %r"
                     % (proc.returncode, proc.stdout[:400]))
            else:
                pass_("(a) docstring token overflagged: %s" % fails[0])

        sub = _fixture_dir(base, "b-comments")
        _write(os.path.join(sub, "comment_only.py"),
               "# This helper shells out with subprocess.run and imports\n"
               "# claude_retry_proxy indirectly.\n")
        proc = _run("prose-b", ["--path", sub])
        if proc is not None:
            fails = _lines(proc.stdout, "FAIL ")
            if proc.returncode != 1 or len(fails) != 1 or \
                    "PROXY_FEATURE_COMPAT_FILE" not in fails[0]:
                fail("(b) comment-only tokens must still classify a spawner; "
                     "exit=%d %r" % (proc.returncode, proc.stdout[:400]))
            else:
                pass_("(b) comment tokens overflagged: %s" % fails[0])
    finally:
        shutil.rmtree(base, ignore_errors=True)


# ---------------------------------------------------------------------------
# Case 6: encoding defects
# ---------------------------------------------------------------------------

def test_spawn_isolation_encoding():
    """Non-ASCII and UTF-16 input is judged without a traceback or a silent SKIP.

    (a) a leading UTF-8 BOM plus an em-dash must not raise and must not hide
    the file's violations — the leading BOM is stripped by ``utf-8-sig``.
    (b) a UTF-16 payload decodes to NUL-interleaved text under a plain
    ``utf-8-sig`` decode, where every token scan would silently miss; the
    encoding probe must report it as a FAIL instead.
    """
    print("\n--- Test: Spawn-Isolation Encoding Defects ---")
    base = tempfile.mkdtemp(prefix="spawn_encoding_")
    try:
        sub = _fixture_dir(base, "a-bom")
        _write_bytes(os.path.join(sub, "bom_spawner.py"),
                     b"\xef\xbb\xbf"
                     + ('import subprocess\nimport sys\n\n'
                        '# em-dash check — the file is plain UTF-8 otherwise\n'
                        + SPAWN_LINE).encode("utf-8"))
        proc = _run("encoding-a", ["--path", sub])
        if proc is not None:
            fails = _lines(proc.stdout, "FAIL ")
            if proc.returncode != 1 or len(fails) != 1 or \
                    not fails[0].startswith("FAIL bom_spawner.py: "):
                fail("(a) BOM + em-dash spawner: expected exactly one FAIL "
                     "line; exit=%d %r stderr=%r"
                     % (proc.returncode, proc.stdout[:400], proc.stderr[:300]))
            elif "Traceback" in proc.stderr:
                fail("(a) a traceback escaped: %r" % proc.stderr[:400])
            else:
                pass_("(a) one aggregated FAIL line, no traceback: %s"
                      % fails[0])

        sub = _fixture_dir(base, "b-utf16")
        _write_bytes(os.path.join(sub, "utf16_spawner.py"),
                     ('import subprocess\nimport sys\n\n'
                      + SPAWN_LINE).encode("utf-16"))
        proc = _run("encoding-b", ["--path", sub])
        if proc is not None:
            fails = _lines(proc.stdout, "FAIL ")
            if proc.returncode != 1 or len(fails) != 1 or \
                    "undecodable encoding" not in fails[0]:
                fail("(b) UTF-16 spawner must FAIL as undecodable rather than "
                     "scan as a clean non-spawner; exit=%d %r"
                     % (proc.returncode, proc.stdout[:400]))
            else:
                pass_("(b) %s" % fails[0])
    finally:
        shutil.rmtree(base, ignore_errors=True)


# ---------------------------------------------------------------------------
# Case 7: default root and the bad-path lattice
# ---------------------------------------------------------------------------

def _normalized(path):
    return os.path.normcase(os.path.realpath(os.path.abspath(path)))


def test_spawn_isolation_root_and_bad_paths():
    """The default root derives from the checker's location, and bad --paths exit 2.

    The no-argument run is executed with cwd set to this test's own temp dir —
    an unrelated working directory — so a checker that derived its root from
    ``os.getcwd()`` cannot stay green (running from the repo root would let a
    cwd-derived root produce the same answer). The assertion is
    coordinate-space-free: the emitted ``root=`` value and the expected path
    are both normalized through ``normcase(realpath(abspath(...)))``, so a
    junctioned or short-named checkout cannot false-fail the comparison.
    """
    print("\n--- Test: Spawn-Isolation Default Root and Bad Paths ---")
    base = tempfile.mkdtemp(prefix="spawn_paths_")
    try:
        proc = _run("root-default", [], cwd=base)
        if proc is not None:
            summary = _summary_line(proc.stdout)
            match = SUMMARY_RE.match(summary or "")
            if proc.returncode != 0 or summary is None or not match:
                fail("default run: expected exit 0 and a summary line, got "
                     "exit=%d stdout=%r stderr=%r"
                     % (proc.returncode, proc.stdout[:400], proc.stderr[:300]))
            elif _normalized(match.group(1)) != _normalized(CORPUS_DIR):
                fail("default run: root is %r, expected %r"
                     % (match.group(1), CORPUS_DIR))
            else:
                pass_("default root resolves to the repo corpus: %s"
                      % match.group(1))

        for label, arg in (("empty-string", ""), ("whitespace-only", "   ")):
            proc = _run(label, ["--path", arg])
            if proc is None:
                continue
            if proc.returncode != 2:
                fail("%s: exit=%d, expected 2 (stdout=%r stderr=%r)"
                     % (label, proc.returncode, proc.stdout[:300],
                        proc.stderr[:300]))
            else:
                pass_("%s --path rejected with exit 2" % label)

        regular = os.path.join(base, "regular.txt")
        _write(regular, "not a directory\n")
        proc = _run("regular-file", ["--path", regular])
        if proc is not None:
            if proc.returncode != 2 or "not a directory" not in proc.stderr:
                fail("regular file --path: expected exit 2 naming the "
                     "rejection; exit=%d stderr=%r"
                     % (proc.returncode, proc.stderr[:300]))
            else:
                pass_("regular-file --path rejected with exit 2")

        missing = os.path.join(base, "does-not-exist")
        proc = _run("nonexistent", ["--path", missing])
        if proc is not None:
            summary = _summary_line(proc.stdout)
            if proc.returncode != 0 or summary is None or \
                    "corpus absent" not in summary:
                fail("nonexistent --path: expected exit 0 'corpus absent', "
                     "got exit=%d stdout=%r" % (proc.returncode,
                                                proc.stdout[:400]))
            else:
                pass_("nonexistent --path is a visible 'corpus absent'")
    finally:
        shutil.rmtree(base, ignore_errors=True)


# ---------------------------------------------------------------------------
# Case 8: corpus hook (non-hermetic by design)
# ---------------------------------------------------------------------------

def test_spawn_isolation_corpus_hook():
    """The live tmp/verification corpus is clean, and vacuity is always visible.

    This is the enforcement mechanism: a non-compliant script authored by any
    round makes this test red in that plan's own tester round. The expected
    census after the plan's sweep is 2 EXEMPT / 0 FAIL; it is recorded, not
    asserted, because the corpus is a live workspace that later compliant
    scripts may join. The 0-FAIL invariant IS asserted.
    """
    print("\n--- Test: Spawn-Isolation Live Corpus Hook ---")
    if not os.path.isfile(CHECKER_PATH):
        fail("anchor broken: %s does not exist" % CHECKER_PATH)
        return
    base = tempfile.mkdtemp(prefix="spawn_corpus_")
    try:
        proc = _run("corpus", ["--path", CORPUS_DIR])
        if proc is not None:
            fails = _lines(proc.stdout, "FAIL ")
            summary = _summary_line(proc.stdout)
            if proc.returncode != 0 or fails or summary is None or \
                    ", 0 fail," not in summary:
                fail("live corpus is not clean: exit=%d summary=%r fails=%r"
                     % (proc.returncode, summary, fails))
            else:
                info("corpus census (precondition: 2 EXEMPT / 0 FAIL): %s"
                     % summary)
                pass_("live corpus clean: %s" % summary)

        absent = os.path.join(base, "absent")
        proc = _run("corpus-absent", ["--path", absent])
        if proc is not None:
            summary = _summary_line(proc.stdout)
            if proc.returncode != 0 or summary is None or \
                    "corpus absent" not in summary:
                fail("absent corpus: expected exit 0 'corpus absent', got "
                     "exit=%d stdout=%r" % (proc.returncode, proc.stdout[:400]))
            else:
                pass_("absent corpus is visible: %s" % summary)

        empty = _fixture_dir(base, "empty")
        proc = _run("corpus-empty", ["--path", empty])
        if proc is not None:
            summary = _summary_line(proc.stdout)
            if proc.returncode != 0 or summary is None or \
                    "corpus empty" not in summary:
                fail("empty corpus: expected exit 0 'corpus empty', got "
                     "exit=%d stdout=%r" % (proc.returncode, proc.stdout[:400]))
            else:
                pass_("empty corpus is visible: %s" % summary)
    finally:
        shutil.rmtree(base, ignore_errors=True)


# ---------------------------------------------------------------------------
# Case 9: checker self-scan (identity exclusion, not a marker)
# ---------------------------------------------------------------------------

def test_spawn_isolation_checker_self_scan():
    """Scanning scripts/ skips the checker by identity and stays exit 0.

    The checker's own text carries both token families — it is a classified
    spawner — so a self-scan without identity exclusion would report the
    checker itself as a violation. The exclusion is by resolved path, never by
    a header marker, so a copy of the file elsewhere is still judged.
    """
    print("\n--- Test: Spawn-Isolation Checker Self-Scan ---")
    scripts_dir = os.path.join(REPO_ROOT, "scripts")
    proc = _run("self-scan", ["--path", scripts_dir])
    if proc is None:
        return
    skips = _lines(proc.stdout, "SKIP ")
    if proc.returncode != 0:
        fail("self-scan: exit=%d, expected 0 (stdout=%r stderr=%r)"
             % (proc.returncode, proc.stdout[:400], proc.stderr[:300]))
        return
    if "SKIP check_spawn_isolation.py: checker itself" not in skips:
        fail("self-scan: expected 'SKIP check_spawn_isolation.py: checker "
             "itself', got %r" % (skips,))
        return
    pass_("checker excluded from its own scan by identity")


# ---------------------------------------------------------------------------
# Case 10: unreadable directory (POSIX-only construct)
# ---------------------------------------------------------------------------

def test_spawn_isolation_unreadable_directory():
    """A spawner beneath an unreadable directory is a counted FAIL.

    The construct needs POSIX directory permissions; Windows has no equivalent
    for a non-privileged process, so the case is skipped there — it still
    gates the branch on every POSIX environment. Root bypasses permission
    checks on POSIX, so it is skipped too rather than green for the wrong
    reason.
    """
    print("\n--- Test: Spawn-Isolation Unreadable Directory ---")
    if os.name != "posix":
        pass_("skipped on Windows — POSIX directory-permission construct only; "
              "see docstring")
        return
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        pass_("skipped as root — directory permissions are not enforced for "
              "uid 0; see docstring")
        return
    base = tempfile.mkdtemp(prefix="spawn_unreadable_")
    locked = os.path.join(base, "locked")
    try:
        os.makedirs(locked)
        _write(os.path.join(locked, "leaky.py"),
               'import subprocess\nimport sys\n\n' + SPAWN_LINE)
        os.chmod(locked, 0)
        try:
            proc = _run("unreadable", ["--path", base])
        finally:
            os.chmod(locked, 0o700)
        if proc is None:
            return
        fails = _lines(proc.stdout, "FAIL ")
        if proc.returncode != 1 or not any(
                "unreadable directory" in line for line in fails):
            fail("unreadable directory must be a counted FAIL at exit 1; "
                 "exit=%d stdout=%r" % (proc.returncode, proc.stdout[:400]))
            return
        pass_("unreadable directory counted: %s" % fails[0])
    finally:
        shutil.rmtree(base, ignore_errors=True)


# ---------------------------------------------------------------------------
# Case 11: quarantine prune (hermetic)
# ---------------------------------------------------------------------------

def test_spawn_isolation_quarantine_prune():
    """A quarantined subtree is pruned visibly, and its contents are unreported.

    The real quarantine (``tmp/retired-artifacts``) holds retired evidence
    whose scripts predate this rule by construction, so it must never be
    scanned. ``--quarantine`` makes that checkable without touching the real
    one: the pruned directory emits ``SKIP <dir>: retired-artifacts`` (so a
    fully pruned scan is visibly vacuous) and the leaky spawner inside is
    never named.
    """
    print("\n--- Test: Spawn-Isolation Quarantine Prune ---")
    base = tempfile.mkdtemp(prefix="spawn_quarantine_")
    try:
        _write(os.path.join(base, "clean_spawner.py"),
               CANON_BLOCK + "\n" + SPAWN_LINE)
        retired = _fixture_dir(base, "retired")
        _write(os.path.join(retired, "inner_leaky.py"),
               'import subprocess\nimport sys\n\n' + SPAWN_LINE)
        proc = _run("quarantine", ["--path", base, "--quarantine", retired])
        if proc is None:
            return
        skips = _lines(proc.stdout, "SKIP ")
        passes = _lines(proc.stdout, "PASS ")
        if proc.returncode != 0:
            fail("quarantine prune: exit=%d, expected 0 (stdout=%r stderr=%r)"
                 % (proc.returncode, proc.stdout[:400], proc.stderr[:300]))
            return
        if "SKIP retired: retired-artifacts" not in skips:
            fail("quarantine prune: expected 'SKIP retired: retired-artifacts', "
                 "got %r" % (skips,))
            return
        if passes != ["PASS clean_spawner.py"]:
            fail("quarantine prune: the unpruned spawner must still be judged; "
                 "got %r" % (passes,))
            return
        if "inner_leaky.py" in proc.stdout:
            fail("quarantine prune: the pruned spawner was reported: %r"
                 % proc.stdout[:400])
            return
        pass_("quarantined subtree pruned and its spawner unreported")
    finally:
        shutil.rmtree(base, ignore_errors=True)


# ---------------------------------------------------------------------------
# Case 12: spawn-only classification
# ---------------------------------------------------------------------------

def test_spawn_isolation_spawn_only_skip():
    """A subprocess helper with no proxy token is a visible SKIP, not a failure.

    Helper scripts that shell out to the suite are common and harmless; they
    get their own SKIP branch so the census distinguishes them from
    non-spawners instead of silently passing them.
    """
    print("\n--- Test: Spawn-Isolation Spawn-Only Is a SKIP ---")
    base = tempfile.mkdtemp(prefix="spawn_spawnonly_")
    try:
        sub = _fixture_dir(base, "helper")
        _write(os.path.join(sub, "helper.py"),
               'import subprocess\n\n'
               'subprocess.run(["echo", "hello"], check=False)\n')
        proc = _run("spawn-only", ["--path", sub])
        if proc is None:
            return
        skips = _lines(proc.stdout, "SKIP ")
        if proc.returncode != 0 or skips != [
                "SKIP helper.py: spawn API without proxy tokens"]:
            fail("spawn-only: expected that single SKIP at exit 0, got exit=%d "
                 "%r" % (proc.returncode, skips))
            return
        pass_("spawn-only classified as a SKIP: %s" % skips[0])
    finally:
        shutil.rmtree(base, ignore_errors=True)


ALL_TESTS = [
    ("spawn-isolation-teeth", test_spawn_isolation_teeth),
    ("spawn-isolation-satisfiable", test_spawn_isolation_satisfiable),
    ("spawn-isolation-import-only-skip", test_spawn_isolation_import_only_skip),
    ("spawn-isolation-exemption", test_spawn_isolation_exemption),
    ("spawn-isolation-prose-overflag", test_spawn_isolation_prose_overflag),
    ("spawn-isolation-encoding", test_spawn_isolation_encoding),
    ("spawn-isolation-root-and-bad-paths",
     test_spawn_isolation_root_and_bad_paths),
    ("spawn-isolation-corpus-hook", test_spawn_isolation_corpus_hook),
    ("spawn-isolation-checker-self-scan",
     test_spawn_isolation_checker_self_scan),
    ("spawn-isolation-unreadable-directory",
     test_spawn_isolation_unreadable_directory),
    ("spawn-isolation-quarantine-prune",
     test_spawn_isolation_quarantine_prune),
    ("spawn-isolation-spawn-only-skip", test_spawn_isolation_spawn_only_skip),
]

if __name__ == "__main__":
    run_cli(ALL_TESTS, "claude-retry-proxy tests: test_spawn_isolation")
