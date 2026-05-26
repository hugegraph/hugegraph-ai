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
from hugegraph_mcp.config import MCPConfig
from hugegraph_mcp.envelope import envelope_err, envelope_ok
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

mcp = FastMCP("HugeGraph MCP")


# ========== 工具 1：检视图状态和 schema ==========

@mcp.tool()
def inspect_graph_tool(include_raw_schema: bool = False) -> dict:
    """检视 HugeGraph 服务器状态、schema 摘要、点边计数和 AI 状态。

    推荐作为连接后第一个调用的工具。
    """
    return inspect_graph(include_raw_schema=include_raw_schema)


# ========== 工具 2：查询图 ==========

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
    """统一图查询入口 — 三种模式：

    - mode="text": 自然语言问图（通过 HugeGraph-AI RAG）
    - mode="generate": NL → Gremlin 生成（默认不执行）
    - mode="gremlin": 执行只读 Gremlin 遍历
    """
    if mode == "text":
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
        if (
            isinstance(result, dict)
            and result.get("data") is not None
            and "error" not in result
        ):
            return envelope_ok(
                {
                    "data": result.get("data"),
                    "total": result.get("total"),
                    "duration_ms": result.get("duration_ms"),
                    "is_read": result.get("is_read", True),
                }
            )
        return result

    return envelope_err(
        "VALIDATION_ERROR",
        f"Unknown mode: {mode!r}. Use 'text', 'generate', or 'gremlin'.",
        details={"mode": mode},
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
    """统一图数据管理入口。

    - extract: 自然语言 → 候选 graph_data（不写入）
    - import: 结构化 graph_data → 校验+导入
    - table: 表格数据 → graph_data → 导入
    - sql_preview / sql_mapping_suggest / sql_import: SQLite 数据源
    - update / delete: 变更计划 → 安全链执行

    写入操作需要 dry_run=True 确认 → plan_hash + confirm=True 执行。
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
        if table_data is None:
            return envelope_err("VALIDATION_ERROR", "table_data is required for mode='table'")
        mapped = import_table_data(table_data=table_data, mapping=mapping)
        if not mapped.get("ok"):
            return mapped
        mapped_graph_data = (mapped.get("data") or {}).get("graph_data")
        if mapped_graph_data is None:
            return mapped
        change_plan = graph_data_to_change_plan(mapped_graph_data)
        return manage_graph_data(
            mode="import",
            graph_data=mapped_graph_data,
            change_plan=change_plan,
            dry_run=dry_run,
            confirm=confirm,
            plan_hash=plan_hash,
        )

    if mode in {"sql_preview", "sql_mapping_suggest", "sql_import"}:
        return _handle_sql_mode(
            mode=mode,
            sql_source=sql_source,
            sql_query=sql_query,
            table_name=table_name,
            mapping=mapping,
            dry_run=dry_run,
            confirm=confirm,
            plan_hash=plan_hash,
        )

    if mode in {"import", "update", "delete"}:
        return manage_graph_data(
            mode=mode,
            graph_data=graph_data,
            change_plan=change_plan,
            dry_run=dry_run,
            confirm=confirm,
            plan_hash=plan_hash,
        )

    return envelope_err(
        "VALIDATION_ERROR",
        f"Unknown mode: {mode!r}. "
        "Use 'extract', 'import', 'table', 'sql_preview', 'sql_mapping_suggest', "
        "'sql_import', 'update', or 'delete'.",
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
    """兼容图数据导入入口 — 推荐使用 manage_graph_data_tool。

    mode="extract": 自然语言文本 → 候选 graph_data
    mode="ingest": 校验+导入 graph_data
    mode="table": 表格映射 → 导入
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
        if table_data is None:
            return envelope_err("VALIDATION_ERROR", "table_data is required for mode='table'")
        mapped = import_table_data(table_data=table_data, mapping=mapping)
        if not mapped.get("ok"):
            return mapped
        mapped_graph_data = (mapped.get("data") or {}).get("graph_data")
        if mapped_graph_data is None:
            return mapped
        return ingest_graph_data(
            graph_data=mapped_graph_data,
            dry_run=dry_run,
            confirm=confirm,
            plan_hash=plan_hash,
        )

    return envelope_err(
        "VALIDATION_ERROR",
        f"Unknown mode: {mode!r}. Use 'extract', 'ingest', or 'table'.",
        details={"mode": mode},
    )


# ========== 高级调试工具 ==========

@mcp.tool()
def refresh_vid_embeddings_tool(confirm: bool = False) -> dict:
    """手动刷新 VID 嵌入 — 需要 INDEX_WRITE 权限和 confirm=True。"""
    return refresh_vid_embeddings(confirm=confirm)


@mcp.tool()
def execute_gremlin_write_tool(gremlin_query: str) -> dict:
    """执行 Gremlin 写查询 — 高级调试工具。

    readonly 模式下返回 READONLY_VIOLATION。推荐使用 manage_graph_data_tool。
    """
    return execute_gremlin_write(gremlin_query)


def main() -> None:
    """CLI 入口 — 默认 stdio 模式。"""
    mcp.run()


if __name__ == "__main__":  # pragma: no cover - manual launch
    main()
