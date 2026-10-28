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

import ollama as ollama
from hugegraph_llm_sdk.providers.ollama import OllamaClient as CoreOllamaClient

from hugegraph_llm.models.llms.base import BaseLLM


class OllamaClient(CoreOllamaClient, BaseLLM):
    """Application compatibility wrapper preserving the legacy truncation policy."""

    def __init__(
        self, model: str, host: str = "127.0.0.1", port: int = 11434, *, raise_on_truncation: bool = False, **kwargs
    ):
        super().__init__(model=model, host=host, port=port, raise_on_truncation=raise_on_truncation, **kwargs)
