import os
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

from pyhugegraph.client import PyHugeClient
import requests


@dataclass
class HugeGraphGremlinConfig:
    url: str = "http://127.0.0.1:8080"
    graph: str = "hugegraph"
    user: str = "admin"
    password: str = ""
    graphspace: Optional[str] = None

    @classmethod
    def from_env(cls) -> "HugeGraphGremlinConfig":
        return cls(
            url=os.getenv("HUGEGRAPH_URL", "http://127.0.0.1:8080"),
            graph=os.getenv("HUGEGRAPH_GRAPH_NAME", "hugegraph"),
            user=os.getenv("HUGEGRAPH_USER", "admin"),
            password=os.getenv("HUGEGRAPH_PASSWORD", ""),
            graphspace=os.getenv("HUGEGRAPH_GRAPH_SPACE") or None,
        )


_cfg = HugeGraphGremlinConfig.from_env()


class GremlinExecutor:
    """Encapsulate HugeGraph Gremlin read/write clients.

    当前实现仍然基于 HTTP REST + pyhugegraph.gremlin()，后续可以在这里
    切换为 WebSocket 或按 HUGEGRAPH_READ_URL/HUGEGRAPH_WRITE_URL 拆分端点。
    """

    def __init__(self, cfg: HugeGraphGremlinConfig) -> None:
        self._cfg = cfg

    def _build_client(self) -> PyHugeClient:
        return PyHugeClient(
            url=self._cfg.url,
            graph=self._cfg.graph,
            user=self._cfg.user,
            pwd=self._cfg.password,
            graphspace=self._cfg.graphspace,
        )

    def get_read_client(self):
        return self._build_client().gremlin()

    def get_write_client(self):
        return self._build_client().gremlin()


_executor = GremlinExecutor(_cfg)


def _get_read_client():
    return _executor.get_read_client()


def _get_write_client():
    return _executor.get_write_client()


_WRITE_KEYWORDS = ("addV", "addE", "dropV", "dropE", "property(")


def _execute_gremlin_with_error_handling(client, gremlin_query: str, operation_type: str = "read") -> Dict[str, Any]:
    """Execute Gremlin query with comprehensive error handling.
    
    Args:
        client: The Gremlin client instance
        gremlin_query: The Gremlin query to execute
        operation_type: "read" or "write" for context in error messages
        
    Returns:
        Dict containing either successful result or structured error information
    """
    start = time.time()
    
    try:
        data = client.exec(gremlin_query)
        duration_ms = (time.time() - start) * 1000.0
        
        # Try to count results
        try:
            count = len(data)  # type: ignore[arg-type]
        except TypeError:
            count = 1 if data is not None else 0
            
        return {
            "success": True,
            "data": data,
            "count": count,
            "duration_ms": duration_ms,
            "operation_type": operation_type,
        }
        
    except requests.exceptions.ConnectionError as e:
        return {
            "success": False,
            "error_type": "connection_error",
            "message": f"Cannot connect to HugeGraph server at {client._url if hasattr(client, '_url') else 'unknown address'}",
            "suggestions": [
                "Check if HugeGraph server is running",
                "Verify the HUGEGRAPH_URL environment variable",
                "Check network connectivity to the server"
            ],
            "duration_ms": (time.time() - start) * 1000.0,
            "operation_type": operation_type,
        }
        
    except requests.exceptions.HTTPError as e:
        status_code = e.response.status_code if hasattr(e, 'response') and e.response else "unknown"
        
        if status_code == 401:
            error_type = "authentication_error"
            message = "Authentication failed - invalid credentials"
            suggestions = [
                "Check HUGEGRAPH_USER and HUGEGRAPH_PASSWORD environment variables",
                "Verify user permissions in HugeGraph"
            ]
        elif status_code == 403:
            error_type = "authorization_error"
            message = "Authorization failed - insufficient permissions"
            suggestions = [
                "Check if the user has permission to execute Gremlin queries",
                "Verify graph space permissions if using graph spaces"
            ]
        elif status_code == 404:
            error_type = "not_found_error"
            message = "Graph or endpoint not found"
            suggestions = [
                "Check if the graph name is correct",
                "Verify the graph exists in HugeGraph"
            ]
        elif status_code == 500:
            error_type = "server_error"
            message = "HugeGraph server internal error"
            suggestions = [
                "Check the Gremlin query syntax",
                "Verify all referenced vertex/edge labels exist",
                "Check HugeGraph server logs for details",
                "Ensure the query doesn't violate graph constraints"
            ]
        else:
            error_type = "http_error"
            message = f"HTTP error {status_code}"
            suggestions = [
                "Check HugeGraph server status",
                "Verify the request format"
            ]
            
        return {
            "success": False,
            "error_type": error_type,
            "message": message,
            "status_code": status_code,
            "suggestions": suggestions,
            "duration_ms": (time.time() - start) * 1000.0,
            "operation_type": operation_type,
        }
        
    except ValueError as e:
        return {
            "success": False,
            "error_type": "query_syntax_error",
            "message": f"Gremlin query syntax error: {str(e)}",
            "suggestions": [
                "Check Gremlin query syntax",
                "Verify all steps and parameters are valid",
                "Ensure proper use of Gremlin traversal steps"
            ],
            "duration_ms": (time.time() - start) * 1000.0,
            "operation_type": operation_type,
        }
        
    except Exception as e:
        return {
            "success": False,
            "error_type": "unknown_error",
            "message": f"Unexpected error: {str(e)}",
            "suggestions": [
                "Check HugeGraph server logs",
                "Verify the query format and parameters",
                "Try a simpler query to test connectivity"
            ],
            "duration_ms": (time.time() - start) * 1000.0,
            "operation_type": operation_type,
        }


def execute_gremlin_read(gremlin_query: str) -> Dict[str, Any]:
    """Execute a read-only Gremlin query and return standardized metadata.

    - Rejects queries that clearly contain write keywords.
    - Returns: {data, total, duration_ms, is_read} or structured error information.
    """

    # Validate query doesn't contain write operations
    lowered = gremlin_query.lower()
    if any(k.lower() in lowered for k in _WRITE_KEYWORDS):
        # For backward compatibility, raise ValueError as expected by existing tests
        raise ValueError("execute_gremlin_read does not allow write operations")

    client = _get_read_client()
    result = _execute_gremlin_with_error_handling(client, gremlin_query, "read")
    
    # Transform successful result to match expected format
    if result.get("success"):
        return {
            "data": result["data"],
            "total": result["count"],
            "duration_ms": result["duration_ms"],
            "is_read": True,
        }
    else:
        # Return error result as-is (already structured)
        return result


def execute_gremlin_write(gremlin_query: str) -> Dict[str, Any]:
    """Execute a Gremlin write query and return affected count & metadata.

    Behaviour as per tests:
    - Uses a dedicated write client.
    - When HUGEGRAPH_MCP_READONLY is true, raise PermissionError.
    - Returns structured error information for all failure cases.
    """

    # Global readonly guard for all write operations
    if os.getenv("HUGEGRAPH_MCP_READONLY", "").lower() in {"1", "true", "yes"}:
        # For backward compatibility with existing tests, raise PermissionError
        raise PermissionError("HugeGraph MCP server is in read-only mode; write queries are disabled")

    client = _get_write_client()
    result = _execute_gremlin_with_error_handling(client, gremlin_query, "write")
    
    # Transform successful result to match expected format
    if result.get("success"):
        return {
            "success": True,
            "affected": result["count"],
            "duration_ms": result["duration_ms"],
            "is_write": True,
        }
    else:
        # Return error result as-is (already structured)
        return result
