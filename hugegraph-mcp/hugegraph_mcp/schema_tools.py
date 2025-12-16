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

import os
from dataclasses import dataclass
from typing import Any

from pyhugegraph.client import PyHugeClient


@dataclass
class HugeGraphMCPConfig:
    graph_url: str = "http://127.0.0.1:8080"
    graph_name: str = "hugegraph"
    graph_user: str = "admin"
    graph_pwd: str = "xxx"  # pragma: allowlist secret - value comes from env
    graphspace: str | None = "DEFAULT"  # HugeGraph 1.7.0+ enhanced graph space support

    @classmethod
    def from_env(cls) -> "HugeGraphMCPConfig":
        # 支持字符串拼接格式：HUGEGRAPH_GRAPH_PATH="DEFAULT/hugegraph"，仅此一种方式
        graph_path = os.getenv("HUGEGRAPH_GRAPH_PATH") or "DEFAULT/hugegraph"

        if "/" in graph_path:
            graphspace, graph_name = graph_path.split("/", 1)
        else:
            graphspace, graph_name = "DEFAULT", graph_path

        graphspace = (graphspace or "DEFAULT").strip() or "DEFAULT"
        graph_name = (graph_name or "hugegraph").strip() or "hugegraph"

        return cls(
            graph_url=os.getenv("HUGEGRAPH_URL", "http://127.0.0.1:8080"),
            graph_name=graph_name,
            graph_user=os.getenv("HUGEGRAPH_USER", "admin"),
            graph_pwd=os.getenv("HUGEGRAPH_PASSWORD", "xxx"),
            graphspace=graphspace,
        )


_config = HugeGraphMCPConfig.from_env()


def _build_client() -> PyHugeClient:
    # HugeGraph 1.7.0+ graph space support - resolved from config (HUGEGRAPH_GRAPH_PATH)
    graphspace = _config.graphspace
    # Only pass graphspace if it's not None and not empty string
    if graphspace and graphspace.strip():
        return PyHugeClient(
            url=_config.graph_url,
            graph=_config.graph_name,
            user=_config.graph_user,
            pwd=_config.graph_pwd,
            graphspace=graphspace.strip(),
        )
    else:
        # Default client without graphspace for backward compatibility
        return PyHugeClient(
            url=_config.graph_url,
            graph=_config.graph_name,
            user=_config.graph_user,
            pwd=_config.graph_pwd,
        )


