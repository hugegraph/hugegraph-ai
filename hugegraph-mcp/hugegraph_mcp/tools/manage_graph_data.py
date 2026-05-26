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

manage_graph_data() keeps the CRUD safety-chain entry point while validation,
Gremlin generation, and execution helpers live in focused modules.
"""

from typing import Any

from hugegraph_mcp import gremlin_tools, schema_tools
from hugegraph_mcp.envelope import ErrorType, envelope_err, envelope_ok
from hugegraph_mcp.guard import Capability, guard
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
    _update_edge_query,
    _update_vertex_query,
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
    "_update_edge_query",
    "_update_vertex_query",
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
    extra_hash_context: dict[str, Any] | None = None,
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
