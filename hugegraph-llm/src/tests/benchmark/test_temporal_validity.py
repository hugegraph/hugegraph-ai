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

"""Tests for TemporalValidity metric."""

import pytest

from hugegraph_llm.benchmark.metrics.extraction.temporal_validity import TemporalValidity

pytestmark = pytest.mark.unit


def test_temporalvalidity_no_temporal_attributes():
    metric = TemporalValidity()
    # Vertices with no temporal props -> rate=1.0, count=0.
    prediction = {'vertices': [{'name': 'Alice', 'properties': {'name': 'Alice', 'city': 'Beijing'}}]}
    result = metric.calculate(prediction)
    assert result['temporal_valid_rate'] == 1.0
    assert result['num_temporal_attrs'] == 0.0


def test_temporalvalidity_all_valid_temporal():
    metric = TemporalValidity()
    # year=2020, date='2023-01-15' -> rate=1.0, count=2.
    prediction = {
        'vertices': [{'name': 'Event', 'properties': {'name': 'Event', 'year': '2020', 'date': '2023-01-15'}}]
    }
    result = metric.calculate(prediction)
    assert result['temporal_valid_rate'] == 1.0
    assert result['num_temporal_attrs'] == 2.0


def test_temporalvalidity_invalid_year_out_of_range():
    metric = TemporalValidity()
    # Values outside both year range [1900,2030] and Unix timestamp\n        range (0, 4102444800) are invalid. Negative numbers and very large\n        numbers fail both checks.
    prediction = {'vertices': [{'name': 'Bad', 'properties': {'name': 'Bad', 'year': '-500'}}]}
    result = metric.calculate(prediction)
    assert result['temporal_valid_rate'] < 1.0
    assert result['num_temporal_attrs'] == 1.0
    prediction_future = {
        'vertices': [{'name': 'FarFuture', 'properties': {'name': 'FarFuture', 'year': '99999999999'}}]
    }
    result_future = metric.calculate(prediction_future)
    assert result_future['temporal_valid_rate'] < 1.0
    assert result_future['num_temporal_attrs'] == 1.0


def test_temporalvalidity_small_positive_integer_is_not_timestamp():
    metric = TemporalValidity()
    prediction = {'vertices': [{'name': 'Event', 'properties': {'name': 'Event', 'timestamp': '5'}}]}
    result = metric.calculate(prediction)
    assert result['temporal_valid_rate'] == 0.0
    assert result['num_temporal_attrs'] == 1.0


def test_temporalvalidity_mixed_valid_invalid():
    metric = TemporalValidity()
    # One valid year, one invalid -> rate=0.5, count=2.
    prediction = {
        'vertices': [
            {'name': 'A', 'properties': {'name': 'A', 'year': '2020'}},
            {'name': 'B', 'properties': {'name': 'B', 'year': '-500'}},
        ]
    }
    result = metric.calculate(prediction)
    assert result['temporal_valid_rate'] == 0.5
    assert result['num_temporal_attrs'] == 2.0


def test_temporalvalidity_non_dict_input():
    metric = TemporalValidity()
    # Non-dict input -> rate=1.0, count=0.
    result = metric.calculate('not_a_dict')
    assert result['temporal_valid_rate'] == 1.0
    assert result['num_temporal_attrs'] == 0.0


def test_temporalvalidity_chinese_temporal_key():
    metric = TemporalValidity()
    # Property key '年份' with value '2020' -> valid.
    prediction = {'vertices': [{'name': 'Event', 'properties': {'name': 'Event', '年份': '2020'}}]}
    result = metric.calculate(prediction)
    assert result['temporal_valid_rate'] == 1.0
    assert result['num_temporal_attrs'] == 1.0
