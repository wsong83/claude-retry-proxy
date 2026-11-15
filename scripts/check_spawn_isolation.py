#!/usr/bin/env python3
"""Committed corpus checker: spawn-isolation compliance for proxy-spawning scripts.

Standalone verification scripts (tmp/verification/*.py and anything else that
launches a throwaway proxy) bypass the test harness's env-override loop. The
suite isolates its children because the harness sets PROXY_STATE_FILE,
PROXY_TRACE_FILE and PROXY_FEATURE_COMPAT_FILE at import, before importing
cli.py or server.py; a standalone script does not, so the child it spawns
inherits the live paths and can write to -- or delete -- the live
~/.claude/proxy state document.

The rule enforced here (the canonical block lives verbatim in
doc/test-catalog.html#pattern-spawn-isolation): a script that spawns a proxy
child must create one tempfile.mkdtemp() directory and set all three
PROXY_*_FILE environment variables under it, BEFORE the first
`import claude_retry_proxy` line AND before the first process spawn --
settings.py binds all three paths from the environment at import (the sinks
are configured from SETTINGS at import), and a spawned child inherits the
environment it is forked with.

Scope. A scanned .py file is a "spawner" when its RAW text carries at least
one launch token and at least one spawn-API token. Comment- and
docstring-only mentions count deliberately (overflag is the safe side); the
exemption marker `# spawn-isolation: exempt: <reason>` is the escape hatch,
and it waives the trace and compatibility assignments ONLY -- the mkdtemp
derivation, the PROXY_STATE_FILE assignment and the ordering rule stay
enforced under the marker.

Declared textual limitations:
  * token presence and position are proven, not execution -- a docstring
    quoting the block passes only when no real block exists elsewhere, and
    fails the exactly-once checks when one does;
  * cleanup is not checked;
  * non-Python spawners (.js/.ps1/.bat/.sh) are invisible to the compliance
    rule (reported as "not scanned (non-Python)");
  * fully dynamic module construction defeats literal token matching;
  * a hard-killed script still orphans its proxy-probe-* temp dir; no
    "no residue" claim is made. Measure with: ls %TEMP%/proxy-probe-*

Standalone, stdlib only, cross-platform. Runs from any working directory --
the default scan root derives from this file's own location:

    python scripts/check_spawn_isolation.py
    python scripts/check_spawn_isolation.py --path <dir> [--quarantine <dir>]

Exit codes:
    0 = clean, including an absent corpus and an empty one
    1 = at least one failure (a compliance violation, an unreadable file or
        directory, or an undecodable encoding)
    2 = a bad explicit --path (empty/whitespace-only, exists but is not a
        directory, existing but unreadable) or an abnormal run -- a crash
        must never masquerade as exit 1.

Tests: tests/test_spawn_isolation.py drives this file as the permanent
regression net, including the live-corpus hook that makes a non-compliant
script fail its own plan's tester round.
"""

import argparse
import os
import re
import stat
import sys
import time

# <repo>/scripts/check_spawn_isolation.py -> <repo>
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# The scan root derives from this file, never from cwd.
DEFAULT_ROOT = os.path.join(REPO_ROOT, "tmp", "verification")
DEFAULT_QUARANTINE = os.path.join(REPO_ROOT, "tmp", "retired-artifacts")

# A file is a spawner only when BOTH lists hit. Bare substrings on purpose:
# a token in a comment or docstring still counts (overflag is safe-side).
LAUNCH_TOKENS = (
    "claude_retry_proxy",   # subsumes .server / .cli and in-process imports
    "claude-retry-proxy",   # subsumes -server and .exe spellings
    "PROXY_SERVER",
    "CLAUDE_PROXY",
)
SPAWN_TOKENS = (
    "Popen(",
    "subprocess.run",
    "subprocess.call",
    "subprocess.check_call",
    "subprocess.check_output",
    "os.system",
    "os.spawn",
    "os.exec",
    "os.popen(",
    "subprocess.getoutput(",
    "subprocess.getstatusoutput(",
    "os.posix_spawn",
    "os.posix_spawnp",
    "multiprocessing.Process(",
    "asyncio.create_subprocess_exec",
    "asyncio.create_subprocess_shell",
    "from subprocess import",
)

