# Plan: Replace the retry-nudge marker's stored messages copy with a prefix digest, drop the size cap, raise the entry cap to 64, and make the skip visible on the wire
**Project:** D:\proj\claude-retry-proxy
**Plan ID:** 2026-10-18-retry-nudge-digest-store
**Created:** 2026-10-18
**Verification state at close:** `./tmp/verification/2026-10-18-retry-nudge-digest-store-step1.py` reads **11/11 PASS** against the shipped `src/claude_retry_proxy/server.py`. The full suite reads **428 passed / 0 failed** and `tests/test_chat_sse.py` **76/76**, no skips. Both doc gates PASS: `scripts/check_doc_anchors.py` (206 anchors resolved, no secret shapes) and `doc_structure_check.py` (9 files, no violations). The load-bearing calibration `step3-head-calibration.py` is **red against `HEAD` and green against the tree**, driven by the shipped test body rather than a paraphrase. Reviewer verdict: **Issues found — non-blocking** (0 Critical / 2 Warning / 2 Suggestion), report `./tmp/reports/2026-10-18-retry-nudge-digest-store-review-2026-10-18.json`.

## Immediate Actions

**Phase 6 review is complete and the gate passed** — 0 Critical findings, so nothing
blocks the commit. All three steps are landed and verified: Step 1 gate 11/11 PASS;
Step 2 module 76/76 and suite 428/428; Step 3 doc gates PASS.

**Two non-blocking Warnings are recorded but not fixed.** Both are defects in
plan-supplied *text* rather than in behaviour, and both are cheap:

1. `_retry_nudge_remember` encodes the canonical string twice — once to hash it
   (`server.py:339`), once to take its length (`:350`) — which contradicts this
   plan's own cost note claiming the field "costs one `len()` and no extra
   serialization". Measured on the test's own 1,500,086-byte fixture: the second
   encode is 0.82 ms plus a 1.5 MB transient, against 0.0003 ms for
   `len(canonical_bytes)`. Fix: bind the encoded bytes once and use it for both.
2. The new accessor's docstring states `None` ⇔ "the marker was never stored (an
   ineligible body)". That equivalence is false: the read is taken *before* the arm,
   so the entry is unarmed, and the cap victimises the oldest unarmed entry — which
   is exactly a long in-flight generation. `None` therefore also means "stored, then
   evicted" (and, on a re-entry, "armed then swept"). `doc/trace-log.html` repeats
   the weaker form. This is the same class of stale-claim defect the coder caught
   twice during the rounds.

Two Suggestions are likewise recorded: there is no *behavioural* pin for the
key-order-insensitivity that `sort_keys=True` exists for (only the gate's substring
check guards it), and the digest's equivalence class differs from the removed `==`
comparison in two directions where only one was documented.

**Awaiting user approval.** The implementation is ready to commit as it stands; say
the word if you want findings 1–2 fixed first, which is a small coder round plus a
plan/doc revision.

## Issue Log

Rows ordered newest-first (latest issues at top). New issues are prepended; resolved issues stay in place with updated status.

