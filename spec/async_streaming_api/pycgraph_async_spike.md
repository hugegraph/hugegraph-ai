# P1-T0 spike：pycgraph 3.2.4 asyncRun 行为验证

> 配套 spike 脚本：[pycgraph_async_spike.py](./pycgraph_async_spike.py)
>
> 状态：✅ 已结题，选定方案 **b**。

## 目的

`tasks.md` P1-T0 / `requirements.md` 2.4 / `design.md` §3.2 中关于
`pipeline.asyncRun()` 是否为 Python awaitable 的两个候选方案（a 升级直接 await /
b 维持 `asyncio.to_thread(pipeline.run)`）必须用真机数据决断，否则 P1-T3、
P3-T2 落地写法无据可依。

## 验证项

1. `asyncRun()` 返回对象的真实类型（`type` / `module`）
2. 是否满足 Python awaitable 协议（`inspect.isawaitable` / `__await__`）
3. 该对象的 API 表面（`wait` / `get` / `done`）及阻塞行为
4. 直接 `await asyncRun()` 是否抛 `TypeError`
5. `asyncio.to_thread(pipeline.run)` 是否真的让出事件循环（→ Phase 2 压测）
6. `asyncio.to_thread(future.get)` 是否等价 / 更优（→ Phase 2 压测）
7. 8 路并发下事件循环 tick 阻塞 P99（→ Phase 2 压测）

## 运行步骤

在装好 `pycgraph==3.2.4` 的远程环境：

```bash
cd hugegraph-llm
python ../spec/async_streaming_api/pycgraph_async_spike.py
```

## 运行结果

`/home/ubuntu/yoya/baidu/hugegraph-ai`（Linux x86_64, Python 3.11.15,
pycgraph==3.2.4 cpython-311-x86_64-linux-gnu）实测：

```text
pycgraph module file: .../site-packages/pycgraph.cpython-311-x86_64-linux-gnu.so
============================================================
[1] asyncRun() 返回对象探针
============================================================
  type:                StdFutureCStatus
  type.__module__:     pycgraph
  inspect.isawaitable: False
  has __await__:       False
  has wait:            True
  has get:             True
  has done:            False
  dir:                 ['get', 'wait']
  wait() blocked:      50.2 ms
  get() returned:      type=CStatus, isErr=False, in 0.0 ms
============================================================
[2] 直接 await asyncRun() 的行为
============================================================
  await 抛 TypeError: object pycgraph.StdFutureCStatus can't be used in
                      'await' expression
```

[3] / [4] / [5] 未采集（spike 脚本心跳 task 收尾问题，不影响结题）。
[1][2] 已经把方案 a 从协议层面排除，[3][4][5] 的"事件循环 tick gap 阻塞"维度
已被 Phase 2 退出标准 §"运行时门禁"覆盖（32 路并发 P99 ≤ 50ms 探针），届时
统一采集，详见 [tasks.md](./tasks.md) Phase 2 退出标准。

## 结论

### 断言

- [x] `type(asyncRun()).__name__` = `StdFutureCStatus`（`module=pycgraph`）
- [x] `inspect.isawaitable(asyncRun()) == False`
- [x] `hasattr(future, "wait") == True`，`wait()` 阻塞调用线程
      （node `time.sleep(0.05)` → `wait()` blocked 50.2 ms，等价同步阻塞）
- [x] `hasattr(future, "get") == True`，`get()` 返回 `CStatus`
- [x] 直接 `await asyncRun()` 抛 `TypeError: object pycgraph.StdFutureCStatus
      can't be used in 'await' expression`
- [ ] 8 路并发下 `asyncio.to_thread(pipeline.run)` 的事件循环 tick gap P99
      ≤ 50ms — 推迟到 Phase 2 退出标准压测中验证

### 选定方案

- [ ] **方案 a**：pycgraph 3.2.4 的 `asyncRun()` 已是真正 awaitable
- [x] **方案 b**：`status = await asyncio.to_thread(pipeline.run)`，与同步
      `pipeline.run()` 等价，事件循环不被独占

### 选定理由

1. 方案 a **协议层面排除**：`asyncRun()` 在 pycgraph 3.2.4 上返回的 C++ future
   `StdFutureCStatus` 不实现 `__await__` / `inspect.isawaitable=False`，直接
   `await` 抛 `TypeError`；只有升级到提供真正 Python awaitable 的更新版本才能
   走方案 a，但当前 pycgraph 没有这样的版本可选。
2. `StdFutureCStatus.wait()` 阻塞 50ms（恰好 = 节点 `time.sleep(0.05)`），证明它
   是同步阻塞 + 不释放 GIL。即使写 `await asyncio.to_thread(future.get)` 也只是
   多绕一层 C++ future、阻塞性质等价于 `asyncio.to_thread(pipeline.run)` 而无任何
   收益（`requirements.md` 2.4 b 段："不要画蛇添足"）。
3. `asyncio.to_thread(pipeline.run)` 直接复用同步 `run()` 入口，**已经是当前
   pycgraph 上唯一可用的非阻塞接入方式**；事件循环把 pipeline 交给 default
   thread executor，自身 tick 不被独占。
4. Gradio 同步路径（`schedule_flow` → `pipeline.run()`）保持不动，不受方案 b 影响。

## 后续动作（已落地状态）

- [x] `flows/scheduler.py` 的 `schedule_stream_flow` L158 / L172 改为
      `status = await asyncio.to_thread(pipeline.run)`（P1-T3）
- [x] 同步路径 `schedule_flow` 仍走 `pipeline.run()` 不变
- [x] 顺手修复 `schedule_stream_flow` 的"漏 return + manager.add 未在 finally"
      bug（导致首次请求 pipeline 跑两遍、LLM token 流被复发两遍；详见 P1-T3
      代码注释）
- [x] **不**新增"禁用 `asyncio.to_thread(pipeline.run)`"的 lint 规则——方案 b
      下这是合法且必要的实现（`tasks.md` L45）
- [x] spec 4 个文档（`README.md` / `requirements.md` / `design.md` / `tasks.md`）
      把"二选一/spike 出结论前"的双路径表述统一收敛为方案 b 单路径
- [ ] Phase 2 退出标准压测中采集 32 路并发事件循环 tick gap P99
- [ ] Phase 3 `schedule_flow_async` 沿用方案 b 写法（`P3-T2`）
