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
from unittest.mock import Mock

from hugegraph_mcp.envelope import ErrorType, envelope_err, envelope_ok
from hugegraph_mcp.tools import extract_graph_data as extract_graph_data_module


def test_extract_graph_data_basic(monkeypatch):
    graph_data = {
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
    post = Mock(return_value=envelope_ok({"ok": True, "data": json.dumps(graph_data)}))
    monkeypatch.setattr(extract_graph_data_module, "post", post)

    result = extract_graph_data_module.extract_graph_data(
        "Alice knows Bob.",
        schema={"vertexlabels": ["person"]},
        example_prompt="extract people",
    )

    assert result["ok"] is True
    assert result["data"]["vertices"] == graph_data["vertices"]
    assert result["data"]["edges"] == graph_data["edges"]
    assert "schema_ref" in result["data"]
    assert result["data"]["schema_ref"]["graph"] is not None
    assert result["data"]["warnings"] == []
    assert result["data"]["schema_warnings"] == []
    post.assert_called_once_with(
        "/graph-extract",
        json={
            "text": "Alice knows Bob.",
            "schema": {"vertexlabels": ["person"]},
            "example_prompt": "extract people",
            "language": "zh",
        },
    )


def test_extract_graph_data_ai_unavailable(monkeypatch):
    ai_error = envelope_err(
        ErrorType.HUGEGRAPH_AI_UNAVAILABLE,
        "HugeGraph-AI is unavailable",
        retryable=True,
    )
    post = Mock(return_value=ai_error)
    monkeypatch.setattr(extract_graph_data_module, "post", post)

    result = extract_graph_data_module.extract_graph_data("Alice knows Bob.")

    assert result == ai_error
