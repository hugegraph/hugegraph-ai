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

from copy import deepcopy
import re

from hugegraph_mcp.tools import manage_graph_data as manage_graph_data_module


def _live_schema():
    return {
        "schema": {
            "propertykeys": [
                {"name": "name", "data_type": "TEXT"},
                {"name": "age", "data_type": "INT"},
                {"name": "since", "data_type": "INT"},
            ],
            "vertexlabels": [
                {
                    "name": "person",
                    "properties": ["name", "age"],
                    "primary_keys": ["name"],
                },
            ],
            "edgelabels": [
                {
                    "name": "knows",
                    "source_label": "person",
                    "target_label": "person",
                    "properties": ["since"],
                },
            ],
        },
        "simple_schema": {"vertices": ["person"], "edges": ["knows"]},
    }


def _update_vertex_plan():
    return {
        "operations": [
            {
                "op": "update_vertex",
                "label": "person",
                "match": {"name": "Alice"},
                "set": {"age": 31},
            }
        ]
    }


def _delete_edge_plan():
    return {
        "operations": [
            {
                "op": "delete_edge",
                "label": "knows",
                "source_label": "person",
                "source_match": {"name": "Alice"},
                "target_label": "person",
                "target_match": {"name": "Bob"},
            }
        ]
    }


def _update_edge_plan():
    return {
        "operations": [
            {
                "op": "update_edge",
                "label": "knows",
                "source_label": "person",
                "source_match": {"name": "Alice"},
                "target_label": "person",
                "target_match": {"name": "Bob"},
                "set": {"since": 2025},
            }
        ]
    }


def _delete_vertex_plan():
    return {
        "operations": [
            {
                "op": "delete_vertex",
                "label": "person",
                "match": {"name": "Alice"},
            }
        ]
    }


def _mock_schema(monkeypatch):
    monkeypatch.setattr(
        manage_graph_data_module,
        "_fetch_live_schema",
        lambda: _live_schema(),
    )


def _nested_count_result(count):
    return {
        "data": {"data": [count], "meta": {}},
        "total": 1,
        "duration_ms": 1,
        "is_read": True,
    }


def test_validate_graph_change_plan_rejects_unknown_op():
    result = manage_graph_data_module.validate_graph_change_plan(
        {"operations": [{"op": "merge_vertex", "label": "person"}]},
        _live_schema(),
    )

    assert result["valid"] is False
    assert "unsupported op" in result["errors"][0]["reason"]


def test_validate_update_vertex_rejects_primary_key_set():
    result = manage_graph_data_module.validate_graph_change_plan(
        {
            "operations": [
                {
                    "op": "update_vertex",
                    "label": "person",
                    "match": {"name": "Alice"},
                    "set": {"name": "Alicia"},
                }
            ]
        },
        _live_schema(),
    )

    assert result["valid"] is False
    assert "must not include primary key" in result["errors"][0]["reason"]


def test_validate_delete_vertex_requires_primary_key_match():
    result = manage_graph_data_module.validate_graph_change_plan(
        {
            "operations": [
                {
                    "op": "delete_vertex",
                    "label": "person",
                    "match": {"age": 31},
                }
            ]
        },
        _live_schema(),
    )

    assert result["valid"] is False
    assert "must contain primary key" in result["errors"][0]["reason"]


def test_validate_edge_rejects_unknown_endpoint_label():
    result = manage_graph_data_module.validate_graph_change_plan(
        {
            "operations": [
                {
                    "op": "delete_edge",
                    "label": "knows",
                    "source_label": "ghost",
                    "source_match": {"name": "Alice"},
                    "target_label": "person",
                    "target_match": {"name": "Bob"},
                }
            ]
        },
        _live_schema(),
    )

    assert result["valid"] is False
    assert any(
        "source_label references undefined" in e["reason"] for e in result["errors"]
    )


