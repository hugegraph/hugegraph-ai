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

from typing import Any

from hugegraph_mcp.config import MCPConfig
from hugegraph_mcp.envelope import envelope_err, envelope_ok
from hugegraph_mcp.hugegraph_ai_client import post


_EVIDENCE_LIMIT = 2000
_DEFAULT_GRAPH_RAG_ITEMS = 20
_MODE_ENDPOINTS = {
    "graph_only": "/rag/graph",
    "vector_only": "/rag",
}


def query_graph_by_text(
    query: str,
    mode: str = "graph_only",
    include_evidence: bool = False,
    max_context_items: int = 20,
) -> dict[str, Any]:
    """Query graph knowledge with natural language through HugeGraph-AI RAG APIs."""

    endpoint = _MODE_ENDPOINTS.get(mode)
    if endpoint is None:
        return envelope_err(
            "VALIDATION_ERROR",
            "Invalid query mode",
            suggestion="Use mode='graph_only' or mode='vector_only'.",
            details={"mode": mode, "allowed_modes": sorted(_MODE_ENDPOINTS)},
        )

    cfg = MCPConfig.from_env()
    payload = _build_rag_payload(query, cfg, max_context_items, mode)

    ai_result = post(endpoint, json=payload)
    if not ai_result.get("ok"):
        if not ai_result.get("next_actions"):
            ai_result["next_actions"] = _next_actions(None)
        return ai_result

    ai_data = ai_result.get("data") or {}
    if not isinstance(ai_data, dict):
        ai_data = {}

    # /rag/graph returns {graph_recall: {...}} wrapper
    if mode == "graph_only" and "graph_recall" in ai_data:
        recall = ai_data["graph_recall"]
        if isinstance(recall, dict):
            answer = _format_graph_recall_answer(recall)
            gremlin_val = recall.get("gremlin")
            evidence = recall if include_evidence else None
            data = {
                "answer": answer,
                "evidence": evidence,
                "gremlin": gremlin_val,
                "source_summary": "GraphRAG via graph_only",
                "truncated": False,
                "mode": mode,
            }
        else:
            data = _empty_result(mode)
    else:
        answer = _extract_answer(ai_data, mode)
        evidence_source = _extract_evidence(ai_data) if include_evidence else None
        evidence, truncated = _truncate_evidence(evidence_source)
        data = {
            "answer": answer,
            "evidence": evidence,
            "gremlin": ai_data.get("gremlin"),
            "source_summary": ai_data.get("source_summary") or _source_summary(mode),
            "truncated": truncated,
            "mode": mode,
        }

    warnings = []
    if _is_empty_answer(data.get("answer")):
        data["warning"] = "No matching graph data found"
        warnings.append("No matching graph data found")

    return envelope_ok(
        data,
        warnings=warnings,
        next_actions=_next_actions(data.get("answer")),
        graph=cfg.graph,
        graphspace=cfg.graphspace,
    )


def _build_rag_payload(
    query: str, cfg: MCPConfig, max_context_items: int, mode: str
) -> dict[str, Any]:
    limit = max_context_items or _DEFAULT_GRAPH_RAG_ITEMS
    payload: dict[str, Any] = {
        "query": query,
        "max_graph_items": limit,
        "topk_return_results": limit,
        "vector_dis_threshold": 0.9,
        "topk_per_keyword": 1,
        "gremlin_tmpl_num": -1,
        "rerank_method": "bleu",
        "near_neighbor_first": False,
        "custom_priority_info": "",
        "gremlin_prompt": None,
        "get_vertex_only": False,
        "client_config": {
            "url": cfg.ai_graph_url or cfg.url,
            "graph": cfg.graph,
            "user": cfg.user,
            "pwd": cfg.password,
            "gs": cfg.graphspace,
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


def _truncate_evidence(evidence: Any) -> tuple[Any, bool]:
    if evidence is None:
        return None, False
    if isinstance(evidence, str) and len(evidence) > _EVIDENCE_LIMIT:
        return f"{evidence[:_EVIDENCE_LIMIT]}...", True
    return evidence, False


def _extract_answer(ai_data: dict[str, Any], mode: str) -> Any:
    combined = _combined_answer(ai_data)
    if combined:
        return combined

    if mode == "graph_only":
        keys = ("graph_only", "graph_only_answer", "graph_vector_answer", "raw_answer")
    else:
        keys = ("vector_only", "vector_only_answer", "raw_answer")

    for key in (*keys, "answer"):
        value = ai_data.get(key)
        if not _is_empty_answer(value):
            return value
    return None


def _combined_answer(ai_data: dict[str, Any]) -> str | None:
    sections = [
        ("graph_only", ai_data.get("graph_only_answer") or ai_data.get("graph_only")),
        ("vector_only", ai_data.get("vector_only_answer") or ai_data.get("vector_only")),
        (
            "graph_vector",
            ai_data.get("graph_vector_answer") or ai_data.get("graph_vector"),
        ),
    ]
    present = [
        f"{label}: {value}" for label, value in sections if not _is_empty_answer(value)
    ]
    if len(present) > 1:
        return "\n\n".join(present)
    return None


def _extract_evidence(ai_data: dict[str, Any]) -> Any:
    for key in ("evidence", "context", "references", "source_summary"):
        value = ai_data.get(key)
        if value is not None:
            return value
    return ai_data or None


def _format_graph_recall_answer(recall: dict) -> str | None:
    if recall.get("graph_result"):
        return str(recall["graph_result"])
    if recall.get("keywords"):
        return f"Keywords: {recall['keywords']}"
    return None


def _empty_result(mode: str) -> dict[str, Any]:
    return {
        "answer": None,
        "evidence": None,
        "gremlin": None,
        "source_summary": f"No results from {mode}",
        "truncated": False,
        "mode": mode,
    }


def _source_summary(mode: str) -> str:
    return f"HugeGraph-AI RAG via {mode}"


def _is_empty_answer(answer: Any) -> bool:
    if answer is None:
        return True
    if isinstance(answer, str):
        return answer.strip() == ""
    if isinstance(answer, (list, dict, tuple, set)):
        return len(answer) == 0
    return False


def _next_actions(answer: Any) -> list[str]:
    if not _is_empty_answer(answer):
        return []
    return [
        "Try mode='vector_only'",
        "Use generate_gremlin_tool to produce a precise read-only graph traversal",
        "Use inspect_graph_tool to confirm HugeGraph Server and HugeGraph-AI status",
    ]
