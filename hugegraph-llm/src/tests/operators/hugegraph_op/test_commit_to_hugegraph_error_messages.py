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

from unittest.mock import MagicMock, patch

import pytest

from hugegraph_llm.operators.hugegraph_op.commit_to_hugegraph import Commit2Graph

pytestmark = [pytest.mark.unit]


def _commit_operator():
    mock_client = MagicMock()
    mock_client.schema.return_value = MagicMock()
    with patch("hugegraph_llm.operators.hugegraph_op.commit_to_hugegraph.PyHugeClient", return_value=mock_client):
        return Commit2Graph()


def _schema():
    return {
        "propertykeys": [
            {"name": "name", "data_type": "TEXT", "cardinality": "SINGLE"},
            {"name": "title", "data_type": "TEXT", "cardinality": "SINGLE"},
            {"name": "role", "data_type": "TEXT", "cardinality": "SINGLE"},
        ],
        "vertexlabels": [
            {
                "name": "person",
                "properties": ["name"],
                "primary_keys": ["name"],
                "nullable_keys": [],
                "id_strategy": "PRIMARY_KEY",
            },
            {
                "name": "movie",
                "properties": ["title"],
                "primary_keys": ["title"],
                "nullable_keys": [],
                "id_strategy": "PRIMARY_KEY",
            },
        ],
        "edgelabels": [{"name": "acted_in", "properties": ["role"], "source_label": "person", "target_label": "movie"}],
    }


def test_import_errors_do_not_include_raw_vertex_or_edge_payloads():
    commit2graph = _commit_operator()
    vertices = [{"label": "person", "properties": {"name": "Tom Hanks"}}]
    edges = [
        {
            "label": "acted_in",
            "properties": {"role": "Forrest Gump"},
            "outV": "person:Tom Hanks",
            "inV": "movie:Forrest Gump",
        }
    ]

    with patch.object(commit2graph, "_handle_graph_creation", return_value=None):
        result = commit2graph.load_into_graph(vertices, edges, _schema())

    assert result["errors"] == [
        "Failed to create vertex label 'person' at index 0",
        "Failed to create edge label 'acted_in' at index 0",
    ]
    error_text = " ".join(result["errors"])
    assert "Tom Hanks" not in error_text
    assert "Forrest Gump" not in error_text


def test_primary_key_import_error_identifies_key_label_and_index_only():
    commit2graph = _commit_operator()
    vertices = [{"label": "person", "properties": {"name": ""}}]

    result = commit2graph.load_into_graph(vertices, [], _schema())

    assert result["errors"] == ["Primary-key 'name' missing in vertex label 'person' at index 0"]
    assert "{'label':" not in result["errors"][0]


def test_schema_free_import_errors_do_not_include_raw_triple_payloads():
    commit2graph = _commit_operator()
    triples = [["Alice Sensitive", "knows", "Bob Sensitive"]]

    with patch.object(commit2graph, "_handle_graph_creation", return_value=None):
        result = commit2graph.schema_free_mode(triples)

    assert result["errors"] == ["Failed to create schema-free vertices for triple at index 0"]
    error_text = " ".join(result["errors"])
    assert "Alice Sensitive" not in error_text
    assert "Bob Sensitive" not in error_text
