"""Unit tests for the sink class family (sinks.py).

No subprocess, no proxy, no network: the sinks, the shared _SinkHealth failure
reporter and the process-wide configure() are all constructed directly and
driven with fake paths and an injected clock. Assertions read the injected
report callback's captured messages, never stderr.

The module-level delegates (log_trace / write_state) reached from the request
path and the heartbeat are covered by tests/test_trace.py, which drives a live
proxy; this file covers the class-level branches those delegates cannot reach.

Part of the claude-retry-proxy suite; runnable standalone.
"""

import json
import os
import re
import shutil
import stat
import tempfile
import threading
import unittest.mock

from _harness import (
    fail,
    pass_,
    run_cli,
)

from claude_retry_proxy import sinks


class _FakeClock(object):
    """A manually advanced clock, so interval lapses need no real waiting."""

    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class _CapturedReport(object):
    """Callable stand-in for the stderr report, recording messages in order."""

    def __init__(self):
        self.messages = []

    def __call__(self, message):
        self.messages.append(message)

    def matching(self, needle):
        return [m for m in self.messages if needle in m]


def _parse_suppressed(line):
    """Exact integer from '(N further failures suppressed)', or None."""
    m = re.search(r"\((\d+) further failures? suppressed\)", line)
    return int(m.group(1)) if m else None


def _parse_resumed_count(line):
    """Exact integer from 'resumed after N failed write(s)', or None."""
    m = re.search(r"resumed after (\d+) failed write", line)
    return int(m.group(1)) if m else None


# ===========================================================================
# _SinkHealth: failure-episode policy
# ===========================================================================

def test_sink_warning_rate_limit():
    """The first failure of an episode warns immediately; further failures
    inside the interval are silent; the next failure after the interval warns
    once and reports how many were suppressed."""
    print("\n--- Test: Sink Warning Rate Limit ---")

    sink = "trace"
    rapid = 5
    clock = _FakeClock()
    report = _CapturedReport()
    health = sinks._SinkHealth(interval=60.0, clock=clock, report=report)

    for _ in range(rapid):
        health.failure(sink, OSError("boom"))

    first = report.matching("[proxy] WARNING:")
    if len(first) == 1:
        pass_("1 warning for {} rapid failures: {!r}".format(rapid, first[0]))
    else:
        fail("expected exactly 1 warning for {} rapid failures, got {}".format(
            rapid, len(first)))
        return

    # Force the interval to lapse, then fail once more. Only the failures that
    # were actually silent (rapid - 1) are reported: the failure triggering the
    # emission is never counted as suppressed.
    report.messages = []
    clock.advance(61.0)
    health.failure(sink, OSError("boom"))

    later = report.matching("[proxy] WARNING:")
    expected = rapid - 1
    got = _parse_suppressed(later[0]) if len(later) == 1 else None
    if got == expected:
        pass_("failure past the interval reports exactly {} suppressed: "
              "{!r}".format(expected, later[0]))
    else:
        fail("expected exactly 1 warning reporting {} suppressed, parsed "
             "{!r} from {!r}".format(expected, got, later))