def test_dry_run_update_vertex_returns_preview_and_hash(monkeypatch):
    queries = []

    def fake_read(query):
        queries.append(query)
        return {"data": [1], "total": 1, "duration_ms": 1, "is_read": True}

    monkeypatch.setattr(
        manage_graph_data_module.gremlin_tools, "execute_gremlin_read", fake_read
    )

    result = manage_graph_data_module.dry_run_graph_change_plan(
        _update_vertex_plan(),
        _live_schema(),
    )

    assert result["valid"] is True
    assert re.fullmatch(r"[0-9a-f]{16}", result["plan_hash"])
    assert result["preview"][0]["matched_count"] == 1
    assert queries == ['g.V().hasLabel("person").has("name","Alice").count()']


def test_dry_run_update_vertex_accepts_nested_count_result(monkeypatch):
    monkeypatch.setattr(
        manage_graph_data_module.gremlin_tools,
        "execute_gremlin_read",
        lambda _query: _nested_count_result(1),
    )

    result = manage_graph_data_module.dry_run_graph_change_plan(
        _update_vertex_plan(),
        _live_schema(),
    )

    assert result["valid"] is True
    assert result["preview"][0]["matched_count"] == 1


def test_dry_run_delete_edge_rejects_non_single_match(monkeypatch):
    counts = iter([1, 1, 2])

    monkeypatch.setattr(
        manage_graph_data_module.gremlin_tools,
        "execute_gremlin_read",
        lambda _query: {
            "data": [next(counts)],
            "total": 1,
            "duration_ms": 1,
            "is_read": True,
        },
    )

    result = manage_graph_data_module.dry_run_graph_change_plan(
        _delete_edge_plan(),
        _live_schema(),
    )

    assert result["valid"] is False
    assert "delete_edge matched_count must be 1" in result["errors"][0]["reason"]


def test_dry_run_delete_edge_returns_preview_and_hash(monkeypatch):
    queries = []
    counts = iter([1, 1, 1])

    def fake_read(query):
        queries.append(query)
        return {
            "data": [next(counts)],
            "total": 1,
            "duration_ms": 1,
            "is_read": True,
        }

    monkeypatch.setattr(
        manage_graph_data_module.gremlin_tools, "execute_gremlin_read", fake_read
    )

    result = manage_graph_data_module.dry_run_graph_change_plan(
        _delete_edge_plan(),
        _live_schema(),
    )

    assert result["valid"] is True
    assert re.fullmatch(r"[0-9a-f]{16}", result["plan_hash"])
    assert result["preview"][0]["source_matched_count"] == 1
    assert result["preview"][0]["target_matched_count"] == 1
    assert result["preview"][0]["matched_count"] == 1
    assert queries == [
        'g.V().hasLabel("person").has("name","Alice").count()',
        'g.V().hasLabel("person").has("name","Bob").count()',
        'g.V().hasLabel("person").has("name","Alice").outE("knows").where(inV().hasLabel("person").has("name","Bob")).count()',
    ]


def test_dry_run_delete_edge_accepts_nested_count_result(monkeypatch):
    counts = iter([1, 1, 1])

    monkeypatch.setattr(
        manage_graph_data_module.gremlin_tools,
        "execute_gremlin_read",
        lambda _query: _nested_count_result(next(counts)),
    )

    result = manage_graph_data_module.dry_run_graph_change_plan(
        _delete_edge_plan(),
        _live_schema(),
    )

    assert result["valid"] is True
    assert result["preview"][0]["source_matched_count"] == 1
    assert result["preview"][0]["target_matched_count"] == 1
    assert result["preview"][0]["matched_count"] == 1


def test_dry_run_delete_edge_rejects_missing_source(monkeypatch):
    counts = iter([0, 1])

    monkeypatch.setattr(
        manage_graph_data_module.gremlin_tools,
        "execute_gremlin_read",
        lambda _query: {
            "data": [next(counts)],
            "total": 1,
            "duration_ms": 1,
            "is_read": True,
        },
    )

    result = manage_graph_data_module.dry_run_graph_change_plan(
        _delete_edge_plan(),
        _live_schema(),
    )

    assert result["valid"] is False
    assert (
        "delete_edge source endpoint matched_count must be 1"
        in result["errors"][0]["reason"]
    )
    assert "matched_count" not in result["preview"][0]


