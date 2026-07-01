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

"""Integration tests for retrieval benchmark runner."""

import os

import pytest

from hugegraph_llm.benchmark.runners.retrieval_runner import RetrievalRunner

pytestmark = pytest.mark.unit

_SAMPLES_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'hugegraph_llm', 'benchmark', 'data', 'samples')
_RETRIEVAL_DATA = os.path.join(_SAMPLES_DIR, 'retrieval_sample.json')
_ZH_RETRIEVAL_DATA = os.path.join(_SAMPLES_DIR, 'chinese_retrieval_sample.json')


def test_retrievalrunnerintegration_retrieval_runner_runs_successfully():
    """Run RetrievalRunner on retrieval_sample.json with standard metrics."""
    runner = RetrievalRunner()
    result = runner.run(data_path=_RETRIEVAL_DATA, metrics=['recall_at_k', 'hit_at_k', 'mrr'])
    assert len(result.samples) == 3
    assert 'recall@1' in result.overall
    assert 'mrr' in result.overall


def test_retrievalrunnerintegration_retrieval_runner_all_metrics_present():
    """Verify that every sample has all expected metric keys."""
    runner = RetrievalRunner()
    result = runner.run(data_path=_RETRIEVAL_DATA, metrics=['recall_at_k', 'hit_at_k', 'mrr'])
    expected_keys = set()
    for k in [1, 5, 10, 20]:
        expected_keys.add(f'recall@{k}')
        expected_keys.add(f'hit_any@{k}')
        expected_keys.add(f'hit_all@{k}')
    expected_keys.add('mrr')
    for sample in result.samples:
        for key in expected_keys:
            assert key in sample.metrics, f"Sample {sample.sample_id} missing metric key '{key}'"


def test_retrievalrunnerintegration_chinese_sample_runs_successfully():
    """Chinese retrieval sample keeps Issue #75 sample coverage explicit."""
    runner = RetrievalRunner()
    result = runner.run(data_path=_ZH_RETRIEVAL_DATA, metrics=['recall_at_k', 'hit_at_k', 'mrr'], language='zh')
    assert len(result.samples) == 2
    assert result.overall['recall@1'] == 0.75
    assert result.overall['mrr'] == 1.0
