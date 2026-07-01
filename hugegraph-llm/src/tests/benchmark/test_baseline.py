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

"""Tests for BaselineStore save/load and BaselineComparator regression detection."""

import os

import pytest

from hugegraph_llm.benchmark.baseline.compare import BaselineComparator
from hugegraph_llm.benchmark.baseline.store import BaselineStore
from hugegraph_llm.benchmark.models.result import BenchmarkResult, SampleResult

pytestmark = pytest.mark.unit


def _make_result(sample_metrics: list[dict], overall: dict | None = None) -> BenchmarkResult:
    """Build a BenchmarkResult from a list of per-sample metric dicts."""
    samples = [SampleResult(sample_id=f's{i:03d}', metrics=m) for i, m in enumerate(sample_metrics)]
    result = BenchmarkResult(samples=samples, metadata={'mode': 'test'})
    if overall is not None:
        result.overall = overall
    else:
        result.compute_overall()
    return result


def test_baselinestore_save_load_roundtrip(tmp_path):
    original = _make_result([{'entity_f1': 0.9, 'triple_f1': 0.8}])
    path = str(tmp_path / 'baseline.json')
    BaselineStore.save(original, path)
    loaded = BaselineStore.load(path)
    assert loaded.overall == original.overall
    assert len(loaded.samples) == len(original.samples)
    assert loaded.samples[0].sample_id == 's000'
    assert loaded.samples[0].metrics['entity_f1'] == 0.9


def test_baselinestore_save_creates_parent_dirs(tmp_path):
    path = str(tmp_path / 'nested' / 'dir' / 'baseline.json')
    result = _make_result([{'metric_a': 0.5}])
    BaselineStore.save(result, path)
    assert os.path.isfile(path)


def test_baselinestore_load_preserves_metadata(tmp_path):
    original = _make_result([{'f1': 0.7}])
    original.metadata['custom_key'] = 'custom_value'
    path = str(tmp_path / 'meta_test.json')
    BaselineStore.save(original, path)
    loaded = BaselineStore.load(path)
    assert loaded.metadata.get('custom_key') == 'custom_value'
    assert 'timestamp' in loaded.metadata
    assert 'git_commit' in loaded.metadata


def test_baselinestore_list_baselines(tmp_path):
    for name in ['a.json', 'b.json']:
        result = _make_result([{'x': 0.1}])
        BaselineStore.save(result, str(tmp_path / name))
    baselines = BaselineStore.list_baselines(str(tmp_path))
    assert len(baselines) == 2
    filenames = {b['filename'] for b in baselines}
    assert filenames == {'a.json', 'b.json'}


def test_baselinestore_list_baselines_empty_dir(tmp_path):
    empty_dir = str(tmp_path / 'empty')
    os.makedirs(empty_dir, exist_ok=True)
    assert BaselineStore.list_baselines(empty_dir) == []


def test_baselinestore_list_baselines_nonexistent_dir():
    assert BaselineStore.list_baselines('/nonexistent/path/xyz') == []


def test_baselinecomparator_no_regression():
    baseline = _make_result([{'f1': 0.8}])
    candidate = _make_result([{'f1': 0.85}])
    comparison = BaselineComparator.compare(baseline, candidate)
    assert len(comparison.regressed_samples) == 0
    assert comparison.overall_diff['f1'] > 0


def test_baselinecomparator_regression_detected():
    baseline = _make_result([{'f1': 0.9}])
    candidate = _make_result([{'f1': 0.5}])
    comparison = BaselineComparator.compare(baseline, candidate)
    assert len(comparison.regressed_samples) == 1
    assert 'f1' in comparison.regressed_samples[0]['regressions']


def test_baselinecomparator_improvement_detected():
    baseline = _make_result([{'f1': 0.5}])
    candidate = _make_result([{'f1': 0.9}])
    comparison = BaselineComparator.compare(baseline, candidate)
    assert len(comparison.improved_samples) == 1
    assert 'f1' in comparison.improved_samples[0]['improvements']


def test_baselinecomparator_within_delta_not_flagged():
    """Small differences within delta should not be flagged."""
    baseline = _make_result([{'f1': 0.8}])
    candidate = _make_result([{'f1': 0.79}])
    comparison = BaselineComparator.compare(baseline, candidate, delta=0.05)
    assert len(comparison.regressed_samples) == 0


def test_baselinecomparator_llm_judge_metric_higher_threshold():
    """LLM-Judge metrics should use higher delta (0.05)."""
    baseline = _make_result([{'llm_judge_score': 0.8}])
    candidate = _make_result([{'llm_judge_score': 0.77}])
    comparison = BaselineComparator.compare(baseline, candidate, delta=0.0)
    assert len(comparison.regressed_samples) == 0
    candidate2 = _make_result([{'llm_judge_score': 0.74}])
    comparison2 = BaselineComparator.compare(baseline, candidate2, delta=0.0)
    assert len(comparison2.regressed_samples) == 1


def test_baselinecomparator_actual_llm_metric_names_use_higher_threshold():
    """Real LLM metric names should use the same 0.05 variance threshold."""
    baseline = _make_result([{'answer_correctness': 0.8}])
    candidate = _make_result([{'answer_correctness': 0.77}])
    comparison = BaselineComparator.compare(baseline, candidate, delta=0.0)
    assert len(comparison.regressed_samples) == 0

    candidate2 = _make_result([{'answer_correctness': 0.74}])
    comparison2 = BaselineComparator.compare(baseline, candidate2, delta=0.0)
    assert len(comparison2.regressed_samples) == 1


def test_benchmarkresult_compute_overall_clears_stale_scores():
    result = _make_result([{'f1': 0.8}])
    assert result.overall == {'f1': 0.8}
    result.samples = []
    result.compute_overall()
    assert result.overall == {}


def test_baselinecomparator_overall_diff_computed():
    baseline = _make_result([{'f1': 0.8, 'recall': 0.7}])
    candidate = _make_result([{'f1': 0.9, 'recall': 0.6}])
    comparison = BaselineComparator.compare(baseline, candidate)
    assert abs(comparison.overall_diff['f1'] - 0.1) < 0.001
    assert abs(comparison.overall_diff['recall'] - -0.1) < 0.001


def test_baselinecomparator_reference_scores_included():
    baseline = _make_result([{'f1': 0.8}])
    candidate = _make_result([{'f1': 0.9}])
    reference = _make_result([{'f1': 0.95}])
    comparison = BaselineComparator.compare(baseline, candidate, reference=reference)
    assert 'f1' in comparison.overall_reference
    assert comparison.overall_reference['f1'] == 0.95


def test_baselinecomparator_comparison_result_regressed_samples_structure():
    baseline = _make_result([{'f1': 0.9}])
    candidate = _make_result([{'f1': 0.5}])
    comparison = BaselineComparator.compare(baseline, candidate)
    regressed = comparison.regressed_samples[0]
    assert 'sample_id' in regressed
    assert 'regressions' in regressed
    assert 'baseline_metrics' in regressed
    assert 'candidate_metrics' in regressed
    assert regressed['sample_id'] == 's000'
