# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Review contracts, native async execution and bounded batch behavior."""

import asyncio
from threading import Barrier, Event, Lock, get_ident

import pytest
from pydantic import ValidationError

from hugegraph_llm_core.errors import LLMOutputTruncatedError
from hugegraph_llm_core.extraction_runtime.review import (
    ChunkInput,
    ChunkResult,
    ExtractionOptions,
    Issue,
    ReviewResult,
    arun_chunk,
    arun_chunks,
    run_chunk,
    run_chunks,
)


class ScriptedBundle:
    def __init__(self, *, initial=1, repaired=2, decisions=("pass",), fail_at=None):
        self.initial = initial
        self.repaired = repaired
        self.decisions = iter(decisions)
        self.fail_at = fail_at
        self.calls = []
        self.validated = []
        self.repair_issues = []

    def _call(self, stage):
        self.calls.append(stage)
        if self.fail_at == stage:
            raise ValueError("scripted failure")

    def extract(self, chunk: ChunkInput) -> dict:
        self._call("extract")
        return {"value": self.initial, "chunk": chunk.index}

    def validate(self, graph, chunk):
        self._call("validate")
        self.validated.append(graph["value"])
        graph["normalized"] = True
        return [Issue("value", "must be non-negative")] if graph["value"] < 0 else []

    def review(self, graph, chunk):
        self._call("review")
        assert graph["normalized"]
        decision = next(self.decisions)
        return ReviewResult(decision, [Issue("value", "old review issue")] if decision != "pass" else [])

    def repair(self, graph, chunk, issues):
        self._call("repair")
        self.repair_issues.append(issues)
        return {"value": self.repaired, "chunk": chunk.index}

    async def aextract(self, chunk):
        await asyncio.sleep(0)
        return self.extract(chunk)

    async def areview(self, graph, chunk):
        await asyncio.sleep(0)
        return self.review(graph, chunk)

    async def arepair(self, graph, chunk, issues):
        await asyncio.sleep(0)
        return self.repair(graph, chunk, issues)


def run(bundle, **limits):
    return run_chunk(bundle=bundle, chunk=ChunkInput(7, "text"), options=ExtractionOptions(**limits))


def test_success_uses_normalized_graph_and_counts_calls():
    bundle = ScriptedBundle()
    result = run(bundle)
    assert result.status == "final"
    assert result.index == 7
    assert result.graph == {"value": 1, "chunk": 7, "normalized": True}
    assert bundle.calls == ["extract", "validate", "review"]
    assert (result.reviews_used, result.fixes_used, result.llm_calls) == (1, 0, 2)
    assert result.issues == [] and result.stage is None


@pytest.mark.parametrize(
    ("bundle_kwargs", "limits", "status", "reason", "counts"),
    [
        ({}, {"max_reviews": 0}, "candidate", "review_budget_exhausted", (0, 0, 1)),
        ({"initial": -1}, {"max_fixes": 0}, "blocked", "validation_failed", (0, 0, 1)),
        ({"initial": -1, "repaired": -2}, {}, "blocked", "validation_failed", (0, 1, 2)),
        ({"decisions": ("fix",)}, {"max_fixes": 0}, "candidate", "fix_budget_exhausted", (1, 0, 2)),
        ({"decisions": ("block",)}, {}, "blocked", "review_blocked", (1, 0, 2)),
        ({"decisions": ("fix", "fix")}, {}, "candidate", "fix_budget_exhausted", (2, 1, 4)),
    ],
)
def test_terminal_and_budget_matrix(bundle_kwargs, limits, status, reason, counts):
    result = run(ScriptedBundle(**bundle_kwargs), **limits)
    assert (result.status, result.reason) == (status, reason)
    assert (result.reviews_used, result.fixes_used, result.llm_calls) == counts
    assert result.llm_calls <= 1 + ExtractionOptions(**limits).max_reviews + ExtractionOptions(**limits).max_fixes


def test_validation_issues_reach_repair_then_replacement_is_reviewed():
    bundle = ScriptedBundle(initial=-1)
    result = run(bundle)
    assert result.status == "final" and result.graph["value"] == 2
    assert bundle.validated == [-1, 2]
    assert bundle.repair_issues[0][0].message == "must be non-negative"
    assert (result.reviews_used, result.fixes_used, result.llm_calls) == (1, 1, 3)


