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
from logging.handlers import RotatingFileHandler

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


os.makedirs = _safe_makedirs

_OriginalRotatingFileHandler = RotatingFileHandler


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

# ---- patch 完成，安全导入依赖 pyhugegraph 的模块 ----

from fastmcp import FastMCP

from hugegraph_mcp.gremlin_tools import execute_gremlin_read, execute_gremlin_write
from hugegraph_mcp.config import MCPConfig, TRUE_VALUES
from hugegraph_mcp.envelope import ErrorType, envelope_err
from hugegraph_mcp.tools.generate_gremlin import generate_gremlin
from hugegraph_mcp.tools.inspect_graph import inspect_graph
from hugegraph_mcp.tools.extract_graph_data import extract_graph_data
from hugegraph_mcp.tools.import_table import import_table_data
from hugegraph_mcp.tools.ingest_graph_data import ingest_graph_data
from hugegraph_mcp.tools.manage_graph_data import (
    graph_data_to_change_plan,
    manage_graph_data,
)
from hugegraph_mcp.tools.sql_modes import _handle_sql_mode
from hugegraph_mcp.tools.manage_schema import manage_schema
from hugegraph_mcp.tools.query_graph import query_graph_by_text
from hugegraph_mcp.tools.refresh_vid_embeddings import refresh_vid_embeddings

os.makedirs = _original_makedirs

# 抑制 FastMCP info 日志 — stdout 必须保留为纯 JSON 协议流
logging.disable(logging.CRITICAL)

READONLY = MCPConfig.from_env().is_readonly()
ADMIN_MODE = os.environ.get("HUGEGRAPH_MCP_ADMIN_MODE", "").strip().lower() in TRUE_VALUES

mcp = FastMCP("HugeGraph MCP")


def _admin_gate(tool_name: str) -> dict | None:
    """Return FEATURE_DISABLED envelope if admin mode is not enabled, else None."""
    if ADMIN_MODE:
        return None
    return envelope_err(
        ErrorType.FEATURE_DISABLED,
        f"{tool_name} is disabled by default in V1. Enable with HUGEGRAPH_MCP_ADMIN_MODE=true.",
        suggestion="Set HUGEGRAPH_MCP_ADMIN_MODE=true to enable this tool.",
        details={"tool": tool_name, "enable_env": "HUGEGRAPH_MCP_ADMIN_MODE"},
    )


# ========== 工具 1：检视图状态和 schema ==========

@mcp.tool()
def inspect_graph_tool(include_raw_schema: bool = False) -> dict:
    """检视 HugeGraph 服务器状态、schema 摘要、点边计数和 AI 状态。

    推荐作为连接后第一个调用的工具。
    """
    return inspect_graph(include_raw_schema=include_raw_schema)


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
    return generate_gremlin(query=query, execute=execute)


@mcp.tool()
def execute_gremlin_read_tool(gremlin_query: str) -> dict:
    """V1 稳定工具：执行只读 Gremlin 遍历查询。

    经过 GremlinPolicy 安全检查后执行。
    """
    return execute_gremlin_read(gremlin_query)


@mcp.tool()
def extract_graph_data_tool(
    text: str,
    schema: dict | None = None,
    example_prompt: str | None = None,
) -> dict:
    """V1 稳定工具：自然语言文本 → 候选 graph_data（不写入）。

    返回提取的顶点和边数据，供后续导入使用。
    """
    return extract_graph_data(text=text, schema=schema, example_prompt=example_prompt)


@mcp.tool()
def design_schema_tool(operations: list[dict] | None = None) -> dict:
    """V1 稳定工具：schema 设计指导。

    提供 schema 设计建议和最佳实践。
    """
    return manage_schema(mode="design", operations=operations)


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
    if mode == "apply":
        return envelope_err(
            ErrorType.FEATURE_DISABLED,
            "Schema apply is disabled in V1. Use validate or dry_run mode.",
            suggestion="Use mode='validate' or mode='dry_run' to preview schema changes.",
            details={"mode": mode, "tool": "apply_schema_tool"},
        )
    return manage_schema(mode=mode, operations=operations, confirm=confirm, plan_hash=plan_hash)


