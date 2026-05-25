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

from hugegraph_mcp import gremlin_tools, schema_tools
from hugegraph_mcp.config import MCPConfig
from hugegraph_mcp.envelope import ErrorType, envelope_err, envelope_ok
from hugegraph_mcp.guard import Capability, guard
from hugegraph_mcp.tools import ingest_graph_data


ALLOWED_OPS = frozenset(
    {
        "create_vertex",
        "create_edge",
        "update_vertex",
        "update_edge",
        "delete_vertex",
        "delete_edge",
    }
)

VERTEX_OPS = frozenset({"create_vertex", "update_vertex", "delete_vertex"})
EDGE_OPS = frozenset({"create_edge", "update_edge", "delete_edge"})
WRITE_OPS = frozenset({"update_vertex", "update_edge", "delete_vertex", "delete_edge"})
MODE_OPS = {
    "import": frozenset({"create_vertex", "create_edge"}),
    "update": frozenset({"update_vertex", "update_edge"}),
    "delete": frozenset({"delete_vertex", "delete_edge"}),
}

GraphChangePlan = dict[str, list[dict[str, Any]]]
ValidationError = dict[str, Any]


def _schema_payload(live_schema: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(live_schema, dict):
        return {}
    raw = live_schema.get("schema") or live_schema
    return raw if isinstance(raw, dict) else {}


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


def _vertex_labels(raw_schema: dict[str, Any]) -> dict[str, dict[str, Any]]:
    labels: dict[str, dict[str, Any]] = {}
    for label in raw_schema.get("vertexlabels", []):
        if not isinstance(label, dict):
            continue
        name = label.get("name")
        if isinstance(name, str):
            labels[name] = label
    return labels


def _edge_labels(raw_schema: dict[str, Any]) -> dict[str, dict[str, Any]]:
    labels: dict[str, dict[str, Any]] = {}
    for label in raw_schema.get("edgelabels", []):
        if not isinstance(label, dict):
            continue
        name = label.get("name")
        if isinstance(name, str):
            labels[name] = label
    return labels


def _edge_schema_endpoint_label(edge_schema: dict[str, Any], endpoint: str) -> Any:
    if endpoint == "source":
        return edge_schema.get("source_label") or edge_schema.get("sourceLabel")
    return edge_schema.get("target_label") or edge_schema.get("targetLabel")


def _schema_summary(live_schema: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(live_schema, dict):
        return None
    simple = live_schema.get("simple_schema")
    if isinstance(simple, dict) and simple:
        return simple
    raw = _schema_payload(live_schema)
    if not raw:
        return None
    return {
        "vertexlabels": raw.get("vertexlabels", []),
        "edgelabels": raw.get("edgelabels", []),
        "propertykeys": raw.get("propertykeys", []),
    }


def _operations(change_plan: Any) -> list[dict[str, Any]]:
    if isinstance(change_plan, list):
        return change_plan
    if not isinstance(change_plan, dict):
        return []
    operations = change_plan.get("operations")
    return operations if isinstance(operations, list) else []


def _change_plan_from_operations(operations: list[dict[str, Any]]) -> GraphChangePlan:
    return {"operations": operations}


def _validation_error(
    operation_index: int,
    operation: Any,
    reason: str,
    suggestion: str,
    error_type: str | None = None,
) -> ValidationError:
    error = {
        "operation_index": operation_index,
        "operation": operation,
        "reason": reason,
        "suggestion": suggestion,
    }
    if error_type is not None:
        error["error_type"] = error_type
    return error


def _validate_field_map(
    *,
    idx: int,
    operation: dict[str, Any],
    field: str,
    allowed_properties: set[str],
    errors: list[ValidationError],
) -> None:
    values = operation.get(field)
    if values is None:
        return
    if not isinstance(values, dict):
        errors.append(
            _validation_error(
                idx,
                operation,
                f"{field} must be an object",
                f"Use an object mapping property names to values for {field}.",
            )
        )
        return
    unknown = sorted(set(values) - allowed_properties)
    if unknown:
        errors.append(
            _validation_error(
                idx,
                operation,
                f"{field} references property not on label: {', '.join(unknown)}",
                "Use only properties defined on the referenced label.",
            )
        )


def _validate_primary_key_match(
    *,
    idx: int,
    operation: dict[str, Any],
    field: str,
    primary_keys: list[str],
    errors: list[ValidationError],
) -> None:
    match = operation.get(field)
    if not isinstance(match, dict):
        errors.append(
            _validation_error(
                idx,
                operation,
                f"{field} must be an object",
                f"Use {field} to identify a vertex by its primary key.",
            )
        )
        return
    missing = [
        pk for pk in primary_keys if pk not in match or match.get(pk) in (None, "")
    ]
    if missing:
        errors.append(
            _validation_error(
                idx,
                operation,
                f"{field} must contain primary key(s): {', '.join(missing)}",
                "Include every primary key from the referenced vertex label.",
            )
        )


def validate_graph_change_plan(
    change_plan: Any,
    live_schema: dict[str, Any],
) -> dict[str, Any]:
    errors: list[ValidationError] = []
    warnings: list[str] = []

    if not isinstance(change_plan, (dict, list)):
        return {
            "valid": False,
            "errors": [
                _validation_error(
                    -1,
                    change_plan,
                    "change_plan must be an object with operations",
                    "Pass {'operations': [...]} as the graph change plan.",
                )
            ],
            "warnings": [],
        }

    if isinstance(change_plan, dict) and not isinstance(
        change_plan.get("operations"), list
    ):
        return {
            "valid": False,
            "errors": [
                _validation_error(
                    -1,
                    change_plan,
                    "change_plan.operations must be a list",
                    "Pass graph change operations as a JSON array.",
                )
            ],
            "warnings": [],
        }

    operations = _operations(change_plan)
    raw_schema = _schema_payload(live_schema)
    vertex_labels = _vertex_labels(raw_schema)
    edge_labels = _edge_labels(raw_schema)
    vertex_properties = {
        label: _property_names(schema.get("properties"))
        for label, schema in vertex_labels.items()
    }
    edge_properties = {
        label: _property_names(schema.get("properties"))
        for label, schema in edge_labels.items()
    }
    primary_keys = {
        label: _primary_key_names(schema) for label, schema in vertex_labels.items()
    }

    for idx, operation in enumerate(operations):
        if not isinstance(operation, dict):
            errors.append(
                _validation_error(
                    idx,
                    operation,
                    "operation must be an object",
                    "Replace this item with a graph change operation object.",
                )
            )
            continue

        op = str(operation.get("op") or operation.get("type") or "")
        if op not in ALLOWED_OPS:
            errors.append(
                _validation_error(
                    idx,
                    operation,
                    f"unsupported op: {op}",
                    "Use one of: create_vertex, create_edge, update_vertex, update_edge, delete_vertex, delete_edge.",
                )
            )
            continue

        label = operation.get("label")
        if not isinstance(label, str) or not label:
            errors.append(
                _validation_error(
                    idx,
                    operation,
                    "missing required field: label",
                    "Add the schema label targeted by this operation.",
                )
            )
            continue

        if op in VERTEX_OPS:
            if label not in vertex_labels:
                errors.append(
                    _validation_error(
                        idx,
                        operation,
                        f"label references undefined vertex label: {label}",
                        "Use an existing vertex label from the live schema.",
                    )
                )
                continue
            allowed = vertex_properties.get(label, set())
            pks = primary_keys.get(label, [])
            if not pks:
                warnings.append(
                    f"operation {idx} references vertex label '{label}' with no primary_keys"
                )
            _validate_field_map(
                idx=idx,
                operation=operation,
                field="properties",
                allowed_properties=allowed,
                errors=errors,
            )
            _validate_field_map(
                idx=idx,
                operation=operation,
                field="match",
                allowed_properties=allowed,
                errors=errors,
            )
            _validate_field_map(
                idx=idx,
                operation=operation,
                field="set",
                allowed_properties=allowed,
                errors=errors,
            )
            if op == "update_vertex":
                set_values = operation.get("set")
                if not isinstance(set_values, dict) or not set_values:
                    errors.append(
                        _validation_error(
                            idx,
                            operation,
                            "update_vertex set must be a non-empty object",
                            "Provide at least one non-primary-key property to update.",
                        )
                    )
                elif any(pk in set_values for pk in pks):
                    errors.append(
                        _validation_error(
                            idx,
                            operation,
                            "update_vertex set must not include primary key properties",
                            "Primary key values identify the vertex and cannot be updated.",
                        )
                    )
                _validate_primary_key_match(
                    idx=idx,
                    operation=operation,
                    field="match",
                    primary_keys=pks,
                    errors=errors,
                )
            elif op == "delete_vertex":
                _validate_primary_key_match(
                    idx=idx,
                    operation=operation,
                    field="match",
                    primary_keys=pks,
                    errors=errors,
                )
        else:
            if label not in edge_labels:
                errors.append(
                    _validation_error(
                        idx,
                        operation,
                        f"label references undefined edge label: {label}",
                        "Use an existing edge label from the live schema.",
                    )
                )
                continue
            edge_schema = edge_labels[label]
            source_label = operation.get("source_label") or operation.get("outVLabel")
            target_label = operation.get("target_label") or operation.get("inVLabel")
            for endpoint_name, endpoint_label in (
                ("source_label", source_label),
                ("target_label", target_label),
            ):
                if (
                    not isinstance(endpoint_label, str)
                    or endpoint_label not in vertex_labels
                ):
                    errors.append(
                        _validation_error(
                            idx,
                            operation,
                            f"{endpoint_name} references undefined vertex label: {endpoint_label}",
                            "Use existing source and target vertex labels from the live schema.",
                        )
                    )
            expected_source = _edge_schema_endpoint_label(edge_schema, "source")
            expected_target = _edge_schema_endpoint_label(edge_schema, "target")
            if expected_source and source_label and source_label != expected_source:
                errors.append(
                    _validation_error(
                        idx,
                        operation,
                        f"source_label does not match edge label '{label}' source_label '{expected_source}'",
                        "Use the source label defined by the edge schema.",
                    )
                )
            if expected_target and target_label and target_label != expected_target:
                errors.append(
                    _validation_error(
                        idx,
                        operation,
                        f"target_label does not match edge label '{label}' target_label '{expected_target}'",
                        "Use the target label defined by the edge schema.",
                    )
                )
            allowed = edge_properties.get(label, set())
            _validate_field_map(
                idx=idx,
                operation=operation,
                field="properties",
                allowed_properties=allowed,
                errors=errors,
            )
            _validate_field_map(
                idx=idx,
                operation=operation,
                field="set",
                allowed_properties=allowed,
                errors=errors,
            )
            if op == "update_edge":
                set_values = operation.get("set")
                if not isinstance(set_values, dict) or not set_values:
                    errors.append(
                        _validation_error(
                            idx,
                            operation,
                            "update_edge set must be a non-empty object",
                            "Provide at least one edge property to update.",
                        )
                    )
                elif any(
                    endpoint in set_values
                    for endpoint in (
                        "source",
                        "target",
                        "source_label",
                        "target_label",
                        "source_match",
                        "target_match",
                        "outV",
                        "inV",
                        "outVLabel",
                        "inVLabel",
                    )
                ):
                    errors.append(
                        _validation_error(
                            idx,
                            operation,
                            "update_edge set must not include source/target endpoint fields",
                            "Endpoints identify the edge and cannot be updated.",
                        )
                    )
            if isinstance(source_label, str) and source_label in vertex_labels:
                _validate_primary_key_match(
                    idx=idx,
                    operation=operation,
                    field="source_match",
                    primary_keys=primary_keys.get(source_label, []),
                    errors=errors,
                )
                _validate_field_map(
                    idx=idx,
                    operation=operation,
                    field="source_match",
                    allowed_properties=vertex_properties.get(source_label, set()),
                    errors=errors,
                )
            if isinstance(target_label, str) and target_label in vertex_labels:
                _validate_primary_key_match(
                    idx=idx,
                    operation=operation,
                    field="target_match",
                    primary_keys=primary_keys.get(target_label, []),
                    errors=errors,
                )
                _validate_field_map(
                    idx=idx,
                    operation=operation,
                    field="target_match",
                    allowed_properties=vertex_properties.get(target_label, set()),
                    errors=errors,
                )

    return {"valid": not bool(errors), "errors": errors, "warnings": warnings}


def _g(value: Any) -> str:
    return json.dumps(value, sort_keys=True)


def _has_steps(match: dict[str, Any]) -> str:
    return "".join(f".has({_g(key)},{_g(value)})" for key, value in match.items())


def _vertex_match_query(operation: dict[str, Any]) -> str:
    return f"g.V().hasLabel({_g(operation['label'])}){_has_steps(operation['match'])}"


def _edge_match_query(operation: dict[str, Any]) -> str:
    source_label = operation.get("source_label") or operation.get("outVLabel")
    target_label = operation.get("target_label") or operation.get("inVLabel")
    return (
        f"g.V().hasLabel({_g(source_label)}){_has_steps(operation['source_match'])}"
        f".outE({_g(operation['label'])})"
        f".where(inV().hasLabel({_g(target_label)}){_has_steps(operation['target_match'])})"
    )


def _source_vertex_match_query(operation: dict[str, Any]) -> str:
    source_label = operation.get("source_label") or operation.get("outVLabel")
    return f"g.V().hasLabel({_g(source_label)}){_has_steps(operation['source_match'])}"


def _target_vertex_match_query(operation: dict[str, Any]) -> str:
    target_label = operation.get("target_label") or operation.get("inVLabel")
    return f"g.V().hasLabel({_g(target_label)}){_has_steps(operation['target_match'])}"


def _read_count(gremlin_query: str) -> dict[str, Any]:
    result = gremlin_tools.execute_gremlin_read(f"{gremlin_query}.count()")
    if isinstance(result, dict) and result.get("ok") is False:
        return result
    if isinstance(result, dict) and result.get("success") is False:
        return envelope_err(
            ErrorType.CONNECTION_FAILED,
            "HugeGraph read query failed during graph change dry run.",
            details=result,
            retryable=True,
        )
    data = result.get("data") if isinstance(result, dict) else result
    if isinstance(data, list):
        count = data[0] if data else 0
    else:
        count = data
    try:
        matched_count = int(count)
    except (TypeError, ValueError):
        return envelope_err(
            ErrorType.INVALID_GRAPH_DATA,
            "HugeGraph count query returned a non-numeric result.",
            details={"query": gremlin_query, "data": data},
        )
    return envelope_ok({"matched_count": matched_count})


def _read_values(gremlin_query: str) -> dict[str, Any]:
    result = gremlin_tools.execute_gremlin_read(gremlin_query)
    if isinstance(result, dict) and result.get("ok") is False:
        return result
    if isinstance(result, dict) and result.get("success") is False:
        return envelope_err(
            ErrorType.CONNECTION_FAILED,
            "HugeGraph read query failed during graph change dry run.",
            details=result,
            retryable=True,
        )
    data = result.get("data") if isinstance(result, dict) else result
    return envelope_ok({"values": data if isinstance(data, list) else [data]})


def _mutation_summary(operations: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for operation in operations:
        op = str(operation.get("op") or operation.get("type") or "unknown")
        counts[op] = counts.get(op, 0) + 1
    return counts


def calculate_graph_change_plan_hash(
    change_plan: Any,
    graph: str | None = None,
    graphspace: str | None = None,
    schema_summary: dict[str, Any] | None = None,
) -> str:
    cfg = MCPConfig.from_env()
    payload = {
        "change_plan": change_plan,
        "graph": cfg.graph if graph is None else graph,
        "graphspace": cfg.graphspace if graphspace is None else graphspace,
    }
    if schema_summary is not None:
        payload["schema_summary"] = schema_summary
    encoded = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


def dry_run_graph_change_plan(
    change_plan: Any,
    live_schema: dict[str, Any],
) -> dict[str, Any]:
    validation = validate_graph_change_plan(change_plan, live_schema)
    if not validation["valid"]:
        return validation

    operations = _operations(change_plan)
    preview: list[dict[str, Any]] = []
    errors: list[ValidationError] = []

    for idx, operation in enumerate(operations):
        op = str(operation.get("op") or operation.get("type"))
        item = {
            "operation_index": idx,
            "op": op,
            "label": operation.get("label"),
            "action": op,
        }
        if op not in WRITE_OPS:
            item["matched_count"] = None
            preview.append(item)
            continue

        if op in {"update_edge", "delete_edge"}:
            endpoint_failed = False
            for endpoint, endpoint_query in (
                ("source", _source_vertex_match_query(operation)),
                ("target", _target_vertex_match_query(operation)),
            ):
                endpoint_count_result = _read_count(endpoint_query)
                if not endpoint_count_result.get("ok"):
                    errors.append(
                        _validation_error(
                            idx,
                            operation,
                            f"{endpoint} endpoint count query failed",
                            "Verify HugeGraph Server is available and retry the dry run.",
                        )
                    )
                    endpoint_failed = True
                    continue
                endpoint_count = endpoint_count_result["data"]["matched_count"]
                item[f"{endpoint}_matched_count"] = endpoint_count
                if endpoint_count != 1:
                    errors.append(
                        _validation_error(
                            idx,
                            operation,
                            f"{op} {endpoint} endpoint matched_count must be 1, got {endpoint_count}",
                            "Narrow the endpoint match criteria so exactly one vertex is selected.",
                        )
                    )
                    endpoint_failed = True
            if endpoint_failed:
                preview.append(item)
                continue

        match_query = (
            _edge_match_query(operation)
            if op in {"update_edge", "delete_edge"}
            else _vertex_match_query(operation)
        )
        count_result = _read_count(match_query)
        if not count_result.get("ok"):
            errors.append(
                _validation_error(
                    idx,
                    operation,
                    "matched_count query failed",
                    "Verify HugeGraph Server is available and retry the dry run.",
                )
            )
            continue
        matched_count = count_result["data"]["matched_count"]
        item["matched_count"] = matched_count

        if (
            op in {"update_vertex", "update_edge", "delete_vertex", "delete_edge"}
            and matched_count != 1
        ):
            errors.append(
                _validation_error(
                    idx,
                    operation,
                    f"{op} matched_count must be 1, got {matched_count}",
                    "Narrow the match criteria so exactly one graph element is affected.",
                )
            )

        if (
            op == "delete_vertex"
            and operation.get("cascade", False) is False
            and matched_count == 1
        ):
            edge_count_result = _read_count(f"{match_query}.bothE()")
            if not edge_count_result.get("ok"):
                errors.append(
                    _validation_error(
                        idx,
                        operation,
                        "associated edge count query failed",
                        "Verify HugeGraph Server is available and retry the dry run.",
                    )
                )
            else:
                edge_count = edge_count_result["data"]["matched_count"]
                item["associated_edge_count"] = edge_count
                if edge_count > 0:
                    errors.append(
                        _validation_error(
                            idx,
                            operation,
                            "delete_vertex cascade=false but vertex has associated edges",
                            "Set cascade=true or delete associated edges first.",
                            "BLOCKED_BY_RELATIONSHIPS",
                        )
                    )
        elif op == "delete_vertex" and operation.get("cascade", False) is True:
            edge_result = _read_values(f"{match_query}.bothE().elementMap()")
            if not edge_result.get("ok"):
                errors.append(
                    _validation_error(
                        idx,
                        operation,
                        "associated edge preview query failed",
                        "Verify HugeGraph Server is available and retry the dry run.",
                    )
                )
            else:
                item["associated_edges"] = edge_result["data"]["values"]
                errors.append(
                    _validation_error(
                        idx,
                        operation,
                        "delete_vertex cascade=true is not enabled in this phase",
                        "Delete associated edges explicitly, then delete the vertex with cascade=false.",
                        "CASCADE_NOT_ENABLED",
                    )
                )
        preview.append(item)

    if errors:
        return {
            "valid": False,
            "errors": errors,
            "warnings": validation.get("warnings", []),
            "preview": preview,
        }

    return {
        "valid": True,
        "plan_hash": calculate_graph_change_plan_hash(
            change_plan,
            schema_summary=_schema_summary(live_schema),
        ),
        "mutation_summary": _mutation_summary(operations),
        "preview": preview,
        "warnings": validation.get("warnings", []),
    }


def _create_vertex_query(operation: dict[str, Any]) -> str:
    query = f"g.addV({_g(operation['label'])})"
    for prop, value in (operation.get("properties") or {}).items():
        query += f".property({_g(prop)},{_g(value)})"
    return query


def _create_edge_query(operation: dict[str, Any]) -> str:
    source_label = operation.get("source_label") or operation.get("outVLabel")
    target_label = operation.get("target_label") or operation.get("inVLabel")
    query = (
        f"g.V().hasLabel({_g(source_label)}){_has_steps(operation['source_match'])}.as('s')"
        f".V().hasLabel({_g(target_label)}){_has_steps(operation['target_match'])}"
        f".addE({_g(operation['label'])}).from('s')"
    )
    for prop, value in (operation.get("properties") or {}).items():
        query += f".property({_g(prop)},{_g(value)})"
    return query


def _update_vertex_query(operation: dict[str, Any]) -> str:
    query = _vertex_match_query(operation)
    for prop, value in operation["set"].items():
        query += f".property({_g(prop)},{_g(value)})"
    return query


def _update_edge_query(operation: dict[str, Any]) -> str:
    query = _edge_match_query(operation)
    for prop, value in operation["set"].items():
        query += f".property({_g(prop)},{_g(value)})"
    return query


def _delete_vertex_query(operation: dict[str, Any]) -> str:
    return f"{_vertex_match_query(operation)}.drop()"


def _delete_edge_query(operation: dict[str, Any]) -> str:
    return f"{_edge_match_query(operation)}.drop()"


def _write_query(operation: dict[str, Any]) -> str:
    op = str(operation.get("op") or operation.get("type"))
    if op == "create_vertex":
        return _create_vertex_query(operation)
    if op == "create_edge":
        return _create_edge_query(operation)
    if op == "update_vertex":
        return _update_vertex_query(operation)
    if op == "update_edge":
        return _update_edge_query(operation)
    if op == "delete_vertex":
        return _delete_vertex_query(operation)
    if op == "delete_edge":
        return _delete_edge_query(operation)
    raise ValueError(f"Unsupported op: {op}")


def _validate_mode_operations(
    mode: str, change_plan: GraphChangePlan
) -> dict[str, Any]:
    allowed = MODE_OPS[mode]
    errors = []
    for idx, operation in enumerate(_operations(change_plan)):
        op = str(operation.get("op") or operation.get("type"))
        if op not in allowed:
            errors.append(
                _validation_error(
                    idx,
                    operation,
                    f"op {op} is not allowed in mode='{mode}'",
                    f"Use only {', '.join(sorted(allowed))} operations for mode='{mode}'.",
                )
            )
    return {"valid": not bool(errors), "errors": errors, "warnings": []}


def execute_graph_change_plan(change_plan: Any) -> dict[str, Any]:
    operations = _operations(change_plan)
    results: list[dict[str, Any]] = []
    for idx, operation in enumerate(operations):
        op = str(operation.get("op") or operation.get("type"))
        if op in WRITE_OPS:
            if op in {"update_edge", "delete_edge"}:
                for endpoint, endpoint_query in (
                    ("source", _source_vertex_match_query(operation)),
                    ("target", _target_vertex_match_query(operation)),
                ):
                    endpoint_count_result = _read_count(endpoint_query)
                    if not endpoint_count_result.get("ok"):
                        return endpoint_count_result
                    endpoint_count = endpoint_count_result["data"]["matched_count"]
                    if endpoint_count != 1:
                        return envelope_err(
                            ErrorType.INVALID_GRAPH_DATA,
                            f"{op} {endpoint} endpoint matched_count must be 1 before execution.",
                            details={
                                "operation_index": idx,
                                "matched_count": endpoint_count,
                            },
                        )
            match_query = (
                _edge_match_query(operation)
                if op in {"update_edge", "delete_edge"}
                else _vertex_match_query(operation)
            )
            count_result = _read_count(match_query)
            if not count_result.get("ok"):
                return count_result
            matched_count = count_result["data"]["matched_count"]
            if matched_count != 1:
                return envelope_err(
                    ErrorType.INVALID_GRAPH_DATA,
                    f"{op} matched_count must be 1 before execution.",
                    details={
                        "operation_index": idx,
                        "matched_count": matched_count,
                    },
                )
            if op == "delete_vertex" and operation.get("cascade", False) is False:
                edge_count_result = _read_count(f"{match_query}.bothE()")
                if not edge_count_result.get("ok"):
                    return edge_count_result
                edge_count = edge_count_result["data"]["matched_count"]
                if edge_count > 0:
                    return envelope_err(
                        "BLOCKED_BY_RELATIONSHIPS",
                        "delete_vertex cascade=false but vertex has associated edges.",
                        suggestion="Delete associated edges first, then retry the vertex delete.",
                        details={
                            "operation_index": idx,
                            "associated_edge_count": edge_count,
                        },
                    )
            if op == "delete_vertex" and operation.get("cascade", False) is True:
                return envelope_err(
                    "CASCADE_NOT_ENABLED",
                    "delete_vertex cascade=true is not enabled in this phase.",
                    suggestion="Delete associated edges explicitly, then delete the vertex with cascade=false.",
                    details={"operation_index": idx},
                )
        write_result = gremlin_tools.execute_gremlin_write(_write_query(operation))
        if isinstance(write_result, dict) and write_result.get("ok") is False:
            return write_result
        if isinstance(write_result, dict) and write_result.get("success") is False:
            return envelope_err(
                ErrorType.CONNECTION_FAILED,
                "HugeGraph write query failed during graph change execution.",
                details=write_result,
                retryable=True,
            )
        if op == "delete_vertex":
            verify_result = _read_count(_vertex_match_query(operation))
            if not verify_result.get("ok"):
                return verify_result
            if verify_result["data"]["matched_count"] != 0:
                return envelope_err(
                    ErrorType.INVALID_GRAPH_DATA,
                    "delete_vertex execution did not remove the matched vertex.",
                    suggestion="Inspect the graph state and retry after confirming the vertex match criteria.",
                    details={
                        "operation_index": idx,
                        "matched_count": verify_result["data"]["matched_count"],
                    },
                )
        results.append(
            {
                "operation_index": idx,
                "op": op,
                "label": operation.get("label"),
                "result": write_result,
            }
        )
    return {
        "success": True,
        "results": results,
        "mutation_summary": _mutation_summary(operations),
    }


def graph_data_to_change_plan(graph_data: dict[str, Any]) -> GraphChangePlan:
    operations: list[dict[str, Any]] = []
    for vertex in graph_data.get("vertices") or []:
        if not isinstance(vertex, dict):
            continue
        operations.append(
            {
                "op": "create_vertex",
                "label": vertex.get("label"),
                "properties": vertex.get("properties") or {},
            }
        )
    for edge in graph_data.get("edges") or []:
        if not isinstance(edge, dict):
            continue
        source_label = edge.get("source_label") or edge.get("outVLabel")
        target_label = edge.get("target_label") or edge.get("inVLabel")
        operations.append(
            {
                "op": "create_edge",
                "label": edge.get("label"),
                "source_label": source_label,
                "target_label": target_label,
                "source_match": edge.get("source")
                if isinstance(edge.get("source"), dict)
                else {"id": edge.get("source") or edge.get("outV")},
                "target_match": edge.get("target")
                if isinstance(edge.get("target"), dict)
                else {"id": edge.get("target") or edge.get("inV")},
                "properties": edge.get("properties") or {},
            }
        )
    return _change_plan_from_operations(operations)


def _fetch_live_schema() -> dict[str, Any] | None:
    try:
        return schema_tools.get_live_schema()
    except Exception:
        return None


def manage_graph_data(
    mode: str,
    graph_data: dict[str, Any] | None = None,
    change_plan: dict[str, Any] | list[dict[str, Any]] | None = None,
    dry_run: bool = True,
    confirm: bool = False,
    plan_hash: str | None = None,
) -> dict[str, Any]:
    if mode == "import":
        if graph_data is None:
            return envelope_err(
                "VALIDATION_ERROR",
                "graph_data is required for mode='import'",
            )
        plan = graph_data_to_change_plan(graph_data)
    elif mode in {"update", "delete"}:
        if change_plan is None:
            return envelope_err(
                "VALIDATION_ERROR",
                f"change_plan is required for mode='{mode}'",
            )
        plan = (
            change_plan
            if isinstance(change_plan, dict)
            else _change_plan_from_operations(change_plan)
        )
    else:
        return envelope_err(
            "VALIDATION_ERROR",
            f"Unknown mode: {mode!r}. Use 'import', 'update', or 'delete'.",
            details={"mode": mode},
        )

    mode_validation = _validate_mode_operations(mode, plan)
    if not mode_validation["valid"]:
        return envelope_err(
            ErrorType.INVALID_GRAPH_DATA,
            "Graph change plan contains operations outside the selected mode.",
            details={"errors": mode_validation["errors"]},
        )

    live_schema = _fetch_live_schema()
    if live_schema is None:
        return envelope_err(
            ErrorType.CONNECTION_FAILED,
            "Cannot read live schema from HugeGraph Server. Schema validation is required before graph data changes.",
            suggestion="Ensure HugeGraph Server is running and accessible, then retry.",
            retryable=True,
        )

    if mode == "import" and graph_data is not None:
        payload_validation = ingest_graph_data.validate_graph_payload(
            graph_data,
            live_schema=live_schema,
        )
        if not payload_validation["valid"]:
            return envelope_err(
                ErrorType.SCHEMA_MISMATCH,
                "Graph data does not match live schema.",
                details={"errors": payload_validation["errors"]},
            )

    dry_run_result = dry_run_graph_change_plan(plan, live_schema)
    if not dry_run_result["valid"]:
        errors = dry_run_result["errors"]
        error_type = next(
            (
                error["error_type"]
                for error in errors
                if isinstance(error, dict) and error.get("error_type")
            ),
            ErrorType.INVALID_GRAPH_DATA,
        )
        return envelope_err(
            error_type,
            "Graph change plan is invalid.",
            details={"errors": errors},
            warnings=dry_run_result.get("warnings", []),
        )

    if dry_run:
        return envelope_ok(dry_run_result, warnings=dry_run_result.get("warnings", []))

    violation = guard(Capability.DATA_WRITE)
    if violation is not None:
        return violation

    if not confirm:
        return envelope_err(
            ErrorType.CONFIRM_REQUIRED,
            "Graph data changes require confirm=True after a dry_run.",
            suggestion="Run dry_run=True, review preview and warnings, then pass confirm=True with the returned plan_hash.",
        )

    expected_plan_hash = dry_run_result["plan_hash"]
    if plan_hash != expected_plan_hash:
        return envelope_err(
            ErrorType.PLAN_HASH_MISMATCH,
            "Provided plan_hash does not match the current graph data change plan.",
            suggestion="Run dry_run=True again and use the returned plan_hash.",
            details={
                "expected_plan_hash": expected_plan_hash,
                "provided_plan_hash": plan_hash,
            },
        )

    return envelope_ok(execute_graph_change_plan(plan))
