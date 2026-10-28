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
import json
import threading
from copy import deepcopy
from dataclasses import FrozenInstanceError

import pytest

from hugegraph_llm_core import aextract_graph, extract_graph
from hugegraph_llm_core.errors import ModelOutputError, SchemaValidationError
from hugegraph_llm_core.models import FunctionModel, ThreadedModel
from hugegraph_llm_core.prompts import DEFAULT_EXTRACT_PROMPT_CN, GraphPrompts
from hugegraph_llm_core.schema import (
    adesign_schema,
    build_schema_prompt,
    choose_schema_examples,
    design_schema,
    normalize_few_shot_schema,
    normalize_few_shot_schema_json,
    normalize_query_examples,
    normalize_query_examples_json,
    parse_schema_response,
    validate_schema,
)


@pytest.fixture
def schema():
    return {
        "vertexlabels": [
            {"id": 1, "name": "person", "properties": ["name"], "primary_keys": ["name"], "id_strategy": "PRIMARY_KEY"}
        ],
        "edgelabels": [{"name": "knows", "source_label": "person", "target_label": "person", "properties": ["since"]}],
        "propertykeys": [
            {"name": "name", "data_type": "TEXT", "cardinality": "SINGLE"},
            {"name": "since", "data_type": "DATE", "cardinality": "SINGLE"},
        ],
    }


def test_validation_preserves_complete_schema_and_optional_server_metadata(schema):
    schema["vertexlabels"][0].update({"userdata": {"owner": "团队"}, "enable_label_index": True, "ttl": 0})
    schema["indexlabels"] = [
        {"name": "by_name", "base_type": "VERTEX_LABEL", "base_value": "person", "fields": ["name"]}
    ]
    before = deepcopy(schema)
    assert validate_schema(schema) == []
    assert schema == before


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), -float("inf"), object(), {1, 2}, (1, 2)])
def test_schema_metadata_must_be_json_before_sync_or_async_extraction(invalid):
    metadata = {"bad": invalid}
    schema = {"vertexlabels": [], "edgelabels": [], "userdata": metadata}
    calls = []

    def generate(prompt):
        calls.append(prompt)
        return '{"vertices": [], "edges": []}'

    async def agenerate(prompt):
        return generate(prompt)

    model = FunctionModel(generate=generate, agenerate=agenerate)
    assert any(issue.path == "schema.userdata.bad" for issue in validate_schema(schema))
    for review in (True, False):
        with pytest.raises(SchemaValidationError):
            extract_graph("Alice", schema=schema, model=model, review=review)
        with pytest.raises(SchemaValidationError):
            asyncio.run(aextract_graph("Alice", schema=schema, model=model, review=review))
    assert calls == []
    assert schema["userdata"] is metadata and metadata["bad"] is invalid


def test_metadata_cycles_and_non_string_keys_are_rejected_but_shared_values_are_valid():
    shared = {"source": "document"}
    schema = {"vertexlabels": [], "edgelabels": [], "userdata": {"first": shared, "second": shared}}
    assert validate_schema(schema) == []
    shared["cycle"] = shared
    assert any("Circular references" in issue.message for issue in validate_schema(schema))
    del shared["cycle"]
    shared[42] = "would be silently coerced to a string"
    assert any("keys must be strings" in issue.message for issue in validate_schema(schema))


@pytest.mark.parametrize("cardinality,value", [("SINGLE", {"source": "invoice"}), ("LIST", [{"source": "invoice"}])])
def test_object_property_type_is_supported_through_public_extraction(cardinality, value):
    schema = {
        "vertexlabels": [{"name": "record", "id_strategy": "CUSTOMIZE_STRING", "properties": ["data"]}],
        "edgelabels": [],
        "propertykeys": [{"name": "data", "data_type": "OBJECT", "cardinality": cardinality}],
    }
    graph = {"vertices": [{"id": "record-1", "label": "record", "properties": {"data": value}}], "edges": []}
    assert validate_schema(schema) == []
    result = extract_graph(
        "An invoice record", schema=schema, model=FunctionModel(generate=lambda _: json.dumps(graph)), review=False
    )
    assert result.status == "succeeded"
    assert len(result.graph["vertices"]) == 1
    assert result.graph["vertices"][0]["id"] == "record-1"
    assert result.graph["vertices"][0]["properties"] == {"data": value}
    assert result.graph["edges"] == []


