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


"""Graph data management orchestration layer.

manage_graph_data() keeps the V1 import/delete safety-chain entry point while
validation, Gremlin generation, and execution helpers live in focused modules.
"""

from typing import Any

from hugegraph_mcp import gremlin_tools, schema_tools
from hugegraph_mcp.envelope import ErrorType, envelope_err, envelope_ok
from hugegraph_mcp.guard import Capability, guard
from hugegraph_mcp.plan_hash import (
    build_plan_context,
    compute_payload_digest,
    compute_plan_hash,
    verify_plan_hash,
)
from hugegraph_mcp.tools import ingest_graph_data
from hugegraph_mcp.tools.graph_data_execute import (
    _extract_count_value,
    _fetch_live_schema,
    _mutation_summary,
    _read_count,
    _read_values,
    calculate_graph_change_plan_hash,
    dry_run_graph_change_plan,
    execute_graph_change_plan,
)
from hugegraph_mcp.tools.graph_data_gremlin import (
    _create_edge_query,
    _create_vertex_query,
    _delete_edge_query,
    _delete_vertex_query,
    _edge_match_query,
    _g,
    _has_steps,
    _source_vertex_match_query,
    _target_vertex_match_query,
    _vertex_match_query,
    _write_query,
)
from hugegraph_mcp.tools.graph_data_mapping import (
    GraphChangePlan,
    _change_plan_from_operations,
    graph_data_to_change_plan,
)
from hugegraph_mcp.tools.graph_data_validate import (
    ALLOWED_OPS,
    EDGE_OPS,
    MODE_OPS,
    VERTEX_OPS,
    WRITE_OPS,
    ValidationError,
    _edge_labels,
    _edge_schema_endpoint_label,
    _operations,
    _primary_key_names,
    _property_names,
    _schema_name,
    _schema_payload,
    _schema_summary,
    _validate_field_map,
    _validate_mode_operations,
    _validate_primary_key_match,
    _validation_error,
    _vertex_labels,
    validate_graph_change_plan,
)

# 这里保留一批下划线 helper 的 re-export，是为了兼容既有测试和旧调用方。
# 新代码应优先直接依赖 graph_data_* 子模块，避免继续扩大这个兼容面。
__all__ = [
    "ALLOWED_OPS",
    "EDGE_OPS",
    "GraphChangePlan",
    "MODE_OPS",
    "VERTEX_OPS",
    "ValidationError",
    "WRITE_OPS",
    "_change_plan_from_operations",
    "_create_edge_query",
    "_create_vertex_query",
    "_delete_edge_query",
    "_delete_vertex_query",
    "_edge_labels",
    "_edge_match_query",
    "_edge_schema_endpoint_label",
    "_extract_count_value",
    "_fetch_live_schema",
    "_g",
    "_has_steps",
    "_mutation_summary",
    "_operations",
    "_primary_key_names",
    "_property_names",
    "_read_count",
    "_read_values",
    "_schema_name",
    "_schema_payload",
    "_schema_summary",
    "_source_vertex_match_query",
    "_target_vertex_match_query",
    "_validate_field_map",
    "_validate_mode_operations",
    "_validate_primary_key_match",
    "_validation_error",
    "_vertex_labels",
    "_vertex_match_query",
    "_write_query",
    "calculate_graph_change_plan_hash",
    "dry_run_graph_change_plan",
    "execute_graph_change_plan",
    "gremlin_tools",
    "graph_data_to_change_plan",
    "manage_graph_data",
    "schema_tools",
    "validate_graph_change_plan",
]


# ---- 统一入口 ----


