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
    payload = {
        "query": query,
        "graph": cfg.graph,
        "graphspace": cfg.graphspace,
        "max_context_items": max_context_items,
    }

    ai_result = post(endpoint, json=payload)
    if not ai_result.get("ok"):
        return ai_result

    ai_data = ai_result.get("data") or {}
    if not isinstance(ai_data, dict):
        ai_data = {}

    answer = ai_data.get("answer")
    evidence, truncated = _truncate_evidence(
        ai_data.get("evidence") if include_evidence else None
    )
    data: dict[str, Any] = {
        "answer": answer,
        "evidence": evidence,
        "gremlin": ai_data.get("gremlin"),
        "source_summary": ai_data.get("source_summary"),
        "truncated": truncated,
        "mode": mode,
    }

    return envelope_ok(
        data,
        next_actions=_next_actions(answer),
        graph=cfg.graph,
        graphspace=cfg.graphspace,
    )


def _truncate_evidence(evidence: Any) -> tuple[Any, bool]:
    if evidence is None:
        return None, False
    if isinstance(evidence, str) and len(evidence) > _EVIDENCE_LIMIT:
        return f"{evidence[:_EVIDENCE_LIMIT]}...", True
    return evidence, False


def _next_actions(answer: Any) -> list[str]:
    if answer:
        return []
    return [
        "Use query_graph_by_text with mode='vector_only' if graph RAG returned no answer",
        "Use generate_gremlin_tool to produce a precise read-only graph traversal",
        "Use inspect_graph_tool to confirm HugeGraph Server and HugeGraph-AI status",
    ]
