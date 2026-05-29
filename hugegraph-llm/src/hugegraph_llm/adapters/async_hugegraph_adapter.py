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

"""
AsyncHugeGraphAdapter — Phase 2 strategy: uniform `asyncio.to_thread` wrapper
around the sync `PyHugeClient`. The C++/requests-based pyhugegraph cannot be
made awaitable without rewriting hugegraph-python-client. Instead we keep the
sync client and push every call to the default thread executor, matching the
pipeline-level approach chosen by the P1-T0 spike (Plan b).

Phase 2 callers: HTTP routes that talk to HugeGraph *outside* the pycgraph
pipeline (e.g. graph metadata endpoints in Phase 3). Pipeline nodes that
already run via `await asyncio.to_thread(pipeline.run)` should keep calling
PyHugeClient synchronously — wrapping again here would only add a redundant
hop with no concurrency benefit.

httpx-direct REST access is deferred until pyhugegraph upstream provides a
native async surface.
"""

import asyncio
from typing import Any, Callable, Optional

from pyhugegraph.client import PyHugeClient

from hugegraph_llm.config import huge_settings


class AsyncHugeGraphAdapter:
    """Async facade over PyHugeClient via asyncio.to_thread."""

    def __init__(self, client_factory: Optional[Callable[[], PyHugeClient]] = None):
        # Lazy: defer client construction (and any IO it triggers) to first use.
        self._factory = client_factory or _default_client_factory
        self._client: Optional[PyHugeClient] = None
        # Guards lazy init against concurrent first-callers; without it a burst of
        # in-flight requests on cold start would each spawn a redundant factory()
        # in the executor and leak connections.
        self._lock = asyncio.Lock()

    async def _get_client(self) -> PyHugeClient:
        # Double-checked: the fast path stays lock-free once the client is set,
        # the lock only protects the one-shot construction.
        if self._client is None:
            async with self._lock:
                if self._client is None:
                    self._client = await asyncio.to_thread(self._factory)
        return self._client

    async def execute_gremlin(self, query: str) -> Any:
        client = await self._get_client()
        return await asyncio.to_thread(lambda: client.gremlin().exec(query))

    async def get_schema(self) -> Any:
        client = await self._get_client()
        return await asyncio.to_thread(lambda: client.schema().getSchema())

    async def query_vid(self, vid: str) -> Any:
        client = await self._get_client()
        return await asyncio.to_thread(lambda: client.graph().getVertexById(vid))

    async def call(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Generic escape hatch for long-tail PyHugeClient methods."""
        return await asyncio.to_thread(fn, *args, **kwargs)


def _default_client_factory() -> PyHugeClient:
    return PyHugeClient(
        url=huge_settings.graph_url,
        graph=huge_settings.graph_name,
        user=huge_settings.graph_user,
        pwd=huge_settings.graph_pwd,
        graphspace=huge_settings.graph_space,
    )
