"""Redaction chokepoint for error text reaching stderr, trace `error` fields, and client-facing error bodies."""

import re

# IGNORECASE: Windows paths (the class issue #4 is about) are case-insensitive,
# so a capitalized dotdir (.CLAUDE) is still a sensitive segment.
_SENSITIVE_SEGMENT_RE = re.compile(
    r"[\\/]\.(?:claude|ssh|gnupg|aws|azure|config|local)\b", re.IGNORECASE)


def sanitize_error(msg):
    """Redact sensitive home-directory paths and IPv4 addresses from error text.

    Path redaction runs on whitespace- and double-quote-delimited tokens: a
    token containing a separator-prefixed sensitive dotdir segment (`.claude`,
    `.ssh`, `.gnupg`, `.aws`, `.azure`, `.config`, `.local`, any casing) is
    replaced whole. The token scan is linear in the input length — no nested
    quantifiers — so adversarial error text cannot trigger exponential
    backtracking. A message object whose `__str__` itself raises propagates:
    every internal caller passes an already-`str()`-ed exception, and any
    future direct caller must guard accordingly.
    """
    if not msg:
        return None
    msg = str(msg)
    msg = "".join(
        "[redacted-path]" if _SENSITIVE_SEGMENT_RE.search(part) else part
        for part in re.split(r'(\s+|")', msg))
    msg = re.sub(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b",
                 "[redacted-ip]", msg)
    return msg[:200]
