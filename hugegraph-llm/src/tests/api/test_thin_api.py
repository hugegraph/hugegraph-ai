# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

import importlib
import warnings
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from hugegraph_llm.api.models.rag_response import ThinAPIError, ThinAPIMeta, ThinAPIResponse
from hugegraph_llm.api.thin_api import thin_router
from hugegraph_llm.flows import FlowName


def _client(monkeypatch, scheduler):
    monkeypatch.setattr(
        "hugegraph_llm.api.thin_api.SchedulerSingleton.get_instance",
        Mock(return_value=scheduler),
    )
    app = FastAPI()
    app.include_router(thin_router)
    return TestClient(app)


def _assert_envelope(response_json: dict, expected_ok: bool):
    assert response_json["ok"] is expected_ok
    assert "data" in response_json
    assert "error" in response_json
    assert "warnings" in response_json
    assert "next_actions" in response_json
    assert "meta" in response_json
    assert response_json["meta"]["request_id"].startswith("req-")
    assert isinstance(response_json["meta"]["duration_ms"], (int, float))
    if expected_ok:
        assert response_json["error"] is None
    else:
        assert response_json["error"] is not None
        assert "type" in response_json["error"]
        assert "message" in response_json["error"]


def test_graph_extract_api_calls_flow(monkeypatch):
    scheduler = Mock()
    scheduler.schedule_flow.return_value = '{"vertices": [], "edges": []}'
    client = _client(monkeypatch, scheduler)

    response = client.post(
        "/graph-extract",
        json={
            "text": "Alice knows Bob.",
            "schema": "{}",
            "example_prompt": "extract graph",
            "language": "en",
        },
    )

    assert response.status_code == 200
    json_body = response.json()
    _assert_envelope(json_body, expected_ok=True)
    assert json_body["data"] == '{"vertices": [], "edges": []}'
    scheduler.schedule_flow.assert_called_once_with(
        FlowName.GRAPH_EXTRACT,
        "{}",
        "Alice knows Bob.",
        "extract graph",
        "property_graph",
        "en",
    )


def test_graph_import_api_calls_flow(monkeypatch):
    scheduler = Mock()
    scheduler.schedule_flow.return_value = '{"imported": true}'
    client = _client(monkeypatch, scheduler)

    response = client.post("/graph-import", json={"data": "{}", "schema": None})

    assert response.status_code == 200
    json_body = response.json()
    _assert_envelope(json_body, expected_ok=True)
    assert json_body["data"] == '{"imported": true}'
    scheduler.schedule_flow.assert_called_once_with(FlowName.IMPORT_GRAPH_DATA, "{}", None)


def test_thin_api_request_models_do_not_emit_schema_shadow_warning():
    import hugegraph_llm.api.models.rag_requests as rag_requests

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        module = importlib.reload(rag_requests)

    assert not any("Field name \"schema\"" in str(item.message) for item in caught)

    extract = module.GraphExtractRequest(text="Alice knows Bob.", schema="{}")
    graph_import = module.GraphImportRequest(data="{}", schema=None)

    assert extract.graph_schema == "{}"
    assert graph_import.graph_schema is None
    assert extract.model_dump(by_alias=True)["schema"] == "{}"


def test_vid_embeddings_refresh_api_calls_flow(monkeypatch):
    scheduler = Mock()
    scheduler.schedule_flow.return_value = "Removed 0 vectors, added 1 vectors."
    client = _client(monkeypatch, scheduler)

    response = client.post("/vid-embeddings/refresh", json={})

    assert response.status_code == 200
    json_body = response.json()
    _assert_envelope(json_body, expected_ok=True)
    assert json_body["data"] == "Removed 0 vectors, added 1 vectors."
    scheduler.schedule_flow.assert_called_once_with(FlowName.UPDATE_VID_EMBEDDINGS)


def test_graph_index_info_api_calls_flow(monkeypatch):
    scheduler = Mock()
    scheduler.schedule_flow.return_value = '{"vertices": 1}'
    client = _client(monkeypatch, scheduler)

    response = client.get("/graph-index-info")

    assert response.status_code == 200
    json_body = response.json()
    _assert_envelope(json_body, expected_ok=True)
    assert json_body["data"] == '{"vertices": 1}'
    scheduler.schedule_flow.assert_called_once_with(FlowName.GET_GRAPH_INDEX_INFO)


def test_thin_api_returns_flow_execution_failed(monkeypatch):
    scheduler = Mock()
    scheduler.schedule_flow.side_effect = RuntimeError("secret path /tmp/token")
    client = _client(monkeypatch, scheduler)

    response = client.get("/graph-index-info")

    assert response.status_code == 200
    json_body = response.json()
    _assert_envelope(json_body, expected_ok=False)
    assert json_body["data"] is None
    assert json_body["error"]["type"] == "FLOW_EXECUTION_FAILED"
    assert json_body["error"]["message"] == "An internal error occurred during flow execution."
    assert "secret" not in json_body["error"]["message"]
    assert json_body["error"]["source"] == "hugegraph-llm"
    assert "details" in json_body["error"]


def test_thin_api_response_defaults_are_not_shared():
    first = ThinAPIResponse(ok=True, meta=ThinAPIMeta(request_id="req-a"))
    second = ThinAPIResponse(ok=True, meta=ThinAPIMeta(request_id="req-b"))
    first.warnings.append("one")
    first.next_actions.append("next")

    assert second.warnings == []
    assert second.next_actions == []

    first_error = ThinAPIError(type="X", message="x")
    second_error = ThinAPIError(type="Y", message="y")
    first_error.details["secret"] = "value"
    assert second_error.details == {}
