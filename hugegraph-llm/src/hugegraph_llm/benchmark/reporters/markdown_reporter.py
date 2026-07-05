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

"""Markdown reporter for benchmark results.

Report layout (inverted-pyramid, designed for PR/Issue comments):

  1. 概览 (TL;DR)       — analyst-style summary, no BLOCK verdict
  2. 分析               — programmatic roll-up: domain / sub-dimension /
                          question-type clustering / concentration
  3. 指标总览            — only changed metrics in a table; flat ones folded
  4. 退化样例 / 改进样例  — per-sample rows sorted by severity
  5. 证据层              — failures + full metrics + metadata, all folded

The compare-mode report is driven by ``ComparisonResult.analyze()``; the
single-run report reuses the same section scaffolding without comparison.
"""

from typing import Any, Dict, List, Optional, Tuple

# Import metrics to trigger self-registration before querying directions.
from hugegraph_llm.benchmark import metrics  # noqa: F401
from hugegraph_llm.benchmark.baseline.compare import ComparisonResult
from hugegraph_llm.benchmark.metrics.dimensions import domain_label, get_dimension
from hugegraph_llm.benchmark.metrics.registry import MetricRegistry
from hugegraph_llm.benchmark.models.result import BenchmarkResult

_VERDICT_SYMBOL = {"regressed": "🔴", "improved": "🟢", "unchanged": "—"}
_VERDICT_LABEL = {"regressed": "退化", "improved": "改进", "unchanged": "持平"}


def _fmt(value: float) -> str:
    """Format a score / delta with sign for deltas."""
    return f"{value:.4f}"


def _fmt_delta(value: float) -> str:
    return f"+{value:.4f}" if value > 0 else f"{value:.4f}"


def _direction_symbol(metric_name: str) -> str:
    return "↑" if MetricRegistry.is_higher_is_better(metric_name) else "↓"


# ---------------------------------------------------------------------------
# Section 1 — 概览 (TL;DR)
# ---------------------------------------------------------------------------


def _section_overview(result: BenchmarkResult, analysis: Optional[Dict[str, Any]]) -> List[str]:
    """Analyst-style overview. States what happened, never whether to merge."""
    lines: List[str] = ["## 📊 概览", ""]

    if analysis is None:
        # Single-run: just report the headline numbers per domain.
        lines.append(f"- 样例数：{len(result.samples)}")
        lines.append(f"- 指标数：{len(result.overall)}")
        errors = result.metadata.get("error_count") or len(result.metadata.get("errors", []))
        if errors:
            lines.append(f"- 失败样例：{errors}")
        lines.append("")
        return lines

    counts = analysis["counts"]
    total = sum(counts.values())
    lines.append(
        f"- 指标变化：{counts['regressed']} 退化 / {counts['improved']} 改进 / "
        f"{counts['unchanged']} 持平（共 {total}）"
    )

    # Per-domain one-liners, only for domains that actually moved.
    domain_lines: List[str] = []
    for domain, slot in sorted(analysis["by_domain"].items()):
        if slot["regressed"] == 0 and slot["improved"] == 0:
            continue
        parts = []
        if slot["regressed"]:
            parts.append(f"{slot['regressed']} 退化")
        if slot["improved"]:
            parts.append(f"{slot['improved']} 改进")
        worst = slot["worst_delta"]
        tail = f"，最严重 { _fmt_delta(worst)}" if worst < 0 else ""
        domain_lines.append(f"- {domain_label(domain)}：{' / '.join(parts)}{tail}")
    lines.extend(domain_lines)

    # Sample-level headline.
    n_reg = analysis["concentration"]["regressed_samples"]
    lines.append(f"- 样例级：{n_reg} 个退化样例")
    lines.append("")
    return lines


# ---------------------------------------------------------------------------
# Section 2 — 分析
# ---------------------------------------------------------------------------


