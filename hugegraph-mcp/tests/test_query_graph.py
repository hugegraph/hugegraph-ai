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

from unittest.mock import Mock

from hugegraph_mcp.envelope import ErrorType, envelope_err, envelope_ok
from hugegraph_mcp.tools import query_graph as query_graph_module


def _ai_ok(**extra) -> dict:
    data = {
        "answer": "Alice knows Bob.",
        "evidence": "Alice -> knows -> Bob",
        "gremlin": "g.V().has('name', 'Alice').out('knows')",
        "source_summary": {"sources": 1},
    }
    data.update(extra)
    return envelope_ok(data)


def test_query_graph_basic(monkeypatch):
    post = Mock(return_value=_ai_ok())
    monkeypatch.setattr(query_graph_module, "post", post)

    result = query_graph_module.query_graph_by_text("Who does Alice know?")

    assert result["ok"] is True
    assert result["data"]["answer"] == "Alice knows Bob."
    assert result["data"]["gremlin"] == "g.V().has('name', 'Alice').out('knows')"
    assert result["data"]["source_summary"] == {"sources": 1}
    assert result["data"]["mode"] == "graph_only"
    assert result["data"]["truncated"] is False
    assert result["data"]["evidence"] is None
    post.assert_called_once_with(
        "/rag/graph",
        json={
            "query": "Who does Alice know?",
            "graph": "hugegraph",
            "graphspace": "DEFAULT",
            "max_context_items": 20,
        },
    )


def test_query_graph_vector_mode(monkeypatch):
    post = Mock(return_value=_ai_ok())
    monkeypatch.setattr(query_graph_module, "post", post)

    result = query_graph_module.query_graph_by_text(
        "Who does Alice know?",
        mode="vector_only",
    )

    assert result["ok"] is True
    assert result["data"]["mode"] == "vector_only"
    post.assert_called_once_with(
        "/rag",
        json={
            "query": "Who does Alice know?",
            "graph": "hugegraph",
            "graphspace": "DEFAULT",
            "max_context_items": 20,
        },
    )


def test_query_graph_with_evidence(monkeypatch):
    post = Mock(return_value=_ai_ok())
    monkeypatch.setattr(query_graph_module, "post", post)

    result = query_graph_module.query_graph_by_text(
        "Who does Alice know?",
        include_evidence=True,
    )

    assert result["ok"] is True
    assert result["data"]["evidence"] == "Alice -> knows -> Bob"
    assert result["data"]["truncated"] is False


def test_query_graph_truncation(monkeypatch):
    long_evidence = "x" * 2001
    post = Mock(return_value=_ai_ok(evidence=long_evidence))
    monkeypatch.setattr(query_graph_module, "post", post)

    result = query_graph_module.query_graph_by_text(
        "Who does Alice know?",
        include_evidence=True,
    )

    assert result["ok"] is True
    assert len(result["data"]["evidence"]) == 2003
    assert result["data"]["evidence"] == f"{'x' * 2000}..."
    assert result["data"]["truncated"] is True


def test_query_graph_invalid_mode(monkeypatch):
    post = Mock()
    monkeypatch.setattr(query_graph_module, "post", post)

    result = query_graph_module.query_graph_by_text(
        "Who does Alice know?",
        mode="hybrid",
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "VALIDATION_ERROR"
    assert result["error"]["details"]["mode"] == "hybrid"
    post.assert_not_called()


def test_query_graph_ai_unavailable(monkeypatch):
    ai_error = envelope_err(
        ErrorType.HUGEGRAPH_AI_UNAVAILABLE,
        "HugeGraph-AI is unavailable",
        retryable=True,
    )
    post = Mock(return_value=ai_error)
    monkeypatch.setattr(query_graph_module, "post", post)

    result = query_graph_module.query_graph_by_text("Who does Alice know?")

    assert result == ai_error


def test_query_graph_graph_config(monkeypatch):
    post = Mock(return_value=_ai_ok())
    monkeypatch.setenv("HUGEGRAPH_GRAPH", "graph_a")
    monkeypatch.setenv("HUGEGRAPH_GRAPHSPACE", "space_a")
    monkeypatch.setattr(query_graph_module, "post", post)

    result = query_graph_module.query_graph_by_text("Who does Alice know?")

    assert result["ok"] is True
    post.assert_called_once_with(
        "/rag/graph",
        json={
            "query": "Who does Alice know?",
            "graph": "graph_a",
            "graphspace": "space_a",
            "max_context_items": 20,
        },
    )


def test_query_graph_custom_max_context_items(monkeypatch):
    post = Mock(return_value=_ai_ok())
    monkeypatch.setattr(query_graph_module, "post", post)

    query_graph_module.query_graph_by_text(
        "Who does Alice know?",
        max_context_items=50,
    )

    post.assert_called_once_with(
        "/rag/graph",
        json={
            "query": "Who does Alice know?",
            "graph": "hugegraph",
            "graphspace": "DEFAULT",
            "max_context_items": 50,
        },
    )
