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
import logging
from collections.abc import AsyncGenerator, Callable, Generator
from typing import Any

import httpx
import ollama
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from hugegraph_llm_sdk.errors import LLMOutputTruncatedError
from hugegraph_llm_sdk.providers._diagnostics import token_usage

log = logging.getLogger(__name__)


class OllamaClient:
    """LLM wrapper should take in a prompt and return a string."""

    def __init__(
        self, model: str, host: str = "127.0.0.1", port: int = 11434, *, raise_on_truncation: bool = True, **kwargs
    ):
        self.model = model
        self.raise_on_truncation = raise_on_truncation
        self.client = ollama.Client(host=f"http://{host}:{port}", **kwargs)
        self.async_client = ollama.AsyncClient(host=f"http://{host}:{port}", **kwargs)

    def close(self) -> None:
        """Release the synchronous client; async callers should use aclose."""
        # Ollama 0.4 exposes no public close method; its transport is an httpx client.
        self.client._client.close()

    async def aclose(self) -> None:
        """Release both transports without blocking the caller's event loop."""
        try:
            await self.async_client._client.aclose()
        finally:
            await asyncio.to_thread(self.close)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type((ollama.ResponseError, httpx.ConnectError, httpx.TimeoutException)),
    )
    def generate(
        self,
        messages: list[dict[str, Any]] | None = None,
        prompt: str | None = None,
    ) -> str:
        """Generate a response to the query messages/prompt."""
        if messages is None:
            assert prompt is not None, "Messages or prompt must be provided."
            messages = [{"role": "user", "content": prompt}]
        try:
            response = self.client.chat(
                model=self.model,
                messages=messages,
            )
            if self.raise_on_truncation and response.get("done_reason") == "length":
                raise LLMOutputTruncatedError("done_reason=length")
            usage = token_usage(
                {"prompt_tokens": response["prompt_eval_count"], "completion_tokens": response["eval_count"]}
            )
            log.info("Token usage: %s", usage)
            return response["message"]["content"]
        except (ollama.ResponseError, httpx.ConnectError, httpx.TimeoutException) as e:
            log.error("LLM call failed (%s)", type(e).__name__)
            raise

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type((ollama.ResponseError, httpx.ConnectError, httpx.TimeoutException)),
    )
    async def agenerate(
        self,
        messages: list[dict[str, Any]] | None = None,
        prompt: str | None = None,
    ) -> str:
        """Generate a response to the query messages/prompt asynchronously."""
        if messages is None:
            assert prompt is not None, "Messages or prompt must be provided."
            messages = [{"role": "user", "content": prompt}]
        try:
            response = await self.async_client.chat(
                model=self.model,
                messages=messages,
            )
            if self.raise_on_truncation and response.get("done_reason") == "length":
                raise LLMOutputTruncatedError("done_reason=length")
            usage = token_usage(
                {"prompt_tokens": response["prompt_eval_count"], "completion_tokens": response["eval_count"]}
            )
            log.info("Token usage: %s", usage)
            return response["message"]["content"]
        except (ollama.ResponseError, httpx.ConnectError, httpx.TimeoutException) as e:
            log.error("LLM call failed (%s)", type(e).__name__)
            raise

    def generate_streaming(
        self,
        messages: list[dict[str, Any]] | None = None,
        prompt: str | None = None,
        on_token_callback: Callable | None = None,
    ) -> Generator[str, None, None]:
        """Stream response tokens one by one."""
        if messages is None:
            assert prompt is not None, "Messages or prompt must be provided."
            messages = [{"role": "user", "content": prompt}]

        for chunk in self.client.chat(model=self.model, messages=messages, stream=True):
            if self.raise_on_truncation and chunk.get("done_reason") == "length":
                raise LLMOutputTruncatedError("done_reason=length")
            if not chunk["message"]:
                log.debug("Received empty message in streaming chunk")
                continue
            token = chunk["message"]["content"]
            if on_token_callback:
                on_token_callback(token)
            yield token

    async def agenerate_streaming(
        self,
        messages: list[dict[str, Any]] | None = None,
        prompt: str | None = None,
        on_token_callback: Callable | None = None,
    ) -> AsyncGenerator[str, None]:
        """Stream response tokens one by one."""
        if messages is None:
            assert prompt is not None, "Messages or prompt must be provided."
            messages = [{"role": "user", "content": prompt}]

        try:
            async_generator = await self.async_client.chat(model=self.model, messages=messages, stream=True)
            async for chunk in async_generator:
                if self.raise_on_truncation and chunk.get("done_reason") == "length":
                    raise LLMOutputTruncatedError("done_reason=length")
                token = chunk.get("message", {}).get("content", "")
                if on_token_callback:
                    on_token_callback(token)
                yield token
        except (ollama.ResponseError, httpx.ConnectError, httpx.TimeoutException) as e:
            log.error("Async streaming LLM call failed (%s)", type(e).__name__)
            raise

    def num_tokens_from_string(
        self,
        string: str,
    ) -> int:
        """Given a string returns the number of tokens the given string consists of"""
        return len(string)

    def max_allowed_token_length(
        self,
    ) -> int:
        """Returns the maximum number of tokens the LLM can handle"""
        return 4096

    def get_llm_type(self) -> str:
        """Returns the type of the LLM"""
        return "ollama/local"
