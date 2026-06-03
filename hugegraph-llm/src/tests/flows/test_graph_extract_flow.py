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

import os
from pathlib import Path

SCHEMA = '{"vertices": [], "edges": []}'
TEXTS = ["Alice knows Bob."]
EXAMPLE_PROMPT = ""
EXTRACT_TYPE = "property_graph"


def load_flow_types():
    original_cwd = Path.cwd()
    os.chdir(Path(__file__).resolve().parents[3])

    try:
        from hugegraph_llm.flows.graph_extract import GraphExtractFlow
        from hugegraph_llm.state.ai_state import WkFlowInput, WkFlowState
    finally:
        os.chdir(original_cwd)

    return GraphExtractFlow, WkFlowInput, WkFlowState


def test_prepare_writes_requested_split_type():
    GraphExtractFlow, WkFlowInput, _ = load_flow_types()
    flow = GraphExtractFlow()
    prepared_input = WkFlowInput()

    flow.prepare(
        prepared_input,
        SCHEMA,
        TEXTS,
        EXAMPLE_PROMPT,
        EXTRACT_TYPE,
        split_type="paragraph",
    )

    assert prepared_input.split_type == "paragraph"


def test_build_flow_writes_requested_split_type_to_workflow_input():
    GraphExtractFlow, _, _ = load_flow_types()
    flow = GraphExtractFlow()

    pipeline = flow.build_flow(
        SCHEMA,
        TEXTS,
        EXAMPLE_PROMPT,
        EXTRACT_TYPE,
        split_type="paragraph",
    )

    wkflow_input = pipeline.getGParamWithNoEmpty("wkflow_input")
    assert wkflow_input.split_type == "paragraph"


def test_build_flow_defaults_to_document_split_type_for_existing_callers():
    GraphExtractFlow, _, _ = load_flow_types()
    flow = GraphExtractFlow()

    pipeline = flow.build_flow(SCHEMA, TEXTS, EXAMPLE_PROMPT, EXTRACT_TYPE)

    wkflow_input = pipeline.getGParamWithNoEmpty("wkflow_input")
    assert wkflow_input.split_type == "document"


def test_workflow_state_setup_clears_graph_extract_result_fields():
    _, _, WkFlowState = load_flow_types()
    state = WkFlowState()
    state.vertices = [{"id": "old"}]
    state.edges = [{"id": "old-edge"}]
    state.triples = [("old", "rel", "value")]
    state.chunks = ["old chunk"]
    state.call_count = 10

    status = state.setup()

    assert not status.isErr()
    assert state.vertices is None
    assert state.edges is None
    assert state.triples is None
    assert state.chunks is None
    assert state.call_count is None
