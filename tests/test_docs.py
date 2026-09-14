"""Doc-anchor checker tests: the committed scripts/check_doc_anchors.py.

The real-tree case is the regression net for every CLAUDE.md/README.md/doc
anchor. The planted-failure cases build one temp doc tree per failure class
and assert the checker reports exactly that class (and only it). The CLI case
pins the 0/1/2 exit-code mapping.

Part of the claude-retry-proxy suite; runnable standalone.
"""

import importlib.util
import os
import subprocess
import sys
import tempfile

from _harness import (
    fail,
    pass_,
    run_cli,
)


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHECKER_PATH = os.path.join(REPO_ROOT, "scripts", "check_doc_anchors.py")

_spec = importlib.util.spec_from_file_location("check_doc_anchors", CHECKER_PATH)
if _spec is None or _spec.loader is None:
    raise ImportError("cannot load checker script: %s" % CHECKER_PATH)
_checker = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_checker)
run = _checker.run


# The sample credential shape used by the planted secret cases. The sk- pattern
# requires a >= 20-char tail after "sk-" — a short sample would not match at all
# and the cases would pass for the wrong reason.
SECRET_NO_MARKER = "sk-ant-api03-abcdefghijklmnopqrstuvwx"
SECRET_WITH_MARKER = "sk-ant-api03-YOUR-KEY-PLACEHOLDER"

# Stub URL vocabulary: allowlisted and reserved-TLD hosts only, so no
# non-secret case trips an unintended second failure class.
CLEAN_URLS = ("<p>See https://api.anthropic.com/v1 and "
              "https://myco.invalid/api and http://localhost:8080/x.</p>")


def _make_tree(base, refs, pages):
    """Build a stub doc tree under `base` and return it.

    `base` is the path of the caller's TemporaryDirectory, so the whole tree
    (refs and the doc/ pages) is removed when the caller's context exits.
    refs: {filename: text} written at the root; pages: {doc filename: text}
    written under a doc/ directory.
    """
    root = base
    doc = os.path.join(root, "doc")
    os.makedirs(doc, exist_ok=True)
    for name, text in refs.items():
        with open(os.path.join(root, name), "w", encoding="utf-8") as f:
            f.write(text)
    for name, text in pages.items():
        with open(os.path.join(doc, name), "w", encoding="utf-8") as f:
            f.write(text)
    return root


def _assert_single_class(t_name, result, status, needle):
    """Assert run() returned `status`, exactly one failure, containing `needle`.

    Returns True on success after having recorded the assertion outcome.
    """
    st, failures, anchors, secrets = result
    if st != status:
        fail("%s: status is %r, expected %r" % (t_name, st, status))
        return False
    if len(failures) != 1:
        fail("%s: expected exactly 1 failure, got %d: %r"
             % (t_name, len(failures), failures))
        return False
    if needle not in failures[0]:
        fail("%s: failure %r does not match class %r" % (t_name, failures[0], needle))
        return False
    pass_("%s: single class reported -> %s" % (t_name, failures[0]))
    return True


def _assert_no_failures(t_name, result, status="ok"):
    st, failures, anchors, secrets = result
    if st != status:
        fail("%s: status is %r, expected %r" % (t_name, st, status))
        return False
    if failures:
        fail("%s: expected zero failures, got %r" % (t_name, failures))
        return False
    pass_("%s: no failures" % t_name)
    return True


# ---------------------------------------------------------------------------
# Real tree
# ---------------------------------------------------------------------------

def doc_real_tree_success():
    """The committed checker passes on the real repo tree.

    anchors_checked >= 1 so a referrer wipe cannot silently green: losing the
    referrer files (the isfile guard skips them silently) must fail this floor.
    """
    print("\n--- Test: Doc checker real-tree success ---")
    result = run(REPO_ROOT)
    if not isinstance(result, tuple) or len(result) != 4:
        fail("run() must return a 4-tuple, got %r" % (result,))
        return
    status, failures, anchors, secrets = result
    if status != "ok":
        fail("status is %r, expected 'ok'" % status)
        return
    if failures:
        fail("expected zero failures, got %r" % failures)
        return
    if not isinstance(anchors, int) or anchors < 1:
        fail("anchors_checked must be >= 1, got %r" % anchors)
        return
    if not isinstance(secrets, int) or secrets < 1:
        fail("secrets_scanned must be >= 1, got %r" % secrets)
        return
    pass_("real tree: status ok, %d anchors checked, %d pages scanned"
          % (anchors, secrets))


