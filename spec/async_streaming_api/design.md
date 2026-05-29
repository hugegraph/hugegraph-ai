# API 异步与流式输出改造 - 设计文档

> 配套文档：[requirements.md](./requirements.md) | [tasks.md](./tasks.md)

## 概述

本设计旨在让 hugegraph-llm 的 HTTP API 层从"全同步阻塞"演进为"API async boundary + SSE 流式输出"，采用方案 A（`FastAPI async route -> 非阻塞 pipeline 调度 -> pipeline 内部仍是同步 node/operator`），避免 event loop 被单请求独占，同时复用底层已就绪的 `agenerate_streaming` 能力。pipeline 异步调度统一采用 `await asyncio.to_thread(pipeline.run)`（P1-T0 spike 已确认 pycgraph 3.2.4 的 `asyncRun()` 不是 Python awaitable，方案 a 不可达），详见 §3.2 与 [pycgraph_async_spike.md](./pycgraph_async_spike.md)。改造涉及 HTTP 路由、IO 客户端、Pipeline 调度边界、retry 机制、测试基础设施五个层面，按 Phase 1 → Phase 2 → Phase 3 渐进推进，避免一次性改动引发"伪异步"退化。

### 设计原则

- **渐进式 async 化**：先暴露已有能力（Phase 1），再消除阻塞 IO（Phase 2），最后处理边界硬骨头（Phase 3）。
- **不破坏向后兼容**：原同步接口完全保留，新增 `/stream` 后缀路由暴露流式能力。
- **边界化阻塞调用**：对**没有原生异步接口**的第三方同步 SDK（pyhugegraph 冷路径、`pipeline.run()` 等）通过 `asyncio.to_thread` 推到线程池，事件循环不被独占。pycgraph 上游若未来提供真正 Python awaitable 的 `asyncRun()`，可平滑切换到直接 `await`，但 P1-T0 spike 已确认当前 3.2.4 上不可行。
- **lint 防御伪异步**：通过工具链强制约束，防止后续维护中在 async 函数里偷懒调 `requests`。

### 技术栈选型

| 层 | 选型 | 理由 |
|---|---|---|
| Web 框架 | FastAPI（已有） | 原生 async 支持，已在用 |
| 流式协议 | SSE (`text/event-stream`) | FastAPI `StreamingResponse` 原生支持，与 OpenAI streaming 协议语义一致，前端 EventSource 可直接消费 |
| HTTP 客户端 | `httpx.AsyncClient` | FastAPI 生态默认搭档，API 与 `requests` 接近，迁移成本低 |
| 异步 retry | `tenacity` async 用法 | 已在 OpenAI/LiteLLM 使用，统一即可 |
| 测试 | `pytest-asyncio` + `httpx.AsyncClient` (TestClient async 模式) | 标配 |
| Pipeline 异步执行 | `await asyncio.to_thread(pipeline.run)` | P1-T0 spike 已确认 pycgraph 3.2.4 的 `asyncRun()` 返回 `StdFutureCStatus` 非 awaitable，且 `wait()`/`get()` 阻塞不释放 GIL；唯一可用的非阻塞接入方式 |
| 第三方同步 SDK 边界 | `asyncio.to_thread`（Python 3.9+） | 用于无原生异步接口的同步 SDK（如 pyhugegraph 冷路径、`pipeline.run()`），标准库无新依赖 |

## 模块分层与改造影响面

```text
hugegraph-llm/src/hugegraph_llm/
├── api/                              # [Phase 1+3] 路由层
│   ├── rag_api.py                    # 新增 stream 路由 / 改 async def
│   ├── admin_api.py                  # 已部分 async,补齐
│   └── middleware/                   # 兼容 async + StreamingResponse
├── flows/                            # [Phase 1] 全量审视 + scheduler 修正
│   ├── scheduler.py                  # schedule_stream_flow 修正(pipeline.run 阻塞)
│   ├── rag_flow_raw.py               # 审视 post_deal/post_deal_stream 内是否含同步 IO
│   ├── rag_flow_vector_only.py       # 同上
│   ├── rag_flow_graph_only.py        # 同上
│   ├── rag_flow_graph_vector.py      # 同上
│   ├── text2gremlin.py               # 同上
│   └── common.py                     # BaseFlow 基类,确认 stream 接口签名
├── operators/
│   ├── llm_op/answer_synthesize.py   # [Phase 1] 删除嵌套 asyncio.run
│   ├── common_op/merge_dedup_rerank.py  # [Phase 2] requests → httpx
│   └── hugegraph_op/                 # [Phase 2] requests → httpx
├── models/
│   ├── llms/ollama.py                # [Phase 2] retry → tenacity async
│   └── rerankers/                    # [Phase 2] requests → httpx
├── utils/
│   └── hugegraph_utils.py            # [Phase 2] requests → httpx
├── adapters/                         # [Phase 2 新增]
│   └── async_hugegraph_adapter.py    # 绕开 pyhugegraph 同步客户端的 async 适配
├── demo/
│   └── rag_demo/configs_block.py     # [豁免] UI 配置块,非 RAG 请求路径,允许保留 requests
└── config/
    └── async_config.py               # [Phase 2 新增] 线程池/连接池配置
```

