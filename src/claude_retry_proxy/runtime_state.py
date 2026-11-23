"""Runtime-mutable process state and its heartbeat.

The proxy's process-wide mutable state lives here, in one neutral leaf: the
loaded config document and its path, the decrypted vendor catalog, the startup
state projection, and the shutdown flag. It is the runtime-mutable sibling of
``settings.py`` (the resolved-once home): ``settings.py`` holds values fixed at
startup, this module holds the values an admin press swaps at runtime.

Access is attribute-form only (``runtime_state._current_config``). The state is
never re-exported through ``server.py``, because a re-export copies the binding
and a write to the copy would diverge from the live one. ``main`` writes the
four startup values; the heartbeat thread and the admin handlers read and write
them thereafter.
"""

import time

from .sinks import write_state


_current_config = None  # Set at startup after validation
_config_path = None  # Path to config.json, set at startup


# Startup state dict, kept in memory so the heartbeat can rewrite a
# proxy-state.json deleted externally without losing pid/port fields.
_startup_state = None

# Decrypted vendors table (read-only after init)
# {provider_name: {"url": ..., "key": ..., "mode": "anthropic|chat|response"}}
_vendors = None


# Shutdown flag — checked by background threads to avoid interfering with
# graceful shutdown. Set True by the /admin/shutdown handler.
_shutting_down = False


# ---------------------------------------------------------------------------
# Heartbeat thread
# ---------------------------------------------------------------------------

def heartbeat_loop():
    while not _shutting_down:
        time.sleep(30)
        if _shutting_down:
            break
        if _startup_state is not None:
            _startup_state["last_heartbeat"] = time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            write_state(_startup_state)
