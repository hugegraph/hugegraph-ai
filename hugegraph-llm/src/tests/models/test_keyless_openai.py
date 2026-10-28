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

import httpx
import pytest
from hugegraph_llm_sdk.providers.openai import OpenAIClient as SDKOpenAIClient

from hugegraph_llm.models.embeddings.openai import OpenAIEmbedding
from hugegraph_llm.models.llms.openai import OpenAIClient

pytestmark = pytest.mark.contract


@pytest.mark.parametrize("factory", [OpenAIClient, SDKOpenAIClient, OpenAIEmbedding])
@pytest.mark.parametrize("key", [None, "", "configured-key"])
def test_real_openai_clients_accept_keyless_endpoints(monkeypatch, factory, key):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    client = factory(api_key=key, api_base="http://local-model.test/v1")
    expected = key or "EMPTY"

    def endpoint(request):
        assert request.headers["authorization"] == f"Bearer {expected}"
        if request.url.path.endswith("embeddings"):
            return httpx.Response(
                200, json={"data": [{"embedding": [0.1, 0.2], "index": 0}], "model": "local", "object": "list"}
            )
        return httpx.Response(
            200,
            json={
                "id": "local",
                "model": "local",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
            },
        )

    client.client._client = httpx.Client(transport=httpx.MockTransport(endpoint))
    client.aclient._client = httpx.AsyncClient(transport=httpx.MockTransport(endpoint))
    try:
        if factory is OpenAIEmbedding:
            assert client.get_text_embedding("hello") == [0.1, 0.2]
            assert asyncio.run(client.async_get_texts_embeddings(["hello"])) == [[0.1, 0.2]]
        else:
            assert client.generate(prompt="hello") == "ok"
            assert asyncio.run(client.agenerate(prompt="hello")) == "ok"
    finally:
        client.client.close()
        asyncio.run(client.aclient.close())
