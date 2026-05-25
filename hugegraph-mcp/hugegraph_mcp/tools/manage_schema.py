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
from hugegraph_mcp import schema_tools


ALLOWED_OPERATION_TYPES = frozenset(
    {
        "create_property_key",
        "create_vertex_label",
        "create_edge_label",
        "create_index_label",
    }
)

REQUIRED_FIELDS = {
    "create_property_key": ("name", "data_type"),
    "create_vertex_label": ("name",),
    "create_edge_label": ("name", "source_label", "target_label"),
    "create_index_label": ("name", "base_type", "base_label"),
}


ValidationError = dict[str, Any]


def _operation_type(operation: dict[str, Any]) -> str:
    return str(operation.get("type", ""))


def _is_delete_operation(op_type: str) -> bool:
    lowered = op_type.lower()
    return "delete" in lowered or "drop" in lowered


def _validation_error(
    operation_index: int,
    operation: Any,
    reason: str,
    suggestion: str,
) -> ValidationError:
    return {
        "operation_index": operation_index,
        "operation": operation,
        "reason": reason,
        "suggestion": suggestion,
    }


def _schema_items(live_schema: dict[str, Any], key: str) -> set[str]:
    schema = live_schema.get("schema", {})
    return {
        item.get("name")
        for item in schema.get(key, [])
        if isinstance(item, dict) and item.get("name")
    }


def _validate_property_references(
    *,
    idx: int,
    operation: dict[str, Any],
    field: str,
    property_keys: set[str],
    errors: list[ValidationError],
) -> None:
    values = operation.get(field, [])
    if values in (None, ""):
        return
    if not isinstance(values, list):
        errors.append(
            _validation_error(
                idx,
                operation,
                f"{field} must be a list",
                f"Use an array of existing property key names for {field}.",
            )
        )
        return

    missing_properties = [name for name in values if name not in property_keys]
    if missing_properties:
        errors.append(
            _validation_error(
                idx,
                operation,
                f"{field} references undefined property key(s): {', '.join(missing_properties)}",
                "Create these property keys first and rerun validation after they exist in the live schema.",
            )
        )


def _validation_warnings(operations: list[dict[str, Any]]) -> list[str]:
    warnings: list[str] = []
    for idx, operation in enumerate(operations):
        if not isinstance(operation, dict):
            continue
        if operation.get("type") == "create_vertex_label" and not operation.get(
            "primary_keys"
        ):
            warnings.append(
                f"operation {idx} (create_vertex_label) has no primary_keys definition"
            )
    return warnings