| Issue | Status | Found | Resolved | Resolved By |
|-------|--------|-------|----------|-------------|
| retry-nudge-size-cap-kills-feature | Resolved | 2026-10-18 | 2026-10-18 | coder rounds 1–2 (Step 1), tester (Step 2) |
| [defer-issue-recursion-guard-residual-sites](./tmp/reports/defer-issue-recursion-guard-residual-sites.json) — **site 4 only** | Resolved (partial — sites 1–3 remain Open in the report) | 2026-10-18 | 2026-10-18 | planner (Step 1 Edits 2–4 deleted the Pass-2 `json.loads` re-parse; the report's `context` records the retirement and its `status` stays **Open**) |
| [step1-gate-names-removed-constant](./tmp/reports/2026-10-18-retry-nudge-digest-store-step1-gate-names-removed-constant.json) | Resolved | 2026-10-18 | 2026-10-18 | planner revision (Edit 5 docstring) |
| [arm-gate-comment-oversized-stale](./tmp/reports/2026-10-18-retry-nudge-digest-store-arm-gate-comment-oversized-stale.json) | Resolved | 2026-10-18 | 2026-10-18 | planner revision (Edit 7) + coder round 2 |

## Guidance for Coder

**Files to modify:** `src/claude_retry_proxy/server.py`

**Round completion — read this before you start.** Run any command that can spawn
a proxy or run a test with an explicit `timeout`, and **write your session report
before you end your turn, whatever the result.** A round that reports nothing is
treated as a failed round even when its code landed.

One cohesive change, seven edits. Five are inside the retry-nudge marker store at
`server.py:271-440`; the sixth is the fire-event payload at `server.py:3015-3028`;
the seventh is the stale rationale comment on the arm-gated error path at
`server.py:3065-3069`. The detector's predicate, the arm-gate's logic, the nudge
injection, the eviction loop, the sweep, and the eligibility wiring all stay
exactly as they are. The client wire format does not change; no new config is
added. The trace gains exactly one field, on one event.

### Step 1 — the digest store and the visible skip

**Edit 1 — the constants (`server.py:286-288`).** Delete the size cap; raise the
entry cap:

```python
RETRY_NUDGE_TTL_SECONDS = 180
RETRY_NUDGE_MAX_ENTRIES = 64
```

`RETRY_NUDGE_MAX_MESSAGES_BYTES` must not exist anywhere afterwards.

**Edit 2 — the module comment (`server.py:282-285`).** The block comment above the
constants currently ends:

```
# ... Bounded by RETRY_NUDGE_MAX_ENTRIES entries of at
# most RETRY_NUDGE_MAX_MESSAGES_BYTES of serialized messages each; cleared
# on restart, never persisted. Helpers never raise: ...
```

Replace that clause so it describes the digest bound:

```
# ... Bounded by RETRY_NUDGE_MAX_ENTRIES entries, each holding only a body
# hash, a prefix digest and the prefix's byte count — no messages copy;
# cleared on restart, never persisted. Helpers never raise: ...
```

**Edit 3 — `_retry_nudge_remember` (`server.py:317-367`).** Remove the size
skip, store a digest instead of the serialized copy, and retain the prefix's
byte count for the trace. **The docstring loses its size clause and gains the
digest description — it must not still name `RETRY_NUDGE_MAX_MESSAGES_BYTES`,
or the `cap-constant-removed` gate check fails.** Docstring and body together
become:

```python
def _retry_nudge_remember(request_id, body, body_json):
    """Store an unarmed marker for this chat request. True iff stored.

    Skips (mutating nothing) when request_id is falsy or already present (a
    compat/reasoning re-entry of the same request must not clobber an entry
    armed earlier in its lifecycle), or when messages is not a non-empty
    list of dicts. The marker holds a body hash, the prefix length, a
    prefix digest and the prefix's byte count — never a copy of the
    messages. At the entry cap, unarmed entries are evicted first (oldest
    first) and armed only as a last resort — armed entries are the ones
    with imminent recoveries.
    """
    if not request_id:
        return False
    messages = body_json.get("messages") if isinstance(body_json, dict) else None
    if not isinstance(messages, list) or not messages:
        return False
    if not all(isinstance(m, dict) for m in messages):
        return False
    try:
        canonical = json.dumps(messages, separators=(",", ":"), sort_keys=True)
        body_hash = hashlib.sha256(body).hexdigest()
        prefix_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    except (TypeError, ValueError, RecursionError):
        return False
    with _retry_nudge_lock:
        if request_id in _retry_nudge_entries:
            return False
        _retry_nudge_sweep()
        _retry_nudge_entries[request_id] = {
            "hash": body_hash,
            "prefix_len": len(messages),
            "prefix_hash": prefix_hash,
            "messages_bytes": len(canonical.encode("utf-8")),
            "armed": False,
            "stored_at": time.time(),
        }
        # ... the eviction while-loop is UNCHANGED ...
    return True
```

Contract points the gate pins:
- The serialization happens **before** the lock is acquired (it is the expensive
  part), exactly as today.
- `sort_keys=True` is required and is **not** cosmetic: it makes the digest
  order-insensitive to dict key order, which is what the old
  `messages[:len(stored)] == stored` list comparison did (Python dict `==` ignores
  key order). Both sides — here and in `_retry_nudge_check` — must use the
  identical `json.dumps(messages, separators=(",", ":"), sort_keys=True)` form.
- `messages_bytes` reuses the `canonical` string already computed for the digest
  — it costs one `len()` and no extra serialization. **Reusing `canonical` is
  exact, not approximate:** `sort_keys` reorders keys without changing their
  count or their separators, so the dump's length is identical with and without
  it. This is the *same* quantity the removed cap measured.
- The `except` tuple keeps `RecursionError` (the encode ceiling sits below the
  decode ceiling; see `doc/architecture.html#error-envelope`).
- `"messages_json"` is gone; the entry is now `hash` / `prefix_len` /
  `prefix_hash` / `messages_bytes` / `armed` / `stored_at`.
- The eviction `while len(...) > RETRY_NUDGE_MAX_ENTRIES:` loop, its
  unarmed-first/oldest-first victim scan, and the `_retry_nudge_sweep()` call are
  unchanged.

**Edit 4 — `_retry_nudge_check` Pass 2 (`server.py:424-439`).** Replace the
`json.loads(entry["messages_json"])` + list comparison with a prefix-digest
comparison. Pass 1 (the exact `sha256(body)` match) is unchanged. The Pass-2
block becomes:

```python
        # Pass 2: strict extension of the stored conversation prefix — the
        # recovery's messages start with the stored prefix AND are longer.
        # The store keeps a digest, not a copy, so re-serialize the candidate
        # prefix with the same canonical form remember used.
        messages = body_json.get("messages") if isinstance(body_json, dict) else None
        if not isinstance(messages, list) or not messages:
            return None
        if not all(isinstance(m, dict) for m in messages):
            return None
        for rid, entry in armed:
            prefix_len = entry.get("prefix_len")
            if not isinstance(prefix_len, int) or prefix_len <= 0:
                continue
            if len(messages) <= prefix_len:
                continue
            try:
                canonical = json.dumps(messages[:prefix_len],
                                       separators=(",", ":"), sort_keys=True)
                prefix_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            except (TypeError, ValueError, RecursionError):
                continue
            if prefix_hash == entry.get("prefix_hash"):
                del _retry_nudge_entries[rid]
                return rid
    return None
```

Contract points the gate pins:
- `len(messages) <= prefix_len: continue` is the strictness guard the old
  `len(messages) > len(stored)` expressed: an equal-length or shorter recovery is
  not a strict extension, and it is checked **before** any serialization so the
  common non-matching request pays nothing.
- The digest is compared with `==` against the stored hex string.
- The entry is still consumed (`del`) before returning; the single-use contract is
  untouched.
- `except (TypeError, ValueError, RecursionError): continue` preserves the
  no-raise discipline. This is also **the closure of site 4** of the open
  deferral `./tmp/reports/defer-issue-recursion-guard-residual-sites.json`: the
  old guard here caught only `(TypeError, ValueError)` around a `json.loads`, and
  that call no longer exists. The deferral's other three sites are out of scope
  and remain open.
- The docstring's "the new messages list starts with the stored list AND is
  longer" is still accurate; update "stored list" to "stored prefix" for precision.

**Edit 5 — a new accessor, after `_retry_nudge_arm` (`server.py` ~line 390).**
The fire site needs the stored byte count, and the store is reached only through
lock-encapsulating helpers — so add one:

```python
def _retry_nudge_messages_bytes(request_id):
    """The stored prefix's byte count for this request, or None if no marker.

    Read-only diagnostic companion to the fire event: a None here means the
    marker was never stored for this request (an ineligible body — falsy id,
    or messages not a non-empty list of dicts), while a number is the size of
    the serialized messages array the marker was built from. This is the
    quantity the removed messages-size cap measured, kept on the trace so a
    future skip is visible on the wire rather than inferred from session
    transcripts.
    """
    if not request_id:
        return None
    with _retry_nudge_lock:
        entry = _retry_nudge_entries.get(request_id)
        return entry.get("messages_bytes") if entry is not None else None
```

- It acquires the same lock as every other store access; it never mutates, so it
  is safe to call on the fire path before the arm decision.
- It returns `None` (never raises) for a falsy id or an absent entry — the
  no-raise discipline the module's other helpers follow.
- It does **not** sweep. A read must not mutate; the fire path's arm call
  performs the sweep under its own lock acquisition, moments later.

**Edit 6 — the fire-event payload (`server.py:3015-3028`).** The
`chat_sse_unfinished_turn` event gains one field. Add the read immediately
before the `log_trace({...})` call:

```python
                messages_bytes = _retry_nudge_messages_bytes(request_id)
                log_trace({
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "event": "chat_sse_unfinished_turn",
                    "request_id": request_id,
                    "tier": tier,
                    "provider": provider,
                    "key": key,
                    "finish_reason": finish_reason_seen,
                    "tool_calls_seen": 1 if tool_calls_seen else 0,
                    "emitted_tool_use": 1 if emitted_tool_use else 0,
                    "tools_declared": 1 if tools_declared else 0,
                    "text_tail_len": len(text_tail),
                    "messages_bytes": messages_bytes,
                    "rule": "colon_after_prose",
                })
```

Contract points the gate pins:
- The event is emitted for **every** fire, including one that goes on to pass
  through — the read must sit *before* the arm gate, not inside the arm branch.
- `messages_bytes` is `None` when no marker was stored and an int when one was.
  Post-fix every eligible fire stores a marker, so the expected steady state is
  **an int on every fire**; a `null` is the signal that the body was ineligible
  for a reason the detector's own gates allow.
- No other field on this event changes, and no other trace event changes.

**Edit 7 — the arm-gate rationale comment (`server.py:3065-3069`).** The comment
that justifies the arm-gate names the size skip as one of the reasons a marker
could never be stored. Edit 1 and Edit 3 delete that skip, so the clause becomes
a reason that cannot occur — and this comment is the rationale a future reader
consults to decide whether the arm-gate is still needed, so a dead branch in its
two-entry enumeration is load-bearing prose, not decoration. Only the comment
changes; the gate's logic is untouched.

Current:

```python
                    # The arm must succeed before the error is written: a turn
                    # whose marker could never be stored (oversized or
                    # malformed messages) must pass through, never error, or
                    # every stall on that conversation becomes a
                    # repeated-error loop.
```

Becomes:

```python
                    # The arm must succeed before the error is written: a turn
                    # whose marker could never be stored (a malformed messages
                    # array, or one already armed earlier in the request's
                    # lifecycle) must pass through, never error, or every stall
                    # on that conversation becomes a repeated-error loop.
```

Contract points the gate pins:
- The replacement names the **two reasons that survive** Edit 1–3, not one:
  `_retry_nudge_remember` now returns `False` only for a falsy `request_id`, an
  already-present id, or `messages` not being a non-empty list of dicts — the
  first is unreachable at this call site (the fire block is inside a request),
  and the third is "a malformed messages array". The second reason is the one
  the operator sees in practice: a repeated stall on a request whose marker is
  already armed passes through, which is the documented behaviour.
- `oversized` must not survive anywhere in the file: `grep -n oversized src/claude_retry_proxy/server.py` returns nothing.
- No code line in the arm-gated branch changes; the gate still reads
  `and _retry_nudge_arm(request_id)`.

→ coder verify (auto): `grep -n "RETRY_NUDGE_MAX_MESSAGES_BYTES\|messages_json" src/claude_retry_proxy/server.py`
  returns nothing; `RETRY_NUDGE_MAX_ENTRIES = 64` is present; the store dict
  literal carries `hash`/`prefix_len`/`prefix_hash`/`messages_bytes`/`armed`/`stored_at`;
  Pass 2 compares `prefix_hash` and guards on `len(messages) <= prefix_len`; the
  fire event carries `messages_bytes`; the eviction loop and the sweep are
  byte-for-byte unchanged
→ coder verify (scripted): `python ./tmp/verification/2026-10-18-retry-nudge-digest-store-step1.py`
  (exit 0 required — checks 1–11 below)
→ tester verify: `test_chat_retry_nudge_large_conversation_is_nudgeable` passes
  (it FAILS against the pre-change tree), plus the two other new tests and the
  existing module unchanged

**The Step-1 scripted gate** (`./tmp/verification/2026-10-18-retry-nudge-digest-store-step1.py`):

```python
#!/usr/bin/env python3
"""Gate for 2026-10-18-retry-nudge-digest-store Step 1. Exit 0 iff all pass.

The source path defaults to the repo's server.py and may be overridden with an
optional first argument, so the planner can calibrate the gate against a
pre-fix and post-fix text without touching the working tree.
"""
import ast, re, sys, pathlib

DEFAULT_SRC = "src/claude_retry_proxy/server.py"


def run(text):
    checks = []
    def chk(name, ok, detail=""):
        checks.append((name, ok, detail))

    # 1. the cap is gone everywhere
    chk("cap-constant-removed", "RETRY_NUDGE_MAX_MESSAGES_BYTES" not in text)
    # 2. the stored copy is gone everywhere
    chk("messages_json-removed", "messages_json" not in text)
    # 3. the entry cap is 64
    chk("entry-cap-64", re.search(r"^RETRY_NUDGE_MAX_ENTRIES\s*=\s*64\s*$", text, re.M) is not None)

    tree = ast.parse(text)
    funcs = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}

    # 4. remember stores the digest fields (incl. the trace byte count) and no copy
    rem = ast.get_source_segment(text, funcs["_retry_nudge_remember"]) if "_retry_nudge_remember" in funcs else ""
    keys = set(re.findall(r'"([a-z_]+)":', rem))
    chk("remember-entry-keys",
        {"hash", "prefix_len", "prefix_hash", "messages_bytes", "armed", "stored_at"} <= keys,
        "keys=%r" % sorted(keys))
    # 5. remember computes a prefix_hash from a canonical dump with sort_keys
    chk("remember-canonical-hash",
        "sort_keys=True" in rem and "prefix_hash" in rem and "sha256" in rem)
    # 6. remember no longer has a size skip
    chk("remember-no-size-skip", "MAX_MESSAGES_BYTES" not in rem)

    # 7. check Pass 2 compares the digest with a length guard
    chkfn = ast.get_source_segment(text, funcs["_retry_nudge_check"]) if "_retry_nudge_check" in funcs else ""
    chk("check-pass2-digest",
        "prefix_hash" in chkfn and "prefix_len" in chkfn and "sort_keys=True" in chkfn
        and "len(messages) <= prefix_len" in chkfn)
    # 8. eviction loop unchanged (still present, still keyed on the entry cap)
    chk("eviction-loop-present",
        "while len(_retry_nudge_entries) > RETRY_NUDGE_MAX_ENTRIES:" in text)

    # 9. the accessor exists, is lock-held, and never writes
    acc = ast.get_source_segment(text, funcs["_retry_nudge_messages_bytes"]) \
        if "_retry_nudge_messages_bytes" in funcs else ""
    chk("messages-bytes-accessor",
        "with _retry_nudge_lock:" in acc
        and '"messages_bytes"' in acc
        and "_retry_nudge_entries[" not in acc
        and "del " not in acc)
    # 10. the fire event carries messages_bytes, read before the arm gate
    fire = re.search(r'"event": "chat_sse_unfinished_turn",(.*?)\n\s*\}\)', text, re.S)
    payload = fire.group(1) if fire else ""
    chk("fire-event-messages-bytes", '"messages_bytes"' in payload)
    # 11. the arm-gate rationale no longer names the deleted size skip
    chk("arm-gate-comment-current", "oversized" not in text)
    return checks


def main(argv):
    src = pathlib.Path(argv[1] if len(argv) > 1 else DEFAULT_SRC)
    checks = run(src.read_text(encoding="utf-8"))
    bad = [(n, d) for (n, ok, d) in checks if not ok]
    for (n, ok, d) in checks:
        print("%-28s %s %s" % (n, "PASS" if ok else "FAIL", d))
    print("RESULT:", "PASS" if not bad else "FAIL (%d)" % len(bad))
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
```

## Guidance for Tester

**Files to modify:** `tests/test_chat_sse.py` only. Do not touch
`src/claude_retry_proxy/server.py` (Step 1 is the coder's lane) and do not touch
`doc/**` (planner-owned).

**Round completion — read this before you start.** Bound every command that can
spawn a proxy or run a test with an explicit `timeout`, run the full suite in the
**foreground**, and **write your session report before you end your turn.**

The three tests below are **store-level** — they call the module's own helpers
directly, the same idiom as the existing `test_chat_retry_nudge_sweep_expires_armed_only`
(`tests/test_chat_sse.py:3459`). They are fast (no proxy spawn) and they pin the
exact defect. Copy them in after `test_chat_retry_nudge_ineligible_request_does_not_consume`
and register them beside its entry in `ALL_TESTS`.

**The helpers they use already exist in this module** — `fail` and `pass_` come
from the `_harness` import block at the top of the file. **`srv` is NOT one of
them:** `srv` is not bound at module scope in `tests/test_chat_sse.py`, so each
test must import it itself, exactly as `test_chat_retry_nudge_sweep_expires_armed_only`
does at line 3470. The line is included in each function below — **keep it**, or
every test raises `NameError`.

**Clear the store before each test** (`with srv._retry_nudge_lock: srv._retry_nudge_entries.clear()`),
because the store is module-global and earlier tests may have left entries.

```python
def _nudge_canonical(messages):
    import json as _j
    return _j.dumps(messages, separators=(",", ":"), sort_keys=True)


def test_chat_retry_nudge_large_conversation_is_nudgeable():
    """A conversation whose serialized messages exceed the old 1 MiB cap must
    still be remembered, armed, and matched. Regression for the size cap that
    silently killed the feature on every real chat-mode body."""
    print("\n--- Test: Chat Retry Nudge — Large Conversation Is Nudgeable ---")
    import claude_retry_proxy.server as srv
    with srv._retry_nudge_lock:
        srv._retry_nudge_entries.clear()
    messages = [
        {"role": "user", "content": "x" * 1_500_000},
        {"role": "assistant", "content": "Now running the suite:"},
    ]
    body = json.dumps({"messages": messages}).encode("utf-8")
    size = len(_nudge_canonical(messages).encode("utf-8"))
    if size <= 1024 * 1024:
        fail("fixture must exceed the old 1 MiB cap, got {} bytes".format(size))
        return
    if not srv._retry_nudge_remember("rid-big", body, json.loads(body)):
        fail("a >1 MiB conversation must be remembered (the cap is removed)")
        return
    if srv._retry_nudge_messages_bytes("rid-big") != size:
        fail("the stored messages_bytes must equal the serialized prefix size")
        return
    if not srv._retry_nudge_arm("rid-big"):
        fail("remembered entry must arm")
        return
    extended = messages + [{"role": "user", "content": "[proxy nudge]"}]
    ebody = json.dumps({"messages": extended}).encode("utf-8")
    if srv._retry_nudge_check(ebody, json.loads(ebody)) != "rid-big":
        fail("the strict-extension recovery of a large conversation must match")
        return
    pass_(">1 MiB conversation remembered, armed, and matched")


def test_chat_retry_nudge_prefix_digest_matches_strict_extension():
    """The digest Pass 2 matches a strict extension and rejects the two
    near-misses: a same-length different-content body and a shorter body."""
    print("\n--- Test: Chat Retry Nudge — Prefix Digest Pass 2 ---")
    import claude_retry_proxy.server as srv
    with srv._retry_nudge_lock:
        srv._retry_nudge_entries.clear()
    messages = [{"role": "user", "content": "alpha"},
                {"role": "assistant", "content": "beta"}]
    body = json.dumps({"messages": messages}).encode("utf-8")
    if not srv._retry_nudge_remember("rid-digest", body, json.loads(body)):
        fail("remember must store the entry")
        return
    if not srv._retry_nudge_arm("rid-digest"):
        fail("entry must arm")
        return
    # (a) same length, different content -> no match, entry survives
    same_len = [{"role": "user", "content": "alpha"},
                {"role": "assistant", "content": "GAMMA"}]
    sbody = json.dumps({"messages": same_len}).encode("utf-8")
    if srv._retry_nudge_check(sbody, json.loads(sbody)) is not None:
        fail("a same-length non-identical body must not match the prefix digest")
        return
    with srv._retry_nudge_lock:
        if "rid-digest" not in srv._retry_nudge_entries:
            fail("the non-match must not consume the marker")
            return
    # (b) shorter -> no match
    short = messages[:1]
    hbody = json.dumps({"messages": short}).encode("utf-8")
    if srv._retry_nudge_check(hbody, json.loads(hbody)) is not None:
        fail("a shorter body must not match the strict-extension prefix")
        return
    # (c) strict extension -> match and consume
    extended = messages + [{"role": "user", "content": "continue"}]
    ebody = json.dumps({"messages": extended}).encode("utf-8")
    if srv._retry_nudge_check(ebody, json.loads(ebody)) != "rid-digest":
        fail("a strict extension must match")
        return
    with srv._retry_nudge_lock:
        if "rid-digest" in srv._retry_nudge_entries:
            fail("a match must consume the single-use marker")
            return
    pass_("prefix digest: extension matches; same-length and shorter rejected")


def test_chat_retry_nudge_evicts_at_sixty_four_entries():
    """The entry cap is 64: storing a 65th distinct entry evicts the oldest
    unarmed one and the store never exceeds the cap."""
    print("\n--- Test: Chat Retry Nudge — Eviction At 64 Entries ---")
    import claude_retry_proxy.server as srv
    with srv._retry_nudge_lock:
        srv._retry_nudge_entries.clear()
    for i in range(65):
        messages = [{"role": "user", "content": "conv-%d" % i}]
        body = json.dumps({"messages": messages}).encode("utf-8")
        if not srv._retry_nudge_remember("rid-%d" % i, body, json.loads(body)):
            fail("remember(rid-%d) must store" % i)
            return
    with srv._retry_nudge_lock:
        n = len(srv._retry_nudge_entries)
        oldest = "rid-0" in srv._retry_nudge_entries
        newest = "rid-64" in srv._retry_nudge_entries
    if n != 64:
        fail("store must hold exactly 64 entries, got {}".format(n))
        return
    if oldest:
        fail("the oldest unarmed entry must be the eviction victim")
        return
    if not newest:
        fail("the newest entry must survive")
        return
    pass_("store capped at 64; oldest unarmed evicted, newest kept")
```

Registrations to add to `ALL_TESTS` (beside the existing
`chat-retry-nudge-ineligible-request-does-not-consume` row, currently at
`tests/test_chat_sse.py:4961`):

```python
    ("chat-retry-nudge-large-conversation-is-nudgeable",
     test_chat_retry_nudge_large_conversation_is_nudgeable),
    ("chat-retry-nudge-prefix-digest-matches-strict-extension",
     test_chat_retry_nudge_prefix_digest_matches_strict_extension),
    ("chat-retry-nudge-evicts-at-sixty-four-entries",
     test_chat_retry_nudge_evicts_at_sixty_four_entries),
```

**Tests to create:**
- **Permanent:** the three tests above — a large-conversation regression (the
  tightest pin of the removed cap), the digest Pass-2 match with its two
  near-miss controls, and the 64-entry eviction bound.

**Tests to investigate for retirement:**
- No test obsolescence identified. `test_chat_retry_nudge_sweep_expires_armed_only`
  calls `_retry_nudge_remember` / `_retry_nudge_arm` / `_retry_nudge_check` and
  must keep passing unchanged — it exercises the TTL sweep, which this plan does
  not touch. Verify it still passes; do not edit it.
- Tester may identify additional candidates during test work.

**Retirement procedure:** For each candidate, verify the test exercises code being
removed/changed. If obsolete: delete and note in session report. If still valid:
document why in session report.

**Load-bearing check — NOT yours.** The shadow-tree calibration (copy the package
to a scratch tree, reset its `server.py` to `HEAD`, run the module with
`PYTHONPATH` pointed at it) is **assigned to the planner** and is recorded in
`## Final Results`. It requires writing outside the tester's boundary — the
tester contract forbids touching source "via Write, Edit, Bash redirect, shell
redirect, or any other path" — and the harness denies that write to the planner's
own shell as well, so the planner performs it as an in-memory module load rather
than a scratch copy. **Do not attempt the scratch-tree recipe.** Your evidence
that the large-conversation test is load-bearing is: it asserts a `>1 MiB`
fixture is remembered, and against `HEAD` `_retry_nudge_remember` returns `False`
for exactly that input (the planner's recorded measurement).

→ tester verify: the three new tests pass; the module's pre-existing nudge tests
  pass **unchanged**; the full suite's count rises by exactly **3** (module 73 →
  76, suite 425 → 428); the tester's report states the large-conversation test's
  load-bearing status by reference to the planner's recorded `HEAD` measurement

## Summary

**The problem.** The chat-mode retry-nudge feature is dead on real traffic. Over
the trace window **2026-10-13T05:12Z → 2026-10-18T05:57Z** (32,598 requests), its
detector (`chat_sse_unfinished_turn`) fired **91** times and its act branch (error
the unfinished turn + nudge the recovery) ran **zero** times:

| event | count |
|---|---|
| `chat_sse_unfinished_turn` | **91** |
| `chat_retry_nudge` | **0** |
| `chat_retry_passthrough` | **0** |

Every one of the 91 fires carries `rule=colon_after_prose`, `tools_declared=1`,
`finish_reason=stop`, `tool_calls_seen=0` (keys CZ 82 / USTB 9) — so every gate
visible on the wire is satisfied, and the marker store is the only place left that
can skip. The cause is a single skip in `_retry_nudge_remember`: any request whose
serialized `messages` array exceeds `RETRY_NUDGE_MAX_MESSAGES_BYTES = 1 MiB` stores
no marker, so `_retry_nudge_arm` returns `False`, the arm-gate suppresses the
error, and the turn is delivered as an ordinary tool-less `end_turn` — exactly the
stall the feature exists to prevent. Claude Code's own compaction keeps the live
body on a sawtooth that peaks around ~1.25 MiB, so the cap and the compaction
trigger overlap and the feature is dead for a meaningful slice of every cycle.
(Measured across the trace and session transcripts; see
`./tmp/research/tool-call-after-text-nudge-root-cause-2026-10-18.md` and its
compaction-aware correction
`./tmp/research/retry-nudge-cap-what-it-measures-2026-10-18.md`.)

**Competing explanation, tested and rejected.** The store holds 32 entries keyed
by a per-request id, so eviction churn could in principle have starved the marker
before it armed. Measured against the **`mode_dispatch`** timestamp (the true
`remember` time — the `request` event is written at *completion*, median 10 s
later, so timing off it undercounts by a wide margin): across the vulnerable
`remember → arm` window the most any fire ever saw was **20 competing arrivals,
and 0 of 91 exceeded 32**. Eviction churn is ruled out; the size cap stands as the
sole explanation.

**The fix — four coupled changes to one store, plus one trace field.**

1. **Remove the size cap.** `RETRY_NUDGE_MAX_MESSAGES_BYTES` and its skip go away.
   Every conversation, however large, becomes nudgeable.
2. **Store a digest, not a copy.** The marker kept a full JSON copy of `messages`
   *solely* so Pass 2 of `_retry_nudge_check` could compare the recovery's prefix.
   A hash answers the same question. The entry becomes
   `{hash, prefix_len, prefix_hash, messages_bytes, armed, stored_at}` and Pass 2
   re-serializes the candidate prefix in the same canonical form
   (`json.dumps(..., separators=(",", ":"), sort_keys=True)`) and compares the
   digest. Measured: a real entry is **718 bytes** deep — so the store's bound
   goes from 32 × ~1 MiB to 64 × 718 B ≈ **45 KB** (49.5 KB counting the
   `request_id` keys), a ~700× reduction in the worst case.
3. **Raise the entry cap to 64.** `RETRY_NUDGE_MAX_ENTRIES` 32 → 64. **This is
   headroom, not a fix** — no observed fire was ever at risk from the cap (max 20
   competing arrivals against a cap of 32). It is justified only as margin: the
   measured peak already reaches 20 of 32, the digest makes an entry ~700× cheaper
   (so doubling costs ~22 KB), and the slack costs nothing. It is explicitly *not*
   part of the causal explanation for the 0 nudges.
4. **Put the skip on the wire.** The `chat_sse_unfinished_turn` event gains
   `messages_bytes` — the byte size of the serialized `messages` array the marker
   was built from, or `null` if no marker was stored. This is the quantity the
   removed cap measured, so a future skip is visible in the trace instead of
   having to be inferred from session transcripts — which is how this defect
   survived its entire deployed life.

```
remember(rid, body, body_json)
  └─ messages = body_json["messages"]            (no size test any more)
     canonical   = dumps(messages, sep, sort_keys=True)
     body_hash   = sha256(body)                  ← Pass 1 key (raw bytes, no dump)
     prefix_hash = sha256(canonical)             ← Pass 2 key
     store {hash, prefix_len=len(messages), prefix_hash,
            messages_bytes=len(canonical.encode()), armed:False, stored_at}

check(body, body_json)                            (recovery request, entry armed)
  Pass 1: sha256(body) == entry["hash"]           (byte-identical re-issue)
  Pass 2: len(new) > prefix_len
          and sha256(dumps(new[:prefix_len], sep, sort_keys=True)) == prefix_hash
          → consume (delete) and return rid

fire (chat_sse_unfinished_turn)
  messages_bytes = _retry_nudge_messages_bytes(rid)   ← None if never stored
```

**Correcting an earlier over-claim.** The digest does **not** remove the
per-request serialization tax the earlier analysis report attributed to it: the
prefix hash is a hash *of the serialized messages*, so `remember` still dumps the
array once per eligible chat request (as it did before, for the length test).
Measured: `json.dumps` costs 10.3 ms at `HEAD` and 12.5 ms with `sort_keys=True`;
adding the two `sha256` calls brings it to 15.3 ms. What the digest removes is the
**memory** cost (~1 MiB → 718 B per entry), the **cap**, and the per-recovery
`json.loads` of a large stored copy. The honest summary is: this makes the feature
*work*, at ~45 KB instead of ~40–320 MiB, without claiming a CPU win it does not
deliver.

**`PROXY_MAX_BODY_SIZE` — measured, and left at 10 MB.** The user asked whether the
10 MB body cap is enough for a future ~1M-token context. Measured on a real agentic
session (`cl100k_base` over the live `messages` JSON: 1,076,066 bytes / 291,761
tokens = **3.69 bytes/token**), a 1,000,000-token body projects to **≈3.5 MiB** of
`messages` JSON, plus a system prompt and the ~30 tool schemas — call it ~3.6 MiB,
**~2.8× under the 10 MiB cap**. To exceed 10 MiB you would need >10 bytes/token,
which no text/code/JSON content reaches (denser content — base64, hex, CJK —
tokenizes at *fewer* bytes/token, i.e. smaller bodies for the same token count).
**Decision: keep `PROXY_MAX_BODY_SIZE` at its 10 MiB default; do not raise it to
20 MB.** Raising it is a *global* change (it also doubles the transient buffered
worst case for every request and is pinned by
`tests/test_tier_routing.py:1074`, which hardcodes `10485760 + 1`), and the
measurement says it is not needed. This is recorded so the decision is auditable;
the user may still override it.

**Alternatives considered.**
- *Raise the cap only* (e.g. 16–32 MiB, fewer entries) — rejected: keeps a cliff
  (just a higher one), keeps a large in-memory copy, and keeps the store's memory
  proportional to conversation size.
- *Store only the body hash (Pass 1), drop Pass 2* — rejected: the realistic
  recovery is a strict extension, not a byte-identical re-issue; Pass 2 is the
  branch that actually fires.
- *Hash the raw body for Pass 2 as well* — impossible: the recovery body differs
  from the original (turns appended), so only the messages-prefix digest can
  answer the question.
- *Thread `messages_bytes` through the call chain as a parameter* (the way
  `tools_declared` is threaded through `_forward_request_impl` → `_forward_core` →
  `_stream_upstream_response` → `_stream_chat_sse_to_anthropic`) — rejected: four
  signatures and every call site, versus one lock-encapsulating accessor that
  matches how the module already reaches the store.

**Out of scope** (separate decisions, deliberately untouched):
- The **colon-only predicate** — 42 of 48 real stalls end in `.`, not `:`; the
  detector is blind to them.
- The **anthropic-mode blind spot** — the `qwen` tier has no detector at all.
- The **`PROXY_MAX_BODY_SIZE` default** — measured sufficient, left at 10 MB.
- The **other three sites** of
  `./tmp/reports/defer-issue-recursion-guard-residual-sites.json` (the admin
  switch body and the two upstream tool-call argument parses). This plan closes
  only **site 4**; the deferral stays open for the rest.

## Repo Mode

Public

## Document Overrides

| Document | Rule Overridden | Reason |
|----------|----------------|--------|

## Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| The digest is *stricter* than the old list comparison in one corner: `json.dumps` is key-order-sensitive unless `sort_keys=True`, and int/float or `True`/`1` distinctions the old Python `==` collapsed are now visible | A recovery that reorders keys or re-types a numeric could fail to match and lose its nudge | `sort_keys=True` on **both** sides restores the old order-insensitivity; the client re-sends the prefix verbatim, so the numeric corner is unreachable in practice. Pinned by the same-length-different-content control in `test_chat_retry_nudge_prefix_digest_matches_strict_extension` |
| Pass 2 now re-serializes the candidate prefix per armed entry, where the old code `json.loads`ed the stored copy | A recovery with many armed entries could spend more CPU | The `len(messages) <= prefix_len` guard runs **before** any dump, so non-matching requests pay nothing; in practice ≤1 entry is armed per recovery, and the cost is on the recovery path only, never the hot path |
| Removing the cap widens the reachable `MemoryError` path (an uncaught allocation failure on a huge dump) | A request thread could die on a genuine allocation failure | Narrow and pre-existing — `remember`'s `except` tuple never caught `MemoryError`. The digest *shrinks* retained memory (no copy), so the store is not what grows; the transient dump is bounded by `PROXY_MAX_BODY_SIZE`. Left as-is (out of scope); not widened in practice |
| The new `messages_bytes` accessor takes the store lock on the fire path | A fire could contend with concurrent `remember` calls | The lock is already taken twice on this path (`remember` at entry, `arm` moments later) and is held only for a dict lookup; the store is at most 64 entries. The read is a `.get` with no mutation and no sweep |
| `messages_bytes` is `None` on a fire whose body was ineligible | A reader could misread `null` as a regression | The plan states the expected steady state (**an int on every eligible fire**) in the coder guidance and in the doc row, so `null` reads as the signal it is |

## Proposed Changes

1. **Step 1:** Replace the stored `messages_json` copy with a `(prefix_len, prefix_hash, messages_bytes)` digest, delete `RETRY_NUDGE_MAX_MESSAGES_BYTES` and its skip, raise `RETRY_NUDGE_MAX_ENTRIES` to 64, add the `_retry_nudge_messages_bytes` accessor, carry `messages_bytes` on the `chat_sse_unfinished_turn` event, and drop the now-dead `oversized` reason from the arm-gate rationale comment — all in `src/claude_retry_proxy/server.py`
   → coder verify (auto): `grep -n "RETRY_NUDGE_MAX_MESSAGES_BYTES\|messages_json\|oversized" src/claude_retry_proxy/server.py` returns nothing; `RETRY_NUDGE_MAX_ENTRIES = 64` present; the store dict carries `hash`/`prefix_len`/`prefix_hash`/`messages_bytes`/`armed`/`stored_at`; Pass 2 compares `prefix_hash` behind a `len(messages) <= prefix_len` guard; the fire event carries `messages_bytes`; the eviction loop and sweep are unchanged
   → coder verify (scripted): `./tmp/verification/2026-10-18-retry-nudge-digest-store-step1.py` exit 0 (11 checks)
   → tester verify: `test_chat_retry_nudge_large_conversation_is_nudgeable` passes; the digest-control and eviction tests pass; the module's pre-existing nudge tests pass unchanged

2. **Step 2:** Pin the digest store with three store-level tests in `tests/test_chat_sse.py` — a >1 MiB conversation that is remembered (`messages_bytes` included), armed and matched (the cap regression), the prefix-digest Pass-2 match with same-length and shorter controls, and eviction at exactly 64 entries (tester-owned; no coder work)
   → tester verify: the three tests pass; the full suite rises by exactly 3 (module 73 → 76, suite 425 → 428); `test_chat_retry_nudge_sweep_expires_armed_only` still passes untouched

3. **Step 3:** Reconcile the documentation with the landed code (planner-owned; no coder or tester work)
   → planner verify: the `chat-sse-unfinished-turn` prose describes the digest store and drops the 1 MiB boundary; `doc/trace-log.html`'s event-table row lists `messages_bytes`; `doc/test-catalog.html` carries three new rows and the counts 76 / 428

## Guidance for Planner

Documentation and calibration tasks you will execute yourself (not the coder):

- **Files to modify:**
  - `./doc/provider-modes.html`
  - `./doc/trace-log.html`
  - `./doc/test-catalog.html`
- **`.claude/mega-audit-files.json`:** does not exist in this repo — nothing to update.
- **When:** after the coder finishes (the prose must match the landed code).
- **What to sync:**
  - `doc/provider-modes.html` — the `chat-sse-unfinished-turn` section
    (`#chat-sse-unfinished-turn`) has two passages that the removal of the cap and
    the switch to a digest make **false**:
    1. **~lines 501–503:** *"It remembers the conversation's messages in process
       memory"* — it no longer stores the messages; it stores a body hash, a
       length-plus-prefix-hash, and the prefix's byte count. Rewrite to describe
       the digest (a body hash for the byte-identical re-issue and a
       length-plus-prefix-hash for the strict extension).
    2. **~lines 514–517:** the "Two boundaries are deliberate" paragraph says a
       conversation *"larger than 1 MiB"* *"can never be nudged, so it is never
       errored"*, and that the store is *"at most 32 conversations, at most 1 MiB
       of messages each"*. **The size boundary is gone** — a large conversation is
       now nudgable. Keep only the *malformed-cannot-be-stored* half of the
       "cannot be nudged ⇒ must not error" boundary (remember can still return
       False for a falsy id or a non-list/empty/non-dict `messages`), and restate
       the bounds as *"at most 64 conversations, each a sub-kilobyte digest (no
       messages copy)"*. **State the measured figure** — 718 bytes per entry,
       ~45 KB for the full store — not the earlier ~140 bytes/~9 KB estimate,
       which was ~5× low. This is the **doc-side twin of Step 1's Edit 7**: the
       page and the arm-gate comment must name the same surviving reasons, and
       `oversized` must appear in neither.
  - `doc/trace-log.html` — the `chat_sse_unfinished_turn` row in the event table
    (~line 140) and its prose section (~line 228). Add `messages_bytes` to the
    field list and say what it is for: the serialized `messages` byte size the
    marker was built from, `null` when no marker was stored — the quantity the
    removed size cap measured, kept so a skip is visible on the wire. The prose
    at line 228ff currently cross-references (`Behaviour, the store's bounds, and
    the kill switch: provider-modes.html`) rather than restating the bounds, so
    only the field needs adding here.
  - `doc/test-catalog.html` — add a per-test row for each of the three new tests
    in the `test_chat_sse.py` index (~line 491), and update the module count
    (line 127, the `test_chat_sse.py` table row; and line 432, the section
    heading) and the suite total. The tester's report establishes the measured
    counts — take them from the report, which should read **76** and **428**.
    Do not guess.
  - **Not in this plan:** `CLAUDE.md` and `README.md` carry **no** statement of the
    cap, the entry count, or the store's memory bound (verified: zero matches for
    `MAX_MESSAGES_BYTES`/`1 MiB`/`32 conversation` outside `provider-modes.html`),
    so neither needs a change. `CLAUDE.md`'s deferred-issue block is rewritten
    wholesale by the deferred-corpus-sweep plan, not here.
