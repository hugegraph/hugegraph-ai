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
TODO: It is not clear whether there is any other dependence on the SCHEMA_EXAMPLE_PROMPT variable.
Because the SCHEMA_EXAMPLE_PROMPT variable will no longer change based on
prompt.extract_graph_prompt changes after the system loads, this does not seem to meet expectations.
"""

# pylint: disable=W0621

import asyncio
from typing import Any, AsyncGenerator, Dict, Optional, Tuple

from hugegraph_llm.config import prompt
from hugegraph_llm.models.llms.base import BaseLLM
from hugegraph_llm.models.llms.init_llm import LLMs
from hugegraph_llm.utils.log import log

DEFAULT_ANSWER_TEMPLATE = prompt.answer_prompt


class AnswerSynthesize:
    def __init__(
        self,
        llm: Optional[BaseLLM] = None,
        prompt_template: Optional[str] = None,
        question: Optional[str] = None,
        context_body: Optional[str] = None,
        context_head: Optional[str] = None,
        context_tail: Optional[str] = None,
        raw_answer: bool = False,
        vector_only_answer: bool = True,
        graph_only_answer: bool = False,
        graph_vector_answer: bool = False,
    ):
        self._llm = llm
        self._prompt_template = prompt_template or DEFAULT_ANSWER_TEMPLATE
        self._question = question
        self._context_body = context_body
        self._context_head = context_head
        self._context_tail = context_tail
        self._raw_answer = raw_answer
        self._vector_only_answer = vector_only_answer
        self._graph_only_answer = graph_only_answer
        self._graph_vector_answer = graph_vector_answer

    def run(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """同步入口：仅供同步路径调用（pycgraph node operator_schedule、Gradio 同步链）。

        async 路径**禁止**调用本方法，必须改用 run_async；否则会触发
        "Cannot run nested event loops" RuntimeError。
        """
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            raise RuntimeError(
                "AnswerSynthesize.run() called from a running event loop; "
                "use AnswerSynthesize.run_async() instead."
            )

        context_head_str, context_tail_str = self.init_llm(context)

        if self._context_body is not None:
            context_str = f"{context_head_str}\n{self._context_body}\n{context_tail_str}".strip("\n")

            final_prompt = self._prompt_template.format(context_str=context_str, query_str=self._question)
            response = self._llm.generate(prompt=final_prompt)
            return {"answer": response}

        graph_result_context, vector_result_context = self.handle_vector_graph(context)
        context = asyncio.run(
            self.async_generate(
                context,
                context_head_str,
                context_tail_str,
                vector_result_context,
                graph_result_context,
            )
        )
        return context

    async def run_async(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """异步入口：供 HTTP async 路径直接 await，不嵌套新建事件循环。"""
        context_head_str, context_tail_str = self.init_llm(context)

        if self._context_body is not None:
            context_str = f"{context_head_str}\n{self._context_body}\n{context_tail_str}".strip("\n")

            final_prompt = self._prompt_template.format(context_str=context_str, query_str=self._question)
            response = await self._llm.agenerate(prompt=final_prompt)
            return {"answer": response}

        graph_result_context, vector_result_context = self.handle_vector_graph(context)
        return await self.async_generate(
            context,
            context_head_str,
            context_tail_str,
            vector_result_context,
            graph_result_context,
        )

    def init_llm(self, context):
        if self._llm is None:
            self._llm = LLMs().get_chat_llm()
        if self._question is None:
            self._question = context.get("query") or None
        assert self._question is not None, "No question for synthesizing."
        context_head_str = context.get("synthesize_context_head") or self._context_head or ""
        context_tail_str = context.get("synthesize_context_tail") or self._context_tail or ""
        return context_head_str, context_tail_str

    def handle_vector_graph(self, context):
        vector_result = context.get("vector_result")
        if vector_result:
            vector_result_context = "Phrases related to the query:\n" + "\n".join(
                f"{i + 1}. {res}" for i, res in enumerate(vector_result)
            )
        else:
            vector_result_context = "No (vector)phrase related to the query."
        graph_result = context.get("graph_result")
        if graph_result:
            graph_context_head = context.get("graph_context_head", "Knowledge from graphdb for the query:\n")
            graph_result_context = graph_context_head + "\n".join(
                f"{i + 1}. {res}" for i, res in enumerate(graph_result)
            )
        else:
            graph_result_context = "No related graph data found for current query."
            log.warning(graph_result_context)
        return graph_result_context, vector_result_context

    async def run_streaming(self, context: Dict[str, Any]) -> AsyncGenerator[Tuple[str, str], None]:
        """流式入口：yield ``(answer_type, token_delta)`` 元组。

        与历史"反复 yield 累计 context"的语义不同——本接口由 P1-T2.5 改造，
        delta 直传到 SSE adapter（见 ``api/chat_completion_adapter.py``）。
        Gradio 等需要累计快照的调用方请用 ``accumulate(...)`` 适配 wrapper。
        """
        context_head_str, context_tail_str = self.init_llm(context)

        if self._context_body is not None:
            context_str = f"{context_head_str}\n{self._context_body}\n{context_tail_str}".strip("\n")

            final_prompt = self._prompt_template.format(context_str=context_str, query_str=self._question)
            # 单一 answer 路径：流式逐 token 透传到 raw_answer 通道。
            async for token in self._llm.agenerate_streaming(prompt=final_prompt):
                if token:
                    yield "raw_answer", token
            return

        graph_result_context, vector_result_context = self.handle_vector_graph(context)

        async for answer_type, token in self.async_streaming_generate(
            context, context_head_str, context_tail_str, vector_result_context, graph_result_context
        ):
            yield answer_type, token

    async def async_generate(
        self,
        context: Dict[str, Any],
        context_head_str: str,
        context_tail_str: str,
        vector_result_context: str,
        graph_result_context: str,
    ):
        # async_tasks stores the async tasks for different answer types
        async_tasks = {}
        if self._raw_answer:
            final_prompt = self._question
            async_tasks["raw_task"] = asyncio.create_task(self._llm.agenerate(prompt=final_prompt))
        if self._vector_only_answer:
            context_str = f"{context_head_str}\n{vector_result_context}\n{context_tail_str}".strip("\n")

            final_prompt = self._prompt_template.format(context_str=context_str, query_str=self._question)
            async_tasks["vector_only_task"] = asyncio.create_task(self._llm.agenerate(prompt=final_prompt))
        if self._graph_only_answer:
            context_str = f"{context_head_str}\n{graph_result_context}\n{context_tail_str}".strip("\n")

            final_prompt = self._prompt_template.format(context_str=context_str, query_str=self._question)
            async_tasks["graph_only_task"] = asyncio.create_task(self._llm.agenerate(prompt=final_prompt))
        if self._graph_vector_answer:
            context_body_str = f"{vector_result_context}\n{graph_result_context}"
            if context.get("graph_ratio", 0.5) < 0.5:
                context_body_str = f"{graph_result_context}\n{vector_result_context}"
            context_str = f"{context_head_str}\n{context_body_str}\n{context_tail_str}".strip("\n")

            final_prompt = self._prompt_template.format(context_str=context_str, query_str=self._question)
            async_tasks["graph_vector_task"] = asyncio.create_task(self._llm.agenerate(prompt=final_prompt))

        async_tasks_mapping = {
            "raw_task": "raw_answer",
            "vector_only_task": "vector_only_answer",
            "graph_only_task": "graph_only_answer",
            "graph_vector_task": "graph_vector_answer",
        }

        for task_key, context_key in async_tasks_mapping.items():
            if async_tasks.get(task_key):
                response = await async_tasks[task_key]
                context[context_key] = response
                log.debug("Query Answer: %s", response)

        ops = sum(
            [
                self._raw_answer,
                self._vector_only_answer,
                self._graph_only_answer,
                self._graph_vector_answer,
            ]
        )
        context["call_count"] = context.get("call_count", 0) + ops
        return context

    async def async_streaming_generate(
        self,
        context: Dict[str, Any],
        context_head_str: str,
        context_tail_str: str,
        vector_result_context: str,
        graph_result_context: str,
    ) -> AsyncGenerator[Tuple[str, str], None]:
        """并发跑多路 LLM streaming，yield ``(answer_type, token_delta)`` 元组。

        关键正确性约束（见 design.md §1.4 / requirements.md 1.4）：

        1. 用 ``dict[Task, task_id]`` 维护"活跃" task；任意 task 完成（含
           ``StopAsyncIteration``）后 **立即 pop**，再决定是否 schedule 下一个
           ``anext``。**禁止**把已完成的 task 留在原位再传给 ``asyncio.wait()``——
           那样它会立刻返回，造成 busy loop（CPU 100%），且 ``len`` 比对结束条件
           会永远不达成或提前误判。
        2. 循环条件改为"活跃集合非空"，不再用 ``len(stop) == len(async_tasks)``。
        3. ``finally`` 中 cancel 所有 pending task + ``gather(return_exceptions=True)``
           + ``aclose()`` 子 generator，配合需求 1.3 的 cancel 语义。
        """
        async_generators: list[AsyncGenerator[Tuple[int, str, str], None]] = []
        target_keys: list[str] = []

        if self._raw_answer:
            final_prompt = self._question
            target_keys.append("raw_answer")
            async_generators.append(
                self.__llm_generate_with_meta_info(
                    task_id=len(target_keys) - 1,
                    target_key="raw_answer",
                    prompt=final_prompt,
                )
            )
        if self._vector_only_answer:
            context_str = f"{context_head_str}\n{vector_result_context}\n{context_tail_str}".strip("\n")
            final_prompt = self._prompt_template.format(context_str=context_str, query_str=self._question)
            target_keys.append("vector_only_answer")
            async_generators.append(
                self.__llm_generate_with_meta_info(
                    task_id=len(target_keys) - 1,
                    target_key="vector_only_answer",
                    prompt=final_prompt,
                )
            )
        if self._graph_only_answer:
            context_str = f"{context_head_str}\n{graph_result_context}\n{context_tail_str}".strip("\n")
            final_prompt = self._prompt_template.format(context_str=context_str, query_str=self._question)
            target_keys.append("graph_only_answer")
            async_generators.append(
                self.__llm_generate_with_meta_info(
                    task_id=len(target_keys) - 1,
                    target_key="graph_only_answer",
                    prompt=final_prompt,
                )
            )
        if self._graph_vector_answer:
            context_body_str = f"{vector_result_context}\n{graph_result_context}"
            if context.get("graph_ratio", 0.5) < 0.5:
                context_body_str = f"{graph_result_context}\n{vector_result_context}"
            context_str = f"{context_head_str}\n{context_body_str}\n{context_tail_str}".strip("\n")
            final_prompt = self._prompt_template.format(context_str=context_str, query_str=self._question)
            target_keys.append("graph_vector_answer")
            async_generators.append(
                self.__llm_generate_with_meta_info(
                    task_id=len(target_keys) - 1,
                    target_key="graph_vector_answer",
                    prompt=final_prompt,
                )
            )

        ops = len(async_generators)
        context["call_count"] = context.get("call_count", 0) + ops

        # 活跃 task -> task_id；StopAsyncIteration 后立即从 active 中删除，
        # 不再回填到 asyncio.wait()，避免已完成 task 反复被 wait 返回造成 busy loop。
        active: Dict[asyncio.Task, int] = {
            asyncio.create_task(anext(gen)): tid for tid, gen in enumerate(async_generators)
        }

        try:
            while active:
                done, _ = await asyncio.wait(
                    list(active.keys()),
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in done:
                    tid = active.pop(task)
                    try:
                        _task_id, target_key, token = task.result()
                    except StopAsyncIteration:
                        # 该 generator 结束：不再 schedule 下一个 anext，active 收缩。
                        continue
                    if token:
                        yield target_key, token
                    next_task = asyncio.create_task(anext(async_generators[tid]))
                    active[next_task] = tid
        finally:
            # 客户端断开 / 异常退出时释放上游 LLM streaming 资源（见需求 1.3）。
            for t in list(active.keys()):
                if not t.done():
                    t.cancel()
            if active:
                await asyncio.gather(*active.keys(), return_exceptions=True)
            for gen in async_generators:
                try:
                    await gen.aclose()
                except Exception:  # noqa: BLE001
                    pass

    async def __llm_generate_with_meta_info(self, task_id: int, target_key: str, prompt: str):
        # FIXME: Expected type 'AsyncIterable', got 'Coroutine[Any, Any, AsyncGenerator[str, None]]' instead
        async for token in self._llm.agenerate_streaming(prompt=prompt):
            yield task_id, target_key, token
