#!/usr/bin/env python3
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

"""Generate a演示用 candidate baseline from an existing one by jittering metrics.

读一份真实 baseline，对 metrics 做可控扰动，产出一个"看起来像另一次 run"的
candidate，让 ``compare`` 能现场演示退化/改进/持平的全谱，而不需要真的重跑
评测流程。用于演示测评闭环。

扰动策略（按 metric 名前缀分桶，每桶一个方向）：
  - recall@1 / hit_*@1   → 普遍退化（演示主要回归点）
  - mrr                   → 普遍改进（演示正向变化）
  - 其余                  → 小幅随机抖动（演示持平/噪音）

值被 clamp 到 [0, 1]。整体改动幅度由 --magnitude 控制（默认 0.08）。

用法：
  uv run python scripts/benchmark/jitter_baseline.py \
      --baseline testdata/eval_ready/baselines/hotpotqa_retrieval.json \
      --output   testdata/eval_ready/baselines/hotpotqa_retrieval_jittered.json
然后：
  uv run python -m hugegraph_llm.benchmark compare \
      --baseline testdata/eval_ready/baselines/hotpotqa_retrieval.json \
      --candidate testdata/eval_ready/baselines/hotpotqa_retrieval_jittered.json
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from typing import Optional

# 按前缀/名分桶的扰动方向。键为判断函数，值为 (方向, 幅度系数)。
# 方向: "down" = 退化, "up" = 改进, "jitter" = 双向小噪。
# 设计意图：让 compare 报告同时出现"退化集中在某维度""改进在某维度""部分持平"，
# 形成可演示的完整闭环。

REGRESS_PREFIXES = ("recall@1", "hit_any@1", "hit_all@1")     # top-1 召回/命中退化
IMPROVE_NAMES = {"mrr", "hit_all@5", "hit_any@5"}             # 排序/前5改进
# 其余 metric 走 jitter（小幅双向）


def _clamp01(v: float) -> float:
    return max(0.0, min(1.0, v))


def _direction_for(metric: str) -> str:
    if any(metric == p or metric.startswith(p) for p in REGRESS_PREFIXES):
        return "down"
    if metric in IMPROVE_NAMES:
        return "up"
    return "jitter"


def jitter_baseline(data: dict, magnitude: float, seed: int) -> dict:
    """Return a deep-copied baseline with metrics jittered per-bucket."""
    rng = random.Random(seed)
    out = json.loads(json.dumps(data))  # deep copy via json

    for sample in out.get("samples", []):
        metrics = sample.get("metrics")
        if not isinstance(metrics, dict):
            continue
        for name, value in list(metrics.items()):
            if value is None or not isinstance(value, (int, float)):
                continue
            direction = _direction_for(name)
            if direction == "down":
                # 退化：大概率显著下降
                delta = -magnitude * (0.5 + rng.random())
            elif direction == "up":
                # 改进：大概率上升
                delta = magnitude * (0.5 + rng.random())
            else:
                # 噪音：小双向
                delta = (rng.random() - 0.5) * magnitude * 0.4
            metrics[name] = round(_clamp01(value + delta), 4)

    # overall / by_type 是聚合值，重算才准；这里直接清空，让 compare 走 sample 级。
    # compare 的退化判定基于 per-sample metrics，overall_diff 会从 candidate.overall
    # 重算 —— 所以我们要重算 overall。
    out["overall"] = _recompute_overall(out.get("samples", []))
    out["by_type"] = {}  # 简化：扰动后不再分 tier（演示足够）
    return out


def _recompute_overall(samples: list) -> dict:
    """Mean of per-sample metrics, mirroring BenchmarkResult.compute_overall."""
    if not samples:
        return {}
    keys: set = set()
    for s in samples:
        m = s.get("metrics") or {}
        keys.update(m.keys())
    overall = {}
    for k in keys:
        vals = [
            s["metrics"][k]
            for s in samples
            if isinstance(s.get("metrics"), dict)
            and s["metrics"].get(k) is not None
        ]
        if vals:
            overall[k] = round(sum(vals) / len(vals), 4)
    return overall


def main(argv: Optional[list] = None) -> int:
    p = argparse.ArgumentParser(description="Jitter a baseline to demo compare.")
    p.add_argument("--baseline", required=True, help="Path to source baseline JSON")
    p.add_argument("--output", required=True, help="Path to write jittered candidate")
    p.add_argument(
        "--magnitude",
        type=float,
        default=0.08,
        help="Max change magnitude (default 0.08)",
    )
    p.add_argument("--seed", type=int, default=42, help="RNG seed for reproducibility")
    args = p.parse_args(argv)

    with open(args.baseline, "r", encoding="utf-8") as f:
        data = json.load(f)

    jittered = jitter_baseline(data, args.magnitude, args.seed)

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(jittered, f, ensure_ascii=False, indent=2)

    # 简要报告变化分布，方便演示时讲解
    orig_overall = data.get("overall", {})
    new_overall = jittered.get("overall", {})
    regressed, improved, flat = [], [], []
    for k in orig_overall:
        if k not in new_overall:
            continue
        diff = round(new_overall[k] - orig_overall[k], 4)
        if diff < -0.005:
            regressed.append((k, diff))
        elif diff > 0.005:
            improved.append((k, diff))
        else:
            flat.append(k)
    print(f"已生成: {args.output}", file=sys.stderr)
    print(
        f"指标变化: {len(regressed)} 退化 / {len(improved)} 改进 / {len(flat)} 持平",
        file=sys.stderr,
    )
    for k, d in sorted(regressed, key=lambda x: x[1])[:5]:
        print(f"  退化  {k}: {orig_overall[k]:.4f} -> {new_overall[k]:.4f} ({d:+.4f})", file=sys.stderr)
    for k, d in sorted(improved, key=lambda x: -x[1])[:5]:
        print(f"  改进  {k}: {orig_overall[k]:.4f} -> {new_overall[k]:.4f} ({d:+.4f})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