def manage_graph_data(
    mode: str,
    graph_data: dict[str, Any] | None = None,
    change_plan: dict[str, Any] | list[dict[str, Any]] | None = None,
    dry_run: bool = True,
    confirm: bool = False,
    plan_hash: str | None = None,
    nonce: str | None = None,
    expires_at: float | None = None,
    extra_hash_context: dict[str, Any] | None = None,
    plan_tool_name: str = "manage_graph_data",
) -> dict[str, Any]:
    """统一图数据管理入口。

    安全链：validate → dry_run → confirm check → plan_hash match → execute
    每个环节失败均返回结构化错误，不抛异常。
    """
    if mode == "import":
        if graph_data is None:
            return envelope_err(
                "VALIDATION_ERROR",
                "graph_data is required for mode='import'",
            )
        # import 模式以用户友好的 graph_data 为输入，但后续安全链统一处理
        # change_plan；这样 import/delete 能共享 dry-run、hash 和执行逻辑。
        plan = graph_data_to_change_plan(graph_data)
    elif mode == "delete":
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
            f"Unknown mode: {mode!r}. Use 'import' or 'delete'.",
            details={"mode": mode},
        )

    # mode 和 op 的关系是第一道边界：import 只能 create，delete
    # 只能执行对应操作，避免用户把高风险操作塞进低风险入口。
    mode_validation = _validate_mode_operations(mode, plan)
    if not mode_validation["valid"]:
        return envelope_err(
            ErrorType.INVALID_GRAPH_DATA,
            "Graph change plan contains operations outside the selected mode.",
            details={"errors": mode_validation["errors"]},
        )

    # 写入前必须读取 live schema。这里不允许在 schema 缺失时降级执行，
    # 因为主键、端点和属性合法性都依赖当前图的真实 schema。
    live_schema = _fetch_live_schema()
    if live_schema is None:
        return envelope_err(
            ErrorType.CONNECTION_FAILED,
            "Cannot read live schema from HugeGraph Server. Schema validation is required before graph data changes.",
            suggestion="Ensure HugeGraph Server is running and accessible, then retry.",
            retryable=True,
        )

    if mode == "import" and graph_data is not None:
        # import 额外校验原始 graph_data，覆盖 change_plan 不容易表达的规则：
        # 顶点主键是否齐全、边端点是否能解析、payload 内部是否有重复身份。
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

    dry_run_result = dry_run_graph_change_plan(
        plan, live_schema, extra_hash_context=extra_hash_context
    )
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

    plan_context, _ = _build_manage_graph_data_plan_context(
        tool_name=plan_tool_name,
        mode=mode,
        plan=plan,
        live_schema=live_schema,
        nonce=nonce,
        extra_hash_context=extra_hash_context,
    )
    target_bound_hash = compute_plan_hash(plan_context)
    dry_run_result["plan_hash"] = target_bound_hash
    dry_run_result["plan_context"] = _plan_context_payload(plan_context)

    if dry_run:
        return envelope_ok(dry_run_result, warnings=dry_run_result.get("warnings", []))

    # readonly 需要在执行期再检查，不能只依赖 server 注册时隐藏写工具；
    # 长运行进程和测试中都可能动态切换配置或直接调用内部函数。
    violation = guard(Capability.DATA_WRITE)
    if violation is not None:
        return violation

    if not confirm:
        return envelope_err(
            ErrorType.CONFIRM_REQUIRED,
            "Graph data changes require confirm=True after a dry_run.",
            suggestion="Run dry_run=True, review preview and warnings, then pass confirm=True with the returned plan_hash.",
        )

    schema_summary = _schema_summary(live_schema)
    valid, error_type, details = verify_plan_hash(
        submitted_hash=plan_hash,
        tool_name=plan_tool_name,
        mode=mode,
        payload_digest=_manage_graph_data_payload_digest(
            plan,
            extra_hash_context=extra_hash_context,
        ),
        schema_hash=compute_payload_digest(schema_summary) if schema_summary else None,
        nonce=nonce,
        expires_at=expires_at,
        extra_context={"extra_hash_context": extra_hash_context or {}},
    )
    if not valid:
        message = (
            "Graph data change plan has expired."
            if error_type == ErrorType.PLAN_EXPIRED
            else "Provided plan_hash does not match the current graph data change plan."
        )
        return envelope_err(
            error_type or ErrorType.PLAN_HASH_MISMATCH,
            message,
            suggestion="Run dry_run=True again and use the returned plan_hash.",
            details=details,
        )

    execute_result = execute_graph_change_plan(plan)
    if isinstance(execute_result, dict) and execute_result.get("ok") is False:
        return envelope_err(
            execute_result["error"]["type"],
            execute_result["error"]["message"],
            suggestion=execute_result["error"].get("suggestion"),
            retryable=execute_result["error"].get("retryable", False),
            details=_normalize_execute_result(execute_result, plan),
        )

    normalized = _normalize_execute_result(execute_result, plan)
    if normalized.get("success") is False or normalized.get("status") in {
        "partial",
        "error",
        "degraded",
    }:
        return envelope_err(
            ErrorType.FLOW_EXECUTION_FAILED,
            "Graph change execution did not complete successfully.",
            retryable=bool(normalized.get("retryable")),
            details=normalized,
            warnings=normalized.get("warnings", []),
        )

    return envelope_ok(normalized)


