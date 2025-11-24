# FastMCP server bootstrap for HugeGraph MCP

import logging
import os

from fastmcp import FastMCP

from hugegraph_mcp.schema_tools import execute_schema_operations, get_live_schema
from hugegraph_mcp.gremlin_tools import execute_gremlin_read, execute_gremlin_write


# Suppress FastMCP info-level logs (e.g. "Starting server ...") so that
# stdout is reserved for MCP JSON protocol only. Windsurf's MCP client
# reads stdout as a pure JSON stream and will fail if human-readable logs
# are mixed in.
logging.disable(logging.CRITICAL)

# Check if server should run in read-only mode
def _is_readonly():
    readonly_env = os.getenv("HUGEGRAPH_MCP_READONLY", "").lower()
    return readonly_env in {"1", "true", "yes"}

READONLY = _is_readonly()

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
    def execute_schema_operations_tool(operations: list[dict]) -> dict:
        """Execute schema operations (create/modify vertex labels, edge labels, property keys, indexes).

        This tool allows you to modify your graph schema by:
        - Creating new property keys with specified data types
        - Creating vertex and edge labels with defined properties
        - Creating index labels for query optimization
        
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
