# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

"""
Phase 2 / 3 runtime gate: concurrent load probe with **client-side**
event-loop tick-gap sampling.

Spawns N concurrent clients against a chosen RAG endpoint and concurrently
samples the asyncio event-loop tick gap on **this load-test process** (i.e.
how long between consecutive iterations of the *client* loop the loop went
unscheduled). Emits a summary with:
    - completed / failed request counts
    - end-to-end latency P50 / P95 / P99
    - client tick-gap P50 / P95 / P99 (Phase 2 gate: P99 ≤ 50ms)

**Scope caveat — what this measures and what it does NOT**:
    The tick-gap sampler runs in the *load-test client process*, not the
    HugeGraph / hugegraph-llm server process. It catches client-side
    scheduling latency — useful as a smoke check that the probe itself isn't
    starved while waiting on responses, and a healthy client tick gap is a
    *necessary* condition for the gate. It is **not sufficient**: a blocked
    server event loop can still produce a low client-side tick_gap_ms here.
    To enforce the "server event loop not blocked" gate end-to-end, sample
    from inside the ASGI app process (e.g. middleware/background instrumen-
    tation exposed via metrics) and pair both signals.

Endpoint modes (Phase 3 P3-T6 mock-LLM 压测对比用):
    --endpoint /rag/stream      (default, SSE — needs --stream/auto-detected)
    --endpoint /rag --no-stream (non-stream JSON; pair with feature flag
                                 HUGEGRAPH_LLM_ASYNC_ROUTES_ENABLED=0/1 to
                                 compare async vs sync route bodies)

Standard 4-cell run for Phase 3 退出标准（搭配 scripts/mock_llm_server.py）:

    # 1. async + stream:
    python scripts/async_load_probe.py --concurrency 32 --requests 200
    # 2. async + non-stream:
    python scripts/async_load_probe.py --endpoint /rag --no-stream \\
        --concurrency 32 --requests 200
    # 3 & 4. restart app with HUGEGRAPH_LLM_ASYNC_ROUTES_ENABLED=0 then re-run
    #        cell 2 to capture the sync baseline (cell 1 has no sync analogue —
    #        /rag/stream is always async by design).

Exits 1 if **any** of the following hold (every condition is hard-required to
pass; any failed request invalidates the run regardless of tick-gap health):
    - client tick-gap P99 exceeds --tick-gate-ms; or
    - any request failed (failures > 0); or
    - completed request count != --requests.
"""

import argparse
import asyncio
import json
import statistics
import sys
import time
from typing import List

import httpx


async def _sample_tick_gap(samples: List[float], stop: asyncio.Event, interval: float = 0.005) -> None:
    """Wake every `interval` seconds, record actual gap. Drift above interval
    means the loop was blocked (a sync call that did not yield)."""
    last = time.monotonic()
    while not stop.is_set():
        await asyncio.sleep(interval)
        now = time.monotonic()
        gap_ms = (now - last) * 1000.0
        samples.append(gap_ms)
        last = now


async def _one_request(
    client: httpx.AsyncClient,
    base_url: str,
    endpoint: str,
    query: str,
    stream: bool,
    latencies: List[float],
    failures: List[str],
) -> None:
    """Drive one request and record wall-clock latency.

    Streaming mode reads to EOF (so latency includes full token stream — closer
    to real SSE client behavior); non-stream mode does a plain POST.
    """
    start = time.monotonic()
    # raw_answer=True keeps us off the graph/vector retrieval paths so latency
    # reflects router + pipeline + LLM only — the cleanest signal for routing
    # async-vs-sync comparison against scripts/mock_llm_server.py.
    payload = {"query": query, "raw_answer": True, "graph_only": False}
    url = f"{base_url}{endpoint}"
    try:
        if stream:
            async with client.stream("POST", url, json=payload, timeout=120.0) as resp:
                if resp.status_code != 200:
                    failures.append(f"http {resp.status_code}")
                    return
                async for _ in resp.aiter_text():
                    pass
        else:
            resp = await client.post(url, json=payload, timeout=120.0)
            if resp.status_code != 200:
                failures.append(f"http {resp.status_code}")
                return
        latencies.append((time.monotonic() - start) * 1000.0)
    except Exception as e:  # pylint: disable=broad-except
        failures.append(repr(e))