**请求路径边界定义**：本设计中"请求路径"指 `POST /rag*`、`POST /text2gremlin*` 等 HTTP 路由处理函数被调用后、直至响应返回客户端之间所触达的所有代码。以下不属于请求路径，允许保留同步 IO：

- 启动期一次性调用（如 `config/huge_config.py:49` 的健康检查）
- Gradio UI 配置块（`demo/rag_demo/configs_block.py`）
- CLI / 离线脚本入口

## 1. Phase 1：HTTP 暴露已有的流式能力

### 1.1 新增路由设计

在 `api/rag_api.py` 中新增 `/rag/stream`，与原 `/rag` 并存：

```python
# api/rag_api.py（新增，原同步路由保持不变）
from fastapi.responses import StreamingResponse
from hugegraph_llm.demo.rag_demo.rag_block import rag_answer_streaming
import json

@router.post("/rag/stream")
async def rag_answer_stream_api(req: RAGRequest, request: Request):
    async def event_generator():
        try:
            # rag_answer_streaming 必须 yield (answer_type, token_delta) 元组，
            # 不再 yield 累计 context dict。adapter 负责包成 ChatCompletionChunk。
            first_chunks_emitted: set[int] = set()
            async for answer_type, token_delta in rag_answer_streaming(...):
                if await request.is_disconnected():
                    break
                index = ANSWER_TYPE_TO_INDEX[answer_type]
                include_role = index not in first_chunks_emitted
                first_chunks_emitted.add(index)
                chunk = to_chat_completion_stream_chunk(
                    token=token_delta, index=index, role="assistant" if include_role else None,
                )
                yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
            # 结束 chunk：每个用过的 index 都发一个 finish_reason=stop
            for index in first_chunks_emitted:
                final = to_chat_completion_stream_chunk(token=None, index=index, finish_reason="stop")
                yield f"data: {json.dumps(final, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
        except asyncio.CancelledError:
            log.info("client cancelled streaming, trace_id=%s", trace_id)
            raise
        except Exception as e:
            log.exception("streaming error")
            err_payload = json.dumps({"error": str(e), "trace_id": trace_id})
            yield f"event: error\ndata: {err_payload}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )
```

**adapter 函数签名**（位置建议：`api/chat_completion_adapter.py` 或 `api/sse_helpers.py`）：

```python
def to_chat_completion_stream_chunk(
    token: Optional[str],
    index: int,
    role: Optional[str] = None,        # 仅首 chunk 传 "assistant"
    finish_reason: Optional[str] = None,  # 仅结束 chunk 传 "stop"
    completion_id: Optional[str] = None,  # 同一次响应内所有 chunk 共用
) -> Dict[str, Any]:
    delta: Dict[str, Any] = {}
    if role is not None:
        delta["role"] = role
    if token:
        delta["content"] = token
    return {
        "id": completion_id or _gen_completion_id(),
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "choices": [{"index": index, "delta": delta, "finish_reason": finish_reason}],
    }
```

**禁止**实现：在 adapter 里读取上一轮累计文本、用字符串差分反推 delta。delta 必须由 `async_streaming_generate` 在 token 产生时直接传出。

**关键点**：

