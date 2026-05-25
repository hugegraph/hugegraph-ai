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

import time
from typing import Any

import requests

from hugegraph_mcp.config import MCPConfig
from hugegraph_mcp.envelope import envelope_ok
from hugegraph_mcp.gremlin_tools import execute_gremlin_read
from hugegraph_mcp.schema_tools import get_live_schema


def _extract_count(result: dict[str, Any]) -> int | None:
    if result.get("ok") is False or result.get("success") is False:
        return None

    data = result.get("data")
    if isinstance(data, list):
        if not data:
            return 0
        first = data[0]
        return first if isinstance(first, int) else None
    if isinstance(data, int):
        return data
    return None


def _count_indexes(raw_schema: dict[str, Any] | None) -> int | None:
    if raw_schema is None:
        return None
    index_labels = raw_schema.get("indexlabels")
    if isinstance(index_labels, list):
        return len(index_labels)
    return 0


def _warning_from_exception(prefix: str, exc: Exception) -> str:
    message = str(exc).strip()
    return f"{prefix}: {message}" if message else prefix


def _check_ai_status(ai_url: str, timeout_seconds: int) -> tuple[str, Any, list[str]]:
    warnings: list[str] = []
    base_url = ai_url.rstrip("/")

    try:
        index_info = requests.get(
            f"{base_url}/graph-index-info", timeout=timeout_seconds
        )
        index_info.raise_for_status()
        try:
            graph_index_info: Any = index_info.json()
        except ValueError:
            graph_index_info = index_info.text
        return "available", graph_index_info, warnings
    except Exception as exc:
        index_warning = _warning_from_exception(
            "HugeGraph-AI graph index info is unavailable", exc
        )

    try:
        openapi = requests.get(f"{base_url}/openapi.json", timeout=timeout_seconds)
        openapi.raise_for_status()
        warnings.append(index_warning)
        return "available", None, warnings
    except Exception as exc:
        warnings.append(index_warning)
        warnings.append(_warning_from_exception("HugeGraph-AI is unavailable", exc))
        return "unavailable", None, warnings


def inspect_graph(include_raw_schema: bool = False) -> dict[str, Any]:
    """Inspect HugeGraph server, schema, counts, and optional HugeGraph-AI status.

    This high-level entry point is intentionally best-effort: connection and
    query failures are reported as warnings in a successful envelope.
    """

    start = time.time()
    cfg = MCPConfig.from_env()
    warnings: list[str] = []

    server_status = "available"
    schema_summary: dict[str, Any] | None = None
    raw_schema: dict[str, Any] | None = None
    readonly: bool | None = None
    vertex_count: int | None = None
    edge_count: int | None = None

    try:
        schema_result = get_live_schema()
        schema_summary = schema_result.get("simple_schema")
        raw_schema = schema_result.get("schema")
        readonly = schema_result.get("readonly")
    except Exception as exc:
        server_status = "unavailable"
        warnings.append(_warning_from_exception("HugeGraph Server is unavailable", exc))

    if server_status == "available":
        vertex_count = _run_count_query("g.V().count()", "vertex", warnings)
        edge_count = _run_count_query("g.E().count()", "edge", warnings)

    ai_status, graph_index_info, ai_warnings = _check_ai_status(
        cfg.ai_url, cfg.timeout_seconds
    )
    warnings.extend(ai_warnings)

    data: dict[str, Any] = {
        "graph": cfg.graph,
        "graphspace": cfg.graphspace,
        "hugegraph_server_status": server_status,
        "hugegraph_ai_status": ai_status,
        "vid_embedding_status": "available" if graph_index_info is not None else "unknown",
        "schema_summary": schema_summary,
        "vertex_count": vertex_count,
        "edge_count": edge_count,
        "index_status": {"total": _count_indexes(raw_schema)},
        "readonly": readonly if readonly is not None else cfg.is_readonly(),
    }
    if include_raw_schema:
        data["raw_schema"] = raw_schema

    duration_ms = (time.time() - start) * 1000.0
    return envelope_ok(
        data,
        duration_ms=duration_ms,
        warnings=warnings,
        next_actions=_next_actions(data),
        readonly=data["readonly"],
    )


def _run_count_query(query: str, label: str, warnings: list[str]) -> int | None:
    try:
        result = execute_gremlin_read(query)
        count = _extract_count(result)
        if count is None:
            warnings.append(f"Failed to fetch {label} count")
        return count
    except Exception as exc:
        warnings.append(_warning_from_exception(f"Failed to fetch {label} count", exc))
        return None


def _next_actions(data: dict[str, Any]) -> list[str]:
    actions = ["Use get_live_schema_tool for full schema details"]
    if data.get("hugegraph_server_status") == "available":
        actions.append("Use execute_gremlin_read_tool for read-only graph exploration")
    else:
        actions.append("Check HugeGraph Server URL, graph name, and credentials")
    if data.get("hugegraph_ai_status") != "available":
        actions.append("Check HugeGraph-AI URL if embedding or graph index features are needed")
    return actions
