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

from hugegraph_llm.models.rerankers.cohere import CohereReranker


@pytest.fixture
def reranker():
    return CohereReranker(
        api_key="test_api_key",
        base_url="https://api.cohere.ai/v1/rerank",
        model="rerank-english-v2.0",
    )


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
    with patch("hugegraph_llm.models.rerankers.cohere.runtime.get_http_client", return_value=client):
        result = await reranker.aget_rerank_lists("What is the capital of France?", documents)

    assert len(result) == 3
    assert result[0] == "Paris is known as the City of Light."
    assert result[1] == "Paris is the capital of France."
    assert result[2] == "Berlin is the capital of Germany."

    client.post.assert_awaited_once()
    _, kwargs = client.post.call_args
    assert kwargs["json"]["query"] == "What is the capital of France?"
    assert kwargs["json"]["documents"] == documents
    assert kwargs["json"]["top_n"] == 3


@pytest.mark.asyncio
async def test_aget_rerank_lists_with_top_n(reranker, documents):
    client = _mock_http_client([2, 0])
    with patch("hugegraph_llm.models.rerankers.cohere.runtime.get_http_client", return_value=client):
        result = await reranker.aget_rerank_lists("q", documents, top_n=2)

    assert len(result) == 2
    assert result[0] == "Paris is known as the City of Light."
    _, kwargs = client.post.call_args
    assert kwargs["json"]["top_n"] == 2


@pytest.mark.asyncio
async def test_aget_rerank_lists_empty_documents(reranker):
    with pytest.raises(ValueError):
        await reranker.aget_rerank_lists("q", [], top_n=1)


@pytest.mark.asyncio
async def test_aget_rerank_lists_top_n_zero(reranker):
    result = await reranker.aget_rerank_lists("q", ["Paris is the capital of France."], top_n=0)
    assert result == []


def test_get_rerank_lists_sync_wrapper_calls_runtime(reranker, documents):
    """Sync wrapper bridges to async via runtime.run_async_from_sync."""
    expected = ["Paris is known as the City of Light."]
    with patch(
        "hugegraph_llm.models.rerankers.cohere.runtime.run_async_from_sync",
        return_value=expected,
    ) as bridge:
        result = reranker.get_rerank_lists("q", documents, top_n=1)
    assert result == expected
    bridge.assert_called_once()