def test_repaired_graph_never_keeps_previous_review_issues():
    bundle = ScriptedBundle(decisions=("fix",))
    result = run(bundle, max_reviews=1)
    assert result.status == "candidate"
    assert result.reason == "review_budget_exhausted"
    assert result.graph["value"] == 2
    assert result.issues == []
    assert bundle.validated == [1, 2]
    assert bundle.repair_issues[0][0].message == "old review issue"


def test_repair_introducing_invalid_graph_must_be_revalidated():
    result = run(ScriptedBundle(decisions=("fix",), repaired=-1))
    assert result.status == "blocked"
    assert result.graph["value"] == -1
    assert [issue.message for issue in result.issues] == ["must be non-negative"]
    assert (result.reviews_used, result.fixes_used, result.llm_calls) == (1, 1, 3)


def test_review_runs_again_on_repaired_graph():
    bundle = ScriptedBundle(decisions=("fix", "pass"))
    result = run(bundle)
    assert result.status == "final" and result.graph["value"] == 2
    assert bundle.calls == ["extract", "validate", "review", "repair", "validate", "review"]
    assert (result.reviews_used, result.fixes_used, result.llm_calls) == (2, 1, 4)


@pytest.mark.parametrize(
    ("stage", "counts", "has_graph"),
    [
        ("extract", (0, 0, 1), False),
        ("validate", (0, 0, 1), True),
        ("review", (1, 0, 2), True),
        ("repair", (1, 1, 3), True),
    ],
)
def test_failures_count_attempts_and_preserve_previous_graph(stage, counts, has_graph):
    result = run(ScriptedBundle(decisions=("fix",), fail_at=stage))
    assert result.status == "failed" and result.stage == stage
    assert result.reason == f"{stage}_failed: ValueError"
    assert (result.reviews_used, result.fixes_used, result.llm_calls) == counts
    assert (result.graph is not None) == has_graph
    if has_graph:
        assert result.graph["value"] == 1
    if stage == "repair":
        assert [issue.message for issue in result.issues] == ["old review issue"]


def test_repeated_chunk_runs_do_not_leak_state():
    first = run_chunk(
        bundle=ScriptedBundle(decisions=("fix", "pass")), chunk=ChunkInput(0, "a"), options=ExtractionOptions()
    )
    second = run_chunk(bundle=ScriptedBundle(), chunk=ChunkInput(1, "b"), options=ExtractionOptions())
    assert (first.graph["value"], first.fixes_used) == (2, 1)
    assert (second.graph["value"], second.fixes_used, second.llm_calls) == (1, 0, 2)


@pytest.mark.parametrize(
    ("stage", "counts", "has_graph"),
    [("extract", (0, 0, 1), False), ("review", (1, 0, 2), True), ("repair", (1, 1, 3), True)],
)
def test_output_truncation_has_public_reason_and_preserves_graph(stage, counts, has_graph):
    class TruncatedBundle(ScriptedBundle):
        def _call(self, called_stage):
            super()._call(called_stage)
            if called_stage == stage:
                raise LLMOutputTruncatedError()

    result = run(TruncatedBundle(decisions=("fix",)))
    assert result.status == "failed"
    assert result.stage == stage
    assert result.reason == f"{stage}_output_truncated: finish_reason=length"
    assert (result.reviews_used, result.fixes_used, result.llm_calls) == counts
    assert (result.graph is not None) == has_graph
    if has_graph:
        assert result.graph["value"] == 1
    if stage == "repair":
        assert [issue.message for issue in result.issues] == ["old review issue"]


def test_batch_keeps_input_order_and_limits_whole_chunk_concurrency():
    barrier = Barrier(2, timeout=5)
    lock = Lock()
    active = peak = 0
    completed = []
    release_first = Event()

    class ConcurrentBundle(ScriptedBundle):
        def extract(self, chunk):
            barrier.wait()
            return super().extract(chunk)

        def review(self, graph, chunk):
            nonlocal active
            if chunk.index == 9:
                assert release_first.wait(5)
            result = super().review(graph, chunk)
            with lock:
                completed.append(chunk.index)
                active -= 1
            if chunk.index == 3:
                release_first.set()
            return result

    def prepare(chunk):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        return ConcurrentBundle()

    results = run_chunks(
        chunks=[ChunkInput(i, "text") for i in (9, 3, 6, 0)], prepare=prepare, options=ExtractionOptions(max_workers=2)
    )
    assert [result.index for result in results] == [9, 3, 6, 0]
    assert completed[0] == 3
    assert peak == 2 and active == 0
    assert all(result.status == "final" for result in results)
    assert [result.graph["chunk"] for result in results] == [9, 3, 6, 0]


