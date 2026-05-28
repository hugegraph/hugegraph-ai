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

import logging

from hugegraph_mcp.config import MCPConfig, config


CONFIG_ENV_VARS = (
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
    "HUGEGRAPH_MCP_TIMEOUT_SECONDS",
)


def clear_config_env(monkeypatch):
    for name in CONFIG_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def test_basic_config_parsing(monkeypatch):
    clear_config_env(monkeypatch)
    monkeypatch.setenv("HUGEGRAPH_URL", "http://graph.example:18080")
    monkeypatch.setenv("HUGEGRAPH_GRAPHSPACE", "space_a")
    monkeypatch.setenv("HUGEGRAPH_GRAPH", "graph_a")
    monkeypatch.setenv("HUGEGRAPH_USER", "alice")
    monkeypatch.setenv("HUGEGRAPH_PASSWORD", "secret")
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "true")
    monkeypatch.setenv("HUGEGRAPH_AI_URL", "http://ai.example:18001")
    monkeypatch.setenv("HUGEGRAPH_AI_GRAPH_URL", "http://graph-internal:8080")
    monkeypatch.setenv("HUGEGRAPH_MCP_ALLOW_AI", "yes")
    monkeypatch.setenv("HUGEGRAPH_MCP_TIMEOUT_SECONDS", "45")

    cfg = MCPConfig.from_env()

    assert cfg.url == "http://graph.example:18080"
    assert cfg.graphspace == "space_a"
    assert cfg.graph == "graph_a"
    assert cfg.user == "alice"
    assert cfg.password == "secret"
    assert cfg.is_readonly() is True
    assert cfg.ai_url == "http://ai.example:18001"
    assert cfg.ai_graph_url == "http://graph-internal:8080"
    assert cfg.allow_ai is True
    assert cfg.timeout_seconds == 45


def test_graph_path_parsing(monkeypatch):
    clear_config_env(monkeypatch)
    monkeypatch.setenv("HUGEGRAPH_GRAPH_PATH", "myspace/mygraph")

    cfg = MCPConfig.from_env()

    assert cfg.graphspace == "myspace"
    assert cfg.graph == "mygraph"


def test_split_graph_variables_take_priority(monkeypatch):
    clear_config_env(monkeypatch)
    monkeypatch.setenv("HUGEGRAPH_GRAPH_PATH", "path_space/path_graph")
    monkeypatch.setenv("HUGEGRAPH_GRAPHSPACE", "split_space")
    monkeypatch.setenv("HUGEGRAPH_GRAPH", "split_graph")

    cfg = MCPConfig.from_env()

    assert cfg.graphspace == "split_space"
    assert cfg.graph == "split_graph"
    assert cfg.warnings == (
        "HUGEGRAPH_GRAPHSPACE/HUGEGRAPH_GRAPH override HUGEGRAPH_GRAPH_PATH",
    )


def test_warnings_are_logged(monkeypatch, caplog):
    clear_config_env(monkeypatch)
    monkeypatch.setenv("HUGEGRAPH_GRAPH_PATH", "path_space/path_graph")
    monkeypatch.setenv("HUGEGRAPH_GRAPHSPACE", "split_space")

    with caplog.at_level(logging.WARNING, logger="hugegraph_mcp.config"):
        cfg = MCPConfig.from_env()

    assert cfg.warnings == (
        "HUGEGRAPH_GRAPHSPACE/HUGEGRAPH_GRAPH override HUGEGRAPH_GRAPH_PATH",
    )
    assert (
        "HUGEGRAPH_GRAPHSPACE/HUGEGRAPH_GRAPH override HUGEGRAPH_GRAPH_PATH"
        in caplog.messages
    )


def test_duplicate_config_warnings_are_not_logged_for_unchanged_env(
    monkeypatch, caplog
):
    clear_config_env(monkeypatch)
    monkeypatch.setenv("HUGEGRAPH_GRAPH_PATH", "cache_space/cache_graph")
    monkeypatch.setenv("HUGEGRAPH_GRAPHSPACE", "cache_override")

    with caplog.at_level(logging.WARNING, logger="hugegraph_mcp.config"):
        first = MCPConfig.from_env()
        second = MCPConfig.from_env()

    assert first is second
    assert (
        caplog.messages.count(
            "HUGEGRAPH_GRAPHSPACE/HUGEGRAPH_GRAPH override HUGEGRAPH_GRAPH_PATH"
        )
        == 1
    )


def test_invalid_integer_config_falls_back_to_default(monkeypatch, caplog):
    clear_config_env(monkeypatch)
    monkeypatch.setenv("HUGEGRAPH_MCP_TIMEOUT_SECONDS", "not-a-number")

    with caplog.at_level(logging.WARNING, logger="hugegraph_mcp.config"):
        cfg = MCPConfig.from_env()

    assert cfg.timeout_seconds == 30
    assert (
        "Invalid integer config value 'not-a-number'; using default 30"
        in caplog.messages
    )


def test_non_positive_integer_config_falls_back_to_default(monkeypatch, caplog):
    for value in ("0", "-1"):
        clear_config_env(monkeypatch)
        monkeypatch.setenv("HUGEGRAPH_MCP_TIMEOUT_SECONDS", value)
        caplog.clear()

        with caplog.at_level(logging.WARNING, logger="hugegraph_mcp.config"):
            cfg = MCPConfig.from_env()

        assert cfg.timeout_seconds == 30
        assert (
            f"Invalid integer config value '{value}'; using default 30"
            in caplog.messages
        )


def test_readonly_and_allow_ai_are_controlled_independently(monkeypatch):
    clear_config_env(monkeypatch)
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "true")
    monkeypatch.setenv("HUGEGRAPH_MCP_ALLOW_AI", "true")

    cfg = MCPConfig.from_env()

    assert cfg.is_readonly() is True
    assert cfg.allow_ai is True


def test_readonly_parsing(monkeypatch):
    true_values = ("true", "1", "yes", "TRUE")
    false_values = ("false", "0", "no", "")

    for value in true_values:
        clear_config_env(monkeypatch)
        monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", value)
        assert MCPConfig.from_env().is_readonly() is True

    for value in false_values:
        clear_config_env(monkeypatch)
        monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", value)
        assert MCPConfig.from_env().is_readonly() is False


def test_default_password_is_empty_but_explicit_xxx_is_accepted(monkeypatch):
    clear_config_env(monkeypatch)
    assert MCPConfig.from_env().password == ""

    monkeypatch.setenv("HUGEGRAPH_PASSWORD", "xxx")
    assert MCPConfig.from_env().password == "xxx"


def test_default_values(monkeypatch):
    clear_config_env(monkeypatch)

    cfg = MCPConfig.from_env()

    assert cfg.url == "http://127.0.0.1:8080"
    assert cfg.graphspace == "DEFAULT"
    assert cfg.graph == "hugegraph"
    assert cfg.user == "admin"
    assert cfg.password == ""
    assert cfg.is_readonly() is True
    assert cfg.ai_url == "http://127.0.0.1:8001"
    assert cfg.ai_graph_url is None
    assert cfg.allow_ai is False
    assert cfg.timeout_seconds == 30
    assert cfg.warnings == ()


def test_config_proxy_reads_current_env(monkeypatch):
    clear_config_env(monkeypatch)
    monkeypatch.setenv("HUGEGRAPH_GRAPH", "first_graph")
    assert config.graph == "first_graph"

    monkeypatch.setenv("HUGEGRAPH_GRAPH", "second_graph")
    assert config.graph == "second_graph"
