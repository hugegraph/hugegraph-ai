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

"""图数据导入 — 结构化 graph_data 校验+写入链路。

ingest_graph_data() 提供 dry_run → confirm → plan_hash → execute 安全链。
validate_graph_payload() 对 vertices/edges 做全面 schema 校验：
- label 是否存在于 live schema
- properties 字段是否在对应 label 中定义
- 主键是否提供
- 边端点是否可解析
- 类型匹配
"""

import json
from copy import deepcopy
from typing import Any
from uuid import uuid4

from hugegraph_mcp.config import MCPConfig
from hugegraph_mcp.envelope import ErrorType, envelope_err, envelope_ok
from hugegraph_mcp.guard import Capability, guard
from hugegraph_mcp.hugegraph_ai_client import post
from hugegraph_mcp.tools.schema_utils import (
    edge_schema_endpoint_label as _edge_schema_endpoint_label,
    normalized_schema_summary,
    primary_key_names as _primary_key_names,
    property_names as _property_names,
    schema_payload as _schema_payload,
)
from hugegraph_mcp.tools.live_schema import fetch_live_schema_or_none


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
    # 边端点支持两种写法：直接给后端 id，或按顶点主键给对象。
    # 返回多个候选身份，是为了兼容用户传入 "1:alice" 这类后端 id
    # 和 {"name": "alice"} 这类主键对象两种输入。
    identities: list[tuple[str, str, Any]] = []
    primary_keys = schema_primary_keys.get(label, [])

    if isinstance(value, dict):
        explicit_id = value.get("id")
        if _identity_value_present(explicit_id):
            identities.append((label, "id", explicit_id))
        if primary_keys:
            missing = [
                pk
                for pk in primary_keys
                if pk not in value or not _identity_value_present(value.get(pk))
            ]
            if missing:
                return identities, missing[0]
            identities.append(
                (label, "pk", tuple(value.get(pk) for pk in primary_keys))
            )
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
    return {
        "vertexlabels": raw.get("vertexlabels", []),
        "edgelabels": raw.get("edgelabels", []),
        "propertykeys": raw.get("propertykeys", []),
        "indexlabels": raw.get("indexlabels", []),
    }


def _canonical_json_key(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))


def _normalize_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _normalize_value(value[key])
            for key in sorted(value, key=lambda item: str(item))
        }
    if isinstance(value, list):
        return [_normalize_value(item) for item in value]
    return value


def _vertex_sort_key(
    vertex: Any,
    schema_primary_keys: dict[str, list[str]],
) -> tuple[str, str]:
    if not isinstance(vertex, dict):
        return ("", _canonical_json_key(vertex))
    label = str(vertex.get("label") or "")
    if _identity_value_present(vertex.get("id")):
        identity = vertex.get("id")
    else:
        props = vertex.get("properties")
        primary_keys = schema_primary_keys.get(label, [])
        if isinstance(props, dict) and primary_keys:
            identity = props.get(primary_keys[0])
        elif isinstance(props, dict) and props:
            first_key = sorted(props, key=lambda item: str(item))[0]
            identity = props.get(first_key)
        else:
            identity = None
    return (label, _canonical_json_key(identity))


def _edge_sort_key(edge: Any) -> tuple[str, str, str, str]:
    if not isinstance(edge, dict):
        return ("", "", "", _canonical_json_key(edge))
    source_label, source = _edge_endpoint(edge, "source")
    target_label, target = _edge_endpoint(edge, "target")
    return (
        str(edge.get("label") or ""),
        str(source_label or ""),
        str(target_label or ""),
        _canonical_json_key(
            {
                "source": source,
                "target": target,
                "properties": edge.get("properties", {}),
            }
        ),
    )


