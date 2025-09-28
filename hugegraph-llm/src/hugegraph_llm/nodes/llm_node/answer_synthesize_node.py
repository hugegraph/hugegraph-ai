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

from typing import Dict, Any
from hugegraph_llm.nodes.base_node import BaseNode
from hugegraph_llm.operators.llm_op.answer_synthesize import AnswerSynthesize
from hugegraph_llm.utils.log import log


class AnswerSynthesizeNode(BaseNode):
    """
    答案合成节点，负责基于检索结果生成最终答案
    """

    operator: AnswerSynthesize

    def __init__(self):
        super().__init__()
        self.operator = None

    def node_init(self):
        """
        初始化答案合成算子
        """
        try:
            prompt_template = self.wk_input.answer_prompt
            raw_answer = self.wk_input.raw_answer or False
            vector_only_answer = self.wk_input.vector_only_answer or False
            graph_only_answer = self.wk_input.graph_only_answer or False
            graph_vector_answer = self.wk_input.graph_vector_answer or False

            self.operator = AnswerSynthesize(
                prompt_template=prompt_template,
                raw_answer=raw_answer,
                vector_only_answer=vector_only_answer,
                graph_only_answer=graph_only_answer,
                graph_vector_answer=graph_vector_answer,
            )
            return super().node_init()
        except Exception as e:
            log.error(f"Failed to initialize AnswerSynthesizeNode: {e}")
            from PyCGraph import CStatus

            return CStatus(-1, f"AnswerSynthesizeNode initialization failed: {e}")

    def operator_schedule(self, data_json: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行答案合成操作
        """
        try:
            # 执行答案合成
            result = self.operator.run(data_json)

            # 记录生成的答案类型
            answer_types = []
            if result.get("raw_answer"):
                answer_types.append("raw")
            if result.get("vector_only_answer"):
                answer_types.append("vector_only")
            if result.get("graph_only_answer"):
                answer_types.append("graph_only")
            if result.get("graph_vector_answer"):
                answer_types.append("graph_vector")

            log.info(f"Answer synthesis completed for types: {', '.join(answer_types)}")

            # 根据self.wk_input中的对应配置打印answer type
            wk_input_types = []
            if getattr(self.wk_input, "raw_answer", False):
                wk_input_types.append("raw")
            if getattr(self.wk_input, "vector_only_answer", False):
                wk_input_types.append("vector_only")
            if getattr(self.wk_input, "graph_only_answer", False):
                wk_input_types.append("graph_only")
            if getattr(self.wk_input, "graph_vector_answer", False):
                wk_input_types.append("graph_vector")
            log.info(
                f"根据wk_input配置，启用的answer type有: {', '.join(wk_input_types)}"
            )
            return result

        except Exception as e:
            log.error(f"Answer synthesis failed: {e}")
            return data_json
