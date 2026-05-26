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


class FakeGremlinClient:
    def __init__(self):
        self.last_query = None

    def exec(self, query: str):  # minimal interface for tests
        self.last_query = query
        # return a fake list result
        return ["alice", "bob"]


def test_execute_gremlin_read_basic(monkeypatch):
    """Basic happy path: query is executed with read client and returns data/total/duration/is_read."""

    from hugegraph_mcp import gremlin_tools  # to be implemented

    client = FakeGremlinClient()
    monkeypatch.setattr(
        gremlin_tools, "_get_read_client", lambda: client, raising=False
    )

    result = gremlin_tools.execute_gremlin_read("g.V().limit(2)")

    assert client.last_query == "g.V().limit(2)"
    assert result["ok"] is True
    assert result["error"] is None
    assert result["data"]["is_read"] is True
    assert result["data"]["total"] == 2
    assert isinstance(result["data"]["duration_ms"], (int, float))
    assert result["meta"]["duration_ms"] == result["data"]["duration_ms"]


def test_execute_gremlin_read_rejects_obvious_writes(monkeypatch):
    """Queries with clear write keywords must be rejected even through read tool."""

    from hugegraph_mcp import gremlin_tools

    client = FakeGremlinClient()
    monkeypatch.setattr(
        gremlin_tools, "_get_read_client", lambda: client, raising=False
    )

    result = gremlin_tools.execute_gremlin_read("g.addV('person')")

    assert result["ok"] is False
    assert result["error"]["type"] == "UNSAFE_GREMLIN"
    assert result["meta"]


def test_execute_gremlin_read_respects_readonly_env(monkeypatch):
    """When HUGEGRAPH_MCP_READONLY is true, execute_gremlin_read should still work (it's read)."""

    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "true")

    from hugegraph_mcp import gremlin_tools

    client = FakeGremlinClient()
    monkeypatch.setattr(
        gremlin_tools, "_get_read_client", lambda: client, raising=False
    )

    result = gremlin_tools.execute_gremlin_read("g.V().count()")

    assert result["ok"] is True
    assert result["data"]["is_read"] is True
    assert "total" in result["data"]
