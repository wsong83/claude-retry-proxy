"""String-emission-safety predicates.

Task contract: pure, stdlib-only predicate functions and patterns used to
validate values before they are emitted into sensitive text surfaces (error
messages, logs, admin names). No package imports, no module state.

The stay-behind idioms of the same task, indexed:
- the inline control-character scans that move with the validators in
  config.py and keys.py
- ``_crlf_safe`` (server.py), ``_validate_csrf_origin`` (server.py),
  ``ALLOWED_PATH_RE`` (server.py),
  ``RESERVED_EXTRA_HEADER_NAMES`` / ``EXTRA_FROM_FORBIDDEN`` (config.py)

Extracted from server.py verbatim.
"""

import re

_ADMIN_NAME_RE = re.compile(r"^[a-zA-Z0-9_./-]+$")


def _validate_admin_name(name):
    """Validate provider/model name contains only safe characters."""
    return bool(_ADMIN_NAME_RE.match(name))
