# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements. See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License. You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import asyncio
import threading
from functools import partial
from types import SimpleNamespace

import pytest

from hugegraph_llm_sdk import (
    FunctionModel,
    ThreadedModel,
    adesign_schema,
    aextract_graph,
    design_schema,
    extract_graph,
)

SCHEMA = {"vertexlabels": [], "edgelabels": []}


class AsyncGenerate:
    def __init__(self):
        self.calls = 0

    async def __call__(self, prompt):
        self.calls += 1
        return '{"vertexlabels": [], "edgelabels": []}'


@pytest.fixture(params=[False, True], ids=["callable-object", "partial-callable-object"])
def async_callback(request):
    callback = AsyncGenerate()
    return (partial(callback) if request.param else callback), callback


def test_function_model_rejects_async_callable_in_sync_slot(async_callback):
    function, callback = async_callback
    with pytest.raises(TypeError, match="synchronous callable"):
        FunctionModel(generate=function)
    assert callback.calls == 0


def test_threaded_model_rejects_async_callable_in_sync_slot(async_callback):
    function, callback = async_callback
    with pytest.raises(TypeError, match="synchronous generate"):
        ThreadedModel(SimpleNamespace(generate=function))
    assert callback.calls == 0


@pytest.mark.parametrize("entrypoint", ["design", "extract"])
def test_public_sync_calls_reject_async_callable_model_before_inference(async_callback, entrypoint):
    function, callback = async_callback
    model = SimpleNamespace(generate=function)
    with pytest.raises(TypeError, match="generate must be synchronous"):
        if entrypoint == "design":
            design_schema("text", model=model)
        else:
            extract_graph("text", schema=SCHEMA, model=model)
    assert callback.calls == 0


def test_async_callable_object_remains_supported_for_async_models(async_callback):
    function, callback = async_callback
    draft = asyncio.run(adesign_schema("text", model=FunctionModel(agenerate=function)))
    assert draft.schema == SCHEMA and draft.issues == []
    assert callback.calls == 1


def test_threaded_model_rejects_function_adapter_without_sync_implementation():
    with pytest.raises(TypeError, match="synchronous generate"):
        ThreadedModel(FunctionModel(agenerate=AsyncGenerate()))


@pytest.mark.parametrize("asynchronous", [False, True], ids=["sync", "async"])
@pytest.mark.parametrize("hook_name", ["model_factory", "validators"])
def test_async_callable_partial_hooks_are_rejected_before_any_model_call(asynchronous, hook_name):
    calls = []

    class AsyncHook:
        async def __call__(self, *args):
            calls.append("hook")

    def generate(prompt):
        calls.append("model")
        return '{"vertices": [], "edges": []}'

    async def agenerate(prompt):
        return generate(prompt)

    hook = partial(AsyncHook())
    arguments = {"model_factory": hook}
    if hook_name == "validators":
        arguments = {"model": FunctionModel(generate=generate, agenerate=agenerate), "validators": [hook]}
    with pytest.raises(TypeError, match=f"{hook_name} must be synchronous"):
        if asynchronous:
            asyncio.run(aextract_graph("text", schema=SCHEMA, review=False, **arguments))
        else:
            extract_graph("text", schema=SCHEMA, review=False, **arguments)
    assert calls == []


@pytest.mark.parametrize("asynchronous", [False, True], ids=["sync", "async"])
@pytest.mark.parametrize("wrapped", [False, True], ids=["class", "partial-class"])
def test_model_class_factory_can_have_async_callable_instances(asynchronous, wrapped):
    instances = []

    class Model:
        def __init__(self):
            self.closed = 0
            instances.append(self)

        async def __call__(self, prompt):
            return self.generate(prompt=prompt)

        def generate(self, *, prompt):
            return '{"vertices": [], "edges": []}'

        async def agenerate(self, *, prompt):
            return await self(prompt)

        def close(self):
            self.closed += 1

        async def aclose(self):
            self.close()

    factory = partial(Model) if wrapped else Model
    arguments = {"schema": SCHEMA, "model_factory": factory, "review": False}
    result = asyncio.run(aextract_graph("text", **arguments)) if asynchronous else extract_graph("text", **arguments)
    assert result.status == "succeeded"
    assert len(instances) == 1 and instances[0].closed == 1


@pytest.mark.parametrize("asynchronous", [False, True], ids=["sync", "async"])
@pytest.mark.parametrize("wrapped", [False, True], ids=["class", "partial-class"])
def test_async_metaclass_factory_is_rejected_before_construction(asynchronous, wrapped):
    calls = []

    class AsyncFactory(type):
        async def __call__(cls):
            calls.append("factory")
            return super().__call__()

    class Model(metaclass=AsyncFactory):
        def __init__(self):
            calls.append("constructor")

    factory = partial(Model) if wrapped else Model
    with pytest.raises(TypeError, match="model_factory must be synchronous"):
        if asynchronous:
            asyncio.run(aextract_graph("text", schema=SCHEMA, model_factory=factory))
        else:
            extract_graph("text", schema=SCHEMA, model_factory=factory)
    assert calls == []


def test_function_model_passes_prompt_to_caller_function():
    calls = []

    def generate(prompt):
        calls.append(prompt)
        return "answer"

    model = FunctionModel(generate=generate)
    assert model.generate(prompt="question") == "answer"
    assert calls == ["question"]


def test_function_model_requires_at_least_one_function():
    with pytest.raises((TypeError, ValueError)):
        FunctionModel()


def test_function_model_does_not_implicitly_run_an_async_function_synchronously():
    async def generate(prompt):
        return prompt

    model = FunctionModel(agenerate=generate)
    with pytest.raises((TypeError, ValueError, RuntimeError, NotImplementedError)):
        model.generate(prompt="question")


def test_sync_function_requires_explicit_async_bridge():
    model = FunctionModel(generate=lambda prompt: prompt)

    async def scenario():
        with pytest.raises((TypeError, ValueError, RuntimeError, NotImplementedError)):
            await model.agenerate(prompt="question")

    asyncio.run(scenario())


def test_threaded_model_runs_sync_call_off_the_event_loop():
    async def scenario():
        loop = asyncio.get_running_loop()
        entered = asyncio.Event()
        release = threading.Event()
        loop_thread = threading.get_ident()
        seen_threads = []

        def generate(prompt):
            seen_threads.append(threading.get_ident())
            loop.call_soon_threadsafe(entered.set)
            if not release.wait(timeout=5):
                raise RuntimeError("event loop could not release worker")
            return prompt.upper()

        model = ThreadedModel(FunctionModel(generate=generate))
        task = asyncio.create_task(model.agenerate(prompt="question"))
        try:
            await asyncio.wait_for(entered.wait(), timeout=2)
            release.set()
            assert await asyncio.wait_for(task, timeout=2) == "QUESTION"
        finally:
            release.set()
        assert seen_threads and seen_threads[0] != loop_thread

    asyncio.run(scenario())
