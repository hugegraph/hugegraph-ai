# API 异步与流式输出改造 - 需求文档

> 配套文档：[design.md](./design.md) | [tasks.md](./tasks.md)

## 背景

hugegraph-llm 当前的 HTTP API 层（`hugegraph-llm/src/hugegraph_llm/api/rag_api.py`）全部由同步 `def` 路由组成，调用方必须等待完整 RAG 链路（检索 + 重排 + LLM 生成）执行完毕后才能拿到结果。在涉及多次 LLM 调用、长上下文生成的场景下，首字节延迟（TTFT）与端到端时延都不可接受，且单实例并发吞吐受同步阻塞 IO 拖累。

底层 LLM 客户端（OpenAI / LiteLLM / Ollama）已在 `models/llms/base.py` 强制实现 `agenerate` 与 `agenerate_streaming`，流式中间层 `rag_block.rag_answer_streaming` 已存在并接到 Gradio 前端，但 HTTP API 层未对外暴露这套能力。

## 需求列表

### 1. 流式 HTTP 接口暴露

**核心**：在不破坏现有同步接口的前提下，新增 SSE 流式版本的核心 RAG 接口。

**验收标准**：

1.1. 保留现有 `/rag`、`/rag/graph`、`/text2gremlin` 同步接口，行为与响应结构完全不变（向后兼容）。

1.2. **Phase 1 只新增 `/rag/stream` 一个 SSE 路由**，使用 `text/event-stream` 协议、OpenAI ChatCompletionChunk 语义输出（见 1.4）。`/rag/graph/stream` 与 `/text2gremlin/stream` 均推迟，原因如下，**禁止**在 Phase 1 套同款 ChatCompletionChunk 实现：

   - **`/rag/graph/stream`（推迟到 Phase 2，独立事件协议）**：现有 `/rag/graph` 是 graph recall API，请求体走 `is_graph_rag_recall=True` 路径，flow 跳过 `AnswerSynthesizeNode`，**根本不产生 token delta**，没有 `stream_generator` 可消费。即使把它接进 `rag_stream_generator`，也只能在 pipeline 跑完后一次性返回 `keywords` / `match_vids` / `gremlin` / `graph_result` 等结构化字段，不是真流式。若要做真流式，必须单独定义 SSE 事件协议（候选事件类型：`event: keywords` / `event: match_vids` / `event: gremlin` / `event: graph_result` / `event: done`），并改 flow 在每个阶段写入对应事件，而**不是**套 ChatCompletionChunk 的 `choices[].delta.content` 模式（语义不匹配，前端 EventSource 消费逻辑也不同）。
   - **`/text2gremlin/stream`（推迟到 Phase 2，独立设计）**：`Text2GremlinFlow` 无 `AnswerSynthesizeNode`，不会写入 `stream_generator`；若按 `/rag/stream` 方式实现，只能返回 `No stream_generator found` 或一次性返回最终结果。若需支持，需单独定义事件协议如 `match_result` / `raw_gremlin_delta` / `template_gremlin_delta` / `execution_result` / `done`，同样**不能套** ChatCompletion token delta 模式。

   Phase 1 退出标准与 P1-T4 任务清单需以此为准：只交付 `/rag/stream`；`/rag/graph/stream` 与 `/text2gremlin/stream` 不在 Phase 1 范围内。

1.3. 流式接口必须支持中途取消，取消语义分两层：
   - **检索/pipeline 阶段**：best-effort cancellation——客户端断开后 SSE generator 停止写入。HTTP async 路径采用 `await asyncio.to_thread(pipeline.run)`（P1-T0 spike 选定方案 b）使事件循环不被独占，但 pipeline 内部已发起的同步阻塞 IO（pyhugegraph 请求等）只能等待超时或自然返回，无法强制中断。
   - **LLM streaming 阶段**：必须显式取消 pending tasks 并关闭 async generator（`finally` 中 cancel task、await gather、必要时 `aclose()`），确保 LLM streaming 资源释放。

