# Plan: Windows readiness probe, admin fixes, count_tokens retry control, and test suite completion

**Project:** D:\proj\claude-retry-proxy
**Plan ID:** 2026-08-25-fix-windows-readiness-probe
**Created:** 2026-08-25
**Updated:** 2026-08-26 (COMPLETED — all 39 steps done, 64/64 PASS)

## Summary

**Part A (Steps 1-8, COMPLETED):** Fix `claude-retry-proxy start` on Windows
where `select.select()` fails on pipe fds. Replace with thread-based READY
detection. Also fix admin model dropdown (provider-keyed), tier ordering,
`_config_path` global bug, button naming, and trace log `model` field.

**Part B (Steps 9-15, COMPLETED):** Add `disable_retry_claude_count_token` config flag to
skip retrying the `count_tokens` endpoint. Third-party providers don't support
it — they return 503/connection-errors — and the proxy wastes 10 retries per
request. Also enrich retry log messages with model, provider, and request ID.

**Part C (Steps 16-39):** Fix two pre-existing test issues from the
`2026-08-23-cc-switch-mode` plan: (1) 4 CLI-start tests defined but never
registered in `ALL_TESTS`, with bodies written against the old CLI that had
URL-swap/settings.json manipulation — the current CLI has none of these;
(2) 14 admin/CLI tests are stub SKIPs that print "SKIP: Requires ..." and
count as PASSED without exercising any code. The fix introduces plain
(unencrypted) keys-index.json file support in the server and CLI — a
`VimCrypt~03!` header triggers decryption, otherwise the file is parsed as
plain JSON (with a stderr warning). This eliminates the passphrase
requirement for most tests. Steps 16-17 (coder: server.py + cli.py),
Steps 18-35a (tester: 18 test implementations), and Steps 36-37 (planner:
CLAUDE.md + README.md) are COMPLETED. Steps 38-39 (tester: cleanup) remain.

## Issue Log

Rows ordered newest-first (latest issues at top). New issues are prepended; resolved issues stay in place with updated status.

| Issue | Status | Found | Resolved | Resolved By |
|-------|--------|-------|----------|-------------|
| [test-step-flakiness-and-count-vs-stub-tests](./tmp/reports/2026-08-25-fix-windows-readiness-probe-test-step-flakiness-and-count-vs-stub-tests.json) | Resolved | 2026-08-26 | 2026-08-26 | tester |
| [cli-start-tests-unregistered-and-failing](./tmp/reports/2026-08-25-fix-windows-readiness-probe-cli-start-tests-unregistered-and-failing.json) | Resolved | 2026-08-25 | 2026-08-26 | tester |
| [admin-switch-test-stub](./tmp/reports/2026-08-25-fix-windows-readiness-probe-admin-switch-test-stub.json) | Resolved | 2026-08-25 | 2026-08-26 | tester |
| [report-state-reconciliation](./tmp/reports/2026-08-25-fix-windows-readiness-probe-report-state-reconciliation.json) | Resolved | 2026-08-26 | 2026-08-26 | planner |
| [count-tokens-retry-control-plan-contradictions](./tmp/reports/2026-08-25-fix-windows-readiness-probe-count-tokens-retry-control-plan-contradictions.json) | Resolved | 2026-08-26 | 2026-08-26 | tester |
| [steps14-15-doc-work](./tmp/reports/2026-08-25-fix-windows-readiness-probe-steps14-15-doc-work.json) | Resolved | 2026-08-26 | 2026-08-26 | planner |
| [no-retry-paths-mega-audit](./tmp/reports/2026-08-25-no-retry-paths-mega-audit-2026-08-25.json) | Resolved | 2026-08-25 | 2026-08-25 | planner |
| [models-tier-keyed-docs-and-template](./tmp/reports/2026-08-25-fix-windows-readiness-probe-models-tier-keyed-docs-and-template.json) | Resolved | 2026-08-25 | 2026-08-25 | coder + tester |
| mega-audit-missing-tests | Resolved | 2026-08-25 | 2026-08-25 | tester |
| config-path-not-global | Resolved | 2026-08-25 | 2026-08-25 | coder |
| admin-models-tier-keyed | Resolved | 2026-08-25 | 2026-08-25 | coder |
| [step2-doc-work](./tmp/reports/2026-08-25-fix-windows-readiness-probe-step2-doc-work.json) | Resolved | 2026-08-25 | 2026-08-25 | planner |

## Audit Accumulation

| Counter | Value |
|---------|-------|
| `issues_resolved_since_audit` | 3 |
| `steps_changed_since_audit` | 25 |
| `files_changed_since_audit` | 7 |
| **Last Updated** | 2026-08-26 (COMPLETED) |

## Guidance for Coder

**Files to modify (Part A, completed):** `src/claude_retry_proxy/cli.py`, `src/claude_retry_proxy/admin.html`, `src/claude_retry_proxy/server.py`, `src/claude_retry_proxy/config-template.json`, `README.md`

**Files to modify (Part B, completed):** `src/claude_retry_proxy/config-template.json`, `src/claude_retry_proxy/server.py`, `README.md`, `CLAUDE.md`

**Files to modify (Part C):** `src/claude_retry_proxy/server.py`, `src/claude_retry_proxy/cli.py`

**Files to modify (Part C, tester):** `tests/test_claude_proxy.py`

**Files to modify (Part C, planner):** `CLAUDE.md`, `README.md`

### Part A: Steps 1-8 (COMPLETED)

Steps 1-8 are complete. See [coder reports](./tmp/reports/) for implementation details.

### Part B: Steps 9-15 (COMPLETED)

Steps 9-15 are complete. See [coder reports](./tmp/reports/) for implementation details.

### Part C: Steps 16-17 (coder — source files only)

#### Step 16: server.py — add `load_keys_file` supporting plain and encrypted

Add a new function `load_keys_file(path, passphrase=None)` after the existing
`decrypt_keys` function (around line 336). This function handles both
encrypted and plain keys files. The server reads the file once, checks for
`VimCrypt~03!` magic via `startswith`, and dispatches:

```python
def load_keys_file(path, passphrase=None):
    """Load keys-index.json (encrypted or plain) and return vendors table.

    If the file starts with VimCrypt~03!, passphrase is required and the
    file is decrypted. Otherwise, the file is parsed as plain JSON
    (passphrase is ignored).
    """
    with open(path, "rb") as f:
        data = f.read()

    if data.startswith(b"VimCrypt~03!"):
        if not passphrase:
            raise ValueError("passphrase required for encrypted keys file")
        plaintext = vimcrypt.decrypt(data, passphrase)
    else:
        # Reject other VimCrypt~ prefixes (e.g. blowfish1) to avoid confusing
        # "not valid JSON" errors
        if data.startswith(b"VimCrypt~"):
            raise ValueError(
                "unsupported vim encryption method — only blowfish2 "
                "(VimCrypt~03!) is supported"
            )
        plaintext = data

    try:
        text = plaintext.decode("utf-8")
    except UnicodeDecodeError as e:
        raise ValueError("keys file is not valid UTF-8: {}".format(e))
    try:
        keys_data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError("keys file is not valid JSON: {}".format(e))
    if not isinstance(keys_data, dict):
        raise ValueError("keys file must be a JSON object")
    if "vendors" not in keys_data:
        raise ValueError("keys file missing 'vendors' key")
    vendors = keys_data["vendors"]
    if not isinstance(vendors, dict):
        raise ValueError("'vendors' must be an object")
    for name, vendor in vendors.items():
        if not isinstance(vendor, dict):
            raise ValueError("vendor '{}' must be an object".format(name))
        if "url" not in vendor:
            raise ValueError("vendor '{}' missing 'url'".format(name))
        if "key" not in vendor:
            raise ValueError("vendor '{}' missing 'key'".format(name))
    return vendors
```

