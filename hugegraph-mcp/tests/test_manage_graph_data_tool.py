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


def test_manage_graph_data_tool_extract_routes_to_extract(monkeypatch):
    calls = []

    def fake_extract_graph_data(text, schema=None, example_prompt=None):
        calls.append((text, schema, example_prompt))
        return envelope_ok({"graph_data": {"vertices": [], "edges": []}})

    monkeypatch.setattr(server, "extract_graph_data", fake_extract_graph_data)

    result = server.manage_graph_data_tool(
        mode="extract",
        text="Alice knows Bob.",
        schema={"vertexlabels": ["person"]},
        example_prompt="extract people",
    )

    assert result["ok"] is True
    assert calls == [
        ("Alice knows Bob.", {"vertexlabels": ["person"]}, "extract people")
    ]


def test_manage_graph_data_tool_import_routes_to_manage_graph_data(monkeypatch):
    calls = []
    graph_data = {"vertices": [], "edges": []}

    def fake_manage_graph_data(
        mode,
        graph_data=None,
        change_plan=None,
        dry_run=True,
        confirm=False,
        plan_hash=None,
    ):
        calls.append((mode, graph_data, change_plan, dry_run, confirm, plan_hash))
        return envelope_ok({"plan_hash": "0123456789abcdef"})

    monkeypatch.setattr(server, "manage_graph_data", fake_manage_graph_data)

    result = server.manage_graph_data_tool(
        mode="import",
        graph_data=graph_data,
        dry_run=False,
        confirm=True,
        plan_hash="0123456789abcdef",
    )

    assert result["ok"] is True
    assert calls == [("import", graph_data, None, False, True, "0123456789abcdef")]


def test_manage_graph_data_tool_update_routes_to_manage_graph_data(monkeypatch):
    calls = []
    change_plan = {"operations": [{"op": "update_vertex"}]}

    def fake_manage_graph_data(
        mode,
        graph_data=None,
        change_plan=None,
        dry_run=True,
        confirm=False,
        plan_hash=None,
    ):
        calls.append((mode, graph_data, change_plan, dry_run, confirm, plan_hash))
        return envelope_ok({"plan_hash": "0123456789abcdef"})

    monkeypatch.setattr(server, "manage_graph_data", fake_manage_graph_data)

    result = server.manage_graph_data_tool(
        mode="update",
        change_plan=change_plan,
    )

    assert result["ok"] is True
    assert calls == [("update", None, change_plan, True, False, None)]


def test_manage_graph_data_tool_delete_routes_to_manage_graph_data(monkeypatch):
    calls = []
    change_plan = {"operations": [{"op": "delete_vertex"}]}

    def fake_manage_graph_data(
        mode,
        graph_data=None,
        change_plan=None,
        dry_run=True,
        confirm=False,
        plan_hash=None,
    ):
        calls.append((mode, graph_data, change_plan, dry_run, confirm, plan_hash))
        return envelope_ok({"plan_hash": "0123456789abcdef"})

    monkeypatch.setattr(server, "manage_graph_data", fake_manage_graph_data)

    result = server.manage_graph_data_tool(
        mode="delete",
        change_plan=change_plan,
        dry_run=False,
        confirm=True,
        plan_hash="0123456789abcdef",
    )

    assert result["ok"] is True
    assert calls == [("delete", None, change_plan, False, True, "0123456789abcdef")]


def test_manage_graph_data_tool_table_routes_to_manage_graph_data(monkeypatch):
    calls = []

    table_data = {
        "table_name": "people",
        "columns": ["name"],
        "rows": [["Alice"]],
    }
    mapping = {
        "vertex_mappings": [
            {
                "target_label": "person",
                "column_mapping": {"name": "name"},
                "primary_key_columns": ["name"],
            }
        ],
        "edge_mappings": [],
    }

    def fake_manage_graph_data(
        mode,
        graph_data=None,
        change_plan=None,
        dry_run=True,
        confirm=False,
        plan_hash=None,
    ):
        calls.append((mode, graph_data, change_plan, dry_run, confirm, plan_hash))
        return envelope_ok({"plan_hash": "0123456789abcdef"})

    monkeypatch.setattr(server, "manage_graph_data", fake_manage_graph_data)

    result = server.manage_graph_data_tool(
        mode="table",
        table_data=table_data,
        mapping=mapping,
        dry_run=False,
        confirm=True,
        plan_hash="0123456789abcdef",
    )

    assert result["ok"] is True
    assert len(calls) == 1
    mode, graph_data, change_plan, dry_run, confirm, plan_hash = calls[0]
    assert mode == "import"
    assert graph_data["vertices"][0] == {
        "label": "person",
        "properties": {"name": "Alice"},
    }
    assert change_plan["operations"][0] == {
        "op": "create_vertex",
        "label": "person",
        "properties": {"name": "Alice"},
    }
    assert (dry_run, confirm, plan_hash) == (
        False,
        True,
        "0123456789abcdef",
    )


def test_manage_graph_data_tool_validates_extract_text():
    result = server.manage_graph_data_tool(mode="extract")

    assert result["ok"] is False
    assert result["error"]["type"] == "VALIDATION_ERROR"
    assert "text is required" in result["error"]["message"]


def test_manage_graph_data_tool_validates_table_data():
    result = server.manage_graph_data_tool(mode="table")

    assert result["ok"] is False
    assert result["error"]["type"] == "VALIDATION_ERROR"
    assert "table_data is required" in result["error"]["message"]


def test_manage_graph_data_tool_rejects_unknown_mode():
    result = server.manage_graph_data_tool(mode="unknown")

    assert result["ok"] is False
    assert result["error"]["type"] == "VALIDATION_ERROR"
    assert result["error"]["details"] == {"mode": "unknown"}
