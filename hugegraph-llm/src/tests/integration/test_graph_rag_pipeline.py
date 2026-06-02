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

import pytest

pytestmark = [pytest.mark.smoke, pytest.mark.integration]


def test_vector_only_rag_flow_builds_production_pipeline():
    from hugegraph_llm.flows.rag_flow_vector_only import RAGVectorOnlyFlow

    pipeline = RAGVectorOnlyFlow().build_flow(
        query="Who created lop?",
        topk_return_results=2,
        vector_dis_threshold=0.8,
    )
    prepared = pipeline.getGParamWithNoEmpty("wkflow_input")
    dot = pipeline.dump()

    assert prepared.query == "Who created lop?"
    assert prepared.vector_search is True
    assert prepared.graph_search is False
    assert prepared.topk_return_results == 2
    assert prepared.vector_dis_threshold == 0.8
    assert 'label="only_vector"' in dot
    assert 'label="merge_two"' in dot
    assert 'label="vector"' in dot
