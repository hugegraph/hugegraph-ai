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


@pytest.mark.asyncio
async def test_aget_rerank_lists_negative_top_n_raises(reranker, documents):
    """``top_n < 0`` 必须由 ``_validate`` 拦下，避免静默退化为空 list 或下游崩溃。"""
    with pytest.raises(ValueError):
        await reranker.aget_rerank_lists("q", documents, top_n=-1)


@pytest.mark.asyncio
async def test_aget_rerank_lists_top_n_exceeds_documents_raises(reranker, documents):
    """``top_n > len(documents)`` 必须拦下，避免被服务端 400 兜底掉。"""
    with pytest.raises(ValueError):
        await reranker.aget_rerank_lists("q", documents, top_n=len(documents) + 1)


def test_get_rerank_lists_sync_uses_oneshot_httpx_client(reranker, documents):
    """Sync path is now self-contained: builds its own httpx.Client (no main-loop
    bridging), so we patch the local `httpx.Client` import instead of runtime."""
    response = MagicMock()
    response.json.return_value = {"results": [{"index": 2, "relevance_score": 0.9}]}
    response.raise_for_status.return_value = None
    sync_client = MagicMock()
    sync_client.post.return_value = response
    sync_client.__enter__ = MagicMock(return_value=sync_client)
    sync_client.__exit__ = MagicMock(return_value=False)

    with patch("httpx.Client", return_value=sync_client) as client_cls:
        result = reranker.get_rerank_lists("q", documents, top_n=1)

    assert result == ["Paris is known as the City of Light."]
    client_cls.assert_called_once()
    sync_client.post.assert_called_once()
    args, kwargs = sync_client.post.call_args
    assert args[0] == "https://api.siliconflow.cn/v1/rerank"
    assert kwargs["json"]["top_n"] == 1
    assert kwargs["headers"]["authorization"].startswith("Bearer ")
