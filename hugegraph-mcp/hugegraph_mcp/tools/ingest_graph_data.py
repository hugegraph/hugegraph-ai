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


def _schema_name(item: Any) -> str | None:
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        name = item.get("name")
        return name if isinstance(name, str) else None
    return None


def _property_names(properties: Any) -> set[str]:
    if not isinstance(properties, list):
        return set()
    return {name for prop in properties if (name := _schema_name(prop))}


def _primary_key_names(vertex_label: dict[str, Any]) -> list[str]:
    primary_keys = vertex_label.get("primary_keys")
    if primary_keys is None:
        primary_keys = vertex_label.get("primaryKeys")
    if not isinstance(primary_keys, list):
        return []
    return [name for pk in primary_keys if (name := _schema_name(pk))]


def _schema_payload(live_schema: dict[str, Any] | None) -> dict[str, Any] | None:
    if not live_schema:
        return None
    raw = live_schema.get("schema") or live_schema
    return raw if isinstance(raw, dict) else None


def _property_types(raw_schema: dict[str, Any]) -> dict[str, str]:
    types: dict[str, str] = {}
    for prop in raw_schema.get("propertykeys", []):
        if not isinstance(prop, dict):
            continue
        name = prop.get("name")
        data_type = prop.get("data_type")
        if isinstance(name, str) and isinstance(data_type, str):
            types[name] = data_type.upper()
    return types


def _value_matches_type(value: Any, data_type: str) -> bool:
    if value is None:
        return True
    if data_type in {"TEXT", "UUID"}:
        return isinstance(value, str)
    if data_type in {"INT", "LONG", "BYTE"}:
        return isinstance(value, int) and not isinstance(value, bool)
    if data_type in {"FLOAT", "DOUBLE"}:
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if data_type == "BOOLEAN":
        return isinstance(value, bool)
    if data_type in {"DATE", "BLOB"}:
        return isinstance(value, str)
    return True


def _indexed_labels(raw_schema: dict[str, Any]) -> dict[str, set[str]]:
    indexed = {"VERTEX": set(), "EDGE": set()}
    for index in raw_schema.get("indexlabels", []):
        if not isinstance(index, dict):
            continue
        base_label = index.get("base_label") or index.get("baseLabel")
        if not isinstance(base_label, str):
            continue
        base_type = str(index.get("base_type") or index.get("baseType") or "").upper()
        if base_type in {"VERTEX", "VERTEX_LABEL"}:
            indexed["VERTEX"].add(base_label)
        elif base_type in {"EDGE", "EDGE_LABEL"}:
            indexed["EDGE"].add(base_label)
    return indexed


def _edge_schema_endpoint_label(edge_schema: dict[str, Any], endpoint: str) -> Any:
    if endpoint == "source":
        return edge_schema.get("source_label") or edge_schema.get("sourceLabel")
    return edge_schema.get("target_label") or edge_schema.get("targetLabel")


def _edge_endpoint(edge: dict[str, Any], endpoint: str) -> tuple[Any, Any]:
    if endpoint == "source":
        label = edge.get("source_label") or edge.get("outVLabel")
        value = edge.get("source") if "source" in edge else edge.get("outV")
    else:
        label = edge.get("target_label") or edge.get("inVLabel")
        value = edge.get("target") if "target" in edge else edge.get("inV")
    return label, value


def _identity_value_present(value: Any) -> bool:
    return value is not None and value != ""


def _format_endpoint_value(value: Any) -> str:
    return repr(value)


def _endpoint_identities(
    label: str,
    value: Any,
    schema_primary_keys: dict[str, list[str]],
) -> tuple[list[tuple[str, str, Any]], str | None]:
    identities: list[tuple[str, str, Any]] = []
    primary_keys = schema_primary_keys.get(label, [])

    if isinstance(value, dict):
        explicit_id = value.get("id")
        if _identity_value_present(explicit_id):
            identities.append((label, "id", explicit_id))
        if primary_keys:
            missing = [
                pk for pk in primary_keys
                if pk not in value or not _identity_value_present(value.get(pk))
            ]
            if missing:
                return identities, missing[0]
            identities.append((label, "pk", tuple(value.get(pk) for pk in primary_keys)))
        return identities, None

    if _identity_value_present(value):
        identities.append((label, "id", value))
        if len(primary_keys) == 1:
            pk_value = value
            if isinstance(value, str) and ":" in value:
                pk_value = value.split(":", 1)[1]
            identities.append((label, "pk", (pk_value,)))
    return identities, None


