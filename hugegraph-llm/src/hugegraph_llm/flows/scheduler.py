#  Licensed to the Apache Software Foundation (ASF) under one or more
#  contributor license agreements.  See the NOTICE file distributed with
#  this work for additional information regarding copyright ownership.
#  The ASF licenses this file to You under the Apache License, Version 2.0
#  (the "License"); you may not use this file except in compliance with
#  the License.  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.

import asyncio
import threading
from typing import Any, Dict

from pycgraph import GPipeline, GPipelineManager

from hugegraph_llm.flows import FlowName
from hugegraph_llm.flows.build_example_index import BuildExampleIndexFlow
from hugegraph_llm.flows.build_schema import BuildSchemaFlow
from hugegraph_llm.flows.build_vector_index import BuildVectorIndexFlow
from hugegraph_llm.flows.common import BaseFlow
from hugegraph_llm.flows.get_graph_index_info import GetGraphIndexInfoFlow
from hugegraph_llm.flows.graph_extract import GraphExtractFlow
from hugegraph_llm.flows.import_graph_data import ImportGraphDataFlow
from hugegraph_llm.flows.prompt_generate import PromptGenerateFlow
from hugegraph_llm.flows.rag_flow_graph_only import RAGGraphOnlyFlow
from hugegraph_llm.flows.rag_flow_graph_vector import RAGGraphVectorFlow
from hugegraph_llm.flows.rag_flow_raw import RAGRawFlow
from hugegraph_llm.flows.rag_flow_vector_only import RAGVectorOnlyFlow
from hugegraph_llm.flows.text2gremlin import Text2GremlinFlow
from hugegraph_llm.flows.update_vid_embeddings import UpdateVidEmbeddingsFlow
from hugegraph_llm.state.ai_state import WkFlowInput
from hugegraph_llm.utils.log import log


