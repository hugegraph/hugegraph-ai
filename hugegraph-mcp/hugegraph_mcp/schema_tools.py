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

"""HugeGraph Schema 操作层 — 底层 schema CRUD 和设计指导。

get_live_schema() 从 HugeGraph 拉取全量 schema 并生成 LLM 精简版，
execute_schema_operations() 执行幂等 schema 创建，
design_schema() 提供链式思维引导的 schema 设计框架。
"""

from typing import Any

from pyhugegraph.client import PyHugeClient

from hugegraph_mcp.config import MCPConfig
from hugegraph_mcp.envelope import ErrorType, envelope_err
from hugegraph_mcp.guard import Capability, guard
from hugegraph_mcp.hugegraph_client import build_hugegraph_client

_config = MCPConfig.from_env()

ALLOWED_SCHEMA_OPERATION_TYPES = frozenset(
    {
        "create_property_key",
        "create_vertex_label",
        "create_edge_label",
        "create_index_label",
    }
)


def _is_delete_schema_operation(op_type: Any) -> bool:
    lowered = str(op_type).lower()
    return "delete" in lowered or "drop" in lowered


def _build_client() -> PyHugeClient:
    return build_hugegraph_client(_config, client_cls=PyHugeClient)


def _simple_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """精简 schema 供 LLM 消费 — 去掉冗余字段，只保留 name/properties/source_label/target_label。

    与 hugegraph_llm.SchemaManager.simple_schema 行为一致。
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
    """从 HugeGraph 拉取活跃 schema，同时返回原始版和 LLM 精简版。

    返回: {schema, simple_schema, graphspace?, readonly}
    """

    client = _build_client()
    raw_schema = client.schema().getSchema()

    if raw_schema is None:
        raise ValueError("Failed to retrieve schema from HugeGraph server")

    result: dict[str, Any] = {
        "schema": raw_schema,
        "simple_schema": _simple_schema(raw_schema),
    }

    graphspace = _config.graphspace
    if graphspace:
        result["graphspace"] = graphspace

    result["readonly"] = MCPConfig.from_env().is_readonly()

    return result


def _run_schema_operations(operations: list[dict[str, Any]]) -> dict[str, Any]:
    """底层 schema 执行器 — 对 HugeGraph REST schema API 的最小封装。

    支持 create_property_key / create_vertex_label / create_edge_label / create_index_label，
    使用 ifNotExist() 保证幂等，拒绝 delete/drop 操作。
    """

    client = _build_client()
    schema = client.schema()

    results: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for idx, op in enumerate(operations):
        op_type = op.get("type")
        try:
            if _is_delete_schema_operation(op_type):
                raise ValueError(
                    f"Delete/drop schema operation is not supported: {op_type}"
                )
            if op_type not in ALLOWED_SCHEMA_OPERATION_TYPES:
                raise ValueError(f"Unsupported schema operation type: {op_type}")

            if op_type == "create_property_key":
                name = op["name"]
                # 未指定 data_type 时默认 TEXT
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

            results.append({"op": op, "status": "ok"})
        except Exception as exc:  # pragma: no cover - errors are aggregated above
            msg = str(exc)
            results.append({"op": op, "status": "failed", "error": msg})
            errors.append({"op_index": idx, "message": msg})

    return {"success": not bool(errors), "results": results, "errors": errors}


def execute_schema_operations(operations: list[dict[str, Any]]) -> dict[str, Any]:
    """执行一组幂等 schema 操作 — 带 readonly 守卫和 delete 预检。

    readonly 模式下拒绝执行，delete 操作在预检阶段直接拒绝。
    """

    violation = guard(Capability.SCHEMA_WRITE)
    if violation is not None:
        return violation

    for idx, operation in enumerate(operations):
        op_type = operation.get("type") if isinstance(operation, dict) else None
        if _is_delete_schema_operation(op_type):
            return envelope_err(
                ErrorType.SCHEMA_MISMATCH,
                f"Delete/drop schema operation is not supported: {op_type}",
                details={"op_index": idx, "operation": operation},
            )

    result = _run_schema_operations(operations)

    if "errors" not in result:
        result["errors"] = []
    if "success" not in result:
        result["success"] = not bool(result["errors"])

    return result


def design_schema(
    thought: str,
    thought_number: int,
    total_thoughts: int = 4,
    next_thought_needed: bool = True,
    is_revision: bool = False,
    revision_of: int | None = None,
) -> dict:
    """Schema 设计引导工具 — 参考 Sequential Thinking 模式。

    HugeGraph 使用 schema-based 图模型，数据写入前必须先定义 PropertyKeys、
    VertexLabels、EdgeLabels、IndexLabels。本函数提供分步引导框架。

    【最佳实践】
    1. 先定义 PropertyKeys — 所有属性必须在 VertexLabel/EdgeLabel 中预定义
    2. 选择合适的 DataType (TEXT/INT/DATE/DOUBLE) 和 Cardinality (SINGLE/SET/LIST)
    3. VertexLabel 需指定 primaryKeys 用于顶点唯一标识
    4. EdgeLabel 需指定 sourceLabel 和 targetLabel
    5. EdgeLabel 的 frequency 可选 SINGLE 或 MULTIPLE
    6. 使用 nullableKeys 允许属性为空
    7. 为常用查询字段创建 IndexLabels (secondary/range/search)
    """

    return {
        "thought_number": thought_number,
        "total_thoughts": total_thoughts,
        "next_thought_needed": next_thought_needed,
    }
