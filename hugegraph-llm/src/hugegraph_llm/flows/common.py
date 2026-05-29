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

from abc import ABC, abstractmethod
from typing import Any, AsyncGenerator, Dict

from hugegraph_llm.state.ai_state import WkFlowInput
from hugegraph_llm.utils.log import log


class BaseFlow(ABC):
    """
    Base class for flows, defines three interface methods: prepare, build_flow, and post_deal.
    """

    @abstractmethod
    def prepare(self, prepared_input: WkFlowInput, **kwargs):
        """
        Pre-processing interface.
        """

    @abstractmethod
    def build_flow(self, **kwargs):
        """
        Interface for building the flow.
        """

    @abstractmethod
    def post_deal(self, **kwargs):
        """
        Post-processing interface.
        """

    async def post_deal_stream(self, pipeline=None) -> AsyncGenerator[Any, None]:
        """
        Streaming post-processing interface.
        Subclasses can override this method as needed.

        Stream item contract（V1，详见 ``api/chat_completion_adapter.py``
        模块 docstring）：先把任何"非 token 状态"（warning / error / metadata）
        以 dict 形式 yield 出来，再透传 LLM token tuple。这样下游 SSE adapter
        与 Gradio ``accumulate`` wrapper 都能用同一套 contract 消费上游事件，
        避免外部 reranker 失败之类的降级被静默吞掉（见 review）。
        """
        flow_name = self.__class__.__name__
        if pipeline is None:
            yield {"error": "No pipeline provided"}
            return
        state_json = pipeline.getGParamWithNoEmpty("wkflow_state").to_json()
        log.info("%s post processing success", flow_name)

        # 把非 token 控制 / 元数据先发出，避免 token 流启动后这些状态被埋没。
        if state_json.get("switch_to_bleu"):
            yield {
                "warning": ("Online reranker fails, automatically switches to local bleu rerank."),
                "switch_to_bleu": True,
            }

        stream_flow = state_json.get("stream_generator")
        if stream_flow is None:
            yield {"error": "No stream_generator found in workflow state"}
            return
        async for chunk in stream_flow:
            yield chunk
