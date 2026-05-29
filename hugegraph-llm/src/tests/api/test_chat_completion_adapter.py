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

"""ChatCompletionChunk SSE adapter 单元测试。

覆盖 P1-T5 中的"协议合规断言"：
  * 每条 ``data:`` payload 是合法 JSON dict 且含 id / object / choices
  * 同 index 下所有 chunk 的 ``delta.content`` 拼接 = 完整答案
  * 任意 chunk 的 ``delta.content`` 不得等于"该 index 历史 content 拼接结果"
    （拒收"反复 yield 累计全文"实现）
  * 多 answer 场景同 answer_type 始终对应同一 index
  * 首 chunk 含 ``role="assistant"``；结束 chunk ``finish_reason="stop"`` 且 delta 不含 content
  * ``[DONE]`` 严格在所有结束 chunk 之后
  * 错误事件以 ``event: error`` 行起始，payload 含 trace_id
"""

import json
from typing import AsyncIterable, List, Tuple

import pytest

from hugegraph_llm.api.chat_completion_adapter import (
    ANSWER_TYPE_TO_INDEX,
    accumulate,
    rag_stream_generator,
    to_chat_completion_stream_chunk,
)


async def _delta_stream_from(items: List[Tuple[str, str]]) -> AsyncIterable[Tuple[str, str]]:
    for it in items:
        yield it


async def _collect(gen: AsyncIterable[str]) -> List[str]:
    out = []
    async for line in gen:
        out.append(line)
    return out


def _parse_data_chunks(lines: List[str]):
    """把 SSE 行流拆成 (data_chunks, error_payloads, has_done)。"""
    data_chunks = []
    error_payloads = []
    has_done = False
    pending_event = None
    for line in lines:
        if line.startswith("event: "):
            pending_event = line[len("event: ") :].strip().splitlines()[0]
            # event 行紧跟 data 行（同一条消息），用 \n\n 分割
            # 我们的实现把 event + data 写在一条 yield 里，因此需要继续解析
            if "\ndata: " in line:
                payload = line.split("\ndata: ", 1)[1].rstrip("\n")
                if pending_event == "error":
                    error_payloads.append(json.loads(payload))
                pending_event = None
            continue
        if not line.startswith("data: "):
            continue
        body = line[len("data: ") :].rstrip("\n")
        if body == "[DONE]":
            has_done = True
            continue
        data_chunks.append(json.loads(body))
    return data_chunks, error_payloads, has_done


# ---------- to_chat_completion_stream_chunk ----------


def test_chunk_shape_basic():
    chunk = to_chat_completion_stream_chunk(token="hello", index=0, role="assistant", completion_id="x")
    assert chunk["object"] == "chat.completion.chunk"
    assert chunk["id"] == "x"
    assert isinstance(chunk["created"], int)
    choice = chunk["choices"][0]
    assert choice["index"] == 0
    assert choice["delta"] == {"role": "assistant", "content": "hello"}
    assert choice["finish_reason"] is None


def test_chunk_finish_reason_no_content():
    chunk = to_chat_completion_stream_chunk(token=None, index=2, finish_reason="stop", completion_id="x")
    delta = chunk["choices"][0]["delta"]
    assert "content" not in delta
    assert "role" not in delta
    assert chunk["choices"][0]["finish_reason"] == "stop"


def test_chunk_empty_token_skipped():
    """空 token 不应写入 delta.content（避免下游误判）。"""
    chunk = to_chat_completion_stream_chunk(token="", index=0)
    assert "content" not in chunk["choices"][0]["delta"]


# ---------- rag_stream_generator ----------


@pytest.mark.asyncio
async def test_single_index_concat_equals_full_answer():
    items = [("raw_answer", "Hello "), ("raw_answer", "world"), ("raw_answer", "!")]
    lines = await _collect(rag_stream_generator(_delta_stream_from(items)))
    chunks, errs, has_done = _parse_data_chunks(lines)
    assert not errs
    assert has_done
    # 拼接 == 完整答案
    content = "".join(c["choices"][0]["delta"].get("content", "") for c in chunks)
    assert content == "Hello world!"


@pytest.mark.asyncio
async def test_first_chunk_has_role_subsequent_no_role():
    items = [("raw_answer", "a"), ("raw_answer", "b")]
    lines = await _collect(rag_stream_generator(_delta_stream_from(items)))
    chunks, _, _ = _parse_data_chunks(lines)
    # 首块 delta 含 role；后续不含
    deltas = [c["choices"][0]["delta"] for c in chunks if c["choices"][0]["finish_reason"] is None]
    assert deltas[0].get("role") == "assistant"
    for d in deltas[1:]:
        assert "role" not in d