def validate_schema_operations(
    operations: list[dict[str, Any]], live_schema: dict[str, Any] | None = None
) -> dict[str, Any]:
    errors: list[ValidationError] = []

    if not isinstance(operations, list):
        return {
            "valid": False,
            "errors": [
                _validation_error(
                    -1,
                    operations,
                    "operations must be a list",
                    "Pass schema operations as a JSON array.",
                )
            ],
            "warnings": [],
        }

    live_schema = live_schema or schema_tools.get_live_schema()
    property_keys = _schema_items(live_schema, "propertykeys")
    vertex_labels = _schema_items(live_schema, "vertexlabels")
    edge_labels = _schema_items(live_schema, "edgelabels")
    index_labels = _schema_items(live_schema, "indexlabels")

    for idx, operation in enumerate(operations):
        if not isinstance(operation, dict):
            errors.append(
                _validation_error(
                    idx,
                    operation,
                    "operation must be an object",
                    "Replace this item with a schema operation object.",
                )
            )
            continue

        op_type = _operation_type(operation)
        if _is_delete_operation(op_type):
            errors.append(
                _validation_error(
                    idx,
                    operation,
                    f"unsupported delete/drop type: {op_type}",
                    "Use create-only schema operations; destructive schema changes are not supported.",
                )
            )
            continue

        if op_type not in ALLOWED_OPERATION_TYPES:
            errors.append(
                _validation_error(
                    idx,
                    operation,
                    f"unsupported type: {op_type}",
                    "Use one of: create_property_key, create_vertex_label, create_edge_label, create_index_label.",
                )
            )
            continue

        for field in REQUIRED_FIELDS[op_type]:
            if field not in operation or operation[field] in (None, ""):
                errors.append(
                    _validation_error(
                        idx,
                        operation,
                        f"missing required field: {field}",
                        f"Add {field} to the {op_type} operation.",
                    )
                )
        if any(
            field not in operation or operation[field] in (None, "")
            for field in REQUIRED_FIELDS[op_type]
        ):
            continue

        name = operation.get("name")
        if op_type == "create_property_key" and name in property_keys:
            errors.append(
                _validation_error(
                    idx,
                    operation,
                    f"property key already exists: {name}",
                    "Use a new property key name or remove this create_property_key operation.",
                )
            )
        elif op_type == "create_vertex_label":
            if name in vertex_labels:
                errors.append(
                    _validation_error(
                        idx,
                        operation,
                        f"vertex label already exists: {name}",
                        "Use a new vertex label name or remove this create_vertex_label operation.",
                    )
                )
            _validate_property_references(
                idx=idx,
                operation=operation,
                field="properties",
                property_keys=property_keys,
                errors=errors,
            )
        elif op_type == "create_edge_label":
            if name in edge_labels:
                errors.append(
                    _validation_error(
                        idx,
                        operation,
                        f"edge label already exists: {name}",
                        "Use a new edge label name or remove this create_edge_label operation.",
                    )
                )
            for field in ("source_label", "target_label"):
                label = operation[field]
                if label not in vertex_labels:
                    errors.append(
                        _validation_error(
                            idx,
                            operation,
                            f"{field} references undefined vertex label: {label}",
                            "Create the referenced vertex label first and rerun validation after it exists in the live schema.",
                        )
                    )
        elif op_type == "create_index_label":
            if name in index_labels:
                errors.append(
                    _validation_error(
                        idx,
                        operation,
                        f"index label already exists: {name}",
                        "Use a new index label name or remove this create_index_label operation.",
                    )
                )
            base_type = str(operation.get("base_type", "")).upper()
            base_label = operation["base_label"]
            if base_type == "VERTEX":
                if base_label not in vertex_labels:
                    errors.append(
                        _validation_error(
                            idx,
                            operation,
                            f"base_label references undefined vertex label: {base_label}",
                            "Create the referenced vertex label first and rerun validation after it exists in the live schema.",
                        )
                    )
            elif base_type == "EDGE":
                if base_label not in edge_labels:
                    errors.append(
                        _validation_error(
                            idx,
                            operation,
                            f"base_label references undefined edge label: {base_label}",
                            "Create the referenced edge label first and rerun validation after it exists in the live schema.",
                        )
                    )
            else:
                errors.append(
                    _validation_error(
                        idx,
                        operation,
                        f"unsupported base_type for index label: {base_type}",
                        "Use base_type='VERTEX' or base_type='EDGE'.",
                    )
                )
            _validate_property_references(
                idx=idx,
                operation=operation,
                field="fields",
                property_keys=property_keys,
                errors=errors,
            )

    return {
        "valid": not bool(errors),
        "errors": errors,
        "warnings": _validation_warnings(operations),
    }


def _current_plan_context(
    operations: list[dict[str, Any]], live_schema: dict[str, Any] | None = None
) -> dict[str, Any]:
    cfg = MCPConfig.from_env()
    live_schema = live_schema or schema_tools.get_live_schema()
    return {
        "operations": operations,
        "graph": cfg.graph,
        "graphspace": cfg.graphspace,
        "schema_version": live_schema,
    }


def calculate_plan_hash(
    operations: list[dict[str, Any]], live_schema: dict[str, Any] | None = None
) -> str:
    payload = _current_plan_context(operations, live_schema)
    encoded = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


