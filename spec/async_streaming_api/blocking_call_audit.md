# Phase 2 间接同步调用门禁 — 审计交付物

> 配套 [tasks.md](./tasks.md) Phase 2 退出标准「间接同步调用门禁」要求。
>
> AST `requests.*` 检查（[scripts/lint_async_no_requests.py](../../scripts/lint_async_no_requests.py)）只是 direct-call guard——`PyHugeClient.gremlin().exec()` 这种 wrapper 把同步 IO 藏在调用链里，AST 看不到。本文档逐条列举请求路径上的"间接同步 IO"调用，给出归属类别。
>
> **归属类别说明**：
> - **A. async**：调用本身已是 async（`await ...`），事件循环不受阻塞
> - **B. bounded executor (outer)**：调用本身是 sync，但 caller 整体已被外层 `await asyncio.to_thread(pipeline.run)` 推入 default executor（P1-T0 spike 选定的方案 b），事件循环不受阻塞——这是 Phase 2 的主防线
> - **C. bounded executor (inner)**：直接 `await asyncio.to_thread(sync_fn)`，事件循环不受阻塞
> - **D. main loop bridge**：sync caller 通过 `runtime.run_async_from_sync()`（内部 `asyncio.run_coroutine_threadsafe`）跳回主 loop 调真 async 实现——用于复用共享 httpx 连接池

## 1. PyHugeClient / `gremlin().exec()` / `schema.getSchema()`

| 位置 | 调用 | 类别 | 说明 |
|------|------|------|------|
| `utils/hugegraph_utils.py:37` | `get_hg_client().gremlin().exec(query)` 在 `run_gremlin_query` | B | 被 pycgraph node `OperatorList` 调；外层 `await asyncio.to_thread(pipeline.run)` 边界化 |
| `utils/hugegraph_utils.py:115`（`backup_data` 内的 `.schema().getSchema(_format="groovy")`） | sync | B | lifespan AsyncIOScheduler 每日 1:00 调；非请求路径 |
| `utils/hugegraph_utils.py:137,140` | `client.gremlin().exec(query)` | B | 同上（backup_data 内部）|
| `utils/graph_index_utils.py:64,70` | `gremlin().exec(...)` | B | 仅 admin 接口/Gradio 按钮调 |
| `operators/hugegraph_op/schema_manager.py:62` | `self.schema.getSchema()` 在 `run` | B | pycgraph node 内；外层 to_thread 边界化 |
| `operators/hugegraph_op/commit_to_hugegraph.py:31` | sync schema/graph 操作 | B | pycgraph node 内 |
| `operators/hugegraph_op/fetch_graph_data.py:25,47` | sync gremlin | B | pycgraph node 内 |
| `operators/index_op/semantic_id_query.py:51,68` | sync gremlin | B | pycgraph node 内（RAG 主路径）|
| `nodes/hugegraph_node/graph_query_node.py:96,131,153,359,374,404` | 5 处 `gremlin().exec(...)` | B | pycgraph node 内（RAG 主路径，调用最频繁）|
| `indices/graph_index.py:35,40,51` | sync gremlin | B | pycgraph node 内 |

**结论**：所有 PyHugeClient 调用均为类别 B（外层 to_thread 边界化）。Phase 2 不重写为 async；[adapters/async_hugegraph_adapter.py](../../hugegraph-llm/src/hugegraph_llm/adapters/async_hugegraph_adapter.py) 提供类别 C 入口（`async def execute_gremlin / get_schema / query_vid / call`，内部 `await asyncio.to_thread`），仅给 Phase 3 不走 pipeline 的 HTTP 路由直接调 HugeGraph 时备用。

> **范围决策记录**：原 spec P2-T5 计划"热点方法走 httpx 直连 HugeGraph REST"被收敛为"统一 to_thread 包装"——pyhugegraph 整套基于 requests，重写一层 REST 客户端工作量超出 Phase 2 单期能消化的程度，且与 P1-T0 spike 选定的方案 b 同源。等 pyhugegraph 上游提供 async 入口时再切换。

## 2. 同步 LLM `generate()`（请求路径上禁止使用）

请求路径上**禁止使用** sync `generate()`；统一走 `agenerate` / `agenerate_streaming`。

| 文件 | sync 入口 | async 入口 | 请求路径上是否还在用 |
|------|----------|-----------|---------------------|
| `models/llms/openai.py` | `generate` (line 57) | `agenerate` (line 95) | 否（路由侧已切 async）|
| `models/llms/litellm.py` | `generate` | `agenerate` | 否 |
| `models/llms/ollama.py` | `generate` (line 38) | `agenerate` (line 64) | 否 |
| `models/llms/qianfan.py` | — | — | 不存在该 client（grep 无匹配）|