def test_dry_run_delete_edge_rejects_missing_target(monkeypatch):
    counts = iter([1, 0])

    monkeypatch.setattr(
        manage_graph_data_module.gremlin_tools,
        "execute_gremlin_read",
        lambda _query: {
            "data": [next(counts)],
            "total": 1,
            "duration_ms": 1,
            "is_read": True,
        },
    )

    result = manage_graph_data_module.dry_run_graph_change_plan(
        _delete_edge_plan(),
        _live_schema(),
    )

    assert result["valid"] is False
    assert (
        "delete_edge target endpoint matched_count must be 1"
        in result["errors"][0]["reason"]
    )
    assert "matched_count" not in result["preview"][0]


def test_dry_run_delete_edge_rejects_zero_edge_match(monkeypatch):
    counts = iter([1, 1, 0])

    monkeypatch.setattr(
        manage_graph_data_module.gremlin_tools,
        "execute_gremlin_read",
        lambda _query: {
            "data": [next(counts)],
            "total": 1,
            "duration_ms": 1,
            "is_read": True,
        },
    )

    result = manage_graph_data_module.dry_run_graph_change_plan(
        _delete_edge_plan(),
        _live_schema(),
    )

    assert result["valid"] is False
    assert "delete_edge matched_count must be 1, got 0" in result["errors"][0]["reason"]


def test_dry_run_delete_vertex_rejects_edges_when_not_cascade(monkeypatch):
    counts = iter([1, 3])

    monkeypatch.setattr(
        manage_graph_data_module.gremlin_tools,
        "execute_gremlin_read",
        lambda _query: {
            "data": [next(counts)],
            "total": 1,
            "duration_ms": 1,
            "is_read": True,
        },
    )

    result = manage_graph_data_module.dry_run_graph_change_plan(
        {
            "operations": [
                {
                    "op": "delete_vertex",
                    "label": "person",
                    "match": {"name": "Alice"},
                    "cascade": False,
                }
            ]
        },
        _live_schema(),
    )

    assert result["valid"] is False
    assert "cascade=false" in result["errors"][0]["reason"]
    assert result["preview"][0]["associated_edge_count"] == 3


