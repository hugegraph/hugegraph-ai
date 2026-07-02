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

"""Integration tests for ablation benchmark runner."""

import os

import pytest

from hugegraph_llm.benchmark.runners.ablation_runner import AblationRunner

pytestmark = pytest.mark.unit

_SAMPLES_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'hugegraph_llm', 'benchmark', 'data', 'samples')
_ABLATION_DATA = os.path.join(_SAMPLES_DIR, 'ablation_sample.json')


def test_ablationrunnerintegration_ablation_runner_runs_successfully():
    """Run AblationRunner on ablation_sample.json with token_f1 and exact_match."""
    runner = AblationRunner()
    result = runner.run(data_path=_ABLATION_DATA, answer_metrics=['token_f1', 'exact_match'], language='en')
    assert len(result.samples) == 2


def test_ablationrunnerintegration_ablation_runner_four_modes_present():
    """Verify overall keys include prefixed metrics for all four answer modes."""
    runner = AblationRunner()
    result = runner.run(data_path=_ABLATION_DATA, answer_metrics=['token_f1', 'exact_match'], language='en')
    modes = ['raw', 'vector_only', 'graph_only', 'graph_vector']
    for mode in modes:
        assert f'{mode}_token_f1' in result.overall, f"Missing overall key '{mode}_token_f1'"
        assert f'{mode}_exact_match' in result.overall, f"Missing overall key '{mode}_exact_match'"