def _quantile(values: List[float], q: float) -> float:
    """Linear-interpolation quantile that works for any sample size ≥ 1.

    `statistics.quantiles(n=100)` requires len ≥ 2 and produces 99 cut points
    (no 0% / 100%); falling back to max() on small samples conflates P50/P95/P99,
    hiding tail-latency shape. This routine sorts once and interpolates between
    the two surrounding ranks for the requested quantile.
    """
    if not values:
        return float("nan")
    if len(values) == 1:
        return values[0]
    sorted_vals = sorted(values)
    pos = q * (len(sorted_vals) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = pos - lo
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * frac


async def main_async(args: argparse.Namespace) -> int:
    tick_samples: List[float] = []
    stop_sampler = asyncio.Event()
    sampler = asyncio.create_task(_sample_tick_gap(tick_samples, stop_sampler))

    latencies: List[float] = []
    failures: List[str] = []

    sem = asyncio.Semaphore(args.concurrency)

    # Auto-pick stream mode from endpoint when user didn't override.
    stream = args.stream
    if stream is None:
        stream = args.endpoint.endswith("/stream")

    async def _bounded(client):
        async with sem:
            await _one_request(
                client,
                args.base_url,
                args.endpoint,
                args.query,
                stream,
                latencies,
                failures,
            )

    async with httpx.AsyncClient() as client:
        wall_start = time.monotonic()
        await asyncio.gather(*[_bounded(client) for _ in range(args.requests)])
        wall_end = time.monotonic()

    stop_sampler.set()
    await sampler

    summary = {
        "endpoint": args.endpoint,
        "stream": stream,
        "concurrency": args.concurrency,
        "requests": args.requests,
        "completed": len(latencies),
        "failed": len(failures),
        "wall_seconds": round(wall_end - wall_start, 3),
        "rps": round(len(latencies) / max(wall_end - wall_start, 1e-9), 2),
        "latency_ms": {
            "p50": round(_quantile(latencies, 0.50), 1),
            "p95": round(_quantile(latencies, 0.95), 1),
            "p99": round(_quantile(latencies, 0.99), 1),
        },
        # NOTE: client_tick_gap_ms — sampled from THIS load-test process's loop,
        # not the server's. See module docstring for the scope caveat.
        "client_tick_gap_ms": {
            "samples": len(tick_samples),
            "p50": round(_quantile(tick_samples, 0.50), 2),
            "p95": round(_quantile(tick_samples, 0.95), 2),
            "p99": round(_quantile(tick_samples, 0.99), 2),
        },
        "first_failures": failures[:5],
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))

    # Multi-condition gate. tick-gap alone can NOT carry the run: a misconfigured
    # base-url or a fully-down service can produce 100% failures while the
    # client loop happily idles at sub-millisecond tick gaps — without a request
    # gate the probe would exit 0 and silently bless a broken endpoint.
    failed = summary["failed"]
    completed = summary["completed"]
    requested = summary["requests"]
    tick_p99 = summary["client_tick_gap_ms"]["p99"]
    failures_summary: list[str] = []
    if failed > 0:
        failures_summary.append(f"failed requests = {failed} (>0)")
    if completed != requested:
        failures_summary.append(f"completed = {completed} != requests = {requested}")
    if tick_p99 > args.tick_gate_ms:
        failures_summary.append(f"client tick-gap P99 = {tick_p99}ms > gate {args.tick_gate_ms}ms")
    if failures_summary:
        print("\nFAIL: " + "; ".join(failures_summary), file=sys.stderr)
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Async load probe with event-loop tick-gap sampling")
    parser.add_argument("--base-url", default="http://localhost:8001")
    parser.add_argument(
        "--endpoint",
        default="/rag/stream",
        help="route under test, e.g. /rag/stream (SSE) or /rag (non-stream)",
    )
    # Mutually exclusive --stream / --no-stream; if neither given we infer from
    # the endpoint suffix so the common case (just point at /rag/stream) stays
    # zero-config.
    stream_group = parser.add_mutually_exclusive_group()
    stream_group.add_argument(
        "--stream",
        dest="stream",
        action="store_true",
        default=None,
        help="treat response as SSE; overrides endpoint-based auto-detection",
    )
    stream_group.add_argument(
        "--no-stream",
        dest="stream",
        action="store_false",
        help="treat response as plain JSON (use with /rag, /text2gremlin, ...)",
    )
    parser.add_argument("--concurrency", type=int, default=32)
    parser.add_argument("--requests", type=int, default=64)
    parser.add_argument("--query", default="你好")
    parser.add_argument("--tick-gate-ms", type=float, default=50.0, help="Phase 2 gate (default 50ms)")
    args = parser.parse_args()
    # Reject non-positive values up front: --concurrency=0 deadlocks on
    # ``Semaphore(0)`` and --requests<=0 silently produces an empty success
    # report — both are footguns for a CI gate utility.
    if args.concurrency <= 0:
        parser.error("--concurrency must be > 0")
    if args.requests <= 0:
        parser.error("--requests must be > 0")
    if args.tick_gate_ms <= 0:
        parser.error("--tick-gate-ms must be > 0")
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
