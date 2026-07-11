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

from hugegraph_mcp.tools import mutate_graph_properties as mutate_module


def _schema():
    return {
        "schema": {
            "propertykeys": [
                {"name": "name", "data_type": "TEXT"},
                {"name": "age", "data_type": "INT"},
            ],
            "vertexlabels": [
                {
                    "name": "person",
                    "properties": ["name", "age"],
                    "primary_keys": ["name"],
                }
            ],
            "edgelabels": [
                {
                    "name": "knows",
                    "source_label": "person",
                    "target_label": "person",
                    "properties": ["age"],
                }
            ],
            "indexlabels": [],
        },
        "readonly": False,
    }


class FakeGraphManager:
    def __init__(self, vertex=None, changed_vertex=None):
        self.vertex = vertex or {
            "id": "1:alice",
            "label": "person",
            "type": "vertex",
            "properties": {"name": "Alice"},
        }
        self.changed_vertex = changed_vertex
        self.read_count = 0
        self.append_calls = []
        self.eliminate_calls = []

    def getVertexById(self, vertex_id):
        self.read_count += 1
        if self.changed_vertex is not None and self.read_count >= 2:
            return self.changed_vertex
        return self.vertex

    def getEdgeById(self, edge_id):
        return {
            "id": edge_id,
            "label": "knows",
            "type": "edge",
            "properties": {"age": 1},
        }

    def appendVertex(self, vertex_id, properties):
        self.append_calls.append((vertex_id, properties))
        self.vertex = {
            **self.vertex,
            "properties": {**self.vertex["properties"], **properties},
        }
        return self.vertex

    def eliminateVertex(self, vertex_id, properties):
        self.eliminate_calls.append((vertex_id, properties))
        self.vertex = {
            **self.vertex,
            "properties": {
                key: value
                for key, value in self.vertex["properties"].items()
                if key not in properties
            },
        }
        return self.vertex


class MissingTargetManager:
    def getVertexById(self, vertex_id):
        raise RuntimeError("404 Not Found: vertex does not exist")

    def getEdgeById(self, edge_id):
        raise RuntimeError("404 Not Found: edge does not exist")


class PostReadFailureManager(FakeGraphManager):
    def __init__(self):
        super().__init__()
        self.post_read_error = RuntimeError(
            "post read failed: Authorization: Bearer abc123 "
            "token=xyz http://user:pass@example.com"
        )

    def getVertexById(self, vertex_id):
        if self.append_calls:
            raise self.post_read_error
        return super().getVertexById(vertex_id)


class PostReadMissingManager(FakeGraphManager):
    def getVertexById(self, vertex_id):
        if self.append_calls:
            return None
        return super().getVertexById(vertex_id)


class PostReadMismatchManager(FakeGraphManager):
    def getVertexById(self, vertex_id):
        if self.append_calls:
            return {
                **self.vertex,
                "properties": {"name": "Alice", "age": 31},
            }
        return super().getVertexById(vertex_id)


class ExecutionFailureManager(FakeGraphManager):
    def appendVertex(self, vertex_id, properties):
        self.append_calls.append((vertex_id, properties))
        raise RuntimeError("404 Not Found: vertex does not exist")


def _patch_schema(monkeypatch):
    monkeypatch.setattr(mutate_module, "current_live_schema", lambda: _schema())


def test_mutate_dry_run_returns_snapshot_bound_plan(monkeypatch):
    _patch_schema(monkeypatch)
    manager = FakeGraphManager()
    monkeypatch.setattr(mutate_module, "_graph_manager", lambda: manager)

    result = mutate_module.mutate_graph_properties(
        target="vertex",
        operation="append",
        id="1:alice",
        properties={"age": 30},
    )

    assert result["ok"] is True
    assert result["data"]["status"] == "planned"
    assert result["data"]["before"]["properties"] == {"name": "Alice"}
    assert result["data"]["after"]["properties"] == {"name": "Alice", "age": 30}
    assert result["data"]["plan_hash"]
    assert "|ts:" in result["data"]["plan_context"]["nonce"]


