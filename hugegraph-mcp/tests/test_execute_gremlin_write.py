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

import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class FakeGremlinClient:
    def __init__(self, results):
        self.results = results
        self.last_query = None

    def exec(self, query: str):
        self.last_query = query
        return self.results


def test_execute_gremlin_write_basic(monkeypatch):
    """Basic write path: uses write client, returns affected & is_write."""

    # Set readonly environment to false for this test
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    
    from hugegraph_mcp import gremlin_tools

    fake_client = FakeGremlinClient(results=[{"id": 1}, {"id": 2}])
    monkeypatch.setattr(gremlin_tools, "_get_write_client", lambda: fake_client, raising=False)

    res = gremlin_tools.execute_gremlin_write("g.addV('person').property('name','Alice')")

    assert fake_client.last_query is not None
    assert fake_client.last_query.startswith("g.addV")
    assert res["is_write"] is True
    assert res["affected"] == 2
    assert isinstance(res["duration_ms"], (int, float))




def test_execute_gremlin_write_blocked_in_readonly(monkeypatch):
    """When HUGEGRAPH_MCP_READONLY is true, write tool must be blocked."""

    # Set readonly environment to true for this test
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "true")

    from hugegraph_mcp import gremlin_tools

    fake_client = FakeGremlinClient(results=[])
    monkeypatch.setattr(gremlin_tools, "_get_write_client", lambda: fake_client, raising=False)

    with pytest.raises(PermissionError):
        gremlin_tools.execute_gremlin_write("g.addV('person')")