def _normalize_graph_data(
    graph_data: dict[str, Any],
    schema_summary: dict[str, Any] | None,
) -> dict[str, Any]:
    # plan_hash 需要对输入顺序不敏感：同一批顶点/边即使 JSON 数组顺序不同，
    # 也应得到同一个 hash；但属性值、schema 主键等安全相关内容必须参与 hash。
    normalized = _normalize_value(graph_data)
    if not isinstance(normalized, dict):
        return normalized

    schema_primary_keys: dict[str, list[str]] = {}
    if schema_summary:
        for vertex_label in schema_summary.get("vertexlabels", []):
            if isinstance(vertex_label, dict):
                name = vertex_label.get("name")
                primary_keys = vertex_label.get("primary_keys")
                if isinstance(name, str) and isinstance(primary_keys, list):
                    schema_primary_keys[name] = primary_keys

    vertices = normalized.get("vertices")
    if isinstance(vertices, list):
        normalized["vertices"] = sorted(
            vertices,
            key=lambda vertex: _vertex_sort_key(vertex, schema_primary_keys),
        )

    edges = normalized.get("edges")
    if isinstance(edges, list):
        normalized["edges"] = sorted(edges, key=_edge_sort_key)

    return normalized


def _schema_vertex_info(raw_schema: dict[str, Any]) -> dict[str, dict[str, Any]]:
    info: dict[str, dict[str, Any]] = {}
    for vertex_label in raw_schema.get("vertexlabels", []):
        if not isinstance(vertex_label, dict):
            continue
        name = vertex_label.get("name")
        if isinstance(name, str):
            info[name] = {
                "id": vertex_label.get("id"),
                "primary_keys": _primary_key_names(vertex_label),
            }
    return info


def _canonical_primary_key_id(
    label: str,
    values: tuple[Any, ...],
    vertex_info: dict[str, dict[str, Any]],
) -> str | None:
    label_id = vertex_info.get(label, {}).get("id")
    if label_id is None:
        return None
    return f"{label_id}:{'!'.join(str(value) for value in values)}"


def _vertex_backend_id(
    vertex: dict[str, Any],
    vertex_info: dict[str, dict[str, Any]],
) -> Any:
    # HugeGraph PRIMARY_KEY 顶点的后端 id 由 label id 和主键值拼接而成。
    # 在导入前补齐 id，能让边端点在同一批 payload 内稳定引用刚创建的顶点。
    explicit_id = vertex.get("id")
    if _identity_value_present(explicit_id):
        return explicit_id

    label = vertex.get("label")
    props = vertex.get("properties")
    if not isinstance(label, str) or not isinstance(props, dict):
        return None

    primary_keys = vertex_info.get(label, {}).get("primary_keys", [])
    if not primary_keys:
        return None
    if not all(
        pk in props and _identity_value_present(props.get(pk)) for pk in primary_keys
    ):
        return None

    values = tuple(props.get(pk) for pk in primary_keys)
    return _canonical_primary_key_id(label, values, vertex_info)


def _vertex_identity_map(
    vertices: list[Any],
    raw_schema: dict[str, Any],
) -> tuple[dict[tuple[str, str, Any], Any], dict[str, list[str]]]:
    # 建立"用户可表达的身份"到 HugeGraph 后端 id 的映射。
    # 同一顶点可能同时拥有显式 id、PRIMARY_KEY 后端 id 和主键 tuple，
    # 边端点解析时任意一种命中都应该指向同一个后端顶点。
    vertex_info = _schema_vertex_info(raw_schema)
    schema_primary_keys = {
        label: info.get("primary_keys", []) for label, info in vertex_info.items()
    }
    identities: dict[tuple[str, str, Any], Any] = {}

    for vertex in vertices:
        if not isinstance(vertex, dict):
            continue
        label = vertex.get("label")
        if not isinstance(label, str):
            continue

        backend_id = _vertex_backend_id(vertex, vertex_info)
        if _identity_value_present(backend_id):
            vertex.setdefault("id", backend_id)
            identities[(label, "id", backend_id)] = backend_id

        explicit_id = vertex.get("id")
        if _identity_value_present(explicit_id):
            identities[(label, "id", explicit_id)] = backend_id or explicit_id

        props = vertex.get("properties")
        primary_keys = schema_primary_keys.get(label, [])
        if isinstance(props, dict) and primary_keys:
            if all(
                pk in props and _identity_value_present(props.get(pk))
                for pk in primary_keys
            ):
                values = tuple(props.get(pk) for pk in primary_keys)
                identities[(label, "pk", values)] = backend_id or explicit_id

    return identities, schema_primary_keys


