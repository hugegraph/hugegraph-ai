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

"""Tests for graph extraction normalization utilities."""

import json

import pytest

from hugegraph_llm.benchmark.utils.graph_extract import normalize_graph_extract

pytestmark = pytest.mark.unit


def test_normalize_property_graph_with_prefixed_ids():
    data = {
        "vertices": [
            {"id": "1:Alice", "label": "person", "type": "vertex", "properties": {"name": "Alice"}},
            {"id": "2:Bob", "label": "person", "type": "vertex", "properties": {"name": "Bob"}},
        ],
        "edges": [
            {
                "label": "knows",
                "type": "edge",
                "outV": "1:Alice",
                "outVLabel": "person",
                "inV": "2:Bob",
                "inVLabel": "person",
                "properties": {},
            }
        ],
    }
    result = normalize_graph_extract(data)
    assert result["candidate_vertices"] == [
        {"label": "person", "name": "Alice", "properties": {"name": "Alice"}},
        {"label": "person", "name": "Bob", "properties": {"name": "Bob"}},
    ]
    assert result["candidate_edges"] == [
        {"label": "knows", "outV": "Alice", "inV": "Bob", "properties": {}},
    ]


def test_normalize_triples_mode():
    data = {
        "vertices": [
            {"id": "person-Alice", "label": "person", "name": "Alice"},
            {"id": "person-Bob", "label": "person", "name": "Bob"},
        ],
        "edges": [
            {"type": "knows", "start": "person-Alice", "end": "person-Bob"},
        ],
    }
    result = normalize_graph_extract(data)
    assert result["candidate_vertices"] == [
        {"label": "person", "name": "Alice", "properties": {}},
        {"label": "person", "name": "Bob", "properties": {}},
    ]
    assert result["candidate_edges"] == [
        {"label": "knows", "outV": "Alice", "inV": "Bob", "properties": {}},
    ]


def test_normalize_json_string_input():
    data = {
        "vertices": [{"id": "1:Alice", "label": "person", "properties": {"name": "Alice"}}],
        "edges": [{"label": "knows", "outV": "1:Alice", "inV": "1:Bob", "properties": {}}],
    }
    result = normalize_graph_extract(json.dumps(data))
    assert result["candidate_vertices"][0]["name"] == "Alice"
    assert result["candidate_edges"][0]["inV"] == "Bob"


def test_normalize_property_graph_vertex_name_from_first_property():
    data = {
        "vertices": [{"id": "1:Paris", "label": "city", "properties": {"title": "Paris"}}],
        "edges": [],
    }
    result = normalize_graph_extract(data)
    assert result["candidate_vertices"][0]["name"] == "Paris"


def test_normalize_skips_malformed_edges():
    data = {
        "vertices": [],
        "edges": [
            {"label": "knows"},
            {"type": "knows", "start": "A"},
        ],
    }
    result = normalize_graph_extract(data)
    assert result["candidate_edges"] == []


def test_normalize_invalid_input_type_raises():
    with pytest.raises(TypeError):
        normalize_graph_extract(12345)


def test_normalize_unknown_endpoint_uses_prefix_strip():
    data = {
        "vertices": [{"id": "1:Alice", "label": "person", "properties": {"name": "Alice"}}],
        "edges": [{"label": "knows", "outV": "1:Alice", "inV": "9:Unknown"}],
    }
    result = normalize_graph_extract(data)
    assert result["candidate_edges"][0]["inV"] == "Unknown"


def test_normalize_explicit_extract_type_overrides_detection():
    data = {
        "vertices": [],
        "edges": [{"label": "knows", "outV": "A", "inV": "B"}],
    }
    result = normalize_graph_extract(data, extract_type="property_graph")
    assert result["candidate_edges"][0]["label"] == "knows"
    assert result["candidate_edges"][0]["outV"] == "A"
    assert result["candidate_edges"][0]["inV"] == "B"


def test_normalize_triples_without_vertices_falls_back_to_name_stripping():
    data = {
        "vertices": [],
        "edges": [{"type": "knows", "start": "person-Alice", "end": "person-Bob"}],
    }
    result = normalize_graph_extract(data)
    assert result["candidate_edges"][0]["outV"] == "Alice"
    assert result["candidate_edges"][0]["inV"] == "Bob"