# ---------------------------------------------------------------------------
# Planted-failure suite: one temp tree per failure class
# ---------------------------------------------------------------------------

def doc_missing_anchor_file():
    """A referrer anchor to a missing doc page is flagged."""
    print("\n--- Test: Doc checker missing anchor file ---")
    with tempfile.TemporaryDirectory() as root:
        _make_tree(root,
            {"CLAUDE.md": "See [x](doc/ghost.html#x).\n", "README.md": "Stub.\n"},
            {"page.html": "<html><body><h1 id=\"top\">p</h1></body></html>"})
        _assert_single_class(
            "doc-missing-anchor-file", run(root), "ok",
            "CLAUDE.md: references missing file 'doc/ghost.html'")


def doc_missing_fragment():
    """A referrer fragment not matching any id on an existing page is flagged."""
    print("\n--- Test: Doc checker missing fragment ---")
    with tempfile.TemporaryDirectory() as root:
        _make_tree(root,
            {"CLAUDE.md": "See [x](doc/page.html#nosuch).\n", "README.md": "Stub.\n"},
            {"page.html": "<html><body><h1 id=\"top\">p</h1></body></html>"})
        _assert_single_class(
            "doc-missing-fragment", run(root), "ok",
            "CLAUDE.md: '#nosuch' does not resolve in doc/page.html")


def doc_missing_bare_doc_link():
    """A referrer bare doc/page.html link (no fragment) to a missing page is flagged."""
    print("\n--- Test: Doc checker missing bare doc link ---")
    with tempfile.TemporaryDirectory() as root:
        _make_tree(root,
            {"CLAUDE.md": "See [x](doc/ghost.html).\n", "README.md": "Stub.\n"},
            {"page.html": "<html><body><h1 id=\"top\">p</h1></body></html>"})
        _assert_single_class(
            "doc-missing-bare-doc-link", run(root), "ok",
            "CLAUDE.md: links to missing file 'doc/ghost.html'")


def doc_page_sibling_anchor_miss():
    """A doc page's sibling anchor to a missing fragment is flagged."""
    print("\n--- Test: Doc checker sibling anchor miss ---")
    with tempfile.TemporaryDirectory() as root:
        _make_tree(root,
            {"CLAUDE.md": "Stub.\n", "README.md": "Stub.\n"},
            {"page1.html": "<html><body><p>See "
                           "<a href=\"page2.html#missing\">y</a>.</p></body></html>",
             "page2.html": "<html><body><h1 id=\"top\">p</h1></body></html>"})
        _assert_single_class(
            "doc-page-sibling-anchor-miss", run(root), "ok",
            "doc/page1.html: '#missing' does not resolve in page2.html")


def doc_page_bare_href_missing():
    """A doc page's bare sibling href to a missing page is flagged."""
    print("\n--- Test: Doc checker bare sibling href missing ---")
    with tempfile.TemporaryDirectory() as root:
        _make_tree(root,
            {"CLAUDE.md": "Stub.\n", "README.md": "Stub.\n"},
            {"page1.html": "<html><body><p>See <a href=\"ghost.html\">y</a>.</p>"
                           "</body></html>"})
        _assert_single_class(
            "doc-page-bare-href-missing", run(root), "ok",
            "doc/page1.html: links to missing file 'ghost.html'")


def doc_secret_without_marker():
    """A credential-shaped string without a placeholder marker is flagged."""
    print("\n--- Test: Doc checker secret without marker ---")
    with tempfile.TemporaryDirectory() as root:
        _make_tree(root,
            {"CLAUDE.md": "Stub.\n", "README.md": "Stub.\n"},
            {"page.html": "<html><body><p>Key shape: %s.</p>%s</body></html>"
                          % (SECRET_NO_MARKER, CLEAN_URLS)})
        _assert_single_class(
            "doc-secret-without-marker", run(root), "ok",
            "possible anthropic/openai-style key")


def doc_secret_with_marker():
    """The same credential shape with a placeholder marker is not flagged."""
    print("\n--- Test: Doc checker secret with marker ---")
    with tempfile.TemporaryDirectory() as root:
        _make_tree(root,
            {"CLAUDE.md": "Stub.\n", "README.md": "Stub.\n"},
            {"page.html": "<html><body><p>Key shape: %s.</p>%s</body></html>"
                          % (SECRET_WITH_MARKER, CLEAN_URLS)})
        _assert_no_failures("doc-secret-with-marker", run(root))


