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

import pytest
from unittest.mock import patch, Mock
import requests
from hugegraph_mcp.gremlin_tools import execute_gremlin_read, execute_gremlin_write


def test_connection_error_handling():
    """Test handling of connection errors."""
    with patch('hugegraph_mcp.gremlin_tools._get_read_client') as mock_client:
        mock_client_instance = Mock()
        mock_client_instance.exec.side_effect = requests.exceptions.ConnectionError("Connection refused")
        mock_client.return_value = mock_client_instance
        
        result = execute_gremlin_read("g.V().count()")
        
        assert result["success"] is False
        assert result["error_type"] == "connection_error"
        assert "Cannot connect to HugeGraph server" in result["message"]
        assert len(result["suggestions"]) > 0
        assert "Check if HugeGraph server is running" in result["suggestions"]


def test_http_500_error_handling():
    """Test handling of HTTP 500 server errors."""
    with patch('hugegraph_mcp.gremlin_tools._get_write_client') as mock_client:
        mock_client_instance = Mock()
        
        # Create a mock response with status code 500
        mock_response = Mock()
        mock_response.status_code = 500
        error = requests.exceptions.HTTPError("Internal Server Error", response=mock_response)
        mock_client_instance.exec.side_effect = error
        mock_client.return_value = mock_client_instance
        
        result = execute_gremlin_write("g.addV('test')")
        
        assert result["success"] is False
        assert result["error_type"] == "server_error"
        assert "HugeGraph server internal error" in result["message"]
        assert result["status_code"] == 500
        assert "Check the Gremlin query syntax" in result["suggestions"]


def test_authentication_error_handling():
    """Test handling of authentication errors (401)."""
    with patch('hugegraph_mcp.gremlin_tools._get_read_client') as mock_client:
        mock_client_instance = Mock()
        
        # Create a mock response with status code 401
        mock_response = Mock()
        mock_response.status_code = 401
        error = requests.exceptions.HTTPError("Unauthorized", response=mock_response)
        mock_client_instance.exec.side_effect = error
        mock_client.return_value = mock_client_instance
        
        result = execute_gremlin_read("g.V().limit(10)")
        
        assert result["success"] is False
        assert result["error_type"] == "authentication_error"
        assert "Authentication failed" in result["message"]
        assert any("Check HUGEGRAPH_USER" in suggestion for suggestion in result["suggestions"])


def test_readonly_mode_error():
    """Test readonly mode error handling."""
    with patch.dict('os.environ', {'HUGEGRAPH_MCP_READONLY': 'true'}):
        with pytest.raises(PermissionError) as exc_info:
            execute_gremlin_write("g.addV('test')")
        
        assert "read-only mode" in str(exc_info.value)


def test_validation_error_for_read_operations():
    """Test validation error when trying to use write keywords in read operations."""
    with pytest.raises(ValueError) as exc_info:
        execute_gremlin_read("g.addV('test')")
    
    assert "write operations" in str(exc_info.value)


def test_syntax_error_handling():
    """Test handling of Gremlin syntax errors."""
    with patch('hugegraph_mcp.gremlin_tools._get_read_client') as mock_client:
        mock_client_instance = Mock()
        mock_client_instance.exec.side_effect = ValueError("Invalid Gremlin syntax")
        mock_client.return_value = mock_client_instance
        
        result = execute_gremlin_read("g.invalidSyntax()")
        
        assert result["success"] is False
        assert result["error_type"] == "query_syntax_error"
        assert "syntax error" in result["message"]


def test_unknown_error_handling():
    """Test handling of unexpected errors."""
    with patch('hugegraph_mcp.gremlin_tools._get_read_client') as mock_client:
        mock_client_instance = Mock()
        mock_client_instance.exec.side_effect = RuntimeError("Unexpected error")
        mock_client.return_value = mock_client_instance
        
        result = execute_gremlin_read("g.V().count()")
        
        assert result["success"] is False
        assert result["error_type"] == "unknown_error"
        assert "Unexpected error" in result["message"]


def test_successful_execution_preserves_format():
    """Test that successful execution maintains the expected format."""
    with patch('hugegraph_mcp.gremlin_tools._get_read_client') as mock_client:
        mock_client_instance = Mock()
        mock_client_instance.exec.return_value = [{"id": "1", "label": "person"}]
        mock_client.return_value = mock_client_instance
        
        result = execute_gremlin_read("g.V().limit(1)")
        
        # Successful execution returns the original format without success field
        assert "data" in result
        assert "total" in result
        assert "duration_ms" in result
        assert result["is_read"] is True
        assert result["total"] == 1