def test_preparation_and_model_failures_do_not_discard_other_chunks():
    def prepare(chunk):
        if chunk.index == 1:
            raise RuntimeError("cannot construct client")
        return ScriptedBundle(fail_at="review" if chunk.index == 2 else None)

    results = run_chunks(
        chunks=[ChunkInput(i, "text") for i in range(4)], prepare=prepare, options=ExtractionOptions(max_workers=2)
    )
    assert [result.status for result in results] == ["final", "failed", "failed", "final"]
    assert results[1].stage == "prepare" and results[1].graph is None
    assert results[1].llm_calls == results[1].reviews_used == results[1].fixes_used == 0
    assert results[2].stage == "review" and results[2].llm_calls == 2


def test_parallel_repairs_keep_graphs_issues_and_budgets_local():
    results = run_chunks(
        chunks=[ChunkInput(i, "text") for i in range(5)],
        prepare=lambda chunk: ScriptedBundle(
            initial=chunk.index, repaired=100 + chunk.index, decisions=("fix", "pass")
        ),
        options=ExtractionOptions(max_workers=3),
    )
    assert [result.graph["value"] for result in results] == list(range(100, 105))
    assert all((result.reviews_used, result.fixes_used, result.llm_calls) == (2, 1, 4) for result in results)
    assert all(result.status == "final" and result.issues == [] for result in results)


def test_serial_batch_and_empty_input():
    seen = []

    def prepare(chunk):
        seen.append(chunk.index)
        return ScriptedBundle()

    options = ExtractionOptions(max_workers=1)
    assert run_chunks(chunks=[], prepare=prepare, options=options) == ()
    results = run_chunks(chunks=[ChunkInput(2, "b"), ChunkInput(1, "a")], prepare=prepare, options=options)
    assert seen == [2, 1] and [result.index for result in results] == [2, 1]


def test_serial_batch_preserves_the_calling_thread_for_injected_clients():
    caller_thread = get_ident()

    class ThreadBoundBundle(ScriptedBundle):
        def _call(self, stage):
            assert get_ident() == caller_thread
            super()._call(stage)

    def prepare(chunk):
        assert get_ident() == caller_thread
        return ThreadBoundBundle()

    results = run_chunks(chunks=[ChunkInput(i, "text") for i in range(2)], prepare=prepare, options=ExtractionOptions())
    assert all(result.status == "final" for result in results)


def test_input_iteration_errors_propagate_after_started_work_finishes():
    completed = Event()

    class CompletingBundle(ScriptedBundle):
        def review(self, graph, chunk):
            result = super().review(graph, chunk)
            completed.set()
            return result

    def chunks():
        yield ChunkInput(0, "text")
        raise ValueError("broken input iterator")

    with pytest.raises(ValueError, match="broken input iterator"):
        run_chunks(chunks=chunks(), prepare=lambda chunk: CompletingBundle(), options=ExtractionOptions(max_workers=1))
    assert completed.is_set()


@pytest.mark.parametrize("field", ["max_reviews", "max_fixes", "max_workers"])
@pytest.mark.parametrize("value", [-1, True, 1.5, "2"])
def test_options_reject_invalid_limits(field, value):
    with pytest.raises(ValidationError):
        ExtractionOptions(**{field: value})


def test_options_allow_zero_business_budgets_but_require_workers():
    assert ExtractionOptions(max_reviews=0, max_fixes=0).max_workers == 1
    with pytest.raises(ValidationError):
        ExtractionOptions(max_workers=0)


@pytest.mark.parametrize("field, upper", [("max_reviews", 5), ("max_fixes", 3), ("max_workers", 8)])
def test_options_accept_upper_boundary_and_reject_excess(field, upper):
    assert getattr(ExtractionOptions(**{field: upper}), field) == upper
    with pytest.raises(ValidationError) as exc_info:
        ExtractionOptions(**{field: upper + 1})
    error = exc_info.value.errors()[0]
    assert error["loc"] == (field,)
    assert error["type"] == "less_than_equal"


