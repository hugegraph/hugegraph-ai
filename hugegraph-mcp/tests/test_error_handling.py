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

"""Test improved error handling for Gremlin operations."""

from unittest.mock import Mock, patch

import requests
from hugegraph_mcp.gremlin_tools import execute_gremlin_read, execute_gremlin_write


def test_connection_error_handling():
    """Test handling of connection errors."""
    with patch("hugegraph_mcp.gremlin_tools._get_read_client") as mock_client:
        mock_client_instance = Mock()
        mock_client_instance.exec.side_effect = requests.exceptions.ConnectionError(
            "Connection refused"
        )
        mock_client.return_value = mock_client_instance

        result = execute_gremlin_read("g.V().count()")

        assert result["ok"] is False
        assert result["error"]["type"] == "CONNECTION_FAILED"
        assert "Cannot connect to HugeGraph server" in result["error"]["message"]
        assert "Check if HugeGraph server is running" in result["error"]["suggestion"]
        assert result["error"]["details"]["error_type"] == "connection_error"
        assert result["error"]["retryable"] is True


def test_read_client_initialization_connection_error_is_enveloped():
    """Connection failures while constructing the client should not escape."""
    with patch("hugegraph_mcp.gremlin_tools._get_read_client") as mock_client:
        mock_client.side_effect = requests.exceptions.ConnectionError(
            "Connection refused during init"
        )

        result = execute_gremlin_read("g.V().count()")

        assert result["ok"] is False
        assert result["error"]["type"] == "CONNECTION_FAILED"
        assert "Cannot connect to HugeGraph server" in result["error"]["message"]
        assert result["error"]["details"]["error_type"] == "connection_error"
        assert result["error"]["retryable"] is True


def test_write_client_initialization_connection_error_is_enveloped(monkeypatch):
    """Write client construction failures should use the same envelope path."""
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    monkeypatch.setenv("HUGEGRAPH_MCP_ADMIN_MODE", "true")
    with patch("hugegraph_mcp.gremlin_tools._get_write_client") as mock_client:
        mock_client.side_effect = requests.exceptions.ConnectionError(
            "Connection refused during init"
        )

        result = execute_gremlin_write("g.addV('test')")

        assert result["ok"] is False
        assert result["error"]["type"] == "CONNECTION_FAILED"
        assert "Cannot connect to HugeGraph server" in result["error"]["message"]
        assert result["error"]["details"]["error_type"] == "connection_error"
        assert result["error"]["retryable"] is True


def test_http_500_error_handling(monkeypatch):
    """Test handling of HTTP 500 server errors."""
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    monkeypatch.setenv("HUGEGRAPH_MCP_ADMIN_MODE", "true")
    with patch("hugegraph_mcp.gremlin_tools._get_write_client") as mock_client:
        mock_client_instance = Mock()

        # Create a mock response with status code 500
        mock_response = Mock()
        mock_response.status_code = 500
        error = requests.exceptions.HTTPError(
            "Internal Server Error", response=mock_response
        )
        mock_client_instance.exec.side_effect = error
        mock_client.return_value = mock_client_instance

        result = execute_gremlin_write("g.addV('test')")

        assert result["ok"] is False
        assert result["error"]["type"] == "SERVER_ERROR"
        assert "HugeGraph server internal error" in result["error"]["message"]
        assert result["error"]["details"]["error_type"] == "server_error"
        assert result["error"]["details"]["status_code"] == 500
        assert "Check the Gremlin query syntax" in result["error"]["suggestion"]
        assert result["error"]["retryable"] is True


def test_http_503_error_is_retryable():
    """Temporary 5xx HTTP failures should be retryable."""
    with patch("hugegraph_mcp.gremlin_tools._get_read_client") as mock_client:
        mock_client_instance = Mock()

        mock_response = Mock()
        mock_response.status_code = 503
        error = requests.exceptions.HTTPError(
            "Service Unavailable", response=mock_response
        )
        mock_client_instance.exec.side_effect = error
        mock_client.return_value = mock_client_instance

        result = execute_gremlin_read("g.V().limit(10)")

        assert result["ok"] is False
        assert result["error"]["type"] == "SERVER_ERROR"
        assert result["error"]["details"]["error_type"] == "http_error"
        assert result["error"]["details"]["status_code"] == 503
        assert result["error"]["retryable"] is True


def test_http_404_error_handling():
    """Test handling of HTTP 404 graph or endpoint errors."""
    with patch("hugegraph_mcp.gremlin_tools._get_read_client") as mock_client:
        mock_client_instance = Mock()

        mock_response = Mock()
        mock_response.status_code = 404
        error = requests.exceptions.HTTPError("Not Found", response=mock_response)
        mock_client_instance.exec.side_effect = error
        mock_client.return_value = mock_client_instance

        result = execute_gremlin_read("g.V().limit(10)")

        assert result["ok"] is False
        assert result["error"]["type"] == "NOT_FOUND"
        assert "Graph or endpoint not found" in result["error"]["message"]
        assert result["error"]["details"]["error_type"] == "not_found_error"
        assert result["error"]["details"]["status_code"] == 404
        assert result["error"]["retryable"] is False