In `main()` (around line 1688-1725), replace the passphrase-read +
`decrypt_keys` call. Read the file once, check magic with `startswith`, and
dispatch. **Important:** keep the error message wording as "decryption" (not
"load") to avoid breaking `test_key_decryption_wrong_passphrase`:

```python
# Read keys file and detect format
try:
    with open(keys_path, "rb") as _kf:
        _keys_data = _kf.read()
except FileNotFoundError:
    print("[proxy] ERROR: Keys file not found: {}".format(keys_path), file=sys.stderr)
    sys.exit(1)

_needs_passphrase = _keys_data.startswith(b"VimCrypt~03!")

if _needs_passphrase:
    # Read passphrase (same logic as before)
    if args.passphrase_file:
        try:
            with open(args.passphrase_file, "r", encoding="utf-8") as f:
                passphrase = f.read().rstrip("\r\n")
        except OSError as e:
            print("[proxy] ERROR: Cannot read passphrase file: {}".format(e), file=sys.stderr)
            sys.exit(1)
        if not passphrase:
            print("[proxy] ERROR: Empty passphrase in file", file=sys.stderr)
            sys.exit(1)
    else:
        passphrase = read_passphrase_from_stdin()
else:
    passphrase = None
    # Warn about plain keys at-rest exposure (mirrors --all warning)
    print("[proxy] WARNING: keys file is plain JSON — API keys are stored "
          "unencrypted on disk", file=sys.stderr)

# Load keys (decrypts if encrypted, parses plain JSON otherwise)
try:
    _vendors = load_keys_file(keys_path, passphrase)
except ValueError as e:
    print("[proxy] ERROR: Key decryption failed: {}".format(e), file=sys.stderr)
    sys.exit(1)
```

Key design decisions:
- Read the file once, pass bytes to `load_keys_file` — no TOCTOU window
- Use `startswith` (not `==` on a 12-byte read) for consistency with
  `vimcrypt.decrypt` and `load_keys_file`
- Reject `VimCrypt~01!`/`VimCrypt~02!` prefixes in `load_keys_file` to
  avoid confusing "not valid JSON" errors for unsupported encryption methods
- Keep "Key decryption failed" wording in the error message so
  `test_key_decryption_wrong_passphrase` continues to pass
- Emit stderr warning when plain keys are loaded (security transparency)

Keep the existing `decrypt_keys` function unchanged for backward
compatibility.

#### Step 17: cli.py — plain keys file detection in `cmd_start`

In `cmd_start()` (around line 384-410), replace the passphrase prompt +
decrypt block. **Critical:** track whether the file is encrypted so the
server-spawn code can conditionally pipe the passphrase:

```python
    # 3. Load keys file (plain JSON or encrypted)
    try:
        with open(keys_path, "rb") as f:
            keys_data = f.read()
    except FileNotFoundError:
        print("ERROR: Keys file not found: {}".format(keys_path))
        return 1

    _keys_encrypted = keys_data.startswith(b"VimCrypt~03!")

    if _keys_encrypted:
        # Encrypted: prompt for passphrase and decrypt
        try:
            passphrase = vimcrypt.prompt_hidden("Passphrase: ")
        except (ValueError, KeyboardInterrupt) as e:
            print("\nERROR: {}".format(e))
            return 1
        try:
            plaintext = vimcrypt.decrypt(keys_data, passphrase)
            keys_json = json.loads(plaintext.decode("utf-8"))
        except ValueError as e:
            print("ERROR: Decryption failed: {}".format(e))
            return 1
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            print("ERROR: Invalid keys file: {}".format(e))
            return 1
    else:
        # Plain JSON: parse directly, no passphrase needed
        passphrase = None  # signal to skip stdin piping below
        try:
            keys_json = json.loads(keys_data.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            print("ERROR: Invalid keys file: {}".format(e))
            return 1

    if "vendors" not in keys_json:
        print("ERROR: keys file missing 'vendors' key")
        return 1
    vendors = keys_json["vendors"]
    _trace("cmd_start: loaded {} vendors".format(len(vendors)))
```

In the server spawn block (around line 482-503), guard the passphrase piping
on `_keys_encrypted`:

```python
    proc = subprocess.Popen(
        PROXY_SERVER + ["--port", str(port), "--config-path", config_path,
                        "--keys-path", keys_path],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env=env, text=True
    )

    if _keys_encrypted:
        # Pipe passphrase to server for decryption
        try:
            proc.stdin.write(passphrase + "\n")
            proc.stdin.flush()
        except (BrokenPipeError, OSError) as e:
            _trace("cmd_start: server exited early during passphrase pipe: {}".format(e))
            # ... existing early-death detection logic ...
        finally:
            try:
                proc.stdin.close()
            except OSError:
                pass
    else:
        # Plain keys — close stdin so server doesn't block on read
        proc.stdin.close()
```

Note: `passphrase` is set to `None` in the plain branch (not left
unassigned), so the `_keys_encrypted` guard is safe — no NameError.

Also add `--passphrase-file` to the CLI `start` subcommand parser
(around line 354) so encrypted-key CLI starts can work non-interactively:

```python
parser.add_argument("--passphrase-file", type=str, default=None,
                    help="Read passphrase from file (for non-interactive use)")
```

When `--passphrase-file` is set and the keys file is encrypted, read
passphrase from the file instead of prompting. Pass it through to the
server via `--passphrase-file` on the server command line (instead of
piping on stdin) so the server reads it directly.

## Guidance for Planner

### Part C: Steps 36-37 (documentation)

#### Step 36: CLAUDE.md — plain keys file support

In the Gotchas section, add a note about plain keys files:

```markdown
- **Keys file can be plain JSON (no encryption).** The server and CLI
  auto-detect the format: if the file starts with `VimCrypt~03!` it is
  decrypted with the passphrase; otherwise it is parsed as plain JSON
  directly (no passphrase prompt). The server emits a stderr warning when
  plain keys are loaded. Plain files are convenient for testing and
  automation but leave API keys unencrypted on disk — restrict the file
  ACL on Windows with `icacls`. The recommended approach for production is
  to encrypt with `vim -n -x` (blowfish2, `VimCrypt~03!`, the default).
```

#### Step 37: README.md — plain keys file documentation

In the Configuration section, add a "Keys file format" subsection:

```markdown
### Keys file format

The keys file (`~/.claude/keys-index.json`) can be either:

- **Encrypted** (recommended for production): Encrypt with `vim -n -x
  keys-index.json` using the default blowfish2 method (`VimCrypt~03!`).
  The server and CLI will prompt for the passphrase.

- **Plain JSON** (convenient for testing/automation): A standard JSON file
  with a `"vendors"` key. No passphrase is required. The server emits a
  warning to stderr when plain keys are loaded. On Windows, restrict the
  file ACL with `icacls` since `chmod` is a near-no-op.

The format is auto-detected by checking for the `VimCrypt~03!` magic bytes
at the start of the file.
```