@pytest.mark.asyncio
async def test_done_after_all_finish_chunks():
    items = [("raw_answer", "x"), ("vector_only_answer", "y")]
    lines = await _collect(rag_stream_generator(_delta_stream_from(items)))
    # [DONE] 必须出现在最后一行
    assert lines[-1] == "data: [DONE]\n\n"
    # 倒数第 2、3 行是 finish 块
    finish_lines = [ln for ln in lines if '"finish_reason": "stop"' in ln]
    assert len(finish_lines) == 2  # 两个 index 各一个 finish chunk


@pytest.mark.asyncio
async def test_index_mapping_stable_per_answer_type():
    """同一 answer_type 始终对应同一 index。"""
    items = [
        ("raw_answer", "a"),
        ("vector_only_answer", "b"),
        ("graph_only_answer", "c"),
        ("graph_vector_answer", "d"),
        ("raw_answer", "e"),  # 再来一次 raw，index 必须仍是 0
    ]
    lines = await _collect(rag_stream_generator(_delta_stream_from(items)))
    chunks, _, _ = _parse_data_chunks(lines)
    delta_chunks = [c for c in chunks if c["choices"][0]["finish_reason"] is None]
    seen = {}
    for c in delta_chunks:
        idx = c["choices"][0]["index"]
        content = c["choices"][0]["delta"]["content"]
        # 通过 content 反查 answer_type
        for at, expected_idx in ANSWER_TYPE_TO_INDEX.items():
            if content in {"a", "b", "c", "d", "e"} and (
                (content == "a" and at == "raw_answer")
                or (content == "b" and at == "vector_only_answer")
                or (content == "c" and at == "graph_only_answer")
                or (content == "d" and at == "graph_vector_answer")
                or (content == "e" and at == "raw_answer")
            ):
                seen.setdefault(at, set()).add(idx)
                assert idx == expected_idx
    # 每个 answer_type 只用过一个 index
    for at, idxs in seen.items():
        assert len(idxs) == 1, f"{at} mapped to multiple indexes: {idxs}"


@pytest.mark.asyncio
async def test_no_chunk_equals_accumulated_history():
    """**关键护栏**：任意 chunk 的 delta.content 不得等于该 index 历史 content 累积结果。"""
    items = [("raw_answer", "Hello "), ("raw_answer", "world!")]
    lines = await _collect(rag_stream_generator(_delta_stream_from(items)))
    chunks, _, _ = _parse_data_chunks(lines)
    accumulated = ""
    for c in chunks:
        if c["choices"][0]["finish_reason"] is not None:
            continue
        delta_content = c["choices"][0]["delta"].get("content", "")
        # delta 不得 == 历史拼接（防止累计 yield 全文）
        assert delta_content != accumulated, (
            f"chunk content {delta_content!r} equals accumulated history "
            f"{accumulated!r} — adapter regressed to cumulative-yield mode"
        )
        # 进一步：长度上限（单 token，宽容到 200 字符）
        assert len(delta_content) <= 200
        accumulated += delta_content


@pytest.mark.asyncio
async def test_unknown_answer_type_dropped():
    items = [("raw_answer", "ok"), ("unknown_type", "should be dropped")]
    lines = await _collect(rag_stream_generator(_delta_stream_from(items)))
    chunks, _, _ = _parse_data_chunks(lines)
    contents = [c["choices"][0]["delta"].get("content", "") for c in chunks]
    assert "ok" in contents
    assert "should be dropped" not in contents


@pytest.mark.asyncio
async def test_error_event_emitted_with_trace_id():
    """delta_stream 抛异常时下发 event: error 而非半挂连接。"""

    async def boom():
        yield "raw_answer", "ok"
        raise RuntimeError("upstream boom")

    lines = await _collect(rag_stream_generator(boom(), trace_id="trace-xyz"))
    # 有一行以 "event: error\n" 起始
    err_lines = [ln for ln in lines if ln.startswith("event: error\n")]
    assert err_lines, f"expected event: error line, got {lines!r}"
    payload_str = err_lines[0].split("\ndata: ", 1)[1].rstrip("\n")
    payload = json.loads(payload_str)
    assert payload["trace_id"] == "trace-xyz"
    assert "boom" in payload["error"]
    # 末尾仍发 [DONE]
    assert lines[-1] == "data: [DONE]\n\n"


