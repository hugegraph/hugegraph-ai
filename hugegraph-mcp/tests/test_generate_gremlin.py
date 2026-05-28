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

from unittest.mock import Mock

from hugegraph_mcp.envelope import ErrorType, envelope_err, envelope_ok
from hugegraph_mcp.tools import generate_gremlin as generate_gremlin_module


def _ai_ok(gremlin: str, **extra) -> dict:
    data = {
        "gremlin": gremlin,
        "template_gremlin": gremlin,
        "raw_gremlin": gremlin,
        "requires_index": False,
        "assumptions": None,
    }
    data.update(extra)
    return envelope_ok(data)


def test_generate_gremlin_default_no_execute(monkeypatch):
    post = Mock(return_value=_ai_ok("g.V().count()"))
    execute_read = Mock()
    monkeypatch.setattr(generate_gremlin_module, "post", post)
    monkeypatch.setattr(generate_gremlin_module, "execute_gremlin_read", execute_read)

    result = generate_gremlin_module.generate_gremlin("count vertices")

    assert result["ok"] is True
    assert result["data"]["gremlin"] == "g.V().count()"
    assert result["data"]["template_gremlin"] == "g.V().count()"
    assert result["data"]["raw_gremlin"] == "g.V().count()"
    assert result["data"]["is_readonly"] is True
    assert result["data"]["risk_level"] == "low"
    assert result["data"]["requires_index"] is False
    assert result["data"]["assumptions"] is None
    assert result["data"]["executed"] is False
    assert result["data"]["execution_result"] is None
    post.assert_called_once_with("/text2gremlin", json={"query": "count vertices"})
    execute_read.assert_not_called()


def test_generate_gremlin_passes_output_types(monkeypatch):
    post = Mock(return_value=_ai_ok("g.V().count()"))
    monkeypatch.setattr(generate_gremlin_module, "post", post)

    result = generate_gremlin_module.generate_gremlin(
        "count vertices",
        output_types=["vertex"],
    )

    assert result["ok"] is True
    post.assert_called_once_with(
        "/text2gremlin",
        json={"query": "count vertices", "output_types": ["vertex"]},
    )


def test_generate_gremlin_rejects_missing_gremlin(monkeypatch):
    post = Mock(
        return_value=envelope_ok(
            {"requires_index": False, "assumptions": ["no query generated"]}
        )
    )
    execute_read = Mock()
    monkeypatch.setattr(generate_gremlin_module, "post", post)
    monkeypatch.setattr(generate_gremlin_module, "execute_gremlin_read", execute_read)

    result = generate_gremlin_module.generate_gremlin("count vertices", execute=True)

    assert result["ok"] is False
    assert result["error"]["type"] == "FLOW_EXECUTION_FAILED"
    assert result["error"]["message"] == "HugeGraph-AI did not return Gremlin."
    execute_read.assert_not_called()


def test_generate_gremlin_safe_execute(monkeypatch):
    post = Mock(return_value=_ai_ok("g.V().limit(2)"))
    execution_result = {
        "data": [{"id": 1}],
        "total": 1,
        "duration_ms": 1,
        "is_read": True,
    }
    execute_read = Mock(return_value=execution_result)
    monkeypatch.setattr(generate_gremlin_module, "post", post)
    monkeypatch.setattr(generate_gremlin_module, "execute_gremlin_read", execute_read)

    result = generate_gremlin_module.generate_gremlin("show two vertices", execute=True)

    assert result["ok"] is True
    assert result["data"]["is_readonly"] is True
    assert result["data"]["risk_level"] == "low"
    assert result["data"]["requires_index"] is False
    assert result["data"]["assumptions"] is None
    assert result["data"]["executed"] is True
    assert result["data"]["execution_result"] == execution_result
    execute_read.assert_called_once_with("g.V().limit(2)")


def test_generate_gremlin_unsafe_no_execute(monkeypatch):
    post = Mock(return_value=_ai_ok("g.addV('person')"))
    execute_read = Mock()
    monkeypatch.setattr(generate_gremlin_module, "post", post)
    monkeypatch.setattr(generate_gremlin_module, "execute_gremlin_read", execute_read)

    result = generate_gremlin_module.generate_gremlin("add a person", execute=True)

    assert result["ok"] is False
    assert result["error"]["type"] == "UNSAFE_GREMLIN"
    assert (
        result["error"]["message"]
        == "Generated Gremlin is not safe to execute automatically"
    )
    assert result["error"]["details"]["classification"] == "unsafe"
    execute_read.assert_not_called()


def test_generate_gremlin_ai_unavailable(monkeypatch):
    ai_error = envelope_err(
        ErrorType.HUGEGRAPH_AI_UNAVAILABLE,
        "HugeGraph-AI is unavailable",
        retryable=True,
    )
    post = Mock(return_value=ai_error)
    execute_read = Mock()
    monkeypatch.setattr(generate_gremlin_module, "post", post)
    monkeypatch.setattr(generate_gremlin_module, "execute_gremlin_read", execute_read)

    result = generate_gremlin_module.generate_gremlin("count vertices", execute=True)

    assert result == ai_error
    execute_read.assert_not_called()
