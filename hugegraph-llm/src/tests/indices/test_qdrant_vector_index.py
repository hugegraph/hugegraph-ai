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

import importlib
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest

pytestmark = pytest.mark.contract

MODULE_NAME = "hugegraph_llm.indices.vector_index.qdrant_vector_store"


@pytest.fixture
def qdrant_vector_store(monkeypatch):
    """Load the optional adapter without installing the Qdrant dependency."""
    qdrant_client = ModuleType("qdrant_client")
    qdrant_client.__path__ = []
    qdrant_client.QdrantClient = Mock
    qdrant_http = ModuleType("qdrant_client.http")
    qdrant_http.models = SimpleNamespace()
    qdrant_client.http = qdrant_http

    monkeypatch.setitem(sys.modules, "qdrant_client", qdrant_client)
    monkeypatch.setitem(sys.modules, "qdrant_client.http", qdrant_http)
    previous = sys.modules.pop(MODULE_NAME, None)
    try:
        yield importlib.import_module(MODULE_NAME)
    finally:
        sys.modules.pop(MODULE_NAME, None)
        if previous is not None:
            sys.modules[MODULE_NAME] = previous


def test_search_uses_qdrant_query_points_contract(qdrant_vector_store):
    client = Mock(spec_set=["query_points"])
    client.query_points.return_value = SimpleNamespace(
        points=[
            SimpleNamespace(score=0.95, payload={"property": "near"}),
            SimpleNamespace(score=0.05, payload={"property": "far"}),
            SimpleNamespace(score=0.99, payload=None),
        ]
    )
    index = qdrant_vector_store.QdrantVectorIndex.__new__(qdrant_vector_store.QdrantVectorIndex)
    index.client = client
    index.name = "hugegraph_llm_contract"

    assert index.search([0.1, 0.2], top_k=7, dis_threshold=0.9) == ["near"]
    client.query_points.assert_called_once_with(
        collection_name="hugegraph_llm_contract",
        query=[0.1, 0.2],
        limit=7,
    )
