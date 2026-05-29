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
P1-T0 spike: 验证 pycgraph 3.2.4 上 GPipeline.asyncRun() 的真实返回类型与可用语义。

运行方式（在装好 pycgraph==3.2.4 的远程环境）：
    cd hugegraph-llm
    python ../spec/async_streaming_api/pycgraph_async_spike.py

预期产出：
  1) asyncRun() 返回对象的 type / module / dir
  2) inspect.isawaitable / __await__ / wait / get 是否存在
  3) wait() / get() 是否阻塞、阻塞耗时
  4) asyncio 事件循环里 await asyncio.to_thread(future.get) 是否真的让出 GIL
  5) asyncio.to_thread(pipeline.run) 与 asyncio.to_thread(future.get) 的对比

把 stdout 全部拷贝到 spec/async_streaming_api/pycgraph_async_spike.md 的"运行结果"小节，
然后填入"选定方案"。
"""

import asyncio
import inspect
import threading
import time

import pycgraph
from pycgraph import CStatus, GNode, GPipeline


class NoopNode(GNode):
    """最小可执行节点：sleep 50ms 后返回 OK"""

    def init(self):
        return CStatus()

    def run(self):
        time.sleep(0.05)
        return CStatus()


def build_pipeline() -> GPipeline:
    p = GPipeline()
    n = NoopNode()
    p.registerGElement(n, set(), "noop")
    s = p.init()
    if s.isErr():
        raise RuntimeError(f"pipeline init failed: {s.getInfo()}")
    return p


def probe_async_run_return():
    print("=" * 60)
    print("[1] asyncRun() 返回对象探针")
    print("=" * 60)
    p = build_pipeline()
    ret = p.asyncRun()
    print(f"  type:                {type(ret).__name__}")
    print(f"  type.__module__:     {type(ret).__module__}")
    print(f"  inspect.isawaitable: {inspect.isawaitable(ret)}")
    print(f"  has __await__:       {hasattr(ret, '__await__')}")
    print(f"  has wait:            {hasattr(ret, 'wait')}")
    print(f"  has get:             {hasattr(ret, 'get')}")
    print(f"  has done:            {hasattr(ret, 'done')}")
    print(f"  dir:                 {[m for m in dir(ret) if not m.startswith('_')]}")

    if hasattr(ret, "wait"):
        t0 = time.time()
        ret.wait()
        print(f"  wait() blocked:      {(time.time() - t0) * 1000:.1f} ms")

    if hasattr(ret, "get"):
        t0 = time.time()
        s = ret.get()
        print(
            f"  get() returned:      type={type(s).__name__}, "
            f"isErr={s.isErr() if hasattr(s, 'isErr') else 'n/a'}, "
            f"in {(time.time() - t0) * 1000:.1f} ms"
        )
    p.destroy()


def probe_direct_await():
    print("=" * 60)
    print("[2] 直接 await asyncRun() 的行为（预期可能 TypeError）")
    print("=" * 60)
    p = build_pipeline()

    async def _try():
        ret = p.asyncRun()
        try:
            r = await ret  # 期望此处 raise TypeError 当 ret 不是 awaitable
            print(f"  await 成功，返回 {type(r).__name__}")
            return "AWAITABLE"
        except TypeError as e:
            print(f"  await 抛 TypeError: {e}")
            return "NOT_AWAITABLE"

    result = asyncio.run(_try())
    print(f"  conclusion: {result}")
    p.destroy()


def probe_to_thread_pipeline_run():
    print("=" * 60)
    print("[3] asyncio.to_thread(pipeline.run) — 方案 b 主路径")
    print("=" * 60)
    p = build_pipeline()

    async def _go():
        loop_thread_id = threading.get_ident()
        t0 = time.time()
        s = await asyncio.to_thread(p.run)
        print(f"  to_thread(pipeline.run) elapsed: {(time.time() - t0) * 1000:.1f} ms")
        print(f"  status isErr={s.isErr()}, info={s.getInfo()!r}")
        print(f"  loop thread id at start: {loop_thread_id}")

    asyncio.run(_go())
    p.destroy()


def probe_to_thread_future_get():
    print("=" * 60)
    print("[4] asyncio.to_thread(future.get) — asyncRun + 推线程池")
    print("=" * 60)
    p = build_pipeline()

    async def _go():
        ret = p.asyncRun()
        if not hasattr(ret, "get"):
            print("  future 无 get 方法，跳过")
            return
        t0 = time.time()
        s = await asyncio.to_thread(ret.get)
        print(f"  to_thread(future.get) elapsed: {(time.time() - t0) * 1000:.1f} ms")
        print(f"  status isErr={s.isErr() if hasattr(s, 'isErr') else 'n/a'}")

    asyncio.run(_go())
    p.destroy()


def probe_event_loop_blocking():
    """并发若干次 pipeline 执行，看事件循环是否被独占。"""
    print("=" * 60)
    print("[5] 事件循环阻塞探针：8 路并发 + 心跳 task")
    print("=" * 60)
    pipelines = [build_pipeline() for _ in range(8)]

    async def heartbeat(stop_evt: asyncio.Event, gaps: list):
        last = asyncio.get_event_loop().time()
        while not stop_evt.is_set():
            await asyncio.sleep(0.005)
            now = asyncio.get_event_loop().time()
            gaps.append((now - last) * 1000)
            last = now

    async def _run_one(p):
        await asyncio.to_thread(p.run)

    async def _go():
        gaps = []
        stop = asyncio.Event()
        hb = asyncio.create_task(heartbeat(stop, gaps))
        t0 = time.time()
        await asyncio.gather(*(_run_one(p) for p in pipelines))
        elapsed = (time.time() - t0) * 1000
        stop.set()
        await hb
        gaps.sort()
        p99 = gaps[int(len(gaps) * 0.99)] if gaps else 0.0
        p_max = gaps[-1] if gaps else 0.0
        print(f"  total elapsed:       {elapsed:.1f} ms")
        print(f"  loop tick gap p99:   {p99:.2f} ms (target ≤ 50ms)")
        print(f"  loop tick gap max:   {p_max:.2f} ms")
        print(f"  loop tick samples:   {len(gaps)}")

    asyncio.run(_go())
    for p in pipelines:
        p.destroy()


def main():
    print(f"pycgraph module file: {pycgraph.__file__}")
    probe_async_run_return()
    probe_direct_await()
    probe_to_thread_pipeline_run()
    probe_to_thread_future_get()
    probe_event_loop_blocking()
    print("=" * 60)
    print("spike done — 把以上输出粘到 pycgraph_async_spike.md")
    print("=" * 60)


if __name__ == "__main__":
    main()
