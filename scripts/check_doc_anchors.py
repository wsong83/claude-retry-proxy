#!/usr/bin/env python3
"""Committed checker: doc-anchor resolution and secret-shape scanning.

Two checks the committed doc-structure gate does NOT perform:

  1. ANCHOR RESOLUTION. doc_structure_check.py validates that <a href> values
     are RELATIVE, but never that the target file exists or that a #fragment
     resolves to a real id attribute. Every doc/<page>.html#<anchor> pointer in
     CLAUDE.md, README.md, and the doc/ pages themselves is resolved here.
     Fragment ids must match [A-Za-z0-9_-]+ (they are matched case-sensitively
     against the page's id="..." attribute values).

  2. SECRET SHAPES. This repo is public. The doc pages document the keys-file
     and config schemas, so a copied real credential would be published. Only
     HIGH-CONFIDENCE patterns fail the check; see ALLOWED_HOSTS below for the
     placeholder-host allowlist.

Exit codes:
    0 = pass
    1 = failures found
    2 = abnormal run state (no doc/ tree found under the given root, or no
        referrer files CLAUDE.md/README.md under root — a zero-referrer run
        must never report a vacuous PASS — or internal error).

ALLOWED_HOSTS maintenance contract: when new example URLs appear in the doc/
pages, either use a reserved-TLD host (.invalid/.test/.example — any
subdomain of those is a placeholder by construction) or add the real
hostname to ALLOWED_HOSTS deliberately, with a comment saying why. Any
unlisted real-TLD host is reported as a failure.

This script does NOT re-implement any doc-structure rule. Those are the
personal gate's job (~/.claude/scripts/doc_structure_check.py) and
duplicating them is a rule violation, not a convenience. It also does NOT
run the suite — tests/test_docs.py drives run() as the permanent
regression net over the real tree.

Standalone, stdlib only, cross-platform. Run from the repository root:
    python scripts/check_doc_anchors.py [root]
"""

import os
import re
import sys

DOC_DIR = "doc"
# Files whose doc/*.html#anchor references are resolved against the doc tree.
REFERRERS = ["CLAUDE.md", "README.md"]

# Hostnames that may appear in an example URL. Anything else in a URL is
# reported — the repo is public and example configs are the likeliest place a
# real provider hostname leaks.
ALLOWED_HOSTS = {
    "localhost", "127.0.0.1", "::1", "[::1]",
    "api.anthropic.com",          # the real Anthropic API, documented on purpose
}
# Hosts under a reserved TLD (RFC 2606 / RFC 6761) can never resolve, so any
# subdomain of them is a placeholder by construction — this is what makes
# "api.example.invalid" safe to show in an example without an allowlist entry
# per invented hostname.
ALLOWED_HOST_SUFFIXES = (
    ".invalid", ".test", ".example", ".localhost", "example.com", "example.org",
)