def _build_manage_graph_data_plan_context(
    *,
    tool_name: str,
    mode: str,
    plan: Any,
    live_schema: dict[str, Any],
    nonce: str | None,
    extra_hash_context: dict[str, Any] | None,
):
    schema_summary = _schema_summary(live_schema)
    return build_plan_context(
        tool_name=tool_name,
        mode=mode,
        payload_digest=_manage_graph_data_payload_digest(
            plan,
            extra_hash_context=extra_hash_context,
        ),
        schema_hash=compute_payload_digest(schema_summary) if schema_summary else None,
        nonce=nonce,
        extra_context={"extra_hash_context": extra_hash_context or {}},
    )


def _manage_graph_data_payload_digest(
    plan: Any,
    *,
    extra_hash_context: dict[str, Any] | None,
) -> str:
    payload: dict[str, Any] = {"change_plan": plan}
    if extra_hash_context is not None:
        payload["extra_hash_context"] = extra_hash_context
    return compute_payload_digest(payload)


def _plan_context_payload(plan_context) -> dict[str, Any]:
    return {
        "nonce": plan_context.nonce,
        "expires_at": plan_context.expires_at,
        "graph_url": plan_context.graph_url,
        "graph_name": plan_context.graph_name,
        "graphspace": plan_context.graphspace,
        "principal": plan_context.principal,
        "readonly": plan_context.readonly,
    }


def _normalize_execute_result(execute_result: Any, plan: Any) -> dict[str, Any]:
    operations = _operations(plan)
    planned = _mutation_summary(operations)

    if isinstance(execute_result, dict) and execute_result.get("ok") is False:
        return {
            "status": "error",
            "success": False,
            "planned": planned,
            "written": {},
            "failed_items": [execute_result["error"]],
            "warnings": execute_result.get("warnings", []),
            "retryable": execute_result["error"].get("retryable", False),
            "compensation_suggestions": [],
            "results": [],
            "mutation_summary": planned,
        }

    if not isinstance(execute_result, dict):
        return {
            "status": "degraded",
            "success": False,
            "planned": planned,
            "written": {},
            "failed_items": [{"result": execute_result}],
            "warnings": ["Graph change execution returned an unrecognized result."],
            "retryable": True,
            "compensation_suggestions": ["Inspect graph state before retrying."],
            "results": [],
            "mutation_summary": planned,
        }

    raw_results = execute_result.get("results")
    results = raw_results if isinstance(raw_results, list) else []
    failed_items = execute_result.get("failed_items")
    if not isinstance(failed_items, list):
        failed_items = []

    if (
        execute_result.get("success") is True
        and len(results) == len(operations)
        and not failed_items
    ):
        status = "success"
    elif results:
        status = "partial"
    elif execute_result.get("success") is False or failed_items:
        status = "error"
    else:
        status = "degraded"

    written = _mutation_summary(
        [operation for operation, _result in zip(operations, results, strict=False)]
    )
    return {
        "status": status,
        "success": status == "success",
        "planned": planned,
        "written": written,
        "failed_items": failed_items,
        "warnings": execute_result.get("warnings", []),
        "retryable": status in ("partial", "degraded", "error"),
        "compensation_suggestions": (
            ["Inspect graph state before retrying remaining operations."]
            if status in ("partial", "degraded")
            else []
        ),
        "results": results,
        "mutation_summary": execute_result.get("mutation_summary", planned),
    }
