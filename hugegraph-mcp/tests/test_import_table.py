# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from hugegraph_mcp import server
from hugegraph_mcp.envelope import envelope_ok
from hugegraph_mcp.tools.import_table import import_table_data, suggest_table_mapping


def _table_data():
    return {
        "table_name": "knows",
        "columns": ["src_name", "dst_name", "since"],
        "rows": [
            ["Alice", "Bob", 2020],
            ["Alice", "Bob", 2020],
            ["", "", ""],
        ],
    }


def _mapping():
    return {
        "vertex_mappings": [
            {
                "target_label": "person",
                "column_mapping": {"name": "src_name"},
                "primary_key_columns": ["src_name"],
            },
            {
                "target_label": "person",
                "column_mapping": {"name": "dst_name"},
                "primary_key_columns": ["dst_name"],
            },
        ],
        "edge_mappings": [
            {
                "target_label": "knows",
                "source_vertex": {
                    "label": "person",
                    "primary_key_columns": ["src_name"],
                },
                "target_vertex": {
                    "label": "person",
                    "primary_key_columns": ["dst_name"],
                },
                "column_mapping": {"since": "since"},
            }
        ],
    }


def test_import_table_data_maps_vertices_and_edges():
    result = import_table_data(_table_data(), _mapping())

    assert result["ok"] is True
    graph_data = result["data"]["graph_data"]
    assert graph_data == {
        "vertices": [
            {"label": "person", "properties": {"name": "Alice"}},
            {"label": "person", "properties": {"name": "Bob"}},
        ],
        "edges": [
            {
                "label": "knows",
                "source_label": "person",
                "target_label": "person",
                "source": {"name": "Alice"},
                "target": {"name": "Bob"},
                "properties": {"since": 2020},
            },
            {
                "label": "knows",
                "source_label": "person",
                "target_label": "person",
                "source": {"name": "Alice"},
                "target": {"name": "Bob"},
                "properties": {"since": 2020},
            },
        ],
    }


def test_import_table_data_rejects_missing_primary_key_column():
    mapping = _mapping()
    mapping["vertex_mappings"][0]["primary_key_columns"] = ["missing"]

    result = import_table_data(_table_data(), mapping)

    assert result["ok"] is False
    assert result["error"]["type"] == "INVALID_GRAPH_DATA"
    assert (
        "primary key column 'missing' does not exist"
        in result["error"]["details"]["errors"][0]
    )


def test_import_table_data_rejects_missing_mapped_column():
    mapping = _mapping()
    mapping["edge_mappings"][0]["column_mapping"] = {"since": "missing"}

    result = import_table_data(_table_data(), mapping)

    assert result["ok"] is False
    assert result["error"]["type"] == "INVALID_GRAPH_DATA"
    assert any(
        "column 'missing' does not exist" in error
        for error in result["error"]["details"]["errors"]
    )


def test_import_table_data_skips_empty_rows():
    table_data = {
        "table_name": "people",
        "columns": ["name", "age"],
        "rows": [["Alice", 30], ["", ""], [None, None]],
    }
    mapping = {
        "vertex_mappings": [
            {
                "target_label": "person",
                "column_mapping": {"name": "name", "age": "age"},
                "primary_key_columns": ["name"],
            }
        ],
        "edge_mappings": [],
    }

    result = import_table_data(table_data, mapping)

    assert result["ok"] is True
    assert result["data"]["graph_data"]["vertices"] == [
        {"label": "person", "properties": {"name": "Alice", "age": 30}}
    ]
    assert result["data"]["graph_data"]["edges"] == []


def test_import_table_data_rejects_edge_endpoint_label_not_defined():
    mapping = _mapping()
    mapping["edge_mappings"][0]["target_vertex"]["label"] = "ghost"

    result = import_table_data(_table_data(), mapping)

    assert result["ok"] is False
    assert any(
        "target_vertex label 'ghost' is not defined in vertex_mappings" in error
        for error in result["error"]["details"]["errors"]
    )


def test_import_table_data_returns_mapping_suggestion_when_mapping_missing():
    table_data = {
        "table_name": "People",
        "columns": ["person_id", "name", "age"],
        "rows": [[1, "Alice", 30]],
    }

    result = import_table_data(table_data)

    assert result["ok"] is True
    assert result["data"]["graph_data"] is None
    assert result["data"]["mapping_suggestion"] == {
        "vertex_mappings": [
            {
                "target_label": "people",
                "column_mapping": {
                    "person_id": "person_id",
                    "name": "name",
                    "age": "age",
                },
                "primary_key_columns": ["person_id"],
            }
        ],
        "edge_mappings": [],
    }


def test_suggest_table_mapping_infers_edge_shape():
    suggestion = suggest_table_mapping(
        {
            "table_name": "Relationships",
            "columns": ["source_id", "target_id", "weight"],
            "rows": [],
        }
    )

    assert suggestion["vertex_mappings"][0]["target_label"] == "relationship"
    assert suggestion["vertex_mappings"][0]["primary_key_columns"] == ["source_id"]
    assert suggestion["edge_mappings"] == [
        {
            "target_label": "relationship",
            "source_vertex": {
                "label": "source",
                "primary_key_columns": ["source_id"],
            },
            "target_vertex": {
                "label": "target",
                "primary_key_columns": ["target_id"],
            },
            "column_mapping": {"weight": "weight"},
        }
    ]


def test_import_graph_data_tool_table_routes_to_ingest(monkeypatch):
    calls = []

    def fake_ingest_graph_data(
        graph_data,
        dry_run=True,
        confirm=False,
        plan_hash=None,
    ):
        calls.append((graph_data, dry_run, confirm, plan_hash))
        return envelope_ok({"plan_hash": "0123456789abcdef"})

    monkeypatch.setattr(server, "ingest_graph_data", fake_ingest_graph_data)

    result = server.import_graph_data_tool(
        mode="table",
        table_data=_table_data(),
        mapping=_mapping(),
        dry_run=False,
        confirm=True,
        plan_hash="0123456789abcdef",
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "FEATURE_DISABLED"


def test_import_graph_data_tool_table_returns_feature_disabled():
    result = server.import_graph_data_tool(mode="table")

    assert result["ok"] is False
    assert result["error"]["type"] == "FEATURE_DISABLED"
