"""Unit tests for the config.json / models.json document pair (plan
2026-09-23-config-models-json-split).

Direct-import, no subprocess, no server. Covers the loader contract at the
module level: the merged load of the document pair, the ValueError
conversion of every unreadable or malformed shape of either document
(malformed JSON, a directory in place of the file, invalid UTF-8, and
unreadable-by-permissions where the platform can express it), the
leftover-key warning precedence, the sibling models.json resolution rule,
and the CLI-side _load_config_for_validation parity.

Filesystem mutations use tempfile.mkdtemp and shutil.rmtree in finally.
The unreadable-permissions shape is attempted and self-verified: if the
platform cannot actually deny the read (Windows chmod is a near-no-op),
the shape is reported as not expressible rather than asserted.

Part of the claude-retry-proxy suite; runnable standalone.
"""

import contextlib
import io
import json
import os
import shutil
import stat
import sys
import tempfile

from _harness import (
    fail,
    pass_,
    run_cli,
)

from claude_retry_proxy import config


TIERS = {
    "haiku": {"provider": "p", "model": "claude-haiku-4-5"},
    "sonnet": {"provider": "p", "model": "claude-sonnet-5"},
    "opus": {"provider": "p", "model": "claude-opus-5"},
}


def _write_pair(temp_dir, tiers=TIERS, models_doc=None, config_doc=None):
    """Write a config.json / models.json pair.

    models_doc: dict body of models.json (required unless deliberately
    omitted via models_doc=None AND write_models=False callers build it
    themselves). config_doc: full config.json body override.
    """
    if config_doc is None:
        config_doc = {"tiers": tiers}
    cpath = os.path.join(temp_dir, "config.json")
    with open(cpath, "w", encoding="utf-8") as f:
        json.dump(config_doc, f)
    mpath = config.models_path_for(cpath)
    if models_doc is not None:
        with open(mpath, "w", encoding="utf-8") as f:
            json.dump(models_doc, f)
    return cpath, mpath


def _check(cond, name, detail=""):
    if cond:
        pass_(name)
    else:
        fail("{}: {}".format(name, detail))


