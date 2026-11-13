# Plan: Close the test-harness port-allocation races and preserve failure evidence
**Plan ID:** 2026-11-12-test-harness-port-hardening
**Created:** 2026-11-12

## Immediate Actions

**Tester:**
- Execute Step 11 only (one edit in `tests/_harness.py`): add the `winerror 10048` arm to `_bind_mock_server`'s except, per the literal old→new block.
- Run `timeout 120 python ./tmp/verification/2026-11-12-test-harness-port-hardening-bind.py` (expect exit 0, 19/19 — assertion 11 added).
- Run `timeout 300 python tests/test_harness_hardening.py` (3/3) and `timeout 900 python tests/test_claude_proxy.py` (0 failed).
- Write the session report.

## Issue Log

Rows ordered newest-first (latest issues at top). New issues are prepended; resolved issues stay in place with updated status.

| Issue | Status | Found | Resolved | Resolved By |
|-------|--------|-------|----------|-------------|
| [review-R1-windows-winerror-10048](./tmp/reports/2026-11-12-test-harness-port-hardening-review-2026-11-13.json) | Resolved | 2026-11-13 | 2026-11-13 | [tester](./tmp/reports/2026-11-12-test-harness-port-hardening-tester-2026-11-13.json) — Step 11 landed in round 2: bind gate 19/19 (assertion 11 PASS), full suite 503/503, planner re-ran the gate independently (19/19, exit 0). |
| [flaky-chat-sse-transition-empty-stream](./tmp/reports/defer-issue-flaky-chat-sse-transition-empty-stream.json) | Resolved | 2026-10-25 | 2026-11-13 | [tester](./tmp/reports/2026-11-12-test-harness-port-hardening-tester-2026-11-13.json) — self-classifying failure message (frame types + raw head) landed (Step 9) and the evidence survives failure (trace + stderr preserved, Step 8); the transition test passes 76/76 in its module and in the full suite. |
| [admin-straggler-eaddrinuse](./tmp/reports/defer-issue-admin-straggler-eaddrinuse.json) | Resolved | 2026-10-25 | 2026-11-13 | [tester](./tmp/reports/2026-11-12-test-harness-port-hardening-tester-2026-11-13.json) — bind-first with ephemeral rebind + URL correction at all four builders and the six direct sites, `caller_owns_ports` for the pre-binding family, proxy-port spawn retry keyed on the server's real busy-port message, `server_close()` at all six harness teardown sites plus the six direct-site teardowns; pinned behaviorally by the three new harness-* tests and all four gates (planner re-ran them independently: 18/18, 10/10, 9/9, 3/3, exit 0). |

Both rows were adoptions; each row is the retirement trigger for its report
(`/update-and-commit` Step 9.6 deletes the report on this Resolved status).

## Guidance for Coder

**Files to modify:** none — this plan changes no source code and no product
behavior. Every change is test infrastructure (`tests/_harness.py` and test
modules), which is the tester's lane (precedent:
`plans/2026-10-03-stale-test-state-file-pid-reuse.md`, same situation). Do not
touch `src/`, `doc/`, `CLAUDE.md`, or `README.md`.

**Step-by-step with verification:** there are no coder steps. All checks are
tester checks (below); the tester self-verifies `(scripted)` checks by running
the provided gates.

## Guidance for Tester

**Files to modify:** `tests/_harness.py`, `tests/test_admin.py`,
`tests/test_cli.py`, `tests/test_retry_streaming.py`,
`tests/test_tier_routing.py`, `tests/test_chat_sse.py`,
`tests/test_harness_hardening.py` (new), `tests/test_claude_proxy.py`
(aggregator registration).

**Operational discipline (read first):**
- Every command that can spawn a proxy, bind a socket, or run a test module
  MUST carry an explicit timeout (e.g. `timeout 300 python tests/test_admin.py`).
  A hung socket read otherwise stalls the round (lesson recorded in plan
  `2026-10-15-chat-sse-stream-tail.md`).
- The steps below carry literal old→new edits keyed to unique anchor text, not
  line numbers (lines shift as edits land). Match the `old` block exactly —
  indentation included, including continuation-line alignment — and replace
  with the `new` block.
- All edits are in test files only. `src/` is out of bounds; if a step seems
  to require touching `src/`, stop and file an issue report instead.
- Gates print one PASS/FAIL line per assertion and a final summary; a gate's
  **exit code stays 1 mid-group by design** — individual steps state which
  assertions must print PASS at that point, and only the named final runs
  require exit 0.

**Tests to create:**
- **Permanent** (new module `tests/test_harness_hardening.py`, registered in
  the aggregator — see Step 10 for the complete body):
  - `harness-bind-fallback-rebinds-and-url-follows` — a vendor port held by a
    foreign listener makes the mock rebind ephemeral and the vendor URL follow
    it; the request path still works end to end.
  - `harness-proxy-port-busy-retries-once` — a proxy spawn onto a held port
    is detected via marker-vs-connect discrimination and retried once on a
    fresh port, coming up ready.
  - `harness-cleanup-preserves-artifacts-on-failure` — with the failure flag
    set, `cleanup()` keeps `temp_dir` + trace + stderr dump and prints their
    paths.

**Tests to investigate for retirement:**
- Planner candidates: **none.** No test is tied to code being removed or
  changed in behavior — the collision test in `tests/test_tier_routing.py`
  (the one with `CollisionHandler`) is about model-name collisions between
  tiers, builds its own config/keys, spawns through the unchanged
  `_start_proxy_server_directly`, and is unaffected. The SSE-rewrite pre-bind
  family keeps its skip semantics behind `caller_owns_ports=True` (Step 5).
  No test obsolescence identified.
- Tester may identify additional candidates during test work.

**Retirement procedure:** For each candidate, verify the test exercises code
being removed/changed. If obsolete: delete and note in session report. If still
valid: document why in session report.

## Summary

The suite intermittently crashes at test setup with `[Errno 98] Address
already in use` (observed 2-of-3 full-suite runs on 2026-10-25, deferred issue
`admin-straggler-eaddrinuse`), and the one unexplained wire flake
(`chat-sse-reasoning-then-text-transition`, deferred issue
`flaky-chat-sse-transition-empty-stream`) is undiagnosable because `cleanup()`
deletes the per-test trace before anyone can read it. Both are test-harness
defects; no `src/` code is implicated.

Root cause of the crash: `find_free_port()` (`tests/_harness.py`) binds `:0`,
reads the port, closes the socket, and returns the number — the port is
unowned between that close and the caller's real bind. The number is baked
into vendor URLs written to `keys.json` *before* the mock binds, so a
collision at bind raises out of the test body ("Test crashed"). Amplifier:
mock listening sockets are never closed at teardown (`shutdown()` without
`server_close()`), leaving listeners alive until the server object is
collected.

Fix — five mechanisms, all in `tests/_harness.py` + test files:

```
probe (:0, close) → URL frozen into keys.json → mock bind P     ← crash point (today)
                                    │
                                    ▼  (this plan)
bind mock P, else :0-fallback → patch URL to server_address[1] → write keys.json
  (all four builders incl. _setup_tier_routing_test's majority path;
   the 3 SSE-rewrite pre-bind callers keep skip semantics via caller_owns_ports)
proxy spawn → READY-marker-seen is the only trusted success; a connect-only
  probe success is confirmed by the child surviving a short grace; a child
  that died naming the busy port (the server's own guard message or the raw
  OSError) is retried once on a fresh port
teardown  → shutdown() + server_close()   (early branches, cleanups, and the
  six direct-site teardowns; other test-local listeners are an accepted residual)
failure   → cleanup() keeps temp_dir + trace + a stderr dump, prints paths
  (covers fail() AND in-flight exceptions)
```

Alternatives considered and rejected: (1) migrating every `find_free_port()`
call site to bind-first (measured 2026-11-12: 246 sites) — huge diff, no
marginal gain over fixing the concentration points; (2) giving
`_start_streaming_mock_upstream` the EADDRINUSE *skip* tolerance — skipping
the listener leaves no upstream, converting a crash-flake into a
no-upstream-flake; the fallback must *rebind*, not skip (skip survives only
where the caller's own listener is the upstream, i.e. the
`caller_owns_ports=True` family); (3) retry-only at bind sites without URL
correction — hides the race and leaves stale URLs.

Out of scope: `src/` changes of any kind (the retry wrapper matches the
server's existing busy-port message; no server change is needed); the
`redacted_thinking` placeholder removal (separate deferral); the analyzer
escape fix and `Server`/`Date` header fix (Plan B, separate).

## Repo Mode

Public

*Detected at plan creation. Determines: plan archival path, commit-message content, staged files.*

## Document Overrides

If the plan intentionally contradicts a documented rule (in `CLAUDE.md` or `doc/*`), declare the override here. An empty or absent table means zero tolerance — every documented rule is in force.

| Document | Rule Overridden | Reason |
|----------|----------------|--------|

## Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Reorder (bind before keys write) breaks a fixture that reads config during bind | Test failures in unrelated modules | Verified none exist: `_models_for_vendors` reads provider names only, not URLs; the builders are the only consumers of the vendors dict at that point. Full-suite run is the gate. |
| `_TEST_FAILED` misses failures recorded after `cleanup()` ran | Late-failure evidence for that proxy lost | `cleanup()` also preserves when an exception is in flight (`sys.exc_info()`), covering crash-shaped failures — the dominant hard-to-diagnose class. A failure recorded strictly after `finally` still leaves its message. |
| Proxy-port retry misfires on localized stderr | One wasted respawn then normal failure path | The primary match is the server's own fixed guard message (`"is already in use"`, not localized — it is a literal in `server.py`); the raw-OSError forms (`Errno 98`, `10048`) are secondary matches for the probe-to-bind window. |
| Preserved artifacts accumulate unboundedly | Disk growth in system temp | Preserved dirs only appear on failure (rare), are inert, and are named in the run output; manual cleanup suffices. Each carries the trace file's 0600 permissions. |
| Test-local listeners outside the plan's touched sites still `shutdown()` without `server_close()` | Residual zombie-listener exposure (e.g. the SSE pre-bind fixtures' own listeners) | Accepted residual: the crash family the deferral names ran through the builder path, which is fully covered; the residual listeners are few and short-lived. Recorded here deliberately. |
| URL patch uses `parsed.scheme/hostname` | A vendor URL with auth/path components would be rebuilt bare | All suite URLs are `http://127.0.0.1:<port>`; the rebuild preserves scheme+host and replaces only the port, matching every existing fixture. |
| Intermediate state between Step 1 and Steps 3-5 converts a mock-bind collision from a crash into a silent wrong-port failure | Transient, only if a collision occurs mid-implementation | Steps land in one round; the note on Step 1's verify marks its run as normal-path smoke only, with collision evidence coming from Step 10's fallback test. |