def _section_analysis(result: BenchmarkResult, comparison: Optional[ComparisonResult]) -> List[str]:
    """Programmatic analysis bullets — dimension / sub-dim / type / concentration."""
    if comparison is None:
        return []
    analysis = comparison.analyze()

    lines: List[str] = ["## 🔍 分析", ""]
    bullets: List[str] = []

    # (a) Which sub-dimension regressed most? Strongest localized signal.
    worst_subdim = _worst_subdimension(analysis)
    if worst_subdim:
        name, slot = worst_subdim
        bullets.append(
            f"退化集中在 **{name}**（{slot['regressed']}/{slot['total']} 指标退化，"
            f"最严重 {_fmt_delta(slot['worst_delta'])}）"
        )

    # (b) Question-type clustering — is the regression pinned to one tier?
    by_qt = analysis["by_question_type"]
    if by_qt:
        dominant_qt, dominant_n = max(by_qt.items(), key=lambda kv: kv[1])
        total_reg = analysis["concentration"]["regressed_samples"]
        if total_reg and dominant_n / max(total_reg, 1) >= 0.5 and len(by_qt) < total_reg:
            bullets.append(
                f"退化扎堆在 **{dominant_qt}** 类型（{dominant_n}/{total_reg}），"
                f"建议回归测试聚焦该类型"
            )

    # (c) Concentration — outlier-driven vs systemic.
    conc = analysis["concentration"]
    n_reg_samples = conc["regressed_samples"]
    n_reg_metrics = analysis["counts"]["regressed"]
    if n_reg_samples and n_reg_metrics:
        if n_reg_samples == 1:
            bullets.append("退化为单一样例驱动（个案），非系统性回归")
        elif conc["max_metrics_per_sample"] >= 3:
            bullets.append(
                f"最严重样例一次丢失 {conc['max_metrics_per_sample']} 个指标，"
                "关注是否存在结构性破坏"
            )

    # (d) Direction consistency within a sub-dimension — noise vs real signal.
    inconsistent = _direction_inconsistency(analysis)
    if inconsistent:
        names = "、".join(inconsistent[:3])
        bullets.append(f"部分维度指标方向不一致（{names}），可能为评测噪音而非真实变化")

    if bullets:
        for b in bullets:
            lines.append(f"- {b}")
    else:
        lines.append("- 无显著结构性变化")
    lines.append("")
    return lines


def _worst_subdimension(analysis: Dict[str, Any]) -> Optional[Tuple[str, Dict[str, Any]]]:
    """Pick the sub-dimension worst-hit: most regressions, then most-negative delta."""
    candidates = [
        (name, slot)
        for name, slot in analysis["by_subdimension"].items()
        if slot["regressed"] > 0
    ]
    if not candidates:
        return None
    # Most regressions first; ties broken by the most-negative worst_delta.
    candidates.sort(key=lambda kv: (-kv[1]["regressed"], kv[1]["worst_delta"]))
    return candidates[0]


def _direction_inconsistency(analysis: Dict[str, Any]) -> List[str]:
    """Sub-dimensions where metrics move in opposite directions (noise hint)."""
    out: List[str] = []
    for name, slot in analysis["by_subdimension"].items():
        if slot["regressed"] and slot["improved"] and slot["total"] >= 2:
            out.append(name)
    return out


# ---------------------------------------------------------------------------
# Section 3 — 指标总览
# ---------------------------------------------------------------------------


