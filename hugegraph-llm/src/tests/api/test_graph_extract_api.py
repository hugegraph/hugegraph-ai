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

import json
from unittest.mock import Mock

import pytest
from fastapi import APIRouter, FastAPI, status
from fastapi.testclient import TestClient
from pydantic import ValidationError

from hugegraph_llm.api.graph_extract_api import graph_extract_http_api
from hugegraph_llm.api.models.graph_extract_requests import GraphExtractClientConfig, GraphExtractRequest
from hugegraph_llm.api.models.graph_extract_responses import GraphExtractResponse
from hugegraph_llm.api.rag_api import rag_http_api
from hugegraph_llm.config import huge_settings
from hugegraph_llm.flows.graph_extract import GraphExtractFlow
from hugegraph_llm.services.graph_extract_service import GraphExtractService
from hugegraph_llm.state.ai_state import WkFlowInput

INLINE_SCHEMA = {"vertexlabels": [], "edgelabels": []}
VALID_SCHEMA = {
    "vertexlabels": [{"name": "person", "properties": ["name"]}],
    "edgelabels": [{"name": "knows", "source_label": "person", "target_label": "person"}],
}


class CapturePipeline:
    def __init__(self):
        self.params = {}

    def createGParam(self, value, name):
        self.params[name] = value

    def registerGElement(self, *args):
        return None


def _graph_client(service=None):
    router = APIRouter()
    graph_extract_http_api(router, service=service)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _named_client_config(graph="custom_graph"):
    return {"graph": graph, "user": "admin", "pwd": "secret", "gs": "space_a"}


def _graph_result():
    return {
        "vertices": [{"label": "person", "properties": {"name": "marko"}}],
        "edges": [
            {
                "label": "knows",
                "outV": "marko",
                "outVLabel": "person",
                "inV": "vadas",
                "inVLabel": "person",
                "properties": {},
            }
        ],
    }