def test_sink_recovery_notice():
    """The first successful write after a failure episode emits one line
    carrying the episode's dropped-write count; later successes are silent; and
    a *new* episode after a success opens its own fresh count rather than
    staying consumed."""
    print("\n--- Test: Sink Recovery Notice ---")

    sink = "state"
    report = _CapturedReport()
    health = sinks._SinkHealth(clock=_FakeClock(), report=report)

    # (a) recovery with no open episode emits nothing
    health.success(sink)
    if "resumed" not in "".join(report.messages):
        pass_("recovery with no open episode emits nothing")
    else:
        fail("recovery notice without a failure episode: {!r}".format(
            report.messages))

    # (b) three failures then a success -> one line reporting exactly 3
    failures = 3
    for _ in range(failures):
        health.failure(sink, OSError("nope"))
    health.success(sink)
    lines = report.matching("resumed")
    got = _parse_resumed_count(lines[0]) if len(lines) == 1 else None
    if got == failures and sink in lines[0]:
        pass_("recovery line reports exactly {} failed write(s): {!r}".format(
            failures, lines[0]))
    else:
        fail("expected 1 recovery line reporting exactly {} failed writes, "
             "parsed {!r} from {!r}".format(failures, got, lines))

    # (c) episode closed — a second recovery emits nothing
    report.messages = []
    health.success(sink)
    if "resumed" not in "".join(report.messages):
        pass_("episode closed — a second recovery emits nothing")
    else:
        fail("second recovery notice emitted: {!r}".format(report.messages))

    # (d) a new episode after a success reports its own count, not the closed
    #     episode's — the counter resets with the episode
    report.messages = []
    health.failure(sink, OSError("again"))
    health.success(sink)
    lines = report.matching("resumed")
    got = _parse_resumed_count(lines[0]) if len(lines) == 1 else None
    if got == 1:
        pass_("a new episode emits its own recovery line: {!r}".format(lines[0]))
    else:
        fail("expected 1 recovery line reporting 1 failed write for the new "
             "episode, parsed {!r} from {!r}".format(got, lines))


# ===========================================================================
# _Sink.write: the shared never-raising write path
# ===========================================================================

