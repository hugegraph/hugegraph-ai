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

"""Tests for plan_hash module (Milestone 4)."""

from hugegraph_mcp.plan_hash import (
    PlanContext,
    build_plan_context,
    compute_payload_digest,
    compute_plan_hash,
    verify_plan_hash,
)


def test_plan_hash_changes_when_graph_url_changes(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_URL", "http://server-a:8080")
    ctx_a, hash_a = build_plan_context(
        tool_name="test", mode="import", payload_digest="abc123"
    )

    monkeypatch.setenv("HUGEGRAPH_URL", "http://server-b:8080")
    ctx_b, hash_b = build_plan_context(
        tool_name="test", mode="import", payload_digest="abc123"
    )

    assert hash_a != hash_b


def test_plan_hash_changes_when_graph_name_changes(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_GRAPH", "graph_a")
    _, hash_a = build_plan_context(
        tool_name="test", mode="import", payload_digest="abc123"
    )

    monkeypatch.setenv("HUGEGRAPH_GRAPH", "graph_b")
    _, hash_b = build_plan_context(
        tool_name="test", mode="import", payload_digest="abc123"
    )

    assert hash_a != hash_b


def test_plan_hash_changes_when_graphspace_changes(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_GRAPHSPACE", "space_a")
    _, hash_a = build_plan_context(
        tool_name="test", mode="import", payload_digest="abc123"
    )

    monkeypatch.setenv("HUGEGRAPH_GRAPHSPACE", "space_b")
    _, hash_b = build_plan_context(
        tool_name="test", mode="import", payload_digest="abc123"
    )

    assert hash_a != hash_b


def test_plan_hash_changes_when_principal_changes(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_USER", "alice")
    _, hash_a = build_plan_context(
        tool_name="test", mode="import", payload_digest="abc123"
    )

    monkeypatch.setenv("HUGEGRAPH_USER", "bob")
    _, hash_b = build_plan_context(
        tool_name="test", mode="import", payload_digest="abc123"
    )

    assert hash_a != hash_b


def test_plan_hash_changes_when_readonly_changes(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "true")
    _, hash_a = build_plan_context(
        tool_name="test", mode="import", payload_digest="abc123"
    )

    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    _, hash_b = build_plan_context(
        tool_name="test", mode="import", payload_digest="abc123"
    )

    assert hash_a != hash_b


def test_plan_hash_changes_when_payload_changes(monkeypatch):
    _, hash_a = build_plan_context(
        tool_name="test", mode="import", payload_digest="aaa"
    )

    _, hash_b = build_plan_context(
        tool_name="test", mode="import", payload_digest="bbb"
    )

    assert hash_a != hash_b


def test_plan_hash_changes_when_schema_hash_changes(monkeypatch):
    _, hash_a = build_plan_context(
        tool_name="test", mode="import", payload_digest="abc", schema_hash="schema1"
    )

    _, hash_b = build_plan_context(
        tool_name="test", mode="import", payload_digest="abc", schema_hash="schema2"
    )

    assert hash_a != hash_b


def test_verify_plan_hash_accepts_matching_hash(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_URL", "http://test:8080")
    monkeypatch.setenv("HUGEGRAPH_GRAPH", "testgraph")
    monkeypatch.setenv("HUGEGRAPH_USER", "testuser")
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "true")

    context, plan_hash = build_plan_context(
        tool_name="test", mode="import", payload_digest="abc123", nonce="mynonce"
    )

    valid, error_type, details = verify_plan_hash(
        submitted_hash=plan_hash,
        tool_name="test",
        mode="import",
        payload_digest="abc123",
        nonce="mynonce",
        expires_at=context.expires_at,
    )

    assert valid is True
    assert error_type is None


def test_verify_plan_hash_rejects_mismatched_hash(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_URL", "http://test:8080")
    context, _ = build_plan_context(
        tool_name="test", mode="import", payload_digest="abc123", nonce="mynonce"
    )

    valid, error_type, details = verify_plan_hash(
        submitted_hash="wrong_hash",
        tool_name="test",
        mode="import",
        payload_digest="abc123",
        nonce="mynonce",
        expires_at=context.expires_at,
    )

    assert valid is False
    assert error_type == "PLAN_HASH_MISMATCH"


def test_verify_plan_hash_rejects_missing_nonce(monkeypatch):
    valid, error_type, details = verify_plan_hash(
        submitted_hash="any_hash",
        tool_name="test",
        mode="import",
        payload_digest="abc123",
        nonce=None,
    )

    assert valid is False
    assert error_type == "PLAN_HASH_MISMATCH"


def test_compute_payload_digest_is_stable():
    d1 = compute_payload_digest({"a": 1, "b": 2})
    d2 = compute_payload_digest({"b": 2, "a": 1})

    assert d1 == d2


def test_plan_context_is_frozen():
    context, _ = build_plan_context(
        tool_name="test", mode="import", payload_digest="abc"
    )

    try:
        context.tool_name = "other"
        assert False, "Should be frozen"
    except AttributeError:
        pass


def test_verify_plan_hash_rejects_expired_plan(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_URL", "http://test:8080")

    context, plan_hash = build_plan_context(
        tool_name="test", mode="import", payload_digest="abc123", nonce="mynonce"
    )

    # Set expires_at to the past
    valid, error_type, details = verify_plan_hash(
        submitted_hash=plan_hash,
        tool_name="test",
        mode="import",
        payload_digest="abc123",
        nonce="mynonce",
        expires_at=0.0,  # expired long ago
    )

    assert valid is False
    assert error_type == "PLAN_EXPIRED"
