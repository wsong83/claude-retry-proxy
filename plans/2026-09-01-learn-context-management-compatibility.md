# Plan: Learn per-upstream `context_management` compatibility
**Project:** D:\proj\claude-retry-proxy
**Plan ID:** 2026-09-01-learn-context-management-compatibility
**Created:** 2026-09-01
**Updated:** 2026-09-02 (review fixes verified, 253/253 tests pass, ready for Step 4)

## Issue Log

| Issue | Status | Found | Resolved | Resolved By |
|-------|--------|-------|----------|-------------|
| [review-findings](../reports/2026-09-01-learn-context-management-compatibility-review-2026-09-02.json) | Resolved | 2026-09-02 | 2026-09-02 | tester |
| [compat-retry-not-single-attempt](../reports/2026-09-01-learn-context-management-compatibility-compat-retry-not-single-attempt.json) | Resolved | 2026-09-02 | 2026-09-02 | tester |
| [buffered-response-paths-uncapped](../reports/2026-09-01-learn-context-management-compatibility-buffered-response-paths-uncapped.json) | Resolved | 2026-09-02 | 2026-09-02 | tester |
| [break-up-large-source-and-test-files](../reports/defer-issue-break-up-large-source-and-test-files.json) | Open | 2026-09-01 | — | — |
| [opencode-zen-claude-rejects-extra-inputs](../reports/defer-issue-opencode-zen-claude-rejects-extra-inputs.json) | Resolved | 2026-08-28 | 2026-09-02 | tester |

## Guidance for Coder

**Files to modify:**
- `src/claude_retry_proxy/server.py`

**Step-by-step with verification:** each coder step has mechanical `(auto)` checks. The tester owns all behavioral checks and test-file changes.

1. **Step 1:** Add a narrowly scoped compatibility-state subsystem to `server.py`. Define one centralized, maintainer-tunable policy entry whose only feature key is the constant `"context_management"` in `anthropic` mode, and constants for initial strip threshold `32`, probation threshold `8`, rejection backoff multiplier `2`, maximum strip threshold `4096`, delisting successes `2`, maximum compatibility retries per client request `1`, and failed-confirmation suppression count `3`. Do not add an Anthropic request-field whitelist and do not classify, strip, probe, or learn any other field. Validate constants at startup: `2 <= multiplier`, `2 <= delisting_successes`, `initial <= max`; emit stderr warning and clamp otherwise.

   **State model — per-entry persisted fields:** `schema_version` (int), `provider` (str), `mode` (str), `actual_model` (str), `feature` (str — always `"context_management"`), `state` (enum: `"unsupported"` | `"probation"`), `threshold` (int — on the doubling ladder [32, 4096]), `strip_counter` (int — in [0, threshold]), `probation_successes` (int — in [0, delisting_successes]), `failed_confirmations` (int — in [0, failed_confirmation_suppression_count]). The feature field in every entry is always the constant `"context_management"`; field names from upstream error bodies are compared against this constant and never copied into state keys, strip logic, or trace events.

   **Write cadence:** persist on state-machine transitions only (learn, backoff doubling, probation changes, delist, failed-confirmation threshold reached). Strip counters and probation success counters are in-memory-only — restart resets them to zero (fail-safe: over-stripping).

   **Persistence:** key learned state by `(provider, mode, actual_model, feature)`. Load it from `PROXY_FEATURE_COMPAT_FILE`, defaulting to `~/.claude/proxy/feature-compatibility.json`; missing files mean empty state, while malformed/unreadable files warn to stderr and fail open with empty state. On load: unknown/absent `schema_version` → warn + fail open empty; known version but invalid individual entries → drop the bad entry, keep valid ones, warn per entry; unknown feature keys → ignore (forward-compat); counters clamped to `[0, threshold]`; thresholds normalized onto the doubling ladder; unknown state values → treat as absent. Validate `isinstance(loaded_state, dict)` and `isinstance(entries, dict)` on read. Persist schema-versioned, metadata-only state atomically with a unique temporary filename (pid/uuid suffix, not a fixed `.tmp`) + `os.replace`, guarded by the dedicated state lock; keep successful in-memory updates if persistence fails and emit a metadata-only `compatibility_persist_failed` trace event (rate-limited: once per 60s per key). Never persist request field values, prompt content, full request bodies, or raw error bodies. Apply best-effort `os.chmod(0o600)` on POSIX (guarded by `os.name == 'posix'`), mirroring the existing `write_state`/`log_trace` pattern.

   **Concurrency:** two locks:
   - `_compat_state_lock` (`threading.Lock`): protects the in-memory state dict. Held only for microseconds (dict reads, counter increments, in-progress-set operations). Persistence built under the lock, I/O serialized through it.
   - `_compat_retry_lock` (`threading.Lock`): ensures at most one in-flight compatibility retry or probe globally. Acquired with `blocking=False` — if held, the caller returns the original error unchanged. Held for the duration of the upstream HTTP call. Released in `finally` on every outcome.

   → coder verify (auto): `server.py` contains one policy registry whose only feature key is `context_management`, the eight named tuning constants with values `32`, `8`, `2`, `4096`, `2`, `1`, and `3`, a default `feature-compatibility.json` path overridable by `PROXY_FEATURE_COMPAT_FILE`, `_compat_state_lock` and `_compat_retry_lock`, schema-versioned load/write helpers with per-entry validation, and atomic `os.replace` with unique temp filename; no general request-field whitelist is introduced.
   → tester verify: unit-level permanent tests prove missing/corrupt/unreadable state fails open, valid state round-trips, writes are atomic and metadata-only, one-bad-entry-among-good preserves valid entries, unknown-feature entries are ignored, higher-version files fail open, duplicate concurrent updates do not lose state, persistence failure retains the in-memory update and emits rate-limited trace, distinct provider/mode/model keys do not collide, and both locks are present with correct behavior.

