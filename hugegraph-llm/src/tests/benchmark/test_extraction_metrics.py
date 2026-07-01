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

"""Tests for graph extraction metrics: EntityF1, TripleF1, SchemaValidity,
StructuralIntegrity, SyntaxValidity."""

import pytest

from hugegraph_llm.benchmark.metrics.extraction.entity_f1 import EntityF1
from hugegraph_llm.benchmark.metrics.extraction.schema_validity import SchemaValidity
from hugegraph_llm.benchmark.metrics.extraction.structural_integrity import StructuralIntegrity
from hugegraph_llm.benchmark.metrics.extraction.syntax_validity import SyntaxValidity
from hugegraph_llm.benchmark.metrics.extraction.triple_f1 import TripleF1

pytestmark = pytest.mark.unit


def test_entityf1_perfect_match():
    metric = EntityF1()
    pred = [{'label': 'person', 'name': 'Alice'}, {'label': 'person', 'name': 'Bob'}]
    ref = [{'label': 'person', 'name': 'Alice'}, {'label': 'person', 'name': 'Bob'}]
    result = metric.calculate(pred, ref)
    assert result['entity_f1'] == 1.0
    assert result['entity_precision'] == 1.0
    assert result['entity_recall'] == 1.0


def test_entityf1_complete_miss():
    metric = EntityF1()
    pred = [{'label': 'person', 'name': 'Charlie'}]
    ref = [{'label': 'person', 'name': 'Alice'}, {'label': 'person', 'name': 'Bob'}]
    result = metric.calculate(pred, ref)
    assert result['entity_f1'] == 0.0
    assert result['entity_precision'] == 0.0
    assert result['entity_recall'] == 0.0


def test_entityf1_partial_match():
    metric = EntityF1()
    pred = [{'label': 'person', 'name': 'Alice'}, {'label': 'person', 'name': 'Charlie'}]
    ref = [{'label': 'person', 'name': 'Alice'}, {'label': 'person', 'name': 'Bob'}]
    result = metric.calculate(pred, ref)
    assert result['entity_precision'] == 0.5
    assert result['entity_recall'] == 0.5
    assert result['entity_f1'] == 0.5


def test_entityf1_empty_inputs():
    metric = EntityF1()
    result = metric.calculate([], [])
    assert result['entity_f1'] == 0.0


def test_entityf1_name_from_properties():
    metric = EntityF1()
    # Vertices can store name inside properties dict.
    pred = [{'label': 'person', 'properties': {'name': 'Alice'}}]
    ref = [{'label': 'person', 'name': 'Alice'}]
    result = metric.calculate(pred, ref)
    assert result['entity_f1'] == 1.0


def test_entityf1_case_insensitive_matching():
    metric = EntityF1()
    pred = [{'label': 'Person', 'name': 'ALICE'}]
    ref = [{'label': 'person', 'name': 'alice'}]
    result = metric.calculate(pred, ref)
    assert result['entity_f1'] == 1.0


def test_entityf1_non_list_input_returns_zero():
    metric = EntityF1()
    result = metric.calculate('not_a_list', 'also_not_a_list')
    assert result['entity_f1'] == 0.0


def test_triplef1_correct_triples():
    metric = TripleF1()
    pred = [{'outV': 'Alice', 'label': 'knows', 'inV': 'Bob'}]
    ref = [{'outV': 'Alice', 'label': 'knows', 'inV': 'Bob'}]
    result = metric.calculate(pred, ref)
    assert result['triple_f1'] == 1.0
    assert result['triple_precision'] == 1.0
    assert result['triple_recall'] == 1.0


def test_triplef1_wrong_direction():
    metric = TripleF1()
    # Reversed direction should not match.
    pred = [{'outV': 'Bob', 'label': 'knows', 'inV': 'Alice'}]
    ref = [{'outV': 'Alice', 'label': 'knows', 'inV': 'Bob'}]
    result = metric.calculate(pred, ref)
    assert result['triple_f1'] == 0.0


