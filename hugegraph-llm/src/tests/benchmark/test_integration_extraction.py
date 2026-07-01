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

"""Integration tests for extraction benchmark runner."""

import json
import os

import pytest

from hugegraph_llm.benchmark.models.result import BenchmarkResult, SampleResult
from hugegraph_llm.benchmark.runners.base_runner import BaseRunner
from hugegraph_llm.benchmark.runners.extraction_runner import ExtractionRunner

pytestmark = pytest.mark.unit

_SAMPLES_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'hugegraph_llm', 'benchmark', 'data', 'samples')
_CAR_DATA = os.path.join(_SAMPLES_DIR, 'car_extraction_sample.json')
_EXTRACTION_DATA = os.path.join(_SAMPLES_DIR, 'extraction_sample.json')


def test_extractionrunnercardataset_extraction_runner_with_car_dataset():
    """Run ExtractionRunner on car_extraction_sample.json with entity_f1 and triple_f1."""
    runner = ExtractionRunner()
    result = runner.run(data_path=_CAR_DATA, metrics=['entity_f1', 'triple_f1'], language='zh')
    assert len(result.samples) == 2
    assert 0 < result.overall['entity_f1'] <= 1
    assert 0 < result.overall['triple_f1'] <= 1
    peugeot = next((s for s in result.samples if s.sample_id == 'car_peugeot_5008'))
    assert peugeot.metrics['entity_f1'] == 1.0
    assert peugeot.metrics['triple_f1'] == 1.0
    audi = next((s for s in result.samples if s.sample_id == 'car_audi_a8'))
    assert audi.metrics['entity_f1'] < 1.0


def test_extractionrunnerstandardsample_extraction_runner_with_standard_sample():
    """Run on extraction_sample.json with default metrics."""
    runner = ExtractionRunner()
    metrics = ['entity_f1', 'triple_f1', 'schema_validity', 'structural_integrity']
    result = runner.run(data_path=_EXTRACTION_DATA, metrics=metrics, language='en')
    assert 'entity_f1' in result.overall
    assert 'entity_precision' in result.overall
    assert 'entity_recall' in result.overall
    assert 'triple_f1' in result.overall
    assert 'triple_precision' in result.overall
    assert 'triple_recall' in result.overall
    assert 'type_constraint_pass' in result.overall
    assert 'required_property_fill' in result.overall
    assert 'illegal_edge_rate' in result.overall
    assert 'orphan_edge_rate' in result.overall
    assert 'duplicate_entity_rate' in result.overall
    assert 'duplicate_edge_rate' in result.overall


@pytest.mark.skipif(not os.path.isfile(_CAR_DATA), reason='car_extraction_sample.json not found')
def test_extractionrunnerresultstructure_extraction_runner_benchmark_result_structure():
    """Verify BenchmarkResult has correct structure."""
    runner = ExtractionRunner()
    result = runner.run(data_path=_CAR_DATA, metrics=['entity_f1'], language='zh')
    assert isinstance(result, BenchmarkResult)
    assert result.metadata['mode'] == 'extraction'
    assert result.metadata['language'] == 'zh'
    assert result.metadata['metrics'] == ['entity_f1']
    assert result.metadata['data_path'] == _CAR_DATA
    assert all((isinstance(s, SampleResult) for s in result.samples))
    assert isinstance(result.overall, dict)
    assert len(result.overall) > 0


def test_extractionrunnerdatacoupling_all_extraction_metrics_receive_correct_data():
    """Run with all extraction metrics; verify each produces expected keys."""
    runner = ExtractionRunner()
    metrics = [
        'entity_f1',
        'triple_f1',
        'property_f1',
        'schema_validity',
        'structural_integrity',
        'graph_structure',
        'conflict_detection',
        'temporal_validity',
    ]
    result = runner.run(data_path=_EXTRACTION_DATA, metrics=metrics, language='en')
    assert 'entity_f1' in result.overall
    assert 'triple_f1' in result.overall
    assert 'property_f1' in result.overall
    assert 'type_constraint_pass' in result.overall
    assert 'orphan_edge_rate' in result.overall
    assert 'duplicate_entity_rate' in result.overall
    assert 'num_nodes' in result.overall
    assert 'density' in result.overall
    assert 'conflict_rate' in result.overall
    assert 'num_conflicts' in result.overall
    assert 'temporal_valid_rate' in result.overall


