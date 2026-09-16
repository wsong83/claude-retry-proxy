"""Aggregator and CLI entry point for the claude-retry-proxy suite.

Test functions live in per-area modules (test_unit.py,
test_trace.py, ...). This file merges their ALL_TESTS lists in
historical section order. Run all: python tests/test_claude_proxy.py.
Run a subset: python tests/test_claude_proxy.py -t <name> ...
"""
from _harness import run_cli

from test_unit import ALL_TESTS as UNIT_TESTS
from test_trace import ALL_TESTS as TRACE_TESTS
from test_retry_streaming import ALL_TESTS as RETRY_STREAMING_TESTS
from test_tier_routing import ALL_TESTS as TIER_ROUTING_TESTS
from test_config_keys import ALL_TESTS as CONFIG_KEYS_TESTS
from test_admin import ALL_TESTS as ADMIN_TESTS
from test_cli import ALL_TESTS as CLI_TESTS
from test_mode_dispatch import ALL_TESTS as MODE_DISPATCH_TESTS
from test_chat_transform import ALL_TESTS as CHAT_TRANSFORM_TESTS
from test_chat_sse import ALL_TESTS as CHAT_SSE_TESTS
from test_response_transform import ALL_TESTS as RESPONSE_TRANSFORM_TESTS
from test_compat import ALL_TESTS as COMPAT_TESTS
from test_sinks import ALL_TESTS as SINKS_TESTS
from test_sanitize import ALL_TESTS as SANITIZE_TESTS
from test_settings import ALL_TESTS as SETTINGS_TESTS
from test_docs import ALL_TESTS as DOCS_TESTS

ALL_TESTS = (
    UNIT_TESTS +
    TRACE_TESTS +
    RETRY_STREAMING_TESTS +
    TIER_ROUTING_TESTS +
    CONFIG_KEYS_TESTS +
    ADMIN_TESTS +
    CLI_TESTS +
    MODE_DISPATCH_TESTS +
    CHAT_TRANSFORM_TESTS +
    CHAT_SSE_TESTS +
    RESPONSE_TRANSFORM_TESTS +
    COMPAT_TESTS +
    SINKS_TESTS +
    SANITIZE_TESTS +
    SETTINGS_TESTS +
    DOCS_TESTS
)

if __name__ == "__main__":
    run_cli(ALL_TESTS, "Test suite for claude-retry-proxy")
