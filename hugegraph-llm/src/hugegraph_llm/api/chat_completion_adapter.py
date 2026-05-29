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
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, AsyncIterable, Dict, Optional, Tuple

from hugegraph_llm.utils.log import log

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
    delta_stream: AsyncIterable[Tuple[str, str]],
    *,
    trace_id: Optional[str] = None,
    is_disconnected=None,
    model: Optional[str] = None,
) -> AsyncIterable[str]:
    """把 ``(answer_type, token_delta)`` 流转成 SSE 行。

    Args:
        delta_stream: 源头 async generator，每次 yield ``(answer_type, token_delta)``，
            其中 ``answer_type`` 必须是 :data:`ANSWER_TYPE_TO_INDEX` 的键。
        trace_id: 链路追踪 id，挂在 error 事件里。
        is_disconnected: 可选 awaitable callable，每次 yield 前调用，True 即
            停止写入并退出（best-effort cancellation，详见 requirements.md 1.3）。
        model: 可选模型名，写入每个 chunk 的 ``model`` 字段。

    Yields:
        SSE 字节行（已含 ``data: ... \\n\\n`` 或 ``event: error\\n...``）。

    Errors:
        delta_stream 抛异常时，下发 ``event: error`` 而非 raise，避免半挂连接。
        最终始终发 ``data: [DONE]\\n\\n`` 哨兵。
    """
    completion_id = _gen_completion_id()
    seen_indexes: set[int] = set()

    try:
        async for answer_type, token_delta in delta_stream:
            if is_disconnected is not None:
                try:
                    if await is_disconnected():
                        log.info("client disconnected during stream, trace_id=%s", trace_id)
                        break
                except Exception as e:  # pylint: disable=broad-except
                    log.warning("is_disconnected probe failed: %s", e)

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
    finally:
        # [DONE] 哨兵在所有结束 chunk 之后；error 路径也发 [DONE] 让客户端干净收尾。
        yield "data: [DONE]\n\n"


async def accumulate(
    delta_stream: AsyncIterable[Tuple[str, str]],
) -> AsyncIterable[Dict[str, str]]:
    """把 ``(answer_type, token_delta)`` 流累加成完整文本快照流。

    Gradio demo 端依赖"反复 yield 整个 context"的旧形态。本 wrapper 维持其语义，
    与新的 delta 流共享同一份 token 源（见 design.md §1.4 末尾）。

    Yields:
        ``Dict[answer_type, accumulated_text]``，每个 token 到达后都 yield 一次。
    """
    snapshot: Dict[str, str] = {}
    async for answer_type, token_delta in delta_stream:
        if not token_delta:
            continue
        snapshot[answer_type] = snapshot.get(answer_type, "") + token_delta
        yield dict(snapshot)