def _risk_warnings(
    operations: list[dict[str, Any]], live_schema: dict[str, Any] | None = None
) -> list[str]:
    warnings: list[str] = []
    live_schema = live_schema or schema_tools.get_live_schema()
    property_keys = _schema_items(live_schema, "propertykeys")
    vertex_labels = _schema_items(live_schema, "vertexlabels")
    edge_labels = _schema_items(live_schema, "edgelabels")
    index_labels = _schema_items(live_schema, "indexlabels")

    created_vertex_labels = [
        op["name"] for op in operations if op.get("type") == "create_vertex_label"
    ]
    created_edge_labels = [
        op["name"] for op in operations if op.get("type") == "create_edge_label"
    ]
    indexed_labels = {
        op.get("base_label")
        for op in operations
        if op.get("type") == "create_index_label" and op.get("base_label")
    }

    for operation in operations:
        op_type = operation.get("type")
        name = operation.get("name")
        if op_type == "create_property_key" and name in property_keys:
            warnings.append(f"property key already exists: {name}")
        elif op_type == "create_vertex_label" and name in vertex_labels:
            warnings.append(f"vertex label already exists: {name}")
        elif op_type == "create_edge_label" and name in edge_labels:
            warnings.append(f"edge label already exists: {name}")
        elif op_type == "create_index_label" and name in index_labels:
            warnings.append(f"index label already exists: {name}")

    for label in created_vertex_labels + created_edge_labels:
        if label not in indexed_labels:
            warnings.append(f"no index operation included for label: {label}")

    return warnings


def _mutation_summary(operations: list[dict[str, Any]]) -> str:
    counts: dict[str, int] = {}
    for operation in operations:
        op_type = operation.get("type", "unknown")
        counts[op_type] = counts.get(op_type, 0) + 1

    if not counts:
        return "No schema operations planned."

    parts = [f"{op_type}={count}" for op_type, count in sorted(counts.items())]
    return "Schema operations planned: " + ", ".join(parts)


def dry_run_schema_operations(operations: list[dict[str, Any]]) -> dict[str, Any]:
    live_schema = schema_tools.get_live_schema()
    validation = validate_schema_operations(operations, live_schema)
    if not validation["valid"]:
        return validation

    return {
        "valid": True,
        "plan_hash": calculate_plan_hash(operations, live_schema),
        "mutation_summary": _mutation_summary(operations),
        "warnings": validation.get("warnings", [])
        + _risk_warnings(operations, live_schema),
    }


def _design_from_operations(operations: list[dict[str, Any]]) -> dict[str, Any]:
    params = operations[0] if operations else {}
    return schema_tools.design_schema(
        thought=params.get("thought", ""),
        thought_number=params.get("thought_number", 1),
        total_thoughts=params.get("total_thoughts", 4),
        next_thought_needed=params.get("next_thought_needed", True),
        is_revision=params.get("is_revision", False),
        revision_of=params.get("revision_of"),
    )


def manage_schema(
    mode: str,
    operations: list[dict[str, Any]] | None = None,
    confirm: bool = False,
    plan_hash: str | None = None,
) -> dict[str, Any]:
    operations = operations or []

    if mode == "design":
        return envelope_ok(_design_from_operations(operations))

    if mode == "validate":
        return envelope_ok(validate_schema_operations(operations))

    if mode == "dry_run":
        return envelope_ok(dry_run_schema_operations(operations))

    if mode == "apply":
        violation = guard(Capability.SCHEMA_WRITE)
        if violation is not None:
            return violation

        if not confirm:
            return envelope_err(
                ErrorType.CONFIRM_REQUIRED,
                "Schema apply requires confirm=True after a dry_run.",
                suggestion="Run mode='dry_run', review warnings, then pass confirm=True with the returned plan_hash.",
            )

        expected_plan_hash = calculate_plan_hash(operations)
        if plan_hash != expected_plan_hash:
            return envelope_err(
                ErrorType.PLAN_HASH_MISMATCH,
                "Provided plan_hash does not match the current schema plan.",
                suggestion="Run mode='dry_run' again and use the returned plan_hash.",
                details={
                    "expected_plan_hash": expected_plan_hash,
                    "provided_plan_hash": plan_hash,
                },
            )

        return envelope_ok(schema_tools.execute_schema_operations(operations))

    return envelope_err(
        ErrorType.SCHEMA_MISMATCH,
        f"Unsupported manage_schema mode: {mode}",
        suggestion="Use one of: design, validate, dry_run, apply.",
    )
