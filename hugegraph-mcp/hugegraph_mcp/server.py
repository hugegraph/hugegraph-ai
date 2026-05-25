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
from hugegraph_mcp.envelope import envelope_err, envelope_ok
from hugegraph_mcp.schema_tools import (
    design_schema,
    execute_schema_operations,
)
from hugegraph_mcp.tools.generate_gremlin import generate_gremlin
from hugegraph_mcp.tools.inspect_graph import inspect_graph
from hugegraph_mcp.tools.extract_graph_data import extract_graph_data
from hugegraph_mcp.tools.ingest_graph_data import ingest_graph_data
from hugegraph_mcp.tools.manage_schema import manage_schema
from hugegraph_mcp.tools.query_graph import query_graph_by_text
from hugegraph_mcp.tools.refresh_vid_embeddings import refresh_vid_embeddings

# Suppress FastMCP info-level logs (e.g. "Starting server ...") so that
# stdout is reserved for MCP JSON protocol only. Windsurf's MCP client
# reads stdout as a pure JSON stream and will fail if human-readable logs
# are mixed in.
logging.disable(logging.CRITICAL)

READONLY = MCPConfig.from_env().is_readonly()

mcp = FastMCP("HugeGraph MCP")



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
def query_graph_tool(
    mode: str,
    query: str | None = None,
    gremlin_query: str | None = None,
    rag_mode: str = "graph_only",
    execute: bool = False,
    include_evidence: bool = False,
    max_context_items: int = 20,
) -> dict:
    """Unified graph query entry — the recommended tool for all graph read operations.

    Three modes:
    - mode="text": Ask a natural-language question and get an AI-powered answer
      backed by graph data. Uses HugeGraph-AI RAG.
    - mode="generate": Convert a natural-language question to a Gremlin traversal.
      By default only generates the query without executing it.
    - mode="gremlin": Execute a read-only Gremlin query directly against HugeGraph.
      Only known-safe read traversals are allowed.

    Args:
        mode: Query mode — "text", "generate", or "gremlin".
        query: Natural language question (required for text and generate modes).
        gremlin_query: Gremlin query string (required for gremlin mode).
        rag_mode: RAG mode for text queries — "graph_only" (default) or "vector_only".
        execute: For generate mode, whether to auto-execute if the Gremlin is read-only.
        include_evidence: For text mode, include supporting graph evidence in the response.
        max_context_items: For text mode, max context items the AI can use (default 20).

    Returns:
        dict: Standard envelope with answer, gremlin, execution results, or error.
    """

    if mode == "text":
        if not query:
            return envelope_err(
                "VALIDATION_ERROR",
                "query is required for mode='text'",
            )
        return query_graph_by_text(
            query=query,
            mode=rag_mode,
            include_evidence=include_evidence,
            max_context_items=max_context_items,
        )

    if mode == "generate":
        if not query:
            return envelope_err(
                "VALIDATION_ERROR",
                "query is required for mode='generate'",
            )
        return generate_gremlin(query=query, execute=execute)

    if mode == "gremlin":
        if not gremlin_query:
            return envelope_err(
                "VALIDATION_ERROR",
                "gremlin_query is required for mode='gremlin'",
            )
        result = execute_gremlin_read(gremlin_query)
        if isinstance(result, dict) and result.get("data") is not None and "error" not in result:
            return envelope_ok({
                "data": result.get("data"),
                "total": result.get("total"),
                "duration_ms": result.get("duration_ms"),
                "is_read": result.get("is_read", True),
            })
        return result

    return envelope_err(
        "VALIDATION_ERROR",
        f"Unknown mode: {mode!r}. Use 'text', 'generate', or 'gremlin'.",
        details={"mode": mode},
    )


@mcp.tool()
def manage_schema_tool(
    mode: str,
    operations: list[dict] | None = None,
    confirm: bool = False,
    plan_hash: str | None = None,
) -> dict:
    """Unified schema management entry point with design, validation, dry-run, and apply modes.

    This tool is always registered. In apply mode it performs a runtime
    SCHEMA_WRITE guard, requires confirm=True, and verifies the dry-run plan_hash
    against the current schema state before executing mutations.
    """

    return manage_schema(
        mode=mode,
        operations=operations,
        confirm=confirm,
        plan_hash=plan_hash,
    )


@mcp.tool()
def extract_graph_data_tool(
    text: str,
    schema: dict | None = None,
    example_prompt: str | None = None,
) -> dict:
    """Extract candidate graph data from text without writing to HugeGraph.

    Calls HugeGraph-AI /graph-extract and returns normalized graph_data with
    vertices and edges. This tool never mutates graph data.
    """

    return extract_graph_data(
        text=text,
        schema=schema,
        example_prompt=example_prompt,
    )


@mcp.tool()
def ingest_graph_data_tool(
    graph_data: dict,
    dry_run: bool = True,
    confirm: bool = False,
    plan_hash: str | None = None,
) -> dict:
    """Validate and import structured graph data with dry-run and plan_hash gating.

    dry_run defaults to true and returns a deterministic plan_hash plus mutation
    summary. Mutating imports require DATA_WRITE permission, confirm=True, and a
    matching plan_hash from dry-run.
    """

    return ingest_graph_data(
        graph_data=graph_data,
        dry_run=dry_run,
        confirm=confirm,
        plan_hash=plan_hash,
    )


@mcp.tool()
def refresh_vid_embeddings_tool(confirm: bool = False) -> dict:
    """Manually refresh VID embeddings through HugeGraph-AI.

    This tool is always registered, but mutating refresh requires INDEX_WRITE
    permission and confirm=True at runtime.
    """

    return refresh_vid_embeddings(confirm=confirm)


# Old write tools — always registered, runtime-guarded via envelope on readonly.
# When readonly, these return structured READONLY_VIOLATION instead of executing.

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
    """Execute schema operations (create vertex labels, edge labels, property keys, indexes).

    ⚠️ DEBUG TOOL — prefer manage_schema_tool for everyday schema operations.
    This low-level tool is always registered but returns a structured
    READONLY_VIOLATION when the server runs in read-only mode.

    Args:
        operations: List of schema operation dicts (see manage_schema_tool docs).

    Returns:
        dict: Execution result or structured readonly rejection.
    """

    return execute_schema_operations(operations)


@mcp.tool()
def execute_gremlin_write_tool(gremlin_query: str) -> dict:
    """Execute a Gremlin write query directly.

    ⚠️ DEBUG TOOL — prefer ingest_graph_data_tool for graph data writes.
    This low-level tool is always registered but returns a structured
    READONLY_VIOLATION when the server runs in read-only mode.

    Args:
        gremlin_query: A valid Gremlin write query string.

    Returns:
        dict: Write result or structured readonly rejection.
    """

    return execute_gremlin_write(gremlin_query)


def main() -> None:
    """CLI entry point used by console_scripts."""

    # Default to stdio; callers can also use `uv run fastmcp run` style entry.
    mcp.run()


if __name__ == "__main__":  # pragma: no cover - manual launch
    main()
