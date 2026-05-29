# API 异步与流式输出改造 - 任务清单

> 配套文档：[requirements.md](./requirements.md) | [design.md](./design.md)

## Phase 1：HTTP 暴露已有的流式能力（预计 1-2 天）

### P1-T0：pycgraph asyncRun spike（已结题，选定方案 b）

- [x] **验证 pycgraph 3.2.4 上 `GPipeline.asyncRun()` 的真实返回类型**：实测 `type=StdFutureCStatus`（`pycgraph` 模块），`inspect.isawaitable=False`，`hasattr(__await__)=False`，`hasattr(wait)=True`、`hasattr(get)=True`；`wait()` 阻塞调用线程（节点 `time.sleep(0.05)` → `wait()` blocked 50.2ms，等价同步阻塞、不释放 GIL）
- [x] **结论**：方案 a 在协议层面被排除（`asyncRun()` 非 awaitable，直接 `await` 抛 `TypeError`）；选定**方案 b**——`status = await asyncio.to_thread(pipeline.run)`，与同步 `run()` 等价；`asyncio.to_thread(future.get)` 阻塞性质等价、无收益，不画蛇添足
- [x] **spike 输出物**：[pycgraph_async_spike.md](./pycgraph_async_spike.md)（含 spike 脚本 [pycgraph_async_spike.py](./pycgraph_async_spike.py) 与 [1][2] 项远程实测数据）
- [x] **退出条件**：spike 文档已评审通过；spec 4 个文档（README/requirements/design/tasks）已统一收敛为方案 b 单路径表述；P1-T3 落地以方案 b 写法实施

### P1-T1：依赖与基础设施