# High-confidence credential shapes. Deliberately narrow: a broad "long random
# string" rule would flag CSS class names and hex colours.
SECRET_PATTERNS = [
    ("anthropic/openai-style key", re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}")),
    ("bearer token literal", re.compile(r"\bBearer\s+[A-Za-z0-9_\-\.]{24,}")),
    ("aws access key id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("google api key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("github token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}")),
    ("private key header", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
]

# A credential-shaped match is only a finding if it does NOT advertise itself
# as a placeholder. Documentation legitimately shows shapes like
# "sk-ant-api03-your-key-here"; flagging those would make the check useless
# noise and train the reader to ignore it.
PLACEHOLDER_MARKERS = (
    "YOUR", "PLACEHOLDER", "EXAMPLE", "REPLACE", "SAMPLE",
    "XXXX", "TODO", "FAKE", "DUMMY", "REDACTED", "CHANGEME",
)

URL_RE = re.compile(r"https?://([A-Za-z0-9\.\-]+)")

# Two reference forms, because the doc/ tree is reached two ways:
#   * repo-root files (CLAUDE.md, README.md) write "doc/page.html#frag"
#   * pages inside doc/ write the bare "page.html#frag" (relative sibling)
# The lookbehind on the bare form stops it re-matching the tail of a
# "doc/page.html#frag" reference (whose "page.html" is preceded by "/").
ANCHOR_REF_ROOT_RE = re.compile(
    r"\b(doc/[A-Za-z0-9_\-]+\.html)#([A-Za-z0-9_\-]+)")
ANCHOR_REF_DOC_RE = re.compile(
    r"(?<![/\w.\-])([A-Za-z0-9_\-]+\.html)#([A-Za-z0-9_\-]+)")
ID_RE = re.compile(r'\bid="([^"]+)"')


def read(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None


def collect_doc_files(root):
    doc = os.path.join(root, DOC_DIR)
    if not os.path.isdir(doc):
        return []
    out = []
    for name in sorted(os.listdir(doc)):
        full = os.path.join(doc, name)
        if os.path.isfile(full) and name.lower().endswith(".html"):
            out.append(full)
    return out


def check_anchors(root, doc_files, failures):
    """Resolve every doc/<page>.html#<frag> reference found in the referrers
    plus the doc pages themselves."""
    ids_by_file = {}
    for full in doc_files:
        text = read(full) or ""
        ids_by_file["doc/" + os.path.basename(full)] = set(ID_RE.findall(text))

    checked = 0

    # Repo-root referrers: "doc/page.html#frag"
    for rel in REFERRERS:
        full = os.path.join(root, rel)
        if not os.path.isfile(full):
            continue
        text = read(full) or ""
        for target, frag in ANCHOR_REF_ROOT_RE.findall(text):
            checked += 1
            if target not in ids_by_file:
                failures.append(
                    "%s: references missing file '%s'" % (rel, target))
                continue
            if frag not in ids_by_file[target]:
                failures.append(
                    "%s: '#%s' does not resolve in %s" % (rel, frag, target))

    # doc/ pages referring to their own siblings: "page.html#frag"
    for full in doc_files:
        rel = "doc/" + os.path.basename(full)
        text = read(full) or ""
        for target, frag in ANCHOR_REF_DOC_RE.findall(text):
            checked += 1
            key = "doc/" + target
            if key not in ids_by_file:
                failures.append(
                    "%s: references missing file '%s'" % (rel, target))
                continue
            if frag not in ids_by_file[key]:
                failures.append(
                    "%s: '#%s' does not resolve in %s" % (rel, frag, target))

    # Bare sibling links (no fragment) must also point at a file that exists —
    # a dangling link is the same defect class as a dangling anchor.
    for full in doc_files:
        rel = "doc/" + os.path.basename(full)
        text = read(full) or ""
        for m in re.finditer(r'href="([A-Za-z0-9_\-]+\.html)"', text):
            checked += 1
            if "doc/" + m.group(1) not in ids_by_file:
                failures.append(
                    "%s: links to missing file '%s'" % (rel, m.group(1)))

    # The same for README/CLAUDE.md, which reach the tree as "doc/page.html".
    # The lookahead skips fragment-bearing refs — those were checked above, and
    # counting them twice would inflate the reported total.
    for rel in REFERRERS:
        full = os.path.join(root, rel)
        if not os.path.isfile(full):
            continue
        text = read(full) or ""
        for m in re.finditer(r"doc/([A-Za-z0-9_\-]+\.html)(?!#)", text):
            checked += 1
            if "doc/" + m.group(1) not in ids_by_file:
                failures.append(
                    "%s: links to missing file 'doc/%s'" % (rel, m.group(1)))

    return checked


def check_secrets(root, doc_files, failures):
    scanned = 0
    for full in doc_files:
        text = read(full) or ""
        rel = os.path.relpath(full, root).replace(os.sep, "/")
        scanned += 1
        for label, pat in SECRET_PATTERNS:
            for m in pat.finditer(text):
                hit = m.group(0)
                if any(mk in hit.upper() for mk in PLACEHOLDER_MARKERS):
                    continue
                failures.append("%s: possible %s: %s..." % (
                    rel, label, hit[:24]))
        for host in URL_RE.findall(text):
            h = host.split(":")[0].lower()
            if h in ALLOWED_HOSTS:
                continue
            if h.endswith(ALLOWED_HOST_SUFFIXES):
                continue
            failures.append(
                "%s: non-placeholder hostname in URL: %s" % (rel, host))
    return scanned


def run(root):
    """Run both checks under `root`.

    Returns (status, failures, anchors_checked, secrets_scanned) where
    status is "ok" (checks ran), "no-tree" (no doc/ directory under root),
    or "no-referrers" (no CLAUDE.md/README.md under root — a zero-referrer
    run must never report a vacuous PASS). Both abnormal statuses map to
    exit code 2 in main().
    """
    doc_files = collect_doc_files(root)
    if not doc_files:
        return ("no-tree", [], 0, 0)

    referrers_present = any(
        os.path.isfile(os.path.join(root, rel)) for rel in REFERRERS)
    if not referrers_present:
        return ("no-referrers", [], 0, 0)

    failures = []
    anchors = check_anchors(root, doc_files, failures)
    secrets_scanned = check_secrets(root, doc_files, failures)
    return ("ok", failures, anchors, secrets_scanned)


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]
    root = argv[0] if argv else os.getcwd()
    status, failures, anchors, secrets_scanned = run(root)

    if status == "no-tree":
        print("No doc/ tree found under %s" % root)
        return 2
    if status == "no-referrers":
        print("No referrer files (%s) found under %s"
              % (", ".join(REFERRERS), root))
        return 2

    if failures:
        print("## Doc Verification: FAIL")
        for f in failures:
            print("  FAIL " + f)
        print("- %d anchor reference(s) checked" % anchors)
        print("- %d html file(s) scanned for secrets" % secrets_scanned)
        print("- %d failure(s)" % len(failures))
        return 1

    print("## Doc Verification: PASS")
    print("- %d anchor reference(s) resolved" % anchors)
    print("- %d html file(s) scanned for secrets" % secrets_scanned)
    print("- no unresolved anchors, no secret shapes")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # internal error, not a content failure
        print("internal error: %r" % (exc,), file=sys.stderr)
        sys.exit(2)