def test_simplified_schema_is_not_completed_or_mutated():
    schema = {"vertexlabels": [{"name": "person", "properties": ["name"]}], "edgelabels": []}
    before = deepcopy(schema)
    assert validate_schema(schema) == []
    assert schema == before


@pytest.mark.parametrize("strategy", ["AUTOMATIC", "CUSTOMIZE_STRING", "CUSTOMIZE_NUMBER", "CUSTOMIZE_UUID"])
def test_custom_and_automatic_ids_do_not_require_primary_keys_or_properties(strategy):
    schema = {"vertexlabels": [{"name": "person", "id_strategy": strategy}], "edgelabels": []}
    assert validate_schema(schema) == []
    assert "primary_keys" not in schema["vertexlabels"][0]


@pytest.mark.parametrize(
    ("value", "path"),
    [
        (None, "schema"),
        ([], "schema"),
        ({}, "vertexlabels"),
        ({"vertexlabels": [], "edgelabels": None}, "edgelabels"),
        ({"vertexlabels": [None], "edgelabels": []}, "vertexlabels[0]"),
        ({"vertexlabels": [{"name": []}], "edgelabels": []}, "vertexlabels[0].name"),
        ({"vertexlabels": [{"name": "p", "properties": [None]}], "edgelabels": []}, "vertexlabels[0].properties[0]"),
        ({"vertexlabels": [], "edgelabels": [], "propertykeys": [1]}, "propertykeys[0]"),
    ],
)
def test_malformed_schema_returns_findings_without_raising(value, path):
    before = deepcopy(value)
    assert any(issue.path == path for issue in validate_schema(value))
    assert value == before


@pytest.mark.parametrize(
    ("collection", "field", "value", "expected_path"),
    [
        ("vertexlabels", "properties", ["unknown"], "vertexlabels[0].properties[0]"),
        ("vertexlabels", "properties", ["name", "name"], "vertexlabels[0].properties[1]"),
        ("vertexlabels", "primary_keys", ["unknown"], "vertexlabels[0].primary_keys"),
        ("vertexlabels", "primary_keys", [], "vertexlabels[0].primary_keys"),
        ("vertexlabels", "nullable_keys", ["name"], "vertexlabels[0].nullable_keys"),
        ("vertexlabels", "id_strategy", "UNKNOWN", "vertexlabels[0].id_strategy"),
        ("vertexlabels", "id", True, "vertexlabels[0].id"),
        ("vertexlabels", "properties", "name", "vertexlabels[0].properties"),
        ("edgelabels", "source_label", "missing", "edgelabels[0].source_label"),
        ("edgelabels", "target_label", ["person"], "edgelabels[0].target_label"),
        ("edgelabels", "sort_keys", ["name"], "edgelabels[0].sort_keys"),
        ("edgelabels", "nullable_keys", ["name"], "edgelabels[0].nullable_keys"),
        ("propertykeys", "data_type", "unknown", "propertykeys[0].data_type"),
        ("propertykeys", "cardinality", [], "propertykeys[0].cardinality"),
    ],
)
def test_invalid_references_and_enums_are_reported(schema, collection, field, value, expected_path):
    schema[collection][0][field] = value
    before = deepcopy(schema)
    assert any(issue.path == expected_path for issue in validate_schema(schema))
    assert schema == before


@pytest.mark.parametrize("collection", ["vertexlabels", "edgelabels", "propertykeys"])
def test_duplicate_names_are_reported_in_each_namespace(schema, collection):
    schema[collection].append(deepcopy(schema[collection][0]))
    assert any("Duplicate name" in issue.message for issue in validate_schema(schema))


def test_label_id_text_identity_collision_is_reported_before_extraction(schema):
    schema["vertexlabels"].append(
        {"id": "1", "name": "company", "properties": ["name"], "primary_keys": ["name"], "id_strategy": "PRIMARY_KEY"}
    )
    before = deepcopy(schema)
    findings = validate_schema(schema)
    assert any(issue.path == "vertexlabels[1].id" and "Duplicate schema ID" in issue.message for issue in findings)
    assert schema == before


