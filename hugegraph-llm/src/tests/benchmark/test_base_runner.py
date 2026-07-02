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

"""Tests for BaseRunner abstract base class."""

import json
from typing import Any, Dict

import pytest

from hugegraph_llm.benchmark.metrics.base import BaseMetric
from hugegraph_llm.benchmark.models.result import BenchmarkResult
from hugegraph_llm.benchmark.runners.base_runner import BaseRunner

pytestmark = pytest.mark.unit


class _StubRunner(BaseRunner):
    """Minimal concrete runner for testing BaseRunner methods."""

    def run(self, *args: Any, **kwargs: Any) -> BenchmarkResult:
        return self._create_result(mode='stub')


class _SuccessMetric(BaseMetric):
    name = '_test_success'
    requires_llm = False

    def calculate(self, prediction: Any, reference: Any, **kwargs: Any) -> Dict[str, float]:
        return {'score': 1.0}


class _FailMetric(BaseMetric):
    name = '_test_fail'
    requires_llm = False

    def calculate(self, prediction: Any, reference: Any, **kwargs: Any) -> Dict[str, float]:
        raise ValueError('intentional test failure')


def test_baserunnerloaddata_load_data_normal(tmp_path):
    data = {'samples': [{'id': 1}], 'meta': 'ok'}
    p = tmp_path / 'data.json'
    p.write_text(json.dumps(data), encoding='utf-8')
    runner = _StubRunner()
    loaded = runner._load_data(str(p))
    assert loaded == data


def test_baserunnerloaddata_load_data_file_not_found():
    runner = _StubRunner()
    with pytest.raises(FileNotFoundError):
        runner._load_data('/nonexistent/path/data.json')


def test_baserunnerloaddata_load_data_invalid_json(tmp_path):
    p = tmp_path / 'bad.json'
    p.write_text('not valid json {{{', encoding='utf-8')
    runner = _StubRunner()
    with pytest.raises(json.JSONDecodeError):
        runner._load_data(str(p))


def test_baserunnercreatemetricinstances_create_known_metrics():
    runner = _StubRunner()
    instances = runner._create_metric_instances(['entity_f1', 'triple_f1'])
    assert 'entity_f1' in instances
    assert 'triple_f1' in instances
    assert isinstance(instances['entity_f1'], BaseMetric)


def test_baserunnercreatemetricinstances_create_unknown_metric_raises():
    runner = _StubRunner()
    with pytest.raises(KeyError, match='Unknown metric'):
        runner._create_metric_instances(['nonexistent_metric_xyz'])


def test_baserunnerrunmetricsafe_safe_run_success():
    runner = _StubRunner()
    metric = _SuccessMetric()
    scores = runner._run_metric_safe(metric=metric, prediction=[], reference=[], sample_id='s1')
    assert scores == {'score': 1.0}
    assert len(runner._errors) == 0


def test_baserunnerrunmetricsafe_safe_run_failure_records_error():
    runner = _StubRunner()
    metric = _FailMetric()
    scores = runner._run_metric_safe(metric=metric, prediction=[], reference=[], sample_id='s2')
    assert scores == {}
    assert len(runner._errors) == 1
    assert runner._errors[0]['sample_id'] == 's2'
    assert runner._errors[0]['metric'] == '_test_fail'
    assert 'intentional test failure' in runner._errors[0]['error']


def test_baserunnerrunmetricsafe_safe_run_multiple_failures_accumulate():
    runner = _StubRunner()
    metric = _FailMetric()
    for i in range(5):
        runner._run_metric_safe(metric=metric, prediction=[], reference=[], sample_id=f's{i}')
    assert len(runner._errors) == 5


def test_baserunnercreateresult_create_result_has_mode():
    runner = _StubRunner()
    result = runner._create_result(mode='extraction', language='en')
    assert isinstance(result, BenchmarkResult)
    assert result.metadata['mode'] == 'extraction'
    assert result.metadata['language'] == 'en'


def test_baserunnercreateresult_create_result_has_timestamp():
    runner = _StubRunner()
    result = runner._create_result(mode='test')
    assert 'timestamp' in result.metadata


def test_baserunnerfinalizeresult_finalize_no_errors():
    runner = _StubRunner()
    result = runner._create_result(mode='test')
    runner._finalize_result(result)
    assert result.metadata['error_count'] == 0
    assert 'errors' not in result.metadata


def test_baserunnerfinalizeresult_finalize_with_errors():
    runner = _StubRunner()
    runner._errors = [
        {'sample_id': 's1', 'metric': 'm1', 'error': 'err1'},
        {'sample_id': 's2', 'metric': 'm2', 'error': 'err2'},
    ]
    result = runner._create_result(mode='test')
    runner._finalize_result(result)
    assert result.metadata['error_count'] == 2
    assert len(result.metadata['errors']) == 2


def test_baserunnerfinalizeresult_finalize_caps_errors_at_10():
    runner = _StubRunner()
    runner._errors = [{'sample_id': f's{i}', 'metric': 'm', 'error': f'err{i}'} for i in range(20)]
    result = runner._create_result(mode='test')
    runner._finalize_result(result)
    assert result.metadata['error_count'] == 20
    assert len(result.metadata['errors']) == 10