def test_graph_extract_returns_envelope_from_service():
    service = Mock()
    service.extract_sync.return_value = GraphExtractResponse(
        status="succeeded",
        result=_graph_result(),
        warnings=[],
        meta={"vertex_count": 1, "edge_count": 1, "text_count": 1},
    )

    response = _graph_client(service).post(
        "/graph/extract",
        json={"texts": "marko knows vadas", "schema": VALID_SCHEMA, "include_meta": True},
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {
        "status": "succeeded",
        "result": _graph_result(),
        "warnings": [],
        "meta": {"vertex_count": 1, "edge_count": 1, "text_count": 1},
    }
    service.extract_sync.assert_called_once()


def test_graph_extract_rejects_invalid_public_contract_inputs():
    client = _graph_client(Mock())

    cases = [
        {"texts": "  ", "schema": INLINE_SCHEMA},
        {"texts": "x", "schema": "{bad"},
        {"texts": "x", "schema": {"vertexlabels": [{"name": "person"}], "edgelabels": []}},
        {"texts": "x", "schema": INLINE_SCHEMA, "split_type": "doc"},
        {"texts": "x", "schema": INLINE_SCHEMA, "extract_type": "triples"},
        {"texts": "x", "schema": "hugegraph"},
        {"texts": "x", "schema": INLINE_SCHEMA, "client_config": _named_client_config()},
        {"texts": "x", "schema": "custom_graph", "client_config": _named_client_config("other_graph")},
        {"texts": "x", "schema": "custom_graph", "client_config": {"graph": "custom_graph", "url": "10.0.0.1:8080"}},
    ]

    for payload in cases:
        response = client.post("/graph/extract", json=payload)
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_graph_extract_service_parses_flow_json_and_records_metadata():
    scheduler = Mock()
    scheduler.schedule_flow.return_value = json.dumps(
        {
            **_graph_result(),
            "call_count": 2,
            "warning": "schema mismatch",
        }
    )

    response = GraphExtractService(scheduler).extract_sync(
        GraphExtractRequest(texts="marko knows vadas", schema=VALID_SCHEMA, language="en", include_meta=True)
    )

    assert response.status == "succeeded"
    assert response.result == _graph_result()
    assert response.warnings == ["schema mismatch"]
    assert response.meta["extract_type"] == "property_graph"
    assert response.meta["language"] == "en"
    assert response.meta["text_count"] == 1
    assert response.meta["vertex_count"] == 1
    assert response.meta["edge_count"] == 1
    assert response.meta["call_count"] == 2
    scheduler.schedule_flow.assert_called_once()
    assert scheduler.schedule_flow.call_args.kwargs["language"] == "en"
    assert scheduler.schedule_flow.call_args.kwargs["split_type"] == "document"


def test_graph_extract_service_passes_request_local_client_config_and_redacts_password(monkeypatch):
    scheduler = Mock()
    scheduler.schedule_flow.return_value = json.dumps({"vertices": [], "edges": []})
    monkeypatch.setattr(huge_settings, "graph_url", "127.0.0.1:8080")
    original = (
        huge_settings.graph_url,
        huge_settings.graph_name,
        huge_settings.graph_user,
        huge_settings.graph_pwd,
        huge_settings.graph_space,
    )
    client_config = GraphExtractClientConfig(graph="custom_graph", user="admin", pwd="secret", gs="space_a")

    response = GraphExtractService(scheduler).extract_sync(
        GraphExtractRequest(
            texts="x",
            schema="custom_graph",
            client_config=client_config,
            include_meta=True,
        )
    )

    assert scheduler.schedule_flow.call_args.kwargs["client_config"] == client_config
    assert "graph_config" not in scheduler.schedule_flow.call_args.kwargs
    assert response.meta["client_config"] == {
        "graph": "custom_graph",
        "user": "admin",
        "pwd": "***",
        "gs": "space_a",
    }
    assert (
        huge_settings.graph_url,
        huge_settings.graph_name,
        huge_settings.graph_user,
        huge_settings.graph_pwd,
        huge_settings.graph_space,
    ) == original


def test_graph_extract_service_rejects_invalid_flow_json():
    scheduler = Mock()
    scheduler.schedule_flow.return_value = "{broken"

    with pytest.raises(ValueError, match="Invalid graph extraction flow JSON"):
        GraphExtractService(scheduler).extract_sync(GraphExtractRequest(texts="x", schema=INLINE_SCHEMA))


def test_property_graph_response_rejects_legacy_edge_shape():
    scheduler = Mock()
    scheduler.schedule_flow.return_value = json.dumps(
        {
            "vertices": [{"label": "person", "properties": {"name": "marko"}}],
            "edges": [{"start": "marko", "type": "knows", "end": "vadas"}],
        }
    )

    with pytest.raises(ValueError, match="canonical property graph edge"):
        GraphExtractService(scheduler).extract_sync(GraphExtractRequest(texts="x", schema=INLINE_SCHEMA))


def test_request_model_validation_and_aliases():
    req = GraphExtractRequest(texts="hello", schema=INLINE_SCHEMA)
    assert req.texts == ["hello"]
    assert req.graph_schema == INLINE_SCHEMA
    assert req.schema == INLINE_SCHEMA
    assert req.client_config is None

    with pytest.raises(ValidationError):
        GraphExtractRequest(texts=[], schema="hugegraph")


def test_flow_prepare_sets_request_local_graph_config():
    flow = GraphExtractFlow()
    prepared_input = WkFlowInput()
    client_config = GraphExtractClientConfig(graph="custom_graph", user="admin", pwd="secret", gs="space_a")

    flow.prepare(prepared_input, "custom_graph", ["text"], "prompt", "property_graph", client_config=client_config)

    assert prepared_input.graph_client_config == {
        "url": huge_settings.graph_url,
        "user": "admin",
        "pwd": "secret",
        "graphspace": "space_a",
    }


def test_flow_build_flow_preserves_split_type_and_client_config(monkeypatch):
    monkeypatch.setattr("hugegraph_llm.flows.graph_extract.GPipeline", CapturePipeline)
    client_config = GraphExtractClientConfig(graph="custom_graph", user="admin", pwd="secret", gs="space_a")

    pipeline = GraphExtractFlow().build_flow(
        "custom_graph",
        ["text"],
        "prompt",
        "property_graph",
        split_type="paragraph",
        client_config=client_config,
    )

    prepared_input = pipeline.params["wkflow_input"]
    assert prepared_input.split_type == "paragraph"
    assert prepared_input.graph_client_config["graphspace"] == "space_a"


def test_wkflow_input_reset_clears_graph_configs():
    prepared_input = WkFlowInput()
    prepared_input.graph_client_config = {"url": "10.0.0.1:8080"}
    prepared_input.graph_config = {"graph": "custom_graph"}

    prepared_input.reset(None)

    assert prepared_input.graph_client_config is None
    assert prepared_input.graph_config is None


def test_existing_routes_still_register():
    router = APIRouter()
    rag_http_api(
        router,
        rag_answer_func=Mock(),
        graph_rag_recall_func=Mock(),
        apply_graph_conf=Mock(),
        apply_llm_conf=Mock(),
        apply_embedding_conf=Mock(),
        apply_reranker_conf=Mock(),
        gremlin_generate_selective_func=Mock(),
    )
    graph_extract_http_api(router)
    app = FastAPI()
    app.include_router(router)

    paths = set(app.openapi()["paths"])
    assert "/rag" in paths
    assert "/text2gremlin" in paths
    assert "/config/graph" in paths
    assert "/graph/extract" in paths
    assert "/graph/extract/jobs" in paths
    assert "/graph/import" in paths
    assert "/graph/extract-and-import" in paths
