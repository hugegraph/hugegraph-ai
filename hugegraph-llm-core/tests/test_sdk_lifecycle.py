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

"""Model ownership and cleanup at the public SDK batch boundary."""

import asyncio
import threading
from contextlib import ExitStack
from tempfile import TemporaryFile

import pytest

from hugegraph_llm_core import ExtractionOptions, ThreadedModel, aextract_graph, extract_graph
from hugegraph_llm_core._lifecycle import OwnedModels

SCHEMA = {"vertexlabels": [], "edgelabels": []}
EMPTY_GRAPH = '{"vertices": [], "edges": []}'
PASS_REVIEW = '{"decision": "pass", "issues": []}'


class ClosableModel:
    def __init__(self, failure=None):
        self.failure = failure
        self.calls = 0
        self.closed = 0

    def generate(self, *, prompt):
        assert self.closed == 0, "Model was closed before its chunk finished"
        self.calls += 1
        if self.failure:
            raise self.failure
        return EMPTY_GRAPH if self.calls == 1 else PASS_REVIEW

    def close(self):
        self.closed += 1


@pytest.mark.parametrize(
    ("failures", "status"),
    [
        ((None, None), "succeeded"),
        ((RuntimeError("provider failed"), None), "partial"),
        ((RuntimeError("first provider failed"), RuntimeError("second provider failed")), "failed"),
    ],
)
def test_sync_batch_closes_factory_models_for_all_result_states(failures, status):
    models = []

    def factory():
        model = ClosableModel(failures[len(models)])
        models.append(model)
        return model

    result = extract_graph(["first text", "second text"], schema=SCHEMA, model_factory=factory)

    assert result.status == status
    assert len(models) == 2
    assert all(model.closed == 1 for model in models)


def test_sync_model_passed_by_caller_is_not_closed():
    model = ClosableModel()
    result = extract_graph("text", schema=SCHEMA, model=model)
    assert result.status == "succeeded" and model.closed == 0
    model.close()
    assert model.closed == 1


def test_sync_caller_keeps_model_ownership_after_runtime_failure():
    model = ClosableModel(RuntimeError("provider failed"))
    result = extract_graph("text", schema=SCHEMA, model=model)
    assert result.status == "failed" and model.closed == 0


def test_preparation_failure_still_closes_already_created_factory_model():
    model = ClosableModel()
    attempts = []

    def factory():
        attempts.append(True)
        if len(attempts) == 1:
            return model
        raise RuntimeError("client construction failed")

    result = extract_graph(["first", "second"], schema=SCHEMA, model_factory=factory)
    assert result.status == "partial"
    assert result.chunks[1].stage == "prepare"
    assert model.closed == 1


def test_factory_model_is_closed_when_interface_validation_fails():
    class InvalidModel:
        closed = 0

        def close(self):
            self.closed += 1

    model = InvalidModel()
    result = extract_graph("text", schema=SCHEMA, model_factory=lambda: model)
    assert result.status == "failed" and result.chunks[0].stage == "prepare"
    assert model.closed == 1


def test_sync_fatal_error_propagates_after_factory_model_cleanup():
    model = ClosableModel(KeyboardInterrupt())
    with pytest.raises(KeyboardInterrupt):
        extract_graph("text", schema=SCHEMA, model_factory=lambda: model)
    assert model.closed == 1


def test_duplicate_factory_model_fails_preparation_and_is_closed_once():
    model = ClosableModel()
    result = extract_graph(["first", "second"], schema=SCHEMA, model_factory=lambda: model)
    assert result.status == "partial"
    assert result.chunks[0].status == "final"
    assert result.chunks[1].status == "failed" and result.chunks[1].stage == "prepare"
    assert model.closed == 1


def test_sync_cleanup_attempts_all_models_before_reporting_cleanup_failure():
    class BrokenClose(ClosableModel):
        def close(self):
            super().close()
            raise RuntimeError("closing failed")

    first, second = BrokenClose(), ClosableModel()
    models = iter([first, second])
    with pytest.raises(RuntimeError):
        extract_graph(
            ["first", "second"],
            schema=SCHEMA,
            model_factory=lambda: next(models),
            options=ExtractionOptions(max_workers=2),
        )
    assert first.closed == second.closed == 1


