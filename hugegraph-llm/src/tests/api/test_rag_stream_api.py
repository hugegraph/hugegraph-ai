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
async def _make_client(monkeypatch, fake_stream_items=None, raise_inside=None, captured_kwargs=None):
    """构造一个挂好 /rag/stream 路由 + mock scheduler 的 AsyncClient。

    ``captured_kwargs``：可选 dict，若提供则 fake scheduler 会把实际收到的
    ``schedule_stream_flow(**kwargs)`` 写进去，供测试断言参数透传契约
    （拦截 review 提到的"fake scheduler 吞掉 **_kwargs"问题）。
    """
    from hugegraph_llm.api import rag_api as rag_api_mod

    class _FakeFlow:
        async def schedule_stream_flow(self, _flow_key, **kwargs):
            if captured_kwargs is not None:
                captured_kwargs.update(kwargs)
                captured_kwargs["_flow_key"] = _flow_key
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
    我们按 ``\\n\\n`` 切分并解析 data: / event: 行。

    返回 ``(data_chunks, error_payloads, warning_payloads, has_done)``。
    """
    data_chunks = []
    error_payloads = []
    warning_payloads = []
    has_done = False
    for block in text.split("\n\n"):
        block = block.strip("\n")
        if not block:
            continue
        if block.startswith("event: error"):
            data_line = next(ln for ln in block.split("\n") if ln.startswith("data: "))
            error_payloads.append(json.loads(data_line[len("data: ") :]))
            continue
        if block.startswith("event: warning"):
            data_line = next(ln for ln in block.split("\n") if ln.startswith("data: "))
            warning_payloads.append(json.loads(data_line[len("data: ") :]))
            continue
        if block.startswith("data: "):
            body = block[len("data: ") :]
            if body == "[DONE]":
                has_done = True
                continue
            data_chunks.append(json.loads(body))
    return data_chunks, error_payloads, warning_payloads, has_done


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

    chunks, errors, _warnings, has_done = _parse_sse_lines(text)
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

    chunks, _, _warnings, has_done = _parse_sse_lines(text)
    assert has_done
    delta_chunks = [c for c in chunks if c["choices"][0]["finish_reason"] is None]
    # 4 种 answer_type → 4 个不同 index，每个 index 有一个结束块
    final_chunks = [c for c in chunks if c["choices"][0]["finish_reason"] == "stop"]
    assert {c["choices"][0]["index"] for c in final_chunks} == {0, 1, 2, 3}
    # 同 answer_type "raw_answer" 拼接 = "R1R2"
    raw_content = "".join(
        c["choices"][0]["delta"].get("content", "") for c in delta_chunks if c["choices"][0]["index"] == 0
    )
    assert raw_content == "R1R2"


@pytest.mark.asyncio
async def test_rag_stream_no_chunk_equals_accumulated_prefix(monkeypatch):
    """关键护栏：拒收"反复 yield 累计全文"实现。"""
    items = [("raw_answer", "Hello "), ("raw_answer", "world!")]
    async with _make_client(monkeypatch, fake_stream_items=items) as client:
        async with client.stream("POST", "/rag/stream", json=_payload(raw_answer=True)) as resp:
            text = (await resp.aread()).decode("utf-8")

    chunks, _, _warnings, _done = _parse_sse_lines(text)
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

    _, errors, _warnings, has_done = _parse_sse_lines(text)
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


# ---------- /rag/stream 参数透传契约（review 阻塞项） ----------


@pytest.mark.asyncio
async def test_rag_stream_passes_retrieval_params_to_scheduler(monkeypatch):
    """
    阻塞项 (review)：/rag/stream 必须把 RAGRequest 中的检索调参
    (max_graph_items / topk_return_results / vector_dis_threshold /
    topk_per_keyword) 透传给 scheduler.schedule_stream_flow，否则同一个请求体
    在 /rag 与 /rag/stream 上的召回 / 排序语义会不一致。

    使用 *非默认 sentinel 值*（不是 None / 0 / 0.0）避免被 fake scheduler 漏接。
    """
    captured: dict = {}
    async with _make_client(
        monkeypatch,
        fake_stream_items=[("raw_answer", "ok")],
        captured_kwargs=captured,
    ) as client:
        body = _payload(raw_answer=True)
        # 非默认 sentinel：保证测试不会被全局默认值误判为透传成功
        body["max_graph_items"] = 1234
        body["topk_return_results"] = 77
        body["vector_dis_threshold"] = 0.42
        body["topk_per_keyword"] = 9
        async with client.stream("POST", "/rag/stream", json=body) as resp:
            await resp.aread()
            assert resp.status_code == 200

    assert captured.get("max_graph_items") == 1234, f"missing max_graph_items, got: {captured!r}"
    assert captured.get("topk_return_results") == 77
    assert captured.get("vector_dis_threshold") == 0.42
    assert captured.get("topk_per_keyword") == 9


# ---------- /rag vs /rag/stream 检索参数 contract（review 阻塞项 follow-up） ----------


@pytest.mark.asyncio
async def test_rag_and_rag_stream_share_retrieval_param_contract(monkeypatch):
    """
    Cross-route contract test：同一份 RAGRequest body 同时打 /rag 与 /rag/stream，
    断言两条路径透传到底层（``rag_answer_func`` / ``schedule_stream_flow``）的
    4 个检索调参完全一致。

    单独的 ``test_rag_answer_passes_retrieval_params_to_func`` 与
    ``test_rag_stream_passes_retrieval_params_to_scheduler`` 都依赖 reviewer
    肉眼对齐 sentinel；这条 test 把"两条路径参数对等"做成机器可断言的不变量，
    任一边今后漏传 / 漏接 / 改名都会被立即抓出。
    """
    from hugegraph_llm.api import rag_api as rag_api_mod

    # /rag/stream 这条走 scheduler.schedule_stream_flow，捕获其 kwargs
    stream_captured: dict = {}

    class _FakeFlow:
        async def schedule_stream_flow(self, _flow_key, **kwargs):
            stream_captured.update(kwargs)
            await asyncio.sleep(0)
            yield ("raw_answer", "ok")

    monkeypatch.setattr(
        rag_api_mod.SchedulerSingleton,
        "get_instance",
        classmethod(lambda cls: _FakeFlow()),
    )

    # /rag 这条走 rag_answer_func，捕获其 kwargs
    rag_answer_func = Mock(return_value=("ok", None, None, None))

    router = APIRouter()
    rag_api_mod.rag_http_api(
        router,
        rag_answer_func=rag_answer_func,
        graph_rag_recall_func=Mock(),
        apply_graph_conf=Mock(),
        apply_llm_conf=Mock(),
        apply_embedding_conf=Mock(),
        apply_reranker_conf=Mock(),
        gremlin_generate_selective_func=Mock(),
    )
    app = FastAPI()
    app.include_router(router)

    # 非默认 sentinel：必须避开 RAGRequest 默认值（30 / 20 / 0.9 / 1），
    # 否则"漏传 → 退回全局默认"也能巧合通过。
    retrieval_params = {
        "max_graph_items": 1234,
        "topk_return_results": 77,
        "vector_dis_threshold": 0.42,
        "topk_per_keyword": 9,
    }
    body = _payload(raw_answer=True)
    body.update(retrieval_params)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 先打 /rag —— 同步收尾路径
        resp_sync = await client.post("/rag", json=body)
        assert resp_sync.status_code == 200
        # 再打 /rag/stream —— 流式路径
        async with client.stream("POST", "/rag/stream", json=body) as resp_stream:
            await resp_stream.aread()
            assert resp_stream.status_code == 200

    rag_answer_func.assert_called_once()
    sync_kwargs = rag_answer_func.call_args.kwargs

    # 1) /rag 路径透传 OK
    for k, v in retrieval_params.items():
        assert sync_kwargs.get(k) == v, f"/rag dropped {k}: expected {v!r}, got {sync_kwargs.get(k)!r}"
    # 2) /rag/stream 路径透传 OK
    for k, v in retrieval_params.items():
        assert stream_captured.get(k) == v, f"/rag/stream dropped {k}: expected {v!r}, got {stream_captured.get(k)!r}"
    # 3) 两条路径在这 4 个键上严格相等 —— drift 立刻爆炸
    sync_subset = {k: sync_kwargs.get(k) for k in retrieval_params}
    stream_subset = {k: stream_captured.get(k) for k in retrieval_params}
    assert sync_subset == stream_subset, (
        f"retrieval param contract drift between /rag and /rag/stream:\n"
        f"  /rag        -> {sync_subset!r}\n"
        f"  /rag/stream -> {stream_subset!r}"
    )


# ---------- /rag/stream 控制 / 元数据通道（review 阻塞项） ----------


@pytest.mark.asyncio
async def test_rag_stream_warning_event_passed_through(monkeypatch):
    """
    阻塞项 (review)：delta-only stream contract 不能丢失 ``switch_to_bleu``
    这种降级状态。上游若 yield ``{"warning": ...}`` 控制消息，HTTP SSE 必须
    以独立 ``event: warning`` 行下发，不能静默吞掉。
    """
    items = [
        ("raw_answer", "Hello"),
        {"warning": "Online reranker fails, switches to bleu.", "switch_to_bleu": True},
        ("raw_answer", " world"),
    ]
    async with _make_client(monkeypatch, fake_stream_items=items) as client:
        async with client.stream("POST", "/rag/stream", json=_payload(raw_answer=True)) as resp:
            text = (await resp.aread()).decode("utf-8")

    chunks, errors, warnings, has_done = _parse_sse_lines(text)
    assert not errors
    assert has_done
    assert warnings, f"expected event: warning passed through, text={text!r}"
    assert warnings[0].get("switch_to_bleu") is True
    assert "bleu" in warnings[0]["warning"]
    # warning 不应污染 chat.completion.chunk 主流，token 拼接仍是 "Hello world"
    contents = "".join(
        c["choices"][0]["delta"].get("content", "") for c in chunks if c["choices"][0]["finish_reason"] is None
    )
    assert contents == "Hello world"


@pytest.mark.asyncio
async def test_rag_stream_error_dict_emits_event_error(monkeypatch):
    """上游 yield ``{"error": ...}`` 控制消息 → 下发 ``event: error`` 而非崩溃。"""
    items = [
        ("raw_answer", "partial"),
        {"error": "stream_generator missing"},
    ]
    async with _make_client(monkeypatch, fake_stream_items=items) as client:
        async with client.stream("POST", "/rag/stream", json=_payload(raw_answer=True)) as resp:
            text = (await resp.aread()).decode("utf-8")

    _chunks, errors, _warnings, has_done = _parse_sse_lines(text)
    assert errors, f"expected event: error, got: {text!r}"
    assert "stream_generator missing" in errors[0]["error"]
    assert has_done


@pytest.mark.asyncio
async def test_rag_stream_metadata_event_passed_through(monkeypatch):
    """
    上游 yield 泛型 dict（非 error / warning）→ 下发 ``event: metadata`` SSE 行，
    不污染 ``chat.completion.chunk`` 主流，也不触发 error 路径。
    """
    items = [
        ("raw_answer", "hello"),
        {"custom_meta": "some_value", "extra_count": 99},
        ("raw_answer", " world"),
    ]
    async with _make_client(monkeypatch, fake_stream_items=items) as client:
        async with client.stream("POST", "/rag/stream", json=_payload(raw_answer=True)) as resp:
            text = (await resp.aread()).decode("utf-8")

    # event: metadata 行必须存在
    assert "event: metadata" in text, f"expected event: metadata in stream, text={text!r}"

    # 解析验证 payload 字段
    meta_payloads = []
    for block in text.split("\n\n"):
        block = block.strip("\n")
        if block.startswith("event: metadata"):
            data_line = next((ln for ln in block.split("\n") if ln.startswith("data: ")), None)
            if data_line:
                meta_payloads.append(json.loads(data_line[len("data: ") :]))
    assert meta_payloads, f"metadata payload 解析失败，text={text!r}"
    assert meta_payloads[0].get("custom_meta") == "some_value"
    assert meta_payloads[0].get("extra_count") == 99

    # 主流 token 拼接不受影响
    chunks, errors, _warnings, has_done = _parse_sse_lines(text)
    assert not errors
    assert has_done
    contents = "".join(
        c["choices"][0]["delta"].get("content", "") for c in chunks if c["choices"][0]["finish_reason"] is None
    )
    assert contents == "hello world"