Also update the Quick start bullet that currently says "encrypted, vim
blowfish2 format" to mention the plain-JSON option, and update the
`PROXY_KEYS_PATH` environment variable description from "Encrypted keys
file location" to "Keys file location (encrypted or plain JSON)".

## Guidance for Tester

### Part A tests (completed)

- `test_admin_models_provider_keyed` — permanent, PASS
- `tests/temp/test_windows_readiness_probe_2026-08-25.py` — temporary, PASS

### Part B tests (completed)

8 permanent tests, all PASS. See tester reports for details.

### Part C tests (COMPLETED — tester round 5, 64/64 PASS)

These tests are authored by the tester, not the coder. The coder only
implements Steps 16-17 (server.py + cli.py). The tester implements
Steps 18-35a (test infrastructure + test bodies). All 18 new/rewritten
tests pass. See [tester report](./tmp/reports/2026-08-25-fix-windows-readiness-probe-tester-2026-08-26.json).

#### Phase 1: Test infrastructure (Step 18)

<!-- UPDATED: 2026-08-26 — detailed implementation patterns added -->

1. Add `_create_test_keys_plain(temp_dir, vendors)` — writes plain JSON
   `{"vendors": vendors}` to `keys-index.json`. No encryption, no passphrase:

   ```python
   def _create_test_keys_plain(temp_dir, vendors):
       """Create a plain (unencrypted) keys-index.json for testing."""
       path = os.path.join(temp_dir, "keys-index.json")
       with open(path, "w") as f:
           json.dump({"vendors": vendors}, f)
       return path
   ```

2. Update `_start_proxy_server_directly`: **keep default `passphrase="test-passphrase"`**
   (do NOT change to None). When `passphrase` is not None, pipe it as before.
   When `passphrase` is **exactly** `None`, close stdin without writing.
   Replace the passphrase-piping block (currently lines 333-339):

   ```python
   # Pipe passphrase to server (or close stdin for plain keys)
   if passphrase is not None:
       if proc.stdin:
           try:
               proc.stdin.write(passphrase + "\n")
               proc.stdin.close()
           except (BrokenPipeError, OSError):
               pass
   else:
       # Plain keys: close stdin so server doesn't block on read
       if proc.stdin:
           try:
               proc.stdin.close()
           except OSError:
               pass
   ```

   **Why the `is not None` check matters:** The current code always writes
   `passphrase + "\n"` to stdin. With `passphrase=None`, this writes
   `"None\n"` — the server tries to decrypt with "None" as the passphrase
   and fails. The fix closes stdin without writing for the plain-keys path.

3. Update `_setup_tier_routing_test`: when `default_passphrase` is `None`,
   call `_create_test_keys_plain`; otherwise call `_create_test_keys`
   (existing encrypted path). Default stays `"test-passphrase"` so all
   existing callers (~13) continue to work unchanged. Replace the
   keys-creation line (currently `_create_test_keys(temp_dir, vendors, default_passphrase)`):

   ```python
   # Create keys (plain or encrypted depending on passphrase)
   if default_passphrase is None:
       keys_path = _create_test_keys_plain(temp_dir, vendors)
   else:
       keys_path = _create_test_keys(temp_dir, vendors, default_passphrase)
   ```

   **Note:** The parameter is `default_passphrase`, not `passphrase`. Check
   `if default_passphrase is None`.

4. `_start_proxy_with_flag` is dead code — it's defined but never called.
   Do NOT update it. If needed for new tests, use the plain-keys helpers
   directly.

#### Phase 2: Unregistered CLI tests (Steps 19-22)

These tests were written for the old CLI that had URL-swap, base-url.lock,
and settings.json manipulation. The current CLI has NONE of these. **Every
test body must be rewritten** to match the current CLI's actual behavior.

**Common pattern for all CLI tests (Steps 20-22, 32-35a):**

The CLI writes to hardcoded `~/.claude/proxy/proxy-state.json`. All CLI
tests must:
- Back up the existing `proxy-state.json` before the test
- Delete it so `cmd_start` doesn't refuse with "Proxy already running"
- Restore the backup after the test
- Pass `--log <temp_trace>` to avoid mutating the user's real trace log
- Pass `--config-path <temp_config>` and `--keys-path <temp_keys>` to
  isolate from the user's real config

Add the `PROXY_STATE_FILE` constant (it's not currently defined in the test
file — the test file uses `URL_LOCK_FILE` but not `PROXY_STATE_FILE`):

```python
PROXY_STATE_FILE = os.path.join(PROXY_DIR, "proxy-state.json")
```

Helper for backup/restore (add near `backup_settings`):

```python
def _backup_proxy_state():
    """Back up proxy-state.json, return backup content or None."""
    if os.path.exists(PROXY_STATE_FILE):
        with open(PROXY_STATE_FILE) as f:
            return f.read()
    return None

def _restore_proxy_state(backup):
    """Restore proxy-state.json from backup, or delete if None."""
    if backup is not None:
        os.makedirs(PROXY_DIR, exist_ok=True)
        with open(PROXY_STATE_FILE, "w") as f:
            f.write(backup)
    else:
        try:
            os.remove(PROXY_STATE_FILE)
        except OSError:
            pass

# Add after existing PROXY_STATE_FILE constant:
PROXY_STATE_FILE = os.path.join(PROXY_DIR, "proxy-state.json")
```

Helper for CLI start with plain keys (tests that need a running proxy):

```python
def _cli_start_with_plain_keys(port, config_path, keys_path, trace_file):
    """Start proxy via CLI with plain keys. Returns (proc, stdout, stderr, returncode)."""
    cmd = CLAUDE_PROXY + [
        "start", "--port", str(port),
        "--config-path", config_path,
        "--keys-path", keys_path,
        "--log", trace_file
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            stdin=subprocess.PIPE, text=True)
    # Close stdin — plain keys, no passphrase needed
    try:
        proc.stdin.close()
    except OSError:
        pass
    try:
        stdout, stderr = proc.communicate(timeout=30)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        return proc, "", "", "timeout"
    return proc, stdout, stderr, proc.returncode
```

**Step 19: Rewrite and register test_stop_cleans_proxy_state_lock**

The current test body creates a fake `base-url.lock` with a dead PID and
asserts `cmd_stop` deletes `proxy-state.lock` and `base-url.lock` — but
`cmd_stop` has zero lock-file logic. Rewrite:

1. Back up `proxy-state.json`
2. Create `~/.claude/proxy/proxy-state.json` with a dead PID (99999) and
   a fake port:
   ```python
   dead_pid = 99999
   fake_state = {"pid": dead_pid, "port": 19999, "start_time": "2020-01-01T00:00:00Z",
                 "config_path": "/nonexistent", "keys_path": "/nonexistent"}
   os.makedirs(PROXY_DIR, exist_ok=True)
   with open(PROXY_STATE_FILE, "w") as f:
       json.dump(fake_state, f)
   ```
