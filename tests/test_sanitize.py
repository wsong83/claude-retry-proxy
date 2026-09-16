"""Unit tests for the sanitize_error redaction chokepoint (sanitize.py).

Table-driven, direct-import, no subprocess except the ReDoS tripwire, which
must run in an isolated process with a hard timeout: a regressed exponential
match holds the GIL and would hang the suite instead of failing it (the
pre-fix regex on 64 slashes is effectively unbounded, 2^64 partitions).

Windows-separator inputs are built with chr(92) joins, never literal
escapes — quoting-independent, matching the issue-report reproduction
convention.

Part of the claude-retry-proxy suite; runnable standalone.
"""

import subprocess
import sys
import time

from _harness import (
    fail,
    pass_,
    run_cli,
)

from claude_retry_proxy.sanitize import sanitize_error


BS = chr(92)


def _native_windows(dotdir):
    """C:<BS>Users<BS>wsong<BS>.<dotdir><BS>x — the native Windows shape."""
    return BS.join(["C:", "Users", "wsong", "." + dotdir, "x"])


def _check(name, got, expected):
    if got == expected:
        pass_("{} -> {!r}".format(name, got))
    else:
        fail("{}: expected {!r}, got {!r}".format(name, expected, got))


def _redacted_all(dotdirs):
    """Every named dotdir redacts under all three path shapes."""
    for d in dotdirs:
        for shape in [
            "/home/wsong/.{}/x".format(d),
            _native_windows(d),
            "C:/Users/wsong/.{}/x".format(d),
        ]:
            got = sanitize_error(shape)
            _check("dotdir={} shape={}".format(d, shape), got,
                   "[redacted-path]")


def test_redaction_table_dotdirs_shapes():
    """Each of the seven sensitive dotdirs redacts fully in all three path
    shapes (POSIX, native Windows, forward-slash Windows)."""
    print("\n--- Test: Redaction Table (dotdirs x shapes) ---")
    _redacted_all(["claude", "ssh", "gnupg", "aws", "azure", "config", "local"])


def test_redaction_case_insensitive():
    """The dotdir alternation is compiled IGNORECASE: capitalized dotdirs on
    otherwise-identical path shapes still redact (Windows paths are
    case-insensitive)."""
    print("\n--- Test: Redaction Case Insensitive ---")
    for msg in ["/home/wsong/.CLAUDE/x",
                BS.join(["C:", "Users", "WSONG", ".Claude", "x"])]:
        got = sanitize_error(msg)
        _check("uppercase variant {!r}".format(msg), got, "[redacted-path]")


def test_redaction_errno_quote_shape():
    """OSError messages carrying a quoted POSIX path keep their prefix and
    lose the stray quote."""
    msg = ("[Errno 13] Permission denied: "
           "'/home/wsong/.claude/logs/proxy-trace.jsonl'")
    got = sanitize_error(msg)
    _check("errno-quoted path", got,
           "[Errno 13] Permission denied: [redacted-path]")


def test_redaction_boundary_cases():
    """Prefix attachment, word-boundary guard, and no-separator cases."""
    print("\n--- Test: Redaction Boundary Cases ---")
    _check("attached prefix", sanitize_error("error:/home/u/.claude/x err"),
           "[redacted-path] err")
    _check("mid-token separator", sanitize_error("see/.aws/x"),
           "[redacted-path]")
    _check("non-domain dotdir", sanitize_error("visit .aws.amazon.com docs"),
           "visit .aws.amazon.com docs")
    _check("dotdir continued by word chars",
           sanitize_error("x/.claudefoo/y"), "x/.claudefoo/y")
    _check("bare dotdir token", sanitize_error(".claude"), ".claude")


def test_redaction_ip_arm():
    """The IPv4 arm is unchanged: dotted-quads redact inside surrounding
    text; a 5-digit first octet (not an IP) is untouched."""
    print("\n--- Test: Redaction IP Arm ---")
    _check("ipv4", sanitize_error("ip 192.168.1.50 here"),
           "ip [redacted-ip] here")
    _check("not an ipv4", sanitize_error("nope 1234.56.78.90"),
           "nope 1234.56.78.90")