2. **Step 2:** Integrate conservative discovery, stripping, probing, and delisting into the Anthropic upstream request flow without changing chat/response transforms. Add `anthropic-beta` to the forwarded-header allowlist. Compatibility logic is gated by `mode == "anthropic"`, a valid top-level `context_management` key in the parsed request body (any value including `null`/`{}`/`[]`; unparseable bodies skip compatibility entirely), and the single policy entry. The compatibility check is integrated inside `_forward_request_impl` using the same config/vendors snapshot taken at entry — it is immune to mid-request config swaps.

   **Detector:** recognize unsupported-feature evidence only for HTTP 400 responses whose body parses as JSON (content-type-agnostic — attempt `json.loads()` on the drained body regardless of Content-Type header, bodies capped at `PROXY_MAX_BODY_SIZE` via `_read_capped`; bodies exceeding the cap or failing to parse are inconclusive) and matches an enumerated parser: the observed message form ending in `context_management: Extra inputs are not permitted` (anchored: the token must be at message start or preceded by `': '` or `'] '`, not preceded by `'.'` — rejects nested-path matches like `tools.0.context_management`), plus explicitly supported structured `extra_forbidden` validation data whose body location identifies top-level `context_management`. The parsed field name is compared against the constant `"context_management"` and never copied into state keys, strip targets, or trace events. Require the named field to exist in the exact outbound body. Do not learn from broad "invalid request," malformed-value, authentication, model, quota, context-limit, or unrelated 400 errors.

   **Discovery:** for an Anthropic request containing `context_management` with no learned entry: forward unchanged. On recognized exact 400, acquire `_compat_retry_lock` (non-blocking; if held, return original 400). Close/drain the original response, make one compatibility retry (a single upstream HTTP call inside `_forward_request_impl`, same config/vendors snapshot, explicit `suppress_compat=True` parameter so recursion is structurally impossible, NOT re-entering `forward_request` or the 429/503 retry loop). Non-2xx results from the retry are returned to the client as-is — there is no 429/503 retry loop on the compatibility retry. If the retry is 2xx, learn unsupported state (2xx evidence recorded at upstream status receipt before streaming begins; mid-stream failures do not roll back). If the retry is non-2xx, return the original 400 (already processed through the existing anthropic-mode non-2xx path including `_rewrite_json_response` for model name), do not learn, and increment a per-key in-memory failed-confirmation counter. After `failed_confirmation_suppression_count` (default 3) failed confirmations, suppress further compatibility retries for that key (record as a metadata-only trace event; re-enter discovery after a request-count interval equal to the current threshold). The discovery path shares the same `_compat_retry_lock` as revalidation probes — concurrent discovery bursts are serialized to one leader; losers return the original 400.

   **Stripping:** learned unsupported entries strip `context_management` from the request body for `threshold` matching requests. The strip counter is protected by `_compat_state_lock`. If the request body is unparseable (json.loads failure), skip compatibility logic entirely.

   **Probing:** when the strip counter reaches `threshold`, acquire `_compat_retry_lock` (non-blocking; if held, skip — the request is stripped and counts toward the next threshold). The probe owner sends the unstripped body. Probe outcomes:
   - **2xx:** record one probation success. If `probation_successes >= delisting_successes` (2), delist the entry (remove from state). Otherwise transition to `"probation"` state, strip the next `probation_threshold` (8) matching requests, then probe again.
   - **Same exact 400:** the provider still rejects the field. Reset probation to zero, double the threshold (`min(threshold * 2, max_threshold)`), persist the doubled threshold, and return the stripped retry result (single attempt, no 429/503 loop, same `_forward_request_impl` inner path as discovery retry). The doubled threshold is preserved across restarts.
   - **Other (non-matching 400, 5xx, etc.):** inconclusive. Leave probation state and success count unchanged, reset strip counter to zero, reschedule another probe after the current (possibly doubled) threshold.

   **Strip counter semantics** (all under `_compat_state_lock`):
   - Counter resets to 0 when a probe begins.
   - Stripped requests concurrent with an in-progress probe still increment the counter and count toward the next threshold.
   - Inconclusive probes reschedule at the current threshold (which may have been doubled by prior rejections).
   - Repeated rejection resets probation to zero but keeps the doubled threshold.

   Trace retries field: the returned tuple's `retries` count sums the original forwarding loop's retries with the compatibility retry's own retries.

   **Exclusions:** `count_tokens` requests skip compatibility processing entirely (consistent with `disable_retry_claude_count_token`). Compatibility retries are independent of the existing `PROXY_MAX_RETRIES` budget and are not applied recursively. Preserve existing 429/503/connection retry behavior, one-time request transformation, streaming behavior, response transforms, and `count_tokens` handling.

   Emit metadata-only events for `compatibility_rejection_detected`, `compatibility_learned`, `compatibility_field_stripped`, `compatibility_probe_started`, `compatibility_probe_succeeded`, `compatibility_probe_rejected`, `compatibility_probe_inconclusive`, `compatibility_delisted`, `compatibility_persist_failed`, and `compatibility_failed_confirmation_suppressed`; include request ID, provider, mode, tier, actual model, feature name, counters/state where relevant, and no field values, raw error text, or field names from upstream bodies.
   → coder verify (auto): `FORWARD_HEADERS` includes `anthropic-beta`; compatibility logic is gated by `mode == "anthropic"`, a valid top-level `context_management` presence, and the single policy entry; the detector accepts only the two enumerated JSON 400 shapes with content-type-agnostic parsing; every compatibility retry is bounded by `COMPAT_MAX_RETRIES_PER_REQUEST` and passes `suppress_compat=True`; retry is inside `_forward_request_impl` with same snapshot, not re-entering `forward_request`; `_compat_retry_lock` is released in `finally`; `count_tokens` is excluded; no chat/response transformation function references the compatibility subsystem; existing 429/503 retry branches remain present.
   → tester verify: permanent live-proxy tests cover initial 400→stripped-2xx learning, no learning when stripped retry fails, original-error preservation on failed initial confirmation, failed-confirmation suppression after N attempts, immediate stripping after learning, exact key isolation, forwarding of `anthropic-beta`, unknown fields passing unchanged, all non-matching 400 forms passing through without retry, nested-path 400 messages not triggering retry, one-retry cap, content-type-agnostic detection, 32-request initial probe, repeated-rejection doubling/cap, 8-request probation, two-success delisting, inconclusive-probe rescheduling, concurrent single-retry global ownership, retry cleanup after exceptions, config-swap-during-retry isolation, and interaction with existing 429/503 plus streamed 2xx responses.

