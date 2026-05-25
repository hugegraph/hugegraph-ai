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
from uuid import uuid4

from hugegraph_mcp.config import MCPConfig
from hugegraph_mcp.envelope import ErrorType, envelope_err, envelope_ok
from hugegraph_mcp.guard import Capability, guard
from hugegraph_mcp.hugegraph_ai_client import post


def validate_graph_payload(
    graph_data: Any,
    live_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
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

    schema_vlabels: set[str] = set()
    schema_props: dict[str, set[str]] = {}
    if live_schema:
        raw = live_schema.get("schema") or live_schema
        for vl in raw.get("vertexlabels", []):
            name = vl.get("name")
            if name:
                schema_vlabels.add(name)
                schema_props[name] = {p.get("name") for p in vl.get("properties", []) if p.get("name")}

    vertex_labels: set[str] = set()
    if isinstance(vertices, list):
        for idx, vertex in enumerate(vertices):
            if not isinstance(vertex, dict):
                errors.append(f"vertex {idx} must be an object")
                continue
            label = vertex.get("label")
            if label in (None, ""):
                errors.append(f"vertex {idx} missing required field: label")
                continue
            vertex_labels.add(label)
            if schema_vlabels and label not in schema_vlabels:
                errors.append(f"vertex {idx} label '{label}' does not exist in schema")

            props = vertex.get("properties")
            if isinstance(props, dict):
                schema_prop_names = schema_props.get(label, set())
                for prop_name, prop_value in props.items():
                    if prop_value is None or prop_value == "":
                        warnings.append(f"vertex {idx} property '{prop_name}' has empty value")
                    if schema_prop_names and prop_name not in schema_prop_names:
                        errors.append(
                            f"vertex {idx} property '{prop_name}' does not exist on label '{label}'"
                        )
            primary_keys = vertex.get("primary_keys")
            if primary_keys is not None and isinstance(props, dict):
                for pk in primary_keys:
                    if pk not in props or props.get(pk) in (None, ""):
                        errors.append(f"vertex {idx} missing primary key value for: {pk}")

    edge_labels: set[str] = set()
    if isinstance(edges, list):
        for idx, edge in enumerate(edges):
            if not isinstance(edge, dict):
                errors.append(f"edge {idx} must be an object")
                continue
            for field in ("label", "source_label", "target_label"):
                if edge.get(field) in (None, ""):
                    errors.append(f"edge {idx} missing required field: {field}")
            label = edge.get("label")
            if label:
                edge_labels.add(label)
            src_label = edge.get("source_label")
            tgt_label = edge.get("target_label")
            if schema_vlabels:
                if src_label and src_label not in schema_vlabels:
                    errors.append(
                        f"edge {idx} source_label '{src_label}' does not exist in schema"
                    )
                if tgt_label and tgt_label not in schema_vlabels:
                    errors.append(
                        f"edge {idx} target_label '{tgt_label}' does not exist in schema"
                    )
            source = edge.get("source")
            target = edge.get("target")
            if source is None and target is None:
                continue
            if source is None:
                errors.append(f"edge {idx} has target but missing source")
            if target is None:
                errors.append(f"edge {idx} has source but missing target")

    if isinstance(vertices, list) and len(vertex_labels) < len(vertices):
        warnings.append("duplicate vertex labels detected")
    if isinstance(edges, list):
        edge_pairs = []
        for e in edges:
            if isinstance(e, dict):
                edge_pairs.append(
                    (e.get("label"), e.get("source_label"), e.get("target_label"),
                     e.get("source"), e.get("target"))
                )
        if len(edge_pairs) > len(set(str(p) for p in edge_pairs)):
            warnings.append("potential duplicate edges detected")

    if vertex_labels or edge_labels:
        warnings.append("verify that appropriate indexes exist for queried properties")

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


def _fetch_live_schema() -> dict[str, Any] | None:
    try:
        from hugegraph_mcp.schema_tools import get_live_schema
        return get_live_schema()
    except Exception:
        return None


def ingest_graph_data(
    graph_data: dict[str, Any],
    dry_run: bool = True,
    confirm: bool = False,
    plan_hash: str | None = None,
) -> dict[str, Any]:
    live_schema = _fetch_live_schema()
    validation = validate_graph_payload(graph_data, live_schema=live_schema)
    if not validation["valid"]:
        error_type = ErrorType.SCHEMA_MISMATCH if live_schema else ErrorType.INVALID_GRAPH_DATA
        return envelope_err(
            error_type,
            "Graph data payload is invalid." if not live_schema else "Graph data does not match live schema.",
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

    batch_id = f"batch-{uuid4().hex[:12]}"
    ai_result = post(
        "/graph-import",
        json={"data": json.dumps(graph_data, sort_keys=True), "schema": None},
    )
    if not ai_result.get("ok"):
        return ai_result

    import_result = _unwrap_ai_payload(ai_result.get("data"))
    if isinstance(import_result, dict) and import_result.get("ok") is False:
        return import_result

    return envelope_ok(
        {
            "batch_id": batch_id,
            "mutation_summary": mutation_summary,
            "import_result": import_result,
        }
    )


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
