"""Durable output sinks: the trace JSONL append and the atomic state document.

The trace and state sinks are written from the request path and the heartbeat
thread. Their writes must never raise into the caller: a trace-write OSError
inside the retry loop's `except (socket.error, ConnectionError, OSError)`
clause would be misread as a connection error and re-issue the upstream POST.
Failures are recorded by a shared `_SinkHealth` and reported on stderr at most
once per interval.
"""

import json
import os
import sys
import tempfile
import threading
import time

from .sanitize import sanitize_error

__all__ = [
    "TraceSink", "StateSink", "configure", "log_trace", "write_state",
    "increment_total", "increment_retried",
    "write_start_marker", "write_stop_marker",
]

SINK_WARN_INTERVAL = 60.0


def _stderr_report(message):
    """Default failure report. Resolves sys.stderr at call time, not at import.

    Binding the stream here would bypass the _BestEffortStderr wrapper the
    server installs at startup.
    """
    print(message, file=sys.stderr)


class _SinkHealth:
    """Records failed sink writes and warns on stderr, rate-limited per sink.

    Shared by both sinks, keyed by sink name — matching the single episode
    dict that served both before the extraction. The first failure of an
    episode always warns; later failures warn at most once per interval and
    report how many were suppressed. Carries only the sink name and the
    sanitized cause — never the entry contents, which can hold raw prompts
    under --all.
    """

    def __init__(self, interval=SINK_WARN_INTERVAL, clock=time.time, report=_stderr_report):
        self._interval = interval
        self._clock = clock
        self._report = report
        self._lock = threading.Lock()
        self._state = {}

    def failure(self, name, exc):
        now = self._clock()
        with self._lock:
            entry = self._state.setdefault(
                name, {"failed": False, "last_warn": 0.0, "episode": 0,
                       "since_warn": 0})
            entry["episode"] += 1
            if not entry["failed"]:
                entry["failed"] = True
                emit, suppressed = True, 0
            else:
                suppressed = entry["since_warn"]
                emit = now - entry["last_warn"] >= self._interval
                if not emit:
                    entry["since_warn"] += 1
            if emit:
                entry["last_warn"] = now
                entry["since_warn"] = 0
        if not emit:
            return
        detail = (" ({} further failures suppressed)".format(suppressed)
                  if suppressed else "")
        try:
            self._report("[proxy] WARNING: {} sink write failed{}: {}".format(
                name, detail, sanitize_error(str(exc))))
        except Exception:
            pass

    def success(self, name):
        """Close a sink's failure episode, reporting its dropped-write count once."""
        with self._lock:
            entry = self._state.pop(name, None)
        if entry is None:
            return
        try:
            self._report("[proxy] WARNING: {} sink write resumed after {} failed "
                         "write(s)".format(name, entry["episode"]))
        except Exception:
            pass


class _Sink:
    """Private base for the durable sinks: path, name, health, shared write path.

    Nothing outside this module subclasses it; the shared policy is exercised
    through either concrete sink.
    """

    def __init__(self, path, name, health):
        self._path = path
        self._name = name
        self._health = health if health is not None else _SinkHealth()

    def _emit(self, payload):
        raise NotImplementedError

    def write(self, payload):
        """Emit one payload. Returns True on success, False on failure.

        Never raises: callers include the retry loop's error paths, where an
        escaping OSError would be misclassified as a connection error and
        re-issue the upstream POST, and the heartbeat thread, which a failing
        state sink must not kill. A payload or path that raises something
        other than OSError (a non-serializable entry, an unset path) is caught
        by the same handler rather than propagating.
        """
        try:
            d = os.path.dirname(self._path)
            if d:
                os.makedirs(d, exist_ok=True)
            self._emit(payload)
            # Restrict permissions on POSIX (best-effort; Windows chmod is a near-no-op).
            if os.name == "posix":
                try:
                    os.chmod(self._path, 0o600)
                except OSError:
                    pass
        except Exception as e:
            self._health.failure(self._name, e)
            return False
        self._health.success(self._name)
        return True


class TraceSink(_Sink):
    """Append-only JSONL sink, plus the request counters and the lifecycle markers."""

    def __init__(self, path, name="trace", health=None):
        super().__init__(path, name, health)
        self._lock = threading.Lock()
        self._counter_lock = threading.Lock()
        self._total = 0
        self._retried = 0

    def _emit(self, payload):
        with self._lock:
            with open(self._path, "a") as f:
                f.write(json.dumps(payload) + "\n")

    def count_request(self):
        with self._counter_lock:
            self._total += 1

    def count_retry(self):
        with self._counter_lock:
            self._retried += 1

    def start_marker(self, port):
        """Write the proxy_start marker. Returns the sink write result."""
        return self.write({
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
            "event": "proxy_start",
            "port": port,
            "pid": os.getpid()
        })

    def stop_marker(self):
        # Read the counters under the lock, release it, then write: holding the
        # non-reentrant lock across self.write() would self-deadlock.
        with self._counter_lock:
            total = self._total
            retried = self._retried
        self.write({
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
            "event": "proxy_stop",
            "pid": os.getpid(),
            "requests_total": total,
            "requests_retried": retried
        })


class StateSink(_Sink):
    """Atomic replace of one JSON document. Unique per-write temp names make
    concurrent writers safe without a mutex; an empty path is rejected before
    any file is created."""

    def __init__(self, path, name="state", health=None):
        super().__init__(path, name, health)

    def _emit(self, payload):
        if not self._path:
            raise ValueError("state sink path is empty")
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(self._path))
        try:
            try:
                f = os.fdopen(fd, "w", encoding="utf-8")
            except Exception:
                os.close(fd)
                raise
            with f:
                json.dump(payload, f)
            os.replace(tmp, self._path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise


_health = _SinkHealth()
# path=None until configure() runs: this module must import without the server,
# so it cannot resolve a real path and must never guess one.
_trace = TraceSink(None, health=_health)
_state = StateSink(None, health=_health)


def configure(*, trace_path=None, state_path=None, health=None):
    """Rebind the process-wide sinks. `None` means "keep".

    Tested with `is not None`, so an empty-string path is passed through rather
    than silently ignored. A rebuild rebinds the path and starts fresh
    counters; a health-only call rebinds the health on both live sinks and does
    not reset the counters.
    """
    global _health, _trace, _state
    if health is not None:
        _health = health
    if trace_path is not None:
        _trace = TraceSink(trace_path, health=_health)
    else:
        _trace._health = _health
    if state_path is not None:
        _state = StateSink(state_path, health=_health)
    else:
        _state._health = _health


def log_trace(entry):
    """Append one trace entry. Returns True on success, False on failure."""
    return _trace.write(entry)


def write_state(state):
    """Write the state file. Returns True on success, False on failure."""
    return _state.write(state)


def increment_total():
    _trace.count_request()


def increment_retried():
    _trace.count_retry()


def write_start_marker(port):
    """Write the proxy_start trace marker. Returns the sink write result."""
    return _trace.start_marker(port)


def write_stop_marker():
    _trace.stop_marker()