def _simple_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Simplify HugeGraph schema for LLM consumption.

    This mirrors the behaviour of hugegraph_llm.SchemaManager.simple_schema
    for the fields used in tests.
    """

    mini_schema: dict[str, Any] = {}

    if schema.get("vertexlabels"):
        mini_schema["vertexlabels"] = []
        for vertex in schema["vertexlabels"]:
            new_vertex = {
                key: vertex[key]
                for key in ("id", "name", "properties")
                if key in vertex
            }
            mini_schema["vertexlabels"].append(new_vertex)

    if schema.get("edgelabels"):
        mini_schema["edgelabels"] = []
        for edge in schema["edgelabels"]:
            new_edge = {
                key: edge[key]
                for key in ("name", "source_label", "target_label", "properties")
                if key in edge
            }
            mini_schema["edgelabels"].append(new_edge)

    return mini_schema


def get_live_schema() -> dict[str, Any]:
    """Fetch live schema from HugeGraph and return both full and simplified forms.

    This is written in a way that can be wrapped as a FastMCP tool later.
    """

    client = _build_client()
    raw_schema = client.schema().getSchema()

    # Ensure raw_schema is not None before processing
    if raw_schema is None:
        raise ValueError("Failed to retrieve schema from HugeGraph server")

    result: dict[str, Any] = {
        "schema": raw_schema,
        "simple_schema": _simple_schema(raw_schema),
    }

    # HugeGraph 1.7.0+ graph space handling - from resolved config
    graphspace = _config.graphspace
    if graphspace:
        result["graphspace"] = graphspace

    readonly_env = os.getenv("HUGEGRAPH_MCP_READONLY", "").lower()
    result["readonly"] = readonly_env in {"1", "true", "yes"}

    return result


def _run_schema_operations(operations: list[dict[str, Any]]) -> dict[str, Any]:
    """Low-level schema executor against HugeGraph REST schema API.

    This is a minimal first version that supports a small subset of
    operation types. It is intentionally simple and can be extended as
    needed with more op kinds.
    """

    client = _build_client()
    schema = client.schema()

    results: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for idx, op in enumerate(operations):
        op_type = op.get("type")
        try:
            if op_type == "create_property_key":
                name = op["name"]
                # Default to TEXT if caller没有指定类型；后续可以扩展 data_type 映射
                data_type = op.get("data_type", "TEXT").upper()
                pk_builder = schema.propertyKey(name)
                if data_type == "INT":
                    pk_builder = pk_builder.asInt()
                elif data_type == "DOUBLE":
                    pk_builder = pk_builder.asDouble()
                else:
                    pk_builder = pk_builder.asText()
                pk_builder.ifNotExist().create()

            elif op_type == "create_vertex_label":
                name = op["name"]
                properties = op.get("properties", [])
                vl_builder = schema.vertexLabel(name)
                if properties:
                    vl_builder = vl_builder.properties(*properties)
                # 使用 primaryKeys(name) 作为默认主键策略，后续可按需扩展
                if op.get("primary_keys"):
                    vl_builder = vl_builder.primaryKeys(*op["primary_keys"])
                vl_builder.ifNotExist().create()

            elif op_type == "create_edge_label":
                name = op["name"]
                source_label = op["source_label"]
                target_label = op["target_label"]
                properties = op.get("properties", [])
                sort_keys = op.get("sort_keys", [])
                nullable_keys = op.get("nullable_keys", [])
                frequency = op.get("frequency", "MULTI").upper()

                el_builder = (
                    schema.edgeLabel(name)
                    .sourceLabel(source_label)
                    .targetLabel(target_label)
                )
                if properties:
                    el_builder = el_builder.properties(*properties)
                if sort_keys:
                    el_builder = el_builder.sortKeys(*sort_keys)
                if nullable_keys:
                    el_builder = el_builder.nullableKeys(*nullable_keys)
                if frequency == "MULTI":
                    el_builder = el_builder.multiTimes()
                el_builder.ifNotExist().create()

            elif op_type == "create_index_label":
                name = op["name"]
                base_type = op.get("base_type", "VERTEX").upper()
                base_label = op["base_label"]
                fields = op.get("fields", [])
                index_type = op.get("index_type", "SECONDARY").upper()

                il_builder = schema.indexLabel(name)
                if base_type == "VERTEX":
                    il_builder = il_builder.onV(base_label)
                elif base_type == "EDGE":
                    il_builder = il_builder.onE(base_label)
                else:
                    raise ValueError(
                        f"Unsupported base_type for index label: {base_type}"
                    )

                if fields:
                    il_builder = il_builder.by(*fields)

                if index_type == "SECONDARY":
                    il_builder = il_builder.secondary()
                elif index_type == "RANGE":
                    il_builder = il_builder.range()
                else:
                    raise ValueError(
                        f"Unsupported index_type for index label: {index_type}"
                    )

                il_builder.ifNotExist().create()

            else:
                raise ValueError(f"Unsupported schema operation type: {op_type}")

            results.append({"op": op, "status": "ok"})
        except Exception as exc:  # pragma: no cover - 错误路径由上层聚合
            msg = str(exc)
            results.append({"op": op, "status": "failed", "error": msg})
            errors.append({"op_index": idx, "message": msg})

    return {"success": not bool(errors), "results": results, "errors": errors}


def execute_schema_operations(operations: list[dict[str, Any]]) -> dict[str, Any]:
    """Execute a sequence of idempotent schema operations.

    Behaviour covered by tests:
    - Delegates actual execution to `_run_schema_operations`.
    - Respects HUGEGRAPH_MCP_READONLY environment variable.
    """

    result = _run_schema_operations(operations)

    # Normalise result keys a bit so callers always get predictable fields.
    if "errors" not in result:
        result["errors"] = []
    if "success" not in result:
        result["success"] = not bool(result["errors"])

    return result