def test_sink_write_contract_class_level():
    """A directly-constructed sink on an unwritable path returns False and
    records exactly one failure on its *own* health.

    The delegate-level blocked-path contract is asserted elsewhere
    (tests/test_trace.py); this asserts the class-level branch and the private
    health a constructed sink is given by default.
    """
    print("\n--- Test: Sink Write Contract (Class Level) ---")

    root = tempfile.mkdtemp(prefix="proxy_sinks_")
    blocked = os.path.join(root, "trace-is-a-directory")
    os.mkdir(blocked)

    report = _CapturedReport()
    health = sinks._SinkHealth(report=report)
    sink = sinks.TraceSink(blocked, health=health)
    try:
        result = sink.write({"event": "probe"})
        if result is False:
            pass_("constructed sink's write returned False on an unwritable path")
        else:
            fail("write returned {!r}, expected False".format(result))

        warnings = report.matching("trace sink write failed")
        if len(warnings) == 1:
            pass_("injected health recorded exactly 1 failure: {!r}".format(
                warnings[0]))
        else:
            fail("expected exactly 1 recorded failure on the injected health, "
                 "got {} ({!r})".format(len(warnings), report.messages))

        default_health = sinks.TraceSink(os.path.join(root, "isolated.jsonl"))
        if default_health._health is not sinks._health:
            pass_("a constructed sink defaults to a private health, not the "
                  "process-wide one")
        else:
            fail("constructed sink shares the process-wide health — a direct "
                 "construction would pollute the shared episode dict")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_trace_sink_creates_missing_directories():
    """TraceSink.write creates missing parent directories and writes the entry.

    Guards the makedirs self-heal: a deleted trace directory must recover on
    the next write with no intervention.
    """
    print("\n--- Test: Trace Sink Creates Missing Directories ---")

    root = tempfile.mkdtemp(prefix="proxy_trace_mkdir_")
    target = os.path.join(root, "missing", "nested", "trace.jsonl")
    try:
        ok = sinks.TraceSink(target).write({"event": "sink_mkdir_probe", "value": 1})
        if ok is True:
            pass_("TraceSink.write returned True")
        else:
            fail("TraceSink.write returned {!r}, expected True".format(ok))
            return
        if not os.path.exists(target):
            fail("trace file not created at {!r}".format(target))
            return
        pass_("missing parent directories were created and the entry written")

        with open(target) as f:
            lines = [l for l in f if l.strip()]
        if len(lines) == 1 and json.loads(lines[0])["event"] == "sink_mkdir_probe":
            pass_("entry round-trips through the newly created directory")
        else:
            fail("unexpected trace contents: {!r}".format(lines))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_trace_sink_markers_write_to_own_path():
    """The lifecycle markers land in the constructed sink's own file, carrying
    the port, this process's pid, and the counters read back under the lock."""
    print("\n--- Test: Trace Sink Markers Write To Own Path ---")

    root = tempfile.mkdtemp(prefix="proxy_sinks_markers_")
    target = os.path.join(root, "trace.jsonl")
    port = 8123
    try:
        sink = sinks.TraceSink(target)
        sink.count_request()
        sink.count_request()
        sink.count_retry()

        started = sink.start_marker(port)
        if started is True:
            pass_("start_marker returned the write result (True)")
        else:
            fail("start_marker returned {!r}, expected True — the startup "
                 "fail-fast reads this value".format(started))

        sink.stop_marker()

        if not os.path.exists(target):
            fail("markers did not reach the sink's own path {!r}".format(target))
            return
        with open(target) as f:
            lines = [json.loads(l) for l in f if l.strip()]

        if len(lines) == 2:
            pass_("exactly 2 marker lines in the sink's own file")
        else:
            fail("expected 2 marker lines, got {}: {!r}".format(len(lines), lines))
            return

        start, stop = lines
        if (start.get("event") == "proxy_start" and start.get("port") == port
                and start.get("pid") == os.getpid()):
            pass_("proxy_start carries port={} and pid={}".format(port, os.getpid()))
        else:
            fail("unexpected proxy_start marker: {!r}".format(start))

        if (stop.get("event") == "proxy_stop"
                and stop.get("requests_total") == 2
                and stop.get("requests_retried") == 1
                and stop.get("pid") == os.getpid()):
            pass_("proxy_stop carries requests_total=2, requests_retried=1")
        else:
            fail("unexpected proxy_stop marker: {!r}".format(stop))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_state_sink_write_round_trips():
    """StateSink.write emits one JSON document at its own path, atomically.

    The class exposes no read(); the document is read back with json.load, as
    the state file has no in-process consumer.
    """
    print("\n--- Test: State Sink Write Round Trips ---")

    root = tempfile.mkdtemp(prefix="proxy_sinks_state_")
    target = os.path.join(root, "nested", "state.json")
    payload = {"pid": 4242, "port": 8123, "last_heartbeat": "2026-09-12T00:00:00Z"}
    try:
        ok = sinks.StateSink(target).write(payload)
        if ok is True:
            pass_("StateSink.write returned True")
        else:
            fail("StateSink.write returned {!r}, expected True".format(ok))
            return
        if not os.path.exists(target):
            fail("state document not written at {!r}".format(target))
            return
        with open(target) as f:
            got = json.load(f)
        if got == payload:
            pass_("state document round-trips: {!r}".format(got))
        else:
            fail("expected {!r}, read back {!r}".format(payload, got))

        leftovers = [n for n in os.listdir(os.path.dirname(target))
                     if n.endswith(".tmp")]
        if not leftovers:
            pass_("no .tmp file left behind (os.replace cleaned up)")
        else:
            fail("temp file left behind: {!r}".format(leftovers))
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ===========================================================================
# configure(): the process-wide sink pair
# ===========================================================================

