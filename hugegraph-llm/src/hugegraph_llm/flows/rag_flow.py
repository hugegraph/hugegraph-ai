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

from typing import Optional, Literal
from hugegraph_llm.flows.common import BaseFlow
from hugegraph_llm.nodes.llm_node.keyword_extract_node import KeywordExtractNode
from hugegraph_llm.nodes.index_node.vector_query_node import VectorQueryNode
from hugegraph_llm.nodes.index_node.semantic_id_query_node import SemanticIdQueryNode
from hugegraph_llm.nodes.hugegraph_node.schema import SchemaNode
from hugegraph_llm.nodes.hugegraph_node.graph_query_node import GraphQueryNode
from hugegraph_llm.nodes.common_node.merge_rerank_node import MergeRerankNode
from hugegraph_llm.nodes.llm_node.answer_synthesize_node import AnswerSynthesizeNode
from hugegraph_llm.state.ai_state import WkFlowInput, WkFlowState
from hugegraph_llm.config import huge_settings, prompt
from hugegraph_llm.utils.log import log

import json
from PyCGraph import GPipeline


class RAGFlow(BaseFlow):
    """
    RAG 工作流，基于 CGraph 执行引擎的检索增强生成流程
    """

    def __init__(self):
        pass

    def prepare(
        self,
        prepared_input: WkFlowInput,
        query: str,
        vector_search: bool = True,
        graph_search: bool = True,
        raw_answer: bool = False,
        vector_only_answer: bool = True,
        graph_only_answer: bool = False,
        graph_vector_answer: bool = False,
        graph_ratio: float = 0.5,
        rerank_method: Literal["bleu", "reranker"] = "bleu",
        near_neighbor_first: bool = False,
        custom_related_information: str = "",
        answer_prompt: Optional[str] = None,
        keywords_extract_prompt: Optional[str] = None,
        gremlin_tmpl_num: Optional[int] = -1,
        gremlin_prompt: Optional[str] = None,
        max_graph_items: int = None,
        topk_return_results: int = None,
        vector_dis_threshold: float = None,
        topk_per_keyword: int = None,
    ):
        """
        准备 RAG 工作流输入参数
        """
        prepared_input.query = query
        prepared_input.vector_search = vector_search
        prepared_input.graph_search = graph_search
        prepared_input.raw_answer = raw_answer
        prepared_input.vector_only_answer = vector_only_answer
        prepared_input.graph_only_answer = graph_only_answer
        prepared_input.graph_vector_answer = graph_vector_answer
        prepared_input.graph_ratio = graph_ratio
        prepared_input.rerank_method = rerank_method
        prepared_input.near_neighbor_first = near_neighbor_first
        prepared_input.custom_related_information = custom_related_information
        prepared_input.answer_prompt = answer_prompt or prompt.answer_prompt
        prepared_input.keywords_extract_prompt = (
            keywords_extract_prompt or prompt.keywords_extract_prompt
        )
        prepared_input.gremlin_tmpl_num = gremlin_tmpl_num
        prepared_input.gremlin_prompt = gremlin_prompt or prompt.gremlin_generate_prompt
        prepared_input.max_graph_items = (
            max_graph_items or huge_settings.max_graph_items
        )
        prepared_input.topk_return_results = (
            topk_return_results or huge_settings.topk_return_results
        )
        prepared_input.vector_dis_threshold = (
            vector_dis_threshold or huge_settings.vector_dis_threshold
        )
        prepared_input.topk_per_keyword = (
            topk_per_keyword or huge_settings.topk_per_keyword
        )
        prepared_input.schema = huge_settings.graph_name

        return

    def build_flow(
        self,
        query: str,
        vector_search: bool = True,
        graph_search: bool = True,
        raw_answer: bool = False,
        vector_only_answer: bool = True,
        graph_only_answer: bool = False,
        graph_vector_answer: bool = False,
        graph_ratio: float = 0.5,
        rerank_method: Literal["bleu", "reranker"] = "bleu",
        near_neighbor_first: bool = False,
        custom_related_information: str = "",
        answer_prompt: Optional[str] = None,
        keywords_extract_prompt: Optional[str] = None,
        gremlin_tmpl_num: Optional[int] = -1,
        gremlin_prompt: Optional[str] = None,
        max_graph_items: int = None,
        topk_return_results: int = None,
        vector_dis_threshold: float = None,
        topk_per_keyword: int = None,
    ):
        """
        构建 RAG 工作流流水线
        """
        pipeline = GPipeline()

        # 准备输入参数
        prepared_input = WkFlowInput()
        self.prepare(
            prepared_input,
            query=query,
            vector_search=vector_search,
            graph_search=graph_search,
            raw_answer=raw_answer,
            vector_only_answer=vector_only_answer,
            graph_only_answer=graph_only_answer,
            graph_vector_answer=graph_vector_answer,
            graph_ratio=graph_ratio,
            rerank_method=rerank_method,
            near_neighbor_first=near_neighbor_first,
            custom_related_information=custom_related_information,
            answer_prompt=answer_prompt,
            keywords_extract_prompt=keywords_extract_prompt,
            gremlin_tmpl_num=gremlin_tmpl_num,
            gremlin_prompt=gremlin_prompt,
            max_graph_items=max_graph_items,
            topk_return_results=topk_return_results,
            vector_dis_threshold=vector_dis_threshold,
            topk_per_keyword=topk_per_keyword,
        )

        # 创建参数区
        pipeline.createGParam(prepared_input, "wkflow_input")
        pipeline.createGParam(WkFlowState(), "wkflow_state")

        # 创建节点
        keyword_extract_node = KeywordExtractNode()

        vector_query_node = VectorQueryNode()

        # 新增的独立节点
        schema_node = SchemaNode()
        semantic_id_query_node = SemanticIdQueryNode()

        graph_query_node = GraphQueryNode()

        merge_rerank_node = MergeRerankNode()

        answer_synthesize_node = AnswerSynthesizeNode()

        # 注册节点和依赖关系
        # 关键词提取节点（独立）
        pipeline.registerGElement(keyword_extract_node, set(), "keyword_extract")

        # 向量查询节点（独立，如果启用向量搜索）
        if prepared_input.vector_search:
            pipeline.registerGElement(vector_query_node, set(), "vector_query")

        # 图搜索相关节点（如果启用图搜索）
        if graph_search:
            # Schema节点（独立）
            pipeline.registerGElement(schema_node, set(), "schema")

            # 语义ID查询节点（依赖关键词提取）
            pipeline.registerGElement(
                semantic_id_query_node, {keyword_extract_node}, "semantic_id_query"
            )

            # 图查询节点（依赖Schema和语义ID查询）
            pipeline.registerGElement(
                graph_query_node, {schema_node, semantic_id_query_node}, "graph_query"
            )

        # 合并重排序节点（依赖向量查询和图查询）
        dependencies = set()
        if vector_search:
            dependencies.add(vector_query_node)
        if graph_search:
            dependencies.add(graph_query_node)

        if dependencies:  # 只有当有查询结果时才需要合并重排序
            pipeline.registerGElement(merge_rerank_node, dependencies, "merge_rerank")
            # 答案合成节点（依赖合并重排序）
            pipeline.registerGElement(
                answer_synthesize_node, {merge_rerank_node}, "answer_synthesize"
            )
        else:
            # 如果没有查询结果，直接进行答案合成
            pipeline.registerGElement(
                answer_synthesize_node, set(), "answer_synthesize"
            )

        log.info("RAG workflow pipeline built successfully")
        return pipeline

    def post_deal(self, pipeline=None):
        """
        后处理 RAG 工作流结果
        """
        if pipeline is None:
            return json.dumps(
                {"error": "No pipeline provided"}, ensure_ascii=False, indent=2
            )

        try:
            res = pipeline.getGParamWithNoEmpty("wkflow_state").to_json()

            # 提取各种类型的答案
            return {
                "raw_answer": res.get("raw_answer", ""),
                "vector_only_answer": res.get("vector_only_answer", ""),
                "graph_only_answer": res.get("graph_only_answer", ""),
                "graph_vector_answer": res.get("graph_vector_answer", ""),
            }

        except Exception as e:
            log.error(f"RAG workflow post processing failed: {e}")
            return json.dumps(
                {"error": f"Post processing failed: {str(e)}"},
                ensure_ascii=False,
                indent=2,
            )
