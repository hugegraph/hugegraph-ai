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

"""FastMCP 服务器入口 — MCP 工具注册和轻量 mode 路由。

每个 @mcp.tool() 装饰的函数就是一个对外暴露的 MCP 工具。
server.py 只负责参数校验和 mode 分发，具体业务逻辑委托给 tools/ 下的模块。
"""

import logging
import logging.handlers
import os
import time
from typing import Any

# ---- 启动时 patch：阻止 pyhugegraph 模块级日志初始化写入文件 ----
# pyhugegraph 在 import 时会创建 RotatingFileHandler 写入 'logs/' 目录，
# 在 MCP stdio 模式下这会破坏 JSON 协议流，因此拦截 makedirs 和 RotatingFileHandler。

_original_makedirs = os.makedirs


def _safe_makedirs(name, mode=0o777, exist_ok=False):
    if _is_logs_dir(name):
        return None
    return _original_makedirs(name, mode, exist_ok)


def _is_logs_dir(name) -> bool:
    try:
        path = os.fspath(name)
    except TypeError:
        return False
    return os.path.basename(os.path.normpath(path)).lower() == "logs"


_OriginalRotatingFileHandler = logging.handlers.RotatingFileHandler


class _NoOpFileHandler(logging.NullHandler):
    """无操作日志处理器 — 用于禁用文件日志记录。"""

    def __init__(self, *args, **kwargs):
        super().__init__()


def _patched_rotating_handler(filename, *args, **kwargs):
    if _is_logs_file(filename):
        return _NoOpFileHandler()
    return _OriginalRotatingFileHandler(filename, *args, **kwargs)


def _is_logs_file(filename) -> bool:
    try:
        path = os.path.normpath(os.fspath(filename))
    except TypeError:
        return False
    return any(part.lower() == "logs" for part in path.split(os.sep))


logging.handlers.RotatingFileHandler = _patched_rotating_handler

os.makedirs = _safe_makedirs

try:
    # ---- patch 作用域内，安全导入依赖 pyhugegraph 的模块 ----
    from fastmcp import FastMCP

    from hugegraph_mcp.config import MCPConfig
    from hugegraph_mcp.envelope import ErrorType, envelope_err
    from hugegraph_mcp.gremlin_tools import execute_gremlin_read, execute_gremlin_write
    from hugegraph_mcp.guard import Capability
    from hugegraph_mcp.tools.extract_graph_data import extract_graph_data
    from hugegraph_mcp.tools.generate_gremlin import generate_gremlin
    from hugegraph_mcp.tools.inspect_graph import inspect_graph
    from hugegraph_mcp.tools.manage_graph_data import manage_graph_data
    from hugegraph_mcp.tools.manage_schema import manage_schema
    from hugegraph_mcp.tools.refresh_vid_embeddings import refresh_vid_embeddings
finally:
    os.makedirs = _original_makedirs
    logging.handlers.RotatingFileHandler = _OriginalRotatingFileHandler

READONLY = MCPConfig.from_env().is_readonly()

mcp = FastMCP("HugeGraph MCP")


def _align_public_tool_envelope(
    result: dict[str, Any],
    *,
    tool_name: str,
    duration_ms: float,
) -> dict[str, Any]:
    """Add public wrapper metadata without changing the inner tool payload."""
    aligned = dict(result)
    meta = dict(aligned.get("meta") or {})
    meta.setdefault("duration_ms", duration_ms)
    aligned["meta"] = meta

    if aligned.get("ok") is False and isinstance(aligned.get("error"), dict):
        error = dict(aligned["error"])
        error["source"] = tool_name
        aligned["error"] = error

    return aligned


def _call_public_tool(tool_name: str, func, *args, **kwargs) -> dict[str, Any]:
    start = time.perf_counter()
    try:
        result = func(*args, **kwargs)
    except Exception as exc:
        return envelope_err(
            ErrorType.FLOW_EXECUTION_FAILED,
            f"{tool_name} failed: {exc!s}",
            source=tool_name,
            details={"tool": tool_name},
            duration_ms=(time.perf_counter() - start) * 1000.0,
        )
    return _align_public_tool_envelope(
        result,
        tool_name=tool_name,
        duration_ms=(time.perf_counter() - start) * 1000.0,
    )


def _is_admin_mode_enabled() -> bool:
    return MCPConfig.from_env().admin_mode