- **Load-bearing calibration (planner-executed).** Prove
  `test_chat_retry_nudge_large_conversation_is_nudgeable` fails against the
  pre-change tree. **Do not copy the package to a scratch tree** — that write is
  outside this role's boundary and the harness denies it. Instead load `HEAD`'s
  `server.py` **in memory** as a module and drive `_retry_nudge_remember` on the
  test's own fixture: `git show HEAD:src/claude_retry_proxy/server.py` into a
  string, exec it under a synthetic package (`mod.__package__ =
  "claude_retry_proxy"`, with the real package's submodules pre-registered in
  `sys.modules` so its relative imports resolve), then assert
  `_retry_nudge_remember("rid-big", body, json.loads(body)) is False` for a
  `>1 MiB` fixture. Record the measured result in `## Final Results`. The write
  goes nowhere; the working tree stays clean.
- **Deferral bookkeeping.** This plan closes **site 4** of
  `./tmp/reports/defer-issue-recursion-guard-residual-sites.json`. Update that
  report's `context` to note site 4 is retired by this plan (the Pass-2
  `json.loads` guard no longer exists), leave its `status` **Open** for the other
  three sites, and record the partial closure in this plan's Issue Log row and
  `## Final Results`. The file is **not** deleted — the corpus rule is that a file
  is removed only on a terminal disposition.