def test_triplef1_extra_triples():
    metric = TripleF1()
    pred = [{'outV': 'Alice', 'label': 'knows', 'inV': 'Bob'}, {'outV': 'Alice', 'label': 'knows', 'inV': 'Charlie'}]
    ref = [{'outV': 'Alice', 'label': 'knows', 'inV': 'Bob'}]
    result = metric.calculate(pred, ref)
    assert result['triple_precision'] == 0.5
    assert result['triple_recall'] == 1.0
    assert abs(result['triple_f1'] - 0.6667) < 0.001


def test_triplef1_empty_inputs():
    metric = TripleF1()
    result = metric.calculate([], [])
    assert result['triple_f1'] == 0.0


def test_triplef1_outvlabel_invelabel_fields():
    metric = TripleF1()
    # Support outVLabel/inVLabel as alternative field names.
    pred = [{'outVLabel': 'Alice', 'label': 'knows', 'inVLabel': 'Bob'}]
    ref = [{'outV': 'Alice', 'label': 'knows', 'inV': 'Bob'}]
    result = metric.calculate(pred, ref)
    assert result['triple_f1'] == 1.0


def test_schemavalidity_all_legal_labels():
    metric = SchemaValidity()
    schema = {
        'vertexlabels': [{'name': 'person', 'primary_keys': ['name']}],
        'edgelabels': [{'name': 'knows', 'source_label': 'person', 'target_label': 'person'}],
    }
    items = [
        {'label': 'person', 'name': 'Alice', 'properties': {'name': 'Alice'}},
        {'label': 'person', 'name': 'Bob', 'properties': {'name': 'Bob'}},
    ]
    result = metric.calculate(items, None, schema=schema)
    assert result['type_constraint_pass'] == 1.0


def test_schemavalidity_illegal_label():
    metric = SchemaValidity()
    schema = {
        'vertexlabels': [{'name': 'person', 'primary_keys': ['name']}],
        'edgelabels': [{'name': 'knows', 'source_label': 'person', 'target_label': 'person'}],
    }
    items = [
        {'label': 'person', 'name': 'Alice', 'properties': {'name': 'Alice'}},
        {'label': 'company', 'name': 'Acme', 'properties': {'name': 'Acme'}},
    ]
    result = metric.calculate(items, None, schema=schema)
    assert result['type_constraint_pass'] == 0.5


def test_schemavalidity_required_property_missing():
    metric = SchemaValidity()
    schema = {
        'vertexlabels': [{'name': 'person', 'primary_keys': ['name']}],
        'edgelabels': [{'name': 'knows', 'source_label': 'person', 'target_label': 'person'}],
    }
    items = [{'label': 'person', 'name': 'Alice', 'properties': {}}]
    result = metric.calculate(items, None, schema=schema)
    assert result['required_property_fill'] == 0.0


def test_schemavalidity_required_property_present():
    metric = SchemaValidity()
    schema = {
        'vertexlabels': [{'name': 'person', 'primary_keys': ['name']}],
        'edgelabels': [{'name': 'knows', 'source_label': 'person', 'target_label': 'person'}],
    }
    items = [{'label': 'person', 'name': 'Alice', 'properties': {'name': 'Alice'}}]
    result = metric.calculate(items, None, schema=schema)
    assert result['required_property_fill'] == 1.0


def test_schemavalidity_no_schema_returns_zeros():
    metric = SchemaValidity()
    items = [{'label': 'person', 'name': 'Alice'}]
    result = metric.calculate(items, None)
    assert result['type_constraint_pass'] == 0.0
    assert result['required_property_fill'] == 0.0
    assert result['illegal_edge_rate'] == 0.0


def test_schemavalidity_illegal_edge_endpoint():
    metric = SchemaValidity()
    schema = {
        'vertexlabels': [{'name': 'person', 'primary_keys': ['name']}],
        'edgelabels': [{'name': 'knows', 'source_label': 'person', 'target_label': 'person'}],
    }
    # Edge with endpoint label not matching schema.
    items = [
        {'label': 'person', 'name': 'Alice', 'properties': {'name': 'Alice'}},
        {'label': 'company', 'name': 'Acme', 'properties': {'name': 'Acme'}},
        {'label': 'knows', 'outV': 'Alice', 'inV': 'Acme'},
    ]
    result = metric.calculate(items, None, schema=schema)
    assert result['illegal_edge_rate'] > 0.0