def test_options_reject_unknown_fields_instead_of_using_defaults():
    with pytest.raises(ValidationError) as exc_info:
        ExtractionOptions(max_review=0)
    error = exc_info.value.errors()[0]
    assert error["loc"] == ("max_review",)
    assert error["type"] == "extra_forbidden"


def test_result_serializes_issues_and_detaches_payload():
    result = ChunkResult(
        0, "blocked", {"vertices": []}, [Issue("vertices", "missing", "Alice")], "invalid", None, 0, 0, 1
    )
    payload = result.as_dict()
    assert payload["issues"] == [{"path": "vertices", "message": "missing", "evidence": "Alice"}]
    payload["graph"]["vertices"].append({"id": "new"})
    assert result.graph == {"vertices": []}


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("initial,status", [(1, "validated"), (-1, "blocked")])
def test_disabling_review_never_repairs_or_claims_final(asynchronous, initial, status):
    bundle = ScriptedBundle(initial=initial)
    kwargs = {"bundle": bundle, "chunk": ChunkInput(0, "text"), "options": ExtractionOptions(), "review": False}
    result = asyncio.run(arun_chunk(**kwargs)) if asynchronous else run_chunk(**kwargs)
    assert result.status == status
    assert bundle.calls == ["extract", "validate"]
    assert (result.reviews_used, result.fixes_used, result.llm_calls) == (0, 0, 1)
    assert result.reason == ("review_disabled" if status == "validated" else "validation_failed")


@pytest.mark.parametrize(
    "bundle_kwargs,limits",
    [
        ({}, {}),
        ({}, {"max_reviews": 0}),
        ({"initial": -1}, {"max_fixes": 0}),
        ({"initial": -1, "repaired": -2}, {}),
        ({"initial": -1}, {}),
        ({"decisions": ("fix",)}, {"max_fixes": 0}),
        ({"decisions": ("block",)}, {}),
        ({"decisions": ("fix", "pass")}, {}),
        ({"decisions": ("fix", "fix")}, {}),
        ({"decisions": ("fix",)}, {"max_reviews": 1}),
        ({"decisions": ("fix",), "repaired": -1}, {}),
        *[({"decisions": ("fix",), "fail_at": stage}, {}) for stage in ("extract", "validate", "review", "repair")],
    ],
)
def test_async_engine_preserves_sync_states_budgets_and_failures(bundle_kwargs, limits):
    options = ExtractionOptions(**limits)
    chunk = ChunkInput(7, "text")
    sync_bundle = ScriptedBundle(**bundle_kwargs)
    async_bundle = ScriptedBundle(**bundle_kwargs)
    expected = run_chunk(bundle=sync_bundle, chunk=chunk, options=options)
    actual = asyncio.run(arun_chunk(bundle=async_bundle, chunk=chunk, options=options))
    assert actual == expected
    assert async_bundle.calls == sync_bundle.calls
    assert async_bundle.repair_issues == sync_bundle.repair_issues


@pytest.mark.parametrize("stage", ["extract", "review", "repair"])
def test_async_truncation_preserves_stage_and_graph(stage):
    class TruncatedBundle(ScriptedBundle):
        def _call(self, called_stage):
            super()._call(called_stage)
            if called_stage == stage:
                raise LLMOutputTruncatedError("done_reason=length")

    result = asyncio.run(
        arun_chunk(
            bundle=TruncatedBundle(decisions=("fix",)),
            chunk=ChunkInput(0, "text"),
            options=ExtractionOptions(),
        )
    )
    assert result.status == "failed"
    assert result.stage == stage
    assert result.reason == f"{stage}_output_truncated: done_reason=length"
    assert (result.graph is not None) == (stage != "extract")


