# RAG HTTP API 异步迁移指南（Phase 3）

> Phase 3 把 `hugegraph-llm` 的 HTTP API 路由从 `def` 升级为 `async def`，事件循环不再被单个 `pipeline.run()` 独占。本文给调用方介绍协议差异、SSE 客户端示例、回滚开关与已知限制。配套设计参见 [`spec/async_streaming_api/design.md`](../../spec/async_streaming_api/design.md)、`tasks.md`。

## 1. 调用方需要注意的协议差异

| 接口 | 协议变化 | 兼容性 |
|---|---|---|
| `POST /rag` | 请求/响应体 byte-for-byte 不变；状态码、字段、报错语义完全等价 | **完全兼容**，无需改客户端 |
| `POST /rag/graph` | 同上 | **完全兼容** |
| `POST /text2gremlin` | 同上 | **完全兼容** |
| `POST /rag/stream` | 新增 SSE 端点，OpenAI ChatCompletionChunk 协议 | **新功能**，老客户端不受影响 |
| `POST /config/*` | 不变 | **完全兼容** |
| 响应 header | 新增 `X-Trace-Id`（HTTP）和 `X-Trace-Id` / `X-Accel-Buffering: no` / `Cache-Control: no-cache`（SSE） | 新 header 可忽略 |
| Header `X-Trace-Id` (request) | 客户端可主动传入，会在响应中回显并贯穿日志 | 可选 |

调用方代码无需任何变更即可享受 Phase 3 的非阻塞 IO 收益。

## 2. SSE 客户端示例

### 2.1 curl

```bash
curl -N -X POST http://localhost:8001/rag/stream \
  -H "Content-Type: application/json" \
  -d '{
    "query": "What is HugeGraph?",
    "raw_answer": true,
    "vector_only": false,
    "graph_only": false,
    "graph_vector_answer": false
  }'
```

`-N` 关闭 curl 自身的输出缓冲；服务端会下发 `data: {...ChatCompletionChunk...}\n\n`，最后一行为 `data: [DONE]\n\n`。

### 2.2 JavaScript / 浏览器

```js
const resp = await fetch("/rag/stream", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ query: "Hello?", raw_answer: true }),
});
const reader = resp.body.getReader();
const decoder = new TextDecoder("utf-8");
let buf = "";
while (true) {
  const { value, done } = await reader.read();
  if (done) break;
  buf += decoder.decode(value, { stream: true });
  for (const block of buf.split("\n\n").slice(0, -1)) {
    const line = block.split("\n").find((l) => l.startsWith("data: "));
    if (!line) continue;
    const data = line.slice(6);
    if (data === "[DONE]") return;
    const chunk = JSON.parse(data); // OpenAI ChatCompletionChunk
    const delta = chunk.choices[0].delta.content || "";
    process.stdout.write(delta);
  }
  buf = buf.slice(buf.lastIndexOf("\n\n") + 2);
}
```

注意：浏览器原生 `EventSource` 仅支持 `GET`，因此用 `fetch` + `ReadableStream` 手动解析 SSE。

### 2.3 Python

```python
import json
import httpx

with httpx.stream(
    "POST",
    "http://localhost:8001/rag/stream",
    json={"query": "Hello?", "raw_answer": True},
    timeout=httpx.Timeout(connect=5.0, read=120.0),
) as resp:
    for line in resp.iter_lines():
        if not line.startswith("data: "):
            continue
        body = line[6:]
        if body == "[DONE]":
            break
        chunk = json.loads(body)
        delta = chunk["choices"][0]["delta"].get("content", "")
        print(delta, end="", flush=True)
```

错误以 `event: error\ndata: {...trace_id...}\n\n` 行下发，客户端解析时识别 `event:` 前缀即可区分。

## 3. 性能对比

参考 Phase 2 的 [async_load_probe.py](../../scripts/async_load_probe.py) 远端基线（200 req / 32 并发，2026-05-28）：

| 指标 | 同步基线 (Phase 2 前) | Phase 3 |
|---|---|---|
| RPS（32 并发） | 1×（基线） | ~2× 起步（具体以远端压测为准） |
| 单 tick 阻塞 P99 | 主流程独占 loop | 6.06 ms（≪ 50 ms 门禁） |
| latency P99 | 受序列化影响显著 | 4166 ms（200 req / 32 并发） |
| 失败率 | — | 0 / 200 |