def test_models_path_for_sibling_resolution():
    """models_path_for resolves the sibling beside the abspath of the
    config path — a bare filename must resolve against cwd, not an empty
    dirname (the loader's abspath is load-bearing)."""
    print("\n--- Test: models_path_for Sibling Resolution ---")
    temp_dir = tempfile.mkdtemp(prefix="proxy_split_res_")
    old_cwd = os.getcwd()
    try:
        cpath, mpath = _write_pair(
            temp_dir, models_doc={"models": {"p": ["claude-haiku-4-5"]}})
        expected = os.path.join(os.path.abspath(temp_dir), "models.json")
        _check(config.models_path_for(cpath) == expected,
               "absolute config path -> sibling in same dir",
               "got {}".format(config.models_path_for(cpath)))

        # Bare filename resolves against cwd (not an empty dirname).
        os.chdir(temp_dir)
        got = config.models_path_for("config.json")
        _check(os.path.isabs(got) and got.endswith("models.json"),
               "bare filename resolves absolutized",
               "got {}".format(got))

        # The loader reads the sibling beside the given path: a different
        # catalog in the default location is not consulted (we point at a
        # temp dir whose sibling we wrote, and merge reflects it).
        merged = config.load_config(cpath)
        _check(merged.get("models") == {"p": ["claude-haiku-4-5"]},
               "loader reads sibling beside --config-path",
               "got models={!r}".format(merged.get("models")))
    finally:
        os.chdir(old_cwd)
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_merged_load_with_optional_keys():
    """A valid pair merges: tiers from config.json, models and
    extra_request_headers from models.json; a flag set in models.json
    survives the merge."""
    print("\n--- Test: Merged Load ---")
    temp_dir = tempfile.mkdtemp(prefix="proxy_split_merge_")
    try:
        cpath, _ = _write_pair(
            temp_dir,
            models_doc={"models": {"p": ["claude-haiku-4-5", "claude-sonnet-5"]},
                        "extra_request_headers": {"p": {"X-Flag": {"from": "x-pl"}}},
                        "disable_retry_claude_count_token": True})
        merged = config.load_config(cpath)
        _check(merged.get("tiers") == TIERS, "tiers merged from config.json",
               "got {!r}".format(merged.get("tiers")))
        _check(merged.get("models") ==
               {"p": ["claude-haiku-4-5", "claude-sonnet-5"]},
               "models merged from models.json",
               "got {!r}".format(merged.get("models")))
        _check(merged.get("extra_request_headers") is not None,
               "extra_request_headers merged from models.json",
               "got {!r}".format(merged.get("extra_request_headers")))
        _check(merged.get("disable_retry_claude_count_token") is True,
               "flag present in the merged dict",
               "got {!r}".format(merged.get("disable_retry_claude_count_token")))
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_missing_models_json_is_value_error_naming_path():
    """A missing models.json is a ValueError (not FileNotFoundError — the
    server's startup handler would misreport it as 'Config file not
    found: <config path>') whose message names models.json, the resolved
    sibling path, and carries 'not found'."""
    print("\n--- Test: Missing models.json Is ValueError ---")
    temp_dir = tempfile.mkdtemp(prefix="proxy_split_miss_")
    try:
        cpath, _ = _write_pair(temp_dir, models_doc=None)
        raised = None
        try:
            config.load_config(cpath)
        except Exception as e:
            raised = e
        if isinstance(raised, ValueError):
            pass_("missing models.json -> ValueError")
        elif isinstance(raised, FileNotFoundError):
            fail("missing models.json raised FileNotFoundError, not ValueError "
                 "(misreported by the server as 'Config file not found')")
            return
        else:
            fail("expected ValueError, got {!r}".format(raised))
            return
        msg = str(raised)
        if "models.json" in msg and "not found" in msg:
            pass_("message names models.json and 'not found'")
        else:
            fail("message must name models.json and 'not found': {!r}".format(msg))
        _check(temp_dir in msg or os.path.abspath(temp_dir) in msg,
               "message carries the resolved sibling path",
               "msg={!r}".format(msg))
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_models_doc_bad_shapes_collapse_to_value_error():
    """Malformed JSON, a directory in place of models.json, and invalid
    UTF-8 bytes all collapse to ValueError naming models.json; so do the
    structural shapes (not an object, missing 'models', 'models' not an
    object, non-object extra_request_headers)."""
    print("\n--- Test: models.json Bad Shapes -> ValueError ---")
    temp_dir = tempfile.mkdtemp(prefix="proxy_split_shapes_")
    try:
        cpath, mpath = _write_pair(temp_dir, models_doc=None)

        def expect_value_error(body_writer, shape_name, fragment):
            if os.path.exists(mpath):
                if os.path.isdir(mpath):
                    import stat as _stat
                    os.rmdir(mpath)
                else:
                    os.remove(mpath)
            body_writer()
            try:
                config.load_config(cpath)
            except ValueError as e:
                msg = str(e)
                pass_(shape_name + " -> ValueError")
                if "models.json" in msg:
                    pass_(shape_name + ": message names models.json")
                else:
                    fail(shape_name + ": message must name models.json: "
                         "{!r}".format(msg))
                if fragment in msg:
                    pass_(shape_name + ": message carries the expected fragment")
                else:
                    fail(shape_name + ": message must carry {!r}: {!r}".format(
                        fragment, msg))
            except Exception as e:
                fail(shape_name + ": expected ValueError, got {!r}".format(e))
            else:
                fail(shape_name + ": loader succeeded; expected ValueError")

        expect_value_error(
            lambda: open(mpath, "w", encoding="utf-8").write("{not json"),
            "malformed JSON", "not valid JSON")

        expect_value_error(
            lambda: os.makedirs(mpath, exist_ok=True),
            "directory in place of the file", "cannot be read")

        def bad_utf8():
            with open(mpath, "wb") as f:
                f.write(b'{"models": {"p": [`]}}\xa0\xff')
        expect_value_error(bad_utf8, "invalid UTF-8", "not valid")

        expect_value_error(
            lambda: _dump(mpath, ["not", "an", "object"]),
            "document not an object", "must be a JSON object")

        expect_value_error(
            lambda: _dump(mpath, {"extra_request_headers": {}}),
            "missing 'models' key", "missing 'models'")

        expect_value_error(
            lambda: _dump(mpath, {"models": ["p", "q"]}),
            "'models' not an object", "'models' must be an object")

        expect_value_error(
            lambda: _dump(mpath, {"models": {},
                                  "extra_request_headers": ["x"]}),
            "non-object extra_request_headers", "'extra_request_headers'")

        expect_value_error(
            lambda: _dump(mpath, {"models": {},
                                  "disable_retry_claude_count_token": "yes"}),
            "non-boolean count-tokens flag", "'disable_retry_claude_count_token'")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _dump(path, body):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(body, f)