def test_structuralintegrity_clean_graph():
    metric = StructuralIntegrity()
    prediction = {
        'vertices': [{'label': 'person', 'name': 'Alice'}, {'label': 'person', 'name': 'Bob'}],
        'edges': [{'outV': 'Alice', 'label': 'knows', 'inV': 'Bob'}],
    }
    result = metric.calculate(prediction, None)
    assert result['orphan_edge_rate'] == 0.0
    assert result['duplicate_entity_rate'] == 0.0
    assert result['duplicate_edge_rate'] == 0.0


def test_structuralintegrity_orphan_edge():
    metric = StructuralIntegrity()
    # Edge referencing a vertex not in the vertex set.
    prediction = {
        'vertices': [{'label': 'person', 'name': 'Alice'}],
        'edges': [{'outV': 'Alice', 'label': 'knows', 'inV': 'Ghost'}],
    }
    result = metric.calculate(prediction, None)
    assert result['orphan_edge_rate'] == 1.0


def test_structuralintegrity_duplicate_entity():
    metric = StructuralIntegrity()
    prediction = {'vertices': [{'label': 'person', 'name': 'Alice'}, {'label': 'person', 'name': 'Alice'}], 'edges': []}
    result = metric.calculate(prediction, None)
    assert result['duplicate_entity_rate'] == 0.5


def test_structuralintegrity_duplicate_edge():
    metric = StructuralIntegrity()
    prediction = {
        'vertices': [{'label': 'person', 'name': 'Alice'}, {'label': 'person', 'name': 'Bob'}],
        'edges': [{'outV': 'Alice', 'label': 'knows', 'inV': 'Bob'}, {'outV': 'Alice', 'label': 'knows', 'inV': 'Bob'}],
    }
    result = metric.calculate(prediction, None)
    assert result['duplicate_edge_rate'] == 0.5


def test_structuralintegrity_non_dict_prediction():
    metric = StructuralIntegrity()
    result = metric.calculate('not_a_dict', None)
    assert result['orphan_edge_rate'] == 0.0
    assert result['duplicate_entity_rate'] == 0.0
    assert result['duplicate_edge_rate'] == 0.0


def test_syntaxvalidity_all_parsed_successfully():
    metric = SyntaxValidity()
    prediction = {'raw_responses': ['json1', 'json2'], 'parse_results': [{'v': 1}, {'v': 2}]}
    result = metric.calculate(prediction, None)
    assert result['json_parse_rate'] == 1.0


def test_syntaxvalidity_parse_failure():
    metric = SyntaxValidity()
    prediction = {'raw_responses': ['bad_json'], 'parse_results': [None]}
    result = metric.calculate(prediction, None)
    assert result['json_parse_rate'] == 0.0


def test_syntaxvalidity_mixed_parse():
    metric = SyntaxValidity()
    prediction = {'raw_responses': ['ok', 'bad'], 'parse_results': [{'v': 1}, None]}
    result = metric.calculate(prediction, None)
    assert result['json_parse_rate'] == 0.5


def test_syntaxvalidity_db_load_success():
    metric = SyntaxValidity()
    prediction = {'raw_responses': ['json1'], 'parse_results': [{'v': 1}]}
    result = metric.calculate(prediction, None, db_load_results=[True, True])
    assert result['load_to_db_success'] == 1.0


def test_syntaxvalidity_db_load_partial_failure():
    metric = SyntaxValidity()
    prediction = {'raw_responses': ['json1'], 'parse_results': [{'v': 1}]}
    result = metric.calculate(prediction, None, db_load_results=[True, False])
    assert result['load_to_db_success'] == 0.5


def test_syntaxvalidity_non_dict_prediction():
    metric = SyntaxValidity()
    result = metric.calculate('not_a_dict', None)
    assert result['json_parse_rate'] == 0.0
    assert result['load_to_db_success'] == 0.0