### Step 2 follow-up: fix `compat-retry-not-single-attempt` and `buffered-response-paths-uncapped`

**Issue #1 — `compat-retry-not-single-attempt`:** The compatibility retry re-enters the 429/503/connection retry loop instead of being a single upstream attempt. Two call sites are affected:

| Call site | File:line | Current behavior |
|-----------|-----------|-----------------|
| Discovery retry | `server.py:1473-1477` | `_forward_request_impl(suppress_compat=True)` → `_forward_core` runs full retry loop |
| Probe rejection retry | `server.py:1208-1212` | Same pattern |

Root cause: `_forward_request_impl` passes `suppress_compat=True` to skip the compat subsystem, but never limits `_forward_core`'s retry loop. The docstring at line 1222-1225 already claims correct behavior ("the retry is a single upstream attempt (never re-enters the 429/503 retry loop)") — it's just not implemented.

**Fix — `_forward_core`** (line 1501): add optional `max_attempts=None` parameter. When explicitly passed, use it directly, overriding both the default `PROXY_MAX_RETRIES + 1` and the `disable_retry_claude_count_token` logic:

```python
def _forward_core(method, path, handler, request_id, config,
                  rewritten_body, fwd_headers, upstream_path,
                  host, port, use_ssl, tier, provider_name, actual_model,
                  mode, is_count_tokens, max_attempts=None):
    ...
    if max_attempts is not None:
        pass  # use as-is
    else:
        disable_retry = config.get("disable_retry_claude_count_token", False)
        max_attempts = 1 if (disable_retry and is_count_tokens) \
                       else PROXY_MAX_RETRIES + 1
```

**Fix — `_forward_request_impl`** (line 1424): pass `max_attempts=1` when `suppress_compat=True`:

```python
result = _forward_core(
    method, path, handler, request_id, config, rewritten_body,
    fwd_headers, upstream_path, host, port, use_ssl, tier,
    provider_name, actual_model, mode, _is_count_tokens,
    max_attempts=1 if suppress_compat else None)
```

**Fix — probe path** (line 1414): pass `max_attempts=None` (unchanged — the probe is the normal forwarding path and should use the full retry loop).

**Issue #2 — `buffered-response-paths-uncapped`:** Three buffered read loops in `_forward_core` read the upstream response body without a size cap:

| Path | Lines | Current behavior |
|------|-------|-----------------|
| 2xx `application/json` | 1586-1597 | `while True: chunk = resp.read(8192)` — unbounded |
| 2xx other-content-type (chat/response) | 1625-1632 | Same |
| Non-2xx (all modes) | 1657-1664 | Same |

**Fix:** add `PROXY_MAX_RESPONSE_SIZE` size tracking to each loop. Initialize `total_bytes = 0` before the loop. After each `chunks.append(chunk)`, add:

```python
total_bytes += len(chunk)
if total_bytes > PROXY_MAX_RESPONSE_SIZE:
    log_trace({
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "event": "response_size_cap_exceeded",
        "request_id": request_id,
        "bytes_read": total_bytes,
        "limit": PROXY_MAX_RESPONSE_SIZE,
    })
    print("[proxy] Response size limit exceeded ({} bytes), rid={}".format(
        total_bytes, request_id), file=sys.stderr)
    break
```

Apply this pattern to all three loops. The existing first-byte timing tracking is preserved (the cap check comes after the first-byte capture).

**Coder files modified:** `src/claude_retry_proxy/server.py` only.

**Tester verification:**

| Test | What to verify |
|------|---------------|
| `test_compat_retry_lock_released_on_exception` | Already written — should pass after fix. Mock upstream drops connection on stripped retry; proxy returns original 400 after exactly 1 extra upstream attempt. |
| `test_buffered_response_size_cap` | New test. Mock upstream returns body > `PROXY_MAX_RESPONSE_SIZE` on a 2xx JSON path. Proxy truncates at limit, emits `response_size_cap_exceeded` trace event, returns truncated body. |

### Step 2 follow-up: review findings (Warning + 5 Suggestions)

Per [review report](../reports/2026-09-01-learn-context-management-compatibility-review-2026-09-02.json). All changes in `src/claude_retry_proxy/server.py` only.

**Warning 1 — `_compat_normalize_threshold` while-loop is dead code** (`server.py:679-689`):

The while-loop guard `t * MULT <= threshold` can never be true (requires `threshold*2 <= threshold` when `MULT >= 2`). The function just returns `clamp(threshold, 32, 4096)`. A hand-edited off-ladder value (e.g., 50) stays off the ladder forever, violating the plan's invariant "threshold on the doubling ladder."

