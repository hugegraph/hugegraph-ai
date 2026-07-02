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

"""End-to-end CLI tests for the benchmark module."""

import json
import os
import subprocess
import sys

import pytest

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


def test_e2eextractionpipeline_e2e_extraction_pipeline(tmp_path):
    """Full pipeline: run, save baseline, run again, compare."""
    baseline_path = str(tmp_path / 'baseline.json')
    candidate_path = str(tmp_path / 'candidate.json')
    r1 = _run_cli(
        'run',
        '--mode',
        'extraction',
        '--data',
        _CAR_DATA,
        '--save-baseline',
        baseline_path,
        '--format',
        'json',
        '--offline',
        '--language',
        'zh',
    )
    assert r1.returncode == 0, f'stderr: {r1.stderr}'
    assert os.path.isfile(baseline_path)
    with open(baseline_path, 'r', encoding='utf-8') as f:
        baseline_data = json.load(f)
    assert 'overall' in baseline_data
    r2 = _run_cli(
        'run',
        '--mode',
        'extraction',
        '--data',
        _CAR_DATA,
        '--save-baseline',
        candidate_path,
        '--format',
        'json',
        '--offline',
        '--language',
        'zh',
    )
    assert r2.returncode == 0, f'stderr: {r2.stderr}'
    assert os.path.isfile(candidate_path)
    cmp_result = _run_cli('compare', '--baseline', baseline_path, '--candidate', candidate_path, '--format', 'json')
    assert cmp_result.returncode == 0, f'stderr: {cmp_result.stderr}'
    comparison = json.loads(cmp_result.stdout)
    assert 'overall_diff' in comparison


def test_e2ecardatasetmetrics_e2e_car_dataset_metrics_positive():
    """Run extraction on car dataset; verify entity_f1 > 0 and triple_f1 > 0."""
    result = _run_cli(
        'run', '--mode', 'extraction', '--data', _CAR_DATA, '--format', 'json', '--offline', '--language', 'zh'
    )
    assert result.returncode == 0, f'stderr: {result.stderr}'
    output = json.loads(result.stdout)
    assert output['overall']['entity_f1'] > 0
    assert output['overall']['triple_f1'] > 0


def test_e2ecardatasetmetrics_e2e_markdown_report_contains_table():
    """Run extraction with markdown format; verify table formatting present."""
    result = _run_cli(
        'run', '--mode', 'extraction', '--data', _CAR_DATA, '--format', 'markdown', '--offline', '--language', 'zh'
    )
    assert result.returncode == 0, f'stderr: {result.stderr}'
    assert '|' in result.stdout, 'Markdown output should contain table formatting'


def test_e2ecardatasetmetrics_e2e_smoke_mode_limits_samples():
    """Run extraction with --smoke; verify sample count <= 5."""
    result = _run_cli(
        'run',
        '--mode',
        'extraction',
        '--data',
        _CAR_DATA,
        '--smoke',
        '--format',
        'json',
        '--offline',
        '--language',
        'zh',
    )
    assert result.returncode == 0, f'stderr: {result.stderr}'
    output = json.loads(result.stdout)
    assert len(output['samples']) <= 5


def test_e2ecardatasetmetrics_e2e_baseline_contains_metadata(tmp_path):
    """Run with --save-baseline; verify saved file contains meta with timestamp."""
    baseline_path = str(tmp_path / 'baseline_meta.json')
    result = _run_cli(
        'run',
        '--mode',
        'extraction',
        '--data',
        _CAR_DATA,
        '--save-baseline',
        baseline_path,
        '--format',
        'json',
        '--offline',
        '--language',
        'zh',
    )
    assert result.returncode == 0, f'stderr: {result.stderr}'
    assert os.path.isfile(baseline_path)
    with open(baseline_path, 'r', encoding='utf-8') as f:
        saved = json.load(f)
    assert 'meta' in saved
    assert 'timestamp' in saved['meta']


def test_e2eerrortracking_json_output_contains_error_count():
    """JSON output should include error_count field in metadata."""
    result = _run_cli(
        'run', '--mode', 'extraction', '--data', _CAR_DATA, '--format', 'json', '--offline', '--language', 'zh'
    )
    assert result.returncode == 0, f'stderr: {result.stderr}'
    output = json.loads(result.stdout)
    assert 'meta' in output
    assert 'error_count' in output['meta']


def test_e2eerrortracking_markdown_report_generates_with_errors_field():
    """Markdown report should generate even when error_count is present."""
    result = _run_cli(
        'run', '--mode', 'extraction', '--data', _CAR_DATA, '--format', 'markdown', '--offline', '--language', 'zh'
    )
    assert result.returncode == 0, f'stderr: {result.stderr}'
    assert '|' in result.stdout