def test_declared_property_key_collection_checks_references_even_when_empty(schema):
    del schema["propertykeys"]
    assert validate_schema(schema) == []
    schema["propertykeys"] = []
    assert any("Unknown property key" in issue.message for issue in validate_schema(schema))


def test_design_returns_invalid_draft_for_inspection_and_validates_with_no_default_writes():
    draft_schema = {"vertexlabels": [{"name": "person", "properties": ["name"]}], "edgelabels": [{"name": "knows"}]}
    requests = []

    def generate(prompt):
        requests.append(prompt)
        return json.dumps(draft_schema)

    draft = design_schema(
        ["Alice knows Bob"],
        model=FunctionModel(generate=generate),
        questions=["Who does Alice know?"],
        example_schema={},
    )
    assert draft.schema == draft_schema
    assert {issue.path for issue in draft.issues} == {"edgelabels[0].source_label", "edgelabels[0].target_label"}
    assert len(requests) == 1
    assert "Alice knows Bob" in requests[0] and "Who does Alice know?" in requests[0]
    assert "primary_keys" not in draft.schema["vertexlabels"][0]


@pytest.mark.parametrize(
    "response", ["", "  ", None, "invalid", "[]", "null", '{"x": 1, "x": 2}', '{"x": NaN}', '{"x": 1e400}']
)
def test_invalid_model_schema_output_is_an_explicit_error(response):
    with pytest.raises(ModelOutputError):
        design_schema("source", model=FunctionModel(generate=lambda _: response))


def test_model_failure_propagates_instead_of_becoming_a_schema_issue():
    def fail(_):
        raise ConnectionError("provider is unavailable")

    with pytest.raises(ConnectionError, match="provider is unavailable"):
        design_schema("source", model=FunctionModel(generate=fail))


def test_schema_parser_accepts_legacy_markdown_fences(schema):
    assert parse_schema_response("Here is the schema:\n```json\n" + json.dumps(schema) + "\n```\n") == schema


def test_async_schema_uses_async_model_inside_existing_event_loop(schema):
    async def scenario():
        loop = asyncio.get_running_loop()

        async def generate(prompt):
            assert asyncio.get_running_loop() is loop
            assert "Alice" in prompt
            await asyncio.sleep(0)
            return json.dumps(schema)

        draft = await adesign_schema("Alice", model=FunctionModel(agenerate=generate))
        assert draft.schema == schema
        assert draft.issues == []

    asyncio.run(scenario())


def test_async_requires_explicit_sync_adapter(schema):
    class SyncModel:
        thread_id = None

        def generate(self, *, prompt):
            self.thread_id = threading.get_ident()
            return json.dumps(schema)

    async def scenario():
        model = SyncModel()
        with pytest.raises(TypeError, match="agenerate"):
            await adesign_schema("Alice", model=model)
        assert model.thread_id is None
        draft = await adesign_schema("Alice", model=ThreadedModel(model))
        assert draft.schema == schema
        assert model.thread_id != threading.get_ident()

    asyncio.run(scenario())


@pytest.mark.parametrize("texts", ["", " \n", [], (), [" "], ["Alice", "\t"], ["Alice", None]])
def test_public_schema_design_rejects_empty_samples_before_any_model_call(texts):
    calls = []

    def generate(prompt):
        calls.append(prompt)
        return "{}"

    async def agenerate(prompt):
        calls.append(prompt)
        return "{}"

    model = FunctionModel(generate=generate, agenerate=agenerate)
    with pytest.raises(ValueError, match="non-empty"):
        design_schema(texts, model=model)
    with pytest.raises(ValueError, match="non-empty"):
        asyncio.run(adesign_schema(texts, model=model))
    assert calls == []


def test_schema_design_consumes_iterable_samples_once_and_legacy_prompt_still_allows_empty():
    seen = []

    def texts():
        seen.append("consumed")
        yield "Alice"

    draft = design_schema(texts(), model=FunctionModel(generate=lambda _: '{"vertexlabels": [], "edgelabels": []}'))
    assert draft.issues == []
    assert seen == ["consumed"]
    assert build_schema_prompt([])
    assert build_schema_prompt("")


