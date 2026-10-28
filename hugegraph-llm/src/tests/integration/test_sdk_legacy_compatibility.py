# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements. See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License. You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Exercise legacy workflows through the shared core with only model calls replaced."""

import json

import pytest

from hugegraph_llm.config import prompt, runtime_config_lock
from hugegraph_llm.document import schema_examples
from hugegraph_llm.extraction_runtime.review import ExtractionOptions
from hugegraph_llm.flows import FlowName
from hugegraph_llm.flows.scheduler import Scheduler
from hugegraph_llm.operators.llm_op.schema_build import SchemaBuilder

SCHEMA = {
    "vertexlabels": [
        {
            "id": 1,
            "name": "person",
            "id_strategy": "PRIMARY_KEY",
            "properties": ["name"],
            "primary_keys": ["name"],
            "nullable_keys": [],
        }
    ],
    "edgelabels": [],
    "propertykeys": [{"name": "name", "data_type": "TEXT", "cardinality": "SINGLE"}],
}
GRAPH = {"vertices": [{"id": "Alice", "label": "person", "properties": {"name": "Alice"}}], "edges": []}
PASS = {"decision": "pass", "issues": []}
FIX = {"decision": "fix", "issues": [{"path": "vertices", "message": "Check the name against the source"}]}


def test_legacy_reviewed_flow_snapshots_prompts_across_all_chunks(monkeypatch):
    monkeypatch.setattr(prompt, "review_graph_prompt", "REVIEW BEFORE")
    monkeypatch.setattr(prompt, "repair_graph_prompt", "REPAIR BEFORE")
    clients = []

    class Model:
        def __init__(self):
            self.prompts = []

        def generate(self, *, prompt):
            self.prompts.append(prompt)
            if len(clients) == 1 and len(self.prompts) == 1:
                # A settings edit during inference must apply only to the next batch.
                with runtime_config_lock:
                    from hugegraph_llm.config import prompt as app_prompt

                    app_prompt.review_graph_prompt = "REVIEW AFTER"
                    app_prompt.repair_graph_prompt = "REPAIR AFTER"
            return json.dumps([GRAPH, FIX, GRAPH, PASS][len(self.prompts) - 1])

    def create_model(_settings, *, limit_output, raise_on_truncation):
        assert limit_output is False
        assert raise_on_truncation is True
        model = Model()
        clients.append(model)
        return model

    monkeypatch.setattr("hugegraph_llm.nodes.llm_node.extract_info.get_chat_llm", create_model)
    scheduler = Scheduler()

    def extract():
        return json.loads(
            scheduler.schedule_flow(
                FlowName.GRAPH_EXTRACT,
                json.dumps(SCHEMA),
                ["Alice is named Alice.", "Alice is a person."],
                "EXTRACT PREFIX",
                "property_graph",
                review_options=ExtractionOptions(max_workers=1),
            )
        )

    result = extract()
    assert result["extraction_status"] == "succeeded"
    assert [chunk["status"] for chunk in result["chunk_results"]] == ["final", "final"]
    assert [chunk["llm_calls"] for chunk in result["chunk_results"]] == [4, 4]
    assert all(vertex["id"] == "1:Alice" for vertex in result["vertices"])
    assert len(clients) == 2
    for model in clients:
        assert model.prompts[0].startswith("EXTRACT PREFIX")
        assert model.prompts[1].startswith("REVIEW BEFORE")
        assert model.prompts[2].startswith("REPAIR BEFORE")
        assert model.prompts[3].startswith("REVIEW BEFORE")

    assert extract()["extraction_status"] == "succeeded"
    for model in clients[2:]:
        assert model.prompts[1].startswith("REVIEW AFTER")
        assert model.prompts[2].startswith("REPAIR AFTER")


def test_schema_examples_and_legacy_flow_share_core_design_logic(monkeypatch, tmp_path):
    resources = tmp_path / "prompt_examples"
    resources.mkdir()
    (resources / "query_examples.json").write_text('["Who is Alice?"]', encoding="utf-8")
    (resources / "schema_examples.json").write_text(json.dumps(SCHEMA), encoding="utf-8")
    questions = schema_examples.load_query_examples(
        resource_path=str(tmp_path), persisted="invalid JSON", language="CN"
    )
    example_schema = schema_examples.load_schema_fewshot_examples(resource_path=str(tmp_path))
    seen = []

    class Model:
        def generate(self, *, prompt):
            seen.append(prompt)
            return "```json\n" + json.dumps(SCHEMA) + "\n```"

    monkeypatch.setattr("hugegraph_llm.nodes.llm_node.schema_build.get_chat_llm", lambda _settings: Model())
    result = Scheduler().schedule_flow(FlowName.BUILD_SCHEMA, "Alice is a person.", questions, example_schema)
    assert isinstance(result, str)
    assert json.loads(result) == SCHEMA
    assert len(seen) == 1
    assert "Alice is a person." in seen[0]
    assert "Who is Alice?" in seen[0]
    assert '"vertexlabels"' in seen[0]


def test_legacy_schema_builder_keeps_dict_output_custom_prompt_and_parse_error():
    seen = []

    class Model:
        def generate(self, *, prompt):
            seen.append(prompt)
            return "Generated schema:\n```json\n" + json.dumps(SCHEMA) + "\n```"

    builder = SchemaBuilder(llm=Model(), schema_prompt="CUSTOM\n{raw_texts}\n{query_examples}\n{few_shot_schema}")
    result = builder.run({"raw_texts": ["Alice"], "query_examples": ["Who is Alice?"], "few_shot_schema": {}})
    assert isinstance(result, dict)
    assert result == SCHEMA
    assert seen[0].startswith("CUSTOM\n")
    assert "Who is Alice?" in seen[0]
    with pytest.raises(RuntimeError, match="Invalid JSON response"):
        builder._extract_schema("not JSON")
