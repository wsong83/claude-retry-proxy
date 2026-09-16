"""Unit tests: pure functions, no subprocess and no network.

Part of the claude-retry-proxy suite; runnable standalone.
"""

import threading

from _harness import (
    fail,
    pass_,
    run_cli,
)




# ===========================================================================
# Test Case 5b: Jittered Delay Bounds (unit test of compute_jittered_delay)
# ===========================================================================

def test_compute_jittered_delay_bounds():
    """Unit-test compute_jittered_delay: bounds, rounding, de-sync pattern, guards, thread-local RNG."""
    print("\n--- Test 5b: Jittered Delay Bounds ---")

    import math
    from claude_retry_proxy.server import compute_jittered_delay, compute_delay, _rng, SETTINGS

    bases = [1, 2, 3, 4, 8, 16, 30, 300]
    draws_per_base = 2000

    for base in bases:
        results = [compute_jittered_delay(base) for _ in range(draws_per_base)]

        # Every result must be an int >= 0
        for r in results:
            if not isinstance(r, int):
                fail(f"base={base}: non-int result: {r} (type={type(r).__name__})")
                break
            if r < 0:
                fail(f"base={base}: negative result: {r}")
                break
        else:
            # Upper bound: floor(base * 1.25 + 0.5)
            hi = math.floor(base * 1.25 + 0.5)
            for r in results:
                if r > hi:
                    fail(f"base={base}: result {r} exceeds upper bound {hi}")
                    break
            else:
                pass_(f"base={base}: all {draws_per_base} draws within [0, {hi}]")

            # Lower bound (allow one integer step below floor for edge effects)
            lo = math.floor(base * 0.75 + 0.5) - 1
            for r in results:
                if r < lo:
                    fail(f"base={base}: result {r} below lower bound {lo}")
                    break
            else:
                pass_(f"base={base}: all draws >= lower bound {lo}")

            # Empirical mean check (±15% of base — unbiased jitter)
            mean = sum(results) / len(results)
            if abs(mean - base) < 0.15 * base:
                pass_(f"base={base}: mean={mean:.2f} ≈ {base} (within ±15%)")
            else:
                fail(f"base={base}: mean={mean:.2f} deviates >15% from {base}")

    # De-sync regression guard: base=3 and base=4 produce ≥2 distinct values
    for base in [3, 4]:
        results = [compute_jittered_delay(base) for _ in range(draws_per_base)]
        distinct = len(set(results))
        if distinct >= 2:
            pass_(f"base={base}: {distinct} distinct values (de-sync active)")
        else:
            fail(f"base={base}: only 1 distinct value — de-sync dead (rounding bug)")

    # De-sync regression guard: base=1 and base=2 are degenerate (documented)
    for base in [1, 2]:
        results = [compute_jittered_delay(base) for _ in range(500)]
        distinct = len(set(results))
        if distinct == 1:
            pass_(f"base={base}: exactly 1 distinct value ({results[0]}) — degenerate, documented")
        else:
            fail(f"base={base}: {distinct} distinct values — expected exactly 1 (degenerate case)")

    # Guard clause: compute_jittered_delay(0) == 0 and compute_jittered_delay(-5) == 0
    if compute_jittered_delay(0) == 0:
        pass_("compute_jittered_delay(0) == 0")
    else:
        fail(f"compute_jittered_delay(0) = {compute_jittered_delay(0)}, expected 0")

    if compute_jittered_delay(-5) == 0:
        pass_("compute_jittered_delay(-5) == 0")
    else:
        fail(f"compute_jittered_delay(-5) = {compute_jittered_delay(-5)}, expected 0")

    # Regression guard on unchanged compute_delay
    if compute_delay(0) == SETTINGS.initial_delay:
        pass_(f"compute_delay(0) == SETTINGS.initial_delay ({SETTINGS.initial_delay})")
    else:
        fail(f"compute_delay(0) = {compute_delay(0)}, expected {SETTINGS.initial_delay}")

    if compute_delay(100) == SETTINGS.max_delay:
        pass_(f"compute_delay(100) == SETTINGS.max_delay ({SETTINGS.max_delay})")
    else:
        fail(f"compute_delay(100) = {compute_delay(100)}, expected {SETTINGS.max_delay}")

    # Thread-local RNG correctness: same object within one thread
    r1 = _rng()
    r2 = _rng()
    if r1 is r2:
        pass_("_rng() returns same object within one thread")
    else:
        fail("_rng() returned different objects within the same thread")

    # Thread-local RNG correctness: distinct objects across threads
    cross_thread_results = []
    def get_rng():
        cross_thread_results.append(_rng())

    t = threading.Thread(target=get_rng)
    t.start()
    t.join()
    if len(cross_thread_results) == 1 and cross_thread_results[0] is not r1:
        pass_("_rng() returns distinct objects across threads")
    elif len(cross_thread_results) == 1 and cross_thread_results[0] is r1:
        fail("_rng() returned the SAME object across threads — not thread-local")
    else:
        fail(f"Unexpected cross-thread _rng() result: {cross_thread_results}")




