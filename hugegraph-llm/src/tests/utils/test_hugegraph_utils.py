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

import httpx
import pytest

from hugegraph_llm.utils import hugegraph_utils as hu


@pytest.mark.asyncio
async def test_acheck_graph_db_connection_returns_true_on_200():
    response = MagicMock()
    response.status_code = 200
    client = MagicMock()
    client.get = AsyncMock(return_value=response)
    with patch("hugegraph_llm.utils.hugegraph_utils.runtime.get_http_client", return_value=client):
        ok = await hu.acheck_graph_db_connection("http://h:8080", "g", "u", "p", "")
    assert ok is True
    client.get.assert_awaited_once()
    args, _ = client.get.call_args
    assert args[0] == "http://h:8080/graphs/g/schema"


@pytest.mark.asyncio
async def test_acheck_graph_db_connection_uses_graphspace_when_set():
    response = MagicMock()
    response.status_code = 200
    client = MagicMock()
    client.get = AsyncMock(return_value=response)
    with patch("hugegraph_llm.utils.hugegraph_utils.runtime.get_http_client", return_value=client):
        await hu.acheck_graph_db_connection("http://h:8080", "g", "u", "p", "myspace")
    args, _ = client.get.call_args
    assert args[0] == "http://h:8080/graphspaces/myspace/graphs/g/schema"


@pytest.mark.asyncio
async def test_acheck_graph_db_connection_returns_false_on_request_error():
    client = MagicMock()
    client.get = AsyncMock(side_effect=httpx.ConnectError("boom"))
    with patch("hugegraph_llm.utils.hugegraph_utils.runtime.get_http_client", return_value=client):
        ok = await hu.acheck_graph_db_connection("http://h:8080", "g", "u", "p", "")
    assert ok is False


def test_check_graph_db_connection_sync_uses_oneshot_client():
    response = MagicMock()
    response.status_code = 200
    inst = MagicMock()
    inst.get.return_value = response
    inst.__enter__ = MagicMock(return_value=inst)
    inst.__exit__ = MagicMock(return_value=False)
    with patch("hugegraph_llm.utils.hugegraph_utils.httpx.Client", return_value=inst):
        ok = hu.check_graph_db_connection("http://h:8080", "g", "u", "p", "")
    assert ok is True


def test_run_gremlin_query_calls_pyhugeclient_directly():
    fake_gremlin = MagicMock()
    fake_gremlin.exec.return_value = {"data": [1, 2]}
    fake_client = MagicMock()
    fake_client.gremlin.return_value = fake_gremlin
    with patch("hugegraph_llm.utils.hugegraph_utils.get_hg_client", return_value=fake_client):
        out = hu.run_gremlin_query("g.V().limit(1)", fmt=False)
    assert out == {"data": [1, 2]}
    fake_gremlin.exec.assert_called_once_with("g.V().limit(1)")


@pytest.mark.asyncio
async def test_arun_gremlin_query_pushes_to_thread():
    fake_gremlin = MagicMock()
    fake_gremlin.exec.return_value = {"data": [42]}
    fake_client = MagicMock()
    fake_client.gremlin.return_value = fake_gremlin
    with patch("hugegraph_llm.utils.hugegraph_utils.get_hg_client", return_value=fake_client):
        out = await hu.arun_gremlin_query("g.V().count()", fmt=False)
    assert out == {"data": [42]}
