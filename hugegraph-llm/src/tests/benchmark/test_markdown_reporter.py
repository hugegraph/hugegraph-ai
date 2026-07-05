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

"""Tests for MarkdownReporter failure and direction reporting."""

import pytest

from hugegraph_llm.benchmark.baseline.compare import ComparisonResult
from hugegraph_llm.benchmark.models.result import BenchmarkResult, SampleResult
from hugegraph_llm.benchmark.reporters.markdown_reporter import MarkdownReporter

pytestmark = pytest.mark.unit


def test_report_includes_failed_samples():
    result = BenchmarkResult(
        samples=[SampleResult(sample_id="s1", metrics={"entity_f1": 1.0})],
        overall={"entity_f1": 1.0},
        metadata={
            "mode": "extraction",
            "error_count": 1,
            "errors": [{"sample_id": "s1", "metric": "triple_f1", "error": "division by zero"}],
        },
    )
    report = MarkdownReporter.report(result)
    assert "## Failed Samples" in report
    assert "division by zero" in report
    assert "triple_f1" in report


def test_report_overall_metrics_show_direction():
    result = BenchmarkResult(
        samples=[],
        overall={"entity_f1": 0.8, "conflict_rate": 0.1},
        metadata={"mode": "extraction"},
    )
    report = MarkdownReporter.report(result)
    assert "## Overall Metrics" in report
    assert "| entity_f1 | ↑ |" in report
    assert "| conflict_rate | ↓ |" in report


def test_report_by_type_metrics_show_direction():
    result = BenchmarkResult(
        samples=[],
        overall={},
        by_type={"simple": {"entity_f1": 0.9, "orphan_edge_rate": 0.05}},
        metadata={},
    )
    report = MarkdownReporter.report(result)
    assert "## Metrics by Question Type" in report
    assert "### simple" in report
    assert "| entity_f1 | ↑ |" in report
    assert "| orphan_edge_rate | ↓ |" in report


def test_report_comparison_includes_direction_and_delta():
    result = BenchmarkResult(
        samples=[SampleResult(sample_id="s1", metrics={"entity_f1": 0.6, "conflict_rate": 0.2})],
        overall={"entity_f1": 0.6, "conflict_rate": 0.2},
        metadata={"mode": "extraction"},
    )
    comparison = ComparisonResult(
        overall_diff={"entity_f1": -0.2, "conflict_rate": -0.1},
        regressed_samples=[
            {
                "sample_id": "s1",
                "regressions": {"entity_f1": -0.2},
                "baseline_metrics": {"entity_f1": 0.8, "conflict_rate": 0.1},
                "candidate_metrics": {"entity_f1": 0.6, "conflict_rate": 0.2},
            }
        ],
    )
    report = MarkdownReporter.report(result, comparison=comparison)
    assert "## Overall Metrics" in report
    assert "| entity_f1 | ↑ | 0.6000 | -0.2000 |" in report
    assert "## Regressed Samples" in report
    assert "| Sample ID | Metric | Direction | Baseline | Candidate | Delta |" in report
    assert "| s1 | entity_f1 | ↑ |" in report


def test_report_unknown_metric_defaults_to_higher_direction():
    result = BenchmarkResult(
        samples=[],
        overall={"unknown_metric": 0.5},
        metadata={},
    )
    report = MarkdownReporter.report(result)
    assert "| unknown_metric | ↑ |" in report


def test_report_omits_low_performing_section():
    result = BenchmarkResult(
        samples=[SampleResult(sample_id="s1", metrics={"entity_f1": 0.0})],
        overall={"entity_f1": 0.0},
        metadata={"mode": "extraction"},
    )
    report = MarkdownReporter.report(result)
    assert "## Low-performing Samples" not in report
    assert "## Failed Samples" not in report


def test_failed_samples_error_truncation():
    long_error = "x" * 200
    result = BenchmarkResult(
        samples=[],
        overall={},
        metadata={
            "mode": "extraction",
            "error_count": 1,
            "errors": [{"sample_id": "s1", "metric": "m", "error": long_error}],
        },
    )
    report = MarkdownReporter.report(result)
    # Should be truncated with ellipsis
    assert "..." in report
    assert "x" * 120 not in report