1.4. 流式输出的事件结构需与 OpenAI Chat Completions streaming 协议保持语义一致。需增加一层 API adapter（`to_chat_completion_stream_chunk(...)`）明确 payload schema，输出 delta 而非累计全文：
   - 每个 token 一个 chunk：`data: {"id":"...","object":"chat.completion.chunk","choices":[{"index":0,"delta":{"content":"<本次增量>"},"finish_reason":null}]}`
   - 首 chunk 在 `delta` 中带 `"role":"assistant"`，结束 chunk 中 `delta` 为空且 `finish_reason="stop"`，最后再发 `data: [DONE]`
   - 多 answer 类型（`raw_answer` / `vector_only_answer` / `graph_only_answer` / `graph_vector_answer`）映射到不同 `choices[].index`，单次响应内 index 与 answer_type 的对应关系稳定不变
   - 错误以独立 `event: error` 事件下发（见 1.5），不混在 `chat.completion.chunk` 里

   当前 `AnswerSynthesize.async_streaming_generate()` 是把 token 追加到 context 后反复 yield 整个 context（类似 Gradio state snapshot），直接包进 `data:` 不是 delta chunk，前端无法复用 OpenAI ChatCompletionChunk 消费逻辑。

   **adapter 实现要求**：必须从源头按 token 流消费——即 `async_streaming_generate()`（或新增的 `async_streaming_delta()`）直接 yield `(answer_type, token_delta)`，由 adapter 包装成 ChatCompletionChunk。**禁止**用"本轮累计 - 上轮累计 = delta"这种字符串反推方式，因为多 answer 并发完成、空 token、token 末尾等于上一 token 后缀等边界场景会算错。

   **测试断言要求**（见 [tasks.md](./tasks.md) P1-T5）：
   - 所有 chunk 的 `delta.content` 按 index 拼接后等于完整答案
   - 任意 chunk 的 `delta.content` **不得**是历史 chunk 累积内容的前缀超集（拒收累计全文实现的关键护栏）
   - 多 answer 场景下同一 `index` 始终对应同一 `answer_type`
   - 首 chunk 含 `delta.role="assistant"`，结束 chunk 含 `finish_reason="stop"`，`[DONE]` 在结束 chunk 之后

1.5. 错误事件需以独立的 SSE event 类型（如 `event: error`）下发，不能简单 HTTP 5xx，因为流式响应在首字节后已无法回退到 HTTP 错误码。

### 2. 端到端 async 化（全链路）

**核心**：采用方案 A（API async boundary）——HTTP async 路径在事件循环上调度 pipeline，同时将请求路径上的热点 IO 逐步改为 async。不追求"端到端 async 化"（方案 B 需要改 `operator.run`、node 调度和 pipeline contract，改动面过大），当前 `GraphQueryNode`/`GremlinExecuteNode`/`Text2GremlinNode` 内部仍走同步调用，现阶段目标为：`API async boundary + 非阻塞 pipeline 调度 + 局部 async IO`。

**Pipeline 异步调度采用 `await asyncio.to_thread(pipeline.run)`**（P1-T0 spike 已结题，见 [pycgraph_async_spike.md](./pycgraph_async_spike.md) 与验收 2.4 / [design.md](./design.md) §3.2）：在固定 `pycgraph==3.2.4` 上实测 `asyncRun()` 返回 `StdFutureCStatus`，不是 Python awaitable，且 `wait()`/`get()` 阻塞不释放 GIL，方案 a 不可达。Gradio 等同步路径继续使用同步 `pipeline.run()` 不变。

**验收标准**：

2.1. **HTTP 路由层**：所有 RAG 相关路由签名改为 `async def`。

2.2. **检索/重排 IO 层**：将请求路径上的 `requests` 同步调用替换为 `httpx.AsyncClient`，覆盖范围至少包括：
   - `utils/hugegraph_utils.py:23`
   - `models/rerankers/cohere.py`
   - `models/rerankers/siliconflow.py`
   - `operators/common_op/merge_dedup_rerank.py:22`
   - `operators/hugegraph_op/schema_manager.py`
   - `config/huge_config.py:49`（启动期可保留同步，请求路径必须替换）

2.3. **HugeGraph 客户端**：不强行修改 `hugegraph-python-client` 子项目（独立维护、影响面大）；在 hugegraph-llm 内部新增 `AsyncHugeGraphAdapter`，对热点检索方法（vid 查询、邻居查询、Gremlin 执行）走 `httpx` 直连 HugeGraph REST API；冷路径仍调用同步 `pyhugegraph` 不动。

