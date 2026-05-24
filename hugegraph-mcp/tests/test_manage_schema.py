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


def _property_key(name="age"):
    return {"type": "create_property_key", "name": name, "data_type": "INT"}


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


def test_manage_schema_validate_valid():
    result = manage_schema(mode="validate", operations=[_property_key()])

    assert result["ok"] is True
    assert result["data"]["valid"] is True
    assert result["data"]["errors"] == []


def test_manage_schema_validate_invalid_missing_name():
    result = manage_schema(
        mode="validate",
        operations=[{"type": "create_property_key"}],
    )

    assert result["ok"] is True
    assert result["data"]["valid"] is False
    assert "missing required field: name" in result["data"]["errors"][0]


def test_manage_schema_validate_rejects_delete():
    result = manage_schema(
        mode="validate",
        operations=[{"type": "delete_vertex_label", "name": "person"}],
    )

    assert result["ok"] is True
    assert result["data"]["valid"] is False
    assert "unsupported delete/drop type" in result["data"]["errors"][0]


def test_manage_schema_dry_run(monkeypatch):
    monkeypatch.setattr(
        manage_schema_module.schema_tools, "get_live_schema", _empty_schema
    )

    result = manage_schema(mode="dry_run", operations=[_property_key()])

    assert result["ok"] is True
    assert result["data"]["valid"] is True
    assert re.fullmatch(r"[0-9a-f]{16}", result["data"]["plan_hash"])
    assert "mutation_summary" in result["data"]
    assert isinstance(result["data"]["warnings"], list)


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


def test_manage_schema_apply_missing_confirm(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")

    result = manage_schema(
        mode="apply",
        operations=[_property_key()],
        confirm=False,
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "CONFIRM_REQUIRED"


def test_manage_schema_apply_plan_hash_mismatch(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    monkeypatch.setattr(
        manage_schema_module.schema_tools, "get_live_schema", _empty_schema
    )

    result = manage_schema(
        mode="apply",
        operations=[_property_key()],
        confirm=True,
        plan_hash="0000000000000000",
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "PLAN_HASH_MISMATCH"


def test_manage_schema_apply_readonly(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "true")

    result = manage_schema(
        mode="apply",
        operations=[_property_key()],
        confirm=True,
        plan_hash="0000000000000000",
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "READONLY_VIOLATION"


def test_manage_schema_apply_success(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    monkeypatch.setattr(
        manage_schema_module.schema_tools, "get_live_schema", _empty_schema
    )

    operations = [_property_key()]
    dry_run = manage_schema(mode="dry_run", operations=operations)

    def fake_execute(ops):
        return {"success": True, "results": [{"op": ops[0], "status": "ok"}], "errors": []}

    monkeypatch.setattr(
        manage_schema_module.schema_tools,
        "execute_schema_operations",
        fake_execute,
    )

    result = manage_schema(
        mode="apply",
        operations=operations,
        confirm=True,
        plan_hash=dry_run["data"]["plan_hash"],
    )

    assert result["ok"] is True
    assert result["data"]["success"] is True
    assert result["data"]["errors"] == []
