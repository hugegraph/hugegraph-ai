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


def _sample_ops():
    return [
        {"type": "create_property_key", "name": "age"},
        {"type": "create_vertex_label", "name": "person", "properties": ["age"]},
    ]


def test_execute_schema_operations_all_success(monkeypatch):
    """All operations succeed → success True, no errors, per-op results preserved."""

    from hugegraph_mcp import schema_tools

    called = {}

    def fake_runner(ops):
        called["ops"] = ops
        return {
            "success": True,
            "results": [
                {"op": ops[0], "status": "ok"},
                {"op": ops[1], "status": "ok"},
            ],
            "errors": [],
        }

    # Assume execute_schema_operations will delegate to an internal runner
    monkeypatch.setattr(schema_tools, "_run_schema_operations", fake_runner, raising=False)

    ops = _sample_ops()
    result = schema_tools.execute_schema_operations(ops)

    assert called["ops"] == ops
    assert result["success"] is True
    assert result["errors"] == []
    assert len(result["results"]) == 2
    assert result["results"][0]["status"] == "ok"


def test_execute_schema_operations_collects_errors(monkeypatch):
    """Mixed success/failure → When operations fail, errors are collected and success is False."""
    
    from hugegraph_mcp import schema_tools

    def fake_runner(ops):
        return {
            "success": False,
            "results": [
                {"op": ops[0], "status": "ok"},
                {"op": ops[1], "status": "failed", "error": "Constraint violation"},
            ],
            "errors": [
                {"op_index": 1, "message": "Constraint violation"},
            ],
        }

    monkeypatch.setattr(schema_tools, "_run_schema_operations", fake_runner, raising=False)

    result = schema_tools.execute_schema_operations(_sample_ops())

    assert result["success"] is False
    assert result["errors"]
    assert result["errors"][0]["message"] == "Constraint violation"


