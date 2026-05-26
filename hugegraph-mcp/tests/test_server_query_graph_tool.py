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

import importlib
from unittest.mock import Mock


def _reload_server(monkeypatch, *, graphrag_enabled: bool = False):
    monkeypatch.setenv(
        "HUGEGRAPH_MCP_ENABLE_GRAPHRAG_EXPERIMENTAL",
        "true" if graphrag_enabled else "false",
    )

    import hugegraph_mcp.server

    return importlib.reload(hugegraph_mcp.server)


def test_query_graph_text_mode_is_disabled_by_default(monkeypatch):
    server = _reload_server(monkeypatch, graphrag_enabled=False)
    query_graph_by_text = Mock()
    monkeypatch.setattr(server, "query_graph_by_text", query_graph_by_text)

    result = server.query_graph_tool(mode="text", query="Who does Alice know?")

    assert result["ok"] is False
    assert result["error"]["type"] == "FEATURE_DISABLED"
    assert result["error"]["details"]["feature"] == "GraphRAG"
    assert (
        result["error"]["details"]["enable_env"]
        == "HUGEGRAPH_MCP_ENABLE_GRAPHRAG_EXPERIMENTAL"
    )
    assert "mode='generate'" in result["next_actions"][0]
    query_graph_by_text.assert_not_called()


def test_query_graph_text_mode_can_be_enabled_for_debugging(monkeypatch):
    server = _reload_server(monkeypatch, graphrag_enabled=True)
    expected = {"ok": True, "data": {"answer": "Alice knows Bob."}}
    query_graph_by_text = Mock(return_value=expected)
    monkeypatch.setattr(server, "query_graph_by_text", query_graph_by_text)

    result = server.query_graph_tool(
        mode="text",
        query="Who does Alice know?",
        rag_mode="graph_only",
        include_evidence=True,
        max_context_items=5,
    )

    assert result == expected
    query_graph_by_text.assert_called_once_with(
        query="Who does Alice know?",
        mode="graph_only",
        include_evidence=True,
        max_context_items=5,
    )


def test_query_graph_generate_mode_is_unchanged(monkeypatch):
    server = _reload_server(monkeypatch, graphrag_enabled=False)
    expected = {"ok": True, "data": {"gremlin": "g.V().count()"}}
    generate_gremlin = Mock(return_value=expected)
    monkeypatch.setattr(server, "generate_gremlin", generate_gremlin)

    result = server.query_graph_tool(
        mode="generate",
        query="count vertices",
        execute=True,
    )

    assert result == expected
    generate_gremlin.assert_called_once_with(query="count vertices", execute=True)


def test_query_graph_gremlin_mode_returns_execute_envelope_directly(monkeypatch):
    server = _reload_server(monkeypatch, graphrag_enabled=False)
    expected = {
        "ok": True,
        "data": {
            "data": ["alice", "bob"],
            "total": 2,
            "duration_ms": 1.5,
            "is_read": True,
        },
        "error": None,
        "warnings": [],
        "next_actions": [],
        "meta": {"duration_ms": 1.5},
    }
    execute_gremlin_read = Mock(return_value=expected)
    monkeypatch.setattr(server, "execute_gremlin_read", execute_gremlin_read)

    result = server.query_graph_tool(
        mode="gremlin",
        gremlin_query="g.V().limit(2)",
    )

    assert result == expected
    execute_gremlin_read.assert_called_once_with("g.V().limit(2)")