def _endpoint_backend_id(
    label: str,
    value: Any,
    identities: dict[tuple[str, str, Any], Any],
    schema_primary_keys: dict[str, list[str]],
    vertex_info: dict[str, dict[str, Any]],
) -> Any:
    # 边端点优先解析为本批 payload 中的顶点，保证"先创建顶点再创建边"
    # 的批量导入场景不需要用户提前知道 HugeGraph 后端 id。
    endpoint_identities, _missing_pk = _endpoint_identities(
        label,
        value,
        schema_primary_keys,
    )
    for identity in endpoint_identities:
        if identity in identities:
            return identities[identity]

    if isinstance(value, dict):
        explicit_id = value.get("id")
        if _identity_value_present(explicit_id):
            return explicit_id

        primary_keys = schema_primary_keys.get(label, [])
        if primary_keys and all(
            pk in value and _identity_value_present(value.get(pk))
            for pk in primary_keys
        ):
            values = tuple(value.get(pk) for pk in primary_keys)
            return _canonical_primary_key_id(label, values, vertex_info)
        return None

    if _identity_value_present(value):
        return value
    return None


def _prepare_graph_import_data(
    graph_data: dict[str, Any],
    live_schema: dict[str, Any],
) -> dict[str, Any]:
    # HugeGraph-AI 的 graph-import 接口需要 outV/inV/outVLabel/inVLabel。
    # MCP 对用户暴露更友好的 source/target，因此这里在写入前做一次格式转换。
    prepared = deepcopy(graph_data)
    raw_schema = _schema_payload(live_schema) or {}
    vertex_info = _schema_vertex_info(raw_schema)
    vertices = prepared.get("vertices") or []
    edges = prepared.get("edges") or []
    identities, schema_primary_keys = _vertex_identity_map(vertices, raw_schema)

    for edge in edges:
        if not isinstance(edge, dict):
            continue
        src_label, source = _edge_endpoint(edge, "source")
        tgt_label, target = _edge_endpoint(edge, "target")
        edge.setdefault("properties", {})

        if isinstance(src_label, str):
            source_id = _endpoint_backend_id(
                src_label,
                source,
                identities,
                schema_primary_keys,
                vertex_info,
            )
            if _identity_value_present(source_id):
                edge["outV"] = source_id
            edge.setdefault("outVLabel", src_label)

        if isinstance(tgt_label, str):
            target_id = _endpoint_backend_id(
                tgt_label,
                target,
                identities,
                schema_primary_keys,
                vertex_info,
            )
            if _identity_value_present(target_id):
                edge["inV"] = target_id
            edge.setdefault("inVLabel", tgt_label)

    return prepared