- `request.is_disconnected()` 在每次 yield 前检查，客户端断开后 SSE generator 停止写入。但需注意：`schedule_stream_flow()` 先执行 pipeline，再开始 `post_deal_stream()`；写法采用 `await asyncio.to_thread(pipeline.run)`（P1-T0 spike 选定的方案 b），事件循环不会被独占，但 pipeline 内部已发起的同步阻塞 IO（pyhugegraph 请求等）仍可能等待超时或自然返回。`AnswerSynthesize.async_streaming_generate()` 创建了 `anext(gen)` task 但没有 `finally` 去取消 pending task，SSE generator 被关闭时底层 LLM streaming task 可能清理不完整。需在 `finally` 中 cancel task、await gather、必要时 `aclose()`。
- **多 generator 完成态管理**：`async_streaming_generate()` 同时跑多个 answer 的 streaming（raw / vector_only / graph_only / graph_vector），每个 answer 对应一个 generator 与一个 pending task。某个 generator `StopAsyncIteration` 后**必须立即从 active task set 移除**，不能再回填到 `asyncio.wait()` 的入参里——否则已完成的 task 会被反复传给 `wait()` 导致 busy loop（CPU 飙升）；同时若用 `len(async_tasks)` 与 `stop_task_num` 比对结束条件，已完成 task 没移除会让结束判定永远不达成或提前误判。建议改为以 `dict[task -> task_id]` 维护活跃 task 集合，命中 `StopAsyncIteration` 时 `del`，并以"集合非空"作为循环条件。
- `X-Accel-Buffering: no` 禁止 nginx 缓冲，否则流式会被攒成一坨
- 错误用 `event: error` SSE 事件下发，不能靠 HTTP 5xx（首字节后 status code 已发出）
- `[DONE]` 哨兵与 OpenAI 协议保持一致

### 1.2 Scheduler 流式路径修正（已落地）

当前 `flows/scheduler.py` 的 `schedule_stream_flow`（函数签名在 L143）是 `async def`，但内部在 L158 与 L172 两处直接调用同步 `pipeline.run()`，等于"同步跑完才开始 stream"。P1-T3 已落地修正：

```python
async def schedule_stream_flow(self, ...):
    ...
    status = await asyncio.to_thread(pipeline.run)   # P1-T0 spike 选定的方案 b
    if status.isErr():
        ...
    async for chunk in flow.post_deal_stream(pipeline):
        yield chunk
```

**注意**：

- scheduler 中 `schedule_flow`（同步路径，L120/L133）保留 `pipeline.run()` 同步调用不变——它由 Gradio 同步入口调用，本身是 `def`，无需 async 化。
- `asyncio.to_thread(pipeline.run)` 是当前 pycgraph 上唯一可用的非阻塞接入方式（spike 已确认 `asyncRun()` 不是 awaitable 且 `wait()`/`get()` 阻塞）；**不要**给它加 lint 禁用规则。
- P1-T3 修复同时随手补上"`manager.fetch() is None` 分支漏 `return` + `manager.add` 未在 finally"的既有 bug，否则首次请求会让 pipeline 跑两遍、LLM token 流被复发两遍。

### 1.3 嵌套事件循环消除

`operators/llm_op/answer_synthesize.py:73` 处当前写法：

```python
# 现状（错误模式）
def run(self, ...):
    return asyncio.run(self.async_generate(...))  # 在 async 上下文里会 RuntimeError
```

改造为同步与异步入口分离：

```python
# 改造后
def run(self, ...):
    # 同步入口：仅供同步路径调用（如旧 /rag）
    return asyncio.run(self.async_generate(...))

async def run_async(self, ...):
    # 异步入口：供 async 路径直接 await
    return await self.async_generate(...)
```

调用方按上下文选择 `run` 或 `run_async`，禁止在 async 路径上调用 `run`。

### 1.4 流式源头改造：yield delta 而非累计 context

当前 `operators/llm_op/answer_synthesize.py` 的 `async_streaming_generate()`（L207-L280）写法：

```python
# 现状：累计快照
context[target_key] = context.get(target_key, "") + token
yield context  # 反复 yield 整个 context dict
```

直接喂给 SSE 会输出累计全文，不符合需求 1.4 的 OpenAI delta 语义。改造为按 token yield delta：