def _admin_gate(tool_name: str, *, requires_write: bool = False) -> dict | None:
    """Return FEATURE_DISABLED envelope if admin mode is not enabled, else None."""
    if not _is_admin_mode_enabled():
        enable_env = {"admin_mode": "HUGEGRAPH_MCP_ADMIN_MODE"}
        suggestion = f"Set HUGEGRAPH_MCP_ADMIN_MODE=true to enable {tool_name}."
        if requires_write:
            enable_env["readonly"] = "HUGEGRAPH_MCP_READONLY"
            suggestion = (
                f"Set HUGEGRAPH_MCP_ADMIN_MODE=true and HUGEGRAPH_MCP_READONLY=false "
                f"to enable {tool_name}."
            )
        return envelope_err(
            ErrorType.FEATURE_DISABLED,
            f"{tool_name} is disabled by default in V1. Enable with HUGEGRAPH_MCP_ADMIN_MODE=true.",
            suggestion=suggestion,
            source=tool_name,
            details={"tool": tool_name, "enable_env": enable_env},
        )

    if requires_write and MCPConfig.from_env().is_readonly():
        return envelope_err(
            ErrorType.READONLY_VIOLATION,
            f"{tool_name} requires HUGEGRAPH_MCP_READONLY=false.",
            suggestion=(
                "Set HUGEGRAPH_MCP_ADMIN_MODE=true and HUGEGRAPH_MCP_READONLY=false "
                "before retrying this admin write tool."
            ),
            source=tool_name,
            details={
                "tool": tool_name,
                "required_env": {
                    "HUGEGRAPH_MCP_ADMIN_MODE": "true",
                    "HUGEGRAPH_MCP_READONLY": "false",
                },
            },
            readonly=True,
        )
    return None


# ========== 工具 1：检视图状态和 schema ==========


@mcp.tool()
def inspect_graph_tool(include_raw_schema: bool = False) -> dict:
    """检视 HugeGraph 服务器状态、schema 摘要、点边计数和 AI 状态。

    推荐作为连接后第一个调用的工具。
    """
    return _call_public_tool(
        "inspect_graph_tool",
        inspect_graph,
        include_raw_schema=include_raw_schema,
    )


# ========== V1 稳定工具 ==========


@mcp.tool()
def generate_gremlin_tool(
    query: str,
    execute: bool = False,
) -> dict:
    """V1 稳定工具：自然语言 → Gremlin 生成。

    默认不执行（execute=false），返回生成的 Gremlin 查询。
    设置 execute=true 可执行生成的只读 Gremlin。
    """
    return _call_public_tool(
        "generate_gremlin_tool",
        generate_gremlin,
        query=query,
        execute=execute,
    )


@mcp.tool()
def execute_gremlin_read_tool(gremlin_query: str) -> dict:
    """V1 稳定工具：执行只读 Gremlin 遍历查询。

    经过 GremlinPolicy 安全检查后执行。
    """
    return _call_public_tool(
        "execute_gremlin_read_tool",
        execute_gremlin_read,
        gremlin_query,
    )


@mcp.tool()
def extract_graph_data_tool(
    text: str,
    graph_schema: dict | None = None,
    example_prompt: str | None = None,
) -> dict:
    """V1 稳定工具：自然语言文本 → 候选 graph_data（不写入）。

    返回提取的顶点和边数据，供后续导入使用。
    graph_schema 可传入 HugeGraph schema；为空时使用当前图名作为 schema 引用。
    """
    return _call_public_tool(
        "extract_graph_data_tool",
        extract_graph_data,
        text=text,
        schema=graph_schema,
        example_prompt=example_prompt,
    )


@mcp.tool()
def design_schema_tool(operations: list[dict] | None = None) -> dict:
    """V1 稳定工具：schema 设计指导。

    提供 schema 设计建议和最佳实践。
    """
    return _call_public_tool(
        "design_schema_tool",
        manage_schema,
        mode="design",
        operations=operations,
    )


@mcp.tool()
def apply_schema_tool(
    mode: str,
    operations: list[dict] | None = None,
    confirm: bool = False,
    plan_hash: str | None = None,
) -> dict:
    """V1 稳定工具：schema 校验和预览。

    支持 validate 和 dry_run 模式。apply 模式在 V1 中返回 FEATURE_DISABLED。
    """
    start = time.perf_counter()
    if mode == "apply":
        return envelope_err(
            ErrorType.FEATURE_DISABLED,
            "Schema apply is disabled in V1. Use validate or dry_run mode.",
            suggestion="Use mode='validate' or mode='dry_run' to preview schema changes.",
            source="apply_schema_tool",
            details={"mode": mode, "tool": "apply_schema_tool"},
            duration_ms=(time.perf_counter() - start) * 1000.0,
        )
    return _call_public_tool(
        "apply_schema_tool",
        manage_schema,
        mode=mode,
        operations=operations,
        confirm=confirm,
        plan_hash=plan_hash,
    )


