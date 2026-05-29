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

import asyncio
import json
import os
import uuid

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from hugegraph_llm.api.chat_completion_adapter import rag_stream_generator
from hugegraph_llm.api.exceptions.rag_exceptions import generate_response
from hugegraph_llm.api.models.rag_requests import (
    GraphConfigRequest,
    GraphRAGRequest,
    GremlinGenerateRequest,
    LLMConfigRequest,
    RAGRequest,
    RerankerConfigRequest,
)
from hugegraph_llm.api.models.rag_response import RAGResponse
from hugegraph_llm.config import huge_settings, llm_settings, prompt
from hugegraph_llm.flows import FlowName
from hugegraph_llm.flows.scheduler import SchedulerSingleton
from hugegraph_llm.middleware.middleware import get_trace_id
from hugegraph_llm.utils.graph_index_utils import get_vertex_details
from hugegraph_llm.utils.log import log


def _async_routes_enabled() -> bool:
    """Phase 3 P3-T5: feature flag.

    Defaults to enabled. Set ``HUGEGRAPH_LLM_ASYNC_ROUTES_ENABLED=0/false/no``
    to fall back to the legacy synchronous route handlers (pre-Phase-3 behavior)
    as a one-shot rollback switch. The streaming ``/rag/stream`` route is always
    async — only ``/rag``, ``/rag/graph``, ``/text2gremlin`` honor this flag.
    """
    raw = os.getenv("HUGEGRAPH_LLM_ASYNC_ROUTES_ENABLED")
    if raw is None:
        return True
    return raw.strip().lower() not in {"0", "false", "no", "off", ""}


