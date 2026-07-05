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

"""CLI integration tests for the benchmark module."""

import argparse
import json
import os
import subprocess
import sys
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.unit

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
_SRC_DIR = os.path.join(_PROJECT_ROOT, 'src')
_SAMPLES_DIR = os.path.join(_SRC_DIR, 'hugegraph_llm', 'benchmark', 'data', 'samples')
_EXTRACTION_DATA = os.path.join(_SAMPLES_DIR, 'extraction_sample.json')
_RETRIEVAL_DATA = os.path.join(_SAMPLES_DIR, 'retrieval_docid_sample.json')


def _run_cli(*args: str, timeout: int = 60) -> subprocess.CompletedProcess:
    """Run the benchmark CLI as a subprocess."""
    cmd = [sys.executable, '-m', 'hugegraph_llm.benchmark', *args]
    env = os.environ.copy()
    env['PYTHONPATH'] = _SRC_DIR + ':' + env.get('PYTHONPATH', '')
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env, cwd=_PROJECT_ROOT)


def test_clirunextraction_extraction_runs_successfully():
    result = _run_cli('run', '--mode', 'extraction', '--data', _EXTRACTION_DATA, '--format', 'json')
    assert result.returncode == 0, f'stderr: {result.stderr}'
    output = json.loads(result.stdout)
    assert 'overall' in output
    assert 'samples' in output


def test_clirunextraction_extraction_smoke_mode():
    result = _run_cli('run', '--mode', 'extraction', '--data', _EXTRACTION_DATA, '--smoke', '--format', 'json')
    assert result.returncode == 0, f'stderr: {result.stderr}'
    output = json.loads(result.stdout)
    assert len(output['samples']) <= 5


def test_clirunretrieval_retrieval_runs_successfully():
    result = _run_cli('run', '--mode', 'retrieval', '--data', _RETRIEVAL_DATA, '--format', 'json')
    assert result.returncode == 0, f'stderr: {result.stderr}'
    output = json.loads(result.stdout)
    assert 'overall' in output
    assert 'samples' in output
    assert len(output['samples']) == 3


def test_clirunretrieval_retrieval_smoke_mode():
    result = _run_cli('run', '--mode', 'retrieval', '--data', _RETRIEVAL_DATA, '--smoke', '--format', 'json')
    assert result.returncode == 0, f'stderr: {result.stderr}'
    output = json.loads(result.stdout)
    assert len(output['samples']) <= 5


def test_clirunretrieval_samples_filter_recomputes_by_type(tmp_path):
    data_path = tmp_path / 'typed_retrieval.json'
    data_path.write_text(
        json.dumps(
            {
                'samples': [
                    {
                        'sample_id': 'keep',
                        'question': 'Which doc is relevant?',
                        'question_type': 'Fact Retrieval',
                        'gold_doc_ids': ['doc_a'],
                        'retrieved_doc_ids': ['doc_a'],
                    },
                    {
                        'sample_id': 'drop',
                        'question': 'Which doc is relevant?',
                        'question_type': 'Complex Reasoning',
                        'gold_doc_ids': ['doc_b'],
                        'retrieved_doc_ids': ['doc_b'],
                    },
                ]
            }
        ),
        encoding='utf-8',
    )
    result = _run_cli(
        'run',
        '--mode',
        'retrieval',
        '--data',
        str(data_path),
        '--samples',
        'keep',
        '--metrics',
        'recall_at_k',
        '--format',
        'json',
    )
    assert result.returncode == 0, f'stderr: {result.stderr}'
    output = json.loads(result.stdout)
    assert [sample['sample_id'] for sample in output['samples']] == ['keep']
    assert set(output['by_type']) == {'Fact Retrieval'}


def test_clirunall_skips_unsupported_modes_for_single_schema():
    result = _run_cli('run', '--mode', 'all', '--data', _EXTRACTION_DATA, '--format', 'json', '--offline')
    assert result.returncode == 0, f'stderr: {result.stderr}'
    output = json.loads(result.stdout)
    assert output['meta']['mode'] == 'extraction'
    assert output['meta']['skipped_modes'] == ['retrieval', 'ablation']


def test_clirunall_output_uses_envelope_for_multiple_results(tmp_path):
    data_path = tmp_path / 'multi_mode.json'
    output_path = tmp_path / 'out.json'
    data_path.write_text(
        json.dumps(
            {
                'schema': {
                    'vertexlabels': [{'name': 'person', 'primary_keys': ['name']}],
                    'edgelabels': [{'name': 'knows', 'source_label': 'person', 'target_label': 'person'}],
                },
                'samples': [
                    {
                        'sample_id': 'multi_001',
                        'gold_vertices': [{'label': 'person', 'properties': {'name': 'Alice'}}],
                        'candidate_vertices': [{'label': 'person', 'properties': {'name': 'Alice'}}],
                        'gold_edges': [],
                        'candidate_edges': [],
                        'gold_doc_ids': ['doc_a'],
                        'retrieved_doc_ids': ['doc_a', 'doc_b'],
                        'gold_answer': 'Alice',
                        'raw_answer': 'Alice',
                        'vector_only_answer': 'Alice',
                        'graph_only_answer': 'Alice',
                        'graph_vector_answer': 'Alice',
                    }
                ],
            }
        ),
        encoding='utf-8',
    )

    result = _run_cli(
        'run',
        '--mode',
        'all',
        '--data',
        str(data_path),
        '--format',
        'json',
        '--offline',
        '--output',
        str(output_path),
    )
    assert result.returncode == 0, f'stderr: {result.stderr}'
    output = json.loads(output_path.read_text(encoding='utf-8'))
    assert set(output['results']) == {'extraction', 'retrieval', 'ablation'}