```python
# 改造后：源头按 token 流出 delta，活跃 task 用 dict 维护，已完成的立即移除
async def async_streaming_generate(...) -> AsyncGenerator[Tuple[str, str], None]:
    # ...构建 async_generators 不变...

    # active: 活跃 task -> task_id；StopAsyncIteration 后立即从 active 中删除，
    # 不再回填到 asyncio.wait()，避免已完成 task 反复被 wait 返回造成 busy loop。
    active: Dict[asyncio.Task, int] = {
        asyncio.create_task(anext(gen)): tid
        for tid, gen in enumerate(async_generators)
    }
    try:
        while active:
            done, _ = await asyncio.wait(
                list(active.keys()), return_when=asyncio.FIRST_COMPLETED,
            )
            for task in done:
                tid = active.pop(task)  # 先移除，无论是否抛 StopAsyncIteration
                try:
                    task_id, target_key, token = task.result()
                except StopAsyncIteration:
                    # 该 generator 结束：不再 schedule 下一个 anext，active 收缩
                    continue
                yield target_key, token  # ← 直接 yield delta
                next_task = asyncio.create_task(anext(async_generators[tid]))
                active[next_task] = tid
    finally:
        # 配合需求 1.3 的取消语义：客户端断开 / 异常退出时必须释放上游 LLM streaming 资源
        for t in list(active.keys()):
            if not t.done():
                t.cancel()
        await asyncio.gather(*active.keys(), return_exceptions=True)
        for gen in async_generators:
            try:
                await gen.aclose()
            except Exception:  # noqa: BLE001
                pass
```

**关键约束**：

- `target_key`（如 `"raw_answer"`、`"vector_only_answer"`）由 adapter 映射到 `choices[].index`，映射表在 API 层定义并固化（如 `ANSWER_TYPE_TO_INDEX = {"raw_answer": 0, "vector_only_answer": 1, ...}`）
- **活跃 task 集合管理**：必须用 `dict[Task, task_id]` 维护活跃 task。任意 task 完成（含 `StopAsyncIteration`）后立即 `pop`，再决定是否 schedule 下一个 `anext`。**禁止**保留"已完成但还在原位"的 task 再传给 `asyncio.wait()`——它会立刻返回，造成 busy loop（CPU 100%）；也禁止用 `len(stop_count) == len(async_tasks)` 这种全量比对作为结束条件，应以"活跃集合非空"为循环条件。
- 如需保留同步路径（Gradio）"反复 yield 整个 context"的旧行为，由 Gradio 适配层在外侧自行累加，不污染 operator 源头
- 若 Gradio demo 当前依赖累计 context，新增一个轻量 wrapper（如 `async_streaming_generate_legacy()` 或 `accumulate(stream)` 适配函数）维持旧形态，其与新 delta 流共享同一份 token 源

### 1.5 Phase 1 验收

- 仅新增 `/rag/stream` **一个** SSE 路由（采用 OpenAI ChatCompletionChunk 协议）。`/rag/graph/stream`、`/text2gremlin/stream` 均推迟到 Phase 2 单独设计——`/rag/graph` 走 graph recall 不产生 token delta、`Text2GremlinFlow` 无 `AnswerSynthesizeNode` 不写 `stream_generator`，两者都需要独立的 SSE 事件协议，**不能**套 ChatCompletionChunk（详见需求 1.2）
- 原同步路由响应结构 byte-for-byte 一致
- `schedule_stream_flow` 内部不再独占事件循环
- 客户端断开能在 1 秒内停止上游 LLM 调用

## 2. Phase 2：检索/重排路径换 httpx + async

### 2.1 httpx 客户端生命周期

引入应用级共享 `AsyncClient`，避免每次请求新建连接：

```python
# api/lifespan.py 或 demo/rag_demo/app.py 的 lifespan
from contextlib import asynccontextmanager
import httpx

@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(connect=5.0, read=60.0, write=10.0, pool=2.0),
        limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
    )
    yield
    await app.state.http_client.aclose()
```

通过 FastAPI 依赖注入或全局单例提供给下游模块。

### 2.2 替换映射表

| 文件 | 现状 | 改造后 |
|---|---|---|
| `utils/hugegraph_utils.py:23` | `requests.get(...)` | `await client.get(...)` |
| `models/rerankers/cohere.py` | `requests.post(...)` | `await client.post(...)` |
| `models/rerankers/siliconflow.py` | 同上 | 同上 |
| `operators/common_op/merge_dedup_rerank.py:22` | 同上 | 同上 |
| `operators/hugegraph_op/schema_manager.py` | 同上 | 同上 |
| `config/huge_config.py:49` | 启动时 `requests.get(timeout=0.5)` | 启动期保留同步；请求路径上的健康检查改 async |