class Scheduler:
    pipeline_pool: Dict[str, Any]
    max_pipeline: int

    def __init__(self, max_pipeline: int = 10):
        self.pipeline_pool = {}
        # pipeline_pool act as a manager of GPipelineManager which used for pipeline management
        self.pipeline_pool[FlowName.BUILD_VECTOR_INDEX] = {
            "manager": GPipelineManager(),
            "flow": BuildVectorIndexFlow(),
        }
        self.pipeline_pool[FlowName.GRAPH_EXTRACT] = {
            "manager": GPipelineManager(),
            "flow": GraphExtractFlow(),
        }
        self.pipeline_pool[FlowName.IMPORT_GRAPH_DATA] = {
            "manager": GPipelineManager(),
            "flow": ImportGraphDataFlow(),
        }
        self.pipeline_pool[FlowName.UPDATE_VID_EMBEDDINGS] = {
            "manager": GPipelineManager(),
            "flow": UpdateVidEmbeddingsFlow(),
        }
        self.pipeline_pool[FlowName.GET_GRAPH_INDEX_INFO] = {
            "manager": GPipelineManager(),
            "flow": GetGraphIndexInfoFlow(),
        }
        self.pipeline_pool[FlowName.BUILD_SCHEMA] = {
            "manager": GPipelineManager(),
            "flow": BuildSchemaFlow(),
        }
        self.pipeline_pool[FlowName.PROMPT_GENERATE] = {
            "manager": GPipelineManager(),
            "flow": PromptGenerateFlow(),
        }
        self.pipeline_pool[FlowName.TEXT2GREMLIN] = {
            "manager": GPipelineManager(),
            "flow": Text2GremlinFlow(),
        }
        # New split rag pipelines
        self.pipeline_pool[FlowName.RAG_RAW] = {
            "manager": GPipelineManager(),
            "flow": RAGRawFlow(),
        }
        self.pipeline_pool[FlowName.RAG_VECTOR_ONLY] = {
            "manager": GPipelineManager(),
            "flow": RAGVectorOnlyFlow(),
        }
        self.pipeline_pool[FlowName.RAG_GRAPH_ONLY] = {
            "manager": GPipelineManager(),
            "flow": RAGGraphOnlyFlow(),
        }
        self.pipeline_pool[FlowName.RAG_GRAPH_VECTOR] = {
            "manager": GPipelineManager(),
            "flow": RAGGraphVectorFlow(),
        }
        self.pipeline_pool[FlowName.BUILD_EXAMPLES_INDEX] = {
            "manager": GPipelineManager(),
            "flow": BuildExampleIndexFlow(),
        }
        self.max_pipeline = max_pipeline

    # TODO: Implement Agentic Workflow
    def agentic_flow(self):
        pass

    def schedule_flow(self, flow_name: str, *args, **kwargs):
        if flow_name not in self.pipeline_pool:
            raise ValueError(f"Unsupported workflow {flow_name}")
        manager: GPipelineManager = self.pipeline_pool[flow_name]["manager"]
        flow: BaseFlow = self.pipeline_pool[flow_name]["flow"]
        pipeline: GPipeline = manager.fetch()
        if pipeline is None:
            # call coresponding flow_func to create new workflow
            pipeline = flow.build_flow(*args, **kwargs)
            status = pipeline.init()
            if status.isErr():
                error_msg = f"Error in flow init: {status.getInfo()}"
                log.error(error_msg)
                raise RuntimeError(error_msg)
            status = pipeline.run()
            if status.isErr():
                manager.add(pipeline)
                error_msg = f"Error in flow execution: {status.getInfo()}"
                log.error(error_msg)
                raise RuntimeError(error_msg)
            res = flow.post_deal(pipeline)
            manager.add(pipeline)
            return res
        try:
            # fetch pipeline & prepare input for flow
            prepared_input = pipeline.getGParamWithNoEmpty("wkflow_input")
            flow.prepare(prepared_input, *args, **kwargs)
            status = pipeline.run()
            if status.isErr():
                error_msg = f"Error in flow execution {status.getInfo()}"
                log.error(error_msg)
                raise RuntimeError(error_msg)
            res = flow.post_deal(pipeline)
        finally:
            manager.release(pipeline)
        return res

    async def schedule_flow_async(self, flow_name: str, *args, **kwargs):
        """非流式异步调度入口（HTTP async 路径，Phase 3 P3-T2）。

        与 :meth:`schedule_flow` 等价，但把同步 ``pipeline.run()`` 推到默认线程池
        执行（``await asyncio.to_thread(pipeline.run)``，与 P1-T0 spike 选定方案 b
        保持一致），保证事件循环不被独占。Gradio 同步路径仍调用 :meth:`schedule_flow`。
        """
        if flow_name not in self.pipeline_pool:
            raise ValueError(f"Unsupported workflow {flow_name}")
        manager: GPipelineManager = self.pipeline_pool[flow_name]["manager"]
        flow: BaseFlow = self.pipeline_pool[flow_name]["flow"]
        pipeline: GPipeline = manager.fetch()
        if pipeline is None:
            pipeline = flow.build_flow(*args, **kwargs)
            status = pipeline.init()
            if status.isErr():
                error_msg = f"Error in flow init: {status.getInfo()}"
                log.error(error_msg)
                raise RuntimeError(error_msg)
            try:
                status = await asyncio.to_thread(pipeline.run)
                if status.isErr():
                    error_msg = f"Error in flow execution: {status.getInfo()}"
                    log.error(error_msg)
                    raise RuntimeError(error_msg)
                res = flow.post_deal(pipeline)
            finally:
                manager.add(pipeline)
            return res
        try:
            prepared_input = pipeline.getGParamWithNoEmpty("wkflow_input")
            flow.prepare(prepared_input, *args, **kwargs)
            status = await asyncio.to_thread(pipeline.run)
            if status.isErr():
                error_msg = f"Error in flow execution {status.getInfo()}"
                log.error(error_msg)
                raise RuntimeError(error_msg)
            res = flow.post_deal(pipeline)
        finally:
            manager.release(pipeline)
        return res

    async def schedule_stream_flow(self, flow_name: str, *args, **kwargs):
        """流式调度入口（HTTP async 路径）。

        P1-T3：基于 P1-T0 spike 结论（pycgraph 3.2.4 上 ``GPipeline.asyncRun()`` 返回
        ``StdFutureCStatus``，**不是** Python awaitable，``wait()`` / ``get()`` 也是
        阻塞调用，详见 ``spec/async_streaming_api/pycgraph_async_spike.md``），采用
        **方案 b**：``await asyncio.to_thread(pipeline.run)`` 把同步 ``run()`` 推到
        线程池，保证事件循环不被独占。同步路径 :meth:`schedule_flow` 仍走同步
        ``pipeline.run()``，由 Gradio 等同步入口使用，互不影响。

        修复 BUG：原实现在 ``manager.fetch() is None`` 分支中漏写 ``return``，
        会让首次请求把 pipeline 跑两遍（一次走"新建分支"，一次走 try 块的"已存在
        分支"），LLM token 流被复发两遍。本次随同方案 b 落地一并补上。
        """
        if flow_name not in self.pipeline_pool:
            raise ValueError(f"Unsupported workflow {flow_name}")
        manager: GPipelineManager = self.pipeline_pool[flow_name]["manager"]
        flow: BaseFlow = self.pipeline_pool[flow_name]["flow"]
        pipeline: GPipeline = manager.fetch()
        if pipeline is None:
            # call coresponding flow_func to create new workflow
            pipeline = flow.build_flow(*args, **kwargs)
            pipeline.getGParamWithNoEmpty("wkflow_input").stream = True
            status = pipeline.init()
            if status.isErr():
                error_msg = f"Error in flow init: {status.getInfo()}"
                log.error(error_msg)
                raise RuntimeError(error_msg)
            status = await asyncio.to_thread(pipeline.run)
            if status.isErr():
                manager.add(pipeline)
                error_msg = f"Error in flow execution: {status.getInfo()}"
                log.error(error_msg)
                raise RuntimeError(error_msg)
            try:
                async for res in flow.post_deal_stream(pipeline):
                    yield res
            finally:
                manager.add(pipeline)
            return
        try:
            # fetch pipeline & prepare input for flow
            prepared_input: WkFlowInput = pipeline.getGParamWithNoEmpty("wkflow_input")
            prepared_input.stream = True
            flow.prepare(prepared_input, *args, **kwargs)
            status = await asyncio.to_thread(pipeline.run)
            if status.isErr():
                raise RuntimeError(f"Error in flow execution {status.getInfo()}")
            async for res in flow.post_deal_stream(pipeline):
                yield res
        finally:
            manager.release(pipeline)


class SchedulerSingleton:
    _instance = None
    _instance_lock = threading.Lock()

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = Scheduler()
        return cls._instance
