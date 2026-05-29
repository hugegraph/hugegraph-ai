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

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hugegraph_llm.models.rerankers.siliconflow import SiliconReranker


@pytest.fixture
def reranker():
    return SiliconReranker(api_key="k", model="bge-reranker-v2-m3")


@pytest.fixture
def documents():
    return [
        "Paris is the capital of France.",
        "Berlin is the capital of Germany.",
        "Paris is known as the City of Light.",
    ]


def _mock_http_client(rank_indices):
    response = MagicMock()
    response.json.return_value = {"results": [{"index": i, "relevance_score": 1.0 - 0.1 * i} for i in rank_indices]}
    response.raise_for_status.return_value = None
    client = MagicMock()
    client.post = AsyncMock(return_value=response)
    return client


@pytest.mark.asyncio
async def test_aget_rerank_lists(reranker, documents):
    client = _mock_http_client([2, 0, 1])
    with patch("hugegraph_llm.models.rerankers.siliconflow.runtime.get_http_client", return_value=client):
        result = await reranker.aget_rerank_lists("q", documents)

    assert result[0] == "Paris is known as the City of Light."
    client.post.assert_awaited_once()
    args, kwargs = client.post.call_args
    assert args[0] == "https://api.siliconflow.cn/v1/rerank"
    assert kwargs["json"]["top_n"] == 3


@pytest.mark.asyncio
async def test_aget_rerank_lists_with_top_n(reranker, documents):
    client = _mock_http_client([2, 0])
    with patch("hugegraph_llm.models.rerankers.siliconflow.runtime.get_http_client", return_value=client):
        result = await reranker.aget_rerank_lists("q", documents, top_n=2)
    assert len(result) == 2


@pytest.mark.asyncio
async def test_aget_rerank_lists_empty(reranker):
    with pytest.raises(ValueError):
        await reranker.aget_rerank_lists("q", [], top_n=1)


@pytest.mark.asyncio
async def test_aget_rerank_lists_top_n_zero(reranker):
    result = await reranker.aget_rerank_lists("q", ["x"], top_n=0)
    assert result == []


def test_get_rerank_lists_sync_wrapper(reranker, documents):
    with patch(
        "hugegraph_llm.models.rerankers.siliconflow.runtime.run_async_from_sync",
        return_value=["Paris is known as the City of Light."],
    ) as bridge:
        result = reranker.get_rerank_lists("q", documents, top_n=1)
    assert result == ["Paris is known as the City of Light."]
    bridge.assert_called_once()
