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

import re

from hugegraph_mcp.tools import manage_schema as manage_schema_module
from hugegraph_mcp.tools.manage_schema import manage_schema


def _empty_schema():
    return {
        "schema": {
            "propertykeys": [],
            "vertexlabels": [],
            "edgelabels": [],
            "indexlabels": [],
        },
        "simple_schema": {},
        "readonly": False,
    }


def _schema(
    *,
    propertykeys=None,
    vertexlabels=None,
    edgelabels=None,
    indexlabels=None,
):
    return {
        "schema": {
            "propertykeys": propertykeys or [],
            "vertexlabels": vertexlabels or [],
            "edgelabels": edgelabels or [],
            "indexlabels": indexlabels or [],
        },
        "simple_schema": {},
        "readonly": False,
    }


def _property_key(name="age"):
    return {"type": "create_property_key", "name": name, "data_type": "INT"}


def _vertex_label(name="person", properties=None, primary_keys=None):
    operation = {"type": "create_vertex_label", "name": name}
    if properties is not None:
        operation["properties"] = properties
    if primary_keys is not None:
        operation["primary_keys"] = primary_keys
    return operation


def _edge_label(
    name="knows", source_label="person", target_label="person", properties=None
):
    operation = {
        "type": "create_edge_label",
        "name": name,
        "source_label": source_label,
        "target_label": target_label,
    }
    if properties is not None:
        operation["properties"] = properties
    return operation


def _index_label(
    name="personByAge", base_type="VERTEX", base_label="person", fields=None
):
    operation = {
        "type": "create_index_label",
        "name": name,
        "base_type": base_type,
        "base_label": base_label,
    }
    if fields is not None:
        operation["fields"] = fields
    return operation


def _live_pk(name):
    return {"name": name, "data_type": "TEXT"}


def _live_vertex(name, properties=None):
    return {"name": name, "properties": properties or []}


def _live_edge(name, source_label="person", target_label="software"):
    return {
        "name": name,
        "source_label": source_label,
        "target_label": target_label,
    }


def test_manage_schema_design():
    result = manage_schema(
        mode="design",
        operations=[
            {
                "thought": "Need a graph for users",
                "thought_number": 2,
                "total_thoughts": 5,
                "next_thought_needed": True,
            }
        ],
    )

    assert result["ok"] is True
    assert result["data"]["thought_number"] == 2
    assert result["data"]["total_thoughts"] == 5
    assert result["data"]["next_thought_needed"] is True


def test_manage_schema_validate_valid(monkeypatch):
    monkeypatch.setattr(
        manage_schema_module.schema_tools, "get_live_schema", _empty_schema
    )

    result = manage_schema(mode="validate", operations=[_property_key()])

    assert result["ok"] is True
    assert result["data"]["valid"] is True
    assert result["data"]["errors"] == []


def test_manage_schema_validate_invalid_missing_name(monkeypatch):
    monkeypatch.setattr(
        manage_schema_module.schema_tools, "get_live_schema", _empty_schema
    )

    result = manage_schema(
        mode="validate",
        operations=[{"type": "create_property_key", "data_type": "TEXT"}],
    )

    assert result["ok"] is True
    assert result["data"]["valid"] is False
    assert result["data"]["errors"][0]["operation_index"] == 0
    assert "missing required field: name" in result["data"]["errors"][0]["reason"]


def test_manage_schema_validate_rejects_delete(monkeypatch):
    monkeypatch.setattr(
        manage_schema_module.schema_tools, "get_live_schema", _empty_schema
    )

    result = manage_schema(
        mode="validate",
        operations=[{"type": "delete_vertex_label", "name": "person"}],
    )

    assert result["ok"] is True
    assert result["data"]["valid"] is False
    assert "unsupported delete/drop type" in result["data"]["errors"][0]["reason"]