def test_redaction_both_arms_together():
    """A message carrying an IP and a native Windows .gnupg path redacts both."""
    msg = "connect " + _native_windows("gnupg") + " from 10.0.0.7 failed"
    got = sanitize_error(msg)
    expected = "connect [redacted-path] from [redacted-ip] failed"
    _check("path + ip together", got, expected)


def test_redaction_falsy_contract():
    """None, the empty string, and the falsy integer 0 all resolve to None —
    the pinned falsy-input contract."""
    print("\n--- Test: Redaction Falsy Contract ---")
    for v in [None, "", 0]:
        got = sanitize_error(v)
        if got is None:
            pass_("sanitize_error({!r}) is None".format(v))
        else:
            fail("sanitize_error({!r}) returned {!r}, expected None".format(v, got))


def test_redaction_truncation_last():
    """The [:200] cap applies after redaction; a 300-char plain message is
    its exact first 200 chars."""
    print("\n--- Test: Redaction Truncation Last ---")
    msg = "word " * 60  # 300 chars
    got = sanitize_error(msg)
    _check("truncation", got, msg[:200])


def test_redaction_exception_object_input():
    """A non-str input (an OSError carrying a path) is str()-ed and redacted."""
    print("\n--- Test: Redaction Exception Object Input ---")
    try:
        open(BS.join(["C:", "Users", "wsong", ".ssh", "nokey"]))
    except OSError as e:
        got = sanitize_error(e)
        if isinstance(got, str) and ".ssh" not in got\
                and "[redacted-path]" in got:
            pass_("OSError input redacted: {!r}".format(got))
        else:
            fail("OSError input not redacted: {!r}".format(got))


def test_redaction_linear_time_bound():
    """ReDoS tripwire: sanitize_error on 64 slashes completes inside a hard
    subprocess timeout. The pre-fix regex is effectively unbounded at this
    input; a container regression must produce a FAIL (timeout or nonzero
    exit), never a hang."""
    print("\n--- Test: Redaction Linear Time Bound ---")
    probe = (
        "import time\n"
        "from claude_retry_proxy.sanitize import sanitize_error\n"
        "t0 = time.perf_counter()\n"
        "sanitize_error('/' * 64)\n"
        "print('elapsed', (time.perf_counter() - t0) * 1000)\n"
    )
    t0 = time.perf_counter()
    try:
        proc = subprocess.run(
            [sys.executable, "-c", probe],
            capture_output=True, text=True, timeout=20)
    except subprocess.TimeoutExpired:
        fail("64-slash scan did not finish in 20 s — exponential regression")
        return
    if proc.returncode != 0:
        fail("timing probe exited {}: {}".format(proc.returncode,
                                                 proc.stderr.strip()))
        return
    ms = round((time.perf_counter() - t0) * 1000)
    pass_("64-slash scan finished in-process-probe fast (parent wall "
          "clock {} ms); probe output: {}".format(ms, proc.stdout.strip()))


ALL_TESTS = [
    ("redaction-table-dotdirs-shapes", test_redaction_table_dotdirs_shapes),
    ("redaction-case-insensitive", test_redaction_case_insensitive),
    ("redaction-errno-quote-shape", test_redaction_errno_quote_shape),
    ("redaction-boundary-cases", test_redaction_boundary_cases),
    ("redaction-ip-arm", test_redaction_ip_arm),
    ("redaction-both-arms-together", test_redaction_both_arms_together),
    ("redaction-falsy-contract", test_redaction_falsy_contract),
    ("redaction-truncation-last", test_redaction_truncation_last),
    ("redaction-exception-object-input", test_redaction_exception_object_input),
    ("redaction-linear-time-bound", test_redaction_linear_time_bound),
]

if __name__ == "__main__":
    from _harness import run_cli
    run_cli(ALL_TESTS, "sanitize_error unit tests")