**Fix:** Start the walk at `COMPAT_INITIAL_THRESHOLD`:
```python
def _compat_normalize_threshold(threshold):
    t = COMPAT_INITIAL_THRESHOLD
    while t * COMPAT_BACKOFF_MULTIPLIER <= min(threshold, COMPAT_MAX_THRESHOLD):
        t *= COMPAT_BACKOFF_MULTIPLIER
    return t
```

**Suggestion 2 — unknown-feature valid entries loaded + re-persisted** (`server.py:772-784`):

A well-formed entry with `feature: "some_future_beta"` passes `_compat_validate_entry` (all fields are valid types), gets loaded into `_compat_state`, and is re-persisted on every transition. The "unknown feature → ignore" skip at line 777-780 only fires when `parsed` is `None` (invalid entry). Example: `{"feature": "some_future_beta", "state": "unsupported", "threshold": 32, ...}` passes validation, is loaded, never matches a request, and is rewritten to disk forever.

**Fix:** In `_compat_validate_entry`, after the existing field-type checks, add:
```python
if feature != COMPAT_FEATURE:
    return None
```
This rejects foreign-feature entries at validation time, so the loader's "unknown feature → ignore" path (line 777-780) fires and they are silently skipped.

**Suggestion 3 — `compatibility_field_stripped` fires for probe-owning request** (`server.py:1330-1359`):

The `compatibility_field_stripped` trace event is emitted at line 1332 before the probe-lock decision at line 1342. When the probe lock is acquired, the feature is NOT popped from the body — the request goes out unstripped. The trace says "field stripped" but the upstream actually received the field. Over a full probe cycle (32 strips + 1 probe), the trace shows 33 `compatibility_field_stripped` events but only 32 requests were actually stripped.

**Fix:** Move the `log_trace("compatibility_field_stripped")` from line 1332 into the `else` branch (after `body_json.pop(COMPAT_FEATURE, None)` at line 1359), so it only fires when the field is actually removed from the outbound body. The probe-owning request already has its own trace event (`compatibility_probe_started`).

**Suggestion 4 — temp file leaked when `os.replace` fails** (`server.py:799-815`):

When `os.replace` fails (PermissionError, disk full), the `except OSError` handler returns `False` without unlinking `tmp`. Each failure leaves one `.<pid>-<uuid>.tmp` file. Aggravated by empty `PROXY_FEATURE_COMPAT_FILE`: `os.path.dirname("")` returns `""`, `os.makedirs("", exist_ok=True)` is a no-op, and the temp file lands in the process CWD with a dot-prefix.

**Fix:**
1. Read `PROXY_FEATURE_COMPAT_FILE` via `_env_str` (the existing helper at `server.py:443-445` that treats empty strings as missing) so an empty value falls back to the default path.
2. In the `except OSError` handler, unlink the temp file:
```python
except OSError:
    try:
        os.unlink(tmp)
    except OSError:
        pass
    return False
```

**Suggestion 5 — dead `trace_fields` mechanism in `_compat_update`** (`server.py:843-853`):

`_compat_update` unpacks `trace_fields` from every mutator (`new_entry, persist, trace_fields = mutate(entry)`) but never uses it. The mutators build dicts (`{"delisted": True}`, `{"threshold": new_threshold}`) that go nowhere. The actual trace events in `_compat_probe_success`/`_compat_probe_rejected` re-derive their fields independently.

**Fix:** Remove `trace_fields` from the mutator contract:
- `_compat_update` signature: remove `trace_fields` from the unpacking and docstring
- All mutators (`_mutate_learn`, `_mutate_probe_success`, `_mutate_probe_rejected`, `_mutate_probe_inconclusive`, `_mutate_delist`): remove the third return element
- `_compat_update` docstring: update to `(new_entry_or_None, persist_flag)` return

**Suggestion 6 — probe path inherits `_DISCONNECT_ERRORS` residual** (`server.py:1411-1422`, `server.py:1728`):

`_stream_upstream_response` only catches `_DISCONNECT_ERRORS`. An exotic Windows client-write OSError (e.g., `WSAENOBUFS`) propagates into `_forward_core`'s broad `except (socket.error, ConnectionError, OSError)`, which re-enters the retry loop and re-issues the unstripped probe POST after response headers were already sent. The duplicate probe outcome can spuriously double the threshold or reset probation. Pre-existing residual class, but the probe gives it a state-corruption consequence the ordinary retry path doesn't have.

**Fix:** In the probe-owner branch (`server.py:1411-1422`), wrap the `_forward_core` call so that if `_stream_upstream_response` was invoked (a 2xx streaming response had its headers sent), the result is NOT re-issued through the retry loop. Simplest approach: in `_forward_core`, add a `no_retry` flag gated on `compat_owned` — once the response body has begun streaming, mark the attempt as non-retryable. Practical approach given the low probability: check `result[0] >= 200 and result[2] == b""` (the streamed-flag contract — streaming returns empty body), and if headers were sent, suppress retry for that attempt:
```python
# In _forward_core, after the streaming branch returns (line 1577-1582 / 1643-1648):
# The streaming path already returns b"" on success. The residual OSError
# only reaches the except block if _stream_upstream_response propagated it.
# For probe-owned requests, treat any post-streaming exception as terminal:
# do not retry if the probe was already streaming (headers committed).
```
Given the exotic nature of this residual (WSAENOBUFS-class, documented as accepted), a minimal fix is to add a comment noting the risk and ensure the probe's `_compat_retry_lock` is released in `finally` (already done). The state-machine consequence is bounded: a spurious double would at worst double the threshold once, and the next probe cycle would revalidate. For now, document the accepted risk in CLAUDE.md's Gotchas alongside the existing `_DISCONNECT_ERRORS` residual entry.

