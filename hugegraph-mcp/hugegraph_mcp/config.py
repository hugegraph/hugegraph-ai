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
CONFIG_ENV_NAMES = (
    "HUGEGRAPH_URL",
    "HUGEGRAPH_GRAPH_PATH",
    "HUGEGRAPH_GRAPH",
    "HUGEGRAPH_GRAPHSPACE",
    "HUGEGRAPH_USER",
    "HUGEGRAPH_PASSWORD",
    "HUGEGRAPH_MCP_READONLY",
    "HUGEGRAPH_AI_URL",
    "HUGEGRAPH_AI_GRAPH_URL",
    "HUGEGRAPH_MCP_ALLOW_AI",
    "HUGEGRAPH_MCP_ADMIN_MODE",
    "HUGEGRAPH_MCP_TIMEOUT_SECONDS",
)
_CONFIG_CACHE_KEY: tuple[tuple[str, str | None], ...] | None = None
_CONFIG_CACHE_VALUE = None


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
    admin_mode: bool = False
    timeout_seconds: int = 30
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "MCPConfig":
        global _CONFIG_CACHE_KEY, _CONFIG_CACHE_VALUE

        use_cache = env is None
        env = env if env is not None else os.environ
        cache_key = _env_cache_key(env) if use_cache else None
        if (
            use_cache
            and cache_key == _CONFIG_CACHE_KEY
            and _CONFIG_CACHE_VALUE is not None
        ):
            return _CONFIG_CACHE_VALUE

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
            admin_mode=_parse_bool(env.get("HUGEGRAPH_MCP_ADMIN_MODE", "")),
            timeout_seconds=_parse_int(env.get("HUGEGRAPH_MCP_TIMEOUT_SECONDS"), 30),
            warnings=tuple(warnings),
        )
        for warning in config.warnings:
            LOGGER.warning(warning)
        if use_cache:
            _CONFIG_CACHE_KEY = cache_key
            _CONFIG_CACHE_VALUE = config
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
    try:
        parsed = int(value)
    except ValueError:
        LOGGER.warning(
            "Invalid integer config value %r; using default %s", value, default
        )
        return default
    if parsed <= 0:
        LOGGER.warning(
            "Invalid integer config value %r; using default %s", value, default
        )
        return default
    return parsed


def _non_empty(value: str, default: str) -> str:
    return value.strip() or default


def _optional_non_empty(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _env_cache_key(env: Mapping[str, str]) -> tuple[tuple[str, str | None], ...]:
    return tuple((name, env.get(name)) for name in CONFIG_ENV_NAMES)


class RuntimeConfigProxy:
    """Compatibility proxy for code that imports config directly."""

    def __getattr__(self, name: str):
        return getattr(MCPConfig.from_env(), name)

    def is_readonly(self) -> bool:
        return MCPConfig.from_env().is_readonly()


config = RuntimeConfigProxy()
