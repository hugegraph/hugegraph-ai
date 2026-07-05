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

# Import the metrics package to trigger self-registration before querying directions.
from hugegraph_llm.benchmark import metrics  # noqa: F401
from hugegraph_llm.benchmark.metrics.dimensions import get_dimension
from hugegraph_llm.benchmark.metrics.registry import MetricRegistry
from hugegraph_llm.benchmark.models.result import BenchmarkResult


class ComparisonResult(BaseModel):
    """Result of comparing two benchmark runs."""

    model_config = ConfigDict(extra="ignore")

    overall_diff: Dict[str, float] = Field(default_factory=dict)
    overall_reference: Dict[str, float] = Field(default_factory=dict)
    # Raw overall scores for baseline and candidate, so the reporter can show
    # true before/after values without reverse-engineering them from the delta.
    baseline_overall: Dict[str, float] = Field(default_factory=dict)
    candidate_overall: Dict[str, float] = Field(default_factory=dict)
    regressed_samples: List[Dict[str, Any]] = Field(default_factory=list)
    improved_samples: List[Dict[str, Any]] = Field(default_factory=list)
    delta: float = 0.0

    def analyze(self) -> Dict[str, Any]:
        """Produce an analyst-readable summary of the comparison.

        Returns a dict with:
          - ``counts``: {regressed, improved, unchanged} metric counts
          - ``by_domain``: per top-level domain → verdict counts + worst
            semantic delta, so the reporter can say "relation-extraction
            regressed" instead of listing metrics.
          - ``by_subdimension``: finer ``"domain / subdim"`` breakdown.
          - ``by_question_type``: whether regressions cluster in a tier
            (uses candidate samples' ``question_type``).
          - ``concentration``: are regressions spread (systemic) or driven
            by a few samples (outliers)? ``max_metrics_per_sample`` = the
            most metrics any single regressed sample lost.
          - ``metric_verdicts``: metric → {semantic_delta, verdict}.

        All metrics are judged the same way; dimension is a presentation
        grouping only. Pure function of self; safe to call repeatedly.
        """
        verdicts: Dict[str, Dict[str, Any]] = {}
        regressed_metrics: List[str] = []
        improved_metrics: List[str] = []
        unchanged_metrics: List[str] = []

        # Floor the threshold at DEFAULT_RATIO_DELTA so sub-1% wobble is
        # treated as 持平 rather than 退化/改进 noise.
        threshold = max(self.delta, DEFAULT_RATIO_DELTA)

        for metric, sem_delta in self.overall_diff.items():
            if sem_delta < -threshold - 1e-9:
                verdict = "regressed"
                regressed_metrics.append(metric)
            elif sem_delta > threshold + 1e-9:
                verdict = "improved"
                improved_metrics.append(metric)
            else:
                verdict = "unchanged"
                unchanged_metrics.append(metric)
            verdicts[metric] = {"semantic_delta": sem_delta, "verdict": verdict}

        # Roll up by domain / sub-dimension.
        by_domain: Dict[str, Dict[str, Any]] = {}
        by_subdim: Dict[str, Dict[str, Any]] = {}
        for metric, v in verdicts.items():
            domain, subdim = get_dimension(metric)
            sem = v["semantic_delta"]
            for bucket, key in ((by_domain, domain), (by_subdim, f"{domain} / {subdim}")):
                slot = bucket.setdefault(
                    key,
                    {"regressed": 0, "improved": 0, "unchanged": 0, "total": 0, "worst_delta": 0.0},
                )
                slot[v["verdict"]] += 1
                slot["total"] += 1
                if sem < slot["worst_delta"]:
                    slot["worst_delta"] = round(sem, 4)

        # Question-type clustering: do regressions pile into one tier?
        by_qtype: Dict[str, int] = {}
        for entry in self.regressed_samples:
            qt = entry.get("question_type")
            if qt:
                by_qtype[qt] = by_qtype.get(qt, 0) + 1

        # Concentration: how many metrics does the worst single sample lose?
        max_per_sample = 0
        if self.regressed_samples:
            max_per_sample = max(len(e.get("regressions", {})) for e in self.regressed_samples)

        return {
            "counts": {
                "regressed": len(regressed_metrics),
                "improved": len(improved_metrics),
                "unchanged": len(unchanged_metrics),
            },
            "by_domain": by_domain,
            "by_subdimension": by_subdim,
            "by_question_type": by_qtype,
            "concentration": {
                "regressed_samples": len(self.regressed_samples),
                "max_metrics_per_sample": max_per_sample,
            },
            "metric_verdicts": verdicts,
        }


# Minimum |delta| for a RATIO metric to count as 退化/改进. Below this the
# change is treated as noise (抖动) and folded into "unchanged". Count and
# structure metrics are exempt — they are reported as movement, not verdict.
DEFAULT_RATIO_DELTA = 0.01

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


def _higher_is_better(metric_name: str) -> bool:
    """Return metric direction using registered metric metadata."""
    return MetricRegistry.is_higher_is_better(metric_name)


def _semantic_delta(metric_name: str, baseline_value: float, candidate_value: float) -> float:
    """Return a positive delta for improvement, negative for regression."""
    raw_delta = candidate_value - baseline_value
    return raw_delta if _higher_is_better(metric_name) else -raw_delta


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

        # Preserve raw overall scores for true before/after reporting.
        result.baseline_overall = dict(baseline.overall)
        result.candidate_overall = dict(candidate.overall)

        # Overall diff is direction-aware: positive means improvement.
        all_keys = set(baseline.overall.keys()) | set(candidate.overall.keys())
        for key in sorted(all_keys):
            base_val = baseline.overall.get(key, 0.0)
            cand_val = candidate.overall.get(key, 0.0)
            result.overall_diff[key] = round(_semantic_delta(key, base_val, cand_val), 4)

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
                diff = _semantic_delta(metric, base_val, cand_val)

                # Floor at DEFAULT_RATIO_DELTA so trivial wobble doesn't
                # flood the regressed/improved sample lists. LLM-Judge
                # metrics keep their higher variance tolerance.
                effective_delta = max(delta, DEFAULT_RATIO_DELTA)
                if _is_llm_judge_metric(metric):
                    effective_delta = max(effective_delta, cls.DEFAULT_LLM_JUDGE_DELTA)

                if diff < -effective_delta:
                    regressions[metric] = round(diff, 4)
                elif diff > effective_delta:
                    improvements[metric] = round(diff, 4)

            if regressions:
                result.regressed_samples.append(
                    {
                        "sample_id": sid,
                        "question_type": cand_sample.question_type,
                        "regressions": regressions,
                        "baseline_metrics": dict(base_sample.metrics),
                        "candidate_metrics": dict(cand_sample.metrics),
                    }
                )

            if improvements:
                result.improved_samples.append(
                    {
                        "sample_id": sid,
                        "question_type": cand_sample.question_type,
                        "improvements": improvements,
                        "baseline_metrics": dict(base_sample.metrics),
                        "candidate_metrics": dict(cand_sample.metrics),
                    }
                )

        return result