3. Run `claude-retry-proxy stop`, capture stdout + stderr
4. Assert stderr contains: `"cmd_stop: entering"`, `"cmd_stop: proxy-state.json removed"`,
   `"cmd_stop: returning 0"`
   (Note: `"proxy-state.json removed"` IS deterministic here — the dead-PID
   flow skips graceful shutdown, so the server's finally block doesn't run,
   and `cmd_stop`'s own `os.remove` succeeds.)
5. Assert stdout contains `"Proxy: stopped"`
6. Assert exit code 0
7. Assert `proxy-state.json` is deleted
8. Restore `proxy-state.json`
9. Register in `ALL_TESTS`

**Step 20: Rewrite and register test_stop_cleans_proxy_state**

Current body reads PID from `URL_LOCK_FILE` (base-url.lock) for force-kill
and asserts `base-url.lock` cleanup. Rewrite:

1. Back up `proxy-state.json`, delete it
2. Create temp config + plain keys (`_create_test_config` +
   `_create_test_keys_plain`), temp trace file
3. Start proxy via `_cli_start_with_plain_keys(port, config_path, keys_path, trace_file)`
4. Assert exit code 0, stdout contains `"Proxy started"`
5. TCP-probe the port to confirm proxy is ready
6. Read PID from `proxy-state.json`:
   ```python
   with open(PROXY_STATE_FILE) as f:
       state = json.load(f)
   pid = state["pid"]
   ```
7. Force-kill the server process:
   ```python
   if sys.platform == "win32":
       subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
   else:
       os.kill(pid, signal.SIGKILL)
   time.sleep(0.5)
   ```
8. Assert `proxy-state.json` still exists after force-kill (server cleanup bypassed)
9. Run `claude-retry-proxy stop`, capture stdout + stderr
10. Assert `proxy-state.json` deleted
11. Assert stderr contains: `"cmd_stop: entering"`, `"cmd_stop: returning 0"`
    (Note: `"proxy-state.json removed"` or `"proxy-state.json not found"` —
    either is acceptable. The server's finally block may have removed it
    during the force-kill, or `cmd_stop`'s own `os.remove` may succeed.)
12. Assert exit code 0
13. Restore `proxy-state.json`
14. Register in `ALL_TESTS`

**Step 21: Rewrite and register test_stop_trace_with_proxy**
<!-- UPDATED: 2026-08-26 — fixed non-deterministic assertion list -->

1. Back up `proxy-state.json`, delete it
2. Start proxy via `_cli_start_with_plain_keys(port, config_path, keys_path, trace_file)`
3. Assert exit code 0, TCP-probe the port
4. Run `claude-retry-proxy stop`, capture stdout + stderr
5. Assert stderr contains the deterministic trace lines for the graceful
   shutdown flow (live proxy, `/admin/shutdown` succeeds):
   - `"cmd_stop: entering"` — ALWAYS (cli.py:658)
   - `"cmd_stop: shutdown request accepted"` — iff graceful POST succeeds (cli.py:682)
   - `"cmd_stop: proxy exited gracefully"` — iff server exits within 5s (cli.py:693)
   - `"cmd_stop: returning 0"` — ALWAYS (cli.py:726)
   **Do NOT assert** `"force-killing"` or `"proxy-state.json removed"` —
   in the graceful path, the server's `finally` block removes
   `proxy-state.json` first (server.py:1866-1873), so `cmd_stop`'s own
   `os.remove` raises `OSError` → `"proxy-state.json not found"` (cli.py:706)
   instead of `"removed"` (cli.py:704). The PID is dead after graceful
   exit, so `"force-killing"` (cli.py:712) is never emitted.
6. Assert stdout contains `"Proxy: stopped"`
7. Assert exit code 0
8. Restore `proxy-state.json`
9. Register in `ALL_TESTS`

**Step 22: Rewrite and register test_start_stdout_not_contaminated**

1. Back up `proxy-state.json`, delete it
2. Create temp config + plain keys, temp trace file
3. Start proxy via `_cli_start_with_plain_keys(port, config_path, keys_path, trace_file)`
4. Assert stdout contains `"Proxy started"` and `"Tiers:"`
5. Assert stdout does NOT contain `"[claude-retry-proxy]"` (trace goes to stderr)
6. Assert stdout does NOT contain auth token (no `"x-api-key"` or key material)
7. Assert stderr contains `"[claude-retry-proxy]"` trace lines
8. Remove all `get_base_url()`, `"Original URL"`, `backup_settings()`,
   `restore_settings()` calls — the current CLI doesn't touch settings.json
9. Run `claude-retry-proxy stop` to clean up the proxy
10. Restore `proxy-state.json`
11. Register in `ALL_TESTS`

#### Phase 3: Admin API stub tests (Steps 23-31)

All admin API tests use `_start_proxy_server_directly` with plain keys
(`passphrase=None`). The server starts directly — no CLI involved, no
`proxy-state.json` needed.

**Common pattern for admin API tests:**

```python
def _admin_post(proxy_port, path, body, origin=None):
    """POST to admin API with CSRF Origin header."""
    import http.client as _hc
    conn = _hc.HTTPConnection("127.0.0.1", proxy_port, timeout=10)
    headers = {"Content-Type": "application/json"}
    if origin is not None:
        headers["Origin"] = origin
    else:
        headers["Origin"] = "http://127.0.0.1:{}".format(proxy_port)
    conn.request("POST", path, body=json.dumps(body), headers=headers)
    resp = conn.getresponse()
    data = resp.read().decode()
    conn.close()
    return resp.status, data
```

**Step 23: Implement test_admin_api_switch**

Start proxy with two providers (p1 and p2) on different mock upstream ports.
All 3 tiers initially mapped to p1. POST to `/admin/api/switch` with a full
3-tier body, changing sonnet's provider from p1 to p2:

1. Create two mock upstream servers on different ports:
   ```python
   p1_port = find_free_port()
   p2_port = find_free_port()
   # Create mock servers for p1 and p2 (same pattern as _setup_tier_routing_test)
   ```
2. Create config with both providers, all tiers → p1:
   ```python
   tiers = {
       "haiku": {"provider": "p1", "model": "claude-haiku-4-5"},
       "sonnet": {"provider": "p1", "model": "claude-sonnet-5"},
       "opus": {"provider": "p1", "model": "claude-opus-5"},
   }
   vendors = {
       "p1": {"url": f"http://127.0.0.1:{p1_port}", "key": "k1"},
       "p2": {"url": f"http://127.0.0.1:{p2_port}", "key": "k2"},
   }
   ```
3. Start proxy via `_start_proxy_server_directly(proxy_port, config_path=..., keys_path=..., passphrase=None)`
   (uses `_create_test_keys_plain` for keys)
4. Send a request with model "sonnet" → verify it routes to p1 (baseline)
5. Snapshot p1's request count: `p1_count_before = len(p1_requests)`
6. POST `/admin/api/switch` with full 3-tier body changing sonnet → p2:
   ```python
   switch_body = {
       "tiers": {
           "haiku": {"provider": "p1", "model": "claude-haiku-4-5"},
           "sonnet": {"provider": "p2", "model": "claude-sonnet-5"},
           "opus": {"provider": "p1", "model": "claude-opus-5"},
       }
   }
   status, data = _admin_post(proxy_port, "/admin/api/switch", switch_body)
   ```
7. Assert status == 200, response is `{"status": "ok"}`
8. Send another request with model "sonnet" → verify it routes to p2
   (p2's mock received the request)
9. Assert p1's request count is unchanged: `len(p1_requests) == p1_count_before`
   (p1 received zero further sonnet requests)
10. Register in `ALL_TESTS`

**Step 24: Implement test_admin_api_switch_invalid_provider**

POST a full 3-tier body with one provider set to `"nonexistent"` (all 3
tiers must be present since the server validates tier count before provider
existence). `"nonexistent"` passes `_validate_admin_name` (regex
`^[a-zA-Z0-9_./-]+$`), so validation reaches the provider-existence check
(server.py:1464) which returns `{"error": "unknown provider: nonexistent"}`.

1. Start proxy with one provider via `_start_proxy_server_directly(..., passphrase=None)`
2. POST full 3-tier body with sonnet's provider = `"nonexistent"`:
   ```python
   switch_body = {
       "tiers": {
           "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
           "sonnet": {"provider": "nonexistent", "model": "claude-sonnet-5"},
           "opus": {"provider": "p", "model": "claude-opus-5"},
       }
   }
   status, data = _admin_post(proxy_port, "/admin/api/switch", switch_body)
   ```
3. Assert status == 400
4. Assert `"unknown provider"` in data
5. Register in `ALL_TESTS`

**Step 25: Implement test_admin_api_switch_preserves_models**

Start proxy with a `models` section in config. POST switch with only tiers
(no models field). Verify via GET `/admin/api/config` that the `models`
section is unchanged. Also verify on-disk `config.json` still has the
models section.

1. Create config with `models` section:
   ```python
   config = {
       "tiers": { ... },
       "models": {"p": ["claude-sonnet-5", "claude-haiku-4-5", "claude-opus-5"]}
   }
   ```
2. Start proxy, POST switch (tiers only, no models), assert 200
3. GET `/admin/api/config` → assert `models` section unchanged
4. Read `config.json` from disk → assert `models` section still present
5. Register in `ALL_TESTS`

**Step 26: Implement test_admin_api_csrf_rejected**

POST to `/admin/api/switch` with `Origin: http://evil.com:9999`:

```python
status, data = _admin_post(proxy_port, "/admin/api/switch", switch_body,
                           origin="http://evil.com:9999")
assert status == 403
```

**Step 27: Implement test_admin_api_csrf_null_origin_rejected**

POST with `Origin: null`:

```python
status, data = _admin_post(proxy_port, "/admin/api/switch", switch_body,
                           origin="null")
assert status == 403
```

**Step 28: Implement test_admin_api_csrf_missing_origin_rejected**

POST without Origin header (use `http.client.HTTPConnection` directly,
omit the `Origin` header entirely):

```python
conn = _hc.HTTPConnection("127.0.0.1", proxy_port, timeout=10)
conn.request("POST", "/admin/api/switch",
             body=json.dumps(switch_body),
             headers={"Content-Type": "application/json"})
resp = conn.getresponse()
assert resp.status == 403
```

**Step 29: Implement test_admin_api_csrf_ipv6_loopback_accepted**

POST with `Origin: http://[::1]:<proxy_port>` and a valid 3-tier switch body.
Verify 200 (Origin allowlist accepts [::1] loopback). Note: the server binds
`127.0.0.1` only, so the actual connection is IPv4 — this test validates the
Origin header allowlist, not a real IPv6 connection.

```python
origin = "http://[::1]:{}".format(proxy_port)
status, data = _admin_post(proxy_port, "/admin/api/switch", switch_body,
                           origin=origin)
assert status == 200
```

**Step 30: Implement test_admin_api_switch_missing_tier_rejected**

POST with only 2 tiers (e.g., haiku + sonnet, missing opus). The server
validates tier count (server.py:1432-1438) before provider existence.
Verify 400 response with `"missing tiers"` in the error:

```python
switch_body = {
    "tiers": {
        "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
        "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
    }
}
status, data = _admin_post(proxy_port, "/admin/api/switch", switch_body)
assert status == 400
assert "missing tiers" in data
```

**Step 31: Implement test_admin_api_reload**

Start proxy with tier mapping A. Modify `config.json` on disk to tier
mapping B (different model for sonnet). POST `/admin/api/reload`. Send a
request with model "sonnet" and verify it routes to the new model (mapping B).

1. Create config with tier mapping A (sonnet → model-A)
2. Start proxy via `_start_proxy_server_directly(..., passphrase=None)`
3. Send request with model "sonnet" → verify routes to model-A (baseline)
4. Modify `config.json` on disk: change sonnet model to model-B
5. POST `/admin/api/reload`:
   ```python
   status, data = _admin_post(proxy_port, "/admin/api/reload", {})
   assert status == 200
   ```
6. Send another request with model "sonnet" → verify routes to model-B
7. Register in `ALL_TESTS`

#### Phase 4: CLI stub tests (Steps 32-35a)

**Important:** `cmd_reload` and `cmd_status` read from
`~/.claude/proxy/proxy-state.json` (hardcoded path). They do NOT accept
`--port` or `--config-path` arguments. The proxy must be started via the
CLI `start` command (which writes proxy-state.json) for these tests to work.
Direct server start (`_start_proxy_server_directly`) does NOT write
`proxy-state.json`.

All CLI tests in this phase must back up/restore `proxy-state.json` and
delete it before starting (to avoid `cmd_start` refusing with "Proxy
already running" when `is_pid_alive(pid)` returns True).

**Step 32: Implement test_cli_reload**

1. Back up `proxy-state.json`, delete it
2. Create temp config (tier mapping A) + plain keys, temp trace file
3. Start proxy via `_cli_start_with_plain_keys(port, config_path, keys_path, trace_file)`
4. Assert exit code 0, TCP-probe the port
5. Modify `config.json` on disk: change sonnet's model to a different value
   (tier mapping B)
6. Run `claude-retry-proxy reload` (no `--port` — it reads port from
   `proxy-state.json`):
   ```python
   result = subprocess.run(CLAUDE_PROXY + ["reload"],
                           capture_output=True, text=True, timeout=10)
   assert result.returncode == 0
   ```
7. Send a request with model "sonnet" → verify it routes to the new model
   (mapping B). This proves the reload took effect.
8. Run `claude-retry-proxy stop` to clean up
9. Restore `proxy-state.json`
10. Register in `ALL_TESTS`

**Step 33: Implement test_cli_start_no_config**

1. Back up `proxy-state.json`, delete it
2. Set `--config-path` to a temp path that doesn't exist
3. Create a plain keys file at a temp path
4. Run `claude-retry-proxy start --config-path <nonexistent> --keys-path <plain_keys>`,
   close stdin (plain keys → no passphrase prompt):
   ```python
   proc = subprocess.Popen(
       CLAUDE_PROXY + ["start", "--config-path", nonexistent_config,
                       "--keys-path", plain_keys_path],
       stdout=subprocess.PIPE, stderr=subprocess.PIPE,
       stdin=subprocess.PIPE, text=True
   )
   try:
       proc.stdin.close()
   except OSError:
       pass
   stdout, stderr = proc.communicate(timeout=30)
   ```
5. Assert exit code == 1
6. Assert template is created at the config path: `os.path.exists(nonexistent_config)`
7. Assert stdout contains `"Created config template"`
   (Note: the CLI checks config existence FIRST, returns 1 before reading
   the keys file — so `--keys-path` can point to anything valid)
8. Restore `proxy-state.json`
9. Register in `ALL_TESTS`

**Step 34: Implement test_cli_start_invalid_config**

1. Back up `proxy-state.json`, delete it
2. Create a config file with invalid JSON at a temp path:
   ```python
   with open(invalid_config_path, "w") as f:
       f.write("not valid json {{{")
   ```
3. Create a plain keys file at a temp path
4. Run `claude-retry-proxy start --config-path <invalid_config> --keys-path <plain_keys>`,
   close stdin
5. Assert exit code == 1
6. Assert stderr contains `"Invalid config"` or `"ERROR"`
   (The CLI loads and validates config at line 381-384. Invalid JSON is
   caught by `_load_config_for_validation` which calls `json.load`.)
7. Restore `proxy-state.json`
8. Register in `ALL_TESTS`

**Step 35: Implement test_cli_status_shows_tiers**

1. Back up `proxy-state.json`, delete it
2. Create temp config + plain keys, temp trace file
3. Start proxy via `_cli_start_with_plain_keys(port, config_path, keys_path, trace_file)`
4. Assert exit code 0
5. Run `claude-retry-proxy status`:
   ```python
   stdout, stderr, rc = proxy_status()
   assert rc == 0
   ```
6. Assert stdout contains tier names (haiku, sonnet, opus) and
   provider/model info. The `cmd_status` output format is (cli.py
   `cmd_status` function):
   ```
   Proxy: running
     PID: <pid>
     Port: <port>
     Config: <config_path>
     Tiers:
       haiku -> <model> (<provider>)
       sonnet -> <model> (<provider>)
       opus -> <model> (<provider>)
   ```
7. Run `claude-retry-proxy stop` to clean up
8. Restore `proxy-state.json`
9. Register in `ALL_TESTS`

**Step 35a: Implement test_config_template_copy (bonus)**

The existing `test_config_template_copy` is also a SKIP stub. Implement it:

1. Back up `proxy-state.json`, delete it
2. Choose a temp path for the config that doesn't exist yet
3. Create a plain keys file at a temp path
4. Run `claude-retry-proxy start --config-path <temp_nonexistent> --keys-path <plain_keys>`,
   close stdin
5. Assert exit code == 1
6. Assert template is created at the config path
7. Assert stdout contains `"Created config template"`
8. Restore `proxy-state.json`
9. Register in `ALL_TESTS`

This is essentially the same flow as Step 33 — can share the same
implementation or be a separate test with the same assertions.

#### Phase 5: Documentation verification (Steps 36-37)

22. **CLAUDE.md** — plain keys file gotcha present with `vim -n -x`
    recommendation and Windows ACL note.
23. **README.md** — keys file format section present with encrypted vs
    plain options, auto-detection description, and Windows ACL note.
    Quick start bullet and `PROXY_KEYS_PATH` env-var row updated.

#### Phase 6: Cleanup (Steps 38-39, tester) <!-- ADDED: 2026-08-26 -->

**Step 38: Fix stale proxy-state.json cleanup in test_stop_cleans_proxy_state**

The force-kill test has a race: the server writes `proxy-state.json` on
startup, the test force-kills the server (bypassing its `finally` block),
and the `_restore_proxy_state` in the test's `finally` block may restore
a backup taken before the server wrote state. This leaves inert residue
in `~/.claude/proxy/proxy-state.json` with a dead test PID.

Fix: after the force-kill, explicitly delete `proxy-state.json` before
restoring the backup. This ensures the restore always puts back the
pre-test state:

```python
# After force-kill and before restore:
try:
    os.remove(PROXY_STATE_FILE)
except OSError:
    pass
```

This is a one-line addition in `test_stop_cleans_proxy_state` (Step 20),
after the force-kill and before the `_restore_proxy_state` call in the
`finally` block.

**Step 39: Delete 6 dead old-CLI test functions**

Six test functions are defined but never registered in `ALL_TESTS`. They
were written for the old CLI with URL-swap, `base-url.lock`,
`settings.json` manipulation — concepts that don't exist in the current
CLI. They are:

| Function | Line | Dead references |
|----------|------|----------------|
| `test_stop_cleans_lock_on_write_failure` | 1695 | `write_settings_url`, `base-url.lock`, `backup_settings()` |
| `test_stop_kills_proxy_with_non_localhost_url` | 1797 | `get_base_url()`, `set_base_url()`, `restore_settings()` |
| `test_release_swap_lock_retries` | 1911 | `URL_SWAP_LOCK_FILE`, `release_swap_lock()` |
| `test_release_swap_lock_warns_on_final_failure` | 1966 | `URL_SWAP_LOCK_FILE`, `release_swap_lock()` |
| `test_stop_trace_no_proxy` | 2167 | `base-url.lock`, `backup_settings()` |
| `test_proxy_state_no_auth_token` | 2601 | `proxy-state.json` auth token format |

Delete all six functions and their associated test blocks. They are dead
code — the concepts they test don't exist in the current CLI, and they
were never registered in `ALL_TESTS`. Also remove any stale imports or
helpers that are only used by these six functions (e.g.,
`write_settings_url`, `release_swap_lock`, `URL_SWAP_LOCK_FILE` if they
become orphaned).

Verify the suite still passes 64/64 after deletion.

## Proposed Changes

### Part A (Steps 1-8, COMPLETED)

1. **Step 1:** Replace `select`-based stdout readiness loop with thread-based reader in `cli.py`.
2. **Step 2:** Update CLAUDE.md Gotchas with two-phase readiness protocol (planner).
3. **Step 3:** Fix admin page model dropdown to use provider-keyed models.
4. **Step 4:** Change tier display order to opus → sonnet → haiku.
5. **Step 5:** Fix `_config_path` missing from `global` declaration in `server.py`.
6. **Step 6:** Rename admin buttons: "Save Configuration" → "Apply", "Reload from Disk" → "Reload".
7. **Step 7:** Record actual upstream model name in trace log `model` field.
8. **Step 8:** Update config-template.json and README.md to provider-keyed models.

### Part B (Steps 9-15, COMPLETED)

9. **Step 9:** `config-template.json` — add `"disable_retry_claude_count_token": true`.
10. **Step 10:** `server.py` — skip retry logic: `max_attempts` computed from flag, inner guards use `max_attempts - 1`.
11. **Step 11:** `server.py` — enrich retry messages with `model`, `provider`, `request_id`.
12. **Step 12:** `server.py` — `validate_config` boolean type check for the new field.
13. **Step 13:** `server.py` — `/admin/api/switch` preserve `disable_retry_claude_count_token` across hot-switches.
14. **Step 14:** `README.md` — document the new config field.
15. **Step 15:** `CLAUDE.md` — Gotchas entry.

### Part C (Steps 16-37)

16. **Step 16:** `server.py` — add `load_keys_file(path, passphrase=None)` supporting plain JSON and encrypted keys; update `main()` to read file once, detect magic with `startswith`, dispatch, warn on plain keys, keep "Key decryption failed" error wording.
17. **Step 17:** `cli.py` — update `cmd_start()` to detect plain vs encrypted keys file, track `_keys_encrypted` flag, guard passphrase piping, initialize `passphrase=None` in plain branch, add `--passphrase-file` option.
18. **Step 18:** `tests/test_claude_proxy.py` — add `_create_test_keys_plain` helper; keep `_start_proxy_server_directly` default `passphrase="test-passphrase"`; update `_setup_tier_routing_test` to use plain keys when `passphrase=None`.
19. **Step 19:** Rewrite and register `test_stop_cleans_proxy_state_lock` — create proxy-state.json with dead PID, assert proxy-state.json removal (no lock assertions).
20. **Step 20:** Rewrite and register `test_stop_cleans_proxy_state` — plain keys + `--config-path`/`--keys-path`/`--log`, read PID from proxy-state.json for force-kill, back up/restore state.
21. **Step 21:** Rewrite and register `test_stop_trace_with_proxy` — plain keys, assert deterministic graceful-shutdown stderr lines (`"cmd_stop: entering"`, `"cmd_stop: shutdown request accepted"`, `"cmd_stop: proxy exited gracefully"`, `"cmd_stop: returning 0"`), back up/restore state. <!-- UPDATED: 2026-08-26 — removed non-deterministic "force-killing" and "proxy-state.json removed" lines -->
22. **Step 22:** Rewrite and register `test_start_stdout_not_contaminated` — plain keys, strip URL-swap assertions, assert "Proxy started"/"Tiers:" on stdout, remove settings.json interaction.
23. **Step 23:** Implement `test_admin_api_switch` — two providers, switch tier, verify routing changes.
24. **Step 24:** Implement `test_admin_api_switch_invalid_provider` — full 3-tier body with one provider "nonexistent", verify 400 "unknown provider".
25. **Step 25:** Implement `test_admin_api_switch_preserves_models` — verify models section survives switch.
26. **Step 26:** Implement `test_admin_api_csrf_rejected` — foreign Origin → 403.
27. **Step 27:** Implement `test_admin_api_csrf_null_origin_rejected` — Origin: null → 403.
28. **Step 28:** Implement `test_admin_api_csrf_missing_origin_rejected` — no Origin → 403.
29. **Step 29:** Implement `test_admin_api_csrf_ipv6_loopback_accepted` — [::1] Origin → 200 (validates Origin allowlist, not real IPv6).
30. **Step 30:** Implement `test_admin_api_switch_missing_tier_rejected` — 2 tiers → 400 "missing tiers".
31. **Step 31:** Implement `test_admin_api_reload` — disk config change → reload → routing updates.
32. **Step 32:** Implement `test_cli_reload` — start via CLI (for proxy-state.json), run `claude-retry-proxy reload` (no --port), verify effect.
33. **Step 33:** Implement `test_cli_start_no_config` — template created, exit 1.
34. **Step 34:** Implement `test_cli_start_invalid_config` — error message, exit 1.
35. **Step 35:** Implement `test_cli_status_shows_tiers` — start via CLI, status shows tier mapping.
35a. **Step 35a:** Implement `test_config_template_copy` — same flow as Step 33.
36. **Step 36:** `CLAUDE.md` — Gotchas entry: plain keys file support with `vim -n -x` recommendation, Windows ACL note, stderr warning note.
37. **Step 37:** `README.md` — Configuration section: keys file format documentation, update Quick start bullet and `PROXY_KEYS_PATH` env-var row.
38. **Step 38:** `tests/test_claude_proxy.py` — fix stale proxy-state.json cleanup race in `test_stop_cleans_proxy_state` (delete state file after force-kill before restore).
39. **Step 39:** `tests/test_claude_proxy.py` — delete 6 dead old-CLI test functions that reference URL-swap, base-url.lock, and settings.json concepts that no longer exist.

## Repo Mode

Public

## Document Overrides

None.

## Plan Metadata

```json
{
  "plan_id": "2026-08-25-fix-windows-readiness-probe",
  "repo_mode": "Public",
  "steps": [
    "Step 1: Replace select-based stdout readiness loop with thread-based reader (COMPLETED)",
    "Step 2: Update CLAUDE.md Gotchas with two-phase readiness protocol (COMPLETED)",
    "Step 3: Fix admin page model dropdown to use provider-keyed models (COMPLETED)",
    "Step 4: Change tier display order to opus-sonnet-haiku (COMPLETED)",
    "Step 5: Fix _config_path missing from global declaration in server.py (COMPLETED)",
    "Step 6: Rename admin buttons to Apply and Reload (COMPLETED)",
    "Step 7: Record actual upstream model name in trace log model field (COMPLETED)",
    "Step 8: Update config-template.json and README.md to provider-keyed models (COMPLETED)",
    "Step 9: config-template.json — add disable_retry_claude_count_token: true (COMPLETED)",
    "Step 10: server.py — skip retry logic with corrected inner guards (COMPLETED)",
    "Step 11: server.py — enrich retry messages with model/provider/request_id (COMPLETED)",
    "Step 12: server.py — validate_config boolean type check (COMPLETED)",
    "Step 13: server.py — admin /switch preserve disable_retry_claude_count_token (COMPLETED)",
    "Step 14: README.md — document disable_retry_claude_count_token (COMPLETED)",
    "Step 15: CLAUDE.md — Gotchas entry for disable_retry_claude_count_token (COMPLETED)",
    "Step 16: server.py — add load_keys_file (plain+encrypted), update main() dispatch (CODER)",
    "Step 17: cli.py — plain vs encrypted keys detection, conditional passphrase piping, --passphrase-file (CODER)",
    "Step 18: test_claude_proxy.py — add _create_test_keys_plain, update helpers (COMPLETED)",
    "Step 19: Rewrite+register test_stop_cleans_proxy_state_lock (COMPLETED)",
    "Step 20: Rewrite+register test_stop_cleans_proxy_state (COMPLETED)",
    "Step 21: Rewrite+register test_stop_trace_with_proxy — graceful-shutdown stderr lines (COMPLETED)",
    "Step 22: Rewrite+register test_start_stdout_not_contaminated (COMPLETED)",
    "Step 23: Implement test_admin_api_switch (COMPLETED)",
    "Step 24: Implement test_admin_api_switch_invalid_provider (COMPLETED)",
    "Step 25: Implement test_admin_api_switch_preserves_models (COMPLETED)",
    "Step 26: Implement test_admin_api_csrf_rejected (COMPLETED)",
    "Step 27: Implement test_admin_api_csrf_null_origin_rejected (COMPLETED)",
    "Step 28: Implement test_admin_api_csrf_missing_origin_rejected (COMPLETED)",
    "Step 29: Implement test_admin_api_csrf_ipv6_loopback_accepted (COMPLETED)",
    "Step 30: Implement test_admin_api_switch_missing_tier_rejected (COMPLETED)",
    "Step 31: Implement test_admin_api_reload (COMPLETED)",
    "Step 32: Implement test_cli_reload (COMPLETED)",
    "Step 33: Implement test_cli_start_no_config (COMPLETED)",
    "Step 34: Implement test_cli_start_invalid_config (COMPLETED)",
    "Step 35: Implement test_cli_status_shows_tiers (COMPLETED)",
    "Step 35a: Implement test_config_template_copy (COMPLETED)",
    "Step 36: CLAUDE.md — Gotchas entry: plain keys file support (COMPLETED)",
    "Step 37: README.md — keys file format documentation (COMPLETED)",
    "Step 38: Fix stale proxy-state.json cleanup race in test_stop_cleans_proxy_state (TESTER)",
    "Step 39: Delete 6 dead old-CLI test functions (TESTER)"
  ],
  "coder_files": [
    "src/claude_retry_proxy/cli.py",
    "src/claude_retry_proxy/server.py"
  ],
  "tester_files": [
    "tests/test_claude_proxy.py"
  ],
  "doc_files": ["CLAUDE.md", "README.md", "src/claude_retry_proxy/config-template.json"],
  "verification_scripts": [],
  "document_overrides": []
}
```

## History

| Date | Event | Conclusion | Dismissed |
|------|-------|------------|-----------|
| 2026-08-26 | Plan COMPLETED | All 39 steps done. 64/64 PASS. 10 issues resolved. 7 files changed across coder/tester/planner | — |
| 2026-08-26 | Tester (Steps 38-39) | Stale proxy-state.json cleanup fix applied; 6 dead old-CLI test functions deleted. Suite still 64/64 PASS | — |
| 2026-08-26 | Planner (Steps 36-37) | CLAUDE.md Gotchas entry for plain keys file support added; passphrase pipe protocol updated. README.md Keys file format section added with encrypted vs plain options, auto-detection, JSON example, and Windows ACL note. Quick start bullets and PROXY_KEYS_PATH env-var row updated | — |
| 2026-08-26 | Spec revision (/update-plan) | Steps 38-39 added: stale proxy-state.json cleanup fix + delete 6 dead old-CLI test functions. Report files reconciled (report-state-reconciliation, cli-start-tests-unregistered-and-failing, admin-switch-test-stub status fields updated to Resolved) | — |
| 2026-08-26 | Tester round 5 | Steps 18-35a COMPLETED: 64/64 PASS. All 18 new/rewritten tests pass. Three pre-existing issues resolved (cli-start-tests-unregistered-and-failing, admin-switch-test-stub, test-step-flakiness-and-count-vs-stub-tests). Steps 36-37 (docs) remain for planner | [tester-2026-08-26](./tmp/reports/2026-08-25-fix-windows-readiness-probe-tester-2026-08-26.json) |
| 2026-08-26 | Spec revision (/update-plan) | Step 21 assertion list fixed (removed non-deterministic "force-killing" and "proxy-state.json removed" lines); detailed tester guidance added for all 18 steps (18-35a) with exact code patterns, error messages, and edge-case notes | — |
| 2026-08-26 | Mega-audit | 16 High, 13 Medium, 15 Low findings; verdict: plan needs revision | [mega-audit-2026-08-26](./tmp/reports/2026-08-25-fix-windows-readiness-probe-mega-audit-2026-08-26.json) |
| 2026-08-26 | Spec revision (/update-plan) | Part C revised: all 16 High findings addressed — test bodies rewritten for current CLI (no URL-swap/lock assertions), passphrase default kept, agent boundaries fixed (coder=source, tester=tests, planner=docs), magic detection standardized on startswith, plain-keys warning added, --passphrase-file added to CLI, VimCrypt~ prefix rejection added | — |
| 2026-08-26 | Spec revision (/update-plan) | Part C added (Steps 16-37): plain keys file support + 18 test fixes/implementations to resolve the two pre-existing issues (cli-start-tests-unregistered-and-failing, admin-switch-test-stub) | — |
| 2026-08-26 | Spec revision (/update-plan) | Coder round 8 (Steps 10/12 fix) + tester round 4 (60/60 SUCCESS); count-tokens-retry-control-plan-contradictions resolved; report files reconciled; plan COMPLETE | — |
| 2026-08-25 | Spec revision (/update-plan) | All 8 steps complete; coder round 6 (Step 8a), tester round 2 (53/53 pass); models-tier-keyed-docs-and-template resolved | — |
| 2026-08-25 | Spec revision (/update-plan) | README.md updated by planner (provider-keyed models); config-template.json still needs coder | — |
| 2026-08-25 | Mega-audit | 3 High, 12 Medium, 12 Low findings; verdict: plan needs revision | [mega-audit](./tmp/reports/2026-08-25-fix-windows-readiness-probe-mega-audit-2026-08-25.json) |
| 2026-08-25 | Spec revision (/update-plan) | Added Step 7: record actual upstream model name in trace log `model` field | — |
| 2026-08-25 | Spec revision (/update-plan) | Added Steps 5–6: fix `_config_path` not-global bug in server.py; rename admin buttons to Apply/Reload | — |
| 2026-08-25 | Spec revision (/update-plan) | Added Step 4: reverse tier display order to opus→sonnet→haiku per user request | — |
| 2026-08-25 | Spec revision (/update-plan) | Step 3 completed by coder: admin model dropdown now uses provider-keyed models; all 3 steps done | — |
| 2026-08-25 | Spec revision (/update-plan) | Added Step 3: fix admin page model dropdown to use provider-keyed models | — |
| 2026-08-25 | Spec revision (/update-plan) | Reassigned Step 2 (CLAUDE.md edit) from coder to planner; executed Step 2; both steps complete | [step2-doc-work](./tmp/reports/2026-08-25-fix-windows-readiness-probe-step2-doc-work.json) |
| 2026-08-25 | Initial plan | 2-step fix: replace select-based readiness loop with thread-based reader; update CLAUDE.md | — |

## Final Results

**Status:** COMPLETED
**Completion date:** 2026-08-26
**Files changed:** 7

| File | Agent | Change |
|------|-------|--------|
| `src/claude_retry_proxy/cli.py` | coder | Thread-based READY detection, plain keys detection, `--passphrase-file`, conditional passphrase piping |
| `src/claude_retry_proxy/server.py` | coder | `load_keys_file` (plain+encrypted), `_config_path` global fix, `disable_retry_claude_count_token`, retry message enrichment, trace model field fix, admin validation |
| `src/claude_retry_proxy/admin.html` | coder | Provider-keyed model dropdown, tier order (opus→sonnet→haiku), button rename (Apply/Reload) |
| `src/claude_retry_proxy/config-template.json` | coder | Provider-keyed models, `disable_retry_claude_count_token: true` |
| `tests/test_claude_proxy.py` | tester | 18 new/rewritten tests (4 CLI + 14 admin/CLI stubs), plain keys test infrastructure, 6 dead old-CLI tests deleted, stale state cleanup fix. Total: 64 tests, all PASS |
| `CLAUDE.md` | planner | Two-phase readiness protocol, `disable_retry_claude_count_token` gotcha, plain keys file gotcha, passphrase pipe protocol update |
| `README.md` | planner | Provider-keyed models, keys file format section, `disable_retry_claude_count_token` docs, env var updates |

**Test results:** 64 passed, 0 failed, 0 skipped (64 total)

**Issues resolved:** 10

| Issue | Resolved by |
|-------|-------------|
| `test-step-flakiness-and-count-vs-stub-tests` | tester (Step 21 fix verified) |
| `cli-start-tests-unregistered-and-failing` | tester (4 tests rewritten + registered) |
| `admin-switch-test-stub` | tester (14 stubs implemented) |
| `report-state-reconciliation` | planner (report files reconciled) |
| `count-tokens-retry-control-plan-contradictions` | tester (TDD verified) |
| `steps14-15-doc-work` | planner (docs verified) |
| `no-retry-paths-mega-audit` | planner |
| `models-tier-keyed-docs-and-template` | coder + tester |
| `mega-audit-missing-tests` | tester |
| `config-path-not-global` | coder |
| `admin-models-tier-keyed` | coder |
| `step2-doc-work` | planner |

**Warnings:** 1 (No `proxy_stop` trace event — expected on abrupt termination)