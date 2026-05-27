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

import json
import re
from unittest.mock import Mock

from hugegraph_mcp.envelope import envelope_ok
from hugegraph_mcp.tools import ingest_graph_data as ingest_graph_data_module


def _graph_data():
    return {
        "vertices": [
            {"label": "person", "properties": {"name": "Alice"}},
            {"label": "person", "properties": {"name": "Bob"}},
        ],
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


def _live_schema():
    return {
        "schema": {
            "vertexlabels": [
                {
                    "id": 1,
                    "name": "person",
                    "properties": [{"name": "name"}, {"name": "age"}],
                    "primary_keys": ["name"],
                },
            ],
            "edgelabels": [
                {"name": "knows", "source_label": "person", "target_label": "person"},
            ],
            "propertykeys": [
                {"name": "name", "data_type": "TEXT"},
                {"name": "age", "data_type": "INT"},
            ],
        },
    }


def _mock_schema(monkeypatch):
    monkeypatch.setattr(
        ingest_graph_data_module, "_fetch_live_schema", lambda: _live_schema()
    )


def test_ingest_graph_data_accepts_string_property_schema(monkeypatch):
    schema = _live_schema()
    schema["schema"]["vertexlabels"][0]["properties"] = ["name", "age"]
    schema["schema"]["edgelabels"][0]["properties"] = ["since"]
    monkeypatch.setattr(ingest_graph_data_module, "_fetch_live_schema", lambda: schema)

    result = ingest_graph_data_module.ingest_graph_data(
        {
            "vertices": [
                {"label": "person", "properties": {"name": "Alice", "age": 30}},
                {"label": "person", "properties": {"name": "Bob", "age": 31}},
            ],
            "edges": [
                {
                    "label": "knows",
                    "source_label": "person",
                    "target_label": "person",
                    "source": {"name": "Alice"},
                    "target": {"name": "Bob"},
                    "properties": {"since": 2020},
                }
            ],
        }
    )

    assert result["ok"] is True


def test_ingest_graph_data_dry_run(monkeypatch):
    _mock_schema(monkeypatch)

    result = ingest_graph_data_module.ingest_graph_data(_graph_data())

    assert result["ok"] is True
    assert re.fullmatch(r"[0-9a-f]{16}", result["data"]["plan_hash"])
    assert result["data"]["mutation_summary"] == {"vertices": 2, "edges": 1}
    assert any("index" in w for w in result["data"]["warnings"])
    assert "duplicate vertex labels detected" not in result["data"]["warnings"]


def test_ingest_graph_data_dry_run_same_input_same_hash(monkeypatch):
    _mock_schema(monkeypatch)
    monkeypatch.setattr("hugegraph_mcp.plan_hash.time.time", lambda: 1000)

    # Same nonce + same payload + same expiry window = same hash.
    first = ingest_graph_data_module.ingest_graph_data(
        _graph_data(), nonce="fixed_nonce"
    )
    second = ingest_graph_data_module.ingest_graph_data(
        _graph_data(), nonce="fixed_nonce"
    )

    assert first["data"]["plan_hash"] == second["data"]["plan_hash"]


def test_ingest_graph_data_plan_hash_includes_schema(monkeypatch):
    graph_data = _graph_data()
    schema = _live_schema()
    schema_with_age_text = _live_schema()
    schema_with_age_text["schema"]["propertykeys"][1]["data_type"] = "TEXT"

    first = ingest_graph_data_module.calculate_plan_hash(graph_data, schema)
    second = ingest_graph_data_module.calculate_plan_hash(
        graph_data, schema_with_age_text
    )

    assert first != second


def test_ingest_plan_hash_schema_field_order_same_hash():
    graph_data = _graph_data()
    schema = _live_schema()
    reordered_schema = _live_schema()
    reordered_schema["schema"]["propertykeys"] = list(
        reversed(reordered_schema["schema"]["propertykeys"])
    )
    reordered_schema["schema"]["vertexlabels"][0]["properties"] = [
        {"name": "age"},
        {"name": "name"},
    ]

    first = ingest_graph_data_module.calculate_plan_hash(graph_data, schema)
    second = ingest_graph_data_module.calculate_plan_hash(graph_data, reordered_schema)

    assert first == second


def test_ingest_plan_hash_schema_primary_key_change_different_hash():
    graph_data = _graph_data()
    schema = _live_schema()
    changed_schema = _live_schema()
    changed_schema["schema"]["vertexlabels"][0]["primary_keys"] = ["age"]

    first = ingest_graph_data_module.calculate_plan_hash(graph_data, schema)
    second = ingest_graph_data_module.calculate_plan_hash(graph_data, changed_schema)

    assert first != second


def test_ingest_plan_hash_schema_metadata_ignored_same_hash():
    graph_data = _graph_data()
    schema = _live_schema()
    schema_with_metadata = _live_schema()
    schema_with_metadata["schema"]["propertykeys"][0]["id"] = 1
    schema_with_metadata["schema"]["propertykeys"][0]["user_data"] = {"x": "y"}
    schema_with_metadata["schema"]["vertexlabels"][0]["id"] = 99
    schema_with_metadata["server_time"] = "2026-05-26T00:00:00Z"

    first = ingest_graph_data_module.calculate_plan_hash(graph_data, schema)
    second = ingest_graph_data_module.calculate_plan_hash(
        graph_data, schema_with_metadata
    )

    assert first == second


def test_ingest_plan_hash_graph_data_order_same_hash():
    graph_data = _graph_data()
    reordered_graph_data = {
        "edges": [
            {
                "target": {"name": "Bob"},
                "source": {"name": "Alice"},
                "target_label": "person",
                "source_label": "person",
                "label": "knows",
            }
        ],
        "vertices": [
            {"properties": {"name": "Bob"}, "label": "person"},
            {"properties": {"name": "Alice"}, "label": "person"},
        ],
    }

    first = ingest_graph_data_module.calculate_plan_hash(graph_data, _live_schema())
    second = ingest_graph_data_module.calculate_plan_hash(
        reordered_graph_data,
        _live_schema(),
    )

    assert first == second


def test_ingest_graph_data_validate_invalid(monkeypatch):
    _mock_schema(monkeypatch)

    result = ingest_graph_data_module.ingest_graph_data({"vertices": [{}], "edges": []})

    assert result["ok"] is False
    assert result["error"]["type"] == "SCHEMA_MISMATCH"
    assert "missing required field: label" in result["error"]["details"]["errors"][0]


def test_ingest_graph_data_rejects_when_live_schema_unavailable(monkeypatch):
    monkeypatch.setattr(ingest_graph_data_module, "_fetch_live_schema", lambda: None)

    result = ingest_graph_data_module.ingest_graph_data(
        {"vertices": [{"label": "x"}], "edges": []}
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "CONNECTION_FAILED"
    assert "Cannot read live schema" in result["error"]["message"]


def test_ingest_graph_data_schema_mismatch(monkeypatch):
    _mock_schema(monkeypatch)

    # Edge source_label='ghost' does not exist in schema
    bad_data = {
        "vertices": [{"label": "person", "properties": {"name": "Alice"}}],
        "edges": [
            {
                "label": "knows",
                "source_label": "ghost",
                "target_label": "person",
            }
        ],
    }

    result = ingest_graph_data_module.ingest_graph_data(bad_data)

    assert result["ok"] is False
    assert result["error"]["type"] == "SCHEMA_MISMATCH"
    assert any(
        "source_label 'ghost'" in e for e in result["error"]["details"]["errors"]
    )


def test_ingest_graph_data_rejects_property_type_mismatch(monkeypatch):
    _mock_schema(monkeypatch)

    bad_data = {
        "vertices": [{"label": "person", "properties": {"name": "Alice", "age": "30"}}],
        "edges": [],
    }

    result = ingest_graph_data_module.ingest_graph_data(bad_data)

    assert result["ok"] is False
    assert result["error"]["type"] == "SCHEMA_MISMATCH"
    assert any(
        "property 'age' expects INT" in e for e in result["error"]["details"]["errors"]
    )


def test_ingest_graph_data_rejects_missing_schema_primary_key(monkeypatch):
    _mock_schema(monkeypatch)

    result = ingest_graph_data_module.ingest_graph_data(
        {"vertices": [{"label": "person", "properties": {"age": 30}}], "edges": []}
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "SCHEMA_MISMATCH"
    assert any(
        "vertex 0 missing primary key value for label 'person': name" in e
        for e in result["error"]["details"]["errors"]
    )


def test_ingest_graph_data_rejects_edge_target_not_in_payload(monkeypatch):
    _mock_schema(monkeypatch)

    result = ingest_graph_data_module.ingest_graph_data(
        {
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
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "SCHEMA_MISMATCH"
    assert any(
        "edge 0 target endpoint not found for label 'person': {'name': 'Bob'}" in e
        for e in result["error"]["details"]["errors"]
    )


def test_ingest_graph_data_rejects_edge_endpoint_missing_primary_key(monkeypatch):
    _mock_schema(monkeypatch)

    result = ingest_graph_data_module.ingest_graph_data(
        {
            "vertices": [
                {"label": "person", "properties": {"name": "Alice"}},
                {"label": "person", "properties": {"name": "Bob"}},
            ],
            "edges": [
                {
                    "label": "knows",
                    "source_label": "person",
                    "target_label": "person",
                    "source": {"name": "Alice"},
                    "target": {"age": 31},
                }
            ],
        }
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "SCHEMA_MISMATCH"
    assert any(
        "edge 0 target endpoint missing primary key for label 'person': name" in e
        for e in result["error"]["details"]["errors"]
    )


def test_ingest_graph_data_valid_payload_with_primary_key_endpoints(monkeypatch):
    _mock_schema(monkeypatch)

    result = ingest_graph_data_module.ingest_graph_data(_graph_data())

    assert result["ok"] is True
    assert result["data"]["mutation_summary"] == {"vertices": 2, "edges": 1}


def test_ingest_graph_data_resolves_outv_inv_endpoint_shape(monkeypatch):
    schema = _live_schema()
    schema["schema"]["vertexlabels"][0].pop("primary_keys")
    schema["schema"]["vertexlabels"][0]["primaryKeys"] = ["name"]
    monkeypatch.setattr(ingest_graph_data_module, "_fetch_live_schema", lambda: schema)

    result = ingest_graph_data_module.ingest_graph_data(
        {
            "vertices": [
                {"label": "person", "properties": {"name": "Alice"}},
                {"label": "person", "properties": {"name": "Bob"}},
            ],
            "edges": [
                {
                    "label": "knows",
                    "outV": "1:Alice",
                    "outVLabel": "person",
                    "inV": "1:Bob",
                    "inVLabel": "person",
                }
            ],
        }
    )

    assert result["ok"] is True


def test_ingest_graph_data_rejects_duplicate_vertex_identity(monkeypatch):
    _mock_schema(monkeypatch)

    result = ingest_graph_data_module.ingest_graph_data(
        {
            "vertices": [
                {"label": "person", "properties": {"name": "Alice"}},
                {"label": "person", "properties": {"name": "Alice"}},
            ],
            "edges": [],
        }
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "SCHEMA_MISMATCH"


def test_ingest_graph_data_rejects_edge_label_mismatch(monkeypatch):
    _mock_schema(monkeypatch)

    bad_data = {
        "vertices": [{"label": "person", "properties": {"name": "Alice"}}],
        "edges": [
            {
                "label": "likes",
                "source_label": "person",
                "target_label": "person",
                "source": {"name": "Alice"},
                "target": {"name": "Bob"},
            },
            {
                "label": "knows",
                "source_label": "person",
                "target_label": "ghost",
                "source": {"name": "Alice"},
                "target": {"name": "Bob"},
            },
        ],
    }

    result = ingest_graph_data_module.ingest_graph_data(bad_data)

    assert result["ok"] is False
    assert result["error"]["type"] == "SCHEMA_MISMATCH"
    errors = result["error"]["details"]["errors"]
    assert any("edge 0 label 'likes' does not exist in schema" in e for e in errors)
    assert any("edge 1 target_label 'ghost'" in e for e in errors)
    assert any(
        "does not match edge label 'knows' target_label 'person'" in e for e in errors
    )


def test_ingest_graph_data_warns_for_labels_without_schema_index(monkeypatch):
    schema = _live_schema()
    schema["schema"]["indexlabels"] = [
        {"name": "personByName", "base_type": "VERTEX", "base_label": "person"},
    ]
    monkeypatch.setattr(ingest_graph_data_module, "_fetch_live_schema", lambda: schema)

    result = ingest_graph_data_module.ingest_graph_data(_graph_data())

    assert result["ok"] is True
    assert (
        "no edge index found in schema for label: knows" in result["data"]["warnings"]
    )


def test_ingest_graph_data_missing_confirm(monkeypatch):
    _mock_schema(monkeypatch)
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")

    result = ingest_graph_data_module.ingest_graph_data(
        _graph_data(),
        dry_run=False,
        confirm=False,
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "CONFIRM_REQUIRED"


def test_ingest_graph_data_plan_hash_mismatch(monkeypatch):
    _mock_schema(monkeypatch)
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
    _mock_schema(monkeypatch)
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
    _mock_schema(monkeypatch)
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    post = Mock(return_value=envelope_ok({"ok": True, "data": {"inserted": 2}}))
    monkeypatch.setattr(ingest_graph_data_module, "post", post)
    graph_data = _graph_data()
    dry_run = ingest_graph_data_module.ingest_graph_data(graph_data)

    # M5: pass nonce and expires_at from dry_run plan_context
    plan_ctx = dry_run["data"]["plan_context"]
    result = ingest_graph_data_module.ingest_graph_data(
        graph_data,
        dry_run=False,
        confirm=True,
        plan_hash=dry_run["data"]["plan_hash"],
        nonce=plan_ctx["nonce"],
        expires_at=plan_ctx["expires_at"],
    )

    assert result["ok"] is True
    assert result["data"]["batch_id"].startswith("batch-")
    assert result["data"]["status"] in ("success", "partial", "degraded")
    assert result["data"]["planned"] == {"vertices": 2, "edges": 1}
    post.assert_called_once()
    assert post.call_args.args == ("/graph-import",)
    assert post.call_args.kwargs["json"]["schema"] == "hugegraph"
    import_payload = json.loads(post.call_args.kwargs["json"]["data"])
    assert import_payload["vertices"][0]["id"] == "1:Alice"
    assert import_payload["vertices"][1]["id"] == "1:Bob"
    assert import_payload["edges"][0]["outV"] == "1:Alice"
    assert import_payload["edges"][0]["outVLabel"] == "person"
    assert import_payload["edges"][0]["inV"] == "1:Bob"
    assert import_payload["edges"][0]["inVLabel"] == "person"
    assert import_payload["edges"][0]["properties"] == {}


def test_ingest_graph_data_assumes_planned_counts_when_ai_omits_counts(monkeypatch):
    _mock_schema(monkeypatch)
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    post = Mock(return_value=envelope_ok({"message": "import finished"}))
    monkeypatch.setattr(ingest_graph_data_module, "post", post)
    graph_data = _graph_data()
    dry_run = ingest_graph_data_module.ingest_graph_data(graph_data)
    plan_ctx = dry_run["data"]["plan_context"]

    result = ingest_graph_data_module.ingest_graph_data(
        graph_data,
        dry_run=False,
        confirm=True,
        plan_hash=dry_run["data"]["plan_hash"],
        nonce=plan_ctx["nonce"],
        expires_at=plan_ctx["expires_at"],
    )

    assert result["ok"] is True
    assert result["data"]["status"] == "success"
    assert result["data"]["written"] == {"vertices": 2, "edges": 1}
    assert any(
        "did not return explicit written counts" in w for w in result["warnings"]
    )


def test_ingest_graph_data_splits_total_written_count(monkeypatch):
    _mock_schema(monkeypatch)
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    post = Mock(return_value=envelope_ok({"inserted": 2}))
    monkeypatch.setattr(ingest_graph_data_module, "post", post)
    graph_data = _graph_data()
    dry_run = ingest_graph_data_module.ingest_graph_data(graph_data)
    plan_ctx = dry_run["data"]["plan_context"]

    result = ingest_graph_data_module.ingest_graph_data(
        graph_data,
        dry_run=False,
        confirm=True,
        plan_hash=dry_run["data"]["plan_hash"],
        nonce=plan_ctx["nonce"],
        expires_at=plan_ctx["expires_at"],
    )

    assert result["ok"] is True
    assert result["data"]["status"] == "partial"
    assert result["data"]["written"] == {"vertices": 2, "edges": 0}
    assert any("total written count" in w for w in result["warnings"])
