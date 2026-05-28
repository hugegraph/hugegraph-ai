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

"""统一配置层 — 所有 MCP 工具通过 MCPConfig.from_env() 获取配置。

环境变量优先级高于默认值，避免硬编码连接信息。"""

import logging
import os
from dataclasses import dataclass, field
from typing import Mapping

TRUE_VALUES = {"1", "true", "yes"}
LOGGER = logging.getLogger("hugegraph_mcp.config")


@dataclass
class MCPConfig:
    """MCP 服务器统一配置，所有字段从环境变量读取，有合理默认值。"""

    url: str = "http://127.0.0.1:8080"
    graph: str = "hugegraph"
    graphspace: str | None = "DEFAULT"
    user: str = "admin"
    password: str = ""
    readonly: bool = True
    ai_url: str = "http://127.0.0.1:8001"
    ai_graph_url: str | None = None
    allow_ai: bool = False
    enable_graphrag_experimental: bool = False
    timeout_seconds: int = 30
    max_context_items: int = 100
    sql_enabled: bool = False
    sqlite_allowlist: tuple[str, ...] = field(default_factory=tuple)
    sql_max_preview_rows: int = 20
    sql_max_import_rows: int = 1000
    sql_timeout_seconds: int = 10
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "MCPConfig":
        env = env if env is not None else os.environ
        warnings: list[str] = []

        path_graphspace, path_graph = _parse_graph_path(
            env.get("HUGEGRAPH_GRAPH_PATH", "DEFAULT/hugegraph")
        )
        graphspace = path_graphspace
        graph = path_graph

        split_graphspace = env.get("HUGEGRAPH_GRAPHSPACE")
        split_graph = env.get("HUGEGRAPH_GRAPH")
        if env.get("HUGEGRAPH_GRAPH_PATH") is not None and (
            split_graphspace is not None or split_graph is not None
        ):
            warnings.append(
                "HUGEGRAPH_GRAPHSPACE/HUGEGRAPH_GRAPH override HUGEGRAPH_GRAPH_PATH"
            )

        if split_graphspace is not None:
            graphspace = _non_empty(split_graphspace, "DEFAULT")
        if split_graph is not None:
            graph = _non_empty(split_graph, "hugegraph")

        config = cls(
            url=env.get("HUGEGRAPH_URL", "http://127.0.0.1:8080"),
            graph=graph,
            graphspace=graphspace,
            user=env.get("HUGEGRAPH_USER", "admin"),
            password=env.get("HUGEGRAPH_PASSWORD", ""),
            readonly=_parse_bool(env.get("HUGEGRAPH_MCP_READONLY", "true")),
            ai_url=env.get("HUGEGRAPH_AI_URL", "http://127.0.0.1:8001"),
            ai_graph_url=_optional_non_empty(env.get("HUGEGRAPH_AI_GRAPH_URL")),
            allow_ai=_parse_bool(env.get("HUGEGRAPH_MCP_ALLOW_AI", "")),
            enable_graphrag_experimental=_parse_bool(
                env.get("HUGEGRAPH_MCP_ENABLE_GRAPHRAG_EXPERIMENTAL", "")
            ),
            timeout_seconds=_parse_int(env.get("HUGEGRAPH_MCP_TIMEOUT_SECONDS"), 30),
            max_context_items=_parse_int(
                env.get("HUGEGRAPH_MCP_MAX_CONTEXT_ITEMS"), 100
            ),
            sql_enabled=_parse_bool(env.get("HUGEGRAPH_MCP_SQL_ENABLED", "")),
            sqlite_allowlist=_parse_semicolon_tuple(
                env.get("HUGEGRAPH_MCP_SQLITE_ALLOWLIST", "")
            ),
            sql_max_preview_rows=_parse_int(
                env.get("HUGEGRAPH_MCP_SQL_MAX_PREVIEW_ROWS"), 20
            ),
            sql_max_import_rows=_parse_int(
                env.get("HUGEGRAPH_MCP_SQL_MAX_IMPORT_ROWS"), 1000
            ),
            sql_timeout_seconds=_parse_int(
                env.get("HUGEGRAPH_MCP_SQL_TIMEOUT_SECONDS"), 10
            ),
            warnings=tuple(warnings),
        )
        for warning in config.warnings:
            LOGGER.warning(warning)
        return config

    def is_readonly(self) -> bool:
        return self.readonly


def _parse_graph_path(graph_path: str) -> tuple[str, str]:
    if "/" in graph_path:
        graphspace, graph = graph_path.split("/", 1)
    else:
        graphspace, graph = "DEFAULT", graph_path

    return _non_empty(graphspace, "DEFAULT"), _non_empty(graph, "hugegraph")


def _parse_bool(value: str) -> bool:
    return value.strip().lower() in TRUE_VALUES


def _parse_int(value: str | None, default: int) -> int:
    if value is None or value.strip() == "":
        return default
    return int(value)


def _non_empty(value: str, default: str) -> str:
    return value.strip() or default


def _optional_non_empty(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _parse_semicolon_tuple(value: str) -> tuple[str, ...]:
    if not value or not value.strip():
        return ()
    return tuple(part.strip() for part in value.split(";") if part.strip())


class RuntimeConfigProxy:
    """Compatibility proxy for code that imports config directly."""

    def __getattr__(self, name: str):
        return getattr(MCPConfig.from_env(), name)

    def is_readonly(self) -> bool:
        return MCPConfig.from_env().is_readonly()


config = RuntimeConfigProxy()
