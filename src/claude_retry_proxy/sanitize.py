"""Redaction chokepoint for error text reaching stderr, trace `error` fields, and client-facing error bodies."""

import re


def sanitize_error(msg):
    if not msg:
        return None
    msg = str(msg)
    msg = re.sub(r'(?:/[^\s"]*)+([/\\]\.(?:claude|ssh|gnupg|aws|azure|config|local))[^\s"]*',
                 r'[redacted-path]', msg)
    msg = re.sub(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b',
                 '[redacted-ip]', msg)
    return msg[:200]