# ========== 图数据导入入口 ==========


@mcp.tool()
def import_graph_data_tool(
    mode: str,
    text: str | None = None,
    graph_schema: dict | None = None,
    example_prompt: str | None = None,
    graph_data: dict | None = None,
    table_data: dict | None = None,
    mapping: dict | None = None,
    dry_run: bool = True,
    confirm: bool = False,
    plan_hash: str | None = None,
    nonce: str | None = None,
    expires_at: float | None = None,
) -> dict:
    """V1 图数据导入入口。

    mode="extract": 自然语言文本 → 候选 graph_data
    mode="ingest": MCP 本地校验+dry_run/confirm+Gremlin 导入 graph_data
    mode="table": V1 禁用（返回 FEATURE_DISABLED）
    """
    start = time.perf_counter()

    if mode == "extract":
        if not text:
            return envelope_err(
                ErrorType.VALIDATION_ERROR,
                "text is required for mode='extract'",
                source="import_graph_data_tool",
                duration_ms=(time.perf_counter() - start) * 1000.0,
            )
        return _call_public_tool(
            "import_graph_data_tool",
            extract_graph_data,
            text=text,
            schema=graph_schema,
            example_prompt=example_prompt,
        )

    if mode == "ingest":
        if graph_data is None:
            return envelope_err(
                ErrorType.VALIDATION_ERROR,
                "graph_data is required for mode='ingest'",
                source="import_graph_data_tool",
                duration_ms=(time.perf_counter() - start) * 1000.0,
            )
        return _call_public_tool(
            "import_graph_data_tool",
            manage_graph_data,
            mode="import",
            graph_data=graph_data,
            dry_run=dry_run,
            confirm=confirm,
            plan_hash=plan_hash,
            nonce=nonce,
            expires_at=expires_at,
            plan_tool_name="import_graph_data_tool",
        )

    if mode == "table":
        return envelope_err(
            ErrorType.FEATURE_DISABLED,
            "Table import is not available in V1.",
            suggestion="Use mode='extract' with extract_graph_data_tool instead.",
            source="import_graph_data_tool",
            details={"mode": mode, "tool": "import_graph_data_tool"},
            duration_ms=(time.perf_counter() - start) * 1000.0,
        )

    return envelope_err(
        ErrorType.VALIDATION_ERROR,
        f"Unknown mode: {mode!r}. Use 'extract' or 'ingest'.",
        source="import_graph_data_tool",
        details={"mode": mode},
        duration_ms=(time.perf_counter() - start) * 1000.0,
    )


# ========== 受控图数据删除入口 ==========


@mcp.tool()
def delete_graph_data_tool(
    change_plan: dict,
    dry_run: bool = True,
    confirm: bool = False,
    plan_hash: str | None = None,
    nonce: str | None = None,
    expires_at: float | None = None,
) -> dict:
    """V1 稳定工具：受控删除图数据。

    只支持精确 delete_vertex/delete_edge change_plan。
    必须经过 dry_run -> plan_hash -> confirm；不支持批量条件删除或级联删除。
    """
    return _call_public_tool(
        "delete_graph_data_tool",
        manage_graph_data,
        mode="delete",
        change_plan=change_plan,
        dry_run=dry_run,
        confirm=confirm,
        plan_hash=plan_hash,
        nonce=nonce,
        expires_at=expires_at,
        plan_tool_name="delete_graph_data_tool",
    )


# ========== 高级调试工具 ==========


@mcp.tool()
def refresh_vid_embeddings_tool(confirm: bool = False) -> dict:
    """手动刷新 VID 嵌入 — 需 admin mode 且 readonly=false。"""
    blocked = _admin_gate("refresh_vid_embeddings_tool", requires_write=True)
    if blocked:
        return blocked
    return _call_public_tool(
        "refresh_vid_embeddings_tool",
        refresh_vid_embeddings,
        confirm=confirm,
    )


@mcp.tool()
def execute_gremlin_write_tool(gremlin_query: str) -> dict:
    """执行 Gremlin 写查询 — 需 admin mode 且 readonly=false。"""
    blocked = _admin_gate("execute_gremlin_write_tool", requires_write=True)
    if blocked:
        return blocked
    return _call_public_tool(
        "execute_gremlin_write_tool",
        execute_gremlin_write,
        gremlin_query,
        capability=Capability.DEBUG_WRITE,
    )


def main() -> None:
    """CLI 入口 — 默认 stdio 模式。"""
    mcp.run()


if __name__ == "__main__":  # pragma: no cover - manual launch
    main()