def test_query_examples_normalize_ui_and_python_shapes_without_mutation():
    original = [" 找朋友 ", {"description": " Find Alice ", "gremlin": " g.V() ", "extra": True}]
    before = deepcopy(original)
    expected = [{"description": "找朋友", "gremlin": ""}, {"description": "Find Alice", "gremlin": "g.V()"}]
    assert normalize_query_examples(original) == expected
    assert json.loads(normalize_query_examples_json(json.dumps(original))) == expected
    assert original == before


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("not-json", "valid JSON"),
        ("{}", "JSON list"),
        ([" "], "non-empty string"),
        ([{"query": "Alice"}], "description"),
        ([{"description": "Alice"}], "gremlin"),
        ([42], "strings or objects"),
    ],
)
def test_query_example_validation_messages_are_usable_by_legacy_ui(value, message):
    with pytest.raises(ValueError, match=message):
        normalize_query_examples(value)


def test_few_shot_shape_validation_preserves_invalid_semantic_draft_without_aliasing():
    original = {"vertexlabels": [{"name": "person"}]}
    result = normalize_few_shot_schema(original)
    assert result == original and result is not original
    result["vertexlabels"][0]["name"] = "changed"
    assert original["vertexlabels"][0]["name"] == "person"
    with pytest.raises(ValueError, match="JSON object"):
        normalize_few_shot_schema("[]")
    with pytest.raises(ValueError, match="valid JSON"):
        normalize_few_shot_schema("{")


def test_blank_examples_use_supplied_defaults_but_explicit_empty_values_are_retained(schema):
    assert normalize_query_examples_json(" ") == normalize_few_shot_schema_json(None) == ""
    questions, example = choose_schema_examples("", "", default_questions=["Alice?"], default_schema=schema)
    assert json.loads(questions) == [{"description": "Alice?", "gremlin": ""}]
    assert json.loads(example) == schema
    assert choose_schema_examples("[]", "{}", default_questions=["Alice?"], default_schema=schema) == ("[]", "{}")


def test_custom_schema_template_and_input_validation(schema):
    request = build_schema_prompt("Alice", ["Who?"], schema, "{raw_texts}|{query_examples}|{few_shot_schema}")
    assert request.startswith("- Alice|-")
    assert '"vertexlabels"' in request
    with pytest.raises(ValueError, match="only strings"):
        build_schema_prompt(["Alice", 1])
    with pytest.raises(ValueError, match="iterable of strings"):
        build_schema_prompt(None)


def test_default_graph_prompts_are_immutable_and_customization_is_local():
    defaults = GraphPrompts()
    chinese = GraphPrompts(extract=DEFAULT_EXTRACT_PROMPT_CN)
    assert "PRIMARY_KEY" in defaults.extract and "CUSTOMIZE_UUID" in defaults.review
    assert "entire replacement graph" in defaults.repair
    assert chinese.extract != defaults.extract
    assert GraphPrompts().extract == defaults.extract
    with pytest.raises(FrozenInstanceError):
        defaults.extract = "changed"


@pytest.mark.parametrize("name", ["extract", "review", "repair"])
def test_invalid_graph_prompt_values_fail_when_constructed(name):
    with pytest.raises(TypeError, match=name):
        GraphPrompts(**{name: None})
    assert getattr(GraphPrompts(**{name: ""}), name) == ""


def test_schema_generation_rejects_incompatible_model_before_consuming_input():
    def texts():
        pytest.fail("An incompatible model should fail before inputs are consumed")
        yield "source"

    class AsyncGenerate:
        async def generate(self, *, prompt):
            pytest.fail("The async generate must not be called by synchronous design_schema")

    with pytest.raises(TypeError, match="synchronous"):
        design_schema(texts(), model=AsyncGenerate())
    with pytest.raises(TypeError, match="agenerate"):
        asyncio.run(adesign_schema(texts(), model=FunctionModel(generate=lambda _: "{}")))
