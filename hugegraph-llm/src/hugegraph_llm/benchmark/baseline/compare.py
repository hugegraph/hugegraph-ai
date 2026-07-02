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

"""Baseline comparator for regression detection between benchmark runs."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from hugegraph_llm.benchmark.models.result import BenchmarkResult


class ComparisonResult(BaseModel):
    """Result of comparing two benchmark runs."""

    model_config = ConfigDict(extra="ignore")

    overall_diff: Dict[str, float] = Field(default_factory=dict)
    overall_reference: Dict[str, float] = Field(default_factory=dict)
    regressed_samples: List[Dict[str, Any]] = Field(default_factory=list)
    improved_samples: List[Dict[str, Any]] = Field(default_factory=list)
    delta: float = 0.0


# Metric names/prefixes that indicate LLM-Judge metrics (higher variance).
_LLM_JUDGE_METRICS = {
    "answer_correctness",
    "faithfulness",
    "coverage",
    "context_precision",
    "context_relevancy",
    "evidence_recall_llm",
    "conflict_detection",
    "temporal_validity",
}
_LLM_JUDGE_PREFIXES = ("answer_", "coverage_", "judge_", "llm_judge")


def _is_llm_judge_metric(metric_name: str) -> bool:
    """Check if a metric name indicates an LLM-Judge metric."""
    return metric_name in _LLM_JUDGE_METRICS or any(metric_name.startswith(prefix) for prefix in _LLM_JUDGE_PREFIXES)


class BaselineComparator:
    """Compare candidate benchmark results against a baseline.

    Detects regressions and improvements at both overall and per-sample levels.
    For LLM-Judge metrics, uses a higher delta threshold (0.05) to avoid
    false positives from evaluation variance.
    """

    DEFAULT_LLM_JUDGE_DELTA = 0.05

    @classmethod
    def compare(
        cls,
        baseline: BenchmarkResult,
        candidate: BenchmarkResult,
        reference: Optional[BenchmarkResult] = None,
        delta: float = 0.0,
    ) -> ComparisonResult:
        """Compare candidate against baseline, optionally with a reference.

        Args:
            baseline: The established baseline result.
            candidate: The new result to evaluate.
            reference: Optional external reference scores for context.
            delta: Global regression threshold. LLM-Judge metrics automatically
                   use max(delta, 0.05) unless overridden.

        Returns:
            ComparisonResult with diffs, regressed/improved samples.
        """
        result = ComparisonResult(delta=delta)

        # Overall diff: candidate - baseline for each metric
        all_keys = set(baseline.overall.keys()) | set(candidate.overall.keys())
        for key in sorted(all_keys):
            base_val = baseline.overall.get(key, 0.0)
            cand_val = candidate.overall.get(key, 0.0)
            result.overall_diff[key] = round(cand_val - base_val, 4)

        # Reference scores (if provided)
        if reference:
            result.overall_reference = dict(reference.overall)

        # Per-sample comparison
        baseline_by_id = {s.sample_id: s for s in baseline.samples}
        candidate_by_id = {s.sample_id: s for s in candidate.samples}

        all_sample_ids = set(baseline_by_id.keys()) | set(candidate_by_id.keys())

        for sid in sorted(all_sample_ids):
            base_sample = baseline_by_id.get(sid)
            cand_sample = candidate_by_id.get(sid)

            if not base_sample or not cand_sample:
                continue

            # Check each metric for regression / improvement
            sample_metrics = set(base_sample.metrics.keys()) | set(cand_sample.metrics.keys())
            regressions: Dict[str, float] = {}
            improvements: Dict[str, float] = {}

            for metric in sample_metrics:
                base_val = base_sample.metrics.get(metric, 0.0)
                cand_val = cand_sample.metrics.get(metric, 0.0)
                diff = cand_val - base_val

                # Determine effective delta for this metric
                effective_delta = delta
                if _is_llm_judge_metric(metric):
                    effective_delta = max(delta, cls.DEFAULT_LLM_JUDGE_DELTA)

                if diff < -effective_delta:
                    regressions[metric] = round(diff, 4)
                elif diff > effective_delta:
                    improvements[metric] = round(diff, 4)

            if regressions:
                result.regressed_samples.append(
                    {
                        "sample_id": sid,
                        "regressions": regressions,
                        "baseline_metrics": dict(base_sample.metrics),
                        "candidate_metrics": dict(cand_sample.metrics),
                    }
                )

            if improvements:
                result.improved_samples.append(
                    {
                        "sample_id": sid,
                        "improvements": improvements,
                        "baseline_metrics": dict(base_sample.metrics),
                        "candidate_metrics": dict(cand_sample.metrics),
                    }
                )

        return result