# ===========================================================================
# Test Case 32: CRLF Header Filter (plan 2026-08-12-streaming-proxy, Step 5 unit test)
# ===========================================================================

def test_crlf_header_filter():
    """In-process unit test of _crlf_safe: clean headers pass through; a header
    VALUE containing CR/LF is omitted; a header NAME containing CR/LF is
    omitted; None → {}; a mixed dict keeps only clean entries. Behavioral
    testing via a mock upstream is infeasible (modern http.client parses raw
    CR/LF header lines into separate clean headers before the proxy sees them)
    — the unit test is authoritative."""
    print("\n--- Test 32: CRLF Header Filter ---")

    from claude_retry_proxy.server import _crlf_safe

    # Clean headers pass through
    result = _crlf_safe({"X-Ok": "fine"})
    if result == {"X-Ok": "fine"}:
        pass_("Clean header preserved: {\"X-Ok\": \"fine\"}")
    else:
        fail(f"_crlf_safe({{'X-Ok': 'fine'}}) returned {result!r}, expected "
             "{\"X-Ok\": \"fine\"}")

    # Header VALUE containing CR/LF is omitted
    result = _crlf_safe({"X-Bad": "a\r\nSet-Cookie: injected=1"})
    if result == {}:
        pass_("Header value with CRLF omitted")
    else:
        fail(f"_crlf_safe returned {result!r}, expected {{}} for CRLF value")

    # Header NAME containing CR/LF is omitted
    result = _crlf_safe({"X\nBad": "v"})
    if result == {}:
        pass_("Header name with newline omitted")
    else:
        fail(f"_crlf_safe returned {result!r}, expected {{}} for CRLF name")

    # None input returns {}
    if _crlf_safe(None) == {}:
        pass_("_crlf_safe(None) returns {}")
    else:
        fail(f"_crlf_safe(None) returned {_crlf_safe(None)!r}, expected {{}}")

    # Empty dict returns {}
    if _crlf_safe({}) == {}:
        pass_("_crlf_safe({}) returns {}")
    else:
        fail(f"_crlf_safe({{}}) returned {_crlf_safe({})!r}, expected {{}}")

    # Mixed dict keeps only clean entries
    result = _crlf_safe({"X-Clean": "ok", "X-Dirty": "a\nb", "Y\nZ": "1"})
    if result == {"X-Clean": "ok"}:
        pass_("Mixed dict keeps only clean entries")
    else:
        fail(f"_crlf_safe mixed returned {result!r}, expected "
             "{\"X-Clean\": \"ok\"}")


ALL_TESTS = [
    ("compute-jittered-delay-bounds", test_compute_jittered_delay_bounds),
    ("crlf-header-filter", test_crlf_header_filter),
]


if __name__ == "__main__":
    run_cli(ALL_TESTS, "claude-retry-proxy tests: test_unit")
