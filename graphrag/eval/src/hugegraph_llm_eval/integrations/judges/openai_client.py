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

"""Build a Judge backed by an OpenAI-compatible chat-completions endpoint."""

from typing import Protocol, cast

from hugegraph_llm_eval.evaluation.judges.base import JudgeDescriptor
from hugegraph_llm_eval.integrations.judges.openai_compatible import (
    OpenAICompatibleJudge,
    OpenAICompatiblePricing,
    OpenAICompatibleSettings,
    _configuration_payload,
)
from hugegraph_llm_eval.utils.clock import utc_now


class _ParseCompletions(Protocol):
    def parse(self, **kwargs: object) -> object: ...


class _Chat(Protocol):
    completions: _ParseCompletions


class _CompletionsClient(Protocol):
    chat: _Chat


class OpenAIClientTransport:
    """Adapt an ``openai.OpenAI`` client to the parse-transport protocol."""

    def __init__(self, client: _CompletionsClient) -> None:
        self._client = client

    def parse(self, **kwargs: object) -> object:
        return self._client.chat.completions.parse(**kwargs)


def openai_judge(
    *,
    model: str,
    api_key: str | None = None,
    base_url: str | None = None,
    provider: str = "openai",
    temperature: float = 0,
    seed: int | None = 42,
    max_tokens: int = 16_384,
    input_usd_per_million: float | None = None,
    output_usd_per_million: float | None = None,
    client: _CompletionsClient | None = None,
) -> OpenAICompatibleJudge:
    """Create a judge for OpenAI or any compatible endpoint.

    Without ``client``, the ``openai`` extra is imported lazily. Pricing stays
    unknown unless both rates are supplied, so budgets only apply when the caller
    can price the model.
    """
    settings = OpenAICompatibleSettings(temperature=temperature, seed=seed, max_tokens=max_tokens)
    pricing = OpenAICompatiblePricing(
        input_usd_per_million=input_usd_per_million,
        output_usd_per_million=output_usd_per_million,
    )
    descriptor = JudgeDescriptor.create(
        provider=provider,
        model=model,
        configuration=_configuration_payload(settings, pricing),
    )
    transport = OpenAIClientTransport(client if client is not None else _client(api_key=api_key, base_url=base_url))
    return OpenAICompatibleJudge(
        transport=transport,
        descriptor=descriptor,
        pricing=pricing,
        settings=settings,
        clock=utc_now,
    )


def _client(*, api_key: str | None, base_url: str | None) -> _CompletionsClient:
    try:
        from openai import OpenAI
    except ImportError as exc:
        msg = "openai_judge requires the 'openai' extra: pip install hugegraph-llm-eval[openai]"
        raise ImportError(msg) from exc
    return cast(_CompletionsClient, OpenAI(api_key=api_key, base_url=base_url, max_retries=0))