def test_configure_rebinds_paths_and_resets_counters():
    """A rebuild rebinds the path and starts fresh counters; an omitted
    (None) argument keeps the sink it belongs to."""
    print("\n--- Test: Configure Rebinds Paths And Resets Counters ---")

    saved = (sinks._trace, sinks._state, sinks._health)
    root = tempfile.mkdtemp(prefix="proxy_sinks_configure_")
    first = os.path.join(root, "first.jsonl")
    second = os.path.join(root, "second.jsonl")
    state_path = os.path.join(root, "state.json")
    try:
        sinks.configure(trace_path=first, state_path=state_path)
        sinks.increment_total()
        sinks.increment_retried()

        # Second call: only the trace path is given, so the state sink keeps
        # the path it already had.
        sinks.configure(trace_path=second)

        if sinks._trace._path == second:
            pass_("second configure() rebound the trace path to {!r}".format(second))
        else:
            fail("trace path after the second configure(): {!r}".format(
                sinks._trace._path))
        if sinks._state._path == state_path:
            pass_("omitted state_path kept the existing state sink path")
        else:
            fail("state path changed to {!r} — None did not mean 'keep'".format(
                sinks._state._path))

        sinks.write_stop_marker()
        if not os.path.exists(second):
            fail("stop marker did not reach the rebound path {!r}".format(second))
            return
        with open(second) as f:
            marker = json.loads([l for l in f if l.strip()][-1])
        if (marker.get("requests_total") == 0
                and marker.get("requests_retried") == 0):
            pass_("a rebuild started fresh counters (0 / 0), not the pre-rebind "
                  "totals")
        else:
            fail("expected fresh counters 0/0 after the rebuild, got {!r}".format(
                marker))
        if os.path.exists(first):
            fail("a stale trace file was still written at {!r}".format(first))
        else:
            pass_("nothing was written to the superseded trace path")
    finally:
        sinks._trace, sinks._state, sinks._health = saved
        shutil.rmtree(root, ignore_errors=True)


def test_configure_health_only_rebinds_live_sinks():
    """configure(health=H) reaches BOTH live sinks, and a health-only call does
    not reset the counters.

    This is what makes a test-time health injection meaningful: _Sink captures
    its health at construction, so rebinding only the module-level reference
    would leave the injected object unconsulted.
    """
    print("\n--- Test: Configure Health Only Rebinds Live Sinks ---")

    saved = (sinks._trace, sinks._state, sinks._health)
    root = tempfile.mkdtemp(prefix="proxy_sinks_health_")
    trace_path = os.path.join(root, "trace.jsonl")
    state_path = os.path.join(root, "state.json")
    try:
        sinks.configure(trace_path=trace_path, state_path=state_path)
        sinks.increment_total()

        report = _CapturedReport()
        injected = sinks._SinkHealth(report=report)
        sinks.configure(health=injected)

        if sinks._trace._health is injected and sinks._state._health is injected:
            pass_("injected health reached both live sinks")
        else:
            fail("injected health did not reach both sinks (trace={!r}, "
                 "state={!r})".format(sinks._trace._health is injected,
                                      sinks._state._health is injected))

        # A health-only configure must not reset the counters: the stop marker
        # still reports the increment made before the injection.
        sinks.write_stop_marker()
        with open(trace_path) as f:
            marker = json.loads([l for l in f if l.strip()][-1])
        if marker.get("requests_total") == 1:
            pass_("health-only configure preserved the counters "
                  "(requests_total=1)")
        else:
            fail("health-only configure reset the counters: {!r}".format(marker))

        # Drive a failure through a delegate and observe it on the injected
        # health, not on the process-wide one. The state path's parent is a
        # regular file, so the sink's directory guard fails deterministically
        # (and the rebuild inherits the injected health, which is the point).
        not_a_dir = os.path.join(root, "not-a-directory")
        with open(not_a_dir, "w") as f:
            f.write("")
        sinks.configure(state_path=os.path.join(not_a_dir, "state.json"))
        result = sinks.write_state({"pid": 1})
        if result is False:
            pass_("write_state returned False through the rebound state sink")
        else:
            fail("write_state returned {!r}, expected False".format(result))
        warnings = report.matching("state sink write failed")
        if len(warnings) == 1:
            pass_("the injected health observed the episode: {!r}".format(
                warnings[0]))
        else:
            fail("expected exactly 1 failure on the injected health, got "
                 "{}".format(len(warnings)))
    finally:
        sinks._trace, sinks._state, sinks._health = saved
        shutil.rmtree(root, ignore_errors=True)


