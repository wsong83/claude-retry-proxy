"""Shared fixtures for the compatibility-learning tests.

The cross-cluster constants (the 400-body constants, the shared
rejected-body corpus, the reasoning complaint body) and the fixture helpers
every compat test module drives the live learning flow with. Members moved
byte-verbatim from tests/test_compat.py (plan
2026-11-26-partition-test-compat); single-cluster helpers live in their
cluster files."""

import json
import os
import shutil
import tempfile

from _harness import (
    _mode_tiers,
    _send_proxy_request,
    _start_mode_proxy,
    fail,
    find_free_port,
    warn,
)


STATE_ENV = "PROXY_FEATURE_COMPAT_FILE"


# The exact 400 body observed from opencode-zen-claude (deferred issue
# opencode-zen-claude-rejects-extra-inputs): message form ending in
# "context_management: Extra inputs are not permitted", token preceded by "] ".
OBSERVED_400_BODY = json.dumps({
    "type": "error",
    "error": {
        "type": "invalid_request_error",
        "message": "Error from provider (Console): Upstream request failed: "
                   "[invalid_request_error] context_management: "
                   "Extra inputs are not permitted",
    },
}).encode()


# Rejected-body corpus shared by the context_management detector scenarios and
# the reasoning matcher's unit test: (label, status, body_bytes) triples that
# are NOT complaints for either feature. The two matchers are structurally
# parallel by design, so one table is what keeps them from drifting apart.
# Accept-side cases stay separate — they differ by field-name constant.
REJECTED_BODY_CORPUS = [
    ("http-500", 500, json.dumps({
        "type": "error",
        "error": {"type": "api_error", "message": "upstream exploded"},
    }).encode()),
    ("http-2xx-success", 200, json.dumps({
        "id": "msg_ok", "type": "message", "role": "assistant", "model": "m",
        "content": [], "usage": {"input_tokens": 1, "output_tokens": 1},
    }).encode()),
    ("unparseable-body", 400, b"this is not json at all"),
    ("empty-body", 400, b""),
    ("json-array-body", 400, b'["context_management", "reasoning_content"]'),
]


CM_VALUE = {"edits": [{"type": "clear_tool_uses_20250901"}]}


CM_MARKER = "clear_tool_uses_20250901"


ERROR_MARKER = "Extra inputs are not permitted"


UPSTREAM_ERROR_MARKER = "Error from provider"


SSE_BODY = (
    b"event: message_start\n"
    b'data: {"type":"message_start","message":{"id":"msg_sse","type":"message",'
    b'"role":"assistant","model":"claude-sonnet-5","content":[],"stop_reason":null,'
    b'"usage":{"input_tokens":1,"output_tokens":1}}}\n'
    b"\n"
    b"event: content_block_delta\n"
    b'data: {"type":"content_block_delta","index":0,'
    b'"delta":{"type":"text_delta","text":"hi"}}\n'
    b"\n"
    b"event: message_stop\n"
    b'data: {"type":"message_stop"}\n'
    b"\n"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _cm_request(model="sonnet", include_cm=True, text="hello"):
    body = {
        "model": model,
        "max_tokens": 16,
        "messages": [{"role": "user", "content": [{"type": "text", "text": text}]}],
    }
    if include_cm:
        body["context_management"] = CM_VALUE
    return body


def _send(port, body, path="/v1/messages"):
    return _send_proxy_request(port, path=path, body=json.dumps(body))


def _make_state_dir():
    d = tempfile.mkdtemp(prefix="compat_state_")
    return d, os.path.join(d, "feature-compatibility.json")


def _read_state_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _write_state_file(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f)


# 400 bodies naming a reasoning field, in the content shapes a real gateway
# uses. All are built from the field-name constants; none carries upstream
# prose the matcher depends on.
REASONING_MESSAGE_400 = json.dumps({
    "type": "error",
    "error": {
        "type": "invalid_request_error",
        "message": "The reasoning_content in the thinking mode must be passed "
                   "back to the API.",
    },
}).encode()


def _reasoning_request(model="sonnet", with_thinking=True, text="hello",
                       demanding=False):
    """A chat-mode client request. `with_thinking` appends an assistant turn
    carrying a thinking block — a presence signal for the reasoning feature.

    `demanding=True` makes that turn a DEMANDING turn: it carries a tool_use
    block, answered by a trailing user tool_result. The credit gate is
    demanding-turn scoped (2026-10-22-reasoning-roundtrip-compliance Step 5),
    so only a demanding turn feeds the learner; every credit/switch test must
    opt in. The default shape (thinking + text, no tool_use) stays available
    for the documented no-tool-call rescue case, whose passes remain same-body
    re-rolls.
    """
    body = {
        "model": model,
        "max_tokens": 16,
        "messages": [
            {"role": "user", "content": [{"type": "text", "text": text}]},
        ],
    }
    if demanding:
        content = []
        if with_thinking:
            content.append({"type": "thinking", "thinking": "hmm",
                            "signature": "s"})
        content.append({"type": "tool_use", "id": "toolu_demand",
                        "name": "lookup", "input": {"q": text}})
        body["messages"].append({"role": "assistant", "content": content})
        body["messages"].append({
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "toolu_demand",
                         "content": "ok"}],
        })
    elif with_thinking:
        body["messages"].append({
            "role": "assistant",
            "content": [
                {"type": "thinking", "thinking": "hmm", "signature": "s"},
                {"type": "text", "text": "ok"},
            ],
        })
    return body


