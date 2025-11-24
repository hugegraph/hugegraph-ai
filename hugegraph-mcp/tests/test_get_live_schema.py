import os
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class FakeSchemaManager:
    def __init__(self, schema):
        self._schema = schema

    def getSchema(self, _format: str = "json"):
        return self._schema


class FakePyHugeClient:
    last_init_kwargs: dict | None = None
    schema_data: dict | None = None

    def __init__(self, url: str, graph: str, user: str, pwd: str, graphspace=None, timeout=None):
        FakePyHugeClient.last_init_kwargs = {
            "url": url,
            "graph": graph,
            "user": user,
            "pwd": pwd,
            "graphspace": graphspace,
            "timeout": timeout,
        }
        self._schema = FakePyHugeClient.schema_data

    def schema(self):
        return FakeSchemaManager(self._schema)


def _make_full_schema():
    return {
        "vertexlabels": [
            {"id": 1, "name": "person", "properties": ["name", "age"]},
        ],
        "edgelabels": [
            {
                "name": "knows",
                "source_label": "person",
                "target_label": "person",
                "properties": ["since"],
            }
        ],
        "propertykeys": [
            {"name": "name", "data_type": "TEXT"},
            {"name": "age", "data_type": "INT"},
            {"name": "since", "data_type": "INT"},
        ],
    }


def test_get_live_schema_basic(monkeypatch):
    from hugegraph_mcp import schema_tools

    FakePyHugeClient.schema_data = _make_full_schema()
    monkeypatch.setattr(schema_tools, "PyHugeClient", FakePyHugeClient)

    result = schema_tools.get_live_schema()

    assert "schema" in result
    assert result["schema"] == FakePyHugeClient.schema_data
    assert "simple_schema" in result
    simple = result["simple_schema"]
    assert "vertexlabels" in simple
    assert "edgelabels" in simple
    assert simple["vertexlabels"][0]["name"] == "person"
    assert simple["edgelabels"][0]["name"] == "knows"


def test_get_live_schema_with_graphspace(monkeypatch):
    os.environ["HUGEGRAPH_GRAPH_SPACE"] = "mcp_space"

    from hugegraph_mcp import schema_tools

    FakePyHugeClient.schema_data = _make_full_schema()
    monkeypatch.setattr(schema_tools, "PyHugeClient", FakePyHugeClient)

    result = schema_tools.get_live_schema()

    assert FakePyHugeClient.last_init_kwargs["graphspace"] == "mcp_space"
    assert result.get("graphspace") == "mcp_space"


def test_get_live_schema_respects_readonly_flag(monkeypatch):
    os.environ["HUGEGRAPH_MCP_READONLY"] = "true"

    from hugegraph_mcp import schema_tools

    FakePyHugeClient.schema_data = _make_full_schema()
    monkeypatch.setattr(schema_tools, "PyHugeClient", FakePyHugeClient)

    result = schema_tools.get_live_schema()

    assert result.get("readonly") is True
