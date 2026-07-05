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

"""Tests for retrieval context adapter."""

import json

import pytest

from hugegraph_llm.benchmark.utils.retrieval_adapter import build_retrieval_sample_from_state

pytestmark = pytest.mark.unit


def test_adapter_extracts_vector_contexts():
    state = {
        "query": "What does Alice do?",
        "vector_result": ["Alice is an engineer.", "Alice works remotely."],
        "vector_only_answer": "Alice is an engineer.",
    }
    sample = build_retrieval_sample_from_state(state, mode="vector_only", sample_id="q1")
    assert sample["sample_id"] == "q1"
    assert sample["question"] == "What does Alice do?"
    assert sample["retrieved_contexts"] == ["Alice is an engineer.", "Alice works remotely."]
    assert sample["vector_only_answer"] == "Alice is an engineer."
    assert sample["raw_answer"] == ""


def test_adapter_extracts_graph_contexts():
    state = {
        "query": "Where does Alice work?",
        "graph_result": ["Alice--[works_at]-->TechCorp"],
        "graph_only_answer": "TechCorp",
    }
    sample = build_retrieval_sample_from_state(state, mode="graph_only")
    assert sample["retrieved_contexts"] == ["Alice--[works_at]-->TechCorp"]
    assert sample["graph_only_answer"] == "TechCorp"


def test_adapter_combines_vector_and_graph_contexts():
    state = {
        "query": "Who is Alice?",
        "vector_result": ["Alice is an engineer."],
        "graph_result": ["Alice--[knows]-->Bob"],
        "graph_vector_answer": "Alice is an engineer who knows Bob.",
    }
    sample = build_retrieval_sample_from_state(state, mode="graph_vector")
    assert sample["retrieved_contexts"] == ["Alice is an engineer.", "Alice--[knows]-->Bob"]
    assert sample["graph_vector_answer"] == "Alice is an engineer who knows Bob."


def test_adapter_raw_mode_has_no_contexts():
    state = {
        "query": "What is X?",
        "raw_answer": "I don't know.",
        "vector_result": ["should be ignored"],
    }
    sample = build_retrieval_sample_from_state(state, mode="raw")
    assert sample["retrieved_contexts"] == []
    assert sample["raw_answer"] == "I don't know."


def test_adapter_accepts_json_string():
    state = json.dumps({"query": "Q", "vector_result": ["ctx"], "vector_only_answer": "A"})
    sample = build_retrieval_sample_from_state(state, mode="vector_only", sample_id="json_q")
    assert sample["sample_id"] == "json_q"
    assert sample["retrieved_contexts"] == ["ctx"]


def test_adapter_uses_question_field_over_query():
    state = {"question": "Prefer this", "query": "Ignore this", "vector_result": ["ctx"]}
    sample = build_retrieval_sample_from_state(state, mode="vector_only")
    assert sample["question"] == "Prefer this"


def test_adapter_unknown_mode_raises():
    with pytest.raises(ValueError):
        build_retrieval_sample_from_state({"query": "Q"}, mode="unknown")


def test_adapter_coerces_non_string_context_items():
    state = {"query": "Q", "vector_result": [{"text": "obj"}]}
    sample = build_retrieval_sample_from_state(state, mode="vector_only")
    assert sample["retrieved_contexts"] == ["{'text': 'obj'}"]
