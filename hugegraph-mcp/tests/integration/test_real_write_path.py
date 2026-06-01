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

"""Layer B integration tests for the real HugeGraph write path."""

from __future__ import annotations

from uuid import uuid4

import pytest
from pyhugegraph.client import PyHugeClient

from hugegraph_mcp import server
from hugegraph_mcp.config import MCPConfig
from hugegraph_mcp.hugegraph_client import build_hugegraph_client
from hugegraph_mcp.tools import manage_graph_data as manage_graph_data_module
from hugegraph_mcp.tools.graph_data_gremlin import _g


pytestmark = [pytest.mark.integration, pytest.mark.real_hugegraph]


@pytest.fixture
def hugegraph_client(monkeypatch):
    if _env("RUN_MCP_REAL_HUGEGRAPH_TESTS") != "1":
        pytest.skip(
            "set RUN_MCP_REAL_HUGEGRAPH_TESTS=1 to run real HugeGraph write tests"
        )

    monkeypatch.setenv("HUGEGRAPH_URL", _env("HUGEGRAPH_URL", "http://127.0.0.1:8080"))
    monkeypatch.setenv(
        "HUGEGRAPH_GRAPH_PATH", _env("HUGEGRAPH_GRAPH_PATH", "DEFAULT/hugegraph")
    )
    monkeypatch.setenv("HUGEGRAPH_USER", _env("HUGEGRAPH_USER", "admin"))
    monkeypatch.setenv("HUGEGRAPH_PASSWORD", _env("HUGEGRAPH_PASSWORD", "admin"))
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    monkeypatch.setenv("HUGEGRAPH_MCP_ALLOW_AI", "false")
    monkeypatch.setenv("HUGEGRAPH_MCP_ADMIN_MODE", "false")

    client = build_hugegraph_client(MCPConfig.from_env(), client_cls=PyHugeClient)
    try:
        client.schema().getSchema()
    except Exception as exc:  # pragma: no cover - depends on external service
        pytest.fail(f"HugeGraph Server is not available: {exc}")
    return client


def test_id_based_ingest_writes_the_intended_edge(hugegraph_client):
    names = _schema_names("id_edge")
    _ensure_custom_id_schema(hugegraph_client, names)
    _exec(
        hugegraph_client,
        f"g.addV({_g(names.vertex_label)}).property(T.id,'decoy')"
        f".property({_g(names.name_key)},'Alice')",
    )

    graph_data = {
        "vertices": [
            {
                "id": "alice",
                "label": names.vertex_label,
                "properties": {names.name_key: "Alice"},
            },
            {
                "id": "bob",
                "label": names.vertex_label,
                "properties": {names.name_key: "Bob"},
            },
        ],
        "edges": [
            {
                "label": names.edge_label,
                "source_label": names.vertex_label,
                "target_label": names.vertex_label,
                "source": {"id": "alice"},
                "target": {"id": "bob"},
            }
        ],
    }

    result = _import_graph_data(graph_data)

    assert result["ok"] is True
    assert (
        _count(
            hugegraph_client,
            f"g.V().hasId('alice').out({_g(names.edge_label)}).hasId('bob')",
        )
        == 1
    )
    assert (
        _count(
            hugegraph_client,
            f"g.V().hasId('decoy').out({_g(names.edge_label)})",
        )
        == 0
    )


def test_create_edge_rejects_missing_endpoint(hugegraph_client):
    names = _schema_names("missing")
    _ensure_custom_id_schema(hugegraph_client, names)
    _exec(
        hugegraph_client,
        f"g.addV({_g(names.vertex_label)}).property(T.id,'alice')"
        f".property({_g(names.name_key)},'Alice')",
    )
    change_plan = {
        "operations": [
            {
                "op": "create_edge",
                "label": names.edge_label,
                "source_label": names.vertex_label,
                "source_match": {"id": "alice"},
                "target_label": names.vertex_label,
                "target_match": {"id": "bob"},
            }
        ]
    }

    result = manage_graph_data_module.dry_run_graph_change_plan(
        change_plan,
        manage_graph_data_module._fetch_live_schema(),
    )

    assert result["valid"] is False
    assert any(
        "target endpoint matched_count must be 1" in error["reason"]
        for error in result["errors"]
    )
    assert (
        _count(
            hugegraph_client,
            f"g.V().hasId('alice').out({_g(names.edge_label)}).hasId('bob')",
        )
        == 0
    )


def test_create_edge_rejects_non_unique_property_match(hugegraph_client):
    names = _schema_names("nonunique")
    _ensure_custom_id_schema(hugegraph_client, names)
    _exec(
        hugegraph_client,
        f"g.addV({_g(names.vertex_label)}).property(T.id,'alice_1')"
        f".property({_g(names.name_key)},'Alice')",
    )
    _exec(
        hugegraph_client,
        f"g.addV({_g(names.vertex_label)}).property(T.id,'alice_2')"
        f".property({_g(names.name_key)},'Alice')",
    )
    _exec(
        hugegraph_client,
        f"g.addV({_g(names.vertex_label)}).property(T.id,'bob')"
        f".property({_g(names.name_key)},'Bob')",
    )
    change_plan = {
        "operations": [
            {
                "op": "create_edge",
                "label": names.edge_label,
                "source_label": names.vertex_label,
                "source_match": {names.name_key: "Alice"},
                "target_label": names.vertex_label,
                "target_match": {"id": "bob"},
            }
        ]
    }

    result = manage_graph_data_module.dry_run_graph_change_plan(
        change_plan,
        manage_graph_data_module._fetch_live_schema(),
    )

    assert result["valid"] is False
    assert any(
        "source endpoint matched_count must be 1" in error["reason"]
        for error in result["errors"]
    )
    assert (
        _count(
            hugegraph_client,
            f"g.V().has({_g(names.name_key)},'Alice').out({_g(names.edge_label)})",
        )
        == 0
    )


