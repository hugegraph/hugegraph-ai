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

"""``rag_answer_streaming`` 检索参数透传契约测试。

阻塞项（review）：``rag_answer_streaming`` 必须把 4 个检索调参
（``max_graph_items`` / ``topk_return_results`` / ``vector_dis_threshold`` /
``topk_per_keyword``）透传给 ``schedule_stream_flow``，与 HTTP ``/rag`` /
``/rag/stream`` 路径保持语义等价。

Gradio UI 不暴露这些控件（始终使用默认值），但程序化调用者可以指定非默认值，
且若透传缺失则两条路径（HTTP vs Gradio streaming）在同一份参数下会产生不同的
召回 / 排序结果。
"""

import asyncio

import pytest


@pytest.mark.asyncio
async def test_rag_answer_streaming_passes_retrieval_params_to_scheduler(monkeypatch):
    """
    Blocker: rag_answer_streaming 透传 4 个检索调参到 schedule_stream_flow。

    使用非默认 sentinel 值（1234 / 77 / 0.42 / 9），避免"漏传 → 恰好命中全局
    默认值（30 / 20 / 0.9 / 1）"的误判。
    """
    from hugegraph_llm.demo.rag_demo import rag_block

    captured: dict = {}

    class _FakeScheduler:
        async def schedule_stream_flow(self, flow_key, **kwargs):
            captured.update(kwargs)
            captured["_flow_key"] = flow_key
            await asyncio.sleep(0)
            yield ("raw_answer", "ok")

    monkeypatch.setattr(
        rag_block.SchedulerSingleton,
        "get_instance",
        classmethod(lambda cls: _FakeScheduler()),
    )
    # 屏蔽 prompt YAML 落盘副作用
    monkeypatch.setattr(rag_block.prompt, "update_yaml_file", lambda: None)

    snapshots = []
    async for snap in rag_block.rag_answer_streaming(
        text="test question",
        raw_answer=True,
        vector_only_answer=False,
        graph_only_answer=False,
        graph_vector_answer=False,
        graph_ratio=0.6,
        rerank_method="bleu",
        near_neighbor_first=False,
        custom_related_information="",
        answer_prompt="answer prompt",
        keywords_extract_prompt="keywords extract prompt",
        gremlin_tmpl_num=-1,
        gremlin_prompt=None,
        # 非默认 sentinel 值
        max_graph_items=1234,
        topk_return_results=77,
        vector_dis_threshold=0.42,
        topk_per_keyword=9,
    ):
        snapshots.append(snap)

    assert captured.get("max_graph_items") == 1234, (
        f"max_graph_items 未透传到 schedule_stream_flow，captured={captured!r}"
    )
    assert captured.get("topk_return_results") == 77, f"topk_return_results 未透传，captured={captured!r}"
    assert captured.get("vector_dis_threshold") == pytest.approx(0.42), (
        f"vector_dis_threshold 未透传，captured={captured!r}"
    )
    assert captured.get("topk_per_keyword") == 9, f"topk_per_keyword 未透传，captured={captured!r}"
    # 至少产出了一次 snapshot
    assert snapshots, "rag_answer_streaming 未 yield 任何 snapshot"


@pytest.mark.asyncio
async def test_rag_answer_streaming_default_retrieval_params(monkeypatch):
    """
    当调用方不传检索调参时，schedule_stream_flow 收到的必须是明确的默认值
    （30 / 20 / 0.9 / 1），而不是 None（None 会让 flow 走不确定的 fallback 分支）。
    """
    from hugegraph_llm.demo.rag_demo import rag_block

    captured: dict = {}

    class _FakeScheduler:
        async def schedule_stream_flow(self, flow_key, **kwargs):
            captured.update(kwargs)
            await asyncio.sleep(0)
            yield ("raw_answer", "ok")

    monkeypatch.setattr(
        rag_block.SchedulerSingleton,
        "get_instance",
        classmethod(lambda cls: _FakeScheduler()),
    )
    monkeypatch.setattr(rag_block.prompt, "update_yaml_file", lambda: None)

    async for _ in rag_block.rag_answer_streaming(
        text="test",
        raw_answer=True,
        vector_only_answer=False,
        graph_only_answer=False,
        graph_vector_answer=False,
        graph_ratio=0.6,
        rerank_method="bleu",
        near_neighbor_first=False,
        custom_related_information="",
        answer_prompt="prompt",
        keywords_extract_prompt="kw prompt",
        # 不传 max_graph_items / topk_return_results / vector_dis_threshold / topk_per_keyword
    ):
        pass

    assert captured.get("max_graph_items") == 30, f"expected default 30, got {captured.get('max_graph_items')!r}"
    assert captured.get("topk_return_results") == 20, (
        f"expected default 20, got {captured.get('topk_return_results')!r}"
    )
    assert captured.get("vector_dis_threshold") == pytest.approx(0.9), (
        f"expected default 0.9, got {captured.get('vector_dis_threshold')!r}"
    )
    assert captured.get("topk_per_keyword") == 1, f"expected default 1, got {captured.get('topk_per_keyword')!r}"


@pytest.mark.asyncio
async def test_rag_answer_streaming_switch_to_bleu_warning_visible(monkeypatch):
    """
    reranker 降级时上游 yield 的 ``{"warning": ..., "switch_to_bleu": True}``
    控制消息必须经 accumulate wrapper 以 ``__events__`` 暴露给 demo 层，
    并触发 gr.Warning。这条路径与 HTTP SSE 的 ``event: warning`` 通道一起构成
    "降级可见性"保证。
    """
    import gradio as gr

    from hugegraph_llm.demo.rag_demo import rag_block

    warning_messages: list = []

    class _FakeScheduler:
        async def schedule_stream_flow(self, flow_key, **kwargs):
            await asyncio.sleep(0)
            yield ("raw_answer", "partial answer")
            yield {"warning": "Online reranker fails, switches to bleu.", "switch_to_bleu": True}
            yield ("raw_answer", " rest of answer")

    monkeypatch.setattr(
        rag_block.SchedulerSingleton,
        "get_instance",
        classmethod(lambda cls: _FakeScheduler()),
    )
    monkeypatch.setattr(rag_block.prompt, "update_yaml_file", lambda: None)
    # 捕获 gr.Warning 而不是让它向 Gradio server 发事件
    monkeypatch.setattr(gr, "Warning", lambda msg: warning_messages.append(msg))

    snapshots = []
    async for snap in rag_block.rag_answer_streaming(
        text="test",
        raw_answer=True,
        vector_only_answer=False,
        graph_only_answer=False,
        graph_vector_answer=False,
        graph_ratio=0.6,
        rerank_method="bleu",
        near_neighbor_first=False,
        custom_related_information="",
        answer_prompt="p",
        keywords_extract_prompt="kp",
    ):
        snapshots.append(snap)

    # gr.Warning 必须被调用一次（dedup 保证不会重复投递）
    assert warning_messages, "gr.Warning 未被调用，reranker 降级对 Gradio 不可见"
    assert any("bleu" in m.lower() for m in warning_messages), f"warning 内容不含 bleu 关键词: {warning_messages!r}"
    # 最终答案完整（warning 不破坏 token 拼接）
    assert snapshots, "rag_answer_streaming 未 yield 任何 snapshot"
    final = snapshots[-1]
    assert final.get("raw_answer") == "partial answer rest of answer", f"最终 raw_answer 文本不完整: {final!r}"
