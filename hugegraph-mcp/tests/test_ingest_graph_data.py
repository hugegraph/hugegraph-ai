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

import re
from unittest.mock import Mock

from hugegraph_mcp.envelope import envelope_ok
from hugegraph_mcp.tools import ingest_graph_data as ingest_graph_data_module


def _graph_data():
    return {
        "vertices": [{"label": "person", "properties": {"name": "Alice"}}],
        "edges": [
            {
                "label": "knows",
                "source_label": "person",
                "target_label": "person",
                "source": {"name": "Alice"},
                "target": {"name": "Bob"},
            }
        ],
    }


def test_ingest_graph_data_dry_run():
    result = ingest_graph_data_module.ingest_graph_data(_graph_data())

    assert result["ok"] is True
    assert re.fullmatch(r"[0-9a-f]{16}", result["data"]["plan_hash"])
    assert result["data"]["mutation_summary"] == {"vertices": 1, "edges": 1}
    assert result["data"]["warnings"] == []


def test_ingest_graph_data_dry_run_same_input_same_hash():
    first = ingest_graph_data_module.ingest_graph_data(_graph_data())
    second = ingest_graph_data_module.ingest_graph_data(_graph_data())

    assert first["data"]["plan_hash"] == second["data"]["plan_hash"]


def test_ingest_graph_data_validate_invalid():
    result = ingest_graph_data_module.ingest_graph_data({"vertices": [{}], "edges": []})

    assert result["ok"] is False
    assert result["error"]["type"] == "INVALID_GRAPH_DATA"
    assert "missing required field: label" in result["error"]["details"]["errors"][0]


def test_ingest_graph_data_missing_confirm(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")

    result = ingest_graph_data_module.ingest_graph_data(
        _graph_data(),
        dry_run=False,
        confirm=False,
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "CONFIRM_REQUIRED"


def test_ingest_graph_data_plan_hash_mismatch(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")

    result = ingest_graph_data_module.ingest_graph_data(
        _graph_data(),
        dry_run=False,
        confirm=True,
        plan_hash="0000000000000000",
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "PLAN_HASH_MISMATCH"


def test_ingest_graph_data_readonly(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "true")

    result = ingest_graph_data_module.ingest_graph_data(
        _graph_data(),
        dry_run=False,
        confirm=True,
        plan_hash="0000000000000000",
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "READONLY_VIOLATION"


def test_ingest_graph_data_success(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    post = Mock(return_value=envelope_ok({"ok": True, "data": {"inserted": 2}}))
    monkeypatch.setattr(ingest_graph_data_module, "post", post)
    graph_data = _graph_data()
    dry_run = ingest_graph_data_module.ingest_graph_data(graph_data)

    result = ingest_graph_data_module.ingest_graph_data(
        graph_data,
        dry_run=False,
        confirm=True,
        plan_hash=dry_run["data"]["plan_hash"],
    )

    assert result["ok"] is True
    assert result["data"]["batch_id"].startswith("batch-")
    assert result["data"]["mutation_summary"] == {"vertices": 1, "edges": 1}
    assert result["data"]["import_result"] == {"inserted": 2}
    post.assert_called_once()
    assert post.call_args.args == ("/graph-import",)
    assert post.call_args.kwargs["json"]["schema"] is None
