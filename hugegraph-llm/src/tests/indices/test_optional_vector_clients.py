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

pytestmark = pytest.mark.contract


def test_installed_milvus_client_constructs_adapter_schema():
    milvus = pytest.importorskip("pymilvus", reason="Install the vectordb extra")
    from hugegraph_llm.indices.vector_index.milvus_vector_store import MilvusVectorIndex

    schema = milvus.CollectionSchema(
        fields=[
            milvus.FieldSchema(name="id", dtype=milvus.DataType.INT64, is_primary=True),
            milvus.FieldSchema(name="embedding", dtype=milvus.DataType.FLOAT_VECTOR, dim=3),
        ]
    )
    assert schema.fields[1].params["dim"] == 3
    assert callable(MilvusVectorIndex.search)


def test_installed_qdrant_client_searches_real_local_storage(monkeypatch):
    qdrant = pytest.importorskip("qdrant_client", reason="Install the vectordb extra")
    from hugegraph_llm.indices.vector_index import qdrant_vector_store

    client = qdrant.QdrantClient(":memory:")
    monkeypatch.setattr(qdrant_vector_store, "QdrantClient", lambda **kwargs: client)
    try:
        index = qdrant_vector_store.QdrantVectorIndex("contract", "localhost", 6333, embed_dim=3)
        index.add([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], ["Alice", "Acme"])
        assert index.search([1.0, 0.0, 0.0], top_k=2, dis_threshold=0.2) == ["Alice"]
        assert index.remove(["Alice"]) == 1
        assert index.search([1.0, 0.0, 0.0], top_k=2, dis_threshold=0.2) == []
    finally:
        client.close()