def validate_graph_payload(
    graph_data: Any,
    live_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """校验 graph_data (vertices/edges) 与 live schema 的兼容性。

    覆盖：label 存在性、properties 字段合法性、主键完整性、
    边端点可解析性、类型匹配、重复检测、索引建议。
    """
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
    raw = _schema_payload(live_schema) if live_schema is not None else None
    schema_available = raw is not None
    if schema_available:
        # 把 live schema 摘成 label -> 属性/主键/类型表，后续校验只依赖这份快照。
        # 这避免遍历过程中 schema 被重复读取导致前后判断不一致。
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
            if schema_available and label not in schema_vlabels:
                errors.append(f"vertex {idx} label '{label}' does not exist in schema")

            props = vertex.get("properties")
            if isinstance(props, dict):
                schema_prop_names = schema_props.get(label, set())
                for prop_name, prop_value in props.items():
                    if prop_value is None or prop_value == "":
                        warnings.append(
                            f"vertex {idx} property '{prop_name}' has empty value"
                        )
                    if (
                        schema_available
                        and label in schema_props
                        and prop_name not in schema_prop_names
                    ):
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
                # PRIMARY_KEY label 必须提供完整主键；否则 HugeGraph 无法构造稳定 id，
                # 后续边端点也无法可靠解析到这个顶点。
                if not isinstance(props, dict):
                    props = {}
                for pk in primary_keys:
                    if pk not in props or not _identity_value_present(props.get(pk)):
                        errors.append(
                            f"vertex {idx} missing primary key value for label '{label}': {pk}"
                        )
                if all(
                    pk in props and _identity_value_present(props.get(pk))
                    for pk in primary_keys
                ):
                    identity = (
                        label,
                        "pk",
                        tuple(props.get(pk) for pk in primary_keys),
                    )
                    if identity in vertex_identity_index:
                        errors.append(
                            f"vertex {idx} duplicate primary key identity for label '{label}': "
                            f"values={tuple(props.get(pk) for pk in primary_keys)} "
                            f"already used by vertex {vertex_identity_index[identity]}"
                        )
                    else:
                        vertex_identity_index[identity] = idx
            explicit_id = vertex.get("id")
            if _identity_value_present(explicit_id):
                # 同一个 payload 内不允许重复 id 或重复主键身份，避免边端点解析到多义目标。
                identity = (label, "id", explicit_id)
                if identity in vertex_identity_index:
                    errors.append(
                        f"vertex {idx} duplicate id '{explicit_id}' for label '{label}' "
                        f"already used by vertex {vertex_identity_index[identity]}"
                    )
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
                if schema_available and label not in schema_elabels:
                    errors.append(
                        f"edge {idx} label '{label}' does not exist in schema"
                    )
            if schema_available:
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
                        warnings.append(
                            f"edge {idx} property '{prop_name}' has empty value"
                        )
                    if (
                        schema_available
                        and label in schema_eprops
                        and prop_name not in schema_prop_names
                    ):
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
                    # 端点对象缺主键时直接报错，不退化为字符串匹配；
                    # 退化匹配会把错误数据静默写成悬空边。
                    errors.append(
                        f"edge {idx} {endpoint_name} endpoint missing primary key for label '{endpoint_label}': {missing_pk}"
                    )
                    continue
                if identities and not any(
                    identity in vertex_identity_index for identity in identities
                ):
                    errors.append(
                        f"edge {idx} {endpoint_name} endpoint not found for label '{endpoint_label}': {_format_endpoint_value(endpoint_value)}"
                    )

    if isinstance(edges, list):
        edge_pairs = []
        for e in edges:
            if isinstance(e, dict):
                edge_pairs.append(
                    (
                        e.get("label"),
                        e.get("source_label"),
                        e.get("target_label"),
                        e.get("source"),
                        e.get("target"),
                    )
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
    """计算图数据导入的计划哈希（兼容旧接口）。"""
    from hugegraph_mcp.plan_hash import compute_payload_digest

    cfg = MCPConfig.from_env()
    schema_summary = normalized_schema_summary(live_schema)
    payload = {
        "graph_data": _normalize_graph_data(graph_data, schema_summary),
        "graph": cfg.graph,
        "graphspace": cfg.graphspace,
    }
    if schema_summary is not None:
        payload["schema_summary"] = schema_summary
    return compute_payload_digest(payload)


def _fetch_live_schema() -> dict[str, Any] | None:
    return fetch_live_schema_or_none()


def ingest_graph_data(
    graph_data: dict[str, Any],
    dry_run: bool = True,
    confirm: bool = False,
    plan_hash: str | None = None,
    nonce: str | None = None,
    expires_at: float | None = None,
) -> dict[str, Any]:
    """导入图数据 — 安全链入口。

    dry_run=True: schema 校验 + plan_hash 生成，不写入
    dry_run=False + confirm=True + plan_hash 匹配: 执行写入
    nonce/expires_at: dry_run 返回的 plan_context 中的字段，confirm 时必须传回
    """
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

    from hugegraph_mcp.plan_hash import (
        build_plan_context,
        compute_plan_hash,
        compute_payload_digest,
    )

    mutation_summary = _mutation_summary(graph_data)
    warnings = validation["warnings"]

    # 构建目标绑定的计划上下文（包含 url、user、readonly、nonce、expires_at）
    cfg = MCPConfig.from_env()
    schema_summary = normalized_schema_summary(live_schema)
    payload_for_digest = {
        "graph_data": _normalize_graph_data(graph_data, schema_summary),
        "graph": cfg.graph,
        "graphspace": cfg.graphspace,
    }
    if schema_summary is not None:
        payload_for_digest["schema_summary"] = schema_summary

    payload_digest = compute_payload_digest(payload_for_digest)
    schema_hash = compute_payload_digest(schema_summary) if schema_summary else None
    plan_context, _ = build_plan_context(
        tool_name="ingest_graph_data",
        mode="import",
        payload_digest=payload_digest,
        schema_hash=schema_hash,
        nonce=nonce,
    )

    if dry_run:
        return envelope_ok(
            {
                "plan_hash": compute_plan_hash(plan_context),
                "plan_context": {
                    "nonce": plan_context.nonce,
                    "expires_at": plan_context.expires_at,
                    "graph_url": plan_context.graph_url,
                    "graph_name": plan_context.graph_name,
                    "graphspace": plan_context.graphspace,
                    "principal": plan_context.principal,
                    "readonly": plan_context.readonly,
                },
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

    # 使用目标绑定验证：重新读取 config 和 schema，重新计算哈希
    # nonce 必须从 dry_run 返回的 plan_context 中传回
    from hugegraph_mcp.plan_hash import verify_plan_hash

    valid, error_type, details = verify_plan_hash(
        submitted_hash=plan_hash,
        tool_name="ingest_graph_data",
        mode="import",
        payload_digest=payload_digest,
        schema_hash=schema_hash,
        nonce=nonce or plan_context.nonce,
        expires_at=expires_at,
    )
    if not valid:
        return envelope_err(
            ErrorType.PLAN_HASH_MISMATCH,
            "Plan hash mismatch: config, schema, or payload has changed since dry_run.",
            suggestion="Run dry_run=True again and use the returned plan_hash.",
            details=details,
        )

    batch_id = f"batch-{uuid4().hex[:12]}"
    request_id = f"req-{uuid4().hex[:12]}"
    cfg = MCPConfig.from_env()
    planned = mutation_summary

    import_data = _prepare_graph_import_data(graph_data, live_schema)
    # 真实写入仍走 HugeGraph-AI 的 graph-import HTTP 接口；MCP 只负责
    # schema 校验、安全确认和 payload 规范化，不直接导入 hugegraph-llm 流程。
    try:
        ai_result = post(
            "/graph-import",
            json={"data": json.dumps(import_data, sort_keys=True), "schema": cfg.graph},
        )
    except Exception as exc:
        return envelope_err(
            ErrorType.FLOW_EXECUTION_FAILED,
            f"Import execution failed: {exc}",
            details=_import_error_result(
                planned=planned, batch_id=batch_id, request_id=request_id, cfg=cfg
            ),
        )

    if not ai_result.get("ok"):
        # M5: 归一化 AI 错误响应，而非透传原始结果
        return envelope_err(
            ErrorType.FLOW_EXECUTION_FAILED,
            "HugeGraph-AI import returned an error.",
            details=_normalize_import_result(
                ai_result=None,
                planned=planned,
                batch_id=batch_id,
                request_id=request_id,
                cfg=cfg,
            ),
        )

    import_result = _unwrap_ai_payload(ai_result.get("data"))
    if isinstance(import_result, dict) and import_result.get("ok") is False:
        return envelope_err(
            ErrorType.FLOW_EXECUTION_FAILED,
            "HugeGraph-AI import returned an error in payload.",
            details=_normalize_import_result(
                ai_result=None,
                planned=planned,
                batch_id=batch_id,
                request_id=request_id,
                cfg=cfg,
            ),
        )

    # M5: 规范化导入结果
    normalized = _normalize_import_result(
        ai_result=import_result,
        planned=planned,
        batch_id=batch_id,
        request_id=request_id,
        cfg=cfg,
    )

    if normalized.get("status") != "success":
        return envelope_err(
            ErrorType.FLOW_EXECUTION_FAILED,
            "Graph data import did not complete successfully.",
            retryable=bool(normalized.get("retryable")),
            details=normalized,
            warnings=normalized.get("warnings", []),
        )

    return envelope_ok(normalized, warnings=normalized.get("warnings", []))


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


def _normalize_import_result(
    ai_result: Any,
    planned: dict[str, int],
    batch_id: str,
    request_id: str,
    cfg: MCPConfig,
) -> dict[str, Any]:
    """将 AI 导入结果规范化为 V1 标准格式。

    M5: success / partial / degraded / error
    """
    target = {
        "graph_url": cfg.url,
        "graph_name": cfg.graph,
        "graphspace": cfg.graphspace or "DEFAULT",
    }

    if ai_result is None or (
        isinstance(ai_result, dict) and ai_result.get("ok") is False
    ):
        return {
            "status": "error",
            "planned": planned,
            "written": {"vertices": 0, "edges": 0},
            "failed_items": [],
            "warnings": [],
            "retryable": True,
            "compensation_suggestions": ["Retry the import with dry_run first."],
            "target": target,
            "batch_id": batch_id,
            "request_id": request_id,
        }

    written, count_source = _extract_written_counts(ai_result, planned)
    failed_items = _extract_failed_items(ai_result)
    warnings = _extract_import_warnings(ai_result)
    remote_success = ai_result.get("success") if isinstance(ai_result, dict) else None
    remote_status = (
        str(ai_result.get("status")).lower()
        if isinstance(ai_result, dict) and ai_result.get("status") is not None
        else None
    )

    if written is None:
        if failed_items:
            written = {"vertices": 0, "edges": 0}
            status = "error" if remote_success is False else "degraded"
            warnings.append(
                "HugeGraph-AI import returned failures without explicit written counts."
            )
        elif remote_success is False:
            written = {"vertices": 0, "edges": 0}
            status = "error"
            warnings.append(
                "HugeGraph-AI import reported failure without explicit written counts."
            )
        else:
            written = {"vertices": 0, "edges": 0}
            status = (
                remote_status
                if remote_status in {"partial", "error", "degraded"}
                else "degraded"
            )
            warnings.append(
                "HugeGraph-AI import did not return explicit written counts; write outcome is unknown."
            )
    elif remote_success is False and (written["vertices"] > 0 or written["edges"] > 0):
        status = "partial"
    elif remote_success is False:
        status = "error"
    elif remote_status in {"partial", "error", "degraded"}:
        status = remote_status
    elif written == planned and not failed_items:
        status = "success"
    elif written["vertices"] > 0 or written["edges"] > 0:
        status = "partial"
    elif failed_items:
        status = "error"
    else:
        status = "degraded"

    if count_source == "total":
        warnings.append(
            "HugeGraph-AI import returned only a total written count; vertices/edges were estimated from the planned import order."
        )

    return {
        "status": status,
        "planned": planned,
        "written": written,
        "failed_items": failed_items,
        "warnings": warnings,
        "retryable": status in ("partial", "degraded", "error"),
        "compensation_suggestions": (
            ["Review failed_items and retry partial import."]
            if status in {"partial", "degraded", "error"}
            else []
        ),
        "target": target,
        "batch_id": batch_id,
        "request_id": request_id,
    }


def _extract_written_counts(
    ai_result: Any, planned: dict[str, int]
) -> tuple[dict[str, int] | None, str | None]:
    """从 AI 结果中提取写入计数。

    返回 (counts, source)，无法识别时 counts 为 None。source="total" 表示
    只有总数，vertices/edges 是按导入顺序估算出来的。
    """
    if not isinstance(ai_result, dict):
        return None, None

    # 常见的 AI 返回格式
    for key in ("written", "imported", "created", "result"):
        data = ai_result.get(key)
        if isinstance(data, dict):
            verts = data.get("vertices")
            if verts is None:
                verts = data.get("vertex_count")
            edges = data.get("edges")
            if edges is None:
                edges = data.get("edge_count")
            if verts is not None or edges is not None:
                return {
                    "vertices": _safe_int(verts),
                    "edges": _safe_int(edges),
                }, "explicit"

    # 顶层直接有计数
    verts = ai_result.get("vertices_written")
    if verts is None:
        verts = ai_result.get("vertex_count")
    edges = ai_result.get("edges_written")
    if edges is None:
        edges = ai_result.get("edge_count")
    if verts is not None or edges is not None:
        return {
            "vertices": _safe_int(verts),
            "edges": _safe_int(edges),
        }, "explicit"

    for key in ("inserted", "total_inserted", "created_count", "imported_count"):
        if key in ai_result:
            return _split_total_written(_safe_int(ai_result.get(key)), planned), "total"

    return None, None


def _safe_int(value: Any) -> int:
    if value in (None, ""):
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _split_total_written(total: int, planned: dict[str, int]) -> dict[str, int]:
    total = max(0, total)
    planned_vertices = max(0, int(planned.get("vertices", 0)))
    planned_edges = max(0, int(planned.get("edges", 0)))
    vertices = min(planned_vertices, total)
    edges = min(planned_edges, max(0, total - vertices))
    return {"vertices": vertices, "edges": edges}


def _extract_failed_items(ai_result: Any) -> list[dict[str, Any]]:
    """从 AI 结果中提取失败项，统一为对象数组。"""
    if not isinstance(ai_result, dict):
        return []

    for key in ("failed_items", "errors", "failures"):
        items = ai_result.get(key)
        if isinstance(items, list):
            normalized = []
            for item in items[:100]:
                if isinstance(item, dict):
                    normalized.append(item)
                elif isinstance(item, str):
                    normalized.append({"message": item})
                else:
                    normalized.append({"item": str(item)})
            return normalized

    return []


def _extract_import_warnings(ai_result: Any) -> list[str]:
    if not isinstance(ai_result, dict):
        return []
    raw_warnings = ai_result.get("warnings")
    if not isinstance(raw_warnings, list):
        return []
    return [str(warning) for warning in raw_warnings[:100]]


def _import_error_result(
    planned: dict[str, int],
    batch_id: str,
    request_id: str,
    cfg: MCPConfig,
) -> dict[str, Any]:
    """构建导入执行错误的规范化结果。"""
    return {
        "status": "error",
        "planned": planned,
        "written": {"vertices": 0, "edges": 0},
        "failed_items": [],
        "warnings": ["Import execution failed before any writes."],
        "retryable": True,
        "compensation_suggestions": ["Check HugeGraph-AI service availability."],
        "target": {
            "graph_url": cfg.url,
            "graph_name": cfg.graph,
            "graphspace": cfg.graphspace or "DEFAULT",
        },
        "batch_id": batch_id,
        "request_id": request_id,
    }
