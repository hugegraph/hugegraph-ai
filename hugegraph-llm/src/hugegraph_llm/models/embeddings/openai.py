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


import asyncio
import time
from typing import List, Optional

from openai import APIConnectionError, APITimeoutError, AsyncOpenAI, OpenAI, RateLimitError

from hugegraph_llm.models.embeddings.base import BaseEmbedding
from hugegraph_llm.utils.log import log


class OpenAIEmbedding(BaseEmbedding):
    def __init__(
        self,
        embedding_dimension: int = 1536,
        model_name: str = "text-embedding-3-small",
        api_key: Optional[str] = None,
        api_base: Optional[str] = None,
    ):
        api_key = api_key or ""
        # Use a generous timeout; local proxies (e.g. Clash) can be slow to
        # establish the HTTPS CONNECT tunnel for the async client.
        self.client = OpenAI(api_key=api_key, base_url=api_base, timeout=300)
        self.aclient = AsyncOpenAI(api_key=api_key, base_url=api_base, timeout=300)
        self.model = model_name
        self.embedding_dimension = embedding_dimension

    def get_embedding_dim(
        self,
    ) -> int:
        return self.embedding_dimension

    def get_text_embedding(self, text: str) -> List[float]:
        """Get embedding for a single text with retry."""
        response = self._embed_with_retry([text])
        return response.data[0].embedding

    @staticmethod
    def _truncate_texts(texts: List[str], max_tokens: int = 7000) -> List[str]:
        """Truncate texts to keep them under provider token limits.

        Providers such as Jina enforce a per-request token cap (8194 for
        jina-embeddings-v3).  A conservative character cap of ``4 * max_tokens``
        keeps us safely below the limit without needing a tokenizer.
        """
        max_chars = max_tokens * 4
        return [text[:max_chars] for text in texts]

    def get_texts_embeddings(self, texts: List[str], batch_size: int = 32) -> List[List[float]]:
        """Get embeddings for multiple texts with automatic batch splitting.

        This method efficiently processes multiple texts by splitting them into
        smaller batches to respect API rate limits and batch size constraints.
        """
        texts = self._truncate_texts(texts)
        all_embeddings = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            self._rate_limit_sleep(batch)
            response = self._embed_with_retry(batch)
            all_embeddings.extend([data.embedding for data in response.data])
        return all_embeddings

    async def async_get_texts_embeddings(self, texts: List[str], batch_size: int = 32) -> List[List[float]]:
        """Get embeddings for multiple texts with automatic batch splitting (async).

        This method should efficiently process multiple texts at once by leveraging
        the embedding model's batching capabilities, which is typically more efficient
        than processing texts individually.
        """
        texts = self._truncate_texts(texts)
        all_embeddings = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            await self._async_rate_limit_sleep(batch)
            response = await self._async_embed_with_retry(batch)
            all_embeddings.extend([data.embedding for data in response.data])
        return all_embeddings

    async def async_get_text_embedding(self, text: str) -> List[float]:
        response = await self.aclient.embeddings.create(input=[text], model=self.model)
        return response.data[0].embedding

    @staticmethod
    def _estimate_tokens(batch: List[str]) -> int:
        """Rough token estimate used for rate-limit pacing."""
        return max(1, sum(len(text) for text in batch) // 4)

    def _rate_limit_sleep(self, batch: List[str], target_tpm: int = 1_000_000) -> None:
        """Sleep to keep embedding requests under the provider's per-minute token cap."""
        tokens = self._estimate_tokens(batch)
        sleep_seconds = tokens / target_tpm * 60
        if sleep_seconds > 0:
            time.sleep(sleep_seconds)

    async def _async_rate_limit_sleep(self, batch: List[str], target_tpm: int = 1_000_000) -> None:
        tokens = self._estimate_tokens(batch)
        sleep_seconds = tokens / target_tpm * 60
        if sleep_seconds > 0:
            await asyncio.sleep(sleep_seconds)

    def _embed_with_retry(self, batch: List[str], max_retries: int = 5):
        last_exc = None
        for attempt in range(max_retries):
            try:
                return self.client.embeddings.create(input=batch, model=self.model)
            except (RateLimitError, APIConnectionError, APITimeoutError) as exc:
                last_exc = exc
                wait = min(2 ** attempt, 60)
                log.warning("Embedding request failed (attempt %d/%d): %s; retrying in %ds", attempt + 1, max_retries, exc, wait)
                time.sleep(wait)
        raise RuntimeError(f"Embedding failed after {max_retries} retries: {last_exc}")

    async def _async_embed_with_retry(self, batch: List[str], max_retries: int = 5):
        last_exc = None
        for attempt in range(max_retries):
            try:
                return await self.aclient.embeddings.create(input=batch, model=self.model)
            except (RateLimitError, APIConnectionError, APITimeoutError) as exc:
                last_exc = exc
                wait = min(2 ** attempt, 60)
                log.warning("Embedding request failed (attempt %d/%d): %s; retrying in %ds", attempt + 1, max_retries, exc, wait)
                await asyncio.sleep(wait)
        raise RuntimeError(f"Embedding failed after {max_retries} retries: {last_exc}")