**Coder files modified:** `src/claude_retry_proxy/server.py` only.

**Tester verification:**

| Test | What to verify |
|------|---------------|
| `test_compat_normalize_threshold_ladder` | New or extend existing. Seed `threshold=50`, assert `_compat_normalize_threshold(50)` returns `32` (largest ladder element ≤ 50). Seed `threshold=100`, assert returns `64`. Seed `threshold=5000`, assert returns `4096` (clamped). |
| `test_compat_state_unknown_feature_ignored` | Extend existing. Seed a well-formed entry with `feature: "other"`, assert the entry is NOT loaded (not in `_compat_state`). |
| `test_compat_field_stripped_trace_accuracy` | New test. Send requests through a full probe cycle (threshold=3, monkeypatched), verify `compatibility_field_stripped` count equals actual strips (3), not strips+probe (4). |
| `test_compat_temp_file_cleanup` | New test. Mock `os.replace` to raise OSError, verify the temp file is unlinked (does not exist after persist failure). |
| `test_compat_trace_fields_removed` | No new test needed — verify existing tests still pass after removing the dead `trace_fields` mechanism. |

## Guidance for Tester

**Tests to create:**
- **Permanent:** Compatibility-state load/write/fail-open tests; per-entry validation tests (one-bad-entry-among-good, unknown-feature, higher-version, wrong-typed counters); exact error-detector tests (content-type-agnostic, nested-path rejection, message-form and structured shapes); initial learning tests; failed-confirmation suppression tests; strip/probe/backoff/probation/delist state-machine tests (run in-process at unit level — import `claude_retry_proxy.server` and drive the compatibility subsystem directly, monkeypatching constants to small counts); live-proxy integration tests (seed the state file with near-boundary counters for threshold tests); concurrency single-retry tests; path-isolation tests; `anthropic-beta` forwarding test (extend existing `test_auth_header_anthropic_mode` rather than adding a standalone test); other-field pass-through tests; retry/stream interaction regressions (assert only compatibility-specific deltas; do not re-assert generic retry-count/transform/SSE behavior); metadata-only trace tests; config-swap-during-retry isolation test; `count_tokens` exclusion test; all in `tests/test_claude_proxy.py`.
- **Temporary:** None.

**Step 3:** Extend `tests/test_claude_proxy.py` with permanent compatibility-state and end-to-end tests, and isolate every spawned proxy from the live learned-state file by assigning a session-temporary `PROXY_FEATURE_COMPAT_FILE` before server imports/process launches. <!-- UPDATED 2026-09-02: the test suite was split into 12 modules (tests/_harness.py + 11 cluster modules + aggregator); compat tests live in tests/test_compat.py. The documented entry point `python tests/test_claude_proxy.py` is unchanged. --> Use controllable mock upstream handlers that record headers and request bodies and return deterministic response sequences. Tests may temporarily monkeypatch the source constants or loaded module constants to small counts when exercising threshold/backoff/probation behavior at the unit level; for live-proxy tests, seed the schema-versioned state file with near-boundary counters so the spawned proxy crosses the cap within a few requests. Assert trace events are metadata-only and that ordinary Anthropic pass-through plus all chat/response mode behavior remain unchanged. Do not retire existing tests.
   → tester verify: `python tests/test_claude_proxy.py` reports all tests passing; the run uses a temporary compatibility path and leaves the user's `~/.claude/proxy/feature-compatibility.json` untouched; each new test fails against the pre-change implementation and passes after the implementation.

**Tests to investigate for retirement:**
- No test obsolescence identified. Existing Anthropic pass-through, retry, streaming, mode-dispatch, and non-2xx tests remain valid and should be retained as regressions.

**Specific behavioral expectations:**
- Only `context_management` in Anthropic mode can enter compatibility learning.
- The feature name in state keys and strip logic is always the constant `"context_management"`; field names from upstream error bodies are compared against it and never copied.
- Initial unsupported state requires affirmative recognized 400 evidence followed by a successful stripped retry.
- A failed initial stripped retry returns the original 400 (already model-rewritten via `_rewrite_json_response`) and leaves no state.
- After 3 failed confirmations for the same key, further compatibility retries are suppressed.
- Ordinary unknown fields are never stripped or learned.
- `count_tokens` requests skip compatibility processing entirely.
- Request-count thresholds are exact: 32 strips before the first revalidation, 8 strips between probation probes, ×2 rejection backoff capped at 4096, and two successful probes before delisting.
- Strip counter resets to 0 at probe start; strips concurrent with an in-progress probe count toward the next threshold.
- An unrelated probe result resets the strip counter and reschedules at the current (possibly doubled) threshold without changing support confidence.
- Repeated rejection resets probation to zero but keeps the doubled threshold.
- At most one compatibility retry/probe occurs globally at a time (`_compat_retry_lock`, non-blocking).
- The compatibility retry is a single upstream attempt inside `_forward_request_impl` using the same config/vendors snapshot; it is not subject to the 429/503 retry loop.
- The persistent state and trace events contain no `context_management` value, field name from upstream, or request/error body.
- 2xx evidence is recorded at upstream status receipt, before streaming begins; mid-stream failures do not roll back learned state.
- The full suite baseline before implementation is 209/209 passing; the final suite must have zero failures.

## Guidance for Planner

Documentation and lifecycle tasks to execute personally:

- **Doc files to create/update:** `README.md`, `CLAUDE.md`.
- **When:** After coder and tester finish, before Final Results and commit approval.
- **What to sync:**
  - Anthropic-mode compatibility behavior; absence of a general whitelist; sole probe-eligible feature.
  - Exact evidence policy (content-type-agnostic, two enumerated shapes, constant-anchored, nested-path exclusion).
  - Request-count thresholds and source constants; failed-confirmation suppression count.
  - Persistence path and `PROXY_FEATURE_COMPAT_FILE`; state privacy/fail-open behavior; per-entry validation.
  - `anthropic-beta` forwarding; trace events; test isolation; runtime artifacts and environment-variable tables.
  - Two locks: `_compat_state_lock` (fast) and `_compat_retry_lock` (non-blocking, one global retry/probe at a time).
  - **CLAUDE.md Architecture:** update the "Request body is built once before the retry loop — never re-transformed on retry" invariant to note that a stripped variant is derived from the already-transformed outbound body for compatibility retries.
  - **README.md Provider Modes table:** update the anthropic-mode row from "Request/response body is model-name-rewritten only" to mention learned conditional stripping of `context_management`.
  - **CLAUDE.md Gotchas:** update the "(209 tests)" figure to the new post-implementation suite total (and refresh its "updated" date).
  - **CLAUDE.md Gotchas:** update the "(209 tests)" figure to the new post-implementation suite total (249 tests) and refresh its "updated" date. Document the new tests/ layout (12 modules + aggregator).
  - **CLAUDE.md Gotchas:** reconcile the "response-streaming-no-size-cap is partially addressed" gotcha — all four streaming loops now apply `PROXY_MAX_RESPONSE_SIZE` checks. Also review the coder-filed `buffered-response-paths-uncapped` issue for the buffered-paths cap gap.
  - **Windows `icacls` gotcha:** add the new `feature-compatibility.json` file to the runtime-artifacts list and the Windows ACL caveat.
- **Issue lifecycle:** After tester success and final review, update `tmp/reports/defer-issue-opencode-zen-claude-rejects-extra-inputs.json` to `Resolved` with the implementation/test evidence, remove it from `CLAUDE.md`'s unresolved list, and record resolution in this plan's Issue Log and Final Results.

## Summary

The proxy currently forwards Anthropic-mode request fields unchanged except for `model`. Some third-party Anthropic-compatible providers implement only a subset of the current Anthropic API and reject the valid beta `context_management` field. This plan adds a deliberately narrow compatibility learner for that one field rather than maintaining a broad API whitelist or exposing provider-specific configuration to users.

```text
Anthropic request with context_management
                 |
                 v
        learned unsupported?
          /             \
        no               yes
        |                 |
 forward unchanged   strip for N matching requests
        |                 |
 recognized exact 400?    +-- threshold reached --> one unstripped probe
   /          \                              /          |          \
 no            yes                         2xx    same exact 400   other
 |              |                           |           |           |
return       retry once stripped       probation/   retry stripped  reschedule
error             |  (single attempt,  delist        + backoff       unchanged
                  |   same snapshot,               (doubled, keeps
             2xx / non-2xx       suppress_compat)   threshold)
              |       |
            learn   return original 400
            (state)   (model-rewritten)
              |
   failed confirmations >= 3 → suppress future retries
```

The learned key is `(provider, mode, actual upstream model, context_management)`. The feature name is always the constant `"context_management"` — field names from upstream error bodies are compared against it and never copied into state keys, strip targets, or trace events. Revalidation is driven only by matching request counts, not elapsed time. Source constants make every learning parameter easy for maintainers to tune without adding a user-facing configuration surface. Chat and Responses modes retain their existing explicit transformations and do not participate.

**Concurrency model:** `_compat_state_lock` (held for microseconds) protects the state dict; `_compat_retry_lock` (non-blocking, one global retry/probe at a time) serializes the slow HTTP operation. No per-key tracking needed — the probability of concurrent compatibility operations across different providers is negligible, and skipping a retry for a concurrent request returns the original error (no regression).

**Alternatives rejected:**
- General whitelist filtering: risks silently deleting newly released Anthropic fields and requires continuous spec synchronization.
- User-managed provider denylist: exposes transport compatibility details the user should not need to understand.
- Broad 400 regex learning: creates false-positive risk and can silently degrade valid requests.
- Time-based revalidation: unnecessary for rarely used combinations; request-count impact naturally scales with traffic.

**Out of scope:** Any feature other than top-level `context_management`; nested-field learning; recursive elimination of multiple rejected fields; chat/response compatibility learning; admin UI controls; user-editable learning parameters; provider capability discovery APIs; time-based expiry or probing; multi-process state-file sharing.

## Configuration Surface

The compatibility subsystem is configured entirely through source constants in `server.py` (no user-facing configuration surface). Constants:

| Constant | Default | Description |
|----------|---------|-------------|
| `COMPAT_INITIAL_THRESHOLD` | 32 | Strips before first revalidation probe |
| `COMPAT_PROBATION_THRESHOLD` | 8 | Strips between probation probes |
| `COMPAT_BACKOFF_MULTIPLIER` | 2 | Threshold multiplier on repeated rejection |
| `COMPAT_MAX_THRESHOLD` | 4096 | Maximum strip threshold |
| `COMPAT_DELISTING_SUCCESSES` | 2 | Successful probes to delist (restore support) |
| `COMPAT_MAX_RETRIES_PER_REQUEST` | 1 | Maximum compatibility retries per client request |
| `COMPAT_FAILED_CONFIRMATION_SUPPRESSION` | 3 | Failed confirmations before suppressing retries |

**Environment variables:**

| Variable | Default | Description |
|----------|---------|-------------|
| `PROXY_FEATURE_COMPAT_FILE` | `~/.claude/proxy/feature-compatibility.json` | Compatibility state file path |

**Disable learning:** delete the state file or set `PROXY_FEATURE_COMPAT_FILE` to an empty/writable temporary path (e.g., `/dev/null` on POSIX, `NUL` on Windows). There is no dedicated kill-switch env var; the state file is the kill-switch.