# ===========================================================================
# Plan 2026-09-15-sanitize-sinks-deferred: chmod, empty path, replace
# failure, and concurrent-writer integrity
# ===========================================================================

def test_chmod_posix_mode_and_swallow():
    """POSIX-gated: after a write through either sink, the landed file's mode
    is 0600; and a failing os.chmod is swallowed — write still returns True
    and the payload lands.

    Skipped on Windows by design: os.chmod there is a near-no-op (read-only
    bit only), so the POSIX-only branch in _Sink.write never executes on the
    dev box. Do not delete this test for being permanently skipped — it
    gates the branch on every POSIX environment.
    """
    print("\n--- Test: Chmod POSIX Mode And Swallow ---")
    if os.name != "posix":
        pass_("skipped on Windows — POSIX chmod branch by design; see "
              "docstring")
        return

    root = tempfile.mkdtemp(prefix="proxy_sinks_chmod_")
    trace_path = os.path.join(root, "trace.jsonl")
    state_path = os.path.join(root, "state.json")
    try:
        trace_ok = sinks.TraceSink(trace_path).write({"event": "chmod_probe"})
        state_ok = sinks.StateSink(state_path).write({"pid": 1})
        if trace_ok is True and state_ok is True:
            pass_("both sinks wrote successfully")
        else:
            fail("sink write failed (trace={!r}, state={!r})".format(
                trace_ok, state_ok))
            return

        for label, path in [("trace", trace_path), ("state", state_path)]:
            mode = stat.S_IMODE(os.stat(path).st_mode)
            if mode == 0o600:
                pass_("{} sink file landed with mode 0600".format(label))
            else:
                fail("{} sink file mode is {:o}, expected 600".format(
                    label, mode))

        with unittest.mock.patch(
                "claude_retry_proxy.sinks.os.chmod",
                side_effect=OSError(1, "chmod denied")):
            ok = sinks.TraceSink(
                os.path.join(root, "swallow.jsonl")).write(
                {"event": "chmod_swallow_probe"})
        if ok is not True:
            fail("write returned {!r} with a failing chmod, expected True"
                 .format(ok))
            return
        with open(os.path.join(root, "swallow.jsonl")) as f:
            landed = json.loads([l for l in f if l.strip()][-1])
        if landed.get("event") == "chmod_swallow_probe":
            pass_("a failing chmod is swallowed and the payload landed")
        else:
            fail("payload did not land past a failing chmod: {!r}".format(
                landed))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_state_sink_empty_path_rejected_no_stray_tmp():
    """StateSink("") rejects the write before any file is created: write
    returns False and the pre-fix stray '.tmp' (a file literally named
    '.tmp' in the process CWD, from open('' + '.tmp')) does not exist.

    The assertion is name-pinned against os.getcwd() rather than a
    before/after set-diff snapshot, so the result does not depend on other
    CWD activity and holds whatever the CWD is.
    """
    print("\n--- Test: State Sink Empty Path Rejected No Stray Tmp ---")
    sink = sinks.StateSink("")
    result = sink.write({"pid": 1})
    if result is not False:
        fail("StateSink(\"\").write returned {!r}, expected False".format(
            result))
        return
    pass_("empty-path write returned False")
    if os.path.exists(".tmp"):
        fail("stray '.tmp' exists at the CWD {!r} — the empty-path guard "
             "did not fire before file creation".format(os.getcwd()))
    else:
        pass_("no stray '.tmp' at the CWD")


