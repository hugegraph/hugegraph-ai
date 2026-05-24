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

from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

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


def test_graph_extract_api_calls_flow(monkeypatch):
    scheduler = Mock()
    scheduler.schedule_flow.return_value = '{"vertices": [], "edges": []}'
    client = _client(monkeypatch, scheduler)

    response = client.post(
        "/thin/graph-extract",
        json={
            "text": "Alice knows Bob.",
            "schema": "{}",
            "example_prompt": "extract graph",
            "language": "en",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "data": '{"vertices": [], "edges": []}',
        "error": None,
    }
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

    response = client.post("/thin/graph-import", json={"data": "{}", "schema": None})

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["data"] == '{"imported": true}'
    scheduler.schedule_flow.assert_called_once_with(FlowName.IMPORT_GRAPH_DATA, "{}", None)


def test_vid_embeddings_refresh_api_calls_flow(monkeypatch):
    scheduler = Mock()
    scheduler.schedule_flow.return_value = "Removed 0 vectors, added 1 vectors."
    client = _client(monkeypatch, scheduler)

    response = client.post("/thin/vid-embeddings/refresh", json={})

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["data"] == "Removed 0 vectors, added 1 vectors."
    scheduler.schedule_flow.assert_called_once_with(FlowName.UPDATE_VID_EMBEDDINGS)


def test_graph_index_info_api_calls_flow(monkeypatch):
    scheduler = Mock()
    scheduler.schedule_flow.return_value = '{"vertices": 1}'
    client = _client(monkeypatch, scheduler)

    response = client.get("/thin/graph-index-info")

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["data"] == '{"vertices": 1}'
    scheduler.schedule_flow.assert_called_once_with(FlowName.GET_GRAPH_INDEX_INFO)


def test_thin_api_returns_flow_execution_failed(monkeypatch):
    scheduler = Mock()
    scheduler.schedule_flow.side_effect = RuntimeError("boom")
    client = _client(monkeypatch, scheduler)

    response = client.get("/thin/graph-index-info")

    assert response.status_code == 200
    assert response.json() == {
        "ok": False,
        "data": None,
        "error": {
            "type": "FLOW_EXECUTION_FAILED",
            "message": "boom",
        },
    }
