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

# FastMCP server bootstrap for HugeGraph MCP

import logging
import logging.handlers
import os
from logging.handlers import RotatingFileHandler

# MUST patch BEFORE importing any module that triggers pyhugegraph
# pyhugegraph initializes logging at module level and tries to create 'logs' directory
# We intercept both os.makedirs and RotatingFileHandler to prevent file logging in MCP context

# 1. Patch os.makedirs to silently skip 'logs' directory creation
_original_makedirs = os.makedirs


def _safe_makedirs(name, mode=0o777, exist_ok=False):
    # Silently succeed for 'logs' directory (don't actually create it)
    if isinstance(name, str) and ("logs" in name or name == "logs"):
        return None  # Pretend success
    return _original_makedirs(name, mode, exist_ok)


os.makedirs = _safe_makedirs

# 2. Patch RotatingFileHandler to return NullHandler for 'logs/' files
_OriginalRotatingFileHandler = RotatingFileHandler


class _NoOpFileHandler(logging.NullHandler):
    """A no-op handler that silently ignores all log records (used to disable file logging in MCP)."""

    def __init__(self, *args, **kwargs):
        # Ignore all arguments (filename, maxBytes, etc.) and just create a NullHandler
        super().__init__()


def _patched_rotating_handler(filename, *args, **kwargs):
    # If the filename contains 'logs', disable file logging by returning a no-op handler
    if "logs" in str(filename):
        return _NoOpFileHandler()
    return _OriginalRotatingFileHandler(filename, *args, **kwargs)


logging.handlers.RotatingFileHandler = _patched_rotating_handler

# Now safe to import modules that use pyhugegraph
from fastmcp import FastMCP

from hugegraph_mcp.gremlin_tools import execute_gremlin_read, execute_gremlin_write
from hugegraph_mcp.config import MCPConfig
from hugegraph_mcp.schema_tools import (
    design_schema,
    execute_schema_operations,
    get_live_schema,
)
from hugegraph_mcp.tools.generate_gremlin import generate_gremlin
from hugegraph_mcp.tools.inspect_graph import inspect_graph
from hugegraph_mcp.tools.query_graph import query_graph_by_text

# Suppress FastMCP info-level logs (e.g. "Starting server ...") so that
# stdout is reserved for MCP JSON protocol only. Windsurf's MCP client
# reads stdout as a pure JSON stream and will fail if human-readable logs
# are mixed in.
logging.disable(logging.CRITICAL)

READONLY = MCPConfig.from_env().is_readonly()

mcp = FastMCP("HugeGraph MCP")


@mcp.tool()
def get_live_schema_tool() -> dict:
    """Fetch live HugeGraph schema via REST and return full & simplified schema.

    This tool provides comprehensive schema information including:
    - Vertex labels with their properties
    - Edge labels with source/target relationships
    - Property keys and their data types
    - Index labels for search optimization

    The schema is fetched in real-time from your HugeGraph instance.
    This tool is always available regardless of read-only mode settings.

    Returns:
        dict: Contains 'schema' (full raw schema), 'simple_schema' (LLM-friendly format),
              and 'readonly' (boolean indicating if server is in read-only mode).
    """

    return get_live_schema()


@mcp.tool()
def inspect_graph_tool(include_raw_schema: bool = False) -> dict:
    """Inspect HugeGraph server status, schema summary, counts, and AI status.

    This is the recommended first tool after connecting to HugeGraph MCP. It
    returns a best-effort status envelope and degrades gracefully when HugeGraph
    Server, Gremlin counts, or HugeGraph-AI are unavailable.

    Args:
        include_raw_schema: Include the full raw HugeGraph schema in the response.

    Returns:
        dict: Standard ok envelope with server_status, ai_status, schema_summary,
              vertex_count, edge_count, index_count, readonly, warnings, and
              suggested next_actions.
    """

    return inspect_graph(include_raw_schema=include_raw_schema)


@mcp.tool()
def generate_gremlin_tool(
    query: str,
    execute: bool = False,
    output_types: list[str] | None = None,
) -> dict:
    """Generate Gremlin from natural language using HugeGraph-AI.

    The generated Gremlin is safety-classified before any optional execution.
    By default execute is false, so this tool returns the generated traversal
    without running it. When execute is true, only confidently read-only Gremlin
    will be executed automatically.

    Args:
        query: Natural language question or request to convert to Gremlin.
        execute: Whether to execute the generated Gremlin when it is read-only.
        output_types: Reserved for future response filtering. Current responses
            include gremlin, template_gremlin, and raw_gremlin.

    Returns:
        dict: Standard envelope with generated Gremlin, safety metadata,
              execution status, and optional execution_result.
    """

    return generate_gremlin(
        query=query,
        execute=execute,
        output_types=output_types,
    )


@mcp.tool()
def query_graph_by_text_tool(
    query: str,
    mode: str = "graph_only",
    include_evidence: bool = False,
    max_context_items: int = 20,
) -> dict:
    """Ask HugeGraph-AI RAG a natural-language question about the graph.

    Args:
        query: Natural language question to answer from graph knowledge.
        mode: Query mode. "graph_only" uses graph RAG via /rag/graph;
            "vector_only" uses pure vector retrieval via /rag.
        include_evidence: Whether to include supporting evidence from the AI response.
        max_context_items: Maximum number of context items the AI can use.

    Returns:
        dict: Standard envelope with answer, evidence, generated Gremlin,
              source summary, and suggested next actions when no answer is found.
    """

    return query_graph_by_text(
        query=query,
        mode=mode,
        include_evidence=include_evidence,
    )