def test_clirunretrieval_rejects_mode_mismatched_metric():
    result = _run_cli(
        'run',
        '--mode',
        'retrieval',
        '--data',
        _RETRIEVAL_DATA,
        '--metrics',
        'entity_f1',
        '--format',
        'json',
    )
    assert result.returncode == 2
    assert 'not valid for retrieval mode' in result.stderr


def test_clirunretrieval_rejects_offline_llm_metric():
    result = _run_cli(
        'run',
        '--mode',
        'retrieval',
        '--data',
        _RETRIEVAL_DATA,
        '--metrics',
        'context_relevancy',
        '--offline',
        '--format',
        'json',
    )
    assert result.returncode == 2
    assert 'require online mode' in result.stderr


def test_clicompare_compare_two_baselines(tmp_path):
    """Generate two baselines via run+save-baseline, then compare."""
    baseline_path = str(tmp_path / 'baseline.json')
    candidate_path = str(tmp_path / 'candidate.json')
    r1 = _run_cli(
        'run', '--mode', 'retrieval', '--data', _RETRIEVAL_DATA, '--save-baseline', baseline_path, '--format', 'json'
    )
    assert r1.returncode == 0, f'stderr: {r1.stderr}'
    assert os.path.isfile(baseline_path)
    r2 = _run_cli(
        'run', '--mode', 'retrieval', '--data', _RETRIEVAL_DATA, '--save-baseline', candidate_path, '--format', 'json'
    )
    assert r2.returncode == 0, f'stderr: {r2.stderr}'
    assert os.path.isfile(candidate_path)
    cmp_result = _run_cli('compare', '--baseline', baseline_path, '--candidate', candidate_path, '--format', 'json')
    assert cmp_result.returncode == 0, f'stderr: {cmp_result.stderr}'
    comparison = json.loads(cmp_result.stdout)
    assert 'overall_diff' in comparison
    assert 'regressed_samples' in comparison
    assert len(comparison['regressed_samples']) == 0


def test_clihelp_no_command_shows_help():
    result = _run_cli()
    assert result.returncode == 1


def test_clihelp_run_missing_data_errors():
    result = _run_cli('run', '--data', '/nonexistent/file.json')
    assert result.returncode != 0
    assert 'not found' in result.stderr.lower() or 'error' in result.stderr.lower()


def test_createllmclient_uses_fixed_judge_params():
    """_create_llm_client builds an OpenAI-compatible client with fixed temperature/seed."""
    from hugegraph_llm.benchmark.cli import _create_llm_client

    class _FakeSettings:
        openai_chat_api_key = "test-key"
        openai_chat_api_base = "https://test.example/v1"
        openai_chat_language_model = "test-model"
        openai_chat_tokens = 1024

    fake_choice = MagicMock()
    fake_choice.message.content = "json response"
    fake_response = MagicMock()
    fake_response.choices = [fake_choice]

    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = fake_response

    with patch("hugegraph_llm.benchmark.cli.OpenAI", return_value=fake_client) as mock_openai:
        llm, meta = _create_llm_client(settings=_FakeSettings())

    assert meta == {"model": "test-model", "temperature": 0.0, "seed": 42}
    mock_openai.assert_called_once_with(api_key="test-key", base_url="https://test.example/v1")
    response = llm.generate(prompt="hello")
    fake_client.chat.completions.create.assert_called_once_with(
        model="test-model",
        messages=[{"role": "user", "content": "hello"}],
        temperature=0.0,
        max_tokens=1024,
        seed=42,
    )
    assert response == "json response"


def test_handlerun_attaches_llm_metadata_and_saves_baseline(tmp_path):
    """LLM metadata is attached to results and persisted by save-baseline."""
    from hugegraph_llm.benchmark.cli import _handle_run

    baseline_path = str(tmp_path / "baseline.json")
    args = argparse.Namespace(
        mode="retrieval",
        data=_RETRIEVAL_DATA,
        metrics="recall_at_k",
        offline=False,
        language="en",
        max_workers=1,
        smoke=False,
        samples=None,
        save_baseline=baseline_path,
        format="json",
        output=None,
    )

    fake_llm = MagicMock()
    fake_meta = {"model": "gpt-4.1-mini", "temperature": 0.0, "seed": 42}

    with patch("hugegraph_llm.benchmark.cli._create_llm_client", return_value=(fake_llm, fake_meta)):
        _handle_run(args)

    assert os.path.isfile(baseline_path)
    data = json.loads(open(baseline_path, encoding="utf-8").read())
    assert data["meta"]["model"] == "gpt-4.1-mini"
    assert data["meta"]["temperature"] == 0.0
    assert data["meta"]["seed"] == 42
    assert "git_commit" in data["meta"]
    assert "timestamp" in data["meta"]
