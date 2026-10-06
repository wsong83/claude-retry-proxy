#!/usr/bin/env python3
"""
Analyze proxy trace log for model statistics.

Calculates per-model metrics including:
- Request count
- Average retries
- Query success rate (treating retries as part of same query)
- Attempt success rate (each retry as separate attempt)
- Geometric mean TTFT (Time To First Token)
- Geometric mean latency

Also reports chat-mode drain diagnostics:
- chat_sse_unfinished_turn count per provider
- late-frame offset distributions (late_tool_call_ms, last_late_ms)
- share of drained streams that exited on drain_exit == "time_budget"
- retry recovery: chat_retry_nudge joined to the recovery request's own
  chat_sse_drain.emitted_tool_use, per provider, with dangling keys
  (nudged requests with no observed retry drain) accounted separately

Filters:
- Latency > 30 minutes (outliers)
- Max retries (10) + failure status (complete upstream outage)

Usage:
    python analyze_proxy_trace.py [options]

Options:
    --days N        Analyze last N days (default: 3)
    --trace-file    Path to trace file (default: ~/.claude/logs/proxy-trace.jsonl)
    --help          Show this help message
"""

import argparse
import json
import math
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone


def geomean(values):
    """Calculate geometric mean of a list of positive values."""
    if not values:
        return 0
    positive_values = [v for v in values if v > 0]
    if not positive_values:
        return 0
    return math.exp(sum(math.log(v) for v in positive_values) / len(positive_values))


