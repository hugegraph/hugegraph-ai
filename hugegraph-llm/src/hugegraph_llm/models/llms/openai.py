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

from typing import Optional

import openai as openai
import tiktoken as tiktoken
from hugegraph_llm_core.providers.openai import OpenAIClient as CoreOpenAIClient
from openai import AsyncOpenAI, OpenAI

from hugegraph_llm.models.llms.base import BaseLLM


class OpenAIClient(CoreOpenAIClient, BaseLLM):
    """Application compatibility wrapper preserving legacy defaults and SDK hooks."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_base: Optional[str] = None,
        model_name: str = "gpt-4.1-mini",
        max_tokens: Optional[int] = 8092,
        temperature: float = 0.01,
        raise_on_truncation: bool = False,
    ) -> None:
        super().__init__(
            api_key=api_key,
            api_base=api_base,
            model_name=model_name,
            max_tokens=max_tokens,
            temperature=temperature,
            raise_on_truncation=raise_on_truncation,
            client=OpenAI(api_key=api_key or "", base_url=api_base),
            async_client=AsyncOpenAI(api_key=api_key or "", base_url=api_base),
        )
