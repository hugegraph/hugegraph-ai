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

"""Markdown reporter for benchmark results."""

from typing import Any, Dict, List, Optional, Tuple

# Import the metrics package to trigger self-registration before querying directions.
from hugegraph_llm.benchmark import metrics  # noqa: F401
from hugegraph_llm.benchmark.baseline.compare import ComparisonResult
from hugegraph_llm.benchmark.metrics.registry import MetricRegistry
from hugegraph_llm.benchmark.models.result import BenchmarkResult


def _format_delta(value: float) -> str:
    """Format a delta value with sign prefix."""
    if value > 0:
        return f"+{value:.4f}"
    return f"{value:.4f}"


def _is_degraded(metric_name: str, value: Optional[float]) -> bool:
    """Return True when a metric value is at its worst bound.

    Uses registered metric direction metadata. Higher-is-better metrics are
    degraded at 0.0; lower-is-better metrics are degraded at 1.0. ``None``
    values are also treated as degraded (metric failed or was skipped).
    """
    if value is None:
        return True
    if MetricRegistry.is_higher_is_better(metric_name):
        return float(value) <= 0.0
    return float(value) >= 1.0


def _collect_degraded_samples(result: BenchmarkResult) -> List[Tuple[str, List[Tuple[str, Any]]]]:
    """Return samples with degraded metrics, sorted by severity.

    Each entry is ``(sample_id, [(metric, value), ...])``. Samples with more
    degraded metrics come first.
    """
    degraded: List[Tuple[str, List[Tuple[str, Any]]]] = []
    for sample in result.samples:
        bad: List[Tuple[str, Any]] = []
        for metric, value in sample.metrics.items():
            if _is_degraded(metric, value):
                bad.append((metric, value))
        if bad:
            bad.sort(key=lambda x: x[0])
            degraded.append((sample.sample_id, bad))
    degraded.sort(key=lambda item: (-len(item[1]), item[0]))
    return degraded


class MarkdownReporter:
    """Generate a Markdown string from benchmark results.

    The output is designed to be pasted into PR / Issue comments.
    """

    @staticmethod
    def report(
        result: BenchmarkResult,
        comparison: Optional[ComparisonResult] = None,
    ) -> str:
        """Build a Markdown report.

        Args:
            result: The benchmark result to report.
            comparison: Optional comparison against a baseline.

        Returns:
            A complete Markdown document as a string.
        """
        lines: List[str] = []

        # Title
        lines.append("# Benchmark Report")
        lines.append("")

        # Meta info
        meta = result.metadata
        lines.append("## Metadata")
        lines.append("")
        lines.append(f"- **Timestamp**: {meta.get('timestamp', 'N/A')}")
        lines.append(f"- **Git Commit**: {meta.get('git_commit', 'N/A')}")
        lines.append(f"- **Model**: {meta.get('model', 'N/A')}")
        lines.append(f"- **Sample Count**: {len(result.samples)}")
        error_count = meta.get("error_count", 0)
        if error_count:
            lines.append(f"- **Error Count**: {error_count}")
        lines.append("")

        # Overall metrics table
        lines.append("## Overall Metrics")
        lines.append("")

        if comparison and comparison.overall_diff:
            lines.append("| Metric | Score | Delta |")
            lines.append("|--------|-------|-------|")
            all_keys = sorted(set(result.overall.keys()) | set(comparison.overall_diff.keys()))
            for key in all_keys:
                score = result.overall.get(key, 0.0)
                diff = comparison.overall_diff.get(key, 0.0)
                diff_str = _format_delta(diff)
                lines.append(f"| {key} | {score:.4f} | {diff_str} |")
        else:
            lines.append("| Metric | Score |")
            lines.append("|--------|-------|")
            for key in sorted(result.overall.keys()):
                lines.append(f"| {key} | {result.overall[key]:.4f} |")

        lines.append("")

        # Per-tier breakdown (only when samples carry question_type)
        if result.by_type:
            lines.append("## Metrics by Question Type")
            lines.append("")
            for tier in sorted(result.by_type.keys()):
                tier_overall = result.by_type[tier]
                lines.append(f"### {tier}")
                lines.append("")
                lines.append("| Metric | Score |")
                lines.append("|--------|-------|")
                for key in sorted(tier_overall.keys()):
                    lines.append(f"| {key} | {tier_overall[key]:.4f} |")
                lines.append("")

        # Failed samples (single-run errors)
        errors = meta.get("errors", [])
        if errors:
            lines.append("## Failed Samples")
            lines.append("")
            lines.append("| Sample ID | Metric | Error |")
            lines.append("|-----------|--------|-------|")
            for entry in errors:
                sid = entry.get("sample_id", "N/A")
                metric = entry.get("metric", "N/A")
                error = str(entry.get("error", "")).replace("|", "\\|").replace("\n", " ")
                # Truncate very long errors
                display_error = error if len(error) <= 120 else error[:117] + "..."
                lines.append(f"| {sid} | {metric} | {display_error} |")
            lines.append("")

        # Degraded samples (single-run worst-bound metrics)
        if not comparison:
            degraded = _collect_degraded_samples(result)
            if degraded:
                lines.append("## Degraded Samples")
                lines.append("")
                lines.append("| Sample ID | Degraded Metrics |")
                lines.append("|-----------|------------------|")
                for sid, bad_metrics in degraded:
                    metric_cells = ", ".join(
                        f"{name}={value if value is not None else 'N/A'}" for name, value in bad_metrics
                    )
                    # Escape pipe characters in metric names/values
                    metric_cells = metric_cells.replace("|", "\\|")
                    lines.append(f"| {sid} | {metric_cells} |")
                lines.append("")

        # Regressed samples (if comparison available)
        if comparison and comparison.regressed_samples:
            lines.append("## Regressed Samples")
            lines.append("")
            lines.append("| Sample ID | Metric | Baseline | Candidate | Delta |")
            lines.append("|-----------|--------|----------|-----------|-------|")

            # Flatten and sort by delta ascending (worst first)
            rows: List[Dict[str, Any]] = []
            for entry in comparison.regressed_samples:
                sid = entry["sample_id"]
                base_metrics = entry.get("baseline_metrics", {})
                cand_metrics = entry.get("candidate_metrics", {})
                for metric, diff in entry.get("regressions", {}).items():
                    rows.append(
                        {
                            "sample_id": sid,
                            "metric": metric,
                            "baseline": base_metrics.get(metric, 0.0),
                            "candidate": cand_metrics.get(metric, 0.0),
                            "delta": diff,
                        }
                    )

            # Sort by delta ascending (most negative first)
            rows.sort(key=lambda r: r["delta"])

            for row in rows:
                lines.append(
                    f"| {row['sample_id']} | {row['metric']} "
                    f"| {row['baseline']:.4f} | {row['candidate']:.4f} "
                    f"| {_format_delta(row['delta'])} |"
                )

            lines.append("")

        return "\n".join(lines)