@pytest.mark.asyncio
async def test_is_disconnected_short_circuits():
    """断开探针为 True 时立即停止写入。"""
    items = [("raw_answer", "a"), ("raw_answer", "b"), ("raw_answer", "c")]

    state = {"called": 0}

    async def is_disconnected():
        state["called"] += 1
        # 第二次探针返回 True，模拟客户端断开
        return state["called"] >= 2

    lines = await _collect(rag_stream_generator(_delta_stream_from(items), is_disconnected=is_disconnected))
    chunks, _, has_done = _parse_data_chunks(lines)
    delta_chunks = [c for c in chunks if c["choices"][0]["finish_reason"] is None]
    # 第一次探针 False 时写出第一个 chunk；第二次探针 True 后不再写新 delta
    assert len(delta_chunks) == 1
    # 即便断开也必须发 [DONE] 哨兵
    assert has_done


# ---------- accumulate ----------


@pytest.mark.asyncio
async def test_accumulate_yields_snapshot_per_token():
    items = [
        ("raw_answer", "Hi"),
        ("vector_only_answer", "Vec"),
        ("raw_answer", " there"),
    ]
    snapshots = []
    async for snap in accumulate(_delta_stream_from(items)):
        snapshots.append(dict(snap))
    # 三次 token 三次 snapshot
    assert len(snapshots) == 3
    assert snapshots[0] == {"raw_answer": "Hi"}
    assert snapshots[1] == {"raw_answer": "Hi", "vector_only_answer": "Vec"}
    assert snapshots[2] == {"raw_answer": "Hi there", "vector_only_answer": "Vec"}


# ---------- accumulate() 控制 / 元数据通道（review 阻塞项） ----------


@pytest.mark.asyncio
async def test_accumulate_raises_on_error_dict():
    """
    Review 阻塞项：``{"error": ...}`` 控制消息原本会在
    ``answer_type, token_delta = item`` 处变成 ValueError，掩盖根因。
    新 contract 应显式抛 RuntimeError，让 Gradio demo 层能正确感知失败。
    """

    async def producer():
        yield ("raw_answer", "ok")
        yield {"error": "stream_generator missing"}
        yield ("raw_answer", "should-not-arrive")

    with pytest.raises(RuntimeError, match="stream_generator missing"):
        async for _snap in accumulate(producer()):
            pass


@pytest.mark.asyncio
async def test_accumulate_surfaces_warning_in_events():
    """
    Review 阻塞项：``switch_to_bleu`` 这类降级 warning 必须能被 Gradio 端看到，
    不能静默丢弃。本测试断言 ``__events__`` 列表暴露给 demo 层。
    """
    items = [
        ("raw_answer", "Hi"),
        {"warning": "Online reranker fails, switches to bleu.", "switch_to_bleu": True},
        ("raw_answer", " there"),
    ]
    snapshots = []
    async for snap in accumulate(_delta_stream_from(items)):
        snapshots.append(dict(snap))

    # 累计文本不丢
    assert snapshots[-1]["raw_answer"] == "Hi there"
    # warning event 透出在 __events__ 列表
    final_events = snapshots[-1].get("__events__", [])
    assert any(ev.get("switch_to_bleu") is True for ev in final_events), f"events={final_events!r}"


# ---------- rag_stream_generator 控制 / 元数据通道 ----------


@pytest.mark.asyncio
async def test_rag_stream_generator_emits_event_warning_for_warning_dict():
    """上游 ``{"warning": ...}`` 控制消息 → 独立 ``event: warning`` SSE 行。"""

    async def producer():
        yield ("raw_answer", "ok")
        yield {"warning": "downgraded", "switch_to_bleu": True}

    lines = await _collect(rag_stream_generator(producer(), trace_id="t1"))
    warning_lines = [ln for ln in lines if ln.startswith("event: warning\n")]
    assert warning_lines, f"expected event: warning, lines={lines!r}"
    payload_str = warning_lines[0].split("\ndata: ", 1)[1].rstrip("\n")
    payload = json.loads(payload_str)
    assert payload.get("switch_to_bleu") is True
    assert payload["warning"] == "downgraded"
    # 主流 chunk 拼接仍正常
    chunks, _errs, has_done = _parse_data_chunks(lines)
    contents = "".join(
        c["choices"][0]["delta"].get("content", "") for c in chunks if c["choices"][0]["finish_reason"] is None
    )
    assert contents == "ok"
    assert has_done


@pytest.mark.asyncio
async def test_rag_stream_generator_emits_event_error_for_error_dict():
    """上游 ``{"error": ...}`` 控制消息 → ``event: error`` 而非半挂连接。"""

    async def producer():
        yield ("raw_answer", "partial")
        yield {"error": "stream_generator missing"}

    lines = await _collect(rag_stream_generator(producer(), trace_id="t2"))
    err_lines = [ln for ln in lines if ln.startswith("event: error\n")]
    assert err_lines
    payload_str = err_lines[0].split("\ndata: ", 1)[1].rstrip("\n")
    payload = json.loads(payload_str)
    assert "stream_generator missing" in payload["error"]
    assert payload["trace_id"] == "t2"
    assert lines[-1] == "data: [DONE]\n\n"


