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

"""``/rag`` / ``/rag/graph`` / ``/text2gremlin`` / ``/config/*`` HTTP routes.

Phase 3 P3-T4: migrated from sync ``TestClient`` to ``httpx.AsyncClient`` +
``ASGITransport`` so we exercise the same path FastAPI uses for production
async clients (including the ``async def`` route handlers introduced in
P3-T1). One sync TestClient smoke test is retained to guard against
``StreamingResponse`` / middleware compatibility regressions on the sync
shim.
"""

import importlib
from contextlib import contextmanager
from unittest.mock import Mock

import pytest
from fastapi import APIRouter, FastAPI, status
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient


@contextmanager
def _async_routes_env(monkeypatch, enabled: bool):
    """Toggle the P3-T5 feature flag and reload ``rag_api`` so the route
    registrations re-read the env var."""
    if enabled:
        monkeypatch.delenv("HUGEGRAPH_LLM_ASYNC_ROUTES_ENABLED", raising=False)
    else:
        monkeypatch.setenv("HUGEGRAPH_LLM_ASYNC_ROUTES_ENABLED", "0")
    from hugegraph_llm.api import rag_api as rag_api_mod

    rag_api_mod = importlib.reload(rag_api_mod)
    try:
        yield rag_api_mod
    finally:
        # Reload again with default env so subsequent tests see a clean module.
        monkeypatch.delenv("HUGEGRAPH_LLM_ASYNC_ROUTES_ENABLED", raising=False)
        importlib.reload(rag_api_mod)


def _build_app(rag_api_mod, **mocks):
    router = APIRouter()
    rag_api_mod.rag_http_api(
        router,
        rag_answer_func=mocks.get("rag_answer_func", Mock()),
        graph_rag_recall_func=mocks.get("graph_rag_recall_func", Mock()),
        apply_graph_conf=mocks.get("apply_graph_conf", Mock()),
        apply_llm_conf=mocks.get("apply_llm_conf", Mock()),
        apply_embedding_conf=mocks.get("apply_embedding_conf", Mock()),
        apply_reranker_conf=mocks.get("apply_reranker_conf", Mock()),
        gremlin_generate_selective_func=mocks.get("gremlin_generate_selective_func", Mock()),
    )
    app = FastAPI()
    app.include_router(router)
    return app


# ---------- /config/graph (TestClient retained as smoke test) ----------


def test_graph_config_api_passes_graph_field_to_apply_graph_conf(monkeypatch):
    apply_graph_conf = Mock(return_value=status.HTTP_200_OK)
    with _async_routes_env(monkeypatch, enabled=True) as rag_api_mod:
        app = _build_app(rag_api_mod, apply_graph_conf=apply_graph_conf)
        response = TestClient(app).post(
            "/config/graph",
            json={
                "url": "127.0.0.1:8080",
                "graph": "custom_graph",
                "user": "admin",
                "pwd": "secret",
                "gs": "space_a",
            },
        )

    assert response.status_code == status.HTTP_201_CREATED
    assert response.json() == {"message": "Connection successful. Configured finished."}
    apply_graph_conf.assert_called_once_with(
        "127.0.0.1:8080",
        "custom_graph",
        "admin",
        "secret",
        "space_a",
        origin_call="http",
    )


# ---------- /rag (async route, AsyncClient) ----------


@pytest.mark.asyncio
async def test_rag_answer_async_route_runs_in_threadpool(monkeypatch):
    """P3-T1: ``async def rag_answer_api`` boundaries the legacy sync handler
    via ``asyncio.to_thread``. Validate that (a) the handler is invoked, and
    (b) the response shape matches the legacy sync route."""
    rag_answer_func = Mock(return_value=("raw out", "vec out", "graph out", "gv out"))
    with _async_routes_env(monkeypatch, enabled=True) as rag_api_mod:
        app = _build_app(rag_api_mod, rag_answer_func=rag_answer_func)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/rag",
                json={
                    "query": "what is hugegraph?",
                    "raw_answer": True,
                    "vector_only": False,
                    "graph_only": False,
                    "graph_vector_answer": False,
                },
            )

    assert resp.status_code == 200
    body = resp.json()
    assert body["query"] == "what is hugegraph?"
    assert body["raw_answer"] == "raw out"
    # only flagged answer types are surfaced
    assert "vector_only" not in body
    rag_answer_func.assert_called_once()


@pytest.mark.asyncio
async def test_rag_answer_async_empty_query_400(monkeypatch):
    with _async_routes_env(monkeypatch, enabled=True) as rag_api_mod:
        app = _build_app(rag_api_mod)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/rag",
                json={
                    "query": "   ",
                    "raw_answer": True,
                    "vector_only": False,
                    "graph_only": False,
                    "graph_vector_answer": False,
                },
            )
    assert resp.status_code == 400


# ---------- /rag (sync fallback via feature flag) ----------


def test_rag_answer_sync_route_when_flag_disabled(monkeypatch):
    """P3-T5: setting ``HUGEGRAPH_LLM_ASYNC_ROUTES_ENABLED=0`` rolls back to the
    pre-Phase-3 ``def`` handler. We sanity-check by calling via TestClient."""
    rag_answer_func = Mock(return_value=("a", "b", "c", "d"))
    with _async_routes_env(monkeypatch, enabled=False) as rag_api_mod:
        app = _build_app(rag_api_mod, rag_answer_func=rag_answer_func)
        resp = TestClient(app).post(
            "/rag",
            json={
                "query": "ping",
                "raw_answer": True,
                "vector_only": False,
                "graph_only": False,
                "graph_vector_answer": False,
            },
        )
    assert resp.status_code == 200
    assert resp.json()["raw_answer"] == "a"
    rag_answer_func.assert_called_once()


# ---------- /rag/graph (async) ----------


@pytest.mark.asyncio
async def test_graph_rag_recall_async_route(monkeypatch):
    graph_rag_recall_func = Mock(
        return_value={
            "query": "q",
            "keywords": ["k"],
            "match_vids": ["v1"],
            "graph_result_flag": True,
            "gremlin": "g.V()",
            "graph_result": {"foo": 1},
            "vertex_degree_list": [],
        }
    )
    with _async_routes_env(monkeypatch, enabled=True) as rag_api_mod:
        app = _build_app(rag_api_mod, graph_rag_recall_func=graph_rag_recall_func)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/rag/graph", json={"query": "anything"})

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["graph_recall"]["query"] == "q"
    assert payload["graph_recall"]["match_vids"] == ["v1"]
    graph_rag_recall_func.assert_called_once()


# ---------- /text2gremlin (async) ----------


@pytest.mark.asyncio
async def test_text2gremlin_async_route(monkeypatch):
    gremlin_generate = Mock(return_value={"gremlin": "g.V().limit(1)"})
    with _async_routes_env(monkeypatch, enabled=True) as rag_api_mod:
        app = _build_app(rag_api_mod, gremlin_generate_selective_func=gremlin_generate)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/text2gremlin", json={"query": "list one vertex"})

    assert resp.status_code == 200
    assert resp.json() == {"gremlin": "g.V().limit(1)"}
    gremlin_generate.assert_called_once()