def doc_url_host_disallowed():
    """A URL whose host is neither allowlisted nor reserved-TLD is flagged."""
    print("\n--- Test: Doc checker disallowed URL host ---")
    with tempfile.TemporaryDirectory() as root:
        _make_tree(root,
            {"CLAUDE.md": "Stub.\n", "README.md": "Stub.\n"},
            {"page.html": "<html><body><p>Endpoint: "
                          "https://acme.com/v1/example.</p></body></html>"})
        _assert_single_class(
            "doc-url-host-disallowed", run(root), "ok",
            "non-placeholder hostname in URL: acme.com")


def doc_url_host_allowed():
    """Allowlisted and reserved-TLD URL hosts are not flagged."""
    print("\n--- Test: Doc checker allowed URL hosts ---")
    with tempfile.TemporaryDirectory() as root:
        _make_tree(root,
            {"CLAUDE.md": "Stub.\n", "README.md": "Stub.\n"},
            {"page.html": "<html><body><h1 id=\"top\">p</h1>%s</body></html>"
                          % CLEAN_URLS})
        _assert_no_failures("doc-url-host-allowed", run(root))


# ---------------------------------------------------------------------------
# CLI exit-code mapping (subprocess)
# ---------------------------------------------------------------------------

def doc_cli_exit_codes():
    """main() maps: healthy tree -> 0, failures -> 1, abnormal status -> 2."""
    print("\n--- Test: Doc checker CLI exit codes ---")

    def run_cli_on(root):
        return subprocess.run(
            [sys.executable, CHECKER_PATH, root],
            capture_output=True, text=True, timeout=30)

    proc = run_cli_on(REPO_ROOT)
    if proc.returncode != 0:
        fail("real tree: exit %d, expected 0. Output: %s" % (proc.returncode, proc.stdout))
        return
    if "## Doc Verification: PASS" not in proc.stdout:
        fail("real tree: missing PASS banner. Output: %r" % proc.stdout)
        return

    with tempfile.TemporaryDirectory() as root:
        _make_tree(root,
            {"CLAUDE.md": "See [x](doc/ghost.html#x).\n", "README.md": "Stub.\n"},
            {"page.html": "<html><body><h1 id=\"top\">p</h1></body></html>"})
        proc = run_cli_on(root)
        if proc.returncode != 1:
            fail("failing tree: exit %d, expected 1. Output: %s" % (proc.returncode, proc.stdout))
            return
        if "## Doc Verification: FAIL" not in proc.stdout:
            fail("failing tree: missing FAIL banner. Output: %r" % proc.stdout)
            return

    with tempfile.TemporaryDirectory() as root:
        proc = run_cli_on(root)
        if proc.returncode != 2:
            fail("no-tree root: exit %d, expected 2. Output: %s" % (proc.returncode, proc.stdout))
            return
        if "No doc/ tree found" not in proc.stdout:
            fail("no-tree root: missing message. Output: %r" % proc.stdout)
            return

    with tempfile.TemporaryDirectory() as root:
        _make_tree(root,{}, {"page.html": "<p>x</p>"})
        proc = run_cli_on(root)
        if proc.returncode != 2:
            fail("no-referrers root: exit %d, expected 2. Output: %s" % (proc.returncode, proc.stdout))
            return
        if "No referrer files" not in proc.stdout:
            fail("no-referrers root: missing message. Output: %r" % proc.stdout)
            return

    pass_("CLI exit codes 0/1/2 verified")


ALL_TESTS = [
    ("doc-real-tree-success", doc_real_tree_success),
    ("doc-missing-anchor-file", doc_missing_anchor_file),
    ("doc-missing-fragment", doc_missing_fragment),
    ("doc-missing-bare-doc-link", doc_missing_bare_doc_link),
    ("doc-page-sibling-anchor-miss", doc_page_sibling_anchor_miss),
    ("doc-page-bare-href-missing", doc_page_bare_href_missing),
    ("doc-secret-without-marker", doc_secret_without_marker),
    ("doc-secret-with-marker", doc_secret_with_marker),
    ("doc-url-host-disallowed", doc_url_host_disallowed),
    ("doc-url-host-allowed", doc_url_host_allowed),
    ("doc-cli-exit-codes", doc_cli_exit_codes),
]


if __name__ == "__main__":
    run_cli(ALL_TESTS, "claude-retry-proxy tests: test_docs")
