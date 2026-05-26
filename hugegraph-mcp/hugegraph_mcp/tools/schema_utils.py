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

"""Shared HugeGraph schema parsing and normalization helpers."""

from typing import Any


__all__ = [
    "edge_schema_endpoint_label",
    "normalized_schema_summary",
    "primary_key_names",
    "property_names",
    "schema_name",
    "schema_payload",
]


def schema_name(item: Any) -> str | None:
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        name = item.get("name")
        return name if isinstance(name, str) else None
    return None


def property_names(properties: Any) -> set[str]:
    if not isinstance(properties, list):
        return set()
    return {name for prop in properties if (name := schema_name(prop))}


def primary_key_names(vertex_label: dict[str, Any]) -> list[str]:
    primary_keys = vertex_label.get("primary_keys")
    if primary_keys is None:
        primary_keys = vertex_label.get("primaryKeys")
    if not isinstance(primary_keys, list):
        return []
    return [name for pk in primary_keys if (name := schema_name(pk))]


def schema_payload(live_schema: dict[str, Any] | None) -> dict[str, Any] | None:
    # inspect_graph/get_live_schema 可能返回 {"schema": {...}}，也可能直接返回
    # schema 本体；共享入口统一解包，避免各工具各自判断格式。
    if not live_schema:
        return None
    raw = live_schema.get("schema") or live_schema
    return raw if isinstance(raw, dict) else None


def edge_schema_endpoint_label(edge_schema: dict[str, Any], endpoint: str) -> Any:
    if endpoint == "source":
        return edge_schema.get("source_label") or edge_schema.get("sourceLabel")
    return edge_schema.get("target_label") or edge_schema.get("targetLabel")


def _field_value(item: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in item:
            return item.get(name)
    return None


def _normalize_named_list(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    names = [name for value in values if (name := schema_name(value))]
    return sorted(names)


def _normalize_schema_items(
    items: Any,
    field_aliases: list[tuple[str, tuple[str, ...]]],
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    if not isinstance(items, list):
        return normalized

    for item in items:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if not isinstance(name, str):
            continue
        result: dict[str, Any] = {"name": name}
        for output_name, aliases in field_aliases:
            value = _field_value(item, *aliases)
            if value is None:
                continue
            if output_name in {
                "fields",
                "nullable_keys",
                "primary_keys",
                "properties",
            }:
                value = _normalize_named_list(value)
            result[output_name] = value
        normalized.append(result)

    return sorted(normalized, key=lambda value: value["name"])


def normalized_schema_summary(
    live_schema: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Return the security-relevant schema subset used for plan hashes."""
    raw = schema_payload(live_schema)
    if raw is None:
        return None

    # plan hash 只关心会影响写入语义的 schema 字段：
    # 属性类型、label 的属性/主键/端点、索引定义。id、状态、创建时间等
    # 元数据被刻意忽略，防止无关字段变化导致 confirm 阶段误拒。
    return {
        "propertykeys": _normalize_schema_items(
            raw.get("propertykeys"),
            [
                ("data_type", ("data_type", "dataType")),
                ("cardinality", ("cardinality",)),
            ],
        ),
        "vertexlabels": _normalize_schema_items(
            raw.get("vertexlabels"),
            [
                ("properties", ("properties",)),
                ("primary_keys", ("primary_keys", "primaryKeys")),
                ("nullable_keys", ("nullable_keys", "nullableKeys")),
            ],
        ),
        "edgelabels": _normalize_schema_items(
            raw.get("edgelabels"),
            [
                ("source_label", ("source_label", "sourceLabel")),
                ("target_label", ("target_label", "targetLabel")),
                ("properties", ("properties",)),
                ("nullable_keys", ("nullable_keys", "nullableKeys")),
                ("frequency", ("frequency",)),
            ],
        ),
        "indexlabels": _normalize_schema_items(
            raw.get("indexlabels"),
            [
                ("base_type", ("base_type", "baseType")),
                ("base_label", ("base_label", "baseLabel")),
                ("index_type", ("index_type", "indexType")),
                ("fields", ("fields",)),
                ("unique", ("unique",)),
            ],
        ),
    }