# ========== 兼容工具：查询图 ==========

@mcp.tool()
def query_graph_tool(
    mode: str,
    query: str | None = None,
    gremlin_query: str | None = None,
    rag_mode: str = "graph_only",
    execute: bool = False,
    include_evidence: bool = False,
    max_context_items: int = 20,
) -> dict:
    """兼容图查询入口 — 推荐使用 generate_gremlin_tool 或 execute_gremlin_read_tool。

    - mode="generate": NL → Gremlin 生成（兼容路由到 generate_gremlin_tool）
    - mode="gremlin": 执行只读 Gremlin 遍历（兼容路由到 execute_gremlin_read_tool）
    - mode="text": GraphRAG 实验路径，默认禁用
    """
    if mode == "text":
        cfg = MCPConfig.from_env()
        if not cfg.enable_graphrag_experimental:
            return envelope_err(
                ErrorType.FEATURE_DISABLED,
                "GraphRAG text query mode is experimental and disabled by default",
                suggestion=(
                    "Use mode='generate' with execute=true for the stable "
                    "natural-language graph query path, or enable "
                    "HUGEGRAPH_MCP_ENABLE_GRAPHRAG_EXPERIMENTAL=true for "
                    "GraphRAG debugging."
                ),
                details={
                    "mode": mode,
                    "feature": "GraphRAG",
                    "enable_env": "HUGEGRAPH_MCP_ENABLE_GRAPHRAG_EXPERIMENTAL",
                },
                next_actions=[
                    "Use query_graph_tool with mode='generate' and execute=true",
                    "Enable HUGEGRAPH_MCP_ENABLE_GRAPHRAG_EXPERIMENTAL=true only for experimental GraphRAG debugging",
                ],
            )
        if not query:
            return envelope_err("VALIDATION_ERROR", "query is required for mode='text'")
        return query_graph_by_text(
            query=query,
            mode=rag_mode,
            include_evidence=include_evidence,
            max_context_items=max_context_items,
        )

    if mode == "generate":
        if not query:
            return envelope_err("VALIDATION_ERROR", "query is required for mode='generate'")
        return generate_gremlin(query=query, execute=execute)

    if mode == "gremlin":
        if not gremlin_query:
            return envelope_err("VALIDATION_ERROR", "gremlin_query is required for mode='gremlin'")
        result = execute_gremlin_read(gremlin_query)
        return result

    return envelope_err(
        "VALIDATION_ERROR",
        f"Unknown mode: {mode!r}. Use 'generate' or 'gremlin'.",
        details={
            "mode": mode,
            "stable_modes": ["generate", "gremlin"],
            "experimental_modes": ["text"],
        },
    )


# ========== 工具 3：设计和管理 schema ==========

@mcp.tool()
def manage_schema_tool(
    mode: str,
    operations: list[dict] | None = None,
    confirm: bool = False,
    plan_hash: str | None = None,
) -> dict:
    """统一 schema 管理入口 — design / validate / dry_run / apply 四种模式。

    apply 模式需 dry_run 返回的 plan_hash + confirm=True。
    """

    return manage_schema(
        mode=mode,
        operations=operations,
        confirm=confirm,
        plan_hash=plan_hash,
    )


# ========== 工具 4：导入和管理图数据 ==========