## Rollback Plan

The feature is additive — no existing signatures are removed. Rollback:
1. `git revert` the feature commit.
2. Delete `~/.claude/proxy/feature-compatibility.json` (or the `PROXY_FEATURE_COMPAT_FILE` path) to clear any persisted learned state. Stale state is harmless after revert (the loader is removed), but the file can be cleaned up.
3. Restart the proxy.

## Migration Plan

- **First run / missing file:** default to empty state — all features assumed supported. No startup warning.
- **Schema versioning:** the persisted file has a `schema_version` integer. On load: unknown/absent version → warn + fail open empty; known version → per-entry validation; higher version (downgrade scenario) → warn + fail open empty. The initial version is `1`.
- **Upgrade path:** future versions increment the schema version. The loader skips unknown schema versions (fail open). Entries with unknown feature keys are ignored (forward-compat).
- **Reset:** delete the state file to reset all learned state to defaults.
- **No data migration:** the state file is disposable — no user data, no configuration, no keys. Deleting it is always safe.

## Repo Mode

Public

*Detected at plan creation. Determines: plan archival path, commit-message content, staged files.*

## Document Overrides

| Document | Rule Overridden | Reason |
|----------|----------------|--------|

## Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| False-positive learning from an ambiguous 400 | Valid context management is silently removed | Require enumerated JSON error shapes, exact field presence, constant-anchored feature name, and a successful stripped confirmation; no broad regex or arbitrary-field learning. |
| Compatibility retry duplicates a request | Duplicate upstream work or cost | Probe only schema-validation 400 responses, which precede inference; cap compatibility retries at one; global non-blocking `_compat_retry_lock` serializes all retries/probes. |
| Removing `context_management` changes long-session behavior | Context editing/compaction may not occur on that provider | Strip only after confirmed rejection, trace every decision, and periodically revalidate with two-success delisting. |
| Concurrent probes or state writes race | Excess 400s, lost counters, corrupt state | Two locks: `_compat_state_lock` (fast) for state dict, `_compat_retry_lock` (non-blocking) for HTTP calls; atomic replace with unique temp filename; idempotent updates; and concurrency tests. |
| Test run touches live user compatibility state | Corrupts real learned behavior | Set `PROXY_FEATURE_COMPAT_FILE` to a session-temporary path before imports/process launches. |
| Missing `anthropic-beta` changes feature negotiation | Learner diagnoses a proxy-induced rejection as provider incompatibility | Forward `anthropic-beta` before enabling detection and test it end to end. |
| Repeated failed confirmations cause unbounded upstream call duplication | Every matching request costs 2 upstream calls indefinitely | In-memory per-key failed-confirmation counter; suppress further retries after `COMPAT_FAILED_CONFIRMATION_SUPPRESSION` (default 3) failures; re-enter discovery after `threshold` stripped requests. |
| Persisted state lost on restart (in-memory counters) | Strip counter/probation counter reset to zero | Fail-safe: counters reset to zero, so the next strip cycle starts from the beginning — over-stripping (never under-stripping). State transitions (threshold, probation state) are persisted and survive restart. |
| Poisoned learned state survives restarts | Bad policy persists indefinitely | State file is user-deletable; count-based revalidation self-heals if matching traffic recurs; two-success delisting provides automatic recovery. See Rollback Plan. |
| `anthropic-beta` forwarding changes behavior for previously-working setups | Providers may react differently to the header | The header is a valid Anthropic beta header; providers that ignore it should be unaffected; providers that respect it gain the feature they were missing. |

## Proposed Changes

1. **Step 1:** Implement the compatibility policy, state model, atomic persistence, two locks, and per-entry validation in `src/claude_retry_proxy/server.py`.
   → coder verify (auto): all policy constants, the sole `context_management` entry, state helpers, two locks, per-entry validation, and atomic writer are present; no whitelist or second learnable field exists.
   → tester verify: persistence, corruption, isolation, per-entry validation, metadata privacy, and concurrency tests pass.

2. **Step 2:** Integrate `anthropic-beta` forwarding and the bounded learn/strip/probe/backoff/probation/delist/suppression flow into Anthropic request forwarding (inside `_forward_request_impl`, `suppress_compat=True`).
   → coder verify (auto): compatibility processing is Anthropic-only, constant-anchored, one-retry-bounded, content-type-agnostic, inside `_forward_request_impl` with same snapshot, and leaves chat/response transforms plus ordinary retries intact.
   → tester verify: all state transitions, error outcomes, threshold boundaries, concurrency behavior, config-swap isolation, and retry/stream regressions pass.

3. **Step 3:** Add permanent compatibility tests and live-state-file isolation in `tests/test_claude_proxy.py` (unit-level for state machine, live-proxy with seeded state for thresholds).
   → tester verify: full test suite passes with zero failures and no writes to the default compatibility path.

4. **Step 4:** Update `README.md`, `CLAUDE.md`, deferred-issue status, and final plan records after implementation and review.
   → Evidence: documentation diff matches final behavior; unresolved list and deferred report agree; final tester and reviewer reports are linked.

## History