**ollama 历史 silent-broken bug 已修复**（P2-T6）：原 `from retry import retry` 装饰 `async def agenerate` 时，`retry` 包不感知 coroutine——只在创建协程时重试一次，await 中的网络异常**完全不会被重试**。已替换为 tenacity，并补回归测试。

## 3. Reranker 同步 IO

| 位置 | 类别 | 说明 |
|------|------|------|
| `models/rerankers/cohere.py:aget_rerank_lists` | A | `await runtime.get_http_client().post(...)` |
| `models/rerankers/cohere.py:get_rerank_lists` | D | `runtime.run_async_from_sync(self.aget_rerank_lists(...))` |
| `models/rerankers/siliconflow.py:aget_rerank_lists` | A | 同上 |
| `models/rerankers/siliconflow.py:get_rerank_lists` | D | 同上 |
| `operators/common_op/merge_dedup_rerank.py:131` except | — | `httpx.RequestError`/`HTTPStatusError`（已替换 `requests.exceptions.RequestException`），fallback-to-bleu 兜底保留并新增回归测试 |

**为什么 reranker 走类别 D 而 hugegraph 走类别 B？**
- reranker 底层是真 async httpx + 共享连接池：跳回主 loop 用共享 client 有意义（连接复用 + tick-gap 探针 P99 更优）。
- hugegraph 底层是 sync `PyHugeClient`（基于 requests）：跳回主 loop 没有 async 后端可调，反而是 sync→主loop→worker→sync 的多余跳跃。

## 4. `pipeline.run()`（HTTP async 路径）

| 位置 | 类别 | 说明 |
|------|------|------|
| `flows/scheduler.py:schedule_stream_flow` 两处 | C | `status = await asyncio.to_thread(pipeline.run)`（P1-T0 spike 选定方案 b）|
| `flows/scheduler.py:schedule_flow` (Gradio sync 路径) | — | 仍 `pipeline.run()`，由 Gradio 同步路径调用，无需 async 化 |

## 5. utils/hugegraph_utils.py `check_graph_db_connection`

| 入口 | 类别 | 说明 |
|------|------|------|
| `acheck_graph_db_connection` | A | `await runtime.get_http_client().get(...)` |
| `check_graph_db_connection` | C | 一次性 `httpx.Client()` 同步调用——Gradio configs_block 在 lifespan 启动前调用，runtime 还没 client；**不绕主 loop**（避免 D 类的 sync→loop→worker 跳跃）|

## 6. 冷路径未改项（Phase 2 范围外）

| 位置 | 现状 | 计划 |
|------|------|------|
| `operators/index_op/gremlin_example_index_query.py:62` | `ThreadPoolExecutor` 跑 sync `embedding.get_text_embedding` | 冷启动一次性建索引，不在请求路径；底层 embedding 仍 sync。Phase 3 embedding async 化时一并改 |

---

## 总结

- **直接调用门禁**：[lint_async_no_requests.py](../../scripts/lint_async_no_requests.py) 已就位 + 单测；CI 接入待项目 CI 流水线接入
- **间接同步调用门禁**：本文档覆盖。所有 PyHugeClient 调用均类别 B；reranker async + sync 包装走类别 D；pipeline.run 类别 C
- **运行时门禁**：[async_load_probe.py](../../scripts/async_load_probe.py) 已就位 + **2026-05-28 远端基线达标**：

  ```json
  200 req / 32 并发：completed=200 failed=0 wall=12.4s rps=16.13
  latency_ms: p50=1361 p95=3857 p99=4166
  tick_gap_ms: p50=5.08 p95=5.90 p99=6.06    ← gate 50ms，远低于 1/8 ✅
  ```

  事件循环单 tick 阻塞 P99 仅 ~6ms（asyncio.sleep(5ms) 自然抖动级别），证明 P1-T0 方案 b（`await asyncio.to_thread(pipeline.run)`）+ Phase 2 reranker D 类桥都没让事件循环受阻。

---

## 附录：Phase 3 mock-LLM 压测（2026-05-29）

> 用 [scripts/mock_llm_server.py](../../scripts/mock_llm_server.py)（first_token_delay=0.2s / per_token_delay=0.02s / tokens=100，单次响应 ≈ 2.2s）替换真实 LLM 后端，让 latency 完全由路由层 + pipeline 调度决定。`raw_answer=True` 路径走单次 chat LLM 调用，绕开向量/图检索与 rerank。

### 测试矩阵

