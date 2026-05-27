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

from hugegraph_mcp.envelope import envelope_ok
from hugegraph_mcp import server


def test_import_graph_data_tool_extract_routes_to_extract(monkeypatch):
    calls = []

    def fake_extract_graph_data(text, schema=None, example_prompt=None):
        calls.append((text, schema, example_prompt))
        return envelope_ok({"graph_data": {"vertices": [], "edges": []}})

    monkeypatch.setattr(server, "extract_graph_data", fake_extract_graph_data)

    result = server.import_graph_data_tool(
        mode="extract",
        text="Alice knows Bob.",
        schema={"vertexlabels": ["person"]},
        example_prompt="extract people",
    )

    assert result["ok"] is True
    assert calls == [
        ("Alice knows Bob.", {"vertexlabels": ["person"]}, "extract people")
    ]


def test_import_graph_data_tool_ingest_routes_to_ingest(monkeypatch):
    calls = []
    graph_data = {"vertices": [], "edges": []}

    def fake_ingest_graph_data(
        graph_data,
        dry_run=True,
        confirm=False,
        plan_hash=None,
        nonce=None,
        expires_at=None,
    ):
        calls.append((graph_data, dry_run, confirm, plan_hash))
        return envelope_ok({"plan_hash": "0123456789abcdef"})

    monkeypatch.setattr(server, "ingest_graph_data", fake_ingest_graph_data)

    result = server.import_graph_data_tool(
        mode="ingest",
        graph_data=graph_data,
        dry_run=False,
        confirm=True,
        plan_hash="0123456789abcdef",
    )

    assert result["ok"] is True
    assert calls == [(graph_data, False, True, "0123456789abcdef")]


def test_import_graph_data_tool_validates_extract_text():
    result = server.import_graph_data_tool(mode="extract")

    assert result["ok"] is False
    assert result["error"]["type"] == "VALIDATION_ERROR"
    assert "text is required" in result["error"]["message"]


def test_import_graph_data_tool_validates_ingest_graph_data():
    result = server.import_graph_data_tool(mode="ingest")

    assert result["ok"] is False
    assert result["error"]["type"] == "VALIDATION_ERROR"
    assert "graph_data is required" in result["error"]["message"]


def test_import_graph_data_tool_rejects_unknown_mode():
    result = server.import_graph_data_tool(mode="unknown")

    assert result["ok"] is False
    assert result["error"]["type"] == "VALIDATION_ERROR"
    assert result["error"]["details"] == {"mode": "unknown"}


def test_import_graph_data_tool_table_returns_feature_disabled():
    result = server.import_graph_data_tool(mode="table", table_data={"rows": []})

    assert result["ok"] is False
    assert result["error"]["type"] == "FEATURE_DISABLED"