def test_partial_write_returns_error_envelope_and_real_graph_state_matches(
    hugegraph_client,
):
    names = _schema_names("partial")
    _ensure_custom_id_schema(hugegraph_client, names, unique_name=True)
    graph_data = {
        "vertices": [
            {
                "label": names.vertex_label,
                "id": "alice",
                "properties": {names.name_key: "Duplicate"},
            },
            {
                "label": names.vertex_label,
                "id": "conflict",
                "properties": {names.name_key: "Duplicate"},
            },
        ],
        "edges": [],
    }
    dry_run = server.import_graph_data_tool(mode="ingest", graph_data=graph_data)
    assert dry_run["ok"] is True

    plan_context = dry_run["data"]["plan_context"]

    result = server.import_graph_data_tool(
        mode="ingest",
        graph_data=graph_data,
        dry_run=False,
        confirm=True,
        plan_hash=dry_run["data"]["plan_hash"],
        nonce=plan_context["nonce"],
        expires_at=plan_context["expires_at"],
    )

    assert result["ok"] is False
    assert result["error"]["details"]["status"] == "partial"
    assert (
        _count(
            hugegraph_client,
            f"g.V().hasLabel({_g(names.vertex_label)}).hasId('alice')",
        )
        == 1
    )
    assert (
        _count(
            hugegraph_client,
            f"g.V().hasLabel({_g(names.vertex_label)})"
            f".hasId('conflict').has({_g(names.name_key)},'Duplicate')",
        )
        == 0
    )


def test_public_ingest_readonly_gate_prevents_real_write(hugegraph_client, monkeypatch):
    names = _schema_names("readonly")
    _ensure_custom_id_schema(hugegraph_client, names)
    graph_data = {
        "vertices": [
            {
                "id": "readonly_alice",
                "label": names.vertex_label,
                "properties": {names.name_key: "Alice"},
            }
        ],
        "edges": [],
    }
    dry_run = server.import_graph_data_tool(mode="ingest", graph_data=graph_data)
    assert dry_run["ok"] is True
    plan_context = dry_run["data"]["plan_context"]

    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "true")
    result = server.import_graph_data_tool(
        mode="ingest",
        graph_data=graph_data,
        dry_run=False,
        confirm=True,
        plan_hash=dry_run["data"]["plan_hash"],
        nonce=plan_context["nonce"],
        expires_at=plan_context["expires_at"],
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "READONLY_VIOLATION"
    assert (
        _count(
            hugegraph_client,
            f"g.V().hasLabel({_g(names.vertex_label)}).hasId('readonly_alice')",
        )
        == 0
    )


def test_admin_write_tool_gate_prevents_real_write(hugegraph_client, monkeypatch):
    names = _schema_names("admin")
    _ensure_custom_id_schema(hugegraph_client, names)
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    monkeypatch.setenv("HUGEGRAPH_MCP_ADMIN_MODE", "false")

    result = server.execute_gremlin_write_tool(
        gremlin_query=(
            f"g.addV({_g(names.vertex_label)}).property(T.id,'admin_blocked')"
            f".property({_g(names.name_key)},'Blocked')"
        )
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "FEATURE_DISABLED"
    assert (
        _count(
            hugegraph_client,
            f"g.V().hasLabel({_g(names.vertex_label)}).hasId('admin_blocked')",
        )
        == 0
    )


def _import_graph_data(graph_data: dict) -> dict:
    dry_run = server.import_graph_data_tool(mode="ingest", graph_data=graph_data)
    assert dry_run["ok"] is True
    plan_context = dry_run["data"]["plan_context"]
    return server.import_graph_data_tool(
        mode="ingest",
        graph_data=graph_data,
        dry_run=False,
        confirm=True,
        plan_hash=dry_run["data"]["plan_hash"],
        nonce=plan_context["nonce"],
        expires_at=plan_context["expires_at"],
    )


class _Names:
    def __init__(self, prefix: str) -> None:
        suffix = uuid4().hex[:8]
        self.name_key = f"{prefix}_name_{suffix}"
        self.vertex_label = f"{prefix}_v_{suffix}"
        self.edge_label = f"{prefix}_e_{suffix}"
        self.name_index = f"{prefix}_name_idx_{suffix}"


def _schema_names(prefix: str) -> _Names:
    return _Names(prefix)


def _ensure_custom_id_schema(
    client,
    names: _Names,
    *,
    unique_name: bool = False,
) -> None:
    schema = client.schema()
    schema.propertyKey(names.name_key).asText().ifNotExist().create()
    schema.vertexLabel(names.vertex_label).properties(
        names.name_key
    ).useCustomizeStringId().nullableKeys(names.name_key).ifNotExist().create()
    schema.edgeLabel(names.edge_label).sourceLabel(names.vertex_label).targetLabel(
        names.vertex_label
    ).ifNotExist().create()
    index = (
        schema.indexLabel(names.name_index).onV(names.vertex_label).by(names.name_key)
    )
    if unique_name:
        index.unique().ifNotExist().create()
    else:
        index.secondary().ifNotExist().create()


def _exec(client, query: str):
    return client.gremlin().exec(query)


def _count(client, query: str) -> int:
    return int(_extract_count(_exec(client, f"{query}.count()")) or 0)


def _extract_count(data):
    if isinstance(data, dict) and "data" in data:
        return _extract_count(data["data"])
    if isinstance(data, list):
        return _extract_count(data[0]) if data else 0
    return data


def _env(name: str, default: str | None = None) -> str | None:
    import os

    return os.environ.get(name, default)
