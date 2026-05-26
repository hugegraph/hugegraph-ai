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

"""Graph data change plan execution.

Dry-run preview, write execution, pre-execution matched_count verification,
and plan hash computation.
"""

import hashlib
import json
from typing import Any

from hugegraph_mcp import gremlin_tools, schema_tools
from hugegraph_mcp.config import MCPConfig
from hugegraph_mcp.envelope import ErrorType, envelope_err, envelope_ok
from hugegraph_mcp.tools.graph_data_gremlin import (
    _edge_match_query,
    _source_vertex_match_query,
    _target_vertex_match_query,
    _vertex_match_query,
    _write_query,
)
from hugegraph_mcp.tools.graph_data_validate import (
    WRITE_OPS,
    ValidationError,
    _operations,
    _validation_error,
    validate_graph_change_plan,
)
from hugegraph_mcp.tools.schema_utils import normalized_schema_summary


# ---- Gremlin 执行辅助 ----


def _read_count(gremlin_query: str) -> dict[str, Any]:
    result = gremlin_tools.execute_gremlin_read(f"{gremlin_query}.count()")
    # execute_gremlin_read 已逐步迁移到统一 envelope，但这里仍兼容旧的
    # success=false 形状，避免低层工具格式差异破坏 dry-run 安全链。
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
    count = _extract_count_value(data)
    try:
        matched_count = int(count)
    except (TypeError, ValueError):
        return envelope_err(
            ErrorType.INVALID_GRAPH_DATA,
            "HugeGraph count query returned a non-numeric result.",
            details={"query": gremlin_query, "data": data},
        )
    return envelope_ok({"matched_count": matched_count})


def _extract_count_value(data: Any) -> Any:
    if isinstance(data, dict) and "data" in data:
        return _extract_count_value(data.get("data"))
    if isinstance(data, list):
        if not data:
            return 0
        return _extract_count_value(data[0])
    return data


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


# ---- Plan Hash 计算 — 防篡改校验 ----


def calculate_graph_change_plan_hash(
    change_plan: Any,
    graph: str | None = None,
    graphspace: str | None = None,
    schema_summary: dict[str, Any] | None = None,
    extra_hash_context: dict[str, Any] | None = None,
) -> str:
    """基于 change_plan + graph/schema 上下文计算确定性哈希。

    用于防篡改安全链：dry_run 返回 plan_hash，执行时校验匹配。
    """
    cfg = MCPConfig.from_env()
    payload: dict[str, Any] = {
        "change_plan": change_plan,
        "graph": cfg.graph if graph is None else graph,
        "graphspace": cfg.graphspace if graphspace is None else graphspace,
    }
    if schema_summary is not None:
        payload["schema_summary"] = schema_summary
    if extra_hash_context is not None:
        # SQL 导入等上游链路会把来源 SQL、映射配置放进额外上下文。
        # 同一个 change_plan 如果来自不同 SQL 或 mapping，不能复用确认 hash。
        payload["extra_hash_context"] = extra_hash_context
    encoded = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


# ---- 干跑预览 ----


def dry_run_graph_change_plan(
    change_plan: Any,
    live_schema: dict[str, Any],
    extra_hash_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """干跑 — 校验 + 预览每个操作的影响（matched_count），不执行写入。

    update/delete 操作通过只读 Gremlin 查询验证 matched_count==1，
    delete_vertex cascade=false 时检查关联边。
    """
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
            # create 操作没有“必须命中唯一旧数据”的要求；真正的 schema/payload
            # 合法性已经在 validate 阶段检查，因此 dry-run 只展示计划。
            item["matched_count"] = None
            preview.append(item)
            continue

        if op in {"update_edge", "delete_edge"}:
            # 边的 update/delete 先分别确认两个端点唯一，再确认边本身唯一。
            # 这样错误能定位到 source/target，而不是只得到一条模糊的边匹配失败。
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
            # 默认禁止删除带边的顶点，避免 HugeGraph 侧级联行为造成不可预期的数据损失。
            # 用户需要先显式删除关联边，再删除顶点。
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
                # 目前 cascade=true 只做关联边预览，不执行级联删除。
                # 这是有意的保守策略：真实级联删除需要单独的产品决策和测试覆盖。
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
            schema_summary=normalized_schema_summary(live_schema),
            extra_hash_context=extra_hash_context,
        ),
        "mutation_summary": _mutation_summary(operations),
        "preview": preview,
        "warnings": validation.get("warnings", []),
    }


# ---- 执行 — 写入前再次校验 matched_count ----


def execute_graph_change_plan(change_plan: Any) -> dict[str, Any]:
    """执行变更计划 — 写入前对每个操作再次校验 matched_count。

    防止 dry_run 和 execute 之间状态变化导致的误操作。
    """
    operations = _operations(change_plan)
    results: list[dict[str, Any]] = []
    for idx, operation in enumerate(operations):
        op = str(operation.get("op") or operation.get("type"))
        if op in WRITE_OPS:
            # 执行前再次读取 matched_count，处理 dry-run 和 confirm 之间图状态变化
            # 的 TOCTOU 风险；只要匹配不再唯一，就拒绝写入。
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
            # 删除顶点后立即反查，确保 HugeGraph 已经实际移除目标。
            # 这能捕获后端静默失败或异步状态异常，而不是只信任写接口返回。
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


# ---- Live Schema 获取 ----


def _fetch_live_schema() -> dict[str, Any] | None:
    try:
        return schema_tools.get_live_schema()
    except Exception:
        return None