2.4. **Pipeline 引擎**：`pycgraph.GPipeline` 暴露了 `asyncRun()` 方法，但 P1-T0 spike 在固定 `pycgraph==3.2.4` 上实测：返回 `pycgraph.StdFutureCStatus`（C++ future 包装），不是 Python awaitable（`inspect.isawaitable() = False`），直接 `await` 抛 `TypeError`；其 `wait()` 阻塞调用线程不释放 GIL（节点 `time.sleep(0.05)` → `wait()` blocked 50.2ms）。详见 [pycgraph_async_spike.md](./pycgraph_async_spike.md)。

   **采纳方案**：HTTP async 路径统一写 `status = await asyncio.to_thread(pipeline.run)`（与同步 `run()` 等价，事件循环不被独占）。`asyncio.to_thread(future.get)` 在阻塞性质上与之等价、并无收益（spike 第 [1] 项 `wait/get` 阻塞数据已证实），不画蛇添足。Gradio 等同步路径继续使用 `pipeline.run()` 不变。

   **不要**给 `asyncio.to_thread(pipeline.run)` / `loop.run_in_executor(..., pipeline.run)` 加 lint 禁用规则——这是当前 pycgraph 上唯一可用的非阻塞接入方式。

   **验收测试需断言**：高并发场景下该实现不阻塞事件循环（事件循环单次 tick 阻塞 P99 ≤ 50ms，详见 [tasks.md](./tasks.md) Phase 2 退出标准 §"运行时门禁"），且与同步 `run()` 对同一 pipeline 的执行结果一致。

   **未来回路**：若 pycgraph 上游提供真正 Python awaitable 的 `asyncRun()`，可平滑切换为 `await pipeline.asyncRun()` 并在测试里加 `assert inspect.isawaitable(pipeline.asyncRun())` 防回退；属后续优化项，不在当前设计范围。

2.5. **retry 装饰器**：`models/llms/ollama.py` 的同步 `retry` 库替换为 `tenacity` 的 async 用法，与 OpenAI/LiteLLM 实现保持一致。

2.6. **嵌套事件循环消除**：删除 `operators/llm_op/answer_synthesize.py:73` 处的 `asyncio.run(...)` 调用；同步路径与异步路径分别提供独立入口（`run` / `run_async`），不在 async 上下文里嵌套新建事件循环。

2.7. **测试基础设施**：引入 `pytest-asyncio`，在 `pyproject.toml` 显式声明 `fastapi`、`uvicorn`、`httpx`、`pytest-asyncio` 依赖。所有 `async def` 路由补 `@pytest.mark.asyncio` 测试。

2.8. **lint 防御**：通过 ruff 规则或自定义检查禁止在 `async def` 函数体内直接 `import requests` / 调用 `requests.*`，防止退回同步阻塞。

### 3. 性能与并发指标

**核心**：改造后的 async + streaming 接口需在压测中体现可衡量的收益。

**验收标准**：

3.1. **TTFT（首字节时间）显著下降**：相同 prompt 下，`/rag/stream` 的 TTFT 应不高于 `/rag` 端到端时延的 30%（首 token 出现时机以检索完成为准）。

3.2. **并发吞吐提升**：单 worker 在 32 路并发下，async 接口的 RPS 应不低于同步接口的 2 倍（前提是 LLM 后端非瓶颈）。

3.3. **单请求时延不退化**：低并发下（QPS=1），async 接口端到端时延相比同步接口的退化幅度不超过 5%。

3.4. **资源占用可控**：httpx 连接池大小、第三方同步 SDK fallback 线程池大小可通过配置项调整，默认值在 `config/` 下显式声明。pipeline 并发走 `asyncio.to_thread(pipeline.run)` → asyncio default executor；若 Phase 2 压测中事件循环 tick gap P99 不达标，可在 lifespan 中调 `loop.set_default_executor(...)` 或在 `AsyncConfig` 中补 `pipeline_thread_pool_size` 字段。

### 4. 错误处理与可观测性

**核心**：异步 + 流式场景下的错误不能被吞掉，必须可追溯。

**验收标准**：

4.1. 流式生成途中发生异常时，下发 `event: error` 事件并包含 trace_id；不允许静默关闭连接。

4.2. 客户端中途断开（`asyncio.CancelledError`）时，上游 LLM 调用必须被取消，cancel 路径需写日志便于排查。

4.3. 新增 observability 工作：定义 `trace_id` 生成、通过 `contextvars` 传播、响应头/SSE error payload 输出，以及 sync/async/stream metrics。需先确认 `middleware/middleware.py` 是否实际注册（当前未被 `app.add_middleware()` 挂载），再把它作为已有能力兼容项。

4.4. 在请求级别的 metrics 中区分 sync / async / stream 三种类型，便于后续观测改造收益。

### 5. 向后兼容与迁移

**核心**：改造期间不能影响现有 Gradio Demo 与外部 API 调用方。

**验收标准**：

5.1. 现有同步接口在 Phase 3 完成后仍保留至少一个版本周期，行为不变。

5.2. Gradio Demo 端的 `rag_block.rag_answer_streaming` 调用路径不需要修改，复用新的 async 实现。

5.3. 提供从 sync 到 async 的迁移指南文档，列出所有破坏性变更（如有）。