def test_state_sink_replace_failure_leaves_no_temp():
    """A failing os.replace (realistic on Windows: a reader holds the state
    file open) returns False via the swallow path AND unlinks the unique
    mkstemp temp — none accumulates in the target directory."""
    print("\n--- Test: State Sink Replace Failure Leaves No Temp ---")
    root = tempfile.mkdtemp(prefix="proxy_sinks_replace_")
    target = os.path.join(root, "state.json")
    try:
        with unittest.mock.patch(
                "claude_retry_proxy.sinks.os.replace",
                side_effect=PermissionError(13, "denied")):
            ok = sinks.StateSink(target).write({"pid": 1})
        if ok is not False:
            fail("write returned {!r} with a failing replace, expected "
                 "False".format(ok))
            return
        pass_("replace-failure write returned False")
        leftovers = os.listdir(root)
        if leftovers:
            fail("stray temp files left in the target directory after a "
                 "replace failure: {!r}".format(leftovers))
        else:
            pass_("no leftover temp in the target directory")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_state_sink_concurrent_writes_last_writer_wins():
    """N >= 16 concurrent writers through one StateSink produce exactly one
    complete payload — the unique-temp + atomic-replace design needs no
    mutex — and no temp file survives in the target directory."""
    print("\n--- Test: State Sink Concurrent Writes Last Writer Wins ---")
    root = tempfile.mkdtemp(prefix="proxy_sinks_concurrent_")
    target = os.path.join(root, "state.json")
    payloads = [{"payload": i, "marker": "w{}".format(i)} for i in range(16)]
    try:
        sink = sinks.StateSink(target)
        results = []

        def writer(p):
            results.append(sink.write(p))

        def writer_wrapped(p):
            try:
                writer(p)
            except Exception as e:
                results.append(e)

        threads = [threading.Thread(target=writer_wrapped, args=(p,))
                   for p in payloads]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        bad = [r for r in results if isinstance(r, Exception)]
        if bad:
            fail("writer threads raised: {!r}".format(bad))
            return
        # False is a valid result under the never-raise contract: on Windows
        # a concurrent os.replace can transiently hit PermissionError, and
        # the failure path handles it (unlink temp, return False). What must
        # hold is: no exceptions, exactly one complete payload in the file,
        # and no leftover temps.
        lost = [r for r in results if r is not True]
        if lost:
            pass_("{}/{} writes returned False (swallowed replace races on "
                  "Windows; documented never-raise contract)".format(
                      len(lost), len(payloads)))
        else:
            pass_("all {} writes returned True".format(len(payloads)))
        with open(target) as f:
            landed = json.load(f)
        if landed in payloads:
            pass_("file holds exactly one complete payload ({!r}) — last "
                  "writer wins, no interleaving".format(landed))
        else:
            fail("file content is not one of the writer payloads "
                 "(interleaving or corruption): {!r}".format(landed))
        leftovers = [n for n in os.listdir(root) if n != "state.json"]
        if not leftovers:
            pass_("no leftover temp files in the target directory")
        else:
            fail("stray files in the target directory: {!r}".format(leftovers))
    finally:
        shutil.rmtree(root, ignore_errors=True)


ALL_TESTS = [
    ("sink-warning-rate-limit", test_sink_warning_rate_limit),
    ("sink-recovery-notice", test_sink_recovery_notice),
    ("sink-write-contract-class-level", test_sink_write_contract_class_level),
    ("trace-sink-creates-missing-directories", test_trace_sink_creates_missing_directories),
    ("trace-sink-markers-own-path", test_trace_sink_markers_write_to_own_path),
    ("state-sink-write-round-trips", test_state_sink_write_round_trips),
    ("configure-rebinds-paths-and-resets-counters",
     test_configure_rebinds_paths_and_resets_counters),
    ("configure-health-only-rebinds-live-sinks",
     test_configure_health_only_rebinds_live_sinks),
    ("chmod-posix-mode-and-swallow", test_chmod_posix_mode_and_swallow),
    ("state-sink-empty-path-rejected-no-stray-tmp",
     test_state_sink_empty_path_rejected_no_stray_tmp),
    ("state-sink-replace-failure-leaves-no-temp",
     test_state_sink_replace_failure_leaves_no_temp),
    ("state-sink-concurrent-writes-last-writer-wins",
     test_state_sink_concurrent_writes_last_writer_wins),
]

if __name__ == "__main__":
    run_cli(ALL_TESTS, "Sink class family unit tests")
