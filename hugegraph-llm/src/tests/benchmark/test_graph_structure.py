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

"""Tests for GraphStructure metric."""

import pytest

from hugegraph_llm.benchmark.metrics.extraction.graph_structure import GraphStructure

pytestmark = pytest.mark.unit


def test_graphstructure_empty_graph():
    metric = GraphStructure()
    # Empty vertices/edges -> all zeros.
    prediction = {'vertices': [], 'edges': []}
    result = metric.calculate(prediction)
    assert result['num_nodes'] == 0.0
    assert result['num_edges'] == 0.0
    assert result['density'] == 0.0
    assert result['clustering_coefficient'] == 0.0
    assert result['num_components'] == 0.0
    assert result['largest_component_ratio'] == 0.0


def test_graphstructure_single_node():
    metric = GraphStructure()
    # One node, no edges -> density=0, components=1, ratio=1.0.
    prediction = {'vertices': [{'name': 'A', 'label': 'node'}], 'edges': []}
    result = metric.calculate(prediction)
    assert result['num_nodes'] == 1.0
    assert result['num_edges'] == 0.0
    assert result['density'] == 0.0
    assert result['num_components'] == 1.0
    assert result['largest_component_ratio'] == 1.0


def test_graphstructure_complete_graph():
    metric = GraphStructure()
    # 4 nodes fully connected (6 edges) -> density=1.0, components=1, ratio=1.0.
    prediction = {
        'vertices': [{'name': 'A'}, {'name': 'B'}, {'name': 'C'}, {'name': 'D'}],
        'edges': [
            {'outV': 'A', 'inV': 'B', 'label': 'e'},
            {'outV': 'A', 'inV': 'C', 'label': 'e'},
            {'outV': 'A', 'inV': 'D', 'label': 'e'},
            {'outV': 'B', 'inV': 'C', 'label': 'e'},
            {'outV': 'B', 'inV': 'D', 'label': 'e'},
            {'outV': 'C', 'inV': 'D', 'label': 'e'},
        ],
    }
    result = metric.calculate(prediction)
    assert result['num_nodes'] == 4.0
    assert result['num_edges'] == 6.0
    assert result['density'] == 1.0
    assert result['num_components'] == 1.0
    assert result['largest_component_ratio'] == 1.0


def test_graphstructure_disconnected_graph():
    metric = GraphStructure()
    # Two separate components (A-B and C-D) -> components=2, ratio=0.5.
    prediction = {
        'vertices': [{'name': 'A'}, {'name': 'B'}, {'name': 'C'}, {'name': 'D'}],
        'edges': [{'outV': 'A', 'inV': 'B', 'label': 'e'}, {'outV': 'C', 'inV': 'D', 'label': 'e'}],
    }
    result = metric.calculate(prediction)
    assert result['num_nodes'] == 4.0
    assert result['num_edges'] == 2.0
    assert result['num_components'] == 2.0
    assert result['largest_component_ratio'] == 0.5


def test_graphstructure_non_dict_prediction():
    metric = GraphStructure()
    # String input -> all zeros.
    result = metric.calculate('not_a_dict')
    assert result['num_nodes'] == 0.0
    assert result['num_edges'] == 0.0
    assert result['density'] == 0.0
    assert result['clustering_coefficient'] == 0.0
    assert result['num_components'] == 0.0
    assert result['largest_component_ratio'] == 0.0


def test_graphstructure_clustering_coefficient_triangle():
    metric = GraphStructure()
    # Triangle graph A-B-C-A -> clustering > 0.
    prediction = {
        'vertices': [{'name': 'A'}, {'name': 'B'}, {'name': 'C'}],
        'edges': [
            {'outV': 'A', 'inV': 'B', 'label': 'e'},
            {'outV': 'B', 'inV': 'C', 'label': 'e'},
            {'outV': 'C', 'inV': 'A', 'label': 'e'},
        ],
    }
    result = metric.calculate(prediction)
    assert result['num_nodes'] == 3.0
    assert result['num_edges'] == 3.0
    assert result['clustering_coefficient'] > 0.0
    assert result['clustering_coefficient'] == 1.0
