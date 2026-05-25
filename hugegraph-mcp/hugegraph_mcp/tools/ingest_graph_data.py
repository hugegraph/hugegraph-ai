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

import hashlib
import json
from typing import Any

from hugegraph_mcp.config import MCPConfig
from hugegraph_mcp.envelope import ErrorType, envelope_err, envelope_ok
from hugegraph_mcp.guard import Capability, guard
from hugegraph_mcp.hugegraph_ai_client import post


def validate_graph_payload(graph_data: Any) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []

    if not isinstance(graph_data, dict):
        return {
            "valid": False,
            "errors": ["graph_data must be an object"],
            "warnings": warnings,
        }

    vertices = graph_data.get("vertices")
    edges = graph_data.get("edges")

    if not isinstance(vertices, list):
        errors.append("vertices must be a list")
    if not isinstance(edges, list):
        errors.append("edges must be a list")

    if isinstance(vertices, list):
        for idx, vertex in enumerate(vertices):
            if not isinstance(vertex, dict):
                errors.append(f"vertex {idx} must be an object")
                continue
            if vertex.get("label") in (None, ""):
                errors.append(f"vertex {idx} missing required field: label")

    if isinstance(edges, list):
        for idx, edge in enumerate(edges):
            if not isinstance(edge, dict):
                errors.append(f"edge {idx} must be an object")
                continue
            for field in ("label", "source_label", "target_label"):
                if edge.get(field) in (None, ""):
                    errors.append(f"edge {idx} missing required field: {field}")

    return {
        "valid": not bool(errors),
        "errors": errors,
        "warnings": warnings,
    }


def calculate_plan_hash(graph_data: dict[str, Any]) -> str:
    cfg = MCPConfig.from_env()
    payload = {
        "graph_data": graph_data,
        "graph": cfg.graph,
        "graphspace": cfg.graphspace,
    }
    encoded = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


def ingest_graph_data(
    graph_data: dict[str, Any],
    dry_run: bool = True,
    confirm: bool = False,
    plan_hash: str | None = None,
) -> dict[str, Any]:
    validation = validate_graph_payload(graph_data)
    if not validation["valid"]:
        return envelope_err(
            ErrorType.INVALID_GRAPH_DATA,
            "Graph data payload is invalid.",
            details={"errors": validation["errors"]},
        )

    expected_plan_hash = calculate_plan_hash(graph_data)
    mutation_summary = _mutation_summary(graph_data)
    warnings = validation["warnings"]

    if dry_run:
        return envelope_ok(
            {
                "plan_hash": expected_plan_hash,
                "mutation_summary": mutation_summary,
                "warnings": warnings,
            },
            warnings=warnings,
        )

    violation = guard(Capability.DATA_WRITE)
    if violation is not None:
        return violation

    if not confirm:
        return envelope_err(
            ErrorType.CONFIRM_REQUIRED,
            "Graph data import requires confirm=True after a dry_run.",
            suggestion="Run dry_run=True, review mutation_summary and warnings, then pass confirm=True with the returned plan_hash.",
        )

    if plan_hash != expected_plan_hash:
        return envelope_err(
            ErrorType.PLAN_HASH_MISMATCH,
            "Provided plan_hash does not match the current graph data plan.",
            suggestion="Run dry_run=True again and use the returned plan_hash.",
            details={
                "expected_plan_hash": expected_plan_hash,
                "provided_plan_hash": plan_hash,
            },
        )

    ai_result = post(
        "/graph-import",
        json={"data": json.dumps(graph_data, sort_keys=True), "schema": None},
    )
    if not ai_result.get("ok"):
        return ai_result

    data = _unwrap_ai_payload(ai_result.get("data"))
    if isinstance(data, dict) and data.get("ok") is False:
        return data

    return envelope_ok(data)


def _mutation_summary(graph_data: dict[str, Any]) -> dict[str, int]:
    return {
        "vertices": len(graph_data.get("vertices") or []),
        "edges": len(graph_data.get("edges") or []),
    }


def _unwrap_ai_payload(data: Any) -> Any:
    if isinstance(data, dict) and "ok" in data and "data" in data:
        if data.get("ok") is False:
            return data
        return data.get("data")
    return data