实际收益取决于 LLM 后端吞吐和并发度。建议上线后用同一压测脚本采集本地基线，对比 Phase 2/3。

## 4. 回滚开关与预案

### 4.1 一键回滚到 Phase 2 同步路由

设置环境变量后重启服务：

```bash
export HUGEGRAPH_LLM_ASYNC_ROUTES_ENABLED=0   # 或 false / no / off
```

| 路由 | flag=1（默认） | flag=0 |
|---|---|---|
| `POST /rag` | `async def` + `asyncio.to_thread` | 旧 `def` 同步处理 |
| `POST /rag/graph` | `async def` + `asyncio.to_thread` | 旧 `def` |
| `POST /text2gremlin` | `async def` + `asyncio.to_thread` | 旧 `def` |
| `POST /rag/stream` | **始终** async（无 sync 实现可回退） | 同 |
| `POST /config/*` | 始终 `def`（轻量元数据写入，不需要 async 化） | 同 |

回滚不影响响应协议；调用方代码无需改动。

### 4.2 完全回滚到 Phase 1（仅 `/rag/stream`）

如果遇到 Phase 2 的检索/重排 httpx 链路问题，需要回到 Phase 1 状态：

1. 在 `pyproject.toml` 锁定 Phase 2 之前的依赖版本；
2. 通过 git revert 撤回 Phase 2 PR；
3. 设置 `HUGEGRAPH_LLM_ASYNC_ROUTES_ENABLED=0` 让路由保持同步形态。

## 5. 已知限制 / FAQ

**Q: pipeline 内部仍是同步 node/operator？**
A: 是的，本设计选 [方案 A](../../spec/async_streaming_api/design.md#42-为什么选方案-a-而不是方案-b)，即"API async boundary + 非阻塞 pipeline 调度 + 局部 async IO"。`pipeline.run()` 走 `asyncio.to_thread` 推到默认线程池，事件循环不被独占；node/operator 的 async 化属于后续优化项。

**Q: 为什么不改 `pyhugegraph` / `pycgraph`？**
A: `pyhugegraph` 是独立子项目，多团队共用；`pycgraph` 是 C++ 扩展。两者改 async 工作量与协调成本高于本期收益，统一通过 `asyncio.to_thread` 边界化。详见 design.md §4.3 / §4.4。

**Q: `asyncio.to_thread` 会不会成为吞吐瓶颈？**
A: 默认线程池容量随 CPU 核数缩放（FastAPI/Uvicorn 默认 40），Phase 2 远端 32 并发压测下未观察到瓶颈。若出现，可在 lifespan 中 `loop.set_default_executor(ThreadPoolExecutor(max_workers=...))` 或后续单独建专用 executor。

**Q: Gradio Demo 受影响吗？**
A: 不受影响。Gradio 仍调用同步 `Scheduler.schedule_flow` → `pipeline.run()` 链路，与 HTTP async 路径并行存在，互不干扰。

**Q: trace_id 怎么用？**
A: 客户端可在请求 header 传入 `X-Trace-Id: <hex>`，服务端会保留并回显在响应 header 与日志里；不传则服务端自动生成。SSE 错误事件的 payload 中也会带 `trace_id`，便于跨端排查。

**Q: 中间件会不会消费 SSE 流？**
A: 不会。`UseTimeMiddleware` 用 `BaseHTTPMiddleware`，对 `StreamingResponse` 透传不读 body；trace_id 用 `contextvars.ContextVar` 传递，不会污染异步上下文。

## 6. 参考

- 设计文档：[spec/async_streaming_api/design.md](../../spec/async_streaming_api/design.md)
- 任务清单：[spec/async_streaming_api/tasks.md](../../spec/async_streaming_api/tasks.md)
- pycgraph spike：[spec/async_streaming_api/pycgraph_async_spike.md](../../spec/async_streaming_api/pycgraph_async_spike.md)
- 阻塞调用审计：[spec/async_streaming_api/blocking_call_audit.md](../../spec/async_streaming_api/blocking_call_audit.md)
- 压测脚本：[scripts/async_load_probe.py](../../scripts/async_load_probe.py)
