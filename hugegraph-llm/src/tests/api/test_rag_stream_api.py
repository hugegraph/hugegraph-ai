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

"""``/rag/stream`` 路由集成测试（P1-T5）。

通过 monkeypatching ``SchedulerSingleton.get_instance().schedule_stream_flow`` 替换为
mock async generator，避开真实 pipeline / pyhugegraph，专注验证 SSE 协议合规性。
"""

import asyncio
import json
from contextlib import asynccontextmanager
from unittest.mock import Mock

import pytest
from fastapi import APIRouter, FastAPI
from httpx import ASGITransport, AsyncClient

from hugegraph_llm.api.rag_api import rag_http_api


@asynccontextmanager
async def _make_client(monkeypatch, fake_stream_items=None, raise_inside=None):
    """构造一个挂好 /rag/stream 路由 + mock scheduler 的 AsyncClient。"""
    from hugegraph_llm.api import rag_api as rag_api_mod

    class _FakeFlow:
        async def schedule_stream_flow(self, _flow_key, **_kwargs):
            if raise_inside:
                raise raise_inside
            for it in fake_stream_items or []:
                # 模拟 pipeline 调度后让出事件循环
                await asyncio.sleep(0)
                yield it

    fake_scheduler = _FakeFlow()
    monkeypatch.setattr(
        rag_api_mod.SchedulerSingleton,
        "get_instance",
        classmethod(lambda cls: fake_scheduler),
    )

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
    app = FastAPI()
    app.include_router(router)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


def _payload(query="hello?", **flags) -> dict:
    body = {
        "query": query,
        "raw_answer": False,
        "vector_only": False,
        "graph_only": False,
        "graph_vector_answer": False,
    }
    body.update(flags)
    return body


def _parse_sse_lines(text: str):
    """SSE chunks 已在 adapter 层逐行 yield，httpx 把它们拼成 text；
    我们按 ``\\n\\n`` 切分并解析 data: / event: 行。"""
    data_chunks = []
    error_payloads = []
    has_done = False
    for block in text.split("\n\n"):
        block = block.strip("\n")
        if not block:
            continue
        if block.startswith("event: error"):
            data_line = next(ln for ln in block.split("\n") if ln.startswith("data: "))
            error_payloads.append(json.loads(data_line[len("data: ") :]))
            continue
        if block.startswith("data: "):
            body = block[len("data: ") :]
            if body == "[DONE]":
                has_done = True
                continue
            data_chunks.append(json.loads(body))
    return data_chunks, error_payloads, has_done


# ---------- /rag/stream ----------


@pytest.mark.asyncio
async def test_rag_stream_basic_flow_raw(monkeypatch):
    items = [("raw_answer", "Hello "), ("raw_answer", "world"), ("raw_answer", "!")]
    async with _make_client(monkeypatch, fake_stream_items=items) as client:
        async with client.stream("POST", "/rag/stream", json=_payload(raw_answer=True)) as resp:
            assert resp.status_code == 200
            assert resp.headers["content-type"].startswith("text/event-stream")
            assert resp.headers["x-accel-buffering"] == "no"
            assert resp.headers["cache-control"] == "no-cache"
            assert "x-trace-id" in resp.headers
            text = await resp.aread()
            text = text.decode("utf-8")

    chunks, errors, has_done = _parse_sse_lines(text)
    assert not errors
    assert has_done
    # 同 index 拼接 == 完整答案
    contents = [c["choices"][0]["delta"].get("content", "") for c in chunks if c["choices"][0]["finish_reason"] is None]
    assert "".join(contents) == "Hello world!"
    # 首块带 role
    first_delta_chunk = next(c for c in chunks if c["choices"][0]["finish_reason"] is None)
    assert first_delta_chunk["choices"][0]["delta"].get("role") == "assistant"
    # 结束块 finish_reason=stop 且 delta 不含 content
    final_chunks = [c for c in chunks if c["choices"][0]["finish_reason"] == "stop"]
    assert len(final_chunks) == 1
    assert "content" not in final_chunks[0]["choices"][0]["delta"]


@pytest.mark.asyncio
async def test_rag_stream_multi_answer_indexes_stable(monkeypatch):
    items = [
        ("raw_answer", "R1"),
        ("vector_only_answer", "V1"),
        ("graph_only_answer", "G1"),
        ("graph_vector_answer", "GV1"),
        ("raw_answer", "R2"),
    ]
    async with _make_client(monkeypatch, fake_stream_items=items) as client:
        async with client.stream(
            "POST",
            "/rag/stream",
            json=_payload(raw_answer=True, vector_only=True, graph_only=True, graph_vector_answer=True),
        ) as resp:
            text = (await resp.aread()).decode("utf-8")

    chunks, _, has_done = _parse_sse_lines(text)
    assert has_done
    delta_chunks = [c for c in chunks if c["choices"][0]["finish_reason"] is None]
    # 4 种 answer_type → 4 个不同 index，每个 index 有一个结束块
    final_chunks = [c for c in chunks if c["choices"][0]["finish_reason"] == "stop"]
    assert {c["choices"][0]["index"] for c in final_chunks} == {0, 1, 2, 3}
    # 同 answer_type "raw_answer" 拼接 = "R1R2"
    raw_content = "".join(
        c["choices"][0]["delta"].get("content", "")
        for c in delta_chunks
        if c["choices"][0]["index"] == 0
    )
    assert raw_content == "R1R2"


@pytest.mark.asyncio
async def test_rag_stream_no_chunk_equals_accumulated_prefix(monkeypatch):
    """关键护栏：拒收"反复 yield 累计全文"实现。"""
    items = [("raw_answer", "Hello "), ("raw_answer", "world!")]
    async with _make_client(monkeypatch, fake_stream_items=items) as client:
        async with client.stream("POST", "/rag/stream", json=_payload(raw_answer=True)) as resp:
            text = (await resp.aread()).decode("utf-8")

    chunks, _, _ = _parse_sse_lines(text)
    accumulated = ""
    for c in chunks:
        if c["choices"][0]["finish_reason"] is not None:
            continue
        delta = c["choices"][0]["delta"].get("content", "")
        assert delta != accumulated, (
            f"chunk content {delta!r} equals accumulated history {accumulated!r}; "
            "implementation regressed to cumulative-yield mode"
        )
        accumulated += delta


@pytest.mark.asyncio
async def test_rag_stream_error_event_with_trace_id(monkeypatch):
    """upstream 抛异常时下发 event: error 而非半挂或 5xx。"""
    async with _make_client(monkeypatch, raise_inside=RuntimeError("scheduler boom")) as client:
        async with client.stream("POST", "/rag/stream", json=_payload(raw_answer=True)) as resp:
            assert resp.status_code == 200  # 流首字节后 status code 已无法变更
            text = (await resp.aread()).decode("utf-8")

    _, errors, has_done = _parse_sse_lines(text)
    assert errors, f"expected event: error in stream, got {text!r}"
    assert "trace_id" in errors[0]
    assert "boom" in errors[0]["error"]
    assert has_done  # 错误路径仍发 [DONE]


@pytest.mark.asyncio
async def test_rag_stream_empty_query_400(monkeypatch):
    async with _make_client(monkeypatch, fake_stream_items=[]) as client:
        resp = await client.post("/rag/stream", json=_payload(query="   ", raw_answer=True))
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_rag_stream_no_answer_flag_400(monkeypatch):
    async with _make_client(monkeypatch, fake_stream_items=[]) as client:
        resp = await client.post("/rag/stream", json=_payload())
    assert resp.status_code == 400
