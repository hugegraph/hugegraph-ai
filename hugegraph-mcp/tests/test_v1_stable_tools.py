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

"""Tests for V1 stable tools and admin gate (Milestone 2)."""

import asyncio
from unittest.mock import Mock
import warnings

from hugegraph_mcp import server
from hugegraph_mcp.envelope import ErrorType, envelope_err, envelope_ok


async def _list_mcp_tools():
    list_tools = getattr(server.mcp, "_mcp_list_tools", None)
    if list_tools is None:
        list_tools = getattr(server.mcp, "_list_tools")
    return await list_tools()


def _assert_v1_envelope_shape(result):
    assert set(result) == {"ok", "data", "error", "warnings", "next_actions", "meta"}
    assert result["meta"]["request_id"].startswith("req-")
    assert "graph" in result["meta"]
    assert "graphspace" in result["meta"]
    assert "readonly" in result["meta"]
    assert "duration_ms" in result["meta"]


def test_public_tool_contract_lists_only_v1_tools():
    async def _tool_names():
        tools = await _list_mcp_tools()
        return {tool.name for tool in tools}

    assert asyncio.run(_tool_names()) == {
        "inspect_graph_tool",
        "generate_gremlin_tool",
        "execute_gremlin_read_tool",
        "extract_graph_data_tool",
        "design_schema_tool",
        "apply_schema_tool",
        "import_graph_data_tool",
        "delete_graph_data_tool",
        "refresh_vid_embeddings_tool",
        "execute_gremlin_write_tool",
    }


def test_public_tool_argument_models_do_not_emit_schema_shadow_warning():
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")

        async def _list_tools():
            return await _list_mcp_tools()

        asyncio.run(_list_tools())

    assert not any("shadows an attribute" in str(item.message) for item in captured)


def test_generate_gremlin_tool_routes_to_generate_gremlin(monkeypatch):
    expected = envelope_ok({"gremlin": "g.V().count()"})
    mock = Mock(return_value=expected)
    monkeypatch.setattr(server, "generate_gremlin", mock)

    result = server.generate_gremlin_tool(query="count vertices", execute=True)

    _assert_v1_envelope_shape(result)
    assert result["ok"] is True
    assert result["data"] == expected["data"]
    mock.assert_called_once_with(query="count vertices", execute=True)


def test_execute_gremlin_read_tool_routes_to_execute_gremlin_read(monkeypatch):
    expected = envelope_ok({"data": [1, 2, 3]})
    mock = Mock(return_value=expected)
    monkeypatch.setattr(server, "execute_gremlin_read", mock)

    result = server.execute_gremlin_read_tool(gremlin_query="g.V().limit(3)")

    _assert_v1_envelope_shape(result)
    assert result["ok"] is True
    assert result["data"] == expected["data"]
    mock.assert_called_once_with("g.V().limit(3)")


def test_extract_graph_data_tool_routes_to_extract_graph_data(monkeypatch):
    expected = envelope_ok({"graph_data": {"vertices": [], "edges": []}})
    mock = Mock(return_value=expected)
    monkeypatch.setattr(server, "extract_graph_data", mock)

    result = server.extract_graph_data_tool(
        text="Alice knows Bob.",
        graph_schema={"vertexlabels": ["person"]},
        example_prompt="extract people",
    )

    _assert_v1_envelope_shape(result)
    assert result["ok"] is True
    assert result["data"] == expected["data"]
    mock.assert_called_once_with(
        text="Alice knows Bob.",
        schema={"vertexlabels": ["person"]},
        example_prompt="extract people",
    )


def test_design_schema_tool_routes_to_manage_schema_design(monkeypatch):
    expected = envelope_ok({"suggestions": []})
    mock = Mock(return_value=expected)
    monkeypatch.setattr(server, "manage_schema", mock)

    result = server.design_schema_tool(operations=[{"op": "add_vertex_label"}])

    _assert_v1_envelope_shape(result)
    assert result["ok"] is True
    assert result["data"] == expected["data"]
    mock.assert_called_once_with(mode="design", operations=[{"op": "add_vertex_label"}])


def test_apply_schema_tool_validate_routes_to_manage_schema(monkeypatch):
    expected = envelope_ok({"valid": True})
    mock = Mock(return_value=expected)
    monkeypatch.setattr(server, "manage_schema", mock)

    result = server.apply_schema_tool(
        mode="validate", operations=[{"op": "add_vertex_label"}]
    )

    _assert_v1_envelope_shape(result)
    assert result["ok"] is True
    assert result["data"] == expected["data"]
    mock.assert_called_once_with(
        mode="validate",
        operations=[{"op": "add_vertex_label"}],
        confirm=False,
        plan_hash=None,
    )


