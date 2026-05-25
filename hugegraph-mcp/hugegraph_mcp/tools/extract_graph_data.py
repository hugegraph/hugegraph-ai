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

import json
from typing import Any

from hugegraph_mcp.config import MCPConfig
from hugegraph_mcp.envelope import ErrorType, envelope_err, envelope_ok
from hugegraph_mcp.hugegraph_ai_client import post


def extract_graph_data(
    text: str,
    schema: dict[str, Any] | None = None,
    example_prompt: str | None = None,
) -> dict[str, Any]:
    """Extract candidate graph data from text without writing to HugeGraph."""

    ai_result = post(
        "/graph-extract",
        json={
            "text": text,
            "schema": schema,
            "example_prompt": example_prompt,
            "language": "zh",
        },
    )
    if not ai_result.get("ok"):
        return ai_result

    payload = _unwrap_ai_payload(ai_result.get("data"))
    if isinstance(payload, dict) and payload.get("ok") is False:
        return payload

    graph_data = _extract_graph_data(payload)
    if graph_data is None:
        return envelope_err(
            ErrorType.INVALID_GRAPH_DATA,
            "HugeGraph-AI did not return graph_data with vertices and edges.",
            details={"data": payload},
        )

    cfg = MCPConfig.from_env()
    return envelope_ok({
        "schema_ref": {
            "schema_source": "graph",
            "graph": cfg.graph,
            "graphspace": cfg.graphspace,
            "version": None,
        },
        "vertices": graph_data.get("vertices", []),
        "edges": graph_data.get("edges", []),
        "warnings": graph_data.get("warnings", []),
        "raw": graph_data.get("raw"),
        "raw_summary": graph_data.get("raw_summary"),
        "schema_warnings": graph_data.get("schema_warnings", []),
    })


def _unwrap_ai_payload(data: Any) -> Any:
    if isinstance(data, dict) and "ok" in data and "data" in data:
        if data.get("ok") is False:
            return data
        return data.get("data")
    return data


def _extract_graph_data(data: Any) -> dict[str, Any] | None:
    parsed = _parse_json_if_needed(data)
    if isinstance(parsed, dict) and "graph_data" in parsed:
        parsed = _parse_json_if_needed(parsed.get("graph_data"))

    if not isinstance(parsed, dict):
        return None

    vertices = parsed.get("vertices")
    edges = parsed.get("edges")
    if not isinstance(vertices, list) or not isinstance(edges, list):
        return None

    return {
        "vertices": vertices,
        "edges": edges,
    }


def _parse_json_if_needed(data: Any) -> Any:
    if not isinstance(data, str):
        return data

    try:
        return json.loads(data)
    except json.JSONDecodeError:
        return data
