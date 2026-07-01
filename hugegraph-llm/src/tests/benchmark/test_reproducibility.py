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

"""Reproducibility tests for benchmark runners."""

import os

import pytest

from hugegraph_llm.benchmark.baseline.store import BaselineStore
from hugegraph_llm.benchmark.runners.extraction_runner import ExtractionRunner
from hugegraph_llm.benchmark.runners.retrieval_runner import RetrievalRunner

pytestmark = pytest.mark.unit

_SAMPLES_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'hugegraph_llm', 'benchmark', 'data', 'samples')
_CAR_DATA = os.path.join(_SAMPLES_DIR, 'car_extraction_sample.json')
_RETRIEVAL_DATA = os.path.join(_SAMPLES_DIR, 'retrieval_sample.json')


def test_reproducibilityextraction_same_input_same_output_extraction():
    """Run ExtractionRunner twice on same data; overall dicts should be identical."""
    runner = ExtractionRunner()
    metrics = ['entity_f1', 'triple_f1']
    result1 = runner.run(data_path=_CAR_DATA, metrics=metrics, language='zh')
    result2 = runner.run(data_path=_CAR_DATA, metrics=metrics, language='zh')
    assert result1.overall == result2.overall


def test_reproducibilityretrieval_same_input_same_output_retrieval():
    """Run RetrievalRunner twice on same data; overall dicts should be identical."""
    runner = RetrievalRunner()
    metrics = ['recall_at_k', 'hit_at_k', 'mrr']
    result1 = runner.run(data_path=_RETRIEVAL_DATA, metrics=metrics)
    result2 = runner.run(data_path=_RETRIEVAL_DATA, metrics=metrics)
    assert result1.overall == result2.overall


def test_baselinesaveloadroundtrip_baseline_save_load_roundtrip(tmp_path):
    """Save baseline via BaselineStore.save(), load it back, compare overall values."""
    runner = ExtractionRunner()
    result = runner.run(data_path=_CAR_DATA, metrics=['entity_f1', 'triple_f1'], language='zh')
    baseline_path = str(tmp_path / 'roundtrip_baseline.json')
    BaselineStore.save(result, baseline_path)
    loaded = BaselineStore.load(baseline_path)
    for key in result.overall:
        assert key in loaded.overall, f"Missing key '{key}' after roundtrip"
        assert abs(result.overall[key] - loaded.overall[key]) < 1e-06, (
            f"Key '{key}': original={result.overall[key]}, loaded={loaded.overall[key]}"
        )