def test_config_doc_bad_shapes():
    """config.json's own structural and read failures are loader-level:
    not valid JSON, invalid UTF-8, a directory in place of the file, not an
    object, missing 'tiers', and a non-object 'tiers' all raise ValueError
    naming config.json (or the value path), not an escaping OSError or a
    downstream generic validate_config error."""
    print("\n--- Test: config.json Bad Shapes -> ValueError ---")
    temp_dir = tempfile.mkdtemp(prefix="proxy_split_cfgshapes_")
    try:
        cpath, _ = _write_pair(
            temp_dir, models_doc={"models": {"p": ["claude-haiku-4-5"]}})

        def expect_value_error(body_writer, shape_name, fragment):
            if os.path.isdir(cpath):
                os.rmdir(cpath)
            else:
                os.remove(cpath)
            body_writer()
            try:
                config.load_config(cpath)
            except ValueError as e:
                msg = str(e)
                pass_(shape_name + " -> ValueError")
                if fragment in msg:
                    pass_(shape_name + ": message carries the expected fragment")
                else:
                    fail(shape_name + ": message must carry {!r}: {!r}".format(
                        fragment, msg))
            except Exception as e:
                fail(shape_name + ": expected ValueError, got {!r}".format(e))
            else:
                fail(shape_name + ": loader succeeded; expected ValueError")

        expect_value_error(
            lambda: open(cpath, "w", encoding="utf-8").write("{{oops"),
            "malformed JSON", "not valid JSON")

        def bad_utf8():
            with open(cpath, "wb") as f:
                f.write(b'\xff\xfe{"tiers": {}}')
        expect_value_error(bad_utf8, "invalid UTF-8", "not valid")

        expect_value_error(
            lambda: os.makedirs(cpath, exist_ok=True),
            "directory in place of the file", "cannot be read")

        expect_value_error(
            lambda: _dump(cpath, ["tiers"]),
            "document not an object", "must be a JSON object")

        expect_value_error(
            lambda: _dump(cpath, {"models": {}}),
            "missing 'tiers' key", "missing 'tiers'")

        expect_value_error(
            lambda: _dump(cpath, {"tiers": ["x"]}),
            "'tiers' not an object", "'tiers' must be an object")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_models_json_unreadable_permissions_shape():
    """The unreadable-by-permissions shape collapses to ValueError naming
    models.json. The chmod is self-verified first: if the platform cannot
    actually deny the read (Windows chmod is a near-no-op) the shape is
    reported as not expressible, not asserted."""
    print("\n--- Test: models.json Unreadable Permissions ---")
    temp_dir = tempfile.mkdtemp(prefix="proxy_split_perm_")
    try:
        cpath, mpath = _write_pair(
            temp_dir, models_doc={"models": {"p": ["claude-haiku-4-5"]}})
        denied = False
        try:
            os.chmod(mpath, 0o000)
            with open(mpath, "rb") as f:
                f.read()
        except (OSError, ValueError):
            denied = True
        finally:
            os.chmod(mpath, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
        if not denied:
            pass_("platform cannot express an unreadable file read "
                  "(chmod near-no-op); shape not asserted here")
            return
        try:
            config.load_config(cpath)
        except ValueError as e:
            msg = str(e)
            if "models.json" in msg:
                pass_("unreadable permissions -> ValueError naming models.json")
            else:
                fail("message must name models.json: {!r}".format(msg))
        except Exception as e:
            fail("expected ValueError, got {!r}".format(e))
        else:
            fail("load succeeded on an unreadable models.json")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_leftover_keys_warn_and_lose():
    """A leftover catalog key in config.json with a models.json present:
    load succeeds, the models.json value wins, and a stderr warning naming
    the models file is printed — captured from stderr, not stdout."""
    print("\n--- Test: Leftover Keys Warn and Lose ---")
    temp_dir = tempfile.mkdtemp(prefix="proxy_split_left_")
    try:
        cpath, _ = _write_pair(
            temp_dir,
            config_doc={"tiers": TIERS,
                        "models": {"q": ["from-config-catalog"]},
                        "extra_request_headers": {"q": {"X-Old": {"from": "x-y"}}},
                        "disable_retry_claude_count_token": False},
            models_doc={"models": {"p": ["claude-haiku-4-5"]},
                        "extra_request_headers": {"p": {"X-New": {"from": "x-n"}}},
                        "disable_retry_claude_count_token": True})
        mpath = config.models_path_for(cpath)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            merged = config.load_config(cpath)
        out = err.getvalue()
        _check(merged.get("models") == {"p": ["claude-haiku-4-5"]},
               "models.json catalog wins over the leftover",
               "got {!r}".format(merged.get("models")))
        _check(merged.get("extra_request_headers") ==
               {"p": {"X-New": {"from": "x-n"}}},
               "models.json headers win over the leftover",
               "got {!r}".format(merged.get("extra_request_headers")))
        _check(merged.get("disable_retry_claude_count_token") is True,
               "models.json flag wins over the leftover",
               "got {!r}".format(merged.get("disable_retry_claude_count_token")))
        _check("WARNING" in out and "models" in out,
               "warnings on stderr", "stderr={!r}".format(out))
        _check(mpath in out, "warning names the models path",
               "stderr={!r}".format(out))
        for key in ("models", "extra_request_headers",
                    "disable_retry_claude_count_token"):
            _check("carries a '{}' key".format(key) in out,
                   "warning names the leftover '{}' key".format(key),
                   "stderr={!r}".format(out))
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_leftover_key_dropped_warning():
    """When models.json does NOT carry a key that config.json still has,
    the warning names the drop — a policy-bearing value silently discarded
    must never be announced as being re-read from elsewhere."""
    print("\n--- Test: Dropped Leftover Key Warning ---")
    temp_dir = tempfile.mkdtemp(prefix="proxy_split_drop_")
    try:
        cpath, _ = _write_pair(
            temp_dir,
            config_doc={"tiers": TIERS,
                        "disable_retry_claude_count_token": True},
            models_doc={"models": {"p": ["claude-haiku-4-5"]}})
        mpath = config.models_path_for(cpath)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            merged = config.load_config(cpath)
        out = err.getvalue()
        _check("disable_retry_claude_count_token" not in merged,
               "dropped key absent from the merged dict",
               "merged={!r}".format(merged))
        _check("dropped" in out and mpath in out,
               "warning names the drop and the models path",
               "stderr={!r}".format(out))
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_leftover_key_no_models_json_still_fails():
    """A leftover catalog key with no models.json still fails: the warning
    path is not a bypass for the required file."""
    print("\n--- Test: Leftover Key Is Not a Bypass ---")
    temp_dir = tempfile.mkdtemp(prefix="proxy_split_nobypass_")
    try:
        cpath, _ = _write_pair(
            temp_dir,
            config_doc={"tiers": TIERS, "models": {"q": ["x"]}},
            models_doc=None)
        try:
            config.load_config(cpath)
        except ValueError as e:
            if "models.json" in str(e):
                pass_("leftover key + missing models.json still fails, "
                      "naming models.json")
            else:
                fail("error must name models.json: {!r}".format(str(e)))
        except Exception as e:
            fail("expected ValueError, got {!r}".format(e))
        else:
            fail("load succeeded; leftover key must not bypass the required file")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_load_config_for_validation():
    """_load_config_for_validation: (config, None) on a valid pair;
    (None, err) naming models.json on a missing one — the CLI path is as
    strict as the server path; path=None falls back to
    SETTINGS.config_path without raising."""
    print("\n--- Test: _load_config_for_validation ---")
    temp_dir = tempfile.mkdtemp(prefix="proxy_split_cli_")
    try:
        cpath, _ = _write_pair(
            temp_dir,
            models_doc={"models": {"p": ["claude-haiku-4-5"]}})
        got, err = config._load_config_for_validation(cpath)
        _check(err is None and got is not None and
               got.get("models") == {"p": ["claude-haiku-4-5"]},
               "valid pair -> (config, None)",
               "got {!r}, err {!r}".format(got, err))

        # Missing models.json: (None, err) naming models.json.
        os.remove(config.models_path_for(cpath))
        got, err = config._load_config_for_validation(cpath)
        _check(got is None and err is not None and "models.json" in err,
               "missing models.json -> (None, err) naming models.json",
               "got {!r}, err {!r}".format(got, err))
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    # path=None falls back to SETTINGS.config_path before sibling
    # resolution (a None would raise TypeError inside abspath).
    class _ProbeSignal(Exception):
        pass

    captured = {}
    original = config._load_config_documents

    def probe(path, *args, **kwargs):
        captured["path"] = path
        raise _ProbeSignal()

    config._load_config_documents = probe
    try:
        try:
            config._load_config_for_validation(None)
        except _ProbeSignal:
            pass_(
                "path=None resolves to SETTINGS.config_path and invokes the "
                "pair loader (no TypeError before it)")
        else:
            # validation returns (None, err) on failure and never raises
            fail("probe signal not raised; fallback did not route through "
                 "_load_config_documents (captured={!r})".format(
                     captured.get("path")))
        _check(captured.get("path") == config.SETTINGS.config_path,
               "fallback path equals SETTINGS.config_path",
               "captured={!r}".format(captured.get("path")))
    finally:
        config._load_config_documents = original


ALL_TESTS = [
    ("models-path-for-sibling-resolution", test_models_path_for_sibling_resolution),
    ("merged-load-with-optional-keys", test_merged_load_with_optional_keys),
    ("missing-models-json-is-value-error",
     test_missing_models_json_is_value_error_naming_path),
    ("models-doc-bad-shapes-collapse-to-value-error",
     test_models_doc_bad_shapes_collapse_to_value_error),
    ("config-doc-bad-shapes", test_config_doc_bad_shapes),
    ("models-doc-unreadable-permissions",
     test_models_json_unreadable_permissions_shape),
    ("leftover-keys-warn-and-lose", test_leftover_keys_warn_and_lose),
    ("leftover-key-dropped-warning", test_leftover_key_dropped_warning),
    ("leftover-key-no-models-json-still-fails",
     test_leftover_key_no_models_json_still_fails),
    ("load-config-for-validation-parity", test_load_config_for_validation),
]

if __name__ == "__main__":
    run_cli(ALL_TESTS, "config.json / models.json split loader-contract tests")
