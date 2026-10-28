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

"""Public SDK contracts exercised with the real graph domain and runtime."""

import asyncio
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy

import pytest

from hugegraph_llm_core import (
    ExtractionOptions,
    FunctionModel,
    GraphPrompts,
    Issue,
    adesign_schema,
    aextract_graph,
    design_schema,
    extract_graph,
    validate_schema,
)

SCHEMA = {
    "propertykeys": [{"name": "name", "data_type": "TEXT", "cardinality": "SINGLE"}],
    "vertexlabels": [{"name": "person", "properties": ["name"], "primary_keys": ["name"], "nullable_keys": []}],
    "edgelabels": [],
}
PASS = json.dumps({"decision": "pass", "issues": []})


def graph(name="Alice", label="person"):
    return {
        "vertices": [{"id": name, "label": label, "properties": {"name": name}}],
        "edges": [],
    }


class ScriptedModel:
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.prompts = []

    def generate(self, *, prompt):
        self.prompts.append(prompt)
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


def test_design_edit_validate_extract_is_one_independent_library_flow():
    model = ScriptedModel(json.dumps(SCHEMA), json.dumps(graph(label="contact")), PASS)
    draft = design_schema("Alice is a person.", model=model, questions=["Who is mentioned?"])
    assert draft.issues == []
    draft.schema["vertexlabels"][0]["name"] = "contact"
    assert validate_schema(draft.schema) == []

    result = extract_graph("Alice is a contact.", schema=draft.schema, model=model)

    assert result.status == "succeeded"
    assert [chunk.status for chunk in result.chunks] == ["final"]
    assert result.graph["vertices"][0]["label"] == "contact"
    assert result.chunks[0].llm_calls == 2
    assert len(model.prompts) == 3


def test_review_false_accepts_validated_graph_without_review_or_repair():
    model = ScriptedModel(json.dumps(graph()))
    result = extract_graph("Alice", schema=SCHEMA, model=model, review=False)
    assert result.status == "succeeded"
    assert result.chunks[0].status == "validated"
    assert result.chunks[0].reviews_used == result.chunks[0].fixes_used == 0
    assert result.chunks[0].llm_calls == len(model.prompts) == 1
    assert result.graph["vertices"][0]["properties"]["name"] == "Alice"


def test_default_sync_call_keeps_caller_owned_model_on_its_own_thread():
    caller_thread = threading.get_ident()
    called_on = []

    def generate(prompt):
        called_on.append(threading.get_ident())
        return json.dumps(graph())

    result = extract_graph("Alice", schema=SCHEMA, model=FunctionModel(generate=generate), review=False)
    assert result.status == "succeeded"
    assert called_on == [caller_thread]


def test_review_false_blocks_invalid_graph_without_attempting_repair():
    model = ScriptedModel(json.dumps(graph(label="unknown")))
    result = extract_graph("Alice", schema=SCHEMA, model=model, review=False)
    assert result.status == "failed"
    assert result.chunks[0].status == "blocked"
    assert result.chunks[0].issues
    assert result.graph == {"vertices": [], "edges": []}
    assert len(model.prompts) == 1


def test_prechunked_input_keeps_order_and_retains_partial_failures():
    model = ScriptedModel(json.dumps(graph("Alice")), RuntimeError("provider unavailable"), json.dumps(graph("Carol")))
    result = extract_graph(["Alice", "Bob", "Carol"], schema=SCHEMA, model=model, review=False)
    assert result.status == "partial"
    assert [chunk.index for chunk in result.chunks] == [0, 1, 2]
    assert [chunk.status for chunk in result.chunks] == ["validated", "failed", "validated"]
    assert [vertex["properties"]["name"] for vertex in result.graph["vertices"]] == ["Alice", "Carol"]
    assert result.chunks[1].stage == "extract"


@pytest.mark.parametrize("texts", ["", " \n ", [], ["Alice", ""], [1], 12])
def test_invalid_text_input_never_calls_model(texts):
    model = ScriptedModel()
    with pytest.raises((TypeError, ValueError)):
        extract_graph(texts, schema=SCHEMA, model=model)
    assert model.prompts == []