### 2.3 AsyncHugeGraphAdapter 设计（统一 `asyncio.to_thread` 包装）

`pyhugegraph` 整套基于 `requests.Session`，强行改造影响 `hugegraph-python-client` 子项目所有下游。本次在 hugegraph-llm 内部新增适配层；**Phase 2 不写 httpx 直连 HugeGraph REST 的客户端**——重写一层 PyHugeClient 抽象工作量超出 Phase 2 单期能消化的程度，且与 P1-T0 spike 选定的方案 b（pipeline.run 走 to_thread）同源，事件循环不被独占已经够用。httpx 直连 HugeGraph REST 推迟到后续优化项。

```python
# adapters/async_hugegraph_adapter.py
class AsyncHugeGraphAdapter:
    """
    统一 asyncio.to_thread 包装 PyHugeClient 的同步调用边界化。
    所有方法都走 await asyncio.to_thread(...)，事件循环不被独占。
    """
    def __init__(self, client_factory):
        # client_factory: () -> PyHugeClient（lazy 构造，避免 __init__ 触发 IO）
        self._factory = client_factory
        self._client: PyHugeClient | None = None

    async def _get_client(self) -> PyHugeClient:
        if self._client is None:
            # 首次访问才建连接，且推到线程池（PyHugeClient.__init__ 内部可能有 IO）
            self._client = await asyncio.to_thread(self._factory)
        return self._client

    async def execute_gremlin(self, query: str) -> dict:
        client = await self._get_client()
        return await asyncio.to_thread(client.gremlin().exec, query)

    async def get_schema(self) -> dict:
        client = await self._get_client()
        return await asyncio.to_thread(client.schema.getSchema)

    async def query_vid(self, vid: str) -> dict:
        client = await self._get_client()
        return await asyncio.to_thread(client.graph().get_vertex_by_id, vid)

    async def query_neighbors(self, vid: str, **kwargs) -> dict:
        client = await self._get_client()
        return await asyncio.to_thread(
            client.gremlin().exec,
            f"g.V('{vid}').both()",  # 示例
        )
```

**覆盖范围**：Phase 2 内替换 ~15 个产线 callsite（含 `graph_query_node.py` 主路径 5 处），全部走 adapter 的 `to_thread` 包装。`schema_manager.py:28-34` 在 `__init__` 里隐式建 PyHugeClient 连接的现状必须解耦——构造期仅保存配置，首次方法调用时才走 `to_thread` 建连接，否则 await 链断在很尴尬的位置。

**前置设计任务**：在实现 adapter 前需对照 `pyhugegraph` router 和 HugeGraph graphspace 行为确认 REST 路径，并定义共享 `httpx.AsyncClient` 如何从 FastAPI lifespan 注入到 scheduler/flow/node/operator。否则可能写出无法被真实请求路径使用，或者 REST endpoint 不正确的 adapter。

### 2.4 retry 统一为 tenacity async

`models/llms/ollama.py:23` 的 `from retry import retry` 是阻塞 sleep，套在 async 函数上会卡事件循环。改造：

```python
# models/llms/ollama.py
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type((httpx.HTTPError, ollama.ResponseError)),
)
async def agenerate(self, ...):
    ...
```

`tenacity` 自动识别 async 函数并使用 `asyncio.sleep`，不阻塞事件循环。

### 2.5 配置项

新增 `config/async_config.py`：

```python
@dataclass
class AsyncConfig:
    http_max_connections: int = 100
    http_max_keepalive: int = 20
    http_connect_timeout: float = 5.0
    http_read_timeout: float = 60.0
    # 注：pipeline 异步调度采用 await asyncio.to_thread(pipeline.run)（P1-T0 spike 选定方案 b）；
    # 如需对 default executor 容量做约束，可在 lifespan 中调 loop.set_default_executor(...)
    # 或在此处补 pipeline_thread_pool_size 字段（Phase 2 压测 P99 不达标时再加）。
```

### 2.6 lint 防御伪异步

grep 在「async 函数嵌套定义」「跨文件 helper 间接调 requests」「类方法继承链」等场景会漏检，因此采用 **AST 检查** 作为主防线，grep 仅作为兜底。

**主方案：基于 `ast` 的自定义检查脚本**