def test_manage_schema_validate_rejects_unknown_property_key(monkeypatch):
    monkeypatch.setattr(
        manage_schema_module.schema_tools,
        "get_live_schema",
        lambda: _schema(propertykeys=[_live_pk("name")]),
    )

    result = manage_schema(
        mode="validate",
        operations=[
            {
                "type": "create_vertex_label",
                "name": "person",
                "properties": ["name", "age"],
                "primary_keys": ["name"],
            }
        ],
    )

    assert result["ok"] is True
    assert result["data"]["valid"] is False
    error = result["data"]["errors"][0]
    assert error["operation_index"] == 0
    assert "undefined property key" in error["reason"]
    assert "age" in error["reason"]


def test_manage_schema_validate_rejects_unknown_edge_endpoint(monkeypatch):
    monkeypatch.setattr(
        manage_schema_module.schema_tools,
        "get_live_schema",
        lambda: _schema(vertexlabels=[_live_vertex("person")]),
    )

    result = manage_schema(
        mode="validate",
        operations=[
            {
                "type": "create_edge_label",
                "name": "created",
                "source_label": "person",
                "target_label": "software",
            }
        ],
    )

    assert result["ok"] is True
    assert result["data"]["valid"] is False
    error = result["data"]["errors"][0]
    assert error["operation_index"] == 0
    assert "target_label references undefined vertex label: software" == error["reason"]


def test_manage_schema_validate_rejects_duplicate_vertex_label(monkeypatch):
    monkeypatch.setattr(
        manage_schema_module.schema_tools,
        "get_live_schema",
        lambda: _schema(vertexlabels=[_live_vertex("person")]),
    )

    result = manage_schema(
        mode="validate",
        operations=[{"type": "create_vertex_label", "name": "person"}],
    )

    assert result["ok"] is True
    assert result["data"]["valid"] is False
    error = result["data"]["errors"][0]
    assert error["operation_index"] == 0
    assert error["reason"] == "vertex label already exists: person"


def test_manage_schema_validate_accepts_semantically_valid_operations(monkeypatch):
    monkeypatch.setattr(
        manage_schema_module.schema_tools,
        "get_live_schema",
        lambda: _schema(
            propertykeys=[_live_pk("name")],
            vertexlabels=[_live_vertex("person")],
            edgelabels=[_live_edge("created")],
        ),
    )

    result = manage_schema(
        mode="validate",
        operations=[
            {
                "type": "create_index_label",
                "name": "personByName",
                "base_type": "VERTEX",
                "base_label": "person",
                "fields": ["name"],
            }
        ],
    )

    assert result["ok"] is True
    assert result["data"]["valid"] is True
    assert result["data"]["errors"] == []


def test_same_batch_pk_to_vertex_label(monkeypatch):
    monkeypatch.setattr(
        manage_schema_module.schema_tools, "get_live_schema", _empty_schema
    )

    result = manage_schema(
        mode="validate",
        operations=[
            _property_key("age"),
            _vertex_label("person", properties=["age"], primary_keys=["age"]),
        ],
    )

    assert result["ok"] is True
    assert result["data"]["valid"] is True
    assert result["data"]["errors"] == []


def test_same_batch_vertex_to_edge_label(monkeypatch):
    monkeypatch.setattr(
        manage_schema_module.schema_tools, "get_live_schema", _empty_schema
    )

    result = manage_schema(
        mode="validate",
        operations=[
            _vertex_label("person"),
            _vertex_label("software"),
            _edge_label("created", source_label="person", target_label="software"),
        ],
    )

    assert result["ok"] is True
    assert result["data"]["valid"] is True
    assert result["data"]["errors"] == []


def test_same_batch_label_to_index(monkeypatch):
    monkeypatch.setattr(
        manage_schema_module.schema_tools, "get_live_schema", _empty_schema
    )

    result = manage_schema(
        mode="validate",
        operations=[
            _property_key("name"),
            _vertex_label("person", properties=["name"], primary_keys=["name"]),
            _index_label("personByName", base_label="person", fields=["name"]),
        ],
    )

    assert result["ok"] is True
    assert result["data"]["valid"] is True
    assert result["data"]["errors"] == []