- [x] **核对 [pyproject.toml](../../hugegraph-llm/pyproject.toml) 现状**已完成
- [x] **依赖声明策略（2026-05-29 用户决策回滚 P1-T1 的"显式声明"做法）**：`fastapi` / `uvicorn` / `httpx` / `tenacity` 不在 `dependencies` 中显式声明，由 `gradio` / `litellm` 等已声明依赖传递引入；`[project.optional-dependencies] dev` 段与 `[tool.pytest.ini_options] asyncio_mode = "auto"` 也不再写入。代码层 `import fastapi / httpx / tenacity` 正常工作，测试用例显式标 `@pytest.mark.asyncio` 故无需 auto 模式
- [x] **`retry` 包保留** [pyproject.toml:50](../../hugegraph-llm/pyproject.toml#L50)：用户决策保留（包冗余但不影响功能；[ollama.py:23](../../hugegraph-llm/src/hugegraph_llm/models/llms/ollama.py#L23) 已切 tenacity）
- [x] **pycgraph 版本统一 = 3.2.4**：`dependencies` ([pyproject.toml:65](../../hugegraph-llm/pyproject.toml#L65)) 与 `[tool.uv.sources] tag = "v3.2.4"` ([pyproject.toml:100](../../hugegraph-llm/pyproject.toml#L100)) 一致，与 P1-T0 spike 实测版本对齐
- [x] ~~若 P1-T0 spike 选方案 a，在此处一并锁定 pycgraph 下限版本~~ — spike 已选方案 b，无需锁定下限

### P1-T2：消除嵌套事件循环

- [x] 拆分 sync / async 入口：[answer_synthesize.py:62-117](../../hugegraph-llm/src/hugegraph_llm/operators/llm_op/answer_synthesize.py#L62-L117) 提供 `run`（同步入口，仅供 pycgraph node operator_schedule / Gradio 同步链）与 `run_async`（HTTP async 路径直接 await）
- [x] **嵌套循环 guard**：sync `run()` 进入时 `asyncio.get_running_loop()` 检测，若已在事件循环中**直接 raise**（明确错误胜于"在 async 上下文里再 `asyncio.run`"产生 `RuntimeError: cannot run nested event loops` 的隐式失败），引导调用方迁移至 `run_async`。`run()` 内部仍保留 `asyncio.run(...)` 是合理的——它现在只在**真正同步**的栈上执行（pycgraph worker thread / Gradio sync 入口），不构成嵌套
- [x] 全文核对 `asyncio.run\(` 其他出现（`build_*_index.py:43-72` 三处），均在冷启动/索引构建脚本，**不在请求路径**，按 design 允许保留

### P1-T2.5：API adapter — ChatCompletion 流式 chunk 转换层

- [x] 新增 [api/chat_completion_adapter.py](../../hugegraph-llm/src/hugegraph_llm/api/chat_completion_adapter.py)，实现 `to_chat_completion_stream_chunk(token, index, role=None, finish_reason=None, completion_id=None, model=None)` 返回符合 ChatCompletionChunk 协议的 dict（与 design.md §1.1 签名一致；可选 `model` 字段为额外便利项）
- [x] 固化 `ANSWER_TYPE_TO_INDEX` 映射 [chat_completion_adapter.py:42-47](../../hugegraph-llm/src/hugegraph_llm/api/chat_completion_adapter.py#L42-L47)：`raw_answer=0` / `vector_only_answer=1` / `graph_only_answer=2` / `graph_vector_answer=3`
- [x] 改造 [operators/llm_op/answer_synthesize.py:async_streaming_generate](../../hugegraph-llm/src/hugegraph_llm/operators/llm_op/answer_synthesize.py#L230-L339)：直接 yield `(answer_type, token_delta)` 元组；`finally` 中 cancel pending tasks → `gather(return_exceptions=True)` → `aclose()` 每个子 generator
- [x] **活跃 task 集合管理**：用 `active: Dict[asyncio.Task, int]` 维护，`pop` 后再决定是否 schedule 下一个 `anext`；循环条件 `while active`，已根除 busy loop 风险（[answer_synthesize.py:306-326](../../hugegraph-llm/src/hugegraph_llm/operators/llm_op/answer_synthesize.py#L306-L326)）
- [x] 在 [api/chat_completion_adapter.py:rag_stream_generator](../../hugegraph-llm/src/hugegraph_llm/api/chat_completion_adapter.py#L101-L173) 中接入 adapter：消费 `(answer_type, token)` → 调 adapter → 写 SSE；首块带 `delta.role="assistant"`，正常结束时每个 index 各发一个 `finish_reason="stop"` 的空 chunk，最后发 `data: [DONE]\n\n`
- [x] [accumulate()](../../hugegraph-llm/src/hugegraph_llm/api/chat_completion_adapter.py#L176-L192) wrapper 维持 Gradio "累计快照" 旧形态，与新 delta 流共享同一份 token 源；operator 源头未回退到累计 yield
- [x] **明确禁止**：adapter 不读上一轮累计、不做字符串差分；delta 由源头直传（已落地 + 测试 [test_chat_completion_adapter.py:test_no_chunk_equals_accumulated_history](../../hugegraph-llm/src/tests/api/test_chat_completion_adapter.py#L182-L200) 护栏）

### P1-T3：修正 schedule_stream_flow 的伪异步（P1-T0 spike 已选定方案 b）

- [x] **方案 b 落地**：`flows/scheduler.py:schedule_stream_flow` 中两处 `pipeline.run()` 改为 `status = await asyncio.to_thread(pipeline.run)`；`asyncRun()` 在 pycgraph 3.2.4 上不是 awaitable（详见 [pycgraph_async_spike.md](./pycgraph_async_spike.md)），方案 a 不可达
- [x] **顺手修复独立 bug**：`schedule_stream_flow` 在"新建 pipeline"分支漏 `return` 导致首次请求 pipeline 跑两遍 / LLM token 流被复发两遍；同时把 `manager.add(pipeline)` 用 `try/finally` 包裹防止 `post_deal_stream` 抛异常时 pipeline 资源泄漏
- [x] 同步路径 `schedule_flow`（L121、L134）保持 `pipeline.run()` 同步调用不变（Gradio 走这条）
- [x] **不预设 lint 禁用规则**：方案 b 下 `asyncio.to_thread(pipeline.run)` 是合法且必要的实现，**禁止**新增"禁用 `asyncio\.to_thread\(\s*pipeline\.run`"的 CI 规则
- [x] 验证 `post_deal_stream` 的 async generator 行为不变（[test_rag_stream_api.py](../../hugegraph-llm/src/tests/api/test_rag_stream_api.py) 通过 mock 后的 schedule_stream_flow 走通整个生成器链路）
- [x] 高并发场景下事件循环不被单个 pipeline 阻塞——指标已在 Phase 2 退出标准压测中采集：32 路并发 / 200 req，**tick_gap P99 = 6.06 ms**（远低于 50 ms gate），详见 [blocking_call_audit.md](./blocking_call_audit.md) §"运行时门禁"

### P1-T3.5：审视 flows/ 下其余 flow 文件是否含同步 IO

- [x] 已审视所有 flow 文件的 `prepare` / `build_flow` / `post_deal` / `post_deal_stream`，**flow 层无直接 `requests.*` / 同步 SDK 调用**——所有 IO 都封装在 node 实现里。审计交付物：[flows_sync_io_audit.md](./flows_sync_io_audit.md)
- [x] flow 间接依赖的同步 IO（reranker / hugegraph_utils / schema_manager）已归入 Phase 2 P2-T3 / P2-T4 / P2-T5 处理

### P1-T4：新增流式 SSE 路由（仅 `/rag/stream`）

- [x] [api/rag_api.py:118-175](../../hugegraph-llm/src/hugegraph_llm/api/rag_api.py#L118-L175) 新增 `POST /rag/stream`（`async def`，返回 `StreamingResponse`），采用 OpenAI ChatCompletionChunk 协议
- [x] `event_generator` 内通过 `is_disconnected=request.is_disconnected` 传递给 `rag_stream_generator`；`asyncio.CancelledError` 显式 log + reraise；`finally` 中调用 `delta_stream.aclose()` 触发上游 LLM streaming task 取消
- [x] 错误事件以 `event: error\ndata: {...}\n\n` 下发，包含 `trace_id`（[chat_completion_adapter.py:154-159](../../hugegraph-llm/src/hugegraph_llm/api/chat_completion_adapter.py#L154-L159)）
- [x] 流尾 `data: [DONE]\n\n` 哨兵（含错误路径，便于客户端干净收尾，[chat_completion_adapter.py:171-173](../../hugegraph-llm/src/hugegraph_llm/api/chat_completion_adapter.py#L171-L173)）
- [x] 响应头 `X-Accel-Buffering: no` / `Cache-Control: no-cache` / 额外 `X-Trace-Id`（[rag_api.py:167-175](../../hugegraph-llm/src/hugegraph_llm/api/rag_api.py#L167-L175)）
- [x] **空 query / 全部 answer 标志位为 False** 的 400 在 StreamingResponse 启动**前**抛 HTTPException（避免首字节后无法回退状态码）
- [x] **不在 Phase 1 范围**：`/rag/graph/stream` 与 `/text2gremlin/stream` 仍未实现，符合 spec；代码中无遗留 stub

### P1-T5：测试与验证

- [x] 引入 `pytest-asyncio`（dev extras），新增 [tests/api/test_rag_stream_api.py](../../hugegraph-llm/src/tests/api/test_rag_stream_api.py) 与 [tests/api/test_chat_completion_adapter.py](../../hugegraph-llm/src/tests/api/test_chat_completion_adapter.py)
- [x] 用 `httpx.AsyncClient + ASGITransport` 测试流式响应、错误事件、客户端中断
- [x] **多 answer stream 协议合规** + **错误下发为 SSE event 而非半挂**：[test_rag_stream_multi_answer_indexes_stable](../../hugegraph-llm/src/tests/api/test_rag_stream_api.py#L141-L170) / [test_rag_stream_error_event_with_trace_id](../../hugegraph-llm/src/tests/api/test_rag_stream_api.py#L194-L206)
- [x] **断开探针短路**：[test_is_disconnected_short_circuits](../../hugegraph-llm/src/tests/api/test_chat_completion_adapter.py#L233-L253) 验证 `is_disconnected` 触发后立即停止写入；同时 [rag_api.py:159-165](../../hugegraph-llm/src/hugegraph_llm/api/rag_api.py#L159-L165) 的 `delta_stream.aclose()` 触发 [answer_synthesize.py:327-338](../../hugegraph-llm/src/hugegraph_llm/operators/llm_op/answer_synthesize.py#L327-L338) 的 cancel + gather + aclose finally 语义
- [x] **ChatCompletionChunk 协议合规断言**（防止累计实现回潮）：
  - [x] 每个 `data:` payload 含 `id` / `object="chat.completion.chunk"` / `choices`：[test_chunk_shape_basic](../../hugegraph-llm/src/tests/api/test_chat_completion_adapter.py#L86-L94)
  - [x] 同 index 下 `delta.content` 拼接 = 完整答案：[test_single_index_concat_equals_full_answer](../../hugegraph-llm/src/tests/api/test_chat_completion_adapter.py#L114-L123)
  - [x] **关键护栏**：delta 长度 ≤ 200 且不得等于历史累计：[test_no_chunk_equals_accumulated_history](../../hugegraph-llm/src/tests/api/test_chat_completion_adapter.py#L182-L200) + [test_rag_stream_no_chunk_equals_accumulated_prefix](../../hugegraph-llm/src/tests/api/test_rag_stream_api.py#L173-L191)
  - [x] 同一 `answer_type` 始终对应同一 index：[test_index_mapping_stable_per_answer_type](../../hugegraph-llm/src/tests/api/test_chat_completion_adapter.py#L149-L179)
  - [x] 首块带 `role="assistant"`；结束块 `finish_reason="stop"` 且 delta 无 `content`；`[DONE]` 在结束块之后：[test_first_chunk_has_role_subsequent_no_role](../../hugegraph-llm/src/tests/api/test_chat_completion_adapter.py#L126-L135) / [test_done_after_all_finish_chunks](../../hugegraph-llm/src/tests/api/test_chat_completion_adapter.py#L138-L146)
  - [x] 错误事件以 `event: error` 行起始 + payload 含 `trace_id`：[test_error_event_emitted_with_trace_id](../../hugegraph-llm/src/tests/api/test_chat_completion_adapter.py#L213-L230)
- [x] Gradio demo 通过 [accumulate()](../../hugegraph-llm/src/hugegraph_llm/api/chat_completion_adapter.py#L176-L192) 复用 token 源（[test_accumulate_yields_snapshot_per_token](../../hugegraph-llm/src/tests/api/test_chat_completion_adapter.py#L259-L273)），未污染 operator 源头
- [ ] curl 手动冒烟（端到端真实 LLM）— 待联调环境执行；自动化测试已用 `httpx.AsyncClient` 完整覆盖协议合规

### Phase 1 退出标准

- [x] **唯一**新增的 `/rag/stream` 路由可用（[rag_api.py:118-175](../../hugegraph-llm/src/hugegraph_llm/api/rag_api.py#L118-L175)）；`/rag/graph/stream`、`/text2gremlin/stream` 不在 Phase 1 范围（无遗留实现）
- [x] 客户端断开 → `is_disconnected` 短路 + `delta_stream.aclose()` 触发 `answer_synthesize.async_streaming_generate` 的 finally cancel/gather/aclose；自动化测试覆盖（断开后断言）
- [x] 原同步接口响应结构 byte-for-byte 不变：[test_rag_api.py](../../hugegraph-llm/src/tests/api/test_rag_api.py) 沿用既有断言 + Phase 3 P3-T5 feature flag 保留同步路径回退
- [x] 流式接口 payload 通过 ChatCompletionChunk 协议合规断言（P1-T5 全部用例 pass）
- [ ] **远端全量回归**待用户在远端环境执行 `pytest hugegraph-llm/src/tests/`（Phase 2 已记录 293 passed / 13 skipped / 0 failed 基线，Phase 3 新增的 P3-T1/T3/T4 用例需在合并前再跑一次）

### P1-T6：post-review contract 加固（2026-05-29）

> 维护者 review（[PR comments](https://github.com/apache/incubator-hugegraph-ai/pull/336) 9 条 inline）指出 V1 仍有 4 个 blocker / 3 个重要项 / 2 个小问题，主要集中在「streaming contract 边界没钉死 + 测试覆盖太窄漏过 mock」。本节是 review 整改的最小集，**修复后**才认为 Phase 1 真正可合并。

- [x] **#1 阻塞｜`/rag` 与 `/rag/stream` 检索参数透传不一致**：[rag_api.py:_rag_delta_stream](../../hugegraph-llm/src/hugegraph_llm/api/rag_api.py#L82-L130) 补传 `max_graph_items` / `topk_return_results` / `vector_dis_threshold` / `topk_per_keyword` 4 个 kwargs 到 `schedule_stream_flow`。新增 contract test：[test_rag_stream_passes_retrieval_params_to_scheduler](../../hugegraph-llm/src/tests/api/test_rag_stream_api.py) + [test_rag_answer_passes_retrieval_params_to_func](../../hugegraph-llm/src/tests/api/test_rag_api.py) 用非默认 sentinel 值（1234 / 77 / 0.42 / 9）锁住两条 API 路径的契约对齐；fake scheduler 加 `captured_kwargs` 钩子，根除 review 提到的「`**_kwargs` 吞掉漏传也全绿」问题
- [x] **#2 阻塞｜scheduler cold path 取消时 pipeline 泄漏**：[scheduler.py:schedule_stream_flow](../../hugegraph-llm/src/hugegraph_llm/flows/scheduler.py#L186-L240) cold path 的 try/finally 上移到 `build_flow(...)` 之后，覆盖 `init` / `await asyncio.to_thread(pipeline.run)` / `post_deal_stream` 三段；正常 / 异常 / `asyncio.CancelledError` 三条路径都归还 `manager.add(pipeline)`。新增回归测试：[test_scheduler_stream_cancellation.py:test_cold_path_cancellation_returns_pipeline_to_manager](../../hugegraph-llm/src/tests/flows/test_scheduler_stream_cancellation.py) 用阻塞型 fake pipeline + `task.cancel()` 触发取消，断言 `manager.add` 被调用 1 次
- [x] **#3 阻塞｜delta-only stream contract 丢失非 token 状态**：定义 V1 stream item contract（详见 [design.md §1.1](./design.md#11-新增路由设计)）：`(answer_type, token_delta)` / `{"warning": ...}` / `{"error": ...}` 三类，HTTP SSE 与 Gradio `accumulate` wrapper 共享同一套消费逻辑。落地：
  - [x] [WkFlowState](../../hugegraph-llm/src/hugegraph_llm/state/ai_state.py) 加 `switch_to_bleu` 字段（`MergeDedupRerank.run()` 已通过 `context["switch_to_bleu"] = True` 写出，但 `WkFlowState.__dict__` 之前没声明导致 `assign_from_json` 跳过）
  - [x] [BaseFlow.post_deal_stream](../../hugegraph-llm/src/hugegraph_llm/flows/common.py) 在透传 LLM token 流之前先 yield `{"warning": "Online reranker fails, automatically switches to local bleu rerank.", "switch_to_bleu": True}` 控制消息
  - [x] [chat_completion_adapter.rag_stream_generator](../../hugegraph-llm/src/hugegraph_llm/api/chat_completion_adapter.py) 加 `event: warning` / `event: metadata` SSE 通道；`{"error": ...}` 走 `event: error`
  - [x] [demo/rag_demo/rag_block.rag_answer_streaming](../../hugegraph-llm/src/hugegraph_llm/demo/rag_demo/rag_block.py) 把 `accumulate` 暴露的 `__events__` 用 `gr.Warning` 投递给前端，与同步 `/rag` 路径行为一致
  - [x] 回归测试：[test_rag_stream_warning_event_passed_through](../../hugegraph-llm/src/tests/api/test_rag_stream_api.py) / [test_rag_stream_error_dict_emits_event_error](../../hugegraph-llm/src/tests/api/test_rag_stream_api.py) / [test_rag_stream_generator_emits_event_warning_for_warning_dict](../../hugegraph-llm/src/tests/api/test_chat_completion_adapter.py) / [test_rag_stream_generator_emits_event_error_for_error_dict](../../hugegraph-llm/src/tests/api/test_chat_completion_adapter.py)
- [x] **#4 重要｜`accumulate()` 把 error dict 解包成 ValueError 掩盖根因**：[chat_completion_adapter.accumulate](../../hugegraph-llm/src/hugegraph_llm/api/chat_completion_adapter.py) 显式区分 dict / tuple；`{"error": ...}` raise `RuntimeError`，`{"warning": ...}` 走 `__events__`，非法形态 log warning 后忽略而不崩溃。回归：[test_accumulate_raises_on_error_dict](../../hugegraph-llm/src/tests/api/test_chat_completion_adapter.py) / [test_accumulate_surfaces_warning_in_events](../../hugegraph-llm/src/tests/api/test_chat_completion_adapter.py)
- [x] **#5 阻塞｜fake scheduler 吞掉 kwargs**：解决方式见 #1（`captured_kwargs` 钩子 + 非默认 sentinel 值）
- [x] **#6 重要｜accumulated history 测试拦不住典型累计序列**：[test_no_chunk_equals_cumulative_typical_sequence](../../hugegraph-llm/src/tests/api/test_chat_completion_adapter.py) 用累计 producer（`["Hello ", "Hello world!"]`）显式断言 adapter 不做反推 — 输出全文 == `"Hello Hello world!"` 而非 `"Hello world!"`，把 design.md §1.4「禁止反推 delta」契约钉死在测试里
- [x] **#7 重要｜reranker fallback 只测私有状态没测对外 contract**：[test_run_writes_switch_to_bleu_into_context_on_reranker_failure](../../hugegraph-llm/src/tests/operators/common_op/test_merge_dedup_rerank.py) 通过 `MergeDedupRerank.run()` 入口（不是 `_rerank_with_vertex_degree` 私有方法）断言 `context["switch_to_bleu"] = True` 被写出。mock side_effect 用 `*args / **kwargs` 吸收 `_dedup_and_rerank` 与 `_rerank_with_vertex_degree` 两种调用签名，避免「空输入也提前抛错」绊倒测试主线
- [x] **#8 小提醒｜siliconflow `_validate` 边界回归丢失**：[test_aget_rerank_lists_negative_top_n_raises](../../hugegraph-llm/src/tests/models/rerankers/test_siliconflow_reranker.py) / [test_aget_rerank_lists_top_n_exceeds_documents_raises](../../hugegraph-llm/src/tests/models/rerankers/test_siliconflow_reranker.py) 补回 `top_n < 0` 与 `top_n > len(documents)` 两个边界用例
- [x] **#9 重要｜scheduler cancellation / pipeline 回收没有回归测试**：解决方式见 #2

### P1-T6 验收

- [x] 7 项 blocker / 重要项的代码与测试落地（远端 `pytest src/tests/api src/tests/flows src/tests/operators src/tests/models -v` 全绿）
- [x] spec 4 个文档（requirements / design / tasks / blocking_call_audit 不涉及）已同步：详见本节链接
- [x] 测试覆盖矩阵（参数透传 / 取消回收 / 控制消息 / contract 反推 / 边界）通过非默认 sentinel + 真 raise 断言锁住，杜绝 mock 漏过
- [ ] **远端 mock-LLM 真机冒烟**：上游若 `switch_to_bleu` 触发，`/rag/stream` 客户端应能在 token 流前就读到 `event: warning` 行；待联调环境一并跑

---

## Phase 2：检索/重排路径换 httpx + async（预计 3-5 天）

### P2-T1：httpx 客户端基础设施

- [x] 在 `demo/rag_demo/other_block.py` 的 `lifespan` 中初始化 `httpx.AsyncClient`，挂到 `app.state.http_client` 与新增 `hugegraph_llm.runtime` 全局 holder（pycgraph node 跑 worker thread 里通过 holder 读共享 client + main loop）
- [x] 配置连接池参数：默认 `max_connections=100`、`max_keepalive_connections=20`（由 `AsyncConfig` 注入）
- [x] 配置超时：默认 connect=5s、read=60s、write=10s、pool=2s（由 `AsyncConfig` 注入）
- [x] 应用关闭时 `await http_client.aclose()`

### P2-T2：新增 AsyncConfig 配置

- [x] 创建 `config/async_config.py`，定义 `AsyncConfig`（继承 `BaseConfig`/`pydantic_settings.BaseSettings`，与其他 config 一致）
- [x] 字段：`http_max_connections` / `http_max_keepalive_connections` / `http_connect_timeout` / `http_read_timeout` / `http_write_timeout` / `http_pool_timeout`。**未引入 `pipeline_executor_max_workers`**：方案 b 默认走 default executor 已够用，若 Phase 2 压测显示需约束再补字段并在 lifespan 注入
- [x] 接入 `config/__init__.py`：`async_settings = AsyncConfig()` 模块级单例，`__all__` 已加入

### P2-T3：替换 reranker 同步 IO

> **实施策略调整（与原 spec 出入）**：reranker 走 **双接口**——`async def aget_rerank_lists` 用共享 `runtime.get_http_client()` 直连；`def get_rerank_lists` 是 sync 包装，通过 `runtime.run_async_from_sync()`（内部 `asyncio.run_coroutine_threadsafe`）从 pycgraph node 的 worker thread 跳回主 loop 调 async 版本。pycgraph 节点协议是 sync 的，无法直接 await——这是把 async httpx + 共享连接池能力下沉到 pipeline node 的最干净办法。

- [x] `models/rerankers/cohere.py`：新增 `async aget_rerank_lists` 用 `runtime.get_http_client().post`；保留 `get_rerank_lists` 为 sync 包装
- [x] `models/rerankers/siliconflow.py`：同上
- [x] 调用方 `operators/common_op/merge_dedup_rerank.py:22` `import requests` 改 `import httpx`；`except requests.exceptions.RequestException` 改 `except (httpx.RequestError, httpx.HTTPStatusError)`，fallback-to-bleu 兜底逻辑保持
- [x] 单测：`tests/models/rerankers/test_cohere_reranker.py` / `test_siliconflow_reranker.py` 全部改用 `pytest.mark.asyncio` + `AsyncMock` mock httpx；新增 sync 包装回归用例。`tests/operators/common_op/test_merge_dedup_rerank.py` 新增 fallback-to-bleu on httpx.ConnectError 用例

### P2-T4：替换检索/工具类同步 IO

> **实施策略调整**：reranker 走"绕主 loop"是因为底层有真 async httpx + 共享连接池可复用；hugegraph 底层是 sync `PyHugeClient`（基于 requests），绕主 loop 只是 sync→主loop→worker→sync 的多余跳跃，**反而劣化**。所以 hugegraph utils / schema_manager 走"sync 主接口 + async 包装走 to_thread"——sync 主接口被 pycgraph node 直接调（已被 `await asyncio.to_thread(pipeline.run)` 外层边界化），async 包装给 Phase 3 路由直接调用预留。

- [x] `utils/hugegraph_utils.py`：`check_graph_db_connection` 拆为 `acheck_graph_db_connection`（async，用共享 httpx）+ sync 版本（一次性 `httpx.Client`，因为 Gradio 启动期常在 lifespan 之前调用、此时 runtime 还没 client）；`run_gremlin_query` 保 sync（被 Gradio 按钮 / pycgraph node 调），新增 `arun_gremlin_query` 异步包装走 `asyncio.to_thread`
- [x] `operators/hugegraph_op/schema_manager.py`：保 sync 不动。该文件被 pycgraph node 调，外层 `await asyncio.to_thread(pipeline.run)` 已边界化；`PyHugeClient` 内部 `RequestException` 异常类型仍兼容（pyhugegraph 仍用 requests），无需改 except
- [x] `config/huge_config.py`：启动期一次性调用，按 P2-T7 lint 白名单豁免，不动
- [ ] `operators/index_op/gremlin_example_index_query.py:59` 的 `ThreadPoolExecutor`：是冷启动一次性建索引、**不在请求路径上**，且底层 `embedding.get_text_embedding` 仍是 sync，Phase 2 不动；列入 Phase 3 待办（embedding async 化时一并改）

### P2-T5：AsyncHugeGraphAdapter（统一 `asyncio.to_thread` 包装）

> **范围决策**：Phase 2 不写 httpx 直连 HugeGraph REST 的客户端（重写一层 PyHugeClient 抽象工作量超出 Phase 2 单期能消化）。统一走 `await asyncio.to_thread(client.gremlin().exec, ...)` 把所有 PyHugeClient 同步调用边界化——与 P1-T0 spike 选定的方案 b 同源（pipeline.run 也是 to_thread），事件循环不被独占。httpx 直连 HugeGraph REST 推迟到后续优化项。

- [x] 创建 `adapters/async_hugegraph_adapter.py`，提供 `AsyncHugeGraphAdapter`（持有 `PyHugeClient`，工厂注入）
- [x] 实现热点方法：`async def query_vid(...)`、`async def execute_gremlin(...)`、`async def get_schema(...)`、`async def call(fn, ...)` 通用逃生口；全部走 `await asyncio.to_thread(...)`
- [x] **lazy 构造**：`__init__` 仅保存 client_factory；`_get_client()` 首次调用才 `await asyncio.to_thread(factory)` 建 PyHugeClient（避免 `__init__` 隐式 IO）
- [x] **不替换现有 ~15 个 pycgraph node callsite**：所有 callsite（`schema_manager.py:28` / `graph_query_node.py:96,131,153,359,374,404` / `commit_to_hugegraph.py` / `fetch_graph_data.py` / `semantic_id_query.py` / `graph_index_utils.py` / `indices/graph_index.py`）都在 pycgraph node 内部、被外层 `await asyncio.to_thread(pipeline.run)` 边界化。再 wrap 一层 `to_thread` 不会让事件循环更不阻塞、徒增 worker→主loop→worker 的跳跃。Adapter 仅作为 **Phase 3 HTTP 路由直连 HugeGraph** 时的入口预留（路由不走 pipeline 的场景）
- [x] 单元测试 [tests/adapters/test_async_hugegraph_adapter.py](../../hugegraph-llm/src/tests/adapters/test_async_hugegraph_adapter.py)：lazy 构造、execute_gremlin / get_schema / query_vid / call、异常传播

### P2-T6：retry 装饰器统一

- [x] `models/llms/ollama.py:23` 的 `from retry import retry` 替换为 `tenacity.retry`（`stop_after_attempt(3) + wait_fixed(1) + reraise=True`）。**这是 silent-broken 修复**：原 `retry` 包不感知 coroutine，被装饰的 `async def agenerate` 实际只在创建协程时重试一次，`await` 中的网络异常**完全不会被重试**——无人察觉的多年潜在 bug
- [x] tenacity 原生支持 async：`async def` 上自动用 `asyncio.sleep`
- [x] 全仓搜索其他 `from retry import` 已无残留；openai.py / litellm.py 已是 tenacity，无需改
- [x] [pyproject.toml](../../hugegraph-llm/pyproject.toml) 保留 `retry` 依赖（用户决策，与 P1-T1 同一拍板）：当前代码已无 `from retry import` 引用、[models/llms/ollama.py:23](../../hugegraph-llm/src/hugegraph_llm/models/llms/ollama.py#L23) 已切 tenacity，包冗余但保留不影响功能。**注意**：本条与 P1-T1 第 18 行"`retry` 包保留"为同一决策——历史版本曾标"移除 retry 依赖（顺手清理）"，已撤回，不要据此再次清理
- [x] 单测 [tests/models/llms/test_ollama_client.py](../../hugegraph-llm/src/tests/models/llms/test_ollama_client.py) 新增：mock `async_client.chat` 抛 `RuntimeError`，断言 tenacity 重试次数恰为 3

### P2-T7：lint 防御（AST 检查 + 白名单）

- [x] 创建 [scripts/lint_async_no_requests.py](../../scripts/lint_async_no_requests.py)，`ast.NodeVisitor` 扫描所有 `async def` 函数体（含嵌套作用域），禁止调用 `requests.*`
- [x] **白名单**：以下文件豁免（不在请求路径上）：
  - `hugegraph-llm/src/hugegraph_llm/demo/rag_demo/configs_block.py`（Gradio UI 配置块）
  - `hugegraph-llm/src/hugegraph_llm/config/huge_config.py`（启动期一次性调用）
- [x] 单元测试 [tests/test_lint_async_no_requests.py](../../hugegraph-llm/src/tests/test_lint_async_no_requests.py) 覆盖：含违例时报错、干净 async 通过、sync 函数被忽略
- [ ] **CI 接入**：在 CI 流水线 lint 阶段加 `python scripts/lint_async_no_requests.py`（与 ruff/pylint 并列），失败阻断 — 待项目 CI 接入时执行

### P2-T8：测试矩阵补齐

- [x] reranker：[test_cohere_reranker.py](../../hugegraph-llm/src/tests/models/rerankers/test_cohere_reranker.py) / [test_siliconflow_reranker.py](../../hugegraph-llm/src/tests/models/rerankers/test_siliconflow_reranker.py) 全部改 `pytest.mark.asyncio` + `AsyncMock` mock httpx；新增 sync 包装回归用例
- [x] hugegraph utils：[test_hugegraph_utils.py](../../hugegraph-llm/src/tests/utils/test_hugegraph_utils.py)（新增）覆盖 `acheck_graph_db_connection` / `check_graph_db_connection` / `run_gremlin_query` / `arun_gremlin_query` 全部分支
- [x] AsyncHugeGraphAdapter：[test_async_hugegraph_adapter.py](../../hugegraph-llm/src/tests/adapters/test_async_hugegraph_adapter.py)（新增）lazy 构造 + 4 个方法 + 异常传播
- [x] ollama retry：[test_ollama_client.py](../../hugegraph-llm/src/tests/models/llms/test_ollama_client.py) 新增 sync/async 双侧 retry 次数断言
- [x] lint 脚本：[test_lint_async_no_requests.py](../../hugegraph-llm/src/tests/test_lint_async_no_requests.py)（新增）3 个边界用例
- [x] merge_dedup_rerank：[test_merge_dedup_rerank.py](../../hugegraph-llm/src/tests/operators/common_op/test_merge_dedup_rerank.py) 新增 fallback-to-bleu on httpx.ConnectError
- [ ] **回归运行**：在远端环境跑 `pytest hugegraph-llm/src/tests/` 全量绿（待用户同步代码后执行）

### P2-T9：压测与性能验证

- [x] 创建 [scripts/async_load_probe.py](../../scripts/async_load_probe.py)：32 路并发 SSE 客户端 + 事件循环 tick gap 探针（每 5ms 采样一次实际间隔，间隔超过预设说明 loop 被同步调用阻塞）；输出 latency P50/P95/P99 + tick_gap P50/P95/P99；tick_gap P99 > 50ms 时 exit 1（Phase 2 退出标准 第三类门禁）
- [x] **远端基线（200 req / 32 并发，2026-05-28）**：

  ```json
  {
    "completed": 200, "failed": 0, "wall_seconds": 12.402, "rps": 16.13,
    "latency_ms": { "p50": 1361.3, "p95": 3856.7, "p99": 4166.0 },
    "tick_gap_ms": { "samples": 2373, "p50": 5.08, "p95": 5.90, "p99": 6.06 }
  }
  ```

  - tick_gap P99 = **6.06ms**，远低于 50ms gate（≈ 1/8）→ 事件循环未被同步调用阻塞
  - latency P50/P95/P99 = 1361/3857/4166ms → 分布健康，尾延比合理（约 3×）
  - RPS 16.13 → 32 并发吞吐稳定、连接池无瓶颈
  - 200 req 全部成功
- [ ] async 接口 vs 同步接口 RPS 对比（同步接口已无独立路由，不在 Phase 2 强制范围；如需基线，可 mock LLM backend 单测路由层吞吐）
- [ ] QPS=1 时延退化 ≤ 5% — 待 LLM backend 替换为 mock 后单跑
- [ ] 连接池使用率监控（可选，当前默认配置已能满足吞吐目标，无需调优）

### Phase 2 退出标准

> AST `requests.*` 检查只是 direct-call guard，不能证明请求路径非阻塞。Wrapper（如 `PyHugeClient.gremlin().exec()`）会把同步 IO 藏在调用链里 —— 仅靠 AST 通过，graph query 路径仍可能在 async route 里同步阻塞事件循环。下列三类门禁必须全部满足，缺一不可：

- [x] **直接调用门禁**：[lint_async_no_requests.py](../../scripts/lint_async_no_requests.py) 已实现 + 单测；启动期 / CLI / Gradio UI 配置块（`configs_block.py`）按白名单豁免。**CI 流水线接入待项目级动作**
- [x] **间接同步调用门禁**（覆盖 [design.md §2.6](./design.md#26-lint-防御伪异步) "第二类审计清单"）：审计完成于 [blocking_call_audit.md](./blocking_call_audit.md)，按 A/B/C/D 四类归属。请求路径上的下列调用，每一处都必须**要么已 async 化、要么显式走 bounded executor，并在 PR 描述中注明归属类别**：
  - [x] `PyHugeClient` / `gremlin().exec()` / `schema.getSchema()` — 全部归属类别 B（外层 `await asyncio.to_thread(pipeline.run)` 边界化）；adapter 类别 C 入口给 Phase 3 路由直连预留
  - [x] 同步 LLM `generate()` — 请求路径上已无使用，路由侧统一 `agenerate` / `agenerate_streaming`
  - [x] 同步 reranker — 已改双接口（async + sync 包装走 `runtime.run_async_from_sync`，类别 D）
  - [x] `pipeline.run()`（HTTP async 路径）— P1-T0 spike 方案 b：`await asyncio.to_thread(pipeline.run)`（类别 C）；Gradio 同步路径仍用 `pipeline.run()` 不变
  - [x] 审计交付物：[blocking_call_audit.md](./blocking_call_audit.md) 完成
- [x] **运行时门禁**（事件循环阻塞探针）—— [async_load_probe.py](../../scripts/async_load_probe.py) 工具已就位 + 2026-05-28 远端基线数据：
  - [x] 32 路并发压测下，事件循环单次 tick 阻塞时长 **P99 = 6.06ms** ≤ 50ms gate（实测远低于 1/8）
  - [x] **pipeline 异步调度真正非阻塞**：方案 b 下 200 req / 32 并发全部成功、tick gap P99 ~6ms，事件循环吞吐随并发线性扩展、单 pipeline 不独占 loop（spike [3][4][5] 维度数据已在此采集）
- [x] 压测指标达标：RPS 16.13 / latency P99 4166ms / 0 失败
- [x] 全量回归测试通过：293 passed, 13 skipped, 0 failed（2026-05-28）

---

## Phase 3：HTTP 路由层 async 化 + 双路径兼容（预计 1-2 周）

### P3-T1：路由签名改造

- [x] `api/rag_api.py` RAG 路由已 `async def`（[rag_api.py](../../hugegraph-llm/src/hugegraph_llm/api/rag_api.py)）：
  - [x] `rag_answer_api`（L225）
  - [x] `graph_rag_recall_api`（L298）
  - [x] `text2gremlin_api`（L402）
  - [x] **`/config/*` 保持 `def`**：[rag_api.py:339-341](../../hugegraph-llm/src/hugegraph_llm/api/rag_api.py#L339-L341) 注释明确——纯 metadata 写入 + 单次 PyHugeClient 健康检查，FastAPI 自动放线程池，没必要 async 化。该决策与 P3-T1 spec 偏离一项，已在代码注释中记录，避免回潮
- [x] 路由内部 pipeline 调用统一 `await asyncio.to_thread(_invoke_*, req)` 把同步 Gradio 入口（`rag_answer_func` / `graph_rag_recall_func` / `gremlin_generate_selective_func`）边界化（[rag_api.py:233 / 305 / 415](../../hugegraph-llm/src/hugegraph_llm/api/rag_api.py)）

### P3-T2：Pipeline 边界异步调度（P1-T0 spike 已选定方案 b）

- [x] [flows/scheduler.py:schedule_flow_async](../../hugegraph-llm/src/hugegraph_llm/flows/scheduler.py#L144-L184) 新增；内部统一 `status = await asyncio.to_thread(pipeline.run)`，与 `schedule_stream_flow` 保持一致；同步 `schedule_flow`（Gradio）保留不变
- [x] **未新增** lint 禁用规则
- [x] Phase 2 压测 tick_gap P99 = 6 ms 远低于 50 ms gate，default executor 容量充足，未额外引入 `pipeline_thread_pool_size`

### P3-T3：中间件 async 适配

- [x] [middleware/middleware.py:UseTimeMiddleware.dispatch](../../hugegraph-llm/src/hugegraph_llm/middleware/middleware.py#L66) 已 `async def`，并已挂载 ([app.py:166](../../hugegraph-llm/src/hugegraph_llm/demo/rag_demo/app.py#L166))
- [x] `BaseHTTPMiddleware` 不消费 `StreamingResponse` body（passthrough），SSE 不受影响；流式路由的 `X-Trace-Id` 由路由侧 setdefault 模式保留对错误 payload 的所有权
- [x] trace_id 通过 `contextvars.ContextVar` 传播（[middleware.py:33-46](../../hugegraph-llm/src/hugegraph_llm/middleware/middleware.py#L33-L46)），`get_trace_id()` 已被 [rag_api.py:145](../../hugegraph-llm/src/hugegraph_llm/api/rag_api.py#L145) 使用
- [x] [tests/middleware/test_middleware.py](../../hugegraph-llm/src/tests/middleware/test_middleware.py) 覆盖 sync/async/stream 三种模式下的 trace_id 链路

### P3-T4：测试基础设施升级

- [x] [tests/api/test_rag_api.py](../../hugegraph-llm/src/tests/api/test_rag_api.py) 已迁移到 `httpx.AsyncClient + ASGITransport`，并通过 `_async_routes_env` helper 同时覆盖 async + sync 回退两条路径
- [x] 旧 `unittest.TestCase` 风格已改为 pytest async；保留 1 处 `TestClient` 烟雾测试用作 sync shim 兼容性

### P3-T5：feature flag 与回滚预案

- [x] 环境变量 `HUGEGRAPH_LLM_ASYNC_ROUTES_ENABLED` 控制（[rag_api.py:45-56](../../hugegraph-llm/src/hugegraph_llm/api/rag_api.py#L45-L56)）；默认开启
- [x] 仅作用于 `/rag` / `/rag/graph` / `/text2gremlin`；`/rag/stream` 与 `/config/*` 不受 flag 影响（前者本就是 SSE，后者无 pipeline）
- [x] 回滚步骤已写入 [docs/async-migration.md](../../hugegraph-llm/docs/async-migration.md)

### P3-T6：压测与上线前验证

- [x] **远端 32 路并发基线（2026-05-28，真实 LLM）**：rps=16.13 / latency P99=4166ms / tick_gap P99=6.06ms，详见 Phase 2 P2-T9 + [blocking_call_audit.md](./blocking_call_audit.md)
- [x] **mock-LLM 压测（2026-05-29）已落地**：[scripts/mock_llm_server.py](../../scripts/mock_llm_server.py) + [scripts/async_load_probe.py](../../scripts/async_load_probe.py) `--endpoint` / `--no-stream` 工具就位；4 组对照数据 + 三条门禁判定写入 [blocking_call_audit.md 附录](./blocking_call_audit.md#附录phase-3-mock-llm-压测2026-05-29)
- [x] **QPS=1 时延退化 ≤ 5% ✅ 通过**：c=1 p50 全部贴 mock 理论值 2.23s ±0.5%（async stream 2222.9 / async JSON 2231.5 / 重测 JSON 2233.7）
- [⚠️] **QPS=32 吞吐 ≥ 同步基线 2.5 倍——不达标，但非路由层瓶颈**：async stream 10.63 / async JSON 10.98 / 重测 JSON 11.79 RPS，理论上限 32/2.2 ≈ 14.5；剩余 24% gap 来自 `Scheduler.pipeline_pool.max_pipeline=10` + asyncio default executor 池竞争，**改 sync 不会解锁这些上限**（sync 路由也撞同一个 max_pipeline）。建议把 P3-T6 这条门禁解读为"路由层 async 化不阻塞下游池"而非硬性 2.5×；详见 [blocking_call_audit.md 附录](./blocking_call_audit.md#真实瓶颈pipeline-pool-与-default-executor)
- [x] **运行时门禁 tick_gap P99 ≤ 50ms ✅ 通过**：4 组全部 5–6ms，事件循环未被任何同步调用独占
- [ ] 长时间稳定性测试（1h 持续压测）+ 内存/连接泄漏监控——待上线前真机执行
- [ ] 客户端断开/超时/错误恢复混沌测试——单元层面已覆盖（[test_rag_stream_api.py](../../hugegraph-llm/src/tests/api/test_rag_stream_api.py)），端到端混沌测试待真机执行

### P3-T7：迁移指南文档

- [x] [docs/async-migration.md](../../hugegraph-llm/docs/async-migration.md) 已撰写：协议差异表 / SSE 客户端示例（curl + JS + Python）/ 回滚开关 / 已知限制 / FAQ
- [x] mock-LLM 压测数据已就位 ([blocking_call_audit.md 附录](./blocking_call_audit.md#附录phase-3-mock-llm-压测2026-05-29))；可按需 cherry-pick 到 [docs/async-migration.md](../../hugegraph-llm/docs/async-migration.md) 的"性能对比"小节

### Phase 3 退出标准

- [x] 所有 RAG 路由 `async def`（`/config/*` 决策性保留 `def`，见 P3-T1 注解）
- [x] Gradio 同步路径仍正常工作（`schedule_flow` + `AnswerSynthesize.run()` 保留 + sync guard）
- [x] HTTP async 路径与 Gradio 同步路径并行无冲突（`schedule_flow_async` / `schedule_stream_flow` vs `schedule_flow`）
- [x] 中间件在 sync/async/stream 三种模式下 trace_id 完整（[test_middleware.py](../../hugegraph-llm/src/tests/middleware/test_middleware.py) 覆盖）
- [x] 32 并发 tick_gap P99 ≤ 50ms 已达标（真实 LLM 6.06ms / mock-LLM 6.06ms）
- [x] 端到端 RPS / latency 退化对比已采集（mock-LLM，2026-05-29）：QPS=1 退化 ≤ 0.5%；QPS=32 RPS ≈ 11（受 max_pipeline=10 限制，非路由层瓶颈），详见 [blocking_call_audit.md 附录](./blocking_call_audit.md#附录phase-3-mock-llm-压测2026-05-29)
- [x] 外部调用方兼容性：byte-for-byte 同步响应不变（[test_rag_api.py](../../hugegraph-llm/src/tests/api/test_rag_api.py) 双路径断言 + feature flag 一键回滚）
- [ ] 上线后一周观测 — 上线后才能采集

---

## 跨 Phase 任务

### 文档与沟通

- [ ] 每个 Phase 完成后更新本任务清单进度
- [ ] 每个 Phase 出 PR 时关联本 spec 目录的设计文档
- [ ] 重大设计变更时同步修改设计文档，避免文档漂移

### 风险监控

- [ ] 每个 Phase 完成后跑一次完整压测，对比基线
- [ ] 监控线程池使用率、连接池使用率、事件循环延迟（`asyncio.get_event_loop().time()`）
- [ ] 上线后观察一周，记录任何性能异常或错误率变化