def test_mutate_rejects_unknown_property(monkeypatch):
    _patch_schema(monkeypatch)
    manager = FakeGraphManager()
    monkeypatch.setattr(mutate_module, "_graph_manager", lambda: manager)

    result = mutate_module.mutate_graph_properties(
        target="vertex",
        operation="append",
        id="1:alice",
        properties={"missing": "x"},
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "SCHEMA_MISMATCH"
    assert result["error"]["details"]["unknown_properties"] == ["missing"]


def test_mutate_missing_vertex_returns_not_found(monkeypatch):
    _patch_schema(monkeypatch)
    monkeypatch.setattr(mutate_module, "_graph_manager", lambda: MissingTargetManager())

    result = mutate_module.mutate_graph_properties(
        target="vertex",
        operation="append",
        id="1:missing",
        properties={"age": 30},
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "NOT_FOUND"
    assert result["error"]["retryable"] is False
    assert result["error"]["details"]["reason"] == "not_found"


def test_mutate_missing_edge_returns_not_found(monkeypatch):
    _patch_schema(monkeypatch)
    monkeypatch.setattr(mutate_module, "_graph_manager", lambda: MissingTargetManager())

    result = mutate_module.mutate_graph_properties(
        target="edge",
        operation="append",
        id="S1:alice>11>knows>S2:bob",
        properties={"age": 1},
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "NOT_FOUND"
    assert result["error"]["retryable"] is False
    assert result["error"]["details"]["reason"] == "not_found"


def test_mutate_confirm_applies_after_valid_plan(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    _patch_schema(monkeypatch)
    manager = FakeGraphManager()
    monkeypatch.setattr(mutate_module, "_graph_manager", lambda: manager)

    dry_run = mutate_module.mutate_graph_properties(
        target="vertex",
        operation="append",
        id="1:alice",
        properties={"age": 30},
    )
    context = dry_run["data"]["plan_context"]
    result = mutate_module.mutate_graph_properties(
        target="vertex",
        operation="append",
        id="1:alice",
        properties={"age": 30},
        dry_run=False,
        confirm=True,
        plan_hash=dry_run["data"]["plan_hash"],
        nonce=context["nonce"],
        expires_at=context["expires_at"],
    )

    assert result["ok"] is True
    assert result["data"]["status"] == "applied"
    assert manager.append_calls == [("1:alice", {"age": 30})]


def test_mutate_confirm_maps_execution_errors_with_hugegraph_classifier(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    _patch_schema(monkeypatch)
    manager = ExecutionFailureManager()
    monkeypatch.setattr(mutate_module, "_graph_manager", lambda: manager)

    dry_run = mutate_module.mutate_graph_properties(
        target="vertex",
        operation="append",
        id="1:alice",
        properties={"age": 30},
    )
    context = dry_run["data"]["plan_context"]
    result = mutate_module.mutate_graph_properties(
        target="vertex",
        operation="append",
        id="1:alice",
        properties={"age": 30},
        dry_run=False,
        confirm=True,
        plan_hash=dry_run["data"]["plan_hash"],
        nonce=context["nonce"],
        expires_at=context["expires_at"],
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "NOT_FOUND"
    assert result["error"]["retryable"] is False
    assert result["error"]["details"]["stage"] == "mutation_execute"
    assert result["error"]["details"]["reason"] == "not_found"


def test_mutate_confirm_sanitizes_post_read_error(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    _patch_schema(monkeypatch)
    manager = PostReadFailureManager()
    monkeypatch.setattr(mutate_module, "_graph_manager", lambda: manager)

    dry_run = mutate_module.mutate_graph_properties(
        target="vertex",
        operation="append",
        id="1:alice",
        properties={"age": 30},
    )
    context = dry_run["data"]["plan_context"]
    result = mutate_module.mutate_graph_properties(
        target="vertex",
        operation="append",
        id="1:alice",
        properties={"age": 30},
        dry_run=False,
        confirm=True,
        plan_hash=dry_run["data"]["plan_hash"],
        nonce=context["nonce"],
        expires_at=context["expires_at"],
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "PARTIAL_APPLY"
    assert result["error"]["details"]["stage"] == "post_write_verification"
    assert result["error"]["details"]["status"] == "unknown"
    response_text = str(result)
    assert "abc123" not in response_text
    assert "token=xyz" not in response_text
    assert "user:pass" not in response_text
    assert result["warnings"] == [
        "Mutation returned from HugeGraph, but post-read verification failed."
    ]
    assert result["next_actions"] == [
        "Call query_graph_data_tool to verify the target state."
    ]


def test_mutate_confirm_returns_error_when_post_read_is_missing(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    _patch_schema(monkeypatch)
    manager = PostReadMissingManager()
    monkeypatch.setattr(mutate_module, "_graph_manager", lambda: manager)

    dry_run = mutate_module.mutate_graph_properties(
        target="vertex",
        operation="append",
        id="1:alice",
        properties={"age": 30},
    )
    context = dry_run["data"]["plan_context"]
    result = mutate_module.mutate_graph_properties(
        target="vertex",
        operation="append",
        id="1:alice",
        properties={"age": 30},
        dry_run=False,
        confirm=True,
        plan_hash=dry_run["data"]["plan_hash"],
        nonce=context["nonce"],
        expires_at=context["expires_at"],
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "PARTIAL_APPLY"
    assert result["error"]["details"]["stage"] == "post_write_verification"
    assert result["error"]["details"]["post_read"] is None
    assert result["warnings"] == [
        "Mutation returned from HugeGraph, but the target was not found on post-read."
    ]
    assert result["next_actions"] == [
        "Call query_graph_data_tool to verify whether the target still exists."
    ]


def test_mutate_confirm_returns_error_when_post_read_mismatches_plan(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    _patch_schema(monkeypatch)
    manager = PostReadMismatchManager()
    monkeypatch.setattr(mutate_module, "_graph_manager", lambda: manager)

    dry_run = mutate_module.mutate_graph_properties(
        target="vertex",
        operation="append",
        id="1:alice",
        properties={"age": 30},
    )
    context = dry_run["data"]["plan_context"]
    result = mutate_module.mutate_graph_properties(
        target="vertex",
        operation="append",
        id="1:alice",
        properties={"age": 30},
        dry_run=False,
        confirm=True,
        plan_hash=dry_run["data"]["plan_hash"],
        nonce=context["nonce"],
        expires_at=context["expires_at"],
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "PARTIAL_APPLY"
    assert result["error"]["details"]["stage"] == "post_write_verification"
    assert result["error"]["details"]["planned_after"]["properties"]["age"] == 30
    assert result["error"]["details"]["post_read"]["properties"]["age"] == 31
    assert result["warnings"] == ["Post-read state did not match the planned preview."]


def test_mutate_confirm_detects_target_changed(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    _patch_schema(monkeypatch)
    manager = FakeGraphManager(
        changed_vertex={
            "id": "1:alice",
            "label": "person",
            "type": "vertex",
            "properties": {"name": "Alice", "age": 99},
        }
    )
    monkeypatch.setattr(mutate_module, "_graph_manager", lambda: manager)

    dry_run = mutate_module.mutate_graph_properties(
        target="vertex",
        operation="append",
        id="1:alice",
        properties={"age": 30},
    )
    context = dry_run["data"]["plan_context"]
    result = mutate_module.mutate_graph_properties(
        target="vertex",
        operation="append",
        id="1:alice",
        properties={"age": 30},
        dry_run=False,
        confirm=True,
        plan_hash=dry_run["data"]["plan_hash"],
        nonce=context["nonce"],
        expires_at=context["expires_at"],
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "TARGET_CHANGED"
    assert manager.append_calls == []


def test_mutate_confirm_requires_non_readonly(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "true")
    _patch_schema(monkeypatch)
    manager = FakeGraphManager()
    monkeypatch.setattr(mutate_module, "_graph_manager", lambda: manager)

    result = mutate_module.mutate_graph_properties(
        target="vertex",
        operation="append",
        id="1:alice",
        properties={"age": 30},
        dry_run=False,
        confirm=True,
        plan_hash="bad",
        nonce="nonce",
        expires_at=9999999999,
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "READONLY_VIOLATION"
    assert manager.append_calls == []