def test_invalid_schema_never_creates_a_model_or_mutates_the_schema():
    invalid_schema = deepcopy(SCHEMA)
    invalid_schema["edgelabels"] = [{"name": "knows", "source_label": "person", "target_label": "missing"}]
    before = deepcopy(invalid_schema)
    created = []

    def factory():
        created.append(True)
        return ScriptedModel()

    with pytest.raises(ValueError):
        extract_graph("Alice", schema=invalid_schema, model_factory=factory)
    assert created == []
    assert invalid_schema == before


def test_model_and_factory_are_exclusive_and_required():
    model = ScriptedModel()
    for kwargs in ({}, {"model": model, "model_factory": lambda: model}):
        with pytest.raises((TypeError, ValueError)):
            extract_graph("Alice", schema=SCHEMA, **kwargs)
    assert model.prompts == []


def test_parallelism_requires_factory_before_any_model_call():
    model = ScriptedModel()
    with pytest.raises(ValueError):
        extract_graph(["Alice", "Bob"], schema=SCHEMA, model=model, options=ExtractionOptions(max_workers=2))
    assert model.prompts == []


def test_async_model_factory_is_rejected_before_execution():
    called = []

    async def factory():
        called.append(True)
        return ScriptedModel()

    with pytest.raises((TypeError, ValueError)):
        extract_graph("Alice", schema=SCHEMA, model_factory=factory)
    assert called == []


def test_async_callable_factory_is_rejected_before_execution():
    called = []

    class Factory:
        async def __call__(self):
            called.append(True)
            return ScriptedModel()

    with pytest.raises((TypeError, ValueError)):
        extract_graph("Alice", schema=SCHEMA, model_factory=Factory())
    assert called == []


def test_async_business_validator_is_rejected_before_model_call():
    model = ScriptedModel(json.dumps(graph()), PASS)

    async def check(candidate, supplied_schema, text):
        return []

    with pytest.raises((TypeError, ValueError)):
        extract_graph("Alice", schema=SCHEMA, model=model, validators=[check])
    assert model.prompts == []


@pytest.mark.parametrize("field", ["extract", "review", "repair"])
def test_invalid_prompt_type_is_rejected_before_model_call(field):
    model = ScriptedModel(json.dumps(graph()), PASS)
    with pytest.raises((TypeError, ValueError)):
        extract_graph("Alice", schema=SCHEMA, model=model, prompts=GraphPrompts(**{field: None}))
    assert model.prompts == []


def test_factory_creates_independent_models_for_parallel_chunks():
    barrier = threading.Barrier(2)
    instances = []

    class IndependentModel:
        calls = 0

        def generate(self, *, prompt):
            self.calls += 1
            barrier.wait(timeout=5)
            return json.dumps({"vertices": [], "edges": []})

    def factory():
        instance = IndependentModel()
        instances.append(instance)
        return instance

    result = extract_graph(
        ["Alice", "Bob"], schema=SCHEMA, model_factory=factory, review=False, options=ExtractionOptions(max_workers=2)
    )
    assert result.status == "succeeded"
    assert len(instances) == 2 and instances[0] is not instances[1]
    assert [instance.calls for instance in instances] == [1, 1]


def test_custom_validation_rechecks_repaired_graph_and_preserves_caller_schema():
    observations = []
    schema = deepcopy(SCHEMA)
    model = ScriptedModel(json.dumps(graph("Bob")), json.dumps(graph("Alice")), PASS)

    def check_name(candidate, supplied_schema, text):
        name = candidate["vertices"][0]["properties"]["name"]
        observations.append((name, supplied_schema, text))
        return [] if name == "Alice" else [Issue("vertices[0].properties.name", "Use the name from the source.")]

    result = extract_graph("Alice", schema=schema, model=model, validators=[check_name])
    assert result.status == "succeeded"
    assert [entry[0] for entry in observations] == ["Bob", "Alice"]
    assert all(entry[2] == "Alice" for entry in observations)
    assert result.chunks[0].fixes_used == result.chunks[0].reviews_used == 1
    assert schema == SCHEMA