## History

| Date | Event | Conclusion | Dismissed |
|------|-------|------------|-----------|
| 2026-10-18 | Initial plan | Three coupled changes to the retry-nudge marker store — drop the 1 MiB size cap, replace the stored `messages` copy with a `(prefix_len, prefix_hash)` digest, raise the entry cap to 64 — restoring a feature that had been dead for its entire deployed life; `PROXY_MAX_BODY_SIZE` measured sufficient at 10 MB and left unchanged. | — |
| 2026-10-18 | Planner revision — Phase 3 discussion | Premise re-measured on the live trace (91 fires / 0 nudges / 0 passthrough, all gates satisfied); eviction churn re-tested against the correct `mode_dispatch` anchor and ruled out (max 20 competing arrivals against a cap of 32). Four decisions taken: keep the cap raise at 64 but **re-justify it as headroom, not a fix**; move the shadow-tree calibration to the planner as an in-memory `HEAD` load; **add `messages_bytes` instrumentation** as a fourth change; record the **partial closure of deferral site 4**. Two plan defects corrected — the three supplied tests omitted `import claude_retry_proxy.server as srv` (they would `NameError`), and the store-size figures were ~5× low (measured 718 B per entry, ~45 KB for 64, not ~140 B / ~9 KB). | A first-pass eviction-churn measurement (max 14, 0/89) that used the `request` trace event as the `remember` anchor — that event is written at *completion*, median 10 s late, so it undercounted; superseded by the `mode_dispatch`-anchored measurement |
| 2026-10-18 | Coder round 1 (Phase 4.6) | Six of the seven edits landed in `server.py` (52+/22−); the gate went GREEN on the tree at 10 checks; the frozen regions (eviction loop, sweep, detector predicate, arm-gate logic, nudge injection) verified byte-for-byte unchanged. The coder filed **two plan-text defects instead of deviating silently**, and both are real: (a) the plan's Edit 5 docstring named `RETRY_NUDGE_MAX_MESSAGES_BYTES`, which the plan's own `cap-constant-removed` check forbids — the supplied text could not pass the supplied gate; (b) the arm-gate rationale comment still gave `oversized` as a reason a marker could never be stored, a reason Edit 1–3 delete. Planner revision: Edit 5 corrected, the comment added as **Edit 7**, the gate extended to **11 checks** so the comment is pinned by `arm-gate-comment-current` rather than requested in prose, and the Step-1 calibration rebuilt to splice the plan's own code blocks. | The first calibration run's GREEN verdict — it built the post-fix text from a **hand-abridged** copy of Edit 5, so it validated a text nobody was asked to write; the rebuilt calibration extracts every block from the plan and asserts each block's lines survive into the built text (negative-tested: it flags the abridged docstring the gate alone is blind to) |
| 2026-10-18 | Tester round (Phase 4.6) | Step 2 landed as three store-level tests in `tests/test_chat_sse.py`, **+120 lines / 0 deletions** — pure addition, so the plan's one retirement candidate (`test_chat_retry_nudge_sweep_expires_armed_only`) survived untouched as intended. Module 73 → **76**, suite 425 → **428**, 0 failed, 0 skipped; the Step-1 gate re-run read-only at **11/11 PASS**. No issue reports filed: no non-skipped test failed. | Two observations, both non-defects, both kept rather than edited: (1) the eviction test's 64 entries stay in the module-global store, since the supplied bodies clear at entry but not in a `finally` — harmless, as every new test clears first and no later test in `ALL_TESTS` touches the store, but a deviation from its neighbour's cleanup idiom; (2) the claim that the plan's `## Summary` still enumerates `(oversized or malformed messages)` — **independently checked and false**: the phrase appears nowhere between the `## Summary` heading and `## Repo Mode`, and the tester had inherited the claim from the coder's issue report rather than verifying it. Its real home is `doc/provider-modes.html`, which Step 3 fixes. |
| 2026-10-18 | Step 3 + planner verification | The three doc pages reconciled: `doc/provider-modes.html` now describes the digest and states the bounds as 64 sub-kilobyte digests (718 B/entry, ~45 KB), with the size boundary removed and only the malformed-cannot-be-stored half kept; `doc/trace-log.html` carries `messages_bytes` in the event's field list; `doc/test-catalog.html` carries three new rows and the counts 76/428. Load-bearing calibration executed in memory against `HEAD` and recorded in `## Final Results`. Deferral site 4 retired in the report's `context` with `status` left **Open**. | — |
| 2026-10-18 | Review (Phase 6) | Verdict **Issues found — non-blocking**: **0 Critical** / 2 Warning / 2 Suggestion — report `./tmp/reports/2026-10-18-retry-nudge-digest-store-review-2026-10-18.json`. The reviewer worked independently rather than restating: it re-ran the Step-1 gate (**11/11 PASS**), re-derived HEAD's pre-fix shape from `git show HEAD:...`, reproduced the fixture's canonical size (**1,500,086 bytes**), and swept the repo for the removed identifiers (zero hits outside the immutable archives). It **refuted three of the plan's own hunches with measurement**: the eviction-test residue is not a hazard (that test sits at `ALL_TESTS` index 64 of 76 and no later test body touches the store), `isinstance(prefix_len, int)` admitting `True` is unreachable and harmless (`messages[:True]` is `messages[:1]`, the correct 1-message prefix), and the "headroom, not a fix" framing is consistent across Summary, Final Results and the catalog row with no stale causal claim. It also **confirmed** that no parse normalises the prefix (`json.loads` at `server.py:1058` feeds both `remember` and `check` before the transform runs), that the `remember → arm` window is strictly improved by the cap raise, that the Pass-2 guards are sound on every probe, and that the accessor is read-only, lock-held and read before the arm gate. | Four findings recorded, none blocking: `review-duplicate-canonical-encode` (Warning/Perf — `server.py:350` re-encodes the canonical string instead of reusing `:339`'s encode; measured 0.82 ms + a 1.5 MB transient on the 1.5 MB fixture against 0.0003 ms for `len(canonical_bytes)`, contradicting this plan's own cost note); `review-accessor-none-semantics` (Warning/Correctness — the accessor docstring asserts `None` ⇔ never-stored, but the read precedes the arm so an unarmed entry evicted by the cap also reads `None`, and `doc/trace-log.html` repeats the weaker form); `review-key-order-pin-absent` (Suggestion/Testability — no behavioural pin for the key-order-insensitivity `sort_keys=True` exists for; only the gate's substring check guards it, so dropping it from either side leaves the module green); `review-digest-equivalence-noted` (Suggestion/Correctness — the digest's equivalence class differs from the removed `==` in two directions and only the stricter one, `1` vs `1.0`, was recorded; the looser `NaN` direction was not). Not re-derived in the reviewer's lane: frozen-region byte-identity (its evidence is the full 7-hunk diff plus the gate), suite execution, and the live-trace counts. |

## Plan Metadata

```json
{
  "plan_id": "2026-10-18-retry-nudge-digest-store",
  "steps": [
    "Step 1: Replace the stored messages_json copy with a (prefix_len, prefix_hash, messages_bytes) digest, delete RETRY_NUDGE_MAX_MESSAGES_BYTES and its skip, raise RETRY_NUDGE_MAX_ENTRIES to 64, add the _retry_nudge_messages_bytes accessor, and carry messages_bytes on the chat_sse_unfinished_turn event in src/claude_retry_proxy/server.py",
    "Step 2: Pin the digest store with three store-level tests in tests/test_chat_sse.py",
    "Step 3: Reconcile doc/provider-modes.html, doc/trace-log.html and doc/test-catalog.html with the landed code"
  ],
  "coder_files": ["src/claude_retry_proxy/server.py"],
  "tester_files": ["tests/test_chat_sse.py"],
  "doc_files": ["./doc/provider-modes.html", "./doc/trace-log.html", "./doc/test-catalog.html"],
  "verification_scripts": ["./tmp/verification/2026-10-18-retry-nudge-digest-store-step1.py", "./tmp/verification/2026-10-18-retry-nudge-digest-store-step1-calibration.py", "./tmp/verification/2026-10-18-retry-nudge-digest-store-step2-loadbearing.py", "./tmp/verification/2026-10-18-retry-nudge-digest-store-step3-head-calibration.py"],
  "repo_mode": "Public",
  "document_overrides": []
}
```

## Audit Accumulation

| Counter | Value | Last Updated |
|---------|-------|--------------|
| issues_resolved_since_audit | 3 | 2026-10-18 |
| steps_changed_since_audit | 3 | 2026-10-18 |
| files_changed_since_audit | 2 | 2026-10-18 |

## Documentation

- `doc/provider-modes.html` — the `chat-sse-unfinished-turn` section: the store
  keeps a digest (not a messages copy), the 1 MiB size boundary is removed, and
  the bounds read 64 conversations of sub-kilobyte digests (~718 B each, ~45 KB
  total).
- `doc/trace-log.html` — `messages_bytes` added to the `chat_sse_unfinished_turn`
  field list, with its meaning (`null` = no marker stored).
- `doc/test-catalog.html` — three new `test_chat_sse.py` rows and the updated
  suite / module counts.

## Final Results

**Outcome.** The retry-nudge marker no longer stores the conversation. It stores a
fingerprint — a body hash (byte-identical re-issue), a prefix length plus a hash of
the canonical serialization (strict extension), and the prefix's byte count — so
every conversation, however large, becomes nudgeable. `RETRY_NUDGE_MAX_MESSAGES_BYTES`
and its skip are gone; `RETRY_NUDGE_MAX_ENTRIES` is 64 as **headroom, not a fix**
(measured ceiling was 20 competing arrivals against the old cap of 32); the skip that
used to be silent now shows on the wire as `messages_bytes` on
`chat_sse_unfinished_turn`.

**Landed.**
- `src/claude_retry_proxy/server.py` — 56 insertions / 26 deletions (seven edits).
- `tests/test_chat_sse.py` — 120 insertions / **0 deletions** (three store-level
  tests; pure addition, so the one retirement candidate survived untouched).
- `doc/provider-modes.html`, `doc/trace-log.html`, `doc/test-catalog.html`.

**Verification.**
- Step-1 gate `./tmp/verification/2026-10-18-retry-nudge-digest-store-step1.py` —
  **11/11 PASS, exit 0**, re-run by me against the landed tree.
- Full suite **428 passed / 0 failed**, `tests/test_chat_sse.py` **76/76** (tester).
- `scripts/check_doc_anchors.py` — PASS, 206 anchors resolved, no secret shapes.
- `doc_structure_check.py` — PASS, 9 files, no violations.

**Load-bearing calibration (planner-executed, in memory —
`./tmp/verification/2026-10-18-retry-nudge-digest-store-step3-head-calibration.py`).**
HEAD's `server.py` was read from git into a string and exec'd as a synthetic
`claude_retry_proxy.server`, so the working tree was never copied or written. The
test body was lifted by AST out of `tests/test_chat_sse.py`, so what was calibrated
is the shipped body, not a paraphrase. Measured: HEAD carries
`RETRY_NUDGE_MAX_MESSAGES_BYTES = 1048576` and an entry cap of 32; the fixture
serializes to **1,500,086 bytes**, 451,510 bytes over HEAD's cap; against HEAD the
test fails on exactly `a >1 MiB conversation must be remembered (the cap is removed)`,
and against the working tree it passes. The test is load-bearing by construction, and
the claimed root cause — the size skip, `return False` → no arm → no error → no nudge
— is the branch the fix flips.

**Deferral site 4.** Closed by this plan: Step 1 Edits 2–4 deleted the Pass-2
`json.loads(entry["messages_json"])` re-parse, so the narrow guard site no longer
exists. `./tmp/reports/defer-issue-recursion-guard-residual-sites.json` stays
**Open** for sites 1–3, and both its `context` and its site-4 paragraph now record
the retirement. Any sub-1 MiB request that previously stored no marker now does.

**Review (Phase 6).** Verdict **Issues found — non-blocking**: **0 Critical**, 2
Warning, 2 Suggestion. Report:
`./tmp/reports/2026-10-18-retry-nudge-digest-store-review-2026-10-18.json`. The
reviewer's own coverage self-assessment: complete for the source and test diffs
(7 hunks in `server.py`, the whole test diff, the surrounding store, the eligibility
gate, the `request_id` chain and the fire site), with each of the six obligations
getting a designed probe. It refuted three of the plan's stated hunches with
measurement rather than accepting them.

**Known caveats (the four reviewer findings — none blocking).**
- `server.py:350` re-encodes the canonical string that `:339` had already encoded,
  paying a second full UTF-8 encode (0.82 ms, 1.5 MB transient on the test's own
  fixture) where `len(canonical_bytes)` would be 0.0003 ms. The plan's cost note for
  this field is therefore wrong as landed.
- The accessor's docstring claims `None` ⇔ "never stored". False: because the read
  precedes the arm and the cap victimises the oldest *unarmed* entry, `None` also
  covers "stored, then evicted or swept". `doc/trace-log.html` repeats the weaker
  form. Unreachable in practice at the measured peak of 20 concurrent unarmed
  entries against a cap of 64, but the claim as written is absolute.
- No behavioural test pins the key-order-insensitivity that justifies
  `sort_keys=True`; the gate's substring check is the only guard.
- The digest's equivalence class differs from the removed `==` in two directions;
  only the stricter direction (`1` vs `1.0`) was documented, not the looser `NaN`
  one. Both require the client to alter the prefix's numeric text between the
  original and the recovery, which the verbatim re-send rules out.

**Audit scope.** The mega-audit entry threshold (≥5 steps **or** ≥5 source files) is
**not** met: 3 steps, 1 source file (`server.py`) plus 1 test file.
