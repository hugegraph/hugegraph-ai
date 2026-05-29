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

"""ChatCompletionChunk SSE 适配层（Phase 1 / P1-T2.5）。

把 hugegraph-llm 内部 ``(answer_type, token_delta)`` 元组流包装成 OpenAI
``chat.completion.chunk`` 协议，供 ``/rag/stream`` 路由直接喂 SSE。

设计要点（见 spec/async_streaming_api/design.md §1.1 / §1.4）：

* 多 ``answer_type`` 类型映射到不同 ``choices[].index``，本响应内稳定不变。
* delta 直接由源头 ``async_streaming_generate`` 提供，禁止用"本轮累计 - 上轮累计"反推。
* 首块带 ``delta.role="assistant"``；每个用过的 index 在结束时各发一个空 delta +
  ``finish_reason="stop"``；流尾追加 ``data: [DONE]\\n\\n``。
* 错误事件用独立 ``event: error`` 行，不混进 ``chat.completion.chunk``。

Stream item contract（V1，与 review 对齐）：

  上游 generator（``post_deal_stream`` / ``schedule_stream_flow``）可 yield 三类项：

  1. ``(answer_type, token_delta)`` —— LLM token 增量，正常 path。
  2. ``{"warning": "...", ...}`` —— 非致命降级 / 元数据通道，例如外部 reranker
     失败回退 BLEU。HTTP SSE 以独立 ``event: warning`` 行下发；Gradio
     ``accumulate`` wrapper 以 ``__events__`` key 暴露给 demo 层。
  3. ``{"error": "..."}`` —— 控制级错误（如 ``stream_generator`` 缺失）；HTTP SSE
     以 ``event: error`` 行下发并以 [DONE] 收尾，``accumulate`` wrapper 将其向上
     抛 RuntimeError，避免错误被静默吞掉。
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, AsyncIterable, Dict, Optional, Tuple, Union

from hugegraph_llm.utils.log import log

# 流式 item 联合类型：token tuple 或 control / metadata dict。
StreamItem = Union[Tuple[str, str], Dict[str, Any]]

# answer_type → choices[].index，固定映射（见 design.md §1.1）。
ANSWER_TYPE_TO_INDEX: Dict[str, int] = {
    "raw_answer": 0,
    "vector_only_answer": 1,
    "graph_only_answer": 2,
    "graph_vector_answer": 3,
}

# 反向映射，便于错误处理时输出可读的 answer_type。
INDEX_TO_ANSWER_TYPE: Dict[int, str] = {v: k for k, v in ANSWER_TYPE_TO_INDEX.items()}


def _gen_completion_id() -> str:
    return f"chatcmpl-{uuid.uuid4().hex}"


def to_chat_completion_stream_chunk(
    token: Optional[str],
    index: int,
    role: Optional[str] = None,
    finish_reason: Optional[str] = None,
    completion_id: Optional[str] = None,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """构造单条 ChatCompletionChunk dict。

    禁止由本函数读取上一轮累计文本反推 delta —— delta 必须由调用方在 token
    产生时直接传入（见 design.md §1.4 "禁止"段）。
    """
    delta: Dict[str, Any] = {}
    if role is not None:
        delta["role"] = role
    if token:
        delta["content"] = token

    chunk: Dict[str, Any] = {
        "id": completion_id or _gen_completion_id(),
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "choices": [
            {
                "index": index,
                "delta": delta,
                "finish_reason": finish_reason,
            }
        ],
    }
    if model is not None:
        chunk["model"] = model
    return chunk


def _format_data_line(payload: Dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _format_event_line(event: str, payload: Dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def rag_stream_generator(
    delta_stream: AsyncIterable[StreamItem],
    *,
    trace_id: Optional[str] = None,
    is_disconnected=None,
    model: Optional[str] = None,
) -> AsyncIterable[str]:
    """把 ``(answer_type, token_delta)`` 流转成 SSE 行。

    Args:
        delta_stream: 源头 async generator，每次 yield 一个 token tuple 或 control
            dict（见模块 docstring 中的 stream item contract）。
        trace_id: 链路追踪 id，挂在 error 事件里。
        is_disconnected: 可选 awaitable callable，每次 yield 前调用，True 即
            停止写入并退出（best-effort cancellation，详见 requirements.md 1.3）。
        model: 可选模型名，写入每个 chunk 的 ``model`` 字段。

    Yields:
        SSE 字节行（已含 ``data: ... \\n\\n`` 或 ``event: error|warning\\n...``）。

    Errors:
        delta_stream 抛异常时，下发 ``event: error`` 而非 raise，避免半挂连接。
        最终始终发 ``data: [DONE]\\n\\n`` 哨兵。
    """
    completion_id = _gen_completion_id()
    seen_indexes: set[int] = set()

    try:
        async for item in delta_stream:
            if is_disconnected is not None:
                try:
                    if await is_disconnected():
                        log.info("client disconnected during stream, trace_id=%s", trace_id)
                        break
                except Exception as e:  # pylint: disable=broad-except
                    log.warning("is_disconnected probe failed: %s", e)

            # 控制 / 元数据通道（dict）：error 抛 RuntimeError 走 except 分支
            # 下发 event: error；warning / metadata 直接以独立 SSE event 透出，
            # 不会污染 chat.completion.chunk 主流。
            if isinstance(item, dict):
                if "error" in item:
                    raise RuntimeError(str(item.get("error")))
                if "warning" in item:
                    warn_payload: Dict[str, Any] = {"warning": str(item["warning"])}
                    if trace_id is not None:
                        warn_payload["trace_id"] = trace_id
                    # 顺带把额外的 metadata 一并透传（例如 switch_to_bleu）。
                    for k, v in item.items():
                        if k != "warning" and k not in warn_payload:
                            warn_payload[k] = v
                    yield _format_event_line("warning", warn_payload)
                    continue
                # 其它 metadata-only dict
                meta_payload = {k: v for k, v in item.items()}
                if trace_id is not None and "trace_id" not in meta_payload:
                    meta_payload["trace_id"] = trace_id
                yield _format_event_line("metadata", meta_payload)
                continue

            # token tuple
            if not (isinstance(item, tuple) and len(item) == 2):
                log.warning("unexpected stream item type=%s, trace_id=%s", type(item).__name__, trace_id)
                continue
            answer_type, token_delta = item

            if answer_type not in ANSWER_TYPE_TO_INDEX:
                log.warning("unknown answer_type=%r dropped, trace_id=%s", answer_type, trace_id)
                continue

            index = ANSWER_TYPE_TO_INDEX[answer_type]
            include_role = index not in seen_indexes
            seen_indexes.add(index)

            chunk = to_chat_completion_stream_chunk(
                token=token_delta,
                index=index,
                role="assistant" if include_role else None,
                completion_id=completion_id,
                model=model,
            )
            yield _format_data_line(chunk)
    except Exception as e:  # pylint: disable=broad-except
        log.exception("rag stream generator error, trace_id=%s", trace_id)
        err_payload: Dict[str, Any] = {"error": str(e)}
        if trace_id is not None:
            err_payload["trace_id"] = trace_id
        yield _format_event_line("error", err_payload)
        # error 路径也发 [DONE] 让客户端干净收尾。注意：不放在 finally 中 —— 当
        # StreamingResponse 因客户端断连关闭生成器时，finally 中的 yield 会触发
        # ``RuntimeError: async generator ignored GeneratorExit`` (PEP 525)。
        yield "data: [DONE]\n\n"
    else:
        # 正常结束：每个用过的 index 各发一个 finish_reason=stop 的空 chunk。
        for index in sorted(seen_indexes):
            final_chunk = to_chat_completion_stream_chunk(
                token=None,
                index=index,
                finish_reason="stop",
                completion_id=completion_id,
                model=model,
            )
            yield _format_data_line(final_chunk)
        # [DONE] 哨兵在所有结束 chunk 之后。
        yield "data: [DONE]\n\n"


async def accumulate(
    delta_stream: AsyncIterable[StreamItem],
) -> AsyncIterable[Dict[str, Any]]:
    """把 ``(answer_type, token_delta)`` 流累加成完整文本快照流。

    Gradio demo 端依赖"反复 yield 整个 context"的旧形态。本 wrapper 维持其语义，
    与新的 delta 流共享同一份 token 源（见 design.md §1.4 末尾）。

    Stream item 处理（与 :func:`rag_stream_generator` 共享 contract，避免一个
    通道处理 ``{"error": ...}`` 而另一个解包阶段炸掉，详见 review）：

      * ``(answer_type, token_delta)`` —— 按原语义累加并发快照。
      * ``{"error": ...}`` —— 上抛 ``RuntimeError`` 让 Gradio 层显式失败，
        而不是把"错误 dict"在 ``answer_type, token_delta = item`` 解包阶段
        变成 ValueError 掩盖根因。
      * ``{"warning": ...}`` 等控制 / 元数据 dict —— 通过快照里
        ``__events__`` 列表暴露，保持向后兼容（demo 层可选择忽略）。

    Yields:
        ``Dict[answer_type, accumulated_text]``，每个 token 到达后都 yield 一次。
    """
    snapshot: Dict[str, Any] = {}
    events: list = []
    async for item in delta_stream:
        if isinstance(item, dict):
            if "error" in item:
                # 显式失败优于在解包处炸掉。
                raise RuntimeError(str(item.get("error")))
            # warning / metadata：累计到 __events__ 列表，让 demo 层可见。
            events.append(dict(item))
            snapshot["__events__"] = list(events)
            yield dict(snapshot)
            continue

        if not (isinstance(item, tuple) and len(item) == 2):
            # 非法形态忽略，避免 Gradio yield 阶段崩溃。
            log.warning("accumulate ignored unexpected stream item type=%s", type(item).__name__)
            continue
        answer_type, token_delta = item
        if not token_delta:
            continue
        snapshot[answer_type] = snapshot.get(answer_type, "") + token_delta
        yield dict(snapshot)