```python
# scripts/lint_async_no_requests.py
"""
扫描所有 async def 函数体（含嵌套作用域），禁止出现：
  - 直接调用 requests.* 模块函数
  - 调用以 requests.Session/get/post 等为基础的同步 IO

豁免清单（白名单）：
  - hugegraph_llm/demo/rag_demo/configs_block.py    # Gradio UI 配置块,非请求路径
  - hugegraph_llm/config/huge_config.py             # 启动期一次性调用
"""
import ast, sys
from pathlib import Path

EXEMPT = {
    "hugegraph-llm/src/hugegraph_llm/demo/rag_demo/configs_block.py",
    "hugegraph-llm/src/hugegraph_llm/config/huge_config.py",
}

class AsyncRequestsChecker(ast.NodeVisitor):
    def __init__(self, file): self.file, self.errs, self.depth = file, [], 0
    def visit_AsyncFunctionDef(self, node):
        self.depth += 1
        self.generic_visit(node)
        self.depth -= 1
    def visit_Call(self, node):
        if self.depth > 0:
            # requests.xxx(...) 或 requests.Session().xxx
            target = node.func
            while isinstance(target, ast.Attribute): target = target.value
            if isinstance(target, ast.Name) and target.id == "requests":
                self.errs.append((node.lineno, ast.unparse(node.func)))
        self.generic_visit(node)

def check(path: Path) -> int:
    if any(str(path).replace("\\", "/").endswith(e) for e in EXEMPT): return 0
    tree = ast.parse(path.read_text(encoding="utf-8"))
    chk = AsyncRequestsChecker(str(path)); chk.visit(tree)
    for ln, call in chk.errs:
        print(f"{path}:{ln}: async 函数内禁止调用 {call}")
    return len(chk.errs)

if __name__ == "__main__":
    root = Path("hugegraph-llm/src/hugegraph_llm")
    n = sum(check(p) for p in root.rglob("*.py"))
    sys.exit(1 if n else 0)
```

**接入 CI**：在 `pyproject.toml` 或现有 lint 流程中追加：

```bash
python scripts/lint_async_no_requests.py
```

**兜底方案：grep**（用于本地快速自检，不替代 AST 检查）

```bash
# 仅作为辅助参考,容易漏报
grep -rn -B2 "requests\." hugegraph-llm/src/hugegraph_llm/ \
  --include="*.py" | grep -B2 "async def"
```

**第二类审计清单**：AST 脚本只能作为 direct-call guard，不能作为请求路径非阻塞的证明。还需增加以下间接同步调用的审计清单，每条 async 请求路径都必须证明这些调用要么有 async 实现，要么走 bounded executor fallback：

- `PyHugeClient` / `gremlin().exec()` / `schema.getSchema()`
- 同步 LLM `generate()`
- 同步 reranker 方法
- `pipeline.run()`

### 2.7 测试基础设施

`pyproject.toml` 显式声明：

```toml
[project.optional-dependencies]
dev = [
    "pytest~=8.0",
    "pytest-asyncio>=0.23",
    "httpx>=0.27",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
```

注意：`fastapi`、`uvicorn`、`httpx` 应作为直接依赖声明在 `dependencies` 中，不能仅靠 Gradio 传递引入，避免运行和测试依赖 Gradio 的传递依赖集合。

补 async 路由测试：

```python
# tests/api/test_rag_stream_api.py
import pytest
from httpx import AsyncClient, ASGITransport

@pytest.mark.asyncio
async def test_rag_stream_basic(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        async with client.stream("POST", "/rag/stream", json={...}) as resp:
            chunks = []
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    chunks.append(line[6:])
            assert chunks[-1] == "[DONE]"
```

### 2.8 Phase 2 验收

- 请求路径上不再出现同步 `requests.*` 调用（lint/grep 验证）
- 32 路并发压测：async 接口 RPS ≥ 同步接口 2 倍
- 单请求时延退化 ≤ 5%
- `pytest-asyncio` 测试矩阵全绿

## 3. Phase 3：HTTP 路由层 async 化 + Gradio 双路径兼容

> **方案 A 约束**：Phase 3 不追求"全链路 async"（方案 B），而是在方案 A 框架下将路由签名改为 `async def`，内部通过 `await asyncio.to_thread(pipeline.run)`（P1-T0 spike 选定方案 b）+ `await` 已替换的 async IO 完成工作。pipeline 内部 node/operator 仍为同步；只有无原生异步接口的第三方 SDK（如 pyhugegraph 冷路径）才走 `asyncio.to_thread` 边界。