def test_sync_cleanup_failure_does_not_replace_primary_error():
    class BrokenClose(ClosableModel):
        def close(self):
            super().close()
            raise RuntimeError("closing failed")

    model = BrokenClose(KeyboardInterrupt())
    with pytest.raises(KeyboardInterrupt):
        extract_graph("text", schema=SCHEMA, model_factory=lambda: model)
    assert model.closed == 1


class AsyncClosableModel:
    def __init__(self, failure=None):
        self.failure = failure
        self.calls = 0
        self.closed = 0
        self.sync_closed = 0

    async def agenerate(self, *, prompt):
        assert self.closed == 0, "Model was closed before its chunk finished"
        self.calls += 1
        await asyncio.sleep(0)
        if self.failure:
            raise self.failure
        return EMPTY_GRAPH if self.calls == 1 else PASS_REVIEW

    async def aclose(self):
        # Increment after a suspension so a forgotten await cannot pass.
        await asyncio.sleep(0)
        self.closed += 1

    def close(self):
        self.sync_closed += 1


@pytest.mark.parametrize("failure", [None, RuntimeError("provider failed")])
def test_async_batch_awaits_factory_aclose_and_prefers_it_to_close(failure):
    async def scenario():
        model = AsyncClosableModel(failure)
        result = await aextract_graph("text", schema=SCHEMA, model_factory=lambda: model)
        assert result.status == ("succeeded" if failure is None else "failed")
        assert model.closed == 1 and model.sync_closed == 0

    asyncio.run(scenario())


def test_async_model_passed_by_caller_is_not_closed():
    async def scenario():
        model = AsyncClosableModel()
        result = await aextract_graph("text", schema=SCHEMA, model=model)
        assert result.status == "succeeded"
        assert model.closed == model.sync_closed == 0
        await model.aclose()
        assert model.closed == 1

    asyncio.run(scenario())


@pytest.mark.parametrize("factory_owned", [False, True])
def test_threaded_model_delegates_cleanup_only_for_factory_owned_models(factory_owned):
    async def scenario():
        underlying = ClosableModel()
        wrapped = ThreadedModel(underlying)
        kwargs = {"model_factory": lambda: wrapped} if factory_owned else {"model": wrapped}
        result = await aextract_graph("text", schema=SCHEMA, review=False, **kwargs)
        assert result.status == "succeeded"
        assert underlying.closed == int(factory_owned)

    asyncio.run(scenario())


def test_async_cleanup_attempts_all_models_before_reporting_cleanup_failure():
    async def scenario():
        class BrokenClose(AsyncClosableModel):
            async def aclose(self):
                await super().aclose()
                raise RuntimeError("closing failed")

        first, second = BrokenClose(), AsyncClosableModel()
        models = iter([first, second])
        with pytest.raises(RuntimeError):
            await aextract_graph(
                ["first", "second"],
                schema=SCHEMA,
                model_factory=lambda: next(models),
                options=ExtractionOptions(max_workers=2),
            )
        assert first.closed == second.closed == 1

    asyncio.run(scenario())