def _schema_plan_summary(live_schema: dict[str, Any] | None) -> dict[str, Any] | None:
    raw = _schema_payload(live_schema)
    if raw is None:
        return None
    simple = live_schema.get("simple_schema") if isinstance(live_schema, dict) else None
    if isinstance(simple, dict):
        return simple
    return {
        "vertexlabels": raw.get("vertexlabels", []),
        "edgelabels": raw.get("edgelabels", []),
        "propertykeys": raw.get("propertykeys", []),
    }


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
    schema_primary_keys: dict[str, list[str]] = {}
    schema_property_types: dict[str, str] = {}
    schema_elabels: dict[str, dict[str, Any]] = {}
    schema_eprops: dict[str, set[str]] = {}
    indexed_labels = {"VERTEX": set(), "EDGE": set()}
    if live_schema:
        raw = _schema_payload(live_schema) or {}
        schema_property_types = _property_types(raw)
        for vl in raw.get("vertexlabels", []):
            if not isinstance(vl, dict):
                continue
            name = vl.get("name")
            if name:
                schema_vlabels.add(name)
                schema_props[name] = _property_names(vl.get("properties", []))
                schema_primary_keys[name] = _primary_key_names(vl)
        for el in raw.get("edgelabels", []):
            if not isinstance(el, dict):
                continue
            name = el.get("name")
            if isinstance(name, str):
                schema_elabels[name] = el
                schema_eprops[name] = _property_names(el.get("properties", []))
        indexed_labels = _indexed_labels(raw)

    vertex_labels: set[str] = set()
    vertex_identity_index: dict[tuple[str, str, Any], int] = {}
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
                    data_type = schema_property_types.get(prop_name)
                    if data_type and not _value_matches_type(prop_value, data_type):
                        errors.append(
                            f"vertex {idx} property '{prop_name}' expects {data_type}, got {type(prop_value).__name__}"
                        )
            primary_keys = schema_primary_keys.get(label, [])
            if primary_keys:
                if not isinstance(props, dict):
                    props = {}
                for pk in primary_keys:
                    if pk not in props or not _identity_value_present(props.get(pk)):
                        errors.append(
                            f"vertex {idx} missing primary key value for label '{label}': {pk}"
                        )
                if all(pk in props and _identity_value_present(props.get(pk)) for pk in primary_keys):
                    identity = (label, "pk", tuple(props.get(pk) for pk in primary_keys))
                    if identity in vertex_identity_index:
                        warnings.append("duplicate vertex identity")
                    else:
                        vertex_identity_index[identity] = idx
            explicit_id = vertex.get("id")
            if _identity_value_present(explicit_id):
                identity = (label, "id", explicit_id)
                if identity in vertex_identity_index:
                    warnings.append("duplicate vertex identity")
                else:
                    vertex_identity_index[identity] = idx

    edge_labels: set[str] = set()
    if isinstance(edges, list):
        for idx, edge in enumerate(edges):
            if not isinstance(edge, dict):
                errors.append(f"edge {idx} must be an object")
                continue
            label = edge.get("label")
            src_label, source = _edge_endpoint(edge, "source")
            tgt_label, target = _edge_endpoint(edge, "target")
            if label in (None, ""):
                errors.append(f"edge {idx} missing required field: label")
            if src_label in (None, ""):
                errors.append(f"edge {idx} missing required field: source_label")
            if tgt_label in (None, ""):
                errors.append(f"edge {idx} missing required field: target_label")
            if label:
                edge_labels.add(label)
                if schema_elabels and label not in schema_elabels:
                    errors.append(f"edge {idx} label '{label}' does not exist in schema")
            if schema_vlabels:
                if src_label and src_label not in schema_vlabels:
                    errors.append(
                        f"edge {idx} source_label '{src_label}' does not exist in schema"
                    )
                if tgt_label and tgt_label not in schema_vlabels:
                    errors.append(
                        f"edge {idx} target_label '{tgt_label}' does not exist in schema"
                    )
            if label and label in schema_elabels:
                schema_edge = schema_elabels[label]
                expected_src = _edge_schema_endpoint_label(schema_edge, "source")
                expected_tgt = _edge_schema_endpoint_label(schema_edge, "target")
                if src_label and expected_src and src_label != expected_src:
                    errors.append(
                        f"edge {idx} source_label '{src_label}' does not match edge label '{label}' source_label '{expected_src}'"
                    )
                if tgt_label and expected_tgt and tgt_label != expected_tgt:
                    errors.append(
                        f"edge {idx} target_label '{tgt_label}' does not match edge label '{label}' target_label '{expected_tgt}'"
                    )
            props = edge.get("properties")
            if isinstance(props, dict):
                schema_prop_names = schema_eprops.get(label, set())
                for prop_name, prop_value in props.items():
                    if prop_value is None or prop_value == "":
                        warnings.append(f"edge {idx} property '{prop_name}' has empty value")
                    if schema_prop_names and prop_name not in schema_prop_names:
                        errors.append(
                            f"edge {idx} property '{prop_name}' does not exist on label '{label}'"
                        )
                    data_type = schema_property_types.get(prop_name)
                    if data_type and not _value_matches_type(prop_value, data_type):
                        errors.append(
                            f"edge {idx} property '{prop_name}' expects {data_type}, got {type(prop_value).__name__}"
                        )
            if source is None and target is None:
                continue
            if source is None:
                errors.append(f"edge {idx} has target but missing source")
            if target is None:
                errors.append(f"edge {idx} has source but missing target")
            for endpoint_name, endpoint_label, endpoint_value in (
                ("source", src_label, source),
                ("target", tgt_label, target),
            ):
                if endpoint_value is None or not isinstance(endpoint_label, str):
                    continue
                identities, missing_pk = _endpoint_identities(
                    endpoint_label,
                    endpoint_value,
                    schema_primary_keys,
                )
                if missing_pk:
                    errors.append(
                        f"edge {idx} {endpoint_name} endpoint missing primary key for label '{endpoint_label}': {missing_pk}"
                    )
                    continue
                if identities and not any(identity in vertex_identity_index for identity in identities):
                    errors.append(
                        f"edge {idx} {endpoint_name} endpoint not found for label '{endpoint_label}': {_format_endpoint_value(endpoint_value)}"
                    )

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

    if indexed_labels["VERTEX"] or indexed_labels["EDGE"]:
        for label in sorted(vertex_labels - indexed_labels["VERTEX"]):
            warnings.append(f"no vertex index found in schema for label: {label}")
        for label in sorted(edge_labels - indexed_labels["EDGE"]):
            warnings.append(f"no edge index found in schema for label: {label}")
    elif vertex_labels or edge_labels:
        warnings.append("verify that appropriate indexes exist for queried properties")

    return {
        "valid": not bool(errors),
        "errors": errors,
        "warnings": warnings,
    }


def calculate_plan_hash(
    graph_data: dict[str, Any],
    live_schema: dict[str, Any] | None = None,
) -> str:
    cfg = MCPConfig.from_env()
    payload = {
        "graph_data": graph_data,
        "graph": cfg.graph,
        "graphspace": cfg.graphspace,
    }
    schema_summary = _schema_plan_summary(live_schema)
    if schema_summary is not None:
        payload["schema_summary"] = schema_summary
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
    if live_schema is None:
        return envelope_err(
            ErrorType.CONNECTION_FAILED,
            "Cannot read live schema from HugeGraph Server. Schema validation is required before import.",
            suggestion="Ensure HugeGraph Server is running and accessible, then retry.",
            retryable=True,
        )
    validation = validate_graph_payload(graph_data, live_schema=live_schema)
    if not validation["valid"]:
        return envelope_err(
            ErrorType.SCHEMA_MISMATCH,
            "Graph data does not match live schema.",
            details={"errors": validation["errors"]},
        )

    expected_plan_hash = calculate_plan_hash(graph_data, live_schema=live_schema)
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