### 3.1 路由签名改造

```python
# api/rag_api.py
@router.post("/rag")
async def rag_answer_api(req: RAGRequest):  # def → async def
    # 已替换的 async IO 直接 await；未替换的走 to_thread
    return await rag_answer_async(...)

@router.post("/rag/graph")
async def graph_rag_recall_api(req: GraphRAGRequest):
    ...
```

**前置条件**：Phase 2 必须完成（请求路径上 `requests.*` 已替换为 `httpx`），否则改 `async def` 后内部仍有阻塞 IO 调用，事件循环被独占，性能反而退化。

**注意**：路由改为 `async def` 后，Gradio 的同步路径仍需工作。方案 A 下 Gradio 继续走同步 `schedule_flow` → `pipeline.run()` 调用链，与 HTTP async 路径并行存在，互不影响。需确保：

- `AnswerSynthesize.run()` 保留（Gradio 同步路径仍通过 `AnswerSynthesizeNode.operator_schedule()` → `self.operator.run()` 调用）
- `Scheduler.schedule_flow()` 保留同步版本
- 两套入口（`run`/`run_async`，`schedule_flow`/`schedule_stream_flow`）长期并存

### 3.2 pycgraph 边界处理（已由 P1-T0 spike 选定方案 b）

`pycgraph.GPipeline` 暴露了 `asyncRun()`，但 P1-T0 spike 在 `pycgraph==3.2.4` 上实测：返回 `StdFutureCStatus`，**不是** Python awaitable（`inspect.isawaitable() = False`），直接 `await` 抛 `TypeError`；其 `wait()` 阻塞调用线程不释放 GIL（节点 `time.sleep(0.05)` → `wait()` blocked 50.2ms）。详见 [pycgraph_async_spike.md](./pycgraph_async_spike.md)。

HTTP async 路径**统一采用方案 b**：

```python
async def schedule_flow_async(self, ...):
    pipeline = self._get_pipeline(...)
    result = await asyncio.to_thread(pipeline.run)
    return result
```

Gradio 同步路径继续走 `pipeline.run()`，与 HTTP async 路径互不影响。**不要**给 `asyncio.to_thread(pipeline.run)` 加 lint 禁用规则——这是当前 pycgraph 上唯一可用的非阻塞接入方式。

未来若 pycgraph 上游提供真正 Python awaitable 的 `asyncRun()`，可平滑切换到 `await pipeline.asyncRun()` 并补一条 `assert inspect.isawaitable(pipeline.asyncRun())` 防回退测试；这属于后续优化项，不在当前设计范围内。

### 3.3 中间件兼容

`middleware/middleware.py` 下的日志/trace 中间件需验证：

- 先确认 middleware 已注册到 app（当前未被挂载）
- `BaseHTTPMiddleware.dispatch` 必须是 `async def`（当前已是）
- 对 `StreamingResponse` 的处理不会一次性消费完整响应（否则流式失效）
- trace_id 在 async context 中通过 `contextvars` 传递

### 3.4 Phase 3 验收

- 所有 RAG 路由签名为 `async def`
- 中间件在 sync / async / stream 三种模式下 trace_id 链路完整
- 端到端压测：QPS=1 时延不退化，QPS=32 吞吐≥2x
- Gradio Demo 不受影响（仍走同步 `schedule_flow` 路径）

## 4. 关键设计决策

### 4.1 为什么不一次性改造？

Python async 的"传染性"决定了大型 codebase 改造必须分层。一次性把路由改 `async def` 而 IO 层未替换，会造成"路由声明 async 但内部全是阻塞调用"的伪异步状态——比纯同步还糟（事件循环被一个慢请求独占，其他请求全部排队）。本设计先在 Phase 1 暴露已有能力拿短期收益，Phase 2 解决 IO 阻塞这个核心问题，Phase 3 才动路由签名。

### 4.2 为什么选方案 A 而不是方案 B？

当前文档同时出现过两种思路：