def test_async_cancellation_closes_created_models_before_propagating():
    async def scenario():
        started = asyncio.Event()
        never = asyncio.Event()
        models = []
        active = 0

        class WaitingModel(AsyncClosableModel):
            async def agenerate(self, *, prompt):
                nonlocal active
                active += 1
                if active == 2:
                    started.set()
                try:
                    await never.wait()
                    return EMPTY_GRAPH
                finally:
                    active -= 1

            async def aclose(self):
                assert active == 0, "SDK closed a client while a chunk was still running"
                await super().aclose()

        def factory():
            model = WaitingModel()
            models.append(model)
            return model

        task = asyncio.create_task(
            aextract_graph(
                ["first", "second", "third", "fourth"],
                schema=SCHEMA,
                model_factory=factory,
                options=ExtractionOptions(max_workers=2),
            )
        )
        await asyncio.wait_for(started.wait(), timeout=2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert len(models) == 2
        assert all(model.closed == 1 and model.sync_closed == 0 for model in models)
        assert active == 0

    asyncio.run(scenario())


def test_cancellation_does_not_close_caller_owned_async_model():
    async def scenario():
        started = asyncio.Event()

        class WaitingModel(AsyncClosableModel):
            async def agenerate(self, *, prompt):
                started.set()
                await asyncio.Event().wait()
                return EMPTY_GRAPH

        model = WaitingModel()
        task = asyncio.create_task(aextract_graph("text", schema=SCHEMA, model=model))
        await asyncio.wait_for(started.wait(), timeout=2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert model.closed == model.sync_closed == 0

    asyncio.run(scenario())


def test_async_cleanup_failure_preserves_cancellation():
    async def scenario():
        started = asyncio.Event()

        class WaitingModel(AsyncClosableModel):
            async def agenerate(self, *, prompt):
                started.set()
                await asyncio.Event().wait()
                return EMPTY_GRAPH

            async def aclose(self):
                await super().aclose()
                raise RuntimeError("closing failed")

        model = WaitingModel()
        task = asyncio.create_task(aextract_graph("text", schema=SCHEMA, model_factory=lambda: model))
        await asyncio.wait_for(started.wait(), timeout=2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert model.closed == 1

    asyncio.run(scenario())


@pytest.mark.parametrize("cancel_count", [1, 2])
def test_cancellation_during_cleanup_still_awaits_all_owned_models(cancel_count):
    async def scenario():
        closing = asyncio.Event()
        release = asyncio.Event()
        models = []

        class SlowClose(AsyncClosableModel):
            async def aclose(self):
                closing.set()
                await release.wait()
                await super().aclose()

        def factory():
            model = SlowClose()
            models.append(model)
            return model

        task = asyncio.create_task(
            aextract_graph(
                ["first", "second"],
                schema=SCHEMA,
                model_factory=factory,
                options=ExtractionOptions(max_workers=2),
            )
        )
        await asyncio.wait_for(closing.wait(), timeout=2)
        for _ in range(cancel_count):
            task.cancel()
            await asyncio.sleep(0)
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=2)
        assert len(models) == 2
        assert all(model.closed == 1 for model in models)

    asyncio.run(scenario())


def test_async_cleanup_offloads_a_sync_close_method():
    async def scenario():
        loop = asyncio.get_running_loop()
        loop_thread = threading.get_ident()
        closing = asyncio.Event()
        release = threading.Event()
        seen_threads = []

        class SyncCloseModel:
            async def agenerate(self, *, prompt):
                return EMPTY_GRAPH

            def close(self):
                seen_threads.append(threading.get_ident())
                loop.call_soon_threadsafe(closing.set)
                if not release.wait(timeout=5):
                    raise RuntimeError("The event loop was blocked by close()")

        task = asyncio.create_task(aextract_graph("text", schema=SCHEMA, model_factory=SyncCloseModel, review=False))
        try:
            await asyncio.wait_for(closing.wait(), timeout=2)
            release.set()
            result = await asyncio.wait_for(task, timeout=2)
            assert result.status == "succeeded"
        finally:
            release.set()
        assert seen_threads and seen_threads[0] != loop_thread

    asyncio.run(scenario())


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("max_workers", [1, 3])
def test_long_batch_respects_open_client_resource_budget(asynchronous, max_workers):
    budget = threading.BoundedSemaphore(max_workers)
    lock = threading.Lock()
    models = []
    active = peak = 0

    class FileModel:
        def __init__(self):
            nonlocal active, peak
            if not budget.acquire(blocking=False):
                raise OSError("Open model client resource budget exhausted")
            with ExitStack() as resources:
                self.resource = resources.enter_context(TemporaryFile(mode="w+t"))
                self.resource.write(EMPTY_GRAPH)
                self.resources = resources.pop_all()
            self.closed = 0
            with lock:
                models.append(self)
                active += 1
                peak = max(peak, active)

        def generate(self, *, prompt):
            self.resource.seek(0)
            return self.resource.read()

        async def agenerate(self, *, prompt):
            await asyncio.sleep(0)
            return self.generate(prompt=prompt)

        def close(self):
            nonlocal active
            self.resources.close()
            self.closed += 1
            with lock:
                active -= 1
            budget.release()

        async def aclose(self):
            await asyncio.sleep(0)
            self.close()

    arguments = {
        "schema": SCHEMA,
        "model_factory": FileModel,
        "options": ExtractionOptions(max_workers=max_workers),
        "review": False,
    }
    texts = [f"text {index}" for index in range(37)]
    result = asyncio.run(aextract_graph(texts, **arguments)) if asynchronous else extract_graph(texts, **arguments)
    assert result.status == "succeeded"
    assert [chunk.index for chunk in result.chunks] == list(range(len(texts)))
    assert len(models) == len(texts)
    assert peak == max_workers and active == 0
    assert all(model.closed == 1 and model.resource.closed for model in models)


def test_parallel_sync_groups_close_models_on_batch_callers_thread():
    caller_thread = threading.get_ident()
    created_on = []
    closed_on = []

    class ThreadTrackedModel(ClosableModel):
        def __init__(self):
            super().__init__()
            created_on.append(threading.get_ident())

        def close(self):
            closed_on.append(threading.get_ident())
            super().close()

    result = extract_graph(
        ["text"] * 5,
        schema=SCHEMA,
        model_factory=ThreadTrackedModel,
        options=ExtractionOptions(max_workers=2),
    )
    assert result.status == "succeeded"
    assert len(created_on) == len(closed_on) == 5
    assert all(thread != caller_thread for thread in created_on)
    assert closed_on == [caller_thread] * 5


def test_async_reusing_closed_factory_model_fails_without_closing_it_again():
    async def scenario():
        model = AsyncClosableModel()
        result = await aextract_graph(["first", "second"], schema=SCHEMA, model_factory=lambda: model)
        assert result.status == "partial"
        assert result.chunks[0].status == "final"
        assert result.chunks[1].reason == "prepare_failed: ValueError"
        assert model.calls == 2 and model.closed == 1

    asyncio.run(scenario())


@pytest.mark.parametrize("asynchronous", [False, True])
def test_cleanup_failure_stops_before_next_factory_group(asynchronous):
    models = []

    class BrokenClose(ClosableModel):
        def __init__(self):
            super().__init__()
            models.append(self)

        async def agenerate(self, *, prompt):
            return self.generate(prompt=prompt)

        def close(self):
            super().close()
            raise RuntimeError("closing failed")

        async def aclose(self):
            self.close()

    arguments = {"schema": SCHEMA, "model_factory": BrokenClose}
    with pytest.raises(RuntimeError, match="Failed to close a model"):
        if asynchronous:
            asyncio.run(aextract_graph(["first", "second"], **arguments))
        else:
            extract_graph(["first", "second"], **arguments)
    assert len(models) == 1 and models[0].closed == 1


@pytest.mark.parametrize("cancel_during_inference", [False, True])
def test_client_cleanup_cancellation_closes_siblings_and_preserves_caller_cancellation(cancel_during_inference):
    async def scenario():
        started = asyncio.Event()
        models = []
        active = 0

        class CancellingClose(AsyncClosableModel):
            async def agenerate(self, *, prompt):
                nonlocal active
                if not cancel_during_inference:
                    return EMPTY_GRAPH
                active += 1
                if active == 2:
                    started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    active -= 1

            async def aclose(self):
                assert active == 0, "Closing a client while a group worker is active"
                await super().aclose()
                if self is models[-1]:
                    future = asyncio.get_running_loop().create_future()
                    future.cancel("client cleanup")
                    await future

        def factory():
            model = CancellingClose()
            models.append(model)
            return model

        task = asyncio.create_task(
            aextract_graph(
                ["first", "second", "third"],
                schema=SCHEMA,
                model_factory=factory,
                options=ExtractionOptions(max_workers=2),
                review=False,
            )
        )
        if cancel_during_inference:
            await asyncio.wait_for(started.wait(), timeout=2)
            task.cancel("caller cancellation")
        message = "caller cancellation" if cancel_during_inference else "client cleanup"
        with pytest.raises(asyncio.CancelledError) as exc_info:
            await asyncio.wait_for(task, timeout=2)
        # Python 3.10's gather/wait_for can omit the cancellation message when
        # re-raising; the original cancellation remains in the context chain.
        cancellation = exc_info.value
        while not cancellation.args and isinstance(cancellation.__context__, asyncio.CancelledError):
            cancellation = cancellation.__context__
        assert str(cancellation) == message
        assert len(models) == 2
        assert all(model.closed == 1 and model.sync_closed == 0 for model in models)

    asyncio.run(scenario())


def test_client_cleanup_cancellation_preserves_existing_primary_exception():
    async def scenario():
        class CancellingClose(AsyncClosableModel):
            async def aclose(self):
                await super().aclose()
                raise asyncio.CancelledError("client cleanup")

        first, second = AsyncClosableModel(), CancellingClose()
        resources = OwnedModels()
        with pytest.raises(ValueError, match="original error"):
            async with resources:
                resources.add(first)
                resources.add(second)
                raise ValueError("original error")
        assert first.closed == second.closed == 1

    asyncio.run(scenario())