def test_prompts_and_schemas_are_local_to_each_call():
    first = ScriptedModel(json.dumps(graph()), PASS)
    second = ScriptedModel(json.dumps(graph("Bob")), PASS)
    first_schema = deepcopy(SCHEMA)
    second_schema = deepcopy(SCHEMA)
    extract_graph(
        "Alice", schema=first_schema, model=first, prompts=GraphPrompts(extract="FIRST_EXTRACT", review="FIRST_REVIEW")
    )
    extract_graph(
        "Bob",
        schema=second_schema,
        model=second,
        prompts=GraphPrompts(extract="SECOND_EXTRACT", review="SECOND_REVIEW"),
    )
    assert "FIRST_EXTRACT" in first.prompts[0] and "FIRST_REVIEW" in first.prompts[1]
    assert "SECOND_EXTRACT" in second.prompts[0] and "SECOND_REVIEW" in second.prompts[1]
    assert all("FIRST_" not in prompt for prompt in second.prompts)
    assert first_schema == second_schema == SCHEMA


def test_overlapping_calls_cannot_change_each_others_schema_or_prompts():
    extracted = threading.Barrier(2)
    models = []

    def execute(name):
        local_schema = deepcopy(SCHEMA)
        local_schema["vertexlabels"][0]["name"] = name

        class IsolatedModel(ScriptedModel):
            def generate(self, *, prompt):
                result = super().generate(prompt=prompt)
                if len(self.prompts) == 1:
                    extracted.wait(timeout=5)
                return result

        model = IsolatedModel(json.dumps(graph(name, label=name)), PASS)
        models.append((name, model))
        result = extract_graph(
            name,
            schema=local_schema,
            model=model,
            prompts=GraphPrompts(extract=f"EXTRACT_{name}", review=f"REVIEW_{name}"),
        )
        assert result.status == "succeeded"
        assert result.graph["vertices"][0]["label"] == name

    with ThreadPoolExecutor(max_workers=2) as executor:
        tuple(executor.map(execute, ["Alice", "Bob"]))
    for name, model in models:
        assert f"EXTRACT_{name}" in model.prompts[0]
        assert f"REVIEW_{name}" in model.prompts[1]
        assert f'"name": "{name}"' in model.prompts[1]


def test_native_async_design_and_extract_do_not_require_sync_methods():
    async def scenario():
        responses = iter([json.dumps(SCHEMA), json.dumps(graph()), PASS])
        calls = []

        async def generate(prompt):
            await asyncio.sleep(0)
            calls.append(prompt)
            return next(responses)

        model = FunctionModel(agenerate=generate)
        draft = await adesign_schema("Alice", model=model)
        result = await aextract_graph("Alice", schema=draft.schema, model=model)
        assert draft.issues == []
        assert result.status == "succeeded" and result.chunks[0].status == "final"
        assert len(calls) == 3

    asyncio.run(scenario())


def test_async_parallel_completion_preserves_input_order():
    async def scenario():
        second_completed = asyncio.Event()
        created = []
        completion_order = []

        def factory():
            index = len(created)
            created.append(index)

            async def generate(prompt):
                if index == 0:
                    await second_completed.wait()
                completion_order.append(index)
                if index == 1:
                    second_completed.set()
                return json.dumps(graph(["Alice", "Bob"][index]))

            return FunctionModel(agenerate=generate)

        result = await asyncio.wait_for(
            aextract_graph(
                ["Alice", "Bob"],
                schema=SCHEMA,
                model_factory=factory,
                review=False,
                options=ExtractionOptions(max_workers=2),
            ),
            timeout=2,
        )
        assert completion_order == [1, 0]
        assert [chunk.index for chunk in result.chunks] == [0, 1]
        assert [vertex["properties"]["name"] for vertex in result.graph["vertices"]] == ["Alice", "Bob"]

    asyncio.run(scenario())


def test_async_cancellation_propagates_and_does_not_start_the_next_chunk():
    async def scenario():
        entered = asyncio.Event()
        never = asyncio.Event()
        calls = []

        async def generate(prompt):
            calls.append(prompt)
            entered.set()
            await never.wait()
            return json.dumps(graph())

        task = asyncio.create_task(
            aextract_graph(["Alice", "Bob"], schema=SCHEMA, model=FunctionModel(agenerate=generate))
        )
        await asyncio.wait_for(entered.wait(), timeout=2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert len(calls) == 1

    asyncio.run(scenario())