def test_extractionrunnerdatacoupling_structural_integrity_receives_dict_format():
    """Verify structural_integrity gets vertices+edges dict, not just vertex list."""
    runner = ExtractionRunner()
    result = runner.run(data_path=_EXTRACTION_DATA, metrics=['structural_integrity'], language='en')
    assert 'orphan_edge_rate' in result.overall
    assert 'duplicate_entity_rate' in result.overall
    assert 'duplicate_edge_rate' in result.overall


def test_extractionrunnerschemavalidity_receives_edges(tmp_path):
    """Schema validity must score illegal candidate edges, not only vertices."""
    data_file = tmp_path / 'schema_edges.json'
    data_file.write_text(
        json.dumps(
            {
                'schema': {
                    'vertexlabels': [{'name': 'person', 'primary_keys': ['name']}],
                    'edgelabels': [{'name': 'knows', 'source_label': 'person', 'target_label': 'person'}],
                },
                'samples': [
                    {
                        'sample_id': 'bad_edge',
                        'gold_vertices': [],
                        'gold_edges': [],
                        'candidate_vertices': [
                            {'label': 'person', 'name': 'Alice', 'properties': {'name': 'Alice'}},
                            {'label': 'company', 'name': 'Acme', 'properties': {'name': 'Acme'}},
                        ],
                        'candidate_edges': [{'label': 'works_at', 'outV': 'Alice', 'inV': 'Acme'}],
                    }
                ],
            }
        ),
        encoding='utf-8',
    )

    runner = ExtractionRunner()
    result = runner.run(data_path=str(data_file), metrics=['schema_validity'], language='en')
    assert result.samples[0].metrics['illegal_edge_rate'] == 1.0


def test_extractionrunnerpropertyf1_receives_edge_properties(tmp_path):
    """Property F1 must include edge properties as well as vertex properties."""
    data_file = tmp_path / 'edge_properties.json'
    data_file.write_text(
        json.dumps(
            {
                'samples': [
                    {
                        'sample_id': 'edge_property',
                        'candidate_vertices': [{'label': 'person', 'properties': {'name': 'Alice'}}],
                        'gold_vertices': [{'label': 'person', 'properties': {'name': 'Alice'}}],
                        'candidate_edges': [
                            {'outV': 'Alice', 'inV': 'Bob', 'label': 'knows', 'properties': {'since': '2020'}}
                        ],
                        'gold_edges': [
                            {'outV': 'Alice', 'inV': 'Bob', 'label': 'knows', 'properties': {'since': '2021'}}
                        ],
                    }
                ],
            }
        ),
        encoding='utf-8',
    )

    runner = ExtractionRunner()
    result = runner.run(data_path=str(data_file), metrics=['property_f1'], language='en')
    assert result.samples[0].metrics['property_f1'] == 0.5


def test_extractionrunnererrortracking_error_count_present_in_metadata():
    """Every result should have error_count in metadata."""
    runner = ExtractionRunner()
    result = runner.run(data_path=_EXTRACTION_DATA, metrics=['entity_f1'], language='en')
    assert 'error_count' in result.metadata
    assert result.metadata['error_count'] == 0


def test_extractionrunnererrortracking_error_tracking_with_bad_sample(tmp_path):
    """Inject a malformed sample and verify errors are tracked."""
    bad_data = {'schema': {}, 'samples': [{'sample_id': 'bad_001', 'input_text': 'test'}]}
    data_file = tmp_path / 'bad_data.json'
    data_file.write_text(json.dumps(bad_data), encoding='utf-8')
    runner = ExtractionRunner()
    result = runner.run(data_path=str(data_file), metrics=['entity_f1'], language='en')
    assert isinstance(result, BenchmarkResult)
    assert 'error_count' in result.metadata


def test_extractionrunnererrortracking_runner_inherits_base_runner():
    """ExtractionRunner should inherit from BaseRunner."""
    assert issubclass(ExtractionRunner, BaseRunner)