def test_async_batch_limits_whole_chunk_and_retains_input_order():
    async def scenario():
        active = peak = 0
        release_first = asyncio.Event()
        completed = []
        bundles = []

        class ConcurrentBundle(ScriptedBundle):
            async def areview(self, graph, chunk):
                nonlocal active
                if chunk.index == 9:
                    await release_first.wait()
                result = await super().areview(graph, chunk)
                completed.append(chunk.index)
                active -= 1
                if chunk.index == 3:
                    release_first.set()
                return result

        async def prepare(chunk):
            nonlocal active, peak
            active += 1
            peak = max(active, peak)
            await asyncio.sleep(0)
            bundle = ConcurrentBundle()
            bundles.append(bundle)
            return bundle

        results = await asyncio.wait_for(
            arun_chunks(
                chunks=[ChunkInput(i, "text") for i in (9, 3, 6, 0)],
                prepare=prepare,
                options=ExtractionOptions(max_workers=2),
            ),
            timeout=5,
        )
        assert [result.index for result in results] == [9, 3, 6, 0]
        assert completed[0] == 3
        assert peak == 2 and active == 0
        assert len({id(bundle) for bundle in bundles}) == 4
        assert all(result.status == "final" for result in results)

    asyncio.run(scenario())


def test_async_batch_preparation_failures_and_model_failures_are_isolated():
    async def prepare(chunk):
        if chunk.index == 1:
            raise RuntimeError("cannot construct client")
        return ScriptedBundle(fail_at="review" if chunk.index == 2 else None)

    results = asyncio.run(
        arun_chunks(
            chunks=[ChunkInput(i, "text") for i in range(4)],
            prepare=prepare,
            options=ExtractionOptions(max_workers=2),
        )
    )
    assert [result.status for result in results] == ["final", "failed", "failed", "final"]
    assert results[1].stage == "prepare" and results[1].llm_calls == 0
    assert results[2].stage == "review" and results[2].llm_calls == 2


@pytest.mark.parametrize("cancel_stage", ["prepare", "extract", "review", "repair"])
def test_async_cancellation_cleans_workers_and_starts_no_further_chunks(cancel_stage):
    async def scenario():
        prepared = []
        active = 0
        started = asyncio.Event()
        never = asyncio.Event()

        async def block():
            nonlocal active
            active += 1
            if active == 2:
                started.set()
            try:
                await never.wait()
            finally:
                active -= 1

        class CancellableBundle(ScriptedBundle):
            async def aextract(self, chunk):
                if cancel_stage == "extract":
                    await block()
                return await super().aextract(chunk)

            async def areview(self, graph, chunk):
                if cancel_stage == "review":
                    await block()
                return await super().areview(graph, chunk)

            async def arepair(self, graph, chunk, issues):
                if cancel_stage == "repair":
                    await block()
                return await super().arepair(graph, chunk, issues)

        async def prepare(chunk):
            prepared.append(chunk.index)
            if cancel_stage == "prepare":
                await block()
            return CancellableBundle(decisions=("fix", "pass"))

        tasks_before = asyncio.all_tasks()
        task = asyncio.create_task(
            arun_chunks(
                chunks=[ChunkInput(i, "text") for i in range(10)],
                prepare=prepare,
                options=ExtractionOptions(max_workers=2),
            )
        )
        await asyncio.wait_for(started.wait(), timeout=5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert prepared == [0, 1]
        assert active == 0
        assert not (asyncio.all_tasks() - tasks_before)

    asyncio.run(scenario())


def test_async_iterator_failure_cancels_already_running_chunks():
    async def scenario():
        cleaned = asyncio.Event()

        class WaitingBundle(ScriptedBundle):
            async def aextract(self, chunk):
                try:
                    await asyncio.Event().wait()
                finally:
                    cleaned.set()

        def chunks():
            yield ChunkInput(0, "text")
            raise ValueError("broken iterator")

        with pytest.raises(ValueError, match="broken iterator"):
            await arun_chunks(
                chunks=chunks(), prepare=lambda _: WaitingBundle(), options=ExtractionOptions(max_workers=2)
            )
        assert cleaned.is_set()

    asyncio.run(scenario())


def test_async_empty_and_review_disabled_batches():
    options = ExtractionOptions(max_workers=2)
    assert asyncio.run(arun_chunks(chunks=[], prepare=lambda _: ScriptedBundle(), options=options)) == ()
    results = asyncio.run(
        arun_chunks(
            chunks=[ChunkInput(2, "b"), ChunkInput(1, "a")],
            prepare=lambda _: ScriptedBundle(),
            options=options,
            review=False,
        )
    )
    assert [result.index for result in results] == [2, 1]
    assert all(result.status == "validated" and result.llm_calls == 1 for result in results)
