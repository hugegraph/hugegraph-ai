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
        "graph_only": "Alice knows Bob.",
        "evidence": "Alice -> knows -> Bob",
        "gremlin": "g.V().has('name', 'Alice').out('knows')",
        "source_summary": {"sources": 1},
    }
    data.update(extra)
    return envelope_ok(data)


def _expected_payload(
    query: str = "Who does Alice know?",
    *,
    graph: str = "hugegraph",
    graphspace: str = "DEFAULT",
    graph_url: str = "http://127.0.0.1:8080",
    max_context_items: int = 20,
    mode: str = "graph_only",
) -> dict:
    payload = {
        "query": query,
        "max_graph_items": max_context_items,
        "topk_return_results": max_context_items,
        "vector_dis_threshold": 0.9,
        "topk_per_keyword": 1,
        "gremlin_tmpl_num": -1,
        "rerank_method": "bleu",
        "near_neighbor_first": False,
        "custom_priority_info": "",
        "gremlin_prompt": None,
        "get_vertex_only": False,
        "client_config": {
            "url": graph_url,
            "graph": graph,
            "user": "admin",
            "pwd": "",
            "gs": graphspace,
        },
    }
    if mode == "vector_only":
        payload.update(
            {
                "raw_answer": False,
                "vector_only": True,
                "graph_only": False,
                "graph_vector_answer": False,
            }
        )
        payload.pop("get_vertex_only")
    return payload


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
        json=_expected_payload(),
    )


def test_query_graph_vector_mode(monkeypatch):
    post = Mock(return_value=_ai_ok(vector_only="Vector says Bob.", graph_only=None))
    monkeypatch.setattr(query_graph_module, "post", post)

    result = query_graph_module.query_graph_by_text(
        "Who does Alice know?",
        mode="vector_only",
    )

    assert result["ok"] is True
    assert result["data"]["answer"] == "Vector says Bob."
    assert result["data"]["mode"] == "vector_only"
    post.assert_called_once_with(
        "/rag",
        json=_expected_payload(mode="vector_only"),
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
        json=_expected_payload(graph="graph_a", graphspace="space_a"),
    )


def test_query_graph_uses_ai_graph_url_for_backend_client_config(monkeypatch):
    post = Mock(return_value=_ai_ok())
    monkeypatch.setenv("HUGEGRAPH_URL", "http://127.0.0.1:8080")
    monkeypatch.setenv("HUGEGRAPH_AI_GRAPH_URL", "http://server:8080")
    monkeypatch.setattr(query_graph_module, "post", post)

    result = query_graph_module.query_graph_by_text("Who does Alice know?")

    assert result["ok"] is True
    post.assert_called_once_with(
        "/rag/graph",
        json=_expected_payload(graph_url="http://server:8080"),
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
        json=_expected_payload(max_context_items=50),
    )


def test_query_graph_raw_rag_fields(monkeypatch):
    post = Mock(
        return_value=envelope_ok(
            {
                "raw_answer": "Raw answer.",
                "vector_only": "Vector answer.",
                "graph_only": "Graph answer.",
                "graph_vector_answer": "Hybrid answer.",
            }
        )
    )
    monkeypatch.setattr(query_graph_module, "post", post)

    result = query_graph_module.query_graph_by_text("Who does Alice know?")

    assert result["ok"] is True
    assert result["data"]["answer"] == (
        "graph_only: Graph answer.\n\n"
        "vector_only: Vector answer.\n\n"
        "graph_vector: Hybrid answer."
    )


def test_query_graph_empty_result_warning(monkeypatch):
    post = Mock(return_value=envelope_ok({"graph_only": ""}))
    monkeypatch.setattr(query_graph_module, "post", post)

    result = query_graph_module.query_graph_by_text("Unknown?")

    assert result["ok"] is True
    assert result["data"]["answer"] is None
    assert result["data"]["warning"] == "No matching graph data found"
    assert "No matching graph data found" in result["warnings"]
    assert "Try mode='vector_only'" in result["next_actions"]