## Proposed Changes

Each step includes verification checks tagged with confidence. `(scripted)` checks are gates the tester runs; behavioral checks are the tester's own tests. All steps are tester-lane (no coder steps in this plan). Every command below that runs a test or gate must carry an explicit timeout.

**Gate baselines (RED, pre-change):** measured against the untouched tree on 2026-11-12 for the original four gates, re-measured 2026-11-13 after the post-audit gate rebuild:
- `-bind.py`: only the unchanged-behavior pin (`_setup_tier_routing_test` keeps an inline `ThreadingHTTPServer` bind — true until Step 5 replaces the majority path; the `caller_owns_ports=True` branch keeps its own) prints PASS; every other assertion FAILs with detail.
- `-spawn.py`: only the `_start_proxy_server_directly` still-defined pin.
- `-cleanup.py`: only the success-path rmtree and `fail()`-appends-to-errors pins.
- `-chat-sse-message.py`: only the test-exists pin.
- Every FAIL line names the concrete miss (e.g. `last_bind_line=1085 first_keys_line=1070`). The constructor-detection predicate was probed against a synthetic wrong implementation (inline ctor → verdict False) and a synthetic right one (helper → verdict True): teeth and satisfiability confirmed.

**Step 6 target functions (the exhaustive six, per the gate's pre-change enumeration):** `tests/test_cli.py::test_cli_reload`, `tests/test_cli.py::test_cli_status_shows_tiers`, `tests/test_cli.py::test_start_status_reload_tier_lines_show_key`, `tests/test_admin.py::test_admin_api_reload`, `tests/test_admin.py::test_admin_switch_validates_key_names`, `tests/test_retry_streaming.py::test_retry_path_print_failure_does_not_misclassify`. The edits below land one per function, in the order listed.

1. **Step 1: Add `_MockHTTPServer` + `_bind_mock_server`; migrate the three mock starters to it**

   Insert into `tests/_harness.py` immediately before `def _start_mock_upstream(port, req_list):`:

   ```python
   class _MockHTTPServer(http.server.ThreadingHTTPServer):
       """ThreadingHTTPServer with POSIX-only SO_REUSEADDR, mirroring the
       proxy's own _ProxyHTTPServer (src server.py): http.server's default
       allow_reuse_address=1 lets a second listener bind a port a live
       listener already holds on Windows, which would defeat the EADDRINUSE
       fallback _bind_mock_server depends on."""
       allow_reuse_address = (sys.platform != "win32")


   def _bind_mock_server(handler_cls, preferred_port):
       """Bind a _MockHTTPServer on preferred_port, falling back to an
       ephemeral port on EADDRINUSE.

       find_free_port() hands out a port nobody owns between its probe's
       close and the caller's real bind (the TOCTOU behind the intermittent
       [Errno 98] setup crashes). Binding preferred-first with an ephemeral
       fallback keeps the requested port in the common case and removes the
       crash; callers that embed the port in a config/keys URL must use the
       port the server actually owns — server.server_address[1] — not the
       number they asked for.
       """
       try:
           server = _MockHTTPServer(("127.0.0.1", preferred_port), handler_cls)
       except OSError as e:
           if e.errno != errno.EADDRINUSE:
               raise
           server = _MockHTTPServer(("127.0.0.1", 0), handler_cls)
       return server
   ```

   Then in each of the three starters — `_start_mock_upstream`,
   `_start_streaming_mock_upstream`, `_start_mode_mock_upstream` — replace the
   tail constructor line (4-space indent, the starters' own; NOT the
   8-space-indented one inside `_setup_tier_routing_test`'s `try:`, whose
   majority path Step 5 replaces and whose pre-bind branch keeps):

   ```python
   # old (in each of the three starters)
       server = http.server.ThreadingHTTPServer(("127.0.0.1", port), MockHandler)
       thread = threading.Thread(target=server.serve_forever, daemon=True)
   # new
       server = _bind_mock_server(MockHandler, port)
       thread = threading.Thread(target=server.serve_forever, daemon=True)
   ```

   Return shapes are unchanged (`server` only) — all existing callers keep
   working; the six direct test-file call sites are corrected in Step 6.

   → tester verify (scripted): `timeout 120 python ./tmp/verification/2026-11-12-test-harness-port-hardening-bind.py` — assertions 1, 2, 7 must print PASS (the script's exit stays 1 until Steps 3-6 land)
   → tester verify: `timeout 300 python tests/test_admin.py -t admin-switch-pre-first-byte-straggler` passes — **normal-path smoke only**, not collision evidence (a collision at this intermediate point yields a wrong-port failure until Steps 3-5 land; the collision behavior is proven by Step 10's fallback test)

2. **Step 2: `_spawn_proxy_with_bind_retry` (marker-gated) + `_readiness_detail` plumbing; migrate the three in-harness proxy spawn sites**

   First, the optional detail kwarg in `_start_proxy_server_directly`
   (`_wait_for_readiness` itself is NOT touched — its contract is pinned by
   plan 2026-11-03's tests):

   ```python
   # old
   def _start_proxy_server_directly(port, config_path=None, keys_path=None,
                                     passphrase="test-passphrase", trace_file=None, cwd=None,
                                     extra_env=None):
   # new
   def _start_proxy_server_directly(port, config_path=None, keys_path=None,
                                     passphrase="test-passphrase", trace_file=None, cwd=None,
                                     extra_env=None, _readiness_detail=None):
   ```

   ```python
   # old
       probe_ok = _wait_for_readiness(proc, port, ready_event)
       return proc, probe_ok
   # new
       probe_ok = _wait_for_readiness(proc, port, ready_event)
       if _readiness_detail is not None:
           # True from the TCP fallback alone does not mean the CHILD is
           # listening — a foreign listener holding the port also accepts the
           # connect. The bind-retry wrapper reads marker_seen from this dict
           # to discriminate; every other caller ignores the kwarg.
           _readiness_detail["marker_seen"] = ready_event.is_set()
       return proc, probe_ok
   ```

   Then insert into `tests/_harness.py` immediately before `def _send_proxy_request(port, path="/v1/messages", body=None, headers=None):`:

   ```python
   _BIND_RACE_GRACE_SECONDS = 1.5


   def _spawn_proxy_with_bind_retry(port, **kwargs):
       """Spawn the proxy via _start_proxy_server_directly, retrying once on a
       fresh port when the child died of a busy listen port.

       The proxy's own port comes from find_free_port() and carries the same
       TOCTOU window as the mock ports. Two facts shape the discrimination:
       (1) the server pre-probes its port and exits with the fixed message
       "[proxy] Port {N} is already in use." — the raw OSError text reaches
       stderr only in the narrow probe-close-to-bind window, so both forms
       are matched; (2) the readiness probe's TCP-connect fallback succeeds
       against a FOREIGN listener holding the port, so probe_ok=True does not
       by itself mean the child is up. marker_seen (plumbed through the
       optional _readiness_detail dict) is the trustworthy success signal; a
       connect-only success is confirmed by the child staying alive past a
       short grace — a child that lost its bind exits within ~1s of spawn.
       Real startup failures (bad config, bad keys) die with other stderr and
       surface unchanged. _start_proxy_server_directly's signature is
       unchanged apart from the optional kwarg; its direct test-file callers
       keep today's behavior.

       Returns (port, proc, probe_ok): `port` is the port actually bound and
       must replace the caller's copy.
       """
       for attempt in (0, 1):
           detail = {}
           proc, probe_ok = _start_proxy_server_directly(
               port, _readiness_detail=detail, **kwargs)
           if probe_ok and not detail.get("marker_seen"):
               # Connect-only success: the connect may have reached a foreign
               # listener holding the port. A child that lost its bind exits
               # quickly; confirm liveness before trusting the probe.
               try:
                   proc.wait(timeout=_BIND_RACE_GRACE_SECONDS)
               except subprocess.TimeoutExpired:
                   pass
               if proc.poll() is None:
                   return port, proc, True
               probe_ok = False
           if probe_ok:
               return port, proc, True
           if attempt == 1:
               return port, proc, False
           if proc.poll() is None:
               # Alive but not ready: not a bind race; surface as before.
               return port, proc, False
           stderr = _read_child_stderr(proc) or ""
           proc.wait()  # reap the dead first attempt; returncode is set
           if ("is already in use" not in stderr
                   and "Address already in use" not in stderr
                   and "Errno 98" not in stderr
                   and "10048" not in stderr):
               # Died of something else; surface as before.
               return port, proc, False
           port = find_free_port()
       return port, proc, probe_ok  # unreachable
   ```

   Migrate `_setup_tier_routing_test`'s spawn (its mock-bind logic is Step 5's
   business, not this edit):

   ```python
   # old
       proc, probe_ok = _start_proxy_server_directly(
           proxy_port, config_path=config_path, keys_path=keys_path,
           passphrase=default_passphrase, trace_file=trace_file
       )
   # new
       proxy_port, proc, probe_ok = _spawn_proxy_with_bind_retry(
           proxy_port, config_path=config_path, keys_path=keys_path,
           passphrase=default_passphrase, trace_file=trace_file
       )
   ```

   The builder spawns (admin/mode) are migrated inside Steps 3-4's larger
   edits.

   → tester verify (scripted): `timeout 120 python ./tmp/verification/2026-11-12-test-harness-port-hardening-spawn.py` — assertions 1, 2, 5, 6 must print PASS after this step for the wrapper itself; assertions 3-4 (per-site migration) complete with Steps 3-5 (exit stays 1 until then)
   → tester verify: `harness-proxy-port-busy-retries-once` (Step 10) passes — the behavioral proof of the marker-vs-connect discrimination

3. **Step 3: `_start_admin_proxy` — bind mocks before writing config/keys, patch the vendor URL to the bound port**

   One edit replacing the body from `temp_dir = tempfile.mkdtemp(prefix="proxy_admin_")` through the `_start_proxy_server_directly` call:

   ```python
   # old
       temp_dir = tempfile.mkdtemp(prefix="proxy_admin_")
       proxy_port = find_free_port()
       if models is None:
           # Every vendor in keys needs >=1 model for startup validation
           models = _models_for_vendors(tiers, vendors)
       config_path = _create_test_config(temp_dir, tiers, models=models)
       keys_path = _create_test_keys_plain(temp_dir, vendors)

       mock_servers = {}
       for vendor_name, vendor_info in vendors.items():
           from urllib.parse import urlparse
           parsed = urlparse(vendor_info["url"])
           port = parsed.port
           req_list = []
           if streamers and vendor_name in streamers:
               server = _start_streaming_mock_upstream(
                   port, req_list, streamers[vendor_name])
           elif responders and vendor_name in responders:
               server = _start_mode_mock_upstream(
                   port, req_list, responders[vendor_name])
           else:
               server = _start_mock_upstream(port, req_list)
           mock_servers[vendor_name] = {"server": server, "requests": req_list}

       trace_fd, trace_file = tempfile.mkstemp(suffix=".jsonl", dir=temp_dir)
       os.close(trace_fd)

       proc, probe_ok = _start_proxy_server_directly(
           proxy_port, config_path=config_path, keys_path=keys_path,
           passphrase=None, trace_file=trace_file, extra_env=extra_env)
   # new
       temp_dir = tempfile.mkdtemp(prefix="proxy_admin_")
       proxy_port = find_free_port()
       if models is None:
           # Every vendor in keys needs >=1 model for startup validation
           models = _models_for_vendors(tiers, vendors)

       # Bind the mock upstreams BEFORE the config/keys files are written: a
       # mock that lost its preferred port to EADDRINUSE rebinds ephemeral
       # (_bind_mock_server), and the vendor URL written into keys.json must
       # carry the port the mock actually owns, not the number it asked for.
       mock_servers = {}
       for vendor_name, vendor_info in vendors.items():
           from urllib.parse import urlparse
           parsed = urlparse(vendor_info["url"])
           port = parsed.port
           req_list = []
           if streamers and vendor_name in streamers:
               server = _start_streaming_mock_upstream(
                   port, req_list, streamers[vendor_name])
           elif responders and vendor_name in responders:
               server = _start_mode_mock_upstream(
                   port, req_list, responders[vendor_name])
           else:
               server = _start_mock_upstream(port, req_list)
           actual_port = server.server_address[1]
           if actual_port != port:
               vendor_info["url"] = "{}://{}:{}".format(
                   parsed.scheme, parsed.hostname, actual_port)
           mock_servers[vendor_name] = {"server": server, "requests": req_list}

       config_path = _create_test_config(temp_dir, tiers, models=models)
       keys_path = _create_test_keys_plain(temp_dir, vendors)

       trace_fd, trace_file = tempfile.mkstemp(suffix=".jsonl", dir=temp_dir)
       os.close(trace_fd)

       proxy_port, proc, probe_ok = _spawn_proxy_with_bind_retry(
           proxy_port, config_path=config_path, keys_path=keys_path,
           passphrase=None, trace_file=trace_file, extra_env=extra_env)
   ```

   → tester verify (scripted): `timeout 120 python ./tmp/verification/2026-11-12-test-harness-port-hardening-bind.py` — assertions 4, 5 print PASS for `_start_admin_proxy`; `timeout 120 python ./tmp/verification/2026-11-12-test-harness-port-hardening-spawn.py` — assertions 3, 4 print PASS for `_start_admin_proxy` (both scripts' exit stays 1 until Steps 4-6)
   → tester verify: `timeout 600 python tests/test_admin.py` passes in full

4. **Step 4: `_start_mode_proxy` — same reorder and URL patch**

   ```python
   # old
       temp_dir = tempfile.mkdtemp(prefix="proxy_mode_")
       proxy_port = find_free_port()
       config_path = _create_test_config(
           temp_dir, tiers, models=_models_for_vendors(tiers, vendors),
           extra_request_headers=extra_headers,
           reasoning_field_switch=reasoning_field_switch,
           reasoning_roundtrip=reasoning_roundtrip)
       keys_path = _create_test_keys_plain(temp_dir, vendors)

       responders = responders or {}
       mock_servers = {}
       for vendor_name, vendor_info in vendors.items():
           from urllib.parse import urlparse
           port = urlparse(vendor_info["url"]).port
           req_list = []
           if streamers and vendor_name in streamers:
               server = _start_streaming_mock_upstream(
                   port, req_list, streamers[vendor_name])
           else:
               responder = responders.get(vendor_name, _mode_default_responder)
               server = _start_mode_mock_upstream(port, req_list, responder)
           mock_servers[vendor_name] = {"server": server, "requests": req_list}

       trace_fd, trace_file = tempfile.mkstemp(suffix=".jsonl", dir=temp_dir)
       os.close(trace_fd)

       proc, probe_ok = _start_proxy_server_directly(
           proxy_port, config_path=config_path, keys_path=keys_path,
           passphrase=None, trace_file=trace_file, extra_env=extra_env
       )
   # new
       temp_dir = tempfile.mkdtemp(prefix="proxy_mode_")
       proxy_port = find_free_port()

       # Bind the mock upstreams BEFORE the config/keys files are written
       # (same reason as _start_admin_proxy): the vendor URL in keys.json
       # must carry the port the mock actually owns.
       responders = responders or {}
       mock_servers = {}
       for vendor_name, vendor_info in vendors.items():
           from urllib.parse import urlparse
           parsed = urlparse(vendor_info["url"])
           port = parsed.port
           req_list = []
           if streamers and vendor_name in streamers:
               server = _start_streaming_mock_upstream(
                   port, req_list, streamers[vendor_name])
           else:
               responder = responders.get(vendor_name, _mode_default_responder)
               server = _start_mode_mock_upstream(port, req_list, responder)
           actual_port = server.server_address[1]
           if actual_port != port:
               vendor_info["url"] = "{}://{}:{}".format(
                   parsed.scheme, parsed.hostname, actual_port)
           mock_servers[vendor_name] = {"server": server, "requests": req_list}

       config_path = _create_test_config(
           temp_dir, tiers, models=_models_for_vendors(tiers, vendors),
           extra_request_headers=extra_headers,
           reasoning_field_switch=reasoning_field_switch,
           reasoning_roundtrip=reasoning_roundtrip)
       keys_path = _create_test_keys_plain(temp_dir, vendors)

       trace_fd, trace_file = tempfile.mkstemp(suffix=".jsonl", dir=temp_dir)
       os.close(trace_fd)

       proxy_port, proc, probe_ok = _spawn_proxy_with_bind_retry(
           proxy_port, config_path=config_path, keys_path=keys_path,
           passphrase=None, trace_file=trace_file, extra_env=extra_env
       )
   ```

   → tester verify (scripted): bind gate assertions 4, 5 for `_start_mode_proxy`; spawn gate assertions 3, 4 for `_start_mode_proxy`
   → tester verify: `timeout 600 python tests/test_chat_sse.py` and `timeout 600 python tests/test_mode_dispatch.py` pass in full

5. **Step 5: `_setup_tier_routing_test` — migrate the majority path to bind-first, keep skip semantics behind `caller_owns_ports`**

   Only 3 of this helper's 20 call sites (the SSE-rewrite tests in
   `test_tier_routing.py`) pre-bind their own listener; the other 17 rely on
   the helper's bind as their ONLY upstream and keep the write-before-bind
   TOCTOU this plan removes. The flag splits the behaviors.

   Signature + docstring:

   ```python
   # old
   def _setup_tier_routing_test(tiers_config, vendors, default_passphrase="test-passphrase"):
       """Set up a standard tier routing test environment.

       Creates temp directory with config.json and keys-index.json, starts mock
       upstream servers for each vendor, and starts the proxy server.

       Args:
           tiers_config: Dict mapping tier -> {provider, model}
           vendors: Dict mapping vendor -> {url, key}
           default_passphrase: Passphrase for keys decryption

       Returns:
           (temp_dir, proxy_port, proxy_proc, mock_servers, cleanup_fn)
       """
   # new
   def _setup_tier_routing_test(tiers_config, vendors, default_passphrase="test-passphrase",
                                caller_owns_ports=False):
       """Set up a standard tier routing test environment.

       Creates temp directory with config.json and keys-index.json, starts mock
       upstream servers for each vendor, and starts the proxy server.

       Args:
           tiers_config: Dict mapping tier -> {provider, model}
           vendors: Dict mapping vendor -> {url, key}
           default_passphrase: Passphrase for keys decryption
           caller_owns_ports: True when the caller pre-binds its own listener
               on each vendor URL's port (the SSE-rewrite family); that
               listener IS the upstream, so this helper's own bind is skipped
               on EADDRINUSE instead of rebound. False (default): this
               helper's bind is the vendor's only upstream — bind
               preferred-first with an ephemeral fallback and repoint the
               vendor URL at the port actually owned.

       Returns:
           (temp_dir, proxy_port, proxy_proc, mock_servers, cleanup_fn)
       """
   ```

   Body reorder + bind-loop branch — one edit replacing the region from
   `temp_dir = tempfile.mkdtemp(prefix="proxy_tier_test_")` through
   `mock_servers[vendor_name] = {"server": server, "requests": requests_received}`
   (the `make_handler` factory in the middle is verbatim-unchanged; it is
   reproduced here only because it sits inside the replaced region):

   ```python
   # old
       temp_dir = tempfile.mkdtemp(prefix="proxy_tier_test_")
       proxy_port = find_free_port()

       # Create config — every vendor in keys needs >=1 model for startup validation
       config_path = _create_test_config(
           temp_dir, tiers_config, models=_models_for_vendors(tiers_config, vendors)
       )

       # Create keys (plain or encrypted depending on passphrase)
       if default_passphrase is None:
           keys_path = _create_test_keys_plain(temp_dir, vendors)
       else:
           keys_path = _create_test_keys(temp_dir, vendors, default_passphrase)

       # Start mock upstreams
       mock_servers = {}
       for vendor_name, vendor_info in vendors.items():
           # Parse port from URL
           from urllib.parse import urlparse
           parsed = urlparse(vendor_info["url"])
           port = parsed.port

           # Create mock handler that records requests
           # Use a factory function to properly capture requests_received per iteration
           requests_received = []

           def make_handler(req_list):
               class MockHandler(http.server.BaseHTTPRequestHandler):
                   def do_POST(self):
                       content_len = int(self.headers.get("Content-Length", 0))
                       body = self.rfile.read(content_len) if content_len > 0 else b"{}"
                       api_key = self.headers.get("x-api-key", "")
                       req_list.append({"body": body, "api_key": api_key,
                                        "headers": _record_request_headers(self.headers)})
                       self.send_response(200)
                       self.send_header("Content-Type", "application/json")
                       self.end_headers()
                       try:
                           req_data = json.loads(body)
                           model = req_data.get("model", "unknown")
                       except:
                           model = "unknown"
                       self.wfile.write(json.dumps({
                           "id": "ok",
                           "type": "message",
                           "model": model,
                           "content": [{"text": "response"}]
                       }).encode())

                   def log_message(self, format, *args):
                       pass
               return MockHandler

           MockHandler = make_handler(requests_received)
           try:
               server = http.server.ThreadingHTTPServer(("127.0.0.1", port), MockHandler)
           except OSError as e:
               # A caller may pre-bind its own listener on the vendor URL's port
               # before calling this helper (the SSE-rewrite tests bind their SSE
               # mock first). Linux rejects a second bind with EADDRINUSE; skip
               # ours and leave `server` None so teardown skips it — the caller's
               # listener serves the upstream traffic instead.
               if e.errno != errno.EADDRINUSE:
                   raise
               server = None
           if server is not None:
               thread = threading.Thread(target=server.serve_forever, daemon=True)
               thread.start()
               time.sleep(0.1)
           mock_servers[vendor_name] = {"server": server, "requests": requests_received}
   # new
       temp_dir = tempfile.mkdtemp(prefix="proxy_tier_test_")
       proxy_port = find_free_port()

       # Start mock upstreams FIRST (same reason as _start_admin_proxy): when
       # caller_owns_ports is False, a mock that lost its preferred port to
       # EADDRINUSE rebinds ephemeral (_bind_mock_server) and the vendor URL
       # written into keys below carries the bound port.
       mock_servers = {}
       for vendor_name, vendor_info in vendors.items():
           # Parse port from URL
           from urllib.parse import urlparse
           parsed = urlparse(vendor_info["url"])
           port = parsed.port

           # Create mock handler that records requests
           # Use a factory function to properly capture requests_received per iteration
           requests_received = []

           def make_handler(req_list):
               class MockHandler(http.server.BaseHTTPRequestHandler):
                   def do_POST(self):
                       content_len = int(self.headers.get("Content-Length", 0))
                       body = self.rfile.read(content_len) if content_len > 0 else b"{}"
                       api_key = self.headers.get("x-api-key", "")
                       req_list.append({"body": body, "api_key": api_key,
                                        "headers": _record_request_headers(self.headers)})
                       self.send_response(200)
                       self.send_header("Content-Type", "application/json")
                       self.end_headers()
                       try:
                           req_data = json.loads(body)
                           model = req_data.get("model", "unknown")
                       except:
                           model = "unknown"
                       self.wfile.write(json.dumps({
                           "id": "ok",
                           "type": "message",
                           "model": model,
                           "content": [{"text": "response"}]
                       }).encode())

                   def log_message(self, format, *args):
                       pass
               return MockHandler

           MockHandler = make_handler(requests_received)
           if caller_owns_ports:
               # The pre-binding family: the caller's own listener on this
               # port IS the upstream; this helper's bind is the redundant
               # one, so on EADDRINUSE skip it and leave `server` None so
               # teardown skips it.
               try:
                   server = http.server.ThreadingHTTPServer(("127.0.0.1", port), MockHandler)
               except OSError as e:
                   if e.errno != errno.EADDRINUSE:
                       raise
                   server = None
           else:
               # The majority: this bind is the vendor's ONLY upstream. Bind
               # preferred-first with an ephemeral fallback and let the URL
               # carry the port actually owned.
               server = _bind_mock_server(MockHandler, port)
               actual_port = server.server_address[1]
               if actual_port != port:
                   vendor_info["url"] = "{}://{}:{}".format(
                       parsed.scheme, parsed.hostname, actual_port)
           if server is not None:
               thread = threading.Thread(target=server.serve_forever, daemon=True)
               thread.start()
               time.sleep(0.1)
           mock_servers[vendor_name] = {"server": server, "requests": requests_received}

       # Create config — every vendor in keys needs >=1 model for startup validation
       config_path = _create_test_config(
           temp_dir, tiers_config, models=_models_for_vendors(tiers_config, vendors)
       )

       # Create keys (plain or encrypted depending on passphrase)
       if default_passphrase is None:
           keys_path = _create_test_keys_plain(temp_dir, vendors)
       else:
           keys_path = _create_test_keys(temp_dir, vendors, default_passphrase)
   ```

   Then the three SSE pre-bind call sites in `tests/test_tier_routing.py`
   (identifiable as exactly the three call sites followed by
   `if proc is None:` / `mock_server.shutdown()` — the majority sites follow
   the call with a `fail(...)` instead). Replace all three occurrences of:

   ```python
   # old
       temp_dir, proxy_port, proc, mock_servers, cleanup = _setup_tier_routing_test(tiers, vendors)
       if proc is None:
           mock_server.shutdown()
   # new
       temp_dir, proxy_port, proc, mock_servers, cleanup = _setup_tier_routing_test(
           tiers, vendors, caller_owns_ports=True)
       if proc is None:
           mock_server.shutdown()
   ```

   → tester verify (scripted): bind gate assertions 8, 9 print PASS; spawn gate assertions 3, 4 print PASS for `_setup_tier_routing_test`
   → tester verify: `timeout 600 python tests/test_tier_routing.py` and `timeout 600 python tests/test_config_keys.py` pass in full

6. **Step 6: Correct the six direct starter call sites — bind first, derive the port from the server; close their teardown listeners**

   All six follow one recipe: the mock binds (crash-safe since Step 1), then
   the port actually owned (`server.server_address[1]`) feeds the URL *before*
   it is written into keys; and each function's own teardown `shutdown()` call
   gains `server_close()` (the amplifier fix for listeners this plan touches).

   `tests/test_admin.py`, `test_admin_api_reload` (anchor: `proxy_admin_reload_` temp prefix, `p_port = find_free_port()` above `tiers_a`):

   ```python
   # old
       proxy_port = find_free_port()
       config_path = _create_test_config(temp_dir, tiers_a)
       keys_path = _create_test_keys_plain(temp_dir, vendors)

       req_list = []
       mock_servers = {"p": {
           "server": _start_mock_upstream(p_port, req_list),
           "requests": req_list,
       }}
   # new
       proxy_port = find_free_port()
       config_path = _create_test_config(temp_dir, tiers_a)

       req_list = []
       p_server = _start_mock_upstream(p_port, req_list)
       # The mock owns the port it actually bound (an EADDRINUSE fallback
       # rebinds ephemeral) — the URL must carry that port, so bind first.
       p_port = p_server.server_address[1]
       vendors["p"]["url"] = "http://127.0.0.1:{}".format(p_port)
       keys_path = _create_test_keys_plain(temp_dir, vendors)
       mock_servers = {"p": {
           "server": p_server,
           "requests": req_list,
       }}
   ```

   Same test's teardown:

   ```python
   # old
           mock_servers["p"]["server"].shutdown()
           shutil.rmtree(temp_dir, ignore_errors=True)
   # new
           mock_servers["p"]["server"].shutdown()
           mock_servers["p"]["server"].server_close()
           shutil.rmtree(temp_dir, ignore_errors=True)
   ```

   `tests/test_admin.py`, `test_admin_switch_validates_key_names` (anchor: `proxy_admin_reload_key_` prefix, `port = find_free_port()` above the `tiers` with `"key": "SW"`):

   ```python
   # old
       proxy_port = find_free_port()
       config_path = _create_test_config(temp_dir, tiers, models=_derive_models_from_tiers(tiers))
       keys_path = _create_test_keys_plain(temp_dir, vendors)

       req_list = []
       mock_servers = {"mkp": {"server": _start_mock_upstream(port, req_list), "requests": req_list}}
   # new
       proxy_port = find_free_port()
       config_path = _create_test_config(temp_dir, tiers, models=_derive_models_from_tiers(tiers))

       req_list = []
       mkp_server = _start_mock_upstream(port, req_list)
       # Same as the reload test above: the URL follows the bound port.
       port = mkp_server.server_address[1]
       vendors["mkp"]["url"] = "http://127.0.0.1:{}".format(port)
       keys_path = _create_test_keys_plain(temp_dir, vendors)
       mock_servers = {"mkp": {"server": mkp_server, "requests": req_list}}
   ```

   Its teardown:

   ```python
   # old
           mock_servers["mkp"]["server"].shutdown()
           shutil.rmtree(temp_dir, ignore_errors=True)
   # new
           mock_servers["mkp"]["server"].shutdown()
           mock_servers["mkp"]["server"].server_close()
           shutil.rmtree(temp_dir, ignore_errors=True)
   ```

   `tests/test_cli.py`, `test_cli_reload` (anchor: `proxy_cli_reload_` temp prefix; `p_port = find_free_port()` then `config_path = _create_test_config(temp_dir, tiers_a)`):

   ```python
   # old
               config_path = _create_test_config(temp_dir, tiers_a)
               keys_path = _create_test_keys_plain(temp_dir, {
                   "p": {"url": f"http://127.0.0.1:{p_port}", "key": "k"}
               })
               trace_fd, trace_file = tempfile.mkstemp(suffix=".jsonl", dir=temp_dir)
               os.close(trace_fd)

               req_list = []
               mock_server = _start_mock_upstream(p_port, req_list)
               mock_started = True
   # new
               config_path = _create_test_config(temp_dir, tiers_a)

               req_list = []
               mock_server = _start_mock_upstream(p_port, req_list)
               # The mock owns the port it actually bound; the URL follows it.
               p_port = mock_server.server_address[1]
               keys_path = _create_test_keys_plain(temp_dir, {
                   "p": {"url": f"http://127.0.0.1:{p_port}", "key": "k"}
               })
               trace_fd, trace_file = tempfile.mkstemp(suffix=".jsonl", dir=temp_dir)
               os.close(trace_fd)

               mock_started = True
   ```

   Its teardown:

   ```python
   # old
               if 'mock_started' in dir():
                   mock_server.shutdown()
               shutil.rmtree(temp_dir, ignore_errors=True)
   # new
               if 'mock_started' in dir():
                   mock_server.shutdown()
                   mock_server.server_close()
               shutil.rmtree(temp_dir, ignore_errors=True)
   ```

   `tests/test_cli.py`, `test_cli_status_shows_tiers` (anchor: the `_create_test_keys_plain(temp_dir, {` call whose inline dict is `"p": {"url": f"http://127.0.0.1:{p_port}", "key": "k"}` and whose bind line follows `os.close(trace_fd)` — the one WITHOUT `mock_started`):

   ```python
   # old
               keys_path = _create_test_keys_plain(temp_dir, {
                   "p": {"url": f"http://127.0.0.1:{p_port}", "key": "k"}
               })
               trace_fd, trace_file = tempfile.mkstemp(suffix=".jsonl", dir=temp_dir)
               os.close(trace_fd)

               mock_server = _start_mock_upstream(p_port, [])
   # new
               mock_server = _start_mock_upstream(p_port, [])
               # The mock owns the port it actually bound; the URL follows it.
               p_port = mock_server.server_address[1]
               keys_path = _create_test_keys_plain(temp_dir, {
                   "p": {"url": f"http://127.0.0.1:{p_port}", "key": "k"}
               })
               trace_fd, trace_file = tempfile.mkstemp(suffix=".jsonl", dir=temp_dir)
               os.close(trace_fd)
   ```

   Its teardown (anchor: the `mock_server.shutdown()` that follows a
   `stop_result.returncode != 0` check with an f-string `fail`):

   ```python
   # old
               mock_server.shutdown()

           finally:
               shutil.rmtree(temp_dir, ignore_errors=True)
   # new
               mock_server.shutdown()
               mock_server.server_close()

           finally:
               shutil.rmtree(temp_dir, ignore_errors=True)
   ```

   `tests/test_cli.py`, `test_start_status_reload_tier_lines_show_key` (anchor: the inline dict with `"keys": {"SW": "p1", "CZ": "p2"}`):

   ```python
   # old
               keys_path = _create_test_keys_plain(temp_dir, {
                   "p": {"url": "http://127.0.0.1:{}".format(p_port), "keys": {"SW": "p1", "CZ": "p2"}}
               })
               trace_fd, trace_file = tempfile.mkstemp(suffix=".jsonl", dir=temp_dir)
               os.close(trace_fd)

               mock_server = _start_mock_upstream(p_port, [])
   # new
               mock_server = _start_mock_upstream(p_port, [])
               # The mock owns the port it actually bound; the URL follows it.
               p_port = mock_server.server_address[1]
               keys_path = _create_test_keys_plain(temp_dir, {
                   "p": {"url": "http://127.0.0.1:{}".format(p_port), "keys": {"SW": "p1", "CZ": "p2"}}
               })
               trace_fd, trace_file = tempfile.mkstemp(suffix=".jsonl", dir=temp_dir)
               os.close(trace_fd)
   ```

   Its teardown (anchor: the `mock_server.shutdown()` that follows the
   `.format`-style `fail` after `stop_result`):

   ```python
   # old
               mock_server.shutdown()
       finally:
           shutil.rmtree(temp_dir, ignore_errors=True)
   # new
               mock_server.shutdown()
               mock_server.server_close()
       finally:
           shutil.rmtree(temp_dir, ignore_errors=True)
   ```

   `tests/test_retry_streaming.py`, `test_retry_path_print_failure_does_not_misclassify` (anchor: `mock_server = _start_mode_mock_upstream(upstream_port, reqs, _responder_503)` — bind already precedes the URL, so one line suffices):

   ```python
   # old
       mock_server = _start_mode_mock_upstream(upstream_port, reqs, _responder_503)
   # new
       mock_server = _start_mode_mock_upstream(upstream_port, reqs, _responder_503)
       # The mock owns the port it actually bound; the URL below follows it.
       upstream_port = mock_server.server_address[1]
   ```

   Its teardown (try/except-wrapped):

   ```python
   # old
           try:
               mock_server.shutdown()
           except Exception:
               pass
           shutil.rmtree(root, ignore_errors=True)
   # new
           try:
               mock_server.shutdown()
               mock_server.server_close()
           except Exception:
               pass
           shutil.rmtree(root, ignore_errors=True)
   ```

   → tester verify (scripted): `timeout 120 python ./tmp/verification/2026-11-12-test-harness-port-hardening-bind.py` — **exit 0, all assertions PASS** (this step completes the bind group)
   → tester verify: `timeout 600 python tests/test_admin.py`, `timeout 600 python tests/test_cli.py`, `timeout 600 python tests/test_retry_streaming.py` pass in full

7. **Step 7: Close mock listening sockets at every harness teardown site; preserve setup-failure evidence (incl. child stderr)**

   Three early-failure branches (`if not probe_ok:` in `_setup_tier_routing_test`,
   `_start_admin_proxy`, `_start_mode_proxy`) AND the three `cleanup()` closures'
   shutdown loops gain `server_close()`; the early branches replace the silent
   `rmtree` with an evidence-preserving note that also dumps the child's
   buffered stderr. Tier-routing early branch (its loop carries the
   `is not None` guard; `child_stderr` is already in scope):

   ```python
   # old (tier routing early branch)
           for ms in mock_servers.values():
               if ms["server"] is not None:
                   ms["server"].shutdown()
           proc.kill()
           shutil.rmtree(temp_dir, ignore_errors=True)
           return None, None, None, None, None
   # new (tier routing early branch)
           for ms in mock_servers.values():
               if ms["server"] is not None:
                   ms["server"].shutdown()
                   ms["server"].server_close()
           proc.kill()
           # A failed spawn IS the failure: keep its evidence for triage —
           # the trace AND the child's stderr, which is buffered in memory
           # and lost once the proc is collected.
           stderr_path = os.path.join(temp_dir, "proxy-stderr.log")
           try:
               with open(stderr_path, "w", encoding="utf-8") as f:
                   f.write(child_stderr or "")
           except Exception:
               pass
           print("  NOTE: setup failed — artifacts preserved at {} (trace: {}; stderr: {})".format(
               temp_dir, trace_file, stderr_path))
           return None, None, None, None, None
   ```

   The admin and mode early branches have the unguarded loop
   (`for ms in mock_servers.values(): ms["server"].shutdown()`) and the same
   `child_stderr` variable; apply the same server_close pair and the same
   NOTE/stderr-dump/rmtree replacement. The mode branch returns six `None`s —
   preserve its arity.

   The three `cleanup()` closures' shutdown loops (tier routing: guarded;
   admin/mode: unguarded) — e.g. tier routing:

   ```python
   # old (tier routing cleanup loop)
           for ms in mock_servers.values():
               if ms["server"] is not None:
                   ms["server"].shutdown()
   # new (tier routing cleanup loop)
           for ms in mock_servers.values():
               if ms["server"] is not None:
                   ms["server"].shutdown()
                   ms["server"].server_close()
   ```

   and admin/mode:

   ```python
   # old (admin/mode cleanup loop)
           for ms in mock_servers.values():
               ms["server"].shutdown()
   # new (admin/mode cleanup loop)
           for ms in mock_servers.values():
               ms["server"].shutdown()
               ms["server"].server_close()
   ```

   → tester verify (scripted): `timeout 120 python ./tmp/verification/2026-11-12-test-harness-port-hardening-cleanup.py` — assertions 4, 5, 6 must print PASS (assertion 5's full count completes with Step 8; exit stays 1 until then)
   → tester verify: `harness-cleanup-preserves-artifacts-on-failure` (Step 10) passes

8. **Step 8: Failure-aware `cleanup()` — `_TEST_FAILED` flag, preserve on flag OR in-flight exception, dump stderr**

   Module level, next to the `errors` list definition:

   ```python
   # old
   errors = []
   # new
   errors = []
   # Set by fail() and read by the builders' cleanup() closures: a failed
   # test's temp_dir (trace file + child stderr + artifacts) is the only
   # record of what the proxy actually did, so it is preserved instead of
   # deleted.
   _TEST_FAILED = False
   ```

   `fail()` (keep `warn`/`pass_` untouched — a warning is not a failure):

   ```python
   # old
   def fail(msg):
       errors.append(msg)
       print(f"  FAIL: {msg}")
   # new
   def fail(msg):
       global _TEST_FAILED
       _TEST_FAILED = True
       errors.append(msg)
       print(f"  FAIL: {msg}")
   ```

   `run_cli`'s per-test reset (inside the `for name in selected:` loop):

   ```python
   # old
           # Clear per-test errors
           global errors
           errors = []
   # new
           # Clear per-test errors
           global errors
           errors = []
           global _TEST_FAILED
           _TEST_FAILED = False
   ```

   In each of the three `cleanup()` closures, replace the unconditional
   `rmtree` (the `# Shared removal...` comment line and everything after it in
   each cleanup stay unchanged — the replacement stops at that anchor):

   ```python
   # old
           shutil.rmtree(temp_dir, ignore_errors=True)
           # Shared removal for the per-run state file — see
   # new
           if _TEST_FAILED or sys.exc_info()[0] is not None:
               # The failure's evidence (trace, child stderr, artifacts) is
               # the only record of what the proxy actually did — keep it for
               # triage. sys.exc_info covers crash-shaped failures: an
               # uncaught exception unwinds through this finally BEFORE
               # run_cli records anything, so the flag alone would miss
               # exactly the hardest failures to diagnose.
               stderr_path = os.path.join(temp_dir, "proxy-stderr.log")
               try:
                   with open(stderr_path, "w", encoding="utf-8") as f:
                       f.write(_read_child_stderr(proc) or "")
               except Exception:
                   pass
               print("  NOTE: test failed — artifacts preserved at {} (trace: {}; stderr: {})".format(
                   temp_dir, trace_file, stderr_path))
           else:
               shutil.rmtree(temp_dir, ignore_errors=True)
           # Shared removal for the per-run state file — see
   ```

   → tester verify (scripted): `timeout 120 python ./tmp/verification/2026-11-12-test-harness-port-hardening-cleanup.py` — **exit 0, all assertions PASS** (this step completes the cleanup group)
   → tester verify: `harness-cleanup-preserves-artifacts-on-failure` (Step 10) passes; the Step 10 full-suite run leaves no `proxy_admin_*`/`proxy_mode_*`/`proxy_tier_test_*` dirs behind on passing tests

9. **Step 9: Self-classifying failure message in the chat-sse transition test**

   In `tests/test_chat_sse.py`, `test_chat_sse_reasoning_then_text_transition`:

   ```python
   # old
           if len(starts) != 2 or len(stops) != 2:
               fail("expected 2 starts and 2 stops, got starts={!r} stops={!r}".format(starts, stops))
               return
   # new
           if len(starts) != 2 or len(stops) != 2:
               # Self-classifying failure (deferred issue
               # flaky-chat-sse-transition-empty-stream): the frame types and
               # raw head distinguish an SSE error frame (proxy cut the
               # stream) from raw chat-completion chunks (Content-Type
               # misdetected, untransformed passthrough) without a rerun —
               # and with Step 8's preservation the trace and stderr survive
               # for the same triage.
               fail("expected 2 starts and 2 stops, got starts={!r} stops={!r}; "
                    "frame types={!r}; raw head={!r}".format(
                        starts, stops,
                        [t for t, _ in frames[:8]], raw[:200]))
               return
   ```

   (`_parse_sse_frames` returns `(event_type_or_None, data)` tuples, so
   `[t for t, _ in frames[:8]]` lists the event names; `raw` is the response
   bytes already in scope.)

   → tester verify (scripted): `timeout 120 python ./tmp/verification/2026-11-12-test-harness-port-hardening-chat-sse-message.py` — **exit 0**
   → tester verify: `timeout 300 python tests/test_chat_sse.py -t chat-sse-reasoning-then-text-transition` passes

10. **Step 10: New permanent tests — `tests/test_harness_hardening.py` + aggregator registration**

    Create `tests/test_harness_hardening.py` with exactly this content:

    ```python
    """Harness-behavior tests: port-ownership fallback, proxy-port bind
    retry, failure artifact preservation (plan
    2026-11-12-test-harness-port-hardening)."""
    import http.server
    import json
    import os
    import shutil
    import tempfile
    import threading

    import _harness
    from _harness import (
        _MockHTTPServer,
        _create_test_config,
        _create_test_keys_plain,
        _send_proxy_request,
        _spawn_proxy_with_bind_retry,
        _start_mode_proxy,
        fail,
        find_free_port,
        pass_,
        run_cli,
    )

    # Startup validation requires all three tiers (config.py), so every
    # fixture uses the same three-tier shape the admin tests use.
    _TIERS = {
        "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
        "opus": {"provider": "p", "model": "claude-opus-5"},
    }


    def _hold_a_port():
        """Occupy a TCP port with a silent listener; returns (server, port)."""
        class Silent(http.server.BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass
        server = _MockHTTPServer(("127.0.0.1", 0), Silent)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        return server, server.server_address[1]


    def test_bind_fallback_rebinds_and_url_follows():
        """A vendor port held by a foreign listener: the mock rebinds
        ephemeral, the vendor URL follows the bound port, and the request
        path still works end to end."""
        print("\n--- Test: Harness Bind Fallback Rebinds, URL Follows ---")
        holder, held_port = _hold_a_port()
        vendors = {"p": {"url": "http://127.0.0.1:{}".format(held_port),
                         "key": "k"}}
        before_url = vendors["p"]["url"]
        td, proxy_port, proc, mock_servers, trace_file, cleanup = \
            _start_mode_proxy(_TIERS, vendors)
        if proc is None:
            fail("setup failed entirely (probe never succeeded)")
            holder.shutdown()
            holder.server_close()
            return
        try:
            after_url = vendors["p"]["url"]
            if after_url == before_url:
                fail("vendor URL was not repointed off the held port: "
                     "{!r}".format(after_url))
                return
            bound_port = mock_servers["p"]["server"].server_address[1]
            if str(bound_port) not in after_url:
                fail("URL {!r} does not carry the bound port {}".format(
                    after_url, bound_port))
                return
            body = json.dumps({"model": "sonnet",
                               "messages": [{"role": "user", "content": "hi"}]})
            status, resp = _send_proxy_request(proxy_port, body=body)
            if status != 200:
                fail("end-to-end request failed: {} {!r}".format(status, resp[:200]))
                return
            pass_("mock rebound off the held port, URL followed, request OK")
        finally:
            cleanup()
            holder.shutdown()
            holder.server_close()


    def test_proxy_port_busy_retries_once():
        """A proxy spawn onto a held port: the connect-only probe success is
        rejected by marker-vs-liveness discrimination, the dead child's
        stderr names the busy port, and one retry on a fresh port comes up
        ready."""
        print("\n--- Test: Harness Proxy Port Busy Retries Once ---")
        holder, held_port = _hold_a_port()
        temp_dir = tempfile.mkdtemp(prefix="harness_hard_")
        trace_fd, trace_file = tempfile.mkstemp(suffix=".jsonl", dir=temp_dir)
        os.close(trace_fd)
        port = held_port
        proc = None
        try:
            config_path = _create_test_config(temp_dir, _TIERS)
            keys_path = _create_test_keys_plain(
                temp_dir, {"p": {"url": "http://127.0.0.1:1", "key": "k"}})
            port, proc, probe_ok = _spawn_proxy_with_bind_retry(
                held_port, config_path=config_path, keys_path=keys_path,
                passphrase=None, trace_file=trace_file)
            if not probe_ok:
                fail("retry did not bring the proxy up on a fresh port")
                return
            if port == held_port:
                fail("returned port {} is the held port".format(port))
                return
            if proc.poll() is not None:
                fail("returned proc is not alive")
                return
            pass_("proxy respawned on fresh port {} after bind collision".format(port))
        finally:
            if proc is not None and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except Exception:
                    proc.kill()
            holder.shutdown()
            holder.server_close()
            shutil.rmtree(temp_dir, ignore_errors=True)


    def test_cleanup_preserves_artifacts_on_failure():
        """With the failure flag set, cleanup() keeps temp_dir, the trace
        file, and a stderr dump, and prints their paths. (The removal branch
        is pinned by the Step 10 suite-level no-residue check, not here.)"""
        print("\n--- Test: Harness Cleanup Preserves Artifacts on Failure ---")
        vendors = {"p": {"url": "http://127.0.0.1:{}".format(find_free_port()),
                         "key": "k"}}
        td, proxy_port, proc, mock_servers, trace_file, cleanup = \
            _start_mode_proxy(_TIERS, vendors)
        if proc is None:
            fail("setup failed")
            return
        _harness._TEST_FAILED = True
        cleanup()
        try:
            if not os.path.isdir(td):
                fail("cleanup() deleted temp_dir despite the failure flag")
                return
            if not os.path.exists(trace_file):
                fail("cleanup() deleted the trace file despite the failure flag")
                return
            if not os.path.exists(os.path.join(td, "proxy-stderr.log")):
                fail("cleanup() wrote no proxy-stderr.log despite the failure flag")
                return
            pass_("failure flag preserves temp_dir, trace file, stderr dump")
        finally:
            _harness._TEST_FAILED = False
            shutil.rmtree(td, ignore_errors=True)


    ALL_TESTS = [
        ("harness-bind-fallback-rebinds-and-url-follows",
         test_bind_fallback_rebinds_and_url_follows),
        ("harness-proxy-port-busy-retries-once",
         test_proxy_port_busy_retries_once),
        ("harness-cleanup-preserves-artifacts-on-failure",
         test_cleanup_preserves_artifacts_on_failure),
    ]


    if __name__ == "__main__":
        run_cli(ALL_TESTS, "claude-retry-proxy tests: test_harness_hardening")
    ```

    Register in `tests/test_claude_proxy.py`:

    ```python
    # old (import block, after the parse_guards import)
    from test_parse_guards import ALL_TESTS as PARSE_GUARDS_TESTS
    # new
    from test_parse_guards import ALL_TESTS as PARSE_GUARDS_TESTS
    from test_harness_hardening import ALL_TESTS as HARNESS_HARDENING_TESTS
    ```

    ```python
    # old (aggregation, tail of ALL_TESTS = (...))
        DOCS_TESTS +
        PARSE_GUARDS_TESTS
    )
    # new
        DOCS_TESTS +
        PARSE_GUARDS_TESTS +
        HARNESS_HARDENING_TESTS
    )
    ```

    Registration proof and final gates, in order (per
    `doc/test-catalog.html` "Adding a test"):

    ```bash
    timeout 60 python tests/test_claude_proxy.py --list   # must print the three harness-* slugs
    timeout 300 python tests/test_claude_proxy.py -t harness-bind-fallback-rebinds-and-url-follows   # must print ">> harness-bind-fallback-rebinds-and-url-follows: PASSED"
    timeout 300 python tests/test_harness_hardening.py    # all three PASS, 0 failed
    timeout 120 python ./tmp/verification/2026-11-12-test-harness-port-hardening-bind.py            # exit 0
    timeout 120 python ./tmp/verification/2026-11-12-test-harness-port-hardening-spawn.py           # exit 0
    timeout 120 python ./tmp/verification/2026-11-12-test-harness-port-hardening-cleanup.py         # exit 0
    timeout 120 python ./tmp/verification/2026-11-12-test-harness-port-hardening-chat-sse-message.py  # exit 0
    timeout 900 python tests/test_claude_proxy.py         # full suite green: 0 failed, three harness-* PASSED lines (with a live proxy running, per the suite's documented safe-alongside property)
    ```

    → tester verify (scripted): all four gates exit 0
    → tester verify: the command block above, all green — the `--list` and targeted `-t` runs are the registration proof (a green module run alone is exactly what an unregistered module produces)

11. **Step 11: `_bind_mock_server` also matches the Windows bind-collision errno (review R1, user-approved 2026-11-13)**

   In `tests/_harness.py`, `_bind_mock_server`:

   ```python
   # old
       try:
           server = _MockHTTPServer(("127.0.0.1", preferred_port), handler_cls)
       except OSError as e:
           if e.errno != errno.EADDRINUSE:
               raise
           server = _MockHTTPServer(("127.0.0.1", 0), handler_cls)
       return server
   # new
       try:
           server = _MockHTTPServer(("127.0.0.1", preferred_port), handler_cls)
       except OSError as e:
           # On Windows a bind collision surfaces as winerror 10048
           # (WSAEADDRINUSE), which CPython does not map to EADDRINUSE —
           # match it explicitly so the fallback works there too (review R1).
           if (e.errno != errno.EADDRINUSE
                   and getattr(e, "winerror", None) != 10048):
               raise
           server = _MockHTTPServer(("127.0.0.1", 0), handler_cls)
       return server
   ```

   (`_spawn_proxy_with_bind_retry` already matches the `10048` stderr form; the
   `caller_owns_ports` branch keeps its POSIX skip semantics unchanged — its
   plain-`ThreadingHTTPServer` dual-bind behavior on Windows predates this plan.)

   → tester verify (scripted): `timeout 120 python ./tmp/verification/2026-11-12-test-harness-port-hardening-bind.py` — **exit 0**, including assertion 11 (winerror match)
   → tester verify: `timeout 300 python tests/test_harness_hardening.py` — 3/3; `timeout 900 python tests/test_claude_proxy.py` — full suite green, 0 failed

## Guidance for Planner

Documentation tasks you will execute yourself (not the coder):

- **Files to modify:**
  - `./doc/test-catalog.html`
- **`.claude/mega-audit-files.json`:** not touched by this plan (the file is absent; no declared audit locations change).
- **When:** after tester finishes.
- **What to sync:**
  - The harness helper table ("Proxy lifecycle" rows, ~lines 853-861): the `find_free_port()` row currently says "Pick an unused port — always prefer this over a hard-coded one"; add that the returned port is unowned until bound and mocks bind through `_bind_mock_server`'s preferred-first/ephemeral-fallback, so a URL carrying a port must be built after the bind from `server.server_address[1]`. Add rows for `_bind_mock_server`, `_MockHTTPServer`, and `_spawn_proxy_with_bind_retry` (including the marker-vs-connect discrimination and the busy-port stderr signature) in the same table.
  - The anti-pattern table row "Hard-code a port" (~line 938) stays; no contradiction.
  - "The catalog" module table (~lines 113-167): add a `<tr>` row for `test_harness_hardening.py` (covers: mock-bind preferred-first/ephemeral fallback, proxy-port bind-retry respawn, failure-artifact preservation).
  - The isolation/harness prose: teardown closes mock listening sockets (`shutdown()` + `server_close()`) at the harness teardown sites and the six direct sites (other test-local listeners are an accepted residual — say so); a failed test's `temp_dir` + trace + `proxy-stderr.log` are preserved (paths printed) instead of deleted; `_setup_tier_routing_test` gains `caller_owns_ports` and its majority path binds before writing keys.
  - The per-test index: add the three `harness-*` tests under the new module's entry. **Extend the inventory's provenance comment** (`<!-- BEGIN per-test inventory (generated ...) -->`, ~line 169) with the sync date, and **bump both "Last updated" stamps** (head ~line 13 and footer ~line 973) to the sync date.
  - No exact counts anywhere (repo rule): describe test totals behaviorally; date-stamp any snapshot figure.
- Doc-sync is a sweep: `git grep` the changed identifiers (`find_free_port`, `_bind_mock_server`, `_MockHTTPServer`, `_spawn_proxy_with_bind_retry`, `caller_owns_ports`, `server_close`, `artifacts preserved`, `proxy-stderr.log`) across `doc/`, `CLAUDE.md`, `README.md`, docstrings, and archived `plans/` and reconcile every hit against the new behavior. `CLAUDE.md`'s test-isolation gotcha mentions neither port allocation nor cleanup behavior — no change expected there, but verify with the grep.

## History

One row per event (spec revision / mega-audit / review / implementation round). Conclusion = one-sentence outcome or what changed. Dismissed = compact dismissed-findings list for the reviewer — verbatim issue slugs linked as `[<slug>](<report-path>)`, no prose-only entries. Link to report files; never restate findings inline.

| Date | Event | Conclusion | Dismissed |
|------|-------|------------|-----------|
| 2026-11-12 | Initial plan | Adopts two deferrals (`admin-straggler-eaddrinuse`, `flaky-chat-sse-transition-empty-stream`); closes the harness port TOCTOU by bind-first/URL-follows + proxy-port retry + socket-close hygiene + failure artifact preservation. Baseline: full suite 500 passed / 0 failed on 2026-11-12. | — |
| 2026-11-12 | Mega-audit (pre-implementation) | [Report](./tmp/reports/2026-11-12-test-harness-port-hardening-mega-audit-2026-11-12.json): 41 findings (10 High / 15 Medium / 16 Low). All High+Medium fixed in the 2026-11-13 revision — the retry wrapper redesigned around marker-seen discrimination + the server's actual busy-port message (both empirically verified by the audit), `server_close()` extended to the success-path cleanups and the six direct-site teardowns, Step-10 fixtures corrected to three-tier validation, `_setup_tier_routing_test` migrated behind `caller_owns_ports` (user-approved Option A), gates rebuilt and re-proven RED. 0 High remain. | [title-overstates-coverage](./tmp/reports/2026-11-12-test-harness-port-hardening-mega-audit-2026-11-12.json), [portless-url-none-port](./tmp/reports/2026-11-12-test-harness-port-hardening-mega-audit-2026-11-12.json), [preserved-dirs-unbounded-no-retention-note](./tmp/reports/2026-11-12-test-harness-port-hardening-mega-audit-2026-11-12.json), [reorder-mock-thread-leak-on-write-raise](./tmp/reports/2026-11-12-test-harness-port-hardening-mega-audit-2026-11-12.json), [no-rollback-section](./tmp/reports/2026-11-12-test-harness-port-hardening-mega-audit-2026-11-12.json), [in-place-vendors-mutation](./tmp/reports/2026-11-12-test-harness-port-hardening-mega-audit-2026-11-12.json), [reorder-write-raise-thread-leak](./tmp/reports/2026-11-12-test-harness-port-hardening-mega-audit-2026-11-12.json), [proxy-port-retry-bounded-not-removed](./tmp/reports/2026-11-12-test-harness-port-hardening-mega-audit-2026-11-12.json) |
| 2026-11-13 | Spec revision (post-audit) | Steps renumbered to 10; every High/Medium applied; user confirmed Option A (tier-routing migration) on 2026-11-13. | — |
| 2026-11-13 | Implementation round (tester) — `overall_result: SUCCESS`, report written | All ten steps landed in one round ([report](./tmp/reports/2026-11-12-test-harness-port-hardening-tester-2026-11-13.json)): full suite **503 passed / 0 failed / 503 total** at exit 0 with a live proxy running (the 500-test baseline + the three new `harness-*` tests); registration proven by `--list` and a targeted `-t` run; all four gates exit 0 with per-step checkpoint lines matching the plan's stated expectations; zero failures, zero flakes, zero skips across every step-conditioned module run. Planner independent verification: all four gates re-run green (18/18, 10/10, 9/9, 3/3), the new module 3/3, `git status` shows exactly the plan's eight files and nothing else. Both adopted deferrals → Resolved. One cosmetic plan-text note: Step 3's old block rendered the admin spawn call's closing paren attached rather than on its own line; the tester applied the edit against the file's actual text — recorded here, no behavior impact. | — |
| 2026-11-13 | Spec revision (/update-plan) | Post-tester pass: both adopted deferral rows flipped to Resolved; Audit Accumulation `issues_resolved_since_audit` 0→2 (below the ≥3 re-audit trigger); Final Results written; `retire_inventory` recorded. No step, file, or guidance change — non-substantive revision. | — |
| 2026-11-13 | Implementation round (tester, round 2) — `overall_result: SUCCESS`, report folded into the day-granular file | Step 11 only ([report](./tmp/reports/2026-11-12-test-harness-port-hardening-tester-2026-11-13.json), which now carries both rounds' records): the `winerror 10048` arm landed in `_bind_mock_server`; bind gate 19/19, all gates exit 0, module 3/3, full suite 503/503, zero flakes. Planner independent verification: bind gate re-run 19/19 exit 0, edit present at `tests/_harness.py`. R1 → Resolved. | — |
| 2026-11-13 | Spec revision (/update-plan, round 2) | Post-round-2 pass: R1 flipped to Resolved; Final Results updated (Step 11 landed; R2 accepted by user). Non-substantive beyond the status flip. | — |
| 2026-11-13 | Review (Phase 6) | [Report](./tmp/reports/2026-11-12-test-harness-port-hardening-review-2026-11-13.json): **Issues found — non-blocking** (0 Critical, 2 Warning, 7 Suggestion); independently re-measured all four gates green, the wrapper's six state-machine shapes, `--list` registration, and the doc gates; confirmed or refuted all 24 mega-audit hunches with evidence. The planner fixed the three doc-accuracy Suggestions (R5 isolation-prose overclaim, R6 Category-14 placement outside the inventory, R9 stale `_drain_child_stderr` row) in the same pass; doc gates re-run green. Warnings R1 (Windows `winerror` 10048 not matched in `_bind_mock_server`, making the fallback POSIX-only) and R2 (the connect-only grace is a fixed 1.5 s vs. the readiness window's load headroom) are recorded as known caveats in Final Results, disposition presented to the user. | [R3-preserve-block-sixfold-duplication](./tmp/reports/2026-11-12-test-harness-port-hardening-review-2026-11-13.json), [R4-removal-branch-suite-level-only](./tmp/reports/2026-11-12-test-harness-port-hardening-review-2026-11-13.json), [R7-green-run-prints-preserve-note](./tmp/reports/2026-11-12-test-harness-port-hardening-review-2026-11-13.json), [R8-two-test-admin-early-branches-unclosed](./tmp/reports/2026-11-12-test-harness-port-hardening-review-2026-11-13.json), [R5-doc-isolation-overclaim](./tmp/reports/2026-11-12-test-harness-port-hardening-review-2026-11-13.json) (fixed), [R6-category-14-placement](./tmp/reports/2026-11-12-test-harness-port-hardening-review-2026-11-13.json) (fixed), [R9-drain-row-stale](./tmp/reports/2026-11-12-test-harness-port-hardening-review-2026-11-13.json) (fixed) |

## Plan Metadata

```json
{
  "plan_id": "2026-11-12-test-harness-port-hardening",
  "steps": [
    "Step 1: Add _MockHTTPServer + _bind_mock_server; migrate the three mock starters to it",
    "Step 2: _spawn_proxy_with_bind_retry (marker-gated) + _readiness_detail plumbing; migrate the three in-harness proxy spawn sites",
    "Step 3: _start_admin_proxy — bind mocks before writing config/keys, patch the vendor URL to the bound port",
    "Step 4: _start_mode_proxy — same reorder and URL patch",
    "Step 5: _setup_tier_routing_test — migrate the majority path to bind-first, keep skip semantics behind caller_owns_ports",
    "Step 6: Correct the six direct starter call sites — bind first, derive the port from the server; close their teardown listeners",
    "Step 7: Close mock listening sockets at every harness teardown site; preserve setup-failure evidence (incl. child stderr)",
    "Step 8: Failure-aware cleanup() — _TEST_FAILED flag, preserve on flag OR in-flight exception, dump stderr",
    "Step 9: Self-classifying failure message in the chat-sse transition test",
    "Step 10: New permanent tests — tests/test_harness_hardening.py + aggregator registration",
    "Step 11: _bind_mock_server also matches the Windows bind-collision errno (review R1, user-approved 2026-11-13)"
  ],
  "coder_files": [],
  "tester_files": [
    "tests/_harness.py",
    "tests/test_admin.py",
    "tests/test_cli.py",
    "tests/test_retry_streaming.py",
    "tests/test_tier_routing.py",
    "tests/test_chat_sse.py",
    "tests/test_harness_hardening.py",
    "tests/test_claude_proxy.py",
    "./tmp/verification/2026-11-12-test-harness-port-hardening-bind.py",
    "./tmp/verification/2026-11-12-test-harness-port-hardening-spawn.py",
    "./tmp/verification/2026-11-12-test-harness-port-hardening-cleanup.py",
    "./tmp/verification/2026-11-12-test-harness-port-hardening-chat-sse-message.py"
  ],
  "doc_files": ["./doc/test-catalog.html"],
  "verification_scripts": [
    "./tmp/verification/2026-11-12-test-harness-port-hardening-bind.py",
    "./tmp/verification/2026-11-12-test-harness-port-hardening-spawn.py",
    "./tmp/verification/2026-11-12-test-harness-port-hardening-cleanup.py",
    "./tmp/verification/2026-11-12-test-harness-port-hardening-chat-sse-message.py"
  ],
  "retire_inventory": [
    "./tmp/reports/2026-11-12-test-harness-port-hardening-mega-audit-2026-11-12.json",
    "./tmp/reports/2026-11-12-test-harness-port-hardening-tester-2026-11-13.json",
    "./tmp/reports/2026-11-12-test-harness-port-hardening-review-2026-11-13.json",
    "./tmp/verification/2026-11-12-test-harness-port-hardening-bind.py",
    "./tmp/verification/2026-11-12-test-harness-port-hardening-spawn.py",
    "./tmp/verification/2026-11-12-test-harness-port-hardening-cleanup.py",
    "./tmp/verification/2026-11-12-test-harness-port-hardening-chat-sse-message.py"
  ],
  "repo_mode": "Public",
  "document_overrides": []
}
```

## Audit Accumulation

*Counters reset when mega-audit runs. Used by Phase 5 entry trigger.*

| Counter | Value | Last Updated |
|---------|-------|--------------|
| issues_resolved_since_audit | 2 | 2026-11-13 |
| steps_changed_since_audit | 0 | 2026-11-13 |
| files_changed_since_audit | 0 | 2026-11-13 |

## Documentation

See "Guidance for Planner" — the only doc surface is `doc/test-catalog.html`
(harness helper table, module catalog row, isolation prose, per-test index
plus its stamps). No `CLAUDE.md` or `README.md` change is expected; the
doc-sync grep confirms.

## Final Results

**Status: COMPLETED** — 2026-11-13.

All eleven tester-lane steps implemented and verified (Steps 1-10 in one round, Step 11 in a follow-up round)
([tester report](./tmp/reports/2026-11-12-test-harness-port-hardening-tester-2026-11-13.json),
`overall_result: SUCCESS`). No coder steps existed (test-infrastructure plan;
repo precedent: `plans/2026-10-03-stale-test-state-file-pid-reuse.md`).

**Files changed:** `tests/_harness.py`, `tests/test_admin.py`,
`tests/test_cli.py`, `tests/test_retry_streaming.py`,
`tests/test_tier_routing.py`, `tests/test_chat_sse.py`,
`tests/test_harness_hardening.py` (new), `tests/test_claude_proxy.py`.
No `src/`, `doc/`, `CLAUDE.md`, or `README.md` file touched by the round.

**Test results:** full suite **503 passed / 0 failed / 503 total** at exit 0,
run with a live proxy on port 8080 (the plan's safe-alongside condition) —
the 500-test 2026-11-12 baseline plus the three new permanent
`harness-*` tests, all passing standalone, via targeted `-t`, and inside the
aggregator (registration proven by `--list`). All four planner-authored gates
green on the final tree (bind 18/18, spawn 10/10, cleanup 9/9,
chat-sse-message 3/3), independently re-run by the planner. Zero flakes
across the round's runs.

**Issues resolved (both were adopted deferrals):**
- `admin-straggler-eaddrinuse` — Resolved 2026-11-13 (see Issue Log).
- `flaky-chat-sse-transition-empty-stream` — Resolved 2026-11-13 (see Issue Log).

**Deferred issues remaining open in this repo (not this plan's):**
`analyze-trace-model-terminal-escape`, `drop-redacted-thinking-chat-placeholder`,
`proxy-own-server-date-headers` — the first and third are Plan B's scope.

**Known caveats / accepted residuals:**
- **R1 (review Warning) — resolved in Step 11:** `_bind_mock_server` now also
  matches `winerror 10048` (round 2, bind gate assertion 11), so the fallback
  works on Windows too. The `caller_owns_ports` skip branch keeps its
  pre-existing Windows dual-bind behavior by design.
- **R2 (review Warning):** the retry wrapper's connect-only confirmation is a
  single fixed 1.5 s grace, while the readiness wait itself grants 30 s ×2
  windows for load; a heavily loaded child that has not yet reached its port
  guard behind a foreign listener could theoretically be returned as ready.
  Idle-measured marker latency is ~0.2 s, so the exposure is load-only and
  rare. Accepted by the user (2026-11-13).
- Test-local listeners outside the plan's touched sites still `shutdown()`
  without `server_close()` (e.g. the SSE pre-bind fixtures' own listeners,
  and the two in-test early branches in `test_admin.py` noted by the review) —
  recorded in Risks as accepted.
- The 28 direct `_start_proxy_server_directly` test-file spawn sites and the
  CLI-start probe paths keep today's behavior (no bind retry) — the retry
  rides only the three harness-mediated spawns.
- One pre-existing residue directory, `/tmp/proxy_mode_9nato33h`
  (2026-11-12 23:43, pre-round) — an instance of the pre-change crash shape
  this plan removes; left in place (workflow deletions ride the user's
  hand-off). Inert; may be deleted by hand.
- Cosmetic: Step 3's plan old-block rendered the admin spawn call's closing
  paren attached; the tester applied the edit against the file's actual text
  (History row, 2026-11-13).

## Cross-References to Prior Plans

| Prior Plan | Deferred Issue | Resolution |
|------------|---------------|------------|
| 2026-10-25-json-nesting-limit | `**Deferral: \`admin-straggler-eaddrinuse\`**` | This plan closed the harness port-allocation race family: bind-first with ephemeral rebind and URL correction at all four builders and the six direct sites, `caller_owns_ports` skip semantics for the 3 SSE pre-bind callers, proxy-port spawn retry keyed on the server's real busy-port message, and `server_close()` at every harness teardown site the plan touches. |
| 2026-10-25-json-nesting-limit | `**Deferral: \`flaky-chat-sse-transition-empty-stream\`**` | This plan implemented the deferral's prescribed disposition: the transition test's failure is now self-classifying (frame types + raw head in the message) and a failed test preserves its trace, child stderr, and artifacts instead of deleting them, so a recurrence is diagnosable without a rerun. |