def parse_args():
    parser = argparse.ArgumentParser(
        description="Analyze proxy trace log for model statistics",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument(
        "--days",
        type=int,
        default=3,
        help="Analyze last N days (default: 3)"
    )
    parser.add_argument(
        "--trace-file",
        type=str,
        default=None,
        help="Path to trace file (default: ~/.claude/logs/proxy-trace.jsonl)"
    )
    return parser.parse_args()


def main():
    args = parse_args()

    # Resolve trace file path
    if args.trace_file:
        trace_path = os.path.expanduser(args.trace_file)
    else:
        trace_path = os.path.expanduser("~/.claude/logs/proxy-trace.jsonl")

    if not os.path.exists(trace_path):
        print(f"Error: Trace file not found: {trace_path}")
        sys.exit(1)

    # Calculate cutoff time
    cutoff_time = datetime.now(timezone.utc) - timedelta(days=args.days)

    # Model names detected from trace
    model_names = set()

    # Data structures per model
    model_stats = defaultdict(lambda: {
        "total_requests": 0,
        "total_retries": 0,
        "success_queries": 0,
        "failure_queries": 0,
        "ttft_list": [],
        "latency_list": [],
    })

    # Filter thresholds
    MAX_LATENCY_SEC = 30 * 60  # 30 minutes
    MAX_RETRIES_THRESHOLD = 10

    # Chat-mode drain diagnostics (chat_sse_drain / chat_sse_unfinished_turn)
    unfinished_by_provider = defaultdict(int)
    late_tool_call_ms_values = []
    last_late_ms_values = []
    drain_total = 0
    drain_time_budget = 0

    # Retry-recovery join: each chat_retry_nudge (deduped by request_id —
    # the guard against multiple armed markers matching one request across
    # the two passes, the cross-prefix collision, and belt-and-braces for
    # the once-per-matching-entry consume rule) joins to the recovery
    # request's own chat_sse_drain.
    nudge_by_request = {}      # recovery request_id -> its first nudge entry
    passthrough_ids = set()    # recovery request_ids that logged chat_retry_passthrough
    passthrough_originals = set()  # errored request_ids whose recovery stalled again
    drain_emitted_tool = {}    # request_id -> 1/0 emitted_tool_use from chat_sse_drain

    total_entries = 0
    entries_in_range = 0
    filtered_latency = 0
    filtered_outage = 0

    with open(trace_path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                entry = json.loads(line.strip())
            except json.JSONDecodeError:
                continue

            _ev = entry.get("event")
            if _ev not in ("request", "chat_sse_drain", "chat_sse_unfinished_turn",
                           "chat_retry_nudge", "chat_retry_passthrough"):
                continue

            if _ev == "request":
                total_entries += 1

            # Parse timestamp
            timestamp_str = entry.get("timestamp")
            if not timestamp_str:
                continue

            try:
                # Handle ISO format with Z suffix
                if timestamp_str.endswith("Z"):
                    dt = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
                else:
                    dt = datetime.fromisoformat(timestamp_str)

                # Skip entries outside the time range
                if dt < cutoff_time:
                    continue
            except Exception:
                continue

            # Drain diagnostics collected under the same window as the table.
            if _ev != "request":
                if _ev == "chat_sse_unfinished_turn":
                    unfinished_by_provider[entry.get("provider") or "?"] += 1
                    continue
                # Explicit branches, each ending in continue: without them the
                # two retry events would fall through into drain_total and
                # inflate the drained-stream diagnostics.
                if _ev == "chat_retry_nudge":
                    _rid = entry.get("request_id")
                    if _rid and _rid not in nudge_by_request:
                        nudge_by_request[_rid] = entry
                    continue
                if _ev == "chat_retry_passthrough":
                    _rid = entry.get("request_id")
                    if _rid:
                        passthrough_ids.add(_rid)
                    _oid = entry.get("original_request_id")
                    if _oid:
                        passthrough_originals.add(_oid)
                    continue
                drain_total += 1
                if entry.get("drain_exit") == "time_budget":
                    drain_time_budget += 1
                for _field, _sink in (("late_tool_call_ms", late_tool_call_ms_values),
                                      ("last_late_ms", last_late_ms_values)):
                    _v = entry.get(_field)
                    if isinstance(_v, (int, float)) and not isinstance(_v, bool):
                        _sink.append(float(_v))
                _rid = entry.get("request_id")
                if _rid:
                    drain_emitted_tool[_rid] = 1 if entry.get("emitted_tool_use") else 0
                continue

            entries_in_range += 1

            model = entry.get("model")
            if not model:
                continue

            model_names.add(model)

            latency = entry.get("total_latency_sec")
            retries = entry.get("retries", 0)
            status = entry.get("status")

            # Filter 1: latency > 30 minutes
            if latency is not None and latency > MAX_LATENCY_SEC:
                filtered_latency += 1
                continue

            # Filter 2: max retries + failure = complete outage
            if retries >= MAX_RETRIES_THRESHOLD and status == "failure":
                filtered_outage += 1
                continue

            stats = model_stats[model]
            stats["total_requests"] += 1
            stats["total_retries"] += retries

            if status == "success":
                stats["success_queries"] += 1
            else:
                stats["failure_queries"] += 1

            ttft_ms = entry.get("first_byte_latency_ms")
            if ttft_ms is not None and ttft_ms > 0:
                stats["ttft_list"].append(float(ttft_ms) / 1000)

            if latency is not None and latency > 0:
                stats["latency_list"].append(float(latency))

    # Print summary
    cutoff_str = cutoff_time.strftime("%Y-%m-%d %H:%M UTC")
    print(f"Proxy Trace Analysis")
    print(f"====================")
    print(f"Time range: {cutoff_str} to now ({args.days} days)")
    print(f"Trace file: {trace_path}")
    print()
    print(f"Total request entries: {total_entries}")
    print(f"Entries in time range: {entries_in_range}")
    print(f"Filtered (>30 min latency): {filtered_latency}")
    print(f"Filtered (max retries + failure): {filtered_outage}")
    print(f"Remaining entries: {entries_in_range - filtered_latency - filtered_outage}")
    print()

    # Print results table
    print("=" * 130)
    print(f"{'Model':<20} {'Requests':>10} {'Avg Retries':>12} {'Query Success%':>15} {'Attempt Success%':>17} {'Avg TTFT':>12} {'Avg Latency':>12}")
    print("=" * 130)

    total_requests = 0
    total_retries = 0
    total_success = 0
    total_failure = 0
    all_ttft = []
    all_latency = []

    # Sort by request count descending
    for model in sorted(model_stats.keys(), key=lambda m: model_stats[m]["total_requests"], reverse=True):
        stats = model_stats[model]
        req_count = stats["total_requests"]
        if req_count == 0:
            continue

        total_requests += req_count

        avg_retries = stats["total_retries"] / req_count if req_count > 0 else 0
        total_retries += stats["total_retries"]

        query_success_rate = stats["success_queries"] / req_count * 100 if req_count > 0 else 0
        total_success += stats["success_queries"]
        total_failure += stats["failure_queries"]

        total_attempts = req_count + stats["total_retries"]
        attempt_success_rate = stats["success_queries"] / total_attempts * 100 if total_attempts > 0 else 0

        geo_ttft = geomean(stats["ttft_list"])
        geo_latency = geomean(stats["latency_list"])
        all_ttft.extend(stats["ttft_list"])
        all_latency.extend(stats["latency_list"])

        print(f"{model:<20} {req_count:>10} {avg_retries:>12.4f} {query_success_rate:>14.2f}% {attempt_success_rate:>16.2f}% {geo_ttft:>11.2f}s {geo_latency:>11.2f}s")

    print("=" * 130)

    # Totals
    if total_requests > 0:
        overall_avg_retries = total_retries / total_requests
        overall_query_success = total_success / total_requests * 100
        overall_attempts = total_requests + total_retries
        overall_attempt_success = total_success / overall_attempts * 100
        overall_geo_ttft = geomean(all_ttft)
        overall_geo_latency = geomean(all_latency)

        print(f"{'TOTAL':<20} {total_requests:>10} {overall_avg_retries:>12.4f} {overall_query_success:>14.2f}% {overall_attempt_success:>16.2f}% {overall_geo_ttft:>11.2f}s {overall_geo_latency:>11.2f}s")

    print()
    # Chat-mode drain diagnostics: the unfinished-turn detector, the late-frame
    # offsets, and the share of drains that hit the time budget.
    def _dist(values):
        if not values:
            return "n/a"
        s = sorted(values)
        n = len(s)
        median = s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2
        p90 = s[min(n - 1, max(0, math.ceil(0.9 * n) - 1))]
        return f"min={s[0]:.0f} median={median:.0f} p90={p90:.0f} max={s[-1]:.0f}"

    print()
    print("=" * 130)
    print("Chat-mode drain diagnostics")
    print("=" * 130)
    print(f"Drained streams (chat_sse_drain): {drain_total}")
    if drain_total:
        share = drain_time_budget / drain_total * 100
        print(f"  Exited on drain_exit == \"time_budget\": {drain_time_budget} ({share:.1f}%)")
    else:
        print("  Exited on drain_exit == \"time_budget\": 0")
    if unfinished_by_provider:
        print("chat_sse_unfinished_turn by provider:")
        for prov in sorted(unfinished_by_provider,
                           key=lambda p: unfinished_by_provider[p], reverse=True):
            print(f"  {prov}: {unfinished_by_provider[prov]}")
    else:
        print("chat_sse_unfinished_turn: none in window")

    # Retry recovery: join each nudged request (deduped by request_id) to its
    # own chat_sse_drain.emitted_tool_use. A nudge with no observed retry
    # drain (errored again, disconnected, never re-issued, or outside the
    # --days window) is counted as dangling and excluded from the success
    # denominator.
    retry_success = 0
    retry_no_tool = 0
    retry_dangling = 0
    retry_success_by_provider = defaultdict(int)
    retry_dangling_by_provider = defaultdict(int)
    for _rid, _entry in nudge_by_request.items():
        _prov = _entry.get("provider") or "?"
        if _rid not in drain_emitted_tool:
            retry_dangling += 1
            retry_dangling_by_provider[_prov] += 1
        elif drain_emitted_tool[_rid]:
            retry_success += 1
            retry_success_by_provider[_prov] += 1
        else:
            retry_no_tool += 1
    retry_denominator = retry_success + retry_no_tool
    print()
    print("Retry recovery (chat_retry_nudge):")
    print(f"  Nudged requests (deduped by request_id): {len(nudge_by_request)}")
    print(f"  Observed retry drain with a tool call: {retry_success}")
    print(f"  Observed retry drain without a tool call: {retry_no_tool}")
    print(f"  No observed retry drain (excluded from the success denominator): {retry_dangling}")
    if retry_denominator:
        print(f"  Retry success rate: {retry_success / retry_denominator * 100:.1f}% "
              f"({retry_success}/{retry_denominator})")
    print(f"  Repeated stall passed through without a second error "
          f"(chat_retry_passthrough): {len(passthrough_ids)} "
          f"[distinct errored conversations by original_request_id: "
          f"{len(passthrough_originals)}]")
    if nudge_by_request:
        print("  Retry recovery by provider (success / dangling):")
        for prov in sorted(set(retry_success_by_provider) | set(retry_dangling_by_provider),
                           key=lambda p: retry_success_by_provider[p], reverse=True):
            print(f"    {prov}: {retry_success_by_provider[prov]} / "
                  f"{retry_dangling_by_provider[prov]}")
    print(f"late_tool_call_ms: {_dist(late_tool_call_ms_values)}")
    print(f"last_late_ms: {_dist(last_late_ms_values)}")
    print()

    print("Notes:")
    print("  - Query Success%: % of queries that eventually succeeded (retries counted as part of same query)")
    print("  - Attempt Success%: % of all attempts that succeeded (each retry counted separately)")
    print("  - Avg TTFT: Geometric mean Time To First Token")
    print("  - Avg Latency: Geometric mean total request latency")
    print("  - Filters applied: latency >30 min, max retries (10) + failure (outage)")


if __name__ == "__main__":
    main()