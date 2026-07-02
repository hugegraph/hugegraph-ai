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

"""Tests for ConflictDetection metric."""

import pytest

from hugegraph_llm.benchmark.metrics.extraction.conflict_detection import ConflictDetection

pytestmark = pytest.mark.unit


def test_conflictdetection_no_conflicts():
    metric = ConflictDetection()
    # Clean graph -> num_conflicts=0, rate=0.
    prediction = {
        'vertices': [
            {'name': 'Alice', 'properties': {'name': 'Alice', 'age': '30'}},
            {'name': 'Bob', 'properties': {'name': 'Bob', 'age': '25'}},
        ],
        'edges': [{'outV': 'Alice', 'label': 'knows', 'inV': 'Bob'}],
    }
    result = metric.calculate(prediction)
    assert result['num_conflicts'] == 0.0
    assert result['conflict_rate'] == 0.0


def test_conflictdetection_property_value_conflict():
    metric = ConflictDetection()
    # Same entity 'Alice' appears twice with age=30 and age=25 -> 1 conflict.
    prediction = {
        'vertices': [
            {'name': 'Alice', 'properties': {'name': 'Alice', 'age': '30'}},
            {'name': 'Alice', 'properties': {'name': 'Alice', 'age': '25'}},
        ],
        'edges': [],
    }
    result = metric.calculate(prediction)
    assert result['num_conflicts'] == 1.0
    assert result['conflict_rate'] > 0.0


def test_conflictdetection_symmetric_relation_no_conflict():
    metric = ConflictDetection()
    # Symmetric relations should not trigger conflicts when reversed.
    prediction = {
        'vertices': [{'name': 'Alice'}, {'name': 'Bob'}],
        'edges': [
            {'outV': 'Alice', 'label': 'related_to', 'inV': 'Bob'},
            {'outV': 'Bob', 'label': 'related_to', 'inV': 'Alice'},
        ],
    }
    result = metric.calculate(prediction)
    assert result['num_conflicts'] == 0.0


def test_conflictdetection_asymmetric_relation_conflict():
    metric = ConflictDetection()
    # (A,knows,B) + (B,knows,A) where knows is NOT symmetric -> 1 conflict.
    prediction = {
        'vertices': [{'name': 'Alice'}, {'name': 'Bob'}],
        'edges': [{'outV': 'Alice', 'label': 'knows', 'inV': 'Bob'}, {'outV': 'Bob', 'label': 'knows', 'inV': 'Alice'}],
    }
    result = metric.calculate(prediction)
    assert result['num_conflicts'] == 1.0
    assert result['conflict_rate'] > 0.0


def test_conflictdetection_empty_graph():
    metric = ConflictDetection()
    # Empty graph -> no conflicts.
    prediction = {'vertices': [], 'edges': []}
    result = metric.calculate(prediction)
    assert result['num_conflicts'] == 0.0
    assert result['conflict_rate'] == 0.0


def test_conflictdetection_non_dict_input():
    metric = ConflictDetection()
    # String input -> zeros.
    result = metric.calculate('not_a_dict')
    assert result['num_conflicts'] == 0.0
    assert result['conflict_rate'] == 0.0
