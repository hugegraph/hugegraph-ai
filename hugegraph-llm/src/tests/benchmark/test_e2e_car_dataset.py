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

"""End-to-end tests specific to the car dataset."""

import json
import os
import subprocess
import sys

import pytest

from hugegraph_llm.benchmark.runners.extraction_runner import ExtractionRunner

pytestmark = pytest.mark.unit

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
_SRC_DIR = os.path.join(_PROJECT_ROOT, 'src')
_SAMPLES_DIR = os.path.join(_SRC_DIR, 'hugegraph_llm', 'benchmark', 'data', 'samples')
_CAR_DATA = os.path.join(_SAMPLES_DIR, 'car_extraction_sample.json')


def _run_cli(*args: str, timeout: int = 60) -> subprocess.CompletedProcess:
    """Run the benchmark CLI as a subprocess."""
    cmd = [sys.executable, '-m', 'hugegraph_llm.benchmark', *args]
    env = os.environ.copy()
    env['PYTHONPATH'] = _SRC_DIR + ':' + env.get('PYTHONPATH', '')
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env, cwd=_PROJECT_ROOT)


def test_cardatasetentityf1_car_dataset_entity_f1_positive():
    """Both samples should have entity_f1 > 0."""
    runner = ExtractionRunner()
    result = runner.run(data_path=_CAR_DATA, metrics=['entity_f1'], language='zh')
    assert len(result.samples) == 2
    for sample in result.samples:
        assert sample.metrics['entity_f1'] > 0, f'Sample {sample.sample_id} has entity_f1 <= 0'


def test_cardatasettriplef1_car_dataset_triple_f1_positive():
    """Both samples should have triple_f1 > 0."""
    runner = ExtractionRunner()
    result = runner.run(data_path=_CAR_DATA, metrics=['triple_f1'], language='zh')
    assert len(result.samples) == 2
    for sample in result.samples:
        assert sample.metrics['triple_f1'] > 0, f'Sample {sample.sample_id} has triple_f1 <= 0'


def test_cardatasetschemavalidity_car_dataset_schema_validity():
    """Run with schema_validity metric; verify type_constraint_pass appears."""
    runner = ExtractionRunner()
    result = runner.run(data_path=_CAR_DATA, metrics=['schema_validity'], language='zh')
    assert len(result.samples) == 2
    for sample in result.samples:
        assert 'type_constraint_pass' in sample.metrics, f'Sample {sample.sample_id} missing type_constraint_pass'


def test_cardatasetpeugeotperfectmatch_car_dataset_peugeot_perfect_match():
    """For Peugeot sample (candidate == gold), entity_f1 and triple_f1 should be 1.0."""
    runner = ExtractionRunner()
    result = runner.run(data_path=_CAR_DATA, metrics=['entity_f1', 'triple_f1'], language='zh')
    peugeot = next((s for s in result.samples if s.sample_id == 'car_peugeot_5008'))
    assert peugeot.metrics['entity_f1'] == 1.0
    assert peugeot.metrics['triple_f1'] == 1.0


def test_cardatasetreportgeneration_car_dataset_report_generation():
    """Run via CLI with --format json; verify JSON parseable and has expected structure."""
    result = _run_cli(
        'run', '--mode', 'extraction', '--data', _CAR_DATA, '--format', 'json', '--offline', '--language', 'zh'
    )
    assert result.returncode == 0, f'stderr: {result.stderr}'
    output = json.loads(result.stdout)
    assert 'meta' in output
    assert 'overall' in output
    assert 'samples' in output
    assert len(output['samples']) == 2
    for sample in output['samples']:
        assert 'sample_id' in sample
        assert 'metrics' in sample
        assert isinstance(sample['metrics'], dict)