def _sent_reasoning_field(info):
    """The reasoning field the proxy actually sent upstream, or None.

    Read from the mock upstream's recorded request, so it observes the bytes
    that really left the proxy rather than any internal call record.
    """
    try:
        body = json.loads(info["body"])
    except Exception:
        return None
    for m in body.get("messages", []):
        if not isinstance(m, dict) or m.get("role") != "assistant":
            continue
        for f in ("reasoning_content", "reasoning"):
            if f in m:
                return f
    return None


def _chat_ok_response(info):
    """A minimal OpenAI chat-completions 2xx body."""
    try:
        model = json.loads(info["body"]).get("model", "unknown")
    except Exception:
        model = "unknown"
    return 200, "application/json", json.dumps({
        "id": "chatcmpl-ok", "object": "chat.completion", "created": 1,
        "model": model,
        "choices": [{"index": 0, "message": {"role": "assistant",
                                             "content": "hi"},
                     "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1,
                  "total_tokens": 2},
    }).encode()


def _chat_vendor(port):
    """A single chat-mode vendor spec pointing at a mock upstream."""
    return {"url": "http://127.0.0.1:%d" % port, "key": "K", "mode": "chat"}


def _entries(state):
    return state.get("entries", {})


def _entry_values(entries):
    return list(entries.values()) if isinstance(entries, dict) else []


def _reject_unstripped_responder(ok_body="json"):
    """400 with the observed error for bodies containing context_management,
    2xx otherwise. Drives both discovery (unstripped 400) and stripping."""

    def responder(info):
        try:
            has_cm = "context_management" in json.loads(info["body"])
        except Exception:
            has_cm = False
        if has_cm:
            return 400, "application/json", OBSERVED_400_BODY
        return _ok_response(info, ok_body)

    return responder


def _ok_response(info, kind="json"):
    try:
        model = json.loads(info["body"]).get("model", "unknown")
    except Exception:
        model = "unknown"
    if kind == "sse":
        return 200, "text/event-stream", SSE_BODY
    if kind == "truncated-sse":
        return 200, "text/event-stream", SSE_BODY[:80]
    body = json.dumps({
        "id": "msg_ok", "type": "message", "role": "assistant",
        "model": model,
        "content": [{"type": "text", "text": "hello"}],
        "stop_reason": "end_turn", "stop_sequence": None,
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }).encode()
    return 200, "application/json", body


def _cm_count(requests):
    """Number of recorded upstream requests whose body contained
    context_management."""
    n = 0
    for r in requests:
        try:
            if "context_management" in json.loads(r["body"]):
                n += 1
        except Exception:
            pass
    return n


def _compat_trace_events(trace_file, name=None, prefix="compatibility_"):
    """Trace events whose name starts with `prefix`, optionally one exact name.

    The default prefix scopes the result to the compatibility learner's own
    event family. `reasoning_rescue` is a server-emitted event (not a learner
    event), so it is read through `_rescue_trace_events` below.
    """
    out = []
    if not trace_file or not os.path.exists(trace_file):
        return out
    with open(trace_file) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except Exception:
                continue
            ev_name = ev.get("event", "")
            if ev_name.startswith(prefix):
                if name is None or ev_name == name:
                    out.append(ev)
    return out


def _rescue_trace_events(trace_file):
    """Every server-emitted `reasoning_rescue` event, in file order."""
    return _compat_trace_events(trace_file, prefix="reasoning_rescue")


def _start_compat_proxy(responders, state_path, tiers=None, vendors=None,
                        extra_env=None, reasoning_field_switch=None):
    """Start a proxy with an isolated compatibility state file."""
    if tiers is None:
        tiers = _mode_tiers()
    if vendors is None:
        upstream_port = find_free_port()
        vendors = {"p": {"url": "http://127.0.0.1:%d" % upstream_port,
                         "key": "K"}}
    env = {STATE_ENV: state_path}
    if extra_env:
        env.update(extra_env)
    return _start_mode_proxy(tiers, vendors, responders=responders,
                             extra_env=env,
                             reasoning_field_switch=reasoning_field_switch)


def _bootstrap_learned_state(model="claude-sonnet-5", state="unsupported"):
    """Start a throwaway proxy and learn context_management-unsupported.

    Returns (state_dir, state_path). The proxy is stopped before returning;
    the caller owns state_dir cleanup. This bootstraps a state file in the
    implementation's own format so later tests can mutate plan-pinned fields
    without knowing the entry-key layout.
    """
    state_dir, state_path = _make_state_dir()
    tiers = _mode_tiers(model=model)
    responders = {"p": _reject_unstripped_responder()}
    temp_dir, proxy_port, proc, mock_servers, trace_file, cleanup = \
        _start_compat_proxy(responders, state_path, tiers=tiers)
    if proc is None:
        shutil.rmtree(state_dir, ignore_errors=True)
        fail("bootstrap proxy failed to start")
        return state_dir, state_path
    try:
        status, _ = _send(proxy_port, _cm_request())
        if status != 200:
            fail("bootstrap learning request returned %s" % status)
    finally:
        cleanup()
    return state_dir, state_path


def _mutate_entry(state_path, mutate, expect_count=1):
    """Apply mutate(entry_dict) to every entry whose feature is
    context_management; write the file back in place."""
    state = _read_state_file(state_path)
    if state is None:
        fail("cannot read bootstrapped state file at %s" % state_path)
        return
    touched = 0
    for entry in _entry_values(_entries(state)):
        if isinstance(entry, dict) and entry.get("feature") == "context_management":
            mutate(entry)
            touched += 1
    if touched != expect_count:
        warn("entry mutation touched %d entries (expected %d)"
             % (touched, expect_count))
    _write_state_file(state_path, state)


def _walk_strips(port, mock, n):
    """Send n matching requests, asserting each is stripped (exactly one
    upstream call whose body lacks context_management).

    Strip counters are in-memory-only (reset to zero on state-file load), so
    threshold tests reach the probe by walking the counter in memory.
    """
    for i in range(n):
        before = len(mock["requests"])
        status, _ = _send(port, _cm_request())
        reqs = mock["requests"][before:]
        if status != 200 or len(reqs) != 1 or _cm_count(reqs) != 0:
            fail("stripped request %d unexpected (%s, %d calls, %d with cm)"
                 % (i + 1, status, len(reqs), _cm_count(reqs)))
            return False
    return True
