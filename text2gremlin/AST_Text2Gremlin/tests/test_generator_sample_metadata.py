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

# ruff: noqa: E402

import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from base.GremlinParse import Step, Traversal
from base.TraversalGenerator import GeneratedSample, TraversalGenerator


class _GremlinBase:
    def get_token_desc(self, name: str, *args) -> str:
        return name

    def get_schema_desc(self, name: str) -> str:
        return name


class _TerminalEnhancementController:
    max_total = {}

    def get_chain_category(self, step_count: int) -> str:
        return "short"

    def should_stop_generation(self, generated_count: int, category: str) -> bool:
        return False

    def should_apply_random_enhancement(self, is_terminal: bool, enhancement_count: int) -> bool:
        return is_terminal and enhancement_count == 0


class _MaxOneController(_TerminalEnhancementController):
    max_total = {"short": 1}

    def should_apply_random_enhancement(self, is_terminal: bool, enhancement_count: int) -> bool:
        return False


class _OrderedPairs:
    def __init__(self):
        self._pairs = []

    def add(self, pair):
        if pair not in self._pairs:
            self._pairs.append(pair)

    def clear(self):
        self._pairs.clear()

    def __iter__(self):
        return iter(self._pairs)

    def __len__(self):
        return len(self._pairs)


class _DuplicateQueryMaxLimitGenerator(TraversalGenerator):
    def __init__(self):
        super().__init__(
            schema=object(),
            recipe=_recipe(Step("V")),
            gremlin_base=_GremlinBase(),
            controller=_MaxOneController(),
        )
        self.generated_pairs = _OrderedPairs()

    def _recursive_generate(self, *args, **kwargs):
        self._emit_sample("g.V()", "prefix desc", "prefix", 1)
        self._emit_sample("g.V()", "complete desc", "complete", 1)


class _EmptyGenerator(TraversalGenerator):
    def __init__(self):
        super().__init__(
            schema=object(),
            recipe=_recipe(Step("V")),
            gremlin_base=_GremlinBase(),
            controller=None,
        )
        self.generate_calls = 0

    def generate(self) -> list[tuple[str, str]]:
        self.generate_calls += 1
        return super().generate()

    def _get_valid_options_for_step(self, *args, **kwargs) -> list[dict]:
        return []


def _recipe(*steps: Step) -> Traversal:
    traversal = Traversal()
    for step in steps:
        traversal.add_step(step)
    return traversal


def _generator(steps: list[Step], controller=None) -> TraversalGenerator:
    generator = TraversalGenerator(
        schema=object(),
        recipe=_recipe(*steps),
        gremlin_base=_GremlinBase(),
        controller=controller,
    )
    if controller is None:
        generator.controller = None
    return generator


def _payload_by_query(payloads: list[dict]) -> dict[str, dict]:
    return {payload["query"]: payload for payload in payloads}


def test_generated_sample_keeps_query_description_and_metadata():
    sample = GeneratedSample(
        query="g.V().hasLabel('person')",
        description="查询 person 顶点",
        sample_kind="prefix",
        recipe_step_count=3,
        emitted_step_count=2,
        top_level_step_count=2,
        has_nested_traversal=False,
    )

    payload = sample.to_dict()

    assert payload["query"] == "g.V().hasLabel('person')"
    assert payload["description"] == "查询 person 顶点"
    assert payload["metadata"]["sample_kind"] == "prefix"
    assert payload["metadata"]["recipe_step_count"] == 3
    assert payload["metadata"]["emitted_step_count"] == 2
    assert payload["metadata"]["top_level_step_count"] == 2
    assert payload["metadata"]["has_nested_traversal"] is False


def test_generate_keeps_tuple_return_and_generate_samples_metadata():
    generator = _generator([Step("V"), Step("count")])

    results = generator.generate()
    payloads = generator.generate_samples()
    payloads_by_query = _payload_by_query(payloads)

    assert isinstance(results, list)
    assert all(isinstance(pair, tuple) and len(pair) == 2 for pair in results)
    assert all(isinstance(query, str) and isinstance(desc, str) for query, desc in results)
    assert set(payloads_by_query) == {query for query, _desc in results}

    prefix_payload = payloads_by_query["g.V()"]
    complete_payload = payloads_by_query["g.V().count()"]

    assert prefix_payload["query"] == "g.V()"
    assert "description" in prefix_payload
    assert prefix_payload["metadata"] == {
        "sample_kind": "prefix",
        "recipe_step_count": 2,
        "emitted_step_count": 1,
        "top_level_step_count": 1,
        "has_nested_traversal": False,
    }
    assert complete_payload["metadata"] == {
        "sample_kind": "complete",
        "recipe_step_count": 2,
        "emitted_step_count": 2,
        "top_level_step_count": 2,
        "has_nested_traversal": False,
    }


def test_generate_samples_runs_generate_when_needed():
    generator = _generator([Step("V"), Step("count")])

    payloads = generator.generate_samples()

    assert {payload["query"] for payload in payloads} == {"g.V()", "g.V().count()"}


def test_generate_samples_descriptions_match_final_result_tuples_after_max_limit():
    generator = _DuplicateQueryMaxLimitGenerator()

    results = generator.generate()
    payloads = generator.generate_samples()

    assert results == [("g.V()", "prefix desc")]
    assert [(payload["query"], payload["description"]) for payload in payloads] == results
    assert payloads[0]["metadata"]["sample_kind"] == "complete"


def test_generate_samples_does_not_regenerate_empty_results():
    generator = _EmptyGenerator()

    assert generator.generate_samples() == []
    assert generator.generate_samples() == []
    assert generator.generate_calls == 1


def test_terminal_enhancement_path_records_enhancement_metadata():
    generator = _generator([Step("V")], controller=_TerminalEnhancementController())

    def _enhance(query, desc, current_label, current_type):
        return [(f"{query}.limit(1)", f"{desc}，限制 1 条")]

    generator._apply_random_enhancement = _enhance

    generator.generate()
    payloads_by_query = _payload_by_query(generator.generate_samples())

    assert payloads_by_query["g.V()"]["metadata"]["sample_kind"] == "complete"
    assert payloads_by_query["g.V().limit(1)"]["query"] == "g.V().limit(1)"
    assert payloads_by_query["g.V().limit(1)"]["description"].endswith("限制 1 条")
    assert payloads_by_query["g.V().limit(1)"]["metadata"] == {
        "sample_kind": "enhancement",
        "recipe_step_count": 1,
        "emitted_step_count": 1,
        "top_level_step_count": 2,
        "has_nested_traversal": False,
    }


def test_emit_sample_prioritizes_duplicate_query_without_changing_generated_pairs():
    generator = _generator([Step("V"), Step("filter")])
    query = "g.V().filter(__.out('knows'))"

    generator._emit_sample(query, "prefix desc", "prefix", 1)
    generator._emit_sample(query, "enhancement desc", "enhancement", 2)
    generator._emit_sample(query, "complete desc", "complete", 2)

    sample = generator.generated_samples[query]

    assert sample.sample_kind == "complete"
    assert sample.description == "complete desc"
    assert sample.recipe_step_count == 2
    assert sample.emitted_step_count == 2
    assert sample.top_level_step_count == 2
    assert sample.has_nested_traversal is True
    assert generator.generated_pairs == {
        (query, "prefix desc"),
        (query, "enhancement desc"),
        (query, "complete desc"),
    }
