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
import logging
from dataclasses import dataclass, field
from typing import Mapping


TRUE_VALUES = {"1", "true", "yes"}
LOGGER = logging.getLogger("hugegraph_mcp.config")


@dataclass
class MCPConfig:
    url: str = "http://127.0.0.1:8080"
    graph: str = "hugegraph"
    graphspace: str | None = "DEFAULT"
    user: str = "admin"
    password: str = ""
    readonly: bool = False
    ai_url: str = "http://127.0.0.1:8001"
    allow_ai: bool = False
    timeout_seconds: int = 30
    max_context_items: int = 100
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.readonly:
            self.allow_ai = False

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
            readonly=_parse_bool(env.get("HUGEGRAPH_MCP_READONLY", "")),
            ai_url=env.get("HUGEGRAPH_AI_URL", "http://127.0.0.1:8001"),
            allow_ai=_parse_bool(env.get("HUGEGRAPH_MCP_ALLOW_AI", "")),
            timeout_seconds=_parse_int(
                env.get("HUGEGRAPH_MCP_TIMEOUT_SECONDS"), 30
            ),
            max_context_items=_parse_int(
                env.get("HUGEGRAPH_MCP_MAX_CONTEXT_ITEMS"), 100
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


config = MCPConfig.from_env()
