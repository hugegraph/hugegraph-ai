import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


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
    monkeypatch.setattr(gremlin_tools, "_get_read_client", lambda: client, raising=False)

    result = gremlin_tools.execute_gremlin_read("g.V().limit(2)")

    assert client.last_query == "g.V().limit(2)"
    assert result["is_read"] is True
    assert result["total"] == 2
    assert isinstance(result["duration_ms"], (int, float))


def test_execute_gremlin_read_rejects_obvious_writes(monkeypatch):
    """Queries with clear write keywords must be rejected even through read tool."""

    from hugegraph_mcp import gremlin_tools

    client = FakeGremlinClient()
    monkeypatch.setattr(gremlin_tools, "_get_read_client", lambda: client, raising=False)

    with pytest.raises(ValueError):
        gremlin_tools.execute_gremlin_read("g.addV('person')")


def test_execute_gremlin_read_respects_readonly_env(monkeypatch):
    """When HUGEGRAPH_MCP_READONLY is true, execute_gremlin_read should still work (it's read)."""

    os.environ["HUGEGRAPH_MCP_READONLY"] = "true"

    from hugegraph_mcp import gremlin_tools

    client = FakeGremlinClient()
    monkeypatch.setattr(gremlin_tools, "_get_read_client", lambda: client, raising=False)

    result = gremlin_tools.execute_gremlin_read("g.V().count()")

    assert result["is_read"] is True
    assert "total" in result