def _section_metrics(result: BenchmarkResult, comparison: Optional[ComparisonResult]) -> List[str]:
    """Changed-metric table up top; unchanged metrics folded below."""
    lines: List[str] = ["## 指标总览", ""]

    if comparison is None:
        # Single run: show all metrics grouped by domain, no delta column.
        lines.extend(_render_single_run_metrics(result))
        return lines

    analysis = comparison.analyze()
    verdicts = analysis["metric_verdicts"]

    changed = [(m, v) for m, v in verdicts.items() if v["verdict"] != "unchanged"]
    flat = [(m, v) for m, v in verdicts.items() if v["verdict"] == "unchanged"]

    changed.sort(key=lambda mv: mv[1]["semantic_delta"])  # worst regression first

    if changed:
        lines.append("| 指标 | 维度 | Baseline | Candidate | Δ | 判定 |")
        lines.append("|------|------|----------|-----------|-----|------|")
        for metric, v in changed:
            domain, _ = get_dimension(metric)
            base_val = comparison.baseline_overall.get(metric, 0.0)
            cand_val = comparison.candidate_overall.get(metric, 0.0)
            lines.append(
                f"| {metric} | {domain_label(domain)} | {_fmt(base_val)} | {_fmt(cand_val)} "
                f"| {_fmt_delta(v['semantic_delta'])} | {_VERDICT_SYMBOL[v['verdict']]} {_VERDICT_LABEL[v['verdict']]} |"
            )
        lines.append("")

    if flat:
        lines.append(f"<details><summary>未显著变化的指标（{len(flat)}）</summary>")
        lines.append("")
        lines.append("| 指标 | Baseline | Candidate | Δ |")
        lines.append("|------|----------|-----------|-----|")
        for metric, v in sorted(flat, key=lambda mv: mv[0]):
            base_val = comparison.baseline_overall.get(metric, 0.0)
            cand_val = comparison.candidate_overall.get(metric, 0.0)
            lines.append(
                f"| {metric} | {_fmt(base_val)} | {_fmt(cand_val)} | {_fmt_delta(v['semantic_delta'])} |"
            )
        lines.append("")
        lines.append("</details>")
        lines.append("")
    return lines


def _render_single_run_metrics(result: BenchmarkResult) -> List[str]:
    """Single-run metrics grouped by domain (no comparison columns)."""
    lines: List[str] = []
    by_domain: Dict[str, List[str]] = {}
    for metric in sorted(result.overall.keys()):
        domain, _ = get_dimension(metric)
        by_domain.setdefault(domain, []).append(metric)

    for domain in sorted(by_domain.keys()):
        metrics_list = by_domain[domain]
        lines.append(f"### {domain_label(domain)}")
        lines.append("")
        lines.append("| 指标 | 方向 | 得分 |")
        lines.append("|------|------|------|")
        for metric in metrics_list:
            lines.append(
                f"| {metric} | {_direction_symbol(metric)} | {_fmt(result.overall[metric])} |"
            )
        lines.append("")
    return lines


# ---------------------------------------------------------------------------
# Section 4 — 样例
# ---------------------------------------------------------------------------


def _section_samples(
    title: str,
    symbol: str,
    entries: List[Dict[str, Any]],
    change_key: str,
    limit: int = 5,
) -> List[str]:
    """Render regressed/improved samples: top-N rows + folded detail.

    Each entry becomes ONE row (sample_id + worst metric + counts) so a human
    can scan dozens of samples; the per-metric breakdown is folded.
    """
    if not entries:
        return []

    lines: List[str] = [f"## {symbol} {title}（{len(entries)}）", ""]

    # Flatten to find the worst metric per sample, then sort samples by it.
    summarized: List[Dict[str, Any]] = []
    for entry in entries:
        changes = entry.get(change_key, {})
        if not changes:
            continue
        # worst = most negative semantic delta (regression) or most positive (improvement)
        worst_metric, worst_delta = min(changes.items(), key=lambda kv: kv[1]) \
            if change_key == "regressions" else max(changes.items(), key=lambda kv: kv[1])
        summarized.append(
            {
                "sample_id": entry["sample_id"],
                "question_type": entry.get("question_type"),
                "worst_metric": worst_metric,
                "worst_delta": worst_delta,
                "n_metrics": len(changes),
            }
        )
    summarized.sort(key=lambda r: r["worst_delta"])  # worst first

    lines.append("| Sample | 最严重指标 | Δ | 涉及指标数 | 类型 |")
    lines.append("|--------|-----------|-----|-----------|------|")
    for row in summarized[:limit]:
        qt = row["question_type"] or "—"
        lines.append(
            f"| {row['sample_id']} | {row['worst_metric']} | {_fmt_delta(row['worst_delta'])} "
            f"| {row['n_metrics']} | {qt} |"
        )
    if len(summarized) > limit:
        lines.append(f"| ... | 还有 {len(summarized) - limit} 个样例见下方明细 | | | |")
    lines.append("")

    # Folded per-metric detail.
    lines.append("<details><summary>逐指标明细</summary>")
    lines.append("")
    lines.append("| Sample | Metric | Baseline | Candidate | Δ |")
    lines.append("|--------|--------|----------|-----------|-----|")
    for entry in entries:
        sid = entry["sample_id"]
        base_m = entry.get("baseline_metrics", {})
        cand_m = entry.get("candidate_metrics", {})
        for metric, diff in entry.get(change_key, {}).items():
            lines.append(
                f"| {sid} | {metric} | {_fmt(base_m.get(metric, 0.0))} "
                f"| {_fmt(cand_m.get(metric, 0.0))} | {_fmt_delta(diff)} |"
            )
    lines.append("")
    lines.append("</details>")
    lines.append("")
    return lines


