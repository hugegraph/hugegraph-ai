"""Test that HUGEGRAPH_MCP_READONLY properly disables write tools."""

import os
import pytest
from unittest.mock import patch
import inspect
import subprocess
import sys
import asyncio
from typing import Any, Dict


def get_registered_tools():
    """Helper to get actually registered MCP tools."""
    import hugegraph_mcp.server
    
    async def _get_tools():
        # Type: ignore to work around FastMCP's type annotation issue
        # get_tools() is actually async despite its type signature
        tools_result = hugegraph_mcp.server.mcp._tool_manager.get_tools()  # type: ignore
        tools = await tools_result
        return list(tools.keys())
    
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
            
            assert hugegraph_mcp.server.READONLY == expected


def test_write_tools_available_when_not_readonly():
    """Test that write tools are registered when not in readonly mode."""
    # Use subprocess to avoid module caching issues
    result = subprocess.run([
        sys.executable, "-c", """
import asyncio
import os
os.environ['HUGEGRAPH_MCP_READONLY'] = 'false'

import hugegraph_mcp.server

async def test():
    # Get the actual registered tools (async call)
    tools_result = hugegraph_mcp.server.mcp._tool_manager.get_tools()  # type: ignore
    tools = await tools_result
    tool_names = list(tools.keys())

    # All tools should be available
    has_schema_ops = 'execute_schema_operations_tool' in tool_names
    has_gremlin_write = 'execute_gremlin_write_tool' in tool_names
    print(f"schema_ops: {has_schema_ops}, gremlin_write: {has_gremlin_write}")

asyncio.run(test())
"""
    ], capture_output=True, text=True, cwd="/Users/lotus/workspace/incubator-hugegraph-ai/hugegraph-mcp")
    
    assert "schema_ops: True" in result.stdout
    assert "gremlin_write: True" in result.stdout


def test_write_tools_disabled_when_readonly():
    """Test that write tools are NOT registered when in readonly mode."""
    # Use subprocess to avoid module caching issues
    result = subprocess.run([
        sys.executable, "-c", """
import asyncio
import os
os.environ['HUGEGRAPH_MCP_READONLY'] = 'true'

import hugegraph_mcp.server

async def test():
    # Get the actual registered tools (async call)
    tools_result = hugegraph_mcp.server.mcp._tool_manager.get_tools()  # type: ignore
    tools = await tools_result
    tool_names = list(tools.keys())

    # Only read tools should be available
    has_schema_ops = 'execute_schema_operations_tool' in tool_names
    has_gremlin_write = 'execute_gremlin_write_tool' in tool_names
    has_read_schema = 'get_live_schema_tool' in tool_names
    has_read_gremlin = 'execute_gremlin_read_tool' in tool_names
    print(f"schema_ops: {has_schema_ops}, gremlin_write: {has_gremlin_write}")
    print(f"read_schema: {has_read_schema}, read_gremlin: {has_read_gremlin}")

asyncio.run(test())
"""
    ], capture_output=True, text=True, cwd="/Users/lotus/workspace/incubator-hugegraph-ai/hugegraph-mcp")
    
    assert "schema_ops: False" in result.stdout
    assert "gremlin_write: False" in result.stdout
    assert "read_schema: True" in result.stdout
    assert "read_gremlin: True" in result.stdout


def test_readonly_mode_default():
    """Test that default mode is not readonly when env is not set."""
    # Use subprocess to avoid module caching issues
    result = subprocess.run([
        sys.executable, "-c", """
import asyncio
import os
# Explicitly clear the env var
os.environ.pop('HUGEGRAPH_MCP_READONLY', None)

import hugegraph_mcp.server

async def test():
    # Get the actual registered tools (async call)
    tools_result = hugegraph_mcp.server.mcp._tool_manager.get_tools()  # type: ignore
    tools = await tools_result
    tool_names = list(tools.keys())

    # All tools should be available by default
    has_schema_ops = 'execute_schema_operations_tool' in tool_names
    has_gremlin_write = 'execute_gremlin_write_tool' in tool_names
    print(f"schema_ops: {has_schema_ops}, gremlin_write: {has_gremlin_write}")

asyncio.run(test())
"""
    ], capture_output=True, text=True, cwd="/Users/lotus/workspace/incubator-hugegraph-ai/hugegraph-mcp")
    
    assert "schema_ops: True" in result.stdout
    assert "gremlin_write: True" in result.stdout