def test_manage_delete_vertex_returns_blocked_by_relationships(monkeypatch):
    _mock_schema(monkeypatch)
    counts = iter([1, 2])

    monkeypatch.setattr(
        manage_graph_data_module.gremlin_tools,
        "execute_gremlin_read",
        lambda _query: {
            "data": [next(counts)],
            "total": 1,
            "duration_ms": 1,
            "is_read": True,
        },
    )

    result = manage_graph_data_module.manage_graph_data(
        mode="delete",
        change_plan=_delete_vertex_plan(),
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "BLOCKED_BY_RELATIONSHIPS"


def test_dry_run_delete_vertex_allows_no_edges_when_not_cascade(monkeypatch):
    counts = iter([1, 0])

    monkeypatch.setattr(
        manage_graph_data_module.gremlin_tools,
        "execute_gremlin_read",
        lambda _query: {
            "data": [next(counts)],
            "total": 1,
            "duration_ms": 1,
            "is_read": True,
        },
    )

    result = manage_graph_data_module.dry_run_graph_change_plan(
        _delete_vertex_plan(),
        _live_schema(),
    )

    assert result["valid"] is True
    assert re.fullmatch(r"[0-9a-f]{16}", result["plan_hash"])
    assert result["preview"][0]["matched_count"] == 1
    assert result["preview"][0]["associated_edge_count"] == 0


def test_dry_run_delete_vertex_accepts_nested_count_result(monkeypatch):
    counts = iter([1, 0])

    monkeypatch.setattr(
        manage_graph_data_module.gremlin_tools,
        "execute_gremlin_read",
        lambda _query: _nested_count_result(next(counts)),
    )

    result = manage_graph_data_module.dry_run_graph_change_plan(
        _delete_vertex_plan(),
        _live_schema(),
    )

    assert result["valid"] is True
    assert result["preview"][0]["matched_count"] == 1
    assert result["preview"][0]["associated_edge_count"] == 0


def test_dry_run_delete_vertex_rejects_non_single_match(monkeypatch):
    monkeypatch.setattr(
        manage_graph_data_module.gremlin_tools,
        "execute_gremlin_read",
        lambda _query: {"data": [0], "total": 1, "duration_ms": 1, "is_read": True},
    )

    result = manage_graph_data_module.dry_run_graph_change_plan(
        _delete_vertex_plan(),
        _live_schema(),
    )

    assert result["valid"] is False
    assert "delete_vertex matched_count must be 1" in result["errors"][0]["reason"]


def test_manage_graph_data_execute_delete_vertex_verifies_removed(monkeypatch):
    _mock_schema(monkeypatch)
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    reads = []
    writes = []
    counts = iter([1, 0, 1, 0, 1, 0, 0])

    def fake_read(query):
        reads.append(query)
        return {
            "data": [next(counts)],
            "total": 1,
            "duration_ms": 1,
            "is_read": True,
        }

    def fake_write(query):
        writes.append(query)
        return {"success": True, "affected": 1, "duration_ms": 1, "is_write": True}

    monkeypatch.setattr(
        manage_graph_data_module.gremlin_tools, "execute_gremlin_read", fake_read
    )
    monkeypatch.setattr(
        manage_graph_data_module.gremlin_tools, "execute_gremlin_write", fake_write
    )
    dry_run = manage_graph_data_module.manage_graph_data(
        mode="delete",
        change_plan=_delete_vertex_plan(),
    )

    result = manage_graph_data_module.manage_graph_data(
        mode="delete",
        change_plan=_delete_vertex_plan(),
        dry_run=False,
        confirm=True,
        plan_hash=dry_run["data"]["plan_hash"],
    )

    assert result["ok"] is True
    assert writes == ['g.V().hasLabel("person").has("name","Alice").drop()']
    assert reads[-1] == 'g.V().hasLabel("person").has("name","Alice").count()'


def test_dry_run_update_edge_returns_preview_and_hash(monkeypatch):
    queries = []
    counts = iter([1, 1, 1])

    def fake_read(query):
        queries.append(query)
        return {
            "data": [next(counts)],
            "total": 1,
            "duration_ms": 1,
            "is_read": True,
        }

    monkeypatch.setattr(
        manage_graph_data_module.gremlin_tools, "execute_gremlin_read", fake_read
    )

    result = manage_graph_data_module.dry_run_graph_change_plan(
        _update_edge_plan(),
        _live_schema(),
    )

    assert result["valid"] is True
    assert result["preview"][0]["source_matched_count"] == 1
    assert result["preview"][0]["target_matched_count"] == 1
    assert result["preview"][0]["matched_count"] == 1
    assert queries == [
        'g.V().hasLabel("person").has("name","Alice").count()',
        'g.V().hasLabel("person").has("name","Bob").count()',
        'g.V().hasLabel("person").has("name","Alice").outE("knows").where(inV().hasLabel("person").has("name","Bob")).count()',
    ]


def test_validate_update_edge_rejects_unknown_set_field():
    plan = _update_edge_plan()
    plan["operations"][0]["set"] = {"weight": 1}

    result = manage_graph_data_module.validate_graph_change_plan(plan, _live_schema())

    assert result["valid"] is False
    assert (
        "set references property not on label: weight" in result["errors"][0]["reason"]
    )


def test_validate_update_vertex_rejects_unknown_set_field():
    plan = _update_vertex_plan()
    plan["operations"][0]["set"] = {"nickname": "Al"}

    result = manage_graph_data_module.validate_graph_change_plan(plan, _live_schema())

    assert result["valid"] is False
    assert (
        "set references property not on label: nickname"
        in result["errors"][0]["reason"]
    )


def test_validate_update_edge_rejects_endpoint_set_field():
    plan = _update_edge_plan()
    plan["operations"][0]["set"] = {"source_label": "person"}

    result = manage_graph_data_module.validate_graph_change_plan(plan, _live_schema())

    assert result["valid"] is False
    assert any(
        "must not include source/target" in e["reason"] for e in result["errors"]
    )


def test_dry_run_update_edge_rejects_non_single_edge_match(monkeypatch):
    counts = iter([1, 1, 2])

    monkeypatch.setattr(
        manage_graph_data_module.gremlin_tools,
        "execute_gremlin_read",
        lambda _query: {
            "data": [next(counts)],
            "total": 1,
            "duration_ms": 1,
            "is_read": True,
        },
    )

    result = manage_graph_data_module.dry_run_graph_change_plan(
        _update_edge_plan(),
        _live_schema(),
    )

    assert result["valid"] is False
    assert "update_edge matched_count must be 1, got 2" in result["errors"][0]["reason"]


def test_dry_run_update_edge_rejects_endpoint_match_failure(monkeypatch):
    counts = iter([0, 1])

    monkeypatch.setattr(
        manage_graph_data_module.gremlin_tools,
        "execute_gremlin_read",
        lambda _query: {
            "data": [next(counts)],
            "total": 1,
            "duration_ms": 1,
            "is_read": True,
        },
    )

    result = manage_graph_data_module.dry_run_graph_change_plan(
        _update_edge_plan(),
        _live_schema(),
    )

    assert result["valid"] is False
    assert "source endpoint matched_count must be 1" in result["errors"][0]["reason"]
    assert "matched_count" not in result["preview"][0]


def test_graph_data_to_change_plan_maps_create_operations():
    result = manage_graph_data_module.graph_data_to_change_plan(
        {
            "vertices": [{"label": "person", "properties": {"name": "Alice"}}],
            "edges": [
                {
                    "label": "knows",
                    "source_label": "person",
                    "source": {"name": "Alice"},
                    "target_label": "person",
                    "target": {"name": "Bob"},
                    "properties": {"since": 2024},
                }
            ],
        }
    )

    assert [op["op"] for op in result["operations"]] == ["create_vertex", "create_edge"]
    assert result["operations"][1]["source_match"] == {"name": "Alice"}


def test_graph_data_to_change_plan_maps_outv_inv_to_vertex_properties():
    result = manage_graph_data_module.graph_data_to_change_plan(
        {
            "vertices": [
                {"id": "1:Alice", "label": "person", "properties": {"name": "Alice"}},
                {"id": "1:Bob", "label": "person", "properties": {"name": "Bob"}},
            ],
            "edges": [
                {
                    "label": "knows",
                    "outV": "1:Alice",
                    "outVLabel": "person",
                    "inV": "1:Bob",
                    "inVLabel": "person",
                    "properties": {"since": 2024},
                }
            ],
        }
    )

    edge_op = result["operations"][2]
    assert edge_op["source_match"] == {"name": "Alice"}
    assert edge_op["target_match"] == {"name": "Bob"}


def test_graph_data_to_change_plan_normalizes_vertex_id_lookup():
    result = manage_graph_data_module.graph_data_to_change_plan(
        {
            "vertices": [
                {"id": 123, "label": "person", "properties": {"name": "Alice"}},
                {"id": 456, "label": "person", "properties": {"name": "Bob"}},
            ],
            "edges": [
                {
                    "label": "knows",
                    "outV": "123",
                    "outVLabel": "person",
                    "inV": "456",
                    "inVLabel": "person",
                }
            ],
        }
    )

    edge_op = result["operations"][2]
    assert edge_op["source_match"] == {"name": "Alice"}
    assert edge_op["target_match"] == {"name": "Bob"}


def test_manage_graph_data_requires_confirm(monkeypatch):
    _mock_schema(monkeypatch)
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    monkeypatch.setattr(
        manage_graph_data_module.gremlin_tools,
        "execute_gremlin_read",
        lambda _query: {"data": [1], "total": 1, "duration_ms": 1, "is_read": True},
    )

    result = manage_graph_data_module.manage_graph_data(
        mode="update",
        change_plan=_update_vertex_plan(),
        dry_run=False,
        confirm=False,
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "CONFIRM_REQUIRED"


def test_manage_graph_data_rejects_wrong_mode_operations(monkeypatch):
    _mock_schema(monkeypatch)

    result = manage_graph_data_module.manage_graph_data(
        mode="update",
        change_plan=_delete_edge_plan(),
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "INVALID_GRAPH_DATA"
    assert (
        "not allowed in mode='update'"
        in result["error"]["details"]["errors"][0]["reason"]
    )


def test_manage_graph_data_plan_hash_mismatch(monkeypatch):
    _mock_schema(monkeypatch)
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    monkeypatch.setattr(
        manage_graph_data_module.gremlin_tools,
        "execute_gremlin_read",
        lambda _query: {"data": [1], "total": 1, "duration_ms": 1, "is_read": True},
    )

    result = manage_graph_data_module.manage_graph_data(
        mode="update",
        change_plan=_update_vertex_plan(),
        dry_run=False,
        confirm=True,
        plan_hash="0000000000000000",
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "PLAN_HASH_MISMATCH"


def test_manage_graph_data_dry_run_returns_plan_hash(monkeypatch):
    _mock_schema(monkeypatch)
    monkeypatch.setattr(
        manage_graph_data_module.gremlin_tools,
        "execute_gremlin_read",
        lambda _query: {"data": [1], "total": 1, "duration_ms": 1, "is_read": True},
    )

    result = manage_graph_data_module.manage_graph_data(
        mode="update",
        change_plan=_update_vertex_plan(),
    )

    assert result["ok"] is True
    assert re.fullmatch(r"[0-9a-f]{16}", result["data"]["plan_hash"])


def test_manage_graph_data_plan_hash_schema_field_order_same_hash():
    plan = _update_vertex_plan()
    schema = _live_schema()
    reordered_schema = _live_schema()
    reordered_schema["schema"]["propertykeys"] = list(
        reversed(reordered_schema["schema"]["propertykeys"])
    )
    reordered_schema["schema"]["vertexlabels"][0]["properties"] = ["age", "name"]
    reordered_schema["schema"]["vertexlabels"][0]["primaryKeys"] = ["name"]
    reordered_schema["schema"]["vertexlabels"][0].pop("primary_keys")
    reordered_schema["schema"]["edgelabels"][0]["sourceLabel"] = "person"
    reordered_schema["schema"]["edgelabels"][0]["targetLabel"] = "person"
    reordered_schema["schema"]["edgelabels"][0].pop("source_label")
    reordered_schema["schema"]["edgelabels"][0].pop("target_label")

    first = manage_graph_data_module.calculate_graph_change_plan_hash(
        plan,
        schema_summary=manage_graph_data_module._schema_summary(schema),
    )
    second = manage_graph_data_module.calculate_graph_change_plan_hash(
        plan,
        schema_summary=manage_graph_data_module._schema_summary(reordered_schema),
    )

    assert first == second


def test_manage_graph_data_plan_hash_schema_primary_key_change_different_hash():
    plan = _update_vertex_plan()
    schema = _live_schema()
    changed_schema = deepcopy(schema)
    changed_schema["schema"]["vertexlabels"][0]["primary_keys"] = ["age"]

    first = manage_graph_data_module.calculate_graph_change_plan_hash(
        plan,
        schema_summary=manage_graph_data_module._schema_summary(schema),
    )
    second = manage_graph_data_module.calculate_graph_change_plan_hash(
        plan,
        schema_summary=manage_graph_data_module._schema_summary(changed_schema),
    )

    assert first != second


def test_manage_graph_data_plan_hash_schema_metadata_ignored_same_hash():
    plan = _update_vertex_plan()
    schema = _live_schema()
    schema_with_metadata = deepcopy(schema)
    schema_with_metadata["server_time"] = "2026-05-26T00:00:00Z"
    schema_with_metadata["schema"]["vertexlabels"][0]["id"] = 99
    schema_with_metadata["schema"]["vertexlabels"][0]["user_data"] = {"x": "y"}
    schema_with_metadata["simple_schema"] = {"unrelated": ["metadata"]}

    first = manage_graph_data_module.calculate_graph_change_plan_hash(
        plan,
        schema_summary=manage_graph_data_module._schema_summary(schema),
    )
    second = manage_graph_data_module.calculate_graph_change_plan_hash(
        plan,
        schema_summary=manage_graph_data_module._schema_summary(schema_with_metadata),
    )

    assert first == second


def test_manage_graph_data_readonly_rejects_execution(monkeypatch):
    _mock_schema(monkeypatch)
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "true")
    writes = []

    monkeypatch.setattr(
        manage_graph_data_module.gremlin_tools,
        "execute_gremlin_read",
        lambda _query: {"data": [1], "total": 1, "duration_ms": 1, "is_read": True},
    )
    monkeypatch.setattr(
        manage_graph_data_module.gremlin_tools,
        "execute_gremlin_write",
        lambda query: writes.append(query),
    )
    dry_run = manage_graph_data_module.manage_graph_data(
        mode="update",
        change_plan=_update_vertex_plan(),
    )

    result = manage_graph_data_module.manage_graph_data(
        mode="update",
        change_plan=_update_vertex_plan(),
        dry_run=False,
        confirm=True,
        plan_hash=dry_run["data"]["plan_hash"],
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "READONLY_VIOLATION"
    assert writes == []


def test_manage_graph_data_execute_update_vertex(monkeypatch):
    _mock_schema(monkeypatch)
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    reads = []
    writes = []

    def fake_read(query):
        reads.append(query)
        return {"data": [1], "total": 1, "duration_ms": 1, "is_read": True}

    def fake_write(query):
        writes.append(query)
        return {"success": True, "affected": 1, "duration_ms": 1, "is_write": True}

    monkeypatch.setattr(
        manage_graph_data_module.gremlin_tools, "execute_gremlin_read", fake_read
    )
    monkeypatch.setattr(
        manage_graph_data_module.gremlin_tools, "execute_gremlin_write", fake_write
    )
    dry_run = manage_graph_data_module.manage_graph_data(
        mode="update",
        change_plan=_update_vertex_plan(),
    )

    result = manage_graph_data_module.manage_graph_data(
        mode="update",
        change_plan=_update_vertex_plan(),
        dry_run=False,
        confirm=True,
        plan_hash=dry_run["data"]["plan_hash"],
    )

    assert result["ok"] is True
    assert result["data"]["success"] is True
    assert reads == [
        'g.V().hasLabel("person").has("name","Alice").count()',
        'g.V().hasLabel("person").has("name","Alice").count()',
        'g.V().hasLabel("person").has("name","Alice").count()',
    ]
    assert writes == ['g.V().hasLabel("person").has("name","Alice").property("age",31)']


def test_manage_graph_data_import_validates_graph_payload(monkeypatch):
    _mock_schema(monkeypatch)

    result = manage_graph_data_module.manage_graph_data(
        mode="import",
        graph_data={
            "vertices": [{"label": "person", "properties": {"age": 31}}],
            "edges": [],
        },
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "SCHEMA_MISMATCH"