def test_apply_schema_tool_dry_run_routes_to_manage_schema(monkeypatch):
    expected = envelope_ok({"plan_hash": "abc123"})
    mock = Mock(return_value=expected)
    monkeypatch.setattr(server, "manage_schema", mock)

    result = server.apply_schema_tool(
        mode="dry_run", operations=[{"op": "add_vertex_label"}]
    )

    _assert_v1_envelope_shape(result)
    assert result["ok"] is True
    assert result["data"] == expected["data"]
    mock.assert_called_once_with(
        mode="dry_run",
        operations=[{"op": "add_vertex_label"}],
        confirm=False,
        plan_hash=None,
    )


def test_apply_schema_tool_apply_returns_feature_disabled():
    result = server.apply_schema_tool(mode="apply", operations=[{"op": "test"}])

    _assert_v1_envelope_shape(result)
    assert result["ok"] is False
    assert result["error"]["type"] == "FEATURE_DISABLED"
    assert result["error"]["source"] == "apply_schema_tool"
    assert "apply" in result["error"]["message"].lower()


def test_delete_graph_data_tool_routes_to_manage_graph_data_delete(monkeypatch):
    expected = envelope_ok({"valid": True, "preview": [], "plan_hash": "abc123"})
    mock = Mock(return_value=expected)
    monkeypatch.setattr(server, "manage_graph_data", mock)
    change_plan = {
        "operations": [
            {
                "op": "delete_vertex",
                "label": "person",
                "match": {"name": "Alice"},
            }
        ]
    }

    result = server.delete_graph_data_tool(change_plan=change_plan)

    _assert_v1_envelope_shape(result)
    assert result["ok"] is True
    assert result["data"] == expected["data"]
    mock.assert_called_once_with(
        mode="delete",
        change_plan=change_plan,
        dry_run=True,
        confirm=False,
        plan_hash=None,
        nonce=None,
        expires_at=None,
        plan_tool_name="delete_graph_data_tool",
    )


def test_generate_gremlin_tool_aligns_error_source(monkeypatch):
    expected = {
        **envelope_ok(),
        "ok": False,
        "data": None,
        "error": {
            "type": "HUGEGRAPH_AI_UNAVAILABLE",
            "message": "AI disabled",
            "suggestion": None,
            "retryable": False,
            "source": "hugegraph-ai",
            "details": {},
        },
    }
    mock = Mock(return_value=expected)
    monkeypatch.setattr(server, "generate_gremlin", mock)

    result = server.generate_gremlin_tool(query="count vertices")

    _assert_v1_envelope_shape(result)
    assert result["ok"] is False
    assert result["error"]["source"] == "generate_gremlin_tool"


def test_execute_gremlin_read_tool_aligns_error_source(monkeypatch):
    expected = envelope_err(
        ErrorType.UNSAFE_GREMLIN,
        "Unsafe query",
        source="gremlin_tools",
    )
    mock = Mock(return_value=expected)
    monkeypatch.setattr(server, "execute_gremlin_read", mock)

    result = server.execute_gremlin_read_tool(gremlin_query="g.addV('person')")

    _assert_v1_envelope_shape(result)
    assert result["ok"] is False
    assert result["error"]["source"] == "execute_gremlin_read_tool"


def test_admin_gate_blocks_write_tool_by_default(monkeypatch):
    monkeypatch.setattr(server, "ADMIN_MODE", False)

    result = server.execute_gremlin_write_tool(gremlin_query="g.addV('test')")

    assert result["ok"] is False
    assert result["error"]["type"] == "FEATURE_DISABLED"
    assert "ADMIN_MODE" in result["error"]["message"]


def test_admin_gate_blocks_refresh_embeddings_by_default(monkeypatch):
    monkeypatch.setattr(server, "ADMIN_MODE", False)

    result = server.refresh_vid_embeddings_tool(confirm=True)

    assert result["ok"] is False
    assert result["error"]["type"] == "FEATURE_DISABLED"
    assert "ADMIN_MODE" in result["error"]["message"]


def test_admin_gate_allows_write_tool_when_enabled(monkeypatch):
    monkeypatch.setattr(server, "ADMIN_MODE", True)
    expected = envelope_ok({"data": "ok"})
    mock = Mock(return_value=expected)
    monkeypatch.setattr(server, "execute_gremlin_write", mock)

    result = server.execute_gremlin_write_tool(gremlin_query="g.addV('test')")

    assert result == expected
    mock.assert_called_once_with("g.addV('test')")


def test_admin_gate_allows_refresh_embeddings_when_enabled(monkeypatch):
    monkeypatch.setattr(server, "ADMIN_MODE", True)
    expected = envelope_ok({"data": "refreshed"})
    mock = Mock(return_value=expected)
    monkeypatch.setattr(server, "refresh_vid_embeddings", mock)

    result = server.refresh_vid_embeddings_tool(confirm=True)

    assert result == expected
    mock.assert_called_once_with(confirm=True)