def test_timeout_error_handling():
    """Test handling of request timeouts."""
    with patch("hugegraph_mcp.gremlin_tools._get_read_client") as mock_client:
        mock_client_instance = Mock()
        mock_client_instance.exec.side_effect = requests.exceptions.Timeout(
            "Read timed out"
        )
        mock_client.return_value = mock_client_instance

        result = execute_gremlin_read("g.V().count()")

        assert result["ok"] is False
        assert result["error"]["type"] == "TIMEOUT"
        assert "timed out" in result["error"]["message"]
        assert result["error"]["details"]["error_type"] == "timeout_error"
        assert result["error"]["retryable"] is True


def test_authentication_error_handling():
    """Test handling of authentication errors (401)."""
    with patch("hugegraph_mcp.gremlin_tools._get_read_client") as mock_client:
        mock_client_instance = Mock()

        # Create a mock response with status code 401
        mock_response = Mock()
        mock_response.status_code = 401
        error = requests.exceptions.HTTPError("Unauthorized", response=mock_response)
        mock_client_instance.exec.side_effect = error
        mock_client.return_value = mock_client_instance

        result = execute_gremlin_read("g.V().limit(10)")

        assert result["ok"] is False
        assert result["error"]["type"] == "AUTHENTICATION_FAILED"
        assert "Authentication failed" in result["error"]["message"]
        assert "Check HUGEGRAPH_USER" in result["error"]["suggestion"]
        assert result["error"]["details"]["error_type"] == "authentication_error"


def test_readonly_mode_error():
    """Test readonly mode error handling."""
    with patch.dict("os.environ", {"HUGEGRAPH_MCP_READONLY": "true"}):
        result = execute_gremlin_write("g.addV('test')")

        assert result["ok"] is False
        assert result["error"]["type"] == "READONLY_VIOLATION"
        assert result["meta"]["readonly"] is True


def test_validation_error_for_read_operations():
    """Test validation error when trying to use write keywords in read operations."""
    result = execute_gremlin_read("g.addV('test')")

    assert result["ok"] is False
    assert result["error"]["type"] == "UNSAFE_GREMLIN"
    assert "write" in result["error"]["message"].lower()


def test_syntax_error_handling():
    """Test handling of Gremlin syntax errors."""
    with patch("hugegraph_mcp.gremlin_tools._get_read_client") as mock_client:
        mock_client_instance = Mock()
        mock_client_instance.exec.side_effect = ValueError("Invalid Gremlin syntax")
        mock_client.return_value = mock_client_instance

        result = execute_gremlin_read("g.V().count()")

        assert result["ok"] is False
        assert result["error"]["type"] == "QUERY_SYNTAX_ERROR"
        assert "syntax error" in result["error"]["message"]
        assert result["error"]["details"]["error_type"] == "query_syntax_error"
        assert result["error"]["retryable"] is False


def test_unknown_error_handling():
    """Test handling of unexpected errors."""
    with patch("hugegraph_mcp.gremlin_tools._get_read_client") as mock_client:
        mock_client_instance = Mock()
        mock_client_instance.exec.side_effect = RuntimeError("Unexpected error")
        mock_client.return_value = mock_client_instance

        result = execute_gremlin_read("g.V().count()")

        assert result["ok"] is False
        assert result["error"]["type"] == "SERVER_ERROR"
        assert "Unexpected error" in result["error"]["message"]
        assert result["error"]["details"]["error_type"] == "unknown_error"


def test_no_index_exception_is_classified_as_no_index():
    """HugeGraph NoIndexException should not be reported as a connection failure."""
    with patch("hugegraph_mcp.gremlin_tools._get_read_client") as mock_client:
        mock_client_instance = Mock()
        mock_client_instance.exec.side_effect = RuntimeError(
            "Gremlin can't get results: Server Exception: "
            "org.apache.hugegraph.exception.NoIndexException"
        )
        mock_client.return_value = mock_client_instance

        result = execute_gremlin_read("g.V().has('occupation','engineer')")

        assert result["ok"] is False
        assert result["error"]["type"] == "NO_INDEX"
        assert result["error"]["details"]["error_type"] == "no_index_error"
        assert "Create an index" in result["error"]["suggestion"]
        assert result["error"]["retryable"] is False


def test_successful_execution_preserves_format():
    """Test that successful execution maintains the expected format."""
    with patch("hugegraph_mcp.gremlin_tools._get_read_client") as mock_client:
        mock_client_instance = Mock()
        mock_client_instance.exec.return_value = [{"id": "1", "label": "person"}]
        mock_client.return_value = mock_client_instance

        result = execute_gremlin_read("g.V().limit(1)")

        assert result["ok"] is True
        assert result["error"] is None
        assert result["data"]["is_read"] is True
        assert result["data"]["total"] == 1
        assert result["data"]["data"] == [{"id": "1", "label": "person"}]
        assert isinstance(result["meta"]["duration_ms"], (int, float))