- **方案 A：API async boundary** — `FastAPI async route -> 非阻塞 pipeline 调度（await asyncio.to_thread(pipeline.run)）-> pipeline 内部仍是同步 node/operator`。收益是 event loop 不被单请求独占，但不是全链路 async。
- **方案 B：真正端到端 async** — `FastAPI async route -> async scheduler -> async node/operator contract -> await httpx / LLM / adapter`。需要改 `operator.run`、node 调度和 pipeline contract，改动面明显更大。

结合当前仓库现状：`pycgraph.GPipeline.run()` 是同步扩展，`GraphQueryNode`、`GremlinExecuteNode`、`Text2GremlinNode` 也仍走同步调用。选方案 B 需要补上 node/operator/pipeline contract 的 async 迁移方案，否则 Phase 3 的"路由内部所有 IO 调用改为 await"不可落地。

本设计选择方案 A，目标定位为 `API async boundary + 非阻塞 pipeline 调度 + 局部 async IO`。Gradio 同步路径（`schedule_flow` → `pipeline.run()`）与 HTTP async 路径（`schedule_stream_flow` / `schedule_flow_async` → `await asyncio.to_thread(pipeline.run)`，P1-T0 spike 选定方案 b）长期并存。

### 4.3 为什么不动 pyhugegraph？

`hugegraph-python-client` 是独立子项目，被多个下游使用。强行改造为 async 会污染所有下游，且需要协调多个团队。本次通过适配器模式（`AsyncHugeGraphAdapter`）在 hugegraph-llm 内部解决——Phase 2 统一 `asyncio.to_thread` 包装，与 P1-T0 spike 选定的方案 b 同源，事件循环不被独占。httpx 直连 HugeGraph REST 推迟到后续优化项；等 pyhugegraph 上游有 async 计划时，可平滑切换。

### 4.4 为什么不动 pycgraph？

C++ 扩展改 async 需要重写 binding，工作量巨大且风险高。pycgraph 已暴露 `asyncRun()`，但 P1-T0 spike 在 `pycgraph==3.2.4` 上实测它返回 `StdFutureCStatus`（C++ future），不是 Python awaitable，且 `wait()`/`get()` 阻塞不释放 GIL。本设计采用 `await asyncio.to_thread(pipeline.run)`（详见 §3.2 / 需求 2.4 / [pycgraph_async_spike.md](./pycgraph_async_spike.md)）。该实现在性能上等价于"每个请求消耗一个线程跑 pipeline"，配合连接池和 LLM async 出口，实测吞吐瓶颈通常在 LLM 后端而非 pipeline 调度。等 pycgraph 上游真正 awaitable 化后，可平滑切换到 `await pipeline.asyncRun()`，但属后续优化项。

### 4.5 为什么选 SSE 而不是 WebSocket？

RAG 是单向流（服务端 → 客户端），WebSocket 的双向能力用不上。SSE 协议简单（HTTP/1.1 长连接 + `text/event-stream`），FastAPI/nginx/CDN 全部原生支持，与 OpenAI streaming 协议语义一致，前端 EventSource 一行代码消费。WebSocket 需要额外的协议握手、心跳、重连逻辑，性价比低。

## 5. 性能预估

| 指标 | 同步基线 | Phase 1 (stream only) | Phase 2 (+httpx) | Phase 3 (async routes) |
|---|---|---|---|---|
| TTFT (3000 token output) | ~5s | ~0.5s | ~0.4s | ~0.3s |
| QPS=1 端到端时延 | T | T | T (-2%) | T (-3%) |
| QPS=32 单 worker 吞吐 | 1x | 1x | 1.8x | 2.5x |
| 内存占用 | 1x | 1x | 1.1x（连接池） | 1.1x |

注：以上为预估值，具体以压测为准。

## 6. 回滚方案

每个 Phase 独立可回滚，回滚应通过 feature flag 切回旧的同步实现，而不是在同步路由里用 `asyncio.run` 包 async 内部逻辑（回滚目标应是回到已知稳定同步路径，而不是引入第三种执行模型）：

- Phase 1 回滚：删除 `/stream` 路由，恢复 `schedule_stream_flow` 原状
- Phase 2 回滚：通过 feature flag 切回同步 IO（保留同步实现至少一个版本周期）
- Phase 3 回滚：通过环境变量 `HUGEGRAPH_LLM_ASYNC_ROUTES_ENABLED` 切回同步路由

每个 Phase 完成后跑全量回归测试 + 压测，确认无退化再进入下一 Phase。
