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

"""表格数据映射 — 将结构化 rows/columns 转为图数据 {vertices, edges}。

import_table_data() 根据 mapping 将表行映射为顶点和边，
suggest_table_mapping() 基于列名启发式生成可编辑的映射建议。
映射缺失时返回建议而不执行导入，用户审阅后可编辑映射重试。
"""

from hugegraph_mcp.envelope import ErrorType, envelope_err, envelope_ok


def import_table_data(
    table_data: dict[str, Any],
    mapping: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Map structured rows into the graph_data payload used by ingest_graph_data."""

    table_validation = _validate_table_data(table_data)
    if table_validation:
        return _validation_error(table_validation)

    if not _is_complete_mapping(mapping):
        return envelope_ok(
            {
                "graph_data": None,
                "mapping_suggestion": suggest_table_mapping(table_data, mapping),
            },
            warnings=[
                "mapping is incomplete; review and submit mapping to import table data"
            ],
            next_actions=[
                "Edit mapping_suggestion if needed, then call mode='table' with mapping."
            ],
        )

    assert mapping is not None
    mapping_errors = _validate_mapping(table_data["columns"], mapping)
    if mapping_errors:
        return _validation_error(mapping_errors)

    graph_data = _table_to_graph_data(table_data, mapping)
    return envelope_ok({"graph_data": graph_data})


def suggest_table_mapping(
    table_data: dict[str, Any],
    mapping: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Generate an editable best-effort table-to-graph mapping suggestion."""

    columns = _columns(table_data)
    table_label = _normalize_label(str(table_data.get("table_name") or "row"))
    existing = mapping if isinstance(mapping, dict) else {}
    suggested = {
        "vertex_mappings": list(existing.get("vertex_mappings") or []),
        "edge_mappings": list(existing.get("edge_mappings") or []),
    }

    if not suggested["vertex_mappings"]:
        pk_columns = _infer_primary_key_columns(columns, table_label)
        suggested["vertex_mappings"].append(
            {
                "target_label": table_label,
                "column_mapping": {column: column for column in columns},
                "primary_key_columns": pk_columns,
            }
        )

    if not suggested["edge_mappings"]:
        edge_mapping = _suggest_edge_mapping(columns, table_label)
        if edge_mapping is not None:
            suggested["edge_mappings"].append(edge_mapping)

    return suggested


def _validate_table_data(table_data: Any) -> list[str]:
    if not isinstance(table_data, dict):
        return ["table_data must be an object"]

    errors: list[str] = []
    columns = table_data.get("columns")
    rows = table_data.get("rows")
    table_name = table_data.get("table_name")

    if not isinstance(columns, list) or not all(
        isinstance(c, str) and c for c in columns
    ):
        errors.append("table_data.columns must be a list of non-empty strings")
    elif len(columns) != len(set(columns)):
        errors.append("table_data.columns must not contain duplicates")
    if not isinstance(rows, list):
        errors.append("table_data.rows must be a list")
    elif not all(isinstance(row, list) for row in rows):
        errors.append("each table_data.rows item must be a list")
    if not isinstance(table_name, str) or not table_name:
        errors.append("table_data.table_name must be a non-empty string")

    return errors


def _is_complete_mapping(mapping: Any) -> bool:
    if not isinstance(mapping, dict):
        return False
    vertex_mappings = mapping.get("vertex_mappings")
    edge_mappings = mapping.get("edge_mappings")
    return isinstance(vertex_mappings, list) and isinstance(edge_mappings, list)


def _validate_mapping(columns: list[str], mapping: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    column_names = set(columns)
    vertex_mappings = mapping.get("vertex_mappings") or []
    edge_mappings = mapping.get("edge_mappings") or []
    vertex_labels: set[str] = set()

    for idx, vertex_mapping in enumerate(vertex_mappings):
        if not isinstance(vertex_mapping, dict):
            errors.append(f"vertex_mapping {idx} must be an object")
            continue
        label = vertex_mapping.get("target_label")
        if not isinstance(label, str) or not label:
            errors.append(f"vertex_mapping {idx} missing target_label")
        else:
            vertex_labels.add(label)
        errors.extend(
            _validate_column_mapping(
                columns=column_names,
                mapping=vertex_mapping,
                location=f"vertex_mapping {idx}",
            )
        )

    for idx, edge_mapping in enumerate(edge_mappings):
        if not isinstance(edge_mapping, dict):
            errors.append(f"edge_mapping {idx} must be an object")
            continue
        if not isinstance(
            edge_mapping.get("target_label"), str
        ) or not edge_mapping.get("target_label"):
            errors.append(f"edge_mapping {idx} missing target_label")
        errors.extend(
            _validate_column_mapping(
                columns=column_names,
                mapping=edge_mapping,
                location=f"edge_mapping {idx}",
                require_primary_keys=False,
            )
        )
        for endpoint in ("source_vertex", "target_vertex"):
            endpoint_mapping = edge_mapping.get(endpoint)
            if not isinstance(endpoint_mapping, dict):
                errors.append(f"edge_mapping {idx} {endpoint} must be an object")
                continue
            endpoint_label = endpoint_mapping.get("label")
            if not isinstance(endpoint_label, str) or not endpoint_label:
                errors.append(f"edge_mapping {idx} {endpoint} missing label")
            elif endpoint_label not in vertex_labels:
                errors.append(
                    f"edge_mapping {idx} {endpoint} label '{endpoint_label}' is not defined in vertex_mappings"
                )
            pk_columns = endpoint_mapping.get("primary_key_columns")
            if not isinstance(pk_columns, list) or not pk_columns:
                errors.append(
                    f"edge_mapping {idx} {endpoint} primary_key_columns must be a non-empty list"
                )
                continue
            for pk_column in pk_columns:
                if pk_column not in column_names:
                    errors.append(
                        f"edge_mapping {idx} {endpoint} primary key column '{pk_column}' does not exist"
                    )

    return errors


def _validate_column_mapping(
    *,
    columns: set[str],
    mapping: dict[str, Any],
    location: str,
    require_primary_keys: bool = True,
) -> list[str]:
    errors: list[str] = []
    column_mapping = mapping.get("column_mapping")
    if not isinstance(column_mapping, dict):
        errors.append(f"{location} column_mapping must be an object")
    else:
        for prop, column in column_mapping.items():
            if not isinstance(prop, str) or not prop:
                errors.append(
                    f"{location} column_mapping property names must be non-empty strings"
                )
            if column not in columns:
                errors.append(f"{location} column '{column}' does not exist")

    primary_key_columns = mapping.get("primary_key_columns")
    if require_primary_keys:
        if not isinstance(primary_key_columns, list) or not primary_key_columns:
            errors.append(f"{location} primary_key_columns must be a non-empty list")
        else:
            for pk_column in primary_key_columns:
                if pk_column not in columns:
                    errors.append(
                        f"{location} primary key column '{pk_column}' does not exist"
                    )
    elif primary_key_columns is not None and not isinstance(primary_key_columns, list):
        errors.append(f"{location} primary_key_columns must be a list when provided")

    return errors


def _table_to_graph_data(
    table_data: dict[str, Any],
    mapping: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    vertices: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    seen_vertices: set[tuple[Any, ...]] = set()

    for row in _row_dicts(table_data):
        if _is_empty_row(row):
            continue
        for vertex_mapping in mapping.get("vertex_mappings") or []:
            vertex = _build_vertex(row, vertex_mapping)
            identity = _vertex_identity(vertex, vertex_mapping)
            if identity in seen_vertices:
                continue
            seen_vertices.add(identity)
            vertices.append(vertex)
        for edge_mapping in mapping.get("edge_mappings") or []:
            edge = _build_edge(row, edge_mapping, mapping.get("vertex_mappings") or [])
            if edge is not None:
                edges.append(edge)

    return {"vertices": vertices, "edges": edges}


def _row_dicts(table_data: dict[str, Any]) -> list[dict[str, Any]]:
    columns = table_data["columns"]
    rows = table_data["rows"]
    row_dicts = []
    for row in rows:
        row_dicts.append(
            {
                column: row[idx] if idx < len(row) else None
                for idx, column in enumerate(columns)
            }
        )
    return row_dicts


def _build_vertex(
    row: dict[str, Any], vertex_mapping: dict[str, Any]
) -> dict[str, Any]:
    return {
        "label": vertex_mapping["target_label"],
        "properties": _mapped_properties(
            row, vertex_mapping.get("column_mapping") or {}
        ),
    }


def _build_edge(
    row: dict[str, Any],
    edge_mapping: dict[str, Any],
    vertex_mappings: list[dict[str, Any]],
) -> dict[str, Any] | None:
    source = _endpoint_properties(row, edge_mapping["source_vertex"], vertex_mappings)
    target = _endpoint_properties(row, edge_mapping["target_vertex"], vertex_mappings)
    if _is_empty_values(source.values()) or _is_empty_values(target.values()):
        return None

    edge: dict[str, Any] = {
        "label": edge_mapping["target_label"],
        "source_label": edge_mapping["source_vertex"]["label"],
        "target_label": edge_mapping["target_vertex"]["label"],
        "source": source,
        "target": target,
    }
    properties = _mapped_properties(row, edge_mapping.get("column_mapping") or {})
    if properties:
        edge["properties"] = properties
    return edge


def _mapped_properties(
    row: dict[str, Any], column_mapping: dict[str, str]
) -> dict[str, Any]:
    return {prop: row.get(column) for prop, column in column_mapping.items()}


def _endpoint_properties(
    row: dict[str, Any],
    endpoint_mapping: dict[str, Any],
    vertex_mappings: list[dict[str, Any]],
) -> dict[str, Any]:
    column_to_property = _column_to_property(endpoint_mapping, vertex_mappings)
    return {
        column_to_property.get(column, column): row.get(column)
        for column in endpoint_mapping.get("primary_key_columns") or []
    }


def _vertex_identity(
    vertex: dict[str, Any],
    vertex_mapping: dict[str, Any],
) -> tuple[Any, ...]:
    properties = vertex.get("properties") or {}
    primary_key_columns = vertex_mapping.get("primary_key_columns") or []
    column_to_property = {
        column: prop
        for prop, column in (vertex_mapping.get("column_mapping") or {}).items()
    }
    return (
        vertex.get("label"),
        *(
            properties.get(column_to_property.get(column, column))
            for column in primary_key_columns
        ),
    )


def _column_to_property(
    endpoint_mapping: dict[str, Any],
    vertex_mappings: list[dict[str, Any]],
) -> dict[str, str]:
    label = endpoint_mapping.get("label")
    endpoint_pk_columns = set(endpoint_mapping.get("primary_key_columns") or [])
    for vertex_mapping in vertex_mappings:
        if vertex_mapping.get("target_label") != label:
            continue
        vertex_pk_columns = set(vertex_mapping.get("primary_key_columns") or [])
        if endpoint_pk_columns and not endpoint_pk_columns.issubset(vertex_pk_columns):
            continue
        return {
            column: prop
            for prop, column in (vertex_mapping.get("column_mapping") or {}).items()
        }
    return {}


def _is_empty_row(row: dict[str, Any]) -> bool:
    return _is_empty_values(row.values())


def _is_empty_values(values: Any) -> bool:
    return all(value is None or value == "" for value in values)


def _columns(table_data: dict[str, Any]) -> list[str]:
    columns = table_data.get("columns")
    if not isinstance(columns, list):
        return []
    return [column for column in columns if isinstance(column, str)]


def _infer_primary_key_columns(columns: list[str], label: str) -> list[str]:
    normalized_columns = {column.lower(): column for column in columns}
    for candidate in ("id", f"{label}_id", "uuid", "key"):
        if candidate in normalized_columns:
            return [normalized_columns[candidate]]
    for column in columns:
        if column.lower().endswith("_id"):
            return [column]
    return columns[:1]


def _suggest_edge_mapping(
    columns: list[str], table_label: str
) -> dict[str, Any] | None:
    source_column = _first_existing(
        columns, ("source_id", "src_id", "from_id", "out_id")
    )
    target_column = _first_existing(columns, ("target_id", "dst_id", "to_id", "in_id"))
    if source_column is None or target_column is None:
        return None
    return {
        "target_label": table_label,
        "source_vertex": {
            "label": _endpoint_label(source_column, "source"),
            "primary_key_columns": [source_column],
        },
        "target_vertex": {
            "label": _endpoint_label(target_column, "target"),
            "primary_key_columns": [target_column],
        },
        "column_mapping": {
            column: column
            for column in columns
            if column not in {source_column, target_column}
        },
    }


def _first_existing(columns: list[str], candidates: tuple[str, ...]) -> str | None:
    by_lower = {column.lower(): column for column in columns}
    for candidate in candidates:
        if candidate in by_lower:
            return by_lower[candidate]
    return None


def _endpoint_label(column: str, fallback: str) -> str:
    normalized = column.lower()
    for suffix in ("_id", "_key", "_uuid"):
        if normalized.endswith(suffix):
            normalized = normalized[: -len(suffix)]
            break
    if normalized in {"source", "src", "from", "out"}:
        return fallback
    if normalized in {"target", "dst", "to", "in"}:
        return "target"
    return _normalize_label(normalized)


def _normalize_label(value: str) -> str:
    chars = []
    previous_underscore = False
    for char in value.strip().lower():
        if char.isalnum():
            chars.append(char)
            previous_underscore = False
        elif not previous_underscore:
            chars.append("_")
            previous_underscore = True
    label = "".join(chars).strip("_") or "row"
    if label.endswith("s") and len(label) > 1:
        label = label[:-1]
    return label


def _validation_error(errors: list[str]) -> dict[str, Any]:
    return envelope_err(
        ErrorType.INVALID_GRAPH_DATA,
        "Table data mapping is invalid.",
        details={"errors": errors},
    )