def test_same_batch_full_chain(monkeypatch):
    monkeypatch.setattr(
        manage_schema_module.schema_tools, "get_live_schema", _empty_schema
    )

    result = manage_schema(
        mode="validate",
        operations=[
            _property_key("name"),
            _property_key("weight"),
            _vertex_label("person", properties=["name"], primary_keys=["name"]),
            _vertex_label("software", properties=["name"], primary_keys=["name"]),
            _edge_label(
                "created",
                source_label="person",
                target_label="software",
                properties=["weight"],
            ),
            _index_label(
                "createdByWeight",
                base_type="EDGE",
                base_label="created",
                fields=["weight"],
            ),
        ],
    )

    assert result["ok"] is True
    assert result["data"]["valid"] is True
    assert result["data"]["errors"] == []


def test_same_batch_unknown_reference(monkeypatch):
    monkeypatch.setattr(
        manage_schema_module.schema_tools, "get_live_schema", _empty_schema
    )

    result = manage_schema(
        mode="validate",
        operations=[_vertex_label("person", properties=["missing"])],
    )

    assert result["ok"] is True
    assert result["data"]["valid"] is False
    error = result["data"]["errors"][0]
    assert error["operation_index"] == 0
    assert "undefined property key" in error["reason"]
    assert "missing" in error["reason"]


def test_same_batch_duplicate_definition(monkeypatch):
    monkeypatch.setattr(
        manage_schema_module.schema_tools, "get_live_schema", _empty_schema
    )

    result = manage_schema(
        mode="validate",
        operations=[_property_key("age"), _property_key("age")],
    )

    assert result["ok"] is True
    assert result["data"]["valid"] is False
    error = result["data"]["errors"][0]
    assert error["operation_index"] == 1
    assert error["reason"] == (
        "duplicate create_property_key name age within the same batch"
    )


def test_same_batch_edge_missing_endpoint(monkeypatch):
    monkeypatch.setattr(
        manage_schema_module.schema_tools, "get_live_schema", _empty_schema
    )

    result = manage_schema(
        mode="validate",
        operations=[
            _vertex_label("person"),
            _edge_label("created", source_label="person", target_label="software"),
        ],
    )

    assert result["ok"] is True
    assert result["data"]["valid"] is False
    error = result["data"]["errors"][0]
    assert error["operation_index"] == 1
    assert error["reason"] == "target_label references undefined vertex label: software"


def test_manage_schema_dry_run(monkeypatch):
    monkeypatch.setattr(
        manage_schema_module.schema_tools, "get_live_schema", _empty_schema
    )

    result = manage_schema(mode="dry_run", operations=[_property_key()])

    assert result["ok"] is True
    assert result["data"]["valid"] is True
    assert re.fullmatch(r"[0-9a-f]{32}", result["data"]["plan_hash"])
    assert "mutation_summary" in result["data"]
    assert isinstance(result["data"]["warnings"], list)


def test_manage_schema_dry_run_invalid_schema_has_no_plan_hash(monkeypatch):
    monkeypatch.setattr(
        manage_schema_module.schema_tools,
        "get_live_schema",
        lambda: _schema(propertykeys=[_live_pk("name")]),
    )

    result = manage_schema(
        mode="dry_run",
        operations=[
            {
                "type": "create_vertex_label",
                "name": "person",
                "properties": ["age"],
            }
        ],
    )

    assert result["ok"] is True
    assert result["data"]["valid"] is False
    assert "plan_hash" not in result["data"]


def test_manage_schema_dry_run_same_ops_same_hash(monkeypatch):
    monkeypatch.setattr(
        manage_schema_module.schema_tools, "get_live_schema", _empty_schema
    )

    first = manage_schema(mode="dry_run", operations=[_property_key()])
    second = manage_schema(mode="dry_run", operations=[_property_key()])

    assert first["data"]["plan_hash"] == second["data"]["plan_hash"]