# ---------------------------------------------------------------------------
# Section 5 — 证据层
# ---------------------------------------------------------------------------


def _section_evidence(result: BenchmarkResult) -> List[str]:
    """Failures + metadata, all folded."""
    lines: List[str] = ["## 证据层", ""]
    errors = result.metadata.get("errors", [])
    if errors:
        lines.append("<details><summary>失败样例（{}）</summary>".format(len(errors)))
        lines.append("")
        lines.append("| Sample | Metric | Error |")
        lines.append("|--------|--------|-------|")
        for entry in errors:
            sid = entry.get("sample_id", "N/A")
            metric = entry.get("metric", "N/A")
            err = str(entry.get("error", "")).replace("|", "\\|").replace("\n", " ")
            if len(err) > 120:
                err = err[:117] + "..."
            lines.append(f"| {sid} | {metric} | {err} |")
        lines.append("")
        lines.append("</details>")
        lines.append("")

    meta = result.metadata
    lines.append("<details><summary>元数据</summary>")
    lines.append("")
    lines.append(f"- Timestamp: {meta.get('timestamp', 'N/A')}")
    lines.append(f"- Git Commit: {meta.get('git_commit', 'N/A')}")
    lines.append(f"- Model: {meta.get('model', 'N/A')}")
    if meta.get("temperature") is not None:
        lines.append(f"- Temperature: {meta.get('temperature')}  Seed: {meta.get('seed')}")
    lines.append("")
    lines.append("</details>")
    lines.append("")
    return lines


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class MarkdownReporter:
    """Generate a Markdown string from benchmark results.

    Output is designed to be pasted into PR / Issue comments.
    """

    @staticmethod
    def report(
        result: BenchmarkResult,
        comparison: Optional[ComparisonResult] = None,
    ) -> str:
        """Build a Markdown report.

        Args:
            result: The (candidate) benchmark result to report.
            comparison: Optional comparison against a baseline.

        Returns:
            A complete Markdown document as a string.
        """
        analysis = comparison.analyze() if comparison else None
        lines: List[str] = []

        lines.append("# Benchmark Report")
        lines.append("")
        lines.extend(_section_overview(result, analysis))
        lines.extend(_section_analysis(result, comparison))
        lines.extend(_section_metrics(result, comparison))

        if comparison:
            lines.extend(
                _section_samples("退化样例", "🔴", comparison.regressed_samples, "regressions")
            )
            lines.extend(
                _section_samples("改进样例", "🟢", comparison.improved_samples, "improvements")
            )
        lines.extend(_section_evidence(result))

        return "\n".join(lines)
