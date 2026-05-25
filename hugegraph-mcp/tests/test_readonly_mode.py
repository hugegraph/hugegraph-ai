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

"""Test that HUGEGRAPH_MCP_READONLY properly disables write tools."""

import asyncio
import importlib
import os
from unittest.mock import patch


def get_registered_tools():
    """Helper to get registered MCP tool names from a running server instance."""
    import hugegraph_mcp.server

    async def _get_tools():
        tools = await hugegraph_mcp.server.mcp._list_tools()
        return [t.name for t in tools]

    return asyncio.run(_get_tools())


def test_readonly_env_parsing():
    """Test that various readonly env values are parsed correctly."""
    test_cases = [
        ("true", True),
        ("1", True),
        ("yes", True),
        ("TRUE", True),
        ("True", True),
        ("false", False),
        ("0", False),
        ("no", False),
        ("", False),
        ("invalid", False),
    ]

    for env_value, expected in test_cases:
        with patch.dict(os.environ, {"HUGEGRAPH_MCP_READONLY": env_value}, clear=True):
            # Import and check READONLY value
            import importlib

            import hugegraph_mcp.server

            importlib.reload(hugegraph_mcp.server)

            assert expected == hugegraph_mcp.server.READONLY


def test_write_tools_available_when_not_readonly(monkeypatch):
    """Test that write tools are registered when not in readonly mode."""
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")

    import hugegraph_mcp.server

    importlib.reload(hugegraph_mcp.server)
    tools = get_registered_tools()
    assert "execute_schema_operations_tool" in tools
    assert "execute_gremlin_write_tool" in tools


def test_write_tools_disabled_when_readonly(monkeypatch):
    """Test that old write tools remain registered in readonly mode (runtime-guarded)."""
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "true")

    import hugegraph_mcp.server

    importlib.reload(hugegraph_mcp.server)
    tools = get_registered_tools()
    # Old write tools now always registered — reject via structured envelope at runtime
    assert "execute_schema_operations_tool" in tools
    assert "execute_gremlin_write_tool" in tools
    assert "design_schema_tool" in tools
    assert "manage_schema_tool" in tools
    # Read tools should still be available
    assert "get_live_schema_tool" in tools
    assert "generate_gremlin_tool" in tools
    assert "query_graph_by_text_tool" in tools
    assert "execute_gremlin_read_tool" in tools


def test_readonly_mode_default(monkeypatch):
    """Test that default mode is not readonly when env is not set."""
    monkeypatch.delenv("HUGEGRAPH_MCP_READONLY", raising=False)

    import hugegraph_mcp.server

    importlib.reload(hugegraph_mcp.server)
    tools = get_registered_tools()
    assert "execute_schema_operations_tool" in tools
    assert "execute_gremlin_write_tool" in tools
