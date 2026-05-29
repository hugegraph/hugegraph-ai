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

"""``Scheduler.schedule_stream_flow`` cold path 回归测试（review 阻塞项）。

review 提到："cold path 中 ``pipeline.run`` 在进入 ``manager.add(pipeline)`` 之前
执行；首次流式请求若在 ``await asyncio.to_thread(pipeline.run)`` 期间被取消，
刚 ``build_flow`` 出来的 pipeline 不会归还到 ``GPipelineManager``，会造成资源泄漏。"

本测试通过把 ``manager.fetch`` mock 成返回 ``None``（强制走 cold path），同时把
``pipeline.run`` 替换成"等到被 cancel"，验证 ``manager.add`` 仍然被调用。
"""

import asyncio

import pytest

from hugegraph_llm.flows.scheduler import Scheduler


class _FakeStatus:
    def isErr(self):
        return False

    def getInfo(self):
        return ""


class _FakePipeline:
    """一个最小可用的 pipeline 替身：``init`` 立即返回 OK，``run`` 永远阻塞，
    直到外层 task 被取消时由 ``asyncio.to_thread`` 抛 ``CancelledError`` 出来。"""

    def __init__(self):
        self.run_called = False

    def init(self):
        return _FakeStatus()

    def run(self):
        # ``asyncio.to_thread(pipeline.run)`` 把这个调用扔到默认线程池；
        # 我们用一个跨线程 ``threading.Event`` 让它"卡住"足够久，主协程 cancel
        # 时 ``await`` 那一侧会先 raise CancelledError。
        import threading

        self.run_called = True
        threading.Event().wait(timeout=2.0)  # 限时兜底，避免泄漏线程
        return _FakeStatus()

    def getGParamWithNoEmpty(self, _name):
        class _Stub:
            stream = False

        return _Stub()


class _FakeFlow:
    def build_flow(self, **_kwargs):
        return _FakePipeline()


class _CountingManager:
    """记录 ``add`` / ``release`` 调用次数 —— cold path 下应当 ``add``。"""

    def __init__(self):
        self.add_count = 0
        self.release_count = 0
        self.added_pipelines = []

    def fetch(self):
        return None  # 强制 cold path

    def add(self, pipeline):
        self.add_count += 1
        self.added_pipelines.append(pipeline)

    def release(self, _pipeline):
        self.release_count += 1


@pytest.mark.asyncio
async def test_cold_path_cancellation_returns_pipeline_to_manager():
    """阻塞项：cold path 期间 cancel 必须把 pipeline 归还到 manager。"""
    scheduler = Scheduler()
    manager = _CountingManager()
    flow = _FakeFlow()
    # 替换某个已注册 flow_name 的 manager / flow 为 fake。
    flow_name = next(iter(scheduler.pipeline_pool.keys()))
    scheduler.pipeline_pool[flow_name] = {"manager": manager, "flow": flow}

    async def _consume():
        # 必须 ``async for`` 才能驱动 generator 进入 cold path 的 await。
        async for _ in scheduler.schedule_stream_flow(flow_name):
            pass

    task = asyncio.create_task(_consume())
    # 让 task 跑到 await asyncio.to_thread(pipeline.run) 那一步，再 cancel。
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises((asyncio.CancelledError, BaseException)):
        await task

    assert manager.add_count == 1, (
        f"cold path 取消时 pipeline 未归还到 manager (add_count={manager.add_count}); "
        "此乃 review 阻塞项 —— 资源泄漏会在高并发取消下消耗完池容量。"
    )