| Date | Event | Conclusion | Dismissed |
|------|-------|------------|-----------|
| 2026-09-01 | Initial plan | User confirmed a one-feature, Anthropic-only compatibility learner with exact error patterns, request-count revalidation, proposed default constants, and `feature-compatibility.json`. | — |
| 2026-09-01 | Mega-audit revisions | 3 High, 25 Medium, 15 Low findings resolved. Added: retry re-entry spec (inside `_forward_request_impl`, same snapshot, `suppress_compat`), content-type-agnostic detector, global non-blocking `_compat_retry_lock`, constant-anchored feature name, per-entry validation, write-cadence spec, failed-confirmation suppression, probe scheduling semantics, `count_tokens` exclusion, response body size cap, Rollback Plan, Migration Plan, Configuration Surface, doc-file sync items. Moved Steps 3→Tester, 4→Planner. Fixed Issue Log status. | — |
| 2026-09-02 | Coder/tester round 3 — review findings resolved | All 6 review findings implemented and verified. W1: threshold ladder walk starting at `COMPAT_INITIAL_THRESHOLD`. S2: foreign-feature entries rejected at validation. S3: `field_stripped` trace moved to actual-strip branch. S4: temp file unlinked on persist failure + `_env_str` for env var. S5: dead `trace_fields` removed. S6: documented as accepted residual (planner Step 4). 253/253 tests pass. | — |
| 2026-09-02 | Coder/tester round 2 — both open issues resolved | `compat-retry-not-single-attempt`: `_forward_core` gains `max_attempts=None` param; `_forward_request_impl` passes `max_attempts=1` when `suppress_compat=True`. `buffered-response-paths-uncapped`: three buffered read loops now capped at `PROXY_MAX_RESPONSE_SIZE` with `response_size_cap_exceeded` trace event. Tester round 2: 250/250 pass, zero failures. Plan ready for review and Step 4 doc sync. | — |

## Plan Metadata

```json
{
  "plan_id": "2026-09-01-learn-context-management-compatibility",
  "steps": [
    "Step 1: Implement compatibility policy and state persistence",
    "Step 2: Integrate compatibility learning into Anthropic forwarding",
    "Step 3: Add permanent compatibility tests and isolation",
    "Step 4: Reconcile documentation and issue lifecycle"
  ],
  "coder_files": [
    "src/claude_retry_proxy/server.py"
  ],
  "tester_files": [
    "tests/test_claude_proxy.py",
    "tests/_harness.py",
    "tests/test_compat.py",
    "tests/test_admin.py",
    "tests/test_chat_sse.py",
    "tests/test_chat_transform.py",
    "tests/test_cli.py",
    "tests/test_config_keys.py",
    "tests/test_mode_dispatch.py",
    "tests/test_response_transform.py",
    "tests/test_retry_streaming.py",
    "tests/test_tier_routing.py",
    "tests/test_trace.py",
    "tests/test_unit.py"
  ],
  "doc_files": [
    "README.md",
    "CLAUDE.md"
  ],
  "verification_scripts": [],
  "repo_mode": "Public",
  "document_overrides": []
}
```

## Audit Accumulation

| Counter | Value | Last Updated |
|---------|-------|--------------|
| issues_resolved_since_audit | 0 | 2026-09-01 |
| steps_changed_since_audit | 0 | 2026-09-01 |
| files_changed_since_audit | 0 | 2026-09-01 |

## Documentation

- `README.md`: user-facing description of automatic compatibility learning, state path, tunable source defaults, behavior/privacy caveats, and runtime environment/path reference.
- `CLAUDE.md`: maintainer architecture, exact state machine and constants, two-lock concurrency model, gotchas, test isolation, trace events, runtime artifact list, and deferred-issue resolution.

## Final Results

**Status:** COMPLETED — 2026-09-02

**Implementation:** Coder completed Steps 1-2 (compatibility policy, state persistence, learning, stripping, probing, delisting), three follow-up rounds (single-attempt compat retry, buffered response caps, review findings), all in `src/claude_retry_proxy/server.py`.

**Tests:** 253/253 pass (209 original + 40 compat + 1 cap test + 3 review-fix tests). Tester split the 12,375-line test monolith into 12 modules (`tests/_harness.py` + 11 cluster modules + aggregator). All pre-existing tests pass unchanged. Permanent compat tests cover persistence/fail-open, exact detector shapes, state machine transitions, concurrency bounds, `count_tokens` exclusion, metadata-only trace privacy, threshold normalization, foreign-feature rejection, probe trace accuracy, and temp file cleanup.

**Issues resolved:**
- [`opencode-zen-claude-rejects-extra-inputs`](../reports/defer-issue-opencode-zen-claude-rejects-extra-inputs.json) — the deferred issue this plan targeted. The proxy now learns per-provider `context_management` incompatibility from recognized 400 responses and strips the field on subsequent requests.
- [`compat-retry-not-single-attempt`](../reports/2026-09-01-learn-context-management-compatibility-compat-retry-not-single-attempt.json) — `_forward_core` `max_attempts` parameter; compatibility retries are now single upstream attempts.
- [`buffered-response-paths-uncapped`](../reports/2026-09-01-learn-context-management-compatibility-buffered-response-paths-uncapped.json) — three buffered read loops capped at `PROXY_MAX_RESPONSE_SIZE`.
- [`review-findings`](../reports/2026-09-01-learn-context-management-compatibility-review-2026-09-02.json) — 1 Warning + 5 Suggestions all fixed and verified.

**Pending:** Step 4 doc sync (CLAUDE.md/README.md updates, deferred-issue lifecycle in CLAUDE.md's Unresolved Deferred Issues). The [`break-up-large-source-and-test-files`](../reports/defer-issue-break-up-large-source-and-test-files.json) deferred issue remains open (test file split done; source file split pending).

**Files changed:** `src/claude_retry_proxy/server.py`, `tests/test_claude_proxy.py`, `tests/_harness.py`, `tests/test_admin.py`, `tests/test_chat_sse.py`, `tests/test_chat_transform.py`, `tests/test_cli.py`, `tests/test_compat.py`, `tests/test_config_keys.py`, `tests/test_mode_dispatch.py`, `tests/test_response_transform.py`, `tests/test_retry_streaming.py`, `tests/test_tier_routing.py`, `tests/test_trace.py`, `tests/test_unit.py`.