@mcp.tool()
def manage_graph_data_tool(
    mode: str,
    text: str | None = None,
    schema: dict | None = None,
    example_prompt: str | None = None,
    graph_data: dict | None = None,
    change_plan: dict | list[dict] | None = None,
    table_data: dict | None = None,
    mapping: dict | None = None,
    sql_source: dict | None = None,
    sql_query: str | None = None,
    table_name: str | None = None,
    dry_run: bool = True,
    confirm: bool = False,
    plan_hash: str | None = None,
) -> dict:
    """统一图数据管理入口 — 兼容工具。

    V1 支持的模式：
    - extract: 自然语言 → 候选 graph_data（不写入）
    - import: 结构化 graph_data → 校验+导入

    V1 禁用的模式（返回 FEATURE_DISABLED）：
    - table, sql_preview, sql_mapping_suggest, sql_import, update, delete
    """

    if mode == "extract":
        if not text:
            return envelope_err("VALIDATION_ERROR", "text is required for mode='extract'")
        return extract_graph_data(
            text=text,
            schema=schema,
            example_prompt=example_prompt,
        )

    if mode == "table":
        return envelope_err(
            ErrorType.FEATURE_DISABLED,
            "Table import is not available in V1.",
            suggestion="Use mode='extract' with extract_graph_data_tool instead.",
            details={"mode": mode, "tool": "manage_graph_data_tool"},
        )

    if mode in {"sql_preview", "sql_mapping_suggest", "sql_import"}:
        return envelope_err(
            ErrorType.FEATURE_DISABLED,
            f"SQL mode '{mode}' is not available in V1.",
            details={"mode": mode, "tool": "manage_graph_data_tool"},
        )

    if mode == "import":
        return manage_graph_data(
            mode=mode,
            graph_data=graph_data,
            change_plan=change_plan,
            dry_run=dry_run,
            confirm=confirm,
            plan_hash=plan_hash,
        )

    if mode in {"update", "delete"}:
        return envelope_err(
            ErrorType.FEATURE_DISABLED,
            f"Mode '{mode}' is not available in V1.",
            details={"mode": mode, "tool": "manage_graph_data_tool"},
        )

    return envelope_err(
        "VALIDATION_ERROR",
        f"Unknown mode: {mode!r}. "
        "Use 'extract' or 'import'.",
        details={"mode": mode},
    )


# ========== 兼容入口：import_graph_data_tool ==========

@mcp.tool()
def import_graph_data_tool(
    mode: str,
    text: str | None = None,
    schema: dict | None = None,
    example_prompt: str | None = None,
    graph_data: dict | None = None,
    table_data: dict | None = None,
    mapping: dict | None = None,
    dry_run: bool = True,
    confirm: bool = False,
    plan_hash: str | None = None,
) -> dict:
    """兼容图数据导入入口 — 推荐使用 extract_graph_data_tool。

    mode="extract": 自然语言文本 → 候选 graph_data
    mode="ingest": 校验+导入 graph_data
    mode="table": V1 禁用（返回 FEATURE_DISABLED）
    """

    if mode == "extract":
        if not text:
            return envelope_err("VALIDATION_ERROR", "text is required for mode='extract'")
        return extract_graph_data(
            text=text,
            schema=schema,
            example_prompt=example_prompt,
        )

    if mode == "ingest":
        if graph_data is None:
            return envelope_err("VALIDATION_ERROR", "graph_data is required for mode='ingest'")
        return ingest_graph_data(
            graph_data=graph_data,
            dry_run=dry_run,
            confirm=confirm,
            plan_hash=plan_hash,
        )

    if mode == "table":
        return envelope_err(
            ErrorType.FEATURE_DISABLED,
            "Table import is not available in V1.",
            suggestion="Use mode='extract' with extract_graph_data_tool instead.",
            details={"mode": mode, "tool": "import_graph_data_tool"},
        )

    return envelope_err(
        "VALIDATION_ERROR",
        f"Unknown mode: {mode!r}. Use 'extract' or 'ingest'.",
        details={"mode": mode},
    )


# ========== 高级调试工具 ==========

@mcp.tool()
def refresh_vid_embeddings_tool(confirm: bool = False) -> dict:
    """手动刷新 VID 嵌入 — V1 默认禁用，需 HUGEGRAPH_MCP_ADMIN_MODE=true。"""
    blocked = _admin_gate("refresh_vid_embeddings_tool")
    if blocked:
        return blocked
    return refresh_vid_embeddings(confirm=confirm)


@mcp.tool()
def execute_gremlin_write_tool(gremlin_query: str) -> dict:
    """执行 Gremlin 写查询 — V1 默认禁用，需 HUGEGRAPH_MCP_ADMIN_MODE=true。"""
    blocked = _admin_gate("execute_gremlin_write_tool")
    if blocked:
        return blocked
    return execute_gremlin_write(gremlin_query)


def main() -> None:
    """CLI 入口 — 默认 stdio 模式。"""
    mcp.run()


if __name__ == "__main__":  # pragma: no cover - manual launch
    main()
