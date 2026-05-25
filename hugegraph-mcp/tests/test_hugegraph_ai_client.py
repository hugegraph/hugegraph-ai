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

from unittest.mock import Mock

import requests

from hugegraph_mcp.config import MCPConfig
from hugegraph_mcp.hugegraph_ai_client import get, health_check, post, request


class FakeResponse:
    def __init__(self, data=None, status_code: int = 200):
        self._data = data
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(
                f"HTTP {self.status_code}", response=self
            )

    def json(self):
        if isinstance(self._data, Exception):
            raise self._data
        return self._data


def _cfg(**overrides):
    values = {
        "ai_url": "http://ai.example:8001",
        "allow_ai": True,
        "timeout_seconds": 7,
    }
    values.update(overrides)
    return MCPConfig(**values)


def test_request_success(monkeypatch):
    http_request = Mock(return_value=FakeResponse({"status": "ok"}))
    monkeypatch.setattr("hugegraph_mcp.hugegraph_ai_client.requests.request", http_request)

    result = request("GET", "/health", cfg=_cfg())

    assert result["ok"] is True
    assert result["data"] == {"status": "ok"}
    http_request.assert_called_once_with(
        "GET",
        "http://ai.example:8001/health",
        params=None,
        headers=None,
        timeout=7,
    )


def test_request_connection_error(monkeypatch):
    monkeypatch.setattr(
        "hugegraph_mcp.hugegraph_ai_client.requests.request",
        Mock(side_effect=requests.exceptions.ConnectionError("connection refused")),
    )

    result = request("GET", "/health", cfg=_cfg())

    assert result["ok"] is False
    assert result["error"]["type"] == "HUGEGRAPH_AI_UNAVAILABLE"


def test_request_timeout(monkeypatch):
    monkeypatch.setattr(
        "hugegraph_mcp.hugegraph_ai_client.requests.request",
        Mock(side_effect=requests.exceptions.Timeout("timed out")),
    )

    result = request("GET", "/health", cfg=_cfg())

    assert result["ok"] is False
    assert result["error"]["type"] == "HUGEGRAPH_AI_UNAVAILABLE"


def test_request_http_500(monkeypatch):
    monkeypatch.setattr(
        "hugegraph_mcp.hugegraph_ai_client.requests.request",
        Mock(return_value=FakeResponse({"error": "boom"}, status_code=500)),
    )

    result = request("GET", "/health", cfg=_cfg())

    assert result["ok"] is False
    assert result["error"]["type"] == "HUGEGRAPH_AI_UNAVAILABLE"
    assert result["error"]["details"]["status_code"] == 500


def test_request_allow_ai_disabled(monkeypatch):
    http_request = Mock()
    monkeypatch.setattr("hugegraph_mcp.hugegraph_ai_client.requests.request", http_request)

    result = request("GET", "/health", cfg=_cfg(allow_ai=False))

    assert result["ok"] is False
    assert result["error"]["type"] == "HUGEGRAPH_AI_UNAVAILABLE"
    assert result["error"]["message"] == "AI calls are disabled"
    http_request.assert_not_called()


def test_post_convenience(monkeypatch):
    http_request = Mock(return_value=FakeResponse({"gremlin": "g.V().count()"}))
    monkeypatch.setattr("hugegraph_mcp.hugegraph_ai_client.requests.request", http_request)

    result = post("/generate-gremlin", cfg=_cfg(), json={"question": "count vertices"})

    assert result["ok"] is True
    http_request.assert_called_once_with(
        "POST",
        "http://ai.example:8001/generate-gremlin",
        params=None,
        headers=None,
        timeout=7,
        json={"question": "count vertices"},
    )


def test_get_convenience(monkeypatch):
    http_request = Mock(return_value=FakeResponse({"ready": True}))
    monkeypatch.setattr("hugegraph_mcp.hugegraph_ai_client.requests.request", http_request)

    result = get("/graph-index-info", cfg=_cfg())

    assert result["ok"] is True
    http_request.assert_called_once_with(
        "GET",
        "http://ai.example:8001/graph-index-info",
        params=None,
        headers=None,
        timeout=7,
    )


def test_health_check(monkeypatch):
    http_request = Mock(return_value=FakeResponse({"ok": True, "data": "ready"}))
    monkeypatch.setattr("hugegraph_mcp.hugegraph_ai_client.requests.request", http_request)

    result = health_check(cfg=_cfg())

    assert result["ok"] is True
    assert result["data"]["status"] == "available"
    assert result["data"]["health_endpoint"] == "/graph-index-info"
    http_request.assert_called_once_with(
        "GET",
        "http://ai.example:8001/graph-index-info",
        params=None,
        headers=None,
        timeout=7,
    )


def test_health_check_falls_back_to_openapi(monkeypatch):
    http_request = Mock(
        side_effect=[
            FakeResponse({"detail": "missing"}, status_code=404),
            FakeResponse({"openapi": "3.1.0"}),
        ]
    )
    monkeypatch.setattr("hugegraph_mcp.hugegraph_ai_client.requests.request", http_request)

    result = health_check(cfg=_cfg())

    assert result["ok"] is True
    assert result["data"]["status"] == "available"
    assert result["data"]["health_endpoint"] == "/openapi.json"
    assert result["data"]["openapi"] == "3.1.0"
    assert len(result["warnings"]) == 1
    assert http_request.call_args_list[0].args[:2] == (
        "GET",
        "http://ai.example:8001/graph-index-info",
    )
    assert http_request.call_args_list[1].args[:2] == (
        "GET",
        "http://ai.example:8001/openapi.json",
    )