# pylint: disable=too-many-statements
def rag_http_api(
    router: APIRouter,
    rag_answer_func,
    graph_rag_recall_func,
    apply_graph_conf,
    apply_llm_conf,
    apply_embedding_conf,
    apply_reranker_conf,
    gremlin_generate_selective_func,
):
    def _select_flow_key(req: RAGRequest):
        """根据请求标志位选 flow_key；若一个都没勾返回 None（路由层据此返回 400）。"""
        if req.graph_vector_answer or (req.graph_only and req.vector_only):
            return FlowName.RAG_GRAPH_VECTOR
        if req.vector_only:
            return FlowName.RAG_VECTOR_ONLY
        if req.graph_only:
            return FlowName.RAG_GRAPH_ONLY
        if req.raw_answer:
            return FlowName.RAG_RAW
        return None

    async def _rag_delta_stream(req: RAGRequest, flow_key):
        """直接 yield ``(answer_type, token_delta)`` 元组；调用方需先在路由函数里
        校验 query 与 flow_key（错误必须在 StreamingResponse 启动前抛 HTTPException，
        否则首字节后只能下发 ``event: error`` SSE 事件，HTTP status 已锁死 200）。

        注意：必须把 RAGRequest 中的检索调参（``max_graph_items`` /
        ``topk_return_results`` / ``vector_dis_threshold`` / ``topk_per_keyword``）
        透传给 scheduler，否则 ``/rag`` 与 ``/rag/stream`` 在同一请求体上会出现
        召回 / 排序语义不一致（详见 review）。
        """
        graph_search = req.graph_only or req.graph_vector_answer
        vector_search = req.vector_only or req.graph_vector_answer
        scheduler = SchedulerSingleton.get_instance()
        async for item in scheduler.schedule_stream_flow(
            flow_key,
            query=req.query,
            vector_search=vector_search,
            graph_search=graph_search,
            raw_answer=req.raw_answer,
            vector_only_answer=req.vector_only,
            graph_only_answer=req.graph_only,
            graph_vector_answer=req.graph_vector_answer,
            graph_ratio=req.graph_ratio,
            rerank_method=req.rerank_method,
            near_neighbor_first=req.near_neighbor_first,
            custom_related_information=req.custom_priority_info,
            answer_prompt=req.answer_prompt or prompt.answer_prompt,
            keywords_extract_prompt=req.keywords_extract_prompt or prompt.keywords_extract_prompt,
            gremlin_tmpl_num=req.gremlin_tmpl_num,
            gremlin_prompt=req.gremlin_prompt or prompt.gremlin_generate_prompt,
            # 检索调参，必须与同步 /rag 路径保持一致。
            max_graph_items=req.max_graph_items,
            topk_return_results=req.topk_return_results,
            vector_dis_threshold=req.vector_dis_threshold,
            topk_per_keyword=req.topk_per_keyword,
        ):
            # operator 源头 yield (answer_type, token_delta)；post_deal_stream 透传，
            # 这里直接转发给 SSE adapter。
            if isinstance(item, tuple) and len(item) == 2:
                yield item
            elif isinstance(item, dict):
                # 控制 / 元数据通道：error / warning / metadata 等非 token 状态
                # 直接透传给 adapter（``rag_stream_generator``）解释。post_deal_stream
                # 在 stream_generator 缺失时 yield {"error": ...} 也走这条路径。
                yield item
            else:
                # 兼容兜底：忽略其他形态
                log.warning("ignored unexpected stream item type=%s", type(item).__name__)

    @router.post("/rag/stream", status_code=status.HTTP_200_OK)
    async def rag_answer_stream_api(req: RAGRequest, request: Request):
        """SSE 流式 RAG 接口（OpenAI ChatCompletionChunk 协议，详见 design.md §1.1）。

        - 响应类型 ``text/event-stream``
        - 客户端断开后通过 ``request.is_disconnected()`` best-effort 取消
        - 错误以 ``event: error`` 行下发，附 trace_id；不返回 5xx
        - 流尾发 ``data: [DONE]\\n\\n``
        """
        set_graph_config(req)
        if not req.query or not str(req.query).strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Query must not be empty.",
            )
        flow_key = _select_flow_key(req)
        if flow_key is None:
            # 必须在 StreamingResponse 启动前返回 400，否则首字节后只能发 SSE error。
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="At least one of raw_answer / vector_only / graph_only / graph_vector_answer must be true.",
            )

        # Phase 3 P3-T3: prefer trace_id from middleware ContextVar so it matches
        # the X-Trace-Id stamped by UseTimeMiddleware on this same request; fall
        # back to a fresh uuid when the middleware isn't installed (e.g. tests
        # mounting only the router).
        trace_id = get_trace_id() or uuid.uuid4().hex
        delta_stream = _rag_delta_stream(req, flow_key)

        async def event_generator():
            try:
                async for line in rag_stream_generator(
                    delta_stream,
                    trace_id=trace_id,
                    is_disconnected=request.is_disconnected,
                ):
                    yield line
            except asyncio.CancelledError:
                log.info("client cancelled streaming, trace_id=%s", trace_id)
                raise
            finally:
                # 显式关闭上游 generator，触发 answer_synthesize 的 finally
                # 取消 pending LLM streaming task（见需求 1.3）。
                try:
                    await delta_stream.aclose()
                except Exception:  # noqa: BLE001
                    pass

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "X-Accel-Buffering": "no",
                "Cache-Control": "no-cache",
                "X-Trace-Id": trace_id,
            },
        )

    def _build_rag_answer_response(req: RAGRequest, result):
        # TODO: we need more info in the response for users to understand the query logic
        return {
            "query": req.query,
            **{
                key: value
                for key, value in zip(
                    ["raw_answer", "vector_only", "graph_only", "graph_vector_answer"],
                    result,
                )
                if getattr(req, key)
            },
        }

    def _validate_rag_request(req: RAGRequest):
        set_graph_config(req)
        # Basic parameter validation: empty query => 400
        if not req.query or not str(req.query).strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Query must not be empty.",
            )

    def _invoke_rag_answer(req: RAGRequest):
        return rag_answer_func(
            text=req.query,
            raw_answer=req.raw_answer,
            vector_only_answer=req.vector_only,
            graph_only_answer=req.graph_only,
            graph_vector_answer=req.graph_vector_answer,
            graph_ratio=req.graph_ratio,
            rerank_method=req.rerank_method,
            near_neighbor_first=req.near_neighbor_first,
            gremlin_tmpl_num=req.gremlin_tmpl_num,
            max_graph_items=req.max_graph_items,
            topk_return_results=req.topk_return_results,
            vector_dis_threshold=req.vector_dis_threshold,
            topk_per_keyword=req.topk_per_keyword,
            # Keep prompt params in the end
            custom_related_information=req.custom_priority_info,
            answer_prompt=req.answer_prompt or prompt.answer_prompt,
            keywords_extract_prompt=req.keywords_extract_prompt or prompt.keywords_extract_prompt,
            gremlin_prompt=req.gremlin_prompt or prompt.gremlin_generate_prompt,
        )

    if _async_routes_enabled():

        @router.post("/rag", status_code=status.HTTP_200_OK)
        async def rag_answer_api(req: RAGRequest):
            """Phase 3 P3-T1: async route. ``rag_answer_func`` is the legacy
            sync entrypoint (``demo.rag_demo.rag_block.rag_answer``) which calls
            ``Scheduler.schedule_flow`` → ``pipeline.run()``; we boundary it with
            ``asyncio.to_thread`` so the event loop is not held by a single request
            (consistent with P1-T0 spike's option-b for streaming).
            """
            _validate_rag_request(req)
            result = await asyncio.to_thread(_invoke_rag_answer, req)
            return _build_rag_answer_response(req, result)

    else:

        @router.post("/rag", status_code=status.HTTP_200_OK)
        def rag_answer_api(req: RAGRequest):
            _validate_rag_request(req)
            result = _invoke_rag_answer(req)
            return _build_rag_answer_response(req, result)

    def set_graph_config(req):
        if req.client_config:
            huge_settings.graph_url = req.client_config.url
            huge_settings.graph_name = req.client_config.graph
            huge_settings.graph_user = req.client_config.user
            huge_settings.graph_pwd = req.client_config.pwd
            huge_settings.graph_space = req.client_config.gs

    def _validate_graph_rag_request(req: GraphRAGRequest):
        set_graph_config(req)
        if not req.query or not str(req.query).strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Query must not be empty.",
            )

    def _invoke_graph_rag_recall(req: GraphRAGRequest):
        return graph_rag_recall_func(
            query=req.query,
            max_graph_items=req.max_graph_items,
            topk_return_results=req.topk_return_results,
            vector_dis_threshold=req.vector_dis_threshold,
            topk_per_keyword=req.topk_per_keyword,
            gremlin_tmpl_num=req.gremlin_tmpl_num,
            rerank_method=req.rerank_method,
            near_neighbor_first=req.near_neighbor_first,
            custom_related_information=req.custom_priority_info,
            gremlin_prompt=req.gremlin_prompt or prompt.gremlin_generate_prompt,
            get_vertex_only=req.get_vertex_only,
        )

    def _build_graph_rag_response(req: GraphRAGRequest, result):
        if req.get_vertex_only:
            vertex_details = get_vertex_details(result["match_vids"], result)
            if vertex_details:
                result["match_vids"] = vertex_details

        if isinstance(result, dict):
            params = [
                "query",
                "keywords",
                "match_vids",
                "graph_result_flag",
                "gremlin",
                "graph_result",
                "vertex_degree_list",
            ]
            user_result = {key: result[key] for key in params if key in result}
            return {"graph_recall": user_result}
        return {"graph_recall": json.dumps(result)}

    if _async_routes_enabled():

        @router.post("/rag/graph", status_code=status.HTTP_200_OK)
        async def graph_rag_recall_api(req: GraphRAGRequest):
            """Phase 3 P3-T1: async route. Underlying ``graph_rag_recall_func`` is
            the sync Gradio entrypoint that drives ``Scheduler.schedule_flow``;
            we boundary it with ``asyncio.to_thread`` to keep the event loop free.
            """
            try:
                _validate_graph_rag_request(req)
                result = await asyncio.to_thread(_invoke_graph_rag_recall, req)
                return _build_graph_rag_response(req, result)
            except HTTPException:
                raise
            except TypeError as e:
                log.error("TypeError in graph_rag_recall_api: %s", e)
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
            except Exception as e:
                log.error("Unexpected error occurred: %s", e)
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="An unexpected error occurred.",
                ) from e

    else:

        @router.post("/rag/graph", status_code=status.HTTP_200_OK)
        def graph_rag_recall_api(req: GraphRAGRequest):
            try:
                _validate_graph_rag_request(req)
                result = _invoke_graph_rag_recall(req)
                return _build_graph_rag_response(req, result)
            except HTTPException:
                raise
            except TypeError as e:
                log.error("TypeError in graph_rag_recall_api: %s", e)
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
            except Exception as e:
                log.error("Unexpected error occurred: %s", e)
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="An unexpected error occurred.",
                ) from e

    # Config routes are pure metadata writes (no pipeline, no IO besides a single
    # PyHugeClient health-check). They stay ``def`` regardless of the feature flag
    # — FastAPI executes them on its threadpool, no event-loop blocking risk.
    @router.post("/config/graph", status_code=status.HTTP_201_CREATED)
    def graph_config_api(req: GraphConfigRequest):
        # Accept status code
        res = apply_graph_conf(req.url, req.graph, req.user, req.pwd, req.gs, origin_call="http")
        return generate_response(RAGResponse(status_code=res, message="Missing Value"))

    # TODO: restructure the implement of llm to three types, like "/config/chat_llm"
    @router.post("/config/llm", status_code=status.HTTP_201_CREATED)
    def llm_config_api(req: LLMConfigRequest):
        llm_settings.llm_type = req.llm_type

        if req.llm_type == "openai":
            res = apply_llm_conf(
                req.api_key,
                req.api_base,
                req.language_model,
                req.max_tokens,
                origin_call="http",
            )
        else:
            res = apply_llm_conf(req.host, req.port, req.language_model, None, origin_call="http")
        return generate_response(RAGResponse(status_code=res, message="Missing Value"))

    @router.post("/config/embedding", status_code=status.HTTP_201_CREATED)
    def embedding_config_api(req: LLMConfigRequest):
        llm_settings.embedding_type = req.llm_type

        if req.llm_type == "openai":
            res = apply_embedding_conf(req.api_key, req.api_base, req.language_model, origin_call="http")
        else:
            res = apply_embedding_conf(req.host, req.port, req.language_model, origin_call="http")
        return generate_response(RAGResponse(status_code=res, message="Missing Value"))

    @router.post("/config/rerank", status_code=status.HTTP_201_CREATED)
    def rerank_config_api(req: RerankerConfigRequest):
        llm_settings.reranker_type = req.reranker_type

        if req.reranker_type == "cohere":
            res = apply_reranker_conf(req.api_key, req.reranker_model, req.cohere_base_url, origin_call="http")
        elif req.reranker_type == "siliconflow":
            res = apply_reranker_conf(req.api_key, req.reranker_model, None, origin_call="http")
        else:
            res = status.HTTP_501_NOT_IMPLEMENTED
        return generate_response(RAGResponse(status_code=res, message="Missing Value"))

    def _invoke_text2gremlin(req: GremlinGenerateRequest):
        output_types_str_list = None
        if req.output_types:
            output_types_str_list = [ot.value for ot in req.output_types]
        return gremlin_generate_selective_func(
            inp=req.query,
            example_num=req.example_num,
            schema_input=huge_settings.graph_name,
            gremlin_prompt_input=req.gremlin_prompt,
            requested_outputs=output_types_str_list,
        )

    if _async_routes_enabled():

        @router.post("/text2gremlin", status_code=status.HTTP_200_OK)
        async def text2gremlin_api(req: GremlinGenerateRequest):
            """Phase 3 P3-T1: async route. ``gremlin_generate_selective_func``
            drives a sync ``schedule_flow`` → ``pipeline.run()``; boundary it via
            ``asyncio.to_thread`` so the event loop is never held by a single
            text2gremlin request.
            """
            try:
                set_graph_config(req)
                if not req.query or not str(req.query).strip():
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Query must not be empty.",
                    )
                return await asyncio.to_thread(_invoke_text2gremlin, req)
            except HTTPException as e:
                raise e
            except Exception as e:
                log.error("Error in text2gremlin_api: %s", e)
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="An unexpected error occurred during Gremlin generation.",
                ) from e

    else:

        @router.post("/text2gremlin", status_code=status.HTTP_200_OK)
        def text2gremlin_api(req: GremlinGenerateRequest):
            try:
                set_graph_config(req)
                if not req.query or not str(req.query).strip():
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Query must not be empty.",
                    )
                return _invoke_text2gremlin(req)
            except HTTPException as e:
                raise e
            except Exception as e:
                log.error("Error in text2gremlin_api: %s", e)
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="An unexpected error occurred during Gremlin generation.",
                ) from e