@mcp.tool()
def execute_gremlin_read_tool(gremlin_query: str) -> dict:
    """Execute a read-only Gremlin query and return data/total/duration_ms/is_read.

    This tool allows you to explore and query your graph data safely without
    making any modifications. Use it for:
    - Finding vertices and edges
    - Counting nodes and relationships
    - Traversing the graph structure
    - Analyzing graph patterns

    The query will be validated to ensure it only contains read operations.

    Args:
        gremlin_query: A valid Gremlin query string (e.g., "g.V().count()",
                      "g.V().hasLabel('person').limit(10)")

    Returns:
        dict: Contains 'data' (query results), 'total' (result count),
              'duration_ms' (execution time), and 'is_read' (always true).
    """

    return execute_gremlin_read(gremlin_query)


# Write tools - only registered when not in read-only mode
if not READONLY:

    @mcp.tool()
    def design_schema_tool(
        thought: str,
        thought_number: int,
        total_thoughts: int = 4,
        next_thought_needed: bool = True,
        is_revision: bool = False,
        revision_of: int | None = None,
    ) -> dict:
        """Schema design guidance tool - Multi-turn interactive graph design

        【When to Use This Tool】

        Use this tool when:
        - User requests to design a new HugeGraph schema but doesn't know the specific structure
        - User describes a graph database use case and needs help planning entities, properties, and relationships
        - User needs interactive guidance to complete schema definition

        【When NOT to Use This Tool】
        - User already knows exactly what vertex labels and edge labels to create
        - User provides complete schema definition and only needs execution (use execute_schema_operations directly)
        - Only querying existing schema (use get_live_schema)

        【Workflow】
        1. Call design_schema_tool to start interactive design
        2. Iterate through questions based on returned thought_number
        3. Generate operations list after collecting all information
        4. Call execute_schema_operations to create the schema

        Reference Sequential Thinking pattern, letting LLM autonomously guide users
        through schema design. Tool only returns current iteration info.

        See design_schema() docstring for best practices and examples.

        Args:
            thought: Current thought or summary of user's answer
            thought_number: Current iteration number
            total_thoughts: Planned total iterations (3-5 recommended)
            next_thought_needed: Whether to continue to next iteration
            is_revision: Whether revising previous thought
            revision_of: Which iteration being revised

        Returns:
            dict: Contains 'thought_number', 'total_thoughts', 'next_thought_needed'
        """

        return design_schema(
            thought=thought,
            thought_number=thought_number,
            total_thoughts=total_thoughts,
            next_thought_needed=next_thought_needed,
            is_revision=is_revision,
            revision_of=revision_of,
        )

    @mcp.tool()
    def execute_schema_operations_tool(operations: list[dict]) -> dict:
        """Execute schema operations (create/modify vertex labels, edge labels, property keys, indexes).

        This tool allows you to modify your graph schema by:
        - Creating new property keys with specified data types
        - Creating vertex and edge labels with defined properties
        - Creating index labels for query optimization

        【Prerequisite - Must Read】

        ⚠️ Before using this tool, you MUST use design_schema_tool first if ANY of the following applies:
        - User's design intent is not clear or obvious
        - User's request lacks sufficient schema details (entities, properties, relationships)
        - User is designing a new schema but has not gone through the interactive design process
        - You are uncertain about the appropriate schema structure

        If any of the above conditions are true, call design_schema_tool first to interactively
        gather the required information, then use this tool to execute the operations.

        ⚠️ WRITE TOOL - Only available when HUGEGRAPH_MCP_READONLY is false/undefined.

        Args:
            operations: List of schema operation dictionaries, each containing:
                       - type: Operation type ("create_property_key", "create_vertex_label",
                               "create_edge_label", "create_index_label")
                       - Additional fields specific to each operation type

        Returns:
            dict: Contains 'success' (boolean), 'results' (per-operation status),
                  and 'errors' (list of any failures).
        """

        return execute_schema_operations(operations)

    @mcp.tool()
    def execute_gremlin_write_tool(gremlin_query: str) -> dict:
        """Execute a Gremlin write query and return affected/duration_ms/is_write.

        ⚠️ WRITE TOOL - Only available when HUGEGRAPH_MCP_READONLY is false/undefined.

        This tool allows you to modify your graph data by:
        - Adding new vertices and edges
        - Updating vertex and edge properties
        - Deleting graph elements
        - Performing bulk data operations

        Use with caution - write operations cannot be undone and will permanently
        modify your graph data.

        Args:
            gremlin_query: A valid Gremlin write query string (e.g.,
                          "g.addV('person').property('name', 'Alice')",
                          "g.V().has('name', 'Alice').property('age', 30)")

        Returns:
            dict: Contains 'affected' (number of elements modified),
                  'duration_ms' (execution time), and 'is_write' (always true).
        """

        return execute_gremlin_write(gremlin_query)


def main() -> None:
    """CLI entry point used by console_scripts."""

    # Default to stdio; callers can also use `uv run fastmcp run` style entry.
    mcp.run()


if __name__ == "__main__":  # pragma: no cover - manual launch
    main()