def test_manage_schema_dry_run_different_ops_different_hash(monkeypatch):
    monkeypatch.setattr(
        manage_schema_module.schema_tools, "get_live_schema", _empty_schema
    )

    first = manage_schema(mode="dry_run", operations=[_property_key("age")])
    second = manage_schema(mode="dry_run", operations=[_property_key("score")])

    assert first["data"]["plan_hash"] != second["data"]["plan_hash"]


def test_manage_schema_plan_hash_schema_field_order_same_hash():
    operations = [_property_key()]
    schema = _schema(
        propertykeys=[
            {"name": "name", "data_type": "TEXT"},
            {"name": "age", "data_type": "INT"},
        ],
        vertexlabels=[
            {
                "name": "person",
                "properties": [{"name": "name"}, {"name": "age"}],
                "primary_keys": ["name"],
            },
        ],
        edgelabels=[
            {"name": "knows", "source_label": "person", "target_label": "person"},
        ],
    )
    reordered_schema = _schema(
        propertykeys=[
            {"name": "age", "data_type": "INT"},
            {"name": "name", "data_type": "TEXT"},
        ],
        vertexlabels=[
            {
                "name": "person",
                "properties": [{"name": "age"}, {"name": "name"}],
                "primaryKeys": ["name"],
            },
        ],
        edgelabels=[
            {"name": "knows", "sourceLabel": "person", "targetLabel": "person"},
        ],
    )

    first = manage_schema_module.calculate_plan_hash(operations, schema)
    second = manage_schema_module.calculate_plan_hash(operations, reordered_schema)

    assert first == second


def test_manage_schema_plan_hash_schema_primary_key_change_different_hash():
    operations = [_property_key()]
    schema = _schema(
        vertexlabels=[
            {"name": "person", "properties": ["name", "age"], "primary_keys": ["name"]},
        ],
    )
    changed_schema = _schema(
        vertexlabels=[
            {"name": "person", "properties": ["name", "age"], "primary_keys": ["age"]},
        ],
    )

    first = manage_schema_module.calculate_plan_hash(operations, schema)
    second = manage_schema_module.calculate_plan_hash(operations, changed_schema)

    assert first != second


def test_manage_schema_plan_hash_schema_metadata_ignored_same_hash():
    operations = [_property_key()]
    schema = _schema(
        propertykeys=[{"name": "name", "data_type": "TEXT"}],
        vertexlabels=[
            {"name": "person", "properties": ["name"], "primary_keys": ["name"]}
        ],
    )
    schema_with_metadata = _schema(
        propertykeys=[
            {
                "id": 1,
                "name": "name",
                "data_type": "TEXT",
                "user_data": {"x": "y"},
            }
        ],
        vertexlabels=[
            {
                "id": 99,
                "name": "person",
                "properties": ["name"],
                "primary_keys": ["name"],
                "user_data": {"x": "y"},
            }
        ],
    )
    schema_with_metadata["server_time"] = "2026-05-26T00:00:00Z"

    first = manage_schema_module.calculate_plan_hash(operations, schema)
    second = manage_schema_module.calculate_plan_hash(operations, schema_with_metadata)

    assert first == second


def test_manage_schema_plan_hash_operation_order_different_hash():
    schema = _empty_schema()
    operations = [_property_key("age"), _property_key("score")]
    reordered_operations = [_property_key("score"), _property_key("age")]

    first = manage_schema_module.calculate_plan_hash(operations, schema)
    second = manage_schema_module.calculate_plan_hash(reordered_operations, schema)

    assert first != second


def test_manage_schema_apply_is_not_an_internal_v1_mode():
    result = manage_schema(
        mode="apply",
        operations=[_property_key()],
        confirm=True,
        plan_hash="0000000000000000",
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "SCHEMA_MISMATCH"
    assert "Unsupported manage_schema mode: apply" in result["error"]["message"]