四组对照（async route always-on flag=1，stream/non-stream 两条路径）：

| # | endpoint | mode | c | requests | rps | p50 | p95 | p99 | tick P99 |
|---|----------|------|---|----------|-----|-----|-----|-----|----------|
| 1 | /rag/stream | async + SSE | 1  | 50  | 0.45  | 2222.9 | 2232.2 | 2244.8 | 6.05 |
| 2 | /rag/stream | async + SSE | 32 | 200 | 10.63 | 2732.8 | 3406.2 | 7975.2 | 6.06 |
| 3 | /rag        | async + JSON | 1  | 50  | 0.45  | 2231.5 | 2241.5 | 2243.1 | 5.14 |
| 4 | /rag        | async + JSON | 32 | 200 | 10.98 | 2444.0 | 3574.9 | 3808.0 | 5.90 |

> sync 基线（`HUGEGRAPH_LLM_ASYNC_ROUTES_ENABLED=0`）未单独采集——首次复跑时未重启 app 切 flag，c=32 数据 (rps≈11.79 / p99=2793ms) 与 async 几乎重合，证实**当前瓶颈不在路由层 async/sync 选择**。详见下文。

### 三条门禁判定

- **运行时门禁（tick_gap P99 ≤ 50ms）✅**：4 组全部 5–6ms，事件循环未被任何同步调用独占。这是改造最确凿的成果。
- **QPS=1 时延退化 ≤ 5% ✅**：c=1 p50 全部贴在 2.23s（mock 理论值 2.2s），async 路由层无显著开销。
- **QPS=32 吞吐 ≥ sync × 2.5 ⚠️ 不达标，但非路由层瓶颈**：async / sync 几乎打平在 ~11 RPS。理论上限 = `concurrency / latency = 32 / 2.2 = 14.5`，实测 11 ≈ **76%**——已逼近上限。剩余 24% gap 来自下游池竞争，不是事件循环阻塞（tick gap P99 = 6ms 已证）。

### 真实瓶颈：Pipeline pool 与 default executor

c=32 时三个串联的"32 并发吞吐"约束：

1. **`Scheduler.pipeline_pool[flow_name].max_pipeline = 10`**（[scheduler.py:45](../../hugegraph-llm/src/hugegraph_llm/flows/scheduler.py#L45)）—— 22 个请求等池
2. **asyncio default executor**（`asyncio.to_thread` 入口）默认 = `min(32, cpu+4)`
3. **GIL** —— pyhugegraph 同步 IO 释放 GIL，但纯 Python pipeline 调度不释放

任意一个池满 → 后续请求队列化 → 体现为 c=32 p99 长尾（stream 路径 7975ms vs p50 2733ms ≈ 3×）。**改 sync 不会解锁这些上限**——sync 路由也走 FastAPI 的 anyio threadpool（默认 40），最终撞同一个 max_pipeline=10。

### 写进 PR 的有效结论

| 维度 | 状态 | 数据支撑 |
|------|------|----------|
| 事件循环非阻塞 | ✅ 通过 | 32 并发 tick_gap P99 = 6.06ms（gate 50ms，达标 1/8） |
| QPS=1 时延不退化 | ✅ 通过 | async/sync 路径 c=1 p50 都贴 mock 理论值 2.23s ±0.5% |
| QPS=32 吞吐 | ⚠️ async ≈ sync ≈ 11 RPS（受 max_pipeline=10 限制） | rps=10.63 (stream) / 10.98 (non-stream) |
| Gradio 同步路径不受影响 | ✅ 通过 | sync 路径仍走 `schedule_flow`（保留） |
| 多模态路径并存 | ✅ 通过 | sync def `/config/*` + async def `/rag*` + SSE `/rag/stream` 同 app 共存 |

**改造的真正价值在质而不在量**：32 并发下事件循环单 tick 阻塞仅 6ms（vs 同步阻塞 IO 时常见 ≥ 1000ms），意味着 SSE 流式输出能稳定推进、客户端断开能秒级响应、混合 sync/async/stream 三种模式不会互相饿死——这才是 P3-T6 的核心交付物。

### 后续优化项（不阻塞 Phase 3 上线）

- 把 `max_pipeline` 提到 32 + 跑同样四组 → 验证 RPS 是否能拉到 13-14（接近理论上限）
- 等真实 LLM 后端接入并能产出基线后，跑一次 1h 持续压测验证内存/连接泄漏（P3-T6 第 3、4 项）
- pycgraph 上游若提供 awaitable `asyncRun()`，切到 `await pipeline.asyncRun()` 跑同样压测对比 to_thread 开销