MARKER_PREFIX = "# spawn-isolation: exempt:"
MAX_SCAN_BYTES = 5 * 1024 * 1024
ENCODING_PROBE_BYTES = 4096
# utf-16 LE/BE and utf-32 LE/BE byte-order marks. A leading utf-8 BOM is NOT a
# defect (utf-8-sig decoding strips it); NUL bytes are caught separately.
UTF16_32_BOMS = (b"\xff\xfe", b"\xfe\xff", b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff")

ISO_DIR_ASSIGN_RE = re.compile(r"(?m)^\s*_ISOLATION_DIR\s*=")
ISO_DIR_MKDTEMP_RE = re.compile(r"_ISOLATION_DIR\s*=\s*tempfile\.mkdtemp\(")
IMPORT_RE = re.compile(r"(?m)^\s*(?:from|import)\s+claude_retry_proxy")
CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")

# (env var name, file name) pairs the canonical block assigns.
ISOLATION_VARS = (
    ("PROXY_STATE_FILE", "state.json"),
    ("PROXY_TRACE_FILE", "trace.jsonl"),
    ("PROXY_FEATURE_COMPAT_FILE", "feature-compat.json"),
)


def clean(value):
    """Strip every C0 control character and DEL from a variable field.

    Evidence lines stay one line and the trail cannot be forged by content.
    """
    return CONTROL_RE.sub("", value)


def norm_real(path):
    """One coordinate space for identity, containment and quarantine checks."""
    return os.path.normcase(os.path.realpath(os.path.abspath(path)))


def under(path_key, root_key):
    """True when path_key is root_key or lies beneath it (both norm_real'd)."""
    return path_key == root_key or path_key.startswith(root_key + os.sep)


def emit(verdict, rel_path, detail=""):
    if verdict == "PASS":
        print("PASS %s" % clean(rel_path))
    else:
        print("%s %s: %s" % (verdict, clean(rel_path), clean(detail)))


def is_reparse_point(path):
    """True for a symlink or an NTFS junction / reparse directory."""
    isjunction = getattr(os.path, "isjunction", None)
    if isjunction is not None:
        try:
            if isjunction(path):
                return True
        except OSError:
            pass
    try:
        if os.path.islink(path):
            return True
    except OSError:
        pass
    if os.name == "nt":
        try:
            st = os.stat(path)
        except OSError:
            return False
        attrs = getattr(st, "st_file_attributes", 0)
        return bool(attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    return False


def exemption_reason(raw_text):
    """The marker's reason, or None when the file carries no marker.

    The reason is the remainder after the FULL PREFIX (never the first colon
    of the line), stripped; an empty result is the "without reason" failure.
    """
    for line in raw_text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("#"):
            continue
        if stripped.startswith(MARKER_PREFIX):
            return stripped.split(MARKER_PREFIX, 1)[1].strip()
    return None


def blank_comments(raw_text):
    """Replace each '#'-first-non-space line by its line terminator.

    Comment-only tokens must not satisfy up or skew the compliance checks.
    Every offset the checker compares is measured on this ONE text, so raw and
    blanked offsets are never mixed.
    """
    out = []
    for line in raw_text.splitlines(True):
        if line.lstrip().startswith("#"):
            cut = len(line)
            while cut > 0 and line[cut - 1] in "\r\n":
                cut -= 1
            out.append(line[cut:])
        else:
            out.append(line)
    return "".join(out)


def first_token_hit(text, tokens):
    """(offset, token) for the earliest token in text, or None when none is."""
    best = None
    for token in tokens:
        offset = text.find(token)
        if offset != -1 and (best is None or offset < best[0]):
            best = (offset, token)
    return best


def check_isolation_dir(blanked):
    """Check 1 shape: exactly one _ISOLATION_DIR assignment, of the mkdtemp form.

    Returns (ok, offset, detail). The offset is the assignment's position even
    when its shape is wrong, so the ordering comparator sees the real position.
    """
    matches = list(ISO_DIR_ASSIGN_RE.finditer(blanked))
    if not matches:
        return (False, None,
                "no `_ISOLATION_DIR = tempfile.mkdtemp(...)` line found; the "
                "block must be copied verbatim, including the assignment on "
                "one line")
    if len(matches) > 1:
        return (False, None,
                "_ISOLATION_DIR = tempfile.mkdtemp(...) derivation: expected "
                "exactly one assignment, found %d" % len(matches))
    keyword = blanked.index("_ISOLATION_DIR", matches[0].start())
    line_end = blanked.find("\n", keyword)
    line = blanked[keyword:line_end if line_end != -1 else len(blanked)]
    if not ISO_DIR_MKDTEMP_RE.search(line):
        return (False, matches[0].start(),
                "_ISOLATION_DIR is not derived from tempfile.mkdtemp(...)")
    return (True, matches[0].start(), None)


def check_env_assignment(blanked, env_name, file_name):
    """Check 2/3/4 shape: exactly one assignment, joined under _ISOLATION_DIR.

    Returns (ok, offset, detail). The offset is the position of the canonical
    assignment when one exists, else of any assignment in the wrong shape, so
    the ordering comparator sees the real position either way.
    """
    join_re = re.compile(
        r"os\.environ\[[\"']%s[\"']\]\s*=\s*os\.path\.join\(\s*_ISOLATION_DIR\s*,"
        r"\s*[\"']%s[\"']\s*,?\s*\)" % (env_name, re.escape(file_name)))
    assign_re = re.compile(r"os\.environ\[[\"']%s[\"']\]\s*=" % env_name)

    joins = [m.start() for m in join_re.finditer(blanked)]
    assigns = [m.start() for m in assign_re.finditer(blanked)]

    if not joins:
        detail = '%s is not assigned os.path.join(_ISOLATION_DIR, "%s")' % (
            env_name, file_name)
    elif len(assigns) != 1:
        detail = "%s assignment: expected exactly one, found %d" % (
            env_name, len(assigns))
    else:
        detail = None
    offset = joins[0] if joins else (assigns[0] if assigns else None)
    return (detail is None, offset, detail)


def ordering_violations(blanked, offsets):
    """Check 5 on ONE coordinate space: the latest assignment vs import/spawn."""
    if not offsets:
        return []
    latest = max(offsets)
    violations = []
    spawn_hit = first_token_hit(blanked, SPAWN_TOKENS)
    if spawn_hit is not None and latest > spawn_hit[0]:
        violations.append(
            "ordering: the isolation assignments must precede the first "
            "spawn-API token (%s)" % spawn_hit[1])
    import_match = IMPORT_RE.search(blanked)
    if import_match is not None and latest > import_match.start():
        violations.append(
            "ordering: the isolation assignments must precede the first "
            "claude_retry_proxy import")
    return violations


def compliance_violations(blanked):
    """The five compliance checks on one blanked text, in the pinned order."""
    violations = []
    offsets = []

    ok, offset, detail = check_isolation_dir(blanked)
    if not ok:
        violations.append(detail)
    if offset is not None:
        offsets.append(offset)

    for env_name, file_name in ISOLATION_VARS:
        ok, offset, detail = check_env_assignment(blanked, env_name, file_name)
        if not ok:
            violations.append(detail)
        if offset is not None:
            offsets.append(offset)

    # Ordering, one coordinate space: ALL offsets above and both comparators
    # are measured on this same blanked text.
    violations.extend(ordering_violations(blanked, offsets))
    return violations


def classify(raw_text):
    """(verdict, detail) from decoded raw text: marker, spawner, compliance."""
    reason = exemption_reason(raw_text)
    has_launch = any(token in raw_text for token in LAUNCH_TOKENS)
    has_spawn = any(token in raw_text for token in SPAWN_TOKENS)

    if not (has_launch and has_spawn):
        if has_launch:
            return ("SKIP", "launch tokens without a spawn API")
        if has_spawn:
            return ("SKIP", "spawn API without proxy tokens")
        return ("SKIP", "no proxy tokens")

    if reason is not None and reason == "":
        return ("FAIL", "exempt marker without reason")

    blanked = blank_comments(raw_text)
    if reason is not None:
        # The marker waives the trace and compatibility assignments only. The
        # mkdtemp derivation, the state assignment and the ordering rule stay
        # enforced: a live-path _ISOLATION_DIR, a missing state assignment, or
        # a block placed after the first spawn-API token or proxy import would
        # each let a spawned child inherit the live state path.
        violations = []
        offsets = []
        ok, offset, detail = check_isolation_dir(blanked)
        if not ok:
            violations.append(detail)
        if offset is not None:
            offsets.append(offset)
        ok, offset, _detail = check_env_assignment(
            blanked, "PROXY_STATE_FILE", "state.json")
        if not ok:
            violations.append("exempt-without-state-isolation")
        if offset is not None:
            offsets.append(offset)
        violations.extend(ordering_violations(blanked, offsets))
        if violations:
            return ("FAIL", "; ".join(violations))
        return ("EXEMPT", reason)

    violations = compliance_violations(blanked)
    if violations:
        return ("FAIL", "; ".join(violations))
    return ("PASS", "")


def evaluate(path):
    """One full read-and-classify pass over one file."""
    try:
        if os.path.getsize(path) > MAX_SCAN_BYTES:
            return ("SKIP", "oversize, not scanned")
        with open(path, "rb") as handle:
            data = handle.read()
    except FileNotFoundError:
        return ("SKIP", "vanished during scan")
    except OSError as exc:
        return ("FAIL", "unreadable (%s)" % exc.__class__.__name__)

    head = data[:ENCODING_PROBE_BYTES]
    if b"\x00" in head or head.startswith(UTF16_32_BOMS):
        return ("FAIL", "undecodable encoding (utf-16 suspected)")
    return classify(data.decode("utf-8-sig", errors="replace"))


def scan(root, quarantine_root):
    """Walk the verified scan root and print one line per file considered."""
    root_key = norm_real(root)
    quarantine_key = norm_real(quarantine_root)
    self_key = norm_real(__file__)
    stats = {"py": 0, "spawners": 0, "fail": 0, "exempt": 0, "skip": 0}
    root_errors = []

    def rel_of(path):
        return os.path.relpath(path, root).replace(os.sep, "/")

    def on_error(err):
        failed = getattr(err, "filename", None)
        if failed is not None and norm_real(failed) == root_key:
            root_errors.append(err)
            return
        name = rel_of(failed) if failed is not None else "<unknown>"
        if isinstance(err, FileNotFoundError):
            emit("SKIP", name, "vanished during scan")
        else:
            stats["fail"] += 1
            emit("FAIL", name, "unreadable directory (%s)"
                 % err.__class__.__name__)

    for dirpath, dirnames, filenames in os.walk(
            root, followlinks=False, onerror=on_error):
        kept = []
        for name in sorted(dirnames):
            full = os.path.join(dirpath, name)
            full_key = norm_real(full)
            if is_reparse_point(full):
                emit("SKIP", rel_of(full), "reparse point not descended")
            elif not under(full_key, root_key):
                emit("SKIP", rel_of(full), "escapes scan root")
            elif under(full_key, quarantine_key):
                emit("SKIP", rel_of(full), "retired-artifacts")
            else:
                kept.append(name)
        dirnames[:] = kept

        for name in sorted(filenames):
            full = os.path.join(dirpath, name)
            rel_path = rel_of(full)
            full_key = norm_real(full)
            if full_key == self_key:
                emit("SKIP", rel_path, "checker itself")
                continue
            if under(full_key, quarantine_key):
                emit("SKIP", rel_path, "retired-artifacts")
                continue
            if os.path.splitext(name)[1].casefold() != ".py":
                emit("SKIP", rel_path, "not scanned (non-Python)")
                continue
            stats["py"] += 1
            verdict, detail = evaluate(full)
            if verdict == "FAIL":
                # Torn-read guard: one delayed re-read replaces the verdict.
                time.sleep(0.5)
                verdict, detail = evaluate(full)
            if verdict == "PASS":
                stats["spawners"] += 1
            elif verdict == "FAIL":
                stats["spawners"] += 1
                stats["fail"] += 1
            elif verdict == "EXEMPT":
                stats["spawners"] += 1
                stats["exempt"] += 1
            else:
                stats["skip"] += 1
            emit(verdict, rel_path, detail)

    if root_errors:
        print("ERROR: scan root unreadable (%s): %s"
              % (root_errors[0].__class__.__name__, clean(root)),
              file=sys.stderr)
        return 2

    if stats["py"] == 0:
        print("check_spawn_isolation: root=%s | corpus empty | PASS"
              % clean(root))
        return 0

    print("check_spawn_isolation: root=%s | %d spawners, %d fail, %d exempt, "
          "%d skip | %s"
          % (clean(root), stats["spawners"], stats["fail"], stats["exempt"],
             stats["skip"], "PASS" if stats["fail"] == 0 else "FAIL"))
    return 0 if stats["fail"] == 0 else 1


def build_parser():
    parser = argparse.ArgumentParser(
        prog="check_spawn_isolation.py",
        description=(
            "Corpus runtime-isolation checker. A scanned .py file that both "
            "mentions the proxy and spawns a process (a 'spawner') must create "
            "one tempfile.mkdtemp() directory and set PROXY_STATE_FILE, "
            "PROXY_TRACE_FILE and PROXY_FEATURE_COMPAT_FILE under it -- before "
            "the first claude_retry_proxy import and before the first spawn. "
            "Default scan root: %s" % DEFAULT_ROOT),
        epilog=(
            "--path scans an arbitrary directory instead of the default root; "
            "it is for fixture/corpus inspection only -- production and test "
            "trees isolate by other mechanisms and FAIL by design under this "
            "checker.\n"
            "Default quarantine root: %s\n"
            "Exit codes: 0 clean (including an absent or empty corpus), "
            "1 failures found, 2 a bad --path or an abnormal run."
            % DEFAULT_QUARANTINE))
    parser.add_argument(
        "--path", metavar="<dir>", default=None,
        help="directory to scan (default: the repo's tmp/verification)")
    parser.add_argument(
        "--quarantine", metavar="<dir>", default=None,
        help="quarantine root pruned from the scan "
             "(default: the repo's tmp/retired-artifacts)")
    return parser


def main(argv=None):
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass

    args = build_parser().parse_args(argv)

    explicit = args.path is not None
    if explicit and args.path.strip() == "":
        print("ERROR: --path is empty or whitespace-only", file=sys.stderr)
        return 2
    root = os.path.abspath(args.path) if explicit else DEFAULT_ROOT
    quarantine_root = (os.path.abspath(args.quarantine)
                       if args.quarantine is not None else DEFAULT_QUARANTINE)

    if not os.path.isdir(root):
        if explicit and os.path.exists(root):
            print("ERROR: --path is not a directory: %s" % clean(root),
                  file=sys.stderr)
            return 2
        print("check_spawn_isolation: root=%s | corpus absent | PASS"
              % clean(root))
        return 0
    try:
        os.listdir(root)
    except OSError as exc:
        print("ERROR: scan root unreadable (%s): %s"
              % (exc.__class__.__name__, clean(root)), file=sys.stderr)
        return 2

    return scan(root, quarantine_root)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as exc:  # abnormal run: never exit 1 on a crash
        print("ERROR: abnormal run: %s: %s" % (exc.__class__.__name__, exc),
              file=sys.stderr)
        sys.exit(2)
