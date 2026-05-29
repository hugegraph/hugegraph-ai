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

"""
Deterministic OpenAI-compatible mock LLM server (Phase 3 P3-T6 压测专用).

把 hugegraph-llm 配的 openai.api_base 指向这台 mock 后，路由层 + pipeline 调度的
时延就不再被真实 LLM 后端的网络抖动 + token 生成时间淹没——可以干净地对比
"async route vs sync route 在事件循环上的吞吐差异"，以及验证 Phase 3 退出标准的
QPS=1 时延退化 ≤ 5% / QPS=32 吞吐 ≥ 同步基线 2.5x 两条门禁。

设计目标（与 P3-T6 验收对齐）:
  - 行为完全确定性：first-token 延迟、per-token 延迟、token 数都是配置值
  - 同时支持 stream=True (SSE) 与 stream=False (一次性 JSON)
  - 协议子集：仅实现 /v1/chat/completions，足够覆盖 hugegraph-llm 所有 LLM 出口
    （包括 raw_answer / vector_only / graph_only / graph_vector 四种 answer_type
    并发场景；后端只是吐固定 token，并发由 hugegraph-llm 自己调度）
  - **完全 async**：用 asyncio.sleep 模拟时延，不阻塞事件循环——否则压测结果反映
    的是 mock server 的瓶颈，不是被测系统的瓶颈

Usage（与 async_load_probe.py 配合的标准跑法）:

  Terminal A — 起 mock LLM:
    python scripts/mock_llm_server.py --port 9999 \\
      --first-token-delay 0.2 --per-token-delay 0.02 --tokens 100

  Terminal B — 让 hugegraph-llm 指向 mock:
    export OPENAI_API_KEY=sk-fake
    export OPENAI_API_BASE=http://127.0.0.1:9999/v1
    # 用 P3-T5 feature flag 切 async / sync 两条路径分别压
    HUGEGRAPH_LLM_ASYNC_ROUTES_ENABLED=1 \\
      python -m hugegraph_llm.demo.rag_demo.app --port 8001

  Terminal C — 跑压测:
    # SSE async route
    python scripts/async_load_probe.py --concurrency 32 --requests 200
    # 非流式 async route
    python scripts/async_load_probe.py --endpoint /rag --no-stream \\
      --concurrency 32 --requests 200
    # 第二轮把 app 重启 + 设 HUGEGRAPH_LLM_ASYNC_ROUTES_ENABLED=0 跑同步基线

Env / CLI 等价配置:
  --first-token-delay   MOCK_FIRST_TOKEN_DELAY   (s, 模拟 LLM 首字节时延)
  --per-token-delay     MOCK_PER_TOKEN_DELAY     (s, 模拟 token 生成节奏)
  --tokens              MOCK_TOKENS              (流式 chunk 数 / 非流式总长)
  --port                MOCK_LLM_PORT
"""

import argparse
import asyncio
import json
import os
import time
import uuid
from typing import Any, Dict, List, Optional

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse


# 单 token "内容"——固定 1 字符是为了让 latency 完全由 sleep 决定，
# 避免不同长度 token 的 JSON 序列化开销污染基线。
_TOKEN_CHAR = "a"


def _make_chat_chunk(
    completion_id: str,
    model: str,
    *,
    role: Optional[str] = None,
    content: Optional[str] = None,
    finish_reason: Optional[str] = None,
) -> Dict[str, Any]:
    delta: Dict[str, Any] = {}
    if role is not None:
        delta["role"] = role
    if content is not None:
        delta["content"] = content
    return {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }


def _make_full_completion(
    completion_id: str, model: str, content: str, prompt_tokens: int, completion_tokens: int
) -> Dict[str, Any]:
    return {
        "id": completion_id,
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


def _approx_prompt_tokens(messages: List[Dict[str, Any]]) -> int:
    # 不需要精准——usage.prompt_tokens 只为日志/监控好看；用字符数除以 4 估算。
    total_chars = 0
    for m in messages:
        c = m.get("content")
        if isinstance(c, str):
            total_chars += len(c)
    return max(1, total_chars // 4)


def create_app(first_token_delay: float, per_token_delay: float, tokens: int) -> FastAPI:
    # tokens=0 没有压测意义，且会让 stream/non-stream 两条路径在内容语义上分叉
    # （流式仍发首字节，非流式返回空串），把它当作显式错误更干净。
    if tokens < 1:
        raise ValueError(f"tokens must be >= 1, got {tokens}")
    app = FastAPI(title="hugegraph-llm mock LLM server")

    @app.get("/v1/models")
    async def list_models() -> JSONResponse:
        # 个别 client 启动时会探测 /v1/models；返回最小可用结构。
        return JSONResponse(
            {
                "object": "list",
                "data": [
                    {"id": "mock-llm", "object": "model", "owned_by": "mock"},
                ],
            }
        )

    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request):
        body = await request.json()
        stream = bool(body.get("stream", False))
        model = body.get("model", "mock-llm")
        messages = body.get("messages", []) or []
        completion_id = f"chatcmpl-{uuid.uuid4().hex}"

        if not stream:
            # 与流式路径对齐：流式最后一个 token 在 first + per * (tokens - 1) 处发出，
            # 非流式按相同总时长 sleep，避免给 sync 基线人为多算一个 token 周期。
            await asyncio.sleep(first_token_delay + per_token_delay * (tokens - 1))
            content = _TOKEN_CHAR * tokens
            return JSONResponse(
                _make_full_completion(
                    completion_id,
                    model,
                    content,
                    prompt_tokens=_approx_prompt_tokens(messages),
                    completion_tokens=tokens,
                )
            )

        async def event_stream():
            await asyncio.sleep(first_token_delay)
            # 首块带 role
            first = _make_chat_chunk(completion_id, model, role="assistant", content=_TOKEN_CHAR)
            yield f"data: {json.dumps(first, ensure_ascii=False)}\n\n"
            # 中间 token-1 个 delta（首块已发了 1 个）
            for _ in range(max(0, tokens - 1)):
                await asyncio.sleep(per_token_delay)
                chunk = _make_chat_chunk(completion_id, model, content=_TOKEN_CHAR)
                yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
            # 结束块
            final = _make_chat_chunk(completion_id, model, finish_reason="stop")
            yield f"data: {json.dumps(final, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
        )

    @app.get("/healthz")
    async def healthz() -> JSONResponse:
        return JSONResponse(
            {"ok": True, "first_token_delay": first_token_delay, "per_token_delay": per_token_delay, "tokens": tokens}
        )

    return app


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Deterministic mock LLM server for hugegraph-llm load tests")
    p.add_argument("--host", default=os.getenv("MOCK_LLM_HOST", "127.0.0.1"))
    p.add_argument("--port", type=int, default=int(os.getenv("MOCK_LLM_PORT", "9999")))
    p.add_argument(
        "--first-token-delay",
        type=float,
        default=float(os.getenv("MOCK_FIRST_TOKEN_DELAY", "0.2")),
        help="seconds before first SSE chunk (mocks LLM TTFT)",
    )
    p.add_argument(
        "--per-token-delay",
        type=float,
        default=float(os.getenv("MOCK_PER_TOKEN_DELAY", "0.02")),
        help="seconds between subsequent SSE chunks",
    )
    p.add_argument(
        "--tokens",
        type=int,
        default=int(os.getenv("MOCK_TOKENS", "100")),
        help="number of tokens (chunks) per response",
    )
    args = p.parse_args()
    if args.tokens < 1:
        p.error("--tokens must be >= 1 (0-token responses have no benchmark meaning)")
    if args.first_token_delay < 0 or args.per_token_delay < 0:
        p.error("--first-token-delay and --per-token-delay must be >= 0")
    return args


def main() -> None:
    args = _parse_args()
    app = create_app(args.first_token_delay, args.per_token_delay, args.tokens)
    # log_level=warning 减少 access log 对本地终端的污染；压测细节看 probe 输出
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