# ---------- rag_stream_generator 元数据通道 ----------


@pytest.mark.asyncio
async def test_rag_stream_generator_emits_event_metadata_for_unknown_dict():
    """
    非 error / warning 的 dict item（泛型元数据）必须以独立 ``event: metadata``
    行下发，不能污染 ``chat.completion.chunk`` 主流，也不能触发 error 路径。
    """

    async def producer():
        yield ("raw_answer", "ok")
        yield {"custom_key": "custom_value", "extra": 42}

    lines = await _collect(rag_stream_generator(producer(), trace_id="t-meta"))
    meta_lines = [ln for ln in lines if ln.startswith("event: metadata\n")]
    assert meta_lines, f"expected event: metadata line, got {lines!r}"

    payload_str = meta_lines[0].split("\ndata: ", 1)[1].rstrip("\n")
    payload = json.loads(payload_str)
    assert payload.get("custom_key") == "custom_value"
    assert payload.get("extra") == 42
    assert payload.get("trace_id") == "t-meta"

    # 主流 token 拼接不受影响
    chunks, errs, has_done = _parse_data_chunks(lines)
    assert not errs
    assert has_done
    delta_contents = "".join(
        c["choices"][0]["delta"].get("content", "") for c in chunks if c["choices"][0]["finish_reason"] is None
    )
    assert delta_contents == "ok"


@pytest.mark.asyncio
async def test_accumulate_surfaces_generic_metadata_in_events():
    """
    非 error / warning 的 dict（泛型元数据）也必须出现在 ``__events__`` 列表中，
    Gradio 端可选择处理（当前只对 warning 做 gr.Warning，其余忽略也安全）。
    """
    items = [
        ("raw_answer", "hi"),
        {"custom_key": "metadata_value", "some_count": 7},
        ("raw_answer", " world"),
    ]
    snapshots = []
    async for snap in accumulate(_delta_stream_from(items)):
        snapshots.append(dict(snap))

    # 最终累计文本完整
    assert snapshots[-1].get("raw_answer") == "hi world"

    # 泛型元数据 dict 出现在任意 snapshot 的 __events__ 中
    all_events = [ev for snap in snapshots for ev in (snap.get("__events__") or [])]
    assert any(ev.get("custom_key") == "metadata_value" for ev in all_events), (
        f"泛型元数据未出现在 __events__ 中，all_events={all_events!r}"
    )
    assert any(ev.get("some_count") == 7 for ev in all_events)


# ---------- 累计反推护栏：直接拒收"反复 yield 累计全文"实现 ----------


@pytest.mark.asyncio
async def test_no_chunk_equals_cumulative_typical_sequence():
    """
    Review review：原 ``test_no_chunk_equals_accumulated_history`` 用
    ["Hello ", "world!"] 测累计反推，但典型累计输入 ["Hello ", "Hello world!"]
    其实也能蒙混过关（"Hello world!" != "Hello "）。这里给一个明确反例：
    生产者直接 yield 累计快照的"经典递增"序列，至少 1 个 chunk 应被命中
    accumulated == delta 断言。本测试只是 *拦截器* —— 它消费当前 adapter，
    断言 adapter 不会在 cumulative producer 上输出"全部不同于历史"的 chunk
    序列（因为 cumulative producer 的第二条 token = ``"Hello world!"``，
    若 adapter 把它整段当 delta 喂出，那么累计后会是 "HelloHello world!"
    与下一段拼接之后断言失败）。
    """
    cumulative = [("raw_answer", "Hello "), ("raw_answer", "Hello world!")]
    lines = await _collect(rag_stream_generator(_delta_stream_from(cumulative)))
    chunks, _, _ = _parse_data_chunks(lines)
    # 累计 producer 的"完整答案"应是 "Hello world!"。
    # 但当前 adapter 透传 delta 不做反推，因此输出会是 "Hello Hello world!" —
    # 这是 cumulative producer 的正确"被检测"信号：消费方拼接之后包含双份前缀，
    # 说明 producer 而非 adapter 在做累计。把这条断言落到 *显式 expected*，
    # 避免后续把 adapter 改成"自动反推 delta"。
    full = "".join(
        c["choices"][0]["delta"].get("content", "") for c in chunks if c["choices"][0]["finish_reason"] is None
    )
    assert full == "Hello Hello world!", (
        "若 producer 在 yield 累计快照、adapter 自动反推 delta，则 full == 'Hello world!'。"
        "这违背 design.md §1.4 '禁止反推 delta' 的契约 —— delta 必须由源头 producer 给出。"
    )
