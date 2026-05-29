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

from unittest.mock import MagicMock

import pytest

from hugegraph_llm.adapters.async_hugegraph_adapter import AsyncHugeGraphAdapter


def _make_client(*, schema=None, gremlin_result=None, vertex=None):
    client = MagicMock()
    client.schema.return_value.getSchema.return_value = schema or {"vertexlabels": []}
    client.gremlin.return_value.exec.return_value = gremlin_result or {"data": []}
    client.graph.return_value.getVertexById.return_value = vertex or {"id": "v1"}
    return client


@pytest.fixture
def adapter_with_factory():
    holder: dict = {}

    def factory():
        client = _make_client(
            schema={"vertexlabels": [{"id": 1, "name": "Person"}]},
            gremlin_result={"data": [42]},
            vertex={"id": "v42"},
        )
        holder["calls"] = holder.get("calls", 0) + 1
        holder["client"] = client
        return client

    return AsyncHugeGraphAdapter(client_factory=factory), holder


@pytest.mark.asyncio
async def test_factory_called_lazily_on_first_use(adapter_with_factory):
    adapter, holder = adapter_with_factory
    assert "client" not in holder
    await adapter.execute_gremlin("g.V().count()")
    assert holder["calls"] == 1
    # second call reuses cached client
    await adapter.execute_gremlin("g.V().limit(1)")
    assert holder["calls"] == 1


@pytest.mark.asyncio
async def test_execute_gremlin(adapter_with_factory):
    adapter, _ = adapter_with_factory
    out = await adapter.execute_gremlin("g.V().count()")
    assert out == {"data": [42]}


@pytest.mark.asyncio
async def test_get_schema(adapter_with_factory):
    adapter, _ = adapter_with_factory
    out = await adapter.get_schema()
    assert out["vertexlabels"][0]["name"] == "Person"


@pytest.mark.asyncio
async def test_query_vid(adapter_with_factory):
    adapter, _ = adapter_with_factory
    out = await adapter.query_vid("v42")
    assert out["id"] == "v42"


@pytest.mark.asyncio
async def test_call_generic_escape_hatch(adapter_with_factory):
    adapter, _ = adapter_with_factory

    def custom(a, b):
        return a + b

    out = await adapter.call(custom, 3, 4)
    assert out == 7


@pytest.mark.asyncio
async def test_exception_propagates(adapter_with_factory):
    adapter, holder = adapter_with_factory
    await adapter._get_client()
    holder["client"].gremlin.return_value.exec.side_effect = RuntimeError("boom")
    with pytest.raises(RuntimeError, match="boom"):
        await adapter.execute_gremlin("g.V()")
