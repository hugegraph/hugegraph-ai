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

"""Tests for MarkdownReporter failure/degradation reporting."""

import pytest

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


def test_report_includes_degraded_samples():
    result = BenchmarkResult(
        samples=[
            SampleResult(sample_id="good", metrics={"entity_f1": 1.0, "triple_f1": 1.0}),
            SampleResult(sample_id="bad", metrics={"entity_f1": 0.0, "triple_f1": 0.5}),
        ],
        overall={"entity_f1": 0.5, "triple_f1": 0.75},
        metadata={"mode": "extraction"},
    )
    report = MarkdownReporter.report(result)
    assert "## Degraded Samples" in report
    assert "bad" in report
    assert "entity_f1=0.0" in report


def test_report_omits_degraded_section_when_all_perfect():
    result = BenchmarkResult(
        samples=[SampleResult(sample_id="good", metrics={"entity_f1": 1.0})],
        overall={"entity_f1": 1.0},
        metadata={"mode": "extraction"},
    )
    report = MarkdownReporter.report(result)
    assert "## Degraded Samples" not in report
    assert "## Failed Samples" not in report


def test_report_respects_lower_is_better_direction():
    result = BenchmarkResult(
        samples=[
            SampleResult(sample_id="s1", metrics={"orphan_edge_rate": 1.0}),
        ],
        overall={"orphan_edge_rate": 1.0},
        metadata={"mode": "extraction"},
    )
    report = MarkdownReporter.report(result)
    assert "## Degraded Samples" in report
    assert "orphan_edge_rate=1.0" in report


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
